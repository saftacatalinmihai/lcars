# LCARS as an omarchy plugin — design

The captain's order (26 Oct 2026, through Number One): an omarchy plugin,
listed on plugins.omarchy.org, that opens the web console as an app from
the desktop, with two setups - the whole system run locally from the
public GitHub release (one static binary, `lcars init`, a systemd user
unit), or the address of a server the user already has. O'Brien builds
the installer for both (`scripts/omarchy/lcars-webapp`); the theme hook
(`scripts/omarchy/lcars-theme-set`, theming.md) exists. This note is the
plugin around them (zimmerman-c39). Built as section 7's step 3; "As
built" notes below say where the build differs from the first draft.

Sources, read 26 Oct 2026: plugins.omarchy.org's develop and publish
pages; omarchy's `manual/32-shell-plugins.md`, `docs/omarchy-shell.md`,
`shell/plugins/README.md`, `bin/omarchy-plugin-validate`,
`bin/omarchy-launch-webapp`, `bin/omarchy-webapp-install`, and the
first-party weather, tailscale and media widgets (github.com/omacom/omarchy
at 4601078); the marketplace's `SUBMISSION.md`
(github.com/omacom/omarchy-plugin-marketplace). A clone is in the
engineer's research folder.

## 0. What a plugin is, and is not

A public git repo with `manifest.json` at its root and QML entry points,
cloned by `omarchy plugin add <url>` into
`~/.config/omarchy/plugins/<id>/` and loaded into `omarchy-shell`, the one
long-lived Quickshell process that draws the bar, panels and menus. It
runs unsandboxed with the user's permissions. Three facts shape this
design:

- **Nothing runs at install.** `plugin add` clones, validates and flips a
  bit over IPC; it "never runs anything from the plugin, never executes an
  install hook, and never asks for sudo". So the binary, the journal and
  the unit cannot be installed by adding the plugin: they are installed by
  the user clicking the widget, which opens a terminal running the
  installer, where they see what it does.
- **No symlinks anywhere in the plugin's folder** (the validator refuses
  one). The scripts it carries are real files in its tree (section 3).
- **Settings are the manifest's `barWidget.defaults` and `schema`.** There
  is no top-level `settings` field: a bar widget declares `defaults` (an
  object) and `schema` (a list of `{key, type, label, …}`, types seen in
  the first-party plugins: `string`, `integer`, `boolean`, `enum`,
  `path`), the bar's widget settings show a form from it, and the values
  are stored inline on the widget's entry in `~/.config/omarchy/shell.json`
  (`{"id": "...", "url": "..."}`), read in QML with `setting(name,
  fallback)` and settable from a script with `omarchy bar set` (the IPC
  `setBarWidget <id> <key> <valueJson> <selectorJson>`). The captain's own
  plugin of the VPS era kept its address the same way (`baseUrl`,
  TODO.md).

## 1. The kind, and what the user sees

**One kind: `bar-widget`.** The LCARS mark (a small two-tone LCARS
elbow, or the letters `LCARS` in the bar's font where an icon reads
poorly) in the bar's `right` section by default.

- **Click**: the console as an app. `omarchy-launch-or-focus-webapp
  <class> "<url>/ui/"` - an LCARS window already open is focused, not a
  second one started. As built, `<class>` is the class Chromium gives an
  `--app` window at that URL (`chrome-<host>_ui_-Default`, computed as
  `omarchy-webapp-window-class` does, in `Model.js`), not the word
  "LCARS", which would also match any window titled so; the launcher
  entry's `StartupWMClass` is the same class, so the bar and the launcher
  open one window. The address is held to a safe set of characters
  because `omarchy-launch-or-focus` eval's its launch command.
