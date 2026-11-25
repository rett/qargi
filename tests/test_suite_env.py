#!/usr/bin/env python3
"""lib/suite_env.py: the declaration (problems, normalise, loosens, the id and the approved entry), the pure readers, and the launcher itself:
stage 1 against a stub systemd-run, stage 2 for real on the no-scope route under hostile parents, the two pipes of `ci-like`, the parent's
signal forwarding and cleanup, and (where systemd can make a user scope) the scope route. Offline; a scratch home; no project.
Run: python3 tests/test_suite_env.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import errno, json, os, pty, re, select, shutil, signal, subprocess, sys, tempfile, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
SCRIPT = os.path.join(LIB, "suite_env.py")
sys.path.insert(0, LIB)
import suite_env as SE  # noqa: E402

PY = [sys.executable, "-B", "-I"]
WAIT = 30                       # the longest any wait in this file takes; a deadline, never a fixed pause

# the shell stub of systemd-run: logs each call (a line CALL and then one argument per line), answers --version, and either runs what
# follows `--` (no scope is made) or fails with status 1 and no output
FAKE = """#!/bin/sh
{ echo CALL; printf '%s\\n' "$@"; } >> "$FAKE_LOG"
case $1 in --version) echo "systemd ${FAKE_VER:-255} (fake)"; exit 0;; esac
[ "${FAKE_MODE:-pass}" = fail ] && exit 1
while [ "$1" != "--" ]; do shift; done
shift
exec "$@"
"""

# what a command sees of itself, printed as JSON
INSPECT = r"""
import json, os, re, stat, sys
def fds():
    return sorted(int(n) for n in os.listdir("/proc/self/fd") if os.path.lexists("/proc/self/fd/" + n))
st = open("/proc/self/status").read()
env = [e.split(b"=", 1)[0].decode() for e in open("/proc/self/environ", "rb").read().split(b"\0") if e]
print(json.dumps({"fds": fds(), "env": sorted(env), "sid": os.getsid(0), "pid": os.getpid(),
                  "tty0": os.isatty(0), "stdin": os.readlink("/proc/self/fd/0"),
                  "sigblk": re.search(r"SigBlk:\s*(\w+)", st).group(1)}))
"""

# the descriptors the command has, written to the file named by its first argument
FDS_TO_FILE = r"""
import json, os, sys
names = os.listdir("/proc/self/fd")
found = json.dumps(sorted(int(n) for n in names if os.path.lexists("/proc/self/fd/" + n)))
open(sys.argv[1], "w").write(found)
"""

CI_INSPECT = r"""
import json, os, re, stat, subprocess, sys, time
def fds():
    return sorted(int(n) for n in os.listdir("/proc/self/fd") if os.path.lexists("/proc/self/fd/" + n))
R, W = int(sys.argv[1]), int(sys.argv[2])
out = {"fds": fds()}
for name, fd in (("r", R), ("w", W)):
    sb = os.fstat(fd)
    out[name] = {"fifo": stat.S_ISFIFO(sb.st_mode), "ino": sb.st_ino,
                 "flags": re.search(r"flags:\s*(\w+)", open("/proc/self/fdinfo/%d" % fd).read()).group(1)}
def eagain():
    try:
        return "DATA/EOF " + repr(os.read(R, 1))
    except BlockingIOError:
        return "EAGAIN"
out["read_first"] = eagain()
# hermetic: allow sleep (a pause inside the command under test: a pipe the launcher closed would read end-of-file after it)
time.sleep(0.3)
out["read_later"] = eagain()
out["write1"] = os.write(W, b"x")
sent = 0
while sent < 200000:
    sent += os.write(W, b"y" * min(65536, 200000 - sent))
