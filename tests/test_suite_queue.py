#!/usr/bin/env python3
"""The queue of the whole-suite runs (lib/suite_queue.py): first in, first out with three waiters, the waiter file of a dead pid skipped, a holder killed with
SIGKILL freeing the slot, the bounded wait that refuses and names the holder, the one line of the wait that is printed again only when the holder or the position
changes, the modes of the files, and `status` (text and --json against its registry file). Hermetic, no fixed sleep: every wait is a bounded poll for a file or a
line. Run: python3 tests/test_suite_queue.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import fcntl
import io
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
SQ = os.path.join(LIB, "suite_queue.py")
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import suite_queue as Q  # noqa: E402
import jsonkind as K  # noqa: E402

# What the shell of a verb does (lib/suite_queue.sh), as a process of its own: it opens the lock file, asks `acquire` to take the flock on that descriptor, says when
# it holds the slot (the time of its monotonic clock, which every process of the machine shares), and holds it until it is told to let go (mode hold) or at once (auto).
HELPER = r'''
import os, subprocess, sys, time
sq, state, name, mode = sys.argv[1:5]
bound = sys.argv[5:6]
d = subprocess.run([sys.executable, "-I", sq, "prepare", "--state", state], check=True, capture_output=True, text=True).stdout.strip()
fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
cmd = [sys.executable, "-I", sq, "acquire", "--state", state, "--fd", str(fd), "--owner", str(os.getpid()), "--project", "app", "--verb", "feature verify",
       "--name", name, "--head", "a" * 40, "--poll", "0.02", "--result", os.path.join(state, "result." + name)] + (["--bound", bound[0]] if bound else [])
rc = subprocess.run(cmd, pass_fds=[fd]).returncode
print("rc=%d mono=%d" % (rc, time.monotonic_ns()), flush=True)
if rc == 0:
    if mode == "hold":
        sys.stdin.readline()
    subprocess.run([sys.executable, "-I", sq, "release", "--state", state, "--owner", str(os.getpid())], check=True)
    print("released", flush=True)
'''


def until(predicate, what, timeout=20.0):
    """Polls a condition, bounded: no fixed sleep decides anything."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("timed out waiting for " + what)


