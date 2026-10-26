import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Commons as Commons
import qs.Ui
import "Model.js" as Model

// The LCARS mark in the omarchy bar (docs/design/omarchy-plugin.md in the
// LCARS repo). Kept small on purpose: no omarchy runs where it is built, so
// the logic is in Model.js, which the tests run in node, and this file only
// wires it to the shell. Click: the console as an app. Right click: Open,
// New entry, Set up…, Add to the app launcher. Middle click: check now.
BarWidget {
  id: root
  moduleName: "dev.mihai-safta.lcars"

  // The address: the widget's `url` setting, else LCARS_URL in
  // ~/.config/lcars/env (the file the theme hook and lcars-cli read). Only
  // that line of the file is used; the login in it never reaches QML.
  readonly property string configHome: Quickshell.env("XDG_CONFIG_HOME") || (Quickshell.env("HOME") + "/.config")
  property string envText: ""
  readonly property string base: Model.effectiveBase(root.setting("url", ""), envText)
  readonly property int pollMs: Model.pollMs(root.setting("pollSec", 60))

  // "unknown" until the first answer for this base; "up" or "down" after
  property string health: "unknown"
  readonly property string st: Model.state(base, health)
  property bool hasLauncher: false
  property bool popupOpen: false

  onBaseChanged: { health = "unknown"; check() }

  // the shell's routing contract for a bar widget (open/close/opened)
  readonly property bool opened: popupOpen
  function open() { refreshLauncher(); popupOpen = true }
  function close() { popupOpen = false }
  function toggle() { if (popupOpen) close(); else open() }

  function pluginFile(rel) { return Model.localPath(Qt.resolvedUrl(rel)) }

  function openConsole() {
    if (!base) { setUp(); return }
    var url = Model.consoleUrl(base)
    // focuses the console's window when one is open, by the class Chromium
    // gives it; else starts it as omarchy-launch-webapp would
    Quickshell.execDetached(["omarchy-launch-or-focus-webapp", Model.windowClass(url), url])
  }

  function newEntry() {
    if (!base) { setUp(); return }
    Quickshell.execDetached(["omarchy-launch-webapp", Model.captureUrl(base)])
  }

  // The installer (bin/lcars-webapp) in omarchy's own floating terminal,
  // where the user sees and answers what it does: adding a plugin runs
  // nothing, so this click is where a server is installed or named.
  function setUp() {
    Quickshell.execDetached(["omarchy-launch-floating-terminal-with-presentation",
                             Model.shellQuote(pluginFile("bin/lcars-webapp"))])
  }

  function addLauncher() {
    if (!base) { setUp(); return }
    Quickshell.execDetached(["omarchy-webapp-install", "LCARS", Model.consoleUrl(base), pluginFile("icon.png")])
    launcherRecheck.restart()
  }

  function refreshLauncher() { desktopFile.reload() }

  // GET /health: no login, nothing of the journal in it. QML's own
  // XMLHttpRequest, not a process per poll; aborted after 3 s by a timer
  // (the request's own timeout is not one QML's XHR keeps).
  property var xhr: null
  function check() {
    if (xhr) { xhr.abort(); xhr = null }
    if (!base) return
    var req = new XMLHttpRequest()
    var forBase = base
    xhr = req
    req.onreadystatechange = function() {
      if (req.readyState !== XMLHttpRequest.DONE) return
      if (root.xhr === req) { root.xhr = null; abortTimer.stop() }
      if (forBase === root.base) root.health = Model.healthOf(req.status)
    }
    req.open("GET", Model.healthUrl(base))
    req.send()
    abortTimer.restart()
  }

  Timer {
    id: abortTimer
    interval: 3000
    onTriggered: if (root.xhr) root.xhr.abort()
  }

  Timer {
    interval: root.pollMs
    running: root.base !== ""
    repeat: true
    onTriggered: root.check()
  }

  Timer {
    id: launcherRecheck
    interval: 2000
    onTriggered: root.refreshLauncher()
  }

  FileView {
    path: root.configHome + "/lcars/env"
    watchChanges: true
    printErrors: false
    onFileChanged: reload()
    onLoaded: root.envText = text()
    onLoadFailed: root.envText = ""
  }

  FileView {
    id: desktopFile
    path: Quickshell.env("HOME") + "/.local/share/applications/LCARS.desktop"
    printErrors: false
    onLoaded: root.hasLauncher = true
    onLoadFailed: root.hasLauncher = false
  }

  Component.onCompleted: check()

  implicitWidth: mark.implicitWidth + Style.space(14)
  implicitHeight: barSize

  Text {
    id: mark
    anchors.centerIn: parent
    textFormat: Text.PlainText
    text: root.vertical ? "LC" : "LCARS"
    font.family: root.bar ? root.bar.fontFamily : ""
    font.pixelSize: Style.font.body
    font.bold: true
    font.letterSpacing: 1
    color: !root.bar ? "transparent"
      : root.st === "down" ? root.bar.urgent
      : root.bar.barForeground
    opacity: root.st === "unset" ? 0.45 : 1.0
  }

  MouseArea {
    anchors.fill: parent
    hoverEnabled: true
    cursorShape: Qt.PointingHandCursor
    acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
    onClicked: function(mouse) {
      if (mouse.button === Qt.RightButton) root.toggle()
      else if (mouse.button === Qt.MiddleButton) root.check()
      else root.openConsole()
    }
    onEntered: if (root.bar) root.bar.showTooltip(root, Model.tooltip(root.st, root.base))
    onExited: if (root.bar) root.bar.hideTooltip(root)
  }

  PopupCard {
    id: popup
    anchorItem: root
    bar: root.bar
    owner: root
    open: root.popupOpen
    contentWidth: popup.fittedContentWidth(Style.space(240))
    contentHeight: popup.fittedContentHeight(rows.implicitHeight)

    Column {
      id: rows
      anchors.fill: parent
      spacing: Style.space(4)

      Repeater {
        model: [
          { label: "Open LCARS", act: "open", on: true },
          { label: "New entry", act: "new", on: true },
          { label: "Set up…", act: "setup", on: true },
          { label: "Add to the app launcher", act: "launcher", on: !root.hasLauncher }
        ]

        Button {
          required property var modelData
          width: rows.width
          text: modelData.label
          foreground: root.bar ? root.bar.foreground : Commons.Color.foreground
          enabled: modelData.on
          opacity: enabled ? 1.0 : 0.4
          onClicked: {
            root.close()
            if (modelData.act === "open") root.openConsole()
            else if (modelData.act === "new") root.newEntry()
            else if (modelData.act === "setup") root.setUp()
            else root.addLauncher()
          }
        }
      }
    }
  }
}
