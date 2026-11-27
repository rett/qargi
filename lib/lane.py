#!/usr/bin/env python3
"""The lane of a sign-in: who holds the lock beside it, who waits for it, and what `qargi local list --lanes` shows.

  lane.py list            one block for each lock file of the runtimes the stored projects declare (the plain links of dispatch.home, and the private
                          links that declare a refresh): the lock, its state, the holder and the waiters. Read-only: it takes no lock of any kind (the
                          holder is read from the record only when /proc/locks says the lock file is held), and nothing is written.

The lane is the flock of lib/local_run.py (LOCK_NAME). Beside it two kinds of small files, all mode 600, advisory only (the flock stays the authority):

  .qargi-lane.json                      the record of the holder, written atomically (a new file renamed over it) while the lock is held and removed before it is
                                        let go: {schema, runtime, kind (run or refresh), lead, run (the slug), runner {pid, start}, member {pid, start} or
                                        null, started}. `start` is the process start token (field 22 of /proc/PID/stat), so a pid that was reused is not taken
                                        for the holder. No path and no value of the sign-in is in it.
  .qargi-lane-wait.PID.START            one for each run that waits for the lock: {pid, start, lead, run, runtime, since}; removed when the wait ends. The
                                        order of a lane's waiters is the order of `since`; one of a process that is gone is ignored.

The files sit in a directory other processes of the user can write, so every field read from them is cut to plain characters before it is printed or compared.
"""
import json
import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

RECORD = ".qargi-lane.json"
WAIT = ".qargi-lane-wait."
LOCK_NAME = ".qargi-run.lock"          # as lib/local_run.py names it
MAX_FILE = 16384                        # bytes read of a record or a waiter file
PLAIN = re.compile(r"[^A-Za-z0-9._:@+-]")


def plain(value, limit=80):
    """The text of a field cut to letters, digits and . _ : @ + - (at most limit of them): what another process wrote is never printed as it is."""
    return PLAIN.sub("", value)[:limit] if isinstance(value, str) else ""


def whole(value, high=2 ** 40):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= high else None


