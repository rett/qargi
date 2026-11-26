#!/usr/bin/env python3
"""What `qargi project remove NAME` plans and what holds it back (read only; lib/project.sh does the removal).

  project_remove.py scan NAME     print one JSON object on standard output, exit 0; nothing is changed:

      {"project": NAME, "answers": PATH, "answers_sha": SHA256-OF-THE-FILE,
       "members": [{"name", "roles", "file", "file_exists", "copy", "copy_exists"}],      the members of NAME in agents.json, by name
       "members_sha": SHA256 of the raw record of the project in agents.json (every member as stored), "" when it has none,
       "approved": the id of the approved verify.environment declaration, "" when there is an entry for it that declares none, null when there is no entry,
       "stays": [PATH],                                                                    files of the marshal that the removal leaves (the switch of the shared refs backend, the allowed signers),
       "held": [{"code": REFUSAL-CODE, "values": {FIELD: TEXT}}]}                          what refuses the removal, in a fixed order

The answers file holds the stored answers; the members are the entries of the project in the members file (config/agents.json) with the written member file
and the render's copy in config/agents/NAME/ that `qargi agent remove` would take away. The removal never touches the repository: the one thing read from it
is the list of its feature branches and of its work trees (git for-each-ref, git worktree list: reads).

Held, in this order, each with the refusal code of lib/refusals.json that names the command that clears it:
  project-remove-feature     an open feature: a branch feature/* of the repository (qargi feature list)
  project-remove-run         an open run of the lead's registry for the project (a line of local-runs.jsonl that is not cleaned and not closed)
  project-remove-lease       a marshal record of a feature of the project, neither finished nor abandoned, whose lead renewed it less than marshal.lease_minutes ago
  project-remove-release     a cut record of a release (release/NAME-VERSION.cut.json) without the finish step
  project-remove-linked      a work tree of the repository where `qargi project unlink NAME` would unlink something (project_link.py plan)
  project-remove-cloud       the cloud answer (qargi cloud): a profile and a workspace
  project-remove-instances   an entry of instances.json named NAME-...
  project-remove-unreadable  something that could hold the removal back and cannot be read although its source is there: the stored answers (not JSON, not an
                             object), git in the repository (for-each-ref, worktree list), the plan of project unlink in a work tree (it did not run or took too
                             long), instances.json, the registry local-runs.jsonl (the file or a line of it), the directories features/ and release/ of the state,
                             and the marshal of a project on the shared refs backend (its switch file $STATE/marshal/NAME.enabled: the leases are in refs of the
                             remote, so they cannot be read in the state); each names what and the one command or file that fixes it

A thing that cannot be read is reported as held: the removal goes on only when nothing holds it, so a plan that says nothing holds it back has read
everything that could. A source that is not there holds nothing. A repository that is gone or is not one has no feature and no work tree to look at.
Run through lib/project.sh; python3 -I, standard library only."""
import calendar
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402

NAME_RE = re.compile(r"^[a-z][a-z0-9]{0,23}$")
FMT = "%Y-%m-%dT%H:%M:%SZ"
CTRL = re.compile(r"[\x00-\x1f\x7f]")
MAX = 200                       # a value of a refusal is one line of at most this many characters
GIT_TIMEOUT = 20


def text(s):
    """One line of at most MAX characters, the control characters shown as ?: what a refusal and a plan print of a name or a path."""
    return CTRL.sub("?", str(s))[:MAX]


class Unreadable:
    """What could not be read, each with what to fix: a hold of project-remove-unreadable (the two lists are one item for each thing)."""

    def __init__(self):
        self.items = []

    def add(self, what, fix):
        self.items.append((text(what), text(fix)))


