#!/usr/bin/env python3
"""qargi discover: find, recommend and install tools for the roles of a project.

  discover.py sources
  discover.py search QUERY [--kind K] [--role R] [--online]
  discover.py recommend [PROJECT] [--role R] [--online]
  discover.py show ID
  discover.py install ID [--scope S] [--project P] [--role R] [--dry-run]

A tool is a skill, an MCP server, a package for the sandbox or a built-in tool of the agent. The catalog
(catalog/tools.json, reviewed with the repository) is searched first, then the local library, then, with
--online, the official MCP registry and Anthropic's skills repository. Installing never skips a gate: a skill or
an MCP server goes through `qargi skill|tool import` (the review, then your approval of exactly that content),
is linked at the scope you choose, and may be applied to existing cloud agents (`qargi packs apply`, again with
its plan shown first). Nothing found online is installed on trust.
"""
import datetime, getpass, glob, json, os, re, subprocess, sys, tempfile, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOG = os.environ.get("QARGI_CATALOG") or os.path.join(ROOT, "catalog", "tools.json")
CONF = os.environ.get("QARGI_CONF") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "qargi")
STATE = os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")
AGENT_FILE = os.environ.get("QARGI_AGENT_FILE") or os.path.join(ROOT, "agents", "qargi-agent.md")
QARGI = os.path.join(ROOT, "bin", "qargi")
TTY_IN = os.environ.get("QARGI_TTY_IN", "/dev/tty")
TTY_OUT = os.environ.get("QARGI_TTY_OUT", "/dev/tty")
KINDS = ("skill", "mcp", "package", "agent-tool")
LEVELS = {"necessary": 3, "recommended": 2, "optional": 1}
SCOPES = ("user", "user-role", "project", "project-role")
MCP_REGISTRY = "https://registry.modelcontextprotocol.io/v0/servers"
SKILLS_API = "https://api.github.com/repos/anthropics/skills/contents/skills"
SKILLS_URL = "https://github.com/anthropics/skills"


def F(name):
    return "--" + name


