# The version number, given by the deploy

Lieutenant Torres, 2026-10-22, at main `d60dc81` (0.296.4). Number One's
order: version numbers collide (four engineers took 0.296.5 or 0.297.0
within one hour, and none of them had landed), and with more seats awake
at once (docs/design/job-queue.md, "More than one") it gets worse. On
10-14, 11 of 29 failed deploys were CHANGELOG or APP_VERSION conflicts.
**Design only.** It is built on the captain's word. Marked **[captain]**:
his to settle.

## The idea

An engineer no longer picks a number. They write their entry under a
placeholder heading that says what kind of bump it is, and leave
`APP_VERSION` alone. The deploy holds `deploy.lock`, so it is the only
writer of main at that moment. At rebase it gives each placeholder the
next free number, writes the heading, `APP_VERSION` and the commit's
subject, and so merges entries that are only stacked at the top of
CHANGELOG.md. A number exists only once it is on main. Two branches can
never hold the same one.

## What the engineer writes

```
## next patch — 2026-10-22        (or: ## next minor — 2026-10-22)

- **ops:** ...
```

- One placeholder per commit that needs an entry: a fix or polish is
  `patch`, a feature `minor`. A major is the captain's and is written by
  hand on main. The date is the engineer's. The deploy rewrites it to the
  day the version lands (that is what the date has always meant to a
  reader).
- `APP_VERSION` in `lcars-ui/index.html` is **not touched**. It stays
  main's number until the deploy sets it. That one change removes the
  index.html conflict on line 10 entirely.
- The commit's subject ends `(patch)` or `(minor)` instead of
  `(0.296.5)`. The deploy writes the number in.
- Placeholders sit above every numbered entry. A branch of several
  commits has several, newest on top, each in its own commit.

## The deploy

In `do_deploy`, under `deploy.lock`, in place of today's bare `git rebase`:

1. **The floor.** `floor = max(the top numbered heading of main's
   CHANGELOG, the highest version in deploy history)`. The history counts
   rolled-back deploys too: after a rollback main's top goes back down,
   but phones may already hold the rolled-back page. A number reused for
   other code would never be offered to them as an update. So a number is
   never given twice.
2. **The rebase, with the stamp after each commit**: `git rebase -x
   "python3 scripts/version-stamp.py" <live>`, with `LCARS_VERSION_FLOOR`
   set. After each commit is replayed, `version-stamp.py` looks at what
   that commit added to CHANGELOG.md. With no placeholder it does
   nothing. With one it takes `next = bump(max(floor, the numbered top
   below it), kind)`: patch is `x.y.z+1`, minor `x.y+1.0`. It rewrites
   `## next patch — <date>` as `## 0.296.5 — <today>`, sets
   `APP_VERSION`, replaces the subject's `(patch)` or `(minor)` with
   `(0.296.5)` (or appends it), and runs `git commit --amend --no-edit`
   with the new message. Its next commit's floor is that number, so a
   branch's entries are numbered in order.
