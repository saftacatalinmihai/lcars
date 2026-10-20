#!/usr/bin/env python3
"""Generate importable Apple Shortcuts (.shortcut) files for the LCARS HTTP API.

A .shortcut file is a property list describing WFWorkflowActions. Apple's own
export signs that plist (AEA container); an unsigned plist is still importable
as long as the device has Settings > Privacy & Security > Allow Untrusted
Shortcuts turned on -- that is how RoutineHub and friends distribute shortcuts.
See README.md next to this file for the import routes.

Every shortcut is self-contained: the first two actions hold the server URL and
the `user:password` pair, and both are declared as import questions, so the
Shortcuts app asks for them once while importing instead of the user having to
hunt through the actions afterwards.

Usage: python3 shortcuts/generate.py [--url URL] [outdir]

--url is the server's address the import question offers (the shortcuts are
built with no host of ours in them); the user can still change it there.
"""

import argparse
import plistlib
import re
import uuid
from pathlib import Path

# Object Replacement Character: the placeholder a Shortcuts text token leaves
# where an attachment (a variable) is spliced in. attachmentsByRange indexes
# those placeholders by UTF-16 offset, which is why offsets are computed on the
# encoded string rather than on Python's code points.
OBJ = "￼"

# What the import question offers when no --url is given: a placeholder,
# so a shortcut built without one asks for the real address.
API_DEFAULT_URL = "https://your-lcars-server"
SERVER_URL = API_DEFAULT_URL   # --url, set by main()
API_DEFAULT_AUTH = "user:password"

URL_VAR = "LcarsURL"
AUTH_VAR = "LcarsAuth"


# --- plist building blocks -------------------------------------------------


def var(name):
    """Attachment dict for a named variable (one set by Set Variable)."""
    return {"Type": "Variable", "VariableName": name}


def token(template, attachments=None):
    """WFTextTokenString from a template using {name} placeholders.

    `attachments` maps each placeholder name to an attachment dict. A template
    with no placeholders still round-trips as a token, which is what most
    parameters expect.
    """
    attachments = attachments or {}
    out = []
    ranges = {}
    i = 0
    while i < len(template):
        ch = template[i]
        if ch == "{":
            end = template.index("}", i)
            name = template[i + 1 : end]
            assert name in attachments, "no attachment for {%s}" % name
            prefix = "".join(out)
            offset = len(prefix.encode("utf-16-le")) // 2
            ranges["{%d, 1}" % offset] = attachments[name]
            out.append(OBJ)
            i = end + 1
        else:
            out.append(ch)
            i += 1
    value = {"string": "".join(out)}
    if ranges:
        value["attachmentsByRange"] = ranges
    return {"Value": value, "WFSerializationType": "WFTextTokenString"}


def var_input(name):
    """WFTextTokenAttachment: a whole value (not text) taken from a variable."""
    return {"Value": var(name), "WFSerializationType": "WFTextTokenAttachment"}


def dict_field(pairs):
    """WFDictionaryFieldValue from (key, value-token) pairs. WFItemType 0 = text."""
    items = [
        {"WFItemType": 0, "WFKey": token(k), "WFValue": v} for k, v in pairs
    ]
    return {
        "Value": {"WFDictionaryFieldValueItems": items},
        "WFSerializationType": "WFDictionaryFieldValue",
    }


def act(identifier, params=None):
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": params or {},
    }


def set_var(name):
    return act("is.workflow.actions.setvariable", {"WFVariableName": name})


def auth_headers():
    """The Authorization header every route but /health requires."""
    return dict_field(
        [("Authorization", token("Basic {a}", {"a": var(AUTH_VAR)}))]
    )