class Helper:
    """A process that waits for the slot like the shell of a verb does; its lines on standard output and standard error are kept."""

    def __init__(self, state, name, mode="hold", bound=None):
        self.start([sys.executable, "-I", "-c", HELPER, SQ, state, name, mode] + ([str(bound)] if bound is not None else []), name)

    def start(self, args, name, env=None):
        self.p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        self.name, self.out, self.err = name, [], []
        self.threads = []
        for stream, into in ((self.p.stdout, self.out), (self.p.stderr, self.err)):
            t = threading.Thread(target=lambda s=stream, i=into: [i.append(line.rstrip("\n")) for line in s], daemon=True)
            t.start()
            self.threads.append(t)

    def line(self, prefix):
        return until(lambda: next((l for l in self.out if l.startswith(prefix)), None), "%s: a line %r (have %r, stderr %r)" % (self.name, prefix, self.out, self.err))

    def taken(self):
        """The monotonic time at which it held the slot."""
        line = self.line("rc=")
        assert line.startswith("rc=0 "), "%s did not take the slot: %r %r" % (self.name, self.out, self.err)
        return int(line.split("mono=")[1])

    def let_go(self):
        self.p.stdin.write("release\n")
        self.p.stdin.flush()
        self.line("released")

    def kill(self):
        self.p.kill()

    def close(self):
        try:
            self.p.kill()
        except OSError:
            pass
        self.p.wait()
        for t in self.threads:
            t.join(10)
        for f in (self.p.stdin, self.p.stdout, self.p.stderr):
            try:
                f.close()
            except OSError:
                pass


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sq.")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.dir = os.path.join(self.state, "suite-queue")
        self.helpers = []

    def tearDown(self):
        for h in self.helpers:
            h.close()
        subprocess.run(["rm", "-rf", self.tmp])

    def helper(self, name, mode="hold", bound=None):
        h = Helper(self.state, name, mode, bound)
        self.helpers.append(h)
        return h

    def waits(self, helper):
        return [n for n in os.listdir(self.dir) if n.startswith("wait.%d." % helper.p.pid)] if os.path.isdir(self.dir) else []

    def run_cli(self, *args, **kw):
        return subprocess.run([sys.executable, "-I", SQ] + list(args), capture_output=True, text=True, **kw)

    def status(self):
        r = self.run_cli("status", "--state", self.state, "--json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(K.validate(K.registry_path("qargi-suite-queue"), r.stdout), [])
        return json.loads(r.stdout)


class Order(Base):
    def test_three_waiters_are_served_in_the_order_they_came(self):
        a = self.helper("holder")
        a.taken()
        waiters = []
        for name in ("first", "second", "third"):          # each is known to wait before the next starts: the order of arrival is not a race
            h = self.helper(name, "auto")
            until(lambda h=h: self.waits(h), "the waiter file of " + name)
            waiters.append(h)
        doc = self.status()
        self.assertEqual([w["name"] for w in doc["waiting"]], ["first", "second", "third"])
        self.assertEqual([w["position"] for w in doc["waiting"]], [1, 2, 3])
        a.let_go()
        times = [h.taken() for h in waiters]
        self.assertEqual(times, sorted(times), "served out of order: %r" % times)
        self.assertEqual(len(set(times)), 3)
        for h in waiters:
            h.line("released")
        self.assertEqual(self.status()["state"], "free")
        self.assertEqual([n for n in os.listdir(self.dir) if n.startswith("wait.")], [])

    def test_a_waiter_file_of_a_dead_pid_is_skipped_and_removed(self):
        dead = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
        dead.wait()
        d = Q.prepare(self.state)
        # a file that claims the head of the line: the oldest time, the pid of a process that is gone; and one of a pid that lives but with another start token (a reused pid)
        for name in ("wait.%d.123456" % dead.pid, "wait.%d.1" % os.getpid()):
            with open(os.path.join(d, name), "w") as f:
                json.dump({"schema": 1, "pid": int(name.split(".")[1]), "start": name.split(".")[2], "project": "app", "verb": "feature verify", "name": "ghost", "enqueued": 1}, f)
        self.assertEqual(Q.waiters(d), [])
        self.assertEqual(self.status()["waiting"], [])
        h = self.helper("alive", "auto")
        self.assertTrue(h.taken() > 0)
        left = [n for n in os.listdir(d) if n.startswith("wait.")]
        self.assertEqual(left, [], "the stale files stay: %r" % left)

    def test_the_owner_that_is_gone_ends_the_wait(self):
        dead = subprocess.Popen([sys.executable, "-I", "-c", "pass"])
        dead.wait()
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(fd), "--owner", str(dead.pid), "--verb", "x", "--name", "y", pass_fds=[fd])
        finally:
            os.close(fd)
        self.assertEqual(r.returncode, Q.EX_GONE, r.stderr)
        self.assertEqual(os.listdir(d), ["lock"])


class Holder(Base):
    def test_a_holder_killed_with_sigkill_frees_the_slot(self):
        a = self.helper("doomed")
        a.taken()
        self.assertEqual(self.status()["holder"]["name"], "doomed")
        b = self.helper("next", "auto")
        until(lambda: self.waits(b), "the waiter file of next")
        self.assertNotIn("rc=", " ".join(b.out))
        a.kill()
        b.taken()                                           # the kernel let go of the lock when the process died: nothing else did
        b.line("released")
        self.assertEqual(self.status()["state"], "free")

    def test_the_record_of_a_killed_holder_names_nobody(self):
        a = self.helper("doomed")
        a.taken()
        a.kill()
        a.p.wait()
        until(lambda: self.status()["state"] == "free", "the slot to be free")
        self.assertTrue(os.path.exists(os.path.join(self.dir, "holder.json")), "the record of a killed run is left behind (advisory)")
        doc = self.status()
        self.assertIsNone(doc["holder"])
        self.assertEqual(Q.live_holder(self.dir), None)
        self.assertIn("free", self.run_cli("status", "--state", self.state).stdout)

    def test_release_removes_only_the_record_of_its_owner(self):
        a = self.helper("mine")
        a.taken()
        other = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(30)"])
        try:
            self.assertEqual(self.run_cli("release", "--state", self.state, "--owner", str(other.pid)).returncode, 0)
            self.assertTrue(os.path.exists(os.path.join(self.dir, "holder.json")), "the record of another run was removed")
        finally:
            other.kill()
            other.wait()
        a.let_go()
        self.assertFalse(os.path.exists(os.path.join(self.dir, "holder.json")))

    def test_the_files_and_the_directory_are_private(self):
        a = self.helper("mode")
        a.taken()
        b = self.helper("mode2", "auto")
        until(lambda: self.waits(b), "the waiter file")
        self.assertEqual(stat.S_IMODE(os.stat(self.dir).st_mode), 0o700)
        for n in os.listdir(self.dir):
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.dir, n)).st_mode), 0o600, n)
        with open(os.path.join(self.dir, "holder.json")) as f:
            rec = json.load(f)
        self.assertEqual({k: rec[k] for k in ("project", "verb", "name", "head")}, {"project": "app", "verb": "feature verify", "name": "mode", "head": "a" * 40})
        self.assertEqual(rec["pid"], a.p.pid)
        self.assertEqual(sorted(rec), ["head", "name", "pid", "project", "schema", "start", "started", "verb"])

    def test_pids_name_the_holder_and_the_waiters(self):
        a = self.helper("holder")
        a.taken()
        b = self.helper("waiter", "auto")
        until(lambda: self.waits(b), "the waiter file")
        pids = self.run_cli("pids", "--state", self.state).stdout.split()
        self.assertEqual(pids, [str(a.p.pid), str(b.p.pid)])


