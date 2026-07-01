#!/usr/bin/env python3
"""add_npth_keepouts.py — keepout every NON-PLATED through-hole (mechanical hole) in the DSN.

The companion to add_cutout_keepouts.py: that one keepouts interior *Edge.Cuts* shapes, but
mechanical mounting holes (keyswitch poles/alignment pins, USB-C posts, board screw holes) come
in as NPTH *pads* with no copper. Freerouting sees no obstacle and routes tracks straight across
the drilled hole -> the drill removes the copper -> open net. This adds a per-copper-layer keepout
(hole radius + margin) around each np_thru_hole pad so the router avoids them.

Usage:  python3 add_npth_keepouts.py <board.kicad_pcb> <board.dsn> [--margin MM] [--min-hole MM]
"""
import math
import re
import sys


def opt(flag, d):
    return float(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else d


def sexpr(s, i):
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


def fa(l, k):
    return [x for x in l if isinstance(x, list) and x and x[0] == k]


def g(l, k):
    for x in l:
        if isinstance(x, list) and x and x[0] == k:
            return x
    return None


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    kpcb, dsn = sys.argv[1], sys.argv[2]
    margin = opt("--margin", 0.3)
    min_hole = opt("--min-hole", 0.5)
    ktxt = open(kpcb).read()
    dtxt = open(dsn).read()

    # NPTH mechanical holes -> (world x, y, radius+margin)
    root, _ = sexpr(ktxt, ktxt.index("("))
    holes = []
    for fp in fa(root, "footprint"):
        at = g(fp, "at")
        fx, fy, rot = float(at[1]), float(at[2]), (float(at[3]) if len(at) > 3 else 0.0)
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        for pad in fa(fp, "pad"):
            if len(pad) > 2 and pad[2] == "np_thru_hole":
                drill = g(pad, "drill")
                dia = float(drill[1]) if drill else 0.0
                if dia < min_hole:
                    continue
                pat = g(pad, "at")
                px, py = float(pat[1]), float(pat[2])
                wx = fx + px * ca - py * sa
                wy = fy + px * sa + py * ca
                holes.append((wx, wy, dia / 2 + margin))
    if not holes:
        print("no NPTH holes found"); return

    # transform kicad(mm) -> DSN units from the outer Edge.Cuts bbox <-> DSN boundary bbox
    epts = []
    for m in re.finditer(r'\(gr_(?:line|arc)\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,140}?\(layer "?Edge\.Cuts"?\)', ktxt):
        a, b, c, d = map(float, m.groups()); epts += [(a, b), (c, d)]
    for m in re.finditer(r'\(gr_circle\s*\(center ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,140}?\(layer "?Edge\.Cuts"?\)', ktxt):
        cx, cy, ex, ey = map(float, m.groups()); r = math.hypot(ex - cx, ey - cy)
        epts += [(cx - r, cy - r), (cx + r, cy + r)]
    if not epts:
        print("no Edge.Cuts geometry for transform"); sys.exit(1)
    okx0, oky0 = min(p[0] for p in epts), min(p[1] for p in epts)
    okx1, oky1 = max(p[0] for p in epts), max(p[1] for p in epts)

    mb = re.search(r'\(boundary\s*\(path \S+ \S+\s+([-\d.\s]+)\)', dtxt)
    nums = [float(x) for x in mb.group(1).split()]
    dxs, dys = nums[0::2], nums[1::2]
    dminx, dmaxx, dminy, dmaxy = min(dxs), max(dxs), min(dys), max(dys)
    sx = (dmaxx - dminx) / (okx1 - okx0)
    sy = (dmaxy - dminy) / (oky1 - oky0)
    kcx, kcy = (okx0 + okx1) / 2, (oky0 + oky1) / 2
    dcx, dcy = (dminx + dmaxx) / 2, (dminy + dmaxy) / 2
    TX = lambda kx: (kx - kcx) * sx + dcx
    TY = lambda ky: dcy - (ky - kcy) * sy       # Specctra Y up, KiCad Y down
    layers = [l for l in dict.fromkeys(re.findall(r'\(layer (\S+)', dtxt[:dtxt.index("(placement")]))
              if l.endswith(".Cu")]

    ko = ""
    for j, (wx, wy, r) in enumerate(holes):
        X = sorted([TX(wx - r), TX(wx + r)])
        Y = sorted([TY(wy - r), TY(wy + r)])
        for l in layers:
            ko += f'\n    (keepout "npth{j}_{l}" (rect {l} {int(X[0])} {int(Y[0])} {int(X[1])} {int(Y[1])}))'

    i = dtxt.index("(boundary")
    depth = 0; e = i
    while e < len(dtxt):
        if dtxt[e] == "(":
            depth += 1
        elif dtxt[e] == ")":
            depth -= 1
            if depth == 0:
                break
        e += 1
    dtxt = dtxt[:e + 1] + ko + dtxt[e + 1:]
    open(dsn, "w").write(dtxt)
    print(f"added {len(holes)*len(layers)} NPTH keepout rect(s) for {len(holes)} holes on {layers} (scale {sx:.0f} u/mm)")


if __name__ == "__main__":
    main()
