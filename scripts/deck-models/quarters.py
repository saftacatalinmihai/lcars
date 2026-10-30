"""The crew quarters' props (docs/design/deck-remodel.md section 6, slice 5):
lcars-ui/deck/quarters.glb, the one atlas every generated cabin takes (as
lab.glb is every lab's): the bed with its headboard (two widths), the sofa
and the armchair, the nightstands, the coffee table, the round side table
by the window, the low cabinet under the screen, the desk and its chair,
the table and floor lamps, the wardrobe and the two PADD shelves.

    blender -b --factory-startup -P scripts/deck-models/quarters.py -- OUT_DIR

Coordinates: metres, Blender's +Z up, each prop's front toward -Y (glTF's
+Z once exported, the stand-in group's local +z), built to its stand-in in
deck.html's `quarters` builder, whose origin (the floor under the middle of
its footprint) it keeps:
- `quarters_bed`, `quarters_bed_narrow`, over `bed(x, z, rot, wd)` at wd
  1.6 and 1.2, L 2.1: its head at +Y (the stand-in's local -z, against
  the wall), a plinth set back over a dark kick, the mattress to 0.5, a
  duvet with its top folded back, two pillows (one on the narrow bed),
  and an upholstered headboard in a wood frame to 0.95;
- `quarters_sofa` (2.3, the page squeezes it to its width) and
  `quarters_armchair` (0.95), over `sofa(x, z, rot, w)`: common.py's
  measures (the seats' tops at 0.465, the back to 0.84, the arms to 0.6,
  0.86 deep), so the stand-in's seats and pillows (kept over the model)
  fit; on short tapered legs, the arms rolled;
- `quarters_nightstand`, 0.42 x 0.42 to 0.5, two drawers;
- `quarters_coffee_table`, 1.1 x 0.6 to 0.38, a top on slab ends over a
  shelf;
- `quarters_side_table`, round, r 0.28 to 0.57, on a stem;
- `quarters_credenza`, 1.8 x 0.4 to 0.5, three doors, under the screen;
- `quarters_desk`, 1.5 x 0.8 to 0.775, its sitter at -Y: panel ends, a
  modesty panel, a shallow drawer, the screen's stand at the back (the
  page's screen, kept, sits on it at 1.02), three books at +X;
- `quarters_desk_chair`, over `deskChair()`: a five-star base on casters,
  the column, a seat to 0.51 and a back leaning back as the stand-in's;
- `quarters_table_lamp` (h 0.34, over a nightstand) and
  `quarters_floor_lamp` (h 1.45): the base and the stem in brass; the
  shade and the bulb are the page's (lit, kept over the model);
- `quarters_wardrobe`, `quarters_padd_shelf_a`, `_b`: common.py's, as
  lounge.py had them for the cabins.
Every cabin's furniture in this one atlas: one draw call for all of it,
where the code-built pieces were a call per material.

The sofa and the double bed are generated (deck-remodel.md slice 9, on the
captain's word 2026-10-30): Tripo H3.1 multiview through gen.py, fitted by
fit.py to the boxes above (the sofa 2.3 x 0.86 x 0.84, the bed 1.6 x 2.16
x 0.95 with its headboard), kept in the media store and passed by build.sh
(`generated()`); the narrow bed is the double's copy at 1.2 across. With
no folder (the public repo, a box without the NAS) the scripted ones below
are built, as before.

    blender -b --factory-startup -P scripts/deck-models/quarters.py -- OUT_DIR [GENERATED_DIR]
"""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bpy  # noqa: E402,F401

import common as C  # noqa: E402

# a cabin's upholstery: a warm taupe weave (the code-built sofa's grey
# read cold under the cabins' amber light), the bed's linen and duvet
C.PALETTE["cabin_fabric"] = (0x8a6c58, 0.85, 0.0, "weave")
C.PALETTE["linen"] = (0xd8dde4, 0.8, 0.0, "weave")
C.PALETTE["duvet"] = (0x3e4c66, 0.9, 0.0, "weave")
C.PALETTE["head_pad"] = (0x6e5a4c, 0.8, 0.0, "pebble")