class Bound(Base):
    def test_a_bound_that_runs_out_refuses_and_names_the_holder(self):
        a = self.helper("busyone")
        a.taken()
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        result = os.path.join(self.tmp, "result")
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(fd), "--owner", str(os.getpid()), "--project", "app", "--verb", "release verify", "--name", "0.3.10",
                             "--bound", "0", "--result", result, pass_fds=[fd])
        finally:
            os.close(fd)
        self.assertEqual(r.returncode, Q.EX_BUSY, r.stderr)
        with open(result) as f:
            text = f.read().splitlines()
        self.assertIn("status=busy", text)
        self.assertIn("holder=app feature verify busyone", text)
        self.assertIn("position 1, holder is app feature verify busyone", r.stderr)
        self.assertEqual([n for n in os.listdir(d) if n.startswith("wait.")], [], "a refused run left its waiter file")
        self.assertEqual(self.status()["holder"]["name"], "busyone", "the holder was disturbed")

    def test_a_bound_of_zero_takes_a_free_slot(self):
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(fd), "--owner", str(os.getpid()), "--verb", "feature verify", "--name", "x", "--bound", "0", pass_fds=[fd])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(r.stderr, "", "nothing is printed when there was nothing to wait for")
            self.assertEqual(self.status()["holder"]["name"], "x")
            self.assertEqual(self.status()["state"], "held")
        finally:
            os.close(fd)                                    # the descriptor of the owner closes: the slot is free again
        until(lambda: self.status()["state"] == "free", "the slot to be free")

    def test_a_bound_of_zero_does_not_pass_a_run_that_is_ahead(self):
        a = self.helper("holder")
        a.taken()
        b = self.helper("ahead", "auto")
        until(lambda: self.waits(b), "the waiter file")
        a.let_go()
        b.line("rc=")
        # a free slot with a run ahead is not taken by a run that came later; the one ahead has finished by now, so the order is the test's, not a race: hold again and queue
        c = self.helper("holder2")
        c.taken()
        d = self.helper("ahead2", "auto")
        until(lambda: self.waits(d), "the waiter file")
        lock = os.open(os.path.join(self.dir, "lock"), os.O_RDONLY)
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(lock), "--owner", str(os.getpid()), "--verb", "feature verify", "--name", "late", "--bound", "0", pass_fds=[lock])
        finally:
            os.close(lock)
        self.assertEqual(r.returncode, Q.EX_BUSY)
        self.assertIn("position 2", r.stderr)


