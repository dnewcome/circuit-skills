#!/usr/bin/env python3
"""add_cutout_keepouts.py — auto-keepout every INTERIOR closed path in the board outline.

Detects closed Edge.Cuts shapes inside the main outer outline (window, reel/drive holes,
screw holes — whether they came in as gr_line loops, gr_poly, or gr_circle) and writes a
per-copper-layer keepout for each into the Specctra DSN, so Freerouting never routes across
a board hole. The OUTER outline (largest bbox) is left alone; everything inside it is keepout.

The kicad_pcb -> DSN transform is derived by matching the outer Edge.Cuts bbox to the DSN
boundary bbox (handles the +100mm offset, the ~1000 u/mm scale, and the Specctra Y-flip).

Usage:  python3 add_cutout_keepouts.py <board.kicad_pcb> <board.dsn> [--margin MM]
"""
import sys, re
from collections import defaultdict

def opt(flag, d):
    return float(sys.argv[sys.argv.index(flag)+1]) if flag in sys.argv else d

def edge_shapes(txt):
    """Return list of bboxes (minx,miny,maxx,maxy) for each closed Edge.Cuts shape."""
    bboxes = []
    # gr_circle: bbox = center +/- r
    for m in re.finditer(r'\(gr_circle\s*\(center ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,160}?\(layer Edge\.Cuts\)', txt):
        cx,cy,ex,ey = map(float, m.groups()); r = ((ex-cx)**2+(ey-cy)**2)**0.5
        bboxes.append((cx-r, cy-r, cx+r, cy+r))
    # gr_poly: bbox of pts
    for m in re.finditer(r'\(gr_poly\s*\(pts((?:\s*\(xy [-\d.]+ [-\d.]+\))+)\s*\)[\s\S]{0,200}?\(layer Edge\.Cuts\)', txt):
        pts = [(float(a),float(b)) for a,b in re.findall(r'\(xy ([-\d.]+) ([-\d.]+)\)', m.group(1))]
        xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        bboxes.append((min(xs),min(ys),max(xs),max(ys)))
    # gr_line: union-find into loops, bbox per loop
    segs=[]
    for m in re.finditer(r'\(gr_line\s*\(start ([-\d.]+) ([-\d.]+)\)\s*\(end ([-\d.]+) ([-\d.]+)\)[\s\S]{0,120}?\(layer Edge\.Cuts\)', txt):
        x1,y1,x2,y2 = map(float, m.groups()); segs.append(((round(x1,3),round(y1,3)),(round(x2,3),round(y2,3))))
    par={}
    def find(p):
        par.setdefault(p,p)
        while par[p]!=p: par[p]=par[par[p]]; p=par[p]
        return p
    for a,b in segs: par[find(a)]=find(b)
    loops=defaultdict(list)
    for a,b in segs: loops[find(a)].append((a,b))
    for ss in loops.values():
        xs=[p[0] for s in ss for p in s]; ys=[p[1] for s in ss for p in s]
        bboxes.append((min(xs),min(ys),max(xs),max(ys)))
    return bboxes

def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    kpcb, dsn = sys.argv[1], sys.argv[2]
    margin = opt("--margin", 0.3)
    ktxt = open(kpcb).read(); dtxt = open(dsn).read()

    bb = edge_shapes(ktxt)
    if not bb:
        print("no Edge.Cuts shapes found"); sys.exit(1)
    area = lambda b: (b[2]-b[0])*(b[3]-b[1])
    outer = max(bb, key=area)
    interiors = [b for b in bb if b is not outer]
    print(f"Edge.Cuts: {len(bb)} closed shapes | outer + {len(interiors)} interior keepout(s)")

    # DSN boundary bbox -> derive kicad(mm) -> DSN(units) transform (offset, scale, Y-flip)
    mb = re.search(r'\(boundary\s*\(path \S+ \S+\s+([-\d.\s]+)\)', dtxt)
    nums = [float(x) for x in mb.group(1).split()]
    dxs = nums[0::2]; dys = nums[1::2]
    dminx,dmaxx,dminy,dmaxy = min(dxs),max(dxs),min(dys),max(dys)
    okx0,oky0,okx1,oky1 = outer
    sx = (dmaxx-dminx)/(okx1-okx0); sy = (dmaxy-dminy)/(oky1-oky0)
    kcx=(okx0+okx1)/2; kcy=(oky0+oky1)/2; dcx=(dminx+dmaxx)/2; dcy=(dminy+dmaxy)/2
    TX = lambda kx: (kx-kcx)*sx + dcx
    TY = lambda ky: dcy - (ky-kcy)*sy          # Specctra Y is up; KiCad Y is down
    layers = [l for l in dict.fromkeys(re.findall(r'\(layer (\S+)', dtxt[:dtxt.index("(placement")])) if l.endswith(".Cu")]

    ko = ""
    for j,(x0,y0,x1,y1) in enumerate(interiors):
        m = margin
        X = sorted([TX(x0-m), TX(x1+m)]); Y = sorted([TY(y0-m), TY(y1+m)])
        for l in layers:
            ko += f'\n    (keepout "cutout{j}_{l}" (rect {l} {int(X[0])} {int(Y[0])} {int(X[1])} {int(Y[1])}))'

    i = dtxt.index("(boundary"); depth=0; e=i
    while e < len(dtxt):
        if dtxt[e]=="(": depth+=1
        elif dtxt[e]==")":
            depth-=1
            if depth==0: break
        e+=1
    dtxt = dtxt[:e+1] + ko + dtxt[e+1:]
    open(dsn,"w").write(dtxt)
    print(f"added {len(interiors)*len(layers)} keepout rect(s) on {layers} (scale {sx:.0f} u/mm)")

if __name__ == "__main__":
    main()
