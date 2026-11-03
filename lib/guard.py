#!/usr/bin/env python3
"""qargi __guard: a PreToolUse hook for the local members' Bash, Edit, Write, NotebookEdit, Read and Grep tools. Reads the hook's
JSON on stdin and refuses (exit 2, reason on stderr) what would publish, reach out or change a skill. A barrier, not
proof: a second barrier beside the git wrapper (which has no credentials) and `qargi local verify`; an agent that goes
out of its way can still get around it, which is why verify exists.

Two layers. The hook protocol (HOOK PROTOCOL below) is data: where in the hook's JSON the tool, the command, the paths and the working
directory are, which tool names are a shell, a write or a read, and how a refusal is given back (exit status and stream, or JSON on
standard output). It turns the hook's input into a neutral Call(kind, name, command, path, cwd) and a refusal into the hook's answer.
The decisions (judge and everything it calls) see only the Call. The data of the runtime that qargi was built for is CLAUDE_HOOK, used
when the hook command names no provider; `--provider NAME` reads it from the barrier.hook of that provider's local definition instead
(the shipped ones and the library's), and a provider whose definition has no usable hook data refuses every call, in the plain way (exit 2,
reason on stderr), since it has no other. A refusal, a failure and an unknown class are given back in the provider's way.

Publishing: git push, gh, ssh, scp, sftp, and changing a remote.

Review is read-only as a rule. A member whose definition passes `--class read-only` (the hook command in its frontmatter,
under the protected ~/.claude/agents) is held to it on every task. A member that serves several abilities passes no class
and falls back on `qargi local prepare`, which writes the task's ability to RUN/ability; the guard refuses any write to
that file and to refs.before and profile, so a member cannot change the ability it is judged by. When the class says read-only, or
the nearest run directory above the call's cwd or file path says review, the guard also refuses an edit outside RUN/out (the report
and the manifest) and a Bash command that writes into the clone: a redirection into it, a command that creates,
changes or removes files there, or a git command that changes the work tree or the history.

Skills: only a person, through qargi's own skills, changes a skill, so the guard refuses a member
  - the verbs that change one: qargi skill|tool new|import|seal|remove|unlink|link|enable|disable, qargi skill accept|unaccept
    (they record which skills the owner accepts, in <packs>/accepted.json), qargi discover
    install, qargi packs apply|seed|link|unlink, qargi project link|unlink (they link the project's skills, agents and memory into the
    checkout and the runtime's memory directory, which changes what a session loads) and qargi import (it restores the pack library).
    Read-only verbs (list, show, check, effective, search, render, export) stay allowed. The verb is found after wrappers, inside `sh|bash -c STRING` and
    `eval STRING`, inside $(...) and backticks, and when the script is named directly (packs.sh, discover.py, and the scripts the shell
    verbs call: packs_link.py is packs link|unlink and project_link.py is project link|unlink in any use, packs_audit.py store is skill accept|unaccept, marshal_handoff.py is marshal handoff,
    linker.py (the link engine) is packs link in any use, and render.py (it can run the command a definition names) is refused in any use;
    the last two have names a project may use for its own scripts, so only the files in the lib directory of the tool or of the installed
    copy count, found from the directory the command runs in);
  - qargi project init (it stores a whole answers file, so it is a way to models.extensions and models.accept_no_barrier, which have gated verbs;
    found like the skill verbs), and qargi project set of any models answer (the other answers stay open). A project verb the guard cannot read is
    refused: set with a path that is missing or built by xargs, a variable, a substitution, a brace or a glob; and any command with the word project,
    link, unlink, set or init after it and a shell expansion or xargs in the segment (found again inside `sh -c` and `eval` strings with the quotes
    taken off, so a quote or a backslash inside the verb does not hide it). Whatever the verb would have said, it is not read. lib/gated_answers.py, the store behind
    provider enable|disable|accept (no environment variable or option opens project set to the two keys any more), is refused in any use;
  - setting QARGI_NESTED (it makes some verbs skip their plan-token check);
  - a write under a protected location: the pack library ($QARGI_CONF/packs, else $QARGI_HOME/config/packs, else
    ~/.qargi/config/packs; the earlier ~/.config/qargi/packs, also under $XDG_CONFIG_HOME, stays protected), the credentials
    directory and install.json of the same configuration directories (not the rest of it: a member may run qargi verbs that
    change instances, agents or projects; the guard decides by the path a write construct names, never by the verb, and a
    read of a protected path stays allowed), the skills and agents directories the provider definitions name in their resources (user_dir, below
    the home: for Claude Code ~/.claude/skills and ~/.claude/agents; project_dir, found in any path outside the run's clone, a project's
    installed ones: .claude/skills and .claude/agents), ~/.claude/plugins, and the installed copy of the tool (the tool_root in install.json:
    the skills there are linked from ~/.claude/skills), and the claude/ and render/ directories of the state (the renders a runtime loads
    its skills, tools and members from; the claude/ one is what `packs apply --target claude-code` makes). Inside the clone, found from the nearest `qargi local
    prepare` run directory, a project directory such as .claude/skills is the work product and stays writable; the path is resolved first, so a
    symbolic link in the clone that leads to a protected root is still denied. Edit, Write and
    NotebookEdit are decided by the resolved path (symbolic links followed). A Bash command is decided by a heuristic:
    a command that names a protected path as the destination of a write construct: a redirection (also `>file`
    without a space), tee, cp, mv, rm, ln, install, rsync, touch, mkdir, chmod, chown, truncate, shred, patch,
    `sed|perl -i`, `dd of=`, a git command that changes the tree, find with -delete or -exec, and any argument of
    tar, unzip, curl or wget. `~`, $HOME, $QARGI_CONF and cd are followed. What an agent edits in its own clone, the
    repository's `skills/` directory included, and in its run directories stays allowed: protection is by the
    resolved path relative to the roots above, never by the word `skills`.
Provider: `qargi provider accept` (it records that the owner accepts a provider surface with no read-only barrier, which lets a
read-only role run there) is refused to a member, found like the skill verbs, and so is every other provider verb that changes the
definitions (new, import, seal, remove, rename, enable, disable, attest, migrate, and any verb added later: only the ones in
PROVIDER_READ, list, show, effective, require-barrier, skills-dirs, of, layout, require-skills and launch, stay allowed).
Release: `qargi release publish` (it creates the GitHub release of a tag) is refused to a member, found like the skill verbs, also as a
verb held in a variable and through lib/release.sh; the other release verbs stay allowed (they need a plan token and approval of their own).
Marshal: the feature marshal (`qargi marshal`) is changed only by the lead. The guard refuses a member
  - the verbs that change it: qargi marshal claim|set|renew|release|take|takeover|finish|enable|disable, found like the skill verbs
    (after wrappers, in `sh -c`, `eval`, $(...), through a path to bin/qargi or marshal.sh). status and check stay allowed, and so
    does handoff, which only reads, unless it is given --write (that makes a file, as only the lead's session may) or an argument
    held in a variable (it could be --write); any other verb,
    none, or one held in a variable is refused (fail closed);
  - the feature verbs that write the marshal: qargi feature start|finish|verify (start and finish create and finish the lead's record
    and push it with the lead's credentials, verify keeps the lease renewed), found the same way. list, status, merge and sync stay
    allowed (merge and sync only ask the marshal); any other verb or one held in a variable is refused. The marshal itself tells a
    member run only by the working directory, so this refusal covers a member whose directory lies outside its run;
  - a write under the features/ directory of the state ($QARGI_STATE, else <root>/state, and ~/.qargi/state), where the
    marshal keeps one record per open feature (and, beside them, the `.observed-<project>.json` clock cache of the shared-refs
    backend): decided like the other protected roots, reading stays allowed;
  - a write under the marshal/ directory of the state, where `marshal enable` keeps the per-project `.enabled` switch of the
    shared-refs backend: found and decided like features/, reading stays allowed;
  - a write to the ref journal of the state ($QARGI_STATE/ref-journal.jsonl, its lock and any rotated or temporary file next to
    it, e.g. ref-journal.jsonl.lock, .1, .tmp): the lead's record of the branch moves its own verbs made, which `qargi local verify`
    accepts as lead-side changes. Decided like features/; reading stays allowed. The journal is trusted only as far as the state
    directory is: an executor running as the same OS user could still edit the file by code the guard cannot see (HMAC-signed
    records are a later feature);
  - the verbs of the signed records: qargi marshal key|signers|resign (the lead's signing key, the allowed signers, a record signed
    with the key), refused with their own reason; and a write to the allowed signers ($QARGI_STATE/marshal/<project>.signers, under
    the marshal/ root above) or to the acceptance marks ($QARGI_STATE/features/.accepted-<project>.json, under features/), which the
    refusal names;
  - setting or unsetting QARGI_LEAD (the lead identity): an assignment, export, declare, unset or env -u in a command.
Signing key: the one credential a member may not even read is the lead's signing key for the marshal records,
  credentials/marshal_* (the private key and its public half) in any of the configuration directories above. The guard refuses
  the Read, NotebookRead and Grep tools on it, and a Bash segment with any word that names it: after ~ and variables, braces,
  globs and symbolic links are resolved, in a `<` redirection, an `--opt=path` and in the text of a `-c` program. A directory that holds the key
  is refused to the recursive readers (cp, rsync, tar, grep, rg, zip, find with an action) and to Grep. ls, stat and test only
  look at it and stay allowed; the other credentials stay readable.
  pushd and popd are followed like cd (a directory stack), a text scan reads `dir//key` and `dir/./key` as `dir/key`, and ln, mv and cp -s|-l
  are refused on a credentials directory (or a directory above one) as the recursive readers are, since a link made in the same command
  is a name the guard cannot resolve yet.
Residual for marshal handoff: xargs in front of it is refused (its arguments come from standard input), but other ways to build a command line the
guard does not parse (a shell loop that reads a file, `parallel`, a script written earlier) are not seen; the redirect form `... < args` into a
loop is accepted as residual, and `qargi local verify` and the lead's review of the output are what catch a note written by a member.
Not covered: code that writes or reads a file itself (python -c, perl -e, node -e, a script written earlier and run) unless it
names the key by its full path, a glob that expands to a protected path (for a write), a path built from a variable the guard cannot see
(a directory assigned to a variable earlier in the command, d=...; cat $d/marshal_ed25519; a name produced by a command substitution,
cat $(echo ...), or by an echo piped to xargs). A heredoc line that starts with a
refused verb is refused even as text (use the Write tool for documents).

Failure: the guard fails closed. Any unexpected exception ends in exit 2 with the reason on stderr. Input that is not
JSON is still let through (exit 0), as before. Known limits outside this file, from the Claude Code hooks documentation
(https://code.claude.com/docs/en/hooks): a hook that cannot start, exits other than 0 or 2, times out or prints invalid
JSON is a non-blocking error ("The action goes ahead, except for hooks whose failure blocks the action, for example a
hook with `onFailure` set to \"block\""), so agents/member.md sets `onFailure: "block"` and a `timeout` (`onFailure`
"Requires Claude Code v2.1.295 or later"; an older version does not enforce it). Frontmatter hooks of a project-level
agent file run only after the workspace trust dialog is accepted (https://code.claude.com/docs/en/sub-agents): until
then the subagent runs without this guard."""
import collections, glob, json, os, re, shlex, sys

SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
SUBST = re.compile(r"\$\(|`")                               # command substitution starts a command of its own
HANDOFF_SUBST = re.compile(r"(?:marshal(?:\.sh)?[\"']*\s+[\"']*handoff|marshal_handoff\.py)[\"']*[^;&|\n]*(?:\$\(|`)")   # `marshal handoff ... $(...)`: the substitution may produce --write, and splitting it off hides that
PROJECT_SET_SUBST = re.compile(r"project(?:\.sh)?[\"']*\s+[\"']*set[\"']*\s[^;&|\n]*(?:\$\(|`)")   # `project set ... $(...)`: the substitution may produce a models path, and splitting it off hides that
AUDIT_SUBST = re.compile(r"packs_audit\.py[\"']*[^;&|\n]*(?:\$\(|`)")   # `packs_audit.py ... $(...)`: the substitution may produce `store`, and splitting it off hides that
UNREADABLE = "$`{}*?[]"                                     # in a word: a variable, a substitution, a brace or a glob builds it, so the guard cannot read what it is
PROJECT_VERBS = ("set", "init", "link", "unlink")           # the project verbs a member may not run (set: the models answers; init: the whole file; link, unlink: what a session loads)
WRAP = {"sudo", "env", "command", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice"}
WRITERS = {"rm", "rmdir", "touch", "mkdir", "chmod", "chown", "truncate", "tee", "patch", "unlink", "shred"}
COPIERS = {"cp", "mv", "ln", "install", "rsync"}            # the last argument is the destination
INPLACE = {"sed", "perl"}                                   # with -i
GIT_WRITES = {"add", "commit", "apply", "am", "checkout", "switch", "reset", "rm", "mv", "stash", "merge", "rebase",
              "cherry-pick", "revert", "restore", "clean", "tag", "branch", "pull", "fetch", "init", "clone", "worktree",
              "notes", "update-ref", "config", "submodule"}
REDIR = re.compile(r"^(?:\d*|&)>>?(.*)$")

SKILL_VERBS = {"new", "import", "seal", "remove", "unlink", "link", "enable", "disable", "accept", "unaccept"}
SCRIPTS = ("qargi", "packs.sh", "discover.py", "cloud.py", "upgrade.sh", "marshal.sh", "feature.sh", "provider.py", "provider.sh",
           "memory.sh", "tierwrite.sh", "tierplan.py", "memplan.py", "packs_link.py", "project_link.py", "gated_answers.py", "project.sh", "packs_audit.py", "marshal_handoff.py", "linker.py", "render.py", "local_run.py", "local.sh", "release.sh")
# the command and the scripts behind the refused verbs (packs_link.py is packs link|unlink, packs_audit.py store is skill accept|unaccept,
# marshal_handoff.py is marshal handoff: the shell verbs call them, and a member could call them directly with a hand-made inputs file;
# linker.py, the link engine packs_link.py calls, is packs link, and render.py renders member definitions and runs the command a definition names)
OWN_ONLY = ("linker.py", "render.py")                       # names too common to refuse by name alone: only the file of the tool is the script (own_script)
# Known limit, by design: the scripts are recognized by the NAME the command gives. `python3 LINK` where LINK is a symlink to lib/linker.py or
# lib/render.py, a copy of them under another name, and `python3 -c 'import linker'` (with lib on the path) are not recognized. A check on the
# resolved path would catch only a link that already exists when the call is judged, not one made earlier in the same command line
# (`ln -s .../linker.py x && python3 x`), and an import can be spelled in too many ways (importlib, __import__, string joins) to read from
# the command text; a half check would suggest a guarantee the guard does not give. Like the rest of the shell reading it is a heuristic
# against a mistake, not a wall against a member that works to get round it; the local verify of the patches is the backstop.
MEMORY_VERBS = ("init", "move", "split", "merge", "copy")                          # qargi memory verbs that change a memory tier
MEMORY_READ = ("tiers", "check", "get", "lint")
PROVIDER_READ = ("", "list", "show", "effective", "require-barrier", "skills-dirs", "of", "layout", "require-skills", "launch")   # the provider verbs that only read; the rest, and any verb added later, change the definitions
MEMORY_NOTE = "propose it in your report"
MARSHAL_MUTATING = ("claim", "set", "renew", "release", "take", "takeover", "finish", "enable", "disable")
MARSHAL_READ = ("status", "check", "handoff")                # handoff only reads; with --write it makes a file and is refused (skill_verb)
MARSHAL_SIGNING = {"key": "manages the marshal's signing key", "signers": "manages the marshal's allowed signers",
                   "resign": "signs a marshal record with the lead's key"}      # the verbs of the signed records, each refused with its own reason
FEATURE_OPEN = ("", "list", "status", "merge", "sync")       # the feature verbs that do not write the marshal (the rest does, or is unknown)
LEAD_BUILTINS = {"export", "declare", "typeset", "readonly", "local", "unset", "env", "read", "printf", "set", "let"}
MARSHAL_NOTE = "the lead changes the marshal; report it in your task output"
KEY_NOTE = "the signing key is the lead's alone; report it in your task output"
KEY_PREFIX = "marshal_"                                      # the lead's signing key and everything named like it in a credentials directory
KEY_METADATA = {"ls", "stat", "test", "[", "[["}            # these only look at a file's existence and size, never at its content
KEY_RECURSIVE = {"cp", "rsync", "tar", "grep", "egrep", "fgrep", "rg", "ag", "find", "zip", "7z", "7za", "7zr"}   # a directory named to these is read whole
KEY_LINKERS = {"ln", "mv"}                                  # a link to the directory (or a move of it) makes the key reachable by a name the guard has not seen
LINK_FLAGS = re.compile(r"^-[A-Za-z]*[sl][A-Za-z]*$")       # cp -s, -l, -rs: a symbolic or hard link instead of a copy
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


def read_provider(argv):
    """The provider the hook command line names with --provider NAME: None when it names none, "" when the name is missing."""
    if "--provider" not in argv:
        return None
    k = argv.index("--provider")
    return argv[k + 1] if k + 1 < len(argv) else ""


CLASS = ""
CLASSES = ("", "read-only")


def is_review(run):
    """True when the member is read-only by class (its hook) or the run directory says so (its class file, or the review role)."""
    return CLASS == "read-only" or ability_of(run) == "review" or run_class(run) == "read-only"


def control_refusal(full):
    """The reason a write to a run directory's control file (ability, class, profile, refs.before) is refused, or None."""
    if os.path.basename(full) in ("ability", "class", "profile", "refs.before") and run_dir(os.path.dirname(full)) == os.path.dirname(full):
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


def review_refusal(call):
    """The reason a call under the review ability is refused, or None."""
    cwd = call.cwd
    if call.kind == "write":
        fp = call.path
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
    if call.kind != "shell":
        return None
    here = cwd
    for seg in SEGMENT.split(call.command):
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


class MemoryReason(MarshalReason):
    """A refusal about a memory tier: decide() prints it as it is (it carries its own advice)."""


def conf_dirs(P, home):
    """The configuration directories a qargi installation may keep its packs, credentials and install record in."""
    return (P.conf(), os.path.join(P.root(), "config"), os.path.join(home, ".qargi", "config"), P.legacy_conf(), os.path.join(home, ".config", "qargi"))


_RESOURCE_DIRS = []
# The directories of Claude Code, the runtime qargi was built for. They are held whatever the library says: a definition of that name that
# clashes with the shipped one (or is broken) is skipped below, and its directories must not drop out of the protection with it.
CLAUDE_RESOURCE_DIRS = ((".claude", "skills"), (".claude", "agents")), ("~/.claude/skills", "~/.claude/agents")


def resource_dirs():
    """(project, user): the skills and agents directories that the resources of every provider definition name (the shipped ones and the
    library's, every surface), and those of Claude Code. project: tuples of path components (".claude/skills" is (".claude", "skills")),
    found anywhere in a path; user: real directories below the home. A path that cannot be one (absolute, with .., a user path not below
    ~/) is left out. Read once per call of the hook. A definition that does not load (unreadable, a name clash, a name that disagrees with
    its directory) is skipped with one note on standard error: its directories are unknown, but one broken file of the library must not
    make the guard refuse every write, and the roots of the definitions that do load stay (the roots only add up)."""
    if not _RESOURCE_DIRS:
        provider = _provider()
        home = os.path.expanduser("~")
        project = [tuple(c) for c in CLAUDE_RESOURCE_DIRS[0]]
        user = [os.path.join(home, u[2:]) for u in CLAUDE_RESOURCE_DIRS[1]]
        skipped = []
        for name in provider.names():
            try:
                defs = list(provider.definitions_unsealed(name).values())   # unsealed or changed packs too: what they name stays protected
            except Exception as e:
                skipped.append("%s (%s)" % (name, str(e).splitlines()[0][:100] if str(e) else type(e).__name__))
                continue
            for doc in defs:
                res = doc.get("resources")
                for kind in ("skills", "agents"):
                    r = res.get(kind) if isinstance(res, dict) else None
                    r = r if isinstance(r, dict) else {}
                    d, u = r.get("project_dir"), r.get("user_dir")
                    comps = tuple(c for c in os.path.normpath(d).split("/") if c not in ("", ".")) if isinstance(d, str) and d else ()
                    if comps and not d.startswith(("/", "~")) and ".." not in comps and comps not in project:
                        project.append(comps)
                    if isinstance(u, str) and u.startswith("~/") and len(u) > 2 and os.path.join(home, u[2:]) not in user:
                        user.append(os.path.join(home, u[2:]))
        if skipped:
            print("qargi guard: provider definitions skipped, their skills and agents directories are not protected: %s" % "; ".join(skipped), file=sys.stderr)
        _RESOURCE_DIRS.append((project, user))
    return _RESOURCE_DIRS[0]


def protected_roots():
    """The locations whose content is a skill, the library of them, a credential or the install record (real paths)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import paths as P                                     # here, not at the top: an import failure is then a refusal (see main)
    home = os.path.expanduser("~")
    # the library where the data lives now, the default and the QARGI_HOME one beside an override, and the earlier XDG
    # libraries, which stay as a backup after `qargi migrate home`
    # Besides the library, only the credentials and the install record of each configuration directory: not the rest of
    # <conf> (instances, agents, projects, profiles), which qargi verbs a member runs legitimately change.
    # The user's skills and agents directories are the ones the definitions name. No resource names a plugins directory yet, so the one
    # of Claude Code is kept here.
    roots = set(resource_dirs()[1]) | {os.path.join(home, ".claude", "plugins")}
    # (the live configuration directory is one of these: QARGI_CONF, QARGI_HOME/config or ~/.qargi/config)
    for conf in conf_dirs(P, home):
        roots.update(os.path.join(conf, name) for name in ("packs", "credentials", "install.json"))
    roots.add(os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config"), "anthropic"))   # the ant profiles and logins
    # the installed copy of the tool: ~/.claude/skills/qargi-* are links into it, and a write through such a link resolves
    # here, so it must be a root itself (it holds the skills, the member definition and the roles a member is launched with)
    installed = P.installed_tool_root()
    if installed:
        roots.add(installed)
    roots.update(claude_render_roots(P, home))
    roots.update(render_roots(P, home))
    roots.update(providers_state_roots(P, home))
    roots.update(feature_roots(P, home))
    roots.update(switch_roots(P, home))
    roots.update(journal_roots(P, home))
    roots.update(memory_roots(P, home))
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


def render_roots(P=None, home=None):
    """The render/ directory of the state: where the renders of every runtime go (state/render/<project>/<runtime>: skills, tools and
    members as a runtime loads them). Found as claude_render_roots does."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "render")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def providers_state_roots(P=None, home=None):
    """The providers/ directory of the state: the verification records (verified.json) that decide which capabilities of a library
    runtime count. Written only by `provider check` and `provider attest`. Found as render_roots does."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "providers")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def feature_roots(P=None, home=None):
    """The features/ directory of the state: the marshal's record of each open feature. Found as claude_render_roots does."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "features")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def switch_roots(P=None, home=None):
    """The marshal/ directory of the state: the per-project `.enabled` switch files of the shared-refs backend. Found as
    feature_roots does."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, "marshal")) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def memory_roots(P=None, home=None):
    """The memory tiers qargi keeps by default: <root>/memory (project, shared and system) and ~/.qargi/memory. Reading stays
    allowed; a tier placed elsewhere by the project's answers is not guarded."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(r, "memory")) for r in (P.root(), os.path.join(home, ".qargi"))}


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
    name = os.path.basename(dest.rstrip("/"))
    if root in feature_roots() and name.startswith(".accepted-"):
        return MarshalReason("%s on %s would change %s, the marshal's acceptance marks (the newest signed record this machine has accepted, "
                             "which a rollback is measured against); %s" % (what, dest, root, MARSHAL_NOTE))
    if root in feature_roots():
        return MarshalReason("%s on %s would change %s, the marshal's record of the open features; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in switch_roots() and name.endswith(".signers"):
        return MarshalReason("%s on %s would change %s, the marshal's allowed signers (the keys whose records are accepted); %s"
                             % (what, dest, root, MARSHAL_NOTE))
    if root in switch_roots():
        return MarshalReason("%s on %s would change %s, the marshal's per-project switch of the shared-refs backend; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in memory_roots():
        return MemoryReason("%s on %s would change %s, a memory tier; %s" % (what, dest, root, MEMORY_NOTE))
    if root in claude_render_roots():
        return ("%s on %s would change %s, the render of a project's skills and tools that Claude Code loads; it is managed by "
                "`qargi packs apply` and changed only by the lead" % (what, dest, root))
    if root in render_roots():
        return ("%s on %s would change %s, the render of a project's skills, tools and members that a runtime loads; it is managed by "
                "qargi and changed only by the lead" % (what, dest, root))
    return "%s on %s would change %s, a protected location (skills, the pack library, credentials)" % (what, dest, root)


# --- the signing key: a read of it is refused (a read of the other credentials stays allowed)

_KEY_DIRS = []


def key_dirs():
    """The credentials directories (real paths) that may hold the lead's signing key, found like the protected roots (once per call of the hook)."""
    if not _KEY_DIRS:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
        _KEY_DIRS.append({os.path.realpath(os.path.join(c, "credentials")) for c in conf_dirs(P, os.path.expanduser("~"))})
    return _KEY_DIRS[0]


def is_key(full):
    return os.path.basename(full).startswith(KEY_PREFIX) and os.path.dirname(full) in key_dirs()


def holds_key(full):
    """True when the real path full is a credentials directory with a signing key in it, or a directory above one."""
    return any(inside(d, full) and glob.glob(os.path.join(glob.escape(d), KEY_PREFIX + "*")) for d in key_dirs())


def brace_expand(word, limit=64):
    """The words a simple shell brace expression stands for (a{b,c}d -> abd, acd); one level per pass, at most limit words."""
    words, out = [word], []
    while words and len(out) < limit:
        w = words.pop()
        m = re.search(r"\{([^{}]*,[^{}]*)\}", w)
        if not m:
            out.append(w)
        else:
            words += [w[:m.start()] + alt + w[m.end():] for alt in m.group(1).split(",")]
    return out


def key_named(word, here, recursive):
    """The signing key (or, for a recursive reader, a directory holding it) that one shell word stands for, else None. The word
    is read with ~ and variables expanded, braces and globs expanded, symbolic links followed; `--opt=path`, `-Opath` and a
    `<path` redirection are read as their path too."""
    cands = {word, word.lstrip("<"), word.split("=", 1)[-1]}
    if word.startswith("-") and not word.startswith("--"):
        cands.add(word[2:])
    for c in cands:
        if not c or c.startswith("-"):
            continue
        for b in brace_expand(os.path.expandvars(os.path.expanduser(c))):
            plain = re.sub(r"/(?:\./)+", "/", re.sub(r"/{2,}", "/", b))        # dir//key and dir/./key are the path dir/key
            if any(d + os.sep + KEY_PREFIX in plain for d in key_dirs()):     # a path inside text, e.g. python -c "open('...')"
                return b
            paths = glob.glob(os.path.join(here, b))[:200] if re.search(r"[*?\[]", b) else []
            for full in [os.path.realpath(os.path.join(here, b))] + [os.path.realpath(x) for x in paths]:
                if is_key(full) or (recursive and holds_key(full)):
                    return b
    return None


def key_refusal_text(prog, word, tool=None):
    return MarshalReason("%s on %s would read the marshal's signing key (credentials/%s*); %s" % (tool or prog, word, KEY_PREFIX, KEY_NOTE))


def key_read(toks, i, here):
    """The reason a Bash segment reads the lead's signing key, or None: any word of it that names the key, whatever the program."""
    prog, rest = os.path.basename(toks[i]), toks[i + 1:]
    if prog in KEY_METADATA:
        return None
    recursive = prog in KEY_RECURSIVE and (prog != "find" or any(t in FIND_ACTIONS for t in rest))
    recursive = recursive or prog in KEY_LINKERS or (prog == "cp" and any(LINK_FLAGS.match(t) or t in ("--symbolic-link", "--link") for t in rest))
    for t in [toks[i]] + rest if any(d + os.sep + KEY_PREFIX in toks[i] for d in key_dirs()) else rest:    # a `;` in quoted code split it: its tail is a "program"
        named = key_named(t, here, recursive)
        if named:
            return key_refusal_text(prog, named)
    return None


def in_clone(full):
    """True when the real path full lies inside the clone of the nearest run directory `qargi local prepare` made. A
    clone is made from repository content, so a .claude/skills there is the work product (reviewed as a patch), not an
    installed skill. Call it only with a resolved path: a symbolic link in the clone has then already been followed."""
    run = run_dir(os.path.dirname(full)) or run_dir(full)
    return bool(run) and inside(full, os.path.join(os.path.realpath(run), "clone"))


def protected(full, destructive=False):
    """The protected location a real path belongs to, or None. A destructive command (rm, mv) also reaches a directory
    that holds one. A project's own skills and agents directories (.claude/skills and .claude/agents for Claude Code; resource_dirs
    has the others) are found by their path components, wherever the project is; the repository's `skills/` directory is not
    protected, nor is anything inside the run's clone (see in_clone) unless it resolves into a named root."""
    for r in protected_roots():
        if inside(full, r) or (destructive and inside(r, full)):
            return r
    j = journal_sibling(full)
    if j:
        return j
    if in_clone(full):          # after the named roots: a link in the clone that leads to one was resolved and is denied above
        return None
    parts = full.split(os.sep)
    for comps in resource_dirs()[0]:          # a project's installed skills and member definitions (the latter hold the hook that guards a member)
        n = len(comps)
        if any(tuple(parts[k:k + n]) == comps for k in range(len(parts) - n + 1)):
            return "/".join(comps)
        # a destructive command on a directory above one of them: rm -rf .claude, with .claude/skills in it
        if destructive and any(tuple(parts[-m:]) == comps[:m] and os.path.isdir(os.path.join(full, *comps[m:])) for m in range(1, n)):
            return "/".join(comps)
    return None


def skill_refusal(call):
    """The reason a call would change a skill (or let an agent skip a plan token), or None."""
    fp = call.path
    if call.kind == "write":
        root = protected(resolve(call.cwd, fp)) if fp else None
        return refusal_text(call.name, fp, root) if root else None
    if call.kind in ("read", "search"):                  # the read tools: the signing key, alone or in a directory the search reaches
        full = resolve(call.cwd, fp) if fp else ""
        return key_refusal_text(call.name, fp) if full and (is_key(full) or (call.kind == "search" and holds_key(full))) else None
    if call.kind != "shell":
        return None
    return bash_skill_refusal(call.command, call.cwd, 0)


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
    if HANDOFF_SUBST.search(command):
        return MarshalReason("qargi marshal handoff with a command substitution in its arguments could be given --write, which writes a file and is not available to an agent; %s"
                             % MARSHAL_NOTE)
    if PROJECT_SET_SUBST.search(command):
        return "qargi project set with a command substitution in its arguments takes a path the guard cannot read, which could be a models answer, and is not available to an agent"
    if AUDIT_SUBST.search(command):
        return "qargi skill accept (packs_audit.py with a command substitution in its arguments could be `store`) changes a skill and is not available to an agent"
    segs = SEGMENT.split(SUBST.sub(";", command))
    stack = []                                           # the directories pushd left behind
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
        if prog == "pushd":                              # like cd, and popd goes back; -n changes the stack only, and the words are read as paths either way
            dirs = [t for t in rest if not t.startswith("-") and not t.startswith("+")]
            if dirs and "-n" not in rest:
                stack.append(here)
                here = resolve(here, dirs[0])
            continue
        if prog == "popd":
            if stack and "-n" not in rest:
                here = stack.pop()
            continue
        if prog in ("export", "declare", "typeset", "readonly") and any(t.split("=")[0] == "QARGI_NESTED" for t in rest):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        why = skill_verb(prog, rest, via_xargs=any(os.path.basename(t) == "xargs" for t in toks[:i]), here=here, exe=toks[i])
        if why:
            return why
        inner = shell_string(prog, rest) if depth < 3 else None
        if inner is not None:          # a `;` inside the quoted string split it: read the segments that follow as part of it
            inner += " ; " + " ; ".join(segs[n + 1:]).replace('"', " ").replace("'", " ")
            why = bash_skill_refusal(inner, here, depth + 1)
            if why:
                return why
        why = protected_write(toks, i, here) or key_read(toks, i, here)
        if why:
            return why
    return unreadable_project_verb(command)


def lex(seg):
    """The words of a command segment as the shell would cut them, each with whether the shell expands it: [(word, bool)]. Quotes are taken off and a
    backslash makes the next character plain; a variable or a substitution expands outside single quotes, a brace or a glob outside any quote."""
    out, cur, expands, started, quote, k = [], [], False, False, "", 0
    while k < len(seg):
        c = seg[k]
        if quote == "'":
            if c == "'":
                quote = ""
            else:
                cur.append(c)
        elif c == "\\" and k + 1 < len(seg):
            k += 1
            if quote == '"' and seg[k] not in '$`"\\':
                cur.append("\\")
            cur.append(seg[k])
        elif c == "'" and quote == "":
            quote, started = "'", True
        elif c == '"':
            quote, started = ("" if quote else '"'), True
        elif c in "$`":
            cur.append(c)
            expands = True
        elif quote == "" and c in UNREADABLE:
            cur.append(c)
            expands = True
        elif quote == "" and c.isspace():
            if cur or started:
                out.append(("".join(cur), expands))
            cur, expands, started = [], False, False
        else:
            cur.append(c)
        k += 1
    if cur or started:
        out.append(("".join(cur), expands))
    return out


def unreadable_project_verb(command):
    """The reason a command runs a `project` verb the guard could not read, or None. The verbs are read from the words of each segment; a quote, a
    substitution, xargs, a brace or a glob can hide which one it is or what it is given. A segment with the word project, one of PROJECT_VERBS after
    it (or a word in the place of the verb that the shell expands), and any expansion in the segment, or xargs in front, is refused whatever it would
    turn out to say. A segment that hands a string to a shell (sh -c, eval) is read again with every quote and backslash taken off, since the string
    is cut into words once more there. This runs after the readable forms were judged (their reasons are the better ones), and does not look at a
    program held in a variable (the limit of the whole guard)."""
    for seg in SEGMENT.split(command.replace("\\\n", "")):
        forms = [seg]
        if any(os.path.basename(w) in SHELLS or w == "eval" for w, _ in lex(seg)):
            forms.append(re.sub(r"[\\'\"]", "", seg))
        for form in forms:
            words = lex(form)
            names = [re.sub(r"[)`;&]+$", "", w) for w, _ in words]
            for k, w in enumerate(names):
                if os.path.basename(w) not in ("project", "project.sh"):
                    continue
                rest = [(n, e) for n, (_, e) in zip(names[k + 1:], words[k + 1:]) if not n.startswith("-")]
                named = [n for n, _ in rest[:3] if n in PROJECT_VERBS]
                if (named or (rest and rest[0][1])) and (any(e for _, e in words) or any(os.path.basename(n) == "xargs" for n in names[:k])):
                    return ("qargi project %s with a variable, a substitution, a brace, a glob or xargs in the command takes words the guard cannot read, and project set of a models answer, "
                            "project init and project link are not available to an agent" % (named[0] if named else "(a verb the shell builds)"))
    return None


def shell_string(prog, rest):
    """The command text a shell is given to run (sh -c STRING, eval STRING), or None. The quotes left in the string are dropped, which
    is conservative: the text is then read as plain words, and a quote inside a word (pro''ject) joins it as the shell would. A `\\$` or
    `\\`` is read as the expansion it would be for the inner shell (shlex keeps the backslash a double-quoted outer string had before it)."""
    if prog == "eval":
        text = " ".join(rest)
    elif prog in SHELLS:
        text = next((" ".join(rest[k + 1:]) for k, t in enumerate(rest) if SHELL_C.match(t)), None)
    else:
        return None
    return None if text is None else text.replace('"', "").replace("'", "").replace("\\$", "$").replace("\\`", "`")


def own_script(path, here):
    """True when path, named from the directory here, is a file in the lib directory of this tool or of the installed copy (real paths)."""
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import paths as P
    installed = P.installed_tool_root()
    libs = {os.path.dirname(os.path.realpath(os.path.abspath(__file__)))} | ({os.path.join(installed, "lib")} if installed else set())
    return os.path.dirname(resolve(here, path)) in libs


def skill_verb(prog, rest, via_xargs=False, here=".", exe=None):
    """The reason a qargi command (or the script behind it, run directly) is a verb that changes a skill, or None. via_xargs: xargs
    stands before the program, so its arguments come from standard input, where --write could be. here: the directory the command runs
    in, and exe: the word that names the program, for the scripts that are only the tool's own (OWN_ONLY)."""
    words = [t for t in rest if not t.startswith("-")]
    name, script = prog, exe or prog
    if prog not in SCRIPTS:
        if (prog in SHELLS or re.match(r"^python[0-9.]*$", prog)) and words and os.path.basename(words[0]) in SCRIPTS:
            name, script, words = os.path.basename(words[0]), words[0], words[1:]
        else:
            return None
    if name in OWN_ONLY and not own_script(script, here):
        return None
    if name == "linker.py":                              # the engine behind packs link and unlink: any use of it is the verb
        words = ["packs", "link"]
    if name == "render.py":
        return "lib/render.py is the renderer of member definitions and can run the command a definition names; it is not available to an agent"
    if name == "discover.py":
        words = ["discover"] + words
    if name == "cloud.py":
        words = ["cloud"] + words
    if name == "upgrade.sh":
        words = ["upgrade"] + words
    if name == "marshal.sh":
        words = ["marshal"] + words
    if name == "feature.sh":
        words = ["feature"] + words
    if name == "release.sh":
        words = ["release"] + words
    if name == "packs_link.py":                          # plan and apply both: any use of the script is the verb (the shell makes its inputs)
        words = ["packs", "unlink" if "unlink" in words[:2] else "link"]
    if name == "project_link.py":                        # plan, apply and members-dir alike: any use of the script is the verb (the shell checks the plan token)
        words = ["project", "unlink" if "unlink" in words[:2] else "link"]
    if name == "local_run.py":                           # any use of the script is `local run`
        words = ["local", "run"]
    if name == "local.sh":
        words = ["local"] + words
    if name == "project.sh":
        words = ["project"] + words
    if name == "gated_answers.py":                       # the store behind provider enable|disable|accept, with no gate of its own: any use of the script is the verbs
        return "lib/gated_answers.py stores models.extensions and models.accept_no_barrier for the verbs that have a plan token (qargi provider enable, disable, accept) and is not available to an agent"
    if name == "packs_audit.py":                         # only `store` writes accepted.json; scan, report, target and acceptance read (scan and target write the file they are given)
        if words[:1] != ["store"] and not any("$" in w or "`" in w for w in words):
            return None
        words = ["skill", "unaccept" if "unaccept" in words[:2] else "accept"]
    if name == "marshal_handoff.py":
        words = ["marshal", "handoff"] + words
    if name in ("provider.py", "provider.sh"):
        words = ["provider"] + words
    if name in ("tierplan.py", "memplan.py"):          # apply writes the tiers and plan-init/plan-move write a plan file; plan (--out) writes a plan file; show only reads
        return MemoryReason("%s %s changes a memory tier and is not available to an agent; %s" % (name, words[0], MEMORY_NOTE)) \
            if words[:1] in (["apply"], ["plan-init"], ["plan-move"], ["plan"]) else None
    if name in ("memory.sh", "tierwrite.sh"):
        words = ["memory"] + words
    area, verb = (words + ["", ""])[:2]
    if area == "memory" and words[1:2] != [] and (verb in MEMORY_VERBS or (verb not in MEMORY_READ and any(w in MEMORY_VERBS for w in words[1:4]))):
        which = verb if verb in MEMORY_VERBS else next(w for w in words[1:4] if w in MEMORY_VERBS)
        return MemoryReason("qargi memory %s changes a memory tier and is not available to an agent; %s" % (which, MEMORY_NOTE))
    if area == "project" and verb in ("link", "unlink"):
        return "qargi project %s changes what the checkout and the runtime's memory directory load (skills, agents, memory) and is not available to an agent" % verb
    if area == "project" and verb == "init":
        return "qargi project init stores a whole answers file (the models answers that choose the runtime and what counts as a barrier among them) and is not available to an agent"
    if area == "project" and verb == "set":
        # the models answers choose the runtime and what counts as a read-only barrier: they have gated verbs (provider enable, provider accept),
        # and project set has no plan token, so a member may not set any of them (the owner may). The path is the second word after set. A path
        # that is missing (a substitution split the command, or xargs brings the words), or that a variable, a substitution, a brace or a glob
        # builds, is not read here and is refused
        if via_xargs or len(words) <= 3 or any(c in words[3] for c in UNREADABLE):
            return "qargi project set takes a path the guard cannot read here (it is missing, or comes from xargs, a variable, a substitution, a brace or a glob), and a models answer is not available to an agent"
        path = words[3]
        if path == "models" or path.startswith("models."):
            return "qargi project set of %s changes which runtime the project uses or what counts as its barrier and is not available to an agent (qargi provider enable and qargi provider accept have a plan token)" % path
    if area == "provider" and verb == "accept":
        return "qargi provider accept records that you accept a provider with no read-only barrier and is not available to an agent"
    if area == "provider" and verb not in PROVIDER_READ:
        return "qargi provider %s changes the provider definitions and is not available to an agent" % verb
    if area == "release" and any(w == "publish" or "$" in w or "`" in w for w in words[1:4]):   # a verb held in a variable could be publish
        return "qargi release publish creates a GitHub release and is not available to an agent; report that the tag needs publishing"
    if area == "feature" and verb not in FEATURE_OPEN:
        return MarshalReason("qargi feature %s writes the feature marshal (the lead's record) and is not available to an agent (only %s are); %s"
                             % (verb, ", ".join(v for v in FEATURE_OPEN if v), MARSHAL_NOTE))
    if area == "marshal" and verb in MARSHAL_SIGNING:
        return MarshalReason("qargi marshal %s %s and is not available to an agent (only status, check and handoff without --write are); %s" % (verb, MARSHAL_SIGNING[verb], MARSHAL_NOTE))
    if area == "marshal" and verb == "handoff" and via_xargs:
        return MarshalReason("qargi marshal handoff through xargs takes arguments the guard cannot read (one could be --write, which writes a file) and is not available to an agent; %s"
                             % MARSHAL_NOTE)
    if area == "marshal" and verb == "handoff" and any(t == "--write" or t.startswith("--write=") or ("--write".startswith(t) and len(t) > 2 and t.startswith("--"))
                                                       or "$" in t or "`" in t for t in rest):
        return MarshalReason("qargi marshal handoff --write writes a file (or takes an argument it cannot read from a variable) and is not available to an agent (handoff without --write, status and check are); %s"
                             % MARSHAL_NOTE)
    if area == "marshal" and verb not in MARSHAL_READ:
        return MarshalReason("qargi marshal %s changes the feature marshal and is not available to an agent (only status, check and handoff without --write are); %s"
                             % (verb or "(no verb)", MARSHAL_NOTE))
    if (area in ("skill", "tool") and verb in SKILL_VERBS) or (area, verb) in (("discover", "install"), ("packs", "apply"), ("packs", "seed"), ("packs", "link"), ("packs", "unlink"), ("packs", "migrate-render"), ("local", "run")) \
            or (area == "import" and name == "qargi") or (area == "cloud" and verb in ("set", "unset", "login")) or area == "upgrade":
        if area == "upgrade":
            return "qargi upgrade changes the installed tool and its skills and is not available to an agent"
        if area == "cloud":
            return "qargi cloud %s changes which cloud workspace a project uses and is not available to an agent" % verb
        if area == "local":
            return "qargi local run starts the runtime's command for the lead, with the environment it names, and is not available to an agent"
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


# --- HOOK PROTOCOL: how a runtime's hook hands a call over and how it is told no. Data, not code: the decisions above and in judge()
# see only a Call. The data has the keys of a definition's barrier.hook (the provider schema):
#   input          "json-stdin": the hook's input is one JSON document on standard input
#   tool_pointer   JSON pointer to the name of the tool; command_pointer: to the shell command; cwd_pointer: to the working directory
#   path_pointers  the pointers to the path a tool names, tried in order and the first that is set is used: a list for every tool, or
#                  a map of a kind to its list (a search tool without its own list uses the one of read)
#   tool_names     kind -> tool names. shell: runs a command; write: changes the file it names; read: reads the file it names; search:
#                  reads like read and also reaches the directory it names. A call that names no tool is a shell command; a tool in
#                  no list is not judged
#   deny           how a refusal is given back: {"exit": N, "stream": "stderr"|"stdout"} prints the reason there, or {"exit": 0,
#                  "stdout": {...}} prints that JSON with "{reason}" replaced in every string; allow: {"exit": N}, the answer to a call that passes
# The data must be complete: tool_names.shell is listed, and every kind that lists a tool has a pointer for its path (hook_problem).
# The text of a refusal belongs to the decisions: the protocol only carries it.

Call = collections.namedtuple("Call", "kind name command path cwd")    # kind: shell, write, read, search or None; name: the runtime's name of the tool
KINDS = ("shell", "write", "read", "search")

CLAUDE_HOOK = {
    "input": "json-stdin", "tool_pointer": "/tool_name", "command_pointer": "/tool_input/command", "cwd_pointer": "/cwd",
    "path_pointers": {"write": ["/tool_input/file_path", "/tool_input/notebook_path"],
                      "read": ["/tool_input/file_path", "/tool_input/notebook_path", "/tool_input/path"]},
    "tool_names": {"shell": ["Bash"], "write": ["Edit", "Write", "NotebookEdit", "MultiEdit"], "read": ["Read", "NotebookRead"], "search": ["Grep"]},
    "deny": {"exit": 2, "stream": "stderr"}, "allow": {"exit": 0},
}


def pointer(doc, ptr):
    """The value a JSON pointer names in doc, or None where it is missing, null or empty on the way. A step into a value that is neither
    an object nor a list is an error (the caller ends it as a refusal), so a tool_input of the wrong type is not read as "nothing"."""
    cur = doc
    for key in ptr.split("/")[1:]:
        key = key.replace("~1", "/").replace("~0", "~")
        if not cur:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        elif isinstance(cur, list) and key.isdigit():
            cur = cur[int(key)] if int(key) < len(cur) else None
        else:
            raise TypeError("%s: a %s has no member %s" % (ptr, type(cur).__name__, key))
    return cur


def kind_of(hook, name):
    if not name:
        return "shell"
    for k in KINDS:
        if name in hook["tool_names"].get(k, ()):
            return k
    return None


def path_pointers(hook, kind):
    pp = hook.get("path_pointers") or []
    if isinstance(pp, dict):
        return pp.get(kind) or (pp.get("read") if kind == "search" else None) or []
    return pp if kind in ("write", "read", "search") else []


def parse_call(hook, data):
    """The neutral Call a hook's JSON stands for."""
    if not isinstance(data, dict):
        raise TypeError("the hook's input is not a JSON object")
    name = pointer(data, hook["tool_pointer"])
    command = pointer(data, hook["command_pointer"]) or ""        # read for every call: a tool_input that cannot be read is an error
    kind = kind_of(hook, name)
    path = next((v for v in (pointer(data, p) for p in path_pointers(hook, kind)) if v), "")
    cwd = (pointer(data, hook["cwd_pointer"]) if hook.get("cwd_pointer") else None) or os.getcwd()
    return Call(kind, name, command if kind == "shell" else "", path, cwd)


def fill(node, reason):
    """node with "{reason}" replaced by the reason in every string (JSON is built from the data, never by splicing text into it)."""
    if isinstance(node, str):
        return node.replace("{reason}", reason)
    if isinstance(node, list):
        return [fill(v, reason) for v in node]
    if isinstance(node, dict):
        return {k: fill(v, reason) for k, v in node.items()}
    return node


def refuse(hook, reason):
    """Give back a refusal in the hook's way; the exit status to end with."""
    deny = hook["deny"]
    if "stdout" in deny:
        print(json.dumps(fill(deny["stdout"], reason)))
    else:
        print(reason, file=sys.stdout if deny.get("stream") == "stdout" else sys.stderr)
    return deny["exit"]


HOOK_KEYS = ("input", "tool_pointer", "command_pointer", "cwd_pointer", "path_pointers", "tool_names", "deny", "allow")


class HookError(Exception):
    """The hook protocol of a provider cannot be used."""


def _provider():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import provider                                       # here, not at the top: an import failure is then a refusal (see main)
    return provider


def _is_pointer(v):
    return isinstance(v, str) and v.startswith("/") and len(v) > 1


def _is_exit(v):
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 255


def hook_problem(h):
    """What is wrong with hook protocol data (the barrier.hook of a definition), or None. A guard that misreads a call would pass it, so
    data that does not say everything the guard reads, or says more, is not used."""
    if not isinstance(h, dict):
        return "barrier.hook is not an object"
    for k in sorted(set(h) - set(HOOK_KEYS)):
        return "barrier.hook.%s is not a key of the hook protocol" % k
    if h.get("input") != "json-stdin":
        return "barrier.hook.input must be \"json-stdin\""
    for k in ("tool_pointer", "command_pointer") + (("cwd_pointer",) if "cwd_pointer" in h else ()):
        if not _is_pointer(h.get(k)):
            return "barrier.hook.%s must be a JSON pointer (it starts with /)" % k
    pp = h.get("path_pointers", [])
    lists = pp if isinstance(pp, dict) else {"": pp}
    if not (isinstance(pp, (list, dict)) and set(lists) <= set(KINDS) | {""}
            and all(isinstance(v, list) and all(_is_pointer(p) for p in v) for v in lists.values())):
        return "barrier.hook.path_pointers must be a list of JSON pointers, or a map of %s to such lists" % "/".join(KINDS)
    names = h.get("tool_names")
    if not (isinstance(names, dict) and set(names) <= set(KINDS) and all(isinstance(v, list) and all(isinstance(n, str) for n in v) for v in names.values())):
        return "barrier.hook.tool_names must be a map of %s to lists of tool names" % "/".join(KINDS)
    seen = [n for v in names.values() for n in v]
    for n in sorted(set(seen)):
        if seen.count(n) > 1:
            return "barrier.hook.tool_names: the tool %s is listed twice" % n
    # Complete, not only well formed: data that names a tool but not what to read from it would pass its calls unjudged (a write tool with
    # no path pointers names no path, so the write is allowed; a hook with no shell tool judges no command).
    if not names.get("shell"):
        return "barrier.hook.tool_names.shell must list the tool that runs a command (without it no command is judged)"
    for kind in ("write", "read", "search"):
        if names.get(kind) and not path_pointers(h, kind):
            return "barrier.hook.path_pointers must give at least one pointer for %s (tool_names lists %s)" % (kind, ", ".join(names[kind]))
    deny = h.get("deny")
    if not (isinstance(deny, dict) and _is_exit(deny.get("exit")) and (("stdout" in deny) != ("stream" in deny))
            and set(deny) <= {"exit", "stream", "stdout"} and (deny.get("stream") in ("stderr", "stdout") if "stream" in deny else isinstance(deny["stdout"], dict))):
        return "barrier.hook.deny must be {exit, stream: stderr|stdout} or {exit, stdout: {...}}"
    if not (isinstance(h.get("allow"), dict) and set(h["allow"]) == {"exit"} and _is_exit(h["allow"]["exit"])):
        return "barrier.hook.allow must be {exit: N}"
    # A refusal must be something the runtime can tell from a pass. The stream form gives the reason on a stream and nothing else, so its exit is
    # the only sign: the same exit as an allow is a refusal that every runtime reads as a pass. The stdout form is told by the JSON it prints, so that
    # JSON must be an object that carries the reason (a bare {} or one with no "{reason}" says nothing a runtime reads as a denial).
    if "stream" in deny and deny["exit"] == h["allow"]["exit"]:
        return "barrier.hook.deny.exit must differ from barrier.hook.allow.exit (a refusal that exits like an allow is read as an allow)"
    if "stdout" in deny and not _has_reason(deny["stdout"]):
        return "barrier.hook.deny.stdout must be a non-empty object with at least one string containing {reason} (otherwise a refusal says nothing a runtime reads as a denial)"
    return None


def _has_reason(node):
    """True when a string anywhere in node (a non-empty JSON value) contains the placeholder {reason}."""
    if isinstance(node, str):
        return "{reason}" in node
    if isinstance(node, list):
        return any(_has_reason(v) for v in node)
    if isinstance(node, dict):
        return any(_has_reason(v) for v in node.values())
    return False


def hook_of(name):
    """The hook protocol data of the local definition of a provider. HookError when there is none or it is not usable."""
    provider = _provider()
    try:
        d = provider.definition(name, "local")
    except provider.ProviderError as e:
        raise HookError(str(e))
    barrier = d.get("barrier") if isinstance(d.get("barrier"), dict) else {}
    if barrier.get("kind") != "hook":
        raise HookError("provider %s has no hook barrier (its barrier is %s), so there is no hook protocol to read"
                        % (name, repr(barrier["kind"]) if barrier.get("kind") else "not described"))
    why = hook_problem(barrier.get("hook"))
    if why:
        raise HookError("the hook protocol of provider %s cannot be used: %s" % (name, why))
    return barrier["hook"]


# --- the decisions

def judge(call):
    """The refusal (a sentence for the member, ending in what to do instead) a Call earns, or None. The neutral core."""
    why = blocked(call.command) if call.kind == "shell" else None
    if why:
        return "qargi guard: %s. Agents never push; return patches instead." % why
    why = skill_refusal(call)
    if isinstance(why, MarshalReason):
        return "qargi guard: %s." % why
    if why:
        return ("qargi guard: %s. Only a person, through qargi's own skills, changes a skill; propose the change as a "
                "patch or a plan in RUN_DIR." % why)
    why = review_refusal(call)
    if why:
        return "qargi guard: %s. A review reads the work and writes its report to RUN_DIR." % why
    return None


def decide(hook):
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return hook["allow"]["exit"]                      # not JSON: not a call to judge (as before)
    why = judge(parse_call(hook, data))
    return refuse(hook, why) if why else hook["allow"]["exit"]


def main():
    global CLASS
    hook = CLAUDE_HOOK
    name = read_provider(sys.argv[1:])
    if name is not None:                                  # the provider's protocol; one that cannot be read refuses (in the plain way: there is no other)
        try:
            if not name:
                raise HookError("--provider needs the name of a provider")
            hook = hook_of(name)
        except Exception as e:
            print("qargi guard: cannot use the hook protocol of provider %s (%s); refusing every call until the hook command or the definition is fixed." % (name or "?", e),
                  file=sys.stderr)
            return 2
    cls = read_class(sys.argv[1:])
    if cls not in CLASSES:
        return refuse(hook, "qargi guard: unknown class %r in the hook command; refusing every call until the member is refreshed." % cls)
    CLASS = cls
    try:
        return decide(hook)
    except Exception as e:                                # fail closed: a guard that cannot decide refuses
        return refuse(hook, "qargi guard: internal error (%s: %s); refusing the call because the guard could not check it."
                      % (type(e).__name__, e))


if __name__ == "__main__":
    sys.exit(main())
