#!/usr/bin/env python3
"""Lead-owned lifecycle authority for prepared local runs.

Store(run) selects the lead's root with paths.state(), never from RUN. The exact
registry lifecycle:1 marker authorizes reads/transitions; absent means Legacy,
even if a state directory happens to exist. init() is the sole exception: prepare
must call it under the lock BEFORE publishing the registry marker. closed/cleaned
remain registry authority; apply records remain the integration caller's concern.

All transitions require an already exclusively locked fd 7 for this run. Shell
lc_lock acquires it; Python callers can open_lock(), dup2 to 7, then flock EX|NB.
No environment variable grants entry. Lock order: lifecycle, apply pid lock,
short leaf locks. Children that need no authority MUST use close_fds=True (shell:
7>&-), especially members, scrub/git and marshal background hold renewers.

API (snapshots are bounded bytes, never filenames supplied by the member):
  init(refs, epoch=, base=, base_sha=) -> initial state; exclusive creation
  show() -> validated record, including hashes of every referenced snapshot
  gate() -> baseline name/hash, epoch and strict/after-verify comparison phase
  gate_pending(refs, epoch=, owner_pid=None) -> bounded, state-bound plan owned
                 by this process, or a bounded ancestor before shell exec
  begin(pending, refs) -> commit dispatch before accepted output mutation; consumes plan once
  member(pid) -> record a newly spawned child/session leader (pid == pgid)
  end(outcome) -> owner records completion after its member group is gone
  reconcile() -> refuse live/unknown dispatch, mark a dead dispatch lost, retain
                 stale saved copies; idempotent after interrupted begin/verify
  prepare_save() -> retain the old copy, commit and return a fresh marker
  verified(refs) -> commit verification AFTER installing the prepared copy
  saved_copy() -> current verified saved path with the exact attempt marker
  drop() -> after registry cleaned/drop commit; remove state, KEEP lock inode

Gate comparison belongs to local.sh: compare against the baseline
and phase returned by gate(), and only call gate_pending with an accepted lead
snapshot. It does not prove a git comparison. begin attaches to the first unused
attempt, otherwise opens a strict attempt whose epoch is the accepted gate time.
Prepared refs/epoch/base SHA never change. Pending plans are not authority files.

Records commit by fsync + atomic rename, mode 600 inside mode 700 directories.
Snapshots are immutable; verified snapshots are hash named. Failure before record replacement
leaves no new authority. Retention commits before dispatch. A rename interrupted before its record commit
is recovered by reconcile. Directory fsync failure after atomic replacement is
treated as committed, though persistence across power loss is not guaranteed.
Under the lock, reconcile first, then call prepare_save before each save. Build
the copy in a private temporary directory on the same filesystem, write its
returned marker as mode 600, chmod the directory 700, and rename it to runs/ID.
Only then verify and call verified(refs). Never use a member-provided marker.
Interrupted retention is recovered by reconcile; retry drop after interrupted
cleanup. Post-effect directory fsync failures warn without undoing the effect.
Retention and verification history are bounded to 32 per attempt; base names
are bounded to 1024 UTF-8 bytes without C0 controls or DEL; caller validates Git refs.
Never infer verification from RUN, saved output, or an orphaned snapshot.
The integration caller clears registry/RUN verification mirrors after begin's
commit; reg_del is a leaf operation under this lock. It must use record snapshots
for verification, including --saved, rather than saved/member-writable refs.
Liveness covers the recorded Linux process group only, not escaped descendants;
missing platform evidence is an error, not proof of death.

CLI: COMMAND RUN; mutations consume one bounded JSON object on stdin (refs is a
UTF-8 string). init: refs/epoch/base/base_sha; gate-pending: refs/epoch; begin:
pending/refs; member: pid; end: outcome; verified: refs. Other verbs take no input.
CLI gate-pending defaults to its parent; in a pipeline/command substitution pass
owner_pid=$$ explicitly in the JSON so the shell can exec the Python runtime
which imports begin/member/end. Those owner-sensitive APIs must execute in the
runner itself, not one-shot subprocesses with different process identities.
lock-open is a shell-only handshake: prints /proc/PID/fd/N of a safely opened
regular lock, then waits for one input byte so bash can duplicate that inode.
lock-match checks fd identity; lock-check proves the inherited exclusive lock.
Errors exit 1 with qargi: diagnostics; successful JSON goes to stdout.
"""
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths
from procenv import now

MAX_RECORD = 256 * 1024
DISPATCH_HEADROOM = 1024
MAX_REFS = 1024 * 1024
MAX_REGISTRY = 8 * 1024 * 1024
MAX_ATTEMPTS = 256
MAX_SAVED = 32
MAX_VERIFICATIONS = 32
MAX_EPOCH = 253402300799
NOFOLLOW = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class Refuse(Exception):
    """No trusted transition is possible."""


class Legacy(Refuse):
    """Registry explicitly has no lifecycle marker; no automatic adoption."""


