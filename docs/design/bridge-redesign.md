# Bridge redesign: concept art, the target, and the slices to it

Number One's order for the captain, 2026-10-20: redesign the main bridge
of the 3D deck (`lcars-ui/deck.html`), concept art first, built by a
modelling engineer afterwards (Okafor, who built deck 8's models). This
doc is the design: what the bridge looks like now, three directions
painted with Higgsfield, the one recommended, what changes object by
object, which generated images can be textures, and the slices, ranked,
each one engineer's order. Nothing in `deck.html` was touched for it.

Read with `deck-models.md` (the rules every slice keeps), `deck-style.md`
(the palette, part 1; the bridge's props, part 2) and `deck-pipeline.md`
(Blender, `bridge.py`, the budgets).

**The report** (the shots and the concepts side by side, the prompts):
<https://<server>/media/reports/2026/10/main-bridge-redesign-concept-art-zimmerman-fd7dd8ab.html>.
The full-resolution images (the nine concepts at 2k, the three tiles,
the current shots) and `prompts.py` are one zip in the reports store:
<https://<server>/media/reports/2026/10/main-bridge-concepts-full-resolution-images-and-56aa7198.zip>.
No image is in the tree.

## 1. The bridge as it is (deb 0.279.4)

Shot with `lcars-ui/test/deckshots.py` (niced), `--only none` and four
`--view` looks at 390x844, 3x, graphics low, and two at 1280x720,
graphics high (`--gfx high`: GTAO, bloom, the grade). World coordinates:
the bridge is a circle of radius 10 centred at (0, -38), the corridor
doors at z -28, the turbolifts at x ±9.94.

| view | `--view` | draw calls | triangles |
|---|---|---|---|
| A, from the port turbolift | `lift,-8.6,-38,-1.0` | 64 | 512 k |
| from the corridor doors | `door,0,-29,0` | 80 | 703 k |
| B, behind the captain's chair | `chairs,0,-35.4,0,-0.06` | 59 | 490 k |
| C, from the viewscreen, aft | `screenback,0,-44.5,3.14159,-0.1` | 208 | 963 k |
| desktop high, from the aft rail | `wide,0,-30.5,0,-0.1` | - | - |
| desktop high, from the viewscreen | `screenback,0,-45,3.14159,-0.08` | - | - |

Boot to the ship built 39.0 s, the models landed 73.9 s (SwiftShader,
the box at load ~1). On graphics high deckshots reads 1 call and 2
triangles: the composer's last pass, not the scene - the high run is
for its pictures only. The bridge's models (`bridge.glb`, six props) are
33.1 k triangles of the room's 40 k; `bridge.glb` and its three webp are
276 kB.

**What gives it away, object by object** (from the shots; the concepts
make each one plain):

- **The floor.** Two carpets: a dark brown round the room and a
  terracotta disc in the well (`M.carpetWell`, `#86624c`). The terracotta
  is the warmest, largest surface in every view and nothing in the set is
  that colour; the series' bridge is one cool grey-mauve carpet
  throughout. From the turbolift (A) the floor is two thirds of the
  phone's screen.
- **The command chairs from behind.** The view from the doors, the
  rail and the chairs (B) sees their backs: a black shell with a brushed
  plate, red only at the edges. They read as black office chairs. In the
  concepts the shell is burgundy leather too, and the back taller.
- **Conn and ops from the viewscreen** (C). Their far faces are
  1.5 m by 0.8 m of flat black, the largest dark shapes on the phone.
  The concepts' consoles are lower and narrower at the foot: the top
  overhangs a slimmer pedestal and a trim line breaks the face.
- **The skylight.** It dominates every look up (B and C on a phone are
  a third ceiling): a large, evenly white disc behind heavy black
  mullions. In the concepts the mullions are a warm grey and the panels
  graded, brighter at the centre, so it reads as a lit coffer, not a
  graphic.
- **The walls.** A plain cylinder of putty panels with vertical seams;
  the wall displays hang on it like television sets. The concepts have
  sculpted bulkheads that lean in either side of the viewscreen (the
  set's big curved fins), a dark wainscot with a reveal, and displays
  set into the wall in a bezel.
- **The standing stations.** Six separate black boxes. In the concepts
  the side stations either side of the viewscreen (B) are one long
  counter with a wood cap and inset LCARS, of a piece with the rail.
- **Lighting.** Even everywhere: walls, floor and ceiling at the same
  brightness. The concepts grade it - bright overhead, the walls falling
  off toward the floor, light pooling at the consoles. On desktop high
  the room is already closer (GTAO, bloom); on the phone (low, no
  composer) it is flattest.
- **What is right already**: the room's plan, the viewscreen (a window
  onto the 3D sky, the black hole through it, its amber edge lights),
  the tactical rail's shape and wood, the chairs' form, the LCARS
  displays. Every concept kept them; none of them needs replacing.

## 2. The concepts

**How.** Higgsfield's CLI (`higgsfield`, signed in as the captain; the
plugin's skills were not in this session). Each concept is Seedream 5.0
Flash (`seedream_5_0_flash`, 2k, 16:9, 0.5 credits) with the current
shot of that angle as its image reference, so all three directions keep
the deck's own layout and camera and compare like with like. The UI's
pills and header were cropped off the references first. Three angles
(A turbolift, B chairs, C viewscreen aft; references `lift.jpg`,
`chairs.jpg` and the desktop `screenback`) times three directions: nine
images, every one used, none retried. Three texture tiles on Z Image
(`z_image`, 1:1, 0.15 credits each).

**Credits:** 5.69 before, 0.74 after: 4.95 spent (9 x 0.5 + 3 x 0.15).
The free plan runs one job at a time (seven started in parallel were
refused, at no cost, and run in turn).

**The prompts.** Each is the common lead, the angle's line and the
direction's line, in that order.

Common lead:

> Keep the camera position, lens, room layout and the placement of every
> object from the reference image (a game render of the room); redraw it
> as concept art in the style below. Empty room, no people, no readable
> text, no logos.

Angles:

- **A** (`lift.jpg`): Camera at eye height in the port turbolift doorway
  of a circular starship bridge, looking diagonally across it: the huge
  curved viewscreen on the left, the three command chairs on a sunken
  circular carpet in the centre, the two forward helm consoles, wall
  displays on the far wall. Wide angle.
- **B** (`chairs.jpg`): Camera at standing eye height just behind the
  captain's chair, looking forward over the three command chairs and the
  two helm consoles to the wide viewscreen filling the forward wall,
  showing a black hole with a glowing orange accretion disk. The domed
  ceiling with radial ribs above.
- **C** (`desk-screenback.jpg`): Camera in front of the viewscreen
  looking aft: the two helm consoles in the foreground seen from behind,
  the three command chairs in the middle, a curved horseshoe tactical
  rail behind them in two arcs with an aisle to the corridor doors in the
  back wall, standing consoles and wall displays round the circular wall,
  the round domed ceiling skylight above.

Directions:

1. **TNG-faithful.** Faithful to the 1990s Star Trek: The Next
   Generation Galaxy-class bridge set: putty-beige curved wall panels
   over a dark brown wainscot, burgundy leather command chairs with piped
   seams and padded arms ending in small slanted armrest consoles, a
   curved lacquered dark-wood tactical rail on dark panels, grey-black
   consoles with glowing amber, peach and lilac LCARS touch panels set
   flush in sloped tops, a light domed ceiling with radial ribs and a
   luminous centre, a cool grey-brown carpet, soft even studio lighting,
   photographic, 35mm film still.
2. **Darker, modern.** A darker, modern reading of the same bridge, as a
   2020s prestige TV series would build it: charcoal and graphite matte
   wall panels with thin warm light seams, a walnut tactical rail, black
   leather command chairs with oxblood inserts on brushed steel
   pedestals, slim consoles with glass LCARS displays in amber and blue,
   concealed linear lights along the ceiling ribs, low-key cinematic
   lighting with pools of light on the floor, slate-blue carpet,
   photorealistic, anamorphic lens.
3. **Night watch** (mine). The same Galaxy-class bridge at night watch:
   putty walls, burgundy leather chairs and the dark wood rail as on the
   TNG set, but the room lights dimmed low, amber light strips along the
   floor and the wainscot, the LCARS console displays and the viewscreen
   the main light sources, the ceiling dome a faint warm glow, deep soft
   shadows, the displays reflected in the lacquered wood and the leather,
   quiet and calm, photorealistic film still.

Textures (Z Image, each "Seamless tileable texture, orthographic, flat
even lighting: ..."): a cool grey-brown low-pile carpet with a loop
weave and a darker fleck; one putty-beige padded wall panel 1.3 m wide
with a dark seam and a reveal at two thirds of its height; the matte
grey-black fascia of a console with a brushed trim line and two amber
indicator slots. The exact texts are in the report and the zip.

**What came back.** All nine kept the layout. Direction 1 is the set,
as the deck already means it to be. Direction 2 is a different ship:
graphite walls, a slate-blue carpet, black chairs - handsome, but it
would make the corridor, Ten Forward and the ready room (all putty and
warm) look like another vessel's, and it trades the room's best-known
colours (putty, burgundy, wood) for a generic dark interior. Direction 3
keeps the set and changes only light: the walls fall into shadow, the
displays and amber strips carry the room. Two of the night-watch frames
(B, C) kept the deck's crosshair from the reference, a small "+" - read
past it.

## 3. Recommendation

**Direction 1, TNG-faithful, as the target; direction 3 later, as a
switch (a night watch the room dims to), not a rebuild.** Why:

- The deck's other rooms are TNG already; the bridge is the room it is
  about. Direction 1 finishes it, 2 would start a new ship.
- Almost all of direction 1's gain is **palette, light and silhouette**,
  which cost no draw calls and few triangles: the carpet, the chairs'
  shells, the skylight's mullions, the light's falloff. The geometry it
  asks for (the viewscreen's bulkheads, the stations' counter, the
  displays' bezels, the consoles' feet) fits the room's 40 k, with 6.9 k
  left today, and the bridge atlas.
- Direction 3 is a lighting state: the bridge's lights, the glow
  materials' intensity, the skylight's colour. Per `deck-models.md`
  that is "a uniform or a handful of" values per frame, not a rebuild,
  so it can come later as its own order with its voice order (`DVCMDS`).

## 4. What changes, object by object (to direction 1)

| object | now | direction 1 | where |
|---|---|---|---|
| floor | brown `M.carpetBridge` `#5a4a44` round a terracotta well `M.carpetWell` `#86624c` | one cool grey-mauve family: the well a shade lighter than the floor, both cool (start at `#6a5e60` the well, `#4e4548` the floor; the concept's lit carpet samples `#645556`); the wood rim stays | `M.carpetWell`, `M.carpetBridge` colours only |
| command chairs | black shell, red cushions | burgundy leather on the shell's outside too; the back ~8 cm taller to the headrest; the brushed plate kept | `bridge.py`: `back_shell`'s material `console` to `bridge_leather` (a darker leather shade for the shell if it reads flat), `Z1` 1.27 to ~1.35; rebake |
| conn and ops | flat black far face, 1.5 x 0.8 m | the pedestal narrower than the top (the top overhangs ~8 cm on the far side as on the near), a brushed trim line across the far face at a third of its height | `bridge.py` `conn_console`: the `body` prism's far face set in, a `trim` box on it |
| viewscreen | the frame, amber edge lights, a grey step | unchanged in what it shows; two sculpted bulkheads either side, leaning in, from the floor to the cornice (the set's fins) | new prop `screen_fin` in `bridge.py` (≤ 800 triangles each, x2), or `rgeo`/lathe in code in `M.wall` |
| standing stations | six boxes | the two pairs flanking the viewscreen (at ±2.2) one counter each with a wood cap (`rail_wood`) and the LCARS inset; the four at ±0.8, ±1.15 kept as stations but with the wood cap | `bridge.py` `station()`: a cap in `rail_wood`; a `station_long` for the forward pair |
| wall displays | flat panels on the wall | set into the wall: a bezel 4 cm deep in `M.trim` round each, the panel back 2 cm | `bpanel()` in deck.html: a frame (four `rbox`es, or one model `display_bezel` in bridge.glb) |
| walls | putty cylinder, vertical seams | a horizontal reveal at two thirds of the panel's height (the set's), in the texture | `T.panel` (or the bridge's own wall tile): a reveal line in the height map; texture-only |
| ceiling and skylight | white disc, black mullions | mullions warm grey (`#7a7268`), the panels graded brighter to the centre, the disc's level down (`skyMat.color` 0.55 to ~0.45) | `skylightTex()` and `skyMat`; texture-only |
| lighting | even | brighter overhead, the walls falling off toward the floor; the cove and the cornice glow kept | the bridge's `light()` intensities and heights, the wall's lower band (`bwLowMat`) a shade darker; no new lights |
| palette and materials | `deck-style.md` part 1 | kept: leather `#5e1f1c`, rail wood `#5a3a28`, putty walls; the carpet is the one change | no new materials |

## 5. Generated images as textures

Judged one by one; the rule is the deck's, that a texture is generated
seamless with its normal and roughness maps (`T.*`), so an image must
beat that to earn its place:

- **The viewscreen's image: no.** It is a window onto the 3D sky (the
  black hole in `skyMat`), drawn with depth and parallax as you walk; a
  picture there would be a step back.
- **The consoles' displays: no.** `lcarsPanelTex` draws them from the
  journal (today, tasks, engineering): live data, which a generated image
  cannot be. The concepts' LCARS colours (amber, peach, lilac on black)
  are already the panels'.
- **The carpet: not directly.** The tile came back with tile seams and a
  scratch, and it is not seamless; `T.carpet` is, with relief. Use the
  concept for the colour only (section 4).
- **The wall panel: as a reference.** Three panels with reveals, no
  normal or roughness map, and `M.wall` is shared by every room of deck
  8: a photo texture there would change them all and add bytes to the
  boot. The reveal goes in the generated texture.
- **The console fascia: the one near direct use.** As the base colour of
  the station's and the consoles' faces in the bridge atlas: the bake
  (`common.py`'s `finish_room`) would need an image texture node beside
  the palette's procedurals. At the phone's size a station 1.6 m wide
  seen from 2 m is ~600 device pixels, so a **512² crop** of it is enough;
  the atlas stays 1024². Weigh it against a procedural fascia in
  `PALETTE` (a trim line and two slots are a few lines of shader).
- **Not generated, worth one: the skylight.** A top-down image of the
  lit coffer (warm grey mullions, graded panels) at **1024²**, in place
  of `skylightTex()`'s canvas, +0 calls, +~100 kB. It is the one surface
  that is a picture already (a canvas drawing) and fills a third of the
  phone's screen looking up. One Z Image (0.15 credits) or a Seedream
  (0.5). (The credit count once here was stale: the captain's plan has
  plenty; one Seedream was made, slice 6.)

## 6. Budgets each slice keeps

From `deck-models.md` and `deck-pipeline.md`: the bridge's models at most
40 k triangles in all (33.1 k now: **6.9 k left**), hero props ≤ 6 k,
furniture ≤ 1.5 k; the bridge atlas is its one draw call (a new prop in
`bridge.glb` is +0 calls); a new material is a new draw call, so none;
the room's bytes ≤ ~600 kB at 1024² (276 kB now); boot unchanged within
noise; graphics low no heavier. Every slice measures with deckshots
before and after, niced, from the six looks of section 1 plus `--only
"Main bridge"` (its four quarters), and puts the numbers in its commit.

## 7. The slices, ranked (for Okafor)

Ranked by what the phone sees per cost. Each is one engineer's order,
shippable alone; the first a minor, each after a patch.

1. **Palette and light** (deck.html only). The two carpets to the cool
   family, the skylight's mullions and level, the lights' falloff (the
   wall's lower band darker, the overhead lights' heights). Before and
   after: the six looks' pictures side by side; calls and triangles
   **+0**; frame p50 within noise. The biggest change on the phone for
   the least work: the carpet is two thirds of view A.
   **Done in 0.281.0**: the carpets `#4e4548`/`#6a5e60`, `skylightTex(true)`
   (the panels' grade a little stronger than asked, `#fffaf0` to `#a08058`,
   so the centre reads as the brightest at 0.45), the two lights at 4.15 m
   with reach 14.5 and 11.5, the wainscot x0.82; calls and triangles +0
   in all ten looks.
2. **The command chairs' shells** (`bridge.py`, rebake). Burgundy shell,
   the taller back; the conn chairs' shells the same. Measure: view B and
   `--view prop:captain_chair,1.6,180` (from behind); captain_chair
   ≤ 5.3 k (5044 now), calls +0, the room's models ≤ 33.5 k.
   **Done in 0.281.2**: `bridge_shell` `#4a1715` (a darker leather, a
   palette entry baked into the atlas) on the captain's `back_shell` and
   conn_chair's shell; `Z1` 1.35, the upper cushion 0.32 at 1.02 and the
   headrest at 1.27; captain_chair 5044 (the height moves vertices, adds
   none), calls +0, 276 kB (+0.5).
3. **Conn and ops' feet** (`bridge.py`). The set-in pedestal and the
   trim line. Measure: view C, `prop:conn_console,1.6,180`; ≤ +300
   triangles each, calls +0.
   **Done in 0.282.1**: the body's far face from y 0.17 at the foot to
   0.27 under the top, the pedestal 0.50 deep at its top (cy -0.06, was
   0.58 at -0.02) flaring to 0.64, the band 0.52; a `trimline` (1.24 x
   0.025, `trim`) leaning with the face at a third of its height;
   conn_console 1512 (+44), calls +0, 279 kB.
4. **The viewscreen's bulkheads** (`bridge.py` `screen_fin`, placed with
   `model()` with no stand-in, so its contact patch comes with the
   placement). Measure: views B and A; ≤ 800 triangles each, +1.6 k in
   all; calls +0 (+1 at most for the patches, per the pipeline's budget).
   Check the `block()` round the viewscreen still keeps people off them.
   **Done in 0.284.2**: `screen_fin`, 360 triangles (a putty loft raked
   from 0.74 m deep at the foot to 0.29 under the ceiling, 0.82 to 0.52
   wide, a wainscot foot, the band, a black slot in a trim frame on the
   face), at 2.545 rad either side where the last ribs were (dropped); the
   viewscreen's block stops at x 5.4 and a fin's foot reaches 5.8, so each
   has its own block; room models 36.7 k; views A and B +1 call (the
   patches), +100 triangles.
5. **Stations and wall displays** (`bridge.py` `station` with a wood cap
   and `station_long` for the pair flanking the viewscreen; a bezel for
   `bpanel`). Measure: views A and B; ≤ +2.5 k in all, calls +0. The
   room's models then ~37.5 k of 40 k: the last geometry slice.
   **Done in 0.284.3**: `station()` capped in `rail_wood` (a fuller
   bullnose on the near edge, the far edge, the cheeks), 1036 triangles
   (+80) x4; `station_long` (the same, `L` 2.6) x2 at +-2.2, its glow strip
   2.5 and five blocks; `display_bezel` (a 7 cm `trim` frame 4 cm deep, 2 cm
   proud of the display) x6 round `bpanel()`'s, 176 triangles, as geometry
   (it fitted: no atlas paint). Room models 38.3 k of 40 k; views A and B
   calls +0, +1,536 triangles; 419.8 kB.
6. **The wall's reveal and the skylight image** (texture-only: the reveal
   in the bridge's wall tile; optionally the generated skylight of
   section 5, which needs the captain's 0.15-0.5 credits). Measure: the
   six looks; +0 calls, +0 triangles, bytes ≤ +100 kB.
   **Done in 0.284.4**: the reveal in `T.panelBridge` (`panelSet(true)`,
   the bridge wall's own tile; `M.wall` untouched), at 3.02 m, 6 cm tall
   (3 cm did not read across the room), its rows' tone x0.6 and a lit lip
   under it. The skylight: one Seedream 5.0 Flash image (0.5 credits,
   Higgsfield on the captain's plan), 2048² scaled to a 1024² webp of
   67 kB, `deck/bridge_skylight.webp`, loaded over the canvas drawing,
   which stays the fallback; `skyMat` at 0.45 as 0.281.0 set it. It beat
   the drawing: the panels read as frosted glass lit from behind, the
   mullions as metal. The six looks: calls and triangles +0, bytes +67 kB.

**Night watch** (direction 3, 0.297.0, Number One's order of
2026-10-22): built as a lighting state, as section 3 meant. `NIGHT` in
deck.html holds the state (`lcars.deck.night` in localStorage, off by
default) and a setter per part, registered as the bridge is built;
`nightWatch(on)` runs them. At night:

| part | day | night | how |
|---|---|---|---|
| the two pooled lights | 9 and 5, `#fff0dd` | x0.17, `#ffd2a0` | the light spots' values |
| the key spot over the well | 36 | 8 | its intensity (the shadow map is not redrawn) |
| the fill on the bridge | `ROOM_FILL` or 0.55/0.35 | x0.22 / x0.25 | scaled in the tick for the zone "Main bridge" |
| the skylight's panel | 0.45 | 0.12 | the bridge's own `skyMat` |
| wall, cornice / wainscot | as built | x0.7 / x0.55 | the bridge's own clones |
| the dome's light ring | lit | x0.18 | a per-vertex mask in the shared batch |
| displays, viewscreen, amber and warm strips | lit | lit | untouched |

The ring is `M.lightStrip`, merged by `mergeStatic` with a halo and a
lift's ring into one draw, so a bridge-only clone would be a call more.
Instead the material lists an attribute `aNight` (`userData.attrs`),
the ring's geometry carries it as 1 and the others get zeros from
`copyGeo`'s `fill`, and a shader hook (`hookShader`, key "night")
multiplies the emissive and the diffuse by `mix(1, uNight, aNight)`.
The shared glows (`M.glowAmber`, `M.glowWarm`, `M.glowDim`) stay as by
day: they are the strips that carry the room at night. Toggled by **U**,
a Night/Day pill shown on the bridge (`data-when="bridge"`), and the
orders "night watch" and "day watch" with their aliases. Measured (deckshots
390x844, graphics low, main 0.295.3 beside it): the six looks' calls
65/81/60/210/77/210 day and night, as main (main's 211 on one look is the
culling's noise), triangles identical; no texture, render target or
material added.

**By the clock** (the captain's order of 2026-10-30): the watch follows
the captain's hours by default, night from 23:00 to 07:00 in the zone of
the server's `$LCARS_TZ`, which the deck asks `GET /zone` for (and keeps
in `lcars.deck.zone` for the next boot and offline) rather than trusting
the device's clock, set to wherever the phone is; with none (the demo, an
older server, no `LCARS_TZ`) the device's own zone. `watchAt(t)` names the
watch at a time and its key (the zone's date an hour on: 23:00 to 07:00
is one night); `nightTick` runs at boot (quiet) and once a minute, and at
a change of watch puts the bridge in it, with a hint ("Night watch by the
clock...") only when standing on the bridge, where the lights change
(elsewhere it is seen on walking in). A choice by hand (U, the pill, the orders) is kept as its
watch's key in `lcars.deck.nighthand` and holds until that watch ends.
The switch, `lcars.deck.nightclock` per device (on by default), is a row
in the PADD's settings and the orders "watch by the clock" and "watch by
hand"; turned on, it lets a hand's choice go. deckboot.js stands the hour
in (23:30 night, 07:30 day, the hand held, the switch off).

## 8. Scouting: Blender and image-to-3D

**Blender runs headless on this box, and already does.** Blender 4.3.2
is installed (`/usr/local/bin/blender`, a wrapper that preloads the
system's libsqlite3 before `/usr/bin/blender`); `blender -b
--factory-startup --python-expr ...` answered 4.3.2 today, and
`scripts/deck-models/build.sh` builds every room's props with it
(Cycles on the CPU, three threads, niced; `deck-pipeline.md`). Nothing to
install. The box has no GPU (a virtual VGA, 4 cores, 7 GB): the bakes are
CPU bakes, about a minute a room, and nothing image-to-3D can run
locally (TRELLIS and Hunyuan3D want a 16-24 GB NVIDIA GPU).

**Image-to-3D services.** Two routes; no sign-ups made, nothing
installed.

*Through Higgsfield, the account the captain already has* (costs from
`higgsfield generate cost` today, nothing spent):

| model (`job_type`) | credits a job | what it takes | notes |
|---|---|---|---|
| Tripo H3.1 (`tripo_h3_1_image_to_3d`) | 9 | one image; `face_limit`, PBR, `texture_quality` | the pilot's pick: a face limit is the budget, asked for up front |
| Hunyuan3D v3 (`hunyuan3d_v3_image_to_3d`) | 11 | one image; `face_count`, `generate_type` LowPoly, PBR | licence: see below |
| Tripo P2 (`tripo_p2_image_to_3d`) | 34 | one image; `export_uv`, `delight`, `face_limit` | the higher tier |
| Meshy 7 (`meshy_v7_image_to_3d`) | 38 | one image; `model_type` lowpoly, PBR, remesh | |
| Tripo multiview, Multi-Image to 3D, SAM 3 3D Objects | not estimated by the CLI | several views / one object cut from a photo | |

Their output is a glb (textured, PBR where asked). 0.74 credits are left
on the free plan: a pilot needs a top-up or a plan.

*Directly, each with a free tier* (from what I know as of mid-2026; not
checked online today and not signed up for - the captain should read
each one's current terms before a pilot):

| service | free tier | formats | licence of free output |
|---|---|---|---|
| Meshy | monthly credits, a few image-to-3D jobs | glb, fbx, obj, usdz, stl | free-tier models CC BY 4.0 (credit needed), paid owned |
| Tripo | monthly credits, more jobs than Meshy's | glb, fbx, obj, usdz | free tier limited (public / non-commercial); paid owned |
| Rodin (Hyper3D) | trial credits | glb, fbx, obj, usdz | paid for owned use |
| Hunyuan3D (hosted: Tencent's site, a Hugging Face Space) | free, queued | glb | Tencent Hunyuan community licence, **which excludes the EU, the UK and South Korea**: the captain is in Romania, so not usable |
| TRELLIS (Microsoft; a Hugging Face Space) | free, queued | glb | MIT: the cleanest licence of the five |

**The pilot: the captain's chair, one object end to end.**

1. **Image.** One clean three-quarter front view of the chair alone on a
   plain ground, in direction 1's style, with `tng-B` as its reference:
   Seedream 5.0 Flash, 0.5 credits (a second from behind helps the
   multiview tools).
2. **Mesh.** Tripo H3.1 with `face_limit` 12000 and PBR (9 credits), or
   TRELLIS on its Space (free, MIT). A glb back.
3. **Decimate and bake.** The pipeline does this already: the glb in a
   folder with a `LICENSE.txt`, a case in `build.sh`'s `pack()` or
   `C.import_pack` in `bridge.py`, decimated to the hero budget (≤ 6 k,
   5044 now) and baked onto the bridge atlas (`pack.py`: one atlas
   whatever the source's materials). The chair must be rescaled to the
   stand-in's measures (seat top 0.58, arms at ±0.36, the armrest fronts
   where the status lights sit: `bridge.py`'s docstring), which an
   image-to-3D mesh will not match by itself: expect a Blender pass to fit
   it.
4. **Into the deck.** In place of `captain_chair` in `bridge.glb`, the
   same `model()` placement; measured as any prop (deckshots, view B and
   `prop:captain_chair`), against the scripted chair, side by side.

**What it needs from the captain:** about 10 Higgsfield credits (a
top-up or a plan: 0.74 left), or the go-ahead to use TRELLIS's free
Space; and a decision on the licence line `LICENSE.txt` gets for a
generated model (the pipeline refuses a folder without one): Higgsfield's
terms for its outputs, or MIT for TRELLIS. My expectation, to be proven
by the pilot: a generated chair will look richer in its texture and
worse in its silhouette than the scripted one at ≤ 6 k triangles, and
the scripted one wins on the fit to the stand-in. That is why the
slices above stay in `bridge.py`; the pilot decides whether a later
order should change that.

## 8b. The pilot: the captain's chair (2026-10-20, main 0.281.2)

Number One's order, on the captain's new plan (786 credits, at most 20
for this). Done as section 8 planned it, but not placed in the deck:
slice 2 (Okafor's burgundy shells) was being built in `bridge.py` at
the time. **The report** (both chairs from the same two angles, the
numbers, the images and prompts):
<https://<server>/media/reports/2026/10/captain-s-chair-the-image-to-3d-pilot-zimmerman-5a10b9b6.html>.
The glbs (Tripo's raw one and the fitted 6 k one), its `LICENSE.txt`,
the Blender pass (`pilot.py`) and the two images are one zip:
<https://<server>/media/reports/2026/10/captain-s-chair-pilot-the-glbs-license-blender-p-559b178b.zip>.

**What was done.**

1. Two images on Seedream 5.0 Flash (1:1, 2k, the TNG concept's angle B
   as the reference): the chair alone on a plain grey ground, three
   quarters from the front, and three quarters from behind. The first
   front image put the back's brushed plate on the *front* of the
   backrest; re-rolled once with "the front of the backrest plain
   padded leather, no plate".
2. Tripo H3.1 image-to-3D (`tripo_h3_1_image_to_3d`, `face_limit`
   12000, PBR) on the front image: 2 min 46 s, a 2.98 MB glb of 11,506
   triangles with 2048² colour, normal and ORM maps, 1.0 m tall.
3. Blender, headless (`pilot.py`): joined, turned -55° (Tripo's front
   was +X, and aligned to the image's three-quarter camera, not square;
   the importer's quaternion rotation mode has to be set to Euler before a
   turn takes), set on the floor, scaled x and y by 1.17 so the arms'
   outer faces meet the scripted chair's (±0.415, the arm pads round
   ±0.36) and z by 1.39 so the seat top is 0.58, then decimated to
   5,899 triangles. Fitted: 0.83 x 0.78 x 1.39 m, against the scripted
   chair's 0.83 x 0.80 x 1.35. Its glb with 1024² webp maps is 266 kB.
4. Rendered with the scripted chair (bridge.py's `captain_chair()`
   built in the same scene, in its palette materials before the bake)
   from the same two angles, Cycles on the CPU.

**Credits:** 786 before, 775.5 after, **10.5 spent**: three images
(1.5) and the 3D job (9). The one retry the order allowed went unused:
Tripo's multiview wants straight-on views (front, side, back) and the
two images were three-quarter ones, so it would likely have wasted the 9
credits; making straight views first would have passed the 20.

**What it found, against my expectation in section 8** (richer
texture, worse silhouette, the scripted chair winning on fit):

- **The texture is richer**, as expected: stitched cushions, leather
  sheen, a headrest that reads as one.
- **The silhouette is better, not worse.** A contoured shell, a
  free-standing headrest on a stem, a flared pedestal, thin padded arms
  with consoles at their ends: at 5.9 k triangles it is the chair in the
  concepts, and the scripted one (rounded blocks) is not. Decimation
  from 11.5 k to 5.9 k changed nothing visible.
- **The back is black.** Tripo saw only the front and invented the
  hidden side in black. That is the side the bridge shows most (view B,
  the doors, the rail) and the giveaway slice 2 just fixed. From one
  image, the side you can't see is a guess.
- **The pedestal is a smudged mirror chrome**: its own ORM (metal 1,
  low roughness, blotches). The pipeline's bake would carry that into
  the atlas, so it needs repainting or a material override.
- **The fit is the scripted chair's to keep.** The stand-in's armrest
  lights and seat (`chair(x, z, s, true)`) are where bridge.py put them;
  the generated arms are thinner and sit in another place, so the lights
  would not sit on their fronts without a second, by-hand fit (or
  `chair(..., lights = false)` and lights of its own).
- **Cost in the deck:** three chairs 17.7 k against 15.1 k, +2.6 k,
  within the room's 40 k; +0 draw calls once baked into the bridge atlas
  (`C.import_pack`, `--tris-captain_chair 6000`); ~100 kB of geometry
  through meshopt, no textures of its own.

**Should a later order bring it in? Yes, after a second pilot, not
this mesh.** The second pilot, about 10 credits: straight-on front and
back views of the chair (Seedream, 0.5 each, the slice-2 chair's
burgundy back named in the prompt) through `tripo_h3_1_multiview_to_3d`
(9), so the back is seen, not guessed; then the same fit, the pedestal's
ORM replaced with the palette's brushed metal before the bake. If it
holds up from behind, that order places it with `C.import_pack` in
`bridge.py` as the captain's chair (the conn chairs stay scripted:
furniture at 1.5 k is where scripting wins), measured with deckshots
against slice 2's chair. The `LICENSE.txt` line the pipeline needs is
the one used here: "Generated with Higgsfield (Tripo H3.1) on the
captain's plan, 2026-10-20, the output the captain's under Higgsfield's
terms."

## 8c. The second pilot: four straight views (2026-10-20, main 0.282.0) - placed in 0.283.0

Number One's order, on the captain's word: 8b's recommendation, at most
12 credits. Not placed in `bridge.py` (Okafor is on slice 3 there);
the deck shots below come from a scratch build only. **The report**
(the deck shots, the Blender renders, the numbers, the images and
prompts):
<https://<server>/media/reports/2026/10/captain-s-chair-the-second-pilot-multiview-1504b8eb.html>.
The glbs (Tripo's raw one, the fitted one for the pack, the 6 k one),
`LICENSE.txt`, the Blender pass (`pilot2.py`), the four images and
prompts, and the scratch diffs of `bridge.py` and `common.py` are one zip:
<https://<server>/media/reports/2026/10/captain-s-chair-pilot-2-the-glbs-license-blender-2c0edfa2.zip>.

**What was done.**

1. **Four views, not two.** Tripo's multiview takes its slots in the
   order front, left, back, right ("left" the object's own: the front
   swings to the camera's left), and `higgsfield` fills them from the
   `--image-references` in order, with no way to leave one empty: two
   images would have put the back in the left slot. So four Seedream 5.0
   Flash images (1:1, 2k), straight on and level with the arms: the
   front (references: the TNG concept B and 8b's front image), then the
   back (the new front and 8b's back), then the two sides (the new front
   and back). The prompts name the darker burgundy shell, the brighter
   cushions and a satin, not mirror, pedestal. None re-rolled; the sides
   are a few degrees off true profile, which did not matter.
2. **Tripo H3.1 multiview** (`tripo_h3_1_multiview_to_3d`, `face_limit`
   12000, PBR): 3 min 9 s, a 2.9 MB glb of 10,932 triangles, 1.0 m tall,
   its front +X and square to the axes this time.
3. **Blender** (`pilot2.py`, 8b's `pilot.py` plus three steps): turned
   -90°, on the floor; the pedestal (faces under 22.5 % of the height
   and inside the foot's radius: 2,795) given the palette's `trim` in
   place of Tripo's maps, before any bake; the same fit (x and y x1.30
   so the arms' outer faces are ±0.415, z x1.45 so the seat top is
   0.58); the pedestal's axis on the origin; written whole as the pack's
   `captain_chair.glb`, then decimated to 5,900 for the renders.
   Fitted: 0.83 x 0.87 x 1.45 m against the scripted 0.83 x 0.80 x 1.35.
4. **The deck, from a scratch build.** A copy of the tree with
   `bridge.py`'s chair replaced by `C.import_pack(pack, "bridge",
   budgets={"captain_chair": 6000})` and built by `build.sh bridge`;
   deckshots of it and of main at 390x844, graphics low: view B
   (`chairs,0,-35.4,0,-0.06`), `prop:captain_chair,1.6,180` and
   `prop:captain_chair,1.6`.

**Credits:** 775.5 before, 764.5 after, **11 spent**: four images (2.0)
and the multiview job (9).

**Does it hold up from behind? Yes.** Seen, not guessed: a burgundy
shell a shade darker than the cushions, the brushed plate down its
middle, the headrest on a steel stem, the black pan, the satin pedestal.
From view B it reads as the set's chair where the scripted one reads as
a rounded block; from the front, the stand-in's armrest lights land
under its arm consoles' fronts as they are, no second fit needed. Three
chairs cost +2.9 k triangles in view B (492.6 k against 489.8 k), +0
draw calls (59), and the bridge's files 394 kB against 277 kB.

**A trap the placement must avoid.** Tripo's mesh is open (2,914
non-manifold edges), and `import_pack`'s `normals_make_consistent`
turned 1,274 of the decimated chair's 5,999 faces inside out: in the
deck, a hole through the backrest from the front and a ragged fringe
under the back (the report's fourth deck shot). Tripo's own normals are
right; the scratch build without that step shows neither. The step
stays for the Poly Haven packs it was written for (the vase's flipped
faces); a generated mesh needs it off.

**Should the next order place it? Yes.** The plan:

1. **The folder.** `scripts/deck-models/generated/captain_chair/`, not
   in git like a downloaded pack's (it is 2.8 MB): `captain_chair.glb`
   (the zip's `chair/captain_chair.glb`, already fitted, pedestal in
   `trim`, its axis on the origin) and `LICENSE.txt` ("Generated with
   Higgsfield (Tripo H3.1 multiview) on the captain's plan, 2026-10-20,
   the output the captain's under Higgsfield's terms."). Where the glb
   lives for a rebuild is the order's choice: the media store with a
   fetch in `build.sh`'s `fetch()`, as Poly Haven's are cached, is my
   pick; committed is simpler and 2.8 MB.
2. **`common.import_pack`** gets `keep_normals=False`, skipping
   `normals_make_consistent` when true (the zip's `placement-common.diff`
   is the scratch form, an environment switch).
3. **`bridge.py`**: `captain_chair()` stays (the fallback, and the
   numbers above). In its place at the bottom:
   `lows, sources = C.import_pack(src, "bridge", budgets={"captain_chair":
   6000}, keep_normals=True)`; then the pedestal's axis back on the
   origin, since `floor_origin` centred the footprint (the bottom's
   vertices' mean, applied to the low copy and its source alike: -0.011,
   -0.009 here); `chair = lows[0]` in `props`, and `C.finish_room("bridge",
   props, size=1024, sources=sources)`. `build.sh`'s `fetch()` gives
   `bridge` the folder as its second argument. The same as passing
   `--tris-captain_chair 6000` to `pack.py`, inside the room script so
   it shares the bridge's atlas. The zip's `placement-bridge.diff` is
   this, in scratch form.
4. **The colour.** Its leather is pinker than `bridge_leather`
   (0x5e1f1c) and `bridge_shell` (0x4a1715); a hue and saturation pull
   on its base colour before the bake, toward the palette, so it sits
   with the conn chairs.
5. **`deck.html` needs nothing**: the same `model(chair(x, z, s, true),
   "bridge", "captain_chair", ...)` for all three command chairs, and
   the stand-in's armrest lights fit as they are. The captain's chair is
   scaled 1.15 wide there; it was shot so and holds.
6. **Measure** as here: view B, `prop:captain_chair,1.6,180` and
   `prop:captain_chair,1.6` against main, and look at the front for a
   hole (the normals) before anything else.

**Placed, 0.283.0** (Number One's order, after slice 3). As planned,
with what the plan did not know:

- **Where the glb lives:** `$LCARS_MEDIA_ROOT/media/deck-models/captain_chair/`
  (`captain_chair.glb`, `LICENSE.txt`), the NAS here. `build.sh`'s
  `fetch()` for `bridge` copies it into `~/.cache/lcars-deck-models/generated/`
  (the root from the environment, else `~/.env`'s line) and passes that
  folder; with neither, nothing, and `bridge.py` builds
  `captain_chair()` (checked: 5,044 triangles, as before). The licence line
  reaches `lcars-ui/deck/LICENSE.txt`'s bridge section.
- **The colour:** measured and pulled in linear space (the node works on
  the texture node's linear output): the leather's mean hue 0.959 to the
  palette's 0.003, saturation x1.07, **and value x0.81**. The first try,
  hue and saturation measured in sRGB, came out orange-tan in the deck:
  the texture's cushions are lighter than `bridge_leather`, and turned to
  its hue alone under the bridge's warm light they read as tan leather.
- **Measured against main 0.282.1** (deckshots, 390x844, graphics low): no
  hole from the front; view B 59 calls, 492.7 k triangles against 489.9 k
  (+2,865: three chairs at +955); from behind 58 and 58; from the front
  170 and 170. The room's models ~36.1 k of 40 k (section 6's 33.1 k,
  slice 3's +88, this). **The wire:** `bridge.glb` and its three webp 279
  to 406 kB, +127 kB (+45 %), almost all the atlas carrying the generated
  chair's texture and normal detail (base 21 to 51 kB, normal 11 to 37,
  ORM 109 to 141, the glb 139 to 178); still under section 6's ~600 kB.


## 8d. The third pilot: Tripo's own API (2026-10-20, main 0.284.1) - the plan; run in 8e

Number One's order, on the captain's word: the same chair through Tripo's
API directly (developers.tripo3d.ai), at most 200 API credits, to see
whether its own steps (smart low-poly, retopology, a texture pass last)
beat 8c's Higgsfield job plus our Blender pass. Nothing placed.

**Not run: the API account has no credits.** `TRIPO_API_KEY` (in
`~/.env`) authenticates, but `GET /v3/account/balance` (and the v2
`/user/balance`) answer `balance 0, frozen 0`, and `/v3/account/usage` is
empty: the plan's 1,000 and the first key's 2,000 are not on this key's
account. Nothing was submitted (a task freezes its credits at creation and
would only be refused). The plan below is checked against Tripo's docs
today, so the run is the API calls and the measuring.

**The docs, checked** (the `.md` form of each page:
`developers.tripo3d.ai/en/docs/<page>.md`), against the web's summary:

- **Endpoints (v3).** `POST /v3/files` (multipart, PNG/JPEG ≤ 20 MB: a
  `file_token`), `POST /v3/generation/multiview-to-model`, `POST
  /v3/mesh/decimate` (the retopology), `POST /v3/models/texture`, `GET
  /v3/tasks/{id}`, `GET /v3/account/balance`. Bearer key.
- **Multiview inputs:** view keys, `[{"front": tok}, {"left": tok},
  {"back": tok}, {"right": tok}]` (order free; the legacy form is four
  strings front, left, back, right). 8c's four images fit as they are;
  no regeneration needed.
- **Generation parameters, as named:** `texture`, `pbr`,
  `texture_quality` (`fast|standard|detailed|extreme`), `geometry_quality`
  (`standard|detailed`, H ≥ v3.0 only), `orientation` (`default|align_image`,
  only with a texture), `auto_size` (H ≥ v3.0), `smart_low_poly` with
  `face_limit` (triangles 500-20,000, quads 500-10,000; it ignores
  `quad`), `export_uv`, `compress: "geometry"` (meshopt). The summary
  was right on all of them but one: **there is no `lighting_removal`;
  the switch is `delight`** (default true), and only texture model
  `v3.5-20260815` reads it - the H and P series default to texture
  `v3.0-20250812`, which ignores it. So `texture_version:
  "v3.5-20260815"` must be set, or the studio shading 8c's albedo carries
  is baked in again. `export_orientation` must stay unset when the model
  is post-processed (a wrongly oriented result is reported as success).
- **Retopology (`/mesh/decimate`):** `input` (a task id), `model`
  `v1.0` (plain decimation, 10 credits), `v2.0` (default, "smart" with
  `bake`, 30), `v3.0` (35 triangles, 40 quads, `smart_uv` to unwrap in
  the same task); `face_limit` 500-20,000 (quads 500-10,000).
- **Texture (`/models/texture`):** `input` a task id, `model`
  `v3.5-20260815` (for `delight`), `texture_quality`, `pbr`, `bake`,
  `texture_alignment` (`original_image|geometry`), and `texture_prompt.images`
  with the four views - "strongly recommended" when texturing from a
  task id, so given again.
- **Versions** (`models-and-versions`): H3.1 (`v3.1-20260211`, the
  default) "high-precision"; P1 (`P1-20260311`, 50-20,000 faces, "best
  low-poly") and P2 (`P2-20260801`, preview, native quads, 48-50,000);
  the P series is documented as giving "cleaner topology and more precise
  face-count control". Multiview takes either (`/generation-multiview-to-model/p`).
- **Prices** (`/en/pricing`, 1 credit = 1 cent): multiview 30 with a
  standard texture (20 without); add-ons HD texture +10, 8K +20, HD
  geometry +20, quad +5, smart low-poly +10; texture task 10 / 20 (HD) /
  30 (8K); retopology as above. The same for the H and P series.

**The run, 175 credits:**

| # | task | parameters | credits |
|---|---|---|---|
| A | H3.1 multiview, the full mesh | `geometry_quality detailed`, `texture true`, `pbr true`, `texture_quality standard`, `texture_version v3.5-20260815`, `delight true`, `orientation align_image`, `auto_size true` | 50 |
| B | retopology of A | `/mesh/decimate`, `model v3.0`, `face_limit 6000`, `smart_uv true`, triangles | 35 |
| C | H3.1 smart low-poly | as A without HD geometry, `smart_low_poly true`, `face_limit 6000` | 40 |
| D | P1 multiview | `P1-20260311`, `face_limit 6000`, the texture as A | 30 |
| E | HD texture, last, on the kept mesh (B, C or D) | `/models/texture`, `v3.5-20260815`, `texture_quality detailed`, `pbr`, the four views as `texture_prompt.images` | 20 |

A is textured at standard only because `align_image` needs a texture;
the texture that counts is E's, after the topology is final, so its UVs
are the final mesh's (no Blender decimation this time). D is the
docs' own answer to "which series for clean low-poly", at the price of
one generation, against the two ways of getting there from H3.1 (B and C).

**Then, as ordered:** each of A-D and E's result through trimesh first
(`is_watertight`, non-manifold edges, `is_winding_consistent`, bounds in
metres, triangles), next to 8c's raw mesh (10,932 triangles, 2,914
non-manifold edges, open); pilot2.py's fit without its -90° turn
(`align_image`) and without the decimation; `import_pack` with
`keep_normals` off and on; deckshots of a scratch build from view B,
`prop:captain_chair,1.6,180` and `prop:captain_chair,1.6` against
0.283.0's chair; the bridge files' bytes; the credits from `credits_consumed`.

**For the record: the roads.** The official Tripo MCP server
(vast-ai-research/tripo-mcp) and Higgsfield's Blender plugin both drive
an open Blender GUI scene, so neither runs on this box (headless, no
display); the two roads are Higgsfield's CLI (8b, 8c: Tripo H3.1 at 9
Higgsfield credits a job, no retopology or texture task) and Tripo's own
API (this section: every step, priced above). Tripo also ships a CLI
(`developers.tripo3d.ai/en/docs/cli`); plain `curl` against the v3 API
is enough here.

**Needed from the captain:** API credits on the account this key
belongs to (platform.tripo3d.ai's billing page: the Studio plan's 1,000
may need claiming there, or a top-up of at least $2), or a key from the
account that holds them. Then the run above is about half an hour.

## 8e. The third pilot, run (2026-10-21, main 0.285.0)

8d's plan, run after the captain's 1,000 trial credits reached the key's
account. Nothing placed; the deck shots come from scratch builds.
**The report** (Tripo's previews, Blender renders, deck shots, numbers):
<https://<server>/media/reports/2026/10/captain-s-chair-pilot-3-tripo-s-own-api-d2cb4722.html>.
The glbs (B, C, D, E, E fitted for the pack; A's 57 MB left out, its
task id kept), `tasks.json` (each task's parameters, credits and time),
the scripts (`tripo.py`: upload, submit, poll, reading the key from
`~/.env` and never printing it; `pilot3.py`, pilot2.py without the
decimation and with the normals count; the trimesh checks) and the
scratch diffs are one zip:
<https://<server>/media/reports/2026/10/captain-s-chair-pilot-3-the-glbs-scripts-and-sho-fa6c7b0b.zip>.

**Credits: 195** (1,000 to 805): A 50, B 35, C 40, D 50, E 20. P1 was
billed 50, not the 30 that the price list's one multiview row suggests.

**The meshes** (trimesh merged by position for the topology; "as
imported" is Blender's view, where every UV seam is split):

| | triangles | watertight | non-manifold edges, merged / as imported | bodies | `normals_make_consistent` turns, as imported / merged first |
|---|---|---|---|---|---|
| 8c, Higgsfield H3.1 multiview | 10,932 | yes | 0 / 2,826 | 1 | 1,702 / 6 |
| A, H3.1 multiview, HD geometry | 1,935,430 | no | 132 / - | 42 | - |
| B, retopology v3.0 of A, 6k | 6,071 | no | 60 / 1,579 | 25 | 251 / 53 |
| C, H3.1 smart low-poly, 6k | 7,212 | **yes** | **0** / 6,362 | **1** | 1,909 / **0** |
| D, P1 multiview, 6k | 5,816 | no | 260 / 6,218 | 17 | 1,131 / 61 |
| E, C with the HD texture | 7,212 | yes | 0 / 6,362 | 1 | 1,909 / 0 |

**What it found.**

- **The normals trap is Blender's seams, not holes in the meshes.** 8c's
  mesh is watertight, and so is C. The 2,914 "non-manifold" edges 8c
  counted are UV seams, which the glTF importer splits into separate
  vertices. `normals_make_consistent` then sees islands, not one closed
  surface, and turns faces inside out. Merged by distance first
  (`remove_doubles`, 1e-5 m), C has 0 open edges and 0 faces turned,
  and 8c's has 6. In the deck, keep_normals **off** shows holes along
  the backrest's seams from the front. **On**, or off with the merge
  first, is clean (the report's deck shots). So the fix belongs in
  `import_pack`: merge, then make consistent. `keep_normals` can then
  go, and the bake from the unmerged source is unchanged.
- **Smart low-poly (C) is the step that earns its credits.** At 40 it
  gives a closed, single-body mesh at about 7k triangles, with Tripo's
  own UVs and maps for that mesh, and no Blender decimation. It came out
  at 7,212 for a `face_limit` of 6000 (the limit seems to count quads
  before triangulation), so the bridge's three chairs cost +1,213 each.
- **Tripo's retopology (B) does not.** For 35 it took A's 1.9 M
  triangles to 6,071, but in 25 bodies and open (60 edges), and its
  smart UV gave a 1024² normal map. Our decimate-and-bake from a closed
  mesh does better for nothing. A's HD geometry (+20) is only worth
  having as a retopology source, so it goes too.
- **P1 (D) does not.** The docs call the P series "cleaner topology", but
  this chair came back in 17 bodies, open, and pinched at the backrest,
  for 50. P1 may suit simpler, harder-edged props; a curved
  upholstered chair is H3.1's.
- **The HD texture pass last (E) does not, for the deck.** It gave 4096²
  maps (a 17 MB glb), but the bridge bakes every prop into one 1024²
  atlas, where E and C look the same. It would matter for a close-up
  model with its own textures, which the deck has none of.
- **`delight` is visible but small.** The leather's shading is flatter
  than 8c's (less of Seedream's studio light in the albedo). It is still
  pinker than the palette, so `pull_leather` stays.
- **`align_image` and `auto_size` saved nothing.** The front still came
  out on +X, so the -90° turn stays. auto_size measured a real 1.10 m
  chair with a 0.44 m seat, and the stand-in's 0.58 m seat stretches it
  by ×1.32 regardless. Fitted, E is 0.83 × 0.86 × 1.45 m, as 8c's.
- **In the deck** (390x844, graphics low, against main 0.285.0 with 8c's
  chair): view B 59 calls both, 497,488 triangles against 493,849
  (+3,639). The bridge's files (glb and three webp): 420 kB on main,
  453 kB keep_normals on, 466 kB off, **392 kB off with the merge** (a
  merged low copy has fewer vertices, and its atlas compresses better).
  The chair reads the same as 8c's from view B and the front. Its back
  plate is cleaner, and the headrest's stem bracket shows as a small
  bright block from behind.

**Verdict: no better chair. Leave 8c's placed.** The API's chair is a
peer of 8c's: closed where 8c's was too, with flatter albedo, at four
times the price, and with +1.2 k triangles a chair unless limited
lower. What the pilot does change:

1. **The merge before `normals_make_consistent` in `common.import_pack`**,
   with `keep_normals` dropped. It is a small code change for a later
   order: it makes any image-to-3D mesh safe, and on this chair it
   saved 28 kB of the bridge's wire.
2. **For the other rooms' hero props, the pipeline:** the four straight
   views as 8c made them (Seedream, about 0.5 Higgsfield credits each);
   then `POST /v3/generation/multiview-to-model` on H3.1
   (`v3.1-20260211`) with `smart_low_poly true`, `face_limit` about
   0.8 x the prop's budget (it overshoots), `texture true`, `pbr true`,
   `texture_quality standard`, `texture_version v3.5-20260815`,
   `delight true`: 40 API credits, about 5 min. Then our Blender fit
   (turn, floor, scale, the trim and palette pulls) and `import_pack`
   with the merge, with no decimation needed. No retopology, no P1, no
   HD texture, no HD geometry. Higgsfield's H3.1 job (9 Higgsfield
   credits, 12k triangles, no smart low-poly) plus our decimation stays
   the cheap road, and since the merge fixes the normals it is as good
   for a prop the deck bakes small.
3. **The licence line** for an API-made model is open: these were trial
   credits, and Tripo's terms for trial output (ownership, attribution)
   should be read before one is shipped. 8c's model, made on the
   captain's Higgsfield plan, is unaffected.

## 8f. The chair's seam cracks, mended (2026-10-21, main 0.286.1, 0.286.2)

The captain, on the live deck: the chairs look ugly, with triangles
intersecting. Shot close up (`prop:captain_chair` from the front, at 1 m
and 30°, three-quarters behind and behind, at graphics low and high),
the placed chair had black slashes across the seat's front, light
slivers along the backrest's seams, and blotches in the bake. 8e's cause:
the glTF importer splits every vertex on a UV seam, so the closed mesh
was decimated as islands, and each side of a seam collapsed on its own.

**The fix, as 8e said:** `common.import_pack` welds the joined mesh
(`remove_doubles` at 1e-5 m, the source and so its low copy) before the
decimation and before `normals_make_consistent`; `keep_normals` is
gone. Rebuilt: the cracks, slivers and slashes gone at low and high;
view B 60 calls and 494,368 triangles (494,365 before), the prop views
the same; `bridge.glb` and its three webp 420 to 381 kB (base 53 to
42, normal 32 to 30, ORM 132 to 121, glb 203 to 187: a welded mesh has
fewer vertices and bakes cleaner). No Tripo job was needed. The ready
room's two Poly Haven props go through the same weld at their next
build; at 1e-5 m it merges only a seam's twins.

## 8g. Handover: the textures (part 4, in progress) and parts 2 and 3

Number One's order of 2026-10-21 (thread deck-redesign), four parts.
**Part 1 is done:** 85f3623 (0.286.2, 8f), committed and not deployed.
Number One deploys it after reading the diff. Parts 4, 2 and 3 follow,
in that order; part 4 is its own commit, so the chair can ship first.

**Where the work lives (none of it in the tree):**

- The generated tiles and their prompts:
  `$LCARS_MEDIA_ROOT/media/deck-models/bridge_tiles/` (that is
  `$LCARS_MEDIA_ROOT/media/deck-models/bridge_tiles/`). It holds
  `carpet.png`, `wall.png` and `wainscot.png`, the chosen sources, and
  `LICENSE.txt`. Under `raw/` are all seven (`*_s` Seedream 5.0 Flash at
  1k, `*_z` Z Image at 2048) and `prompts.txt`, one `name|prompt` per
  line, all sharing the lead "Seamless tileable texture, edge to edge,
  orthographic straight-on, flat even shadowless lighting, no vignette,
  no perspective, no objects, no text:".
- The working files: `~/.local/share/lcars-eng-work/zimmerman-c39/`.
  - `tiles.py`: the draft processor (below).
  - `tiles-out/`: its first output.
  - `live-{low,high}/` and `new-{low,high}/`: part 1's chair shots,
    before and after.
  - `grid.py` and `montage.py`: shot contact sheets.
  - `six0-{low,high}/`: where the before shots land (below).
- **Credits: 1.75 Higgsfield** of part 4's 10 (764 to 762.25): five Z
  Image (0.15 each) and two Seedream at 1k (0.5 each). Part 2's
  concepts have their own 5. Tripo: 0, and none needed.

**Which tiles won (judged as images; still to be judged on the phone):**

- **Carpet: `carpet_s` (Seedream) wins.** A fine loop pile with the
  darker charcoal fleck, as the concept has it; it came back purple and
  is matched to `#4e4548`. `carpet_z` is a featureless grey and lost.
- **Wall: `wall_s` (Seedream) is the candidate.** One padded
  putty-vinyl panel with a dark rim, which is the concept's wall (the
  set's padded panels). `wall_z` is almost blank and lost. The open
  question for the phone: the square panel is stretched to the 1.2 x
  2.4 m cell (see `wall()` below). If a stretched pillow reads badly,
  the fallback is `T.panelBridge` with `wall_z`'s grain only.
- **Wainscot: `wainscot_z`, doubtful.** Dark walnut that reads as plank
  flooring (horizontal board seams about every quarter of the tile). The
  concept's wainscot is dark panels with vertical seams, which
  `T.grooves` is nearer to. My expectation: keep the procedural
  `M.wallLow` clone (`bwLowMat`), and say so.
- **Fascia (`fascia_z`) and rail wood (`railwood_z`): lost.** Both came
  back as stacked planks with dark seams. Besides, the consoles' and
  stations' faces and the tactical rail are in `bridge.glb`'s baked
  atlas (the `console` and `rail_wood` palette materials in Blender),
  not in a deck.html material: a generated texture there would need an
  image texture node in `bridge.py` before `finish_room`'s bake. Keep
  the procedural; reason: no clean tile, and the atlas bake already
  gives them their shading. `M.rail` (deck.html) is shared with the
  handrails and display frames of other rooms, so it cannot change for
  the bridge alone.

**`tiles.py`** (to be committed as `scripts/deck-models/tiles.py`):
`python3 tiles.py SRC_DIR OUT_DIR [name...]` writes
`bridge_<name>_{base,norm,rough}.webp`. The steps, per surface:
`flatten` (divide out the generated light's slow drift), `seamless` (the
offset-and-blend pass: rolled by half, a smoothstep weight, a
variance-preserving mix), the height from luminance (normalised), the
normals from the height wrapping (as `normalTex` in deck.html, the
same "dn - up"), roughness from the height, and `match` (a per-channel
gain in linear space so the mean is the palette's colour, as
`pull_leather` did; the material's colour then becomes white). The
roughness is written at a quarter size. For `wall()`, the panel goes in
twice across (two 1.2 m columns, the tile 2.4 m square as
`T.panelBridge`'s), rolled down so its rims sit on the reveal at 0.7 of
the tile from the top (3.02 m), with the 6 cm reveal channel cut darker
and deeper, as `panelSet(true)` does. Still to do: prove each tile with
a 2x2 repeat (an image) before wiring it in.

**Map sizes so far, and the bytes problem.** First pass, at 512²:
carpet base 52 kB and **normal 129 kB**; wall 5 + 9 kB; wainscot 8 + 3
kB; roughness under 1 kB each. Room budget (section 6): ~600 kB, with
`bridge.glb` and its three webp now 381 kB plus the skylight's 67:
**~150 kB left.** The carpet's normal map is the problem: it is noise,
so webp cannot compress it. Fixes to try in order: the normal from a
blurred height (the loops' relief at 1 px is lost on a phone anyway), at
256² with the tile kept at 0.7 m; quality 60; or no normal map, the
carpet's relief left to `T.carpet`'s procedural normal (keep `T.carpet`'s
`normalMap` and swap only `map`). The wall's numbers are suspiciously
small: check its output was not flattened to a blank before trusting
them.

**How each is to be wired into `deck.html`** (no new materials, +0
calls, +0 triangles):

- **Carpet:** `M.carpetBridge` and `M.carpetWell` (line ~1335; only the
  bridge uses them, `floor` at ~3422 and `well` at ~4245) keep
  `surf(T.carpet, 0.7, ...)` as the fallback. Then the same loader the
  skylight uses (~4315: a `THREE.TextureLoader().load(DECK_MODELS +
  "bridge_carpet_base.webp", t => ...)`, failing silently): on load, set
  `colorSpace` SRGB on the base, `wrapS = wrapT = RepeatWrapping`,
  `anisotropy = maxAniso`, swap `map`, `normalMap` and `roughnessMap`,
  set `color` to white, and `needsUpdate`. The well's colour is a shade
  lighter (`#6a5e60`): either keep its `color` at the ratio of the two
  palette colours with the same map (simplest, one texture set for
  both), or match a second base. `userData.tile` (0.7) stays, so
  `autoUV` is unchanged.
- **Wall:** `bwMat` (~3431, a clone of `M.wall` already taking
  `T.panelBridge`'s maps) swaps to `bridge_wall_*` on load, in the same
  way; `T.panelBridge` stays as the fallback. The tile is 2.4 m, so the
  reveal stays at 3.02 m.
- **Wainscot:** only if it wins on the phone: `bwLowMat` (~3431, a
  clone of `M.wallLow`, colour x0.82) swaps the same way.
- One helper for the three swaps (a `swapTiles(mat, name)` beside the
  skylight's loader), so a missing file leaves the procedural.
- **Licence:** a `== bridge_{carpet,wall}_*.webp` section in
  `lcars-ui/deck/LICENSE.txt`, and a THIRD_PARTY_NOTICES.md row (the
  captain's, under Higgsfield's terms), as 0.286.2 did for the chair.

**Jobs.** The six looks' "before" shots, at graphics low and high,
are re-queued to `~/.local/share/lcars-eng-work/zimmerman-c39/six0-{low,high}/`.
The views are A `lift,-8.6,-38,-1.0`, `door,0,-29,0`, B
`chairs,0,-35.4,0,-0.06`, C `screenback,0,-44.5,3.14159,-0.1`,
`wide,0,-30.5,0,-0.1` and `screenfar,0,-45,3.14159,-0.08`, at 390x844.
They are the state after part 1 and the baseline for part 4. Shoot the
same after the textures, compare the bytes and the boot time
(deckshots' "boot" line), and run `run.sh --changed` (deck.html: the
deck stage) and `node test/deckboot.js deck.html`. CHANGELOG and
`APP_VERSION` take a minor (0.287.0: a new look). Commit, and do not
deploy.

**Part 2, the gap report (not started).** The six looks above, beside
the nine concepts: the report
<https://<server>/media/reports/2026/10/main-bridge-redesign-concept-art-zimmerman-fd7dd8ab.html>
and its zip
`$LCARS_MEDIA_ROOT/media/reports/2026/10/main-bridge-concepts-full-resolution-images-and-56aa7198.zip`,
which holds `concept-{tng,dark,night}-{A,B,C}.jpg`, `current-phone-*.png`,
the old `texture-*.jpg` and `prompts.py`. Go object by object: what the
concept has that the deck still lacks now that the six slices are in.
Then three new Seedream 5.0 Flash concepts (A, B, C; section 2's common
lead and direction 1's line; today's live shots, with the UI's pills
and header cropped, as the references; 2k, 16:9, about 1.5 credits),
and put them in the report. Publish with `scripts/report.py publish`.

**Part 3, the plan (not started):** in that report, and as section 9 of
this doc. The ranked slices to close the gap, using 8e's pipeline for
hero props: four straight views on Seedream (front, left, back, right),
then Tripo `multiview-to-model` on H3.1 with `smart_low_poly`,
`face_limit` about 0.8 x the budget, PBR, `texture_version v3.5`,
`delight`, at 40 API credits; then pilot3.py's Blender fit (the -90°
turn, the floor, the scale, the trim and palette pulls) and
`import_pack`, which now welds (8f). Candidates: the conn consoles,
the tactical rail, the stations and the conn chairs; say which are
worth it. For each slice give its credits (Higgsfield and Tripo), its
triangles against the 40 k with ~1.7 k left (say whether the budget
should move, and what that costs the phone), and the captain's
decisions. Also open: Tripo's terms for output made on trial credits,
to be read before any API-made model ships.

## 8h. Part 4, the surfaces, done (2026-10-21, 0.287.1)

8g's part 4, finished. **Shipped: the carpet and the wall.** Dropped:
the wainscot (made, tied), the fascia and the rail wood (never good).

**The processor:** `scripts/deck-models/tiles.py` (numpy, Pillow), run as
`python3 scripts/deck-models/tiles.py <media>/deck-models/bridge_tiles
lcars-ui/deck`. Per surface: the source's outer 1.5% cut (a generated
"scan" has a light frame, which the seamless pass carried to the tile's
middle as a faint cross: seen in the first 2x2 proof), `flatten`,
`seamless` (offset and blend, variance-preserving), the height from
luminance, normals from it as `normalTex` does, roughness from it, and
`match`: a per-channel gain in linear space to **the palette colour times
the canvas tone's mean** (T.carpet ~0.82, T.panelBridge ~0.92), so the
albedo the room had is kept and only the pattern changes. The deck then
sets each material's colour to its tint over that palette colour
(`bridgeTiles(name, base, ...mats)`): 1 for the floor and the wall, and
the well's lighter `#6a5e60` over the same carpet set, so one texture
serves both carpets. Every tile was proved by a 2x2 repeat before wiring.

**The carpet's normal map:** from the height blurred by 1.5 texels and
written at 256² (the tile stays 0.7 m): **21 kB, from 129**. The loops'
single-texel relief is noise webp cannot pack and a phone never resolves;
the fleck's dimples survive.

**Wiring:** `bridgeTiles()` beside the bridge's floor in deck.html loads
the three maps; when all three land it swaps `map`, `normalMap` and
`roughnessMap` on the existing materials (`M.carpetBridge`,
`M.carpetWell`, `bwMat`) and sets their colour. A missing file leaves the
canvas set. `M.wall`, `M.wallLow` and every other room untouched.

**Measured** (deckshots, 390x844, the six looks of 8g, on this box's
software renderer; `six0` before, `six1` after):

| | before | after |
|---|---|---|
| calls, triangles (each of the six, low) | 65/81/60/209/77/209; 517.0k/707.5k/494.4k/967.3k/703.0k/967.3k | identical |
| boot, low / high | 37.7 s / 46.7 s | 37.8 s / 45.2 s (noise) |
| the bridge's files | 448 kB (glb + 3 webp 381, skylight 67) | **537 kB** (+89: carpet 50+21+1, wall 6+10+0.4) |

**Judged on the phone's shots:** the carpet wins clearly (a loop pile with
a charcoal fleck where the canvas was a flat wash, same colour). The wall
wins: the set's padded panels with a dark rim, the reveal where it was,
the access plate gone (the set has none). The **wainscot** (a clean board
cut from Z Image's walnut, stacked into T.grooves' quarters) ties with
the procedural at that distance and neither has the concept's vertical
seams: not worth 33 kB, dropped; its recipe stays in tiles.py, not in
`SHIPPED`. The **fascia and rail wood** came back as stacked planks; and
the consoles', stations' and rail's faces are in `bridge.glb`'s baked
atlas, not in a deck material (an image there needs a texture node in
`bridge.py` before the bake): procedural kept, no second prompt spent.

**Credits:** 1.75 Higgsfield for part 4 (five Z Image at 0.15, two
Seedream at 0.5), none more. Licence: `deck/LICENSE.txt`'s
`bridge_{carpet,wall}` section and a THIRD_PARTY_NOTICES row, the
captain's under Higgsfield's terms. Sources and prompts:
`<media>/deck-models/bridge_tiles/`.

## 9. The gap after part 4, and the plan (2026-10-21)

**The report** (part 4's before and after, the live looks beside the old
and new concepts, this plan):
<https://<server>/media/reports/2026/10/main-bridge-the-surfaces-the-gap-and-the-plan-zi-7dc12492.html>.
The three new concepts at full resolution, their references and prompt:
<https://<server>/media/reports/2026/10/main-bridge-the-three-new-concepts-at-full-resol-b149d608.zip>.
They are Seedream 5.0 Flash, 2k, 16:9, from 0.287.1's high shots of
angles A, B and C (the header and pills cropped), with section 2's lead,
the angle's line and direction 1's line: **1.5 credits** (762.25 to
760.75).

**Closed:** the carpet, the walls, the skylight and ceiling, the
viewscreen's fins. **Still open**, largest first: the conn and ops
consoles (the concepts' wedge with a lacquered rim round a sloped LCARS
top; ours a tall black box: still the biggest dark blocks from C); the
tactical rail (a continuous padded rolled top over seamed panels; ours a
wood cap on plain boxes); the conn chairs (tall upholstered seats; ours
procedural, 1,252 triangles, a generation older than the captain's
beside them); the captain's chair's back plate (it bakes near white); the
stations' faces; the light (direction 3's, its own order).

**The budget today:** the room's models are 38,276 of 40,000 triangles
(captain_chair 6,000 x3, tactical_rail 2,374 x2, station 1,036 x4,
station_long 1,036 x2, conn_console 1,512 x2, conn_chair 1,252 x2,
armrest_console 1,004 x2, display_bezel 176 x6, screen_fin 360 x2).

**The slices, ranked.** 8e's pipeline is for soft, organic props (it made
the chair); hard-edged ones fitted to the room's radii are better and
cheaper in `bridge.py`.

1. **Conn consoles** (`bridge.py` `conn_console`): a sloped top with a
   rounded lacquered rim (`rail_wood`/`bridge_shell`), rounded ends, the
   inset flush; rebake. 0 credits, ~+400 triangles each.
2. **Tactical rail** (`tactical_rail`): a padded bullnose swept along
   the arc, vertical seams on the panels, LCARS tiles in its top.
   0 credits, ~+400 each.
3. **The captain's chair's plate:** a palette pull on its texels in the
   fit, as `pull_leather`. 0 credits, +0.
4. **Conn chairs, generated** (8e's pipeline): four views (2 Higgsfield
   credits), then Higgsfield's H3.1 job (9) and our decimation to ~2.4 k,
   or Tripo's API (smart low-poly, `face_limit` 2,000: 40 API credits).
   +2.3 k triangles: it does not fit the 1.7 k left.
5. **Stations:** the inset tilted 15°, ~+50 each. Later.

**The budget move:** 1-3 and 5 fit only tightly; 4 does not. (a) Take the
three captain's chairs from 6,000 to 5,000 (frees 3 k; the weld makes
the decimation clean) - recommended; or (b) the room to 43 k: view B
draws 494 k triangles in all, so +3 k is +0.6 % and the phone's frame
is bound by fill and calls, which stay +0.

**Tripo's terms** (Terms of User Agreement, updated 2025-07-11, 5.2):
for "Free Users" (those who "use the Services free of charge") Tripo
"retains all rights ... [in] the Inputs and Outputs"; "Paid Users
generally have all rights" in theirs, granting Tripo a non-exclusive
licence to display them for the service, and Tripo does not train on
them. The terms do not mention trial credits: what counts is whether the
account is paid. platform.tripo3d.ai has no terms of its own (404). So
an API-made model ships only if the captain confirms the account that
holds the 1,000 credits is a paid one; otherwise the Higgsfield road,
whose output is the captain's.

**The captain decides:** ship 0.287.1; order slices 1-3; slice 4 yes or
no, with (a) or (b), and its road.

**As built** (Number One's order of 2026-10-21: slices 1-3, 0 credits;
the room's models against the 40 k; deckshots, 390x844, graphics low):

- **Slice 1, the conn consoles' rim (0.287.2):** `conn_console`'s far
  edge and ends a `rail_wood` bullnose (1.66 x 0.07 x 0.07 m, the ends
  0.07 x 0.7, bevel 2.4 cm in three segments), replacing the black edge
  boxes. 1,512 to 1,752 triangles each, +480; the room 38,756. Views
  (main, after): calls the same in all fifteen looks and props;
  screenback 967,266 to 967,746 triangles, `prop:conn_console` 477,854
  to 478,334. `bridge.glb` + atlas 380.7 to 385.2 kB. The concepts'
  wedge (rounded far corners) and the low brushed bar were left: the bar
  is 0.282.1's trim line, and the corners would cost ~300 more each.

- **Slice 2, the tactical rail (0.287.3):** the cap's half-section eight
  points (was six) out to 13.6 cm, the top at 1.14; the four inner posts
  replaced by seven `black` seams (2.2 x 8.2 cm, 0.86 m tall) at eighths
  of the arc, the two end posts kept. 2,374 to 2,386 triangles each, +24;
  the room 38,780. Calls the same; chairs 494,848 to 494,872 triangles.
  385.2 to 381.3 kB. The concepts' LCARS tiles in the rail's top were left
  for later (the tactical panel is the one there).

- **Slice 3, the captain's chair's plate (0.287.4):** `pull_plate` in
  `generated_chair`, after `pull_leather`: texels with value over 0.4 and
  saturation under 0.3 (ramped over 0.1 each, so no edge shows; 18.6% of
  the texture) scaled by 0.68 with a +-6% streak per texel row. The plate's
  albedo was not lighter than `trim` (0.56 in sRGB); it read white because
  nothing else on the chair is near it under the overhead light. +0
  triangles, calls the same; 381.3 to 380.5 kB.
- **After the three:** the room's models **38,780 of 40,000: 1,220
  left**. All six looks: calls +0, triangles +504 where both consoles and
  both arcs show. The bridge's files 536.5 to 536.3 kB in all (the glb and
  atlas 380.5, the skylight 67.1, the tiles 88.7). Boot within noise
  (37.7 s main, 36.4-36.7 s the slices; one run at 59.6 s on a loaded box,
  its high run 45.1 against main's 44.7).

- **Slice 4, the conn chairs generated (0.288.1;** Number One's order:
  budget (a), Higgsfield's road, cap 15 credits). Four Seedream 5.0 Flash
  views (1:1, 2k, none re-rolled): the front from a crop of concept B's
  port helm chair and the whole concept, the back from the new front and
  the crop, the two sides from the front and back; the chair alone on a
  plain grey ground, level with the arms. Then `tripo_h3_1_multiview_to_3d`
  in the order front, left, back, right, `face_limit` 2,400 (0.8 x the
  budget), PBR: 3 min 30 s, **2,238 triangles** (2,234 welded), 1.0 m
  tall, front +X. **Credits: 11** (760.75 to 749.75): four images 2.0, the
  job 9.
  - **The fit** (`<media>/deck-models/conn_chair/raw/fit.py`, with the raw
    glb, the views and prompts): turned -90°, on the floor; z x1.41 so the
    cushion's top (0.41 of the raw height) is the stand-in's 0.58, x and y
    x1.1 so the arms are +-0.31 (`block()`'s +-0.315) and the foot r 0.27;
    faces under the pan (0.27 of the height) and inside r 0.29 in `trim`
    (600); the foot's axis on the origin. 0.63 x 0.66 x 1.42 m against the
    scripted 0.58 x 0.62 x ~1.30. The folder is
    `<media>/deck-models/conn_chair/` (`conn_chair.glb`, 2.3 MB, and
    `LICENSE.txt`), as the captain's chair's.
  - **The wiring:** `build.sh`'s `fetch()` copies each chair the store has
    into `~/.cache/lcars-deck-models/generated/bridge/<prop>/` and passes
    that folder; `bridge.py`'s `generated_chairs` imports both through one
    `import_pack` (`GEN_BUDGETS`: captain_chair **5,000**, conn_chair 2,400,
    so Tripo's mesh is not decimated), puts each axis on the origin and
    pulls each source's leather and plate; `conn_chair()` and
    `captain_chair()` stay the fallbacks, each on its own. `deck.html`
    needed nothing but two comments: the model is placed unscaled over
    `chair(x, z, 0.9, true, false)`, whose armrest lights stay off (its
    arms are bare).
  - **Metalness x0.35** (`satin`, the conn chair only): Tripo's ORM made
    the back plate and the headrest stem full metal, and a mirror on the
    deck reflects the dark room: from behind a smudged near-black slab.
    The plate's remaining mottle at 1.6 m is the atlas's texel density on
    Tripo's fragmented islands; the captain's plate, live since 0.283.0,
    shows the same at that distance. A clean plate would need the plate's
    faces in `trim` (Tripo's coarse faces do not follow its outline) or
    the chairs their own atlas: not done.
  - **Measured** (deckshots, 390x844, main 0.287.6 against this; graphics
    low for the counts, high for the looks, which counts only the
    composer's pass): view B 60 calls both, 494,872 to 493,836 triangles
    (-1,036: the captain's -1,000 each where all three show, the conn
    chairs +982 each); view C 203 both, 951,587 to 950,551;
    `prop:conn_chair` from the front 205/202 to 206/202 (the culling's
    noise: 1-180, 0-135 and 1-135 equal), from behind 52 both. **The
    room's models 37,744 of 40,000** (the captain's 3 x 5,000, the conn
    chairs 2 x 2,234). The bridge's glb and atlas **380.5 to 397 kB**
    (+16.5; the room's files ~553 kB with the skylight and tiles, under
    section 6's ~600). Boot within noise (low 41.5 s main, 36.9-60.8 s
    this on a shared box). From view B the helm chairs now read as the
    concept's tall squared backs with the brushed plate and the headrest
    on its stem, a generation level with the captain's.

- **Slice 5, the leftovers (0.291.1;** Number One's order of 2026-10-21
  night, 0 credits; deckshots 390x844, main 0.289.1 against this):
  - **The stations' faces:** the body's near face below the status
    lights (0.62 m) is an inset raked back 15° to the foot, 13 cm in at
    0.13, between the end panels and over the lit slot, which stays at the
    front: two more points in `station()`'s profile. 1,036 to 1,048
    triangles each (+12, under the plan's +50), x6.
  - **The conn consoles' rounded far corners:** `far_round()` (r 0.2 in
    six steps) for the slab, extruded by `plate()`, and the rim one
    12-sided bullnose (r 3.5 cm) swept along it by `along()`, where the far
    edge and the two cheeks were three bevelled boxes meeting square. The
    display (1.4 x 0.5) clears the rim's inside at the corners by 1.3 cm.
    1,752 to **1,696** each (-56: one sweep is cheaper than three bevelled
    boxes).
  - **The rail's LCARS tiles:** a black bed 6.4 cm wide on the cap's
    crown, 0.13-0.4 rad either side of the panel (`TILE_A`, swept in six
    steps), 2,386 to 2,490 each (+104); the tiles in it are the page's:
    `blink()` takes a phase and a gain, and a phase under 0.33 is steady,
    so each arc's tiles (lengths cycling 0.22, 0.07, 0.12, 0.3, 0.07, 0.16
    m with 2 cm gaps, colours from `LCV`) are boxes in `blinkMat`, merged
    with the panel's lights: +0 materials and calls, lit as the panel is.
    Baked into the atlas they would have been paint under the room's light.
    `blinkR`'s sequence is untouched (both arguments passed), so every
    other light keeps its colour and phase.
  - **The chairs' plates:** `pull_plate` no longer streaks (a streak along
    the texture's u lands in patches at every angle on Tripo's fragmented
    islands) and pulls the plate's texels 75% of the way to their mean
    before the x0.68: both generated chairs' plates read one clean brushed
    grey from behind at 1.6 m, where main's were blotchy. +0 triangles,
    calls, materials: the cheaper of the two roads, and the trim faces or
    an atlas of their own are not needed.
  - **Measured** (graphics low): the six looks' calls identical
    (65/81/60/209/77/209), triangles +456 each (the models +168 where all
    show, the tiles' merged lights ~+288); the prop views the same calls
    within the culling's noise of one (as slice 4's), +456 triangles. **The
    room's models 37,912 of 40,000** (2,088 left). The bridge's glb and
    atlas 397 to 401 kB. Boot within noise (low 63.0 s main, 46.3 s this,
    on a shared box; the rail views 35.8 against 36.4; high 45.7 main 0.291.0,
    47.1 this). deckboot and `run.sh --changed` pass. The report, the six
    looks low and high and the props, main beside this:
    <https://<server>/media/reports/2026/10/bridge-slice-5-faces-corners-rail-tiles-plates-88697742.html>.
