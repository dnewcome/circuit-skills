#!/usr/bin/env python3
"""Post-process a tscircuit 4-layer Specctra DSN so Freerouting treats the inner
layers as power PLANES, not signal layers.

tscircuit exports EVERY copper layer as `(type signal)`, so Freerouting happily
routes signals on the GND/PWR inner layers. Fix: relabel the inner layers
`(type power)` and add `(plane ...)` conduction areas for the GND/PWR nets. Then
Freerouting routes signals only on F.Cu/B.Cu and stitches GND/PWR pins to the
planes with through-vias.

    python3 dsn_4layer_planes.py build/index.dsn \
        --gnd GND --pwr V3V3 --gnd-layer In1.Cu --pwr-layer In2.Cu
"""
import argparse
import re
import sys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dsn")
    ap.add_argument("--gnd", default="GND")
    ap.add_argument("--pwr", default="V3V3")
    ap.add_argument("--gnd-layer", default="In1.Cu")
    ap.add_argument("--pwr-layer", default="In2.Cu")
    ap.add_argument("--inset", type=int, default=300, help="DSN units (1000/mm)")
    ap.add_argument("--no-planes", action="store_true",
                    help="strip wiring + (optionally relabel) only; planes done in KiCad")
    ap.add_argument("--relabel-power", action="store_true",
                    help="also set inner layers (type power) — usually NOT wanted: Freerouting "
                         "honors (plane ...) on SIGNAL-type layers (KiCad format) and ignores it "
                         "when the layer is relabeled power")
    a = ap.parse_args()

    t = open(a.dsn).read()

    # 0) strip tscircuit's malformed (wiring ...) section — it pre-places power
    # vias as `(via (path ...)(net "V3V3"))` which Freerouting can't parse
    # ("padstack name expected at 'V3V3'") and which break plane stitching.
    def strip_section(text, name):
        i = text.find("(" + name)
        if i < 0:
            return text, False
        depth, j = 0, i
        while j < len(text):
            if text[j] == "(":
                depth += 1
            elif text[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        return text[:i] + text[j + 1:], True

    t, stripped = strip_section(t, "wiring")

    # 1) relabel inner layers signal -> power
    for ly in (a.gnd_layer, a.pwr_layer):
        t, n = re.subn(r"(\(layer\s+" + re.escape(ly) + r"\s*\(type\s+)signal", r"\1power", t)
        if not n:
            sys.exit(f"ERROR: layer {ly} not found in DSN")

    # 2) resolve the real net ids (NAME or NAME_source_net_N)
    def netid(base):
        m = re.search(r'\(net\s+"(' + re.escape(base) + r'(?:_source_net_\d+)?)"', t)
        if not m:
            sys.exit(f"ERROR: net {base} not found in DSN")
        return m.group(1)

    gnd_id, pwr_id = netid(a.gnd), netid(a.pwr)

    # 3) board boundary -> inset plane rectangle
    mb = re.search(r"\(boundary\s*\(path pcb 0([-\d\s]+)\)\s*\)", t)
    nums = [int(x) for x in mb.group(1).split()]
    xs, ys = nums[0::2], nums[1::2]
    x1, x2 = min(xs) + a.inset, max(xs) - a.inset
    y1, y2 = min(ys) + a.inset, max(ys) - a.inset

    def plane(net, layer):
        return (f'    (plane "{net}"\n'
                f'      (polygon {layer} 0 {x1} {y1} {x2} {y1} {x2} {y2} {x1} {y2})\n'
                f'    )\n')

    planes = plane(gnd_id, a.gnd_layer) + plane(pwr_id, a.pwr_layer)

    # 4) insert the planes inside (structure ...), right after the (boundary ...) block
    if not a.no_planes:
        t, n = re.subn(r"(\(boundary\s*\(path pcb 0[-\d\s]+\)\s*\))",
                       lambda m: m.group(1) + "\n" + planes.rstrip("\n"), t, count=1)
        if not n:
            sys.exit("ERROR: boundary block not found")

    open(a.dsn, "w").write(t)
    print(f"4-layer DSN: wiring-stripped={stripped}; {a.gnd_layer}=power plane({gnd_id}), "
          f"{a.pwr_layer}=power plane({pwr_id}); rect [{x1},{y1}]..[{x2},{y2}]")


if __name__ == "__main__":
    main()
