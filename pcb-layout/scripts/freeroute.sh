#!/usr/bin/env bash
# freeroute.sh <board.dsn | circuit.tsx> — route a board with FREEROUTING (fast by default).
#
# Back into KiCad: inject the .ses with `apply_ses_ipc.py` (IPC, headless — works with a
# tscircuit-exported DSN, no GUI menus). The old GUI Specctra round-trip is the fallback.
#
# VERSION REALITY (Freerouting v2.1.0, the one that works for tscircuit DSNs):
#   - The `-mp`/`-oit` CLI flags and `router.max_passes` in freerouting.json are IGNORED — it runs to
#     the built-in default (9999 passes). So you CANNOT cap passes; the only bound is the wall timeout.
#   - It writes the .ses ONLY when it CONVERGES (no improvement for a while). A routable board converges
#     in seconds. A board it can't fully route (e.g. keepouts that strand a net) OSCILLATES forever and
#     NEVER writes — so on a timeout you get NO .ses, only the log.
#   - Therefore: for MEASURING a placement, run with a short MAXT and read the unrouted count from the
#     LOG (build/freeroute.log), don't rely on the .ses. For an injectable .ses, the board must converge.
#   - DON'T upgrade to v2.2.x for tscircuit: it needs Java 25 AND its stricter DSN parser REJECTS the
#     tscircuit DSN ("padstack name expected at 'V3V3'"). Stay on v2.1.0 for this flow.
#   MAXT=<wall timeout s, default 120>   (MP/OIT are passed but v2.1.0 ignores them)
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
