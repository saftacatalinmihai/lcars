# The user manual

The console's user manual (`lcars-ui/index.html` only, not the deck) is
written for someone meeting LCARS for the first time, from the open-source
release or the public demo; it is read on a phone as often as at a desk.
Its plan, review and first publishing were sato-c31's (25 Oct 2026); this is
how it is kept.

## 1. The source: `site/manual/`

- `pages/*.md`, one per section, in order by name: `00-start` to
  `13-trouble`, and the appendices `20-keys`, `21-phrases`, `22-glossary`.
  A small Markdown subset (`build.py`'s docstring): `##`/`###` with
  `{#id}`, flat `-` and `1.` lists (no nesting), `|` tables,
  `![alt](img/x.webp "caption")`, `**bold**`, backticks, `[t](#anchor)`.
- `**label**{ui}`: a label of the console as it reads on screen (a button,
  a dialog's title, a chip's state). The `{ui}` is not shown; it is what
  the check finds in `index.html`. A label the page builds at run time is
  written as shown, with `N` or `…` for what it fills in ("Delete N").
- `img/*.webp`: the pictures, at 6-25 KB each (192 KB together), made by
  `pictures.sh` (README.md) from `lcars-ui/test/shots.py`'s frames and
  `shots_crew.py`'s (the crew's views, which need made-up crew rows).
- `{{KEYS}}` and `{{PHRASES}}` in the appendices: the tables are made at
  every build from `index.html`'s `KEYS` and `VCMDS` by `cmds.js` (node:
  each array cut from its `const NAME = [` line to the first `];`,
  evaluated with every other name a no-op). Never kept by hand. `PLAIN` in
  `build.py` says a few help strings in a reader's words.

The framings the manual holds word for word (the entry, the kind, the crew,
the console, the deck, Number One) are its glossary's.

## 2. Three builds from one source

`python3 site/manual/build.py`:

1. **The landing's page**, `site/landing/public/manual/index.html` and its
   `img/` (copies of the source's): committed, served with the landing's
   assets at `/manual/` under `public/_headers` (its CSP allows the inline
   style and `self` pictures; `/manual/img/*` cached a day like `/shots/`).
   The landing's footer links it ("The manual").
2. **The app's copy**, `lcars-ui/manual/index.html` and its `img/`:
   committed, written by the same run as the landing's. It is part of the
   shipped `lcars-ui/`, so the server serves it at `/ui/manual/` from disk
   and from the embedded pack (`scripts/ui-pack.py`: 13 files, ~300 KB),
   and it ships in the one binary and the open-source release; the demo's
   `static.py` copies it too. `/manual`, `/manual/` and `/ui/manual` answer
   a 301 to `/ui/manual/` (`UIRedirectFor` in `lcars_ui_files.h`, /ui/'s
   auth rule: none from loopback). `/ui/` sends no CSP header (index.html's
   own is a `<meta>`), so the inline style needs nothing. `sw.js` leaves
   `manual/` to the network: a navigation missing from its cache is
   answered with the console, so the manual's first opening would have
   been the console; the manual needs no offline copy. The console's doors:
   **The manual** at the foot of the help (both the keyboard's and the
   voice's), the palette's "app · the user manual", and "computer, open the
   manual" (`openManual`, a tab of its own: the console stays as it was, an
   edited entry with it; a spoken order is no tap, so a refused tab becomes a
   toast whose Open is). `test/uigzip.py` holds the serving.
3. **The report**, `build.py --inline OUT`: one file, the pictures as
   `data:` URIs, under 400 KB, for the media store, where the HTML report
   sandbox allows no other file. Never committed: built when published.

None carries a script. The landing's adds the landing's Antonio face and a
link home, the app's a link to the console (`../`); the report and the
app's copy use the system faces.

## 3. The version: a placeholder

Under the title: "For LCARS X.Y.Z". `APP_VERSION` changes at every deploy
(version-at-deploy.md), so a number baked into the committed page would
make it stale each time. The committed page carries `__VERSION__`, as the
landing's pages carry `__SITE__`:

- `site/landing/deploy.sh` fills it in its staged copy from
  `../../lcars-ui/index.html`'s `APP_VERSION` (`$LCARS_LANDING_APP_PAGE`
  another copy), refusing a page without a plain X.Y.Z;
  `preview.mjs` does the same for the preview.
- `build.py --inline` fills it with the checkout's `APP_VERSION`, or
  `--version V`.
- The app's copy names no number: "For the console it came with". It is
  served by the server it shipped in, so it is always that console's
  manual; a number would need the deploy to stamp a second file beside
  `APP_VERSION` (version-at-deploy.md) for no news the console's own badge
  does not already give. Nothing in the deploy's stamping changed.

## 4. The check: `site/manual/test/manual.py`

About a second, in `lcars-ui/test/run.sh`'s every run (beside the version
check), so every deploy runs it. It fails when:

- (a) a committed build (the landing's, the app's) is not what
  `build.py` makes of the source now. A changed help string in `KEYS` or `VCMDS` makes it stale:
  run `python3 site/manual/build.py` and commit what it writes.
- (b) a `"computer, …"` the pages quote is no order in `VCMDS` (its say or
  an alias, `{*}` and `{n}` standing for any words);
- (c) a key the pages name in bold (`**n**`, `**[**`, `**Ctrl+S**`) is not
  in `KEYS` (a glyph button such as `**+**` or `**⋯**` excepted). The keys
  appendix is `KEYS` itself, held by (a);
- (d) a `**label**{ui}` is not text in `index.html` (its entities read;
  `N`, a number or `…` split the label, each part found);

and when the report's inline build is over 400 KB, or a `[t](#id)` has no
heading. CLAUDE.md's rule: a change to the web UI that the manual describes
updates its page and rebuilds it.

What it cannot see: a sentence that is no longer true while every label in
it still exists, and a picture that no longer shows the view. Those are the
engineer's, at the change.

## 5. Publishing

- **The landing's** is the captain's `site/landing/deploy.sh`, by hand,
  with the rest of the landing page, which itself waits on the captain
  (TODO.md). Nothing in the deploy publishes it.
- **The report's**, `media/reports/2026/10/the-console-a-user-manual-f3f3e65d.html`
  (`MANUAL_REPORT` in `scripts/engineer.py`; `$LCARS_MANUAL_REPORT`,
  empty to turn it off): the deploy writes it over in place. In
  `land_commits`, after the merge, the push and the release entries,
  `manual_report` looks at the files `prev..new` changed; when one is under
  `site/manual/`, `site/landing/public/manual/` or `lcars-ui/manual/`
  (`MANUAL_PATHS`) it runs `build.py
  --inline` in the live checkout (the version the deploy just stamped) and
  `scripts/report.py update REL FILE`, which keeps the URL, the title and
  the entry (reports-as-entries.md). Its outcome is a line in the deploy's
  message; a failure is said there and never fails the deploy (by hand:
  `build.py --inline F`, then `report.py update REL F`).
  `scripts/test_version_stamp.py` holds it, with both scripts stood in for.