def turned(name, profile, material, steps, at):
    return C.lathe(name, profile, material, steps=steps, at=at)


def bed(name, wd):
    """The stand-in's bed at width `wd`: L 2.1, the head at +Y."""
    L = 2.1
    parts = [C.box("kick", (wd - 0.16, L - 0.16, 0.08), (0, 0, 0.04), "console"),
             C.box("frame", (wd, L, 0.22), (0, 0, 0.19), "cabin_wood", bevel=0.02, segments=2),
             C.box("mattress", (wd - 0.06, L - 0.08, 0.2), (0, -0.01, 0.4), "linen", bevel=0.05, segments=3)]
    # the duvet over the foot two thirds, its sides falling past the
    # mattress's, the top 0.3 folded back over it
    dl = L * 0.66
    parts += [C.box("duvet", (wd + 0.02, dl, 0.07), (0, -L / 2 + dl / 2 - 0.01, 0.485), "duvet", bevel=0.03, segments=3),
              C.box("fold", (wd + 0.03, 0.3, 0.04), (0, -L / 2 + dl - 0.14, 0.535), "duvet", bevel=0.018, segments=2)]
    # the pillows against the headboard
    for i, x in enumerate((-wd / 4, wd / 4) if wd > 1.3 else (0,)):
        pw = wd / 2 - 0.14 if wd > 1.3 else wd - 0.4
        p = C.box(f"pillow{i}", (pw, 0.36, 0.13), (x, L / 2 - 0.27, 0.56), "linen", bevel=0.05, segments=3)
        p.rotation_euler.x = -0.22      # leaning on the headboard
        parts.append(p)
    # the headboard: a wood frame round an upholstered panel in channels
    hy, hh = L / 2 + 0.02, 0.95
    parts.append(C.box("hframe", (wd + 0.06, 0.08, hh), (0, hy, hh / 2), "cabin_wood", bevel=0.02, segments=2))
    n = 3 if wd > 1.3 else 2
    cw = (wd - 0.1) / n
    for i in range(n):
        x = -wd / 2 + 0.05 + cw * (i + 0.5)
        parts.append(C.box(f"chan{i}", (cw - 0.012, 0.06, 0.48), (x, hy - 0.05, 0.69), "head_pad", bevel=0.025, segments=3))
    return C.smooth(C.join(name, parts), 40)


def sofa(name, w, aw):
    """common.py's sofa's measures, the arms rolled, on legs."""
    seats = 2 if w > 1.2 else 1
    sw = (w - 2 * aw) / seats
    parts = [C.box("base", (w - 2 * aw + 0.02, 0.84, 0.22), (0, 0, 0.2), "cabin_fabric", bevel=0.025, segments=2),
             C.box("frame", (w - 0.02, 0.17, 0.5), (0, 0.345, 0.59), "cabin_fabric", bevel=0.03, segments=2)]
    for sx in (-1, 1):
        for sy in (-1, 1):
            parts.append(turned(f"leg{sx}{sy}", [(0.001, 0), (0.018, 0), (0.026, 0.09), (0.001, 0.09)], "desk_wood", 8,
                                (sx * (w / 2 - 0.07), sy * 0.36, 0)))
    for i in range(seats):
        x = (i + 0.5 - seats / 2) * sw
        parts.append(C.box(f"seat{i}", (sw - 0.015, 0.68, 0.15), (x, -0.07, 0.39), "cabin_fabric", bevel=0.055, segments=3))
        back = C.box(f"back{i}", (sw - 0.015, 0.16, 0.42), (x, 0.235, 0.67), "cabin_fabric", bevel=0.06, segments=3)
        back.rotation_euler.x = -0.12
        parts.append(back)
    # the arms: a panel, a roll along its top a little proud of it outward
    for s in (-1, 1):
        x = s * (w - aw) / 2
        parts.append(C.box(f"arm{s}", (aw - 0.02, 0.86, 0.42), (x, 0, 0.3), "cabin_fabric", bevel=0.03, segments=2))
        r = aw / 2 + 0.005
        roll = turned(f"roll{s}", [(0.001, -0.43), (r * 0.7, -0.43), (r * 0.95, -0.42), (r, -0.4), (r, 0.4), (r * 0.95, 0.42),
                                   (r * 0.7, 0.43), (0.001, 0.43)], "cabin_fabric", 14, (0, 0, 0))
        roll.rotation_euler.x = math.pi / 2
        roll.location = (x + s * 0.005, 0, 0.6 - r)
        parts.append(roll)
    return C.smooth(C.join(name, parts), 40)


