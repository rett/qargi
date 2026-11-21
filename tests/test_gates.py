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


# ---- the coordinator label (QARGI_ACTOR): the form, and the narrowing of a session that carries one --------------------------------------------
# What a coordinator may run, written out here on purpose and independently of lib/commands.py ACTOR_VERBS: the test compares the two, so a verb that is
# added or moved in the table without this list changing fails. Every other verb of the table of commands is refused (the lead runs it).
COORD_ALLOWED = {
    "project": "template show list validate profile", "agent": "list models for", "role": "list show prompt check", "feature": "list status verify",
    "marshal": "status check handoff", "upstream": "status review", "campaign": "show check log", "backlog": "graph list", "release": "plan status",
    "doctor": "", "env": "show check", "instances": "list show", "skill": "list show effective check", "tool": "list show effective check",
    "packs": "load check", "status": "", "report": "", "watch": "", "methodology": "list show check files deployment", "cloud": "list show check",
    "provider": "list show check addenda notes model", "noticed": "list", "team": "brief check contract", "memory": "lint get tiers check",
    "canon": "check plan audit", "credential": "check", "discover": "sources search recommend show", "lead": "usage compact-check status",
    "supervise": "status hooks", "local": "list prepare run verify clean", "review": "check",
}
LABEL = "lead-1:coord:alpha:1"
sys.path.insert(0, ROOT + "/lib")
import commands as C  # noqa: E402
import help as H  # noqa: E402


def gate(argv, label=LABEL):
    """(exit status, standard error) of the narrowing for one command line, with QARGI_ACTOR set to label (None: unset)."""
    import contextlib, io
    saved = os.environ.pop("QARGI_ACTOR", None)
    if label is not None:
        os.environ["QARGI_ACTOR"] = label
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            rc = H.actor_gate(argv)
    finally:
        os.environ.pop("QARGI_ACTOR", None)
        if saved is not None:
            os.environ["QARGI_ACTOR"] = saved
    return rc, err.getvalue()


class ActorLabelForm(unittest.TestCase):
    def test_the_form(self):
        for ok, want in (("lead-1:coord:alpha:1", ("lead-1", "alpha", "1")), ("a:coord:a-b-2:10", ("a", "a-b-2", "10")),
                         ("user@host.example:coord:x:7", ("user@host.example", "x", "7")), ("a:b+c:coord:f:3", ("a:b+c", "f", "3")),
                         ("x:coord:coord:coord:5", ("x:coord", "coord", "5"))):
            self.assertEqual(H.actor_parse(ok), want, ok)

    def test_each_malformed_form_is_none(self):
        long_lead = "a" * 118
        for bad in ("", " ", "x", "lead", "lead:coord:alpha", "lead:coord:alpha:", "lead:coord:alpha:0", "lead:coord:alpha:01", "lead:coord:alpha:-1", "lead:coord:alpha:1.5",
                    "lead:coord:alpha:x", "lead:coordx:alpha:1", "lead:Coord:alpha:1", "lead:coord::1", ":coord:alpha:1", "lead:coord:Alpha:1", "lead:coord:al_pha:1",
                    "lead:coord:alpha-:1", "lead:coord:-alpha:1", "lead:coord:a--b:1", "lead/x:coord:alpha:1", "le ad:coord:alpha:1", "lead:coord:alpha:1 ", " lead:coord:alpha:1",
                    "lead:coord:alpha:1\n", "lead\n:coord:alpha:1", "lead:coord:alpha:1:2", "lead:coord:al:pha:1", "lead:coord:%s:1" % ("f" * 41),
                    long_lead + ":coord:alpha:1", "lead:coord:alpha:١", "léad:coord:alpha:1"):
            self.assertIsNone(H.actor_parse(bad), repr(bad))
        self.assertEqual(len(long_lead + ":coord:alpha:1"), 132)
        self.assertEqual(H.actor_parse("a" * 114 + ":coord:alpha:1"), ("a" * 114, "alpha", "1"))   # 128 characters: the longest
        self.assertIsNone(H.actor_parse("a" * 115 + ":coord:alpha:1"))

    def test_unset_and_empty_are_no_label(self):
        for label in (None, ""):
            self.assertEqual(gate(["feature", "finish", "alpha"], label), (0, ""))
            self.assertEqual(gate(["release", "push", "1.0.0", "--approved", "w"], label), (0, ""))

    def test_a_malformed_label_is_a_usage_error_for_every_verb_that_goes_through_the_gate(self):
        for argv in (["feature", "list"], ["doctor"], ["local", "list"], ["marshal", "status", "alpha"], ["project", "show"], ["feature", "finish", "alpha"], ["campaign", "show"]):
            rc, err = gate(argv, "lead/x:coord:alpha:1")
            self.assertEqual(rc, 2, argv)
            self.assertIn("<lead-id>:coord:<feature>:<n>", err)
            self.assertIn("never /", err)
            self.assertIn("is set and is not a coordinator label", err)

    def test_help_hooks_and_a_bare_area_pass_the_gate(self):
        for argv in (["feature", "--help"], ["feature", "finish", "--help"], ["hook", "tool-use"], ["feature"], ["nosuch", "x"], []):
            self.assertEqual(gate(argv), (0, ""), argv)
        self.assertEqual(gate(["hook", "tool-use"], "junk")[0], 0)      # a run-event hook never fails, whatever the label
        self.assertEqual(gate(["feature", "finish", "--help"], "junk")[0], 0)       # nor does a request for help
        self.assertEqual(gate(["feature", "list"], "junk")[0], 2)


