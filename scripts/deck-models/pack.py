"""A downloaded pack to one room glb: a folder of .glb, .gltf or .obj files
in (each file one prop, named by the file), one glb with one atlas material
out, its licence copied beside it.

    blender -b --factory-startup -P scripts/deck-models/pack.py -- OUT_DIR NAME IN_DIR [--tris N] [--tris-PROP N] [--size 1024]

Each file's meshes are joined into one prop, set on the floor with its
origin at its footprint's middle (part 4 of docs/design/deck-style.md; the
pack's own front is kept: a placement in the page turns it), and decimated
to its triangle budget (`--tris`, default 1500, a furniture prop's;
`--tris-<prop>` for one prop): common.import_pack, which a room script
calls too when it has a pack's props beside its own (readyroom.py). The
bake is from the original onto the decimated copy, so the pack's own
textures (whatever they were, however many) end in one atlas: OUT/NAME.glb
and OUT/NAME_{base,norm,orm}.png, as a room script's.

The licence: every LICENSE* or LICENCE* file under IN_DIR is copied to
OUT/NAME.LICENSE.txt, which the cleaner folds into lcars-ui/deck/LICENSE.txt.
No licence file, no conversion: a pack whose terms are not on disk does not
ship.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C  # noqa: E402

out, args = C.out_dir()
if len(args) < 2:
    sys.exit("usage: blender -b -P pack.py -- OUT_DIR NAME IN_DIR [--tris N] [--tris-PROP N] [--size N]")
name, src = args[0], args[1]
opts = dict(zip(args[2::2], args[3::2]))
lic = C.pack_licences(src)
C.clean_scene()
lows, sources = C.import_pack(src, name, int(opts.get("--tris", 1500)),
                              {k[len("--tris-"):]: v for k, v in opts.items() if k.startswith("--tris-")})
C.finish_room(name, lows, size=int(opts.get("--size", 1024)), sources=sources)
C.write_licences(lic, os.path.join(out, f"{name}.LICENSE.txt"))
