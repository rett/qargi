#!/usr/bin/env python3
"""qargi help, the manual page and the completion candidates, all from lib/commands.py.

  help.py show [ARGS...]      qargi help, qargi help COMMAND [VERB], qargi help TOPIC, qargi COMMAND --help
  help.py man                 the manual page (roff) on stdout
  help.py complete WORDS...   completion candidates for the last word (qargi __complete, used by the bash completion)
"""
import glob, json, os, shutil, subprocess, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import commands as C  # noqa: E402
import paths as P  # noqa: E402

ROOT = os.path.dirname(HERE)
BOLD = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def conf():
    return P.conf()


def state():
    return P.state()


def b(s):
    return "\033[1m%s\033[0m" % s if BOLD else s


def width():
    return max(60, min(100, shutil.get_terminal_size((100, 24)).columns))


def wrap(text, indent=0, first=None):
    pad = " " * indent
    return textwrap.fill(text, width() , initial_indent=(first if first is not None else pad), subsequent_indent=pad)


def load_json(path):
    with open(path) as f:
        return json.load(f)


def version():
    try:
        with open(os.path.join(ROOT, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "0"


def verbs_of(cmd):
    v = C.COMMANDS[cmd].get("verbs")
    return v if isinstance(v, dict) else None


def kind(t):
    """The family of a value type: 'session:active' is a session, 'project:teams' a project."""
    return t.split(":")[0] if isinstance(t, str) else t


def argstr(args):
    out = []
    for a in args:
        name, optional = a[0], (a[2] if len(a) > 2 else False)
        implied = kind(a[1]) == "project" and not optional   # filled in from the current directory (see infer_project)
        out.append("[%s]" % name if (optional or implied) else name)
    return " ".join(out)


def has_project_arg(args):
    return any(kind(a[1]) == "project" and not (a[2] if len(a) > 2 else False) for a in args)


def optstr(o):
    return o["flag"] + (" " + o["arg"] if o["arg"] else "")


def usage_lines(cmd):
    spec = C.COMMANDS[cmd]
    vs = verbs_of(cmd)
    if vs:
        return ["qargi %s %s%s" % (cmd, v, (" " + argstr(vs[v]["args"])) if vs[v]["args"] else "") + (" [OPTIONS]" if vs[v]["opts"] else "") for v in vs]
    args = spec.get("usage", [])
    return ["qargi %s%s%s" % (cmd, (" " + argstr(args)) if args else "", " [OPTIONS]" if spec.get("opts") else "")]


def opts_block(opts, indent):
    lines = []
    w = max([len(optstr(o)) for o in opts] + [0]) + 2
    for o in opts:
        left = optstr(o).ljust(w)
        lines.append(textwrap.fill(o["help"], width(), initial_indent=" " * indent + left, subsequent_indent=" " * (indent + w)))
    return lines


def show_overview():
    out = [b("qargi") + " - " + C.TAGLINE, "", wrap(C.INTRO), "", "Usage: qargi COMMAND [VERB] [ARGUMENTS]     qargi help COMMAND", ""]
    w = max(len(c) for _, cs in C.GROUPS for c in cs) + 2
    for title, cmds in C.GROUPS:
        out.append(b(title))
        for c in cmds:
            out.append(textwrap.fill(C.COMMANDS[c]["summary"], width(), initial_indent="  " + c.ljust(w), subsequent_indent="  " + " " * w))
        out.append("")
    out.append(b("Topics") + "  (qargi help TOPIC)")
    tw = max(len(t) for t in C.TOPICS) + 2
    for t, (title, _) in C.TOPICS.items():
        out.append("  " + t.ljust(tw) + title)
    out += ["", b("Typical use"), ]
    for title, lines in C.WORKFLOW:
        out.append("  " + title)
        out += ["    " + l for l in lines]
    out += ["", "A cloud verb needs --asked \"<your request>\"; a change to shared resources prints a plan and needs --plan and --approved (qargi help approvals).",
            "Manual page: qargi help --man | man -l -        Completion: see the README."]
    return "\n".join(out)


def show_command(cmd, verb=None):
    spec = C.COMMANDS[cmd]
    vs = verbs_of(cmd)
    out = [b("qargi %s" % cmd) + " - " + spec["summary"], ""]
    if verb:
        if not vs or verb not in vs:
            return None
        v = vs[verb]
        out += ["Usage:", "  " + usage_lines(cmd)[list(vs).index(verb)], "", wrap(v["summary"] + ".")]
        if v["desc"]:
            out += ["", wrap(v["desc"])]
        if has_project_arg(v["args"]):
            out += ["", wrap("PROJECT can be left out inside the project's repository, or set QARGI_PROJECT.")]
        if v["opts"]:
            out += ["", "Options:"] + opts_block(v["opts"], 2)
        if v["examples"]:
            out += ["", "Examples:"] + ["  " + e for e in v["examples"]]
        return "\n".join(out)
    out += ["Usage:"] + ["  " + l for l in usage_lines(cmd)]
    if spec.get("desc"):
        out += ["", wrap(spec["desc"])]
    if vs:
        out += ["", "Verbs:"]
        w = max(len(v) for v in vs) + 2
        for v, vd in vs.items():
            left = ("  " + v).ljust(w + 2)
            out.append(textwrap.fill(vd["summary"], width(), initial_indent=left, subsequent_indent=" " * (w + 2)))
        out += ["", "qargi help %s VERB  shows a verb's arguments and options." % cmd]
        allopts = []
        for vd in vs.values():
            for o in vd["opts"]:
                if o["flag"] not in [x["flag"] for x in allopts]:
                    allopts.append(o)
        ex = [e for vd in vs.values() for e in vd["examples"]]
    else:
        allopts = spec.get("opts", [])
        ex = spec.get("examples", [])
        if allopts:
            out += ["", "Options:"] + opts_block(allopts, 2)
    if ex:
        out += ["", "Examples:"] + ["  " + e for e in ex]
    return "\n".join(out)


def show_topic(t):
    title, paras = C.TOPICS[t]
    return "\n\n".join([b(title)] + [wrap(p) for p in paras])


def show(args):
    args = [a for a in args if a not in ("-h", "--help")]
    if args and args[0] == "--man":
        sys.stdout.write(man())
        return 0
    if not args:
        print(show_overview())
        return 0
    name = args[0]
    if name in C.TOPICS:
        print(show_topic(name))
        return 0
    if name in C.COMMANDS:
        txt = show_command(name, args[1] if len(args) > 1 else None)
        if txt is None:
            print("qargi %s has no verb '%s'. Verbs: %s" % (name, args[1], ", ".join(verbs_of(name) or [])), file=sys.stderr)
            return 2
        print(txt)
        return 0
    print("qargi: no command or topic '%s'.\nCommands: %s\nTopics: %s" % (name, ", ".join(sorted(C.COMMANDS)), ", ".join(C.TOPICS)), file=sys.stderr)
    return 2


# ------------------------------------------------------------------ manual page
def esc(s):
    s = s.replace("\\", "\\e").replace("-", "\\-")
    return ("\\&" + s) if s.startswith((".", "'")) else s


def man():
    o = []
    w = o.append
    w('.TH QARGI 1 "" "qargi %s"' % version())
    w(".SH NAME")
    w("qargi \\- " + esc(C.TAGLINE.rstrip(".")))
    w(".SH SYNOPSIS")
    w(".B qargi")
    w(".I command")
    w("[\\fIverb\\fR] [\\fIarguments\\fR]")
    w(".br")
    w(".B qargi help")
    w("[\\fIcommand\\fR|\\fItopic\\fR]")
    w(".SH DESCRIPTION")
    w(esc(C.INTRO))
    w(".PP")
    w("Every command takes \\fB\\-\\-help\\fR. A command that changes shared resources prints a plan and applies it only with "
      "\\fB\\-\\-plan\\fR and \\fB\\-\\-approved\\fR; a cloud command needs \\fB\\-\\-asked\\fR. See APPROVALS.")
    for t in ("concepts", "approvals", "naming", "memory", "push"):
        title, paras = C.TOPICS[t]
        w(".SH " + t.upper())
        for i, p in enumerate(paras):
            w(".PP" if i else "")
            w(esc(p))
    w(".SH COMMANDS")
    for title, cmds in C.GROUPS:
        w(".SS " + esc(title))
        for c in cmds:
            spec = C.COMMANDS[c]
            vs = verbs_of(c)
            w(".TP")
            w(".B qargi %s" % esc(c))
            w(esc(spec["summary"] + "."))
            if spec.get("desc"):
                w(".PP")
                w(esc(spec["desc"]))
            if vs:
                for v, vd in vs.items():
                    w(".RS")
                    w(".TP")
                    w('.BI "%s " "%s"' % (esc(v), esc(argstr(vd["args"]))) if vd["args"] else ".B " + esc(v))
                    w(esc(vd["summary"] + "."))
                    if vd["desc"]:
                        w(".br")
                        w(esc(vd["desc"]))
                    for op in vd["opts"]:
                        w(".RS")
                        w(".TP")
                        w('.BI "%s " "%s"' % (esc(op["flag"]), esc(op["arg"])) if op["arg"] else ".B " + esc(op["flag"]))
                        w(esc(op["help"] + "."))
                        w(".RE")
                    w(".RE")
            else:
                args = spec.get("usage", [])
                if args:
                    w(".RS")
                    w(".nf")
                    w(esc("qargi %s %s" % (c, argstr(args))))
                    w(".fi")
                    w(".RE")
                for op in spec.get("opts", []):
                    w(".RS")
                    w(".TP")
                    w('.BI "%s " "%s"' % (esc(op["flag"]), esc(op["arg"])) if op["arg"] else ".B " + esc(op["flag"]))
                    w(esc(op["help"] + "."))
                    w(".RE")
    w(".SH EXAMPLES")
    for title, lines in C.WORKFLOW:
        w(".PP")
        w(esc(title + ":"))
        w(".nf")
        for l in lines:
            w(esc("    " + l))
        w(".fi")
    w(".SH FILES")
    for p, d in C.FILES:
        w(".TP")
        w(".I " + esc(p))
        w(esc(d + "."))
    w(".SH ENVIRONMENT")
    for k, d in C.ENVIRONMENT:
        w(".TP")
        w(".B " + k)
        w(esc(d + "."))
    w(".SH EXIT STATUS")
    w("0 on success. 1 when a check fails or a command is refused (the message says why). 2 for a usage error.")
    w(".SH SEE ALSO")
    w("The skills qargi\\-task, qargi\\-team, qargi\\-project, qargi\\-instances, qargi\\-provision, qargi\\-memory, qargi\\-packs "
      "and qargi\\-verify in Claude Code, and the ability skills qargi\\-build, qargi\\-write, qargi\\-review and qargi\\-test "
      "(qargi help roles).")
    return "\n".join(x for x in o if x != "") + "\n"


# ------------------------------------------------------------------ completion
def _read(path):
    try:
        return load_json(path)
    except (OSError, ValueError):
        return {}


def project_data(words):
    """The stored answers of the project named among the words, else of the one the directory implies."""
    for w in words:
        f = os.path.join(conf(), "projects", w + ".json")
        if w and not w.startswith("-") and os.path.isfile(f):
            return _read(f)
    p = infer_project()
    return _read(os.path.join(conf(), "projects", p + ".json")) if p else {}


def money(cents):
    try:
        return "$%.2f" % (int(cents) / 100)
    except (TypeError, ValueError):
        return ""


def projects(teams_only=False):
    out = []
    for f in sorted(glob.glob(os.path.join(conf(), "projects", "*.json"))):
        d = _read(f)
        if teams_only and not d.get("teams"):
            continue
        out.append((os.path.basename(f)[:-5], (d.get("repo") or {}).get("url", "")))
    return out


def instances(cloud_only=False):
    out = []
    for n, v in sorted(_read(os.path.join(conf(), "instances.json")).items()):
        loc = v.get("location", "")
        if cloud_only and loc == "local":
            continue
        ag = v.get("agent") or {}
        model = ag.get("model", "") + ("/" + ag["effort"] if ag.get("model") and ag.get("effort") else "")
        out.append((n, " ".join(x for x in (loc, "agent v%s" % ag["version_pinned"] if ag.get("version_pinned") else "", model) if x)))
    return out


def sessions(want=""):
    """Tracked sessions, narrowed to the ones the verb can act on: active (not archived), running (not idle),
    idle, uncollected (outputs not downloaded yet)."""
    out = []
    for sid, v in sorted(_read(os.path.join(state(), "sessions.json")).items()):
        st = v.get("status", "")
        opened = not v.get("closed_at") and st != "archived"
        ok = {"": True, "active": opened, "running": opened and st != "idle", "idle": opened and st == "idle",
              "uncollected": opened and v.get("outputs_collected") in (False, None)}.get(want, True)
        if ok:
            out.append((sid, " ".join(x for x in (v.get("instance", ""), st, v.get("label", ""), money(v.get("list_cost"))) if x)))
    return out


def packs(words):
    lib, out = os.path.join(conf(), "packs"), []
    if not words or words[0] != "tool":
        out += [(os.path.basename(p), "skill") for p in sorted(glob.glob(os.path.join(lib, "skills", "*")))]
    if not words or words[0] != "skill":
        out += [(os.path.basename(p)[:-5], "tool") for p in sorted(glob.glob(os.path.join(lib, "tools", "*.json")))]
    return out


def roles_of(words):
    d = project_data(words)
    have = list((d.get("roles") or {}))
    if d.get("teams") or not have:
        have.append("lead")
    have = [r for r in C.ROLES if r in have] + sorted(r for r in have if r not in C.ROLES) or list(C.ROLES)
    return [(r, "%s/%s" % ((d.get("roles") or {}).get(r, {}).get("model", ""), (d.get("roles") or {}).get(r, {}).get("effort", "")) if (d.get("roles") or {}).get(r) else "") for r in have]


def work_roles():
    """The roles a task can have: the built-in ones, then yours (no lead)."""
    mine = os.path.join(conf(), "roles")
    own = sorted(n for n in (os.listdir(mine) if os.path.isdir(mine) else []) if n not in C.ABILITIES and n != "lead" and os.path.isfile(os.path.join(mine, n, "role.json")))
    return [(r, "") for r in list(C.ABILITIES) + own]


def stores():
    seen = {}
    for n, v in sorted(_read(os.path.join(conf(), "instances.json")).items()):
        for r in v.get("resources") or []:
            sid = r.get("memory_store_id")
            if sid and sid not in seen:
                seen[sid] = "%s, %s" % (n.rsplit("-", 1)[0], "reference" if r.get("access") == "read_only" else "memory")
    return list(seen.items())


def deployments():
    return [(v["deployment_id"], n) for n, v in sorted(_read(os.path.join(conf(), "instances.json")).items()) if v.get("deployment_id")]


def models():
    seen = {m: "" for m in C.MODELS}
    for v in _read(os.path.join(conf(), "instances.json")).values():
        m = (v.get("agent") or {}).get("model")
        if m:
            seen.setdefault(m, "")
    return list(seen.items())


def branches(words):
    path = os.path.expanduser((project_data(words).get("repo") or {}).get("path") or os.getcwd())
    try:
        r = subprocess.run(["git", "-C", path, "for-each-ref", "--format=%(refname:short)", "refs/heads", "refs/remotes/origin"],
                           capture_output=True, text=True, timeout=3, stdin=subprocess.DEVNULL, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return []
    names_ = []
    for b in r.stdout.split():
        b = b[len("origin/"):] if b.startswith("origin/") else b
        if b not in ("HEAD", "origin") and b not in names_:
            names_.append(b)
    return [(b, "") for b in names_]


FIELD_VALUES = {"effort": C.EFFORTS, "model": C.MODELS, "local": ("true", "false"), "cloud": ("none", "branches"),
                "merge": ("ask", "never"), "release": ("ask", "never"), "mode": ("none",)}
# answers a project may hold that are not there yet, so a key can be typed before it exists
EXTRA_KEYS = ("lead.model", "lead.effort", "lead.push.local", "lead.push.cloud", "lead.push.branch_pattern", "lead.push.merge",
              "lead.push.release", "budget_cents") + tuple("roles.%s.%s" % (r, k) for r in C.ROLES[:-1] for k in ("model", "effort", "base", "apt", "skills", "push.mode"))


def flatten(d, prefix=""):
    """The dotted paths of a project's answers down to a scalar, a list or an empty object."""
    out = {}
    for k, v in d.items():
        p = prefix + k
        if isinstance(v, dict) and v:
            out.update(flatten(v, p + "."))
        else:
            out[p] = v
    return out


def keys(words):
    flat = flatten(project_data(words))
    out = {}
    for k in sorted(set(flat) | set(EXTRA_KEYS)):
        v = flat.get(k)
        out[k] = ("now %s" % json.dumps(v)) if isinstance(v, (bool, int)) else ("a list" if isinstance(v, list) else "")
    return list(out.items())


def values(words):
    key = words[-1] if words else ""
    cur = flatten(project_data(words[:-1])).get(key)
    last = key.rsplit(".", 1)[-1]
    if last in FIELD_VALUES:
        return [(v, "") for v in FIELD_VALUES[last]]
    if isinstance(cur, bool):
        return [("true", ""), ("false", "")]
    return []


def by_type(t, words):
    """Candidates for a value of type t, as (candidate, description). The words before the cursor give the context."""
    if isinstance(t, tuple):
        return [(x, "") for x in t]
    base, _, sub = t.partition(":")
    if base == "project":
        return projects(sub == "teams")
    if base == "instance":
        return instances(sub == "cloud")
    if base == "session":
        return sessions(sub)
    if base == "target":
        return sessions() + instances(True)
    if base == "pack":
        return packs(words)
    if base == "member":
        return [(n, ",".join(v.get("abilities") or [])) for n, v in sorted(_read(os.path.join(conf(), "agents.json")).items())]
    if base == "team":
        return [(n, ", ".join(v.get("members", []))) for n, v in sorted((project_data(words).get("teams") or {}).items())]
    if base == "role":
        return roles_of(words)
    if base == "workrole":
        return work_roles()
    if base == "store":
        return stores()
    if base == "deployment":
        return deployments()
    if base == "model":
        return models()
    if base == "branch":
        return branches(words)
    if base == "key":
        return keys(words)
    if base == "value":
        return values(words)
    if base == "seconds":
        return [(s, d) for s, d in (("600", "10 minutes"), ("1800", "30 minutes"), ("3600", "1 hour"), ("7200", "2 hours, the default"))]
    if base == "cents":
        return [(c, money(c)) for c in ("500", "1000", "1500", "3000")]
    if base == "entry":
        try:
            with open(os.environ.get("QARGI_CATALOG") or os.path.join(ROOT, "catalog", "tools.json")) as f:
                data = json.load(f)
            return [(e["id"], e.get("summary", "")[:60]) for e in (data["tools"] if isinstance(data, dict) else data)]
        except (OSError, ValueError, KeyError):
            return []
    if base == "help":
        return [(c, C.COMMANDS[c]["summary"]) for c in sorted(C.COMMANDS)] + [(k, v[0]) for k, v in C.TOPICS.items()]
    if base == "file":
        return [("@file", "")]
    if base == "dir":
        return [("@dir", "")]
    return []


def names(what, words=()):
    """The plain names of one kind (used by resolve)."""
    return [n for n, _ in by_type(what, list(words))]


def complete(words):
    """The candidates for the last word, as plain strings."""
    return [c for c, _ in complete_described(words)]


HELP_FLAG = ("--help", "show this help")


def complete_described(words):
    cur, prev = words[-1], list(words[:-1])
    eq = ""
    if cur.startswith("--") and "=" in cur:   # --option=value: complete the value, give the whole word back
        flag, cur = cur.split("=", 1)
        eq, prev = flag + "=", prev + [flag]
    out = _candidates(cur, prev)
    return [(eq + c, d) for c, d in out] if eq else out


def _candidates(cur, prev):
    if not prev:
        return [(c, C.COMMANDS[c]["summary"]) for c in sorted(C.COMMANDS)] if not cur.startswith("-") else [HELP_FLAG]
    if prev[0] == "help":
        if len(prev) == 1:
            return by_type("help", prev)
        vs = verbs_of(prev[1]) if prev[1] in C.COMMANDS else None
        return [(v, vs[v]["summary"]) for v in vs] if vs and len(prev) == 2 else []
    if prev[0] not in C.COMMANDS:
        return []
    spec = C.COMMANDS[prev[0]]
    vs = verbs_of(prev[0])
    if vs:
        if len(prev) == 1:
            return [(v, vs[v]["summary"]) for v in vs] + ([HELP_FLAG] if cur.startswith("-") else [])
        vspec = vs.get(prev[1])
        if not vspec:
            return []
        args, opts, rest = vspec["args"], vspec["opts"], prev[2:]
    else:
        args = [tuple(a) for a in spec.get("usage", [])]
        opts, rest = spec.get("opts", []), prev[1:]
    flags = {o["flag"]: o for o in opts}
    pos, used, i = 0, set(), 0
    while i < len(rest):
        t = rest[i]
        name, inline = (t.split("=", 1)[0], True) if t.startswith("--") and "=" in t else (t, False)
        if name.startswith("-") and name in flags:
            used.add(name)
            if flags[name]["arg"] and not inline and i + 1 >= len(rest):
                return by_type(flags[name]["type"], prev)
            i += 2 if flags[name]["arg"] and not inline else 1
        else:
            pos += 1
            i += 1
    free = [(f, flags[f]["help"]) for f in flags if f not in used] + [HELP_FLAG]
    if cur.startswith("-"):
        return free
    if pos < len(args):
        return by_type(args[pos][1], prev)
    return free


def infer_project():
    """The project in effect: QARGI_PROJECT, else the one whose repository (repo.path in its answers) contains
    the current directory (the longest match), else None."""
    p = os.environ.get("QARGI_PROJECT")
    if p:
        return p
    here, best, blen = os.path.realpath(os.getcwd()), None, -1
    for f in glob.glob(os.path.join(conf(), "projects", "*.json")):
        try:
            rp = load_json(f).get("repo", {}).get("path") or ""
        except (OSError, ValueError):
            continue
        if not rp:
            continue
        rp = os.path.realpath(os.path.expanduser(rp))
        if (here == rp or here.startswith(rp + os.sep)) and len(rp) > blen:
            best, blen = os.path.basename(f)[:-5], len(rp)
    return best


def resolve(argv):
    """Fill in what the current directory implies: a missing PROJECT argument, and a role used as an instance
    (build -> PROJECT-build). An argument you give always wins. Returns the argument list to run."""
    if not argv or argv[0] not in C.COMMANDS or argv[0] in ("help", "version"):
        return argv
    P = infer_project()
    cmd, rest = argv[0], argv[1:]
    vs = verbs_of(cmd)
    if vs:
        if not rest or rest[0] not in vs:
            return argv
        head, args, opts, body = [cmd, rest[0]], vs[rest[0]]["args"], vs[rest[0]]["opts"], rest[1:]
    else:
        head, args, opts, body = [cmd], [tuple(a) for a in C.COMMANDS[cmd].get("usage", [])], C.COMMANDS[cmd].get("opts", []), rest
    flags = {o["flag"]: o for o in opts}
    pos, i = [], 0
    while i < len(body):
        t = body[i]
        if t.startswith("-"):
            i += 2 if (t in flags and flags[t]["arg"]) else 1
            continue
        pos.append(i)
        i += 1
    out = list(body)
    insts = names("instance")
    for k, a in enumerate(args):
        if kind(a[1]) == "instance" and k < len(pos) and out[pos[k]] not in insts and out[pos[k]] in C.ROLES:
            out[pos[k]] = "%s-%s" % (P, out[pos[k]])
    required = [k for k, a in enumerate(args) if not (a[2] if len(a) > 2 else False)]
    pk = next((k for k in required if kind(args[k][1]) == "project"), None)
    if not P:
        if pk is not None and len(pos) < len(required) and not (pk < len(pos) and os.path.exists(os.path.join(conf(), "projects", body[pos[pk]] + ".json"))) \
                and not any(t in ("-h", "--help") for t in body):
            have = names("project")
            print("qargi: which project? Give its name, run this inside its repository, or set QARGI_PROJECT.%s" %
                  ((" Projects: " + ", ".join(have)) if have else " No project is stored yet: qargi help project."), file=sys.stderr)
            return None
        return argv
    if pk is not None and len(pos) < len(required):
        given = pk < len(pos) and os.path.exists(os.path.join(conf(), "projects", out[pos[pk]] + ".json"))
        if not given:
            out.insert(pos[pk] if pk < len(pos) else (pos[-1] + 1 if pos else 0), P)
    if cmd == "provision" and head[1] in ("plan", "apply") and not pos and "--project" not in body:
        out = ["--project", P] + out
    return head + out


def main(argv):
    if not argv:
        return show([])
    if argv[0] == "infer":
        print(infer_project() or "")
        return 0
    if argv[0] == "resolve":
        r = resolve(argv[1:])
        if r is None:
            return 2
        sys.stdout.write("".join(a + "\0" for a in r))
        return 0
    if argv[0] == "show":
        return show(argv[1:])
    if argv[0] == "man":
        sys.stdout.write(man())
        return 0
    if argv[0] == "complete":
        words = argv[1:]
        described = bool(words) and words[0] == "--described"   # candidate TAB description, for zsh and fish
        words = (words[1:] if described else words) or [""]
        if described:
            print("\n".join(c + ("\t" + d if d else "") for c, d in complete_described(words)))
        else:
            print("\n".join(complete(words)))
        return 0
    print("usage: help.py show|man|complete ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
