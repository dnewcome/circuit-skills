#!/usr/bin/env python3
"""apply_ses.py <kicad_pcb> <ses> [out] — write a Freerouting .ses into a KiCad board, headless.

KiCad's own SES import is unusable here (kicad-cli has no specctra; headless
pcbnew.ImportSpecctraSES throws). So we apply the routes ourselves. Net assignment
is by UNION-FIND over the routing graph: every wire segment unions its endpoints,
coincident endpoints/vias share a node, and each connected run takes the net of the
KiCad pad it lands in. That can't mislabel adjacent nets (e.g. V3V3 vs GND) the way
per-endpoint guessing does. Geometry via the measured transform:
  mm = ses/10000 ; kicad_x = mm_x + 100 ; kicad_y = 100 - mm_y .

Default out = the input board (in place), so index.circuit.kicad_pcb becomes routed.
The SES must have tscircuit "_source_component_N" ids stripped (freeroute.sh does it).
"""
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, "/usr/lib/python3/dist-packages")
import pcbnew

PCB = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "index.circuit.kicad_pcb")
SES = os.path.abspath(sys.argv[2] if len(sys.argv) > 2 else "build/index.fixed.ses")
OUT = os.path.abspath(sys.argv[3]) if len(sys.argv) > 3 else PCB

S = 1 / 10000.0
LAYER = {"F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu}


def tx(x, y):
    return (x * S + 100.0, 100.0 - y * S)


def MM(v):
    return pcbnew.FromMM(v)


def key(p):
    return (round(p[0], 3), round(p[1], 3))   # 1um-quantized node id


board = pcbnew.LoadBoard(PCB)

# --- parse all segments + vias (global; net assignment spans blocks) ---
ses = open(SES).read()
ses = ses[ses.index("(network_out"):]
segs, vias = [], []
for w in re.finditer(r"\(path\s+(F\.Cu|B\.Cu)\s+(\d+)\s+([-\d\s]+?)\)", ses):
    nums = [float(v) for v in w.group(3).split()]
    pts = [tx(nums[i], nums[i + 1]) for i in range(0, len(nums), 2)]
    for i in range(len(pts) - 1):
        segs.append((LAYER[w.group(1)], int(w.group(2)) * S, pts[i], pts[i + 1]))
for v in re.finditer(r'\(via\s+"Via\[0-1\]_(\d+):(\d+)_um"\s+(-?\d+)\s+(-?\d+)', ses):
    vias.append((int(v.group(1)), int(v.group(2)), tx(float(v.group(3)), float(v.group(4)))))

# --- union-find ---
parent = {}


def find(x):
    parent.setdefault(x, x)
    r = x
    while parent[r] != r:
        r = parent[r]
    while parent[x] != r:
        parent[x], x = r, parent[x]
    return r


def union(a, b):
    parent[find(a)] = find(b)


for (_, _, a, b) in segs:
    union(key(a), key(b))
for (_, _, p) in vias:
    find(key(p))

# spatial index of the routing nodes for pad lookup
grid = defaultdict(list)
G = 0.5  # mm cell


def cell(p):
    return (int(p[0] / G), int(p[1] / G))


for k in list(parent.keys()):
    grid[cell(k)].append(k)

# attach each pad's net to the run that lands inside it (pad bbox containment)
root_net = {}
for f in board.GetFootprints():
    for pad in f.Pads():
        pos, sz = pad.GetPosition(), pad.GetSize()
        pm = (pos.x / 1e6, pos.y / 1e6)
        hw, hh = sz.x / 2e6 + 0.01, sz.y / 2e6 + 0.01
        cx, cy = cell(pm)
        hit = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for k in grid.get((cx + dx, cy + dy), []):
                    if abs(k[0] - pm[0]) <= hw and abs(k[1] - pm[1]) <= hh:
                        hit = k if hit is None else hit
                        if hit is not None:
                            union(hit, k)
        if hit is not None:
            root_net[find(hit)] = pad.GetNetCode()


def netof(p):
    return root_net.get(find(key(p)))


# --- rip old routing, lay down the SES routing ---
for t in list(board.GetTracks()):
    board.Remove(t)
added_t = added_v = skipped = 0
for (layer, width, a, b) in segs:
    nc = netof(a)
    if nc is None:
        nc = netof(b)
    if nc is None:
        skipped += 1
        continue
    tr = pcbnew.PCB_TRACK(board)
    tr.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1])))
    tr.SetEnd(pcbnew.VECTOR2I(MM(b[0]), MM(b[1])))
    tr.SetWidth(MM(width))
    tr.SetLayer(layer)
    tr.SetNetCode(nc)
    board.Add(tr)
    added_t += 1
for (padd, drill, p) in vias:
    nc = netof(p)
    if nc is None:
        skipped += 1
        continue
    via = pcbnew.PCB_VIA(board)
    via.SetPosition(pcbnew.VECTOR2I(MM(p[0]), MM(p[1])))
    via.SetWidth(MM(padd / 1000.0))
    via.SetDrill(MM(drill / 1000.0))
    via.SetNetCode(nc)
    board.Add(via)
    added_v += 1

pcbnew.ZONE_FILLER(board).Fill(board.Zones())
pcbnew.SaveBoard(OUT, board)
open("build/apply_ses_result.txt", "w").write(
    f"injected {added_t} segments + {added_v} vias ({skipped} skipped) -> {OUT}\n")