class ActorVerbTable(unittest.TestCase):
    def verbs(self):
        for area, spec in C.COMMANDS.items():
            if area in ("help", "version", "hook"):
                continue
            vs = spec.get("verbs")
            for v in (vs if isinstance(vs, dict) else [""]):
                yield area, v

    def test_every_name_of_the_table_is_a_verb_and_the_options_exist(self):
        have = set(self.verbs())
        for key, names in C.ACTOR_VERBS.items():
            self.assertIn(key, have, key)
            self.assertIn(names, ("", "run", "feature", "base"), key)
        for (area, verb), opts in C.ACTOR_OPTS.items():
            self.assertIn((area, verb), C.ACTOR_VERBS)
            flags = {o["flag"] for o in C.COMMANDS[area]["verbs"][verb]["opts"]}
            for o in opts:
                self.assertIn(o, flags, (area, verb, o))

    def test_exactly_the_listed_verbs_are_allowed_and_every_other_is_refused_by_name(self):
        allowed = {(a, v) for a, words in COORD_ALLOWED.items() for v in (words.split() or [""])}
        self.assertEqual(set(C.ACTOR_VERBS), allowed)
        refused = 0
        for area, verb in self.verbs():
            argv = [x for x in (area, verb) if x]
            rc, err = gate(argv)
            if (area, verb) in allowed:
                self.assertEqual((rc, err), (0, ""), argv)
                continue
            refused += 1
            self.assertEqual(rc, 2, argv)
            self.assertEqual(err.count("\n"), 1, err)
            self.assertIn("refused under the coordinator label %s:" % LABEL, err)
            self.assertIn("a coordinator does not run %s;" % " ".join(argv), err)
            self.assertIn("the lead runs it", err)
        self.assertEqual(refused, len(list(self.verbs())) - len(allowed))

    def test_the_lead_only_acts_of_the_task_are_refused(self):
        for argv in (["feature", "finish", "alpha"], ["release", "start", "1.0.0"], ["release", "push", "1.0.0"], ["release", "finish", "1.0.0"], ["release", "fix", "1.0.0"],
                     ["release", "site", "1.0.0"], ["release", "publish", "1.0.0"], ["release", "step", "1.0.0", "x"], ["branch", "prune"], ["marshal", "takeover", "alpha"],
                     ["marshal", "forget", "alpha"], ["marshal", "release", "alpha"], ["marshal", "take", "alpha"], ["marshal", "claim", "alpha"], ["upgrade"],
                     ["project", "set", "p", "k", "v"], ["provider", "accept", "x"], ["packs", "apply", "p"], ["memory", "init", "p"], ["skill", "import", "d"], ["local", "close", "d"],
                     ["review", "apply", "d"], ["feature", "merge", "alpha", "agent/x"], ["backlog", "done"], ["ref", "record", "x"], ["export"], ["import"], ["discover", "install", "x"]):
            self.assertEqual(gate(argv)[0], 2, argv)

    def test_an_option_that_is_the_leads_refuses_an_allowed_verb(self):
        for argv, why in ((["release", "plan", "1.0.0", "--approved", "w"], "--approved"), (["release", "plan", "1.0.0", "--approved=w"], "--approved"),
                          (["feature", "verify", "alpha", "--approved", "w"], "--approved"), (["local", "list", "--approved"], "--approved"),
                          (["doctor", "--approved", "w"], "--approved"), (["release", "plan", "1.0.0", "--again"], "--again"),
                          (["marshal", "handoff", "alpha", "--write", "/x"], "--write"), (["local", "clean", "/x", "--discard"], "--discard"),
                          (["local", "clean", "--applied", "--scratch", "/x"], "--applied"), (["local", "clean", "--stale", "3", "--scratch", "/x", "--yes"], "--stale"),
                          (["local", "clean", "--orphans"], "--orphans"), (["local", "clean", "/x", "--yes"], "--yes"),
                          (["doctor", "--push"], "--push"), (["feature", "status", "alpha", "--push=origin"], "--push")):
            rc, err = gate(argv)
            self.assertEqual(rc, 2, argv)
            self.assertIn(why, err)
            self.assertIn("the lead runs it", err)

    def test_the_label_is_not_an_identity_the_verbs_compare(self):
        # nothing of the marshal, the leases or the approvals reads it: only help.py (the gate and its parser), lib.sh (actor_label) and local.sh (the run's record) name it
        import glob
        users = []
        for f in glob.glob(os.path.join(ROOT, "lib", "*")):
            if os.path.isfile(f):
                with open(f, errors="replace") as h:
                    if "QARGI_ACTOR" in h.read():
                        users.append(os.path.basename(f))
        users.sort()
        self.assertEqual(users, ["commands.py", "help.py", "lib.sh", "local.sh"])


