#!/usr/bin/env python3
"""check_floating.py — catch wrong-side / floating SMD pads BEFORE fab.

The failure it exists for: an SMD pad lives on ONE copper layer (F.Cu *or* B.Cu),
but the autorouter (Freerouting is a repeat offender) routed its net on the OTHER
layer and never dropped a fanout via — so the pad is reached only by opposite-side
copper and is electrically FLOATING even though a 2D plot "looks" connected. This
is invisible to a casual look and easy to miss in a huge DRC list.

Rule: for every SMD pad with a net, there must be, within the pad, EITHER
  - a copper segment on the pad's OWN layer whose endpoint lands on it, OR
  - a via on the pad (a via bridges layers, so it legitimately brings the net up).
If the only copper touching the pad is on the opposite layer with NO via -> FLAG.

Reads the .kicad_pcb text; no running KiCad needed. Exit 1 if any pad is flagged,
so it drops straight into a Makefile / route script as a gate.

  python3 scripts/check_floating.py [board.kicad_pcb]
"""
import math
import sys

BOARD = sys.argv[1] if len(sys.argv) > 1 else "index.circuit.kicad_pcb"
REACH = 0.60          # mm: how far from pad center copper may land and still count as "on the pad"
VIA_REACH = 0.70      # mm: a via this close to the pad center counts as fanning it out
txt = open(BOARD).read()


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


root, _ = sexpr(txt, txt.index("("))
nn = {x[1]: (x[2] if len(x) > 2 else "") for x in fa(root, "net")}

segs, vias = [], []
for x in root:
    if not isinstance(x, list) or not x:
        continue
    if x[0] == "segment":
        st, en, ly, net = g(x, "start"), g(x, "end"), g(x, "layer"), g(x, "net")
        segs.append((float(st[1]), float(st[2]), float(en[1]), float(en[2]), ly[1],
                     nn.get(net[1], "?") if net else "?"))
    elif x[0] == "via":
        at, net = g(x, "at"), g(x, "net")
        vias.append((float(at[1]), float(at[2]), nn.get(net[1], "?") if net else "?"))


def close(ax, ay, bx, by, tol):
    return math.hypot(ax - bx, ay - by) <= tol


flagged = []
checked = 0
for fp in fa(root, "footprint"):
    ref = next((p[2] for p in fa(fp, "property") if p[1] == "Reference"), "?")
    at = g(fp, "at")
    fx, fy = float(at[1]), float(at[2])
    rot = float(at[3]) if len(at) > 3 else 0.0
    ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))
    for pad in fa(fp, "pad"):
        ptype = pad[2]
        if ptype != "smd":
            continue                        # thru-hole/NPTH are on all layers -> never wrong-side
        net = g(pad, "net")
        if not net or len(net) < 3 or not net[2]:
            continue                        # unconnected-by-design pad, skip
        netname = net[2]
        players = [l for l in (g(pad, "layers") or [])[1:] if l.endswith(".Cu")]
        if not players:
            continue
        pat = g(pad, "at")
        px, py = float(pat[1]), float(pat[2])
        wx = fx + px * ca - py * sa
        wy = fy + px * sa + py * ca
        checked += 1
        same, opp = [], []
        for sx, sy, ex, ey, ly, sn in segs:
            if sn != netname:
                continue
            if close(sx, sy, wx, wy, REACH) or close(ex, ey, wx, wy, REACH):
                (same if ly in players else opp).append(ly)
        via_here = any(sn == netname and close(vx, vy, wx, wy, VIA_REACH)
                       for vx, vy, sn in vias)
        if not same and not via_here and opp:
            flagged.append((ref, pad[1], netname, players[0], sorted(set(opp)), wx, wy))

print(f"check_floating: inspected {checked} SMD pads in {BOARD}")
if not flagged:
    print("  OK — every SMD pad is reached on its own layer or via a fanout via.")
    sys.exit(0)
print(f"  FLOATING / WRONG-SIDE pads: {len(flagged)}")
for ref, num, net, pl, opp, wx, wy in flagged:
    print(f"    {ref}.{num} [{net}] pad on {pl}, but only {opp} copper reaches it, "
          f"no via  @({wx:.2f},{wy:.2f})")
sys.exit(1)
