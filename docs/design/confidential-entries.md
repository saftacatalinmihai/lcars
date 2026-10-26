# Confidential entries: classification levels, and Secret entries no agent can read

Status: phase 1 built (0.280.0, 2026-10-20): Secret entries in the
console, as section 9's first paragraph; phases 2-5 to come. The captain's
answers to section 10 are recorded there; what phase 1 decided that this
design left open, and the handover, is section 11.

## 0. What is asked, and the threat model

An entry gets a classification level. A **Secret** entry is encrypted and
no agent can read it: not the chat's Claude, not the crew's scheduled
roles, not Number One, not the engineers, not the embedder, not the
Logseq export, CalDAV, the server's search, the public demo, and not
someone holding a copy of `lcars.db`. Only the journal's owner, after
authenticating on a device they use, reads it.

Who the adversaries are, concretely, on a box like this one:

- **Agents with a login.** Number One, the crew, the steward (the limited
  logins, `lcars_logins.h`), and the chat's Claude, whose `lcars-cli`
  carries the **main** login today (`ChatBuildEnv` in `lcars_chat.h`).
- **Agents with a shell as the same user.** Number One and the engineers
  run as the box's user. They can read `~/.env`, so they have the main
  login's password; they can read `lcars.db`, its WAL and every backup.
  Any line the server holds (an access check, a "need to know" flag) is a
  line they can step around. Only cryptography whose key is never on the
  box holds against them.
- **A backup reader**: `lcars_bkp.db`, `~/lcars-personal.db`, a NAS
  snapshot, a copy taken to a laptop.

What this design does **not** protect against, said plainly so nobody
believes otherwise:

- **The page's own code.** Decryption happens in the browser, in code the
  server serves from `lcars-ui/`. An agent who can change that code and
  deploy it (an engineer, Number One) could ship a page that sends the
  password, or the plaintext, back to the server the next time the owner
  unlocks. Encryption moves the trust from "everything on the box" to
  "the code of one page, as reviewed before a deploy". Mitigations are in
  section 7; none is a proof.
- **Metadata** the owner chooses to leave visible (section 3).
- **Copies made before an entry was raised to Secret**: an old backup, a
  Logseq page already written, a CalDAV client that has not synced since.
  Section 4 lists what is cleaned at the moment of raising and what cannot be.
