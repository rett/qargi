#!/usr/bin/env python3
"""Attach qargi to an existing repository without changing it.

  attach.py detect DIR [--name N] [--methodology M]    print JSON: what was found, the draft answers, the gaps, the questions
  attach.py adopt-plan PROJECT ANSWERS [--methodology M]   print JSON: the safe gaps `qargi project adopt` would close (reads only)
  attach.py adopt-apply PROJECT ANSWERS < PLAN          create what that plan lists (stdin is the plan adopt-plan printed)

detect only reads DIR (files and `git` queries). The draft answers are what `qargi project init` would store; the gaps are what
the chosen methodology has that the repository lacks (`qargi project adopt` closes the safe ones, as a branch to review); the
questions are the facts it could not determine. Nothing is written by detect or adopt-plan, and nothing about the project goes
into its repository.

adopt-apply writes exactly two kinds of thing: local branches that did not exist (git branch, never -f), and one commit of
files that did not exist, made with git plumbing in a temporary index on a new branch, so the checked-out branch, the index
and the working tree are never touched. It refuses (exit 2) a member run, an unattached project, a repository with no commit,
a detached HEAD and a dirty working tree.
"""
import hashlib, json, os, re, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marshal_refs as MR  # noqa: E402  (in_member_run)
import methodology as M  # noqa: E402
import provider as PV  # noqa: E402


def git(d, *args):
    r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


class Tree:
    """The files of one commit of the repository, read with git (ls-tree, show): never the working tree."""

    def __init__(self, d, ref):
        self.d, self.ref = d, ref
        out = git(d, "ls-tree", "-r", "--name-only", "-z", ref) if ref else ""
        self.files = set(p for p in out.split("\0") if p)
        self.dirs = set()
        for p in self.files:
            while "/" in p:
                p = p.rsplit("/", 1)[0]
                self.dirs.add(p)

    def read(self, rel):
        if rel not in self.files:
            return ""
        r = subprocess.run(["git", "-C", self.d, "show", "%s:%s" % (self.ref, rel)], capture_output=True)
        return r.stdout.decode("utf-8", "replace") if r.returncode == 0 else ""

    def exists(self, rel):
        rel = rel.rstrip("/")
        return rel in self.files or rel in self.dirs

    def listdir(self, rel):
        pre = rel.rstrip("/") + "/"
        return [p[len(pre):] for p in self.files if p.startswith(pre) and "/" not in p[len(pre):]]


def read(t, rel):
    return t.read(rel)


def exists(t, rel):
    return t.exists(rel)


