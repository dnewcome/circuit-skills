// outline-check.mjs [circuit.tsx] — the BOARD-OUTLINE RULE.
//
// tscircuit does NOT constrain placement to the board outline: pcbX/pcbY is
// manual, and a part can land in a notch, off the edge, or inside a cutout.
// tscircuit emits `pcb_component_outside_board_error` for off-outline parts, but
// the build only prints a generic "Build completed with errors", so it's easy to
// miss — and it does NOT flag parts sitting inside a <cutout>. This surfaces BOTH.
// Exit 1 if any part is off the outline or in a cutout.
//
//   node scripts/outline-check.mjs                 # index.circuit.tsx
//   node scripts/outline-check.mjs modules/x.circuit.tsx
import { execSync } from "node:child_process"
import { readFileSync, mkdirSync } from "node:fs"

const file = process.argv[2] || "index.circuit.tsx"
const base = file.split("/").pop().replace(/\.circuit\.tsx$/, "").replace(/\.tsx$/, "")
const ENV = { ...process.env, PATH: `${process.env.HOME}/.bun/bin:${process.env.PATH || ""}` }

mkdirSync("build", { recursive: true })
try {
  execSync(`timeout 200 ./node_modules/.bin/tsci build ${file} --pcb-only > build/outline-check.log 2>&1`,
           { stdio: "ignore", env: ENV })
} catch { /* tsci may exit nonzero; the circuit json is the ground truth */ }

let arr
try { arr = JSON.parse(readFileSync(`dist/${base}/circuit.json`, "utf8")) }
catch { console.error(`outline-check: no dist/${base}/circuit.json — build failed (see build/outline-check.log)`); process.exit(2) }

const byId = Object.fromEntries(arr.filter(e => e.pcb_component_id).map(e => [e.pcb_component_id, e]))
const srcById = Object.fromEntries(arr.filter(e => e.source_component_id && e.name).map(e => [e.source_component_id, e]))
const nameOf = (pc) => (pc && srcById[pc.source_component_id]?.name) || pc?.pcb_component_id || "?"

// 1) off the outline — tscircuit's own error (covers notches + off-edge)
const outside = arr.filter(e => e.type === "pcb_component_outside_board_error")

// 2) inside a cutout — AABB overlap of each component's bbox with each cutout rect.
// Parts INTENTIONALLY over a cutout (e.g. an OLED/display behind a window) are allowed:
// ALLOW_IN_CUTOUT="OLED,LCD" (default "OLED").
const allow = new Set((process.env.ALLOW_IN_CUTOUT ?? "OLED").split(",").map(s => s.trim()).filter(Boolean))
const cutouts = arr.filter(e => e.type === "pcb_cutout")
const comps = arr.filter(e => e.type === "pcb_component" && e.center)
const inCutout = []
for (const c of comps) {
  if (allow.has(nameOf(c))) continue   // intentionally over a cutout (display behind a window)
  for (const k of cutouts) {
    const kw = k.width ?? (k.radius ? k.radius * 2 : 0), kh = k.height ?? (k.radius ? k.radius * 2 : 0)
    if (Math.abs(c.center.x - k.center.x) < (c.width + kw) / 2 &&
        Math.abs(c.center.y - k.center.y) < (c.height + kh) / 2) {
      inCutout.push(`${nameOf(c)} overlaps cutout @ (${k.center.x}, ${k.center.y}) ${kw}x${kh}mm`)
    }
  }
}

if (!outside.length && !inCutout.length) {
  console.log("outline-check: all parts inside the board outline, clear of cutouts ✓")
  process.exit(0)
}
if (outside.length) {
  console.log(`outline-check: ${outside.length} part(s) OUTSIDE the board outline:`)
  for (const e of outside) console.log("  ✗ " + e.message)
}
if (inCutout.length) {
  console.log(`outline-check: ${inCutout.length} part(s) INSIDE a cutout:`)
  for (const m of inCutout) console.log("  ✗ " + m)
}
console.log("\nPlacement is manual — tscircuit has no keep-in. Move these onto solid copper.")
process.exit(1)
