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

**A deploy that fails after the rebase puts the branch back** (25 Oct
2026): the web suite, the checks, the merge or the rebuild failing left
the branch rebased and numbered, and its next deploy refused the stamp's
own `APP_VERSION` as one set by hand. `do_deploy` keeps the branch's ref
before the rebase (`branch_before` in the deploy's state, and a line in
the log) and, on any failure after it, resets the branch there
(`restore_branch`); the failure message says so (`eng/x is put back at
a1b2c3d4, as it was before the deploy`), or that it could not be, to be
done by hand. A retry then rebases and numbers afresh. The reset was
chosen over teaching the pre-check to accept the deploy's own stamp:
the branch is the engineer's, and one state is simpler to reason about.

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

## As built: slice 1 (0.299.1)

The captain approved the build (ask 9819), switching over in one deploy,
with no explainer re-render per deploy.

- **`scripts/version-stamp.py`**, run by `git rebase -x` (an up-to-date
  branch is replayed too: `-x` always runs). Its decision is `plan(new,
  old, floor)` (pure): the headings the commit added are the ones above
  HEAD^'s, matched from the bottom (two entries can carry one heading:
  two branches that picked the same number the old way). Numbered as the
  design says. An old-style number above `max(floor, the one below)` is
  kept with its date; one not above is renumbered (minor if it ends .0)
  and dated today. The day is `LCARS_TZ`'s (the captain's). Refused (the
  rebase stops; the deploy aborts it and the failure says why: `could not
  be numbered: <sha>: ...`): two entries in a commit, a kind other than
  patch or minor, a heading that is neither, a placeholder below a
  number, an entry below the top added, changed or moved. **Not refused
  yet: `APP_VERSION` edited by hand.** Every commit made the old way
  does that, and the stamp overwrites it anyway. Until slice 3's
  switch-over, two branches that both moved it still conflict on
  index.html at rebase, as before.
- **`scripts/changelog-merge.py`.** The rule changed from the design's.
  In a rebase, "ours" is main *plus the branch's earlier commits*,
  already stamped. Their entries sit above main's, and their headings
  changed (`next minor` became `0.6.0`), so "both sides only stack on
  top of the base" does not hold for a branch of two commits. The
  driver's rule instead: theirs (the commit replayed) may only have put
  entries on top of the base, with the base's headings in order below
  them. Ours is taken whole. Theirs' new entries go on top of it (one
  already in ours, by its text, is dropped). An old entry theirs edited
  is carried into ours if ours still has it as the base had it, and is a
  conflict if ours changed it too - except when ours changed only its
  heading (one entry of ours, not an old one, with the base's text under
  another heading) and theirs only its text: that is a review-fix commit
  editing the branch's own entry, which the replay of the earlier commit
  has numbered, and ours' heading goes over theirs' text (as git's own
  merge would: separate hunks). Exit 1 runs `git merge-file`, so the
  markers are git's own.
- **A commit that adds no entry** has its subject's mark mended: `(patch)`
  or an old-way `(X.Y.Z)` would otherwise go into the history as a
  stale or another branch's version. It takes the branch's current top
  when that is one of the branch's own (above the floor), else the mark
  is dropped; `versions_in` lists each version once. The heading is
  found on its own line (`^## <h>$`), never in a mention in the preamble.
  The stamp's `LCARS_TZ` is the deploy's environment's, else `~/.env`'s
  (`stamp_env`, by `setting()`), as the server's unit reads it.
- **The deploy** (`do_deploy`): `version_floor(lb)` (main's top, and
  every `versions` in deploys.jsonl), `changelog_driver()` (sets
  `merge.lcars-changelog.driver` to the live checkout's script, by
  absolute path, so a worktree whose tree predates the script still gets
  it; idempotent), the rebase with `LCARS_VERSION_FLOOR`, its output in
  the deploy log, and `version_check` before the web suite. The check
  wants: no placeholder; numbered headings strictly falling; and, if the
  branch changed the top, the top above the floor and equal to
  `APP_VERSION`. A branch that added no entry passes, as before. The
  outcome: `deployed <name> as <v>[, <v>]: ...`, oldest first, from
  `versions_in` of the landed subjects.
- **`.gitattributes`**: `CHANGELOG.md merge=lcars-changelog`.
- **Tests**: `scripts/test_version_stamp.py` (25 tests, ~5 s). The
  plan; the driver (both orders, one-sided edits, the conflicts and
  their markers); and `do_deploy` end to end on a scratch live checkout
  with two worktrees: two placeholder branches from one main (one of
  them two commits, minor then patch), with and without the engineer's
  own rebase; the old way colliding and renumbered; a rolled-back floor;
  a real conflict and a refused stamp, each leaving the branch as it
  was; the checks; the config set once; a review fix editing the
  branch's own entry (a placeholder, and an old-way number renumbered,
  each with and without the engineer's own rebase), behind a commit with
  a stale mark; the zone read from `~/.env`.

## As built: slice 2 (0.299.4)

- **`lcars-ui/test/version.py`**, run.sh's version check (its inline
  grep retired). `check(changelog, page, commits)` is pure: numbered
  (the top equal to `APP_VERSION`: `ok (0.299.2)`), or placeholders on
  top with `APP_VERSION` left at the number below them (`ok (0.299.2 +
  next patch, numbered at deploy)`). Fails: a placeholder below a
  number, a kind other than patch or minor, a top that is neither, and
  `APP_VERSION` moved under a placeholder. With a base (`--base`, run.sh
  passes `CHANGED_BASE`, default main; none in a fresh clone: skipped),
  each commit since the merge base and the worktree's change may add one
  entry at most, as the stamp numbers them. Self-contained, not an
  import of the stamp: it ships in the public tree's run.sh.
