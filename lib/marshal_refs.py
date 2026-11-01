#!/usr/bin/env python3
"""The shared refs backend of the marshal: git plumbing for refs/qargi/ on the project's remote.

One commit per update, on refs/qargi/features/<name>; its tree holds the single file record.json. A finished feature moves to
refs/qargi/done/<name> in the same atomic push that deletes features/<name>. The repository's own refs/qargi/* is the cache of
the remote's (fetched with +refs/qargi/*:refs/qargi/* --prune; a plain git fetch never brings it). Nothing here touches the
working tree or the index: only objects and refs under refs/qargi/ are written.

  refresh(repo, remote)        fetch the cache -> (ok, why)
  read(repo)                   the valid records of the cache -> (features, done, ignored); a ref or record that is not
                               valid (bad name, not a commit, other files in the tree, not a regular file, over 64 KiB, not a
                               JSON object, control characters, `feature` other than the ref name) is ignored and listed in
                               `ignored` as (ref, why): data from a remote is never trusted and never crashes a reader
  write(repo, rec, parent, ...) a commit holding rec as record.json -> its oid
  marshal_push(repo, remote, updates, atomic) the ONLY pusher: refs under refs/qargi/features|done only, always with a
                               --force-with-lease=REF:EXPECT (40 zeros: the ref must not exist), GIT_TERMINAL_PROMPT=0 and a
                               timeout -> ("ok" | "rejected" | "unreachable", detail)
  finish(repo, remote, name, rec, features_oid, done_oid) the ONE atomic push that deletes features/<name> and creates
                               done/<name>
  observed(state, project, current) how long each oid has been unchanged on THIS machine's monotonic clock; a lead's wall
                               clock is never compared with another machine's

Environment: QARGI_REMOTE_TIMEOUT seconds for a fetch or push (default 10); QARGI_MARSHAL_MONO the monotonic clock in seconds
(tests inject it).

Command line (marshal.sh and the tests; python3 -I, standard library only):
  push-check REF               exit 0 when marshal_push may push REF, 2 otherwise; runs no git
  member-check VERB            exit 2 (and say so) inside a member run, else 0
  switch-write --state S --project P --remote R --words W   write $S/marshal/P.enabled
  switch-remove --state S --project P                       remove it"""
import argparse, json, os, re, signal, subprocess, sys, time

ZERO = "0" * 40
PUSH_RE = re.compile(r"refs/qargi/(features|done)/[a-z0-9]+(-[a-z0-9]+)*")
NAME_RE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
OID_RE = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
REMOTE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
MAX_RECORD = 64 * 1024
FETCH_SPEC = "+refs/qargi/*:refs/qargi/*"


def ref_ok(ref):
    """True for a ref marshal_push may push: refs/qargi/features/NAME or refs/qargi/done/NAME, nothing else."""
    return isinstance(ref, str) and len(ref) < 200 and PUSH_RE.fullmatch(ref) is not None


def name_ok(name):
    return isinstance(name, str) and 0 < len(name) <= 40 and NAME_RE.fullmatch(name) is not None


def remote_ok(remote):
    return isinstance(remote, str) and REMOTE_RE.fullmatch(remote) is not None


def clean(s):
    return CTRL_RE.sub("", s) if isinstance(s, str) else ""


def timeout_secs():
    try:
        t = float(os.environ.get("QARGI_REMOTE_TIMEOUT", "10"))
    except ValueError:
        return 10.0
    return t if t > 0 else 10.0


def in_member_run(path=None):
    """True when path (default: the current directory) is at or below a directory `qargi local prepare` made (it holds the
    files ability and refs.before): that is a member's run. Same rule as lib/guard.py run_dir."""
    p = os.path.realpath(path or os.getcwd())
    while p and p != os.path.dirname(p):
        if os.path.isfile(os.path.join(p, "ability")) and os.path.isfile(os.path.join(p, "refs.before")):
            return True
        p = os.path.dirname(p)
    return False


# ---- git -----------------------------------------------------------------------------------------------------------

