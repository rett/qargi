#!/usr/bin/env python3
"""The history of the whole-suite runs and the review reports (lib/history.py): the append-only file (modes, no rewrite, a torn last line, the attempt
number, the cap of the logs and its exception for the latest pass of a branch), the entries against their registry files, the tolerant reader, and
the verb `qargi history` (text, --json, show, the filters, the member guard). Hermetic and fast. Run: python3 tests/test_history.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import history as H  # noqa: E402
import history_write as W  # noqa: E402
import jsonkind as K  # noqa: E402

HEAD = "a" * 40
TREE = "b" * 40
CMD = "bash tests/run.sh -j 2"


def slurp(path):
    with open(path) as f:
        return f.read()


def load(path):
    with open(path) as f:
        return json.load(f)


def mode(path):
    return stat.S_IMODE(os.stat(path).st_mode)


def errors(findings):
    return ["%s %s %s" % (f[0], f[1], f.message) for f in findings]


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="history.")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.state)
        self.saved = os.environ.get("QARGI_STATE")
        os.environ["QARGI_STATE"] = self.state          # lib/history.py reads the state from the environment, as the verbs do

    def tearDown(self):
        if self.saved is None:
            os.environ.pop("QARGI_STATE", None)
        else:
            os.environ["QARGI_STATE"] = self.saved
        subprocess.run(["rm", "-rf", self.tmp])

    def path(self, project="demo"):
        return H.history_path(project)

    def raw(self, project="demo"):
        with open(self.path(project), "rb") as f:
            return f.read()

    def make_log(self, text="ok   fine\n"):
        p = os.path.join(self.tmp, "run.log")
        with open(p, "w") as f:
            f.write(text)
        return p

    def write_suite(self, project="demo", result="pass", head=HEAD, tree=TREE, command=CMD, env_id="", branch="feature/x", names=None, gates=None, log=True,
                    name="x", started="2026-11-27T01:02:03Z", seconds=7, verb="feature verify"):
        """`history.py write suite` in this process (the state is the environment's); the failing names and the gates go through files."""
        args = ["suite", "--project", project, "--verb", verb, "--name", name, "--branch", branch, "--head", head, "--tree", tree,
                "--command=" + command, "--env-id=" + env_id, "--result", result, "--started", started, "--seconds", str(seconds), "--load-start", "0.50"]
        if log:
            args += ["--log", self.make_log()]
        if names is not None:
            n = os.path.join(self.tmp, "names")
            with open(n, "w") as f:
                f.write("".join(x + "\n" for x in names))
            args += ["--names", n]
        if gates is not None:
            g = os.path.join(self.tmp, "gates")
            with open(g, "w") as f:
                f.write("".join(json.dumps(x) + "\n" for x in gates))
            args += ["--gates", g]
        rc = W.write_main(args)
        self.assertEqual(rc, 0)
        return H.read(project, warn=False)[0][-1]

    def run_cli(self, *args, cwd=None, env=None):
        p = subprocess.run([BIN, *args], capture_output=True, text=True, cwd=cwd, env=env or dict(os.environ), timeout=60)
        return p.returncode, p.stdout, p.stderr


class AppendOnly(Base):
    def test_the_directory_is_700_and_the_file_600(self):
        self.write_suite()
        self.assertEqual(mode(os.path.dirname(self.path())), 0o700)
        self.assertEqual(mode(self.path()), 0o600)
        self.assertEqual(mode(os.path.join(self.state, "suite-logs", "runs")), 0o700)

    def test_a_loose_directory_is_tightened_and_a_loose_file_too(self):
        d = os.path.dirname(self.path())
        os.makedirs(d, mode=0o755)
        os.chmod(d, 0o755)
        with open(self.path(), "w"):
            pass
        os.chmod(self.path(), 0o644)
        self.write_suite()
        self.assertEqual((mode(d), mode(self.path())), (0o700, 0o600))

    def test_an_append_never_changes_the_bytes_before_it(self):
        self.write_suite(result="fail", names=["FAIL one"])
        before = self.raw()
        inode = os.stat(self.path()).st_ino
        self.write_suite(result="pass")
        after = self.raw()
        self.assertTrue(after.startswith(before))
        self.assertGreater(len(after), len(before))
        self.assertEqual(os.stat(self.path()).st_ino, inode)        # the same file: nothing was renamed over it
        self.assertEqual(after.count(b"\n"), 2)
        self.assertTrue(after.endswith(b"\n"))

    def test_the_file_is_opened_for_append(self):
        text = slurp(os.path.join(LIB, "history.py"))
        self.assertIn("O_APPEND", text)
        self.assertIn("LOCK_EX", text)
        self.assertIn("os.fsync", text)

    def test_one_line_is_one_valid_entry(self):
        self.write_suite(result="fail", names=["FAIL: a"], gates=[{"name": "unit", "tier": "feature", "result": "fail", "seconds": 3}])
        lines = self.raw().decode().splitlines()
        self.assertEqual(len(lines), 1)
        doc = json.loads(lines[0])
        self.assertEqual(errors(K.validate(K.registry_path("qargi-history-entry"), lines[0])), [])
        self.assertEqual((doc["schema"], doc["kind"], doc["entry_kind"], doc["project"]), (1, "qargi-history-entry", "suite", "demo"))
        self.assertRegex(doc["id"], r"^[0-9a-f]{16}$")
        self.assertEqual((doc["head"], doc["tree"], doc["command"], doc["environment_id"]), (HEAD, TREE, CMD, None))
        self.assertEqual(doc["gates"], [{"name": "unit", "result": "fail", "seconds": 3}])
        self.assertEqual((doc["failing_tests"], doc["failing_total"], doc["result"], doc["seconds"], doc["attempt"]), (["FAIL: a"], 1, "fail", 7, 1))
        self.assertEqual((doc["started"], doc["load_start"]), ("2026-11-27T01:02:03Z", "0.50"))
        self.assertRegex(doc["ended"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertTrue(doc["load_end"] is None or re.match(r"^\d+\.\d+$", doc["load_end"]))

    def test_a_link_in_the_place_of_the_file_or_the_directory_is_refused(self):
        os.makedirs(os.path.join(self.tmp, "elsewhere"))
        os.symlink(os.path.join(self.tmp, "elsewhere"), os.path.join(self.state, "history"))
        buf = io.StringIO()
        with redirect_stderr(buf):
            self.assertEqual(W.write_main(["suite", "--project", "demo", "--verb", "feature verify", "--name", "x", "--branch", "b", "--head", HEAD, "--tree", TREE,
                                           "--command=c", "--result", "pass", "--started", "2026-11-27T01:02:03Z", "--seconds", "1"]), 1)
        self.assertIn("is a link", buf.getvalue())
        self.assertEqual(os.listdir(os.path.join(self.tmp, "elsewhere")), [])

    def test_an_entry_that_breaks_its_registry_file_is_not_written(self):
        entry = {"schema": 1, "kind": "qargi-history-entry", "entry_kind": "suite", "id": "not-hex", "project": "demo", "time": "2026-11-27T01:02:03Z"}
        with self.assertRaises(H.HistoryError):
            H.append("demo", entry)
        self.assertFalse(os.path.exists(self.path()))

    def test_concurrent_appends_get_distinct_attempts(self):
        code = ("import sys; sys.path.insert(0, %r); import history_write as W; import history as H; "
                "sys.exit(W.write_main(['suite', '--project', 'demo', '--verb', 'feature verify', '--name', 'x', '--branch', 'b', '--head', %r, '--tree', %r, "
                "'--command=' + %r, '--result', 'pass', '--started', '2026-11-27T01:02:03Z', '--seconds', '1']))" % (LIB, HEAD, TREE, CMD))
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code]) for _ in range(4)]
        self.assertEqual([p.wait(timeout=60) for p in procs], [0, 0, 0, 0])
        entries, skipped = H.read("demo")
        self.assertEqual(skipped, 0)
        self.assertEqual(sorted(e["attempt"] for e in entries), [1, 2, 3, 4])
        self.assertEqual(len({e["id"] for e in entries}), 4)


