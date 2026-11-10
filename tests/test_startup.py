#!/usr/bin/env python3
"""The dispatcher's startup (bin/qargi). Everything it does before a verb runs is one python process (lib/help.py preamble),
counted with a python3 shim on PATH; its output on the paths it owns is byte for byte what tests/fixtures/startup-goldens.json
holds (unknown command, verb and option, a missing project, no repository, a bad cloud binding, and the help pages, which are
the ones lib/help.py show prints); every module under lib/ imports, and every lazily imported part of help.py and cloud.py
runs; the resolved arguments, the exported binding, the current directory, the umask and the exit code of a failed preamble
are what they were. `qargi __guard` (run on every tool call of a member) loads guard.py as an imported module, so its bytecode is cached,
and answers byte for byte as the script did, also from a tool that is read-only. `qargi role list` is timed against tests/startup-budget.txt (the median of 20 runs; a ceiling only warns,
a machine under load is no failure; shrink-only: a ceiling above its value at the merge base with origin/develop needs a
`# raised: reason` comment). Offline; temporary state.
Run: python3 tests/test_startup.py
     python3 tests/test_startup.py --dump BIN     the goldens as BIN (a bin/qargi) prints them, as JSON: regenerate the fixture
                                                  with the repository's own, or compare two checkouts"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, shutil, stat, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
LIB = os.path.join(ROOT, "lib")
BUDGET = os.path.join(ROOT, "tests", "startup-budget.txt")
GOLDENS = os.path.join(ROOT, "tests", "fixtures", "startup-goldens.json")
RUNS = 20
WS = "wrkspc_01QargiQargiQargi"
sys.path.insert(0, LIB)
import commands as C  # noqa: E402
import help as H  # noqa: E402

# the goldens: (name, setup, env, argv); setup is none (no project), project (alpha, its repository a plain directory,
# the current directory outside it), inside (the same, run inside that directory) or binding (alpha with a cloud binding)
CASES = [
    ("unknown command", "none", {}, ["nosuch"]),
    ("unknown verb", "none", {}, ["role", "nosuchverb"]),
    ("unknown option", "none", {}, ["feature", "list", "--bogus"]),
    ("a verb's missing argument", "none", {}, ["role", "show"]),
    ("missing project, none stored", "none", {}, ["lead", "status"]),
    ("missing project, one stored", "project", {}, ["lead", "status"]),
    ("no repository", "inside", {}, ["feature", "list"]),
    ("bad cloud binding", "binding", {"ANTHROPIC_PROFILE": "other"}, ["project", "show", "alpha"]),
    ("qargi cloud is exempt from the binding", "binding", {"ANTHROPIC_PROFILE": "other"}, ["cloud", "show", "alpha"]),
]
# the dispatcher's usage (exit 2, the overview on stderr): compared with what help.py show prints, as the overview changes with the table
USAGE = [[], ["review", "frob"]]


def base_env():
    env = dict(os.environ)
    for k in ("COLUMNS", "LINES", "NO_COLOR", "ANTHROPIC_PROFILE", "QARGI_PROJECT"):
        env.pop(k, None)
    return env


class Home:
    """A fresh home with qargi's config and state inside, and the setup a case asks for."""

    def __init__(self, setup="none"):
        self.t = tempfile.mkdtemp(prefix="startup.")
        self.conf, self.state, self.repo = (os.path.join(self.t, x) for x in ("conf", "state", "repo"))
        self.env = dict(base_env(), HOME=self.t, QARGI_CONF=self.conf, QARGI_STATE=self.state)
        self.cwd = self.t
        if setup != "none":
            os.makedirs(os.path.join(self.conf, "projects"))
            os.makedirs(self.repo)
            doc = {"repo": {"url": "https://example.com/acme.git", "path": self.repo}, "roles": {"build": {}}}
            if setup == "binding":
                doc["cloud"] = {"profile": "qargi", "workspace_id": WS}
            with open(os.path.join(self.conf, "projects", "alpha.json"), "w") as f:
                json.dump(doc, f)
            if setup == "inside":
                self.cwd = self.repo

    def run(self, argv, bin_=BIN, env=None, trace=False):
        cmd = (["bash", "-x", bin_] if trace else [bin_]) + list(argv)
        return subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.cwd, env=dict(self.env, **(env or {})))

    def preamble(self, argv, env=None):
        return subprocess.run([sys.executable, "-I", os.path.join(LIB, "help.py"), "preamble", *argv], capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, cwd=self.cwd, env=dict(self.env, **(env or {})))

    def close(self):
        shutil.rmtree(self.t, True)


