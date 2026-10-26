"""Main engineering's props (docs/design/deck-remodel.md, slice 4):
lcars-ui/deck/engineering.glb: the master systems display's table and the
wall console, after the slice's Seedream concept (a satin gunmetal table
flaring up to a rimmed top; sloped wall consoles, LCARS insets).

    blender -b --factory-startup -P scripts/deck-models/engineering.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported), built to its stand-in in deck.html, whose origin it
keeps:
- `msd_table`, over the master systems display's box (3.4 x 0.95 x 1.6,
  its origin on the floor under its middle): a dark kick, a body flaring
  up to a grey top slab, and a raised rim round a black recess the
  stand-in's display (3.2 x 1.4 at 0.956, kept) lies in, the rim's top at
  0.975; the stand-in's amber strips (y 0.84, on the slab's upright
  edge, 0.82 to 0.86, at 0.8 and 1.7 out) are kept;
- `wall_console`, over `wallConsole()`: its back to the wall at Y 0, the
  room toward -Y; a body whose top slopes from 0.94 at the front edge (Y
  -0.52) to 1.12 at the back (Y -0.04), the stand-in's LCARS inset (1.3 x
  0.34 on that slope) kept; side cheeks, a lip on the front edge, a grille
  under it, a dark kick; and the back panel (1.76 wide, 1.1 to 2.4) the
  wall display's frame stands in front of (0.085 off the wall).
Budgets (deck-remodel.md): at most 1.5 k triangles each.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401

import common as C  # noqa: E402

# the concept's satin gunmetal, and its darker body (0x7c8088 and 0x34363c
# at first: under deck 36's blue light both read as black boxes)
C.PALETTE["eng_grey"] = (0x9a9ea6, 0.42, 0.55, "brushed")
C.PALETTE["eng_dark"] = (0x5c6068, 0.5, 0.45, "brushed")


def msd_table():
    """A kick, a flared body, the top slab, a rim round the display's
    recess."""
    parts = [C.loft("kick", [(0.0, 2.7, 0.92, 0), (0.1, 2.7, 0.92, 0)], "console", r=0.06),
             C.loft("body", [(0.1, 2.86, 1.06, 0), (0.5, 2.98, 1.18, 0), (0.78, 3.3, 1.5, 0), (0.82, 3.36, 1.56, 0)], "eng_dark", r=0.08),
             C.loft("slab", [(0.82, 3.4, 1.6, 0), (0.86, 3.4, 1.6, 0), (0.9, 3.36, 1.56, 0)], "eng_grey", r=0.08),
             C.box("recess", (3.22, 1.42, 0.05), (0, 0, 0.925), "black")]
    # the rim: two long and two short bars, bevelled, a little over the display
    for sy in (-1, 1):
        parts.append(C.box(f"rimx{sy}", (3.4, 0.09, 0.075), (0, sy * 0.755, 0.9375), "eng_grey", bevel=0.012, segments=2))
    for sx in (-1, 1):
        parts.append(C.box(f"rimy{sx}", (0.09, 1.42, 0.075), (sx * 1.655, 0, 0.9375), "eng_grey", bevel=0.012, segments=2))
    # a dark panel set in each long side of the body
    for sy in (-1, 1):
        parts.append(C.box(f"panel{sy}", (1.9, 0.012, 0.36), (0, sy * 0.55, 0.42), "black"))
    return C.smooth(C.join("msd_table", parts), 35)


def wall_console():
    """A sloped body between cheeks, a lip and a grille on its front, a
    kick, and the back panel up the wall behind the display."""
    # the body's section in (Y, Z), the room at -Y
    sec = [(-0.03, 0.1), (-0.47, 0.1), (-0.5, 0.16), (-0.52, 0.9), (-0.52, 0.94), (-0.04, 1.12), (-0.03, 1.12)]
    parts = [C.prism("body", sec, -0.74, 0.74, "eng_dark", bevel=0.008),
             C.box("kick", (1.48, 0.4, 0.1), (0, -0.25, 0.05), "console"),
             C.box("lip", (1.5, 0.05, 0.05), (0, -0.52, 0.93), "eng_grey", bevel=0.015, segments=2),
             C.box("back", (1.76, 0.06, 1.3), (0, -0.04, 1.75), "eng_grey", bevel=0.012, segments=2),
             C.box("rail", (1.76, 0.07, 0.06), (0, -0.07, 1.13), "eng_grey", bevel=0.015, segments=2)]
    for sx in (-1, 1):
        parts.append(C.prism(f"cheek{sx}", [(y, z + 0.02) for y, z in sec[1:6]] + [(-0.04, 0.1)], sx * 0.74, sx * 0.78, "eng_grey", bevel=0.006))
    for i in range(4):
        parts.append(C.box(f"slat{i}", (1.3, 0.012, 0.025), (0, -0.53 + 0.003 * i, 0.3 + i * 0.1), "black"))
    return C.smooth(C.join("wall_console", parts), 35)


C.clean_scene()
props = C.finish_props([msd_table(), wall_console()])
C.finish_room("engineering", props, size=1024)
