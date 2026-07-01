#!/usr/bin/env python3
"""fanout_planes.py — connect unconnected GND/V3V3 pads to their inner plane with a
COLLISION-AWARE fanout via.

On a 4-layer board GND/V3V3 are planes (In1/In2); every GND/V3V3 pad reaches its plane
through a through-via. The naive approach (drop a via at a fixed offset + a stub trace)
lands vias/stubs on top of signal copper on a dense board -> dozens of plane-vs-signal
shorts. Instead, for each pad this:

  1. prefers VIA-IN-PAD (via at the pad centre): the pad is already that net's copper, so a
     via there adds no signal-layer trace and can't cross a neighbouring signal on the pad's
     own layer. The zone refill carves the antipad in the OTHER plane automatically.
  2. only if via-in-pad is geometrically blocked (a foreign track runs under/over the pad, or
     a foreign pad/via is too close on either outer layer) does it try small offsets, and each
     candidate (via point + the pad->via stub) is clearance-checked against all foreign copper
     on both outer layers before being accepted.
  3. if nothing is clear, it leaves the pad unconnected and REPORTS it (never creates a short).

Geometry is read live over IPC; picks are applied as vias(+stubs), then zones refilled + saved.

    python3 fanout_planes.py [board.kicad_pcb]
"""
import json
import math
import re
import subprocess
import sys

import kipy
from kipy.board_types import Track, Via, BoardLayer
from kipy.geometry import Vector2

BOARD = sys.argv[1] if len(sys.argv) > 1 else "index.circuit.kicad_pcb"
PLANE = {"GND", "V3V3"}
NM = 1_000_000
VIA_D, VIA_DRILL, TRK_W = 600_000, 300_000, 200_000     # JLC-legal via
CLR = 150_000                                            # clearance margin (nm)
VIA_R = VIA_D // 2
# candidate offsets (nm): 0 = via-in-pad first, then rings of 8 directions
DIRS = [(1, 0), (0, 1), (-1, 0), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
OFFS = [500_000, 800_000, 1_100_000]

b = kipy.KiCad().get_board()
nets = {n.name: n for n in b.get_nets() if n.name}

# --- gather foreign copper as (layer-set, geometry) primitives -------------------------
F, B = "F", "B"


def layers_of(obj_layers):
    s = set()
    for l in obj_layers:
        if l == BoardLayer.BL_F_Cu:
            s.add(F)
        elif l == BoardLayer.BL_B_Cu:
            s.add(B)
    return s


segs = []    # (net, layerset, x1,y1,x2,y2, halfwidth)
pts = []     # (net, layerset, x, y, radius)   pads & vias
padlist = []  # (ref,num,net,pos,layerset) SMD pads to consider
for t in b.get_tracks():
    net = t.net.name if t.net else ""
    if isinstance(t, Via):
        pts.append((net, {F, B}, t.position.x, t.position.y, t.diameter // 2))
    else:
        ls = F if t.layer == BoardLayer.BL_F_Cu else B
        segs.append((net, {ls}, t.start.x, t.start.y, t.end.x, t.end.y, t.width // 2))

for fp in b.get_footprints():
    ref = fp.reference_field.text.value
    for pd in fp.definition.pads:
        net = pd.net.name if pd.net else ""
        ls = set()
        try:
            ls = layers_of(pd.padstack.copper_layers) if hasattr(pd, "padstack") else set()
        except Exception:
            ls = set()
        if not ls:
            ls = {F, B}                       # unknown -> treat as both (conservative)
        # pad radius ~ half its larger dimension
        try:
            sz = pd.padstack.size if hasattr(pd, "padstack") else None
            r = max(sz.x, sz.y) // 2 if sz else 400_000
        except Exception:
            r = 400_000
        pts.append((net, ls, pd.position.x, pd.position.y, r))
        padlist.append((ref, str(pd.number), net, pd.position, ls))


def seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    L2 = dx * dx + dy * dy
    if L2 == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
    return math.hypot(px - (x1 + t * dx), py - (y1 + t * dy))


def clear_point(vx, vy, net, use_layers):
    """True if a via at (vx,vy) clears all FOREIGN copper on `use_layers`."""
    for n, ls, x, y, r in pts:
        if n == net or not (ls & use_layers):
            continue
        if math.hypot(vx - x, vy - y) < VIA_R + r + CLR:
            return False
    for n, ls, x1, y1, x2, y2, hw in segs:
        if n == net or not (ls & use_layers):
            continue
        if seg_dist(vx, vy, x1, y1, x2, y2) < VIA_R + hw + CLR:
            return False
    return True


def clear_stub(x1, y1, x2, y2, net, layer):
    """True if the pad->via stub segment on `layer` clears foreign copper."""
    for n, ls, x, y, r in pts:
        if n == net or layer not in ls:
            continue
        if seg_dist(x, y, x1, y1, x2, y2) < TRK_W // 2 + r + CLR:
            return False
    for n, ls, a1, b1, a2, b2, hw in segs:
        if n == net or layer not in ls:
            continue
        # approximate segment-segment clearance by sampling endpoints + midpoint
        for sx, sy in ((x1, y1), (x2, y2), ((x1 + x2) / 2, (y1 + y2) / 2)):
            if seg_dist(sx, sy, a1, b1, a2, b2) < TRK_W // 2 + hw + CLR:
                return False
    return True


# --- which pads need a fanout: DRC unconnected on a plane net --------------------------
subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", "build/drc.json", BOARD],
               capture_output=True)
drc = json.load(open("build/drc.json"))
need = set()
for v in drc.get("unconnected_items", []):
    for it in v.get("items", []):
        m = re.match(r"Pad (\S+) \[(.+?)\] of (\S+)", it.get("description", ""))
        if m and m.group(2) in PLANE:
            need.add((m.group(3), m.group(1)))

items, placed, skipped = [], 0, []
for ref, num, net, pos, ls in padlist:
    if (ref, num) not in need or net not in PLANE:
        continue
    done = False
    # 1) via-in-pad
    if clear_point(pos.x, pos.y, net, {F, B}):
        via = Via(); via.position = pos; via.diameter = VIA_D; via.drill_diameter = VIA_DRILL; via.net = nets[net]
        items.append(via); placed += 1; done = True
    else:
        # 2) offset into a clear spot, stub on the pad's own layer
        stub_layer = F if F in ls else B
        for off in OFFS:
            for dx, dy in DIRS:
                d = math.hypot(dx, dy)
                vx, vy = int(pos.x + dx / d * off), int(pos.y + dy / d * off)
                if clear_point(vx, vy, net, {F, B}) and clear_stub(pos.x, pos.y, vx, vy, net, stub_layer):
                    via = Via(); via.position = Vector2.from_xy(vx, vy)
                    via.diameter = VIA_D; via.drill_diameter = VIA_DRILL; via.net = nets[net]
                    tr = Track(); tr.start = pos; tr.end = Vector2.from_xy(vx, vy)
                    tr.width = TRK_W; tr.net = nets[net]
                    tr.layer = BoardLayer.BL_F_Cu if stub_layer == F else BoardLayer.BL_B_Cu
                    items += [via, tr]; placed += 1; done = True
                    break
            if done:
                break
    if not done:
        skipped.append(f"{ref}.{num}[{net}]")

created = b.create_items(items)
b.refill_zones(); b.save()
print(f"fanout_planes: {placed} pads connected ({len(items)} items), "
      f"{len(skipped)} unplaced{': '+', '.join(skipped) if skipped else ''} -> saved")
