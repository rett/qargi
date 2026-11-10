#!/usr/bin/env python3
"""lib/marshal_refs.py read(): the cache is listed with one for-each-ref and every object of every ref is read by two cat-file processes
(sizes first, then commits, trees and record.json files), however many refs there are. The batch read gives, for every kind of bad ref and
record, the same answer as reading one ref at a time (the former way, and the fallback when git cannot answer in a batch): the same
records, the same ignored refs with the same reasons in the same order, and verify called with the same arguments. verify is called for
every record on every read (nothing is remembered between reads, so a record that was changed in between is judged again). Offline.
Run: python3 tests/test_marshal_batch.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'lib'))
import marshal_refs as R  # noqa: E402

GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME='t', GIT_AUTHOR_EMAIL='t@example.net', GIT_COMMITTER_NAME='t', GIT_COMMITTER_EMAIL='t@example.net')


def rec(name, **more):
    return dict({'feature': name, 'status': 'active', 'rev': 1, 'goal': 'g ' + name}, **more)


class Repo:
    """A scratch repository whose refs/qargi/ holds one ref of every kind a remote can put there."""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix='batch.')
        self.git('init', '-q', '.')

    def git(self, *args, data=None, check=True):
        r = subprocess.run(['git', '-C', self.dir] + list(args), input=data, capture_output=True, env=GIT_ENV)
        if check and r.returncode != 0:
            raise AssertionError('git %s: %s' % (' '.join(args), r.stderr.decode()))
        return r.stdout.decode().strip()

    def blob(self, data):
        return self.git('hash-object', '-w', '--stdin', data=data if isinstance(data, bytes) else data.encode())

    def tree(self, lines, missing=False):
        return self.git('mktree', *(['--missing'] if missing else []), data=''.join(l + '\n' for l in lines).encode())

    def commit(self, tree, parent=None, message='m'):
        return self.git('commit-tree', '-m', message, *(['-p', parent] if parent else []), tree)

    def record(self, ref, data, mode='100644', message='m', parent=None):
        """A commit whose tree holds data as record.json, on ref."""
        c = self.commit(self.tree(['%s blob %s\trecord.json' % (mode, self.blob(data))]), parent, message)
        self.git('update-ref', ref, c)
        return c

    def close(self):
        shutil.rmtree(self.dir, True)


def populate(repo):
    """Every kind of ref; returns {ref: commit oid}."""
    f, d = 'refs/qargi/features/', 'refs/qargi/done/'
    out = {}
    for n in ('alpha', 'beta', 'gamma'):
        out[f + n] = repo.record(f + n, json.dumps(rec(n)), message='marshal: %s rev 1\n\nsignature goes here' % n)
    out[d + 'delta'] = repo.record(d + 'delta', json.dumps(rec('delta', status='finished')))
    out[f + 'exe'] = repo.record(f + 'exe', json.dumps(rec('exe')), mode='100755')
    out[f + 'child'] = repo.record(f + 'child', json.dumps(rec('child')), parent=out[f + 'alpha'])
    out[f + 'same-commit'] = out[f + 'alpha']                                       # a second ref at a commit that names another feature
    repo.git('update-ref', f + 'same-commit', out[f + 'alpha'])
    out[f + 'badjson'] = repo.record(f + 'badjson', '{not json')
    out[f + 'array'] = repo.record(f + 'array', '[1, 2]')
    out[f + 'other'] = repo.record(f + 'other', json.dumps(rec('someone-else')))
    out[f + 'ctrl'] = repo.record(f + 'ctrl', json.dumps(rec('ctrl', goal='a\x01b')))
    out[f + 'latin'] = repo.record(f + 'latin', b'{"feature": "latin", "goal": "\xe9"}')
    out[f + 'big'] = repo.record(f + 'big', json.dumps(rec('big', note='x' * (R.MAX_RECORD + 10))))
    out[f + 'edge'] = repo.record(f + 'edge', json.dumps(rec('edge', note='x' * (R.MAX_RECORD - 200))))
    b = repo.blob(json.dumps(rec('extra')))
    out[f + 'extra'] = repo.commit(repo.tree(['100644 blob %s\trecord.json' % b, '100644 blob %s\tother.txt' % b]))
    out[f + 'empty'] = repo.commit(repo.tree([]))
    out[f + 'wrongfile'] = repo.commit(repo.tree(['100644 blob %s\trecords.json' % b]))
    out[f + 'dir'] = repo.commit(repo.tree(['040000 tree %s\trecord.json' % repo.tree(['100644 blob %s\ta' % b])]))
    out[f + 'link'] = repo.commit(repo.tree(['120000 blob %s\trecord.json' % repo.blob('target')]))
    out[f + 'noblob'] = repo.commit(repo.tree(['100644 blob %s\trecord.json' % ('1234567890' * 4)], missing=True))
    out[f + 'Bad_Name'] = repo.record(f + 'Bad_Name', json.dumps(rec('Bad_Name')))
    out[f + 'blobref'] = repo.blob('not a commit')
    out[f + 'treeref'] = repo.tree([])
    for ref in ('blobref', 'treeref', 'extra', 'empty', 'wrongfile', 'dir', 'link', 'noblob'):    # made without a ref
        repo.git('update-ref', f + ref, out[f + ref])
    out['refs/qargi/other/x'] = repo.record('refs/qargi/other/x', json.dumps(rec('x')))
    return out


class Counting:
    """run_git of marshal_refs, counting the git processes by subcommand and keeping the input of every cat-file."""

    def __init__(self):
        self.calls, self.inputs = [], []

    def __enter__(self):
        self.real = R.run_git

        def run(repo, args, timeout=None, data=None, extra_env=None):
            self.calls.append(args[0])
            if args[0] == 'cat-file':
                self.inputs.append((args[1], (data or b'').decode().split()))
            return self.real(repo, args, timeout, data, extra_env)
        R.run_git = run
        return self

    def __exit__(self, *exc):
        R.run_git = self.real

    def count(self, sub):
        return self.calls.count(sub)


def reading(repo, batch, check=None, verify=None):
    """read() in the batch way, or one ref at a time (batch_records answers None, as it does when git cannot) -> (result, heads, verify calls)."""
    calls, heads = [], {}

    def v(kind, name, oid, record, parents, message):
        calls.append((kind, name, oid, record, parents, message))
        return verify(kind, name, oid, record, parents, message) if verify else None
    real = R.batch_records
    if not batch:
        R.batch_records = lambda *a: None
    try:
        res = R.read(repo.dir, check, v, heads)
    finally:
        R.batch_records = real
    return res, heads, calls


class Batch(unittest.TestCase):
    def setUp(self):
        self.repo = Repo()
        self.addCleanup(self.repo.close)
        self.oids = populate(self.repo)

    def test_the_batch_read_answers_as_reading_one_ref_at_a_time(self):
        for check, verify in ((None, None), (lambda r: 'check says no' if r.get('feature') == 'beta' else None,
                                             lambda k, n, o, r, p, m: 'verify says no' if n == 'gamma' else None)):
            new = reading(self.repo, True, check, verify)
            old = reading(self.repo, False, check, verify)
            self.assertEqual(new, old)
            (feats, done, ignored), heads, calls = new
            self.assertIn('alpha', feats)
            self.assertIn('exe', feats)
            self.assertIn('edge', feats)
            self.assertEqual(list(done), ['delta'])
            self.assertEqual(len(heads), 23)                                           # every ref of features/ and done/, valid or not
            self.assertEqual(feats['child'][0], self.oids['refs/qargi/features/child'])
        # the reasons are the ones read_one gives, whichever way a ref was read
        why = dict(ignored)
        for name, want in (('badjson', 'record.json is not valid JSON'), ('array', 'record.json is not a JSON object'),
                           ('other', 'its feature is not other'), ('ctrl', 'the record has control characters'),
                           ('latin', 'record.json is not valid JSON'), ('big', 'record.json is over 64 KiB'),
                           ('extra', 'its tree must hold record.json and nothing else'), ('empty', 'its tree must hold record.json and nothing else'),
                           ('wrongfile', 'its tree must hold record.json and nothing else'), ('dir', 'record.json is not a regular file'),
                           ('link', 'record.json is not a regular file'), ('noblob', 'its tree must hold record.json and nothing else'),
                           ('Bad_Name', 'not a feature name'), ('blobref', 'not a commit'), ('treeref', 'not a commit'),
                           ('same-commit', 'its feature is not same-commit')):
            self.assertEqual(why.get('refs/qargi/features/' + name), want, name)

    def test_the_processes_do_not_grow_with_the_refs(self):
        with Counting() as c:
            (feats, done, ignored), _, _ = reading(self.repo, True)
        self.assertEqual((c.count('for-each-ref'), c.count('cat-file'), len(c.calls)), (1, 2, 3), c.calls)
        for n in range(30):
            self.repo.record('refs/qargi/features/more-%d' % n, json.dumps(rec('more-%d' % n)))
        with Counting() as c:
            (feats2, _, _), _, _ = reading(self.repo, True)
        self.assertEqual((c.count('for-each-ref'), c.count('cat-file'), len(c.calls)), (1, 2, 3), c.calls)
        self.assertEqual(len(feats2), len(feats) + 30)
        with Counting() as c:                                                              # one at a time: the processes grow with the refs
            reading(self.repo, False)
        self.assertGreater(c.count('cat-file') + c.count('ls-tree'), 100)

    def test_a_record_over_the_limit_is_never_read(self):
        big = self.oids['refs/qargi/features/big']
        with Counting() as c:
            reading(self.repo, True)
        sizes, objects = c.inputs
        self.assertEqual((sizes[0], objects[0]), ('--batch-check', '--batch'))
        self.assertIn(big + ':record.json', sizes[1])                                      # its size is asked
        self.assertNotIn(big + ':record.json', objects[1])                                 # its content is not
        self.assertIn(self.oids['refs/qargi/features/edge'] + ':record.json', objects[1])

    def test_nothing_to_read_runs_no_cat_file(self):
        empty = Repo()
        self.addCleanup(empty.close)
        with Counting() as c:
            self.assertEqual(R.read(empty.dir), ({}, {}, []))
        self.assertEqual(c.calls, ['for-each-ref'])
        empty.record('refs/qargi/features/Bad_Name', '{}')
        with Counting() as c:
            self.assertEqual(R.read(empty.dir)[2], [('refs/qargi/features/Bad_Name', 'not a feature name')])
        self.assertEqual(c.count('cat-file'), 0)

    def test_verify_is_called_for_every_record_on_every_read(self):
        seen = []
        for _ in range(3):
            _, _, calls = reading(self.repo, True)
            seen.append(sorted((k, n) for k, n, *_ in calls))
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(seen[0], seen[2])
        self.assertEqual(len(seen[0]), 7)                                                  # alpha beta gamma delta exe child edge: the records that passed
        # a record that is replaced between two reads is judged again: verify sees the new commit and its refusal drops the record
        c2 = self.repo.record('refs/qargi/features/alpha', json.dumps(rec('alpha', goal='changed')))

        def verify(kind, name, oid, record, parents, message):
            return 'not signed' if oid == c2 else None
        (feats, _, ignored), _, calls = reading(self.repo, True, None, verify)
        self.assertNotIn('alpha', feats)
        self.assertIn(('refs/qargi/features/alpha', 'not signed'), ignored)
        self.assertIn(c2, [c[2] for c in calls])

    def test_verify_gets_the_real_parents_and_message(self):
        _, _, calls = reading(self.repo, True)
        got = {n: (p, m) for k, n, o, r, p, m in calls}
        self.assertEqual(got['child'][0], [self.oids['refs/qargi/features/alpha']])
        self.assertEqual(got['alpha'], ([], 'marshal: alpha rev 1\n\nsignature goes here\n'))

    def test_git_that_cannot_answer_in_a_batch_falls_back_to_one_ref_at_a_time(self):
        real = R.run_git

        def broken(repo, args, timeout=None, data=None, extra_env=None):
            if args[0] == 'cat-file' and args[1].startswith('--batch'):
                return 129, b'', 'unknown option', False
            return real(repo, args, timeout, data, extra_env)
        R.run_git = broken
        try:
            res = R.read(self.repo.dir)
        finally:
            R.run_git = real
        self.assertEqual(res, reading(self.repo, False)[0])

    def test_an_answer_that_does_not_parse_is_not_used(self):
        for out in (b'', b'x\n', b'abc blob 3\nabcd\n', b'abc blob 3\nabc\nextra', b'abc blob x\nabc\n', b'abc nothing 3\nabc\n'):
            real = R.run_git
            R.run_git = lambda repo, args, timeout=None, data=None, extra_env=None, out=out: (0, out, '', False)
            try:
                self.assertIsNone(R.batch_lines(self.repo.dir, '--batch', ['abc']), out)
            finally:
                R.run_git = real
        real = R.run_git
        R.run_git = lambda repo, args, timeout=None, data=None, extra_env=None: (0, b'abc missing\nabc blob 3\nabc\n', '', False)
        try:
            self.assertEqual(R.batch_lines(self.repo.dir, '--batch', ['x', 'abc']), [None, (b'blob', b'abc')])
        finally:
            R.run_git = real

    def test_the_tree_rules(self):
        h = b'\x01' * 20
        ent = lambda mode, name: mode + b' ' + name + b'\0' + h
        self.assertEqual(R.tree_record(ent(b'100644', b'record.json'), 20), '')
        self.assertEqual(R.tree_record(ent(b'100755', b'record.json'), 20), '')
        self.assertEqual(R.tree_record(ent(b'120000', b'record.json'), 20), 'record.json is not a regular file')
        self.assertEqual(R.tree_record(ent(b'40000', b'record.json'), 20), 'record.json is not a regular file')
        self.assertEqual(R.tree_record(ent(b'100644', b'x'), 20), 'its tree must hold record.json and nothing else')
        self.assertEqual(R.tree_record(b'', 20), 'its tree must hold record.json and nothing else')
        self.assertEqual(R.tree_record(ent(b'100644', b'record.json') + ent(b'100644', b'z'), 20), 'its tree must hold record.json and nothing else')
        self.assertEqual(R.tree_record(ent(b'100644', b'record.json')[:-3], 20), 'its tree cannot be read')
        self.assertEqual(R.tree_record(b'100644 record.json', 20), 'its tree cannot be read')


if __name__ == '__main__':
    unittest.main()
