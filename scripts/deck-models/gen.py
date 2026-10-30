#!/usr/bin/env python3
"""The generated road for one deck prop (docs/design/deck-remodel.md
section 3 item 4, slice 9; deck-pipeline.md, "A generated prop"): its
views on Seedream, then Higgsfield's image-to-3D job, the glb downloaded at
once and a LICENSE.txt beside it.

    scripts/deck-models/gen.py PROP                # the plan and its price: spends nothing
    scripts/deck-models/gen.py PROP --spend N      # run it, at most N credits
    scripts/deck-models/gen.py PROP --spend N --redo back,3d   # re-roll steps

The prop's folder is the media store's, as the generated chairs' are:
MEDIA/media/deck-models/PROP/ (MEDIA is $LCARS_MEDIA_ROOT, else ~/.env's
line, as build.sh finds it; --media overrides). Its raw/prompts.txt says
what to make, in `key: value` lines (a line indented under one continues
it; # starts a comment line):

    road: multiview        multiview (four views, Tripo H3.1 multiview),
                           image (one view, Tripo H3.1 image) or text
                           (no views: Tripo's text to 3D from `prompt`)
    object: one three-seat sofa, ...      what it is, in every view's prompt
    palette: warm taupe weave #8a6c58, ...   the colours by name and hex
    front: straight from the front, ...   a view each the road needs (multiview:
    back: / left: / right:                front, back, left, right; image: front)
    refs: concept.png                     images in raw/ every view is shown too
    left_refs: front                      the earlier views one is shown (default: all
                                          of them; a side shown the front and the back
                                          came out a front or a back, 2026-10-30)
    prompt: ...                           text road: the whole prompt
    params: face_limit=2400 pbr=true      the 3D job's, as `generate create` takes them
    lead: ...                             replaces LEAD below (rarely)

Steps run in this order: the views front, back, left, right (each given
the views before it as references: the front sets the object, the back
is the front's other side, the sides see both, bridge-redesign.md 8c),
then the 3D job with the views in Tripo's slot order front, left, back,
right ("left" the object's own: its front swings to the camera's left).

Nothing is spent without --spend: first every step's price is asked of
`higgsfield generate cost` with its real prompt, references and params
(a reference stood in for by a placeholder id: the price is per job, not
per image), printed with the total and the balance, and the script stops.
With --spend N it refuses before a job when what it has spent this run
plus that job's price would pass N, so N is a hard cap; a step already
done (its file in raw/ and its record in raw/gen.json) is skipped, and
--redo names steps to make again. A job is recorded as pending in
gen.json the moment it is made, so a run stopped while it waits (its
turn ended, the box restarted) has the next run fetch it, not pay again. Each job is created, waited for, read
back with `generate get` and its result downloaded at once (Higgsfield
keeps outputs for a time only): raw/<view>.png, raw/raw.glb. raw/gen.json
records every job (id, model, price, the balance before and after, the
url) and the credits spent. LICENSE.txt is written beside the folder's
glb the first time the 3D job lands.

What it does not do: the fit. Turning, scaling to the stand-in and
recolouring stay per prop, raw/fit.py in Blender (as the chairs' did),
writing the folder's PROP.glb that build.sh hands the room script.
"""
import argparse
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

IMAGE_MODEL = "seedream_5_0_flash"
IMAGE_PARAMS = {"aspect_ratio": "1:1", "resolution": "2k"}
ROADS = {
    "multiview": ("tripo_h3_1_multiview_to_3d", ["front", "back", "left", "right"]),
    "image": ("tripo_h3_1_image_to_3d", ["front"]),
    "text": ("tripo_3d", []),
}
SLOTS = ["front", "left", "back", "right"]  # Tripo's multiview order
# The prompt kit's lead (deck-remodel.md section 3 item 3): what an
# image-to-3D job reads best - one object, centred, flat even light, a plain
# ground, no perspective, nothing shiny that bakes in as a highlight
LEAD = ("Product reference for a real-time 3D model: one {object} alone, centred, filling 80% of a square frame, "
        "level camera at the object's middle, long lens, no perspective distortion, on a plain flat 50% grey ground "
        "with no horizon, soft even overcast light from every side, no cast shadow, no reflections, satin not mirror "
        "metal, no glass, no text, no logos.")