out["written"] = sent
g = subprocess.run(["sh", "-c", "ls /proc/$$/fd"], close_fds=False, capture_output=True, text=True)
out["grandchild"] = sorted(int(x) for x in g.stdout.split())
print(json.dumps(out))
"""


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open("/proc/%d/stat" % pid) as f:
            return f.read().rsplit(")", 1)[1].split()[0] not in ("Z", "X")
    except OSError:
        return False


def wait_until(cond, what):
    deadline = time.monotonic() + WAIT
    while not cond():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting for " + what)
        time.sleep(0.02)


def hostile():
    """The caller of a hard case: HUP, INT and PIPE ignored, three signals blocked."""
    for s in (signal.SIGHUP, signal.SIGINT, signal.SIGPIPE):
        signal.signal(s, signal.SIG_IGN)
    signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGUSR1, signal.SIGUSR2, signal.SIGCHLD])


class Scratch(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="suite-env.")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.report = os.path.join(self.dir, "report.json")
        self.pids = []
        self.addCleanup(self.reap)

    def reap(self):
        for pid in self.pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass

    @staticmethod
    def kill_wait(proc):
        """Cleanup of a process the test started: it ends it, then waits, so a failed test does not wait for what it left running."""
        proc.kill()
        proc.wait()

    def path(self, name):
        return os.path.join(self.dir, name)

    def run_cmd(self, decl, command, waive="", extra=(), env=None, timeout=WAIT, **kw):
        """Stage 1 of the launcher, as the verb runs it; returns (CompletedProcess, report or None)."""
        cmd = PY + [SCRIPT, "run", "--decl", json.dumps(decl), "--waive", waive, "--report", self.report] + list(extra) + ["--"] + list(command)
        kw.setdefault("stdin", subprocess.DEVNULL)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env if env is not None else dict(os.environ), **kw)
        return r, SE.read_report(self.report)

    def fake_systemd(self, version="255", mode="pass"):
        d = self.path("fake-bin")
        os.makedirs(d, exist_ok=True)
        p = os.path.join(d, "systemd-run")
        with open(p, "w") as f:
            f.write(FAKE)
        os.chmod(p, 0o755)
        log = self.path("fake.log")
        env = dict(os.environ, PATH=d + os.pathsep + os.environ["PATH"], FAKE_LOG=log, FAKE_VER=version, FAKE_MODE=mode)
        return env, log

    def calls(self, log):
        if not os.path.exists(log):
            return []
        out = []
        with open(log) as f:
            lines = f.read().splitlines()
        for line in lines:
            if line == "CALL":
                out.append([])
            else:
                out[-1].append(line)
        return out


class Declaration(Scratch):
    def test_valid_declarations(self):
        for d in (None, {}, {"fds": "close"}, {"fds": "ci-like"}, {"fds": "ci-like", "ci_fds": [142, 145]}, {"fds": "ci-like", "ci_fds": [3, 4]},
                  {"fds": "ci-like", "ci_fds": [4, 3]}, {"fds": "ci-like", "ci_fds": [1023, 3]},
                  {"cpu_quota": "max"}, {"cpu_quota": None}, {"cpu_quota": "10%"}, {"cpu_quota": "12800%"}, {"cpu_quota": "200%"},
                  {"env_pass": ["LANG", "_X1"]}, {"env_set": {"EXAMPLE_OFFLINE": "1", "EMPTY": ""}},
                  {"env_pass": ["A"], "env_set": {"B": "x y"}}):
            self.assertEqual(SE.problems(d), [], d)

    def test_invalid_declarations(self):
        cases = [
            ([], "must be an object"), ("close", "must be an object"), (5, "must be an object"),
            ({"signals": "default"}, "unknown key"), ({"tty": "none"}, "unknown key"), ({"cpus": 2}, "unknown key"),
            ({"fds": "open"}, "fds:"), ({"fds": 1}, "fds:"), ({"fds": None}, "fds:"),
            ({"ci_fds": [142, 145]}, "only with fds ci-like"), ({"fds": "close", "ci_fds": [142, 145]}, "only with fds ci-like"),
            ({"fds": "ci-like", "ci_fds": [3]}, "ci_fds"), ({"fds": "ci-like", "ci_fds": [3, 4, 5]}, "ci_fds"),
            ({"fds": "ci-like", "ci_fds": [4, 4]}, "ci_fds"), ({"fds": "ci-like", "ci_fds": [2, 4]}, "ci_fds"),
            ({"fds": "ci-like", "ci_fds": [3, 1024]}, "ci_fds"), ({"fds": "ci-like", "ci_fds": [3, True]}, "ci_fds"),
            ({"fds": "ci-like", "ci_fds": ["3", "4"]}, "ci_fds"), ({"fds": "ci-like", "ci_fds": 142}, "ci_fds"),
            ({"fds": "ci-like", "ci_fds": None}, "ci_fds"),
            ({"cpu_quota": "9%"}, "cpu_quota"), ({"cpu_quota": "12801%"}, "cpu_quota"), ({"cpu_quota": "200"}, "cpu_quota"),
            ({"cpu_quota": 200}, "cpu_quota"), ({"cpu_quota": "0%"}, "cpu_quota"), ({"cpu_quota": "-5%"}, "cpu_quota"),
            ({"cpu_quota": "010%"}, "cpu_quota"), ({"cpu_quota": "MAX"}, "cpu_quota"), ({"cpu_quota": "2.5%"}, "cpu_quota"),
            ({"cpu_quota": True}, "cpu_quota"),
            ({"env_pass": "LANG"}, "env_pass"), ({"env_pass": ["1X"]}, "variable name"), ({"env_pass": ["A-B"]}, "variable name"),
            ({"env_pass": ["A", "A"]}, "twice"), ({"env_pass": [3]}, "variable name"), ({"env_pass": ["A\n"]}, "variable name"),
            ({"env_set": ["A"]}, "env_set"), ({"env_set": {"1A": "x"}}, "variable name"), ({"env_set": {"A": 1}}, "env_set"),
            ({"env_set": {"A": "x\ny"}}, "line break"), ({"env_set": {"A": "x\0y"}}, "line break"), ({"env_set": {"A": "x\ry"}}, "line break"),
            ({"env_pass": ["A"], "env_set": {"A": "1"}}, "both"),
            ({"env_pass": ["PATH"]}, "always passes"), ({"env_set": {"HOME": "/x"}}, "always passes"),
            ({"env_pass": ["QARGI_STATE"]}, "QARGI_"), ({"env_set": {"QARGI_X": "1"}}, "QARGI_"),
        ]
        for d, want in cases:
            found = SE.problems(d)
            self.assertTrue(found, d)
            self.assertTrue(any(want in line for line in found), (d, want, found))
            with self.assertRaises(SE.Invalid):
                SE.normalise(d)

    def test_cloud_binding_names_are_refused_as_run_clean_removes_them(self):
        names = SE.cloud_binding_names()
        self.assertGreaterEqual(len(names), 3, names)
        self.assertIn("QARGI_CLOUD_WORKSPACE", names)
        for n in names:
            self.assertTrue(any("cannot be declared" in p or "QARGI_" in p for p in SE.problems({"env_pass": [n]})), n)
            self.assertTrue(SE.problems({"env_set": {n: "x"}}), n)

    def test_an_unparsable_run_clean_is_a_problem_not_an_empty_list(self):
        good = "run_clean() { # x\n  local dir=$1; shift\n  (cd \"$dir\" && env -u AAA_ONE -u BBB_TWO \"$@\") 7>&-\n}\n"
        self.assertEqual(SE._parse_cloud_names(good), ("AAA_ONE", "BBB_TWO"))
        for text in ("", "other() { :; }\n", "run_clean() {\n  env --unset=AAA_ONE \"$@\"\n}\n"):
            self.assertEqual(SE._parse_cloud_names(text), (), text)
        with mock.patch.object(SE, "cloud_binding_names", return_value=()):
            for d in ({"env_pass": ["FOO"]}, {"env_set": {"FOO": "1"}}):
                found = SE.problems(d)
                self.assertTrue(any("cannot be read from lib.sh" in p for p in found), found)
            self.assertEqual(SE.problems({}), [])                       # nothing declared: nothing to compare

    def test_the_default_row(self):
        n = SE.normalise({})
        self.assertEqual(n, {"fds": "close", "cpu_quota": "max", "env_pass": [], "env_set": {}})
        self.assertEqual(SE.DEFAULT_CPU_QUOTA, "max")
        self.assertEqual(SE.normalise({"fds": "ci-like"})["ci_fds"], [142, 145])
        self.assertEqual(SE.normalise({"cpu_quota": None})["cpu_quota"], None)
        self.assertIsNone(SE.normalise(None))

    def test_the_hash_and_id_are_stable_under_key_order_and_defaults(self):
        a = {"fds": "ci-like", "ci_fds": [142, 145], "cpu_quota": "max", "env_pass": ["B", "A"], "env_set": {"Y": "1", "X": "2"}}
        b = {"env_set": {"X": "2", "Y": "1"}, "env_pass": ["A", "B"], "fds": "ci-like"}
        na, nb = SE.normalise(a), SE.normalise(b)
        self.assertEqual(na, nb)
        self.assertEqual(SE.decl_hash(na), SE.decl_hash(nb))
        self.assertEqual(SE.suite_env_id(na), SE.suite_env_id(nb))
        self.assertRegex(SE.suite_env_id(na), r"^[0-9a-f]{12}$")
        self.assertRegex(SE.decl_hash(na), r"^[0-9a-f]{64}$")
        self.assertNotEqual(SE.decl_hash(na), SE.decl_hash(SE.normalise({})))
        self.assertEqual(SE.suite_env_id(None), "")

    def test_the_id_changes_with_the_launcher_version_and_the_hash_does_not(self):
        n = SE.normalise({"fds": "ci-like"})
        before_id, before_hash = SE.suite_env_id(n), SE.decl_hash(n)
        with mock.patch.object(SE, "LAUNCHER_VERSION", SE.LAUNCHER_VERSION + 1):
            self.assertNotEqual(SE.suite_env_id(n), before_id)
            self.assertEqual(SE.decl_hash(n), before_hash)

    def test_loosens_table(self):
        q = lambda v: {"cpu_quota": v}  # noqa: E731
        plain = [
            (None, None), (None, {}), (None, {"fds": "ci-like"}), (None, q("200%")),
            ({}, {}), ({"cpu_quota": "max"}, {}),
            (q(None), q("max")), (q(None), q("200%")), (q("max"), q("200%")), (q("max"), q("10%")), (q("400%"), q("200%")),
            (q("200%"), q("200%")), (q("200%"), q("199%")),
        ]
        for old, new in plain:
            self.assertEqual(SE.loosens(old, new), (False, []), (old, new))
        loose = [
            ({}, None), (q("200%"), None), ({"fds": "ci-like"}, None),
            (q("200%"), q("max")), (q("200%"), q(None)), (q("200%"), q("400%")), (q("max"), q(None)), (q("100%"), q("101%")),
            ({}, {"fds": "ci-like"}), ({"fds": "ci-like"}, {}), ({"fds": "ci-like"}, {"fds": "ci-like", "ci_fds": [3, 4]}),
            ({}, {"env_pass": ["LANG"]}), ({"env_pass": ["LANG"]}, {}), ({"env_set": {"A": "1"}}, {"env_set": {"A": "2"}}),
            ({"env_set": {"A": "1"}}, {}),
            ({}, {"cpu_quota": "200%", "env_pass": ["LANG"]}),                        # a tighter quota does not excuse another change
            ({"cpu_quota": "max"}, {"fds": "ci-like", "cpu_quota": "100%"}),
        ]
        for old, new in loose:
            yes, why = SE.loosens(old, new)
            self.assertTrue(yes and why, (old, new))
        # the defaults spelled out are no change
        self.assertEqual(SE.loosens({}, {"fds": "close", "cpu_quota": "max", "env_pass": [], "env_set": {}}), (False, []))
        self.assertEqual(SE.loosens({"fds": "ci-like"}, {"fds": "ci-like", "ci_fds": [142, 145]}), (False, []))
        with self.assertRaises(SE.Invalid):
            SE.loosens({}, {"signals": 1})
        with self.assertRaises(SE.Invalid):
            SE.loosens({"bad": 1}, {})

    def test_the_error_codes_are_fourteen_constants(self):
        self.assertEqual(len(SE.CODES), 14)
        self.assertEqual(len({c for c in SE.CODES}), 14)
        for code, part in SE.CODES.items():
            self.assertRegex(code, r"^verify-env-[a-z-]+$")
            self.assertIn(part, (None,) + SE.PARTS)
        self.assertEqual(SE.CODE_CPU_READBACK, "verify-env-cpu-readback")
        self.assertEqual(SE.CODES[SE.CODE_NO_LOG], "tty")
        self.assertEqual(SE.CODES[SE.CODE_WAIVE_USED], None)
        self.assertEqual(SE.CODES[SE.CODE_WAIVER_DIR], None)

    def test_the_catalogue_of_refusals_lists_the_codes_of_the_table_and_no_other(self):
        """lib/refusals.json (schema 1, a map of codes, each once) holds every code of CODES, with the exit and the class of each, and (apart from the
        codes of other classes, which tests/test_refusals.py reads) no other of the class verify-environment; no code
        of a shell file of lib/ is outside CODES (so the project and flow codes, invalid, change-unapproved and the waive codes, are all in CODES and
        there is none outside it); a code with a part has a site that prints it with that part (no-log is the one code with a part that no site prints:
        the launcher never reports it, a verb dies with it); and every line of every site is in the code: its literal text between the filled-in words
        (words in capitals; the slice and the least systemd version are the code's constants) occurs in lib/gitflow.sh, lib/project.sh or lib/suite_env.py."""
        with open(os.path.join(LIB, "refusals.json")) as f:
            cat = json.load(f)
        self.assertEqual(cat["schema"], 1)
        self.assertEqual(set(cat), {"schema", "codes"})
        codes = {c: e for c, e in cat["codes"].items() if e["class"] == "verify-environment"}
        self.assertEqual(set(codes), set(SE.CODES))
        printed, corpus = set(), ""
        for name in ("gitflow.sh", "project.sh", "feature.sh", "release.sh", "suite_env.py"):
            path = os.path.join(LIB, name)
            with open(path) as f:
                text = f.read()
            if name != "suite_env.py":
                printed |= set(re.findall(r"(verify-env-[a-z]+(?:-[a-z]+)*)[:\"' ]", text))
            if name in ("gitflow.sh", "project.sh", "suite_env.py"):
                corpus += text.replace('\\"', '"')
        self.assertEqual(sorted(printed - set(SE.CODES) - {"verify-env-waivers"}), [])
        placeholder = re.compile(r"\b[A-Z][A-Z0-9_]*\b")
        for code, e in codes.items():
            self.assertEqual(set(e), {"rule", "why", "class", "exit", "status", "fields", "message", "next", "sites"}, code)   # the keys of every code (tests/test_refusals.py), and the sites of this one
            self.assertEqual((e["class"], e["exit"], e["status"]), ("verify-environment", 1, "live"), code)
            self.assertTrue(e["rule"] and e["why"] and e["sites"], code)
            part = SE.CODES[code]
            if part and code != SE.CODE_NO_LOG:
                self.assertTrue(any(s["text"].startswith("qargi: %s: %s: " % (code, part)) for s in e["sites"]), code)
            for s in e["sites"]:
                self.assertEqual(set(s), {"verbs", "text"}, code)
                self.assertTrue(s["verbs"] and all(isinstance(v, str) and v for v in s["verbs"]), (code, s))
                for line in s["text"].split("\n"):
                    rest = line[len("qargi: "):] if line.startswith("qargi: ") else line
                    if rest.startswith(code + ": "):
                        rest = rest[len(code) + 2:]
                        if part and rest.startswith(part + ": "):
                            rest = rest[len(part) + 2:]
                        elif rest.startswith("-: "):
                            rest = rest[3:]
                        elif rest.startswith("verify.environment: ") and not rest.startswith("verify.environment: the"):
                            rest = rest[len("verify.environment: "):]     # project.sh puts the problem of suite_env.py after it
                    rest = rest.replace(SE.SLICE, "SLICE").replace("%d or newer" % SE.MIN_SYSTEMD, "MINVER or newer")
                    segments = [g.strip(" '\"(),:.") for part_ in placeholder.split(rest) for g in re.split(r"\. | \(", part_)]   # a sentence or a parenthesis is one piece of the code or several
                    stem = segments[0]
                    self.assertTrue(stem or len(segments) > 1, (code, line))
                    # the one line the code builds from parts (the verb, and ' VALUE' for set only) is checked by its stem
                    built = line.startswith("plan token: TOKEN   (apply with: qargi project ")
                    for g in [stem] + ([] if built else [g for g in segments[1:] if len(g) >= 8]):
                        self.assertTrue(g in corpus, "%s: '%s' of %r is not in the code" % (code, g, line))
            self.assertEqual(len(e["sites"]), len({(tuple(s["verbs"]), s["text"]) for s in e["sites"]}), code)


class Pure(unittest.TestCase):
    def test_cgroup_path(self):
        self.assertEqual(SE.cgroup_path("0::/user.slice/a.scope\n"), "/user.slice/a.scope")
        self.assertEqual(SE.cgroup_path("0::/x/y.scope (deleted)\n"), "/x/y.scope")
        self.assertEqual(SE.cgroup_path("12:cpu:/a\n0::/b\n"), "/b")
        self.assertIsNone(SE.cgroup_path("12:cpu:/a\n1:name=systemd:/b\n"))
        self.assertIsNone(SE.cgroup_path(""))
        self.assertIsNone(SE.cgroup_path("0::relative\n"))

    def test_cpu_max_ok(self):
        self.assertTrue(SE.cpu_max_ok("max 100000\n", "max"))
        self.assertTrue(SE.cpu_max_ok("200000 100000", "200%"))
        self.assertTrue(SE.cpu_max_ok("10000 100000", "10%"))
        self.assertTrue(SE.cpu_max_ok("20000 10000", "200%"))
        self.assertTrue(SE.cpu_max_ok("12800000 100000", "12800%"))
        self.assertFalse(SE.cpu_max_ok("200000 100000", "max"))
        self.assertFalse(SE.cpu_max_ok("max 100000", "200%"))
        self.assertFalse(SE.cpu_max_ok("200000 100000", "100%"))
        self.assertFalse(SE.cpu_max_ok("100000", "100%"))
        self.assertFalse(SE.cpu_max_ok("", "max"))
        self.assertFalse(SE.cpu_max_ok("a b", "100%"))
        self.assertFalse(SE.cpu_max_ok("100 0", "100%"))
        self.assertFalse(SE.cpu_max_ok("max 100000", None))

    def test_sig_clean_masks_the_c_library_signals(self):
        self.assertEqual(SE.sig_clean(0, 0), (True, False))
        self.assertEqual(SE.sig_clean("0000000000000000", "0000000000000000"), (True, False))
        libc = (1 << 31) | (1 << 32)                    # signals 32 and 33
        self.assertEqual(SE.sig_clean(libc, 0), (True, True))
        self.assertEqual(SE.sig_clean(1 << 31, 0), (True, True))
        self.assertEqual(SE.sig_clean("%x" % libc, "0"), (True, True))
        self.assertEqual(SE.sig_clean(1 << 12, 0), (False, False))                    # SIGPIPE
        self.assertEqual(SE.sig_clean(libc | (1 << 12), 0), (False, True))
        self.assertEqual(SE.sig_clean(0, 1 << 16), (False, False))                    # SIGCHLD blocked
        self.assertEqual(SE.sig_clean(0, libc), (False, False))                       # the mask is not masked


class Approved(Scratch):
    def test_entry_roundtrip_and_mode(self):
        state = self.path("state")
        self.assertIsNone(SE.approved_get("p", state))
        e = SE.approved_set("p", {"fds": "ci-like", "env_pass": ["LANG"]}, "project-set", state, now="2026-01-02T03:04:05Z")
        self.assertEqual(e["at"], "2026-01-02T03:04:05Z")
        self.assertEqual(e["by"], "project-set")
        self.assertEqual(e["decl"], SE.decl_hash(SE.normalise({"fds": "ci-like", "env_pass": ["LANG"]})))
        self.assertEqual(SE.approved_get("p", state), e)
        path = os.path.join(state, "verify-env.json")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertEqual(os.listdir(state).count("verify-env.json"), 1)
        self.assertEqual([n for n in os.listdir(state) if n.startswith("verify-env.json.") and n != "verify-env.json.lock"], [])
        SE.approved_set("q", None, "project-unset", state)
        self.assertIsNone(SE.approved_get("q", state)["declared"])
        self.assertEqual(SE.approved_get("q", state)["decl"], SE.decl_hash(None))
        self.assertEqual(SE.approved_get("p", state), e)            # the other project's entry is kept

    def test_forget_removes_one_entry_and_keeps_the_others(self):
        """qargi project remove forgets the approved declaration of the project it removes: that entry only, atomically, mode 600; no entry is exit 1 and no write."""
        state = self.path("state")
        self.assertFalse(SE.approved_forget("p", state))             # no file: nothing made
        self.assertFalse(os.path.exists(os.path.join(state, "verify-env.json")))
        SE.approved_set("p", {"fds": "ci-like"}, "project-set", state)
        q = SE.approved_set("q", None, "project-unset", state)
        path = os.path.join(state, "verify-env.json")
        before = os.stat(path).st_mtime_ns
        self.assertFalse(SE.approved_forget("nobody", state))
        self.assertEqual(os.stat(path).st_mtime_ns, before)
        self.assertTrue(SE.approved_forget("p", state))
        self.assertIsNone(SE.approved_get("p", state))
        self.assertEqual(SE.approved_get("q", state), q)
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")
        self.assertEqual([n for n in os.listdir(state) if n.startswith("verify-env.json.") and n != "verify-env.json.lock"], [])
        self.assertFalse(SE.approved_check("p", {"fds": "ci-like"}, state)["entry"])

    def test_forget_on_the_command_line_and_on_a_damaged_file(self):
        state = self.path("state")
        SE.approved_set("p", None, "x", state)
        cmd = [sys.executable, "-I", os.path.join(LIB, "suite_env.py"), "approved", "forget", "p", "--state", state]
        self.assertEqual(subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode, 0)
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((r.returncode, r.stdout), (1, b""))
        with open(os.path.join(state, "verify-env.json"), "w") as f:
            f.write("{not json")
        r = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.assertEqual((r.returncode, r.stdout), (3, b""))
        with open(os.path.join(state, "verify-env.json")) as f:
            self.assertEqual(f.read(), "{not json")

    def test_check_compares_with_the_entry_and_no_entry_is_off(self):
        state = self.path("state")
        off = SE.approved_check("p", None, state)
        self.assertEqual((off["equal"], off["entry"]), (True, False))
        on = SE.approved_check("p", {}, state)
        self.assertEqual((on["equal"], on["entry"]), (False, False))
        self.assertEqual(on["state"], SE.decl_hash(None))
        SE.approved_set("p", {"cpu_quota": "200%"}, "project-set", state)
        self.assertTrue(SE.approved_check("p", {"cpu_quota": "200%"}, state)["equal"])
        self.assertTrue(SE.approved_check("p", {"cpu_quota": "200%", "env_pass": [], "fds": "close"}, state)["equal"])
        diff = SE.approved_check("p", None, state)
        self.assertEqual((diff["equal"], diff["entry"]), (False, True))
        self.assertNotEqual(diff["answers"], diff["state"])
        self.assertFalse(SE.approved_check("p", {"cpu_quota": "100%"}, state)["equal"])

    def test_the_entry_does_not_change_with_the_launcher_version(self):
        state = self.path("state")
        SE.approved_set("p", {"fds": "ci-like"}, "project-set", state)
        with mock.patch.object(SE, "LAUNCHER_VERSION", SE.LAUNCHER_VERSION + 7):
            self.assertTrue(SE.approved_check("p", {"fds": "ci-like"}, state)["equal"])

    def test_a_damaged_file_is_not_replaced_silently(self):
        state = self.path("state")
        os.makedirs(state)
        with open(os.path.join(state, "verify-env.json"), "w") as f:
            f.write("{not json")
        for fn in (lambda: SE.approved_get("p", state), lambda: SE.approved_set("p", None, "x", state)):
            with self.assertRaises(SystemExit) as cm:
                fn()
            self.assertEqual(cm.exception.code, 3)
        with open(os.path.join(state, "verify-env.json")) as f:
            self.assertEqual(f.read(), "{not json")

    def test_the_default_state_is_the_one_qargi_uses(self):
        state = self.path("qstate")
        with mock.patch.dict(os.environ, {"QARGI_STATE": state}):
            SE.approved_set("p", None, "x")
        self.assertTrue(os.path.exists(os.path.join(state, "verify-env.json")))


class Postconditions(Scratch):
    """The read-back checks of stage 2 run directly, where a real launch cannot be made to fail."""

    def test_check_fds_names_each_wrong_pipe(self):
        r, w1 = os.pipe()
        r1, w = os.pipe()                                           # the two ends come from two pipes, as the launcher makes them
        for fd in (r, w):
            os.set_inheritable(fd, True)
        for fd in (r, w, r1, w1):
            self.addCleanup(os.close, fd)
        os.set_blocking(r, False)
        report_fd = os.open(os.devnull, os.O_WRONLY | os.O_CLOEXEC)
        self.addCleanup(os.close, report_fd)

        def pipe_problems():
            rb = {}
            found = SE._check_fds(rb, True, [r, w], report_fd, [])
            return [p for p in found if p.startswith(("descriptor %d" % r, "descriptor %d" % w, "a read of", "descriptors"))], rb

        found, rb = pipe_problems()
        self.assertEqual(found, [])                                 # the right kind of pipe: nothing said of the two numbers
        self.assertEqual([e["read"] for e in rb["ci_fds"] if "read" in e], ["EAGAIN"])
        os.write(w1, b"x")
        found, _ = pipe_problems()
        self.assertTrue(any("gave data" in p for p in found), found)
        os.set_inheritable(w, False)
        found, _ = pipe_problems()
        self.assertTrue(any("close-on-exec" in p for p in found), found)
        os.set_inheritable(w, True)
        os.set_blocking(r, True)
        found, _ = pipe_problems()
        self.assertTrue(any("flags" in p and "expected 04000" in p for p in found), found)
        os.set_blocking(r, False)
        # a descriptor that is not a pipe, and the same pipe twice
        found = SE._check_fds({}, True, [report_fd, w], report_fd, [])
        self.assertTrue(any("is not a pipe" in p for p in found), found)
        r3, w3 = os.pipe()
        self.addCleanup(os.close, r3)
        self.addCleanup(os.close, w3)
        os.set_inheritable(w3, True)
        os.set_inheritable(r3, True)
        os.set_blocking(r3, False)
        # both numbers on the two ends of one pipe: each has the right flags for its end, only the inode rule is left to say it
        found = SE._check_fds({}, True, [r3, w3], report_fd, [])
        self.assertTrue(any("are the same pipe" in p for p in found), found)
        # an end that reads as end-of-file: its writer is gone
        r2, w2 = os.pipe()
        os.set_inheritable(r2, True)
        os.set_blocking(r2, False)
        os.close(w2)
        self.addCleanup(os.close, r2)
        found = SE._check_fds({}, True, [r2, w], report_fd, [])
        self.assertTrue(any("end-of-file" in p for p in found), found)

    def test_check_fds_flags_an_extra_descriptor_and_placement_errors(self):
        found = SE._check_fds({}, False, [], 99999, ["cannot list /proc/self/fd: boom"])
        self.assertTrue(any("boom" in p for p in found))
        self.assertTrue(any("open descriptors are" in p for p in found))     # this process has more than 0-2

    def test_check_signals_reads_the_state_of_the_process(self):
        code = ("import signal, sys\nsys.path.insert(0, %r)\nimport suite_env as SE\n"
                "signal.signal(signal.SIGHUP, signal.SIG_IGN)\nsignal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGUSR1])\n"
                "rb = {}\nbad, _ = SE._check_signals(rb)\nprint(len(bad), rb['sig_ign'], rb['sig_blk'])\n"
                "SE._reset_signals()\nrb = {}\nbad, _ = SE._check_signals(rb)\nprint(len(bad), rb['sig_ign'], rb['sig_blk'])\n" % LIB)
        r = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, timeout=WAIT, env=dict(os.environ))
        self.assertEqual(r.returncode, 0, r.stderr)
        first, second = r.stdout.splitlines()
        self.assertEqual(first.split()[0], "1")
        self.assertNotEqual(first.split()[1:], ["0", "0"])
        self.assertEqual(second, "0 0 0")

    def test_dev_tty_that_is_absent_is_not_the_expected_no_terminal(self):
        real = os.open

        def no_node(path, *a, **kw):
            if path == "/dev/tty":
                raise OSError(errno.ENOENT, "No such file or directory")
            return real(path, *a, **kw)
        with mock.patch.object(SE.os, "open", side_effect=no_node):
            rb = {}
            found = SE._check_tty(rb, None)
        self.assertEqual(rb["dev_tty_errno"], "ENOENT")
        self.assertTrue(any("expected ENXIO" in p for p in found), found)
        def no_tty(path, *a, **kw):
            if path == "/dev/tty":
                raise OSError(errno.ENXIO, "No such device or address")
            return real(path, *a, **kw)
        with mock.patch.object(SE.os, "open", side_effect=no_tty):
            rb = {}
            found = SE._check_tty(rb, None)
        self.assertEqual(rb["dev_tty_errno"], "ENXIO")
        self.assertFalse(any("/dev/tty" in p for p in found), found)

    def test_check_cpu_names_what_it_found(self):
        found = SE._check_cpu({}, "200%", "verify-env-cpu-no-user-manager")
        self.assertEqual(found[0], "verify-env-cpu-no-user-manager")
        rb = {}
        code, why = SE._check_cpu(rb, "200%", None)                 # this test process is not in a scope of ours
        self.assertEqual(code, SE.CODE_CPU_READBACK)
        self.assertIn(SE.SLICE, why)


