#!/usr/bin/env python3
"""The large Python modules run as imported modules (pymod in lib/lib.sh, the same form in bin/qargi): provider, marshal_store, help, gates and
lead_usage. Each answers as the script did (exit status, standard output and standard error), its bytecode is cached where the script's never was,
and the verbs that use them stay under their startup ceilings (tests/startup-budget.txt). Offline.
Run: python3 tests/test_startup_modules.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, shutil, subprocess, sys, time, unittest

from test_startup import BUDGET, LIB, ROOT, RUNS, VERBS, GuardTool, base_env, median_ms, read_budget


class VerbTool(GuardTool):
    """The tool as an installation leaves it (lib/ compiled) with a project, a repository, a member and an open feature, to time a verb in."""

    def __init__(self):
        super().__init__()
        for d in ("roles", "agents", "catalog", "contract", "provision", "methodologies", "canon"):      # what the verbs read besides bin/ and lib/
            shutil.copytree(os.path.join(ROOT, d), os.path.join(self.t, d), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(ROOT, "VERSION"), os.path.join(self.t, "VERSION"))
        self.conf, self.state, self.repo = (os.path.join(self.t, x) for x in ("conf", "state", "repo"))
        os.makedirs(os.path.join(self.conf, "projects"))
        os.makedirs(self.repo)
        with open(os.path.join(self.conf, "projects", "alpha.json"), "w") as f:
            json.dump({"repo": {"url": "https://example.com/acme.git", "path": self.repo}, "roles": {"build": {}, "review": {}}, "models": {"provider": "claude-code"}}, f)
        ident = {"GIT_AUTHOR_NAME": "a", "GIT_COMMITTER_NAME": "a", "GIT_AUTHOR_EMAIL": "a@example.invalid", "GIT_COMMITTER_EMAIL": "a@example.invalid"}
        self.verb_env = dict(base_env(), **ident, **self.env(QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_LEAD="lead1"))
        self.compile()
        for argv in (["git", "init", "-q", "."], ["git", "commit", "-q", "--allow-empty", "-m", "init"], ["git", "branch", "develop"],
                     [self.bin, "agent", "add", "worker", "--project", "alpha"], [self.bin, "feature", "start", "f1"]):
            r = self.run(argv)
            assert r.returncode == 0, (argv, r.stderr)

    def run(self, argv):
        return subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.repo, env=self.verb_env)


class PyMod(unittest.TestCase):
    """provider, marshal_store, help, gates and lead_usage are imported by bin/qargi and by pymod (lib/lib.sh), as the guard is (python compiles a
    script on every run and caches only what it imports), and everything the script did is what they still do."""
    MODULES = ("provider", "marshal_store", "help", "gates", "lead_usage")

    def setUp(self):
        self.tool = GuardTool()
        t = self.tool.t
        self.conf, self.state, self.repo, self.tree = (os.path.join(t, x) for x in ("conf", "state", "repo", "tree"))
        for d in (self.conf, self.state, self.repo, os.path.join(self.tree, ".github", "workflows")):
            os.makedirs(d)
        self.answers = os.path.join(t, "answers.json")
        with open(self.answers, "w") as f:
            json.dump({"gates": [{"name": "unit", "tier": "feature", "command": "make test"}, {"name": "lint", "tier": "release", "command": "make lint"}]}, f)
        with open(os.path.join(self.tree, ".github", "workflows", "test.yml"), "w") as f:
            f.write("name: t\non: push\njobs:\n  unit:\n    runs-on: x\n    steps: []\n")
        self.lead = ["--state", self.state, "--conf", self.conf, "--project", "alpha"]

    def tearDown(self):
        self.tool.close()

    def env(self):
        return dict(self.tool.env(), QARGI_CONF=self.conf, QARGI_STATE=self.state, DA_NOSETUP="1")

    def pymod(self, *args, env=None):
        return subprocess.run(["bash", "-c", '. "$0/lib/lib.sh"; pymod "$@"', self.tool.t, *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              cwd=self.tool.t, env=env or self.env())

    def script(self, module, *args, env=None):
        return subprocess.run([sys.executable, "-I", os.path.join(self.tool.lib, module + ".py"), *args], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                              cwd=self.tool.t, env=env or self.env())

    def pycs(self):
        d = os.path.join(self.tool.lib, "__pycache__")
        return sorted(n for n in (os.listdir(d) if os.path.isdir(d) else []) if n.endswith(".pyc"))

    def cases(self):
        gates, missing = self.answers, os.path.join(self.tool.t, "nosuch.json")
        return [("help", "infer"), ("help", "show"), ("help", "show", "role"), ("help", "show", "marshal", "status"), ("help", "complete", "role", ""),
                ("help", "complete", "--described", "marshal", ""), ("help", "resolve", "lead", "status"), ("help", "frob"), ("help",),
                ("provider", "list"), ("provider", "show", "claude-code"), ("provider", "show", "nosuch"), ("provider", "layout", "claude-code", "user_skills_dir"),
                ("provider", "model", "claude-code", "local", "balanced"), ("provider", "frob"), ("provider",),
                ("gates",), ("gates", "frob", "a"), ("gates", "select", gates, "feature", "release"), ("gates", "select", gates, "nosuchtier"),
                ("gates", "identity", gates, "feature", "release"), ("gates", "scan", gates, self.tree), ("gates", "scan", gates), ("gates", "select", missing, "feature"),
                ("lead_usage",), ("lead_usage", "--help"), ("lead_usage", "frob"), ("lead_usage", "usage", *self.lead),
                ("lead_usage", "open-runs", *self.lead, "--feature", "x"), ("lead_usage", "advice", *self.lead),
                ("marshal_store",), ("marshal_store", "--help"), ("marshal_store", "status", *self.lead, "--repo", self.repo, "--ttl", "15", "--brief", "--no-fetch")]

    def test_pymod_answers_as_the_script_did(self):
        """The same exit status, standard output and standard error as `python3 -I lib/MODULE.py ARGS`, for every module, the verbs that fail and the
        usage a missing argument gets (gates takes the whole argv, the others take it without the name)."""
        seen = set()
        for case in self.cases():
            a, b = self.pymod(*case), self.script(*case)
            self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), case)
            seen.add(case[0])
        self.assertEqual(seen, set(self.MODULES))
        self.assertEqual(self.pymod("gates", "select", self.answers, "feature").returncode, 0)
        self.assertEqual(self.pymod("gates", "select", self.answers, "nosuchtier").returncode, 2)
        self.assertEqual(self.pymod("provider", "show", "nosuch").returncode, 1)

    def test_the_dispatcher_answers_as_the_script_did(self):
        """bin/qargi help, completion and provider: the same as the scripts printed (the dispatcher adds the project it infers to the provider verbs)."""
        env = self.env()
        for argv, script in ((["help", "role"], ("help", "show", "role")), (["help"], ("help", "show")), (["role", "--help"], ("help", "show", "role")),
                             (["role", "list", "--help"], ("help", "show", "role", "list")), (["__complete", "role", ""], ("help", "complete", "role", "")),
                             (["provider", "list"], ("provider", "list")), (["provider", "show", "claude-code"], ("provider", "show", "claude-code")),
                             (["provider", "show", "nosuch"], ("provider", "show", "nosuch")), (["provider", "frob"], ("provider", "frob"))):
            a = subprocess.run([self.tool.bin, *argv], capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.tool.t, env=env)
            b = self.script(*script, env=env)
            self.assertEqual((a.returncode, a.stdout, a.stderr), (b.returncode, b.stdout, b.stderr), argv)
        r = subprocess.run([self.tool.bin], capture_output=True, text=True, stdin=subprocess.DEVNULL, cwd=self.tool.t, env=env)    # the dispatcher's usage: help show on stderr, exit 2
        self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", self.script("help", "show").stdout))

    def test_the_two_texts_agree(self):
        """bin/qargi does not source lib/lib.sh (the cost of a start-up of its own, and it execs), so it holds the text of pymod's code itself."""
        texts = []
        for p in (os.path.join(ROOT, "bin", "qargi"), os.path.join(LIB, "lib.sh")):
            with open(p) as f:
                found = re.findall(r"^PYMOD_SRC='([^']*)'$", f.read(), re.M)
            self.assertEqual(len(found), 1, p)
            texts.append(found[0])
        self.assertEqual(texts[0], texts[1])
        self.assertIn("import sys", texts[0])

    def test_they_are_imported_so_their_bytecode_is_cached(self):
        """Run with bytecode allowed, pymod leaves the compiled form of each module next to the source (a script never gets one)."""
        self.assertEqual(self.pycs(), [])
        for module in self.MODULES:
            self.assertEqual(self.script(module, "--help").returncode in (0, 2), True)
        self.assertEqual([n for n in self.pycs() if n.split(".")[0] in self.MODULES], [], "python cached a script")
        for case in (("help", "show"), ("provider", "list"), ("gates",), ("lead_usage", "--help"), ("marshal_store", "--help")):
            self.pymod(*case)
        got = {n.split(".")[0] for n in self.pycs()}
        self.assertEqual(got & set(self.MODULES), set(self.MODULES), "a module was not imported: its bytecode was not cached")

    def test_compiled_by_the_installer_they_run_from_the_bytecode(self):
        """install.sh --user and qargi upgrade compile lib/ (compileall); the modules then load that bytecode and do not compile again."""
        self.tool.compile()
        before = {n: os.stat(os.path.join(self.tool.lib, "__pycache__", n)).st_mtime_ns for n in self.pycs()}
        for case in (("help", "show"), ("provider", "list"), ("gates",), ("lead_usage", "--help"), ("marshal_store", "--help")):
            r = self.pymod(*case)
            self.assertIn(r.returncode, (0, 2), (case, r.stderr))
        self.assertEqual({n: os.stat(os.path.join(self.tool.lib, "__pycache__", n)).st_mtime_ns for n in self.pycs()}, before)
        self.assertTrue({"provider", "marshal_store", "help", "gates", "lead_usage"} <= {n.split(".")[0] for n in before})

    def test_a_module_that_does_not_load_fails_as_a_script_that_cannot_run_does(self):
        with open(os.path.join(self.tool.lib, "gates.py"), "w") as f:
            f.write("def main(:\n")
        a, b = self.pymod("gates", "select", self.answers, "feature"), self.script("gates", "select", self.answers, "feature")
        self.assertNotEqual(a.returncode, 0)
        self.assertEqual(a.returncode, b.returncode)
        self.assertIn("SyntaxError", a.stderr)