class ActorFeatureNarrowing(unittest.TestCase):
    """A local or review verb that names a run is refused when the run's base is not the label's feature; a feature verb that names a feature, for another feature."""

    @classmethod
    def setUpClass(cls):
        cls.d = tempfile.mkdtemp(dir=os.environ["TMPDIR"])
        os.makedirs(os.path.join(cls.d, "state"))
        cls.runs = {}
        rows = []
        for name, base in (("qargi.aaaaaa", "feature/alpha"), ("qargi.bbbbbb", "feature/beta"), ("qargi.cccccc", "develop")):
            run = os.path.join(cls.d, "runs", name)
            os.makedirs(os.path.join(run, "out"))
            cls.runs[name] = run
            rows.append({"run": run, "base": base, "slug": name[-6:]})
        with open(os.path.join(cls.d, "state", "local-runs.jsonl"), "w") as f:
            f.write("not json\n" + "".join(json.dumps(r) + "\n" for r in rows))
        os.makedirs(os.path.join(cls.d, "loose", "out"))
        cls._state = os.environ.get("QARGI_STATE")
        os.environ["QARGI_STATE"] = os.path.join(cls.d, "state")

    @classmethod
    def tearDownClass(cls):
        if cls._state is None:
            os.environ.pop("QARGI_STATE", None)
        else:
            os.environ["QARGI_STATE"] = cls._state
        subprocess.run(["rm", "-rf", cls.d])

    def test_a_feature_verb_for_the_labels_feature_and_not_for_another(self):
        for verb in ("status", "verify"):
            self.assertEqual(gate(["feature", verb, "alpha"]), (0, ""))
            rc, err = gate(["feature", verb, "beta"])
            self.assertEqual(rc, 2)
            self.assertIn("feature beta", err)
            self.assertIn("this coordinator's feature is alpha", err)
            self.assertIn("the lead runs it", err)
        self.assertEqual(gate(["feature", "list"]), (0, ""))                       # it names no feature
        self.assertEqual(gate(["feature", "status", "beta"], "lead-1:coord:beta:3"), (0, ""))
        self.assertEqual(gate(["feature", "status", "--project", "p", "alpha"]), (0, ""))   # an option's value is no feature name
        self.assertEqual(gate(["feature", "status", "--project", "alpha", "beta"])[0], 2)

    def test_an_undeclared_option_fails_closed(self):
        # feature.sh reads --purpose with a value and --keep and --resolved without, and the table of verify declares none of them (--plan it declares since
        # verify.environment: a waiver needs it): without this the gate read alpha, the verb ran beta
        for line in (["feature", "verify", "--purpose", "alpha", "beta"], ["feature", "verify", "--keep", "alpha", "beta"], ["feature", "status", "--purpose", "alpha", "beta"],
                     ["feature", "verify", "--purpose=x", "alpha"], ["feature", "verify", "alpha", "--bogus"], ["feature", "verify", "-x", "alpha"], ["feature", "verify", "--", "alpha"]):
            rc, err = gate(line)
            self.assertEqual(rc, 2, line)
            self.assertIn("is not an option the verb declares", err)
            self.assertIn("the lead runs it", err)
        self.assertEqual(gate(["feature", "verify", "--project", "p", "alpha"]), (0, ""))
        self.assertEqual(gate(["feature", "verify", "alpha", "--assume-unreachable-ok"]), (0, ""))
        base = ["local", "prepare", "--repo", "/r", "--slug", "s", "--scratch", "/x", "--base", "feature/alpha"]
        self.assertEqual(gate(base + ["--bogus", "feature/beta"])[0], 2)
        self.assertEqual(gate(["local", "verify", self.runs["qargi.aaaaaa"], "--bogus"])[0], 2)

    def test_prepare_needs_the_labels_feature_as_its_base(self):
        base = ["local", "prepare", "--repo", "/r", "--slug", "s", "--scratch", "/x"]
        self.assertEqual(gate(base + ["--base", "feature/alpha"]), (0, ""))
        self.assertEqual(gate(base + ["--base=feature/alpha"]), (0, ""))
        for bad in ("feature/beta", "develop", "alpha", "feature/alpha2", "feature/alpha/x", ""):
            rc, err = gate(base + ["--base", bad])
            self.assertEqual(rc, 2, bad)
            self.assertIn("feature/alpha", err)
            self.assertIn("the lead runs it", err)
        self.assertEqual(gate(base + ["--base", "feature/alpha", "--base", "develop"])[0], 2)   # the last --base would win: every one is checked
        self.assertEqual(gate(base), (0, ""))                                      # no base: the verb refuses it itself

    def test_a_local_verb_that_names_a_run(self):
        a, b, c = (self.runs[n] for n in ("qargi.aaaaaa", "qargi.bbbbbb", "qargi.cccccc"))
        for verb in ("verify", "run", "clean"):
            self.assertEqual(gate(["local", verb, a]), (0, ""), verb)
            self.assertEqual(gate(["local", verb, a + "/"]), (0, ""), verb)
            for other in (b, c, os.path.join(self.d, "runs", "qargi.zzzzzz")):
                rc, err = gate(["local", verb, other])
                self.assertEqual(rc, 2, (verb, other))
                self.assertIn("a coordinator does not run local %s on" % verb, err)
                self.assertIn("the lead runs it", err)
        self.assertEqual(gate(["local", "verify", "--saved", "qargi.aaaaaa"]), (0, ""))
        self.assertEqual(gate(["local", "verify", "--saved", "qargi.bbbbbb"])[0], 2)
        self.assertEqual(gate(["local", "verify", "--saved=qargi.bbbbbb"])[0], 2)
        self.assertEqual(gate(["local", "run", a, "--task", b, "--dry-run"]), (0, ""))   # --task's value is a file, not a run
        self.assertEqual(gate(["local", "verify", "--mine"]), (0, ""))
        self.assertEqual(gate(["local", "list"]), (0, ""))
        self.assertEqual(gate(["local", "list", "--scratch", b]), (0, ""))
        self.assertEqual(gate(["local", "verify", a], "lead-2:coord:beta:1")[0], 2)
        self.assertEqual(gate(["local", "verify", b], "lead-2:coord:beta:1"), (0, ""))   # feature-scoped: any coordinator of the feature, a predecessor's run too

    def test_review_check_reads_a_run_by_its_out_or_the_run(self):
        a, b = self.runs["qargi.aaaaaa"], self.runs["qargi.bbbbbb"]
        self.assertEqual(gate(["review", "check", a + "/out"]), (0, ""))
        self.assertEqual(gate(["review", "check", a]), (0, ""))
        self.assertEqual(gate(["review", "check", b + "/out"])[0], 2)
        self.assertEqual(gate(["review", "check", b])[0], 2)
        self.assertEqual(gate(["review", "check", os.path.join(self.d, "loose", "out")]), (0, ""))   # an output no run of the registry owns: it only reads it
        self.assertEqual(gate(["review", "check", "--allow-empty", a + "/out"]), (0, ""))

    def test_an_empty_word_names_nothing_and_is_refused(self):
        # lib/local.sh clean skips an empty word and cleans the next one; the gate read "" as realpath(""), the current directory: inside run A, clean "" B passed
        a, b = self.runs["qargi.aaaaaa"], self.runs["qargi.bbbbbb"]
        cwd = os.getcwd()
        os.chdir(a)
        try:
            for line in (["local", "clean", "", b], ["local", "clean", b, ""], ["local", "verify", "", b], ["local", "run", "", b], ["local", "verify", "--saved", "", "qargi.bbbbbb"],
                         ["feature", "status", "", "alpha"], ["feature", "verify", "alpha", ""], ["review", "check", "", b + "/out"]):
                rc, err = gate(line)
                self.assertEqual(rc, 2, line)
                self.assertIn("with an empty word", err)
                self.assertIn("the lead runs it", err)
            self.assertEqual(gate(["local", "clean", "."]), (0, ""))          # the current directory, named, is run A: its base is the label's feature
            self.assertEqual(gate(["local", "clean", "", a])[0], 2)           # refused even when every other word is the label's own
            self.assertEqual(gate(["local", "clean", b])[0], 2)
        finally:
            os.chdir(cwd)
        self.assertEqual(gate(["local", "list", ""]), (0, ""))              # a verb that names nothing is not narrowed here: it reads its own words

    def test_every_positional_is_checked(self):
        a, b = self.runs["qargi.aaaaaa"], self.runs["qargi.bbbbbb"]
        self.assertEqual(gate(["local", "clean", a, b])[0], 2)
        self.assertEqual(gate(["local", "clean", b, a])[0], 2)
        self.assertEqual(gate(["local", "verify", a, b])[0], 2)
        self.assertEqual(gate(["review", "check", a + "/out", b + "/out"])[0], 2)
        self.assertEqual(gate(["feature", "status", "alpha", "beta"])[0], 2)
        self.assertEqual(gate(["feature", "status", "beta", "alpha"])[0], 2)
        self.assertEqual(gate(["local", "verify", "--saved", "qargi.aaaaaa", b])[0], 2)

    def test_the_run_of_local_run_and_verify_is_the_first_word(self):
        a, b = self.runs["qargi.aaaaaa"], self.runs["qargi.bbbbbb"]
        rc, err = gate(["local", "run", "--timeout", b, a])               # the script takes $1, --timeout, as the run: the gate read a, the word after the option's value
        self.assertEqual(rc, 2)
        self.assertIn("not its first word", err)
        for verb in ("run", "verify"):
            self.assertEqual(gate(["local", verb, "--bogus", a])[0], 2, verb)
            self.assertEqual(gate(["local", verb, a]), (0, ""), verb)
        self.assertEqual(gate(["local", "run", a, "--timeout", "5"]), (0, ""))
        self.assertEqual(gate(["local", "run", "--timeout", "5", a])[0], 2)   # fail closed: the script reads --timeout as the run, whatever follows
        self.assertEqual(gate(["local", "verify", "--saved", "qargi.aaaaaa"]), (0, ""))
        self.assertEqual(gate(["local", "verify", "--mine"]), (0, ""))
        self.assertEqual(gate(["local", "run", "--json", a]), (0, ""))        # bin/qargi takes --json out before the script runs, so a is its first word
        self.assertEqual(gate(["local", "run", "--json", "--timeout", b, a])[0], 2)

    def test_json_is_the_dispatchers_option_and_passes_on_a_narrowed_verb(self):
        # bin/qargi runs the call again without --json (lib/jsonplan.py), so the gate runs twice: with it and without
        a, b = self.runs["qargi.aaaaaa"], self.runs["qargi.bbbbbb"]
        for line in (["feature", "status", "alpha", "--json"], ["feature", "status", "--json", "alpha"], ["feature", "verify", "alpha", "--json"], ["local", "verify", a, "--json"],
                     ["review", "check", a + "/out", "--json"], ["local", "clean", a, "--json"]):
            self.assertEqual(gate(line), (0, ""), line)
        for line in (["feature", "status", "beta", "--json"], ["local", "verify", b, "--json"], ["feature", "status", "alpha", "--json", "--bogus"]):
            self.assertEqual(gate(line)[0], 2, line)
        self.assertEqual(gate(["marshal", "status", "alpha", "--json"]), (0, ""))   # a verb that declares --json keeps its own

    def test_a_copy_of_a_run_is_read_by_its_id_as_review_sh_does(self):
        # review check resolves a directory it does not find in the registry by its basename (reg_id) and renews the lease of that run's feature: a copy of run B, elsewhere,
        # holds B's id
        b = self.runs["qargi.bbbbbb"]
        for sub in ("copy1", "copy2"):
            os.makedirs(os.path.join(self.d, sub, "qargi.bbbbbb", "out"))
            os.makedirs(os.path.join(self.d, sub, "qargi.aaaaaa", "out"))
        for sub in ("copy1", "copy2"):
            c = os.path.join(self.d, sub, "qargi.bbbbbb")
            for word in (c, c + "/", c + "/out"):
                rc, err = gate(["review", "check", word])
                self.assertEqual(rc, 2, word)
                self.assertIn("based on feature/beta", err)
            self.assertEqual(gate(["review", "check", os.path.join(self.d, sub, "qargi.aaaaaa", "out")]), (0, ""))
            self.assertEqual(gate(["local", "verify", c])[0], 2)
        self.assertEqual(gate(["review", "check", os.path.join(self.d, "loose", "out")]), (0, ""))   # a name that is no run id stays a plain output
        os.makedirs(os.path.join(self.d, "copy3", "qargi.zzzzzz", "out"))
        self.assertEqual(gate(["review", "check", os.path.join(self.d, "copy3", "qargi.zzzzzz", "out")]), (0, ""))   # an id the registry does not hold: no run of this lead
        self.assertIn(b, self.runs.values())

    def test_no_registry_means_no_known_run(self):
        os.environ["QARGI_STATE"] = os.path.join(self.d, "nostate")
        try:
            self.assertEqual(gate(["local", "verify", self.runs["qargi.aaaaaa"]])[0], 2)
            self.assertEqual(gate(["local", "list"]), (0, ""))
        finally:
            os.environ["QARGI_STATE"] = os.path.join(self.d, "state")