# a reference's stand-in when pricing, one id each
PLACEHOLDER = "00000000-0000-0000-0000-{:012d}"
HF = os.environ.get("LCARS_HIGGSFIELD", "higgsfield")


def die(msg, code=2):
    print(f"gen.py: {msg}", file=sys.stderr)
    sys.exit(code)


def media_root(arg):
    if arg:
        return arg
    root = os.environ.get("LCARS_MEDIA_ROOT")
    if not root:
        # the one line, as build.sh reads it: nothing else of ~/.env
        try:
            for line in open(os.path.expanduser("~/.env")):
                m = re.match(r"""^(?:export )?LCARS_MEDIA_ROOT=["']?([^"'\n]*)""", line)
                if m:
                    root = m.group(1)
        except OSError:
            pass
    if not root:
        die("no media root: set LCARS_MEDIA_ROOT or pass --media")
    return root


def read_prompts(path):
    """`key: value` lines, an indented line continuing the one above."""
    keys, last = {}, None
    for n, line in enumerate(open(path), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] in " \t" and last:
            keys[last] += " " + line.strip()
            continue
        m = re.match(r"([a-z_]+):\s*(.*)", line.rstrip("\n"))
        if not m:
            die(f"{path}:{n}: not a `key: value` line")
        last = m.group(1)
        keys[last] = m.group(2).strip()
    return keys


def parse_params(s):
    out = {}
    for tok in (s or "").split():
        k, eq, v = tok.partition("=")
        if not eq or not k:
            die(f"params: {tok!r} is not name=value")
        out[k] = v
    return out


def plan(p, raw):
    """The steps: (name, model, prompt or None, {param: value}, [reference files])."""
    road = p.get("road", "multiview")
    if road not in ROADS:
        die(f"road: {road!r}, not one of {', '.join(ROADS)}")
    model3d, views = ROADS[road]
    refs = [os.path.join(raw, f) for f in p.get("refs", "").split()]
    for f in refs:
        if not os.path.isfile(f):
            die(f"refs: {f} is not there")
    steps = []
    if road == "text":
        if not p.get("prompt"):
            die("road text needs a prompt:")
    else:
        for k in ("object", "palette"):
            if not p.get(k):
                die(f"road {road} needs {k}:")
        lead = p.get("lead") or LEAD.format(object=p["object"])
        for i, v in enumerate(views):
            if not p.get(v):
                die(f"road {road} needs a {v}: view")
            prompt = f"{lead} The view: {p[v]} Colours: {p['palette']}."
            shown = p[v + "_refs"].split() if v + "_refs" in p else views[:i]
            for w in shown:
                if w not in views[:i]:
                    die(f"{v}_refs: {w} is not a view made before {v}")
            steps.append((v, IMAGE_MODEL, prompt, dict(IMAGE_PARAMS),
                          refs + [os.path.join(raw, w + ".png") for w in shown]))
    params = parse_params(p.get("params"))
    if road == "text":
        steps.append(("3d", model3d, p["prompt"], params, []))
    else:
        order = SLOTS if road == "multiview" else views
        steps.append(("3d", model3d, None, params, [os.path.join(raw, v + ".png") for v in order]))
    return steps


