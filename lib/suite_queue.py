#!/usr/bin/env python3
"""The queue of the whole-suite runs of one user: two of them never overlap on one host.

A whole-suite run (qargi feature verify, qargi release verify, qargi suite run -- COMMAND) takes one slot of the queue for as long as its suite runs and not
a moment longer. The slot is a kernel lock (flock) on a file of the state directory; the waiting is first in, first out. Files of the directory $QARGI_STATE/suite-queue
(mode 700; every file mode 600, advisory only: the flock stays the authority):

  lock                      the file the flock is taken on. The shell that runs the suite opens it and keeps the descriptor for exactly that long (lib/suite_queue.sh),
                            and the lock is the kernel's, so no run can leave it held: it is freed when the last process that has the descriptor ends, whatever way
                            it ends. That is the shell and the subshell that waits for the suite; what the suite starts (an exec) never has the descriptor, so a
                            daemon a test leaves behind cannot keep the slot. A verb that is killed while its suite runs leaves the slot taken until that suite ends.
  holder.json               the record of the holder, written atomically (a new file renamed over it) once the lock is held and removed before it is let go:
                            {schema, pid, start, project, verb, name, head, started}. `start` is the process start token (field 22 of /proc/PID/stat), so a pid that was
                            reused is not taken for the holder; pid is the shell that holds the descriptor. A record whose process is gone is ignored.
  wait.PID.START            one for each run that waits: {schema, pid, start, project, verb, name, head, enqueued (ns)}; removed when the wait ends. The order of
                            the waiters is the order of `enqueued`; a file of a process that is gone is ignored and removed by the next waiter. Only the first of the live
                            waiters tries the flock, which is what makes the order first in, first out and not whoever polls first.

The shape is that of lib/lane.py (a record of the holder, waiter files, a start token to tell a reused pid), which this module uses for those parts. The files sit in a
directory only their user can write, but every field read from them is cut to plain characters before it is printed or compared.

  suite_queue.py prepare --state DIR                    make the directory and the lock file; print the directory
  suite_queue.py acquire --state DIR --fd N --owner PID --project P --verb V --name N [--head H] [--bound SECONDS] [--result FILE] [--poll S]
                                                        wait in line and take the flock on the descriptor N (an inherited descriptor of the lock file: the lock
                                                        belongs to the open file description, so it stays held by the process that owns the descriptor after this
                                                        one exits), then write the record of the holder. OWNER is the pid of that process: the waiter file and the record
                                                        carry it, and this command stops when it is gone. While it waits it prints one line on standard error naming
                                                        the holder and the position, again only when one of them changes. Exit 0 (taken), 4 (the bound ran out;
                                                        nothing was taken or left behind), 3 (the owner is gone), 1 (an error), 2 (a wrong call). RESULT gets
                                                        `status=ok|busy`, `waited=SECONDS` (whole seconds, rounded up, 0 when it did not have to wait; rounded down for busy) and, for busy,
                                                        `holder=TEXT`.
  suite_queue.py release --state DIR --owner PID        remove the record of the holder and the waiter file of OWNER (the shell then closes its descriptor)
  suite_queue.py status --state DIR [--json]            the slot, its holder and the waiters in the order of the queue; with --json one document of the draft kind
                                                        qargi-suite-queue. Read-only: no lock is taken, nothing is removed, no process is signalled (/proc/locks says
                                                        whether the lock is held)
  suite_queue.py pids --state DIR                       the pids of the holder and of the waiters that are alive, one line, space separated (for the warning of other runs)
  suite_queue.py project                                the project in effect here (QARGI_PROJECT, else the one whose repository holds the current directory), or nothing

Exit status of status: 0 after a document or the text, 1 for a queue that cannot be read, 2 for a wrong call, 70 for a document that fails its registry file
(nothing is printed). Moving a run forward in the queue is not offered.
"""
import argparse
import errno
import fcntl
import json
import math
import os
import re
import signal
import stat
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import lane as L  # noqa: E402  (the record of the holder, the waiter files and the start token of a process: the shape of the lane of a sign-in)

