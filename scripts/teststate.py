"""Imported before engineer.py by every test that loads it (testguard.py
imports it first): engineer.py's state is never the box's real one.

engineer.py reads LCARS_ENG_STATE once, when it loads, and makes its paths
from it then: STATE, and with it DEPLOY_JSON, HISTORY, NO1_ANSWERS. A test
that patches E.STATE alone leaves those three on whatever STATE was at
import, and with the variable unset that is the box's real
~/.local/state/lcars-eng: on 2026-10-22 test_no1_threads.py's deploy case
(`E.detach("deploy", "obrien")`), run by the public export's test stage,
wrote a phantom "queued" deploy into the real deploy.json, and the job
line waited behind it. So, before engineer.py loads: LCARS_ENG_STATE is a
scratch directory of the run's own, unless the test has set one already
(and never the real one). Every engineer.py the test starts inherits it.
"""

import atexit
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lcars-ui", "test"))
import killclean  # noqa: E402 - the scratch goes with a killed run too

# engineer.py's default, by the same rule (its HOME is the environment's)
REAL = os.path.realpath(os.path.join(os.environ.get("HOME") or os.path.expanduser("~"), ".local/state/lcars-eng"))


def real(path):
    """True when path is the real state directory or inside it."""
    p = os.path.realpath(path)
    return p == REAL or p.startswith(REAL + os.sep)


if "engineer" in sys.modules:
    raise RuntimeError("teststate imported after engineer.py: its paths are already the real state's")
if not os.environ.get("LCARS_ENG_STATE") or real(os.environ["LCARS_ENG_STATE"]):
    STATE = killclean.mkdtemp("guard-test-")
    atexit.register(shutil.rmtree, STATE, True)
    os.environ["LCARS_ENG_STATE"] = STATE
