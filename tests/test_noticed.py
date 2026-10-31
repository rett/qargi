#!/usr/bin/env python3
"""qargi noticed and mark --why: notes from a manifest, dispositions, the report lines. Offline; temporary state.
Run: python3 tests/test_noticed.py"""
import json, os, subprocess, sys, tempfile, unittest
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import noticed as N  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.state, self.conf = os.path.join(self.t, "s"), os.path.join(self.t, "c")
        os.makedirs(self.state), os.makedirs(self.conf)
        self.env = dict(os.environ, HOME=self.t, QARGI_STATE=self.state, QARGI_CONF=self.conf)

    def q(self, *a):
        return subprocess.run([BIN, *a], capture_output=True, text=True, env=self.env)

    def run_dir(self, name, notes, sub=None):
        d = os.path.join(self.t, name, sub or "")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "manifest.json"), "w") as f:
            json.dump({"status": "DONE", "noticed_not_acted_on": notes}, f)
        return os.path.join(self.t, name)

    def ingest(self, sid, d):
        return subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "noticed.py"), "ingest", sid, d], capture_output=True, text=True, env=self.env)

    def events(self):
        return N.read_events(os.path.join(self.state, "events.jsonl"))


class Notes(Base):
    def test_ingest_records_once_and_redacts(self):
        d = self.run_dir("r1", ["the lint config ignores tests/", "token sk-ant-api03-ABCDEFGHIJKLMNOPQRSTUVWX was in the log", {"file": "a.py"}])
        self.assertIn("3 new", self.ingest("sesn_1", d).stdout)
        self.assertIn("nothing new", self.ingest("sesn_1", d).stdout)          # idempotent
        text = json.dumps(self.events())
        self.assertNotIn("ABCDEFGHIJKLMNOPQRSTUVWX", text)
        self.assertIn("[redacted]", text)
        self.assertEqual(oct(os.stat(os.path.join(self.state, "events.jsonl")).st_mode & 0o777), "0o600")

    def test_team_members_are_separate(self):
        d = self.run_dir("r2", ["same words"], sub="build")
        self.run_dir("r2", ["same words"], sub="test")
        self.ingest("sesn_2", d)
        self.assertEqual(sorted(e["member"] for e in self.events()), ["build", "test"])

    def test_text_is_capped(self):
        self.ingest("sesn_3", self.run_dir("r3", ["word " * 200]))
        self.assertLessEqual(len(self.events()[0]["text"]), N.MAXLEN)

    def test_dispositions(self):
        self.ingest("sesn_4", self.run_dir("r4", ["one", "two"]))
        a, b = sorted(e["id"] for e in self.events())
        self.assertIn(a, self.q("noticed", "list").stdout)
        self.assertEqual(self.q("noticed", "resolve", a, "dismissed").returncode, 2)            # needs --why
        self.assertEqual(self.q("noticed", "resolve", a, "dismissed", "--why", "nonsense").returncode, 2)
        self.assertEqual(self.q("noticed", "resolve", a, "dismissed", "--why", "style").returncode, 0)
        self.assertEqual(self.q("noticed", "resolve", "nope", "accepted").returncode, 1)
        self.assertEqual(self.q("noticed", "resolve", b, "later").returncode, 2)
        listed = self.q("noticed", "list").stdout
        self.assertNotIn(a, listed)
        self.assertIn(b, listed)
        self.assertIn("dismissed", self.q("noticed", "list", "--all").stdout)
        self.assertEqual(self.q("noticed", "resolve", b, "followup").returncode, 0)

    def test_report_shows_counts_not_text(self):
        self.ingest("sesn_5", self.run_dir("r5", ["SECRET-NOTE-TEXT", "other"]))
        nid = self.events()[0]["id"]
        self.q("noticed", "resolve", nid, "accepted")
        r = self.q("report")
        self.assertIn("Noticed, not acted on", r.stdout)
        self.assertIn("1 open", r.stdout)
        self.assertIn("accepted 1", r.stdout)
        self.assertNotIn("SECRET-NOTE-TEXT", r.stdout)

    def test_summary_age(self):
        ev = [{"kind": "noticed", "id": "a", "ts": "2026-10-30T10:00:00Z", "text": "x"}]
        s = N.summary(ev, datetime(2026, 10, 30, 12, 0, 0, tzinfo=timezone.utc))
        self.assertEqual((s["open"], s["oldest_open_seconds"]), (1, 7200))


class MarkWhy(Base):
    def setUp(self):
        super().setUp()
        with open(os.path.join(self.state, "sessions.json"), "w") as f:
            json.dump({"s1": {"instance": "i", "label": "l", "status": "archived", "review_state": "pending", "last_seen": "2026-10-30T10:00:00Z"}}, f)

    def row(self):
        with open(os.path.join(self.state, "sessions.json")) as f:
            return json.load(f)["s1"]

    def test_why_is_recorded_and_validated(self):
        self.assertNotEqual(self.q("mark", "s1", "rejected", "--why", "nonsense").returncode, 0)
        self.assertNotEqual(self.q("mark", "s1", "pending", "--why", "style").returncode, 0)
        self.assertNotEqual(self.q("mark", "nosuch", "applied").returncode, 0)
        self.assertEqual(self.row()["review_state"], "pending")
        self.assertEqual(self.q("mark", "s1", "rejected", "--why", "broke-check").returncode, 0)
        r = self.row()
        self.assertEqual((r["review_state"], r["review_reason"]), ("rejected", "broke-check"))
        self.assertTrue(r["reviewed_at"])
        self.assertIn("rejected: broke-check 1", self.q("report").stdout)
        self.q("mark", "s1", "pending")
        self.assertIsNone(self.row()["review_reason"])

    def test_mark_without_why_still_works(self):
        self.assertEqual(self.q("mark", "s1", "applied").returncode, 0)
        self.assertEqual(self.row()["review_state"], "applied")


if __name__ == "__main__":
    unittest.main()