def prelude():
    """Server URL + base64 credentials, plus the import questions for both.

    Returns (actions, questions). The questions reference action indices 0 and
    2, so the prelude must stay at the front of the action list.
    """
    actions = [
        act("is.workflow.actions.gettext", {"WFTextActionText": SERVER_URL}),
        set_var(URL_VAR),
        act("is.workflow.actions.gettext", {"WFTextActionText": API_DEFAULT_AUTH}),
        # Basic auth is base64(user:password); line breaks would corrupt the
        # header, and the default on older clients is to wrap at 76 columns.
        act(
            "is.workflow.actions.base64encode",
            {"WFEncodeMode": "Encode", "WFBase64LineBreakMode": "None"},
        ),
        set_var(AUTH_VAR),
    ]
    questions = [
        {
            "ParameterKey": "WFTextActionText",
            "Category": "Parameter",
            "ActionIndex": 0,
            "Text": "LCARS server URL (scheme, host and port)",
            "DefaultValue": SERVER_URL,
        },
        {
            "ParameterKey": "WFTextActionText",
            "Category": "Parameter",
            "ActionIndex": 2,
            "Text": "LCARS credentials as user:password",
            "DefaultValue": API_DEFAULT_AUTH,
        },
    ]
    return actions, questions


def get_url(url_token, method="GET", body=None):
    """URL action, then Get Contents of URL -- returns both actions.

    The URL cannot be assembled in Get Contents of URL's own field: that field
    is typed URL, and splicing a variable built by a Text action into it fails
    at run time with "couldn't convert from Rich Text to URL". The URL action
    (`WFURLActionURL`) is the one that takes text with variables and hands back
    a real URL value, so the request reads it out of a variable instead.

    WFURL still names that variable *and* the URL action sits immediately
    before the request, so the request gets the same URL whether the field is
    honoured or the action falls back to its input.
    """
    actions = [
        act(
            "is.workflow.actions.url",
            {"Show-WFURLActionURL": True, "WFURLActionURL": [url_token]},
        ),
        set_var("RequestURL"),
    ]
    params = {
        "WFURL": var_input("RequestURL"),
        "WFHTTPMethod": method,
        "WFHTTPHeaders": auth_headers(),
    }
    if body is not None:
        params["WFHTTPBodyType"] = "JSON"
        params["WFJSONValues"] = body
    actions.append(act("is.workflow.actions.downloadurl", params))
    return actions


def dict_value(key, source_var):
    return act(
        "is.workflow.actions.getvalueforkey",
        {
            "WFInput": var_input(source_var),
            "WFDictionaryKey": key,
            "WFGetDictionaryValueType": "Value",
        },
    )


def render_rows(line_template, keys):
    """Repeat over the JSON array in `Rows`, building one text line per entry.

    Each key is pulled into a variable named after it (`title` -> `title`) and
    spliced into `line_template`. Lines are appended to the `Lines` list
    variable, which Combine Text joins after the loop -- a repeat block's own
    output would need an action-output UUID reference, and a plain list
    variable is the sturdier of the two.
    """
    group = str(uuid.uuid4()).upper()
    actions = [
        act(
            "is.workflow.actions.repeat.each",
            {
                "GroupingIdentifier": group,
                "WFControlFlowMode": 0,
                "WFInput": var_input("Rows"),
            },
        )
    ]
    for key in keys:
        actions.append(dict_value(key, "Repeat Item"))
        actions.append(set_var(key))
    actions.append(
        act(
            "is.workflow.actions.gettext",
            {
                "WFTextActionText": token(
                    line_template, {k: var(k) for k in keys}
                )
            },
        )
    )
    actions.append(
        act("is.workflow.actions.appendvariable", {"WFVariableName": "Lines"})
    )
    actions.append(
        act(
            "is.workflow.actions.repeat.each",
            {"GroupingIdentifier": group, "WFControlFlowMode": 2},
        )
    )
    actions.append(
        act(
            "is.workflow.actions.text.combine",
            {"WFInput": var_input("Lines"), "WFTextSeparator": "New Lines"},
        )
    )
    actions.append(set_var("Report"))
    actions.append(
        act(
            "is.workflow.actions.showresult",
            {"Text": token("{r}", {"r": var("Report")})},
        )
    )
    return actions