class Reader(Base):
    def test_a_torn_last_line_is_skipped_with_a_warning_and_never_fatal(self):
        self.write_suite()
        with open(self.path(), "ab") as f:
            f.write(b'{"schema":1,"kind":"qargi-history-entry","entry_kind":"suite","id":"0123')
        buf = io.StringIO()
        with redirect_stderr(buf):
            entries, skipped = H.read("demo")
        self.assertEqual((len(entries), skipped), (1, 1))
        self.assertIn("skipped 1 line(s)", buf.getvalue())
        quiet = io.StringIO()
        with redirect_stderr(quiet):
            H.read("demo", warn=False)
        self.assertEqual(quiet.getvalue(), "")

    def test_the_next_append_starts_a_line_of_its_own_and_keeps_the_torn_bytes(self):
        self.write_suite()
        with open(self.path(), "ab") as f:
            f.write(b'{"torn"')
        before = self.raw()
        self.write_suite(result="fail")
        after = self.raw()
        self.assertTrue(after.startswith(before))                      # nothing before the new line was touched
        self.assertEqual(after[len(before):len(before) + 1], b"\n")
        entries, skipped = H.read("demo", warn=False)
        self.assertEqual((len(entries), skipped), (2, 1))

    def test_garbage_lines_and_foreign_objects_are_skipped(self):
        good = self.write_suite()
        with open(self.path(), "ab") as f:
            f.write(b"\xff\xfe not json\n[1,2]\n{\"kind\":\"other\"}\n\n   \n")
        self.write_suite(result="fail")
        entries, skipped = H.read("demo", warn=False)
        self.assertEqual((len(entries), skipped), (2, 3))
        self.assertEqual(entries[0]["id"], good["id"])

    def test_no_file_is_no_entry(self):
        self.assertEqual(H.read("demo"), ([], 0))

    def test_select_by_kind_and_head_prefix(self):
        a = self.write_suite(head="1" * 40)
        b = self.write_suite(head="2" * 40, tree="c" * 40)
        entries = [a, b, {"entry_kind": "review", "base_sha": "2" * 40, "id": "x"}]
        self.assertEqual([e["id"] for e in H.select(entries, kind="suite")], [a["id"], b["id"]])
        self.assertEqual([e.get("id") for e in H.select(entries, head="2222")], [b["id"], "x"])
        self.assertEqual(H.select(entries, kind="review", head="1111"), [])


