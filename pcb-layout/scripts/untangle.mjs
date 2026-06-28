#!/usr/bin/env node
// untangle.mjs — part-level ROTATION untangle: orient each part so the ratsnest stops crossing.
//
// The cheap pre-routing win the autorouter can't give you: with positions fixed (from your hand
// floorplan in placement/<variant>.json), try each part at 0/90/180/270 and keep the orientation
// that minimises its nets' wirelength — iterate to convergence. Points each part AT its neighbours,
// so traces stop knotting before you ever route. Power/ground nets (poured, high-fanout) are dropped
// so they don't drag everything to the board centre.
//
//   node scripts/untangle.mjs [variant=default] [--write] [--fanout 6]
//     reads dist/<base>/circuit.json (intrinsic pad geometry + nets) + placement/<variant>.json
//     (the hand-placed x/y) -> writes the improved `rot` back into placement/<variant>.json.
//
// Pure functions (padOffsets, netHPWL, bestRot, untangle) are exported for tests.
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const rot = (dx, dy, deg) => {                        // rotate a local offset by 0/90/180/270
  const r = ((deg % 360) + 360) % 360;
  if (r === 0) return [dx, dy];
  if (r === 90) return [-dy, dx];
  if (r === 180) return [-dx, -dy];
  return [dy, -dx];                                   // 270
};

// half-perimeter wirelength of one net given its pad coordinates
export const netHPWL = (pads) => {
  if (pads.length < 2) return 0;
  const xs = pads.map((p) => p[0]), ys = pads.map((p) => p[1]);
  return Math.max(...xs) - Math.min(...xs) + (Math.max(...ys) - Math.min(...ys));
};

// pad world position for a part at (cx,cy) rotated `deg`, from an intrinsic local offset
export const padAt = (cx, cy, off, deg) => { const [dx, dy] = rot(off[0], off[1], deg); return [cx + dx, cy + dy]; };

// total signal-net wirelength for a placement {ref -> {cx,cy,rot}} given parts (pad offsets+nets) and nets
export function totalHPWL(parts, nets, place) {
  let t = 0;
  for (const [net, members] of Object.entries(nets)) {
    const pads = members.map(({ ref, off }) => {
      const p = place[ref]; return padAt(p.cx, p.cy, off, p.rot);
    });
    t += netHPWL(pads);
  }
  return t;
}

const rectOverlap = (a, b) =>
  Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0])) * Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
function pointInPoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
// would a part at (cx,cy), size w×h, rotated `deg` stay in the outline AND off every cutout?
export function fitsRot(cx, cy, w, h, deg, poly, cuts) {
  const ww = deg % 180 ? h : w, hh = deg % 180 ? w : h;
  const box = [cx - ww / 2, cy - hh / 2, cx + ww / 2, cy + hh / 2];
  for (const cut of cuts) if (rectOverlap(box, cut) > 0) return false;
  if (poly && poly.length) {
    const [x0, y0, x1, y1] = box;
    for (const [px, py] of [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]) if (!pointInPoly(px, py, poly)) return false;
  }
  return true;
}

// best of 0/90/180/270 for one part (min wirelength), holding everyone else fixed and STAYING legal
export function bestRot(ref, parts, nets, place, geom = {}) {
  const part = parts[ref], touch = part.nets, { poly = [], cuts = [] } = geom;
  let best = place[ref].rot, bestC = Infinity;
  for (const deg of [0, 90, 180, 270]) {
    if (part.w && !fitsRot(place[ref].cx, place[ref].cy, part.w, part.h, deg, poly, cuts)) continue;  // gate
    place[ref].rot = deg;
    let c = 0;
    for (const net of touch) {
      const pads = nets[net].map(({ ref: r, off }) => { const p = place[r]; return padAt(p.cx, p.cy, off, p.rot); });
      c += netHPWL(pads);
    }
    if (c < bestC) { bestC = c; best = deg; }
  }
  place[ref].rot = best;
  return best;
}

// greedy sweeps until no part changes (or maxSweeps)
export function untangle(parts, nets, place, geom = {}, { maxSweeps = 12 } = {}) {
  const refs = Object.keys(parts);
  for (let s = 0; s < maxSweeps; s++) {
    let changed = 0;
    for (const ref of refs) { const before = place[ref].rot; if (bestRot(ref, parts, nets, place, geom) !== before) changed++; }
    if (!changed) return s + 1;
  }
  return maxSweeps;
}

