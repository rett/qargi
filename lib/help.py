#!/usr/bin/env python3
"""qargi help, the manual page and the completion candidates, all from lib/commands.py.

  help.py show [ARGS...]      qargi help, qargi help COMMAND [VERB], qargi help TOPIC, qargi COMMAND --help
  help.py man                 the manual page (roff) on stdout
  help.py complete WORDS...   completion candidates for the last word (qargi __complete, used by the bash completion)
"""
import glob, json, os, shutil, sys, textwrap

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import commands as C  # noqa: E402

ROOT = os.path.dirname(HERE)
BOLD = sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def conf():
    return os.environ.get("QARGI_CONF") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "qargi")


def state():
    return os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")


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


def argstr(args):
    out = []
    for a in args:
        name, optional = a[0], (a[2] if len(a) > 2 else False)
        implied = a[1] == "project" and not optional   # filled in from the current directory (see infer_project)
        out.append("[%s]" % name if (optional or implied) else name)
    return " ".join(out)


def has_project_arg(args):
    return any(a[1] == "project" and not (a[2] if len(a) > 2 else False) for a in args)


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
      "and qargi\\-review in Claude Code.")
    return "\n".join(x for x in o if x != "") + "\n"


# ------------------------------------------------------------------ completion
def names(kind, words=()):
    try:
        if kind == "project":
            return sorted(os.path.basename(f)[:-5] for f in glob.glob(os.path.join(conf(), "projects", "*.json")))
        if kind == "instance":
            return sorted(load_json(os.path.join(conf(), "instances.json")))
        if kind == "session":
            return sorted(load_json(os.path.join(state(), "sessions.json")))
        if kind == "pack":
            lib = os.path.join(conf(), "packs")
            return sorted([os.path.basename(p) for p in glob.glob(os.path.join(lib, "skills", "*"))] +
                          [os.path.basename(p)[:-5] for p in glob.glob(os.path.join(lib, "tools", "*.json"))])
        if kind == "team":
            prj = next((w for w in words if os.path.exists(os.path.join(conf(), "projects", w + ".json"))), None)
            return sorted(load_json(os.path.join(conf(), "projects", prj + ".json")).get("teams", {})) if prj else []
    except (OSError, ValueError):
        return []
    return []


def by_type(t, words):
    if isinstance(t, tuple):
        return list(t)
    if t in ("project", "instance", "session", "pack", "team"):
        return names(t, words)
    if t == "role":
        return list(C.ROLES)
    if t == "file":
        return ["@file"]
    if t == "dir":
        return ["@dir"]
    if t == "help":
        return sorted(C.COMMANDS) + list(C.TOPICS)
    return []


def complete(words):
    cur, prev = words[-1], words[:-1]
    if not prev:
        return sorted(C.COMMANDS)
    if prev[0] == "help":
        return by_type("help", prev) if len(prev) == 1 else []
    if prev[0] not in C.COMMANDS:
        return []
    spec = C.COMMANDS[prev[0]]
    vs = verbs_of(prev[0])
    if vs:
        if len(prev) == 1:
            return list(vs)
        vspec = vs.get(prev[1])
        if not vspec:
            return []
        args, opts, rest = vspec["args"], vspec["opts"], prev[2:]
    else:
        args = [tuple(a) for a in spec.get("usage", [])]
        opts, rest = spec.get("opts", []), prev[1:]
    flags = {o["flag"]: o for o in opts}
    pos, i = 0, 0
    while i < len(rest):
        t = rest[i]
        if t.startswith("-") and t in flags:
            if flags[t]["arg"] and i + 1 >= len(rest):
                return by_type(flags[t]["type"], prev)
            i += 2 if flags[t]["arg"] else 1
        else:
            pos += 1
            i += 1
    if cur.startswith("-"):
        return list(flags)
    if pos < len(args):
        return by_type(args[pos][1], prev)
    return list(flags)


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
    (dev -> PROJECT-dev). An argument you give always wins. Returns the argument list to run."""
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
        if a[1] == "instance" and k < len(pos) and out[pos[k]] not in insts and out[pos[k]] in C.ROLES:
            out[pos[k]] = "%s-%s" % (P, out[pos[k]])
    required = [k for k, a in enumerate(args) if not (a[2] if len(a) > 2 else False)]
    pk = next((k for k in required if args[k][1] == "project"), None)
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
        print("\n".join(complete(argv[1:] or [""])))
        return 0
    print("usage: help.py show|man|complete ...", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
