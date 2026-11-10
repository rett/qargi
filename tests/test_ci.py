#!/usr/bin/env python3
"""The CI workflow (.github/workflows/test.yml) and the durations file it shards by: the workflow parses, its triggers have no
schedule, every action is pinned to a full commit SHA with a version comment and checks out without credentials, the concurrency
keys are as intended, each job's timeout is not below what the manifest's budgets ask for (the arithmetic in the workflow's comment,
recomputed here), and tests/durations.txt balances four shards (the slowest shard plans at most 1.3 times the fastest).
Run: python3 tests/test_ci.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import math, os, re, subprocess, unittest

try:
    import yaml
except ImportError:   # the parsing tests are skipped, the text tests still run
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(ROOT, ".github", "workflows", "test.yml")
ACTIONS = [WF, os.path.join(ROOT, ".github", "actions", "tools", "action.yml")]
SLOW = 1.5      # the runner reports a step over 1.5 x its budget
SETUP = 600     # seconds for checkout, packages and the git identity
SHARDS = 4


def plan(*args):
    """tests/run.sh --plan: (the shard-plan line or '', [(weight, command)])."""
    p = subprocess.run(["bash", "tests/run.sh", "--plan", *args], cwd=ROOT, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    lines = p.stdout.splitlines()
    head = lines[0] if lines and lines[0].startswith("shard plan") else ""
    return head, [(int(w), c) for w, c in (l.split(" ", 1) for l in lines[1 if head else 0:])]


def shard_totals(*extra):
    """The planned seconds of each of the four shards, as the runner prints its plan."""
    head, _ = plan("--shard", "1/%d" % SHARDS, *extra)
    return [int(x) for x in re.findall(r"=(\d+)s\(", head)]


def text(path):
    with open(path) as f:
        return f.read()


@unittest.skipUnless(yaml, "PyYAML is not installed")
class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.doc = yaml.safe_load(text(WF))
        cls.on = cls.doc.get("on", cls.doc.get(True))   # YAML 1.1 reads the key `on` as true

    def test_parses_and_has_the_jobs(self):
        self.assertEqual(sorted(self.doc["jobs"]), ["pr", "result", "suite"])

    def test_triggers_and_no_schedule(self):
        self.assertEqual(sorted(self.on), ["pull_request", "push", "workflow_dispatch"])
        self.assertEqual(self.on["push"]["branches"], ["develop"])
        self.assertIn("labeled", self.on["pull_request"]["types"])
        self.assertNotIn("schedule", self.on)
        self.assertNotIn("schedule", text(WF).replace("There is no scheduled run", ""))

    def test_concurrency(self):
        c = self.doc["concurrency"]
        self.assertIn("github.sha", c["group"])      # a push to develop has its commit as its key: no run replaces another
        self.assertIn("github.ref", c["group"])      # a pull request has its ref: a newer run replaces an older one
        self.assertEqual(c["cancel-in-progress"], "${{ github.event_name == 'pull_request' }}")

    def test_the_pull_request_job_runs_the_fast_tier_and_the_changed_areas(self):
        job = self.doc["jobs"]["pr"]
        self.assertIn("full-suite", job["if"])
        self.assertIn("!contains(", job["if"])
        self.assertIn("!= 'master'", job["if"])
        run = [s["run"] for s in job["steps"] if "run" in s and "tests/run.sh" in s["run"]]
        self.assertEqual(len(run), 1)
        self.assertRegex(run[0], r"tests/run\.sh --tier fast --changed-from ")

    def test_the_suite_job_runs_four_shards_with_the_durations(self):
        job = self.doc["jobs"]["suite"]
        self.assertEqual(job["strategy"]["matrix"]["shard"], list(range(1, SHARDS + 1)))
        self.assertIs(job["strategy"]["fail-fast"], False)
        for want in ("github.event_name != 'pull_request'", "github.base_ref == 'master'", "full-suite"):
            self.assertIn(want, job["if"])
        run = [s["run"] for s in job["steps"] if "run" in s and "tests/run.sh" in s["run"]]
        self.assertEqual(run, ["bash tests/run.sh --shard ${{ matrix.shard }}/%d --durations tests/durations.txt" % SHARDS])

    def test_the_result_job_waits_for_every_part_and_always_runs(self):
        job = self.doc["jobs"]["result"]
        self.assertEqual(sorted(job["needs"]), ["pr", "suite"])
        self.assertEqual(job["if"], "always()")

    def test_every_checkout_is_without_credentials_and_the_git_identity_is_set(self):
        for name, job in self.doc["jobs"].items():
            for s in job["steps"]:
                if str(s.get("uses", "")).startswith("actions/checkout@"):
                    self.assertIs(s["with"]["persist-credentials"], False, name)
        for name in ("pr", "suite"):
            self.assertTrue(any("git config --global user.email" in s.get("run", "") for s in self.doc["jobs"][name]["steps"]), name)

    def test_every_job_has_a_timeout_not_below_the_budgets(self):
        # the arithmetic of the comment in the workflow: the heaviest shard's budgets x 1.5 + the setup, in minutes, to the next 5
        totals = shard_totals()
        need = math.ceil((SLOW * max(totals) + SETUP) / 60)
        for name in ("pr", "suite"):
            self.assertGreaterEqual(self.doc["jobs"][name]["timeout-minutes"], need, "%s: the budgets ask for %d min" % (name, need))
        said = int(re.search(r"plans (\d+) s of budgets", text(WF)).group(1))   # the comment keeps up with the manifest, within 5 %
        self.assertLessEqual(abs(said - max(totals)), max(totals) * 0.05, "the comment says %d s, the manifest plans %d s" % (said, max(totals)))
        total = sum(totals)                  # the other figure of the comment: all the budgets, one after the other
        said_all = int(re.search(r"\(now (\d+) s x 1\.5 = \d+ min", text(WF)).group(1))
        self.assertLessEqual(abs(said_all - total), total * 0.05, "the comment says %d s in all, the manifest plans %d s" % (said_all, total))
        for name, job in self.doc["jobs"].items():
            self.assertIsInstance(job.get("timeout-minutes"), int, name)


class Pins(unittest.TestCase):
    def test_every_action_is_pinned_to_a_full_commit_sha_with_a_version_comment(self):
        n = 0
        for f in ACTIONS:
            for line in text(f).splitlines():
                m = re.match(r"\s*(?:-\s+)?uses:\s*(\S+)(.*)$", line)
                if not m or m.group(1).startswith("./"):
                    continue
                n += 1
                self.assertRegex(m.group(1), r"^[\w.-]+/[\w./-]+@[0-9a-f]{40}$", "%s: %s" % (f, line.strip()))
                self.assertRegex(m.group(2), r"^\s+#\s+v\d+(\.\d+)*\s*$", "%s: no version comment: %s" % (f, line.strip()))
        self.assertGreaterEqual(n, 3)

    @unittest.skipUnless(yaml, "PyYAML is not installed")
    def test_the_action_parses_and_caches_the_packages_by_their_list(self):
        a = yaml.safe_load(text(ACTIONS[1]))
        self.assertEqual(a["runs"]["using"], "composite")
        cache = [s for s in a["runs"]["steps"] if str(s.get("uses", "")).startswith("actions/cache@")]
        self.assertEqual(len(cache), 1)
        self.assertIn("inputs.packages", cache[0]["with"]["key"])
        self.assertEqual(sorted(a["inputs"]["packages"]["default"].split()), ["jq", "shellcheck"])


class Durations(unittest.TestCase):
    def test_the_file_is_in_the_format_of_save_durations(self):
        lines = text(os.path.join(ROOT, "tests", "durations.txt")).splitlines()
        self.assertGreater(len(lines), 50)
        for l in lines:
            self.assertRegex(l, r"^\d+ \S.*$")
        self.assertEqual(len(lines), len(set(l.split(" ", 1)[1] for l in lines)), "a command twice")

    def test_every_step_of_the_suite_has_a_row_and_every_row_a_step(self):
        # a step with no row counts as its budget in the shard plan, which unbalances the shards of the CI run
        steps = set()
        for l in text(os.path.join(ROOT, "tests", "suite.txt")).splitlines():
            l = l.strip()
            if l and not l.startswith("#"):
                steps.add(l.split("|")[4].strip())
        rows = set(l.split(" ", 1)[1] for l in text(os.path.join(ROOT, "tests", "durations.txt")).splitlines() if l.strip())
        self.assertEqual(sorted(steps - rows), [], "steps of tests/suite.txt with no row in tests/durations.txt")
        self.assertEqual(sorted(rows - steps), [], "rows of tests/durations.txt with no step in tests/suite.txt")

    def test_four_shards_by_the_durations_are_balanced_within_1_3(self):
        t = shard_totals("--durations", "tests/durations.txt")
        self.assertTrue(all(t), t)
        self.assertLessEqual(max(t) / min(t), 1.3, "planned seconds per shard: %s" % t)

    def test_four_shards_by_the_budgets_are_balanced_within_1_3(self):
        t = shard_totals()
        self.assertLessEqual(max(t) / min(t), 1.3, "planned seconds per shard: %s" % t)

    def test_the_shards_together_are_the_whole_manifest(self):
        _, whole = plan()
        parts = []
        for i in range(1, SHARDS + 1):
            parts += [c for _, c in plan("--shard", "%d/%d" % (i, SHARDS), "--durations", "tests/durations.txt")[1]]
        self.assertEqual(sorted(parts), sorted(c for _, c in whole))


if __name__ == "__main__":
    unittest.main()
