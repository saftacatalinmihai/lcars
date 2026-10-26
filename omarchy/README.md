# LCARS for omarchy

A bar widget for [omarchy](https://omarchy.org) that puts
[LCARS](https://github.com/saftacatalinmihai/lcars), a Star Trek-style
personal journal, one click away: the LCARS mark in the bar opens the
journal's web console as an app. With no server yet, the same click sets
one up: the whole system on this machine from LCARS's public release, or
the address of a server you already run.

Plugin id `dev.mihai-safta.lcars`, MIT licence.

## Install

    omarchy plugin add https://github.com/saftacatalinmihai/omarchy-lcars.git --enable

omarchy shows you the repo and asks before it adds anything (a plugin runs
inside the shell with your permissions: read it first). Adding runs
nothing from the plugin; the mark appears on the right of the bar, dimmed
until a server is set up.

## Set up

Click the dimmed mark (or right click → **Set up…**). A terminal opens
running `bin/lcars-webapp`, the installer, which asks which you want:

- **Local**: it downloads the LCARS release for your machine from GitHub,
  checks it against the release's `SHA256SUMS`, makes a journal with
  `lcars init`, and starts it as a systemd user unit on 127.0.0.1.
- **Remote**: you give the address of your LCARS server and its login; it
  checks the server answers.

Either way it writes the address (and the login) to
`~/.config/lcars/env` (mode 0600), adds LCARS to the app launcher
(Super+Space) with `omarchy-webapp-install`, and offers to install the
theme hook, `bin/lcars-theme-set`, so the console takes on each theme you
set in omarchy. The mark lights up within a minute.

The widget reads only the `LCARS_URL=` line of that file; the login stays
in the file, for the browser's own sign-in prompt, `lcars-cli` and the
theme hook. To point the widget elsewhere without touching the file, set
**Server address** in the bar's settings for the widget; it wins over the
file. **Check the server every** sets how often it asks (60 s by
default).

## Use

- **Click**: the console in its own window; a second click focuses it.
- **Right click**: Open LCARS, New entry (the console's quick capture),
  Set up…, Add to the app launcher.
- **Middle click**: check the server now.
- The mark is drawn in the bar's colour while the server answers its
  `/health` (no login needed, nothing of the journal in it), in the bar's
  urgent colour while it does not, and dimmed while none is set up.

### In the omarchy menu too

omarchy's own menu takes extensions without a plugin. To have LCARS under
Super+Alt+Space, add this to `~/.config/omarchy/extensions/omarchy-menu.jsonc`
(with your address):

```jsonc
{
  "items": [
    {
      "id": "lcars",
      "label": "LCARS",
      "icon": "󰠮",
      "children": [
        { "id": "lcars-open", "label": "Open", "action": "omarchy-launch-webapp https://your.server/ui/" },
        { "id": "lcars-new", "label": "New entry", "action": "omarchy-launch-webapp 'https://your.server/ui/?capture=1'" },
        { "id": "lcars-setup", "label": "Set up", "action": "omarchy-launch-floating-terminal-with-presentation ~/.config/omarchy/plugins/dev.mihai-safta.lcars/bin/lcars-webapp" }
      ]
    }
  ]
}
```

(omarchy's `docs/menu.md` has the file's whole shape.)

## Remove

Two steps, in this order:

1. `~/.config/omarchy/plugins/dev.mihai-safta.lcars/bin/lcars-webapp --uninstall`
   stops and removes the systemd unit and the launcher entry. It never
   deletes your journal: it says where it is. `~/.config/lcars/env` is
   left too (it holds no entries); delete it by hand if you want.
2. `omarchy plugin remove dev.mihai-safta.lcars` takes the widget away.

## Dependencies

- omarchy with its Quickshell shell (the plugin system, `omarchy-launch-webapp`,
  `omarchy-webapp-install`, a Chromium-based browser for web apps).
- For a local server: `curl`, `sha256sum`, `tar` and systemd's user
  instance (all on omarchy already); the LCARS release is one static
  binary, x86_64 or arm64, downloaded from
  github.com/saftacatalinmihai/lcars/releases.
- For a remote one: an LCARS server you can reach.

## Testing

What runs without omarchy is checked by `scripts/test_omarchy_plugin.py`
in the LCARS repo (the manifest against omarchy's validator, the
marketplace's rules, `Model.js` in node). The widget itself needs an
omarchy machine; this is the list to go through there:

1. `omarchy plugin validate ~/path/to/lcars/omarchy` exits 0.
2. `omarchy plugin add <repo> --enable`: the warning, then the mark on
   the right of the bar.
3. No server set: the mark dimmed, the tooltip "not set up"; a click opens
   the floating terminal with the installer.
4. Local setup: the binary, the unit (`systemctl --user status lcars`),
   LCARS under Super+Space, the mark lit within a minute.
5. Click: the console in its own window; a second click focuses it, no
   second window.
6. Right click: the four rows; New entry opens the quick capture; Set
   up… and Add to the app launcher do what they say (the last greyed out
   once the launcher entry exists).
7. Stop the unit (`systemctl --user stop lcars`): the mark turns the
   urgent colour within the poll; start it, and middle click: lit at once.
8. Remote setup against a server elsewhere: the login asked once, and
   the browser's own sign-in remembered by the web app.
9. The widget's settings in the bar: Server address and Check the server
   every, a change taking effect without a restart.
10. `omarchy theme set <another>`: the mark follows the bar's colours;
    with the hook installed, the console's theme follows too.
11. `bin/lcars-webapp --uninstall`, then `omarchy plugin remove
    dev.mihai-safta.lcars`: nothing left but the journal and the env file.
12. Throughout, the shell's log (`journalctl --user -b | grep -i lcars`)
    shows no QML warning from the plugin.