def run_git(repo, args, timeout=None, data=None, extra_env=None):
    """git -C repo ARGS -> (returncode, stdout bytes, stderr text, timed_out). No terminal prompt; a timeout kills the whole
    process group (ssh and the helpers git starts)."""
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env.update(extra_env or {})
    try:
        p = subprocess.Popen(["git", "-C", repo] + list(args), stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, start_new_session=True)
    except OSError as e:
        return 127, b"", "cannot run git: %s" % e, False
    try:
        out, err = p.communicate(data, timeout=timeout)
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
        return 124, b"", "timed out after %g s" % timeout, True
    return p.returncode, out, err.decode("utf-8", "replace"), False


def first_line(s):
    for ln in (s or "").splitlines():
        if ln.strip():
            return clean(ln.strip())[:200]
    return ""


def refresh(repo, remote):
    """Fetch the remote's refs/qargi/ into the repository's own (and drop the ones the remote no longer has).
    -> (True, "") or (False, why): the remote was not checked."""
    if not remote_ok(remote):
        return False, "%r is not a remote name" % remote
    rc, _, err, _ = run_git(repo, ["fetch", '--prune', '--no-tags', '--quiet', '--no-recurse-submodules', remote, FETCH_SPEC], timeout_secs())
    return (True, "") if rc == 0 else (False, first_line(err) or "git fetch failed (status %d)" % rc)


def update_cache(repo, ref, oid):
    """Set (oid) or delete (None) one cache ref after our own successful push."""
    if not ref_ok(ref):
        return
    run_git(repo, ["update-ref", "-d", ref] if oid is None else ["update-ref", ref, oid], 30)


# ---- reading -------------------------------------------------------------------------------------------------------

def walk_ok(v, depth=0):
    """No control character in any string or key, and not nested deeper than 20 levels."""
    if depth > 20:
        return False
    if isinstance(v, str):
        return CTRL_RE.search(v) is None
    if isinstance(v, dict):
        return all(isinstance(k, str) and CTRL_RE.search(k) is None and walk_ok(x, depth + 1) for k, x in v.items())
    if isinstance(v, list):
        return all(walk_ok(x, depth + 1) for x in v)
    return True


