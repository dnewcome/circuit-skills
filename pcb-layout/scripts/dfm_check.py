#!/usr/bin/env python3
"""dfm_check.py — the pre-order DFM gate: fab rules that KiCad's default DRC does NOT catch
but a fab's DFM (e.g. JLCPCB) does. Run it right before generating the fab bundle.

Checks, against JLCPCB minimums (override via flags):
  * plated hole-to-hole EDGE spacing >= 0.5 mm  — the big one; a finisher via dropped next to a
    connector/keyswitch/screw hole reads as a DFM 'plated through-hole spacing' danger and the
    drills can break into each other. Splits INTER-part (actionable — move/reroute the via) from
    INTRA-part (a single component's own footprint, e.g. a USB-C connector's mount-post-to-GND-pad
    spacing — inherent to the qualified part, informational only).
  * via drill >= 0.30 mm and annular ring >= 0.13 mm — undersized finisher vias.

Exits nonzero if any ACTIONABLE violation remains, so it gates the pipeline. Reads the .kicad_pcb
text (no KiCad needed). Note: silkscreen-over-pad/hole and sub-min silk lines are NOT checked here —
they're cosmetic (JLC auto-clips silk around openings); don't block a build on them.

  python3 dfm_check.py [board.kicad_pcb] [--hole-gap 0.5] [--via-drill 0.3] [--annular 0.13]
"""
import math
import sys

BOARD = next((a for a in sys.argv[1:] if not a.startswith("--")), "index.circuit.kicad_pcb")


def opt(flag, d):
    return float(sys.argv[sys.argv.index(flag) + 1]) if flag in sys.argv else d


HOLE_GAP = opt("--hole-gap", 0.5)
VIA_DRILL = opt("--via-drill", 0.30)
ANNULAR = opt("--annular", 0.13)


def sx(s, i):
    i += 1; out = []
    while True:
        while s[i] in " \t\r\n":
            i += 1
        if s[i] == ")":
            return out, i + 1
        if s[i] == "(":
            v, i = sx(s, i); out.append(v)
        elif s[i] == '"':
            j = i + 1
            while s[j] != '"':
                if s[j] == "\\":
                    j += 1
                j += 1
            out.append(s[i + 1:j]); i = j + 1
        else:
            j = i
            while s[j] not in ' \t\r\n()':
                j += 1
            out.append(s[i:j]); i = j


def fa(l, k):
    return [x for x in l if isinstance(x, list) and x and x[0] == k]


def g(l, k):
    for x in l:
        if isinstance(x, list) and x and x[0] == k:
            return x
    return None


def drill_dia(pad):
    dr = g(pad, "drill")
    if not dr:
        return 0.0
    return max(float(dr[2]), float(dr[3])) if dr[1] == "oval" else float(dr[1])


txt = open(BOARD).read()
root, _ = sx(txt, txt.index("("))

# every drilled hole: (owner, x, y, drill_radius); owner = footprint ref, or "via"
holes = []
vias = []
for fp in fa(root, "footprint"):
    at = g(fp, "at"); fx, fy = float(at[1]), float(at[2])
    rot = float(at[3]) if len(at) > 3 else 0.0
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    ref = next((p[2] for p in fa(fp, "property") if p[1] == "Reference"), "?")
    for pad in fa(fp, "pad"):
        if pad[2] in ("thru_hole", "np_thru_hole"):
            d = drill_dia(pad)
            pat = g(pad, "at"); px, py = float(pat[1]), float(pat[2])
            holes.append((ref, fx + px * ca - py * sa, fy + px * sa + py * ca, d / 2))
for x in root:
    if isinstance(x, list) and x and x[0] == "via":
        at = g(x, "at"); dr = g(x, "drill"); sz = g(x, "size")
        d = float(dr[1]) if dr else 0.0
        dia = float(sz[1]) if sz else 0.0
        holes.append(("via", float(at[1]), float(at[2]), d / 2))
        vias.append((float(at[1]), float(at[2]), dia, d))

inter, intra = [], []
for i in range(len(holes)):
    for j in range(i + 1, len(holes)):
        a, b = holes[i], holes[j]
        edge = math.hypot(a[1] - b[1], a[2] - b[2]) - a[3] - b[3]   # center dist - both radii
        if edge < HOLE_GAP:
            row = (edge, a, b)
            (intra if a[0] == b[0] and a[0] != "via" else inter).append(row)
inter.sort(); intra.sort()

via_bad = []
for x, y, dia, d in vias:
    if d + 1e-9 < VIA_DRILL:
        via_bad.append(("drill", x, y, d))
    elif (dia - d) / 2 + 1e-9 < ANNULAR:
        via_bad.append(("annular", x, y, (dia - d) / 2))

print(f"dfm_check {BOARD}  (hole-gap>={HOLE_GAP} via-drill>={VIA_DRILL} annular>={ANNULAR} mm)")
print(f"  drilled holes: {len(holes)}  vias: {len(vias)}")
if inter:
    print(f"  ✗ ACTIONABLE hole-spacing (inter-part) < {HOLE_GAP} mm: {len(inter)}")
    for e, a, b in inter[:12]:
        print(f"      {e:.3f} mm  {a[0]}@({a[1]:.2f},{a[2]:.2f}) <-> {b[0]}@({b[1]:.2f},{b[2]:.2f})")
else:
    print(f"  ✓ hole spacing (inter-part) OK")
if via_bad:
    print(f"  ✗ via drill/annular below min: {len(via_bad)}")
    for kind, x, y, v in via_bad[:12]:
        print(f"      {kind} {v:.3f} mm @({x:.2f},{y:.2f})")
else:
    print(f"  ✓ via drill + annular OK")
if intra:
    print(f"  ℹ {len(intra)} intra-footprint hole pair(s) < {HOLE_GAP} mm — part-inherent "
          f"(e.g. connector footprint), fab still builds it:")
    for e, a, b in intra[:6]:
        print(f"      {e:.3f} mm  {a[0]} (own footprint)")

sys.exit(1 if inter or via_bad else 0)
