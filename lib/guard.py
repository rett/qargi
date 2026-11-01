#!/usr/bin/env python3
"""qargi __guard: a PreToolUse hook for the local members' Bash, Edit, Write and NotebookEdit tools. Reads the hook's
JSON on stdin and refuses (exit 2, reason on stderr) what would publish, reach out or change a skill. A barrier, not
proof: a second barrier beside the git wrapper (which has no credentials) and `qargi local verify`; an agent that goes
out of its way can still get around it, which is why verify exists.

Publishing: git push, gh, ssh, scp, sftp, and changing a remote.

Review is read-only as a rule. A member whose definition passes `--class read-only` (the hook command in its frontmatter,
under the protected ~/.claude/agents) is held to it on every task. A member that serves several abilities passes no class
and falls back on `qargi local prepare`, which writes the task's ability to RUN/ability; the guard refuses any write to
that file and to refs.before, so a member cannot change the ability it is judged by. When the class says read-only, or
the nearest run directory above the call's cwd or file path says review, the guard also refuses an edit outside RUN/out (the report
and the manifest) and a Bash command that writes into the clone: a redirection into it, a command that creates,
changes or removes files there, or a git command that changes the work tree or the history.

Skills: only a person, through qargi's own skills, changes a skill, so the guard refuses a member
  - the verbs that change one: qargi skill|tool new|import|seal|remove|unlink|link|enable|disable, qargi discover
    install, qargi packs apply, qargi packs seed and qargi import (it restores the pack library). Read-only verbs (list, show, check,
    effective, search, render, export) stay allowed. The verb is found after wrappers, inside `sh|bash -c STRING` and
    `eval STRING`, inside $(...) and backticks, and when the script is named directly (packs.sh, discover.py);
  - setting QARGI_NESTED (it makes some verbs skip their plan-token check);
  - a write under a protected location: the pack library ($QARGI_CONF/packs, else $QARGI_HOME/config/packs, else
    ~/.qargi/config/packs; the earlier ~/.config/qargi/packs, also under $XDG_CONFIG_HOME, stays protected), the credentials
    directory and install.json of the same configuration directories (not the rest of it: a member may run qargi verbs that
    change instances, agents or projects; the guard decides by the path a write construct names, never by the verb, and a
    read of a protected path stays allowed), ~/.claude/skills, ~/.claude/agents, ~/.claude/plugins, the installed copy of the tool (the tool_root in install.json:
    the skills there are linked from ~/.claude/skills), and any .claude/skills or .claude/agents directory
    outside the run's clone (a project's installed ones). Inside the clone, found from the nearest `qargi local
    prepare` run directory, .claude/skills is the work product and stays writable; the path is resolved first, so a
    symbolic link in the clone that leads to a protected root is still denied. Edit, Write and
    NotebookEdit are decided by the resolved path (symbolic links followed). A Bash command is decided by a heuristic:
    a command that names a protected path as the destination of a write construct: a redirection (also `>file`
    without a space), tee, cp, mv, rm, ln, install, rsync, touch, mkdir, chmod, chown, truncate, shred, patch,
    `sed|perl -i`, `dd of=`, a git command that changes the tree, find with -delete or -exec, and any argument of
    tar, unzip, curl or wget. `~`, $HOME, $QARGI_CONF and cd are followed. What an agent edits in its own clone, the
    repository's `skills/` directory included, and in its run directories stays allowed: protection is by the
    resolved path relative to the roots above, never by the word `skills`.
Marshal: the feature marshal (`qargi marshal`) is changed only by the lead. The guard refuses a member
  - the verbs that change it: qargi marshal claim|set|renew|release|take|takeover|finish, found like the skill verbs
    (after wrappers, in `sh -c`, `eval`, $(...), through a path to bin/qargi or marshal.sh). status and check stay allowed;
    any other verb, none, or one held in a variable is refused (fail closed);
  - a write under the features/ directory of the state ($QARGI_STATE, else <root>/state, and ~/.qargi/state), where the
    marshal keeps one record per open feature: decided like the other protected roots, reading stays allowed;
  - a write to the ref journal of the state ($QARGI_STATE/ref-journal.jsonl, its lock and any rotated or temporary file next to
    it, e.g. ref-journal.jsonl.lock, .1, .tmp): the lead's record of the branch moves its own verbs made, which `qargi local verify`
    accepts as lead-side changes. Decided like features/; reading stays allowed. The journal is trusted only as far as the state
    directory is: an executor running as the same OS user could still edit the file by code the guard cannot see (HMAC-signed
    records are a later feature);
  - setting or unsetting QARGI_LEAD (the lead identity): an assignment, export, declare, unset or env -u in a command.
Not covered: code that writes a file itself (python -c, perl -e, node -e, a script written earlier and run), a glob
that expands to a protected path, a path built from a variable the guard cannot see. A heredoc line that starts with a
refused verb is refused even as text (use the Write tool for documents).

Failure: the guard fails closed. Any unexpected exception ends in exit 2 with the reason on stderr. Input that is not
JSON is still let through (exit 0), as before. Known limits outside this file, from the Claude Code hooks documentation
(https://code.claude.com/docs/en/hooks): a hook that cannot start, exits other than 0 or 2, times out or prints invalid
JSON is a non-blocking error ("The action goes ahead, except for hooks whose failure blocks the action, for example a
hook with `onFailure` set to \"block\""), so agents/member.md sets `onFailure: "block"` and a `timeout` (`onFailure`
"Requires Claude Code v2.1.295 or later"; an older version does not enforce it). Frontmatter hooks of a project-level
agent file run only after the workspace trust dialog is accepted (https://code.claude.com/docs/en/sub-agents): until
then the subagent runs without this guard."""
import json, os, re, shlex, sys

SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
SUBST = re.compile(r"\$\(|`")                               # command substitution starts a command of its own
WRAP = {"sudo", "env", "command", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice"}
WRITERS = {"rm", "rmdir", "touch", "mkdir", "chmod", "chown", "truncate", "tee", "patch", "unlink", "shred"}
COPIERS = {"cp", "mv", "ln", "install", "rsync"}            # the last argument is the destination
INPLACE = {"sed", "perl"}                                   # with -i
GIT_WRITES = {"add", "commit", "apply", "am", "checkout", "switch", "reset", "rm", "mv", "stash", "merge", "rebase",
              "cherry-pick", "revert", "restore", "clean", "tag", "branch", "pull", "fetch", "init", "clone", "worktree",
              "notes", "update-ref", "config", "submodule"}
REDIR = re.compile(r"^(?:\d*|&)>>?(.*)$")
EDIT_TOOLS = ("Edit", "Write", "NotebookEdit", "MultiEdit")

SKILL_VERBS = {"new", "import", "seal", "remove", "unlink", "link", "enable", "disable"}
SCRIPTS = ("qargi", "packs.sh", "discover.py", "cloud.py", "upgrade.sh", "marshal.sh")              # the command and the scripts behind the refused verbs
MARSHAL_MUTATING = ("claim", "set", "renew", "release", "take", "takeover", "finish")
MARSHAL_READ = ("status", "check")
LEAD_BUILTINS = {"export", "declare", "typeset", "readonly", "local", "unset", "env", "read", "printf", "set", "let"}
MARSHAL_NOTE = "the lead changes the marshal; report it in your task output"
SHELLS = {"sh", "bash", "dash", "zsh", "ksh"}
SHELL_C = re.compile(r"^-[A-Za-z]*c[A-Za-z]*$")
DESTRUCTIVE = {"rm", "rmdir", "shred", "unlink", "mv"}      # these also remove a directory that holds a protected one
EXTRACTORS = {"tar", "unzip", "curl", "wget"}              # write where an option says: any argument that names a protected path
FIND_ACTIONS = {"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprintf", "-fls"}


def blocked(command):
    for seg in SEGMENT.split(command):
        toks = tokens(seg)
        i = skip_wrappers(toks)
        if i >= len(toks):
            continue
        prog = os.path.basename(toks[i])
        rest = toks[i + 1:]
        if prog in ("gh", "ssh", "scp", "sftp"):
            return "%s is not available to an agent" % prog
        if prog == "git":
            words = [t for t in rest if not t.startswith("-")]
            if "push" in words:
                return "git push is not available to an agent"
            if words[:1] == ["remote"] and len(words) > 1 and words[1] in ("add", "set-url", "remove", "rm"):
                return "changing a git remote is not available to an agent"
    return None


def tokens(seg):
    try:
        toks = shlex.split(seg)
    except ValueError:
        toks = seg.split()
    return toks


def skip_wrappers(toks):
    i = 0
    while i < len(toks) and ("=" in toks[i].split("/")[0] and not toks[i].startswith("-")
                             or os.path.basename(toks[i]) in WRAP or toks[i].isdigit() or (toks[i].startswith("-") and i)):
        i += 1
    return i


def run_dir(path):
    """The nearest directory at or above path that `qargi local prepare` made (it holds ability and refs.before)."""
    p = os.path.realpath(path) if path else ""
    while p and p != os.path.dirname(p):
        if os.path.isfile(os.path.join(p, "ability")) and os.path.isfile(os.path.join(p, "refs.before")):
            return p
        p = os.path.dirname(p)
    return None


def read_class(argv):
    """The class the hook command line names: "" (none) or "read-only". Anything else is an error the caller refuses."""
    if "--class" not in argv:
        return ""
    k = argv.index("--class")
    return argv[k + 1] if k + 1 < len(argv) else None


CLASS = ""
CLASSES = ("", "read-only")


def is_review(run):
    """True when the member is read-only by class (its hook) or the run directory says so (its class file, or the review role)."""
    return CLASS == "read-only" or ability_of(run) == "review" or run_class(run) == "read-only"


def control_refusal(full):
    """The reason a write to a run directory's control file (ability, class, refs.before) is refused, or None."""
    if os.path.basename(full) in ("ability", "class", "refs.before") and run_dir(os.path.dirname(full)) == os.path.dirname(full):
        return "%s is the run's own record (the coordinator wrote it); a member does not change it" % full
    return None


def run_class(run):
    try:
        with open(os.path.join(run, "class")) as f:
            return f.read().strip()
    except OSError:
        return ""


def ability_of(run):
    try:
        with open(os.path.join(run, "ability")) as f:
            return f.read().strip()
    except OSError:
        return ""


def inside(path, base):
    return path == base or path.startswith(base + os.sep)


def resolve(here, p):
    """The real path of p (with ~ and environment variables expanded) as seen from the directory here."""
    return os.path.realpath(os.path.join(here, os.path.expandvars(os.path.expanduser(p))))


def write_targets(toks, i):
    """(what, destination) of everything a segment writes, by its redirections and its program (git included)."""
    targets, gitdir = [], None
    for k, t in enumerate(toks):                       # redirections anywhere in the segment
        m = REDIR.match(t)
        if m and not t.startswith(">&") and not re.match(r"^\d*>&\d+$", t):
            dest = m.group(1) or (toks[k + 1] if k + 1 < len(toks) else "")
            if dest and dest != "/dev/null":
                targets.append(("a redirection", dest))
    if i < len(toks):
        prog, rest = os.path.basename(toks[i]), toks[i + 1:]
        args = [t for t in rest if not t.startswith("-") and not REDIR.match(t)]
        if prog in WRITERS:
            targets += [(prog, a) for a in args]
        elif prog in COPIERS and args:
            targets.append((prog, args[-1]))
        elif prog in INPLACE and any(t.startswith("-i") or t == "--in-place" for t in rest):
            targets += [(prog + " -i", a) for a in args[1:]]
        elif prog == "git":
            k = 0
            while k < len(rest) and rest[k].startswith("-"):
                if rest[k] == "-C" and k + 1 < len(rest):
                    gitdir = rest[k + 1]; k += 2
                elif rest[k] in ("-c", "--git-dir", "--work-tree"):
                    k += 2
                else:
                    k += 1
            sub = rest[k] if k < len(rest) else ""
            if sub in GIT_WRITES:
                targets.append(("git " + sub, gitdir or "."))
    return targets


def review_refusal(tool, inp, cwd):
    """The reason a call under the review ability is refused, or None."""
    if tool in EDIT_TOOLS:
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if not fp:
            return None
        full = os.path.realpath(os.path.join(cwd, fp))
        why = control_refusal(full)
        if why:
            return why
        run = run_dir(os.path.dirname(full)) or run_dir(cwd)
        if run and is_review(run) and not inside(full, os.path.join(run, "out")):
            return "under the review ability only the report and the manifest in RUN_DIR may be written (%s is not)" % fp
        return None
    if tool != "Bash":
        return None
    command = inp.get("command") or ""
    here = cwd
    for seg in SEGMENT.split(command):
        toks = tokens(seg)
        i = skip_wrappers(toks)
        if i < len(toks) and toks[i] == "cd" and i + 1 < len(toks):
            here = os.path.realpath(os.path.join(here, os.path.expanduser(toks[i + 1])))
            continue
        why = review_segment(toks, i, here)
        if why:
            return why
    return None


def review_segment(toks, i, here):
    def resolve_(p):
        return os.path.realpath(os.path.join(here, os.path.expanduser(p)))
    for what, dest in write_targets(toks, i):
        full = resolve_(dest)
        why = control_refusal(full)
        if why:
            return why
        run = run_dir(full if os.path.isdir(full) else os.path.dirname(full)) or run_dir(here)
        if run and is_review(run) and inside(full, os.path.join(run, "clone")):
            return "under the review ability nothing in the clone may be changed (%s into %s)" % (what, dest)
    return None


# --- skills: who may change one, and where they live

class MarshalReason(str):
    """A refusal about the marshal: decide() ends it with the marshal's advice instead of the skills'."""


def protected_roots():
    """The locations whose content is a skill, the library of them, a credential or the install record (real paths)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import paths as P                                     # here, not at the top: an import failure is then a refusal (see main)
    home = os.path.expanduser("~")
    # the library where the data lives now, the default and the QARGI_HOME one beside an override, and the earlier XDG
    # libraries, which stay as a backup after `qargi migrate home`
    # Besides the library, only the credentials and the install record of each configuration directory: not the rest of
    # <conf> (instances, agents, projects, profiles), which qargi verbs a member runs legitimately change.
    roots = {os.path.join(home, ".claude", "skills"), os.path.join(home, ".claude", "agents"), os.path.join(home, ".claude", "plugins")}
    # (the live configuration directory is one of these: QARGI_CONF, QARGI_HOME/config or ~/.qargi/config)
    for conf in (P.conf(), os.path.join(P.root(), "config"), os.path.join(home, ".qargi", "config"), P.legacy_conf(),
                 os.path.join(home, ".config", "qargi")):
        roots.update(os.path.join(conf, name) for name in ("packs", "credentials", "install.json"))
    roots.add(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "anthropic"))   # the ant profiles and logins
    # the installed copy of the tool: ~/.claude/skills/qargi-* are links into it, and a write through such a link resolves
    # here, so it must be a root itself (it holds the skills, the member definition and the roles a member is launched with)
    installed = P.installed_tool_root()
    if installed:
        roots.add(installed)
    roots.update(claude_render_roots(P, home))
    roots.update(feature_roots(P, home))
    roots.update(journal_roots(P, home))
    return sorted(os.path.realpath(r) for r in roots)


def claude_render_roots(P=None, home=None):
    """The claude/ directory of the state: the render that `packs apply --target claude-code` makes of a project's enabled
    skills and tools, which Claude Code loads with --add-dir. Its content is instructions a session follows, so it is
    protected like the pack library. Found like the other qargi paths: QARGI_STATE, else <root>/state, and the default
    ~/.qargi/state beside an override (real paths, so a link into it is followed)."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "claude")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def feature_roots(P=None, home=None):
    """The features/ directory of the state: the marshal's record of each open feature. Found as claude_render_roots does."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "features")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


JOURNAL = "ref-journal.jsonl"


def state_dirs(P=None, home=None):
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(st) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def journal_roots(P=None, home=None):
    """The lead's ref journal of the state and its lock (real paths). Rotated and temporary files next to it are found by
    journal_sibling. Trusted only as far as the state directory is: see the module docstring."""
    return {os.path.join(st, n) for st in state_dirs(P, home) for n in (JOURNAL, JOURNAL + ".lock")}


def journal_sibling(full):
    """The journal root when full is a file next to the journal named like it (ref-journal.jsonl.1, .tmp, ...), else None."""
    for st in state_dirs():
        if os.path.dirname(full) == st and os.path.basename(full).startswith(JOURNAL):
            return os.path.join(st, JOURNAL)
    return None


def refusal_text(what, dest, root):
    """The sentence for a refused write: the generic one, or for the claude render and the marshal's records the reason."""
    if root in journal_roots() or journal_sibling(root):
        return MarshalReason("%s on %s would change %s, the lead's ref journal of branch moves; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in feature_roots():
        return MarshalReason("%s on %s would change %s, the marshal's record of the open features; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in claude_render_roots():
        return ("%s on %s would change %s, the render of a project's skills and tools that Claude Code loads; it is managed by "
                "`qargi packs apply` and changed only by the lead" % (what, dest, root))
    return "%s on %s would change %s, a protected location (skills, the pack library, credentials)" % (what, dest, root)


def in_clone(full):
    """True when the real path full lies inside the clone of the nearest run directory `qargi local prepare` made. A
    clone is made from repository content, so a .claude/skills there is the work product (reviewed as a patch), not an
    installed skill. Call it only with a resolved path: a symbolic link in the clone has then already been followed."""
    run = run_dir(os.path.dirname(full)) or run_dir(full)
    return bool(run) and inside(full, os.path.join(os.path.realpath(run), "clone"))


def protected(full, destructive=False):
    """The protected location a real path belongs to, or None. A destructive command (rm, mv) also reaches a directory
    that holds one. A project's own .claude/skills is found by its two path components, wherever the project is; the
    repository's `skills/` directory is not protected, nor is anything inside the run's clone (see in_clone) unless it
    resolves into a named root."""
    for r in protected_roots():
        if inside(full, r) or (destructive and inside(r, full)):
            return r
    j = journal_sibling(full)
    if j:
        return j
    if in_clone(full):          # after the named roots: a link in the clone that leads to one was resolved and is denied above
        return None
    parts = full.split(os.sep)
    for sub in ("skills", "agents"):          # a project's installed skills and member definitions (the latter hold the hook that guards a member)
        if any(parts[k] == ".claude" and parts[k + 1] == sub for k in range(len(parts) - 1)):
            return ".claude/" + sub
        if destructive and os.path.basename(full) == ".claude" and os.path.isdir(os.path.join(full, sub)):
            return ".claude/" + sub
    return None


def skill_refusal(tool, inp, cwd):
    """The reason a call would change a skill (or let an agent skip a plan token), or None."""
    if tool in EDIT_TOOLS:
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        root = protected(resolve(cwd, fp)) if fp else None
        return refusal_text(tool, fp, root) if root else None
    if tool != "Bash":
        return None
    return bash_skill_refusal(inp.get("command") or "", cwd, 0)


def names_lead(t):
    """True when a word assigns, exports or unsets QARGI_LEAD (QARGI_LEAD=x, QARGI_LEAD+=x, -u QARGI_LEAD, --unset=QARGI_LEAD, bare name)."""
    lhs, _, rhs = t.partition("=")
    return lhs.rstrip("+") == "QARGI_LEAD" or (lhs in ("--unset", "-u") and rhs == "QARGI_LEAD")


def lead_refusal(prog, rest, pre):
    """The reason a segment sets or unsets QARGI_LEAD, or None. pre: the words up to and with the program (VAR=x, env -u NAME)."""
    if any(names_lead(t) for t in pre) or (prog in LEAD_BUILTINS and any(names_lead(t) for t in rest)):
        return MarshalReason("setting or unsetting QARGI_LEAD changes who the lead is and is not available to an agent; " + MARSHAL_NOTE)
    return None


def bash_skill_refusal(command, here, depth):
    command = command.replace("\\\n", "")                # a line continuation joins the lines
    segs = SEGMENT.split(SUBST.sub(";", command))
    for n, seg in enumerate(segs):
        toks = tokens(seg)
        if toks:
            toks[0] = toks[0].lstrip("({")
            toks = toks if toks[0] else toks[1:]
        i = skip_wrappers(toks)
        if any(t.startswith("QARGI_NESTED=") for t in toks[:i]):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
        why = lead_refusal(prog, rest, toks[:i + 1])
        if why:
            return why
        if i >= len(toks):
            continue
        if prog == "cd" and rest:
            here = resolve(here, rest[0])
            continue
        if prog in ("export", "declare", "typeset", "readonly") and any(t.split("=")[0] == "QARGI_NESTED" for t in rest):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        why = skill_verb(prog, rest)
        if why:
            return why
        inner = shell_string(prog, rest) if depth < 3 else None
        if inner is not None:          # a `;` inside the quoted string split it: read the segments that follow as part of it
            inner += " ; " + " ; ".join(segs[n + 1:]).replace('"', " ").replace("'", " ")
            why = bash_skill_refusal(inner, here, depth + 1)
            if why:
                return why
        why = protected_write(toks, i, here)
        if why:
            return why
    return None


def shell_string(prog, rest):
    """The command text a shell is given to run (sh -c STRING, eval STRING), or None. The quotes are dropped, which
    is conservative: the text is then read as plain words."""
    if prog == "eval":
        return " ".join(rest)
    if prog in SHELLS:
        for k, t in enumerate(rest):
            if SHELL_C.match(t):
                return " ".join(rest[k + 1:]).replace('"', " ").replace("'", " ")
    return None


def skill_verb(prog, rest):
    """The reason a qargi command (or the script behind it, run directly) is a verb that changes a skill, or None."""
    words = [t for t in rest if not t.startswith("-")]
    name = prog
    if prog not in SCRIPTS:
        if (prog in SHELLS or re.match(r"^python[0-9.]*$", prog)) and words and os.path.basename(words[0]) in SCRIPTS:
            name, words = os.path.basename(words[0]), words[1:]
        else:
            return None
    if name == "discover.py":
        words = ["discover"] + words
    if name == "cloud.py":
        words = ["cloud"] + words
    if name == "upgrade.sh":
        words = ["upgrade"] + words
    if name == "marshal.sh":
        words = ["marshal"] + words
    area, verb = (words + ["", ""])[:2]
    if area == "marshal" and verb not in MARSHAL_READ:
        return MarshalReason("qargi marshal %s changes the feature marshal and is not available to an agent (only status and check are); %s"
                             % (verb or "(no verb)", MARSHAL_NOTE))
    if (area in ("skill", "tool") and verb in SKILL_VERBS) or (area, verb) in (("discover", "install"), ("packs", "apply"), ("packs", "seed")) \
            or (area == "import" and name == "qargi") or (area == "cloud" and verb in ("set", "unset", "login")) or area == "upgrade":
        if area == "upgrade":
            return "qargi upgrade changes the installed tool and its skills and is not available to an agent"
        if area == "cloud":
            return "qargi cloud %s changes which cloud workspace a project uses and is not available to an agent" % verb
        return "%s changes a skill and is not available to an agent" % ("qargi import" if area == "import" else "qargi %s %s" % (area, verb))
    return None


def protected_write(toks, i, here):
    """The reason a segment writes under a protected location, or None (the heuristic the docstring describes)."""
    prog, rest = os.path.basename(toks[i]), toks[i + 1:]
    args = [t for t in rest if not t.startswith("-") and not REDIR.match(t)]
    cands = [(what, dest) for what, dest in write_targets(toks, i)]
    for t in toks:                                       # >file and 2>>file written without a space
        if ">" in t and not REDIR.match(t) and t.rsplit(">", 1)[1] and not t.rsplit(">", 1)[1].startswith("&"):
            cands.append(("a redirection", t.rsplit(">", 1)[1]))
    if prog == "mv":
        cands += [(prog, a) for a in args]               # the source is removed
    elif prog in INPLACE and any(re.match(r"^-[A-Za-z]*i", t) or t == "--in-place" for t in rest):   # -i, -i.bak, -pi, -ni
        cands += [(prog + " -i", a) for a in args]
    if prog in COPIERS:                                  # -t DIR, --target-directory=DIR, -tDIR
        for k, t in enumerate(rest):
            if t in ("-t", "--target-directory") and k + 1 < len(rest):
                cands.append((prog, rest[k + 1]))
            elif t.startswith("--target-directory="):
                cands.append((prog, t.split("=", 1)[1]))
            elif t.startswith("-t") and not t.startswith("--") and len(t) > 2:
                cands.append((prog, t[2:]))
    if prog in SCRIPTS or (prog in SHELLS or re.match(r"^python[0-9.]*$", prog)) and args and os.path.basename(args[0]) in SCRIPTS:
        words = args if prog in SCRIPTS else args[1:]
        if words[:2] == ["packs", "render"]:                 # render writes its output directory: judge every operand
            cands += [("qargi packs render", c) for t in words[2:] for c in {t, t.split("=", 1)[-1]}]
    if prog == "dd":
        cands += [(prog, t[3:]) for t in rest if t.startswith("of=")]
    if prog == "find" and any(t in FIND_ACTIONS for t in rest):
        cands += [("find", t) for t in rest if not t.startswith("-") and t not in ("(", "!")][:8]
    if prog == "tar":
        cands += [(prog, a) for a in tar_targets(rest)]
    elif prog in EXTRACTORS:
        for t in rest:
            cands += [(prog, c) for c in {t, t.split("=", 1)[-1], t[2:] if t.startswith("-") and not t.startswith("--") else t}]
    for what, dest in cands:
        if not dest or dest.startswith("-") and dest != "-":
            continue
        root = protected(resolve(here, dest), what in DESTRUCTIVE)
        if root:
            return refusal_text(what, dest, root)
    return None


def tar_targets(rest):
    """What a tar command writes: every operand when it extracts or appends (it may write anywhere it is told, -C
    included), only the archive (-f, --file) when it creates or lists, so reading a protected directory into an
    archive stays allowed."""
    modes = [t.lstrip("-") for k, t in enumerate(rest) if re.match(r"^-?[A-Za-z]+$", t) and (k == 0 or t.startswith("-"))]
    longs = [t for t in rest if t.startswith("--")]
    if any(set(m) & set("xru") for m in modes) or any(t.split("=")[0] in ("--extract", "--get", "--append", "--update", "--delete") for t in longs):
        return [c for t in rest for c in (t, t.split("=", 1)[-1], t[2:] if t.startswith("-") and not t.startswith("--") else t)]
    out = []
    for k, t in enumerate(rest):
        if k + 1 < len(rest) and ((re.match(r"^-?[A-Za-z]+$", t) and "f" in t.lstrip("-") and (k == 0 or t.startswith("-"))) or t == "--file"):
            out.append(rest[k + 1])
        elif t.startswith("--file="):
            out.append(t.split("=", 1)[1])
    return out


def decide():
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0                                          # not JSON: not a call to judge (as before)
    tool = data.get("tool_name") or "Bash"
    inp = data.get("tool_input") or {}
    cwd = data.get("cwd") or os.getcwd()
    why = blocked(inp.get("command") or "") if tool == "Bash" else None
    if why:
        print("qargi guard: %s. Agents never push; return patches instead." % why, file=sys.stderr)
        return 2
    why = skill_refusal(tool, inp, cwd)
    if isinstance(why, MarshalReason):
        print("qargi guard: %s." % why, file=sys.stderr)
        return 2
    if why:
        print("qargi guard: %s. Only a person, through qargi's own skills, changes a skill; propose the change as a "
              "patch or a plan in RUN_DIR." % why, file=sys.stderr)
        return 2
    why = review_refusal(tool, inp, cwd)
    if why:
        print("qargi guard: %s. A review reads the work and writes its report to RUN_DIR." % why, file=sys.stderr)
        return 2
    return 0


def main():
    global CLASS
    cls = read_class(sys.argv[1:])
    if cls not in CLASSES:
        print("qargi guard: unknown class %r in the hook command; refusing every call until the member is refreshed." % cls, file=sys.stderr)
        return 2
    CLASS = cls
    try:
        return decide()
    except Exception as e:                                # fail closed: a guard that cannot decide refuses
        print("qargi guard: internal error (%s: %s); refusing the call because the guard could not check it."
              % (type(e).__name__, e), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
