#!/usr/bin/env python3
"""The install records of install.sh. Every path an install writes is recorded before it is written, so --uninstall removes exactly what
an install made and nothing else. The records live in the live configuration directory CONF (~/.qargi/config, or QARGI_CONF / QARGI_HOME):

  CONF/install.d/shared.manifest            the command, its manual page and completions, the --copy tool copy, the parents they needed
  CONF/install.d/runtime-NAME.manifest      the lead skills of one runtime in its user skills directory
  CONF/install.d/project-N-NAME.manifest    the skills of one runtime in one project directory (N: the cksum of the directory's real path)
  CONF/install.lock                         held (flock) by install.sh while a run reads or changes the records
  CONF/install.json                         the tool the user install came from: tool_root, installed_at, version, source (link or copy)

A manifest is text. Its first line is the header: "#qargi-manifest", "2" and KEY=VALUE fields, separated by tabs: kind (runtime, shared or
project), name (the runtime), root (its skills directory; two while a refresh moves it), project (the project directory), data (the --copy
tool directory) and slot (the fixed path of the command, the man page or a completion). Each further line is one path:

  L<TAB>PATH<TAB>TARGET   a link the install made; removed only while it still points at TARGET
  C<TAB>PATH              the root of a copy (a file or a directory)
  f<TAB>PATH, d<TAB>PATH  a file, a directory inside a copy
  P<TAB>PATH              a directory the install had to make; removed only when it is empty
  c<TAB>PATH              the configuration directory, or a parent of it, that an install made; removed when empty, after the records

Every line is checked when a manifest is read, and a manifest with one bad line is refused whole (nothing is changed): a known kind, an
absolute normalized path with no '..', and a place the kind of the manifest allows. A runtime or project manifest holds qargi-* entries
directly in one of its roots, what is inside them and the parents of a root (a project's inside the project directory); a shared manifest
holds its slots, its data directory and what is inside it, and their parents; a c line names the configuration directory that holds the
manifest, or a parent of it. A manifest is written whole: a temporary file in the same directory, flushed to disk, renamed over the old one,
the directory flushed. An install writes the complete manifest of a part (its old entries and every new one) before it changes anything,
then acts, then writes the manifest of what it made; an interrupted run leaves a manifest that lists more than is there, which the next run
reads as its old entries. A link already pointing at its target is left as it is. An uninstall removes the paths, then the manifest.

Verbs (install.sh runs them as python3 -I lib/install_record.py VERB; status 1 is a refusal, its reason on stderr):
  state --conf CONF [--data DIR] [--project-key N]
        the records, one per line: runtime NAME FILE, shared FILE, project NAME FILE (of project N), record TOOL_ROOT SOURCE (install.json)
  apply --conf CONF [--force] < PLAN
        install the parts PLAN describes. Every manifest it reads and every path it will write is checked before anything changes.
  uninstall --conf CONF [--drop-record] FILE...
        remove what each manifest lists, then the manifest; with --drop-record install.json too; then install.d and the lock once no
        manifest is left, and the c directories once they are empty
  excludes FILE
        the lines (/PATH, relative to the project) a project install added to the repository's exclude file
  record --conf CONF --tool-root DIR --version V --source link|copy
        write install.json
  migrate --conf CONF --data DIR --slot PATH... --tool-root DIR
        first remove what an interrupted run left (install.d.new, temporary manifests; never read). Then, once, while install.d does not
        exist, turn the single CONF/install.manifest and CONF/project-N.manifest of qargi 0.3.1 into install.d (see migrate below); with
        install.d there they are removed unread. The migration goes in 0.3.3.
PLAN: one item per line, fields separated by tabs. "M FILE KEY=VALUE..." starts a part, recorded in FILE, with the header fields given;
"D DIR" a directory the part needs (the parents it makes are recorded as P); "L PATH TARGET" a link; "C PATH SRC [NAME...]" a copy of SRC,
or of the NAMEs inside SRC, at PATH; "c DIR" the configuration directory, or a parent, that this run made. The parts are applied in order.
"""
import json, os, re, shutil, subprocess, sys, tempfile, time

MAGIC, SCHEMA = "#qargi-manifest", "2"
KINDS = ("L", "C", "f", "d", "P", "c")
SINGLE, MULTI = ("kind", "name", "project"), ("root", "data", "slot")
SLOT_NAMES = ("qargi", "qargi.1", "_qargi", "qargi.fish")     # the command and the bash completion, the man page, zsh, fish
RUNTIME_FILE = re.compile(r"^runtime-([a-z0-9-]+)\.manifest$")
PROJECT_FILE = re.compile(r"^project-([0-9]+)-([a-z0-9-]+)\.manifest$")
NAME = re.compile(r"^[a-z0-9-]+$")


