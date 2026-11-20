#!/usr/bin/env python3
"""The launcher of a whole-suite run, and the declaration it applies (`verify.environment`).

A suite that runs through this launcher starts from a known state: default signal dispositions and an empty mask, only the descriptors it
is declared to have, a session of its own with no terminal, a transient cgroup with the cpu controller on, and an environment built from
an allowlist. A part that cannot be applied refuses the run with a code; nothing is silently skipped. Standard library only.

Subcommands (every JSON argument is the text of a JSON value; `null` means the setting is off):

  run --decl DECL --waive PARTS --report FILE [--cpu-route no-scope --cpu-code CODE] -- COMMAND...
        stage 1, in the caller's environment. Writes the job (declaration, argv, waived parts, report path) to an anonymous file on
        descriptor 3 and replaces itself with `systemd-run --user --scope ...` (the scope route) or with stage 2 (the no-scope route).
        The route is chosen before the exec and never after it. A refusal it can see itself (no systemd-run, one below
        MIN_SYSTEMD, an invalid declaration) is written to the report as {"refused": [...]} and the exit status is 125.
        PARTS is a comma-separated list of signals, fds, tty, cpu (empty: none). The exit status of a complete run is the command's
        (128+N for a signal); the verdict is read from the report (its `complete` key), never from the status alone.
  stage2 --job-fd N [--no-scope]
        stage 2, inside the scope. Not called by hand.
  probe --decl DECL
        makes the attempt for a run before its worktree exists: runs a no-op command through `run` with a throwaway report and prints
        {"ok", "route", "refused": [codes], "details": [{"part", "code", "found"}], "stderr": [last lines]} on standard output.
        Exit 0 when everything applies, 1 when a part refuses, 3 when the launcher itself failed without a scope.
  problems DECL           one line per problem with the declaration, exit 1 when there is one (exit 0: valid or null)
  normalise DECL          the normalised declaration (defaults filled in, names sorted) as compact JSON, `null` for off
  hash DECL               sha256 of the normalised declaration alone: the `decl` of the state entry (not the id; see id)
  id DECL                 the first 12 hex digits of the sha256 of LAUNCHER_VERSION and the normalised declaration; empty for off
  loosens OLD NEW         `loosens` and the reasons (exit 0), or `plain` (exit 1); exit 2 when a declaration is invalid
  approved get NAME [--state DIR]
  approved set NAME DECL --by VERB [--state DIR]
  approved check NAME DECL [--state DIR]
        the declaration qargi last accepted for a project, kept in STATE/verify-env.json (mode 600, replaced atomically under a lock):
        {"declared": NORMALISED-or-null, "decl": HASH, "at": TIME, "by": VERB}. `get` prints the entry, exit 1 when there is none.
        `set` writes it (DECL `null` stores "declared": null). `check` prints {"equal", "answers", "state", "entry"} (the two hashes;
        no entry counts as off, `entry` says whether there is one), exit 0 when equal and 1 when not.
        A state file that cannot be read (not JSON, no "projects" object) is exit 3 in all three verbs, with a message and nothing on standard
        output: a caller that branches on 1 for "no entry" is never told that a damaged file is a first declaration.

Library use: problems(decl), normalise(decl), loosens(old, new), decl_hash(n), suite_env_id(n), cpu_max_ok(text, quota), cgroup_path(text),
sig_clean(ign, blk), and the refusal codes (CODES, and one constant for each).
"""
import argparse
import errno
import fcntl
import hashlib
import json
import os
import re
import select
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import procenv  # noqa: E402

LAUNCHER_VERSION = 1            # raised whenever what the launcher applies changes: it is part of the id, so earlier runs go stale
DEFAULT_FDS = "close"
DEFAULT_CI_FDS = (142, 145)     # [READ, WRITE]
DEFAULT_CPU_QUOTA = "max"       # the controller on and no quota: what the reference runner has (cpu.max `max 100000`)
CPU_WEIGHT = 100                # CPUWeight of the "max" scope: the reference runner's cpu.weight
QUOTA_MIN, QUOTA_MAX = 10, 12800
CI_FD_MIN, CI_FD_MAX = 3, 1023
SLICE = "qargi-verify.slice"
MIN_SYSTEMD = 254
PARTS = ("signals", "fds", "tty", "cpu")
KEYS = ("fds", "ci_fds", "cpu_quota", "env_pass", "env_set")
FDS_VALUES = ("close", "ci-like")
FORWARD = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP, signal.SIGQUIT)
LIBC_SIGNALS = (32, 33)         # the C library's own: python cannot set them, so a bit of them in SigIgn is noted, not refused
LIBC_BITS = sum(1 << (n - 1) for n in LIBC_SIGNALS)
CGROUP_ROOT = "/sys/fs/cgroup"
NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
QUOTA_RE = re.compile(r"([1-9][0-9]*)%")
STATE_NAME = "verify-env.json"
STATE_DAMAGED = 3               # the exit status of an `approved` verb when the state file cannot be read: never "no entry" (1)
REFUSED_STATUS = 125            # the launcher refused, or could not start the command
CLEANUP_ROUNDS, CLEANUP_STEP = 5, 0.4          # at most 5 rounds over 2 seconds

CODE_INVALID = "verify-env-invalid"
CODE_CHANGE_UNAPPROVED = "verify-env-change-unapproved"
CODE_NO_SYSTEMD_RUN = "verify-env-cpu-no-systemd-run"
CODE_SYSTEMD_TOO_OLD = "verify-env-cpu-systemd-too-old"
CODE_NO_USER_MANAGER = "verify-env-cpu-no-user-manager"
CODE_CPU_READBACK = "verify-env-cpu-readback"
CODE_SIGNALS = "verify-env-signals"
CODE_FDS = "verify-env-fds"
CODE_TTY = "verify-env-tty"
CODE_NO_LOG = "verify-env-no-log"
CODE_WAIVE_UNAPPROVED = "verify-env-waive-unapproved"
CODE_WAIVE_UNKNOWN = "verify-env-waive-unknown"
# code -> the part it belongs to (None: no part)
CODES = {CODE_INVALID: None, CODE_CHANGE_UNAPPROVED: None, CODE_NO_SYSTEMD_RUN: "cpu", CODE_SYSTEMD_TOO_OLD: "cpu",
         CODE_NO_USER_MANAGER: "cpu", CODE_CPU_READBACK: "cpu", CODE_SIGNALS: "signals", CODE_FDS: "fds", CODE_TTY: "tty",
         CODE_NO_LOG: "tty", CODE_WAIVE_UNAPPROVED: None, CODE_WAIVE_UNKNOWN: None}
