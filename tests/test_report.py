#!/usr/bin/env python3
"""qargi report: the figures from a fixture tracker and fixture local run directories. Offline; no cloud, no real state.
Run: python3 tests/test_report.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import report as R  # noqa: E402

NOW = datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc)
SECRET = "SECRET-NOTE-AND-REQUEST"


def ts(delta_min, now=NOW):
    return (now - timedelta(minutes=delta_min)).strftime("%Y-%m-%dT%H:%M:%SZ")


def row(inst, label, status, review, seen, cost, created=120, closed=None, why=None):
    return {"instance": inst, "label": label, "status": status, "review_state": review, "last_seen": ts(seen), "list_cost": cost,
            "created": ts(created), "closed_at": ts(closed) if closed is not None else None, "stop_reason": why,
            "note": SECRET, "asked": SECRET, "budget": "3000", "outputs_collected": True}


def tracker():
    return {
        "s1": row("acme-build", "rename-verb", "archived", "applied", 600, "300", created=1000, closed=700),     # 300 min
        "s2": row("acme-build", "fix-doc", "archived", "applied", 500, "100", created=1000, closed=400),        # 600 min
        "s3": row("acme-build", "bad-idea", "archived", "rejected", 500, "50", created=900, closed=800),        # 100 min
        "s4": row("acme-build", "wait-review", "idle", "pending", 300, "200", why="end_turn"),                   # 5 h pending, stale
        "s5": row("acme-build", "fresh-review", "idle", "pending", 10, "20", why="end_turn"),                    # 10 min pending
        "s6": row("acme-write", "needs-approval", "idle", "pending", 20, None, why="requires_action"),
        "s7": row("acme-write", "stuck-run", "running", "pending", 240, "70"),                                   # running, unseen 4 h
        "s8": row("acme-write", "busy", "running", "pending", 5, "10"),
        "s9": row("acme-write", "unknown-why", "idle", "pending", 30, "5", why=None),
    }


class Pure(unittest.TestCase):
    def setUp(self):
        self.rep = R.summarize(tracker(), NOW)
        self.b = self.rep["instances"]["acme-build"]

    def test_counts_and_spend(self):
        t = self.rep["total"]
        self.assertEqual(t["sessions"], 9)
        self.assertEqual(t["review"], {"pending": 6, "applied": 2, "rejected": 1, "not-applicable": 0})
        self.assertEqual(t["status"], {"archived": 3, "idle": 4, "running": 2})
        self.assertEqual(t["spend"]["total"], 755.0)
        self.assertEqual(t["spend"]["sessions_without_cost"], 1)
        self.assertEqual(t["spend"]["per_applied"], 755 / 2)
        self.assertEqual(self.b["spend"]["total"], 670.0)
        self.assertIsNone(R.summarize({"x": row("a-b", "l", "idle", "pending", 1, "5")}, NOW)["total"]["spend"]["per_applied"])

    def test_pending_review_is_oldest_first_and_leaves_out_running(self):
        labels = [p["label"] for p in self.rep["total"]["pending_review"]]
        self.assertEqual(labels, ["wait-review", "unknown-why", "needs-approval", "fresh-review"])
        self.assertEqual(self.rep["total"]["pending_review"][0]["age_seconds"], 300 * 60)

    def test_stale_is_running_or_idle_pending_beyond_the_window(self):
        self.assertEqual([p["label"] for p in self.rep["total"]["stale"]], ["wait-review", "stuck-run"])
        wide = R.summarize(tracker(), NOW, stale_after=6 * 3600)
        self.assertEqual(wide["total"]["stale"], [])

    def test_time_to_close(self):
        t = self.b["time_to_close_seconds"]
        self.assertEqual((t["count"], t["median"], t["max"]), (3, 300 * 60, 600 * 60))

    def test_idle_sessions_split_by_stop_reason(self):
        i = self.rep["total"]["idle"]
        self.assertEqual((i["finished"], i["needs_input"], i["not_recorded"]), (2, {"requires_action": 1}, 1))
        txt = R.render(self.rep)
        self.assertIn("awaiting review (finished, end_turn): 2", txt)
        self.assertIn("stopped needing input: requires_action 1", txt)
        self.assertIn("reason a session went idle: not recorded for 1", txt)

    def test_an_interrupted_session_is_not_counted_as_finished(self):
        t = tracker()
        t["s5"]["interrupt_sent_at"] = ts(15)       # fresh-review ended with end_turn, but after a qargi stop
        rep = R.summarize(t, NOW)
        i = rep["total"]["idle"]
        self.assertEqual((i["finished"], i["stopped_by_qargi"]), (1, 1))
        self.assertIn("stopped by qargi (interrupt sent, end_turn): 1", R.render(rep))

    def test_filters(self):
        self.assertEqual(list(R.summarize(tracker(), NOW, instance="acme-write")["instances"]), ["acme-write"])
        since = R.summarize(tracker(), NOW, since=NOW - timedelta(minutes=950))
        self.assertEqual(since["total"]["sessions"], 7)   # s1 and s2 were created 1000 minutes ago

    def test_free_text_is_never_in_the_output(self):
        self.assertNotIn(SECRET, R.render(self.rep))
        self.assertNotIn(SECRET, json.dumps(self.rep))

    def test_limits_are_stated(self):
        txt = R.render(self.rep)
        self.assertIn("What this cannot tell you", txt)
        self.assertIn("cents, per the docs", txt)
        self.assertIn("last_seen", txt)

    def test_odd_rows_do_not_crash(self):
        rep = R.summarize({"a": {"instance": "x-y"}, "b": "junk", "c": {"instance": "x-y", "list_cost": "n/a", "last_seen": "never", "status": "idle", "review_state": "pending"}}, NOW)
        self.assertEqual(rep["total"]["sessions"], 2)
        R.render(rep)

    def test_durations(self):
        self.assertEqual([R.parse_duration(x) for x in ("90", "90s", "45m", "2h", "1d")], [90, 90, 2700, 7200, 86400])
        with self.assertRaises(ValueError):
            R.parse_duration("soon")

    def test_local_classification_is_pure(self):
        def facts(manifest, last_change_min, exists=True):
            return {"run": "/r/%s" % manifest, "label": "l", "ability": "build", "started": ts(100), "exists": exists, "manifest": manifest,
                    "last_change": (NOW - timedelta(minutes=last_change_min)).timestamp(), "log_bytes": 5}
        sec = R.local_section([facts("DONE", 5), facts(None, 5), facts(None, 31), facts(None, 29, exists=False)], NOW, 1800)
        self.assertEqual([r["state"] for r in sec["runs"]],
                         ["finished DONE", "no manifest, still changing", "no manifest, quiet for 31 minutes: possibly stalled", "directory gone"])
        self.assertEqual(sec["counts"]["possibly_stalled"], 1)


def make_run(root, name, age_min, manifest=None, log=None, label="job"):
    """A local run directory as prepare leaves it (out/, clone/), with every file last changed age_min minutes ago."""
    run = os.path.join(root, name)
    for d in ("out", "clone/.git"):
        os.makedirs(os.path.join(run, d), exist_ok=True)
    with open(os.path.join(run, "clone", ".git", "HEAD"), "w") as f:
        f.write("ref: refs/heads/agent/%s\n" % label)
    with open(os.path.join(run, "ability"), "w") as f:
        f.write("build\n")
    if manifest is not None:
        with open(os.path.join(run, "out", "manifest.json"), "w") as f:
            f.write(manifest)
    if log is not None:
        with open(os.path.join(run, "out", "log.txt"), "w") as f:
            f.write(log)
    t = (datetime.now(timezone.utc) - timedelta(minutes=age_min)).timestamp()
    for d, _, files in os.walk(run):
        for f in files:
            os.utime(os.path.join(d, f), (t, t))
    return run


class Local(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.state = os.path.join(self.t, "s")
        self.root = os.path.join(self.t, "scratch")
        os.makedirs(self.state)
        os.makedirs(self.root)
        self.env = dict(os.environ, QARGI_STATE=self.state, QARGI_CONF=os.path.join(self.t, "c"))
        self.env.pop("QARGI_RUNS_ROOT", None)

    def report(self, *a):
        return subprocess.run([BIN, "report", *a], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)

    def register(self, run, slug, started_min_ago):
        with open(os.path.join(self.state, "local-runs.jsonl"), "a") as f:
            f.write(json.dumps({"run": run, "slug": slug, "ability": "build", "base": "main",
                                "started": ts(started_min_ago, datetime.now(timezone.utc))}) + "\n")

    def fixture(self):
        return {
            "done": make_run(self.root, "qargi.done", 90, '{"status":"DONE"}', "x" * 10, "done-job"),
            "blocked": make_run(self.root, "qargi.blocked", 80, '{"status":"BLOCKED"}', "", "blocked-job"),
            "broken": make_run(self.root, "qargi.broken", 70, "{not json", None, "broken-job"),
            "busy": make_run(self.root, "qargi.busy", 3, None, "y" * 2048, "busy-job"),
            "quiet": make_run(self.root, "qargi.quiet", 45, None, "z" * 100, "quiet-job"),
        }

    def test_the_states_of_local_runs(self):
        runs = self.fixture()
        r = self.report("--runs-root", self.root)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("finished DONE 1, BLOCKED 1, no manifest and still changing 1, possibly stalled 1", out)
        self.assertIn("busy-job", out)
        self.assertIn("no manifest, still changing", out)
        self.assertIn("no manifest, quiet for 45 minutes: possibly stalled", out)
        self.assertIn("log 2048 bytes", out)
        self.assertIn(runs["quiet"], out)
        self.assertNotIn("done-job", out)      # finished runs are counted, not listed
        data = json.loads(self.report("--runs-root", self.root, "--json").stdout)["local"]
        states = {os.path.basename(x["run"]): x["state"] for x in data["runs"]}
        self.assertEqual(states["qargi.done"], "finished DONE")
        self.assertEqual(states["qargi.blocked"], "finished BLOCKED")
        self.assertEqual(states["qargi.broken"], "manifest unreadable")
        self.assertEqual(data["counts"]["finished_other"], 1)
        self.assertEqual(next(x for x in data["runs"] if x["label"] == "quiet-job")["log_bytes"], 100)

    def test_the_threshold_is_an_option(self):
        self.fixture()
        self.assertIn("possibly stalled 0", self.report("--runs-root", self.root, "--local-stale-after", "1h").stdout)
        self.assertIn("possibly stalled 2", self.report("--runs-root", self.root, "--local-stale-after", "2m").stdout)

    def test_activity_in_the_clone_counts_as_still_changing(self):
        run = make_run(self.root, "qargi.work", 60, None, "l", "work")
        with open(os.path.join(run, "clone", "edited.py"), "w") as f:
            f.write("x")
        out = self.report("--runs-root", self.root).stdout
        self.assertIn("no manifest, still changing", out)
        self.assertIn("possibly stalled 0", out)

    def test_the_registry_lists_runs_and_notes_a_removed_directory(self):
        busy = make_run(self.root, "qargi.busy", 2, None, "l", "from-registry")
        self.register(busy, "from-registry", 10)
        self.register(os.path.join(self.root, "qargi.gone"), "gone-job", 500)
        out = self.report().stdout      # no --runs-root: only the registry
        self.assertIn("from-registry", out)
        self.assertIn("directory gone 1", out)
        self.assertIn("started 10m ago", out)

    def test_since_and_instance(self):
        self.register(make_run(self.root, "qargi.busy", 2, None, "l", "recent"), "recent", 10)
        self.register(make_run(self.root, "qargi.old", 2, None, "l", "ancient"), "ancient", 100000)
        out = self.report("--since", (datetime.now(timezone.utc) - timedelta(days=2)).strftime("%Y-%m-%d")).stdout
        self.assertIn("recent", out)
        self.assertNotIn("ancient", out)
        out = self.report("--instance", "acme-build").stdout
        self.assertNotIn("recent", out)
        self.assertIn("Local runs: not shown", out)

    def test_a_cloud_tracker_through_the_command(self):
        n = datetime.now(timezone.utc)
        t = {"sesn_1": {"instance": "acme-build", "label": "waits", "status": "idle", "review_state": "pending", "last_seen": ts(300, n), "created": ts(400, n),
                        "closed_at": None, "list_cost": "250", "stop_reason": "end_turn", "note": SECRET, "asked": SECRET}}
        with open(os.path.join(self.state, "sessions.json"), "w") as f:
            json.dump(t, f)
        r = self.report()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("waits", r.stdout)
        self.assertIn("Instance acme-build", r.stdout)
        self.assertNotIn(SECRET, r.stdout)
        self.assertNotIn(SECRET, self.report("--json").stdout)
        self.assertEqual(self.report("--stale-after", "soon").returncode, 2)
        self.assertEqual(self.report("--since", "yesterday").returncode, 2)
        self.assertEqual(self.report("--bogus").returncode, 2)

    def test_no_tracker_is_not_an_error_and_nothing_is_created(self):
        r = self.report()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("no tracked sessions match", r.stdout)
        self.assertEqual(os.listdir(self.state), [])

    def test_prepare_registers_a_run_that_report_then_lists(self):
        repo = os.path.join(self.t, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.net", "commit", "-q", "--allow-empty", "-m", "one"], check=True)
        p = subprocess.run([BIN, "local", "prepare", "--repo", repo, "--base", "main", "--slug", "live-job", "--scratch", self.root],
                           capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)
        self.assertEqual(p.returncode, 0, p.stderr)
        out = self.report().stdout
        self.assertIn("live-job", out)
        self.assertIn("no manifest, still changing", out)

    def test_supervisor_section_counts_stalls_and_prepared_nudges(self):
        runs = {"last_tick_at": "2026-10-30T12:00:00Z", "runs": {
            "a": {"class": "looping"}, "b": {"class": "looping"}, "c": {"class": "suspected_dead"}, "d": {"class": "waiting"},
            "e": {"class": "finished"}, "f": {"class": "working"}}}
        nudges = [{"type": "prepared", "id": "a#1", "key": "a", "class": "looping", "number": 1},
                  {"type": "prepared", "id": "b#1", "key": "b", "class": "looping", "number": 1},
                  {"type": "delivered", "id": "b#1", "key": "b"},
                  {"type": "prepared", "id": "c#1", "key": "c", "class": "suspected_dead", "number": 1},
                  {"type": "cancelled", "id": "c#1", "key": "c"}]
        sec = R.supervisor_section(runs, nudges)
        self.assertEqual(sec["stalls"], {"looping": 2, "suspected_dead": 1})
        self.assertEqual(sec["asks"], {"waiting": 1})
        self.assertEqual(sec["prepared_nudges"], [["a", "looping", 1]])
        self.assertIsNone(R.supervisor_section({}, []))
        self.assertIsNone(R.supervisor_section({"runs": {"a": {"class": "looping"}}}, []), "a supervisor that never ticked reports nothing")

    def test_supervisor_section_through_the_command(self):
        self.assertNotIn("Supervisor", self.report().stdout)
        with open(os.path.join(self.state, "runs.json"), "w") as f:
            json.dump({"last_tick_at": "2026-10-30T12:00:00Z", "runs": {"agent-9": {"class": "looping"}}}, f)
        with open(os.path.join(self.state, "nudges.jsonl"), "w") as f:
            f.write(json.dumps({"type": "prepared", "id": "agent-9#1", "key": "agent-9", "class": "looping", "number": 1, "text": SECRET}) + "\n")
        r = self.report()
        self.assertIn("suspected stalls: looping 1", r.stdout)
        self.assertIn("agent-9", r.stdout)
        self.assertNotIn(SECRET, r.stdout)
        self.assertEqual(json.loads(self.report("--json").stdout)["supervisor"]["prepared_nudges"], [["agent-9", "looping", 1]])


if __name__ == "__main__":
    unittest.main()
