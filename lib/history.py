#!/usr/bin/env python3
"""The history of the whole-suite runs and of the review reports of one project: one append-only file of JSON lines, kept as evidence.

  $QARGI_STATE/history/PROJECT.jsonl    one JSON object per line (kind qargi-history-entry, lib/kinds/qargi-history-entry.json)
  $QARGI_STATE/suite-logs/runs/ID.log   the log of one suite run, the newest KEEP_LOGS of each project (and the latest pass of each branch)

The file is evidence and no gate: no verb decides anything from it. `verified()` and the per-branch record of lib/gitflow.sh decide what a
verify means; an entry only says that a run happened, on which commit and tree, with which command, and how it ended. A line is written once, by
one write(2) of one buffer on a descriptor opened with O_APPEND, under an flock on the file itself, and fsynced; it is never rewritten, and nothing
else in the file is touched (a line a crash left without its newline gets the newline first, as the start of the next line). The reader skips a
line it cannot read and says so on standard error; it never fails because of one. The directory has mode 700 and the file and the logs mode 600.

As a library (import history; standard library and lib/jsonkind.py only, no recursion):
  history_path(project, state=None)     the file of a project
  append(project, entry, state=None, prepare=None)
                                        validates entry against its registry file and appends it; prepare(earlier, entry) may complete the entry
                                        (the attempt number) from the entries read under the same lock
  read(project, state=None, warn=True)  (entries, skipped): the readable entries in file order, and the number of lines that were not
  select(entries, kind=None, head=None) the entries of an entry_kind, and of a head (a hex prefix; a review entry's base sha counts)
  attempt_number(entries, head, tree, command, env_id)
                                        1 and the number of earlier suite entries of the same head, tree and command identity
  keep_logs(project, state=None, keep=KEEP_LOGS)
                                        removes the logs the cap leaves out, never the log of the latest pass of a branch

Command line (lib/history.py read ... is `qargi history ...`; write is what the verbs of lib/gitflow.sh and lib/review.sh call):
  history.py read [--project P] [--kind suite|review] [--head SHA] [--limit N] [--json]
  history.py read show ID [--project P] [--json]
  history.py write suite  --project P --verb V --name N --branch B --head H --tree T --command=C [--env-id=E] --result R --started S --seconds N
                          [--load-start X] [--log FILE] [--gates FILE] [--names FILE]
  history.py write review --project P --run ID --slug S --facts FILE [--base B] [--base-sha H] [--role R] [--class C] [--runtime=R] [--model=M]
Exit status of read: 0, 1 for an ID that no entry has, 2 a wrong call, 70 a document that fails its registry file (a defect, nothing printed). Exit status of
write: 0, or 1 with a line on standard error when nothing could be written (the caller goes on: the history is evidence, not a gate)."""
import argparse
import errno
import fcntl
import json
import os
import re
import secrets
import shutil
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I does not put the script's directory on sys.path
import jsonkind as K  # noqa: E402

