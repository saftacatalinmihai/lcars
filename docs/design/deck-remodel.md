# Deck remodel: current practice, our pipeline, and the next slices (2026-10-22, main 0.298.6)

Number One's order of 2026-10-22 (thread main), for the captain: the next
stage of the deck remodel, done the way the best current practice says.
Research and a plan only: **no Higgsfield or Tripo credits spent** (the
captain sets a budget after reading this). Read first: deck-models.md,
deck-style.md, deck-pipeline.md, bridge-redesign.md (sections 8-9: the
chair pilots, the tiles, the bridge slices) and deck-polish.md (slices
1-8). This doc does not repeat them; it says what the field does now,
what we already do, what to change, and the slices.

**The report** (this plan on a phone, with the survey's sheets and
links):
<https://<server>/media/reports/2026/10/deck-remodel-practice-pipeline-slices-89097d56.html>.

## 1. What was checked, and how

- **Tripo:** the official API docs, each page's `.md` form
  (`developers.tripo3d.ai/en/docs/<page>.md`), fetched today: the
  [index](https://developers.tripo3d.ai/llms.txt),
  [models and versions](https://developers.tripo3d.ai/en/docs/models-and-versions),
  [multiview to model, H series](https://developers.tripo3d.ai/en/docs/generation-multiview-to-model/standard),
  [image to model, P series](https://developers.tripo3d.ai/en/docs/generation-image-to-model/p),
  [image to multiview](https://developers.tripo3d.ai/en/docs/generation-image-to-multiview),
  [retopology](https://developers.tripo3d.ai/en/docs/mesh-decimate),
  [smart UV](https://developers.tripo3d.ai/en/docs/mesh-uv),
  [segmentation](https://developers.tripo3d.ai/en/docs/mesh-segment),
  [convert](https://developers.tripo3d.ai/en/docs/models-convert),
  [billing](https://developers.tripo3d.ai/en/docs/billing),
  [changelog](https://developers.tripo3d.ai/en/docs/changelog),
  [CLI](https://developers.tripo3d.ai/en/docs/cli) and the
  [price list](https://developers.tripo3d.ai/en/pricing).
- **Higgsfield:** its public API docs
  ([docs.higgsfield.ai](https://docs.higgsfield.ai/docs/llms.txt),
  [billing and retention](https://docs.higgsfield.ai/docs/concepts/billing-and-retention.md))
  do **not** document the 3D jobs, and the CLI's
  [MODELS.md](https://github.com/higgsfield-ai/cli/blob/main/MODELS.md)
  lists only the generic ones (`image_to_3d`, `multi_image_to_3d`,
  `tripo_3d`, `sam_3_3d`, `3d_rigging`). So every Higgsfield model name,
  parameter and price below is from the installed CLI (higgsfield 1.2.2,
  built 2026-10-16): `higgsfield model get <job_type>` and `higgsfield
  generate cost`, which estimates and spends nothing. Balance today:
  **748.25 credits** (plus plan).
- **three.js and delivery:** three's docs
  ([KTX2Loader](https://threejs.org/docs/pages/KTX2Loader.html),
  [BatchedMesh](https://threejs.org/docs/pages/BatchedMesh.html),
  [PMREMGenerator](https://threejs.org/docs/pages/PMREMGenerator.html)),
  its `src/constants.js` (the tone mappers), Khronos'
  [KTX artist guide](https://github.com/KhronosGroup/3D-Formats-Guidelines/blob/main/KTXArtistGuide.md)
  and [PBR Neutral](https://www.khronos.org/news/press/khronos-pbr-neutral-tone-mapper-released-for-true-to-life-color-rendering-of-3d-products),
  [glTF Transform](https://gltf-transform.dev/cli),
  [meshoptimizer's gltfpack](https://meshoptimizer.org/gltf/),
  [Blender's baking manual](https://docs.blender.org/manual/en/latest/render/cycles/baking.html).
- **How people work with an agent** (blogs, October 2026; practice, not
  specs): [Claude Code and three.js for browser games](https://gamesbyai.win/guides/threejs-with-ai-agents/)
  (2026-10-02), [100 three.js tips](https://www.utsubo.com/blog/threejs-best-practices-100-tips)
  (September 2026), [Tripo for game assets with the CLI skill](https://sunoboard.com/blog/tripo3d-game-assets-claude-code)
  (2026-10-09), [Opus 5.5 and the Higgsfield MCP](https://www.developersdigest.tech/blog/claude-opus-5-5-3d-world-higgsfield-mcp)
  (2026-10-05: an overview, no settings in it).
- **Ours:** the five design docs, deck.html's renderer block, the
  survey's 32 contact sheets (deck-polish's report) and La Forge's memory
  report (0.295.2). No deckshots run was needed: the survey is from
  0.291.2, and slices 1-4, 6 and 7 since are each measured in
  deck-polish.md section 5.

## 2. The practices that matter for us, against what we do

| practice (source) | what we do | change? |
|---|---|---|
| **Inputs for image-to-3D**: one subject, plain light-grey ground, even diffuse light, no hard shadows, no chrome or glass, the subject 70-85% of the frame, 2-4 views (Tripo's help pages, via search: the pages refuse a fetch, 403) | four straight views (front, left, back, right) on Seedream 5.0 Flash, 1:1 2k, grey ground, each next view referencing the ones before (8c, slice 4) | **keep**; add the frame and the material lines (section 3) |
| **Multiview from one image**: Tripo's `POST /v3/generation/image-to-multiview` makes the four views from one front, and `multiview-to-model` takes its task id directly | Seedream by hand, four prompts | **try once** (10 Tripo credits): views made by the model that reads them may agree better |
| **De-lit textures**: `delight` (default true) removes baked light, but only texture model `v3.5-20260815` reads it; `texture_version` pins it | the API pilot (8e) set it; **Higgsfield's H3.1 jobs have no `delight`, `texture_version` or `smart_low_poly`** (`model get`, CLI 1.2.2); its P2 job has `delight` and `texture_version` | for a hero prop where albedo matters, Higgsfield's P2 or Tripo's API; else H3.1 and our palette pull |
| **The face budget asked for up front**: `face_limit`; `smart_low_poly` fixes it to 500-20,000 triangles; P1 50-20,000, P2 48-50,000 (25,000 quads) | `face_limit` 0.8 x the budget (it overshoots: 6000 asked, 7,212 back) | keep |
| **Quads**: `quad` forces FBX out and needs a convert back | triangles (three draws triangles; quads only help a sculptor) | no |
| **Texture size**: `texture_quality` standard / detailed / extreme (8K) | standard (2048² measured in 8b); every prop is baked into the room's 1024² atlas, where detailed (4096²) looked the same (8e) | keep standard |
| **Segmentation** (`/mesh/segment` 40, smart segment 55-85; `generate_parts` refuses `texture`) | faces picked by height and radius in Blender for the pedestals | no: a Blender selection is free and exact for our shapes |
| **Tripo's retopology** (`/mesh/decimate` v3.0, 35) and Smart UV (20) | tried (8e B): 25 bodies, open; our weld, decimate and bake wins | no |
| **Blender clean-up**: weld, decimate, one UV set, bake to an atlas (gltf-transform / Blender docs) | `import_pack`: weld (1e-5 m), decimate, consistent normals, bake every prop of a room into one 1024² atlas, ORM with AO (deck-pipeline.md) | keep |
| **meshopt over Draco** for the web: faster decode, glTF Transform's default (utsubo, glTF Transform) | meshopt since 0.242.1 (~17 B a triangle) | keep |
| **GPU-compressed textures (KTX2 / Basis)**: a 1024² RGBA8 map with mips is ~5.6 MB of GPU memory however small its webp; ETC1S for base colour, UASTC for normal and ORM (Khronos' guide) | **webp atlases**, decoded to RGBA8 on the GPU: three maps a room type, every type seen kept | **yes, first** (slice 1) |
| **Draw calls on a phone**: ~100-120 a frame as a working budget (utsubo; gamesbyai's `MAX_CALLS = 120`); merge statics, instance repeats, `BatchedMesh` for many geometries in one material | deck 8 merged per material; the bridge 59-209 a view; **generated rooms 400-510 in a view** (deck-pipeline.md, 0.243.0: deck 12's sickbay 510, quarters 431, mess 419) | **yes** (slice 2) |
| **Baked light**: lightmaps and AO in a second UV set are free at run time (utsubo; Blender baking) | AO per prop in the atlas; the floors' occlusion baked in code (0.251.0); no lightmaps: graphics low has no GTAO | **a pilot** (slice 8) |
| **Environment**: one PMREM for ambient and reflections | `RoomEnvironment` at 0.35 for the whole ship; the pond its own (0.297.1) | keep; a room's own only where a mirror shows it |
| **Colour management**: sRGB output, colour maps sRGB, data maps linear | `outputColorSpace` sRGB, `canvasTex` sRGB, the atlases from glTF (the loader sets them) | keep |
| **Tone mapping**: ACES skews bright orange toward yellow-white and cannot reach saturated yellows; AgX keeps hue into the highlights; Khronos PBR Neutral keeps base colours (Khronos, three's forum overview) | `ACESFilmicToneMapping`, exposure 0.9 | **A/B it** (slice 3): LCARS is saturated orange, peach and lilac |
| **LOD** | dressing culled past 4 m on low; the rooms are small | no new LOD |
| **Pixel ratio** capped (utsubo: 2) | 1.5, stepping to 1 when slow | keep |
| **Shadows**: few casters, drawn once | four spots, redrawn only on a change (deck-models.md slice 2) | keep |
| **The agent loop**: count, don't time, on a box without a GPU; screenshots from a real browser (SwiftShader); `renderer.info` calls, triangles, geometries, textures stable over restarts (gamesbyai) | deckshots (calls, triangles, looks at a phone's size), deckmem `--check` (WebGL memory, live objects, loops), an HTML report a slice, main beside the branch | keep; add a calls budget that fails (slice 2) |

## 3. The pipeline, as it should run from here

Unchanged where it works (deck-pipeline.md's five steps, `import_pack`'s
weld and bake, the room's one atlas). Changed:

1. **Ship KTX2, keep webp as the fallback** (slice 1). The cleaner
   (`deck-model-assets.mjs`) writes `<room>_base.ktx2` (ETC1S, `--clevel
   4 --qlevel 255`), `_norm.ktx2` and `_orm.ktx2` (UASTC, quality 4, RDO
   0.5, zstd 22, the normal map `--assign_oetf linear`), mipmapped, beside
   the webp; the page loads them with `KTX2Loader` (already in our three
   bundle) and Basis' transcoder (vendored as the meshopt decoder is),
   and falls back to the webp when either fails. Needs KTX-Software's
   `toktx` in the build cache (a binary, like the npm packages there).
2. **Two roads for a generated prop, picked by what it is:**
   - **soft, organic, seen close** (upholstery, plants, a sculpture):
     four Seedream views, then Higgsfield's `tripo_h3_1_multiview_to_3d`
     (9 credits, `face_limit` 0.8 x budget, PBR, texture standard) and
     our fit and palette pull. Where the albedo must be clean (light
     leather, painted metal), Higgsfield's `tripo_p2_image_to_3d` with
     `texture_version v3.5-20260815`, `delight true` (34 credits, one
     image) or Tripo's API (H3.1 multiview + smart low-poly, 40 API
     credits; ships only on a paid account, bridge-redesign.md section 9);
   - **hard-edged, fitted to the room** (consoles, rails, cabinets,
     beds, tables): scripted in Blender (`common.py`). The bridge proved
     this: the scripted consoles and rail beat what Tripo would give at
     1.5 k triangles, for 0 credits.
3. **The prompt kit.** A lead line every view shares, kept with the
   model's sources (`<media>/deck-models/<prop>/raw/prompts.txt`):
   *"Product reference for a real-time 3D model: one <object> alone,
   centred, filling 80% of a square frame, level camera at the object's
   middle, long lens, no perspective distortion, on a plain flat 50% grey
   ground with no horizon, soft even overcast light from every side, no
   cast shadow, no reflections, satin not mirror metal, no glass, no
   text, no logos."* Then the view (`straight from the front` / `the
   object's own left side, at exactly 90 degrees` / ...), the palette's
   colours by name and hex, and the earlier views as references. For a
   tile, bridge-redesign 8g's lead ("Seamless tileable texture, edge to
   edge, orthographic straight-on, flat even shadowless lighting...")
   and `tiles.py`. For a concept, deck-polish's (the survey's look as
   the reference, "keep the room, camera and layout").
4. **One script for the generated road** (slice 9): `scripts/deck-models/gen.py
   PROP` reads that folder's prompts, prints `higgsfield generate cost`
   for every step and stops until told `--spend N` (a cap), makes the
   views and the job, downloads the glb (Higgsfield keeps outputs for a
   time only: download at once), and writes `LICENSE.txt`. The fit stays
   per prop (`fit.py`, as slice 4's).
5. **Budgets that fail.** deckshots gains `--max-calls N` (a look over
   it fails the run) and every slice's report gives deckmem `--check` at
   low with the WebGL memory at boot and at the walk's end.

## 4. The rooms that look worst now

After the bridge (bridge-redesign.md section 9, slices 1-5) and the
polish (deck-polish.md slices 1-4, 6, 7), from the survey's sheets
(0.291.2) with each fix since taken off:

1. **Main engineering (deck 36).** The warp core is a white blob from
   the floor to the ceiling (its emissive far over the bloom's
   threshold at high, flat white at low), the consoles near-black
   boxes, the walls a dark grid. The ship's heart, and the room a
   visitor asks for first.
2. **The generated rooms' furniture**, every deck: quarters (a box
   sofa, a slab bed, box shelves, a plain coffee table), the conference
   room (black chairs that read as blobs, a table whose grain shows as
   ripples), the classroom, the observation lounge 7-A. Code-built
   boxes in many materials: they look a generation older than deck 8's
   baked rooms, **and** they are where the 400-510 call views are.
3. **Bare walls** in the same rooms and the gym (deck-polish slice 5,
   not built).
4. **Hydroponics (deck 11).** Pink grow-light bars blown out at high
   and much brighter than anything else, plants in plain black troughs.
5. **Sickbay (deck 8, 12).** White cabinets as flat boxes with black
   faces, beds as white tubs: clean but toy-like next to the bridge.
6. **The turbolift**, the white field in the door's opening
   (deck-polish slice 8, waiting for a look taken mid-ride).

Holding up, as the survey said: the corridors, the concourse, Ten
Forward, the arboretum, stellar cartography, the holodeck, the labs'
consoles, the bridge.

## 5. The memory and the calls today

- **Memory** (deckmem, 0.298.1, graphics low, 393x852 at 3x): boot 353 MB
  of WebGL memory, **389 MB of textures at a walk's end**, peak 585 MB.
  iOS kills a tab at a few hundred MB of WebGL memory (reports put it at
  300-500 MB; Apple publishes no figure:
  [Apple's forum](https://developer.apple.com/forums/thread/741624)).
  The captain's iPhone 14 Pro lost the tab before 0.295.2. Every room
  atlas is three 1024² maps at ~5.6 MB each with mips (~17 MB a room
  type; ten deck-8 glbs alone ~170 MB if all are kept), and the 12
  procedural `texSet`s and ~37 canvases (~40-60 MB, estimated, not
  measured) are RGBA8 too. KTX2 in ETC1S transcodes to ~0.5 byte a
  pixel on a phone, UASTC to ASTC 4x4 at 1 byte: **~4-8x less** for the
  atlases.
- **Calls** (low): the bridge 59-209 a view, deck 8's rooms ~50-350,
  the generated rooms up to 510. The budget elsewhere is ~100-120 on a
  phone. Generated rooms are built from `M.*`/`MX.*` code materials, one
  call each per cell; deck 8's rooms became one atlas call each.

## 6. The slices, ranked

Ranked by what the phone sees per cost: memory first (a dead tab is the
worst look), then calls, then the looks, worst room first. Each is one
engineer's order, shippable alone, with bridge-redesign.md section 6's
rules (a new material is a call; boot within noise; low no heavier),
deckboot and `run.sh --changed`, deckshots main beside the branch at
390x844 (low for the counts, high for the looks), **deckmem `--check` at
low**, and an HTML report. A minor for the first new look, patches after.
Credits are Higgsfield's from `generate cost` today (Seedream 5.0 Flash
0.5 an image at 1k or 2k, Seedream 5.0 Pro 2.5, Z Image 0.15, Tripo H3.1
image or multiview 9 with standard texture, 18 with detailed texture and
geometry, Tripo P2 34-37, Hunyuan3D v3 11, Meshy 7 38); each slice's
estimate includes one re-roll of its images.

| # | slice | rooms | credits | calls | triangles | textures (GPU) |
|---|---|---|---|---|---|---|
| 1 | KTX2 atlases | every room with a glb | 0 | +0 | +0 | **-100 MB or more** at a walk's end |
| 2 | the generated rooms' calls | every generated room | 0 | **≤ 200 a view** | +0 | +0 |
| 3 | tone mapping A/B | all | 0 | +0 | +0 | +0 |
| 4 | main engineering | deck 36 | 1.5-3 | +0 to +1 | ≤ +6 k | ≤ +6 MB (KTX2) |
| 5 | quarters, baked | every quarters | 0-24 | -50 or more | ≤ 15 k a room | +1.5 MB (KTX2 atlas) |
| 6 | bare walls (polish 5) and the turbolift (polish 8) | quarters, obs 7-A, gym, conference, school; the car | 0 | +1 a room | +100 a room | +0 |
| 7 | conference, classroom, mess, baked | those | 0-12 | -30 or more | ≤ 15 k a room | +1.5 MB |
| 8 | lightmap pilot | Ten Forward | 0 | +0 | +0 | +1.5 MB |
| 9 | `gen.py`, the generated road | tooling | 0 | - | - | - |
| 10 | hydroponics and sickbay | deck 11, 8, 12 | 0-12 | +0 | ≤ +5 k | +0 |

1. **KTX2 atlases** (`deck-model-assets.mjs`, `deck.html`'s prop
   library). Section 3.1. Looks the same by eye (the report: each room's
   look, webp beside KTX2, at high, close up on a normal-mapped prop).
   Budgets: calls +0, triangles +0; the wire per room kept under ~600 kB
   (UASTC normals are bigger than webp: if a room goes over, its normal
   map ETC1S, or 512²); boot within noise (the transcoder is a worker,
   ~200-500 kB fetched once, size to be measured); deckmem `--check` at
   low passes and **its textures at a walk's end drop by at least 100
   MB** from 389 (the number that proves the slice). Then the same for
   the bridge's tiles and skylight. Decision: `toktx` installed in the
   build cache.
   **Built** (0.302.5, and the bridge's maps after it): KTX-Software
   4.4.2's `ktx create` (not `toktx`), fetched by `build.sh` into its
   cache and checked by sha1; `build.sh --ktx2 [ROOM ... | maps]` makes
   them from the shipped webps with no Blender. Each room's three maps at
   min(baked, 1024)², mipmapped: base ETC1S (sRGB), normal UASTC (quality
   4, RDO 0.5, zstd 22), **ORM ETC1S**, not UASTC (its baked AO is noise
   UASTC cannot pack: 2.4 MB at 2048² and 7 minutes to encode; the close
   looks of the captain's chair, the conn and the brass vase showed no
   blotching or bleeding). A room over 600 kB steps down: normal map
   ETC1S (the bridge, the ready room), then ORM at half, then normal at
   half. Every room fits: 184-573 kB with its glb. `lcars-ui/deck/atlases.json`
   lists what each has; the page loads a listed room's KTX2 on a phone,
   or anywhere at ≤ 1024² (a desktop keeps Ten Forward's 2048 webp), and
   the webp when a KTX2 fails. The loader is a second vendored module
   (`vendor/ktx2loader-0.186.1.mjs`, 60 kB, `three` external), the
   transcoder three's own (`vendor/basis-0.186.1/`, 527 kB wasm, gzipped);
   **four workers** (one made the boot's 30 maps wait on each other's
   trips through the main thread), the transcoder fetched as the loader is
   made, the workers ended once no KTX2 is in flight. The server serves
   `.ktx2` as `image/ktx2` (C: the deploy rebuilds it). Measured, deckmem
   at low on the iPhone walk: **textures at a walk's end 389.0 to 269.0
   MB**, peak (all GPU) 585 to 465; calls and triangles +0 (26 views; a
   Concourse view that differed rerun twice each: equal). In headless
   Chromium the models land ~60 s after boot against main's 7 (2 s with
   the frame loop held: a software frame takes a second, and each map's
   result waits for one), so **deckshots and deckmem wait up to 180 s**
   for the models (`MODELS_WAIT`); a phone's frames are milliseconds.
   The bridge's maps (the carpet's and the wall's base, normal and
   roughness, the coffer's skylight) are under `maps` in atlases.json, at
   their webp's size, loaded by `deckMap`: written flipped, since they
   load with three's flipY and a KTX2 cannot be flipped. Normals UASTC,
   the rest ETC1S - the skylight too: its smooth panes showed no banding
   at high (the same mean colour in the scene, main and branch), only a
   4x4 block noise with the gradient stretched 4x offline; UASTC would
   have been 821 kB against 196. Textures at a walk's end 268.9 to 261.6
   MB, the bridge's calls and triangles +0. Paused after this (the
   captain, 2026-10-23); the lightmap pilot (slice 8) left for later.
2. **The generated rooms' calls.** Count calls by material in the worst
   looks (deck 12 sickbay starboard, quarters forward, deck 25 mess:
   the `renderBufferDirect` hook from deck-pipeline.md's 0.223.0
   section), then merge what a cell draws per material where it does
   not already, instance what repeats (chairs, bunks, crates), and
   `BatchedMesh` where one material holds many shapes. deckshots'
   `--max-calls` (section 3.5) set at 200 on these looks. Budgets: calls
   ≤ 200 in every generated look, triangles +0, deckmem `--check` passes
   (no new geometry kept a loop). 0 credits.
   **Built** (2026-10-23): `batchDeck` in deck.html, after `buildDeck` -
   a generated deck's cell merges, and each cell's lone mesh of a shared
   material (its ceiling, its light strip), one `BatchedMesh` per
   material and attribute layout, each cell an instance at its own
   transform; the door leaves one more, moved by `setMatrixAt`. Deck 8
   untouched. The six worst looks at low: 491 calls at most to 150,
   triangles equal look for look, the looks at high alike by eye;
   deckmem `--check` at low passes (peak geometries 391 against main's
   612). deckshots gained `--max-calls`, `--calls-by`, `--dump`, and
   console errors in report.json. Open: whether the iPhone's Safari has
   `WEBGL_multi_draw` (without it three.js draws a batch's pieces one by
   one: no worse than before, and no better).
3. **Tone mapping A/B.** ACES (now), AgX and Neutral, each at the
   exposure that gives the corridor's walls the same mean, on eight
   looks (the bridge B and C, the corridor, Ten Forward's bar, the
   concourse, quarters, engineering, the arboretum) at high and low;
   the LCARS panels' oranges measured against their sRGB values. The
   captain picks. +0 everything; a changed mapper also changes the
   bloom's threshold, so slice 1 of the polish's emissive levels are
   rechecked. 0 credits.
   **Applied** (2026-10-23, the captain's pick): `NeutralToneMapping`
   at 1.25 the default (it gives the corridor's walls ACES-at-0.9's
   mean), `?tone=`/`?exposure=` and `__deck.setTone` kept for trying
   others. The glow levels rechecked at high against main (deckshots,
   the bridge, the corridor, Ten Forward, the arboretum, the concourse,
   main engineering): no level changed. The warp core's bands no longer
   bloom to white and its body keeps its blue; Ten Forward's strips and
   the LCARS panels read as before, a little warmer; the bridge's
   skylight glare a touch wider and warmer, left as it is. At low the
   core and the panels are `toneMapped: false` and do not change.
4. **Main engineering.** The warp core: a lathe in code with a
   gradient emissive map under the bloom's threshold but its bands, the
   blue pulse moving up as a uniform (+0 calls, as `blinkMat`), its
   ring frames in `M.trim`; the consoles a scripted Blender prop
   (`engineering.py`: the master systems display's table and the
   wall consoles, sloped, bevelled, the LCARS insets the page's), one
   atlas. Two Seedream concepts from the survey's looks first (1 credit,
   plus one re-roll). Budgets: ≤ 6 k triangles for the core, ≤ 1.5 k a
   console, the room +1 call (the atlas), 1024² KTX2. **1.5-3 credits.**
   **Built** (2026-10-23): two Seedream 5.0 Flash concepts (the core,
   the MSD table; 1 credit, no re-roll, 748.25 to 747.25). `warpCore` in
   deck.html: the column a lathe bulging between its frames, its body a
   blue gradient computed in coreMat's shader (no texture: +0 memory)
   under the threshold, only the bands and the climbing pulse over it;
   ~5 k triangles (the old cylinder and tori ~8 k). `engineering.py`:
   `msd_table` 744 triangles, `wall_console` 792 (one under each wall
   display, new), 76 kB with the webp atlas; its KTX2 (made by
   `build.sh --ktx2` once slice 1 landed) 166 kB with the glb. At
   low: +1 call in every look (57-151 on main, 58-152), +8.8 k
   triangles (the ten consoles); boot within noise; deckmem `--check`
   at low over decks 36 and 12 passes (measured with the webp atlas).
5. **Quarters, baked.** `quarters.py` as deck 8's rooms: the sofa, the
   bed with its headboard, the shelves, the desk and chair, the coffee
   table, the lamp, scripted; one atlas for every quarters cell (the
   type's glb, as `lab` and `sickbay` are shared). The sofa and the bed
   are the soft props: scripted first; if the report shows them as
   blocks, the generated road (four views 2 + H3.1 9 each: **22**, plus
   a re-roll 2). Budgets: ≤ 15 k triangles a room, sofa ≤ 3 k, bed ≤
   3 k, the rest ≤ 1.5 k; calls in its looks down by at least 50 (the
   code furniture's materials replaced by one atlas call); 1024² KTX2
   (+~1.5 MB GPU once for the type); wire ≤ 600 kB. **0-24 credits.**
   **Built** (2026-10-23, no credits: the captain paused the remodel after
   it and ruled out the spend): `scripts/deck-models/quarters.py`,
   `lcars-ui/deck/quarters.glb`, one 1024² atlas for every cabin - the
   bed (1.6 and 1.2: a plinth over a kick, the duvet with its top folded
   back, pillows, a headboard in upholstered channels in a wood frame),
   the sofa and armchair (common.py's measures, rolled arms, legs, a
   warm taupe weave), the nightstand, coffee table, round side table,
   the low cabinet under the screen, the desk (its books and the
   screen's stand in it) and a five-star desk chair, the table and
   floor lamps (the page's lit shade kept over them), the wardrobe and
   the two PADD shelves (lounge.glb's, moved here: a cabin no longer
   loads the lounge's glb). 15 props, 13.3 k triangles: the beds 1652
   and 1276, the sofa 1768, the rest 252-1392. Wire 214 kB glb + 300 kB
   KTX2 (381 kB as webp). At low, the twelve looks of three cabins
   (deck 7's first two, deck 9's first): calls -1 to -9 a look (one +10,
   a neighbour built in deckshots' wait), triangles +2 to +13 k (the
   stand-ins' collapsed ones still counted); boot 39.1 s against 41.9.
   deckmem `--check` at low passes (decks 12 and 3's cabins on the walk):
   boot 281 MB of WebGL memory, textures at a walk's end 273 MB (269
   before), peak 476 MB, nothing growing loop to loop, the forced
   context loss restored.
   **The calls' target (-50) was not reachable**: slice 2 had already
   put the code furniture's materials in one batch per material across
   the deck, so what remained per cabin was a few calls. By eye at high
   the scripted sofa and bed read as furniture, not blocks, and beat
   main's (the report); the generated road (22 credits) is left for
   later.
6. **Bare walls and the turbolift** (deck-polish.md slices 5 and 8, as
   planned there; the riding look first for 8). 0 credits.
7. **Conference, classroom and mess, baked.** As 5, one glb a type: the
   conference chairs (high-backed, the shape and seam must read in a
   dark leather: the generated road if scripted blocks again, **11-12**),
   the table with an inlay (scripted, the grain from `T.grain` in the
   bake), the classroom's desks, the mess's counters (scripted).
   Budgets as 5. **0-12 credits.**
   **Built** (2026-10-23, 0 credits: the captain paused the remodel
   and spent none): scripted, `conference.py` (`conf_table` 700
   triangles, built at L 6 and stretched by the page; `conf_chair` 908,
   lounge.py's chair re-dressed in an oxblood leather in three channels
   with piping, its shell, arms and pedestal the brushed trim: it reads
   at a phone's distance, so the generated road was not needed),
   `school.py` (four desk tops in the page's cushion colours and wood,
   268 each; the stool 216; the screen's frame 768, its display the
   room's panel kept over it), `mess.py` (table 200, chair 164,
   replicator bay 204, its lit niche kept over it; the messes no longer
   load Ten Forward's 2048 atlas for its tables and tub chairs). The
   biggest rooms' furniture: conference ~11.6 k, classroom ~12.4 k,
   mess ~14.7 k. Wire (atlases.json's, the glb with its KTX2
   atlas): conference 502 kB, school 431, mess 431, under 600 (the
   UASTC normal map most of it; with the webp 135, 118, 92). The three
   atlases loaded as KTX2 in headless Chromium (`atlasVia`). At low, on
   decks 2, 22 and 25 (four looks each): calls 1-6 down a look (most
   156 to 151), triangles 1.6-6.8 k down, boot within noise (38.6 s
   main, 37.7 s branch). **The calls target (-30) is not met, and
   cannot be in these looks:** it was set before slice 2, whose batching
   took them from ~400 calls to at most 156; each room's own cell now
   draws 11-17 calls, nearly all its shell (walls, ceiling, rail, light
   panels), and the furniture's code materials were at most 6 of them.
   Two first-bake faults caught in the looks: a brushed rim lofted as a
   full-width solid capped over the table's wood and the desks' colour
   (now each rim tops out under the top it rings).
8. **Lightmap pilot, Ten Forward.** The room's shell and its baked
   props exported from the page (three's `GLTFExporter` in headless
   Chromium, the merged static meshes of that room), a second UV set and
   a Cycles diffuse bake of the room's own lights in Blender (direct
   and indirect, no colour: a light-only map), back as `uv2` and
   `lightMap` on the room's merged materials, KTX2 ETC1S 1024². The
   question it answers: does graphics low look grounded without GTAO,
   and what does it cost a room. Budgets: +0 calls, +0 triangles, +1
   texture (~0.7-1.5 MB GPU), boot within noise, the shadows' look kept.
   0 credits. If it wins, a slice a room.
9. **`gen.py`** (section 3.4) and the prompt kit in deck-pipeline.md's
   steps. Built when 5 or 7 first takes the generated road. 0 credits
   to build.
10. **Hydroponics and sickbay.** The grow lights' emissive under the
    threshold with a magenta wash on the plants from a pooled light (the
    light, not the panel, carries the colour); troughs with a soil top
    and a rim; sickbay's cabinets as a scripted prop (doors, a handle, a
    lit strip) and the biobeds' tubs with a lip and the bed's display.
    Scripted; a generated plant pack (**~11-12**) only if the current
    foliage is judged the weak part. Budgets: ≤ 5 k triangles a room,
    +0 calls (into the sickbay atlas already there).

**The credits, all ten:** 1.5-3 (4) + 0-24 (5) + 0-12 (7) + 0-12 (10):
**about 2-50 Higgsfield credits**, most of it only if a scripted sofa,
bed, chair or plant reads as a block. Tripo API credits: 10 if the
image-to-multiview trial (section 2) is wanted, 40 a prop on that road,
on a paid account only.

**Recommended first:** 1 and 2 (the iPhone's memory and its frame,
0 credits), then 3 (one evening, decides every look after it), then 4
and 5.

## 7. Not verified

- **Higgsfield's 3D jobs are in no public doc**: names, parameters and
  prices are the CLI's own (`model get`, `generate cost`, 1.2.2). What
  `3d_jutsu_angles` (2.5 credits) makes was not tried; whether
  Higgsfield's H3.1 job uses Tripo's `delight` or `smart_low_poly`
  internally is not said anywhere (its parameters do not include them).
- **Higgsfield's credit in money**: the billing page's example (1.5
  credits = $0.094) is marked illustrative, so Tripo's API (1 credit = 1
  cent) and Higgsfield's are not compared in money here.
- **Tripo's P-series prices**: the price list's P tab did not render as
  text; 8e was billed 50 for a P1 multiview. Tripo's output sizes for
  `texture_quality` standard and detailed are not in the docs (2048²
  and 4096² are what 8b and 8e got). Tripo's v3 generation docs have no
  `style` parameter (asked for in the order; none found).
- **Tripo's own input tips** come from its tutorials as search quoted
  them (the pages answer 403 to a fetch).
- **iOS Safari's WebGL memory limit** is from forum reports, not Apple.
- **The call budget** (~100-120 on a phone) is two blogs' working rule,
  not a spec; our own number comes from deckshots and the captain's
  phone.
- **KTX2 sizes** on our atlases were measured by slice 1 (section 6, its
  "Built"); what an iPhone's Safari transcodes to (ASTC or ETC2) is
  WebKit's in Playwright, not a real phone's.

## 8. The report

<https://<server>/media/reports/2026/10/deck-remodel-practice-pipeline-slices-89097d56.html>: this doc, with six of the survey's sheets (engineering, quarters,
the conference room, hydroponics, sickbay, the gym) before section 6.
