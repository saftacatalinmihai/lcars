"""Makes three more hair styles for the deck's crew from the Universal Base
Characters pack's own (CC0), each skinned to the head bone as the pack's
are, into OUT/Hair_<style>.glb for scripts/deck-crew-assets.mjs:

  - Short: TNG's short back-and-sides (a man's): Simple Parted with
    everything below the crown laid down onto the scalp, Buzzed's shape;
  - Bob: Long cut level at the jaw, the ends turned in a little;
  - Ponytail: Long drawn back tight to the scalp above the nape, cut there,
    and a tail from the back of the crown to between the shoulder blades.

The pack's hair is one weighted shell per style, every vertex on the head
bone; what is added here is put on the head bone with it, so the page
binds a new style exactly as an old one (no bones of its own).

Blender 4.3, headless (scripts/deck-crew-build.sh runs it, niced):
  blender -b --factory-startup -P scripts/deck-crew-hair.py -- UBC_DIR OUT_DIR [--preview]
UBC_DIR is the unzipped "Universal Base Characters[Standard]". --preview
renders each style on its body from the front, the side and the back
(OUT/hair-*.png).
"""
import math
import os
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
UBC, OUT = argv[0], argv[1]
PREVIEW = "--preview" in argv
os.makedirs(OUT, exist_ok=True)
HAIR = os.path.join(UBC, "Hairstyles", "Rigged to Head Bone", "glTF (Godot -Unreal)")


def fresh():
    bpy.ops.wm.read_factory_settings(use_empty=True)


def load(name):
    """The pack's hair `name`: its armature and its one mesh."""
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=os.path.join(HAIR, name + ".gltf"))
    new = [o for o in bpy.data.objects if o not in before]
    return next(o for o in new if o.type == "ARMATURE"), next(o for o in new if o.type == "MESH")


def smooth01(a, b, x):
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def onto(mesh, scalp, weight, offset):
    """Each vertex of `mesh` moved toward the closest point of `scalp`'s
    surface (lifted `offset` along its normal) by weight(v) (Blender world
    coordinates: z up, the face toward -y)."""
    dg = bpy.context.evaluated_depsgraph_get()
    sc = scalp.evaluated_get(dg)
    inv = sc.matrix_world.inverted()
    mw, mwi = mesh.matrix_world, mesh.matrix_world.inverted()
    for v in mesh.data.vertices:
        w = mesh.matrix_world @ v.co
        k = weight(w)
        if k <= 0:
            continue
        ok, loc, nor, _ = sc.closest_point_on_mesh(inv @ w)
        if not ok:
            continue
        p = sc.matrix_world @ (loc + nor.normalized() * offset)
        v.co = mwi @ w.lerp(p, k)
    mesh.data.update()


def cut_below(mesh, z):
    """Everything of `mesh` below world height z taken away (the shell left
    open there: it is drawn double-sided)."""
    bm = bmesh.new()
    bm.from_mesh(mesh.data)
    mw = mesh.matrix_world
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if (mw @ v.co).z < z], context="VERTS")
    bm.to_mesh(mesh.data)
    bm.free()


def export(arm, mesh, style):
    for o in list(bpy.data.objects):
        if o not in (arm, mesh):
            bpy.data.objects.remove(o)
    mesh.name = mesh.data.name = "Hair_" + style
    bpy.ops.export_scene.gltf(filepath=os.path.join(OUT, f"Hair_{style}.glb"), export_format="GLB",
                              export_animations=False, export_skins=True, export_yup=True)
    print(f"[deck-crew] Hair_{style}.glb: {len(mesh.data.polygons)} faces")


def short():
    fresh()
    arm, m = load("Hair_SimpleParted")
    _, scalp = load("Hair_Buzzed")
    top = max((m.matrix_world @ v.co).z for v in m.data.vertices)
    # the crown keeps its volume, the sides and back lie down onto the
    # scalp below it (3 mm proud, or the scalp's shell shows through)
    onto(m, scalp, lambda w: 1 - smooth01(top - 0.075, top - 0.03, w.z), 0.003)
    return arm, m


def bob():
    fresh()
    arm, m = load("Hair_Long")
    top = max((m.matrix_world @ v.co).z for v in m.data.vertices)
    jaw = top - 0.2
    cut_below(m, jaw)
    # the ends turned in toward the neck over their last 6 cm
    for v in m.data.vertices:
        w = m.matrix_world @ v.co
        k = 1 - smooth01(jaw, jaw + 0.06, w.z)
        v.co = m.matrix_world.inverted() @ Vector((w.x * (1 - 0.12 * k), w.y * (1 - 0.1 * k) + 0.004 * k, w.z))
    return arm, m


