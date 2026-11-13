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
from attempt_fixture import wire, ForkAfterEnumeration


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
import os, subprocess, sys, time
from pathlib import Path
run = Path.cwd().parent
assert not Path('/proc/self/fd/7').exists(), 'member inherited lifecycle lock'
assert not Path('/proc/self/fd/8').exists(), 'member inherited pending plan'
if (run / 'wait-member').exists():
    if (run / 'spawn-child').exists():
        subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
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

    def unmark(self, **changes):
        """Reconstruct a released run, without inventing private authority."""
        shutil.rmtree(self.store.path)
        registry = self.state / 'local-runs.jsonl'
        rows = [json.loads(line) for line in registry.read_text().splitlines()]
        row = next(r for r in rows if r['run'] == str(self.run))
        del row['lifecycle']
        row.update(changes)
        registry.write_text(''.join(json.dumps(r) + '\n' for r in rows))

    def registry_row(self):
        rows = [json.loads(line) for line in (self.state / 'local-runs.jsonl').read_text().splitlines()]
        return next(r for r in rows if r['run'] == str(self.run))

    def test_legacy_discard_recovers_without_adoption_and_ignores_member_tmp(self):
        self.prepare()
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        decoy = self.root / 'qargi-run.Decoy1'
        decoy.mkdir()
        (decoy / 'keep').write_text('not registered')
        (self.run / 'tmpdir').write_text(str(decoy))
        self.unmark()
        registry = self.state / 'local-runs.jsonl'
        row = self.registry_row()
        del row['class']  # classless discard remains the explicit recovery route
        registry.write_text(json.dumps(row) + '\n')
        out = self.cmd('local', 'clean', self.run, '--discard')
        self.assertIn('unmarked legacy run', out)
        self.assertIn('no proof of process quiescence', out)
        self.assertFalse(self.run.exists() or tmp.exists())
        self.assertEqual((decoy / 'keep').read_text(), 'not registered')
        self.assertNotIn('lifecycle', self.registry_row())
        self.assertTrue(self.registry_row().get('cleaned'))
        self.assertFalse(Path(self.store.path).exists())

    def test_legacy_discard_preserves_unconfined_or_linked_tmp(self):
        for form in ('outside-parent', 'link'):
            with self.subTest(form=form):
                self.prepare()
                elsewhere = self.root / ('elsewhere-' + form)
                elsewhere.mkdir()
                decoy = elsewhere / 'qargi-run.Decoy2'
                decoy.mkdir()
                (decoy / 'keep').write_text('another run')
                named = decoy
                if form == 'link':
                    named = self.root / 'qargi-run.Link01'
                    named.symlink_to(decoy)
                self.unmark(tmpdir=str(named))
                out = self.cmd('local', 'clean', self.run, '--discard')
                self.assertIn('left %s alone' % named, out)
                self.assertFalse(self.run.exists())
                self.assertEqual((decoy / 'keep').read_text(), 'another run')
                self.assertTrue(named.is_symlink() if form == 'link' else named.is_dir())

    def test_legacy_stale_and_applied_batches_and_retained_evidence(self):
        for route in ('stale', 'applied', 'gone-kept', 'gone-empty'):
            with self.subTest(route=route):
                self.prepare('build' if route == 'applied' else 'review')
                tmp = Path((self.run / 'tmpdir').read_text().strip())
                (self.run / 'out/report.md').write_text('# Findings\nNo findings.\nverdict: accept\n')
                if route == 'applied':
                    (self.run / 'out/manifest.json').write_text(json.dumps({'status': 'DONE', 'commits': []}))
                self.unmark(started='2020-01-01T00:00:00Z')
                self.verify()  # exercise the actual legacy save helper
                self.assertFalse((self.saved / 'attempt').exists())
                self.assertFalse(Path(self.store.path).exists())
                if route == 'applied':
                    self.cmd('local', 'close', self.run, '--applied-by-am')
                    out = self.cmd('local', 'clean', '--applied', '--scratch', self.root)
                else:
                    if route.startswith('gone'):
                        shutil.rmtree(self.run)
                        if route == 'gone-empty':
                            shutil.rmtree(self.saved)
                    plan = self.cmd('local', 'clean', '--stale', '0', '--scratch', self.root)
                    self.assertIn(str(self.run), plan)
                    out = self.cmd('local', 'clean', '--stale', '0', '--scratch', self.root,
                                   '--yes', ok=route != 'gone-kept')
                if route == 'gone-kept':
                    self.assertIn('work that was never applied', out)
                    self.assertTrue((self.saved / 'out/report.md').exists())
                    self.cmd('local', 'clean', self.run, '--discard')
                else:
                    self.assertIn('unmarked legacy run', out)
                self.assertFalse(self.run.exists() or self.saved.exists())
                self.assertFalse(Path(self.store.path).exists())
                if route.startswith('gone'):
                    # Released recovery drops the absent RUN's row; TMP is left as an orphan.
                    self.assertTrue(tmp.exists())
                    with self.assertRaises(StopIteration):
                        self.registry_row()
                else:
                    self.assertFalse(tmp.exists())
                    self.assertTrue(self.registry_row().get('cleaned'))

    def test_legacy_internal_tmp_and_failed_one_filesystem_removal(self):
        self.env['QARGI_RUN_TMP'] = str(self.root / 'unavailable')
        self.prepare()
        tmp = self.run / 'tmp'
        self.assertTrue(tmp.is_dir())
        (tmp / 'keep').write_text('mounted evidence')
        self.unmark()
        shim = self.bin / 'rm'
        real_rm = shutil.which('rm')
        shim.write_text(f'#!{sys.executable}\nimport os, sys\n'
                        f'if {str(tmp)!r} in sys.argv:\n'
                        "    assert '--one-file-system' in sys.argv\n"
                        '    sys.exit(1)\n'
                        f'os.execv({real_rm!r}, [{real_rm!r}, *sys.argv[1:]])\n')
        shim.chmod(0o755)
        out = self.cmd('local', 'clean', self.run, '--discard', ok=False)
        self.assertIn('not recorded as cleaned', out)
        self.assertEqual((tmp / 'keep').read_text(), 'mounted evidence')
        self.assertFalse(self.registry_row().get('cleaned'))
        shim.unlink()
        self.cmd('local', 'clean', self.run, '--discard')
        self.assertFalse(self.run.exists())

    def test_prepare_canonical_tmp_paths_and_repointed_alias_cleanup(self):
        parent = self.root / 'real-tmp'
        parent.mkdir()
        alias = self.root / 'alias-tmp'
        alias.symlink_to(parent, target_is_directory=True)
        decoy = self.root / 'decoy-tmp'
        decoy.mkdir()
        task = self.root / 'input-task'
        task.write_text('Offline canonical path fixture')
        for spelling in ('alias', 'relative', 'dotdot'):
            for role in ('build', 'review'):
                with self.subTest(spelling=spelling, role=role):
                    named = {'alias': str(alias), 'relative': '../real-tmp',
                             'dotdot': str(self.repo / '../real-tmp') + '/'}[spelling]
                    self.env['QARGI_RUN_TMP'] = named
                    out = self.cmd('local', 'prepare', '--repo', self.repo, '--base', 'develop',
                                   '--slug', 'canonical', '--scratch', self.root, '--role', role,
                                   '--task-file', task, '--done', 'true')
                    run = Path(next(l[4:] for l in out.splitlines() if l.startswith('RUN=')))
                    tmp = Path(next(l[4:] for l in out.splitlines() if l.startswith('TMP=')))
                    self.assertEqual(tmp.parent, parent)
                    self.assertEqual((run / 'tmpdir').read_text().strip(), str(tmp))
                    self.assertIn('TMP: ' + str(tmp), (run / 'task.md').read_text())
                    rows = [json.loads(l) for l in (self.state / 'local-runs.jsonl').read_text().splitlines()]
                    self.assertEqual(next(r for r in rows if r['run'] == str(run))['tmpdir'], str(tmp))
                    work = json.loads((Path(A.Store(run).path) / 'work.json').read_text())
                    self.assertEqual(work['tmp']['path'], str(tmp))
                    if spelling == 'alias':
                        alias.unlink()
                        alias.symlink_to(decoy, target_is_directory=True)
                        other = decoy / tmp.name
                        other.mkdir()
                        (other / 'keep').write_text('decoy')
                    self.cmd('local', 'clean', run, '--discard')
                    self.assertFalse(tmp.exists() or run.exists())
                    if spelling == 'alias':
                        self.assertEqual((other / 'keep').read_text(), 'decoy')
                        alias.unlink()
                        alias.symlink_to(parent, target_is_directory=True)

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
        before = self.bytes_tree(self.run)
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        self.assertIn('ownership unavailable', self.cmd('local', 'clean', self.run, '--discard', ok=False))
        self.assertEqual(before, self.bytes_tree(self.run))
        self.assertTrue(tmp.is_dir())

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

    def test_runtime_failure_timeout_and_unknown_probe_cannot_complete_ok(self):
        for mode in ('failure', 'timeout', 'unknown-probe'):
            with self.subTest(mode=mode):
                self.prepare()
                code = {'failure': 'raise SystemExit(7)',
                        'timeout': 'import time; time.sleep(30)',
                        'unknown-probe': 'pass'}[mode]
                self.fake.write_text('#!/usr/bin/env python3\n' + code + '\n')
                with mock.patch.object(R, 'main', R.main), mock.patch.object(R, 'run_it', R.run_it):
                    wire(R)
                    probe = (mock.patch.object(R, 'group_left', side_effect=PermissionError('unknown group'))
                             if mode == 'unknown-probe' else contextlib.nullcontext())
                    with probe:
                        rc = R.main([str(self.run), '--project', 'demo', '--runtime', 'codex',
                                     '--class', 'write', '--timeout', '1'])
                self.assertNotEqual(rc, 0)
                dispatch = json.loads((self.run / 'dispatch.json').read_text())
                self.assertEqual(dispatch['timed_out'], mode == 'timeout')
                self.assertEqual(dispatch['outcome'], 'refused' if mode == 'unknown-probe' else 'failed')
                if mode == 'unknown-probe':
                    self.assertIsNone(dispatch['group_left'])
                self.assertEqual(self.state_json()['attempts'][-1]['dispatch']['outcome'], 'failed')
                self.assertIsNone(self.state_json()['attempts'][-1]['verified'])
                self.assertFalse(R.group_left(dispatch['member']))

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

    def test_forked_group_refuses_public_retry_and_cleanup_preserving_evidence(self):
        self.prepare('review')
        self.cmd('review', 'save', self.run, input='# Findings\nNo findings.\nverdict: accept\n')
        self.verify()
        with ForkAfterEnumeration() as group:
            with self.locked():
                refs = (Path(self.store.path) / 'prepared.refs').read_bytes()
                self.store.begin(self.store.gate_pending(refs, epoch=int(time.time())), refs)
                self.store.member(group.pgid)
                original = os.listdir
                def enumerate_then_fork(path):
                    names = original(path)
                    if path == '/proc':
                        group.fork_and_exit()
                        self.assertNotIn(str(group.child), names)
                    return names
                with mock.patch.object(os, 'listdir', side_effect=enumerate_then_fork):
                    with self.assertRaisesRegex(A.Refuse, 'quiescence unknown'):
                        self.store.end('ok')
                record = self.state_json()
                record['attempts'][-1]['dispatch']['runner']['token'] = '0'
                self.record.write_bytes(A.encode(record))
            tmp = Path((self.run / 'tmpdir').read_text().strip())
            (tmp / 'evidence').write_text('keep')
            snapshot = lambda: [self.bytes_tree(p) for p in (self.run, tmp, Path(self.store.path))]
            before = snapshot()
            for args in (('run', self.run, '--again'), ('clean', self.run), ('clean', self.run, '--discard')):
                self.assertIn('busy', self.cmd('local', *args, ok=False))
                self.assertEqual(before, snapshot())
        self.cmd('local', 'clean', self.run, '--discard')

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

    def test_late_signal_preserves_completed_attempt_for_verify(self):
        self.prepare()
        self.collect()
        original = R.clear_home
        def late(*args):
            result = original(*args)
            os.kill(os.getpid(), signal.SIGTERM)
            return result
        with mock.patch.object(R, "main", R.main), mock.patch.object(R, "run_it", R.run_it), \
                mock.patch.object(R, "clear_home", side_effect=late):
            wire(R)
            rc = R.main([str(self.run), "--project", "demo", "--runtime", "codex", "--class", "write"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads((self.run / "dispatch.json").read_text())["outcome"], "ok")
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "ok")
        self.verify()
        self.assertIsNotNone(self.state_json()["attempts"][-1]["verified"])

    def test_running_signal_cancels_attempt_and_stops_group(self):
        self.prepare()
        (self.run / "wait-member").touch()
        (self.run / "spawn-child").touch()
        original = subprocess.Popen.wait
        def interrupt(proc, *args, **kwargs):
            if kwargs.get("timeout") and not (self.run / "member-ready").exists():
                deadline = time.monotonic() + 10
                while not (self.run / "member-ready").exists() and time.monotonic() < deadline:
                    time.sleep(.01)
                self.assertTrue((self.run / "member-ready").exists())
                os.kill(os.getpid(), signal.SIGTERM)
            return original(proc, *args, **kwargs)
        with mock.patch.object(R, "main", R.main), mock.patch.object(R, "run_it", R.run_it), \
                mock.patch.object(subprocess.Popen, "wait", interrupt):
            wire(R)
            rc = R.main([str(self.run), "--project", "demo", "--runtime", "codex", "--class", "write"])
        self.assertEqual(rc, 128 + signal.SIGTERM)
        dispatch = json.loads((self.run / "dispatch.json").read_text())
        self.assertEqual(dispatch["outcome"], "interrupted")
        self.assertFalse(R.group_left(dispatch["member"]))
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "cancelled")

    def test_failed_retry_cannot_accept_prior_external_output(self):
        self.prepare()
        self.collect()
        self.verify()
        original = self.bytes_tree(self.saved / "out")
        self.fake.write_text("#!/usr/bin/env python3\nraise SystemExit(1)\n")
        self.dispatch(ok=False)
        self.assertEqual(self.state_json()["attempts"][-1]["dispatch"]["outcome"], "failed")
        check = self.cmd("review", "check", self.run / "out")
        self.assertIn("structural validation of unsuccessful-attempt output is not acceptance", check)
        for args in [("local", "verify", self.run), ("review", "apply", self.run, "--project", "demo")]:
            self.assertIn("cannot be attributed", self.cmd(*args, ok=False))
        self.assertIsNone(self.state_json()["attempts"][-1]["verified"])
        self.assertEqual(original, self.bytes_tree(Path(self.store.path) / "a1.saved.1/out"))

    def test_dead_apply_parent_keeps_live_hook_worktree(self):
        self.prepare()
        self.collect()
        hook = self.repo / ".git/hooks/applypatch-msg"
        hook_ready, release = self.root / "hook-ready", self.root / "hook-release"
        hook.write_text(f"#!{sys.executable}\nimport os, time\nfrom pathlib import Path\n"
                        "assert not Path('/proc/self/fd/7').exists()\n"
                        f"Path({str(hook_ready)!r}).write_text(str(os.getpid()))\n"
                        f"while not Path({str(release)!r}).exists(): time.sleep(.02)\n")
        hook.chmod(0o755)
        p = subprocess.Popen([str(ROOT / "bin/qargi"), "review", "apply", str(self.run), "--project", "demo"],
                             cwd=self.repo, env=self.env, start_new_session=True,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            deadline = time.monotonic() + 20
            while not hook_ready.exists() and p.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(hook_ready.exists())
            record = self.state / "apply" / (self.run.name + ".json")
            apply = json.loads(record.read_text())
            os.kill(apply["pid"], signal.SIGKILL)
            p.wait(timeout=5)
            hook_pid = int(hook_ready.read_text())
            os.kill(hook_pid, 0)
            worktrees = list(self.state.glob("apply-wt.*"))
            self.assertEqual(len(worktrees), 1)
            for args in [("local", "clean", self.run), ("local", "clean", self.run, "--discard"),
                         ("review", "apply", self.run, "--project", "demo")]:
                self.assertIn("Git-child liveness is unknown", self.cmd(*args, ok=False))
                self.assertTrue(worktrees[0].exists())
                self.assertTrue(record.exists())
                self.assertTrue(self.run.exists())
                os.kill(hook_pid, 0)
        finally:
            release.touch()
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            p.communicate(timeout=10)

    def test_built_apply_bookkeeping_can_resume(self):
        self.prepare()
        self.collect()
        self.cmd("review", "apply", self.run, "--project", "demo")
        tip = self.git("rev-parse", "agent/example")
        record = self.state / "apply" / (self.run.name + ".json")
        row = json.loads(record.read_text())
        row.update(status="built", pid=2**31 - 1, ptoken="0")
        record.write_text(json.dumps(row))
        self.assertIn("finishing it", self.cmd("review", "apply", self.run, "--project", "demo"))
        self.assertEqual(json.loads(record.read_text())["status"], "done")
        self.assertEqual(self.git("rev-parse", "agent/example"), tip)

    def test_sigkill_during_save_recovers_single_owned_stage(self):
        self.prepare()
        (self.run / "out/report.md").write_text("product")
        ready = self.root / "copy-ready"
        code = '''import sys, os, fcntl, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import attempts as A
s = A.Store(sys.argv[2]); fd = s.open_lock()
if fd != 7: os.dup2(fd, 7); os.close(fd)
fcntl.flock(7, fcntl.LOCK_EX)
copy = A.copy_product
def stop_after_copy(src, dst):
    copy(src, dst)
    Path(sys.argv[3]).touch()
    while True: time.sleep(.02)
A.copy_product = stop_after_copy
A.save_product(s, Path(s.path + '/prepared.refs').read_bytes())
'''
        for _ in range(2):
            p = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "lib"), str(self.run), str(ready)], env=self.env)
            try:
                deadline = time.monotonic() + 10
                while not ready.exists() and p.poll() is None and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(ready.exists())
            finally:
                p.kill()
                p.wait(timeout=5)
            self.assertTrue((Path(self.store.path) / "save.stage/out/report.md").exists())
            ready.unlink()
        self.verify()
        self.assertEqual((self.saved / "out/report.md").read_text(), "product")
        self.assertFalse((Path(self.store.path) / "save.stage").exists())
        self.assertFalse((Path(self.store.path) / "save-stage.json").exists())

    def test_interrupted_clean_resumes_at_each_private_boundary(self):
        for boundary in ("intent", "saved-rename", "staged", "registry", "marker-removed", "state-removed"):
            with self.subTest(boundary=boundary):
                self.prepare()
                tmp = Path((self.run / 'tmpdir').read_text().strip())
                (tmp / 'evidence').write_text('temporary evidence')
                (self.run / "out/report.md").write_text("retained product")
                self.verify()
                with self.locked():
                    self.store.clean_begin(discard=True)
                    if boundary == "saved-rename":
                        rename = A.os.rename
                        def interrupted_rename(*args, **kw):
                            rename(*args, **kw)
                            raise OSError("interrupted after rename")
                        with mock.patch.object(A.os, "rename", side_effect=interrupted_rename):
                            with self.assertRaises(OSError):
                                self.store.clean_stage()
                    elif boundary != "intent":
                        self.store.clean_stage()
                    if boundary in ("registry", "marker-removed", "state-removed"):
                        p = subprocess.run(["bash", "-c", '. "$1/lib/lib.sh"; reg_edit "$2" cleaned',
                                            "test", str(ROOT), str(self.run)], env=self.env, capture_output=True)
                        self.assertEqual(p.returncode, 0, p.stderr)
                        if boundary != "registry":
                            remove = A.shutil.rmtree
                            def interrupted_remove(name, **kw):
                                if boundary == "marker-removed":
                                    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY, dir_fd=kw["dir_fd"])
                                    try:
                                        os.unlink("attempt", dir_fd=fd)
                                    finally:
                                        os.close(fd)
                                    raise OSError("interrupted after marker deletion")
                                remove(name, **kw)
                                if name == self.run.name + ".clean":
                                    raise OSError("interrupted after state removal")
                            with mock.patch.object(A.shutil, "rmtree", side_effect=interrupted_remove) as removal:
                                removal.avoids_symlink_attacks = True
                                with self.assertRaises(OSError):
                                    self.store.clean_finish()
                    else:
                        with self.assertRaisesRegex(A.Refuse, "registry must commit"):
                            self.store.clean_finish()
                self.assertIn("finished interrupted cleanup", self.cmd("local", "clean", self.run))
                self.assertFalse(self.run.exists())
                self.assertFalse(tmp.exists())
                self.assertFalse(self.saved.exists())
                self.assertFalse(Path(self.store.path).exists())
                self.assertFalse(Path(self.store.path + ".clean").exists())
                self.assertFalse((Path(self.store.area) / self.store.clean_name).exists())
                self.assertIn("cleaned already", self.cmd("local", "clean", self.run))

    def test_refused_clean_preserves_tmp_run_and_retained_review_generation(self):
        self.prepare('review')
        self.cmd('review', 'save', self.run, input='# Findings\nNo findings.\nverdict: accept\n')
        self.verify()
        with self.locked():
            refs = (Path(self.store.path) / 'prepared.refs').read_bytes()
            pending = self.store.gate_pending(refs, epoch=int(time.time()))
            original = A.Store.begin
            def begin(store, *args):
                result = original(store, *args)
                os.kill(os.getpid(), signal.SIGTERM)
                return result
            with mock.patch.object(A.Store, 'begin', begin), mock.patch.object(R, 'run_started') as started:
                rc = R.run_it({'final': None, 'package': None}, str(self.run),
                              {'pending': pending, 'refs': refs.decode()})
        self.assertEqual(rc, 128 + signal.SIGTERM)
        started.assert_not_called()
        self.assertEqual(self.state_json()['attempts'][-1]['dispatch']['outcome'], 'not-started')
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        (tmp / 'wanted-evidence').write_text('keep')
        self.assertTrue((Path(self.store.path) / 'a1.saved.1/out').is_dir())
        snapshot = lambda: [self.bytes_tree(p) for p in (tmp, self.run, Path(self.store.path))]
        kept = snapshot()
        self.assertIn('explicit discard', self.cmd('local', 'clean', self.run, ok=False))
        self.assertEqual(kept, snapshot())
        self.assertEqual((tmp / 'wanted-evidence').read_text(), 'keep')
        self.assertFalse((Path(self.store.area) / self.store.clean_name).exists())
        self.cmd('local', 'clean', self.run, '--discard')
        self.assertFalse(tmp.exists())
        self.assertFalse(self.run.exists())

    def test_interrupted_clean_uses_owned_tmp_never_member_named_directory(self):
        self.prepare()
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        decoy = self.root / 'qargi-run.Decoy1'
        decoy.mkdir(mode=0o700)
        (decoy / 'keep').write_text('another run')
        (self.run / 'tmpdir').write_text(str(decoy) + '\n')
        with self.locked():
            self.store.clean_begin(discard=True)
            self.store.clean_stage()
        self.assertIn('finished interrupted cleanup', self.cmd('local', 'clean', self.run))
        self.assertFalse(tmp.exists())
        self.assertFalse(self.run.exists())
        self.assertEqual((decoy / 'keep').read_text(), 'another run')

    def test_cleanup_refuses_replaced_tmp_before_staging(self):
        for boundary in ('before-intent', 'after-intent'):
            with self.subTest(boundary=boundary):
                self.prepare('review')
                self.cmd('review', 'save', self.run, input='# Findings\nNo findings.\nverdict: accept\n')
                self.verify()
                tmp = Path((self.run / 'tmpdir').read_text().strip())
                if boundary != 'before-intent':
                    with self.locked():
                        self.store.clean_begin(discard=True)
                        self.store.clean_stage()
                if tmp.exists():
                    tmp.rename(tmp.with_name(tmp.name + '.kept'))
                tmp.mkdir(mode=0o700)
                (tmp / 'replacement').write_text('must not delete')
                snapshot = lambda: [self.bytes_tree(p) for p in (tmp, self.run, self.state / 'attempts', self.state / 'runs')]
                kept = snapshot()
                out = self.cmd('local', 'clean', self.run, '--discard', ok=False)
                self.assertIn('ownership mismatch', out)
                self.assertEqual(kept, snapshot())
                self.assertTrue(self.run.exists())

    def interrupted_work_cleanup(self, key, point):
        """Crash at rename, staged commit, deletion or removed commit of TMP/RUN."""
        item = json.loads((Path(self.store.path) / 'work.json').read_text())[key]
        source = Path(item['path'])
        tomb = Path(A.Store._work_tomb(item, self.state_json()['prepared']['identity']))
        nth = 1 if key == 'tmp' else 2
        seen = []
        real_sync, real_rm, real_commit = A.sync_dir, A.subprocess.run, self.store._clean_commit
        def sync(fd, effect):
            real_sync(fd, effect)
            if point == 'rename' and effect == 'work cleanup rename':
                seen.append(effect)
                if len(seen) == nth:
                    raise OSError('interrupted after rename')
        def remove(*args, **kwargs):
            result = real_rm(*args, **kwargs)
            if point == 'delete':
                seen.append('rm')
                if len(seen) == nth:
                    raise OSError('interrupted after deletion')
            return result
        def commit(row):
            real_commit(row)
            if point in ('staged', 'removed') and row['work'][key]['phase'] == point:
                raise OSError('interrupted after phase commit')
        with self.locked():
            self.store.clean_begin(discard=True)
            self.store.clean_stage()
            with mock.patch.object(A, 'sync_dir', sync), mock.patch.object(A.subprocess, 'run', remove), \
                    mock.patch.object(self.store, '_clean_commit', commit):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    self.store.clean_work()
        self.assertEqual(tomb.exists(), point in ('rename', 'staged'))
        return source, tomb

    def test_cleanup_preserves_replacements_and_finishes(self):
        for key in ('tmp', 'run'):
            for point in ('rename', 'staged', 'delete', 'removed'):
                with self.subTest(key=key, point=point):
                    self.prepare('review')
                    self.cmd('review', 'save', self.run, input='# Findings\nNo findings.\nverdict: accept\n')
                    self.verify()
                    tmp = Path((self.run / 'tmpdir').read_text().strip())
                    source, tomb = self.interrupted_work_cleanup(key, point)
                    source.mkdir(mode=0o700)
                    (source / 'replacement').write_text('must not delete')
                    preserved = self.bytes_tree(source)
                    out = self.cmd('local', 'clean', self.run)
                    self.assertIn('replacement preserved', out)
                    self.assertIn(str(source), out)
                    self.assertEqual(preserved, self.bytes_tree(source))
                    self.assertFalse(tomb.exists())
                    self.assertFalse((self.run if key == 'tmp' else tmp).exists())
                    self.assertFalse(Path(self.store.path).exists() or Path(self.store.path + '.clean').exists())
                    self.assertFalse((Path(self.store.area) / self.store.clean_name).exists())
                    self.assertFalse(self.saved.exists())
                    self.assertTrue(self.registry_row().get('cleaned'))
                    shutil.rmtree(source)

    def test_removed_parent_and_tombstone_recreation(self):
        for kind in ('recreated', 'missing', 'tombstone'):
            with self.subTest(kind=kind):
                rt = self.root / ('rt-' + kind)
                rt.mkdir(mode=0o700)
                self.env['QARGI_RUN_TMP'] = str(rt)
                self.prepare()
                source, tomb = self.interrupted_work_cleanup('tmp', 'removed')
                if kind != 'tombstone':
                    rt.rename(rt.with_name(rt.name + '.old'))
                    if kind == 'recreated':
                        rt.mkdir(mode=0o700)
                if kind != 'missing':
                    for path in (source, tomb):
                        path.mkdir(mode=0o700)
                        (path / 'keep').write_text('foreign')
                    before = [self.bytes_tree(p) for p in (source, tomb)]
                out = self.cmd('local', 'clean', self.run)
                if kind != 'missing':
                    self.assertEqual(before, [self.bytes_tree(p) for p in (source, tomb)])
                self.assertEqual('replacement preserved' in out, kind == 'tombstone')
                self.assertTrue(self.registry_row().get('cleaned'))
                self.assertFalse(self.run.exists())

    def test_staged_parent_recreation_still_refuses(self):
        for kind in ('recreated', 'missing'):
            with self.subTest(kind=kind):
                rt = self.root / ('staged-' + kind)
                rt.mkdir(mode=0o700)
                self.env['QARGI_RUN_TMP'] = str(rt)
                self.prepare()
                source, tomb = self.interrupted_work_cleanup('tmp', 'staged')
                old = rt.with_name(rt.name + '.old')
                rt.rename(old)
                if kind == 'recreated':
                    rt.mkdir(mode=0o700)
                out = self.cmd('local', 'clean', self.run, ok=False)
                self.assertRegex(out, 'parent (ownership mismatch|missing)')
                self.assertTrue((old / tomb.name).is_dir())
                self.assertTrue(self.run.exists())

    def test_internal_tmp_cleanup_never_traverses_replacement_run(self):
        self.env['QARGI_RUN_TMP'] = str(self.root / 'unavailable')
        for point in ('rename', 'staged', 'delete', 'removed'):
            for kind in ('directory', 'symlink'):
                with self.subTest(point=point, kind=kind):
                    self.prepare()
                    identity = self.state_json()['prepared']['identity']
                    source, tomb = self.interrupted_work_cleanup('run', point)
                    decoy = self.root / ('decoy-' + point + '-' + kind)
                    decoy.mkdir(mode=0o700)
                    if kind == 'symlink':
                        source.symlink_to(decoy, target_is_directory=True)
                    else:
                        source.mkdir(mode=0o700)
                    (source / 'tmp').mkdir()
                    (source / 'tmp/keep').write_text('replacement TMP')
                    (source / ('.clean.tmp.' + identity)).mkdir()
                    (source / ('.clean.tmp.' + identity) / 'keep').write_text('foreign tomb in replacement RUN')
                    preserved = self.bytes_tree(source)
                    # A row at the symlink target must not be marked cleaned by resolution.
                    registry = self.state / 'local-runs.jsonl'
                    with registry.open('a') as stream:
                        stream.write(json.dumps({'run': str(decoy), 'sentinel': 'unchanged'}) + '\n')
                    decoy_row = registry.read_text().splitlines()[-1]
                    out = self.cmd('local', 'clean', self.run, '--discard')
                    self.assertIn('replacement preserved', out)
                    self.assertEqual(preserved, self.bytes_tree(source))
                    self.assertEqual(source.is_symlink(), kind == 'symlink')
                    self.assertFalse(tomb.exists())
                    self.assertTrue(self.registry_row().get('cleaned'))
                    self.assertEqual(registry.read_text().splitlines()[-1], decoy_row)
                    self.assertFalse((Path(self.store.area) / self.store.clean_name).exists())

    def test_external_cleanup_preserves_replacement_symlinks(self):
        for key in ('tmp', 'run'):
            for point in ('staged', 'delete'):
                with self.subTest(key=key, point=point):
                    self.prepare()
                    source, tomb = self.interrupted_work_cleanup(key, point)
                    decoy = self.root / ('decoy-' + key + '-' + point)
                    decoy.mkdir()
                    (decoy / 'keep').write_text('untouched')
                    source.symlink_to(decoy, target_is_directory=True)
                    out = self.cmd('local', 'clean', self.run)
                    self.assertIn('replacement preserved', out)
                    self.assertTrue(source.is_symlink())
                    self.assertEqual((decoy / 'keep').read_text(), 'untouched')
                    self.assertFalse(tomb.exists())
                    self.assertTrue(self.registry_row().get('cleaned'))

    def test_cleanup_refuses_unowned_or_foreign_work_tombstone(self):
        for key in ('tmp', 'run'):
            for when in ('before-staging', 'after-staging'):
                with self.subTest(key=key, when=when):
                    self.prepare()
                    if when == 'before-staging':
                        item = json.loads((Path(self.store.path) / 'work.json').read_text())[key]
                        tomb = Path(A.Store._work_tomb(item, self.state_json()['prepared']['identity']))
                    else:
                        source, tomb = self.interrupted_work_cleanup(key, 'rename')
                        original = tomb.with_name(tomb.name + '.original')
                        tomb.rename(original)
                        source.mkdir(mode=0o700)
                        (source / 'replacement').write_text('someone else')
                    tomb.mkdir(mode=0o700)
                    (tomb / 'foreign').write_text('not qargi')
                    out = self.cmd('local', 'clean', self.run, '--discard', ok=False)
                    self.assertIn('unowned work cleanup tombstone' if when == 'before-staging'
                                  else 'tombstone ownership mismatch', out)
                    self.assertEqual((tomb / 'foreign').read_text(), 'not qargi')
                    if when == 'after-staging':
                        self.assertEqual((source / 'replacement').read_text(), 'someone else')
                        self.assertTrue(original.is_dir())

    def test_missing_run_cleanup_requires_prepared_tmp_ownership(self):
        for ownership in ('known', 'missing', 'replaced', 'registry-decoy'):
            with self.subTest(ownership=ownership):
                self.prepare()
                tmp = Path((self.run / 'tmpdir').read_text().strip())
                (tmp / 'keep').write_text('diagnostic')
                if ownership == 'missing':
                    (Path(self.store.path) / 'work.json').unlink()
                elif ownership == 'replaced':
                    tmp.rename(tmp.with_name(tmp.name + '.kept'))
                    tmp.mkdir(mode=0o700)
                    (tmp / 'keep').write_text('replacement')
                elif ownership == 'registry-decoy':
                    registry = self.state / 'local-runs.jsonl'
                    rows = [json.loads(line) for line in registry.read_text().splitlines()]
                    decoy = self.root / 'qargi-run.Decoy2'
                    decoy.mkdir(mode=0o700)
                    (decoy / 'keep').write_text('another run')
                    rows[-1]['tmpdir'] = str(decoy)
                    registry.write_text(''.join(json.dumps(row) + '\n' for row in rows))
                shutil.rmtree(self.run)
                self.cmd('local', 'clean', self.run, '--discard', ok=ownership == 'known')
                if ownership == 'known':
                    self.assertFalse(tmp.exists())
                else:
                    self.assertTrue((tmp / 'keep').exists())
                    self.assertTrue(self.record.exists())
                if ownership == 'registry-decoy':
                    self.assertEqual((decoy / 'keep').read_text(), 'another run')

    def test_clean_refuses_replaced_run_before_removing_tmp(self):
        self.prepare()
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        (tmp / 'keep').write_text('diagnostic')
        saved = self.run.with_name(self.run.name + '.kept')
        self.run.rename(saved)
        shutil.copytree(saved, self.run)
        before = self.bytes_tree(self.run)
        self.assertIn('ownership mismatch', self.cmd('local', 'clean', self.run, '--discard', ok=False))
        self.assertEqual(before, self.bytes_tree(self.run))
        self.assertEqual((tmp / 'keep').read_text(), 'diagnostic')

    def test_clean_internal_tmp_and_legacy_ownership_refusal(self):
        self.env['QARGI_RUN_TMP'] = str(self.root / 'unavailable')
        self.prepare()
        tmp = Path((self.run / 'tmpdir').read_text().strip())
        self.assertEqual(tmp, self.run / 'tmp')
        (tmp / 'keep').write_text('diagnostic')
        registry = self.state / 'local-runs.jsonl'
        original = registry.read_text()
        row = json.loads(original)
        del row['lifecycle']
        registry.write_text(json.dumps(row) + '\n')
        self.assertIn('ownership unavailable', self.cmd('local', 'clean', self.run, '--discard', ok=False))
        self.assertEqual((tmp / 'keep').read_text(), 'diagnostic')
        registry.write_text(original)
        self.cmd('local', 'clean', self.run, '--discard')
        self.assertFalse(self.run.exists())

    def test_retry_epoch_precedes_slow_remote_snapshot(self):
        remote = self.root / "remote.git"
        self.git("init", "--bare", "-q", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.prepare()
        self.verify()
        probe = self.root / "remote-probe"
        real_git = shutil.which("git")
        shim = self.bin / "git"
        shim.write_text(f"#!{sys.executable}\nimport os, sys, time\nfrom pathlib import Path\n"
                        "if 'ls-remote' in sys.argv:\n"
                        "    epoch = int(time.time())\n"
                        f"    Path({str(probe)!r}).write_text(str(epoch))\n"
                        "    while int(time.time()) == epoch: time.sleep(.02)\n"
                        f"os.execv({real_git!r}, [{real_git!r}] + sys.argv[1:])\n")
        shim.chmod(0o755)
        self.dispatch()
        self.assertLessEqual(self.state_json()["attempts"][-1]["epoch"], int(probe.read_text()))

    def test_report_manifests_use_private_prepared_base(self):
        for command in (("review", "save"), ("local", "report")):
            with self.subTest(command=command):
                self.prepare("review")
                (self.run / "refs.before").write_text("local refs/heads/develop " + "f" * 40 + "\n")
                self.cmd(*command, self.run, input="# Findings\nNo findings.\n")
                manifest = json.loads((self.run / "out/manifest.json").read_text())
                self.assertEqual(manifest["base"]["sha"], self.sha)

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
