"""Sickbay's props (docs/design/deck-style.md part 2, "Sickbay"):
lcars-ui/deck/sickbay.glb: the biobed, the surgical bed and its clamshell
arch, the instrument tray on its post, the wall cabinet, the hypospray
rack and the doctor's office desk.

    blender -b --factory-startup -P scripts/deck-models/sickbay.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported). Each is built to its stand-in in deck.html, whose origin
it keeps (the floor under the middle of the bed):
- `biobed`, over `biobed()`: the head end at +Y (the page's local -z,
  against the wall), the pad's top at 0.75, and the head display on an arm
  over the pillow - the stand-in's screen (0.6 x 0.34, its own texture) is
  kept, 3 cm in front of the middle of a housing at (0, 0.86, 1.38) tilted
  0.3 toward the foot, and the housing is built round it;
- `surgical_bed`, over `surgicalBed()`: the bed on a pedestal, its pad's top
  at 0.88, and over the chest (Y +0.15) the clamshell arch, 0.66 round
  about (0, 0.9), hinged on its +X side; the stand-in's lit panel (y 1.48,
  0.36 x 0.3) stays under the arch's crown;
- `instrument_tray`, over `instrumentTray()`: a tray at 0.97 on a post,
  dressing (at most 200 triangles: no bevels).
- `wall_cabinet`, over `cabinet()` at 1.4 x 2.0 (0.55 deep, its doors at
  the page's local +z): two doors with a dark window in each upper half,
  a 4 cm slot between them where the stand-in's blue strip (y 0.3-1.7,
  z 0.28) is kept, handles beside it, a dark kick under them;
- `hypospray_rack`, on the wall over no stand-in: its origin the plate's
  back at its middle, four hyposprays in clips and a vial shelf under
  them; dressing (at most 200 triangles);
- `office_desk`, over the office's `officeDesk()`: a top 1.4 x 0.7 at
  0.775 on a pedestal of drawers (+X) and an end panel (-X), a modesty
  panel at the back (the page's local -z), a slim terminal on it;
- `sick_padd_shelf`, over sickbay's `padShelf()`: common.py's rack in the
  shell's white, dressed as a ward's: folded blankets, medkits, PADDs, a
  tray of vials.
The shell is the palette's sick_white (#e8e6e0, roughness 0.35: a slightly
glossy plastic), the pads bed_pad (#7a8ea0), all baked in the one atlas.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bmesh  # noqa: E402
import bpy  # noqa: E402
from mathutils import Matrix  # noqa: E402

import common as C  # noqa: E402


def biobed():
    """A curved base on a dark kick, a shell tray, the soft blue pad and a
    pillow, and at the head an arm up to the display's housing."""
    parts = [
        C.loft("kick", [(0.0, 0.54, 1.62, 0), (0.07, 0.54, 1.62, 0)], "black", r=0.12),
        # the base swells from its kick to the tray: narrow at the floor,
        # rounded out under the bed, as the TNG beds are
        C.loft("base", [(0.06, 0.6, 1.7, 0), (0.18, 0.63, 1.75, 0), (0.33, 0.7, 1.84, 0), (0.46, 0.8, 1.93, 0),
                        (0.56, 0.87, 1.98, 0), (0.61, 0.9, 2.0, 0)], "sick_white", r=0.16),
        C.box("tray", (0.92, 2.02, 0.04), (0, 0, 0.62), "sick_white", bevel=0.015, segments=2),
        C.pad("pad", (0.82, 1.9, 0.1), (0, 0, 0.7), "bed_pad"),
        C.box("pillow", (0.56, 0.32, 0.06), (0, 0.72, 0.775), "bed_pad", bevel=0.025, segments=2),
        C.box("post", (0.07, 0.07, 0.74), (0, 0.97, 0.98), "sick_white", bevel=0.02, segments=1),
        C.box("elbow", (0.06, 0.12, 0.06), (0, 0.92, 1.33), "sick_white"),
    ]
    # the housing, in its own frame (the stand-in's display group): the
    # screen lies at Y -0.03, in front of a black bezel and inside a rim
    hs = [C.box("shell", (0.72, 0.06, 0.46), (0, 0.01, 0), "sick_white", bevel=0.015, segments=2),
          C.box("bezel", (0.64, 0.006, 0.38), (0, -0.021, 0), "black"),
          C.box("rimT", (0.72, 0.03, 0.04), (0, -0.035, 0.21), "sick_white"),
          C.box("rimB", (0.72, 0.03, 0.04), (0, -0.035, -0.21), "sick_white")]
    for sx in (-1, 1):
        hs.append(C.box(f"rim{sx}", (0.04, 0.03, 0.38), (sx * 0.34, -0.035, 0), "sick_white"))
    C.placed(hs, Matrix.Translation((0, 0.86, 1.38)) @ Matrix.Rotation(0.3, 4, "X"))
    parts += hs
    return C.smooth(C.join("biobed", parts), 35)


