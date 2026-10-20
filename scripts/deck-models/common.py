"""Shared by every deck model script: the palette, the modelling helpers, the
atlas bake and the export (docs/design/deck-pipeline.md).

A room script (bridge.py) builds its props as Blender objects, one object per
prop, named by the prop: the page finds a prop by that name. Each object is
in metres, +Z up (glTF's +Y once exported), its origin on the floor at the
middle of its footprint and its front toward Blender's -Y (glTF's +Z, the
deck's convention, docs/design/deck-style.md part 4). Then `finish_room`
gives every prop UVs in one shared atlas, bakes their materials into three
images (base colour, normal, and AO/roughness/metal packed as ORM, as glTF
does), swaps every material for the one atlas material and writes
OUT/<room>.glb and OUT/<room>_{base,norm,orm}.png. scripts/deck-model-
assets.mjs then cleans the glb and turns the pngs into the webp the page
loads.

Blender 4.3, run headless:  blender -b --factory-startup -P scripts/deck-models/<room>.py -- OUT_DIR
(scripts/deck-models/build.sh runs every room, niced, and the cleaner).
"""
import math
import os
import sys

import bmesh
import bpy
import numpy as np

# ---------------------------------------------------------------- palette
# One palette for every room: the hexes of docs/design/deck-style.md part 1,
# so a model baked here sits beside the code-built surfaces in deck.html
# without a seam. name: (sRGB hex, roughness, metalness, detail) - detail is
# the surface's fine relief, baked into the normal map (see `_detail`).
PALETTE = {
    "putty": (0xd6c4a6, 0.8, 0.0, None),
    "wainscot": (0x6a5646, 0.7, 0.0, None),
    "console": (0x2a2624, 0.5, 0.3, "brushed"),
    "trim": (0x958c80, 0.45, 0.5, "brushed"),
    "black": (0x161514, 0.6, 0.1, None),
    "bridge_leather": (0x5e1f1c, 0.45, 0.0, "pebble"),
    "bridge_piping": (0x3a1210, 0.4, 0.0, None),
    "rail_wood": (0x5a3a28, 0.35, 0.0, "grain"),
    "desk_wood": (0x4a3022, 0.3, 0.0, "grain"),
    "lounge_leather": (0x1c1a1a, 0.45, 0.0, "pebble"),
    "sofa": (0x6a6460, 0.85, 0.0, "weave"),
    "bronze": (0x8a6a44, 0.35, 0.8, "brushed"),
    "lab_grey": (0x9aa0a8, 0.5, 0.3, None),
    "sick_white": (0xe8e6e0, 0.35, 0.0, None),
    "bed_pad": (0x7a8ea0, 0.85, 0.0, "weave"),
}


def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_rgb(h):
    return tuple(srgb_to_linear(((h >> s) & 255) / 255) for s in (16, 8, 0))


def out_dir():
    """OUT_DIR from the command line (after Blender's own `--`)."""
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if not argv:
        sys.exit("usage: blender -b -P script.py -- OUT_DIR")
    os.makedirs(argv[0], exist_ok=True)
    return argv[0], argv[1:]


def clean_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)


_mats = {}


def mat(name):
    """The palette's material `name`: a Principled BSDF with its colour,
    roughness and metalness, and its detail as a bump (procedural, in object
    space, so it needs no UVs and bakes the same whatever the unwrap)."""
    if name in _mats:
        return _mats[name]
    hexv, rough, metal, detail = PALETTE[name]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*hex_rgb(hexv), 1)
    bsdf.inputs["Roughness"].default_value = rough
    bsdf.inputs["Metallic"].default_value = metal
    if detail:
        _detail(nt, bsdf, detail)
    _mats[name] = m
    return m