def ponytail():
    fresh()
    arm, m = load("Hair_Long")
    _, scalp = load("Hair_BuzzedFemale")
    top = max((m.matrix_world @ v.co).z for v in m.data.vertices)
    nape = top - 0.17
    cut_below(m, nape)
    # drawn back tight: all but the very top laid onto the scalp
    onto(m, scalp, lambda w: 1 - smooth01(top - 0.06, top - 0.02, w.z), 0.004)
    # the tail: a tapered tube from the back of the crown, out and down
    ys = [(m.matrix_world @ v.co).y for v in m.data.vertices]
    back = max(ys)
    root = Vector((0.0, back - 0.01, top - 0.08))
    path = [root, root + Vector((0, 0.03, -0.04)), root + Vector((0, 0.04, -0.12)), root + Vector((0, 0.035, -0.22)),
            root + Vector((0, 0.025, -0.3))]
    radii = [0.028, 0.03, 0.026, 0.018, 0.008]
    bm = bmesh.new()
    bm.from_mesh(m.data)
    uv = bm.loops.layers.uv.active
    N, rings = 14, []
    for i, (p, r) in enumerate(zip(path, radii)):
        d = (path[min(i + 1, len(path) - 1)] - path[max(i - 1, 0)]).normalized()
        a = Vector((1, 0, 0))
        b = d.cross(a).normalized()
        a = b.cross(d).normalized()
        inv = m.matrix_world.inverted()
        rings.append([bm.verts.new(inv @ (p + (a * math.cos(t) + b * math.sin(t)) * r * (1.0 if math.cos(t) > -0.5 else 0.9)))
                      for t in (2 * math.pi * k / N for k in range(N))])
    for i in range(len(rings) - 1):
        for k in range(N):
            f = bm.faces.new((rings[i][k], rings[i][(k + 1) % N], rings[i + 1][(k + 1) % N], rings[i + 1][k]))
            f.smooth = True
            # the strands run down the tail: v along it, u round it
            for lp, (du, dv) in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lp[uv].uv = ((k + du) / N * 0.4, (i + dv) / (len(rings) - 1))
    bm.normal_update()
    bm.to_mesh(m.data)
    bm.free()
    # the import's custom normals cover only the faces it brought (the new
    # ones would be shaded flat); the shell's own are smooth anyway
    with bpy.context.temp_override(object=m, active_object=m, selected_objects=[m]):
        bpy.ops.mesh.customdata_custom_splitnormals_clear()
        bpy.ops.object.shade_smooth()
    # what was added: on the head bone, as the rest
    g = m.vertex_groups["Head"]
    g.add([v.index for v in m.data.vertices], 1.0, "REPLACE")
    for vg in m.vertex_groups:
        if vg.name != "Head":
            m.vertex_groups.remove(vg)
    return arm, m


def preview(mesh, style):
    sc = bpy.context.scene
    body = os.path.join(UBC, "Base Characters", "Godot - UE",
                        f"Superhero_{'Male' if style == 'Short' else 'Female'}_FullBody.gltf")
    bpy.ops.import_scene.gltf(filepath=body)
    sc.render.engine = "CYCLES"
    sc.cycles.samples = 8
    sc.cycles.use_denoising = False   # this build has no OpenImageDenoise
    sc.render.resolution_x, sc.render.resolution_y = 300, 300
    w = bpy.data.worlds.new("w")
    w.color = (0.6, 0.6, 0.65)
    sc.world = w
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.lens = 85
    sc.collection.objects.link(cam)
    sc.camera = cam
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.rotation_euler = (0.8, 0.2, 0.6)
    sc.collection.objects.link(sun)
    h = max((mesh.matrix_world @ v.co).z for v in mesh.data.vertices) - 0.12
    for side, a in (("front", 0), ("side", 90), ("back", 180), ("three", 135)):
        t = math.radians(a)
        cam.location = (1.4 * math.sin(t), -1.4 * math.cos(t), h)
        cam.rotation_euler = (math.radians(90), 0, t)
        sc.render.filepath = os.path.join(OUT, f"hair-{style}-{side}.png")
        bpy.ops.render.render(write_still=True)


for style, make in (("Short", short), ("Bob", bob), ("Ponytail", ponytail)):
    arm, m = make()
    if PREVIEW:
        preview(m, style)
    export(arm, m, style)