class Refused(Exception):
    """A refusal: install.sh prints it and stops."""


def clean(p):
    """An absolute, normalized path other than /, with no '..' and no control character."""
    return (isinstance(p, str) and p.startswith("/") and not p.startswith("//") and p != "/" and os.path.normpath(p) == p
            and ".." not in p.split("/") and not any(ord(ch) < 32 or ord(ch) == 127 for ch in p))


def under(p, d):
    """p lies inside d (not d itself)."""
    return p.startswith(d.rstrip("/") + "/")


def at_or_above(p, d):
    """p is d or a parent of d."""
    return p == d or under(d, p)


def norm(p):
    return os.path.normpath(p) if p.startswith("/") else p


def depth(p):
    return (p.count("/"), p)


# ---- the manifest file

class Manifest:
    def __init__(self, path, header, lines):
        self.path, self.header, self.lines = path, header, lines

    def paths(self):
        return {p for _, p, _ in self.lines}


def header_text(h):
    f = [MAGIC, SCHEMA, "kind=" + h["kind"]]
    f += ["%s=%s" % (k, h[k]) for k in ("name", "project") if h.get(k)]
    for k in MULTI:
        f += ["%s=%s" % (k, v) for v in h.get(k, [])]
    return "\t".join(f)


def parse_header(line, where):
    f = line.split("\t")
    if f[:2] != [MAGIC, SCHEMA]:
        raise Refused("%s: not an install manifest of this qargi (its first line is not '%s<TAB>%s ...')" % (where, MAGIC, SCHEMA))
    h = {k: [] for k in MULTI}
    for x in f[2:]:
        k, sep, v = x.partition("=")
        if not sep or k not in SINGLE + MULTI:
            raise Refused("%s: an unknown header field %r" % (where, x[:60]))
        if k in SINGLE:
            if k in h:
                raise Refused("%s: the header names %s twice" % (where, k))
            h[k] = v
        elif v not in h[k]:
            h[k].append(v)
    return h


def check_header(h, fname, where):
    kind, bad = h.get("kind"), None
    paths = h["root"] + h["data"] + h["slot"] + ([h["project"]] if "project" in h else [])
    if kind == "shared":
        if fname != "shared.manifest" or "name" in h or "project" in h or h["root"]:
            bad = "a shared header in a file not named shared.manifest, or with a name, project or root"
        elif not h["data"] or not h["slot"]:
            bad = "a shared header with no data or no slot"
        elif any(os.path.basename(d) != "qargi" for d in h["data"]) or any(os.path.basename(s) not in SLOT_NAMES for s in h["slot"]):
            bad = "a data directory not named qargi or a slot not named %s" % ", ".join(SLOT_NAMES)
    elif kind in ("runtime", "project"):
        m = (RUNTIME_FILE if kind == "runtime" else PROJECT_FILE).match(fname)
        if not m or h.get("name") != m.groups()[-1]:
            bad = "the file name %s does not name the runtime of the header (%s)" % (fname, h.get("name"))
        elif not h["root"] or h["data"] or h["slot"]:
            bad = "a %s header with no root, or with data or slot" % kind
        elif kind == "runtime" and "project" in h:
            bad = "a runtime header with a project"
        elif kind == "project" and ("project" not in h or not all(under(r, h["project"]) for r in h["root"] if clean(h["project"]))):
            bad = "a project header whose roots are not inside its project"
    else:
        bad = "an unknown kind %r" % kind
    if not bad:
        bad = next(("%r is not an absolute normalized path" % p for p in paths if not clean(p)), None)
    if bad:
        raise Refused("%s: %s" % (where, bad))


def check_line(h, conf, k, p, t):
    """Why the line cannot be in a manifest with header h kept in the configuration directory conf, or None."""
    if k not in KINDS:
        return "an unknown kind %r" % k
    if not clean(p):
        return "%r is not an absolute normalized path" % p
    if k == "L" and not clean(t):
        return "a link line with no absolute normalized target"
    if k != "L" and t is not None:
        return "a %s line with a third field" % k
    kind = h["kind"]
    if k == "c":
        if kind == "runtime":
            return "a configuration directory in a runtime manifest"
        return None if at_or_above(p, conf) else "%s is not the configuration directory %s or a parent of it" % (p, conf)
    if kind == "shared":
        slots, data = h["slot"], h["data"]
        ok = {"L": lambda: p in slots, "C": lambda: p in slots or p in data, "f": lambda: any(under(p, x) for x in data),
              "d": lambda: any(under(p, x) for x in data),
              "P": lambda: any(at_or_above(p, os.path.dirname(x)) for x in slots + data)}[k]()
        return None if ok else "%s %s is not a place a shared manifest records" % (k, p)
    roots = h["root"]
    if k in "LC":
        ok = os.path.dirname(p) in roots and os.path.basename(p).startswith("qargi-")
    elif k in "fd":
        ok = any(under(p, r) and "/" in p[len(r) + 1:] and p[len(r) + 1:].startswith("qargi-") for r in roots)
    else:
        ok = any(at_or_above(p, r) for r in roots) and (kind != "project" or under(p, h["project"]))
    return None if ok else "%s %s is not a place a %s manifest of %s records" % (k, p, kind, ", ".join(roots))


