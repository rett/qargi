#!/usr/bin/env python3
"""Memory store backends: a store is a set of notes {path: {type, id, path, content, content_sha256}}.

  DirBackend      a local directory tree; every file is a note (the reference backend)
  FixtureBackend  the JSONL dump the tests use ({"id","path","content"} per line)
  CloudBackend    a Managed Agents memory store, through the `ant` CLI (tests use a fake `ant`)

A backend lists, reads, creates, updates and moves notes, and archives them. It has no way to delete one:
what a split, merge or migration would remove moves under /_archive/ and the planner records where it came
from (memplan.py). apply_ops(backend, ops, expect_sha) runs a plan's steps for every backend; it checks each
note's digest against the one the plan was computed from and changes nothing if any differs.
Nothing here talks to the network except CloudBackend, and only through `ant`.
"""
import contextlib, errno, fcntl, hashlib, json, os, re, subprocess, tempfile, threading, unicodedata

ARCHIVE = "/_archive/"


class StoreError(Exception):
    pass


class StaleError(StoreError):
    """A note is not what the plan was computed from (changed, created or moved meanwhile)."""


def digest(content):
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def note(path, content, id=None, sha=None):
    return {"type": "memory", "id": id or "", "path": path, "content": content, "content_sha256": sha or digest(content)}


def path_problem(p):
    """Why p cannot be a note path in any store, or None. A path is absolute, has no empty, . or .. part, no part that
    starts with a dot (.git and temporary files are not notes) or ends in white space, and no control character or
    backslash. DirBackend.list shows exactly the paths that pass, so what is listed is what can be stored."""
    if not isinstance(p, str) or not p.startswith("/") or p == "/" or p.endswith("/"):
        return "not an absolute path to a file"
    if "\\" in p or any(ord(c) < 32 or ord(c) == 127 for c in p):
        return "a backslash or control character"
    for part in p[1:].split("/"):
        if part in ("", ".", ".."):
            return "an empty, . or .. part"
        if part.startswith("."):
            return "a part starting with a dot (%s)" % part
        if part != part.rstrip():
            return "a part ending in white space (%s)" % part
    return None


def check_path(p):
    why = path_problem(p)
    if why:
        raise StoreError("not a store path: %r (%s)" % (p, why))
    return p


# What the Managed Agents memory store accepts (checked at plan time, not left to fail in the middle of an apply).
CLOUD = {"segments": 20, "path_bytes": 1024, "content_bytes": 102400}


def cloud_problem(p, content=None):
    why = path_problem(p)
    if why:
        return why
    if len(p[1:].split("/")) > CLOUD["segments"]:
        return "more than %d path segments" % CLOUD["segments"]
    if len(p.encode("utf-8")) > CLOUD["path_bytes"]:
        return "a path over %d bytes" % CLOUD["path_bytes"]
    if unicodedata.normalize("NFC", p) != p:
        return "a path that is not NFC-normalised"
    if any(unicodedata.category(c) in ("Cc", "Cf", "Zl", "Zp") for c in p):
        return "a control, format or line-separator character"
    if content is not None and len(content.encode("utf-8")) > CLOUD["content_bytes"]:
        return "content over %d bytes" % CLOUD["content_bytes"]
    return None


class Backend:
    """list/read/create/update/move/archive; versions is optional. There is no delete."""
    label = "store"

    def list(self):
        raise NotImplementedError

    def read(self, path):
        return self.list().get(path)

    def create(self, path, content):
        raise NotImplementedError

    def update(self, path, content, expect=None):
        raise NotImplementedError

    def move(self, path, to, expect=None, content=None):
        """Rename a note; with content the new text is written in the same step."""
        raise NotImplementedError

    def archive(self, path, to, content, expect=None):
        """Move a note to `to` (under /_archive/) with `content` (its Sources: line records the origin)."""
        if not to.startswith(ARCHIVE):
            raise StoreError("an archive path is under %s: %s" % (ARCHIVE, to))
        self.move(path, to, expect, content)

    def versions(self, path):
        return []

    def refusal(self, path, content=None):
        """Why this store cannot hold a note at `path` with `content`, or None. The planners ask it for every path they
        would write, so a note that cannot be stored is refused when the plan is made, never in the middle of an apply."""
        return path_problem(path)

    @contextlib.contextmanager
    def lock(self):
        yield

    def _check(self, path, cur, expect):
        if cur is None:
            raise StaleError("%s is gone" % path)
        if expect is not None and digest(cur["content"]) != expect:
            raise StaleError("%s changed since the plan was made" % path)


