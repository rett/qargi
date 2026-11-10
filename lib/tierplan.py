#!/usr/bin/env python3
"""Plans for writing a memory tier: `qargi memory init TIER` and `qargi memory move PATH --from T --to T`.

  tierplan.py plan-init TIER [--project P] [--worktree DIR] [--today D] --out FILE
  tierplan.py plan-move PATH --from T --to T [--project P] [--worktree DIR] [--today D] --out FILE
  tierplan.py show FILE
  tierplan.py apply FILE

The approval gate (token, audit log, --approved) is in tierwrite.sh; this module only plans and applies, through the
same steps memplan.py uses (create, update, marker, archive), so nothing is ever deleted and every store is checked
against the notes the plan read before the first change (membackend.apply_ops). The target is written first.

init writes the canon-2 seed (memplan.canon_plan on an empty store) into one directory tier. It refuses a directory
that has other content, a repo tier that leaves its checkout, and locations that overlap another tier's.

The repo tier lives inside the project's checkout (repo.path) and qargi never commits it. --worktree DIR (the repo tier of init, or a
move that has it at one end) writes it into DIR instead, a worktree of the same repository, at the same path inside it, so the files
can be made on the branch that must hold them; the warning in the plan says in which directory and on which branch to commit.

move copies notes from one tier to another and archives the originals (/_archive/<date>/<path>), moving their index
rows too. A note lives in one tier, so the plan refuses a path that any other tier holds. A stale plan (a tier
changed after it was made) refuses with "plan again" before anything is written.

Exit codes: 0 done (also "nothing to do"), 1 refusal or failure, 2 usage. Messages go to stderr as `qargi: ...`
except what show prints and the "already initialised" line."""
import argparse, json, os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import canon as C  # noqa: E402
import membackend as B  # noqa: E402
import memplan as M  # noqa: E402
import tiers as T  # noqa: E402

NOT_CANON = "not empty and not a canon-%d store; use qargi canon plan or another path" % C.LATEST
PLACEHOLDER = "| (none yet) | | |"
PRIVATE = ("project", "shared", "system")          # tiers that are the user's own directories: created with umask 077


class Refused(Exception):
    pass


def say(msg):
    print("qargi: " + msg, file=sys.stderr)


def seed_dir():
    for rel in ("../provision/canon-seed", "provision/canon-seed"):
        d = os.path.join(HERE, rel)
        if os.path.isdir(d):
            return d
    raise Refused("the canon seed is missing from this installation")


def real(path):
    """The real path of path even when its tail does not exist yet: the nearest existing ancestor, resolved, plus the rest."""
    path = os.path.abspath(path)
    rest = []
    while not os.path.lexists(path) and path != os.path.dirname(path):
        path, tail = os.path.dirname(path), os.path.basename(path)
        rest.insert(0, tail)
    return os.path.join(os.path.realpath(path), *rest)


def nests(a, b):
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


def load_answers(project):
    project = T._project(project)
    a, err = T._answers(project)
    if err:
        raise Refused(err)
    return project, a


def checkout_of(a, tier):
    """For the repo tier: (checkout path, location relative to it); a Refused when it cannot be written safely."""
    repo = (a.get("repo") or {}).get("path") or ""
    if not repo:
        raise Refused("the repo tier needs repo.path in the project's answers (qargi project set P repo.path DIR)")
    repo = os.path.expanduser(repo)
    try:
        r = subprocess.run(["git", "-C", repo, 'rev-parse', '--is-inside-work-tree'], capture_output=True, text=True, timeout=10)
        ok = r.returncode == 0 and r.stdout.strip() == "true"
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        raise Refused("repo.path %s is not a git work tree; the repo tier lives inside the project's checkout" % repo)
    loc = tier["location"]
    if not real(loc).startswith(os.path.realpath(repo) + os.sep):
        raise Refused("the repo tier %s leaves the checkout %s (a link points out of it?); refusing" % (loc, repo))
    return repo, os.path.relpath(loc, repo)