def load(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (OSError, ValueError):
        return None


def git(repo, *args):
    """The output lines of a read of git in repo, or None when git is not there, fails or takes too long."""
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0")
    try:
        r = subprocess.run(["git", "-C", repo] + list(args), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                           env=env, timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.decode("utf-8", "replace").splitlines() if r.returncode == 0 else None


def is_repo(path):
    """A directory that is a repository to look at: a checkout (a .git entry) or a bare one. A path that is not one has no feature and no work tree."""
    return os.path.exists(os.path.join(path, ".git")) or (os.path.isfile(os.path.join(path, "HEAD")) and os.path.isdir(os.path.join(path, "objects")))


def repo_of(answers):
    p = (answers.get("repo") or {}).get("path") if isinstance(answers.get("repo"), dict) else ""
    p = os.path.expanduser(p) if isinstance(p, str) else ""
    return p if p and os.path.isdir(p) else ""


def members_of(conf, name):
    """The members of the project, from agents.json, with what removing each takes away, and the hash of the project's raw record there
    (the text of a member is cut and cleaned for the plan; the hash is of what is stored, so a changed record is a changed token)."""
    doc = load(os.path.join(conf, "agents.json"), {})
    if doc is None or not isinstance(doc, dict):
        sys.exit("qargi: %s cannot be read as the members file; nothing was planned" % os.path.join(conf, "agents.json"))
    projects = doc.get("projects", {}) if doc else {}
    mine = projects.get(name) if isinstance(projects, dict) else None
    sha = hashlib.sha256(json.dumps(mine, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest() if mine is not None else ""
    out = []
    for n in sorted(mine or {}):
        rec = mine[n] if isinstance(mine[n], dict) else {}
        f = rec.get("file") if isinstance(rec.get("file"), str) else ""
        rp = (rec.get("render") or {}).get("path") if isinstance(rec.get("render"), dict) else ""
        copy = ""
        # a copy is the render's path under config/agents/NAME: a path that leaves it is no copy of ours
        if isinstance(rp, str) and rp and not os.path.isabs(rp) and ".." not in rp.split("/"):
            copy = os.path.join(conf, "agents", name, rp)
        out.append({"name": text(n), "roles": [text(r) for r in rec.get("roles", []) if isinstance(r, str)] if isinstance(rec.get("roles"), list) else [],
                    "file": text(f), "file_exists": bool(f) and os.path.isfile(f), "copy": text(copy), "copy_exists": bool(copy) and os.path.isfile(copy)})
    return out, sha


def features(repo, bad):
    if not repo or not is_repo(repo):
        return []
    out = git(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads/feature/*")
    if out is None:
        bad.add("the feature branches of the repository %s (git for-each-ref failed or took more than %d s)" % (repo, GIT_TIMEOUT),
                "make git -C %s for-each-ref refs/heads/feature/* work" % repo)
        return []
    return sorted(b[len("feature/"):] for b in out if b.startswith("feature/"))


def runs(state, name, repo, bad):
    """The runs of the lead's registry that belong to the project and are not cleaned or closed (the last line of a run is the run's)."""
    last = {}
    path = os.path.join(state, "local-runs.jsonl")
    skipped = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if isinstance(r, dict) and isinstance(r.get("run"), str) and r["run"]:
                    last[r["run"]] = r
    except FileNotFoundError:
        return []
    except OSError as e:
        bad.add("the registry of runs %s (%s)" % (path, e.strerror or type(e).__name__), "make %s readable (qargi local list reads it)" % path)
        return []
    if skipped:
        bad.add("%d line(s) of the registry of runs %s are not JSON, so a run of the project may be among them" % (skipped, path),
                "repair or remove those lines of %s (qargi local list names them)" % path)
    rp = os.path.realpath(repo) if repo else ""
    out = []
    for run, r in last.items():
        mine = r.get("project") == name or (rp and isinstance(r.get("repo"), str) and r["repo"] and os.path.realpath(r["repo"]) == rp)
        if mine and not r.get("cleaned") and not r.get("closed"):
            out.append(text(run))
    return sorted(out)


def now():
    v = os.environ.get("QARGI_MARSHAL_NOW")
    try:
        return int(float(v)) if v else int(time.time())
    except ValueError:
        return int(time.time())


def listing(path, what, fix, bad):
    """The sorted names in a directory of the state: [] when it is not there, and a thing that could not be read when it is there and cannot be listed."""
    try:
        return sorted(os.listdir(path))
    except FileNotFoundError:
        return []
    except OSError as e:
        bad.add("%s %s (%s)" % (what, path, e.strerror or type(e).__name__), fix)
        return []


def leases(state, name, ttl, bad):
    """The features of the project whose marshal record names a lead whose lease is live (or whose time cannot be read)."""
    fdir = os.path.join(state, "features")
    out = []
    entries = listing(fdir, "the marshal records in", "make %s readable (qargi marshal status --project %s reads it)" % (fdir, name), bad)
    pat = re.compile(r"^%s-([a-z0-9]+(?:-[a-z0-9]+)*)\.json$" % re.escape(name))
    for fn in entries:
        m = pat.match(fn)
        if not m:
            continue
        rec = load(os.path.join(fdir, fn), None)
        if not isinstance(rec, dict):
            out.append(text(m.group(1)))
            continue
        ld = rec.get("lead")
        if not (isinstance(ld, dict) and ld.get("id")) or rec.get("status") in ("finished", "abandoned"):
            continue
        try:
            age = now() - calendar.timegm(time.strptime(rec.get("renewed_at"), FMT))
        except (TypeError, ValueError):
            out.append(text(m.group(1)))
            continue
        if age < ttl * 60:
            out.append(text(m.group(1)))
    return out


def marshal_files(state, name):
    """The files of the marshal that are kept for the project outside its records: the switch of the shared refs backend and the allowed signers."""
    return [p for p in (os.path.join(state, "marshal", name + ext) for ext in (".enabled", ".signers")) if os.path.lexists(p)]


def shared(state, name, bad):
    """A project on the shared refs backend keeps its leases in refs of the remote, which the records of the state do not hold: with its switch file
    there (the backend is not the local one) the leases cannot be read here, and that holds the removal."""
    sw = os.path.join(state, "marshal", name + ".enabled")
    if not os.path.lexists(sw):
        return
    doc = load(sw, None)
    if isinstance(doc, dict) and doc.get("backend") == "local":
        return
    bad.add("the marshal leases of %s: it is on the shared refs backend (the switch %s), whose leases are in refs of the remote, not in the records of this machine" % (name, sw),
            "qargi marshal status --project %s shows them; release each (qargi marshal release FEATURE --project %s), then qargi marshal disable --project %s" % (name, name, name))


def cuts(state, name, bad):
    """The versions of the project's release cut records that did not reach finish."""
    rdir = os.path.join(state, "release")
    out = []
    prefix, suffix = name + "-", ".cut.json"
    for fn in listing(rdir, "the release cut records in", "make %s readable (qargi release status --project %s reads it)" % (rdir, name), bad):
        if not (fn.startswith(prefix) and fn.endswith(suffix)) or len(fn) <= len(prefix) + len(suffix):
            continue
        rec = load(os.path.join(rdir, fn), None)
        done = rec.get("done") if isinstance(rec, dict) else None
        if isinstance(rec, dict) and isinstance(done, dict) and done.get("finish"):
            continue
        out.append(text(fn[len(prefix):-len(suffix)]))
    return out


def linked(name, repo, bad):
    """The work trees of the repository (it too) where qargi project unlink NAME would unlink something: project_link.py plans it and writes
    a token only when there is something to do. A work tree it cannot plan for (no provider, no checkout: it exits without a token) has nothing it
    links; one where it did not run or took too long is a thing that could not be read."""
    if not repo or not is_repo(repo):
        return []
    trees = [repo]
    listed = git(repo, "worktree", "list", "--porcelain")
    if listed is None:
        bad.add("the work trees of the repository %s (git worktree list failed or took more than %d s)" % (repo, GIT_TIMEOUT),
                "make git -C %s worktree list work" % repo)
        listed = []
    for line in listed:
        if line.startswith("worktree "):
            trees.append(line[len("worktree "):])
    seen, out = set(), []
    with tempfile.TemporaryDirectory() as tmp:
        for t in trees:
            real = os.path.realpath(t)
            if real in seen or not os.path.isdir(real):
                continue
            seen.add(real)
            tok = os.path.join(tmp, "token")
            if os.path.exists(tok):
                os.unlink(tok)
            try:
                subprocess.run([sys.executable, "-I", os.path.join(HERE, "project_link.py"), "plan", "unlink", name, "", tok], cwd=real, stdin=subprocess.DEVNULL,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
            except (OSError, subprocess.SubprocessError) as e:
                bad.add("the links of project %s in the work tree %s (the plan of project unlink did not run: %s)" % (name, real, type(e).__name__),
                        "run qargi project unlink %s inside %s and see what it says" % (name, real))
                continue
            if os.path.isfile(tok) and os.path.getsize(tok) > 0:
                out.append(text(real))
    return out


def bound(answers):
    c = answers.get("cloud")
    return isinstance(c, dict) and bool(c.get("profile")) and bool(c.get("workspace_id"))


def instances(conf, name, bad):
    path = os.path.join(conf, "instances.json")
    doc = load(path, {})
    if not isinstance(doc, dict):
        bad.add("the registry of instances %s is not a JSON object that can be read" % path, "repair %s by hand (qargi instances list reads it)" % path)
        return []
    return sorted(text(k) for k in doc if isinstance(k, str) and k.startswith(name + "-"))


def approved(state, name):
    """The id of the approved verify.environment declaration of the project: "" when the entry says it is off, None when there is no entry."""
    import suite_env as SE  # noqa: E402
    entry = SE.approved_get(name, state)
    if entry is None:
        return None
    return SE.suite_env_id(entry.get("declared")) or ""


def scan(name):
    conf, state = paths.conf(), paths.state()
    ap = os.path.join(conf, "projects", name + ".json")
    try:
        with open(ap, "rb") as f:
            raw = f.read()
    except OSError:
        sys.exit("qargi: no stored answers for %s (qargi project list)" % name)
    bad = Unreadable()
    try:
        answers = json.loads(raw)
    except ValueError:
        answers = None
    if not isinstance(answers, dict):
        answers = {}
        bad.add("the stored answers %s are not a JSON object, so the repository, the cloud binding and the lease length of the project are not known" % ap,
                "repair %s by hand (qargi project validate %s says what is wrong)" % (ap, name))
    repo = repo_of(answers)
    mz = answers.get("marshal")
    ttl = mz.get("lease_minutes") if isinstance(mz, dict) else None
    ttl = ttl if isinstance(ttl, int) and not isinstance(ttl, bool) and 1 <= ttl <= 1440 else 15
    held = []
    for code, field, found in (("project-remove-feature", "features", features(repo, bad)), ("project-remove-run", "runs", runs(state, name, repo, bad)),
                               ("project-remove-lease", "features", leases(state, name, ttl, bad)), ("project-remove-release", "versions", cuts(state, name, bad)),
                               ("project-remove-linked", "trees", linked(name, repo, bad))):
        if found:
            held.append({"code": code, "values": {field: ",".join(x.replace(",", ";") for x in found)}})
    if bound(answers):
        held.append({"code": "project-remove-cloud", "values": {}})
    inst = instances(conf, name, bad)
    if inst:
        held.append({"code": "project-remove-instances", "values": {"instances": ",".join(x.replace(",", ";") for x in inst)}})
    shared(state, name, bad)
    if bad.items:
        held.append({"code": "project-remove-unreadable", "values": {"what": ",".join(w.replace(",", ";") for w, _ in bad.items),
                                                                      "fix": ",".join(f.replace(",", ";") for _, f in bad.items)}})
    members, members_sha = members_of(conf, name)
    return {"project": name, "answers": ap, "answers_sha": hashlib.sha256(raw).hexdigest(), "members": members, "members_sha": members_sha,
            "approved": approved(state, name), "stays": [text(p) for p in marshal_files(state, name)], "held": held}


def main(argv):
    if len(argv) != 2 or argv[0] != "scan" or not NAME_RE.fullmatch(argv[1]):
        print("usage: project_remove.py scan NAME", file=sys.stderr)
        return 2
    print(json.dumps(scan(argv[1]), sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
