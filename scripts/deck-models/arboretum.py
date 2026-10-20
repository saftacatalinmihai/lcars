"""The arboretum's props (docs/design/deck-style.md part 2, "Arboretum"):
lcars-ui/deck/arboretum.glb, one 1024² atlas. Two pieces of furniture, each
at most 1.5k triangles, over their code-built stand-ins in deck.html
(buildArboretum, bench()):

- `fountain`, the pond's: a stone basin 1.2 m across on a turned pedestal,
  its underside fluted, its lip carved in scallops. The water in it stays
  the stand-in's disc in the page's pondMat (kept over the model: the atlas
  has no ripples or reflections), at 0.85, in the basin's 0.52 m bore;
- `garden_bench`, over each of the room's four benches: wood slats on
  cast metal ends (the concourse's are its own, curved round its plinth:
  ringBench() and concourse.py's `ring_bench`).

    blender -b --factory-startup -P scripts/deck-models/arboretum.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported), its origin its stand-in's: the fountain's on the pond's
floor under its axis, the bench's on the floor at the middle of its seat
(bench()'s group; its sitters face its local +z, here -Y, and its seat's
top is at 0.46, where the page seats them).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402

# the arboretum's, from deck-style.md part 1: the bench wood; the stone a
# shade lighter and warmer than the stepping stones (#9a9284) so the basin
# reads against them; cast iron, near black with a green cast
C.PALETTE.update({
    "arb_stone": (0xa89e8c, 0.9, 0.0, None),
    "bench_wood": (0x7a5a3e, 0.6, 0.0, "grain"),
    "cast_iron": (0x262a26, 0.55, 0.6, None),
})


def mottle(name, other, scale, bump=0.0):
    """The palette's `name` with its colour broken up by a noise toward
    `other` (weathering, a stone's veins), and for stone a coarser relief
    than common's details: baked into the atlas's colour and normal."""
    m = C.mat(name)
    nt = m.node_tree
    b = nt.nodes["Principled BSDF"]
    tc = nt.nodes.new("ShaderNodeTexCoord")
    n = nt.nodes.new("ShaderNodeTexNoise")
    n.inputs["Scale"].default_value = scale
    n.inputs["Detail"].default_value = 6
    nt.links.new(tc.outputs["Object"], n.inputs["Vector"])
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position, ramp.color_ramp.elements[1].position = 0.35, 0.7
    ramp.color_ramp.elements[0].color = b.inputs["Base Color"].default_value[:]
    ramp.color_ramp.elements[1].color = (*C.hex_rgb(other), 1)
    nt.links.new(n.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    if bump and not b.inputs["Normal"].links:
        bu = nt.nodes.new("ShaderNodeBump")
        bu.inputs["Distance"].default_value = 0.004
        bu.inputs["Strength"].default_value = bump
        nt.links.new(n.outputs["Fac"], bu.inputs["Height"])
        nt.links.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def drop_floor_faces(ob):
    """Faces on the floor looking down: never seen, atlas space wasted."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    gone = [f for f in bm.faces if f.normal.z < -0.99 and max(v.co.z for v in f.verts) < 0.002]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def carve(ob, z0, z1, lobes, depth, absolute=False):
    """Push the verts between heights z0 and z1 in and out round the axis:
    `lobes` scallops or flutes, `depth` of the radius (|cos|: flutes with a
    sharp arris between them; plain cos: a wavy scalloped edge)."""
    for v in ob.data.vertices:
        if z0 <= v.co.z <= z1:
            r = math.hypot(v.co.x, v.co.y)
            if r < 1e-4:
                continue
            a = math.atan2(v.co.y, v.co.x)
            c = math.cos(lobes * a)
            k = 1 + depth * (abs(c) if absolute else c)
            v.co.x *= k
            v.co.y *= k


# ---------------------------------------------------------------- fountain
# The stand-in (buildArboretum): a pedestal to 0.56 and a bowl from there to
# 0.88, 1.2 across at the top, the water at 0.855, 0.53 m round. The pond's
# own water is at 0.04: the plinth stands in it.
def fountain():
    ped = C.lathe("ped", [(0.44, 0.0), (0.44, 0.07), (0.41, 0.1), (0.3, 0.12), (0.22, 0.16), (0.17, 0.24), (0.15, 0.36),
                          (0.17, 0.44), (0.21, 0.5), (0.25, 0.57)], "arb_stone", steps=20)
    # the basin, turned: the fluted underside, a bead, the lip's roll, the
    # bore down to the water and a floor under it (hidden by the water)
    bowl = C.lathe("bowl", [(0.22, 0.56), (0.36, 0.6), (0.48, 0.66), (0.56, 0.735), (0.585, 0.755), (0.585, 0.785),
                            (0.6, 0.81), (0.612, 0.845), (0.6, 0.875), (0.575, 0.885), (0.545, 0.88), (0.528, 0.86),
                            (0.52, 0.82), (0.0, 0.81)], "arb_stone", steps=40)
    carve(bowl, 0.59, 0.74, 10, 0.035, absolute=True)   # gadroons
    carve(bowl, 0.8, 0.86, 10, 0.018)                   # the lip's scallops
    ob = C.join("fountain", [ped, bowl])
    drop_floor_faces(ob)
    return C.smooth(ob, 50)


# ---------------------------------------------------------------- bench
SLAT_L = 1.46


def bench_end(sx):
    x = sx * 0.64
    # the arm and the front leg, one cast piece swept as a round section:
    # from the front foot up, out to a scroll at the arm's front, back
    # along the arm to the back; the back leg rising into the back's upright
    front = [(x, -0.2, 0.0), (x, -0.18, 0.2), (x, -0.17, 0.44), (x, -0.19, 0.56), (x, -0.235, 0.62), (x, -0.235, 0.66),
             (x, -0.2, 0.68), (x, -0.1, 0.665), (x, 0.08, 0.66), (x, 0.24, 0.68)]
    back = [(x, 0.26, 0.0), (x, 0.23, 0.22), (x, 0.215, 0.44), (x, 0.235, 0.6), (x, 0.27, 0.74), (x, 0.3, 0.88)]
    return [C.tube(f"arm{sx}", front, 0.02, "cast_iron"), C.tube(f"leg{sx}", back, 0.022, "cast_iron"),
            # the seat rail the slats lie on, and the foot rail between legs
            C.box(f"rail{sx}", (0.04, 0.44, 0.035), (x, 0.02, 0.425), "cast_iron", bevel=0.006, segments=1),
            C.box(f"foot{sx}", (0.03, 0.44, 0.025), (x, 0.03, 0.1), "cast_iron", bevel=0.005, segments=1)]


def garden_bench():
    parts = []
    # the seat: four slats, its top at 0.46 (the page seats its sitters there)
    for i, y in enumerate((-0.18, -0.075, 0.03, 0.135)):
        parts.append(C.box(f"seat{i}", (SLAT_L, 0.088, 0.03), (0, y, 0.445), "bench_wood", bevel=0.007, segments=1))
    # the back: three slats on a plane leaning back 12 degrees
    for i, z in enumerate((0.56, 0.68, 0.8)):
        s = C.box(f"back{i}", (SLAT_L, 0.022, 0.088), (0, 0.235 + (z - 0.5) * math.tan(math.radians(12)), z), "bench_wood",
                  bevel=0.006, segments=1)
        s.rotation_euler.x = -math.radians(12)   # its top back, toward +Y
        parts.append(s)
    for sx in (-1, 1):
        parts += bench_end(sx)
    # a stretcher under the seat between the ends
    parts.append(C.box("stretch", (1.28, 0.025, 0.025), (0, 0.03, 0.1), "cast_iron", bevel=0.005, segments=1))
    ob = C.join("garden_bench", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


C.clean_scene()
mottle("arb_stone", 0x8e8676, 18, bump=0.4)
mottle("bench_wood", 0x8a7e6e, 6)      # weathered: silvering toward grey
props = [fountain(), garden_bench()]
for p in props:
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
C.finish_room("arboretum", props, size=1024)
