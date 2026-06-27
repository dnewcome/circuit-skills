#!/usr/bin/env node
// autoplace.mjs — block-level autoplacer for a modular tscircuit board.
//
// The placement analog of the autorouter (and the one place no good open tool exists). It positions
// the <subcircuit> BLOCKS into the board's clear regions by simulated annealing: minimise inter-block
// wirelength (HPWL) so communicating blocks sit close, with HARD penalties for the three placement
// gates — block-block overlap, block-on-cutout, and block-outside-outline (incl. the head-notch via
// point-in-polygon). Anchored/edge blocks (connectors) stay locked.
//
// Reads the built circuit.json (block bboxes + cutouts + outline + connectivity via the
// subcircuit_connectivity_map_key) and the current block pcbX/pcbY from the source, then prints the
// suggested pcbX/pcbY (+ pcbRotation) per block — and applies them with --write. ALWAYS validate the
// winner with outline-check + a fast route (the ground truth; HPWL is only a proxy).
//
//   node scripts/autoplace.mjs [circuit.tsx]
//     --write          rewrite the block pcbX/pcbY/pcbRotation in the source
//     --scramble       start from random spreads (escape a stuck layout); implies restarts
//     --lock a,b       keep these blocks fixed (e.g. an edge-connector block)
//     --iters N        annealing iterations per restart (default 60000)
//     --restarts N     random restarts, keep the best (default 8 with --scramble, 1 otherwise)
//
// The pure geometry/cost/anneal functions are EXPORTED for tests (see tests/autoplace.test.mjs).
import { readFileSync, writeFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

// ---------- pure, testable core ----------
export const rectOverlap = (a, b) =>
  Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) *
  Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));