def parse(text, path):
    """The Manifest in text, checked line by line; a manifest with one bad line is refused whole."""
    where, fname = path, os.path.basename(path)
    conf = os.path.dirname(os.path.dirname(os.path.abspath(path)))
    if not text.endswith("\n"):
        raise Refused("%s: empty, or its last line is not complete" % where)
    rows = text[:-1].split("\n")
    h = parse_header(rows[0], where)
    check_header(h, fname, where)
    lines = []
    for n, row in enumerate(rows[1:], 2):
        f = row.split("\t")
        if len(f) not in (2, 3):
            raise Refused("%s line %d: not KIND<TAB>PATH[<TAB>TARGET]" % (where, n))
        k, p, t = f[0], f[1], (f[2] if len(f) == 3 else None)
        why = check_line(h, conf, k, p, t)
        if why:
            raise Refused("%s line %d: %s" % (where, n, why))
        lines.append((k, p, t))
    return Manifest(path, h, lines)


def read(path):
    if os.path.islink(path) or not os.path.isfile(path):
        raise Refused("%s: not a regular file" % path)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError) as e:
        raise Refused("%s: cannot be read (%s)" % (path, e))
    try:
        return parse(text, path)
    except Refused as e:
        raise Refused("%s; the record is not used (nothing was changed): move it aside, then remove by hand what it lists" % e)


def fsync_dir(d):
    fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_whole(path, text):
    """Write text to path whole: a temporary file beside it (mode 600), flushed, renamed over path; then the directory is flushed."""
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix="." + os.path.basename(path) + ".", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    fsync_dir(d)


def unique(lines):
    seen, out = set(), []
    for x in lines:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def write(path, h, lines):
    """Write the manifest whole, after checking that it reads back (nothing is written that a later run would refuse)."""
    text = header_text(h) + "\n" + "".join("\t".join(x for x in line if x is not None) + "\n" for line in unique(lines))
    parse(text, path)
    write_whole(path, text)


# ---- removing what a manifest lists

def remove(m, say, keep=frozenset()):
    """Remove exactly the paths m lists, except the (kind, path) pairs in keep. A link goes only while it points at a target the manifest
    records; a directory only once it is empty (the bytecode Python wrote inside a copied directory goes with it); c lines are left to the
    caller. Anything that is no longer what the install made is kept and said."""
    targets = {}
    for k, p, t in m.lines:
        if k == "L":
            targets.setdefault(p, set()).add(t)
    dirs, links = set(), set()
    for k, p, t in m.lines:
        if (k, p) in keep:
            continue
        if k == "L":
            if p in links:
                continue
            links.add(p)
            if os.path.islink(p):
                if os.readlink(p) in targets[p]:
                    os.unlink(p)
                    say("removed " + p)
                else:
                    say("kept %s (a link to %s, not the one the install made)" % (p, os.readlink(p)))
            elif os.path.lexists(p):
                say("kept %s (no longer the link the install made)" % p)
        elif k == "f":
            if os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
        elif k == "C":
            if os.path.isdir(p) and not os.path.islink(p):
                dirs.add((p, k))
            elif os.path.islink(p) or os.path.isfile(p):
                os.unlink(p)
                say("removed " + p)
        elif k in "dP":
            dirs.add((p, k))
    for d, k in sorted(dirs, key=lambda x: depth(x[0]), reverse=True):
        if not os.path.isdir(d) or os.path.islink(d):
            continue
        if k != "P":
            pyc = os.path.join(d, "__pycache__")
            if os.path.islink(pyc):
                os.unlink(pyc)
            elif os.path.isdir(pyc):
                shutil.rmtree(pyc, ignore_errors=True)
        try:
            os.rmdir(d)
            if k == "C":
                say("removed " + d)
        except OSError:
            if k == "C":
                say("kept %s (it holds files the install did not write)" % d)


