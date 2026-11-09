#!/usr/bin/env python3
"""lib/gates.py: the check of the answer gates (names unique and non-empty, a tier of the two, a command line or a list of words), the
selection by tier (a list of words is shell-quoted into one line), and the reading of workflow files without a YAML library: the job
ids and the name: line of each job, and the findings of the scan (unmatched jobs; unknown names, which are never counted as unmatched).
Run: python3 tests/test_gates.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import gates  # noqa: E402


def G(name="test", command="make test", tier="feature"):
    return {"name": name, "command": command, "tier": tier}


class Validation(unittest.TestCase):
    def test_absent_and_empty_are_valid(self):
        self.assertEqual(gates.problems(None), [])
        self.assertEqual(gates.problems([]), [])

    def test_valid_forms(self):
        self.assertEqual(gates.problems([G(), G("lint", ["make", "lint"], "release")]), [])

    def test_not_a_list(self):
        self.assertTrue(gates.problems({"name": "x"})[0].startswith("gates: a list"))

    def test_each_problem_is_named(self):
        for bad, key in ((G(name=""), "name"), (G(name=" x"), "name"), (G(name=5), "name"), (G(command=""), "command"), (G(command=[]), "command"),
                         (G(command=["make", ""]), "command"), (G(command="a\nb"), "command"), (G(tier="nightly"), "tier"), (G(tier=None), "tier"),
                         ({"name": "x", "command": "y", "tier": "feature", "extra": 1}, "extra"), ("make test", "an object"),
                         # a Unicode line break would split the rendered YAML block and markdown list item
                         (G(name="a b"), "name"), (G(name="a b"), "name"), (G(name="a\x85b"), "name"), (G(name="a\x0bb"), "name"),
                         (G(command="a b"), "command"), (G(command="a b"), "command"), (G(command="a\x85b"), "command"),
                         (G(command="a\x0cb"), "command"), (G(command=["echo", "a b"]), "command"), (G(command=["echo", "a\nb"]), "command")):
            p = gates.problems([bad])
            self.assertTrue(p and key in p[0], (bad, p))
            self.assertIn("gates[0]", p[0])

    def test_duplicate_names(self):
        p = gates.problems([G("a"), G("b"), G("a", tier="release")])
        self.assertEqual(len(p), 1)
        self.assertIn("gates[2].name", p[0])
        self.assertIn('"a" is used twice', p[0])


class Selection(unittest.TestCase):
    def test_tiers_and_order(self):
        gs = [G("a"), G("b", tier="release"), G("c", ["make", "two words"])]
        self.assertEqual([g["name"] for g in gates.select(gs, ["feature"])], ["a", "c"])
        self.assertEqual([g["name"] for g in gates.select(gs, ["feature", "release"])], ["a", "c", "b"])   # the feature tier, then the release tier
        self.assertEqual(gates.select(gs, ["feature"])[1]["command"], "make 'two words'")


class Identity(unittest.TestCase):
    def test_the_identity_of_the_gates_of_the_tiers(self):
        gs = [G("a"), G("b", tier="release"), G("c", ["make", "two words"])]
        self.assertEqual(gates.identity(gs, ["feature"]), "gates: a=make test; c=make 'two words'")
        self.assertEqual(gates.identity(gs, ["feature", "release"]), "gates: a=make test; c=make 'two words'; b=make test")

    def test_none_when_no_declared_gate_has_the_tiers_and_nothing_when_none_is_declared(self):
        self.assertEqual(gates.identity([G(tier="release")], ["feature"]), "gates: none")
        self.assertIsNone(gates.identity([], ["feature"]))
        self.assertIsNone(gates.identity(None, ["feature"]))


class Parsing(unittest.TestCase):
    def jobs(self, text):
        return gates.parse_jobs(text)

    def test_ids_and_names(self):
        t = ("name: CI\non: [push]\njobs:\n"
             "  test:\n    runs-on: x\n    steps:\n      - name: a step\n        run: |\n          name: not a job name\n"
             "  lint:\n    name: \"Lint code\"   # why\n"
             "  'quoted-id':\n    name: 'it''s'\n"
             "  # a comment between jobs\n"
             "  plain:\n    name: Plain words # c\n"
             "env:\n  a: b\n")
        self.assertEqual(self.jobs(t), [("test", ""), ("lint", "Lint code"), ("quoted-id", "it's"), ("plain", "Plain words")])

    def test_names_that_cannot_be_read(self):
        t = ("jobs:\n  a:\n    name: build ${{ matrix.os }}\n  b:\n    name: |\n      text\n  c: {uses: x/y}\n  d:\n    name: *alias\n"
             "  e:\n    name: \"esc\\u0041\"\n  f:\n    name:\n")
        self.assertEqual(self.jobs(t), [("a", None), ("b", None), ("c", None), ("d", None), ("e", None), ("f", None)])

    def test_unreadable_files(self):
        self.assertIsNone(self.jobs("name: x\non: push\n"))
        self.assertIsNone(self.jobs("jobs:\n"))
        self.assertIsNone(self.jobs("jobs: {a: {}}\n"))
        self.assertIsNone(self.jobs("jobs:\n\ta:\n"))

    def test_crlf(self):
        self.assertEqual(self.jobs("jobs:\r\n  a:\r\n    name: A\r\n"), [("a", "A")])


class Scan(unittest.TestCase):
    def tree(self, files):
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        os.makedirs(os.path.join(d, ".github", "workflows"))
        for n, t in files.items():
            with open(os.path.join(d, ".github", "workflows", n), "w") as f:
                f.write(t)
        return d

    def test_matches_by_name_or_id(self):
        d = self.tree({"a.yml": "jobs:\n  test:\n    name: Unit\n  lint:\n    runs-on: x\n  extra:\n    name: Extra job\n  m:\n    name: ${{ x }}\n"})
        found, bad = gates.scan([G("Unit"), G("lint")], d)
        self.assertEqual(found, [("unmatched", ".github/workflows/a.yml", "extra", "Extra job"), ("unknown", ".github/workflows/a.yml", "m", "")])
        self.assertEqual(bad, 1)

    def test_id_matches_when_the_name_is_unreadable(self):
        d = self.tree({"a.yaml": "jobs:\n  test:\n    name: ${{ x }}\n"})
        self.assertEqual(gates.scan([G("test")], d), ([], 0))

    def test_no_workflow(self):
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        self.assertEqual(gates.scan([G()], d), ([], 0))

    def test_unreadable_workflow_is_unknown_not_unmatched(self):
        d = self.tree({"x.yml": "jobs: {a: {}}\n"})
        self.assertEqual(gates.scan([], d), ([("unknown", ".github/workflows/x.yml", "", "")], 0))

    def test_files_in_order(self):
        d = self.tree({"b.yml": "jobs:\n  two:\n    runs-on: x\n", "a.yml": "jobs:\n  one:\n    runs-on: x\n"})
        self.assertEqual([f[2] for f in gates.scan([], d)[0]], ["one", "two"])


class Cli(unittest.TestCase):
    def run_cli(self, answers, *args):
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        af = os.path.join(d, "a.json")
        with open(af, "w") as f:
            json.dump(answers, f)
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "gates.py"), args[0], af, *args[1:]], capture_output=True, text=True)

    def test_select_prints_nothing_without_gates(self):
        p = self.run_cli({"test_command": "true"}, "select", "feature")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        p = self.run_cli({"gates": []}, "select", "feature")
        self.assertEqual((p.returncode, p.stdout), (0, ""))

    def test_select_prints_json(self):
        p = self.run_cli({"gates": [G(), G("r", tier="release")]}, "select", "release")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout), [{"name": "r", "tier": "release", "command": "make test"}])

    def test_identity_prints_the_text_a_run_record_keeps(self):
        p = self.run_cli({"gates": [G(), G("r", tier="release")]}, "identity", "feature")
        self.assertEqual((p.returncode, p.stdout), (0, "gates: test=make test\n"))
        p = self.run_cli({"gates": [G(tier="release")]}, "identity", "feature")
        self.assertEqual(p.stdout, "gates: none\n")
        p = self.run_cli({"test_command": "true"}, "identity", "feature")
        self.assertEqual((p.returncode, p.stdout), (0, ""))
        p = self.run_cli({"gates": [G(), G()]}, "identity", "feature")
        self.assertEqual(p.returncode, 1)

    def test_select_refuses_invalid_gates(self):
        p = self.run_cli({"gates": [G(), G()]}, "select", "feature")
        self.assertEqual(p.returncode, 1)
        self.assertIn("is used twice", p.stderr)


if __name__ == "__main__":
    unittest.main()