- **The explainer**: `version.mjs`'s `appVersion()` and `page.py`'s
  `VERSION` add `+` when CHANGELOG.md's top is a placeholder;
  `deliver.sh` refuses such a tree before anything is encoded
  ("deliver after the deploy has numbered this tree").
- **`export-public.py`** refuses a placeholder anywhere in CHANGELOG.md
  before it writes DEST; `--audit-only` still runs on a branch.
- **Tests**: test_version_stamp.py's `Check` (the shapes and failures,
  two entries in a commit, the explainer's `+` through node and
  deliver.sh's refusal in a scratch tree) and test_export.py's placeholder
  case.

## As built: slice 3

- **The rules**: CLAUDE.md's "`CHANGELOG.md` holds the version, and the
  deploy gives it", CHANGELOG.md's own preamble, `brief_seat` (the
  placeholder entry, "patch, unnumbered" in a report before the deploy,
  the number from `[deploy finished]` after it) and `brief_no1` (review
  for a placeholder of the right kind; `[deploy finished]` names the
  number). They reach a session from its next start after the deploy:
  `do_deploy` runs the live checkout's `engineer.py`.
- **The stamp runs only in the deploy's rebase.** It used to take no
  arguments: an engineer ran `version-stamp.py --help` to read its usage,
  and it numbered their placeholder against a floor of 0.0.0 (0.299.5) and
  amended the commit (4a9468f, reported as "a hook wrote it"; there is no
  hook). Now any argument prints the docstring and changes nothing (exit
  0 for `--help`, 2 otherwise), and with no `LCARS_VERSION_FLOOR` or no
  rebase in progress (`git rev-parse --git-path rebase-merge`) it says so
  and exits 2.
- **The switch-over's refusal**, before the rebase: `hand_set_versions`
  (engineer.py, by the stamp's `hand_set`) walks the branch's commits, and
  one that adds a placeholder and moves `APP_VERSION` fails the deploy
  with `<sha> sets APP_VERSION by hand under a placeholder: leave it, the
  deploy numbers it`, the branch untouched. It is put back in that commit
  (amended, or rebased): a later commit undoing it would still conflict
  when the first is replayed over a main that moved the line. An old-way
  commit (its own number, `APP_VERSION` set to it) is not refused: the
  stamp renumbers it, and two of them at different numbers still conflict
  on index.html as before. The design's alternative, resetting the line on
  the branch before the rebase, was not built: it rewrites the engineer's
  commits outside the deploy's one rebase, and after the briefs change no
  one writes the old way.
- **Tests**: test_version_stamp.py's `Deploys` - the stamp by hand
  (`--help`, an unknown argument, no floor, a floor and no rebase: HEAD,
  the tree and the placeholder unchanged; the deploy then numbering it),
  and the refusal (the sha named, the branch as it was, put back by an
  amend and landed; an old-way branch passing the check).

## As built: fragments (2026-10-24)

Number One's order, the captain's word: parallel engineers must not
conflict on files they both only append to. The placeholder still had
every branch edit the top of CHANGELOG.md (the merge driver took most of
it, but a branch had to rebase through it) and TODO.md collided outright.

- **The fragment.** An engineer never edits CHANGELOG.md. A commit that
  needs an entry adds `changelog.d/<name>-<slug>.md`: first line `minor`
  or `patch`, then the entry's text. `changelog.d/README.md` says the
  format, and is never a fragment (a fragment's name is lowercase
  `[a-z0-9][a-z0-9._-]*.md`).
- **The stamp** (version-stamp.py, still the rebase's `-x`): after the
  placeholder (numbered first, as before), each fragment the commit
  *added*, in name order, becomes `## X.Y.Z — <today>` with its text on
  top of CHANGELOG.md, X.Y.Z = bump(max(floor, the top number), kind);
  `APP_VERSION` and the subject take the highest given. The fragment is
  **not** deleted in that commit: a later commit of the branch that edits
  it (a review fix) must still apply in the replay. A fragment *edited*
  replaces its section's text, its number kept; one *deleted* takes its
  section out (and `APP_VERSION` follows the top down). Which section is
  whose is the rebase's own record, `lcars-fragments.json` in git's
  `rebase-merge` directory, gone with the rebase.
- **The finish** (`finish`, called by `do_deploy` right after the rebase,
  before `version_check`): every fragment in the branch's tree that the
  live branch lacks is `git rm`'d and the last commit amended. What lands
  holds none; `version_check` fails a deploy that would leave one.
- **Two fragments at once** are numbered in turn: two in one commit by
  name, two in two commits by commit, two branches by deploy. A fragment
  and a placeholder, either order, either commit, number in turn.
- **The transition.** The placeholder is retired but still numbered; both
  shapes pass `lcars-ui/test/version.py`, the explainer and
  `export-public.py` treat a fragment as unnumbered as they do a
  placeholder. `hand_set` refuses a commit adding a fragment and moving
  `APP_VERSION`, as it does a placeholder.
- **TODO.md** merges with git's built-in `union` driver
  (`.gitattributes`): both sides' added lines kept, order not
  guaranteed. A rebase uses merge drivers, the deploy's included
  (`test_todo_items_at_one_place_both_land`).
- **Tests**: test_version_stamp.py - a fragment alone; two from one main
  across two branches, and two in one commit; a fragment plus a
  placeholder (both orders, and in one commit); a review fix editing the
  fragment and a later commit deleting another; a bad one (kind, no text)
  failing the deploy with the branch as it was; `APP_VERSION` set by hand
  with one; one left failing the check, the README not one; TODO.md's
  items from two branches at one place. `Check.test_fragments` for
  run.sh's check, test_export.py's `test_a_fragment_refused`.

