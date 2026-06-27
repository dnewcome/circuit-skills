/**
 * Fab routing presets (SOURCE side) — spread into every <board> AND <subcircuit>
 * so `tsci export -f kicad_pcb` generates fab-legal TRACK geometry:
 *
 *     import { JLCPCB } from "../lib/fab"
 *     <board {...JLCPCB} ...>            <subcircuit {...JLCPCB} ...>
 *
 * Copy this file into a project's lib/. JLCPCB is the default. See rules/README.md.
 *
 * KNOWN LIMIT: tscircuit's sequential-trace autorouter honors minTraceWidth /
 * defaultTraceWidth but IGNORES the via-size props — exported vias stay
 * 0.3mm pad / 0.2mm drill regardless. Fix vias on the KiCad side (select all
 * vias → set the fab via size), or via the rules/<fab>.kicad_dru + Board Setup.
 */
export const JLCPCB = {
  minTraceWidth: "0.15mm",     // JLC 2-layer standard min track
  defaultTraceWidth: "0.2mm",  // what the autorouter draws
  viaHoleDiameter: "0.3mm",    // (autorouter ignores — see KNOWN LIMIT)
  viaPadDiameter: "0.6mm",     // (autorouter ignores — see KNOWN LIMIT)
}

export const PCBWAY = {
  minTraceWidth: "0.15mm", defaultTraceWidth: "0.2mm",
  viaHoleDiameter: "0.3mm", viaPadDiameter: "0.6mm",
}

export const OSHPARK = {        // 6mil / 0.33mm-drill / 0.2mm-clearance service
  minTraceWidth: "0.1524mm", defaultTraceWidth: "0.2032mm",
  viaHoleDiameter: "0.33mm", viaPadDiameter: "0.7mm",
}