def help_pages():
    """Every help page the dispatcher serves: (argv, what help.py show gets)."""
    out = [(["help"], []), (["--help"], []), (["-h"], []), (["help", "--help"], []), (["help", "-h"], []), (["role", "-h"], ["role"]), (["role", "list", "-h"], ["role", "list"])]
    for area in sorted(C.COMMANDS):
        out.append((["help", area], [area]))
        if area not in ("help", "version"):           # `qargi help --help` is the overview, `qargi version --help` the version
            out.append(([area, "--help"], [area]))
        for v in (H.verbs_of(area) or {}):
            out += [(["help", area, v], [area, v]), ([area, v, "--help"], [area, v])]
    for t in C.TOPICS:
        out.append((["help", t], [t]))
    return out


def dump(bin_):
    """The goldens as BIN prints them: the cases and the help pages, with rc, stdout and stderr."""
    out = {"cases": [], "help": []}
    for name, setup, env, argv in CASES:
        h = Home(setup)
        try:
            r = h.run(argv, bin_, env)
        finally:
            h.close()
        out["cases"].append({"name": name, "setup": setup, "env": env, "argv": argv, "rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
    h = Home()
    try:
        for argv, _ in help_pages() + [(u, None) for u in USAGE]:
            r = h.run(argv, bin_)
            out["help"].append({"argv": argv, "rc": r.returncode, "stdout": r.stdout, "stderr": r.stderr})
    finally:
        h.close()
    return out


def read_budget(text):
    """{command: (ceiling, comment)} from `COMMAND MAX_MS [# comment]` lines; a malformed line raises ValueError."""
    out = {}
    for line in text.split("\n"):
        body = line.split("#", 1)[0].strip()
        if not body:
            continue
        *cmd, ms = body.split()
        if not cmd or not ms.isdigit():
            raise ValueError("not 'COMMAND MAX_MS [# comment]': %s" % line)
        out[" ".join(cmd)] = (int(ms), line.split("#", 1)[1] if "#" in line else "")
    return out


def raised_without_reason(old, new):
    """The commands whose ceiling in NEW is above the one in OLD without a `# raised: reason` comment."""
    return sorted(c for c, (ms, cmt) in new.items() if c in old and ms > old[c][0] and not re.match(r"\s*raised:\s*\S", cmt))


class Goldens(unittest.TestCase):
    """The dispatcher's own output, byte for byte: the fixture holds what it printed before the preamble became one process."""

    def test_the_cases_match_the_fixture(self):
        with open(GOLDENS) as f:
            want = json.load(f)["cases"]
        self.assertEqual([c["name"] for c in want], [c[0] for c in CASES], "the fixture and CASES differ: regenerate it with --dump")
        for case, (name, setup, env, argv) in zip(want, CASES):
            h = Home(setup)
            try:
                r = h.run(argv, env=env)
            finally:
                h.close()
            self.assertEqual((r.returncode, r.stdout, r.stderr), (case["rc"], case["stdout"], case["stderr"]), name)
        for c in want:
            self.assertNotIn("/home/", c["stdout"] + c["stderr"], "a host path in the fixture")

    def test_every_help_page_is_what_help_py_prints(self):
        """`qargi help AREA [VERB]`, `qargi AREA [VERB] --help` and `-h`, for every area, verb and topic of lib/commands.py:
        exit 0, nothing on stderr, and on stdout what lib/help.py show prints for the same words (so every verb's help loads)."""
        import contextlib, io

        def shown(words):                      # help.py show in this process, as a pipe sees it: no bold, the fallback width
            old = H.BOLD, H.width
            H.BOLD, H.width = False, lambda: 100
            try:
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    self.assertEqual(H.show(list(words)), 0, words)
            finally:
                H.BOLD, H.width = old
            return out.getvalue()
        h = Home()
        try:
            self.assertEqual(shown(["role", "list"]), h.run(["help", "role", "list"]).stdout)   # the in-process copy is the real thing
            for argv, words in help_pages():
                r = h.run(argv)
                self.assertEqual((r.returncode, r.stderr), (0, ""), argv)
                self.assertEqual(r.stdout, shown(words), argv)
                self.assertGreater(len(r.stdout), 20, argv)
            overview = shown([])
            for argv in USAGE:                                                       # the dispatcher's usage: exit 2, the overview on stderr
                r = h.run(argv)
                self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", overview), argv)
        finally:
            h.close()


class Imports(unittest.TestCase):
    """Imports moved to where they are used, so a missing one would show on the first use of a rare verb: every module imports
    and every lazily imported part runs."""

    def test_every_module_under_lib_imports(self):
        """Every lib/*.py imports with nothing on stderr, apart from a plain script (review_check.py, which runs at import) that
        must then stop at its usage, exit 2."""
        names = sorted(n[:-3] for n in os.listdir(LIB) if n.endswith(".py"))
        self.assertGreater(len(names), 20)
        scripts = []
        for n in names:                                                              # --nope: the script stops at its usage
            r = subprocess.run([sys.executable, "-I", "-c", "import os, sys; sys.path.insert(0, os.environ['QARGI_TEST_LIB']); import %s" % n, "--nope"],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(base_env(), QARGI_TEST_LIB=LIB))
            if r.returncode == 2 and "usage" in (r.stdout + r.stderr).lower():
                scripts.append(n)
            else:
                self.assertEqual((r.returncode, r.stderr), (0, ""), n)
        self.assertEqual(scripts, ["review_check"], "a new script under lib/ (it runs at import): give it a main guard")

    def test_the_lazy_parts_of_help_and_cloud_run(self):
        import cloud
        self.assertGreaterEqual(H.width(), 60)                                   # shutil
        self.assertEqual(H.wrap("a b", 2), "  a b")                              # textwrap
        self.assertEqual(H.th_date('.TH QARGI 1 "2026-01-01" "qargi 1"'), "2026-01-01")   # re
        self.assertIsInstance(H.kept_date(), str)                                 # subprocess (git show)
        self.assertTrue(H.man().startswith(".TH QARGI 1 "))
        self.assertEqual(H.by_type("pack", []), [])                               # glob
        self.assertIsInstance(H.branches([]), list)                               # subprocess (git for-each-ref)
        self.assertEqual(H.field_values("effort"), C.EFFORTS)
        self.assertGreater(len(H.field_values("model")), 0)                       # C.MODELS, read from the runtime descriptors on demand
        self.assertEqual(H.field_values("model"), C.MODELS)
        self.assertIn(C.MODELS[0], [m for m, _ in H.models()])
        self.assertEqual(H.values(["project", "set", "alpha", "lead.model"]), [(m, "") for m in C.MODELS])
        self.assertEqual(cloud.projects(), [])
        self.assertIsNone(cloud.profiles())                                       # subprocess: the hermetic ant stub fails
        with self.assertRaises(AttributeError):
            C.NOPE


class Processes(unittest.TestCase):
    """A python3 shim first on PATH records every python3 the dispatcher starts."""

    def setUp(self):
        self.h = Home("binding")
        self.shim = os.path.join(self.h.t, "shim")
        os.makedirs(self.shim)
        self.log = os.path.join(self.h.t, "python3.log")
        self.real = shutil.which("python3", path=os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if p != os.path.join(hermetic.ROOT, "bin")))
        self.assertTrue(self.real, "no python3 on PATH")
        self.write_shim('#!/bin/sh\nprintf \'%%s\\n\' "$*" >> "$QARGI_TEST_PYLOG"\nexec "%s" "$@"\n' % self.real)
        self.h.env.update(PATH=self.shim + os.pathsep + self.h.env["PATH"], QARGI_TEST_PYLOG=self.log)

    def tearDown(self):
        self.h.close()

    def write_shim(self, text):
        p = os.path.join(self.shim, "python3")
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, 0o755)

    def starts(self, *argv, env=None, cwd=None):
        if os.path.exists(self.log):
            os.remove(self.log)
        if cwd:
            self.h.cwd = cwd
        r = self.h.run(argv, env=env)
        with open(self.log) if os.path.exists(self.log) else open(os.devnull) as f:
            return r, f.read().splitlines()

    def test_exactly_one_python_process_before_the_verb(self):
        for argv in (("role", "list"), ("role", "show", "build")):                 # the verb runs no python: the preamble is all there is
            r, py = self.starts(*argv)
            self.assertEqual(r.returncode, 0, argv)
            self.assertEqual(len(py), 1, (argv, py))
            self.assertIn("preamble", py[0])
        for argv in (("nosuch",), ("lead", "status"), ("role", "nosuchverb")):     # the dispatcher's errors: the preamble, nothing else
            r, py = self.starts(*argv, cwd=self.h.t)
            self.assertEqual(r.returncode, 2, argv)
            self.assertEqual(len(py), 1, (argv, py))
        r, py = self.starts("project", "show", "alpha", cwd=self.h.repo)          # a verb that runs python of its own: the preamble is first and once
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("preamble", py[0])
        self.assertEqual(sum("preamble" in l for l in py), 1, py)

    def test_no_preamble_for_help_version_completion_guard_and_hooks(self):
        for argv in (("version",), ("help",), ("role", "--help"), ("__complete", "role", ""), ("hook", "tool-use")):
            r, py = self.starts(*argv)
            self.assertEqual(r.returncode, 0, argv)
            self.assertEqual([l for l in py if "preamble" in l], [], argv)

    def test_the_binding_is_exported_to_the_verb_and_the_arguments_resolved(self):
        self.write_shim('#!/bin/sh\nprintf \'%%s|%%s|%%s|%%s\\n\' "$*" "${ANTHROPIC_PROFILE-unset}" "${QARGI_CLOUD_WORKSPACE-unset}" "${QARGI_CLOUD_PROJECT-unset}" >> "$QARGI_TEST_PYLOG"\nexec "%s" "$@"\n'
                        % self.real)
        r, py = self.starts("provider", "disable", "nothing", cwd=self.h.repo)     # provider is python: the shim sees the verb's environment
        self.assertTrue(py[0].endswith("|unset|unset|unset"), py[0])                # the preamble runs in the caller's environment
        self.assertEqual(len(py), 2, py)
        self.assertTrue(py[1].endswith("|qargi|%s|alpha" % WS), py[1])              # the verb gets the binding
        self.assertIn("provider.py disable alpha nothing|", py[1])                  # with the project filled in where it belongs (argv order)
        r, py = self.starts("provider", "disable", "alpha", "nothing", cwd=self.h.t)  # named outside the repository: the binding still
        self.assertTrue(py[1].endswith("provider.py disable alpha nothing|qargi|%s|alpha" % WS), py[1])
        r, py = self.starts("noticed", "list", cwd=self.h.t)                        # about no project: no binding
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(py[1].endswith("noticed.py list|unset|unset|unset"), py[1])

    def test_a_preamble_that_dies_exits_2_and_prints_nothing(self):
        self.write_shim('#!/bin/sh\necho shim >> "$QARGI_TEST_PYLOG"\nexit 7\n')
        r, py = self.starts("role", "list")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", ""))
        self.assertEqual(py, ["shim"])
        self.write_shim('#!/bin/sh\nprintf \'half\\0\' ; exit 0\n')                  # too few fields: the same
        r, py = self.starts("role", "list")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", ""))


