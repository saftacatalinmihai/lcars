# The architect: change the ship (and the console) while you watch

Status: **design, for the captain's approval**. Phase 1 is built on the
engineer's branch, not shipped: the deck's layer (0.271.0: `deckApi`,
`lcarsDeckPatch`, `lcarsDeckSees`, `lcarsDeckShot`, the sheet, the deck's
`/events`) and the console's half (0.272.0: the `arch` thread in
index.html, "the architect" block; `crew/architect.md`, served through
`engineer.py brief architect` and kept out of `crew.py`'s runs by `kind:
chat`; the server's guard, `PatchKindAllowed` in lcars_http.h). Not built:
the frozen aim's outline (4.4), the HUD mark and the shimmer (5).
Phase 2's deck half (code-built props by name, generated rooms, the new
verbs, the room's inventory) is built: "Phase 2, as built" in section 7.
Number One's order of 2026-10-19, written by Zimmerman at 0dadeb8
(0.266.0). Line numbers are of that commit.

The captain's wish, in his words: on the deck, say *make this table
round*, *add a plant by that window*, *make this room's light warmer*, or
anything anywhere in the ship; a crew member (the architect, or the
designer) gets what he sees, makes the change, and it appears in front of
him with no reload, "like magic". And the same for the console: ask in a
chat, see the page change live.

The short answer: **the architect is a chat, not an engineer; its answer
ends with a patch (a few lines of JavaScript against a small deck API), and
the page that asked applies it the moment the fence closes in the stream,
keeps it as a journal entry only once it applied, and replays every kept
patch at load.** The rest of this file is why, and how, from the code.

---

## 1. What exists to build on

### 1.1 The deck's chats with the crew

- A crew member's talk sheet is a **thread of the console's**, shown in the
  console frame the deck keeps (`#cframe`, `deck.html:13419`; `frameLoad`
  13422, `framePoll` 13449). `openTalk` (`deck.html:13990`) hides the other
  sheets, shows `#talk` and calls `talkChat` (14024), which sets
  `wantRead = {chat: "person-<key>", o: {person, prompt, model}}` and polls
  until the frame's `window.lcarsDeckChat(id, o)` (`index.html:21992`)
  answers true.
- The persona (`personaOf`, `deck.html:13944`, from the person's room and
  uniform; `personaPrompt` after it) becomes the thread's `t.pre`: sent
  with the **first message only**, after which `--resume` carries it
  (`index.html` ~31330: `const pre = th.pre; th.pre = ""`).
- The model is per thread (`TALK_MODEL`, haiku for the crew, sonnet for the
  host).
- The frame calls back into the deck through functions the deck puts on
  its window: `lcarsDeckOrder` (an order said in the chat, answered by
  `crewOrderSaid` in the page, never sent to `/chat`), `lcarsDeckLips`,
  `lcarsDeckOpenEntry`, `lcarsDeckSound` (`deck.html:14062` on). **This is the
  door the architect's patches come through**: one more,
  `lcarsDeckPatch`.
- The deck's crew threads take no files: `chatTakesFiles = t => !!t &&
  !t.nav && !t.person` (`index.html:30514`).

### 1.2 The navigator's pattern (the closest thing to what is wanted)

The course sheet's navigator (`index.html`, "plot a course",
ARCHITECTURE.md "Plot a course") changes a trip plan while the captain
watches. In `chatSend` (31261; the navigator at ~31325-31345):

- **Context, rebuilt each message.** `body = crsNavBrief(id) +
  crsNavPast(msgs) + crsNavWhere() + crsNavTrack() + crsNavState() + q`
  and `th.sid = null`: every order is a fresh conversation carrying the
  brief (`crsNavBrief`, 37761: the format, the rules), the thread so far as
  a capped transcript (`crsNavPast`, 37815), where and when the captain
  is, the recording, and the plan as the page holds it (`crsNavState`,
  37781), saved first so what the agent reads is what is on screen.
- **The change comes back as a fence, and the page applies it.** The brief
  tells the agent *not* to write the entry ("no lcars-cli set, add or
  rm") and to end with ```` ```json trip ```` holding the whole new plan.
  `navRevise` (37892) finds the last fence (`crsNavPlan`, `CRS_ANS_FENCE`),
  and `crsRevise` writes it as the page: a new entry, the old one
  soft-deleted, a toast with Undo, a line appended to the answer saying
  which entry is now the plan. If the agent wrote the entry anyway,
  `navRevise` notices (`e.content !== before`) and takes that.
- So: **the page owns the write; the agent proposes in a fixed format;
  the page validates, applies, keeps an undo.** The architect copies all
  three.

### 1.3 Files in a message (the screenshot's road)

- `POST /chat/media` (`lcars_media.h`, `HandleChatMediaUpload`) stores a
  file under `media/chat/YYYY/MM/` and answers `{path, url, name, mime,
  bytes}`. The page uploads with `chatMediaSend` (XHR for progress).
- `POST /chat` takes `attachments` (`ChatAttachmentsParse` checks each path
  is a regular file under `media/chat/`, at most 20); the server puts one
  line per file at the head of the message: `Attached file: <absolute
  path> (<name>, <mime>, <size>)`. The agent opens it with **Read**,
  allowed only as `Read(//<root>/media/chat/**)` (`lcars_chat.h` head).
  Claude reads a PNG or JPEG as an image.
- An engineer gets the same attachments typed as path and URL lines
  (`/engineer/<name>/say`).

### 1.4 Server push

- `GET /events` (`lcars_events.h`): a watcher thread reads the SQLite
  file's change counter and the WAL's size once a second
  (`EVENTS_POLL_MS 1000`) and sends `data: {"seq":N}` on every change;
  heartbeat 15 s, end at 30 min, at most 8 streams.
