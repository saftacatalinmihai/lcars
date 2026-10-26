#!/usr/bin/env python3
"""Tests for omarchy/bin/lcars-webapp (docs/design/omarchy-plugin.md 2), the
omarchy plugin's installer, scripts/omarchy/lcars-webapp a link to it:
run in a scratch HOME with stand-ins on PATH for omarchy-webapp-install
and -remove, curl (GitHub's API, the downloads, /health and the icon), gh,
systemctl, and the release's lcars (a script in a made-up tarball). Both
modes, ~/.config/lcars/env (0600, the login in it and nowhere else, its
other lines kept), --uninstall, --dry-run, a second run's "left alone",
a newer release, a tarball that fails its checksum, the plugin's icon,
the file run alone, and the refusal off omarchy.

    python3 scripts/test_webapp.py   (~2s)
"""

import hashlib
import io
import json
import os
import pathlib
import platform
import pty
import re
import shutil
import subprocess
import sys
import tarfile
import time
import unittest

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "lcars-ui" / "test"))
import killclean  # noqa: E402 - its scratch goes when the run is killed

SCRIPT = HERE.parent / "omarchy" / "bin" / "lcars-webapp"
LINK = HERE / "omarchy" / "lcars-webapp"
TMP = pathlib.Path(killclean.mkdtemp(prefix="webapp-test-"))
ARCH = {"aarch64": "arm64", "arm64": "arm64"}.get(platform.machine(), "x86_64")
REPO = "saftacatalinmihai/lcars"

# Each stand-in logs its argv, one line, to $FAKE/log.
CURL = r'''#!/usr/bin/env python3
import os, shutil, sys
F = os.environ["FAKE"]
open(F + "/log", "a").write("curl " + " ".join(sys.argv[1:]) + "\n")
a = sys.argv[1:]
url = [x for x in a if x.startswith("http")][-1]
out = a[a.index("-o") + 1] if "-o" in a else None
if "api.github.com" in url:
    sys.stdout.write(open(F + "/release.json").read()); sys.exit(0)
if "/download/" in url:
    shutil.copy(F + "/dl/" + url.rsplit("/", 1)[1], out); sys.exit(0)
if url.endswith("/health"):
    sys.exit(0 if os.path.exists(F + "/up") else 7)
if url.endswith("/ui/icon-512.png"):
    # the login comes as a config on stdin (-K -), kept for the test to read
    if "-K" in a:
        open(F + "/curlconf", "a").write(sys.stdin.read())
    if not os.path.exists(F + "/icon"):
        sys.exit(22)
    open(out, "wb").write(b"\x89PNG the server's")
    sys.exit(0)
sys.exit(6)
'''
GH = r'''#!/usr/bin/env python3
import os, sys
F = os.environ["FAKE"]
open(F + "/log", "a").write("gh " + " ".join(sys.argv[1:]) + "\n")
if not os.path.exists(F + "/gh"):
    sys.exit(4)
sys.stdout.write(open(F + "/release.json").read())
'''
SYSTEMCTL = r'''#!/usr/bin/env python3
import os, pathlib, sys
F = pathlib.Path(os.environ["FAKE"])
(F / "log").open("a").write("systemctl " + " ".join(sys.argv[1:]) + "\n")
a = [x for x in sys.argv[1:] if x not in ("--user", "--quiet")]
if a[0] == "is-enabled": sys.exit(0 if (F / "enabled").exists() else 1)
if a[0] == "is-active": sys.exit(0 if (F / "active").exists() else 3)
if a[:2] == ["enable", "--now"]:
    for f in ("enabled", "active", "up"): (F / f).touch()
if a[:2] == ["disable", "--now"]:
    for f in ("enabled", "active", "up"): (F / f).unlink(missing_ok=True)
'''
INSTALL = r'''#!/usr/bin/env python3
import os, pathlib, sys
F = os.environ["FAKE"]
open(F + "/log", "a").write("omarchy-webapp-install " + " ".join(sys.argv[1:]) + "\n")
d = pathlib.Path(os.environ["HOME"]) / ".local/share/applications"
d.mkdir(parents=True, exist_ok=True)
name, url, icon = sys.argv[1:4]
# as omarchy's own: empty, or an existing file (it copies it into
# ~/.local/share/icons/hicolor); a URL is never handed to it here
if icon:
    if not os.path.isfile(icon):
        sys.exit("icon is not a file: " + icon)
    open(F + "/installed-icon", "wb").write(open(icon, "rb").read())
(d / (name + ".desktop")).write_text(f"[Desktop Entry]\nName={name}\nExec=omarchy-launch-webapp {url}\nIcon={icon}\n")
'''
REMOVE = r'''#!/usr/bin/env python3
import os, pathlib, sys
F = os.environ["FAKE"]
open(F + "/log", "a").write("omarchy-webapp-remove " + " ".join(sys.argv[1:]) + "\n")
d = pathlib.Path(os.environ["HOME"]) / ".local/share/applications"
for n in sys.argv[1:]: (d / (n + ".desktop")).unlink(missing_ok=True)
'''
# the release's binary: init as the real one does it, by its output's words
LCARS = r'''#!/bin/sh
echo "lcars $*" >> "$FAKE/log"
[ "$1" = init ] || exit 0
mkdir -p "$2"
printf 'LCARS_PORT=8080\nLCARS_AUTH_USER=lcars\nLCARS_AUTH_PASS=pw\n' > "$2/lcars.env"
echo "made      $2/lcars.env (mode 600)"
echo "Open:      http://127.0.0.1:8080/ui/"
echo "Login:     lcars / pw"
'''


