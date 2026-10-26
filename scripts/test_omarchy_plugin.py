#!/usr/bin/env python3
"""The omarchy plugin (omarchy/, docs/design/omarchy-plugin.md) on a box
with no omarchy and no Quickshell: what can be checked here.

- omarchy's own validator (scripts/testdata/omarchy/, pinned: its README
  says from where and how to refresh it), bash and jq; where jq is missing,
  `validate_like`, the same checks in Python, and the run says so. Both
  are also shown a broken plugin of each kind and must refuse it.
- the marketplace's rules the validator does not hold (SUBMISSION.md of
  omacom/omarchy-plugin-marketplace): author, license, description, a
  version of at most 64 characters, README and LICENSE at the root, the
  README naming install and removal, a preview under 40 MP and 50 MB.
- Model.js in node: the env file, the address, the window class, the poll,
  the state.
- BarWidget.qml: qmllint when there is one (`qmllint`, `qmllint6`,
  `pyside6-qmllint`), only its syntax errors counted (Quickshell's and
  omarchy's modules are not here); else a said skip, and a bracket check.
- scripts/omarchy-publish.sh on scratch repos: the refusals, the dry run
  pushing nothing, a push, nothing to publish, an unbumped change refused,
  a bump fast-forwarding.

    python3 scripts/test_omarchy_plugin.py [-q]

OMARCHY_PLUGIN_DIR=DIR checks that plugin instead and skips the publish
tests (omarchy-publish.sh runs it so); OMARCHY_REQUIRE_BIN=1 fails when its
bin/ lacks the installer or the theme hook.
"""

import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
PLUGIN = pathlib.Path(os.environ.get("OMARCHY_PLUGIN_DIR") or ROOT / "omarchy").resolve()
VALIDATOR = HERE / "testdata" / "omarchy" / "omarchy-plugin-validate"
PUBLISH = HERE / "omarchy-publish.sh"
JQ = shutil.which("jq")

# The kinds omarchy knows and the entry point each one loads (the
# validator's table).
KINDS = {"bar": "bar", "bar-widget": "barWidget", "menu": "menu",
         "overlay": "overlay", "panel": "panel", "service": "service"}
SECTIONS = ["left", "centerBegin", "center", "centerEnd", "tray", "right"]
# the marketplace's (SUBMISSION.md): exactly one category, one to three tags
CATEGORIES = ["Appearance", "Desktop", "Developer Tools", "Hardware", "Kids",
              "Productivity", "System", "Widgets", "Other"]
SCHEMA_TYPES = {"string", "integer", "boolean", "enum", "path"}
# The two scripts the plugin carries. O'Brien moves them into omarchy/bin/
# (with links left in scripts/omarchy/) on his own branch; until that lands
# their absence is allowed here, and omarchy-publish.sh, which must not
# publish a plugin without its installer, requires them.
BIN = ["lcars-webapp", "lcars-theme-set"]


def validate_like(d):
    """bin/omarchy-plugin-validate's checks, in Python, for a box with no
    jq: the reason a plugin is refused, or None. Keep in step with the
    pinned copy."""
    d = pathlib.Path(d)
    m = d / "manifest.json"
    if not m.is_file():
        return "missing manifest.json"
    try:
        j = json.loads(m.read_text())
    except ValueError:
        return "manifest.json is not valid JSON"
    if not isinstance(j, dict) or j.get("schemaVersion") != 1 or isinstance(j.get("schemaVersion"), bool):
        return "unsupported or missing schemaVersion"
    for f in ("id", "name", "version", "kinds", "entryPoints"):
        if f not in j:
            return f"manifest missing required field '{f}'"
    pid = j["id"] if isinstance(j["id"], str) else ""
    if not pid:
        return "manifest 'id' is empty"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", pid) or ".." in pid:
        return f"invalid plugin id '{pid}'"
    if pid.startswith("omarchy."):
        return "reserved omarchy.* namespace"
    if not isinstance(j["kinds"], list) or not j["kinds"]:
        return "'kinds' must be a non-empty array"
    if not isinstance(j["entryPoints"], dict):
        return "'entryPoints' must be an object"
    bw = j.get("barWidget")
    if isinstance(bw, dict) and "defaultSection" in bw and bw["defaultSection"] not in SECTIONS:
        return "bad barWidget.defaultSection"
    for ep in j["entryPoints"].values():
        ep = ep if isinstance(ep, str) else json.dumps(ep)
        if not ep or "\n" in ep or ep.startswith("/") or ".." in ep or not (d / ep).is_file():
            return f"bad entry point '{ep}'"
    for kind, key in KINDS.items():
        if kind in j["kinds"] and key not in j["entryPoints"]:
            return f"kind '{kind}' requires an 'entryPoints.{key}'"
    for p in d.rglob("*"):
        if ".git" in p.relative_to(d).parts:
            continue
        if p.is_symlink():
            return f"symlinks are not allowed: {p}"
    return None


