#!/usr/bin/env python3
"""Signed marshal records: the signed payload, the signature (OpenSSH, one ed25519 key per lead machine), the allowed signers
file and the accepted high-water mark.

Signing makes a forged or altered record detectable; it cannot stop a deletion or a rewind (the high-water mark makes a rewind
detectable on a machine that has seen the newer record). Standard library plus the OpenSSH key tool, started with an argument
list (never a shell), with a timeout, in a scratch directory of mode 0700. The private key is only ever named by its path.

  canonical_json(obj)          bytes: sorted keys, separators (',', ':'), ASCII only; a float, a non-string key or a type JSON has
                               no form for raises ValueError
  signed_payload(project, feature, kind, rev, parent, lead, record) -> bytes  the bytes that are signed; a reader rebuilds them
                               from the commit and the record every time, nothing of them is stored
  sign(payload, keyfile, ns)   armored signature text (SignError when it cannot sign)
  verify(payload, armored, signers_file, principal, ns) -> (ok, why)  never raises
  armor_from_message(message)  the one signature block of a commit message -> (armor, why)
  keygen(keyfile, principal)   a new ed25519 key (0600, never overwrites) -> the allowed signers line
  signers_add(file, line) / signers_remove(file, principal) / signers_list(file)   atomic edits of the allowed signers file
  hw_load(file) / hw_record(file, name, rev, oid) / hw_check(marks, name, rev, oid, is_ancestor) / hw_drop(file, name)
                               the accepted high-water mark {name: [rev, oid]}

Environment: QARGI_MARSHAL_KEYGEN the key tool (default ssh-keygen; tests inject a fake); QARGI_MARSHAL_SIGN_TIMEOUT seconds
for one call of it (default 10).

Command line (the shell and the tests; python3 -I, standard library only):
  keygen --key F [--principal P]                         create the key, print the signers line
  sign --key F [--ns NS]                                 payload on stdin, armored signature on stdout
  verify --signers F --principal P --sig FILE [--ns NS]  payload on stdin; exit 0 ok, 1 not verified (why on stderr)
  signers add --file F --line L | remove --file F --principal P | list --file F
Exit status 2: the call itself is wrong (message on stderr)."""
import getpass, hashlib, json, os, re, shutil, signal, socket, stat, subprocess, tempfile

NS = 'qargi-marshal'
PAYLOAD_V = 1
KINDS = ('features', 'done')
MAX_ARMOR = 2048          # the signature block
MAX_MESSAGE = 8192        # a commit message with a signature in it; also the largest payload
MAX_FILE = 1024 * 1024    # a signers file or a high-water mark file
PRINCIPAL_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._+@-]{0,127}')
NS_RE = re.compile(r'[a-z0-9][a-z0-9.-]{0,63}')
OID_RE = re.compile(r'[0-9a-f]{40}([0-9a-f]{24})?')
NAME_RE = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*')
B64_RE = re.compile(r'[A-Za-z0-9+/]+={0,2}')
BEGIN = '-----BEGIN SSH SIGNATURE-----'
END = '-----END SSH SIGNATURE-----'
SIGNER_RE = re.compile(r'(?P<p>%s) namespaces="%s" (?P<t>ssh-ed25519) (?P<k>[A-Za-z0-9+/]+={0,2})(?: [^\x00-\x1f\x7f]*)?' % (PRINCIPAL_RE.pattern, NS))


class SignError(Exception):
    """A signing, key or file operation that could not be done; the message says why."""


def principal_ok(p):
    return isinstance(p, str) and PRINCIPAL_RE.fullmatch(p) is not None


def timeout_secs():
    try:
        t = float(os.environ.get('QARGI_MARSHAL_SIGN_TIMEOUT', '10'))
    except ValueError:
        return 10.0
    return t if t > 0 else 10.0


# ---- the signed payload --------------------------------------------------------------------------------------------

def _check_json(v, depth=0):
    if depth > 20:
        raise ValueError('nested too deeply')
    if v is None or isinstance(v, (bool, int, str)):
        return
    if isinstance(v, float):
        raise ValueError('a float has no canonical form here')
    if isinstance(v, (list, tuple)):
        for x in v:
            _check_json(x, depth + 1)
    elif isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                raise ValueError('a key that is not a string')
            _check_json(x, depth + 1)
    else:
        raise ValueError('%s has no JSON form' % type(v).__name__)


