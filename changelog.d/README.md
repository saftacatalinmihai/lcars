# changelog.d - the entries waiting for their number

An engineer never edits CHANGELOG.md: each change brings one file here,

    changelog.d/<name>-<slug>.md      e.g. obrien-c33-changelog-fragments.md

`<name>` the engineer's (their branch `eng/<name>`), `<slug>` a few
lowercase words of the change, `[a-z0-9._-]`. Its first line is the
intent, `minor` (a feature) or `patch` (a fix, polish, an internal
change); the rest is the entry's text as CHANGELOG.md has it:

    minor
    - **web** The thing, what it does and why.

The deploy (scripts/version-stamp.py, in its rebase) numbers it above
everything deployed, puts it on top of CHANGELOG.md as `## X.Y.Z — <date>`,
sets `APP_VERSION`, and deletes the file. A review fix edits the fragment.
Leave `APP_VERSION` alone. docs/design/version-at-deploy.md has the whole.
