#!/usr/bin/env bash
# routecheck.sh — the ENCODED "iterate until routing converges" metric.
#
# Builds each module standalone under a timeout and reports, per block:
#   UNROUTED  — nets the router gave up on  (grep 'Could not find a route')
#   TIME      — wall-clock seconds to build/route  ("runs faster" lever)
#   PASS      — unrouted==0 AND clean exit
# Ground truth is the LOG, not trace counts (which lie — "1 passed" + high
# trace count can still hide unrouted nets). Drive UNROUTED -> 0 and TIME down
# by refining placement (edge-aware moves, decap layer=bottom, declaration
# order), re-running, and watching the numbers fall.
#
#   bash scripts/routecheck.sh                 # all modules/*.circuit.tsx
#   bash scripts/routecheck.sh mcu audio       # a subset
#   TIMEOUT=180 bash scripts/routecheck.sh     # raise the per-block cap
set -u
cd "$(dirname "$0")/.." || exit 1
export PATH="$HOME/.bun/bin:$PATH"
TSCI=./node_modules/.bin/tsci
TIMEOUT=${TIMEOUT:-120}
LOGDIR=build/routecheck
mkdir -p "$LOGDIR"

mods=("$@")
if [ ${#mods[@]} -eq 0 ]; then
  for f in modules/*.circuit.tsx; do
    [ -e "$f" ] && mods+=("$(basename "$f" .circuit.tsx)")
  done
fi
[ ${#mods[@]} -eq 0 ] && { echo "no modules found in modules/"; exit 1; }

printf '%-12s %9s %8s %7s  %s\n' MODULE UNROUTED TIME PASS NOTE
printf '%-12s %9s %8s %7s  %s\n' "------" "--------" "----" "----" "----"
fail=0
for m in "${mods[@]}"; do
  f="modules/$m.circuit.tsx"
  [ -e "$f" ] || { printf '%-12s %9s\n' "$m" "MISSING"; fail=1; continue; }
  log="$LOGDIR/$m.log"
  start=$(date +%s.%N)
  timeout "$TIMEOUT" $TSCI build "$f" --disable-parts-engine --pcb-only >"$log" 2>&1
  rc=$?
  end=$(date +%s.%N)
  dt=$(awk "BEGIN{printf \"%.1f\", $end-$start}")
  if [ $rc -eq 124 ]; then
    printf '%-12s %9s %7ss %7s  %s\n' "$m" "?" "$dt" "TIMEOUT" "exceeded ${TIMEOUT}s — split this block"
    fail=1; continue
  fi
  un=$(grep -c 'Could not find a route' "$log")
  # Only SPECIFIC fatals count — tsci prints a generic "Build completed with
  # errors" (and exits 0) for benign unconnected NC/mounting pads; ignore it.
  err=$(grep -iE 'does not have a footprint|has no footprint|no ports|cannot find module|is not exported|not exported from|SyntaxError|TypeError:|ReferenceError|Unexpected token|failed to resolve' \
        "$log" | head -1 | tr -s ' ')
  if [ "$un" -eq 0 ] && [ -z "$err" ]; then pass=yes; else pass=NO; fail=1; fi
  note=""; [ -n "$err" ] && note="${err:0:46}"
  printf '%-12s %9s %7ss %7s  %s\n' "$m" "$un" "$dt" "$pass" "$note"
done
echo ""
[ $fail -eq 0 ] && echo "all blocks converged (0 unrouted)." || echo "refine placement on the NO/▲ rows, then re-run. logs in $LOGDIR/"
exit $fail