def need(ok, message):
    if not ok:
        raise Refuse(message)


def integer(value, lo=1, hi=MAX_ATTEMPTS):
    return type(value) is int and lo <= value <= hi


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _pairs(pairs):
    obj = {}
    for key, value in pairs:
        need(key not in obj, "duplicate JSON key")
        obj[key] = value
    return obj


def decode(data):
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: need(False, "invalid JSON constant"))
    except (ValueError, RecursionError, UnicodeError) as e:
        raise Refuse("malformed lifecycle JSON") from e


def shape(value, keys):
    need(type(value) is dict and set(value) == set(keys.split()), "invalid lifecycle fields")


def stamp(value):
    need(isinstance(value, str) and re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", value, flags=re.ASCII), "invalid timestamp")
    # strptime accepts some non-calendar values (leap seconds); schema uses UTC seconds.
    import datetime
    try:
        datetime.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as e:
        raise Refuse("invalid timestamp") from e


def canonical(path):
    need(isinstance(path, str) and len(os.fsencode(path)) <= 4096 and "\0" not in path
         and path.startswith("/") and not path.startswith("//")
         and os.path.normpath(path) == path and os.path.realpath(path) == path,
         "expected a canonical absolute path without symlinks")
    return path


def private(st, mode):
    need(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == mode,
         "lifecycle state must be lead-owned with private permissions")


def sync_dir(fd, effect):
    try:
        os.fsync(fd)
    except OSError as e:
        try:
            print("qargi: lifecycle: warning: %s committed; directory fsync failed: %s" % (effect, e), file=sys.stderr)
        except OSError:
            pass  # The filesystem effect already committed, even if stderr is broken.


def directory(path, create=False, tighten=False):
    """Anchor every component with O_NOFOLLOW; never mkdir through a symlink."""
    path = canonical(path)
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW)
    try:
        for part in path.strip("/").split("/"):
            if not part:
                continue
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if tighten:
            need(os.fstat(fd).st_uid == os.geteuid(), "directory is not lead-owned")
            os.fchmod(fd, 0o700)
        private(os.fstat(fd), 0o700)
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_at(fd, name, limit, mode=None):
    f = os.open(name, os.O_RDONLY | NOFOLLOW, dir_fd=fd)
    try:
        st = os.fstat(f)
        need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_size <= limit,
             "not a bounded plain lifecycle file: " + name)
        if mode is not None:
            private(st, mode)
        data = os.read(f, limit + 1)
        need(len(data) <= limit, "oversized lifecycle file: " + name)
        return data
    finally:
        os.close(f)


def atomic(fd, name, data):
    tmp = ".write." + uuid.uuid4().hex
    f = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | NOFOLLOW, 0o600, dir_fd=fd)
    try:
        with os.fdopen(f, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, name, src_dir_fd=fd, dst_dir_fd=fd)
        sync_dir(fd, "replacement")
    finally:
        try:
            os.unlink(tmp, dir_fd=fd)
        except FileNotFoundError:
            pass


def process(pid):
    """Linux stat identity, ppid and pgid, or None for a proven absent pid."""
    need(integer(pid, 1, 2**31 - 1) and sys.platform.startswith("linux"), "unknown process liveness")
    try:
        with open("/proc/%d/stat" % pid, "rb") as stream:
            data = stream.read(8193)
    except FileNotFoundError:
        need(os.path.isfile("/proc/self/stat"), "unknown process liveness: /proc unavailable")
        return None
    except OSError as e:
        raise Refuse("unknown process liveness") from e
    try:
        need(len(data) <= 8192, "invalid process stat")
        fields = data[data.rindex(b")") + 2:].split()
        need(len(fields) >= 20 and fields[19].isdigit() and len(fields[19]) <= 24
             and fields[1].isdigit() and fields[2].isdigit()
             and 0 <= int(fields[1]) < 2**31 and 0 <= int(fields[2]) < 2**31,
             "unknown process liveness: invalid stat")
        return {"token": str(int(fields[19])), "ppid": int(fields[1]), "pgid": int(fields[2]),
                "state": fields[0].decode("ascii")}
    except (ValueError, IndexError) as e:
        raise Refuse("unknown process liveness: invalid stat") from e


def group_alive(pgid):
    need(integer(pgid, 1, 2**31 - 1) and sys.platform.startswith("linux")
         and os.path.isfile("/proc/self/stat"), "unknown process group liveness")
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except OSError as e:
        raise Refuse("unknown process group liveness") from e
    try:
        for name in os.listdir("/proc"):
            if name.isdigit():
                p = process(int(name))
                if p is not None and p["pgid"] == pgid and p["state"] not in ("Z", "X"):
                    return True
    except OSError as e:
        raise Refuse("unknown process group liveness") from e
    return False


