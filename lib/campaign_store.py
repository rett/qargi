"""Local campaign declarations on a trusted local filesystem.

Store(campaign) selects paths.state() once, lazily on the first operation.
commit(document, create=True) creates revision 1. Otherwise commit requires
expected_head='sha256:...'. show(revision=None), check(), and log(cursor=None,
limit=50) inspect one selected head without locks or filesystem writes. Inputs
are decoded Python documents from campaign_doc.decode, never source filenames.
Results are ordinary campaign-report dictionaries. Error carries code, message
and details with fixed diagnostics. Schema refusals retain their code and path.
Every state operation refuses members through marshal_refs.in_member_run.
Launch readers with python3 -B to suppress Python's import caches. The store
imports all helpers up front and performs no imports during read operations.

Only head.json publishes an object. Exact-current retries settle that head.
Other stale expectations conflict without inspecting history. Object reuse
verifies bytes and grants no committed membership. Successful writes report
fsync-acknowledged, which describes syscall results without a power-loss claim.
Failures distinguish candidate publication from pre-existing parent uncertainty.
Publication describes the candidate's observed selection, including exact retries.
It is not-assessed until classification under the writer lock, none after proving
the candidate unselected, and visible after selecting or observing that candidate.
An attempted head replacement with an unreconciled outcome reports unknown.
The writer reconciles replacement errors under its held lock without repeating
the effect or changing the selected head. Unknown and not-assessed failures grant
no acceptance credit. Durability is a separate field. Visible or unknown failures
report unknown durability. An unpublished child can have an uncertain parent.

History proves selected-head ancestry on every request, including cursor pages.
The total budget is 4096 predecessor edges across head to start, start to next
and page entries. Each edge is charged once. Exhaustion returns no partial page.
A cursor grants no proof credit. complete means this page reached revision 1.
At most 4097 chain objects and two candidate lookups can be read, each bounded
to 256 KiB, plus a 512-byte head. The conservative aggregate byte bound is
4099 * 262144 + 512 = 1074528768 bytes per historical request. Memory retains
a constant number of documents and at most 200 small summaries. Current reads
and commits use at most two distinct objects and have no history-length limit.
Log revision and findings describe the selected head. Entries, selected_start
and cursor describe the historical page within that selected head's ancestry.
Stray temporary files are ignored. Reads never repair, fsync or create state.

Configured root aliases and trusted ancestors are resolved once. The root must
be effective-user-owned and have no group/other write permissions. Descendants
are descriptor-relative, no-follow, exact 0700 directories and 0600 single-link
regular files. Existing permissions never change. Explicit creation durably
links missing directories before publishing a head. One permanent nonblocking
flock serializes each campaign. Writers check its named and held identity.
Qualification assumes cooperating writers, atomic same-directory rename,
directory fsync and local flock. Malicious same-user/root mutation and network
filesystem behavior fall outside this boundary.
Every operation requires readable and searchable ancestors through the configured
root. Every write requires successful directory fsync through those ancestors to
slash, including links left uncertain by earlier creation attempts. Ancestor
failures carry an ancestor-access or ancestor-fsync stage with fixed diagnostics.
Traverse-only ancestors and ancestor filesystems without directory fsync remain
unsupported. The traced 16-large-object test measures instrumented fixture cost.
It does not establish ordinary latency or qualify power loss or kernel EIO.
"""
import contextlib
import errno
import fcntl
import hashlib
import os
import re
import stat
import uuid

import campaign_doc as doc
import marshal_refs
import paths

