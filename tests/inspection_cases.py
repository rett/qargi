"""Hermetic inspection cases, also run by test_local_run.sh."""
import hermetic  # noqa: F401
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
import local_run as L


class Inspection(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.clone = self.root / 'run/clone'
        self.git('init', '-q', '-b', 'main', str(self.clone))
        (self.clone / 'data').write_text('old\n')
        self.git('-C', str(self.clone), 'add', 'data')
        self.git('-C', str(self.clone), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'base')
        self.git('-C', str(self.clone), 'update-ref', 'refs/remotes/origin/main', 'HEAD')
        self.gd = self.clone / '.git'

    def git(self, *args):
        return subprocess.run([L.INSPECTION_GIT, *args], check=True, capture_output=True)

    def test_clean_dirty_and_commit_counts(self):
        self.assertEqual(L.worktree_changes(str(self.clone)), ([], []))
        self.assertEqual(L.clone_commits(str(self.clone)), 0)
        (self.clone / 'data').write_text('new\n')
        (self.clone / 'new').write_text('new\n')
        self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], ['new']))
        self.git('-C', str(self.clone), 'add', 'data')
        self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], ['new']))
        self.git('-C', str(self.clone), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'work')
        self.assertEqual(L.clone_commits(str(self.clone)), 1)
        self.assertEqual(L.clone_commits(str(self.clone), branches=True), 1)

    def test_new_filter_after_preflight_cannot_execute(self):
        marker = self.root / 'helper-ran'
        config = self.gd / 'config'
        helper = self.root / 'helper'
        helper.write_text('#!/bin/sh\ntouch "' + str(marker) + '"\ncat\n')
        helper.chmod(0o755)
        original = subprocess.run
        def late_filter(argv, **kwargs):
            # Immediately before status executes: after all config preflight and
            # after any driver enumeration. Rechecking names cannot close this race.
            if 'status' in argv:
                with config.open('a') as f:
                    f.write('\n[filter "previously-unknown"]\n clean = ' + str(helper) + '\n required = true\n')
                (self.clone / '.gitattributes').write_text('data filter=previously-unknown\n')
                (self.clone / 'data').write_text('new\n')  # different content, same length
            return original(argv, **kwargs)
        with patch.object(L.subprocess, 'run', late_filter):
            result = L.worktree_changes(str(self.clone))
        self.assertTrue(result is None or 'data' in result[0], result)
        self.assertFalse(marker.exists())

    def test_unsupported_and_nonregular_metadata(self):
        target = self.root / 'outside'
        target.write_text('evidence\n')
        for name in ('commondir', 'config.worktree', 'reftable', 'info/grafts', 'shallow', 'sharedindex.abc',
                     'objects/info/alternates', 'objects/info/http-alternates', 'objects/linked', 'refs/linked'):
            path = self.gd / name
            path.parent.mkdir(parents=True, exist_ok=True)
            for kind in ('file', 'symlink', 'fifo'):
                if kind == 'file' and name in ('objects/linked', 'refs/linked'):
                    continue  # regular object/ref entries are part of the supported copy
                with self.subTest(name=name, kind=kind):
                    if kind == 'file':
                        path.write_text('unsupported\n')
                    elif kind == 'symlink':
                        path.symlink_to(target)
                    else:
                        os.mkfifo(path)
                    self.assertIsNone(L.clone_commits(str(self.clone)))
                    self.assertIsNone(L.worktree_changes(str(self.clone)))
                    path.unlink()
        for name in ('HEAD', 'config', 'index', 'packed-refs'):
            path = self.gd / name
            saved = path.read_bytes() if path.exists() else None
            if path.exists():
                path.unlink()
            for kind in ('symlink', 'fifo', 'directory'):
                with self.subTest(name=name, kind=kind):
                    if kind == 'symlink':
                        path.symlink_to(target)
                    elif kind == 'fifo':
                        os.mkfifo(path)
                    else:
                        path.mkdir()
                    self.assertIsNone(L.clone_commits(str(self.clone)))
                    self.assertIsNone(L.worktree_changes(str(self.clone)))
                    path.rmdir() if kind == 'directory' else path.unlink()
            if saved is not None:
                path.write_bytes(saved)
        self.assertEqual(target.read_text(), 'evidence\n')

    def test_trusted_ancestor_links_but_no_clone_or_git_links(self):
        link = self.root / 'ancestor'
        link.symlink_to(self.root / 'run', target_is_directory=True)
        self.assertEqual(L.clone_commits(str(link / 'clone')), 0)
        self.assertEqual(L.worktree_changes(str(link / 'clone')), ([], []))
        clone_link = self.root / 'clone-link'
        clone_link.symlink_to(self.clone, target_is_directory=True)
        self.assertIsNone(L.clone_commits(str(clone_link)))
        saved = self.clone / 'git.saved'
        self.gd.rename(saved)
        self.gd.symlink_to(saved, target_is_directory=True)
        self.assertIsNone(L.clone_commits(str(self.clone)))

    def test_bounds_and_unsupported_refstorage(self):
        reasons = []
        with patch.object(L, 'INSPECTION_BYTES_MAX', 1):
            self.assertIsNone(L.clone_commits(str(self.clone), reasons=reasons))
        self.assertEqual(reasons, ['metadata byte limit exceeded (512 MiB in 0.2.13)'])
        reasons = []
        with patch.object(L, 'INSPECTION_ENTRIES_MAX', 1):
            self.assertIsNone(L.worktree_changes(str(self.clone), reasons))
        self.assertEqual(reasons, ['metadata traversal/read-step limit exceeded'])
        reasons = []
        with patch.object(L, 'GIT_CONFIG_MAX', 8):
            self.assertIsNone(L.worktree_changes(str(self.clone), reasons))
        self.assertEqual(reasons, ['Git config byte limit exceeded (1 MiB)'])
        reasons = []
        with patch.object(L.time, 'monotonic', side_effect=[0] + [L.WORKTREE_TIMEOUT + 1] * 20):
            self.assertIsNone(L.clone_commits(str(self.clone), reasons=reasons))
        self.assertEqual(reasons, ['metadata copy time limit exceeded'])
        deep = self.gd / 'refs' / Path(*(['d'] * 66))
        deep.mkdir(parents=True)
        reasons = []
        self.assertIsNone(L.clone_commits(str(self.clone), reasons=reasons))
        self.assertEqual(reasons, ['metadata directory depth limit exceeded'])
        shutil.rmtree(self.gd / 'refs/d')
        with (self.gd / 'config').open('a') as f:
            f.write('\n[extensions]\n refStorage = reftable\n')
        self.assertIsNone(L.clone_commits(str(self.clone)))

    def test_failure_diagnostics_never_copy_exception_or_config_contents(self):
        secret = 'fixture-config-and-exception-secret'
        for error in (OSError(secret), ValueError(secret), subprocess.SubprocessError(secret), subprocess.TimeoutExpired(secret, 1)):
            reasons = []
            with patch.object(L, 'inspection_copy', side_effect=error):
                self.assertIsNone(L.worktree_changes(str(self.clone), reasons))
            self.assertTrue(reasons)
            self.assertNotIn(secret, str(reasons))
        with (self.gd / 'config').open('a') as f:
            f.write('\n[core]\n eol = ' + secret + '\n')
        reasons = []
        self.assertIsNone(L.clone_commits(str(self.clone), reasons=reasons))
        self.assertEqual(reasons, ['unsupported core configuration value'])

    def test_replacement_refs_cannot_change_commit_or_status_semantics(self):
        (self.clone / 'data').write_text('new\n')
        self.git('-C', str(self.clone), 'add', 'data')
        self.git('-C', str(self.clone), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-qm', 'work')
        self.git('-C', str(self.clone), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'second')
        self.git('-C', str(self.clone), 'replace', 'HEAD', 'HEAD^^')
        # Negative control: replacements hide the new commit and change its tree.
        self.assertEqual(self.git('-C', str(self.clone), 'rev-list', '--count', 'HEAD', '--not', '--remotes=origin').stdout.strip(), b'1')
        self.assertEqual(self.git('-C', str(self.clone), 'status', '--porcelain').stdout, b'M  data\n')
        self.assertEqual(L.clone_commits(str(self.clone)), 2)
        self.assertEqual(L.worktree_changes(str(self.clone)), ([], []))
        (self.clone / 'data').write_text('old\n')
        self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], []))

    def test_sha256(self):
        repo = self.root / 'sha256/clone'
        self.git('init', '-q', '--object-format=sha256', str(repo))
        self.git('-C', str(repo), '-c', 'user.name=t', '-c', 'user.email=t@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'base')
        self.assertEqual(L.clone_commits(str(repo)), 1)
        self.assertEqual(L.worktree_changes(str(repo)), ([], []))
        self.assert_inspection_format(repo, '1', 'sha256')

    def assert_inspection_format(self, clone, version, fmt):
        original = subprocess.run
        def inspect(argv, **kwargs):
            if 'rev-list' in argv:
                config = (Path(kwargs['env']['GIT_DIR']) / 'config').read_bytes()
                entries = L.config_entries(config)
                self.assertEqual(entries['core.repositoryformatversion'], [version])
                self.assertEqual(entries.get('extensions.objectformat'), [fmt] if fmt == 'sha256' else None)
            return original(argv, **kwargs)
        with patch.object(L.subprocess, 'run', inspect):
            self.assertIsNotNone(L.clone_commits(str(clone)))

    def test_sha1_uses_minimal_version_zero_configuration(self):
        self.assert_inspection_format(self.clone, '0', 'sha1')

    def test_explicit_empty_and_valueless_booleans_keep_git_semantics(self):
        config = self.gd / 'config'
        original = config.read_text()
        (self.clone / 'data').chmod(0o755)
        for spelling, expected in (('filemode', (['data'], [])), ('filemode =', ([], [])), ('filemode = ""', ([], []))):
            config.write_text(original + '\n[core]\n ' + spelling + '\n')
            self.assertEqual(self.git('-C', str(self.clone), 'config', '--bool', 'core.filemode').stdout.strip(),
                             b'true' if expected[0] else b'false')
            self.assertEqual(L.worktree_changes(str(self.clone)), expected)
        self.assertEqual(L.config_entries(b'[core]\n filemode\n filemode =\n'), {'core.filemode': [None, '']})

    def test_safe_filemode_configuration(self):
        self.git('-C', str(self.clone), 'config', 'core.filemode', 'false')
        (self.clone / 'data').chmod(0o755)
        self.assertEqual(L.worktree_changes(str(self.clone)), ([], []))
        (self.clone / 'data').write_text('new\n')
        self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], []))

    def test_index_copy_preserves_racy_timestamp_detection(self):
        index = self.gd / 'index'
        data = self.clone / 'data'
        before = data.stat()
        timestamp = before.st_mtime_ns
        os.utime(index, ns=(timestamp, timestamp))
        data.write_text('new\n')
        os.utime(data, ns=(before.st_atime_ns, timestamp))
        original = subprocess.run
        lose_timestamp = False
        def inspect(argv, **kwargs):
            if 'status' in argv:
                copied = Path(kwargs['env']['GIT_DIR']) / 'index'
                self.assertEqual(copied.stat().st_mtime_ns, timestamp)
                # Test-only controls remove inode/ctime detection as an explanation.
                argv = argv[:1] + ['-c', 'core.checkstat=minimal', '-c', 'core.trustctime=false'] + argv[1:]
                if lose_timestamp:
                    newer = timestamp + 10_000_000_000
                    os.utime(copied, ns=(newer, newer))
            return original(argv, **kwargs)
        with patch.object(L.subprocess, 'run', inspect):
            self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], []))
            lose_timestamp = True
            self.assertEqual(L.worktree_changes(str(self.clone)), ([], []))  # negative control
            lose_timestamp = False
            self.assertEqual(L.worktree_changes(str(self.clone)), (['data'], []))

    def test_lead_git_resolved_once_from_nonstandard_path(self):
        trusted = self.root / 'trusted'
        trusted.mkdir()
        shutil.copy2(L.INSPECTION_GIT, trusted / 'git')
        with patch.dict(os.environ, PATH=str(trusted) + os.pathsep + os.environ['PATH']):
            importlib.reload(L)
        try:
            self.assertEqual(L.INSPECTION_GIT, str(trusted / 'git'))
            member = self.clone / 'bin'
            member.mkdir()
            marker = self.root / 'wrapper-ran'
            (member / 'git').write_text('#!/bin/sh\ntouch "' + str(marker) + '"\nexit 99\n')
            (member / 'git').chmod(0o755)
            with patch.dict(os.environ, PATH=str(member), GIT_EXEC_PATH=str(member), GIT_CONFIG_COUNT='1',
                            GIT_CONFIG_KEY_0='core.fsmonitor', GIT_CONFIG_VALUE_0=str(member / 'git')):
                self.assertEqual(L.clone_commits(str(self.clone)), 0)
                self.assertIn('bin/git', L.worktree_changes(str(self.clone))[1])
            self.assertFalse(marker.exists())
        finally:
            importlib.reload(L)


if __name__ == '__main__':
    unittest.main(verbosity=2)
