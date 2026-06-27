#!/usr/bin/env python3
"""merge_nets.py — the net-reconciliation "overview pass" for a modular tscircuit export.

tscircuit scopes `net.X` per <subcircuit>, so a signal shared across modules exports as
SEVERAL net codes that reduce to the same name — e.g. SDA appears as `SDA` (x4, one per
scope) + `J_OLED.SDA to net.SDA`, and V3V3 as 9 codes. Routed, KiCad flags these as FALSE
`shorting_items`. This pass collapses every signal to ONE canonical net by NAME, BEFORE
routing — giving the modular workflow a flat, clean netlist (what you'd get non-modular).

It is the answer to "have common net names between modules where they need to connect":
name shared signals consistently in each module (net.SDA, net.GND, …), then reconcile here.

Grouping (a net's canonical "base"):
  "<anything> to net.<X>"   -> X        (tscircuit's 2-point auto-name)
  "<X>_source_net_<n>"      -> X        (tscircuit's per-scope source nets)
  "<X>"                     -> X        (already-clean name; multiple scopes share it)
Any base with >1 code is merged to one canonical net named <base>. Single-code nets
(VBUS/VBAT/VSYS/… power-internal) are untouched.

Run on the freshly-exported board, BEFORE opening it in KiCad / routing:
    python3 merge_nets.py index.circuit.kicad_pcb [--write]
"""
import sys, re
from collections import defaultdict

def base_of(name):
    m = re.match(r'^.* to net\.([A-Za-z0-9_]+)$', name)
    if m: return m.group(1)
    m = re.match(r'^([A-Za-z0-9_]+)_source_net_\d+$', name)
    if m: return m.group(1)
    return name

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    write = '--write' in sys.argv
    lines = open(path).read().split('\n')

    # --- net table = the CONTIGUOUS block of (net CODE "NAME") lines near the top.
    # Stop at the first non-net line so pad/segment net refs (which reuse the same
    # syntax, deeper in the file) are never mistaken for table entries. ---
    table = {}  # code -> (line_index, name)
    started = False
    for i, l in enumerate(lines):
        m = re.match(r'^\s*\(net (\d+) "(.*)"\)\s*$', l)
        if m:
            table[int(m.group(1))] = (i, m.group(2)); started = True
        elif started:
            break

    groups = defaultdict(list)
    for code, (i, name) in table.items():
        groups[base_of(name)].append(code)

    remap = {}          # fragment code -> canonical code
    canon_name = {}     # canonical code -> base name
    name_to_base = {}   # fragment name -> base  (for zone net_name)
    for b, codes in groups.items():
        if b == "" or len(codes) <= 1:
            continue
        canon = next((c for c in codes if table[c][1] == b), min(codes))
        canon_name[canon] = b
        for c in codes:
            name_to_base[table[c][1]] = b
            if c != canon:
                remap[c] = canon

    if not remap:
        print("no fragmented nets — nothing to merge"); return
    print(f"merging {len(remap)} fragment codes -> {len(canon_name)} canonical nets:")
    for b, codes in sorted(groups.items()):
        if len(codes) > 1 and b:
            print(f"  {b:10s} {sorted(codes)}")

    drop = {table[c][0] for c in remap}  # fragment net-table lines to delete

    out = []
    for i, l in enumerate(lines):
        if i in drop:
            continue
        # canonical net-table (or pad-ref) line: force the name to <base>
        m = re.match(r'^(\s*)\(net (\d+) "(.*)"\)\s*$', l)
        if m and int(m.group(2)) in canon_name:
            out.append(f'{m.group(1)}(net {m.group(2)} "{canon_name[int(m.group(2))]}")')
            continue
        # body refs: (net C "name") , (net C) , (net_name "name")
        def rep_named(mm):
            c = int(mm.group(1))
            return f'(net {remap[c]} "{canon_name[remap[c]]}")' if c in remap else mm.group(0)
        l = re.sub(r'\(net (\d+) "[^"]*"\)', rep_named, l)
        l = re.sub(r'\(net (\d+)\)', lambda mm: f'(net {remap[int(mm.group(1))]})' if int(mm.group(1)) in remap else mm.group(0), l)
        l = re.sub(r'\(net_name "([^"]*)"\)', lambda mm: f'(net_name "{name_to_base[mm.group(1)]}")' if mm.group(1) in name_to_base and name_to_base[mm.group(1)] else mm.group(0), l)
        out.append(l)

    if write:
        open(path, 'w').write('\n'.join(out))
        print("WROTE", path)
    else:
        print("dry run — pass --write to apply")

if __name__ == "__main__":
    main()
