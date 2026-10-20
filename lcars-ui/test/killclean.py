"""A test's scratch directory, and the processes it started, that go with
it when the run is killed.

    import killclean
    tmp = pathlib.Path(killclean.mkdtemp("lcars-foo-"))
    proc = killclean.child(subprocess.Popen([binary, "--port", ...]))

The tests remove their scratch at the end of a run (or keep it, with the
server's log, when a check failed). A run killed from outside never gets
there: the tool's 10-minute timeout, a closed terminal. Its directories
were left behind, and /tmp on the VPS is tmpfs, so they held RAM: ~156 MB
of them in 2026-10 (docs/ops/engineer-time.md), and the scratch server
went on running, its binary and database deleted under it. Here SIGTERM
and SIGHUP end every process given to child(), remove every directory
made through mkdtemp, then end the process with the
same signal, as it would have ended without the handler: the exit status
is unchanged, and no finally block runs on a half-torn-down run. A
SIGKILL cannot be caught; `engineer.py reap` sweeps what that leaves, a
day later. Ctrl-C (SIGINT) is left alone: it is a person, who may want the
log.
"""
import os
import shutil
import signal
import tempfile
import time

_dirs = []
_procs = []


def end(procs, grace=2.0):
    """SIGTERM to each process still running, then SIGKILL to what has not
    ended within grace seconds of the first: a scratch server stops in
    milliseconds, and a hung one must not hold the run's end up."""
    live = [p for p in procs if p.poll() is None]
    for p in live:
        try:
            p.terminate()
        except OSError:
            pass
    deadline = time.time() + grace
    for p in live:
        try:
            p.wait(max(0.0, deadline - time.time()))
        except Exception:  # noqa: BLE001 - TimeoutExpired: the hard way
            try:
                p.kill()
                p.wait(1)
            except Exception:  # noqa: BLE001
                pass


def _killed(sig, _frame):
    # the children first: a server still running would be writing its log
    # into the directory being removed
    end(_procs)
    for d in _dirs:
        shutil.rmtree(d, ignore_errors=True)
    signal.signal(sig, signal.SIG_DFL)
    os.kill(os.getpid(), sig)


def _arm():
    if _dirs or _procs:
        return
    for s in (signal.SIGTERM, signal.SIGHUP):
        # a handler of the program's own is its business, not ours
        if signal.getsignal(s) == signal.SIG_DFL:
            signal.signal(s, _killed)


def mkdtemp(prefix, dir=None):
    d = tempfile.mkdtemp(prefix=prefix, dir=dir)
    _arm()
    _dirs.append(d)
    return d


def child(proc):
    """A Popen the run started - a scratch lcars server, a shard of itself -
    ended with it when it is killed (SIGTERM, a short grace, SIGKILL), before
    its directories go. A normal exit is the test's own business, as before:
    it stops its server itself. Returns proc."""
    _arm()
    _procs.append(proc)
    return proc
