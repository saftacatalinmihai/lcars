# Deck pipeline: models from Blender and CC0 packs into the deck

Number One's order, 2026-10-15: a pipeline so that every room of the 3D deck
(`lcars-ui/deck.html`) can be rebuilt from real models, proven end to end.
The two doors `deck-models.md` kept shut are open: models may be built in
Blender (4.3, headless on the box) and CC0 packs may be downloaded, each
with its licence kept. `deck-style.md` (Mendez) is the art direction: the
palette, the props per room, and in its part 4 the rules this pipeline
implements. Where this doc and part 4 differ, part 4 decided and this doc
says why it had to bend.

## The rule for every slice: the server first

**Every Blender build, every `deckshots.py` run and every test suite runs
under `nice -n 19`, and `ionice -c3` where it writes a lot.** A bake takes
every core it is given and `deckshots.py` (WebGL in software) takes the
rest; on 2026-10-15 a deckshots run took the whole box and the captain's
phone saw the live server time out. `scripts/deck-models/build.sh` nices
itself and gives Blender three threads of the four; run deckshots as
`nice -n 19 ionice -c3 python3 lcars-ui/test/deckshots.py ...`, and never a
bake and deckshots at once (the first measurement here was lost that way:
deckshots' screenshots timed out behind the bake).

## Adding a model, in five steps

1. **Script it.** A room's props are `scripts/deck-models/<room>.py`: build
   each prop from primitives and modifiers with `common.py`'s helpers
   (`box` with a bevel, `pad` - a subdivided cushion, `lathe` - a turned
   profile, `tube` - a curve with a bevel depth, `join`), materials only
   from `common.PALETTE` (`mat(name)`), one object per prop named by the
   prop, then `C.finish_room("<room>", [props])`. A downloaded pack's
   props beside a script's own: a case in `build.sh`'s `fetch()` fetches
   them (Poly Haven: `fetch_polyhaven.py`) into the cache and hands the
   folder to the script, which imports them with `C.import_pack` and
   passes its `sources` to `finish_room` (`readyroom.py`). A room of a
   pack alone gets a case in `pack()`, which runs `pack.py` on the folder.
2. **Build it.** `scripts/deck-models/build.sh <room>`: Blender headless
   writes the glb and three baked pngs to a temp dir, then
   `scripts/deck-model-assets.mjs` cleans them into `lcars-ui/deck/` and
   rewrites `lcars-ui/deck/LICENSE.txt`. It prints each prop's triangles
   and the room's bytes: check them against the budgets below.
3. **Place it.** In the room's builder in `deck.html`, wrap the code-built
   prop: `model(chair(x, z, s, true), "bridge", "captain_chair", { rot:
   Math.PI, scale: [s, 1, 1] })`, or place a new one at a point of its own:
   `model([x, y, z], "readyroom", "brass_vase_03", { rot: 0.6 })`.
4. **Look at it.** `nice -n 19 ionice -c3 python3 lcars-ui/test/deckshots.py
   OUT --only "<Room>" --view prop:<prop>`, and the PNGs at a phone's
   size: the room's four quarters, and each placement of the prop from
   its front.
5. **Measure and commit.** deckshots before and after (draw calls,
   triangles, boot, the models' arrival, frame p50), `node
   lcars-ui/test/deckboot.js`, `run.sh --changed`; commit the script, the
   built `lcars-ui/deck/` files and the numbers in the message.
   Before committing a script, `python3 -m py_compile
   scripts/deck-models/*.py`, and build at least one room with
   `build.sh`: no web test imports `common.py`, so a build is its only real
   test (a rebase once left conflict markers in it that every web test
   passed).

## A generated prop (deck-remodel.md slice 9)

Scripted first (the steps above); generated only to beat a scripted
piece, soft and organic ones (upholstery, plants), on credits the captain
has given. Its files live in the media store, never in git:
`MEDIA/media/deck-models/<prop>/` holds `<prop>.glb` (fitted, what a build
takes), `LICENSE.txt` and `raw/` (the prompts, the views, Tripo's
`raw.glb`, `gen.json`: every job, its price and the credits it took).

1. **Write `raw/prompts.txt`** (`gen.py`'s docstring has every key): the
   road, the object and the palette by name and hex, a line per view.
   The kit's lead (deck-remodel.md section 3 item 3) is put before each
   view by `gen.py`. **Side views** must say what the frame shows, not
   only "its left side at 90 degrees": Seedream shown the front and the
   back made one "left" a second front and one "right" a second back
   (2026-10-30, the sofa's first try), and Tripo fused the four into a
   two-faced sofa with its cushions heaped in the middle (9 credits
   lost). Name the end-on look ("only its 0.86 m depth across the frame,
   the arm's outer face in the middle, the seat's front at the left") and
   show the side the front alone (`left_refs: front`).
2. **Price it:** `scripts/deck-models/gen.py <prop>` asks `higgsfield
   generate cost` for each step with its real parameters (prices move
   with them: H3.1 with `texture_quality detailed` is 12, not 9) and
   stops. Nothing is spent.
3. **Make it:** `gen.py <prop> --spend N`, N a hard cap. Run it detached
   (`setsid nohup ... &`): a view takes 1-2 minutes, the 3D job 3-5, and
   a run killed with its turn has paid for the job it was waiting on (the
   next run fetches that job from `gen.json`'s `pending`, not paying
   again). **Look at each view as it lands** and stop the run before the
   3D job if one is wrong: a view re-rolled is 0.5, a 3D job 9.
   `--redo <view>` makes it and every step after it again; copy the old
   files aside first for the report.
4. **Fit it:** `blender -b --factory-startup -P scripts/deck-models/fit.py
   -- raw/raw.glb raw/fitted.glb --turn -90 --box W D H` (or `--height H`
   for a plant; `--drop-islands 0.01` for Tripo's loose wisps). Tripo's
   multiview puts the front at +X: `--turn -90` brings it to -Y. Look at
   it (Blender's workbench, four sides) before going on.
5. **Judge it in the deck.** Copy `raw/fitted.glb` to `<prop>.glb` (that
   is what `build.sh`'s `generated()` copies to the cache and the room
   script imports with `C.import_pack`); build the room, and deckshots
   main beside the branch, close and at a phone's distance. Kept only if
   it beats the scripted one by eye and fits the room's budgets; if not,
   delete `<prop>.glb` (the raw files stay, for the record) and the
   scripted one is built again.

## How it works

**Blender side (`scripts/deck-models/`).**

- `common.py`: the palette (`PALETTE`: deck-style.md part 1's hexes,
  roughness and metalness, plus a procedural relief per surface - pebble
  leather, brushed metal, grain, weave - in object space, so it needs no
  UVs), the modelling helpers, and `finish_room`: one UV map over every
  prop (smart project, islands scaled to their area in the world, packed
  into one square), the bake, one material, the glb.
- **The bake** (Cycles, CPU) writes five images and packs three: base
  colour and metalness through the emission (an `EMIT` bake of the input,
  so neither is lit nor weighted by the other), roughness, a tangent-space
  normal map (the relief, and for a pack the detail the decimation took),
  and ambient occlusion from the prop itself (for a pack, from the
  decimated prop alone: baked from the original, the low copy around it
  occluded it in dark cracks); then ORM = AO (floored at
  0.2: it is a hint, the room's contact shadow and GTAO do the rest),
  roughness, metalness, as glTF packs it. Samples per pass: 1 for a flat
  value, 4 for the normal, 16 for the AO - at 24 everywhere the chair's
  bake was 4 minutes of the box, now about one. A room of several props
  is baked as **one copy of them all, each moved 20 m from the last**
  (deleted after): baked one by one, each prop's margin painted over the
  islands of the props before it (the chair came out grey once the
  consoles joined it), and on top of one another, as they are built,
  each would shade the others' AO. A pack's props are in that copy too,
  then baked again each from its original (selected to active) with a
  margin of two pixels, inside the gap the packer leaves: a full margin
  there would paint over the islands baked before. The bake's margin is a
  sixteenth of the atlas (`EXTEND`): the black gaps between islands bleed
  into the seams a mip level down on a phone.
- **Tangents ship.** The normal map is baked in Blender's tangent space
  (MikkTSpace); three's own per-pixel tangents disagree with it across an
  atlas's rotated islands. So the glb keeps `TANGENT` and the page uses the
  map as baked (no `normalScale` flip, unlike the crew's tangentless
  glbs).
- `pack.py`, the converter, and `common.import_pack`, its loop, which a
  room script calls too: a folder of `.glb`, `.gltf` or `.obj` (each
  file one prop) in; each file's meshes joined, set on the floor at its
  footprint's middle, **decimated to its budget** (`--tris`,
  `--tris-<prop>`), and the original baked onto the decimated copy
  (selected to active), so however many materials and textures the pack
  had, one atlas comes out. Faces the collapse turned inside out are made
  consistent before the bake. **Not for thin-walled models**: a vase with
  an inner wall, decimated hard, has its inner wall poke through the outer
  (Poly Haven's ceramic_vase_01, tried here and dropped); pick solid
  pieces, or give them more triangles. Every `LICENSE*` file in the
  folder is copied beside the glb; **a folder without one is refused**.
- `fetch_polyhaven.py`: a Poly Haven asset's glTF at 1k with its textures,
  and a LICENSE.txt with the asset's name, authors, page and CC0, from the
  API. Downloads live in `~/.cache/lcars-deck-models/` and are never
  committed; `build.sh` names what it fetches.
- `build.sh [room...]`: the rooms (every `<room>.py`) and packs (`pack()`),
  niced, then the cleaner (its npm packages in the same cache, lent to it
  as `scripts/node_modules`, ignored).

**The cleaner (`scripts/deck-model-assets.mjs`)**, as the crew's: keeps
`POSITION`, `NORMAL`, `TANGENT`, `TEXCOORD_0`; prune, dedup, weld;
meshopt (`EXT_meshopt_compression`, level "high": reordered for size,
positions quantized to 14 bits, UVs 12, normals and tangents through its
octahedral filter at 8; since 0.242.1, before it the quantizer's 10 bits
uncompressed - "Measured: meshopt"); webp
atlases (base q82, normal q90, ORM q90) at the size they were baked
(1024² a room, 2048² a hero room, 512² a few pieces of dressing) unless
`--size room=N`; LICENSE.txt one
section per glb (a pack's own licence text, or "built by
scripts/deck-models/<room>.py").

**The page (`deck.html`, "the prop library").** The rooms' glbs are
loaded through one GLTFLoader with meshopt's decoder
(`lcars-ui/vendor/meshopt_decoder-<version>.mjs`, the npm package's file
as it is, MIT; a new version gets a new name, as the three bundle does),
imported once and shared. The crew's glbs (`deck-crew-assets.mjs`) are
meshopt-compressed too (0.248.2) and use a loader of their own on the same
decoder, so it is fetched at boot with the crew (before 0.248.2, with the
first room's glb).
`model()` records a
placement. Nothing waits for a model: the ship is built and shown from
code as before; `loadModels()` starts once the boot is done (after the
journal), fetches each room's glb and its three webp once, and for each
room merges every placement into **one mesh in the room's one material**
(one draw call per room, cast and received shadows, the shadow maps
redrawn once). A stand-in (the code-built group the placement wraps) has
its triangles collapsed where `mergeStatic` (or `finishCell`) merged them,
recorded by `standinRanges` at the merge: rebuilding the deck-wide merged
buffers for one chair would cost the whole deck's merge again. It keeps its
contact shadow, its blinking lights (the chair's armrest lights sit on the
model's armrest fronts), its `block()` and its seats: the originals stay
in `pinnable`, so aiming and sitting go by the code-built shapes, which the
model is built to. A placement with no stand-in gets a contact patch of
its own from the model's extent (merged: one more draw for all of them). A
room whose glb fails to load keeps its stand-ins; no stand-in, nothing.
**A room built later** (a wing's, another deck's: `buildRoom` into a cell)
places its models the same way: `model()` records the frame it was called
in, `finishCell` takes the placements of its cell (the tail of the list,
their stand-ins' ranges recorded by its own merge) and `cellModels` merges
them into one mesh under the cell from the kept glb (`modelReady`: in the
frame the cell is built, once the room's glb is in; else when it lands).
`dropCell` drops them with the cell (geometry disposed, the atlas material
`keep`). A cell's models receive shadows but cast none, as everything in
a cell. A cell built before the boot is done waits for `loadModels`.

## Budgets

From deck-style.md part 4, which these keep:

| class | what | triangles per prop | notes |
|---|---|---|---|
| hero | seen close and alone (captain's chair, bar, surgical bed) | ≤ 6 k | at most 3 in a room |
| furniture | repeated (chairs, benches, consoles, beds) | ≤ 1.5 k | |
| dressing | small (PADDs, vases, trays, cups) | ≤ 200 | its own mesh; not drawn on graphics low beyond 4 m |

- **A room: at most +40 k triangles** with every prop in (the stand-ins'
  collapsed triangles count: three still sends them), **+1 draw call** (the
  atlas), +1 more for the contact patches of placements with no stand-in.
- **Dressing: +1 draw call for the room you stand in, +0 for every other
  room** on graphics low. A room's placements merge into two meshes in its
  one atlas material (`placeModels`): its hero and furniture props, and its
  dressing (`DRESSING` in deck.html, the props of class D in deck-style.md
  part 2: comm panels, plaques, PADD racks, trays, the hypospray rack, the
  sample racks, the ready room's vase and carving). On low the dressing
  mesh is drawn only from within 4 m of its box (`tickDressing`, each
  frame from the eye), on high and medium always (+1 a room in view). A
  new small prop goes in `DRESSING`. A generated room type's glb is split
  the same way, per cell (each corridor cell is a room: up to +2 where
  two cells' dressing is within 4 m). Measured in "Measured (0.248.1)".
  A dressing prop's contact patches are a mesh of their own, the dressing
  mesh's child, so they go with it (+1 call near in a room whose furniture
  has patches too). **The code-built dressing** (Ten Forward's bottles and
  glasses, the lounge's ship models, the ready room's ship model, mugs,
  books and teapot, a cabin's mugs and ship model) goes in a group of the
  room's (`dressGroup`), which `tickDressing` treats as a dressing mesh:
  +0 calls, as its merged parts are cut out of the merges they were in by
  drawRange (`dressOrder`: a group's at the head of its material's buffer,
  a second's at the tail). A new small code-built thing goes in its room's
  group. Measured in "Measured (0.254.0)".
- **Textures**: one atlas per room, 1024² (a hero room 2048²), webp:
  base q82, normal q90, ORM q90.
- **Bytes per room**: at most ~600 kB for a 1024² room (glb + three webp),
  ~1.5 MB at 2048², **as the files are**: tailscale serve passes the
  bytes through, and the server sends a webp as it is; a glb has gone
  gzipped since 0.255.0 (~56% of the file - "Measured: gzip for the web
  UI's files"), but the budget is kept on the file's size. The glb is
  meshopt-compressed (0.242.1): ~17 B a triangle, where quantized alone it
  was ~47. The bridge's first prop: see the numbers below.
- **The crew's bytes** (`lcars-ui/crew/`, every file fetched at boot on
  every phone: two bodies, nine hair glbs, the clips, seven webp): at most
  ~1.3 MB as the files are, plus the 29 kB decoder; 1.21 MB since 0.248.2
  (meshopt), 1.98 MB before ("Measured: the crew's meshopt").

## Measured: gzip for the web UI's files (0.255.0, measured against 0.254.1)

A cold boot of `deck.html?demo&touch` on graphics low at 390x844 in
headless Chromium (cache disabled, CDP's `encodedDataLength` of every
response, headers included), against scratch release builds of deb and of
this change serving the same `lcars-ui/` from loopback:

| | 0.254.1 | 0.255.0 |
|---|---|---|
| deck.html | 860 kB | 289 kB (gzip) |
| three-0.186.1-r2.min.js | 908 kB | 259 kB (gzip) |
| meshopt_decoder (mjs) | 29 kB | 8 kB (gzip) |
| 22 glbs (rooms and crew) | 2013 kB | 1122 kB (gzip) |
| 37 webp | 1958 kB | 1959 kB (as is) |
| the API (2 answers) | 28 kB | 28 kB |
| **all 64 requests** | **5796 kB** | **3665 kB (-37%)** |

The webp atlases are now most of a boot (53%). Boot time on loopback is
unchanged (56.6 s against 55.6 s to the ship built: SwiftShader's, not the
network's); on a phone over tailscale the 2.1 MB less is the gain.
Per file at level 5: readyroom.glb 213 -> 104 kB, crew/clips.glb 273 ->
96 kB. The server's cost: the first gzip GET of deck.html after a save
28 ms, of index.html 72 ms (compressing into the cache); every later one
under 1 ms, from it.

## Measured (0.214.0 against 0.213.0)

`deckshots.py`, 390x844, graphics low, SwiftShader, niced, the bridge,
corridor, ready room and Ten Forward looking four ways (16 views):

| | before | after |
|---|---|---|
| boot to ship built | 38.2 s | 41.2 s (runs of the same page: 39.4-42.5; the load starts after it) |
| crew loaded | 44.2 s | 47.2 s |
| models landed | - | 53.7 s (both rooms) |
| draw calls, bridge views | 56-190 | 57-194 (+1; +4 looking aft, the corridor's too) |
| draw calls, ready room views | 77-144 | 79-146 (+2-3: the atlas, the contact patches, the bridge's chairs through the door) |
| triangles, bridge views | | +15.1 k (three chairs of 5044; their stand-ins' collapsed ones still sent) |
| triangles, ready room views | | +0.4 k |
| frame p50 over the 16 views | 1058 ms | 1043 ms |
| shadow redraws | 0 of 38 | 0 of 49 |

Files: `bridge.glb` + atlas 298 kB (1024²), `readyroom.glb` + atlas
156 kB (512², two props of 200 triangles).

## Measured: the bridge's props (0.215.0 against 0.214.0)

`deckshots.py` as above, the bridge's four quarters:

| | before | after |
|---|---|---|
| draw calls (fwd, port, aft, stbd) | 59 / 63 / 195 / 57 | 60 / 63 / 194 / 57 |
| triangles, looking aft | 787.8 k | 803.0 k |
| triangles, the other three | 491.6-532.6 k | 453.2-494.3 k |
| boot / models landed | 42.6 s / 55.8 s | 40.9 s / 53.8 s |
| frame p50 over the views | 1216 ms | 1221 ms |
| shadow redraws | 0 of 9 | 0 of 9 |

The props: captain_chair 5044 x 3, conn_console 1468 x 2, tactical_rail
2374 x 2, station 956 x 6 - 28.6 k in all (+13.4 k on 0.214.0), under
the room's 40 k. The three views that lost 38 k lost M.wood: the well's
rim and the rail left it for M.rail, so its merged mesh no longer reaches
the bridge and is culled there. `bridge.glb` + atlas 410 kB at 1024².

## Measured: Ten Forward (0.216.0 against 0.215.0)

`deckshots.py` as above, Ten Forward's four quarters, niced:

| | before | after |
|---|---|---|
| draw calls (fwd, stbd, aft, port) | 113 / 112 / 135 / 75 | 113 / 111 / 136 / 82 |
| triangles, same quarters | 770.1 / 666.1 / 766.4 / 655.1 k | 788.9 / 688.2 / 785.4 / 707.0 k |
| boot / models landed | 40.8 s / 53.4 s | 43.1 s / 56.3 s (one busy box: 40.5 / 53.0 on another run) |
| frame p50 over the views | 1534 ms | 1469 ms |
| shadow redraws | 0 of 8 | 0 of 17 |

The props: tf_bar 1436, tub_chair 976 x 30, tf_table 480 x 10 - 35.5 k in
all, under the room's 40 k. The fourth quarter's +52 k is a viewpoint, not
geometry: deckshots stands at the walkable point nearest the room's
centroid, and the window seat moved it. From one point for both pages
(looking to port from 11.5, -19) the difference is +37.1 k: the atlas mesh
+35.5 k, M.topTF +4.8 k and M.wallTF +4.0 k, less M.console -3.9 k (the
table tops), the corridor's putty -3.0 k, M.wood -0.9 k. One run of the
aft quarter counted 1.30 M where the rest gave 785 k: the same page, a
neighbouring room built that frame; it did not repeat. `tenforward.glb` +
atlas 434 kB at 2048².

## Measured: the ready room and the lounge (0.217.0 against 0.215.0)

`deckshots.py` as above, the two rooms' four quarters (fwd, port, aft,
stbd; "before" is 0.215.0's page, "after" this one before its rebase onto
Ten Forward's, which neither room sees):

| | before | after |
|---|---|---|
| draw calls, ready room | 85 / 78 / 132 / 93 | 84 / 77 / 132 / 92 |
| draw calls, lounge | 139 / 71 / 129 / 101 | 139 / 72 / 130 / 102 |
| triangles, ready room | 596.1-667.0 k | +12.0 k (+29.2 k looking aft, through the door to the lounge's chairs) |
| triangles, lounge | 636.4-724.8 k | +17.2 k (+29.2 k looking forward, the ready room's too) |
| boot / models landed | 42.9 s / 55.5 s (2 rooms) | 42.3 s / 55.5 s (3 rooms) |
| frame p50 over the 8 views | 1329 ms | 1226 ms |
| shadow redraws | 0 of 16 | 0 of 16 |

The props: desk 2304, padd_shelf_a 1308 x 4, padd_shelf_b 1108 x 3,
fish_tank 1124, the elephant and vase 200 each - 12.4 k in the ready room;
lounge_chair 1436 x 12 - 17.2 k in the lounge. `readyroom.glb` + atlas
482 kB at 1024², `lounge.glb` + atlas 97 kB at 512². The ready room lost a
call: its wood ceiling is the deck's `M.ceil`, and its carpet took the
planks' place.

## Measured: the corridor and the arboretum (0.218.0 against 0.216.0)

`deckshots.py` as above, the two rooms' four quarters, niced; "before" is
0.216.0's page, "after" this one before its rebase onto 0.217.0's (the
ready room and lounge, which these views barely see):

| | before | after |
|---|---|---|
| draw calls, corridor | 189 / 85 / 132 / 86 | 191 / 87 / 134 / 87 |
| draw calls, arboretum | 131 / 91 / 87 / 66 | 132 / 93 / 88 / 68 |
| triangles, corridor | 1363.0 / 659.8 / 724.6 / 708.2 k | 1321.8 / 668.2 / 737.8 / 721.3 k |
| triangles, arboretum | 1252.5 / 1125.9 / 1081.1 / 1060.6 k | 1216.0 / 1089.4 / 1044.7 / 1024.1 k |
| boot / models landed | 44.4 s / 57.3 s (3 rooms) | 42.8 s / 56.1 s (5 rooms) |
| frame p50 over the 8 views | 2155 ms | 2014 ms |
| shadow redraws | 0 of 12 | 0 of 12 |

The props: comm_panel 176 x 12, door_plaque 176 x 7, padd_rack 192 x 3 -
3.9 k in the corridor; fountain 1360, garden_bench 846 x 4 - 4.7 k in the
arboretum. A view's +2 calls is its own room's atlas and the other's
through a door. The arboretum's views are 36 k lighter: the kerbs take
12 cm off each bed's soil, and the flowers in it are fewer (the corridor's
looking-forward view, which sees the arboretum's beds through its door,
lost the same). `corridor.glb` + atlas 61 kB at 512², `arboretum.glb` +
atlas 231 kB at 1024².

## Measured: the crew (0.219.0 against 0.217.0)

`deckshots.py` as above, niced, on a box at load 3.5-4 (another session's
tests): the bridge's and Ten Forward's quarters, and six close looks at
the crew (`--view crew:N`: the conn officer at 40° round, the science
station from its side, tactical from the front, a Ten Forward table).
"After" is this page before its rebase onto 0.218.0, which neither room
sees, and before the combadge was raised onto the yoke (the same
triangles).

| | before | after |
|---|---|---|
| frame p50, bridge (fwd, port, aft, stbd) | 1564 / 925 / 3183 / 682 ms | 1474 / 914 / 3331 / 688 ms |
| frame p50, Ten Forward | 1352 / 1164 / 1815 / 678 ms | 1416 / 1144 / 1859 / 687 ms |
| frame p50, crew close-ups | 1886 / 773 / 1283 / 2417 ms | 1884 / 895 / 1294 / 2748 ms |
| median over the 12 views | 1318 ms | 1355 ms (+3%, inside one run's spread) |
| draw calls | | the same, ±1 (a crew member's insignia is one draw, as the badge was) |
| triangles | | +0.2-1.5 k a view (~200 an officer: the badge's two extrusions and the pips) |
| boot / crew loaded | not recorded (the run died on a later screenshot) | 42.8 s / 48.6 s |
| shadow redraws | 0 | 0 |

The two close-ups that rose by 0.1-0.3 s are one- and three-frame
measurements at 1-3 s a frame (p99 = p50), so a single slow frame of a
busy box; the room views, a dozen frames each, moved both ways. Per
person per frame the crew now turn up to nine bones (breathing: the chest
and three counter-scales; the weight shift: pelvis, thighs, spine, neck;
the head: neck and head) after the mixer, with no allocation; the far
ones every other frame, as the mixer.

## Measured: the crew's leftovers (0.239.0 against 0.238.0)

`deckshots.py`, niced, at a phone's size, one after the other on the same
box (load ~4: other sessions' work), "before" being 0.238.0's page served
from a copy: Ten Forward's and the corridor's quarters, and ten close
looks at 2 m (`--view crew:N,2`: the PADD reader, a ponytail, a bob, a
science officer buzzed and one female-buzzed, two seated at Ten Forward's
tables, an ops officer at a console from behind, hands behind the back,
arms folded; the walkers were often mid-stride when shot).

| | before | after |
|---|---|---|
| frame p50, Ten Forward (fwd, port, aft, stbd) | 1397 / 1165 / 2213 / 746 ms | 1705 / 984 / 2267 / 746 ms |
| frame p50, corridor | 2607 / 1858 / 2662 / 1751 ms | 2942 / 1852 / 2663 / 1841 ms |
| median over the 18 views | 2152 ms | 2078 ms |
| draw calls, room views | 86-195 | 86-196 (+0-1: a PADD) |
| triangles, room views | | within ±1.5 k (poses differ) |
| boot / crew loaded | 55.4 / 63.4 s (8.0 s apart) | 60.0 / 67.9 s (7.9 s apart) |
| shadow redraws | 0 of 29 frames | 0 of 31 |
| `lcars-ui/crew/` | 1676 kB | 1979 kB (+302: three hair glbs 256, clips +47) |

Ten Forward's views moved both ways (an earlier "before" run gave 1400 /
1097 / 2326 / 850 ms), and the room views are a few frames each at 1-3 s
a frame: inside one run's spread. The close-ups are one-frame
measurements of walkers at different places in their walk. The load from
boot to crew is unchanged: `clothNormals` (24 Taubin steps over ~7 k
vertices, twice) and the three extra hair files are lost in the 8 s.

## Measured: the concourse (0.220.0 against 0.218.0)

`deckshots.py` as above, the concourse's four quarters (fwd, port, aft,
stbd), niced; a third run is this page with `concourse.glb` taken away
(the stand-ins alone). All three before the rebase onto 0.219.0 (the
crew's part 3, which changes the walkers, not the hall):

| | before | stand-ins alone | after |
|---|---|---|---|
| draw calls | 217 / 123 / 52 / 118 | 218 / 122 / 53 / 117 | 219 / 126 / 54 / 119 |
| triangles | 1360.7 / 663.0 / 525.5 / 643.2 k | 1359.9 / 661.5 / 524.1 / 641.6 k | 1377.2 / 679.3 / 541.3 / 658.3 k |
| boot / models landed | 42.8 s / 55.7 s (6 rooms) | 46.3 s / 59.2 s | 46.4 s / 60.2 s (7 rooms; the box busier) |
| frame p50 over the views | 1353 ms | 1445 ms | 1384 ms (the 4 quarters) |
| shadow redraws | 0 of 7 | 0 of 7 | 0 of 7 |

The props: ring_bench 1174 x 6, column 1180 x 8, directory 400 x 2 -
17.3 k in all, under the room's 40 k; the views +15-16.5 k. The stand-ins
alone are the old page's calls give or take one (the crew walk, and a
view counts its busiest frame), so the atlas is the room's one call, as
budgeted; the rest is the crew. `concourse.glb` + atlas 192 kB at 1024².
The concourse's first quarter takes ~5 s a frame in software, longer
than playwright's 30 s for a screenshot at 3x: deckshots now waits 3
minutes.

## Measured: sickbay and the labs (0.221.0 against 0.220.0)

`deckshots.py` as above, niced: deck 8's Stellar sciences (a lab) and
Sickbay, built at boot, and a wing's lab (the Exobiology lab) and deck
12's sickbay, built in cells - the four quarters of each. "Before" is
0.220.0's page (with the concourse's models) and this deckshots; "after"
this page before its rebase onto 0.220.0, which these views do not reach.

| | before | after |
|---|---|---|
| draw calls, Stellar sciences | 142 / 60 / 85 / 93 | 143 / 61 / 86 / 94 |
| draw calls, Sickbay | 160 / 125 / 89 / 138 | 161 / 129 / 89 / 138 |
| draw calls, wing lab | 72 / 69 / 62 / 248 | 74 / 70 / 63 / 250 |
| draw calls, deck 12 sickbay | 194 / 51 / 98 / 499 | 195 / 52 / 98 / 500 |
| triangles, Stellar sciences | 760.6 / 579.9 / 621.7 / 714.9 k | +5.5-7.9 k |
| triangles, Sickbay | 797.6 / 718.8 / 706.1 / 744.8 k | +5.5 / +24.7 / -1.9 / -1.9 k |
| triangles, wing lab | 479.7 / 232.7 / 224.5 / 987.6 k | +6.0 / +7.5 / +7.5 / +13.0 k |
| triangles, deck 12 sickbay | 316.1 / 159.0 / 231.4 / 695.5 k | +20.3-20.5 k |
| boot / models landed | 46.0 s / 58.9 s (7 rooms) | 48.2 s / 61.1 s (8 rooms; the concourse's not in this page) |
| frame p50 over the 16 views | 1119 ms | 1203 ms (+7.5%: the medians fall between a 0.8 s and a 1.5 s view; the views themselves moved -8 to +14%) |
| shadow redraws | 0 of 47 | 0 of 149 (the prop views too) |

The props: biobed 1120, surgical_bed 3452, instrument_tray 196 - deck 8's
sickbay has three beds, a surgical bed and four trays (8.6 k with their
stand-ins' collapsed triangles still sent); work_bench 680, specimen_case
856, holo_table 1280 - a lab of four benches, seven cases and its table is
~10 k. Each room +1 call (the wing lab's +2 looking aft sees the next
lab's through its door). The sickbay views that lost 1.9 k lost the wall
screens over the beds (now the display on the arm). `sickbay.glb` + atlas
269 kB, `lab.glb` + atlas 183 kB, both 1024².

## Measured: the polish round (0.221.4 against 0.220.0)

`deckshots.py` as above, niced, the four rooms' quarters (fwd, port, aft,
stbd), "before" this branch's base (0.220.0), "after" with all four
pieces in, before the rebase onto 0.221.0 (sickbay and the labs, which
these views do not reach):

| | before | after |
|---|---|---|
| draw calls, Ten Forward | 100 / 106 / 124 / 82 | 95 / 106 / 124 / 83 |
| draw calls, lounge | 141 / 73 / 133 / 107 | 141 / 72 / 133 / 107 |
| draw calls, ready room | 85 / 78 / 135 / 97 | 85 / 77 / 135 / 97 |
| draw calls, concourse | 228 / 121 / 56 / 121 | 212 / 121 / 56 / 123 |
| triangles, Ten Forward | 741.5 / 702.4 / 779.8 / 708.4 k | 730.1 / 708.7 / 787.1 / 712.3 k |
| triangles, lounge | 750.8 / 647.1 / 753.5 / 791.5 k | 753.6 / 648.1 / 758.2 / 796.4 k |
| triangles, ready room | 629.5 / 601.2 / 706.8 / 723.0 k | 631.2 / 602.6 / 713.1 / 728.5 k |
| triangles, concourse | 1409.8 / 679.2 / 556.9 / 893.2 k | 957.7 / 682.8 / 560.4 / 897.9 k |
| boot / crew / models landed | 42.7 / 49.1 / 56.1 s | 48.6 / 55.4 / 61.9 s (the run with six close looks after it, the box busier) |
| frame p50, median of the 16 quarters | 1179 ms | 1223 ms |
| shadow redraws | 0 of 34 | 0 of 77 (with the close looks) |

The props: bar_stool 472 x 8 (+3.8 k; Ten Forward 39.3 k in all, under
its 40 k), lounge_sofa 1132 (the lounge 18.4 k), planter 896 x 4 (+3.6 k;
the concourse 20.9 k), tea_table 816 and window_seat 860 (the ready room
14.1 k). No room gained a draw call: each prop is in its room's one atlas.
The views move by what they see of the new props (+1-7 k); the two first
quarters that fell (Ten Forward -11 k and -5 calls, the concourse -452 k
and -16 calls) are the busiest frame of a view that a walker or a
neighbouring room changes, as the 1.30 M of 0.216.0's run was: the
concourse's first quarter counted 1360.7 k on 0.220.0's own run. Files:
`tenforward` 461 kB (2048²), `lounge` 184 kB (now 1024²), `concourse`
246 kB, `readyroom` 530 kB, each with its atlas.

## Measured: every corridor (0.222.0 against 0.221.4)

`deckshots.py` as above, niced, the new "Deck 12 corridor" view: the
street in the middle before deck 12's sickbay's door, the four quarters.

| | before | after |
|---|---|---|
| draw calls | 227 / 76 / 37 / 436 | 232 / 77 / 38 / 447 |
| triangles | 439.0 / 187.1 / 151.9 / 629.7 k | 452.4 / 191.3 / 156.1 / 666.9 k |
| frame p50 | 1460 / 683 / 365 / 1756 ms | 1623 / 691 / 385 / 1779 ms |
| boot / models landed | 47.1 s / 60.5 s | 46.3 s / 59.6 s |
| shadow redraws | 0 of 13 | 0 of 13 |

Each corridor cell is +1 call (its atlas mesh, no contact patches: all
three props are hung on the wall); the views that look down a street or
through a junction see several cells, so +5 and +11. A cell's props are
~3-11 k triangles (comm_panel 176 x 2 a door, door_plaque 176 a door,
padd_rack 192 every 12 m or more).

## Measured: the generated room types (0.223.0 against 0.222.0)

`deckshots.py --gen 8:observation --gen 25:mess`, niced: a wing's
observation lounge (8-A) and deck 25's mess hall, the four quarters.

| | before | after |
|---|---|---|
| draw calls, observation 8-A | 53 / 57 / 52 / 256 | 54 / 58 / 53 / 259 |
| draw calls, deck 25 mess | 64 / 127 / 195 / 408 | 66 / 171 / 203 / 422 |
| triangles, observation 8-A | 221.1 / 227.0 / 220.2 / 1033.8 k | +8.0 / +8.0 / +8.0 / +18.5 k |
| triangles, deck 25 mess | 205.2 / 278.6 / 380.0 / 639.2 k | +9.2 / +33.6 / +23.8 / +42.8 k |
| frame p50, the 8 views | 866 ms | 831 ms |
| shadow redraws | 0 of 22 | 0 of 22 |

The mess's +44 calls looking to port is not the models: deckshots waits
600 ms after `tickRooms`, and the rooms are built one a frame, so which
neighbours are up when it counts differs between two pages. Counted on
one frame after 1.5 s at the same spot (`renderBufferDirect` hooked,
calls by cell): 128 before, 131 after - the mess's atlas mesh and the two
corridor cells' (0.222.0) it sees. Deck 25's mess has more than eight
tables, so it takes Ten Forward's tables and keeps its chairs code-built
(480 a table). The lounge's three sofas are 1132 each.

## Measured: sickbay's and the labs' leftovers (0.224.0 against 0.223.0)

`deckshots.py` as above, niced: the four rooms of 0.221.0's measure, and
the new props from their fronts (`--view prop:`; the office desk on deck
12 with `--views-deck 12`: deck 8's sickbay is too small for an office).

| | before | after |
|---|---|---|
| draw calls, Stellar sciences | 142 / 62 / 88 / 94 | 143 / 62 / 87 / 95 |
| draw calls, Sickbay | 161 / 107 / 90 / 139 | 161 / 129 / 91 / 140 |
| draw calls, wing lab | 74 / 70 / 63 / 286 | 75 / 71 / 63 / 254 |
| draw calls, deck 12 sickbay | 195 / 53 / 98 / 501 | 199 / 53 / 98 / 513 |
| triangles, Stellar sciences | 769.5 / 601.5 / 646.7 / 725.1 k | +10.8 / -4.3 / +2.6 / +10.8 k |
| triangles, Sickbay | 828.8 / 710.8 / 723.5 / 762.3 k | +2.7 / +45.1 / +12.6 / +12.9 k |
| triangles, wing lab | 486.0 / 240.2 / 232.0 / 1076.6 k | +11.3 / +11.3 / +11.3 / -10.1 k |
| triangles, deck 12 sickbay | 336.5 / 179.6 / 251.7 / 716.0 k | -0.1 / -14.2 / -10.5 / +29.6 k |
| boot / models landed | 46.5 s / 59.3 s | 46.1 s / 59.5 s |
| frame p50 over the 16 views | 1397 ms | 1630 ms (the medians fall between 0.8 and 1.9 s views; the views moved -24 to +21%) |
| shadow redraws | 0 of 44 | 0 of 62 (the prop views too) |

The swings of 20-45 k and of calls (sickbay looking to port +22, the wing
lab's stern -32) are the neighbours built in deckshots' 600 ms, as in
0.223.0's note: the props themselves are 632 + 2 x 184 in a lab and
440 a cabinet (6-12 to a sickbay) + 192 + 372. `sickbay.glb` + atlas
327 kB, `lab.glb` + atlas 231 kB, both 1024².

## Measured: ornate corridors (0.225.0 against 0.224.0)

`deckshots.py --only "Corridor,Deck 12 corridor"`, niced, the four
quarters of each; the boot from `--only none` runs, deb's page and this
one alternated, twice each.

| | before | after |
|---|---|---|
| draw calls, deck 8 | 192 / 90 / 137 / 86 | 193 / 91 / 138 / 87 |
| draw calls, deck 12 | 231 / 78 / 37 / 447 | 232 / 80 / 36 / 446 |
| triangles, deck 8 | 1357.3 / 702.9 / 782.4 / 722.3 k | 1364.6 / 710.2 / 789.7 / 729.6 k |
| triangles, deck 12 | 456.3 / 191.4 / 156.1 / 666.6 k | 500.9 / 200.4 / 160.9 / 731.9 k |
| frame p50, deck 8 | 2860 / 1725 / 2911 / 1563 ms | 2784 / 1585 / 2353 / 1664 ms |
| frame p50, deck 12 | 1601 / 629 / 297 / 2425 ms | 1628 / 558 / 309 / 2090 ms |
| boot (deb / this) | 49.4, 49.6 s | 50.0, 49.9 s (51.0, 50.5 with a 1024² wall) |
| shadow redraws | 0 of 20 | 0 of 20 |

Deck 8's corridor: +7.3 k triangles, +1 call (M.wallCorr, merged
deck-wide apart from M.wall). A generated cell draws M.wallCorr in
M.wall's place: +0, but one with no door, rack or wall unit had no
atlas mesh and now has one for its ribs (deck 12's view 1, +2). Deck 12's
widest view (446 calls, many cells) is +65 k: ribs 162 each, wall units
556 / 844. The first build, its new mouldings in rounded boxes (~300
triangles each), was +234 k there and up to 25 % slower; they are plain
boxes now (`sbox`).

## Measured: the ornate hull (0.228.0 against 0.227.0)

`deckshots.py --only "Ten Forward,Observation lounge,Arboretum,Ready
room" --secs 4 --no-shots`, niced, deb's page and this one alternated,
twice each (the box was shared: single runs swung ±25 %); the window
quarters are Ten Forward 0 (ahead) and 3 (starboard), the lounge's and
the ready room's 1 (port), the arboretum's 3 (starboard). Boot from
`--only none`, three of each, alternated.

| | before | after |
|---|---|---|
| draw calls, every view | | +2 (the greebles' mesh, the shell's strobes) |
| triangles, every view | | +33.9 k (hull.glb: 84 phaser segments x 204, 79 lifeboat rows x 144, 4 RCS quads x 572, 12 domes x 256) |
| frame p50, Ten Forward 0 / 3 | 1449 / 803 ms | 1541 / 844 ms (+6 / +5 %) |
| frame p50, lounge 1, ready room 1 | 989 / 1043 ms | 1061 / 1138 ms (+7 / +9 %) |
| frame p50, arboretum 3 | 1972 ms | 2035 ms (+3 %) |
| frame p50, all 16 views (median ratio) | | +4 % |
| boot (three each) | 54.7, 50.6, 50.6 s | 56.7, 55.0, 53.9 s |
| shadow redraws | 0 of 29 | 0 of 29 |
| bytes | | hull.glb + atlas 137 kB (1024²) |

The views facing away from the windows moved -9 to +17 % (Ten Forward
1 and 2, both rooms looking into the room); they draw the same hull
through other rooms' glass. Boot is ~3 s longer on SwiftShader. It is
not the relief (81 ms to generate it in node) but, as far as could be
told, compiling the larger hullMat: it was +6 s while `wins()` was
inlined three times, and one call brought it to +3 s. A phone's driver
compiles it in a fraction of that. The greebles' mesh and the strobes,
each switched off in turn, changed no view's frame time measurably.

## Measured: the corridors' leftovers (0.236.0 against 0.235.0)

`deckshots.py --only "Corridor,Deck 12 corridor"`, niced, the four
quarters of each; the boot from `--only none` runs, deb's page and this
one alternated, twice each. Door frames (`door_frame`, 356 triangles), the
replicator (`alcove_replicator`, 572), the carpet border
(`carpet_border`, 12 a piece, about one per 1.3 m of trim) in
corridor.glb, 315 kB with its atlas; the cap rail in code (`railGeo`).

| | before | after |
|---|---|---|
| draw calls, deck 8 | 195 / 94 / 140 / 90 | 195 / 94 / 140 / 90 |
| draw calls, deck 12 | 233 / 80 / 38 / 447 | 233 / 80 / 38 / 447 |
| triangles, deck 8 | 1398.5 / 744.1 / 823.6 / 763.5 k | 1399.0 / 744.6 / 824.0 / 764.0 k |
| triangles, deck 12 | 534.7 / 234.2 / 194.8 / 765.8 k | 536.8 / 234.2 / 195.4 / 771.6 k |
| frame p50, deck 8 | 2822 / 1760 / 2682 / 1745 ms | 2756 / 1797 / 2790 / 1747 ms |
| frame p50, deck 12 | 1743 / 558 / 321 / 2103 ms | 1858 / 583 / 367 / 2458 ms |
| frame p50, deck 12, again | 2042 / 866 / 737 / 2413 ms | 2335 / 847 / 631 / 2234 ms |
| boot (deb / this) | 58.0, 56.7 s | 57.9, 58.1 s |
| shadow redraws | 0 of 20 | 0 of 20 |

+0 calls everywhere. Deck 8 is +0.5 k triangles: its door frames are
paid for by the cap rail, a plain strip and a half-round (~80 triangles a
wall piece) where `rgeo`'s rounded bar was ~300. Deck 12's widest view
is +5.9 k over many cells, well inside +5 k a cell. The frame times
swing ±15 % from run to run on this box, either page (the second pair).

The border as a material of its own (`surf(T.carpet, 0.7, 0x2c3646)`,
floor quads in `corridorDress`), measured on deb's page with only that
change: calls 196 / 99 / 141 / 91 on deck 8 and 240 / 83 / 38 / 460 on
deck 12, +1 to +13, one per corridor cell in view, where part 6 (c) has
+1 for the deck and M.wallCorr took it. So it is in the corridor atlas
instead: +0, at the cost of a plain carpet offline (no glb). The carpet
texture was the other way, but `T.carpet` is every room's carpet and
tiles at 0.7 m, so a band along a wall cannot be in it.

## Measured: the bridge's leftovers (0.237.0 against 0.236.0)

`deckshots.py --only "Main bridge"`, niced, 0.235.0's page (the bridge is
the same on 0.236.0) and this one; `--view prop:conn_chair,1.6` and
`prop:armrest_console,1.6` looked at. Boot from `--only none`, two of
each, alternated, on a box at load ~4 (other sessions).

| | before | after |
|---|---|---|
| draw calls (fwd, port, aft, stbd) | 62 / 65 / 206 / 58 | 62 / 65 / 206 / 58 (+0: the bridge atlas) |
| triangles, every quarter | 473.7-990.3 k | +4.37 k |
| frame p50 (fwd, port, aft, stbd) | 1852 / 1080 / 3612 / 917 ms | 1797 / 1131 / 3214 / 1034 ms |
| boot (two each) | 58.2, 57.8 s | 60.3, 54.5 s |
| shadow redraws | 0 of 8 | 0 of 8 |

The props: conn_chair 1252 x 2, armrest_console 1004 x 2 - +4.5 k, less
the conn chairs' twelve armrest lights (they would float beside an
armless model: `chair(..., lights = false)`). The room's models are
33.1 k in all, under 40 k. `bridge.glb` + atlas 496 kB at 1024² (410 kB
before). Decided on Number One's watch: both built in bridge.py, not
fetched - a conn chair is a few bevelled blocks, and the captain's
addendum (free models from the web) saved nothing here. The conn chair
has no arms (the series' conn and ops chairs have none) and plain
bevelled cushions, not `pad`'s subdivided ones: those are what make the
captain's chair 5 k. The armrest console has no leather lip (no one
leans on it) and keeps the stand-in's display and six lights; its lit
kick goes with the stand-in, as the conn console's does.

## Measured: the ready room's leftovers (0.240.0 against 0.239.0)

`deckshots.py --only "Ready room"`, niced, deb's page (0.239.0) and this
one; `--view prop:` for `bookcase_a`, `bookcase_b` (2.2 m), `rr_sofa`
(2.4) and `rr_armchair` (1.8) looked at. The cabins: `--gen 8:quarters`
(Lt. Cmdr. Mwangi's, 9.8 m wide, so it has the two armchairs) and
`--view prop:lounge_armchair,1.8`. A box at load ~1-3.

| | before | after |
|---|---|---|
| draw calls, ready room (fwd, port, aft, stbd) | 88 / 80 / 139 / 100 | 87 / 80 / 139 / 100 (the instanced books gone) |
| triangles, ready room | 676.0 / 643.1 / 778.8 / 769.0 k | +5.7 / +7.3 / +7.3 / +7.3 k |
| frame p50, ready room | 1575 / 1163 / 2868 / 1386 ms | 1471 / 1147 / 2655 / 1522 ms |
| draw calls, deck 8 quarters | 55 / 62 / 56 / 273 | 55 / 62 / 56 / 272 |
| triangles, deck 8 quarters | 281.1 / 288.8 / 280.5 / 1135.1 k | -2.2 / -2.2 / -2.2 / -1.5 k |
| boot / models landed | 59.9 s / 75.5 s | 59.2, 57.4, 61.2 s / 74.5, 72.4, 76.5 s |
| shadow redraws | 0 of 7 | 0 of 7 |

The props: bookcase_a 1456, bookcase_b 1424, rr_sofa 1132, rr_armchair
756 x 2 in the ready room (+4.5 k of models; the room's models are
12.7 k in all); lounge_armchair 756 x 2 in a cabin. A book is a box
without its back and bottom (8 triangles), a board holds a run or two,
not a full row: full rows were 2.4 k a case. The sofa is common.py's
(lounge.py's moved there unchanged), baked into both atlases: the
lounge's glb in the ready room would have been +1 call for three
seats. **Bytes**: `readyroom.glb` + atlas 796 kB (530 kB before), over
the ~600 kB a 1024² room is allowed; it is geometry (the glb is 589 kB,
~47 B a triangle once quantized), not the atlas. Meshopt compression in
the cleaner would take every room's glb to about a third; left in
TODO.md. `lounge.glb` + atlas 206 kB (184 kB).

## Measured: the concourse's leftovers (0.241.0, measured against 0.238.0)

`deckshots.py --only Concourse`, niced, deb's page at 0.238.0 then this one
(before 0.239.0 and 0.240.0, the crew and the ready room, were under it),
one run each, on a box with other sessions; the balconies' rails and
doors looked at in the quarters and `--view prop:balcony_rail,2.5`.

| | before | after |
|---|---|---|
| draw calls (fwd, port, aft, stbd) | 222 / 125 / 56 / 123 | 222 / 123 / 53 / 121 |
| triangles | 1457.7 / 730.9 / 568.9 / 712.6 k | 1469.0 / 742.1 / 579.7 / 723.5 k |
| frame p50 | 7515 / 1863 / 1204 / 1423 ms | 5782 / 1674 / 1130 / 1346 ms |
| boot / models landed | 60.9 s / 77.5 s | 56.9 s / 71.9 s |
| shadow redraws | 0 of 7 | 0 of 7 |

The props: balcony_rail 50 x 106 bays, rail_post 8 x 108, balcony_door
190 x 26 - +11.2 k a view, the room's models now 28 k in all.
`concourse.glb` + atlas 269 kB at 1024² (192 kB at 0.220.0). No call
more: the rails and doors are in the concourse atlas, the ring's stone
replaces the rainbow's canvas material one for one, and its amber line is
the shared `M.glowAmber` (the calls a few fewer: the crew walk, and a view
counts its busiest frame). Built in concourse.py, not fetched: a bay is
three boxes and a door seven, and a model off the web would have cost
its decimation and a licence for nothing the boxes do not give. A rail
is one 1.6 m bay placed per bay (stretched under 1.5 % to fill a run),
the posts a prop of their own so a corner has one; a whole run as one
model would be a 30 m island the atlas cannot fit at the hall's texel
size. `--view prop:` shoots every placement: 106 bays take it past 10
minutes, so look at a few and stop it.

## Measured: people in the generated decks' rooms (0.242.0 against 0.241.1)

`deckshots.py`, niced, one after the other on a quiet box (load ~0.3, a
deploy just done), deb's page at 0.241.1 then this one, both with this
branch's deckshots (`--gen DECK:TYPE:K`, the Kth room of a type, so both
look into the same room): deck 12's corridor outside its first sickbay,
its first cabin (Crewman Ivanova's: one at the desk), its seventh lab
(the Warp field lab: one at a bench, one at the hologram table), its
ninth sickbay (Medical bay 5 2: one at the office desk, one at a bedside)
and deck 10's third mess (two at one table) - the four quarters of each
(fwd, port, aft, stbd).

| | before | after |
|---|---|---|
| draw calls, deck 12 corridor | 234 / 80 / 37 / 447 | 234 / 81 / 37 / 447 |
| draw calls, cabin | 214 / 155 / 80 / 431 | 214 / 126 / 84 / 431 |
| draw calls, lab | 186 / 201 / 60 / 325 | 186 / 202 / 60 / 330 |
| draw calls, sickbay | 231 / 47 / 33 / 425 | 235 / 47 / 33 / 430 |
| draw calls, mess | 37 / 88 / 266 / 272 | 37 / 92 / 275 / 276 |
| triangles, where people are in view | | +15.6-18.5 k a person (the mess's two: +35.3 k) |
| frame p50, corridor | 1956 / 1039 / 711 / 2256 ms | 2356 / 853 / 499 / 2218 ms |
| frame p50, cabin | 1404 / 1209 / 649 / 2052 ms | 1006 / 821 / 513 / 2333 ms |
| frame p50, lab | 1376 / 1276 / 621 / 1655 ms | 1339 / 1306 / 744 / 1412 ms |
| frame p50, sickbay | 1115 / 487 / 382 / 2136 ms | 1260 / 417 / 394 / 2228 ms |
| frame p50, mess | 608 / 511 / 1693 / 1324 ms | 663 / 652 / 1934 / 1223 ms |
| median over the 20 views | 1242 ms | 1114 ms |
| boot / crew loaded / models | 60.6 / 67.8 / 76.1 s | 62.5 / 70.9 / 79.1 s |
| shadow redraws | 0 of 52 | 0 of 65 (four crew views too) |

A person in view is +4-5 calls (the body, its hair, eyes, brows) and
~16 k triangles; a view with nobody in it is unchanged (+0-1 call). The
cabin's port view at 155 calls in "before" was that run's: deb again gave
125 calls, 304.3 k (after: 126, 304.4 k), whatever neighbour or door it
caught. The p50s move both ways by up to 25 % a view, as the runs always
do in software; the medians agree.

The build behind the lift's fade (`switchDeck(12)`, standing at its first
lift, `tickRooms(true)`; `renderer.compile` apart), eight rides each,
pages alternated: deb 787 / 943 ms, this 846 / 951 ms (run-to-run spread
~150 ms; the four or five people built there cost ~2 ms each). A room
built on the way, one a frame, timed with and without its people on the
same page: a cabin +1-6 ms (one person), a lab, a sickbay or a
conference room +1-5 ms (two).

The caps (`staffDeck`): at most three a room; 24 a deck; and at most 12
(`ROOM_CREW_NEAR`) in the rooms within `DROP_R` of any point of the
deck's streets, which is the most that can be built at once wherever you
walk, so the most whose bones could ever be in view, before the
visibility cull (`crewRoomsSeen`) leaves only those in your room and
behind open doors. Deck 12 gets 18 people in 13 of its 76 rooms, deck 10
(recreation) 19, deck 36 19, two of them in main engineering (staffed
first). The twelve are the
order's figure, checked by the sweep in `deckboot.js`; the frame budget
only ever sees the few in sight.
## Measured: meshopt (0.242.1, measured against 0.241.1, before 0.242.0 was under it)

**On the wire first.** The server sends `/ui/` files as they are: it
gzips JSON only (`HTTPShouldGzip`), and tailscale serve passes the bytes
through - `readyroom.glb` asked for with `Accept-Encoding: gzip, br`, at
the server and through the tailnet, came back 599 304 bytes with no
`Content-Encoding`. So a file's size is what a phone fetches (gzip -9
would have taken a quantized glb to about 0.35-0.5, but serving it is a
server change; meshopt makes it moot for the glbs, and the webp would not
shrink).

**The route.** Meshopt (`EXT_meshopt_compression`, gltf-transform's
`meshopt()` at level "high", meshoptimizer 1.3.0) in the cleaner, in place
of the bare quantizer: alone it puts every room under budget, so no
attribute was dropped (TANGENT stays: deck-model-assets.mjs says why) and
no quantization tightened beyond its normals and tangents, 8-bit
octahedral where they were 10 bits a component. The page's decoder,
`vendor/meshopt_decoder-1.3.0.mjs`, is 29 kB (both its wasm builds,
baseline and SIMD), fetched once with the first room and cached; the
saving is 1.3 MB.

Every room rebuilt by `build.sh` (3 min 20 s, niced); the atlases came out
byte-identical, so the change is the glbs'. Bytes, glb / glb + atlas:

| room | before | after |
|---|---|---|
| arboretum | 80 / 236 kB | 33 / 189 kB |
| bridge | 369 / 507 kB | 138 / 275 kB |
| concourse | 155 / 275 kB | 65 / 184 kB |
| corridor | 207 / 326 kB | 80 / 199 kB |
| hull | 55 / 139 kB | 25 / 109 kB |
| lab | 148 / 236 kB | 57 / 144 kB |
| lounge | 111 / 211 kB | 46 / 146 kB |
| readyroom | 599 / 814 kB | 213 / 428 kB |
| sickbay | 213 / 334 kB | 80 / 201 kB |
| tenforward (2048²) | 156 / 472 kB | 58 / 374 kB |
| all ten | 2.09 / 3.56 MB | 0.79 / 2.25 MB (+29 kB decoder) |

The ready room's glb is ~17 B a triangle (12.7 k), ~47 before. The
biggest room is now the ready room at 428 kB, Ten Forward's 2048² atlas
the biggest part of any room (316 kB).

**Load.** `deckshots.py --only "Ready room,Bridge,Deck 12 sickbay"`
(deck 12's sickbay a generated deck's), niced, deb's page (0.241.1, from
`git archive`) and this one alternated twice on a box at load ~4:

| | before | after |
|---|---|---|
| boot | 59.9, 61.9 s | 44.6, 43.6 s |
| crew landed | 67.5, 70.2 s | 62.0, 67.1 s |
| models landed (10 rooms) | 75.0, 78.3 s | 69.7, 75.5 s |
| views p50 / worst p99 | 1360, 1390 / 2753, 2770 ms | 1332, 1275 / 2887, 2670 ms |
| calls, triangles (Deck 12 sickbay) | 510, 856.8 k | 510, 856.8 k |

The models land within the noise (from a local server: the bytes saved
are a phone's network time, which this box does not see). The decode
itself, every compressed bufferView of a glb through the decoder in node,
best of 20: ready room 0.85 ms, bridge 0.61, Ten Forward 0.22. The boot's
15 s is not this change's (the boot loads no model); both runs of each
were alike, so it is noted, not claimed. The shots before and after are
alike by eye (the ready room's sofas, armchair and bookcase looked at for
banding from the 8-bit normals: none).

The crew's glbs (`deck-crew-assets.mjs`, skinned) followed in 0.248.2:
"Measured: the crew's meshopt".

## Measured: the generated rooms' leftovers (0.243.0, measured against 0.242.0)

`deckshots.py --gen 12:lab --gen 12:quarters --gen 25:mess --only "Deck 12
sickbay,Deck 12 lab,Deck 12 quarters,Deck 25 mess"`, niced, deb's page at
0.242.0 then this one (before 0.242.1's meshopt was under it: calls and
triangles are the same either way), one run each, on a box with other
sessions; `--views-deck 12 --view prop:` for the three shelves at 2 m.

| | before | after |
|---|---|---|
| draw calls, deck 12 sickbay (fwd, port, aft, stbd) | 202 / 53 / 100 / 510 | 202 / 53 / 97 / 510 |
| draw calls, deck 12 lab | 149 / 454 / 121 / 136 | 149 / 454 / 121 / 134 |
| draw calls, deck 12 quarters | 214 / 126 / 84 / 431 | 214 / 125 / 84 / 431 |
| draw calls, deck 25 mess | 67 / 175 / 204 / 419 | 65 / 173 / 202 / 417 |
| triangles, sickbay | 405.3 / 202.8 / 292.8 / 856.8 k | +3.7 / +1.8 / -0.9 / +1.8 k |
| triangles, lab | 388.5 / 799.1 / 381.7 / 335.1 k | +1.8 / +1.8 / +1.8 / -0.8 k |
| triangles, quarters | 483.2 / 304.4 / 244.3 / 775.1 k | +1.9 / +1.3 / +1.9 / +1.9 k |
| triangles, mess | 257.0 / 367.6 / 490.8 / 782.9 k | -23.0 / -21.1 / -23.0 / -23.0 k |
| frame p50 over the 16 views | 912 ms | 1005 ms (the views moved -26 to +21 %, both ways in each room) |
| boot / models landed | 61.7 s / 77.2 s | 61.1 s / 76.1 s |
| shadow redraws | 0 of 44 | 0 of 48 (the shelf views too) |

+0 calls a room: the shelves are in the room's own atlas (the calls a
few fewer: people move, and a view counts its busiest frame). The props:
lab_padd_shelf 1216, sick_padd_shelf 1150, cabin_padd_shelf_a 1308 and
_b 1108 (one a cabin), so +1.2-1.3 k and the rail's two halves a room;
mess_chair 210, four to each of the hall's tables. The mess fell by 21-23
k in all four views, which the chairs alone do not explain (210 against
the stand-in's two rounded boxes and two cylinders, which stay sent,
collapsed): explained in "Measured (0.254.0)" - the hall's chair and
table stand-ins, all collapsed, left merged meshes whose bounding sphere
was a point, culled from those four views. Every generated mess has at most 21 tables (decks 7, 9, 10 and 25
counted in deckboot), so the mess chair fits every hall the tub chair
does not (21 x (480 + 4 x 210) = 27.7 k). **Bytes** (meshopt, 0.242.1's
cleaner): `lab.glb` + atlas 200 kB (141 before), `sickbay` 246 kB (197),
`lounge` 239 kB (142), `tenforward` 387 kB (365) at 2048².

## Measured: Ten Forward's port wall (0.244.0, measured against 0.242.1)

The room's side of the corridor's starboard wall was three 1 cm sheets of
`M.wallTF` above the rail, and the corridor's wainscot, grip and amber
skirting showed below them. It is now lined by `wall(x0, z0, x1, z1, H,
{ face })`: wall()'s own lower and upper panels, rail, and kick with its
dim line, in the room's skin, only on the room's side - each piece a box
from 4 cm inside the corridor wall (no rounded back edge shows) to `face`
in front of the wall's line. Two runs either side of the door, floor to
the room's 4.8 m ceiling, and over the lintel one box of `M.wallTF`; the
0.12 m box that closed the gap above the corridor's ceiling went (the
lining's upper panel closes it). Chosen over a thin wall() stood against
the corridor wall: a two-faced one buries a whole rail, kick and floor
band in the corridor wall for nothing, and needs no block of its own.

- **The face is 9 cm off the line**, 3 cm proud of the corridor wall's:
  that buries the corridor's skirting lip (8.7 cm out, 0-13 cm high) and
  amber slot behind the lining's lower panel, and its grip (11 cm out, at
  0.97-1.03 m) inside the lining's rail (17 cm out, 0.95-1.05 m), and
  leaves the door frame (11 cm) still 2 cm proud of it.
- **The wall display moved out with it** (`X0 + 0.07` to `0.1`).
- No new material: `M.wallLow`, `M.wallTF`, `M.rail`, `M.console`,
  `M.glowDim`, all the room's other walls' already. Static and merged;
  walkable and block() unchanged (the corridor wall's block is the one).

`deckshots.py --only "Ten Forward"`, niced, one run each (on 0.242.1,
before 0.243.0, the generated rooms' leftovers, was under it), with `--view
port,7,-19,1.5708,-0.05` (the door, head on) and `--view
portob,6.5,-13,0.85,-0.1` (the wall down its length).

| | before | after |
|---|---|---|
| draw calls (fwd, port, aft, stbd) | 118 / 112 / 140 / 85 | 118 / 111 / 140 / 85 |
| triangles | 843.1 / 769.5 / 899.7 / 753.4 k | 844.6 / 771.0 / 901.2 / 754.9 k |
| frame p50 | 1895 / 1736 / 2885 / 1149 ms | 2288 / 1719 / 2946 / 1099 ms |
| views port, portob: calls / triangles | 107 / 761.7 k, 133 / 798.6 k | 107 / 763.2 k, 133 / 800.1 k |
| boot / models landed | 42.7 s / 73.9 s | 44.0 s / 76.7 s |
| shadow redraws | 0 of 11 | 0 of 10 |

+1.5 k triangles (the rounded boxes: two runs of four and the lintel's),
no call more (port's one fewer is the crew walking: a view counts its
busiest frame). The frame times are software rendering on a shared box,
within its noise both ways.

## Measured: dressing left out past 4 m on graphics low (0.248.1, measured against 0.247.1)

`deckshots.py`, 390x844, graphics low, SwiftShader, niced, deb's page
(0.247.1) and this branch's, each room's middle looking four ways
(views 0-3). Calls and triangles carry over; the milliseconds are a
software GPU's and move ±15% between runs of the same page.

| view | calls before → after | triangles before → after |
|---|---|---|
| Main bridge 0, 1, 3 | 62, 65, 58 → same | 490.9 k, 481.3 k, 521.7 k → same |
| Main bridge 2 (aft, the corridor through the door) | 208 → 208 | 1017.8 k → 1012.0 k (−5.9 k) |
| Ten Forward 0-3 | 98, 107, 130, 86 → 98, 106, 130, 85 | 778.4 k, 756.2 k, 871.2 k, 756.2 k → −3.9 k, −4.3 k, −5.5 k, −4.0 k |
| Corridor 0-3 (standing in it) | 197, 96, 143, 91 → 198, 97, 144, 92 (+1) | 1410.7 k, 750.4 k, 844.4 k, 768.9 k → −0.4 k, −0.4 k, −1.5 k, 0 |
| Sickbay 0-3 (its trays within 4 m) | 163, 135, 95, 144 → +1 each | 898.1 k, 855.9 k, 810.6 k, 849.6 k → −4.7 k, −14.3 k, −14.0 k, −14.3 k |
| Wing lab (Exobiology, a generated cell) 0-3 | 76, 73, 66, 257 → same | 543.6 k, 301.5 k, 293.3 k, 1157.8 k → −10.4 k, −10.4 k, −10.4 k, −26.2 k |
| frame p50, the 20 views (median) | 1695 ms | 1599 ms (within the runs' noise) |

Near, +1 call (the room's dressing mesh drawn apart); far, the dressing
of every room past 4 m gone, 4-26 k triangles a view, and a call less
where a room's dressing was the only thing its merge drew in view. The
shots before and after match by eye in every view: nothing within 4 m
is missing (sickbay 0's instrument tray at the bed is there in both).

## Measured: the dressing's patches, the code-built dressing, the collapsed merges (0.254.0, measured against 0.253.0)

Three loose ends of 0.248.1:

- **A dressing prop's contact patch** (the vase's, the carving's, the
  sample racks') was in the room's one patch mesh and stayed on the desk
  when the prop went past 4 m. Each dressing mesh's patches are now a
  mesh of their own, its child: they go with it.
- **The code-built dressing** goes in a group a room (`dressGroup`): Ten
  Forward's bottles and glasses, the lounge's three cased ship models,
  the ready room's ship model, two mugs, desk books, teapot and steam, a
  generated cabin's mugs and ship model. Splitting it from the merges by
  material would have been a call a material near (five for a ship
  model), so the merge orders it instead: a group's parts at the head of
  their material's buffer, a second group's at the tail, and drawRange
  leaves out a hidden group's (`dressOrder`, `dressCut`, `dressRange`);
  what is not merged (the bottles are instanced) goes with the group's
  `visible`. **+0 calls.** A third group in one material would stay drawn,
  with a warning; none does (deck 8's lounge and ready room share the
  ship's materials, a cell's merge is its own room's).
  **The 4 m rule alone emptied the bar**: from Ten Forward's middle the
  backlit shelves are 5-7 m off, and showed bare (the lounge's cases
  too). A group with its room's rectangle (all four kinds have one) is
  drawn on low from anywhere in the room as well, and left out from the
  corridor, the next room and the map.
- **The deck 25 mess's missing 21-23 k (0.243.0) was not a lost seat or a
  model placed twice**: every chair and table there is a stand-in, so a
  cell merge whose material held only them (the chairs' fabric, 26.4 k
  triangles; the tables', 7.2 k; the metal, 5.8 k) was all collapsed to
  the cell's origin. Its bounding sphere, first computed after the
  collapse (the models land in the frame the cell is built), was that
  point, radius 0, on the floor under the room's middle: out of all four
  views, so 39 k sent triangles were culled by chance. Not a visible bug,
  but a merge of nothing that was drawn whenever that point was in view,
  and on deck 8 (merged before the models land, its spheres whole) drawn
  always: `hideStandin` now hides a merged mesh once every range in it is
  collapsed. Found with a probe listing the cell's meshes of radius 0.

`deckshots.py`, 390x844, graphics low, SwiftShader, niced, a copy of
deb's page and this branch's, each room's middle looking four ways
(views 0-3). The shots match by eye in every view (the bar's bottles,
the cases, the desk); calls and triangles carry over, the milliseconds
are a software GPU's.

| view | calls before → after | triangles before → after |
|---|---|---|
| Ready room 0-3 | 88, 81, 141, 101 → 87, 81, 136, 93 | 681.1, 649.8, 806.0, 777.8 k → −3.0, −2.9, −29.8, −69.3 k |
| Observation lounge 0-3 | 124, 76, 139, 100 → 114, 73, 130, 86 | 739.5, 692.2, 846.7, 806.1 k → −9.5, −7.5, −27.9, −84.6 k |
| Ten Forward 0-3 | 100, 106, 131, 86 → 96, 99, 123, 81 | 791.7, 756.6, 874.3, 754.7 k → −25.4, −35.8, −45.8, −25.5 k |
| Deck 25 mess 0-3 | 65, 174, 206, 424 → 62, 167, 202, 420 | 229.8, 339.9, 446.9, 723.4 k → 0, −6.6, 0, 0 k |
| frame p50, the 16 views | 1333 ms | 1229 ms (within the runs' noise) |

The calls fewer are the collapsed merges hidden (3 in the mess, 1-14 on
deck 8 by view: the tub chairs', the lounge chairs' and the other
models' stand-ins whose material held nothing else), and Ten Forward's
three bottle meshes and glasses from the next rooms; the triangles are
both, and the code-built dressing of the rooms not stood in (Ten
Forward's ~30 k of bottles from the lounge and the ready room, the two
cabins' next to the mess in view 1). The two were not measured apart.

## Measured: the concourse's last pieces (0.248.0, measured against 0.247.1)

What was left in code in the concourse (deck-style.md part 2, rows 7-10)
is in `concourse.glb`, built by `build.sh concourse` from concourse.py:

- **`plinth`** (1 792 triangles, the hall's hero: ≤ 6 k), over the
  code-built cone, now a stand-in in a group of its own: the floor ring's
  dark honed stone `#3a3632` (its own palette entry, `plinth_stone`), a
  recessed kick, a base course, the batter, a groove at 0.5 m, a bevelled
  top edge and a flat top face round the lit disc. The light line round it
  was `M.glowBlue` 6 cm proud; it is the ring's one amber line carried up,
  `M.glowAmber`, in the groove.
- **`holo_top`** (1 096), the hologram's top - what the code built was the
  bare lit disc: a bronze bezel round it, its lip over the disc's edge, and
  a low bronze emitter boss at its middle with a console-black lens. The
  disc itself stays the page's (the atlas carries no emission). Placed at
  the plinth's axis with no stand-in, no contact patch.
- **`slab_edge`** (26: no ends, no back), a 1.6 m bay under each of the rail's (placed with
  them, the same stretch): in the slab's putty (`#d6c4a6`, `M.wall`'s), an
  8 mm lip over the slab's top, a bevel to a fascia 12.5 cm out with a
  shadow reveal, a drip lip 6 cm below the slab that hides the amber light
  from across the hall, and the soffit's cove it hangs in. The slab's box
  and underside stay the page's. Where a front-run bay crosses a side
  run's at a corner, the front run sits 1 mm higher so no two faces share a
  plane.
- **`balcony_rail`** 46 to 54: each bay a framed pane, a bronze bead on
  the glass's hall side over the shoe and under the channel and a stile
  through it at each end (none on the wall side: the balconies are never
  walked on). Paid for by its hidden faces: the joined bay was in the
  handrail's frame (0.93 up) when its faces were picked by height, so since
  0.241.0 the handrail's and channel's undersides were dropped and the
  shoe's foot kept; it is put in the prop's frame first now, and the
  handrail's bevel at the bay's ends (24 triangles, butted on the next bay)
  goes too. **The glass stays code**, `M.glass`: the atlas is one opaque
  material, and a second, transparent one would be a call; no new material.

`deckshots.py --only Concourse`, niced, one run each, deb's page from `git
archive` before; `--view plinth,0,25.2,3.1416,-0.12` and `--view
balcony,-11,34,1.5708,0.42` (the forward balconies from the floor); after,
also `--view plinthnear,0,27.6,3.1416,-0.35` (the bezel and emitter).

| | before | after |
|---|---|---|
| draw calls (fwd, port, aft, stbd) | 223 / 128 / 56 / 125 | 223 / 123 / 54 / 119 |
| triangles | 1479.3 / 747.6 / 584.9 / 728.9 k | 1485.4 / 751.8 / 590.7 / 733.1 k |
| frame p50 | 9236 / 1657 / 1295 / 1293 ms | 5330 / 1692 / 1232 / 1524 ms |
| views plinth, balcony: calls / triangles | 57 / 585.0 k, 136 / 759.5 k | 55 / 590.7 k, 135 / 765.3 k |
| boot / models landed | 57.0 s / 75.5 s | 45.3 s / 77.8 s |
| shadow redraws | 0 of 11 | 0 of 14 (three views more) |

+6.1 k triangles in the forward view (the whole hall). The room's models
with every prop in, placements times triangles: benches 7.0 k, columns
9.4 k, directories 0.8 k, planters 3.6 k, rails 5.7 k (106 bays), posts
0.9 k, doors 4.9 k (26), slab edges 2.8 k, plinth 1.8 k, its top 1.1 k -
38.0 k, inside part 4's +40 k (a first cut, with beads both sides of the
glass and the slab bays' ends, came to 46 k and was trimmed). No call more: the new
pieces merge into the room's one atlas mesh, and the blue band's call went
into the amber glow's (the fewer calls are that and the crew walking). The
glb 64 to 97 kB, glb + atlas 184 to 226 kB, under the 600 kB budget. Frame
times are software rendering on a shared box, its noise both ways.

## Measured: the corridor's leftovers in code (0.247.1, measured against 0.246.0)

Two of the corridor's leftovers (deck-style.md part 6). **The carpet
border offline**: under each piece of corridor.glb's `carpet_border`, a
0.3 m strip 3 mm up in the floor's own material (`borderFloor`,
`borderGeo`): its u lifted by 4096 whole repeats, which the wrapped maps
do not see, and the floor's shader (one `onBeforeCompile` on the floor
material) tints what is past 2048 to `#2c3646`. It merges into the floor's
mesh, and is a stand-in, collapsed when the model lands, so the two never
fight. **The replicator's back** is a lit alcove: a 64x128 canvas, a warm
white head falling to a dim amber foot and darker at its sides, in one
`MeshBasicMaterial` every replicator shares (`replicatorBack`), glow-bright
at the head as `M.glowWarm` was.

`deckshots.py --only Corridor --view prop:alcove_replicator,1.6` (deck 8's
main corridor's four quarters, then 1.6 m in front of each replicator
placed on deck 8, generated cells' included), niced, one run each page,
models landed and held back (`--no-models`, new: the rooms' glbs refused,
as offline). The shots, before/after: the border along both walls with
no models, and the replicator's back.

| | before | after |
|---|---|---|
| draw calls, models (fwd, port, aft, stbd) | 195 / 94 / 143 / 90 | 196 / 95 / 143 / 91 |
| draw calls, no models | 189 / 89 / 136 / 86 | 190 / 90 / 137 / 87 |
| triangles, models | 1410.5 / 750.3 / 844.4 / 768.8 k | 1410.6 / 750.4 / 844.4 / 768.9 k |
| triangles, no models | 1254.7 / 675.9 / 738.8 / 677.9 k | 1254.8 / 676.0 / 738.9 / 678.0 k |
| replicator views 2-8, calls (models) | 79 / 124 / 37 / 46 / 37 / 46 / 38 | 80 / 126 / 38 / 47 / 38 / 47 / 39 |
| boot / models landed | 47.3 s / 80.2 s | 53.8 s / 72.2 s |
| shadow redraws | 0 of 36 | 0 of 37 |

The border is +0 calls, as meant, and ~+0.1 k triangles (two a piece).
The replicator's material is +1 where one is in view (the deck's merged
mesh, or a generated cell with one), +2 where two cells with one are
(view 3): the budget Number One gave it. Replicator views 0 and 1 are
left out: their calls swing with which rooms are built in time
(-3 and +2 on a rerun of each page). Frame times are software rendering on
a shared box, within its noise (the after runs' p50 1163 against 1414 ms).

## Measured: the crew's meshopt (0.248.2, measured against 0.248.1)

**On the wire.** Every file in `lcars-ui/crew/` but LICENSE.txt is
fetched at boot on every phone (`loadCrew`: both bodies, all nine hair
styles, the clips, seven webp), sent as it is (no gzip, "Measured:
meshopt"). Before: 1 755 552 B of glb and 222 656 B of webp, 1.98 MB.

**The route.** `deck-crew-assets.mjs` as the rooms' cleaner, with two
differences. A body or hair: `meshopt()`'s level "high" by hand (reorder
for size, the quantizer, `EXT_meshopt_compression` with its filters),
because `meshopt()` would quantize the UVs and the crew's stay floats
(the eyes' run outside 0..1). Positions 14 bits and weights 8 as before;
normals 8-bit octahedral (were 10 bits), as the rooms'; JOINTS_0 and
WEIGHTS_0 take no filter, the codec stores them exactly. The clips:
the codec without filters, so every keyframe is the float it was (the
filters would make rotations 16-bit quaternions and the pelvis's height
a 12-bit mantissa). three's GLTFLoader decodes the bufferViews before
it builds anything, skinned or not; the page's code reads the
attributes through `fromBufferAttribute`/`getComponent`, which take
the interleaved, normalized 8-bit normals as they come. Rebuilt by
`deck-crew-build.sh` (16 s; Blender's hair and poses came out
byte-identical, as did the webp; LICENSE.txt untouched).

**What decodes.** Every glb read back in node and matched vertex by
vertex against 0.248.1's: positions, joints, weights, UVs and inverse
binds identical, every vertex found; normals within 1.35° (hair_Long's
worst; the bodies 1.15°); 32 378 keyframe values in 11 clips, none
different. In the page both builds give 37 bodies, 620 873 triangles,
mesh for mesh.

| file | before | after |
|---|---|---|
| male.glb / female.glb | 387 / 403 kB | 171 / 177 kB |
| nine hair glbs | 713 kB | 372 kB (each 0.45-0.68) |
| clips.glb | 252 kB | 240 kB (filters would give 193) |
| all glbs | 1.76 MB | 0.96 MB |
| with the webp | 1.98 MB | 1.18 MB, +29 kB decoder: 1.21 MB |

The decoder is now fetched at boot, with the crew, where it came with
the first room's glb (the rooms then find it loaded). Reading all twelve
glbs in node, best of 10: 102 ms before, 119 after (gltf-transform's
read, decode included).

**Load.** `deckshots.py --only none --view crew:0 --view crew:1`,
niced, deb's page (0.248.1, `git archive`) and this one alternated
twice, box at load ~4:

| | before | after |
|---|---|---|
| boot | 59.7, 43.0 s | 61.1, 37.2 s |
| crew landed | 70.3, 60.4 s | 70.3, 60.6 s |
| models landed | 77.4, 68.0 s | 77.9, 69.1 s |
| crew close-ups p50 | 5074 / 1610, 4836 / 2020 ms | 4785 / 1444, 4790 / 1461 ms |
| calls, triangles (crew:0) | 245, 1 577 966 | 245, 1 577 966 |

The crew lands within the noise from a local server: the 0.8 MB saved is
a phone's network time, which this box does not see.

**Close-ups.** Two standing officers held mid-step (the walk clip alone,
at 30% of its length, every frame), body, face and hair at 0.75 m, on
graphics low at 390x844 x3, before and after: alike by eye, no banding
in the skin or hair from the 8-bit normals, the step's pose the same
(published as "Crew meshopt: close-ups before and after"; only the
heads' glances differ, which are random per run).

## Measured: deck 8's last code-built furniture (0.250.0, measured against 0.249.0)

The four shelves outside the ready room and a cabin's wardrobe, as
models over their stand-ins (`padShelf()` and `cabinet()` still build,
register the shelf slots and block the floor, so pinning and aiming are
as they were; the amber strips stay over the models). **Ten Forward's
two** (`dressShip`, on its forward wall by the corridor's door): in
`tenforward.glb`, `tf_padd_shelf_a`/`_b`, common.py's rack and the ready
room's two arrangements in the ready room's colours. **The lounge's
two**: in `lounge.glb`, `lounge_padd_shelf_a`/`_b`, the same rack and
arrangements on the lounge's table wood (`rail_wood`), its ashlar's grey
sides (`lounge_grey`) and a black back. **The wardrobe**: common.py's
`wardrobe()`, `cabin_wardrobe` in `lounge.glb` (the cabins' glb), 1.4 x
2.25 x 0.55 to `cabinet()`'s measures, two panelled doors either side
of the strip's slot, a recessed plinth, a top rail, in the cabin's wood
(`cabin_wood`, M.wood's hex); the 1.2 one the page builds where the
aisle leaves less takes it squeezed across (`scale`), its slot still in
the middle.

`deckshots.py --gen 8:quarters --only "Observation lounge,Ten
Forward,Deck 8 quarters"`, niced, deb's page (0.249.0) from `git
archive` then this one, one run each, plus a look at each set of shelves
from 2.7 m; the props at 2 m (`--view prop:`). A cabin's placements are
only found with the cabin the last room shot and nothing after it on the
deck: a run with the lounge and Ten Forward too printed `not placed` for
the wardrobe, so its views are a run of its own (`--only "Deck 8
quarters" --view prop:cabin_wardrobe,2`).

| | before | after |
|---|---|---|
| draw calls, lounge (fwd, port, aft, stbd) | 144 / 77 / 135 / 140 | 144 / 76 / 133 / 140 |
| draw calls, Ten Forward | 117 / 113 / 130 / 86 | 97 / 106 / 130 / 85 |
| draw calls, deck 8 quarters (Mwangi's) | 56 / 63 / 59 / 292 | 56 / 64 / 57 / 292 |
| triangles, lounge | 801.7 / 689.9 / 825.5 / 937.3 k | +2.4 / +2.3 / +2.3 / +4.8 k |
| triangles, Ten Forward | 841.6 / 783.8 / 871.8 / 752.3 k | -65.0 / -27.1 / +2.4 / +2.3 k |
| triangles, quarters | 271.0 / 278.7 / 270.5 / 1153.7 k | +0.5 / +0.6 / +0.4 / +5.4 k |
| the shelves' looks, calls / triangles | TF 88 / 743.6 k, lounge 138 / 770.9 k | TF 88 / 746.0 k, lounge 139 / 815.0 k |
| boot / models landed | 37.5 s / 71.9 s | 38.4 s / 70.4 s |
| shadow redraws | 0 of 31 | 0 of 37 |

+0 calls a room: each in its room's own atlas. Ten Forward's first two
views fell by 20 and 7 calls and 65 and 27 k triangles, which no model
added here can take away: the crew walk through them (not chased); where the shelves are in view the rest moved
by the props' triangles. The props: the shelves 1308 (a) and 1108 (b) in
each glb, the wardrobe 548, so +2.4 k a room for the shelves and +0.5 k
a cabin (the stbd quarters view looks out through the cabins along the
deck: +5.4 k is ten of them). The lounge's look at its shelves: +44 k, of
which the shelves are 2.4 k and the rest a crewman walking into it.
**Bytes**: `lounge.glb` + atlas 296 kB (239 before), still 1024²;
`tenforward` 539 kB (387) at 2048²; both in their budgets. Frame times
are software rendering on a shared box (view p50 1213 against 1453 ms).
Published as "Deck 8 shelves and wardrobe: before and after".

## Measured: PADD piles (0.252.0, measured against 0.250.0)

Stacking adds no geometry: a pile is the pins' own pads, and the ghost
is the one there was. `deckshots.py --only "Ready room,Ten Forward"`,
niced, deb's page from `git archive` then this one, one run each.

| | before | after |
|---|---|---|
| draw calls, ready room (fwd, port, aft, stbd) | 88 / 81 / 141 / 101 | 88 / 81 / 141 / 101 |
| draw calls, Ten Forward | 97 / 106 / 130 / 86 | 97 / 104 / 130 / 86 |
| triangles, ready room | 681.1 / 649.8 / 806.0 / 777.8 k | the same |
| triangles, Ten Forward | 776.6 / 756.7 / 874.2 / 754.7 k | +0 / -0.1 / +0 / +0 k |
| shadow redraws | 0 of 15 | 0 of 15 |

Ten Forward's port view moved by 2 calls and 84 triangles: the crew
walking through it, as in earlier rounds. The aim's extra work is one
upward raycast against the near pinnable surfaces per frame, and only
while a PADD is in hand and a lying one is aimed at; a throw in flight
also casts against the lying pads (a handful of meshes).

## Where files live

- `scripts/deck-models/<room>.py` - a room's Blender script
- `scripts/deck-models/common.py`, `pack.py`, `fetch_polyhaven.py`,
  `build.sh` - the shared helpers, the converter, the fetcher, the build
- `scripts/deck-models/gen.py`, `fit.py` - the generated road: the views
  and the 3D job on Higgsfield, priced first, and the fit in Blender
  ("A generated prop", above); `scripts/test_gen.py` its test
- `MEDIA/media/deck-models/<prop>/` - a generated prop's glb, licence and
  raw files (the media store; `build.sh` copies the glb into the cache)
- `scripts/deck-model-assets.mjs` - the cleaner
- `lcars-ui/deck/<room>.glb`, `<room>_{base,norm,orm}.webp` - what the
  page loads (served statically, as `lcars-ui/crew/`); committed, so the
  deck never needs Blender at runtime
- `lcars-ui/deck/LICENSE.txt` - one section per glb
- `~/.cache/lcars-deck-models/` - downloads and npm packages, never
  committed

## Decisions taken without the captain (2026-10-15)

- **The origin of a model that replaces a stand-in is the stand-in's**,
  not its footprint's middle (part 4, rule 7): the chair's origin is
  under its pedestal, as `chair()`'s group is, so the seat and the armrest
  lights land where the code put them. Its front is still +z; a deck-8
  chair faces -z, so its placement turns it (`rot: Math.PI`). A pack's
  props are set at their footprint's middle (they have no stand-in).
- **Stand-ins are collapsed, not removed**, as above; their triangles stay
  in the counts.
- **The pipeline's bridge prop is the captain's chair** (deck-style part
  2's first), and it stands in for all three command chairs (the captain's
  stretched 1.15 across, as its stand-in is): three heroes, the room's
  limit. The conn and ops chairs stay code-built for the bridge's slice.
- **The pack test is two Poly Haven models** treated as one pack, the
  "readyroom" glb: a carved wooden elephant on the tea table (placed at
  2.2 times Poly Haven's 11 cm, a carving that reads from a sofa) and a
  brass vase on the desk (1.4 times). Poly Haven's models come one asset
  per download, so "a pack" here is a folder of them; the converter takes
  any folder of glb/gltf/obj. A third, the ceramic vase, was dropped: see
  "not for thin-walled models" above.
- **Dressing at 200 triangles with the original's detail baked in**: the
  decimation keeps the silhouette, the normal map the carving.
- **The ready room's glb is a pack, the bridge's a script**: a room that
  wants both later imports the pack's files in its script as `pack.py`
  does (import, join, decimate, then `finish_room` with `sources`), so a
  room is still one atlas; `pack.py`'s loop moves into `common.py` then.
- **No CPU budget for the bake beyond nice**: three threads, ~1 minute a
  room at 1024², ~30 s a 512² pack.
- **A pack of a few dressing pieces bakes at 512²** (`pack.py --size`),
  not 1024: the cleaner keeps the size it was baked at.
- **The bridge's slice (0.215.0)**, decided on Number One's watch:
  - **Every model is built to its stand-in's measures, not part 2's
    sizes**: the station is 1.8 x 0.45 x 0.9 (the stand-in's) rather than
    1.2 x 0.6 x 1.1, the console 1.6 x 0.8 at the top. The stand-ins'
    displays, lights and blocks stay where the code put them, and the
    models are built round them.
  - **A stand-in part can stay over its model** (`userData.over`):
    the consoles' and stations' displays (their own textures, which the
    atlas cannot hold) sit in recesses the models leave for them, and the
    stations' lit slot is the stand-in's glow strip in the model's dark
    slot. Anything glowing stays in the shared glow and blink materials:
    the tactical panel is the model's black face in a bezel, lit by a
    `glowDim` plate and two rows of blinking lights placed outside the
    stand-in.
  - **The tactical rail is one model for both arcs**, its origin at the
    circle's centre (each arc's stand-in a group turned to its start), and
    each arc has its tactical panel at its middle, where the tactical
    officer stands.
  - **Conn and ops are one model**, as ordered; their chairs stay
    code-built (the captain's at 0.9 would be +10 k: the room would still
    fit, but the three heroes are spent).
  - **The palette costs no draw call where it can avoid one**: the carpet
    is the bridge's own material, recoloured; the leather is recoloured
    in `M.leather` itself (every deck-8 chair, the bar's pad), not a second
    leather; the rail wood is `M.rail` recoloured and lacquered (the
    handrails and display frames with it: they are rail wood too); only the
    beams are a new material (`M.beam`). The tactical rail's two cloned
    wainscot materials became one. Net: +1 call looking forward, 0 or -1
    elsewhere.
  - **One atlas at 1024²**: the captain's chair at 1.3 m still reads its
    leather and piping with four props sharing the atlas, so not 2048.
  - **Station end panels in brushed trim**, not the body's near-black:
    in the console colour the seam and the panels vanished.
- **`deckshots.py --view`** for the close look the four quarters miss:
  `--view prop:captain_chair,1.6` stands 1.6 m before each placement of a
  prop (from `__deck.modelSpots()`), `--view NAME,x,z,yaw,pitch` anywhere;
  `--only none` skips the rooms.
- **Ten Forward's slice (0.216.0)**, decided on Number One's watch:
  - **The atlas is 2048²** (a hero room: the bar is 9 m). At 1024 the bar
    takes most of it and a chair gets ~110 px across. 434 kB in all.
  - **The chair is 976 triangles, not the 1.5 k furniture allows**: there
    are 30 of them, and at 1.5 k they alone were 45 k, past the room's
    40 k. The table is 480 for the same reason. The tub's rim has one
    bevel segment, and the seam and welt are 12-14 sided.
  - **The glass leans in at its head** (the saucer's edge leans over the
    room): 20° from the sill (0.45) to the head (4.35) brings the head
    1.42 m in. The band above it moves in with it, and a cheek closes the
    wedge at each end of a run. `windowWall(..., { rake, seat })`; no other
    room uses either.
  - **The window seat replaces the wooden sill** (0.5 m deep, its top at
    the sill, seatable every 1.3 m), in a fourth material of the room's
    own, `M.sillTF` #2e2a36: deck-style gives no hex for it, so it is a
    darker shade of the chair fabric.
  - **The bar's curved end turns back to the aft wall** at its starboard
    end, inside the stand-in's length (the straight is 6.9 m of the 8).
    The rail, the bar's two amber lines and the display glass stop where
    the curve starts. The kick light is amber, as part 2 says, in place of
    the dim line.
  - **What stays code-built over the bar model**: its lights (glow), the
    display shelf's glass (`M.glass`) and the foot rail (`M.brass`). The
    atlas has no emission or alpha, and these materials are drawn on the
    deck anyway, so they add no draw call.
  - **The port wall is lined, not reskinned**: it is the corridor's
    starboard wall, one mesh with putty on both faces. Since 0.244.0 the
    lining is `wall(..., { face })`, wall()'s one-faced variant (see
    "Measured: Ten Forward's port wall").
  - **Code-side materials only where the order named them**: M.wallTF,
    M.topTF, M.barTF and M.sillTF, four of the six allowed. The chair
    fabric was already #544a66 (M.fabric).
- **The ready room and the lounge (0.217.0)**, decided on Number One's
  watch, the captain asleep:
  - **A room script may carry a pack** (the doc's own forecast):
    `readyroom.py` imports the elephant and vase with
    `common.import_pack`, pack.py's loop moved there, and bakes them
    with its own props in one atlas. The bake does the spread-out copy
    of everything first (the pack's low copies too, through their own
    materials: wrong colours, but only their margins keep them), then
    each pack prop from its original with a two-pixel margin, inside
    the packer's gap. `build.sh`'s `fetch()` hands the script the
    download folder; `pack()` stays for a room of a pack alone.
  - **A room script may add colours of its own** to `C.PALETTE` at its
    top (the ready room's book cloth, fish, gravel, weed): the shared
    hexes stay in common.py, untouched.
  - **The desk is built to its stand-in, 2.0 x 0.9**, not part 2's 1.8;
    its curved front faces the window (the far side from the chair), and
    the stand-in's screen stays over the model's terminal, which keeps
    the screen's tilt. 2.3 k triangles: a hero, well under 6 k.
  - **The PADD shelves are two models, one rack with two arrangements**,
    alternated along each wall, so seven shelves do not repeat one
    picture. The dressing takes a third of four boards at most: the
    shelves are where entries are pinned, and a pinned PADD may still
    stand beside a book. The amber strips stay the stand-in's
    (`padShelf` marks them `over`, the lounge's too, harmless there).
  - **The fish tank keeps the page's glass and water** (`M.glass`, as
    ordered, and `M.water`, its only user, thinned from 0.8 to 0.4
    opacity: at 0.8 the gravel and fish cards were a blue wall). The
    swimming fish stay the page's.
  - **The lounge's chair is over all twelve stand-ins**, not ten: ten
    down the sides and one at each end, and a red chair left at each
    end would read as a mistake. The ends keep their 0.95 stretch.
  - **The lounge's atlas is 512²**: one furniture prop alone gets the
    texel density four get at 1024², for a quarter of the bytes.
  - **The lounge table is `M.rail`**, the lacquered rail wood (#5a3a28,
    0.35), not a new #4a3022 material: darker and lacquered as ordered,
    and a material deck 8 draws already, so it costs no call (the
    atlas is the lounge's one). The desk's #4a3022 lacquer is the
    palette's desk_wood, in the atlas.
  - **The sofa colour is global**: `M.sofa` is every sofa's and
    armchair's (the generated quarters' too), warm grey everywhere, as
    the bridge's leather was recoloured in place.
  - **`sw.js` was left alone**: it caches every same-origin file of the
    page alike (stale-while-revalidate), with no rule for `crew/`, so
    `deck/` already has the same treatment.
- **The corridor and the arboretum (0.218.0)**, decided on Number One's
  watch, the captain asleep:
  - **Only deck 8's own corridor is dressed** (`corridorDress({ models:
    true })` from `dressShip`): the other corridors are built in cells
    after `loadModels` has run, the pipeline gap TODO.md keeps. They keep
    the stand-in panel, which now has the model's measures. (Since 0.222.0 every corridor is: see below.)
  - **The comm panel's stand-in was resized to part 2's 0.18 x 0.3**
    (from 0.22 x 0.34), in a group facing the corridor, and the model built
    to it: the order's measure, not the stand-in's, since the stand-in was
    a box nobody had placed to anything. Its strip and indicator stay the
    stand-in's glows (`userData.over`); the buttons are the atlas's LCARS
    peach and lilac, unlit.
  - **The door plaque is a bezel round the name, not a 0.4 m plate with
    a number**: the lintel already carries the room's name (1.1 x 0.2, its
    own canvas, renamed live by `plates`), and a plate of the order's size
    would have covered a third of it. The bezel's opening is the name's,
    1.12 x 0.21; the name stays over it, 5 mm into its 2 cm depth. On the
    corridor's face only, and on the bridge door's.
  - **Three PADD racks** (port -15.0 and 5.8, starboard -1.9), each
    between two ribs and clear of the doors, displays and hatches. No
    stand-in: offline, the corridor is as it was. 200 triangles is
    tight: only the plate and the PADD bodies are bevelled.
  - **`model(..., { shadow: false })`** for a placement hung on a wall:
    the contact patch a free-standing placement gets would float in the
    air under a plaque.
  - **The fountain is built to the order's 1.2 m, and its stand-in to
    the model**: the old bowl was 1.44 across with its water at 0.635;
    now pedestal and basin are cylinders to the model's measures, the
    water 0.53 m round at 0.855 in the basin's bore. Its stone is a
    shade warmer and lighter than the stepping stones (#a89e8c), mottled
    and bumped in the bake (`mottle` in arboretum.py), so the basin reads
    against the path. 20 sides on the pedestal, 40 on the basin (ten
    gadroons under it, ten scallops on the lip): 1360 triangles.
  - **The bench is built to its stand-in** (the slats 1.46, the seat at
    0.46 where the page seats its sitters, ends at +-0.64), not part 2's
    1.6 m: the block and the seats stay the stand-in's. Weathered: the
    wood's colour drifts toward a silver grey in the bake. Only the
    arboretum's four: the concourse's benches, the same `bench()`, are
    its slice's.
  - **The stepping stones keep `M.stone`**, recoloured to #9a9284 at
    roughness 0.95, with a colour map of its own (`stoneMap`: T.pebble's
    grain, a broad mottle, a warm-cool drift, a few dark flecks; texSet's
    maps are grey), on T.pebble's relief. The pond's rim, its only other
    user, goes with it. No draw call.
  - **The raised beds were wood boxes**: now a kerb of `M.ashlar` (the
    walls', no call) 12 cm thick round a soil top sunk 4 cm, and the five
    beds share one soil material (each made its own before).
  - **Dressing is not culled past 4 m on graphics low** (part 4): each
    room's placements are one merged mesh, so there is nothing to cull
    one by one; 3.9 k triangles in all did not justify a second mesh.
- **The crew, part 3 (0.219.0)**, decided on Number One's watch, the
  captain asleep:
  - **The insignia are code-built, not a glb**: an oval and a delta
    extruded from shapes and up to three cylinders, merged into one
    geometry per body and pip count (cached), in `crewMats.badge`. A
    crew.glb would be a request and a load for well under a kilobyte, and
    a merged geometry keeps a person's insignia one draw.
  - **The pips ride the chest bone, not the neck**: they are on the
    collar, which is the chest's skin, and the neck turns with the head's
    look; and with the badge on the same bone they merge into one mesh.
  - **Pips follow the rank a person gives when spoken to** (`crewRank`,
    which personaOf now uses): Ensign and Chief one, Lieutenant two,
    Lieutenant Commander three. Four are a captain's, so nobody on screen
    wears four: there is no Commander in TALK_RANKS, and adding one would
    reshuffle every seeded rank. A rank no longer changes when the bodies
    load (it used the female draw's slot before them).
  - **The combadge sits on the yoke's black, high on the left chest**,
    6 mm proud of the skin (the clips move the skin a little from its
    bone's hold), with a faint emissive glow: metal 0.9 reflects the room's
    dark away from the eye at a distance. At 2.5 m it is a gold glint; at
    0.7 m the delta on its oval reads.
  - **Slimming is in the inverse binds, not the bones' scale**: a bone's
    scale carries on to its children, so 0.9 at the chest shrinks the head
    and arms, and once a clip turns an arm, non-uniform scale shears it.
    `boneInverses[j]` premultiplied by a 0.9 scale across the bone (its
    local x and z; this rig's bones point along y) narrows only the skin
    weighted to it. The clips are unchanged and still fit: an arm is
    thinner against the torso, never inside it.
  - **The seams are lines in the shader** (3 mm, half dark) along the
    yoke's edge and round the shoulder in a band at the arm's height, so
    they never run down the flanks. The yoke's seam is near invisible on
    black; the shoulder's reads at a metre.
  - **The boots are the trousers' black, roughness 0.3 below 9 cm under
    the knee joint**: gloss alone is the difference, as on screen.
  - **Breathing is the chest bone's uniform scale (±1.4%) with its three
    children (neck, clavicles) scaled back**: a uniform scale is undone
    exactly by its inverse whatever the rotation, so only the chest's own
    skin moves, 2-3 mm, and the shoulders and head rise with it.
  - **The weight shift is a clip** (0.249.0; before, crewLife's 2 cm by
    hand): `Idle_Shift_Loop`, baked in deck-crew-poses.py on the idle's
    first pose held still - the pelvis 2.2 cm to a foot and back over
    7.5 s, that side 2° up, the spine leaning back 2.8° over it and the
    neck levelling the head, the feet held by IK on the legs. The page
    makes it additive (relative to its first frame, the weight even) and
    keeps its nine moving bones' tracks; each stander plays it at their
    own point, weighted by how still they are (`c.still`: walking and a
    reach at a console fade it), as the idles are against the walk.
  - **Saccades**: a new aim every 0.8-3.5 s (a third of them straight
    ahead), ±0.45 rad of turn and ±0.12 of nod, reached in ~0.1 s; you,
    when near and in front, are turned to slowly as before.
  - **Blinks** (0.249.0): shut 0.15 s every 3-7 s, by each person's
    seed. The rig has no eyelids, no morph targets and no eye bones, and
    the eyes are two balls behind an almond opening: squashed, they still
    show their irises. So the eye mesh (and the brows part's pale strip
    across each opening) is skinned to a bone of its own, "eyes", one
    more in each person's skeleton (no draw, no material); a blink shrinks
    it to nothing, and the body's shader paints the sockets left behind
    as closed lids, the skin's mean colour, linear, toned, matte, with a
    lash line (`crewBodyMat`, by the balls' middles and radius at rest,
    `cut.eyeL`/`eyeR`/`eyeRad`). The lids are painted always; the balls
    hide them while open. `deckshots.py --eval "__deck.blinkHold(true)"`
    holds every eye shut for a look.
  - **Turns are a critically damped spring** (ω 14: ~0.3 s), solved
    exactly per frame so a 1 s frame cannot overshoot; **the pace** is
    rate-limited to a full stop or start in 0.4 s, and walkers slow into
    a waypoint they wait at and into an order's end.
  - **Stepping aside is "both keep right"**: a walker with another close
    ahead coming the other way drifts to its right at 0.4 of its pace
    while it lasts, if the floor there is walkable. A dozen lines in
    walkCrew; standers are not stepped round (they never were).
  - **Measured on one page before the badge's last move** (raised and
    set forward): the same triangles, and the box was too busy for a
    second full run (its screenshots timed out).
- **The crew's leftovers (0.239.0)**, on Number One's order, the
  captain having said yes to fetching the packs and to free models:
  - **The packs come from itch.io by script** (`deck-crew-fetch.py`): the
    page's csrf token posted to `/download_url`, then to `/file/<upload>`
    on the download page, gives a signed link that lives a minute. A
    script's own user agent is answered 429, and so is anything quicker
    than a few seconds a request: a browser's agent, 3 s between steps, a
    429 waited out. The zips and what they unzip to stay in the cache.
  - **Nothing from elsewhere**: every clip and hair shares the one rig, so
    a model from another source would need retargeting or its own bones
    per person (the budget forbids more bones). The second Animation
    Library is the same rig, node for node, and has the arms folded.
  - **Hands behind the back and the PADD read are made in Blender**: the
    first library's Idle_Loop with IK on the forearms (chain 2: forearm and
    upper arm; on the hand it moved the forearm alone) to targets riding
    the spine, baked with visual keying, so the arms sway with the body;
    the PADD's head is a damped track, 0.55 of the way to the PADD. The
    glTF round trip through Blender is exact on the bones it did not
    touch (checked against the pack's keys). The assets script copies
    the clips onto the first library's nodes by name.
  - **The PADD is placed from the bodies, not the pose**: the bodies' arms
    are shorter than the mannequin's, so the hands do not meet where the
    pose put the PADD; it is set between the measured wrists, turned to
    the face, and carried by the left hand. One draw (a vertex-coloured
    box), the only one added.
  - **The hair is reshaped, not modelled**: laid onto the pack's own buzzed
    scalp (the closest point, 3-4 mm proud), cut with a plane, and a
    14-sided tapered tube for the tail; every vertex on the head bone,
    and the import's custom normals cleared (the new faces shaded flat
    under them). Bob 108 kB, Ponytail 97, Short 51.
  - **The uniform is the shader's, not a mesh or a baked map**: a mesh
    over the body is a second skinned draw a person, with weights of its
    own; a baked cloth normal map is a texture per body replacing the
    skin's. What made the bodysuit was the skin's normal map, which
    `crewBodyMat` meant to flatten under cloth since 0.219.0 and never
    did: `mapN.xy *= normalScale` is inside `normal_fragment_maps`, and
    onBeforeCompile sees only the `#include`. The chunk is now put in
    whole and changed. The body's own normals under the cloth are a
    Taubin-smoothed copy's (24 steps, at load, ~7 k vertices a body):
    averaging the normals would cancel round an arm. The relief is a bump
    from the bind position through screen derivatives (no tangents, no
    texture), each ripple faded out before a pixel spans a third of its
    period.
  - **The boots are pushed, not modelled**: 6 mm along the unposed normal
    before skinning, in the stored (quantized) units, so the same uniform
    for every person of a body.
  - **Stop/start is timed, not a clip** (no pack has one): `gaitBlend`
    keeps the walk until its pelvis is at its highest (the legs passing),
    read from the clip at load, then a 0.25 s blend, held 0.35 s at most.
- **The concourse (0.220.0)**, decided on Number One's watch, the
  captain asleep:
  - **The plinth's LCARS rainbow ring stays** (Number One's order): part 1
    proposes dark stone with one amber line, and the captain has not seen
    that proposal. TODO.md keeps it.
  - **The bench is the order's 2.4 m, and its stand-in was rebuilt to the
    model**: `ringBench()`, three straight seats along the arc on three
    legs, where it was the garden `bench()` (1.4 m, with a back). Backless,
    as the order's 0.45 m height says; the seat's top stays at 0.46,
    where the page and the crew (two sit there) seat their sitters. The
    arc is the ring's, 6.8 m from the plinth's axis, its concave side
    toward the plinth. Three seats and a block per seat: `block()` takes
    rectangles on the deck's axes only. Its wood is the palette's
    desk_wood (#4a3022, lacquered 0.3), the order's hex; the arboretum's
    is weathered, this hall's polished.
  - **The column is built to its stand-in, not part 2's ø0.4 x 4.6**: it
    runs from the floor past the first balcony to the second's underside
    (8.85), as the stand-in does to 9.2, the shaft ø0.46-0.51 under a
    capital 0.84 across. Part 2's measure is one storey; the stand-in
    holds two balconies. A collar is under and over the first balcony's
    slab, where the column passes its edge.
  - **The column's light is a glow band, not a lamp**: a 14 cm ring of
    `M.glowWarm` (the shared glow, no call) at 8.28, in a recess of the
    model's neck and 6 mm proud of the stand-in, so it shows with or
    without the model. No new light: the hall's lights are spent.
  - **The column's bronze is the atlas's**, as ordered: the shaft is the
    largest surface (8 x 13 m²), but it takes the atlas well at a phone's
    distance; close up at 2.5 m the brushed relief shows its texels in a
    few blotches. Not worth a seventh material or a 2048 atlas; a
    cylindrical unwrap of the shaft in `common.unwrap` would be the fix.
  - **The directory is 0.8 wide, not part 2's 0.5**: the lit face is the
    stand-in's 0.66 x 1.9 canvas, and a narrower totem would shrink the
    deck's directory to a label nobody reads. It is slim in depth (0.3,
    from 0.5) and its top is a half-round to 2.68; the face moved down 10 cm
    (its middle at 1.35) to clear the arch, 2 mm before the front inside a
    14 mm bronze bezel. The stand-in is the same box, 0.3 deep.
  - **No code-side material**: bronze, wood and the totem's black are all
    the atlas's; the bands are the shared glow.
- **Sickbay and the labs (0.221.0)**, decided on Number One's watch, the
  captain asleep:
  - **Generated rooms place models through `finishCell`**, keyed by the
    frame `model()` was called in (`inFrame`'s root), not by walking each
    placement's parents: the cell's are the tail of `modelPlaces`, and a
    parent walk never ends in deckboot.js's stand-in three. A cell's model
    mesh casts no shadow (nothing in a cell does: the maps are not redrawn
    for one) and is drawn from the kept glb in the frame the cell is built,
    so a stand-in never shows once the room's glb is in.
  - **`modelsReady` waits for cells' loads too**, and deckshots waits for
    it after each view's rooms are built.
  - **deckshots' new rooms**: deck 8's Stellar sciences and Sickbay are in
    ROOMS (built at boot), and two generated ones in GEN, visited after
    them: the first lab of deck 8's wings and the first sickbay of deck 12
    (`switchDeck`, and back to 8 after). Deck 8's wings have no sickbay.
  - **The biobed's display moved from the wall to the bed**: part 2 asks
    for a display on an arm, and the stand-in's screen (0.6 x 0.34, was a
    0.9 wall screen) now hangs over the pillow in a housing, tilted 0.3 to
    the foot. The beds keep their places; the stand-ins are new
    (`biobed()`, `surgicalBed()`, `instrumentTray()`), built to the
    models' measures, as the order's.
  - **The clamshell is closed over the chest, across the bed** (the old
    torus spanned the bed's length), its hinge a barrel on the +X rail and
    a latch on the other; the lit panel stays the stand-in's, under the
    crown. The surgical bed is 3.5 k, well under a hero's 6 k: a broader
    shell with banded edges reads at 2 m, more triangles did not.
  - **The trays have stand-ins** (a post and a top), so offline a tray is
    still there and its block is honest; the tray model is 196 triangles
    without a bevel.
  - **The work bench is one model stretched across** to each bench's
    width (`scale: [w / 2.4, 1, 1]`, 1.2-3.2 m), as the captain's chair is:
    its cheeks thicken or thin a little, nothing else shows it. Only the
    labs' benches take it; bench2's other rooms keep the stand-in (its
    display and strip are marked `over`, harmless there).
  - **The specimen case's glass, sample and the light under its cap stay
    the page's** (`M.glass`, `glow()`, `M.glowBlue`); the sample is smaller
    (r 0.08) on a stand, under a shelf of vials. The case faces into the
    room on either wall.
  - **No code-side material**: part 1's lab wall is already `MX.skinLab`,
    the bench top's #2a2a2e is in the atlas (`lab_top`, added in lab.py),
    and the bed pad's #7a8ea0 is the atlas's; the stand-ins keep their
    `MX.sheet`.
  - **The profile helpers moved to the end of common.py** (`mesh_of`,
    `prism`, `rrect`, `loft`, `placed`, `finish_props`): two new scripts
    needed them; bridge.py keeps its own copies.
- **The polish round (0.221.1-0.221.4)**, from TODO.md's leftovers,
  decided on Number One's watch, the captain asleep:
  - **The bar stool is 472 triangles, not furniture's 1.5 k**: Ten
    Forward had ~4.5 k of its 40 k left for eight, so 10-sided turnings and
    a four-sided footring section, smoothed; no piping. Backless, as the
    stand-in is (its seat at 0.81 stays where the page seats a sitter), in
    the tub chair's fabric and chrome. The atlas stays 2048².
  - **The lounge sofa's cushions are bevelled boxes, not `pad`s**: six
    subdivided pads were ~3 k, twice furniture's budget; three bevel
    segments roll an edge as well at a sofa's distance. 1132 triangles.
    Built to `sofa()`'s measures at 2.3 m, so its seats and block are the
    stand-in's; its two throw pillows stay the page's (`userData.over`,
    set in `sofa()` for every sofa: harmless where no model covers one),
    since every sofa's pillows have their own colours and the atlas one.
    Only the lounge's sofa: the ready room's and the generated quarters'
    keep the code-built one.
  - **The lounge's atlas went from 512² to 1024²**: at 512 the sofa and
    the chair would each have had half the chair's texels. 184 kB.
  - **The planters are dark honed stone (#5e5852, a colour of
    concourse.py's own) with a bronze band round the lip and a recessed
    bronze kick**, not bronze alone: four 3 m bowls of bronze beside eight
    bronze columns read as one metal fixture repeated; stone sets the
    columns off. The soil disc stays the page's over the model, and the
    trees.
  - **`common.UNWRAP_HINTS`, at the end of common.py**: `("cylinder",
    cuts)` unrolls a turned prop's side faces (u round it, v the profile's
    arc length) in islands cut at the given heights, then averages and
    packs every island again; its caps keep the smart projection. The
    column is cut at its collars (4.12, 4.73), three strips the square
    packs, rather than one 9 m strip it would have to fit. It redefines
    `unwrap` at the file's end (finish_room looks it up when called), so
    the change stays out of the shared body above it.
  - **The ready room's tea table is one turned piece and the window seat
    a chest with three cushions**, both in the desk's dark wood (#4a3022)
    rather than the stand-ins' M.wood, so the room's wood is one wood; the
    seat's cushion is the page's M.cushion hex (#5a6a7a), a colour of
    readyroom.py's own. The throw pillows on the seat stay the page's. The
    bookcases stay code-built.
- **Every corridor (0.222.0)**, decided on Number One's watch, the
  captain asleep:
  - **A generated corridor places its models in its cell**
    (`corridorDress({ models: true })` from `corridorSeg`), as a room's:
    finishCell takes them, one mesh per cell, shadows received only.
    Each corridor cell is a "room" for the budget: +1 call each, so a
    view down a street pays one per segment it sees.
  - **PADD racks by rule, not by hand**: between two ribs, 1.25 m clear of
    a door's edge and 1.3 m of a wall display's middle, outside a mouth,
    at most one in 12 m of a side, the two sides out of step (the port
    side's first two ribs in, the starboard's three), and none on a side
    of windows (`racks`). Deck 8's three stay placed by hand.
  - **Junctions get nothing**: they have no doors and no wall long enough.
- **The generated room types (0.223.0)**, decided on Number One's watch,
  the captain asleep:
  - **One room's glb per room type**: a cell's placements are merged per
    glb, one call each, so a room that took models from two rooms' glbs
    would be +2. Conference and observation rooms and cabins take the
    lounge's (chairs, sofas), the mess Ten Forward's (tables, tub
    chairs), transporter rooms and main engineering the lab's work bench.
    So the PADD shelves in the labs, sickbays and cabins (the ready
    room's glb) stay code-built, as do a cabin's armchairs (the lounge's
    sofa squeezed to 0.92 m would have arms 6 cm thick).
  - **The mess's chairs only while the room keeps its +40 k**: four tub
    chairs to a table are 3.9 k a table, so a hall of more than eight
    tables keeps the stand-in chairs under Ten Forward's tables. A model
    on half of them would read as two kinds of chair.
  - **`table()` builds in a group and returns it** (the mess was its only
    caller), so a table can be a stand-in.
  - **The sofa and bench are stretched to their stand-in's width**
    (`scale: [w / 2.3, 1, 1]`, 1.4 / 2.4 for a transporter room's bench):
    the cheeks thin a little, nothing else shows.
  - **The holodeck, cargo bay, storage, gym, school, hydroponics,
    cartography and shuttlebay have no prop with a model** and are left
    as they are.
- **Sickbay's and the labs' leftovers (0.224.0)**, decided on Number
  One's watch, the captain asleep:
  - **The wall cabinet only where it is sickbay's** (1.4 x 2.0 in white):
    `cabinet()` is a cabin's wardrobe too, in wood, and kept its
    stand-in there (lounge.glb's `cabin_wardrobe` over it since 0.250.0). Its lit strips are marked `over` everywhere.
  - **The cabinet's windows are flat black**, not glass: the atlas has
    no alpha, and a window into shelves would want an interior.
  - **One hypospray rack a sickbay**, on the bed wall between the first
    two beds at 1.35 m, clear of the beds' arms and the trays.
  - **The office desk got a stand-in** (`officeDesk()`: a white top and a
    drawer pedestal), where the old desk was a wooden top in the air; it
    is white as the sickbay's shell (part 1), not wood.
  - **The microscope station stands against the door's wall at its +x
    end**, facing into the room; none where the way in is there
    (`inAisle`), and a glazed lab drops the specimen cases within 1.4 m
    of it, so its worker has room.
  - **The sample racks sit on the station**, two of them, with no
    stand-in (offline the bench is bare): 184 triangles each, ten tubes
    on a step, no bevels.
  - **`deckshots --views-deck N`**: the close looks of `--view` taken on
    another deck, where its generated rooms' props are.
- **Ornate corridors (0.225.0)**, decided on Number One's watch, the
  captain awake (no question was blocking):
  - **The pilaster is 0.10 proud, not part 6's 0.14**, its channel 0.08
    wide, not 0.05: the channel's floor is the stand-in bar's face, so the
    bar's light slot and its section number stay where the code puts them
    (`userData.over`), in the channel, and offline the rib is as it was.
    The model is scaled to the corridor's height (`(h - 0.4) / 3`).
  - **The wall's relief is generated, not an atlas**: `T.panelCorr`, one
    rib bay (2.6 m) square, its UVs written by the corridor (`corrUV`: u
    from the first rib, v from the floor) where autoUV's run from each
    box's middle. **512², not 1024**: 1024 cost 1.3 s of boot in
    deckshots, and the reveals read at 512 from a metre. The vent is gone
    (part 6 asked for one panel in four; a 2.6 m tile has two).
  - **Corridor-only by `skin`**: `corrSkin(u0)` (M.wallCorr and the
    slotted skirting) round deck 8's corridor walls, `corridorSeg` and a
    junction's walls; the lintels and the cornice take M.wallCorr too, so
    a cell draws no M.wall. A corridor wall's other face (Ten Forward's
    lined side, a room's back) gets the same panels and skirting.
  - **The skirting, cornice trough and T beams are code** (part 6's
    kind), in shared materials (M.console, M.trim, M.glowAmber, M.glowWarm):
    +0 calls. So they change the corridor offline too; "as it was offline"
    holds for every model (ribs, units, racks).
  - **The cap rail (change 4) was kept**: wall()'s rounded M.rail bar,
    8 cm proud, is already the held rail part 6 describes.
  - **Wall units, no stand-in, unlit**: an emergency locker and an LCARS
    wall unit (two of change 5's three; the replicator's lit back
    would need a code light that shows offline, so not yet). Their LCARS
    colours are the atlas's, as the comm panel's buttons. Placed by rule
    in `corridorDress`: bay middles, clear of doors (2.1 m), displays
    (1.5), mouths (1.2), racks and deck 8's hatches (`avoid`, 1.4), one in
    12 m of a side, never within a bay of one across, none on a side of
    windows; the kind alternates by bay, deck and section.
  - **The corridor atlas went to 1024²**: a 3 m rib and two 2.2 m units at
    512 would have had a texel in 1.5 cm. 234 kB.
- **The ornate hull (0.228.0)**, decided on Number One's watch, the
  captain awake (no question was blocking). Number One's budget for it
  (+2 draw calls, +40 k triangles, no shadow redraw, the window views'
  frame p50 within 10 %) stood over part 6's tighter one (+0 calls, +2 k
  triangles), which assumed the greebles would be shader work:
  - **The relief is one generated DataTexture**, `hullRelief`, 512² for a
    16 m tile (3 cm a texel): normal in RG, roughness B, the plate's tone
    A. A DataTexture because a canvas premultiplies alpha, and A is not
    opacity. One fetch, on the saucer's top (k 6) and the shell (k 7)
    only. On the saucer it is laid in polar coordinates with a whole
    number of tiles to each 32 m ring, so it meets itself where the angle
    wraps (the lounge's port windows look straight along that line), its
    gradients worked out from the position's rather than taken of u.
  - **Floodlights were added.** The sun is 9° above the saucer: lit by it
    alone the near plating was a black plain and its relief was lost. A
    warm wash in `hullMat` (pools spreading out from each window band,
    and up the shell's walls from their foot) is what makes part 6's
    Aztec read. It is not in part 6; the Galaxy class is floodlit.
  - **The greebles are merged, not instanced**: four props in one
    InstancedMesh each would be four calls; merged under the ship's group
    they are one, the same triangles. Their material is `hullGreebleMat`,
    a ShaderMaterial lit by `SPACE_LIGHT` as the hull is, not the rooms'
    MeshStandardMaterial (lit by the ship's lights inside). It casts and
    receives nothing. The ORM's blue is a glow mask, not metalness: only
    the phaser's emitter line has it.
  - **The running lights are glints**, the outside's shared material:
    the RCS quads' amber markers in ownShip's glints (+0), and the shell's
    white double-flash strobes (12 corners, 24 points) as one Points
    under shellG (+1, so the greebles' mesh and the strobes are the two
    calls).
  - **The lifeboat rings are at r 176 and 222**, not part 6's "near the
    rim" alone: the registry fills 127-157 m ahead, and the window bands
    are at every 40 m. The phaser ring is at 215, in 84 segments of 14 m.
  - **Lifeboats and the phaser ring are barely seen from the windows**:
    150-220 m off, nearly edge-on. They are cheap (28 k triangles), and a
    view from above would show them. The registry is 18 m letters, drawn
    as a grey sliver ahead of Ten Forward.
- **The generated rooms' leftovers (0.243.0)**, decided on Number One's
  watch:
  - **The PADD shelf is common.py's** (`padd_shelf`, `shelf_book`,
    `shelf_padd`, `shelf_sculpture`, `shelf_books`), moved out of
    readyroom.py unchanged, and baked into each room type's own atlas:
    the lab's in the lab's grey with binders, cases and tubes, sickbay's
    in its white with blankets, medkits and vials, the cabins' (lounge.glb,
    which the quarters take) the ready room's two arrangements, picked by
    `rm.seed % 2` (a draw of the room's random would move every one after
    it). `readyroom.glb` is not rebuilt: the same shelves.
  - **The rail stops behind a generated room's shelf**: `shell()` takes
    `railGaps` ([side, z0, z1]) for wall()'s, and runs the port wall the
    other way when it has one, so the gap is on the room's face. The
    wardrobes and cabinets are solid and keep the rail inside them.
  - **A big mess hall takes `mess_chair`** (tenforward.py, 210): a hall
    keeps one kind of chair, the tub chair while it fits the 40 k, else
    this one; the stand-ins and their seats stay as they were.
  - **Left code-built**: deck 8's own shelves outside the ready room
    (`dressShip`'s two, the observation lounge's two) and a cabin's
    wardrobe (`cabinet()` in wood); models since 0.250.0 ("Measured:
    deck 8's last code-built furniture").

## Measured: seated PADD readers (0.247.0, measured against 0.246.0)

`deckshots.py --gen 12:quarters --only "Ten Forward,Observation
lounge,Concourse,Deck 12 quarters" --view crew:25,1.3 --view
crew:9,1.4,40`, niced, deb's page at 0.246.0 then this one, one run
each, on a box with other sessions. Deck 8 has four seated readers (two
in Ten Forward, one in the lounge, one on a concourse bench); crew 25 is
the lounge's, crew 9 one of Ten Forward's.

| | before | after |
|---|---|---|
| draw calls, observation lounge (fwd, port, aft, stbd) | 142 / 75 / 133 / 138 | 142 / 76 / 133 / 138 |
| draw calls, Ten Forward | 98 / 106 / 129 / 86 | 98 / 107 / 129 / 86 |
| draw calls, concourse | 218 / 124 / 60 / 122 | 218 / 128 / 56 / 124 |
| draw calls, deck 12 quarters | 214 / 124 / 84 / 431 | the same |
| draw calls, the two readers close up | 71 / 91 | 72 / 92 |
| triangles | | +12 a reader in view (the PADD box), else the same |
| frame p50 over the 18 views | 1360 ms | 1326 ms |
| boot / models landed | 53.8 s / 73.5 s | 42.9 s / 72.8 s |
| shadow redraws | 0 of 39 | 0 of 39 |

+1 call a reader in view: the standing reader's PADD, one box in
`crewMats.padd`, no more. The concourse's other moves (+4 / -4 / +2
calls, a few hundred triangles either way) are its walkers, who were
elsewhere when each view counted its busiest frame. The deck 12 cabin's
occupant does not read in this seed (a third at most, by seed), so the
quarters are unchanged.

## Measured: the baked seated read, the shift clip, blinks (0.249.0, measured against 0.248.2)

`deckshots.py --only "Main bridge,Ten Forward,Observation lounge,Concourse"`,
niced, deb's page at 0.248.2 then this one, one run each, on a box with
other sessions.

| | before | after |
|---|---|---|
| draw calls, main bridge (fwd, port, aft, stbd) | 62 / 65 / 208 / 58 | 62 / 65 / 209 / 59 |
| draw calls, observation lounge | 123 / 77 / 140 / 100 | 124 / 77 / 138 / 100 |
| draw calls, Ten Forward | 102 / 106 / 130 / 86 | 102 / 107 / 130 / 86 |
| draw calls, concourse | 232 / 124 / 57 / 123 | 230 / 124 / 59 / 124 |
| triangles | | the same within 1.1 k (the walkers) |
| frame p50 over the 16 views | 1272 ms | 1266 ms |
| boot / crew landed / models landed | 38.3 / 62.2 / 71.4 s | 37.0 / 60.5 / 69.7 s |
| shadow redraws | 0 of 33 | 0 of 32 |
| crew glbs at boot (`lcars-ui/crew/`) | `clips.glb` 239,532 B | 273,340 B (+33.8 kB, the two clips); the rest byte-identical |

+0 calls: the blink is a bone in each skeleton's texture and a few
instructions in the body's shader; the shift an additive action of nine
bones' tracks on the mixer each stander already has. The ±2 calls are
people moving through the busiest frame of a view.


## Measured: baked floor occlusion (0.251.0, measured against 0.249.0)

`bakeAO` in deck.html: each floor's contact shadows drawn once on a
canvas from `blocks` (the furniture's footprints and the walls' lines),
~25 cm of falloff, 5 cm a texel (a tile's longest side at most 1024),
packed into one atlas a bake - deck 8's hand-built floors at boot (one
1248x1600 atlas), each cell's when it is built - and multiplied into the
floor's colour after its map (`aoUv`, a hook composed with borderFloor's
through `hookShader`). On low a cove too: the walls' lower bands darker
toward the floor (`coveHook`, a uniform, 0 on medium and high). Measured
before 0.250.0 (the last furniture models) landed under it, so both
pages are 0.249.0's deck with and without the bake.

`deckshots.py --gen 8:quarters --only "Corridor,Ten Forward,Observation
lounge,Wing lab,Deck 8 quarters,Deck 12 corridor"`, 390x844, SwiftShader,
one run each, deb's page then this one; the milliseconds are a software
GPU's and move ±15% between runs. Shots before and after:
`/media/reports/2026/10/baked-floor-occlusion-deck-shots-before-and-afte-6a0b3905.html` on the journal's server.

| | before | after |
|---|---|---|
| the bake at boot (`aoStats.ms`: deck 8 and the two wing cells built with it) | - | 12-16 ms over five runs |
| a generated room's bake (in `finishCell`) | - | under 1 ms: 65 bakes in 52 ms over deck 12, 8 and 12 again; textures after it 82 against deb's 81 (deck 8's atlas; a dropped cell's is disposed), programs 46 against 43 |
| meshes in the scene after boot, materials | 315, 161 | 315, 163 (each cell's floor clones) |
| calls, low: corridor | 199 / 97 / 142 / 92 | 199 / 97 / 143 / 92 |
| calls, low: Ten Forward | 97 / 106 / 131 / 86 | 102 / 106 / 130 / 86 (the crew: 97 in the run before) |
| calls, low: observation lounge | 124 / 76 / 139 / 100 | 124 / 76 / 138 / 100 |
| calls, low: wing lab (a cell) | 77 / 95 / 66 / 257 | 77 / 94 / 67 / 257 |
| calls, low: deck 8 quarters (a cell) | 56 / 63 / 57 / 274 | the same |
| calls, low: deck 12's corridor (a cell) | 238 / 83 / 38 / 448 | the same |
| frame p50 over the 24 views, low | 1131 ms | 1310 ms (in the noise: 1531 for the three rooms below, 1217 in a run before) |
| frame p50 over the 24 views, high | 1657 ms | 1722 ms |
| boot to the ship built, low / high | 39.7 / 47.4 s | 42.1 / 57.1 s (the box: the bake is 15 ms of it) |

+0 calls: deck 8's floors keep their materials (one atlas for them
all, so their merge is what it was); a cell's floors take a clone of
their material, and were a draw of their own already. One texture per
bake (deck 8's 1248x1600, 8 MB, 10.6 MB with its mips; a room's ~256-512 square).

**Whether GTAO can be lightened, on high, with the bake in** (the
corridor, Ten Forward, the wing lab; 12 views; median frame p50):

| GTAO | p50 | corridor's four views |
|---|---|---|
| as shipped (12 samples, half resolution) | 2088 ms | 4190 / 2736 / 5459 / 2590 |
| 6 samples (`updateGtaoMaterial`/`updatePdMaterial`) | 2202 ms | 4161 / 2837 / 5547 / 2334 |
| off | 2038 ms | 3353 / 2377 / 4568 / 2188 |

In SwiftShader GTAO off is ~10-20% of the corridor's frame and fewer
samples are not measurably cheaper; this box has no GPU, so the 780M's
~5 ms is not re-measured here. With the bake, GTAO off changes little
on the floors (the shots' third column; a diff of the wing lab: 0.5/255
mean, the window's sky and the consoles' feet), as GTAO's darkening
there is what the bake and the contact decals already draw; it still
finds what no footprint knows (under a bar's lip, between a shelf's
boards, the crew's feet). Not changed: the default stays GTAO on high,
the captain's call. If it goes, the cove's uniform should be on for high
too (`applyGfx`).

**The floor-level contact decals dropped** (0.254.1, against 0.254.0):
the wall bands, the bridge's ring and the patches at y 0 (`contact()`
under the consoles and tables, `grounded()` on a group standing on the
floor) are no longer made; the bake had every one of their footprints
in `blocks` but the bridge's round wall, whose foot is now an arc the
bake strokes (`aoArcs`), and the rugs, now baked as floors (`aoFloor`),
so a sofa or a table on one keeps its shadow. Kept: `grounded()` on
anything standing higher (a plant on a shelf board, a lamp on a desk)
and the models' own patches (a vase on the desk). Draws, low, the crew
left out (instanced) and one frame from each spot, deb then this:

| view | calls | contact draws | triangles | contact triangles |
|---|---|---|---|---|
| ready room, bow / stern | 86 / 134 → 86 / 135 | 2 → 2 | -748 / -676 | 806 → 58 |
| corridor, bow / stern | 140 / 115 → 140 / 113 | 1 → 1 | -748 / -892 | 802 → 54 |
| Ten Forward, port / starboard | 96 / 63 → 94 / 63 | 1 → 1 | -712 / -748 | 802 → 54 |
| main bridge, stern | 171 → 173 | 1 → 1 | -184 | 802 → 54 |
| deck 10 quarters (a cell), bow / port | 227 / 509 → 218 / 487 | 11 / 23 → 2 / 1 | -202 / -534 | 218 / 542 → 16 / 8 |

Deck 8 keeps its one contact draw: its raised patches (27 of them, the
plants on the shelves, the lamps on the desks) are merged into the same
mesh as the floor's were, so it is -748 triangles, not a call (the ±2
calls are doors and lights). A generated room, where every cell in view
drew its own patches, loses a contact draw per cell in view: -9 and -22
calls in a cabin. Deck 8's atlas grows from 1248x1600 to 1256x1600 (the
rugs' tiles). Shots, deb's and this page's:
`/media/reports/2026/10/floor-contact-decals-dropped-deck-shots-before-a-2f416d89.html` on the journal's server.
