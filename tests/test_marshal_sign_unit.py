#!/usr/bin/env python3
"""lib/marshal_sign.py: the signed payload, the signature round trip with the real OpenSSH key tool, hostile armor, the signers
file and the accepted high-water mark. Offline. Skips (with a message) when the key tool is not installed.
Run: python3 tests/test_marshal_sign_unit.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import contextlib, json, os, shutil, stat, sys, tempfile, unittest

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


if __name__ == '__main__':
    unittest.main()