class Cli(Scratch):
    def cli(self, *args):
        return subprocess.run(PY + [SCRIPT] + list(args), capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=WAIT)

    def test_problems_normalise_hash_id(self):
        r = self.cli("problems", '{"signals": 1, "fds": "ci-like", "ci_fds": [3, 3]}')
        self.assertEqual(r.returncode, 1)
        self.assertEqual(len(r.stdout.splitlines()), 2)
        self.assertEqual(self.cli("problems", "null").returncode, 0)
        self.assertEqual(self.cli("problems", "{}").stdout, "")
        self.assertEqual(self.cli("problems", "{nope").returncode, 2)
        n = self.cli("normalise", '{"env_pass": ["B", "A"]}')
        self.assertEqual(json.loads(n.stdout), {"fds": "close", "cpu_quota": "max", "env_pass": ["A", "B"], "env_set": {}})
        self.assertEqual(self.cli("normalise", "null").stdout.strip(), "null")
        self.assertEqual(self.cli("hash", "{}").stdout.strip(), SE.decl_hash(SE.normalise({})))
        self.assertEqual(self.cli("hash", "null").stdout.strip(), SE.decl_hash(None))
        self.assertEqual(self.cli("id", "{}").stdout.strip(), SE.suite_env_id(SE.normalise({})))
        self.assertEqual(self.cli("id", "null").stdout, "\n")
        bad = self.cli("normalise", '{"signals": 1}')
        self.assertEqual(bad.returncode, 2)
        self.assertIn("verify-env-invalid", bad.stderr)

    def test_loosens(self):
        r = self.cli("loosens", '{"cpu_quota": "200%"}', "null")
        self.assertEqual((r.returncode, r.stdout.splitlines()[0]), (0, "loosens"))
        self.assertGreaterEqual(len(r.stdout.splitlines()), 2)
        r = self.cli("loosens", '{"cpu_quota": "max"}', '{"cpu_quota": "100%"}')
        self.assertEqual((r.returncode, r.stdout), (1, "plain\n"))
        r = self.cli("loosens", "null", '{"fds": "ci-like"}')
        self.assertEqual((r.returncode, r.stdout), (1, "plain\n"))
        self.assertEqual(self.cli("loosens", "{}", '{"nope": 1}').returncode, 2)

    def test_approved_verbs(self):
        state = self.path("state")
        r = self.cli("approved", "get", "p", "--state", state)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        r = self.cli("approved", "check", "p", "null", "--state", state)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(json.loads(r.stdout), {"equal": True, "answers": SE.decl_hash(None), "state": SE.decl_hash(None), "entry": False})
        r = self.cli("approved", "check", "p", '{"fds": "ci-like"}', "--state", state)
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["entry"], False)
        r = self.cli("approved", "set", "p", '{"fds": "ci-like"}', "--by", "project-set", "--state", state)
        self.assertEqual(r.returncode, 0)
        entry = json.loads(r.stdout)
        self.assertEqual(entry["by"], "project-set")
        self.assertEqual(entry["declared"], SE.normalise({"fds": "ci-like"}))
        got = self.cli("approved", "get", "p", "--state", state)
        self.assertEqual((got.returncode, json.loads(got.stdout)), (0, entry))
        self.assertEqual(self.cli("approved", "check", "p", '{"fds": "ci-like", "ci_fds": [142, 145]}', "--state", state).returncode, 0)
        self.assertEqual(self.cli("approved", "check", "p", "null", "--state", state).returncode, 1)
        r = self.cli("approved", "set", "p", "null", "--by", "project-unset", "--state", state)
        self.assertIsNone(json.loads(r.stdout)["declared"])
        self.assertEqual(self.cli("approved", "get", "p", "--state", state).returncode, 0)
        self.assertEqual(self.cli("approved", "check", "p", "null", "--state", state).returncode, 0)
        self.assertEqual(self.cli("approved", "set", "p", '{"bad": 1}', "--by", "x", "--state", state).returncode, 2)

    def test_a_damaged_state_file_is_exit_3_in_every_approved_verb(self):
        state = self.path("state")
        os.makedirs(state)
        path = os.path.join(state, "verify-env.json")
        for content in ("{not json", "[]", '{"projects": 5}', ""):
            with open(path, "w") as f:
                f.write(content)
            for args in (("get", "p"), ("check", "p", "null"), ("check", "p", "{}"), ("set", "p", "null", "--by", "x")):
                r = self.cli("approved", args[0], *args[1:], "--state", state)
                self.assertEqual(r.returncode, 3, (content, args, r.stderr))
                self.assertIn("cannot be read", r.stderr)
                self.assertEqual(r.stdout, "")
        os.unlink(path)                                  # no file is no entry (1) and equal-to-off (0), never 3
        self.assertEqual(self.cli("approved", "get", "p", "--state", state).returncode, 1)
        self.assertEqual(self.cli("approved", "check", "p", "null", "--state", state).returncode, 0)
        self.assertEqual(self.cli("approved", "check", "p", "{}", "--state", state).returncode, 1)

    def test_any_failure_to_load_the_state_and_an_entry_that_is_no_object_are_exit_3_not_a_traceback(self):
        """RecursionError (a deeply nested file) is not a ValueError, and an interpreter that dies of it exits 1, which a caller reads as "no entry": every load failure
        is the damaged-file status instead, and so is an entry that is not an object (null, text, a list) for the project asked about."""
        state = self.path("state")
        os.makedirs(state)
        path = os.path.join(state, "verify-env.json")
        depth = 200000
        for content in ("[" * depth + "]" * depth, '{"projects": {"p": ' + "[" * depth + "]" * depth + "}}", '{"projects": {"p": null}}', '{"projects": {"p": "x"}}',
                        '{"projects": {"p": []}}', '{"projects": {"p": 3}}'):
            with open(path, "w") as f:
                f.write(content)
            for args in (("get", "p"), ("check", "p", "null"), ("check", "p", '{"fds": "close"}')):
                r = self.cli("approved", args[0], *args[1:], "--state", state)
                self.assertEqual(r.returncode, 3, (content[:40], args, r.stderr[-200:]))
                self.assertIn("cannot be read as the approved declarations", r.stderr)
                self.assertNotIn("Traceback", r.stderr)
                self.assertEqual(r.stdout, "")
        with open(path, "w") as f:                      # a damaged entry of another project does not make this one's absence a damage
            f.write('{"projects": {"p": null}}')
        r = self.cli("approved", "get", "q", "--state", state)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "", ""))
        with open(path, "w") as f:
            f.write("{}")
        with mock.patch.object(SE.json, "load", side_effect=RuntimeError("boom")):
            with self.assertRaises(SystemExit) as cm:
                SE._read_state(path)
            self.assertEqual(cm.exception.code, SE.STATE_DAMAGED)

    def test_probe_of_an_invalid_declaration_is_a_usage_error(self):
        r = self.cli("probe", "--decl", '{"signals": 1}')
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)
        self.assertIn("verify-env-invalid", r.stderr)
        self.assertEqual(r.stdout, "")
        r = self.cli("probe", "--decl", "{nope")
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("Traceback", r.stderr)

    def test_cpu_code_is_a_code_of_the_cpu_part(self):
        for code in ("verify-env-tty", "verify-env-fds", "verify-env-signals", "verify-env-invalid", "verify-env-no-log", "nonsense"):
            r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], waive="cpu", extra=["--cpu-route", "no-scope", "--cpu-code", code])
            self.assertEqual(r.returncode, 2, code)
            self.assertIn("cpu", r.stderr)
        for code in ("verify-env-cpu-no-systemd-run", "verify-env-cpu-systemd-too-old", "verify-env-cpu-no-user-manager", "verify-env-cpu-readback"):
            r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], waive="cpu", extra=["--cpu-route", "no-scope", "--cpu-code", code])
            self.assertEqual(r.returncode, 0, (code, r.stderr))
            self.assertEqual(rep["codes"], [code])

    def test_run_refuses_a_bad_call(self):
        r, rep = self.run_cmd({"fds": "close", "cpu_quota": None}, [])
        self.assertEqual(r.returncode, 2)
        self.assertIn("no command", r.stderr)
        r, rep = self.run_cmd({"cpu_quota": None}, ["true"], waive="env")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not a part", r.stderr)
        r, rep = self.run_cmd(None, ["true"])
        self.assertIn("off", r.stderr)
        self.assertEqual(r.returncode, 2)
        r, rep = self.run_cmd({"signals": 1}, ["true"])
        self.assertEqual(r.returncode, SE.REFUSED_STATUS)
        self.assertEqual(rep["refused"], ["verify-env-invalid"])
        self.assertTrue(rep["complete"])
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], extra=["--cpu-route", "no-scope"])
        self.assertEqual(r.returncode, 2)
        self.assertIn("--cpu-code", r.stderr)


