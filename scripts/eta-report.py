#!/usr/bin/env python3
"""The crew's estimate accuracy through time, as one self-contained HTML page.

    scripts/eta-report.py [-o OUT.html] [--json ETAS.json] [--window N]

Reads `engineer.py etas` (every engineer's eta_done records: took over the
first estimate said, per task; or a saved copy of its output with --json)
and writes a page with no outside fetch at all - reports are served under a
CSP sandbox and read on a phone - holding:

  1. a scatter of each record's ratio (took / said_first) against the day
     its task ended, one colour per engineer, on a log scale with 1.0 (the
     estimate exact) marked: a point's task shows on hover (its SVG title)
     or a tap (the line under the chart);
  2. the crew's rolling median ratio over the last --window records (15)
     on the same axes, drawn from the window's fifth record on;
  3. a table of each engineer's median and record count, and the crew's.

Publish it with `scripts/report.py publish OUT.html --title ...`.
"""
import argparse
import calendar
import html
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
# distinct on the dark ground, LCARS-ish first; cycled past twelve
COLOURS = ["#ff9966", "#99ccff", "#cc99cc", "#ffcc66", "#66cc99", "#ff6666",
           "#9999ff", "#ccdd66", "#66cccc", "#ff99cc", "#dddddd", "#cc9966"]
W, H = 640, 400
ML, MR, MT, MB = 58, 12, 14, 40  # the plot's margins inside the viewBox


def median(xs):
    xs = sorted(xs)
    n = len(xs)
    return None if not n else xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def parse_iso(s):
    try:
        return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ")) if s else None
    except ValueError:
        return None


