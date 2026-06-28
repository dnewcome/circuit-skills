---
name: pcb-enclosure-fit
description: Co-design a PCB and its 3D-printed / CNC enclosure so they physically FIT — the seam between a KiCad board and build123d parts. Export the routed board to 3D, co-register it with the printed shell/frame/insert on a shared datum, render a fit-check, and treat connector / cutout / mounting-hole alignment as a PLACEMENT GATE (the enclosure openings are constraints on where parts go on the board). Use when you have BOTH a PCB and a printed/machined enclosure that must mate — connectors must reach their shell slots, a display must sit behind its window, screws must line up with bosses. The mechanical-fit bridge — NOT electrical assembly (BOM/CPL is a separate concern). Bridges [[pcb-layout]] (board generation) and [[build123d-machine]] (the printed-part assembly + mate conventions). Worked example: flexisette (a cassette-shaped board behind a printed cassette shell — OLED window, 2 reels, 4 screw holes, head-notch all shared between board cutouts and the shell).
argument-hint: [board.kicad_pcb + the enclosure parts (build123d/STEP/STL) they must fit]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

The north star: **a board and its enclosure are ONE design — connector, cutout, and screw
positions only exist correctly if they line up in 3D.** Params lie (a `SHELL_W=100.5` constant
won't stop you drawing a 102.2 mm board); the *rendered overlay* doesn't. So you bring the real
board into the real enclosure assembly, look at them together, and let the mechanical openings
**constrain PCB placement** — the same way the board outline does. This skill is the seam between
[[pcb-layout]] (generates the routed board) and [[build123d-machine]] (models the printed parts).

## When this fires

You have a PCB **and** a printed/CNC/laser enclosure that must mate, and at least one of:
- a connector (USB-C, jack, SD, header) that has to reach an opening in the shell,
- a display / LED / window the board must sit behind or shine through,
- mounting holes that must hit bosses/standoffs,
- a board outline that IS a visible product face (so its shape + cutouts matter).

If the board lives in a generic off-the-shelf box, you don't need this — a datasheet keepout does.

## The loop (run after every placement/route pass)

1. **Export the board to 3D** — `kicad-cli pcb export step --subst-models --no-dnp -o board.step b.kicad_pcb`.
   Carries the **outline + every cutout + drill holes**. (kicad-cli returns **nonzero on benign
   warnings** — trust the *file*, not the exit code.)
2. **Import + register** into the build123d assembly (`scripts/import_pcb.py`): center on the shared
   datum, mirror Y (see gotcha), write `build/pcb.stl`.
3. **Render the fit-check** (`scripts/render_fit.py`): stack the board with the printed parts at the
   `machine_params` Z datums; an **exploded iso** (layers read apart) + a **top-down** (alignment).
4. **Read the overlay**: do the board cutouts sit under the shell openings? Does the connector edge
   meet its slot? Do the screw holes hit the bosses? Is the board inside the shell outline?
5. **Adjust PLACEMENT to the enclosure**, not the reverse where you can help it: move the connector to
   the shell slot's X, the display to the window centre, etc. — in the tscircuit source (`pcbX/pcbY`),
   then re-route. This is a placement gate, like `outline-check`.

```
route board ──▶ kicad-cli export step ──▶ import_pcb.py ──▶ render_fit.py ──▶ eyeball overlay
     ▲                                                                              │
     └────────────── nudge connector/display placement to the shell openings ◀──────┘
```

## Co-registration — the one thing to get right

Center the board and the printed parts on a **shared datum**, not each on its own bbox, or they
drift by half the difference of their outlines. Best datum, in order:
- **The corner mounting holes** (they're the literal mate — align those 4 points).
- The board **outline** centre, IF board outline == shell outline (common for product-face boards).
- A named origin both sides agree on (`FRONT_Y = -SHELL_H/2`, etc.).

`build123d-machine`'s `place(solid, frm, onto)` mate helper is the clean way: give the board a
`MATES["screw_nw"]` etc. and snap it onto the frame's hole mates. The quick version (used in
`import_pcb.py`) is bbox-centre + Y-mirror, which is right when outline==outline.

## Gotchas (hard-won)

- **kicad-cli step export exits nonzero on warnings** — the STEP is still written. Check for the file,
  not `$?`.
- **KiCad STEP is Y-negated vs a Y-up CAD frame.** KiCad's Y is screen-down; build123d's Y is up. The
  raw STEP comes out at negative Y. **Mirror Y** (`mirror(s, Plane.XZ)`) after centering, or the
  head/front edge + every asymmetric cutout lands on the wrong side. Verify by a known feature (a
  notch, an off-centre window).
- **Two 3D sources — pick by what you need (this matters):**
  - **`kicad-cli ... export step`** gives the **ROUTED board but BARE** — tscircuit footprints carry no
    *KiCad* 3D models, so it's outline + cutouts + hole barrels only. Best for **layer registration**
    (a clean flat plate to check outline/cutouts/screws vs the frame). Y-down → mirror.
  - **`tsci export -f step` (or `-f glb`/`-f gltf`)** gives the **POPULATED board WITH component
    bodies** — tscircuit's circuit-json has `cad_component` entries with real EasyEDA/JLCPCB 3D models
    (USB-C, MCU, amp, …) it pulls from `modelcdn.tscircuit.com`. Best for **connector / display
    protrusion + clearance** vs the shell openings. Already origin-centered + **Y-up (no mirror)**.
    Caveats: needs network (CDN fetch); a `<copperpour>` throws a benign async error during the 3D
    render but the file still writes; `tsci` **mangles an absolute `-o`** (strips the leading `/`) —
    write a path relative to the project, then move. And it reflects the **tscircuit placement, not the
    KiCad routing** — fine for mechanical fit (traces don't matter), and it's in sync as long as you
    re-export after moving parts. (tscircuit also has an **interactive 3D viewer** — `tsci dev` → 3D.)
  - So: bare KiCad STL for the stack, populated tscircuit STL for the bodies — `import_pcb.py`
    dispatches on extension (`.kicad_pcb` vs `.tsx`) and emits `pcb.stl` / `pcb_pop.stl`.
- **Params drift from geometry.** The render caught a board drawn 102.2 mm wide against a `SHELL_W=100.5`
  constant — a 1.7 mm overhang no constant would have flagged. Trust the overlay; reconcile the param.
- **OpenSCAD is the always-there previewer; Blender is the beauty shot.** `openscad -o out.png
  --camera=... --viewall scene.scad` renders headless anywhere (good enough to judge alignment).
  Blender/Cycles (via `bpy` or a GPU box) gives materials + soft light — wire `build/pcb.stl` in where
  the flat PCB stand-in was. Don't block the loop on Blender being installed.
- **STL units are mm**, build123d default; a Blender import usually needs a 0.001 scale (m). Keep the
  STL in mm and scale at import.
- **Insert/odd-part orientation** in a quick OpenSCAD stack is easy to get wrong (a rotate sign flips a
  part through the board). It's cosmetic for the alignment check — the board↔shell-opening overlay is
  what matters; fix the pretty orientation in the Blender assembly.

## Scripts (bundled — copy into the project's cad/)

- `scripts/import_pcb.py <board.kicad_pcb>` — kicad-cli STEP export → center + Y-mirror →
  `cad/build/pcb.stl`, with an outline-vs-shell delta print. Genericize the shell W/H or pass `--frame`.
- `scripts/render_fit.py [explode_mm]` — stacks `pcb.stl` + the printed `*.stl` at the stack Z datums,
  renders `build/fit_iso.png` (exploded) + `build/fit_top.png` (alignment) via OpenSCAD.

Wire it into the PCB Makefile so it runs with the route loop:
```make
fit:            ## 3D fit-check: board vs printed enclosure
	python3 ../cad/import_pcb.py index.circuit.kicad_pcb && python3 ../cad/render_fit.py 6
```

## Connector / opening placement (the feedback that matters)

The enclosure openings are **placement constraints**, and they're cheaper to honour than to fix:
- Pin the **connectors** to the shell-slot coordinates FIRST (USB-C at the USB cutout X, jack at the
  jack hole), then floorplan the rest around them. This is the mechanical analogue of pcb-layout's
  "connectors to the board edge first."
- Put a **display** at the window centre as a real placed part (footprint + body silk) so its outline
  shows in both the PCB and the fit render — see [[pcb-layout]] for the over-cutout `ALLOW_IN_CUTOUT`
  exception.
- Mounting holes → the boss positions from `machine_params`; share that constant both ways.

## Verify

- `build/pcb.stl` regenerates from the current board (re-export each pass — a stale STL hides a moved
  connector).
- The exploded iso + top render regenerate; eyeball: cutouts under openings, connectors at slots,
  screws on bosses, board inside the shell outline.
- Any board-vs-shell outline delta is **reconciled in the params**, not left to the render to keep
  catching.
