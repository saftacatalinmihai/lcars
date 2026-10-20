"""The bridge's props (docs/design/deck-style.md part 2, "Bridge"):
lcars-ui/deck/bridge.glb: the captain's chair (the pipeline's first prop),
the conn and ops console, the tactical rail and the standing station; the
conn's and ops' own chair and the command chairs' armrest consoles
(0.237.0).

    blender -b --factory-startup -P scripts/deck-models/bridge.py -- OUT_DIR

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
- `station`, over the six standing stations round the wall (1.8 wide,
  0.45 deep, the display at y 0.905 in a top tilted 0.4).
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402

import common as C  # noqa: E402


def back_shell(name):
    """The shell the back's cushions sit in: a sheet curved round the
    sitter (its sides come forward), thickened and bevelled, rising to a
    rounded top that is the headrest's."""
    bm = bmesh.new()
    nx, nz, W, Z0, Z1 = 10, 9, 0.68, 0.5, 1.27
    rows = []
    for j in range(nz + 1):
        z = Z0 + (Z1 - Z0) * j / nz
        # narrower toward the top: the headrest's shoulders
        w = W * (1 - 0.3 * max(0, (z - 1.05) / (Z1 - 1.05)) ** 1.5)
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
    ob.data.materials.append(C.mat("console"))
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
            C.pad("upper", (0.54, 0.12, 0.28), (0, 0.27, 1.0), "bridge_leather"),
            C.pad("head", (0.38, 0.11, 0.13), (0, 0.27, 1.19), "bridge_leather"),
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
    # z 0.31, where the lights are; far face at -0.27)
    parts.append(loft("ped", [(0.0, 1.46, 0.72, -0.02), (0.02, 1.45, 0.71, -0.02), (0.05, 1.4, 0.66, -0.02),
                              (0.1, 1.34, 0.61, -0.02), (0.17, 1.3, 0.58, -0.02)], "console", r=0.06))
    parts.append(prism("body", [(0.27, 0.16), (-0.31, 0.16), (-0.31, under(0.31)), (0.27, under(-0.27))],
                       -0.65, 0.65, "console", bevel=0.02))
    # a brushed band where the body meets the pedestal
    parts.append(C.box("band", (1.32, 0.6, 0.03), (0, -0.02, 0.175), "trim", bevel=0.008, segments=2))
    # the top, in its own frame: Blender (x, -u, v), then tilted and raised
    top = [C.box("slab", (1.6, 0.8, 0.03), (0, -0.04, -0.01), "console", bevel=0.012, segments=3),
           C.box("far", (1.6, 0.09, 0.03), (0, 0.315, 0.012), "console", bevel=0.008, segments=2),
           C.box("near", (1.56, 0.04, 0.03), (0, -0.29, 0.012), "console", bevel=0.006, segments=2),
           C.pad("lip", (1.56, 0.14, 0.055), (0, -0.37, 0.022), "bridge_leather"),
           C.box("well", (1.44, 0.54, 0.016), (0, 0, 0.0), "black", bevel=0.002, segments=1)]
    for sx in (-1, 1):
        top.append(C.box(f"cheek{sx}", (0.08, 0.6, 0.03), (sx * 0.76, 0.0, 0.012), "console", bevel=0.008, segments=2))
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
    back = [C.box("shell", (0.5, 0.05, 0.62), (0, 0.33, 0.83), "console", bevel=0.018, segments=2),
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
        half = [(0.06, 0.975), (0.1, 0.995), (0.118, 1.03), (0.116, 1.075), (0.095, 1.11), (0.05, 1.133)]
        return ([(-dr * s, z) for dr, z in half] + [(0, 1.14)] + [(dr * s, z) for dr, z in reversed(half)])

    steps = 44
    parts = [sweep("cap", cap, 0, ARC, TR, steps, "rail_wood")]
    # the panel between the posts, set back under the cap, and the kick
    parts.append(sweep("panel", lambda a: [(-0.035, 0.1), (0.035, 0.1), (0.035, 0.98), (-0.035, 0.98)], 0.012, ARC - 0.012, TR, 16, "wainscot"))
    parts.append(sweep("kick", lambda a: [(-0.025, 0.0), (0.025, 0.0), (0.025, 0.1), (-0.025, 0.1)], 0.012, ARC - 0.012, TR, 16, "black"))
    for i in range(6):
        a = ARC * i / 5
        a = min(max(a, 0.015), ARC - 0.015)
        p = C.box(f"post{i}", (0.1, 0.13, 0.98), (TR * math.sin(a), -TR * math.cos(a), 0.49), "console", bevel=0.015, segments=2)
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


def station():
    """A standing station: a body with a sloped top that holds the display
    (the stand-in's plane) in a bezel, end panels standing off it at a dark
    seam, a recessed kick plate and the lit slot above it (the stand-in's
    glow strip, at y 0.1 on the near face)."""
    from mathutils import Matrix
    th = 0.4
    # the underside of the stand-in's slab, centred at (0.881, z 0.01)
    def under(z, v=-0.018):
        u = (z - 0.01 - v * math.sin(th)) / math.cos(th)
        return 0.881 + v * math.cos(th) - u * math.sin(th)
    parts = [prism("body", [(-0.225, 0.13), (0.215, 0.13), (0.215, under(-0.215)), (-0.225, under(0.225))],
                   -0.8, 0.8, "console", bevel=0.01),
             C.box("slot", (1.6, 0.4, 0.06), (0, 0.0, 0.105), "black"),
             C.box("kick", (1.62, 0.39, 0.08), (0, 0.01, 0.04), "trim", bevel=0.006, segments=1)]
    for sx in (-1, 1):
        parts.append(prism(f"end{sx}", [(-0.235, 0.0), (0.235, 0.0), (0.235, under(-0.235) + 0.01), (-0.235, under(0.235) + 0.01)],
                           sx * 0.81, sx * 0.9, "trim", bevel=0.012))
        parts.append(C.box(f"seam{sx}", (0.012, 0.44, under(0) - 0.02), (sx * 0.805, 0, (under(0) - 0.02) / 2), "black"))
    top = [C.box("slab", (1.62, 0.5, 0.03), (0, 0, 0.0), "console", bevel=0.01, segments=2),
           C.box("well", (1.72, 0.42, 0.012), (0, 0, 0.018), "black")]
    for sy, d in ((-1, 0.04), (1, 0.04)):
        top.append(C.box(f"lip{sy}", (1.84, d, 0.026), (0, sy * 0.23, 0.026), "console", bevel=0.008, segments=2))
    for sx in (-1, 1):
        top.append(C.box(f"cheek{sx}", (0.06, 0.5, 0.026), (sx * 0.89, 0, 0.026), "console", bevel=0.008, segments=2))
    # the slab's frame: Blender (x, -u, v) about its middle, as the stand-in's
    placed(top, Matrix.Translation((0, -0.01, 0.881)) @ Matrix.Rotation(th, 4, "X"))
    parts += top
    return C.smooth(C.join("station", parts), 35)


C.clean_scene()
chair = captain_chair()
# The origin is already where the stand-in's is (the floor, under the
# pedestal's axis): floor_origin would centre it on the footprint, which the
# back makes deeper behind than in front, and the seat would move off the
# stand-in's. Transforms applied all the same.
C.activate(chair)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
props = [chair, conn_console(), tactical_rail(), station(), conn_chair(), armrest_console()]
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
C.finish_room("bridge", props, size=1024)