def load(path):
    if path:
        with open(path) as f:
            return json.load(f)
    r = subprocess.run([sys.executable, os.path.join(HERE, "engineer.py"), "etas"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        sys.exit("engineer.py etas failed: " + (r.stderr or r.stdout).strip())
    return json.loads(r.stdout)


def points(data):
    """[(ended epoch, ratio, engineer, record)] with a ratio and an end,
    oldest first; and the engineers in name order."""
    pts = []
    for name, e in (data.get("engineers") or {}).items():
        for rec in e.get("records") or []:
            t, r = parse_iso(rec.get("ended")), rec.get("ratio")
            if t is not None and r is not None:
                pts.append((t, r, name, rec))
    pts.sort(key=lambda p: p[0])
    return pts, sorted(data.get("engineers") or {})


def rolling(pts, window):
    """The crew's median over the last `window` records at each record,
    from min(5, window) records on: fewer is noise, not a trend."""
    out = []
    for i in range(len(pts)):
        if i + 1 >= min(5, window):
            out.append((pts[i][0], median([p[1] for p in pts[max(0, i + 1 - window):i + 1]])))
    return out


def chart(pts, engs, roll):
    colour = {n: COLOURS[i % len(COLOURS)] for i, n in enumerate(engs)}
    t0, t1 = pts[0][0], pts[-1][0]
    if t1 - t0 < 86400:
        t0, t1 = t0 - 43200, t1 + 43200
    pad = (t1 - t0) * 0.02
    t0, t1 = t0 - pad, t1 + pad
    # a ratio of 0 (took under a minute) cannot sit on a log axis: drawn
    # hollow on the floor
    floor = 0.02
    rs = [max(p[1], floor) for p in pts]
    lo = 10 ** math.floor(math.log10(min(rs + [0.5])))
    hi = 10 ** math.ceil(math.log10(max(rs + [2.0])))
    pw, ph = W - ML - MR, H - MT - MB

    def x(t):
        return ML + (t - t0) / (t1 - t0) * pw

    def y(r):
        return MT + (math.log10(hi) - math.log10(r)) / (math.log10(hi) - math.log10(lo)) * ph

    s = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="estimate ratio over time">']
    # the y grid: each decade, and 2 and 5 within it
    d = lo
    while d <= hi * 1.0001:
        for m in (1, 2, 5):
            v = d * m
            if lo <= v <= hi * 1.0001:
                yy = y(v)
                major = m == 1
                s.append(f'<line x1="{ML}" x2="{W - MR}" y1="{yy:.1f}" y2="{yy:.1f}" class="{"g1" if major else "g2"}"/>')
                s.append(f'<text x="{ML - 6}" y="{yy + 4:.1f}" text-anchor="end">{v:g}×</text>')
        d *= 10
    # the x grid: a tick a day, or fewer so labels never crowd
    days = (t1 - t0) / 86400
    step = max(1, math.ceil(days / 10))
    t = (math.ceil(t0 / 86400)) * 86400
    while t <= t1:
        xx = x(t)
        s.append(f'<line x1="{xx:.1f}" x2="{xx:.1f}" y1="{MT}" y2="{H - MB}" class="g2"/>')
        s.append(f'<text x="{xx:.1f}" y="{H - MB + 16}" text-anchor="middle">{time.strftime("%b %d", time.gmtime(t))}</text>')
        t += step * 86400
    y1 = y(1.0)
    s.append(f'<line x1="{ML}" x2="{W - MR}" y1="{y1:.1f}" y2="{y1:.1f}" class="one"/>')
    s.append(f'<text x="{W - MR - 4}" y="{y1 - 5:.1f}" text-anchor="end" class="onel">1.0 = as said</text>')
    s.append(f'<text x="{ML - 44}" y="{MT + ph / 2:.0f}" transform="rotate(-90 {ML - 44} {MT + ph / 2:.0f})" '
             'text-anchor="middle">took / said first</text>')
    if roll:  # under the points, so a tap on one is never the line's
        path = " ".join(f'{"M" if i == 0 else "L"}{x(t):.1f},{y(m):.1f}' for i, (t, m) in enumerate(roll))
        s.append(f'<path d="{path}" class="roll"/>')
    for t, r, n, rec in pts:
        tip = (f'{n}: {rec.get("task") or "(no task)"} - said {rec.get("said_first")}, took {rec.get("took")} min '
               f'({r:g}×), ended {(rec.get("ended") or "")[:16].replace("T", " ")}Z')
        paint = f'style="fill:none;stroke:{colour[n]};stroke-width:2"' if r < floor else f'fill="{colour[n]}"'
        s.append(f'<circle cx="{x(t):.1f}" cy="{y(max(r, floor)):.1f}" r="6" {paint} data-tip="{html.escape(tip)}">'
                 f'<title>{html.escape(tip)}</title></circle>')
    s.append("</svg>")
    return "\n".join(s), colour


def page(data, window):
    pts, engs = points(data)
    if not pts:
        return "<!doctype html><meta charset=utf-8><title>Estimate accuracy</title><p>No estimate records yet.</p>"
    roll = rolling(pts, window)
    svg, colour = chart(pts, engs, roll)
    legend = "".join(f'<span><i style="background:{colour[n]}"></i>{html.escape(n)}</span>' for n in engs
                     if (data["engineers"][n].get("records")))
    legend += f'<span><i class="rl"></i>crew median, last {window}</span>'
    rows = []
    for n in sorted(engs, key=lambda n: -len(data["engineers"][n].get("records") or [])):
        e = data["engineers"][n]
        cnt = sum(1 for r in e.get("records") or [] if r.get("ratio") is not None)
        med, own = e.get("median_ratio"), e.get("own_ratio")
        rows.append(f'<tr><td><i style="background:{colour[n]}"></i>{html.escape(n)}</td><td>{cnt}</td>'
                    f'<td>{"" if med is None else f"{med:g}"}</td>'
                    f'<td>{"" if own is None else f"{own:g}"}</td></tr>')
    crew = data.get("crew_median_ratio")
    rows.append(f'<tr class="crew"><td>the crew</td><td>{data.get("records", len(pts))}</td>'
                f'<td>{"" if crew is None else f"{crew:g}"}</td><td></td></tr>')
    last = roll[-1][1] if roll else None
    made = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crew estimate accuracy</title>
<style>
body {{ background:#000; color:#ddd; font:15px/1.4 system-ui, sans-serif; margin:0; padding:12px; }}
h1 {{ color:#ff9966; font-size:20px; margin:4px 0 2px; }}
p {{ margin:4px 0 10px; color:#aaa; }}
svg {{ width:100%; height:auto; display:block; background:#0b0b10; border-radius:8px; }}
svg text {{ fill:#999; font-size:14px; }}
.g1 {{ stroke:#444; }} .g2 {{ stroke:#222; }}
.one {{ stroke:#ffcc66; stroke-width:1.5; stroke-dasharray:6 4; }} .onel {{ fill:#ffcc66; }}
.roll {{ pointer-events:none; fill:none; stroke:#fff; stroke-width:2.5; opacity:.85; }}
circle {{ opacity:.85; stroke:#000; stroke-width:1; cursor:pointer; }}
circle.on {{ stroke:#fff; stroke-width:2; opacity:1; }}
#tip {{ min-height:2.8em; padding:6px 2px; color:#eee; }}
.legend {{ display:flex; flex-wrap:wrap; gap:4px 14px; margin:8px 0; font-size:13px; }}
i {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:5px; vertical-align:-1px; }}
i.rl {{ border-radius:0; height:3px; width:18px; background:#fff; vertical-align:3px; }}
table {{ border-collapse:collapse; margin-top:8px; font-size:14px; }}
td, th {{ padding:4px 10px; text-align:right; border-bottom:1px solid #222; }}
td:first-child, th:first-child {{ text-align:left; }}
th {{ color:#ff9966; font-weight:600; }}
tr.crew td {{ color:#fff; font-weight:600; border-top:1px solid #555; }}
</style></head><body>
<h1>Crew estimate accuracy</h1>
<p>Each point is a task: the minutes it took over the first estimate said, by the day it ended
(log scale; under 1.0 it ran faster than said; hollow: took under a minute, a ratio of 0). {len(pts)} records;
the crew's median over the last {window} is {"-" if last is None else f"{last:.2f}"}×. Made {made}.</p>
{svg}
<div id="tip">Hover or tap a point for its task.</div>
<div class="legend">{legend}</div>
<table><tr><th>engineer</th><th>records</th><th>median</th><th>last 10</th></tr>
{"".join(rows)}</table>
<p>"median" is over every record kept (up to 30 each); "last 10" is the median that calibrates the bar
(engineer.py's own_ratio, from two records on).</p>
<script>
// a tap (phones have no hover) names the point under the chart
var tip = document.getElementById("tip"), on = null;
document.querySelector("svg").addEventListener("click", function (e) {{
  var c = e.target.closest("circle");
  if (!c) return;
  if (on) on.classList.remove("on");
  on = c; c.classList.add("on");
  tip.textContent = c.getAttribute("data-tip");
}});
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("-o", "--out", default="eta-report.html")
    ap.add_argument("--json", help="a saved `engineer.py etas` output instead of running it")
    ap.add_argument("--window", type=int, default=15, help="the rolling median's records (15)")
    a = ap.parse_args()
    with open(a.out, "w") as f:
        f.write(page(load(a.json), max(1, a.window)))
    print(a.out)


if __name__ == "__main__":
    main()
