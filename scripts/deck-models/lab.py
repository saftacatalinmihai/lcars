"""The labs' props (docs/design/deck-style.md part 2, "Labs"):
lcars-ui/deck/lab.glb: the work bench, the specimen case, the hologram
table, the microscope station and the sample rack.

    blender -b --factory-startup -P scripts/deck-models/lab.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported), built to its stand-in in deck.html, whose origin it
keeps:
- `work_bench`, over `bench2(x, z, rot, w, seed)` at w 2.4, d 0.75 (the
  page stretches it across to the bench's own w): a light grey body with a
  rounded front over a kick recess, and an inset black top tilted 0.25
  (rising away from whoever works it), 4 mm under the stand-in's display
  (0.915 high at z 0.02 of the page), which is kept; the stand-in's amber
  strip stays at the foot of the front (y 0.1, z 0.377);
- `specimen_case`, over the lab builder's case: a base to 0.9 with a dark
  kick, four posts round the stand-in's glass (0.86 x 0.56, 0.9 to 1.5,
  the shared M.glass, kept), a shelf with vials, a stand for the lit sample
  (y 1.03, kept), and a cap whose underside the stand-in's light strip
  (y 1.495) lights;
- `holo_table`, over the hologram table's pedestal: a flared pedestal, a
  ring rim and the black well the stand-in's emitter disc (r 0.62 at 0.856,
  kept) lies in.
- `microscope_station`, over `microscopeStation()`: a bench 1.2 x 0.6 to
  0.9 against a wall (its back the page's local -z), a black top, and on
  it a microscope (foot, arm, stage, turret, binocular head) toward the
  worker at +z, at the bench's -X half;
- `sample_rack`, dressing over no stand-in: a stepped rack of ten
  sample tubes, 0.24 x 0.1, its origin under its middle (at most 200
  triangles: no bevels).
- `lab_padd_shelf`, over the lab's `padShelf()`: common.py's rack in the
  lab's grey, dressed as a working shelf: binders, PADDs, a rack of tubes,
  instrument cases.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401
from mathutils import Matrix  # noqa: E402

import common as C  # noqa: E402

# the bench top's black (deck-style part 1, "Labs")
C.PALETTE["lab_top"] = (0x2a2a2e, 0.35, 0.2, None)

TILT = 0.25


def top(z):
    """The stand-in display's height over the page's local z."""
    return 0.915 + (0.02 - z) * math.tan(TILT)


def work_bench():
    """A grey body (rounded front, the kick set back under it), the black
    top laid in it between grey cheeks and a rear lip."""
    # the body's section in the page's (z, y), toward the worker at +z
    sec = [(-0.375, 0.1), (-0.375, top(-0.375) - 0.034), (0.29, top(0.29) - 0.034), (0.29, 0.862), (0.335, 0.862),
           (0.36, 0.835), (0.37, 0.76), (0.376, 0.6), (0.377, 0.4), (0.375, 0.22), (0.37, 0.13), (0.35, 0.1)]
    parts = [C.prism("body", [(-z, y) for z, y in sec], -1.2, 1.2, "lab_grey", bevel=0.01),
             C.box("kick", (2.3, 0.63, 0.1), (0, 0.015, 0.05), "console", bevel=0.006, segments=1)]
    # the top's own frame: the display's middle, tilted with it
    tp = [C.box("slab", (2.3, 0.62, 0.03), (0, 0, -0.019), "lab_top", bevel=0.004, segments=1),
          C.box("lip", (2.4, 0.05, 0.05), (0, 0.33, 0.0), "lab_grey", bevel=0.012, segments=2)]
    for sx in (-1, 1):
        tp.append(C.box(f"cheek{sx}", (0.05, 0.66, 0.05), (sx * 1.175, 0.0, 0.0), "lab_grey", bevel=0.012, segments=2))
    C.placed(tp, Matrix.Translation((0, -0.02, 0.915)) @ Matrix.Rotation(TILT, 4, "X"))
    parts += tp
    return C.smooth(C.join("work_bench", parts), 35)


def specimen_case():
    """A grey base on a dark kick, the posts at the glass's corners, a
    shelf of vials, the sample's stand and the cap."""
    parts = [C.box("kick", (0.84, 0.54, 0.06), (0, 0, 0.03), "console"),
             C.box("base", (0.9, 0.6, 0.84), (0, 0, 0.48), "lab_grey", bevel=0.02, segments=2),
             C.box("label", (0.32, 0.006, 0.08), (0, -0.301, 0.74), "lab_top"),
             C.box("deck", (0.86, 0.56, 0.01), (0, 0, 0.905), "lab_top"),
             C.lathe("stand", [(0.001, 0.9), (0.07, 0.9), (0.06, 0.95), (0.001, 0.95)], "trim", steps=16),
             C.box("shelf", (0.84, 0.3, 0.012), (0, 0.12, 1.26), "lab_grey"),
             C.box("cap", (0.94, 0.64, 0.06), (0, 0, 1.53), "lab_grey", bevel=0.015, segments=2)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(C.box(f"post{sx}{sy}", (0.025, 0.025, 0.6), (sx * 0.4425, sy * 0.2925, 1.2), "trim", bevel=0.004, segments=1))
    for i, x in enumerate((-0.28, -0.2, -0.12, 0.14, 0.22)):
        parts.append(C.lathe(f"vial{i}", [(0.001, 1.266), (0.018, 1.266), (0.018, 1.36), (0.012, 1.37), (0.001, 1.37)],
                             "lab_top" if i % 2 else "trim", steps=8, at=(x, 0.14, 0)))
    return C.smooth(C.join("specimen_case", parts), 35)


def holo_table():
    """A pedestal flaring at the floor and under the top, a ring rim and the
    black well the emitter lies in."""
    parts = [C.lathe("ped", [(0.001, 0), (0.8, 0), (0.8, 0.03), (0.7, 0.08), (0.52, 0.2), (0.43, 0.35), (0.43, 0.55),
                             (0.5, 0.67), (0.62, 0.76), (0.66, 0.8), (0.001, 0.8)], "lab_grey", steps=32),
             C.lathe("band", [(0.435, 0.42), (0.435, 0.48)], "lab_top", steps=32),
             C.lathe("rim", [(0.62, 0.8), (0.76, 0.8), (0.772, 0.84), (0.76, 0.876), (0.72, 0.886), (0.645, 0.882),
                             (0.625, 0.862), (0.62, 0.8)], "trim", steps=32),
             C.lathe("well", [(0.001, 0.85), (0.63, 0.85), (0.63, 0.8)], "lab_top", steps=32)]
    return C.smooth(C.join("holo_table", parts), 35)


def microscope_station():
    """A grey bench with a dark kick and a black top; the microscope on it."""
    parts = [C.box("body", (1.2, 0.56, 0.84), (0, 0.02, 0.45), "lab_grey", bevel=0.015, segments=2),
             C.box("kick", (1.14, 0.5, 0.06), (0, 0.04, 0.03), "console"),
             C.box("top", (1.24, 0.62, 0.04), (0, 0, 0.88), "lab_top", bevel=0.008, segments=1),
             C.box("drawer", (0.5, 0.006, 0.16), (0.3, -0.262, 0.7), "lab_top")]
    # the microscope, at x -0.25, the eyepieces toward the worker (-Y)
    mx, my, z0 = -0.25, 0.02, 0.9
    parts += [C.box("foot", (0.2, 0.26, 0.04), (mx, my, z0 + 0.02), "lab_grey", bevel=0.01, segments=1),
              C.box("arm", (0.07, 0.07, 0.34), (mx, my + 0.1, z0 + 0.21), "lab_grey", bevel=0.015, segments=1),
              C.box("stage", (0.16, 0.14, 0.015), (mx, my - 0.02, z0 + 0.13), "lab_top"),
              C.box("head", (0.08, 0.16, 0.07), (mx, my + 0.02, z0 + 0.39), "lab_grey", bevel=0.015, segments=1),
              C.lathe("turret", [(0.001, z0 + 0.3), (0.04, z0 + 0.3), (0.045, z0 + 0.34), (0.001, z0 + 0.34)], "trim", steps=12, at=(mx, my - 0.02, 0)),
              C.lathe("lens", [(0.012, z0 + 0.21), (0.012, z0 + 0.3)], "lab_top", steps=8, at=(mx, my - 0.02, 0)),
              C.lathe("knob", [(0.03, -0.015), (0.03, 0.015)], "trim", steps=12, at=(0, 0, 0))]
    knob = parts[-1]
    knob.rotation_euler.y = math.pi / 2
    knob.location = (mx, my + 0.1, z0 + 0.12)
    for sx in (-1, 1):
        ep = C.lathe(f"eye{sx}", [(0.001, 0), (0.014, 0), (0.014, 0.1), (0.017, 0.1), (0.017, 0.13), (0.001, 0.13)], "lab_top", steps=10)
        ep.rotation_euler.x = math.radians(35)
        ep.location = (mx + sx * 0.025, my - 0.05, z0 + 0.4)
        parts.append(ep)
    return C.smooth(C.join("microscope_station", parts), 35)


def sample_rack():
    """Dressing: a two-step rack of tubes, capped in two colours."""
    parts = [C.box("base", (0.24, 0.1, 0.012), (0, 0, 0.006), "lab_grey"),
             C.box("step", (0.24, 0.012, 0.07), (0, 0.0, 0.047), "lab_grey")]
    for row, y in enumerate((-0.025, 0.025)):
        for i in range(5):
            x = -0.096 + i * 0.048
            parts.append(C.lathe(f"tube{row}{i}", [(0.009, 0.012), (0.009, 0.11 - row * 0.01), (0.001, 0.11 - row * 0.01)],
                                 "trim" if (i + row) % 2 else "lab_top", steps=4, at=(x, y, 0)))
    return C.join("sample_rack", parts)


def lab_shelf():
    """Binders in the room's colours, PADDs leaning and a stack lying, a
    rack of tubes (the sample rack's, three to a row, no step) and two
    instrument cases on the bottom board."""
    parts = []
    for i, x in enumerate((-0.4, 0.22)):
        parts.append(C.shelf_book(f"lc{i}", x, 0, 0.26, 0.16, 0.42, "lab_top" if i else "lab_grey", lying=True))
        parts.append(C.box(f"lch{i}", (0.12, 0.012, 0.012), (x, -0.136, C.BOARDS[0] + 0.015 + 0.11), "trim"))
    for i, (dx, m) in enumerate(((0, "lab_top"), (0.06, "bed_pad"), (0.12, "lab_top"), (0.18, "trim"))):
        parts.append(C.shelf_book(f"lb{i}", 0.3 + dx, 1, 0.3, 0.055, 0.24, m))
    parts.append(C.shelf_book("lbl", 0.53, 1, 0.28, 0.05, 0.22, "bed_pad", lean=0.3))
    parts += C.shelf_padd("lp0", -0.5, 1) + C.shelf_padd("lp1", -0.34, 1, lean=0.4)
    z0 = C.BOARDS[2] + 0.015
    parts.append(C.box("ltr", (0.2, 0.08, 0.012), (-0.45, -0.02, z0 + 0.006), "lab_grey"))
    for i in range(3):
        for row, y in enumerate((-0.04, 0.0)):
            parts.append(C.lathe(f"lt{i}{row}", [(0.009, 0.012), (0.009, 0.11), (0.001, 0.11)], "trim" if (i + row) % 2 else "lab_top",
                                 steps=4, at=(-0.5 + i * 0.05, y, z0)))
    for i in range(3):
        parts += C.shelf_padd(f"ls{i}", 0.4, 3, flat_z=i * 0.013, turn=0.08 * (i - 1))
    parts += C.shelf_padd("lp2", -0.45, 4, lean=0.3)
    return C.padd_shelf("lab_padd_shelf", parts, side="lab_grey", back="lab_top", board="lab_grey")


C.clean_scene()
props = C.finish_props([work_bench(), specimen_case(), holo_table(), microscope_station(), sample_rack(), lab_shelf()])
C.finish_room("lab", props, size=1024)