class Ceilings(unittest.TestCase):
    def test_the_verbs_against_their_ceilings(self):
        """`qargi agent for build` (a member's tier, four of the large modules) and `qargi marshal status --brief --no-fetch` (the lead's polling), from a tool
        whose lib/ is compiled, with a project, a member and an open feature: the median of RUNS runs; over the ceiling it warns, as for role list."""
        with open(BUDGET) as f:
            budget = read_budget(f.read())
        tool = VerbTool()
        try:
            for verb in VERBS:
                argv = [tool.bin] + verb.split()
                r = tool.run(argv)
                self.assertEqual(r.returncode, 0, (verb, r.stderr))
                self.assertNotEqual(r.stdout, "", verb)
                times = []
                for _ in range(RUNS):
                    t0 = time.perf_counter()
                    tool.run(argv)
                    times.append((time.perf_counter() - t0) * 1000)
                got, ceiling = median_ms(times), budget[verb][0]
                print("startup: qargi %s median %.0f ms over %d runs (ceiling %d ms)%s" % (verb, got, RUNS, ceiling, "" if got <= ceiling else
                      "\nWARNING: over the ceiling of tests/startup-budget.txt (a loaded machine, or startup got slower: measure it again alone)"), file=sys.stderr)
        finally:
            tool.close()


if __name__ == "__main__":
    unittest.main()