- **Where the owner's own words go while typing**: cloud dictation
  (Deepgram, a browser's speech service) and text-to-speech send the
  words to a third party (section 5f).

## 1. The levels and the columns

Three levels, military style:

| level | name         | stored      | who reads it                                     |
|-------|--------------|-------------|--------------------------------------------------|
| 0     | Unclassified | plaintext   | everyone with a login (today's behaviour)        |
| 1     | Confidential | plaintext   | the main login only; the agents' paths skip it   |
| 2     | Secret       | ciphertext  | nobody on the server; the owner's unlocked page  |

**Confidential** is a line the server holds, not mathematics: the limited
logins see a placeholder, and the embedder, CalDAV, the Logseq export and
the chat skip it. It is for "don't feed this to the agents" without the
unlock's friction. It holds against the agents' *logins*; it does not hold
against an agent with a shell (who has `~/.env` and the db file). The UI
says so in one line where the level is chosen.

**Secret** is the encrypted one, the rest of this design.

Two columns, added the way every column since the table's creation has
been (`lcars_db.h`), so nothing existing changes and every row reads as
Unclassified:

```c
EnsureEntryColumn(db, "classification", "classification INTEGER DEFAULT 0");
EnsureEntryColumn(db, "sealed", "sealed TEXT DEFAULT ''");
```

and a side table for the key material, created on first use like
`entry_media` and `entry_embeddings`:

```sql
CREATE TABLE IF NOT EXISTS vault (
  id INTEGER PRIMARY KEY CHECK (id = 1),  -- one vault per journal
  body TEXT NOT NULL,                     -- the JSON in section 2c
  auth_hash TEXT NOT NULL,                -- hex SHA-256 of the vault token
  version INTEGER NOT NULL,               -- bumped on every write
  modified_at_utc TEXT NOT NULL
);
```

A Secret row keeps `title = ''`, `content = ''`, `value_int` and
`value_float` NULL, and the encrypted envelope in `sealed`. That is the
point of the shape: **every reader that does not know about classification
already sees an empty entry.** `title LIKE ?` never matches, the embedder's
`substr(content, ...)` is empty, a Logseq block would be empty. Nothing
leaks by a reader being forgotten; the explicit skips in section 4 are for
tidiness (no empty VTODO, no dim-0 vector) and for Confidential, which is
plaintext and does depend on every reader checking.

The vault is a table, not an entry, for once against the "state lives in
the journal" rule: it is key material, it must not be in `/dump`, in the
mirror's list, or editable through `PATCH /entries`, and no limited login
may touch it at all.

## 2. Where encryption happens

### 2a. Option A: in the browser (recommended)

The page holds the key; the server stores ciphertext and never sees the
password, the key or a Secret entry's plaintext.

- **Key hierarchy.** A random 256-bit **master key** (MK) per journal,
  made once in the browser (`crypto.getRandomValues`). It is never stored
  bare: the vault holds it *wrapped* (AES-GCM) by a key-encryption key
  derived from the password. Entries are encrypted with MK. So changing the
  password re-wraps one key, not every entry (section 5e), and a passkey
  later is just one more wrap of the same MK (section 6).
- **The password's KDF.** WebCrypto has PBKDF2, not Argon2 or scrypt.
  Phase 1 uses PBKDF2-HMAC-SHA-256, 600,000 iterations (OWASP's 2023
  figure; ~0.5 s on a recent phone), a random 16-byte salt. The vault
  records the KDF and its parameters, so a later move to Argon2id (a WASM
  build, a vendored file) is a re-wrap at the next unlock, not a migration.
- **Telling a wrong password apart.** No separate verifier is needed:
  unwrapping MK is AES-GCM, and a wrong key fails its tag. A stored hash of
  the password would be an offline-guessing oracle exactly as strong as the
  wrap itself, so it adds nothing. The page says "wrong password" on the
  tag failure.
- **Entries.** AES-256-GCM with MK, a fresh random 96-bit IV per write (a
  journal's writes are many orders below GCM's 2^32 random-IV limit). The
  plaintext is a JSON object `{"title", "content", "value_int",
  "value_float"}`; the envelope's header is the additional authenticated
  data, so a header edited by hand fails decryption.
- **The key in memory** is a non-extractable `CryptoKey`: page script can
  use it but cannot read its bytes, and it dies with the tab.
- **The server's part** is small and needs no crypto library for the
  entries: store `sealed`, refuse plaintext on a Secret row, keep the vault,
  skip Secret and Confidential rows where section 4 says. One hash: the
  vault's write guard (2c) is SHA-256, which the server does not have today
  (CalDAV's ETags are FNV-1a). It is ~150 lines of FIPS 180-4 in a new
  `lcars_sha256.h`, tested against the NIST vectors; no new dependency.

Creating a Secret entry, by each door:

- **The console and the deck** (unlocked): the editor encrypts before
  saving; the outbox queues the envelope, never the plaintext.
- **Voice in the console**: "computer, mark this secret" is an order like
  any other; the words of the entry are the cloud-dictation question in 5f.
- **`lcars-cli`, Shortcuts, Reminders, the chat**: they cannot encrypt to
  MK without the password. Phase 3 adds a **write-only** path: the vault
  also holds an ECDH P-256 key pair, the public key in the clear and the
  private key wrapped by MK. Anyone can *seal* an entry to the public key
  (ECDH-ES, HKDF-SHA-256, AES-256-GCM; WebCrypto has all of it, and
  libcrypto, which `lcars-cli` already links through libcurl, does too) and
  nobody but an unlocked page can open it. `lcars-cli add --secret` seals in
  the client, so the plaintext never reaches the server. A Shortcut cannot
  do ECDH; it gets a server route that seals on arrival
  (`POST /entries` with `"seal": true`), which means its plaintext passes
  through the server's memory once, in a request: weaker, documented, and
  an open question whether it is wanted at all.

### 2b. Option B: on the server, with an unlock window

The server holds the vault and the crypto (libcrypto: linked statically in
the release build already, through curl; the dynamic Debian build would add
`-lcrypto`). `POST /vault/unlock {password}` makes the server unwrap MK
and hold it for a window (15 minutes, say) for requests carrying a token
from that unlock; `GET /entries` decrypts for them, and every other request
sees ciphertext.

What it is good at: every door can create *and read* a Secret entry while
the window is open (the CLI, a Shortcut, the chat if the owner lets it),
and the server can search Secret text during the window.

Why it is not recommended:

- The password and every plaintext pass through the server process, on a
  box where the agents are the same user. A deployed server binary that
  logs the password at the next unlock is the same attack as a page that
  does (section 0), with the difference that the server's code is changed
  and rebuilt by agents far more often than one page module would be.
- During the window, the key is in the server's memory: core dumps, an
  ASan build's reports, swap, and any process allowed to ptrace it.
- The window is a time when "no agent can read it" is false for anything
  that can present the token or steal it from the browser.
- It needs OpenSSL in the dynamic build and its checks in
  `scripts/release/check.sh`, for less protection.

### 2c. The vault's write guard (both options)

An agent with the main password could replace the vault with one wrapping
a key of its own; every Secret entry the owner wrote afterwards would be
readable by it. So the vault is only replaced by someone who could unlock
it: from MK the page derives a **vault token** (HKDF-SHA-256, info
`"lcars vault token v1"`); the server stores its SHA-256 (`auth_hash`)
and refuses `PUT /vault` (409/403) unless the request carries the token and
the current `version`. Creating the first vault is the one write with no
token, allowed only to the main login and only when there is none. The
page also pins the vault's fingerprint per device (localStorage) and shows
a red warning if it ever changes outside the page's own writes.

The vault's body:

```json
{"v": 1, "kid": "k1",
 "wraps": [
   {"type": "password", "kdf": "PBKDF2-SHA256", "iter": 600000,
    "salt": "<b64>", "iv": "<b64>", "wrapped": "<b64>"}
 ],
 "seal_pub": null, "seal_priv": null}
```

`wraps` is a list from day one: the recovery code (5g) and each passkey
(section 6) are more entries in it, all wrapping the same MK. The three
kinds as built (0.287.0) are documented as a format in 8a.

An entry's envelope, in `sealed`:

```
lcs1.<b64url of {"kid":"k1","alg":"A256GCM","iv":"<b64>"}>.<b64url ciphertext+tag>
```

and, phase 3, `lcs1s.` for one sealed to the public key (with its `epk`).
The prefix lets every reader recognise one without parsing it.

### 2d. Recommendation

**Option A.** It is the only one where the claim "no agent on the server
can read it" is true at rest, in transit through the server, and while the
owner is reading. The cost is that a Secret entry is born or read only in
the page, until phase 3 gives the CLI and the Shortcuts a write-only door.

## 3. What stays visible for a Secret entry

| field                                   | visible | why                                       |
|-----------------------------------------|---------|-------------------------------------------|
| id, created, last modified, deleted     | yes     | sync, the outbox, the mirror need them    |
| classification                          | yes     | every reader's skip                       |
| kind                                    | yes     | the views, the roles, the logins' gates   |
| start_date, end_date, done_bool         | yes     | the calendar, the rail, tasks             |
| title, content, value_int, value_float  | no      | sealed                                    |
| media (photos, audio, video)            | none    | refused in phase 1 (section 4)            |

**Recommended: kind, dates and done stay visible; the text and the
numbers are sealed.** A Secret row reads in the list as `▮ CLASSIFIED ·
<kind> · <date>` while locked, and with its real title when unlocked. The
kind is the one real leak (`therapy` at 15:00 on a Tuesday says something);
the alternative is to seal the kind too and file every such row under one
`classified` kind, which costs the views and the calendar their sense of
it. That is an open question (Q2).

## 4. Every reader, what it does, and the test that proves it

"Skip" means the row is left out; "placeholder" means it is returned with
its sealed fields empty and `classification` set.

| module / path | Secret | Confidential | proven by |
|---|---|---|---|
| `lcars_http.h` `GET /entries`, `/entries/<id>`, `/dump` (main login) | the row with `sealed`, title/content empty | the row, plaintext | new `test/classified.py` |
| same, a limited login (Number One, crew, steward) | placeholder, **no `sealed`** | placeholder | `test/logins.py` + `classified.py` |
| `GET /entries?q=` (`title LIKE ? OR content LIKE ?`) | never matches (empty columns) | matches for the main login only | `classified.py` |
| `POST`/`PUT`/`PATCH /entries` | a Secret row takes only an `lcs1` envelope and empty title/content/values, else 400; lowering takes plaintext with `sealed: ''` | as today | `classified.py`, `test/api.py` |
| `POST /entries/<id>/append`, `/title`, `/end` | 409 on a Secret row (append and title would write plaintext into it; end is metadata and allowed) | refused to the limited logins | `test/logins.py` |
| the steward (`StewardMayWriteKind`, crew notes) | cannot append to or retitle a Secret row (409 above); may create Unclassified only | may not read, so may not edit | `test_crew_notes.py --real` |
| raising a level (the write that sets 1 or 2) | in the same transaction: delete its `entry_embeddings` row, its `caldav_tasks` row (CalDAV sees it gone), then a WAL checkpoint; `PRAGMA secure_delete = ON` for the server's connections so the old text's pages are zeroed | same, without the checkpoint | `classified.py` reads the db file's bytes for the old text |
| `lcars_embed.h` indexer | `WHERE classification = 0` | same | `classified.py` with a stand-in embedder: nothing sent |
| `lcars_embed.h` `GET /embeddings` | no vector | no vector | same |
| `POST /embed` (the page's "related") | the page never sends a decrypted Secret text | the page never sends it | QuickJS suite |
| `lcars_caldav.h` (VTODO lists, sync tokens) | skipped, as if deleted | skipped | `test/caldav.py` |
| `lcars_logseq.h` export (`lcars-cli logseq export`) | skipped | skipped | a stand-in Logseq API in `classified.py` |
| `lcars_chat.h`: the chat's context and its `lcars-cli` | empty to it already (ciphertext); the page puts no decrypted entry into a chat | the chat must get a login of its own (phase 2): today it carries the main one | `test/chat_media.py` stand-in claude |
| `lcars_media.h` uploads to an entry | 409 in phase 1 (files on the NAS are plaintext); raising an entry with media refused; phase 4 encrypts files in the page | allowed, served to the main login only | `test/recording.py`, `classified.py` |
| `lcars_say.h` `/say` (TTS), `/transcribe` | the page does not read a Secret entry aloud; dictation into one per Q5 | as Unclassified | `test/speech.py` |
| `lcars_metrics.h`, `lcars_kinds.h` counts | counted by kind (metadata only) | same | `test/metrics.py` unchanged |
| `lcars_events.h` | only a sequence number, never content | same | nothing to do |
| `scripts/crew.py`, `crew_tool.py`, `shares.py`, `lcars_linker.py`, `no1.py` | read through the limited logins: placeholders; the linker skips rows with no title | same | `test_crew.py`, `test_linker.py` with a placeholder row in the stub |
| `scripts/db-merge-window.py` (copies rows back through the API) | must copy `classification` and `sealed` verbatim, or a Secret entry is lost | copies the level | `test_db_merge_window.py` |
| `scripts/db-filter.sh`, `db-prune.py` | ciphertext is copied as bytes; nothing to read | the filtered copy keeps the level | `test/db_swap.py` |
| `scripts/export-public.py` | ships code, no journal; nothing to skip. The audit gets a rule that no `lcs1.` envelope is in the tree | n/a | `test_export.py` |
| `lcars-ui/demo/static.py`, `fixture.py` | the fixture is made up; it gets one Secret row and a demo vault whose password the demo prints, so the feature can be shown | one Confidential row | `test/demo_static.py` |
| a backup reader with the db file | ciphertext, a salt, a wrapped key | plaintext (said in the UI) | `classified.py`'s byte scan |
| the page: the mirror (IndexedDB), the outbox, drafts, localStorage | ciphertext only; plaintext only in memory while unlocked; the editor's draft of a Secret entry is encrypted before it is stored, or not stored | as Unclassified | QuickJS suite, `test/offline.py` |
| the page's search, palette, reader | locally over the decrypted titles and text while unlocked; nothing while locked | as Unclassified | QuickJS suite |
| `ui_patch`, `deck_patch` (agent-written code in the page) | not applied in a page that is unlocked; unlocking in a page that has applied one asks for a reload without them (`?nopatch`) | n/a | `test/architect.py`, QuickJS suite |

## 5. The UX

### 5a. The first time
Config gets a "Classified" section: **Set a password**, typed twice, with
the plain warning of 5g on the same screen and a tick-box "I understand a
lost password means the Secret entries are gone". The page makes MK,
wraps it, derives the vault token, and `PUT /vault`s. Optionally (Q4) it
shows a recovery code once.

### 5b. Unlocking on a device
A lock icon in the header, the palette row "Unlock classified", key `U`
(free today? to be checked against `KEYS`), and the voice order "computer,
unlock". All open the same prompt; the password is typed, never spoken.
Opening a Secret row while locked opens the prompt in place.

### 5c. How long, and locking
In memory only, for the tab's life, until any of: **Lock** (the icon, the
palette, "computer, lock", a key), 15 minutes with no input (Config can
change it), the page hidden for 5 minutes on a phone, a reload. On lock the
decrypted rows are dropped from memory and the list redraws the
placeholders in the same frame. No "remember this device" in phase 1: a
stored key is one any same-origin script can use later. Passkeys (section
6) make unlocking cheap enough not to need it.

### 5d. Raising and lowering a level
In the editor's Details and its ⋯ sheet, a level chip: Unclassified /
Confidential / Secret; voice "computer, mark this secret", "mark this
confidential", "declassify". Raising to Secret needs the page unlocked (to
encrypt with MK; with phase 3's public key, raising works locked: sealed
to the public key, readable after the next unlock). Lowering from Secret
decrypts, so it needs the unlock, and asks once ("this entry will be
readable by the agents"). Feedback follows the standing rule: the chip
changes at once, the row shows "sealing…", and a failure says so on the row
with Retry.

### 5e. Changing the password
Unlocked: old password, new twice. The page unwraps MK with the old,
wraps it with the new, `PUT /vault` with the token. One request; no entry
is touched, so it is instant and cannot half-fail. A separate, rare
**Rotate the key** (for "I think MK itself leaked") makes a new MK and
re-encrypts every Secret entry, resumable, each row a guarded PATCH.

### 5f. Voice and dictation in a Secret entry
Orders about an entry (mark, lock, open) carry no content and work as
everywhere. Dictating the *text* of a Secret entry sends the audio to
Deepgram or the browser's recogniser; the page shows a "voice leaves the
device" mark on the microphone in a Secret entry, and reading one aloud
(`/say`) is refused. Whether dictation is allowed at all there is Q5.

### 5g. Losing the password
**The Secret entries are gone.** Nobody can recover them: not the server,
not the box's admin, not an engineer. Their rows stay, as placeholders with
their kind and dates, and can be deleted. This is said at setup, in
Config, and in the docs, in those words.

A **recovery code** is worth offering: a random 128-bit code, shown once
as 26 characters in groups, that is one more wrap of MK in the vault
(nearly free, the same machinery as a passkey). It is one more secret to
keep (a password manager, a paper in a drawer). Offered at setup, on by
default (Q4's answer; built in 0.287.0, section 12).

## 6. Passkeys later

Nothing above ties MK to the password: the vault is a list of wraps. A
passkey adds one, through the WebAuthn **PRF extension**: at registration
and at each `navigator.credentials.get()` the authenticator returns a
32-byte secret for a salt the page chooses, the page runs HKDF on it and
wraps (or unwraps) MK with the result, and the wrap is stored with the
credential's id and the salt. PRF is in iCloud Keychain passkeys (Face ID,
Touch ID; iOS/macOS 18), Chrome and Android, Windows Hello in recent
builds, and FIDO2 keys through `hmac-secret` (a fingerprint YubiKey Bio).
An authenticator without PRF cannot unwrap anything, so it is not
offered; the password stays as the fallback wrap. The server checks no
signature: the PRF output *is* the key, so a passkey unlock is offline and
works the same on the static demo. The only constraint on phase 1 is the
one it already keeps: entries encrypted with MK, never with a key derived
from the password itself.

## 7. Trusting the page

Since the page is where the plaintext lives, the code that touches MK is
one module, `classified` in `index.html` (a marked block, as the chats'
speech queue is), and:

- `ui_patch`/`deck_patch` are never applied in an unlocked page (section 4).
- The page's CSP gets `connect-src 'self'` in phase 1 if it is not there:
  a stolen password then has to go to the journal's own server, where it is
  at least a write that can be noticed.
- A deploy whose diff touches the `classified` block, `sw.js` or the
  page's CSP is named in the deploy report as such (`engineer.py deploy`),
  and Number One does not deploy one without the captain's word (Q6).
- `test/classified.py` pins what the block sends: in Chromium, an unlock,
  an edit and a lock with every request recorded, none carrying the
  password, MK, or a Secret entry's plaintext.

## 8. The open-source angle

Nothing here is personal: "the owner", the levels' names in one table (an
installation may rename them in Config, as kinds are renamed), no
hard-coded login names (the limited logins are whatever the installation
configured). The vault, the envelope prefix and the KDF parameters are
documented in this file as a format, so a third-party reader (a recovery
script, a future native app) can be written from it. The demo carries a
demo vault with a printed password. The release build needs nothing new:
SHA-256 is in-house, the crypto is the browser's, and phase 3's CLI sealing
uses the libcrypto that the static link already carries through libcurl.

### 8a. The vault's format (as of 0.287.0)

For a third-party reader. All base64 is base64url without padding. The
body `GET /vault` answers is `{"version": N, "vault": V}`; V is:

```json
{"v": 1, "kid": "k1", "wraps": [W, ...]}
```

Every wrap W has `type`, `iv` (12 bytes) and `wrapped`: the 32-byte master
key MK wrapped by WebCrypto `wrapKey("raw", MK, KEK, {AES-GCM, iv})`, so
`wrapped` is AES-256-GCM of MK's 32 bytes, 16-byte tag appended, no
additional data. Opening one is AES-GCM-decrypt with that wrap's KEK;
a wrong KEK fails the tag. The KEK per type:

| `type` | fields | KEK |
|---|---|---|
| `password` (exactly one; the server refuses a vault without it, or with two) | `kdf: "PBKDF2-SHA256"`, `iter`, `salt` (16 bytes) | PBKDF2-HMAC-SHA-256(UTF-8 password, salt, iter), 32 bytes |
| `recovery` (at most one) | `kdf: "HKDF-SHA256"`, `info: "lcars vault recovery v1"`, `salt` (16), `created` (YYYY-MM-DD) | HKDF-SHA-256(ikm = the code's 16 bytes, salt, info), 32 bytes |
| `passkey` (any number) | `kdf: "HKDF-SHA256"`, `info: "lcars vault passkey v1"`, `salt` (16), `cred` (the credential's raw id), `prf_salt` (32), `name`, `created` | HKDF-SHA-256(ikm = the WebAuthn PRF output `results.first` for input `prf_salt` from credential `cred`, salt, info), 32 bytes |

The recovery code as shown: its 16 bytes as 26 characters of Crockford's
base32 (`0123456789ABCDEFGHJKMNPQRSTVWXYZ`, most significant bit first,
the last character's two spare bits zero), grouped 5-5-5-5-6 with dashes.
A reader ignores case, spaces and dashes and takes O as 0, I and L as 1.
A passkey's PRF is the WebAuthn `prf` extension (CTAP2 `hmac-secret`
underneath): its relying party is the page's host, so a passkey made at
one address does not open the vault at another.

From MK: entries are AES-256-GCM (section 2c's envelope; the plaintext a
JSON object of `title`, `content`, `value_int`, `value_float`), and the
vault token is HKDF-SHA-256(MK, empty salt, info `"lcars vault token v1"`),
32 bytes as lowercase hex; the server stores its SHA-256 (`auth_hash`).

## 9. Phased plan

Each phase is one engineer's order, shippable alone.

**Phase 1 - Secret entries in the console (the smallest slice).**
Server: the two columns, the `vault` table, `GET/PUT /vault` with the
token guard (`lcars_sha256.h`), the write rules on `/entries` (an
envelope only, append/title 409, media refused), placeholders for the
limited logins, the embedder, CalDAV and Logseq export skips, the raise
clean-up (`secure_delete`, the vector and CalDAV row deleted, a
checkpoint). Page: set the password, unlock/lock (icon, palette, key,
VCMDS), the level chip with Secret only, encrypt on save, the mirror and
outbox holding envelopes, local search while unlocked, patches off while
unlocked, `/say` refused. Tests: new `test/classified.py` (server and
Chromium: the routes, the logins, a stand-in embedder and Logseq, the
db file's bytes, the requests the page makes), additions to `logins.py`,
`caldav.py`, `api.py`, the QuickJS suite, `offline.py`, `architect.py`,
`test_db_merge_window.py`, `demo_static.py`.

**Phase 2 - Confidential, and the chat's own login.** The level 1
behaviour across section 4's table, and a limited login for the chat's
Claude (`ChatBuildEnv`) so the server can withhold Confidential rows from
it. Tests: `logins.py`, `chat_media.py`, `test_crew.py`, `test_linker.py`.

**Phase 3 - The write-only doors.** The vault's ECDH key pair; `lcs1s.`
envelopes opened by the page; `lcars-cli add --secret` sealing in the
client (`-lcrypto`; `make lcars-cli`, `onebin.py`, `scripts/release/check.sh`);
raising while locked; the Shortcut's server-side seal if Q3 says yes.
Tests: `classified.py` (a CLI-sealed entry opened in Chromium), `onebin.py`.

**Phase 4 - Recovery code and media.** The recovery wrap (5g); photos,
audio and video of a Secret entry encrypted in the page before upload
(`lcars_media.h` stores opaque blobs, no thumbnails or transcoding for
them). Tests: `recording.py`, `classified.py`.

**Phase 5 - Passkeys.** WebAuthn PRF wraps, registered per device from
Config, listed and removable; the password kept as a fallback. Tests: a
virtual authenticator in Chromium (CDP `WebAuthn.addVirtualAuthenticator`
with `hasPrf`).

## 10. Open questions for the owner, answered

The captain's answers (2026-10-20, through Number One), all as recommended:

1. Option A, in the browser. (2026-10-20)
2. Kind, dates and done visible; text and numbers sealed. (2026-10-20)
3. Shortcuts open the console; no server-side seal. (2026-10-20)
4. A recovery code offered at setup, on by default; phase 4 builds it,
   phase 1 keeps `wraps` a list. (2026-10-20)
5. Dictation allowed in a Secret entry, with the voice-leaves-the-device
   mark; `/say` (reading it aloud) refused. (2026-10-20)
6. A deploy touching the classified block, `sw.js` or the CSP needs the
   captain's own word; Number One escalates every one. (2026-10-20)
7. Confidential kept, for phase 2. (2026-10-20)

The questions as they were put:


1. **Option A** (in the browser; Secret entries are born and read only in
   the page until phase 3) - agreed?
2. **The kind**: visible on a Secret row (recommended), or sealed too,
   every such row under one `classified` kind?
3. **Shortcuts**: a server-side seal on arrival (plaintext through the
   server once), or Shortcuts open the console to write a Secret entry?
4. **A recovery code**: offered at setup (recommended, off by default),
   or none at all?
5. **Dictation in a Secret entry**: allowed with the "voice leaves the
   device" mark, or off?
6. **Deploys touching the `classified` block** need the captain's own word,
   not Number One's?
7. Is **Confidential** wanted, knowing it holds against the agents'
   logins but not against an agent with a shell?

## 11. Phase 1 as built (0.280.0, the handover)

For whoever picks this up next, knowing nothing. Branch `eng/torres-c37`
(cut from deb at d8fa73a, this design's commit); not deployed: it goes
to the captain first (section 10, Q6).

### 11a. The three commits

- **7604ff7, the server.** `lcars_db.h`: the `classification` and
  `sealed` columns. `lcars_sha256.h` (new): FIPS 180-4, `Sha256Init/
  Update/Final/Hex`. `lcars_vault.h` (new): the vault and the envelope
  rules. `lcars_http.h`: `secure_delete` on every connection
  (`OpenHTTPDB`); `HTTP_ENTRY_COLUMNS` grows `classification, sealed,
  length(sealed)` at its end and `AppendEntryJSON` emits
  `classification` always and `sealed` only to the main login with
  content (`content_length` counts the envelope then); the
  `X-LCARS-Vault` header copied into `g_conn_vault_token` after auth;
  `POST`/`PUT`/`PATCH /entries` enforce the rules (11c); append and
  title answer 409 on a Secret row; the `/vault` route. `lcars_logins.h`:
  `/vault` refused to every limited login. `lcars_media.h`: an upload to
  a Secret entry 409. `lcars_embed.h`: Secret rows never selected,
  counted, served, or given a vector (the insert re-checks the level).
  `lcars_caldav.h`: every read goes through `CALDAV_ENTRIES`, a subquery
  showing a Secret row as deleted and textless; its PUT update refuses
  one. `lcars_cli.h`/`lcars_logseq.h`: `EntryRow.classification`, the
  export skips Secret rows. `scripts/db-merge-window.py`: both columns
  verbatim, `LCARS_VAULT_TOKEN`. Tests: `test/classified.py` (server
  half), additions to `api.py`, `logins.py`, `caldav.py`.
- **e2929c5, the page.** The "classified" block in `index.html` (11b),
  its wiring, the markup (`#edcls` chip, `#bCls` header button, Config's
  `#c_cls` section), VCMDS, `L`, palette rows, CSS; `deck.html`'s patch
  guard.
- **17f12c8, the rest.** `test/classified_ui.py`, the QuickJS block in
  `test/tests.js`, `architect.py`, `demo_static.py`,
  `test_db_merge_window.py`, `changed.py`'s map; the demo's Secret entry
  (`demo/fixture.py`, `static.js`, `static.py`); CHANGELOG 0.280.0,
  APP_VERSION, TODO, CLAUDE.md's test list, sections 10-11 here.

### 11b. The shape of the code, and where the trust boundary is

The boundary: plaintext of a Secret entry exists only in the page's
memory while unlocked. The server (`lcars_vault.h`) never has the
password, the key or the text; it only refuses what would put text in
the clear and guards who may change the level or the envelope.

`lcars_vault.h`: `ClassifiedLevelKnown` (0 or 2 only), `ClassifiedEnvelopeValid`
(the `lcs1.` prefix and base64url/dots; it cannot check the cipher),
`VaultEnsureTable`, `VaultTokenCheck(db, token)` (1 match, 0 not, -1 no
vault; compares the SHA-256 of the lowercased hex token with
`auth_hash`), `ClassifiedRaiseCleanup` (the vector and CalDAV row,
inside the raise's transaction), `ClassifiedCheckpoint` (WAL TRUNCATE
after a raise commits), `HandleVault` → `HandleVaultGet`/`HandleVaultPut`
(first PUT needs no token and version 0; after that the token and the
current version, `new_token` to move the guard). The entry rules live in
`HandlePostEntry` and `HandleUpdateEntry` in `lcars_http.h`; the update
reads the row's level inside `BEGIN IMMEDIATE`, so raise/lower cannot
race.

The page's block (`/* ===== classified`, just before `state`): `cls`
(the vault, `key`, `token`, `plain` = envelope → plaintext, `busy`,
`failed`, the timers); `clsCrypto` (the only WebCrypto calls: `kek`,
`unwrap` (two non-extractable keys: AES-GCM for entries, HKDF for the
token), `fresh`, `wrap`, `seal`, `open`; the QuickJS suite stubs it);
`clsVaultRead`, `clsSetup`, `clsUnlock`, `clsChange`, `clsLock`,
`clsTick` (auto-lock); `clsPatched` / `window.lcarsClsUnlocked` (the deck
side is `lcarsDeckPatched` and the check in `patchApply`). The choke
points, each one line elsewhere in the page: `api()` calls
`clsSealOpts` before the outbox (`clsWrite` decides which writes) and
`clsOpenAnswer` on answers holding a Secret row; `apiNet` calls
`clsHeaders`; `plainRow` → `clsBare` (the mirror, srvSeen, the outbox's
bases); `saveCache` keeps Secret rows bare; `lsSet` refuses a Secret
draft (`clsDraftSecret`); `formValues` carries `classification` so
`createRow` seals a draft that lands late; `obOverlay` → `clsApply`;
`OB_FIELDS` (FIELDS + the two columns) is what the outbox and the
mirror carry. Shown: `shownTitle` (the placeholder), `clsFlag` in the
list row, `clsReadLock` in the reader, `clsForm` in `setForm`
(read-only when locked), `clsChipPaint`, `clsHeadPaint`,
`clsVoicePaint` (from `vPaint`). Doors: `clsSetupAsk`, `clsUnlockAsk`,
`clsChangeAsk`, `clsToggle`, `clsMarkSecret`, `clsDeclassify`,
`clsChipTap`, `clsFail` (the Retry); Config's buttons go through one
`[data-cls]` click handler.

### 11c. What phase 1 decided that the design left open

- **The guard covers entries too.** Any write that sets `classification`
  or `sealed` carries the vault token (`X-LCARS-Vault`), not only a vault
  write: without it an agent with the main password could not read a
  Secret entry but could lower it and so destroy it. The page adds the
  header in `apiNet`, so the outbox's later flush carries it from memory;
  a flush after a reload while locked is refused (403), and the outbox
  keeps the write on this device, says so, and tries again on the next
  visit (its rule for any refusal); unlocked by then, it goes.
  `db-merge-window.py` takes the token from `LCARS_VAULT_TOKEN`, which
  Config copies while unlocked; the token can rewrite an envelope, never
  read one.
- **Confidential is refused** (400) until phase 2 builds its skips: a level
  the readers did not honour would be a promise nobody keeps.
- **CalDAV sees a Secret row as deleted**, through one masking subquery
  (`CALDAV_ENTRIES`) every read goes through, so a sync names it removed
  and a stale client's PUT to it writes nothing (it is refused).
- **No Secret entry reaches `/say`**: the console reads an entry aloud
  through `/say`'s hosted voice when one is set, else the
  browser's own (`ttsAloud`), which may be a service's too, so the
  reading is what is refused for a Secret entry. Suggestions (`sugRun`'s
  `/embed` of the draft) are off in one as well.
- **The chip is the editor's**, beside the kind's, so raising and lowering
  is from Edit; reading a locked entry offers Unlock.
- **Files**: an upload to a Secret entry and the raise of an entry with
  files are refused (409); the page checks the second before it asks.
- **The demo** seals its Secret entry in the browser at its first load
  (`demo/static.js`), with 20,000 rounds rather than 600,000: its password
  is printed, and a visitor waits on them.
- **The tests**: the outbox's offline case is in test/classified.py's
  Chromium half (the network cut, the outbox and its IndexedDB scanned)
  rather than in test/offline.py.

### 11d. The tests, and how long they take

- `python3 lcars-ui/test/classified.py` (~1 min, builds a scratch server
  first, ~30s more; `LCARS_TEST_BIN=` skips the build): the NIST vectors,
  the vault, the rows, a raise with the byte scan, the embedder (two
  scratch servers, a stand-in service), then `classified_ui.run` in
  Chromium (needs playwright). `CHROMIUM=0` runs the server half only
  (~20s). 126 checks.
- `classified_ui.py` is not run alone: classified.py calls it with its
  server binary and scratch dir.
- The QuickJS block ("classified: what is kept, sealed and shown", at the
  end of `test/tests.js`) runs in `lcars-ui/test/run.sh` (~1 min with
  `PERF=0`, ~3 in full).
- Also touched: `api.py`, `logins.py`, `caldav.py` (~30-40s each),
  `architect.py --no-server` (~5 min), `demo_static.py` (~1 min),
  `scripts/test_db_merge_window.py` (~10s).
- Known red not of this change: `editor.py` fails three desktop checks
  (a reading kind's Number, done in the tap, the kind chip) on deb with
  deb's own server too.

### 11e. What is weak or unfinished

- The page is the trusted base (section 7): nothing stops a deployed
  page from leaking the password. Only process guards it (Q6).
- Memory after a lock: the rows and `cls.plain` are cleared, but text
  already copied into other in-memory caches (the search's terms, the
  relation index, DOM nodes since replaced) is only rebuilt, not
  scrubbed; it dies with the tab.
- The outbox: a write refused while locked (after a reload) waits for
  the next visit, not for the unlock. Three-way merges of a Secret row
  offline compare envelopes, so any concurrent change is a conflict.
- The level chip is the editor's only. Files: uploads refused, nothing
  encrypted (phase 4). Rotate the key (5e) is not built. A CalDAV
  client's stale PUT to a raised task gets a 500, not a clean 409.
- Integrity is partial: the token guards the level and the envelope,
  but a main-login agent can still delete (soft), re-kind or re-date a
  Secret row, or replay an old envelope of the same entry.
- The demo uses 20,000 PBKDF2 rounds; the app 600,000.

### 11f. Where phase 2 starts

Confidential (level 1): drop the 400 in `ClassifiedLevelKnown`, then
make every reader of section 4 honour level 1 the way it honours 2 -
the placeholders in `AppendEntryJSON` for the limited logins (and
search for them), the embedder's `classification = 0` filters,
`CALDAV_ENTRIES`'s CASEs, the Logseq skip already tests `!= 0`. Level 1
is plaintext, so none of the page's sealing applies; the chip grows a
third state. Then the chat's own limited login (`ChatBuildEnv` in
`lcars_chat.h` hands the main login to the chat's lcars-cli today), so
the server can withhold level 1 from it; `logins.py`, `chat_media.py`,
`test_crew.py`, `test_linker.py`, and `classified.py` with a level-1 row
through every reader.

## 12. Phase 5 as built (0.287.0, the handover)

Passkeys, the recovery code (phase 4's half of it; its media stay
undone), the page's CSP and the deploy's flag. Branch `eng/torres-c37`,
cut from main at 51fe451; not deployed: it touches the classified block
and adds the CSP, so it is the captain's own word (Q6). Phase 2 was
dropped by the captain (2026-10-21).

### 12a. What changed, where

One commit, **c915eb5** ("Classified entries, phase 5: …", 0.287.0), and
this handover's. Line areas as of c915eb5: `index.html` csp block ~13-60,
classified block ~6266 (`clsPasskeyAdd` ~6593, `clsCfgHtml` ~6858,
`clsCodeShow` ~7026, `clsPasskeyAddAsk` ~7075, the `[data-cls]` click
handler after it), palette rows ~28627, VCMDS ~29518;
`lcars_vault.h` `VaultPasswordWrapKept` ~213; `engineer.py`
`CLASSIFIED_BLOCKS` ~3219, `classified_touches` ~3236;
`classified_ui.py` `passkey_run` ~270.

- **`lcars_vault.h`**: `VaultPasswordWrapKept` - `PUT /vault` answers 400
  unless `wraps` holds exactly one `type: "password"` and every wrap has
  a type. The server knows no other wrap; it stores the body as before.
- **`index.html`, the classified block**: `clsCrypto` gains `bytes`,
  `hkek` (HKDF to an AES-GCM wrapping key), `pkOk`, `pkCreate`, `pkGet`
  (WebAuthn with `prf.eval` / `prf.evalByCredential`), `pkForget` (the
  Signal API, where Chrome has it). Above the lock: `clsWrapsOf`,
  `clsCodeOf`/`clsCodeBytes` (the code's base32), `clsRecWrap`, `clsPut`
  (the guarded PUT), `clsRecoveryMake`, `clsRecoveryUse`,
  `clsPasskeyAdd`, `clsPkErr`, `clsPasskeyUnlock`, `clsPasskeyRemove`.
  `clsSetup(pw, rec)` returns the code. The doors: `clsCfgHtml` (the
  passkeys' list, the recovery line, `CLS_LOST`), the unlock dialog's
  `#clsPk` and `#clsRecUse`, `clsPkTap`, `clsPasskeyAsk`, `clsCodeShow`,
  `clsRecoveryAsk`, `clsRecoveryMakeAsk`, `clsPasskeyAddAsk`,
  `clsPasskeyDel`; `clsDialog`'s `run` gets a `wait(label, why)` for the
  OS sheet. VCMDS (four orders), four palette rows, CSS.
- **`index.html`, the head's "csp" block**: a `<meta http-equiv>` put in
  by script, `connect-src 'self' blob: data: <the configured base's
  origin> <CSP_CONNECT>`, and `window.LCARS_CSP`.
- **`scripts/engineer.py`**: `CLASSIFIED_BLOCKS`, `block_ranges`,
  `classified_touches`; `do_deploy` logs a "CLASSIFIED:" step, sets
  `classified` in deploy.json (so `deploy-status`) and adds it to the
  finished line, which Number One is sent.
- **Tests**: classified.py (the server's refusals), classified_ui.py's
  `passkey_run`, tests.js's phase 5 block, check.py's CSP rule,
  test_deploy_suite.py's `Classified`, shim.js's `atob`.

### 12b. What phase 5 decided that the design left open

- **A new wrap asks for the password.** The unlocked page holds MK as
  non-extractable keys, and `wrapKey` needs an extractable one; keeping
  an extractable copy while unlocked would let any script in the page
  export MK. So registering a passkey and making a recovery code ask for
  the password once more and unwrap an extractable copy for that one
  write. Removing a passkey needs only the token.
- **The recovery door sets a new password.** Using the code is for a lost
  password, so the dialog takes the code and a new password, rewrites the
  password wrap, and unlocks. The code stays valid (Config replaces it).
- **The CSP is a script-made meta, not a header**: the page is served by
  the server, the worker's cache, the embedded build, the R2 demo and a
  file, and only a policy in the page travels with all of them; the
  configured server is allowed by name (read from `lcars.cfg` at load),
  so a page pointed elsewhere still works. A meta's policy cannot be
  lifted by removing it. `connect-src` names the services the console
  calls (Deepgram, Open-Meteo, MeteoAlarm, RainViewer, Mapy.com,
  Nominatim, BRouter, three Overpass mirrors, the tile hosts the course
  map keeps offline); check.py fails on a host in the page it does not
  name and is not in its `LINK_ONLY`.
- **The deploy's flag** is a hunk overlapping the lines from a block's
  opening marker to the next one's (`/* ===== classified` .. `state`,
  `/* ===== csp` .. `/csp`), in the old file or the new, or a marker
  gone; `sw.js` counts whole. It names and does not refuse: Q6 is
  Number One's process.
- **Passkey options**: `userVerification: "required"`, `residentKey:
  "preferred"`, a random user id per registration, `excludeCredentials`
  the vault's own (a second one on the same device is told so). The PRF
  is taken from `create()` where the authenticator gives it, else from
  one `get()` straight after.

### 12c. The tests, and how long they take

- `python3 lcars-ui/test/classified.py` (~25s here with the build cached
  by the job, ~1 min cold): 162 checks; phase 5 at
  `http://localhost:<port>` (WebAuthn takes no IP address) with
  `WebAuthn.addVirtualAuthenticator` (ctap2, internal, hasPrf, UV).
- The QuickJS block "classified: the recovery code and the passkeys"
  (in run.sh): the code's base32 both ways, setup, add, a wrong
  password, no PRF, unlock by passkey and by code, replace, change, remove,
  a one-wrap vault, Config's lines, the four orders, the CSP.
- `python3 scripts/test_deploy_suite.py` (~3s): 6 `Classified` cases.

### 12d. The vault format

Section 8a.

### 12e. What is weak or unfinished

- The page is still the trusted base: the CSP stops code injected into
  it from connecting elsewhere, not a deployed page that drops the CSP.
  Q6's escalation is the guard for that, and it is a process.
- `connect-src` only: an injected script could still leak through an
  image's URL (`img-src` is open: map tiles, pictures) or a navigation.
  Tightening `img-src` means naming every tile host and the media root.
- The deck (`deck.html`) has no CSP of its own; deck patches run there
  (and are refused while the console is unlocked, section 7).
- The allowed services can carry data in a query string (a Nominatim
  search, a weather URL): the CSP narrows where text can go, it does not
  close it.
- A passkey is tied to the host it was made on (its relying party): the
  tailnet address and another name for the same server are different
  passkeys.
- Unlocking by passkey from a voice order calls WebAuthn without a tap;
  Safari may want one, and then the dialog's button is there to tap.
- Removing a passkey from the vault cannot delete it from the device;
  Chrome is told (`signalUnknownCredential`), others keep a dead one.
- A closed dialog's markup stays in `#dlg` until the next one opens: the
  code is cleared on "I have kept it", not when it is closed by Escape.
- The recovery code, like the password, is a full key: anyone holding it
  reads the Secret entries. Said at setup.

### 12f. Where phase 5 stopped (2026-10-21, the handover)

Done and green: classified.py 162/162 (job 083330); the QuickJS suite
(4986 assertions, 0 failures), parse, structure, the deck boot, the
version check, the audit and keyboard.py (0 failures) in the full run.sh
(job 083606); test_deploy_suite.py 13/13. CHANGELOG 0.287.0 and
APP_VERSION 0.287.0 match (run.sh's version stage passed).

Open: **perf's eng-thread** went over in that full run: p99 median 16.7ms
(runs 17.8, 13.1, 16.7) against main 51fe4517's 13.4ms (13.2, 13.4, 15.1),
"slower than main by 25%"; every other scenario passed (stars-chart, over
once, was 13.1 against main's 13.4 on its rerun). Nothing in this change
touches the engineer thread's code, so noise on a busy box is likely,
but a CSP refusal inside that scenario (perf.py's fake API, a fetch the
policy blocks, its violation reports) is the one way it could be real:
look for `securitypolicyviolation`/console CSP errors in that scenario
first. A comparison is queued: job `torres-c37-20261021-085622`,
`perf.py --compare --fresh eng-thread` (its log in
~/.local/state/lcars-eng/logs/job-torres-c37-20261021-085622.log). It was
queued against c915eb5's tree: this handover's commit moves HEAD, so
the job may refuse to start ("HEAD or the tree moved"); if so, queue it
again.

Still to do, in order: the perf verdict (and a fix if it is real; then
run.sh in full again through the job line); `python3
lcars-ui/test/demo_static.py` through the job line (not yet run: the CSP
is in the demo's page too, which is served from R2, so 'self' is the
bucket); then the report as an HTML file through `scripts/report.py
publish FILE --title "Classified entries, phase 5"` - what was built,
the test counts above, the vault format (8a), what stays weak (12e) -
and its link in the last message to Number One. Not deployed, and not to
be: the captain deploys this one on his own word (Q6).

Closed after the handover (job 085850, on bbd464c): perf's eng-thread
against main, fresh, three runs each in turn: p99 median 14.1ms (14.1,
11.8, 14.9) against main's 13.2ms (14.2, 12.5, 13.2), in budget. The
earlier 16.7 was the busy box: the scenario's measured frames make no
request (a file:// page, `engStop()`, DOM only) and its base,
`https://lcars.test`, is in the policy, so the CSP has nothing to refuse
there. `demo_static.py` 58/58 (the demo's Secret entry unlocked under the
CSP, nothing asked of anyone but the folder). Rebased onto main 09a9226
(0.286.2); 0.287.0 stays the top.

