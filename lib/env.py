#!/usr/bin/env python3
"""qargi env: what a repository declares about its development environment, read from files it already has.

qargi defines no file format for this. A project declares its environment with
  - a section of AGENTS.md (or README.md) headed "Development environment", "Environment" or "Setup";
  - version pins in the standard files (go.mod, .tool-versions, mise.toml [tools], .python-version, .nvmrc,
    package.json engines) and .gitmodules for submodules;
  - two conventional runnable targets in its task runner (make, just, task or mise): `bootstrap` (install or update,
    idempotent) and `doctor` (check only). A fallback name is accepted: `setup` for bootstrap, `check` for doctor.
The project's answers (outside the repository) may override the commands derived from them:
  env.doctor_command, env.bootstrap_command, env.dry_run_command (one line each) and env.known_failures (a list of
  strings: doctor lines the owner accepts on this host).

  env.py show [--project P] [--repo DIR] [--json]    print what was detected and the commands in effect
  env.py check [--project P] [--repo DIR] [--timeout SECONDS] [--json]    run the doctor, add the qargi layer, print the verdict (lib/env_check.py)

Detection (show) only reads files. Nothing is executed (make, just, task and mise are never run; their files are parsed
as text), and no git command is run. A file that is a symbolic link leaving the repository, is not a regular file or
is larger than 1 MB is not read. check runs the doctor command and reads the qargi layer: see lib/env_check.py.
plan and apply are lead-only verbs of this group and are not built yet.

As a module: detect(repo) -> dict, effective(repo, answers) -> dict (detection plus the answers' overrides, the
form the later check, plan and apply verbs read), problems(env_answers) -> list of messages (project validation).
"""
import json, os, re, stat, sys, tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

CAP = 1024 * 1024                         # bytes read from any one file
LEAD_ONLY = ("plan", "apply")             # verbs of this group that only the lead will run; the member guard refuses them when they exist
KEYS = ("doctor_command", "bootstrap_command", "dry_run_command", "known_failures")
SECTION_FILES = ("AGENTS.md", "README.md")
SECTION_HEADING = re.compile(r"(?:development |dev )?(?:environment|setup)(?: setup)?")
PIN_FILES = ("go.mod", ".tool-versions", "mise.toml", ".mise.toml", ".python-version", ".nvmrc", "package.json")
VENDOR_FILES = (".devcontainer/devcontainer.json", ".devcontainer.json", "devcontainer.json", ".github/copilot-setup-steps.yml",
                ".github/workflows/copilot-setup-steps.yml", ".cursor/environment.json")
RUNNER_FILES = (("make", ("GNUmakefile", "makefile", "Makefile")), ("just", ("justfile", "Justfile", ".justfile")),
                ("task", ("Taskfile.yml", "Taskfile.yaml", "taskfile.yml", "taskfile.yaml")), ("mise", ("mise.toml", ".mise.toml")))
# runner -> (command for a target, the dry run of it). mise: `mise run --dry-run` prints the tasks in the order they would run
COMMAND = {"make": ("make {t}", "make -n {t}"), "just": ("just {t}", "just --dry-run {t}"),
           "task": ("task {t}", "task --dry {t}"), "mise": ("mise run {t}", "mise run --dry-run {t}")}
WANTED = {"bootstrap": ("bootstrap", "setup"), "doctor": ("doctor", "check")}
TARGET_NAME = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./:+-]{0,63}")
MAX_TARGETS = 200


def clean(v, n=200):
    """Text from a file made safe to print: control and format characters become ?, the length is cut."""
    s = "".join(c if c.isprintable() else "?" for c in str(v))
    return s if len(s) <= n else s[:n - 1] + "…"