class FixtureBackend(Backend):
    """Notes in memory, optionally kept in a JSONL file. A dump is a source: the CLI never opens one for writing
    (open_store). When a test does write one, every row that is not a memory is kept as it was and the file is
    replaced through a uniquely named temporary file, so two writers cannot share a temporary name."""

    def __init__(self, file=None, notes=None, label=None):
        self.file, self.n, self.other = file, 0, []
        self.label = label or (os.path.splitext(os.path.basename(file))[0] if file else "fixture")
        self.notes = {}
        if file and os.path.exists(file):
            with open(file) as f:
                for line in f:
                    if line.strip():
                        m = json.loads(line)
                        if m.get("type", "memory") == "memory":
                            self.notes[m["path"]] = note(m["path"], m["content"], m.get("id"))
                        else:
                            self.other.append(m)
        for p, c in (notes or {}).items():
            self.notes[check_path(p)] = note(p, c, self._id())
        for m in self.notes.values():
            m["id"] = m["id"] or self._id()
        if notes:
            self._save()

    def _id(self):
        self.n += 1
        return "fx_%d" % self.n

    def _save(self):
        if self.file:
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(self.file)), prefix=".qargi-", suffix=".tmp")
            try:
                with os.fdopen(fd, "w") as f:
                    for m in self.other:
                        f.write(json.dumps(m) + "\n")
                    for p in sorted(self.notes):
                        f.write(json.dumps(self.notes[p]) + "\n")
                os.replace(tmp, self.file)
            except BaseException:
                if os.path.exists(tmp):
                    os.unlink(tmp)
                raise

    def list(self):
        return {p: dict(m) for p, m in self.notes.items()}

    def create(self, path, content):
        check_path(path)
        if path in self.notes:
            raise StaleError("%s already exists" % path)
        self.notes[path] = note(path, content, self._id())
        self._save()

    def update(self, path, content, expect=None):
        self._check(path, self.notes.get(path), expect)
        self.notes[path] = note(path, content, self.notes[path]["id"])
        self._save()

    def move(self, path, to, expect=None, content=None):
        check_path(to)
        self._check(path, self.notes.get(path), expect)
        if to in self.notes:
            raise StaleError("%s already exists" % to)
        m = self.notes.pop(path)
        self.notes[to] = note(to, m["content"] if content is None else content, m["id"])
        self._save()