def die(msg, code=1):
    print("qargi: " + msg, file=sys.stderr)
    raise SystemExit(code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# --- terminal ------------------------------------------------------------------------------------------------------
_t = None


def tty():
    global _t
    if _t is None:
        try:
            _t = (open(TTY_IN), open(TTY_OUT, "w"))
        except OSError:
            _t = (None, None)
    return _t


def interactive():
    return bool(tty()[0])


def ask(prompt, default=""):
    tin, tout = tty()
    if not tin:
        die("install is interactive: run it in a terminal (from Claude Code: ! qargi discover install ...), or use --dry-run")
    tout.write(prompt + (" [%s] " % default if default else " "))
    tout.flush()
    line = tin.readline()
    if line == "":
        die("no answer; nothing more was changed")
    return line.strip() or default


def confirm(prompt):
    return ask(prompt + " [y/N]").lower() in ("y", "yes")


def choose(prompt, options, default):
    got = ask(prompt, default)
    if got.isdigit() and 0 < int(got) <= len(options):
        return options[int(got) - 1]
    if got not in options:
        die("'%s' is not one of: %s" % (got, ", ".join(options)))
    return got


# --- catalog and sources -------------------------------------------------------------------------------------------
def load_catalog():
    data = jload(CATALOG, None)
    if data is None:
        die("cannot read the catalog %s" % CATALOG)
    items = data["tools"] if isinstance(data, dict) else data
    for e in items:
        e.setdefault("source", "catalog")
        e.setdefault("tags", [])
        e.setdefault("roles", {})
        e.setdefault("stack", [])
        e.setdefault("risk", "low")
    return items


def library_entries():
    out = []
    base = os.path.join(CONF, "packs")
    for p in sorted(glob.glob(os.path.join(base, "skills", "*"))):
        n = os.path.basename(p)
        out.append({"id": "library:skill:" + n, "kind": "skill", "name": n, "summary": "in your library already", "tags": [], "roles": {}, "stack": [], "risk": "low", "source": "library", "installed": True})
    for p in sorted(glob.glob(os.path.join(base, "tools", "*.json"))):
        n = os.path.basename(p)[:-5]
        out.append({"id": "library:tool:" + n, "kind": "mcp", "name": n, "summary": "in your library already", "tags": [], "roles": {}, "stack": [], "risk": "low", "source": "library", "installed": True})
    return out


def fetch(url):
    try:
        r = subprocess.run(["curl", "-sS", "-m", "15", "-L", "-H", "Accept: application/json", url], capture_output=True, text=True, timeout=25)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except ValueError:
        return None


def online_entries(query):
    """Entries from the official MCP registry and Anthropic's skills; (entries, notes)."""
    out, notes = [], []
    q = (query or "").strip()
    data = fetch("%s?search=%s&limit=15" % (MCP_REGISTRY, urllib.parse.quote(q))) if q else None
    if q and data is None:
        notes.append("the MCP registry could not be reached")
    for s in (data or {}).get("servers", []):
        sv = s.get("server", {})
        remotes = sv.get("remotes") or []
        need_secret = any(h.get("isSecret") for r in remotes for h in (r.get("headers") or []))
        out.append({"id": "mcp-registry:" + sv.get("name", "?"), "kind": "mcp", "name": sv.get("name", "?"), "summary": (sv.get("description") or "")[:140],
                    "tags": [], "roles": {}, "stack": [], "risk": "high" if need_secret else "medium", "source": "mcp-registry",
                    "risk_note": "found online, not reviewed by qargi; the registry does not list the server's tools, so you must write the allowlist yourself",
                    "install": {"name": re.sub(r"[^a-z0-9-]+", "-", sv.get("name", "x").lower()).strip("-")[:40], "url": (remotes[0].get("url") if remotes else ""),
                                "tools": {}, "needs_secret": need_secret, "repository": (sv.get("repository") or {}).get("url", "")}})
    listing = fetch(SKILLS_API)
    if listing is None:
        notes.append("Anthropic's skills repository could not be listed")
    for d in listing or []:
        if d.get("type") == "dir" and (not q or q.lower() in d["name"].lower()):
            out.append({"id": "anthropic-skills:" + d["name"], "kind": "skill", "name": d["name"], "summary": "Anthropic skill (found online, not reviewed by qargi)",
                        "tags": [], "roles": {}, "stack": [], "risk": "medium", "source": "anthropic-skills",
                        "install": {"url": SKILLS_URL, "path": "skills/" + d["name"], "name": d["name"]}})
    return out, notes


def score(e, words):
    if not words:
        return 1
    hay = {"id": e["id"].lower(), "name": e["name"].lower(), "summary": e.get("summary", "").lower(), "tags": " ".join(e.get("tags", [])).lower()}
    s = 0
    for w in words:
        w = w.lower()
        if w == e["name"].lower() or w == e["id"].lower():
            s += 10
        s += 4 * (w in hay["name"]) + 3 * (w in hay["tags"]) + 2 * (w in hay["id"]) + (w in hay["summary"])
    return s


def find_entry(ident, online=False):
    for e in load_catalog() + library_entries():
        if e["id"] == ident:
            return e
    if ident.startswith(("mcp-registry:", "anthropic-skills:")):
        name = ident.split(":", 1)[1]
        got, _ = online_entries(name.split("/")[-1])
        for e in got:
            if e["id"] == ident:
                return e
    return None


# --- the project and what it already has -------------------------------------------------------------------------
def project_names():
    return sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(CONF, "projects", "*.json")))


def project_answers(p):
    return jload(os.path.join(CONF, "projects", p + ".json"), {})


def infer_project():
    p = os.environ.get("QARGI_PROJECT")
    if p:
        return p
    here = os.path.realpath(os.getcwd())
    best, blen = None, -1
    for n in project_names():
        rp = (project_answers(n).get("repo") or {}).get("path") or ""
        if rp:
            rp = os.path.realpath(os.path.expanduser(rp))
            if (here == rp or here.startswith(rp + os.sep)) and len(rp) > blen:
                best, blen = n, len(rp)
    return best