3. **A stacked top merges by itself.** `.gitattributes` gets `CHANGELOG.md
   merge=lcars-changelog`. The deploy sets `git config
   merge.lcars-changelog.driver "python3 scripts/changelog-merge.py %O %A
   %B"` in the repo's config, idempotently. The worktrees share that
   config, so an engineer's own `git rebase main` gets the driver too. A
   fresh public clone lacks it, and git falls back to its own merge,
   harmlessly. The driver splits base, ours and theirs into the preamble
   and the `## ` entries. It succeeds only when:
   - each side's entries are new ones on top of the base's entries;
   - any old entry changed on only one side (that side's version is
     kept);
   - any preamble change is on only one side.

   The result is the preamble, then theirs' new entries (the commit being
   replayed, which the stamp will number next), then ours' new entries
   (main's), then the base's. Anything else, such as an old entry edited
   differently on both sides, or a new heading below an old one, exits 1
   and leaves git's own conflict markers.
4. **Checks before the web suite**: no placeholder is left anywhere in
   CHANGELOG.md; the numbered headings strictly decrease from the top;
   the top is above the floor and equals `APP_VERSION`. Any failure
   aborts the deploy before anything lands (`git rebase --abort` is not
   needed, since the rebase finished). Then `web_suite` and `land_commits`
   run as today. The stamp's hunk changes only `APP_VERSION`, which
   `changed.py` already does not count as a page change, so the suite's
   scope is unchanged.
5. **The outcome says the number**: `deployed kim-c32 as 0.296.5: ...`,
   and `[deploy finished]` names it, so that the engineer's report and
   Number One's say the number. `versions_in` reads the stamped subjects,
   as it does now. The deploy history and the Queue view's versions are
   unchanged.

The engineer's branch after a deploy is the stamped one, as their branch
is the rebased one today. Their next order finds it at main.

## A real conflict

Anything the driver will not take (an old entry edited on both sides),
a conflict in any other file, or a stamp that fails (two placeholders in
one commit, a placeholder below a numbered entry, a commit that changed
`APP_VERSION` by hand) stops the rebase. The deploy aborts it, as today,
and the failure names the file and the reason: `CHANGELOG.md: an old
entry (0.295.2) edited on both sides`, or `a1b2c3d sets APP_VERSION by
hand: leave it, the deploy numbers it`. The engineer rebases, resolves
and commits. Their placeholders stay placeholders, and the next deploy
numbers them. Nothing is half-landed: the stamp amends only the
engineer's branch, and main moves only in `land_commits`.

## What reads the version

| reader | now | with placeholders |
|---|---|---|
| `run.sh`'s check | CHANGELOG's first `## X.Y.Z` = `APP_VERSION` | moved to `test/version.py` (testable): the top is numbered and equal to `APP_VERSION` (main, as now), **or** one or more placeholders on top, with `APP_VERSION` equal to the first numbered heading below them ("leave APP_VERSION alone: the deploy numbers it"). The line says `ok (0.296.4 + next patch, numbered at deploy)`. A placeholder below a number, a bad kind, or two in one commit (read from `git log`, when there is one) fail |
| the page's update check (`verCmp`, `updNewer`) | the server's `APP_VERSION` > the page's | unchanged. Numbers only go up on the server, because they are given in landing order from a floor that includes rolled-back versions. A rollback still serves a lower number, which `updNewer` (correctly) does not offer; the next deploy goes above the one rolled back |
| the Makefile, `lcars version`, `release/check.sh`, `package.sh`, `release.yml` | the first `## X.Y.Z` | unchanged. They skip a placeholder (not digits), so a worktree's build says main's number. A release is tagged on main, which is always numbered |
| `changelog_heads`, the Queue view | numbered headings | unchanged: placeholders never reach main |
| `export-public.py` | the public CHANGELOG from main's | unchanged; refuses a placeholder as a belt to the deploy's check |
| **the explainer** (`version.mjs`, `page.py`, the title and end cards, the poster `deliver.sh` makes) | `APP_VERSION` at bundle time | a tree with a placeholder on top is not numbered yet, so `version.mjs` and `page.py` show `0.296.4+`: main's number plus a mark that the cut is not a release's. **`deliver.sh` refuses a placeholder-topped tree** ("deliver after the deploy has numbered this tree"): a poster or web file that ships must print a real number. A delivered cut is made from the stamped branch after its deploy, as its own follow-up commit. It then prints the version of the code it shows, not of its own commit. That is the card's meaning today (the version of the tree it was made from). **[captain]**: the alternative, the deploy re-rendering, is minutes of exclusive cores per deploy and is not proposed |

## The rules, as the brief and CLAUDE.md will say them

- CLAUDE.md, "`CHANGELOG.md` holds the version": write your entry under
  `## next patch — <date>` (fix, polish, internal) or `## next minor —
  <date>` (a feature), one per commit, on top. Do not touch `APP_VERSION`.
  End the subject `(patch)` or `(minor)`. The deploy gives the number and
  writes the heading, `APP_VERSION` and the subject. A major is the
  captain's.
- `brief_seat`'s line "CHANGELOG.md and APP_VERSION" becomes "a
  placeholder CHANGELOG entry (the deploy numbers it)". The report names
  the number from `[deploy finished]`, and reports before a deploy say
  "patch, unnumbered".
- `brief_no1`: check for "a placeholder entry of the right kind", not "a
  bumped version". A `[deploy finished]` line carries the number.
- Number One's own `crew deploy` takes the same path, so it needs nothing
  of its own.
- **The switch-over**: entries already written with a number on unlanded
  branches are renumbered by the stamp if their number is not above the
  floor (minor if it ends `.0`, else patch), and kept if it is. So
  nothing written in the old way has to be redone, and the old way keeps
  working until the briefs change. The one thing that conflicts is an
  `APP_VERSION` edited by hand. For the switch-over the stamp resets that
  line to the floor before the rebase (one commit on the branch, `Leave
  APP_VERSION to the deploy`), and after it, the check refuses it.
  **[captain]**: switch over in one deploy, or keep the old way accepted
  for a week.

## Tests

`scripts/test_version_stamp.py` (~3 s, scratch git repos):

- the stamp: patch and minor from a floor, a floor from history above
  main's top (a rollback), three commits on a branch numbered in order,
  a mixed minor-then-patch (0.297.0, then 0.297.1), the subject's
  `(patch)` replaced and a subject without it appended, the date
  rewritten, an old-style number below the floor renumbered and one
  above kept, and the refusals (two placeholders in a commit, one below
  a number, a bad kind, `APP_VERSION` edited by hand);
- the merge driver: two stacked tops in both orders, a preamble change on
  one side, an old entry edited on one side, the same old entry edited on
  both sides (exit 1, markers), and a heading inserted below an old one
  (exit 1);
- end to end: a scratch "live" repo and two engineer branches, both
  `## next patch`, each started from the same main. The first deploys,
  the second rebases through the driver and the stamp and lands as the
  next number. The second's own `git rebase main` beforehand resolves too.
  Checked: no placeholder on main, `APP_VERSION` equal to the top,
  `versions_in` on the subjects, and `do_deploy`'s abort leaving the
  branch as it was on a real conflict;
- `test/version.py`'s check: numbered, placeholder-topped, a placeholder
  below a number, and `APP_VERSION` moved under a placeholder (fail).
  run.sh calls it in place of its inline grep;
- `test_deploy_suite.py`: the stamp's hunk is not a page change;
  `test_queue.py`: the deploy history's versions from stamped subjects;
- `video/explainer`: `version.mjs` shows `0.296.4+` under a placeholder,
  and `deliver.sh` refuses (a 1 s shell check, no render).

## Slices

| slice | what | estimate |
|---|---|---|
| 1 | `version-stamp.py`, `changelog-merge.py`, `.gitattributes`, `do_deploy`'s floor, rebase `-x` and checks, the outcome's number; `test_version_stamp.py` (patch, ops) | 30 min |
| 2 | `test/version.py` in run.sh, the explainer's `+` and `deliver.sh`'s refusal, `export-public.py`'s refusal (patch) | 15 min |
| 3 | the rules: CLAUDE.md, `brief_seat`, `brief_no1`, the switch-over (patch; the first commit written the new way) | 10 min |
