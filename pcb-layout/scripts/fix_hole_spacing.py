#!/usr/bin/env python3
"""fix_hole_spacing.py — remove finisher vias that sit too close to a drilled hole (JLC
hole-to-hole min ~0.5 mm). A redundant GND/V3V3 via next to a connector/keyswitch/screw
hole is a DFM 'plated through-hole spacing' danger and can break into the hole's drill —
delete it (the pad it was near reaches the plane anyway) as long as removing it doesn't
disconnect the net. Run over IPC."""
import math
import time

import kipy
from kipy.board_types import Via

BOARD = "index.circuit.kicad_pcb"
MIN_EDGE = 0.45 * 1_000_000   # nm: delete a via whose drill edge is closer than this to a hole edge


# hole geometry from the FILE (kipy's padstack.drill API is unreliable here); oval-drill safe
def parse_holes(path):
    txt = open(path).read()

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
    root, _ = sx(txt, txt.index("("))

    def fa(l, k):
        return [x for x in l if isinstance(x, list) and x and x[0] == k]

    def g(l, k):
        for x in l:
            if isinstance(x, list) and x and x[0] == k:
                return x
    pts = []
    for fp in fa(root, "footprint"):
        at = g(fp, "at"); fx, fy = float(at[1]), float(at[2])
        rot = float(at[3]) if len(at) > 3 else 0.0
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
        for pad in fa(fp, "pad"):
            if pad[2] not in ("thru_hole", "np_thru_hole"):
                continue
            dr = g(pad, "drill")
            if not dr:
                continue
            d = max(float(dr[2]), float(dr[3])) if dr[1] == "oval" else float(dr[1])
            pat = g(pad, "at"); px, py = float(pat[1]), float(pat[2])
            wx = fx + px * ca - py * sa
            wy = fy + px * sa + py * ca
            pts.append((wx * 1e6, wy * 1e6, d / 2 * 1e6))
    return pts


hole_pts = parse_holes(BOARD)
b = None
for _ in range(20):
    try:
        b = kipy.KiCad().get_board(); break
    except Exception:
        time.sleep(2)
if b is None:
    raise SystemExit("no IPC")

kill = []
for t in b.get_vias():          # NB: get_tracks() does NOT return vias in this kipy — use get_vias()
    vr = t.diameter / 2
    for hx, hy, hr in hole_pts:
        edge = math.hypot(t.position.x - hx, t.position.y - hy) - vr - hr
        if edge < MIN_EDGE:
            kill.append((t, edge))
            break

print(f"vias too close to a hole (< {MIN_EDGE/1e6:.2f} mm edge): {len(kill)}")
for t, e in kill:
    net = t.net.name if t.net else "?"
    print(f"  via [{net}] @({t.position.x/1e6:.2f},{t.position.y/1e6:.2f}) edge {e/1e6:.3f} mm")
if kill:
    b.remove_items([t for t, _ in kill])
    b.refill_zones(); b.save()
    print("removed + saved")
