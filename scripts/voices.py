#!/usr/bin/env python3
"""The captain's ElevenLabs account, for the engineers' voices
(docs/design/engineer-voices.md; Number One's order, 2026-10-27).

    voices.py account [--json]        the plan: tier, voice slots, credits this
                                      month and their reset, what it may do
    voices.py design LABEL --description TEXT (--text TEXT | --text-file F)
                     [--out DIR] [--seed N]
                                      three previews of a voice made from a
                                      description, saved as LABEL-1.mp3..3 and
                                      LABEL.json (their generated_voice_ids)
    voices.py create GENERATED_ID --name NAME --description TEXT [--json]
                                      one preview kept as a voice on the
                                      account: its voice_id, for the voices entry
    voices.py delete VOICE_ID --name NAME
                                      a voice taken off the account, freeing its
                                      slot: only when its name is NAME exactly
                                      (read first), never a premade one

`account` only reads. `design` costs credits (ElevenLabs charges the
preview text's characters, once for the three previews), `create` takes a
voice slot, and `delete` cannot be undone: each is run on the captain's
word, never by an engineer's own choice.

The key (ELEVENLABS_API_KEY) is read from ~/.env in this process
(crew_tool.read_env), as steward.py and no1.py read their logins, and is
never printed: an engineer's tools may not read that file and need not.
Anything the service answers is scrubbed of it before it is shown.
$LCARS_ELEVENLABS_URL is the service (the server's own variable; the
tests' stand-in), https://api.elevenlabs.io by default.

The previews go to the research folder of whoever runs it
(~/.local/state/lcars-eng/research/<name>/voices: the engineer whose
worktree it runs from, or $LCARS_VOICES_WHO), or --out; never a checkout.

Exit status: 0 done, 1 the service refused or could not be reached, 2 a
usage error.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import crew_tool as T  # noqa: E402 - ~/.env, read and never printed

BASE = "https://api.elevenlabs.io"
KEY_NAME = "ELEVENLABS_API_KEY"
# ElevenLabs' own bounds for a design (its API reference, 2026): a
# description of 20 to 1000 characters, a preview text of 100 to 1000
DESC_MIN, DESC_MAX = 20, 1000
TEXT_MIN, TEXT_MAX = 100, 1000
DESIGN_MODEL = "eleven_multilingual_ttv_v2"
ENG_ROOT = os.environ.get("LCARS_ENG_ROOT") or os.path.join(os.path.expanduser("~"), "lcars-eng")
RESEARCH = os.path.join(os.path.expanduser("~"), ".local", "state", "lcars-eng", "research")
TIMEOUT = 120


class Refused(Exception):
    pass


def base_url():
    return (os.environ.get("LCARS_ELEVENLABS_URL") or BASE).rstrip("/")


def api_key():
    k = T.read_env().get(KEY_NAME, "")
    if not k:
        raise Refused(f"no {KEY_NAME} in ~/.env")
    return k


def scrub(text, key):
    return text.replace(key, "[key]") if key else text


def call(method, path, body=None, key=None):
    """One request, its JSON answer; a refusal as Refused with the service's
    status and the start of its message, the key scrubbed out."""
    key = key or api_key()
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method,
                                 headers={"xi-api-key": key, "Accept": "application/json",
                                          **({"Content-Type": "application/json"} if data else {})})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read()
    except urllib.error.HTTPError as e:
        msg = e.read()[:400].decode("utf-8", "replace")
        raise Refused(scrub(f"ElevenLabs answered HTTP {e.code}: {msg}", key)) from None
    except (urllib.error.URLError, OSError) as e:
        raise Refused(scrub(f"ElevenLabs unreachable: {e}", key)) from None
    try:
        return json.loads(raw)
    except ValueError:
        raise Refused("ElevenLabs answered something not JSON") from None


def account_summary(sub):
    """GET /v1/user/subscription, the fields that decide how many voices
    may be made. There is no field for voice design itself: every plan has
    it (ElevenLabs' pricing page); what limits it is the credits and the
    slots, so `design` says what it is and the slots say how many can be kept."""
    reset = sub.get("next_character_count_reset_unix")
    used, limit = sub.get("character_count"), sub.get("character_limit")
    return {
        "tier": sub.get("tier"),
        "status": sub.get("status"),
        "voice_slots_used": sub.get("voice_slots_used"),
        "voice_limit": sub.get("voice_limit"),
        "credits_used": used,
        "credits_limit": limit,
        "credits_left": (limit - used) if isinstance(used, int) and isinstance(limit, int) else None,
        "resets_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(reset)) if isinstance(reset, (int, float)) else None,
        "voice_edits": f"{sub.get('voice_add_edit_counter')}/{sub.get('max_voice_add_edits')}"
                       if sub.get("max_voice_add_edits") is not None else None,
        "instant_cloning": sub.get("can_use_instant_voice_cloning"),
        "design": "every plan (no field of its own): limited by credits and voice slots",
    }


def who():
    w = (os.environ.get("LCARS_VOICES_WHO") or "").strip()
    if w:
        return w
    rel = os.path.relpath(os.getcwd(), ENG_ROOT)
    return "" if rel.startswith("..") else rel.split(os.sep)[0]


def cmd_account(a):
    s = account_summary(call("GET", "/v1/user/subscription"))
    if a.json:
        print(json.dumps(s, indent=2))
        return 0
    for k, v in s.items():
        print(f"{k:17} {v}")
    return 0


def read_text(a):
    if a.text_file:
        with open(a.text_file) as f:
            return f.read().strip()
    return (a.text or "").strip()


def cmd_design(a):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,40}", a.label):
        return usage("LABEL is a file name: [a-z0-9_-], 41 at most")
    text = read_text(a)
    if not (DESC_MIN <= len(a.description) <= DESC_MAX):
        return usage(f"--description is {DESC_MIN} to {DESC_MAX} characters ({len(a.description)})")
    if not (TEXT_MIN <= len(text) <= TEXT_MAX):
        return usage(f"the preview text is {TEXT_MIN} to {TEXT_MAX} characters ({len(text)})")
    out = a.out
    if not out:
        w = who()
        if not w:
            return usage("not in an engineer's worktree: name --out, or $LCARS_VOICES_WHO")
        out = os.path.join(RESEARCH, w, "voices")
    os.makedirs(out, exist_ok=True)
    body = {"voice_description": a.description, "text": text, "model_id": DESIGN_MODEL}
    if a.seed is not None:
        body["seed"] = a.seed
    r = call("POST", "/v1/text-to-voice/design?output_format=mp3_44100_128", body)
    previews = r.get("previews") or []
    if not previews:
        raise Refused("ElevenLabs answered no previews")
    kept = []
    for i, p in enumerate(previews, 1):
        path = os.path.join(out, f"{a.label}-{i}.mp3")
        with open(path, "wb") as f:
            f.write(base64.b64decode(p.get("audio_base_64") or ""))
        kept.append({"file": path, "generated_voice_id": p.get("generated_voice_id"),
                     "duration_secs": p.get("duration_secs")})
    meta = {"label": a.label, "description": a.description, "text": text, "chars": len(text),
            "model_id": DESIGN_MODEL, "previews": kept}
    with open(os.path.join(out, a.label + ".json"), "w") as f:
        json.dump(meta, f, indent=2)
    print(f"{len(kept)} previews of {a.label} ({len(text)} characters charged) in {out}:")
    for k in kept:
        print(f"  {os.path.basename(k['file'])}  {k['generated_voice_id']}")
    return 0


def cmd_create(a):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", a.generated_id):
        return usage("GENERATED_ID is a preview's generated_voice_id")
    if not a.name.strip():
        return usage("--name is the voice's name on the account")
    if not (DESC_MIN <= len(a.description) <= DESC_MAX):
        return usage(f"--description is {DESC_MIN} to {DESC_MAX} characters ({len(a.description)})")
    r = call("POST", "/v1/text-to-voice", {"voice_name": a.name.strip(), "voice_description": a.description,
                                           "generated_voice_id": a.generated_id})
    vid = r.get("voice_id")
    if not vid:
        raise Refused("ElevenLabs answered no voice_id")
    print(json.dumps({"voice_id": vid, "name": r.get("name", a.name)}) if a.json
          else f"{a.name}: voice_id {vid}")
    return 0


def cmd_delete(a):
    if not re.fullmatch(r"[A-Za-z0-9_-]{4,128}", a.voice_id):
        return usage("VOICE_ID is a voice's id")
    # the name read back first: an id mistyped or copied from the wrong row
    # is refused here rather than deleting someone's other voice
    v = call("GET", "/v1/voices/" + a.voice_id)
    name, cat = v.get("name", ""), v.get("category", "")
    if name != a.name:
        raise Refused(f"voice {a.voice_id} is named {name!r}, not {a.name!r}: nothing deleted")
    if cat == "premade":
        raise Refused(f"{name!r} is a premade voice: it takes no slot, and is not ours to delete")
    call("DELETE", "/v1/voices/" + a.voice_id)
    print(f"deleted {name} ({cat}, {a.voice_id})")
    return 0


def usage(msg):
    print("voices.py: " + msg, file=sys.stderr)
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(prog="voices.py", description="The captain's ElevenLabs account, for the engineers' voices.")
    sp = ap.add_subparsers(dest="cmd", required=True)
    p = sp.add_parser("account", help="the plan, its slots and credits (reads only)")
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("design", help="three previews of a described voice (costs credits)")
    p.add_argument("label")
    p.add_argument("--description", required=True)
    p.add_argument("--text")
    p.add_argument("--text-file")
    p.add_argument("--out")
    p.add_argument("--seed", type=int)
    p = sp.add_parser("create", help="keep a preview as a voice (takes a slot)")
    p.add_argument("generated_id")
    p.add_argument("--name", required=True)
    p.add_argument("--description", required=True)
    p.add_argument("--json", action="store_true")
    p = sp.add_parser("delete", help="take a voice off the account (frees a slot; cannot be undone)")
    p.add_argument("voice_id")
    p.add_argument("--name", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "design" and bool(a.text) == bool(a.text_file):
        return usage("design takes --text or --text-file, one of them")
    try:
        return {"account": cmd_account, "design": cmd_design, "create": cmd_create,
                "delete": cmd_delete}[a.cmd](a)
    except Refused as e:
        print("voices.py: " + str(e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