class Attempts(Base):
    def test_the_attempt_counts_the_earlier_runs_of_one_head_tree_and_command(self):
        self.assertEqual([self.write_suite()["attempt"] for _ in range(3)], [1, 2, 3])
        self.assertEqual(self.write_suite(head="c" * 40)["attempt"], 1)                       # another head
        self.assertEqual(self.write_suite(tree="d" * 40)["attempt"], 1)                       # another tree
        self.assertEqual(self.write_suite(command="make test")["attempt"], 1)                 # another command
        self.assertEqual(self.write_suite(env_id="e1")["attempt"], 1)                         # another environment id
        self.assertEqual(self.write_suite(env_id="e1")["attempt"], 2)
        self.assertEqual(self.write_suite(branch="feature/y")["attempt"], 4)                  # the branch is not part of it
        self.assertEqual(self.write_suite(project="other")["attempt"], 1)                     # nor does another project count
        self.assertEqual(self.write_suite(result="fail")["attempt"], 5)                       # a failed run counts as an attempt

    def test_attempt_number_ignores_review_entries(self):
        entries = [{"entry_kind": "review", "head": HEAD, "tree": TREE, "command": CMD, "environment_id": None}]
        self.assertEqual(H.attempt_number(entries, HEAD, TREE, CMD, None), 1)


