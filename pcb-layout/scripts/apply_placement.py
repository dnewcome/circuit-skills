"""apply_placement.py — snap a freshly-exported KiCad board to a saved placement file.

The other half of the round-trip (see sync_positions.py). After `tsci export -f kicad_pcb` gives a
board at the .tsx's rough default positions, this moves every part to the refined / hand-tuned /
per-variant placement in placement/<variant>.json. Iterate placement fast WITHOUT re-routing:
    tsci export -f kicad_pcb  ->  apply_placement.py <variant>  ->  open in KiCad  ->  drag  ->  sync_positions.py

Positions are in the tscircuit-centred frame; the board-outline bbox centre maps them back to KiCad mm,
so it works on any board the same way. Rotation is applied; SIDE (top/bottom) is owned by the .tsx
`layer=` (a hand flip needs footprint mirroring — keep that in code, not the round-trip).

    python3 scripts/apply_placement.py [variant=default] [board=index.circuit.kicad_pcb]
"""
import re, json, sys, os

variant = sys.argv[1] if len(sys.argv) > 1 else "default"
board = sys.argv[2] if len(sys.argv) > 2 else "index.circuit.kicad_pcb"
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(HERE)
pos = json.load(open(f"placement/{variant}.json"))
txt = open(board).read()

exs, eys = [], []
for m in re.finditer(r'\(gr_line\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,120}?Edge\.Cuts', txt):
    x1, y1, x2, y2 = map(float, m.groups()); exs += [x1, x2]; eys += [y1, y2]
Cx, Cy = (min(exs) + max(exs)) / 2, (min(eys) + max(eys)) / 2

out = []
i = 0
moved = 0
while True:
    j = txt.find('(footprint', i)
    if j < 0:
        out.append(txt[i:]); break
    out.append(txt[i:j])
    # span of this footprint block
    d = 0; k = j
    while k < len(txt):
        if txt[k] == '(': d += 1
        elif txt[k] == ')':
            d -= 1
            if d == 0: break
        k += 1
    blk = txt[j:k + 1]
    ref = re.search(r'\(property "Reference" "([^"]+)"', blk)
    if ref and ref.group(1) in pos:
        p = pos[ref.group(1)]
        kx, ky = round(p["x"] + Cx, 4), round(Cy - p["y"], 4)
        rot = p.get("rot", 0)
        rep = f'(at {kx} {ky}' + (f' {rot})' if rot else ')')
        blk = re.sub(r'\(at [-\d.]+ [-\d.]+(?: [-\d.]+)?\)', rep, blk, count=1)  # footprint's own (at) is first
        moved += 1
    out.append(blk)
    i = k + 1

open(board, "w").write("".join(out))
print(f"applied placement '{variant}' -> {moved}/{len(pos)} parts moved in {board}")