def drawer_front(tag, w, h, at, wood="cabin_wood"):
    """A drawer's or a door's front a hair proud, and its brushed pull."""
    x, y, z = at
    return [C.box(f"df{tag}", (w, 0.015, h), (x, y - 0.0075, z), wood, bevel=0.006, segments=1),
            C.box(f"dp{tag}", (min(0.14, w * 0.4), 0.018, 0.016), (x, y - 0.024, z + h * 0.25), "trim", bevel=0.005, segments=1)]


def nightstand():
    w, d, h = 0.42, 0.42, 0.5
    parts = [C.box("plinth", (w - 0.06, d - 0.06, 0.06), (0, 0.02, 0.03), "desk_wood"),
             C.box("body", (w - 0.02, d - 0.02, h - 0.09), (0, 0.01, 0.06 + (h - 0.09) / 2), "cabin_wood", bevel=0.01, segments=1),
             C.box("top", (w, d, 0.03), (0, 0, h - 0.015), "cabin_wood", bevel=0.01, segments=2)]
    parts += drawer_front("a", w - 0.06, 0.15, (0, -d / 2 + 0.01, 0.17))
    parts += drawer_front("b", w - 0.06, 0.15, (0, -d / 2 + 0.01, 0.34))
    return C.smooth(C.join("quarters_nightstand", parts), 35)


def coffee_table():
    w, d, h = 1.1, 0.6, 0.38
    parts = [C.box("top", (w, d, 0.04), (0, 0, h - 0.02), "cabin_wood", bevel=0.015, segments=2),
             C.box("shelf", (w - 0.14, d - 0.1, 0.025), (0, 0, 0.1), "desk_wood", bevel=0.006, segments=1)]
    for s in (-1, 1):
        parts.append(C.box(f"end{s}", (0.05, d - 0.06, h - 0.04), (s * (w / 2 - 0.08), 0, (h - 0.04) / 2), "cabin_wood", bevel=0.01, segments=1))
    # an inlaid band of the darker wood across the top
    parts.append(C.box("inlay", (w - 0.1, 0.06, 0.002), (0, 0, h + 0.0005), "desk_wood"))
    return C.smooth(C.join("quarters_coffee_table", parts), 35)


def side_table():
    return C.smooth(C.join("quarters_side_table", [
        turned("foot", [(0.001, 0), (0.2, 0), (0.2, 0.012), (0.17, 0.03), (0.001, 0.03)], "bronze", 24, (0, 0, 0)),
        turned("stem", [(0.03, 0.03), (0.045, 0.05), (0.035, 0.1), (0.032, 0.5), (0.06, 0.53)], "bronze", 12, (0, 0, 0)),
        turned("top", [(0.001, 0.53), (0.27, 0.53), (0.285, 0.545), (0.28, 0.57), (0.001, 0.57)], "cabin_wood", 32, (0, 0, 0))]), 35)


def credenza():
    w, d, h = 1.8, 0.4, 0.5
    parts = [C.box("plinth", (w - 0.06, d - 0.06, 0.07), (0, 0.02, 0.035), "desk_wood"),
             C.box("body", (w - 0.02, d - 0.02, h - 0.1), (0, 0.01, 0.07 + (h - 0.1) / 2), "cabin_wood", bevel=0.01, segments=1),
             C.box("top", (w, d, 0.03), (0, 0, h - 0.015), "cabin_wood", bevel=0.01, segments=2)]
    dw = (w - 0.08) / 3
    for i in range(3):
        parts += drawer_front(f"c{i}", dw - 0.012, h - 0.16, (-w / 2 + 0.04 + dw * (i + 0.5), -d / 2 + 0.01, 0.07 + (h - 0.1) / 2))
    return C.smooth(C.join("quarters_credenza", parts), 35)