def hf(*args, timeout=180):
    """The CLI, its JSON on stdout. Its stdin is /dev/null: given no --prompt
    (an image-to-3D job) the CLI 1.2.2 reads its prompt from a stdin that is
    not a terminal, and waits for ever on an open one. Bounded all the same,
    so nothing holds the seat; a job's own wait is `generate wait`'s."""
    try:
        r = subprocess.run([HF, *args], capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        die(f"{HF} {' '.join(args[:2])}: no answer in {timeout}s", 1)
    if r.returncode:
        die(f"{HF} {' '.join(args[:2])}: {(r.stderr or r.stdout).strip()}", 1)
    return r.stdout


def flags(prompt, params, images):
    a = []
    if prompt is not None:
        a += ["--prompt", prompt]
    for k, v in params.items():
        a += [f"--{k}", v]
    for f in images:
        a += ["--image-references", f]
    return a


def cost(model, prompt, params, images):
    out = json.loads(hf("generate", "cost", model, *flags(prompt, params, [PLACEHOLDER.format(i + 1) for i in range(len(images))]), "--json"))
    return float(out["credits"])


def balance():
    return float(json.loads(hf("account", "status", "--json"))["credits"])


def find(obj, key):
    """The first `key` anywhere in a JSON answer (`generate get`'s is the
    job's object; its shape is not documented)."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        obj = list(obj.values())
    if isinstance(obj, list):
        for x in obj:
            v = find(x, key)
            if v is not None:
                return v
    return None


def create_job(model, prompt, params, images):
    made = json.loads(hf("generate", "create", model, *flags(prompt, params, images), "--json", timeout=600))
    # the CLI 1.2.2 answers a list of the new jobs' ids; a job object kept in case
    jid = made[0] if isinstance(made, list) and made and isinstance(made[0], str) else find(made, "id")
    if not jid:
        die(f"generate create {model}: no job id in {json.dumps(made)[:300]}", 1)
    return jid


def finish_job(jid, timeout):
    print(f"  job {jid}, waiting", flush=True)
    hf("generate", "wait", jid, "--quiet", "--timeout", timeout, timeout=3600)
    job = json.loads(hf("generate", "get", jid, "--json"))
    status, url = find(job, "status"), find(job, "result_url")
    if status != "completed" or not url:
        die(f"job {jid} ended {status}, no result: {json.dumps(job)[:300]}", 1)
    return url


def save(path, state):
    with open(path + ".part", "w") as w:
        json.dump(state, w, indent=1)
    os.replace(path + ".part", path)


def download(url, path):
    tmp = path + ".part"
    with urllib.request.urlopen(url, timeout=300) as r, open(tmp, "wb") as w:
        shutil.copyfileobj(r, w)
    os.replace(tmp, path)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("prop")
    ap.add_argument("--spend", type=float, help="run, spending at most this many credits")
    ap.add_argument("--redo", default="", help="steps to make again, comma-separated (front,back,left,right,3d)")
    ap.add_argument("--media", help="the media root (default: $LCARS_MEDIA_ROOT, else ~/.env's)")
    ap.add_argument("--timeout", default="20m", help="each job's wait (default 20m)")
    a = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9_]+", a.prop):
        die(f"{a.prop!r}: a prop is a slug, [a-z0-9_]")
    folder = os.path.join(media_root(a.media), "media", "deck-models", a.prop)
    raw = os.path.join(folder, "raw")
    pf = os.path.join(raw, "prompts.txt")
    if not os.path.isfile(pf):
        die(f"{pf}: no prompts (the module's docstring says what goes in it)")
    p = read_prompts(pf)
    steps = plan(p, raw)
    names = [s[0] for s in steps]
    redo = [x for x in a.redo.split(",") if x]
    for x in redo:
        if x not in names:
            die(f"--redo {x}: not a step of this prop ({', '.join(names)})")
    sf = os.path.join(raw, "gen.json")
    state = json.load(open(sf)) if os.path.exists(sf) else {"jobs": [], "done": {}, "pending": {}, "spent": 0}
    out = {s[0]: os.path.join(raw, ("raw.glb" if s[0] == "3d" else s[0] + ".png")) for s in steps}
    todo = [s for s in steps if s[0] in redo or not (s[0] in state["done"] and os.path.exists(out[s[0]]))]
    # a step after a re-made view is made again too: it was shown the old one
    first = next((i for i, s in enumerate(steps) if s in todo), None)
    if first is not None and redo:
        todo = steps[first:]

    print(f"{a.prop}: road {p.get('road', 'multiview')}, {folder}")
    pending = state.setdefault("pending", {})
    for x in redo:
        pending.pop(x, None)
    prices, total = {}, 0.0
    for name, model, prompt, params, images in steps:
        if (name, model, prompt, params, images) not in todo:
            print(f"  {name:6} {model}: done ({state['done'][name]['credits']:g}), skipped")
            continue
        if name in pending:
            # created and paid for by a run that stopped before its result
            # landed (its turn ended, the box restarted): waited for, not
            # made again
            prices[name] = 0.0
            print(f"  {name:6} {model}: job {pending[name]['id']} already made ({pending[name]['price']:g}), "
                  "its result fetched")
            continue
        prices[name] = cost(model, prompt, params, images)
        total += prices[name]
        print(f"  {name:6} {model} {' '.join(f'{k}={v}' for k, v in params.items())}"
              f"{f', {len(images)} reference(s)' if images else ''}: {prices[name]:g} credits")
    bal = balance()
    print(f"  total {total:g} credits; the balance {bal:g}")
    if not todo:
        print("nothing to make")
        return
    if a.spend is None:
        print(f"stopped: nothing spent. Run again with --spend N (N >= {total:g}) to make it.")
        return
    if total > a.spend:
        die(f"the steps cost {total:g}, over --spend {a.spend:g}: nothing spent")
    if total > bal:
        die(f"the steps cost {total:g}, the balance is {bal:g}: nothing spent")

    spent = 0.0
    for name, model, prompt, params, images in todo:
        if spent + prices[name] > a.spend:
            die(f"{name}: {spent:g} spent + {prices[name]:g} would pass --spend {a.spend:g}; stopped")
        missing = [f for f in images if not os.path.exists(f)]
        if missing:
            die(f"{name}: its references are not there ({', '.join(missing)})", 1)
        print(f"{name}: {model}", flush=True)
        if name in pending:
            jid, before, took = pending[name]["id"], pending[name]["balance_before"], pending[name]["price"]
        else:
            before = balance()
            jid = create_job(model, prompt, params, images)
            # recorded before the wait: a run stopped from here on has paid
            # for the job, and the next one fetches it rather than paying again
            pending[name] = {"id": jid, "model": model, "price": prices[name], "balance_before": before}
            save(sf, state)
            took = None
        url = finish_job(jid, a.timeout)
        download(url, out[name])
        after = balance()
        if took is None:
            # what the balance says it cost (the price was the estimate)
            took = round(before - after, 4)
        spent += took
        rec = {"step": name, "id": jid, "model": model, "params": params, "price": prices[name], "credits": took,
               "balance_before": before, "balance_after": after, "url": url, "file": os.path.basename(out[name]),
               "at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")}
        if prompt is not None:
            rec["prompt"] = prompt
        state["jobs"].append(rec)
        state["done"][name] = rec
        pending.pop(name, None)
        state["spent"] = round(state["spent"] + took, 4)
        save(sf, state)
        print(f"  {os.path.relpath(out[name], folder)} ({os.path.getsize(out[name])} bytes), {took:g} credits", flush=True)
    lic = os.path.join(folder, "LICENSE.txt")
    if not os.path.exists(lic):
        disp = {"tripo_h3_1_multiview_to_3d": "Tripo H3.1 multiview", "tripo_h3_1_image_to_3d": "Tripo H3.1 image",
                "tripo_3d": "Tripo text to 3D"}.get(steps[-1][1], steps[-1][1])
        views = "" if p.get("road") == "text" else ", from views made with Seedream 5.0 Flash"
        with open(lic, "w") as w:
            w.write(f"{a.prop}: generated with Higgsfield ({disp}{views}) on the captain's plan, "
                    f"{datetime.date.today().isoformat()}, the output the captain's under Higgsfield's terms.\n")
    print(f"done: {spent:g} credits this run, {state['spent']:g} in all; the balance {balance():g}. "
          f"Next: raw/fit.py writes {a.prop}.glb (deck-pipeline.md, \"A generated prop\").")


if __name__ == "__main__":
    main()