INPUT_CLASSES = [
    "WFAppStoreAppContentItem",
    "WFArticleContentItem",
    "WFContactContentItem",
    "WFDateContentItem",
    "WFEmailAddressContentItem",
    "WFGenericFileContentItem",
    "WFImageContentItem",
    "WFiTunesProductContentItem",
    "WFLocationContentItem",
    "WFDCMapsLinkContentItem",
    "WFAVAssetContentItem",
    "WFPDFContentItem",
    "WFPhoneNumberContentItem",
    "WFRichTextContentItem",
    "WFSafariWebPageContentItem",
    "WFStringContentItem",
    "WFURLContentItem",
]

# Icon colours as the Shortcuts app stores them (packed RGBA integers).
COLORS = {
    "orange": 4251333119,
    "yellow": 4274264319,
    "red": 4282601983,
    "blue": 463140863,
    "purple": 2071128575,
    "green": 4292093695,
}


def workflow(actions, questions, glyph, color, share_sheet=False):
    wf = {
        "WFWorkflowClientVersion": "2038.0.2",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": COLORS[color],
            "WFWorkflowIconGlyphNumber": glyph,
        },
        "WFWorkflowImportQuestions": questions,
        "WFWorkflowTypes": ["ActionExtension"] if share_sheet else ["NCWidget", "WatchKit"],
        "WFWorkflowInputContentItemClasses": INPUT_CLASSES,
        "WFWorkflowHasShortcutInputVariables": share_sheet,
        "WFWorkflowActions": actions,
    }
    return wf


# --- the shortcuts ---------------------------------------------------------


def post_entry(kind, content_attachment_var, title_token=None):
    pairs = [
        ("kind", token(kind)),
        ("content", token("{c}", {"c": content_attachment_var})),
    ]
    if title_token is not None:
        pairs.append(("title", title_token))
    return get_url(
        token("{u}/entries", {"u": var(URL_VAR)}),
        method="POST",
        body=dict_field(pairs),
    ) + [
        set_var("Response"),
        dict_value("id", "Response"),
        set_var("NewID"),
        act(
            "is.workflow.actions.notification",
            {
                "WFNotificationActionTitle": "LCARS",
                "WFNotificationActionBody": token(
                    "Saved to %s as entry #{i}" % kind, {"i": var("NewID")}
                ),
                "WFNotificationActionSound": False,
            },
        ),
    ]


def shortcut_ask_and_post(prompt, kind):
    actions, questions = prelude()
    actions += [
        act(
            "is.workflow.actions.ask",
            {
                "WFAskActionPrompt": prompt,
                "WFInputType": "Text",
                "WFAllowsMultilineText": True,
            },
        ),
        set_var("Entry"),
    ]
    actions += post_entry(kind, var("Entry"))
    return actions, questions


def shortcut_share(kind):
    """Share-sheet entry point: whatever was shared becomes the content."""
    actions, questions = prelude()
    actions += post_entry(kind, {"Type": "ExtensionInput"})
    return actions, questions


def shortcut_today():
    actions, questions = prelude()
    actions += [
        act("is.workflow.actions.date", {"WFDateActionMode": "Current Date"}),
        act(
            "is.workflow.actions.format.date",
            {"WFDateFormatStyle": "Custom", "WFDateFormat": "yyyy-MM-dd"},
        ),
        set_var("Today"),
        # `date=` filters on created_at_utc, so around local midnight this shows
        # the UTC day rather than the wall-clock one.
    ]
    actions += get_url(
        token(
            "{u}/entries?date={d}&limit=100&order=created&dir=asc",
            {"u": var(URL_VAR), "d": var("Today")},
        )
    )
    actions += [set_var("Rows")]
    actions += render_rows(
        "{created_at_utc} [{kind}] {title}\n{content}\n",
        ["created_at_utc", "kind", "title", "content"],
    )
    return actions, questions


