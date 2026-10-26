# Deck polish: the rooms after the bridge (2026-10-21, main 0.291.2)

Number One's order of 2026-10-21, night (thread deck-redesign), on the
captain's authority: keep making the deck look better until morning, looks
only, no new features. The bridge is done for now (bridge-redesign.md
section 9, slices 1-5, 0.287.2-0.291.1). This doc is the survey of every
other room a visitor walks through, the worst looks ranked by what a
stranger on Thursday's r/threejs post would notice in the first minute,
and the cheap slices that mend them, worst first.

**The report** (every room's four looks, the three concepts, this plan):
<https://<server>/media/reports/2026/10/deck-polish-survey-and-plan-871ab200.html>.

## 1. The survey

`lcars-ui/test/deckshots.py` at graphics **high**, 390x844 at 2x (a
phone's portrait at half the pixels: the survey is for looks, and 3x
software rendering would not fit the job line's 40 minutes), standing at
each room's walkable middle looking to the four quarters. Three jobs
(about 50 minutes in all): deck 8's rooms, the wing's lab and deck 12's
sickbay and corridor; then deck 7's and 10's generated rooms and the
turbolift (three `--view` looks); then the big generated rooms. 29 rooms,
119 looks. At high the counts are the composer's one pass (1 call, 2
triangles), so the calls and triangles below are each slice's own before
and after at graphics low.

| where | rooms |
|---|---|
| deck 8 | Corridor, Ready room, Observation lounge, Ten Forward, Arboretum, Concourse, Stellar sciences, Sickbay, the wing's lab |
| the turbolift | the bridge's port car: door, back wall, panel |
| deck 12 | Sickbay, the corridor outside it |
| generated | quarters, mess, storage, transporter, observation (deck 7); gym, school (10); conference (2); shuttlebay (4); holodeck (5); cartography (6); hydroponics (11); cargo (18); engineering (36) |

What holds up: the corridors (deck 8's and the generated streets), the
concourse's architecture, stellar cartography, the holodeck's grid, Ten
Forward's bar and window, the arboretum's trees and path, the labs'
consoles, the sickbay biobeds.

## 2. The worst looks, ranked

Ranked by time on screen (every generated room is behind a door the
visitor passes) times distance from believable.

1. **White glare on the generated rooms' ceilings.** The mess, quarters,
   storage, cargo bay and shuttlebay each have a blown-out white blob over
   them, bigger than the panel it stands for. The cause is `shell()`'s
   light spots at `h - 0.7`: a pooled point light (decay 1.6) 0.7 m under
   the ceiling lights it at about 6x what it gives the floor 2.3 m below,
   and the high composer's bloom spreads it. It is the first thing seen on
   entering any generated room.
2. **Black crates.** The cargo bay's crates and the storage room's boxes
   are near-black cubes with a small tan patch of label, though
   `crateTex` is a light tan with a dark rim. They read as broken. The
   cause is not yet known: neither instanced mesh has a `tile` for
   `autoUV`. Slice 2 finds it first.
3. **Flat pale-blue glow shapes.** The transporter's six pads and six
   emitters, the mess hall's replicator alcoves, the shuttle's windows and
   the cargo bay's pad are unshaded flat `glow()` discs and rectangles in
   one pale blue, with no rim, ring or depth. The transporter room is the
   worst: the platform is a wood-toned hexagon with six flat blue
   ellipses. The concepts show what they could be: frosted emitter discs
   with concentric rings and a metal rim, and lit niches.
4. **Faceted hologram orbs in the labs.** Each lab's holo table orb is an
   `IcosahedronGeometry(0.28, 1)` (80 faces). The fresnel shader shows
   every facet, and from the table's side it fills the view as a cut-glass
   ball. The table's disc under it is a flat saturated blue.
5. **Bare walls in generated rooms.** Observation lounge 7-A (an inner
   room, no hull, so no window: an observation lounge facing a blank
   wall), the gym, the conference room, the classroom, quarters: walls of
   blank panels with only the small vent squares. The quarters concept
   puts a framed picture, an LCARS plaque and a small viewport on that
   wall.
6. **The arboretum pond reflects a studio.** `pondMat` mirrors
   `scene.environment`, three's `RoomEnvironment`, whose white light boxes
   show as large white blobs on the water. The pond should mirror a night
   sky.
7. **Dark, featureless carpets.** The ready room, the observation lounge,
   Ten Forward and the mess have carpets at 0x3d-0x4a that read near-black
   at a phone's exposure, so half of each view is an empty dark floor. The
   ready room's rug shows how a pattern breaks it up.
8. **The gym's mats** are flat saturated blue slabs (`MX.mat`), the
   biggest thing in the room.
9. **The turbolift's back wall** washes to white from inside the car. Its
   one light is 0.5 m under a 3.3 m ceiling, 1.3 m from the wall. The
   door and the panel looks are fine.

Noted, not slices: the concourse's middle look stands inside the plinth's
rail, which is deckshots' centroid, not the room; and the warp core's top
blooming white is the core's own look.

## 3. The concepts

Three Seedream 5.0 Flash images (`seedream_5_0_flash`, 9:16, 2k, 0.5
credits each: **1.5 credits**, 749.75 to 748.25), each from that room's
survey look with the pills cropped off, under one lead line: keep the
room, camera and layout, repaint it as a polished TNG set for a real-time
game, with soft cove light and no ceiling glare. Each prompt adds one line
of its own:

- **Mess hall** (deck 7, look 0): replicator niches framed in the
  wall's beige, lit inside with an LCARS strip over them; a cove-lit
  ceiling trough; a carpet border.
- **Quarters** (deck 7, look 3): a framed picture, an LCARS plaque and a
  small starfield viewport on the bare wall; a cove light line under the
  ceiling.
- **Transporter room** (deck 7, look 0): frosted emitter discs with
  concentric rings and a bright metal rim, the same overhead, warm and
  cool wall panels with LCARS strips.

## 4. The slices, worst first

Each slice keeps bridge-redesign.md section 6's rules. Calls +0 where
possible (a new material is a call in every room it shows in). Triangles
are counted against a room's own models' budgets. Boot stays within noise.
Each slice's check is slice 5's: deckshots at 390x844 at graphics low for
the counts and high for the looks, main beside the branch, on that
slice's rooms; deckboot and `run.sh --changed`; an HTML report.

| # | slice | rooms it shows in | calls | triangles |
|---|---|---|---|---|
| 1 | ceiling glare | every generated room | +0 | +0 |
| 2 | crates | cargo, storage | +0 | +0 |
| 3 | emitters | transporter, mess, shuttlebay, cargo | +0 to +1 a room | +0 to +200 |
| 4 | holo orbs | labs (deck 8's and the wings') | +0 | +240 a lab |
| 5 | bare walls | quarters, observation, gym, conference, school | +1 a room | +100 a room |
| 6 | pond | arboretum | +0 | +0 |
| 7 | carpets and mats | ready room, lounge, Ten Forward, mess, gym | +0 | +0 |
| 8 | turbolift | every car | +0 | +0 |

1. **Ceiling glare** (`shell()`): the light spots from `h - 0.7` to about
   `h - 1.4`, with the intensity kept so the floor gets what it does now.
   The ceiling then gets about a third of the light it gets today. Then
   `MX.lightPanel`'s emissive down to where the panel reads as a lit
   diffuser, not a hole: 1.1 to about 0.8. Looks: mess, quarters, storage,
   cargo, shuttlebay, deck 12 sickbay. If the glare is the high
   composer's bloom on the panel rather than the light, the panel's
   emissive is the lever. **Done, 0.291.4** (section 5).
2. **Crates**: find why `MX.crate` renders near-black on the instanced
   boxes (the map's colour space, uvs, an instance colour of 0 in
   storage, which sets none), and mend it. Looks: cargo, storage.
   **Done, 0.291.5** (section 5): the uvs.
3. **Emitters**: one shared canvas texture of concentric rings, a frosted
   centre and a bright rim, as the map of a glow material for the
   transporter's twelve discs and the cargo bay's pad. Give the
   transporter platform's top the console grey, not `M.trim`'s wood
   tone. The mess's replicator faces get a lit-niche texture (a light
   gradient, a shelf line, an LCARS strip). The shuttle's windows get a
   dark glass gradient. One material where the four share it: +1 call in
   each of those rooms, +0 elsewhere. Looks: transporter, mess,
   shuttlebay, cargo.
   **Done, 0.291.6** (section 5).
4. **Holo orbs**: `IcosahedronGeometry(0.28, 1)` to `(0.28, 3)` (80 to
   320 triangles, three's being 20 (d+1)^2, not 20 x 4^d as first
   written here; the shader is the same). The table's disc gets a
   radial gradient with rings (a canvas map on its glow material) instead
   of flat `glowBlue`. Looks: Stellar sciences, the wing lab.
   **Done, 0.291.7** (section 5).
5. **Bare walls**: each long blank wall of the named rooms gets one of
   the deck's existing framed pictures, or a pooled `screen()`. An inner
   observation lounge gets a starfield viewport on its far wall: a plane
   in the windows' sky material, framed. +1 call a room for the frame
   material where it is not already there. Looks: deck 7 quarters,
   observation 7-A, deck 10 gym, deck 2 conference, deck 10 school.
   **Done** (section 5).
6. **Pond**: `pondMat` gets an `envMap` of its own, a small PMREM of a
   night-sky gradient (deep blue to black, a few stars), so the water
   mirrors the glass roof's sky, not a studio. One PMREM at boot (~5 ms).
   Looks: the arboretum's four.
   **Done, 0.297.1** (section 5).
7. **Carpets and mats**: the four dark carpets' colours lifted about 15%
   in value with their hue kept (`carpetTF`, `carpetLounge`,
   `carpetReady`, `MX.carpets`). `MX.mat` desaturated to a gym-mat navy
   with a lighter piping edge (a second thin `rbox` merged in the same
   material is +0 calls). Looks: ready room, lounge, Ten Forward, mess,
   gym.
   **Done, 0.298.1** (section 5).
8. **Turbolift**: the car's light from `LH - 0.5` to `LH - 0.9`, a little
   dimmer, after a reshoot from inside to confirm the cause. Looks: the
   car's three. **Reshot in 0.291.4** (section 5): the cause is not the
   light. **Done** (section 5): the hull's drum round the bridge ran
   through the bridge's two cars; it is open there now.

Slices 1, 2, 6 and 8 are fixes of a line or two each. Slices 3, 4, 5 and
7 are an hour's evening each at most. None needs a model rebuild
(`build.sh`) or credits.

## 5. As built

- **Slice 1, the ceiling glare (0.291.4).** The blob was the panel, not
  the ceiling. A first pass (the light spots 1.2 m under the ceiling,
  `LIGHT_DROP`, the intensity scaled by the decay, `LIGHT_KEEP`, so the
  floor keeps its light; `lightPanel` emissive to 0.85) only shrank it.
  At graphics low the panels were already crisp, so the blob was the high
  composer's bloom (threshold 1.0). Each panel's white body (0xfff6e8)
  was lit by the pooled light under it, on top of its 1.1 emissive: ~3x
  the threshold. Now `MX.lightPanel` and `MX.coolPanel` are a dark body
  (0x2a2826, 0x262a2e) under emissive 1.05 and 1.1, just over the
  threshold: a lit fixture with a thin halo, in every generated room and
  in the labs' and sickbays' cool panels. The spots stay at 1.2 m down,
  which dims the halo on the ceiling round each panel. Measured
  (deckshots, 390x844, main 0.291.3 against this): calls and triangles
  identical in all 28 room looks at graphics low (mess, quarters,
  storage, cargo, shuttlebay, deck 12's sickbay and corridor). Boot 38.8 s
  main, 38.4 s this. deckboot and `run.sh --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-1-the-ceiling-glare-83cb0807.html>.
- **Slice 2, the crates (0.291.5).** The uvs. `MX.crate` had
  `userData.tile = 1.2`, so `autoUV` (run on every mesh a room builds)
  rewrote each unit box's uvs in metres over the tile: -0.42..0.42 on
  every face. `crateTex` is not a repeating texture, so it clamps, and
  every uv under 0 took its edge pixel, the dark rim (#2a2622): three
  quarters of each face black, the 0..0.42 corner a scrap of label. Not
  the colour space (`canvasTex` sets sRGB) nor the instance colours
  (storage sets none, which is white). The tile is gone: the boxes keep
  BoxGeometry's 0-1 uvs, one crate face a side, stretched with a box's
  scale (storage's are 0.6 x 0.2-0.6 x 0.3-0.6, which reads as a crate
  of another size). Mended, the label's "STARFLEET" ran over the right
  rim in the fallback face; both lines now have a `fillText` maxWidth.
  Measured (deckshots, 390x844 at 2x, main 0.291.4 against this, deck 7's
  storage and deck 18's cargo bay, eight looks each): calls and
  triangles identical at low (storage 198/75/47/446 calls, cargo
  162/70/61/455) and at high (the composer's 1 and 2). Boot within noise
  (37.5 s main, 36.8 and 58.4 s this on a busy box at low). The middle
  look of cargo's first quarter stands inside a crate stack (deckshots'
  centroid, not the room). deckboot and `run.sh --changed` pass. The
  report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-2-the-crates-6d36fa5e.html>.
- **Slice 3, the emitters (0.291.6).** Three canvas maps on unshaded
  materials (`glowMap`: a `glow()` with a map), each shared in `MX`:
  `emitterTex`, a frosted radial centre, three rings and a pale rim, for
  the transporter's six pads and six emitters and the cargo bay's pad
  (`MX.emitter`, 0xb0d0ff x1.5: the centre and the rim are over the
  bloom's threshold, the gaps under it, so only they bloom at high);
  `nicheTex`, the replicators' lit niche, light from the top falling down
  the back, dark sides, a shelf and an LCARS strip over the opening
  (`MX.niche`, x1.15); `glassTex`, the shuttles' windows, dark glass with
  sky at the top and a diagonal sheen (`MX.glass`). The transporter's
  platform top and its emitter overhead are `M.grey`, not `M.trim`. The
  consoles' near-black (`M.console`) was tried first and read as a hole
  in the floor. A first ring texture of five rings read as a vinyl
  record, so it now has three, with softer gaps. The mess made a new
  `glow()` for every replicator and the shuttle one for each window, all
  disposed with the room. Now one material each. Not taken, from the
  plan: a mesh for the metal rim (it is in the texture: +0 calls).
  Measured (deckshots, 390x844 at 2x, main 0.291.5 against this; deck 7's
  transporter and mess, deck 4's shuttlebay, deck 18's cargo bay, four
  looks each): no mesh added. The transporter's looks are identical
  (185/57/67/494 calls). The rest move by a call or a person's triangles
  between runs: the mess's look 1 was +5 calls in the first run and equal
  in the second, with the same code. That is the generated crew walking,
  not the slice. None of the twelve quarter-looks sees the cargo pad, which
  sits behind the crate stacks; it is the transporter's material. Boot
  36.1 s both. deckboot and `run.sh --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-3-the-emitters-9323e01c.html>.
- **Slice 4, the holo orbs (0.291.7).** The orb is `IcosahedronGeometry
  (0.28, 3)`, 320 triangles (the plan's 1,280 was a wrong formula). At
  the table's side it is now a smooth glass bubble, not a cut stone, under
  the same fresnel and scan lines. The disc under it is `MX.holoDisc`, a
  `glowMap` of `holoDiscTex`: a radial light from the middle (over the
  bloom's threshold at the centre only), six fine rings, 72 tick marks
  round a pale rim, and an amber and a lilac arc. Shared, so +0 calls.
  `ROOM_T.lab` builds both Stellar sciences and every generated lab, so
  the one change covers them all. Measured (deckshots, 390x844 at 2x,
  main 0.291.6 against this; Stellar sciences and the wing lab, four
  looks each, and `--view prop:holo_table,1.8` at each of deck 8's three
  tables): calls equal within a walking crew member's one; triangles
  +170 to +240 where an orb is in view, -36 to -120 elsewhere, the crew.
  At high the composer's 1 and 2. Boot 44.2 s main, 44.3 s this. deckboot
  and `run.sh --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-4-the-holo-orbs-bad5b744.html>.
- **Stopped after slice 4** on the captain's word (2026-10-22, through
  Number One): slices 5-7 not built, 8 still waiting for its riding look.
- **Resumed the same day** on the captain's word, in the order 6, 7, 5,
  8. Slice 5 adds textures a room, so it waits for La Forge's fix for the
  deck losing its tab on the captain's iPhone at graphics low (0.295.5:
  dropped rooms kept alive by `placeByName`), and each slice from here
  runs his `test/deckmem.py --check` at low and gives its numbers.
- **Slice 6, the pond (0.297.1).** `pondSky()`: a 512x256 equirect canvas,
  `EquirectangularReflectionMapping`, through the scene's `pmrem` once
  when `pondMat()` first makes the material (deck 8's boot), the canvas
  disposed at once, the cube kept on the material, which `keepMat` never
  lets go. So it is one small render target for the life of the page,
  and nothing a walk can grow. The sky: a first cut at a true night
  (zenith #14284a down to near black) read as a hole in the lawn, because
  the mirror is seen at a glancing angle through the water's own dark map.
  It is now #3a5a8a overhead to #16284a at the horizon, with a warm band
  just under it for the room's lamps, and 320 stars of 2-3 px in the
  upper half. The ripples in the shader break the stars up, which reads as
  water. The lamps' own highlights (the point lights) stay as they were.
  Measured (deckshots, 390x844 at 2x, main 0.296.2 against this; the
  arboretum's four looks and two at the pond, `--view
  pondN,13.4,6.4,0,-0.42` and `pondW,9.4,2.6,-1.5708,-0.42`): calls and
  triangles identical, but for one look's one call that moves with the
  arboretum's walking crew. Boot within noise. La Forge's `deckmem.py --check` at
  low (393x852 at 3x, three loops of deck 8's wings and decks 12 and 3)
  passes: boot 192 geometries, 132 textures, 353.3 MB of GPU memory, 9,470
  live three.js objects; each loop's end 267 geometries, 389.0 MB of
  textures, 9,748 live objects, the same all three times; peak 585.4 MB
  GPU; the texture count 170, 171, 172 (+0.3 MB of buffers a loop, under
  its bounds); a lost context restored. The pond's sky is in the boot's
  numbers, made once. deckboot and
  `run.sh --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-6-the-pond-8f438b04.html>.
- **Slice 7, carpets and mats (0.298.1).** Each carpet is x1.15 in every
  channel, which lifts the value 15% and keeps the hue and saturation:
  `carpetTF` 0x464365, `carpetReady` 0x555e6e, `carpetLounge` 0x55455e,
  and `MX.carpets`' five. `MX.mat` is now white under `vertexColors`, and
  `gymMat` places two shared, tinted copies of rounded boxes: the pad
  (2.2 x 0.06 x 3.0, 0x3a4f70, a greyer navy than 0x2a4a7a) on a piping
  (2.3 x 0.04 x 3.1, 0x8a9ab4), so a 5 cm pale rim shows round each mat.
  The colours go in linear, as a vertex colour is read, and
  `MX.mat.userData.attrs` takes `color` into the cell's merge. Both are
  one material, and one draw. A rounded box is 300 triangles, not the
  plan's ~200. Measured (deckshots, 390x844 at 2x, main 0.297.1 against
  this; the ready room, the lounge, Ten Forward, `--gen 7:mess` and
  `--gen 10:gym`, four looks each): calls equal everywhere but Ten
  Forward's 0 and 1, -2 with the crew walking; triangles equal but for
  the gym, +2,400 (eight mats). `deckmem.py --check` at low passes on
  both. Main (0.298.0): boot 192 geometries, 132 textures, 353.4 MB; each loop's
  end 267 geometries, 9,748 live objects; textures 170, 171, 172. This
  slice: 268 geometries (the mats' two, made at the first gym, kept), the
  same 9,748, textures 171, 172, 173. So the texture creep is main's, not
  the slices'. deckboot and `run.sh --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-7-carpets-and-mats-3de94910.html>.
- **Slice 5, the bare walls (2026-10-22).** `wallFrame(mat, fm, w, h, x, y,
  z, rotY)` hangs a plane in a shared material inside four plain box
  strips (50 triangles, where a rounded frame is 300), the strips in
  `M.rail` (a picture) or `M.console` (a display, a viewport), which
  every wall's rail and kick plate already draw. The picture is
  `paintMat()`, `painting()`'s material split out, made once; a display
  is `panelMat(seed)`, the desks' pool; the viewport is `viewMat`,
  cartoMat's depth-writing form of the windows' sky with skyMat's own
  uniforms (skyMat draws at the far plane, behind a solid wall), kept
  DoubleSide as cartoMat is, since the side is in three's program key.
  Quarters: a hull cabin's picture over the window chairs, an inner
  one's viewport on its far wall, and a plaque by every door; an inner
  observation lounge's big viewport across from its sofas, a hull one's
  picture; the gym's display facing the mirror; the conference room's
  picture and small display at the table; the classroom's display.
  Measured (deckshots, 390x844 at 2x, low, main 0.298.1 against this,
  the plan's five rooms, four looks each): +0 to +2 calls a look, the
  two +2s (quarters 0, conference 3) likely the merged meshes' bounds
  and the walking crew; +48 to +196 triangles. `deckmem.py --check` at
  low passes on both, main 0.299.3 and this: each loop's end the same
  267 geometries, 169 textures and 484.6 MB, all three times; this slice
  holds a flat +1 program (60, from the arrival on deck 12) and +1 live
  object (9,749), neither growing: likely `viewMat` compiled under a key
  of its own and a viewport mesh (it merges with nothing) in a room
  still built at the concourse. deckboot and `run.sh --changed` pass.
  The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-5-the-bare-walls-da5deab9.html>.
- **Slice 8, the turbolift: the hull's drum open at the bridge's cars.**
  A look from each car's middle facing the door, as a rider faces, in
  all seven cars on main: only the bridge's two show the white field;
  the concourse's four and deck 12's look out on their corridors. The
  cause is outside the car, not its light: deck 8's outer hull round the
  bridge is a drum (`deck8Shell`, a cone from `BR + 0.35` at its top to
  `BR + 1.2` at `Y0`, open only at the corridor), and the bridge's cars
  stand outside the bridge's wall, x ±9.94 to ±12.54, so the drum ran
  through both at x ≈ ±10.48, half a metre before the rider's face. Rays
  from the eye hit its hull material first (0.96 m), its outside lit by
  the hull's sun. The fix: the drum is three arcs round the bridge, open
  over each car's width (`lg = asin(1.35 / (BR + 0.35))`) from the floor
  to the deck's height, with two open-ended pieces in each gap below the
  floor and above the car; the cone's radius by height (`dR`) makes the
  pieces meet. 68 segments round the arcs and 2 a gap piece: 288
  triangles, the whole drum's before, in the same merged hull mesh.
  Looks, main beside this at low and high: in both cars, from the middle
  and 0.9 m back, the bridge through the door where main had the white
  field. From Ten Forward's forward windows (deck 8's only ones facing
  the bridge's sides; the shell is hidden off deck 8 and on the map) the
  four views match main: the car's own walls close the gap. Counts
  (deckshots, low, the bridge and four views at and facing the cars):
  calls and triangles equal in five of seven; the bridge's first view
  -1 call and -72 triangles and the view facing the port car +1 and +72,
  likely the walking crew (the drum is in one merged mesh, its count
  unchanged).
  `deckmem.py --check` at low passes: each loop's end 267 geometries, 169
  textures, 484.6 MB, live3d 9,749, as slice 5's. deckboot and `run.sh
  --changed` pass. The report:
  <https://<server>/media/reports/2026/10/deck-polish-slice-8-the-turbolift-1b86ddf7.html>.
