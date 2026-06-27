#!/usr/bin/env python3
"""add_plane.py — add a copper plane/pour zone to the LIVE KiCad board via the IPC API.

This is how you get a ground/power plane WITHOUT relying on tscircuit's <copperpour>,
which is silently dropped by `tsci export -f kicad_pcb` (the exported board has 0 zones).
KiCad clips the rectangular outline to the real board edge (Edge.Cuts) on fill, so the
zone shape follows any cassette outline / window cutout automatically.

  2-layer:  add_plane.py GND B.Cu            # ground pour on the bottom
  4-layer:  add_plane.py GND In1.Cu          # dedicated ground plane (inner 1)
            add_plane.py V3V3 In2.Cu --priority 1   # power plane (inner 2)

A real inner GND/PWR plane is the lever for high-pin-count parts: both outer layers stay
free for signal escape, and every pin reaches ground/power with a short stitching via —
instead of the autorouter snaking GND/PWR as tracks (which is what wrecks 4-layer routing).

Usage:  python3 add_plane.py <NET> <LAYER> [--name NAME] [--priority N] [--replace]
        --replace  delete an existing zone of the same name first (idempotent re-run)
"""
import sys
import kipy
from kipy.board_types import Zone, BoardLayer
from kipy.geometry import Vector2, PolyLine, PolyLineNode, PolygonWithHoles

LAYERS = {"F.Cu": BoardLayer.BL_F_Cu, "B.Cu": BoardLayer.BL_B_Cu,
          "In1.Cu": BoardLayer.BL_In1_Cu, "In2.Cu": BoardLayer.BL_In2_Cu,
          "In3.Cu": BoardLayer.BL_In3_Cu, "In4.Cu": BoardLayer.BL_In4_Cu}

def opt(flag, default=None):
    return sys.argv[sys.argv.index(flag) + 1] if flag in sys.argv else default

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    net_name, layer_name = sys.argv[1], sys.argv[2]
    zone_name = opt("--name", f"{net_name}_plane")
    priority = int(opt("--priority", "0"))
    replace = "--replace" in sys.argv

    layer = LAYERS.get(layer_name)
    if layer is None:
        print(f"unknown layer {layer_name}; choose from {list(LAYERS)}"); sys.exit(1)

    b = kipy.KiCad().get_board()
    net = next((n for n in b.get_nets() if n.name == net_name), None)
    if net is None:
        print(f"no net named {net_name!r} on the board"); sys.exit(1)

    if replace:
        dupes = [z for z in b.get_zones() if z.name == zone_name]
        if dupes:
            b.remove_items(dupes); print(f"removed {len(dupes)} existing {zone_name!r} zone(s)")

    # board bbox from Edge.Cuts shapes (fall back to pads); rectangle is clipped to the outline on fill
    xs, ys = [], []
    for s in b.get_shapes():
        for a in ("start", "end"):
            v = getattr(s, a, None)
            if v is not None:
                xs.append(v.x); ys.append(v.y)
    if not xs:
        for p in b.get_pads():
            xs.append(p.position.x); ys.append(p.position.y)
    m = 1_000_000  # 1 mm margin (nm); fill clips to the board edge anyway
    x0, x1, y0, y1 = min(xs) - m, max(xs) + m, min(ys) - m, max(ys) + m

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
    b.refill_zones()
    b.save()
    filled = next((zz for zz in b.get_zones() if zz.name == zone_name), None)
    npoly = sum(len(v) for v in filled.filled_polygons.values()) if filled else 0
    print(f"added {zone_name!r} (net {net_name}, {layer_name}); filled islands={npoly}; SAVED")
    if npoly != 1:
        print(f"  WARNING: expected 1 unbroken island, got {npoly} — check for orphaned regions")

if __name__ == "__main__":
    main()