def arc(name, R, r0, r1, y0, y1, a0, a1, steps, material, cz=0.9):
    """A band of a ring about the Y axis through (0, cz): radii R + r0 to
    R + r1, from Y y0 to y1, angles a0 to a1 from +X up over the top."""
    bm = bmesh.new()
    rings = []
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        c, s = math.cos(a), math.sin(a)
        rings.append([bm.verts.new(((R + dr) * c, y, cz + (R + dr) * s)) for dr, y in ((r0, y0), (r1, y0), (r1, y1), (r0, y1))])
    for p, q in zip(rings, rings[1:]):
        for k in range(4):
            k1 = (k + 1) % 4
            bm.faces.new((p[k], p[k1], q[k1], q[k]))
    bm.faces.new(rings[0])
    bm.faces.new(rings[-1][::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return C.mesh_of(name, bm, material)


def surgical_bed():
    """The bed on its pedestal, rails along its sides, and the clamshell:
    a broad shell over the chest with a trim band at each edge, a dark
    sensor strip inside its crown, hinged on a barrel along the +X rail and
    latched on the -X."""
    parts = [
        C.box("plate", (0.9, 1.5, 0.06), (0, 0, 0.03), "sick_white", bevel=0.02, segments=2),
        C.loft("ped", [(0.06, 0.6, 1.0, 0), (0.12, 0.52, 0.92, 0), (0.3, 0.46, 0.84, 0), (0.5, 0.52, 0.92, 0),
                       (0.62, 0.7, 1.3, 0), (0.7, 0.86, 1.8, 0)], "sick_white", r=0.14),
        C.box("tray", (1.0, 2.1, 0.1), (0, 0, 0.75), "sick_white", bevel=0.03, segments=3),
        C.box("band", (1.02, 2.12, 0.02), (0, 0, 0.705), "trim", bevel=0.008, segments=1),
        C.pad("pad", (0.9, 2.0, 0.08), (0, 0, 0.84), "bed_pad"),
        C.pad("pillow", (0.56, 0.32, 0.06), (0, 0.78, 0.9), "bed_pad"),
    ]
    for sx in (-1, 1):
        # the rails the shell stands on, past the tray's sides
        parts.append(C.box(f"rail{sx}", (0.16, 0.92, 0.1), (sx * 0.62, 0.15, 0.83), "sick_white", bevel=0.025, segments=2))
    # the shell: Y -0.2 to 0.5, 6 cm thick about R 0.66, its edges banded
    shell = arc("shell", 0.66, -0.03, 0.03, -0.2, 0.5, 0, math.pi, 32, "sick_white")
    C.modifier(shell, "BEVEL", width=0.012, segments=2, limit_method="ANGLE")
    parts.append(shell)
    for y0, y1 in ((-0.215, -0.19), (0.49, 0.515)):
        parts.append(arc(f"edge{y0}", 0.66, -0.036, 0.036, y0, y1, 0, math.pi, 32, "trim"))
    parts.append(arc("sensor", 0.66, -0.036, -0.029, -0.02, 0.32, math.radians(62), math.radians(118), 6, "black"))
    # the hinge: a barrel along the +X rail with a knuckle at each end; the
    # latch on the -X
    parts.append(C.lathe("barrel", [(0.001, 0), (0.045, 0), (0.045, 0.74), (0.001, 0.74)], "trim", steps=16))
    parts[-1].rotation_euler.x = -math.pi / 2
    parts[-1].location = (0.7, -0.22, 0.92)
    for y in (-0.24, 0.54):
        parts.append(C.box(f"knuckle{y}", (0.12, 0.06, 0.14), (0.7, y, 0.9), "sick_white", bevel=0.02, segments=2))
    parts.append(C.box("latch", (0.1, 0.3, 0.07), (-0.7, 0.15, 0.905), "sick_white", bevel=0.02, segments=2))
    return C.smooth(C.join("surgical_bed", parts), 35)


def instrument_tray():
    """Dressing: a foot, a post, a rimmed tray with two instruments and a
    hypospray in its holder. No bevels: 200 triangles is the budget."""
    parts = [C.lathe("foot", [(0.001, 0), (0.18, 0), (0.16, 0.04), (0.001, 0.04)], "sick_white", steps=8),
             C.lathe("post", [(0.025, 0.04), (0.025, 0.95)], "trim", steps=8),
             C.box("tray", (0.5, 0.35, 0.02), (0, 0, 0.96), "sick_white")]
    for sy in (-1, 1):
        parts.append(C.box(f"lip{sy}", (0.5, 0.012, 0.03), (0, sy * 0.169, 0.985), "sick_white"))
    for sx in (-1, 1):
        parts.append(C.box(f"end{sx}", (0.012, 0.326, 0.03), (sx * 0.244, 0, 0.985), "sick_white"))
    for i, x in enumerate((-0.12, 0.0)):
        parts.append(C.box(f"tool{i}", (0.02, 0.14, 0.01), (x, -0.02, 0.975), "trim"))
    parts.append(C.box("holder", (0.1, 0.05, 0.04), (0.15, 0.08, 0.99), "black"))
    parts.append(C.lathe("hypo", [(0.001, 0.97), (0.014, 0.97), (0.014, 1.08), (0.001, 1.09)], "trim", steps=6, at=(0.15, 0.08, 0)))
    return C.join("instrument_tray", parts)


def wall_cabinet():
    """The carcass, two doors either side of the lit slot, dark windows in
    their upper halves, handles, a kick and a cap."""
    parts = [C.box("carcass", (1.4, 0.53, 1.9), (0, 0.01, 1.03), "sick_white", bevel=0.02, segments=2),
             C.box("kick", (1.34, 0.49, 0.08), (0, 0.03, 0.04), "black"),
             C.box("cap", (1.42, 0.56, 0.04), (0, 0.0, 1.98), "sick_white", bevel=0.012, segments=2),
             C.box("slot", (0.04, 0.012, 1.84), (0, -0.258, 1.03), "black")]
    for sx in (-1, 1):
        x = sx * 0.355
        parts += [C.box(f"door{sx}", (0.66, 0.02, 1.84), (x, -0.265, 1.03), "sick_white", bevel=0.008, segments=1),
                  C.box(f"window{sx}", (0.5, 0.004, 0.62), (x, -0.276, 1.5), "black"),
                  C.box(f"handle{sx}", (0.02, 0.02, 0.32), (sx * 0.075, -0.286, 1.0), "trim", bevel=0.005, segments=1)]
    return C.smooth(C.join("wall_cabinet", parts), 35)


def hypospray_rack():
    """Dressing: a plate on the wall, four hyposprays in a row of clips
    and a shelf of vials under them. No bevels."""
    parts = [C.box("plate", (0.42, 0.02, 0.28), (0, -0.01, 0), "sick_white"),
             C.box("clips", (0.36, 0.03, 0.03), (0, -0.035, 0.03), "black"),
             C.box("shelf", (0.36, 0.06, 0.012), (0, -0.05, -0.09), "trim")]
    for i, x in enumerate((-0.12, -0.04, 0.04, 0.12)):
        parts.append(C.lathe(f"hypo{i}", [(0.012, -0.02), (0.012, 0.09), (0.006, 0.11), (0.001, 0.11)],
                             "trim" if i % 2 else "sick_white", steps=5, at=(x, -0.04, 0)))
    for i, x in enumerate((-0.1, 0.0, 0.1)):
        parts.append(C.box(f"vial{i}", (0.03, 0.03, 0.06), (x, -0.05, -0.054), "bed_pad"))
    return C.join("hypospray_rack", parts)


def office_desk():
    """A white desk: the top, a drawer pedestal on +X, an end panel on -X,
    the modesty panel at the back, a slim terminal."""
    parts = [C.box("top", (1.4, 0.7, 0.04), (0, 0, 0.755), "sick_white", bevel=0.012, segments=2),
             C.box("ped", (0.42, 0.62, 0.72), (0.47, 0.0, 0.375), "sick_white", bevel=0.01, segments=1),
             C.box("end", (0.04, 0.62, 0.72), (-0.66, 0.0, 0.375), "sick_white", bevel=0.008, segments=1),
             C.box("modesty", (0.9, 0.02, 0.5), (-0.2, 0.3, 0.47), "sick_white"),
             C.box("band", (1.42, 0.72, 0.012), (0, 0, 0.729), "trim"),
             # the terminal at the back, its face toward the sitter (-Y)
             C.box("foot", (0.2, 0.12, 0.012), (-0.2, 0.18, 0.781), "trim"),
             C.box("neck", (0.04, 0.03, 0.14), (-0.2, 0.2, 0.85), "trim"),
             C.box("screen", (0.5, 0.025, 0.3), (-0.2, 0.18, 1.05), "sick_white", bevel=0.008, segments=1),
             C.box("face", (0.46, 0.004, 0.26), (-0.2, 0.166, 1.05), "black")]
    for i in range(3):
        parts.append(C.box(f"drawer{i}", (0.38, 0.006, 0.2), (0.47, -0.312, 0.62 - i * 0.23), "sick_white"))
        parts.append(C.box(f"pull{i}", (0.14, 0.012, 0.012), (0.47, -0.318, 0.69 - i * 0.23), "trim"))
    return C.smooth(C.join("office_desk", parts), 35)


C.PALETTE["med_red"] = (0x9a2a26, 0.5, 0.0, None)


def sick_shelf():
    """Blankets folded on the bottom board, two medkits (a white case with
    a red cross on its lid), PADDs leaning and lying, a tray of vials."""
    parts = []
    for i in range(3):
        b = C.shelf_book(f"sb{i}", 0.3, 0, 0.3, 0.07, 0.42, "bed_pad", lying=True)
        b.location.z += i * 0.07
        parts.append(b)
    for i, x in enumerate((-0.45, -0.1)):
        z0 = C.BOARDS[1] + 0.015
        parts.append(C.box(f"mk{i}", (0.3, 0.22, 0.12), (x, 0.0, z0 + 0.06), "sick_white", bevel=0.01, segments=1))
        parts.append(C.box(f"mkx{i}", (0.1, 0.03, 0.004), (x, 0.0, z0 + 0.122), "med_red"))
        parts.append(C.box(f"mky{i}", (0.03, 0.1, 0.004), (x, 0.0, z0 + 0.122), "med_red"))
    parts += C.shelf_padd("sp0", 0.45, 2) + C.shelf_padd("sp1", 0.29, 2, lean=0.4)
    z0 = C.BOARDS[3] + 0.015
    parts.append(C.box("vt", (0.26, 0.12, 0.012), (-0.4, -0.02, z0 + 0.006), "trim"))
    for i in range(5):
        parts.append(C.lathe(f"v{i}", [(0.014, 0.012), (0.014, 0.07), (0.008, 0.08), (0.001, 0.08)], "bed_pad" if i % 2 else "sick_white",
                             steps=5, at=(-0.5 + i * 0.05, -0.02, z0)))
    for i in range(3):
        parts += C.shelf_padd(f"ss{i}", 0.4, 4, flat_z=i * 0.013, turn=0.08 * (i - 1))
    return C.padd_shelf("sick_padd_shelf", parts, side="sick_white", back="lab_grey", board="sick_white", plinth="trim")


C.clean_scene()
props = C.finish_props([biobed(), surgical_bed(), instrument_tray(), wall_cabinet(), hypospray_rack(), office_desk(), sick_shelf()])
C.finish_room("sickbay", props, size=1024)
