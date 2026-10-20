# Deck models: making the 3D deck more believable

Number One's order for the captain, 2026-10-14: more realistic, life-like
models of the ship's objects in `lcars-ui/deck.html`, built in code (three.js
primitives and generated textures, nothing downloaded), the frame budget and
load time held, low-end phones kept on a way out. Work in slices, one room or
object group each, each shippable alone.

## Where the deck is already

More than "flat shading, no bevels" would suggest: every box is a
`RoundedBoxGeometry` (`rgeo`), every surface a PBR `MeshStandardMaterial`
with a generated tone, normal and roughness map (`T`: panel seams, carpet,
brushed metal, wood grain, planks, bark, pebble leather), `autoUV` keeps a
texture's size in metres, there is an image-based environment
(`RoomEnvironment`), four shadow-casting spots drawn once, a pool of point
lights, and on desktop GTAO, bloom and a film grade. The crew are rigged CC0
models (not primitives; out of this order's reach: new models would be new
assets).

What gives it away, room by room, is on the phone above all: **graphics
"low" has no composer**, so no ambient occlusion: nothing sits on the
floor, every chair and table floats on a flat carpet. Then a handful of
objects that are still a box or a disc where the eye goes first.
(Since: 0.187.0's contact decals under the furniture and along the walls'
feet, and 0.251.0's occlusion baked into every floor at build - a soft
falloff round each footprint and wall, one atlas a bake, +0 calls - with
a cove at the walls' feet on low; deck-pipeline.md, "Measured: baked
floor occlusion". Since 0.254.1 the bake alone darkens the floors and the
rugs: the decals are left only where a piece stands on something else.)

## Measured before (deb 0.186.3)

`lcars-ui/test/deckshots.py` (new): headless Chromium at 390x844, 3x, touch,
graphics low, `?demo`; stands in the middle of each of deck 8's seven rooms
looking four ways, screenshots each, and reads three's draw calls and
triangles. The milliseconds are SwiftShader's (a software GPU on this box's
CPU, ~1 s a frame at the phone's 585x1266 drawing size), so they only compare
with a run made the same way; draw calls and triangles carry over to a phone.

| | before |
|---|---|
| boot to ship built | 43.1 s (SwiftShader; ~2-4 s on a phone) |
| boot to crew loaded | 51.8 s |
| draw calls, most in a view | 346 (corridor, looking forward) |
| triangles, most in a view | 2.67 M |
| frame p50 over all 28 views | 1242 ms (SwiftShader) |

Two facts that shape every slice:

- **Static geometry is merged per material, deck-wide** (`mergeStatic`), so
  one merged mesh is drawn whole wherever any of it is in view. A triangle
  added to a chair is drawn in every room of deck 8. So added geometry is
  counted, and kept to a few percent of the ~2.5 M already there.
- **A new material is a new draw call** (one more merged mesh). New
  materials only where they earn it; reuse `M.*` otherwise.

## Ranked: time on screen x distance from believable

Phones start on the map (top-down), so the 3D view is mostly the desktop's
and a phone's when it walks; the ranking is for the walking view.

| # | object | on screen | what gives it away | do |
|---|---|---|---|---|
| 1 | contact shadows, every room | always | on phone (low) no AO: furniture floats; the floor meets the wall with no darkening | a soft blob decal under every piece of furniture that stands on the floor, and a darkened band where floor meets wall; one shared transparent material, merged: 1-2 draws. Desktop keeps GTAO (decals lighter there) |
| 2 | Ten Forward: bar bottles, chairs, tables | high (showpiece, bar faces the door) | bottles are unlit coloured cylinders that read as books; chairs are two slabs on a pole; tables flat discs | bottles: lathe profiles (body, shoulder, neck, cap), a lit glass material with the backlight through them; chairs: a shaped shell (lathe/curved back) and a padded seat; tables: a bevelled rim and a lip |
| 3 | Bridge: command chairs, consoles | high (first room forward) | the chairs are a box seat and box back; consoles plain black boxes with a quad on top | chairs: a contoured seat and back (rounded profile, piping seam), armrests with a panel; consoles: a sloped, bevelled top, a lip, a kick plate; small life: status lights that blink, a slow scroll on the panels' bars |
| 4 | wood: ready room ceiling, lounge table | medium | the grain's normal map is so deep at that scale the wood reads as sand ripples | the grain's bump and ring scale reduced, a finer tile; a lacquer (low roughness, clearcoat-like env) on the table |
| 5 | Arboretum: stones, pond, walls | medium | octagon stepping stones, a flat blue pond, corridor beige walls in a garden | irregular stones (noise-displaced, flattened), a pond with a shader ripple and a dark depth, the walls in a stone/planter skin |
| 6 | space outside: the viewscreen and windows | high, but already good | the stars do not move | a slow drift of the near stars (the ship is at impulse), the starbase's lights blinking |
| 7 | corridor: wall panels, doors | highest, but already the most believable | little; a wall without wear | nothing structural; rides on 1 (the floor-wall band) |
| 8 | Concourse floor | medium | a plain grey floor | a tiled stone floor texture |
| - | crew | always | stiff idle | out of scope: they are models, not code |