class Stage2(Scratch):
    """Stage 2 for real, on the no-scope route (cpu_quota null), under parents that try to leak their state."""

    def inspect(self, decl, hostile_parent=False, **kw):
        fds = []
        if hostile_parent:
            fds = [os.open(os.devnull, os.O_RDONLY) for _ in range(7)]
            for fd in fds:
                os.set_inheritable(fd, True)
            kw.update(pass_fds=fds, restore_signals=False, preexec_fn=hostile)
            master, slave = pty.openpty()
            kw["stdin"] = slave
            self.addCleanup(os.close, master)
            self.addCleanup(os.close, slave)
        try:
            env = {"PATH": os.environ["PATH"], "HOME": os.environ["HOME"], "LANG": "C.UTF-8", "QARGI_STATE": "/nope", "SECRET_TOKEN": "x",
                   "CI": "true", "EMPTY": ""}
            env.update({"NOISE_%d" % i: "v" * 50 for i in range(60)})
            r, rep = self.run_cmd(decl, [sys.executable, "-I", "-c", INSPECT], env=env, **kw)
        finally:
            for fd in fds:
                os.close(fd)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), rep

    def test_a_clean_state_under_a_hostile_parent(self):
        for decl in ({"cpu_quota": None}, {"cpu_quota": None, "fds": "ci-like"}):
            out, rep = self.inspect(decl, hostile_parent=True)
            ci = decl.get("fds") == "ci-like"
            self.assertEqual(out["fds"], [0, 1, 2] + ([142, 145] if ci else []), decl)
            self.assertEqual(out["stdin"], os.devnull)
            self.assertFalse(out["tty0"])
            self.assertEqual(out["sigblk"].strip("0") or "0", "0")
            self.assertEqual(out["sid"], out["pid"])                 # a session of its own
            self.assertNotEqual(out["sid"], os.getsid(0))
            self.assertEqual(rep["parts"], {"signals": "applied", "fds": "applied", "tty": "applied", "cpu": "off", "env": "applied"})
            self.assertEqual(rep["readback"]["sig_ign"], "0")
            self.assertEqual(rep["readback"]["sig_blk"], "0")
            self.assertEqual(rep["readback"]["dev_tty_errno"], "ENXIO")
            self.assertEqual(rep["readback"]["fds"], [0, 1, 2, 3] + ([142, 145] if ci else []))      # the report took the lowest free number
            self.assertEqual(rep["cleanup"], "pgroup")
            self.assertTrue(rep["complete"])
            self.assertEqual(rep["exit"], 0)
            self.assertEqual(rep["refused"] if "refused" in rep else [], [])

    def test_the_environment_is_built_from_nothing(self):
        out, rep = self.inspect({"cpu_quota": None, "env_pass": ["LANG", "NOT_SET_HERE"], "env_set": {"EXAMPLE_OFFLINE": "1", "CI": "true"}},
                                hostile_parent=True)
        self.assertEqual(out["env"], sorted(["PATH", "HOME", "LANG", "EXAMPLE_OFFLINE", "CI"]))
        self.assertEqual(rep["readback"]["env_names"], out["env"])
        self.assertEqual(rep["readback"]["env_pass_unset"], ["NOT_SET_HERE"])
        out, rep = self.inspect({"cpu_quota": None})
        self.assertEqual(out["env"], ["HOME", "PATH"])
        self.assertNotIn("v" * 50, json.dumps(rep))              # values are never recorded
        self.assertNotIn("SECRET_TOKEN", json.dumps(rep))

    def test_the_path_is_the_clean_one(self):
        env = dict(os.environ, PATH=":.:rel/bin:" + os.environ["PATH"])
        r, rep = self.run_cmd({"cpu_quota": None}, ["sh", "-c", "echo $PATH"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), ":".join(p for p in env["PATH"].split(":") if p.startswith("/")))
        for entry in r.stdout.strip().split(":"):
            self.assertTrue(entry.startswith("/"), entry)

    def test_the_two_pipes_on_other_numbers(self):
        for numbers in ([3, 4], [4, 3], [5, 3], [3, 1023]):
            decl = {"cpu_quota": None, "fds": "ci-like", "ci_fds": numbers}
            out, rep = self.inspect(decl, hostile_parent=True)
            self.assertEqual(out["fds"], sorted([0, 1, 2] + numbers), numbers)
            self.assertEqual(rep["parts"]["fds"], "applied", numbers)
            rb = rep["readback"]
            self.assertEqual([e["fd"] for e in rb["ci_fds"]], numbers)
            self.assertEqual(rb["ci_fds"][0]["read"], "EAGAIN")
            report_fd = [fd for fd in rb["fds"] if fd not in (0, 1, 2) + tuple(numbers)]
            self.assertEqual(len(report_fd), 1, rb["fds"])
            self.assertEqual(report_fd[0], min(set(range(3, 10)) - set(numbers)))      # the report takes the lowest free number

    def test_the_pipes_near_the_top_of_a_soft_limit_of_1024(self):
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)

        def limit():
            resource.setrlimit(resource.RLIMIT_NOFILE, (1024, hard))
        for numbers in ([3, 1023], [1023, 3], [1022, 1023], [1023, 1022], [4, 1023]):
            decl = {"cpu_quota": None, "fds": "ci-like", "ci_fds": numbers}
            r, rep = self.run_cmd(decl, [sys.executable, "-I", "-c", FDS_TO_FILE, self.path("fds")], preexec_fn=limit)
            self.assertEqual(r.returncode, 0, (numbers, r.stderr))
            with open(self.path("fds")) as f:
                self.assertEqual(json.load(f), sorted([0, 1, 2] + numbers), numbers)
            self.assertEqual(rep["parts"]["fds"], "applied", numbers)
            self.assertEqual(rep["readback"]["ci_fds"][0]["read"], "EAGAIN")

    def test_a_caller_with_many_descriptors_open(self):
        """The parent's own pipe and pidfd sit above 1023 when the caller leaves that many open: select() cannot watch them."""
        import resource
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        if hard < 1400:
            print("expected: the many-descriptors case did not run: the hard limit on descriptors is %d" % hard, file=sys.stderr)
            return
        null = os.open(os.devnull, os.O_RDONLY)
        self.addCleanup(os.close, null)

        def crowd():
            resource.setrlimit(resource.RLIMIT_NOFILE, (1400, hard))
            for n in range(4, 1100):
                os.dup2(null, n)
        r, rep = self.run_cmd({"cpu_quota": None, "fds": "ci-like"}, ["sh", "-c", "echo ready"], preexec_fn=crowd, close_fds=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Traceback", r.stderr)
        self.assertEqual((rep["complete"], rep["parts"]["fds"]), (True, "applied"))

    def test_a_noisy_parent_with_plain_close(self):
        out, rep = self.inspect({"cpu_quota": None, "fds": "close"}, hostile_parent=True)
        self.assertEqual(out["fds"], [0, 1, 2])
        self.assertNotIn("ci_fds", rep["readback"])

    def test_close_and_ci_like_fds_as_the_command_sees_them(self):
        cmd = [sys.executable, "-I", "-c", FDS_TO_FILE, self.path("fds")]
        for fds, want in (("close", [0, 1, 2]), ("ci-like", [0, 1, 2, 142, 145])):
            r, rep = self.run_cmd({"cpu_quota": None, "fds": fds}, cmd)
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(self.path("fds")) as f:
                self.assertEqual(json.load(f), want, fds)
            self.assertEqual(rep["parts"]["fds"], "applied")

    def test_a_caller_with_standard_descriptors_closed(self):
        for closed in ((0,), (1,), (2,), (0, 1, 2)):
            def close_them(closed=closed):
                for fd in closed:
                    os.close(fd)
            r = subprocess.run(PY + [SCRIPT, "run", "--decl", json.dumps({"cpu_quota": None, "fds": "ci-like"}), "--waive", "", "--report", self.report,
                                     "--", sys.executable, "-I", "-c", FDS_TO_FILE, self.path("fds")],
                               stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=WAIT, preexec_fn=close_them,
                               env=dict(os.environ))
            self.assertEqual(r.returncode, 0, (closed, r.stderr))
            with open(self.path("fds")) as f:
                self.assertEqual(json.load(f), [0, 1, 2, 142, 145], closed)
            rep = SE.read_report(self.report)
            self.assertEqual(rep["parts"]["fds"], "applied", closed)
            self.assertEqual(rep["readback"]["ci_fds"][0]["read"], "EAGAIN")

    def ci_run(self, numbers=None, timeout=WAIT):
        decl = {"cpu_quota": None, "fds": "ci-like"}
        if numbers:
            decl["ci_fds"] = numbers
        rd, wr = numbers or SE.DEFAULT_CI_FDS
        r, rep = self.run_cmd(decl, [sys.executable, "-I", "-c", CI_INSPECT, str(rd), str(wr)], timeout=timeout)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout), rep

    def test_ci_like_pipes_as_the_command_inspects_itself(self):
        out, rep = self.ci_run()
        self.assertEqual(out["fds"], [0, 1, 2, 142, 145])           # no 255, no jobserver pair, no report descriptor
        self.assertTrue(out["r"]["fifo"] and out["w"]["fifo"])
        self.assertEqual((out["r"]["flags"], out["w"]["flags"]), ("04000", "01"))
        self.assertNotEqual(out["r"]["ino"], out["w"]["ino"])
        self.assertEqual(out["read_first"], "EAGAIN")
        self.assertEqual(out["read_later"], "EAGAIN")                # never end-of-file, not after a pause either
        self.assertEqual(out["write1"], 1)
        self.assertEqual(out["written"], 200000)                    # the parent drains: a full pipe does not block the suite
        self.assertIn(142, out["grandchild"])                       # neither is close-on-exec
        self.assertIn(145, out["grandchild"])
        self.assertEqual(rep["readback"]["ci_fds"], [
            {"fd": 142, "kind": "pipe", "end": "read", "flags": "04000", "cloexec": False, "read": "EAGAIN"},
            {"fd": 145, "kind": "pipe", "end": "write", "flags": "01", "cloexec": False}])

    def test_a_write_to_the_pipe_never_ends_the_suite(self):
        script = "echo x >&145; echo write=$?; grep -E '^SigIgn' /proc/self/status; echo more >&145; echo again=$?"
        r, rep = self.run_cmd({"cpu_quota": None, "fds": "ci-like"}, ["bash", "-c", script])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("write=0", r.stdout)
        self.assertIn("again=0", r.stdout)
        self.assertRegex(r.stdout, r"SigIgn:\s0+\n")                 # SIGPIPE stays at its default

    def test_the_parent_holds_no_pipe_end_afterwards(self):
        r, rep = self.run_cmd({"cpu_quota": None, "fds": "ci-like"},
                              ["sh", "-c", "readlink /proc/self/fd/142; readlink /proc/self/fd/145; sleep 120 >/dev/null 2>&1 & echo $! > " + self.path("pid")])
        self.assertEqual(r.returncode, 0, r.stderr)
        pipes = [x for x in r.stdout.split() if x.startswith("pipe:[")]
        self.assertEqual(len(pipes), 2, r.stdout)
        with open(self.path("pid")) as f:
            self.pids.append(int(f.read()))
        wait_until(lambda: not alive(self.pids[-1]), "the leftover to be killed")
        held = []
        for pid in [n for n in os.listdir("/proc") if n.isdigit()]:
            try:
                for fd in os.listdir("/proc/%s/fd" % pid):
                    if os.readlink("/proc/%s/fd/%s" % (pid, fd)) in pipes:
                        held.append((pid, fd))
            except OSError:
                pass
        self.assertEqual(held, [])

    def terminal_output(self, waive):
        """Run `touch MARKER` with a terminal as its standard output: the tty part cannot be applied. Returns (CompletedProcess, report)."""
        master, slave = pty.openpty()
        self.addCleanup(os.close, master)
        cmd = PY + [SCRIPT, "run", "--decl", '{"cpu_quota": null}', "--waive", waive, "--report", self.report, "--", "touch", self.path("ran")]
        try:
            r = subprocess.run(cmd, stdin=subprocess.DEVNULL, stdout=slave, stderr=subprocess.PIPE, text=True, timeout=WAIT, env=dict(os.environ))
        finally:
            os.close(slave)
        return r, SE.read_report(self.report)

    def test_a_refused_part_writes_a_report_and_does_not_run_the_command(self):
        r, rep = self.terminal_output("")
        self.assertEqual(r.returncode, SE.REFUSED_STATUS, r.stderr)
        self.assertEqual(rep["refused"], ["verify-env-tty"])
        self.assertEqual(rep["parts"], {"signals": "applied", "fds": "applied", "tty": "refused", "cpu": "off", "env": "applied"})
        self.assertFalse(os.path.exists(self.path("ran")))
        self.assertIn("verify-env-tty", r.stderr)
        self.assertEqual(rep["details"][0]["part"], "tty")
        self.assertIn("terminal", rep["details"][0]["found"])
        self.assertEqual((rep["exit"], rep["complete"]), (SE.REFUSED_STATUS, True))

    def test_a_waived_part_that_fails_is_recorded_and_the_command_runs(self):
        r, rep = self.terminal_output("tty")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.path("ran")))
        self.assertEqual(rep["parts"]["tty"], "waived-failed")
        self.assertEqual(rep["codes"], ["verify-env-tty"])
        self.assertNotIn("refused", rep)
        self.assertIn("warning", r.stderr)
        self.assertEqual(rep["waived"], ["tty"])
        # a waiver for another part does not cover it
        os.unlink(self.path("ran"))
        r, rep = self.terminal_output("signals")
        self.assertEqual((r.returncode, rep["refused"]), (SE.REFUSED_STATUS, ["verify-env-tty"]))
        self.assertEqual(rep["parts"]["signals"], "applied")                # the waiver is for a part that did not fail: it is applied
        self.assertFalse(os.path.exists(self.path("ran")))

    def test_the_commands_exit_status_and_a_missing_command(self):
        r, rep = self.run_cmd({"cpu_quota": None}, ["sh", "-c", "exit 7"])
        self.assertEqual((r.returncode, rep["exit"], rep["complete"]), (7, 7, True))
        r, rep = self.run_cmd({"cpu_quota": None}, ["sh", "-c", "kill -TERM $$"])
        self.assertEqual((r.returncode, rep["exit"]), (128 + signal.SIGTERM, 128 + signal.SIGTERM))
        r, rep = self.run_cmd({"cpu_quota": None}, ["no-such-command-here"])
        self.assertEqual(r.returncode, 127)
        self.assertIn("not found", r.stderr)
        self.assertTrue(rep["complete"])

    def test_the_standard_output_and_error_are_the_callers(self):
        r, rep = self.run_cmd({"cpu_quota": None}, ["sh", "-c", "echo out; echo err >&2"])
        self.assertEqual(r.stdout, "out\n")
        self.assertEqual(r.stderr, "err\n")


