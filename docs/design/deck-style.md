# Deck style: a style guide for the 3D deck

Number One's order for the captain, 2026-10-15: make `lcars-ui/deck.html`
look designed. That means objects, decorations and crew that belong to one
ship. From now on models may be built in Blender (4.3, headless on the box:
`blender -b -P script.py`, exporting glTF), and CC0 packs (Kenney,
Quaternius, Poly Haven) may be used if their licence files are kept.

This guide is for the slices after `deck-models.md`. That doc's eight
code-built slices are done (0.187.0-0.188.6), and its budget facts still
hold: **a material is a draw call**, **static geometry is merged deck-wide
per material** (`mergeStatic`), and **phones run graphics "low"** (no
composer, no AO; contact shadows stand in for it).

## Looked at: deck 8 at 0.213.0

`python3 lcars-ui/test/deckshots.py OUT` was run at 390x844, graphics
low, with SwiftShader timings:

| | 0.213.0 |
|---|---|
| boot to ship built / crew | 49.3 s / 56.2 s (SwiftShader) |
| most draw calls in a view | 216 (concourse, looking forward) |
| most triangles in a view | 1.32 M (concourse); arboretum 1.07-1.19 M; every other room 0.48-0.80 M |
| frame p50 over 28 views | 1229 ms (SwiftShader) |
| shadow redraws | 0 of 56 frames |

What the 28 views say, room by room. The labs and sickbay are generated
rooms on the wings, which deckshots does not visit. They were judged from
their builders (`ROOM_T.lab`, `ROOM_T.sickbay`), and deckshots should get them
(see part 4).

- **Bridge.** The architecture reads well: the round beige wall, the
  ribs, the wooden rail and the viewscreen. The furniture does not. Looking
  aft from the middle, the captain's chair fills a third of a phone's
  screen, and it is two red slabs with no seam, piping or headrest. The
  conn and ops consoles are a black box with an LCARS quad on top. The
  carpet (`carpetBridge`, a terracotta) is warmer than every other surface,
  and the ceiling beams are a flat grey.