class Reentry(Base):
    """A whole-suite run started from inside the suite that holds the slot would wait for itself: it is refused at once, with no bound given."""

    def test_the_holder_is_a_parent_of_the_run_that_waits(self):
        d = Q.prepare(self.state)
        held = os.open(os.path.join(d, "lock"), os.O_RDONLY)             # the slot is held, by a descriptor of its own
        fcntl.flock(held, fcntl.LOCK_EX)
        me = Q.who(os.getppid())                                         # the holder is a parent of this test, which is the owner of the run that waits
        Q._write(os.path.join(d, Q.RECORD), dict(Q.info("app", "feature verify", "outer", "a" * 40), schema=1, pid=me["pid"], start=me["start"], started=int(time.time())))
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        result = os.path.join(self.tmp, "result")
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(fd), "--owner", str(os.getpid()), "--verb", "suite run", "--name", "inner", "--result", result,
                             pass_fds=[fd], timeout=30)
        finally:
            os.close(fd)
            os.close(held)
        self.assertEqual(r.returncode, Q.EX_REENTRY, r.stderr)
        with open(result) as f:
            text = f.read().splitlines()
        self.assertIn("status=reentry", text)
        self.assertIn("holder=app feature verify outer", text)
        self.assertEqual([n for n in os.listdir(d) if n.startswith("wait.")], [], "a refused run left its waiter file")

    def test_a_holder_that_is_no_parent_is_waited_for(self):
        self.assertNotIn(os.getpid(), Q.ancestors(os.getpid()))
        self.assertIn(os.getppid(), Q.ancestors(os.getpid()))
        a = self.helper("unrelated")
        a.taken()
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        try:
            r = self.run_cli("acquire", "--state", self.state, "--fd", str(fd), "--owner", str(os.getpid()), "--verb", "suite run", "--name", "inner", "--bound", "0", pass_fds=[fd])
        finally:
            os.close(fd)
        self.assertEqual(r.returncode, Q.EX_BUSY, r.stderr)


class Line(Base):
    """The one line of the wait, with a clock and a sleep that are the test's own."""

    def hold(self):
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_EX)
        self.holder_fd = fd
        self.addCleanup(os.close, fd)
        Q._write(os.path.join(d, Q.RECORD), dict(Q.info("app", "feature verify", "one", "b" * 40), schema=1, pid=os.getpid(), start=Q.L.token(os.getpid()), started=int(time.time()) - 125))
        return d

    def test_the_line_is_printed_once_and_again_only_when_something_changes(self):
        d = self.hold()
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        self.addCleanup(os.close, fd)
        now = [0.0]
        calls = []
        other = subprocess.Popen([sys.executable, "-I", "-c", "import time; time.sleep(60)"])      # another process that holds the slot, from the sixth poll on
        self.addCleanup(other.wait)
        self.addCleanup(other.kill)

        def sleep(seconds):
            calls.append(seconds)
            now[0] += seconds
            if len(calls) == 6:
                Q._write(os.path.join(d, Q.RECORD), dict(Q.info("app", "release verify", "two", "c" * 40), schema=1, pid=other.pid, start=Q.L.token(other.pid), started=int(time.time())))
        err = io.StringIO()
        with mock.patch.object(Q.time, "sleep", sleep):
            status, waited, holder = Q.acquire(d, fd, os.getpid(), Q.info("app", "feature verify", "waits", ""), bound=10, err=err, poll=1.0, clock=lambda: now[0])
        self.assertEqual((status, waited, holder), ("busy", 10, "app release verify two"))
        lines = err.getvalue().splitlines()
        self.assertEqual(len(lines), 2, lines)
        self.assertEqual(lines[0], "qargi: suite queue: position 1, holder is app feature verify one (running 2m)")
        self.assertTrue(lines[1].startswith("qargi: suite queue: position 1, holder is app release verify two (running "), lines[1])
        self.assertGreaterEqual(len(calls), 10)

    def test_a_wait_that_never_waited_prints_nothing_and_counts_zero(self):
        d = Q.prepare(self.state)
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        self.addCleanup(os.close, fd)
        err = io.StringIO()
        self.assertEqual(Q.acquire(d, fd, os.getpid(), Q.info("app", "feature verify", "n", ""), err=err), ("ok", 0, ""))
        self.assertEqual(err.getvalue(), "")

    def test_a_wait_counts_whole_seconds_rounded_up(self):
        d = self.hold()
        fd = os.open(os.path.join(d, "lock"), os.O_RDONLY)
        self.addCleanup(os.close, fd)
        now = [0.0]
        calls = []

        def sleep(seconds):
            calls.append(seconds)
            now[0] += 0.4
            if len(calls) == 3:                              # the holder lets go (its own description of the lock file) at the third poll
                fcntl.flock(self.holder_fd, fcntl.LOCK_UN)
        with mock.patch.object(Q.time, "sleep", sleep):
            result = Q.acquire(d, fd, os.getpid(), Q.info("app", "feature verify", "waits", ""), err=io.StringIO(), poll=0.4, clock=lambda: now[0])
        self.assertEqual(result, ("ok", 2, ""))              # 1.2 seconds waited: 2
        self.assertEqual(Q.live_holder(d)["name"], "waits")


