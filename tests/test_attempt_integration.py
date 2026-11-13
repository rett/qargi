#!/usr/bin/env python3
"""Public lifecycle wiring, offline fake runtime and disposable Git repositories."""
import hermetic  # noqa: F401
import contextlib
import fcntl
import json
import os
from pathlib import Path
import shutil
import shlex
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import attempts as A
import local_run as R
import lead_usage
from attempt_fixture import wire


class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.state = self.root / "state"
        self.conf = self.root / "conf"
        self.bin = self.root / "bin"
        for p in (self.repo, self.conf / "projects", self.bin):
            p.mkdir(parents=True)
        self.env = dict(os.environ, QARGI_CONF=str(self.conf), QARGI_STATE=str(self.state),
                        QARGI_RUN_TMP=str(self.root), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        self.env.pop("CODEX_HOME", None)
        # Attribution assertions must use the fixture's configured identity.
        for key in list(self.env):
            if key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")):
                del self.env[key]
        self.patch = mock.patch.dict(os.environ, self.env, clear=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.git("init", "-q", "-b", "develop")
        self.git("config", "user.name", "Fixture Lead")
        self.git("config", "user.email", "lead@example.invalid")
        self.git("commit", "-q", "--allow-empty", "-m", "initial")
        self.sha = self.git("rev-parse", "HEAD")
        self.answers = {"schema": 1, "project": "demo", "repo": {"path": str(self.repo), "long_lived": ["develop"]},
                        "models": {"provider": {"local": "codex"}}, "roles": {"build": {"base": "develop", "push": {"mode": "none"}}},
                        "memory": {}, "review": {"scrub": "test ! -e /proc/self/fd/7"}}
        (self.conf / "projects/demo.json").write_text(json.dumps(self.answers))
        self.fake = self.bin / "codex"
        self.fake.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
run = Path.cwd().parent
assert not Path('/proc/self/fd/7').exists(), 'member inherited lifecycle lock'
assert not Path('/proc/self/fd/8').exists(), 'member inherited pending plan'
if (run / 'wait-member').exists():
    (run / 'member-ready').write_text(str(os.getpid()))
    while not (run / 'release-member').exists():
        time.sleep(.02)
if '-o' in sys.argv:
    Path(sys.argv[sys.argv.index('-o') + 1]).write_text('fixture report\\n')
print('fixture transcript')
''')
        self.fake.chmod(0o755)

    def cmd(self, *args, ok=True, input=None):
        p = subprocess.run([str(ROOT / "bin/qargi"), *map(str, args)], cwd=self.repo,
                           env=self.env, text=True, input=input, capture_output=True, timeout=30)
        if ok:
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        else:
            self.assertNotEqual(p.returncode, 0, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def git(self, *args, repo=None):
        p = subprocess.run(["git", "-C", str(repo or self.repo), *args], env=self.env,
                           capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout.strip()

    def prepare(self, role="build"):
        out = self.cmd("local", "prepare", "--repo", self.repo, "--base", "develop", "--slug", "example",
                       "--scratch", self.root, "--role", role)
        self.run = Path(next(l[4:] for l in out.splitlines() if l.startswith("RUN=")))
        (self.run / "task.md").write_text("TASK: offline fixture\nDONE: true\n")
        self.store = A.Store(self.run)
        self.saved = self.state / "runs" / self.run.name
        self.record = Path(self.store.path) / "state.json"
        return self.run

    def state_json(self):
        return json.loads(self.record.read_text())

    @contextlib.contextmanager
    def locked(self):
        fd = self.store.open_lock()
        if fd != 7:
            os.dup2(fd, 7)
            os.close(fd)
        fcntl.flock(7, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            os.close(7)

    def verify(self):
        return self.cmd("local", "verify", self.run)

    def dispatch(self, **kw):
        return self.cmd("local", "run", self.run, "--again", **kw)

    def commit(self):
        self.git("commit", "-q", "--allow-empty", "-m", "lead move")
        return self.git("rev-parse", "HEAD")

    def bytes_tree(self, path):
        return {str(p.relative_to(path)): p.read_bytes() for p in path.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_retry_strict_and_original_authority_immutable(self):
        self.prepare()
        original = self.state_json()["prepared"]
        self.verify()
        self.dispatch()
        self.assertEqual(self.state_json()["current"], 2)
        self.assertFalse((self.run / "verified").exists())
        self.commit()
        # Both mirror forgeries must be irrelevant to strict retry acceptance.
        forged = f"local refs/heads/develop {self.git('rev-parse', 'HEAD')}\n"
        (self.run / "verified").write_text(forged)
        (self.run / "refs.before").write_text(forged)
        (self.run / "started").write_text("0\n")
        self.assertIn("REFS CHANGED", self.cmd("local", "verify", self.run, ok=False))
        self.assertEqual(self.state_json()["prepared"], original)
        self.assertEqual(self.state_json()["attempts"][-1]["gate"], "strict")
        self.assertTrue((Path(self.store.path) / "a1.saved.1").is_dir())

    def test_forged_first_verification_and_feature_gate(self):
        self.prepare()
        self.commit()
        forged = f"local refs/heads/develop {self.git('rev-parse', 'HEAD')}\n"
        (self.run / "verified").write_text(forged)
        (self.run / "refs.before").write_text(forged)
        (self.run / "applied").write_text(f"agent/forged {self.sha}\n")
        self.assertIn("REFS CHANGED", self.cmd("local", "verify", self.run, ok=False))
        runs = lead_usage.open_runs(str(self.state), str(self.repo), "")
        self.assertEqual(runs[0][4], "prepared, not verified")

    def test_between_attempt_and_journaled_moves(self):
        self.prepare()
        self.verify()
        self.commit()  # relaxed observation before the new strict baseline
        self.dispatch()
        old = self.git("rev-parse", "HEAD")
        new = self.commit()
        p = subprocess.run(["bash", "-c", '. "$1/lib/lib.sh"; . "$1/lib/gitflow.sh"; journal_line "$2" refs/heads/develop "$3" "$4" fixture "" ""',
                            "fixture", str(ROOT), str(self.repo), old, new], env=self.env, text=True, capture_output=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.verify()
        before = self.record.read_bytes()
        self.verify()
        self.assertEqual(before, self.record.read_bytes(), "observation must not burn a retention slot")

    def test_remote_change_refused(self):
        remote = self.root / "remote.git"
        self.git("init", "--bare", "-q", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", "develop")
        self.prepare()
        self.verify()
        self.dispatch()
        self.commit()
        self.git("push", "-q", "origin", "develop")
        self.assertIn("ref of origin moved", self.cmd("local", "verify", self.run, ok=False))

    def test_repeated_verification_advances_refs_without_replacing_generation(self):
        for saved in (False, True):
            with self.subTest(saved=saved):
                self.prepare()
                self.dispatch()
                self.verify()
                first = self.state_json()["attempts"][-1]["verified"]
                marker = (self.saved / "attempt").read_bytes()
                output = self.bytes_tree(self.saved / "out")
                old = self.git("rev-parse", "HEAD")
                tip = self.commit()
                self.git("branch", "agent/new2")
                args = ("local", "verify", "--saved", self.run.name) if saved else ("local", "verify", self.run)
                self.cmd(*args)
                accepted = self.state_json()["attempts"][-1]
                self.assertEqual(accepted["verified"]["nonce"], first["nonce"])
                self.assertNotEqual(accepted["verified"]["sha256"], first["sha256"])
                self.assertEqual(len(accepted["history"]), 1)
                self.assertEqual(marker, (self.saved / "attempt").read_bytes())
                self.assertEqual(output, self.bytes_tree(self.saved / "out"))
                self.assertEqual(accepted["saved"], [])
                before = self.record.read_bytes()
                self.cmd(*args)
                self.assertEqual(before, self.record.read_bytes())
                self.git("branch", "-D", "agent/new2")
                self.assertIn("REFS CHANGED", self.cmd(*args, ok=False))
                self.git("branch", "agent/new2", tip)
                self.git("reset", "--hard", old)
                self.assertIn("REFS CHANGED", self.cmd(*args, ok=False))
                self.git("commit", "-q", "--allow-empty", "-m", "unrelated rewrite")
                self.assertIn("REFS CHANGED", self.cmd(*args, ok=False))
                self.git("reset", "--hard", tip)
                self.git("branch", "-D", "agent/new2")

    def test_dry_and_preflight_preserve_bytes(self):
        self.prepare()
        self.dispatch()
        self.verify()
        run_before, private_before = self.bytes_tree(self.run), self.bytes_tree(Path(self.store.path))
        saved_before = self.bytes_tree(self.saved)
        self.cmd("local", "run", self.run, "--again", "--dry-run")
        self.cmd("local", "run", self.run, "--again", "--model", "not-a-model", ok=False)
        self.assertEqual(run_before, self.bytes_tree(self.run))
        self.assertEqual(private_before, self.bytes_tree(Path(self.store.path)))
        self.assertEqual(saved_before, self.bytes_tree(self.saved))
        (self.run / "out/transcript").unlink()
        (self.run / "out/transcript").symlink_to(self.root / "nonexistent")
        self.dispatch(ok=False)
        self.assertEqual(private_before, self.bytes_tree(Path(self.store.path)))
        self.assertEqual(saved_before, self.bytes_tree(self.saved))

    def test_active_public_verbs_refuse_and_member_fds_closed(self):
        self.prepare()
        (self.run / "wait-member").touch()
        p = subprocess.Popen([str(ROOT / "bin/qargi"), "local", "run", str(self.run)],
                             env=self.env, cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 15
            while not (self.run / "member-ready").exists() and p.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue((self.run / "member-ready").exists())
            for args in [("local", "verify", self.run), ("review", "apply", self.run, "--project", "demo"),
                         ("local", "close", self.run, "--applied-by-am"), ("local", "clean", self.run, "--discard")]:
                self.assertIn("lifecycle lock", self.cmd(*args, ok=False))
            (self.run / "release-member").touch()
            out, err = p.communicate(timeout=15)
            self.assertEqual(p.returncode, 0, out + err)
            self.verify()
        finally:
            (self.run / "release-member").touch()
            if p.poll() is None:
                p.terminate()
            p.communicate(timeout=15)

    def test_missing_state_is_not_legacy_and_legacy_dispatch_refused(self):
        self.prepare()
        original = self.record.read_bytes()
        self.record.unlink()
        for args in [("local", "verify", self.run), ("local", "run", self.run), ("local", "clean", self.run, "--discard")]:
            self.cmd(*args, ok=False)
        self.record.write_bytes(original)
        self.record.chmod(0o600)
        self.record.write_text("{broken")
        self.cmd("local", "verify", self.run, ok=False)
        self.record.write_bytes(original)
        reg = self.state / "local-runs.jsonl"
        row = json.loads(reg.read_text())
        del row["lifecycle"]
        reg.write_text(json.dumps(row) + "\n")
        self.assertIn("legacy run", self.cmd("local", "verify", self.run))
        self.assertIn("legacy run", self.cmd("local", "run", self.run, ok=False))
        self.cmd("local", "clean", self.run, "--discard")

    def test_external_read_only_report_without_dispatch(self):
        self.prepare("review")
        self.cmd("review", "save", self.run, input="# Findings\nNo findings.\nverdict: accept\n")
        self.verify()
        self.assertIsNone(self.state_json()["attempts"][-1]["dispatch"])
        self.cmd("local", "clean", self.run)
        self.assertFalse(Path(self.store.path).exists())

    def test_saved_generation_failure_recovery_and_identity(self):
        self.prepare()
        (self.run / "out/report.md").write_text("C1")
        self.verify()
        r1 = self.state_json()["attempts"][-1]["verified"]
        with self.locked():
            marker = self.store.prepare_save()
            self.saved.mkdir(mode=0o700)
            (self.saved / "attempt").write_text(marker)
            (self.saved / "attempt").chmod(0o600)
            (self.saved / "out").mkdir()
            (self.saved / "out/report.md").write_text("failed C2")
            (self.saved / "refs.before").write_bytes((Path(self.store.path) / "prepared.refs").read_bytes())
            with self.assertRaises(A.Refuse):
                self.store.saved_copy()
        self.cmd("local", "verify", "--saved", self.run.name, ok=False)
        self.assertEqual(self.state_json()["attempts"][-1]["verified"], r1)
        self.assertEqual((Path(self.store.path) / "a1.saved.2/out/report.md").read_text(), "failed C2")
        (self.run / "out/report.md").write_text("C2 accepted")
        self.verify()
        self.assertNotEqual(self.state_json()["attempts"][-1]["verified"]["nonce"], r1["nonce"])
        self.assertEqual((self.saved / "out/report.md").read_text(), "C2 accepted")
        (self.saved / "attempt").write_text("0" * 32 + " 1 " + "0" * 32 + "\n")
        self.cmd("local", "verify", "--saved", self.run.name, ok=False)

    def test_setup_and_spawn_failures_keep_prior_products(self):
        self.prepare()
        self.dispatch()
        self.verify()
        report = (self.saved / "out/report.md").read_bytes()
        transcript = (self.saved / "out/transcript").read_bytes()
        # Valid executable selection, but the kernel cannot execute this format.
        self.fake.write_text("not an executable format\n")
        self.dispatch(ok=False)
        a = self.state_json()["attempts"][-1]
        self.assertIsNone(a["verified"])
        self.assertEqual(a["dispatch"]["outcome"], "not-started")
        retained = Path(self.store.path) / "a1.saved.1/out"
        self.assertEqual((retained / "report.md").read_bytes(), report)
        self.assertEqual((retained / "transcript").read_bytes(), transcript)
        # Exercise setup failure after begin via the same owning runtime function.
        with self.locked():
            refs = (Path(self.store.path) / a["baseline"]).read_bytes()
            pending = self.store.gate_pending(refs, epoch=int(time.time()))
            plan = {"final": None, "package": None}
            with mock.patch.object(R, "run_started", side_effect=OSError("setup failed")):
                with self.assertRaises(OSError):
                    R.run_it(plan, str(self.run), {"pending": pending, "refs": refs.decode()})
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "not-started")

    def test_injected_runner_fixture_uses_real_authority(self):
        self.prepare()
        with mock.patch.object(R, "main", R.main), mock.patch.object(R, "run_it", R.run_it):
            wire(R)
            self.assertEqual(R.main([str(self.run), "--project", "demo", "--runtime", "codex", "--class", "write"]), 0)
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "ok")
        for fd in (7, 8):
            with self.assertRaises(OSError):
                os.fstat(fd)

    def collect(self):
        clone = self.run / "clone"
        (clone / "result.txt").write_text("result\n")
        self.git("-c", "user.name=Fixture Member", "-c", "user.email=member@example.invalid", "add", "result.txt", repo=clone)
        self.git("-c", "user.name=Fixture Member", "-c", "user.email=member@example.invalid", "commit", "-q", "-m", "Add result", "-m",
                 "Record the offline fixture result for integration testing.", repo=clone)
        sha = self.git("rev-parse", "HEAD", repo=clone)
        patches = self.run / "out/patches"
        patches.mkdir()
        self.git("format-patch", "--binary", "-o", str(patches), self.sha + "..HEAD", repo=clone)
        manifest = {"status": "DONE", "commits": [{"sha": sha, "subject": "Add result"}],
                    "done": {"command": "true", "exit_code": 0},
                    "commit_advice": [{"sha": sha, "why_separate": "fixture", "depends_on": [], "builds_alone": True}],
                    "patch_groups": [{"name": "fixture", "why": "fixture", "commits": [sha]}]}
        (self.run / "out/manifest.json").write_text(json.dumps(manifest))
        (self.run / "out/series.md").write_text("One fixture patch.\n")

    def test_apply_uses_prepared_base_nested_verify_scrub_and_clean(self):
        self.prepare()
        self.collect()
        self.verify()
        # Legitimate lead move after verification cannot change the patch base.
        new = self.commit()
        (self.run / "refs.before").write_text(f"local refs/heads/develop {new}\n")
        self.cmd("review", "apply", self.run, "--project", "demo")
        self.assertEqual(self.git("rev-parse", "agent/example^"), self.sha)
        self.assertEqual(self.git("show", "-s", "--format=%an <%ae>", "agent/example"), "Fixture Lead <lead@example.invalid>")
        (self.run / "applied").unlink()  # the private apply record still refuses retry
        self.assertIn("apply record", self.dispatch(ok=False))
        self.git("merge", "--no-edit", "agent/example")
        self.cmd("local", "clean", self.run)
        self.assertFalse(self.run.exists())
        self.assertFalse(Path(self.store.path).exists())

    def test_closed_and_cleaned_retry_refused(self):
        self.prepare()
        self.collect()
        self.verify()
        self.cmd("local", "close", self.run, "--applied-by-am")
        self.assertIn("closed", self.dispatch(ok=False))
        self.cmd("local", "clean", self.run)
        self.cmd("local", "run", self.run, "--again", ok=False)

    def test_saved_apply_after_directory_loss(self):
        self.prepare()
        self.collect()
        self.verify()
        shutil.rmtree(self.run)
        self.cmd("local", "verify", "--saved", self.run.name)
        self.cmd("review", "apply", "--from-saved", self.run.name, "--project", "demo")
        self.assertEqual(self.git("rev-parse", "agent/example^"), self.sha)
        self.git("merge", "--no-edit", "agent/example")
        self.cmd("local", "clean", self.run)

    def test_replacement_during_scrub_is_scrubbed_at_apply(self):
        scrub = self.root / "scrub.py"
        self.answers["review"]["scrub"] = "python3 " + shlex.quote(str(scrub))
        (self.conf / "projects/demo.json").write_text(json.dumps(self.answers))
        self.prepare()
        self.collect()
        patch = next((self.run / "out/patches").glob("*.patch"))
        scrub.write_text("from pathlib import Path\n"
                         "assert Path('result.txt').read_text() == 'result\\n', 'reject replacement'\n"
                         f"p = Path({str(patch)!r})\n"
                         "p.write_text(p.read_text().replace('+result\\n', '+BAD\\n'))\n")
        self.cmd("review", "check", self.run / "out")
        self.assertIn("scrub", self.cmd("review", "apply", self.run, "--project", "demo", ok=False))
        self.assertEqual(self.git("branch", "--list", "agent/example"), "")

    def test_changed_accepted_output_refused_by_verify_check_apply(self):
        self.prepare()
        self.collect()  # External/session output: no local dispatch.
        self.verify()
        original = self.bytes_tree(self.saved / "out")
        patch = next((self.run / "out/patches").glob("*.patch"))
        patch.write_text(patch.read_text().replace('+result\n', '+changed\n'))
        for args in [("local", "verify", self.run), ("review", "check", self.run / "out"),
                     ("review", "apply", self.run, "--project", "demo")]:
            self.assertIn("OUT changed since acceptance", self.cmd(*args, ok=False))
        self.assertEqual(original, self.bytes_tree(self.saved / "out"))
        self.assertEqual(self.git("branch", "--list", "agent/example"), "")

    def test_historical_runs_directory_permissions_upgrade(self):
        self.prepare()
        runs = self.state / "runs"
        runs.mkdir(mode=0o755)
        runs.chmod(0o755)
        self.verify()
        self.assertEqual(runs.stat().st_mode & 0o777, 0o700)

    def test_failed_retry_stale_cleanup_keeps_retained_product(self):
        self.prepare()
        (self.run / "out/report.md").write_text("C1")
        self.verify()
        self.fake.write_text("not executable format\n")
        self.dispatch(ok=False)
        self.assertIn("cannot be attributed", self.cmd("local", "verify", self.run, ok=False))
        retained = Path(self.store.path) / "a1.saved.1/out/report.md"
        shutil.rmtree(self.run)
        self.cmd("local", "clean", "--stale", "0", "--scratch", self.root, "--yes", ok=False)
        self.assertEqual(retained.read_text(), "C1")
        self.assertTrue(self.record.exists())

    def test_real_prelaunch_signal_records_not_started(self):
        self.prepare()
        for signum in (signal.SIGTERM, signal.SIGHUP):
            with self.subTest(signal=signum), self.locked():
                refs = (Path(self.store.path) / "prepared.refs").read_bytes()
                pending = self.store.gate_pending(refs, epoch=int(time.time()))
                original = A.Store.begin
                def begin(store, *args):
                    result = original(store, *args)
                    os.kill(os.getpid(), signum)
                    return result
                with mock.patch.object(A.Store, "begin", begin), mock.patch.object(R, "run_started") as started:
                    rc = R.run_it({"final": None, "package": None}, str(self.run),
                                  {"pending": pending, "refs": refs.decode()})
                self.assertEqual(rc, 128 + signum)
                started.assert_not_called()
                self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "not-started")
        self.cmd("local", "clean", self.run, "--discard")

    def test_dead_owner_unknown_window_refuses_even_discard(self):
        self.prepare()
        # A real short-lived owning process commits begin without member().
        code = '''import sys, os, fcntl, time
sys.path.insert(0, sys.argv[1])
import attempts as A
s = A.Store(sys.argv[2]); f = s.open_lock()
if f != 7: os.dup2(f, 7); os.close(f)
fcntl.flock(7, fcntl.LOCK_EX)
refs = open(s.path + '/prepared.refs', 'rb').read()
s.begin(s.gate_pending(refs, epoch=int(time.time())), refs)
'''
        p = subprocess.run([sys.executable, "-c", code, str(ROOT / "lib"), str(self.run)], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        (self.run / "dispatch.json").write_text('{"outcome":"ok"}')
        for args in [("local", "verify", self.run), ("local", "clean", self.run, "--discard"), ("local", "run", self.run, "--again")]:
            self.assertIn("liveness unknown", self.cmd(*args, ok=False))

    def test_dead_owner_with_ended_group_reconciles_lost(self):
        self.prepare()
        code = '''import sys, os, fcntl, time, subprocess
sys.path.insert(0, sys.argv[1])
import attempts as A
s = A.Store(sys.argv[2]); f = s.open_lock()
if f != 7: os.dup2(f, 7); os.close(f)
fcntl.flock(7, fcntl.LOCK_EX)
refs = open(s.path + '/prepared.refs', 'rb').read()
s.begin(s.gate_pending(refs, epoch=int(time.time())), refs)
p = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read()'], stdin=subprocess.PIPE,
                     start_new_session=True, close_fds=True)
s.member(p.pid)
p.communicate(timeout=5)
'''
        p = subprocess.run([sys.executable, "-c", code, str(ROOT / "lib"), str(self.run)], env=self.env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertIn("cannot be attributed", self.cmd("local", "verify", self.run, ok=False))
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "lost")


if __name__ == "__main__":
    unittest.main(verbosity=2)
