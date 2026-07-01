#!/bin/bash
# Launch pcbnew, wait for the IPC socket, run the named python IPC script, kill pcbnew.
# Usage: bash scripts/apply_fix.sh scripts/fix_ldo_planes.py
# All output -> build/<script>.log (survives a hard kill).
set +e
PYSCRIPT="$1"
LOG="build/$(basename "$PYSCRIPT" .py).log"
ARGS="$*"
: > "$LOG"
DISPLAY=:0 pcbnew index.circuit.kicad_pcb >build/pcbnew.log 2>&1 &
PID=$!
echo "pcbnew pid=$PID; waiting for /tmp/kicad/api.sock ..." >>"$LOG"
for i in $(seq 1 30); do
  if [ -S /tmp/kicad/api.sock ] && python3 -c "import kipy; kipy.KiCad().get_board()" >/dev/null 2>&1; then
    echo "IPC ready at ~${i}s" >>"$LOG"; break
  fi
  python3 -c "import time; time.sleep(1)"
done
echo "=== running $ARGS ===" >>"$LOG"
python3 $ARGS >>"$LOG" 2>&1
echo "SCRIPT_EXIT=$?" >>"$LOG"
kill $PID 2>/dev/null
python3 -c "import time; time.sleep(1)"
pkill -f 'pcbnew index' 2>/dev/null
echo "done" >>"$LOG"
