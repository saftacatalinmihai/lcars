"""Kinds by role, for the crew's scripts (docs/design/kinds.md).

A script that needs a kind (the linker's sleepers, weekstats' vocabulary,
the crew's never-write list) asks a role, never a name: the journal's owner
says which kind each role is, in the `settings` entry titled `kinds` the
server reads (lcars_kinds.h, GET /kinds/roles). The captain's journal keeps
its own kind names; no row is renamed for a mapping.

Each script asks once a run, the way it already talks to the server:
crew_tool.py and crew.py over HTTP with the crew's login, lcars_linker.py
through `lcars-cli roles --json`. A server older than the route, or none
answering, leaves every role its default (said once on stderr), so a run
never stops for it. DEFAULTS is a copy of the server's g_kind_roles, in its
order; test_crew.py holds the two equal.

    roles = lcars_roles.load(lambda: http_get_json("/kinds/roles"))
    roles.kind("child_sleep"), roles.kinds("imported"), roles.name("child_sleep")

$LCARS_KINDS_FILE, when set, is read instead of the server: a mapping
(the entry's content, {"v":1,"roles":{...}}, or its roles alone). The tests
use it to run a script with a set mapping and no server.
"""
import json
import os
import sys

# (role, default kind, a list role): lcars_kinds.h's g_kind_roles
DEFAULTS = (
    ("log", "personal_log", False), ("work_log", "work_log", False), ("task", "task", False),
    ("sleep", "sleep", False), ("child_sleep", "child_sleep", False), ("child_vocab", "child_vocab", False),
    ("drive", "drive", False), ("trip", "trip", False), ("workout", "workout", False),
    ("counter", "counter", False), ("share", "share", False), ("page", "page", False),
    ("person", "person", False), ("project", "project", False), ("meeting", "meeting", False),
    ("template", "template", False), ("logseq_journal", "logseq_journal", False),
    ("imported", "logseq_journal", True),
)
_DEF = {r: d for r, d, _ in DEFAULTS}


class Roles:
    """The mapping as one run sees it: role -> its kinds, and a name."""

    def __init__(self, kinds=None, names=None, source="defaults"):
        self._kinds = {r: [d] for r, d, _ in DEFAULTS}
        self._kinds.update(kinds or {})
        self._names = dict(names or {})
        self.source = source

    def kind(self, role):
        """The kind a role writes and reads (a list role: its first)."""
        ks = self._kinds.get(role)
        return ks[0] if ks else _DEF.get(role, role)

    def kinds(self, role):
        """Every kind of a list role (`imported`); a plain role's one."""
        return tuple(self._kinds.get(role) or [self.kind(role)])

    def name(self, role):
        """The words a feature says for the role ("" for none)."""
        return self._names.get(role, "")

    def ask(self, owner):
        """A limited login's reminders: <task>_<owner> (task_crew, task_no1)."""
        return f"{self.kind('task')}_{owner}"


def from_answer(j):
    """GET /kinds/roles's answer, {"roles":[{role, kind, kinds, name}, ...]}."""
    kinds, names = {}, {}
    for r in (j or {}).get("roles") or []:
        if not isinstance(r, dict) or not r.get("role") or not r.get("kind"):
            continue
        ks = [k for k in (r.get("kinds") or str(r["kind"]).split(",")) if isinstance(k, str) and k]
        if ks:
            kinds[r["role"]] = ks
        if isinstance(r.get("name"), str) and r["name"].strip():
            names[r["role"]] = r["name"].strip()
    return Roles(kinds, names, "server")


def from_mapping(m):
    """The entry's own shape: {"v":1,"roles":{"<role>":{"kind","name"}}}."""
    m = m.get("roles", m) if isinstance(m, dict) else {}
    kinds, names = {}, {}
    for role, v in m.items():
        if not isinstance(v, dict):
            continue
        ks = [k for k in str(v.get("kind") or "").split(",") if k]
        if ks:
            kinds[role] = ks
        if isinstance(v.get("name"), str) and v["name"].strip():
            names[role] = v["name"].strip()
    return Roles(kinds, names, "file")


def load(get):
    """The run's roles: $LCARS_KINDS_FILE, else get() (the parsed answer,
    or an exception), else the defaults with a line on stderr."""
    path = os.environ.get("LCARS_KINDS_FILE")
    if path:
        with open(path, encoding="utf-8") as f:
            return from_mapping(json.load(f))
    try:
        j = get()
        if isinstance(j, dict) and isinstance(j.get("roles"), list):
            return from_answer(j)
        why = "the answer is not a list of roles"
    except Exception as e:  # noqa: BLE001 - any failure is "no mapping": the run goes on
        why = str(e) or e.__class__.__name__
    print(f"kinds: every role its default ({why[:120]})", file=sys.stderr)
    return Roles()


class Lazy:
    """A tuple of kinds worked out at its first use, not at import: a
    script's module constants (crew_tool's NOT_WRITING) read the roles,
    and importing the module must not ask the server. key: what it was
    worked out from (the module's roles object), checked on each use."""

    def __init__(self, fn, key=None):
        self._fn, self._key, self._v, self._k = fn, key, None, None

    def _get(self):
        # worked out again when the roles it was read from are replaced
        # (a test's own mapping), once otherwise
        k = self._key() if self._key else None
        if self._v is None or k is not self._k:
            self._v, self._k = tuple(self._fn()), k
        return self._v

    def __iter__(self):
        return iter(self._get())

    def __contains__(self, k):
        return k in self._get()

    def __len__(self):
        return len(self._get())

    def __getitem__(self, i):
        return self._get()[i]

    def __repr__(self):
        return repr(self._get())