ENTRY_KIND = "qargi-history-entry"
LIST_KIND = "qargi-history"
SCHEMA = 1
KEEP_LOGS = 20                        # the newest logs kept for each project
MAX_FAILING = 200                     # failing test names kept in an entry
MAX_NAME = 300                        # characters of one stored name
MAX_LIMIT = 1000
DEFAULT_LIMIT = 20
ENTRY_KINDS = ("suite", "review")
RESULTS = ("pass", "fail", "interrupted")
VERBS = ("feature verify", "release verify")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9]{0,23}$")
ID_RE = re.compile(r"^[0-9a-f]{16}$")
HEX_RE = re.compile(r"^[0-9a-f]{4,64}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
LOAD_RE = re.compile(r"^[0-9]+\.[0-9]+$")


class HistoryError(Exception):
    """Something the history cannot do (a bad project name, a file that is a link, a file that cannot be written)."""


class Defect(HistoryError):
    """A document of qargi that fails the registry file of its own kind: a defect of qargi, never of the history."""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def state_dir():
    import paths
    return paths.state()


def check_project(project):
    if not isinstance(project, str) or not PROJECT_RE.match(project):
        raise HistoryError("%r is not a project name" % (project,))
    return project


def history_dir(state=None):
    return os.path.join(state or state_dir(), "history")


def history_path(project, state=None):
    return os.path.join(history_dir(state), check_project(project) + ".jsonl")


def runs_dir(state=None):
    return os.path.join(state or state_dir(), "suite-logs", "runs")


def load_average():
    """The first field of /proc/loadavg as the text it has ("0.52"), or None when it cannot be read. A document holds integers only, so it stays text."""
    try:
        with open("/proc/loadavg") as f:
            word = f.read().split()[0]
    except (OSError, IndexError, ValueError):
        return None
    return word if LOAD_RE.match(word) else None


def vis(text):
    """text with every control character written as \\xNN (a command or a test name is printed to a terminal)."""
    return "".join(c if c >= " " and c != "\x7f" and not "\x80" <= c <= "\x9f" else "\\x%02x" % ord(c) for c in str(text))


# ---- the file ---------------------------------------------------------------------------------------------------------------

def make_dir(path):
    """The directory with mode 700: made when it is missing, set to 700 when group or others may use it. A link in its place is refused."""
    if os.path.islink(path):
        raise HistoryError("%s is a link" % path)
    try:
        os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
        os.mkdir(path, 0o700)
    except FileExistsError:
        pass
    except OSError as e:
        raise HistoryError("cannot make %s: %s" % (path, e.strerror or e))
    try:
        if os.stat(path).st_mode & 0o077:
            os.chmod(path, 0o700)
    except OSError:
        pass


def read_all(fd):
    chunks, off = [], 0
    while True:
        chunk = os.pread(fd, 1 << 20, off)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        off += len(chunk)


def parse(data):
    """(entries, skipped) of the bytes of a history file: every line that is a JSON object of the entry kind is an entry, every other
    non-empty line is skipped (a torn last line is the one to expect)."""
    entries, skipped = [], 0
    for raw in data.split(b"\n"):
        if not raw.strip():
            continue
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, RecursionError):
            skipped += 1
            continue
        if isinstance(doc, dict) and doc.get("kind") == ENTRY_KIND and isinstance(doc.get("id"), str) and isinstance(doc.get("entry_kind"), str):
            entries.append(doc)
        else:
            skipped += 1
    return entries, skipped


def read(project, state=None, warn=True):
    """(entries, skipped) of the history of a project, in file order; no file is no entry. A line that cannot be read is skipped with a warning
    on standard error (warn), never an error."""
    path = history_path(project, state)
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError:
        return [], 0
    except OSError as e:
        raise HistoryError("cannot read %s: %s" % (path, e.strerror or e))
    try:
        data = read_all(fd)
    finally:
        os.close(fd)
    entries, skipped = parse(data)
    if skipped and warn:
        print("qargi: warning: history: skipped %d line(s) of %s that cannot be read (a line cut off by a crash is skipped)" % (skipped, path), file=sys.stderr)
    return entries, skipped


def dumps(entry):
    return json.dumps(entry, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False)


def check_entry(entry):
    """The text of the entry, checked against the registry file of its kind: a document that fails it is not written (HistoryError)."""
    try:
        text = dumps(entry)
    except (ValueError, TypeError) as e:
        raise Defect("the entry cannot be written as JSON (%s)" % e)
    try:
        found = K.validate(K.registry_path(ENTRY_KIND), text)
    except K.RegistryError as e:
        raise Defect("the entry cannot be checked: %s" % e)
    if found:
        raise Defect("the entry breaks its registry file at %s %s: %s" % (found[0].rule, found[0].path, found[0].message))
    return text


def write_all(fd, data):
    while data:
        n = os.write(fd, data)
        data = data[n:]