class Status(Base):
    def test_status_of_a_queue_that_is_not_there_is_free(self):
        doc = self.status()
        self.assertEqual((doc["state"], doc["holder"], doc["waiting"]), ("free", None, []))
        self.assertFalse(os.path.exists(self.dir), "status made the directory")

    def test_status_json_lists_the_holder_and_the_waiters(self):
        a = self.helper("running")
        a.taken()
        b = self.helper("next", "auto")
        until(lambda: self.waits(b), "the waiter file")
        before = sorted(os.listdir(self.dir))
        doc = self.status()
        self.assertEqual(doc["state"], "held")
        self.assertEqual({k: doc["holder"][k] for k in ("pid", "project", "verb", "name", "head")}, {"pid": a.p.pid, "project": "app", "verb": "feature verify", "name": "running", "head": "a" * 40})
        self.assertEqual([(w["position"], w["pid"], w["name"]) for w in doc["waiting"]], [(1, b.p.pid, "next")])
        text = self.run_cli("status", "--state", self.state).stdout
        self.assertIn("suite queue: held", text)
        self.assertRegex(text, r"holder\s+app\s+feature verify\s+running\s+a{8}\s+\d+s\s+%d" % a.p.pid)
        self.assertRegex(text, r"1\s+app\s+feature verify\s+next\s+a{8}\s+\d+s\s+%d" % b.p.pid)
        self.assertEqual(sorted(os.listdir(self.dir)), before, "status changed the directory")

    def test_a_document_that_breaks_its_registry_file_is_70_with_nothing_printed(self):
        with mock.patch.object(Q, "status_data", lambda state: {"schema": 1, "kind": "qargi-suite-queue", "state": "free", "holder": None, "waiting": [{"position": "one"}]}):
            err = io.StringIO()
            out = io.StringIO()
            with mock.patch.object(sys, "stdout", out), mock.patch.object(sys, "stderr", err):
                rc = Q.main(["status", "--state", self.state, "--json"])
        self.assertEqual(rc, 70)
        self.assertEqual(out.getvalue(), "")
        self.assertIn("defect", err.getvalue())

    def test_a_field_of_a_record_is_cut_to_plain_characters(self):
        d = Q.prepare(self.state)
        me = Q.who(os.getpid())
        Q._write(os.path.join(d, Q.RECORD), {"schema": 1, "pid": me["pid"], "start": me["start"], "project": "app", "verb": "feature\x1b[31m verify", "name": "a\nb`c`$(x)", "head": "zz", "started": 1})
        rec = Q.read_holder(d)
        self.assertEqual((rec["verb"], rec["name"], rec["head"]), ("feature31m verify", "abcx", ""))

    def test_the_kind_is_registered_and_its_writes_sentence_says_nothing_is_written(self):
        reg, problems = K.load_registry(K.registry_path("qargi-suite-queue"))
        self.assertEqual(problems, [])
        self.assertTrue(reg["writes"].startswith("Nothing:"))
        self.assertEqual(reg["verbs"], ["suite status --json"])


