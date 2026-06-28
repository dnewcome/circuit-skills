---
name: pcb-layout
description: Design a fabbable PCB the code-driven way — JLCPCB-stocked parts, modular subcircuits, deterministic placement, and an honest routing strategy — then hand off the routing tail to KiCad. The north star is that ROUTING DIFFICULTY IS SET BY PLACEMENT and every autorouter is immature, so you design for trivial routing (modular blocks + ground pours + edge-aware + code-placed decoupling) and hand-finish the rest. Covers tscircuit (React/TSX) as the generator + KiCad as the finisher, part stock-checking, the gotchas that waste hours, and reusable placement helpers (Decap + pin-map generator). Pairs with the circuit-sim skill (simulate first, then lay out). Worked example: the sbs-synth project (RP2350 cap-touch synth — modules/, lib/place.tsx, PCB_WORKFLOW.md, TOOL_CHOICE.md).
argument-hint: [board to design + target fab (default JLCPCB) + any stock/size constraints]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, WebFetch
---

The north star: **routing difficulty is decided at placement time, and every autorouter is immature.**
So you don't hunt for a smart router — you **design so routing is trivial** (modular blocks, ground
pours, deliberate placement, code-placed decoupling) and **hand-finish the stubborn tail**. tscircuit's
real value is *code-driven generation and placement*, NOT its routing; KiCad's real value is *routing*.
Use each for its strength. (Simulate the circuit first with the **circuit-sim** skill; this skill starts
once the topology and values are fixed.)

## Tool choice (decide once)

- **Eagle is dead** — Autodesk sunset standalone Eagle (folded into subscription Fusion 360 Electronics).
  Don't start there.
- The real axis is **code-first (tscircuit)** vs **GUI (KiCad)**. They split on routing: tscircuit
  generates a placed, mostly-routed board from code; KiCad routes interactively and well.
- **Pick a path:**
  - *Plain KiCad* — if reliably finishing boards is the priority. Free, mature router, best JLC support.
  - *tscircuit-generate → KiCad-finish* — if AI/code-reproducible/**many-variants** is the priority.
    `tsci export -f kicad_pcb` → placement + pours + ratsnest → hand-route in KiCad. **One-way per board**
    (no clean round-trip back to tscircuit code).
- A prior project died on **Freerouting** (the autorouter), not KiCad — KiCad's *manual* routing is great.
  "Every autorouter is immature" ⇒ route by hand in a tool that's good at it. **BUT** Freerouting 2.x is
  worth trying as a *finisher on a well-placed board*: measured, it completed flexisette to **0 unrouted
  in ~5 s with 45° traces** where sequential-trace stalled at ~10. Its weakness is large/dense boards +
  trace quality — so it complements the "good placement → trivial routing" north star, it doesn't replace
  it. See [Finishing the routing tail](#finishing-the-routing-tail) → `scripts/freeroute.sh`.

## Setup (tscircuit)

```bash
curl -fsSL https://bun.sh/install | bash          # tsci needs bun (~/.bun/bin/bun)
npm install -D tscircuit @tscircuit/cli @types/react
export PATH="$HOME/.bun/bin:$PATH" && npx tsci init -y   # scaffolds + installs an AI skill at .claude/skills/tscircuit
```
`tsci init` drops an authoritative skill at `.claude/skills/tscircuit/` (SKILL/SYNTAX/elements/*) — read it.

## Workflow

1. **Stock-check parts first.** `tsci search --jlcpcb "<q>"` — read the stock number; <~200 is a supply
   risk for a board you'll reproduce. Swap now, not after layout. (Real swaps on sbs-synth: BS8116A-3
   touch IC had 25 in stock → MPR121; RP2354A had 184 → RP2350A + external W25Q16 flash.)
2. **Import real parts** — `tsci import "C<lcsc#>"` writes `imports/<Part>.tsx` with the true footprint +
   pin labels + JLC part number. Never hand-model a QFN.
3. **Author each functional block as its own module** (`modules/<name>.circuit.tsx`) — see Modular below.
4. **Validate connectivity** cheaply: `tsci build <f> --disable-pcb --schematic-svgs`; fix "missing
   trace"/"no ports" before any PCB work.
5. **Route each block in isolation** with `sequential-trace`; iterate placement until clean or a small tail.
6. **Compose** blocks as placed `<subcircuit>`s; wire only the inter-block buses at top level.
7. **Export** `tsci export -f kicad_pcb`, finish routing + DRC in KiCad, generate Gerbers/BOM/CPL.

## Modular vs non-modular (decide per board)

- **Non-modular (one flat board, no subcircuits)** — default for low/medium part counts. ONE net scope,
  so shared signals are naturally single nets (no fragmentation), and since Freerouting routes the whole
  board anyway, it's the simplest path. Use it unless the design is big/dense enough to choke the
  tscircuit PCB pipeline.
- **Modular (`<subcircuit>` blocks)** — for dense boards: a monolith (60-pin QFN + ~50 parts) **chokes
  the tscircuit PCB pipeline** (100% CPU for 10+ min, 0 traces). Blocks place + route independently. The
  cost: tscircuit scopes `net.X` PER subcircuit, so a signal shared across blocks exports as several net
  codes that KiCad flags as FALSE shorts — you MUST reconcile them after export (see below).

Each module exports a placeable block AND a standalone board:
```tsx
export const McuBlock = ({name="mcu", pcbX=0, pcbY=0}: any) => (
  <subcircuit name={name} pcbX={pcbX} pcbY={pcbY} autorouter="sequential-trace">
    {/* parts + internal traces + a pinrow breakout header + a bottom GND pour */}
  </subcircuit>)
export default () => (<board width="50mm" height="46mm"><McuBlock/></board>)   // standalone build target
```
Compose with top-level bus traces via qualified selectors; **account for each block's real extent** or
they overlap (sbs-synth's touch block was ~108 mm wide → its own bottom band):
```tsx
<board width="130mm" height="75mm" autorouter="sequential-trace">
  <TouchBlock name="touch" pcbX={0} pcbY={-21}/> <McuBlock name="mcu" pcbX={-2} pcbY={19}/> ...
  <trace from=".mcu .J_IO .SDA" to=".touch .J_TOUCH .SDA"/>   {/* buses only */}