class Parent(Scratch):
    """The parent of stage 2: signal forwarding and cleanup, on the process-group route."""

    def start(self, script, decl=None, **kw):
        cmd = PY + [SCRIPT, "run", "--decl", json.dumps(decl or {"cpu_quota": None}), "--waive", "", "--report", self.report, "--",
                    "bash", "-c", script]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ), **kw)
        self.pids.append(p.pid)
        self.addCleanup(self.kill_wait, p)
        self.addCleanup(lambda: p.stdout.close())
        self.addCleanup(lambda: p.stderr.close())
        return p

    def ready(self, p):
        r, _, _ = select.select([p.stdout], [], [], WAIT)
        self.assertTrue(r, "the command did not print ready")
        self.assertEqual(p.stdout.readline().strip(), "ready")

    def test_term_is_forwarded_and_an_ignored_hup_is_not(self):
        hup = self.path("hup")
        script = "trap 'echo term; exit 7' TERM; trap 'touch %s' HUP; echo ready; while :; do sleep 0.1; done" % hup
        p = self.start(script, preexec_fn=hostile, restore_signals=False)
        self.ready(p)
        p.send_signal(signal.SIGHUP)                                # ignored on entry: neither handled nor forwarded
        p.send_signal(signal.SIGINT)                                # ignored on entry too
        p.send_signal(signal.SIGTERM)                               # forwarded; the command's trap answers
        out, err = p.communicate(timeout=WAIT)
        self.assertEqual(p.returncode, 7, err)
        self.assertIn("term", out)
        self.assertFalse(os.path.exists(hup))
        rep = SE.read_report(self.report)
        self.assertEqual((rep["exit"], rep["complete"]), (7, True))
        self.assertEqual(rep["readback"]["sig_ign"], "0")           # the suite itself still gets the default HUP

    def test_a_hup_that_is_not_ignored_is_forwarded(self):
        hup = self.path("hup")
        script = "trap 'touch %s; exit 9' HUP; echo ready; while :; do sleep 0.1; done" % hup
        p = self.start(script)
        self.ready(p)
        p.send_signal(signal.SIGHUP)
        p.communicate(timeout=WAIT)
        self.assertEqual(p.returncode, 9)
        self.assertTrue(os.path.exists(hup))

    def test_a_leftover_is_listed_and_killed(self):
        script = "sleep 120 >/dev/null 2>&1 & echo $! > %s; echo ready" % self.path("leftover")
        p = self.start(script)
        out, err = p.communicate(timeout=WAIT)
        self.assertEqual(p.returncode, 0, err)
        with open(self.path("leftover")) as f:
            pid = int(f.read())
        self.pids.append(pid)
        rep = SE.read_report(self.report)
        self.assertIn({"pid": pid, "comm": "sleep"}, rep["leftovers"])
        self.assertEqual(rep["survivors"], [])
        self.assertIn("left running", err)
        wait_until(lambda: not alive(pid), "the leftover to be gone")

    def test_no_leftover_is_an_empty_list(self):
        p = self.start("echo ready")
        p.communicate(timeout=WAIT)
        rep = SE.read_report(self.report)
        self.assertEqual((rep["leftovers"], rep["survivors"]), ([], []))

    def test_only_the_process_group_is_cleaned_without_a_scope(self):
        """A bystander in the caller's own cgroup and process group is never touched: cleanup without a scope is by the child's group."""
        by = subprocess.Popen(["sleep", "120"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pids.append(by.pid)
        self.addCleanup(self.kill_wait, by)
        p = self.start("echo ready")
        p.communicate(timeout=WAIT)
        self.assertTrue(alive(by.pid))


class StubSystemd(Scratch):
    """Stage 1 on the scope route against the stub: the argv it executes, and what each refusal looks like."""

    def test_the_exact_argv_and_nothing_of_the_command(self):
        env, log = self.fake_systemd()
        marker = "${VERIFY_X} $(touch %s) `x` ; --evil" % self.path("injected")
        r, rep = self.run_cmd({"cpu_quota": "200%", "env_set": {"A": "$(touch %s)" % self.path("injected2")}}, ["sh", "-c", "echo '%s'" % marker],
                              waive="cpu", env=env)
        calls = self.calls(log)
        self.assertEqual(calls[0], ["--version"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1], ["--user", "--scope", "--quiet", "--collect", "--expand-environment=no", "--slice=qargi-verify.slice",
                                    "-p", "CPUQuota=200%", "--", sys.executable, "-B", "-I", SCRIPT, "stage2", "--job-fd", "3"])
        self.assertEqual(r.stdout.strip(), marker)                  # the command went through as text
        self.assertFalse(os.path.exists(self.path("injected")))
        self.assertFalse(os.path.exists(self.path("injected2")))

    def test_max_uses_the_weight(self):
        env, log = self.fake_systemd()
        self.run_cmd({}, ["true"], waive="cpu", env=env)
        self.assertEqual(self.calls(log)[1][7], "CPUWeight=100")
        self.assertEqual(self.calls(log)[1][6], "-p")

    def test_the_fake_scope_is_not_a_scope_so_the_readback_refuses(self):
        env, log = self.fake_systemd()
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], env=env)
        self.assertEqual(r.returncode, SE.REFUSED_STATUS, r.stderr)
        self.assertEqual(rep["refused"], ["verify-env-cpu-readback"])
        self.assertEqual(rep["parts"]["cpu"], "refused")
        self.assertEqual(rep["parts"]["fds"], "applied")
        self.assertIn(SE.SLICE, rep["details"][0]["found"])
        self.assertFalse(os.path.exists(self.path("ran")))
        self.assertEqual(rep["cleanup"], "pgroup")                  # never the cgroup of a process that is not in a scope of ours

    def test_a_waived_cpu_that_fails_runs_and_records_it(self):
        env, log = self.fake_systemd()
        by = subprocess.Popen(["sleep", "120"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.pids.append(by.pid)
        self.addCleanup(self.kill_wait, by)
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], waive="cpu", env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(self.path("ran")))
        self.assertEqual(rep["parts"]["cpu"], "waived-failed")
        self.assertEqual(rep["codes"], ["verify-env-cpu-readback"])
        self.assertEqual(rep["waived"], ["cpu"])
        self.assertTrue(alive(by.pid))                              # the bystander of the caller's own cgroup is untouched
        self.assertIn("warning", r.stderr)

    def test_an_old_systemd_refuses_before_any_exec(self):
        env, log = self.fake_systemd(version="253")
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], waive="cpu", env=env)
        self.assertEqual(r.returncode, SE.REFUSED_STATUS)
        self.assertEqual(rep["refused"], ["verify-env-cpu-systemd-too-old"])
        self.assertTrue(rep["complete"])
        self.assertEqual(self.calls(log), [["--version"]])
        self.assertFalse(os.path.exists(self.path("ran")))
        for v in ("254", "255"):
            env, log = self.fake_systemd(version=v)
            r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], waive="cpu", env=env)
            self.assertEqual(r.returncode, 0, (v, r.stderr))

    def test_no_systemd_run_refuses(self):
        env = dict(os.environ, PATH=self.dir)
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], env=env)
        self.assertEqual(r.returncode, SE.REFUSED_STATUS)
        self.assertEqual(rep["refused"], ["verify-env-cpu-no-systemd-run"])
        self.assertEqual(rep["details"][0]["part"], "cpu")

    def test_no_user_manager_leaves_no_report(self):
        env, log = self.fake_systemd(mode="fail")
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], waive="cpu", env=env)
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(rep)                                      # the verdict is read from the report: none, so never a test failure
        self.assertFalse(os.path.exists(self.path("ran")))

    def test_the_no_scope_route_never_calls_systemd_run(self):
        env, log = self.fake_systemd()
        code = "verify-env-cpu-no-user-manager"
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], waive="cpu", env=env,
                              extra=["--cpu-route", "no-scope", "--cpu-code", code])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(log), [])
        self.assertEqual(rep["parts"]["cpu"], "waived-failed")
        self.assertEqual(rep["codes"], [code])
        self.assertEqual(rep["cleanup"], "pgroup")
        os.unlink(self.path("ran"))
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["touch", self.path("ran")], env=env, extra=["--cpu-route", "no-scope", "--cpu-code", code])
        self.assertEqual(r.returncode, SE.REFUSED_STATUS)
        self.assertEqual(rep["refused"], [code])
        self.assertFalse(os.path.exists(self.path("ran")))
        self.assertEqual(self.calls(log), [])

    def test_a_failed_scope_run_after_a_passing_one_leaves_no_stale_report(self):
        env, log = self.fake_systemd(mode="fail")
        r, rep = self.run_cmd({"cpu_quota": None}, ["true"], env=env)         # a passing run writes a complete report at the path
        self.assertEqual((r.returncode, rep["complete"]), (0, True))
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["false"], env=env)      # the same path; the scope cannot be made
        self.assertEqual(r.returncode, 1)
        self.assertIsNone(rep, "the first run's report stands for the second")
        self.assertFalse(os.path.exists(self.report))
        # a refusal of stage 1 replaces it too
        r, rep = self.run_cmd({"cpu_quota": None}, ["true"], env=env)
        self.assertTrue(rep["complete"])
        r, rep = self.run_cmd({"cpu_quota": "200%"}, ["true"], env=dict(os.environ, PATH=self.dir))
        self.assertEqual(rep["refused"], ["verify-env-cpu-no-systemd-run"])

    def test_a_null_quota_is_the_no_scope_route(self):
        env, log = self.fake_systemd()
        r, rep = self.run_cmd({"cpu_quota": None}, ["true"], env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(log), [])
        self.assertEqual(rep["parts"]["cpu"], "off")

    def probe(self, decl, env):
        r = subprocess.run(PY + [SCRIPT, "probe", "--decl", json.dumps(decl)], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                           timeout=WAIT, env=env)
        return r.returncode, json.loads(r.stdout)

    def test_probe_reports_each_refusal(self):
        env, log = self.fake_systemd()
        rc, out = self.probe({"cpu_quota": "200%"}, env)
        self.assertEqual(rc, 1)
        self.assertEqual(out["refused"], ["verify-env-cpu-readback"])
        self.assertEqual(out["route"], "scope")
        self.assertEqual(out["details"][0]["part"], "cpu")
        env, log = self.fake_systemd(version="253")
        rc, out = self.probe({}, env)
        self.assertEqual((rc, out["refused"]), (1, ["verify-env-cpu-systemd-too-old"]))
        env, log = self.fake_systemd(mode="fail")
        rc, out = self.probe({"cpu_quota": "100%"}, env)
        self.assertEqual((rc, out["refused"]), (1, ["verify-env-cpu-no-user-manager"]))
        self.assertIn("nothing was reported", out["details"][0]["found"])
        rc, out = self.probe({}, dict(os.environ, PATH=self.dir))
        self.assertEqual((rc, out["refused"]), (1, ["verify-env-cpu-no-systemd-run"]))

    def test_probe_of_a_declaration_without_a_scope(self):
        env, log = self.fake_systemd()
        rc, out = self.probe({"cpu_quota": None, "fds": "ci-like"}, env)
        self.assertEqual((rc, out["ok"], out["refused"], out["route"]), (0, True, [], "no-scope"))
        self.assertEqual(out["parts"]["cpu"], "off")
        self.assertEqual(self.calls(log), [])