def _detail(nt, bsdf, kind):
    # Relief only, kept shallow: the deck's own generated textures carry the
    # same families (T.pebble, T.brushed, T.grain) and a model must not shout
    # beside them. Scales are in metres (object coordinates).
    tc = nt.nodes.new("ShaderNodeTexCoord")
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.002
    if kind == "pebble":
        t = nt.nodes.new("ShaderNodeTexVoronoi")
        t.feature = "SMOOTH_F1"
        t.inputs["Scale"].default_value = 260
        nt.links.new(tc.outputs["Object"], t.inputs["Vector"])
        nt.links.new(t.outputs["Distance"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.35
    elif kind == "brushed":
        mp = nt.nodes.new("ShaderNodeMapping")
        mp.inputs["Scale"].default_value = (1, 1, 60)
        t = nt.nodes.new("ShaderNodeTexNoise")
        t.inputs["Scale"].default_value = 30
        nt.links.new(tc.outputs["Object"], mp.inputs["Vector"])
        nt.links.new(mp.outputs["Vector"], t.inputs["Vector"])
        nt.links.new(t.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.12
    elif kind == "grain":
        t = nt.nodes.new("ShaderNodeTexWave")
        t.inputs["Scale"].default_value = 18
        t.inputs["Distortion"].default_value = 6
        nt.links.new(tc.outputs["Object"], t.inputs["Vector"])
        nt.links.new(t.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.15
    elif kind == "weave":
        t = nt.nodes.new("ShaderNodeTexNoise")
        t.inputs["Scale"].default_value = 400
        nt.links.new(tc.outputs["Object"], t.inputs["Vector"])
        nt.links.new(t.outputs["Fac"], bump.inputs["Height"])
        bump.inputs["Strength"].default_value = 0.25
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


# ---------------------------------------------------------------- modelling
def link(ob):
    bpy.context.collection.objects.link(ob)
    return ob


def activate(ob):
    for o in bpy.context.selected_objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    return ob


def box(name, size, at, material, bevel=0.0, segments=3):
    """A box `size` (x, y, z) with its centre at `at`; `bevel` rounds its
    edges (a real edge catches a highlight, a knife edge never does)."""
    bm = bmesh.new()
    bmesh.ops.create_cube(bm, size=1.0)
    for v in bm.verts:
        v.co.x *= size[0]
        v.co.y *= size[1]
        v.co.z *= size[2]
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new(name, me))
    ob.location = at
    ob.data.materials.append(mat(material))
    if bevel:
        modifier(ob, "BEVEL", width=bevel, segments=segments, limit_method="ANGLE")
    return ob


def modifier(ob, kind, **kw):
    m = ob.modifiers.new(kind.lower(), kind)
    for k, v in kw.items():
        setattr(m, k, v)
    return m


def apply_all(ob):
    activate(ob)
    for m in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=m.name)
    return ob


def lathe(name, profile, material, steps=24, at=(0, 0, 0)):
    """Turned about Z from `profile`, [(r, z), ...] bottom to top: a
    pedestal, a vase, a column. Built ring by ring (the Screw modifier left
    stray faces where a profile starts or ends on the axis); a point with
    r 0 is a pole, a cap's centre."""
    bm = bmesh.new()
    rings = []
    for r, z in profile:
        if r <= 1e-4:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * k / steps), r * math.sin(2 * math.pi * k / steps), z))
                          for k in range(steps)])
    for a, b in zip(rings, rings[1:]):
        for k in range(steps):
            k1 = (k + 1) % steps
            if len(a) == 1 and len(b) == 1:
                continue
            if len(a) == 1:
                bm.faces.new((a[0], b[k1], b[k]))
            elif len(b) == 1:
                bm.faces.new((a[k], a[k1], b[0]))
            else:
                bm.faces.new((a[k], a[k1], b[k1], b[k]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new(name, me))
    ob.location = at
    ob.data.materials.append(mat(material))
    return ob


def pad(name, size, at, material, round_=0.35, levels=1):
    """A cushion: a bevelled box under a Subdivision Surface, so its edges
    roll like something stuffed. The bevel's two segments hold the shape:
    over a plain box the subdivision shrinks a thin pad to a lozenge."""
    ob = box(name, size, at, material, bevel=min(size) * round_ * 0.5, segments=2)
    modifier(ob, "SUBSURF", levels=levels, render_levels=levels)
    return ob


def tube(name, points, radius, material, closed=False, res=6):
    """A round section swept along a poly line (a Curve with a bevel depth):
    piping on a seam, a rail, a cable."""
    cu = bpy.data.curves.new(name, "CURVE")
    cu.dimensions = "3D"
    cu.bevel_depth = radius
    cu.bevel_resolution = max(1, res // 4)
    sp = cu.splines.new("POLY")
    sp.points.add(len(points) - 1)
    for p, c in zip(sp.points, points):
        p.co = (*c, 1)
    sp.use_cyclic_u = closed
    ob = link(bpy.data.objects.new(name, cu))
    ob.data.materials.append(mat(material))
    activate(ob)
    bpy.ops.object.convert(target="MESH")
    return bpy.context.view_layer.objects.active


def smooth(ob, angle=40):
    """Smooth shading, split at edges sharper than `angle` degrees."""
    activate(ob)
    bpy.ops.object.shade_smooth_by_angle(angle=math.radians(angle))
    return ob


def join(name, parts):
    """The parts as one object `name` (one prop), modifiers applied, their
    materials kept as slots until the bake."""
    for p in parts:
        if p.type != "MESH":
            activate(p)
            bpy.ops.object.convert(target="MESH")
        apply_all(p)
    activate(parts[0])
    for p in parts[1:]:
        p.select_set(True)
    bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    ob.name = ob.data.name = name
    return ob


def floor_origin(ob):
    """The origin on the floor at the footprint's middle (part 4's rule)."""
    activate(ob)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    vs = np.array([v.co[:] for v in ob.data.vertices])
    lo, hi = vs.min(0), vs.max(0)
    shift = (-(lo[0] + hi[0]) / 2, -(lo[1] + hi[1]) / 2, -lo[2])
    for v in ob.data.vertices:
        v.co.x += shift[0]
        v.co.y += shift[1]
        v.co.z += shift[2]
    ob.location = (0, 0, 0)
    return ob


def tris(ob):
    return sum(len(p.vertices) - 2 for p in ob.data.polygons)


# ---------------------------------------------------------------- atlas
def unwrap(objs, margin=0.004):
    """One UV map, "atlas", over every prop, the islands scaled to their
    area in the world (so a texel is the same size on every prop) and packed
    into the one square."""
    for ob in objs:
        while ob.data.uv_layers:
            ob.data.uv_layers.remove(ob.data.uv_layers[0])
        ob.data.uv_layers.new(name="atlas")
    _edit(objs)
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=margin, scale_to_bounds=False)
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")


def _edit(objs):
    bpy.ops.object.mode_set(mode="OBJECT") if bpy.context.object and bpy.context.object.mode != "OBJECT" else None
    activate(objs[0])
    for o in objs[1:]:
        o.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")


def _image(name, size, data):
    im = bpy.data.images.new(name, size, size, alpha=False, float_buffer=False)
    im.colorspace_settings.name = "Non-Color" if data else "sRGB"
    im.generated_color = (0.5, 0.5, 1, 1) if name.endswith("norm") else (0, 0, 0, 1)
    return im


def _targets(mats, im):
    """Point the bake at `im`: every material gets an image node, active.
    The node is connected to nothing, so it changes no shading."""
    for m in mats:
        nt = m.node_tree
        n = nt.nodes.get("__bake") or nt.nodes.new("ShaderNodeTexImage")
        n.name = "__bake"
        n.image = im
        nt.nodes.active = n


def _as_emission(mats, socket):
    """Route a Principled input (its link, or its value) to the emission, so
    an EMIT bake records it whatever the lighting: base colour and metalness
    have no bake type of their own that is not lit or weighted."""
    undo = []
    for m in mats:
        nt = m.node_tree
        b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        src, em = b.inputs[socket], b.inputs["Emission Color"]
        old = (em.default_value[:], b.inputs["Emission Strength"].default_value, [l.from_socket for l in em.links])
        for l in list(em.links):
            nt.links.remove(l)
        if src.links:
            nt.links.new(src.links[0].from_socket, em)
        else:
            v = src.default_value
            em.default_value = (v, v, v, 1) if isinstance(v, float) else v[:]
        b.inputs["Emission Strength"].default_value = 1.0
        undo.append((nt, b, old))
    return undo


def _restore(undo):
    for nt, b, (col, strength, links) in undo:
        em = b.inputs["Emission Color"]
        for l in list(em.links):
            nt.links.remove(l)
        for s in links:
            nt.links.new(s, em)
        em.default_value = col
        b.inputs["Emission Strength"].default_value = strength


def _px(im):
    a = np.empty(im.size[0] * im.size[1] * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(-1, 4)


def bake(objs, room, out, size=1024, samples=16, sources=None):
    """Bake every prop's materials into the room's three images. `sources`
    (pack.py) maps a low prop to the original it was decimated from, and the
    bake is then from the original onto the low one, its relief carried in
    the normal map."""
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.use_denoising = False
    # Islands spread far past their edges: the gaps between them are black
    # (no AO, no colour), and a mip level or two down on a phone the black
    # bleeds in as dark cracks along every seam. A sixteenth of the atlas
    # fills nearly every gap.
    sc.render.bake.margin = max(16, size // 16)
    sc.render.bake.margin_type = "EXTEND"
    sc.render.bake.use_clear = False
    sc.render.bake.normal_space = "TANGENT"
    mats = {s.material for o in list(objs) + list((sources or {}).values()) for s in o.material_slots if s.material}
    sources = sources or {}
    targets = objs
    if len(objs) > 1:
        # Several props share the atlas: bake them as one. Baked one by one,
        # each prop's margin (above) painted over the islands of the props
        # baked before it (the bridge's chair came out grey under the
        # consoles'). The proxy is a copy of every prop, each moved 20 m
        # from the last: they are all built about the origin, and on top of
        # one another each would shade the others' ambient occlusion. A
        # pack's props are in it too (their AO is their own, as below), and
        # are baked again from their originals after it.
        copies = []
        for i, o in enumerate(objs):
            c = o.copy()
            c.data = o.data.copy()
            link(c)
            c.location.x += 20 * (i + 1)
            copies.append(c)
        activate(copies[0])
        for c in copies[1:]:
            c.select_set(True)
        bpy.ops.object.join()
        targets = [bpy.context.view_layer.objects.active]
        for o in objs:
            o.hide_render = True
    imgs = {k: _image(f"{room}_{k}", size, k != "base") for k in ("base", "norm", "rough", "metal", "ao")}

    # Samples per pass: a flat value (colour, metal, roughness) needs one, a
    # bump a few for its antialiasing, the AO most; with the AO at 24 the
    # whole bake was four minutes of the box's CPU, this way about one.
    def run(kind, im, n=1, **kw):
        sc.cycles.samples = n
        _targets(mats, im)
        sc.render.bake.use_selected_to_active = False
        sc.render.bake.margin = margin
        for o in targets:
            activate(o)
            bpy.ops.object.bake(type=kind, **kw)
        if kind == "AO" or not sources:
            return
        # then each pack prop from its original, over what the proxy gave
        # its islands (its decimated copy's own materials, sampled through
        # the atlas's coordinates: wrong, but only the margin keeps them).
        # A margin of two pixels, inside the gap pack_islands leaves: a
        # full one here would paint over the islands baked before it.
        sc.render.bake.use_selected_to_active = True
        sc.render.bake.margin = max(1, size // 512)
        for lo, hi in sources.items():
            lo.hide_render = False
            activate(lo)
            hi.select_set(True)
            bpy.ops.object.bake(type=kind, **kw)
            lo.hide_render = len(objs) > 1

    margin = sc.render.bake.margin
    if sources:
        # rays start this far out from the low surface and look this far: a
        # vase taken from 10k triangles to a few hundred strays ~1-2 cm from
        # its original, and a ray that misses bakes black (the first cut,
        # at 1 and 5 cm, left the ceramic vase in black shards)
        sc.render.bake.cage_extrusion = 0.03
        sc.render.bake.max_ray_distance = 0.1
    und = _as_emission(mats, "Base Color")
    run("EMIT", imgs["base"])
    _restore(und)
    und = _as_emission(mats, "Metallic")
    run("EMIT", imgs["metal"])
    _restore(und)
    run("ROUGHNESS", imgs["rough"])
    run("NORMAL", imgs["norm"], 4)
    # ambient occlusion only from the prop itself (the room's own contact
    # shadow and, on desktop, GTAO, do the rest): a seat's underside, the
    # creases between cushions
    # (for a pack, from the decimated prop alone: baked from the original,
    # the low copy around it occludes it and the AO came out in dark cracks)
    for hi in sources.values():
        hi.hide_render = True
    run("AO", imgs["ao"], samples)
    if targets is not objs:
        for o in objs:
            o.hide_render = False
        bpy.data.objects.remove(targets[0])

    orm = _image(f"{room}_orm", size, True)
    p = np.ones((size * size, 4), np.float32)
    p[:, 0] = _px(imgs["ao"])[:, 0] * 0.8 + 0.2   # never quite black: the AO is a hint
    p[:, 1] = _px(imgs["rough"])[:, 0]
    p[:, 2] = _px(imgs["metal"])[:, 0]
    orm.pixels.foreach_set(p.ravel())
    for k, im in (("base", imgs["base"]), ("norm", imgs["norm"]), ("orm", orm)):
        im.filepath_raw = os.path.join(out, f"{room}_{k}.png")
        im.file_format = "PNG"
        im.save()


def finish_room(room, props, size=1024, sources=None, samples=16):
    """Unwrap, bake, one material, export: OUT/<room>.glb and its pngs."""
    out, _ = out_dir()
    unwrap(props)
    bake(props, room, out, size, samples, sources)
    atlas = bpy.data.materials.new(f"{room}_atlas")
    for o in props:
        o.data.materials.clear()
        o.data.materials.append(atlas)
    for o in list(bpy.data.objects):
        if o not in props:
            bpy.data.objects.remove(o)
    total = 0
    for o in props:
        print(f"[deck-models] {room}/{o.name}: {tris(o)} triangles")
        total += tris(o)
    print(f"[deck-models] {room}: {len(props)} props, {total} triangles")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.export_scene.gltf(filepath=os.path.join(out, f"{room}.glb"), export_format="GLB", use_selection=True,
                              export_image_format="NONE", export_yup=True, export_apply=True,
                              export_texcoords=True, export_normals=True, export_tangents=True,
                              export_attributes=False, export_extras=False, export_animations=False)


# ---------------------------------------------------------------- packs
def pack_licences(src):
    """Every LICENSE* or LICENCE* file under `src`; none is a refusal: a
    pack whose terms are not on disk does not ship."""
    import glob
    lic = [f for f in sorted(glob.glob(os.path.join(src, "**", "*"), recursive=True))
           if os.path.isfile(f) and os.path.basename(f).lower().startswith(("license", "licence"))]
    if not lic:
        sys.exit(f"[deck-models] {src}: no LICENSE file, so not converted (docs/design/deck-pipeline.md)")
    return lic


def write_licences(lic, path):
    """The pack's licence files one after another (a folder of single-asset
    downloads has one each): OUT/<room>.LICENSE.txt, which the cleaner folds
    into lcars-ui/deck/LICENSE.txt."""
    with open(path, "w") as w:
        w.write("\n".join(open(f).read().strip() + "\n" for f in lic))


def import_pack(src, room, each=1500, budgets=None):
    """A downloaded pack's props (pack.py's, or a room script's own beside
    them): every .glb, .gltf or .obj under `src` one prop, named by its file,
    its meshes joined, set on the floor at its footprint's middle and
    decimated to its budget (`budgets[prop]`, else `each`). Returns the
    decimated props and {low: original}, `finish_room`'s `sources`: the bake
    is from the original onto the low copy, so the detail the decimation
    took is carried in the normal map, and the pack's own textures end in
    the room's one atlas."""
    import glob
    files = sorted(f for f in glob.glob(os.path.join(src, "**", "*"), recursive=True)
                   if f.lower().endswith((".glb", ".gltf", ".obj")))
    if not files:
        sys.exit(f"[deck-models] {src}: no .glb, .gltf or .obj in it")
    lows, sources = [], {}
    for f in files:
        prop = os.path.splitext(os.path.basename(f))[0]
        before = set(bpy.data.objects)
        if f.lower().endswith(".obj"):
            bpy.ops.wm.obj_import(filepath=f)
        else:
            bpy.ops.import_scene.gltf(filepath=f)
        new = [o for o in bpy.data.objects if o not in before]
        meshes = [o for o in new if o.type == "MESH"]
        for o in new:
            if o.type != "MESH":
                # empties and cameras a pack's scene carries: the meshes keep
                # their world placement when their parents go
                for c in o.children:
                    mw = c.matrix_world.copy()
                    c.parent = None
                    c.matrix_world = mw
        for o in new:
            if o.type != "MESH":
                bpy.data.objects.remove(o)
        hi = join(prop + "__src", meshes)
        floor_origin(hi)
        lo = hi.copy()
        lo.data = hi.data.copy()
        link(lo)
        lo.name = lo.data.name = prop
        want = int((budgets or {}).get(prop, each))
        have = tris(lo)
        # a collapse stops short of a steep ratio (UV seams and borders it
        # will not cross), so again, up to three times
        for _ in range(3):
            if tris(lo) <= want * 1.05:
                break
            modifier(lo, "DECIMATE", ratio=want / tris(lo), use_collapse_triangulate=True)
            apply_all(lo)
        # a collapse leaves faces turned inside out, and a flipped face bakes
        # its AO and normal from inside the prop (dark streaks on the vase)
        activate(lo)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.normals_make_consistent(inside=False)
        bpy.ops.object.mode_set(mode="OBJECT")
        smooth(lo)
        print(f"[deck-models] {room}/{prop}: {have} -> {tris(lo)} triangles")
        lows.append(lo)
        sources[lo] = hi
    return lows, sources


# ---------------------------------------------------------------- profiles
# bridge.py's profile helpers, here once sickbay.py and lab.py wanted them
# too (bridge.py keeps its own copies: its numbers were measured with them).
def mesh_of(name, bm, material, bevel=0.0, segments=2):
    """A bmesh as an object `name` in the palette's `material`."""
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = link(bpy.data.objects.new(name, me))
    ob.data.materials.append(mat(material))
    if bevel:
        modifier(ob, "BEVEL", width=bevel, segments=segments, limit_method="ANGLE")
    return ob


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
    return mesh_of(name, bm, material, bevel, segments)


def rrect(w, d, r, k=3, cy=0.0):
    """A rounded rectangle's outline, w across x, d along y, centred on
    (0, cy): 4 * (k + 1) points whatever its size, so two of them loft."""
    r = min(r, w / 2 - 1e-3, d / 2 - 1e-3)
    pts = []
    for cx, cyy, a0 in ((w / 2 - r, d / 2 - r, 0), (-w / 2 + r, d / 2 - r, 90), (-w / 2 + r, -d / 2 + r, 180), (w / 2 - r, -d / 2 + r, 270)):
        for i in range(k + 1):
            a = math.radians(a0 + 90 * i / k)
            pts.append((cx + r * math.cos(a), cy + cyy + r * math.sin(a)))
    return pts


def loft(name, sections, material, r=0.05, k=3):
    """Rounded rectangles [(z, w, d, cy), ...] bottom to top, skinned and
    capped: a pedestal that flares at the floor, a curved base."""
    bm = bmesh.new()
    rings = [[bm.verts.new((x, y, z)) for x, y in rrect(w, d, r, k, cy=cy)] for z, w, d, cy in sections]
    n = len(rings[0])
    for a, b in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            bm.faces.new((a[i], a[j], b[j], b[i]))
    bm.faces.new(rings[0])
    bm.faces.new(rings[-1][::-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_of(name, bm, material)


def placed(objs, M):
    """`objs` moved by the matrix M (a frame of their own: a tilted top)."""
    bpy.context.view_layer.update()
    for o in objs:
        o.matrix_world = M @ o.matrix_world
    return objs


def finish_props(props):
    """Transforms applied, and the ngon caps of prisms and lofts cut into
    triangles: the exporter's tangents (MikkTSpace) take only triangles and
    quads."""
    for p in props:
        activate(p)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        bm = bmesh.new()
        bm.from_mesh(p.data)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if len(f.verts) > 4])
        bm.to_mesh(p.data)
        bm.free()
    return props


# ---------------------------------------------------------------- unwrap hints
# A room script may name a prop whose smart projection does it a disservice:
# `UNWRAP_HINTS[prop] = ("cylinder", cuts)` for a turned one (`lathe`) seen
# close, whose relief runs round it (the concourse's bronze column). Smart
# project cuts a cylinder into strips at odd angles, which the packer turns
# again, so a brushed line crosses the texels aslant and the bake aliases it
# into blotches. This unrolls the prop's side faces instead: u round it (the
# angle times the radius), v along its profile (the arc length, so a flare
# keeps its texels square), each band between two `cuts` heights an island
# of its own so a tall shaft packs as a few strips, not one the square must
# fit. Its near-horizontal faces (caps, steps) keep the smart projection. A
# profile that rises (z never falls along it) is assumed, as a column's.
UNWRAP_HINTS = {}
_smart_unwrap = unwrap


def unwrap(objs, margin=0.004):  # noqa: F811 - the hinted unwrap over the one above
    _smart_unwrap(objs, margin)
    hinted = [o for o in objs if UNWRAP_HINTS.get(o.name, ("",))[0] == "cylinder"]
    if not hinted:
        return
    for ob in hinted:
        me, cuts = ob.data, UNWRAP_HINTS[ob.name][1]
        uv = me.uv_layers["atlas"].data
        side = [p for p in me.polygons if abs(p.normal.z) < 0.7]
        ring = {}
        for p in side:
            for vi in p.vertices:
                co = me.vertices[vi].co
                ring.setdefault(round(co.z, 4), math.hypot(co.x, co.y))
        zs = sorted(ring)
        arc = {zs[0]: 0.0}
        for a, b in zip(zs, zs[1:]):
            arc[b] = arc[a] + math.hypot(b - a, ring[b] - ring[a])
        for p in side:
            th = [math.atan2(me.vertices[v].co.y, me.vertices[v].co.x) for v in p.vertices]
            if max(th) - min(th) > math.pi:     # the face across the seam
                th = [t + 2 * math.pi if t < 0 else t for t in th]
            band = sum(p.center.z > c for c in cuts)
            for li, t in zip(p.loop_indices, th):
                co = me.vertices[me.loops[li].vertex_index].co
                uv[li].uv = (t * math.hypot(co.x, co.y) + 40 * band, arc[round(co.z, 4)])
    # every island again to its area in the world, and packed again
    _edit(objs)
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.uv.select_all(action="SELECT")
    bpy.ops.uv.average_islands_scale()
    bpy.ops.uv.pack_islands(margin=margin, rotate=True)
    bpy.ops.object.mode_set(mode="OBJECT")


# ---------------------------------------------------------------- the sofa
# The deck's one upholstered seat, after `sofa(x, z, rot, w)` in deck.html
# (built at its measures, so its seats and pillows fit): a base w x 0.86 to
# 0.33, the seat cushions to 0.46 (two over 1.2 wide, one under, as the
# stand-in seats its sitters) 0.66 deep from 0.07 before the middle, a back
# 0.2 deep from 0.32 to 0.84 at its rear, arms `aw` wide to 0.6. Its front
# is -Y (glTF's +Z). Two rooms' atlases take it (lounge.py, readyroom.py):
# a prop from another room's glb is another material in a room, a call,
# where a few hundred texels of the room's own atlas are free. The cushions
# are bevelled boxes, not `pad`s: six subdivided pads alone were ~3 k
# triangles, twice furniture's 1.5 k, and three bevel segments roll an edge
# as well at a sofa's distance.
def sofa(name, w, aw=0.17):
    seats = 2 if w > 1.2 else 1
    sw = (w - 2 * aw) / seats
    parts = [box("plinth", (w - 0.12, 0.74, 0.07), (0, -0.02, 0.035), "black"),
             box("base", (w - 2 * aw + 0.02, 0.84, 0.25), (0, 0, 0.195), "sofa", bevel=0.025, segments=1),
             box("frame", (w - 0.02, 0.17, 0.52), (0, 0.345, 0.58), "sofa", bevel=0.03, segments=2)]
    for i in range(seats):
        x = (i + 0.5 - seats / 2) * sw
        parts.append(box(f"seat{i}", (sw - 0.015, 0.68, 0.15), (x, -0.07, 0.39), "sofa", bevel=0.045, segments=3))
        back = box(f"back{i}", (sw - 0.015, 0.15, 0.42), (x, 0.235, 0.67), "sofa", bevel=0.05, segments=3)
        back.rotation_euler.x = -0.12      # leaning back, its foot on the seat's rear
        parts.append(back)
    for s in (-1, 1):
        parts.append(box(f"arm{s}", (aw, 0.86, 0.53), (s * (w - aw) / 2, 0, 0.335), "sofa", bevel=0.05, segments=2))
    return smooth(join(name, parts), 40)


# ---------------------------------------------------------------- the PADD shelf
# After `padShelf(x, z, rot)` in deck.html: 1.4 wide, 2.05 high, 0.36 deep,
# six boards 0.03 thick at 0.1 + 0.384 k, their tops where the page stands a
# pinned PADD; the amber strip under each board stays the stand-in's (kept
# over the model). In the page's frame x across, y up, z out of the wall:
# here Blender (x, -z, y). The ready room's two (readyroom.py) and the
# generated rooms': the labs' (lab.py), the sickbays' (sickbay.py) and the
# cabins' (lounge.py, the glb the quarters take): one rack, each room's own
# colours and dressing, in its own atlas (a prop from another room's glb
# would be another call a room). Dressing on a third of a few boards, so
# the rest stays free for entries.
SW, SH, SD = 1.4, 2.05, 0.36
BOARDS = [0.1 + i * (SH - 0.13) / 5 for i in range(6)]
PALETTE["book_green"] = (0x2e4a3a, 0.8, 0.0, "weave")


def padd_shelf(name, dress, side="trim", back="wainscot", board="desk_wood", plinth="console"):
    """The rack in its materials, with `dress` (a list of objects, built
    with the helpers below) on its boards, joined as one prop."""
    parts = [box(f"back{name}", (SW, 0.03, SH), (0, SD / 2 - 0.015, SH / 2), back, bevel=0.006, segments=1),
             box(f"plinth{name}", (SW - 0.09, SD - 0.04, 0.085), (0, 0, 0.0425), plinth, bevel=0.008, segments=1)]
    for sx in (-1, 1):
        parts.append(box(f"side{name}{sx}", (0.045, SD, SH), (sx * (SW / 2 - 0.0225), 0, SH / 2), side, bevel=0.008, segments=1))
    for i, y in enumerate(BOARDS):
        parts.append(box(f"board{name}{i}", (SW - 0.09, SD - 0.03, 0.03), (0, 0, y), board, bevel=0.006, segments=1))
    return smooth(join(name, parts + dress), 35)


def shelf_book(tag, x, board, h, t, d, mat, lean=0.0, lying=False, at_y=0.0):
    """A book standing on a board (spine out) or lying flat: a box, its
    cover a hair proud of its pages would cost more than it shows. A binder
    or a case is the same box."""
    z0 = BOARDS[board] + 0.015
    if lying:
        return box(f"book{tag}", (d, h, t), (x, at_y, z0 + t / 2), mat, bevel=0.004, segments=1)
    b = box(f"book{tag}", (t, d, h), (x, at_y, z0 + h / 2), mat, bevel=0.004, segments=1)
    if lean:
        # leaning on its neighbour: turned about the foot of its low side
        b.rotation_euler.y = lean
        b.location.x += math.sin(lean) * h / 2
        b.location.z -= (1 - math.cos(lean)) * h / 2
    return b


def shelf_padd(tag, x, board, lean=0.32, flat_z=None, turn=0.0):
    """A PADD: a putty body with its black face, leaning on the rack's back
    (`lean` about X, its foot on the board) or lying flat `flat_z` above the
    board, turned `turn` about Z."""
    from mathutils import Euler, Vector
    w, h, t = 0.15, 0.21, 0.012
    z0 = BOARDS[board] + 0.015
    if flat_z is not None:
        rot = Euler((math.pi / 2, 0, turn))
        at = Vector((x, 0.0, z0 + flat_z + t / 2))
    else:
        rot = Euler((-lean, 0, 0))
        foot = SD / 2 - 0.03 - h * math.sin(lean) - t
        at = Vector((x, foot + h / 2 * math.sin(lean), z0 + h / 2 * math.cos(lean) + t / 2 * math.sin(lean)))
    body = box(f"padd{tag}", (w, t, h), at, "putty", bevel=0.004, segments=1)
    face = box(f"pface{tag}", (w - 0.03, 0.002, h - 0.05), at + rot.to_matrix() @ Vector((0, -t / 2 - 0.0008, 0.008)), "black")
    for o in (body, face):
        o.rotation_euler = rot
    return [body, face]


def shelf_sculpture(tag, x, board):
    """A small bronze on a black block: a turned form, waisted and swelling,
    the kind of thing a captain is given."""
    z0 = BOARDS[board] + 0.015
    base = box(f"sbase{tag}", (0.09, 0.09, 0.04), (x, 0.02, z0 + 0.02), "black", bevel=0.004, segments=1)
    form = lathe(f"sform{tag}", [(0.001, 0), (0.03, 0), (0.018, 0.04), (0.012, 0.08), (0.03, 0.13), (0.035, 0.17), (0.02, 0.21),
                                 (0.008, 0.23), (0.001, 0.235)], "bronze", steps=12, at=(x, 0.02, z0 + 0.04))
    return [base, form]


def shelf_books(variant):
    """The ready room's two arrangements (and a cabin's): books lying and
    upright, PADDs leaning, the bronze, a stack of PADDs."""
    tag = variant
    if variant == "a":
        parts = [shelf_book(f"{tag}0", -0.45, 0, 0.3, 0.05, 0.24, "lounge_leather", lying=True, at_y=-0.01),
                 shelf_book(f"{tag}1", -0.45, 0, 0.28, 0.04, 0.22, "bridge_leather", lying=True, at_y=-0.01),
                 shelf_book(f"{tag}2", -0.45, 0, 0.26, 0.035, 0.2, "book_green", lying=True, at_y=-0.01)]
        # (each lying book stands on the one under it)
        parts[-2].location.z += 0.05
        parts[-1].location.z += 0.09
        for i, (dx, h, t, m) in enumerate(((0, 0.26, 0.04, "bridge_leather"), (0.045, 0.24, 0.035, "lounge_leather"),
                                           (0.087, 0.27, 0.045, "bed_pad"), (0.133, 0.23, 0.03, "sofa"))):
            parts.append(shelf_book(f"{tag}u{i}", 0.42 + dx, 1, h, t, 0.2, m))
        parts.append(shelf_book(f"{tag}ul", 0.6, 1, 0.22, 0.035, 0.19, "book_green", lean=0.28))
        parts += shelf_padd(f"{tag}p0", -0.5, 2) + shelf_padd(f"{tag}p1", -0.33, 2, lean=0.38)
        parts += shelf_sculpture(tag, 0.45, 3)
        for i in range(3):
            parts += shelf_padd(f"{tag}s{i}", -0.45, 4, flat_z=i * 0.013, turn=0.08 * (i - 1))
    else:
        parts = [shelf_book(f"{tag}0", 0.42, 0, 0.3, 0.05, 0.24, "bed_pad", lying=True, at_y=-0.01),
                 shelf_book(f"{tag}1", 0.42, 0, 0.28, 0.045, 0.22, "lounge_leather", lying=True, at_y=-0.01)]
        parts[-1].location.z += 0.05
        parts += shelf_padd(f"{tag}p0", 0.5, 1) + shelf_padd(f"{tag}p1", 0.33, 1, lean=0.4)
        for i, (dx, h, t, m) in enumerate(((0, 0.25, 0.04, "sofa"), (0.042, 0.27, 0.04, "book_green"), (0.084, 0.24, 0.035, "bridge_leather"))):
            parts.append(shelf_book(f"{tag}u{i}", -0.58 + dx, 3, h, t, 0.2, m))
        parts.append(shelf_book(f"{tag}ul", -0.42, 3, 0.23, 0.04, 0.19, "lounge_leather", lean=0.3))
        parts += shelf_sculpture(tag, -0.5, 2)
        parts += shelf_padd(f"{tag}p2", 0.48, 4, lean=0.3)
    return parts


# ---------------------------------------------------------------- the wardrobe
# After `cabinet(x, z, rot, 1.4, 2.25)` in deck.html, a cabin's wardrobe by
# the door: 1.4 wide, 2.25 high, 0.55 deep, its origin the floor under its
# middle, its doors -Y (the stand-in's +z). Two panelled doors either side
# of a slot 3 cm wide at x 0, where the stand-in's lit strip stays (kept
# over the model, as the PADD shelf's: cabinet() puts one at every 0.6 of
# its width, so one in the middle for 1.4 and for the 1.2 the page also
# builds, which takes this squeezed to 1.2 across). A recessed plinth and a
# top rail proud of the doors frame them; the panels are raised a few
# millimetres, enough for the bake to shade their edges. Lounge.py's (the
# glb the cabins take), in the cabin's wood (M.wood).
PALETTE["cabin_wood"] = (0x6a4630, 0.55, 0.0, "grain")
WW, WH, WD = 1.4, 2.25, 0.55


def wardrobe(name, wood="cabin_wood", dark="desk_wood"):
    f = -WD / 2 - 0.015                               # the doors' face, their backs on the body's front
    ph, rh = 0.09, 0.07                               # the plinth's height, the top rail's
    parts = [box(f"wplinth{name}", (WW - 0.06, WD - 0.06, ph), (0, 0.03, ph / 2), dark, bevel=0.006, segments=1),
             box(f"wbody{name}", (WW, WD - 0.02, WH - ph - rh), (0, 0.01, (WH + ph - rh) / 2), wood, bevel=0.008, segments=1),
             box(f"wrail{name}", (WW + 0.03, WD + 0.03, rh), (0, -0.015, WH - rh / 2), wood, bevel=0.012, segments=2)]
    gap, edge = 0.03, 0.035
    dw, dz0, dz1 = (WW - 2 * edge - gap) / 2, ph + 0.025, WH - rh - 0.02
    for sx in (-1, 1):
        x = sx * (gap + dw) / 2
        parts.append(box(f"wdoor{name}{sx}", (dw, 0.025, dz1 - dz0), (x, f + 0.0125, (dz0 + dz1) / 2), wood, bevel=0.006, segments=1))
        # a tall panel over a short one, raised off the door
        for k, (z0, z1) in enumerate(((dz0 + 0.1, 0.86), (0.98, dz1 - 0.1))):
            parts.append(box(f"wpanel{name}{sx}{k}", (dw - 0.13, 0.012, z1 - z0), (x, f - 0.004, (z0 + z1) / 2), wood, bevel=0.005, segments=1))
        # a slim brushed pull on each door by the slot
        parts.append(box(f"wpull{name}{sx}", (0.016, 0.022, 0.26), (sx * (gap / 2 + 0.055), f - 0.011, 1.12), "trim", bevel=0.005, segments=1))
    return smooth(join(name, parts), 35)
