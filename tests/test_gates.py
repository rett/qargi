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


class CiAnswers(unittest.TestCase):
    """gates[].ci_jobs and the answer ci.not_gates: lists of job names or ids."""
    def test_valid(self):
        self.assertEqual(gates.problems([dict(G(), ci_jobs=["Unit tests", "unit-linux"])]), [])
        self.assertEqual(gates.ci_problems(None), [])
        self.assertEqual(gates.ci_problems({}), [])
        self.assertEqual(gates.ci_problems({"not_gates": ["publish", "All checks"]}), [])

    def test_each_problem_is_named(self):
        for bad in ("unit", [], [""], [" x"], ["a", "a"], [5], ["a\nb"], {"a": 1}):
            p = gates.problems([dict(G(), ci_jobs=bad)])
            self.assertTrue(p and "gates[0].ci_jobs" in p[0], (bad, p))
        for bad in ("publish", [], [""], ["x", "x"], [None], ["a\x85b"]):
            p = gates.ci_problems({"not_gates": bad})
            self.assertTrue(p and "ci.not_gates" in p[0], (bad, p))
        self.assertIn("ci.other: unknown key", gates.ci_problems({"other": 1})[0])
        self.assertTrue(gates.ci_problems(["publish"])[0].startswith("ci: an object"))


class CoveredBy(unittest.TestCase):
    """covered_by on a feature gate names a release gate."""
    def test_valid(self):
        self.assertEqual(gates.problems([dict(G("lint"), covered_by="ci"), G("ci", tier="release")]), [])
        self.assertEqual(gates.problems([G("ci", tier="release"), dict(G("lint"), covered_by="ci")]), [])   # the order does not matter

    def test_a_name_that_is_no_release_gate_is_refused(self):
        for gs in ([dict(G("lint"), covered_by="ci")],                                              # no such gate
                   [dict(G("lint"), covered_by="unit"), G("unit")],                                 # a feature gate
                   [dict(G("lint"), covered_by="lint"), G("ci", tier="release")],                   # itself
                   [dict(G("lint"), covered_by=5), G("ci", tier="release")],
                   [dict(G("lint"), covered_by=["ci"]), G("ci", tier="release")],
                   [dict(G("lint"), covered_by=None), G("ci", tier="release")]):
            p = gates.problems(gs)
            self.assertTrue(p and "gates[0].covered_by" in p[0] and "release gate" in p[0], (gs, p))

    def test_only_a_feature_gate_is_covered(self):
        p = gates.problems([dict(G("pack", tier="release"), covered_by="ci"), G("ci", tier="release")])
        self.assertTrue(p and "gates[0].covered_by: only a feature gate" in p[0], p)

    def test_select_carries_covered_by_only_when_set(self):
        gs = [dict(G("lint"), covered_by="ci"), G("unit"), G("ci", tier="release")]
        self.assertEqual([g.get("covered_by") for g in gates.select(gs, ["feature", "release"])], ["ci", None, None])
        self.assertEqual(gates.select(gs, ["feature"])[1], {"name": "unit", "tier": "feature", "command": "make test"})


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


class Trees:
    def tree(self, files):
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        os.makedirs(os.path.join(d, ".github", "workflows"))
        for n, t in files.items():
            with open(os.path.join(d, ".github", "workflows", n), "w") as f:
                f.write(t)
        return d


class Scan(Trees, unittest.TestCase):
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


class ScanListed(Trees, unittest.TestCase):
    """ci_jobs and ci.not_gates in the scan."""
    WF = "jobs:\n  lint:\n    runs-on: x\n  unit-linux:\n    runs-on: x\n  unit-mac:\n    name: Unit (mac)\n  publish:\n    runs-on: x\n  all:\n    name: All checks\n"

    def test_a_job_in_ci_jobs_is_covered_not_unmatched(self):
        d = self.tree({"a.yml": self.WF})
        found, bad = gates.scan([G("lint"), dict(G("unit"), ci_jobs=["unit-linux", "Unit (mac)"])], d, ["publish", "All checks"])
        self.assertEqual(found, [("covered", ".github/workflows/a.yml", "unit-linux", "unit"), ("covered", ".github/workflows/a.yml", "unit-mac", "unit")])
        self.assertEqual(bad, 0)

    def test_not_gates_are_left_out_by_name_or_id(self):
        d = self.tree({"a.yml": self.WF})
        found, bad = gates.scan([G("lint")], d, ["publish", "All checks"])
        self.assertEqual([f[2] for f in found], ["unit-linux", "unit-mac"])
        self.assertTrue(all(f[0] == "unmatched" for f in found))
        self.assertEqual(bad, 2)

    def test_no_gate_declared_still_honours_not_gates(self):
        d = self.tree({"a.yml": "jobs:\n  one:\n    runs-on: x\n  two:\n    runs-on: x\n"})
        self.assertEqual(gates.scan([], d, ["one"])[1], 1)

    def test_a_listed_name_no_workflow_has_is_missing(self):
        d = self.tree({"a.yml": self.WF})
        found, bad = gates.scan([G("lint"), dict(G("unit"), ci_jobs=["unit-linux", "unit-gone"])], d, ["publish", "ALL", "All checks", "gone"])
        self.assertEqual([f for f in found if f[0] == "missing"],
                         [("missing", "-", "unit-gone", "gate unit"), ("missing", "-", "ALL", "ci.not_gates"), ("missing", "-", "gone", "ci.not_gates")])

    def test_missing_is_not_reported_when_a_name_cannot_be_read_or_without_workflow(self):
        d = self.tree({"a.yml": "jobs:\n  one:\n    name: ${{ x }}\n"})
        self.assertEqual([f[0] for f in gates.scan([], d, ["two"])[0]], ["unknown"])
        d = self.tree({"x.yml": "jobs: {a: {}}\n"})
        self.assertEqual([f[0] for f in gates.scan([], d, ["two"])[0]], ["unknown"])
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        self.assertEqual(gates.scan([dict(G(), ci_jobs=["x"])], d, ["y"]), ([], 0))


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

    def test_scan_reads_not_gates_and_ci_jobs_from_the_answers(self):
        d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", d]))
        os.makedirs(os.path.join(d, ".github", "workflows"))
        with open(os.path.join(d, ".github", "workflows", "a.yml"), "w") as f:
            f.write("jobs:\n  lint:\n    runs-on: x\n  ci-all:\n    runs-on: x\n  other:\n    runs-on: x\n")
        p = self.run_cli({"gates": [dict(G("lint"), ci_jobs=["other"])], "ci": {"not_gates": ["ci-all", "stale"]}}, "scan", d)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(p.stdout.splitlines(), ["covered\t.github/workflows/a.yml\tother\tlint", "missing\t-\tstale\tci.not_gates"])
        p = self.run_cli({"gates": [G("lint")], "ci": {"not_gates": "ci-all"}}, "scan", d)
        self.assertEqual(p.returncode, 1)
        self.assertIn("ci.not_gates", p.stderr)


if __name__ == "__main__":
    unittest.main()