KIND = "qargi-suite-queue"
SCHEMA = 1
LOCK = "lock"
RECORD = "holder.json"
WAIT = "wait."
POLL = 0.2
EX_BUSY = 4
EX_GONE = 3
TEXT = re.compile(r"[^A-Za-z0-9._:@+/ -]")
HEAD = re.compile(r"^[0-9a-f]{7,64}$")
PROJECT = re.compile(r"^[a-z][a-z0-9]{0,23}$")


class QueueError(Exception):
    """The queue cannot be used (a directory that is a link, a file that cannot be made)."""


class Defect(QueueError):
    """A document of qargi that fails the registry file of its own kind: a defect of qargi, never of the queue."""


def text(value, limit=80):
    """A field cut to letters, digits and . _ : @ + - / and the space (at most limit of them): what another process wrote is never printed as it is."""
    return TEXT.sub("", value).strip()[:limit] if isinstance(value, str) else ""


def whole(value, high=2 ** 40):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= high else None


def queue_dir(state):
    return os.path.join(state, "suite-queue")


def prepare(state):
    """The queue directory (mode 700) and its lock file (mode 600), made when missing; a link in their place is refused. Returns the directory."""
    d = queue_dir(state)
    try:
        if os.path.islink(d):
            raise QueueError("%s is a link" % d)
        os.makedirs(state, exist_ok=True)
        try:
            os.mkdir(d, 0o700)
        except FileExistsError:
            pass
        if not stat.S_ISDIR(os.lstat(d).st_mode):
            raise QueueError("%s is not a directory" % d)
        if os.lstat(d).st_mode & 0o077:
            os.chmod(d, 0o700)
        fd = os.open(os.path.join(d, LOCK), os.O_RDONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            if os.fstat(fd).st_mode & 0o077:
                os.fchmod(fd, 0o600)
        finally:
            os.close(fd)
    except OSError as e:
        raise QueueError("cannot make %s: %s" % (d, e.strerror or e))
    return d


def who(pid):
    """{pid, start} of the process pid, or None when it is not alive."""
    start = L.token(pid)
    return None if start is None else {"pid": pid, "start": start}


def info(project, verb, name, head):
    """What a run says of itself: the project (a name, or empty), the verb, the name of the feature, version or command, and the commit (hex, or empty)."""
    head = head if isinstance(head, str) and HEAD.match(head) else ""
    project = project if isinstance(project, str) and PROJECT.match(project) else ""
    return {"project": project, "verb": text(verb, 40), "name": text(name, 80), "head": head}


def _write(path, doc):
    L._atomic(path, (json.dumps(doc, sort_keys=True) + "\n").encode("utf-8"))


def _clean(doc, extra):
    """The fields of a record or a waiter file as plain values; None when it names no process."""
    pid, start = whole(doc.get("pid"), 2 ** 31), doc.get("start")
    if not pid or not isinstance(start, str) or not re.fullmatch(r"[0-9]{1,24}", start):
        return None
    out = {"pid": pid, "start": start, "project": text(doc.get("project"), 24), "verb": text(doc.get("verb"), 40), "name": text(doc.get("name"), 80),
           "head": doc.get("head") if isinstance(doc.get("head"), str) and HEAD.match(doc["head"]) else ""}
    out.update(extra)
    return out


def read_holder(d):
    """The record of the holder in d with every field cut to plain characters, or None (no record, or one that names no process). Whether its process lives is
    for the caller: see live_holder."""
    doc = L._read(os.path.join(d, RECORD))
    if doc is None:
        return None
    return _clean(doc, {"started": whole(doc.get("started"), 2 ** 40)})


def live_holder(d):
    """The record of the holder when its process is alive, else None (a record of a run that was killed stays in the file; it is no holder)."""
    rec = read_holder(d)
    return rec if rec and L.alive(rec["pid"], rec["start"]) else None


def waiters(d, remove=False):
    """The runs waiting in d, in the order they began to wait: [{pid, start, project, verb, name, head, enqueued (ns)}]. A file of a process that is gone (or
    whose pid was reused) is ignored, and removed when `remove` is true; so is nothing else: a file that is no waiter file is left alone."""
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        m = re.fullmatch(re.escape(WAIT) + r"([0-9]{1,9})\.([0-9]{1,24})", n)
        if not m:
            continue
        pid, start = int(m.group(1)), m.group(2)
        path = os.path.join(d, n)
        if not L.alive(pid, start):
            if remove:
                try:
                    os.unlink(path)
                except OSError:
                    pass
            continue
        doc = L._read(path) or {}
        enq = whole(doc.get("enqueued"), 2 ** 63)
        if enq is None:
            try:
                enq = os.lstat(path).st_mtime_ns
            except OSError:
                enq = 0
        row = _clean(dict(doc, pid=pid, start=start), {"enqueued": enq})
        if row:
            out.append(row)
    return sorted(out, key=lambda w: (w["enqueued"], w["pid"]))


def waiter_path(d, me):
    return os.path.join(d, "%s%d.%s" % (WAIT, me["pid"], me["start"]))


def holder_text(rec):
    """`PROJECT VERB NAME` of a record, as a refusal and a waiting line name it."""
    return " ".join(w for w in (rec["project"], rec["verb"], rec["name"]) if w) or "unknown"


def age_text(seconds):
    return L.age_text(seconds)


def lock_held(d):
    """True or False (the flock on the lock file is held, or is not: read from /proc/locks, no lock is taken), or None when that cannot be told."""
    h = L.held(os.path.join(d, LOCK))
    return None if h is None or h == L.UNKNOWN else bool(h)


def describe(d, ahead, now=None):
    """The one line of the wait: the holder and the position."""
    now = now or time.time()
    rec = live_holder(d)
    gone = read_holder(d)
    if rec and rec["started"] is not None:
        who_ = "holder is %s (running %s)" % (holder_text(rec), age_text(now - rec["started"]))
    elif rec:
        who_ = "holder is %s" % holder_text(rec)
    elif lock_held(d) and gone:
        who_ = "holder is %s, whose verb is gone (its suite still holds the slot)" % holder_text(gone)
    elif lock_held(d):
        who_ = "holder is not recorded"
    else:
        who_ = "no holder, the run ahead takes the slot"
    return "qargi: suite queue: position %d, %s" % (ahead + 1, who_)


def acquire(d, fd, owner, inf, bound=None, err=None, poll=POLL, clock=time.monotonic):
    """Waits in line and takes the flock on fd for the process `owner`. Returns (status, waited seconds, holder text): status is ok, busy (the bound ran out) or
    gone (the owner died). The waiter file is removed whatever way this ends."""
    err = err if err is not None else sys.stderr
    me = who(owner)
    if me is None:
        return "gone", 0, ""
    path = waiter_path(d, me)
    doc = dict(inf, schema=SCHEMA, pid=me["pid"], start=me["start"], enqueued=time.time_ns())

    def put():
        try:
            _write(path, doc)
        except OSError as e:
            raise QueueError("cannot write %s: %s" % (path, e.strerror or e))

    put()
    t0, shown, had_to_wait = clock(), None, False
    try:
        while True:
            if not L.alive(me["pid"], me["start"]):
                return "gone", 0, ""
            ws = waiters(d, remove=True)
            ahead = next((i for i, w in enumerate(ws) if w["pid"] == me["pid"] and w["start"] == me["start"]), None)
            if ahead is None:                           # the file was removed under us: it stands again, with the time it always had
                put()
                continue
            if ahead == 0:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as e:
                    if e.errno not in (errno.EAGAIN, errno.EACCES, errno.EWOULDBLOCK):
                        raise QueueError("cannot take the lock: %s" % (e.strerror or e))
                else:
                    try:
                        _write(os.path.join(d, RECORD), dict(inf, schema=SCHEMA, pid=me["pid"], start=me["start"], started=int(time.time())))
                    except OSError:
                        pass                            # the record is advisory: a slot that is held is held
                    return "ok", int(math.ceil(clock() - t0)) if had_to_wait else 0, ""
            had_to_wait = True
            rec = live_holder(d)
            key = (ahead, rec["pid"] if rec else None, rec["start"] if rec else None)
            if key != shown:
                print(describe(d, ahead), file=err)
                err.flush()
                shown = key
            elapsed = clock() - t0
            if bound is not None and elapsed >= bound:
                return "busy", int(elapsed), holder_text(rec) if rec else "unknown"      # whole seconds waited, rounded down: never less than the bound
            time.sleep(poll if bound is None else max(min(poll, bound - elapsed), 0.005))
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def release(d, owner):
    """Removes the record of the holder when it is the owner's, and the owner's waiter file; the caller then closes its descriptor."""
    me = who(owner)
    if me is None:
        return
    rec = read_holder(d)
    if rec and rec["pid"] == me["pid"] and rec["start"] == me["start"]:
        try:
            os.unlink(os.path.join(d, RECORD))
        except OSError:
            pass
    try:
        os.unlink(waiter_path(d, me))
    except OSError:
        pass


# ---- qargi suite status -------------------------------------------------------------------------------------------------------

def status_data(state, now=None):
    """The document of the kind qargi-suite-queue: the state of the slot (free, held, unknown), the holder (or None) and the waiters in order."""
    now = now or time.time()
    d = queue_dir(state)
    if not os.path.isdir(d):
        return {"schema": SCHEMA, "kind": KIND, "state": "free", "holder": None, "waiting": []}
    held = lock_held(d)
    rec = live_holder(d)
    if held is False:
        word, rec = "free", None
    elif held is True:
        word = "held"
    else:
        word = "held" if rec else "unknown"
    holder = None
    if rec:
        holder = {"pid": rec["pid"], "project": rec["project"] or None, "verb": rec["verb"], "name": rec["name"], "head": rec["head"] or None,
                  "age_seconds": max(int(now - rec["started"]), 0) if rec["started"] is not None else 0}
    waiting = [{"position": i + 1, "pid": w["pid"], "project": w["project"] or None, "verb": w["verb"], "name": w["name"], "head": w["head"] or None,
                "waiting_seconds": max(int(now - w["enqueued"] / 1e9), 0)} for i, w in enumerate(waiters(d))]
    return {"schema": SCHEMA, "kind": KIND, "state": word, "holder": holder, "waiting": waiting}


def status_text(doc):
    word = doc["state"]
    if doc["holder"] is None and not doc["waiting"]:
        return "suite queue: %s; nothing waits\n" % ("free" if word == "free" else word + ", holder not recorded")
    rows = [("POSITION", "PROJECT", "VERB", "NAME", "HEAD", "AGE", "PID")]
    h = doc["holder"]
    if h:
        rows.append(("holder", h["project"] or "-", h["verb"] or "-", h["name"] or "-", (h["head"] or "-")[:8], age_text(h["age_seconds"]), str(h["pid"])))
    for w in doc["waiting"]:
        rows.append((str(w["position"]), w["project"] or "-", w["verb"] or "-", w["name"] or "-", (w["head"] or "-")[:8], age_text(w["waiting_seconds"]), str(w["pid"])))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    head = "suite queue: %s%s" % (word, "" if h else ", holder not recorded")
    return head + "\n" + "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows) + "\n"


def document(doc):
    """The text of the document, checked against its registry file before it is printed (R-J9)."""
    import jsonkind as K
    try:
        out = json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=1, allow_nan=False) + "\n"
    except (ValueError, TypeError) as e:
        raise Defect("the document of %s cannot be written as JSON (%s)" % (KIND, e))
    try:
        found = K.validate(K.registry_path(KIND), out)
    except K.RegistryError as e:
        raise Defect("the document of %s cannot be checked: %s" % (KIND, e))
    if found:
        raise Defect("the document of %s breaks its registry file at %s %s: %s" % (KIND, found[0].rule, found[0].path, found[0].message))
    return out


