#!/usr/bin/env bash
# make_fab.sh — produce a complete fabrication bundle from a routed KiCad board:
# Gerbers (all copper + mask + silk + paste + edge) + Excellon drill + CPL placement
# + LCSC-mapped BOM, with the Gerbers zipped for upload.
#
# JLCPCB is the target; PCBWay / OSHPark / Aisler accept the SAME Gerber+drill zip
# (only the design-rule limits differ — see rules/). The BOM + CPL are JLCPCB-assembly
# format; other assemblers accept the same CSVs or their own re-mapping.
#
#   bash make_fab.sh <board.kicad_pcb> [name]
#
# Outputs into <board-dir>/fab/ :  <name>-gerbers.zip  <name>-bom.csv  <name>-cpl.csv
set -eu
BOARD="${1:?usage: make_fab.sh <board.kicad_pcb> [name]}"
SELF="$(cd "$(dirname "$0")" && pwd)"
DIR="$(cd "$(dirname "$BOARD")" && pwd)"
B="$(basename "$BOARD")"; STEM="${B%.kicad_pcb}"
NAME="${2:-$STEM}"
FAB="$DIR/fab"; mkdir -p "$FAB"
cd "$DIR"

echo "[1/5] Gerbers (all layers + gerber-job)"
kicad-cli pcb export gerbers -o "$FAB/" "$B" >/dev/null
echo "[2/5] Excellon drill"
kicad-cli pcb export drill -o "$FAB/" "$B" >/dev/null
echo "[3/5] CPL / placement -> JLCPCB columns (Designator, Mid X/Y, Layer, Rotation)"
kicad-cli pcb export pos --format csv --units mm --side both -o "$FAB/${NAME}-cpl-raw.csv" "$B" >/dev/null
python3 - "$FAB/${NAME}-cpl-raw.csv" "$FAB/${NAME}-cpl.csv" <<'PYEOF'
import csv, sys
rows = list(csv.DictReader(open(sys.argv[1])))
with open(sys.argv[2], "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])   # JLCPCB CPL header
    for r in rows:
        ref = (r.get("Ref") or "").strip()
        if not ref:                                   # drop mounting-holes / no-designator rows
            continue
        side = (r.get("Side") or "top").strip().capitalize()   # Top / Bottom
        w.writerow([ref, r.get("PosX", ""), r.get("PosY", ""), side, r.get("Rot", "")])
PYEOF
rm -f "$FAB/${NAME}-cpl-raw.csv"
FAB_TGT="${3:-both}"    # jlcpcb | pcbway | both  (Gerbers + CPL are shared across fabs)
echo "[4/5] BOM(s): $FAB_TGT"
case "$FAB_TGT" in jlcpcb|both) python3 "$SELF/gen_bom.py" "$B" --fab jlcpcb -o "$FAB/${NAME}-bom.csv" ;; esac
case "$FAB_TGT" in pcbway|both) python3 "$SELF/gen_bom.py" "$B" --fab pcbway -o "$FAB/${NAME}-bom-pcbway.csv" ;; esac
echo "[5/5] Zip Gerbers + drill -> ${NAME}-gerbers.zip"
cd "$FAB"
rm -f "${NAME}-gerbers.zip"
# standard fab layers: copper (gtl/gbl + g1..g4 inner) / mask / silk / paste / edge / job / drill
FILES=""
for ext in gtl gbl g1 g2 g3 g4 gts gbs gto gbo gtp gbp gm1 gbrjob drl; do
  for f in "$STEM"*."$ext"; do [ -e "$f" ] && FILES="$FILES $f"; done
done
# shellcheck disable=SC2086
zip -jq "${NAME}-gerbers.zip" $FILES
echo "DONE -> $FAB/  (Gerbers + CPL are shared across fabs)"
echo "  JLCPCB:  ${NAME}-gerbers.zip (PCB) + ${NAME}-bom.csv + ${NAME}-cpl.csv"
echo "  PCBWay:  ${NAME}-gerbers.zip (PCB) + ${NAME}-bom-pcbway.csv + ${NAME}-cpl.csv"
echo "  hand-solder (both): ${NAME}-handsolder.csv"
unzip -l "${NAME}-gerbers.zip" | tail -1