class Logs(Base):
    def entries(self):
        return H.read("demo", warn=False)[0]

    def logs(self):
        d = os.path.join(self.state, "suite-logs", "runs")
        return sorted(f[:-4] for f in os.listdir(d)) if os.path.isdir(d) else []

    def test_each_run_keeps_its_log_with_mode_600(self):
        e = self.write_suite()
        self.assertEqual(e["log"], os.path.join(self.state, "suite-logs", "runs", e["id"] + ".log"))
        self.assertEqual(slurp(e["log"]), "ok   fine\n")
        self.assertEqual(mode(e["log"]), 0o600)
        self.assertIsNone(self.write_suite(log=False)["log"])

    def test_the_newest_20_logs_stay_and_the_oldest_are_removed_as_entries_are_appended(self):
        ids = [self.write_suite(result="fail", head="%040x" % i, branch="feature/x")["id"] for i in range(23)]
        self.assertEqual(self.logs(), sorted(ids[3:]))
        self.assertEqual(len(self.entries()), 23)                                             # the entries stay: only the logs are pruned
        self.assertTrue(all(e["log"] for e in self.entries()))

    def test_the_log_of_the_latest_pass_of_a_branch_is_never_pruned(self):
        kept = self.write_suite(result="pass", head="1" * 40, branch="feature/a")["id"]       # the oldest, and the latest pass of feature/a
        older = self.write_suite(result="pass", head="2" * 40, branch="feature/b")["id"]      # a pass that a later pass of its branch replaces
        newer = self.write_suite(result="pass", head="3" * 40, branch="feature/b")["id"]
        failed = [self.write_suite(result="fail", head="%040x" % (10 + i), branch="feature/c")["id"] for i in range(21)]
        logs = self.logs()
        self.assertIn(kept, logs)                                   # outside the newest 20, but the latest pass of its branch
        self.assertIn(newer, logs)
        self.assertNotIn(older, logs)                               # outside the newest 20, and a later pass of its branch exists
        self.assertEqual(sorted(set(logs) - {kept, newer}), sorted(failed[1:]))     # the newest 20 are the failures but the first
        self.assertEqual(len(logs), 22)                                              # and the latest pass of each of two branches besides

    def test_a_removed_log_does_not_fail_the_next_append(self):
        first = self.write_suite()
        os.unlink(first["log"])
        self.write_suite()
        self.assertEqual(len(self.entries()), 2)

    def test_only_logs_below_the_runs_directory_are_removed_whatever_the_entry_says(self):
        victim = os.path.join(self.tmp, "victim.log")
        with open(victim, "w"):
            pass
        entry = {"schema": 1, "kind": "qargi-history-entry", "entry_kind": "suite", "id": "0" * 16, "project": "demo", "time": "2026-11-27T01:02:03Z",
                 "result": "fail", "branch": "b", "log": victim}
        os.makedirs(os.path.dirname(H.history_path("demo")), mode=0o700, exist_ok=True)
        with open(H.history_path("demo"), "ab") as f:
            f.write((H.dumps(entry) + "\n").encode())
        for i in range(H.KEEP_LOGS):
            self.write_suite(result="fail", head="%040x" % i)
        self.assertTrue(os.path.exists(victim))


class Suite(Base):
    def test_the_failing_names_are_capped_at_200_and_counted(self):
        names = ["FAIL case %d" % i for i in range(250)]
        e = self.write_suite(result="fail", names=names)
        self.assertEqual((len(e["failing_tests"]), e["failing_total"], e["failing_tests"][0], e["failing_tests"][-1]), (200, 250, "FAIL case 0", "FAIL case 199"))

    def test_the_failing_names_may_come_on_standard_input(self):
        code = ("import sys; sys.path.insert(0, %r); import history_write as W; import history as H; "
                "sys.exit(W.write_main(['suite', '--project', 'demo', '--verb', 'release verify', '--name', '1.0.0', '--branch', 'release/1.0.0', '--head', %r, '--tree', %r, "
                "'--command=c', '--result', 'fail', '--started', '2026-11-27T01:02:03Z', '--seconds', '1', '--names', '-']))" % (LIB, HEAD, TREE))
        p = subprocess.run([sys.executable, "-I", "-c", code], input="FAIL one\n--- FAIL: two (0.00s)\n\n", universal_newlines=True, capture_output=True, timeout=60)
        self.assertEqual((p.returncode, p.stderr), (0, ""))
        e = H.read("demo", warn=False)[0][-1]
        self.assertEqual((e["failing_tests"], e["failing_total"], e["verb"], e["name"]), (["FAIL one", "--- FAIL: two (0.00s)"], 2, "release verify", "1.0.0"))

    def test_a_long_name_is_cut(self):
        e = self.write_suite(result="fail", names=["FAIL " + "x" * 1000])
        self.assertEqual(len(e["failing_tests"][0]), H.MAX_NAME)

    def test_gates_keep_their_order_and_a_gate_that_did_not_run_has_no_seconds(self):
        e = self.write_suite(result="fail", gates=[{"name": "lint", "tier": "feature", "result": "pass", "seconds": 2}, {"name": "unit", "tier": "feature", "result": "fail", "seconds": 9},
                                                   {"name": "slow", "tier": "release", "result": "not run"}, {"name": "ci", "tier": "release", "result": "covered by unit"}])
        self.assertEqual([(g["name"], g["result"], g["seconds"]) for g in e["gates"]],
                         [("lint", "pass", 2), ("unit", "fail", 9), ("slow", "not run", None), ("ci", "covered by unit", None)])

    def test_an_interrupted_run_is_an_entry_too(self):
        e = self.write_suite(result="interrupted")
        self.assertEqual(e["result"], "interrupted")

    def test_the_load_average_is_text_or_null(self):
        self.assertTrue(H.load_average() is None or re.match(r"^\d+\.\d+$", H.load_average()))
        self.assertEqual(self.write_suite()["load_start"], "0.50")


