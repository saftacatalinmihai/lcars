# Theming the console

The captain's order (26 Oct 2026, through Number One): the console
themeable, btop's themes replicated, and a theme settable from outside by
a tool such as omarchy. Number One's notes:
`research/number-one/theming-btop-omarchy-2026-10-26.md`. Slice 1 (this
note, mendez-c35): the mapping, the engine, the built-ins, the doors, the
contrast sweep, the transition. Slice 2 (mendez-c35): the choice in a
journal entry (every device), GET/PUT /theme taking either file format,
`lcars-cli theme`, an omarchy hook, the kinds' colours and the reports'
page under a theme. The 3D deck is out of scope.

The deck is not wanted themed (the captain, 2026-10-28): it keeps its own
palette under every theme.

## 1. What a theme is

A theme is a palette - a handful of colours given by a file - mapped by
one table (section 3) onto the tokens in `:root` (`lcars-ui/index.html`;
ui-rules.md, "No colour literals outside :root", rules.py [colours]).
Nothing outside `:root` names a colour, so the whole console follows its
tokens, and a theme is nothing but new values for them: no second
stylesheet, no per-view code.

Two file formats, read in the page (`themeParse`, a few lines each):

- **btop** (`*.theme`): `theme[key]="value"` lines, `#` comments; a value
  is `#RRGGBB`, `#BW` (two hex digits of grey, `#ff` white) or `R G B` in
  decimal; an empty value means "the terminal's default". Anything after
  the closing quote is ignored (two shipped files carry a stray `#...`
  there). Every shipped file has the same 37 keys (the eight gradients
  counted in thirds), a few more in some; the ones we read are in the
  table.
