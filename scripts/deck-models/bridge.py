"""The bridge's props (docs/design/deck-style.md part 2, "Bridge"):
lcars-ui/deck/bridge.glb: the captain's chair (the pipeline's first prop),
the conn and ops console, the tactical rail and the standing station; the
conn's and ops' own chair and the command chairs' armrest consoles
(0.237.0).

    blender -b --factory-startup -P scripts/deck-models/bridge.py -- OUT_DIR [CHAIR_DIR]

The captain's chair is the generated one from CHAIR_DIR when build.sh has it
(bridge-redesign.md 8c: Tripo's, in the media store), else `captain_chair()`
below, which stays as the fallback and the measure the generated one was
fitted to.

Coordinates: metres, Blender's +Z up, the chair's front toward -Y (glTF's
+Z once exported). The chair is built to the code-built one's measures
(`chair(x, z, s, rich)` in deck.html: the seat's top at 0.58, the arms at
x +-0.36 and their fronts at y -0.255, where the page's blinking status
lights sit), so the stand-in's seat, footprint and lights fit it; the
captain's is the same model stretched 1.15 across, as the stand-in is.

The others are built the same way, each to its stand-in's measures in
deck.html, because the stand-in's display, status lights and blocks stay
where the code put them and the model must sit round them:
- `conn_console`, over both of `consoleBody(cg, 1.5, 0.62, 0.6, 0.84, ...)`
  (conn and ops): its display lies 0.0165 above the middle of the tilted
  top, its lights on the near face at y 0.5, z 0.31;
- `tactical_rail`, over each of the two arcs (radius 4.0 about the group's
  origin, the arc from angle 0 to ARC measured from +z toward +x, as the
  page's group turns it): its origin is the circle's centre, not the
  footprint's (deck-pipeline.md's decisions);
- `station`, over the four standing stations round the wall (1.8 wide,
  0.45 deep, the display at y 0.905 in a top tilted 0.4), and
  `station_long`, the same 2.6 long, over the pair either side of the
  viewscreen;
- `screen_fin` and `display_bezel` have no stand-in: the viewscreen's
  bulkheads and the wall displays' frames, placed by position.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402

# The command chairs' shells (bridge-redesign.md, slice 2): burgundy leather
# on the outside as on the set, where they were black and read from behind
# as office chairs; a shade darker than the cushions' so the shell still
# frames them rather than melting into one red block. A palette entry, not a
# material: it is baked into the bridge atlas with the rest, +0 draw calls.
C.PALETTE["bridge_shell"] = (0x4a1715, 0.5, 0.0, "pebble")


def back_shell(name):
    """The shell the back's cushions sit in: a sheet curved round the
    sitter (its sides come forward), thickened and bevelled, rising to a
    rounded top that is the headrest's. Z1 1.35 (1.27 until slice 2 of
    bridge-redesign.md): the set's back stands taller to the headrest."""
    bm = bmesh.new()
    nx, nz, W, Z0, Z1 = 10, 9, 0.68, 0.5, 1.35
    rows = []
    for j in range(nz + 1):
        z = Z0 + (Z1 - Z0) * j / nz
        # narrower toward the top: the headrest's shoulders
        w = W * (1 - 0.3 * max(0, (z - 1.13) / (Z1 - 1.13)) ** 1.5)
        row = []
        for i in range(nx + 1):
            u = i / nx * 2 - 1
            x = u * w / 2
            row.append(bm.verts.new((x, 0.38 - 0.11 * u * u, z)))
        rows.append(row)
    for j in range(nz):
        for i in range(nx):
            bm.faces.new((rows[j][i], rows[j][i + 1], rows[j + 1][i + 1], rows[j + 1][i]))
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = C.link(bpy.data.objects.new(name, me))
    ob.data.materials.append(C.mat("bridge_shell"))
    # centred on the sheet: its face is then 0.35 at the middle, behind the
    # cushions (0.21-0.33), whichever way the faces happen to point
    C.modifier(ob, "SOLIDIFY", thickness=0.06, offset=0)
    C.modifier(ob, "BEVEL", width=0.018, segments=2, limit_method="ANGLE")
    return ob


def tilt(objs, pivot, angle):
    """Lean `objs` back about the X axis through `pivot` (negative leans
    the top toward +Y, away from the chair's front)."""
    from mathutils import Matrix
    # a new object's matrix_world is identity until the view layer is
    # updated: without this the cushions were leaned from the origin, and
    # landed under the seat
    bpy.context.view_layer.update()
    R = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, "X") @ Matrix.Translation([-c for c in pivot])
    for o in objs:
        o.matrix_world = R @ o.matrix_world