def tree(p):
    """p and everything under it, without following a link."""
    yield p
    if os.path.isdir(p) and not os.path.islink(p):
        def fail(e):
            raise e
        for dp, dns, fns in os.walk(p, onerror=fail):
            for n in dns + fns:
                yield os.path.join(dp, n)


def ours(p, m):
    """p and everything under it is in the manifest m (the bytecode inside a recorded directory aside), so it is not something of yours."""
    rec = {q for k, q, _ in m.lines if k != "c"}
    copied = {q for k, q, _ in m.lines if k in "Cd"}
    try:
        for x in tree(p):
            if x in rec:
                continue
            parts = x.split("/")
            if "__pycache__" in parts and "/".join(parts[:parts.index("__pycache__")]) in copied:
                continue
            return False
    except OSError:
        return False
    return True


# ---- apply: install the parts of a plan

class Part:
    def __init__(self, path, header):
        self.path, self.header = path, header
        self.dirs, self.links, self.copies, self.cdirs = [], [], [], []
        self.old = None


def parse_plan(text, records):
    parts = []
    for n, line in enumerate(text.splitlines(), 1):
        if not line:
            continue
        f = line.split("\t")
        k = f[0]
        if k == "M" and len(f) >= 3:
            fields = []
            for x in f[2:]:
                key, _, v = x.partition("=")
                fields.append("%s=%s" % (key, norm(v)) if key in MULTI + ("project",) else x)
            h = parse_header("\t".join([MAGIC, SCHEMA] + fields), "plan line %d" % n)
            path = norm(f[1])
            if os.path.dirname(path) != records:
                raise Refused("plan line %d: %s is not in %s" % (n, path, records))
            check_header(h, os.path.basename(path), "plan line %d" % n)
            parts.append(Part(path, h))
        elif not parts or k not in ("D", "L", "C", "c"):
            raise Refused("plan line %d: not an item of a part: %r" % (n, line[:80]))
        elif k in ("D", "c") and len(f) == 2:
            (parts[-1].dirs if k == "D" else parts[-1].cdirs).append(norm(f[1]))
        elif k == "L" and len(f) == 3:
            parts[-1].links.append((norm(f[1]), norm(f[2])))
        elif k == "C" and len(f) >= 3 and all(x and "/" not in x and x not in (".", "..") for x in f[3:]):
            parts[-1].copies.append((norm(f[1]), norm(f[2]), f[3:]))
        else:
            raise Refused("plan line %d: a malformed %s item" % (n, k))
    return parts


def contents(src, dest):
    """The d and f lines of what cp -r makes inside dest from the contents of the directory src (a link is copied as a link: f)."""
    out = []

    def fail(e):
        raise e
    for dp, dns, fns in os.walk(src, onerror=fail):
        rel = os.path.relpath(dp, src)
        base = dest if rel == "." else os.path.join(dest, rel)
        for n in sorted(dns):
            out.append(("f" if os.path.islink(os.path.join(dp, n)) else "d", os.path.join(base, n), None))
        for n in sorted(fns):
            out.append(("f", os.path.join(base, n), None))
    return out


def copy_lines(path, src, names):
    """The lines of a copy of src (or of the names inside src) at path, from the source tree: known before anything is copied."""
    out = [("C", path, None)]
    for n in names:
        s = os.path.join(src, n)
        if not os.path.lexists(s):
            raise Refused("cannot copy %s: it is not there" % s)
        if os.path.isdir(s) and not os.path.islink(s):
            out += [("d", os.path.join(path, n), None)] + contents(s, os.path.join(path, n))
        else:
            out.append(("f", os.path.join(path, n), None))
    if not names:
        if not os.path.lexists(src):
            raise Refused("cannot copy %s: it is not there" % src)
        if os.path.isdir(src) and not os.path.islink(src):
            out += contents(src, path)
    return out


def to_make(d):
    """The directories mkdir -p d would make, the top first."""
    made = []
    while not os.path.isdir(d) and d not in ("/", "."):
        made.insert(0, d)
        d = os.path.dirname(d)
    return made