class DirBackend(Backend):
    """A directory tree: every regular file is a note, its path the path below the root. Names starting
    with a dot (.git, temporary files) are not notes. The id is derived from the path and the digest, so
    it names one version of one note. A missing root is an empty store, made on the first write."""

    def __init__(self, root, label=None):
        self.root = os.path.realpath(root)
        self.label = label or os.path.basename(self.root) or "dir"
        self._held, self._mutex = 0, threading.RLock()

    def _file(self, path):
        check_path(path)
        f = os.path.join(self.root, *path[1:].split("/"))
        parent = os.path.realpath(os.path.dirname(f))
        if parent != self.root and not parent.startswith(self.root + os.sep):
            raise StoreError("%s leaves the store" % path)
        return f

    @staticmethod
    def _id(path, sha):
        return "dir_" + hashlib.sha256((path + "\0" + sha).encode()).hexdigest()[:16]

    def list(self):
        out = {}
        for d, dirs, files in os.walk(self.root):
            dirs[:] = sorted(x for x in dirs if not x.startswith("."))
            for fn in sorted(files):
                f = os.path.join(d, fn)
                if os.path.islink(f) or not os.path.isfile(f):
                    continue
                p = "/" + os.path.relpath(f, self.root).replace(os.sep, "/")
                if path_problem(p):          # a dot name or a name ending in white space is not a note: listed == storable
                    continue
                try:
                    with open(f, encoding="utf-8", newline="") as h:
                        c = h.read()
                except UnicodeDecodeError:       # fail closed: a store with a binary file is not read at all, never half-read
                    raise StoreError("%s is not UTF-8 text; a store holds notes" % p)
                sha = digest(c)
                out[p] = note(p, c, self._id(p, sha), sha)
        return out

    def refusal(self, path, content=None):
        why = path_problem(path)
        if not why and any(len(part.encode("utf-8")) > 255 for part in path[1:].split("/")):
            why = "a name over 255 bytes"
        return why

    @contextlib.contextmanager
    def lock(self):
        """Exclusive among qargi writers, advisory (an editor that never asks is not stopped), reentrant: apply_ops
        holds it across a whole plan and each write takes it again, and flock on a second descriptor of one
        process would block on the first. The RLock keeps other threads of this process out for the same span."""
        with self._mutex:
            if self._held:
                self._held += 1
                try:
                    yield
                finally:
                    self._held -= 1
                return
            os.makedirs(self.root, exist_ok=True)
            fd = os.open(self.root, os.O_RDONLY)       # on the folder itself: no file is left in the store
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                self._held = 1
                try:
                    yield
                finally:
                    self._held = 0
            finally:
                os.close(fd)

    def _current(self, path):
        f = self._file(path)
        if not os.path.isfile(f) or os.path.islink(f):
            return None
        with open(f, encoding="utf-8", newline="") as h:
            return note(path, h.read())

    def _still(self, path, was):
        """The note at `path` still has digest `was`, read now: the last look before a replace or a release of a name,
        so a change made outside qargi after the check is caught instead of overwritten or lost."""
        now = self._current(path)
        if now is None or digest(now["content"]) != was:
            raise StaleError("%s changed while it was being written" % path)

    def _write(self, f, content, replace, was=None):
        os.makedirs(os.path.dirname(f), exist_ok=True)
        if not replace:
            # O_EXCL: the create fails if the path exists and needs no hard links, which some filesystems refuse
            try:
                fd = os.open(f, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
            except FileExistsError:
                raise StaleError("%s already exists" % f[len(self.root):])
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as h:
                    h.write(content)
            except BaseException:
                os.unlink(f)                 # the half-written file this call made; no note was there
                raise
            return
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(f), prefix=".qargi-")
        try:
            os.chmod(tmp, os.stat(f).st_mode & 0o777 if os.path.exists(f) else 0o644)
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as h:
                h.write(content)
            if was is not None:
                self._still(f[len(self.root):], was)
            os.replace(tmp, f)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def create(self, path, content):
        with self.lock():
            self._write(self._file(path), content, False)

    def update(self, path, content, expect=None):
        with self.lock():
            cur = self._current(path)
            self._check(path, cur, expect)
            self._write(self._file(path), content, True, digest(cur["content"]))

    def move(self, path, to, expect=None, content=None):
        with self.lock():
            cur = self._current(path)
            self._check(path, cur, expect)
            self._write(self._file(to), cur["content"] if content is None else content, False)
            self._still(path, digest(cur["content"]))     # an outside edit since the check must not be lost with the name
            os.unlink(self._file(path))      # the note now lives at `to`; the name is released, not the content
            try:
                d = os.path.dirname(self._file(path))
                while d != self.root and not os.listdir(d):
                    os.rmdir(d)
                    d = os.path.dirname(d)
            except OSError:
                pass                         # tidying an emptied folder; the move itself has succeeded


def _error_type(text):
    """error.type of the JSON body `ant` prints after a failed call (`POST "<url>": 409 Conflict`), or None."""
    i = text.find("{")
    while i != -1:
        try:
            v, _ = json.JSONDecoder().raw_decode(text, i)
            e = v.get("error") if isinstance(v, dict) else None
            if isinstance(e, dict) and e.get("type"):
                return e["type"]
        except ValueError:
            pass
        i = text.find("{", i + 1)
    return None


def _stream(text):
    """JSON values from text, whether one per line, concatenated or an array."""
    dec, i, out = json.JSONDecoder(), 0, []
    while True:
        while i < len(text) and text[i] in " \t\r\n":
            i += 1
        if i >= len(text):
            return out
        v, i = dec.raw_decode(text, i)
        out.extend(v if isinstance(v, list) else [v])


