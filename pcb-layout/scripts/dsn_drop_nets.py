#!/usr/bin/env python3
"""Remove nets from a Specctra DSN so Freerouting won't route them (used to route
SIGNALS ONLY on a 4-layer board — GND/PWR are carried by inner-plane zones + via
stitching added in KiCad, not by the autorouter).

Drops each net's (net ...) block from (network) and its name from every (class ...).

    python3 dsn_drop_nets.py build/index.dsn GND V3V3
"""
import re
import sys

dsn = sys.argv[1]
drops = sys.argv[2:]
t = open(dsn).read()

# resolve full ids (NAME or NAME_source_net_N)
ids = []
for base in drops:
    for m in re.finditer(r'\(net\s+"(' + re.escape(base) + r'(?:_source_net_\d+)?)"', t):
        ids.append(m.group(1))

for nid in ids:
    # remove the (net "<nid>" (pins ...)) block (balanced enough: net block has one nested (pins ...))
    t = re.sub(r'\(net\s+"' + re.escape(nid) + r'"\s*\(pins[^)]*\)\s*\)\s*', "", t)
    # remove the name from any class list
    t = t.replace(f'"{nid}"', "")

open(dsn, "w").write(t)
print(f"dropped {len(ids)} net(s): {ids}")
