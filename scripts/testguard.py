"""Imported first by the tests that run engineer.py in-process: nothing they
do can reach a journal they did not stand up themselves.

engineer.py writes Number One's inbox, the seat and the notices through the
seat module (seat._http, crew_tool's login from ~/.env), and crew_tool's
default URL is the live server on this box. A test that stubs one writer
(`tell`) while the code under test calls another (`no1_send`) reached it:
in 0.284.0's work test_no1.py's Answers wrote a "[captain] ticked off your
question #7" row into the live crew_inbox. So, for the whole run:

- LCARS_URL is a port nothing listens on (9, discard), for this process and
  every engineer.py it starts;
- seat._http raises NoJournal, a BaseException, so no `except Exception`
  in engineer.py swallows it (and then spawns a retry unit): the test fails,
  loudly, where it wrote. A test with a stand-in patches seat._http itself
  (test_no1_threads.py's Journal), which wins inside its patch;
- engineer.py's state is a scratch directory (teststate.py).
"""

import os
import sys

os.environ["LCARS_URL"] = "http://127.0.0.1:9"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import teststate  # noqa: E402,F401 - nor the box's real engineer state
import seat  # noqa: E402


class NoJournal(BaseException):
    """A test reached for the journal without a stand-in."""


def _no_journal(method, path, body=None):
    raise NoJournal(f"a test reached the journal: {method} {path.split('?')[0]} - stand one in (seat._http)")


seat._http = _no_journal