def captain_chair():
    parts = []
    # the turned pedestal, as the stand-in's lathe
    parts.append(C.lathe("ped", [(0.001, 0), (0.3, 0), (0.3, 0.02), (0.24, 0.05), (0.15, 0.1), (0.12, 0.3),
                                 (0.17, 0.38), (0.2, 0.42), (0.001, 0.42)], "trim", steps=20))
    # the seat: a shell pan, the cushion in it, piping round its top
    parts.append(C.box("pan", (0.68, 0.64, 0.08), (0, 0.0, 0.44), "console", bevel=0.025))
    parts.append(C.pad("seat", (0.58, 0.56, 0.14), (0, 0.0, 0.52), "bridge_leather"))
    r = 0.06
    loop = []
    for cx, cy, a0 in ((0.27, -0.25, -90), (0.27, 0.25, 0), (-0.27, 0.25, 90), (-0.27, -0.25, 180)):
        for k in range(4):
            a = math.radians(a0 + k * 30)
            loop.append((cx - r * math.copysign(1, cx) + r * math.cos(a), cy - r * math.copysign(1, cy) + r * math.sin(a), 0.565))
    parts.append(C.tube("piping", loop, 0.008, "bridge_piping", closed=True))
    # the back: shell, three cushions (lumbar, back, headrest), a brushed
    # plate down the outside, leaned back as the stand-in's is
    back = [back_shell("shell"),
            C.pad("lumbar", (0.54, 0.12, 0.3), (0, 0.27, 0.72), "bridge_leather"),
            C.pad("upper", (0.54, 0.12, 0.32), (0, 0.27, 1.02), "bridge_leather"),
            C.pad("head", (0.38, 0.11, 0.13), (0, 0.27, 1.27), "bridge_leather"),
            C.box("plate", (0.14, 0.012, 0.62), (0, 0.417, 0.88), "trim", bevel=0.004, segments=2)]
    tilt(back, (0, 0.3, 0.5), -0.08)
    parts += back
    # the arms: a side panel down to the pan, the arm, a padded top that
    # stops short of the front, where the armrest console slopes down to
    # the face the page's status lights sit on
    for sx in (-1, 1):
        x = sx * 0.36
        parts.append(C.box(f"side{sx}", (0.07, 0.42, 0.16), (x, 0.06, 0.54), "console", bevel=0.015))
        parts.append(C.box(f"arm{sx}", (0.1, 0.55, 0.12), (x, 0.02, 0.66), "console", bevel=0.025))
        parts.append(C.pad(f"armpad{sx}", (0.11, 0.42, 0.045), (x, 0.08, 0.735), "bridge_leather"))
        p = C.box(f"panel{sx}", (0.084, 0.11, 0.012), (x, -0.19, 0.722), "black", bevel=0.003, segments=1)
        p.rotation_euler.x = 0.22
        parts.append(p)
    ob = C.join("captain_chair", parts)
    return C.smooth(ob, 35)


TOP_TILT = math.atan2(0.84 - 0.6, 0.62)   # consoleBody's tilt for conn and ops
TOP_Y = (0.6 + 0.84) / 2 + 0.012          # and the tilted group's height