def owner(pid=None):
    pid = os.getpid() if pid is None else pid
    need(integer(pid, 1, 2**31 - 1), "invalid pending owner")
    ancestor = os.getpid()
    for _ in range(8):
        if ancestor == pid:
            break
        p = process(ancestor)
        need(p is not None, "unknown pending owner ancestry")
        ancestor = p["ppid"]
    need(ancestor == pid, "pending owner must be this process or a nearby ancestor")
    p = process(pid)
    need(p is not None, "cannot identify dispatch owner")
    return {"pid": pid, "token": p["token"]}


def identity(value):
    shape(value, "pid token")
    need(integer(value["pid"], 1, 2**31 - 1) and isinstance(value["token"], str)
         and re.fullmatch(r"[0-9]{1,24}", value["token"]), "invalid process identity")


class Store:
    def __init__(self, run):
        self.run = canonical(os.fspath(run))
        self.id = os.path.basename(self.run)
        need(re.fullmatch(r"qargi\.[A-Za-z0-9]{6}", self.id), "invalid lifecycle run id")
        self.root = canonical(os.path.abspath(paths.state()))
        self.area = self.root + "/attempts"
        self.path = self.area + "/" + self.id
        self.lock_path = self.area + "/.locks/" + self.id + ".lock"

    def open_lock(self):
        """Create only private directories and a permanent, nontruncated lock."""
        root = directory(self.root, True)
        os.close(root)
        area = directory(self.area, True)
        os.close(area)
        locks = directory(self.area + "/.locks", True)
        try:
            f = os.open(self.id + ".lock", os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600, dir_fd=locks)
            try:
                st = os.fstat(f)
                need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1, "not a plain lifecycle lock")
                private(st, 0o600)
                return f
            except BaseException:
                os.close(f)
                raise
        finally:
            os.close(locks)

    def lock_match(self):
        f = self.open_lock()
        try:
            try:
                held = os.fstat(7)
            except OSError as e:
                raise Refuse("lifecycle lock requires fd 7") from e
            st = os.fstat(f)
            need((held.st_dev, held.st_ino) == (st.st_dev, st.st_ino), "fd 7 is for the wrong lifecycle run")
        finally:
            os.close(f)

    def require_lock(self):
        self.lock_match()
        probe = self.open_lock()
        try:
            # A different open description must NOT acquire even a shared lock.
            # Then our own fd must accept EX|NB: another holder cannot pass this.
            try:
                fcntl.flock(probe, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                raise Refuse("fd 7 does not hold the exclusive lifecycle lock")
            try:
                fcntl.flock(7, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as e:
                raise Refuse("lifecycle lock busy or unsupported") from e
        finally:
            os.close(probe)

    def registry(self, require_file=False):
        fd = directory(self.root)
        try:
            lock = os.open("local-runs.jsonl.lock", os.O_RDWR | os.O_CREAT | NOFOLLOW, 0o600, dir_fd=fd)
            try:
                st = os.fstat(lock)
                need(stat.S_ISREG(st.st_mode) and st.st_nlink == 1 and st.st_uid == os.geteuid(),
                     "not an owner-owned plain registry lock")
                if stat.S_IMODE(st.st_mode) != 0o600:
                    os.fchmod(lock, 0o600)
                fcntl.flock(lock, fcntl.LOCK_SH)
                try:
                    data = read_at(fd, "local-runs.jsonl", MAX_REGISTRY, 0o600)
                except FileNotFoundError:
                    need(not require_file, "registry file is missing")
                    return None
            finally:
                os.close(lock)
        finally:
            os.close(fd)
        found = None
        for line in data.splitlines():
            need(len(line) <= MAX_RECORD, "oversized registry line")
            try:
                row = decode(line)
            except Refuse:
                need(self.id.encode() not in line, "ambiguous malformed registry line")
                continue
            if type(row) is not dict or not isinstance(row.get("run"), str):
                need(self.id.encode() not in line, "ambiguous malformed registry line")
                continue
            if os.path.basename(row["run"]) == self.id:
                need(row["run"] == self.run and found is None, "ambiguous lifecycle run id in registry")
                found = row
        return found

    def authority(self, active=False):
        row = self.registry()
        need(row is not None, "run is absent from the lead registry")
        if "lifecycle" not in row:
            raise Legacy("legacy run: re-prepare, or clean --discard; no lifecycle adoption")
        need(type(row["lifecycle"]) is int and row["lifecycle"] == 1, "unsupported registry lifecycle marker")
        if active:
            need(not row.get("closed") and not row.get("cleaned"), "lifecycle run is closed or cleaned")
        return row

    def _validate(self, record, fd):
        shape(record, "schema run prepared current attempts")
        need(type(record["schema"]) is int and record["schema"] == 1 and record["run"] == self.run,
             "unsupported or mismatched lifecycle record")
        p = record["prepared"]
        shape(p, "epoch at base base_sha refs refs_sha256 identity")
        need(isinstance(p["identity"], str) and re.fullmatch(r"[0-9a-f]{32}", p["identity"]), "invalid prepared identity")
        need(integer(p["epoch"], 0, MAX_EPOCH), "invalid prepared epoch")
        stamp(p["at"])
        try:
            base_bytes = p["base"].encode("utf-8") if isinstance(p["base"], str) else b""
        except UnicodeError as e:
            raise Refuse("invalid prepared base") from e
        need(1 <= len(base_bytes) <= 1024
             and all(ord(c) >= 32 and ord(c) != 127 for c in p["base"]), "invalid prepared base")
        need(isinstance(p["base_sha"], str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", p["base_sha"]), "invalid base SHA")
        self._snapshot(fd, p["refs"], p["refs_sha256"], "prepared.refs")
        attempts = record["attempts"]
        need(type(attempts) is list and 1 <= len(attempts) <= MAX_ATTEMPTS
             and integer(record["current"]) and record["current"] == len(attempts), "invalid current attempt")
        previous_epoch = p["epoch"]
        for n, a in enumerate(attempts, 1):
            shape(a, "n epoch baseline baseline_sha256 gate dispatch verified history saved superseded_at save_nonce")
            need(a["save_nonce"] is None or (isinstance(a["save_nonce"], str) and re.fullmatch(r"[0-9a-f]{32}", a["save_nonce"])), "invalid save nonce")
            need(type(a["n"]) is int and a["n"] == n and integer(a["epoch"], previous_epoch, MAX_EPOCH), "invalid attempt epoch/number")
            previous_epoch = a["epoch"]
            expected = "prepared.refs" if n == 1 else "a%d.base.%s.refs" % (n, a["baseline_sha256"])
            self._snapshot(fd, a["baseline"], a["baseline_sha256"], expected)
            if n == 1:
                need(a["epoch"] == p["epoch"] and a["baseline_sha256"] == p["refs_sha256"], "prepared baseline changed")
            need(a["gate"] == "strict", "invalid attempt phase")
            if a["superseded_at"] is not None:
                stamp(a["superseded_at"])
            need((a["superseded_at"] is None) == (n == len(attempts)), "invalid superseded state")
            need(type(a["saved"]) is list and len(a["saved"]) <= MAX_SAVED, "invalid saved-copy list")
            for k, name in enumerate(a["saved"], 1):
                need(name == "a%d.saved.%d" % (n, k), "invalid saved-copy path")
                saved = directory(self.path + "/" + name)
                try:
                    self._parse_marker(read_at(saved, "attempt", 96, 0o600), record, n)
                finally:
                    os.close(saved)
            d = a["dispatch"]
            if d is not None:
                shape(d, "started runner member ended outcome")
                stamp(d["started"])
                identity(d["runner"])
                if d["member"] is not None:
                    identity(d["member"])
                if d["ended"] is not None:
                    stamp(d["ended"])
                    need(d["outcome"] in ("ok", "failed", "cancelled", "lost", "not-started"), "invalid dispatch outcome")
                    need((d["member"] is None) == (d["outcome"] == "not-started"),
                         "ended dispatch has no member evidence")
                else:
                    need(d["outcome"] is None, "unfinished dispatch has outcome")
            need(type(a["history"]) is list and len(a["history"]) <= MAX_VERIFICATIONS, "invalid verification history")
            for v in a["history"] + ([a["verified"]] if a["verified"] is not None else []):
                shape(v, "at snapshot sha256 nonce")
                need(isinstance(v["nonce"], str) and re.fullmatch(r"[0-9a-f]{32}", v["nonce"]), "invalid verification nonce")
                stamp(v["at"])
                need(d is None or d["ended"] is not None, "unfinished dispatch is verified")
                self._snapshot(fd, v["snapshot"], v["sha256"], "a%d.verified.%s.refs" % (n, v["sha256"]))
            if n < len(attempts):
                need((d is None or d["ended"] is not None) and (d is not None or a["verified"] is not None or a["history"]),
                     "invalid superseded attempt")

    def _snapshot(self, fd, name, sha, expected):
        need(isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha)
             and name == expected and "/" not in name, "invalid snapshot binding")
        need(digest(read_at(fd, name, MAX_REFS, 0o600)) == sha, "lifecycle snapshot hash mismatch")

    def show(self):
        self.authority()
        fd = directory(self.path)
        try:
            record = decode(read_at(fd, "state.json", MAX_RECORD, 0o600))
            self._validate(record, fd)
            return record
        finally:
            os.close(fd)

    def _commit(self, record):
        fd = directory(self.path)
        try:
            self._validate(record, fd)
            data = encode(record)
            need(len(data) <= MAX_RECORD, "lifecycle record limit reached")
            atomic(fd, "state.json", data)
        finally:
            os.close(fd)

    def _refs(self, name, refs):
        need(type(refs) is bytes and len(refs) <= MAX_REFS, "expected bounded snapshot bytes")
        fd = directory(self.path)
        try:
            try:
                existing = read_at(fd, name, MAX_REFS, 0o600)
            except FileNotFoundError:
                atomic(fd, name, refs)
            else:
                need(existing == refs, "immutable lifecycle snapshot already exists")
        finally:
            os.close(fd)
        return digest(refs)

    @staticmethod
    def _attempt(n, epoch, baseline, sha):
        return dict(n=n, epoch=epoch, baseline=baseline, baseline_sha256=sha,
                    gate="strict", dispatch=None, verified=None, history=[], saved=[], superseded_at=None, save_nonce=None)

    def init(self, refs, *, epoch, base, base_sha):
        self.require_lock()
        need(self.registry() is None, "run already registered; refusing lifecycle adoption")
        need(not os.path.lexists(self.root + "/runs/" + self.id), "leftover saved copy exists")
        area = directory(self.area)
        try:
            os.mkdir(self.id, 0o700, dir_fd=area)  # exclusive; never take over an orphan
            try:
                sha = self._refs("prepared.refs", refs)
                record = dict(schema=1, run=self.run, prepared=dict(epoch=epoch, at=now(), base=base,
                              base_sha=base_sha, refs="prepared.refs", refs_sha256=sha, identity=uuid.uuid4().hex), current=1,
                              attempts=[self._attempt(1, epoch, "prepared.refs", sha)])
                self._commit(record)
                sync_dir(area, "initialization")
                return record
            except BaseException:
                shutil.rmtree(self.id, dir_fd=area)
                raise
        finally:
            os.close(area)

    def gate_pending(self, refs, *, epoch, owner_pid=None):
        """Read-only plan; caller must first accept refs using its git gate."""
        self.require_lock()
        self.authority(True)
        record = self.show()
        need(type(refs) is bytes and len(refs) <= MAX_REFS and integer(epoch, record["attempts"][-1]["epoch"], MAX_EPOCH), "invalid gate input")
        a = record["attempts"][-1]
        self._quiescent(a)
        return dict(state_sha256=digest(encode(record)), owner=owner(owner_pid), epoch=epoch,
                    refs_sha256=digest(refs), current=record["current"])

    def gate(self, *, closed=False):
        """Use only under lock; read named bytes from this lead-owned store.

        Integration must use the verified snapshot for after-verify comparisons,
        and the original attempt baseline for strict comparisons. New attempts
        always return to strict. This method performs no git operation.
        """
        self.require_lock()
        self.authority(not closed)
        record = self.show()
        a = record["attempts"][-1]
        self._quiescent(a)
        v = a["verified"]
        return dict(baseline=v["snapshot"] if v else a["baseline"],
                    sha256=v["sha256"] if v else a["baseline_sha256"], epoch=a["epoch"],
                    phase="after-verify" if v else "strict",
                    opens_new=v is not None or a["dispatch"] is not None)

    def begin(self, pending, refs):
        """Commit before any accepted output mutation, including report rotation."""
        self.require_lock()
        self.authority(True)
        record = self.show()
        shape(pending, "state_sha256 owner epoch refs_sha256 current")
        identity(pending["owner"])
        need(integer(pending["current"]), "invalid pending attempt")
        need(type(refs) is bytes and len(refs) <= MAX_REFS, "invalid begin snapshot")
        need(pending == self.gate_pending(refs, epoch=pending["epoch"]), "stale or wrong-owner lifecycle pending plan")
        self._recover_retained(record)
        self._retain(record, force=True)
        a = record["attempts"][-1]
        if a["verified"] is not None or a["dispatch"] is not None:
            n = record["current"] + 1
            need(n <= MAX_ATTEMPTS, "attempt limit reached; re-prepare")
            sha = digest(refs)
            name = "a%d.base.%s.refs" % (n, sha)
            self._refs(name, refs)
            a["superseded_at"] = now()
            a = self._attempt(n, pending["epoch"], name, sha)
            record["attempts"].append(a)
            record["current"] = n
        a["dispatch"] = dict(started=now(), runner=owner(), member=None, ended=None, outcome=None)
        a["save_nonce"] = None
        need(len(encode(record)) + DISPATCH_HEADROOM <= MAX_RECORD, "lifecycle record has insufficient dispatch headroom")
        self._commit(record)
        return record

    def _owned_dispatch(self, record):
        d = record["attempts"][-1]["dispatch"]
        need(d is not None and d["ended"] is None and d["runner"] == owner(), "dispatch is not owned by this process")
        return d

    def member(self, pid):
        self.require_lock()
        self.authority(True)
        record = self.show()
        d = self._owned_dispatch(record)
        need(d["member"] is None, "member already recorded")
        p = process(pid)
        need(p is not None and p["ppid"] == os.getpid() and p["pgid"] == pid, "member must be this runner's child and process-group leader")
        d["member"] = dict(pid=pid, token=p["token"])
        self._commit(record)
        return record

    def end(self, outcome):
        self.require_lock()
        self.authority(True)
        record = self.show()
        d = self._owned_dispatch(record)
        need(outcome in ("ok", "failed", "cancelled", "not-started"), "invalid end outcome")
        if d["member"] is None:
            need(outcome == "not-started", "member liveness unknown; only not-started can end without a member")
        else:
            need(outcome != "not-started" and not group_alive(d["member"]["pid"]), "member process group is busy")
        d.update(ended=now(), outcome=outcome)
        self._commit(record)
        return record

    @staticmethod
    def _quiescent(attempt):
        d = attempt["dispatch"]
        need(d is None or d["ended"] is not None, "unfinished dispatch; reconcile before continuing")

    @staticmethod
    def _marker(record, n, nonce):
        return (record["prepared"]["identity"] + " " + str(n) + " " + nonce + "\n").encode()

    @staticmethod
    def _parse_marker(raw, record, expected=None):
        match = re.fullmatch(rb"([0-9a-f]{32}) ([1-9][0-9]{0,2}) ([0-9a-f]{32})\n", raw)
        need(match is not None and match[1].decode() == record["prepared"]["identity"], "invalid saved attempt marker")
        n = int(match[2])
        need(integer(n) and (expected is None or n == expected), "invalid saved attempt marker")
        return n, match[3].decode()

    def _saved_marker(self, record):
        fd = directory(self.root + "/runs/" + self.id)
        try:
            return self._parse_marker(read_at(fd, "attempt", 96, 0o600), record)
        finally:
            os.close(fd)

    def _recover_retained(self, record):
        for a in record["attempts"]:
            k = len(a["saved"]) + 1
            target = "a%d.saved.%d" % (a["n"], k)
            if os.path.lexists(self.path + "/" + target):
                need(k <= MAX_SAVED, "saved-copy limit reached")
                fd = directory(self.path + "/" + target)
                try:
                    self._parse_marker(read_at(fd, "attempt", 96, 0o600), record, a["n"])
                finally:
                    os.close(fd)
                a["saved"].append(target)
                self._commit(record)

    def _retain(self, record, force=False):
        try:
            marker = self._saved_marker(record)
        except FileNotFoundError:
            need(not os.path.lexists(self.root + "/runs/" + self.id), "saved copy lacks an attempt marker")
            return
        current = record["attempts"][-1]
        if not force and current["verified"] is not None and marker == (current["n"], current["verified"]["nonce"]):
            return
        n, _ = marker
        need(n <= current["n"], "saved marker is ahead of lifecycle state")
        a = record["attempts"][n - 1]
        k = len(a["saved"]) + 1
        need(k <= MAX_SAVED, "saved-copy limit reached; clean or re-prepare")
        target = "a%d.saved.%d" % (n, k)
        a["saved"].append(target)
        try:
            need(len(encode(record)) <= MAX_RECORD, "lifecycle record limit reached")
        finally:
            a["saved"].pop()
        fd = directory(self.path)
        try:
            need(not os.path.lexists(self.path + "/" + target), "retained saved copy already exists")
            runs = directory(self.root + "/runs")
            try:
                os.rename(self.id, target, src_dir_fd=runs, dst_dir_fd=fd)
                sync_dir(runs, "retention rename")
                sync_dir(fd, "retention rename")
            finally:
                os.close(runs)
        finally:
            os.close(fd)
        a["saved"].append(target)
        self._commit(record)

    def reconcile(self):
        self.require_lock()
        self.authority(True)
        record = self.show()
        d = record["attempts"][-1]["dispatch"]
        if d is not None and d["ended"] is None:
            runner = process(d["runner"]["pid"])
            need(runner is None or runner["token"] != d["runner"]["token"], "dispatch runner is busy")
            need(d["member"] is not None, "member group was never recorded; liveness unknown")
            need(not group_alive(d["member"]["pid"]), "member process group is busy")
            d.update(ended=now(), outcome="lost")
            self._commit(record)
        self._recover_retained(record)
        self._retain(record)
        return record

    def prepare_save(self):
        """Retain any installed copy and issue a fresh, lead-owned marker.

        Call under fd 7 after reconcile and before creating the replacement.
        The returned ASCII string is the complete marker file content. A failed
        save or verification cannot make the previous verification authorize it.
        """
        self.require_lock()
        self.authority(True)
        record = self.show()
        a = record["attempts"][-1]
        self._quiescent(a)
        self._recover_retained(record)
        self._retain(record, force=True)
        a["save_nonce"] = uuid.uuid4().hex
        self._commit(record)
        return self._marker(record, a["n"], a["save_nonce"]).decode("ascii")

    def verified(self, refs):
        self.require_lock()
        self.authority(True)
        record = self.show()
        a = record["attempts"][-1]
        self._quiescent(a)
        need(a["save_nonce"] is not None and self._saved_marker(record) == (a["n"], a["save_nonce"]), "saved copy does not match prepared save")
        need(type(refs) is bytes and len(refs) <= MAX_REFS, "invalid verification snapshot")
        sha = digest(refs)
        if a["verified"] is not None and a["verified"]["sha256"] == sha and a["verified"]["nonce"] == a["save_nonce"]:
            return record
        name = "a%d.verified.%s.refs" % (a["n"], sha)
        self._refs(name, refs)
        if a["verified"] is not None and (a["verified"]["sha256"] != sha or a["verified"]["nonce"] != a["save_nonce"]):
            need(len(a["history"]) < MAX_VERIFICATIONS, "verification history limit reached")
            a["history"].append(a["verified"])
        a["verified"] = dict(at=now(), snapshot=name, sha256=sha, nonce=a["save_nonce"])
        self._commit(record)
        return record

    def saved_copy(self):
        self.require_lock()
        self.authority(True)
        record = self.show()
        v = record["attempts"][-1]["verified"]
        need(v is not None and self._saved_marker(record) == (record["current"], v["nonce"]), "no current verified saved copy")
        return self.root + "/runs/" + self.id

    def drop(self):
        self.require_lock()
        row = self.registry(require_file=True)
        need(row is None or bool(row.get("cleaned")), "registry must commit cleaned/drop before lifecycle cleanup")
        fd = directory(self.area)
        try:
            try:
                child = os.open(self.id, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                return
            try:
                private(os.fstat(child), 0o700)
            finally:
                os.close(child)
            need(shutil.rmtree.avoids_symlink_attacks, "safe cleanup unavailable")
            shutil.rmtree(self.id, dir_fd=fd)
            sync_dir(fd, "cleanup")
        finally:
            os.close(fd)


def ready(store, *, closed=False):
    """Shared entry gate. Legacy inspection is explicit; runtime never adopts it."""
    store.require_lock()
    try:
        row = store.authority()
    except Legacy:
        print("qargi: warning: legacy run: writable snapshots provide limited inspection/recovery only; re-prepare before runtime dispatch", file=sys.stderr)
        return False
    if closed and (row.get("closed") or row.get("cleaned")):
        store._quiescent(store.show()["attempts"][-1])
    else:
        store.reconcile()
    return True


def applied_record(store):
    """A private apply record, never RUN/applied. Invalid records fail closed."""
    path = store.root + "/apply"
    if not os.path.lexists(path):
        return None
    root = directory(store.root)
    try:
        fd = os.open("apply", os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=root)
        need(os.fstat(fd).st_uid == os.geteuid(), "apply directory is not lead-owned")
    finally:
        os.close(root)
    try:
        try:
            row = decode(read_at(fd, store.id + ".json", MAX_RECORD, 0o600))
        except FileNotFoundError:
            return None
        need(type(row) is dict and row.get("run") == store.run
             and row.get("status") in ("started", "built", "done"), "invalid apply authority")
        if row["status"] in ("built", "done"):
            need(isinstance(row.get("tip"), str) and re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", row["tip"])
                 and isinstance(row.get("branch"), str) and bool(row["branch"]), "invalid applied branch/tip")
        return row
    finally:
        os.close(fd)


def current_verified(store):
    """Read-only observation: a failed save is not a current verified product."""
    record = store.show()
    a = record["attempts"][-1]
    store._quiescent(a)
    v = a["verified"]
    return v is not None and store._saved_marker(record) == (a["n"], v["nonce"])


def product_tree(path):
    """Compare product bytes and names, never follow links or open special files."""
    result = {}
    def visit(fd, prefix):
        for name in sorted(os.listdir(fd)):
            st = os.stat(name, dir_fd=fd, follow_symlinks=False)
            key = prefix + name
            if stat.S_ISLNK(st.st_mode):
                result[key] = ("link", os.readlink(name, dir_fd=fd))
            elif stat.S_ISDIR(st.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW, dir_fd=fd)
                try:
                    result[key] = ("dir",)
                    visit(child, key + "/")
                finally:
                    os.close(child)
            else:
                need(stat.S_ISREG(st.st_mode), "OUT contains a special file")
                child = os.open(name, os.O_RDONLY | os.O_NONBLOCK | NOFOLLOW, dir_fd=fd)
                try:
                    need(stat.S_ISREG(os.fstat(child).st_mode), "OUT file changed kind")
                    h = hashlib.sha256()
                    while block := os.read(child, 1024 * 1024):
                        h.update(block)
                    result[key] = ("file", h.hexdigest())
                finally:
                    os.close(child)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | NOFOLLOW)
    try:
        visit(fd, "")
    finally:
        os.close(fd)
    return result


def product_matches(store):
    store.require_lock()
    record = store.show()
    d = record["attempts"][-1]["dispatch"]
    need(d is None or d["outcome"] == "ok",
         "dispatch did not succeed; output cannot be attributed to this attempt; re-prepare")
    try:
        accepted = current_verified(store)
    except FileNotFoundError:
        accepted = False
    if accepted and os.path.lexists(store.run):
        need(product_tree(store.run + "/out") == product_tree(store.saved_copy() + "/out"),
             "OUT changed since acceptance; retained product was not replaced; re-prepare")


def save_product(store, refs):
    """Publish a generation, then commit acceptance without intervening reconcile.

    Repeated observation reuses the accepted product. A different OUT requires a
    new dispatch (or explicit recovery after an interrupted save).
    """
    store.require_lock()
    product_matches(store)
    try:
        if current_verified(store):
            store.verified(refs)
            return store.saved_copy()
    except FileNotFoundError:
        pass
    marker = store.prepare_save()  # Keep its newline; no shell decoding.
    runs = store.root + "/runs"
    os.close(directory(runs, True, tighten=True))
    tmp = tempfile.mkdtemp(prefix=".save.", dir=runs)
    try:
        # cp -P copies even a replaced top-level OUT as a link; reject it below.
        # Never traverse a member's symlink into unrelated lead files.
        copied = subprocess.run(["cp", "-R", "--no-dereference", "--", store.run + "/out", tmp + "/out"],
                                close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        need(copied.returncode == 0 and not os.path.islink(tmp + "/out") and os.path.isdir(tmp + "/out"),
             "could not copy a plain OUT directory; re-verification required")
        for name in ("run.bundle", "ability", "class", "profile", "task.md"):
            src = store.run + "/" + name
            if os.path.isfile(src) and not os.path.islink(src):
                copied = subprocess.run(["cp", "--no-dereference", "--", src, tmp + "/" + name],
                                        close_fds=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                need(copied.returncode == 0, "could not copy run metadata; re-verification required")
        record = store.show()
        fd = directory(tmp)
        source = directory(store.path)
        try:
            atomic(fd, "attempt", marker.encode("ascii"))
            atomic(fd, "refs.before", read_at(source, "prepared.refs", MAX_REFS, 0o600))
            atomic(fd, "verified", refs)
            atomic(fd, "started", str(record["prepared"]["epoch"]).encode() + b"\n")
            atomic(fd, "record.json", encode(store.authority()))
        finally:
            os.close(fd)
            os.close(source)
        target = runs + "/" + store.id
        need(not os.path.lexists(target), "saved target unexpectedly exists")
        os.rename(tmp, target)
        fd = directory(runs)
        try:
            sync_dir(fd, "saved generation publish")
        finally:
            os.close(fd)
        store.verified(refs)
        return target
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        need(len(argv) == 2, "attempts requires COMMAND RUN")
        cmd, run = argv
        store = Store(run)
        if cmd == "lock-open":
            fd = store.open_lock()
            try:
                print("/proc/%d/fd/%d" % (os.getpid(), fd), flush=True)
                sys.stdin.buffer.read(1)
            finally:
                os.close(fd)
            return 0
        if cmd in ("lock-match", "lock-check"):
            (store.lock_match if cmd == "lock-match" else store.require_lock)()
            return 0
        if cmd in ("ready", "ready-clean"):
            result = ready(store, closed=cmd == "ready-clean")
        elif cmd == "base-sha":
            result = store.show()["prepared"]["base_sha"]
        elif cmd == "applied":
            store.require_lock()
            store.show()
            result = applied_record(store)
        elif cmd == "current":
            store.require_lock()
            need(current_verified(store), "re-verification required: no current verified saved generation")
            result = True
        elif cmd == "product-matches":
            product_matches(store)
            result = True
        elif cmd == "saved-copy":
            try:
                result = store.saved_copy()
            except (FileNotFoundError, Refuse) as e:
                raise Refuse("re-verification required: no current verified saved generation (%s)" % e) from e
        elif cmd == "compare-input":
            row = store.authority()
            result = store.gate(closed=bool(row.get("closed")))
            result["baseline"] = store.path + "/" + result["baseline"]
        elif cmd in ("show", "gate", "reconcile", "prepare-save", "drop"):
            result = getattr(store, cmd.replace("-", "_"))()
        else:
            data = sys.stdin.buffer.read(2 * MAX_REFS + MAX_RECORD + 1)
            need(len(data) <= 2 * MAX_REFS + MAX_RECORD, "oversized lifecycle request")
            args = decode(data)
            need(type(args) is dict, "expected lifecycle request object")
            if "refs" in args:
                need(isinstance(args["refs"], str), "refs must be a string")
                args["refs"] = args["refs"].encode()
            need(cmd in ("init", "gate-pending", "begin", "member", "end", "verified", "save-product"), "unknown lifecycle command")
            if cmd == "gate-pending":
                args.setdefault("owner_pid", os.getppid())
            result = save_product(store, **args) if cmd == "save-product" else getattr(store, cmd.replace("-", "_"))(**args)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (Refuse, OSError, TypeError, ValueError, RecursionError) as e:
        print("qargi: lifecycle: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