def scope_works():
    """(True, version) when a user scope with a quota can be made here and systemd is new enough, else (False, why)."""
    exe = shutil.which("systemd-run")
    if not exe:
        return False, "no systemd-run"
    v = subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.split()
    if len(v) < 2 or not v[1].isdigit() or int(v[1]) < SE.MIN_SYSTEMD:
        return False, "systemd-run %s is older than %d" % (" ".join(v[:2]) or "unknown", SE.MIN_SYSTEMD)
    r = subprocess.run([exe, "--user", "--scope", "--quiet", "--collect", "--slice=" + SE.SLICE, "-p", "CPUQuota=200%", "--", "true"], capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, timeout=60)
    if r.returncode != 0:
        return False, "no user scope can be made (%s)" % ((r.stderr.strip().splitlines() or ["status %d" % r.returncode])[-1])
    return True, v[1]


class RealScope(Scratch):
    def test_the_scope_route_for_real(self):
        ok, why = scope_works()
        if not ok:
            print("expected: the real-scope case did not run: %s" % why, file=sys.stderr)
            return
        systemd_version = int(why)
        sess = ("echo '${VERIFY_X}' pid=$$; cat /proc/self/cgroup; "
                "setsid bash -c 'echo $$ > %s; exec sleep 300' >/dev/null 2>&1 & "
                "while [ ! -s %s ]; do :; done" % (self.path("lpid"), self.path("lpid")))
        for decl, cpu_max, weight in (({"cpu_quota": "200%"}, "200000 100000", None), ({"cpu_quota": "max"}, "max 100000", "100"),
                                       ({}, "max 100000", "100"), ({"cpu_quota": "50%", "fds": "ci-like"}, "50000 100000", None)):
            if os.path.exists(self.path("lpid")):
                os.unlink(self.path("lpid"))
            r, rep = self.run_cmd(decl, ["bash", "-c", sess], env=dict(os.environ, VERIFY_X="expanded"), preexec_fn=hostile, restore_signals=False)
            self.assertEqual(r.returncode, 0, (decl, r.stderr))
            self.assertIn("${VERIFY_X} pid=", r.stdout)
            self.assertRegex(r.stdout, r"pid=\d+")
            self.assertEqual(rep["parts"], {"signals": "applied", "fds": "applied", "tty": "applied", "cpu": "applied", "env": "applied"}, decl)
            rb = rep["readback"]
            self.assertEqual(rb["cpu_max"], cpu_max, decl)
            if weight:
                self.assertEqual(rb["cpu_weight"], weight)
            self.assertIn(SE.SLICE, rb["cgroup"].split("/"))
            self.assertTrue(rb["cgroup"].endswith(".scope"))
            self.assertIn(rb["cgroup"], r.stdout)                  # the command ran in that cgroup
            self.assertEqual(rep["cleanup"], "cgroup")
            self.assertEqual(rb["systemd"], systemd_version)
            with open(self.path("lpid")) as f:
                pid = int(f.read())
            self.pids.append(pid)
            self.assertIn(pid, [x["pid"] for x in rep["leftovers"]], rep["leftovers"])     # a setsid child is reached through the scope
            self.assertEqual(rep["survivors"], [])
            wait_until(lambda: not alive(pid), "the setsid leftover to be killed")
            self.assertTrue(rep["complete"])

    def test_term_reaches_a_setsid_child_through_the_scope(self):
        ok, why = scope_works()
        if not ok:
            print("expected: the real-scope signal case did not run: %s" % why, file=sys.stderr)
            return
        got, spid = self.path("got"), self.path("spid")
        # the child of its own session records TERM; the command itself waits for that record (at most a few seconds) before it ends, so
        # the cleanup that follows cannot kill the child before it has answered
        script = ("setsid bash -c 'trap \"touch %s; exit 0\" TERM; echo $$ > %s; sleep 300 & wait' >/dev/null 2>&1 & "
                  "while [ ! -s %s ]; do :; done; "
                  "trap 'i=0; while [ ! -e %s ] && [ $i -lt 5000 ]; do i=$((i+1)); sleep 0.001; done; exit 0' TERM; echo ready; wait"
                  % (got, spid, spid, got))
        cmd = PY + [SCRIPT, "run", "--decl", '{"cpu_quota": "max"}', "--waive", "", "--report", self.report, "--", "bash", "-c", script]
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=dict(os.environ))
        self.pids.append(p.pid)
        self.addCleanup(self.kill_wait, p)
        self.addCleanup(p.stdout.close)
        self.addCleanup(p.stderr.close)
        r, _, _ = select.select([p.stdout], [], [], WAIT)
        self.assertTrue(r)
        self.assertEqual(p.stdout.readline().strip(), "ready")
        with open(spid) as f:
            self.pids.append(int(f.read()))
        p.send_signal(signal.SIGTERM)
        p.communicate(timeout=WAIT)
        self.assertTrue(os.path.exists(got), "the child of its own session did not get TERM")
        wait_until(lambda: not alive(self.pids[-1]), "the child to be gone")