def detect_stack(answers):
    path = os.path.expanduser((answers.get("repo") or {}).get("path") or "")
    stack = []
    if not path or not os.path.isdir(path):
        return stack
    has = lambda *names: any(os.path.exists(os.path.join(path, n)) for n in names)
    if has("go.mod"): stack.append("go")
    if has("pyproject.toml", "setup.py", "requirements.txt"): stack.append("python")
    if has("package.json"): stack.append("node")
    if has("Cargo.toml"): stack.append("rust")
    if has("Gemfile", "_config.yml", "site/_config.yml"): stack.append("jekyll")
    if has("tests/bats", "test/bats") or glob.glob(os.path.join(path, "**", "*.bats"), recursive=True)[:1]: stack.append("bats")
    if has("Dockerfile", "Containerfile", "tests/containers"): stack.append("containers")
    if has(".github/workflows"): stack.append("actions")
    if has("man"): stack.append("man")
    if glob.glob(os.path.join(path, "**", "*.sh"), recursive=True)[:1]: stack.append("shell")
    return stack


def run_q(args, extra_env=None):
    env = dict(os.environ, **(extra_env or {}))
    env.pop("QARGI_NESTED", None)
    r = subprocess.run([QARGI] + args, capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stdout + r.stderr)


def already_has(e, project, role):
    answers = project_answers(project)
    if e["kind"] in ("skill", "mcp"):
        name = (e.get("install") or {}).get("name") or e["name"]
        rc, out = run_q(["skill" if e["kind"] == "skill" else "tool", "effective", project, role])
        return rc == 0 and name in out.split()
    if e["kind"] == "package":
        have = set((answers.get("roles", {}).get(role) or {}).get("apt") or [])
        return all(p in have for p in (e.get("install") or {}).get("packages", []))
    if e["kind"] == "agent-tool":
        try:
            head = open(AGENT_FILE).read().split("---")[1]
        except (OSError, IndexError):
            return False
        m = re.search(r"(?m)^tools:\s*(.*)$", head)
        return bool(m) and (e.get("install") or {}).get("tool") in [t.strip() for t in m.group(1).split(",")]
    return False


# --- commands ------------------------------------------------------------------------------------------------------
def show_row(e, extra=""):
    return "%-30s %-10s %-8s %s%s" % (e["id"], e["kind"], e.get("risk", ""), (e.get("summary") or "")[:70], extra)


def cmd_sources(args):
    cat = load_catalog()
    print("Sources searched, in this order:")
    print("  catalog           %d reviewed entries (%s)" % (len(cat), os.path.relpath(CATALOG, ROOT) if CATALOG.startswith(ROOT) else CATALOG))
    print("  library           %d pack(s) you already imported" % len(library_entries()))
    print("  mcp-registry      %s   (with --online)" % MCP_REGISTRY)
    print("  anthropic-skills  %s   (with --online)" % SKILLS_URL)
    print("Online results are never installed on trust: install shows the review of the content and asks first.")
    return 0


def cmd_search(args):
    query, kind, role, online = [], None, None, False
    i = 0
    while i < len(args):
        a = args[i]
        if a == F("kind"): kind = args[i + 1]; i += 2
        elif a == F("role"): role = args[i + 1]; i += 2
        elif a == F("online"): online = True; i += 1
        elif a.startswith("-"): die("unknown option %s (qargi help discover search)" % a)
        else: query.append(a); i += 1
    if kind and kind not in KINDS:
        die("--kind is one of: %s" % ", ".join(KINDS))
    words = [w for q in query for w in q.split()]
    pool = load_catalog() + library_entries()
    notes = []
    if online:
        got, notes = online_entries(" ".join(words))
        pool += got
    rows = []
    for e in pool:
        if kind and e["kind"] != kind:
            continue
        if role and role not in e.get("roles", {}) and e["source"] == "catalog":
            continue
        s = score(e, words)
        if s > 0:
            rows.append((s, e))
    rows.sort(key=lambda r: (-r[0], r[1]["id"]))
    if not rows:
        print("Nothing found for '%s'.%s" % (" ".join(words), "" if online else " Try --online to search the MCP registry and Anthropic's skills."))
    for s, e in rows[:40]:
        print(show_row(e, "  [installed]" if e.get("installed") else ""))
    for n in notes:
        print("note: " + n, file=sys.stderr)
    if rows:
        print("\nDetails: qargi discover show ID    Install: qargi discover install ID")
    return 0


