"""import_pcb.py — bring a board into a build123d/CAD assembly as an STL. Two sources:

  *.kicad_pcb -> kicad-cli STEP: the ROUTED board, BARE (tscircuit footprints carry no KiCad 3D
                 models). Y-mirrored (KiCad is Y-down). -> build/pcb.stl. Clean flat plate; best
                 for layer registration (outline/cutouts/screws vs the frame).
  *.tsx       -> tsci export -f step: the POPULATED board WITH component bodies (cad_components +
                 EasyEDA models from modelcdn.tscircuit.com). Already centered + Y-up (no mirror).
                 -> build/pcb_pop.stl. Best for connector/display protrusion + clearance.

    python3 import_pcb.py board.kicad_pcb [--frame W,H]   # bare
    python3 import_pcb.py board.tsx                       # populated (needs network; tsci on PATH)

Notes: kicad-cli exits nonzero on benign warnings (trust the file); a <copperpour> throws a benign
async error in tsci's 3D render but the file still writes; tsci mangles an absolute -o (strips the
leading /) so write a project-relative path. Verify the mirror via a known asymmetric feature.
"""
import subprocess, os, sys, argparse, shutil
from build123d import import_step, export_stl, Pos, mirror, Plane


def export_step(src):
    src = os.path.abspath(src)
    if src.endswith(".tsx"):
        cwd = os.path.dirname(src)                       # run tsci where the tsx + node_modules live
        env = {**os.environ, "PATH": f"{os.environ['HOME']}/.bun/bin:{os.environ.get('PATH','')}"}
        tsci = shutil.which("tsci") or os.path.join(cwd, "node_modules", ".bin", "tsci")
        subprocess.run([tsci, "export", src, "-f", "step", "-o", "_pop.step"],
                       cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
        p = os.path.join(cwd, "_pop.step")
        return p if os.path.exists(p) else None
    out = "/tmp/_pcb_fit.step"
    subprocess.run(["kicad-cli", "pcb", "export", "step", "--subst-models", "--no-dnp", "-o", out, src],
                   capture_output=True, text=True)
    return out if os.path.exists(out) else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("src", help="board.kicad_pcb (bare) or board.tsx (populated)")
    ap.add_argument("--frame", default=None, help="W,H mm of the enclosure outline (bare delta check)")
    ap.add_argument("-o", "--out", default=None)
    a = ap.parse_args()
    populated = a.src.endswith(".tsx")
    out = a.out or os.path.join("build", "pcb_pop.stl" if populated else "pcb.stl")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)

    step = export_step(a.src)
    if not step:
        sys.exit(f"3D export produced no file for {a.src}")
    s = import_step(step)
    bb = s.bounding_box()
    s = Pos(-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z) * s   # center XY, z>=0
    if not populated:
        s = mirror(s, Plane.XZ)                          # KiCad Y-down -> CAD Y-up
    export_stl(s, out)
    b = s.bounding_box()
    print(f"{'populated (+bodies)' if populated else 'bare (routed)'}: "
          f"{b.size.X:.1f} x {b.size.Y:.1f} x {b.size.Z:.2f} mm -> {out}")
    if a.frame and not populated:
        fw, fh = (float(v) for v in a.frame.split(","))
        dx, dy = b.size.X - fw, b.size.Y - fh
        print(f"  vs enclosure {fw}x{fh}: {'MATCH' if abs(dx)<1 and abs(dy)<1 else f'DELTA {dx:+.1f},{dy:+.1f} mm'}")


if __name__ == "__main__":
    main()
