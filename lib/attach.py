#!/usr/bin/env python3
"""Attach qargi to an existing repository without changing it.

  attach.py detect DIR [--name N] [--methodology M]    print JSON: what was found, the draft answers, the gaps, the questions

It only reads DIR (files and `git` queries). The draft answers are what `qargi project init` would store; the gaps are what
the chosen methodology has that the repository lacks (adopting them is a separate, reviewed change); the questions are the
facts it could not determine. Nothing is written here, and nothing about the project goes into its repository.
"""
import json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
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


def main(argv):
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