- **omarchy 3** (`colors.toml`): `key = "#rrggbb"` lines (single quotes
  too), `#` comments, 22 keys: `mode` (dark|light), `accent`,
  `selection`, `muted`, four backgrounds, four foregrounds, the eight
  hues and six bright ones. omarchy makes its own `btop.theme` from these
  (`default/themed/btop.theme.tpl`); our table agrees with that template
  for bg, fg, accent, sel, muted, line and the heat ramp, so those read
  the same whether we are handed a theme's `colors.toml` or the
  `btop.theme` omarchy wrote from it (a test holds this). They differ in
  the title (the template's is the foreground; ours is omarchy's yellow,
  for the LCARS labels' warmth) and in the hues, which a `colors.toml`
  names and a btop file only lets us find.

A file with a `theme[` line is btop; otherwise one with `key = "..."`
lines is omarchy; otherwise it is refused ("not a theme file").

## 2. The internal palette: the roles

Both formats land on one palette of roles (`themePalette`); the tokens
are computed from the roles alone (`themeTokens`), so a third format
later is one more column in the table and nothing else.

| role    | what it is in the console                        |
|---------|--------------------------------------------------|
| bg      | the black field (`--bg`), and the ink on lit fills |
| fg      | body text (`--txt`)                              |
| accent  | the LCARS bars and pills, the lead colour (`--orange`) |
| title   | headings and labels (`--amber`)                  |
| sel     | the selected row's tint (`--warm`)               |
| muted   | a quiet stroke (`--mute`)                        |
| line    | box lines, dividers (`--line`)                   |
| red, orange, yellow, green, cyan, blue, magenta | the hue roles |
| heat    | three stops, the heat map's ramp                 |
| light   | true for a light theme                           |

## 3. The table: a file's keys onto the roles

| role    | btop key                       | omarchy key                 |
|---------|--------------------------------|-----------------------------|
| bg      | `main_bg` (empty: see below)   | `background`                |
| fg      | `main_fg`                      | `foreground`                |
| accent  | `hi_fg`                        | `accent`                    |
| title   | `title`                        | `yellow`                    |
| sel     | `selected_bg`                  | `selection`                 |
| muted   | `inactive_fg`                  | `muted`                     |
| line    | `div_line`                     | `muted`                     |
| red     | by hue, from the file's colours | `red`                      |
| orange  | by hue                         | `orange`                    |
| yellow  | by hue                         | `yellow`                    |
| green   | by hue                         | `green`                     |
| cyan    | by hue                         | `cyan`                      |
| blue    | by hue                         | `blue`                      |
| magenta | by hue                         | `magenta`                   |
| heat    | `cpu_start`, `cpu_mid`, `cpu_end` | `cyan`, `blue`, `magenta` (omarchy's own cpu gradient) |
| light   | `main_bg`'s luminance over 0.4 | `mode = "light"`            |

- **An empty `main_bg`** (adapta, flat-remix, matcha-dark-sea: "the
  terminal's default") is black, or white when `main_fg` is dark
  (luminance under 0.4). A missing key falls back down the table: `title`
  to `fg`, `hi_fg` to `title`, `div_line` to `inactive_fg`, an empty
  gradient third to the one before it.
- **btop has no hue keys**, so the hue roles are found: every colour the
  file gives (all its keys, in file order) is a candidate, and a role
  takes the candidate whose hue is nearest its own (red 0°, orange 30°,
  yellow 50°, green 120°, cyan 185°, blue 220°, magenta 300°), among those
  with saturation of at least 0.25, reading at least 2:1 on bg (so a
  background is never taken for a hue) and within 30° of it; a tie goes to the
  first in the file. A role nothing is near enough to (a grey theme, a
  two-colour one) keeps the LCARS default hue, its lightness moved until it
  reads at 4.5:1 on the theme's bg - so red still means red, readable,
  under greyscale and whiteout.
- An omarchy key that is missing falls back the same way (its hue from
  LCARS's, made readable).

## 4. The tokens: given, and derived

`mix(a, b, t)` is a straight blend in sRGB, `t` of the way from `a` to
`b`. The fractions are the ones that give back today's LCARS greys from
its black and its `--txt` (`#e8e6e3`): `--panel` `#0d0d10` is 0.055 of
the way, `--dim` `#9895a3` 0.655, and so on. The `lcars` theme itself is
not computed: it is `:root` as written.

| token(s) | value |
|----------|-------|
| `--bg` | bg |
| `--txt` | fg |
| `--orange` | accent |
| `--amber` | title |
| `--gold` | yellow |
| `--salmon` | orange |
| `--red`, `--green`, `--purple` | red, green, magenta |
| `--blue`, `--sky` | cyan, blue |
| `--pink` | mix(magenta, fg, .25) |
| `--me` | blue; `--beam` mix(blue, fg, .6) |
| `--well`, `--panel`, `--panel2`, `--panel3` | mix(bg, fg, .043 / .055 / .09 / .12) |
| `--line` | line; `--line2`, `--line3` mix(line, fg, .055 / .135) |
| `--mute` | muted |
| `--dim`, `--soft`, `--txt2` | mix(bg, fg, .655 / .776 / .89), each raised toward fg until 4.5:1 on `--panel` |
| `--ink` | bg (the text on a lit fill is the field's colour: black on LCARS, white on a light theme) |
| `--ink2`, `--ink3` | mix(bg, accent, .25 / .35) |
| `--white` | the extreme away from bg: #fff dark, #000 light (focus rings, a chart's hover stroke) |
| `--paper` | not set: #fff under every theme, the page a report is framed on (an HTML page is drawn on white, as a browser draws it; slice 1 had `--white` there, black under a light theme) |
| `--warm`, `--warm-well`, `--warm-drop` | mix(bg, sel, .5 / .25), mix(bg, accent, .2) |
| `--pick`, `--pick-hi` | mix(bg, blue, .1 / .16) |
| `--heat1..3` | mix(bg, heat[0..2], .3 / .55 / .8) |
| `--red-deep`, `--red-dim` | mix(bg, red, .06 / .4) |
| `--red-light`, `--red-lighter` | mix(red, fg, .2 / .45), raised to 4.5:1 on `--panel` |
| `--track` | mix(bg, magenta, .3) |
| `--raised`, `--raised-hi` | the two gradients from mix(bg, fg, .125 → .078) and (.19 → .12) |
| the alpha ladder | each `--<hue>-NN` is its hue's token at alpha .NN (`--orange-*` accent, `--amber-*` title, `--blue-*` cyan, `--purple-08` magenta, `--green-*`, `--red-*` red); `--panel-90` the panel at .9; `--white-NN` the `--white` above at .NN; `--me-halo` blue at .6, `--beam-40`/`-55` the beam; `--black-NN` and `--red-scrim` stay (a shade is a shade on any field) |
| `color-scheme` | `light` or `dark` (the native date picker, the scrollbars, form controls) |
| `<meta name="theme-color">` | bg (the phone's status bar), set by `themeApply` and on a reload by `themeBoot` |

The hues are a theme's own and are not corrected: a theme that sets a
colour that reads badly on its own field reads badly here too, and the
contrast sweep (section 7) lists it. Only what we derive (`--dim`,
`--soft`, `--txt2`, the red texts, a hue a btop file did not have) is held
to 4.5:1 by construction.

### What stays the console's own under every theme

- **The LCARS shapes**: the elbows, the bars, the pills, the radii, the
  type (Antonio for the chrome), the grain, the bevel's light (`--bevel`,
  `--sheen`: white and black at low alpha, a light source, not a colour).
- **The alert colours**: `--alert-red` (#e8573f), `--alert-yellow`, their
  glows, and `body[data-alert]`'s redefinition of `--orange`, `--amber`,
  `--gold` and `--salmon`. Red alert is a ship's signal, the one thing that
  must look the same whatever palette is up; it is set on `body`, so it
  wins over a theme's values on `:root` while it lasts, and the theme is
  back when the alert clears.
- (Not the kinds' colours: `kindColor` gives a token, `var(--orange)` and
  seven more, so a kind's label, dot and row edge follow the theme. What
  cannot read a `var()` - the graph's and the star chart's canvases, an
  SVG's fill or stroke attribute in the statistics and the charts - takes
  `kindHex`, the token's value as computed under the theme worn. Slice 1
  had them as LCARS literals, faint on a light theme.)
- **The deck** (deck.html): its own palette, not to be themed (2026-10-28).

## 5. The engine

- **Built-ins**: btop's 41 shipped themes, verbatim (their headers
  kept), in `lcars-ui/themes/*.theme`, from
  github.com/aristocratos/btop/themes at af521ae (25 Oct 2026), under
  Apache-2.0: `themes/LICENSE` is btop's, `themes/NOTICE` the attribution.
  They ship with the page (the pack takes every tracked file under
  `lcars-ui/`; the demo's `static.py` copies `themes/`). `THEMES` in the
  page lists their names; the behaviour suite holds it to the directory.
  `lcars` is the default and the first row: the `:root` palette as
  written, no file.
- **Applying** (`themeApply`): the computed tokens set on
  `document.documentElement.style` (an inline style on `<html>`, which
  beats `:root`'s rule and is beaten by `body[data-alert]`), `lcars`
  removing them all. One place sets them, so where a palette comes from
  (a built-in's file, a file handed in, the server in slice 2) does not
  matter: `themeFromText(text, name)` is the whole door, a file's text in
  either format to an applied theme.
- **The choice is the journal's** (slice 2, `lcars_theme.h`): the
  `settings` entry titled `theme` (the lowest live id, as with `kinds`
  and `views`), `{"v":1,"name","fmt","text"}`: a built-in by name
  (`fmt` builtin, `text` empty), any other theme carried whole, the file's
  text as it was handed in (`fmt` btop or omarchy). `GET /theme` reads
  it; `PUT /theme` writes it, from JSON `{name}` or `{name, text}` or the
  file itself as a text/plain body with `?name=` (default `custom`). The
  server checks only the size (64 KB, 413 past it), the name (letters,
  digits, `-_.` and spaces, 1-64, no leading dot; a built-in's file must
  be shipped, on disk or in the embedded pack) and the shape (a `theme[`
  line, or a `key = "#hex"` one, themeParse's own first tests); the
  parsing and the table stay in the page, in one place. The owner's login
  writes it; the limited logins read it and are refused a PUT (no route
  of theirs names it), the steward any `settings` entry. An entry that is
  not JSON (a hand edit) is read as lcars with `error`, and a PUT is
  refused (409) rather than overwrite it, as with `kinds`.
- **Followed as any row**: the page adopts the entry as the sync brings it
  (`themeAdopt`, from `refresh()`: O(1) unless the row count or the row
  moved), so a change from another device, `lcars-cli` or omarchy reaches
  an open console through GET /events within a second or two, no polling.
  The first one a page sees is put on with no fade (a boot: the `<head>`
  already painted the device's copy); a later one fades and is named in a
  toast. A choice made here is shown at once and written after
  (`themePush`, one write at a time); while one is out the entry is not
  adopted (it would put back the one before), and a write that fails says
  "theme kept on this device only" and leaves it worn.
- **Kept on the device**: `localStorage["lcars.theme"]`, the entry's
  cache, `{name, v, text, fmt, tokens}`: the computed tokens, so a small
  script in the page's `<head>` sets them before the first paint, with no
  fetch and offline (no flash of the LCARS palette on a reload). `v` is
  the table's version (`THEME_V`): a copy kept under another is computed
  again at boot from its source (the built-in's file, or `text`) and put
  on with no fade, so a change to the table or a new `:root` token never
  leaves a device on stale values. Bump `THEME_V` with any change to
  `themePalette` or `themeTokens`.
- **Loading a built-in**: `themes/<name>.theme`, fetched when it is
  wanted; the picker fetches all 41 when it opens (small files, cached by
  the browser and the service worker's runtime cache) to tag each row.

## 6. The doors

- **The picker** (palette's "app · theme…", or "computer, choose a
  theme"): the same picker as the kind's or the palette's, a row per
  theme, `lcars` first, the current one ticked and under the cursor when
  it opens, each tagged `dark` or `light`, and `low contrast` when its
  text on its own field fails 4.5:1 (marked, never dropped). As the
  cursor moves the theme is applied live, so the captain sees it before
  pressing Enter; Enter (or a tap) keeps it; Escape, Close or the scrim
  put the one before back.
  A theme handed in from outside (the entry's `text`) has a row of its
  own after lcars, its name and "from omarchy" or "from a file".
- **Tap doors** (a phone has no palette): a **Theme** tile under More (⋯;
  a tile with no header button behind it, so not one Header buttons
  offers), and a **Theme…** row in Config beside the volume, naming the
  theme worn; both open the picker, and the choice is saved as it is made.
- **The palette**: "app · theme…" (the picker) and "app · theme: lcars"
  (back to the default).
- **lcars-cli**: `theme` (which is worn), `theme set NAME` (a built-in),
  `theme load FILE [--name N]` (either format; `-` is stdin; the name is
  the file's, or for a `colors.toml` or `btop.theme` its folder's),
  `theme reset`; `--json` for the server's answer.
- **omarchy** (`scripts/omarchy/lcars-theme-set`, plain sh): a hook for
  `~/.config/omarchy/hooks/theme-set.d/`, run with the theme's name; it
  loads the current theme's `colors.toml` (else its `btop.theme`) through
  `lcars-cli theme load`. It needs lcars-cli (PATH or `$LCARS_CLI`) and
  the login as lcars-cli takes it (the environment, or
  `~/.config/lcars/env`); the request runs in the background with a 5 s
  limit, any failure is one line on stderr, and it always exits 0, so
  omarchy is never held up.
- **Spoken**: "theme {*}" ("computer, theme nord", "computer, theme
  gruvbox dark": the name matched loosely, hyphens and underscores as
  spaces, a word left out allowed when only one theme fits; one that
  fits several, "theme everforest", opens the picker filtered to them),
  "default theme", and "choose a theme".
- A toast names the theme applied ("theme · nord").

## 7. The transition (the captain's addendum)

A change of theme fades, 350 ms, one easing (`ease`). The tokens on
`:root` cannot be transitioned (a custom property is not animatable
unless registered, and registering forty is forty `@property` rules for
one fade), so what reads them is: `background-color`, `color`,
`border-color`, `outline-color`, `fill`, `stroke` and `box-shadow`, on
every element and its `::before`/`::after`, under `html.theming` only. The
class is set for the span of a change and taken off when it ends, so
nothing else in the console is slowed by it, and no property that lays
out (a width, a margin, a transform) is ever in the list.

- `themeApply` sets `html.theming` (and `--theme-ms`), reads one computed
  style so the old colours are the transitions' start, then sets the
  tokens; a timer takes the class off at `--theme-ms` + 50 ms.
  `transitionend` is not what ends it: it fires per element and property,
  thousands of times, and not at all for a colour that did not change.
- The picker's live preview uses the same class at 180 ms: a cursor held
  on ArrowDown runs through the themes without trailing behind.
- `prefers-reduced-motion: reduce`: no class, the colours change at once
  (and the CSS rule is under `no-preference` too, belt and braces).
- 350 ms is longer than motion.md's 150-220: that rule is for a change
  of view, which must never make him wait; this is a fade of colours over
  a page already in place, the captain's own number.

## 8. Tests

- The behaviour suite (tests.js, "themes"): every shipped file parsed
  with the page's own parser (gen.py hands the suite their text), each
  giving every role a colour; omarchy's nord `colors.toml` parsed and
  mapped to what its own `btop.theme` template would give; the table's
  rows (an empty `main_bg`, `#BW` and `R G B` values, a light theme's
  `--ink`, `--white` and `color-scheme`); `THEMES` equal to the
  directory; the picker (rows, tags, the cursor applying, Escape putting
  the old back, Enter keeping it, localStorage); the palette rows; the
  spoken orders (`vMatch`); the toast; the transition's class set on a
  change and gone after its timer, never under reduced motion.
- The contrast sweep, in the same section: the pairs audit.py checks for
  the default (`--dim`, the six hues, `--soft`, `--txt2`, the red texts on
  `--panel`), plus `--txt` on `--bg` and `--ink` on `--orange`, computed
  for every built-in; the failures must be exactly the appendix below,
  so a change to the table that makes a theme better or worse moves the
  appendix with it (the suite prints the new block when they differ).
- Slice 2 in the same suite: a choice written (PUT /theme), a failed
  write's toast, the entry's arrival applying its theme (faded, named),
  an edit carrying an omarchy file, its picker row, picked and written
  back with its text, the stored version recomputed at boot with no fade,
  and an ambiguous name opening the picker.
- `test/theme.py` (~40s, a scratch server): the route (the formats, the
  refusals, the entry by hand, the logins), `lcars-cli theme`, and the
  omarchy hook in a scratch HOME (colors.toml preferred, btop.theme alone,
  the env file, each failure one line and exit 0 at once).
- audit.py checks the default's, as before.

## Appendix: the contrast sweep's failures

AA (4.5:1) failures of the built-ins under the table above, one line per
theme: the pair and its ratio. They are the themes' own colours - btop
draws these on a terminal where nothing else is there - and are listed,
not corrected (section 4). A theme whose `--txt` on `--bg` fails is
marked `low contrast` in the picker.

<!-- sweep:begin -->
- adapta: --purple on --panel 2.70
- adwaita: --purple on --panel 4.24, --blue on --panel 3.97
- adwaita-dark: --red on --panel 3.06
- dracula: --orange on --panel 2.59, --purple on --panel 2.02, --red on --panel 3.88, --ink on --orange 3.03
- elementarish: --orange on --panel 2.16, --blue on --panel 3.29, --red on --panel 2.16, --ink on --orange 2.51
- everforest-dark-hard: --orange on --panel 4.47, --red on --panel 3.74
- everforest-dark-medium: --orange on --panel 4.03, --red on --panel 3.37
- everforest-light-medium: --orange on --panel 2.64, --purple on --panel 2.64, --blue on --panel 2.92, --green on --panel 4.21, --red on --panel 2.77, --ink on --orange 2.83
- flat-remix: --purple on --panel 3.22
- flat-remix-light: --txt on --bg 3.57, --dim on --panel 3.38, --soft on --panel 3.38, --txt2 on --panel 3.38, --red-light on --panel 3.38, --red-lighter on --panel 3.38, --orange on --panel 2.38, --purple on --panel 4.49, --blue on --panel 4.40, --red on --panel 2.73, --ink on --orange 2.52
- flexoki-dark: --purple on --panel 2.62, --red on --panel 4.05
- flexoki-light: --orange on --panel 4.26, --blue on --panel 4.03, --green on --panel 4.31
- gotham: --amber on --panel 3.70, --red on --panel 4.24
- gruvbox_dark: --blue on --panel 3.55, --red on --panel 2.75
- gruvbox_dark_v2: --orange on --panel 2.34, --blue on --panel 3.03, --red on --panel 2.34, --ink on --orange 2.69
- gruvbox_light: --orange on --panel 4.40, --blue on --panel 3.40, --green on --panel 4.02, --red on --panel 4.40
- gruvbox_material_dark: --orange on --panel 4.20, --red on --panel 4.20
- horizon: --red on --panel 4.14
- HotPurpleTrafficLight: --orange on --panel 4.00, --purple on --panel 4.00, --ink on --orange 4.27
- kanagawa-lotus: --orange on --panel 3.77, --purple on --panel 4.46, --blue on --panel 2.90, --green on --panel 4.33, --red on --panel 3.32, --ink on --orange 4.06
- kanagawa-wave: --orange on --panel 3.16, --red on --panel 3.59, --ink on --orange 3.54
- kyli0x: --red on --panel 3.96
- nord: --orange on --panel 2.71, --red on --panel 4.20, --ink on --orange 3.10
- onedark: --red on --panel 3.96
- paper: --orange on --panel 3.74, --purple on --panel 4.41, --blue on --panel 3.82, --red on --panel 3.74, --ink on --orange 4.21
- phoenix-night: --purple on --panel 3.71, --red on --panel 3.80
- solarized_dark: --orange on --panel 4.09, --blue on --panel 3.57, --red on --panel 2.89
- solarized_light: --orange on --panel 2.79, --purple on --panel 2.39, --green on --panel 4.24, --red on --panel 3.95, --ink on --orange 2.98
- tomorrow-night: --red on --panel 3.99
- whiteout: --purple on --panel 1.86
<!-- sweep:end -->
