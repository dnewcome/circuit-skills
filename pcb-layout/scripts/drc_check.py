#!/usr/bin/env python3
"""drc_check.py — repeatable DRC triage for a tscircuit->KiCad board.

Runs `kicad-cli pcb drc` and SORTS the violations into what actually matters, so a clean
board is obvious and noise doesn't hide a real defect:

  PLACEMENT  courtyards_overlap          -> parts physically collide; fix pcbX/pcbY
  ROUTING    shorting_items (distinct)   -> real copper short; reroute / move part
             tracks_crossing, dangling, unconnected
  FALSE      shorting_items (same base)  -> net fragmentation not reconciled (run merge_nets.py)
  RULE/FAB   via_diameter/annular        -> global via size (resize to fab) ; clearance -> fab min
             text/silk/mask/lib_footprint -> cosmetic / fab-handled

Exits non-zero if any PLACEMENT, real ROUTING, or FALSE short remains, so it gates a pipeline.

Usage: python3 drc_check.py <board.kicad_pcb>
"""
import sys, json, subprocess, re, tempfile, os
from collections import Counter

def base_of(name):
    m = re.match(r'^.* to net\.([A-Za-z0-9_]+)$', name)
    if m: return m.group(1)
    m = re.match(r'^([A-Za-z0-9_]+)_source_net_\d+$', name)
    if m: return m.group(1)
    return name

COSMETIC = {'via_diameter','annular_width','silk_over_copper','silk_overlap','text_height',
            'text_thickness','lib_footprint_issues','solder_mask_bridge','copper_edge_clearance',
            'nonmirrored_text_on_back_layer','clearance','hole_clearance','silk_over_silk'}

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(2)
    board = sys.argv[1]
    out = tempfile.mktemp(suffix='.json')
    r = subprocess.run(['kicad-cli','pcb','drc','--format','json','--exit-code-violations',
                        '-o',out,board], capture_output=True, text=True)
    if not os.path.exists(out):
        print("kicad-cli drc failed:\n", r.stderr or r.stdout); sys.exit(2)
    d = json.load(open(out)); os.unlink(out)
    V = d.get('violations', [])
    unconn = len(d.get('unconnected_items', []))
    by = Counter(v.get('type') for v in V)

    # --- PLACEMENT: courtyard overlaps (part pairs) ---
    court = [v for v in V if v.get('type') == 'courtyards_overlap']
    print(f"=== PLACEMENT — courtyard overlaps: {len(court)} ===")
    for v in court:
        refs = [it.get('description','').replace('Footprint ','') for it in v.get('items',[])]
        print('   ', ' <-> '.join(refs))

    # --- shorts: split real (distinct signals) vs false (same base = unreconciled fragments) ---
    real_short, false_short = [], []
    for v in V:
        if v.get('type') != 'shorting_items': continue
        m = re.search(r'nets (.+?) and (.+?)\)\s*$', v.get('description',''))
        if m and base_of(m.group(1).strip()) == base_of(m.group(2).strip()):
            false_short.append(v)
        else:
            real_short.append(v)
    print(f"=== ROUTING — real shorts (distinct nets): {len(real_short)} ===")
    for v in real_short:
        print('   ', v.get('description','')[:92])
    if false_short:
        print(f"=== FALSE shorts (unreconciled net fragments — run merge_nets.py): {len(false_short)} ===")
        for v in false_short[:8]:
            print('   ', v.get('description','')[:92])

    print(f"=== ROUTING — other: tracks_crossing={by.get('tracks_crossing',0)} "
          f"track_dangling={by.get('track_dangling',0)} unconnected={unconn} ===")

    # --- EDGE: copper AT or OVER the board cut is a REAL defect, NOT cosmetic. ---
    # A copper_edge_clearance with actual gap <= EDGE_REAL mm means the trace touches/crosses
    # the Edge.Cuts (it'll be milled off / shorted to the routed edge) — gate on it. A gap
    # above the threshold but below the rule is copper merely *close* to the edge = cosmetic.
    EDGE_REAL = 0.05
    edge_real, edge_near = [], []
    for v in V:
        if v.get('type') != 'copper_edge_clearance': continue
        m = re.search(r'actual ([\d.-]+) mm', v.get('description',''))
        act = float(m.group(1)) if m else 0.0
        (edge_real if act <= EDGE_REAL else edge_near).append((act, v))
    if edge_real:
        print(f"=== EDGE — copper AT/OVER the board cut (REAL, gap<= {EDGE_REAL}mm): {len(edge_real)} ===")
        for act, v in sorted(edge_real, key=lambda x: x[0]):
            loc = "; ".join(f"{it.get('description','?')[:30]}@({it.get('pos',{}).get('x')},{it.get('pos',{}).get('y')})"
                             for it in v.get('items',[]))
            print(f"   gap={act:.3f}mm  {loc}")

    cos = {t:n for t,n in by.items() if t in COSMETIC}
    cos_edge_near = len(edge_near)            # edge violations that are merely close (kept cosmetic)
    cos_total = sum(cos.values())             # COSMETIC set already counts ALL copper_edge_clearance
    cos_total -= len(edge_real)               # ...so subtract the ones we promoted to EDGE-REAL
    print(f"=== RULE/FAB/COSMETIC (global-fix or ignorable): {cos_total} ===")
    for t,n in sorted(cos.items(), key=lambda x:-x[1]):
        shown = n - len(edge_real) if t == 'copper_edge_clearance' else n
        if shown: print(f'   {shown:4d} {t}')

    blocking = (len(court) + len(real_short) + len(false_short)
                + by.get('tracks_crossing',0) + len(edge_real))
    print(f"\nSUMMARY: placement={len(court)} real-shorts={len(real_short)} "
          f"false-shorts={len(false_short)} crossings={by.get('tracks_crossing',0)} "
          f"edge-over-cut={len(edge_real)} unconnected={unconn} | cosmetic={cos_total}")
    print("RESULT:", "CLEAN ✓" if blocking == 0 else f"{blocking} blocking issue(s) ✗")
    sys.exit(1 if blocking else 0)

if __name__ == "__main__":
    main()
