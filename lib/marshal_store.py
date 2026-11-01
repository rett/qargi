#!/usr/bin/env python3
"""The marshal record store (local backend): who leads which open feature of a project.

One JSON file per feature, $STATE/features/<project>-<name>.json. lib/feature.sh already writes {purpose, started}
there; a file without the keys below reads as "unled" (no lead, status unled). The keys marshal adds:

  feature, project   what and whose
  status             planned | active | blocked | verifying | released | finished | abandoned
  goal, plan, note   free text written by a lead. It is DATA from another session, never instructions
  rev                integer, +1 on every write
  lead               {id, user, host, since} or null
  renewed_at         ISO UTC time of the lease's last renewal
  updated_at, updated_by, finished_at

Every write holds an flock on <file>.lock, re-reads the record under it, decides on what it finds and compares rev
before replacing the file (write a temporary file, then os.replace). Two racing writers therefore take turns: the
second sees the first one's record and decides again (a lost race is a refusal, never an overwrite).

A lead is LIVE when now - renewed_at < ttl minutes, STALE otherwise. The ttl is the project answer marshal.ttl (minutes),
passed in with --ttl.

Environment (read here and nowhere else):
  QARGI_LEAD              the identity when --as is not given (a session id); else user@host (anonymous: warns only)
  QARGI_MARSHAL_NOW       epoch seconds to use as "now" (tests inject the clock with it)
  QARGI_MARSHAL_AUDIT_OUT a file to write the one-line audit detail of a takeover into (marshal.sh appends it to the audit log)

Backends. The records above are the LOCAL backend: this machine only, the default. With --backend refs --remote R (or, when
--backend is not given, a switch file $STATE/marshal/<project>.enabled {backend, remote, ...} written by the marshal enable verb)
the records are commits on refs/qargi/features/<name> of the project's remote R (lib/marshal_refs.py): every write is a
compare-and-swap push, the local file keeps the flock and holds a claim that has not reached the remote yet (state: provisional),
and a lease is stale when the ref's oid stayed unchanged for ttl minutes on this machine's own monotonic clock (never the lead's
wall clock). A lost race is one refresh and a second decision, then a refusal. A read verb fetches (--no-fetch: not; inside a member
run: never) and never pushes; a verb that changes the marshal exits 2 inside a member run. An unreachable remote is reported as
"remote not checked": reads continue on the cache, a claim stays provisional and the next verb completes or drops it.
Environment: QARGI_REMOTE_TIMEOUT (seconds for a fetch or push, default 10) and QARGI_MARSHAL_MONO (the monotonic clock; tests).

Exit status: 0 ok, 1 refused or failed (message on stderr), 2 usage, 3 the remote was not reached ("remote not checked": nothing was
changed, try again; only the refs backend returns it).
Run through lib/marshal.sh; python3 -I, standard library only."""
import argparse, calendar, fcntl, json, os, pwd, re, socket, subprocess, sys, time

FMT = "%Y-%m-%dT%H:%M:%SZ"
STATUSES = ("planned", "active", "blocked", "verifying", "released", "finished", "abandoned")
SETTABLE = ("planned", "active", "blocked", "verifying")
CAP = 2000
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ID_RE = re.compile(r"^[A-Za-z0-9._@:+-]{1,128}$")
CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class Refuse(Exception):
    """A refusal: message to stderr, exit 1."""


class Unreachable(Refuse):
    """The change was not made because the remote was not reached: message to stderr, exit 3. Not a refusal of the lead: a caller that
    renews a lease for a long step (marshal_hold_start) tries again, one that gets exit 1 knows the lease is lost."""


def now():
    v = os.environ.get("QARGI_MARSHAL_NOW")
    if v:
        try:
            return int(float(v))
        except ValueError:
            raise Refuse("QARGI_MARSHAL_NOW is not a number of seconds")
    return int(time.time())


def iso(t):
    return time.strftime(FMT, time.gmtime(t))


def parse_iso(s):
    try:
        return calendar.timegm(time.strptime(s, FMT))
    except (TypeError, ValueError):
        return None


def clean(s):
    return CTRL_RE.sub("", s) if isinstance(s, str) else ""


def capped(s):
    return clean(s)[:CAP]


class Ctx:
    def __init__(self, a, be=None):
        self.state, self.project, self.repo = a.state, a.project, a.repo
        self.be = be or LocalBackend()
        self.fetch_ok = not getattr(a, "no_fetch", False) and not getattr(self.be, "member", False)
        self.ttl = a.ttl if a.ttl and a.ttl > 0 else 15
        user = pwd.getpwuid(os.getuid()).pw_name
        host = socket.gethostname()
        given = a.as_id or os.environ.get("QARGI_LEAD") or ""
        self.anon = not given
        self.id = given or "%s@%s" % (user, host)
        if not ID_RE.match(self.id):
            raise Refuse("the lead identity %r is not valid (letters, digits and . _ @ : + - only, at most 128)" % self.id)
        self.user, self.host = user, host
        self.t = now()

    def path(self, name):
        return os.path.join(self.state, "features", "%s-%s.json" % (self.project, name))

    def warn_anon(self):
        if self.anon:
            print("qargi: warning: anonymous identity %s (every session on this host is the same lead): set QARGI_LEAD or pass --as" % self.id, file=sys.stderr)


# ---- records -------------------------------------------------------------------------------------------------------

def read_rec(path):
    try:
        with open(path) as f:
            r = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise Refuse("the record %s cannot be read (%s); fix or remove it" % (path, e))
    if not isinstance(r, dict):
        raise Refuse("the record %s is not a JSON object" % path)
    return r


def lead_of(rec):
    ld = rec.get("lead") if rec else None
    return ld if isinstance(ld, dict) and ld.get("id") else None