def slot_state(p, target, old, force):
    """What becomes of the path p a part writes: new (nothing there), keep (already a link to target), ours (the earlier install wrote it
    and nothing else is in it), force (something else, replaced under --force). Something else without --force is refused. A path that is
    not a link is ours only when the earlier install copied it there (a C line): a recorded link that is now a file or a directory is yours.
    Every part is judged before anything changes, so a refusal here changes nothing."""
    if not os.path.lexists(p):
        return "new"
    if os.path.islink(p):
        to = os.readlink(p)
        if target is not None and to == target:
            return "keep"
        if old and any(k == "L" and q == p and t == to for k, q, t in old.lines):
            return "ours"
        if force:
            return "force"
        raise Refused("refusing to replace %s, a link to %s that no install recorded (use --force)" % (p, to))
    copied = old is not None and ("C", p, None) in old.lines
    if copied and ours(p, old):
        return "ours"
    if force:
        return "force"
    if old and not copied and p in old.paths():
        raise Refused("refusing to replace %s: the install recorded a link there and it is now a %s, which is yours; nothing was changed: "
                      "move it aside and install again, or install with --force to replace it" % (p, "directory" if os.path.isdir(p) else "file"))
    raise Refused("refusing to replace existing %s (use --force)" % p)


def check_overlap(records, parts):
    """One skills directory holds the skills of one runtime: refuse a part whose root is, by its real path, the root of another record."""
    seen, planned = {}, {p.path for p in parts}
    names = sorted(os.listdir(records)) if os.path.isdir(records) else []
    owners = [read(os.path.join(records, n)) for n in names
              if (RUNTIME_FILE.match(n) or PROJECT_FILE.match(n)) and os.path.join(records, n) not in planned]
    owners += [Manifest(p.path, p.header, []) for p in parts if p.header["kind"] != "shared"]
    for m in owners:
        for r in m.header["root"]:
            rr = os.path.realpath(r)
            other = seen.get(rr)
            if other and other[1] != m.path:
                raise Refused("refusing: %s (%s) is the skills directory %s of %s (%s) too; one skills directory holds the skills of one runtime"
                              % (r, os.path.basename(m.path), other[0], os.path.basename(other[1]), rr))
            seen[rr] = (r, m.path)


def records_dir(conf):
    d = os.path.join(conf, "install.d")
    if os.path.lexists(d) and (os.path.islink(d) or not os.path.isdir(d)):
        raise Refused("%s is not a directory; nothing was changed" % d)
    return d


def apply(conf, text, force):
    records = records_dir(conf)
    parts = parse_plan(text, records)
    for part in parts:
        part.old = read(part.path) if os.path.lexists(part.path) else None
    check_overlap(records, parts)
    # every line of every part, before anything changes
    for part in parts:
        made = [("P", d, None) for x in part.dirs for d in to_make(x)]
        old = part.old.lines if part.old else []
        part.carried = [("P", p, None) for k, p, _ in old if k == "P" and os.path.isdir(p) and any(at_or_above(p, x) for x in part.dirs)]
        entries = [("L", p, t) for p, t in part.links]
        for p, src, names in part.copies:
            entries += copy_lines(p, src, names)
        cl = [("c", d, None) for d in part.cdirs] + [x for x in old if x[0] == "c"]
        part.final = unique(made + part.carried + entries + cl)
        parse(header_text(part.header) + "\n" + "".join("\t".join(x for x in line if x is not None) + "\n" for line in part.final), part.path)
    # every path a part writes, before anything changes
    for part in parts:
        part.state = {p: slot_state(p, t, part.old, force) for p, t in part.links}
        part.state.update({p: slot_state(p, None, part.old, force) for p, _, _ in part.copies})
    if not os.path.isdir(records):
        os.mkdir(records, 0o700)
    os.chmod(records, 0o700)
    for part in parts:
        h = dict(part.header)
        if part.old:
            for k in MULTI:
                h[k] = unique(part.header[k] + part.old.header[k])
        write(part.path, h, (part.old.lines if part.old else []) + part.final)
        keep = {("L", p) for p, s in part.state.items() if s == "keep"} | {(k, p) for k, p, _ in part.carried}
        if part.old:
            remove(part.old, lambda _: None, keep)
        for p, s in part.state.items():
            if s != "keep" and os.path.lexists(p):
                if not force:
                    raise Refused("%s is still there once what the earlier install wrote is removed (something changed it during this run); "
                                  "the record lists it, so install with --force to replace it" % p)
                if os.path.isdir(p) and not os.path.islink(p):
                    shutil.rmtree(p)
                else:
                    os.unlink(p)
        for d in part.dirs:
            os.makedirs(d, exist_ok=True)
        for p, t in part.links:
            if part.state[p] != "keep":
                os.symlink(t, p)
        for p, src, names in part.copies:
            if names:
                os.mkdir(p)
                run(["cp", "-r", "--"] + [os.path.join(src, n) for n in names] + [p + "/"])
            else:
                run(["cp", "-r", "--", src, p])
        write(part.path, part.header, part.final)


def run(argv):
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode:
        raise Refused("%s failed: %s" % (" ".join(argv[:3]), r.stderr.strip()))


