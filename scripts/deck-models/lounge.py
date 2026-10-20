"""The observation lounge's props (docs/design/deck-style.md part 2,
"Observation lounge"): lcars-ui/deck/lounge.glb, its own atlas: the black
high-backed chair the senior staff sit in, placed over every chair round the
table, the sofa under the aft wall's screen (`lounge_sofa`, below), and an
armchair the generated cabins take (`lounge_armchair`), and the cabins'
PADD shelves (`cabin_padd_shelf_a`, `_b`: common.py's, the ready room's
two arrangements, as the quarters take this glb) and their wardrobe
(`cabin_wardrobe`, common.py's); and the lounge's own two shelves on its
forward wall (`lounge_padd_shelf_a`, `_b`: the same two arrangements on a
rack in the lounge's colours, its table's wood and its stone's grey).

    blender -b --factory-startup -P scripts/deck-models/lounge.py -- OUT_DIR

Built to the stand-in's measures (`chair(x, z, s)` in deck.html, the plain
one: the seat's top at 0.585, the arms at x +-0.36, the back's cushion
0.19-0.33 behind the pedestal's axis and up to 1.325), so the stand-in's
seat and block fit it; the page stretches it across by the stand-in's `s`
(0.85 at the sides, 0.95 at the ends), as the bridge's chairs are. Its
front is -Y here (glTF's +Z); a deck-8 chair faces -z, so the page turns it.
The leather is the palette's lounge leather, baked: no new material in the
page.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

import common as C  # noqa: E402


def tilt(objs, pivot, angle):
    """Lean `objs` back about the X axis through `pivot` (bridge.py's)."""
    from mathutils import Matrix
    bpy.context.view_layer.update()
    R = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, "X") @ Matrix.Translation([-c for c in pivot])
    for o in objs:
        o.matrix_world = R @ o.matrix_world


def lounge_chair():
    parts = []
    # the pedestal: a turned column on a low round foot, brushed
    parts.append(C.lathe("ped", [(0.001, 0), (0.29, 0), (0.29, 0.015), (0.22, 0.04), (0.08, 0.07), (0.06, 0.3), (0.12, 0.38),
                                 (0.18, 0.4), (0.001, 0.4)], "trim", steps=12))
    # the seat: a black pan, the cushion in it with a rolled front edge
    parts.append(C.box("pan", (0.62, 0.6, 0.07), (0, 0.0, 0.43), "console", bevel=0.02, segments=2))
    parts.append(C.box("seat", (0.56, 0.54, 0.12), (0, -0.01, 0.52), "lounge_leather", bevel=0.045, segments=2))
    # the high back: a shell, and in it a tall cushion in three channels
    # (two seams across) under a rolled head
    back = [C.box("shell", (0.64, 0.07, 0.86), (0, 0.33, 0.93), "console", bevel=0.025, segments=2),
            C.box("cushion", (0.56, 0.1, 0.66), (0, 0.26, 0.86), "lounge_leather", bevel=0.04, segments=3),
            C.box("head", (0.5, 0.11, 0.15), (0, 0.27, 1.25), "lounge_leather", bevel=0.05, segments=3)]
    for i, z in enumerate((0.75, 0.98)):
        back.append(C.box(f"seam{i}", (0.5, 0.012, 0.008), (0, 0.209, z), "black"))
    tilt(back, (0, 0.3, 0.5), -0.1)
    parts += back
    # the arms: a slim black bar on a post, padded on top
    for sx in (-1, 1):
        x = sx * 0.36
        parts.append(C.box(f"post{sx}", (0.05, 0.08, 0.2), (x, 0.08, 0.53), "console", bevel=0.01, segments=1))
        parts.append(C.box(f"arm{sx}", (0.08, 0.52, 0.05), (x, 0.03, 0.645), "console", bevel=0.015, segments=2))
        parts.append(C.box(f"armpad{sx}", (0.075, 0.4, 0.035), (x, 0.06, 0.685), "lounge_leather", bevel=0.014, segments=2))
    return C.smooth(C.join("lounge_chair", parts), 35)


# ---------------------------------------------------------------- the sofa
# The sofa under the aft wall's screen (`sofa(x, z, rot, 2.3)`): common.py's,
# which the ready room's atlas takes too. Its two throw pillows (the page's
# colours, kept over the model) lean on the back cushions. And an armchair,
# the same at 0.95 with one seat and slimmer arms: the generated cabins'
# two by the window (`sofa(..., 0.92)`), which the lounge's sofa squeezed
# to 40% would leave with arms 6 cm thick.
SOFA_W, ARM_W = 2.3, 0.95
# The lounge's grey: its walls' ashlar below the dado (M.ashlarLow); the
# rack's back the black of its chairs' shells, its boards the table's wood.
C.PALETTE["lounge_grey"] = (0x8e8068, 0.7, 0.1, None)


def lounge_shelf(variant):
    return C.padd_shelf(f"lounge_padd_shelf_{variant}", C.shelf_books(variant), side="lounge_grey", back="console", board="rail_wood")


C.clean_scene()
props = [lounge_chair(), C.sofa("lounge_sofa", SOFA_W), C.sofa("lounge_armchair", ARM_W, aw=0.15),
         C.padd_shelf("cabin_padd_shelf_a", C.shelf_books("a")), C.padd_shelf("cabin_padd_shelf_b", C.shelf_books("b")),
         C.wardrobe("cabin_wardrobe"), lounge_shelf("a"), lounge_shelf("b")]
# the origins are the stand-ins' (the floor under the chair's pedestal, the
# middle of the sofa's footprint)
C.finish_props(props)
# 1024 since the sofa joined the chair: at 512 the two would have half the
# chair's texels each (deck-pipeline.md's decisions)
C.finish_room("lounge", props, size=1024)