MAX_HEAD_BYTES = 512
MAX_HISTORY_EDGES = 4096
MAX_PAGE = 200
DEFAULT_PAGE = 50
# Envelope root, five keys and four header scalar values surround the document.
_REVISION_HEADER_VALUES = 10
_FLAGS = os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
_CURSOR = re.compile(r"v1:([0-9a-f]{64}):([0-9a-f]{64})")
_MESSAGES = {
    "identity": "invalid campaign identity",
    "identity-mismatch": "document campaign differs from selected campaign",
    "lead-only": "campaign state requires a lead context",
    "not-found": "campaign or requested revision is absent",
    "conflict": "expected head conflicts with selected head",
    "lock-busy": "campaign writer lock is busy",
    "lock-replaced": "campaign writer lock identity changed",
    "private-state": "campaign state metadata is unsafe",
    "corrupt-store": "campaign state failed byte or lineage validation",
    "storage-error": "campaign storage operation failed",
    "durability-unknown": "candidate is visible with uncertain durability",
    "publication-unknown": "candidate publication could not be established",
    "history-walk-limit": "campaign history traversal budget exhausted",
    "not-in-history": "revision is outside selected head ancestry",
    "cursor": "invalid campaign history cursor",
    "bounds": "campaign operation exceeds its input bounds",
    "schema": "invalid campaign operation arguments",
}


class Error(Exception):
    """A refusal with safe diagnostics and structured outcome details."""

    def __init__(self, code, *, message=None, **details):
        self.code = code
        self.message = message or _MESSAGES[code]
        self.details = details
        super().__init__(self.message)


def _need(ok, code):
    if not ok:
        raise Error(code)


def _digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _is_digest(value):
    return type(value) is str and doc.DIGEST.fullmatch(value) is not None


def _private(st, mode, directory=False):
    _need(st.st_uid == os.geteuid() and stat.S_IMODE(st.st_mode) == mode
          and (stat.S_ISDIR(st.st_mode) if directory else
               stat.S_ISREG(st.st_mode) and st.st_nlink == 1), "private-state")


def _open(name, flags, *, parent=None, mode=0o600):
    try:
        return os.open(name, flags | _FLAGS, mode, dir_fd=parent)
    except OSError as error:
        if error.errno in (errno.ELOOP, errno.ENOTDIR, errno.EISDIR, errno.EACCES,
                           errno.EPERM, errno.ENXIO):
            raise Error("private-state") from None
        raise


def _directory(parent, name, create=False, private=True):
    made = False
    try:
        fd = _open(name, os.O_RDONLY | os.O_DIRECTORY, parent=parent)
    except FileNotFoundError:
        if not create:
            raise
        try:
            os.mkdir(name, 0o700, dir_fd=parent)
            made = True
        except FileExistsError:
            pass
        fd = _open(name, os.O_RDONLY | os.O_DIRECTORY, parent=parent)
    try:
        if made:
            os.fchmod(fd, 0o700)
        if private:
            _private(os.fstat(fd), 0o700, directory=True)
        if made:
            os.fsync(fd)
            os.fsync(parent)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _file(parent, name, limit):
    fd = _open(name, os.O_RDONLY, parent=parent)
    try:
        st = os.fstat(fd)
        _private(st, 0o600)
        _need(st.st_size <= limit, "corrupt-store")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(parent, name, limit):
    fd = _file(parent, name, limit)
    try:
        chunks, remaining = [], limit + 1
        while remaining:
            chunk = os.read(fd, remaining)
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        _need(len(raw) <= limit, "corrupt-store")
        return raw
    finally:
        os.close(fd)


def _parse(raw, fields, kind):
    value = (doc._decode(raw, max_bytes=doc.MAX_REVISION_BYTES,
                         max_values=doc.MAX_VALUES + _REVISION_HEADER_VALUES,
                         max_depth=doc.MAX_DEPTH + 1)
             if kind == "campaign-revision" else doc.decode(raw))
    _need(type(value) is dict and set(value) == set(fields.split()), "corrupt-store")
    _need(value["format"] == kind and type(value["version"]) is int
          and value["version"] == 1, "corrupt-store")
    _need(type(value["rev"]) is int and 1 <= value["rev"] <= doc.MAX_REV,
          "corrupt-store")
    return value