def lease(ctx, rec):
    """-> (state, minutes since renewal): state live | stale | none."""
    ld = lead_of(rec)
    if not ld:
        return "none", None
    age = ctx.be.age(ctx, rec)
    if age is None:
        return ctx.be.no_age, None
    return ("live" if age < ctx.ttl * 60 else "stale"), max(age, 0) // 60


def new_lead(ctx, since=None):
    return {"id": ctx.id, "user": ctx.user, "host": ctx.host, "since": since or iso(ctx.t)}


def update(ctx, name, fn, create=False):
    """Locked compare-and-swap update by the backend of the project (create: fn may create the record of a feature that has none,
    which a backend that cannot reach its store may then keep provisionally). Returns the result of fn."""
    return ctx.be.update(ctx, name, fn, create)


def fresh(ctx, name, rec):
    """A record with every key, keeping what an older file has (purpose, started)."""
    r = dict(rec or {})
    r.setdefault("purpose", "")
    r.setdefault("started", iso(ctx.t))
    for k in ("goal", "plan", "note"):
        if not isinstance(r.get(k), str):
            r[k] = ""
    r.setdefault("status", "unled")
    r.setdefault("lead", None)
    r.setdefault("renewed_at", None)
    r.setdefault("finished_at", None)
    r.setdefault("updated_by", "")
    return r


def led_by_msg(ctx, name, rec, tail=""):
    st, mins = lease(ctx, rec)
    ld = lead_of(rec)
    base = "feature %s is led by %s (%s %s min ago, ttl %d)" % (name, clean(ld["id"]), ctx.be.renewed_word, "?" if mins is None else mins, ctx.ttl)
    if st == "stale":
        base += "; the lease is stale: use qargi marshal takeover %s --approved WORDS" % name
    return base + tail


def check_name(name):
    if not NAME_RE.match(name or "") or len(name) > 40:
        raise Refuse("'%s' is not a feature name: kebab-case, lower-case letters, digits and single '-' (at most 40)" % name)


# ---- backends ------------------------------------------------------------------------------------------------------

class LocalBackend:
    """One JSON file per feature in $STATE/features, this machine only (the default). The lease is the wall clock: renewed_at."""
    refs = False
    ghost_fix = True              # a record whose branch is gone is abandoned on a read
    no_age = "stale"              # the lease of a record without a readable renewed_at
    renewed_word = "renewed"

    def age(self, ctx, rec):
        """Seconds since the lease was renewed, or None."""
        r = parse_iso(rec.get("renewed_at"))
        return None if r is None else ctx.t - r

    def get(self, ctx, name):
        return read_rec(ctx.path(name))

    def names(self, ctx, history=False):
        names = set(open_features(ctx))
        prefix = ctx.project + "-"
        try:
            for f in os.listdir(os.path.join(ctx.state, "features")):
                if f.startswith(prefix) and f.endswith(".json"):
                    n = f[len(prefix):-5]
                    if NAME_RE.match(n):
                        rec = read_rec(os.path.join(ctx.state, "features", f))
                        if n in names or (rec and (history or rec.get("status") != "finished")):
                            names.add(n)
        except OSError:
            pass
        return sorted(names)

    def update(self, ctx, name, fn, create=False):
        """Locked compare-and-swap update. fn(rec or None) -> (new rec or None, result); it may raise Refuse.
        Returns the result. rev of the new record is the old rev + 1."""
        path = ctx.path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            rec = read_rec(path)
            rev0 = rec.get("rev", 0) if rec else 0
            if not isinstance(rev0, int):
                rev0 = 0
            new, res = fn(rec)
            if new is None:
                return res
            if (read_rec(path) or {}).get("rev", 0) != (rec or {}).get("rev", 0):
                raise Refuse("feature %s changed while it was being updated; try again" % name)
            new["rev"] = rev0 + 1
            new["updated_at"] = iso(ctx.t)
            new["feature"], new["project"] = name, ctx.project
            write_local(path, new)
            return res


def write_local(path, rec):
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


NOTE_KEYS = ("state", "done_seen")           # keys of the local note of a claim that was not pushed; never part of a pushed record
REFS_MOD = None


def refs_mod():
    """lib/marshal_refs.py, loaded by path (python -I does not put this directory on sys.path)."""
    global REFS_MOD
    if REFS_MOD is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("marshal_refs", os.path.join(os.path.dirname(os.path.realpath(__file__)), "marshal_refs.py"))
        REFS_MOD = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(REFS_MOD)
    return REFS_MOD


def sane(rec):
    """The store's own rules for a record read from the remote -> a reason to ignore it, or None."""
    if "status" in rec and rec["status"] not in STATUSES:            # a null or a number is as unknown as a word
        return "its status %r is unknown" % clean(str(rec["status"]))[:40]
    for k in ("purpose", "renewed_at", "finished_at"):
        if rec.get(k) is not None and not isinstance(rec[k], str):
            return "its %s is not text" % k
    ld = rec.get("lead")
    if ld is not None and not (isinstance(ld, dict) and isinstance(ld.get("id"), str) and ID_RE.fullmatch(ld["id"])):
        return "its lead is not valid"
    rev = rec.get("rev")
    if rev is not None and (not isinstance(rev, int) or isinstance(rev, bool) or rev < 0):
        return "its rev is not a number"
    return None


def sanitize(v):
    """A record to be written: no control character in any string (a reader would ignore the whole record)."""
    if isinstance(v, str):
        return clean(v) if CTRL_RE.search(v) else v
    if isinstance(v, dict):
        return {clean(k): sanitize(x) for k, x in v.items()}
    if isinstance(v, list):
        return [sanitize(x) for x in v]
    return v


