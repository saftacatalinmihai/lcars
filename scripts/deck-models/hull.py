"""The hull's greebles (docs/design/deck-style.md part 6 (b)):
lcars-ui/deck/hull.glb: the parts on the saucer's top that tell a
Galaxy-class hull from a grey one, seen from deck 8's windows (Ten Forward,
the lounge, the arboretum, the ready room). The page places them by rule on
the saucer (`hullGreebles` in deck.html) and merges them into one mesh in a
material of its own, lit by the sun as `hullMat` is.

    blender -b --factory-startup -P scripts/deck-models/hull.py -- OUT_DIR

Coordinates: metres, Blender's +Z up (the hull's outward normal where it is
placed), the origin on the plating at the footprint's middle, the front
toward -Y (out over the rim, for the ones that face a way):
- `phaser_strip`, a segment of the dorsal phaser array, 14 m along X and
  1.6 m across: a coppery band ribbed every metre, a dark groove down its
  middle with the emitter line in it (laid end to end round the ring, a
  2 m gap between segments);
- `rcs_quad`, a reaction control thruster block, 5 x 5 x 1.5 m, chamfered,
  four nozzles on its face toward the rim;
- `lifeboat_row`, six lifeboat hatches 2.4 m square, 1 m apart (19.4 m
  along X), each a dark-lined frame round a plate a shade darker than the
  hull;
- `sensor_dome`, a dark glossy dome 2.4 m across on a hull-grey collar.

Small, many, and far: 140 to 570 triangles each (no bevels on the ribs or
the hatches - a bevel 200 m off is a pixel's tenth), one 1024 atlas; the
page places about 135 of them, ~35 k triangles in all (the budget is 40 k).

The atlas's metalness is not metalness here: no hull part is metal to the
eye at this distance, so the page reads the ORM's blue channel as a glow
mask (`hullGreebleMat`): the emitter line's `emit_amber` is the only
material with metalness, and it glows.
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401

import common as C  # noqa: E402

# deck-style.md part 6 (b)'s hull colours
C.PALETTE["hull_light"] = (0xbcbfc2, 0.55, 0.0, None)
C.PALETTE["hull_dark"] = (0xa7aaae, 0.6, 0.0, None)
C.PALETTE["hull_line"] = (0x4a4e54, 0.7, 0.0, None)
C.PALETTE["hatch"] = (0x8a8e94, 0.55, 0.0, None)
C.PALETTE["phaser"] = (0x6a5a4c, 0.4, 0.0, None)
C.PALETTE["nozzle"] = (0x3a3c40, 0.5, 0.0, None)
C.PALETTE["frame"] = (0x2a2c30, 0.6, 0.0, None)
C.PALETTE["sensor"] = (0x2e3640, 0.2, 0.0, None)
# the glow mask (see above): metalness 1 marks it
C.PALETTE["emit_amber"] = (0xff9933, 0.5, 1.0, None)

SEG = 14.0


def phaser_strip():
    """A low coppery band, its edges sloped into the plating, a rib across
    it every metre and the dark groove with the emitter down its middle."""
    w, h = 1.6, 0.3
    sec = [(-w / 2 - 0.25, 0.0), (-w / 2, h), (w / 2, h), (w / 2 + 0.25, 0.0)]
    parts = [C.prism("band", sec, -SEG / 2, SEG / 2, "phaser"),
             C.box("groove", (SEG, 0.36, 0.04), (0, 0, h + 0.005), "frame"),
             C.box("emitter", (SEG - 0.4, 0.1, 0.05), (0, 0, h + 0.012), "emit_amber")]
    for i in range(int(SEG)):
        # one box across the band, the groove's floor over it
        parts.append(C.box(f"rib{i}", (0.12, w - 0.1, 0.06), (-SEG / 2 + 0.5 + i, 0, h + 0.02), "phaser"))
    return C.join("phaser_strip", parts)


def rcs_quad():
    """A chamfered block and four nozzles on its rim-ward face (-Y)."""
    s, h = 5.0, 1.5
    sec = [(-s / 2, 0.0), (-s / 2, h * 0.7), (-s / 2 + 0.5, h), (s / 2 - 0.5, h), (s / 2, h * 0.7), (s / 2, 0.0)]
    parts = [C.prism("block", sec, -s / 2, s / 2, "hull_light", bevel=0.06, segments=1),
             C.box("plate", (s - 1.2, s - 1.6, 0.06), (0, 0.2, h + 0.03), "hull_dark"),
             C.box("seat", (s - 0.6, 0.1, h * 0.8), (0, -s / 2 - 0.05, h * 0.45), "frame")]
    for ix in (-1, 1):
        for iz in (0, 1):
            nz = C.lathe(f"nozzle{ix}{iz}", [(0.001, 0.0), (0.42, 0.0), (0.5, 0.35), (0.62, 0.7), (0.5, 0.7), (0.3, 0.2), (0.001, 0.2)],
                         "nozzle", steps=10)
            nz.rotation_euler.x = math.pi / 2
            nz.location = (ix * 1.15, -s / 2 - 0.1, 0.35 + iz * 0.6)
            parts.append(nz)
    return C.smooth(C.join("rcs_quad", parts), 40)


def lifeboat_row():
    """Six hatches in a row along X: each a dark-lined plate a shade
    darker than the hull, a hand proud of it (two boxes: 79 rows ring the
    saucer, so each triangle counts 79 times)."""
    parts = []
    for i in range(6):
        x = (i - 2.5) * 3.4
        parts += [C.box(f"line{i}", (2.5, 2.5, 0.06), (x, 0, 0.03), "hull_line"),
                  C.box(f"hatch{i}", (2.3, 2.3, 0.1), (x, 0, 0.05), "hatch")]
    return C.join("lifeboat_row", parts)


def sensor_dome():
    """A collar on the plating and the dark dome on it."""
    dome = [(1.2 * math.cos(a), 0.25 + 0.9 * math.sin(a)) for a in (0.0, 0.35, 0.7, 1.05, 1.35)] + [(0.001, 1.15)]
    parts = [C.lathe("collar", [(0.001, 0.0), (1.6, 0.0), (1.5, 0.25), (0.001, 0.25)], "hull_light", steps=16),
             C.lathe("dome", dome, "sensor", steps=16)]
    return C.smooth(C.join("sensor_dome", parts), 40)


C.clean_scene()
props = C.finish_props([phaser_strip(), rcs_quad(), lifeboat_row(), sensor_dome()])
C.finish_room("hull", props, size=1024)
