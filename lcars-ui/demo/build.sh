#!/bin/sh
# Record the demo reel and encode it for upload.
#
#   ./demo/build.sh            # record everything, then encode
#   ./demo/build.sh --encode   # encode whatever is already in demo/out/
#
# Leaves behind, in demo/out/:
#   lcars-demo.mp4    H.264/yuv420p 1080p30 — YouTube, and every browser
#   lcars-demo.webm   VP9 — smaller, for embedding on a page yourself
#   poster.png        a still for the <video poster> attribute
#   chapters.txt      timestamps to paste into a YouTube description
#   hero.mp4          a silent ~12s loop for muted autoplay on a front page
#
# The soundtrack is rebuilt rather than recorded — headless Chromium has no
# audio device. See demo/sound.py and the clapperboard note below.
#
# The reel is filmed in four pieces. Three are joined here; the fourth is the
# front-page loop, which stands alone:
#
#   reel-a   the desktop tour, open .. quick capture
#   phone    the app at a phone's size, laid into plate.png (the bezel and
#            caption drawn at 1080p). It has to be its own pass: an iframe on
#            a page carrying the caption overlay does not composite into a
#            headless capture, and films as a black rectangle.
#   reel-c   the end card
#   hero     a silent, chrome-free clip, crossfaded end-to-start so it loops
#
# Separate passes rather than one long take because the joins then fall on file
# boundaries, which are exact. Cutting a single recording at a wall-clock mark
# is not: the capture starts a beat after the page does.
#
# Playwright ships an ffmpeg, but it is a cut-down build that can only write
# VP8 in a WebM — no H.264, no AAC, no ffprobe. This wants a real one.
# Nothing here touches the app itself.
set -e
cd "$(dirname "$0")/.."
OUT=demo/out
FADE=0.5                     # the cross-to-black at each join
FINAL_W=1920                 # the reel is filmed smaller and upscaled to this
FINAL_H=1080

for need in ffmpeg ffprobe; do
  command -v "$need" > /dev/null 2>&1 || {
    echo "$need not found. This needs a full ffmpeg:" >&2
    echo "  sudo apt-get install ffmpeg sox libsox-fmt-all python3-numpy" >&2
    exit 1
  }
done
FF=ffmpeg
echo "== encoder: $(ffmpeg -version | head -1)"

dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

# A filtergraph that produces no frames still writes a valid, empty container
# and still exits 0. That happened once and went unnoticed to the end of the
# build, so anything that matters gets looked at afterwards.
want() {
  D=$(dur "$1" 2>/dev/null || echo 0)
  python3 -c "import sys; sys.exit(0 if float('$D' or 0) >= $2 else 1)" || {
    echo "$1 came out ${D:-empty}s, expected at least ${2}s" >&2; exit 1; }
}
# `calc` keeps the fade arithmetic out of the shell — bc is not something to
# assume is installed, and this is already a python-shaped build.
calc() { python3 -c "print(f'{$1:.3f}')"; }

# Every pass records its own boot — the page load, the fonts, both API sweeps —
# behind the overlay's opening black, and then flashes the cover white for a
# moment and flips it back (demo.py's clap()). That flash does two jobs: it is
# where the head gets trimmed to, and it is the anchor that lets a soundtrack
# timed on the page's clock be laid against the picture.
#
# HANDLE is how much of the black after the flash to keep, so an opening fade
# still has something to fade from — and so the white itself is always gone.
HANDLE=0.05

# Where the phone video sits inside the plate. demo.py draws the bezel to
# match, so both read the same numbers out of it rather than keeping a copy.
eval "$(python3 -c "
import sys; sys.path.insert(0, 'demo'); import demo as D
print(f'PH_W={D.PHONE_SHOW_W}; PH_H={D.PHONE_SHOW_H}; PH_X={D.PHONE_AT[0]}; PH_Y={D.PHONE_AT[1]}')")"
clapfall() {
  "$FF" -v error -i "$1" \
     -vf "scale=64:36,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-" \
     -f null - 2>/dev/null | python3 -c "
import re, sys
t, rows = None, []
for line in sys.stdin:
    m = re.match(r'frame:\s*\d+\s+pts:\s*\d+\s+pts_time:([0-9.]+)', line)
    if m:
        t = float(m.group(1)); continue
    m = re.search(r'YAVG=([0-9.]+)', line)
    if m:
        rows.append((t, float(m.group(1))))
# the first dark frame after a bright run: the flip from white to black
for i in range(1, len(rows)):
    if rows[i - 1][1] > 150 and rows[i][1] < 100:
        print(f'{rows[i][0]:.3f}'); break
else:
    print('0.000')
"
}