RESERVED_NAMES = ("PATH", "HOME")


class Invalid(ValueError):
    """A declaration that problems() refuses; .problems is the list of lines."""

    def __init__(self, found):
        super().__init__("; ".join(found))
        self.problems = list(found)


# --------------------------------------------------------------------------------------------------------------------------------
# the declaration

_CLOUD_NAMES = None


def _parse_cloud_names(text):
    """The names that `env -u NAME` removes in the run_clean function of a lib.sh text; () when the function or the form is not found."""
    m = re.search(r"^run_clean\(\)[^\n]*\n(.*?)^\}", text, re.M | re.S)
    return tuple(re.findall(r"-u ([A-Za-z_][A-Za-z0-9_]*)", m.group(1))) if m else ()


def cloud_binding_names():
    """The variables run_clean (lib/lib.sh) removes before a suite runs, read from there so the two lists cannot drift; QARGI_* is refused
    as a prefix anyway. () when lib.sh cannot be read or run_clean has another shape: _name_problems then refuses every name, since the
    list that must not be passed on is not known."""
    global _CLOUD_NAMES
    if _CLOUD_NAMES is None:
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib.sh")) as f:
                _CLOUD_NAMES = _parse_cloud_names(f.read())
        except OSError:
            _CLOUD_NAMES = ()
    return _CLOUD_NAMES


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _name_problems(label, name, out):
    if not isinstance(name, str) or not NAME_RE.fullmatch(name):
        out.append("%s: %r is not a variable name ([A-Za-z_][A-Za-z0-9_]*)" % (label, name))
        return
    if name in RESERVED_NAMES:
        out.append("%s: %s always passes and cannot be declared" % (label, name))
    elif name.startswith("QARGI_"):
        out.append("%s: %s: no QARGI_* name is accepted" % (label, name))
    elif not cloud_binding_names():
        out.append("%s: %s cannot be accepted: the variables run_clean removes cannot be read from lib.sh" % (label, name))
    elif name in cloud_binding_names():
        out.append("%s: %s is removed from every suite run and cannot be declared" % (label, name))


def problems(decl):
    """The problems with a declaration as a list of lines (empty: valid). None (off) is valid."""
    if decl is None:
        return []
    if not isinstance(decl, dict):
        return ["verify.environment must be an object or null, not %s" % type(decl).__name__]
    out = []
    for k in decl:
        if k not in KEYS:
            out.append("unknown key %r (the keys are %s)" % (k, ", ".join(KEYS)))
    fds = decl.get("fds", DEFAULT_FDS)
    if fds not in FDS_VALUES or not isinstance(fds, str):
        out.append("fds: %r is not one of %s" % (fds, ", ".join(FDS_VALUES)))
    if "ci_fds" in decl:
        v = decl["ci_fds"]
        if fds != "ci-like":
            out.append("ci_fds is accepted only with fds ci-like")
        if not (isinstance(v, list) and len(v) == 2 and all(_is_int(x) for x in v) and v[0] != v[1]
                and all(CI_FD_MIN <= x <= CI_FD_MAX for x in v)):
            out.append("ci_fds: %r is not [READ, WRITE], two different integers from %d to %d" % (v, CI_FD_MIN, CI_FD_MAX))
    if "cpu_quota" in decl:
        v = decl["cpu_quota"]
        m = QUOTA_RE.fullmatch(v) if isinstance(v, str) else None
        if not (v is None or v == "max" or (m and QUOTA_MIN <= int(m.group(1)) <= QUOTA_MAX)):
            out.append("cpu_quota: %r is not \"N%%\" (N from %d to %d), \"max\" or null" % (v, QUOTA_MIN, QUOTA_MAX))
    names = {}
    if "env_pass" in decl:
        v = decl["env_pass"]
        if not isinstance(v, list):
            out.append("env_pass: %r is not a list of names" % (v,))
        else:
            for n in v:
                _name_problems("env_pass", n, out)
            if len(set(n for n in v if isinstance(n, str))) != len([n for n in v if isinstance(n, str)]):
                out.append("env_pass: a name is listed twice")
            names["env_pass"] = {n for n in v if isinstance(n, str)}
    if "env_set" in decl:
        v = decl["env_set"]
        if not isinstance(v, dict):
            out.append("env_set: %r is not an object of name to string" % (v,))
        else:
            for n, val in v.items():
                _name_problems("env_set", n, out)
                if not isinstance(val, str) or any(c in val for c in "\0\n\r"):
                    out.append("env_set: the value of %s is not a string without NUL or line break" % n)
            names["env_set"] = set(v)
    both = names.get("env_pass", set()) & names.get("env_set", set())
    for n in sorted(both):
        out.append("%s is in both env_pass and env_set" % n)
    return out


def normalise(decl):
    """The declaration with every default filled in and the names sorted: what the id and the state entry are computed from. None (off)
    stays None. A declaration that problems() refuses raises Invalid."""
    found = problems(decl)
    if found:
        raise Invalid(found)
    if decl is None:
        return None
    n = {"fds": decl.get("fds", DEFAULT_FDS)}
    if n["fds"] == "ci-like":
        n["ci_fds"] = list(decl.get("ci_fds", DEFAULT_CI_FDS))
    n["cpu_quota"] = decl["cpu_quota"] if "cpu_quota" in decl else DEFAULT_CPU_QUOTA
    n["env_pass"] = sorted(decl.get("env_pass", []))
    n["env_set"] = dict(sorted(decl.get("env_set", {}).items()))
    return n