# the nested case: a launcher run (here with a stub systemd-run, so no scope of its own is made) inside a verify scope of an outer run. The
# inner launcher must not take the outer run's scope for its own: a bystander of the outer scope is never signalled or killed.
NESTED = r"""
import os, subprocess, sys
d, script = sys.argv[1], sys.argv[2]
by = subprocess.Popen(["sleep", "120"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
open(os.path.join(d, "bypid"), "w").write(str(by.pid))
for name, waive in (("waived", "cpu"), ("plain", "")):
    r = subprocess.run([sys.executable, "-I", script, "run", "--decl", '{"cpu_quota": "max"}', "--waive", waive,
                        "--report", os.path.join(d, "report-" + name), "--", "true"],
                       stdin=subprocess.DEVNULL, capture_output=True, text=True)
    open(os.path.join(d, "rc-" + name), "w").write(str(r.returncode))
open(os.path.join(d, "after"), "w").write("alive")
"""


class Nested(Scratch):
    def test_an_enclosing_scope_is_never_the_launchers_own(self):
        ok, why = scope_works()
        if not ok:
            print("expected: the nested-scope case did not run: %s" % why, file=sys.stderr)
            return
        env, log = self.fake_systemd()
        script = self.path("nested.py")
        with open(script, "w") as f:
            f.write(NESTED)
        # the outer scope is the real one (the real systemd-run, by its path); inside it the inner launcher finds the stub first on PATH
        outer = [shutil.which("systemd-run"), "--user", "--scope", "--quiet", "--collect", "--slice=" + SE.SLICE, "--",
                 sys.executable, "-I", script, self.dir, SCRIPT]
        r = subprocess.run(outer, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=WAIT * 2, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.path("bypid")) as f:
            by = int(f.read())
        self.pids.append(by)
        self.assertTrue(os.path.exists(self.path("after")), "the outer run was killed by the inner launcher: %s" % r.stderr)
        self.assertTrue(alive(by), "a bystander of the outer scope was killed")
        waived = SE.read_report(self.path("report-waived"))
        self.assertEqual(waived["cleanup"], "pgroup")
        self.assertEqual(waived["parts"]["cpu"], "waived-failed")
        self.assertEqual(waived["codes"], ["verify-env-cpu-readback"])
        plain = SE.read_report(self.path("report-plain"))
        self.assertEqual(plain["refused"], ["verify-env-cpu-readback"])
        self.assertEqual(plain["cleanup"], "pgroup")