- `index.html` listens (`evStart`, 8163; `pushSync`, 8216, debounced 700 ms
  through `pushSoon`, then `deltaSync`). **It does not listen inside the
  deck's frame**: `evStart` returns when `inDeck()`.
- **The deck does not listen at all.** It catches up with
  `refreshJournal` (`deck.html:595`: the same two `/dump` questions) every
  120 s and on focus (14900). So today a change written elsewhere reaches an
  open deck in up to two minutes; through `/events` it would be ~1-2 s
  (the poll second, the debounce, the dump).

### 1.5 The crew roles and `crew.py`

`crew/<role>.md` (front matter: schedule, model, verbs, budget; then the
prompt) run unattended by `scripts/crew.py`, each leaving one entry a run;
the console's chat with a role is `/chat` with the role's context on the
first message (`crewRoleContext`, `index.html:38363`). Scheduled roles are
the wrong shape for the architect (it is a conversation, live, on demand),
but the **file convention is right for its brief**: `crew/architect.md`
holds the prompt and the API reference, served to the page through
`engineer.py brief` as the console's role chats already are
(`test_brief.py`), so the reference is edited in one place and versioned
with the code that implements it.

### 1.6 The engineers

`lcars_engineer.h` + `scripts/engineer.py`: a full Claude Code session per
engineer in a git worktree, deploying through `engineer.py deploy` (rebase,
web suite, merge, rebuild, push). A fix takes 2-6 minutes of their time, a
feature 10-30, plus the seat's queue and the deploy's ~3-5 minutes. That is
**too slow for "make this table round"** and the wrong tool (a git commit
per armchair), but it is the architect's **fallback** when a change is
beyond a patch (a new kind of room, a model that is not in the library, a
shader) and the **baker** (section 2.7).

### 1.7 The holodeck: a recipe the deck already builds and undoes

`holoPrompt` (`deck.html:14321`) asks `/chat` for a JSON scene,
`holoClean` (14351) clamps it (types from `HOLO_TYPES`, numbers in range,
colours real colours), `holoBuild` (14495) builds it as one
`userData.dynamic` group, and `holoEnd` (14446) undoes it exactly:
removes the group, disposes its geometry and its own materials (never a
`shared` one), shows what it hid, restores the room's light from the copy
it kept. **That is the undo discipline every patch needs**, already written
once.

### 1.8 How the deck is built, as far as a patch cares

- **Rooms.** Deck 8 is built by hand (`buildShip`, 3331); its rooms are
  zones named "Main bridge", "Ready room", "Ten Forward", "Observation
  lounge", "Arboretum", "Stellar sciences", "Sickbay", "Concourse"
  (`DECK8_DESTS`, 7932; `CORR_DOORS`). Every other room is generated:
  `planDeck(n)` (7491) seeds a deck's plan, `roomName` (7433) names each
  room ("Holodeck 4", "Conference room 12-347", "Lt Okafor's quarters"),
  `genRoom` (6281) records it in `genRooms` and its zones carry `{room:
  rec}`, `buildRoom` (6300) builds it within `BUILD_R` and `unbuildRoom`
  (6313) drops it past `DROP_R`, taking everything registered under its
  `owner` with `disown` (2452). A room is the same room on every visit
  (seeded), and its identity is **deck number + generated name**; names
  the captain gives go through `shown()` only. `hereName()` (1540) is
  "where am I" by `zoneAt(player)`.
- **Objects have no names.** Builders (`chair`, `sofa`, `lamp`, `rbox`,
  `box`…) make anonymous meshes. What does have an identity:
  - **model placements** (`model(at, room, prop, {rot, scale})`, 3018):
    `room/prop` in `modelPlaces`, e.g. `tenforward/…`, `readyroom/
    brass_vase_03`, `readyroom/carved_wooden_elephant`;
  - **seats** (`seatable`, every part carries the record), **light spots**
    (`light()`, 2793: `{p, color, intensity, dist}` with its owner),
    **dressing groups** (`dressGroup`, 2941), **zones**, **work spots**,
    **crew** (`roomPid`).
- **The library of models** is `lcars-ui/deck/<glb>.glb` + three webp
  each: `arboretum`, `bridge`, `concourse`, `corridor`, `hull`, `lab`,
  `lounge`, `readyroom`, `sickbay`, `tenforward`; each glb's props are its
  named nodes (`placeModels` takes `doc.scene.getObjectByName(p.prop)`),
  their licences in `deck/LICENSE.txt`. `modelAsset(glb)` (3089) loads one
  once and keeps it (`modelReady`); every room shares it.
- **Almost nothing that stands still is its own mesh.** `mergeStatic`
  (8223) merges deck 8 into one mesh per material and removes the
  originals from their parents (they stay in `pinnable` with their world
  matrices, so the aiming ray still hits single parts); a generated room
  merges per room (`finishCell`); each room's models are **one mesh in its
  atlas** (`placeModels`, 3127). A model's code-built stand-in is
  collapsed in the deck-wide buffer by zeroing its vertex range
  (`hideStandin`, 3046; ranges from `standinRanges`, 3028). Materials
  are shared deck-wide (`M.wood`, `M.leather`…), so a material's colour is
  every wooden thing's.
- **Lights are a pool** (`POOL_N` point lights moved each frame to the
  `lightSpots` that matter, `tickLights`, 2801): changing a spot's colour
  costs nothing and compiles nothing. The fill is `hemi`, eased per room
  from `ROOM_FILL[zone name]` (14838). Shadows are drawn once
  (`renderer.shadowMap.needsUpdate = true` redraws them).
- **The aim.** `updateAim` casts `ray` against `nearPinnable()` (11451) and
  pads; `aim` is the surface hit, `aimPad`, `aimSeat`, `aimHolo`,
  `crewAimed()` the others.
- **The script is a module** (`<script type="module">`, `deck.html:450`):
  nothing in it is reachable from outside except what it puts on
  `window` (`window.__deck`, 14916, for the headless harness).