# ---- record ---------------------------------------------------------------
if [ "$1" != "--encode" ] && [ "$1" != "--hero-only" ]; then
  echo "== recording the desktop tour (a couple of minutes — it plays in real time)"
  python3 demo/demo.py --proof --name reel-a \
    --only open,list,search,reader,links,graph,trend,month,tasks,stats,daypage,template,slash,voice,capture
  echo "== recording the phone pass"
  python3 demo/demo.py --phone
  echo "== recording the end card"
  python3 demo/demo.py --name reel-c --only close
  echo "== recording the hero loop"
  python3 demo/demo.py --hero
fi

if [ "$1" = "--hero-only" ]; then HERO_ONLY=1; else HERO_ONLY=; fi

if [ -z "$HERO_ONLY" ]; then
for f in reel-a.webm reel-c.webm phone.webm plate.png; do
  [ -f "$OUT/$f" ] || { echo "missing $OUT/$f — run without --encode" >&2; exit 1; }
done

# ---- the phone segment ----------------------------------------------------
# The plate is a still; looping it for the length of the phone video gives the
# bezel and the caption, and the recording drops inside the bezel. The phone
# pass opens and closes on its own black, so only the plate needs fading.
echo "== phone segment"
PCLAP=$(clapfall "$OUT/phone.webm")
PCUT=$(calc "$PCLAP + $HANDLE")
PDUR=$(calc "$(dur "$OUT/phone.webm") - $PCUT")
echo "   clap at ${PCLAP}s, trimming to ${PCUT}s, ${PDUR}s left"
"$FF" -v warning -stats -y \
  -loop 1 -framerate 30 -t "$PDUR" -i "$OUT/plate.png" \
  -ss "$PCUT" -i "$OUT/phone.webm" \
  -filter_complex "[0:v]format=yuv420p,fade=t=in:st=0:d=$FADE,fade=t=out:st=$(calc "$PDUR - $FADE"):d=$FADE[bg];[1:v]format=yuv420p,fps=30,scale=${PH_W}:${PH_H}[ph];[bg][ph]overlay=${PH_X}:${PH_Y}:format=auto,format=yuv420p,scale=${FINAL_W}:${FINAL_H}:flags=lanczos[v]" \
  -map "[v]" -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -r 30 \
  "$OUT/seg-phone.mp4"

# ---- normalise the two desktop pieces -------------------------------------
# Same codec, size and frame rate as the phone segment, so the concat below is
# a stream copy and nothing gets re-encoded twice.
norm() {
  IN="$1"; OUTF="$2"; FIN="$3"; FOUT="$4"
  CLAP=$(clapfall "$IN")
  CUT=$(calc "$CLAP + $HANDLE")
  D=$(calc "$(dur "$IN") - $CUT")
  echo "   clap at ${CLAP}s, trimming to ${CUT}s, ${D}s left"
  VF="format=yuv420p,fps=30"
  [ "$FIN" = "y" ] && VF="$VF,fade=t=in:st=0:d=$FADE"
  [ "$FOUT" = "y" ] && VF="$VF,fade=t=out:st=$(calc "$D - $FADE"):d=$FADE"
  # Filmed at 1280x720 so the UI lands 1.5x larger in the frame; this is where
  # it goes back up to 1080p. Scaling last keeps the fades on smaller frames.
  VF="$VF,scale=${FINAL_W}:${FINAL_H}:flags=lanczos"
  "$FF" -v warning -stats -y -ss "$CUT" -i "$IN" -vf "$VF" \
    -c:v libx264 -preset slow -crf 17 -pix_fmt yuv420p -r 30 -an "$OUTF"
}
echo "== desktop tour"
norm "$OUT/reel-a.webm" "$OUT/seg-a.mp4" n y      # opens on its own black card
ACLAP=$CLAP; ACUT=$CUT
echo "== end card"
norm "$OUT/reel-c.webm" "$OUT/seg-c.mp4" y n      # ends on its own black
CCLAP=$CLAP; CCUT=$CUT

# ---- join -----------------------------------------------------------------
echo "== joining"
printf "file '%s'\n" seg-a.mp4 seg-phone.mp4 seg-c.mp4 > "$OUT/parts.txt"
"$FF" -v warning -stats -y -f concat -safe 0 -i "$OUT/parts.txt" \
  -c copy "$OUT/joined.mp4"

