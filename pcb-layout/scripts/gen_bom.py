#!/usr/bin/env python3
"""gen_bom.py — build an assembly BOM (JLCPCB or PCBWay format) from a routed KiCad board.

Reads every footprint's (Reference, Value, Footprint) from the .kicad_pcb, resolves a
part record { LCSC, MPN, Manufacturer } for each, groups identical parts, and writes the
CSV that fab's assembly uploader expects. Hand-soldered / mechanical parts go in a
separate <name>-handsolder.csv (kept out of the assembly BOM).

  --fab jlcpcb   ->  Comment, Designator, Footprint, JLCPCB Part #        (sources by LCSC)
  --fab pcbway   ->  Item#, Designator, Qty, Comment, Footprint,
                     Manufacturer Part Number, Manufacturer, LCSC Part No (sources by MPN)

Part data:
  * ICs / connectors — LCSC from imports/*.tsx `supplierPartNumbers`; MPN + Manufacturer
    from IC_INFO (imports' sanitized name isn't a real MPN, so we override).
  * passives — a table of stock-checked JLCPCB BASIC parts with their LCSC + MPN + mfr.

    python3 gen_bom.py index.circuit.kicad_pcb --fab pcbway [-o fab/x-bom-pcbway.csv]
"""
import argparse
import csv
import glob
import os
import re
from collections import defaultdict

# (value, package-substring) -> (LCSC, MPN, Manufacturer)  — stock-checked JLC basic parts
PASSIVES = {
    ("100nF", "0402"): ("C1525", "CL05B104KO5NNNC", "Samsung Electro-Mechanics"),
    ("1uF", "0402"):   ("C52923", "CL05A105KA5NQNC", "Samsung Electro-Mechanics"),
    ("15pF", "0402"):  ("C1548", "0402CG150J500NT", "FH (Guangdong Fenghua)"),
    ("10uF", "0805"):  ("C15850", "CL21A106KAYNNNE", "Samsung Electro-Mechanics"),
    ("1uF", "0805"):   ("C28323", "CL21B105KBFNNNE", "Samsung Electro-Mechanics"),
    ("100nF", "0805"): ("C49678", "CC0805KRX7R9BB104", "YAGEO"),
    ("1k", "0402"):    ("C11702", "0402WGF1001TCE", "UNI-ROYAL(Uniroyal Elec)"),
    ("5.1k", "0402"):  ("C25905", "0402WGF5101TCE", "UNI-ROYAL(Uniroyal Elec)"),
    ("10k", "0402"):   ("C25744", "0402WGF1002TCE", "UNI-ROYAL(Uniroyal Elec)"),
}
# kicad Value -> (real MPN, Manufacturer). LCSC still comes from imports/*.tsx.
IC_INFO = {
    "RP2040": ("RP2040", "Raspberry Pi"),
    "W25Q16JVSSIQ": ("W25Q16JVSSIQ", "Winbond"),
    "AP2112K_3_3TRG1": ("AP2112K-3.3TRG1", "Diodes Incorporated"),
    "TYPE_C_31_M_12": ("TYPE-C-31-M-12", "Korean Hroparts Elec"),
    "X322512MSB4SI": ("X322512MSB4SI", "YXC"),
    "WS2812B_B_T": ("WS2812B-B/T", "Worldsemi"),
}
HAND = [
    (r"chip$", "Cherry MX / Kailh keyswitch — hand solder"),
    (r"pin_?header|pinrow", "pin header — hand solder"),
    (r"push_?button|pushbutton", "tactile switch — hand solder or verify footprint"),
]


def norm(v):
    return v.replace("Ω", "").replace("µ", "u").strip()  # strip Ω, µ->u


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("board")
    ap.add_argument("--fab", choices=["jlcpcb", "pcbway"], default="jlcpcb")
    ap.add_argument("-o", "--out", default=None)
    ap.add_argument("--imports", default="imports")
    a = ap.parse_args()

    ic_lcsc = {}
    for f in glob.glob(os.path.join(a.imports, "*.tsx")):
        t = open(f).read()
        m = re.search(r'manufacturerPartNumber="([^"]+)"', t)
        c = re.search(r'"(C\d{3,})"', t)
        if m and c:
            ic_lcsc[m.group(1)] = c.group(1)

    t = open(a.board).read()
    fps = re.findall(
        r'\(footprint "([^"]+)".*?\(property "Reference" "([^"]*)".*?\(property "Value" "([^"]*)"',
        t, re.S)

    groups = defaultdict(lambda: {"refs": [], "fp": "", "lcsc": "", "mpn": "", "mfr": "", "note": ""})
    for fp, ref, val in fps:
        if not ref or ref.startswith("REF"):
            continue
        vn = norm(val)
        lcsc = mpn = mfr = note = ""
        if val in ic_lcsc:                                  # imported IC/connector
            lcsc = ic_lcsc[val]
            mpn, mfr = IC_INFO.get(val, (val, ""))
        else:
            for (pv, pkg), (l, m, r) in PASSIVES.items():   # passive by value + package
                if vn == norm(pv) and pkg in fp:
                    lcsc, mpn, mfr = l, m, r
                    break
        if not lcsc:
            for pat, n in HAND:                              # hand-solder / mechanical
                if re.search(pat, fp):
                    note = n
                    break
        g = groups[(val, fp, lcsc)]
        g["refs"].append(ref)
        g.update(fp=fp, lcsc=lcsc, mpn=mpn, mfr=mfr, note=note)

    def refs_of(g):
        return ",".join(sorted(g["refs"], key=lambda r: (r[:2], r)))

    def sortkey(item):
        (val, fp, lcsc), g = item
        return (g["refs"][0][:2], val)

    stem = os.path.splitext(os.path.basename(a.board))[0]
    out = a.out or os.path.join("fab", f"{stem}-bom{'-pcbway' if a.fab == 'pcbway' else ''}.csv")
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

    asm = sorted([kv for kv in groups.items() if kv[0][2]], key=sortkey)
    hand = sorted([kv for kv in groups.items() if not kv[0][2]], key=sortkey)

    with open(out, "w", newline="") as fh:
        w = csv.writer(fh)
        if a.fab == "jlcpcb":
            w.writerow(["Comment", "Designator", "Footprint", "JLCPCB Part #"])
            for (val, fp, lcsc), g in asm:
                w.writerow([norm(val) or "?", refs_of(g), fp.split(":")[-1], lcsc])
        else:  # pcbway
            w.writerow(["Item#", "Designator", "Qty", "Comment", "Footprint",
                        "Manufacturer Part Number", "Manufacturer", "LCSC Part No"])
            for i, ((val, fp, lcsc), g) in enumerate(asm, 1):
                w.writerow([i, refs_of(g), len(g["refs"]), norm(val) or "?",
                            fp.split(":")[-1], g["mpn"], g["mfr"], lcsc])

    base = os.path.basename(out).split("-bom")[0]   # keep the same prefix as the BOM file
    hs = os.path.join(os.path.dirname(out), f"{base}-handsolder.csv")
    with open(hs, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["Comment", "Designator", "Footprint", "Note"])
        for (val, fp, _l), g in hand:
            w.writerow([norm(val) or "?", refs_of(g), fp.split(":")[-1], g["note"]])

    n_asm = sum(len(g["refs"]) for _k, g in asm)
    n_hand = sum(len(g["refs"]) for _k, g in hand)
    print(f"[{a.fab}] wrote {out} ({len(asm)} lines, {n_asm} assembled) + {hs} ({n_hand} hand-solder)")


if __name__ == "__main__":
    main()
