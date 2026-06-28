#!/usr/bin/env python3
"""apply_fab_rules.py — set a board's DRC rules to a fab's real minimums (default JLCPCB).

KiCad's DEFAULT rules are stricter than any cheap fab, so a perfectly fabbable tscircuit board
shows "hundreds of violations" that are pure rule-mismatch (0.2mm clearance vs JLC's 0.127, a
0.5mm copper-edge rule, 0.8mm min silk text, plus library-mismatch warnings for footprints that
are embedded rather than in a KiCad library). Those rules live in the .kicad_pro project file
(not the .kicad_pcb), so this patches them there. kicad-cli pcb drc then reads them; reload the
project in the GUI to see it there too.

Cosmetic checks that don't apply to a generated board (lib_footprint_mismatch, silk overlaps,
back-layer text) are set to 'ignore'/'warning' — NOT the real ones (shorts, unconnected, courtyard).

Usage:  python3 apply_fab_rules.py <board.kicad_pro> [--fab jlcpcb]
"""
import sys, json

FABS = {
    "jlcpcb": dict(clearance=0.127, track_width=0.15, via_dia=0.6, via_drill=0.3,
                   min_copper_edge_clearance=0.2, min_text_height=0.25, min_hole_to_hole=0.5),
    "oshpark": dict(clearance=0.1524, track_width=0.1524, via_dia=0.762, via_drill=0.3302,
                    min_copper_edge_clearance=0.2, min_text_height=0.25, min_hole_to_hole=0.5),
}
# checks that don't apply to a tscircuit-generated board -> downgrade so they stop cluttering DRC
SEVERITY = {
    "lib_footprint_mismatch": "ignore", "lib_footprint_issues": "ignore",
    "footprint_type_mismatch": "ignore", "silk_over_copper": "warning",
    "silk_overlap": "warning", "silk_edge_clearance": "warning",
    "text_height": "ignore", "text_thickness": "ignore",
    "nonmirrored_text_on_back_layer": "ignore", "solder_mask_bridge": "warning",
}

def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    path = sys.argv[1]
    fab = (sys.argv[sys.argv.index("--fab") + 1] if "--fab" in sys.argv else "jlcpcb").lower()
    f = FABS.get(fab)
    if not f:
        print(f"unknown fab {fab}; choose {list(FABS)}"); sys.exit(1)
    d = json.load(open(path))
    ds = d.setdefault("board", {}).setdefault("design_settings", {})

    rules = ds.setdefault("rules", {})
    rules["min_copper_edge_clearance"] = f["min_copper_edge_clearance"]
    rules["min_text_height"] = f["min_text_height"]
    rules["min_hole_to_hole"] = f["min_hole_to_hole"]

    for c in d.setdefault("net_settings", {}).setdefault("classes", [{"name": "Default"}]):
        if c.get("name") == "Default":
            c["clearance"] = f["clearance"]; c["track_width"] = f["track_width"]
            c["via_diameter"] = f["via_dia"]; c["via_drill"] = f["via_drill"]

    sev = ds.setdefault("rule_severities", {})
    changed = 0
    for k, v in SEVERITY.items():
        if k in sev and sev[k] != v:
            sev[k] = v; changed += 1
        elif k not in sev:
            sev[k] = v; changed += 1

    json.dump(d, open(path, "w"), indent=2)
    print(f"apply_fab_rules ({fab}): Default clearance->{f['clearance']} track->{f['track_width']}, "
          f"copper-edge->{f['min_copper_edge_clearance']}, min-text->{f['min_text_height']}; "
          f"{changed} cosmetic severities downgraded. Reload the project in KiCad to apply in the GUI.")

if __name__ == "__main__":
    main()