# ---- the other verbs

def manifests(conf, key=None):
    """(kind, name, path) of the records: the shared one, the user runtimes, and the runtimes of project key when it is given."""
    records = records_dir(conf)
    out = []
    for n in sorted(os.listdir(records)) if os.path.isdir(records) else []:
        p = os.path.join(records, n)
        m, pm = RUNTIME_FILE.match(n), PROJECT_FILE.match(n)
        if n == "shared.manifest":
            out.append(("shared", "", p))
        elif m:
            out.append(("runtime", m.group(1), p))
        elif pm and pm.group(1) == key:
            out.append(("project", pm.group(2), p))
    return out


def state(conf, data, key):
    rows = []
    for kind, name, p in manifests(conf, key):
        read(p)
        rows.append("\t".join(x for x in (kind, name, p) if x))
    rec = os.path.join(conf, "install.json")
    try:
        with open(rec) as f:
            j = json.load(f)
        root = j.get("tool_root")
        if isinstance(root, str) and root:
            src = j.get("source")
            if src not in ("link", "copy"):
                src = "copy" if data and os.path.realpath(root) == os.path.realpath(data) else "link"
            rows.append("record\t%s\t%s" % (root, src))
    except (OSError, ValueError, AttributeError):
        pass
    return rows


def uninstall(conf, files, drop_record, say):
    ms = [read(norm(os.path.abspath(f))) for f in files]      # every one is checked before anything is removed
    created = set()
    for m in ms:
        created |= {p for k, p, _ in m.lines if k == "c"}
        remove(m, say)
        os.unlink(m.path)
    rec = os.path.join(conf, "install.json")
    if drop_record and os.path.lexists(rec):
        os.unlink(rec)
        say("removed " + rec)
    records = records_dir(conf)
    if os.path.isdir(records) and not any(n.endswith(".manifest") for n in os.listdir(records)):
        for n in os.listdir(records):
            if n.startswith(".") and n.endswith(".tmp"):
                os.unlink(os.path.join(records, n))
        try:
            os.rmdir(records)
            lock = os.path.join(conf, "install.lock")
            if os.path.isfile(lock) and not os.path.islink(lock):
                os.unlink(lock)
        except OSError:
            pass
    # the configuration directory the install made, once nothing is left in it (another record, answers or packs keep it)
    for d in sorted(created, key=depth, reverse=True):
        if os.path.isdir(d) and not os.path.islink(d):
            try:
                os.rmdir(d)
                say("removed " + d)
            except OSError:
                pass


def excludes(path):
    m = read(path)
    if m.header["kind"] != "project":
        raise Refused("%s is not a project manifest" % path)
    proj = m.header["project"]
    return ["/" + os.path.relpath(p, proj) for k, p, _ in m.lines if k in "LC" and os.path.dirname(p) in m.header["root"]]


# ---- the one-time migration of the single install.manifest of qargi 0.3.1 and earlier (removed in 0.3.3)

LEGACY_USER = "install.manifest"
LEGACY_PROJECT = re.compile(r"^project-([0-9]+)\.manifest$")
SLOT_SOURCES = {"qargi.1": "man/qargi.1", "_qargi": "completions/_qargi", "qargi.fish": "completions/qargi.fish",
                "bin/qargi": "bin/qargi", "completions/qargi": "completions/qargi.bash"}   # what a slot links to, by its name (and its parent's)


def tidy(conf, say):
    """Remove what an interrupted run left: install.d.new (a migration that never committed) and temporary manifests in install.d. Neither
    is ever read: a migration builds install.d.new afresh from the legacy files, and a temporary manifest is not a record."""
    new = os.path.join(conf, "install.d.new")
    if os.path.islink(new) or os.path.isfile(new):
        os.unlink(new)
    elif os.path.isdir(new):
        shutil.rmtree(new)
    else:
        new = None
    if new:
        say("removed %s, left by an interrupted migration (not read)" % new)
    records = records_dir(conf)
    for n in sorted(os.listdir(records)) if os.path.isdir(records) else []:
        if n.startswith(".") and n.endswith(".tmp"):
            os.unlink(os.path.join(records, n))


def legacy_files(conf):
    names = sorted(os.listdir(conf)) if os.path.isdir(conf) else []
    return [os.path.join(conf, n) for n in names if (n == LEGACY_USER or LEGACY_PROJECT.match(n)) and os.path.isfile(os.path.join(conf, n))]