def append(project, entry, state=None, prepare=None):
    """Appends the entry (a dict of the kind qargi-history-entry) to the history of the project and returns it. The file is made with mode 600 in a
    directory of mode 700; the append is one write on a descriptor opened with O_APPEND, under an flock on the file, and is fsynced. prepare, when
    given, is called under the lock with the entries already there and the entry, and may complete it."""
    path = history_path(project, state)
    check_entry(entry)                    # nothing is made for an entry that cannot be written
    make_dir(os.path.dirname(path))
    created = not os.path.lexists(path)
    try:
        fd = os.open(path, os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    except OSError as e:
        raise HistoryError("cannot open %s: %s" % (path, e.strerror or e))
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        os.fchmod(fd, 0o600)
        data = read_all(fd)
        if prepare is not None:
            prepare(parse(data)[0], entry)
        text = check_entry(entry)
        prefix = b"\n" if data and not data.endswith(b"\n") else b""     # a torn last line stays as it is; the entry starts a line of its own
        write_all(fd, prefix + text.encode("ascii") + b"\n")
        os.fsync(fd)
    except OSError as e:
        raise HistoryError("cannot write %s: %s" % (path, e.strerror or e))
    finally:
        os.close(fd)                      # closing releases the lock
    if created:
        try:
            dfd = os.open(os.path.dirname(path), os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except OSError:
            pass
    return entry


def select(entries, kind=None, head=None):
    """The entries of the entry_kind and of the head: a hex prefix of an entry's head, or of a review entry's base_sha."""
    out = []
    for e in entries:
        if kind is not None and e.get("entry_kind") != kind:
            continue
        if head is not None and not any(isinstance(e.get(k), str) and e[k].startswith(head) for k in ("head", "base_sha")):
            continue
        out.append(e)
    return out


def attempt_number(entries, head, tree, command, env_id):
    """1 + the number of earlier suite entries with this head, tree and command identity (the command and the id of verify.environment)."""
    return 1 + sum(1 for e in entries if e.get("entry_kind") == "suite" and e.get("head") == head and e.get("tree") == tree
                   and e.get("command") == command and e.get("environment_id") == env_id)


# ---- the logs -----------------------------------------------------------------------------------------------------------------

def keep_log(entry_id, source, state=None):
    """Copies the log of a run to suite-logs/runs/ID.log (mode 600, never over a file) and returns its path, or None when the log cannot be read or kept."""
    if not source:
        return None
    dest_dir = runs_dir(state)
    dest = os.path.join(dest_dir, entry_id + ".log")
    try:
        make_dir(os.path.dirname(dest_dir))
        make_dir(dest_dir)
        with open(source, "rb") as src:
            out = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            try:
                with os.fdopen(out, "wb") as dst:
                    out = None
                    shutil.copyfileobj(src, dst)
                    dst.flush()
                    os.fsync(dst.fileno())
            finally:
                if out is not None:
                    os.close(out)
    except (OSError, HistoryError):
        return None
    return dest


def keep_logs(project, state=None, keep=KEEP_LOGS):
    """Removes the logs of the project that the cap leaves out: of its suite entries that have a log, the newest `keep` stay, and so does the
    log of the latest pass of each branch (the evidence a branch's last good run stands on). Returns the ids whose log was removed. Best
    effort: a log that cannot be removed stays."""
    entries, _ = read(project, state, warn=False)
    logged = [e for e in entries if e.get("entry_kind") == "suite" and isinstance(e.get("log"), str) and ID_RE.match(e.get("id", ""))]
    protected, seen = set(), set()
    for e in reversed([e for e in entries if e.get("entry_kind") == "suite"]):
        b = e.get("branch")
        if e.get("result") == "pass" and b not in seen:
            seen.add(b)
            protected.add(e.get("id"))
    removed = []
    for e in logged[:max(0, len(logged) - keep)]:
        if e["id"] in protected:
            continue
        try:
            os.unlink(os.path.join(runs_dir(state), e["id"] + ".log"))       # the path is made from the id, never taken from the entry
            removed.append(e["id"])
        except FileNotFoundError:
            pass
        except OSError:
            pass
    return removed


# ---- the entries --------------------------------------------------------------------------------------------------------------

def read_lines(path):
    if not path:
        return []
    try:
        with open(path, errors="replace") as f:
            return [l.rstrip("\n") for l in f if l.strip()]
    except OSError:
        return []


def gates_of(path):
    rows = []
    for line in read_lines(path):
        try:
            g = json.loads(line)
        except ValueError:
            continue
        if isinstance(g, dict) and isinstance(g.get("name"), str):
            sec = g.get("seconds")
            rows.append({"name": g["name"], "result": g["result"] if isinstance(g.get("result"), str) else "not run",
                         "seconds": sec if isinstance(sec, int) and not isinstance(sec, bool) else None})
    return rows


def suite_entry(project, a, state=None):
    """The entry of a suite run from the arguments of `write suite` (namespace a): the gates and the failing names are read from their files here."""
    names = [n[:MAX_NAME] for n in read_lines(a.names)]
    eid = secrets.token_hex(8)
    ended = now()
    entry = {"schema": SCHEMA, "kind": ENTRY_KIND, "entry_kind": "suite", "id": eid, "project": project, "time": ended,
             "verb": a.verb, "name": a.name, "branch": a.branch, "head": a.head, "tree": a.tree, "command": a.command,
             "environment_id": a.env_id or None, "gates": gates_of(a.gates), "result": a.result, "started": a.started, "ended": ended,
             "seconds": a.seconds, "failing_tests": names[:MAX_FAILING], "failing_total": len(names),
             "load_start": a.load_start if a.load_start and LOAD_RE.match(a.load_start) else None, "load_end": load_average(),
             "attempt": 1, "log": keep_log(eid, a.log, state)}

    def number(earlier, e):
        e["attempt"] = attempt_number(earlier, e["head"], e["tree"], e["command"], e["environment_id"])
    return entry, number


def vendor_of(runtime):
    """The family name of the runtime's descriptor (its `family` field), or None when there is no such runtime or the descriptor has no family."""
    if not runtime:
        return None
    try:
        import provider as P
        fam = P.definition(runtime, "local").get("family")
    except Exception:                                      # a descriptor that cannot be read is no vendor, never a failure of the review check
        return None
    return fam if isinstance(fam, str) and fam else None


def tests_of(value):
    """The tests_run of a report's manifest as an entry holds it: a list of strings, a count, or None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, list):
        return [str(v)[:MAX_NAME] for v in value[:MAX_FAILING] if isinstance(v, (str, int)) and not isinstance(v, bool)]
    return None


def review_entry(project, a):
    """The entry of a review report from the facts review_check.py wrote (the verdict word, the sha256 of the report and tests_run) and what the lead's registry records of the run."""
    try:
        with open(a.facts) as f:
            facts = json.load(f)
    except (OSError, ValueError) as e:
        raise HistoryError("cannot read the facts of the report: %s" % e)
    if not isinstance(facts, dict) or facts.get("verdict") not in ("accept", "revise") or not re.match(r"^[0-9a-f]{64}$", str(facts.get("report_sha256"))):
        raise HistoryError("the facts of the report are not a verdict and a sha256")
    entry = {"schema": SCHEMA, "kind": ENTRY_KIND, "entry_kind": "review", "id": secrets.token_hex(8), "project": project, "time": now(),
             "run": a.run, "slug": a.slug, "verdict": facts["verdict"], "report_sha256": facts["report_sha256"],
             "base": a.base or None, "base_sha": a.base_sha if a.base_sha and SHA_RE.match(a.base_sha) else None,
             "role": a.role or None, "class": a.cls or None, "runtime": a.runtime or None, "model": a.model or None,
             "vendor": vendor_of(a.runtime), "tests_run": tests_of(facts.get("tests_run"))}
    return entry


# ---- the write command --------------------------------------------------------------------------------------------------------

def write_main(argv):
    p = argparse.ArgumentParser(prog="history.py write", allow_abbrev=False)
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("suite")
    s.add_argument("--project", required=True)
    s.add_argument("--verb", required=True, choices=VERBS)
    s.add_argument("--name", required=True)
    s.add_argument("--branch", required=True)
    s.add_argument("--head", required=True)
    s.add_argument("--tree", required=True)
    s.add_argument("--command", required=True)
    s.add_argument("--env-id", default="")
    s.add_argument("--result", required=True, choices=RESULTS)
    s.add_argument("--started", required=True)
    s.add_argument("--seconds", required=True, type=int)
    s.add_argument("--load-start", default="")
    s.add_argument("--log", default="")
    s.add_argument("--gates", default="")
    s.add_argument("--names", default="")
    r = sub.add_parser("review")
    r.add_argument("--project", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--facts", required=True)
    r.add_argument("--base", default="")
    r.add_argument("--base-sha", default="")
    r.add_argument("--role", default="")
    r.add_argument("--class", dest="cls", default="")
    r.add_argument("--runtime", default="")
    r.add_argument("--model", default="")
    a = p.parse_args(argv)
    try:
        project = check_project(a.project)
        if a.what == "suite":
            entry, number = suite_entry(project, a)
            append(project, entry, prepare=number)
            keep_logs(project)
        else:
            append(project, review_entry(project, a))
    except HistoryError as e:
        print("qargi: warning: history: %s; no entry was written" % e, file=sys.stderr)
        return 1
    return 0


# ---- the read command ---------------------------------------------------------------------------------------------------------

def short(sha):
    return sha[:8] if isinstance(sha, str) and sha else "-"


def cell(v):
    return "-" if v is None or v == "" else vis(v)


def table(entries):
    rows = [("TIME", "KIND", "NAME", "HEAD", "TREE", "RESULT", "SECONDS", "ATTEMPT", "ID")]
    for e in entries:
        suite = e.get("entry_kind") == "suite"
        rows.append((cell(e.get("time")), cell(e.get("entry_kind")), cell(e.get("name") if suite else e.get("slug")),
                     short(e.get("head") if suite else e.get("base_sha")), short(e.get("tree")),
                     cell(e.get("result") if suite else e.get("verdict")), cell(e.get("seconds")), cell(e.get("attempt")), cell(e.get("id"))))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(widths[i]) for i, c in enumerate(r)).rstrip() for r in rows) + "\n"


SHOW_ORDER = ("id", "entry_kind", "project", "time", "verb", "name", "branch", "head", "tree", "result", "attempt", "started", "ended", "seconds",
              "load_start", "load_end", "command", "environment_id", "log", "run", "slug", "verdict", "report_sha256", "base", "base_sha", "role",
              "class", "runtime", "model", "vendor", "tests_run")


def show_text(e):
    lines = []
    for k in SHOW_ORDER:
        if k in e and k not in ("gates", "failing_tests"):
            v = e[k]
            lines.append("%s: %s" % (k, cell(", ".join(map(str, v)) if isinstance(v, list) else v)))
    for k, v in sorted(e.items()):
        if k not in SHOW_ORDER and k not in ("schema", "kind", "gates", "failing_tests", "failing_total"):
            lines.append("%s: %s" % (vis(k), cell(json.dumps(v, sort_keys=True) if isinstance(v, (list, dict)) else v)))
    if e.get("gates"):
        lines.append("gates:")
        for g in e["gates"]:
            lines.append("  %s: %s%s" % (cell(g.get("name")), cell(g.get("result")), "" if g.get("seconds") is None else " (%ss)" % g["seconds"]))
    if "failing_tests" in e:
        total = e.get("failing_total", len(e["failing_tests"]))
        lines.append("failing tests: %s" % (total if total else "none") + (" (the first %d are listed)" % len(e["failing_tests"]) if total > len(e["failing_tests"]) else ""))
        lines += ["  " + vis(n) for n in e["failing_tests"]]
    return "\n".join(lines) + "\n"


def document(kind, doc):
    """The text of a document of a kind, checked against its registry file before it is printed (R-J9)."""
    try:
        text = json.dumps(doc, sort_keys=True, ensure_ascii=True, indent=1, allow_nan=False) + "\n"
    except (ValueError, TypeError) as e:
        raise Defect("the document of %s cannot be written as JSON (%s)" % (kind, e))
    try:
        found = K.validate(K.registry_path(kind), text)
    except K.RegistryError as e:
        raise Defect("the document of %s cannot be checked: %s" % (kind, e))
    if found:
        raise Defect("the document of %s breaks its registry file at %s %s: %s" % (kind, found[0].rule, found[0].path, found[0].message))
    return text


def emit(text):
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (OSError, ValueError) as e:
        print("qargi: cannot write the report: %s" % (getattr(e, "strerror", None) or e), file=sys.stderr)
        return 1
    return 0


def project_in_effect(name):
    if name:
        return name
    from help import infer_project
    return infer_project()


def read_main(argv):
    p = argparse.ArgumentParser(prog="qargi history", allow_abbrev=False)
    p.add_argument("action", nargs="?", choices=("show",))
    p.add_argument("id", nargs="?")
    p.add_argument("--project")
    p.add_argument("--kind", choices=ENTRY_KINDS)
    p.add_argument("--head")
    p.add_argument("--limit", type=int)
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    if (a.action == "show") != (a.id is not None):
        p.error("usage: qargi history show ID [--project P] [--json]")
    if a.action == "show" and (a.kind or a.head or a.limit is not None):
        p.error("--kind, --head and --limit belong to the list, not to show")
    if a.head is not None and not HEX_RE.match(a.head):
        p.error("--head is a hex prefix of a commit sha, 4 to 64 digits")
    if a.limit is not None and not 1 <= a.limit <= MAX_LIMIT:
        p.error("--limit is a number from 1 to %d" % MAX_LIMIT)
    project = project_in_effect(a.project)
    if not project or not PROJECT_RE.match(project):
        p.error("name a project with --project P")
    try:
        entries, skipped = read(project)
        if a.action == "show":
            if not HEX_RE.match(a.id):
                p.error("ID is a hex prefix of an entry id, 4 to 16 digits")
            found = [e for e in entries if e["id"].startswith(a.id)]
            if len(found) != 1:
                print("qargi: %s" % ("no history entry of %s has the id %s" % (project, a.id) if not found else "%d history entries of %s start with %s: give more of the id" % (len(found), project, a.id)), file=sys.stderr)
                return 1
            return emit(document(ENTRY_KIND, found[0]) if a.json else show_text(found[0]))
        chosen = select(entries, a.kind, a.head)
        chosen.reverse()                                   # newest first
        limit = a.limit or DEFAULT_LIMIT
        shown = chosen[:limit]
        if a.json:
            return emit(document(LIST_KIND, {"schema": SCHEMA, "kind": LIST_KIND, "project": project, "matched": len(chosen), "skipped": skipped, "entries": shown}))
        text = table(shown) if shown else "no history entry of %s%s\n" % (project, " matches" if entries else "")
        if len(chosen) > len(shown):
            text += "(%d more; --limit N shows more)\n" % (len(chosen) - len(shown))
        return emit(text)
    except Defect as e:
        print("qargi: %s; this is a defect of qargi, not of the history" % e, file=sys.stderr)
        return 70
    except HistoryError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1


def main(argv):
    if argv[:1] == ["read"]:
        return read_main(argv[1:])
    if argv[:1] == ["write"]:
        return write_main(argv[1:])
    print("usage: history.py read ... | write suite|review ... (qargi history is read)", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