- **Right click**: a small popup (a `PopupCard` from `qs.Ui`, as the media
  widget does) with four rows:
  - *Open LCARS* - as the click;
  - *New entry* - the console at `<url>/ui/?capture=1`, the web manifest's
    own "Quick capture" shortcut;
  - *Set up…* - the installer in a terminal (section 2), also what a
    click does while no server is set;
  - *Add to the app launcher* - `omarchy-webapp-install` for the current
    address (the installer's last step, alone), greyed out once the
    `LCARS.desktop` entry exists.
- **Middle click**: check the server now.
- **The one live figure: up or down, nothing more, in slice 1.** The mark
  is drawn in the bar's foreground while `GET <url>/health` answers 200,
  in its `urgent` colour (and the tooltip "LCARS: no answer from <host>")
  while it does not, and dimmed while no server is set (tooltip "LCARS: not
  set up - click to set up"). `/health` needs no login and says nothing of
  the journal (`lcars_http.h`), so the QML holds no credentials. Polled
  every 60 s (a `schema` integer, 15-3600), from QML's own
  `XMLHttpRequest`, aborted by a 3 s timer (QML's XHR keeps no timeout of
  its own): no process per poll; off while no server is set. As built the
  mark is the word `LCARS` in the bar's font, bold (`LC` on a vertical
  bar): an elbow drawn in QML is a later polish, once seen on the bar. A figure from the journal (entries today, open tasks)
  needs the login: a later slice, through `lcars-cli` with the login in
  `~/.config/lcars/env` rather than in QML or shell.json (section 6, Q5).

**Against a `menu` kind.** A menu plugin is summoned by IPC
(`omarchy-shell shell summon <id>`) and has no presence on the bar: the
user would need a key bound to reach it, and the first thing they see
after `plugin add --enable` would be nothing. Omarchy's own menu can
already be extended without a plugin (`~/.config/omarchy/extensions/
omarchy-menu.jsonc`, `action` rows); the README offers that snippet
(an "LCARS" submenu: open, new entry, set up) for those who want it under
Super+Alt+Space. The bar widget is the plugin.

**Later slices, named now so slice 1 leaves room:**
- a `panel` for quick capture from the bar (a text field posting an entry
  through `lcars-cli`, the login staying in the env file) - its own
  design, since it is the first QML that writes;
- the journal figure above;
- the theme hook installed by the plugin's setup, so omarchy's theme
  reaches the console (today the user links it by hand).

## 2. Setup from inside the plugin

**Where the address lives: `~/.config/lcars/env`**, the file the theme
hook already reads (theming.md): `NAME=value` lines, `LCARS_URL`,
`LCARS_AUTH_USER`, `LCARS_AUTH_PASS`, mode 0600. One file for the widget,
the hook and `lcars-cli`, so a user sets their server once. No new
`omarchy.json`. The widget reads it with a `FileView` (`watchChanges:
true`, as the weather widget reads its `weather.json`), takes the
`LCARS_URL=` line only, and never reads the rest. The manifest's `url`
setting (a `string`, empty by default) wins when set: for a user who
points the widget elsewhere from the bar's settings form without
touching the file.

**The flow.** With no address, a click runs
`omarchy-launch-floating-terminal-with-presentation <plugin>/bin/lcars-webapp`
(the terminal omarchy itself uses for its installers; the plugin's own
path from `Qt.resolvedUrl`). O'Brien's installer asks: *local* or
*remote*.

- *Local*: download the release tarball for the machine's arch from
  github.com/saftacatalinmihai/lcars/releases, check it against
  `SHA256SUMS`, put the binary in `~/.local/bin/lcars`, `lcars init
  ~/.local/share/lcars`, write and start a systemd **user** unit
  (`lcars --data … --port 8080`, loopback), wait for `/health`.
- *Remote*: ask for the address, check `/health`, ask for the login.

Both end the same way: write `~/.config/lcars/env` (0600), run
`omarchy-webapp-install LCARS <url>/ui/ <plugin>/icon.png`
(a local icon file: the server's `/ui/icon-512.png` may sit behind the
login), and say what was done. The widget sees the file change and starts
polling; no shell restart.

What the plugin asks of the installer (to agree with O'Brien):
1. runnable from any directory, from the plugin's `bin/`, with no
   argument (it asks) and with `--local` / `--remote URL` (it does not);
2. it writes `~/.config/lcars/env` as above, and nothing in
   `~/.config/omarchy/` but through omarchy's own commands;
3. a second run is safe: an existing install is updated or left alone,
   never a second journal;
4. `--uninstall`: the unit stopped and removed, the launcher entry
   removed (`omarchy-webapp-remove LCARS`), the env file left (it holds
   no data), the journal **never** deleted, its path said.

The README's removal steps are `lcars-webapp --uninstall`, then
`omarchy plugin remove <id>` - the marketplace requires both written down.

## 3. The repo

**Source: `omarchy/` at this repo's root**, shipped in the public export
(nothing private in it; the audit holds that):

```
omarchy/
  manifest.json
  BarWidget.qml        the widget: mark, click, popup, poll
  Model.js             pure JS: parse the env file, the URL, the state
  icon.png             256x256, the launcher entry's icon
  preview.png          the marketplace's picture (section 5)
  README.md            install, setup, removal, dependencies
  LICENSE              MIT, as the repo's
  bin/lcars-webapp     O'Brien's installer
  bin/lcars-theme-set  the theme hook
```

The two scripts' **real files move into `omarchy/bin/`**, and
`scripts/omarchy/` keeps symlinks to them for the paths theming.md and
the tests name. A symlink outside the plugin's folder is harmless; one
inside would fail validation. So the published tree needs no copy step.

**Publishing: `scripts/omarchy-publish.sh`**, run on the captain's word
only. `git subtree split --prefix=omarchy -b omarchy-publish` from the
public repo's checkout (the export, not this private one: the split's
history must be the public history), then a push of that branch to
`main` of **saftacatalinmihai/omarchy-lcars**. `subtree split` is
deterministic, so each publish fast-forwards the last and `omarchy
plugin update` (a fast-forward pull) works for users. Before pushing it
runs the plugin's checks (section 4) and refuses a version not bumped
since the last publish. Creating the GitHub repo and filing the
marketplace issue (`[Plugin]: LCARS`) are the captain's.

**Versions: the plugin's own** semver, starting `0.1.0`, in
`manifest.json`. A plugin release changes when the plugin changes; LCARS
deploys several times a day, and stamping each onto the plugin would make
every `omarchy plugin update` a diff of nothing but a number. The
installer always fetches the latest LCARS release, so the plugin does not
pin one; the README names the oldest LCARS it works with (the one with
`lcars init` and `/health`, both long in).

## 4. Testing without omarchy

This box has no Quickshell and no omarchy. What can be tested here, in a
new `scripts/test_omarchy_plugin.py` (light, ~2 s):

- **omarchy's own validator, run here.** `omarchy-plugin-validate` is
  bash and jq only (schemaVersion 1 as a number, the required fields, the
  id's pattern `^[A-Za-z0-9][A-Za-z0-9._-]*$` and not `omarchy.*`, entry
  points relative and present, one per kind, `defaultSection` in the
  list, no symlinks). A copy, pinned to the commit it came from, in
  `scripts/testdata/omarchy/`, run on `omarchy/`. A copy rather than a
  fetch: the test must pass offline; a note says how to refresh it.
- **The marketplace's rules** the validator does not hold: `author`,
  `license`, `description` present, `version` semver and ≤ 64 chars,
  README and LICENSE at the root, the README naming install and removal,
  a `preview.*` under 40 MP.
- **`Model.js`** in node: the env file parsed (quotes, comments,
  `export`, a missing or empty `LCARS_URL`), the setting winning, a URL
  normalised (`/ui/` appended once, a trailing slash, a bad scheme
  refused, as `omarchy-webapp-install` refuses it).
- **The scripts**, as theming.md's hook test does: in a scratch HOME,
  against a scratch server and a stand-in GitHub release (a local
  tarball and SHA256SUMS), `systemctl --user` and `omarchy-webapp-install`
  stood in for. (O'Brien's to write with the installer.)
- **QML syntax, where it can be had.** `qmllint` is in Debian's
  `qt6-declarative-dev-tools` (not installed; a package for the captain
  to allow) or pip's PySide6 (`pyside6-qmllint`, in a venv). Without
  Quickshell's and omarchy's modules it can check syntax and plain
  QtQuick only; the `qs.*` imports are reported unresolved. The test
  runs it when present and says it skipped when not. This is why the QML
  is kept to one small file with the logic in `Model.js`.

**What only the captain's omarchy laptop can test** - a checklist for
the README's "Testing" section and the captain:

1. `omarchy plugin validate ~/lcars/omarchy` - exits 0.
2. `omarchy plugin add <the published repo> --enable` - the warning, the
   widget in the bar's right section.
3. No server set: the mark dimmed, tooltip "not set up"; a click opens
   the floating terminal with the installer.
4. Local setup: the binary, the unit (`systemctl --user status lcars`),
   the launcher entry under Super+Space, the mark lit within a minute.
5. Click: the console in its own window; a second click focuses it.
6. Right click: the popup; New entry opens the capture; Set up… and Add
   to the app launcher do what they say.
7. Stop the unit: the mark turns urgent within the poll; start it:
   back. Middle click checks at once.
8. Remote setup against the VPS (the tailnet address): the login asked
   once, the browser's own Basic auth remembered by the web app.
9. The bar's widget settings: the URL and interval fields from `schema`,
   a change taking effect without a restart.
10. A theme change (`omarchy theme set …`): the mark follows the bar's
    colours; with the hook installed, the console too.
11. `lcars-webapp --uninstall`, `omarchy plugin remove <id>`: nothing
    left but the journal and the env file, as the README says.
12. Watch `journalctl --user -u omarchy-shell` (or the shell's log) for
    QML warnings from the plugin through all of the above.

## 5. Identity and the listing

- **id: `dev.mihai-safta.lcars`** - reverse-domain of a domain the
  captain holds (the public demo's), and it outlives a move off GitHub.
  IDs are permanent on the marketplace and never reusable, so this was Q1
  (the other form, `io.github.<account>.lcars`, is the marketplace's own
  example).
- **name** `LCARS`, **author** the captain's name, **license** `MIT`,
  **description** "Your LCARS journal in the bar: open the console as an
  app, and set up a local server or connect to your own."
- **barWidget**: `displayName` "LCARS", `category` "Productivity",
  `allowMultiple` false, `defaultSection` "right", `defaults`
  `{ "url": "", "pollSec": 60 }`, `schema` the two fields.
- **Listing**: category `Productivity` (of Appearance, Desktop, Developer
  Tools, Hardware, Kids, Productivity, System, Widgets, Other); tags
  `launcher`, `bar`, `quickshell` (one to three, from a fixed list).
- **icon.png**: from `lcars-ui/icon-512.png`, scaled to 256x256 (where
  `omarchy-webapp-install` puts icons). The bar mark is drawn in QML in the
  bar's own colours, not this picture.
- **preview.png**: the marketplace takes any screenshot (≤ 50 MB, ≤ 40 MP,
  it makes its own sizes). One 1600x1000 frame: an omarchy desktop with
  the bar's LCARS mark and the console open as an app beside a terminal.
  Made on the captain's laptop (it needs the real bar), or composed here
  from a `shots.py` frame of the console under the omarchy theme with a
  drawn bar - Q6.

## 6. The captain's answers (26 Oct 2026)

All seven as recommended: the id `dev.mihai-safta.lcars`; the repo
`saftacatalinmihai/omarchy-lcars`, made by the captain and pushed only on
his word; the plugin's own semver from 0.1.0; the address in
`~/.config/lcars/env` with an optional `url` setting that wins; up or
down only in slice 1; the preview taken on his laptop; the theme hook
offered by Set up….

## 7. The order of the work

1. This design (zimmerman-c39, 0.337.4).
2. O'Brien: `lcars-webapp` in `omarchy/bin/`, the four points of section
   2, its test.
3. The plugin: `omarchy/` (manifest, BarWidget.qml, Model.js, README,
   LICENSE, icon), `scripts/test_omarchy_plugin.py`,
   `scripts/omarchy-publish.sh`, the export audit clean (zimmerman-c39);
   the scripts moved into `omarchy/bin/` with links left behind
   (O'Brien).
4. The captain's checklist on the laptop (section 4); fixes. Done: the
   captain tested it on his laptop and it works (2026-10-28).
5. The repo, the first publish, the listing - the captain's word at each.
