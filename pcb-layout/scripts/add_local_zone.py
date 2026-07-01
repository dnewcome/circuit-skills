#!/usr/bin/env python3
"""add_local_zone.py — add a LOCAL copper pour scoped to one footprint (e.g. a QFN).

The standard way to ground a fine-pitch QFN: a local GND pour on the pads' own layer ties
every ground pin into one pour (no via-per-pin needed — a JLC via won't even fit on 0.5 mm
pitch), and the pour connects down to the inner GND plane through the GND vias already in
that area (add a few stitching vias if the pour comes back isolated). The pour auto-clears
foreign nets on fill, so it won't short the signal escapes.

  python3 add_local_zone.py U1 GND F.Cu [--margin 1.2] [--priority 2]

Run over IPC (pcbnew open). Verify with kicad-cli drc afterwards.
"""
import sys
import time

import kipy
from kipy.board_types import Zone, BoardLayer
from kipy.geometry import Vector2, PolyLine, PolyLineNode, PolygonWithHoles

LAYERS = {"F.Cu": BoardLayer.BL_F_Cu, "B.Cu": BoardLayer.BL_B_Cu,
          "In1.Cu": BoardLayer.BL_In1_Cu, "In2.Cu": BoardLayer.BL_In2_Cu}


def opt(flag, d):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else d


ref = sys.argv[1]
net_name = sys.argv[2]
layer_name = sys.argv[3]
margin = float(opt("--margin", "1.2")) * 1_000_000
priority = int(opt("--priority", "2"))
zone_name = f"{ref}_{net_name}_local"

b = None
for _ in range(20):
    try:
        b = kipy.KiCad().get_board(); break
    except Exception:
        time.sleep(2)
if b is None:
    raise SystemExit("no IPC")

net = next((n for n in b.get_nets() if n.name == net_name), None)
layer = LAYERS[layer_name]

fp = next((f for f in b.get_footprints() if f.reference_field.text.value == ref), None)
if fp is None:
    raise SystemExit(f"no footprint {ref}")
xs, ys = [], []
for pd in fp.definition.pads:
    xs.append(pd.position.x); ys.append(pd.position.y)
x0, x1 = min(xs) - margin, max(xs) + margin
y0, y1 = min(ys) - margin, max(ys) + margin

# idempotent
dupes = [z for z in b.get_zones() if z.name == zone_name]
if dupes:
    b.remove_items(dupes)

pl = PolyLine()
for (x, y) in [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]:
    pl.append(PolyLineNode.from_xy(int(x), int(y)))
pl.closed = True
poly = PolygonWithHoles(); poly.outline = pl
z = Zone()
z.outline = poly
z.layers = [layer]
z.net = net
z.name = zone_name
z.priority = priority
b.create_items([z])
b.refill_zones(); b.save()
print(f"added local pour {zone_name!r} ({net_name} on {layer_name}) over {ref} "
      f"[{(x1-x0)/1e6:.1f} x {(y1-y0)/1e6:.1f} mm] -> saved")
