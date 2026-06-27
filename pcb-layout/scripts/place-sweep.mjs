// place-sweep.mjs <module> <ref> <x,y> [<x,y> ...]
//
// Semi-automates the edge-aware placement search that is the 4x routing lever.
// For each candidate position it rewrites the pcbX/pcbY of the element whose
// name="<ref>" in modules/<module>.circuit.tsx, rebuilds the block standalone,
// counts unrouted nets, and prints a table — then RESTORES the file (you apply
// the winning coordinate by hand, deliberately). This is the encoded version of
// "move the flash to the QSPI edge: 16 -> 3 unrouted".
//
//   node scripts/place-sweep.mjs mcu U2 "-2,11" "3,9" "-8,8"
import { readFileSync, writeFileSync, mkdirSync } from "node:fs"
import { execSync } from "node:child_process"

const [mod, ref, ...positions] = process.argv.slice(2)
if (!mod || !ref || positions.length === 0) {
  console.error('usage: node scripts/place-sweep.mjs <module> <ref> "<x,y>" ["<x,y>" ...]')
  process.exit(1)
}
const file = `modules/${mod}.circuit.tsx`
const orig = readFileSync(file, "utf8")

// Find the JSX opening tag that carries name="<ref>" and set its pcbX/pcbY.
function setPos(src, x, y) {
  const tagRe = new RegExp(`<[A-Za-z][\\w.]*\\b[^>]*?\\bname="${ref}"[^>]*?>`)
  const m = src.match(tagRe)
  if (!m) throw new Error(`no element with name="${ref}" in ${file}`)
  let tag = m[0]
  if (/pcbX=\{[^}]*\}/.test(tag)) {
    tag = tag.replace(/pcbX=\{[^}]*\}/, `pcbX={${x}}`)
    tag = /pcbY=\{[^}]*\}/.test(tag)
      ? tag.replace(/pcbY=\{[^}]*\}/, `pcbY={${y}}`)
      : tag.replace(/pcbX=\{[^}]*\}/, (s) => `${s} pcbY={${y}}`)
  } else {
    tag = tag.replace(new RegExp(`name="${ref}"`), `name="${ref}" pcbX={${x}} pcbY={${y}}`)
  }
  return src.replace(m[0], tag)
}

const TSCI = "./node_modules/.bin/tsci"
// Put bun on PATH via the child ENV — NOT as a `PATH=... cmd` prefix, because
// `timeout <dur> PATH=... tsci` makes timeout try to exec "PATH=..." as the
// program (env assignments can't follow the command), so every build fails to
// launch -> empty log -> false 0 unrouted. (Burned an iteration on this.)
const ENV = { ...process.env, PATH: `${process.env.HOME}/.bun/bin:${process.env.PATH || ""}` }
mkdirSync("build", { recursive: true })
// Log to a FILE and grep it (matching routecheck.sh), not execSync stdout.
function unroutedAt(x, y) {
  writeFileSync(file, setPos(orig, x, y))
  const log = `build/sweep_${mod}_${ref}.log`
  try {
    execSync(`timeout 120 ${TSCI} build ${file} --disable-parts-engine --pcb-only > ${log} 2>&1`,
             { stdio: "ignore", env: ENV })
  } catch { /* tsci can exit nonzero; the log file is the ground truth */ }
  let out = ""
  try { out = readFileSync(log, "utf8") } catch { /* no log produced */ }
  return (out.match(/Could not find a route/g) || []).length
}

console.log(`sweep ${ref} in ${file} (${positions.length} positions):`)
const results = []
try {
  for (const pos of positions) {
    const [x, y] = pos.split(",").map(Number)
    const un = unroutedAt(x, y)
    results.push([pos, un])
    console.log(`  (${pos.padEnd(9)}) -> ${un} unrouted`)
  }
} finally {
  writeFileSync(file, orig) // always restore — you apply the winner deliberately
}
const best = [...results].sort((a, b) => a[1] - b[1])[0]
if (best) console.log(`\nbest: (${best[0]}) @ ${best[1]} unrouted — file restored; set it by hand.`)