# The end card fades to black and then the pass keeps recording for another
# couple of seconds while it shuts down. A beat of black to end on is wanted;
# two and a half is dead air on a front page. Cut back to TAIL of it.
TAIL=0.7
JDUR=$(dur "$OUT/joined.mp4")
ENDS=$("$FF" -v info -i "$OUT/joined.mp4" -vf "blackdetect=d=0.3:pic_th=0.99" -f null - 2>&1 \
  | python3 -c "
import re, sys
last = None
for line in sys.stdin:
    m = re.search(r'black_start:(\S+) black_end:(\S+)', line)
    if m and float(m.group(2)) >= $JDUR - 0.25:   # a run that reaches the end
        last = float(m.group(1))
print(f'{last + $TAIL:.3f}' if last is not None else '$JDUR')
")
echo "   ${JDUR}s joined, ending at ${ENDS}s"
"$FF" -v warning -stats -y -i "$OUT/joined.mp4" -t "$ENDS" -c copy "$OUT/silent.mp4"
rm -f "$OUT/joined.mp4"

# ---- the soundtrack -------------------------------------------------------
# Each part carries its own clap, so each has its own page-clock-to-video-clock
# offset; the plan hands sound.py what was measured off the picture and it does
# the arithmetic. The lifts are where the pad comes up — under the two cards,
# which are the only stretches with no app noise to share the room with.
echo "== soundtrack"
# The app's own voices, rendered through its own scheduler. They only change
# when the SFX table does, so this is skipped once they exist.
[ -f "$OUT/sfx/boot.wav" ] || python3 demo/sound.py --sfx --out "$OUT"
ADUR=$(dur "$OUT/seg-a.mp4")
SDUR=$(dur "$OUT/seg-phone.mp4")
COFF=$(calc "$ADUR + $SDUR")
python3 - "$OUT" "$ENDS" "$ADUR" "$COFF" \
         "$ACLAP" "$ACUT" "$PCLAP" "$PCUT" "$CCLAP" "$CCUT" <<'PY'
import json, pathlib, sys
out, ends, adur, coff, acl, acu, pcl, pcu, ccl, ccu = (
    pathlib.Path(sys.argv[1]), *[float(v) for v in sys.argv[2:]])
plan = {
    "seconds": ends,
    # the pad comes up under the title card and again under the end card
    "lifts": [[0.0, 6.8], [coff + 0.8, ends]],
    # the boot chime fires while the journal is still landing, which is before
    # the hook is in place — and it is the one flourish in the palette, so it
    # is placed by hand under the title card
    "extra": [["boot", 0.9]],
    "parts": [
        {"audio": "reel-a.audio.json", "clap_video": acl, "cut": acu, "offset": 0.0},
        {"audio": "phone.audio.json",  "clap_video": pcl, "cut": pcu, "offset": adur},
        {"audio": "reel-c.audio.json", "clap_video": ccl, "cut": ccu, "offset": coff},
    ],
}
(out / "plan.json").write_text(json.dumps(plan, indent=2) + "\n")
PY
python3 demo/sound.py --track "$OUT/plan.json" --out "$OUT"

# Two-pass loudnorm: the one-pass version normalises dynamically and pumps the
# bed under every chirp. Measure, then apply what was measured.
echo "== mastering"
MEAS=$("$FF" -hide_banner -i "$OUT/track.wav" \
  -af "loudnorm=I=-14:TP=-1:LRA=11:print_format=json" -f null - 2>&1 \
  | python3 -c "
import json, sys, re
txt = sys.stdin.read()
m = re.search(r'\{[^{}]*input_i[^{}]*\}', txt, re.S)
d = json.loads(m.group(0))
print(':'.join(f'measured_{k}={d[\"input_\" + k]}' for k in ('i','lra','tp','thresh'))
      + f':offset={d[\"target_offset\"]}')
")
"$FF" -v warning -stats -y -i "$OUT/track.wav" \
  -af "loudnorm=I=-14:TP=-1:LRA=11:$MEAS:linear=true" \
  -ar 48000 "$OUT/track-master.wav"

echo "== mux"
"$FF" -v warning -stats -y -i "$OUT/silent.mp4" -i "$OUT/track-master.wav" \
  -map 0:v -map 1:a -c:v copy -c:a aac -b:a 192k -shortest \
  -movflags +faststart "$OUT/lcars-demo.mp4"

# -cpu-used 2 rather than libvpx's default 0: on a two and a half minute 1080p
# clip that is the difference between a couple of minutes and twenty, and at
# this CRF the two are not distinguishable on flat colour and type.
want "$OUT/lcars-demo.mp4" 30

echo "== webm"
"$FF" -v warning -stats -y -i "$OUT/lcars-demo.mp4" \
  -c:v libvpx-vp9 -crf 31 -b:v 0 -row-mt 1 -tile-columns 2 \
  -deadline good -cpu-used 2 \
  -pix_fmt yuv420p -r 30 -c:a libopus -b:a 128k "$OUT/lcars-demo.webm"

# A frame from the middle of the link-graph beat: the one picture that says
# what the app is. -ss before -i so it seeks rather than decodes up to it.
echo "== poster"
POSTER_AT=$(python3 -c "
import json
m = {s['scene']: s for s in json.load(open('$OUT/reel-a.marks.json'))}
g = m.get('graph')
print(round(g['start'] + (g['end'] - g['start']) * 0.55, 2) if g else 30)
" 2>/dev/null || echo 30)
"$FF" -v error -y -ss "$POSTER_AT" -i "$OUT/lcars-demo.mp4" -vframes 1 "$OUT/poster.png"

# ---- chapters -------------------------------------------------------------
# YouTube reads these out of a description as long as the first one is 0:00.
ADUR=$(dur "$OUT/seg-a.mp4")
SDUR=$(dur "$OUT/seg-phone.mp4")
python3 - "$OUT" "$ADUR" "$SDUR" <<'PY' > "$OUT/chapters.txt"
import json, pathlib, sys
TITLES = {
    "open": "LCARS", "list": "The journal", "search": "Search",
    "reader": "Markdown", "links": "Links and backlinks", "graph": "The link graph",
    "trend": "Trends", "month": "Month view", "tasks": "Tasks",
    "stats": "Statistics", "daypage": "Day pages", "template": "Templates",
    "slash": "Slash commands", "voice": "Voice", "capture": "Quick capture",
}
out, adur, sdur = pathlib.Path(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3])
marks = json.loads((out / "reel-a.marks.json").read_text())
# The recording starts a beat before the first scene; pin chapter one to 0:00
# so YouTube accepts the list at all.
off = marks[0]["start"]
rows = [(0 if i == 0 else max(0, m["start"] - off), TITLES.get(m["scene"], m["scene"]))
        for i, m in enumerate(marks)]
rows.append((adur, "On a phone"))
rows.append((adur + sdur, "One file"))
for t, title in rows:
    print(f"{int(t // 60)}:{int(t % 60):02d} {title}")
PY

fi   # end of the main assembly

# ---- the hero loop --------------------------------------------------------
# Silent, chrome-free, and joined end-to-start so it can sit on a page on
# repeat. The clip already returns to the state it opened on; the crossfade
# hides the one frame where it jumps.
if [ -f "$OUT/hero.webm" ]; then
  echo "== hero loop"
  HCLAP=$(clapfall "$OUT/hero.webm")
  HCUT=$(calc "$HCLAP + 1.0")                 # past the opening fade
  HDUR=$(calc "$(dur "$OUT/hero.webm") - $HCUT")
  X=0.6                                       # the crossfade
  HOUT=$(calc "$HDUR - $X")
  echo "   clap at ${HCLAP}s, ${HDUR}s of loop, ${HOUT}s out"
  # One line, deliberately. A backslash-continuation inside the quotes keeps
  # the indentation that follows it, and ffmpeg will not parse a filtergraph
  # with spaces in it. `alpha=1` also goes before `d=`, so that `$X:a` cannot
  # be read as a parameter expansion by a shell that has such things.
  HFILT="[0:v]format=yuv420p,fps=30,split[a][b];[a]trim=0:${HOUT},setpts=PTS-STARTPTS[main];[b]trim=${HOUT}:${HDUR},setpts=PTS-STARTPTS,format=yuva420p,fade=t=in:alpha=1:st=0:d=${X}[tail];[main][tail]overlay=eof_action=pass,format=yuv420p,scale=${FINAL_W}:${FINAL_H}:flags=lanczos[v]"
  ffmpeg -v warning -stats -y -ss "$HCUT" -i "$OUT/hero.webm" \
    -filter_complex "$HFILT" \
    -map "[v]" -c:v libx264 -preset slow -crf 18 -pix_fmt yuv420p -r 30 -an \
    -movflags +faststart "$OUT/hero.mp4"
  # Straight to its final name: ffmpeg picks the container from the extension,
  # and a ".tmp" leaves it with nothing to go on. Writing that through an `&&`
  # also hid the failure, because `set -e` does not fire inside a condition.
  ffmpeg -v warning -stats -y -i "$OUT/hero.mp4" \
    -c:v libvpx-vp9 -crf 33 -b:v 0 -row-mt 1 -deadline good -cpu-used 2 \
    -pix_fmt yuv420p -an "$OUT/hero-loop.webm"
  want "$OUT/hero.mp4" 5
  ffmpeg -v error -y -ss 0.2 -i "$OUT/hero.mp4" -vframes 1 "$OUT/hero-poster.png"
fi

echo
ls -la "$OUT"/lcars-demo.mp4 "$OUT"/lcars-demo.webm "$OUT"/poster.png \
       "$OUT"/hero.mp4 "$OUT"/hero-loop.webm 2>/dev/null
echo
echo "chapters:"
cat "$OUT/chapters.txt"
