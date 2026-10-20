"""The corridor's dressing (docs/design/deck-style.md part 2, "Corridor"):
lcars-ui/deck/corridor.glb, one 1024² atlas. Small props placed many times
over by deck.html (corridorDress), and since 0.225.0 (part 6, "ornate
corridors") the corridor's structure too:

- `comm_panel`, over the code-built panel beside each door: a black plate
  with two buttons. Its lit LCARS strip and its indicator stay the
  stand-in's (the shared glow materials, kept over the model: the atlas has
  no emission), set on the plate's face where these measures put them;
- `door_plaque`, on each lintel's corridor face: a brushed bezel round the
  door's name, which stays the page's (its own canvas, kept over the
  model): the bezel's opening is the name plate's 1.1 x 0.2;
- `padd_rack`, a wall rack with two PADDs, at a few places only;
- `rib`, the pilaster over every code-built rib: a chamfered shaft with a
  black channel down its face, a plinth and a capital. The channel's floor
  is the stand-in bar's face, so the bar's light slot and section number
  (the shared glow and the page's canvas, kept over the model) lie in it;
- `alcove_locker`, `alcove_console` and (0.236.0) `alcove_replicator`, a
  wall unit between two ribs here and there: an emergency locker (a red
  cross on black, a handle), a tall LCARS wall unit and a replicator (a
  recess lit from behind a louvre), each in a frame 0.15 proud of the
  wall. No stand-in for the first two: offline the wall is as it was, so
  their LCARS colours are the atlas's, unlit, as the comm panel's buttons
  are. The replicator's lit back is a stand-in's glow plate, kept over the
  model in its recess, so offline the plate is on the wall alone;
- `door_frame` (0.236.0), a surround on each corridor door's corridor face:
  chamfered jambs with the door's amber strip in a channel down each, a
  black reveal inside the opening, and a head with a recess the plaque
  sits in;
- `carpet_border` (0.236.0), the darker band of the corridor's carpet
  along each wall's trim, 1.3 m of it, laid end to end and stretched a
  little to a run's length: in the atlas because a material of its own
  would be a draw call in every corridor cell (deck-style.md part 6 (c)).

    blender -b --factory-startup -P scripts/deck-models/corridor.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported). The panel's origin is its stand-in's, the middle of the
plate (the page's group at the plate's centre); the plaque's and the rack's,
which have no stand-in, the middle of their back face, against the wall;
the rib's and the wall units', the wall's face at the floor (the rib's
stand-in group is there too).
"""
import bmesh  # noqa: E402
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

import common as C  # noqa: E402

# the corridor's, from deck-style.md part 1 (the comm panel and door plate
# hex) and the page's LCARS colours (LC.peach, LC.lilac) for the buttons:
# unlit here, the atlas has no emission; the strip above them is the glow
C.PALETTE.update({
    "comm_black": (0x1e1c1b, 0.4, 0.4, None),
    "lcars_peach": (0xff9966, 0.5, 0.0, None),
    "lcars_lilac": (0xcc99cc, 0.5, 0.0, None),
    "padd_body": (0x8a7a66, 0.55, 0.1, None),
    "padd_screen": (0x0c0b0b, 0.2, 0.0, None),
    # part 6: the rib's channel, the locker's red, an LCARS orange and blue
    "channel": (0x141210, 0.5, 0.2, None),
    "locker_red": (0x7e1a1e, 0.5, 0.1, None),
    "lcars_orange": (0xff9933, 0.5, 0.0, None),
    "lcars_blue": (0x9999ff, 0.5, 0.0, None),
    # 0.236.0: the carpet's border, part 6's #2c3646, with the weave the
    # page's T.carpet has (relief only)
    "carpet_border": (0x2c3646, 0.9, 0.0, "weave"),
})


# A profile [(x, y), ...] in Blender's X-Y plane (one way round, any),
# extruded up Z from z0 to z1: the rib's shaft. Its caps stay off: the
# plinth and the capital cover both ends, and an ngon cap would want cutting
# for the exporter's tangents (common.finish_props).
def zprism(name, poly, z0, z1, material):
    bm = bmesh.new()
    a = [bm.verts.new((x, y, z0)) for x, y in poly]
    b = [bm.verts.new((x, y, z1)) for x, y in poly]
    for i in range(len(poly) - 1):
        bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return C.mesh_of(name, bm, material)