def legacy_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            rows = f.read().splitlines()
    except (OSError, UnicodeDecodeError) as e:
        raise Refused("%s cannot be read (%s)" % (path, e))
    out = []
    for n, row in enumerate(rows, 1):
        if not row:
            continue
        k, sep, p = row.partition("\t")
        if not sep or "\t" in p:
            raise Refused("%s line %d: not KIND<TAB>PATH" % (path, n))
        out.append((n, k, p))
    return out


def layouts():
    """name -> layout of every runtime with a definition (shipped or in the library); one that cannot be read is left out."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import provider
    out = {}
    for n in provider.names():
        try:
            out[n] = provider.layout(n)
        except Exception:      # a definition that cannot be read identifies nothing
            continue
    return out


def which(path, lines, candidates):
    """The one runtime whose skills directory holds the qargi-task line of a legacy manifest, by candidates (name -> test of the directory)."""
    tasks = [p for _, k, p in lines if k in "LC" and os.path.basename(p) == "qargi-task"]
    if not tasks:
        return None, None
    d = os.path.dirname(tasks[0])
    hits = [(n, r) for n, test in sorted(candidates.items()) for r in [test(d)] if r]
    if len(hits) != 1 or not clean(d):
        raise Refused("cannot tell which runtime %s belongs to (its skills are in %s; %s); nothing was changed: move it aside and install again"
                      % (path, d, "several runtimes keep skills there" if len(hits) > 1 else "no runtime keeps skills there"))
    return hits[0][0], hits[0][1]


def migrate(conf, data, slots, tool_root, say):
    """Turn the legacy manifests into install.d, once: only while install.d does not exist. install.d.new is built from the legacy files
    alone, every line checked (a link is carried with its target only while it still points into the tool; any other line only inside the
    skills directory, the data directory or a fixed slot, else the migration is refused with nothing changed), committed with one directory
    rename, and then the legacy files are removed. With install.d already there a legacy file is removed and not read."""
    tidy(conf, say)
    legacy = legacy_files(conf)
    records = records_dir(conf)
    if not legacy:
        return
    if os.path.lexists(records):
        for f in legacy:
            os.unlink(f)
            say("removed %s: the records are in %s, so it was not read" % (f, records))
        return
    roots = {data, os.path.realpath(data), tool_root, os.path.realpath(tool_root)}
    try:
        with open(os.path.join(conf, "install.json")) as f:
            t = json.load(f).get("tool_root")
        if isinstance(t, str) and t:
            roots |= {t, os.path.realpath(t)}
    except (OSError, ValueError, AttributeError):
        pass
    roots = {norm(r) for r in roots if r}
    slot_target = {}
    for s in slots:
        rel = SLOT_SOURCES.get(os.path.basename(s)) or SLOT_SOURCES.get("/".join(s.split("/")[-2:]))
        if rel:
            slot_target[s] = {os.path.join(r, rel) for r in roots}
    lay = layouts()
    parts, dropped = [], []

    def link(p, wants):
        if os.path.islink(p) and norm(os.readlink(p)) in wants:
            return ("L", p, norm(os.readlink(p)))
        dropped.append(p)
        return None

    def skill_target(p, root):
        return {os.path.join(r, "skills", os.path.basename(p)) for r in roots} if os.path.dirname(p) == root and os.path.basename(p).startswith("qargi-") else set()

    for f in legacy:
        lines = legacy_lines(f)
        bad = lambda n, k, p: Refused("%s line %d: %s %s is not in the skills directory, the tool copy or a fixed place of the install; nothing was changed: move %s aside and install again" % (f, n, k, p, f))
        if os.path.basename(f) == LEGACY_USER:
            name, root = which(f, lines, {n: (lambda d, l=l: d if l.get("user_skills_dir") and norm(l["user_skills_dir"]) == d else None) for n, l in lay.items()})
            if name is None and lines:
                raise Refused("cannot tell which runtime %s belongs to (it lists no qargi-task); nothing was changed: move it aside and install again" % f)
            if name is None:
                continue
            rt = {"kind": "runtime", "name": name, "root": [root], "data": [], "slot": []}
            sh = {"kind": "shared", "data": [data], "slot": list(slots), "root": []}
            rl, sl = [], []
            for n, k, p in lines:
                if k == "L":
                    if not clean(p):
                        dropped.append(p)
                        continue
                    mine = os.path.dirname(p) == root
                    x = link(p, skill_target(p, root) if mine else slot_target.get(p, set()))
                    if x:
                        (rl if mine else sl).append(x)
                    continue
                if not clean(p) or k not in KINDS:
                    raise bad(n, k, p)
                if k == "C" and os.path.dirname(p) == root and os.path.basename(p).startswith("qargi-") or k in "fd" and check_line(rt, conf, k, p, None) is None \
                        or k == "P" and at_or_above(p, root):
                    rl.append((k, p, None))
                elif k in "CfdPc" and check_line(sh, conf, k, p, None) is None:
                    sl.append((k, p, None))
                else:
                    raise bad(n, k, p)
            parts += [("runtime-%s.manifest" % name, rt, rl), ("shared.manifest", sh, sl)]
        else:
            key = LEGACY_PROJECT.match(os.path.basename(f)).group(1)

            def in_project(d, l):
                psk = l.get("project_skills_dir")
                return d if psk and d.endswith("/" + psk.strip("/")) and clean(d[:-len(psk.strip("/")) - 1]) else None
            name, root = which(f, lines, {n: (lambda d, l=l: in_project(d, l)) for n, l in lay.items()})
            if name is None and lines:
                raise Refused("cannot tell which runtime %s belongs to (it lists no qargi-task); nothing was changed: move it aside and install again" % f)
            if name is None:
                continue
            proj = root[:-len(lay[name]["project_skills_dir"].strip("/")) - 1]
            ph = {"kind": "project", "name": name, "project": proj, "root": [root], "data": [], "slot": []}
            pl = []
            for n, k, p in lines:
                if k == "L":
                    x = link(p, skill_target(p, root)) if clean(p) else None
                    if x:
                        pl.append(x)
                    elif not clean(p):
                        dropped.append(p)
                elif k in KINDS and k != "L" and check_line(ph, conf, k, p, None) is None:
                    pl.append((k, p, None))
                else:
                    raise bad(n, k, p)
            parts.append(("project-%s-%s.manifest" % (key, name), ph, pl))
    new = os.path.join(conf, "install.d.new")
    if not parts:
        for f in legacy:
            os.unlink(f)
            say("removed %s: it recorded nothing" % f)
        return
    os.mkdir(new, 0o700)
    try:
        for fname, h, lines in parts:
            write(os.path.join(new, fname), h, lines)
        fsync_dir(new)
        os.rename(new, records)
    except BaseException:
        shutil.rmtree(new, ignore_errors=True)
        raise
    fsync_dir(conf)
    for f in legacy:
        os.unlink(f)
    fsync_dir(conf)
    for p in dropped:
        say("not carried over: %s (no longer the link the install made)" % p)
    say("moved the install records of %s to %s (%s)" % (", ".join(os.path.basename(f) for f in legacy), records,
                                                      ", ".join("%s: %d" % (n, len(l)) for n, _, l in parts) or "nothing recorded"))


def record(conf, root, version, source):
    j = {"tool_root": root, "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "version": version, "source": source}
    write_whole(os.path.join(conf, "install.json"), json.dumps(j) + "\n")


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(prog="install_record.py")
    sub = ap.add_subparsers(dest="verb", required=True)
    s = sub.add_parser("state")
    s.add_argument("--conf", required=True)
    s.add_argument("--data", default="")
    s.add_argument("--project-key")
    a = sub.add_parser("apply")
    a.add_argument("--conf", required=True)
    a.add_argument("--force", action="store_true")
    u = sub.add_parser("uninstall")
    u.add_argument("--conf", required=True)
    u.add_argument("--drop-record", action="store_true")
    u.add_argument("files", nargs="+")
    e = sub.add_parser("excludes")
    e.add_argument("file")
    r = sub.add_parser("record")
    r.add_argument("--conf", required=True)
    r.add_argument("--tool-root", required=True)
    r.add_argument("--version", required=True)
    r.add_argument("--source", required=True, choices=("link", "copy"))
    g = sub.add_parser("migrate")
    g.add_argument("--conf", required=True)
    g.add_argument("--data", required=True)
    g.add_argument("--slot", action="append", default=[])
    g.add_argument("--tool-root", required=True)
    o = ap.parse_args(argv)
    conf = norm(os.path.abspath(getattr(o, "conf", None) or "."))
    try:
        if o.verb == "state":
            for row in state(conf, o.data, o.project_key):
                print(row)
        elif o.verb == "apply":
            apply(conf, sys.stdin.read(), o.force)
        elif o.verb == "uninstall":
            uninstall(conf, o.files, o.drop_record, print)
        elif o.verb == "excludes":
            for x in excludes(norm(os.path.abspath(o.file))):
                print(x)
        elif o.verb == "record":
            record(conf, o.tool_root, o.version, o.source)
        elif o.verb == "migrate":
            migrate(conf, norm(o.data), [norm(s) for s in o.slot], norm(o.tool_root), print)
    except Refused as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("qargi: install record: %s" % e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