class CloudBackend(Backend):
    """A Managed Agents memory store through `ant beta:memory-stores:memories` (the calls lib.sh makes).

    Inside lock() the store is listed once and the notes kept in a cache that each write updates, so a plan of N
    steps costs about 2N calls (the write, and a listing of the one folder to see that exactly one memory holds the
    path). Outside a lock every list() asks the store. Writes go with a content_sha256 precondition on the current
    content, so a note changed by an agent since the listing is refused (StaleError), not overwritten; the store
    does not promise that a create refuses an existing path, which is why a create is verified afterwards."""

    def __init__(self, store_id, ant="ant"):
        self.store, self.ant, self.label = store_id, ant, store_id
        self._cache, self._held, self._mutex = None, 0, threading.RLock()

    def refusal(self, path, content=None):
        return cloud_problem(path, content)

    def _ant(self, group, args, stdin=None, path=None):
        r = subprocess.run([self.ant, group] + args, input=stdin or "", capture_output=True, text=True)
        if r.returncode != 0:
            text = (r.stderr or "") + (r.stdout or "")
            kind = _error_type(text)
            if kind == "memory_precondition_failed_error":       # the note changed since the plan read it
                raise StaleError("%s changed since the plan was made" % (path or "a note"))
            if kind == "memory_path_conflict_error":             # 409: the path is taken; never delete to make room
                raise StaleError("%s already exists" % (path or "the path"))
            err = " ".join((r.stderr or "").split())[-300:]
            raise StoreError("ant %s %s failed%s" % (group.rsplit(":", 1)[-1], args[0], ": " + err if err else ""))
        return r.stdout

    def _run(self, args, stdin=None, path=None):
        return self._ant("beta:memory-stores:memories", args, stdin, path)

    def _body(self, content):
        f = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="", delete=False)
        try:
            f.write(content)
            f.close()
            return 'content: "@%s"\n' % f.name, f.name
        except BaseException:
            os.unlink(f.name)
            raise

    @staticmethod
    def _note(m):
        c = m.get("content", "")
        return dict(note(m["path"], c, m["id"]), content_sha256=m.get("content_sha256") or digest(c))

    @contextlib.contextmanager
    def lock(self):
        with self._mutex:
            self._held += 1
            try:
                yield
            finally:
                self._held -= 1
                if not self._held:
                    self._cache = None

    def list(self):
        if self._held and self._cache is not None:
            return {p: dict(m) for p, m in self._cache.items()}
        out = {}
        for m in _stream(self._run(["list", "--memory-store-id", self.store, "--path-prefix", "/", "--view", "full", "--max-items", "-1"])):
            if m.get("type", "memory") == "memory":
                out[m["path"]] = self._note(m)
        if self._held:
            self._cache = out
        return {p: dict(m) for p, m in out.items()}

    def _holders(self, path):
        """The memories at `path`, asked of the store for that one folder."""
        out = _stream(self._run(["list", "--memory-store-id", self.store, "--path-prefix", path.rsplit("/", 1)[0] + "/",
                                 "--depth", "1", "--view", "basic", "--max-items", "-1"]))
        return [m for m in out if m.get("type", "memory") == "memory" and m.get("path") == path]

    def _verify(self, path, content):
        """Exactly one memory holds `path` now; two is an error that names both and deletes nothing."""
        ms = self._holders(path)
        if len(ms) != 1:
            self._cache = None
            raise StoreError("%s is held by %s memories (%s); nothing was deleted, resolve it in the store"
                             % (path, len(ms), ", ".join(m.get("id", "?") for m in ms) or "none"))
        if self._cache is not None:
            self._cache[path] = dict(self._note(dict(ms[0], content=content)), content_sha256=ms[0].get("content_sha256") or digest(content))

    def _send(self, verb, path, content, cur=None, to=None):
        args = [verb, "--memory-store-id", self.store]
        if verb == "create":
            args += ["--path", path]
        else:
            args += ["--memory-id", cur["id"], "--precondition.type", "content_sha256", "--precondition.content-sha256", cur["content_sha256"]]
            if to:
                args += ["--path", to]
        stdin, tmp = self._body(content) if content is not None else ("", None)
        try:
            self._run(args, stdin, to or path)
        except StoreError:
            self._cache = None
            raise
        finally:
            if tmp:
                os.unlink(tmp)

    def _fits(self, path, content=None):
        why = cloud_problem(path, content)
        if why:
            raise StoreError("%s cannot be stored in a memory store: %s" % (path, why))

    def create(self, path, content):
        self._fits(path, content)
        if path in self.list():
            raise StaleError("%s already exists" % path)
        self._send("create", path, content)
        self._verify(path, content)

    def update(self, path, content, expect=None):
        self._fits(path, content)
        cur = self.list().get(path)
        self._check(path, cur, expect)
        self._send("update", path, content, cur)
        self._verify(path, content)

    def move(self, path, to, expect=None, content=None):
        cur = self.list().get(path)
        self._check(path, cur, expect)
        self._fits(to, cur["content"] if content is None else content)
        if to in self.list():
            raise StaleError("%s already exists" % to)
        self._send("update", path, content, cur, to)
        if self._cache is not None:
            self._cache.pop(path, None)
        self._verify(to, cur["content"] if content is None else content)

    def versions(self, path):
        cur = self.list().get(path)
        if not cur:
            return []
        return _stream(self._ant("beta:memory-stores:memory-versions",
                                 ["list", "--memory-store-id", self.store, "--memory-id", cur["id"], "--max-items", "-1"]))


