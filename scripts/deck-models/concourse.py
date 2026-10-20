"""The concourse's props (docs/design/deck-style.md part 2, "Concourse"):
lcars-ui/deck/concourse.glb, one 1024² atlas. Eight pieces of furniture,
each at most 1.5k triangles, and the plinth, the hall's hero (at most 6 k),
over their code-built stand-ins in deck.html (buildConcourse, ringBench(),
the columns, the directories, the planters, the balconies' rails, slabs and
doors, the plinth and its lit top):

- `ring_bench`, six round the plinth: a backless bench 2.4 m along an arc
  of the ring it stands on (6.8 m from the plinth's axis), dark wood slats
  on three bronze ends;
- `column`, eight under the balconies' edges: brushed bronze, a moulded
  base, a collar where the first balcony meets it, and a capital under the
  second; the light at its head is the stand-in's glow band (kept over the
  model, in the shared glow material: the atlas has no emission), in the
  recess the model leaves for it;
- `directory`, two by the corridor's mouth: a slim totem with a rounded
  top, a bronze bezel round the directory's lit face (the stand-in's own
  canvas, kept over the model);
- `planter`, four in the corners: a dark stone bowl banded in bronze, over
  the wooden drums the trees stand in;
- `balcony_rail`, a 1.6 m bay of the balconies' rail (the page stretches
  the last few millimetres of a run): a lacquered handrail on a bronze
  channel over the glass, a bronze shoe under it; the glass stays the
  page's (M.glass: the atlas has no transparency), as the light under the
  slab's edge does;
- `rail_post`, the bronze post between two bays, placed apart from them so
  a corner has one post, not the two runs' each;
- `balcony_door`, the rooms' doors up on the balconies: a bronze frame round
  a two-leaf door, its head two bars with the stand-in's amber light
  between them (kept over the model, as the leaf's red seam is);
- `slab_edge`, a 1.6 m bay of the balconies' slab edge under each rail
  bay: a lip, a fascia with a reveal, a drip lip and the soffit's cove the
  amber light hangs in (the slab's body and underside stay the page's);
- `plinth`, the hologram's plinth: dark honed stone, a kick, a base
  course, a groove for the amber line, a bevelled top face round the lit
  disc;
- `holo_top`, the hologram's top: a bronze bezel round the lit disc (kept
  the page's, the atlas has no emission) and the emitter boss at its middle.

    blender -b --factory-startup -P scripts/deck-models/concourse.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported), its origin its stand-in's: the bench's on the floor at
the middle of its arc (ringBench()'s group: its sitters face its local +z,
the plinth, here -Y, and its seat's top is at 0.46, where the page seats
them), the column's and the directory's on the floor under their axis, the
rail's and the post's on the balcony's floor at the glass's middle, the
door's on the floor at its leaf's middle (the leaf 0.1 deep, 2 cm of it
in the wall behind).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402

# the bench's slats are the palette's desk_wood (#4a3022, the order's dark
# wood), its ends and the columns the palette's bronze (#8a6a44, brushed):
# both already in common.PALETTE, as the totem's console black is


def drop_floor_faces(ob):
    """Faces on the floor looking down: never seen, atlas space wasted
    (arboretum.py's, copied: one function does not earn a shared helper)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    gone = [f for f in bm.faces if f.normal.z < -0.99 and max(v.co.z for v in f.verts) < 0.002]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def mesh_from(name, bm, material):
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = C.link(bpy.data.objects.new(name, me))
    ob.data.materials.append(C.mat(material))
    return ob


# ---------------------------------------------------------------- bench
# The ring: the bench's arc is centred on the plinth's axis, RC in front of
# the bench's origin (toward -Y); a point `r` from the axis at angle `t`
# from the bench's middle is pt(r, t). 2.4 m of arc is 0.353 rad of it.
RC = 6.8
HALF = 1.2 / RC


def pt(r, t, z):
    return (r * math.sin(t), -RC + r * math.cos(t), z)


def arc_box(name, r0, r1, z0, z1, t0, t1, material, n=8, bevel=0.0):
    """A box bent along the ring: from radius r0 to r1, height z0 to z1,
    angle t0 to t1 in n straight sections (at 2.4 m and 8, each bows 1.6 mm
    from the arc). Its bevel, by angle, rounds the real edges and leaves
    the 2.5-degree folds between sections alone."""
    bm = bmesh.new()
    secs = []
    for i in range(n + 1):
        t = t0 + (t1 - t0) * i / n
        secs.append([bm.verts.new(pt(r, t, z)) for r, z in ((r0, z0), (r1, z0), (r1, z1), (r0, z1))])
    for a, b in zip(secs, secs[1:]):
        for k in range(4):
            bm.faces.new((a[k], a[(k + 1) % 4], b[(k + 1) % 4], b[k]))
    bm.faces.new(secs[0])
    bm.faces.new(secs[-1][::-1])
    ob = mesh_from(name, bm, material)
    if bevel:
        C.modifier(ob, "BEVEL", width=bevel, segments=1, limit_method="ANGLE")
    return ob


def bench_end(name, t, w=0.05):
    """A cast bronze end, radial at angle t: a panel from the floor to the
    rail the slats lie on, on a wider foot."""
    parts = [C.box(f"{name}_panel", (w, 0.5, 0.39), pt(RC, t, 0.025 + 0.195), "bronze", bevel=0.01, segments=1),
             C.box(f"{name}_foot", (w + 0.03, 0.56, 0.025), pt(RC, t, 0.0125), "bronze", bevel=0.008, segments=1)]
    for p in parts:
        p.rotation_euler.z = -t     # its 0.5 m side along the radius
    return parts


def ring_bench():
    parts = []
    # five slats across the 0.55 m seat, their top at 0.46
    w, gap = 0.096, 0.0175
    for i in range(5):
        r0 = RC - 0.275 + i * (w + gap)
        parts.append(arc_box(f"slat{i}", r0, r0 + w, 0.428, 0.46, -HALF, HALF, "desk_wood", bevel=0.006))
    # the bronze rails under them, inner and outer, end to end
    for i, r0 in enumerate((RC - 0.25, RC + 0.22)):
        parts.append(arc_box(f"rail{i}", r0, r0 + 0.03, 0.37, 0.428, -HALF + 0.03, HALF - 0.03, "bronze"))
    for i, t in enumerate((-HALF + 0.035, 0.0, HALF - 0.035)):
        parts += bench_end(f"end{i}", t)
    ob = C.join("ring_bench", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- column
# The stand-in (buildConcourse): 0.32 to 0.28 round, from the floor to the
# second balcony's top (9.2); the first balcony's slab is 4.26-4.6, the
# second's underside 8.855. The column's axis is the slabs' edge, so half of
# it shows below and beside each. The stand-in's glow band is r 0.29 from
# 8.21 to 8.35: the model's neck there is 0.28, the band 1 cm proud.
def column():
    prof = [(0.34, 0.0), (0.34, 0.1), (0.32, 0.12), (0.32, 0.15), (0.335, 0.175), (0.325, 0.205), (0.29, 0.23),
            (0.27, 0.25), (0.255, 0.3),
            # the collars under and over the first balcony
            (0.245, 4.12), (0.275, 4.15), (0.275, 4.23), (0.245, 4.26),
            (0.243, 4.6), (0.275, 4.63), (0.275, 4.7), (0.243, 4.73),
            # the neck, the light's recess, the capital to the second's underside
            (0.232, 8.0), (0.25, 8.08), (0.29, 8.14), (0.29, 8.19), (0.28, 8.2), (0.28, 8.36), (0.29, 8.37),
            (0.29, 8.42), (0.31, 8.5), (0.35, 8.6), (0.39, 8.68), (0.42, 8.74), (0.42, 8.85), (0.0, 8.85)]
    ob = C.lathe("column", prof, "bronze", steps=20)
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- directory
# The stand-in's lit face is 0.66 x 1.9, its middle 1.35 up, 2 mm before
# the totem's front (0.15 from its axis): the bezel's opening is 0.67 x 1.91,
# its bars 14 mm proud, so the face sits inside them.
def directory():
    bm = bmesh.new()
    outline = [(-0.4, 0.0), (0.4, 0.0)] + [(0.4 * math.cos(math.pi * k / 10), 2.28 + 0.4 * math.sin(math.pi * k / 10))
                                           for k in range(11)]
    front = [bm.verts.new((x, -0.15, z)) for x, z in outline]
    back = [bm.verts.new((x, 0.15, z)) for x, z in outline]
    n = len(outline)
    for k in range(n):
        bm.faces.new((front[k], front[(k + 1) % n], back[(k + 1) % n], back[k]))
    # the arched faces triangulated: the bake's tangents refuse an n-gon
    caps = [bm.faces.new(front), bm.faces.new(back[::-1])]
    bmesh.ops.triangulate(bm, faces=caps, quad_method="BEAUTY", ngon_method="BEAUTY")
    body = mesh_from("body", bm, "console")
    C.modifier(body, "BEVEL", width=0.018, segments=2, limit_method="ANGLE")
    parts = [body,
             C.box("plinth", (0.9, 0.4, 0.08), (0, 0, 0.04), "bronze", bevel=0.012, segments=1)]
    y, zc, hw, hh, b = -0.157, 1.35, 0.335, 0.955, 0.025
    for s in (-1, 1):
        parts.append(C.box(f"bz_side{s}", (b, 0.014, 2 * hh + 2 * b), (s * (hw + b / 2), y, zc), "bronze", bevel=0.004,
                           segments=1))
        parts.append(C.box(f"bz_end{s}", (2 * hw, 0.014, b), (0, y, zc + s * (hh + b / 2)), "bronze", bevel=0.004,
                           segments=1))
    ob = C.join("directory", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- planter
# The stand-in (buildConcourse's four corners): a drum 1.35 round at the
# floor, 1.5 at its top (0.6), the soil a disc of 1.42 at 0.59, a tree in it.
# The model: a honed dark stone bowl on a recessed bronze kick, a bronze
# band round its lip, the lip turned in to the soil's edge; the soil and
# the tree stay the page's (the soil kept over the model).
C.PALETTE.update({"planter_stone": (0x5e5852, 0.8, 0.0, "pebble")})


def planter():
    n = 32
    parts = [C.lathe("kick", [(1.28, 0.0), (1.28, 0.06), (1.33, 0.07)], "bronze", steps=n),
             C.lathe("bowl", [(1.33, 0.07), (1.37, 0.1), (1.42, 0.3), (1.47, 0.49), (1.48, 0.5)], "planter_stone", steps=n),
             C.lathe("band", [(1.48, 0.5), (1.51, 0.505), (1.515, 0.52), (1.515, 0.58), (1.505, 0.6), (1.48, 0.605)], "bronze",
                     steps=n),
             C.lathe("lip", [(1.48, 0.605), (1.43, 0.605), (1.42, 0.59), (1.42, 0.575)], "planter_stone", steps=n)]
    ob = C.join("planter", parts)
    drop_floor_faces(ob)
    return C.smooth(ob, 40)


# ---------------------------------------------------------------- balconies
# The rail, seen from the hall's floor 4.6 and 9.2 m below or across it:
# plain boxes but the handrail one's hand touches (part 4's furniture class
# is per prop; ~110 bays and as many posts, so each is kept to tens of
# triangles: 106 bays x 46 and 108 posts x 10 is ~6 k for the hall). The
# stand-in (buildConcourse): glass 0.9 tall, 3 cm thick, on the slab's top;
# the wooden top 0.1 x 0.06 round 0.93; posts 5 cm square every 1.6 m.
BAY = 1.6


def drop_faces(ob, keep):
    """Faces `keep(centre, normal)` says no to: a bay's ends (the next bay's
    butt against them), a post's top and foot (inside the rail and shoe)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bm.normal_update()
    gone = [f for f in bm.faces if not keep(f.calc_center_median(), f.normal)]
    bmesh.ops.delete(bm, geom=gone, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def balcony_rail():
    parts = [C.box("hand", (BAY, 0.1, 0.06), (0, 0, 0.93), "rail_wood", bevel=0.018, segments=1),
             C.box("chan", (BAY, 0.05, 0.03), (0, 0, 0.885), "bronze"),
             C.box("shoe", (BAY, 0.08, 0.08), (0, 0, 0.04), "bronze")]
    # the pane's frame round the page's glass (3 cm thick, 0.9 tall on the
    # floor): a bronze bead on its hall side over the shoe and under the
    # channel, and a stile through it at each end of the bay inside the
    # posts, so each bay reads as a framed pane; the glass itself stays
    # M.glass. No bead on the wall side: the balconies are never walked on
    # (seen from the hall's floor, through the glass, it was ~2.5 k
    # triangles the room's 40 k could not spare)
    parts += [C.box("bead_lo", (BAY, 0.012, 0.025), (0, -0.021, 0.0925), "bronze"),
              C.box("bead_hi", (BAY, 0.012, 0.02), (0, -0.021, 0.86), "bronze")]
    for s in (-1, 1):
        parts.append(C.box(f"stile{s}", (0.03, 0.054, 0.79), (s * (BAY / 2 - 0.04), 0, 0.475), "bronze"))
    ob = C.join("balcony_rail", parts)
    # the joined mesh is in its first part's frame (the handrail's, 0.93 up):
    # put it in the prop's before the faces are picked by height (until
    # 0.248.0 this dropped the handrail's and the channel's undersides, and
    # kept the shoe's foot)
    C.activate(ob)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

    def keep(c, n):
        # a bay's ends (the next bay butts on them; the handrail's bevel
        # there too, 24 triangles), the shoe's foot, and the frame's faces
        # that lie on the glass, the shoe or the channel
        if abs(n.x) > 0.3 and abs(c.x) > BAY / 2 - 0.02 or n.z < -0.99 and c.z < 0.002:
            return False
        if n.y > 0.99 and abs(c.y + 0.015) < 1e-3:
            return False
        on = abs(n.z) > 0.99 and (abs(c.z - 0.08) < 1e-3 or abs(c.z - 0.87) < 1e-3)
        return not (on and (abs(c.y + 0.021) < 1e-3 or abs(abs(c.x) - (BAY / 2 - 0.04)) < 1e-3))
    drop_faces(ob, keep)
    return C.smooth(ob, 35)


def rail_post():
    ob = C.box("rail_post", (0.05, 0.05, 0.79), (0, 0, 0.08 + 0.395), "bronze")
    drop_faces(ob, lambda c, n: abs(n.z) < 0.99)
    return C.smooth(ob, 35)


# The slab's edge, a 1.6 m bay of it under each of the rail's (placed with
# them): the page's slab is a 0.34 m box to the glass's line, its underside
# a ceiling plane 5 mm under it, the amber light 3 cm square along the line
# 0.36 under the floor. In the slab's putty (M.wall's #d6c4a6), so the two
# meet without a seam. The profile, (out toward the hall from the glass's
# line, height from the balcony's floor): an 8 mm lip over the slab's
# top (clear of it: no fight with the floor), bevelled down to a fascia 12.5
# cm out with a shadow reveal at its middle, a drip lip below the slab that
# hides the light from across the hall, and the soffit's cove the light hangs
# in. Its back, inside the page's slab, has no faces.
SLAB = [(-0.15, 0.0), (-0.14, 0.008), (0.10, 0.008), (0.125, -0.017), (0.125, -0.18), (0.115, -0.19),
        (0.115, -0.21), (0.125, -0.22), (0.125, -0.40), (0.11, -0.42), (0.08, -0.42), (0.07, -0.41), (0.07, -0.335),
        (0.0, -0.335), (0.0, -0.005)]


def extrude(name, prof, length, material):
    """`prof` [(out, z), ...], a closed outline, swept along X over `length`:
    its out is -Y, the prop's front (the hall). The ends triangulated: the
    bake's tangents refuse an n-gon."""
    bm = bmesh.new()
    ends = [[bm.verts.new((x, -u, z)) for u, z in prof] for x in (-length / 2, length / 2)]
    n = len(prof)
    for k in range(n):
        bm.faces.new((ends[0][k], ends[0][(k + 1) % n], ends[1][(k + 1) % n], ends[1][k]))
    caps = [bm.faces.new(ends[0]), bm.faces.new(ends[1][::-1])]
    bmesh.ops.triangulate(bm, faces=caps, quad_method="BEAUTY", ngon_method="EAR_CLIP")
    return mesh_from(name, bm, material)


def slab_edge():
    ob = extrude("slab_edge", SLAB, BAY, "putty")
    # the back (out 0, facing the slab) and the lip's underside lie in the
    # page's slab; the ends butt on the next bay's (at a corner, inside the
    # crossing run's edge; at the window, against it)
    end = BAY / 2 - 1e-3
    drop_faces(ob, lambda c, n: not (n.y > 0.99 and abs(c.y) < 0.005 and c.z < -0.004) and not (n.z < -0.99 and c.z > -0.01)
               and not (abs(n.x) > 0.99 and abs(c.x) > end))
    return C.smooth(ob, 35)


# ---------------------------------------------------------------- plinth
# The stand-in (buildConcourse): a cone 2.7 round at the floor, 2.4 at its
# top (0.7); the lit top, a disc 2.2 round 0.04 thick on it (kept: the
# atlas has no emission), the light line round it at 0.5 (the page's
# M.glowAmber since this model, the ring's one amber line carried up, 2.505
# round and 4 cm tall, in the groove the model leaves for it). The model:
# the ring's dark honed stone (#3a3632), a recessed kick, a base course,
# the body's batter to a bevelled top edge, a flat top face round the disc.
C.PALETTE.update({"plinth_stone": (0x3a3632, 0.4, 0.3, "pebble")})


def plinth():
    prof = [(2.64, 0.0), (2.64, 0.05), (2.7, 0.055), (2.72, 0.075), (2.72, 0.11), (2.7, 0.125), (2.66, 0.135),
            # the batter, the groove the line lies in, the top's bevel
            (2.53, 0.47), (2.5, 0.475), (2.5, 0.525), (2.52, 0.53), (2.45, 0.64), (2.43, 0.665), (2.4, 0.69),
            (2.36, 0.7), (2.15, 0.7), (2.15, 0.66)]
    ob = C.lathe("plinth", prof, "plinth_stone", steps=56)
    drop_floor_faces(ob)
    return C.smooth(ob, 30)


# The hologram's top, what the code built as a bare lit disc: a bronze
# bezel round it (the disc's edge under the bezel's inner lip) and the
# emitter the ship is projected from, a low bronze boss at its middle with
# a console-black lens. Placed on its own, at the plinth's axis on the floor.
def holo_top():
    parts = [C.lathe("bezel", [(2.34, 0.7), (2.345, 0.73), (2.33, 0.752), (2.3, 0.762), (2.22, 0.762),
                               (2.19, 0.752), (2.175, 0.74), (2.17, 0.735)], "bronze", steps=56),
             C.lathe("boss", [(0.46, 0.739), (0.46, 0.75), (0.44, 0.78), (0.4, 0.8), (0.3, 0.805)], "bronze", steps=24),
             C.lathe("lens", [(0.3, 0.805), (0.29, 0.81), (0.2, 0.818), (0.0, 0.822)], "console", steps=24)]
    ob = C.join("holo_top", parts)
    return C.smooth(ob, 30)


# The stand-in's leaf: 1.5 x 2.3, 0.1 deep round the origin (its front 5 cm
# before it, toward -Y); the red seam 6 cm before it, the amber light 1.3 x
# 0.05 round 2.4, 7 cm before it, 2 cm thick. The wall's face is 2 cm behind
# the origin, so the frame's back is sunk 1 cm into it.
C.PALETTE.update({"door_leaf": (0xa89d8c, 0.6, 0.3, "brushed")})


def balcony_door():
    F, W, back = -0.065, 0.1, 0.03
    parts = []
    for s in (-1, 1):
        # the leaves, a centimetre apart: the seam the red light runs down
        parts.append(C.box(f"leaf{s}", (0.745, 0.08, 2.3), (s * 0.3775, -0.01, 1.15), "door_leaf"))
        parts.append(C.box(f"jamb{s}", (W, back - F, 2.5), (s * (0.75 + W / 2), (back + F) / 2, 1.25), "bronze",
                           bevel=0.01, segments=1))
    for z0, z1 in ((2.3, 2.36), (2.44, 2.5)):
        parts.append(C.box(f"head{z0}", (1.5, back - F, z1 - z0), (0, (back + F) / 2, (z0 + z1) / 2), "bronze",
                           bevel=0.01, segments=1))
    # behind the light, between the bars: console black, 3 cm proud
    parts.append(C.box("lamp", (1.5, back + 0.03, 0.08), (0, (back - 0.03) / 2, 2.4), "console"))
    ob = C.join("balcony_door", parts)
    drop_floor_faces(ob)
    drop_faces(ob, lambda c, n: not (n.y > 0.99 and c.y > back - 1e-3))
    return C.smooth(ob, 35)


C.clean_scene()
# the column's shaft unrolled, cut at its collars (common.UNWRAP_HINTS): the
# brushed bronze had blotches at 2.5 m under the smart projection
C.UNWRAP_HINTS["column"] = ("cylinder", [4.12, 4.73])
props = [ring_bench(), column(), directory(), planter(), balcony_rail(), rail_post(), balcony_door(), slab_edge(), plinth(),
         holo_top()]
for p in props:
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
C.finish_room("concourse", props, size=1024)
