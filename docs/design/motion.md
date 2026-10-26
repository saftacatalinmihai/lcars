# Motion: the console's page transitions

The captain's order (2026-10-14): every change of view moves, the way a
film's computer does - quick sweeps, panels that open out of what was
touched - and none of it ever makes him wait.

## Rules

1. **Native only.** CSS transitions and animations, `Element.animate()`
   for a one-shot replay, and the View Transitions API
   (`document.startViewTransition`) for what leaves. No library, no
   animation loop of our own.
2. **Never wait.** 150-220 ms. The change is made in the tap; an animation
   only moves what is already drawn, and nothing is held back until one
   ends. (The swipe page turn used to land its entry after a 140 ms slide
   out; it lands at once now.)
   A theme's fade (theming.md 7) is the one longer one, 350 ms at the
   captain's word: colours over a page already in place, nothing waits.
3. **What comes, moves where it is; what goes, by a view transition.** A
   pane or a page that has just come on screen is animated in place, in
   the same task as the tap: transform, opacity, a clip. Something that
   leaves is gone from the page the moment the change is made, and only a
   view transition can still show it go: `morph()` captures it alone,
   makes the change, and its picture leaves over the page already changed
   underneath.
4. **A view transition's change runs a frame later** (after the capture),
   so `morph()` wraps only a tap's or a key's own handler, never
   `select()`, `closeEditor()` or `closeOv()`: their callers, popstate
   first, read what they did at once. A key, a pointer, Back or a dialog
   opening that comes first makes the change then (`vtFlush`). The doors
   out of an edited entry leave *in* the tap (editor.md, test/editor.py),
   so closing the editor is never a morph.
5. **A second tap works.** During a view transition the browser hit-tests
   its snapshot layer, not the page: a tap would land on `<html>`. A
   pointerdown ends the transition; a touch's tap then lands where it was
   aimed, and a mouse click that still landed on `<html>` is handed to
   whatever is under it. A new transition ends the one running.
6. **Same code path, no motion, where it cannot run:** no
   `startViewTransition` or `animate` (old browsers, the QuickJS suite),
   `prefers-reduced-motion: reduce` (`beamOk()`, `motionOk()`, and the
   media rules), a hidden page. The function just makes the change.
7. **The 60 fps budget holds** (test/perf.py, `morph` and `morph-desktop`).
   A transition that costs frames is cut, not tuned - see "Measured".

## The views

| Change | Motion | ms |
| --- | --- | --- |
| list row → reader (tap, Enter), phone | the pane opens out of the row's band to the full screen (`clip-path`, `openOut`); its slide from the right is held off meanwhile | 200 |
| list row → reader, desk | the page slides in from the list's side and fades up | 200 |
| reader → list (‹, ×, Escape) | in the tap: on a phone the pane slides off by its own CSS transition; the row it came from lights up amber and fades (`closeRow`); a desk's empty pane fades in | 220 |
| next / previous entry (j/k, the swipe page turn) | the page slides in 14px from the side it came from and fades up (`pageIn`); the swipe lands at once and slides in | 160-200 |
| any dialog opens (settings, the palette, the calendar, tasks, help, ...) | on a desk the panel wipes in left to right as it scales up - the LCARS sweep; on a phone it rises as a sheet, as before | 180 |
| a dialog closes (Close, Escape, the scrim) | view transition `vtdlg`: the panel sinks and fades over the page already back | 150 |
| chats list → thread (a row) | the thread opens out of its row's band (phone), slides in from the list (desk) | 200 |
| thread → chats list (‹) | view transition `vtpane`: the thread slides off to the right over the list | 200 |
| the chats list opened | its first rows settle in: up 6px and fade, 15 ms apart (`settleRows`, once per opening) | 160 |

## What stays fixed

The page is never captured as a whole (`:root{view-transition-name:none}`):
during a view transition only the leaving part is a picture, and the
header, the rail and the list are the live page under it - they neither
move nor crossfade.

## What is left still, on purpose

- **The main list's rows.** It is redrawn on every keystroke of a search
  and every filter tap; rows sliding about while one types is noise, and
  4000 rows are the perf budget's worst case.
- **The palette's rows.** Same reason: they are the typing's answer.
- **Read ↔ Edit.** The writer's hands are on the keyboard; the existing
  fade of the body is all.
- **A new entry (+, n).** Its title takes the focus, and iOS raises the
  keyboard only for a focus in the tap itself, so it cannot wait for a
  view transition; the phone's slide in and the desk's fade, as before.
- **Browser Back / Forward and deep links.** They go through `applyPage`,
  which must stay synchronous (rule 4). On a phone the editor still slides
  out by its CSS transition; a dialog closed by Back simply goes.
- **The deck's talk sheet** (`.solo`): the sheet is its own entrance.
- **Idle loops** were already behind Config's idle-animation switch; none
  is added.

## Measured (test/perf.py on the VPS, p99 main-thread per frame)

The first build morphed the row into the reader with a view transition:
the row's box grew into the pane's. With the whole page captured as
`root` it cost a desk 18-21 ms (deb: 12.6); capturing only the moving
part, 15-19; and of that the captures and the growing box (whose width
and height animate on the main thread every frame) each cost about 2 ms
over deb. It was cut for `openOut`'s clip and slide: 12.3-15.0, deb's
numbers within the noise.
