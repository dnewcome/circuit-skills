#!/usr/bin/env bash
# route4.sh — 4-layer route with Freerouting v2.2.4: signals on F.Cu/B.Cu,
# GND/PWR carried on inner-plane ZONES (In1=GND, In2=V3V3) with the autorouter
# placing the power fanout vias.  The recipe that finally worked:
#
#   * tscircuit exports a 4-layer DSN with ALL copper layers (type signal) AND a
#     malformed (wiring) section (pre-placed power vias) -> dsn_4layer_planes.py
#     strips the wiring + relabels the inner layers (type power) so Freerouting
#     keeps SIGNALS off them and stitches GND/PWR pins to them with vias.
#   * Freerouting v2.2.4 (needs JDK 25 -> freert224) honors (type power) inner
#     layers as planes, writes a PARTIAL .ses (v2.1.0 only writes at 0 unrouted,
#     and crashes with a maze NPE on this board).
#   * KiCad side: add_plane In1=GND / In2=V3V3 zones, inject the .ses, refill, DRC.
#
# Needs: bun/tsci, freert224 (JDK25 + freerouting-2.2.4.jar), kipy, KiCad api server.
set -eu
cd "$(dirname "$0")/.."
export PATH="$HOME/.bun/bin:$PATH"
TSCI=./node_modules/.bin/tsci
SRC=index.circuit.tsx
BOARD=index.circuit.kicad_pcb
DSN=build/index.dsn
SES=build/index.ses
DISPLAY=${DISPLAY:-:0}
mkdir -p build

echo "[1/7] export 4-layer board + dsn"
$TSCI export -f kicad_pcb "$SRC" -o "$BOARD" 2>&1 | grep -iE 'exported|error:' || true
$TSCI export -f specctra-dsn "$SRC" -o "$DSN" 2>&1 | grep -iE 'exported|error:' || true

echo "[2/7] placement gate (parts inside outline)"
node scripts/outline-check.mjs "$SRC" || { [ "${FORCE:-}" = 1 ] || { echo "fix placement"; exit 1; }; }

echo "[3/7] DSN prep: strip wiring + inner layers -> (type power)"
python3 scripts/dsn_4layer_planes.py "$DSN" --no-planes --relabel-power

echo "[4/7] Freerouting v2.2.4 (signals F/B; power fanout vias to inner planes)"
rm -f "$SES"
"$HOME/.local/bin/freert224" -de "$DSN" -do "$SES" 2>&1 | grep -iE 'session completed|unrouted' | tail -1
[ -s "$SES" ] || { echo "no SES written"; exit 1; }
echo "      SES: $(grep -c '(wire' "$SES") wires, $(grep -c '(via' "$SES") vias"

echo "[5/7] (re)launch pcbnew on the fresh board"
pkill -9 java 2>/dev/null || true; rm -f /tmp/kicad/api.sock; sleep 1
DISPLAY="$DISPLAY" setsid pcbnew "$BOARD" >/tmp/pcbnew.log 2>&1 < /dev/null &
for i in $(seq 1 30); do sleep 3; python3 -c "import kipy; kipy.KiCad().get_board()" 2>/dev/null && break; done

echo "[6/7] inner-plane zones In1=GND, In2=V3V3"
python3 scripts/add_plane.py GND In1.Cu --replace 2>&1 | tail -1
python3 scripts/add_plane.py V3V3 In2.Cu --replace --priority 1 2>&1 | tail -1

echo "[7/7] inject signals + power vias, refill, DRC"
python3 scripts/apply_ses_ipc.py "$SES" --save --clear 2>&1 | tail -2
python3 scripts/drc_check.py "$BOARD" 2>&1 | tail -22 || true
echo "DONE — routed $BOARD"
