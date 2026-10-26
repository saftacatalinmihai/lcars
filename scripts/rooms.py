"""Rooms: the crew's messages (docs/design/rooms.md).

The one place the header of a crew message is read and written. Every
message between the crew carries, as its first line and alone on it, one
header: `room:: <id>` (for that room) or `to:: <name>` (for that crew
member). threads v2's tag line, `[thread <id>]`, is read as `room:: <id>`,
so a transcript or an inbox row from before rooms is read by the same
parser; nothing writes it any more.

Every message is also a journal row of kind crew_msg (the record, never
pruned: the full text, its header first) beside the crew_inbox slip that
delivers it (seat.py's, pruned weekly); a project room is a crew_room row.
The rows' I/O is seat.py's (msg_add, room_put), which has the journal's
login; this module is pure, so engineer.py, seat.py, no1.py and the tests
share it without a journal.

The page has one copy of HEADER_RE (index.html's ROOM_HEAD, beside
engFrom): scripts/test_rooms.py runs it under node against this one.
"""

import re

MSG_KIND = "crew_msg"
ROOM_KIND = "crew_room"
MAIN = "main"  # Number One's main room (threads v2's main thread)
NO1_NAMES = ("no1", "number-one")  # both name Number One in a to:: header

ID = r"[a-z][a-z0-9-]{0,23}"
ROOM_ID_RE = re.compile(r"^" + ID + r"$")
# The keys case-blind and the id lowered, spaces around "::" allowed: a model
# writing the header gets it a little wrong more often than badly wrong, and
# a near miss costing a misroute is worse than accepting it. Alone on its
# line: "room:: deck and more" is text.
_HEAD = r"[ \t]*(?:(room|to)[ \t]*::[ \t]*([A-Za-z][A-Za-z0-9-]{0,23})|\[thread (" + ID + r")\])[ \t]*"
HEADER_RE = re.compile(r"^" + _HEAD + r"(?:\r?\n|$)", re.I)
# A paragraph of Number One's that speaks into another room: a room:: line
# alone, or (threads v2) a [thread x] tag, the rest of its line then the text.
# Matched only at the text's start or after a blank line (split).
PARA_RE = re.compile(r"(?m)^[ \t]*(?:room[ \t]*::[ \t]*([A-Za-z][A-Za-z0-9-]{0,23})[ \t]*(?:\r?\n|$)"
                     r"|\[thread (" + ID + r")\][ \t]*\n?)", re.I)
# A misrouted header, kept on the row's second line (rooms.md 10.1)
MISROUTED = "misrouted:: "


def header(text):
    """(kind, id, body): kind "room" or "to" and the id lowered, the body the
    text after the header line; (None, None, text) when it has none."""
    t = text or ""
    m = HEADER_RE.match(t)
    if not m:
        return None, None, t
    if m.group(3):
        return "room", m.group(3), t[m.end():]
    return m.group(1).lower(), m.group(2).lower(), t[m.end():]


def strip(text):
    """The text without its header line."""
    return header(text)[2]


def room_of(text, default=MAIN):
    """The room a message's header names, else `default` (a to:: names a
    person, not a room)."""
    k, i, _ = header(text)
    return i if k == "room" else default


def to_of(text):
    """The crew member a to:: header names (Number One as "no1"), else None."""
    k, i, _ = header(text)
    if k != "to":
        return None
    return "no1" if i in NO1_NAMES else i


def line(room=None, to=None):
    return f"to:: {to}" if to else f"room:: {room or MAIN}"


def headed(text, room=None, to=None):
    """`text` with exactly one header: `to:: <to>` if given, else `room::
    <room>`; a header it had is replaced."""
    return line(room, to) + "\n" + strip(text).lstrip("\n")


def typed_for_no1(text, room):
    """What is typed to Number One for a message of `room`: its header line
    first, main's untagged (an untagged message is main's)."""
    return text if not room or room == MAIN else f"room:: {room}\n{text}"


def split(text, cur):
    """Number One's text cut where a paragraph begins with a room line:
    ([(room, part)], the room in force after it). The part before any line is
    `cur`'s. Only at a paragraph's start: the text's own or after a blank line."""
    t = text or ""
    out, at = [], 0
    for m in PARA_RE.finditer(t):
        if m.start() and not t[:m.start()].endswith("\n\n"):
            continue
        part = t[at:m.start()].strip()
        if part:
            out.append((cur, part))
        cur, at = (m.group(1) or m.group(2)).lower(), m.end()
    part = t[at:].strip()
    if part or not out:
        out.append((cur, part if at else t))
    return out, cur


def first_line(text):
    return (strip(text).strip().splitlines() or [""])[0][:90]


def title(frm, to, room, text):
    """A crew_msg row's title, its index: "<from> → <to> #<room>: <first
    line>"; a message to the room's members has no <to>."""
    return f"{frm} → {(to + ' ') if to else ''}#{room or MAIN}: {first_line(text)}"


TITLE_RE = re.compile(r"^(?P<frm>[^ ]+) → (?:(?P<to>[^ #][^ ]*) )?#(?P<room>" + ID + r"): ?(?P<first>.*)$", re.S)


def title_parse(t):
    """{frm, to, room, first} from a crew_msg title, or None."""
    m = TITLE_RE.match(t or "")
    return {k: m.group(k) or "" for k in ("frm", "to", "room", "first")} if m else None


def content(text, room, to=None, extra=()):
    """A crew_msg row's text: its header line first (the row says on its own
    where it went), then any `key:: value` lines (`extra`), then the body
    whole. The header is `to:: <to>` for a crew member addressed by name,
    and `room:: <room>` for the room's members - a message to Number One
    too, who is in every room (rooms.md decision 8: a report carries room::)."""
    lines = [line(room, to if to not in NO1_NAMES else None)] + [x for x in extra if x]
    return "\n".join(lines) + "\n" + strip(text).lstrip("\n")


ROOM_LINE_RE = re.compile(r"(?m)^id::[ \t]*(" + ID + r")[ \t]*$")


def room_row_id(row):
    """The room id a crew_room row is for (its `id::` line), or None."""
    m = ROOM_LINE_RE.search((row or {}).get("content") or "")
    return m.group(1) if m else None