class _Session:
    def __init__(self, store, create, stack):
        try:
            self._ancestors(store, create, stack)
        except Error as error:
            error.details["stage"] = "ancestor-access"
            raise
        except OSError as error:
            raise Error("not-found" if isinstance(error, FileNotFoundError) else "storage-error",
                        stage="ancestor-access") from None
        self.campaigns = _directory(self.root, "campaigns", create)
        stack.callback(os.close, self.campaigns)
        self.campaign = _directory(self.campaigns, store.campaign, create)
        stack.callback(os.close, self.campaign)
        self.store = store
        self.stack = stack

    def _ancestors(self, store, create, stack):
        fd = _open("/", os.O_RDONLY | os.O_DIRECTORY)
        stack.callback(os.close, fd)
        self.ancestors = [fd]
        parts = store._root.strip("/").split("/") if store._root != "/" else []
        for part in parts:
            fd = _directory(fd, part, create, private=False)
            stack.callback(os.close, fd)
            self.ancestors.append(fd)
        root_stat = os.fstat(fd)
        _need(root_stat.st_uid == os.geteuid() and not root_stat.st_mode & 0o022,
              "private-state")
        self.root = fd

    def objects(self, create=False):
        try:
            self.objdir = _directory(self.campaign, "objects", create)
        except FileNotFoundError:
            raise Error("corrupt-store") from None
        self.stack.callback(os.close, self.objdir)

    def head(self):
        try:
            raw = _read(self.campaign, "head.json", MAX_HEAD_BYTES)
        except FileNotFoundError:
            return None
        value = _parse(raw, "format version rev revision", "campaign-head")
        _need(_is_digest(value["revision"]) and raw == doc._encode(value), "corrupt-store")
        return value

    def object(self, digest, *, requested=False):
        try:
            raw = _read(self.objdir, digest[7:] + ".json", doc.MAX_REVISION_BYTES)
        except FileNotFoundError:
            raise Error("not-found" if requested else "corrupt-store") from None
        value = _parse(raw, "format version rev previous document", "campaign-revision")
        _need(_digest(raw) == digest, "corrupt-store")
        _need((value["rev"] == 1 and value["previous"] is None)
              or (value["rev"] > 1 and _is_digest(value["previous"])), "corrupt-store")
        value["document"] = doc.validate(value["document"])
        _need(value["document"]["campaign"] == self.store.campaign, "corrupt-store")
        for group in ("requirements", "work", "coordination"):
            _need(all(int(e["id"][1:].partition(":")[0]) <= value["rev"]
                      for e in value["document"][group]), "corrupt-store")
        if value["rev"] == 1:
            doc.transition(None, value["document"], rev=1)
        _need(raw == doc._encode(value), "corrupt-store")
        return dict(value, digest=digest)

    def current(self, head):
        record = self.object(head["revision"])
        _need(record["rev"] == head["rev"], "corrupt-store")
        return record

    def lock(self, create):
        made = False
        try:
            fd = _open(".lock", os.O_RDWR, parent=self.campaign)
        except FileNotFoundError:
            if not create:
                raise Error("private-state") from None
            try:
                fd = _open(".lock", os.O_RDWR | os.O_CREAT | os.O_EXCL,
                           parent=self.campaign)
                made = True
            except FileExistsError:
                fd = _open(".lock", os.O_RDWR, parent=self.campaign)
        self.stack.callback(os.close, fd)
        if made:
            os.fchmod(fd, 0o600)
        _private(os.fstat(fd), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Error("lock-busy") from None
        self.lockfd = fd
        self.lock_check()
        if made:
            os.fsync(fd)
            os.fsync(self.campaign)

    def lock_check(self):
        held = os.fstat(self.lockfd)
        try:
            named = os.stat(".lock", dir_fd=self.campaign, follow_symlinks=False)
        except FileNotFoundError:
            raise Error("lock-replaced") from None
        _need((held.st_dev, held.st_ino) == (named.st_dev, named.st_ino), "lock-replaced")
        _private(named, 0o600)

    def settle(self, head):
        for parent, name, limit in (
                (self.objdir, head["revision"][7:] + ".json", doc.MAX_REVISION_BYTES),
                (self.campaign, "head.json", MAX_HEAD_BYTES)):
            fd = _file(parent, name, limit)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            os.fsync(parent)
        os.fsync(self.campaigns)
        os.fsync(self.root)
        # A retry must also settle a previously uncertain configured-root link.
        self.settle_ancestors()

    def settle_links(self):
        os.fsync(self.lockfd)
        for fd in (self.objdir, self.campaign, self.campaigns, self.root):
            os.fsync(fd)
        self.settle_ancestors()

    def settle_ancestors(self):
        try:
            for fd in reversed(self.ancestors[:-1]):
                os.fsync(fd)
        except OSError:
            raise Error("storage-error", stage="ancestor-fsync") from None

    def temporary(self, parent, raw, prefix):
        name = prefix + uuid.uuid4().hex
        fd = _open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, parent=parent)
        try:
            os.fchmod(fd, 0o600)
            view = memoryview(raw)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(errno.EIO, "short campaign write")
                view = view[written:]
            os.fsync(fd)
        except BaseException:
            os.unlink(name, dir_fd=parent)
            raise
        finally:
            os.close(fd)
        return name

    def publish_object(self, digest, raw):
        name = digest[7:] + ".json"
        try:
            existing = _read(self.objdir, name, doc.MAX_REVISION_BYTES)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            _need(existing == raw, "corrupt-store")
            fd = _file(self.objdir, name, doc.MAX_REVISION_BYTES)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        else:
            temporary = self.temporary(self.objdir, raw, ".tmp-")
            try:
                os.replace(temporary, name, src_dir_fd=self.objdir, dst_dir_fd=self.objdir)
            finally:
                self.remove_temporary(self.objdir, temporary)
        os.fsync(self.objdir)

    @staticmethod
    def remove_temporary(parent, name):
        try:
            os.unlink(name, dir_fd=parent)
        except FileNotFoundError:
            pass


