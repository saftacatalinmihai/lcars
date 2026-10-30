# Engineer voices: the briefs

Number One's order, the captain's (2026-10-27): ElevenLabs voices designed
for the ten most recently active engineers, each in character. 0.341.0 gave
each engineer a voice of their own (`SAY_PERSONAS` in `index.html`, the
`voices` settings entry, `POST /say`'s `style`); this note is what to make
for the ten, and `scripts/voices.py` is how. Nothing is made until Number
One says so: `design` costs credits, `create` takes a voice slot.

**Done (the captain, 2026-10-28):** the ten voices in `SAY_PERSONAS` are as
the captain tested them. Moreau's designed voice and a voice chooser in
the chat are not planned.

## The account (2026-10-27, `voices.py account`)

| | |
|---|---|
| plan | free |
| voice slots | 2 used of 3: **one** voice can be kept |
| credits | 4,143 used of 10,000 this month, 5,857 left |
| reset | 2026-10-30 02:36 UTC |
| voice add/edits | 2 of 54 |
| voice design | every plan; limited by the credits and the slots |

A design costs its preview text's characters, once for its three previews:
all ten below are 1,965 characters, about a third of what is left, and the
same credits the crew's speech spends until the reset. Keeping ten voices
needs ten free slots: the free plan has one. Starter (10 slots) or above
would hold them, or the two slots in use could be freed.

## As made (2026-10-27)

The captain took Starter, and eight voices for the engineers on duty;
Esposito and Moreau wait (the slots are full: one delete each first).

| | before (Starter, fresh) | after |
|---|---|---|
| voice slots | 2 of 10 | 10 of 10 |
| credits | 0 of 40,000 | 1,004 of 40,000 |
| voice add/edits | 0 of 65 | 8 of 65 |
| reset | 2026-11-27 11:58 UTC | |

The two slots already in use: "Narator" and "Ro FE", both `generated`
voices the captain made before; neither is in the console's
`SAY_VOICES` or `SAY_PERSONAS`. Left alone.

One design each (1,587 characters of preview text; ElevenLabs charged
1,004 credits for the eight). Preview 1 of each was kept, named
`LCARS <character>`; its `generated_voice_id` became the voice's id.
The 24 previews, playable side by side: the Reports page, "Engineer
voices: eight designs, three previews each". The files are in Data's
research folder (`research/data-lqj/voices/`, each label's JSON with the
three ids), so a swap is `voices.py create <the 2nd or 3rd id>` after a
delete on the account, and the new id into `SAY_PERSONAS`.

| key | voice on the account | voice_id |
|---|---|---|
| `obrien` | LCARS O'Brien | `6ijMa1V79cSgKFajQ1MJ` |
| `jake` | LCARS Jake Sisko | `D5jX9uNN2gWmpGT5wjgu` |
| `zimmerman` | LCARS Zimmerman | `NW8z12mbEc5OMACVQnTn` |
| `mendez` | LCARS Mendez | `maqNAqQFaOeQR9UiWrYj` |
| `sato` | LCARS Hoshi Sato | `MvvRmmFIVfFYwEMPohl9` |
| `kim` | LCARS Harry Kim | `jXGs9HQNLAMsGHceIqAi` |
| `okafor` | LCARS Okafor | `yIsaMLKSEBHinbKOp2v3` |
| `laforge` | LCARS La Forge | `e5RaTgzIYa1kZn0EPWCj` |
| `esposito` | LCARS Esposito | `YiahGdOf4Xvr3BfPfcKM` |
| `data` | LCARS Data | `F878ZnHzQZOEg8lM1EYW` (preview 3; preview 1, `6RTULwJNrTgTXBqcMfQk`, kept first and swapped on the captain's word) |

In `SAY_PERSONAS` (index.html) with the styles and backups below.

Later the same day, on the captain's word: "Narator" and "Ro FE" deleted
(`voices.py delete`, the name checked first), freeing two slots; three
more designed - Data's own (until then the premade Eric), Esposito and
Moreau (607 characters of text; the account at 1,817 credits used of
40,000 after) - and Data's and Esposito's preview 1 kept. The slots are
full again (10 of 10): **Moreau waits**, her three previews made
(`research/data-lqj/voices/moreau.json`), to be kept when a slot frees.
Their previews: "Engineer voices: Data, Esposito, Moreau" in Reports.

### Lieutenant Commander Data (`data`)

- **Description** (287 characters): A man in his early forties with a slight General American accent. A light, clear tenor with crisp, exact articulation, even and unemotional, polite and formal, precise measured pacing with no hesitation, every word given equal weight. An android's calm, curious delivery. Studio quality.
- **Preview line** (229 characters): "Captain, I have completed the analysis. The fault was a single misplaced character in line four hundred and twelve. I have corrected it, and the tests now pass. I believe the appropriate human expression is: that was a close one."
- **Style**: stability 0.92, speed 1.05; backup `aura-2-orpheus-en`.

## How

    voices.py design LABEL --description "..." --text "..."   # 3 previews, research/<name>/voices/
    voices.py create GENERATED_ID --name NAME --description "..."   # the voice_id
    # then the `voices` settings entry (or SAY_PERSONAS):
    # {"LABEL": {"elevenlabs": VOICE_ID, "deepgram": AURA, "stability": S, "speed": V}}

The key is the engineer's name's first word (`obrien` for `obrien-c33`),
so the voice follows the character to their next seat. Who the ten are:
`engineer.py list`, by `active`. None has a brief of their own in `crew/`
(those are the scheduled roles'); the canon characters are as the shows
had them, the four from the deck's names (`CHAT_NAMES_F`/`_M`) are given
a voice by their name and the work they did, an accent kept slight.

## The ten

| key | engineer | sex | stability | speed | Aura-2 backup | in a line |
|---|---|---|---|---|---|---|
| `obrien` | Chief Miles O'Brien (`obrien-c33`) | male | 0.55 | 1.0 | `aura-2-jupiter-en` (baritone, expressive) | Colm Meaney's chief: Irish, gruff and warm, the man who keeps it running |
| `jake` | Jake Sisko (`jake-c38`) | male | 0.5 | 1.0 | `aura-2-aries-en` (warm, energetic) | Cirroc Lofton's Jake: young, earnest, a writer more than an officer |
| `zimmerman` | Dr. Lewis Zimmerman (`zimmerman-c39`) | male | 0.4 | 1.1 | `aura-2-hermes-en` (expressive, engaging) | Robert Picardo's Zimmerman: brilliant, impatient, sardonic, fast |
| `mendez` | Lieutenant Elena Mendez (`mendez-c35`) | female | 0.6 | 1.05 | `aura-2-callista-en` (clear, professional) | the deck's own officer: no show to follow; a crisp, composed lieutenant, Spanish by her name |
| `sato` | Lieutenant Hoshi Sato (`sato-c31`) | female | 0.65 | 1.0 | `aura-2-harmonia-en` (clear, calm) | Linda Park's Hoshi: the linguist, precise and careful with words |
| `kim` | Lieutenant Harry Kim (`kim-c32`) | male | 0.55 | 1.05 | `aura-2-atlas-en` (enthusiastic, friendly) | Garrett Wang's Harry: young, eager, earnest, always reporting good news |
| `okafor` | Lieutenant Daniel Okafor (`okafor-c30`) | male | 0.7 | 0.95 | `aura-2-saturn-en` (baritone, confident) | the deck's own officer: calm and measured, Nigerian by his name |
| `laforge` | Lieutenant Commander Geordi La Forge (`laforge-c34`) | male | 0.5 | 1.05 | `aura-2-mars-en` (smooth, baritone) | LeVar Burton's Geordi: warm, resonant, delighted by an engine |
| `esposito` | Lieutenant Ciro Esposito (`esposito-c28`) | male | 0.45 | 1.05 | `aura-2-apollo-en` (confident, casual) | the deck's own officer: warm and animated, Neapolitan by his name |
| `moreau` | Lieutenant Ilse Moreau (`moreau-c29`) | female | 0.7 | 0.95 | `aura-2-cora-en` (smooth, melodic) | the deck's own officer: calm and dry, French by her name |

Stability: lower is livelier, higher steadier (Data is 0.92); speed 1.0 is ElevenLabs' own.

### Chief Miles O'Brien (`obrien`)

- **Description** (208 characters): A man in his early forties with a thick Dublin Irish accent. A warm, slightly gravelly baritone, dry and down to earth, a working engineer's practical brisk pacing with a hint of weary humour. Studio quality.
- **Preview line** (223 characters): "Right, the transporter's back on line. Pattern buffers holding at ninety-eight percent, which is fine, but I'd not put the Captain through it till I've had a look at those coils myself. Give me ten minutes and a cup of tea."
- **Style**: stability 0.55, speed 1.0; backup `aura-2-jupiter-en`.

### Jake Sisko (`jake`)

- **Description** (192 characters): A young man in his early twenties with a slight American accent. A soft, warm, clear tenor, earnest and thoughtful, a writer's easy conversational pacing, a smile in the voice. Studio quality.
- **Preview line** (191 characters): "I was going to write the release notes tonight, but honestly, the story's better than the changelog. The ship learned to talk this week. That's not a feature, Captain, that's a first chapter."
- **Style**: stability 0.5, speed 1.0; backup `aura-2-aries-en`.

### Dr. Lewis Zimmerman (`zimmerman`)

- **Description** (177 characters): A man in his fifties with a slight American accent. A nasal, sharp, expressive tenor, irritable and sardonic, quick clipped pacing that speeds up when impatient. Studio quality.
- **Preview line** (210 characters): "Oh, wonderful. Another build that works on the first try, which in my experience means nobody has tested it properly. Fine. Run the suite again, and this time read the output before you congratulate yourselves."
- **Style**: stability 0.4, speed 1.1; backup `aura-2-hermes-en`.

### Lieutenant Elena Mendez (`mendez`)

- **Description** (172 characters): A woman in her early thirties with a slight Spanish accent. A clear, confident mid-range voice, crisp and composed, warm underneath, even purposeful pacing. Studio quality.
- **Preview line** (174 characters): "The theme's in the journal now, Captain. Change a colour in the entry and the console follows it on every device, no deploy needed. I checked it on the phone twice. It holds."
- **Style**: stability 0.6, speed 1.05; backup `aura-2-callista-en`.

### Lieutenant Hoshi Sato (`sato`)

- **Description** (176 characters): A woman in her late twenties with a slight American accent. A soft, clear, precise voice with careful diction, thoughtful and gentle, measured unhurried pacing. Studio quality.
- **Preview line** (206 characters): "I've gone through the manual line by line, Captain. Every label it names is on the screen, every key does what it says. Where the wording was ambiguous, I chose the plainer word. Translation is mostly that."
- **Style**: stability 0.65, speed 1.0; backup `aura-2-harmonia-en`.

### Lieutenant Harry Kim (`kim`)

- **Description** (167 characters): A young man in his mid twenties with a slight American accent. A bright, light tenor, eager and earnest, a touch quick when excited, friendly and open. Studio quality.
- **Preview line** (198 characters): "Good news, Captain! The cold load is down by almost a third. I moved the report bodies out of the first request, so the list paints before they arrive. I ran it three times to be sure, and it holds."
- **Style**: stability 0.55, speed 1.05; backup `aura-2-atlas-en`.

### Lieutenant Daniel Okafor (`okafor`)

- **Description** (149 characters): A man in his late thirties with a slight Nigerian accent. A deep, calm, resonant baritone, measured and kind, slow deliberate pacing. Studio quality.
- **Preview line** (196 characters): "The mess hall and the classrooms are baked, Captain. Every surface has its light now, so the rooms cost the phone almost nothing to draw. Take a walk through them. I think you will find them calm."
- **Style**: stability 0.7, speed 0.95; backup `aura-2-saturn-en`.

### Lieutenant Commander Geordi La Forge (`laforge`)

- **Description** (172 characters): A man in his late thirties with a slight American accent. A rich, warm, resonant mid-baritone, upbeat and enthusiastic about the work, friendly easy pacing. Studio quality.
- **Preview line** (189 characters): "Captain, you're gonna love this. I got the bridge tiles and the skylight into KTX2, so the textures load in half the time and the GPU barely notices. It looks better, too. Come take a look."
- **Style**: stability 0.5, speed 1.05; backup `aura-2-mars-en`.

### Lieutenant Ciro Esposito (`esposito`)

- **Description** (164 characters): A man in his forties with a slight Neapolitan Italian accent. A warm, animated, expressive baritone, lively and good-humoured, quick musical pacing. Studio quality.
- **Preview line** (192 characters): "Ah, Captain, the floor decals are gone, and nobody will miss them! The shadows do the work now, softer, more natural. Less to draw, less to load. Sometimes the best work is what you take away."
- **Style**: stability 0.45, speed 1.05; backup `aura-2-apollo-en`.

### Lieutenant Ilse Moreau (`moreau`)

- **Description** (142 characters): A woman in her forties with a slight French accent. A low, smooth alto, calm and dry, quietly composed, unhurried even pacing. Studio quality.
- **Preview line** (186 characters): "The gyms, the schools, the hydroponics bay and the holodecks are staffed, Captain. Each crew member has a place and a reason to be there. The ship feels lived in now. That was the point."
- **Style**: stability 0.7, speed 0.95; backup `aura-2-cora-en`.
