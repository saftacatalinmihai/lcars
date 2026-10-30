#!/usr/bin/env python3
"""Tests for scripts/deck-models/gen.py, the deck's generated road, against
a stand-in higgsfield ($LCARS_HIGGSFIELD, a script logging its argv and
keeping a balance) and a stand-in result host, on a scratch media root:
the plan priced and nothing spent without --spend, the cap refused before
any job, the views made in order with the earlier ones as references, the
3D job's slots front, left, back, right, the files downloaded, gen.json and
LICENSE.txt, a second run skipping what is done, a job created by a stopped run
fetched and not paid for again, --redo re-making a view
and what follows it, and the text road.

    python3 scripts/test_gen.py      # ~2s
"""

import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
GEN = os.path.join(HERE, "deck-models", "gen.py")

STAND = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["GEN_STATE"]
st = json.load(open(d)) if os.path.exists(d) else {"balance": 100.0, "jobs": {}, "log": []}
a = sys.argv[1:]
st["log"].append(a)
def price(model, args):
    if model.startswith("seedream"):
        return 0.5
    return 12 if "detailed" in args else (5 if model == "tripo_3d" else 9)
out = None
if a[:2] == ["account", "status"]:
    out = {"credits": st["balance"], "email": "x", "subscription_plan_type": "plus"}
elif a[:2] == ["generate", "cost"]:
    out = {"credits": price(a[2], a)}
elif a[:2] == ["generate", "create"]:
    jid = "job-%d" % len(st["jobs"])
    ext = "png" if a[2].startswith("seedream") else "glb"
    st["jobs"][jid] = {"model": a[2], "url": os.environ["GEN_HOST"] + "/" + jid + "." + ext}
    st["balance"] -= price(a[2], a)
    out = [jid]   # the CLI 1.2.2's answer: the new jobs' ids
elif a[:2] == ["generate", "wait"]:
    out = {}
elif a[:2] == ["generate", "get"]:
    j = st["jobs"][a[2]]
    out = {"id": a[2], "status": "completed", "result_url": j["url"], "job_type": j["model"]}