def canonical_json(obj):
    """The one byte form of a JSON value that is signed."""
    _check_json(obj)
    return json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def signed_payload(project, feature, kind, rev, parent, lead, record):
    """The bytes a record's signature covers: the record's digest and everything that places it (project, feature, ref kind, rev,
    the parent commit it sits on, the lead). `record` is the whole record including its sig_v and signer."""
    if not isinstance(project, str) or not isinstance(feature, str):
        raise ValueError('project and feature are strings')
    if kind not in KINDS:
        raise ValueError('kind is features or done')
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        raise ValueError('rev is a non-negative integer')
    if parent is not None and not (isinstance(parent, str) and OID_RE.fullmatch(parent)):
        raise ValueError('parent is a commit id or null')
    if lead is not None and not isinstance(lead, str):
        raise ValueError('lead is a string or null')
    if not isinstance(record, dict):
        raise ValueError('record is an object')
    return canonical_json({'v': PAYLOAD_V, 'ns': NS, 'project': project, 'feature': feature, 'kind': kind, 'rev': rev,
                           'parent': parent, 'lead': lead, 'record_sha256': hashlib.sha256(canonical_json(record)).hexdigest()})


# ---- armor ---------------------------------------------------------------------------------------------------------

def parse_armor(armored):
    """The one SSH signature block in `armored` (str or bytes), checked and normalised -> (text ending in a newline, "") or
    ("", why). Exactly one block and nothing else; the body is base64 only; at most MAX_ARMOR bytes."""
    if isinstance(armored, (bytes, bytearray)):
        try:
            armored = bytes(armored).decode('ascii')
        except UnicodeDecodeError:
            return '', 'the signature is not ASCII'
    if not isinstance(armored, str) or not armored:
        return '', 'no signature'
    if len(armored) > MAX_ARMOR:
        return '', 'the signature is over %d bytes' % MAX_ARMOR
    if not all(c == '\n' or ' ' <= c <= '~' for c in armored):
        return '', 'the signature has a control or non-ASCII character'
    if armored.count(BEGIN) != 1 or armored.count(END) != 1:
        return '', 'the signature is not exactly one block'
    lines = armored.split('\n')
    if lines and lines[-1] == '':
        lines.pop()
    if len(lines) < 3 or lines[0] != BEGIN or lines[-1] != END:
        return '', 'the signature is not exactly one block'
    if not all(B64_RE.fullmatch(ln) for ln in lines[1:-1]):
        return '', 'the signature body is not base64'
    return '\n'.join(lines) + '\n', ''


def armor_from_message(message):
    """The signature block of a commit message -> (armor, "") or ("", why): the message is at most MAX_MESSAGE bytes and holds
    exactly one BEGIN and one END line; whatever else it says (a subject) is ignored."""
    if isinstance(message, (bytes, bytearray)):
        message = bytes(message).decode('utf-8', 'replace')
    if not isinstance(message, str):
        return '', 'no message'
    if len(message.encode('utf-8', 'replace')) > MAX_MESSAGE:
        return '', 'the commit message is over %d bytes' % MAX_MESSAGE
    if message.count(BEGIN) != 1 or message.count(END) != 1:
        return '', 'the commit message does not hold exactly one signature block'
    a = message.index(BEGIN)
    b = message.index(END)
    if b < a:
        return '', 'the commit message does not hold exactly one signature block'
    return parse_armor(message[a:b + len(END)] + '\n')


# ---- the key tool --------------------------------------------------------------------------------------------------

def keygen_bin():
    return os.environ.get('QARGI_MARSHAL_KEYGEN') or 'ssh-keygen'