class ScopeOwnership(Scratch):
    """_scope_dir against a scratch cgroup tree: the scope is the launcher's own only when it holds this process alone."""

    def tree(self, procs):
        cg = "/user.slice/user.service/%s/run-u1.scope" % SE.SLICE
        root = self.path("cgroup")
        d = root + cg
        os.makedirs(d)
        with open(os.path.join(d, "cgroup.procs"), "w") as f:
            f.write("".join("%d\n" % p for p in procs))
        proc = self.path("self-cgroup")
        with open(proc, "w") as f:
            f.write("0::%s\n" % cg)
        return root, proc, d

    def test_alone_in_a_scope_below_the_slice(self):
        root, proc, d = self.tree([4242])
        with mock.patch.object(SE, "CGROUP_ROOT", root):
            self.assertEqual(SE._scope_dir(proc, 4242), d)
            for procs in ([4242, 4243], [4241], [4241, 4242], []):
                with open(os.path.join(d, "cgroup.procs"), "w") as f:
                    f.write("".join("%d\n" % p for p in procs))
                self.assertIsNone(SE._scope_dir(proc, 4242), procs)

    def test_other_cgroups_are_never_owned(self):
        root, proc, d = self.tree([4242])
        with mock.patch.object(SE, "CGROUP_ROOT", root):
            for line in ("0::/user.slice/app.slice/run-u1.scope", "0::/user.slice/%s" % SE.SLICE, "0::/%s/x.service" % SE.SLICE, "12:cpu:/a"):
                with open(proc, "w") as f:
                    f.write(line + "\n")
                self.assertIsNone(SE._scope_dir(proc, 4242), line)

    def test_a_missing_procs_file_is_not_owned(self):
        root, proc, d = self.tree([4242])
        os.unlink(os.path.join(d, "cgroup.procs"))
        with mock.patch.object(SE, "CGROUP_ROOT", root):
            self.assertIsNone(SE._scope_dir(proc, 4242))


if __name__ == "__main__":
    unittest.main()