def git_out(path, *args):   # (the flags in the calls below are git's, in single quotes: the help test reads double-quoted ones as this script's own)
    try:
        r = subprocess.run(["git", "-C", path] + list(args), capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def branch_of(path):
    """The branch checked out in a work tree, or 'a detached HEAD at SHA'."""
    b = git_out(path, "symbolic-ref", '--short', "-q", "HEAD")
    if b:
        return b
    sha = git_out(path, "rev-parse", '--short', "HEAD")
    return "a detached HEAD at %s" % sha if sha else "no commit yet"


def common_dir(path):
    d = git_out(path, "rev-parse", '--git-common-dir')
    return os.path.realpath(os.path.join(path, d)) if d else None


def repo_place(a, tier, worktree):
    """For the repo tier: (the directory to commit in, the tier's path inside it, the tier with its location there). Without a worktree that is the project's
    checkout; with one, DIR must be the top of a work tree of the same repository."""
    repo, rel = checkout_of(a, tier)
    if not worktree:
        return repo, rel, tier
    wt = os.path.realpath(os.path.expanduser(worktree))
    if not os.path.isdir(wt):
        raise Refused("--worktree %s is not a directory" % worktree)
    top = git_out(wt, "rev-parse", '--show-toplevel')
    if not top or os.path.realpath(top) != wt:
        raise Refused("--worktree %s is not the top of a git work tree" % worktree)
    cd = common_dir(wt)
    if not cd or cd != common_dir(os.path.expanduser(repo)):
        raise Refused("--worktree %s is not a worktree of the project's repository %s (git worktree list shows them)" % (worktree, repo))
    loc = os.path.join(wt, rel)
    if not real(loc).startswith(wt + os.sep):
        raise Refused("the repo tier %s leaves the worktree %s (a link points out of it?); refusing" % (rel, wt))
    return wt, rel, dict(tier, location=loc)


def repo_warning(repo, rel, worktree=False):
    """Where the repo tier is written and where its files must be committed; qargi never commits them."""
    branch = branch_of(repo)
    if worktree:
        return ("WARNING: this writes into %s at %s, a worktree of the project's repository (%s checked out there); qargi never commits it: commit %s on that "
                "branch (git -C %s add %s, then git commit), so that it reaches the other worktrees and the members' clones when that branch does."
                % (repo, rel, branch, rel, repo, rel))
    return ("WARNING: this writes into the repository checkout %s at %s (%s checked out there); qargi never commits it: review it and commit it yourself on "
            "that branch, or ignore it in git. A member's clone is made from the committed branch, so it sees the files only after that. To write them into "
            "another worktree of this repository, for example one on the integration branch, add --worktree DIR." % (repo, rel, branch))


def tier_named(a, project, name):
    return next(t for t in T.resolve(a, project) if t["tier"] == name)


def state_of(t):
    """-> (status, listing, why) with 'marker' checked: status becomes 'canon' when the tier holds a canon-LATEST memory store."""
    st, lst, why = T.probe(t)
    if st == "present" and C.detect("memory", lst)[0] == C.LATEST:
        return "canon", lst, ""
    return st, lst, why


def backend_of(t):
    if t["kind"] == "cloud":
        return B.CloudBackend(t["store_id"])
    return B.DirBackend(t["location"])


def ref_of(t):
    return t["store_id"] if t["kind"] == "cloud" else t["location"]


def open_ref(ref, write):
    """A backend from a plan's store reference: a directory, or a memstore_ id (QARGI_CANON_FIXTURE_DIR replaces the cloud)."""
    if ref.startswith("memstore_"):
        fd = os.environ.get("QARGI_CANON_FIXTURE_DIR")
        if fd:
            fx = os.path.join(fd, ref + ".jsonl")
            if os.path.isfile(fx):
                return B.FixtureBackend(fx)
        return B.CloudBackend(ref)
    return B.DirBackend(ref)


# --- init

def plan_init(tier_name, project_arg, today, worktree=None):
    if tier_name == "cloud":
        raise Refused("the cloud tier is created by qargi provision")
    if worktree and tier_name != "repo":
        raise Refused("--worktree is for the repo tier, which lives in a checkout; tier %s is a directory of its own" % tier_name)
    project, a = load_answers(project_arg)
    t = tier_named(a, project, tier_name)
    repo = rel = None
    if tier_name == "repo":
        repo, rel, t = repo_place(a, t, worktree)
    loc = t["location"]
    if not loc:
        raise Refused("tier %s has no location" % tier_name)
    me = real(loc)
    if os.path.lexists(loc) and not os.path.isdir(loc):
        raise Refused("%s exists and is not a directory" % loc)
    pa, rcsv = T.check_args(tier_name, project, T._roles(a) or ["build"])
    roles = rcsv.split(",")
    held = {}                                     # what a set-up that was interrupted left (no marker yet)
    if os.path.isdir(loc) and os.listdir(loc):
        marker = os.path.join(loc, "CANON.md")
        if os.path.isfile(marker) and not os.path.islink(marker):
            with open(marker, encoding="utf-8", errors="replace") as h:
                m = C.parse_marker(h.read())
            if m.get("canon") == str(C.LATEST) and m.get("kind") == "memory":
                print("tier %s is already initialised at %s; nothing to do" % (tier_name, loc))
                return None
        else:
            held = B.DirBackend(loc).list()
        if not held or C.detect("memory", held, roles)[0] != "empty":
            raise Refused(NOT_CANON)
    for o in T.resolve(a, project):
        if o["tier"] != tier_name and o["kind"] == "dir" and o["location"] and nests(me, real(o["location"])):
            raise Refused("tier %s at %s overlaps tier %s at %s" % (tier_name, loc, o["tier"], o["location"]))
    plan = M.canon_plan(held, "memory", pa, roles, seed_dir(), today)
    plan.update(verb="init", tier=tier_name, stores={"target": loc}, needs_ant=False, private={"target": tier_name in PRIVATE})
    if repo:
        plan["warning"] = repo_warning(repo, rel, bool(worktree))
    return plan


# --- move

def index_parts(path):
    """('/shared' or '/roles/R', rest) for a note path."""
    m = re.match(r"^(/shared|/roles/[^/]+)/(.+)$", path)
    return m.group(1), m.group(2)


def drop_row(content, rel):
    """(content without the row for rel, the row line or None)."""
    lines = content.split("\n")
    row, keep = None, []
    for l in lines:
        m = C.ROW.match(l)
        if m and m.group(1) == rel:
            row = row or l.rstrip("\r")
            continue
        keep.append(l)
    out = "\n".join(keep)
    if row and not C.ROW.search(out) and PLACEHOLDER not in out:      # the table is empty again: the seed's own placeholder
        for i, l in enumerate(keep):
            if re.match(r"^\|\s*-+\s*\|", l):
                keep.insert(i + 1, PLACEHOLDER)
                out = "\n".join(keep)
                break
    return out, row


def add_row(content, row):
    """content with row after its last table row (in place of the placeholder when the table is empty, else at the end)."""
    lines = content.split("\n")
    last = None
    for i, l in enumerate(lines):
        if C.ROW.match(l):
            last = i
    if last is None:
        last = next((i for i, l in enumerate(lines) if l.strip() == PLACEHOLDER), None)
        if last is not None:
            lines[last] = row
            return "\n".join(lines)
        if lines and lines[-1] == "":
            lines.insert(len(lines) - 1, row)
        else:
            lines.append(row)
        return "\n".join(lines)
    lines.insert(last + 1, row)
    return "\n".join(lines)


def index_template(seed, base, role_name=None):
    if base == "/shared":
        return C.slurp(os.path.join(seed, "INDEX.shared.memory.md"))
    return C.slurp(os.path.join(seed, "INDEX.role.memory.md")).replace("{{ROLE}}", base.split("/")[2])


def select_notes(src, path):
    if path.endswith(".md"):
        if path in src and C.is_note(path) and not T.STRUCTURAL.search(path):
            return [path]
        return []
    base = path.rstrip("/")
    return [p for p in T.notes_of(src) if p == base or p.startswith(base + "/")]


def plan_move(path, frm, to, project_arg, today, worktree=None):
    if frm == to:
        raise Refused("--from and --to are the same tier")
    if worktree and "repo" not in (frm, to):
        raise Refused("--worktree is for the repo tier, and this move has it at neither end")
    why = B.path_problem(path)
    if why:
        raise Refused("PATH %s is not a store path (%s)" % (path, why))
    if re.match(r"^/roles/[^/]+$", path):                         # a role folder given without its trailing slash
        path += "/"
    if not re.match(r"^/(shared|roles/[^/]+)/", path):
        raise Refused("PATH must lie under /shared/ or /roles/<role>/: %s" % path)
    project, a = load_answers(project_arg)
    tiers = {t["tier"]: t for t in T.resolve(a, project)}
    repo = rel = None
    if "repo" in (frm, to):
        repo, rel, tiers["repo"] = repo_place(a, tiers["repo"], worktree)
    states = {}
    for name in (frm, to):
        t = tiers[name]
        st, lst, why = state_of(t)
        if st == "unreachable":
            raise Refused("tier %s is unreachable (%s)" % (name, why))
        if st in ("missing", "empty"):
            raise Refused("tier %s is missing: %s" % (name, "the cloud tier is created by qargi provision" if t["kind"] == "cloud"
                                                      else "qargi memory init %s" % name))
        if st != "canon":
            raise Refused("tier %s is not a canon-%d store: qargi memory check" % (name, C.LATEST))
        states[name] = lst
    src, dst = states[frm], states[to]
    sel = select_notes(src, path)
    if not sel:
        raise Refused("no note under %s in tier %s" % (path, frm))
    warns, refused = [], []
    for name, t in tiers.items():
        if name == frm:
            continue
        if name == to:
            lst = dst
        else:
            st, lst, why = T.probe(t)
            if st == "unreachable":
                warns.append("WARNING: tier %s unreachable; collisions with it not checked" % name)
                continue
        for p in sel:
            if lst and p in lst:
                refused.append("refused: %s is also in tier %s; resolve it first (qargi memory check)" % (p, name))
    if refused:
        raise Refused("\n".join(refused))
    sb, db = backend_of(tiers[frm]), backend_of(tiers[to])
    label = "tier-%s" % frm
    try:
        plan = M.merge(dst, src, "conflicts", today, label, sel, db.refusal)
        sops = M.archive_ops(src, sel, today, sb.refusal)
    except M.PlanRefused as x:
        raise Refused(str(x))
    sexpect = dict(plan.pop("read"))
    for op in sops:
        sexpect[op["to"]] = None
    tops, texpect, sidx, tidx = plan["target"]["ops"], plan["target"]["expect"], {}, {}
    for p in sel:                                   # the index rows go with the notes
        base, rel_ref = index_parts(p)
        idx = base + "/INDEX.md"
        cur = sidx.get(idx) or (src[idx]["content"] if idx in src else None)
        row = None
        if cur is not None:
            sidx[idx], row = drop_row(cur, rel_ref)
        row = row or "| %s | moved from tier %s | when the task touches it |" % (rel_ref, frm)
        tcur = tidx.get(idx)
        if tcur is None:
            tcur = dst[idx]["content"] if idx in dst else index_template(seed_dir(), base)
        if not any(m.group(1) == rel_ref for m in C.ROW.finditer(tcur)):
            tcur = add_row(tcur, row)
        tidx[idx] = tcur
    sx, tx, notes = [], [], plan["notes"]
    for idx, new in sorted(sidx.items()):
        if new != src[idx]["content"]:
            sexpect[idx] = M.d(src[idx])
            sx.append({"op": "update", "path": idx, "content": new, "sha": M.d(src[idx])})
    for idx, new in sorted(tidx.items()):
        if idx in dst:
            if new != dst[idx]["content"]:
                texpect[idx] = M.d(dst[idx])
                tx.append({"op": "update", "path": idx, "content": new, "sha": M.d(dst[idx])})
        else:
            texpect[idx] = None
            tx.append({"op": "create", "path": idx, "content": new})
    bad = [("%s (%s)" % (op["path"], w)) for op in tx for w in [db.refusal(op["path"], op["content"])] if w]
    if bad:
        raise Refused("refused, the target cannot hold: " + "; ".join(bad))
    plan["target"] = {"ops": tops + tx, "expect": texpect}
    plan["source"] = {"ops": sops + sx, "expect": sexpect}
    plan["notes"] = notes + warns
    plan.update(verb="move", from_tier=frm, to_tier=to, path=path, stores={"source": ref_of(tiers[frm]), "target": ref_of(tiers[to])},
                needs_ant="cloud" in (frm, to), private={"target": to in PRIVATE, "source": frm in PRIVATE})
    if repo:
        plan["warning"] = repo_warning(repo, rel, bool(worktree))
    return plan


# --- show, apply

def show(plan):
    if plan["verb"] == "init":
        head = "init tier %s -> %s" % (plan["tier"], plan["stores"]["target"])
    else:
        head = "move %s from tier %s to tier %s" % (plan["path"], plan["from_tier"], plan["to_tier"])
    out = [head, M.show(plan)]
    if plan.get("warning"):
        out.append(plan["warning"])
    return "\n".join(out)


def apply(plan):
    """Check every store, then write: the target first. Files a private tier gets are created with umask 077."""
    backends = {k: open_ref(v, bool(plan.get(k) and plan[k]["ops"])) for k, v in plan["stores"].items()}
    M.apply_plan(plan, backends, dry_run=True)          # all stores checked before the first change
    n = 0
    for k in ("target", "source"):
        if k not in backends or not plan.get(k) or not plan[k]["ops"]:
            continue
        old = os.umask(0o077) if (plan.get("private") or {}).get(k) else None
        try:
            n += len(B.apply_ops(backends[k], plan[k]["ops"], plan[k]["expect"], False))
        finally:
            if old is not None:
                os.umask(old)
    print("applied %d step(s)" % n)
    if plan["verb"] == "init":
        print("files: %d" % len(backends["target"].list()))


def main(argv):
    ap = argparse.ArgumentParser(prog="tierplan.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan-init")
    s.add_argument("tier")
    s = sub.add_parser("plan-move")
    s.add_argument("path")
    s.add_argument("--from", dest="frm", required=True, choices=T.ORDER)
    s.add_argument("--to", required=True, choices=T.ORDER)
    for s in (sub.choices["plan-init"], s):
        s.add_argument("--project")
        s.add_argument("--worktree")
        s.add_argument('--today')
        s.add_argument('--out', required=True)
    for n in ("show", "apply"):
        sub.add_parser(n).add_argument("file")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "plan-init" and a.tier not in T.ORDER:
            ap.error("TIER is one of repo, project, shared, system")
        if a.cmd in ("plan-init", "plan-move"):
            today = a.today or M.today_utc()
            plan = (plan_init(a.tier, a.project, today, a.worktree) if a.cmd == "plan-init"
                    else plan_move(a.path, a.frm, a.to, a.project, today, a.worktree))
            if plan is None:
                return 0
            with open(a.out, "w") as f:
                json.dump(plan, f, sort_keys=True)
            return 0
        with open(a.file) as f:
            plan = json.load(f)
        if a.cmd == "show":
            print(show(plan))
        else:
            apply(plan)
    except Refused as x:
        for line in str(x).split("\n"):
            say(line)
        return 1
    except B.StaleError as x:
        say("a tier changed since the plan was made (%s); nothing was written: plan again" % x)
        return 1
    except (B.StoreError, M.PlanRefused, ValueError, OSError, KeyError) as x:
        say(str(x))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
