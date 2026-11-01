#!/usr/bin/env python3
"""lib/marshal_sign.py: the signed payload, the signature round trip with the real OpenSSH key tool, hostile armor, the signers
file and the accepted high-water mark. Offline. Skips (with a message) when the key tool is not installed.
Run: python3 tests/test_marshal_sign_unit.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import contextlib, json, os, shutil, stat, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, '..', 'lib')
sys.path.insert(0, LIB)
import marshal_sign as M  # noqa: E402

REAL = shutil.which('ssh-keygen')
OID1 = 'a' * 40
OID2 = 'b' * 40
OID3 = 'c' * 40
BEGIN = '-----BEGIN SSH SIGNATURE-----'
END = '-----END SSH SIGNATURE-----'


def setUpModule():
    if not REAL:
        raise unittest.SkipTest('ssh-keygen is not installed: the signing tests need the real OpenSSH key tool')


@contextlib.contextmanager
def env(**kv):
    old = {k: os.environ.get(k) for k in kv}
    os.environ.update({k: str(v) for k, v in kv.items()})
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='sign.')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = os.path.join(self.tmp, 'cred', 'marshal_ed25519')
        self.signers = os.path.join(self.tmp, 'state', 'marshal', 'proj.signers')
        self.line = M.keygen(self.key, 'alice@laptop')
        M.signers_add(self.signers, self.line)
        self.payload = M.signed_payload('proj', 'feat', 'features', 3, OID1, 'lead-1', {'feature': 'feat', 'status': 'open'})

    def fake(self, body):
        p = os.path.join(self.tmp, 'fake-keygen')
        with open(p, 'w') as f:
            f.write('#!/bin/sh\n' + body)
        os.chmod(p, 0o755)
        return p


class Canonical(unittest.TestCase):
    def test_form_is_stable(self):
        a = M.canonical_json({'b': [1, 2, {'z': None, 'a': True}], 'a': 'café'})
        self.assertEqual(a, b'{"a":"caf\\u00e9","b":[1,2,{"a":true,"z":null}]}')
        self.assertEqual(a, M.canonical_json({'a': 'café', 'b': [1, 2, {'a': True, 'z': None}]}))

    def test_floats_are_refused(self):
        for bad in (1.5, {'a': [0.0]}, {'a': {'b': float('nan')}}):
            with self.assertRaises(ValueError):
                M.canonical_json(bad)

    def test_non_string_keys_and_unknown_types_are_refused(self):
        for bad in ({1: 'a'}, {'a': object()}, {'a': {1, 2}}):
            with self.assertRaises(ValueError):
                M.canonical_json(bad)

    def test_payload_shape(self):
        p = M.signed_payload('proj', 'feat', 'done', 0, None, None, {'x': 1})
        d = json.loads(p)
        self.assertEqual(sorted(d), ['feature', 'kind', 'lead', 'ns', 'parent', 'project', 'record_sha256', 'rev', 'v'])
        self.assertEqual((d['v'], d['ns'], d['kind'], d['rev'], d['parent'], d['lead']), (1, 'qargi-marshal', 'done', 0, None, None))
        self.assertEqual(len(d['record_sha256']), 64)
        self.assertEqual(p, M.signed_payload('proj', 'feat', 'done', 0, None, None, {'x': 1}))
        self.assertNotEqual(p, M.signed_payload('proj', 'feat', 'done', 0, None, None, {'x': 2}))

    def test_payload_refuses_bad_fields(self):
        for args in (('proj', 'feat', 'other', 1, None, None, {}), ('proj', 'feat', 'done', -1, None, None, {}),
                     ('proj', 'feat', 'done', True, None, None, {}), ('proj', 'feat', 'done', 1, 'xyz', None, {}),
                     ('proj', 'feat', 'done', 1, None, None, {'f': 1.5}), ('proj', 'feat', 'done', 1, None, 5, {}),
                     ('proj', 'feat', 'done', 1, None, None, [])):
            with self.assertRaises(ValueError, msg=repr(args)):
                M.signed_payload(*args)


class Sign(Base):
    def test_round_trip(self):
        arm = M.sign(self.payload, self.key)
        self.assertTrue(arm.startswith(BEGIN + '\n') and arm.rstrip().endswith(END))
        self.assertEqual(M.verify(self.payload, arm, self.signers, 'alice@laptop'), (True, ''))

    def test_key_is_0600_and_line_is_signers_format(self):
        self.assertEqual(stat.S_IMODE(os.stat(self.key).st_mode), 0o600)
        self.assertRegex(self.line, r'^alice@laptop namespaces="qargi-marshal" ssh-ed25519 [A-Za-z0-9+/]+=*$')
        self.assertTrue(os.path.isfile(self.key + '.pub'))

    def test_keygen_never_overwrites(self):
        with self.assertRaises(M.SignError):
            M.keygen(self.key, 'bob@laptop')

    def test_tampered_payload(self):
        arm = M.sign(self.payload, self.key)
        other = M.signed_payload('proj', 'feat', 'features', 4, OID1, 'lead-1', {'feature': 'feat', 'status': 'open'})
        ok, why = M.verify(other, arm, self.signers, 'alice@laptop')
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_wrong_key(self):
        key2 = os.path.join(self.tmp, 'other_key')
        M.keygen(key2, 'alice@laptop')
        ok, _ = M.verify(self.payload, M.sign(self.payload, key2), self.signers, 'alice@laptop')
        self.assertFalse(ok)

    def test_wrong_namespace(self):
        arm = M.sign(self.payload, self.key, 'other-ns')
        self.assertFalse(M.verify(self.payload, arm, self.signers, 'alice@laptop')[0])
        self.assertFalse(M.verify(self.payload, arm, self.signers, 'alice@laptop', 'other-ns')[0])
        arm = M.sign(self.payload, self.key)
        self.assertFalse(M.verify(self.payload, arm, self.signers, 'alice@laptop', 'other-ns')[0])

    def test_unknown_principal(self):
        arm = M.sign(self.payload, self.key)
        ok, why = M.verify(self.payload, arm, self.signers, 'mallory@host')
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_principal_that_is_not_the_signer(self):
        key2 = os.path.join(self.tmp, 'key2')
        M.signers_add(self.signers, M.keygen(key2, 'bob@desk'))
        arm = M.sign(self.payload, key2)
        self.assertTrue(M.verify(self.payload, arm, self.signers, 'bob@desk')[0])
        self.assertFalse(M.verify(self.payload, arm, self.signers, 'alice@laptop')[0])

    def test_revoked_key(self):
        arm = M.sign(self.payload, self.key)
        self.assertTrue(M.verify(self.payload, arm, self.signers, 'alice@laptop')[0])
        self.assertTrue(M.signers_remove(self.signers, 'alice@laptop'))
        ok, _ = M.verify(self.payload, arm, self.signers, 'alice@laptop')
        self.assertFalse(ok)

    def test_signer_names_that_are_not_ids(self):
        arm = M.sign(self.payload, self.key)
        for bad in ('-alice@laptop', '', 'a b', 'a\nb', 'alice@laptop\x00', 'x' * 200, None):
            ok, why = M.verify(self.payload, arm, self.signers, bad)
            self.assertFalse(ok, repr(bad))
            self.assertTrue(why)

    def test_signers_file_must_be_a_regular_file(self):
        arm = M.sign(self.payload, self.key)
        link = os.path.join(self.tmp, 'link.signers')
        os.symlink(self.signers, link)
        ok, why = M.verify(self.payload, arm, link, 'alice@laptop')
        self.assertFalse(ok)
        self.assertIn('symlink', why)
        self.assertFalse(M.verify(self.payload, arm, self.tmp, 'alice@laptop')[0])
        self.assertFalse(M.verify(self.payload, arm, os.path.join(self.tmp, 'absent'), 'alice@laptop')[0])

    def test_sign_refuses_an_open_or_linked_key(self):
        os.chmod(self.key, 0o644)
        with self.assertRaises(M.SignError):
            M.sign(self.payload, self.key)
        os.chmod(self.key, 0o600)
        link = os.path.join(self.tmp, 'keylink')
        os.symlink(self.key, link)
        with self.assertRaises(M.SignError):
            M.sign(self.payload, link)
        with self.assertRaises(M.SignError):
            M.sign(self.payload, os.path.join(self.tmp, 'absent'))

    def test_oversize_payload_is_refused(self):
        with self.assertRaises(M.SignError):
            M.sign(b'x' * (M.MAX_MESSAGE + 1), self.key)
        self.assertFalse(M.verify(b'x' * (M.MAX_MESSAGE + 1), M.sign(self.payload, self.key), self.signers, 'alice@laptop')[0])


class Armor(Base):
    def verify(self, arm):
        return M.verify(self.payload, arm, self.signers, 'alice@laptop')

    def test_hostile_armor(self):
        good = M.sign(self.payload, self.key)
        body = good.strip().splitlines()[1:-1]
        cases = {
            'two blocks': good + good,
            'text before': 'hello\n' + good,
            'text after': good + 'hello\n',
            'oversize': BEGIN + '\n' + 'A' * (M.MAX_ARMOR + 10) + '\n' + END + '\n',
            'not base64': BEGIN + '\n' + 'AAAA!AAA\n' + END + '\n',
            'space in body': BEGIN + '\n' + body[0][:10] + ' ' + body[0][10:] + '\n' + END + '\n',
            'control chars': BEGIN + '\n' + body[0][:10] + '\x1b[2J' + body[0][10:] + '\n' + END + '\n',
            'carriage return': good.replace('\n', '\r\n'),
            'nul': BEGIN + '\n' + 'AAAA\x00AAA\n' + END + '\n',
            'empty body': BEGIN + '\n' + END + '\n',
            'no end': BEGIN + '\n' + body[0] + '\n',
            'no begin': '\n'.join(body) + '\n' + END + '\n',
            'unicode': BEGIN + '\n' + 'AAAAéAAA\n' + END + '\n',
            'empty': '',
            'none': None,
            'int': 5,
        }
        for name, arm in cases.items():
            ok, why = self.verify(arm)
            self.assertFalse(ok, name)
            self.assertTrue(why, name)

    def test_bytes_armor_is_accepted_and_trailing_newline_optional(self):
        good = M.sign(self.payload, self.key)
        self.assertTrue(self.verify(good.encode())[0])
        self.assertTrue(self.verify(good.rstrip('\n'))[0])

    def test_bad_base64_content_is_rejected_by_the_tool(self):
        ok, why = self.verify(BEGIN + '\n' + 'AAAA\n' + END + '\n')
        self.assertFalse(ok)
        self.assertTrue(why)

    def test_armor_from_message(self):
        good = M.sign(self.payload, self.key)
        arm, why = M.armor_from_message('Marshal feat rev 3\n\n' + good)
        self.assertEqual((arm.strip(), why), (good.strip(), ''))
        self.assertTrue(self.verify(arm)[0])
        for bad in ('no signature here\n', 'x\n\n' + good + good, 'x' * (M.MAX_MESSAGE + 1), 'x\n' + BEGIN + '\nAAAA\n', 'x\n' + END + '\n' + good,
                    'x\n' + good + '\n' + BEGIN + '\n', 5, None, 'x\n' + BEGIN + '\n' + END + '\n'):
            arm, why = M.armor_from_message(bad)
            self.assertEqual(arm, '', repr(bad)[:40])
            self.assertTrue(why)

    def test_message_may_be_bytes(self):
        good = M.sign(self.payload, self.key)
        self.assertEqual(M.armor_from_message(('s\n\n' + good).encode())[1], '')


class Timeout(Base):
    def test_slow_tool_is_killed(self):
        slow = self.fake('exec sleep 30\n')
        arm = M.sign(self.payload, self.key)
        with env(QARGI_MARSHAL_KEYGEN=slow, QARGI_MARSHAL_SIGN_TIMEOUT='0.5'):
            ok, why = M.verify(self.payload, arm, self.signers, 'alice@laptop')
            self.assertFalse(ok)
            self.assertIn('timed out', why)
            with self.assertRaises(M.SignError) as c:
                M.sign(self.payload, self.key)
            self.assertIn('timed out', str(c.exception))

    def test_missing_tool(self):
        arm = M.sign(self.payload, self.key)
        with env(QARGI_MARSHAL_KEYGEN=os.path.join(self.tmp, 'absent')):
            ok, why = M.verify(self.payload, arm, self.signers, 'alice@laptop')
            self.assertFalse(ok)
            self.assertTrue(why)
            with self.assertRaises(M.SignError):
                M.sign(self.payload, self.key)

    def test_tool_that_prints_junk_does_not_pass(self):
        junk = self.fake('cat >/dev/null\necho Good signature for anyone\nexit 0\n')
        arm = M.sign(self.payload, self.key)
        with env(QARGI_MARSHAL_KEYGEN=junk):
            # find-principals prints nothing the signer matches
            self.assertFalse(M.verify(self.payload, arm, self.signers, 'alice@laptop')[0])
            with self.assertRaises(M.SignError):
                M.sign(self.payload, self.key)


class Argv(Base):
    def test_private_key_never_in_argv(self):
        log = os.path.join(self.tmp, 'argv.log')
        spy = self.fake('for a in "$@"; do echo "$a" >> %s; done\necho SEPARATOR >> %s\nexec %s "$@"\n' % (log, log, REAL))
        with open(self.key) as f:
            secret = [ln.strip() for ln in f if ln.strip() and not ln.startswith('-----')]
        self.assertTrue(secret)
        with env(QARGI_MARSHAL_KEYGEN=spy):
            arm = M.sign(self.payload, self.key)
            self.assertTrue(M.verify(self.payload, arm, self.signers, 'alice@laptop')[0])
        with open(log) as f:
            logged = f.read()
        self.assertIn(os.path.abspath(self.key), logged)  # the path is passed, never the contents
        for piece in secret:
            self.assertNotIn(piece, logged)
        self.assertNotIn(self.payload.decode(), logged)
        self.assertNotIn(arm.splitlines()[1], logged)


class Signers(Base):
    def test_add_list_remove(self):
        key2 = os.path.join(self.tmp, 'key2')
        line2 = M.keygen(key2, 'bob@desk')
        M.signers_add(self.signers, line2)
        self.assertEqual([p for p, _, _ in M.signers_list(self.signers)], ['alice@laptop', 'bob@desk'])
        self.assertEqual(stat.S_IMODE(os.stat(self.signers).st_mode), 0o600)
        self.assertTrue(M.signers_remove(self.signers, 'alice@laptop'))
        self.assertFalse(M.signers_remove(self.signers, 'alice@laptop'))
        self.assertEqual([p for p, _, _ in M.signers_list(self.signers)], ['bob@desk'])
        self.assertEqual(M.signers_list(os.path.join(self.tmp, 'absent')), [])
        self.assertEqual(os.listdir(os.path.dirname(self.signers)), ['proj.signers'])  # no temp file left behind

    def test_add_refuses_what_is_not_a_signer_line(self):
        key = M.signers_list(self.signers)[0][2]
        bad = ('', 'alice@laptop ssh-ed25519 ' + key, '-x namespaces="qargi-marshal" ssh-ed25519 ' + key,
               'x@y namespaces="*" ssh-ed25519 ' + key, 'x@y namespaces="qargi-marshal" ssh-rsa ' + key,
               'x@y namespaces="qargi-marshal" ssh-ed25519 ' + key + '\nz@y namespaces="qargi-marshal" ssh-ed25519 ' + key,
               'x@y namespaces="qargi-marshal",cert-authority ssh-ed25519 ' + key, 'x@y namespaces="qargi-marshal" ssh-ed25519 !!', None)
        for b in bad:
            with self.assertRaises(M.SignError, msg=repr(b)):
                M.signers_add(self.signers, b)
        with self.assertRaises(M.SignError):
            M.signers_add(self.signers, self.line)  # the principal is already there: remove it first
        self.assertEqual(len(M.signers_list(self.signers)), 1)

    def test_remove_keeps_every_other_line(self):
        with open(self.signers, 'a') as f:
            f.write('# kept comment\n')
        M.signers_add(self.signers, M.keygen(os.path.join(self.tmp, 'k2'), 'bob@desk'))
        M.signers_remove(self.signers, 'bob@desk')
        with open(self.signers) as f:
            self.assertEqual(f.read(), self.line + '\n# kept comment\n')

    def test_symlinked_signers_file_is_refused(self):
        link = os.path.join(self.tmp, 'link.signers')
        os.symlink(self.signers, link)
        with self.assertRaises(M.SignError):
            M.signers_add(link, M.keygen(os.path.join(self.tmp, 'k2'), 'bob@desk'))
        with self.assertRaises(M.SignError):
            M.signers_remove(link, 'alice@laptop')
        with self.assertRaises(M.SignError):
            M.signers_list(link)
        self.assertTrue(os.path.islink(link))

    def test_remove_principal_must_be_an_id(self):
        for bad in ('-x', '', 'a b', None):
            with self.assertRaises(M.SignError, msg=repr(bad)):
                M.signers_remove(self.signers, bad)


class HighWater(unittest.TestCase):
    """The accepted high-water mark: {name: [rev, oid]}. Ancestry is the caller's git question, injected here."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='hwm.')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = os.path.join(self.tmp, 'features', '.accepted-proj.json')
        self.edges = {(OID1, OID2), (OID2, OID3), (OID1, OID3)}  # ancestor -> descendant

    def anc(self, a, b):
        return (a, b) in self.edges

    def check(self, rev, oid, name='feat'):
        return M.hw_check(M.hw_load(self.path), name, rev, oid, self.anc)

    def test_no_mark_trusts_what_it_first_sees(self):
        self.assertEqual(M.hw_load(self.path), {})
        self.assertEqual(self.check(7, OID3), (True, ''))

    def test_record_and_load(self):
        self.assertTrue(M.hw_record(self.path, 'feat', 2, OID2))
        self.assertEqual(M.hw_load(self.path), {'feat': [2, OID2]})
        self.assertEqual(stat.S_IMODE(os.stat(self.path).st_mode), 0o600)
        self.assertTrue(M.hw_record(self.path, 'other', 1, OID1))
        self.assertEqual(sorted(M.hw_load(self.path)), ['feat', 'other'])
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.path))), ['.accepted-proj.json'])

    def test_fine_path(self):
        M.hw_record(self.path, 'feat', 2, OID2)
        self.assertEqual(self.check(2, OID2), (True, ''))   # the same record again
        self.assertEqual(self.check(3, OID3), (True, ''))   # a later rev on top of it
        self.assertEqual(self.check(5, OID3), (True, ''))   # skipped revs are fine: the lead was away

    def test_lower_rev_is_a_rollback(self):
        M.hw_record(self.path, 'feat', 4, OID3)
        ok, why = self.check(3, OID2)
        self.assertFalse(ok)
        self.assertIn('rollback detected', why)

    def test_same_rev_other_oid_is_a_rollback(self):
        M.hw_record(self.path, 'feat', 2, OID2)
        ok, why = self.check(2, OID3)
        self.assertFalse(ok)
        self.assertIn('rollback detected', why)

    def test_same_rev_other_oid_but_the_same_record_is_not_a_rollback(self):
        M.hw_record(self.path, 'feat', 2, OID2)
        marks = M.hw_load(self.path)
        self.assertEqual(M.hw_check(marks, 'feat', 2, OID3, self.anc, lambda a, b: (a, b) == (OID2, OID3)), (True, ''))
        ok, why = M.hw_check(marks, 'feat', 2, OID3, self.anc, lambda a, b: False)
        self.assertFalse(ok)
        self.assertIn('rollback detected', why)

        def boom(a, b):
            raise OSError('git is gone')
        self.assertFalse(M.hw_check(marks, 'feat', 2, OID3, self.anc, boom)[0])

    def test_identity_of_a_record_is_what_the_signature_covers(self):
        rec = {'rev': 3, 'feature': 'feat', 'goal': 'g'}
        self.assertEqual(M.record_ident(rec, OID1), M.record_ident(dict(reversed(list(rec.items()))), OID1))
        self.assertNotEqual(M.record_ident(rec, OID1), M.record_ident(rec, OID2))
        self.assertNotEqual(M.record_ident(rec, OID1), M.record_ident(dict(rec, goal='h'), OID1))
        self.assertEqual(M.record_ident(rec, None)[0], 3)
        for bad in ({'goal': 'g'}, {'rev': -1}, {'rev': True}, {'rev': 1, 'x': 0.5}, None):
            self.assertIsNone(M.record_ident(bad, None))

    def test_non_ancestor_is_a_rollback(self):
        M.hw_record(self.path, 'feat', 2, OID2)
        ok, why = M.hw_check(M.hw_load(self.path), 'feat', 3, OID3, lambda a, b: False)
        self.assertFalse(ok)
        self.assertIn('rollback detected', why)

    def test_ancestry_callback_that_fails_is_a_rollback(self):
        M.hw_record(self.path, 'feat', 2, OID2)

        def boom(a, b):
            raise OSError('git is gone')
        ok, why = M.hw_check(M.hw_load(self.path), 'feat', 3, OID3, boom)
        self.assertFalse(ok)
        self.assertIn('rollback detected', why)

    def test_other_features_are_independent(self):
        M.hw_record(self.path, 'feat', 9, OID3)
        self.assertEqual(self.check(1, OID1, 'other'), (True, ''))

    def test_record_never_moves_a_mark_back(self):
        M.hw_record(self.path, 'feat', 4, OID3)
        self.assertFalse(M.hw_record(self.path, 'feat', 3, OID2))
        self.assertFalse(M.hw_record(self.path, 'feat', 4, OID2))
        self.assertTrue(M.hw_record(self.path, 'feat', 4, OID3))
        self.assertEqual(M.hw_load(self.path), {'feat': [4, OID3]})

    def test_drop(self):
        M.hw_record(self.path, 'feat', 4, OID3)
        M.hw_record(self.path, 'other', 1, OID1)
        self.assertTrue(M.hw_drop(self.path, 'feat'))
        self.assertFalse(M.hw_drop(self.path, 'feat'))
        self.assertEqual(M.hw_load(self.path), {'other': [1, OID1]})

    def test_bad_arguments(self):
        for args in (('Feat', 1, OID1), ('feat', -1, OID1), ('feat', True, OID1), ('feat', 1, 'xyz'), ('', 1, OID1), ('feat', 1.5, OID1)):
            with self.assertRaises(ValueError, msg=repr(args)):
                M.hw_record(self.path, *args)
            with self.assertRaises(ValueError, msg=repr(args)):
                M.hw_check({}, args[0], args[1], args[2], self.anc)

    def test_a_damaged_file_is_an_error_not_an_empty_mark(self):
        os.makedirs(os.path.dirname(self.path))
        for junk in ('{', '[]', '{"feat": [1]}', '{"feat": [1, "zz"]}', '{"feat": [-1, "%s"]}' % OID1, '{"Bad Name": [1, "%s"]}' % OID1, '\x00'):
            with open(self.path, 'w') as f:
                f.write(junk)
            with self.assertRaises(M.SignError, msg=junk):
                M.hw_load(self.path)
            with self.assertRaises(M.SignError, msg=junk):
                M.hw_record(self.path, 'feat', 1, OID1)

    def test_a_symlinked_file_is_refused(self):
        M.hw_record(self.path, 'feat', 2, OID2)
        link = os.path.join(self.tmp, 'link.json')
        os.symlink(self.path, link)
        with self.assertRaises(M.SignError):
            M.hw_load(link)
        with self.assertRaises(M.SignError):
            M.hw_record(link, 'feat', 3, OID3)