def token(pid):
    """The start token of the process pid (field 22 of /proc/PID/stat, as lib/attempts.py process reads it), or None when there is no such process or it cannot
    be told."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0:
        return None
    try:
        with open("/proc/%d/stat" % pid, "rb") as f:
            data = f.read(8193)
        fields = data[data.rindex(b")") + 2:].split()
        return str(int(fields[19])) if len(fields) >= 20 and fields[0] not in (b"Z", b"X") else None
    except (OSError, ValueError, IndexError):
        return None


def alive(pid, start):
    """Is pid the process that has the start token `start` (a pid that was reused is another process)?"""
    now = token(pid)
    return now is not None and now == start


def lead_identity():
    """The identity of this lead as qargi names it: the coordinator label (QARGI_ACTOR) when there is one, else QARGI_LEAD, else user@host (the marshal's
    anonymous identity), cut to plain characters."""
    ident = os.environ.get("QARGI_ACTOR") or os.environ.get("QARGI_LEAD")
    if not ident:
        try:
            import getpass
            import socket
            ident = "%s@%s" % (getpass.getuser(), socket.gethostname())
        except (OSError, KeyError, ImportError):
            ident = "unknown"
    return plain(ident) or "unknown"


def me():
    pid = os.getpid()
    return {"pid": pid, "start": token(pid) or ""}


def _atomic(path, data):
    """Write data (bytes) as the file at path: a new file of its own (mode 600, made exclusively, never through a link) renamed over the name."""
    tmp = "%s.tmp.%d" % (path, os.getpid())
    try:
        os.unlink(tmp)
    except OSError:
        pass
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view):]
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _read(path):
    """The JSON object in the regular file at path (not followed, at most MAX_FILE bytes), or None."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        data = os.read(fd, MAX_FILE + 1)
        if len(data) > MAX_FILE:
            return None
        doc = json.loads(data.decode("utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        os.close(fd)
    return doc if isinstance(doc, dict) else None


def write_record(d, runtime, kind, run):
    """Write the record of the holder (this process) in directory d, while its lock is held. Best effort: a record that cannot be written is no reason to stop a run
    that holds the lock. Returns what was written."""
    rec = {"schema": 1, "runtime": plain(runtime), "kind": kind, "lead": lead_identity(), "run": plain(run), "runner": me(), "member": None,
           "started": int(time.time())}
    try:
        _atomic(os.path.join(d, RECORD), (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
    except OSError:
        pass
    return rec


def read_record(d):
    """The record of the holder in directory d with every field cut to plain characters and the right type, or None."""
    doc = _read(os.path.join(d, RECORD))
    if doc is None:
        return None
    out = {"runtime": plain(doc.get("runtime")), "kind": plain(doc.get("kind"), 12), "lead": plain(doc.get("lead")),
           "run": plain(doc.get("run")), "started": whole(doc.get("started")), "runner": None, "member": None}
    for who in ("runner", "member"):
        v = doc.get(who)
        if isinstance(v, dict) and whole(v.get("pid")) and isinstance(v.get("start"), str):
            out[who] = {"pid": v["pid"], "start": plain(v["start"], 24)}
    return out


def set_member(d, pid):
    """Add the member (its pid and start token) to the record this process wrote in d, or remove it (pid None); nothing when the record is not this process's."""
    rec = _read(os.path.join(d, RECORD))
    mine = me()
    if not rec or not isinstance(rec.get("runner"), dict) or rec["runner"].get("pid") != mine["pid"] or rec["runner"].get("start") != mine["start"]:
        return
    rec["member"] = {"pid": pid, "start": token(pid) or ""} if pid else None
    try:
        _atomic(os.path.join(d, RECORD), (json.dumps(rec, sort_keys=True) + "\n").encode("utf-8"))
    except OSError:
        pass


def clear_record(d):
    """Remove the record in d when it is this process's (the lock is still held by the caller): another holder's is never touched."""
    rec = _read(os.path.join(d, RECORD))
    mine = me()
    if rec and isinstance(rec.get("runner"), dict) and rec["runner"].get("pid") == mine["pid"] and rec["runner"].get("start") == mine["start"]:
        try:
            os.unlink(os.path.join(d, RECORD))
        except OSError:
            pass


def add_waiter(d, runtime, run):
    """Make this process's waiter file in d (a run that waits for the lock): the path to hand to remove_waiter, or None when it cannot be made."""
    mine = me()
    path = os.path.join(d, "%s%d.%s" % (WAIT, mine["pid"], mine["start"]))
    info = {"pid": mine["pid"], "start": mine["start"], "lead": lead_identity(), "run": plain(run), "runtime": plain(runtime), "since": time.time_ns()}
    try:
        _atomic(path, (json.dumps(info, sort_keys=True) + "\n").encode("utf-8"))
    except OSError:
        return None
    return path


def remove_waiter(path):
    if path:
        try:
            os.unlink(path)
        except OSError:
            pass


def waiters(d):
    """The runs waiting for the lock of directory d, in the order they began to wait: [{pid, lead, run, since (ns)}]. A file of a process that is gone (or whose
    pid was reused) is ignored; so is anything that is not a waiter file."""
    out = []
    try:
        names = os.listdir(d)
    except OSError:
        return out
    for n in names:
        m = re.fullmatch(re.escape(WAIT) + r"([0-9]{1,9})\.([0-9]{1,24})", n)
        if not m or not alive(int(m.group(1)), m.group(2)):
            continue
        doc = _read(os.path.join(d, n)) or {}
        since = whole(doc.get("since"), 2 ** 63)
        if since is None:
            try:
                since = os.lstat(os.path.join(d, n)).st_mtime_ns
            except OSError:
                since = 0
        out.append({"pid": int(m.group(1)), "lead": plain(doc.get("lead")) or "?", "run": plain(doc.get("run")) or "?", "since": since})
    return sorted(out, key=lambda w: (w["since"], w["pid"]))


def position(d):
    """(ahead, total): how many waiters began before this process, and how many wait (this one included); (0, 1) when it is not among them."""
    mine = os.getpid()
    ws = waiters(d)
    for i, w in enumerate(ws):
        if w["pid"] == mine:
            return i, len(ws)
    return 0, len(ws) + 1


def age_text(seconds):
    seconds = max(int(seconds), 0)
    if seconds >= 86400:
        return "%dd" % (seconds // 86400)
    if seconds >= 3600:
        return "%dh%02dm" % (seconds // 3600, seconds % 3600 // 60)
    if seconds >= 60:
        return "%dm" % (seconds // 60)
    return "%ds" % seconds


def holder_state(rec):
    """What the record says of the holder, checked against the processes: 'running' (its runner lives), 'member alive, runner gone' (the runner is dead and the
    member lives), 'gone' (both dead: the record is stale)."""
    runner_up = bool(rec["runner"]) and alive(rec["runner"]["pid"], rec["runner"]["start"])
    member_up = bool(rec["member"]) and alive(rec["member"]["pid"], rec["member"]["start"])
    return "running" if runner_up else "member alive, runner gone" if member_up else "gone"


def holder_line(d, now=None):
    """One line naming the holder of the lock in d, from its record: the lead, the run and how long it has held it; or why there is none to name."""
    rec = read_record(d)
    if rec is None:
        return "holder not recorded (a run of an earlier qargi, or one that has only just started)"
    state = holder_state(rec)
    if state == "gone":
        return "the record names lead %s, run %s, but its runner and member are not there any more" % (rec["lead"] or "?", rec["run"] or "?")
    age = age_text((now or time.time()) - rec["started"]) if rec["started"] is not None else "?"
    return "holder is lead %s, run %s, holding it for %s%s" % (rec["lead"] or "?", rec["run"] or "?", age, "" if state == "running" else " (member alive, runner gone)")


def holder_brief(d, now=None):
    """(label of the holder for a refusal: 'lead L run R' or 'unknown', age in seconds)."""
    rec = read_record(d)
    if rec is None or holder_state(rec) == "gone":
        return "unknown", 0
    return "lead %s run %s" % (rec["lead"] or "?", rec["run"] or "?"), max(int((now or time.time()) - (rec["started"] or 0)), 0) if rec["started"] else 0


UNKNOWN = "unknown"


def match_flock(text, st_dev, ino):
    """Is a flock on the file (the device number st_dev of os.stat, the inode ino) in the text of /proc/locks? True (held), False (no lock of that file), or UNKNOWN
    when a line has the inode number but its device cannot be compared with the file's. A line reads ID: FLOCK ADVISORY WRITE PID MAJOR:MINOR:INODE START END (major
    and minor in hex); the line of a lock that waits (->) is passed over. The inode number alone is no identity, for another file system holds the same number, so
    the device is compared as well: equal is held, and unequal with both known is another file's lock. A device that is not known (st_dev None, or 00:00 in the
    line), or whose major number is 0 on either side (an anonymous device, which a file system such as btrfs or an overlay can report to stat and not to /proc/locks)
    cannot be compared: the answer is then UNKNOWN, never held."""
    unsure = False
    for line in text.splitlines():
        parts = line.split()
        if "->" in parts or len(parts) < 6 or parts[1] != "FLOCK":
            continue
        for p in parts:
            q = p.split(":")
            if len(q) != 3 or not q[2].isdigit() or int(q[2]) != ino:
                continue
            try:
                dev = os.makedev(int(q[0], 16), int(q[1], 16))
            except (ValueError, OverflowError):
                dev = None
            if not dev or st_dev is None:
                unsure = True
            elif dev == st_dev:
                return True
            elif os.major(dev) == 0 or os.major(st_dev) == 0:
                unsure = True
    return UNKNOWN if unsure else False


def held(path):
    """Is the flock on the lock file at path held by some process? Read from /proc/locks by the device and the inode number (match_flock; a device that cannot be
    compared makes the answer UNKNOWN, never held); no lock is ever taken, not even for a moment. None when /proc/locks cannot be read, False when the file is
    not there."""
    try:
        st = os.stat(path)
    except OSError:
        return False
    try:
        with open("/proc/locks", encoding="ascii", errors="replace") as f:
            return match_flock(f.read(), st.st_dev, st.st_ino)
    except OSError:
        return None


# ---- qargi local list --lanes -------------------------------------------------------------------------------------------------------

def declared_locks():
    """[(runtime, declared lock name ~/DIR/.qargi-run.lock, real lock path)] for each lock file of the runtimes the stored projects declare, once each: the
    plain links of dispatch.home and the private links that declare a refresh (the refresh takes the lock beside the source). The path is the one a run uses
    (beside the real file of the source), so a source that is a link elsewhere is followed. Nothing is made."""
    import provider as P
    import paths
    seen, out = set(), []
    base = os.path.realpath(os.path.expanduser("~"))
    try:
        files = sorted(os.listdir(os.path.join(paths.conf(), "projects")))
    except OSError:
        return out
    for f in files:
        m = re.fullmatch(r"([a-z][a-z0-9]{0,23})\.json", f)
        if not m:
            continue
        try:
            primary, extra = P.local_runtimes_of(m.group(1))
        except Exception:                                  # a project with no local runtime, or one whose answers are broken, has no lane to show
            continue
        for rt in [primary] + list(extra):
            try:
                disp = P.compose(rt, "local", m.group(1))["definition"].get("dispatch") or {}
            except Exception:
                continue
            home = disp.get("home") if isinstance(disp, dict) else None
            for ln in (home.get("link") if isinstance(home, dict) and isinstance(home.get("link"), list) else []):
                frm = ln.get("from") if isinstance(ln, dict) else None
                if not isinstance(frm, str) or not frm.startswith("~/") or P.home_link_problem(frm):
                    continue
                if "private" in ln and not (isinstance(ln["private"], dict) and "refresh" in ln["private"]):
                    continue
                real = os.path.join(os.path.dirname(os.path.realpath(os.path.join(base, frm[2:]))), LOCK_NAME)
                if real in seen:
                    continue
                seen.add(real)
                out.append((rt, os.path.join(os.path.dirname(frm), LOCK_NAME), real))
    return out


def lanes_text(now=None):
    """The lines of `qargi local list --lanes`: for each declared lock file its state (free, held, member alive and runner gone), the holder and the waiters."""
    now = now or time.time()
    locks = declared_locks()
    if not locks:
        return ["no lane: no runtime of a stored project shares a sign-in lock (a private link takes none unless it declares a refresh)"]
    lines = ["%-12s %-34s %-26s %s" % ("RUNTIME", "LOCK", "STATE", "HOLDER")]
    for rt, shown, real in locks:
        d = os.path.dirname(real)
        is_held = held(real)
        rec = read_record(d)
        shown_waiters = False
        if is_held is None:
            state, who = "unknown (/proc/locks cannot be read)", ""
        elif not is_held:
            state, who = "free", ""
        else:
            unsure = is_held == UNKNOWN                      # /proc/locks has the inode but its device cannot be compared with stat's: held only on the word of a record that is alive
            hs = holder_state(rec) if rec else None
            if rec is None or hs == "gone":
                state, who = ("unknown (device not comparable)", "") if unsure else ("held", "not recorded" if rec is None else "recorded for a run that is gone")
            else:
                state = ("unknown (device not comparable)" if unsure else "held") + ("" if hs == "running" else ", member alive, runner gone")
                who = "lead %s run %s (%s, %s)" % (rec["lead"] or "?", rec["run"] or "?", rec["kind"] or "run", age_text(now - rec["started"]) if rec["started"] is not None else "?")
                shown_waiters = True
            shown_waiters = shown_waiters or not unsure
        lines.append("%-12s %-34s %-26s %s" % (plain(rt, 12), shown, state, who))
        for i, w in enumerate(waiters(d) if shown_waiters else []):
            lines.append("  waiting %d: lead %s run %s (%s)" % (i + 1, w["lead"], w["run"], age_text(now - w["since"] / 1e9)))
    return lines


def main(argv):
    if argv[:1] == ["list"] and len(argv) == 1:
        for line in lanes_text():
            print(line)
        return 0
    sys.stderr.write("usage: lane.py list\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
