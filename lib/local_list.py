#!/usr/bin/env python3
"""The part of `qargi local list` that reads processes: the STATE of each run.

  local_list.py states            read run directories (NUL-ended) on standard input, print for each, NUL-ended, the directory, its STATE and its lock wait (whole seconds)

STATE is display only, derived from RUN/dispatch.json (what the runner of `qargi local run` wrote) and from the runner's process; nothing is signalled, nothing is
written, and nothing of it decides what verify, clean or apply do:

  prepared   the run has no dispatch.json: it was prepared, and no `qargi local run` has started it (a run of an in-session member is always this)
  waiting    the runner is alive and its record says waiting_since: it waits for the lane or for the lock of a refresh
  running    the runner is alive and does not wait (the member runs, or the runner is making ready: no member is recorded yet)
  ended      the record says the run ended (any outcome), or it says running and its runner is gone (a runner that was killed)
  unknown    the record cannot be read or understood, or the runner cannot be compared with a process (no /proc)

The runner is alive when the process with its pid has the start token the record names (runner_start, field 22 of /proc/PID/stat, as lib/lane.py compares it, so a
pid that was reused is not the runner); a record written before the token was kept is compared by the runner's command line, which names local_run.py and the run
(lib/local_run.py proc_of_run). The files of a run are a member's to write: every value read from one is checked for its type and nothing else is believed.
Run as python3 -I lib/local_list.py; standard library only (lib/local_run.py is imported for the command line of a record with no start token)."""
import json
import math
import os
import stat
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import lane as LN  # noqa: E402

MAX_RECORD = 1 << 20
STATES = ("prepared", "waiting", "running", "ended", "unknown")


def read_record(run):
    """(record, why): the JSON object of RUN/dispatch.json (a regular file, never a link, at most MAX_RECORD bytes), or (None, 'absent') when there is none, or
    (None, 'unreadable') when there is one that cannot be read as an object."""
    path = os.path.join(run, "dispatch.json")
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        return None, "absent"
    except OSError:
        return None, "unreadable"
    if not stat.S_ISREG(st.st_mode):
        return None, "unreadable"
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None, "unreadable"
    try:
        data = os.read(fd, MAX_RECORD + 1)
        if len(data) > MAX_RECORD:
            return None, "unreadable"
        doc = json.loads(data.decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return None, "unreadable"
    finally:
        os.close(fd)
    return (doc, "") if isinstance(doc, dict) else (None, "unreadable")


def whole_seconds(value):
    """The seconds of a wait as a whole number, rounded up (a wait of a fraction of a second is 1); 0 for anything that is not a finite number of 0 or more."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return 0
    return min(int(math.ceil(value)), 2 ** 31)


def runner_alive(rec, run):
    """True or False, or None when the runner cannot be compared with a process: the pid and its start token of the record, else the command line of the runner."""
    pid = rec.get("runner")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1:
        return None
    start = rec.get("runner_start")
    if isinstance(start, str) and start:
        if not os.path.isdir("/proc/self"):
            return None
        return LN.alive(pid, start)
    try:
        import local_run
        return bool(local_run.proc_of_run(pid, os.path.realpath(run), "runner"))
    except Exception:                                   # a runner found by its command line is a best effort: any failure is "cannot tell"
        return None


def state_of(run):
    """(STATE, whole seconds the runner waited for a lock) of the run directory."""
    rec, why = read_record(run)
    if rec is None:
        return ("prepared" if why == "absent" else "unknown"), 0
    waited = whole_seconds(rec.get("lock_wait_s"))
    outcome = rec.get("outcome")
    if not isinstance(outcome, str) or not outcome:
        return "unknown", waited
    if outcome != "running":
        return "ended", waited
    alive = runner_alive(rec, run)
    if alive is None:
        return "unknown", waited
    if not alive:
        return "ended", waited
    since = rec.get("waiting_since")
    return ("waiting" if isinstance(since, str) and since else "running"), waited


def cmd_states():
    runs = [os.fsdecode(p) for p in sys.stdin.buffer.read().split(b"\0") if p]
    out = sys.stdout.buffer
    for run in runs:
        state, waited = state_of(run)
        for field in (run, state, str(waited)):
            out.write(os.fsencode(field) + b"\0")
    out.flush()
    return 0


def main(argv):
    if argv == ["states"]:
        return cmd_states()
    print("usage: local_list.py states", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