def prism(name, poly, x0, x1, material, bevel=0.0, segments=2):
    """A profile `poly` [(y, z), ...] in Blender's Y-Z plane (one way round,
    any), extruded along X from x0 to x1: a wedge, a sloped body."""
    bm = bmesh.new()
    a = [bm.verts.new((x0, y, z)) for y, z in poly]
    b = [bm.verts.new((x1, y, z)) for y, z in poly]
    n = len(poly)
    for i in range(n):
        j = (i + 1) % n
        bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(a)
    bm.faces.new(b[::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh(name, bm, material, bevel, segments)


def _mesh(name, bm, material, bevel=0.0, segments=2):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = C.link(bpy.data.objects.new(name, me))
    ob.data.materials.append(C.mat(material))
    if bevel:
        C.modifier(ob, "BEVEL", width=bevel, segments=segments, limit_method="ANGLE")
    return ob


def rrect(w, d, r, k=3, cy=0.0):
    """A rounded rectangle's outline, w across x, d along y, centred on
    (0, cy): 4 * (k + 1) points, the same count whatever its size, so two
    of them loft."""
    r = min(r, w / 2 - 1e-3, d / 2 - 1e-3)
    pts = []
    for cx, cyy, a0 in ((w / 2 - r, d / 2 - r, 0), (-w / 2 + r, d / 2 - r, 90), (-w / 2 + r, -d / 2 + r, 180), (w / 2 - r, -d / 2 + r, 270)):
        for i in range(k + 1):
            a = math.radians(a0 + 90 * i / k)
            pts.append((cx + r * math.cos(a), cy + cyy + r * math.sin(a)))
    return pts


def loft(name, sections, material, r=0.05):
    """Rounded rectangles [(z, w, d, cy), ...] bottom to top, skinned and
    capped: a pedestal that flares at the floor."""
    bm = bmesh.new()
    rings = [[bm.verts.new((x, y, z)) for x, y in rrect(w, d, r, cy=cy)] for z, w, d, cy in sections]
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(rings[0])
    bm.faces.new(rings[-1][::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh(name, bm, material)


def sweep(name, prof, a0, a1, R, steps, material, caps=True):
    """A closed profile `prof(a)` -> [(dr, z), ...] swept round the Z axis
    at radius R from angle a0 to a1, the angles from Blender's -Y (the
    page's +z) toward +X, as the page's arcs are measured: a rail, a curved
    panel. `prof` may change along the sweep (the tactical panel's bulge)."""
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        rings.append([bm.verts.new(((R + dr) * math.sin(a), -(R + dr) * math.cos(a), z)) for dr, z in prof(a)])
    n = len(rings[0])
    for p, q in zip(rings, rings[1:]):
        for k in range(n):
            k1 = (k + 1) % n
            bm.faces.new((p[k], p[k1], q[k1], q[k]))
    if caps:
        bm.faces.new(rings[0])
        bm.faces.new(rings[-1][::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return _mesh(name, bm, material)


def placed(objs, M):
    bpy.context.view_layer.update()
    for o in objs:
        o.matrix_world = M @ o.matrix_world
    return objs


def conn_console():
    """The conn and ops console: a flared pedestal, a body whose near face
    carries the stand-in's status lights, and a bevelled top tilted toward
    the chair that overhangs the body on the near side and the ends, with a
    leather lip along its near edge and the display (the stand-in's own
    plane, kept) set in a recess. Built in the page's console frame: +z
    (Blender's -Y) toward the operator."""
    from mathutils import Matrix
    th = TOP_TILT
    # a point (u along the top toward the operator, v up from its middle) of
    # the tilted top, as Blender (Y, Z)
    def under(z, v=-0.012):
        u = (z - v * math.sin(th)) / math.cos(th)
        return TOP_Y + v * math.cos(th) - u * math.sin(th)
    parts = []
    # the pedestal, flaring to the floor, and the body on it (near face at
    # z 0.31, where the lights are). The far face, the one the viewscreen
    # sees (bridge-redesign.md slice 3), rakes in toward the floor: -0.27
    # under the top, -0.17 at the pedestal, so the top overhangs a slimmer
    # foot as on the set, not a 1.5 by 0.8 m slab of flat black; the
    # pedestal is set in with it (its far edge 0.19, was 0.27)
    zt = under(-0.27)
    parts.append(loft("ped", [(0.0, 1.46, 0.64, -0.06), (0.02, 1.45, 0.63, -0.06), (0.05, 1.4, 0.58, -0.06),
                              (0.1, 1.34, 0.53, -0.06), (0.17, 1.3, 0.5, -0.06)], "console", r=0.06))
    parts.append(prism("body", [(0.17, 0.16), (-0.31, 0.16), (-0.31, under(0.31)), (0.27, zt)],
                       -0.65, 0.65, "console", bevel=0.02))
    # a brushed band where the body meets the pedestal
    parts.append(C.box("band", (1.32, 0.52, 0.03), (0, -0.06, 0.175), "trim", bevel=0.008, segments=2))
    # and a brushed trim line across the raked far face at a third of its
    # height, leaning with it, standing 4 mm proud
    rake = math.atan2(0.27 - 0.17, zt - 0.16)
    zl = 0.16 + (zt - 0.16) / 3
    trim = C.box("trimline", (1.24, 0.008, 0.025), (0, 0.17 + 0.1 / 3 + 0.002, zl), "trim", bevel=0.003, segments=1)
    trim.rotation_euler.x = -rake
    parts.append(trim)
    # the top, in its own frame: Blender (x, -u, v), then tilted and raised
    # The top's rim (bridge-redesign.md section 9, slice 1): the set's
    # lacquered wood round the far edge and both ends, a full bullnose 7 cm
    # deep that drops below the slab, so from the viewscreen (view C) the
    # console reads as a dark body under a lit, edged top - the concepts' -
    # not a black box with a flat lid. `rail_wood`, the tactical rail's and
    # the stations' caps: a palette entry baked into the atlas, +0 calls.
    top = [C.box("slab", (1.6, 0.8, 0.03), (0, -0.04, -0.01), "console", bevel=0.012, segments=3),
           C.box("far", (1.66, 0.07, 0.07), (0, 0.34, 0.0), "rail_wood", bevel=0.024, segments=3),
           C.box("near", (1.56, 0.04, 0.03), (0, -0.29, 0.012), "console", bevel=0.006, segments=2),
           C.pad("lip", (1.56, 0.14, 0.055), (0, -0.37, 0.022), "bridge_leather"),
           C.box("well", (1.44, 0.54, 0.016), (0, 0, 0.0), "black", bevel=0.002, segments=1)]
    for sx in (-1, 1):
        # the ends, from the leather lip to the far rim, as deep as it
        top.append(C.box(f"cheek{sx}", (0.07, 0.7, 0.07), (sx * 0.795, 0.0, 0.0), "rail_wood", bevel=0.024, segments=3))
    placed(top, Matrix.Translation((0, 0, TOP_Y)) @ Matrix.Rotation(th, 4, "X"))
    parts += top
    return C.smooth(C.join("conn_console", parts), 35)


def conn_chair():
    """The conn's and ops' chair, furniture (<= 1.5 k triangles; the
    captain's at 0.9 would be +10 k): no arms, a seat in a shell pan, a
    slim back with a low headrest, on the command chairs' turned pedestal.
    Built at the stand-in's measures for `chair(x, z, 0.9, true)` (the seat
    0.54 across, its top at 0.58, the back behind y 0.2), so it is placed
    unscaled. Plain bevelled blocks, no subdivided cushions: those are
    what make the captain's 5 k."""
    parts = [C.lathe("ped", [(0.001, 0), (0.27, 0), (0.27, 0.02), (0.15, 0.08), (0.11, 0.3), (0.16, 0.38),
                             (0.18, 0.42), (0.001, 0.42)], "trim", steps=14),
             C.box("pan", (0.58, 0.58, 0.07), (0, 0.0, 0.445), "console", bevel=0.02, segments=2),
             C.box("seat", (0.52, 0.52, 0.1), (0, -0.01, 0.53), "bridge_leather", bevel=0.035, segments=3),
             # the front edge rolled down over the pan, where the knees go
             C.box("roll", (0.52, 0.06, 0.08), (0, -0.25, 0.51), "bridge_leather", bevel=0.03, segments=3)]
    back = [C.box("shell", (0.5, 0.05, 0.62), (0, 0.33, 0.83), "bridge_shell", bevel=0.018, segments=2),
            C.box("cushion", (0.44, 0.08, 0.5), (0, 0.28, 0.82), "bridge_leather", bevel=0.035, segments=3),
            # the low headrest on a brushed stem, standing off the shell's top
            C.box("stem", (0.08, 0.04, 0.12), (0, 0.33, 1.16), "trim", bevel=0.008, segments=1),
            C.box("head", (0.32, 0.09, 0.12), (0, 0.3, 1.24), "bridge_leather", bevel=0.035, segments=3),
            C.box("plate", (0.12, 0.012, 0.44), (0, 0.36, 0.83), "trim", bevel=0.004, segments=1)]
    tilt(back, (0, 0.3, 0.5), -0.1)
    return C.smooth(C.join("conn_chair", parts + back), 35)


ATILT = math.atan2(0.65 - 0.56, 0.5)   # consoleBody's tilt for the armrest consoles
ATOP_Y = (0.56 + 0.65) / 2 + 0.012


def armrest_console():
    """The armrest console either side of the command chairs, over
    `consoleBody(cg, 1.1, 0.5, 0.56, 0.65, ...)`: the conn console's build
    at its size, without the lip - a slim pedestal, a body whose near face
    carries the stand-in's six blinking lights (y 0.46, z 0.253), and a
    bevelled top tilted toward the chairs with a recess round the
    stand-in's display (1.0 x 0.45, 0.0165 above the tilted top's middle).
    Page frame as conn_console's: +z (Blender -Y) toward the chairs."""
    from mathutils import Matrix
    th = ATILT

    def under(z, v=-0.012):
        u = (z - v * math.sin(th)) / math.cos(th)
        return ATOP_Y + v * math.cos(th) - u * math.sin(th)
    parts = [loft("ped", [(0.0, 1.0, 0.5, -0.02), (0.02, 0.99, 0.49, -0.02), (0.06, 0.92, 0.42, -0.02),
                          (0.14, 0.9, 0.4, -0.02)], "console", r=0.05),
             prism("body", [(0.21, 0.13), (-0.25, 0.13), (-0.25, under(0.25)), (0.21, under(-0.21))],
                   -0.5, 0.5, "console", bevel=0.016),
             C.box("band", (0.94, 0.42, 0.025), (0, -0.02, 0.145), "trim", bevel=0.006, segments=2)]
    top = [C.box("slab", (1.16, 0.6, 0.03), (0, -0.01, -0.01), "console", bevel=0.012, segments=3),
           C.box("far", (1.16, 0.05, 0.03), (0, 0.27, 0.012), "console", bevel=0.008, segments=2),
           C.box("near", (1.16, 0.05, 0.03), (0, -0.27, 0.012), "console", bevel=0.008, segments=2),
           C.box("well", (1.04, 0.49, 0.016), (0, 0, 0.0), "black", bevel=0.002, segments=1)]
    for sx in (-1, 1):
        top.append(C.box(f"cheek{sx}", (0.06, 0.5, 0.03), (sx * 0.55, 0.0, 0.012), "console", bevel=0.008, segments=2))
    placed(top, Matrix.Translation((0, 0, ATOP_Y)) @ Matrix.Rotation(th, 4, "X"))
    parts += top
    return C.smooth(C.join("armrest_console", parts), 35)


TR, ARC = 4.0, math.pi * 0.33   # the page's tactical rail: radius, each arc's sweep


def tactical_rail():
    """One arc of the tactical rail: a wooden cap with a carved profile (a
    rounded top over an undercut cove) on six posts, a dark panel between
    them and a black kick; at the arc's middle the cap swells into the
    tactical panel, a black face in a brushed bezel set in its top, which
    the page lights (its glow and blinking lights, shared materials)."""
    mid = ARC / 2
    span = 0.42 / TR      # the swell's half-length, as an angle

    def swell(a):
        t = max(0.0, 1 - abs(a - mid) / span)
        return t * t * (3 - 2 * t)

    def cap(a):
        s = 1 + 0.55 * swell(a)
        # (dr, z) round the section: the undercut cove under the inside
        # edge, the rounded top, the cove under the outside edge
        # (bridge-redesign.md section 9, slice 2: a fuller, rounder roll,
        # the set's padded rail, 27 cm across where it was 24; the top
        # stays at 1.14, where the tactical panel's bezel sits)
        half = [(0.055, 0.962), (0.095, 0.972), (0.122, 0.995), (0.136, 1.03), (0.136, 1.068),
                (0.122, 1.1), (0.094, 1.123), (0.052, 1.136)]
        return ([(-dr * s, z) for dr, z in half] + [(0, 1.14)] + [(dr * s, z) for dr, z in reversed(half)])

    steps = 44
    parts = [sweep("cap", cap, 0, ARC, TR, steps, "rail_wood")]
    # the panel between the posts, set back under the cap, and the kick
    parts.append(sweep("panel", lambda a: [(-0.035, 0.1), (0.035, 0.1), (0.035, 0.98), (-0.035, 0.98)], 0.012, ARC - 0.012, TR, 16, "wainscot"))
    parts.append(sweep("kick", lambda a: [(-0.025, 0.0), (0.025, 0.0), (0.025, 0.1), (-0.025, 0.1)], 0.012, ARC - 0.012, TR, 16, "black"))
    # a stout post at each end; between them the panel is cut into bays by
    # slim dark seams standing proud of both faces (slice 2: the set's
    # seamed panels, where four more posts made it read as a fence)
    for i, a in enumerate((0.015, ARC - 0.015)):
        p = C.box(f"post{i}", (0.1, 0.13, 0.98), (TR * math.sin(a), -TR * math.cos(a), 0.49), "console", bevel=0.015, segments=2)
        p.rotation_euler.z = a
        parts.append(p)
    for i in range(1, 8):
        a = ARC * i / 8
        p = C.box(f"seam{i}", (0.022, 0.082, 0.86), (TR * math.sin(a), -TR * math.cos(a), 0.53), "black")
        p.rotation_euler.z = a
        parts.append(p)
    # the tactical panel: a bezel and the black face it holds, curved with
    # the rail, standing a little proud of the swollen cap's flat
    w = 0.3 / TR
    # (a frame, not a block: the face and the page's glow on it sit below
    # its rim, 1.146-1.158)
    e = 0.02 / TR
    ring = lambda r0, r1, z0, z1: (lambda a: [(r0, z0), (r1, z0), (r1, z1), (r0, z1)])
    parts.append(sweep("bezel", ring(-0.1, 0.1, 1.12, 1.146), mid - w - e, mid + w + e, TR, 8, "trim"))
    for r0, r1 in ((-0.1, -0.075), (0.075, 0.1)):
        parts.append(sweep(f"rim{r0}", ring(r0, r1, 1.145, 1.158), mid - w, mid + w, TR, 8, "trim"))
    for a0 in (mid - w - e, mid + w):
        parts.append(sweep(f"end{a0}", ring(-0.1, 0.1, 1.145, 1.158), a0, a0 + e, TR, 1, "trim"))
    parts.append(sweep("face", ring(-0.075, 0.075, 1.14, 1.15), mid - w, mid + w, TR, 8, "black"))
    return C.smooth(C.join("tactical_rail", parts), 35)


def station(name="station", L=1.8):
    """A standing station: a body with a sloped top that holds the display
    (the stand-in's plane) in a bezel, end panels standing off it at a dark
    seam, a recessed kick plate and the lit slot above it (the stand-in's
    glow strip, at y 0.1 on the near face). The top's rim is a wooden cap
    (bridge-redesign.md slice 5, `rail_wood` as the tactical rail's): a
    rounded bullnose along the near edge, where the hands rest, the far edge
    and the cheeks. `L` is its length: 1.8, the stand-in's, for the four
    round the wall; 2.6 for `station_long`, the counter either side of the
    viewscreen, its display still the stand-in's 1.7 in the middle of a black
    inset run the counter's length."""
    from mathutils import Matrix
    th = 0.4
    h = L / 2
    # the underside of the stand-in's slab, centred at (0.881, z 0.01)
    def under(z, v=-0.018):
        u = (z - 0.01 - v * math.sin(th)) / math.cos(th)
        return 0.881 + v * math.cos(th) - u * math.sin(th)
    parts = [prism("body", [(-0.225, 0.13), (0.215, 0.13), (0.215, under(-0.215)), (-0.225, under(0.225))],
                   -(h - 0.1), h - 0.1, "console", bevel=0.01),
             C.box("slot", (L - 0.2, 0.4, 0.06), (0, 0.0, 0.105), "black"),
             C.box("kick", (L - 0.18, 0.39, 0.08), (0, 0.01, 0.04), "trim", bevel=0.006, segments=1)]
    for sx in (-1, 1):
        parts.append(prism(f"end{sx}", [(-0.235, 0.0), (0.235, 0.0), (0.235, under(-0.235) + 0.01), (-0.235, under(0.235) + 0.01)],
                           sx * (h - 0.09), sx * h, "trim", bevel=0.012))
        parts.append(C.box(f"seam{sx}", (0.012, 0.44, under(0) - 0.02), (sx * (h - 0.095), 0, (under(0) - 0.02) / 2), "black"))
    top = [C.box("slab", (L - 0.18, 0.5, 0.03), (0, 0, 0.0), "console", bevel=0.01, segments=2),
           C.box("well", (L - 0.08, 0.42, 0.012), (0, 0, 0.018), "black"),
           # the cap: the near edge (-Y, the operator's) a rounder, fuller
           # bullnose than the far one
           C.box("lip-1", (L + 0.04, 0.05, 0.034), (0, -0.235, 0.028), "rail_wood", bevel=0.014, segments=3),
           C.box("lip1", (L + 0.04, 0.04, 0.026), (0, 0.23, 0.026), "rail_wood", bevel=0.008, segments=2)]
    for sx in (-1, 1):
        top.append(C.box(f"cheek{sx}", (0.06, 0.5, 0.026), (sx * (h - 0.01), 0, 0.026), "rail_wood", bevel=0.008, segments=2))
    # the slab's frame: Blender (x, -u, v) about its middle, as the stand-in's
    placed(top, Matrix.Translation((0, -0.01, 0.881)) @ Matrix.Rotation(th, 4, "X"))
    parts += top
    return C.smooth(C.join(name, parts), 35)


def display_bezel():
    """The wall displays' bezel (bridge-redesign.md slice 5): a brushed frame
    4 cm deep round the page's `panel(2.6, 1.3, ...)`, its face 2 cm proud of
    the display, so the display reads set into the wall rather than hung on
    it. Centred on the display's middle, its front toward -Y (the page's
    +z, the room)."""
    W, Hh, b = 2.6, 1.3, 0.07
    # 1 cm over the display's edges, so no gap shows at a slant
    iw, ih = W - 0.02, Hh - 0.02
    ow, oh = iw + 2 * b, ih + 2 * b
    parts = []
    for sz in (-1, 1):
        parts.append(C.box(f"rail{sz}", (ow, 0.04, b), (0, 0.0, sz * (ih + b) / 2), "trim", bevel=0.008, segments=1))
    for sx in (-1, 1):
        parts.append(C.box(f"stile{sx}", (b, 0.04, ih), (sx * (iw + b) / 2, 0.0, 0), "trim", bevel=0.008, segments=1))
    return C.smooth(C.join("display_bezel", parts), 35)


def screen_fin():
    """One of the viewscreen's two bulkheads (bridge-redesign.md slice 4):
    the set's sculpted fins either side of the screen, from the floor to the
    ceiling (the page's BH, 4.6), standing off the wall and leaning back into
    it as they rise - deep and flared at the foot, slim under the ceiling. Its
    back on the wall at Y 0, its face toward -Y (the page's +z, the room's
    centre), so it is placed on the wall's circle facing in as the stations
    are. Putty like the wall it grows from, the wainscot's line carried round
    it in a brushed band, a black kick, and a dark slot down the raked face
    in a brushed frame. Palette entries all: +0 draw calls."""
    H = 4.6
    # the face's rake above the flare: its front from -0.53 at 1.0 m to -0.25
    # at the ceiling, straight, so the slot can lie on it
    def front(z):
        return -0.53 + 0.28 * (z - 1.0) / (H - 1.0)
    # (z, width, front) bottom to top, the back at +0.04, inside the wall's
    # skin: the putty body from the band up; under it the wainscot's foot,
    # 15 mm proud of the body's line, flaring to the floor, on a black kick
    sec = lambda rows: [(z, w, 0.04 - f, (0.04 + f) / 2) for z, w, f in rows]
    parts = [loft("body", sec([(0.96, 0.68, front(0.96)), (2.4, 0.6, front(2.4)), (H, 0.52, front(H))]), "putty", r=0.06),
             loft("foot", sec([(0.08, 0.82, -0.71), (0.35, 0.77, -0.64), (0.98, 0.695, front(0.98) - 0.015)]), "wainscot", r=0.06),
             loft("kick", sec([(0.0, 0.79, -0.68), (0.09, 0.79, -0.68)]), "black", r=0.05)]
    # the brushed band where they meet, at the wainscot's top (the wall's
    # lower band ends at 0.95)
    parts.append(loft("band", sec([(0.93, 0.72, front(0.95) - 0.03), (0.99, 0.72, front(0.95) - 0.03)]), "trim", r=0.06))
    # the slot down the face, on the rake, with its frame
    rake = math.atan2(0.28, H - 1.0)
    z0, z1 = 1.35, 3.95
    zm = (z0 + z1) / 2
    slot = [C.box("frame", (0.2, 0.02, z1 - z0 + 0.04), (0, front(zm) - 0.004, zm), "trim", bevel=0.006, segments=1),
            C.box("slot", (0.13, 0.02, z1 - z0 - 0.02), (0, front(zm) - 0.008, zm), "black")]
    for o in slot:
        o.rotation_euler.x = -rake
    parts += slot
    return C.smooth(C.join("screen_fin", parts), 35)


def pull_leather(ob, toward="bridge_leather"):
    """Shift the hue and saturation of `ob`'s image-textured base colours so
    their red texels' mean is the palette's `toward`: Tripo's leather came
    out pinker and brighter-red than the conn chairs' (bridge-redesign.md
    8c). A Hue/Saturation node before Base Color, which the bake carries
    into the atlas; materials with no image there (the palette's own, the
    pedestal's `trim`) are left alone. Its value is pulled too: the texture's
    cushions are lighter than the palette's leather, and turned to its hue
    alone they read orange-tan under the bridge's warm light."""
    import colorsys

    import numpy as np
    def lin(c):
        # sRGB to linear: the node works on the texture node's output, which
        # is linear, so the means and the target are taken there
        return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    hexv = C.PALETTE[toward][0]
    t = lin(np.array([(hexv >> 16) & 255, (hexv >> 8) & 255, hexv & 255], np.float64) / 255)
    th, ts, tv = colorsys.rgb_to_hsv(*t)
    for slot in ob.material_slots:
        m = slot.material
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
        if not bsdf or not bsdf.inputs["Base Color"].is_linked:
            continue
        link = bsdf.inputs["Base Color"].links[0]
        tex = link.from_node
        if tex.type != "TEX_IMAGE" or not tex.image:
            continue
        # a byte image's pixels are its sRGB values; HSV by hand over numpy
        # (4 M texels)
        px = np.empty(len(tex.image.pixels), np.float32)
        tex.image.pixels.foreach_get(px)
        rgb = lin(px.reshape(-1, 4)[:, :3])
        mx, mn = rgb.max(1), rgb.min(1)
        d = np.maximum(mx - mn, 1e-6)
        r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
        h = np.where(mx == r, ((g - b) / d) % 6, np.where(mx == g, (b - r) / d + 2, (r - g) / d + 4)) / 6
        sat = (mx - mn) / np.maximum(mx, 1e-6)
        # the leather: reds (within 40 degrees of red either way), coloured
        # enough to have a hue, not the black consoles or the grey pan
        red = ((h < 0.11) | (h > 0.89)) & (sat > 0.5) & (mx > 0.01)
        if red.sum() < 1000:
            continue
        a = h[red] * 2 * math.pi
        mh = math.atan2(float(np.sin(a).mean()), float(np.cos(a).mean())) / (2 * math.pi) % 1
        ms, mv = float(sat[red].mean()), float(mx[red].mean())
        dh = (th - mh + 0.5) % 1 - 0.5
        hs = m.node_tree.nodes.new("ShaderNodeHueSaturation")
        hs.inputs["Hue"].default_value = 0.5 + dh
        hs.inputs["Saturation"].default_value = min(1.5, max(0.5, ts / ms))
        hs.inputs["Value"].default_value = min(1.5, max(0.5, tv / mv))
        m.node_tree.links.new(link.from_socket, hs.inputs["Color"])
        m.node_tree.links.new(hs.outputs["Color"], bsdf.inputs["Base Color"])
        print(f"[deck-models] bridge/{ob.name}: leather hue {mh:.3f} -> {th:.3f}, saturation {ms:.2f} x{hs.inputs['Saturation'].default_value:.2f}, value {mv:.3f} x{hs.inputs['Value'].default_value:.2f}")


def pull_plate(ob, k=0.68):
    """Darken the generated chair's light unsaturated texels (its brushed
    back plate and the arms' metal: 17% of the texture, grey at 0.56 in
    sRGB) toward a brushed grey, with a faint streak along the texture's u
    (bridge-redesign.md section 9, slice 3). They are no lighter than
    `trim`, but nothing else on the chair is near them, and under the
    bridge's overhead light the plate baked to a flat near-white slab from
    behind (view B). Done on the source image's pixels, before the bake: a
    node could not pick the plate out from the leather by colour. The mask
    ramps in over a band of saturation and value, so its edge leaves no
    seam; the leather, the black and the consoles' greys below 0.4 are
    untouched."""
    import numpy as np
    for slot in ob.material_slots:
        m = slot.material
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
        if not bsdf or not bsdf.inputs["Base Color"].is_linked:
            continue
        tex = bsdf.inputs["Base Color"].links[0].from_node
        # past pull_leather's Hue/Saturation node, by whichever input is linked
        while tex.type != "TEX_IMAGE":
            inp = next((i for i in tex.inputs if i.is_linked), None)
            if not inp:
                break
            tex = inp.links[0].from_node
        if tex.type != "TEX_IMAGE" or not tex.image:
            continue
        img = tex.image
        w, h = img.size
        px = np.empty(len(img.pixels), np.float32)
        img.pixels.foreach_get(px)
        a = px.reshape(h, w, 4)
        rgb = a[..., :3]
        mx, mn = rgb.max(2), rgb.min(2)
        sat = (mx - mn) / np.maximum(mx, 1e-6)
        # 1 where grey and light, 0 below 0.4 or above 0.3 saturation
        wv = np.clip((mx - 0.4) / 0.1, 0, 1)
        ws = np.clip((0.3 - sat) / 0.1, 0, 1)
        wm = (wv * ws)[..., None]
        rng = np.random.default_rng(7)
        streak = 1 + 0.06 * np.repeat(rng.standard_normal((h, 1)), w, 1)[..., None]
        rgb[:] = rgb * (1 - wm) + rgb * k * streak * wm
        img.pixels.foreach_set(px)
        print(f"[deck-models] bridge/{ob.name}: plate texels {float((wm > 0.5).mean()):.3f} of the texture, x{k}")
        return


def generated_chair(src):
    """The captain's chair made by image-to-3D (bridge-redesign.md 8c), from
    build.sh's cache: already turned, scaled to the stand-in's seat and arms
    and its pedestal in `trim` (the pilot's Blender pass, kept with the glb in
    the media store). Decimated to the hero budget and baked from the original
    into the bridge's atlas, as a pack's props are. Returns the prop, its
    {low: original} and the licence files."""
    lic = C.pack_licences(src)
    lows, sources = C.import_pack(src, "bridge", budgets={"captain_chair": 6000})
    lo = lows[0]
    hi = sources[lo]
    # import_pack set it on the footprint's middle, which the back makes
    # deeper behind than in front: the pedestal's axis back on the origin,
    # where the stand-in's is (the mean of the foot's ring of vertices),
    # both copies alike so the bake's rays still meet
    foot = [v.co for v in lo.data.vertices if v.co.z < 0.01]
    dx, dy = sum(v.x for v in foot) / len(foot), sum(v.y for v in foot) / len(foot)
    for o in (lo, hi):
        for v in o.data.vertices:
            v.co.x -= dx
            v.co.y -= dy
    pull_leather(hi)
    pull_plate(hi)
    return lo, sources, lic


out, args = C.out_dir()
C.clean_scene()
# build.sh passes the generated chair's folder when it has it; without it
# (the public repo, a box without the NAS) the scripted chair, as before
if args:
    chair, sources, lic = generated_chair(args[0])
else:
    sources, lic = None, None
    chair = captain_chair()
    # The origin is already where the stand-in's is (the floor, under the
    # pedestal's axis): floor_origin would centre it on the footprint, which
    # the back makes deeper behind than in front, and the seat would move off
    # the stand-in's. Transforms applied all the same.
    C.activate(chair)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
props = [chair, conn_console(), tactical_rail(), station(), conn_chair(), armrest_console(), screen_fin(),
         station("station_long", 2.6), display_bezel()]
for p in props[1:]:
    C.activate(p)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # the end caps of prisms, lofts and sweeps are ngons, and the exporter's
    # tangents (MikkTSpace) take only triangles and quads
    bm = bmesh.new()
    bm.from_mesh(p.data)
    bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
    bm.to_mesh(p.data)
    bm.free()
C.finish_room("bridge", props, size=1024, sources=sources)
if lic:
    C.write_licences(lic, os.path.join(out, "bridge.LICENSE.txt"))
