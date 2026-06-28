"""render_fit.py — 3D fit-check: stack the routed PCB against the printed enclosure parts.

Renders two OpenSCAD views from the STLs in build/ (build/pcb.stl from import_pcb.py + your
printed parts):
  build/fit_iso.png  — exploded iso (layers read apart; board cutouts vs shell openings)
  build/fit_top.png  — straight top-down (window / hole / connector alignment)

OpenSCAD is the always-available headless previewer — good enough to judge alignment. For a
beauty render, feed build/pcb.stl into a Blender assembly instead (materials + soft light).

EDIT `LAYERS` for your stack: (stl, z_datum_mm, [r,g,b], explode_dir). Z datums come from your
machine_params (e.g. board at 0, spacer at PCB_T, top at PCB_T+GAP). Run:
    python3 render_fit.py [explode_mm=6]
"""
import os, subprocess, sys

B = "build"
# (stl filename in build/, z datum mm, color, explode direction) — EDIT for your enclosure stack
LAYERS = [
    ("pcb.stl",   0.0,  [0.10, 0.45, 0.20], -1.0),   # the real board (green) — bottom
    ("frame.stl", 1.57, [0.62, 0.63, 0.66],  0.0),   # printed spacer/frame (grey)
    ("panel.stl", 7.43, [0.83, 0.34, 0.06], +1.0),   # printed top face (warm)
]


def scad(explode):
    out = ["$fn=48;"]
    for stl, z, c, ef in LAYERS:
        p = os.path.join(B, stl)
        if os.path.exists(p):
            out.append(f'color([{c[0]},{c[1]},{c[2]}]) translate([0,0,{z + ef*explode:.3f}]) import("{p}");')
    return "\n".join(out)


def render(name, cam, explode):
    s = os.path.join(B, f"_fit_{name}.scad")
    open(s, "w").write(scad(explode))
    out = os.path.join(B, f"fit_{name}.png")
    subprocess.run(["openscad", "-o", out, "--imgsize=1200,800", "--colorscheme=Tomorrow",
                    f"--camera={cam}", "--autocenter", "--viewall", s], capture_output=True)
    print("  ->", out, "OK" if os.path.exists(out) else "FAILED (is openscad installed?)")


def main():
    os.makedirs(B, exist_ok=True)
    expl = float(sys.argv[1]) if len(sys.argv) > 1 else 6.0
    print(f"fit-check render (explode={expl}mm):")
    render("iso", "0,0,0,58,0,22,420", expl)
    render("top", "0,0,0,0,0,0,420", 0.0)


if __name__ == "__main__":
    main()
