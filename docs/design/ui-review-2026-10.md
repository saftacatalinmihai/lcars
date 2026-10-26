# The console's UI review, October 2026

A design review of the web console (`lcars-ui/index.html`, the deck out
of scope), iPhone first, then a desk. It is a report only: nothing in
`lcars-ui/` changed. The full report, with screenshots, measurements
and four HTML mocks beside today's screens, is on the console's Reports
page as "The console, reviewed: a UI design review (Oct 2026)"
(`reports/2026/10/the-console-reviewed-a-ui-design-review-oct-2026-073defdb.html`
in the media store). This note keeps the ranked list and the order of
work, so the slices can be built from it.

## The lens

The main lens is Anthropic's `frontend-design` skill (anthropics/skills,
Apache-2.0). It is about 9 KB of text with no scripts, so it could be
read whole and trusted, and it names the generic looks directly. It also
defers to a pinned brief, and LCARS is one: uppercase condensed labels
are Okuda's grammar here, not a tell. It is written for new pages, so
the review of a working tool also borrowed, as text only, Impeccable's
Operate mode, audit rubric and craft floor (pbakaus/impeccable; its
setup downloads a binary and was not run), and Vercel's Web Interface
Guidelines. The guides held: Refactoring UI, Apple's HIG (44pt targets,
17pt body), Material 3, GOV.UK, WCAG 2.2 AA, Nielsen's heuristics, and
the LCARS tradition (elbows, capped bars, warm structure and cool data,
condensed type).

The skill was installed in an engineer's worktree only
(`.claude/skills/frontend-design/`) and is not committed. Its licence
allows committing it, but it is one `npx skills add` away and updated
upstream. What the repo should hold instead is slice 0's rules file.

## Method

A scratch server on `test/synth.py`'s 4,010-row journal, with
`rooms_ui.py`'s engineer stand-in. Playwright and Chromium at 393x852
(3x, touch) and 1440x900, 16 screens each. Every visible piece of text
was measured (computed face, size, WCAG contrast against the composed
background), along with every visible control's box. WebKit does not
start on the VPS (a missing `libxslt`), so iOS rendering itself was
not checked.

## Findings, ranked by daily cost

1. **The list shows source, not entries.** `.item .sn` prints raw
   markdown in 11-12px mono, and `max-height:3.7em` at line height 1.2
   cuts the third line in half. Above it sit the id, the kind's slug and
   a byte count. (Nielsen #2 and #8; the lens on monospace labels and
   user vocabulary.)
2. **No type scale.** 25 literal font sizes are written in the CSS and
   18 render on the phone. 76% of phone text is 12px or smaller, 11px
   is the most common size, and mono is the main face on 13 of 16
   screens, the editor included. (The lens: "set a clear type scale";
   HIG 17pt body.)
3. **Tap targets.** 10-32 controls a phone screen are under 44pt. The
   reader's TODO toggle (37x20), fold arrows (20x20) and date buttons
   (16px tall) are under WCAG 2.5.8's 24px, and the header pills are
   40px.
4. **The phone month calendar** crams dots, three clipped times and
   "+5 more" into 50px cells. The next-month arrow is 2.9:1.
5. **Headers.** On the phone, three unlabelled glyphs (▤ ◉ ◆). On the
   desk, 11 pills of equal weight. The ⋯ sheet's Unicode glyphs come in
   mixed weights. (Nielsen #6; the craft floor's ban on glyph icons.)
6. **New entry.** The kind is offered twice and "Write something first"
   appears twice. The body is in mono, and Dictate is no bigger than
   Video.
7. **Keyboard help on a phone.** Help opens with shortcuts, and the
   palette's and kind picker's footers give key hints. Tasks shows four
   rows of filters before the first task.
8. **Floating buttons over content.** The phone's + sits over rows and
   the rail, and the desk's Chats over the reader's toolbar. (WCAG
   2.4.11.)
9. **The kinds' slugs are shown as names** (`personal_log`,
   `WAKE_LOG`).
10. **Statistics.** It uses the hero-metric template and side-bordered
    finding cards, and shows a finding that found nothing ("1.0×, 2.1
    vs 2.1").
11. **Small things.** The version string under the clock and on every
    sheet; middle-dot strings; a desk Chats page that is a 210px column
    in 1440px; "20750d" for a missing time; 15 radii and 180 literal
    hex colours beside the tokens.

## Keep

Colour and contrast: on the phone, 15 of 16 screens have no text under
4.5:1, and `--dim` on black is 7.2:1. Also keep the day bars, the desk
sidebar's elbow and numbered section bars, the coloured bar segments
(Media & files, Camera, Attach, Record), the reader and its Standby pane,
the empty search state, reduced motion, focus-visible, aria-live, the
safe areas, tabular numbers, 16px inputs, the immediate-feedback rule,
and the chat lists' structure.

## Order of work

| # | Slice | Findings | Cost |
|---|-------|----------|------|
| 0 | `docs/design/ui-rules.md`: type scale (12, 13, 16, 17, 22, 28; 34 for the reader's title), face roles (Antonio for chrome, sans for reading, mono for code), 44px targets, one SVG icon set | 2, 3, 5 | 15 min |
| 1 | List rows: plain preview clamped to two lines, kind names, time column on the phone | 1, 9 | 30-45 min |
| 2 | Hit areas via `::before`; header pills 44px | 3 | 20 min |
| 3 | Type tokens, two passes (reader, editor and list; then the views) | 2, 6 | 2 x 45 min |
| 4 | Phone month: dot grid and the day's agenda | 4 | 45-60 min |
| 5 | SVG icons, phone labels, desk ranked header, Chats moved off the reader | 5, 8 | 45 min |
| 6 | New entry: one kind control, Dictate primary | 6 | 30 min |
| 7 | The phone's elbow frame, with New in the lower elbow (replaces the FAB) | 5, 8 | 45 min |
| 8 | Help and hints by device; Tasks' filters folded | 7 | 20-30 min |
| 9 | Statistics: no empty findings, readouts not cards | 10 | 20 min |

Slices 1-3 remove most of the daily cost. The slices that touch the list
or the calendar re-run `perf.py`.
