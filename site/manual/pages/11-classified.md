## 11. Classified entries {#classified}

A Secret entry is encrypted in your browser before it is sent, with a key only your password opens. The server keeps the encrypted text and never sees the password.

### Who can read a Secret entry

Only you, on a device where you have unlocked it. Everyone else sees an entry marked **▮ Classified**{ui}, with its kind and its dates but not its title or text. That includes the computer's chat, the crew, Number One, and anyone holding a copy of the journal.

![A locked Secret entry at a desk: the title reads Classified, the kind and the time show, and a box says the entry is Secret, its title and text encrypted, with an Unlock button.](img/classified.webp "A Secret entry while the page is locked.")

What stays visible: the kind, when it was written, its schedule and whether it is done. What is sealed: the title, the text and any value it holds, such as a weight.

Limits:

- An entry with files cannot be made Secret: files are not encrypted. Remove them first.
- A Secret entry is not read aloud.
- Dictating into one sends your voice to the recogniser, off the device. The dictation bar says so: "▮ Secret entry — the voice leaves the device".

### Set the password, the first time

1. Open **Config**{ui} (under **More**{ui}), and find **Classified — Secret entries**{ui}. Tap **Set a password…**{ui}. (Marking an entry Secret before there is a password opens the same dialog.)
2. Type the password (at least 8 characters) in **the new password**{ui} and **the same again**{ui}.
3. Leave **Make a recovery code too**{ui} ticked. **If you lose this password, your Secret entries are gone. Nobody can recover them: not the server, not its admin, not an engineer.** The recovery code is the one way back.
4. Tick **I understand: a lost password means my Secret entries are gone**, and tap **Set the password**.
5. **Your recovery code**{ui} appears. It is shown this once. **Keep it in a password manager or on paper, away from this device.** It opens your Secret entries if the password is lost, for anyone who holds it. Tap **Copy**{ui} if you want it on the clipboard, then **I have kept it**{ui}.

The page is now unlocked on this device.

### Make an entry Secret

1. Open the entry. Under its title, the chip says **Unclassified**{ui}.
2. Tap the chip (or say "computer, mark this secret"). If the page is locked, it asks for the password first.
3. The chip says **▮ Secret · sealing…**{ui}, then **▮ Secret**{ui}. If sealing fails, it says **✕ Not sealed · Retry**{ui}; tap it to try again.

### Unlock and lock

Once a password is set, **Locked**{ui} appears in the header (under **More**{ui} on a phone, as **Unlock classified**{ui}, unless you chose it in Header buttons), or press **L**. Tap it, type the password, and tap **Unlock**. With a passkey registered, **Use a passkey** unlocks with Face ID, a fingerprint or a security key instead.

The page locks itself after 15 minutes idle, 5 minutes away, or a reload. To lock it at once, tap **Unlocked**{ui} in the header, or say "computer, lock". Locking drops the key and the decrypted text from the page.

### Add a passkey

In **Config → Classified**, while unlocked, tap **Register this device…**{ui}. It asks for the password once more, then your device makes the passkey. **Remove**{ui}, beside a passkey, takes it off the list.

### Lost the password?

**Without the password, the recovery code or a passkey, your Secret entries are gone.** Their rows stay, as placeholders with their kind and dates, and can be deleted.

With the recovery code:

1. Tap **Locked**{ui}, then **Lost the password? Use the recovery code…**{ui}.
2. Type the code, then a new password twice.
3. Tap **Unlock and set it**{ui}. The code stays valid. If anyone may have seen it, make a new one in Config (**Replace it…**{ui}, or **Make one…**{ui} if you have none); **the old code then stops working**.

### Change the password

In **Config → Classified**, tap **Change the password…**{ui}: the password now, then the new one twice. No entry is rewritten: the entries keep their key, and only the password that opens it changes.

### Declassify an entry

1. Open the Secret entry and tap its **▮ Secret**{ui} chip (or say "computer, declassify").
2. If the page is locked, it asks for the password first. Then it asks "Declassify #…?" (with the entry's number). **Its title and text go back to the journal in the clear, where the chat, the crew, Number One and every copy of the journal can read them.**
3. Tap **Declassify**{ui} to go ahead.

### Related

- [Write an entry](#write)
- [Offline, updates and settings](#settings)
- [When something goes wrong](#trouble)
