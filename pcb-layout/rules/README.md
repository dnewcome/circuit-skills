# DRC rulesets

A board has to be legal for whoever fabs it. A **ruleset** here has two sides, because
generation and checking are different tools:

1. **Source side — `fab.tsx`** (tscircuit). Spread a preset into every `<board>` *and*
   `<subcircuit>` so the autorouter draws fab-legal **tracks**:
   ```tsx
   import { JLCPCB } from "../lib/fab"      // copy fab.tsx into your project's lib/
   <board {...JLCPCB} …>      <subcircuit {...JLCPCB} …>   // EACH block has its own autorouter
   ```
   ⚠ **The sequential-trace autorouter honors `minTraceWidth`/`defaultTraceWidth` but IGNORES the
   via-size props** — exported vias stay 0.3 mm pad / 0.2 mm drill no matter what. Fix vias on the
   KiCad side (below).

2. **Check side — KiCad.** Two steps:
   - **Board Setup ▸ Design Rules ▸ Constraints** + the **Default net class** — set the mins to the
     fab's capabilities (table below). This is the *functional loosen-to-spec* step (KiCad's defaults
     are often stricter than a fab needs, which is where most of the "hundreds of via violations"
     come from). Also set the net class **via 0.6 / 0.3**.
   - **`<fab>.kicad_dru`** (Board Setup ▸ Custom Rules ▸ paste) — adds rules where the fab is *stricter*
     than KiCad's defaults (edge clearance, hole-to-hole, annular). **Custom rules can only tighten,
     never loosen** — that's why the Constraints tab above is required too.
   - **Resize the existing vias** once: select all (Edit ▸ Select All Tracks & Vias) ▸ Properties ▸ set
     the fab via size. tscircuit's 0.2 mm-drill vias are below even JLC's 0.3 mm min, so this isn't a
     false positive — they genuinely must grow.

## Fab capability table (2-layer standard)

| | track / clearance | via dia / drill | annular | min hole | hole-to-hole | edge clr |
|---|---|---|---|---|---|---|
| **JLCPCB** (default) | 0.127 mm | 0.45 / 0.30 mm | 0.13 mm | 0.30 mm | 0.50 mm | 0.30 mm |
| **PCBWay** | 0.127 mm | 0.45 / 0.30 mm | 0.13 mm | 0.30 mm | 0.50 mm | 0.30 mm |
| **OSH Park** (6 mil) | 0.1524 mm | 0.70 / 0.33 mm | 0.1524 mm | 0.33 mm | 0.50 mm | 0.381 mm |

(Recommended *drawn* sizes, looser than the absolute min: track **0.2 mm**, via **0.6 / 0.3 mm**.)

## The default
**JLCPCB.** `module-scaffold.sh` stamps `<board {...JLCPCB}>`, and `lib/fab.tsx` exports `JLCPCB` first.
Swap by spreading a different preset (`{...PCBWAY}`, `{...OSHPARK}`) and loading that `.kicad_dru`.

## Adding a fab
1. Add a preset to `fab.tsx` (same 4 keys).
2. Add a `<fab>.kicad_dru` (copy `jlcpcb.kicad_dru`, edit the numbers + the Constraints comment block).
3. Add a row to the table above.

## Verify
`kicad-cli pcb drc <board>.kicad_pcb` after applying. Expect the via/track/clearance bucket to
collapse to ~0 once Constraints match the fab + vias are resized; what remains is the real
unconnected/shorting tail to route by hand.