def desk():
    """1.5 across, 0.8 deep, the top at 0.775; its sitter at -Y."""
    w, d, t = 1.5, 0.8, 0.775
    parts = [C.box("top", (w, d, 0.05), (0, 0, t - 0.025), "cabin_wood", bevel=0.015, segments=2),
             C.box("modesty", (w - 0.16, 0.025, 0.45), (0, d / 2 - 0.08, t - 0.05 - 0.225), "cabin_wood", bevel=0.006, segments=1),
             C.box("drawer", (0.6, d - 0.2, 0.08), (0, 0.02, t - 0.09), "cabin_wood", bevel=0.008, segments=1)]
    for s in (-1, 1):
        parts.append(C.box(f"end{s}", (0.05, d - 0.04, t - 0.05), (s * (w / 2 - 0.04), 0, (t - 0.05) / 2), "cabin_wood", bevel=0.01, segments=1))
    parts += drawer_front("dd", 0.56, 0.06, (0, -d / 2 + 0.11, t - 0.09))
    # the screen's stand (the page's screen, 0.55 x 0.34 at 1.02, kept over
    # it 0.28 behind the middle)
    parts += [C.box("sfoot", (0.22, 0.14, 0.012), (0, 0.3, t + 0.006), "console", bevel=0.004, segments=1),
              C.box("sneck", (0.05, 0.025, 0.2), (0, 0.31, t + 0.1), "console", bevel=0.006, segments=1)]
    # books lying at the +X back corner
    z = t
    for i, (hh, m) in enumerate(((0.05, "bridge_leather"), (0.04, "duvet"), (0.035, "rail_wood"))):
        b = C.box(f"book{i}", (0.22, 0.16, hh), (0.5, 0.1, z + hh / 2), m, bevel=0.004, segments=1)
        b.rotation_euler.z = 0.08 * (i - 1)
        parts.append(b)
        z += hh
    return C.smooth(C.join("quarters_desk", parts), 35)


def desk_chair():
    """deskChair()'s measures: the seat's top at 0.51, the back 0.44 x 0.5
    behind it leaning 0.1; a five-star base on casters."""
    parts = [turned("column", [(0.03, 0.06), (0.03, 0.3), (0.022, 0.32), (0.022, 0.43)], "trim", 10, (0, 0, 0)),
             turned("hub", [(0.001, 0.05), (0.05, 0.05), (0.045, 0.09), (0.001, 0.09)], "console", 10, (0, 0, 0)),
             C.box("pan", (0.44, 0.44, 0.03), (0, 0, 0.445), "console", bevel=0.01, segments=1),
             C.box("seat", (0.46, 0.46, 0.065), (0, 0, 0.475), "cabin_fabric", bevel=0.028, segments=3)]
    for k in range(5):
        a = 2 * math.pi * k / 5 + math.pi / 2
        arm = C.box(f"star{k}", (0.24, 0.04, 0.03), (0.12 * math.cos(a), 0.12 * math.sin(a), 0.06), "console", bevel=0.008, segments=1)
        arm.rotation_euler.z = a
        parts.append(arm)
        parts.append(turned(f"caster{k}", [(0.001, 0), (0.022, 0), (0.024, 0.02), (0.018, 0.04), (0.001, 0.045)], "black", 8,
                            (0.235 * math.cos(a), 0.235 * math.sin(a), 0)))
    back = [C.box("bshell", (0.44, 0.03, 0.5), (0, 0.235, 0.78), "console", bevel=0.012, segments=2),
            C.box("bpad", (0.42, 0.05, 0.46), (0, 0.205, 0.78), "cabin_fabric", bevel=0.022, segments=3),
            C.box("spine", (0.05, 0.03, 0.28), (0, 0.255, 0.53), "console", bevel=0.008, segments=1)]
    for o in back:
        o.rotation_euler.x = -0.1
    parts += back
    return C.smooth(C.join("quarters_desk_chair", parts), 35)


