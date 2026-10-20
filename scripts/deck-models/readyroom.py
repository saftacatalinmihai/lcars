"""The ready room's props (docs/design/deck-style.md part 2, "Ready room"):
lcars-ui/deck/readyroom.glb, one atlas at 1024: the desk, the PADD shelves
dressed (two arrangements of the same rack), the fish tank, and the two Poly
Haven pieces that were the room's pack (the carved elephant and the brass
vase), imported, decimated and baked from their originals as pack.py does.

    blender -b --factory-startup -P scripts/deck-models/readyroom.py -- OUT_DIR PACK_DIR

PACK_DIR is the folder build.sh fetches the two Poly Haven assets into; its
licences are copied to OUT/readyroom.LICENSE.txt.

Each prop is built to its stand-in's measures in deck.html's
buildReadyRoom, because the stand-in's display, lights and blocks stay where
the code put them and the model sits round them:
- `desk`, over the desk (a 0.9 x 2.0 top at 0.735-0.785, the sitter on its
  +x side, page coordinates). The page turns it a quarter (rot -PI/2), so
  here Blender's X is the page's z and Blender's Y the page's x: the curved
  front (-Y) faces the window, the knee space (+Y) the chair. The
  stand-in's display (0.52 x 0.32, its middle at Y -0.25, X 0.05, Z 1.0,
  tilted 0.18 back) stays over the model's terminal.
- `padd_shelf_a`, `padd_shelf_b`, over `padShelf(x, z, rot)` (1.4 wide,
  2.05 high, 0.36 deep, six boards at 0.1 + 0.384 k, 0.03 thick, their tops
  where the page stands a pinned PADD): the rack as the stand-in's, and
  dressing on a third of a few boards, so the rest stays free for entries.
  The amber strip under each board stays the stand-in's.
- `fish_tank`, over the tank by the corridor wall (a cabinet to 0.95, the
  glass 0.85-1.75 and the water 0.95-1.65 in the page's M.glass and
  M.water, both kept over the model); turned as the desk is. The fish that
  swim are the page's; the model's are cards among the plants.
- `tea_table`, over the lounge corner's low table, and `window_seat`, over
  the seat and its cushion under the port window (below).
- `bookcase_a`, `bookcase_b`, over the two `bookcase()`s in the corner by
  the window (below), and `rr_sofa`, `rr_armchair`, common.py's sofa at 2.3
  and 0.95 over the lounge corner's `sofa()`s: in this atlas, not taken
  from lounge.glb, which would be one more material in the room.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402

# the room's own colours beside the palette's: the fish and its tank (a
# script may add to the palette for its room; the shared hexes stay in
# common.py)
C.PALETTE.update({
    "fish": (0xe87a2a, 0.4, 0.0, None),
    "gravel": (0x5a5046, 0.9, 0.0, "pebble"),
    "weed": (0x2f6a2a, 0.6, 0.0, None),
})


def _mesh(name, bm, material, bevel=0.0, segments=2):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = C.link(bpy.data.objects.new(name, me))
    ob.data.materials.append(C.mat(material))
    if bevel:
        C.modifier(ob, "BEVEL", width=bevel, segments=segments, limit_method="ANGLE")
    return ob


def slab(name, outline, z0, z1, material, bevel=0.0, segments=2):
    """An outline [(x, y), ...] (one way round, any) extruded up from z0 to
    z1: a desk top with a curved front, a plinth."""
    bm = bmesh.new()
    a = [bm.verts.new((x, y, z0)) for x, y in outline]
    b = [bm.verts.new((x, y, z1)) for x, y in outline]
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(a)
    bm.faces.new(b[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    # the caps are ngons, and the exporter's tangents take only triangles
    # and quads (bridge.py's note)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    return _mesh(name, bm, material, bevel, segments)


def front_arc(w, y_mid, y_end, k=14):
    """The desk's curved front, x from -w/2 to w/2: a shallow arc through
    (0, y_mid) and (+-w/2, y_end)."""
    s = w / 2
    sag = y_end - y_mid
    R = (s * s + sag * sag) / (2 * sag)
    cy = y_mid + R
    a = math.asin(s / R)
    return [(R * math.sin(t), cy - R * math.cos(t)) for t in (-a + 2 * a * i / k for i in range(k + 1))]


def offset(pts, d):
    """The arc moved d toward +y (inward)."""
    return [(x, y + d) for x, y in pts]


def band(name, pts, d, z0, z1, material, bevel=0.0):
    """A panel of thickness d following the poly line `pts` (an arc), its
    outside on the line."""
    return slab(name, pts + offset(pts, d)[::-1], z0, z1, material, bevel)


# ---------------------------------------------------------------- the desk
def desk():
    W, BACK, FRONT_END, FRONT_MID = 2.0, 0.45, -0.38, -0.45
    arc = front_arc(W, FRONT_MID, FRONT_END)
    parts = []
    # the top: the arc in front, straight behind, lacquered dark wood with a
    # black reveal under it (the "black base" shows as a shadow line)
    top = arc + [(W / 2, BACK), (-W / 2, BACK)]
    parts.append(slab("top", top, 0.745, 0.785, "desk_wood", bevel=0.012, segments=3))
    inner = offset(front_arc(W - 0.08, FRONT_MID, FRONT_END), 0.04)
    parts.append(slab("reveal", inner + [(W / 2 - 0.04, BACK - 0.04), (-W / 2 + 0.04, BACK - 0.04)], 0.715, 0.745, "black"))
    # the curved front in wood, standing on a black plinth set back from it
    front = offset(front_arc(W - 0.1, FRONT_MID, FRONT_END), 0.05)
    parts.append(band("front", front, 0.04, 0.09, 0.715, "desk_wood", bevel=0.006))
    # a brushed inlay along it, a hand's width under the top
    parts.append(band("inlay", offset(front, -0.004), 0.01, 0.6, 0.618, "trim"))
    plinth = offset(front_arc(W - 0.22, FRONT_MID, FRONT_END), 0.11)
    parts.append(slab("plinth", plinth + [(W / 2 - 0.11, BACK - 0.1), (-W / 2 + 0.11, BACK - 0.1)], 0.0, 0.09, "black", bevel=0.01))
    # the ends: wood panels from the front to the back edge
    for sx in (-1, 1):
        x = sx * (W / 2 - 0.07)
        y0 = front[0][1] + 0.02
        parts.append(C.box(f"end{sx}", (0.04, BACK - 0.04 - y0, 0.625), (x, (y0 + BACK - 0.04) / 2, 0.09 + 0.3125), "desk_wood", bevel=0.006, segments=2))
    # a drawer pedestal on the sitter's left (+X here: the page's -z end),
    # three drawers with black seams and brushed pulls
    px, pw, pd = 0.62, 0.42, 0.5
    parts.append(C.box("ped", (pw, pd, 0.625), (px, BACK - 0.04 - pd / 2, 0.09 + 0.3125), "desk_wood", bevel=0.008, segments=2))
    for i, z in enumerate((0.27, 0.48)):
        parts.append(C.box(f"seam{i}", (pw - 0.04, 0.006, 0.008), (px, BACK - 0.04 + 0.002, z), "black"))
    for i, z in enumerate((0.19, 0.38, 0.6)):
        parts.append(C.box(f"pull{i}", (0.16, 0.018, 0.016), (px, BACK - 0.03, z), "trim", bevel=0.005, segments=1))
    # the desktop terminal: a housing behind the stand-in's display, its
    # bezel standing proud of it, on a neck and a foot, all at the
    # display's tilt (0.18 about X: the screen faces +Y and a little up)
    from mathutils import Matrix
    th = 0.18
    term = [C.box("housing", (0.58, 0.032, 0.38), (0, -0.03, 0), "console", bevel=0.01, segments=2)]
    # (the rims stand 8 mm proud of the display's plane, at 0 here)
    for nm, size, at in (("rimT", (0.58, 0.012, 0.03), (0, 0.002, 0.175)), ("rimB", (0.58, 0.012, 0.03), (0, 0.002, -0.175)),
                         ("rimL", (0.03, 0.012, 0.38), (-0.275, 0.002, 0)), ("rimR", (0.03, 0.012, 0.38), (0.275, 0.002, 0))):
        term.append(C.box(nm, size, at, "trim", bevel=0.004, segments=1))
    # a strip of black buttons under the screen
    term.append(C.box("keys", (0.36, 0.006, 0.012), (0, 0.009, -0.178), "black"))
    for o in term:
        o.location = (Matrix.Translation((0.05, -0.25, 1.0)) @ Matrix.Rotation(th, 4, "X") @ o.location.to_4d()).to_3d()
        o.rotation_euler.x = th
    parts += term
    parts.append(C.box("neck", (0.08, 0.05, 0.2), (0.05, -0.285, 0.87), "trim", bevel=0.01, segments=2))
    parts.append(C.lathe("foot", [(0.001, 0.785), (0.14, 0.785), (0.13, 0.8), (0.06, 0.81), (0.001, 0.81)], "console", steps=20,
                         at=(0.05, -0.28, 0)))
    ob = C.join("desk", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- the shelves
# common.py's PADD shelf (the generated rooms' are baked from it too), in
# its two arrangements of books, PADDs and a bronze


# ---------------------------------------------------------------- the tank
def fish(tag, x, y, z, s, turn):
    """A fish card: a flat body and tail, a few millimetres thick."""
    bm = bmesh.new()
    pts = [(0.05, 0), (0.035, 0.016), (0.0, 0.022), (-0.03, 0.014), (-0.045, 0.0), (-0.07, 0.022), (-0.07, -0.022),
           (-0.045, 0.0), (-0.03, -0.014), (0.0, -0.022), (0.035, -0.016)]
    # two loops (the tail meets the body at a point): split at the waist
    body = [pts[i] for i in (0, 1, 2, 3, 4, 8, 9, 10)]
    tail = [pts[i] for i in (4, 5, 6)]
    for poly in (body, tail):
        a = [bm.verts.new((px * s, -0.002, py * s)) for px, py in poly]
        b = [bm.verts.new((px * s, 0.002, py * s)) for px, py in poly]
        n = len(poly)
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
        bm.faces.new(a)
        bm.faces.new(b[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    ob = _mesh(f"fish{tag}", bm, "fish")
    ob.location = (x, y, z)
    ob.rotation_euler.z = turn
    return ob


def fish_tank():
    """The tank: a dark wood cabinet on a black kick, a brushed frame where
    the page's glass meets it, gravel and weed inside, a few fish cards, and
    a rounded hood on top with a light strip under its lip. Long along X
    (1.25), 0.45 deep, the room toward -Y."""
    L, D = 1.25, 0.45
    parts = [C.box("kick", (L - 0.06, D - 0.06, 0.08), (0, 0.01, 0.04), "black", bevel=0.01, segments=1),
             C.box("cab", (L, D, 0.82), (0, 0, 0.08 + 0.41), "desk_wood", bevel=0.012, segments=2),
             C.box("cabtop", (L + 0.03, D + 0.03, 0.04), (0, 0, 0.92), "desk_wood", bevel=0.01, segments=2)]
    # two doors' seam and pulls on the room's face
    parts.append(C.box("dseam", (0.006, 0.006, 0.7), (0, -D / 2 - 0.001, 0.48), "black"))
    for sx in (-1, 1):
        parts.append(C.box(f"dpull{sx}", (0.016, 0.018, 0.14), (sx * 0.05, -D / 2 - 0.006, 0.62), "trim", bevel=0.005, segments=1))
    # the frame round the glass: a brushed sill under it and corner posts
    parts.append(C.box("sill", (L + 0.02, D + 0.02, 0.04), (0, 0, 0.96), "trim", bevel=0.008, segments=1))
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(C.box(f"post{sx}{sy}", (0.025, 0.025, 0.8), (sx * (L / 2 - 0.004), sy * (D / 2 - 0.004), 1.35), "trim"))
    # gravel: a low mound, lumpy along its top
    bm = bmesh.new()
    nx, ny = 16, 5
    vs = []
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            x = -L / 2 + 0.03 + (L - 0.06) * i / nx
            y = -D / 2 + 0.04 + (D - 0.08) * j / ny
            h = 0.03 + 0.02 * math.sin(i * 1.7 + j * 2.3) * math.sin(i * 0.6) + 0.02 * (j / ny)
            row.append(bm.verts.new((x, y, 0.98 + max(0.01, h))))
        vs.append(row)
    for j in range(ny):
        for i in range(nx):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    g = _mesh("gravel", bm, "gravel")
    parts.append(g)
    # weed: a few tall blades from the gravel, and a stone
    for i, (x, y, h, a) in enumerate(((-0.45, 0.1, 0.42, 0.1), (-0.4, 0.12, 0.33, -0.2), (-0.36, 0.08, 0.38, 0.25),
                                      (0.38, 0.12, 0.36, -0.1), (0.43, 0.1, 0.45, 0.2), (0.47, 0.13, 0.3, -0.3))):
        b = C.box(f"weed{i}", (0.03, 0.006, h), (x, y, 1.0 + h / 2), "weed")
        b.rotation_euler.y = a * 0.4
        b.rotation_euler.z = a
        parts.append(b)
    parts.append(C.lathe("stone", [(0.001, 0.98), (0.09, 0.98), (0.1, 1.02), (0.07, 1.07), (0.001, 1.08)], "trim", steps=8, at=(0.1, 0.08, 0)))
    for i, (x, y, z, s, t) in enumerate(((-0.15, 0.0, 1.32, 1.0, 0.0), (0.25, 0.05, 1.18, 0.8, math.pi), (-0.3, -0.05, 1.48, 0.7, 0.2),
                                        (0.05, 0.1, 1.55, 0.9, math.pi + 0.15))):
        parts.append(fish(i, x, y, z, s, t))
    # the hood: a rounded top over the glass, its ends capped, a light strip
    # under its front lip
    bm = bmesh.new()
    prof = [(-D / 2 - 0.02, 0.0), (-D / 2 - 0.02, 0.05), (-D / 2 + 0.03, 0.12), (-0.08, 0.16), (0.08, 0.16), (D / 2 - 0.03, 0.12),
            (D / 2 + 0.02, 0.05), (D / 2 + 0.02, 0.0)]
    a = [bm.verts.new((-L / 2 - 0.02, y, 1.75 + z)) for y, z in prof]
    b = [bm.verts.new((L / 2 + 0.02, y, 1.75 + z)) for y, z in prof]
    n = len(prof)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(a)
    bm.faces.new(b[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    parts.append(_mesh("hood", bm, "console", bevel=0.012, segments=2))
    parts.append(C.box("hoodtrim", (L + 0.05, 0.02, 0.025), (0, -D / 2 - 0.025, 1.76), "trim", bevel=0.006, segments=1))
    ob = C.join("fish_tank", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- tea table
# The stand-in (the lounge corner's low table): a top 0.5 round from 0.395
# to 0.445, where the page stands the teapot, a mug and the elephant, on a
# post of 0.08-0.14. One turned piece in the desk's dark wood: a rolled
# edge, a baluster pedestal, a domed foot.
def tea_table():
    prof = [(0.001, 0.0), (0.26, 0.0), (0.27, 0.012), (0.26, 0.03), (0.2, 0.045), (0.09, 0.06), (0.06, 0.1), (0.075, 0.16),
            (0.065, 0.24), (0.05, 0.3), (0.06, 0.36), (0.12, 0.385), (0.44, 0.395), (0.492, 0.4), (0.5, 0.415), (0.497, 0.435),
            (0.482, 0.445), (0.001, 0.445)]
    ob = C.lathe("tea_table", prof, "desk_wood", steps=24)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- window seat
# The stand-in (under the port window): a box 0.62 deep, 3.9 long, to 0.36,
# and a cushion on it to 0.46, where the cat sleeps. Here its length is X,
# its front (the room) -Y; the page turns it a quarter (rot PI/2). A wooden
# chest on a black kick, three raised panels along its front, and three
# cushions with rolled edges; the throw pillows against the window stay the
# page's (their own colours).
C.PALETTE.update({"seat_cushion": (0x5a6a7a, 0.85, 0.0, "weave")})


def window_seat():
    L = 3.9
    parts = [C.box("kick", (L - 0.08, 0.5, 0.06), (0, 0.03, 0.03), "black"),
             C.box("chest", (L, 0.58, 0.29), (0, 0.02, 0.205), "desk_wood", bevel=0.008, segments=1),
             C.box("lid", (L + 0.02, 0.63, 0.03), (0, 0.0, 0.345), "desk_wood", bevel=0.01, segments=2)]
    for i in (-1, 0, 1):
        parts.append(C.box(f"panel{i}", (1.18, 0.012, 0.18), (i * 1.27, -0.276, 0.2), "desk_wood", bevel=0.005, segments=1))
        parts.append(C.box(f"cushion{i}", (1.29, 0.58, 0.1), (i * 1.3, 0.01, 0.41), "seat_cushion", bevel=0.035, segments=3))
    ob = C.join("window_seat", parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- bookcases
# The stand-in (`bookcase(x, z, rot, 1.4, 2.45, 6, seed)` in the corner by
# the window, two side by side): 1.4 wide, 2.45 high, 0.32 deep, seven
# boards 0.03 thick at 0.02 + 0.4 k. A case of the desk's dark wood with
# the PADD racks' wainscot back, a crown and a black kick, its boards full
# of books in runs (a few leaning at a run's end, one stack lying), and a
# PADD or two and a small piece among them, as the PADD shelves are
# dressed. A book is a plain box without its back and bottom (8 triangles:
# a bevel would treble them at no gain at this size), and each board holds
# a run or two, not a full row, to keep a case furniture's 1.5 k and the
# room's bytes near their budget. `seed` picks each case's own runs.
C.PALETTE.update({
    "book_blue": (0x2a3a5a, 0.8, 0.0, None),
    "book_tan": (0x8a7050, 0.75, 0.0, None),
    "book_red": (0x6a2a22, 0.75, 0.0, None),
})
BW, BH, BD = 1.4, 2.45, 0.32
CASE_BOARDS = [0.02 + i * (BH - 0.05) / 6 for i in range(7)]
BOOK_MATS = ["book_green", "book_blue", "book_tan", "book_red", "bridge_leather", "lounge_leather", "bed_pad"]


def open_box(name, size, at, material):
    """A book: C.box without the faces against the case's back (+Y) and the
    board (-Z), which no one sees."""
    ob = C.box(name, size, at, material)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.normal.y > 0.9 or f.normal.z < -0.9], context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def bookcase(name, seed):
    import random
    r = random.Random(seed)
    tag = name[-1]
    parts = [C.box(f"cback{tag}", (BW - 0.04, 0.02, BH - 0.04), (0, BD / 2 - 0.015, BH / 2), "wainscot"),
             C.box(f"ckick{tag}", (BW - 0.08, BD - 0.05, 0.02), (0, 0.0, 0.01), "black"),
             C.box(f"ccrown{tag}", (BW + 0.03, BD + 0.02, 0.04), (0, -0.01, BH - 0.01), "desk_wood", bevel=0.008, segments=1)]
    for sx in (-1, 1):
        parts.append(C.box(f"cside{tag}{sx}", (0.035, BD, BH - 0.02), (sx * (BW / 2 - 0.0175), 0, BH / 2 - 0.01), "desk_wood",
                           bevel=0.006, segments=1))
    for i, y in enumerate(CASE_BOARDS[:-1]):
        parts.append(C.box(f"cboard{tag}{i}", (BW - 0.07, BD - 0.01, 0.03), (0, 0.0, y), "desk_wood", bevel=0.005, segments=1))
    inner = BW / 2 - 0.035
    for sh in range(6):
        z0 = CASE_BOARDS[sh] + 0.015
        room = CASE_BOARDS[sh + 1] - CASE_BOARDS[sh] - 0.06
        # what the board holds besides books: a stack lying, PADDs, the piece
        extra = {1: "padds", 3: "piece", 4: "stack"}.get((sh + seed) % 6)
        x = -inner + 0.01
        end = inner - 0.01
        if extra:
            # the extra takes one end of the board, the seed's side
            if (sh + seed) % 2:
                ex, x = x + 0.17, x + 0.36
            else:
                ex, end = end - 0.17, end - 0.36
        run, runs, stop = 0, 0, 6 + r.randrange(5)
        x += r.random() * 0.15
        while x < end - 0.05 and runs < 2:
            t = 0.03 + r.random() * 0.03
            h = min(room, 0.2 + r.random() * 0.1)
            d = 0.17 + r.random() * 0.06
            m = BOOK_MATS[r.randrange(len(BOOK_MATS))]
            run += 1
            if run > stop:
                # a run ends: one leaning on the last, then a gap
                # (its top toward -X, on the run's last book; its foot out
                # from it by the lean)
                lean = -0.3
                b = open_box(f"bk{tag}{sh}_{run}", (t, d, h), (x + t / 2 + h / 2 * math.sin(-lean), -BD / 2 + 0.02 + d / 2, z0 + h / 2 * math.cos(lean)), m)
                b.rotation_euler.y = lean
                parts.append(b)
                x += 0.25 + r.random() * 0.3
                run, runs, stop = 0, runs + 1, 5 + r.randrange(5)
                continue
            parts.append(open_box(f"bk{tag}{sh}_{run}", (t, d, h), (x + t / 2, -BD / 2 + 0.02 + d / 2, z0 + h / 2), m))
            x += t + 0.002
        if extra == "stack":
            zz = z0
            for k in range(3):
                bt = 0.035 + 0.01 * k
                b = C.box(f"st{tag}{sh}{k}", (0.24 - 0.02 * k, 0.19 - 0.01 * k, bt), (ex, -0.01, zz + bt / 2), BOOK_MATS[(seed + k) % 7])
                b.rotation_euler.z = 0.06 * (k - 1)
                parts.append(b)
                zz += bt
        elif extra == "padds":
            # two leaning on the back, as on the PADD shelves
            from mathutils import Euler, Vector
            for k, (dx, lean) in enumerate(((-0.05, 0.3), (0.06, 0.38))):
                w, h, t = 0.15, 0.21, 0.012
                foot = BD / 2 - 0.03 - h * math.sin(lean) - t
                at = (ex + dx, foot + h / 2 * math.sin(lean), z0 + h / 2 * math.cos(lean))
                body = C.box(f"cp{tag}{sh}{k}", (w, t, h), at, "putty", bevel=0.004, segments=1)
                body.rotation_euler = Euler((-lean, 0, 0))
                rot = Euler((-lean, 0, 0))
                face = C.box(f"cpf{tag}{sh}{k}", (w - 0.03, 0.002, h - 0.05),
                             Vector(at) + rot.to_matrix() @ Vector((0, -t / 2 - 0.0008, 0.008)), "black")
                face.rotation_euler = rot
                parts += [body, face]
        elif extra == "piece":
            # a brass globe on a turned foot: an old Earth, something a
            # captain keeps
            parts.append(C.lathe(f"gfoot{tag}", [(0.001, 0), (0.05, 0), (0.045, 0.012), (0.012, 0.03), (0.01, 0.07), (0.001, 0.07)],
                                 "bronze", steps=8, at=(ex, 0.0, z0)))
            g = C.lathe(f"globe{tag}", [(0.001, -0.075)] + [(0.075 * math.sin(math.pi * k / 6), -0.075 * math.cos(math.pi * k / 6))
                                                            for k in range(1, 6)] + [(0.001, 0.075)], "bronze", steps=12,
                        at=(ex, 0.0, z0 + 0.145))
            parts.append(g)
    ob = C.join(name, parts)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- the room
out, args = C.out_dir()
if not args:
    sys.exit("usage: blender -b -P readyroom.py -- OUT_DIR PACK_DIR")
lic = C.pack_licences(args[0])
C.clean_scene()
props = [desk(), C.padd_shelf("padd_shelf_a", C.shelf_books("a")), C.padd_shelf("padd_shelf_b", C.shelf_books("b")), fish_tank(), tea_table(), window_seat(),
         bookcase("bookcase_a", 5), bookcase("bookcase_b", 6), C.sofa("rr_sofa", 2.3), C.sofa("rr_armchair", 0.95, aw=0.15)]
for p in props:
    # the origin is the stand-in's (on the floor at its middle, as built),
    # so no floor_origin; transforms applied, ngons cut for the tangents
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(p.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(p.data)
    bm.free()
# the pack's two pieces: dressing, 200 triangles each, the carving and the
# vase's hammering carried in the normal map
lows, sources = C.import_pack(args[0], "readyroom", 200)
C.finish_room("readyroom", props + lows, size=1024, sources=sources)
C.write_licences(lic, os.path.join(out, "readyroom.LICENSE.txt"))
