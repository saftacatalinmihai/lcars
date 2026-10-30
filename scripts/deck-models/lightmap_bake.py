"""The bake of a room's lightmap: lightmap.py's step 2.

    blender -b --factory-startup -P scripts/deck-models/lightmap_bake.py -- WORK

WORK holds lightmap.py's export: room.glb (the room's lit triangles, one
mesh a material, each corner's `_tri` its triangle's place in its
selection) and meta.json (the lights, the size, the samples). Writes
WORK/lm.png (the light, sRGB, its top strip black: the page's (0, 0), where
everything outside the room samples) and WORK/uv.json (each triangle's
three corners' UVs in its export order, Blender's orientation; the scale).

The page's lights are three's: a point light of `intensity` candela with a
decay of 1.6 and a cutoff at `dist` (three's getDistanceAttenuation). A
Cycles point light falls off as the inverse square, so each is given the
power that matches three's at D0, the floor's and the tables' distance from
the lamps (3.5 m); nearer, the bake is a little brighter, further a little
darker. What a watt gives in the bake is measured first, in a small scene of
its own (a plane 1 m under a light), so the units do not rest on Cycles'
conventions. The value baked is three's irradiance (what its lightMap adds,
before the albedo): stored over `scale`, its 99.7th percentile.
"""
import datetime
import json
import math
import struct
import sys
import zlib

import bmesh
import bpy
import numpy as np

WORK = sys.argv[sys.argv.index("--") + 1]
meta = json.load(open(f"{WORK}/meta.json"))
SIZE, SAMPLES = meta["size"], meta["samples"]
D0 = 3.5
TOP = 12 / SIZE           # the black strip along the top: the page's (0, 0)
MARGIN = 6                # the bake's bleed, in pixels