class Preamble(unittest.TestCase):
    """lib/help.py preamble itself: what it prints, in which order, and what it leaves alone."""

    def test_it_prints_the_binding_and_the_resolved_arguments(self):
        h = Home("binding")
        try:
            r = h.preamble(["role", "list"])
            self.assertEqual((r.returncode, r.stderr, r.stdout), (0, "", "\0\0\0role\0list\0"))
            h.cwd = h.repo
            cases = (["lead", "status"], ["team", "brief", "code-docs", "--task", "x"], ["instances", "show", "build"], ["send", "build", "the task", "--label", "x"],
                     ["provision", "plan"], ["project", "set", "budget_cents", "600"], ["role", "list"], ["cloud", "show"])
            for argv in cases:
                r = h.preamble(argv)
                self.assertEqual((r.returncode, r.stderr), (0, ""), argv)
                fields = r.stdout.split("\0")[:-1]
                self.assertEqual(fields[:3], ["", "", ""] if argv[0] == "cloud" else ["alpha", "qargi", WS], argv)
                ref = subprocess.run([sys.executable, "-I", os.path.join(LIB, "help.py"), "resolve", *argv], capture_output=True, text=True,
                                     stdin=subprocess.DEVNULL, cwd=h.cwd, env=h.env)
                self.assertEqual(r.stdout[len("\0".join(fields[:3])) + 1:], ref.stdout, argv)   # the same words in the same order as resolve
            self.assertEqual(h.preamble(["lead", "status"]).stdout.split("\0")[3:], ["lead", "status", "alpha", ""])
            h.cwd = h.t
            r = h.preamble(["lead", "status"])
            self.assertEqual((r.returncode, r.stdout), (2, ""))
            self.assertTrue(r.stderr.startswith("qargi: which project? "), r.stderr)
            self.assertEqual(h.preamble(["project", "show", "alpha"]).stdout.split("\0")[:3], ["alpha", "qargi", WS])   # named, not inferred
        finally:
            h.close()

    def test_it_creates_nothing_and_keeps_the_current_directory_and_umask(self):
        h = Home("inside")
        try:
            old = os.umask(0o077)
            try:
                r = h.preamble(["lead", "status"])
            finally:
                os.umask(old)
            self.assertEqual(r.returncode, 0)
            self.assertFalse(os.path.exists(h.state), "the preamble created the state directory")
            self.assertEqual(sorted(os.listdir(h.t)), ["conf", "repo"])
            self.assertEqual((os.listdir(h.conf), os.listdir(os.path.join(h.conf, "projects")), os.listdir(h.repo)), (["projects"], ["alpha.json"], []))
            r = h.run(["nosuch"])                                                    # the dispatcher's error path creates nothing either
            self.assertEqual(r.returncode, 2)
            self.assertFalse(os.path.exists(h.state))
            self.assertEqual((sorted(os.listdir(h.t)), os.listdir(h.conf), os.listdir(h.repo)), (["conf", "repo"], ["projects"], []))
            # a verb runs in the caller's directory: lib.sh's QARGI_TOOL and the project inferred from here agree with the resolve above
            r = h.run(["project", "show"])
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn('"path": ', r.stdout)
            self.assertEqual(stat.S_IMODE(os.stat(h.conf).st_mode), 0o700)           # what lib.sh does on its own, unchanged
        finally:
            h.close()