def read_one(repo, oid, name):
    """-> (record dict, "") or (None, why)."""
    rc, out, _, _ = run_git(repo, ["ls-tree", "-l", "-z", oid], 30)
    if rc != 0:
        return None, "its tree cannot be read"
    entries = [e for e in out.split(b"\0") if e]
    if len(entries) != 1:
        return None, "its tree must hold record.json and nothing else"
    m = re.fullmatch(rb"(\d+) (\w+) ([0-9a-f]+) +(\d+|-)\t(.*)", entries[0], re.S)
    if not m or m.group(5) != b"record.json":
        return None, "its tree must hold record.json and nothing else"
    mode, typ, blob, size = m.group(1), m.group(2), m.group(3).decode(), m.group(4)
    if typ != b"blob" or mode not in (b"100644", b"100755"):
        return None, "record.json is not a regular file"
    if size == b"-" or int(size) > MAX_RECORD:
        return None, "record.json is over %d KiB" % (MAX_RECORD // 1024)
    rc, data, _, _ = run_git(repo, ["cat-file", "blob", blob], 30)
    if rc != 0 or len(data) > MAX_RECORD:
        return None, "record.json cannot be read"
    try:
        rec = json.loads(data.decode("utf-8"))
    except (ValueError, RecursionError):
        return None, "record.json is not valid JSON"
    if not isinstance(rec, dict):
        return None, "record.json is not a JSON object"
    if rec.get("feature") != name:
        return None, "its feature is not %s" % name
    if not walk_ok(rec):
        return None, "the record has control characters"
    return rec, ""


def read(repo, check=None):
    """The valid records of the cache -> (features {name: (oid, rec)}, done {name: (oid, rec)}, ignored [(ref, why)]).
    check(rec) -> a reason or None adds the caller's own rules (status values, the shape of the lead)."""
    feats, done, ignored = {}, {}, []
    rc, out, _, _ = run_git(repo, ["for-each-ref", "--format=%(objectname) %(objecttype) %(refname)", "refs/qargi/features", "refs/qargi/done"], 30)
    if rc != 0:
        return feats, done, ignored
    for ln in out.decode("utf-8", "replace").splitlines():
        parts = ln.split(" ", 2)
        if len(parts) != 3:
            continue
        oid, typ, ref = parts
        kind, _, name = ref[len("refs/qargi/"):].partition("/")
        if kind not in ("features", "done"):
            continue
        why = None
        if not name_ok(name):
            why = "not a feature name"
        elif typ != "commit":
            why = "not a commit"
        else:
            rec, why = read_one(repo, oid, name)
            if rec is not None and check is not None:
                why = check(rec)
            if rec is not None and not why:
                (feats if kind == "features" else done)[name] = (oid, rec)
        if why:
            ignored.append((clean(ref), why))
    return feats, done, ignored


# ---- writing -------------------------------------------------------------------------------------------------------

def write(repo, rec, parent, message):
    """A commit whose tree holds rec as record.json, child of parent (an oid or None) -> its oid, or raises OSError."""
    data = (json.dumps(rec, indent=1) + "\n").encode()
    rc, out, err, _ = run_git(repo, ["hash-object", "-w", '--stdin'], 30, data)
    if rc != 0:
        raise OSError("git hash-object failed: " + first_line(err))
    blob = out.decode().strip()
    rc, out, err, _ = run_git(repo, ["mktree"], 30, ("100644 blob %s\trecord.json\n" % blob).encode())
    if rc != 0:
        raise OSError("git mktree failed: " + first_line(err))
    tree = out.decode().strip()
    ident = {"GIT_AUTHOR_NAME": "qargi marshal", "GIT_AUTHOR_EMAIL": "marshal@qargi.invalid",
             "GIT_COMMITTER_NAME": "qargi marshal", "GIT_COMMITTER_EMAIL": "marshal@qargi.invalid"}
    rc, out, err, _ = run_git(repo, ["-c", "commit.gpgsign=false", "commit-tree", "-m", message] + (["-p", parent] if parent else []) + [tree], 30, None, ident)
    if rc != 0:
        raise OSError("git commit-tree failed: " + first_line(err))
    return out.decode().strip()


def marshal_push(repo, remote, updates, atomic=False):
    """updates: [(new oid or "" to delete, ref, expected oid)], expected = ZERO when the ref must not exist yet.
    -> ("ok", "") | ("rejected", why): the remote has another value or refused | ("unreachable", why): remote not checked."""
    if not remote_ok(remote) or not updates:
        return "unreachable", "no valid remote"
    leases, specs = [], []
    for new, ref, expect in updates:
        if not ref_ok(ref) or not (new == "" or OID_RE.fullmatch(new or "")) or not (OID_RE.fullmatch(expect or "") or expect == ZERO):
            return "unreachable", "refused to push %r" % clean(str(ref))
        leases.append("--force-with-lease=%s:%s" % (ref, expect))
        specs.append("%s:%s" % (new, ref))
    args = ["push", '--porcelain', '--no-verify'] + (['--atomic'] if atomic else []) + leases + [remote] + specs
    rc, out, err, timed_out = run_git(repo, args, timeout_secs())
    if rc == 0:
        return "ok", ""
    if timed_out:
        return "unreachable", err
    rejected = [ln for ln in out.decode("utf-8", "replace").splitlines() if ln.startswith("!")]
    if rejected:
        return "rejected", first_line(rejected[0].replace("\t", " "))
    return "unreachable", first_line(err) or "git push failed (status %d)" % rc


def finish(repo, remote, name, rec, features_oid, done_oid):
    """Move a feature to done: one commit (child of the last feature commit), pushed with ONE atomic push that creates
    done/<name> and deletes features/<name>, each under its own lease. -> (status, why, new oid)."""
    commit = write(repo, rec, features_oid, "marshal: finish %s" % name)
    ups = [(commit, "refs/qargi/done/" + name, done_oid or ZERO)]
    if features_oid:
        ups.append(("", "refs/qargi/features/" + name, features_oid))
    st, why = marshal_push(repo, remote, ups, atomic=True)
    if st == "ok":
        update_cache(repo, "refs/qargi/features/" + name, None)
        update_cache(repo, "refs/qargi/done/" + name, commit)
    return st, why, commit


# ---- the clock: how long has this oid been unchanged, as THIS machine sees it ----------------------------------------

def mono():
    v = os.environ.get("QARGI_MARSHAL_MONO")
    if v:
        try:
            return float(v)
        except ValueError:
            pass
    return time.monotonic()


def boot_id():
    try:
        with open("/proc/sys/kernel/random/boot_id") as f:
            return f.read().strip() or "unknown"
    except OSError:
        return "unknown"


def observed_path(state, project):
    return os.path.join(state, "features", ".observed-%s.json" % project)


def load_observed(state, project):
    try:
        with open(observed_path(state, project)) as f:
            c = json.load(f)
    except (OSError, ValueError):
        return {}
    return c if isinstance(c, dict) else {}


def save_observed(state, project, cache):
    p = observed_path(state, project)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w") as f:
        json.dump(cache, f)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def observed(state, project, current, persist=True):
    """current {name: oid} of every valid record in the cache -> {name: seconds this oid has been unchanged on this machine's
    monotonic clock}. The cache {name: [oid, first_seen_mono, boot_id]} in $STATE/features/.observed-<project>.json starts a
    timer when an oid is first seen and restarts it when the oid changes, when the boot id changed (the clock restarted) or when
    the clock went backwards: a timer is never made longer than the time really observed. persist=False (a member's read)
    computes without writing."""
    now, boot = mono(), boot_id()
    cache = load_observed(state, project)
    new, ages = {}, {}
    for name, oid in current.items():
        e = cache.get(name)
        first = now
        if isinstance(e, list) and len(e) == 3 and e[0] == oid and e[2] == boot and isinstance(e[1], (int, float)) \
                and not isinstance(e[1], bool) and e[1] <= now:
            first = e[1]
        new[name] = [oid, first, boot]
        ages[name] = now - first
    if persist and new != cache:
        save_observed(state, project, new)
    return ages


def observe_own(state, project, name, oid):
    """Our own push: the new oid is first seen now (None: the feature is finished, forget it)."""
    cache = load_observed(state, project)
    if oid is None:
        cache.pop(name, None)
    else:
        cache[name] = [oid, mono(), boot_id()]
    save_observed(state, project, cache)


# ---- the switch ----------------------------------------------------------------------------------------------------

def switch_path(state, project):
    return os.path.join(state, "marshal", "%s.enabled" % project)


def switch_write(state, project, remote, words):
    p = switch_path(state, project)
    os.makedirs(os.path.dirname(p), mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (p, os.getpid())
    with open(tmp, "w") as f:
        json.dump({"backend": "refs", "remote": remote, "enabled_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "words": words}, f, indent=1)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, p)


def main(argv):
    if len(argv) == 2 and argv[0] == "push-check":
        return 0 if ref_ok(argv[1]) else 2
    p = argparse.ArgumentParser(prog="marshal_refs.py")
    p.add_argument('cmd', choices=["member-check", "switch-write", "switch-remove"])
    p.add_argument('verb', nargs="?", default="")
    p.add_argument('--state', default="")
    p.add_argument('--project', default="")
    p.add_argument('--remote', default="origin")
    p.add_argument('--words', default="")
    a = p.parse_args(argv)
    if a.cmd == "member-check":
        if in_member_run():
            print("qargi: marshal %s is not available in a member run: a member never changes the marshal, enables or disables it or pushes; the lead does" % clean(a.verb), file=sys.stderr)
            return 2
        return 0
    if not a.state or not re.fullmatch(r"[A-Za-z0-9._-]+", a.project):
        print("qargi: %s needs --state and a valid --project" % a.cmd, file=sys.stderr)
        return 2
    if a.cmd == "switch-write":
        if not remote_ok(a.remote) or not a.words.strip():
            print("qargi: switch-write needs a remote name and the words", file=sys.stderr)
            return 2
        switch_write(a.state, a.project, a.remote, a.words)
        return 0
    try:
        os.unlink(switch_path(a.state, a.project))
    except FileNotFoundError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