json.dump(st, open(d, "w"))
print(json.dumps(out))
'''

MULTI = """\
# a test prop
road: multiview
object: one test sofa
palette: taupe #8a6c58
front: straight from the front,
  level with the seat.
back: from behind.
left: its own left side.
right: its own right side.
params: face_limit=2400
"""


class Host(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = ("bytes of " + self.path).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class Gen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Host)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="gen-test-")
        self.addCleanup(shutil.rmtree, self.tmp)
        self.stand = os.path.join(self.tmp, "higgsfield")
        with open(self.stand, "w") as w:
            w.write(STAND)
        os.chmod(self.stand, 0o755)
        self.state = os.path.join(self.tmp, "hf.json")
        self.media = os.path.join(self.tmp, "media-root")
        self.raw = os.path.join(self.media, "media", "deck-models", "test_sofa", "raw")
        os.makedirs(self.raw)
        self.prompts(MULTI)

    def prompts(self, text):
        with open(os.path.join(self.raw, "prompts.txt"), "w") as w:
            w.write(textwrap.dedent(text))

    def gen(self, *args, prop="test_sofa"):
        env = dict(os.environ, LCARS_HIGGSFIELD=self.stand, GEN_STATE=self.state,
                   GEN_HOST=f"http://127.0.0.1:{self.srv.server_address[1]}")
        env.pop("LCARS_MEDIA_ROOT", None)
        return subprocess.run([sys.executable, GEN, prop, "--media", self.media, *args],
                              capture_output=True, text=True, env=env, timeout=60)

    def hf(self):
        return json.load(open(self.state))

    def creates(self):
        return [a for a in self.hf()["log"] if a[:2] == ["generate", "create"]]

    def test_plan_spends_nothing(self):
        r = self.gen()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("total 11 credits; the balance 100", r.stdout)
        self.assertIn("stopped: nothing spent", r.stdout)
        self.assertEqual(self.creates(), [])
        self.assertEqual(self.hf()["balance"], 100)
        costs = [a for a in self.hf()["log"] if a[:2] == ["generate", "cost"]]
        self.assertEqual(len(costs), 5)
        # the continued line joined, the lead and the palette in each view's prompt
        front = costs[0][costs[0].index("--prompt") + 1]
        self.assertIn("one test sofa alone", front)
        self.assertIn("straight from the front, level with the seat.", front)
        self.assertIn("Colours: taupe #8a6c58.", front)
        self.assertIn("2400", costs[-1])

    def test_cap_refused_before_any_job(self):
        r = self.gen("--spend", "10")
        self.assertEqual(r.returncode, 2)
        self.assertIn("over --spend 10", r.stderr)
        self.assertEqual(self.creates(), [])

    def test_run_skip_and_redo(self):
        r = self.gen("--spend", "11")
        self.assertEqual(r.returncode, 0, r.stderr)
        made = self.creates()
        self.assertEqual([a[2] for a in made], ["seedream_5_0_flash"] * 4 + ["tripo_h3_1_multiview_to_3d"])
        refs = [[a[i + 1] for i, x in enumerate(a) if x == "--image-references"] for a in made]
        base = [os.path.basename(f) for f in refs[2]]
        self.assertEqual(refs[0], [])
        self.assertEqual([os.path.basename(f) for f in refs[1]], ["front.png"])
        self.assertEqual(base, ["front.png", "back.png"])
        self.assertEqual([os.path.basename(f) for f in refs[4]], ["front.png", "left.png", "back.png", "right.png"])
        for f in ("front.png", "back.png", "left.png", "right.png", "raw.glb"):
            self.assertTrue(open(os.path.join(self.raw, f)).read().startswith("bytes of /job-"), f)
        st = json.load(open(os.path.join(self.raw, "gen.json")))
        self.assertEqual(st["spent"], 11)
        self.assertEqual(st["done"]["3d"]["credits"], 9)
        lic = open(os.path.join(self.raw, "..", "LICENSE.txt")).read()
        self.assertIn("test_sofa: generated with Higgsfield (Tripo H3.1 multiview", lic)
        # again: everything done, nothing made
        r = self.gen("--spend", "11")
        self.assertIn("nothing to make", r.stdout)
        self.assertEqual(len(self.creates()), 5)
        # a side re-rolled: it and every step after it, not the views before
        r = self.gen("--redo", "left")
        self.assertIn("total 10 credits", r.stdout)
        r = self.gen("--spend", "10", "--redo", "left")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([a[2] for a in self.creates()[5:]],
                         ["seedream_5_0_flash", "seedream_5_0_flash", "tripo_h3_1_multiview_to_3d"])  # left, right, 3d
        self.assertEqual(json.load(open(os.path.join(self.raw, "gen.json")))["spent"], 21)

    def test_pending_job_fetched_not_paid_again(self):
        # a run stopped after create: the job is in gen.json's pending
        self.prompts("road: text\nprompt: a potted fern\n")
        self.gen("--spend", "5")
        st = json.load(open(os.path.join(self.raw, "gen.json")))
        rec = st["done"].pop("3d")
        st["pending"] = {"3d": {"id": rec["id"], "model": "tripo_3d", "price": 5, "balance_before": 100}}
        json.dump(st, open(os.path.join(self.raw, "gen.json"), "w"))
        os.remove(os.path.join(self.raw, "raw.glb"))
        r = self.gen("--spend", "0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already made (5), its result fetched", r.stdout)
        self.assertEqual(len(self.creates()), 1)
        self.assertTrue(os.path.exists(os.path.join(self.raw, "raw.glb")))
        st = json.load(open(os.path.join(self.raw, "gen.json")))
        self.assertEqual(st["pending"], {})
        self.assertEqual(st["done"]["3d"]["credits"], 5)

    def test_text_road_and_refusals(self):
        self.prompts("road: text\nprompt: a potted fern\nparams: face_limit=1200 texture_quality=detailed\n")
        r = self.gen()
        self.assertIn("total 12 credits", r.stdout)
        r = self.gen("--spend", "12")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual([a[2] for a in self.creates()], ["tripo_3d"])
        self.prompts("road: multiview\nobject: x\npalette: y\nfront: z\n")
        r = self.gen()
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs a back: view", r.stderr)
        r = self.gen(prop="../etc")
        self.assertEqual(r.returncode, 2)
        self.assertIn("a slug", r.stderr)


if __name__ == "__main__":
    unittest.main()
