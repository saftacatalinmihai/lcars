# Reports as journal entries

The captain's order (2026-10-24): a report is a journal entry, so the
console finds it like any entry - searched, shown, kept with the journal -
and the Reports page no longer reads the NAS over NFS (it was slow). The
file stays in the media store where `scripts/report.py` puts it, so every
link already handed out keeps working. This is the first instance of the
rule in CLAUDE.md: a feature keeps its data as entries wherever it can.

## The format (shared with the console's side; do not drift)

An entry of kind `report`, its title the report's title, `created_at_utc`
the publish time (the sidecar's `published_utc`), and content:

    report:: <type> <rel>

    <the file's whole text>

- line 1: `<type>` is `html|md|txt|csv|pdf|png|zip|other` (from the file's
  extension; `.htm` is html, `.markdown` md, anything else not named
  `other`), `<rel>` the media path as `report.py list` gives it,
  `media/reports/YYYY/MM/<name>` (its link is `/<rel>`);
- for html, md, txt and csv: a blank line, then the file's whole text
  (UTF-8, invalid bytes replaced; CRLF made LF; control characters other
  than tab and newline dropped, as the server's JSON reader cannot carry
  them);
- for the binary types: line 1 alone. The entry is the link.
- an html, md, txt or csv entry with nothing after line 1 is a report too
  big to embed (below): the file is published as ever, the entry is the
  link, and the console shows it as one.

The first line is how an entry is tied to its file: `report.py` finds a
report's entry by it (the lowest id holding it).

## Who writes

`scripts/report.py publish` and `update`, after the file is in place, as
the captain's own login (`LCARS_AUTH_USER`/`_PASS`, the environment, then
`~/.env`; the server at `$LCARS_URL`, else `LCARS_CREW_URL`, else
`127.0.0.1:8080`). The reports are his; no login's allowed kinds changed.
`no1.py report` goes through `report.py`, so Number One's reports get
their entry the same way (its `no1_log` line is written as before).

- `publish`: the file and sidecar, then `POST /entries`. `--json` adds `id`.
- `update`: refreshes (PATCH title and content) the live entry whose first
  line names the report, or makes one for a report from before this.
- the entry failing after the copy (the server down): the link is printed
  all the same, the failure on stderr (`error` in `--json`, `id` null),
  exit 3. `import --apply` writes it later.

## The size cap

`HTTP_MAX_BODY_BYTES` in `lcars_http.h`, 512 KiB: a request body over it is
a 413. `report.py` refuses an entry whose JSON body is over 512 KiB less
4 KiB (`ENTRY_BODY_MAX`, 520,192 bytes): `GET /dump`, the console's cold
load, builds each row in the connection's 1MB arena by doubling, so a
row's JSON must stay under 512 KiB, and a row carries ~250 bytes of fields
the POST body does not. Measured on a scratch server: a 523,313-byte body
of HTML round-trips through POST, GET, `/dump` and PATCH; 531,676 is
refused. A text report whose entry would be over it gets the first line
alone, as a binary one does (the captain's rule: huge text stays a file,
the entry is how he finds it); an update that crosses the cap either way
moves the entry with it. Nothing is refused for its size but the store's
own `MAX_BYTES` (1 GiB, as an upload).

### The cold load

The cap keeps a row within the arena, not out of the cold load: 111 text
reports (~3.9 MB, pictures inlined in base64, which gzip cannot shrink)
took the 4000-row journal's `GET /dump` from 85 KB gzipped to 1.9 MB and
the phone's first paint from ~690 ms to 1.0-1.5 s. So the server leaves a
report's text out of the bulk reads (`AppendEntryJSONAs` in `lcars_http.h`):

- `GET /dump` sends a `report` row's content as its first line alone, no
  newline, `content_length` still the whole row's; `report_body=1` sends
  it whole. `GET /entries` does the same only with `report_body=0` (the
  page's paged sweep asks for it; the CLI and the crew read it whole), and
  `GET /entries/<id>` is always whole.
- The console (`bodyCut`): a report whose content has no newline and is
  shorter than its `content_length` has a body not loaded yet -
  `needsBody` is true for it, but the load owes it nothing (`bodyMissing`,
  `st.bodies`). The list and the Reports page read its type from the
  first line, with no fetch; the reader and the editor fetch it whole on
  opening, as for a row the sweep has not reached. A report that is its
  first line alone (binary, or too big) has its length equal: still the
  link. Search finds a cut report by its title and first line only, until
  it has been opened.
- `perf.py coldload` holds it: the cold boot through `/dump` with 111
  reports within 1.3x (+150 ms) of the boot without, by the medians of
  first paint and of the load's end. Measured: first paint 682 -> 1030 ms
  with the bodies, 683 -> 693 ms cut; `/dump` 1941 KB -> 85 KB gzipped.

## The reader

An HTML report is drawn from the entry's own text in a `srcdoc` frame with
`sandbox=""` (no script, an opaque origin, no way to the top window); the
file itself is a round trip to the NAS, the text is already in the page and
offline. Two things follow from that, and are handled (`reportReadHtml`):

- **Pictures by a relative path.** A srcdoc document has no address: a
  relative `<img src="chart.png">` resolved against the page (`/ui/chart.png`)
  and drew nothing. `reportBased` puts `<base href="<media>/reports/YYYY/MM/">`
  in after the doctype (before it would be quirks mode), so the path is the
  file's folder's, as when the file is opened; a report with a `<base>` of
  its own keeps it. Absolute `/media/...` pictures and `data:` ones drew
  already: `/media/` asks no password from loopback (tailscale serve), and an
  `<img>` sends none anyway, so the frame's opaque origin loses nothing.
- **Open as a page in view.** The frame is the pane's height and scrolls
  inside itself, so the row under it is below a phone's fold. The reader's
  head carries **Open as a page** (`reportHeadLink`, 44px, the desk the
  same): the file's URL in a tab of its own, its script with it; the tap
  is pressed and says "opening…" (`reportPress`). The palette has "entry ·
  open the report as a page, in a tab". A voice order is no gesture, so
  "open the report (as a page)" opens the in-app viewer (`reportHere`), the
  file framed with its script. The row under the frame stays, the viewer's.
  A link-only report (binary, too big) has no head link: its row is first.

## The import

`report.py import` walks the store, oldest first, and for each report whose
first line no report entry holds - deleted ones included, so an entry the
captain deleted stays deleted - would make one, `created_at` the sidecar's
`published_utc` (the file's mtime without one). A dry run unless
`--apply`; idempotent, so it runs any number of times. Run on the live
journal once, when Number One gives the word.

On 2026-10-24, the NAS's 163 reports against a scratch journal: 163 to
make, 52 of them the link alone (all HTML with their pictures inlined, 0.8
to 14 MB). The live import waits for the console's side to be deployed,
so no entry shows raw; Number One gives the word.
