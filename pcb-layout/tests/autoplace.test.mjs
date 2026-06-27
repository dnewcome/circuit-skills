// Tests for the autoplacer core (geometry, cost, annealing, extraction).
//   node --test tests/   (or: make test)
import test from "node:test";
import assert from "node:assert/strict";
import { rectOverlap, pointInPoly, blockBox, totalCost, anneal, hpwlOf, extract } from "../scripts/autoplace.mjs";

// deterministic PRNG so the annealing test is reproducible
function mulberry32(a) {
  return function () {
    a |= 0; a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

test("rectOverlap: disjoint / touching / overlap / nested", () => {
  assert.equal(rectOverlap([0, 0, 2, 2], [3, 3, 5, 5]), 0); // disjoint
  assert.equal(rectOverlap([0, 0, 2, 2], [2, 0, 4, 2]), 0); // share an edge → 0
  assert.equal(rectOverlap([0, 0, 4, 4], [2, 2, 6, 6]), 4); // 2×2 overlap
  assert.equal(rectOverlap([0, 0, 10, 10], [2, 2, 4, 4]), 4); // fully inside → inner area
});

test("pointInPoly: square + a bottom-centre notch (the cassette case)", () => {
  const sq = [[0, 0], [10, 0], [10, 10], [0, 10]];
  assert.equal(pointInPoly(5, 5, sq), true);
  assert.equal(pointInPoly(15, 5, sq), false);
  // U-shape: a notch cut up from the bottom edge between x=4..6
  const notched = [[0, 0], [4, 0], [4, 5], [6, 5], [6, 0], [10, 0], [10, 10], [0, 10]];
  assert.equal(pointInPoly(5, 2, notched), false); // inside the notch → OFF the board
  assert.equal(pointInPoly(5, 8, notched), true);  // above the notch → on the board
  assert.equal(pointInPoly(2, 2, notched), true);  // left of the notch → on the board
});

test("blockBox: bbox + 90° rotation swaps w/h", () => {
  assert.deepEqual(blockBox({ cx: 0, cy: 0, w: 4, h: 2, rot: 0 }), [-2, -1, 2, 1]);
  assert.deepEqual(blockBox({ cx: 0, cy: 0, w: 4, h: 2, rot: 1 }), [-1, -2, 1, 2]);
});

test("totalCost: pure HPWL when the placement is valid", () => {
  const blocks = [{ name: "a", cx: 0, cy: 0, w: 2, h: 2, rot: 0 }, { name: "b", cx: 5, cy: 0, w: 2, h: 2, rot: 0 }];
  const byName = Object.fromEntries(blocks.map((b) => [b.name, b]));
  const env = { blocks, byName, edges: [{ a: "a", b: "b", w: 1 }], cuts: [], poly: [], bbox: [-50, -50, 50, 50], PEN: 1e4 };
  assert.equal(totalCost(env), 5);            // Manhattan 5, no penalties
  assert.equal(hpwlOf(byName, env.edges), 5);
});

test("totalCost: block-block overlap penalty", () => {
  const blocks = [{ name: "a", cx: 0, cy: 0, w: 4, h: 4, rot: 0 }, { name: "b", cx: 2, cy: 2, w: 4, h: 4, rot: 0 }];
  const byName = Object.fromEntries(blocks.map((b) => [b.name, b]));
  const env = { blocks, byName, edges: [], cuts: [], poly: [], bbox: [-50, -50, 50, 50], PEN: 1e4 };
  assert.equal(totalCost(env), 4 * 1e4);       // 2×2 overlap × PEN
});

test("totalCost: block-on-cutout penalty", () => {
  const blocks = [{ name: "a", cx: 0, cy: 0, w: 4, h: 4, rot: 0 }];
  const env = { blocks, byName: { a: blocks[0] }, edges: [], cuts: [[-1, -1, 1, 1]], poly: [], bbox: [-50, -50, 50, 50], PEN: 1e4 };
  assert.equal(totalCost(env), 4 * 1e4);       // block [-2,-2,2,2] ∩ cutout [-1,-1,1,1] = 4
});

test("totalCost: out-of-bounds penalty (no polygon → bbox mode)", () => {
  const blocks = [{ name: "a", cx: 9, cy: 0, w: 4, h: 4, rot: 0 }]; // sticks out past x=10 by 1
  const env = { blocks, byName: { a: blocks[0] }, edges: [], cuts: [], poly: [], bbox: [-10, -10, 10, 10], PEN: 1e4 };
  assert.equal(totalCost(env), 1 * 1e4);       // 1mm over the right edge × PEN
});

test("anneal: separates overlapping connected blocks (residual → 0)", () => {
  const rng = mulberry32(42);
  const blocks = [
    { name: "a", cx: 0, cy: 0, w: 3, h: 3, rot: 0, locked: false },
    { name: "b", cx: 0.5, cy: 0.5, w: 3, h: 3, rot: 0, locked: false },
  ];
  const byName = Object.fromEntries(blocks.map((b) => [b.name, b]));
  const env = { blocks, byName, edges: [{ a: "a", b: "b", w: 1 }], cuts: [], poly: [], bbox: [-15, -15, 15, 15], PEN: 1e4 };
  assert.ok(rectOverlap(blockBox(blocks[0]), blockBox(blocks[1])) > 0, "start overlapping");
  const best = anneal(env, { iters: 30000, rng });
  assert.equal(rectOverlap(blockBox(blocks[0]), blockBox(blocks[1])), 0, "no overlap after anneal");
  assert.ok(best < 200, `cost should be low (HPWL only), got ${best}`); // no penalty residual, blocks ~adjacent
});

test("anneal: respects a locked block", () => {
  const rng = mulberry32(7);
  const a = { name: "a", cx: -10, cy: 0, w: 2, h: 2, rot: 0, locked: true };
  const b = { name: "b", cx: 10, cy: 0, w: 2, h: 2, rot: 0, locked: false };
  const env = { blocks: [a, b], byName: { a, b }, edges: [{ a: "a", b: "b", w: 1 }], cuts: [], poly: [], bbox: [-20, -20, 20, 20], PEN: 1e4 };
  anneal(env, { iters: 20000, rng });
  assert.equal(a.cx, -10, "locked block must not move (x)");
  assert.equal(a.cy, 0, "locked block must not move (y)");
  assert.ok(Math.abs(b.cx - a.cx) < 6, "free block pulled next to the locked one");
});

test("extract: blocks / edges / cutouts / outline from a minimal circuit.json", () => {
  const cj = [
    { type: "source_group", is_subcircuit: true, subcircuit_id: "s0", name: "mcu" },
    { type: "source_group", is_subcircuit: true, subcircuit_id: "s1", name: "audio" },
    { type: "pcb_component", subcircuit_id: "s0", center: { x: 0, y: 0 }, width: 4, height: 4 },
    { type: "pcb_component", subcircuit_id: "s1", center: { x: 20, y: 0 }, width: 2, height: 2 },
    { type: "source_port", subcircuit_id: "s0", subcircuit_connectivity_map_key: "net_SDA" },
    { type: "source_port", subcircuit_id: "s1", subcircuit_connectivity_map_key: "net_SDA" },
    { type: "pcb_cutout", shape: "circle", center: { x: 5, y: 5 }, radius: 2 },
    { type: "pcb_board", outline: [{ x: -50, y: -30 }, { x: 50, y: -30 }, { x: 50, y: 30 }, { x: -50, y: 30 }] },
  ];
  const { blocks, edges, cuts, bbox } = extract(cj);
  assert.equal(blocks.length, 2);
  assert.deepEqual(blocks.map((b) => b.name).sort(), ["audio", "mcu"]);
  assert.equal(blocks.find((b) => b.name === "mcu").w, 4);
  assert.deepEqual(edges, [{ a: "audio", b: "mcu", w: 1 }]); // SDA spans both blocks
  assert.deepEqual(cuts, [[3, 3, 7, 7]]);                    // circle bbox
  assert.deepEqual(bbox, [-50, -30, 50, 30]);
});
