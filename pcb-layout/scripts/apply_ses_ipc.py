#!/usr/bin/env python3
"""apply_ses_ipc.py — inject a Freerouting SES into the LIVE KiCad board via the IPC API.

This is the "automate KiCad the right way" injector: it does what KiCad's GUI
File ▸ Import ▸ Specctra Session does, but headless against a running pcbnew — so it
works with a SES routed from *tscircuit's* DSN (which the GUI import rejects for foreign ids).

Why it's clean where the old SWIG/pcbnew injector (apply_ses.py) was not:
  * Net assignment is AUTHORITATIVE, not geometric — no V3V3/GND mislabel shorts:
      - "Net-(REF-PadN)"        -> the net of kipy pad (REF, N)
      - "NAME_source_net_<n>"   -> kipy net NAME   (GND / V3V3 / SCL / SDA / USB_*)
  * GND lives on a real pour/plane (add_plane.py) — injected GND tracks are redundant copper,
    never the sole ground path, so a missed GND stub can't orphan a pad.

Coordinate transform (tscircuit DSN units -> KiCad nm), verified exact on flexisette:
    resolution = (um 10)  => 10000 units / mm
    x_nm = u*100 + 100_000_000        (mm = u/10000 ; kicad_x = mm + 100)
    y_nm = 100_000_000 - u*100        (Specctra Y is up; KiCad Y is down ; board at +100,+100)
    w_nm = w*100

Usage:  python3 apply_ses_ipc.py <ses_file> [--save] [--clear]
        --save   write the board (default = dry run: parse, map, report, create nothing)
        --clear  rip up existing tracks+vias first (clean re-route)
"""
import sys, re
import kipy
from kipy.board_types import Track, Via, BoardLayer
from kipy.geometry import Vector2

LAYERS = {"F.Cu": BoardLayer.BL_F_Cu, "B.Cu": BoardLayer.BL_B_Cu,
          "In1.Cu": BoardLayer.BL_In1_Cu, "In2.Cu": BoardLayer.BL_In2_Cu}

def TX(u): return int(round(float(u) * 100 + 100_000_000))
def TY(u): return int(round(100_000_000 - float(u) * 100))
def TW(u): return int(round(float(u) * 100))

# ---- minimal s-expression reader ----
def sexpr(text):
    toks = re.findall(r'\(|\)|"[^"]*"|[^\s()]+', text)
    def build(i):
        out = []
        while i < len(toks):
            t = toks[i]
            if t == '(':
                node, i = build(i + 1); out.append(node)
            elif t == ')':
                return out, i + 1
            else:
                out.append(t); i += 1
        return out, i
    return build(0)[0]

def find_all(node, name, acc):
    if isinstance(node, list):
        if node and node[0] == name:
            acc.append(node)
        for c in node:
            find_all(c, name, acc)
    return acc

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    ses_path = sys.argv[1]
    save = "--save" in sys.argv

    b = kipy.KiCad().get_board()

    if "--clear" in sys.argv:
        old = list(b.get_tracks()) + list(b.get_vias())
        if old:
            b.remove_items(old)
            print(f"ripped up {len(old)} existing tracks/vias")

    # --- authoritative net lookups ---
    name_net = {n.name: n for n in b.get_nets() if n.name}
    pad_net = {}
    for fp in b.get_footprints():
        ref = fp.reference_field.text.value
        for pd in fp.definition.pads:
            pad_net[(ref, str(pd.number))] = pd.net
    have_pad_nets = sum(1 for v in pad_net.values() if v and v.name)
    print(f"nets: {len(name_net)} named | pad map: {len(pad_net)} pads, {have_pad_nets} with nets")
    # (tried snapping endpoints to pad centres to kill dangling/unconnected — it ADDED crossings/shorts
    #  and didn't reduce unconnected, so we inject Freerouting's geometry verbatim. The unconnected tail
    #  is the genuine route tail, not off-pad slop.)

    def map_net(raw):
        nm = raw.strip('"')
        m = re.match(r'Net-\((.+)-Pad(\w+)\)$', nm)
        if m:
            ref = re.sub(r'_source_component_\d+$', '', m.group(1))  # tscircuit infix
            return pad_net.get((ref, m.group(2)))
        m = re.match(r'(.+)_source_net_\d+$', nm)
        if m:
            return name_net.get(m.group(1))
        return name_net.get(nm)

    tree = sexpr(open(ses_path).read())
    nets = find_all(tree, "net", [])
    print(f"SES net blocks: {len(nets)}")

    items, unmapped, xs, ys = [], [], [], []
    n_tracks = n_vias = 0
    for net in nets:
        raw = net[1]
        knet = map_net(raw)
        if knet is None:
            unmapped.append(raw.strip('"')); continue
        for child in net[2:]:
            if not isinstance(child, list):
                continue
            if child[0] == "wire":
                path = child[1]            # ['path', layer, width, x1,y1,x2,y2,...]
                layer = LAYERS.get(path[1])
                if layer is None: continue
                width = TW(path[2])
                coords = path[3:]
                pts = [(TX(coords[i]), TY(coords[i+1])) for i in range(0, len(coords) - 1, 2)]
                for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                    if (x1, y1) == (x2, y2):  # zero-length
                        continue
                    t = Track()
                    t.start = Vector2.from_xy(x1, y1)
                    t.end = Vector2.from_xy(x2, y2)
                    t.width = width
                    t.layer = layer
                    t.net = knet
                    items.append(t); n_tracks += 1
                    xs += [x1, x2]; ys += [y1, y2]
            elif child[0] == "via":
                x, y = TX(child[2]), TY(child[3])
                # padstack name carries the size, e.g. "Via[0-1]_600:300_um" -> 0.6mm pad / 0.3mm drill
                m = re.search(r'(\d+):(\d+)', child[1])
                pad_um, drill_um = (int(m.group(1)), int(m.group(2))) if m else (600, 300)
                v = Via()
                v.position = Vector2.from_xy(x, y)
                v.diameter = pad_um * 1000          # um -> nm
                v.drill_diameter = drill_um * 1000
                v.net = knet
                items.append(v); n_vias += 1
                xs.append(x); ys.append(y)

    if xs:
        print(f"coord span mm: x[{min(xs)/1e6:.1f},{max(xs)/1e6:.1f}] "
              f"y[{min(ys)/1e6:.1f},{max(ys)/1e6:.1f}]  (board ~ x[47.9,152.1] y[67.1,132.9])")
    print(f"to create: {n_tracks} tracks, {n_vias} vias | unmapped nets: {len(unmapped)} {unmapped[:6]}")

    if not save:
        print("DRY RUN — nothing created (pass --save to apply)")
        return

    created = b.create_items(items)
    print(f"created {len(created)} items")
    b.refill_zones()
    b.save()
    print("refilled zones + SAVED board")

if __name__ == "__main__":
    main()
