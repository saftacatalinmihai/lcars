"""The generated mess halls' props (docs/design/deck-remodel.md, slice 7):
lcars-ui/deck/mess.glb, one atlas every mess shares - its round table, its
chair and the replicator counter along its wall. Until now a mess took Ten
Forward's table and chairs (its glb, a 2048 atlas, loaded for them on any
deck) and drew its replicators as trim boxes.

    blender -b --factory-startup -P scripts/deck-models/mess.py -- OUT_DIR

Built to the stand-ins in deck.html's `mess` builder, whose origins they
keep (the floor under the footprint's middle), front toward -Y here
(glTF's +Z):
- `mess_table`, over `table(x, z, 1, 1, ..., true)`: a top of 0.5 m radius
  from 0.715 to 0.765, a turned leg;
- `mess_chair`, over `deskChair()`: the seat's top at 0.51, the back
  behind it (+Y here, as tenforward.py's mess_chair);
- `mess_replicator`, one bay of the replicator wall: the stand-in's box
  1.3 wide from 0.5 to 2.4, its face at Y -0.025, and its lit niche
  (0.9 x 0.7 at 1.45, the page's MX.niche, kept over the model) at Y
  -0.03. Here a dark cabinet from the floor, a brushed upper body, a
  rim round the niche standing proud of it (the niche reads set in), a
  counter ledge under it, a lit-strip groove (black) over it.
The biggest hall (15 x ~11 m) has 15 tables and 9 bays: at most 15 k
triangles a room (slice 5's budget) leaves ~880 a table and its four
chairs, so the chair is 164 and the table 200 (that hall's furniture
14.7 k): eight- to twenty-sided turnings of few rings, one-segment
bevels, the rims plain boxes.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401

import common as C  # noqa: E402

C.PALETTE["mess_top"] = (0xd8cfc0, 0.4, 0.0, None)
C.PALETTE["mess_fabric"] = (0x544a66, 0.85, 0.0, "weave")


def mess_table():
    parts = [C.lathe("top", [(0.001, 0.715), (0.5, 0.715), (0.5, 0.765), (0.001, 0.765)], "mess_top", steps=20),
             C.lathe("leg", [(0.001, 0), (0.22, 0), (0.06, 0.05), (0.045, 0.68), (0.12, 0.715), (0.001, 0.715)], "trim", steps=8)]
    return C.smooth(C.join("mess_table", parts), 40)


def mess_chair():
    parts = [C.box("seat", (0.46, 0.46, 0.07), (0, 0, 0.475), "mess_fabric", bevel=0.025, segments=1),
             C.box("spine", (0.05, 0.03, 0.32), (0, 0.225, 0.6), "trim")]
    back = C.box("back", (0.44, 0.06, 0.42), (0, 0.22, 0.79), "mess_fabric", bevel=0.025, segments=1)
    back.rotation_euler.x = -0.1
    parts.append(back)
    parts.append(C.lathe("foot", [(0.001, 0), (0.23, 0), (0.03, 0.05), (0.03, 0.44), (0.001, 0.44)], "trim", steps=8))
    return C.smooth(C.join("mess_chair", parts), 40)


def mess_replicator():
    """One bay, its back to the wall at Y +0.225, the room at -Y."""
    parts = [C.box("cabinet", (1.3, 0.42, 0.98), (0, 0.02, 0.49), "console", bevel=0.015, segments=1),
             C.box("counter", (1.34, 0.46, 0.04), (0, 0.0, 1.0), "trim", bevel=0.012, segments=1),
             C.box("body", (1.3, 0.24, 1.38), (0, 0.105, 1.71), "trim", bevel=0.015, segments=1),
             C.box("groove", (1.1, 0.01, 0.04), (0, -0.02, 2.05), "black"),
             C.box("cap", (1.34, 0.28, 0.06), (0, 0.09, 2.43), "console")]
    # the rim round the niche, proud of the body's face (the niche's plane
    # at -0.03 sits 2.5 cm behind the rim's face)
    for sz in (-1, 1):
        parts.append(C.box(f"rimx{sz}", (1.04, 0.06, 0.07), (0, -0.03, 1.45 + sz * 0.385), "console"))
    for sx in (-1, 1):
        parts.append(C.box(f"rimy{sx}", (0.07, 0.06, 0.7), (sx * 0.485, -0.03, 1.45), "console"))
    return C.smooth(C.join("mess_replicator", parts), 35)


C.clean_scene()
props = C.finish_props([mess_table(), mess_chair(), mess_replicator()])
C.finish_room("mess", props, size=1024)
