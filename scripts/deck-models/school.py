"""The generated classrooms' props (docs/design/deck-remodel.md, slice 7):
lcars-ui/deck/school.glb, one atlas every classroom shares - the pupils'
desks (three tops, the page's three cushion colours and wood, as the
stand-ins pick per desk), their stools, and the frame of the big screen.

    blender -b --factory-startup -P scripts/deck-models/school.py -- OUT_DIR

Built to the stand-ins in deck.html's `school` builder, whose origins they
keep (the floor under the footprint's middle), front toward -Y here
(glTF's +Z):
- `school_desk_a`, `_b`, `_c`, `_w` over a desk: its top 0.9 x 0.55 from
  0.58 to 0.62, one post; here a laminate top in the colour with a
  brushed edge, a dark inset slate at its middle, a book tray under it, a
  post on a round foot. A classroom has up to ~25 desks, so ~300
  triangles each;
- `school_stool`, over the shared stool (0.17 across at the top, 0.42
  high): a cushion on a pan, a stem, a foot, twelve-sided
  (at eight its facets showed at a desk's distance), ~200 triangles;
- `school_screen`, over `screen(3, 1.4)`'s frame, the display (the room's
  panel, the stand-in's) kept over it at Y 0 and 1.7 up: a bezel behind it
  with a rim round its face, a ledge under it, two LCARS caps beside it.
Budgets (deck-remodel.md, slices 5 and 7): at most 15 k triangles a room.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401

import common as C  # noqa: E402

# the page's cushion colours (M.pillowA, B, C) and its wood, as laminates
C.PALETTE["desk_amber"] = (0xc89a3a, 0.5, 0.0, None)
C.PALETTE["desk_teal"] = (0x3a7a78, 0.5, 0.0, None)
C.PALETTE["desk_rust"] = (0xa8543c, 0.5, 0.0, None)
C.PALETTE["desk_wood2"] = (0x6a4630, 0.45, 0.0, "grain")
C.PALETTE["stool_fabric"] = (0x544a66, 0.85, 0.0, "weave")
C.PALETTE["lcars_peach"] = (0xff9966, 0.5, 0.0, None)


def school_desk(tag, top):
    parts = [C.loft("top", [(0.585, 0.88, 0.53, 0), (0.62, 0.88, 0.53, 0)], top, r=0.04, k=2),
             # the edge a brushed rim round the top, its own top under the
             # laminate's (capped over it, it hid the colour)
             C.loft("edge", [(0.58, 0.9, 0.55, 0), (0.59, 0.9, 0.55, 0), (0.61, 0.9, 0.55, 0), (0.614, 0.89, 0.54, 0)], "trim", r=0.045, k=2),
             C.box("slate", (0.34, 0.22, 0.004), (0, -0.05, 0.622), "black"),
             C.box("tray", (0.72, 0.4, 0.015), (0, 0.02, 0.5), "trim"),
             C.box("tray_lip", (0.72, 0.015, 0.05), (0, -0.18, 0.52), "trim"),
             C.lathe("post", [(0.001, 0), (0.2, 0), (0.2, 0.012), (0.12, 0.03), (0.03, 0.05), (0.025, 0.58), (0.001, 0.58)], "trim", steps=8)]
    return C.smooth(C.join(f"school_desk_{tag}", parts), 35)


def school_stool():
    parts = [C.lathe("cushion", [(0.001, 0.37), (0.172, 0.37), (0.17, 0.41), (0.14, 0.421), (0.001, 0.421)], "stool_fabric", steps=12),
             C.lathe("base", [(0.001, 0), (0.16, 0), (0.03, 0.05), (0.025, 0.34), (0.15, 0.37), (0.001, 0.37)], "trim", steps=12)]
    return C.smooth(C.join("school_stool", parts), 40)


def school_screen():
    W, H, Y0 = 3.0, 1.4, 1.7
    parts = [C.box("bezel", (W + 0.16, 0.05, H + 0.16), (0, 0.03, Y0), "console", bevel=0.02, segments=2),
             C.box("ledge", (W + 0.3, 0.16, 0.05), (0, -0.04, Y0 - H / 2 - 0.12), "trim", bevel=0.012, segments=2)]
    for sz in (-1, 1):
        parts.append(C.box(f"rimx{sz}", (W + 0.08, 0.03, 0.04), (0, -0.005, Y0 + sz * (H / 2 + 0.02)), "trim", bevel=0.008, segments=1))
    for sx in (-1, 1):
        parts.append(C.box(f"rimy{sx}", (0.04, 0.03, H), (sx * (W / 2 + 0.02), -0.005, Y0), "trim", bevel=0.008, segments=1))
        parts.append(C.box(f"cap{sx}", (0.1, 0.04, H * 0.6), (sx * (W / 2 + 0.16), 0.02, Y0 + 0.1), "lcars_peach", bevel=0.04, segments=3))
    return C.smooth(C.join("school_screen", parts), 35)


C.clean_scene()
props = C.finish_props([school_desk("a", "desk_amber"), school_desk("b", "desk_teal"), school_desk("c", "desk_rust"),
                        school_desk("w", "desk_wood2"), school_stool(), school_screen()])
C.finish_room("school", props, size=1024)