class Review(Base):
    def facts(self, **over):
        d = {"verdict": "accept", "report_sha256": "f" * 64, "tests_run": None}
        d.update(over)
        p = os.path.join(self.tmp, "facts.json")
        with open(p, "w") as f:
            json.dump(d, f)
        return p

    def write_review(self, facts=None, runtime="", **over):
        args = ["review", "--project", "demo", "--run", "qargi.abc123", "--slug", "check-it", "--facts", facts or self.facts(), "--base", "develop",
                "--base-sha", "1" * 40, "--role", "review", "--class", "read-only", "--runtime=" + runtime, "--model=m1"]
        self.assertEqual(W.write_main(args), 0)
        return H.read("demo", warn=False)[0][-1]

    def test_a_review_entry_holds_the_verdict_the_hash_and_the_registry_facts_but_no_text(self):
        e = self.write_review()
        self.assertEqual(errors(K.validate(K.registry_path("qargi-history-entry"), json.dumps(e))), [])
        self.assertEqual((e["entry_kind"], e["run"], e["slug"], e["verdict"], e["report_sha256"], e["base"], e["base_sha"]),
                         ("review", "qargi.abc123", "check-it", "accept", "f" * 64, "develop", "1" * 40))
        self.assertEqual((e["role"], e["class"], e["runtime"], e["model"], e["vendor"], e["tests_run"]), ("review", "read-only", None, "m1", None, None))
        self.assertNotIn("report", e)

    def test_tests_run_is_kept_as_a_list_of_names_or_a_count(self):
        self.assertEqual(self.write_review(self.facts(tests_run=["python3 tests/test_x.py", "bash t.sh"]))["tests_run"], ["python3 tests/test_x.py", "bash t.sh"])
        self.assertEqual(self.write_review(self.facts(tests_run=12))["tests_run"], 12)
        self.assertIsNone(self.write_review(self.facts(tests_run={"a": 1}))["tests_run"])
        self.assertIsNone(self.write_review(self.facts(tests_run=True))["tests_run"])

    def test_the_vendor_is_the_family_the_descriptor_gives(self):
        import provider as P
        named = [n for n in P.names(P.PROVIDERS) if "local" in P.surfaces_of(n) and isinstance(P.definition(n, "local", root=P.PROVIDERS).get("family"), str)]
        self.assertTrue(named)
        want = P.definition(named[0], "local").get("family")
        self.assertEqual(self.write_review(runtime=named[0])["vendor"], want)
        self.assertIsNone(self.write_review(runtime="no-such-runtime")["vendor"])

    def test_facts_that_are_not_a_verdict_and_a_hash_write_nothing(self):
        for bad in ({"verdict": "maybe", "report_sha256": "f" * 64}, {"verdict": "accept", "report_sha256": "xyz"}):
            buf = io.StringIO()
            with redirect_stderr(buf):
                self.assertEqual(W.write_main(["review", "--project", "demo", "--run", "r", "--slug", "s", "--facts", self.facts(**bad)]), 1)
            self.assertIn("no entry was written", buf.getvalue())
        self.assertFalse(os.path.exists(self.path()))


