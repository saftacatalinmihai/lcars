#!/usr/bin/env python3
"""Tests for scripts/voices.py, the captain's ElevenLabs account for the
engineers' voices: account, design and create against a stand-in
ElevenLabs ($LCARS_ELEVENLABS_URL), each run as its own process with a
scratch ~/.env ($LCARS_CREW_ENV) - what is asked, what is saved where, the
refusals before a request, and nothing of the key in any output, a
refusal that quotes it included.

    python3 scripts/test_voices.py      # ~2s
"""

import base64
import http.server
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest

sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
KEY = "sk_test_9f8e7d6c5b4a"
DESC = "A man in his forties, a thick Dublin accent, warm and dry, steady pacing, studio quality."
TEXT = ("Transporter room three, the pattern buffers are holding at ninety-eight percent. "
        "I'd not put the Captain through it, mind, not till I've had a look at the coils myself.")


class Stand(http.server.BaseHTTPRequestHandler):
    seen = []
    answer = {}   # path -> (status, body)

    def _do(self, method):
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(n)) if n else None
        Stand.seen.append({"method": method, "path": self.path, "key": self.headers.get("xi-api-key"), "body": body})
        path = self.path.split("?")[0]
        vid = path[len("/v1/voices/"):] if path.startswith("/v1/voices/") else None
        if vid is not None:
            v = Stand.voices.get(vid)
            st, out = (404, {"detail": "voice_not_found"}) if not v else (200, v)
            if v and method == "DELETE":
                del Stand.voices[vid]
                out = {"status": "ok"}
        else:
            st, out = Stand.answer.get(path, (404, {"detail": "no such route"}))
        raw = json.dumps(out).encode()
        self.send_response(st)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        self._do("GET")

    def do_POST(self):
        self._do("POST")

    def do_DELETE(self):
        self._do("DELETE")

    def log_message(self, *a):
        pass


SUB = {"tier": "free", "status": "free", "character_count": 4210, "character_limit": 10000,
       "voice_slots_used": 1, "voice_limit": 3, "next_character_count_reset_unix": 1793404800,
       "voice_add_edit_counter": 2, "max_voice_add_edits": 25, "can_use_instant_voice_cloning": False}
PREVIEWS = {"previews": [{"audio_base_64": base64.b64encode(b"ID3audio-%d" % i).decode(),
                          "generated_voice_id": "gen%d_abcdef" % i, "duration_secs": 9.5} for i in (1, 2, 3)],
            "text": TEXT}


