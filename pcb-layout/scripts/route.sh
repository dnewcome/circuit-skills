#!/usr/bin/env bash
# route.sh — the repeatable place -> route -> MEASURE pipeline for a tscircuit board + KiCad.
#
# The loop is PLACEMENT-first and FAST: edit placement (code heuristics or nudge in KiCad),
# run this, read the DRC summary, adjust, repeat. The router is capped so it never spins.
#
#   bash scripts/route.sh              # full: export placement -> reconcile nets -> keepout the
#                                      #   board holes -> fast Freerouting -> inject into KiCad -> DRC
#   MP=100 OIT=20 bash scripts/route.sh   # final grind (route to completion, optimize)
#   DISPLAY=:0 bash scripts/route.sh      # X display pcbnew runs on
#
# 4-layer: after [6], add inner-plane zones (route signals only):
#   python3 scripts/add_plane.py GND In1.Cu --replace ; python3 scripts/add_plane.py V3V3 In2.Cu --replace
#
# Needs: tsci (bun), freert, kipy, KiCad with api.enable_server=true.
set -eu
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.bun/bin:$PATH"
TSCI=./node_modules/.bin/tsci
BOARD=index.circuit.kicad_pcb
SRC=index.circuit.tsx
DISPLAY=${DISPLAY:-:0}
mkdir -p build

echo "[1/8] export placement -> $BOARD"
$TSCI export -f kicad_pcb "$SRC" -o "$BOARD" 2>&1 | grep -iE 'exported|error:' || true

echo "[2/8] PLACEMENT GATE — parts must be INSIDE the outline (notch/cutouts) before routing"
# tscircuit has NO keep-in: pcbX/pcbY is manual, so a part can sit in a notch / on a hole.
# This is a PLACEMENT bug (not a router/keepout issue). Fix it before wasting a route.
if ! node scripts/outline-check.mjs "$SRC"; then
  echo "  ^^ parts outside the outline / in a hole — FIX placement, then re-run. Routing a bad"
  echo "     floorplan just hides the problem. (Also eyeball courtyard overlaps via drc_check.)"
  [ "${FORCE:-}" = "1" ] || exit 1
fi

echo "[3/8] reconcile fragmented cross-subcircuit nets (modular flow)"
python3 scripts/merge_nets.py "$BOARD" --write

echo "[3/7] export DSN + keepout the interior board holes (window/reels/screws)"
$TSCI export -f specctra-dsn "$SRC" -o build/index.dsn 2>&1 | grep -iE 'exported|error:' || true
python3 scripts/add_cutout_keepouts.py "$BOARD" build/index.dsn

echo "[4/7] Freerouting (fast; MP=${MP:-12} OIT=${OIT:-0})"
bash scripts/freeroute.sh build/index.dsn
SES=build/index.ses
[ -f "$SES" ] || { echo "no SES produced — see build/freeroute.log"; exit 1; }

echo "[5/7] (re)launch pcbnew on the fresh board so KiCad's model matches the file"
pkill -9 -f "pcbnew.*$(basename "$BOARD")" 2>/dev/null || true
rm -f /tmp/kicad/api.sock; sleep 1
DISPLAY="$DISPLAY" setsid pcbnew "$BOARD" >/tmp/pcbnew.log 2>&1 < /dev/null &
for i in $(seq 1 25); do sleep 3; python3 -c "import kipy; kipy.KiCad().get_board()" 2>/dev/null && break; done

echo "[6/7] add GND pour (tscircuit <copperpour> doesn't export)"
python3 scripts/add_plane.py GND B.Cu --replace

echo "[7/7] inject routing + save, then DRC triage"
python3 scripts/apply_ses_ipc.py "$SES" --save --clear
python3 scripts/drc_check.py "$BOARD" || true
echo "DONE — routed $BOARD (open in KiCad on $DISPLAY)"
