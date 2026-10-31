#!/usr/bin/env python3
"""qargi cloud: which `ant` profile and workspace each project uses. The binding is the optional `cloud` answer of a project
({"profile": "qargi", "workspace_id": "wrkspc_..."}), stored with the other answers. The dispatcher (bin/qargi) reads it and
exports ANTHROPIC_PROFILE for the command it runs, so every `ant` call, shell or Python, uses the project's profile; before a
cloud call lib.sh checks that the profile still reaches the workspace named here. A project without a binding is unchanged:
`ant` uses its active profile.

qargi stores and checks bindings. It never reads, copies or writes a token: the login is yours (`qargi cloud login`
runs `ant auth login` on your terminal, and only there).

Usage: cloud.py list
       cloud.py show [PROJECT]
       cloud.py set PROJECT --profile NAME --workspace-id ID
       cloud.py unset PROJECT
       cloud.py check [PROJECT]          the profile exists and reaches the workspace (local; one `ant profile` read)
       cloud.py login PROJECT            log the project's profile in, bound to its workspace (needs a terminal)
       cloud.py for-args WORDS...        (dispatcher) prints project, profile, workspace id, one per line"""
import glob, json, os, re, subprocess, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

PROFILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")
ANT_NO_BROWSER = "-" * 2 + "no" + "-browser"        # ant's flag, not qargi's (the help check reads quoted flags as qargi's)
WORKSPACE = re.compile(r"^wrkspc_[A-Za-z0-9]{10,}$")


def die(msg, code=1):
    print("qargi: %s" % msg, file=sys.stderr)
    sys.exit(code)


def pfile(project):
    return os.path.join(P.conf(), "projects", project + ".json")


def projects():
    return sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(P.conf(), "projects", "*.json")))


def load(project):
    try:
        with open(pfile(project)) as f:
            return json.load(f)
    except OSError:
        die("no stored answers for %s (qargi project list)" % project)
    except ValueError as e:
        die("the answers of %s are not valid JSON: %s" % (project, e))


def binding(project):
    try:
        with open(pfile(project)) as f:
            c = (json.load(f) or {}).get("cloud")
    except (OSError, ValueError, AttributeError):
        return None
    if isinstance(c, dict) and c.get("profile") and c.get("workspace_id"):
        return {"profile": str(c["profile"]), "workspace_id": str(c["workspace_id"])}
    return None


def project_of(words):
    """The project a command is about: QARGI_PROJECT, else a stored project or an instance PROJECT-ROLE named in the words,
    else the one whose repository contains the current directory."""
    env = os.environ.get("QARGI_PROJECT")
    if env:
        return env
    have = projects()
    for w in words:
        if w in have:
            return w
    for w in words:
        for p in have:
            if w.startswith(p + "-") and w[len(p) + 1:] in ("build", "write", "review", "test", "lead"):
                return p
    import help as H  # noqa: E402
    return H.infer_project()


def ant(args, **kw):
    try:
        return subprocess.run(["ant"] + args, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60, **kw)
    except (OSError, subprocess.TimeoutExpired) as e:
        die("cannot run ant: %s" % e)


def profiles():
    r = ant(["profile", "list"])
    return [l.lstrip("* ").strip() for l in r.stdout.splitlines() if l.strip()] if r.returncode == 0 else None


def live_workspace(profile):
    r = ant(["--profile", profile, "profile", "get", "workspace_id"])
    return r.stdout.strip() if r.returncode == 0 else None


def check(project, quiet=False):
    b = binding(project)
    if not b:
        if not quiet:
            print("%s: no cloud binding (ant uses its active profile)" % project)
        return 0
    have = profiles()
    if have is None:
        msg = "cannot read the ant profiles (is ant installed?)"
    elif b["profile"] not in have:
        msg = "profile %s does not exist: qargi cloud login %s" % (b["profile"], project)
    else:
        w = live_workspace(b["profile"])
        if w == b["workspace_id"]:
            if not quiet:
                print("%s: profile %s reaches %s" % (project, b["profile"], w))
            return 0
        msg = "profile %s reaches %s, not %s: qargi cloud login %s" % (b["profile"], w or "no workspace", b["workspace_id"], project)
    print("%s: %s" % (project, msg), file=sys.stderr)
    return 1


def write(project, doc):
    path = pfile(project)
    tmp = "%s.tmp.%d" % (path, os.getpid())
    with open(tmp, "w") as f:
        json.dump(doc, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def main(argv):
    verb, rest = (argv[0], argv[1:]) if argv else ("", [])
    if verb == "for-args":
        p = project_of(rest)
        b = binding(p) if p else None
        print("%s\n%s\n%s" % (p or "", b["profile"] if b else "", b["workspace_id"] if b else ""))
        return 0
    if verb == "list":
        for p in projects():
            b = binding(p)
            print("%-16s %s" % (p, ("profile %s -> %s" % (b["profile"], b["workspace_id"])) if b else "no binding (ant's active profile)"))
        if not projects():
            print("no projects stored yet: qargi help project")
        return 0
    if verb in ("show", "check", "login", "unset", "set"):
        opts, pos, i = {}, [], 0
        while i < len(rest):
            if rest[i] in ("--profile", "--workspace-id") and i + 1 < len(rest):
                opts[rest[i]] = rest[i + 1]
                i += 2
            elif rest[i].startswith("-"):
                die("unknown option %s" % rest[i], 2)
            else:
                pos.append(rest[i])
                i += 1
        if len(pos) > 1 or (len(pos) == 0 and verb not in ("show", "check")):
            die("usage: qargi cloud %s PROJECT%s" % (verb, " --profile NAME --workspace-id ID" if verb == "set" else ""), 2)
        proj = pos[0] if pos else project_of([])
        if not proj:
            die("which project? Give its name or run this inside its repository", 2)
        doc = load(proj)
        if verb == "show":
            b = binding(proj)
            print("%s: %s" % (proj, ("profile %s, workspace %s" % (b["profile"], b["workspace_id"])) if b else "no cloud binding"))
            return 0
        if verb == "check":
            return check(proj)
        if verb == "unset":
            if "cloud" in doc:
                del doc["cloud"]
                write(proj, doc)
            print("%s: no cloud binding" % proj)
            return 0
        if verb == "set":
            prof, ws = opts.get("--profile"), opts.get("--workspace-id")
            if not prof or not ws:
                die("usage: qargi cloud set PROJECT --profile NAME --workspace-id ID", 2)
            if not PROFILE.match(prof):
                die("--profile: letters, digits, - and _ (at most 40)", 2)
            if not WORKSPACE.match(ws):
                die("--workspace-id: a workspace id such as wrkspc_01AbC... (Console, Settings, Workspaces)", 2)
            doc["cloud"] = {"profile": prof, "workspace_id": ws}
            write(proj, doc)
            print("%s: profile %s, workspace %s (qargi cloud check %s; qargi cloud login %s if the profile is new)" % (proj, prof, ws, proj, proj))
            return 0
        if verb == "login":
            b = binding(proj)
            if not b:
                die("%s has no cloud binding: qargi cloud set %s --profile NAME --workspace-id ID" % (proj, proj))
            if not (sys.stdin.isatty() and sys.stdout.isatty()):
                die("login needs your own terminal: run `qargi cloud login %s` yourself (a member or a script cannot)" % proj)
            return subprocess.call(["ant", "auth", "login", "--profile", b["profile"], "--workspace-id", b["workspace_id"], ANT_NO_BROWSER])
    die("usage: qargi cloud list|show|set|unset|check|login ...", 2)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
