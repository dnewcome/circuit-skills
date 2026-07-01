---
name: pcb-3d-render
description: Render 3D views of a PCB/PCBA two ways — a native tscircuit snapshot for a quick, authentic board preview, or a GLB→headless-Blender pipeline for a ray-traced hero/marketing shot (studio-lit real boards, or emissive glowing LEDs on a curved "flex" panel). This is the visual layer on top of pcb-layout — the board's 3D model already exists (tscircuit `tsci export -f glb` / `tsci snapshot --3d`, or a KiCad STEP); this skill turns it into an image. Encodes the headless-Blender GPU recipe and the gotchas that silently waste hours (LC_ALL=C OCIO segfault, Blender-5 compositor API change, SIGPIPE-from-head killing a render, tscircuit's 256-part layout-solver limit, emissive glow tuning). Use when someone wants a 3D render / hero shot / README image of a board. Worked example: the flex-led-matrix project (curved emissive hero + studio PCBA shots).
argument-hint: [board/GLB to render + the look: authentic snapshot vs photoreal hero]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

The north star: **the 3D model already exists — this skill only lights and shoots it.** Geometry comes
from the board tools (tscircuit / KiCad); don't hand-model a PCB. Pick the cheapest path that gets the
look you need, and know the two or three headless gotchas that otherwise eat an afternoon.

## Decide the path (two, and they answer different needs)

| | **Native tscircuit snapshot** | **GLB → headless Blender** |
|---|---|---|
| Command | `tsci snapshot <f>.tsx --3d` | `tsci export -f glb` → `blender_render` |
| Look | tscircuit's WebGL viewer (flat-ish, ~800px) | ray-traced studio, hi-res, shadows, emissive |
| Effort | one command | export + a render script |
| Bonus | also emits PCB + schematic `.snap.svg` | full control: camera, materials, lighting |
| Use for | a quick, **authentic** "this is the board" | a **hero / marketing / README** beauty shot |

Default to the **snapshot** for a documentation image; reach for **Blender** only when you want a
polished hero (studio-lit real PCB, or *lit* LEDs / a curved flex panel that the flat viewer can't sell).

## Path A — native tscircuit snapshot (fast, authentic)

```bash
tsci snapshot index.tsx --3d --update            # -> __snapshots__/index-3d.snap.png (+ pcb/schematic svg)
tsci snapshot index.tsx --3d --camera-preset top-center-angled --update
# presets: top-down, top-down-ortho, top-left(-corner), top-right(-corner),
#          left-sideview, right-sideview, front, top-center-angled
```

⚠ **At 256+ components tscircuit's schematic solver dies** — `PackSolver2 ran out of iterations` — and
it blocks both `snapshot` and `export -f glb`. The fix is to **pin schematic coords on every part**, not
just PCB coords: give each component `schX`/`schY` (any spread) alongside `pcbX`/`pcbY`, so the auto-layout
has nothing to solve. (A dense LED matrix is placement-only anyway; positions are known.)

## Path B — GLB → headless Blender (the beauty shot)

1. **Get a GLB.** From tscircuit: `tsci export -f glb index.tsx -o board.glb` (carries the real
   component CAD models). Or build a presentation mesh yourself with trimesh (a curved substrate +
   emissive per-pixel materials — see the flex-led-matrix `gen/render_model.py`). glTF is **Y-up**;
   CAD is Z-up — rotate −90° about X or the board renders on its side.
2. **Render** with the bundled script (Cycles, GPU, AgX, auto-framed camera):

```bash
LC_ALL=C LANG=C blender -b -P scripts/blender_panel.py -- board.glb out.png \
    --studio --res 1500 --samples 200 --az 30 --el 34      # neutral PCB beauty shot
LC_ALL=C LANG=C blender -b -P scripts/blender_panel.py -- panel.glb hero.png \
    --emit 18 --az 36 --el 20                                # dark moody + glowing emissive pixels
```

- `--studio` = bright neutral world + key/fill/rim (real green PCB); omit for a dark moody world where
  **emissive** materials dominate. `--emit N` boosts Emission Strength on materials named `led*`
  (glTF caps `emissiveFactor` at 1, so unboosted LEDs look like matte tiles, not lit pixels).
- `--az`/`--el` orbit the auto-framed camera. `blender` on this machine is
  `/opt/blender-5.0.1-linux-x64/blender` (else `which blender`, then search `/opt`).

## Gotchas (each one silently wastes an hour — all baked into the script)

- **ALWAYS `LC_ALL=C LANG=C` for headless Blender.** A locale bug segfaults **libOpenColorIO** while
  building the AgX transform — and the "CYCLES device:" line prints *before* the crash, so it looks like
  it started but **no file is written**. Force the C locale, and **verify the output mtime actually
  updated** — exit 0 + a device line is NOT proof it rendered.
- **Never pipe Blender's stdout through `head`.** `head` closes the pipe after N lines → **SIGPIPE kills
  Blender mid-render** → silent 0-byte / stale output. Use `... 2>&1 | tail -N` (tail reads to EOF first).
- **GPU on Blender 5: call `prefs.refresh_devices()`, NOT `get_devices()`** (removed in 5.0 → silently
  throws → CPU). Enable only GPU devices, set `cycles.device='GPU'`. Trust the `CYCLES device: OPTIX`
  print; the `HIPEW initialization failed` warning is just the AMD probe — benign.
- **Blender 5 moved the compositor:** `scene.use_nodes`/`scene.node_tree` are gone → glare/bloom setup
  throws `'Scene' object has no attribute 'node_tree'`. Guard it in try/except and skip gracefully; get
  the LED glow from strong emission + a dark world + AgX rolloff instead (it reads fine without a Glare node).
- **Thin boards / single-surface shells** render black from the back → `doubleSided=True` on the material.
- **Emissive realism:** bright LEDs desaturate toward white (that's physical) — don't fight it; pick a
  vivid gradient and let the hot pixels bloom.

## Verify

- Output file **mtime updated** (not just exit 0). Reload/preview the PNG.
- GLB sanity in trimesh: `len(scene.geometry)`, `scene.extents` (right size, upright), a spot-check
  `material.emissiveFactor` if you expect glow.

`scripts/blender_panel.py` is the bundled renderer (`--studio` / `--emit` / `--az` / `--el`, GPU auto-select,
AgX, shadow-catcher floor, auto-framed camera). Needs Blender 3.x+ (validated on 5.0.1) with a GPU for
Cycles. Pairs with **pcb-layout** (which produces the board) — design there, shoot here.