def validate(d):
    """(ok, how): the pinned validator when jq is here, else validate_like."""
    if JQ:
        r = subprocess.run(["bash", str(VALIDATOR), str(d)], capture_output=True, text=True)
        return r.returncode == 0, "omarchy-plugin-validate: " + (r.stderr.strip() or "ok")
    why = validate_like(d)
    return why is None, "validate_like: " + (why or "ok")


def png_size(p):
    b = p.read_bytes()[:24]
    if b[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return struct.unpack(">II", b[16:24])


def manifest():
    return json.loads((PLUGIN / "manifest.json").read_text())


class Validator(unittest.TestCase):
    def test_plugin_valid(self):
        ok, how = validate(PLUGIN)
        if not JQ:
            print("\n  (no jq here: omarchy's validator not run, validate_like instead)", file=sys.stderr)
        self.assertTrue(ok, how)

    def test_broken_refused(self):
        def broken(change):
            t = pathlib.Path(tempfile.mkdtemp(prefix="lcars-omarchy-"))
            self.addCleanup(shutil.rmtree, t, True)
            d = t / "p"
            shutil.copytree(PLUGIN, d, symlinks=True, ignore=shutil.ignore_patterns(".git"))
            j = json.loads((d / "manifest.json").read_text())
            change(d, j)
            (d / "manifest.json").write_text(json.dumps(j))
            return d

        cases = {
            "reserved id": lambda d, j: j.update(id="omarchy.lcars"),
            "bad id": lambda d, j: j.update(id="../lcars"),
            "string schemaVersion": lambda d, j: j.update(schemaVersion="1"),
            "no version": lambda d, j: j.pop("version"),
            "missing entry point": lambda d, j: (d / "BarWidget.qml").unlink(),
            "kind without entry point": lambda d, j: j["kinds"].append("panel"),
            "bad section": lambda d, j: j["barWidget"].update(defaultSection="middle"),
            "symlink": lambda d, j: (d / "link.qml").symlink_to(d / "BarWidget.qml"),
        }
        for name, change in cases.items():
            with self.subTest(name):
                d = broken(change)
                self.assertIsNotNone(validate_like(d), name)
                if JQ:
                    ok, how = validate(d)
                    self.assertFalse(ok, f"{name}: the pinned validator passed it")


class Marketplace(unittest.TestCase):
    def test_fields(self):
        j = manifest()
        for f in ("author", "license", "description"):
            self.assertTrue(isinstance(j.get(f), str) and j[f].strip(), f"no {f}")
        self.assertEqual(j["license"], "MIT")
        self.assertEqual(j["id"], "dev.mihai-safta.lcars")
        self.assertRegex(j["version"], r"^\d+\.\d+\.\d+$")
        self.assertLessEqual(len(j["version"]), 64)

    def test_bar_widget(self):
        j = manifest()
        self.assertEqual(j["kinds"], ["bar-widget"])
        bw = j["barWidget"]
        self.assertEqual(bw["displayName"], "LCARS")
        self.assertIn(bw["category"], CATEGORIES)
        self.assertIs(bw["allowMultiple"], False)
        self.assertEqual(bw["defaultSection"], "right")
        keys = [s["key"] for s in bw["schema"]]
        self.assertEqual(sorted(keys), sorted(bw["defaults"]), "schema and defaults name the same keys")
        for s in bw["schema"]:
            self.assertIn(s["type"], SCHEMA_TYPES)
            self.assertEqual(s.get("defaultValue"), bw["defaults"][s["key"]], s["key"])
        self.assertEqual(bw["defaults"], {"url": "", "pollSec": 60})

    def test_files(self):
        readme = (PLUGIN / "README.md").read_text()
        for must in ("omarchy plugin add", "omarchy plugin remove", "--uninstall",
                     "bin/lcars-webapp", "bin/lcars-theme-set", "## Testing",
                     "omarchy-menu.jsonc", "dev.mihai-safta.lcars"):
            self.assertIn(must, readme)
        lic = (PLUGIN / "LICENSE").read_text()
        self.assertIn("MIT License", lic)
        root_lic = PLUGIN.parent / "LICENSE"
        if root_lic.is_file():
            self.assertEqual(lic, root_lic.read_text(), "omarchy/LICENSE is the repo's")
        self.assertEqual(png_size(PLUGIN / "icon.png"), (256, 256))
        for p in PLUGIN.glob("preview.*"):
            self.assertIn(p.suffix, (".png", ".jpg", ".jpeg", ".webp", ".avif"))
            self.assertLess(p.stat().st_size, 50 * 1024 * 1024)
            size = png_size(p)
            if size:
                self.assertLessEqual(size[0] * size[1], 40_000_000)

    def test_bin(self):
        bindir = PLUGIN / "bin"
        if not bindir.exists():
            if os.environ.get("OMARCHY_REQUIRE_BIN") == "1":
                self.fail("omarchy/bin/ is missing: the installer and the theme hook")
            self.skipTest("omarchy/bin/ not here yet (O'Brien's branch moves the scripts in)")
        for name in BIN:
            p = bindir / name
            self.assertTrue(p.is_file() and not p.is_symlink(), f"bin/{name}: a real file")
            self.assertTrue(os.access(p, os.X_OK), f"bin/{name}: executable")


NODE_HARNESS = r"""
const fs = require('fs'), vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^\.pragma library\s*$/m, '');
const ctx = {}; vm.createContext(ctx); vm.runInContext(src, ctx);
const calls = JSON.parse(fs.readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(calls.map(([f, args]) => ctx[f](...args))));
"""


@unittest.skipUnless(shutil.which("node"), "no node here")
class ModelJs(unittest.TestCase):
    def run_js(self, calls):
        r = subprocess.run(["node", "-e", NODE_HARNESS, str(PLUGIN / "Model.js")],
                           input=json.dumps(calls), capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def check(self, cases):
        got = self.run_js([[f, a] for f, a, _ in cases])
        for (f, a, want), g in zip(cases, got):
            self.assertEqual(g, want, f"{f}{tuple(a)}")

    def test_env(self):
        env = ("# the theme hook's and lcars-cli's\n"
               "export LCARS_URL=\"https://box.example.ts.net\"\n"
               "LCARS_AUTH_USER=me  # a comment\n"
               "LCARS_AUTH_PASS='p#ss word'\n"
               "not a line\n\n")
        self.check([
            ("parseEnv", [env], {"LCARS_URL": "https://box.example.ts.net",
                                 "LCARS_AUTH_USER": "me", "LCARS_AUTH_PASS": "p#ss word"}),
            ("parseEnv", [""], {}),
            ("parseEnv", ["LCARS_URL=\r\n"], {"LCARS_URL": ""}),
            ("effectiveBase", ["", env], "https://box.example.ts.net"),
            ("effectiveBase", ["http://localhost:8080/ui/", env], "http://localhost:8080"),
            ("effectiveBase", ["javascript:alert(1)", env], "https://box.example.ts.net"),
            ("effectiveBase", ["", "LCARS_URL=\n"], ""),
            ("effectiveBase", ["", ""], ""),
        ])

    def test_address(self):
        self.check([
            ("normalizeBase", ["http://127.0.0.1:8080"], "http://127.0.0.1:8080"),
            ("normalizeBase", ["HTTPS://Box.Example/"], "https://box.example"),
            ("normalizeBase", ["https://box.example/ui/"], "https://box.example"),
            ("normalizeBase", ["https://box.example/lcars/ui"], "https://box.example/lcars"),
            ("normalizeBase", ["localhost:8080"], "http://localhost:8080"),
            ("normalizeBase", ["http://[::1]:8080/"], "http://[::1]:8080"),
            # refused: not http(s), a login in it, what a shell would read
            ("normalizeBase", ["file:///etc/passwd"], ""),
            ("normalizeBase", ["ftp://box"], ""),
            ("normalizeBase", ["https://me:pw@box"], ""),
            ("normalizeBase", ["https://box/a b"], ""),
            ("normalizeBase", ["https://box/$(reboot)"], ""),
            ("normalizeBase", ["https://box;reboot"], ""),
            ("normalizeBase", ["https://box/x?y=1"], ""),
            ("normalizeBase", ["https://box/'x'"], ""),
            ("normalizeBase", ["   "], ""),
            ("consoleUrl", ["https://box"], "https://box/ui/"),
            ("captureUrl", ["https://box"], "https://box/ui/?capture=1"),
            ("healthUrl", ["https://box"], "https://box/health"),
            ("consoleUrl", [""], ""),
            ("hostOf", ["http://127.0.0.1:8080/x"], "127.0.0.1:8080"),
        ])

    def test_window_class(self):
        # what omarchy-webapp-window-class prints for these
        self.check([
            ("windowClass", ["https://box.example.ts.net/ui/"], "chrome-box.example.ts.net__ui_-Default"),
            ("windowClass", ["http://127.0.0.1:8080/ui/"], "chrome-127.0.0.1__ui_-Default"),
            ("windowClass", ["https://Box/ui/?capture=1"], "chrome-box__ui_-Default"),
            ("windowClass", ["https://box"], "chrome-box__-Default"),
        ])

    def test_state(self):
        self.check([
            ("pollMs", [60], 60000), ("pollMs", ["30"], 30000), ("pollMs", [1], 15000),
            ("pollMs", [99999], 3600000), ("pollMs", [None], 60000), ("pollMs", ["x"], 60000),
            ("state", ["", "up"], "unset"), ("state", ["https://b", "unknown"], "checking"),
            ("state", ["https://b", "up"], "up"), ("state", ["https://b", "down"], "down"),
            ("healthOf", [200], "up"), ("healthOf", [0], "down"), ("healthOf", [401], "down"),
            ("healthOf", [503], "down"),
            ("tooltip", ["unset", ""], "LCARS: not set up - click to set up"),
            ("tooltip", ["down", "https://b:1"], "LCARS: no answer from b:1"),
            ("tooltip", ["up", "https://b"], "LCARS: b"),
            ("localPath", ["file:///opt/a%20b/x"], "/opt/a b/x"),
            ("shellQuote", ["/a/it's"], "'/a/it'\\''s'"),
        ])


def strip_qml(text):
    """The QML's code with strings and comments blanked, for the bracket
    check."""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith("//", i):
            j = text.find("\n", i)
            i = n if j < 0 else j
        elif text.startswith("/*", i):
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
        elif c in "\"'`":
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == "\\" else 1
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out)


class Qml(unittest.TestCase):
    QML = PLUGIN / "BarWidget.qml"

    def test_brackets(self):
        stack, pairs = [], {")": "(", "]": "[", "}": "{"}
        for c in strip_qml(self.QML.read_text()):
            if c in "([{":
                stack.append(c)
            elif c in pairs:
                self.assertTrue(stack and stack.pop() == pairs[c], f"unbalanced {c}")
        self.assertEqual(stack, [], "unclosed brackets")

    def test_imports(self):
        imports = re.findall(r"^import\s+(\S+)", self.QML.read_text(), re.M)
        self.assertEqual(sorted(set(imports)), sorted(
            ['"Model.js"', "QtQuick", "Quickshell", "Quickshell.Io", "qs.Commons", "qs.Ui"]))
        # the id the QML names itself by is the manifest's
        self.assertIn(f'moduleName: "{manifest()["id"]}"', self.QML.read_text())

    def test_qmllint(self):
        lint = next((shutil.which(t) for t in ("qmllint", "qmllint6", "pyside6-qmllint")
                     if shutil.which(t)), None)
        if not lint:
            self.skipTest("no qmllint here (qt6-declarative-dev-tools, or PySide6's pyside6-qmllint)")
        r = subprocess.run([lint, str(self.QML)], capture_output=True, text=True)
        out = r.stdout + r.stderr
        # without Quickshell's and omarchy's modules every qs.* type is
        # unresolved: only a syntax error is the file's own
        bad = [l for l in out.splitlines() if re.search(r"syntax error|Expected token|Unexpected token", l, re.I)]
        self.assertEqual(bad, [], out)


def git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True,
                          text=True, env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}).stdout.strip()


