/**
 * Placement helpers — kill the "decoupling caps orphaned at origin" problem.
 *
 * `Decap` places a bypass cap *just outside* a named IC power pin, using the
 * real footprint pin coordinates from lib/pinmap.json (run tools/genpinmap.mjs
 * to regenerate). You still wire it with <trace> as usual; this only handles
 * PLACEMENT — and it's reproducible across every board and variant.
 *
 *   <Decap name="C1" part="RP2350A" ic={U1} pin="IOVDD1" />
 *   <trace from="C1.pin1" to="net.V3V3" /><trace from="C1.pin2" to="net.GND" />
 */
import React from "react"
import pinmap from "./pinmap.json"

type XY = { x: number; y: number }

const lookup = (part: string, pin: string): XY => {
  const p = (pinmap as Record<string, Record<string, XY>>)[part]?.[pin]
  if (!p) throw new Error(`place: no pin "${pin}" on part "${part}" in pinmap.json`)
  return p
}

/** absolute (subcircuit-relative) position of an IC pin, given the IC's origin */
export const pinAt = (part: string, pin: string, ic: XY): XY => {
  const p = lookup(part, pin)
  return { x: ic.x + p.x, y: ic.y + p.y }
}

/** a decoupling cap auto-placed just outside `ic`'s `pin`, nudged off-board-center */
export const Decap = ({
  name, part, ic, pin, value = "100nF", footprint = "0402",
  layer = "top", dist, ...rest
}: any) => {
  const p = lookup(part, pin)
  // bottom-side caps sit *under* the chip (no outward nudge) — co-located AND
  // they free the top layer for signal escape. top-side caps nudge outward.
  const d = dist ?? (layer === "bottom" ? 0 : 1.4)
  const ax = Math.abs(p.x), ay = Math.abs(p.y)
  const ox = ax >= ay ? Math.sign(p.x) * d : 0
  const oy = ay > ax ? Math.sign(p.y) * d : 0
  return (
    <capacitor
      name={name}
      capacitance={value}
      footprint={footprint}
      layer={layer}
      pcbX={ic.x + p.x + ox}
      pcbY={ic.y + p.y + oy}
      {...rest}
    />
  )
}