def shortcut_open_tasks(task_kind="task"):
    actions, questions = prelude()
    actions += get_url(
        token(
            "{u}/entries?kind=" + task_kind + "&done=0&limit=100&order=created&dir=desc",
            {"u": var(URL_VAR)},
        )
    )
    actions += [set_var("Rows")]
    actions += render_rows("#{id} {title} {content}", ["id", "title", "content"])
    return actions, questions


def shortcut_search():
    actions, questions = prelude()
    actions += [
        act(
            "is.workflow.actions.ask",
            {"WFAskActionPrompt": "Search LCARS for", "WFInputType": "Text"},
        ),
        set_var("Query"),
        # The term goes into a query string, so anything with a space or an
        # ampersand has to be percent-encoded before it is spliced in.
        act(
            "is.workflow.actions.urlencode",
            {"WFEncodeMode": "Encode", "WFInput": var_input("Query")},
        ),
        set_var("Q"),
    ]
    actions += get_url(
        token(
            "{u}/entries?q={q}&limit=50&order=created&dir=desc",
            {"u": var(URL_VAR), "q": var("Q")},
        )
    )
    actions += [set_var("Rows")]
    actions += render_rows(
        "{created_at_utc} [{kind}] {title}\n{content}\n",
        ["created_at_utc", "kind", "title", "content"],
    )
    return actions, questions


def shortcut_stats():
    actions, questions = prelude()
    actions += get_url(token("{u}/stats", {"u": var(URL_VAR)}))
    actions += [set_var("Stats")]
    keys = ("count", "kinds", "done", "content_bytes",
            "oldest_created_at_utc", "newest_created_at_utc")
    for key in keys:
        actions.append(dict_value(key, "Stats"))
        actions.append(set_var(key))
    actions.append(
        act(
            "is.workflow.actions.showresult",
            {
                "Text": token(
                    "Entries: {count}\nKinds: {kinds}\nDone: {done}\n"
                    "Bytes: {content_bytes}\nOldest: {oldest_created_at_utc}\n"
                    "Newest: {newest_created_at_utc}",
                    {k: var(k) for k in keys},
                )
            },
        )
    )
    return actions, questions


def shortcut_computer():
    """Talk to the journal's Claude Code agent (POST /ask), Siri doing the voice.

    Dictate, send, speak the answer, listen again: a conversation, until a
    turn hears nothing. The session id the first answer brings back is sent
    with every later turn (the server's --resume), and it starts empty, so
    each run of the shortcut is a new conversation. The phone's own clock and
    zone go with every turn, because the server's are not the user's. The
    answer is spoken, not shown: Show Result would stop the loop for a tap,
    and the server words `text` for the ear already. An error is a spoken
    `text` as well (see "Voice" in lcars_chat.h), so there is nothing to
    branch on here.
    """
    actions, questions = prelude()
    loop = str(uuid.uuid4()).upper()
    stop = str(uuid.uuid4()).upper()
    actions += [
        act("is.workflow.actions.gettext", {"WFTextActionText": ""}),
        set_var("SessionID"),
        act(
            "is.workflow.actions.repeat.count",
            {"GroupingIdentifier": loop, "WFControlFlowMode": 0, "WFRepeatCount": 50},
        ),
        act(
            "is.workflow.actions.dictatetext",
            {"WFDictateTextStopListening": "After Pause"},
        ),
        set_var("Heard"),
        # Silence ends it: nothing heard, nothing to send.
        act(
            "is.workflow.actions.conditional",
            {
                "GroupingIdentifier": stop,
                "WFControlFlowMode": 0,
                "WFCondition": 101,  # "does not have any value"
                "WFInput": {"Type": "Variable", "Variable": var_input("Heard")},
            },
        ),
        act("is.workflow.actions.exit"),
        act(
            "is.workflow.actions.conditional",
            {"GroupingIdentifier": stop, "WFControlFlowMode": 2},
        ),
        act("is.workflow.actions.date", {"WFDateActionMode": "Current Date"}),
        act(
            "is.workflow.actions.format.date",
            {"WFDateFormatStyle": "Custom", "WFDateFormat": "yyyy-MM-dd HH:mm ZZZZZ"},
        ),
        set_var("LocalTime"),
    ]
    actions += get_url(
        token("{u}/ask", {"u": var(URL_VAR)}),
        method="POST",
        body=dict_field(
            [
                ("session_id", token("{s}", {"s": var("SessionID")})),
                ("local_time", token("{t}", {"t": var("LocalTime")})),
                ("message", token("{m}", {"m": var("Heard")})),
            ]
        ),
    )
    actions += [
        set_var("Answer"),
        dict_value("session_id", "Answer"),
        set_var("SessionID"),
        dict_value("text", "Answer"),
        set_var("Spoken"),
        act(
            "is.workflow.actions.speaktext",
            {"WFText": token("{t}", {"t": var("Spoken")}), "WFSpeakTextWait": True},
        ),
        act(
            "is.workflow.actions.repeat.count",
            {"GroupingIdentifier": loop, "WFControlFlowMode": 2},
        ),
    ]
    return actions, questions