def check(argv, label=LABEL):
    """(exit status, standard error) of the narrowing at the point of use (help.py actor-check) with QARGI_ACTOR set to label (None: unset)."""
    import contextlib, io
    saved = os.environ.pop("QARGI_ACTOR", None)
    if label is not None:
        os.environ["QARGI_ACTOR"] = label
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            rc = H.main(["actor-check"] + argv)
    finally:
        os.environ.pop("QARGI_ACTOR", None)
        if saved is not None:
            os.environ["QARGI_ACTOR"] = saved
    return rc, err.getvalue()


class ActorCheckAtThePointOfUse(unittest.TestCase):
    """What the scripts ask once they have resolved their target (lib.sh actor_check): one parse, the label's feature, the same message family as the gate."""

    def test_unset_and_empty_go_on_whatever_the_value(self):
        for label in (None, ""):
            for kind, v in (("feature", "beta"), ("prepare-base", "main"), ("run-base", "feature/beta"), ("run-unknown", "x"), ("run-word", "--again")):
                self.assertEqual(check([kind, "w", v], label), (0, ""), (kind, label))

    def test_the_label_s_feature_goes_on_and_any_other_is_refused(self):
        self.assertEqual(check(["feature", "feature status", "alpha"]), (0, ""))
        self.assertEqual(check(["prepare-base", "local prepare", "feature/alpha"]), (0, ""))
        self.assertEqual(check(["run-base", "local run", "feature/alpha"]), (0, ""))
        for kind, v, text in (("feature", "beta", "run feature status on feature beta: this coordinator's feature is alpha"),
                              ("prepare-base", "feature/beta", "prepare a run on feature/beta: this coordinator's runs are based on feature/alpha"),
                              ("prepare-base", "", "prepare a run on an empty base"),
                              ("run-base", "feature/beta", "run feature status on a run based on feature/beta: this coordinator's runs are based on feature/alpha"),
                              ("run-base", "", "on a run based on no branch"),
                              ("run-base", "feature/alpha2", "based on feature/alpha2"),
                              ("run-unknown", "/x/qargi.abcdef", "the lead's registry does not name it"),
                              ("run-word", "--again", "starts with a dash")):
            rc, err = check([kind, "feature status", v])
            self.assertEqual(rc, 2, (kind, v))
            self.assertIn(text, err)
            self.assertIn("refused under the coordinator label %s: a coordinator does not " % LABEL, err)
            self.assertIn("Nothing was changed", err)

    def test_a_malformed_label_and_a_malformed_call_are_usage_errors(self):
        rc, err = check(["feature", "w", "alpha"], "lead/x:coord:alpha:1")
        self.assertEqual(rc, 2)
        self.assertIn("<lead-id>:coord:<feature>:<n>", err)
        for argv in ([], ["feature"], ["feature", "w"], ["nosuch", "w", "v"], ["feature", "w", "v", "extra"]):
            self.assertEqual(check(argv)[0], 2, argv)