def canonical(n):
    """The one text a normalised declaration has: compact JSON with sorted keys."""
    return json.dumps(n, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def decl_hash(n):
    """sha256 (hex) of the normalised declaration alone: the `decl` of the approved entry. It does not hold LAUNCHER_VERSION, so an upgrade
    of qargi does not make every stored declaration differ."""
    return hashlib.sha256(canonical(n).encode()).hexdigest()


def suite_env_id(n):
    """The first 12 hex digits of the sha256 of LAUNCHER_VERSION and the normalised declaration; "" for off. A run is stale when it changes."""
    if n is None:
        return ""
    return hashlib.sha256(("%d\n%s" % (LAUNCHER_VERSION, canonical(n))).encode()).hexdigest()[:12]


def _quota_rank(q):
    """Stricter is higher: null, then "max", then N% with a lower N stricter."""
    if q is None:
        return (0, 0)
    if q == "max":
        return (1, 0)
    return (2, -int(QUOTA_RE.fullmatch(q).group(1)))


def loosens(old, new):
    """(loosening, reasons): whether replacing the declaration OLD by NEW needs a plan token and the owner's words. Plain (tightening, or
    no change): nothing was declared before, or only cpu_quota changed and became stricter (null to a value, "max" to N%, N% to a lower
    N%). Everything else is a loosening: removal, a higher quota, any change of fds, ci_fds, env_pass or env_set. Both are the values of the
    declaration, normalised or not; an invalid one raises Invalid."""
    o, n = normalise(old), normalise(new)
    if o is None or o == n:
        return False, []
    if n is None:
        return True, ["the declaration is removed"]
    why = []
    for k in ("fds", "ci_fds", "env_pass", "env_set"):
        if o.get(k) != n.get(k):
            why.append("%s changes" % k)
    if o["cpu_quota"] != n["cpu_quota"] and _quota_rank(n["cpu_quota"]) < _quota_rank(o["cpu_quota"]):
        why.append("cpu_quota goes from %s to the weaker %s" % (json.dumps(o["cpu_quota"]), json.dumps(n["cpu_quota"])))
    return bool(why), why


# --------------------------------------------------------------------------------------------------------------------------------
# the approved declaration (the state entry)

def state_file(state=None):
    return os.path.join(state or _state_dir(), STATE_NAME)


def _state_dir():
    import paths
    return paths.state()


def _read_state(path):
    try:
        with open(path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return {"version": 1, "projects": {}}
    except (OSError, ValueError) as e:
        _say("%s cannot be read as the approved declarations (%s); restore it or remove it by hand" % (path, e))
        raise SystemExit(STATE_DAMAGED)
    if not isinstance(data, dict) or not isinstance(data.get("projects"), dict):
        _say("%s cannot be read as the approved declarations (it has no \"projects\" object); restore it or remove it by hand" % path)
        raise SystemExit(STATE_DAMAGED)
    return data


def approved_get(name, state=None):
    """The entry of a project, or None when it has none."""
    entry = _read_state(state_file(state))["projects"].get(name)
    return entry if isinstance(entry, dict) else None


def approved_set(name, decl, by, state=None, now=None):
    """Store the declaration (None: off) as the one accepted for a project, by the verb BY; returns the entry. Written to a temporary file
    in the same directory (mode 600) and renamed, under an exclusive lock, so two writers do not lose each other's entry."""
    n = normalise(decl)
    entry = {"declared": n, "decl": decl_hash(n), "at": now or procenv.now(), "by": by}
    path = state_file(state)
    d = os.path.dirname(path)
    os.makedirs(d, mode=0o700, exist_ok=True)
    lock = os.open(path + ".lock", os.O_WRONLY | os.O_CREAT | os.O_CLOEXEC, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = _read_state(path)
        data["projects"][name] = entry
        fd, tmp = tempfile.mkstemp(prefix=STATE_NAME + ".", dir=d)
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=1, sort_keys=True)
                f.write("\n")
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
    finally:
        os.close(lock)
    return entry


def approved_check(name, decl, state=None):
    """{"equal", "answers", "state", "entry"}: the hash of the normalised DECL (the answers' declaration), the hash of the stored one (no
    entry counts as off) and whether there is an entry. Equal when the two hashes are."""
    entry = approved_get(name, state)
    a = decl_hash(normalise(decl))
    s = decl_hash(entry.get("declared")) if entry else decl_hash(None)
    return {"equal": a == s, "answers": a, "state": s, "entry": entry is not None}


# --------------------------------------------------------------------------------------------------------------------------------
# pure readers of what the kernel says

def cgroup_path(text):
    """The path of the unified-hierarchy line (`0::/path`) of /proc/PID/cgroup, or None."""
    for line in text.splitlines():
        if line.startswith("0::"):
            p = line[3:].strip()
            if p.endswith(" (deleted)"):
                p = p[:-len(" (deleted)")]
            return p if p.startswith("/") else None
    return None


def cpu_max_ok(text, quota):
    """Whether the content of a cpu.max file is what the quota declares: first field `max` for "max", else quota/period equal to N/100."""
    f = text.split()
    if len(f) != 2 or quota is None:
        return False
    if quota == "max":
        return f[0] == "max"
    m = QUOTA_RE.fullmatch(quota)
    if not m or f[0] == "max" or not (f[0].isdigit() and f[1].isdigit()) or int(f[1]) == 0:
        return False
    return int(f[0]) * 100 == int(m.group(1)) * int(f[1])


def sig_clean(ign, blk):
    """(ok, libc_bits_set): the mask SigBlk is zero and SigIgn is zero apart from the bits of signals 32 and 33, which belong to the C library
    and cannot be reset from python; the second value says whether those were set. Arguments are integers or hex strings."""
    ign = int(ign, 16) if isinstance(ign, str) else ign
    blk = int(blk, 16) if isinstance(blk, str) else blk
    return (blk == 0 and (ign & ~LIBC_BITS) == 0), bool(ign & LIBC_BITS)


def _proc_status(path="/proc/self/status"):
    out = {}
    with open(path) as f:
        for line in f:
            k, _, v = line.partition(":")
            out[k] = v.strip()
    return out


def _read(path):
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _list_fds():
    """The open descriptors of this process. The listing itself holds one while it reads the directory; it is closed again by the time the
    names are back, so a name whose /proc/self/fd entry is gone is that one."""
    names = os.listdir("/proc/self/fd")
    return sorted(int(n) for n in names if os.path.lexists("/proc/self/fd/" + n))


def _fdinfo_flags(fd):
    text = _read("/proc/self/fdinfo/%d" % fd) or ""
    m = re.search(r"^flags:\s*([0-7]+)", text, re.M)
    return m.group(1) if m else None


def _errname(e):
    return errno.errorcode.get(e.errno, str(e.errno))


# --------------------------------------------------------------------------------------------------------------------------------
# the report

def write_report(path, obj):
    """Write the report atomically (a temporary file beside it, mode 600, renamed)."""
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(prefix=".report.", dir=d)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(obj, f, indent=1, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_report(path):
    try:
        with open(path) as f:
            r = json.load(f)
    except (OSError, ValueError):
        return None
    return r if isinstance(r, dict) else None


def _say(msg):
    print("qargi: " + msg, file=sys.stderr, flush=True)


def _base_report(norm, waive):
    return {"id": suite_env_id(norm), "launcher": LAUNCHER_VERSION, "declared": norm, "waived": sorted(waive), "parts": {},
            "codes": [], "details": [], "warnings": []}


# --------------------------------------------------------------------------------------------------------------------------------
# stage 1

def _systemd_version(path):
    try:
        r = subprocess.run([path, "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        return None, str(e)
    first = (r.stdout.splitlines() or [""])[0]
    m = re.match(r"systemd (\d+)", first)
    return (int(m.group(1)) if m else None), first or (r.stderr.strip().splitlines() or [""])[0]


def _refuse(report, norm, waive, code, found):
    """Stage 1's own refusal: the report names the code, the exit status is 125."""
    rep = _base_report(norm, waive)
    part = CODES.get(code)
    rep.update(refused=[code], complete=True, exit=REFUSED_STATUS)
    rep["details"] = [{"part": part, "code": code, "found": found}]
    if part:
        rep["parts"][part] = "refused"
    write_report(report, rep)
    _say("%s: %s: %s" % (code, part or "-", found))
    raise SystemExit(REFUSED_STATUS)


def _job_to_fd3(job):
    data = json.dumps(job).encode()
    try:
        fd = os.memfd_create("qargi-suite-job")
    except (AttributeError, OSError):
        f = tempfile.TemporaryFile()
        fd = os.dup(f.fileno())
        f.close()
    while data:
        data = data[os.write(fd, data):]
    os.lseek(fd, 0, os.SEEK_SET)
    if fd != 3:
        os.dup2(fd, 3, inheritable=True)
        os.close(fd)
    else:
        os.set_inheritable(3, True)


def _usage(msg):
    print("qargi: suite_env.py: " + msg, file=sys.stderr)
    raise SystemExit(2)


def _split_parts(text):
    parts = [p for p in (text or "").split(",") if p]
    bad = [p for p in parts if p not in PARTS]
    if bad:
        _usage("not a part: %s (the parts are %s)" % (", ".join(bad), ", ".join(PARTS)))
    return parts


def _parse_json(text, what):
    try:
        return json.loads(text)
    except ValueError as e:
        _usage("%s is not JSON: %s" % (what, e))


def cmd_run(args, command):
    if not command:
        _usage("run: no command after --")
    try:
        os.unlink(args.report)          # a report that an earlier command left must never stand for this one
    except FileNotFoundError:
        pass
    waive = _split_parts(args.waive)
    decl = _parse_json(args.decl, "--decl")
    if decl is None:
        _usage("run: --decl is null: the setting is off, run the command directly")
    try:
        norm = normalise(decl)
    except Invalid as e:
        _refuse(args.report, None, waive, CODE_INVALID, "; ".join(e.problems))
    no_scope = norm["cpu_quota"] is None or args.cpu_route == "no-scope"
    if args.cpu_route == "no-scope" and norm["cpu_quota"] is not None and not args.cpu_code:
        _usage("run: --cpu-route no-scope needs --cpu-code CODE (the code of the failed attempt)")
    if args.cpu_code and CODES.get(args.cpu_code) != "cpu":
        _usage("run: --cpu-code %s is not a refusal code of the cpu part (%s)" % (
            args.cpu_code, ", ".join(c for c, p in CODES.items() if p == "cpu")))
    os.environ["PATH"] = procenv.clean_path()
    job = {"decl": norm, "argv": command, "waive": waive, "report": os.path.abspath(args.report),
           "cpu_code": args.cpu_code if (no_scope and norm["cpu_quota"] is not None) else None, "systemd": None}
    here = os.path.abspath(__file__)
    if no_scope:
        _job_to_fd3(job)
        py = [sys.executable] + (["-B"] if sys.flags.dont_write_bytecode else [])
        os.execv(sys.executable, py + ["-I", here, "stage2", "--job-fd", "3", "--no-scope"])
    found = shutil.which("systemd-run", path=procenv.clean_path())
    if not found:
        _refuse(args.report, norm, waive, CODE_NO_SYSTEMD_RUN, "systemd-run is not on PATH (%s)" % procenv.clean_path())
    version, line = _systemd_version(found)
    if version is None or version < MIN_SYSTEMD:
        _refuse(args.report, norm, waive, CODE_SYSTEMD_TOO_OLD,
                "systemd-run reports %r; %d or newer is needed" % (line, MIN_SYSTEMD))
    job["systemd"] = version
    prop = "CPUWeight=%d" % CPU_WEIGHT if norm["cpu_quota"] == "max" else "CPUQuota=%s" % norm["cpu_quota"]
    _job_to_fd3(job)
    # nothing here comes from the declaration's strings or from the command: the job went on descriptor 3
    os.execv(found, ["systemd-run", "--user", "--scope", "--quiet", "--collect", "--expand-environment=no", "--slice=" + SLICE,
                     "-p", prop, "--", "python3", "-I", here, "stage2", "--job-fd", "3"])


# --------------------------------------------------------------------------------------------------------------------------------
# stage 2

def _scope_dir(self_cgroup="/proc/self/cgroup", pid=None):
    """The cgroup directory of this process when it is a scope below SLICE that holds this process alone: the scope `systemd-run --scope` has
    just made for it, which moves only the process in and executes it, so every member is this run's. An enclosing run's scope (no scope was
    made for this one, as with a stand-in for systemd-run) holds other processes, and is never ours to signal or clean: None. Called before
    the fork."""
    path = cgroup_path(_read(self_cgroup) or "")
    if not path:
        return None
    comps = path.strip("/").split("/")
    if not (SLICE in comps[:-1] and comps[-1].endswith(".scope")):
        return None
    d = CGROUP_ROOT + path
    if (_read(d + "/cgroup.procs") or "").split() != [str(pid if pid is not None else os.getpid())]:
        return None
    return d


def _proc_state(pid):
    """(comm, state letter, pgrp) of a process, or None when it is gone."""
    text = _read("/proc/%d/stat" % pid)
    if not text:
        return None
    lp, rp = text.find("("), text.rfind(")")
    if lp < 0 or rp < 0:
        return None
    rest = text[rp + 2:].split()
    try:
        return text[lp + 1:rp], rest[0], int(rest[2])
    except (IndexError, ValueError):
        return None


def _pgroup_pids(pgid):
    out = []
    for n in os.listdir("/proc"):
        if n.isdigit():
            st = _proc_state(int(n))
            if st and st[2] == pgid:
                out.append(int(n))
    return out


def _members(scope, pgid, me):
    """The (pid, comm) of every live process of the scope or, without one, of the child's process group, not counting this process."""
    if scope:
        text = _read(scope + "/cgroup.procs") or ""
        pids = [int(x) for x in text.split() if x.isdigit()]
    else:
        pids = _pgroup_pids(pgid)
    out = []
    for pid in pids:
        st = _proc_state(pid)
        if pid != me and st and st[1] not in ("Z", "X"):
            out.append((pid, st[0]))
    return out


def _child_fds(ci, ci_fds, ends, errs):
    """Close every descriptor from 3 up except the child's two pipe ends and put those on their numbers (READ non-blocking). A failure is a
    line in errs, which makes the fds part fail after the report is open."""
    keep = set(ends) if ci else set()
    try:
        for fd in _list_fds():
            if fd >= 3 and fd not in keep:
                try:
                    os.close(fd)
                except OSError:
                    pass
    except OSError as e:
        errs.append("cannot list /proc/self/fd: %s" % e)
    if not ci:
        return
    try:
        def off_target(fd):
            """The lowest copy of fd from 3 up that is neither target: the soft limit on descriptors is often 1024, so no copy is made above them."""
            n = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 3)
            while n in ci_fds:
                m = fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, n + 1)
                os.close(n)
                n = m
            return n
        a_r = off_target(ends[0])
        b_w = off_target(ends[1])
        os.close(ends[0])
        os.close(ends[1])
        os.set_blocking(a_r, False)
        os.dup2(a_r, ci_fds[0], inheritable=True)
        os.dup2(b_w, ci_fds[1], inheritable=True)
        os.close(a_r)
        os.close(b_w)
    except OSError as e:
        errs.append("cannot place the pipes on %s: %s" % (ci_fds, e))


def _reset_signals():
    for sig in signal.valid_signals():
        if sig in (signal.SIGKILL, signal.SIGSTOP):
            continue
        try:
            signal.signal(sig, signal.SIG_DFL)
        except (OSError, ValueError, RuntimeError):
            pass                  # 32 and 33: the C library's
    signal.pthread_sigmask(signal.SIG_SETMASK, [])


def _check_signals(readback):
    st = _proc_status()
    ign, blk = st.get("SigIgn", "?"), st.get("SigBlk", "?")
    try:
        ok, libc = sig_clean(ign, blk)
        readback["sig_ign"], readback["sig_blk"] = format(int(ign, 16), "x"), format(int(blk, 16), "x")
    except ValueError:
        readback["sig_ign"], readback["sig_blk"] = ign, blk
        return ["SigIgn and SigBlk cannot be read from /proc/self/status"], []
    warn = []
    if libc:
        readback["sig_ign_libc"] = True
        warn.append("SigIgn has the bits of signals 32 and 33 (the C library's) set; python cannot reset them")
    if ok:
        return [], warn
    return ["SigIgn %s and SigBlk %s are not both zero%s" % (readback["sig_ign"], readback["sig_blk"],
                                                           " (apart from signals 32 and 33)" if libc else "")], warn


def _check_fds(readback, ci, ci_fds, report_fd, errs):
    found = _list_fds()
    readback["fds"] = found
    bad = list(errs)
    expected = {0, 1, 2} | set(ci_fds if ci else []) | {report_fd}
    if set(found) != expected:
        bad.append("the open descriptors are %s, expected %s" % (found, sorted(expected)))
    for fd in (0, 1, 2):
        try:
            if fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC:
                bad.append("descriptor %d is close-on-exec: the command would not have it" % fd)
        except OSError:
            pass                                                # a missing one is in the set check above
    try:
        if not fcntl.fcntl(report_fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC:
            bad.append("the report descriptor %d is not close-on-exec" % report_fd)
    except OSError as e:
        bad.append("the report descriptor %d: %s" % (report_fd, e))
    if not ci:
        return bad
    entries, inodes = [], []
    for fd, end in zip(ci_fds, ("read", "write")):
        e = {"fd": fd, "end": end}
        entries.append(e)
        try:
            st = os.fstat(fd)
            e["kind"] = "pipe" if stat.S_ISFIFO(st.st_mode) else "other"
            inodes.append(st.st_ino)
            e["flags"] = _fdinfo_flags(fd)
            e["cloexec"] = bool(fcntl.fcntl(fd, fcntl.F_GETFD) & fcntl.FD_CLOEXEC)
        except OSError as ex:
            bad.append("descriptor %d (%s end): %s" % (fd, end, ex))
            continue
        want = 0o4000 if end == "read" else 0o1
        flags = int(e["flags"], 8) if e["flags"] else -1
        if e["kind"] != "pipe":
            bad.append("descriptor %d is not a pipe" % fd)
        if flags & (0o3 | 0o4000) != want:
            bad.append("descriptor %d (%s end) has flags %s, expected %s" % (fd, end, e["flags"], "01" if want == 1 else "04000"))
        if e["cloexec"]:
            bad.append("descriptor %d is close-on-exec" % fd)
        if end == "read" and flags & 0o4000:                    # never read a blocking pipe: with no writer data it would wait for ever
            try:
                got = os.read(fd, 1)
                e["read"] = "EOF" if got == b"" else "DATA"
                bad.append("a read of descriptor %d gave %s, expected EAGAIN" % (fd, "end-of-file" if got == b"" else "data"))
            except BlockingIOError:
                e["read"] = "EAGAIN"
            except OSError as ex:
                e["read"] = _errname(ex)
                bad.append("a read of descriptor %d failed with %s, expected EAGAIN" % (fd, _errname(ex)))
    if len(inodes) == 2 and inodes[0] == inodes[1]:
        bad.append("descriptors %d and %d are the same pipe" % tuple(ci_fds))
    readback["ci_fds"] = entries
    return bad


def _check_tty(readback, sid_error):
    bad = []
    if sid_error:
        bad.append("setsid failed: %s" % sid_error)
    readback["sid"] = os.getsid(0)
    if os.getsid(0) != os.getpid():
        bad.append("this process is not a session leader")
    ttys = [fd for fd in (0, 1, 2) if os.isatty(fd)]
    if ttys:
        bad.append("descriptors %s are terminals" % ttys)
    try:
        fd = os.open("/dev/tty", os.O_RDWR | os.O_CLOEXEC)
        os.close(fd)
        readback["dev_tty_errno"] = "opened"
        bad.append("/dev/tty opens: the session has a controlling terminal")
    except OSError as e:
        readback["dev_tty_errno"] = _errname(e)
        if e.errno not in (errno.ENXIO, errno.ENOENT):
            bad.append("/dev/tty failed with %s, expected ENXIO" % _errname(e))
    return bad


def _check_cpu(readback, quota, cpu_code, own_scope=True):
    if cpu_code:
        return cpu_code, "no scope: the attempt before the run failed with %s" % cpu_code
    if not own_scope:
        return CODE_CPU_READBACK, "this process is not alone in a new scope below %s: a cpu.max read from a cgroup that is not this run's would prove nothing" % SLICE
    path = cgroup_path(_read("/proc/self/cgroup") or "")
    readback["cgroup"] = path
    if not path:
        return CODE_CPU_READBACK, "/proc/self/cgroup has no unified-hierarchy line"
    if SLICE not in path.strip("/").split("/"):
        return CODE_CPU_READBACK, "the process is in %s, not below %s" % (path, SLICE)
    text = _read(CGROUP_ROOT + path + "/cpu.max")
    if text is None:
        return CODE_CPU_READBACK, "%s has no cpu.max (the cpu controller is off there)" % path
    readback["cpu_max"] = text.strip()
    weight = _read(CGROUP_ROOT + path + "/cpu.weight")
    if weight is not None:
        readback["cpu_weight"] = weight.strip()
    if not cpu_max_ok(text, quota):
        return CODE_CPU_READBACK, "cpu.max is %r, declared %s" % (text.strip(), json.dumps(quota))
    return None


def _child(job, ends, route, no_scope):
    """Runs in the forked child: steps 3 to 8. Does not return: it executes the command or exits."""
    decl, argv, waive = job["decl"], job["argv"], set(job["waive"])
    ci = decl["fds"] == "ci-like"
    ci_fds = decl.get("ci_fds", [])
    errs = {"fds": [], "tty": []}
    sid_error = None
    try:
        os.setsid()
    except OSError as e:
        sid_error = str(e)
    try:
        fd = os.open("/dev/null", os.O_RDONLY)
        if fd != 0:
            os.dup2(fd, 0, inheritable=True)
            os.close(fd)
    except OSError as e:
        errs["fds"].append("cannot open /dev/null for standard input: %s" % e)
    _child_fds(ci, ci_fds, ends, errs["fds"])
    _reset_signals()
    caller = os.environ
    env = {"PATH": procenv.clean_path()}
    if "HOME" in caller:
        env["HOME"] = caller["HOME"]
    unset = []
    for n in decl["env_pass"]:
        if n in caller:
            env[n] = caller[n]
        else:
            unset.append(n)
    env.update(decl["env_set"])
    report_fd = os.open(job["report"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_CLOEXEC, 0o600)
    rep = _base_report(decl, waive)
    rb = rep["readback"] = {}
    fails, warn = {}, rep["warnings"]
    bad, w = _check_signals(rb)
    warn.extend(w)
    if bad:
        fails["signals"] = (CODE_SIGNALS, "; ".join(bad))
    bad = _check_fds(rb, ci, ci_fds, report_fd, errs["fds"])
    if bad:
        fails["fds"] = (CODE_FDS, "; ".join(bad))
    bad = _check_tty(rb, sid_error) + errs["tty"]
    if bad:
        fails["tty"] = (CODE_TTY, "; ".join(bad))
    quota = decl["cpu_quota"]
    if quota is not None:
        res = _check_cpu(rb, quota, job.get("cpu_code") if no_scope else None, route == "cgroup")
        if res:
            fails["cpu"] = res
    rb["env_names"] = sorted(env)
    rb["env_pass_unset"] = unset
    if job.get("systemd") is not None:
        rb["systemd"] = job["systemd"]
    refused = []
    for part in PARTS:
        if part == "cpu" and quota is None:
            rep["parts"][part] = "off"
        elif part in fails:
            code, found = fails[part]
            rep["details"].append({"part": part, "code": code, "found": found})
            if part in waive:
                rep["parts"][part] = "waived-failed"
                rep["codes"].append(code)
                warn.append("%s waived: %s (%s)" % (part, found, code))
            else:
                rep["parts"][part] = "refused"
                refused.append(code)
        else:
            rep["parts"][part] = "applied"
    rep["parts"]["env"] = "applied"
    rep["cleanup"] = route
    rep["leftovers"] = []
    if refused:
        rep["refused"] = refused
    data = (json.dumps(rep, indent=1, sort_keys=True) + "\n").encode()
    while data:
        data = data[os.write(report_fd, data):]
    os.close(report_fd)
    for d in rep["details"]:
        _say("%s: %s: %s" % (d["code"], d["part"], d["found"]) if d["code"] in refused else
             "warning: verify.environment: %s waived-failed (%s): %s" % (d["part"], d["code"], d["found"]))
    for msg in warn:
        if msg.startswith("SigIgn"):
            _say("warning: " + msg)
    if refused:
        os._exit(REFUSED_STATUS)
    try:
        os.execvpe(argv[0], argv, env)
    except FileNotFoundError:
        _say("cannot run %s: not found" % argv[0])
        os._exit(127)
    except OSError as e:
        _say("cannot run %s: %s" % (argv[0], e))
        os._exit(126)


def _drain(fd):
    """Read and discard what is waiting on a non-blocking descriptor; False at end-of-file."""
    while True:
        try:
            if not os.read(fd, 65536):
                return False
        except BlockingIOError:
            return True
        except InterruptedError:
            continue
        except OSError:
            return False


def _wait(pid, b_r):
    """Wait for the child, discarding what the suite writes to its pipe; returns the wait status."""
    pfd = -1
    try:
        pfd = os.pidfd_open(pid)
    except (AttributeError, OSError):
        pass
    try:
        while True:
            watch = ([b_r] if b_r is not None else []) + ([pfd] if pfd >= 0 else [])
            if not watch:
                return os.waitpid(pid, 0)[1]
            ready, _, _ = select.select(watch, [], [], None if pfd >= 0 else 0.05)
            if b_r is not None and b_r in ready and not _drain(b_r):
                b_r = None
            got, status = os.waitpid(pid, os.WNOHANG)
            if got:
                return status
    finally:
        if pfd >= 0:
            os.close(pfd)


def _cleanup(scope, pgid, me, report_path, status):
    """After the child ended: list what is left, kill it, repeat; amend the report. Returns nothing."""
    left, survivors = [], []
    for rnd in range(CLEANUP_ROUNDS):
        ms = _members(scope, pgid, me)
        if rnd == 0:
            left = [{"pid": p, "comm": c} for p, c in ms]
            if ms:
                _say("left running after the command ended: %s; killed" % ", ".join("%d (%s)" % m for m in ms))
        if not ms:
            break
        for pid, _ in ms:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        end = time.monotonic() + CLEANUP_STEP
        while time.monotonic() < end and _members(scope, pgid, me):
            time.sleep(0.02)
    else:
        survivors = [{"pid": p, "comm": c} for p, c in _members(scope, pgid, me)]
        if survivors:
            _say("still running after %d rounds: %s" % (CLEANUP_ROUNDS, ", ".join("%d (%s)" % (s["pid"], s["comm"]) for s in survivors)))
    rep = read_report(report_path)
    if rep is None:
        return
    rep["leftovers"], rep["survivors"], rep["exit"], rep["complete"] = left, survivors, status, True
    write_report(report_path, rep)


def _ensure_std_fds():
    """A caller that closed 0, 1 or 2 would have the first descriptors made here (the pipes) land on them; give each a /dev/null first."""
    for fd in (0, 1, 2):
        try:
            fcntl.fcntl(fd, fcntl.F_GETFD)
        except OSError:
            n = os.open(os.devnull, os.O_RDWR)
            if n != fd:
                os.dup2(n, fd)
                os.close(n)
            else:
                os.set_inheritable(fd, True)


def cmd_stage2(args):
    _ensure_std_fds()
    fd = args.job_fd
    chunks = []
    try:
        while True:
            c = os.read(fd, 65536)
            if not c:
                break
            chunks.append(c)
        os.close(fd)
        job = json.loads(b"".join(chunks))
    except (OSError, ValueError) as e:
        _say("the launcher could not read its job from descriptor %d: %s" % (fd, e))
        raise SystemExit(REFUSED_STATUS)
    ignored = {s for s in FORWARD if signal.getsignal(s) == signal.SIG_IGN}
    fwd = [s for s in FORWARD if s not in ignored]
    ci = job["decl"]["fds"] == "ci-like"
    scope = None if args.no_scope else _scope_dir()
    route = "cgroup" if scope else "pgroup"
    if not args.no_scope and not scope:
        _say("warning: this process is not alone in a new scope below %s: cleanup is by process group" % SLICE)
    a_r = a_w = b_r = b_w = None
    if ci:
        a_r, a_w = os.pipe2(os.O_CLOEXEC)
        b_r, b_w = os.pipe2(os.O_CLOEXEC)
    me = os.getpid()
    signal.pthread_sigmask(signal.SIG_BLOCK, fwd)
    pid = os.fork()
    if pid == 0:
        try:
            _child(job, (a_r, b_w), route, args.no_scope)
        except BaseException:
            import traceback
            traceback.print_exc()
            os._exit(REFUSED_STATUS)
        os._exit(REFUSED_STATUS)

    def forward(sig, _frame):
        if scope:
            for p, _ in _members(scope, pid, me):
                try:
                    os.kill(p, sig)
                except OSError:
                    pass
            return
        try:
            os.killpg(pid, sig)
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                pass

    for s in fwd:
        signal.signal(s, forward)
    signal.pthread_sigmask(signal.SIG_UNBLOCK, fwd)
    if ci:
        os.close(a_r)
        os.close(b_w)
        os.set_blocking(b_r, False)
    status = os.waitstatus_to_exitcode(_wait(pid, b_r))
    code = status if status >= 0 else 128 - status
    _cleanup(scope, pid, me, job["report"], code)
    raise SystemExit(code)


# --------------------------------------------------------------------------------------------------------------------------------
# probe

def cmd_probe(args):
    try:
        norm = normalise(_parse_json(args.decl, "DECL"))
    except Invalid as e:
        for line in e.problems:
            print("qargi: %s: %s" % (CODE_INVALID, line), file=sys.stderr)
        return 2
    if norm is None:
        _usage("probe: the declaration is null: nothing to probe")
    route = "no-scope" if norm["cpu_quota"] is None else "scope"
    d = tempfile.mkdtemp(prefix="suite-env-probe.")
    report = os.path.join(d, "report.json")
    py = [sys.executable] + (["-B"] if sys.flags.dont_write_bytecode else [])
    try:
        try:
            r = subprocess.run(py + ["-I", os.path.abspath(__file__), "run", "--decl", args.decl, "--waive", "", "--report", report, "--",
                                     sys.executable, "-I", "-c", ""], capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=90)
            tail = r.stderr.strip().splitlines()[-5:]
        except subprocess.TimeoutExpired:
            r, tail = None, ["the attempt did not finish in 90 seconds"]
        rep = read_report(report)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    out = {"ok": True, "route": route, "refused": [], "details": [], "stderr": tail}
    if rep is None or (r is None):
        if route == "scope":
            out.update(ok=False, refused=[CODE_NO_USER_MANAGER],
                       details=[{"part": "cpu", "code": CODE_NO_USER_MANAGER,
                                 "found": "the scope could not be made and nothing was reported: " + " | ".join(tail)}])
        else:
            out.update(ok=False, fault=True)
        print(json.dumps(out))
        return 1 if route == "scope" else 3
    if rep.get("refused"):
        out.update(ok=False, refused=rep["refused"])
    out["details"] = rep.get("details", [])
    out["parts"] = rep.get("parts", {})
    print(json.dumps(out))
    return 0 if out["ok"] else 1


# --------------------------------------------------------------------------------------------------------------------------------
# the small verbs for the shell

def _decl_arg(text, what="DECL"):
    return _parse_json(text, what)


def cmd_simple(args):
    c = args.cmd
    try:
        if c == "problems":
            found = problems(_decl_arg(args.decl))
            for line in found:
                print(line)
            return 1 if found else 0
        if c == "normalise":
            print(canonical(normalise(_decl_arg(args.decl))))
        elif c == "hash":
            print(decl_hash(normalise(_decl_arg(args.decl))))
        elif c == "id":
            print(suite_env_id(normalise(_decl_arg(args.decl))))
        elif c == "loosens":
            yes, why = loosens(_decl_arg(args.old, "OLD"), _decl_arg(args.new, "NEW"))
            print("loosens" if yes else "plain")
            for line in why:
                print(line)
            return 0 if yes else 1
        elif c == "approved":
            return cmd_approved(args)
    except Invalid as e:
        for line in e.problems:
            print("qargi: %s: %s" % (CODE_INVALID, line), file=sys.stderr)
        return 2
    return 0


def cmd_approved(args):
    state = args.state
    if args.what == "get":
        entry = approved_get(args.name, state)
        if entry is None:
            return 1
        print(json.dumps(entry, sort_keys=True))
    elif args.what == "set":
        print(json.dumps(approved_set(args.name, _decl_arg(args.decl), args.by, state), sort_keys=True))
    else:
        res = approved_check(args.name, _decl_arg(args.decl), state)
        print(json.dumps(res, sort_keys=True))
        return 0 if res["equal"] else 1
    return 0


def build_parser():
    ap = argparse.ArgumentParser(prog="suite_env.py", description="The launcher of a whole-suite run and its declaration.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run")
    p.add_argument("--decl", required=True)
    p.add_argument("--waive", default="")
    p.add_argument("--report", required=True)
    p.add_argument("--cpu-route", choices=("no-scope",))
    p.add_argument("--cpu-code")
    p = sub.add_parser("stage2")
    p.add_argument("--job-fd", type=int, required=True)
    p.add_argument("--no-scope", action="store_true")
    p = sub.add_parser("probe")
    p.add_argument("--decl", required=True)
    for name in ("problems", "normalise", "hash", "id"):
        sub.add_parser(name).add_argument("decl")
    p = sub.add_parser("loosens")
    p.add_argument("old")
    p.add_argument("new")
    p = sub.add_parser("approved")
    asub = p.add_subparsers(dest="what", required=True)
    for what in ("get", "set", "check"):
        q = asub.add_parser(what)
        q.add_argument("name")
        if what != "get":
            q.add_argument("decl")
        if what == "set":
            q.add_argument("--by", required=True)
        q.add_argument("--state")
    return ap


def main(argv):
    command = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1:]
    args = build_parser().parse_args(argv)
    if args.cmd == "run":
        cmd_run(args, command)
        return REFUSED_STATUS
    if command:
        _usage("%s takes no command after --" % args.cmd)
    if args.cmd == "stage2":
        cmd_stage2(args)
        return REFUSED_STATUS
    if args.cmd == "probe":
        return cmd_probe(args)
    return cmd_simple(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
