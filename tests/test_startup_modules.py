#!/usr/bin/env python3
"""The large Python modules run as imported modules (pymod in lib/lib.sh, the same form in bin/qargi): provider, marshal_store, help, gates and
lead_usage. Each answers as the script did (exit status, standard output and standard error), and its bytecode is cached where the script's never was.
Offline. Run: python3 tests/test_startup_modules.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, subprocess, sys, unittest

from test_startup import LIB, ROOT, GuardTool


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


if __name__ == "__main__":
    unittest.main()
