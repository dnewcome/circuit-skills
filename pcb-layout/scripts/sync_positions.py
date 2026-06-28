"""sync_positions.py — ROUND-TRIP the other way: read hand-placed part positions OUT of a KiCad
board back into a reusable placement file (the data that makes a layout reproducible + variant-able).

The fast early-design loop is:
    tsci export -f kicad_pcb            # topology + rough defaults from the .tsx
    apply_placement.py <variant>       # snap parts to the refined placement
    <open in KiCad, drag + rotate parts by eye against the ratsnest/DRC>
    sync_positions.py <variant>        # <-- THIS: pull those moves back into placement/<variant>.json
…repeat. No re-route needed while you're only moving parts (routing comes after the floorplan settles).

Positions are stored in the tscircuit design frame (board centred at origin, Y-up), derived from the
board-outline bbox centre — so the same numbers read naturally next to the .tsx pcbX/pcbY.

    python3 scripts/sync_positions.py [variant=default] [board=index.circuit.kicad_pcb]
"""
import re, json, sys, os

variant = sys.argv[1] if len(sys.argv) > 1 else "default"
board = sys.argv[2] if len(sys.argv) > 2 else "index.circuit.kicad_pcb"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HERE)
txt = open(board).read()

# board outline bbox centre -> the (Cx,Cy) that maps KiCad mm to the tscircuit-centred frame
exs, eys = [], []
for m in re.finditer(r'\(gr_line\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,120}?Edge\.Cuts', txt):
    x1, y1, x2, y2 = map(float, m.groups()); exs += [x1, x2]; eys += [y1, y2]
Cx, Cy = (min(exs) + max(exs)) / 2, (min(eys) + max(eys)) / 2


def blocks(t, tag='(footprint'):
    o = []; i = 0
    while True:
        i = t.find(tag, i)
        if i < 0: break
        d = 0; j = i
        while j < len(t):
            if t[j] == '(': d += 1
            elif t[j] == ')':
                d -= 1
                if d == 0: break
            j += 1
        o.append(t[i:j + 1]); i = j + 1
    return o


pos = {}
for b in blocks(txt):
    ref = re.search(r'\(property "Reference" "([^"]+)"', b)
    at = re.search(r'\(at ([-\d.]+) ([-\d.]+)(?: ([-\d.]+))?\)', b)        # footprint's own (at) is first in the block
    layer = re.search(r'\(layer "?([^")\s]+)"?\)', b)                      # quoted (KiCad-saved) or unquoted (fresh tsci)
    if not ref or not at: continue
    kx, ky, rot = float(at.group(1)), float(at.group(2)), float(at.group(3) or 0)
    pos[ref.group(1)] = {
        "x": round(kx - Cx, 3), "y": round(Cy - ky, 3),   # KiCad -> tscircuit-centred (Y-up)
        "rot": round(rot % 360, 1),
        "side": "bottom" if layer and "B." in layer.group(1) else "top",
    }

os.makedirs("placement", exist_ok=True)
out = f"placement/{variant}.json"
json.dump(pos, open(out, "w"), indent=2, sort_keys=True)
print(f"synced {len(pos)} part positions -> {out}  (centre KiCad=({Cx:.1f},{Cy:.1f}))")