def cmd_recommend(args):
    project, role = None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == F("role"): role = args[i + 1]; i += 2
        elif a.startswith("-"): die("unknown option %s (qargi help discover recommend)" % a)
        else: project = a; i += 1
    project = project or infer_project()
    if not project or project not in project_names():
        die("which project? Give its name or run this inside its repository (projects: %s)" % (", ".join(project_names()) or "none stored"))
    answers = project_answers(project)
    roles = [role] if role else [r for r in list((answers.get("roles") or {})) + (["lead"] if answers.get("teams") else [])]
    stack = detect_stack(answers)
    print("Project %s; stack seen in the repository: %s" % (project, ", ".join(stack) or "nothing detected"))
    cat = load_catalog()
    shown = 0
    for r in roles:
        rows = []
        for e in cat:
            lv = e.get("roles", {}).get(r)
            if not lv:
                continue
            if e.get("stack") and not set(e["stack"]) & set(stack):
                continue   # fits other repositories than this one
            s = LEVELS.get(lv, 1) * 10 + 3 * len(set(e.get("stack", [])) & set(stack))
            rows.append((s, lv, e, already_has(e, project, r)))
        rows.sort(key=lambda x: (-x[0], x[2]["id"]))
        print("\n== %s" % r)
        for s, lv, e, have in rows:
            print("  %-18s %s" % (lv + (" (have)" if have else ""), show_row(e)))
            shown += 1
        if not rows:
            print("  nothing to add")
    if shown:
        print("\nInstall one: qargi discover install ID --project %s --role ROLE" % project)
    return 0


def cmd_show(args):
    if not args:
        die("show needs an ID (qargi discover search ...)")
    e = find_entry(args[0])
    if not e:
        die("no entry '%s' (search the catalog, or --online, first)" % args[0])
    print("%s  (%s, from %s)" % (e["id"], e["kind"], e["source"]))
    print("  %s" % e.get("summary", ""))
    if e.get("roles"):
        print("  roles: " + ", ".join("%s=%s" % kv for kv in sorted(e["roles"].items())))
    if e.get("stack"):
        print("  fits: " + ", ".join(e["stack"]))
    print("  risk: %s%s" % (e.get("risk", "?"), (" - " + e["risk_note"]) if e.get("risk_note") else ""))
    for k, v in sorted((e.get("install") or {}).items()):
        print("  install.%s: %s" % (k, json.dumps(v) if not isinstance(v, str) else v))
    if e.get("verify"):
        print("  verify: " + e["verify"])
    if e.get("scope_hint"):
        print("  suggested scope: %s" % e["scope_hint"])
    return 0


# --- install -------------------------------------------------------------------------------------------------------
def pick_scope(e, opts, project, role):
    hint = e.get("scope_hint") or ("project-role" if role else "project")
    scope = opts.get("scope")
    if not scope:
        tout = tty()[1]
        tout.write("\nWhere should it reach?\n  1) user          every role of every project\n  2) user-role     this role of every project\n"
                   "  3) project       every role of one project\n  4) project-role  one role of one project\n")
        scope = choose("Scope? (name or number)", list(SCOPES), hint)
    if scope in ("project", "project-role") and not project:
        project = choose("Which project? (%s)" % ", ".join(project_names()), project_names(), infer_project() or (project_names() or [""])[0])
    if scope in ("user-role", "project-role") and not role:
        answers = project_answers(project) if project else {}
        roles = list((answers.get("roles") or {})) or ["dev", "docs", "review", "test"]
        role = choose("Which role? (%s)" % ", ".join(roles), roles, "dev")
    return scope, project, role


def approval():
    return "interactive: confirmed at the terminal by %s at %s" % (getpass.getuser(), now())