class Verbs(Base):
    """qargi suite run and qargi suite status, started as a user starts them (bin/qargi, the state of the test)."""

    def env(self):
        return dict(os.environ, QARGI_STATE=self.state)

    def qargi(self, *args, stdin=None):
        return subprocess.run([BIN] + list(args), capture_output=True, text=True, env=self.env(), input=stdin, timeout=60)

    def run_verb(self, *args):
        h = Helper.__new__(Helper)
        h.start([BIN] + list(args), "suite run", env=self.env())
        self.helpers.append(h)
        return h

    def command(self, name):
        """A bash command that says it runs (a line in NAME.started) and waits, bounded, for the file NAME.go: ($0 is the path without the suffix)."""
        base = os.path.join(self.tmp, name)
        return base, ["bash", "-c", 'echo $$ >> "$0.started"; for _ in $(seq 1500); do [ -e "$0.go" ] && break; sleep 0.02; done', base]

    def test_run_gives_the_command_its_streams_and_returns_its_status(self):
        r = self.qargi("suite", "run", "--", "sh", "-c", "echo out; echo err >&2; exit 7")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (7, "out\n", "err\n"))
        r = self.qargi("suite", "run", "--", "cat", stdin="hello\n")
        self.assertEqual((r.returncode, r.stdout), (0, "hello\n"))
        r = self.qargi("suite", "run", "--", "echo", "--json", "--help", "-h")        # what follows -- is the command's own
        self.assertEqual((r.returncode, r.stdout), (0, "--json --help -h\n"))
        self.assertEqual(self.qargi("suite", "run", "--", "no-such-command-of-qargi").returncode, 127)
        self.assertFalse(os.path.exists(os.path.join(self.state, "history")), "suite run wrote a history")
        self.assertEqual(os.listdir(self.dir), ["lock"], "a run left a file in the queue")

    def test_the_command_has_no_descriptor_of_the_slot(self):
        r = self.qargi("suite", "run", "--", "sh", "-c", "ls -l /proc/$$/fd")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("suite-queue", r.stdout)

    def test_usage_errors_are_exit_2(self):
        for args in (("suite",), ("suite", "nope"), ("suite", "run"), ("suite", "run", "--"), ("suite", "run", "true"), ("suite", "run", "--json", "--", "true"),
                     ("suite", "status", "extra"), ("suite", "status", "--json", "x")):
            r = self.qargi(*args)
            self.assertEqual(r.returncode, 2, (args, r.stderr))
            self.assertIn("usage: qargi suite", r.stderr, args)
        for args in (("suite", "--help"), ("suite", "run", "--help"), ("suite", "status", "-h"), ("help", "suite")):
            r = self.qargi(*args)
            self.assertEqual(r.returncode, 0, (args, r.stderr))
            self.assertIn("qargi suite", r.stdout, args)

    def test_status_names_a_command_that_runs_and_the_one_that_waits(self):
        base, cmd = self.command("one")
        a = self.run_verb("suite", "run", "--", *cmd)
        until(lambda: os.path.exists(base + ".started"), "the command to start")
        doc = self.status()
        self.assertEqual((doc["state"], doc["holder"]["verb"], doc["holder"]["name"], doc["holder"]["pid"], doc["holder"]["project"], doc["holder"]["head"]),
                         ("held", "suite run", "bash", a.p.pid, None, None))
        base2, cmd2 = self.command("two")
        b = self.run_verb("suite", "run", "--", *cmd2)
        until(lambda: any("position 1, holder is suite run bash (running " in l for l in b.err), "the wait line: %r" % b.err)
        until(lambda: self.status()["waiting"], "the waiter")
        doc = self.status()
        self.assertEqual([(w["position"], w["verb"], w["name"], w["pid"]) for w in doc["waiting"]], [(1, "suite run", "bash", b.p.pid)])
        self.assertFalse(os.path.exists(base2 + ".started"), "the second command started while the first held the slot")
        text = self.qargi("suite", "status").stdout
        self.assertRegex(text, r"holder\s+-\s+suite run\s+bash\s+-\s+\d+s\s+%d" % a.p.pid)
        open(base + ".go", "w").close()
        until(lambda: os.path.exists(base2 + ".started"), "the second command to start once the first has ended")
        open(base2 + ".go", "w").close()
        for h in (a, b):
            self.assertEqual(h.p.wait(timeout=30), 0)
        self.assertEqual(self.status()["state"], "free")
        self.assertFalse(os.path.exists(os.path.join(self.state, "history")))

    def test_a_killed_run_leaves_the_slot_to_its_command_until_it_ends(self):
        base, cmd = self.command("orphan")
        a = self.run_verb("suite", "run", "--", *cmd)
        until(lambda: os.path.exists(base + ".started"), "the command to start")
        a.kill()
        a.p.wait()
        doc = self.status()
        self.assertEqual((doc["state"], doc["holder"]), ("held", None), "the command is still running, so the slot stays taken")
        open(base + ".go", "w").close()
        until(lambda: self.status()["state"] == "free", "the slot to be free once the command ended")

    def test_a_suite_run_started_from_inside_a_suite_run_is_refused_not_waited_for(self):
        r = subprocess.run([BIN, "suite", "run", "--", "sh", "-c", '"$0" suite run -- echo inner; echo "inner status $?"', BIN], capture_output=True, text=True, env=self.env(),
                           stdin=subprocess.DEVNULL, timeout=60)        # the bound of a hang is the test's own timeout
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("inner status 1", r.stdout)
        self.assertNotIn("inner\n", r.stdout.replace("inner status", ""), "the inner command ran")
        self.assertIn("would wait for itself for ever", r.stderr)
        self.assertIn("suite run sh", r.stderr, "the message names the holder")
        self.assertEqual(os.listdir(self.dir), ["lock"], "a run left a file in the queue")


if __name__ == "__main__":
    unittest.main()
