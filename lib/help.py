#!/usr/bin/env python3
"""qargi help, the manual page and the completion candidates, all from lib/commands.py.

  help.py show [ARGS...]      qargi help, qargi help COMMAND [VERB], qargi help TOPIC, qargi COMMAND --help
  help.py man [--keep-date F] the manual page (roff) on stdout; its .TH date is the one in F (default man/qargi.1, else the
                              copy committed at HEAD, as `> man/qargi.1` empties the file before this runs), empty when none
  help.py complete WORDS...   completion candidates for the last word (qargi __complete, used by the bash completion)
  help.py preamble AREA ARGS  what bin/qargi does before every command, in one process: the dev-run banner on stderr, the
                              arguments resolved (below) and the project's cloud binding; see preamble()
  help.py actor-gate AREA ARGS  the narrowing of a coordinator label (QARGI_ACTOR): exit 0 to go on, 2 with the message when the label is not
                              valid or the command line is not a coordinator's; see actor_gate()
  help.py actor-parse LABEL   the feature of a coordinator label; exit 2 and the form when it is not one
  help.py actor-check KIND WHERE VALUE  the narrowing of the label at the point of use, asked by the scripts once they have resolved their target; see actor_check()

The modules a plain run does not need (text wrapping, subprocess, glob) are imported where they are used: every qargi
command runs the preamble, and its cost is the import of this module.
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import commands as C  # noqa: E402
import paths as P  # noqa: E402

ROOT = os.path.dirname(HERE)
BOLD = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
APPROVAL_GUIDANCE = ("Request, plan and approval requirements are command-specific. "
                     "See each command's help and qargi help approvals.")


def conf():
    return P.conf()


def state():
    return P.state()


def b(s):
    return "\033[1m%s\033[0m" % s if BOLD else s


def width():
    import shutil
    return max(60, min(100, shutil.get_terminal_size((100, 24)).columns))


def fill(text, width_, initial_indent, subsequent_indent):
    import textwrap
    return textwrap.fill(text, width_, initial_indent=initial_indent, subsequent_indent=subsequent_indent)


def wrap(text, indent=0, first=None):
    pad = " " * indent
    return fill(text, width(), (first if first is not None else pad), pad)


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
        lines.append(fill(o["help"], width(), " " * indent + left, " " * (indent + w)))
    return lines


def show_overview():
    out = [b("qargi") + " - " + C.TAGLINE, "", wrap(C.INTRO), "", "Usage: qargi COMMAND [VERB] [ARGUMENTS]     qargi help COMMAND", ""]
    w = max(len(c) for _, cs in C.GROUPS for c in cs) + 2
    for title, cmds in C.GROUPS:
        out.append(b(title))
        for c in cmds:
            out.append(fill(C.COMMANDS[c]["summary"], width(), "  " + c.ljust(w), "  " + " " * w))
        out.append("")
    out.append(b("Topics") + "  (qargi help TOPIC)")
    tw = max(len(t) for t in C.TOPICS) + 2
    for t, (title, _) in C.TOPICS.items():
        out.append("  " + t.ljust(tw) + title)
    out += ["", b("Typical use"), ]
    for title, lines in C.WORKFLOW:
        out.append("  " + title)
        out += ["    " + l for l in lines]
    out += ["", b("Global options") + "  (every verb)"] + opts_block(C.GLOBAL_OPTS, 2)
    out += ["", APPROVAL_GUIDANCE,
            "Manual page: qargi help --man | man -l -        Completion: see docs/reference/README.md."]
    return "\n".join(out)


def global_opts(own):
    """The options of every verb that the verb (or command) does not describe itself."""
    return [o for o in C.GLOBAL_OPTS if o["flag"] not in [x["flag"] for x in own]]


def global_opts_block(own):
    g = global_opts(own)
    return (["", "Global options:"] + opts_block(g, 2)) if g else []


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
        out += global_opts_block(v["opts"])
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
            out.append(fill(vd["summary"], width(), left, " " * (w + 2)))
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
    out += global_opts_block(allopts if vs else spec.get("opts", []))
    if ex:
        out += ["", "Examples:"] + ["  " + e for e in ex]
    return "\n".join(out)


def show_topic(t):
    title, paras = C.TOPICS[t]
    return "\n\n".join([b(title)] + [wrap(p) for p in paras])


def refusal_codes():
    """The catalogue of refusals (lib/refusals.json, read by lib/refusal.py): {code: entry}."""
    import refusal as R
    return R.load()["codes"]


def show_refusal(args):
    """qargi help refusal [CODE]: the topic and the list of the codes, or the entry of one code (rule, why, class, exit, status, fields, message, next, sites). An unknown code exits 2."""
    codes = refusal_codes()
    if not args:
        out = [show_topic("refusal"), "", b("Codes") + "  (qargi help refusal CODE)"]
        w = max(len(c) for c in codes) + 2
        for c, e in codes.items():
            out.append(fill("(%s, exit %d, %s) %s" % (e["class"], e["exit"], e["status"], e["rule"]), width(), "  " + c.ljust(w), "  " + " " * w))
        return "\n".join(out), 0
    if len(args) > 1 or args[0] not in codes:
        return "qargi: no refusal code '%s'.%s qargi help refusal lists the codes." % (" ".join(args), " One code at a time." if len(args) > 1 else ""), 2
    c, e = args[0], codes[args[0]]
    nxt = e["next"]
    out = [b(c) + "  (%s)" % e["status"], "",
           wrap("Rule: " + e["rule"].rstrip(".") + ".", 2),
           wrap("Why: " + e["why"].rstrip(".") + ".", 2),
           "  Class: %s    Exit: %d" % (e["class"], e["exit"]),
           wrap("Fields: " + (", ".join("%s (%s)" % (k, v) for k, v in e["fields"].items()) or "none"), 2),
           wrap("Message: " + e["message"], 2),
           wrap("Next, for a lead: " + nxt["lead"], 2)]
    if nxt["host"] != nxt["lead"]:
        out.append(wrap("Next, in the owner's own session (host): " + nxt["host"], 2))
    if e.get("sites"):
        n = len(e["sites"])
        out.append(wrap("Printed at %d site%s, not raised by one verb: the sentences are in docs/reference/refusals.md and, for a guard code, qargi help guard." % (n, "" if n == 1 else "s"), 2))
    return "\n".join(out), 0


def show(args):
    args = [a for a in args if a not in ("-h", "--help")]
    if args and args[0] == "--man":
        sys.stdout.write(man())
        return 0
    if not args:
        print(show_overview())
        return 0
    name = args[0]
    if name == "refusal":
        try:
            text, rc = show_refusal(args[1:])
        except (OSError, ValueError, KeyError) as e:
            print("qargi: the catalogue of refusals cannot be read (%s)" % e, file=sys.stderr)
            return 1
        print(text, file=sys.stderr if rc else sys.stdout)
        return rc
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


def th_date(text):
    """The date field of the first .TH line of a manual page, or None when the text has no .TH line with that field."""
    import re
    for line in text.split("\n"):
        if line.startswith(".TH "):
            tok = re.findall(r'"[^"]*"|\S+', line)
            return tok[3].strip('"') if len(tok) > 3 else None
    return None


def kept_date(path=None):
    """The date `qargi release start` set in the manual page, so that regenerating the page does not undo it. From PATH, else
    man/qargi.1 of the repository; the shell redirection in `help.py man > man/qargi.1` has emptied that file by the time it is
    read, so a file with no .TH line is read again from HEAD. Empty when there is no page."""
    import subprocess
    sources = [lambda: open(path or os.path.join(ROOT, "man", "qargi.1"), encoding="utf-8").read()]
    if not path:
        sources.append(lambda: subprocess.run(["git", "-C", ROOT, "show", "HEAD:man/qargi.1"], capture_output=True, text=True, check=True).stdout)
    for read in sources:
        try:
            d = th_date(read())
        except (OSError, subprocess.SubprocessError):
            continue
        if d is not None:
            return d
    return ""


def man(date_from=None):
    o = []
    w = o.append
    w('.TH QARGI 1 "%s" "qargi %s"' % (kept_date(date_from), version()))
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
    w("Every command takes \\fB\\-\\-help\\fR. " + esc(APPROVAL_GUIDANCE))
    w(".SH GLOBAL OPTIONS")
    for op in C.GLOBAL_OPTS:
        w(".TP")
        w('.BI "%s " "%s"' % (esc(op["flag"]), esc(op["arg"])) if op["arg"] else ".B " + esc(op["flag"]))
        w(esc(op["help"] + "."))
    for t in ("concepts", "approvals", "guard", "refusal", "naming", "memory-stores", "push"):
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
    w("Exit statuses are command-specific. Consult the command's help and diagnostic output for its failure and refusal statuses.")
    w(".SH SEE ALSO")
    # a copy of qargi without its skills directory (a partial copy, a packaged lib) still writes the page
    sk = os.path.join(ROOT, "skills")
    skills = sorted(n for n in os.listdir(sk) if os.path.isfile(os.path.join(sk, n, "SKILL.md"))) if os.path.isdir(sk) else []
    if len(skills) > 1:
        named = "The skills " + ", ".join(esc(n) for n in skills[:-1]) + " and " + esc(skills[-1])
    else:
        named = "The skill " + esc(skills[0]) if skills else "The qargi skills"
    w(named + ", loaded by the lead's session "
      "(qargi help roles for the roles, which come as role text with the task block).")
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


def project_files():
    """The stored answers, one file per project, in name order."""
    d = os.path.join(conf(), "projects")
    try:
        return [os.path.join(d, n) for n in sorted(os.listdir(d)) if n.endswith(".json") and not n.startswith(".")]
    except OSError:
        return []


def projects(teams_only=False):
    out = []
    for f in project_files():
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
    import glob
    lib, out = os.path.join(conf(), "packs"), []
    if not words or words[0] != "tool":
        out += [(os.path.basename(p), "skill") for p in sorted(glob.glob(os.path.join(lib, "skills", "*")))]
    if not words or words[0] != "skill":
        out += [(os.path.basename(p)[:-5], "tool") for p in sorted(glob.glob(os.path.join(lib, "tools", "*.json")))]
    return out


def members(words):
    """The members to complete: those of the project named with --project, else of the project in effect, else of every project (a name once)."""
    ps = _read(os.path.join(conf(), "agents.json")).get("projects") or {}
    named = next((words[i + 1] for i in range(len(words) - 1) if words[i] == "--project"), None) or infer_project()
    out = {}
    for p in sorted(ps) if not named else [named]:
        for n, v in sorted((ps.get(p) or {}).items()):
            out.setdefault(n, ",".join(v.get("roles") or []))
    return sorted(out.items())


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


def methodologies():
    """The methodologies, the built-in one and yours: (name, description)."""
    out = []
    for base in (os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "methodologies"), os.path.join(conf(), "methodologies")):
        for n in sorted(os.listdir(base)) if os.path.isdir(base) else []:
            f = os.path.join(base, n, "methodology.json")
            if os.path.isfile(f) and n not in [x[0] for x in out]:
                out.append((n, _read(f).get("description", "")[:60]))
    return out


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
    import subprocess
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


FIELD_VALUES = {"effort": C.EFFORTS, "local": ("true", "false"), "cloud": ("none", "branches"),
                "merge": ("ask", "never"), "release": ("ask", "never"), "mode": ("none",), "numbered": ("true", "false")}


def field_values(name):
    """The fixed words a project answer takes, by the last part of its key; a model's come from the runtime descriptors
    (C.MODELS, read on demand, not at import)."""
    return C.MODELS if name == "model" else FIELD_VALUES.get(name)
# answers a project may hold that are not there yet, so a key can be typed before it exists
EXTRA_KEYS = ("lead.model", "lead.effort", "lead.push.local", "lead.push.cloud", "lead.push.branch_pattern", "lead.push.merge",
              "lead.push.release", "lead.context_window", "lead.compact_advice_pct", "budget_cents", "test_command", "gates", "backlog.file", "release.version_file", "release.version_files", "release.changelog.unreleased", "release.changelog.released", "release.changelog.numbered", "release.changelog.fragments",
              "review.scrub", "review.trailer_policy", "review.reject_trailers", "backlog.archive", "backlog.section", "ci.not_gates", "methodology_accepted", "release.man_pages", "release.test_command", "release.preflight", "release.hotfix_preflight", "release.finish_check", "release.assets", "release.assets_command", "release.after_steps", "release.notes_file",
              "env.doctor_command", "env.bootstrap_command", "env.dry_run_command", "env.known_failures", "verify.environment") + tuple("roles.%s.%s" % (r, k) for r in C.ROLES[:-1] for k in ("model", "effort", "base", "apt", "tools", "skills", "push.mode"))


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
    vals = field_values(key.rsplit(".", 1)[-1])
    if vals:
        return [(v, "") for v in vals]
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
        return members(words)
    if base == "team":
        return [(n, ", ".join(v.get("members", []))) for n, v in sorted((project_data(words).get("teams") or {}).items())]
    if base == "role":
        return roles_of(words)
    if base == "workrole":
        return work_roles()
    if base == "methodology":
        return methodologies()
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
        if prev[1] == "refusal":
            try:
                return [(c, e["rule"]) for c, e in refusal_codes().items()] if len(prev) == 2 else []
            except (OSError, ValueError, KeyError):
                return []
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
    flags = {o["flag"]: o for o in list(opts) + global_opts(opts)}
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
    try:
        here = os.path.realpath(os.getcwd())
    except OSError:
        # No containing repository can be inferred from a removed cwd. Keep
        # explicit arguments usable; QARGI_PROJECT already won above.
        return None
    best, blen = None, -1
    for f in project_files():
        try:
            record = load_json(f)
            if not isinstance(record, dict) or not isinstance(record.get("repo"), dict):
                continue
            rp = record["repo"].get("path")
            if not isinstance(rp, str) or not rp:
                continue
            # Use raw HOME for any leading tilde (Bash '&' replacement differs).
            if rp.startswith("~"):
                rp = os.environ.get("HOME", "") + rp[1:]
            if not rp:
                continue
            rp = os.path.realpath(rp)
        except (OSError, ValueError, RecursionError):
            continue
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


def cloud_binding(words):
    """(project, profile, workspace id) of the project the words are about (lib/cloud.py), empty strings when there is no
    project or no binding. A fault in the lookup is no reason to stop a command: it reads as no binding."""
    try:
        import cloud
        p = cloud.project_of(words)
        b = cloud.binding(p) if p else None
        return (p or "", b["profile"] if b else "", b["workspace_id"] if b else "")
    except Exception:  # noqa: BLE001  (the dispatcher ran this lookup with its errors discarded; it still does)
        return ("", "", "")


# ---- the coordinator label (QARGI_ACTOR; qargi help coordinator) ----------------------------------------------------------
# The label is attribution: unauthenticated, no identity, no authority. It only narrows. The decision is made here, once, from the data
# of lib/commands.py (ACTOR_VERBS, ACTOR_OPTS, ACTOR_ANY_OPTS), before any verb runs, so a refused verb has changed nothing.
ACTOR_FORM = "<lead-id>:coord:<feature>:<n>"
ACTOR_MAX = 128          # the marshal's cap on an identity (marshal_store.ID_RE)
ACTOR_FEATURE_MAX = 40   # the longest feature name qargi accepts (lib/feature.sh)


def actor_parse(label):
    """(lead id, feature, n) of a label of the form <lead-id>:coord:<feature>:<n>, or None. The lead id is as the marshal accepts one (letters, digits
    and . _ @ : + -, so no "/"), a feature is kebab-case (the marshal's name form) and n a positive integer without a leading zero; the whole label has
    at most 128 characters. The feature and n hold no colon, so the label is read from the right and a colon in the lead id is no trouble."""
    import re
    if not isinstance(label, str) or not label or len(label) > ACTOR_MAX:
        return None
    parts = label.rsplit(":", 3)
    if len(parts) != 4 or parts[1] != "coord":
        return None
    lead, _, feature, n = parts
    if not (re.fullmatch(r"[A-Za-z0-9._@:+-]+", lead) and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", feature) and len(feature) <= ACTOR_FEATURE_MAX
            and re.fullmatch(r"[1-9][0-9]*", n)):
        return None
    return lead, feature, n


def actor_form_error(value):
    """The usage error for a value of QARGI_ACTOR that is not a label: it says what was given and the form."""
    return ("qargi: QARGI_ACTOR is set and is not a coordinator label: %r. The form is %s: a lead identity of the form the marshal accepts (letters, digits and . _ @ : + -, never /), "
            "the word coord, a feature name (kebab-case, at most %d) and a positive integer, at most %d characters in all. Unset it or give a label; an empty value is no label (qargi help coordinator)"
            % (value, ACTOR_FORM, ACTOR_FEATURE_MAX, ACTOR_MAX))


def actor_refusal(label, what):
    """The one message of a refusal under a label: it names the label and the verb, and says who runs it. `what` is what a coordinator does not do."""
    return "qargi: refused under the coordinator label %s: a coordinator does not %s; the lead runs it. Nothing was changed (qargi help coordinator)" % (label, what)


def _words_of(words):
    return " ".join(w for w in words if w)


def _positionals(opts, body):
    """The words of a verb's command line that are neither options nor their values, with the options' values and the options the verb does not declare:
    ([positional], {flag: [values]}, [undeclared option words]). An option that takes a value is known from the verb's description; a word of the form
    --flag=value is read as the flag and its value. An option that is not declared is not read as taking a value, so the words after it may be read
    differently here than by the verb: the caller refuses the command line when there is one. --json is the dispatcher's own option (bin/qargi runs the
    call again without it): it is known on every verb, a flag without a value, unless the verb documents it itself."""
    flags = {o["flag"]: o for o in list(C.GLOBAL_OPTS) + list(opts)}
    pos, vals, unknown, i = [], {}, [], 0
    while i < len(body):
        t = body[i]
        if t.startswith("--") and "=" in t:
            f, v = t.split("=", 1)
            vals.setdefault(f, []).append(v)
            if f not in flags:
                unknown.append(f)
        elif t.startswith("-") and t != "-":
            if t not in flags:
                unknown.append(t)
            elif flags[t]["arg"]:
                vals.setdefault(t, []).append(body[i + 1] if i + 1 < len(body) else "")
                i += 1
        else:
            pos.append(t)
        i += 1
    return pos, vals, unknown


def _registry():
    """{real path of a run directory: its last line} from the lead's registry (STATE/local-runs.jsonl); empty when there is none."""
    out = {}
    try:
        with open(os.path.join(state(), "local-runs.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and isinstance(rec.get("run"), str):
                    out[os.path.realpath(rec["run"])] = rec
    except OSError:
        pass
    return out


def _run_record(reg, word, parent=False):
    """The registry's line for the run a word names: a run directory (also with a trailing slash), and with parent=True the directory around the word
    (review check is given OUT, the run's out directory). A path the registry does not hold is read by its basename, as lib/review.sh does (reg_id): a
    directory named like a run id, qargi. and six characters, names the one registered run of that id, wherever it is (a copy of a run is not another run:
    review check renews the lease of the feature of the run the id names). None when it names none."""
    import re
    cands = [os.path.realpath(word)]
    if parent:
        cands.append(os.path.dirname(cands[0]))
    for c in cands:
        if c in reg:
            return reg[c]
    for c in cands:
        base = os.path.basename(c)
        if re.fullmatch(r"qargi\..{6}", base, re.S):
            hit = [r for p, r in reg.items() if os.path.basename(p) == base]
            if len(hit) == 1:
                return hit[0]
    return None


def actor_gate(argv):
    """The narrowing of a session that carries a coordinator label. argv is the command line after `qargi` (area, verb, arguments). Returns 0 to go on,
    2 with the message on standard error when the label is not valid or the command line is not a coordinator's. No label (unset or empty): 0, nothing
    read. Help requests, the run-event hooks (which must never fail) and a command line with no verb (the script prints its usage) are let through."""
    label = os.environ.get("QARGI_ACTOR", "")
    if not label or argv[:1] == ["hook"]:     # a run-event hook never fails, whatever the label
        return 0
    if len(argv) > 1 and argv[1] in ("-h", "--help") or len(argv) > 2 and argv[2] in ("-h", "--help"):    # the two places bin/qargi reads a help request
        return 0
    parsed = actor_parse(label)
    if parsed is None:
        print(actor_form_error(label), file=sys.stderr)
        return 2
    feature = parsed[1]
    if not argv or argv[0] not in C.COMMANDS:
        return 0
    area, vs = argv[0], verbs_of(argv[0])
    if vs:
        if len(argv) < 2:
            return 0
        verb, body = argv[1], argv[2:]
    else:
        verb, body = "", argv[1:]
    where = _words_of([area, verb])
    names = C.ACTOR_VERBS.get((area, verb))
    if names is None:
        print(actor_refusal(label, "run " + where), file=sys.stderr)
        return 2
    for w in body:
        for o in C.ACTOR_ANY_OPTS:
            if w == o or w.startswith(o + "="):
                print(actor_refusal(label, "run a command line with %s (%s)" % (o, where)), file=sys.stderr)
                return 2
        for o in C.ACTOR_OPTS.get((area, verb), ()):
            if w == o or w.startswith(o + "="):
                print(actor_refusal(label, "run %s with %s" % (where, o)), file=sys.stderr)
                return 2
    if not names:
        return 0
    opts = (vs[verb]["opts"] if vs else C.COMMANDS[area].get("opts", []))
    pos, vals, unknown = _positionals(opts, body)
    if unknown:     # fail closed: the verb may read the words after an undeclared option differently than this gate does (feature verify --purpose alpha beta)
        print(actor_refusal(label, "run %s with %s: it is not an option the verb declares, so what it names cannot be told" % (where, unknown[0])), file=sys.stderr)
        return 2
    want = "feature/" + feature
    if names == "base":
        for b in vals.get("--base", []):
            if b != want:
                print(actor_refusal(label, "prepare a run on %s: this coordinator's runs are based on %s" % (b or "an empty base", want)), file=sys.stderr)
                return 2
    if "" in body:     # the verb skips an empty word (local clean "" RUN reads RUN) where realpath("") is the current directory, which may be a run of this feature
        print(actor_refusal(label, "run %s with an empty word: it names nothing, so what the verb acts on cannot be told" % where), file=sys.stderr)
        return 2
    if names == "feature":
        for w in pos:
            if w != feature:
                print(actor_refusal(label, "run %s on feature %s: this coordinator's feature is %s" % (where, w, feature)), file=sys.stderr)
                return 2
    elif names == "run":
        saved = vals.get("--saved", [])
        mine = area == "local" and "--mine" in body
        if area == "local" and verb in ("run", "verify") and pos and not saved and not mine:
            # the scripts read their first word as the run: a run named after an option (local run --timeout B A) is not the one the script acts on
            first = [w for w in body if w != "--json" or any(o["flag"] == "--json" for o in opts)]    # bin/qargi takes --json out before the verb runs
            if first[0] != pos[0]:
                print(actor_refusal(label, "run %s with a run that is not its first word: the verb reads its first word as the run, so which run it acts on cannot be told" % where), file=sys.stderr)
                return 2
        named = pos + saved
        if mine and not named:
            return 0
        reg = _registry()
        for w in named:
            rec = _run_record(reg, w, parent=(area == "review"))
            if rec is None:
                if area == "review":
                    continue          # a collected output the registry does not know names no run of this lead: check only reads it
                print(actor_refusal(label, "run %s on %s: the lead's registry does not name it, so its feature is not known" % (where, w)), file=sys.stderr)
                return 2
            if rec.get("base") != want:
                print(actor_refusal(label, "run %s on a run based on %s: this coordinator's runs are based on %s" % (where, rec.get("base") or "no branch", want)), file=sys.stderr)
                return 2
    return 0


def actor_check(argv):
    """The narrowing of a coordinator label at the point of use: `help.py actor-check KIND WHERE VALUE`, run by lib.sh (actor_check, actor_run_check) after a
    script has resolved what it acts on, so what is checked is what the script acts on and there is one parse of the command line. The gate above is
    the first line (the verb allow-list, the refused options, the empty words) and an early refusal of the same narrowing; this is the authoritative one.
    No label (unset or empty): 0. KIND says what VALUE is: feature (a feature name), prepare-base (the base of the run to prepare), run-base (the registry's
    base of the run the script acts on, empty for none), run-unknown (a run word the registry does not name), run-word (a run word that starts with -: the
    scripts read a first word as the run, and which run such a word names cannot be told). WHERE is the verb, as the refusal says it. Exit 0 to go on, 2 with
    the refusal (the same message family as actor_gate)."""
    if len(argv) != 3 or argv[0] not in ("feature", "prepare-base", "run-base", "run-unknown", "run-word"):
        print("usage: help.py actor-check feature|prepare-base|run-base|run-unknown|run-word WHERE VALUE", file=sys.stderr)
        return 2
    kind, where, value = argv
    label = os.environ.get("QARGI_ACTOR", "")
    if not label:
        return 0
    parsed = actor_parse(label)
    if parsed is None:
        print(actor_form_error(label), file=sys.stderr)
        return 2
    feature = parsed[1]
    want = "feature/" + feature
    what = None
    if kind == "feature" and value != feature:
        what = "run %s on feature %s: this coordinator's feature is %s" % (where, value, feature)
    elif kind == "prepare-base" and value != want:
        what = "prepare a run on %s: this coordinator's runs are based on %s" % (value or "an empty base", want)
    elif kind == "run-base" and value != want:
        what = "run %s on a run based on %s: this coordinator's runs are based on %s" % (where, value or "no branch", want)
    elif kind == "run-unknown":
        what = "run %s on %s: the lead's registry does not name it, so its feature is not known" % (where, value)
    elif kind == "run-word":
        what = "run %s with the run word %s: it starts with a dash, so which run it names cannot be told" % (where, value)
    if what is None:
        return 0
    print(actor_refusal(label, what), file=sys.stderr)
    return 2


def preamble(argv):
    """What bin/qargi does before every command, in one process: the dev-run banner on stderr; the arguments resolved
    (resolve); the cloud binding of the project the command is about (none for qargi cloud itself, which manages the
    bindings). On stdout, NUL-separated: project, profile, workspace id, then the resolved arguments. None (exit 2) when
    resolve refused."""
    if P.banner():
        print("qargi: " + P.banner(), file=sys.stderr)
    r = resolve(argv)
    if r is None:
        return None
    binding = cloud_binding(r) if r and r[0] not in ("cloud", "help", "version") else ("", "", "")
    return list(binding) + r


def main(argv):
    if not argv:
        return show([])
    if argv[0] == "preamble":
        r = preamble(argv[1:])
        if r is None:
            return 2
        sys.stdout.write("".join(a + "\0" for a in r))
        return 0
    if argv[0] == "actor-gate":      # the narrowing of a coordinator label; bin/qargi asks it before any verb when QARGI_ACTOR is not empty
        return actor_gate(argv[1:])
    if argv[0] == "actor-check":     # the narrowing at the point of use (lib.sh actor_check): the scripts ask it once they have resolved their target
        return actor_check(argv[1:])
    if argv[0] == "actor-parse" and len(argv) == 2:   # the feature of a label (lib.sh actor_label); exit 2 and the form when it is not one
        p = actor_parse(argv[1])
        if p is None:
            print(actor_form_error(argv[1]), file=sys.stderr)
            return 2
        print(p[1])
        return 0
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
        rest = argv[1:]
        if rest and rest[0] == "--keep-date" and len(rest) == 2:
            sys.stdout.write(man(rest[1]))
            return 0
        if rest:
            print("usage: help.py man [--keep-date FILE]", file=sys.stderr)
            return 2
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
    print("usage: help.py show|man|complete|resolve|preamble|actor-gate|actor-parse ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
