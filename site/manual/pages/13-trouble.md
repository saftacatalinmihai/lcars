## 13. When something goes wrong {#trouble}

Find what you see, then follow its steps.

### The list says "no link"

The console cannot reach the server. It shows "cannot reach" with the server's address and the reason.

1. Tap **Retry**{ui}.
2. If it fails again, tap **Config**{ui}. Check **base url**{ui} and the login, then tap **Connect**{ui}.
3. If they are right, the server itself is down or out of reach of this network. What you wrote while offline is kept on this device and sent when it is back (see [Offline, updates and settings](#settings)).

### An entry says "✕ Not saved · Retry"

The save did not reach the server. Your text is still in the editor.

1. Tap the chip to try again.
2. If the console says the entry was "Changed on the server", it was edited somewhere else too, such as another window. Choose **Overwrite**{ui} to keep yours (**the other version is lost**) or **Load theirs**{ui} to keep the server's.

### A button or a view says a feature is off

Some features need something on the server: a key, a program or a setting. Press **W** (or say "computer, what is off"). It lists each feature that is off and what it needs. The README on GitHub explains each setting: [github.com/saftacatalinmihai/lcars](https://github.com/saftacatalinmihai/lcars).

### The header shows a red or yellow alert

Tap it, or say "computer, why the alert". It says what the alert is about. Red: offline, changes not sent, a failed save, or overdue tasks. Yellow: a save under way, or changes waiting to be sent.

### The page looks old, or a new feature is missing

The version beside **LCARS**{ui} is the version of this page. Open **Config**{ui} and, under **this app**{ui}, tap **Check now**{ui}, then **Update**{ui} if one is offered. Config's **Reload**{ui} fetches the app again even when it is up to date.

### The microphone does not listen

1. Check that the browser may use the microphone for this site.
2. Say "computer, status": it says which field is listening, and in what mode.
3. While dictation is on, an order needs "computer" in front. With dictation paused, the console answers orders without it.

### Classified entries say they need a secure page

Secret entries need the page served over https. Open the console at its https address.

### I cannot find how to do something

- Press **p** for the command palette and type a word: every filter and action is there by name.
- Press **?** for the keyboard help and type a word: it finds the key.
- Say "computer, help" for every spoken phrase.
- Say "computer, open the manual" to read this manual beside the console.

### Related

- [Offline, updates and settings](#settings)
- [Every key](#keys)
- [Every spoken phrase](#phrases)