class Repo:
    """Reads files below one directory. A path that resolves outside it, a file that is not a regular file and one over CAP are not read."""

    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.refused, self.notes = [], []

    def real(self, rel):
        """The resolved path of rel when it exists below the repository, else None (a link leaving it is recorded as refused)."""
        full = os.path.join(self.root, rel)
        if not os.path.lexists(full):
            return None
        real = os.path.realpath(full)
        if real != self.root and not real.startswith(self.root + os.sep):
            self.refused.append({"file": rel, "why": "a symbolic link that leaves the repository"})
            return None
        return real

    def present(self, rel):
        real = self.real(rel)
        return real is not None and os.path.isfile(real)

    def read(self, rel):
        real = self.real(rel)
        if real is None:
            return None
        try:
            st = os.stat(real)
            if not stat.S_ISREG(st.st_mode):
                return None
            if st.st_size > CAP:
                self.notes.append("%s is larger than %d KB: not read" % (rel, CAP // 1024))
                return None
            fd = os.open(real, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as f:
                data = f.read(CAP + 1)
        except OSError as e:
            self.notes.append("%s could not be read: %s" % (rel, e.strerror or "error"))
            return None
        return data.decode("utf-8", "replace")

    def first(self, names):
        """(name, text) of the first of names that is read, else (None, None)."""
        for n in names:
            t = self.read(n)
            if t is not None:
                return n, t
        return None, None


def section(repo):
    """{file, heading, line, level, mentions} of the first heading in AGENTS.md, else README.md, that names the environment; else None."""
    for fn in SECTION_FILES:
        text = repo.read(fn)
        if text is None:
            continue
        lines, fence = text.splitlines(), None
        for i, ln in enumerate(lines):
            m = re.match(r"^ {0,3}(`{3,}|~{3,})", ln)
            if m:
                fence = None if fence and ln.strip().startswith(fence[0] * len(fence)) else (fence or m.group(1))
                continue
            if fence:
                continue
            h = re.match(r"^ {0,3}(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$", ln)
            if not h:
                continue
            words = " ".join(re.sub(r"[`*_]", "", h.group(2)).lower().split())
            if not SECTION_HEADING.fullmatch(words):
                continue
            level, body = len(h.group(1)), []
            for ln2 in lines[i + 1:]:
                h2 = re.match(r"^ {0,3}(#{1,6})[ \t]+\S", ln2)
                if h2 and len(h2.group(1)) <= level:
                    break
                body.append(ln2)
            text_body = "\n".join(body).lower()
            mentions = [t for names in WANTED.values() for t in names[:1] if re.search(r"\b%s\b" % t, text_body)]
            return {"file": fn, "heading": clean(h.group(2).strip(), 80), "line": i + 1, "level": level, "mentions": mentions}
    return None


def pins(repo):
    out = []

    def add(f, tool, version):
        v = clean(version, 80).strip()
        if v:
            out.append({"file": f, "tool": clean(tool, 40), "version": v})

    t = repo.read("go.mod")
    if t is not None:
        for ln in t.splitlines():
            m = re.match(r"^\s*(go|toolchain)\s+(\S+)", ln)
            if m:
                add("go.mod", m.group(1), m.group(2))
    t = repo.read(".tool-versions")
    if t is not None:
        for ln in t.splitlines():
            w = ln.split("#", 1)[0].split()
            if len(w) >= 2:
                add(".tool-versions", w[0], " ".join(w[1:]))
    for fn in ("mise.toml", ".mise.toml"):
        d = toml(repo, fn)
        tools = d.get("tools") if isinstance(d.get("tools"), dict) else {}
        for tool, v in tools.items():
            if isinstance(v, dict):
                v = v.get("version", "")
            add(fn, tool, ", ".join(str(x) for x in v) if isinstance(v, list) else v)
    for fn, tool in ((".python-version", "python"), (".nvmrc", "node")):
        t = repo.read(fn)
        if t is not None:
            first = next((ln.strip() for ln in t.splitlines() if ln.strip() and not ln.lstrip().startswith("#")), "")
            add(fn, tool, first)
    t = repo.read("package.json")
    if t is not None:
        try:
            eng = json.loads(t).get("engines")
        except (ValueError, AttributeError):
            repo.notes.append("package.json is not valid JSON: engines not read")
            eng = None
        for tool, v in (eng.items() if isinstance(eng, dict) else []):
            if isinstance(v, str):
                add("package.json", tool, v)
    return out


def toml(repo, rel):
    t = repo.read(rel)
    if t is None:
        return {}
    try:
        d = tomllib.loads(t)
    except tomllib.TOMLDecodeError:
        repo.notes.append("%s is not valid TOML: not read" % rel)
        return {}
    return d


def redact(url):
    return re.sub(r"^([a-z+]+://)[^/@\s]*@", r"\1", url)


def submodules(repo):
    t = repo.read(".gitmodules")
    out, cur = [], None
    for ln in (t or "").splitlines():
        m = re.match(r'^\s*\[submodule\s+"([^"]*)"\s*\]', ln)
        if m:
            cur = {"name": clean(m.group(1), 80), "path": "", "url": ""}
            out.append(cur)
            continue
        m = re.match(r"^\s*(path|url)\s*=\s*(.*?)\s*$", ln)
        if m and cur is not None:
            cur[m.group(1)] = clean(redact(m.group(2)) if m.group(1) == "url" else m.group(2), 200)
    return out


def make_targets(text):
    names = []
    rx = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_./+-]*(?:[ \t]+[A-Za-z0-9_][A-Za-z0-9_./+-]*)*)[ \t]*:{1,2}(?![=:])")
    for ln in text.splitlines():
        m = rx.match(ln)
        if m:
            names += [n for n in m.group(1).split() if n not in names]
    return names


def just_recipes(text):
    names = []
    rx = re.compile(r"""^@?([A-Za-z_][A-Za-z0-9_-]*)(?:[ \t]+[+*$]?[A-Za-z_][A-Za-z0-9_-]*(?:=(?:"[^"]*"|'[^']*'|`[^`]*`|[^\s:]+))?)*[ \t]*:(?!=)""")
    for ln in text.splitlines():
        m = rx.match(ln)
        if m and m.group(1) not in ("set", "alias", "export", "import", "mod", "unexport") and m.group(1) not in names:
            names.append(m.group(1))
    return names


def task_names(text):
    """The keys one level below `tasks:` of a Taskfile, found by indentation (no YAML parser is used)."""
    names, lines, inside, indent = [], text.splitlines(), False, None
    for ln in lines:
        if not ln.strip() or ln.lstrip().startswith("#"):
            continue
        if not inside:
            inside = re.match(r"^tasks\s*:\s*(#.*)?$", ln) is not None
            continue
        ind = len(ln) - len(ln.lstrip(" "))
        if ind == 0:
            break
        if indent is None:
            indent = ind
        if ind != indent:
            continue
        m = re.match(r"""^ +(?:"([^"]+)"|'([^']+)'|([A-Za-z0-9_][A-Za-z0-9_.:-]*))\s*:""", ln)
        if m:
            n = next(g for g in m.groups() if g)
            if n not in names:
                names.append(n)
    return names


def runners(repo):
    out = []
    for runner, files in RUNNER_FILES:
        for fn in files:
            text = repo.read(fn)
            if text is None:
                continue
            if runner == "mise":
                tasks = toml(repo, fn).get("tasks")
                if not isinstance(tasks, dict):
                    continue                   # a mise file with no [tasks] is a pin file only, not a runner
                names = list(tasks)
            else:
                names = {"make": make_targets, "just": just_recipes, "task": task_names}[runner](text)
            out.append({"runner": runner, "file": fn, "targets": [n for n in names if TARGET_NAME.fullmatch(n)][:MAX_TARGETS]})
            if runner == "make" and re.search(r"(?m)^-?(?:include|sinclude)\s", text):
                repo.notes.append("%s includes other files: targets defined there are not seen" % fn)
            break
    return out


def pick_targets(rs):
    """{bootstrap, doctor}: the first runner (make, just, task, mise) that has the target, preferring the primary name to its fallback."""
    out = {}
    for role, names in WANTED.items():
        out[role] = None
        for n in names:
            hit = next((r for r in rs if n in r["targets"]), None)
            if hit:
                out[role] = {"name": n, "runner": hit["runner"], "file": hit["file"], "fallback": n != names[0]}
                break
    return out


def derive(tg):
    cmds = {"doctor_command": None, "bootstrap_command": None, "dry_run_command": None}
    from shlex import quote
    if tg["doctor"]:
        cmds["doctor_command"] = COMMAND[tg["doctor"]["runner"]][0].format(t=quote(tg["doctor"]["name"]))
    if tg["bootstrap"]:
        cmds["bootstrap_command"] = COMMAND[tg["bootstrap"]["runner"]][0].format(t=quote(tg["bootstrap"]["name"]))
        cmds["dry_run_command"] = COMMAND[tg["bootstrap"]["runner"]][1].format(t=quote(tg["bootstrap"]["name"]))
    return cmds


def detect(repo_dir):
    """What the repository declares. Reads files only; the answers are not consulted (see effective)."""
    repo = Repo(repo_dir)
    rs = runners(repo)
    tg = pick_targets(rs)
    d = {"repo": repo.root, "section": section(repo), "pins": pins(repo), "submodules": submodules(repo), "runners": rs,
         "runner": (tg["bootstrap"] or tg["doctor"] or (rs[0] if rs else None) or {}).get("runner"),
         "targets": tg, "vendor_files": [f for f in VENDOR_FILES if repo.present(f)], "commands": {}}
    for k, v in derive(tg).items():
        role = "doctor" if k.startswith("doctor") else "bootstrap"
        d["commands"][k] = {"command": v, "source": ("detected: %s %s %s" % (tg[role]["file"], "target" if tg[role]["runner"] != "just" else "recipe", tg[role]["name"])) if v else None}
    d["known_failures"] = []
    d["gaps"] = [g for g, missing in (("no section headed Development environment, Environment or Setup in AGENTS.md or README.md", not d["section"]),
                                      ("no bootstrap target (bootstrap or setup) in a Makefile, justfile, Taskfile or mise.toml", not tg["bootstrap"]),
                                      ("no doctor target (doctor or check) in a Makefile, justfile, Taskfile or mise.toml", not tg["doctor"])) if missing]
    d["refused"], d["notes"] = repo.refused, repo.notes
    return d


def problems(e):
    """Messages for an env object of the project's answers that is not valid (project validation prints them)."""
    if not isinstance(e, dict):
        return ["env: an object with %s" % ", ".join(KEYS)]
    bad = ["env.%s: unknown key (%s)" % (k, ", ".join(KEYS)) for k in e if k not in KEYS]
    for k in KEYS[:3]:
        if k in e:
            v = e[k]
            if not (isinstance(v, str) and v.strip() and len(v) <= 500 and all(c.isprintable() for c in v)):
                bad.append("env.%s: one line of printable text, at most 500 characters" % k)
    if "known_failures" in e:
        v = e["known_failures"]
        if not (isinstance(v, list) and len(v) <= 100 and all(isinstance(x, str) and x.strip() and len(x) <= 300 and all(c.isprintable() for c in x) for x in v)):
            bad.append("env.known_failures: a list of at most 100 one-line strings (doctor lines accepted on this host)")
    return bad


def effective(repo_dir, answers=None):
    """detect(repo_dir) with the answers' env overrides applied: a command in env.* wins over the detected one."""
    d = detect(repo_dir)
    e = (answers or {}).get("env")
    if isinstance(e, dict) and not problems(e):
        for k in KEYS[:3]:
            if e.get(k):
                d["commands"][k] = {"command": e[k], "source": "answers: env.%s" % k}
        d["known_failures"] = list(e.get("known_failures") or [])
    elif e is not None:
        d["notes"].append("env in the project's answers is not valid and is ignored: " + "; ".join(problems(e)))
    return d


def render(d, project):
    L = ["environment of %s (%s)" % (project or "no stored project", d["repo"])]

    def row(label, text):
        L.append("%-15s%s" % (label + ":", text))

    s = d["section"]
    row("section", "%s, \"%s\" (line %d)%s" % (s["file"], s["heading"], s["line"], ", names " + " and ".join(s["mentions"]) if s["mentions"] else "") if s else "none")
    row("pins", "; ".join("%s %s %s" % (p["file"], p["tool"], p["version"]) for p in d["pins"]) or "none")
    row("submodules", ", ".join(m["path"] or m["name"] for m in d["submodules"]) or "none")
    conventional = sum(WANTED.values(), ())
    row("runner", ", ".join("%s (%s: %s)" % (r["runner"], r["file"], ", ".join(t for t in r["targets"] if t in conventional) or "no conventional target") for r in d["runners"]) or "none")
    for k, label in (("bootstrap_command", "bootstrap"), ("doctor_command", "doctor"), ("dry_run_command", "dry run")):
        c = d["commands"][k]
        row(label, "%s   [%s]" % (c["command"], c["source"]) if c["command"] else "none")
    row("known failures", "%d (env.known_failures)" % len(d["known_failures"]) if d["known_failures"] else "none")
    for f in d["known_failures"]:
        L.append("  " + clean(f, 120))
    row("vendor files", ", ".join(d["vendor_files"]) or "none")
    for r in d["refused"]:
        row("refused", "%s (%s)" % (r["file"], r["why"]))
    for n in d["notes"]:
        row("note", n)
    for g in d["gaps"]:
        row("gap", g)
    return "\n".join(L)


def project_for_dir(path):
    """The stored project whose repo.path contains path (the longest match), else None."""
    here, best, blen = os.path.realpath(path), None, -1
    try:
        names = sorted(os.listdir(os.path.join(P.conf(), "projects")))
    except OSError:
        return None
    for fn in names:
        a = answers_of(fn[:-5]) if fn.endswith(".json") else None
        rp = ((a or {}).get("repo") or {}).get("path")
        rp = os.path.realpath(os.path.expanduser(rp)) if isinstance(rp, str) and rp else ""
        if rp and (here == rp or here.startswith(rp + os.sep)) and len(rp) > blen:
            best, blen = fn[:-5], len(rp)
    return best


def answers_of(name):
    try:
        with open(os.path.join(P.conf(), "projects", name + ".json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def repo_root_of(path):
    """The directory above path (itself included) that holds a .git entry, else path."""
    d = os.path.realpath(path)
    while True:
        if os.path.lexists(os.path.join(d, ".git")):
            return d
        up = os.path.dirname(d)
        if up == d:
            return os.path.realpath(path)
        d = up


def show(argv):
    project = repo = None
    as_json = False
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--project", "--repo") and i + 1 < len(argv):
            if a == "--project":
                project = argv[i + 1]
            else:
                repo = argv[i + 1]
            i += 2
        elif a == "--json":
            as_json = True
            i += 1
        else:
            print("usage: qargi env show [--project P] [--repo DIR] [--json]", file=sys.stderr)
            return 2
    answers = None
    if project is not None:
        answers = answers_of(project)
        if answers is None:
            print("qargi: no such project '%s' (qargi project list)" % project, file=sys.stderr)
            return 2
    elif repo is None:
        project = os.environ.get("QARGI_PROJECT") or project_for_dir(os.getcwd())
        answers = answers_of(project) if project else None
        project = project if answers is not None else None
    else:
        project = project_for_dir(repo)
        answers = answers_of(project) if project else None
    if repo is None:
        rp = ((answers or {}).get("repo") or {}).get("path") or ""
        if project is not None and not rp:
            print("qargi: project %s has no repo.path; give --repo DIR" % project, file=sys.stderr)
            return 2
        repo = os.path.expanduser(rp) if rp else repo_root_of(os.getcwd())
    if not os.path.isdir(repo):
        print("qargi: %s is not a directory" % repo, file=sys.stderr)
        return 2
    d = effective(repo, answers)
    d["project"] = project
    print(json.dumps(d, indent=2, sort_keys=True) if as_json else render(d, project))
    return 0


def main(argv):
    if argv[:1] and argv[0] in LEAD_ONLY:
        print("qargi env %s is not built yet; it will be run by the lead only" % argv[0], file=sys.stderr)
        return 2
    if argv[:1] == ["show"]:
        return show(argv[1:])
    if argv[:1] == ["check"]:
        import env_check                       # runs the doctor and reads the qargi layer; kept in its own file
        return env_check.check(argv[1:])
    print("usage: env.py show|check [--project P] [--repo DIR] [--json]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
