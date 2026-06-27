// Parse imports/*.tsx and emit lib/pinmap.json:
//   { "<ComponentFile>": { "<PIN_LABEL>": { x, y } , ... }, ... }
// Coordinates are footprint-relative (mm), straight from each smtpad/plated hole.
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs"
import { join, basename } from "node:path"

const IMPORTS = "imports"
const out = {}

for (const file of readdirSync(IMPORTS).filter((f) => f.endsWith(".tsx"))) {
  const src = readFileSync(join(IMPORTS, file), "utf8")
  const key = basename(file, ".tsx")

  // pin number -> first label
  const labelOf = {}
  for (const m of src.matchAll(/pin(\d+):\s*\[?\s*"([^"]+)"/g)) {
    labelOf[m[1]] = m[2]
  }

  // pin number -> {x,y} from smtpad OR platedhole
  const pos = {}
  const padRe = /portHints=\{\["pin(\d+)"\]\}\s*pcbX="(-?[\d.]+)mm"\s*pcbY="(-?[\d.]+)mm"/g
  for (const m of src.matchAll(padRe)) {
    pos[m[1]] = { x: +(+m[2]).toFixed(3), y: +(+m[3]).toFixed(3) }
  }

  const byLabel = {}
  for (const [pin, p] of Object.entries(pos)) {
    const label = labelOf[pin]
    if (label) byLabel[label] = p
  }
  if (Object.keys(byLabel).length) out[key] = byLabel
}

mkdirSync("lib", { recursive: true })
writeFileSync("lib/pinmap.json", JSON.stringify(out, null, 2))
const sizes = Object.entries(out).map(([k, v]) => `${k}:${Object.keys(v).length}`)
console.log("wrote lib/pinmap.json —", sizes.join("  "))