def _run(args, data=None):
    """The key tool with ARGS -> (returncode, stdout bytes, stderr text, timed_out). No shell, no agent, no terminal, a timeout
    that kills the whole process group."""
    env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C', 'LC_ALL': 'C'}
    try:
        p = subprocess.Popen([keygen_bin()] + list(args), stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    except OSError as e:
        return 127, b'', 'cannot run the key tool: %s' % e, False
    t = timeout_secs()
    try:
        out, err = p.communicate(data, timeout=t)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        for f in (p.stdin, p.stdout, p.stderr):
            try:
                if f:
                    f.close()
            except OSError:
                pass
        return 124, b'', 'timed out after %g s' % t, True
    except OSError as e:  # the tool closed its input early
        return 126, b'', 'the key tool failed: %s' % e, False
    return p.returncode, out, err.decode('utf-8', 'replace'), False


def _why(rc, err, timed_out):
    if timed_out:
        return err
    for ln in (err or '').splitlines():
        if ln.strip():
            return ''.join(c for c in ln.strip() if ' ' <= c <= '~')[:200]
    return 'the key tool failed (status %d)' % rc


def _read_regular(path, limit=MAX_FILE):
    """The bytes of a regular file that is not a symlink, at most `limit`. SignError otherwise."""
    try:
        if stat.S_ISLNK(os.lstat(path).st_mode):
            raise SignError('%s is a symlink' % path)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        raise SignError('%s does not exist' % path)
    except OSError as e:
        raise SignError('cannot open %s: %s' % (path, e.strerror))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise SignError('%s is not a regular file' % path)
        data = os.read(fd, limit + 1)
    finally:
        os.close(fd)
    if len(data) > limit:
        raise SignError('%s is over %d bytes' % (path, limit))
    return data


def _atomic_write(path, data):
    """Replace `path` with `data` (mode 0600) by a rename of a temporary file in the same directory. A symlink or a
    non-regular file at `path` is refused."""
    try:
        st = os.lstat(path)
    except FileNotFoundError:
        st = None
    if st is not None and not stat.S_ISREG(st.st_mode):
        raise SignError('%s is not a regular file (or is a symlink)' % path)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix='.' + os.path.basename(path) + '.')
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    try:
        dfd = os.open(d, os.O_RDONLY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        pass


def _ns_ok(ns):
    return isinstance(ns, str) and NS_RE.fullmatch(ns) is not None


def sign(payload, keyfile, ns=NS):
    """Sign `payload` (bytes) with the private key in `keyfile` -> the armored signature text. The key must be a regular file,
    not a symlink, with no group or other access; the tool is given its path, never its contents."""
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > MAX_MESSAGE:
        raise SignError('nothing to sign, or more than %d bytes' % MAX_MESSAGE)
    if not _ns_ok(ns):
        raise SignError('%r is not a namespace' % (ns,))
    keyfile = os.path.abspath(keyfile)
    try:
        st = os.lstat(keyfile)
    except OSError as e:
        raise SignError('cannot use the key %s: %s' % (keyfile, e.strerror))
    if not stat.S_ISREG(st.st_mode):
        raise SignError('the key %s is not a regular file (a symlink is refused)' % keyfile)
    if st.st_mode & 0o077:
        raise SignError('the key %s is accessible to others (mode %o): chmod 600' % (keyfile, stat.S_IMODE(st.st_mode)))
    rc, out, err, to = _run(['-Y', 'sign', '-f', keyfile, '-n', ns], bytes(payload))
    if rc != 0:
        raise SignError('signing failed: ' + _why(rc, err, to))
    arm, why = parse_armor(out)
    if not arm:
        raise SignError('the key tool returned no usable signature: ' + why)
    return arm


def verify(payload, armored, signers_file, principal, ns=NS):
    """Is `armored` a signature over `payload` by the key the signers file lists for `principal`, in namespace `ns`?
    -> (True, "") or (False, why). Never raises: whatever is wrong, hostile or missing is a (False, why)."""
    try:
        return _verify(payload, armored, signers_file, principal, ns)
    except SignError as e:
        return False, str(e)
    except (OSError, ValueError) as e:
        return False, 'cannot verify: %s' % e


def _verify(payload, armored, signers_file, principal, ns):
    if not principal_ok(principal):
        return False, 'the signer %r is not a valid id' % (principal if isinstance(principal, str) and len(principal) < 40 else '...')
    if not _ns_ok(ns):
        return False, '%r is not a namespace' % (ns,)
    if not isinstance(payload, (bytes, bytearray)) or not payload or len(payload) > MAX_MESSAGE:
        return False, 'the signed payload is empty or over %d bytes' % MAX_MESSAGE
    arm, why = parse_armor(armored)
    if not arm:
        return False, why
    signers = _read_regular(signers_file)  # a copy is verified against: the file cannot change between the two calls
    d = tempfile.mkdtemp(prefix='marshal-sign.')
    try:
        os.chmod(d, 0o700)
        sig = os.path.join(d, 'sig')
        sf = os.path.join(d, 'signers')
        for path, content in ((sig, arm.encode('ascii')), (sf, signers)):
            with open(path, 'wb') as f:
                f.write(content)
        rc, out, err, to = _run(['-Y', 'find-principals', '-f', sf, '-s', sig])
        if rc != 0:
            return False, 'no allowed signer matches this signature' if not to else err
        found = [ln.strip() for ln in out.decode('utf-8', 'replace').splitlines() if ln.strip()]
        if found != [principal]:
            return False, 'the signature is not by %s' % principal
        rc, out, err, to = _run(['-Y', 'verify', '-f', sf, '-I', principal, '-n', ns, '-s', sig], bytes(payload))
        if rc != 0:
            return False, 'signature does not verify: ' + _why(rc, err, to)
        return True, ''
    finally:
        shutil.rmtree(d, ignore_errors=True)


# ---- keys and the allowed signers file -----------------------------------------------------------------------------

def default_principal():
    raw = '%s@%s' % (getpass.getuser(), socket.gethostname().split('.')[0])
    p = re.sub(r'[^A-Za-z0-9._+@-]', '-', raw).lstrip('-.@+_')[:128]
    return p or 'lead@machine'


def keygen(keyfile, principal=None):
    """Create an ed25519 key at `keyfile` (mode 0600, no passphrase, `keyfile`.pub beside it) -> the allowed signers line for it.
    An existing file is never overwritten."""
    principal = principal or default_principal()
    if not principal_ok(principal):
        raise SignError('%r is not a valid signer id (letters, digits and . _ + @ -, not starting with -)' % (principal,))
    keyfile = os.path.abspath(keyfile)
    for p in (keyfile, keyfile + '.pub'):
        if os.path.lexists(p):
            raise SignError('%s already exists: it is never overwritten' % p)
    d = os.path.dirname(keyfile)
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = tempfile.mkdtemp(dir=d, prefix='.keygen.')
    try:
        os.chmod(tmp, 0o700)
        priv = os.path.join(tmp, 'key')
        rc, _, err, to = _run(['-q', '-t', 'ed25519', '-N', '', '-C', principal, '-f', priv])
        if rc != 0:
            raise SignError('key generation failed: ' + _why(rc, err, to))
        parts = _read_regular(priv + '.pub', 4096).decode('ascii', 'replace').split()
        if len(parts) < 2 or parts[0] != 'ssh-ed25519' or not B64_RE.fullmatch(parts[1]):
            raise SignError('the key tool made no ed25519 public key')
        os.chmod(priv, 0o600)
        try:
            os.link(priv, keyfile)  # fails when it exists: no overwrite, even in a race
            os.link(priv + '.pub', keyfile + '.pub')
        except FileExistsError:
            raise SignError('%s already exists: it is never overwritten' % keyfile)
        except OSError as e:
            raise SignError('cannot place the key: %s' % e.strerror)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return '%s namespaces="%s" ssh-ed25519 %s' % (principal, NS, parts[1])


def _signer_lines(path):
    """(lines of the file, kept as written) or [] when there is no file."""
    try:
        data = _read_regular(path)
    except SignError as e:
        if not os.path.lexists(path):
            return []
        raise e
    return data.decode('utf-8', 'replace').splitlines()


def _principal_of(line):
    m = SIGNER_RE.fullmatch(line)
    return m.group('p') if m else None


def signers_list(path):
    """[(principal, keytype, key)] of the lines in the file that are in our format; other lines are left out."""
    out = []
    for ln in _signer_lines(path):
        m = SIGNER_RE.fullmatch(ln)
        if m:
            out.append((m.group('p'), m.group('t'), m.group('k')))
    return out


def signers_add(path, line):
    """Add one signers line (`PRINCIPAL namespaces="qargi-marshal" ssh-ed25519 KEY`). A principal that is already listed is an
    error: remove it first (a key is replaced, never silently). Atomic."""
    if not isinstance(line, str) or not SIGNER_RE.fullmatch(line.strip()):
        raise SignError('not a signers line: PRINCIPAL namespaces="%s" ssh-ed25519 KEY' % NS)
    line = line.strip()
    lines = _signer_lines(path)
    who = SIGNER_RE.fullmatch(line).group('p')
    if any(_principal_of(x) == who for x in lines):
        raise SignError('%s is already listed: remove it first' % who)
    _atomic_write(path, ('\n'.join(lines + [line]) + '\n').encode('utf-8'))


def signers_remove(path, principal):
    """Drop every line of `principal` (a revoked key); every other line is kept as written. -> True when there was one."""
    if not principal_ok(principal):
        raise SignError('%r is not a valid signer id' % (principal,))
    lines = _signer_lines(path)
    keep = [x for x in lines if _principal_of(x) != principal]
    if len(keep) == len(lines):
        return False
    _atomic_write(path, (('\n'.join(keep) + '\n') if keep else '').encode('utf-8'))
    return True


# ---- the accepted high-water mark ----------------------------------------------------------------------------------
# $DA_STATE/features/.accepted-<project>.json: {name: [rev, oid]}, the newest record this machine has accepted for each
# feature. A record whose rev is lower, or whose rev is the same with another oid, or that does not descend from the accepted
# oid, is a rollback. A machine with no mark yet trusts what it first sees.

def _mark_args(name, rev, oid):
    if not (isinstance(name, str) and 0 < len(name) <= 40 and NAME_RE.fullmatch(name)):
        raise ValueError('%r is not a feature name' % (name,))
    if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
        raise ValueError('rev is a non-negative integer')
    if not (isinstance(oid, str) and OID_RE.fullmatch(oid)):
        raise ValueError('oid is a commit id')


def hw_load(path):
    """The marks -> {name: [rev, oid]}; {} when there is no file. A file that is damaged (or a symlink) raises SignError: it is
    never read as an empty mark, which would switch the protection off."""
    if not os.path.lexists(path):
        return {}
    data = _read_regular(path)
    try:
        d = json.loads(data.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise SignError('%s is not valid JSON' % path)
    if not isinstance(d, dict):
        raise SignError('%s is not a JSON object' % path)
    out = {}
    for name, v in d.items():
        try:
            if not (isinstance(v, list) and len(v) == 2):
                raise ValueError('not a pair')
            _mark_args(name, v[0], v[1])
        except ValueError:
            raise SignError('%s holds a bad entry for %r' % (path, name if isinstance(name, str) and len(name) < 60 else '...'))
        out[name] = [v[0], v[1]]
    return out


def _hw_save(path, marks):
    _atomic_write(path, (json.dumps(marks, sort_keys=True, indent=1) + '\n').encode('ascii'))


def hw_record(path, name, rev, oid):
    """Accept (rev, oid) for `name`: True when the mark is now that. A mark never moves backward: a lower rev, or the same rev
    with another oid, is left alone and gives False (hw_check is what says why). Atomic."""
    _mark_args(name, rev, oid)
    marks = hw_load(path)
    cur = marks.get(name)
    if cur is not None:
        if rev < cur[0] or (rev == cur[0] and oid != cur[1]):
            return False
        if cur == [rev, oid]:
            return True
    marks[name] = [rev, oid]
    _hw_save(path, marks)
    return True


def hw_drop(path, name):
    """Forget `name` (its feature is done and the done record was seen). -> True when there was a mark."""
    marks = hw_load(path)
    if name not in marks:
        return False
    del marks[name]
    _hw_save(path, marks)
    return True


def hw_check(marks, name, rev, oid, is_ancestor):
    """May the record (rev, oid) of `name` be accepted, given `marks` (hw_load)? -> (True, "") or (False, "rollback detected: ...").
    is_ancestor(accepted_oid, oid) answers the git question (merge-base --is-ancestor); one that raises or says no is a rollback."""
    _mark_args(name, rev, oid)
    cur = marks.get(name)
    if cur is None:
        return True, ''
    arev, aoid = cur
    if rev < arev:
        return False, 'rollback detected: %s is at rev %d, rev %d was accepted before' % (name, rev, arev)
    if rev == arev:
        if oid == aoid:
            return True, ''
        return False, 'rollback detected: %s rev %d is a different record than the one accepted' % (name, rev)
    try:
        ok = bool(is_ancestor(aoid, oid))
    except Exception:
        ok = False
    if not ok:
        return False, 'rollback detected: %s rev %d does not descend from the accepted rev %d' % (name, rev, arev)
    return True, ''