export function pointInPoly(x, y, poly) {              // ray-cast
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export const blockBox = (b) => {                       // {cx,cy,w,h,rot} -> [x0,y0,x1,y1]
  const w = b.rot ? b.h : b.w, h = b.rot ? b.w : b.h;
  return [b.cx - w / 2, b.cy - h / 2, b.cx + w / 2, b.cy + h / 2];
};

// HPWL (inter-block Manhattan) + hard penalties (overlap, cutout, out-of-outline).
export function totalCost({ blocks, byName, edges, cuts, poly, bbox, PEN = 1e4 }) {
  let c = 0;
  for (const e of edges) { const a = byName[e.a], b = byName[e.b]; c += e.w * (Math.abs(a.cx - b.cx) + Math.abs(a.cy - b.cy)); }
  const cxm = (bbox[0] + bbox[2]) / 2, cym = (bbox[1] + bbox[3]) / 2;
  for (let i = 0; i < blocks.length; i++) {
    const bi = blockBox(blocks[i]);
    for (let j = i + 1; j < blocks.length; j++) c += PEN * rectOverlap(bi, blockBox(blocks[j]));
    for (const cut of cuts) c += PEN * rectOverlap(bi, cut);
    if (poly && poly.length) {
      const [x0, y0, x1, y1] = bi;
      for (const [px, py] of [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [(x0 + x1) / 2, y0], [(x0 + x1) / 2, y1]])
        if (!pointInPoly(px, py, poly)) c += PEN * (Math.abs(px - cxm) + Math.abs(py - cym) + 5);
    } else {
      c += PEN * (Math.max(0, bbox[0] - bi[0]) + Math.max(0, bi[2] - bbox[2]) + Math.max(0, bbox[1] - bi[1]) + Math.max(0, bi[3] - bbox[3]));
    }
  }
  return c;
}

// Simulated annealing over block positions (+90° rotation). Mutates blocks to the BEST state found.
// rng defaults to Math.random; pass a seeded one for deterministic tests.
export function anneal(env, { iters = 60000, T0 = 30, rng = Math.random } = {}) {
  const { blocks } = env;
  const movable = blocks.filter((b) => !b.locked);
  const cost = () => totalCost(env);
  let cur = cost(), best = cur, bestState = blocks.map((b) => ({ cx: b.cx, cy: b.cy, rot: b.rot }));
  for (let it = 0; it < iters && movable.length; it++) {
    const T = T0 * Math.pow(0.0005, it / iters);
    const b = movable[(rng() * movable.length) | 0];
    const save = { cx: b.cx, cy: b.cy, rot: b.rot };
    if (rng() < 0.12) b.rot ^= 1;
    else { const step = 2 + T; b.cx += (rng() - 0.5) * step * 2; b.cy += (rng() - 0.5) * step * 2; }
    const nc = cost(), d = nc - cur;
    if (d < 0 || rng() < Math.exp(-d / T)) { cur = nc; if (nc < best) { best = nc; bestState = blocks.map((q) => ({ cx: q.cx, cy: q.cy, rot: q.rot })); } }
    else Object.assign(b, save);
  }
  blocks.forEach((b, i) => Object.assign(b, bestState[i]));
  return best;
}

// HPWL alone (no penalties), for reporting.
export const hpwlOf = (byName, edges) =>
  edges.reduce((s, e) => s + e.w * (Math.abs(byName[e.a].cx - byName[e.b].cx) + Math.abs(byName[e.a].cy - byName[e.b].cy)), 0);

// ---------- extraction from circuit.json (exported for tests) ----------
export function extract(cj) {
  const groupName = {};
  for (const e of cj) if (e.type === "source_group" && e.is_subcircuit) groupName[e.subcircuit_id] = e.name;
  const acc = {};
  for (const e of cj) {
    if (e.type !== "pcb_component" || !e.subcircuit_id || !groupName[e.subcircuit_id]) continue;
    const b = (acc[e.subcircuit_id] ||= { name: groupName[e.subcircuit_id], x0: 1e9, y0: 1e9, x1: -1e9, y1: -1e9 });
    b.x0 = Math.min(b.x0, e.center.x - e.width / 2); b.x1 = Math.max(b.x1, e.center.x + e.width / 2);
    b.y0 = Math.min(b.y0, e.center.y - e.height / 2); b.y1 = Math.max(b.y1, e.center.y + e.height / 2);
  }
  const blocks = Object.values(acc).map((b) => ({
    name: b.name, w: b.x1 - b.x0, h: b.y1 - b.y0,
    cx: (b.x0 + b.x1) / 2, cy: (b.y0 + b.y1) / 2, bcx: (b.x0 + b.x1) / 2, bcy: (b.y0 + b.y1) / 2, rot: 0, locked: false,
  }));
  const netBlocks = {};
  for (const e of cj) {
    if (e.type !== "source_port" || !e.subcircuit_connectivity_map_key) continue;
    const nm = groupName[e.subcircuit_id]; if (!nm) continue;
    (netBlocks[e.subcircuit_connectivity_map_key] ||= new Set()).add(nm);
  }
  const ew = {};
  for (const set of Object.values(netBlocks)) {
    const a = [...set]; for (let i = 0; i < a.length; i++) for (let j = i + 1; j < a.length; j++) { const k = [a[i], a[j]].sort().join("|"); ew[k] = (ew[k] || 0) + 1; }
  }
  const edges = Object.entries(ew).map(([k, w]) => { const [a, b] = k.split("|"); return { a, b, w }; });
  const board = cj.find((e) => e.type === "pcb_board");
  const poly = (board.outline || []).map((p) => [p.x, p.y]);
  const bbox = poly.length
    ? [Math.min(...poly.map((p) => p[0])), Math.min(...poly.map((p) => p[1])), Math.max(...poly.map((p) => p[0])), Math.max(...poly.map((p) => p[1]))]
    : [-board.width / 2, -board.height / 2, board.width / 2, board.height / 2];
  const cuts = cj.filter((e) => e.type === "pcb_cutout").map((c) =>
    c.shape === "circle"
      ? [c.center.x - c.radius, c.center.y - c.radius, c.center.x + c.radius, c.center.y + c.radius]
      : [c.center.x - c.width / 2, c.center.y - c.height / 2, c.center.x + c.width / 2, c.center.y + c.height / 2]);
  return { blocks, edges, poly, bbox, cuts };
}

function main() {
  const args = process.argv.slice(2);
  const opt = (f, d) => (args.includes(f) ? args[args.indexOf(f) + 1] : d);
  const has = (f) => args.includes(f);
  const SRC = args.find((a) => a.endsWith(".tsx")) || "index.circuit.tsx";
  const ITERS = +opt("--iters", 60000), LOCK = new Set((opt("--lock", "") || "").split(",").filter(Boolean));
  const RESTARTS = +opt("--restarts", has("--scramble") ? 8 : 1);

  const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  process.chdir(ROOT);
  execSync(`PATH="$HOME/.bun/bin:$PATH" ./node_modules/.bin/tsci build ${SRC} --pcb-only`, { stdio: "ignore", timeout: 200000 });
  const base = SRC.replace(/\.circuit\.tsx$/, "").replace(/\.tsx$/, "");
  const cj = JSON.parse(readFileSync(`dist/${base}/circuit.json`, "utf8"));
  const { blocks, edges, poly, bbox, cuts } = extract(cj);
  for (const b of blocks) b.locked = LOCK.has(b.name);
  const byName = Object.fromEntries(blocks.map((b) => [b.name, b]));
  const env = { blocks, byName, edges, cuts, poly, bbox, PEN: 1e4 };

  let bestCost = Infinity, bestSnap = null;
  for (let r = 0; r < RESTARTS; r++) {
    if (has("--scramble")) for (const b of blocks) if (!b.locked) { b.cx = bbox[0] + Math.random() * (bbox[2] - bbox[0]); b.cy = bbox[1] + Math.random() * (bbox[3] - bbox[1]); b.rot = 0; }
    const c = anneal(env, { iters: ITERS });
    if (c < bestCost) { bestCost = c; bestSnap = blocks.map((b) => ({ cx: b.cx, cy: b.cy, rot: b.rot })); }
  }
  blocks.forEach((b, i) => Object.assign(b, bestSnap[i]));

  const hp = hpwlOf(byName, edges), viol = bestCost - hp;
  console.log(`autoplace: ${blocks.length} blocks, ${edges.length} inter-block edges, ${cuts.length} cutouts, ${RESTARTS} restart(s)`);
  console.log(`  HPWL=${hp.toFixed(0)}  hard-violation residual=${viol.toFixed(0)} ${viol < 1 ? "(clean ✓)" : "(courtyard not fully clear — more --restarts/--iters, or finish by hand)"}`);
  let src = readFileSync(SRC, "utf8");
  for (const b of blocks) {
    const dx = +(b.cx - b.bcx).toFixed(2), dy = +(b.cy - b.bcy).toFixed(2);
    const re = new RegExp(`(<\\w*Block\\b[^>]*name=["']${b.name}["'][^>]*?)pcbX=\\{(-?[\\d.]+)\\}\\s*pcbY=\\{(-?[\\d.]+)\\}([^>]*?)(\\spcbRotation=\\{\\d+\\})?(\\s*/?>)`);
    const m = src.match(re);
    if (!m) { console.log(`  ${b.name}: (not found in source; Δ(${dx},${dy}) rot=${b.rot ? 90 : 0})`); continue; }
    const nx = +(+m[2] + dx).toFixed(2), ny = +(+m[3] + dy).toFixed(2), nr = b.rot ? 90 : 0;
    console.log(`  ${b.name.padEnd(8)} pcbX={${nx}} pcbY={${ny}}${nr ? " pcbRotation={90}" : ""}`);
    src = src.replace(re, `$1pcbX={${nx}} pcbY={${ny}}$4${nr ? " pcbRotation={90}" : ""}$6`);
  }
  if (has("--write")) { writeFileSync(SRC, src); console.log("  WROTE — validate with outline-check + a fast route"); }
  else console.log("  (dry run — pass --write to apply, then validate)");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
