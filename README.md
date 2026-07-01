# circuit-skills

[Claude Code](https://claude.com/claude-code) skills for designing real electronics — from
topology to a fabbable board to a hero render — the code-driven, reproducible way. Skills that
compose across the flow: **simulate → lay out → fit the enclosure → render.**

## `circuit-sim` — simulate before you commit

Find the topology and pick parts with evidence, not guesses. Two passes from **one parametric
ngspice deck** (the source of truth): Falstad/CircuitJS1 for interactive intuition (its netlist is
*generated* from the deck so the toy and the rigorous sim never drift), then ngspice for exact
transient/AC, parametric sweeps, and data-driven part selection. For power converters, drivers,
resonant tanks, filters, oscillators, analog front-ends.

## `pcb-layout` — generate placement in code, finish routing in KiCad

The north star: **routing difficulty is set at placement time, and every autorouter is immature** —
so you design so routing is trivial and hand-finish the tail. tscircuit (React/TSX) generates a
placed board; KiCad routes. What's encoded here:

- **The repeatable place→route loop in one command** (`scripts/route.sh`): export placement →
  reconcile nets → keepout the board holes → **fast** Freerouting (capped, never spins) → inject the
  route into KiCad over the **IPC API** → `drc_check.py` triage. Iterate on *placement*, not the router.
- **Automate KiCad headless via the IPC API** (`kipy`) — add ground/power planes, inject a Freerouting
  SES, refill zones, save — all without GUI menus (the deprecated SWIG `ExportSpecctraDSN` is broken).
- **Net reconciliation** (`merge_nets.py`) — collapse the per-subcircuit net fragments tscircuit emits,
  so the modular flow gets a flat netlist and no false shorts.
- **Auto-keepouts** (`add_cutout_keepouts.py`) — detect interior board holes (windows, cutouts, screw
  holes) and stop the router crossing them.
- **Layer-stackup strategy** — 2-layer + pour for simple boards; 4-layer with real GND/PWR planes
  (planes are zones, route signals only) to make high-pin-count parts routable.
- **Placement heuristics + checks** — decoupling at its IC, connectors on edges, lock-vs-float anchors,
  fab DRC rulesets (JLCPCB default), courtyard + shorting triage, the board-outline rule.
- Plus the hard-won gotchas (copperpour/cutout export gaps, EPAD grounding, refdes collisions, …) so
  you don't re-derive them.

## `pcb-enclosure-fit` — co-design the board and its printed enclosure so they FIT

The seam between a KiCad board and build123d parts: export the routed board to 3D, co-register it with
the printed shell on a shared datum, render a fit-check, and gate placement on connector / cutout /
mounting-hole alignment (the enclosure openings are constraints on where parts go, not an afterthought).

## `pcb-3d-render` — turn a board into a 3D image

The visual layer on top of `pcb-layout` — the 3D model already exists, this skill lights and shoots it.
Two paths: a **native tscircuit snapshot** (`tsci snapshot --3d` — one command, the authentic viewer look,
and it also emits PCB + schematic SVGs) for a quick documentation image; or **GLB → headless Blender**
(`scripts/blender_panel.py`) for a ray-traced hero shot — studio-lit real PCBs, or emissive *glowing* LEDs
on a curved "flex" panel the flat viewer can't sell. Encodes the headless-Blender GPU recipe and the
gotchas that each eat an afternoon: the `LC_ALL=C` OCIO/AgX segfault (renders nothing, looks like it
started), Blender-5's removed compositor API, `head` SIGPIPE-killing a render, tscircuit's 256-part
layout-solver limit (pin `schX/schY`), and emissive-glow tuning.

## Install

Copy a skill into your skills directory:

```bash
cp -r pcb-layout ~/.claude/skills/      # user-wide
# or, per-project:
cp -r circuit-sim /path/to/project/.claude/skills/
```

Claude Code discovers it automatically. `pcb-layout` needs `tscircuit` (via `bun`), KiCad 9+ with the
IPC server enabled, `kipy` (`pip install kipy`), and a Freerouting CLI; `circuit-sim` needs `ngspice`;
`pcb-3d-render` needs `tscircuit` and/or Blender 3.x+ (a GPU for fast Cycles) + `trimesh`;
`pcb-enclosure-fit` needs `build123d` + Blender/OpenSCAD.
