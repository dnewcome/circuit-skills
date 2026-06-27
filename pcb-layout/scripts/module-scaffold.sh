#!/usr/bin/env bash
# module-scaffold.sh <name> — stamp modules/<name>.circuit.tsx with the canonical
# subcircuit skeleton, so decomposing a board into route-in-isolation blocks is
# mechanical, not a fresh judgement call each time. Every block gets:
#   - a <subcircuit autorouter="sequential-trace">   (predictable router)
#   - a J_<NAME> breakout header                      (composes via buses only)
#   - a bottom GND copperpour                         (kills 60-70% of nets)
#   - a standalone <board> default export             (routes/builds on its own)
#
#   bash scripts/module-scaffold.sh power
set -eu
cd "$(dirname "$0")/.." || exit 1
name="${1:?usage: module-scaffold <name>}"
f="modules/$name.circuit.tsx"
[ -e "$f" ] && { echo "refusing to overwrite existing $f"; exit 1; }
mkdir -p modules
UP=$(printf '%s' "$name" | tr '[:lower:]' '[:upper:]')
Block="$(printf '%s' "$name" | sed -E 's/(^|_)([a-z])/\U\2/g')Block"
cat > "$f" <<EOF
/**
 * ${name} module — one functional block. Routes standalone (sequential-trace),
 * composes into the board via the J_${UP} breakout header. Edge-aware
 * placement: put each support part on the IC edge its signals exit.
 */
import React from "react"
import { JLCPCB } from "../lib/fab"
// import { PART } from "../imports/PART"
// import { Decap } from "../lib/place"

export const ${Block} = ({ name = "${name}", pcbX = 0, pcbY = 0 }: any) => (
  <subcircuit name={name} pcbX={pcbX} pcbY={pcbY} autorouter="sequential-trace" {...JLCPCB}>
    {/* parts — place by pcbX/pcbY, edge-aware. Decoupling via <Decap/>. */}

    {/* breakout header — only these nets cross the block boundary */}
    <pinheader name="J_${UP}" pinCount={2} footprint="pinrow2" pcbX={0} pcbY={9}
      pinLabels={{ pin1: "V3V3", pin2: "GND" }} />

    {/* internal traces */}

    <copperpour connectsTo="net.GND" layer="bottom" />
  </subcircuit>
)

export default () => (
  <board {...JLCPCB} width="30mm" height="24mm"><${Block} /></board>
)
EOF
echo "scaffolded $f  — block <${Block}/>, header J_${UP}"
