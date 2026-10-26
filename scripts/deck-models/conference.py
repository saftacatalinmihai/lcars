"""The generated conference rooms' props (docs/design/deck-remodel.md,
slice 7): lcars-ui/deck/conference.glb, one atlas every conference room
shares - the long table with its inlay and the high-backed chair round it.

    blender -b --factory-startup -P scripts/deck-models/conference.py -- OUT_DIR

Built to the stand-ins in deck.html's `conference` builder, whose origins
they keep (the floor under the footprint's middle), front toward -Y here
(glTF's +Z):
- `conf_table`, the table at its longest (L 6: `Math.min(D - 4.2, 6)`),
  stretched along its length by the page for a shorter room: a top 1.4
  wide from 0.72 to 0.78, the stand-in's amber strip (0.03 wide at 0.783)
  kept over its middle, two pedestals at a quarter of the length from
  each end. The top is a dark wood with a band of brushed metal round its
  edge and an inlay of a lighter grained wood in its field, under the
  strip; the grain is in the baked colour, not only the relief: the old
  table's grain was the page's `M.wood` repeated at a texel's scale and
  read as ripples (the survey), and a flat colour reads as plastic.
- `conf_chair`, over `chair(x, z, 0.85)` (the plain one, as lounge.py's
  lounge_chair, which these rooms took until now): the seat's top at
  0.585, the arms at x +-0.36, the back behind the pedestal's axis. The
  survey's chairs were black blobs: lounge leather is near-black, and in a
  room lit from above its shell, seat and back merge. So here the leather
  is a dark oxblood a few steps lighter, the shell, arms and pedestal the
  brushed trim (a light frame the dark leather sits in: the silhouette
  reads at a phone's distance), and the back's cushion in three vertical
  channels with piping round it, which a bake shows as lines where a
  bevel alone shows nothing.
Budgets (deck-remodel.md, slices 5 and 7): at most 15 k triangles a room
(twelve chairs and the table), the table at most 1.5 k, a chair under 1 k.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402

import common as C  # noqa: E402

C.PALETTE["conf_wood"] = (0x3e2a1e, 0.35, 0.0, "grain")
C.PALETTE["conf_inlay"] = (0x8a6240, 0.32, 0.0, "grain")
C.PALETTE["conf_leather"] = (0x4e2a24, 0.5, 0.0, "pebble")
C.PALETTE["conf_piping"] = (0x24120f, 0.45, 0.0, None)


def grained(name, dark):
    """The palette's `name` with its grain in the colour too: the wave the
    bump reads also mixes the base colour toward `dark` (a sRGB hex), so
    the bake writes the figure into the atlas. Its bands vary across X, so
    the grain's lines run along Y, the table's length, and are stretched
    along it (a board's long figure, not a ring's)."""
    m = C.mat(name)
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    wave = next(n for n in nt.nodes if n.type == "TEX_WAVE")
    mp = nt.nodes.new("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1, 0.12, 1)
    tc = next(n for n in nt.nodes if n.type == "TEX_COORD")
    nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
    nt.links.new(mp.outputs["Vector"], wave.inputs["Vector"])
    mix = nt.nodes.new("ShaderNodeMixRGB")
    mix.inputs["Color1"].default_value = bsdf.inputs["Base Color"].default_value[:]
    mix.inputs["Color2"].default_value = (*C.hex_rgb(dark), 1)
    ramp = nt.nodes.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.35
    ramp.inputs["From Max"].default_value = 0.85
    nt.links.new(wave.outputs["Fac"], ramp.inputs["Value"])
    nt.links.new(ramp.outputs["Result"], mix.inputs["Fac"])
    nt.links.new(mix.outputs["Color"], bsdf.inputs["Base Color"])
    return m


L = 6.0


def tilt(objs, pivot, angle):
    """Lean `objs` back about the X axis through `pivot` (lounge.py's)."""
    from mathutils import Matrix
    bpy.context.view_layer.update()
    R = Matrix.Translation(pivot) @ Matrix.Rotation(angle, 4, "X") @ Matrix.Translation([-c for c in pivot])
    for o in objs:
        o.matrix_world = R @ o.matrix_world


def conf_table():
    """A dark wooden top with a brushed band round it and a lighter inlay
    in its field; two flared pedestals."""
    parts = [C.loft("top", [(0.72, 1.36, L - 0.04, 0), (0.78, 1.36, L - 0.04, 0)], "conf_wood", r=0.12),
             # the band: a brushed rim 2 cm proud of the top's edge, its own top
             # under the wood's (a solid of the full width capped over the top
             # hid the wood and the inlay: the first bake's grey table)
             C.loft("band", [(0.715, 1.4, L, 0), (0.725, 1.4, L, 0), (0.77, 1.4, L, 0), (0.775, 1.38, L - 0.02, 0)], "trim", r=0.13),
             C.loft("inlay", [(0.776, 0.9, L - 0.6, 0), (0.7815, 0.9, L - 0.6, 0)], "conf_inlay", r=0.08),
             C.box("line_l", (0.012, L - 0.7, 0.002), (-0.41, 0, 0.7815), "bronze"),
             C.box("line_r", (0.012, L - 0.7, 0.002), (0.41, 0, 0.7815), "bronze")]
    for s in (-1, 1):
        y = s * L / 4
        parts.append(C.loft(f"ped{s}", [(0.0, 0.62, 0.8, y), (0.06, 0.62, 0.8, y), (0.1, 0.42, 0.62, y), (0.62, 0.36, 0.56, y),
                                         (0.72, 0.5, 0.74, y)], "console", r=0.06))
        parts.append(C.loft(f"kick{s}", [(0.0, 0.66, 0.84, y), (0.035, 0.66, 0.84, y)], "trim", r=0.07))
    return C.smooth(C.join("conf_table", parts), 35)


def conf_chair():
    """lounge.py's chair, re-dressed: a brushed shell and arms, the
    leather an oxblood in channels with piping round them."""
    parts = [C.lathe("ped", [(0.001, 0), (0.29, 0), (0.29, 0.015), (0.22, 0.04), (0.08, 0.07), (0.06, 0.3), (0.12, 0.38),
                             (0.18, 0.4), (0.001, 0.4)], "trim", steps=10),
             C.box("pan", (0.62, 0.6, 0.07), (0, 0.0, 0.43), "trim", bevel=0.02, segments=1),
             C.box("seat", (0.56, 0.54, 0.12), (0, -0.01, 0.52), "conf_leather", bevel=0.045, segments=2),
             C.tube("seatpipe", [(-0.27, -0.28, 0.545), (0.27, -0.28, 0.545)], 0.008, "conf_piping", res=4)]
    # the high back: a brushed shell, the cushion in three channels (two
    # seams down it and piping round its face), a rolled head
    back = [C.box("shell", (0.64, 0.07, 0.9), (0, 0.33, 0.95), "trim", bevel=0.025, segments=2)]
    for i, x in enumerate((-0.19, 0, 0.19)):
        back.append(C.box(f"ch{i}", (0.18, 0.1, 0.66), (x, 0.26, 0.86), "conf_leather", bevel=0.035, segments=1))
    back.append(C.box("head", (0.54, 0.11, 0.15), (0, 0.27, 1.27), "conf_leather", bevel=0.05, segments=2))
    back.append(C.tube("pipe", [(-0.285, 0.205, 0.52), (-0.285, 0.205, 1.2), (0.285, 0.205, 1.2), (0.285, 0.205, 0.52)], 0.008,
                       "conf_piping", res=4))
    tilt(back, (0, 0.3, 0.5), -0.1)
    parts += back
    for sx in (-1, 1):
        x = sx * 0.36
        parts.append(C.box(f"post{sx}", (0.05, 0.08, 0.2), (x, 0.08, 0.53), "trim"))
        parts.append(C.box(f"arm{sx}", (0.08, 0.52, 0.05), (x, 0.03, 0.645), "trim", bevel=0.015, segments=1))
        parts.append(C.box(f"armpad{sx}", (0.075, 0.4, 0.035), (x, 0.06, 0.685), "conf_leather", bevel=0.014, segments=1))
    return C.smooth(C.join("conf_chair", parts), 35)


C.clean_scene()
grained("conf_wood", 0x2a1a12)
grained("conf_inlay", 0x6a4428)
props = C.finish_props([conf_table(), conf_chair()])
C.finish_room("conference", props, size=1024)