class Cli(unittest.TestCase):
    """python3 -I lib/marshal_sign.py ...: what the shell calls."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='signcli.')
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.key = os.path.join(self.tmp, 'cred', 'k')
        self.signers = os.path.join(self.tmp, 'p.signers')

    def run_cli(self, *args, stdin=b''):
        r = subprocess.run([sys.executable, '-I', os.path.join(LIB, 'marshal_sign.py')] + list(args), input=stdin, capture_output=True, timeout=60,
                           env=dict(os.environ))
        return r.returncode, r.stdout, r.stderr.decode()

    def test_whole_flow(self):
        rc, out, err = self.run_cli('keygen', '--key', self.key, '--principal', 'alice@laptop')
        self.assertEqual((rc, err), (0, ''))
        line = out.decode().strip()
        self.assertRegex(line, r'^alice@laptop namespaces="qargi-marshal" ssh-ed25519 ')
        self.assertEqual(self.run_cli('signers', 'add', '--file', self.signers, '--line', line)[0], 0)
        rc, out, _ = self.run_cli('signers', 'list', '--file', self.signers)
        self.assertEqual((rc, out.decode().split()[0]), (0, 'alice@laptop'))
        rec = os.path.join(self.tmp, 'rec.json')
        with open(rec, 'w') as f:
            json.dump({'feature': 'feat', 'sig_v': 1, 'signer': 'alice@laptop'}, f)
        rc, payload, err = self.run_cli('payload', '--project', 'proj', '--feature', 'feat', '--kind', 'features', '--rev', '3', '--parent', OID1,
                                        '--lead', 'l-1', '--record', rec)
        self.assertEqual((rc, err), (0, ''))
        self.assertEqual(payload, M.signed_payload('proj', 'feat', 'features', 3, OID1, 'l-1', {'feature': 'feat', 'sig_v': 1, 'signer': 'alice@laptop'}))
        rc, arm, err = self.run_cli('sign', '--key', self.key, stdin=payload)
        self.assertEqual((rc, err), (0, ''))
        sig = os.path.join(self.tmp, 'sig')
        with open(sig, 'wb') as f:
            f.write(arm)
        rc, _, err = self.run_cli('verify', '--signers', self.signers, '--principal', 'alice@laptop', '--sig', sig, stdin=payload)
        self.assertEqual((rc, err), (0, ''))
        rc, _, err = self.run_cli('verify', '--signers', self.signers, '--principal', 'alice@laptop', '--sig', sig, stdin=payload + b' ')
        self.assertEqual(rc, 1)
        self.assertTrue(err.strip())
        self.assertEqual(self.run_cli('signers', 'remove', '--file', self.signers, '--principal', 'alice@laptop')[0], 0)
        self.assertEqual(self.run_cli('signers', 'list', '--file', self.signers)[1], b'')
        rc, _, err = self.run_cli('verify', '--signers', self.signers, '--principal', 'alice@laptop', '--sig', sig, stdin=payload)
        self.assertEqual(rc, 1)

    def test_a_wrong_call_is_status_2_with_a_message(self):
        for args in ((), ('nonsense',), ('sign',), ('sign', '--key', os.path.join(self.tmp, 'absent')), ('signers',), ('signers', 'add', '--file', self.signers),
                     ('signers', 'add', '--file', self.signers, '--line', 'junk'), ('keygen', '--key', self.key, '--principal', '-x'),
                     ('verify', '--signers', self.signers, '--principal', 'a@b', '--sig', os.path.join(self.tmp, 'absent'))):
            rc, out, err = self.run_cli(*args, stdin=b'payload')
            self.assertEqual(rc, 2, repr(args))
            self.assertEqual(out, b'', repr(args))
            self.assertTrue(err.strip(), repr(args))
            self.assertNotIn('Traceback', err, repr(args))

    def test_payload_refuses_a_float_record(self):
        rec = os.path.join(self.tmp, 'rec.json')
        with open(rec, 'w') as f:
            f.write('{"a": 1.5}')
        rc, out, err = self.run_cli('payload', '--project', 'p', '--feature', 'f', '--kind', 'done', '--rev', '1', '--record', rec)
        self.assertEqual((rc, out), (2, b''))
        self.assertIn('float', err)


if __name__ == '__main__':
    unittest.main()