def lamp(name, h, shade_r, floor):
    """The base and the stem to the shade's middle at `h` (the page's shade
    and bulb, lit, kept over them); a floor lamp's weighted foot."""
    if floor:
        prof = [(0.001, 0), (0.16, 0), (0.165, 0.015), (0.15, 0.035), (0.05, 0.05), (0.03, 0.07), (0.001, 0.07)]
    else:
        r = shade_r * 0.8
        prof = [(0.001, 0), (r, 0), (r, 0.012), (r * 0.6, 0.04), (0.03, 0.07), (0.028, 0.12), (0.04, 0.16), (0.022, 0.2), (0.001, 0.2)]
    parts = [turned("base", prof, "bronze", 20, (0, 0, 0)),
             turned("stem", [(0.016, 0.05), (0.016, h - shade_r * 0.5), (0.03, h - shade_r * 0.45), (0.03, h - shade_r * 0.35),
                             (0.012, h - shade_r * 0.3), (0.001, h - shade_r * 0.3)], "bronze", 10, (0, 0, 0))]
    if floor:
        parts.append(turned("collar", [(0.022, 0.75), (0.026, 0.77), (0.026, 0.83), (0.022, 0.85)], "trim", 10, (0, 0, 0)))
    return C.smooth(C.join(name, parts), 35)


# The generated sofa and double bed (gen.py, fit.py: deck-remodel.md slice
# 9, on the captain's word 2026-10-30), each already fitted to its
# stand-in's box; Tripo's face_limit 2400 keeps them under the 3 k budget.
GEN_BUDGETS = {"quarters_sofa": 3000, "quarters_bed": 3000}


def generated(src):
    """{prop: low}, {low: original} and the licence files of the props in
    build.sh's folder, as bridge.py's chairs; the narrow bed, when the double
    is generated, is its copy at 1.2 of 1.6 across (both copies, so the bake's
    rays still meet)."""
    lic = C.pack_licences(src)
    lows, sources = C.import_pack(src, "quarters", budgets=GEN_BUDGETS)
    got = {lo.name: lo for lo in lows}
    if "quarters_bed" in got:
        lo, hi = got["quarters_bed"], sources[got["quarters_bed"]]
        nlo, nhi = lo.copy(), hi.copy()
        nlo.data, nhi.data = lo.data.copy(), hi.data.copy()
        C.link(nlo)
        C.link(nhi)
        nlo.name = nlo.data.name = "quarters_bed_narrow"
        nhi.name = "quarters_bed_narrow__src"
        for o in (nlo, nhi):
            for v in o.data.vertices:
                v.co.x *= 1.2 / 1.6
        got["quarters_bed_narrow"] = nlo
        sources[nlo] = nhi
    return got, sources, lic


out, args = C.out_dir()
C.clean_scene()
# build.sh passes the generated props' folder when it has them; one not in it
# (the public repo, a box without the NAS) is the scripted one, as before
gen, sources, lic = generated(args[0]) if args else ({}, None, None)
made = C.finish_props([p for p in [
    None if "quarters_bed" in gen else bed("quarters_bed", 1.6),
    None if "quarters_bed_narrow" in gen else bed("quarters_bed_narrow", 1.2),
    None if "quarters_sofa" in gen else sofa("quarters_sofa", 2.3, 0.17), sofa("quarters_armchair", 0.95, 0.15),
    nightstand(), coffee_table(), side_table(), credenza(), desk(), desk_chair(),
    lamp("quarters_table_lamp", 0.34, 0.11, False), lamp("quarters_floor_lamp", 1.45, 0.2, True),
    C.wardrobe("quarters_wardrobe"),
    C.padd_shelf("quarters_padd_shelf_a", C.shelf_books("a")), C.padd_shelf("quarters_padd_shelf_b", C.shelf_books("b"))] if p])
props = list(gen.values()) + made
C.finish_room("quarters", props, size=1024, sources=sources)
if lic:
    C.write_licences(lic, os.path.join(out, "quarters.LICENSE.txt"))