def integration_ref(d, long_lived, branches):
    """(ref, why): the methodology's integration branch (its last long-lived one), else the default branch, else HEAD."""
    def has(b):
        for full in ("refs/heads/" + b, "refs/remotes/origin/" + b):
            if git(d, "rev-parse", "--verify", "-q", full + "^{commit}"):
                return full
        return ""
    if long_lived:
        r = has(long_lived[-1])
        if r:
            return r, "the methodology's integration branch %s" % long_lived[-1]
    dflt = git(d, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").replace("origin/", "", 1)
    for b in ([dflt] if dflt else []) + ["master", "main", "trunk"]:
        r = has(b)
        if r:
            return r, "the default branch %s (no %s branch)" % (b, long_lived[-1] if long_lived else "integration")
    if git(d, "rev-parse", "--verify", "-q", "HEAD^{commit}"):
        return "HEAD", "HEAD (no integration or default branch found)"
    return "", "no commit yet"


def project_name(d, remote):
    base = ""
    if remote:
        base = re.sub(r"\.git$", "", remote.rstrip("/").split("/")[-1].split(":")[-1])
    base = base or os.path.basename(d.rstrip("/"))
    name = re.sub(r"[^a-z0-9]", "", base.lower())
    if not name or not name[0].isalpha():
        name = "p" + name
    return name[:24]


def https_url(remote):
    """The https form of a remote (the answers keep one; a private key never leaves the machine)."""
    m = re.match(r"^(?:ssh://)?git@([^:/]+)[:/](.+?)(?:\.git)?$", remote)
    if m:
        return "https://%s/%s" % (m.group(1), m.group(2))
    return re.sub(r"\.git$", "", remote)


def test_command(d):
    mk = read(d, "Makefile")
    if re.search(r"(?m)^test\s*:", mk):
        return "make test", "Makefile has a test target"
    if exists(d, "tests/run.sh"):
        return "bash tests/run.sh", "tests/run.sh"
    pj = read(d, "package.json")
    if pj:
        try:
            if (json.loads(pj).get("scripts") or {}).get("test"):
                return "npm test", "package.json has a test script"
        except ValueError:
            pass
    if exists(d, "go.mod"):
        return "go test ./...", "go.mod"
    if exists(d, "Cargo.toml"):
        return "cargo test", "Cargo.toml"
    if exists(d, "pyproject.toml") or exists(d, "pytest.ini") or exists(d, "setup.cfg") or exists(d, "tox.ini"):
        return "python3 -m pytest", "Python project files"
    return "", ""


def language(d):
    for f, lang in (("go.mod", "go"), ("Cargo.toml", "rust"), ("package.json", "javascript"), ("pyproject.toml", "python"),
                    ("setup.py", "python"), ("Gemfile", "ruby"), ("pom.xml", "java"), ("build.gradle", "java")):
        if exists(d, f):
            return lang
    return ""


def version_info(d):
    if exists(d, "VERSION"):
        v = read(d, "VERSION").strip().splitlines()
        return {"file": "VERSION", "value": v[0] if v else ""}
    pj = read(d, "package.json")
    if pj:
        try:
            v = json.loads(pj).get("version")
            if v:
                return {"file": "package.json", "value": v}
        except ValueError:
            pass
    for f in ("pyproject.toml", "Cargo.toml"):
        m = re.search(r'(?m)^version\s*=\s*"([^"]+)"', read(d, f))
        if m:
            return {"file": f, "value": m.group(1)}
    return {}


def tag_pattern(tags):
    sem = [t for t in tags if re.fullmatch(r"v?\d+\.\d+\.\d+([-+].*)?", t)]
    if not sem:
        return {"count": len(tags), "pattern": ""}
    return {"count": len(tags), "pattern": "v<semver>" if sem[0].startswith("v") else "<semver>"}


def changelog_info(d):
    for f in ("CHANGELOG.md", "CHANGELOG", "HISTORY.md", "NEWS.md"):
        if exists(d, f):
            t = read(d, f)
            return {"file": f, "keepachangelog": bool(re.search(r"(?mi)^## \[?unreleased\]?", t))}
    return {}


def detect(d, name=None, methodology="gitflow"):
    d = os.path.realpath(d)
    top = git(d, "rev-parse", "--show-toplevel")
    if not top:
        raise SystemExit("qargi: %s is not inside a git repository (a new project: qargi project new)" % d)
    d = os.path.realpath(top)
    remote = git(d, "remote", "get-url", "origin")
    branches = sorted(set(b.strip().replace("origin/", "", 1) for b in git(d, "branch", "-a", "--format=%(refname:short)").splitlines()
                          if b.strip() and "HEAD" not in b))
    head = git(d, "symbolic-ref", "--short", "-q", "HEAD")
    long_lived = [b for b in ("master", "main", "trunk", "develop") if b in branches]
    tags = git(d, "tag", "--sort=-creatordate").splitlines()
    where, md, m = M.load(methodology)
    ref, ref_why = integration_ref(d, (m.get("branches") or {}).get("long_lived", []), branches)
    dpath, d = d, Tree(d, ref)   # from here on d is the tree of ref
    cmd, why = test_command(d)
    ci = sorted(f for f in d.listdir(".github/workflows") if f.endswith((".yml", ".yaml")))
    found = {
        "ref": ref and git(dpath, "rev-parse", "--abbrev-ref", ref) or ref, "ref_why": ref_why,
        "path": dpath, "remote": remote, "current_branch": head, "branches": branches, "long_lived": long_lived,
        "tags": tag_pattern(tags), "version": version_info(d), "changelog": changelog_info(d),
        "test_command": cmd, "test_command_from": why, "language": language(d), "ci_workflows": ci,
        "files": {f: exists(d, f) for f in ("README.md", "CONTRIBUTING.md", "CLAUDE.md", "AGENTS.md", "LICENSE", ".gitignore")},
        "dirty": bool(git(dpath, "status", "--porcelain")),
        "url": https_url(remote) if remote else "",
    }
    pname = name or project_name(dpath, remote)
    questions = []
    if not remote:
        questions.append("repo.url: the repository has no origin remote; give its https URL (qargi project set %s repo.url ...)" % pname)
    if not long_lived:
        questions.append("repo.long_lived: no master, main, trunk or develop branch was found; name the branches no agent may touch")
    if not cmd:
        questions.append("test_command: no test command was recognised; name the command that runs the whole suite")
    default_model = PV.load("claude")["tiers"]["balanced"]   # a project that is not stored yet has the default provider
    roles = {}
    for r, cfg in (m.get("roles") or {}).items():
        base = cfg.get("base", "@dispatcher")
        roles[r] = {"base": base, "push": {"mode": "none"}, "model": default_model, "effort": "high" if r in ("build", "test") else "medium", "apt": [], "skills": []}
    answers = {
        "schema": 1, "project": pname, "methodology": methodology,
        "repo": {"url": https_url(remote) if remote else "https://github.com/OWNER/REPO", "path": dpath, "credential_file": "",
                 "long_lived": long_lived or ["master", "develop"]},
        "roles": roles, "memory": {"memory_store": "", "reference_store": ""}, "budget_cents": 500,
    }
    if cmd:
        answers["test_command"] = cmd
    gaps = []
    for item in m.get("scaffold") or []:
        if not exists(d, item["dest"]):
            gaps.append({"kind": "file", "what": item["dest"], "why": "the %s methodology starts a project with it" % methodology})
    for b in (m.get("branches") or {}).get("long_lived", []):
        if b not in branches and not (b == "master" and "main" in branches):
            gaps.append({"kind": "branch", "what": b, "why": "the methodology keeps a long-lived %s branch" % b})
    if found["changelog"] and not found["changelog"]["keepachangelog"]:
        gaps.append({"kind": "format", "what": found["changelog"]["file"], "why": "no '## [Unreleased]' heading: not in the Keep a Changelog format"})
    if tags and not found["tags"]["pattern"]:
        gaps.append({"kind": "tags", "what": "tags", "why": "the existing tags are not semantic versions"})
    if not ci:
        gaps.append({"kind": "ci", "what": ".github/workflows", "why": "no CI workflow was found"})
    return {"found": found, "answers": answers, "gaps": gaps, "questions": questions, "methodology": methodology}


class Refuse(Exception):
    """A precondition of adopt that does not hold: exit 2 with the message."""


def adopt_checks(answers_file, project):
    """(answers, repository directory): the stored answers of the project and the repository they name, after every refusal."""
    if MR.in_member_run():
        raise Refuse("project adopt is not available in a member run: a member never changes the branches of a repository outside its clone; the lead does")
    try:
        answers = json.load(open(answers_file))
    except (OSError, ValueError):
        raise Refuse("project %s is not attached: nothing is stored for it (qargi project attach DIR first)" % project)
    path = (answers.get("repo") or {}).get("path") or ""
    top = git(path, "rev-parse", "--show-toplevel") if path and os.path.isdir(path) else ""
    if not top:
        raise Refuse("project %s: repo.path %r is not a git repository (qargi project attach DIR --force)" % (project, path))
    top = os.path.realpath(top)
    if not git(top, "rev-parse", "--verify", "-q", "HEAD^{commit}"):
        raise Refuse("%s has no commit yet: there is no tip to create branches from" % top)
    if not git(top, "symbolic-ref", "-q", "HEAD"):
        raise Refuse("%s has a detached HEAD: check out a branch first" % top)
    if git(top, "status", "--porcelain"):
        raise Refuse("%s has uncommitted changes (or untracked files): commit, stash or remove them first" % top)
    return answers, top


def ref_sha(d, name):
    """(full ref, sha) of branch NAME: the local one, else origin's, else ('', '')."""
    for full in ("refs/heads/" + name, "refs/remotes/origin/" + name):
        sha = git(d, "rev-parse", "--verify", "-q", full + "^{commit}")
        if sha:
            return full, sha
    return "", ""


def default_branch_tip(d):
    """(name, sha) of the repository's default branch: origin's HEAD, else master, main, trunk; else the checked-out branch."""
    dflt = git(d, "symbolic-ref", "-q", "--short", "refs/remotes/origin/HEAD").replace("origin/", "", 1)
    for b in ([dflt] if dflt else []) + ["master", "main", "trunk"]:
        full, sha = ref_sha(d, b)
        if sha:
            return b, sha
    cur = git(d, "symbolic-ref", "--short", "-q", "HEAD")
    return cur, git(d, "rev-parse", "HEAD^{commit}")


def adopt_plan(project, answers_file, methodology=None):
    answers, d = adopt_checks(answers_file, project)
    methodology = methodology or answers.get("methodology") or "gitflow"
    where, md, m = M.load(methodology)
    long_lived = (m.get("branches") or {}).get("long_lived", [])
    det = detect(d, project, methodology)
    found = det["found"]
    base_name, base_sha = default_branch_tip(d)
    heads = git(d, "for-each-ref", "--format=%(refname:short) %(objectname)", "refs/heads").splitlines()

    def sha_of(b):   # the commit of a long-lived branch (local, else origin's; main stands for master), or ""
        return ref_sha(d, b)[1] or (ref_sha(d, "main")[1] if b == "master" else "")

    # a branch that exists only as origin's is present: it is never created or moved here
    branches = [{"name": b, "from": base_name, "sha": base_sha} for b in long_lived if not sha_of(b)]
    integ = long_lived[-1] if long_lived else base_name
    integ_sha = sha_of(integ) or base_sha
    adopt_branch = "agent/adopt-" + methodology
    adopt_exists = bool(git(d, "rev-parse", "--verify", "-q", "refs/heads/" + adopt_branch) or git(d, "rev-parse", "--verify", "-q", "refs/remotes/origin/" + adopt_branch))
    tree = Tree(d, integ_sha)
    lower = {p.lower() for p in tree.files | tree.dirs}
    params = {"project": project}
    if answers.get("test_command") and "test_command" in (m.get("params") or {}) and "\n" not in answers["test_command"]:
        params["test_command"] = answers["test_command"]
    versioning, ci = m.get("versioning") or {}, m.get("ci") or {}
    files, skipped = [], []
    for item in M.render(methodology, params):
        dest = item["dest"]
        parts = dest.split("/")
        prefixes = ["/".join(parts[:i]) for i in range(1, len(parts))]
        why = ""
        if tree.exists(dest):
            continue
        if any(p in tree.files for p in prefixes):
            why = "a file is in the way of its directory"
        elif dest.lower() in lower:
            why = "a path that differs only in letter case exists"
        elif dest == versioning.get("file") and found["version"]:
            why = "the version is kept in %s" % found["version"]["file"]
        elif dest == versioning.get("changelog") and found["changelog"]:
            why = "the changelog is %s" % found["changelog"]["file"]
        elif dest == ci.get("file") and found["ci_workflows"]:
            why = "CI workflows exist (%s)" % ", ".join(found["ci_workflows"])
        elif os.path.splitext(dest)[0].lower() in ("readme", "changelog", "license") and any(
                os.path.splitext(p)[0].lower() == os.path.splitext(dest)[0].lower() for p in tree.files if "/" not in p):
            why = "the same document exists under another name"
        if why:
            skipped.append({"what": dest, "why": why})
        else:
            files.append(item)
    if adopt_exists:
        files = []
    left = [g for g in det["gaps"] if g["kind"] in ("format", "tags", "ci")]
    left += [{"kind": "file", "what": x["what"], "why": "not written: " + x["why"]} for x in skipped]
    if any(f["dest"] == ci.get("file") for f in files):   # the template replaces the "no CI" gap; its content is still the owner's to judge
        left = [g for g in left if g["kind"] != "ci"] + [{"kind": "ci", "what": ci["file"], "why": "written from the template: check that its steps fit this project"}]
    basis = {
        "project": project, "methodology": methodology, "repo": d, "base": {"name": base_name, "sha": base_sha},
        "heads": sorted(heads), "integration": {"name": integ, "sha": integ_sha},
        "branches": [{"name": x["name"], "sha": x["sha"]} for x in branches], "adopt_branch": adopt_branch, "adopt_exists": adopt_exists,
        "files": [{"dest": f["dest"], "sha256": hashlib.sha256(f["content"].encode()).hexdigest()} for f in files],
    }
    return {"project": project, "methodology": methodology, "path": d, "base": basis["base"], "integration": basis["integration"],
            "branches": branches, "adopt_branch": adopt_branch, "adopt_exists": adopt_exists, "files": files, "skipped": skipped, "left": left,
            "nothing_to_do": not branches and not files, "basis": basis}


def gitw(d, *args, env=None, data=None):
    e = dict(os.environ)
    e.update(env or {})
    r = subprocess.run(["git", "-C", d] + list(args), capture_output=True, input=data, env=e)
    if r.returncode != 0:
        hint = " (is a git user.name and user.email set? nothing was created)" if args[0] == "commit-tree" else ""
        raise SystemExit("qargi: git %s failed: %s%s" % (args[0], r.stderr.decode("utf-8", "replace").strip().splitlines()[0] if r.stderr.strip() else "", hint))
    return r.stdout.decode("utf-8", "replace").strip()


def adopt_apply(project, answers_file, plan):
    answers, d = adopt_checks(answers_file, project)
    if os.path.realpath(plan["path"]) != d:
        raise SystemExit("qargi: the plan is for %s, not %s" % (plan["path"], d))
    commit = ""
    if plan["files"]:
        # the commit first (objects only): if it cannot be made (no git identity) no branch has been created yet
        idx = tempfile.mkdtemp(prefix="qargi-adopt-")
        env = {"GIT_INDEX_FILE": os.path.join(idx, "index")}
        try:
            gitw(d, "read-tree", plan["integration"]["sha"], env=env)
            for f in plan["files"]:
                blob = gitw(d, "hash-object", "-w", "--stdin", data=f["content"].encode())
                gitw(d, "update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob, f["dest"]), env=env)
            tree = gitw(d, "write-tree", env=env)
            msg = "Add the %s scaffold files that this project lacks\n\nWritten by qargi project adopt on a branch of its own, for review. Only files that\n" \
                  "did not exist were added; no existing file was changed:\n\n%s\n" % (plan["methodology"], "\n".join("  " + f["dest"] for f in plan["files"]))
            commit = gitw(d, "commit-tree", tree, "-p", plan["integration"]["sha"], "-m", msg)
        finally:
            subprocess.run(["rm", "-rf", idx])
    for b in plan["branches"]:
        gitw(d, "branch", "--no-track", b["name"], b["sha"])   # no -f: an existing branch makes this fail
    if commit:
        gitw(d, "branch", "--no-track", plan["adopt_branch"], commit)
    return {"commit": commit, "branches": [b["name"] for b in plan["branches"]]}


def main(argv):
    if argv and argv[0] in ("adopt-plan", "adopt-apply"):
        if len(argv) < 3:
            raise SystemExit("usage: attach.py %s PROJECT ANSWERS [--methodology M]" % argv[0])
        meth = None
        if len(argv) == 5 and argv[3] == "--methodology":
            meth = argv[4]
        elif len(argv) != 3:
            raise SystemExit("qargi: unknown option %s" % argv[3])
        try:
            if argv[0] == "adopt-plan":
                print(json.dumps(adopt_plan(argv[1], argv[2], meth), indent=2, sort_keys=True))
            else:
                print(json.dumps(adopt_apply(argv[1], argv[2], json.load(sys.stdin)), sort_keys=True))
        except Refuse as e:
            print("qargi: %s" % e, file=sys.stderr)
            sys.exit(2)
        return
    if len(argv) < 2 or argv[0] != "detect":
        raise SystemExit("usage: attach.py detect DIR [--name N] [--methodology M]")
    d, name, meth, i = argv[1], None, "gitflow", 2
    while i < len(argv):
        if argv[i] == "--name" and i + 1 < len(argv):
            name, i = argv[i + 1], i + 2
        elif argv[i] == "--methodology" and i + 1 < len(argv):
            meth, i = argv[i + 1], i + 2
        else:
            raise SystemExit("qargi: unknown option %s" % argv[i])
    print(json.dumps(detect(d, name, meth), indent=2, sort_keys=True))


if __name__ == "__main__":
    main(sys.argv[1:])
