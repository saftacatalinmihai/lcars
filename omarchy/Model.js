.pragma library

// The LCARS bar widget's logic, pure JavaScript: no QML, no Quickshell, so
// scripts/test_omarchy_plugin.py runs it in node on a box with no omarchy
// (docs/design/omarchy-plugin.md, section 4). BarWidget.qml only wires it
// to the shell: the file it reads, the request it makes, what it draws.

// ~/.config/lcars/env: the file the theme hook and lcars-cli read too, lines
// of NAME=value as sh would source them - `export` allowed, a value in
// single or double quotes, `#` comments, blank lines. Only what sh would
// give the same answer for is read; anything cleverer ($VAR, a backslash
// escape) is taken literally, since the widget never runs the file.
function parseEnv(text) {
  var out = {}
  var lines = String(text || "").split(/\r?\n/)
  for (var i = 0; i < lines.length; i++) {
    var line = lines[i].trim()
    if (line === "" || line.charAt(0) === "#") continue
    if (line.indexOf("export ") === 0) line = line.slice(7).trim()
    var m = /^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/.exec(line)
    if (!m) continue
    var v = m[2].trim()
    var q = v.charAt(0)
    if ((q === '"' || q === "'") && v.length >= 2 && v.lastIndexOf(q) > 0) {
      v = v.slice(1, v.lastIndexOf(q))
    } else {
      // unquoted: a ` #` starts a comment, as in sh
      var hash = v.search(/\s#/)
      if (hash >= 0) v = v.slice(0, hash).trim()
    }
    out[m[1]] = v
  }
  return out
}

// The server's base address, "scheme://host[:port][/prefix]" with no
// trailing slash, or "" when the text is not one. The console is at
// base + "/ui/"; a user who pasted that, or a trailing slash, gets the
// same base. Only http and https: Chromium's --app runs a javascript: or
// file: URL as a document (omarchy-webapp-install refuses them too).
// The characters are held to a small safe set because the base reaches a
// shell: omarchy-launch-or-focus eval's its launch command, so a quote, a
// space, `;`, `$`, `&` or `?` here would be a command or a glob. A real
// address needs none of them (a login goes in the env file, never the URL).
function normalizeBase(url) {
  var u = String(url || "").trim()
  if (u === "") return ""
  // no "scheme://": a bare host[:port] ("localhost:8080" included, which
  // a scheme test alone would read as the scheme "localhost")
  if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(u)) u = "http://" + u
  var m = /^(https?):\/\/([^\/]+)(\/.*)?$/i.exec(u)
  if (!m) return ""
  var host = m[2]
  if (host.indexOf("@") >= 0) return ""
  if (!/^[A-Za-z0-9.-]+(:[0-9]{1,5})?$/.test(host) && !/^\[[0-9A-Fa-f:.]+\](:[0-9]{1,5})?$/.test(host)) return ""
  var path = (m[3] || "").replace(/\/+$/, "")
  if (/\/ui$/.test(path)) path = path.slice(0, -3)
  if (!/^[A-Za-z0-9._~\/-]*$/.test(path)) return ""
  return m[1].toLowerCase() + "://" + host.toLowerCase() + path
}

// The widget's `url` setting wins; else LCARS_URL from the env file.
function effectiveBase(setting, envText) {
  var s = normalizeBase(setting)
  if (s !== "") return s
  return normalizeBase(parseEnv(envText).LCARS_URL)
}

function consoleUrl(base) { return base ? base + "/ui/" : "" }
// the web manifest's own "Quick capture" shortcut
function captureUrl(base) { return base ? base + "/ui/?capture=1" : "" }
function healthUrl(base) { return base ? base + "/health" : "" }

function hostOf(base) {
  var m = /^https?:\/\/([^\/]+)/.exec(base || "")
  return m ? m[1] : ""
}

// The class Chromium gives an --app window at this URL, as
// omarchy-webapp-window-class prints it: omarchy-launch-or-focus finds the
// open console by it (a pattern matched against the window's class), and
// omarchy-webapp-install writes it as the launcher entry's StartupWMClass,
// so the bar and the launcher open one window between them.
function windowClass(url) {
  var address = String(url || "").replace(/^[^:]*:\/\//, "")
  address = address.replace(/[?#].*$/, "")
  var slash = address.indexOf("/")
  var host = slash >= 0 ? address.slice(0, slash) : address
  var path = slash >= 0 ? address.slice(slash) : ""
  host = host.replace(/^.*@/, "").replace(/:.*$/, "").toLowerCase()
  return ("chrome-" + host + "_" + (path || "/") + "-Default").replace(/\//g, "_")
}

// The poll's period in milliseconds, from the `pollSec` setting: 15 s to an
// hour, 60 s when unset or not a number.
function pollMs(sec) {
  var n = Number(sec)
  if (!isFinite(n) || n <= 0) n = 60
  return Math.round(Math.min(3600, Math.max(15, n)) * 1000)
}

// What the mark shows: "unset" (no address: dimmed, a click sets up),
// "checking" (an address, no answer yet: drawn as lit), "up" (/health
// answered 200: lit), "down" (anything else: the bar's urgent colour).
function state(base, health) {
  if (!base) return "unset"
  if (health === "up" || health === "down") return health
  return "checking"
}

// /health's answer read: a 200 is up, whatever the body; a status of 0 (no
// connection, a timeout's abort, TLS) or anything else is down.
function healthOf(status) {
  return status === 200 ? "up" : "down"
}

function tooltip(st, base) {
  if (st === "unset") return "LCARS: not set up - click to set up"
  if (st === "down") return "LCARS: no answer from " + hostOf(base)
  if (st === "up") return "LCARS: " + hostOf(base)
  return "LCARS: checking " + hostOf(base)
}

// A file:// URL (Qt.resolvedUrl's answer for a file in the plugin) as the
// path a command takes.
function localPath(url) {
  var s = String(url || "")
  if (s.indexOf("file://") === 0) s = s.slice(7)
  try { return decodeURIComponent(s) } catch (e) { return s }
}

// One word for bash -c (the floating terminal's command is run that way).
function shellQuote(s) {
  return "'" + String(s).replace(/'/g, "'\\''") + "'"
}