</board>
```

**Reconcile cross-block nets (`scripts/merge_nets.py`) — the "overview pass that matches nets by name".**
tscircuit names a shared signal differently in each scope — `SDA`, `SDA`, `"J_OLED.SDA to net.SDA"`,
`SDA_source_net_8` — so after routing KiCad reports them as `shorting_items` (same copper, different net
names). `merge_nets.py` collapses every same-base-name net to ONE canonical net in the exported
kicad_pcb, BEFORE routing (a file transform — pads can't be re-netted over IPC). Name shared signals
consistently (`net.SDA`, `net.GND`, `net.BCK`) in every module — **chip pin AND breakout-header pin both
to the named net** — so they reconcile cleanly. On flexisette this turned 19 false shorts into 0.

## The routing recipe (what makes it route)

1. **Ground/power pours** — `<copperpour connectsTo="net.GND" layer="bottom"/>` removes 60-70% of nets.
   Prefer **per-block** pours; a board-level pour can *fight* bottom-layer signals.
2. **`autorouter="sequential-trace"`** on every board/subcircuit. The default **capacity-mesh fails at
   any size** ("AD ran out of iterations", 0 traces) and can hang. sequential-trace is dumb but
   *predictable* — routes fast or fails fast, never spins.
3. **Explicit `footprint` on EVERY part** incl. `<pinheader footprint="pinrow4">` and
   `<pushbutton footprint="pushbutton">`. The builtin `<connector standard="usb_c">` has no footprint →
   import a real USB-C part (e.g. TYPE-C-31-M-12, C165948).
4. **Declaration order matters** for the greedy router — declare the hardest nets first (e.g. inner QSPI
   pins) so they claim direct paths before outer pins block them.
5. **Stitch QFN center/thermal pads to the pour** with explicit `<via connectsTo="net.GND" .../>` inside
   the pad — the router won't.

**Ground truth is the log, not trace counts.** `"1 passed"` + a high pcb_trace count ≠ routed:
`grep -c 'Could not find a route' build.log`. On the exported KiCad board, the real check is
`kicad-cli pcb drc <f>.kicad_pcb` (counts unconnected items AND clearance/short violations).

## Placement is the whole game

This is where the time goes and where tools are worst (parts dumped at origin, decoupling orphaned).

- **Edge-aware placement (the 4× lever).** Put each support part on the QFN edge its signals exit. Look
  it up: `grep 'portHints=\["pin60"\]' imports/RP2350A.tsx` → x/y → which edge. On sbs-synth's RP2350A,
  moving the flash from *below* to *above-left* (where the QSPI pins are) went **16 → 3 unrouted**, same
  parts/router/nets.
- **Code-place decoupling — never by hand.** Ship `scripts/genpinmap.mjs` (parses `imports/*.tsx` →
  `lib/pinmap.json`: every pin label → footprint x/y) and `scripts/place.tsx` (the `Decap` helper):
  ```tsx
  <Decap name="C1" part="RP2350A" ic={U1} pin="IOVDD1" layer="bottom"/>
  <trace from="C1.pin1" to="net.V3V3"/><trace from="C1.pin2" to="net.GND"/>
  ```
  Places the cap at the real power-pin coordinate — zero hand-guessed numbers, reproducible across
  variants. **Default `layer="bottom"`** for dense QFNs: caps under the chip are co-located AND free the
  top layer for escape (measured: 6 caps top-side → 11 unrouted; same 6 bottom-side → 6).
- **Don't trust tscircuit's auto-layout.** `<group layoutMode="pack">` **stacked parts on the origin** in
  testing — immature. Use the code helper.
- **Clustering heuristic:** a 2-pin passive whose nets are only `{one IC pin, power/GND}` belongs to that
  IC → place adjacent. Captures ~all decoupling/pull-ups.
- **Floorplan by signal flow:** power → MCU → peripherals → connectors; pin connectors/jacks/mounting
  holes to board edges *first*. This is the only real eyeballing — ~5 coordinates.
  - **If the board goes in a printed/CNC enclosure, the shell openings constrain placement** — pin each
    connector to its shell-slot coordinate and the display to its window BEFORE the rest, then verify in
    3D. See the **pcb-enclosure-fit** skill (export board → register to the printed parts → render a
    fit-check → gate placement on cutout/connector/screw alignment).
- **Connectors + user controls live on EDGES, oriented outward.** A USB-C / barrel / jack must sit on
  the board edge with its mouth facing off-board (a connector floating mid-board or rotated inward is
  un-mateable — a common AI-placement bug). Buttons/switches the user presses go on an accessible edge.
  Place + orient these by hand first; they're the fixed reference the rest hangs off.
- **Lock the anchors, float the rest.** What the enclosure/mechanics fix in place — connectors, mounting
  holes, an edge button, a display — are ANCHORS: place them deliberately and don't let an autoplacer or
  sweep move them. Everything else (the MCU module, regulators, passives) is MOVABLE — that's what you
  iterate. State this split explicitly so a placement pass only nudges the floaters.
- **Communicating blocks belong on the same side.** Inter-block buses route *between* blocks; if two
  blocks that talk (MCU↔codec) sit on opposite sides of a big obstacle (a board cutout, a connector
  bank), the bus has to detour around it and unrouted spikes. Put talkers adjacent; keep cutouts/holes
  out of the bus channels (on flexisette, mcu-left ↔ audio-right across a hole-filled centre was the
  whole routing problem — a floorplan fix, not a router fix).
- **On a cutout-heavy outline, MAP THE CLEAR REGIONS FIRST.** Before placing, subtract the holes + the
  notch from the board and note what's left — usually a few bands/ends/strips (flexisette: a top band,
  two narrow end columns beside the reels, a thin strip below the holes/above the notch). Then fit each
  block to a region it actually *fits*. This is the difference between converging and thrashing.
- **Narrow a too-wide block to fit a narrow region** — don't fight a 33mm block into a 24mm column.
  Stack a chip's support parts *above/below* it instead of *beside* it (mcu went 33→21mm wide by moving
  the reset/boot passives above the WROOM), and reposition a long breakout header off the obstacle.
- **Drop redundant parts that hog edge real-estate.** On a tight board, question every connector/button:
  modular **breakout headers** are pointless once buses route chip-to-chip via reconciled named nets;
  **reset/boot buttons** are pointless with native-USB (esptool resets over USB-CDC). Removing
  `J_IO/J_I2S/J_PWR` + `SW_RST/SW_BOOT` freed ~40mm and took flexisette from 14 courtyard overlaps to 0.
- **Gate on the COURTYARD, not the eyeballed body size.** Module/IC keepouts are bigger than the part
  (the ESP32-S3-WROOM-1 antenna keepout extends well past the metal), so two parts that "look" clear
  still collide. `drc_check.py` courtyard is the truth; chase it, not your mental bbox.
- **The board-outline rule — `scripts/outline-check.mjs` (run it after every floorplan move).** tscircuit
  has **no keep-in constraint**: `pcbX/pcbY` is manual, so a block can land in a concave **notch**, off
  the edge, or inside a **`<cutout>`** and you won't see it — tscircuit emits `pcb_component_outside_
  board_error` but the build only prints a generic "Build completed with errors", and it does *not* flag
  parts sitting in a cutout. `outline-check` surfaces both (parses the built `circuit.json`) and exits
  nonzero. It's the placement analog of `routecheck`: nudge a block, re-run, drive the count to 0. (On a
  non-rectangular outline — a cassette, a notched enclosure — this catches the bug every time: e.g. a
  power block floor-planned into the bottom head-access notch read as 16 parts off-board.)
- **KiCad placement aids:** "Pack and Move Footprints", place-by-hierarchical-sheet, and the **Replicate
  Hierarchical Layout** plugin (lay out one repeated channel, replicate to all — ideal for key arrays +
  variants).

## The measured iteration loop (encode it; don't eyeball it)

**The full-board loop is ONE command: `scripts/route.sh`** — export placement → reconcile nets
(`merge_nets.py`) → keepout the board holes (`add_cutout_keepouts.py`) → **fast** Freerouting (capped) →
add the GND pour + inject the route into KiCad over IPC → `drc_check.py` triage. You read the summary,
nudge **placement** (in code, or by hand in KiCad), and re-run. The whole point is *fast iterations on
PLACEMENT*, not one long route:

- **Cap the router — don't let it grind.** A fast pass (`MP=12`) that leaves many unrouted is a
  *placement* signal: fix the layout, don't burn 10 minutes of ripup-retry hoping the router saves a bad
  floorplan. Freerouting will run hundreds of passes making zero progress — `freeroute.sh` caps
  `-mp`/`-oit` and guards a wall-clock timeout. Grind (`MP=100 OIT=20 bash scripts/route.sh`) is the LAST
  step, once placement is good — not the iteration step.
- **The measure is `drc_check.py`** — it sorts DRC into **PLACEMENT** (courtyard overlaps → fix pcbX/pcbY),
  **ROUTING** (real shorts between distinct nets, crossings, unconnected), **FALSE shorts** (unreconciled
  net fragments → run `merge_nets.py`), and **RULE/FAB/COSMETIC** (global via/clearance, silk). A clean
  placement = 0 courtyard overlaps; a routable placement = low unrouted on a FAST pass.
- **Placement has THREE gates — all separate from routing, all must pass:** (1) **`outline-check.mjs`**
  — every part INSIDE the outline (not in a notch, cutout, reel, or screw hole; tscircuit has no keep-in,
  so `pcbX/pcbY` can drop a part into a hole and only this catches it); (2) **`drc_check.py` courtyard**
  — no part-part overlaps; (3) **low unrouted** on a fast pass. Drive ALL THREE — optimising routability
  alone will happily shove a block into the head notch (it did, on flexisette).
- **⚠ Routing keepouts ≠ placement keep-in.** A DSN keepout (`add_cutout_keepouts.py`) stops *traces*
  crossing a hole — the router's job. It does NOTHING to stop a *part* being placed in the hole/notch.
  A part in a cutout is a PLACEMENT bug (`outline-check` flags it), **never** a Freerouting failure —
  the router only routes, it never moves parts.
- **Round-trip:** placement lives in code (`pcbX/pcbY`), so the loop is *edit code → `route.sh` → read
  DRC*. You can also nudge in KiCad; `route.sh` re-exports from code each run, so persist a KiCad nudge
  back into the source (or it's lost on the next export — tscircuit→KiCad is one-way).
- **Grind the gates IN ORDER: outline → courtyard → unrouted.** Don't chase routability past an invalid
  placement. Worked, on flexisette (cassette: OLED window + 2 reels + 4 screws + a bottom head-notch, all
  keep-out): **12 outline violations → 0** (map regions, narrow the mcu, drop the breakout headers) →
  **14 courtyard overlaps → 0** (drop reset/boot buttons, stack support above the WROOM, spread blocks) →
  **~1 unrouted** with every hole kept out — a fabbable, routable floorplan. ~8 measured iterations, each
  a `outline-check` + `drc_check` + a fast capped route. Pace it: outline-check is build-only (fast);
  only run the route once outline+courtyard are clean.

**Autoplace the BLOCKS — `scripts/autoplace.mjs` (the placement analog of the autorouter).** Placement
is an algorithm, not just vibes, and this is the one spot with no good open tool (KiCad's annealer is
weak; tscircuit's `layoutMode="pack"` stacks on the origin). The shipped placer reads the built
`circuit.json` (per-subcircuit block bboxes + cutouts + the outline polygon + inter-block connectivity
from the `subcircuit_connectivity_map_key`) and **simulated-anneals the block positions (+90° rotation)**
to minimise **HPWL** (inter-block Manhattan wirelength → communicating blocks sit close) under **hard
penalties for the three gates**: block-block overlap, block-on-cutout, and block-outside-outline
(point-in-polygon, so it respects the head-notch). Edge/connector blocks stay put with `--lock`.
```bash
node scripts/autoplace.mjs                 # suggest block pcbX/pcbY (+rot); dry run
node scripts/autoplace.mjs --scramble --write   # from random spreads, restarts, apply the best
```
It gets you a near-valid floorplan in seconds (HPWL-min, parts in-board); **always validate the winner
with `outline-check` + a fast route** (HPWL is only a proxy — the route is ground truth), and expect to
hand-finish the last courtyard overlap or two. The pure geometry/cost/anneal/extract functions are unit-
tested: `node --test tests/autoplace.test.mjs` (10 cases — overlap, point-in-poly incl. notch, cost
penalties, anneal-separates-overlap, lock, extraction). To go further: recursive min-cut bisection to
seed regions, then this anneal; or extend from block-level to per-part.

Placement → routing is also a **per-block loop** (isolate one block's routability before composing).
Make the number cheap to read and refine against it. Three bundled scripts (in `scripts/`) encode the loop; wire them
to Makefile targets (`module`, `routecheck`, `sweep`) and copy `scripts/place.tsx` + `genpinmap.mjs`
into `lib/` + `tools/`:

- **`module-scaffold.sh <name>`** — stamp `modules/<name>.circuit.tsx` with the canonical skeleton
  (`<subcircuit autorouter="sequential-trace">` + `J_<NAME>` breakout + bottom GND pour + standalone
  `<board>` export). Decomposition becomes mechanical instead of a fresh judgement each time.
- **`routecheck.sh [names…]`** — THE metric. Builds each block standalone under `timeout`, prints a
  table of **UNROUTED** (`grep -c 'Could not find a route'` on the build LOG) + **TIME** + **PASS**.
  Ground truth is the log, not "passed"/trace counts. Re-run after every placement change; watch the
  number fall. (`TIMEOUT=180 routecheck.sh` raises the per-block cap.)
- **`place-sweep.mjs <module> <ref> "x,y"…`** — semi-automates the edge-aware search: rewrites one
  part's `pcbX/pcbY`, rebuilds, counts unrouted per candidate, prints the winner, **restores the file**
  (you apply the winning coord deliberately). This is "move the flash to the QSPI edge: 16→3", scripted.

The loop in practice: `routecheck` for a baseline → read the unrouted *net names* (which edge does each
endpoint exit?) → `place-sweep` the offending part across a few edge-aware spots → apply the winner →
`routecheck` again. Stop at 0 or a small, known tail you hand-finish in KiCad. **Every change is
measured, so regressions show immediately** (a "fix" that takes a block 5→6 is caught on the next run).

Gotchas the loop itself taught (baked into the scripts):
- **Log to a FILE and grep it**, never capture `execSync` stdout — big builds overflow the default
  `maxBuffer` (truncates the route-failure tail → false 0) and a non-TTY can buffer differently.
- **Put `bun` on PATH via the child `env`, not a `PATH=… cmd` prefix** — `timeout <dur> PATH=… tsci`
  makes `timeout` exec `"PATH=…"` as the program (env assignments can't follow the command), so every
  build fails to launch → empty log → **false 0 unrouted**. Use `{env:{…PATH}}`.
- A generic `⚠ Build completed with errors` (tsci exits 0) is benign (unconnected NC / mounting pads) —
  PASS on `unrouted==0` + *specific* fatals (`does not have a footprint`, `is not exported`, …), not on
  the word "error".

Worked example: the **flexisette** PCB (`flexisette/pcb/` — cassette-shaped board: ESP32-S3 + SSD1306 +
MAX98357A + TP4056/LiPo). 4 blocks; `routecheck` took the power block 6→3 via two `place-sweep`s that
parked the USB-C CC resistors on their real pads; the residual tail (thermal-pad stitch, a cross-block
USB haul) is KiCad-finish work.

## Finishing the routing tail

`sequential-trace` clears ~80-90% then stalls on dense QFN escapes, ground returns, congested buses.
Two ways to close it:
- **Stay in tscircuit:** `<tracehint offset={{x,y}}/>` to nudge a net, or `<pcbtrace route={[...]}/>` for
  an explicit hand-route in code. Reproducible but tedious (coordinates, immature UX).
- **Hand off to KiCad (recommended for a real board):** `tsci export -f kicad_pcb` carries placement +
  pours + ~80% routing + ratsnest. **But the auto-routed traces are low quality** — expect shorts +
  crossings in the DRC; often it's faster to *keep the placement, rip up the routing, and reroute clean*
  in KiCad than to debug it. KiCad is then the source of truth (one-way).

  **Fixing a handful of residual shorts in the injected route — surgically, not by re-routing:**
  After IPC injection you typically have a *few* `shorting_items` where a Freerouting wire grazes a
  neighboring pad (its own clearance + the SES→KiCad coordinate rounding tips a 45° wire ~10-20 µm into
  an adjacent pad). **Do NOT try to fix these with a board-wide clearance bump and a re-route.** Measured
  on flexisette: a tight board converges at `clearance 150` (0.15 mm) but bumping the DSN default to 250,
  or even the *targeted* `(clearance N (type smd_wire))` to push wires off pads, strands **17-52 nets**
  (it never converges → no SES). Freerouting *does* honor `smd_wire`/`pin_wire` clearance types, but any
  board-wide pad clearance increase makes a dense board unroutable. Instead, **fix each short as an
  obstacle-aware text edit on the `.kicad_pcb`** and re-check with `kicad-cli pcb drc`:
  1. Get the exact short geometry from the DRC JSON (`items[].pos` + descriptions).
  2. **Read the REAL pad/via extents** from the footprints — don't guess. (flexisette gotcha: ESP32-S3
     WROOM castellated pads are **1.5 mm wide in X**, so a "nudge 0.25 mm off the pad center" still landed
     *inside* the pad. And the offending obstacle is often a **via** — Ø0.6 mm, 0.3 mm radius — not a pad.)
  3. Map *every* pad + same-layer copper in the local cluster, then reroute the one wire through a verified
     lane (e.g. thread VBAT through the 0.6 mm gap between a GND pad's edge and a VSYS via's clearance
     ring), keeping ≥ fab clearance (0.127 mm) to each. Reuse the segment UUIDs; preserve net numbers.
  4. Re-run `drc_check.py` after EACH edit — these are congested clusters and a fix often trades one short
     for another until you find the true lane (2-3 iterations is normal). This took flexisette 3 real
     shorts → 0 with placement/keepouts untouched.
- **Route the whole board with Freerouting** (a real maze router — ripup-retry, **45° traces** — that
  reached **0 unrouted, ~18 vias, ~5 s** on flexisette where sequential-trace stalls at ~10). Getting it
  back into KiCad was the catch; there are two ways, **prefer the first:**
  - **Pin Freerouting v2.1.0** (`freert`). Its `-mp`/`-oit` CLI flags and `router.max_passes` config are
    **ignored** — it runs to a 9999-pass default and only writes the `.ses` when it **converges** (so a
    routable board writes in seconds, but a board it can't fully route oscillates forever and writes
    NOTHING — measure such a placement from the LOG, not the `.ses`). **Don't upgrade to v2.2.x for
    tscircuit:** it needs Java 25 *and* its stricter parser rejects the tscircuit DSN (`padstack name
    expected at 'V3V3'`). Details in `freeroute.sh`'s header.
  - **IPC injection (headless, recommended)** — `tsci export -f specctra-dsn` → `freeroute.sh <tsx>` →
    `apply_ses_ipc.py <ses> --save --clear`. Injects straight into a running pcbnew; works with
    tscircuit's own DSN; no GUI menus. See *Automate KiCad headless via the IPC API* below — this is the
    flow that finally produced a routed `index.circuit.kicad_pcb` in place.
  - **Specctra GUI round-trip (fallback)** — only if you can't run the IPC server:
    1. **KiCad GUI:** `File ▸ Export ▸ Specctra DSN` → `board.dsn`.
    2. `bash scripts/freeroute.sh board.dsn` → `build/board.ses` (runs `freert` headless).
    3. **KiCad GUI:** `File ▸ Import ▸ Specctra Session` → `build/board.ses` (needs a KiCad-exported DSN).

  **Hard-won gotchas (do NOT re-derive these):**
  - **KiCad's SES import only accepts a session whose DSN KiCad ITSELF exported.** A SES routed from
    *tscircuit's* `tsci export -f specctra-dsn` has foreign net/component ids and **will not import** —
    GUI silently fails, headless `pcbnew.ImportSpecctraSES` throws. So `freeroute.sh <tsx>` is
    **completion-MEASUREMENT only** (good for comparing routers); `freeroute.sh <board.dsn>` is the real one.
  - **Freerouting writes an empty `(host_version )`** which KiCad's specctra parser rejects on import
    ("expecting a symbol or number" at that line). `freeroute.sh` auto-patches it (`sed` → a non-empty
    value); without that the SES won't even parse, regardless of which DSN it came from.
  - **NO automation of the DSN export — period. `pcbnew.ExportSpecctraDSN(board, file)` returns False
    EVERYWHERE:** standalone, under xvfb, AND from a real menu-triggered KiCad action plugin holding the
    correct frame board (verified: plugin logged `run fps=36 … export ok=False`). The SWIG binding is
    non-functional in KiCad 9.0.3 — only the GUI's own `File ▸ Export ▸ Specctra DSN` menu works.
    `kicad-cli` has no specctra command either. So a plugin/script CANNOT export the DSN; steps 1 & 3 are
    irreducibly manual GUI menu actions. Only the `freert` middle (step 2) scripts. Do not waste time on
    plugins, xvfb+xdotool (KiCad ignores synthetic menu input; bare xvfb has no window manager), or
    `wx.CallLater` auto-run (`GetBoard()` is empty off the menu path) — all dead ends, all tried.
    **Not a local fluke:** a KiCad forum thread reported `ExportSpecctraDSN()` "broken in nightly" back in
    **2020**, and the whole SWIG binding is **deprecated as of KiCad 9, removed in KiCad 11** (replaced by
    the **IPC API / `kicad-python`** — which IS the working automation path now; see *Automate KiCad
    headless via the IPC API* below, and just inject the SES with `apply_ses_ipc.py`). Reference KiCad+Freerouting
    automation projects (e.g. B73Labs/clock-skidl, the official freerouting KiCad guide) ALL do the DSN
    export by hand via the GUI menu. The manual export→`freert`→import is the community standard, not a
    workaround — don't keep hunting for a script that doesn't exist.
  - tscircuit's in-tool `autorouter="freerouting"` preset does NOT drive a local Freerouting — it falls
    back (~7 unrouted) and throws copper-pour errors. Don't use it.
  - Freerouting's weak spot is large/dense boards + trace quality, so it's a *finisher* once placement is
    good — it doesn't replace the "good placement → trivial routing" north star.
  - **`auto_cloud` IS hosted Freerouting** (`internal-freerouting.fly.dev`). When up, it routes inside
    tscircuit's pipeline, so `tsci export -f kicad_pcb` comes out routed with no Specctra hand-off at all —
    but it returned HTTP 500s in testing. Local `freert` is the dependable engine; the cloud is a bonus.
  - **Headless SES→board injection now WORKS — via IPC, not SWIG** (`scripts/apply_ses_ipc.py`; see the
    IPC section). The old SWIG `apply_ses.py` (kept only as a cautionary relic) plateaued at ~30 unrouted
    + V3V3↔GND shorts because it guessed nets *geometrically* (union-find) — **that** was the failure, not
    the pour. The IPC tool maps SES nets authoritatively against the live board (`Net-(REF-PadN)` → pad
    `(REF,N)`'s net; `NAME_source_net_N` → net `NAME`) and injects tracks/vias directly into a running
    pcbnew, so the GUI Specctra import is no longer required. The transform is the same verified one
    (`x_nm=u*100+1e8`, `y_nm=1e8−u*100`, `w_nm=w*100`).
  - **4-layer + Freerouting: the planes must be ZONES, not routed nets.** Letting the autorouter route
    GND/PWR as *tracks* is the classic 4-layer failure — it ignores the inner copper and snakes power
    everywhere. Route **signals only**; carry GND/PWR on inner-plane zones + stitch vias. See *Layer
    stackup strategy* below for how to do 4-layer right (it's the lever for high-pin-count parts).

## Automate KiCad headless via the IPC API (the right way)

The old SWIG `pcbnew` bindings are **deprecated (gone in KiCad 11) and `ExportSpecctraDSN` is broken
everywhere** (above), so driving routing from a Python *plugin* is a dead end. The **IPC API
(`kicad-python` / `kipy`, `pip install kipy`)** replaces it and actually works: it drives a *running*
pcbnew over a socket — headless, no menu clicks, and it can even inject a SES that KiCad's own GUI import
rejects. **This is now the primary automation path; the Specctra GUI round-trip is the fallback.**

**Setup (once):**
- `pip install kipy`
- Enable the server: `~/.config/kicad/<ver>/kicad_common.json` → `"api": { "enable_server": true }`.
- **pcbnew must be RUNNING with the board open** — the API needs the live app (socket
  `/tmp/kicad/api.sock`). Launch on a real/virtual display: `DISPLAY=:0 pcbnew board.kicad_pcb &`
  (use `run_in_background` so the agent shell doesn't reap it).
- Connect: `import kipy; b = kipy.KiCad().get_board()`.

**What it gives you that SWIG could not** (all on the live board, then `b.save()`):
`b.create_items([...])` (add `Track`/`Via`/`Zone`), `b.refill_zones()` (the pour refill every edit needs),
`b.remove_items([...])` (rip up for a clean reroute), `b.get_nets/get_pads/get_footprints/get_shapes/get_zones`.

**The shipped tools (`scripts/`, proven on flexisette — board routed in place, 0 unmapped nets):**
- **`add_plane.py <NET> <LAYER> [--replace] [--priority N]`** — add a ground/power plane zone. *Required*
  because tscircuit's `<copperpour>` is dropped on export (0 zones — see pitfalls). Builds a rectangle
  clipped to the board outline on fill, refills, saves, and **warns if it filled as >1 island** (a
  fragmented pour = orphaned ground).
- **`apply_ses_ipc.py <ses> --save [--clear]`** — inject a Freerouting SES into the live board: the
  headless replacement for `File ▸ Import ▸ Specctra Session`, and unlike the GUI it **accepts a SES
  routed from tscircuit's own DSN** (foreign ids and all). `--clear` rips up existing routing first.

**Fully-automated routing flow (no GUI menu clicks):**
1. `tsci export -f kicad_pcb` → placement; open it: `DISPLAY=:0 pcbnew index.circuit.kicad_pcb &`.
2. `python3 scripts/add_plane.py GND B.Cu --replace` (2-layer) — or inner GND/PWR planes (4-layer).
3. `tsci export -f specctra-dsn` → `bash scripts/freeroute.sh <tsx>` → `build/*.ses` (freert routes it).
4. `python3 scripts/apply_ses_ipc.py build/<board>.ses --save --clear` → tracks+vias injected, zones
   refilled, board saved **in place** — the routed `index.circuit.kicad_pcb` you actually wanted.
5. `kicad-cli pcb drc index.circuit.kicad_pcb` → triage the tail (DRC rulesets + pitfalls below).

**Why `apply_ses_ipc.py` is clean where the old SWIG `apply_ses.py` was not:**
- **Net assignment is AUTHORITATIVE, not geometric** (geometric/union-find is what caused the old
  V3V3↔GND short storms). SES names map directly: `Net-(REF-PadN)` → the net of kipy pad `(REF,N)`;
  `NAME_source_net_<n>` → net `NAME` (GND/V3V3/SCL/…). On flexisette: 0 unmapped of 45 net blocks.
- **Transform verified exact** (DSN units → KiCad nm): `x_nm = u*100 + 1e8`, `y_nm = 1e8 − u*100`,
  `w_nm = w*100` (resolution `um 10` = 10000 u/mm; +100 mm board offset; Specctra Y-up vs KiCad Y-down).
- **Via sizes come from the padstack name** (`Via[0-1]_600:300_um` → 0.6/0.3 mm). Forgetting this makes
  every via inherit KiCad's default → `via_diameter`/`annular_width` DRC storm (a real bug, now fixed in
  the tool). Tracks carry width from the SES `(path layer width …)`.

**Caveat:** the IPC server needs a live KiCad GUI process — launch it on a real/virtual display first;
after that there are zero menu clicks. (SWIG `ExportSpecctraDSN`, xvfb+xdotool menu poking, and
`wx.CallLater` plugin auto-run are all dead ends — see above, don't revisit.)

## Layer stackup strategy — the high-pin-count lever

Layer count is a *placement-difficulty* decision — the cheapest lever after placement itself:

- **2-layer + one ground pour** — default for low/medium density. Pour GND on **one** layer and bias
  signals onto the **other**. A full-board pour on a layer that *also* carries signals gets **chopped into
  islands** by those signals (measured: a B.Cu GND pour over B.Cu signals on flexisette filled as **3
  disconnected islands** → orphaned ground). `add_plane.py`'s island check catches this. Alternative:
  per-block pours (a board-spanning pour can fight bottom-layer signals — see pitfalls).
- **4-layer (Sig / GND / PWR / Sig)** — the lever that makes **high-pin-count parts routable** (dense
  QFN/BGA, ESP32-class modules, many buses). Dedicated **inner GND and PWR planes** mean both outer layers
  stay free for signal escape, and every power/ground pin reaches its plane with **one short stitch via**
  — no GND/PWR snaking as tracks (what congests and finally defeats 2-layer on dense parts).

  **Do it the right way (this is where 4-layer usually goes wrong):**
  1. Set the board to 4 copper layers (Board Setup ▸ Physical Stackup); assign **In1 = GND, In2 = PWR**.
  2. Add the planes as **zones**: `add_plane.py GND In1.Cu --replace` and `add_plane.py V3V3 In2.Cu
     --replace`. On a dedicated plane layer (no signals) they fill as **1 island** — the check confirms it.
  3. **Route SIGNALS ONLY** with Freerouting. **Never let it route GND/PWR as tracks** on 4-layer — it
     ignores the inner planes and snakes power everywhere (the classic failure). Exclude the plane nets.
  4. Stitch each power/ground pin (and QFN/EPAD thermal pads) to its plane with a via, then `refill_zones`.

  Net effect: a brutal QFN escape becomes "drop a via to the plane" + a short run on a clear outer layer.
  That is the entire reason to spend the extra two layers.

## DRC rulesets (default: JLCPCB)

Make the board legal for whoever fabs it. Rulesets live in `rules/` (**JLCPCB is the default**) and
have **two sides** — generation and checking are different tools:

- **Source side** — spread a `rules/fab.tsx` preset into every `<board>` AND `<subcircuit>` (each block
  has its own autorouter, so a board-level prop alone won't reach within-block geometry) so generated
  **tracks** are fab-legal: `import { JLCPCB } from "../lib/fab"` → `<board {...JLCPCB}>` /
  `<subcircuit {...JLCPCB}>`. ⚠ the sequential-trace autorouter honors `minTraceWidth` but **ignores the
  via-size props** — vias export as 0.3/0.2 regardless, so fix vias KiCad-side.
- **Check side** — set **Board Setup ▸ Constraints** + the Default net class to the fab's mins (this is
  what *loosens* KiCad's stricter defaults — the source of most "hundreds of via violations"), load
  `rules/<fab>.kicad_dru` for the stricter-than-default rules, and **resize all vias** to the fab size
  (select all ▸ properties). tscircuit's 0.2 mm-drill vias are below JLC's 0.3 mm min — a real fix, not a
  false positive.

`rules/README.md` has the per-fab capability table (JLCPCB / PCBWay / OSH Park) and how to add a fab
(a `fab.tsx` preset + a `<fab>.kicad_dru` + a table row).

## Pitfalls (hard-won)

- **Monolith** → 100% CPU forever, 0 traces. Split into `<subcircuit>` blocks. Always cap builds with
  `timeout 120 ...` so a stall can't thrash the machine.
- **Default capacity-mesh router** fails/hangs at any size → `autorouter="sequential-trace"`.
- **"X does not have a footprint"** (fatal under sequential-trace) → footprint on every part incl.
  headers/buttons; import a real USB-C part (builtin `usb_c` has none).
- **`--disable-parts-engine`** is fast but strips `<connector standard="usb_c">` of its ports → use a real
  imported USB-C part so the block builds offline.
- **`tsci --help`/`check` print nothing** (TTY-gated) → use `tsci build` (writes `dist/.../circuit.json`,
  `pcb.svg`) and read those.
- **`pkill -f tsci` kills your own shell** (its cmdline contains "tsci") → match the exact subcommand /
  use stored PIDs. Killing the `timeout` wrapper leaves a **re-parented `bun`** running → `pkill -9 -f
  'bun .*tsci build'`.
- **Trace counts and "passed" lie** → `grep -c 'Could not find a route'`; on KiCad, `kicad-cli pcb drc`.
- **Copper pours — a recurring source of pain. Specifically:**
  - **tscircuit `<copperpour>` does NOT survive `tsci export -f kicad_pcb`.** The exported board has
    **zero zones** even though every module declares a pour (verify: `grep -c '(zone' board.kicad_pcb` →
    0). So a board you *think* has a ground plane has none, and every router is forced to snake GND as
    tracks — the dense/4-layer killer, and the real root cause of past "GND short storms." **Add the
    pour/plane KiCad-side** with `scripts/add_plane.py` (IPC); don't trust the source `<copperpour>`.
  - **A full-board pour on a layer that also carries signals fragments into islands.** Measured on
    flexisette: a B.Cu GND pour over B.Cu signals filled as **3 disconnected islands** → orphaned ground
    → false "unconnected"/short DRC. Bias signals off the pour layer (2-layer), use **per-block** pours,
    or move ground to a **dedicated inner plane** (4-layer — see Layer stackup strategy). `add_plane.py`
    warns when a plane fills as >1 island so you catch it immediately.
  - **Refill zones after ANY track edit.** Ripping/adding tracks (or a programmatic save) leaves zones
    unfilled → every pad returning through the pour reads "unconnected" in DRC. Headless via IPC:
    `b.refill_zones()` before `b.save()` (the shipped tools do this). GUI: `B`. Always DRC *after* refill.
  - **Headless SES injection IS now clean — via IPC, not SWIG.** The old `apply_ses.py` (SWIG) plateaued
    at ~30 unrouted + V3V3↔GND shorts because it guessed nets *geometrically*; that was the failure, not
    the pour. `apply_ses_ipc.py` maps nets authoritatively against the live board and injects directly —
    no GUI Specctra import required. (Note: since tscircuit's DSN has no pour either, Freerouting's SES
    carries full GND *tracks*; with a KiCad-side pour added too, those are redundant copper, never the
    sole ground path — so a missed GND stub can't orphan a pad.)
  - **Verify the pour is one unbroken island** that actually reaches every GND pad (thin necks and
    keepouts can orphan a region) — a filled-but-disconnected pour looks fine and routes nothing.
- **Interior board holes (window / reels / screw holes) get dropped, then routed across.** Two separate
  failures: (1) a board outline imported as a single outer ring **loses its interior holes** — recover
  them from the CAD source of truth (e.g. `panel._rings()` returns `ext` + `holes`) and re-add each as a
  `<cutout>` (rect / circle / polygon; tscircuit DOES export `<cutout>` to Edge.Cuts, as a polygon). (2)
  tscircuit's `<cutout>` is an Edge.Cuts hole but **NOT a routing keepout in the DSN**, so Freerouting
  routes traces straight across the window — run **`add_cutout_keepouts.py`** (auto-detects every closed
  Edge.Cuts loop inside the outer outline → per-layer DSN keepouts). ⚠ holes in the CENTRE split the
  board (see placement: communicating blocks on the same side).
- **Exported via geometry trips KiCad's default DRC** (via_diameter/drill/annular ×N) → one global
  design-rule fix, not N real errors.
- **Decoupling at the pins crowds QFN escape** → put it `layer="bottom"` under the chip.
- **Schematic symbols overlap** without `schX/schY`/`<schematicsection>` — cosmetic, fix late.
- **Reused module refdes collide on compose** → **duplicate reference designators** in the exported
  board (KiCad warns on open; breaks the fab BOM/CPL — designators must be unique). Modules that each
  name parts `U1`/`C1`/`R1` clash when composed. Give every instantiated part a GLOBALLY-unique refdes
  (sbs-synth did: mcu `U1/U2`, audio `U4`, power `U5`). Quick check headless:
  `python3 -c "import sys;sys.path.insert(0,'/usr/lib/python3/dist-packages');import pcbnew,collections;b=pcbnew.LoadBoard('x.kicad_pcb');print([r for r,n in collections.Counter(f.GetReference() for f in b.GetFootprints()).items() if n>1])"`.
  (Separately, tscircuit emits one benign 0-pad `tscircuit:Unknown` footprint with an empty ref per
  `<cutout>` — harmless, never in the BOM; ignore or strip post-export.)
- **Shared signals fragment into multiple nets → FALSE "shorting_items" after routing.** With modular
  breakout headers + top-level pin-to-pin buses (`<trace from=".mcu .J_IO .SDA" to=".display .J_OLED
  .SDA"/>`), tscircuit assigns a *different* net name on each side of the shared header pin: one signal
  ends up as e.g. `SDA`, `U1.IO8 to J_IO.SDA`, and `.mcu .J_IO .SDA to .display .J_OLED .SDA`. Once
  routed, KiCad sees same-signal copper under different net names and flags `shorting_items` (and false
  `unconnected`). On flexisette ~19 of 23 "shorts" were this (every I2C/I2S/USB/V3V3 bus). **The fix:
  drive shared signals/buses through explicit named nets** (`net.SDA`, `net.SCL`, `net.V3V3`) so each is
  ONE net end-to-end; reserve pin-to-pin `<trace>` for genuinely point-to-point links. To tell false
  from real: a real short pairs *distinct* signals (e.g. `VSYS`/`GND`, or a signal crossing a pad) — only
  a handful, and those are the finish-the-tail cases (move the part / reroute the offending track).
- **Thermal/EPAD pads import as a SPLIT grid — tie EVERY sub-pad to GND, not just the first.** A module
  or QFN exposed pad (e.g. ESP32-S3-WROOM-1 EPAD = pin 41, or a QFN center) comes in as several paste
  sub-pads (pin41, plus `pin42…49` etc.). Connecting only the named one (`U1.GND3`/`U1.pin41`) leaves the
  rest floating → "unconnected" in DRC and a poorly-grounded part. Trace `U1.pin42…pinN` to `net.GND`
  too (verify with the per-footprint pad-net dump). The router/pour then stitches vias down. (Unused
  GPIOs staying unconnected is fine — that's intentional.)
- Render SVG→PNG to actually see it: `convert -background black -density 170 dist/<...>/pcb.svg out.png`.

## Verify every board

- `grep -c 'Could not find a route'` per block = 0 (or a known, hand-routed tail).
- `kicad-cli pcb drc <f>.kicad_pcb` on the export: triage `unconnected_items` (route them) vs
  `tracks_crossing`/`shorting_items` (real — rip up & reroute) vs via-rule (global config).
- Decap caps actually land on their pins (check `pcb_component.center` vs `pinmap.json`).
- All assembled parts are JLCPCB-stocked; `imports/*` pin the LCSC numbers.

## File layout & helpers

```
imports/*.tsx          tsci-imported parts (footprint + pins + JLC #)
modules/*.circuit.tsx  one functional block each (subcircuit + standalone board)
index.circuit.tsx      composes the blocks
lib/pinmap.json        generated by tools/genpinmap.mjs (run after any tsci import)
lib/place.tsx          Decap + pinAt placement helpers
lib/fab.tsx            fab DRC presets (JLCPCB default) — spread into board+subcircuits
tools/genpinmap.mjs    imports/*.tsx -> lib/pinmap.json
scripts/route.sh           THE pipeline: export->merge_nets->keepouts->fast Freerouting->IPC inject->DRC
scripts/routecheck.sh      measured loop: unrouted + time per block
scripts/outline-check.mjs  board-outline rule: parts outside the outline / in a cutout
scripts/drc_check.py       triage DRC: PLACEMENT (courtyard) / ROUTING (shorts) / FALSE / RULE-COSMETIC
scripts/merge_nets.py      reconcile fragmented cross-subcircuit nets in the kicad_pcb (by name)
scripts/add_cutout_keepouts.py  auto-keepout every interior Edge.Cuts hole into the DSN
scripts/freeroute.sh       route with Freerouting, FAST/capped (MP=/OIT=/MAXT=); DSN -> .ses
scripts/add_plane.py       IPC: add a GND/PWR plane zone to the live board (copperpour doesn't export)
scripts/apply_ses_ipc.py   IPC: inject a Freerouting SES into the live board headless (the working path)
scripts/apply_ses.py       OBSOLETE SWIG relic (geometric net guess -> shorts); use apply_ses_ipc.py
scripts/module-scaffold.sh stamp a new subcircuit block (defaults to {...JLCPCB})
scripts/place-sweep.mjs    move a part across candidates, report unrouted each
scripts/autoplace.mjs      autoplacer: anneal block positions (HPWL + outline/cutout/courtyard gates)
tests/autoplace.test.mjs   unit tests for the autoplacer core (node --test tests/*.test.mjs)
rules/                 DRC rulesets: fab.tsx presets + <fab>.kicad_dru + README (JLCPCB default)
Makefile:  make dev | build | modules | outline | routecheck [MODS=…] | freeroute | sweep MOD= REF= POS= | module NAME= | render | export
```
Bundled and ready to copy into a project: `scripts/genpinmap.mjs` + `scripts/place.tsx` + `rules/fab.tsx`
(→ `tools/`+`lib/`), and `scripts/{routecheck,outline-check,freeroute,module-scaffold,place-sweep}` (→
`scripts/`, wired to the Makefile targets above). `rules/<fab>.kicad_dru` load into KiCad Board Setup ▸
Custom Rules. `freeroute.sh` needs a Freerouting CLI (`~/.local/bin/freert`, override `FREERT=`).
Run `tsci dev <f>` (https://localhost:3020) for the interactive viewer + the Gerber/BOM/PnP export UI.