def step_import(kind, source_args, name):
    """Run `qargi skill|tool import`, show the review, ask, then store exactly that content."""
    rc, out = run_q([kind, "import"] + source_args)
    print(out.rstrip())
    m = re.search(r"plan token: ([0-9a-f]+)", out)
    if rc != 0 or not m:
        die("the import was refused or failed; nothing was stored")
    if not confirm("\nI read the review above. Store exactly this content in your library?"):
        print("Not stored. Nothing changed.")
        return False
    rc, out = run_q([kind, "import"] + source_args + [F("plan"), m.group(1), F("approved"), approval()])
    print(out.rstrip())
    return rc == 0


def cmd_install(args):
    ident, opts, dry = None, {}, False
    i = 0
    while i < len(args):
        a = args[i]
        if a in (F("scope"), F("project"), F("role")): opts[a[2:]] = args[i + 1]; i += 2
        elif a == F("dry-run"): dry = True; i += 1
        elif a.startswith("-"): die("unknown option %s (qargi help discover install)" % a)
        elif ident is None: ident = a; i += 1
        else: die("one ID at a time")
    if not ident:
        die("install needs an ID (qargi discover search ...)")
    e = find_entry(ident)
    if not e:
        die("no entry '%s' (search first; online entries are found with: qargi discover search QUERY --online)" % ident)
    if e.get("installed"):
        die("%s is in your library already: link it with: qargi skill|tool link NAME --scope S" % ident)
    inst = e.get("install") or {}
    print("Install %s (%s, risk %s)" % (e["id"], e["kind"], e.get("risk", "?")))
    print("  " + (e.get("summary") or ""))
    if e.get("risk_note"):
        print("  risk: " + e["risk_note"])
    if dry:
        print("\nPlan: %s" % {"skill": "import the skill (review, your approval), link it at the scope you choose, offer to apply it to the cloud agents it reaches",
                              "mcp": "write the server as a tool pack (review, your approval), link it at the scope you choose, offer to apply it",
                              "package": "add the package(s) to the role's apt list in the project answers (the environment is rebuilt by qargi provision)",
                              "agent-tool": "add the tool to the tools line of the local agent definition"}[e["kind"]])
        print("(dry run: nothing changed)")
        return 0
    if not interactive():
        die("install is interactive: run it in a terminal (from Claude Code: ! qargi discover install %s), or use --dry-run" % ident)
    if not confirm("\nContinue?"):
        print("Nothing changed.")
        return 1
    kind = e["kind"]
    if kind in ("skill", "mcp"):
        packkind = "skill" if kind == "skill" else "tool"
        name = inst.get("name") or e["name"]
        tmp = None
        if kind == "skill":
            src = [inst["url"]] if "url" in inst else [inst["dir"]]
            if inst.get("path"): src += [F("path"), inst["path"]]
            if inst.get("ref"): src += [F("ref"), inst["ref"]]
            src += [F("name"), name]
        else:
            if not inst.get("tools"):
                out = os.path.join(os.getcwd(), name + ".tool.json")
                with open(out, "w") as f:
                    json.dump({"name": name, "url": inst.get("url", ""), "vault_ids": [], "tools": {"REPLACE_WITH_A_TOOL_NAME": "always_ask"}}, f, indent=2)
                print("\nqargi does not know which tools this server exposes, and a tool pack must list them, each with a policy.")
                print("Wrote a draft: %s" % out)
                print("Edit it (the server's tool names; write-like tools stay always_ask; credentials are vault ids, never secrets), then:")
                print("  qargi tool import %s" % out)
                print("  qargi tool link %s --scope S [--project P] [--role R]" % name)
                if inst.get("needs_secret"):
                    print("It needs a credential: create a vault credential for it first (qargi help credential).")
                return 0
            tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
            json.dump({"name": name, "url": inst["url"], "vault_ids": inst.get("vault_ids", []), "tools": inst["tools"], **({"write_ok": True} if inst.get("write_ok") else {})}, tmp, indent=2)
            tmp.close()
            src = [tmp.name, F("name"), name]
        try:
            if not step_import(packkind, src, name):
                return 1
        finally:
            if tmp:
                os.unlink(tmp.name)
        scope, project, role = pick_scope(e, opts, opts.get("project"), opts.get("role"))
        largs = [packkind, "link", name, F("scope"), scope] + ([F("project"), project] if scope in ("project", "project-role") else []) + ([F("role"), role] if scope in ("user-role", "project-role") else [])
        rc, out = run_q(largs)
        print(out.rstrip())
        if rc != 0:
            return 1
        if project and role:
            apply_to_cloud(project, role, scope)
        return 0
    if kind == "package":
        project = opts.get("project") or choose("Which project? (%s)" % ", ".join(project_names()), project_names(), infer_project() or (project_names() or [""])[0])
        answers = project_answers(project)
        roles = list((answers.get("roles") or {}))
        role = opts.get("role") or choose("Which role's sandbox? (%s)" % ", ".join(roles), roles, "dev")
        cur = list(((answers.get("roles") or {}).get(role) or {}).get("apt") or [])
        new = cur + [p for p in inst.get("packages", []) if p not in cur]
        print("\nroles.%s.apt: %s -> %s" % (role, json.dumps(cur), json.dumps(new)))
        if new == cur:
            print("Already there. Nothing changed.")
            return 0
        if not confirm("Write it to the project answers?"):
            print("Nothing changed.")
            return 1
        rc, out = run_q(["project", "set", project, "roles.%s.apt" % role, json.dumps(new)])
        print(out.rstrip())
        if rc == 0:
            print("The sandbox is rebuilt when the instance is provisioned or its environment changed: qargi provision plan %s-%s" % (project, role))
        return rc
    if kind == "agent-tool":
        tool = inst["tool"]
        try:
            text = open(AGENT_FILE).read()
        except OSError:
            die("cannot read %s" % AGENT_FILE)
        m = re.search(r"(?m)^(tools:\s*)(.*)$", text)
        if not m:
            die("the agent definition has no tools line: %s" % AGENT_FILE)
        cur = [t.strip() for t in m.group(2).split(",") if t.strip()]
        if tool in cur:
            print("The local agent has %s already. Nothing changed." % tool)
            return 0
        new = cur + [tool]
        print("\n%s\n  tools: %s\n       -> %s" % (AGENT_FILE, ", ".join(cur), ", ".join(new)))
        print("This changes what every local qargi agent may call (the git wrapper and `qargi local verify` still apply).")
        if not confirm("Edit the file?"):
            print("Nothing changed.")
            return 1
        with open(AGENT_FILE, "w") as f:
            f.write(text[:m.start(2)] + ", ".join(new) + text[m.end(2):])
        print("Done. Commit it in the qargi repository; new local agents get the tool.")
        return 0
    die("cannot install a '%s' entry" % kind)