class Webapp(unittest.TestCase):
    def setUp(self):
        n = self.id().rsplit(".", 1)[1]
        self.root = TMP / n
        self.home = self.root / "home"
        self.fake = self.root / "fake"
        self.bin = self.root / "bin"
        for d in (self.home, self.fake / "dl", self.bin):
            d.mkdir(parents=True)
        # a PATH of the stand-ins and only what they need: no real gh or gum
        for name, text in (("curl", CURL), ("gh", GH), ("systemctl", SYSTEMCTL),
                           ("omarchy-webapp-install", INSTALL),
                           ("omarchy-webapp-remove", REMOVE)):
            self.put(name, text)
        for tool in ("python3", "sh", "mkdir"):
            (self.bin / tool).symlink_to(shutil.which(tool))
        self.release("0.337.2")
        self.extra = {}
        (self.fake / "icon").touch()

    def put(self, name, text):
        p = self.bin / name
        p.write_text(text)
        p.chmod(0o755)

    def release(self, version, corrupt=False):
        """The made-up release on 'GitHub': its tarball, SHA256SUMS, the JSON."""
        top = f"lcars-{version}-linux-{ARCH}"
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as t:
            data = LCARS.encode()
            ti = tarfile.TarInfo(top + "/lcars")
            ti.size, ti.mode = len(data), 0o755
            t.addfile(ti, io.BytesIO(data))
            ti = tarfile.TarInfo(top + "/lcars-cli")
            ti.type, ti.linkname = tarfile.SYMTYPE, "lcars"
            t.addfile(ti)
        blob = buf.getvalue()
        name = top + ".tar.gz"
        (self.fake / "dl" / name).write_bytes(blob)
        digest = hashlib.sha256(blob + (b"x" if corrupt else b"")).hexdigest()
        (self.fake / "dl" / "SHA256SUMS").write_text(f"{digest}  {name}\n")
        base = f"https://github.com/{REPO}/releases/download/v{version}/"
        (self.fake / "release.json").write_text(json.dumps({
            "tag_name": "v" + version,
            "assets": [{"name": n, "browser_download_url": base + n}
                       for n in (name, "SHA256SUMS")]}))

    def run_it(self, *args, code=0, script=None, typed=None):
        # by default a copy in a plugin's tree with no icon.png beside bin/
        # (the icon is the plugin's, made in its own slice)
        if script is None:
            script = self.root / "plugin" / "bin" / "lcars-webapp"
            if not script.exists():
                script.parent.mkdir(parents=True)
                shutil.copy(SCRIPT, script)
        env = {"HOME": str(self.home), "PATH": str(self.bin), "FAKE": str(self.fake),
               "USER": "t", "LCARS_WEBAPP_HEALTH_WAIT": "1", **self.extra}
        (self.fake / "log").write_text("")
        stdin, master = subprocess.DEVNULL, None
        if typed is not None:
            # a terminal, with the answer already typed into it
            master, stdin = pty.openpty()
            os.write(master, typed.encode())
        try:
            r = subprocess.run([sys.executable, str(script), *args], env=env,
                               stdin=stdin, capture_output=True, text=True)
        finally:
            if master is not None:
                os.close(master)
                os.close(stdin)
        self.assertEqual(r.returncode, code, r.stdout + r.stderr)
        self.log = (self.fake / "log").read_text()
        return r.stdout + r.stderr

    def desktop(self):
        return (self.home / ".local/share/applications/LCARS.desktop").read_text()

    def env(self):
        return self.home / ".config/lcars/env"

    def test_local_then_again(self):
        out = self.run_it("--local")
        rel = self.home / ".local/lib/lcars/0.337.2"
        data = self.home / ".local/share/lcars"
        self.assertTrue((rel / "lcars").is_file())
        for n in ("lcars", "lcars-cli"):
            self.assertEqual(os.readlink(self.home / ".local/bin" / n), str(rel / "lcars"))
        self.assertIn("checked lcars-0.337.2", out)
        # downloaded and unpacked beside the releases, never in /tmp (a
        # tmpfs on omarchy: the one rename into place would cross devices)
        lib = self.home / ".local/lib/lcars"
        self.assertRegex(self.log, r"curl -fsSL -o " + re.escape(str(lib)) + r"/\.tmp-[^/ ]+/lcars-0\.337\.2-")
        self.assertEqual(list(lib.glob(".tmp-*")), [], "the scratch taken away")
        self.assertIn("Login:     lcars / pw", out)  # init's own words, passed on
        self.assertIn(f"lcars init {data} --port 8080", self.log)
        unit = (self.home / ".config/systemd/user/lcars.service").read_text()
        self.assertIn(f"ExecStart=%h/.local/bin/lcars --data {data} --port 8080", unit)
        self.assertIn("Environment=LCARS_BIND=127.0.0.1", unit)
        self.assertIn("systemctl --user enable --now lcars", self.log)
        self.assertIn("the server answers at http://127.0.0.1:8080/", out)
        # no icon.png beside bin/: the server's, fetched with the login on
        # curl's stdin (never its argv), handed over as a file
        self.assertIn("omarchy-webapp-install LCARS http://127.0.0.1:8080/ui/ /", self.log)
        self.assertEqual((self.fake / "installed-icon").read_bytes(), b"\x89PNG the server's")
        self.assertEqual((self.fake / "curlconf").read_text(), 'user = "lcars:pw"\n')
        self.assertNotIn("pw", "".join(l for l in self.log.splitlines() if l.startswith("curl")))
        self.assertNotIn("pw", self.desktop())
        env = self.env()
        self.assertEqual(env.stat().st_mode & 0o777, 0o600)
        self.assertEqual(env.read_text(), "LCARS_URL=http://127.0.0.1:8080\n"
                         "LCARS_AUTH_USER=lcars\nLCARS_AUTH_PASS=pw\n")
        self.assertIn("never in the launcher", out)
        self.assertFalse((self.home / ".config/omarchy").exists())
        # no gh answer here: the API by curl
        self.assertIn("curl -fsSL -H Accept: application/vnd.github+json "
                      f"https://api.github.com/repos/{REPO}/releases/latest", self.log)

        out = self.run_it("--local")
        for what in ("the release ~/.local/lib/lcars/0.337.2",
                     "the link ~/.local/bin/lcars ->", "the link ~/.local/bin/lcars-cli ->",
                     "the journal ~/.local/share/lcars", "the unit ~/.config/systemd/user/lcars.service",
                     "the service lcars (enabled, running)", "~/.config/lcars/env",
                     "the launcher ~/.local/share/applications/LCARS.desktop"):
            self.assertIn("left alone " + what, out)
        for none in ("/download/", "lcars init", "enable --now", "restart",
                     "omarchy-webapp-install"):
            self.assertNotIn(none, self.log)

    def test_newer_release_relinks_and_restarts(self):
        self.run_it("--local")
        self.release("0.338.0")
        out = self.run_it("--local")
        new = self.home / ".local/lib/lcars/0.338.0/lcars"
        self.assertTrue(new.is_file())
        self.assertTrue((self.home / ".local/lib/lcars/0.337.2/lcars").is_file())
        self.assertEqual(os.readlink(self.home / ".local/bin/lcars"), str(new))
        self.assertIn("systemctl --user restart lcars", self.log)
        self.assertIn("left alone the journal", out)
        self.assertNotIn("lcars init", self.log)

    def test_bad_checksum_installs_nothing(self):
        self.release("0.337.2", corrupt=True)
        out = self.run_it("--local", code=1)
        self.assertIn("does not match SHA256SUMS", out)
        self.assertFalse((self.home / ".local/lib/lcars/0.337.2").exists())
        self.assertFalse((self.home / ".local/bin/lcars").exists())
        self.assertEqual(list((self.home / ".local/lib/lcars").glob(".tmp-*")), [], "a failed run leaves no scratch")

    def test_a_killed_runs_scratch(self):
        # a .tmp-* a killed run left: an hour old it goes, a younger one
        # (another run's, mid-download) is left alone; neither is a release
        lib = self.home / ".local/lib/lcars"
        old, young = lib / ".tmp-killed", lib / ".tmp-running"
        for d in (old, young):
            (d / "x").mkdir(parents=True)
        os.utime(old, (time.time() - 7200,) * 2)
        self.run_it("--local")
        self.assertFalse(old.exists())
        self.assertTrue(young.exists())
        self.assertTrue((lib / "0.337.2/lcars").is_file())

    def test_gh_answers(self):
        (self.fake / "gh").touch()
        self.run_it("--local")
        self.assertIn(f"gh api repos/{REPO}/releases/latest", self.log)
        self.assertNotIn("api.github.com", self.log)

    def test_existing_journal_and_env_lines(self):
        data = self.home / ".local/share/lcars"
        data.mkdir(parents=True)
        (data / "lcars.env").write_text("LCARS_AUTH_USER=me\nLCARS_AUTH_PASS='a b$c'\n")
        self.env().parent.mkdir(parents=True)
        self.env().write_text("# mine\nLCARS_CLI=/opt/lcars cli\nLCARS_URL=https://old\n")
        (self.fake / "up").touch()
        out = self.run_it("--local")
        self.assertNotIn("lcars init", self.log)
        self.assertIn("left alone the journal ~/.local/share/lcars", out)
        self.assertIn("pointed at https://old", out)
        self.assertEqual(self.env().read_text(),
                         "# mine\nLCARS_CLI=/opt/lcars cli\nLCARS_URL=http://127.0.0.1:8080\n"
                         "LCARS_AUTH_USER=me\nLCARS_AUTH_PASS='a b$c'\n")
        # as the theme hook reads it: sh's `. file`
        r = subprocess.run(["sh", "-c", '. "$1"; printf %s "$LCARS_AUTH_PASS"', "sh",
                            str(self.env())], capture_output=True, text=True)
        self.assertEqual(r.stdout, "a b$c")

    def test_remote(self):
        (self.fake / "up").touch()
        self.extra = {"LCARS_AUTH_USER": "u", "LCARS_AUTH_PASS": "p"}
        out = self.run_it("--remote", "lcars.example.net/ui/")
        self.assertIn("the server answers at https://lcars.example.net/", out)
        self.assertIn("omarchy-webapp-install LCARS https://lcars.example.net/ui/ /", self.log)
        self.assertEqual((self.fake / "curlconf").read_text(), 'user = "u:p"\n')
        self.assertNotIn("systemctl", self.log)
        self.assertEqual(self.env().read_text(), "LCARS_URL=https://lcars.example.net\n"
                         "LCARS_AUTH_USER=u\nLCARS_AUTH_PASS=p\n")
        self.assertNotIn("u:p", self.desktop())
        self.extra = {}
        out = self.run_it("--remote=https://lcars.example.net")
        self.assertIn("left alone the launcher", out)
        self.assertIn("left alone ~/.config/lcars/env", out)

    def test_remote_down_no_login(self):
        out = self.run_it("--remote", "https://x.example.net")
        self.assertIn("did not answer", out)
        self.assertIn("no login given", out)
        self.assertEqual(self.env().read_text(), "LCARS_URL=https://x.example.net\n")
        self.assertIn("https://x.example.net/ui/", self.desktop())

    def test_no_icon_anywhere(self):
        # no plugin icon, the server's refused: the empty argument, said
        (self.fake / "icon").unlink()
        out = self.run_it("--remote", "https://h")
        self.assertIn("omarchy looks for the site's icon itself", out)
        self.assertIn("Icon=\n", self.desktop())
        self.assertFalse((self.fake / "installed-icon").exists())

    def test_remote_needs_an_address(self):
        out = self.run_it("--remote", code=1)
        self.assertIn("no address", out)

    def test_uninstall_keeps_the_data(self):
        self.run_it("--local")
        out = self.run_it("--uninstall")
        self.assertIn("omarchy-webapp-remove LCARS", self.log)
        self.assertIn("systemctl --user disable --now lcars", self.log)
        self.assertFalse((self.home / ".config/systemd/user/lcars.service").exists())
        self.assertFalse((self.home / ".local/share/applications/LCARS.desktop").exists())
        self.assertTrue((self.home / ".local/share/lcars/lcars.env").exists())
        self.assertTrue((self.home / ".local/lib/lcars/0.337.2/lcars").exists())
        self.assertTrue(self.env().exists())
        self.assertIn("never deleted: the journal (~/.local/share/lcars)", out)
        out = self.run_it("--uninstall")  # again: nothing there, nothing run
        self.assertIn("nothing to remove", out)
        self.assertNotIn("systemctl", self.log)

    def test_dry_run_runs_nothing(self):
        (self.bin / "omarchy-webapp-install").unlink()  # works off omarchy too
        for args in (["--local"], ["--remote", "https://h"], ["--uninstall"]):
            out = self.run_it("--dry-run", *args)
            self.assertEqual(self.log, "", args)
            self.assertIn("would  ", out)
        self.assertEqual(sorted(p.name for p in self.home.iterdir()), [])
        out = self.run_it("--local", "--dry-run")
        for what in ("lcars init", "enable --now lcars", "omarchy-webapp-install LCARS",
                     "write ~/.config/lcars/env"):
            self.assertIn(what, out)

    def test_refused_off_omarchy(self):
        (self.bin / "omarchy-webapp-install").unlink()
        for args in (["--local"], ["--remote", "https://h"], ["--uninstall"]):
            out = self.run_it(*args, code=1)
            self.assertIn("this is for omarchy", out)
            self.assertEqual(self.log, "")

    def test_the_plugins_icon(self):
        # icon.png beside bin/: its absolute path, for omarchy to copy
        plugin = self.root / "withicon"
        (plugin / "bin").mkdir(parents=True)
        shutil.copy(SCRIPT, plugin / "bin" / "lcars-webapp")
        (plugin / "icon.png").write_bytes(b"\x89PNG the plugin's")
        self.run_it("--remote", "https://h", script=plugin / "bin" / "lcars-webapp")
        self.assertIn(f"omarchy-webapp-install LCARS https://h/ui/ {plugin / 'icon.png'}\n",
                      self.log)
        self.assertEqual((self.fake / "installed-icon").read_bytes(), b"\x89PNG the plugin's")
        self.assertNotIn("icon-512", self.log)  # the server not asked
        self.assertFalse((self.home / ".local/share/applications/icons").exists())

    def plugin(self):
        """The plugin's bin/ as shipped: the installer and the hook beside it."""
        p = self.root / "full"
        (p / "bin").mkdir(parents=True)
        for f in ("lcars-webapp", "lcars-theme-set"):
            shutil.copy(SCRIPT.parent / f, p / "bin" / f)
        (p / "bin" / "lcars-theme-set").chmod(0o644)  # made executable on yes
        return p / "bin"

    def hook(self):
        return self.home / ".config/omarchy/hooks/theme-set.d/lcars-theme-set"

    def test_theme_hook_offered(self):
        b = self.plugin()
        self.extra = {"LCARS_AUTH_USER": "u", "LCARS_AUTH_PASS": "p"}
        # no terminal: no question, nothing linked
        out = self.run_it("--remote", "https://h", script=b / "lcars-webapp")
        self.assertNotIn("theme", out)
        self.assertFalse(self.hook().is_symlink())
        # a terminal, Enter: yes by default
        out = self.run_it("--remote", "https://h", script=b / "lcars-webapp", typed="\n")
        self.assertIn("Have the console follow omarchy's theme? [Y/n]", out)
        self.assertIn("linked     ~/.config/omarchy/hooks/theme-set.d/lcars-theme-set", out)
        self.assertEqual(os.readlink(self.hook()), str(b / "lcars-theme-set"))
        self.assertTrue(os.access(b / "lcars-theme-set", os.X_OK))
        # again: found, not asked
        out = self.run_it("--remote", "https://h", script=b / "lcars-webapp", typed="n\n")
        self.assertIn("left alone the theme hook", out)
        self.assertNotIn("[Y/n]", out)
        # --uninstall takes the link, not the hook's own file
        out = self.run_it("--uninstall", script=b / "lcars-webapp")
        self.assertIn("remove the theme hook", out)
        self.assertFalse(self.hook().is_symlink() or self.hook().exists())
        self.assertTrue((b / "lcars-theme-set").is_file())

    def test_theme_hook_declined_and_dry(self):
        b = self.plugin()
        out = self.run_it("--local", script=b / "lcars-webapp", typed="n\n")
        self.assertIn("the theme hook not installed", out)
        self.assertFalse(self.hook().is_symlink())
        out = self.run_it("--dry-run", "--remote", "https://h", script=b / "lcars-webapp",
                          typed="y\n")
        self.assertIn("would  ask to have the console follow omarchy's theme", out)
        self.assertFalse(self.hook().is_symlink())

    def test_through_the_link(self):
        # the repo's scripts/omarchy/ link runs the plugin's real file
        self.assertEqual(LINK.resolve(), SCRIPT)
        out = self.run_it("--remote", "https://h", script=LINK)
        self.assertIn("omarchy-webapp-install LCARS https://h/ui/", self.log)
        self.assertIn("never in the launcher", out)

    def test_no_mode_no_terminal(self):
        self.assertIn("which one?", self.run_it(code=2))

    def test_old_words_refused(self):
        self.assertIn("unknown argument", self.run_it("remove", code=2))


if __name__ == "__main__":
    try:
        unittest.main()
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
