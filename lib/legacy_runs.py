#!/usr/bin/env python3
"""What `qargi local clean --applied --legacy` needs of Python: sizes, liveness, and the archive that comes before a legacy run is removed.

  legacy_runs.py size RUN...                       one line for each run: its apparent size in bytes (the sum of what lstat says for every entry; no link followed) and its path
  legacy_runs.py live RUN...                       the runs (one path to a line) that have a live runner or member: the runner and the member the run's dispatch.json records
                                                   (lib/local_run.py proc_of_run, the test `local run` and `local clean` use), and any process whose environment carries
                                                   QARGI_MEMBER_RUN=RUN (the mark the marshal reads to tell that a member is working)
  legacy_runs.py archive STATE RUN                 STATE/runs-archive/NAME.tar.gz (NAME is the run's directory name): out/, the run's records and bundle, the lead's saved copy of it
                                                   (STATE/runs/NAME) and its registry line (read from standard input) in one archive; written beside it and moved into place only after
                                                   it was read back in full (the gzip checksum too) and its list of entries (name, kind, size, link target, sha256 of each file) matched
                                                   the list made from the files, and after it and the directory were flushed to disk (fsync), so that removing the run next leaves a
                                                   copy even if the machine stops. An archive that is there already is checked the same way and kept when it matches; one that does not is never replaced.
                                                   A hard link in out/ is archived as a file of its own; a socket cannot be archived and is named as the reason.
                                                   Prints "archive PATH BYTES FILES" and exits 0; exits 1 with the reason on standard error.

Read-only on the run, the saved copy and the state, except for the one archive it writes. python3 -I, standard library only."""
import hashlib, io, json, os, stat, sys, tarfile

RECORDS = ("refs.before", "refs.after", "refs.accepted", "refs.diff", "verified", "applied", "started", "ability", "class", "profile", "task.md", "run.bundle")


def size_of(path):
    total = 0
    try:
        total += os.lstat(path).st_size
    except OSError:
        return 0
    for base, dirs, files in os.walk(path, followlinks=False):
        for n in dirs + files:
            try:
                total += os.lstat(os.path.join(base, n)).st_size
            except OSError:
                pass
    return total