class ActorLabelAndTheMemberGuard(unittest.TestCase):
    """A member that sets QARGI_ACTOR gains nothing: the guard judges the command as it does without it."""

    def test_the_verdict_is_the_same_with_and_without_the_label(self):
        import guard
        # hermetic: allow tmp (a word of a command line that is judged by the guard, never run)
        cmds = ["qargi local prepare --repo . --base feature/alpha --slug x --scratch /tmp/x", "qargi local verify --mine", "qargi local clean /x/qargi.abcdef",
                "qargi feature finish alpha", "qargi marshal takeover alpha", "qargi release push 1.0.0", "qargi review apply /x/qargi.abcdef",
                "qargi doctor", "qargi review check out", "qargi local list", "qargi marshal status alpha", "qargi local report /x/qargi.abcdef"]
        saved = guard.CLASS
        try:
            for cls in ("write", "read-only"):
                guard.CLASS = cls
                for c in cmds:
                    plain = guard.judge(guard.Call("shell", "Bash", c, "", os.getcwd()))
                    for pre in ("QARGI_ACTOR=%s " % LABEL, "env QARGI_ACTOR=%s " % LABEL):
                        self.assertEqual(guard.judge(guard.Call("shell", "Bash", pre + c, "", os.getcwd())), plain, (cls, pre + c))
        finally:
            guard.CLASS = saved


if __name__ == "__main__":
    unittest.main()