def _summary(record):
    return {key: record[key] for key in ("digest", "rev", "previous")}


def _candidate(parent, document):
    rev = 1 if parent is None else parent["rev"] + 1
    try:
        normalized = doc.transition(None if parent is None else parent["document"], document, rev=rev)
    except doc.Invalid as error:
        raise Error(error.code, message=error.message, **error.details) from None
    envelope = dict(format="campaign-revision", version=1, rev=rev,
                    previous=None if parent is None else parent["digest"], document=normalized)
    raw = doc._encode(envelope)
    _need(len(raw) <= doc.MAX_REVISION_BYTES, "bounds")
    return dict(envelope, digest=_digest(raw)), raw


class Store:
    """One campaign, with explicit commit/show/check/log entry points."""

    def __init__(self, campaign):
        _need(type(campaign) is str and doc.UUID.fullmatch(campaign) is not None
              and campaign != "00000000-0000-0000-0000-000000000000", "identity")
        self.campaign = campaign
        self._root = None

    @contextlib.contextmanager
    def _session(self, create=False):
        try:
            try:
                member = marshal_refs.in_member_run()
            except OSError:
                raise Error("lead-only") from None
            if member:
                raise Error("lead-only")
            if self._root is None:
                self._root = os.path.realpath(paths.state())
            with contextlib.ExitStack() as stack:
                yield _Session(self, create, stack)
        except doc.Invalid as error:
            raise Error("corrupt-store") from error
        except FileNotFoundError:
            raise Error("not-found") from None
        except OSError:
            raise Error("storage-error") from None
        except MemoryError:
            raise Error("bounds") from None

    def _report(self, command, record):
        constants = doc.constants()
        constants["coordination_scope"] = "local-store"
        return dict(format="campaign-report", version=1, command=command, valid=True,
                    campaign=self.campaign, revision=_summary(record),
                    findings=doc.findings(record["document"]), constants=constants,
                    durability="not-assessed")

    def commit(self, document, *, create=False, expected_head=None):
        """Publish a deterministic child or settle an exactly current retry.

        Error.details always includes publication and durability for a commit.
        A failed parent settle also includes parent_durability='unknown'.
        No stale candidate receives credit for appearing further down history.
        """
        publication = "not-assessed"
        parent_settling = False
        try:
            _need(type(create) is bool and ((create and expected_head is None)
                  or (not create and _is_digest(expected_head))), "schema")
            document = doc.validate(document)
            _need(document["campaign"] == self.campaign, "identity-mismatch")
            candidate, raw = _candidate(None, document) if create else (None, None)
            with self._session(create) as session:
                # An absent expected-head target cannot create even a lock.
                before = session.head()
                if before is None and not create:
                    raise Error("not-found")
                session.lock(create=before is None and create)
                head = session.head()
                session.objects(create=head is None and create)
                current = session.current(head) if head is not None else None
                if not create:
                    if current is None:
                        raise Error("not-found")
                    if expected_head == current["digest"]:
                        candidate, raw = _candidate(current, document)
                    else:
                        try:
                            parent = session.object(expected_head, requested=True)
                        except Error as error:
                            if error.code != "not-found":
                                raise
                            parent = None
                        if parent is not None:
                            try:
                                candidate, raw = _candidate(parent, document)
                            except Error:
                                candidate = None
                exact = current is not None and candidate is not None \
                    and candidate["digest"] == current["digest"]
                if candidate is not None:
                    publication = "visible" if exact else "none"
                if current is not None and not exact and (create or expected_head != current["digest"]):
                    raise Error("conflict", current_head=current["digest"],
                                candidate=None if candidate is None else candidate["digest"],
                                candidate_in_history="not-checked")
                if current is not None:
                    parent_settling = not exact
                    session.settle(head)
                    parent_settling = False
                if not exact:
                    session.settle_links()
                    session.publish_object(candidate["digest"], raw)
                    new_head = dict(format="campaign-head", version=1,
                                    rev=candidate["rev"], revision=candidate["digest"])
                    temporary = session.temporary(session.campaign, doc._encode(new_head), ".head-")
                    try:
                        session.lock_check()
                        publication = "unknown"
                        try:
                            os.replace(temporary, "head.json", src_dir_fd=session.campaign,
                                       dst_dir_fd=session.campaign)
                        except OSError:
                            # POSIX excludes EIO from rename's unchanged-destination
                            # guarantee. Observe once under the held writer authority.
                            # https://man7.org/linux/man-pages/man3/rename.3p.html
                            try:
                                session.lock_check()
                                observed = session.head()
                                session.lock_check()
                                if observed == new_head:
                                    publication = "visible"
                                elif observed == head:
                                    publication = "none"
                            except (Error, OSError, doc.Invalid, MemoryError):
                                pass
                            raise
                        publication = "visible"
                    finally:
                        session.remove_temporary(session.campaign, temporary)
                    session.settle(new_head)
                session.lock_check()
                result = self._report("commit", candidate)
                result.update(result="already-current" if exact else "committed",
                              publication="visible", durability="fsync-acknowledged")
                return result
        except MemoryError:
            details = dict(publication=publication,
                           durability="unknown" if publication in ("visible", "unknown")
                           else "not-assessed")
            if parent_settling:
                details["parent_durability"] = "unknown"
            raise Error("bounds", **details) from None
        except doc.Invalid as error:
            raise Error(error.code, message=error.message, **error.details,
                        publication=publication, durability="not-assessed") from None
        except Error as error:
            error.details.update(publication=publication,
                                 durability="unknown" if publication in ("visible", "unknown")
                                 else "not-assessed")
            if parent_settling:
                error.details["parent_durability"] = "unknown"
            if error.code == "storage-error" and publication in ("visible", "unknown"):
                raise Error("durability-unknown" if publication == "visible" else "publication-unknown",
                            **error.details) from None
            raise

    def show(self, revision=None):
        """Return a current document or prove a historical document's ancestry."""
        _need(revision is None or _is_digest(revision), "schema")
        with self._session() as session:
            head = session.head()
            if head is None:
                raise Error("not-found")
            session.objects()
            current = session.current(head)
            record = current
            if revision is not None and revision != current["digest"]:
                target = session.object(revision, requested=True)
                record = self._walk_to(session, current, target, [0], (target,))
            result = self._report("show", record)
            result.update(document=record["document"], selected_head=head["revision"],
                          selected_start=record["digest"],
                          verified_scope="selected-head-ancestry")
            return result

    def check(self):
        """Validate the current snapshot and its transition from its parent."""
        with self._session() as session:
            head = session.head()
            if head is None:
                raise Error("not-found")
            session.objects()
            current = session.current(head)
            parent = None
            if current["previous"] is not None:
                parent = session.object(current["previous"])
                self._edge(current, parent)
            doc.transition(None if parent is None else parent["document"],
                           current["document"], rev=current["rev"])
            result = self._report("check", current)
            result.update(selected_head=head["revision"],
                          transition="checked-create" if parent is None else "checked-current-parent")
            return result

    @staticmethod
    def _edge(child, parent):
        _need(child["previous"] == parent["digest"] and child["rev"] == parent["rev"] + 1,
              "corrupt-store")

    def _previous(self, session, current, budget, hints):
        _need(budget[0] < MAX_HISTORY_EDGES, "history-walk-limit")
        budget[0] += 1
        digest = current["previous"]
        _need(digest is not None, "corrupt-store")
        parent = next((r for r in hints if r["digest"] == digest), None)
        if parent is None:
            parent = session.object(digest)
        self._edge(current, parent)
        return parent

    def _walk_to(self, session, current, target, budget, hints):
        _need(target["rev"] <= current["rev"], "not-in-history")
        _need(current["rev"] - target["rev"] <= MAX_HISTORY_EDGES - budget[0],
              "history-walk-limit")
        while current["rev"] > target["rev"]:
            current = self._previous(session, current, budget, hints)
        _need(current["digest"] == target["digest"], "not-in-history")
        return current

    def log(self, *, cursor=None, limit=DEFAULT_PAGE):
        """Buffer a bounded page and prove its start and entries from one head.

        The cursor is v1:<start hex>:<next hex>. Every page independently proves
        membership. A returned cursor does not certify its next object exists.
        The next request must verify it. No page consumption is authenticated.
        """
        try:
            _need(type(limit) is int and 1 <= limit <= MAX_PAGE, "bounds")
            _need(cursor is None or (type(cursor) is str and _CURSOR.fullmatch(cursor)), "cursor")
            with self._session() as session:
                head = session.head()
                if head is None:
                    raise Error("not-found")
                session.objects()
                current = session.current(head)
                result = self._report("log", current)
                start = current
                budget = [0]
                if cursor is not None:
                    start_hex, next_hex = _CURSOR.fullmatch(cursor).groups()
                    start_digest, next_digest = "sha256:" + start_hex, "sha256:" + next_hex
                    start = current if start_digest == current["digest"] else session.object(start_digest, requested=True)
                    target = start if next_digest == start_digest else session.object(next_digest, requested=True)
                    _need(target["rev"] <= start["rev"], "cursor")
                    hints = (start, target)
                    current = self._walk_to(session, current, start, budget, hints)
                    current = self._walk_to(session, current, target, budget, hints)
                entries = []
                while True:
                    entries.append(_summary(current))
                    if current["rev"] == 1 or len(entries) == limit:
                        break
                    current = self._previous(session, current, budget, ())
                complete = current["rev"] == 1
                result.update(entries=entries, selected_head=head["revision"],
                              selected_start=start["digest"], verified_scope="selected-head-ancestry",
                              complete=complete, cursor=None if complete else
                              "v1:" + start["digest"][7:] + ":" + current["previous"][7:])
                return result
        except Error as error:
            error.details.update(entries=[], complete=False)
            raise
