#!/usr/bin/env python3
"""Report, for given footprints, each pad's world position/layer/net and every
track segment or via whose endpoint lands on that pad — with the track's layer.
Purely reads the .kicad_pcb text (no KiCad needed). Flags the failure the user
suspects: a back-layer (B.Cu) segment touching a top-only (F.Cu) SMD pad with no
via = electrically floating."""
import math
import re
import sys

BOARD = "index.circuit.kicad_pcb"
REFS = sys.argv[1:] or ["C_OUT", "C_IN", "U3"]
txt = open(BOARD).read()


def sexpr(s, i):
    """parse one () sexpr starting at s[i]=='(' -> (list, end_index)"""
    assert s[i] == "("
    i += 1
    out = []
    while True:
        while s[i] in " \t\r\n":
            i += 1
        if s[i] == ")":
            return out, i + 1
        if s[i] == "(":
            v, i = sexpr(s, i)
            out.append(v)
        elif s[i] == '"':
            j = i + 1
            while s[j] != '"':
                if s[j] == "\\":
                    j += 1
                j += 1
            out.append(s[i + 1 : j])
            i = j + 1
        else:
            j = i
            while s[j] not in ' \t\r\n()':
                j += 1
            out.append(s[i:j])
            i = j


def find_all(lst, key):
    return [x for x in lst if isinstance(x, list) and x and x[0] == key]


def get(lst, key):
    for x in lst:
        if isinstance(x, list) and x and x[0] == key:
            return x
    return None


# parse the whole board
root, _ = sexpr(txt, txt.index("("))

# collect vias and segments
vias = []
segs = []
for x in root:
    if not isinstance(x, list) or not x:
        continue
    if x[0] == "via":
        at = get(x, "at")
        net = get(x, "net")
        vias.append((float(at[1]), float(at[2]), net[1] if net else "?"))
    elif x[0] == "segment":
        st = get(x, "start")
        en = get(x, "end")
        ly = get(x, "layer")
        net = get(x, "net")
        segs.append((float(st[1]), float(st[2]), float(en[1]), float(en[2]),
                     ly[1], net[1] if net else "?"))

# net id -> name
netnames = {}
for x in find_all(root, "net"):
    netnames[x[1]] = x[2] if len(x) > 2 else ""


def near(ax, ay, bx, by, tol=0.05):
    return math.hypot(ax - bx, ay - by) < tol


for fp in find_all(root, "footprint"):
    ref = None
    for p in find_all(fp, "property"):
        if p[1] == "Reference":
            ref = p[2]
    if ref not in REFS:
        continue
    fat = get(fp, "at")
    fx, fy = float(fat[1]), float(fat[2])
    frot = float(fat[3]) if len(fat) > 3 else 0.0
    fp_layer = get(fp, "layer")[1]
    print(f"\n=== {ref}  @({fx:.2f},{fy:.2f}) rot={frot}  side={fp_layer} ===")
    ca, sa = math.cos(math.radians(frot)), math.sin(math.radians(frot))
    for pad in find_all(fp, "pad"):
        num = pad[1]
        pat = get(pad, "at")
        px, py = float(pat[1]), float(pat[2])
        # rotate pad offset into world
        wx = fx + px * ca - py * sa
        wy = fy + px * sa + py * ca
        pad_layers = get(pad, "layers")
        pad_layers = pad_layers[1:] if pad_layers else []
        net = get(pad, "net")
        nn = net[2] if net and len(net) > 2 else "-"
        ptype = pad[2]  # smd / thru_hole
        print(f"  pad {num:>3} [{nn:6}] {ptype:9} world=({wx:.2f},{wy:.2f}) copper={pad_layers}")
        # segments touching this pad
        for sx, sy, ex, ey, ly, ni in segs:
            if near(sx, sy, wx, wy) or near(ex, ey, wx, wy):
                print(f"        seg  layer={ly:5} net={netnames.get(ni,'?')}")
        # vias on this pad
        for vx, vy, ni in vias:
            if near(vx, vy, wx, wy, tol=0.3):
                print(f"        VIA  net={netnames.get(ni,'?')} @({vx:.2f},{vy:.2f})")
