#!/bin/sh
# The manual's pictures, made again (README.md, "The pictures"): frames of
# the console against perf.py's made-up journal, cropped and encoded as WebP
# into site/manual/img/. Then run build.py and look at every one: a crop
# below was chosen for the frame as it was, and a view that moved may need
# another.
#
#   site/manual/pictures.sh            # from the repo's root
#
# shots.py is a heavy job: an engineer runs this through the job line,
#   scripts/engineer.py job <name> -- site/manual/pictures.sh
# Needs Playwright's Chromium and ffmpeg (libwebp).
set -eu
cd "$(dirname "$0")/../.."
tmp=$(mktemp -d "${TMPDIR:-/tmp}/lcars-manual-shots.XXXXXX")
trap 'rm -rf "$tmp"' EXIT
python3 lcars-ui/test/shots.py "$tmp/shots" --only phone-list.png,phone-reader.png,desktop-edit.png,phone-capture.png,phone-tasks.png,phone-cal-week.png,phone-course.png,phone-voice.png,desktop-secret-locked.png
python3 site/manual/shots_crew.py "$tmp/extra"

# enc SOURCE FILTER NAME [QUALITY]: ffmpeg's crop=w:h:x:y then a width
enc() {
  ffmpeg -loglevel error -y -i "$tmp/$1" -vf "$2" -c:v libwebp -quality "${4:-50}" -compression_level 6 "site/manual/img/$3.webp"
  echo "img/$3.webp $(wc -c <"site/manual/img/$3.webp") bytes"
}
enc shots/phone-list.png "crop=780:1688:0:0,scale=360:-1" list
enc shots/desktop-edit.png "scale=640:-1" desk 45
enc shots/phone-voice.png "scale=360:-1" editor
enc shots/phone-capture.png "crop=780:1500:0:188,scale=360:-1" capture
enc shots/phone-reader.png "scale=360:-1" reader
enc shots/phone-tasks.png "crop=780:1100:0:200,scale=360:-1" tasks
enc shots/phone-cal-week.png "crop=780:1000:0:688,scale=360:-1" calendar
enc shots/phone-course.png "scale=360:-1" course
enc shots/desktop-secret-locked.png "crop=1584:640:1296:0,scale=480:-1" classified
enc extra/phone-chats.png "crop=786:1340:0:0,scale=360:-1" chats
enc extra/phone-room.png "crop=786:1704:0:0,scale=360:-1" room
enc extra/phone-questions.png "crop=786:1640:0:0,scale=360:-1" questions
echo "now: python3 site/manual/build.py, look at each picture, and commit img/ and the build"