def srgb_to_lin(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def cycles(scene, samples):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_denoising = False
    scene.cycles.max_bounces = 4
    scene.cycles.diffuse_bounces = 3
    scene.cycles.glossy_bounces = 0
    scene.cycles.transmission_bounces = 0
    scene.render.bake.use_pass_direct = True
    scene.render.bake.use_pass_indirect = True
    scene.render.bake.use_pass_color = False
    scene.render.bake.margin = MARGIN
    if scene.world is None:
        scene.world = bpy.data.worlds.new("black")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0


def bake_target(obj, img):
    for slot in obj.material_slots:
        m = slot.material
        m.use_nodes = True
        nodes = m.node_tree.nodes
        bsdf = next((n for n in nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf:
            bsdf.inputs["Metallic"].default_value = 0
            bsdf.inputs["Roughness"].default_value = 1
            for k in ("Specular IOR Level", "Coat Weight", "Sheen Weight"):
                if k in bsdf.inputs:
                    bsdf.inputs[k].default_value = 0
        t = nodes.new("ShaderNodeTexImage")
        t.image = img
        nodes.active = t


def watt():
    """What one watt of a point light 1 m over a plane bakes to."""
    sc = bpy.context.scene
    cycles(sc, 64)
    me = bpy.data.meshes.new("cal")
    bm = bmesh.new()
    bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=0.05)
    uv = bm.loops.layers.uv.new("lm")
    for f in bm.faces:
        for lp in f.loops:
            lp[uv].uv = (lp.vert.co.x / 0.1 + 0.5, lp.vert.co.y / 0.1 + 0.5)
    bm.to_mesh(me)
    ob = bpy.data.objects.new("cal", me)
    sc.collection.objects.link(ob)
    mat = bpy.data.materials.new("cal")
    mat.use_nodes = True
    me.materials.append(mat)
    img = bpy.data.images.new("cal", 16, 16, float_buffer=True)
    bake_target(ob, img)
    ld = bpy.data.lights.new("cal", "POINT")
    ld.energy = 100
    ld.shadow_soft_size = 0
    lo = bpy.data.objects.new("cal", ld)
    lo.location = (0, 0, 1)
    sc.collection.objects.link(lo)
    for o in sc.objects:
        o.select_set(o is ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.bake(type="DIFFUSE")
    px = np.array(img.pixels[:]).reshape(16, 16, 4)
    for o in list(sc.objects):
        bpy.data.objects.remove(o)
    return float(px[6:10, 6:10, 0].mean()) / 100


# (in background there is no window to switch scenes in: one scene, emptied)
for o in list(bpy.context.scene.objects):
    bpy.data.objects.remove(o)
k = watt()
print(f"[lightmap] a watt at 1 m bakes to {k:.5f}")

sc = bpy.context.scene
cycles(sc, SAMPLES)
bpy.ops.import_scene.gltf(filepath=f"{WORK}/room.glb", merge_vertices=False)
objs = [o for o in sc.objects if o.type == "MESH"]

# each face's source (its material's key) and triangle, and its corners as
# exported, before the weld: the weld joins the triangles into surfaces the
# unwrap can lay out in pieces bigger than a triangle, and the corners match
# the exported ones again by position afterwards
src = []           # per object: its key
corners = {}       # (key, tri) -> three exported positions
for o in objs:
    me = o.data
    key = me.materials[0].name if me.materials else o.name
    src.append(key)
    att = next(a for a in me.attributes if a.name.lstrip("_").lower() == "tri")
    tri = [0.0] * len(me.vertices)
    att.data.foreach_get("value", tri)
    bm = bmesh.new()
    bm.from_mesh(me)
    lay = bm.faces.layers.int.new("lmtri")
    for f in bm.faces:
        t = int(round(tri[f.verts[0].index]))
        f[lay] = t
        corners[(key, t)] = [tuple(v.co) for v in f.verts]
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=0.0005)
    # smooth across shallow edges (a rounded box's roll), sharp at a corner
    for f in bm.faces:
        f.smooth = True
    for e in bm.edges:
        if len(e.link_faces) == 2 and e.calc_face_angle(0) > math.radians(40):
            e.smooth = False
    bm.to_mesh(me)
    bm.free()
    me.uv_layers.new(name="lm")
    me.uv_layers.active = me.uv_layers["lm"]

# one atlas for the room: every object unwrapped and packed together
bpy.ops.object.select_all(action="DESELECT")
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = objs[0]
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=0.0, area_weight=0.0, scale_to_bounds=False)
bpy.ops.uv.pack_islands(rotate=True, margin_method="FRACTION", margin=2.5 * MARGIN / SIZE)
bpy.ops.object.mode_set(mode="OBJECT")
for o in objs:
    uv = o.data.uv_layers["lm"].data
    for d in uv:
        d.uv = (d.uv[0], d.uv[1] * (1 - TOP))

# the lights, three's units into Cycles' watts
for i, l in enumerate(meta["lights"]):
    ld = bpy.data.lights.new(f"lamp{i}", "POINT")
    c = l["color"]
    ld.color = tuple(srgb_to_lin(((c >> s) & 255) / 255) for s in (16, 8, 0))
    falloff = D0 ** -l["decay"] * max(0.0, 1 - (D0 / l["dist"]) ** 4) ** 2
    ld.energy = l["intensity"] * falloff * D0 ** 2 / k
    ld.shadow_soft_size = 0.08
    lo = bpy.data.objects.new(f"lamp{i}", ld)
    x, y, z = l["p"]
    lo.location = (x, -z, y)    # glTF's +Y up is Blender's +Z
    sc.collection.objects.link(lo)

img = bpy.data.images.new("lm", SIZE, SIZE, float_buffer=True)
img.generated_color = (0, 0, 0, 1)
for o in objs:
    bake_target(o, img)
bpy.ops.object.bake(type="DIFFUSE")
px = np.array(img.pixels[:], dtype=np.float32).reshape(SIZE, SIZE, 4)[:, :, :3]
lit = px.max(axis=2)
scale = float(np.percentile(lit[lit > 0], 99.7)) if (lit > 0).any() else 1.0
v = np.clip(px / scale, 0, 1)
v = np.where(v <= 0.0031308, v * 12.92, 1.055 * np.power(v, 1 / 2.4) - 0.055)
rows = (np.flipud(v) * 255 + 0.5).astype(np.uint8)    # Blender's rows run up, a PNG's down
rows[: int(TOP * SIZE), :8 * 4] = 0                    # (black in any case: the corner exactly)
raw = b"".join(b"\0" + r.tobytes() for r in rows)


def chunk(t, d):
    return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)


png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
open(f"{WORK}/lm.png", "wb").write(png)

# each exported triangle's corners' UVs, matched by position
uvs, lost = {}, 0
for o, key in zip(objs, src):
    me = o.data
    lay = me.attributes["lmtri"]
    uv = me.uv_layers["lm"].data
    out = uvs.setdefault(key, {})
    for poly in me.polygons:
        t = lay.data[poly.index].value
        want = corners.get((key, t))
        if not want or poly.loop_total != 3:
            continue
        got = [(tuple(me.vertices[me.loops[li].vertex_index].co), tuple(uv[li].uv)) for li in poly.loop_indices]
        q = []
        for w in want:
            best = min(got, key=lambda g: sum((a - b) ** 2 for a, b in zip(g[0], w)))
            q.extend(best[1])
        out[str(t)] = [round(x, 6) for x in q]
    lost += sum(1 for (kk, _t) in corners if kk == key) - len(out)
json.dump({"uv": uvs, "scale": scale, "lost": lost, "baked": datetime.date.today().isoformat()}, open(f"{WORK}/uv.json", "w"))
print(f"[lightmap] scale {scale:.4f}, {lost} triangles welded away")
