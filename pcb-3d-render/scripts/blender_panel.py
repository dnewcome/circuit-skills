"""Headless photoreal render of a PCB/PCBA GLB (pcb-3d-render skill).

  blender -b -P blender_panel.py -- IN.glb OUT.png \
      [--studio] [--emit S] [--samples N] [--res N] [--az deg] [--el deg]

  --studio   bright neutral studio (real green PCB beauty shot). Omit for a dark moody
             world where EMISSIVE materials (lit LEDs) dominate.
  --emit S   Emission Strength for emissive parts (name starts 'led' OR non-black emission).
             glTF caps emissiveFactor at 1, so unboosted LEDs look matte — bump this to glow.
  --az/--el  orbit the auto-framed camera (degrees).

ALWAYS launch with `LC_ALL=C LANG=C` (an OCIO/AgX locale segfault otherwise writes no file),
and never pipe stdout through `head` (SIGPIPE kills the render) — use `tail`.
"""
import bpy, sys, math
from mathutils import Vector, Matrix


def argv():
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    o = {"inp": a[0], "out": a[1], "samples": 200, "res": 1500,
         "az": 34.0, "el": 18.0, "emit": 14.0, "studio": False}
    i = 2
    while i < len(a):
        k = a[i]
        if k in ("--samples", "--res"): o[k[2:]] = int(a[i + 1]); i += 2
        elif k in ("--az", "--el", "--emit"): o[k[2:]] = float(a[i + 1]); i += 2
        elif k == "--studio": o["studio"] = True; i += 1
        else: i += 1
    return o


def aim(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()


def area(name, loc, energy, size, target):
    d = bpy.data.lights.new(name, "AREA"); d.energy = energy; d.size = size
    ob = bpy.data.objects.new(name, d); ob.location = loc
    bpy.context.collection.objects.link(ob); aim(ob, target)


def bbox(objs):
    lo = Vector((1e9,) * 3); hi = Vector((-1e9,) * 3)
    for ob in objs:
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            lo = Vector(map(min, lo, w)); hi = Vector(map(max, hi, w))
    return lo, hi


def main():
    o = argv()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    bpy.ops.import_scene.gltf(filepath=o["inp"])
    model = [ob for ob in sc.objects if ob.type == "MESH"]
    lo, hi = bbox(model); center = (lo + hi) * 0.5; radius = (hi - lo).length * 0.5

    # boost emissive parts so lit LEDs glow (skip in studio mode — real PCB shot)
    if not o["studio"]:
        for m in bpy.data.materials:
            if not m.use_nodes:
                continue
            bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if not bsdf:
                continue
            ec = bsdf.inputs["Emission Color"].default_value
            emissive = (ec[0] + ec[1] + ec[2]) > 0.001
            if m.name.lower().startswith("led") or emissive:
                bsdf.inputs["Emission Strength"].default_value = o["emit"]

    # studio: bright neutral for a real PCB beauty shot; else moody (emission dominates)
    wc, ws, kE, fE, rE = ((0.42, 0.44, 0.48), 0.85, 20, 8, 12) if o["studio"] \
        else ((0.018, 0.02, 0.028), 0.35, 7, 3, 9)
    w = bpy.data.worlds.new("W"); sc.world = w; w.use_nodes = True
    bg = w.node_tree.nodes["Background"]
    bg.inputs[0].default_value = (*wc, 1.0); bg.inputs[1].default_value = ws
    area("key", center + Vector((radius, -radius * 1.3, radius * 1.7)), radius * radius * kE, radius * 2.4, center)
    area("fill", center + Vector((-radius * 1.5, -radius * 0.8, radius * 0.6)), radius * radius * fE, radius * 3, center)
    area("rim", center + Vector((0, radius * 1.6, radius * 1.0)), radius * radius * rE, radius * 1.4, center)
    bpy.ops.mesh.primitive_plane_add(size=radius * 40, location=(center.x, center.y, lo.z - radius * 0.02))
    bpy.context.active_object.is_shadow_catcher = True

    # camera (orbit the auto-framed bbox)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam); sc.camera = cam
    az, el, dist = math.radians(o["az"]), math.radians(o["el"]), radius * 2.9
    cam.location = center + Vector((dist * math.cos(el) * math.sin(az),
                                    -dist * math.cos(el) * math.cos(az),
                                    dist * math.sin(el) + radius * 0.12))
    aim(cam, center)

    # optional fog-glow bloom — Blender 5 removed scene.node_tree; skip gracefully
    try:
        sc.use_nodes = True
        nt = sc.node_tree
        rl = next((n for n in nt.nodes if n.type == "R_LAYERS"), None) or nt.nodes.new("CompositorNodeRLayers")
        cp = next((n for n in nt.nodes if n.type == "COMPOSITE"), None) or nt.nodes.new("CompositorNodeComposite")
        gl = nt.nodes.new("CompositorNodeGlare")
        gl.glare_type = "FOG_GLOW"; gl.quality = "HIGH"; gl.threshold = 0.6; gl.size = 7
        nt.links.new(rl.outputs["Image"], gl.inputs["Image"])
        nt.links.new(gl.outputs["Image"], cp.inputs["Image"])
    except Exception as e:
        print("bloom: skipped (", e, ")")

    # render settings + GPU (Blender 5: refresh_devices(), not get_devices())
    sc.render.engine = "CYCLES"; sc.cycles.samples = o["samples"]
    prefs = bpy.context.preferences.addons["cycles"].preferences
    chosen = None
    for backend in ("OPTIX", "CUDA", "HIP", "ONEAPI", "METAL"):
        prefs.compute_device_type = backend
        try: prefs.refresh_devices()
        except Exception: continue
        if any(d.type == backend for d in prefs.devices):
            for d in prefs.devices: d.use = (d.type == backend)
            chosen = backend; break
    sc.cycles.device = "GPU" if chosen else "CPU"
    print("CYCLES device:", chosen or "CPU")
    sc.render.resolution_x = sc.render.resolution_y = o["res"]
    sc.render.film_transparent = False
    try: sc.view_settings.view_transform = "AgX"
    except Exception: sc.view_settings.view_transform = "Filmic"

    sc.render.filepath = o["out"]
    bpy.ops.render.render(write_still=True)
    print("WROTE", o["out"])


main()
