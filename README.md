# circuit-skills

[Claude Code](https://claude.com/claude-code) skills for designing real electronics — from
topology to a fabbable board — the code-driven, reproducible way. Two skills that compose:
**simulate first, then lay out.**

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

## Install

Copy a skill into your skills directory:

```bash
cp -r pcb-layout ~/.claude/skills/      # user-wide
# or, per-project:
cp -r circuit-sim /path/to/project/.claude/skills/
```

Claude Code discovers it automatically. `pcb-layout` needs `tscircuit` (via `bun`), KiCad 9+ with the
IPC server enabled, `kipy` (`pip install kipy`), and a Freerouting CLI; `circuit-sim` needs `ngspice`.