class Verb(Base):
    """qargi history, through bin/qargi: the text table, --json against the kind, show, the filters and the exit statuses."""

    def populate(self):
        self.a = self.write_suite(name="alpha", head="1a2b3c4d" + "0" * 32, tree="9f8e7d6c" + "0" * 32, result="pass", seconds=30)
        self.b = self.write_suite(name="alpha", head="1a2b3c4d" + "0" * 32, tree="9f8e7d6c" + "0" * 32, result="fail", seconds=41, names=["FAIL: a case", "--- FAIL: TestB (0.00s)"])
        facts = os.path.join(self.tmp, "facts.json")
        with open(facts, "w") as f:
            json.dump({"verdict": "revise", "report_sha256": "e" * 64, "tests_run": ["python3 tests/test_x.py"]}, f)
        self.assertEqual(W.write_main(["review", "--project", "demo", "--run", "qargi.zzz999", "--slug", "look", "--facts", facts, "--base", "develop",
                                       "--base-sha", "7a0be12" + "0" * 33, "--role", "review", "--class", "read-only", "--runtime=", "--model=m"]), 0)
        self.c = H.read("demo", warn=False)[0][-1]
        self.d = self.write_suite(name="beta", head="5c5c5c5c" + "0" * 32, tree="aaaaaaaa" + "0" * 32, result="pass", seconds=5)

    def test_the_text_is_newest_first_with_the_columns_of_the_table(self):
        self.populate()
        rc, out, err = self.run_cli("history", "--project", "demo")
        self.assertEqual((rc, err), (0, ""))
        lines = out.splitlines()
        self.assertEqual(lines[0].split(), ["TIME", "KIND", "NAME", "HEAD", "TREE", "RESULT", "SECONDS", "ATTEMPT", "ID"])
        rows = [l.split() for l in lines[1:]]
        self.assertEqual([r[-1] for r in rows], [self.d["id"], self.c["id"], self.b["id"], self.a["id"]])          # newest first
        self.assertEqual(rows[0][1:8], ["suite", "beta", "5c5c5c5c", "aaaaaaaa", "pass", "5", "1"])
        self.assertEqual(rows[1][1:8], ["review", "look", "7a0be120", "-", "revise", "-", "-"])
        self.assertEqual(rows[2][1:8], ["suite", "alpha", "1a2b3c4d", "9f8e7d6c", "fail", "41", "2"])
        self.assertEqual(rows[3][1:8], ["suite", "alpha", "1a2b3c4d", "9f8e7d6c", "pass", "30", "1"])
        self.assertTrue(all(re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$", r[0]) for r in rows))

    def test_the_filters(self):
        self.populate()
        ids = lambda *args: [l.split()[-1] for l in self.run_cli("history", "--project", "demo", *args)[1].splitlines()[1:]]
        self.assertEqual(ids("--kind", "review"), [self.c["id"]])
        self.assertEqual(ids("--kind", "suite"), [self.d["id"], self.b["id"], self.a["id"]])
        self.assertEqual(ids("--head", "1a2b"), [self.b["id"], self.a["id"]])
        self.assertEqual(ids("--head", "7a0b"), [self.c["id"]])                 # the base of a review entry counts as its head
        self.assertEqual(ids("--head", "1a2b", "--kind", "review"), [])
        rc, out, _ = self.run_cli("history", "--project", "demo", "--limit", "1")
        self.assertEqual((rc, out.count("\n")), (0, 3))
        self.assertIn("(3 more; --limit N shows more)", out)

    def test_no_entry_is_a_line_and_exit_0(self):
        rc, out, err = self.run_cli("history", "--project", "demo")
        self.assertEqual((rc, out, err), (0, "no history entry of demo\n", ""))
        self.populate()
        rc, out, _ = self.run_cli("history", "--project", "demo", "--head", "ffff")
        self.assertEqual((rc, out), (0, "no history entry of demo matches\n"))

    def test_json_is_one_document_of_the_kind_qargi_history(self):
        self.populate()
        rc, out, err = self.run_cli("history", "--project", "demo", "--json")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(errors(K.validate(K.registry_path("qargi-history"), out)), [])
        doc = json.loads(out)
        self.assertEqual((doc["schema"], doc["kind"], doc["project"], doc["matched"], doc["skipped"]), (1, "qargi-history", "demo", 4, 0))
        self.assertEqual([e["id"] for e in doc["entries"]], [self.d["id"], self.c["id"], self.b["id"], self.a["id"]])
        self.assertEqual(doc["entries"][2]["failing_tests"], ["FAIL: a case", "--- FAIL: TestB (0.00s)"])
        self.assertEqual(doc["entries"][1]["tests_run"], ["python3 tests/test_x.py"])
        self.assertTrue(out.endswith("}\n") and out.count("\n") > 10)
        rc, out, _ = self.run_cli("history", "--project", "demo", "--json", "--kind", "suite", "--limit", "2")
        doc = json.loads(out)
        self.assertEqual((rc, doc["matched"], len(doc["entries"])), (0, 3, 2))

    def test_json_with_nothing_to_list_is_still_a_document(self):
        rc, out, _ = self.run_cli("history", "--project", "demo", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(errors(K.validate(K.registry_path("qargi-history"), out)), [])
        self.assertEqual((json.loads(out)["entries"], json.loads(out)["matched"]), ([], 0))

    def test_an_unreadable_line_is_counted_and_warned_about(self):
        self.populate()
        with open(self.path(), "ab") as f:
            f.write(b'{"torn":')
        rc, out, err = self.run_cli("history", "--project", "demo", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual((json.loads(out)["skipped"], json.loads(out)["matched"]), (1, 4))
        self.assertIn("skipped 1 line(s)", err)
        rc, out, err = self.run_cli("history", "--project", "demo")
        self.assertEqual(rc, 0)
        self.assertIn("skipped 1 line(s)", err)

    def test_a_document_that_fails_its_registry_file_is_exit_70_and_prints_nothing(self):
        os.makedirs(os.path.dirname(self.path()), mode=0o700)
        with open(self.path(), "w") as f:
            f.write(json.dumps({"schema": 1, "kind": "qargi-history-entry", "entry_kind": "suite", "id": "0123456789abcdef", "project": "demo",
                                "time": "2026-11-27T01:02:03Z", "seconds": "slow"}) + "\n")
        rc, out, err = self.run_cli("history", "--project", "demo", "--json")
        self.assertEqual((rc, out), (70, ""))
        self.assertIn("a defect of qargi", err)
        rc, out, _ = self.run_cli("history", "--project", "demo")                  # the text form does not go through the registry file
        self.assertEqual(rc, 0)

    def test_show_prints_every_field_and_with_json_the_entry_as_stored(self):
        self.populate()
        rc, out, err = self.run_cli("history", "show", self.b["id"][:6], "--project", "demo")
        self.assertEqual((rc, err), (0, ""))
        for want in ("id: " + self.b["id"], "entry_kind: suite", "verb: feature verify", "name: alpha", "result: fail", "attempt: 2", "head: 1a2b3c4d",
                     "command: " + CMD, "environment_id: -", "gates:" if self.b["gates"] else "failing tests: 2", "  FAIL: a case", "  --- FAIL: TestB (0.00s)"):
            self.assertIn(want, out)
        rc, out, _ = self.run_cli("history", "show", self.b["id"], "--project", "demo", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), self.b)
        self.assertEqual(errors(K.validate(K.registry_path("qargi-history-entry"), out)), [])
        rc, out, _ = self.run_cli("history", "show", self.c["id"], "--project", "demo")
        self.assertIn("verdict: revise", out)
        self.assertIn("report_sha256: " + "e" * 64, out)
        self.assertIn("tests_run: python3 tests/test_x.py", out)

    def test_show_says_that_a_pruned_log_is_gone(self):
        e = self.write_suite()
        rc, out, _ = self.run_cli("history", "show", e["id"], "--project", "demo")
        self.assertIn("log: " + e["log"] + "\n", out)
        os.unlink(e["log"])
        rc, out, _ = self.run_cli("history", "show", e["id"], "--project", "demo")
        self.assertIn("log: " + e["log"] + " (the file is gone)\n", out)
        rc, out, _ = self.run_cli("history", "show", e["id"], "--project", "demo", "--json")
        self.assertEqual(json.loads(out)["log"], e["log"])

    def test_show_names_the_whole_range_of_an_id_prefix(self):
        rc, _, err = self.run_cli("history", "show", "abc", "--project", "demo")
        self.assertEqual(rc, 2)
        self.assertIn("4 to 64 digits", err)

    def test_show_escapes_control_characters_of_a_test_name(self):
        e = self.write_suite(result="fail", names=["FAIL \x1b[31mred\x1b[0m"])
        rc, out, _ = self.run_cli("history", "show", e["id"], "--project", "demo")
        self.assertEqual(rc, 0)
        self.assertNotIn("\x1b", out)
        self.assertIn("FAIL \\x1b[31mred\\x1b[0m", out)

    def test_show_of_no_entry_or_of_two_is_exit_1(self):
        self.populate()
        rc, out, err = self.run_cli("history", "show", "ffffffff", "--project", "demo")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("no history entry of demo has the id ffffffff", err)
        os.makedirs(os.path.dirname(self.path()), mode=0o700, exist_ok=True)
        with open(self.path(), "a") as f:
            for tail in ("1" * 12, "2" * 12):
                f.write(json.dumps({"schema": 1, "kind": "qargi-history-entry", "entry_kind": "review", "id": "abcd" + tail, "project": "demo", "time": "2026-11-27T01:02:03Z"}) + "\n")
        rc, out, err = self.run_cli("history", "show", "abcd", "--project", "demo")
        self.assertEqual((rc, out), (1, ""))
        self.assertIn("2 history entries of demo start with abcd", err)

    def test_a_wrong_call_is_exit_2(self):
        for args in (["--limit", "0"], ["--limit", "1001"], ["--limit", "x"], ["--kind", "other"], ["--head", "zz"], ["--head", "abc"], ["show"], ["show", "xyz"], ["show", "abcd", "--kind", "suite"],
                     ["bogus"], ["abcd", "show"]):
            rc, out, err = self.run_cli("history", "--project", "demo", *args)
            self.assertEqual((rc, out), (2, ""), args)
            self.assertTrue(err.strip(), args)

    def test_without_a_project_it_says_so(self):
        rc, out, err = self.run_cli("history", cwd=self.tmp)
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("name a project with --project P", err)

    def test_the_project_is_the_one_in_effect(self):
        self.populate()
        os.makedirs(os.path.join(os.environ["QARGI_CONF"], "projects"), exist_ok=True)
        env = dict(os.environ, QARGI_PROJECT="demo")
        rc, out, _ = self.run_cli("history", "--kind", "review", env=env)
        self.assertEqual((rc, len(out.splitlines())), (0, 2))

    def test_the_help_forms(self):
        for args in (["history", "--help"], ["history", "show", "--help"], ["history", "-h"], ["help", "history"]):
            rc, out, _ = self.run_cli(*args)
            self.assertEqual(rc, 0, args)
            self.assertIn("qargi history", out)
            self.assertIn("evidence", out)
        rc, out, _ = self.run_cli("help", "json", "qargi-history-entry")
        self.assertEqual(rc, 0)
        self.assertIn("Printed by: qargi history show ID --json on stdout.", out)

    def test_it_writes_nothing(self):
        self.populate()
        before = {}
        for d, _, files in os.walk(self.state):
            for f in files:
                p = os.path.join(d, f)
                before[p] = (os.stat(p).st_mtime_ns, os.stat(p).st_size)
        for args in (["history", "--project", "demo"], ["history", "--project", "demo", "--json"], ["history", "show", self.a["id"], "--project", "demo"]):
            self.run_cli(*args)
        after = {}
        for d, _, files in os.walk(self.state):
            for f in files:
                p = os.path.join(d, f)
                after[p] = (os.stat(p).st_mtime_ns, os.stat(p).st_size)
        self.assertEqual(before, after)


class Kinds(unittest.TestCase):
    def test_the_two_kinds_are_registered_drafts_of_schema_1(self):
        for k, verb in (("qargi-history-entry", "history show ID --json"), ("qargi-history", "history --json")):
            reg = load(os.path.join(LIB, "kinds", k + ".json"))
            self.assertEqual((reg["status"], reg["schema"], reg["stream"], reg["verbs"]), ("draft", 1, "stdout", [verb]))
        self.assertEqual(K.check_dir(), [])

    def test_the_list_holds_the_entry_shape_of_the_entry_kind(self):
        entry = load(os.path.join(LIB, "kinds", "qargi-history-entry.json"))["document"]
        lst = load(os.path.join(LIB, "kinds", "qargi-history.json"))["document"]
        shape = dict(entry)
        defs = shape.pop("$defs")
        self.assertEqual(lst["$defs"]["entry"], shape)
        self.assertEqual(lst["$defs"]["gate"], defs["gate"])

    def test_a_review_and_a_suite_entry_both_validate_and_a_wrong_one_does_not(self):
        reg = K.registry_path("qargi-history-entry")
        base = {"schema": 1, "kind": "qargi-history-entry", "entry_kind": "review", "id": "0" * 16, "project": "demo", "time": "2026-11-27T01:02:03Z"}
        self.assertEqual(K.validate(reg, json.dumps(base)), [])
        self.assertNotEqual(K.validate(reg, json.dumps(dict(base, id="zz"))), [])
        self.assertNotEqual(K.validate(reg, json.dumps(dict(base, seconds=1.5, entry_kind="suite"))), [])


if __name__ == "__main__":
    unittest.main()
