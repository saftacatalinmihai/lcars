"""Ten Forward's props (docs/design/deck-style.md part 2, "Ten Forward"):
lcars-ui/deck/tenforward.glb. The bar, the tub chair (one model at every
table's three chairs), the table and the bar stool, each over its
code-built stand-in in deck.html (buildTenForward, dressShip); and the two
PADD shelves on the forward wall by the corridor's door
(`tf_padd_shelf_a`, `_b`: common.py's rack and the ready room's two
arrangements, in the ready room's colours, over dressShip's `padShelf`s). The bottles
stay code-built, and so do the bar's lights and its display shelf's glass:
the atlas has no glow and no transparency, so those keep the deck's shared
glow() and M.glass materials and are placed to these measures.

    blender -b --factory-startup -P scripts/deck-models/tenforward.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported), its origin where its stand-in's is: the bar's at the
middle of its straight 8 m on the floor (the stand-in box's), the chair's,
the table's and the stool's under the pedestal's axis.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402

# Ten Forward's own, from deck-style.md part 1 (the chair fabric is the
# page's M.fabric, the table top and bar front the hexes of the room's
# table); kept here rather than in common.PALETTE, which only this room uses
C.PALETTE.update({
    "tf_fabric": (0x544a66, 0.85, 0.0, "weave"),
    "tf_piping": (0x3a3248, 0.7, 0.0, None),
    "tf_top": (0x141416, 0.25, 0.1, None),
    "tf_bar": (0x2a2220, 0.4, 0.2, None),
    "tf_chrome": (0xa4a4aa, 0.3, 0.85, "brushed"),
})


def mesh_object(name, bm, materials):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = C.link(bpy.data.objects.new(name, me))
    for m in materials:
        ob.data.materials.append(C.mat(m))
    return ob


def drop_floor_faces(ob):
    """Faces lying on the floor looking down: never seen, and atlas space
    the rest wants."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    gone = [f for f in bm.faces if f.normal.z < -0.99 and max(v.co.z for v in f.verts) < 0.002]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


# ---------------------------------------------------------------- the bar
# Its path, along the floor: the straight run from the stand-in's -x end
# (x +4 here, turned to the deck's) to x -2.9, then a quarter turn of 0.7 m
# back toward the aft wall (+Y, 1.1 m behind the bar's middle), the curved
# end. `u` across it is toward the front (the path's left), so on the curve
# the front is the outside.
BAR_HALF, BAR_TURN, BAR_R, BAR_WALL = 4.0, -2.9, 0.7, 1.04


def bar_path():
    pts = [((BAR_HALF, 0.0), (0.0, -1.0)), ((BAR_TURN, 0.0), (0.0, -1.0))]
    n = 10
    for k in range(1, n + 1):
        a = -math.pi / 2 - (math.pi / 2) * k / n          # -90 deg round to -180
        c = (BAR_TURN + BAR_R * math.cos(a), BAR_R + BAR_R * math.sin(a))
        pts.append((c, (math.cos(a), math.sin(a))))
    pts.append(((BAR_TURN - BAR_R, BAR_WALL), (-1.0, 0.0)))
    return pts


# the section, (u, z, material of the face up to the next point); the
# floor's edge is left open. A recessed black kick, the panelled front
# with a moulding near its top, the overhang, a padded roll, the top.
BAR_SECTION = [
    (0.33, 0.0, "black"), (0.33, 0.10, "black"), (0.40, 0.12, "tf_bar"), (0.40, 0.86, "console"),
    (0.415, 0.865, "console"), (0.415, 0.895, "console"), (0.40, 0.90, "tf_bar"), (0.40, 0.98, "tf_bar"),
    (0.46, 0.995, "lounge_leather"), (0.485, 1.02, "lounge_leather"), (0.49, 1.05, "lounge_leather"),
    (0.48, 1.085, "lounge_leather"), (0.455, 1.105, "tf_top"), (-0.42, 1.105, "tf_top"), (-0.43, 1.09, "tf_top"),
    (-0.43, 1.05, "tf_top"), (-0.40, 1.04, "tf_bar"), (-0.40, 0.0, None),
]


