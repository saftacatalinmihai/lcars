# Apple Shortcuts for the LCARS HTTP API

Nine shortcuts that talk to the LCARS API (`ARCHITECTURE.md` → HTTP API).
`generate.py` builds them; the `.shortcut` files next to it are its output and
can be imported as-is. The kinds they post are the journal's roles
(docs/design/kinds.md), fixed at the build: `--kind` the log role's
(default `personal_log`), `--task-kind` the task role's (default `task`);
`lcars-cli roles` says what a journal has.

| File | What it does | Request |
|---|---|---|
| `LCARS Log.shortcut` | Asks for text, files it as a log entry | `POST /entries` kind `personal_log` (`--kind`) |
| `LCARS Task.shortcut` | Asks for text, files it as a task (also what CalDAV/Reminders shows) | `POST /entries` kind `task` (`--task-kind`) |
| `LCARS Note.shortcut` | Asks for text, files it as a note | `POST /entries` kind `note` |
| `LCARS Share.shortcut` | Share-sheet action: whatever you share becomes the entry content | `POST /entries` kind `personal_log` (`--kind`) |
| `LCARS Today.shortcut` | Shows today's entries | `GET /entries?date=…` |
| `LCARS Open Tasks.shortcut` | Shows unfinished tasks | `GET /entries?kind=task&done=0` (`--task-kind`) |
| `LCARS Search.shortcut` | Asks for a term, shows matches | `GET /entries?q=…` |
| `LCARS Stats.shortcut` | Counts, byte total, oldest/newest | `GET /stats` |
| `LCARS Computer.shortcut` | A spoken conversation with the journal's Claude Code agent: dictate, hear the answer, dictate again; silence ends it | `POST /ask` |

## LCARS Computer

The web console's *Ask* panel, by voice, from the phone or the Watch ("Hey
Siri, LCARS Computer"). Each turn is: Dictate Text, `POST /ask` with
`{session_id, local_time, message}`, Speak Text of the answer's `text`, and
round again, keeping the `session_id` the answer brought back. It starts
empty, so every run is a new conversation; a turn that hears nothing ends
it. Questions about the journal, and orders: log or capture something (a
dictated account is stored as a summary plus your exact words), new tasks
with due dates and alerts, titles, kinds, done/open, delete/restore,
scheduling, adding to or continuing an entry. Screens (the calendar, the
star chart) stay on the console.

A turn takes 5–10 seconds — claude starting, and one or two model turns.

If the generated file will not import, it is nine actions by hand:

1. **Text** `https://<your server>` → *Set Variable* `LcarsURL`
2. **Text** `user:password` → **Base64 Encode** (line breaks: none) → *Set
   Variable* `LcarsAuth`
3. **Text** (empty) → *Set Variable* `SessionID`
4. **Repeat** 50 times:
   - **Dictate Text** (stop listening: after pause) → *Set Variable* `Heard`
   - **If** `Heard` *does not have any value* → **Stop This Shortcut**
   - **Date** (current) → **Format Date** custom `yyyy-MM-dd HH:mm ZZZZZ` →
     *Set Variable* `LocalTime`
   - **URL** `LcarsURL`/ask → **Get Contents of URL**: POST, header
     `Authorization: Basic LcarsAuth`, JSON body `session_id` = `SessionID`,
     `local_time` = `LocalTime`, `message` = `Heard` → *Set Variable*
     `Answer`
   - **Get Dictionary Value** `session_id` of `Answer` → *Set Variable*
     `SessionID`
   - **Get Dictionary Value** `text` of `Answer` → **Speak Text** (wait
     until finished)

Optional `model` field: `sonnet` (the default), `haiku`, `opus`, `fable`.

**Which URL.** The tailnet name (`https://….ts.net`) is TLS and private, and
is what the phone should use. The Watch does not run Tailscale; whether a
Watch shortcut's requests go through the phone's tunnel has not been
checked. There is no public fallback any more: the server listens on
127.0.0.1 only, behind tailscale serve.

Each one asks two questions while importing: the server URL (what
`generate.py --url <your server>` built it with, else a placeholder; the
committed `.shortcut` files offer an old address of the captain's that no
longer answers - build your own) and the Basic auth credentials as
`user:password`. Answer both and nothing else needs editing. To change them
later, open the shortcut — the first action holds the URL, the third holds the
credentials.

## Importing

These are **unsigned** shortcut plists, and since iOS 15 that is not enough on
its own: Apple removed the "Allow Untrusted Shortcuts" setting and made every
shared shortcut carry a signature instead. On iOS 26 an unsigned file simply
will not import. Sign it first.

**On a Mac** (`shortcuts` CLI, macOS 12+):

```sh
mkdir -p signed
for f in *.shortcut; do
  shortcuts sign --mode anyone -i "$f" -o "signed/$f"
done
```

`sign-on-mac.sh` next to this file does exactly that. `--mode anyone` is the
share-with-anyone signature; `people-who-know-me` restricts it to contacts,
which is pointless for moving a file to your own phone. AirDrop the `signed/`
files over and tap one to import.

Two things that make the transfer shorter:

- **Importing on the Mac is often enough.** If the Mac and the phone share an
  iCloud account with Shortcuts sync on, a shortcut added on the Mac shows up on
  the phone by itself, no AirDrop and no signing.
- **Re-sharing from a device signs for free.** Once a shortcut is on any Apple
  device, its share sheet produces an iCloud link that any other device of yours
  can open — so the signing step is only ever needed for the first hop.

**Without a Mac**, the only route is a remote signing service:
RoutineHub's HubSign, `POST https://hubsign.routinehub.services/sign` with
`{"shortcutName": "...", "shortcut": "<the plist as XML>"}`, which answers with
the signed AEA1 file. That ships the shortcut's contents to a third party, so
scrub the server URL out of the plist first if that matters.

## Notes

- **The credentials live inside the shortcut as plain text**, and Basic auth
  over plain HTTP travels in the clear on every request. Put the API behind
  TLS before pointing a phone at it over the internet — `tailscale serve --bg
  8080` on the VPS is the cheapest version (see ARCHITECTURE.md → Deployment).
- `LCARS Today` filters on `created_at_utc`, so near local midnight it shows the
  UTC day rather than the wall-clock one. Same caveat the `date=` filter has
  everywhere.
- **The URL is built by a URL action, not in the request's own field.** Get
  Contents of URL types that field as a URL, and a variable coming out of a
  Text action is rich text: dropping it in fails at run time with *"Get Contents
  of URL failed because Shortcuts couldn't convert from Rich Text to URL"*. The
  URL action (`WFURLActionURL`) takes text with variables and produces a real
  URL value, which the request then reads from the `RequestURL` variable. Same
  fix by hand in the app: add a URL action above the request, move the address
  into it, and put its Magic Variable in the URL field.
- The four read shortcuts render their list with a Repeat block; the four write
  shortcuts are a single request and share none of that machinery, so a read one
  misbehaving on an older Shortcuts version does not affect them.
- Adding a shortcut: extend `SHORTCUTS` in `generate.py` and re-run it. Every
  route in the API table is reachable the same way — `PUT /entries/<id>` to mark
  a task done, `GET /kinds` for the kind list.
