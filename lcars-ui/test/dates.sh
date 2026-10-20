#!/bin/sh
# The behaviour suite on the days a check reading "today" breaks: a month's
# first hours, a year's, both clock changes, a Sunday and a Monday, months
# after the journal's last row - each in the page's time zone and in the
# VPS's. Five checks failed only on such a day, found this way (0.152.3).
#
#   ./test/dates.sh        (6-15 min on the VPS, by its load; not part of run.sh)
#
# LCARS_TEST_NOW (test/gen.py) moves the page's clock and cuts the fixture
# back to the journal as it stood then. Read-only on $LCARS_TEST_DB, like
# run.sh.
cd "$(dirname "$0")/.."
T=test
fails=0
for tz in Europe/Helsinki America/New_York; do
  for now in "2026-09-30 22:30:00" "2026-10-01 03:30:00" "2026-10-01 05:30:00" \
             "2026-08-31 21:30:00" "2026-10-04 12:00:00" "2026-10-05 12:00:00" \
             "2026-10-25 01:30:00" "2026-03-29 21:30:00" "2026-12-31 22:30:00" \
             "2027-03-28 21:30:00"; do
    out=$(TZ=$tz LCARS_TEST_NOW="$now" python3 "$T/gen.py" > /dev/null &&
          TZ=$tz "$T/qjs" "$T/run.js" 2>&1 | grep -E "^(  FAIL|RESULT|SUITE .* THREW|TIMED)")
    rm -f "$T/run.js"
    if echo "$out" | grep -q "^RESULT: PASS" && ! echo "$out" | grep -qE "^(  FAIL|SUITE|TIMED)"; then
      echo "ok   $tz $now"
    else
      echo "FAIL $tz $now"
      echo "$out" | grep -v "^RESULT" | sed 's/^/     /'
      fails=$((fails + 1))
    fi
  done
done
echo "dates: $fails failing"
[ $fails = 0 ]