- **Corridor.** This is the most believable place on the deck: the
  panels, the coffer light, the displays, the blue-grey carpet and the
  orange skirting. Nothing structural is wrong. A few dressing props (a
  wall comm panel, a door's chevron plate) are all it wants.
- **Ten Forward.** The bar is good from across the room. The chairs and
  tables are better since 0.188.1, but the room is beige panelling like the
  corridor, when Ten Forward is a darker, moodier room. The forward window
  wall reads as a flat panel, not the long, sloped glass the room is known
  for.
- **Ready room.** It has the wrong floor: wooden planks, under a heavy dark
  plank ceiling, so the room reads as a log cabin. Picard's ready room has
  a grey-blue carpet and a light ceiling. Its desk, sofa and armchairs read
  as furniture. The aft PADD shelves stand empty, like bare racks.
- **Observation lounge.** The table and the oval light ring are right.
  The chairs are the bridge's red leather, where the lounge's high-backed
  chairs are darker. The sofa under the screen is a bench.
- **Arboretum.** The ashlar walls, trees and lawn work. The stepping
  stones are flat grey ovals, and the pond's fountain is a plain bowl.
- **Concourse.** It has the scale. The plinth's LCARS rainbow ring is the
  loudest thing on deck 8, and the benches and columns are bare primitives
  next to it.
- **Labs and sickbay (from the code).** `bench2`, the specimen cases and
  the biobeds are rounded boxes in `M.console` and `MX.white`. A biobed has
  no headboard display frame and no curved base. The surgical arch is a
  torus.
- **Crew (every room).** They are believable at 10 m and less so at 2 m:
  see part 3.

## 1. Palette and materials

**Rules for every family.** At most **six materials of its own** per room
family. Everything else comes from the shared set (`M.*`, `MX.*`). A new
material earns its place only if it covers a large surface or carries a
whole pack's atlas (part 4). Colours are the sRGB hex passed to
`surf()`/`std()`. Roughness and metalness are the `MeshStandardMaterial`
values. "Texture" names one of the generated textures in `T`, or a baked
atlas.

**The ship-wide base.** All families use these, as they are today:

| role | hex | rough / metal | texture |
|---|---|---|---|
| wall panel (TNG "putty") | `#d6c4a6` | 0.8 / 0 | `T.panel`, 2.4 m tile |
| low wall, wainscot | `#6a5646` | 0.7 / 0 | `T.grooves` |
| console body | `#2e2926` | 0.55 / 0.35 | `T.brushed` |
| trim, brushed | `#958c80` | 0.45 / 0.5 | `T.brushed` |
| LCARS accents (emissive only) | `#ff9933` `#cc99cc` `#9999ff` `#ffcc99` | - | - |
| status red (door band) | `#cc3322` emissive | - | - |

### Bridge

TNG reference: a horseshoe of curved wood (the tactical rail) behind three
chairs in burgundy leather. The command well's carpet is a deep, cool
grey-brown, and the wall is putty with dark brown wainscot. The ceiling is
a light dome with a ring of beams, and grey-black stations stand round the
wall under amber LCARS.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| leather (chairs, console lips) | `#5e1f1c` | 0.45 / 0 | `T.pebble` 0.25 m; deeper than `M.leather`'s `#6a2620`; piping in the atlas |
| rail wood (tactical, well rim) | `#5a3a28` | 0.35 / 0 | `T.grain` lacquered; clearcoat-like env 0.6 |
| carpet | `#5a4a44` | 0.95 / 0 | `T.carpet` 0.7 m; cooler than today's `#6a4a3a`, which outshouts the wood |
| console body | `#2a2624` | 0.5 / 0.3 | shared `M.console` |
| ceiling beams | `#a49c90` | 0.6 / 0.2 | `T.brushed`; today's mid grey reads as unfinished |
| chair atlas | one 1024² webp | per texel | Blender bake: leather, seams, brushed arm plates, light strips |

### Corridor

TNG reference: putty panels between rounded ribs, a blue-grey carpet
running between dark wainscot, and orange LCARS strips at skirting and
cornice. The coffered light runs down the middle. Everything is soft-cornered.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| carpet | `#3c4a60` | 0.95 / 0 | as today, `M.carpet` |
| wall, wainscot, trim | shared base | | |
| comm panel / door plate | `#1e1c1b` | 0.4 / 0.4 | in the corridor dressing atlas |
| skirting light | `#ff9933` emissive 2.0 | | `M.glowAmber` |

The corridor keeps its look. Its only new material is the dressing atlas
for comm panels, plaques and door chevrons.

### Ten Forward

TNG reference: a long, low lounge under a sloped wall of windows. It is
dark: a grey-violet carpet, walls in a deep warm grey rather than putty,
and black tables. The chairs are grey-mauve tub chairs on one foot, and
the bar is lit from behind, with a stack of bottles.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| carpet | `#3d3a58` | 0.95 / 0 | as today, `M.carpetTF` |
| wall (new: Ten Forward's own) | `#6e6660` | 0.75 / 0.05 | `T.panel`; replaces putty, so the window and the bar are the light |
| table tops | `#141416` | 0.25 / 0.1 | gloss black; env reflection shows the lamps |
| chair fabric | `#544a66` | 0.85 / 0 | as `M.fabric` |
| bar front | `#2a2220` | 0.4 / 0.2 | a dark panelled front, amber kick light |
| bottles | `glassMat`, tinted per instance | | as today |

### Ready room and observation lounge (the senior staff's rooms)

TNG reference for the ready room: a grey-blue carpet, putty walls and a
light ceiling. It has a desk of dark wood and black, a grey sofa under the
window, the fish tank and the replicator. The observation lounge has a
long, curved table, black high-backed chairs, a wall of windows, and ship
models in cases.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| carpet (new: replaces the plank floor) | `#4a5260` | 0.95 / 0 | `T.carpet` |
| ceiling (replaces `ceilWood`) | `#b4ada0` | 0.85 / 0 | shared `M.ceil`; the beams stay, in `#5a3a28` |
| desk and table wood | `#4a3022` | 0.3 / 0 | `T.grain` fine, lacquered |
| sofa and armchairs | `#6a6460` | 0.85 / 0 | warm grey; today's `#7a4636` is the bridge's red again |
| lounge chair leather | `#1c1a1a` | 0.45 / 0 | black, not the bridge's burgundy |
| case glass | `M.glass` | | as today |

### Arboretum

TNG reference: a planted courtyard under a glass roof, with low stone
walls, raised beds, gravel paths and a still pond. Its colour comes from
the plants. The hard surfaces are warm, pale and matte.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| ashlar walls | `#c2b294` | 0.9 / 0 | as today, `M.ashlar` |
| stepping stones (new) | `#9a9284` | 0.95 / 0 | `T.pebble` with colour noise: today's flat grey reads as plastic |
| bark, foliage | as today | | |
| bench wood | `#7a5a3e` | 0.6 / 0 | weathered, not lacquered |
| water | `pondMat` | | as today |

### Concourse

TNG reference: there is none on screen. It is the ship's civic hall, so it
borrows the Galaxy-class vocabulary at a larger scale: putty and bronze,
stone floor, glass roof. LCARS colour belongs on displays, not floors.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| floor tile | `#7a746a` | 0.7 / 0.05 | as today, `MX.floorTile` |
| plinth ring (since 0.241.0) | `#3a3632` + amber inlay | 0.4 / 0.3 | the LCARS rainbow on the floor went (the captain's yes, 2026-10-16). A ring of dark honed stone, its own `std()` in place of the rainbow's canvas material (no shared one is a dark stone), with one amber light line in the shared `M.glowAmber` |
| column bronze (new) | `#8a6a44` | 0.35 / 0.8 | brushed, `T.brushed` |
| bench | dark wood `#4a3022` on bronze | | from the concourse atlas |

### Labs

TNG reference: white and pale grey walls, cool light, and slanted black
consoles with LCARS. The work surfaces are grey with rounded fronts, and
there are glass specimen cases.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| wall | `#e2e2de` | 0.6 / 0 | as `MX.skinLab` |
| bench body | `#9aa0a8` | 0.5 / 0.3 | a light grey, not `M.console`'s near-black: the lab reads as clean |
| bench top | `#2a2a2e` | 0.35 / 0.2 | black, a lit display laid in it |
| floor | `MX.floorTile` | | |
| lab atlas | one 1024² webp | | benches, cases, a microscope station, sample racks |

### Sickbay

TNG reference: a pale room in white, grey and soft blue. The biobeds have
a curved base and a display panel at the head, and the surgical bed has
the "clamshell" arch. The doctor's office is behind glass.

| material | hex | rough / metal | texture notes |
|---|---|---|---|
| shell (beds, arch, cabinets) | `#e8e6e0` | 0.35 / 0 | as `MX.white`, slightly glossy plastic |
| bed pad | `#7a8ea0` | 0.85 / 0 | soft blue, not a sheet |
| head displays | `panelMat` | | as today |
| sickbay atlas | one 1024² webp | | biobed, arch, tray, hypospray rack |

## 2. Props, room by room

Each room's props are ranked by **time on screen x distance from
believable**, as `deck-models.md` ranks. Sizes are width x depth x height
in metres. Class (part 4): **H** hero, **F** furniture, **D** dressing.

### Bridge

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | captain's chair (and the two either side) | `chair(…, rich)`: rounded slabs, seen from behind it is two red boxes | a sculpted seat, back and headrest in one shell, piped seams, a brushed plate down the back, padded arms ending in the armrest consoles | 0.75 x 0.8 x 1.25 | bridge leather, chair atlas | H |
| 2 | conn and ops consoles | `consoleBody` wedge, black, quad on top | a flared pedestal, a bevelled top that overhangs on the near side, a leather lip, and the display set in a recess | 1.4 x 0.75 x 0.9 | console body, bridge atlas | H |
| 3 | tactical rail | a curved wood band on posts | the rail's carved profile (rounded top, undercut), a lit tactical panel set in its top behind the captain | arc r 4.5, 1.05 high | rail wood, bridge atlas | H |
| 4 | armrest consoles (either side of the command chairs) | wedges | a slim pedestal, a bevelled top tilted to the chairs with the display in a recess, the lights on its near face (0.237.0) | 1.1 x 0.5 x 0.65 | console body, bridge atlas | F |
| 4a | conn and ops chairs | `chair(…, 0.9, rich)` | armless: a seat in a shell pan, a slim back with a low headrest on a stem, the command chairs' pedestal (0.237.0) | 0.58 x 0.6 x 1.3 | bridge leather, bridge atlas | F |
| 5 | standing stations round the wall | sloped tops on boxes | kick plate, side panels with a seam, a lit slot at the foot | 1.2 x 0.6 x 1.1 | console body | F |
| 6 | ceiling dome | radial grey beams | lighter beams (palette), a lit ring in the coffer | - | ceiling beams | (code) |

### Corridor

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | comm panel beside each door | a small box | a black plate with a lit LCARS strip and two buttons | 0.18 x 0.04 x 0.3 | corridor atlas | D |
| 2 | door chevron plate / room plaque | text on the lintel | a brushed plate with the room's number | 0.4 x 0.02 x 0.12 | corridor atlas | D |
| 3 | wall-mounted PADD rack | none | an occasional rack with two PADDs (breaks the rhythm) | 0.5 x 0.1 x 0.4 | corridor atlas | D |

### Ten Forward

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | the forward windows | a flat window wall | a sloped glass wall in its mullions (`windowWall` raked ~20°), a dark sill seat along it | 18 x 0.5 x 3.0 | wall, glass | H (code) |
| 2 | tub chairs | lathe shell on a post | one modelled chair, an upholstered tub with a seam and a domed foot, instanced | 0.6 x 0.6 x 0.8 | TF atlas | F |
| 3 | bar | wood box, padded edge, rail | a dark panelled front with an amber kick light, a glass display shelf lit from below, a curved end | 9 x 0.8 x 1.1 | TF atlas | H |
| 4 | tables | rolled-edge disc | gloss black top with a thin metal rim | ø0.9 x 0.74 | table tops | F |
| 5 | bottles | lathe, instanced | as today; fine at the distance | - | - | D |

### Ready room

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | floor and ceiling | wooden planks; a dark plank ceiling | carpet; a light ceiling with dark beams (palette, no model) | - | carpet, `M.ceil` | (code) |
| 2 | desk | wooden box with things on it | a desk with a curved front in dark wood on a black base, a desktop terminal at an angle | 1.8 x 0.9 x 0.76 | ready room atlas | H |
| 3 | PADD shelves | empty racks | the same racks dressed: PADDs leaning, a few books, a small sculpture | 1.2 x 0.35 x 1.8 | ready room atlas | F |
| 4 | fish tank | box with water | a tank with a rounded top, gravel, a few fish cards | 1.2 x 0.4 x 0.8 | glass, atlas | F |
| 5 | sofa, armchairs | `seat()` | warm grey upholstery (palette); the shape holds. Since 0.240.0 common.py's sofa (at 2.3 and 0.95) in this atlas | 2.3 / 0.95 x 0.86 x 0.84 | sofa, atlas | F |
| 6 | bookcases (x2) | `bookcase()`, wood with instanced books | since 0.240.0: dark wood, the racks' wainscot back, runs of books, a stack, PADDs, a brass globe | 1.4 x 0.32 x 2.45 | ready room atlas | F |

A plain wall's rail stands 8 cm proud of both faces at 1.0 m, through the
back of anything set against the wall; `wall()` takes `railGaps`, the
spans where that face's rail stops (the ready room's shelves and
bookcases, since 0.240.0). A sofa stands 10 cm off the wall instead.

### Observation lounge

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | high-backed chairs (x10) | the bridge's chair, red | one black high-backed chair, instanced | 0.6 x 0.6 x 1.2 | lounge leather, atlas | F |
| 2 | table | long top, lit inlay | as today, with a darker lacquer | - | desk wood | (code) |
| 3 | ship models in cases | primitives in glass | fine at the distance | - | - | D |

### Arboretum

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | fountain | a plain bowl | a stone basin on a pedestal with a carved lip | ø1.2 x 0.9 | stone atlas | F |
| 2 | stepping stones | flat grey ovals | the same shapes in the stone texture (palette) | ~0.5 | stepping stones | (code) |
| 3 | benches | slats on legs | a garden bench, wood on cast metal | 1.6 x 0.5 x 0.85 | arboretum atlas | F |
| 4 | raised beds | boxes | a stone kerb with a soil top | as today | ashlar | (code) |

### Concourse

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | plinth floor ring | LCARS rainbow | dark stone, one amber inlay (palette) | ø8 | plinth ring | (code) |
| 2 | benches round the plinth | slab benches | curved benches following the ring, dark wood on bronze | 2.4 x 0.55 x 0.45 | concourse atlas | F |
| 3 | columns | thin grey cylinders | bronze columns with a capital and a light at the head | ø0.4 x 4.6 | column bronze | F |
| 4 | directory columns | lit boxes | a slim totem with a rounded top | 0.5 x 0.3 x 2.0 | atlas | F |
| 5 | balcony rails | a glass sheet, a wooden bar, metal posts | a lacquered handrail on a bronze channel, a bronze shoe, bronze posts; the glass and the light under the edge stay code (0.241.0) | 1.6 m bay, 1.0 high | atlas | F |
| 6 | balcony doors | a grey slab with two lights | a two-leaf door in a bronze frame, its head two bars round the amber light (0.241.0) | 1.7 x 2.5 | atlas | F |
| 7 | balcony slabs | a plain box | an edge in the slab's putty: a lip, a fascia with a reveal, a drip lip, the soffit's cove the amber light hangs in; the body stays code (0.248.0) | 1.6 m bay | atlas | F |
| 8 | balcony glass | a glass sheet | a framed pane: bronze beads over the shoe and under the channel, a stile at each end of the bay; the glass stays `M.glass` (the atlas has no transparency) (0.248.0) | 1.6 m bay | atlas | F |
| 9 | plinth | a dark cone, a blue band | dark honed stone (plinth ring's `#3a3632`): a kick, a base course, a groove carrying the ring's amber line, a bevelled top face (0.248.0) | ø5.4 x 0.7 | atlas | H |
| 10 | hologram's top | a bare lit disc | a bronze bezel round the disc and an emitter boss at its middle, a console-black lens; the disc stays code (no emission in the atlas) (0.248.0) | ø4.7 | atlas | F |

### Labs

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | work bench | `bench2`, black box | a light-grey body with a rounded front, an inset black top with a display, a kick recess | 2.4 x 0.75 x 0.92 | lab atlas | F |
| 2 | specimen case | box + glass | a lit case with a base and shelves, a sample inside | 0.9 x 0.6 x 1.5 | lab atlas | F |
| 3 | hologram table | cylinder + disc | a flared pedestal, a ring rim, the emitter disc | ø1.5 x 0.85 | lab atlas | F |

### Sickbay

| # | prop | today | should be | size | material | class |
|---|---|---|---|---|---|---|
| 1 | biobed | rounded boxes | a curved base, a padded top, a head display on an arm | 2.0 x 0.9 x 0.75 (display to 1.6) | sickbay atlas | F |
| 2 | surgical bed and arch | box + torus | the clamshell arch on its hinge, the bed on a pedestal | 2.1 x 1.0 x 1.7 | sickbay atlas | H |
| 3 | instrument tray, hypo rack | none | a tray on a post by each bed | 0.5 x 0.35 x 1.0 | sickbay atlas | D |

## 3. The crew

**Uniforms** (TNG seasons 3-7, the jumpsuit with the black yoke). These
are `CREW_UNI`, kept, plus what to add:

| division | hex today | keep / change | notes |
|---|---|---|---|
| command | `#8e1b1b` | **`#7e1a1e`** | TNG command is a deep crimson, slightly blue. Today's reads orange under the warm lights |
| operations (engineering, security) | `#b88a2a` | keep | mustard gold |
| sciences (medical, science) | `#2c6070` | keep | teal |
| yoke, trousers, boots | `#0b0b0d` | keep | |
| combadge | `#d4b25a` metal 0.9 | add | the delta on an oval, on the left chest, 6 x 5 cm |
| rank pips | `#d4b25a` | add | 1-4 on the right collar, by role |
| Ten Forward's host | `#5a2a6a` robe and hat | keep | |

**A convincing idle.** The weight is on one leg and shifts every 6-12 s.
Breathing is visible at the chest (2-3 mm, ~0.25 Hz). The head looks
around in small saccades with longer holds, and blinks every 3-5 s. The
hands are never still at the same height, and arms are not straight down
(today's clip comes close). Two people idling side by side must not be in
phase: randomise the clip's start time and its rate by ±10%.

**A convincing walk.** The feet are locked to the floor: the rate is
matched to the speed, as today. Arm swing is opposite the legs at about
30°. TNG officers walk upright and brisk (1.3-1.5 m/s in corridors, the
"formal" walk), never swaggering. Turns are eased over ~0.3 s, not
snapped. Speed eases at a start and a stop (0.4 s), and a walker steps
aside for another in a corridor.

**What the Quaternius bodies lack.**

- **Proportions.** The "Superhero" base meshes have a wide chest and big
  shoulders and arms. Every officer looks like a bodybuilder in a
  bodysuit. Wanted: a slimmer base (the pack's regular body, or scale the
  bones in Blender: chest x0.9, upper arm x0.9).
- **Clothing.** The uniform is painted on the skin (`cloth` in
  `crewBodyMat`), so it has no thickness, no seams at the shoulder or
  sleeve, no folds at elbow or knee, and no boot. Wanted: a uniform mesh
  over the body (or the body's own mesh with a cloth normal map baked in
  Blender: seams, a zip-less front, ribbing at the cuffs), boots as a
  separate black glossy part.
- **Insignia.** There is no combadge and there are no pips: the two
  details that say Starfleet at any distance.
- **Faces and hair.** The faces are generic and the hair is a helmet. Hair
  is the cheapest gain: two or three more styles (TNG short back-and-
  sides, a bob, a ponytail), skinned to the head bone as now.
- **Clips.** There are eight. Missing: idle variants (weight shift, arms
  folded, hands behind back), a PADD-reading idle, and a stop/start. The
  Universal Animation Library has more clips than the eight we keep:
  re-cut, rotations only, as the assets script already does.

**Where that stands (0.239.0).** Insignia, slimming, seams, idle life and
the eased walk came in 0.219.0 (docs/design/deck-pipeline.md has the
decisions). Since 0.239.0:

- **The packs are on the box**, fetched by `scripts/deck-crew-fetch.py`
  (itch.io's free download, no browser) into the model cache, and the
  crew rebuilt by `scripts/deck-crew-build.sh`. Nothing was taken from
  elsewhere: a body, hair or clips from another source would bring another
  skeleton (retargeting, or a second rig's bones per person), and every
  clip and hair here shares the one; the second Animation Library is the
  same rig, node for node.
- **Clothing**, the shader's way, not a uniform mesh: a mesh over the body
  is a second skinned draw per person and would need its own weights; the
  body's mesh with a baked cloth normal map would need the skin's map
  replaced per texel, while the division colour must stay `clothOf`'s.
  Instead, under the cloth the skin's normal map is off (it was meant to
  be since 0.219.0, and was not: the line that scaled it sits inside a
  shader chunk the page's replace never saw, so the abdominals were the
  map's), the body's normals are a smoothed copy's (the carving gone, the
  silhouette kept), and the cloth has a relief of its own from the bind
  pose: three soft folds either side of the elbow and on the front of the
  knee, 4 cm of ribbing at the cuffs ending in a sunk edge, the seams
  sunk a millimetre. The front has no zip (nothing drawn there). The boots
  are pushed 6 mm proud of the trousers below their top, so they have an
  edge, and are smooth gloss (roughness 0.38): no toes through them.
- **Hair**: nine styles. Three are new, made in Blender from the pack's
  own and on its head bone: Short (TNG's short back-and-sides: Simple
  Parted with the sides and back laid onto the scalp), Bob (Long cut at
  the jaw, the ends turned in) and Ponytail (Long drawn back tight, a
  tapered tail from the crown). Men draw from Short x2, Simple Parted x2,
  Buzzed; women from Long, Bob x2, Ponytail x2, Buns, Buzzed.
- **Idles**: a stander takes one by seed, never the one a neighbour
  within 3 m has: the plain idle (x2, with crewLife's weight shift), hands
  behind the back (x2), arms folded, or a PADD read, with a PADD in the
  left hand and the head bowed to it. Arms folded is the second Animation
  Library's; the other two are the first's idle with the arms re-posed by
  IK in Blender and baked, so they still breathe and sway. Someone at a
  console keeps the plain idle (they reach for it). Each starts a golden-
  ratio step through its clip on from the person dressed before.
- **Stop and start**: no pack has a stop clip, so the blend is timed: a
  walker slowing to a stop keeps the walk until its legs pass (the pelvis
  at its highest, read from the clip), then gives way to the idle in a
  quarter second, holding no more than 0.35 s; a start begins its first
  step from that moment of the walk.
- **Still missing**: faces (two, no morphs; blinks since 0.249.0 are a
  cut, not a lid closing), and thickness at collar and cuffs (only a
  mesh gives that). A PADD for the seated since 0.247.0, a baked pose
  since 0.249.0.

## 4. Rules for new models

1. **A script, not a .blend.** A model is a Blender Python script in
   `scripts/deck-models/<room>.py`, run as
   `blender -b -P scripts/deck-models/<room>.py -- OUT_DIR`. It builds the
   room's props from primitives and modifiers (bevel, subdivision, solidify,
   array), UV-unwraps, bakes them into one atlas, and exports
   `<room>.glb`. Committing the script, not a binary source, keeps the
   model reviewable and rebuildable. A CC0 pack's import is a script too.
   A free-to-use model from the web may be used as well (the captain,
   2026-10-16), licence kept: a script fetches it into the cache, its
   licence text and source URL go into `lcars-ui/deck/LICENSE.txt`, and
   it is cleaned and baked into the room's atlas as `pack.py` does, within
   its class's triangle budget.
2. **Cleaned like the crew.** `scripts/deck-model-assets.mjs` takes the
   raw glbs to `lcars-ui/deck/`, as `scripts/deck-crew-assets.mjs` does
   for the crew. It strips the attributes nothing reads (keep `POSITION`,
   `NORMAL`, `TEXCOORD_0`), runs `prune`, `dedup` and `weld`, and
   quantizes positions (14 bit) and normals (10). Textures leave the glb
   as webp the page loads, at 1024² (a hero room 2048²): base colour
   q82, normal q90, roughness/metal packed into one ORM.
3. **One atlas material per pack or room.** Every prop in a room shares
   one `MeshStandardMaterial` (base colour, normal, ORM from the atlas).
   After `mergeStatic`, the room's whole pack is one draw call. A prop
   needing glass or a glow keeps the shared `M.glass` / `glow()`
   materials for that part. Those already exist, so they add no call.
4. **Triangle budget per prop class.** Merged geometry is drawn
   deck-wide, and today's views are 0.5-1.3 M triangles:

   | class | what | budget per prop | notes |
   |---|---|---|---|
   | hero | seen close and alone (captain's chair, bar, surgical bed) | ≤ 6 k | at most 3 in a room |
   | furniture | repeated (chairs, benches, consoles, beds) | ≤ 1.5 k | instanced if more than 6 in a room |
   | dressing | small (PADDs, panels, trays, cups) | ≤ 200 | instanced; none on graphics low beyond 4 m |

   A room's new geometry is at most **+40 k triangles** with every prop in,
   and the deck's draw calls are at most **+1 per room** (the atlas). The
   dressing is the one exception, merged apart from the rest so graphics
   low can leave it out: **+1 call for the room you stand in, +0 for every
   other room** (on low, drawn within 4 m of its box only;
   deck-pipeline.md, "Budgets").
   Numbers come from deckshots before and after, in the commit.
5. **The code-built prop stays as the fallback.** A glb loads after the
   ship is built, as the crew do (`loadCrew`), and replaces its code-built
   stand-in when it lands. If it never lands (offline, an old phone), the
   room is as today. The stand-in's `block()` footprint and `seatable`
   seats stay, so walking and sitting do not depend on the model.
6. **Where the files live.**
   - `scripts/deck-models/<room>.py`: the Blender scripts
   - `scripts/deck-model-assets.mjs`: the cleaner
   - `lcars-ui/deck/<room>.glb`, `lcars-ui/deck/<room>_{base,norm,orm}.webp`:
     what the page loads; the server serves them under `/ui/`
   - `lcars-ui/deck/LICENSE.txt`: one section per pack used, with its
     licence text and source URL, as `lcars-ui/crew/LICENSE.txt` does
   - raw pack zips: never committed; the script names the zip and its URL
7. **Size and units.** Metres, +Y up, the prop's origin on the floor at
   its footprint's centre, its front facing +Z (the deck's builders'
   convention). Real sizes from part 2's tables.
8. **Checked.** `deckshots.py` on each room touched, its sheets looked at
   on a phone's size; `test/deckboot.js` and `run.sh --changed` green.
   `deckshots.py` should learn to visit one lab and the sickbay (their
   wing rooms) before those rooms' slices.

## 5. Which room goes first

**The bridge.** It is the room the deck is about: the first one forward
from the corridor, the one people come to, and the only room where a
single prop, the captain's chair, fills a third of a phone's screen when
you turn round in the middle of it. Its walls, rail and viewscreen
already read as the Enterprise, so better furniture finishes the room
rather than starting it. All three props that matter fit one atlas and one
added draw call: **the captain's chair (with the two beside it), the conn
and ops consoles, and the tactical rail.** It is also the right room to
prove the pipeline: one Blender script, one atlas, the code-built chair as
the fallback, measured before and after. After it come Ten Forward (the
window wall and the tub chairs), then the ready room's floor and desk.

## 6. Ornate corridors and hull

The captain's order, 2026-10-16, after walking the deck: the corridors
and the hull outside the windows look too flat. Make them ornate. Looked
at on 0.224.0, after every room got its models: `deckshots.py --only
"Corridor,Ten Forward,Observation lounge"`, at 390x844, graphics low.

### (a) The corridor

**What the TNG corridor has that ours lacks.** Ours has the right parts
in the right places (ribs every 2.6 m, a dark wainscot, an amber
skirting light, a sloped cornice, the coffered light), but each part is
a flat slab:

- **Walls.** In TNG, the putty field is made of panels about 1.3 m wide,
  each with a fine reveal round it. Each panel also has a pair of
  recessed horizontal strips about 1.9 m up, a band that runs the length
  of the corridor and ties the panels together. Ours (`T.panel`, 2.4 m
  tile) has one seam and a vent, read at a bump of 5: from 2 m away it is
  a painted wall.
- **Ribs.** In TNG, each rib is a pilaster about 0.3 m wide that stands
  out of the wall in a chamfered profile. A black channel runs down its
  face with the light slot in it, and it has a cap where it meets the
  wainscot and the cornice. Ours is a 0.1 x 0.36 m bar of `M.trim` with a
  glow strip on its side: from down the corridor it is a line, not a
  column.
- **Skirting.** In TNG, a black kick plate about 12 cm high, a hand
  proud of the wall, carries the amber running light along its top. Ours
  has the light and no plate, so the carpet meets the brown wainscot
  directly.
- **Wainscot cap.** In TNG, the dark lower wall ends in a rounded rail
  that can be held. Ours ends in a flat change of colour.
- **Ceiling.** In TNG, the sloped sides have recessed troughs of light,
  and the cross beams have a profile. Ours has a flat cornice and flat
  cross bars, and only the centre coffer reads in depth.
- **Alcoves and wall units.** In TNG, the rhythm of the wall is broken by
  recesses: an emergency locker, a replicator, a tall LCARS wall unit.
  Ours breaks it only with the displays, the comm panels and the PADD
  rack (0.218.0), all of them flat on the wall.

**Where ornament goes, and where it must not.** The corridor is the
deck's longest view and its calmest place, and it should stay that way.
Ornament belongs at the **edges and joints**: ribs, skirting, the
wainscot cap, the cornice line, door frames, and at most **one alcove in
12 m of wall, never opposite another**. It must stay off:

- the upper wall field between ribs, apart from its displays (relief
  only, no props);
- the centre coffer, which is already the brightest, busiest thing in
  view;
- the carpet's walking line;
- the doors' leaves.

No new hues: relief shows as shading (reveals of 4-15 mm), and the only
colours are the palette's putty, brown, black, trim and amber.

**Ranked changes** (time on screen x distance from believable; each
marked **relief** for a normal map in the corridor atlas or a stronger
generated texture, **model** for a prop through `corridor.py`, **code**
for geometry in `corridorDress`):

| # | change | size | material, hex | kind |
|---|---|---|---|---|
| 1 | **Ribs as pilasters.** A chamfered profile out of the wall, a black channel down the face with the light slot in it, a cap top and bottom. Replaces the `M.trim` bar and its side glow (the glow moves into the channel) | 0.32 wide x 0.14 proud x wall height; the channel 0.05 x 0.02 deep | trim `#958c80` 0.45/0.5, channel `#141210` 0.5/0.2, in the corridor atlas; glow stays `M.glowWarm` | model (`rib`, ≤ 300 tris, many per cell) |
| 2 | **Wall panels with reveals.** A corridor-only `T.panelCorr`: panels 1.3 m wide (tile 2.6 m, two to a rib bay), 6 mm reveals all round, a double recessed strip at 1.85 and 1.95 m running the length, bump about 8. The vent drops to one panel in four | 2.6 m tile | putty `#d6c4a6`, roughness 0.75; reveals darken to `#a8987e` in the tone map | relief |
| 3 | **Black skirting plate**, the amber light moved into a slot along its top | 0.12 high x 0.02 proud, the run of each wall | `M.console` `#2e2926` (shared: +0 calls); light `M.glowAmber` | code |
| 4 | **Wainscot cap rail**: a rounded half-round on top of the dark band | 0.06 high x 0.05 proud | `M.rail` `#4a3226` (shared) | code |
| 5 | **Alcoves**: an emergency locker (red cross on black, a handle), a replicator recess (a lit back, a grille), a tall LCARS wall unit. One in 12 m at most, chosen by seed, built 0.12 proud with a frame rather than cut into the wall | 1.1 x 2.2 x 0.3 | corridor atlas; locker `#7e1a1e` on `#1e1c1b`; lit back `M.lightPanel` | model (`alcove_*`, ≤ 1.5 k each) |
| 6 | **Door surrounds**: a thick frame round each door, chamfered, a black inner reveal, the plaque (0.218.0) set in its lintel | 2.4 x 2.9 x 0.15 | trim `#958c80`, reveal `#141210`, atlas | model (`door_frame`, ≤ 600) |
| 7 | **Ceiling troughs**: the sloped cornice sides with a recessed light trough each, and the cross bars given a T profile | trough 0.25 wide x 0.08 deep, the run; bar 0.16 x 0.1 | `M.ceil` `#b4ada0`; trough light `M.lightStrip` | code + relief (in `T.ceil`) |
| 8 | **Carpet border**: a darker 0.3 m band along each wall, inside the trims | 0.3 wide | `#2c3646`, `T.carpet` | code (one more material, last for that reason) |

**Where it stands.** All eight are in: 1, 2, 3, 7 and the locker and
LCARS unit of 5 in 0.225.0; 4, 6, 8 and the replicator of 5 in 0.236.0.
As built, and where it bent: the door frame is 2.3 wide and 9 cm proud,
not 2.4 and 15 (the comm panels stand from 1.16 out of a door's middle,
and the jamb's channel floor must be the post's face, where its amber
strip is). The cap rail is a half-round on a slimmer `M.rail` strip, both
sides of a corridor wall. The carpet border lies inside each floor trim,
toward the walking line, and is in the corridor atlas (`carpet_border`),
not a material: measured as `surf(T.carpet, 0.7, 0x2c3646)` it was +1 to
+5 calls in deck 8's views and up to +13 in deck 12's, one per corridor
cell in view (deck-pipeline.md, "the corridors' leftovers"). So offline
the carpet was plain, until 0.247.1: under each piece of the model is
now a strip of the floor's own material (`borderFloor`, `borderGeo`), its
texture coordinates lifted out of the floor's range so the floor's shader
darkens it to `#2c3646`; it merges into the floor's mesh (+0 calls) and
is collapsed when the model lands. The replicator's lit back, kept over
the model in a stand-in group so it shows without the glb, was a flat
`M.glowWarm` plate; since 0.247.1 it is a lit alcove, a gradient
from a warm-white head to a dim amber foot, darker into its sides, from
one small canvas every replicator shares (`replicatorBack`, one
material: a draw call where one is in view).

### (b) The hull outside the windows

**What is seen.** From Ten Forward, the lounge, the arboretum and the
ready room, you see the saucer's top falling away to its rim. You also
see deck 8's own shell boxes (`deck8Shell`, hull kind 7) a few metres
off, and the bridge's drum. All of it is one `hullMat`: plates in a 6 m
grid and saucer rings of 8 m in two tones, an Aztec patchwork of 2 m at
close range, weathering, window rows and band rings, and glints at the
rim. What is missing is everything that tells a Galaxy-class hull from a
grey one. In the 0.224.0 shots, it reads as a dark plain with a few lit
windows.

**What the Galaxy-class hull shows close up:**

- **Aztec plating** in two close tones of light grey with a faint warm or
  cool cast (`#a7aaae` and `#bcbfc2`), in interlocking stepped blocks 2-6
  m, not a checker.
- **Panel lines**: fine dark lines (`#4a4e54`) round each plate.
- The **dorsal phaser array**: a long ribbed strip near the saucer's rim
  in a coppery dark (`#6a5a4c`).
- **Lifeboat hatches** in rows round the saucer's upper rim, square,
  slightly darker, in groups.
- **Window rows**: some cabins lit warm, some cool, many dark, each in a
  dark frame.
- **RCS thruster quads**: a raised block with four nozzles, at four
  points round the rim.
- **Running lights**: red to port and green to starboard at the rim,
  white strobes in a double flash.
- The **registry** "NCC-1701-D" and "U.S.S. ENTERPRISE" across the
  saucer's top in black-edged grey letters, and the red **pennant**
  stripe along the rim's edge.

**Ranked changes** (each marked **shader** for a change to `hullMat`,
**texture** for one texture it samples, **geometry** for hull parts or
glints):

| # | change | size | colours | kind |
|---|---|---|---|---|
| 1 | **Aztec in stepped blocks, near**: on the saucer top (k 6) and the shell (k 7), two tones of plates in an interlocking pattern. The pattern comes from two offset grids hashed together, not one grid's checker, and fades with distance as today | plates 2-6 m; within 150 m | `#a7aaae` / `#bcbfc2`; stain as today | shader |
| 2 | **Panel lines** round the near plates, anti-aliased by `fwidth` and gone before they shimmer; a faint bevel light on one side of each line, the sun's way, for relief without geometry | 4-6 cm lines | `#4a4e54` | shader |
| 3 | **Lit cabins varied**: warm `#ffd8a0`, cool `#e8f0ff`, dim amber, dark; a dark frame `#2a2c30` round every window; a slow change of a few per minute (lights going on and off) | windows as today | as listed | shader |
| 4 | **Dorsal phaser array**: a ring band on the saucer's top near the rim, ribbed every metre, a faint amber emitter line at its middle | 1.6 m wide, at r ≈ 215 m | `#6a5a4c`, line `#ff9933` at 0.3 | shader |
| 5 | **Registry and pennant**: letters across the saucer's top, and the pennant along the rim's edge, sampled in the saucer's polar coordinates from one canvas texture | letters ~12 m tall; pennant 3 m | grey `#c8ccd0` on a `#2a2c30` edge; pennant `#8e1b1b` | texture (one 1024 x 128 canvas, in `hullMat`: +0 calls) |
| 6 | **Lifeboat hatches**: rows of squares in groups of six between the window bands near the rim | 2.4 m squares, 1 m apart | `#8a8e94` with a dark line | shader |
| 7 | **Running lights and strobes**: white double-flash strobes on the shell boxes' corners and the bridge drum, added to the rim's lights | ≤ 24 more points | as `RED`, `GREEN`, `WHITE` | geometry (glints) |
| 8 | **RCS thruster quads**: four blocks with four nozzles each, on the rim | 5 x 5 x 1.5 m | hull, nozzles `#3a3c40` | geometry (≤ 400 triangles in all) |

### (c) The budgets that apply

**The corridor.** Its merged geometry is drawn deck-wide, and every
corridor cell is a draw call (its atlas mesh, 0.222.0). So relief comes
before triangles:

- A change that can be a normal or a texture is one.
- A model goes into the corridor atlas that every cell already has: +0
  calls.
- A cell gains at most **+5 k triangles**: ribs ~300 x ~16 a cell,
  alcoves 1.5 k, frames 600 a door.
- **The deck gains at most +1 draw call** in a view: the corridor-only
  wall material of change 2, or the carpet border of change 8, not both.
- A generated texture is made at boot on the CPU (`texSet`), so boot must
  stay within noise in deckshots: a 512² set is fine, 1024² is measured.
- Changes 3, 4 and 7 add no material: they reuse shared ones.

**The hull.** It is seen from four rooms at once and fills up to half a
phone's screen in Ten Forward and the lounge. So its cost is per pixel:

- Every change is in `hullMat` or `glints`: **+0 draw calls**.
- **At most one texture fetch added** (the registry's canvas).
- The fragment shader grows by at most about a third in instructions. On
  graphics low (no composer, every phone) the shader is all there is, so
  deckshots' frame p50 in the four rooms must stay within noise.
- New hull triangles are **+2 k** at most (the RCS quads) and glints +24
  points.
- Every near detail (Aztec, lines, hatches, frames) fades by distance and
  `fwidth` before it can shimmer, as the seams and windows already do.
- The detail is spent on the saucer top and the shell (k 6 and k 7),
  which the windows see. The nacelles and the engineering hull, seen only
  far off, are left as they are.