def bar_body():
    mats = ["black", "tf_bar", "console", "lounge_leather", "tf_top"]
    bm = bmesh.new()
    rings = []
    for (px, py), (nx, ny) in bar_path():
        rings.append([bm.verts.new((px + nx * u, py + ny * u, z)) for u, z, _ in BAR_SECTION])
    for a, b in zip(rings, rings[1:]):
        for i, (_, _, m) in enumerate(BAR_SECTION[:-1]):
            f = bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
            f.material_index = mats.index(m)
    # the open end, in the room: one cap of the section
    cap = bm.faces.new(rings[0])
    cap.material_index = mats.index("tf_bar")
    # in triangles: the exporter computes tangents for tris and quads only,
    # and gives up on the whole glb's for one n-gon
    bmesh.ops.triangulate(bm, faces=[cap])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_object("bar_body", bm, mats)


def bar():
    parts = [bar_body()]
    # the panels: a stile every ~0.8 m along the front, round the curve too
    path = bar_path()
    straight = BAR_HALF - BAR_TURN
    for k in range(1, 9):
        x = BAR_HALF - k * straight / 9
        parts.append(C.box(f"stile{k}", (0.035, 0.016, 0.72), (x, -0.405, 0.5), "console", bevel=0.005, segments=1))
    for k in (3, 6, 9):
        (px, py), (nx, ny) = path[1 + k]
        s = C.box(f"stile_c{k}", (0.035, 0.016, 0.72), (px + nx * 0.405, py + ny * 0.405, 0.5), "console", bevel=0.005, segments=1)
        s.rotation_euler.z = math.atan2(ny, nx) + math.pi / 2
        parts.append(s)
    # the display shelf's posts and rails along the back of the top (its glass
    # and the light under it are the page's: M.glass, glow())
    for x in (3.55, 1.95, 0.35, -1.25, -2.6):
        for y in (0.14, 0.36):
            parts.append(C.box(f"post{x}{y}", (0.018, 0.018, 0.19), (x, y, 1.2), "tf_chrome", bevel=0.004, segments=1))
    for y in (0.14, 0.36):
        parts.append(C.box(f"rail{y}", (6.2, 0.022, 0.012), (0.475, y, 1.295), "tf_chrome", bevel=0.004, segments=1))
    ob = C.join("tf_bar", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- the chair
# The stand-in (tfChair in dressShip): a seat whose top is at 0.52, a shell
# of a back 0.27-0.31 round the seat's middle, a stem, a domed foot of 0.22.
# The tub: a wall round 300 degrees of the seat, highest at the back (0.82)
# and falling over the arms to the seat at the front, upholstered (thick,
# rounded at its rim) with a seam round its outside.
TUB_Z0, TUB_SPAN, TUB_N = 0.42, math.radians(150), 12


def tub_top(a):
    f = (1 + math.cos(a)) / 2       # 1 at the back, 0 at the front
    return 0.57 + 0.25 * f ** 1.3


def tub_r(z):
    return 0.255 + 0.04 * (z - TUB_Z0) / (0.82 - TUB_Z0)


def tub_wall():
    bm = bmesh.new()
    rows = 2
    grid = []
    for k in range(TUB_N + 1):
        a = -TUB_SPAN + 2 * TUB_SPAN * k / TUB_N
        col = []
        for j in range(rows + 1):
            z = TUB_Z0 + (tub_top(a) - TUB_Z0) * j / rows
            r = tub_r(z)
            col.append(bm.verts.new((r * math.sin(a), 0.02 + r * math.cos(a), z)))
        grid.append(col)
    for k in range(TUB_N):
        for j in range(rows):
            bm.faces.new((grid[k][j], grid[k + 1][j], grid[k + 1][j + 1], grid[k][j + 1]))
    ob = mesh_object("tub", bm, ["tf_fabric"])
    C.modifier(ob, "SOLIDIFY", thickness=0.07, offset=0)
    C.modifier(ob, "BEVEL", width=0.025, segments=1, limit_method="ANGLE")
    return ob


def tub_chair():
    parts = [tub_wall()]
    # the seam: piping round the tub's outside, at the same share of its height
    seam = []
    for k in range(TUB_N + 1):
        a = -TUB_SPAN + 2 * TUB_SPAN * k / TUB_N
        z = TUB_Z0 + 0.5 * (tub_top(a) - TUB_Z0)
        r = tub_r(z) + 0.036
        seam.append((r * math.sin(a), 0.02 + r * math.cos(a), z))
    parts.append(C.tube("seam", seam, 0.006, "tf_piping"))
    # the cushion, its welt, the pan it sits in
    parts.append(C.lathe("cushion", [(0, 0.43), (0.24, 0.43), (0.258, 0.45), (0.262, 0.49), (0.252, 0.515), (0.23, 0.528),
                                     (0.12, 0.535), (0, 0.535)], "tf_fabric", steps=12, at=(0, 0.02, 0)))
    welt = [(0.259 * math.sin(2 * math.pi * k / 12), 0.02 + 0.259 * math.cos(2 * math.pi * k / 12), 0.505) for k in range(12)]
    parts.append(C.tube("welt", welt, 0.005, "tf_piping", closed=True))
    # (open at the top: the cushion sits in it)
    parts.append(C.lathe("pan", [(0, 0.37), (0.06, 0.37), (0.2, 0.395), (0.25, 0.412), (0.25, 0.43)], "tf_chrome",
                         steps=12, at=(0, 0.02, 0)))
    # the stem and the domed foot, one turned piece
    parts.append(C.lathe("foot", [(0, 0), (0.22, 0), (0.225, 0.008), (0.205, 0.024), (0.14, 0.045), (0.07, 0.062), (0.036, 0.08),
                                  (0.028, 0.1), (0.028, 0.372), (0, 0.372)], "tf_chrome", steps=12))
    ob = C.join("tub_chair", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- the table
# The stand-in: a top of 0.5 m radius at 0.715-0.765, the turned leg.
def tf_table():
    parts = [C.lathe("top", [(0.476, 0.764), (0, 0.764)], "tf_top", steps=24),
             # the rim: a thin band of metal round the top's edge, rounded, and
             # the underside it is turned from (the leg meets it at r 0.06)
             C.lathe("rim", [(0.06, 0.716), (0.49, 0.716), (0.5, 0.728), (0.5, 0.752), (0.49, 0.764), (0.474, 0.764)],
                     "tf_chrome", steps=24),
             C.lathe("leg", [(0, 0), (0.21, 0), (0.215, 0.008), (0.15, 0.024), (0.085, 0.06), (0.058, 0.16),
                             (0.05, 0.4), (0.056, 0.6), (0.08, 0.67), (0.12, 0.7), (0.06, 0.716)], "tf_chrome", steps=12)]
    ob = C.join("tf_table", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- the stool
# The stand-in (buildTenForward's bar stools, eight along the bar): a
# cushion of 0.19 m radius from 0.73 to 0.812, where the page seats its
# sitter, a pole of 0.025, a footring of 0.14 at 0.28, the chair's domed
# foot. The model is the tub chair's family without the tub: a fabric
# cushion with a rolled edge in a chrome pan, the stem, the footring on two
# spokes. Eight of them have ~4.5 k of the room's 40 k left after the bar,
# the chairs and the tables, so ~550 triangles each, not the 1.5 k
# furniture allows: 10-sided turnings and a four-sided ring section, the
# smoothing doing the rest.
def bar_stool():
    n = 10
    parts = [
        C.lathe("cushion", [(0, 0.752), (0.175, 0.752), (0.19, 0.77), (0.192, 0.79), (0.18, 0.806), (0.1, 0.814),
                            (0, 0.815)], "tf_fabric", steps=n),
        C.lathe("pan", [(0, 0.71), (0.05, 0.71), (0.16, 0.735), (0.182, 0.752), (0.17, 0.762)], "tf_chrome", steps=n),
        C.lathe("foot", [(0, 0), (0.22, 0), (0.225, 0.008), (0.205, 0.024), (0.12, 0.045), (0.045, 0.06), (0.03, 0.08),
                         (0.025, 0.1), (0.025, 0.71), (0, 0.71)], "tf_chrome", steps=n),
    ]
    # the footring: a rounded section turned at r 0.14, and its two spokes
    ring = [(0.128, 0.28), (0.14, 0.268), (0.152, 0.28), (0.14, 0.292), (0.128, 0.28)]
    bm = bmesh.new()
    rows = [[bm.verts.new((r * math.cos(2 * math.pi * k / 16), r * math.sin(2 * math.pi * k / 16), z)) for k in range(16)]
            for r, z in ring[:-1]]
    for j in range(4):
        a, b = rows[j], rows[(j + 1) % 4]
        for k in range(16):
            bm.faces.new((a[k], a[(k + 1) % 16], b[(k + 1) % 16], b[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    parts.append(mesh_object("ring", bm, ["tf_chrome"]))
    for a in (0.0, math.pi / 2):
        s = C.box(f"spoke{a}", (0.26, 0.014, 0.012), (0, 0, 0.28), "tf_chrome")
        s.rotation_euler.z = a
        parts.append(s)
    ob = C.join("bar_stool", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- the mess chair
# A big mess hall's chairs (`deskChair(x, z, rot, M.fabric)` in the mess):
# the seat 0.46 square, its top at 0.51 where the page seats the sitter, a
# back 0.44 x 0.5 at 0.21 behind the post, leaning 0.1, on one post and a
# round foot of 0.22. A hall of more than eight tables cannot have the tub
# chair's 976 four to a table inside its 40 k, so this one is the tub's
# family at a quarter of it: Ten Forward's fabric on a chrome stem, the seat
# and back bevelled once, an 8-sided turning.
def mess_chair():
    parts = [C.box("pan", (0.46, 0.46, 0.04), (0, 0, 0.45), "tf_chrome", bevel=0.01, segments=1),
             C.box("seat", (0.45, 0.45, 0.06), (0, -0.005, 0.48), "tf_fabric", bevel=0.022, segments=1),
             C.box("spine", (0.05, 0.03, 0.3), (0, 0.225, 0.58), "tf_chrome")]
    back = C.box("back", (0.44, 0.06, 0.4), (0, 0.215, 0.8), "tf_fabric", bevel=0.022, segments=1)
    back.rotation_euler.x = -0.1
    parts.append(back)
    parts.append(C.lathe("foot", [(0, 0), (0.22, 0), (0.215, 0.015), (0.08, 0.04), (0.03, 0.06), (0.03, 0.43), (0, 0.43)],
                         "tf_chrome", steps=8))
    ob = C.join("mess_chair", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


C.clean_scene()
props = [bar(), tub_chair(), tf_table(), bar_stool(), mess_chair()]
# the origins are already the stand-ins' (see the docstring); transforms
# applied all the same
for p in props:
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
# (the shelves through finish_props, as every other room's: their bronze's
# lathe caps are ngons the exporter's tangents cannot take)
props += C.finish_props([C.padd_shelf("tf_padd_shelf_a", C.shelf_books("a")), C.padd_shelf("tf_padd_shelf_b", C.shelf_books("b"))])
# 2048: the bar is a hero of 9 m, and at 1024 a chair's share of one atlas
# with it is ~110 px across (docs/design/deck-pipeline.md, decisions)
C.finish_room("tenforward", props, size=2048)