def call(command, tool="Bash"):
    """One tool call as the hook protocol delivers it (JSON on standard input)."""
    return json.dumps({"tool_name": tool, "tool_input": {"command": command}, "cwd": "/"})


class GuardTool:
    """A copy of bin/ and lib/ in a fresh directory, without bytecode: the tool as a checkout installed with sudo is, until it is compiled."""

    def __init__(self):
        self.t = tempfile.mkdtemp(prefix="guardtool.")
        self.home = os.path.join(self.t, "home")
        os.makedirs(self.home)
        for d in ("bin", "lib"):
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.t, d), ignore=shutil.ignore_patterns("__pycache__"))
        self.bin = os.path.join(self.t, "bin", "qargi")
        self.lib = os.path.join(self.t, "lib")

    def env(self, **more):
        """What a hook has: little more than a PATH (python3 is found on it)."""
        return dict({"PATH": os.environ["PATH"], "HOME": self.home}, **more)

    def guard(self, stdin, *args, env=None):
        return subprocess.run([self.bin, "__guard", *args], input=stdin, capture_output=True, text=True, env=self.env() if env is None else env)

    def script(self, stdin, *args, env=None):
        """The guard the way bin/qargi ran it before: guard.py as a script."""
        return subprocess.run([sys.executable, "-I", os.path.join(self.lib, "guard.py"), *args], input=stdin, capture_output=True, text=True,
                              env=self.env() if env is None else env)

    def pyc(self):
        d = os.path.join(self.lib, "__pycache__")
        return sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if n.startswith("guard.") and n.endswith(".pyc"))

    def compile(self):
        """What install.sh --user and qargi upgrade do."""
        subprocess.run([sys.executable, "-I", "-m", "compileall", "-q", self.lib], check=True)

    def close(self):
        for d, dirs, _ in os.walk(self.t):
            for x in dirs:
                os.chmod(os.path.join(d, x), 0o755)
        os.chmod(self.t, 0o755)
        shutil.rmtree(self.t, True)


