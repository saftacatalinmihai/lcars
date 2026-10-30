"""A generated prop's fit (deck-remodel.md section 3 item 4: the fit after
gen.py): Tripo's raw glb, its meshes joined, turned about the vertical to
face -Y (the deck's props' front), set on the floor at its footprint's
middle and scaled into its stand-in's box, then written whole as the media
folder's PROP.glb, which build.sh hands the room script for import_pack.

    blender -b --factory-startup -P scripts/deck-models/fit.py -- RAW.glb OUT.glb \\
        --turn DEG (--box W D H | --height H)

--box scales each axis to the stand-in's width (X), depth (Y) and height
(Z): Tripo's proportions are close, not exact, and the page sits people
and pillows at the stand-in's measures. --height scales alike in all
three (a plant has no seat to meet). --turn is the turn that brings the
mesh's front to -Y: Tripo's multiview puts it at +X (bridge-redesign.md
8c, -90); its text road where it pleases (look at the bounds printed
with --turn 0 first). --drop-islands F deletes the loose pieces under F
of the faces. The pedestal recolours and leather pulls the chairs needed
stay with the room script (bridge.py's)."""
import argparse
import math
import os
import sys

import bmesh
import bpy
from mathutils import Matrix

argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser(prog="fit.py")
ap.add_argument("raw")
ap.add_argument("out")
ap.add_argument("--turn", type=float, default=0.0)
# loose pieces under this share of the faces deleted: Tripo leaves wisps
# (a hair of a strand beside the bed's headboard) that bake as dark specks
ap.add_argument("--drop-islands", type=float, default=0.0, metavar="FRACTION")
g = ap.add_mutually_exclusive_group(required=True)
g.add_argument("--box", type=float, nargs=3, metavar=("W", "D", "H"))
g.add_argument("--height", type=float)
a = ap.parse_args(argv)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=a.raw)
meshes = [o for o in bpy.data.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in [o for o in bpy.data.objects if o.type != "MESH"]:
    bpy.data.objects.remove(o)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
o = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = o.data
if a.drop_islands:
    bm = bmesh.new()
    bm.from_mesh(me)
    # welded first, as import_pack does: a UV seam splits a surface into islands
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    seen, gone = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        isl, todo = [], [f]
        seen.add(f)
        while todo:
            x = todo.pop()
            isl.append(x)
            for e in x.edges:
                for y in e.link_faces:
                    if y not in seen:
                        seen.add(y)
                        todo.append(y)
        if len(isl) < a.drop_islands * len(bm.faces):
            gone += isl
    print("FIT dropped", len(gone), "faces in loose pieces")
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bm.to_mesh(me)
    bm.free()
me.transform(Matrix.Rotation(math.radians(a.turn), 4, "Z"))
lo = [min(v.co[i] for v in me.vertices) for i in range(3)]
hi = [max(v.co[i] for v in me.vertices) for i in range(3)]
size = [hi[i] - lo[i] for i in range(3)]
print("FIT raw", os.path.basename(a.raw), "size (x, y, z)", [round(s, 3) for s in size])
k = list(a.box) if a.box else [a.height / size[2]] * 3
if a.box:
    k = [a.box[i] / size[i] for i in range(3)]
me.transform(Matrix.Diagonal((k[0], k[1], k[2], 1)) @ Matrix.Translation(
    (-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])))
# Tripo's own normals are right and its mesh is closed once welded:
# import_pack welds it again and must keep them (bridge-redesign.md 8c, 8f)
bm = bmesh.new()
bm.from_mesh(me)
nt = sum(len(f.verts) - 2 for f in bm.faces)
bm.free()
vs = [v.co for v in me.vertices]
print("FIT tris", nt, "scale", [round(x, 3) for x in k],
      "bounds", [round(min(v[i] for v in vs), 3) for i in range(3)], [round(max(v[i] for v in vs), 3) for i in range(3)])
bpy.ops.export_scene.gltf(filepath=a.out, export_format="GLB", use_selection=False)