// ---- extraction: intrinsic pad offsets (rotation-invariant) + nets, from circuit.json ----
export function extract(cj, fanout = 6) {
  const sName = {}; for (const e of cj) if (e.type === "source_component") sName[e.source_component_id] = e.name;
  const sNet = {}; for (const e of cj) if (e.type === "source_port") sNet[e.source_port_id] = e.subcircuit_connectivity_map_key;
  const comp = {}; for (const e of cj) if (e.type === "pcb_component") comp[e.pcb_component_id] = { ref: sName[e.source_component_id], cx: e.center.x, cy: e.center.y, rot: e.rotation || 0, w: e.width, h: e.height };
  const parts = {};                                   // ref -> {pads:[{off,net}], nets:Set}
  const netCount = {};
  for (const e of cj) {
    if (e.type !== "pcb_port") continue;
    const c = comp[e.pcb_component_id]; const net = sNet[e.source_port_id];
    if (!c || !c.ref || !net) continue;
    // un-rotate (port - center) by the part's CURRENT rotation -> intrinsic local offset
    const lx = e.x - c.cx, ly = e.y - c.cy, [ox, oy] = rot(lx, ly, -c.rot);
    (parts[c.ref] ||= { pads: [], nets: new Set(), w: c.w, h: c.h });
    parts[c.ref].pads.push({ off: [ox, oy], net });
    netCount[net] = (netCount[net] || 0) + 1;
  }
  const drop = new Set(Object.entries(netCount).filter(([, n]) => n > fanout).map(([k]) => k));  // power/ground
  const nets = {};
  for (const [ref, p] of Object.entries(parts)) {
    p.nets = new Set();
    for (const pad of p.pads) {
      if (drop.has(pad.net)) continue;
      (nets[pad.net] ||= []).push({ ref, off: pad.off });
      p.nets.add(pad.net);
    }
    p.nets = [...p.nets];
  }
  // initial placement seed from circuit.json (overridden by placement file in main)
  const seed = {}; for (const c of Object.values(comp)) if (c.ref) seed[c.ref] = { cx: c.cx, cy: c.cy, rot: c.rot };
  const board = cj.find((e) => e.type === "pcb_board") || {};
  const poly = (board.outline || []).map((p) => [p.x, p.y]);
  const cuts = cj.filter((e) => e.type === "pcb_cutout").map((c) =>
    c.shape === "circle"
      ? [c.center.x - c.radius, c.center.y - c.radius, c.center.x + c.radius, c.center.y + c.radius]
      : [c.center.x - c.width / 2, c.center.y - c.height / 2, c.center.x + c.width / 2, c.center.y + c.height / 2]);
  return { parts, nets, seed, dropped: drop.size, poly, cuts };
}

function main() {
  const args = process.argv.slice(2);
  const variant = args.find((a) => !a.startsWith("--")) || "default";
  const fi = args.indexOf("--fanout");
  const fanout = fi >= 0 ? +args[fi + 1] : 6;
  const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
  process.chdir(ROOT);
  execSync(`PATH="$HOME/.bun/bin:$PATH" ./node_modules/.bin/tsci build index.circuit.tsx --pcb-only`, { stdio: "ignore", timeout: 200000 });
  const cj = JSON.parse(readFileSync("dist/index/circuit.json", "utf8"));
  const { parts, nets, seed, dropped, poly, cuts } = extract(cj, fanout);

  const pf = `placement/${variant}.json`;
  const place = {};
  const saved = existsSync(pf) ? JSON.parse(readFileSync(pf, "utf8")) : {};
  for (const ref of Object.keys(parts)) {
    const s = saved[ref] || {};
    place[ref] = { cx: s.x ?? seed[ref].cx, cy: s.y ?? seed[ref].cy, rot: s.rot ?? seed[ref].rot ?? 0 };
  }
  const before = totalHPWL(parts, nets, place);
  const sweeps = untangle(parts, nets, place, { poly, cuts });
  const after = totalHPWL(parts, nets, place);
  const changed = Object.keys(parts).filter((r) => (saved[r]?.rot ?? seed[r].rot ?? 0) !== place[r].rot);
  console.log(`untangle '${variant}': ${Object.keys(parts).length} parts, ${Object.keys(nets).length} signal nets ` +
    `(${dropped} power/ground nets dropped, fanout>${fanout})`);
  console.log(`  signal wirelength ${before.toFixed(0)} -> ${after.toFixed(0)} mm ` +
    `(${(100 * (before - after) / (before || 1)).toFixed(0)}% shorter) in ${sweeps} sweeps; ${changed.length} parts rotated`);
  if (changed.length) console.log("  rotated: " + changed.map((r) => `${r}->${place[r].rot}°`).join(", "));

  if (args.includes("--write")) {
    const out = { ...saved };
    for (const ref of Object.keys(parts)) out[ref] = { ...(saved[ref] || {}), x: place[ref].cx, y: place[ref].cy, rot: place[ref].rot, side: saved[ref]?.side || "top" };
    writeFileSync(pf, JSON.stringify(out, null, 2));
    console.log(`  WROTE ${pf} — make place VARIANT=${variant} to see it (then route)`);
  } else console.log("  (dry run — pass --write to apply to the placement file)");
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main();
