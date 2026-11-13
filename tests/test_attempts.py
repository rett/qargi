#!/usr/bin/env python3
"""Offline lifecycle primitives: private state, crash commits and actual fd proof."""
import hermetic  # noqa: F401
import contextlib
import copy
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import attempts as A


class Attempts(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.state = self.root / "state"
        self.run = self.root / "qargi.Abc123"
        self.run.mkdir()
        self.env = mock.patch.dict(os.environ, QARGI_STATE=str(self.state),
                                   QARGI_CONF=str(self.root / "conf"), DA_NOSETUP="1")
        self.env.start()
        self.addCleanup(self.env.stop)
        self.store = A.Store(self.run)
        self.record = Path(self.store.path) / "state.json"

    @contextlib.contextmanager
    def locked(self, store=None):
        store = store or self.store
        try:
            saved_fd = os.dup(7)
        except OSError:
            saved_fd = None
        fd = store.open_lock()
        if fd != 7:
            os.dup2(fd, 7)
            os.close(fd)
        fcntl.flock(7, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            os.close(7)
            if saved_fd is not None:
                os.dup2(saved_fd, 7)
                os.close(saved_fd)

    def write(self, path, data):
        path = Path(path)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o600)

    def register(self, **extra):
        row = dict(run=str(self.run), lifecycle=1)
        row.update(extra)
        self.write(self.state / "local-runs.jsonl", A.encode(row))

    def prepare(self):
        record = self.store.init(b"lead refs\n", epoch=10, base="feature/example", base_sha="a" * 40)
        self.register()
        return record

    def saved(self, n):
        (self.state / "runs").mkdir(mode=0o700, exist_ok=True)
        path = self.state / "runs" / self.store.id
        if self.record.exists() and (self.state / "local-runs.jsonl").exists():
            marker = self.store.prepare_save().encode()
            if n != self.store.show()["current"]:
                parts = marker.split()
                marker = b" ".join((parts[0], str(n).encode(), parts[2])) + b"\n"
        else:
            marker = b"0" * 32 + b" " + str(n).encode() + b" " + b"0" * 32 + b"\n"
        self.write(path / "attempt", marker)
        self.write(path / "output", b"kept output\n")
        return path

    def shell(self, code, *args, pass_fds=()):
        return subprocess.run(["bash", "-c", 'source "$1/lib/lib.sh"; shift; ' + code,
                               "test", str(ROOT), *map(str, args)],
                              capture_output=True, text=True, timeout=15, pass_fds=pass_fds)

    def test_paths_are_standard_and_import_does_not_create_state(self):
        self.assertEqual(self.store.root, str(self.state))
        self.assertFalse(self.state.exists())
        with mock.patch.dict(os.environ, QARGI_STATE="", QARGI_HOME=str(self.root / "home")):
            self.assertEqual(A.Store(self.run).root, str(self.root / "home/state"))
        self.assertFalse(self.state.exists())

    def test_historical_directory_rejects_links_foreign_owner_and_files(self):
        target = self.root / "historical"
        target.mkdir(mode=0o755)
        target.chmod(0o755)
        with mock.patch.object(A.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaisesRegex(A.Refuse, "lead-owned"):
                A.directory(str(target), tighten=True)
        self.assertEqual(target.stat().st_mode & 0o777, 0o755)
        link = self.root / "link"
        link.symlink_to(target)
        with self.assertRaises(A.Refuse):
            A.directory(str(link), tighten=True)
        target.rmdir()
        target.write_text("plain file")
        with self.assertRaises(OSError):
            A.directory(str(target), tighten=True)

    def test_zombie_only_group_is_terminated(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        try:
            # waitid observes exit but deliberately leaves the child unreaped.
            os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
            self.assertFalse(A.group_alive(child.pid))
        finally:
            child.wait(timeout=5)

    def test_history_limit_creates_no_snapshot(self):
        with self.locked():
            self.prepare()
            self.write(self.saved(1) / "output", b"C1")
            self.store.verified(b"R1")
            before = {p.name: p.read_bytes() for p in Path(self.store.path).iterdir() if p.is_file()}
            with mock.patch.object(A, "MAX_VERIFICATIONS", 0):
                with self.assertRaisesRegex(A.Refuse, "history limit"):
                    self.store.verified(b"R2")
                self.store.verified(b"R1")
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(self.store.path).iterdir() if p.is_file()})

    def test_unowned_or_replaced_save_staging_refuses_deletion(self):
        with self.locked():
            self.prepare()
            stage = Path(self.store.path) / "save.stage"
            stage.mkdir(mode=0o700)
            with self.assertRaisesRegex(A.Refuse, "unowned save staging"):
                self.store.reconcile()
            self.assertTrue(stage.exists())
            stage.rmdir()
            self.store.stage_product()
            stage.rename(stage.with_name("kept-stage"))
            stage.mkdir(mode=0o700)
            with self.assertRaisesRegex(A.Refuse, "ownership mismatch"):
                self.store.recover_stage()
            self.assertTrue(stage.exists())

    def test_cleanup_refuses_unowned_or_replaced_tombstones(self):
        with self.locked():
            self.prepare()
            tomb = Path(self.store.path + ".clean")
            tomb.mkdir(mode=0o700)
            with self.assertRaisesRegex(A.Refuse, "unowned cleanup"):
                self.store.clean_begin(discard=True)
            self.assertTrue(tomb.exists())
            tomb.rmdir()
            self.store.clean_begin(discard=True)
            self.store.clean_stage()
            tomb.rename(tomb.with_name("kept-tombstone"))
            tomb.mkdir(mode=0o700)
            self.register(cleaned="2026-01-01T00:00:00Z")
            with self.assertRaisesRegex(A.Refuse, "ownership mismatch"):
                self.store.clean_finish()
            self.assertTrue(tomb.exists())

    def test_init_and_retry_preserve_prepared_authority(self):
        with self.locked():
            initial = self.prepare()
            self.assertEqual(self.store.show(), initial)
            self.assertEqual(self.store.gate()["phase"], "strict")
            self.saved(1)
            self.store.verified(b"verified refs\n")
            self.assertEqual(self.store.gate()["phase"], "after-verify")
            self.assertEqual(self.store.gate()["sha256"], A.digest(b"verified refs\n"))
            self.assertEqual(self.store.saved_copy(), str(self.state / "runs" / self.store.id))
            pending = self.store.gate_pending(b"gate refs\n", epoch=20)
            result = self.store.begin(pending, b"gate refs\n")
            self.assertEqual(result["current"], 2)
            self.assertEqual(result["prepared"], initial["prepared"])
            self.assertEqual(result["attempts"][-1]["gate"], "strict")
            self.assertIsNone(result["attempts"][-1]["verified"])
            self.assertEqual(result["attempts"][0]["saved"], ["a1.saved.1"])
            self.assertEqual((Path(self.store.path) / "a1.saved.1/output").read_bytes(), b"kept output\n")
            with self.assertRaises(A.Refuse):
                self.store.saved_copy()
            self.store.end("not-started")
            self.assertEqual(self.store.gate()["phase"], "strict")
            self.saved(2)
            self.store.verified(b"second verified refs")
            self.assertEqual(self.store.show()["current"], 2)
            for path in Path(self.store.path).iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700 if path.is_dir() else 0o600)
            (Path(self.store.path) / "a1.saved.1/attempt").unlink()
            with self.assertRaises(FileNotFoundError):
                self.store.show()

    def test_first_dispatch_attaches_and_plan_is_state_and_owner_bound(self):
        with self.locked():
            self.prepare()
            pending = self.store.gate_pending(b"accepted", epoch=20)
            for field, value in (("owner", {"pid": os.getpid(), "token": "0"}),
                                 ("state_sha256", "0" * 64), ("refs_sha256", "0" * 64)):
                bad = copy.deepcopy(pending)
                bad[field] = value
                with self.subTest(field=field), self.assertRaises(A.Refuse):
                    self.store.begin(bad, b"accepted")
            before = self.record.read_bytes()
            with self.assertRaises(A.Refuse):
                self.store.begin(pending, b"changed")
            self.assertEqual(self.record.read_bytes(), before)
            self.assertEqual(self.store.begin(pending, b"accepted")["current"], 1)
            with self.assertRaises(A.Refuse):
                self.store.begin(pending, b"accepted")
            self.store.end("not-started")
            next_plan = self.store.gate_pending(b"retry", epoch=30)
            self.assertEqual(self.store.begin(next_plan, b"retry")["current"], 2)

    def test_registry_marker_alone_decides_legacy_or_missing_authority(self):
        with self.locked():
            self.prepare()
            row = {"run": str(self.run)}
            self.write(self.state / "local-runs.jsonl", A.encode(row))
            with self.assertRaises(A.Legacy):
                self.store.show()
            for marker in (True, 2, None, "1"):
                self.register(lifecycle=marker)
                with self.subTest(marker=marker), self.assertRaises(A.Refuse):
                    self.store.show()
            self.register()
            self.record.unlink()
            with self.assertRaises(FileNotFoundError):
                self.store.show()
            self.write(self.run / "verified", b"forged")
            self.write(self.run / "refs.before", b"forged")
            self.saved(1)
            with self.assertRaises(FileNotFoundError):
                self.store.show()

    def test_schema_paths_hashes_and_bounds_fail_closed(self):
        with self.locked():
            original = self.prepare()
            variants = []
            for key, val in (("schema", 2), ("schema", True), ("current", 0), ("current", True), ("run", "/other/qargi.Abc123")):
                v = copy.deepcopy(original)
                v[key] = val
                variants.append(v)
            for key, val in (("base_sha", "bad"), ("epoch", -1), ("refs", "../outside"), ("refs_sha256", "0" * 64)):
                v = copy.deepcopy(original)
                v["prepared"][key] = val
                variants.append(v)
            for key in original:
                v = copy.deepcopy(original)
                del v[key]
                variants.append(v)
            v = copy.deepcopy(original)
            v["attempts"][0]["saved"] = "../../outside"
            variants.append(v)
            v = copy.deepcopy(original)
            v["attempts"] *= A.MAX_ATTEMPTS + 1
            v["current"] = A.MAX_ATTEMPTS + 1
            variants.append(v)
            for v in variants:
                self.write(self.record, A.encode(v))
                with self.subTest(record=v), self.assertRaises(A.Refuse):
                    self.store.show()
            for raw in (b'{"schema":1,"schema":1}', b"[" * 2000,
                        b" " * (A.MAX_RECORD + 1), b'{"schema":NaN}'):
                self.write(self.record, raw)
                with self.subTest(raw=raw[:30]), self.assertRaises(A.Refuse):
                    self.store.show()
            self.write(self.record, A.encode(original))
            self.write(Path(self.store.path) / "prepared.refs", b"forged")
            with self.assertRaisesRegex(A.Refuse, "hash mismatch"):
                self.store.show()
            self.write(Path(self.store.path) / "prepared.refs", b"x" * (A.MAX_REFS + 1))
            with self.assertRaisesRegex(A.Refuse, "bounded"):
                self.store.show()

    def test_wrong_ids_noncanonical_and_symlink_paths_are_refused(self):
        for run in ("relative/qargi.Abc123", str(self.root / "qargi.12345"),
                    str(self.root / "qargi.abc/../qargi.Abc123"), str(self.root / "qargi.ab$cde")):
            with self.subTest(run=run), self.assertRaises(A.Refuse):
                A.Store(run)
        with self.locked():
            self.prepare()
            outside = self.root / "outside"
            self.write(outside, b"unchanged")
            self.record.unlink()
            self.record.symlink_to(outside)
            with self.assertRaises(OSError):
                self.store.show()
            self.assertEqual(outside.read_bytes(), b"unchanged")
        self.state.rename(self.root / "actual-state")
        self.state.symlink_to(self.root / "actual-state")
        with self.assertRaises(A.Refuse):
            A.Store(self.run)

    def test_private_modes_and_hardlinks_are_required(self):
        with self.locked():
            self.prepare()
            for path, mode in ((self.record, 0o644), (Path(self.store.path), 0o755)):
                old = stat.S_IMODE(path.stat().st_mode)
                path.chmod(mode)
                with self.assertRaises(A.Refuse):
                    self.store.show()
                path.chmod(old)
            os.link(self.record, self.root / "linked")
            with self.assertRaises(A.Refuse):
                self.store.show()

    def test_lock_symlinks_and_fifos_cannot_redirect_or_block_shell(self):
        fd = self.store.open_lock()
        os.close(fd)
        lock = Path(self.store.lock_path)
        outside = self.root / "outside-lock"
        self.write(outside, b"keep")
        lock.unlink()
        lock.symlink_to(outside)
        r = self.shell('lc_lock "$1"', self.run)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(outside.read_bytes(), b"keep")
        lock.unlink()
        os.mkfifo(lock, 0o600)
        r = self.shell('lc_lock "$1"', self.run)
        self.assertNotEqual(r.returncode, 0)

    def test_init_collision_and_atomic_rename_failure_keep_prior_state(self):
        with self.locked():
            self.prepare()
            before = self.record.read_bytes()
            (self.state / "local-runs.jsonl").unlink()
            with self.assertRaises(FileExistsError):
                self.store.init(b"other", epoch=20, base="main", base_sha="b" * 40)
            self.assertEqual(self.record.read_bytes(), before)
            self.register()
            self.saved(1)
            before = self.record.read_bytes()
            with mock.patch.object(A.os, "replace", side_effect=OSError("rename failed")):
                with self.assertRaises(OSError):
                    self.store.verified(b"new snapshot")
            self.assertEqual(self.record.read_bytes(), before)
            self.assertEqual(list(Path(self.store.path).glob(".write.*")), [])

    def test_initial_atomic_failure_cleans_state_directory(self):
        with self.locked():
            with mock.patch.object(A.os, "replace", side_effect=OSError("rename failed")):
                with self.assertRaises(OSError):
                    self.store.init(b"refs", epoch=10, base="main", base_sha="a" * 40)
            self.assertFalse(Path(self.store.path).exists())
            self.prepare()

    def test_reconcile_is_idempotent_when_unchanged(self):
        with self.locked():
            self.prepare()
            first = self.store.reconcile()
            before = self.record.read_bytes()
            self.assertEqual(self.store.reconcile(), first)
            self.assertEqual(self.record.read_bytes(), before)

    def test_broken_stderr_does_not_undo_committed_replacement(self):
        with self.locked():
            self.prepare()
            pending = self.store.gate_pending(b"gate", epoch=20)
            fsync = A.os.fsync
            def fail_directory(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("directory fsync")
                fsync(fd)
            err = mock.Mock()
            err.write.side_effect = BrokenPipeError("closed")
            with mock.patch.object(A.os, "fsync", side_effect=fail_directory), mock.patch("sys.stderr", err):
                self.store.begin(pending, b"gate")
            self.assertIsNotNone(self.store.show()["attempts"][0]["dispatch"])

    def test_saved_marker_links_wrong_numbers_and_new_schema_gaps_refuse(self):
        with self.locked():
            self.prepare()
            saved = self.saved(2)
            with self.assertRaises(A.Refuse):
                self.store.verified(b"refs")
            with self.assertRaises(A.Refuse):
                self.store.reconcile()
            record = self.store.show()
            self.write(saved / "attempt", A.Store._marker(record, 1, record["attempts"][0]["save_nonce"]))
            outside = self.root / "outside-marker"
            self.write(outside, b"1\n")
            (saved / "attempt").unlink()
            (saved / "attempt").symlink_to(outside)
            with self.assertRaises(OSError):
                self.store.verified(b"refs")
            (saved / "attempt").unlink()
            self.write(saved / "attempt", A.Store._marker(record, 1, record["attempts"][0]["save_nonce"]))
            self.store.begin(self.store.gate_pending(b"accepted", epoch=20), b"accepted")
            record = self.store.show()
            for key in record["attempts"][0]["dispatch"]:
                v = copy.deepcopy(record)
                del v["attempts"][0]["dispatch"][key]
                self.write(self.record, A.encode(v))
                with self.subTest(key=key), self.assertRaises(A.Refuse):
                    self.store.show()
            self.write(self.record, A.encode(record))

    def test_missing_and_ambiguous_registry_and_closed_refuse(self):
        with self.locked():
            self.prepare()
            for raw in (b"invalid qargi.Abc123\n", b" " * (A.MAX_REGISTRY + 1),
                        A.encode(dict(run="/other/qargi.Abc123", lifecycle=1))):
                self.write(self.state / "local-runs.jsonl", raw)
                with self.assertRaises(A.Refuse):
                    self.store.show()
            for key in ("closed", "cleaned"):
                self.register(**{key: "2026-01-01T00:00:00Z"})
                with self.assertRaises(A.Refuse):
                    self.store.gate_pending(b"refs", epoch=20)

    def test_failure_before_commit_leaves_no_new_authority(self):
        with self.locked():
            self.prepare()
            self.store.begin(self.store.gate_pending(b"first", epoch=20), b"first")
            self.store.end("not-started")
            pending = self.store.gate_pending(b"gate", epoch=21)
            before = self.record.read_bytes()
            atomic = A.atomic
            def fail_record(fd, name, data):
                if name == "state.json":
                    raise OSError("record write failed")
                atomic(fd, name, data)
            with mock.patch.object(A, "atomic", side_effect=fail_record):
                with self.assertRaises(OSError):
                    self.store.begin(pending, b"gate")
            self.assertEqual(self.record.read_bytes(), before)
            result = self.store.begin(self.store.gate_pending(b"different", epoch=22), b"different")
            self.assertEqual(result["current"], 2)

    def test_interrupted_begin_and_retain_reconcile_without_overwrite(self):
        with self.locked():
            self.prepare()
            self.saved(1)
            with mock.patch.object(self.store, "_commit", side_effect=OSError("verify failed")):
                with self.assertRaises(OSError):
                    self.store.verified(b"verified")
            pending = self.store.gate_pending(b"gate", epoch=20)
            with mock.patch.object(self.store, "_retain", side_effect=OSError("preflight")):
                with self.assertRaises(OSError):
                    self.store.begin(pending, b"gate")
            self.assertIsNone(self.store.show()["attempts"][0]["dispatch"])
            with mock.patch.object(self.store, "_commit", side_effect=OSError("after rename")):
                with self.assertRaises(OSError):
                    self.store.reconcile()
            result = self.store.reconcile()
            self.assertEqual(result["attempts"][0]["saved"], ["a1.saved.1"])
            self.saved(1)
            self.store.verified(b"verified")
            self.store.verified(b"verified again")
            result = self.store.begin(self.store.gate_pending(b"gate", epoch=20), b"gate")
            self.assertEqual(result["attempts"][0]["saved"], ["a1.saved.1", "a1.saved.2"])
            self.assertEqual(result["attempts"][0]["history"][0]["sha256"], A.digest(b"verified"))
            for name in result["attempts"][0]["saved"]:
                self.assertEqual((Path(self.store.path) / name / "output").read_bytes(), b"kept output\n")

    def test_leftover_marker_and_missing_registry_refused(self):
        with self.locked():
            path = self.state / "runs" / self.store.id
            self.write(path / "attempt", b"1\n")
            with self.assertRaises(A.Refuse):
                self.store.init(b"x", epoch=1, base="main", base_sha="a" * 40)
            shutil.rmtree(path)
            self.prepare()
            (self.state / "local-runs.jsonl").unlink()
            with self.assertRaisesRegex(A.Refuse, "registry file is missing"):
                self.store.drop()

    def test_fsync_after_replace_is_committed(self):
        with self.locked():
            self.prepare()
            pending = self.store.gate_pending(b"gate", epoch=20)
            fsync = A.os.fsync
            def fail_directory(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("directory fsync")
                fsync(fd)
            with mock.patch.object(A.os, "fsync", side_effect=fail_directory), mock.patch("sys.stderr", new_callable=__import__("io").StringIO) as err:
                self.store.begin(pending, b"gate")
            self.assertIn("warning:", err.getvalue())
            self.assertIsNotNone(self.store.show()["attempts"][0]["dispatch"])
            self.store.end("not-started")

    def test_registry_historical_lock_and_unsafe_kinds(self):
        with self.locked():
            lock = self.state / "local-runs.jsonl.lock"
            lock.write_bytes(b"")
            lock.chmod(0o644)
            inode = lock.stat().st_ino
            self.prepare()
            self.assertEqual((lock.stat().st_ino, stat.S_IMODE(lock.stat().st_mode)), (inode, 0o600))
            os.link(lock, self.root / "hardlink")
            with self.assertRaises(A.Refuse):
                self.store.show()
            (self.root / "hardlink").unlink()
            with mock.patch.object(A.os, "geteuid", return_value=lock.stat().st_uid + 1):
                with self.assertRaises(A.Refuse):
                    self.store.registry()
            lock.unlink()
            lock.symlink_to(self.root / "hardlink")
            with self.assertRaises(OSError):
                self.store.registry()
            lock.unlink()
            os.mkfifo(lock)
            with self.assertRaises(A.Refuse):
                self.store.registry()

    def test_save_nonce_rejects_failed_replacement_and_wrong_markers(self):
        with self.locked():
            self.prepare()
            first = self.saved(1)
            self.write(first / "output", b"C1")
            self.store.verified(b"R1")
            marker = self.store.prepare_save()
            self.assertEqual((Path(self.store.path) / "a1.saved.1/output").read_bytes(), b"C1")
            self.write(first / "attempt", marker.encode())
            self.write(first / "output", b"C2")
            with mock.patch.object(self.store, "_commit", side_effect=OSError("verification failed")):
                with self.assertRaises(OSError):
                    self.store.verified(b"R2")
            with self.assertRaises(A.Refuse):
                self.store.saved_copy()
            parts = marker.split()
            for identity, nonce in (("f" * 32, parts[2]), (parts[0], "f" * 32)):
                self.write(first / "attempt", (identity + " 1 " + nonce + "\n").encode())
                with self.assertRaises(A.Refuse):
                    self.store.verified(b"R2")
                with self.assertRaises(A.Refuse):
                    self.store.saved_copy()
            self.write(first / "attempt", marker.encode())
            with mock.patch.object(A, "MAX_VERIFICATIONS", 0):
                with self.assertRaises(A.Refuse):
                    self.store.verified(b"R2")
            with self.assertRaises(A.Refuse):
                self.store.saved_copy()

    def test_failed_reverification_retains_c2_then_accepts_new_generation(self):
        with self.locked():
            self.prepare()
            current = self.saved(1)
            self.write(current / "output", b"C1")
            self.store.verified(b"R1")
            marker = self.store.prepare_save()
            self.write(current / "attempt", marker.encode())
            self.write(current / "output", b"C2")
            with mock.patch.object(self.store, "_commit", side_effect=OSError("failed")):
                with self.assertRaises(OSError):
                    self.store.verified(b"R2")
            state = self.store.reconcile()
            self.assertEqual(state["attempts"][0]["verified"]["sha256"], A.digest(b"R1"))
            self.assertEqual((Path(self.store.path) / "a1.saved.1/output").read_bytes(), b"C1")
            self.assertEqual((Path(self.store.path) / "a1.saved.2/output").read_bytes(), b"C2")
            with self.assertRaises((A.Refuse, FileNotFoundError)):
                self.store.saved_copy()
            marker = self.store.prepare_save()
            self.write(current / "attempt", marker.encode())
            self.write(current / "output", b"C2")
            self.store.verified(b"R2")
            self.assertEqual(Path(self.store.saved_copy()).joinpath("output").read_bytes(), b"C2")

    def test_malformed_superseded_and_surrogate_refuse(self):
        with self.locked():
            record = self.prepare()
            bad = copy.deepcopy(record)
            bad["prepared"]["base"] = "\ud800"
            self.write(self.record, A.encode(bad))
            with self.assertRaisesRegex(A.Refuse, "invalid prepared base"):
                self.store.show()
            bad = copy.deepcopy(record)
            bad["attempts"][0]["superseded_at"] = bad["prepared"]["at"]
            second = copy.deepcopy(bad["attempts"][0])
            second.update(n=2, superseded_at=None, baseline="a2.base." + second["baseline_sha256"] + ".refs")
            self.write(Path(self.store.path) / second["baseline"], b"lead refs\n")
            bad["attempts"].append(second)
            bad["current"] = 2
            self.write(self.record, A.encode(bad))
            with self.assertRaisesRegex(A.Refuse, "invalid superseded"):
                self.store.show()

    def test_begin_reserves_dispatch_headroom(self):
        with self.locked():
            self.prepare()
            pending = self.store.gate_pending(b"gate", epoch=20)
            before = self.record.read_bytes()
            with mock.patch.object(A, "MAX_RECORD", len(before) + 500):
                with self.assertRaisesRegex(A.Refuse, "headroom"):
                    self.store.begin(pending, b"gate")
            self.assertEqual(self.record.read_bytes(), before)

    def test_retention_and_drop_fsync_warnings_leave_recoverable_state(self):
        with self.locked():
            self.prepare()
            self.saved(1)
            fsync = A.os.fsync
            def fail_directory(fd):
                if stat.S_ISDIR(os.fstat(fd).st_mode):
                    raise OSError("directory fsync")
                fsync(fd)
            with mock.patch.object(A.os, "fsync", side_effect=fail_directory), mock.patch("sys.stderr", new_callable=__import__("io").StringIO) as err:
                result = self.store.reconcile()
                self.assertEqual(result["attempts"][0]["saved"], ["a1.saved.1"])
                self.register(cleaned="2026-01-01T00:00:00Z")
                self.store.drop()
                self.store.drop()
            self.assertIn("retention rename committed", err.getvalue())
            self.assertIn("cleanup committed", err.getvalue())
            self.assertFalse(Path(self.store.path).exists())

    def test_base_names_timestamps_and_registry_snapshot(self):
        with self.locked():
            record = self.store.init(b"x", epoch=1, base="réf+@,=#%", base_sha="a" * 40)
            self.register()
            self.assertEqual(self.store.show()["prepared"]["base"], "réf+@,=#%")
            bad = copy.deepcopy(record)
            bad["prepared"]["at"] = "٢٠٢٦-01-01T00:00:00Z"
            self.write(self.record, A.encode(bad))
            with self.assertRaises(A.Refuse):
                self.store.show()
            self.write(self.record, A.encode(record))
            registry = self.state / "local-runs.jsonl"
            with registry.open("ab") as stream:
                stream.write(b"unrelated malformed\n\n")
            self.assertEqual(self.store.show(), record)
            lock = os.open(str(registry) + ".lock", os.O_RDWR)
            try:
                fcntl.flock(lock, fcntl.LOCK_EX)
                proc = subprocess.Popen([sys.executable, "-c", 'import sys; sys.path.insert(0, sys.argv[1]); import attempts; attempts.Store(sys.argv[2]).registry()', str(ROOT / "lib"), str(self.run)], env=os.environ.copy())
                try:
                    with self.assertRaises(subprocess.TimeoutExpired):
                        proc.wait(timeout=0.2)
                    fcntl.flock(lock, fcntl.LOCK_UN)
                    self.assertEqual(proc.wait(timeout=10), 0)
                finally:
                    if proc.poll() is None:
                        proc.kill()
                        proc.wait()
            finally:
                os.close(lock)

    def test_reg_del_reloads_and_preserves_unrelated_lines(self):
        with self.locked():
            self.prepare()
            self.register(verified="old")
        registry = self.state / "local-runs.jsonl"
        with registry.open("ab") as stream:
            stream.write(b"{ \"run\": \"/other/qargi.Zzz999\", \"x\": 1 }\nmalformed\n")
        r = self.shell('reg_load; reg_del "$1" verified || exit 1; [ -z "$(reg_get "$1" verified)" ]', self.run)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(registry.read_bytes().endswith(b'{ "run": "/other/qargi.Zzz999", "x": 1 }\nmalformed\n'))

    def test_lock_other_run_does_not_release_original(self):
        other = self.root / "qargi.Def456"
        code = 'lc_lock "$1" || exit 1; lc_lock "$2" && exit 2; lc_lock "$1"'
        r = self.shell(code, self.run, other)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("wrong lifecycle", r.stderr)

    def test_verify_failure_and_unknown_saved_copy_never_grant_authority(self):
        with self.locked():
            self.prepare()
            self.saved(1)
            with mock.patch.object(self.store, "_commit", side_effect=OSError("failed verify")):
                with self.assertRaises(OSError):
                    self.store.verified(b"verified")
            self.assertIsNone(self.store.show()["attempts"][0]["verified"])
            with self.assertRaises(A.Refuse):
                self.store.saved_copy()
            self.store.reconcile()
            self.assertTrue((Path(self.store.path) / "a1.saved.1").is_dir())
            saved = self.saved(1)
            (saved / "attempt").unlink()
            with self.assertRaises(A.Refuse):
                self.store.reconcile()

    def test_fd_must_be_right_inode_exclusively_held_not_env_or_independent_open(self):
        with self.locked():
            self.prepare()
            self.store.require_lock()
            r = self.shell('lc_lock "$1"', self.run)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("busy", r.stderr)
            self.assertEqual(self.shell('lc_lock "$1"', self.run, pass_fds=(7,)).returncode, 0)
            r = self.shell('exec 7>>"$2"; python3 -I "$QARGI_TOOL/lib/attempts.py" lock-check "$1"',
                           self.run, self.store.lock_path)
            self.assertNotEqual(r.returncode, 0)
            other = self.root / "qargi.Def456"
            with self.assertRaisesRegex(A.Refuse, "wrong lifecycle"):
                A.Store(other).require_lock()
        fd = self.store.open_lock()
        try:
            os.dup2(fd, 7)
            with mock.patch.dict(os.environ, QARGI_LC_LOCKED="yes"):
                with self.assertRaisesRegex(A.Refuse, "does not hold"):
                    self.store.require_lock()
            fcntl.flock(7, fcntl.LOCK_SH | fcntl.LOCK_NB)
            with self.assertRaises(A.Refuse):
                self.store.require_lock()
        finally:
            if fd != 7:
                os.close(fd)
            os.close(7)

    def test_shell_opens_lock_and_nested_exec_keeps_actual_description(self):
        r = self.shell('lc_lock "$1" && exec bash -c \'source "$1/lib/lib.sh"; lc_lock "$2"\' nested "$QARGI_TOOL" "$1"', self.run)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(stat.S_IMODE(Path(self.store.lock_path).stat().st_mode), 0o600)

    def test_pending_shell_owner_survives_exec_into_runner(self):
        with self.locked():
            self.prepare()
        runner = self.root / "runner.py"
        runner.write_text('import json, sys\nsys.path.insert(0, sys.argv[1])\n'
                          'import attempts as A\ns = A.Store(sys.argv[2])\n'
                          's.begin(json.loads(sys.argv[3]), b"accepted")\ns.end("not-started")\n')
        code = ('lc_lock "$1" || exit 1; '
                'pending=$(printf \'{"refs":"accepted","epoch":20,"owner_pid":%s}\' "$$" | '
                'python3 -I "$QARGI_TOOL/lib/attempts.py" gate-pending "$1") || exit 1; '
                'exec python3 -I "$2" "$QARGI_TOOL/lib" "$1" "$pending"')
        r = self.shell(code, self.run, runner)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.store.show()["attempts"][0]["dispatch"]["outcome"], "not-started")

    def test_dispatcher_local_and_review_exec_preserve_fd(self):
        # Use the real dispatcher with fake preamble/leaf processes. No provider,
        # model, git repository, networking or user config participates.
        tool = self.root / "tool"
        (tool / "bin").mkdir(parents=True)
        (tool / "lib").mkdir()
        shutil.copyfile(ROOT / "bin/qargi", tool / "bin/qargi")
        (tool / "bin/qargi").chmod(0o755)
        (tool / "lib/help.py").write_text(
            'import sys\ndef main(args):\n'
            ' sys.stdout.buffer.write(b"\\0\\0\\0" + b"\\0".join(x.encode() for x in args[1:]) + b"\\0")\n')
        for area in ("local", "review"):
            leaf = tool / "lib" / (area + ".sh")
            leaf.write_text('#!/bin/bash\nsource "$TEST_LIB/lib.sh"\nlc_lock "$TEST_RUN" || exit 1\n'
                            'exec python3 -I "$TEST_LIB/attempts.py" lock-check "$TEST_RUN"\n')
            leaf.chmod(0o755)
        with self.locked(), mock.patch.dict(os.environ, TEST_LIB=str(ROOT / "lib"), TEST_RUN=str(self.run)):
            for area, verb in (("local", "test"), ("review", "check")):
                r = subprocess.run([str(tool / "bin/qargi"), area, verb], pass_fds=(7,),
                                   capture_output=True, text=True, timeout=15)
                self.assertEqual(r.returncode, 0, r.stderr)

    def test_member_close_fds_busy_refusal_and_end(self):
        with self.locked():
            self.prepare()
            self.store.begin(self.store.gate_pending(b"gate", epoch=20), b"gate")
            code = '''import json, os, subprocess, sys
lock = os.stat(sys.argv[1])
leaked = []
for name in os.listdir('/proc/self/fd'):
 try:
  st = os.fstat(int(name))
  if (st.st_dev, st.st_ino) == (lock.st_dev, lock.st_ino): leaked.append(name)
 except OSError: pass
r = subprocess.run(['bash', '-c', 'source "$1/lib/lib.sh"; lc_lock "$2"', 'member', sys.argv[2], sys.argv[3]], capture_output=True, text=True)
print(json.dumps([leaked, r.returncode, r.stderr]), flush=True)
sys.stdin.read(1)
'''
            child = subprocess.Popen([sys.executable, "-c", code, self.store.lock_path, str(ROOT), str(self.run)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     close_fds=True, start_new_session=True, text=True)
            try:
                # communicate boundedly: the fake exits on input; retain the group
                # long enough to prove member/end refusal before releasing it.
                self.store.member(child.pid)
                # Simulate loss/reuse of the runner identity while its real fake
                # member group remains alive. The group independently blocks.
                live = self.store.show()
                lost = copy.deepcopy(live)
                lost["attempts"][-1]["dispatch"]["runner"]["token"] = "0"
                self.write(self.record, A.encode(lost))
                with self.assertRaisesRegex(A.Refuse, "group is busy"):
                    self.store.reconcile()
                self.write(self.record, A.encode(live))
                with self.assertRaisesRegex(A.Refuse, "busy"):
                    self.store.end("ok")
                with self.assertRaises(A.Refuse):
                    self.store.verified(b"refs")
                out, err = child.communicate("x", timeout=15)
                leaked, rc, diagnostic = json.loads(out)
                self.assertEqual((child.returncode, leaked), (0, []), err)
                self.assertNotEqual(rc, 0)
                self.assertIn("busy", diagnostic)
                self.store.end("ok")
            finally:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=15)

    def test_reconcile_lost_runner_and_unknown_spawn_window(self):
        with self.locked():
            self.prepare()
            code = '''import os, subprocess, sys
sys.path.insert(0, sys.argv[1])
import attempts as A
s = A.Store(sys.argv[2])
s.begin(s.gate_pending(b'gate', epoch=20), b'gate')
if sys.argv[3] == 'member':
 p = subprocess.Popen([sys.executable, '-c', 'import sys; sys.stdin.read(1)'], stdin=subprocess.PIPE, close_fds=True, start_new_session=True)
 s.member(p.pid)
 print('ready', flush=True)
 sys.stdin.read(1)
 p.communicate(b'x', timeout=10)
'''
            runner = subprocess.Popen([sys.executable, "-c", code, str(ROOT / "lib"), str(self.run), "member"],
                                      stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      pass_fds=(7,), text=True)
            try:
                # Readiness is pipe based; timeout below bounds the fake runner.
                import select
                self.assertTrue(select.select([runner.stdout], [], [], 10)[0])
                self.assertEqual(runner.stdout.readline().strip(), "ready")
                with self.assertRaisesRegex(A.Refuse, "runner is busy"):
                    self.store.reconcile()
                out, err = runner.communicate("x", timeout=15)
                self.assertEqual(runner.returncode, 0, err + out)
            finally:
                if runner.poll() is None:
                    runner.kill()
                runner.communicate(timeout=15)
            result = self.store.reconcile()
            self.assertEqual(result["attempts"][-1]["dispatch"]["outcome"], "lost")
            runner = subprocess.run([sys.executable, "-c", code, str(ROOT / "lib"), str(self.run), "no-member"],
                                    pass_fds=(7,), capture_output=True, text=True, timeout=15)
            self.assertEqual(runner.returncode, 0, runner.stderr)
            with self.assertRaisesRegex(A.Refuse, "liveness unknown"):
                self.store.reconcile()

    def test_unknown_host_liveness_never_proves_death(self):
        with mock.patch.object(A.os, "killpg", side_effect=PermissionError("unknown")):
            with self.assertRaises(A.Refuse):
                A.group_alive(os.getpgrp())
        with mock.patch.object(A.sys, "platform", "unsupported"):
            with self.assertRaises(A.Refuse):
                A.process(os.getpid())
        with mock.patch("builtins.open", mock.mock_open(read_data=b"malformed")):
            with self.assertRaises(A.Refuse):
                A.process(os.getpid())

    def test_drop_recreate_uses_same_lock_and_requires_registry_commit(self):
        with self.locked():
            self.prepare()
            inode = Path(self.store.lock_path).stat().st_ino
            with self.assertRaises(A.Refuse):
                self.store.drop()
            self.register(cleaned="2026-01-01T00:00:00Z")
            self.store.drop()
            self.store.drop()
            self.assertFalse(Path(self.store.path).exists())
            self.assertEqual(Path(self.store.lock_path).stat().st_ino, inode)
            r = self.shell('lc_lock "$1"', self.run)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("busy", r.stderr)
            (self.state / "local-runs.jsonl").unlink()
            self.prepare()
            self.assertEqual(Path(self.store.lock_path).stat().st_ino, inode)

    def test_reg_del_shares_registry_lock_with_mark_and_append(self):
        with self.locked():
            self.prepare()
            self.register(verified="old", retained="yes")
        registry = self.state / "local-runs.jsonl"
        lock = os.open(str(registry) + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            script = ('source "$1/lib/lib.sh"; '
                      'flock() { [ /proc/self/fd/9 -ef "$DA_STATE/local-runs.jsonl.lock" ] || return 1; '
                      'printf "locking\\n"; command flock "$@"; }; reg_del "$2" verified')
            deleter = subprocess.Popen(["bash", "-c", script, "test", str(ROOT), str(self.run)],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                import select
                self.assertTrue(select.select([deleter.stdout], [], [], 10)[0])
                self.assertEqual(deleter.stdout.readline().strip(), "locking")
                # While the leaf lock is held, a concurrent append is authoritative.
                with registry.open("ab") as stream:
                    stream.write(A.encode(dict(run=str(self.root / "qargi.Other1"), verified="keep")))
                fcntl.flock(lock, fcntl.LOCK_UN)
                out, err = deleter.communicate(timeout=15)
                self.assertEqual(deleter.returncode, 0, err + out)
            finally:
                if deleter.poll() is None:
                    deleter.kill()
                deleter.communicate(timeout=15)
        finally:
            os.close(lock)
        rows = [json.loads(line) for line in registry.read_text().splitlines()]
        self.assertNotIn("verified", rows[0])
        self.assertEqual(rows[0]["retained"], "yes")
        self.assertEqual(rows[1]["verified"], "keep")
        self.assertEqual(stat.S_IMODE(registry.stat().st_mode), 0o600)
        self.write(registry, b"malformed\n")
        before = registry.read_bytes()
        r = self.shell('reg_del "$1" verified', self.run)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(registry.read_bytes(), before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