# The kinds are the journal's roles (docs/design/kinds.md), fixed when the
# files are built: a shortcut cannot ask GET /kinds/roles before it posts
# without a second request on every run. --kind is the log role's kind
# (Log, Share), --task-kind the task role's (Task, Open Tasks); `lcars-cli
# roles` says what a journal has.
def shortcuts(kind="personal_log", task_kind="task"):
    return [
        ("LCARS Log", shortcut_ask_and_post, ("New log entry", kind), 59511, "orange"),
        ("LCARS Task", shortcut_ask_and_post, ("New task", task_kind), 59829, "red"),
        ("LCARS Note", shortcut_ask_and_post, ("New note", "note"), 59723, "yellow"),
        ("LCARS Share", shortcut_share, (kind,), 59558, "purple"),
        ("LCARS Today", shortcut_today, (), 59511, "blue"),
        ("LCARS Open Tasks", shortcut_open_tasks, (task_kind,), 59829, "green"),
        ("LCARS Search", shortcut_search, (), 59767, "blue"),
        ("LCARS Stats", shortcut_stats, (), 59505, "purple"),
        ("LCARS Computer", shortcut_computer, (), 59723, "orange"),
    ]


def main():
    global SERVER_URL
    ap = argparse.ArgumentParser(description="Build the LCARS shortcuts (.shortcut files).")
    ap.add_argument("--url", default=API_DEFAULT_URL,
                    help="the server's address the import question offers (default: a placeholder)")
    ap.add_argument("--kind", default="personal_log",
                    help="the kind Log and Share post: the log role's (default personal_log)")
    ap.add_argument("--task-kind", default="task",
                    help="the kind Task posts and Open Tasks lists: the task role's (default task)")
    ap.add_argument("outdir", nargs="?", default=str(Path(__file__).parent))
    a = ap.parse_args()
    for k in (a.kind, a.task_kind):
        if not re.fullmatch(r"[a-z0-9_]{1,127}", k):
            ap.error(f"{k!r} is not a kind (letters, digits and _)")
    SERVER_URL = a.url.rstrip("/")
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    for name, builder, args, glyph, color in shortcuts(a.kind, a.task_kind):
        actions, questions = builder(*args)
        wf = workflow(
            actions, questions, glyph, color, share_sheet=(builder is shortcut_share)
        )
        path = outdir / ("%s.shortcut" % name)
        data = plistlib.dumps(wf, fmt=plistlib.FMT_BINARY)
        path.write_bytes(data)
        # Re-read as a sanity check that the plist is well formed.
        plistlib.loads(data)
        print("%s  (%d actions, %d bytes)" % (path, len(actions), len(data)))


if __name__ == "__main__":
    main()
