#!/usr/bin/env bash
# freeroute.sh <board.dsn | circuit.tsx> — route a board with FREEROUTING (fast by default).
#
# Back into KiCad: inject the .ses with `apply_ses_ipc.py` (IPC, headless — works with a
# tscircuit-exported DSN, no GUI menus). The old GUI Specctra round-trip is the fallback.
#
# FAST iteration is the point: cap the passes so the router never spins. Defaults route a
# quick result for measuring a placement; raise the caps for a final grind.
#   MP=<max route passes, default 12>   OIT=<optimization passes, default 0>   MAXT=<wall timeout s, 120>
#   e.g.  MP=100 OIT=20 bash scripts/freeroute.sh build/index.dsn   # final grind
#
# Freerouting = real maze router (ripup-retry, 45 deg). Needs freert (~/.local/bin/freert; FREERT=).
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.bun/bin:$PATH"
FREERT=${FREERT:-$HOME/.local/bin/freert}
MP=${MP:-12}; OIT=${OIT:-0}; MAXT=${MAXT:-120}
arg=${1:-index.circuit.tsx}
mkdir -p build; LOG=build/freeroute.log
[ -x "$FREERT" ] || { echo "freerouting CLI not at $FREERT (set FREERT=)"; exit 1; }

case "$arg" in
  *.dsn) dsn="$arg"; base=$(basename "$dsn" .dsn) ;;
  *) base=$(basename "$arg" | sed -E 's/\.circuit\.tsx$//; s/\.tsx$//')
     timeout 200 ./node_modules/.bin/tsci export "$arg" -f specctra-dsn -o "build/$base.dsn" > "$LOG" 2>&1
     dsn="build/$base.dsn" ;;
esac
[ -f "$dsn" ] || { echo "no DSN found ($dsn) — see $LOG"; exit 1; }
ses="build/$base.ses"

echo "freerouting $dsn  (MP=$MP OIT=$OIT, timeout ${MAXT}s) ..."
rm -f "$ses"
JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" timeout "$MAXT" \
  "$FREERT" -de "$dsn" -do "$ses" -mp "$MP" -oit "$OIT" >> "$LOG" 2>&1
rc=$?
# Freerouting writes an empty "(host_version )" that KiCad's parser rejects; patch it.
[ -f "$ses" ] && sed -i 's/(host_version )/(host_version "freerouting")/' "$ses"
last=$(grep -oE 'score of [0-9.]+ \([0-9]+ unrouted\)' "$LOG" | tail -1)
echo "  ${last:-see $LOG}   (freert rc=$rc)"
if [ -f "$ses" ]; then
  echo "  -> $ses ($(grep -c '(wire' "$ses") wires).  Inject: python3 scripts/apply_ses_ipc.py $ses --save --clear"
else
  echo "  NO .ses written (rc=$rc). If it timed out at the cap, lower MP or check $LOG."
fi