def member_marks():
    """The set of runs that some process names in QARGI_MEMBER_RUN: one pass over /proc."""
    seen = set()
    try:
        pids = [n for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return seen
    key = b"QARGI_MEMBER_RUN="
    for p in pids:
        try:
            with open("/proc/%s/environ" % p, "rb") as f:
                for item in f.read(1 << 20).split(b"\0"):
                    if item.startswith(key):
                        seen.add(os.fsdecode(item[len(key):]))
        except OSError:
            continue
    return seen


def live(runs):
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import local_run
    marks = member_marks()
    out = []
    for run in runs:
        real = os.path.realpath(run)
        why = None
        if run in marks or real in marks:
            why = "a process carries QARGI_MEMBER_RUN for it"
        else:
            rec = os.path.join(run, "dispatch.json")
            try:
                st = os.lstat(rec)
                if stat.S_ISREG(st.st_mode):
                    with open(rec, "rb") as f:
                        d = json.loads(f.read(1 << 20).decode("utf-8", "replace"))
                    if isinstance(d, dict):
                        if d.get("outcome") == "running" and local_run.proc_of_run(d.get("runner"), real, "runner"):
                            why = "its runner is alive"
                        elif local_run.proc_of_run(d.get("member"), real, "member"):
                            why = "its member is alive"
            except (OSError, ValueError, RecursionError):
                pass
        if why:
            out.append((run, why))
    return out


def entries(run, saved, name, record_text):
    """[(arcname, path or None, kind, size, link target, sha256 of a file's content)] in a fixed order: the records, out/, the saved copy, the registry line."""
    rows = []

    def add(arc, path):
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            rows.append((arc, path, "dir", 0, "", ""))
        elif stat.S_ISLNK(st.st_mode):
            rows.append((arc, path, "link", 0, os.readlink(path), ""))
        elif stat.S_ISREG(st.st_mode):
            h, n = digest_of(path)
            rows.append((arc, path, "file", n, "", h))
        elif stat.S_ISSOCK(st.st_mode):
            raise OSError("%s is a socket: a socket cannot be archived (tar has no entry for it); remove it, then archive the run again" % path)
        else:
            rows.append((arc, path, "other", 0, "", ""))

    def tree(arc, path):
        add(arc, path)
        if os.path.isdir(path) and not os.path.islink(path):
            for n in sorted(os.listdir(path)):
                tree(arc + "/" + n, os.path.join(path, n))

    rows.append((name, None, "dir", 0, "", ""))
    for r in RECORDS:
        p = os.path.join(run, r)
        if os.path.lexists(p):
            add(name + "/" + r, p)
    out = os.path.join(run, "out")
    if os.path.lexists(out):
        tree(name + "/out", out)
    if saved and os.path.isdir(saved) and not os.path.islink(saved):
        tree(name + "/saved", saved)
    data = record_text.encode()
    rows.append((name + "/record.json", None, "file", len(data), "", hashlib.sha256(data).hexdigest()))
    return rows


def digest_of(path):
    """(sha256 hex, bytes read) of the file's content."""
    h, n = hashlib.sha256(), 0
    with open(path, "rb") as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def kind_of(ti):
    if ti.isdir():
        return "dir"
    if ti.issym():
        return "link"
    if ti.isreg():
        return "file"
    return "other"


def check(dest, rows):
    """None when the archive at DEST holds exactly ROWS (read back in full: the gzip checksum, every member and the sha256 of each file), else the reason."""
    try:
        if os.path.getsize(dest) <= 0:
            return "the archive is empty"
        got = {}
        with tarfile.open(dest, "r:gz") as tf:
            for ti in tf:
                h = ""
                if ti.isreg():
                    f = tf.extractfile(ti)
                    n, hh = 0, hashlib.sha256()
                    while True:
                        b = f.read(1 << 20)
                        if not b:
                            break
                        n += len(b)
                        hh.update(b)
                    if n != ti.size:
                        return "%s reads back %d bytes, not %d" % (ti.name, n, ti.size)
                    h = hh.hexdigest()
                got[ti.name] = (kind_of(ti), ti.size if ti.isreg() else 0, ti.linkname if ti.issym() else "", h)
            while tf.fileobj.read(1 << 20):      # the tar ends before the gzip trailer: read to its end, where the checksum of the whole stream is checked
                pass
    except (OSError, tarfile.TarError, EOFError) as e:
        return "the archive cannot be read back: %s" % e
    want = {arc: (kind, size, link, sha) for arc, _p, kind, size, link, sha in rows}
    if got != want:
        miss = sorted(set(want) - set(got))[:3]
        extra = sorted(set(got) - set(want))[:3]
        diff = sorted(k for k in set(got) & set(want) if got[k] != want[k])[:3]
        return "its list does not match the files (missing %s, unexpected %s, different %s)" % (miss, extra, diff)
    return None


def sync(path, extra=0):
    """fsync the file (or, with O_DIRECTORY, the directory) at path."""
    fd = os.open(path, os.O_RDONLY | extra)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def archive(state, run, record_text):
    name = os.path.basename(run)
    saved = os.path.join(state, "runs", name)
    rows = entries(run, saved, name, record_text)
    adir = os.path.join(state, "runs-archive")
    os.makedirs(adir, mode=0o700, exist_ok=True)
    if os.path.islink(adir) or not os.path.isdir(adir):
        raise OSError("%s is not a directory" % adir)
    os.chmod(adir, 0o700)
    dest = os.path.join(adir, name + ".tar.gz")
    if os.path.lexists(dest):
        why = check(dest, rows)
        if why:
            raise OSError("an archive %s is there already and %s: it is kept, and this run with it" % (dest, why))
        return dest, os.path.getsize(dest), len(rows)
    tmp = "%s.tmp.%d" % (dest, os.getpid())
    old = os.umask(0o077)
    try:
        with tarfile.open(tmp, "w:gz") as tf:
            for arc, path, kind, size, link, sha in rows:
                ti = tarfile.TarInfo(arc)
                if path is None and arc.endswith("/record.json"):
                    data = record_text.encode()
                    ti.size = len(data)
                    ti.mode = 0o600
                    tf.addfile(ti, io.BytesIO(data))
                    continue
                if path is None:
                    ti.type = tarfile.DIRTYPE
                    ti.mode = 0o700
                    tf.addfile(ti)
                    continue
                tf.inodes.clear()                     # a second name of one inode is a file of its own, not a hard-link entry (the check reads kinds)
                ti = tf.gettarinfo(path, arcname=arc)
                if ti is None:
                    raise OSError("%s cannot be archived (no tar entry for this kind of file)" % path)
                ti.uid = ti.gid = 0
                ti.uname = ti.gname = ""
                if kind == "file":
                    with open(path, "rb") as f:
                        tf.addfile(ti, f)
                else:
                    tf.addfile(ti)
        why = check(tmp, rows)
        if why:
            raise OSError("the archive was not kept: %s" % why)
        sync(tmp)                                  # the bytes are on disk before the name is, and the name before the run is removed
        os.rename(tmp, dest)
        sync(adir, os.O_DIRECTORY)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    finally:
        os.umask(old)
    return dest, os.path.getsize(dest), len(rows)


def main(argv):
    if not argv:
        print("usage: legacy_runs.py size RUN... | live RUN... | archive STATE RUN", file=sys.stderr)
        return 64
    cmd, rest = argv[0], argv[1:]
    if cmd == "size":
        for r in rest:
            print("%d %s" % (size_of(r), r))
        return 0
    if cmd == "live":
        for r, why in live(rest):
            print("%s\t%s" % (r, why))
        return 0
    if cmd == "archive" and len(rest) == 2:
        try:
            dest, n, files = archive(rest[0], rest[1], sys.stdin.read())
        except (OSError, tarfile.TarError) as e:
            print("qargi: %s" % e, file=sys.stderr)
            return 1
        print("archive %s %d %d" % (dest, n, files))
        return 0
    print("usage: legacy_runs.py size RUN... | live RUN... | archive STATE RUN", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