def open_store(ref, ant="ant", write=False):
    """A store from its name on the command line: a directory, a .jsonl dump or a memstore_ id. A dump is read-only:
    it can be a source, never something qargi writes (write=True refuses it)."""
    if ref.startswith("memstore_"):
        return CloudBackend(ref, ant)
    if ref.endswith(".jsonl"):
        if write:
            raise StoreError("%s is a .jsonl dump, which is read-only: it can be copied from, never into" % ref)
        return FixtureBackend(ref)
    if os.path.exists(ref) and not os.path.isdir(ref):
        raise StoreError("%s is not a directory, a .jsonl dump or a memstore_ id" % ref)
    return DirBackend(ref)


def _check_ops(cur, ops, expect_sha):
    """Walk the steps over {path: digest} as they would run. -> (errors, [digest each step expects of its source])"""
    errs, want = [], []
    for p, e in sorted((expect_sha or {}).items()):
        have = cur.get(p)
        if have != e:
            errs.append("%s %s" % (p, "appeared since the plan was made" if e is None else "is gone" if have is None else "changed since the plan was made"))
    virt = dict(cur)

    def src(op, p):
        if p not in virt:
            errs.append("%s: %s is not there" % (op["op"], p)); return None
        if op.get("sha") and op["sha"] != virt[p]:
            errs.append("%s: %s changed since the plan was made" % (op["op"], p))
        return virt[p]

    for op in ops:
        k = op.get("op")
        if k == "create":
            if op["path"] in virt:
                errs.append("create: %s already exists" % op["path"])
            want.append(None); virt[op["path"]] = digest(op["content"])
        elif k in ("update", "marker"):
            if k == "marker" and op["path"] not in virt:
                want.append(None)
            else:
                want.append(src(op, op["path"]))
            virt[op["path"]] = digest(op["content"])
        elif k in ("move", "archive"):
            if k == "archive" and not op["to"].startswith(ARCHIVE):
                errs.append("archive: %s is not under %s" % (op["to"], ARCHIVE))
            d = src(op, op["from"])
            want.append(d)
            if op["to"] in virt:
                errs.append("%s: %s already exists" % (k, op["to"]))
            if d is not None:
                virt.pop(op["from"], None)
                virt[op["to"]] = digest(op["content"]) if "content" in op else d
        else:
            errs.append("unknown step %r" % (k,))
            want.append(None)
    return errs, want


def apply_ops(backend, ops, expect_sha=None, dry_run=True):
    """Run a plan's steps (create, update, marker, move, archive) against a backend.

    expect_sha maps a path to the digest of the note the plan was computed from, or None for a path that
    must not exist; a step may also carry the "sha" it expects. Every check runs before the first write and
    again at each write: a mismatch raises StaleError and, when it is found first, nothing has changed.
    A dry run (the default) only checks and returns what would be done. -> [step descriptions]"""
    with contextlib.nullcontext() if dry_run or not ops else backend.lock():
        cur = {p: digest(m["content"]) for p, m in backend.list().items()}
        errs, want = _check_ops(cur, ops, expect_sha)
        if errs:
            raise StaleError("; ".join(errs[:5]) + (" (+%d more)" % (len(errs) - 5) if len(errs) > 5 else ""))
        done = []
        for n, (op, e) in enumerate(zip(ops, want)):
            k = op["op"]
            done.append("%s %s" % (k, op.get("from") or op["path"]) + (" -> " + op["to"] if "to" in op else ""))
            if dry_run:
                continue
            try:
                if k == "create" or (k == "marker" and e is None):
                    backend.create(op["path"], op["content"])
                elif k in ("update", "marker"):
                    backend.update(op["path"], op["content"], e)
                elif k == "move":
                    backend.move(op["from"], op["to"], e, op.get("content"))
                else:
                    backend.archive(op["from"], op["to"], op.get("content"), e)
            except (StoreError, OSError) as x:
                if not isinstance(x, StoreError):        # ENAMETOOLONG, EACCES, ENOSPC ...: the plan stops, nothing is lost
                    x = StoreError("%s: %s" % (k + " " + (op.get("to") or op["path"]), os.strerror(x.errno) if x.errno else x))
                raise type(x)("%s (%d of %d steps applied; plan again to resume)" % (x, n, len(ops)) if n else str(x))
        return done