## Rules each slice keeps

- built from three primitives and generated textures; no downloads, no new
  files but this doc and the harness;
- draw calls in any view up by at most a handful, triangles by a few
  percent; boot time unchanged within noise; numbers before and after in the
  commit and the report, from `deckshots.py` on a phone viewport;
- graphics low on a phone gets no heavier than it is, beyond the counted
  geometry: per-frame "life" is a uniform or a handful of matrices, never a
  rebuild;
- `test/deckboot.js` green, `run.sh --changed` before each commit;
- a minor for the first slice, a patch for each after.

## Slices done

1. **Contact shadows** (0.187.0): `contactMat`, `contact()`, `grounded(g)`
   and `contactBand()`; every furniture group is `grounded`, every wall and
   window wall has a band each side, the bridge a ring. +1-3 draw calls,
   ~+800 triangles a view; frame times within noise. (0.254.1: the bands,
   the ring and the floor-level patches dropped, the floors' bake draws
   them; `contactBand()` is gone.)
2. **Door shadows** (0.187.1): door leaves cast no shadow (`noCast`), so a
   moving door no longer redraws the maps; `rebuildPads` and `switchDeck`
   redraw them once. Frames redrawing shadows 52/88 → 0/120, most triangles
   in a view 4.92 M → 1.23 M, frame median 1509 → 980 ms (SwiftShader).
   Every number before this slice includes those redraws: compare later
   slices with 0.187.1, not 0.186.3.
3. **Ten Forward** (0.188.1): `lathe()` and `shellGeo()` shapes, shared;
   tables with a rolled edge on a flared pedestal, swivel chairs with a
   curved shell back, rolled stool cushions, the bar's padded edge and
   brass foot rail; bottles in three turned profiles, instanced per profile,
   lit glass (`glassMat`, emissive tinted per instance), glasses. Draw calls
   +0 at the median, triangles +17.5 k a view (~3%), +47 k with the bottles
   in frame. A first cut with finer segments cost +26.6 k a view; trimmed.
4. **Bridge** (0.188.2): `chair(x, z, s, rich)`, the bridge's five rich
   (seat shell, two-cushion back in a shell, padded arms with lights), every
   chair on a turned pedestal; `wedgeGeo`/`consoleBody` for the armrest
   consoles and conn/ops, sloped tops on the standing stations; blinking
   status lights in one shader material (`blinkMat`), the merge keeping
   per-material extra attributes (`userData.attrs`). +1 draw call,
   triangles +13.5 k a view (~2-3%).
5. **Wood** (0.188.3): `T.grain`'s rings moved from relief to colour,
   wider and warped along the board only, pores for relief; `T.planks`'s
   grain out of its height. Texture-only; boot and frames within noise.
6. **Space outside** (0.188.4): the plan was wrong here - the starbase
   turns and blinks, the escort rides, shuttles fly, belt and dust drift.
   What gave it away was the rooms' shell (`deck8Shell`, hull kind 7) seen
   close: in `hullMat`, Aztec sub-plates and weathering (fading with
   distance), cabin-sized windows. Shader-only, cost within noise.
7. **Arboretum** (0.188.5): `T.ashlar` stone walls (`skin` and facings
   over the shared walls), irregular field stones, `pondMat` (depth
   gradient, env reflection, shader ripples). +1-2 draw calls in view,
   ~+700 triangles.
8. **Concourse floor** (0.188.6): `T.tiles` for `MX.floorTile` (the
   concourse, the labs, sickbay). Texture-only.

The plan's eight are done. Left, by the same ranking, for a later order:
the crew's stiff idle (models, out of scope), the stepping stones' flat
grey (a stone texture of their own), and the generated decks' rooms, which
share these builders only in part.

What comes next, with modelled props (Blender, CC0 packs), is in
`deck-style.md`.

## Found on the way

- (fixed in slice 2) **The shadow maps are redrawn far more than "once".** A door within a
  shadow spot's reach sets `shadowMap.needsUpdate` on every frame it moves,
  and the crew walk through those doors all the time. Each such frame
  renders the four spots' depth passes: ~7.5 M triangles on deck 8 (the
  merged static meshes cast whole, and the arboretum's instanced foliage),
  three times the frame itself. In deckshots runs a view had a shadow pass
  on 3 frames of 3 or 0 of 5 depending on who was walking: that, not the
  change, is most of the run-to-run noise. Worth its own slice (a door's
  leaves not casting, so a door never redraws them; or the redraw
  throttled), since on a phone it is a hitch each time someone passes a
  door near the bridge, Ten Forward or the ready room.