class Voices(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Stand)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="voices-test-")
        self.envf = os.path.join(self.tmp, "env")
        with open(self.envf, "w") as f:
            f.write(f"OTHER=1\nexport {'ELEVENLABS_API_KEY'}=\"{KEY}\"\n")
        Stand.seen.clear()
        Stand.answer = {"/v1/user/subscription": (200, SUB), "/v1/text-to-voice/design": (200, PREVIEWS),
                        "/v1/text-to-voice": (200, {"voice_id": "VoiceObrien01", "name": "O'Brien"})}
        Stand.voices = {"OldVoice0001": {"voice_id": "OldVoice0001", "name": "Narator", "category": "generated"},
                        "Premade00001": {"voice_id": "Premade00001", "name": "Eric", "category": "premade"}}

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_(self, *args, env=None):
        e = dict(os.environ, LCARS_CREW_ENV=self.envf,
                 LCARS_ELEVENLABS_URL=f"http://127.0.0.1:{self.srv.server_address[1]}")
        e.pop("LCARS_VOICES_WHO", None)
        e.update(env or {})
        p = subprocess.run([sys.executable, os.path.join(HERE, "voices.py"), *args], env=e, cwd=self.tmp,
                           capture_output=True, text=True, timeout=30)
        self.assertNotIn(KEY, p.stdout + p.stderr, "the key in the output")
        return p

    def test_account(self):
        p = self.run_("account", "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        s = json.loads(p.stdout)
        self.assertEqual((s["tier"], s["voice_slots_used"], s["voice_limit"]), ("free", 1, 3))
        self.assertEqual((s["credits_used"], s["credits_limit"], s["credits_left"]), (4210, 10000, 5790))
        self.assertEqual(s["resets_at"], "2026-10-31 00:00 UTC")
        self.assertEqual(s["voice_edits"], "2/25")
        self.assertIn("every plan", s["design"])
        self.assertEqual(Stand.seen, [{"method": "GET", "path": "/v1/user/subscription", "key": KEY, "body": None}])
        p = self.run_("account")
        self.assertIn("voice_limit       3", p.stdout)

    def test_design(self):
        out = os.path.join(self.tmp, "out")
        p = self.run_("design", "obrien", "--description", DESC, "--text", TEXT, "--out", out, "--seed", "7")
        self.assertEqual(p.returncode, 0, p.stderr)
        s = Stand.seen[0]
        self.assertEqual((s["path"], s["key"]), ("/v1/text-to-voice/design?output_format=mp3_44100_128", KEY))
        self.assertEqual(s["body"], {"voice_description": DESC, "text": TEXT,
                                     "model_id": "eleven_multilingual_ttv_v2", "seed": 7})
        for i in (1, 2, 3):
            with open(os.path.join(out, f"obrien-{i}.mp3"), "rb") as f:
                self.assertEqual(f.read(), b"ID3audio-%d" % i)
        with open(os.path.join(out, "obrien.json")) as f:
            meta = json.load(f)
        self.assertEqual([x["generated_voice_id"] for x in meta["previews"]], ["gen1_abcdef", "gen2_abcdef", "gen3_abcdef"])
        self.assertEqual(meta["chars"], len(TEXT))
        self.assertIn(f"({len(TEXT)} characters charged)", p.stdout)

    def test_design_where(self):
        # a text file, and the research folder of $LCARS_VOICES_WHO under a scratch HOME
        tf = os.path.join(self.tmp, "line.txt")
        with open(tf, "w") as f:
            f.write(TEXT + "\n")
        home = os.path.join(self.tmp, "home")
        p = self.run_("design", "kim", "--description", DESC, "--text-file", tf,
                      env={"HOME": home, "LCARS_VOICES_WHO": "data-lqj"})
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertTrue(os.path.exists(os.path.join(home, ".local/state/lcars-eng/research/data-lqj/voices/kim-3.mp3")))
        # nobody's: refused, nothing asked
        Stand.seen.clear()
        p = self.run_("design", "kim", "--description", DESC, "--text", TEXT, env={"HOME": home})
        self.assertEqual(p.returncode, 2)
        self.assertEqual(Stand.seen, [])

    def test_refusals_before_a_request(self):
        out = os.path.join(self.tmp, "out")
        for args in (("design", "obrien", "--description", "short", "--text", TEXT, "--out", out),
                     ("design", "obrien", "--description", DESC, "--text", "too short", "--out", out),
                     ("design", "obrien", "--description", DESC, "--text", "x" * 1001, "--out", out),
                     ("design", "../up", "--description", DESC, "--text", TEXT, "--out", out),
                     ("design", "obrien", "--description", DESC, "--out", out),
                     ("create", "bad id!", "--name", "O'Brien", "--description", DESC),
                     ("create", "gen1_abcdef", "--name", " ", "--description", DESC)):
            p = self.run_(*args)
            self.assertEqual(p.returncode, 2, args)
        self.assertEqual(Stand.seen, [])
        self.assertFalse(os.path.exists(out))

    def test_create(self):
        p = self.run_("create", "gen2_abcdef", "--name", "O'Brien", "--description", DESC, "--json")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)["voice_id"], "VoiceObrien01")
        self.assertEqual(Stand.seen[0]["path"], "/v1/text-to-voice")
        self.assertEqual(Stand.seen[0]["body"], {"voice_name": "O'Brien", "voice_description": DESC,
                                                 "generated_voice_id": "gen2_abcdef"})

    def test_delete(self):
        # the name read back first; a wrong one, a premade one, an unknown id: nothing deleted
        for args, why in ((("OldVoice0001", "--name", "Ro FE"), "not 'Ro FE'"),
                          (("Premade00001", "--name", "Eric"), "premade"),
                          (("NoSuchVoice1", "--name", "Narator"), "HTTP 404")):
            Stand.seen.clear()
            p = self.run_("delete", *args)
            self.assertEqual(p.returncode, 1, args)
            self.assertIn(why, p.stderr)
            self.assertEqual([x["method"] for x in Stand.seen], ["GET"])
        self.assertEqual(self.run_("delete", "bad id!", "--name", "x").returncode, 2)
        Stand.seen.clear()
        p = self.run_("delete", "OldVoice0001", "--name", "Narator")
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual([(x["method"], x["path"]) for x in Stand.seen],
                         [("GET", "/v1/voices/OldVoice0001"), ("DELETE", "/v1/voices/OldVoice0001")])
        self.assertNotIn("OldVoice0001", Stand.voices)
        self.assertIn("deleted Narator", p.stdout)

    def test_service_refusing(self):
        # a refusal quoting the key back: shown, the key scrubbed (run_ checks)
        Stand.answer["/v1/text-to-voice"] = (400, {"detail": {"status": "voice_limit_reached",
                                                              "message": "key " + KEY + " has no free slot"}})
        p = self.run_("create", "gen2_abcdef", "--name", "O'Brien", "--description", DESC)
        self.assertEqual(p.returncode, 1)
        self.assertIn("HTTP 400", p.stderr)
        self.assertIn("voice_limit_reached", p.stderr)
        self.assertIn("[key]", p.stderr)
        # no key at all
        with open(self.envf, "w") as f:
            f.write("OTHER=1\n")
        Stand.seen.clear()
        p = self.run_("account")
        self.assertEqual(p.returncode, 1)
        self.assertIn("no ELEVENLABS_API_KEY", p.stderr)
        self.assertEqual(Stand.seen, [])
        # nobody answering
        with open(self.envf, "w") as f:
            f.write(f"ELEVENLABS_API_KEY={KEY}\n")
        p = self.run_("account", env={"LCARS_ELEVENLABS_URL": "http://127.0.0.1:9"})
        self.assertEqual(p.returncode, 1)
        self.assertIn("unreachable", p.stderr)


if __name__ == "__main__":
    unittest.main()