class Guard(unittest.TestCase):
    """bin/qargi runs the guard as an imported module (python compiles a script on every run and caches only what it imports: the 235 KB
    guard.py took more than half of the 100 ms of every tool call), and everything the script did is what it still does."""

    def setUp(self):
        self.tool = GuardTool()

    def tearDown(self):
        self.tool.close()

    CALLS = [("a harmless call", call("true")), ("git push", call("git push origin HEAD")), ("a Write", json.dumps({"tool_name": "Write", "tool_input": {"file_path": "/nonexistent/x", "content": "a"}, "cwd": "/"})),
             ("empty input", ""), ("not JSON", "{"), ("not UTF-8 text", "\xff"), ("JSON that is no call", "[1, 2]")]

    def test_it_answers_as_the_script_did(self):
        """The same exit status, standard output and standard error as `python3 -I lib/guard.py`, for the options too (a class, a provider that is not
        there, a class that is not one, an option without its value) and the stdin of a hook."""
        for opts in ((), ("--class", "read-only"), ("--class", "write"), ("--class", "nosuch"), ("--class",), ("--provider", "nosuch"), ("--provider",)):
            for what, stdin in self.CALLS:
                a, b = self.tool.guard(stdin, *opts), self.tool.script(stdin, *opts)
                self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), (what, opts))
        self.assertEqual(self.tool.guard(call("true")).returncode, 0)
        r = self.tool.guard(call("git push origin HEAD"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("qargi guard:", r.stderr)

    def test_the_arguments_after_the_guard_reach_it(self):
        """sys.argv of the module is what the script had (the lib directory the dispatcher passes is taken off): a read-only member may not write."""
        stdin = json.dumps({"tool_name": "Write", "tool_input": {"file_path": os.path.join(self.tool.home, "x"), "content": "a"}, "cwd": self.tool.home})
        plain, ro = self.tool.guard(stdin), self.tool.guard(stdin, "--class", "read-only")
        self.assertEqual(plain.returncode, 0, plain.stderr)
        self.assertEqual(ro.returncode, 2)
        self.assertIn("read-only", ro.stderr)
        self.assertEqual(self.tool.guard(call("true"), "--class", "nosuch").returncode, 2)

    def test_it_is_imported_so_its_bytecode_is_cached(self):
        """Run with bytecode allowed, the dispatcher leaves guard's compiled form next to the source (a script never gets one)."""
        self.assertEqual(self.tool.pyc(), [])
        self.assertEqual(self.tool.script(call("true"), env=self.tool.env()).returncode, 0)
        self.assertEqual(self.tool.pyc(), [], "python cached a script")
        self.assertEqual(self.tool.guard(call("true"), env=self.tool.env()).returncode, 0)
        self.assertEqual(len(self.tool.pyc()), 1, "the guard was not imported: its bytecode was not cached")

    def test_compiled_by_the_installer_it_runs_from_the_bytecode(self):
        """install.sh --user and qargi upgrade compile lib/ (compileall); the guard then loads that bytecode and does not compile again."""
        self.tool.compile()
        before = {n: os.stat(os.path.join(self.tool.lib, "__pycache__", n)).st_mtime_ns for n in self.tool.pyc()}
        self.assertEqual(len(before), 1)
        self.assertEqual(self.tool.guard(call("true")).returncode, 0)
        self.assertEqual(self.tool.guard(call("git push origin HEAD")).returncode, 2)
        self.assertEqual({n: os.stat(os.path.join(self.tool.lib, "__pycache__", n)).st_mtime_ns for n in self.tool.pyc()}, before)
        with open(os.path.join(self.tool.lib, "guard.py"), "a") as f:   # a source that changed is compiled again, not run from stale bytecode
            f.write("\nSTALE_CHECK = True\n")
        r = subprocess.run([self.tool.bin, "__guard"], input=call("true"), capture_output=True, text=True, env=self.tool.env())
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root writes anywhere")
    def test_a_read_only_tool_still_answers_and_stays_untouched(self):
        """The tool as sudo installs it: nothing can be written next to the source, there is no bytecode, and the guard answers all the same."""
        for d, dirs, files in os.walk(self.tool.t):
            if os.path.abspath(d) == self.tool.home:
                dirs[:] = []
                continue
            for x in dirs + files:
                p = os.path.join(d, x)
                if not os.path.islink(p):
                    os.chmod(p, os.stat(p).st_mode & 0o555)
        os.chmod(os.path.join(self.tool.t, "lib"), 0o555)
        os.chmod(os.path.join(self.tool.t, "bin"), 0o555)
        r = self.tool.guard(call("true"), env=self.tool.env())
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(self.tool.guard(call("git push origin HEAD")).returncode, 2)
        self.assertEqual(self.tool.pyc(), [])
        self.assertFalse(os.path.exists(os.path.join(self.tool.lib, "__pycache__")))

    def test_a_missing_or_broken_module_refuses_as_a_script_that_cannot_run_does(self):
        """A guard that cannot be loaded is no allow: the exit status is not 0 (the hook then blocks), as it was for a script that did not parse."""
        with open(os.path.join(self.tool.lib, "guard.py"), "w") as f:
            f.write("def main(:\n")
        r = self.tool.guard(call("true"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SyntaxError", r.stderr)
        os.remove(os.path.join(self.tool.lib, "guard.py"))
        r = self.tool.guard(call("true"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("guard", r.stderr)


class Budget(unittest.TestCase):
    def test_the_budget_file_is_well_formed(self):
        with open(BUDGET) as f:
            b = read_budget(f.read())
        self.assertIn("role list", b)
        with self.assertRaises(ValueError):
            read_budget("role list fast\n")

    def test_the_raised_check(self):
        old = read_budget("a 10\nb 10\nc 10\nd 10\ne 10\n")
        new = read_budget("a 12\nb 12 # raised: a new lookup\nc 9\nd 10 # note\ne 11 # raised:\nf 99\n")
        self.assertEqual(raised_without_reason(old, new), ["a", "e"])

    def test_no_ceiling_is_raised_without_a_reason(self):
        base = subprocess.run(["git", "-C", ROOT, "merge-base", "HEAD", "origin/develop"], capture_output=True, text=True)
        if base.returncode != 0:
            self.skipTest("no merge base with origin/develop")
        old = subprocess.run(["git", "-C", ROOT, "show", "%s:tests/startup-budget.txt" % base.stdout.strip()], capture_output=True, text=True)
        if old.returncode != 0:
            self.skipTest("no tests/startup-budget.txt at the merge base")
        with open(BUDGET) as f:
            raised = raised_without_reason(read_budget(old.stdout), read_budget(f.read()))
        self.assertEqual(raised, [], "ceiling raised without a '# raised: why' comment in tests/startup-budget.txt: %s" % raised)

    def test_role_list_against_its_ceiling(self):
        """The median of RUNS runs; over the ceiling it warns (a loaded machine), it does not fail: the process count is the gate."""
        with open(BUDGET) as f:
            ceiling = read_budget(f.read())["role list"][0]
        h = Home()
        try:
            self.assertEqual(h.run(["role", "list"]).returncode, 0)
            times = []
            for _ in range(RUNS):
                t0 = time.perf_counter()
                h.run(["role", "list"])
                times.append((time.perf_counter() - t0) * 1000)
        finally:
            h.close()
        times.sort()
        got = (times[RUNS // 2 - 1] + times[RUNS // 2]) / 2
        print("startup: qargi role list median %.0f ms over %d runs (ceiling %d ms)%s" % (got, RUNS, ceiling, "" if got <= ceiling else
              "\nWARNING: over the ceiling of tests/startup-budget.txt (a loaded machine, or startup got slower: measure it again alone)"), file=sys.stderr)


if __name__ == "__main__":
    if sys.argv[1:2] == ["--dump"] and len(sys.argv) == 3:
        json.dump(dump(sys.argv[2]), sys.stdout, indent=1, sort_keys=True)
        sys.stdout.write("\n")
        sys.exit(0)
    unittest.main()