def apply_to_cloud(project, role, scope):
    """Offer `qargi packs apply` for the cloud instances the link reaches (plan shown first, then asked)."""
    inst = jload(os.path.join(CONF, "instances.json"), {})
    names = sorted(n for n, v in inst.items() if v.get("location") == "cloud" and n.endswith("-" + role) and (scope in ("user", "user-role") or n.startswith(project + "-")))
    for n in names:
        if not confirm("\nApply it to the existing cloud agent %s now? (shows the plan first)" % n):
            print("Later: qargi packs apply %s --asked \"...\"" % n)
            continue
        asked = "interactive: qargi discover install, confirmed at the terminal"
        rc, out = run_q(["packs", "apply", n, F("asked"), asked])
        print(out.rstrip())
        m = re.search(r"plan token: ([0-9a-f]+)", out)
        if rc == 0 and m and confirm("Apply exactly this plan?"):
            rc, out = run_q(["packs", "apply", n, F("asked"), asked, F("plan"), m.group(1), F("approved"), approval()])
            print(out.rstrip())


def main(argv):
    if not argv:
        print("usage: discover.py sources|search|recommend|show|install ...", file=sys.stderr)
        return 2
    v, rest = argv[0], argv[1:]
    fn = {"sources": cmd_sources, "search": cmd_search, "recommend": cmd_recommend, "show": cmd_show, "install": cmd_install}.get(v)
    if not fn:
        print("qargi: unknown discover verb '%s' (qargi help discover)" % v, file=sys.stderr)
        return 2
    return fn(rest)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
