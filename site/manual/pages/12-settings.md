## 12. Offline, updates and settings {#settings}

The console keeps working without a connection: what you write is kept on this device, in the outbox, and sent when the server is back.

### Working offline

When the server cannot be reached, the header says **offline**{ui}, with how many changes are waiting (for example "2 waiting"). Keep writing as usual.

- When the connection is back, the waiting changes are sent by themselves. A tap on **offline**{ui} tries at once.
- If an entry was changed both here and elsewhere, the header says how many there are to resolve. Tap it; for each one, choose **Overwrite**{ui} (send your edit; **the other version is lost**) or **Load theirs**{ui} (throw your edit away and keep the server's).
- If this device's storage is full, the console says that offline changes will not survive a reload. Reconnect before you close the page.

A course can be kept for offline use too: see [Trips and the map](#trips).

### Update the app

The version is beside **LCARS**{ui}, at the top left. When the server has a newer one, it is marked; a tap shows what is new, with **Update**{ui}.

You can also open **Config**{ui} and, under **this app**{ui}:

- **Update to v…**{ui} loads the newer version and reloads the page.
- **Check now**{ui} asks the server which version it has.
- **Reload**{ui}, here in Config, fetches the app's files again and reloads, even with no update.
- **What's new**{ui} lists the releases newer than this page.

### Settings (Config)

**Config**{ui} is under **More**{ui} (⋯) in the header, or say "computer, settings". It is one dialog, titled **Connection**{ui}: **Connect**{ui}, at its foot, saves what you changed and **Cancel**{ui} drops it (the volume and Kinds save as you change them). It holds:

- **base url**{ui} and your login: the server's address and who you are.
- **drag a row right**{ui} and **drag a row left**{ui}: what a sideways drag on a list row does. For example, done / not done, delete / restore, or open in the editor.
- **speech recognition**, the **volume** of the console's sounds, what the **chat voice says**, when the **voice turns off**, **quick answers**, and when **ambient mode** starts on its own.
- **Server — what it can do**{ui}: each feature, on or off, and what an off one needs. **W** opens the same list.
- **Classified — Secret entries**{ui}: see [Classified entries](#classified).
- **Kinds — what each feature writes**{ui}: see below.

### Choose which kind each feature writes

Each feature finds its kind by role: new entries use the log role's kind, tasks the task role's, courses the trip role's, and so on. A new journal uses the default names (`personal_log`, `task`, `trip`…).

To use your own names, open **Config → Kinds**, and point a role at a kind. Or say it: "computer, set the kind for the task to todos". "To default" puts a role back.

### Change the colours (themes) {#themes}

The console can wear another palette: LCARS's own is the default, and 41 more are built in, the themes of btop (a terminal system monitor), such as nord, dracula, gruvbox_dark, tokyo-night and solarized_light.

- Tap **Theme** under More (**⋯**) in the header, or **Theme…** in the settings (**Connection**), or open the commands (**p**) and choose **Theme…**, or say "computer, choose a theme". The picker lists every theme, the current one ticked, each marked dark or light. As you move through the list, the console takes each theme at once, so you see it before you choose. Enter (or a tap) keeps it; **Esc** puts the one you had back.
- Or say it: "computer, theme nord", "computer, theme gruvbox dark". Hyphens and underscores in a name are spaces when you say it. A name that fits several ("computer, theme everforest") opens the picker on them.
- "computer, default theme", or **Theme: lcars** in the commands, brings LCARS's colours back.
- A theme marked "low contrast" has text that is hard to read on its own background. It is offered anyway.
- The theme is kept in the journal, so every phone and computer wears the one you chose, and an open console follows a change made elsewhere within a second or two.
- A theme of your own: from a terminal, `lcars-cli theme load FILE` takes a btop `.theme` file or an omarchy `colors.toml`, and it appears in the picker under its name, marked "from omarchy" or "from a file". `lcars-cli theme set nord` chooses a built-in, `lcars-cli theme reset` brings LCARS back, and `lcars-cli theme` says which is worn.
- On omarchy, `scripts/omarchy/lcars-webapp --local` installs LCARS on the machine and puts it in the app launcher; `lcars-webapp --remote https://HOST` adds a launcher for a server elsewhere, and `lcars-webapp --uninstall` takes it away (your journal stays). The password is kept in `~/.config/lcars/env`, never in the launcher: the browser asks for it once. It also offers to install the theme hook below for you.
- On omarchy, the console can follow the desktop: copy `scripts/omarchy/lcars-theme-set` into `~/.config/omarchy/hooks/theme-set.d/` and make it executable. Each time omarchy changes theme, the console takes the same colours. It needs lcars-cli and the server's address and password, as lcars-cli takes them (the script's first lines say how).
- Red and yellow alert keep their own colours under every theme.

### Other settings

- **Header buttons**{ui} (under **More**{ui}, on a phone): which four buttons the header carries.
- **Sound**{ui} (**s**): the console's beeps and chirps, on or off.
- **Reset**, on the public demo's banner ("Demo · a made-up journal · your edits stay in this browser"): puts the made-up journal back as it was. **Your edits in this browser are dropped.** Say "computer, reset the demo" to do the same.

### Related

- [When something goes wrong](#trouble)
- [Classified entries](#classified)
- [Start here](#start)