def soft_rec(path):
    try:
        return read_rec(path)
    except Refuse:
        return None


class Snap:
    def __init__(self, feats, done, bad, why, bad_done=frozenset()):
        self.feats, self.done, self.bad, self.why, self.bad_done = feats, done, bad, why, bad_done


class RefsBackend:
    """The records are commits on refs/qargi/features/NAME of the project's remote (lib/marshal_refs.py); the repository's own
    refs/qargi/ is their cache. The local file $STATE/features/<project>-<name>.json keeps the flock and holds a claim that has
    not reached the remote yet (state: provisional). The lease is the time an oid stayed unchanged on THIS machine's monotonic
    clock, never a wall-clock comparison. A read verb fetches (unless --no-fetch or inside a member run) and never pushes."""
    refs = True
    ghost_fix = False
    no_age = "live"
    renewed_word = "last change seen"

    def __init__(self, remote):
        self.R = refs_mod()
        self.remote = remote
        self.member = self.R.in_member_run()
        self.snap = None
        self.warned = set()

    # -- the cache
    def repo_lock(self, ctx):
        os.makedirs(os.path.join(ctx.state, "features"), exist_ok=True)
        lk = open(os.path.join(ctx.state, "features", ".refs-%s.lock" % ctx.project), "a")
        fcntl.flock(lk, fcntl.LOCK_EX)
        return lk

    def load(self, ctx, fetch):
        """Fetch (when asked) and read the cache -> self.snap; snap.why is None when the remote was checked."""
        R = self.R
        if not ctx.repo:
            raise Refuse("the shared refs backend needs the project's repository (repo.path)")
        why = None
        lk = self.repo_lock(ctx)
        try:
            if fetch:
                ok, w = R.refresh(ctx.repo, self.remote)
                why = None if ok else w
            feats, done, ignored = R.read(ctx.repo, sane)
            ages = R.observed(ctx.state, ctx.project, {n: o for n, (o, _) in feats.items()}, persist=not self.member)
        finally:
            lk.close()
        for ref, w in ignored:
            if (ref, w) not in self.warned:
                self.warned.add((ref, w))
                print("qargi: warning: ignoring %s on the remote: %s" % (ref, w), file=sys.stderr)
        bad = {r.rsplit("/", 1)[1] for r, _ in ignored if r.startswith("refs/qargi/features/") and R.name_ok(r.rsplit("/", 1)[1])}
        bad_done = {r.rsplit("/", 1)[1] for r, _ in ignored if r.startswith("refs/qargi/done/") and R.name_ok(r.rsplit("/", 1)[1])}
        self.snap = Snap({n: dict(rec, _oid=o, _age=ages.get(n, 0)) for n, (o, rec) in feats.items()},
                         {n: dict(rec, _oid=o) for n, (o, rec) in done.items()}, bad, why, bad_done)
        return why

    def snapshot(self, ctx):
        if self.snap is None:
            why = self.load(ctx, ctx.fetch_ok)
            if why is not None:
                print("qargi: remote not checked (%s): showing what this machine fetched last" % why, file=sys.stderr)
        return self.snap

    # -- reading
    def age(self, ctx, rec):
        return rec.get("_age")

    def provisional(self, ctx, name):
        rec = soft_rec(ctx.path(name))
        return rec if rec and rec.get("state") == "provisional" else None

    def get(self, ctx, name):
        snap = self.snapshot(ctx)
        return snap.feats.get(name) or self.provisional(ctx, name) or snap.done.get(name)

    def names(self, ctx, history=False):
        snap = self.snapshot(ctx)
        names = set(open_features(ctx))
        for n, rec in snap.feats.items():
            if history or rec.get("status") != "finished":
                names.add(n)
        if history:
            names.update(snap.done)
        prefix = ctx.project + "-"
        try:
            for f in os.listdir(os.path.join(ctx.state, "features")):
                if f.startswith(prefix) and f.endswith(".json") and NAME_RE.match(f[len(prefix):-5]) and self.provisional(ctx, f[len(prefix):-5]):
                    names.add(f[len(prefix):-5])
        except OSError:
            pass
        return sorted(names)

    # -- writing
    def stamp(self, ctx, name, new, base):
        """The record to write: no private key, rev + 1, no control character, not over the size a reader accepts."""
        new = {k: v for k, v in new.items() if not k.startswith("_") and k not in NOTE_KEYS}
        rev0 = (base or {}).get("rev", 0)
        new["rev"] = (rev0 if isinstance(rev0, int) and not isinstance(rev0, bool) else 0) + 1
        new["updated_at"] = iso(ctx.t)
        new["feature"], new["project"] = name, ctx.project
        new = sanitize(new)
        if len(json.dumps(new, indent=1)) > 60000:
            raise Refuse("the record of %s would be over 64 KiB, which no reader accepts: shorten the goal, plan or note" % name)
        return new

    def done_oid(self, name):
        """The oid of refs/qargi/done/<name> in the cache just read, or None."""
        return (self.snap.done.get(name) or {}).get("_oid")

    def mirror(self, ctx, name, rec, state=None):
        """Write the local file. A provisional note also keeps the done/<name> oid the cache showed when the claim was made: a
        claim is dropped on settling only when another machine finished the feature since."""
        rec = {k: v for k, v in rec.items() if not k.startswith("_") and k not in NOTE_KEYS}
        if state:
            rec["state"] = state
            if state == "provisional":
                rec["done_seen"] = self.done_oid(name)
        write_local(ctx.path(name), rec)

    def push_one(self, ctx, name, new, remote_oid):
        """Commit new on top of the remote's commit and push it with a lease on that commit (create-only when there is none)
        -> (status, why)."""
        R = self.R
        ref = "refs/qargi/features/" + name
        try:
            commit = R.write(ctx.repo, new, remote_oid, "marshal: %s rev %s" % (name, new.get("rev")))
        except OSError as e:
            raise Refuse("cannot write the record of %s: %s" % (name, e))
        st, why = R.marshal_push(ctx.repo, self.remote, [(commit, ref, remote_oid or R.ZERO)])
        if st == "ok":
            lk = self.repo_lock(ctx)
            try:
                R.update_cache(ctx.repo, ref, commit)
                R.observe_own(ctx.state, ctx.project, name, commit)
            finally:
                lk.close()
        return st, why

    def update(self, ctx, name, fn, create=False):
        """Locked on this machine; the remote decides by compare-and-swap on the oid of the ref. A lost lease is one refresh and
        a second decision, then a refusal. Returns the result of fn."""
        path = ctx.path(name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            return self.update_locked(ctx, name, fn, create, path)

    def update_locked(self, ctx, name, fn, create, path):
        R = self.R
        retried, last = False, ""
        for _ in range(5):
            why = self.load(ctx, True)
            snap = self.snap
            if name in snap.bad:
                raise Refuse("refs/qargi/features/%s exists on the remote but holds no valid record (see the warning above): ask whoever owns the remote to remove it" % name)
            remote = snap.feats.get(name)
            prov = self.provisional(ctx, name)
            if prov is not None and why is None:
                # settle a claim that was not pushed: complete it when the remote still has no such feature, adopt the remote's record when
                # it is ours already (the answer of the push was lost), drop it when someone else won meanwhile or has finished the
                # feature meanwhile (pushing it would bring a finished feature back to life next to its done/ ref)
                if remote is None and self.done_oid(name) not in (None, prov.get("done_seen")):
                    os.unlink(path)
                    print("qargi: the provisional claim of %s was dropped, not pushed: the feature was finished on the remote meanwhile (refs/qargi/done/%s exists)" % (name, name), file=sys.stderr)
                    prov = None
                elif remote is None:
                    st, last = self.push_one(ctx, name, {k: v for k, v in prov.items() if k not in NOTE_KEYS}, None)
                    if st == "ok":
                        self.mirror(ctx, name, prov)
                    if st in ("ok", "rejected"):
                        continue                                  # read the remote again: it has the feature now, or someone else does
                    why = last
                else:
                    ld = lead_of(remote)
                    if ld and lead_of(prov) and ld["id"] == lead_of(prov)["id"]:
                        self.mirror(ctx, name, remote)
                    else:
                        os.unlink(path)
                    prov = None
            rec = remote if remote is not None else prov
            if why is not None:                                   # the remote was not checked
                new, res = fn(rec)
                if new is None:
                    return res
                if not (create and remote is None):
                    raise Unreachable("remote not checked (%s): feature %s was not changed; try again when the remote is reachable" % (why, name))
                self.mirror(ctx, name, self.stamp(ctx, name, new, rec), "provisional")
                print("qargi: remote not checked (%s): the claim of %s is provisional here; the next marshal verb on it completes or drops it" % (why, name), file=sys.stderr)
                return res
            new, res = fn(rec)
            if new is None:
                return res
            new = self.stamp(ctx, name, new, rec)
            remote_oid = remote["_oid"] if remote else None
            finishing = new.get("status") == "finished"
            wrote_prov = False
            if finishing and name in snap.bad_done:
                raise Refuse("refs/qargi/done/%s exists on the remote but holds no valid record (see the warning above): ask whoever owns the remote to remove it, then finish again" % name)
            if finishing:
                try:
                    st, last, _ = R.finish(ctx.repo, self.remote, name, new, remote_oid, (snap.done.get(name) or {}).get("_oid"))
                except OSError as e:
                    raise Refuse("cannot write the record of %s: %s" % (name, e))
                if st == "ok":
                    lk = self.repo_lock(ctx)
                    try:
                        R.observe_own(ctx.state, ctx.project, name, None)
                    finally:
                        lk.close()
            else:
                if remote is None and create:
                    self.mirror(ctx, name, new, "provisional")      # first the local note, then the create-only push
                    wrote_prov = True
                st, last = self.push_one(ctx, name, new, remote_oid)
            if st == "ok":
                if finishing:
                    try:
                        os.unlink(path)
                    except FileNotFoundError:
                        pass
                else:
                    self.mirror(ctx, name, new)
                return res
            if st == "unreachable":
                if wrote_prov:
                    print("qargi: remote not checked (%s): the claim of %s is provisional here; the next marshal verb on it completes or drops it" % (last, name), file=sys.stderr)
                    return res
                raise Unreachable("remote not checked (%s): feature %s was not changed; try again when the remote is reachable" % (last, name))
            if retried:                                           # rejected twice
                if wrote_prov:
                    os.unlink(path)
                raise Refuse("feature %s changed while it was being updated, or the remote refused the push (%s); try again" % (name, last))
            retried = True
        raise Refuse("feature %s could not be updated (%s); try again" % (name, last or "the remote kept changing"))


# ---- git -----------------------------------------------------------------------------------------------------------

def git(ctx, *args):
    if not ctx.repo:
        return None
    r = subprocess.run(["git", "-C", ctx.repo] + list(args), capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def branch_exists(ctx, name):
    return git(ctx, "rev-parse", "-q", '--verify', "refs/heads/feature/" + name) is not None


def unled(ctx, name, rec):
    """The record, or for a feature that has a branch but no record yet (started before the marshal, or by hand) an empty unled one."""
    if rec is None and branch_exists(ctx, name):
        return {"status": "unled"}
    return rec


def open_features(ctx):
    out = git(ctx, "for-each-ref", "--format=%(refname:short)", "refs/heads/feature/*") or ""
    return sorted(b[len("feature/"):] for b in out.split() if b.startswith("feature/"))


def feature_files(ctx, name):
    if git(ctx, "rev-parse", "-q", '--verify', "refs/heads/develop") is None:
        return set()
    return set((git(ctx, "diff", '--name-only', "develop...feature/" + name) or "").split("\n")) - {""}


def overlaps(ctx, name, files_cache):
    """{other feature: [files both change]} among the open features."""
    if name not in files_cache:
        files_cache[name] = feature_files(ctx, name)
    res = {}
    for o in open_features(ctx):
        if o == name:
            continue
        if o not in files_cache:
            files_cache[o] = feature_files(ctx, o)
        both = sorted(files_cache[name] & files_cache[o])
        if both:
            res[o] = both
    return res


def tasks_of(ctx, name):
    out, p = [], os.path.join(ctx.state, "local-runs.jsonl")
    try:
        lines = open(p).read().splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(r, dict) or r.get("base") != "feature/" + name:
            continue
        run = r.get("run") or ""
        out.append({"run": clean(run), "slug": clean(r.get("slug") or ""), "role": clean(r.get("ability") or r.get("role") or ""),
                    "started": clean(r.get("started") or ""), "verified": bool(run) and os.path.exists(os.path.join(run, "verified"))})
    return out


def unmerged_agents(ctx, name):
    out = git(ctx, "for-each-ref", "--format=%(refname:short)", "refs/heads/agent/*") or ""
    res = []
    for b in out.split():
        if git(ctx, "merge-base", '--is-ancestor', "refs/heads/" + b, "refs/heads/feature/" + name) is None:
            res.append(b)
    return res


def worktrees_of(ctx, name):
    out, res, cur = git(ctx, "worktree", "list", '--porcelain') or "", [], None
    for ln in out.splitlines() + [""]:
        if ln.startswith("worktree "):
            cur = {"path": ln[9:], "branch": ""}
        elif ln.startswith("branch ") and cur is not None:
            cur["branch"] = ln[7:].replace("refs/heads/", "", 1)
        elif ln == "" and cur is not None:
            b = cur["branch"]
            if b == "feature/" + name or b.startswith("agent/"):
                res.append({"path": clean(cur["path"]), "branch": clean(b)})
            cur = None
    return res


# ---- describing a feature ------------------------------------------------------------------------------------------

def ghost_fix(ctx, name, rec):
    """A record whose branch is gone and that never finished is abandoned: record the transition. -> the record.
    Only the local backend writes it (a read never pushes, and another machine may simply not have the branch)."""
    if rec is None or not ctx.be.ghost_fix or branch_exists(ctx, name) or rec.get("status") in ("finished", "abandoned"):
        return rec

    def fn(r):
        if r is None or r.get("status") in ("finished", "abandoned"):
            return None, r
        r = fresh(ctx, name, r)
        r["status"], r["lead"] = "abandoned", None
        r["note"] = r["note"] or "branch feature/%s is gone" % name
        return r, r
    return update(ctx, name, fn)


def describe(ctx, name, rec, files_cache, derived=True):
    rec = fresh(ctx, name, rec)
    st, mins = lease(ctx, rec)
    ld = lead_of(rec)
    ghost = rec["status"] == "abandoned" and not branch_exists(ctx, name)
    d = {"feature": name, "project": ctx.project, "status": rec["status"],
         "lead": ({"id": clean(ld["id"]), "user": clean(ld.get("user", "")), "host": clean(ld.get("host", "")), "since": clean(ld.get("since", ""))} if ld else None),
         "lease": st, "minutes_since_renewal": mins, "ttl_minutes": ctx.ttl, "renewed_at": rec["renewed_at"],
         "rev": rec.get("rev", 0), "branch": branch_exists(ctx, name), "ghost": ghost, "updated_by": clean(rec.get("updated_by") or ""),
         "purpose": capped(rec["purpose"]), "goal": capped(rec["goal"]), "plan": capped(rec["plan"]), "note": capped(rec["note"]),
         "finished_at": rec["finished_at"]}
    if ctx.be.refs:
        d["provisional"] = rec.get("state") == "provisional"
    if derived:
        d["tasks"], d["agent_branches"] = tasks_of(ctx, name), (unmerged_agents(ctx, name) if d["branch"] else [])
        d["worktrees"], d["overlap"] = worktrees_of(ctx, name), (overlaps(ctx, name, files_cache) if d["branch"] else {})
    return d


def lead_word(d, brief=False):
    if not d["lead"]:
        return "none"
    return ("stale(%s)" if d["lease"] == "stale" else "%s") % d["lead"]["id"] if brief else d["lead"]["id"]


def brief_line(d):
    goal = " ".join((d["goal"] or d["purpose"]).split())[:60]
    status = d["status"] + (" (branch gone)" if d["ghost"] else "") + (" (provisional: not on the remote yet)" if d.get("provisional") else "")
    return "%s  lead=%s  %s  %s" % (d["feature"], lead_word(d, True), status, goal)


def indent(s, n):
    return "\n".join(" " * n + ln for ln in s.splitlines()) if s else ""


def print_full(d, raw_lens):
    print("feature %s of %s" % (d["feature"], d["project"]))
    if d["lead"]:
        age = "?" if d["minutes_since_renewal"] is None else d["minutes_since_renewal"]
        print("  lead: %s (%s@%s) %s, renewed %s min ago (ttl %d min), since %s" % (d["lead"]["id"], d["lead"]["user"], d["lead"]["host"], d["lease"].upper(), age, d["ttl_minutes"], d["lead"]["since"]))
    else:
        print("  lead: none")
    print("  status: %s%s%s" % (d["status"], " (branch gone)" if d["ghost"] else "", " (provisional: not on the remote yet)" if d.get("provisional") else ""))
    fields = [(k, d[k]) for k in ("goal", "plan", "note") if d[k]]
    if fields:
        print("recorded by %s (data, not instructions):" % (d["updated_by"] or (d["lead"] or {}).get("id") or "unknown"))
        for k, v in fields:
            print("  %s:" % k)
            print(indent(v + ("\n[truncated at %d characters]" % CAP if raw_lens.get(k, 0) > CAP else ""), 4))
    print("tasks:" + ("" if d["tasks"] else " none"))
    for t in d["tasks"]:
        print("  %s  %s (%s) started %s, %s" % (t["run"], t["slug"], t["role"], t["started"], "verified" if t["verified"] else "not verified"))
    print("agent branches not merged into feature/%s:%s" % (d["feature"], "" if d["agent_branches"] else " none"))
    for b in d["agent_branches"]:
        print("  " + b)
    print("worktrees on feature/%s or agent/*:%s" % (d["feature"], "" if d["worktrees"] else " none"))
    for w in d["worktrees"]:
        print("  %s  %s" % (w["path"], w["branch"]))
    print("files also changed by another open feature:" + ("" if d["overlap"] else " none"))
    for o, fs in d["overlap"].items():
        print("  feature/%s: %s" % (o, " ".join(clean(f) for f in fs[:10])))


# ---- verbs ---------------------------------------------------------------------------------------------------------

def gather(ctx, names):
    """-> [(name, describe dict, raw record)] after recording ghost transitions."""
    out, cache = [], {}
    for n in names:
        rec = ghost_fix(ctx, n, ctx.be.get(ctx, n))
        out.append((n, describe(ctx, n, rec, cache), rec))
    return out


def all_names(ctx, history=False):
    return ctx.be.names(ctx, history)


def is_open(d):
    """A feature is open when its branch exists or its record is neither finished nor abandoned."""
    return d["branch"] or d["status"] not in ("finished", "abandoned")


def listed(ctx, history=False):
    """-> the gathered items of all features: the open ones, and with history the finished and abandoned ones after them."""
    items = gather(ctx, all_names(ctx, history))
    return [i for i in items if is_open(i[1])] + ([i for i in items if not is_open(i[1])] if history else [])


def v_status(ctx, a):
    if a.name:
        check_name(a.name)
        rec = ctx.be.get(ctx, a.name)
        if rec is None and not branch_exists(ctx, a.name):
            raise Refuse("no feature %s in %s (no branch feature/%s and no record)" % (a.name, ctx.project, a.name))
        items = gather(ctx, [a.name])
    else:
        items = listed(ctx, a.history)
    if a.json:
        objs = [d for _, d, _ in items]
        print(json.dumps(objs[0] if a.name else {"project": ctx.project, "features": objs}, indent=1))
        return
    if not items:
        print("no open features (qargi feature start NAME)")
        return
    for i, (n, d, rec) in enumerate(items):
        if a.brief:
            print(brief_line(d))
            continue
        if i:
            print()
        r = fresh(ctx, n, rec)
        print_full(d, {k: len(clean(r[k])) for k in ("goal", "plan", "note")})


def v_claim(ctx, a):
    check_name(a.name)
    ctx.warn_anon()
    if not branch_exists(ctx, a.name):
        raise Refuse("no branch feature/%s: start it first (qargi feature start %s)" % (a.name, a.name))

    def fn(rec):
        ld = lead_of(rec)
        if ld and ld["id"] != ctx.id:
            raise Refuse(led_by_msg(ctx, a.name, rec))
        r = fresh(ctx, a.name, rec)
        again = bool(ld)
        if r["status"] in ("finished", "abandoned"):
            r["plan"] = r["note"] = ""
            r["goal"] = ""
        if not again:
            r["lead"] = new_lead(ctx)
        r["status"] = "active" if r["status"] in ("finished", "abandoned", "released", "unled") else r["status"]
        r["finished_at"] = None
        r["renewed_at"], r["updated_by"] = iso(ctx.t), ctx.id
        if a.goal is not None:
            r["goal"] = a.goal
        return r, again
    again = update(ctx, a.name, fn, create=True)
    print("%s %s (lead %s, ttl %d min)" % ("renewed" if again else "claimed", a.name, ctx.id, ctx.ttl))


def v_start(ctx, a):
    """Internal (marshal_start): create or refresh the record when a feature starts; lead = this identity."""
    check_name(a.name)
    ctx.warn_anon()

    def fn(rec):
        ld = lead_of(rec)
        st, _ = lease(ctx, rec)
        if ld and ld["id"] != ctx.id and rec.get("status") not in ("finished", "abandoned", "released"):
            raise Refuse(led_by_msg(ctx, a.name, rec))
        r = fresh(ctx, a.name, rec)
        if rec is None or rec.get("status") in ("finished", "abandoned", "released", None):
            r["plan"] = r["note"] = ""
            r["goal"] = ""
        if a.purpose or not r["purpose"]:
            r["purpose"] = a.purpose or r["purpose"]
        if not r["goal"]:
            r["goal"] = r["purpose"]
        if not (ld and ld["id"] == ctx.id):
            r["lead"] = new_lead(ctx)
        r["status"], r["finished_at"] = "active", None
        r["renewed_at"], r["updated_by"] = iso(ctx.t), ctx.id
        return r, st
    update(ctx, a.name, fn, create=True)
    print("marshal: %s leads %s" % (ctx.id, a.name))


def mine(ctx, name, rec, what):
    ld = lead_of(rec)
    if rec is None:
        raise Refuse("no record for feature %s (claim it: qargi marshal claim %s)" % (name, name))
    if not ld or ld["id"] != ctx.id:
        who = "led by %s" % clean(ld["id"]) if ld else "without a lead"
        raise Refuse("you (%s) are not the lead of %s, which is %s; %s" % (ctx.id, name, who, what))


def v_set(ctx, a):
    check_name(a.name)
    if a.goal is None and a.plan is None and a.note is None and a.status is None:
        raise SystemExit(usage_exit("set needs --goal, --plan, --note or --status"))
    if a.status is not None and a.status not in SETTABLE:
        raise SystemExit(usage_exit("--status is one of %s" % ", ".join(SETTABLE)))

    def fn(rec):
        mine(ctx, a.name, rec, "claim or take it first")
        r = fresh(ctx, a.name, rec)
        for k in ("goal", "plan", "note", "status"):
            if getattr(a, k) is not None:
                r[k] = getattr(a, k)
        r["renewed_at"], r["updated_by"] = iso(ctx.t), ctx.id
        return r, None
    update(ctx, a.name, fn)
    print("updated %s (lease renewed)" % a.name)


def v_renew(ctx, a):
    check_name(a.name)

    def fn(rec):
        mine(ctx, a.name, rec, "claim or take it first")
        r = fresh(ctx, a.name, rec)
        r["renewed_at"] = iso(ctx.t)
        return r, None
    update(ctx, a.name, fn)
    print("renewed %s (lead %s, ttl %d min)" % (a.name, ctx.id, ctx.ttl))


def v_release(ctx, a):
    check_name(a.name)
    if not (a.note or "").strip():
        raise Refuse("release needs --note TEXT: what the next lead must know")

    def fn(rec):
        mine(ctx, a.name, rec, "only the lead can release it")
        r = fresh(ctx, a.name, rec)
        r["lead"], r["status"], r["note"] = None, "released", a.note
        r["updated_by"] = ctx.id
        return r, None
    update(ctx, a.name, fn)
    print("released %s; the next lead takes it with: qargi marshal take %s" % (a.name, a.name))


def v_take(ctx, a):
    check_name(a.name)
    ctx.warn_anon()

    def fn(rec):
        rec = unled(ctx, a.name, rec)
        if rec is None:
            raise Refuse("no record for feature %s (claim it: qargi marshal claim %s)" % (a.name, a.name))
        ld = lead_of(rec)
        if ld and ld["id"] == ctx.id:
            r = fresh(ctx, a.name, rec)
            r["renewed_at"] = iso(ctx.t)
            return r, True
        if ld:
            raise Refuse(led_by_msg(ctx, a.name, rec, "; take needs a released feature"))
        if rec.get("status") in ("finished", "abandoned"):
            raise Refuse("feature %s is %s" % (a.name, rec["status"]))
        r = fresh(ctx, a.name, rec)
        r["lead"], r["status"] = new_lead(ctx), "active"
        r["renewed_at"], r["updated_by"] = iso(ctx.t), ctx.id
        return r, False
    again = update(ctx, a.name, fn)
    print("%s %s (lead %s, ttl %d min)" % ("renewed" if again else "took", a.name, ctx.id, ctx.ttl))


def v_takeover(ctx, a):
    check_name(a.name)
    ctx.warn_anon()
    words = " ".join((a.approved or "").split())
    if not words:
        raise Refuse("takeover needs --approved WORDS: your go-ahead, in your words, for exactly this takeover")

    def fn(rec):
        rec = unled(ctx, a.name, rec)
        if rec is None:
            raise Refuse("no record for feature %s (claim it: qargi marshal claim %s)" % (a.name, a.name))
        st, mins = lease(ctx, rec)
        if st == "live":
            age = ctx.be.age(ctx, rec)
            if age is None:       # a provisional claim has not been seen on the remote: no age, and nobody else leads it there
                raise Refuse("feature %s is a provisional claim of yours that has not reached the remote yet; there is nothing to take over: "
                             "run a marshal verb on it when the remote is reachable" % a.name)
            left = max(1, -(-(ctx.ttl * 60 - age) // 60))
            raise Refuse("feature %s is led by %s and live for another %d min (ttl %d); wait, or ask the lead to release it" % (a.name, clean(lead_of(rec)["id"]), left, ctx.ttl))
        if rec.get("status") in ("finished", "abandoned"):
            raise Refuse("feature %s is %s" % (a.name, rec["status"]))
        old = clean(lead_of(rec)["id"]) if lead_of(rec) else "none"
        r = fresh(ctx, a.name, rec)
        r["lead"], r["status"] = new_lead(ctx), ("active" if r["status"] in ("released", "unled") else r["status"])
        r["renewed_at"], r["updated_by"] = iso(ctx.t), ctx.id
        return r, old
    old = update(ctx, a.name, fn)
    out = os.environ.get("QARGI_MARSHAL_AUDIT_OUT")
    if out:
        with open(out, "w") as f:
            f.write("%s %s old=%s new=%s" % (ctx.project, a.name, old, ctx.id))
    print("took over %s from %s (lead %s, ttl %d min); the approval covers this takeover only" % (a.name, old, ctx.id, ctx.ttl))


def v_finish(ctx, a):
    check_name(a.name)

    def fn(rec):
        rec = unled(ctx, a.name, rec)
        if rec is None:
            if a.lenient:
                return None, False
            raise Refuse("no record for feature %s" % a.name)
        ld = lead_of(rec)
        if ld and ld["id"] != ctx.id:
            raise Refuse(led_by_msg(ctx, a.name, rec, "; only its lead can finish it"))
        r = fresh(ctx, a.name, rec)
        r["lead"], r["status"], r["finished_at"] = None, "finished", iso(ctx.t)
        r["updated_by"] = ctx.id
        return r, True
    if update(ctx, a.name, fn):
        print("finished %s" % a.name)


def warnings_for(ctx, d, rec_exists):
    w = []
    if d["ghost"]:
        w.append("feature %s was abandoned: its branch feature/%s is gone" % (d["feature"], d["feature"]))
    elif d["lead"] and d["lease"] == "stale" and d["lead"]["id"] != ctx.id:
        w.append("the lead of %s (%s) is stale (renewed %s min ago, ttl %d): qargi marshal takeover %s --approved WORDS" % (
            d["feature"], d["lead"]["id"], "?" if d["minutes_since_renewal"] is None else d["minutes_since_renewal"], ctx.ttl, d["feature"]))
    elif not d["lead"] and (rec_exists or d["branch"]) and d["status"] not in ("finished", "abandoned"):
        w.append("feature %s has no lead (%s): claim or take it" % (d["feature"], d["status"]))
    for o, fs in d.get("overlap", {}).items():
        w.append("feature %s changes files that feature/%s also changes: %s" % (d["feature"], o, " ".join(clean(f) for f in fs[:10])))
    return w


def v_check(ctx, a):
    ctx.warn_anon()
    if a.name:
        check_name(a.name)
        rec = ctx.be.get(ctx, a.name)
        if rec is None and not branch_exists(ctx, a.name):
            raise Refuse("no feature %s in %s (no branch feature/%s and no record)" % (a.name, ctx.project, a.name))
        if rec is not None:
            rec = ghost_fix(ctx, a.name, rec)
        ld = lead_of(rec)
        if ld and ld["id"] != ctx.id:
            st, _ = lease(ctx, rec)
            if st == "live":
                raise Refuse(led_by_msg(ctx, a.name, rec))
        d = describe(ctx, a.name, rec, {})
        for w in warnings_for(ctx, d, rec is not None):
            print("qargi: warning: " + w, file=sys.stderr)
        if ld and ld["id"] == ctx.id:
            print("yours")
        elif ld:
            print("free (the lead %s is stale)" % clean(ld["id"]))
        else:
            print("free")
        return
    items = listed(ctx)
    for n, d, rec in items:
        print(brief_line(d))
        for w in warnings_for(ctx, d, True):
            print("qargi: warning: " + w, file=sys.stderr)
    if not items:
        print("no open features")


def usage_exit(msg):
    print("qargi: " + msg, file=sys.stderr)
    return 2


def choose_backend(a):
    """--backend refs --remote R, or --backend local; without --backend the switch $STATE/marshal/<project>.enabled decides
    (the marshal enable verb writes it: {backend, remote, ...}); no switch means the local backend."""
    be, remote = a.backend, a.remote
    if be is None:
        p = os.path.join(a.state, "marshal", "%s.enabled" % a.project)
        try:
            with open(p) as f:
                sw = json.load(f)
        except FileNotFoundError:
            return LocalBackend()
        except (OSError, ValueError) as e:
            raise Refuse("the marshal switch %s cannot be read (%s); fix it, or remove it with the marshal disable verb" % (p, e))
        if not isinstance(sw, dict):
            raise Refuse("the marshal switch %s is not a JSON object; fix it, or remove it with the marshal disable verb" % p)
        be, remote = sw.get("backend"), sw.get("remote")
    if be == "local":
        return LocalBackend()
    if be == "refs":
        remote = remote or "origin"
        if not isinstance(remote, str) or not refs_mod().remote_ok(remote):
            raise Refuse("the marshal remote %r is not a remote name" % (remote,))
        return RefsBackend(remote)
    raise Refuse("the marshal backend %r is unknown (local or refs)" % (be,))


def main(argv):
    # flags are single-quoted: tests/test_help.py treats a double-quoted option string as a user-facing option that commands.py must
    # describe; --state, --repo, --ttl, --purpose, --lenient, --backend and --remote are only passed by lib/marshal.sh (or come from the switch file)
    p = argparse.ArgumentParser(prog="marshal_store.py")
    p.add_argument("verb", choices=["claim", "start", "status", "set", "check", "renew", "release", "take", "takeover", "finish"])
    p.add_argument("name", nargs="?")
    p.add_argument('--state', required=True)
    p.add_argument('--project', required=True)
    p.add_argument('--repo', default="")
    p.add_argument('--ttl', type=int, default=15)
    p.add_argument('--as', dest="as_id")
    p.add_argument('--goal'), p.add_argument('--plan'), p.add_argument('--note'), p.add_argument('--status')
    p.add_argument('--purpose', default="")
    p.add_argument('--approved')
    p.add_argument('--all', action="store_true"), p.add_argument('--brief', action="store_true"), p.add_argument('--json', action="store_true")
    p.add_argument('--history', action="store_true")
    p.add_argument('--lenient', action="store_true")
    p.add_argument('--no-fetch', dest="no_fetch", action="store_true")
    p.add_argument('--backend', choices=["local", "refs"])
    p.add_argument('--remote')
    a = p.parse_args(argv)
    if a.verb not in ("status", "check") and not a.name:
        return usage_exit("%s needs a feature NAME" % a.verb)
    try:
        ctx = Ctx(a, choose_backend(a))
        if ctx.be.refs and ctx.be.member and a.verb not in ("status", "check"):
            return usage_exit("marshal %s is not available in a member run: a member never changes the shared marshal or pushes; the lead does" % a.verb)
        globals()["v_" + a.verb](ctx, a)
    except Unreachable as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 3
    except Refuse as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    except Exception:          # a bug is not a refusal: exit 70, so a caller never mistakes it for "another lead holds this"
        import traceback
        traceback.print_exc()
        return 70
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
