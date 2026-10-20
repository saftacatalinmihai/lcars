# The demo reel

(The public demo, the console and the deck on this journal as static files,
is `static.py` and `static.js` here: docs/design/demo-static.md.)

A scripted tour of `index.html`, recorded in headless Chromium, with sound —
for a front page or a YouTube upload.

```sh
sudo apt-get install ffmpeg sox libsox-fmt-all python3-numpy
./demo/build.sh              # record, then encode -> demo/out/
./demo/build.sh --encode     # re-encode what is already recorded
```

About half an hour end to end: the reel plays in real time while it is filmed,
and the VP9 encode is slow. Set `LCARS_DEMO_NOW=2026-09-19` to pin the
journal's clock, so a rebuild reproduces the same cut.

## What comes out

| file | what it is |
| --- | --- |
| `lcars-demo.mp4` | H.264 + AAC, 1920x1080 at 30fps, mastered to -14 LUFS. Upload this. |
| `lcars-demo.webm` | VP9 + Opus, a fraction of the size, for embedding yourself |
| `hero.mp4`, `hero-loop.webm` | a silent ~12s loop for muted autoplay on a front page |
| `poster.png`, `hero-poster.png` | stills for `<video poster>` |
| `chapters.txt` | timestamps to paste into a YouTube description |
| `proof/*.png` | one screenshot per scene, straight off the live page |

## The parts

**`fixture.py`** — the journal being filmed. Four months of entries against a
stubbed API; nothing touches `lcars.db` or the live server, and the stub
acknowledges writes without applying them, so a take cannot change what the
next take shows. Rewrite the prose freely; the `IDS` block at the top is the
only thing `demo.py` depends on.

**`demo.py`** — the camera. Drives the app, and lays a title card, captions and
a visible pointer over it.

```sh
python3 demo/demo.py --list             # the scene names
python3 demo/demo.py --only graph       # re-record one scene, to time it
python3 demo/demo.py --fast             # 2.5x, same cuts, for iterating
python3 demo/demo.py --proof            # also save each scene's money shot
python3 demo/demo.py --phone            # the phone pass and its plate
python3 demo/demo.py --hero             # the front-page loop
```

**`sound.py`** — the soundtrack. See below.

**`build.sh`** — the encoder and the cutting room.

**`assets/`** — the display face, kept locally. `index.html` pulls Antonio from
Google Fonts; filming over that is a network dependency in the middle of a
two-minute take, and a blip means the whole reel silently cuts in Arial Narrow.
The demo serves its own copy and blocks the remote one. **The app itself is
untouched** — if you want `index.html` to be self-contained offline too, that
is a separate change, and it would mean embedding the woff2 as a data URI to
keep the one-file promise.

## The sound is rebuilt, not recorded

Headless Chromium has no audio device, so none of the app's voice can be
captured. It does not need to be. Every sound in `SFX` (`index.html`) is a
little table of oscillator frequencies played by `sndPlay()`, and `sndAc` /
`sndMaster` are plain top-level bindings — so `sound.py` points them at an
`OfflineAudioContext` and asks the app's *own* scheduler to render each one.
What comes out is the app's real voice, sample for sample, and it is the same
every run.

`demo.py` wraps `sndPlay` (not `sfx` — `sfx()` is the *ask*, and one gesture
makes several; rank and the 60ms `SFX_GAP` settle what actually sounds a tick
later) and writes down every one with a page timestamp.

Under that: an ambient bed — drone, beating, and filtered air — and a slow
original pad that lifts under the title and end cards. Both are synthesised in
`sound.py`; neither is anyone's cue. The mix is mastered with two-pass
`loudnorm` to -14 LUFS / -1 dBTP, which is what YouTube normalises to.

```sh
python3 demo/sound.py --sfx        # render the app's sounds to out/sfx/
python3 demo/sound.py --preview    # also 20s of bed and pad, with levels
```

### The clapperboard

The page's clock is not the video's clock. Playwright's screencast only emits a
frame when the page changes and drops frames under load, so the recording comes
out shorter than the wall time it covers — about 450ms is lost during the boot,
when the app is busy.

So each pass flashes its cover white and flips it to black just before the
first scene, timestamping the flip (`demo.py:clap()`). `build.sh` finds that
white-to-black edge in the picture, and uses it for two things: the point to
trim the head back to, and the anchor that maps page time onto video time.

One clap is enough. Measured over a full 123s reel, head and tail claps came
out 450.0ms and 459.9ms — a slope of 0.99992, or a third of a frame over two
minutes. The loss is all in the boot, which is before the clap.

## Why it is filmed in four pieces

`build.sh` records `reel-a` (the desktop tour), the phone pass, `reel-c` (the
end card) and `hero`, then joins the first three. Two reasons:

- **The phone cannot be in the same take.** It was an iframe inside the desktop
  reel at first, which was tidier. But an iframe on a page that has any
  compositing-promoted layer on it — and the caption overlay has several,
  between its fades and its animated cursor — is not composited into a headless
  capture, and films as a solid black rectangle. Transform, an `opacity`
  transition on an ancestor, z-order, hiding the overlay again afterwards: none
  of it helps. A separate pass at a phone's viewport, laid into `plate.png` by
  ffmpeg, does.
- **The joins land on file boundaries,** which are exact.

## Changing it

The copy is in the scene functions, one `d.cap(...)` per beat. Keep it in the
app's own voice — plain, lowercase, no adjectives it has not earned.

Four things that are easy to get wrong:

- **Pacing.** `d.cap()` holds only briefly on purpose; the caption is meant to
  be read *while* the thing happens. Holding for the full reading time before
  touching anything turns the reel into a slideshow.
- **The lower third covers the bottom of the screen.** The dictation read-out
  lives down there, so the voice scene passes `pos="top"`. Any new scene whose
  payoff is in the bottom-left needs the same.
- **Do not cross two fades.** The opening holds the title card until it is
  opaque *before* lifting the blackout. Running both at once leaves a moment
  where neither is at full and the journal shows through the title.
- **A filtergraph cannot contain spaces.** A backslash-continuation inside
  shell quotes keeps the indentation after it, and ffmpeg will not parse that —
  but it exits 0 having written an empty container, so it fails silently. The
  hero filter is one long line for this reason, and `want()` checks the
  durations afterwards.

`--proof` is the way to check a scene: the shots are taken from the live page
at the exact moment, rather than by seeking the finished video.
