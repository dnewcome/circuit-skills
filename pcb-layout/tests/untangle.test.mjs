// tests for untangle.mjs — the part-level rotation untangle. Run: node --test tests/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { netHPWL, padAt, fitsRot, bestRot, untangle, totalHPWL, extract } from "../scripts/untangle.mjs";

test("netHPWL: <2 pads = 0; else half-perimeter of the bbox", () => {
  assert.equal(netHPWL([[3, 3]]), 0);
  assert.equal(netHPWL([[0, 0], [2, 5]]), 7);
  assert.equal(netHPWL([[0, 0], [2, 0], [2, 3]]), 5);
});

test("padAt: rotate a local offset about the part centre", () => {
  assert.deepEqual(padAt(10, 10, [1, 0], 0), [11, 10]);
  assert.deepEqual(padAt(10, 10, [1, 0], 90), [10, 11]);
  assert.deepEqual(padAt(10, 10, [1, 0], 180), [9, 10]);
  assert.deepEqual(padAt(10, 10, [1, 0], 270), [10, 9]);
});

test("fitsRot: gate rejects off-outline and cutout-overlapping orientations", () => {
  const poly = [[-3, -3], [3, -3], [3, 3], [-3, 3]];
  assert.ok(fitsRot(0, 0, 4, 2, 0, poly, []));            // 4x2 centred fits
  assert.ok(!fitsRot(2.5, 0, 4, 2, 0, poly, []));         // pushed right -> corner outside
  assert.ok(!fitsRot(0, 0, 2, 4, 0, poly, [[-0.5, -0.5, 0.5, 0.5]])); // overlaps a cutout
  assert.ok(fitsRot(0, 0, 4, 2, 90, poly, []));           // 90° swaps to 2x4 -> still fits
});

test("bestRot: picks the orientation that shortens the part's nets", () => {
  // part P pads: A at local (0,+1) -> net up (neighbor at 0,+5); B at (0,-1) -> net down (0,-5)
  const parts = { P: { w: 1, h: 2, nets: ["up", "down"] } };
  const nets = { up: [{ ref: "P", off: [0, 1] }, { ref: "U", off: [0, 0] }],
                 down: [{ ref: "P", off: [0, -1] }, { ref: "D", off: [0, 0] }] };
  const place = { P: { cx: 0, cy: 0, rot: 180 }, U: { cx: 0, cy: 5, rot: 0 }, D: { cx: 0, cy: -5, rot: 0 } };
  assert.equal(bestRot("P", parts, nets, place), 0);      // rot 0 keeps A up / B down -> shortest
});

test("bestRot: respects the gate — won't choose an illegal rotation", () => {
  const poly = [[-3, -3], [3, -3], [3, 3], [-3, 3]];       // 6x6 board
  const parts = { P: { w: 2, h: 5, nets: ["n"] } };        // tall part; 90° -> 5 wide, pokes out
  const nets = { n: [{ ref: "P", off: [1, 0] }, { ref: "Q", off: [0, 0] }] };
  const place = { P: { cx: 0, cy: 0, rot: 0 }, Q: { cx: 5, cy: 0, rot: 0 } };  // Q to the right wants 90°
  const r = bestRot("P", parts, nets, place, { poly, cuts: [] });
  assert.ok(r === 0 || r === 180, `gate should block 90/270 (5mm wide on a 6mm board), got ${r}`);
});

test("untangle: reduces total wirelength and converges", () => {
  const parts = { P: { w: 1, h: 2, nets: ["up", "down"] }, U: { w: 1, h: 1, nets: ["up"] }, D: { w: 1, h: 1, nets: ["down"] } };
  const nets = { up: [{ ref: "P", off: [0, 1] }, { ref: "U", off: [0, 0] }],
                 down: [{ ref: "P", off: [0, -1] }, { ref: "D", off: [0, 0] }] };
  const place = { P: { cx: 0, cy: 0, rot: 180 }, U: { cx: 0, cy: 5, rot: 0 }, D: { cx: 0, cy: -5, rot: 0 } };
  const before = totalHPWL(parts, nets, place);
  const sweeps = untangle(parts, nets, place);
  const after = totalHPWL(parts, nets, place);
  assert.ok(after < before, `wirelength should drop (${before} -> ${after})`);
  assert.ok(sweeps >= 1);
});

test("extract: builds pads+nets and drops high-fanout (power/ground) nets", () => {
  // 3 parts; net 'sig' on 2 pads (kept), net 'gnd' on 3 pads (dropped at fanout 2)
  const cj = [
    { type: "source_component", source_component_id: "s1", name: "R1" },
    { type: "source_component", source_component_id: "s2", name: "R2" },
    { type: "source_component", source_component_id: "s3", name: "R3" },
    { type: "pcb_component", pcb_component_id: "p1", source_component_id: "s1", center: { x: 0, y: 0 }, rotation: 0, width: 1, height: 0.5 },
    { type: "pcb_component", pcb_component_id: "p2", source_component_id: "s2", center: { x: 5, y: 0 }, rotation: 0, width: 1, height: 0.5 },
    { type: "pcb_component", pcb_component_id: "p3", source_component_id: "s3", center: { x: 0, y: 5 }, rotation: 0, width: 1, height: 0.5 },
    { type: "source_port", source_port_id: "sp1", subcircuit_connectivity_map_key: "sig" },
    { type: "source_port", source_port_id: "sp2", subcircuit_connectivity_map_key: "sig" },
    { type: "source_port", source_port_id: "sp3", subcircuit_connectivity_map_key: "gnd" },
    { type: "source_port", source_port_id: "sp4", subcircuit_connectivity_map_key: "gnd" },
    { type: "source_port", source_port_id: "sp5", subcircuit_connectivity_map_key: "gnd" },
    { type: "pcb_port", pcb_component_id: "p1", source_port_id: "sp1", x: 0.4, y: 0 },
    { type: "pcb_port", pcb_component_id: "p2", source_port_id: "sp2", x: 5.4, y: 0 },
    { type: "pcb_port", pcb_component_id: "p1", source_port_id: "sp3", x: -0.4, y: 0 },
    { type: "pcb_port", pcb_component_id: "p2", source_port_id: "sp4", x: 4.6, y: 0 },
    { type: "pcb_port", pcb_component_id: "p3", source_port_id: "sp5", x: 0, y: 4.6 },
    { type: "pcb_board", width: 20, height: 20, outline: [] },
  ];
  const { parts, nets, dropped } = extract(cj, 2);    // fanout 2 -> 'gnd' (3 pads) dropped, 'sig' kept
  assert.equal(dropped, 1);
  assert.ok(nets.sig && !nets.gnd);
  assert.equal(parts.R1.w, 1);                        // part dims captured for the gate
  assert.deepEqual(parts.R1.nets, ["sig"]);           // gnd filtered out of R1's nets
});