def emit(out):
    try:
        sys.stdout.write(out)
        sys.stdout.flush()
    except (OSError, ValueError) as e:
        print("qargi: cannot write the report: %s" % (getattr(e, "strerror", None) or e), file=sys.stderr)
        return 1
    return 0


# ---- the command line ---------------------------------------------------------------------------------------------------------

def _stop(signum, frame):
    raise SystemExit(128 + signum)


def acquire_main(a):
    for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):    # a signal ends the wait through the `finally` that removes the waiter file (a background job starts with SIGINT ignored)
        signal.signal(s, _stop)
    try:
        d = queue_dir(a.state)
        if not stat.S_ISREG(os.fstat(a.fd).st_mode):
            raise QueueError("descriptor %d is not the lock file" % a.fd)
        status, waited, holder = acquire(d, a.fd, a.owner, info(a.project, a.verb, a.name, a.head), a.bound, poll=a.poll)
    except (QueueError, OSError) as e:
        print("qargi: suite queue: %s" % (getattr(e, "strerror", None) or e), file=sys.stderr)
        return 1
    lines = ["status=%s" % ("ok" if status == "ok" else "busy" if status == "busy" else "gone"), "waited=%d" % waited]
    if status == "busy":
        lines.append("holder=%s" % holder)
    if a.result:
        try:
            L._atomic(a.result, ("\n".join(lines) + "\n").encode("utf-8"))
        except OSError as e:
            print("qargi: suite queue: cannot write %s: %s" % (a.result, e.strerror or e), file=sys.stderr)
            return 1
    return {"ok": 0, "busy": EX_BUSY, "gone": EX_GONE}[status]