@unittest.skipIf(os.environ.get("OMARCHY_PLUGIN_DIR"), "checking a plugin only (omarchy-publish.sh's run)")
class Publish(unittest.TestCase):
    """omarchy-publish.sh against a scratch public checkout and a scratch
    bare remote: nothing leaves the box."""

    def setUp(self):
        self.t = pathlib.Path(tempfile.mkdtemp(prefix="lcars-omarchy-"))
        self.addCleanup(shutil.rmtree, self.t, True)
        self.src = self.t / "public"
        (self.src / "scripts" / "testdata").mkdir(parents=True)
        shutil.copytree(PLUGIN, self.src / "omarchy", ignore=shutil.ignore_patterns(".git", "bin"))
        shutil.copy(ROOT / "LICENSE", self.src / "LICENSE")
        shutil.copy(HERE / "test_omarchy_plugin.py", self.src / "scripts")
        shutil.copytree(HERE / "testdata" / "omarchy", self.src / "scripts" / "testdata" / "omarchy")
        (self.src / "omarchy" / "bin").mkdir()
        for name in BIN:  # stand-ins: the scripts themselves are O'Brien's
            p = self.src / "omarchy" / "bin" / name
            p.write_text("#!/bin/sh\nexit 0\n")
            p.chmod(0o755)
        git(self.t, "init", "-q", "-b", "main", str(self.src))
        git(self.src, "add", "-A")
        git(self.src, "commit", "-q", "-m", "Release 1")
        self.remote = self.t / "remote.git"
        git(self.t, "init", "-q", "--bare", str(self.remote))

    def publish(self, *args):
        return subprocess.run(["bash", str(PUBLISH), "--src", str(self.src), "--remote", str(self.remote), *args],
                              capture_output=True, text=True)

    def remote_main(self):
        r = subprocess.run(["git", "-C", str(self.remote), "rev-parse", "--verify", "-q", "main"],
                           capture_output=True, text=True)
        return r.stdout.strip()

    def bump(self, version, change=True):
        m = self.src / "omarchy" / "manifest.json"
        j = json.loads(m.read_text())
        j["version"] = version
        m.write_text(json.dumps(j, indent=2) + "\n")
        if change:
            with open(self.src / "omarchy" / "README.md", "a") as f:
                f.write(f"\n{version}\n")
        git(self.src, "commit", "-qam", f"plugin {version}")

    def test_refusals(self):
        r = subprocess.run(["bash", str(PUBLISH)], capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--src", r.stderr)
        (self.src / "CLAUDE.local.md").write_text("x")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-qm", "private")
        r = self.publish()
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("private checkout", r.stderr)
        git(self.src, "rm", "-q", "CLAUDE.local.md")
        git(self.src, "commit", "-qm", "public again")
        (self.src / "dirty").write_text("x")
        r = self.publish("--push")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("uncommitted", r.stderr)
        self.assertEqual(self.remote_main(), "")

    def test_bin_required(self):
        git(self.src, "rm", "-rq", "omarchy/bin")
        git(self.src, "commit", "-qm", "no bin")
        r = self.publish("--push")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("checks failed", r.stderr)
        self.assertEqual(self.remote_main(), "")

    def test_round(self):
        r = self.publish()  # the default is a dry run
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run: would push", r.stdout)
        self.assertEqual(self.remote_main(), "")

        r = self.publish("--push")
        self.assertEqual(r.returncode, 0, r.stderr)
        first = self.remote_main()
        self.assertTrue(first)
        # the plugin at the published repo's root, its bin/ real files
        ls = git(self.remote, "ls-tree", "--name-only", "main").split()
        self.assertIn("manifest.json", ls)
        self.assertIn("BarWidget.qml", ls)
        self.assertNotIn("omarchy", ls)
        self.assertIn("100755", git(self.remote, "ls-tree", "main", "bin/lcars-webapp"))
        self.assertEqual(git(self.remote, "rev-parse", "v0.1.0"), first)

        r = self.publish("--push")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing to publish", r.stdout)

        # a change outside omarchy/ is not a plugin change
        (self.src / "other").write_text("x")
        git(self.src, "add", "-A")
        git(self.src, "commit", "-qm", "elsewhere")
        r = self.publish("--push")
        self.assertIn("nothing to publish", r.stdout)

        self.bump("0.1.0")  # changed, not bumped
        r = self.publish("--push")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("did not go up", r.stderr)
        self.assertEqual(self.remote_main(), first)

        self.bump("0.0.9", change=False)  # down is refused too
        r = self.publish()
        self.assertNotEqual(r.returncode, 0)

        self.bump("0.1.1", change=False)
        r = self.publish("--push")
        self.assertEqual(r.returncode, 0, r.stderr)
        second = self.remote_main()
        self.assertNotEqual(second, first)
        # a fast-forward: what `omarchy plugin update` pulls
        git(self.remote, "merge-base", "--is-ancestor", first, second)


if __name__ == "__main__":
    verbosity = 0 if "-q" in sys.argv else 2
    argv = [a for a in sys.argv if a != "-q"]
    unittest.main(argv=argv, verbosity=verbosity)