---

## 2. The runtime patch layer for the deck

A **patch** is one change the captain asked for, applied to the live scene
without rebuilding it, undoable, and replayed at every load.

### 2.1 Three shapes, compared

**(a) Declarative operations** on named objects, like the holodeck's
recipe: `{"op": "move", "obj": "8/Ten Forward/tenforward/table#3", "by":
[0, 0, 0.5]}`, `material`, `light`, `add` (a model from the library),
`hide`, `dress` (replace a room's dressing).

- Safe by construction (the page interprets; `holoClean`-style clamping);
  trivially idempotent (each op has an exact inverse); small; easy for a
  model to get right.
- **Not "anything anywhere".** Every new kind of change ("make the table
  round", "a fountain in the arboretum", "the lights pulse slowly") is a
  new op, which is page code, which is an engineer and a deploy. The
  captain would meet the edge of the vocabulary in his first week.

**(b) JavaScript against a small stable deck API**, run in the page:

```js
// patch arch-0007: a plant by Ten Forward's starboard window
const at = deck.room("8/Ten Forward").point(0.85, 0.2);      // the room's own frame, 0..1
deck.add("plant", deck.model("arboretum", "fern_01", { at, scale: 1.1 }));
```

- As powerful as the page: new geometry (`deck.three` is three.js), a
  shader, an animation hook, anything. "Make this table round" is: hide
  the table, add a `CylinderGeometry` top on its legs in its material.
- The API's verbs **are** the declarative operations, so the common change
  is a line, and the API records every change for undo (2.3): a patch
  written only with verbs is as idempotent as (a).
- Costs: it can throw, hang, leak, or reach past the API. Each has an
  answer below, but none is free.

**(c) The captain's idea: the deck's JavaScript in a journal entry**, edited
by the architect, reloaded by the browser.

- **It does not fit.** `deck.html` is 861,628 bytes; `HTTP_MAX_BODY_BYTES`
  is 512 KB (`lcars_http.h:48`), so the file cannot be written as one
  entry at all, and every change would mean a model rewriting or diffing
  ~15,000 lines through `lcars-cli set --content`.
- **"Reload the entry" is a page reload in all but name.** The deck is one
  module whose top-level state *is* the scene: re-running it means a new
  WebGL context or a teardown of every mesh, the merges, the models'
  fetch, the crew's bones: the boot the captain already waits for, seconds
  on a phone. The magic is that nothing else moves; this moves everything.
- **It forks the code from git.** The next engineer's deploy of
  `deck.html` either ignores the entry (the captain's changes vanish) or
  must merge 15,000 lines of a model's edits by hand. No tests, perf, or
  review ever see it.
- What is right in it, and kept: **the change lives in the journal**, so
  it syncs, the captain can read it, soft-delete and restore it; and **the
  architect edits it, the browser reloads it**. Only the unit is wrong:
  not the file, a patch.

**Recommendation: (b), JavaScript patches, against a deck API whose verbs
are (a)'s operations.** The prompt asks for verbs first and raw three.js
only when no verb does it; the page checks nothing about the code (it
cannot), but the API makes the safe way the short way.

### 2.2 Safety: what `eval` means here

Plainly: **a patch is code the captain's browser runs with everything the
page has.** The deck is same-origin with the console, so a patch can read
`lcars.cfg` from localStorage: the API password, and the deck's
`X-LCARS-Engineer-Key`, which with the password reaches the engineer
routes, which are a shell on the VPS. So "who can write a patch" must be
read as **"who can run a shell on the VPS"**, and the design has to keep
that set to the captain and his own crew.

What keeps it there:

1. **The limited logins cannot.** Number One's and the crew's logins write
   only their own kinds (`lcars_logins.h`); the patch kinds are the app's
   own, so they are refused there already.
2. **The journal's chat agents could, through the captain's login.** Every
   `/chat` agent writes as the captain and searches the web; a page found by
   a search could tell the computer to `lcars-cli add --kind deck_patch`
   something. So **the server refuses a write of the patch kinds that does
   not carry `X-LCARS-Client`** (the page sends it on every request;
   `lcars-cli`, the agents' only tool, sends none: `lcars_cli.c` has no
   such header). The architect never needs `lcars-cli` to write (2.4), so
   nothing legitimate is lost. An engineer with `curl` can still write one:
   engineers already have the shell.
3. **The page runs a patch only from its own kind**, by the API (below),
   and shows every patch it has not seen before on this device in the
   architect's list with who wrote it, so nothing runs unseen twice.

Not a sandbox: a patch could be put in an iframe or a worker, but then it
cannot touch the scene, which is the point. This is a single-user app; the
risk is a confused or injected agent, and the answer is to keep agents that
read the web from writing patches, not to pretend the code is contained.

### 2.3 Idempotence and undo

Each patch has an id (`arch-0007`). Applying it runs its code with a
`deck` object **bound to that id**: every verb records its inverse on the
patch's undo list, every object it adds is owned by the patch. Applying a
patch that is already applied first undoes it:

- **added objects** are removed and disposed (geometry not
  `userData.shared`, materials not `userData.keep`: `holoEnd`'s rule);
- **changed properties** (position, rotation, scale, a material's colour, a
  light spot's colour and intensity, `ROOM_FILL`, `visible`) are restored
  from the value saved at the first change;
- **lifted objects** (2.5) are put back into their merged buffers;
- **registrations** (a `block`, a seat, a light spot, a ticker the patch
  added) are taken out the way `disown` takes out a room's: the patch id is
  their `own`.
- **raw additions**: anything a patch adds to `scene` outside the API is
  caught by comparing `scene.children` before and after its run, and owned
  by it; a patch that mutates raw state the API cannot see must give
  `deck.onUndo(fn)`, and the prompt says so.

Undo runs in reverse order of the changes. A patch undone and applied
again leaves the scene byte-for-byte as one apply would (the test, 7).

### 2.4 Ordering, load and live

- Patches have a **sequence** (`seq` in the entry; new ones get the
  highest + 1) and apply in that order at load and live.
- **Revising patch k** (the captain: "a bit smaller") undoes the patches
  from the last back to k, applies the new k, then re-applies k+1..n. They
  are milliseconds each; correctness beats cleverness.
- **Scoped to a room.** A patch names its room (`8/Ten Forward`,
  `12/Holodeck 4`) or `null` (the ship: the corridor's colour, the sky).
  A deck 8 room's patches apply at boot. A generated room's patches apply
  **when the room is built** (`buildRoom`) and are undone when it is
  dropped (`unbuildRoom`), under the room's `owner`, so a patch to a room on
  deck 12 costs nothing on deck 8.
- **When at load: after the models land, not before the first frame.** The
  deck shows the ship from code before any model (`loadModels` runs after
  the boot), and a patch that moves a model's table needs the table's glb.
  So a room's patches apply in the frame its models are placed
  (`placeModels` returns; for a cell, `cellModels`' `place`), and a patch
  that touches no model in a room whose models are already in applies
  immediately. The captain may see the original for the second the models
  take on a cold load: the same second the stand-ins already show.

### 2.5 Lifting: how a merged object moves

"Move this table" cannot move a mesh: the table is ranges in two merged
buffers (its model in the room's atlas mesh, its collapsed stand-in in
the material merges). A patch therefore **lifts** it:

1. **Record ranges for models too.** `placeModels` already knows each
   placement's geometry; it records `[mesh, start, count]` per placement
   on the placement (as `standinRanges` does for stand-ins), and stamps
   every stand-in part with the placement's name (as `seatable` stamps
   every part with the seat: the merge takes them out of their group, so a
   parent walk will not find it later).
2. **Lift** = copy the placement's vertices out of the room's merged mesh
   (kept for the undo), zero the range (`hideStandin`'s technique,
   `addUpdateRange`, no rebuild of the buffer), and add a mesh of its own,
   `userData.dynamic`, from `floatGeo(src.geometry, …)` of the kept glb, in
   the room's atlas material. Its stand-in parts in `pinnable` move with
   it (their `matrixWorld` updated, `userData.ws` and `pinVer` reset so
   `nearPinnable` sees them), so aiming and sitting follow.
3. **Unlift** (undo) writes the kept vertices back and drops the mesh.

A lifted object is **+1 draw call** until it is baked (2.7): fine for
the handful a room's patches touch, and the perf budget is the deck's own
(deckshots), not the console's.

What lifting leaves for phase 2: **footprints**. A builder's `block()` is
not linked to its prop, so a moved table's old footprint still stops the
walker. Phase 2 adds `prop(name, fn)`: the builder's call wrapped like a
room's `owner`, recording the blocks, seats, lights and stand-in parts
registered inside it; then a lift moves them too, and code-built props get
names (2.6) as models already have.

### 2.6 Names: the scheme the architect and the page share

- **Room**: `<deck>/<generated name>`: `8/Ten Forward`, `8/Main bridge`,
  `25/Mess hall`. The captain's own names (`place.names`, `shown()`) are
  given beside it as the label, never as the key, so a rename does not
  orphan a patch.
- **Model placement**: `<room>/<glb>/<prop>#<n>`, n counting that prop's
  placements in that room in build order (deterministic: builders are
  seeded): `8/Ready room/readyroom/brass_vase_03#1`. Label: `brass vase
  03 (1)`.
- **Light**: `<room>/light#<n>` (its spots by owner, or by `zoneAt` of `p`
  on deck 8); **the fill**: `<room>/fill`.
- **Seat, dressing, surface**: phase 1 reports what the hit already says:
  a seat; a dressing group; else the surface's material by name (a reverse
  lookup of `M`: `wood`, `leather`, `wallCorr`, `carpet…`) and the room,
  e.g. "the floor (carpet) of Ten Forward". Phase 2's `prop()` names
  code-built props (`8/Ten Forward/table#3`).
- **A patch's own objects**: `<patch id>/<name>` (`arch-0007/plant`), so
  a later patch can address them.

### 2.7 Errors, and baking

- **A patch that throws** is undone at once (its undo list holds what it did
  up to the throw), the scene is as it was, and the error (message, the
  line within the patch, the names it touched) goes back to the architect
  (4.5). It is never written to the journal (2.8: kept only once it
  applied).
- **At load**, a kept patch that throws is skipped and marked failed on this
  device (the architect's list shows it red with the error); later patches
  still apply.
- **A patch that hangs** (a loop) freezes the page, and catching that from
  the same thread is impossible. So before running each patch at load the
  page writes its id to `sessionStorage` and clears it after; a load that
  finds an id there skips that patch and says so. And `deck.html?nopatch`
  boots with no patches, the kill switch.
- **Baking.** Patches accumulate; each costs a little at load and a lifted
  object a draw call. An engineer **bakes** them: moves the change into the
  builders (a placement's numbers, a new `model()` call, a light's colour),
  and adds the patch ids to a `DECK_BAKED` set in `deck.html`; the page
  skips a baked patch. That ordering matters: if the patch entries were
  disabled in the journal instead, a deploy and the journal would race
  (the new page with the patch still on would apply it twice: two plants).
  After the deploy the entries can be soft-deleted at leisure.
- **Management**: the architect's sheet lists the room's patches (title,
  who, when, applied or failed) with a switch each (disable: undo now, and
  `on: false` in the entry) and a delete (soft: restore brings it back).
  The console lists them too, as entries of their kind.

### 2.8 The entry

Kind **`deck_patch`** (the app's own kind, like `space` and
`holo_program`; generic, per docs/design/open-source.md and kinds.md).
Title: the one sentence of what it did ("A fern by Ten Forward's starboard
window"). Content, JSON:

```json
{"v": 1, "id": "arch-0007", "seq": 7, "room": "8/Ten Forward", "on": true,
 "code": "const at = deck.room(…)…", "says": "Added a fern by the starboard window.",
 "by": "architect", "asked": "add a plant by that window", "api": 1,
 "replaces": null}
```

`api` is the deck API's version the patch was written against; a page
whose API has moved past it in a breaking way skips it and says so (it
should rarely move: the API is the stable surface, which is its point).
`replaces` names the patch a revision replaced (the old entry kept,
soft-deleted, as the navigator keeps old plans).

---

## 3. Where patches live, and how a page hears of one

**Journal entries, not files on the server.** CLAUDE.md's rule ("state the
captain or the crew should see lives in the journal"), and every reason
holds: they sync to every device through the mirror, they soft-delete and
restore, the captain can read and edit one in the console, and no new
route or file is needed. Files would need a route, would not be in the
mirror for an offline deck, and would be outside the journal's
undo. Size is no issue: a patch is lines, not the file.

**How the page learns of one within a second:**

- **The asking page needs no push at all.** The architect's answer streams
  into the console frame; when its patch fence closes, the frame hands it
  to the deck (`lcarsDeckPatch`), which applies it *then*, before the
  answer's last sentence has arrived, and only after it applied does the
  frame write the entry. Latency from fence to change: the apply itself
  (milliseconds; a model from a glb not yet loaded, ~0.3-1 s).
- **Every other open deck** (the laptop beside the phone, a second tab)
  and a patch written elsewhere (an engineer's, the console's switch):
  **the deck listens to `GET /events`**, as index.html does (`evStart`'s
  code, a copy in the deck: the deck is a module and borrows nothing),
  runs `refreshJournal` on a new `seq`, and for each changed `deck_patch`
  row re-applies from that patch onward (2.4). ~1-2 s (the watcher's
  second, the dump). The frame inside the deck keeps not listening
  (`inDeck()`), so a deck is one stream of the 8.
- **At load**: every `on` patch not in `DECK_BAKED`, by `seq`, each when its
  room is built and its models are in (2.4).
- `?demo` keeps patches in localStorage beside its place, as it keeps pins.

---

## 4. The architect as a crew member

### 4.1 Where it sits

Not a person to walk to. The captain says "make **this** table round" while
looking at the table; turning to face a crew member to say it would turn
him away from what he means. So the architect is **a sheet, opened from
anywhere**: a key (one free in `deckboot.js`'s list), a touch pill, the
voice order "architect, …" (a `DVCMDS` line: the deck's rule, every key and
pill has an order), and the menu. The sheet is the talk sheet's frame in a
mode of its own: the console's thread `arch` (one thread, the architect's,
for the whole ship), with no person under it, the crosshair kept visible
and the sheet narrow (on a phone, the bottom third), because the scene is
what he is talking about.

Difference from the crew's chats: the crew are people (a persona, a body,
lips); the architect is a role (a brief, no body). It may later be given
one (a hologram that appears where it works, the EMH's way), as polish.

### 4.2 Its brief (`crew/architect.md`)

Sent as the thread's `pre` on the first message, through `engineer.py
brief architect` as role chats do (`test_brief.py`); `--resume` carries it,
so the architect remembers what it did in the conversation. Contents:

- **Who**: the ship's architect; changes the 3D ship live with patches;
  reads the context block and the screenshot, never guesses a name.
- **The patch format**: end the answer with exactly one ```` ```js
  deck-patch ```` fence, its first line a comment `// <id or new>: <one
  line>`; to revise a patch the captain refers to, reuse its id.
- **The rules**: one change per patch; small (a few lines); verbs before
  raw three.js; names from the context only; no network, no storage, no
  `lcars-cli` writes; never reload; after the fence, one sentence saying
  what changed, in the captain's words ("The table is round now.").
  If it cannot be done with a patch (a new room type, a model not in the
  library), say so and offer to pass it to an engineer.
- **The API reference** (section 9), generated from the API's own table so
  it cannot drift: the page's `DECK_API` object has a `doc` string per
  verb, and `deckboot.js` checks `crew/architect.md`'s reference matches it.

### 4.3 Its tools

The `/chat` agent as it is: `lcars-cli` (it only reads), WebSearch, Read on
`media/chat/` (the screenshot). It needs nothing else: **the page is its
hands and eyes.** Everything it needs to know about the scene is in the
message; it changes the scene by answering. Its turn is a plain `/chat`
turn (sonnet by default; the model chip in the sheet; `CHAT_MAX_CONCURRENT`
is 2, so the architect and one other chat at a time).

Phase 2 may give it **a look at more of the room** without a new tool: the
page includes the room's whole inventory (every named object, with
position and size) in the first message of a room, and the delta after.

### 4.4 What the page sends with each message

Built by the deck (`lcarsDeckSees()`, called by the frame at Send), ahead
of the captain's words, capped like the navigator's parts:

```
[Where the captain is: 8/Ten Forward ("Ten Forward"), at (9.1, 0, -18.4) m in the room's frame
 (x across from the door's left, z from the far wall), eye 1.62 m, standing; looking 212° (toward the
 starboard windows), 8° down. Under the crosshair, 2.3 m away: 8/Ten Forward/tenforward/table#3
 ("table 3", a model, top at 0.74 m). In view, nearest first: table#3, chair#7, chair#8, window wall,
 8/Ten Forward/light#4 (warm white). Device: phone, 390x844, graphics low.
 Live patches in this room: arch-0005 "Darker carpet", arch-0007 "A fern by the starboard window".]
Attached file: …/media/chat/2026/10/deck-…jpg (what the captain sees, image/jpeg, 142 KB)
make this table round
```

- **The screenshot**: the canvas as a JPEG at ≤1024 px wide (~100-200
  KB), captured in the frame loop right after `renderer.render` /
  `composer.render` in the same task (the drawing buffer is cleared only
  after the task, so `preserveDrawingBuffer` is not needed and costs
  nothing the rest of the time), with the crosshair drawn on it. Uploaded
  with `chatMediaSend` as the bubble goes up, attached as `attachments`;
  `chatTakesFiles` admits the `arch` thread.
- The deck sends the aim **frozen at Send**: the captain may turn his head
  while the architect works, but "this" meant what was under the
  crosshair when he spoke. The frozen target is outlined until the answer.

### 4.5 How the architect learns whether its patch applied

In-band, no entry: the page that applied it knows at once.

- **Applied**: the frame appends to the answer, as `crsRevise` does, one
  line: "Applied as arch-0008." The next message's context opens with
  `[Your last patch arch-0008 applied.]`.
- **Failed**: the frame **sends the error back automatically, once**:
  `[Your patch failed: TypeError: deck.obj("…/table#9") is not in this room
  (line 2). The scene is unchanged. Fix it.]`, shown in the thread as a
  small system line, not as the captain's words. If the second try fails
  too, the captain sees both errors under the answer, with Retry.
- A patch applied at load that fails on another device is not the
  architect's to hear about live; it shows in the list (2.7) and is in the
  next room's context ("arch-0003 failed here: …").

---

## 5. The latency budget

| step | time | what the captain sees |
|---|---|---|
| Send (key, tap, voice) | same frame | his words as a bubble, "sending…"; the target outlined; the architect's mark pulsing on the HUD |
| screenshot + upload | 0.2-0.6 s | the bubble's file bar |
| `/chat` turn: spawn, Read the image, think, write | **10-30 s** (the floor; voice turns measured 5-7 s with no image) | "the architect at work", its first words streaming |
| patch fence closes → apply | **< 1 s** (ms of JS; a glb not yet loaded 0.3-1 s; a shadow redraw one frame) | the change, with a brief shimmer on what changed (a transporter-like fade over 0.4 s, not a jump) |
| the closing sentence | ~1 s more | "The table is round now." (spoken with Voice on), and an Undo chip |
| the entry written | ~0.2 s, after | nothing: it is already there |

The turn is the floor and is the model's; the design's job is that
**everything after the fence is under a second** and nothing before it is
silent. Two things shorten the floor: the brief asks for the fence
**first** and the sentence after (so the change lands before the prose),
and the patch is applied as soon as its fence closes in the stream, not at
the turn's end. Haiku is faster and worse at 3D; the chip lets the captain
choose; sonnet is the default.

---

## 6. The web app: the same layer for `index.html`

### 6.1 What is different

`index.html`'s main script is a **classic script** (`<script>` at
`index.html:4525`, not a module), and that decides what "hot code reload"
can mean:

- **Top-level `function` declarations are properties of `window`.** A
  patch that assigns `window.chatDraw = function (…) {…}` replaces it for
  every caller that calls it by name (`chatDraw()` looks the name up at
  each call): real hot reload of a function, no state lost.
- **Captured references keep the old one**: `addEventListener("x", fn)`,
  `VCMDS`'s and `KEYS`' `fn:` fields, `onclick = fn`, timers. A patch must
  re-register those (the registry, below, does it for its entries).
- **Top-level `const`/`let`** (state like `st`, `chats`, `crs`, and every
  `const f = () => …`) are visible to a patch (global lexical scope is
  shared by classic scripts) but a `const` cannot be reassigned. So
  functions declared as `const` arrows cannot be hot-swapped; state can be
  read and mutated, never rebound.
- **Closures cannot be reached at all**: what lives inside a function's
  scope stays as it is until the page reloads.

So **hot reload here means: replace named functions, add or replace CSS,
add views and settings through a registry, and re-run a view's draw.** It
does not mean editing a closure, changing a `const`, or migrating state.

### 6.2 The layer

Kind **`ui_patch`**, the same entry shape (`room` replaced by `scope`:
`"page"` or a view's name), the same apply/undo discipline:

- **CSS patches**: a `<style data-patch="<id>">` element, replaced on
  revision, removed on undo. Most "make this bigger / warmer / tighter"
  asks are this, and they are perfectly safe to replay.
- **JS patches against `lcarsUi`**, a registry: `ui.replace("chatDraw",
  fn)` (saves the original for undo, re-registers its known captured uses),
  `ui.view(name, {open, draw})`, `ui.key(...)` and `ui.voice(...)` (a `KEYS`
  entry and a `VCMDS` line together, the standing rule), `ui.setting(...)`,
  `ui.redraw(view)`. Raw page access is there; the undo rule is the deck's.
- **Context**: the computer's chat gets the open view, its url, the
  selection, the viewport and a screenshot (html-to-canvas is too heavy;
  the phone's own screenshot attached, or none: the view's name and the
  element under a long-press carry most of it).
- **Risks particular to the console**: it is the tool to undo a bad patch
  (so `?nopatch`, the deck's list, and `lcars-cli` setting `on: false` from
  a terminal are the ways back, and the hang sentinel of 2.7 applies), and
  perf.py's 60 fps never sees a patch (baking is how it does).

### 6.3 The smallest useful version

CSS patches only, in the console's computer chat ("make the task list's
rows tighter"), live through the same fence-then-apply, kept as `ui_patch`
entries, replayed at boot before the first paint (a style element costs
nothing). Then function replacement. Then the registry.

---

## 7. Phases

### Phase 1: the smallest magic (one room, three kinds of change)

Scope: deck 8's rooms; **move/turn/scale a model placement, tint it, add a
model from the library, change a room's light** (spots and fill); the
context and the screenshot; the live apply; the entries; replay at load;
`/events` in the deck.

- `deck.html`: placement names and model ranges (`placeModels`,
  `model()`); the aim's name (`lcarsDeckSees`); the screenshot
  (`lcarsDeckShot`); `DECK_API` v1 (`room`, `obj`, `model`, `light`,
  `fill`, `move`/`turn`/`scale`/`tint`/`hide`, `add`, `onUndo`, `three`)
  with its undo journal and lifting (2.5); `lcarsDeckPatch` (apply,
  revise, undo); replay at load after `placeModels`; the hang sentinel and
  `?nopatch`; the sheet, its key, pill and `DVCMDS` order; an `/events`
  listener.
- `index.html`: the `arch` thread (like `nav`: its kind, title, the
  context block from the deck, the screenshot attached, `chatTakesFiles`),
  the fence found as it closes in the stream (`dockLiveCut`'s place), the
  hand-off to the deck, the entry written after, the automatic error turn,
  "Applied as …"; a voice order and a palette row to open it.
- `crew/architect.md`: the brief and the API reference.
- `lcars_http.h`: the patch kinds refused without `X-LCARS-Client` (2.2);
  `test/logins.py` gains the lines.
- Tests: `deckboot.js` (the API on the stand-ins: a patch applied, undone,
  applied again leaves the scene's arrays as before; a throwing patch
  leaves them unchanged; the reference matches `DECK_API`);
  `test/architect.py` (new, ~1 min): `deck.html?demo` in headless Chromium
  with a stand-in `/chat` streaming a fenced patch: the change applied
  before the stream ends, kept in localStorage, replayed on reload,
  revised, disabled; a failing patch's automatic second turn;
  `?nopatch`; deckshots of Ten Forward before and after one patch (calls
  +1, the lift).
- Size: three engineer features' worth, about **60-90 minutes** of an
  engineer's time, best as two orders (the deck's layer and its tests; the
  chat side and the server guard).

### Phase 2: the whole deck, and the console's CSS

- `prop(name, fn)` in the builders: code-built props named, their
  footprints, seats and lights moving with a lift (2.5); "make this table
  round" for a code-built table.
- Generated rooms: patches applied in `buildRoom`, undone in
  `unbuildRoom` (under the room's owner).
- More verbs: materials (a per-object clone), `dress` (a room's dressing
  replaced), animation hooks (`deck.tick(fn)`), sky and fog.
- The room's inventory in the first message of a room.
- `index.html`: `ui_patch`, CSS first, then `lcarsUi.replace`; the same
  thread on the console's computer chat.
- Tests: `test/architect.py` grows a generated room and a UI CSS patch;
  `run.sh` (behaviour) gains the registry's undo; perf untouched (patches
  off in perf.py).
- Size: **2-3 hours** of engineer time over several orders.

### Phase 2, as built: the deck's half (Number One's order of 2026-10-30)

- **Code-built props** (`prop(name, fn)`, beside `model()` in deck.html).
  The builders that make one piece of furniture (`chair`, `table`, `sofa`,
  `lamp`, `bench`, `ringBench`, `bookcase`, `plant`, `padShelf`,
  `deskChair`, `officeDesk`, `bed`, `biobed`, `surgicalBed`,
  `instrumentTray`, `cabinet`, `microscopeStation`, `wallConsole`) are
  wrapped once where they are declared (`chair = propped("chair", chair)`,
  before any is called), so no builder's body changed. A record keeps the
  group, its meshes (each stamped `userData.prop`), and what was
  registered while it ran: its `block()`s, light spots and work spots
  (seats are on the parts already). A builder inside another is the
  outer's. `standinRanges` records each part's range in the merge, as for
  a stand-in. Names `<deck>/<room>/<name>#<n>` (`nameProps`: deck 8's after
  `mergeStatic`, a cell's at the end of `finishCell`, counted per frame in
  build order; `dropProps` in `dropCell`). A prop a placement stands over
  is not named: the placement is (`propRec` on it, its footprint and
  lights moving with the model's lift). 49 of deck 8's 112 props are named
  that way; a wing lab has 8.
- **Lifting one** (`propLift`): its merged ranges zeroed and kept, its
  unmerged meshes `attach`ed to a group of its own, its merged parts copied
  into that group merged again by material (a chair of leather and metal:
  two calls until baked). `regsFollow` lays its footprints (from the
  rectangles as built, through the move, so nothing drifts), light spots
  and work spots again on every change; hidden, the footprints are empty
  rectangles, the lights dark, the parts out of `pinnable` (no seat in a
  hidden sofa). `propUnlift` and `regsBack` put all of it back.
- **Scopes** (`patchScope`, `patchScopes`): `"8"` (deck 8's rooms and the
  ship's, at boot: `patchLive` as before), `"room:<deck>/<name>"` for a
  generated room (the wings' and every other deck's: `patchRoomUp` from
  `buildRoom` once the cell's `placed` promise settles, `patchRoomDown`
  from `unbuildRoom` before `dropCell`; the patch's `own` is the room's,
  so its ticks go with `disown` too), `"deck:<n>"` for another deck's
  streets (`buildDeck`, `unloadDeck`). Each scope is its own list, so a
  room built applies only its own and nothing else is undone; a room
  dropped while its patch runs has what applied undone at once.
- **The verbs** (API v2; a v1 patch runs as it did): `.material(name |
  fields)` and `.mat()` on an object, `deck.dress(room).clear() / .add() /
  .count()` (the dressing hidden by a flag `tickDressing` honours),
  `deck.tick(fn)` (in `tickers`, stopped if it throws), `deck.sky(id)`
  (`applySky` and back), `deck.fog(hex, k)` (one `FogExp2`, its density
  eased per room in the frame loop, `tickFog`), `deck.materials()`.
- **The inventory**: `lcarsDeckSees({library: true})`, which the console
  asks on the first message in a room, adds "Everything named in <room>":
  each placement, prop and patch object, at x z from the room's middle,
  its size; the room's dressing count; the ship's materials.
- **Tests**: deckboot.js (the verbs applied and undone to the deck's
  arrays, a tick that throws stopped, a wing room's patch applied with
  its room, gone with it, the same when built again); test/architect.py
  (a wing lab walked into: its chair named, the inventory, a patch to it
  kept while the room is down, applied when walked into - the chair
  lifted and hidden, its footprint gone, a round stool in its material,
  two calls - undone when walked away, replayed after a reload, the
  footprint back as built when switched off). Ten Forward's table: its
  footprint moves with it.
- **Measured** (deckshots, the wing lab on graphics low, one patch
  turning its chair into a round stool): the view facing it 68 -> 69
  calls, 290,876 -> 290,948 triangles; the other three views the same
  within the crew's movement. perf.py untouched (the console; the deck
  applies no patch there).
- Left: see TODO.md, "The architect, the rest".

### Phase 3: baking and management

- The list in the sheet and the console (switch, delete, restore, the
  failed ones red); `engineer.py bake`: an order for an engineer with the
  patches' code and names, producing builder changes and `DECK_BAKED`
  ids; the architect offering "bake these" when a room has more than a
  handful.
- `lcarsUi` registry complete (views, settings, keys with voice); a UI
  patch bake the same way (`UI_BAKED`).
- Tests: a baked patch skipped (the page with `DECK_BAKED` and the entry
  still on: applied once).
- Size: **1-2 hours**.

---

## 8. Risks, and questions for the captain

Each with a recommendation.

1. **A patch is code with the API password and the engineer key in reach**
   (2.2). *Recommend*: accept it, with the `X-LCARS-Client` guard on the
   patch kinds so no web-reading agent can write one, and the list showing
   every new patch. Alternative, stricter: the engineer key moved out of
   the deck's localStorage (asked for on Promote only). Captain: is the
   guard enough?
2. **Declarative only, or code?** *Recommend* code against the API (2.1):
   declarative alone meets its edge within a week. Captain: agree?
3. **The whole-file idea** is not possible as stated (861 KB against a
   512 KB body cap) and would fork the deck from git. *Recommend* patches
   in entries, which keep its two good parts (the journal holds the change;
   the browser reloads it live). Captain: content to drop the whole file?
4. **The fence or `lcars-cli`?** *Recommend* the fence (the page applies
   before it saves, so a broken patch is never kept, and nothing waits for
   `/events`). The cost: a patch can only come from a chat in a page that is
   open. Captain: is the architect ever wanted away from the deck (from
   the phone's Shortcut, say)?
5. **A sheet, or a person?** *Recommend* a sheet opened from anywhere (4.1),
   a hologram later as polish. Captain: or do you want to walk to an
   architect's office?
6. **Which model by default?** *Recommend* sonnet, the chip for opus when a
   change is hard. Haiku's speed is tempting and its 3D sense is not.
7. **One ship for all devices.** Patches sync everywhere; a phone on
   graphics low runs the same patches. *Recommend* yes, with the API
   offering `deck.gfx` for a patch that should be lighter on a phone.
8. **Lifts cost a draw call each until baked.** *Recommend* baking when a
   room passes ~10 lifted objects; the architect says so. Captain: fine to
   bake by asking an engineer, or should it be automatic weekly?
9. **The console's hot reload is partial** (6.1: no closures, no `const`).
   *Recommend* CSS first, function replacement second; do not promise more.
10. **Concurrency**: `CHAT_MAX_CONCURRENT` is 2, so an architect turn and a
    crew conversation fill it. *Recommend* leave it; raise to 3 only if the
    captain meets the 429.

## 9. The deck API, v2 (the reference the brief will carry)

This block is `DECK_API_DOC` in deck.html, line for line; deckboot.js
fails when the two differ, so change both together.

```
deck.room(name?)          the room (default: where the captain is); .name, .label, .box, .point(u, v, y?) in 0..1 of its floor,
                          .at(x, z, y?) in metres from its middle (x to starboard, z aft), .objects(), .lights()
deck.obj(name)            a named object (a model placement, a code-built prop, a patch's own); throws if it is not built
  .move([dx,dy,dz]) .moveTo([x,y,z]) .turn(deg) .scale(k|[x,y,z]) .tint("#rrggbb", k?) .hide() .show() .at() .size()
  .material("brass" | {color, emissive, emissiveIntensity, roughness, metalness, opacity})   its own copy, nothing else changes
  .mat()                  the material it is drawn in, for a new part of it in the same
  (each lifts a merged object into a mesh of its own, its footprint, seats and lights moving with it, and records its undo)
deck.model(glb, prop, {at, rot, scale})   a library model (a promise of it), added by deck.add
deck.add(name, object3d) owned by the patch, named "<patch>/<name>", dynamic; a promise of one is awaited
deck.light(name)          a light, or a room's every light: .color("#rrggbb") .intensity(k) .range(m) .warm(k) .cool(k)
deck.fill(room)           the room's fill light: .level(k) .warm(k)
deck.dress(room?)         the room's dressing (small things): .clear() hides it all, .add(name, object3d) adds to it, .count()
deck.tick(fn)             fn(t, dt) every frame while the patch is on (seconds): animation; one that throws is stopped
deck.sky(id?)             what the windows show: "home" | "nebula" | "ocean" | "galaxy" | "binary"; no id: the list
deck.fog("#rrggbb", k?)   a haze in the patch's room (k 0..0.5, 0.04 light), eased in as the captain walks in
deck.library()            the loaded glbs and their props: {glb: [{prop, size: [w, h, d]}]}
deck.materials()          the ship's materials by name, for .material(name)
deck.onUndo(fn)           for anything raw the API cannot see
deck.three, deck.scene    three.js and the scene, when no verb does it
deck.gfx                  "high" | "medium" | "low"
```