def main(argv):
    p = argparse.ArgumentParser(prog="suite_queue.py", allow_abbrev=False)
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("prepare")
    s.add_argument("--state", required=True)
    s = sub.add_parser("acquire")
    s.add_argument("--state", required=True)
    s.add_argument("--fd", type=int, required=True)
    s.add_argument("--owner", type=int, required=True)
    s.add_argument("--project", default="")
    s.add_argument("--verb", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--head", default="")
    s.add_argument("--bound", type=float, default=None)
    s.add_argument("--result", default="")
    s.add_argument("--poll", type=float, default=POLL)
    s = sub.add_parser("release")
    s.add_argument("--state", required=True)
    s.add_argument("--owner", type=int, required=True)
    s = sub.add_parser("status")
    s.add_argument("--state", required=True)
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("pids")
    s.add_argument("--state", required=True)
    sub.add_parser("project")
    a = p.parse_args(argv)
    try:
        if a.what == "prepare":
            print(prepare(a.state))
            return 0
        if a.what == "acquire":
            if a.bound is not None and a.bound < 0 or a.poll <= 0:
                p.error("--bound is 0 or more seconds and --poll more than 0")
            return acquire_main(a)
        if a.what == "release":
            release(queue_dir(a.state), a.owner)
            return 0
        if a.what == "pids":
            d = queue_dir(a.state)
            rec = live_holder(d)
            print(" ".join(str(x) for x in ([rec["pid"]] if rec else []) + [w["pid"] for w in waiters(d)]))
            return 0
        if a.what == "project":
            from help import infer_project
            print(infer_project() or "")
            return 0
        doc = status_data(a.state)
        return emit(document(doc) if a.json else status_text(doc))
    except Defect as e:
        print("qargi: %s; this is a defect of qargi, not of the queue" % e, file=sys.stderr)
        return 70
    except (QueueError, OSError) as e:
        print("qargi: suite queue: %s" % (getattr(e, "strerror", None) or e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