# ---------------------------------------------------------------- rib
# The stand-in (corridorDress): a bar 0.36 wide, 0.08 proud of the wall's
# face (its back 2 cm in), h - 0.4 tall (3.0 in a 3.4 m corridor; the page
# scales the model's height to it), its light slot 0.05 x 0.9 at 1.95 and
# the section number at 1.36 on its face. The pilaster is part 6's 0.32
# wide, 0.10 proud (not 0.14: its channel's floor must be the bar's face,
# 0.08, where the light and the number are), the channel 0.08 wide and 0.02
# deep, the shaft's front corners chamfered 3 cm. The shaft's back is 2 cm
# into the wall and open: nothing sees it.
def rib():
    Hh, P, W, CH, cw = 3.0, 0.10, 0.16, 0.03, 0.04
    shaft = [(-W, 0.02), (-W, -P + CH), (-W + CH, -P), (-cw, -P), (-cw, -P + 0.02),
             (cw, -P + 0.02), (cw, -P), (W - CH, -P), (W, -P + CH), (W, 0.02)]
    parts = [zprism("shaft", shaft, 0.17, Hh - 0.16, "trim"),
             # the channel's black lining, a hair over its floor and walls
             C.box("chan", (2 * cw - 0.002, 0.004, Hh - 0.33), (0, -P + 0.0215, (Hh + 0.01) / 2), "channel"),
             # the plinth: a hand prouder than the shaft, over the skirting
             C.box("plinth", (0.38, 0.15, 0.17), (0, -0.055, 0.085), "console", bevel=0.012, segments=1),
             # the capital: a chamfered step and a slab
             C.box("cap0", (0.35, 0.13, 0.06), (0, -0.045, Hh - 0.13), "trim", bevel=0.015, segments=1),
             C.box("cap1", (0.39, 0.15, 0.07), (0, -0.055, Hh - 0.035), "trim", bevel=0.01, segments=1)]
    ob = C.join("rib", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- wall units
# 1.1 x 2.2 frames 0.15 proud of the wall (part 6: built out, not cut in),
# the face inside at 0.11, past the wainscot rail's 0.08 so the rail dies
# behind it. Origin: the wall's face at the floor, the front -Y.
def frame(tag):
    W, Hh, b, P = 1.1, 2.2, 0.1, 0.15
    parts = [C.box(tag + "fl", (b, P + 0.02, Hh), (-(W - b) / 2, -(P - 0.02) / 2, Hh / 2), "trim", bevel=0.02, segments=1),
             C.box(tag + "fr", (b, P + 0.02, Hh), ((W - b) / 2, -(P - 0.02) / 2, Hh / 2), "trim", bevel=0.02, segments=1),
             C.box(tag + "ft", (W - 2 * b, P + 0.02, b), (0, -(P - 0.02) / 2, Hh - b / 2), "trim", bevel=0.02, segments=1),
             # its foot is the skirting's black, as the rib's plinth
             C.box(tag + "fb", (W - 2 * b, P + 0.02, 0.14), (0, -(P - 0.02) / 2, 0.07), "console", bevel=0.01, segments=1)]
    return parts


def alcove_locker():
    parts = frame("lk")
    # the door, two leaves, a dark seam between them
    parts.append(C.box("door", (0.9, 0.13, 1.96), (0, -0.045, 1.12), "comm_black", bevel=0.006, segments=1))
    parts.append(C.box("seam", (0.008, 0.004, 1.9), (0, -0.111, 1.12), "channel"))
    # the red cross at eye height, on the left leaf
    for sz in ((0.3, 0.08), (0.08, 0.3)):
        parts.append(C.box(f"x{sz[0]}", (sz[0], 0.006, sz[1]), (-0.22, -0.112, 1.6), "locker_red", bevel=0.003, segments=1))
    # the handles, either side of the seam
    for x in (-0.05, 0.05):
        parts.append(C.box(f"h{x}", (0.025, 0.04, 0.32), (x, -0.13, 1.15), "trim", bevel=0.008, segments=1))
    # the label above, an LCARS bar and a lilac cap
    parts.append(C.box("label", (0.5, 0.006, 0.06), (0.05, -0.112, 1.95), "lcars_peach", bevel=0.002, segments=1))
    parts.append(C.box("labelc", (0.1, 0.006, 0.06), (-0.29, -0.112, 1.95), "lcars_lilac", bevel=0.002, segments=1))
    # a grille of slats at its foot
    for i in range(5):
        parts.append(C.box(f"g{i}", (0.6, 0.012, 0.018), (0, -0.112, 0.32 + i * 0.045), "channel"))
    ob = C.join("alcove_locker", parts)
    return C.smooth(ob, 35)


def alcove_console():
    parts = frame("cs")
    parts.append(C.box("face", (0.9, 0.13, 1.96), (0, -0.045, 1.12), "comm_black", bevel=0.006, segments=1))
    # the LCARS frame: a sidebar of blocks down the left, an elbow over the top
    for i, (h, m) in enumerate(((0.36, "lcars_peach"), (0.12, "lcars_lilac"), (0.24, "lcars_orange"), (0.12, "lcars_blue"))):
        z = 1.82 - sum((0.36, 0.12, 0.24, 0.12)[:i]) - 0.02 * i - h / 2
        parts.append(C.box(f"sb{i}", (0.1, 0.006, h), (-0.36, -0.112, z), m, bevel=0.002, segments=1))
    parts.append(C.box("elbow", (0.74, 0.006, 0.07), (0.05, -0.112, 1.965), "lcars_peach", bevel=0.002, segments=1))
    # the screen in a dark-blue field, and a ledge with a row of keys under it
    parts.append(C.box("scr", (0.6, 0.006, 0.62), (0.08, -0.112, 1.5), "padd_screen"))
    for i, m in enumerate(("lcars_blue", "lcars_peach", "lcars_lilac")):
        parts.append(C.box(f"ln{i}", (0.44 - i * 0.1, 0.004, 0.025), (0.0 - i * 0.05, -0.116, 1.68 - i * 0.07), m))
    parts.append(prism_ledge())
    for i in range(6):
        parts.append(C.box(f"k{i}", (0.07, 0.03, 0.02), (-0.18 + i * 0.09, -0.27, 1.105), ("lcars_peach", "lcars_lilac", "lcars_orange")[i % 3], bevel=0.003, segments=1))
    # a grille of slats at its foot, as the locker's
    for i in range(4):
        parts.append(C.box(f"g{i}", (0.6, 0.012, 0.018), (0, -0.112, 0.32 + i * 0.045), "channel"))
    ob = C.join("alcove_console", parts)
    return C.smooth(ob, 35)


# the console's ledge: a wedge out of the face at 1.0-1.1, its top sloping
# up toward the wall
def prism_ledge():
    return C.prism("ledge", [(-0.11, 1.0), (-0.32, 1.06), (-0.32, 1.09), (-0.11, 1.13)], -0.4, 0.4, "console", bevel=0.006, segments=1)


# The replicator: the frame round a face with a recess in it at a hand's
# height, 0.6 x 0.5 and 8 cm deep, its back a black plate the stand-in's
# glow plate lies over (corridorDress: 0.5 x 0.38 at 1.32, 0.03 out of the
# wall's face), and 2.5 cm in front of that a louvre of brushed slats, so
# the light is seen in strips between them, from inside the unit: the
# shared glow is pure white (a material that is not would be a draw call
# more in every corridor cell, 0.236.1), and the slats are what soften it.
# A black floor under it, an LCARS label over it and the family's vent at
# the foot.
def alcove_replicator():
    parts = frame("rp")
    z0, z1, x = 1.05, 1.55, 0.3
    face = [((0.9, 0.13, z0 - 0.14), (0, -0.045, (0.14 + z0) / 2)),
            ((0.9, 0.13, 2.1 - z1), (0, -0.045, (z1 + 2.1) / 2))]
    for sx in (-1, 1):
        face.append(((0.45 - x, 0.13, z1 - z0), (sx * (0.45 + x) / 2, -0.045, (z0 + z1) / 2)))
    for i, (size, at) in enumerate(face):
        parts.append(C.box(f"face{i}", size, at, "comm_black", bevel=0.006, segments=1))
    # the recess's back, behind the glow plate (0.03-0.034 out)
    parts.append(C.box("back", (2 * x, 0.01, z1 - z0), (0, -0.025, (z0 + z1) / 2), "channel"))
    # its floor, and the louvre: eight slats 3 cm tall at 5.5 cm, the light
    # in the 2.5 cm between them
    parts.append(C.box("floor", (2 * x, 0.08, 0.01), (0, -0.07, z0 + 0.005), "channel"))
    for i in range(8):
        parts.append(C.box(f"sl{i}", (2 * x - 0.01, 0.012, 0.03), (0, -0.058, 1.1 + i * 0.055), "trim"))
    # the label over it, an LCARS bar and a lilac cap, as the locker's
    parts.append(C.box("label", (0.44, 0.006, 0.06), (0.08, -0.112, 1.7), "lcars_orange", bevel=0.002, segments=1))
    parts.append(C.box("labelc", (0.1, 0.006, 0.06), (-0.24, -0.112, 1.7), "lcars_lilac", bevel=0.002, segments=1))
    for i in range(4):
        parts.append(C.box(f"g{i}", (0.6, 0.012, 0.018), (0, -0.112, 0.32 + i * 0.045), "channel"))
    ob = C.join("alcove_replicator", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- door frame
# Round the code-built door (door() in deck.html: an opening 2.0 x 2.6, its
# posts 0.15 wide and 0.11 out of the wall's middle with an amber strip on
# each face, the lintel 2.3 x 0.5 over it 0.1 out, the plaque on that). The
# origin is the door's middle on the floor in the wall's middle plane: the
# wall's face is 0.06 out, and the frame's 0.15, so 9 cm proud (not part 6's
# 15: the jamb's channel floor must be the post's face, where the strip is).
# 2.3 wide, not 2.4: the comm panels stand from 1.16 out of the door's middle.
# The jambs have a channel 5 cm wide down them, the strip at its floor; a
# black reveal lines the opening; the head is two rails and two blocks round
# a recess 5 cm deep in which the lintel and its plaque show.
def door_frame():
    F, IN, OUT, CH, cx, cw = 0.15, 1.03, 1.15, 0.025, 1.075, 0.025
    parts = []
    for sx in (-1, 1):
        prof = [(IN, -0.02), (IN, -F), (cx - cw, -F), (cx - cw, -0.11), (cx + cw, -0.11), (cx + cw, -F),
                (OUT - CH, -F), (OUT, -F + CH), (OUT, -0.02)]
        if sx < 0:
            prof = [(-x, y) for x, y in reversed(prof)]
        parts.append(zprism(f"jamb{sx}", prof, 0.14, 2.6, "trim"))
        parts.append(C.box(f"chan{sx}", (2 * cw - 0.002, 0.003, 2.46), (sx * cx, -0.1115, 1.37), "channel"))
        # the foot, the skirting's black and a hand prouder, as the ribs'
        parts.append(C.box(f"foot{sx}", (OUT - 1.0, F + 0.01, 0.14), (sx * (OUT + 1.0) / 2, -(F - 0.01) / 2 - 0.01, 0.07), "console", bevel=0.01, segments=1))
        # the reveal: a black lining of the opening's side, set 2 cm back
        parts.append(C.box(f"rev{sx}", (IN - 0.995, F - 0.065, 2.6), (sx * (IN + 0.995) / 2, -(0.045 + F - 0.02) / 2, 1.3), "channel"))
    parts.append(C.box("revtop", (2 * IN, F - 0.065, 0.03), (0, -(0.045 + F - 0.02) / 2, 2.585), "channel"))
    # the head: rails under and over the plaque's recess, blocks either side
    # (the plaque: 1.19 x 0.28 round 2.85)
    D = F - 0.02
    parts.append(C.box("rail0", (2 * OUT, D, 0.09), (0, -0.02 - D / 2, 2.645), "trim", bevel=0.015, segments=1))
    parts.append(C.box("rail1", (2 * OUT, D, 0.1), (0, -0.02 - D / 2, 3.05), "trim", bevel=0.015, segments=1))
    for sx in (-1, 1):
        parts.append(C.box(f"blk{sx}", (OUT - 0.62, D, 0.31), (sx * (OUT + 0.62) / 2, -0.02 - D / 2, 2.845), "trim", bevel=0.012, segments=1))
    ob = C.join("door_frame", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- carpet border
# 1.3 x 0.3 of floor, a hair thick so its edges catch no light: the page lays
# it flat along each run of trim, its long side along the corridor. Origin
# its middle on the floor, the long side along X.
def carpet_border():
    ob = C.box("carpet_border", (1.3, 0.3, 0.004), (0, 0, 0.002), "carpet_border")
    return ob


# ---------------------------------------------------------------- comm panel
# The stand-in (corridorDress): a plate 0.18 x 0.3, 0.04 deep, the amber
# strip 0.1 x 0.05 at +0.1 on its face, the red or blue indicator 0.06 x
# 0.03 at -0.03. The buttons go under the indicator.
def comm_panel():
    parts = [C.box("plate", (0.18, 0.04, 0.3), (0, 0, 0), "comm_black", bevel=0.008, segments=1),
             # a raised brushed rim round the strip's window, a hand-width
             # above the buttons: the plate's one lighter line
             C.box("rim", (0.13, 0.006, 0.075), (0, -0.021, 0.1), "trim", bevel=0.002, segments=1)]
    for x, m in ((-0.04, "lcars_peach"), (0.04, "lcars_lilac")):
        parts.append(C.box(f"btn{x}", (0.05, 0.012, 0.03), (x, -0.024, -0.09), m, bevel=0.004, segments=1))
    ob = C.join("comm_panel", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- door plaque
# Round the name plate (door() in deck.html: 1.1 x 0.2, 0.005 out from the
# lintel's face, its middle 0.25 below the lintel's top): four bars, the
# opening a hair larger than the name.
def door_plaque():
    W, Hh, b, d = 1.12, 0.21, 0.035, 0.02
    parts = []
    for z in (-1, 1):
        parts.append(C.box(f"bar{z}", (W + 2 * b, d, b), (0, -d / 2, z * (Hh + b) / 2), "trim", bevel=0.006, segments=1))
    for x in (-1, 1):
        parts.append(C.box(f"post{x}", (b, d, Hh), (x * (W + b) / 2, -d / 2, 0), "trim", bevel=0.006, segments=1))
    ob = C.join("door_plaque", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- PADD rack
# 0.5 x 0.1 x 0.4: a back plate, a tray with a lip along its foot; two PADDs
# stand in the tray leaning back on the plate. 200 triangles is tight: only
# the plate and the PADDs' bodies are bevelled (the edges seen), and only
# the first PADD has its LCARS key under the screen.
def padd(name, x, lean, key):
    parts = [C.box(name + "b", (0.13, 0.014, 0.2), (0, 0, 0.1), "padd_body", bevel=0.004, segments=1),
             C.box(name + "s", (0.1, 0.004, 0.13), (0, -0.007, 0.115), "padd_screen")]
    if key:
        parts.append(C.box(name + "k", (0.1, 0.004, 0.022), (0, -0.007, 0.03), "lcars_peach"))
    ob = C.join(name, parts)
    # its origin at its foot, the pivot of the lean
    C.activate(ob)
    bpy.ops.object.transform_apply(location=True)
    ob.rotation_euler.x = lean
    ob.location = (x, -0.05, -0.174)
    return ob


def padd_rack():
    parts = [C.box("back", (0.5, 0.016, 0.4), (0, -0.008, 0), "comm_black", bevel=0.006, segments=1),
             C.box("tray", (0.46, 0.08, 0.016), (0, -0.056, -0.182), "trim"),
             C.box("lip", (0.46, 0.012, 0.04), (0, -0.094, -0.166), "trim"),
             # leaning back (+Y) until the top meets the plate
             padd("padd1", -0.1, -0.17, True), padd("padd2", 0.09, -0.15, False)]
    for p in parts[-2:]:
        C.activate(p)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    ob = C.join("padd_rack", parts)
    return C.smooth(ob, 35)


C.clean_scene()
props = C.finish_props([comm_panel(), door_plaque(), padd_rack(), rib(), alcove_locker(), alcove_console(),
                         alcove_replicator(), door_frame(), carpet_border()])
for p in props:
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
# 1024: three pieces of dressing a few decimetres across were 512
# (deck-pipeline.md, the cleaner's sizes); the rib is 3 m tall and the wall
# units 2.2, and at 512 they would get a texel in 1.5 cm
C.finish_room("corridor", props, size=1024)
