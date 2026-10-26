# Release entries: every deployed version in the journal

Status: built (engineer.py's deploy, `scripts/release-import.py`). The
console's side (Sato) reads them; this note is the format both keep to.

## Why

The console should show what changed, version by version, without reading
CHANGELOG.md off the box: a release is journal state the captain should
see, so it is an entry (CLAUDE.md, "State the captain or the crew should
see lives in the journal"), searchable, backed up and shown like any other.

## The format

One entry per version:

- `kind` `release`
- `title` the version alone: `0.323.5`
- `created_at_utc` the deploy's time (the import's: see below)
- `content`:

      release:: 0.323.5 2026-10-24

      - **web** UI research slice A, ...

  Line 1 is `release:: <version> <date>`, the date the CHANGELOG
  section's own (`## 0.323.5 — 2026-10-24`, the captain's day the stamp
  numbered it); a blank line; then the section's text exactly as
  CHANGELOG.md holds it - every line between its heading and the next
  `## `, markdown and all, the blank lines at either end dropped.

An entry is found by its first line: a version is in the journal when an
entry of kind `release` begins `release:: <version>`, deleted or not.

## Who writes them

- **The deploy** (`engineer.py`, `land_commits` -> `release_write`), as the
  captain's login (LCARS_AUTH_USER/_PASS, the environment then ~/.env,
  through `scripts/journal_api.py`, shared with `report.py`). After the
  fast-forward, the rebuild if C changed, and the push - so a deploy that
  fails writes nothing. The versions are the CHANGELOG sections the new
  live head has and the old one had not: every one the deploy numbered, a
  commit with two fragments included (its subject names only the last).
  Written oldest first; the entry ids are named in `[deploy finished]`
  (`release entries: 0.6.0 #812, 0.6.1 #813`). A write that fails does
  not fail the deploy - the code is live by then: the line says `release
  entries NOT written: <version> (<why>)`, and the import catches it up.
  A version the journal already has is not written twice.
- **The import**, `scripts/release-import.py [--apply] [--json]`: every
  numbered section of CHANGELOG.md (a backported heading's `` · `hash` ``
  suffix included) whose version no entry has, made oldest first - a dry
  run listing them unless `--apply`. A release whose entry the captain
  deleted stays deleted. It runs any number of times. The CHANGELOG
  holds no time of day, so `created_at_utc` is the section's date at
  **12:00 in the captain's zone** (LCARS_TZ, the environment then
  ~/.env; the box's own zone when unset). `LCARS_CHANGELOG` points it at
  another file (the tests).

The first live `--apply` is Number One's word (617 versions at 0.323.5).

## Tests

`scripts/test_version_stamp.py` ("the release entries"): a deploy of one
version and of two (in one commit), a deploy that numbers nothing, the
write failing (the journal down, a POST refused) with the deploy landed,
and a failed deploy writing nothing. `scripts/test_release_import.py`:
the sections, the entry, noon in the zone, and the import on a scratch
server twice (dry run, apply, apply again with one deleted).
