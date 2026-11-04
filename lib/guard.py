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
that file and to the rest of the run's record (RUN_CONTROL), so a member cannot change the ability it is judged by. When the class says read-only, or
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
    ~/.qargi/config/packs), the credentials
    directory and install.json of the same configuration directories (not the rest of it: a member may run qargi verbs that
    change instances, agents or projects; the guard decides by the path a write construct names, never by the verb, and a
    read of a protected path stays allowed), the skills and agents directories the provider definitions name in their resources (user_dir, below
    the home: for Claude Code ~/.claude/skills and ~/.claude/agents; project_dir, found in any path outside the run's clone, a project's
    installed ones: .claude/skills and .claude/agents), ~/.claude/plugins, and the installed copy of the tool (the tool_root in install.json:
    the skills there are linked from ~/.claude/skills), and the render/ directory of the state (the renders a runtime loads
    its skills, tools and members from: what `packs apply --target RUNTIME` makes). Inside the clone, found from the nearest `qargi local
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
definitions (new, import, seal, remove, rename, enable, disable, attest, and any verb added later: only the ones in
PROVIDER_READ, list, show, effective, require-barrier, skills-dirs, of, layout, require-skills, launch, addenda, notes and model, stay allowed;
check records what it verified and may run a pack's code, and adapter-run runs the adapter, so both are refused with their own reasons).
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
cat $(echo ...), or by an echo piped to xargs).
Reading a Bash command (segments()): the plain, conservative split. The line is cut at every ; && || | & and newline whatever the quotes, a comment
or a heredoc body, so a refused verb is found wherever a command could start, and it is refused as text too: `git commit -m "Docs; qargi packs seed"` is
refused, and a member writes a message to a file with its file tool and commits with `git commit -F FILE`. A $( ), <( ), >( ) or backtick substitution, also
inside double quotes, is a command of its own (the line is cut at it, and the text inside it is cut again on its own, so `cat <<<"$(qargi upgrade) x"` is read);
a line continuation is read both ways; `>|` is a redirection and is not cut; the keywords and groupings that a command follows (if, then, do, !, {, (, case
patterns, function definitions) and redirections written before it are skipped; an unbalanced quote falls back on the words with the quotes taken off.
A string handed to a shell (sh -c STRING, eval STRING) is read again, with the segments that follow it. No file is guessed to be run later.
A NUL byte, a command over 262144 characters, checks that take over 8 seconds and a glob that needs more than GLOB_ENTRIES directory entries read are
refused, since a hook that times out does not block.
Write targets (write_targets()): a redirection (> >> >| <> &> >&FILE, N-prefixed, stuck to its word or not), tee, cp mv ln install rsync (every operand of mv:
the sources are removed; -t DIR), dd of=, sort -o|--output, uniq INPUT OUTPUT, sed|perl -i, git --output=FILE, format-patch -o, archive -o, bundle create, and the
git subcommands that change the tree or the repository. A target the shell would expand and the guard cannot read (a glob or a variable, a command
substitution) is refused when it could name a record file of the run (`> abilit?`, `> $F`, `cp x $D/ability`) or, for a command that makes or replaces
its file, whenever a variable or a substitution builds the name; a glob that can name a protected location is refused for a write. Under the read-only class the
variables a read-only tool takes its programs and options from (PATH, GIT_*, PAGER, BASH_ENV, RIPGREP_CONFIG_PATH, LD_* ...) are not set, and a write to
a git configuration or hook file in a command that also runs git is refused for every member.
The run: a directory is a run when it holds any file `qargi local prepare` makes there (RUN_MARKERS), or the clone and out directories beside any other file of
the record (RUN_CONTROL). RUN_CONTROL files are not written, moved, removed, copied or linked, and the run directory is not removed or moved; under
`--class read-only` the run is not asked whether the member is read-only: a run that cannot be found refuses every write (NO_RUN).
Not seen: a script built by code (python -c ...), a program or a verb held in a variable, what a pipe or a here-string hands a shell (`echo qargi upgrade | sh`,
`bash -c "$(echo qargi upgrade)"`), a wrapper's option that takes a value (sudo -u root qargi ...).

Failure: the guard fails closed. Any unexpected exception ends in exit 2 with the reason on stderr. Input that is not
JSON is still let through (exit 0), as before. Known limits outside this file, from the Claude Code hooks documentation
(https://code.claude.com/docs/en/hooks): a hook that cannot start, exits other than 0 or 2, times out or prints invalid
JSON is a non-blocking error ("The action goes ahead, except for hooks whose failure blocks the action, for example a
hook with `onFailure` set to \"block\""), so agents/member.md sets `onFailure: "block"` and a `timeout` (`onFailure`
"Requires Claude Code v2.1.295 or later"; an older version does not enforce it). Frontmatter hooks of a project-level
agent file run only after the workspace trust dialog is accepted (https://code.claude.com/docs/en/sub-agents): until
then the subagent runs without this guard."""
import collections, fnmatch, functools, json, os, re, shlex, sys, time

SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\||\n|(?<![<>&])&(?![>&]))\s*")      # the plain split on every separator (segments())
NOCLOBBER = re.compile(r"\s*(?:&&|\|\||;|(?<!>)\||\n|(?<![<>&])&(?![>&]))\s*")   # the same, with >| left whole: it is a redirection
SEPARATOR = re.compile(r"(\s*(?:&&|\|\||;|\||\n|(?<![<>&])&(?![>&]))\s*)")           # SEGMENT with the separators kept (re.split hands them back between the pieces)
NOCLOBBER_SEPARATOR = re.compile(r"(\s*(?:&&|\|\||;|(?<!>)\||\n|(?<![<>&])&(?![>&]))\s*)")
SUBST = re.compile(r"\$\(|`|[<>]\(")                       # command substitution and process substitution start a command of their own
HANDOFF_SUBST = re.compile(r"(?:marshal(?:\.sh)?[\"']*\s+[\"']*handoff|marshal_handoff\.py)[\"']*[^;&|\n]*(?:\$\(|`)")   # `marshal handoff ... $(...)`: the substitution may produce --write, and splitting it off hides that
PROJECT_SET_SUBST = re.compile(r"project(?:\.sh)?[\"']*\s+[\"']*set[\"']*\s[^;&|\n]*(?:\$\(|`)")   # `project set ... $(...)`: the substitution may produce a models path, and splitting it off hides that
AUDIT_SUBST = re.compile(r"packs_audit\.py[\"']*[^;&|\n]*(?:\$\(|`)")   # `packs_audit.py ... $(...)`: the substitution may produce `store`, and splitting it off hides that
UNREADABLE = "$`{}*?[]"                                     # in a word: a variable, a substitution, a brace or a glob builds it, so the guard cannot read what it is
PROJECT_VERBS = ("set", "init", "link", "unlink")           # the project verbs a member may not run (set: the models answers; init: the whole file; link, unlink: what a session loads)
WRAP = {"sudo", "env", "command", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice"}
WRITERS = {"rm", "rmdir", "touch", "mkdir", "chmod", "chown", "truncate", "tee", "patch", "unlink", "shred"}
COPIERS = {"cp", "mv", "ln", "install", "rsync", "ditto"}   # the last argument is the destination
TARS = {"tar", "gtar", "bsdtar"}
INPLACE = {"sed", "perl"}                                   # with -i
GIT_WRITES = {"add", "commit", "apply", "am", "checkout", "switch", "reset", "rm", "mv", "stash", "merge", "rebase",
              "cherry-pick", "revert", "restore", "clean", "tag", "branch", "pull", "fetch", "init", "clone", "worktree",
              "notes", "update-ref", "config", "submodule", "update-index", "gc", "prune", "repack", "pack-refs", "replace", "filter-branch", "commit-tree",
              "write-tree", "mktag", "mktree", "fast-import", "read-tree", "checkout-index", "sparse-checkout", "maintenance"}
REDIR = re.compile(r"^(?:\d*|&)(?:>>|>\||<>|>)(.*)$")           # > >> >| <> &> &>> and N> N>> N>| N<>, the target stuck to it or in the next word
GIT_OUTPUT_DIRS = {"format-patch", "archive"}                    # git subcommands whose -o names where they write

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
PROVIDER_READ = ("", "list", "show", "effective", "require-barrier", "skills-dirs", "of", "layout", "require-skills", "launch", "addenda", "notes", "model")   # the provider verbs that only read; the rest, and any verb added later, change the definitions or run code (check, adapter-run)
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
MAX_COMMAND = 262144                                         # a longer command cannot be checked in the time the hook has, so it is refused
MAX_NESTED = 40                                              # substitutions inside substitutions, at most; the texts of nested ones hold each other, so the cost grows with the square of the depth
GLOB_ENTRIES = 4000                                          # directory entries read, in all, to expand the globs of one word (the key checks); a pattern that needs more is refused
BUDGET = 8.0                                                 # seconds of checking before a call is refused: the hook is killed at its timeout, and a hook that times out does not block
_DEADLINE = [None]


class TooSlow(Exception):
    """The checks of one call took longer than BUDGET: the call is refused, as a hook that is killed would let it through."""


class TooNested(TooSlow):
    """Substitutions nested more than MAX_NESTED deep: the texts inside them, each holding the next, cost more than the time a hook has."""


class TooBroad(TooSlow):
    """A glob in a word would need more directory entries read than GLOB_ENTRIES to be expanded (`cat /*/*/*/*/*/*`): the call is refused, not expanded."""


def tick():
    if _DEADLINE[0] is not None and time.monotonic() > _DEADLINE[0]:
        raise TooSlow()


def blocked(command, depth=0):
    seen = set()
    for seg in segments(command):
        tick()
        if seg in seen:
            continue
        seen.add(seg)
        toks = cmd_tokens(seg)
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
        inner = shell_string(prog, rest) if depth < 3 else None
        why = blocked(inner, depth + 1) if inner is not None else None
        if why:
            return why
    return None


@functools.cache
def split_words(seg):
    """shlex.split of one segment, cut once per text (the checks of a call all ask); raises ValueError for an unbalanced quote."""
    return tuple(shlex.split(seg))


def tokens(seg):
    try:
        toks = list(split_words(seg))
    except ValueError:                                       # an unbalanced quote (a substitution cut out of a quoted string): the words with the quotes taken off
        toks = re.sub(r"[\\'\"]", "", seg).split()
    return toks


KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "(", "coproc"}   # a command follows them
LEADING_REDIR = re.compile(r"^(?:\d*|&)(?:<<<|<<-?|<>|>>|>\||>&?|<&?|&>>?)")
BARE_REDIR = re.compile(r"^(?:\d*|&)(?:<<<|<<-?|<>|>>|>\||>&?|<&?|&>>?)$")           # the operator alone: its target is the next word


def skip_wrappers(toks):
    """The index of the program: past assignments (VAR=x), wrappers (sudo, env, time ...), their options, the keywords a command can follow (then, do, !) and
    redirections written before the program (> f, 2>&1)."""
    i = 0
    while i < len(toks):
        t = toks[i]
        if "=" in t.split("/")[0] and not t.startswith("-") or os.path.basename(t) in WRAP or t.isdigit() or (t.startswith("-") and i) or t in KEYWORDS:
            i += 1
        elif LEADING_REDIR.match(t):
            i += 2 if BARE_REDIR.match(t) else 1
        else:
            break
    return i


def cmd_tokens(seg):
    """The words of a segment, without what the grammar puts around a command: the ( stuck to the first word, a case pattern (x)), and the ) that closes
    a group or a substitution stuck to the last. Cut once per text (a command is asked about by several checks); the list is the caller's."""
    return list(_cmd_tokens(seg))


@functools.cache
def _cmd_tokens(seg):
    toks = tokens(seg)
    if toks[:1] == ["function"]:                             # function NAME { ...
        toks = toks[2:]
    elif toks[:1] and toks[0].endswith("()"):                # NAME() { ...
        toks = toks[1:]
    if toks:
        toks[0] = toks[0].lstrip("({")
        if not toks[0]:
            toks.pop(0)
    if toks[:1] == ["case"]:                                 # case WORD in PATTERN) command
        k = next((k for k, t in enumerate(toks) if k > 1 and t.endswith(")") and "(" not in t), None)
        toks = toks[k + 1:] if k is not None else toks
    elif len(toks) > 1 and toks[0].endswith(")") and "(" not in toks[0]:
        toks.pop(0)
    if toks and toks[-1].endswith(")") and "(" not in toks[-1]:
        toks[-1] = toks[-1].rstrip(")")
        if not toks[-1]:
            toks.pop()
    return tuple(toks)


# --- reading a Bash command: the plain split (see segments)

def unescape_backticks(text):
    """The command a pair of backticks holds: the shell reads a backslash before a backtick, a backslash or a dollar sign in it as the plain character."""
    return re.sub(r"\\([`\\$])", r"\1", text)


def substitutions(text, depth=0):
    """The texts inside every $( ), <( ), >( ) and pair of backticks of a command line (nested ones too): each is a command of its own. Quotes are not
    read (a ) in a quoted string ends a text early, which only adds pieces), and a text that is never closed runs to the end. One pass: the parentheses
    are counted on a stack."""
    out, stack, backtick, i, n, opened = [], [], None, 0, len(text), 0
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "`":
            if backtick is None:
                backtick = i + 1
            else:
                out.append(unescape_backticks(text[backtick:i]))
                backtick = None
        elif backtick is None and c == "(":
            stack.append(i + 1 if text[i - 1:i] in ("$", "<", ">") else None)
            if stack[-1] is not None:
                opened += 1
                if opened > MAX_NESTED:
                    raise TooNested()
        elif backtick is None and c == ")" and stack:
            start = stack.pop()
            if start is not None:
                opened -= 1
                out.append(text[start:i])
        i += 1
    out += [text[start:] for start in stack if start is not None]
    if backtick is not None:
        out.append(unescape_backticks(text[backtick:]))
    if depth < 8:                                            # a pair of backticks inside a pair, written \`...\`, is found once it is unescaped
        out += [t for o in list(out) if "`" in o for t in substitutions(o, depth + 1)]
    return out


Piece = collections.namedtuple("Piece", "text top chained")   # top: a plain cd here, if it is one, changes the directory of what follows if the command before it in its && chain ran (see pieces()); chained: it follows an &&
SEQUENCE = ("", ";")                                         # separators after which a command runs whatever came before (a newline strips to "")
KEYWORDS_OPEN, KEYWORDS_CLOSE = ("if", "while", "until", "for", "select", "case"), ("fi", "done", "esac")


def subst_cut(text):
    """text with the start of every substitution replaced by `;` (the line cut at them), and where: the position in the new text of each replaced
    character, with 1 for the start of a command of its own and -1 for the backtick that closes a pair."""
    out, marks, last, length, in_backtick = [], [], 0, 0, False
    for m in SUBST.finditer(text):
        out.append(text[last:m.start()])
        length += len(out[-1])
        if m.group() == "`":
            in_backtick = not in_backtick
        marks.append((length, 1 if m.group() != "`" or in_backtick else -1))
        out.append(";")
        length += 1
        last = m.end()
    out.append(text[last:])
    return "".join(out), marks


def quote_after(text, quote):
    """The quote ('', "'" or '"') that is open at the end of text, given the one open at its start."""
    k = 0
    while k < len(text):
        c = text[k]
        if quote == "'":
            quote = "" if c == "'" else quote
        elif c == "\\":
            k += 1
        elif c == "'" and quote == "":
            quote = "'"
        elif c == '"':
            quote = "" if quote else '"'
        k += 1
    return quote


def pieces(text, whole=False, top=True):
    """The pieces of the line (the plain split on every separator, whatever the quotes), each with whether it is certainly run at the top level of the
    line, in order and unconditionally. The text of a piece is the cut that was always made: with the substitutions cut out (cut), or left whole
    (whole). top is False for a piece a cd in which may not change the directory of what follows: one that comes after || | or & (not after &&: see
    walk), or before a | or & (a pipeline and a background job run in a subshell), one inside ( ), a substitution, if/while/for/case, braces or a function, one after a quote that
    is still open, a here-document or a comment, or one cut off from the rest of its command by a substitution (`cd $(x)/y`)."""
    body, marks = (text, []) if whole else subst_cut(text)
    parts = (NOCLOBBER_SEPARATOR if ">|" in text else SEPARATOR).split(body)
    ends, pos = [], 0                                        # where each part ends, to find the separator a substitution's `;` is in
    for part in parts:
        pos += len(part)
        ends.append(pos)
    counted, j = {}, 1                                       # separator index -> [substitutions it starts, backticks it ends]
    for at, kind in marks:
        while ends[j] <= at:
            j += 2
        counted.setdefault(j, [0, 0])[0 if kind > 0 else 1] += 1
    out, depth, quote, heredoc, comment = [], 0, "", False, False
    for k in range(0, len(parts), 2):
        tick()
        piece = parts[k]
        before, after = (parts[k - 1] if k else ""), (parts[k + 1] if k + 1 < len(parts) else "")
        opens, closes = counted.get(k - 1, (0, 0))
        ahead = counted.get(k + 1, (0, 0))[0]                # a substitution starts behind this piece: its command goes on after it
        if "\n" in before:
            comment = False
        depth = max(0, depth + opens - closes)
        top_level = (top and depth == 0 and not quote and not heredoc and not comment and before.strip() in SEQUENCE + ("&&",) and after.strip() not in ("|", "&")
                     and not ahead and not opens and not closes)
        out.append(Piece(piece, top_level, before.strip() == "&&"))
        words = piece.split()
        first = words[0] if words else ""
        depth = max(0, depth + piece.count("(") - piece.count(")") + (first in KEYWORDS_OPEN) - (first in KEYWORDS_CLOSE) + words.count("{") - words.count("}"))
        comment = comment or (not quote and bool(re.search(r"(?:^|\s)#", piece)))
        heredoc = heredoc or bool(re.search(r"<<(?!<)", piece))
        quote = quote_after(piece, quote)
    return tuple(out)


@functools.lru_cache(maxsize=64)
def passes(command):
    """The cuts of a Bash command line, read once per command (the checks of one call all ask): [(kind, pieces)], kind "main" for a cut of the whole line
    (every one starts in the directory the call does) and "inner" for the text of a substitution cut on its own (it runs wherever the line was). The line
    is cut at every ; && || | & and newline whatever the quotes, a comment or a heredoc body; a $( ), <( ), >( ) or backtick substitution is cut off as a
    command of its own, and the text inside each is also cut on its own; the cut with the substitutions left whole is read too (`git $(true) push`); a line
    continuation is read both ways, joined (the shell joins the lines) and as the newline it is in a comment."""
    out = []
    for form in ((command.replace("\\\n", ""), command) if "\\\n" in command else (command,)):
        tick()
        out.append(("main", pieces(form)))
        if SUBST.search(form):                               # and the line cut with its substitutions whole: a word a substitution builds stays in the command it belongs to
            out.append(("main", pieces(form, whole=True)))
        for inner in substitutions(form):
            out.append(("inner", pieces(inner, top=False)))
    return tuple(out)


@functools.lru_cache(maxsize=64)
def segments(command):
    """The commands of a Bash command line as texts, in the order of passes() (the plain, conservative split: a verb in quoted text is found too). Read once per
    command (the checks of one call all ask)."""
    return tuple(p.text for _, ps in passes(command) for p in ps)


MAX_DIRS = 24                                                # directories the shell may be in at once, at most: a cd that may or may not happen doubles them
CD_FLAGS = ("-P", "-L", "-e", "-@", "--")
PLAIN_CD = re.compile(r"\s*(?:cd|pushd|popd)(?:\s|$)")


class TooManyDirs(TooSlow):
    """A command line that changes directory in more than MAX_DIRS ways that cannot be told apart (each cd that may not happen doubles the places the next
    command may run in): the call is refused, not judged from some of them."""


def moved(dirs, args, certain, visited):
    """The directories the shell may be in after `cd ARGS` from any of dirs. certain: the cd is a plain command of the top level, so it changes the
    directory when the directory is there (a directory that is not there yet may be made by a command before it: both are kept). Anything else keeps
    the directory it was in as well. `cd -` is any directory the line has been in."""
    ops = [t for t in args if t not in CD_FLAGS]
    if ops == ["-"]:
        return list(dict.fromkeys(dirs + visited))
    target = ops[0] if ops else "~"
    certain = certain and len(ops) <= 1 and not target.startswith("-") and not UNKNOWN.search(target)
    new = []
    for d in dirs:
        tick()
        r = resolve(d, target)
        new += [r] if certain and os.path.isdir(r) else [d, r]
    new = list(dict.fromkeys(new))
    if len(new) > MAX_DIRS:
        raise TooManyDirs()
    return new


def walk(command, here):
    """Every piece of every cut of the command, with the directories the shell may be in when it runs it: (n, texts, text, dirs). texts: the pieces of the
    cut and n the place of this one in it. here: the directory the call runs in (or a list of them). A plain `cd` at the top level of the line changes
    them for what follows (after an && only if the commands before it in the chain are plain cds too: `pushd d && popd && cmd`); a cd anywhere else (a
    subshell, a substitution, an if, after || or `cmd &&`, before a pipe, with an option or two directories ...)
    leaves the directory it was in among them, and every command is judged from each. pushd and popd are followed like cd. Each cut starts in the
    directory of the call, and a substitution's own text in any directory the line has been in, so a cd is never applied twice to one command."""
    start = list(dict.fromkeys([here] if isinstance(here, str) else here))
    visited = list(start)
    for kind, ps in passes(command):
        dirs = list(start) if kind == "main" else list(visited)
        if len(dirs) > MAX_DIRS:
            raise TooManyDirs()
        stack, ran = [], False                               # ran: the piece before was a cd that is certain
        texts = [p.text for p in ps]
        for n, piece in enumerate(ps):
            tick()
            yield n, texts, piece.text, dirs
            toks = cmd_tokens(piece.text)
            i = skip_wrappers(toks)
            prog = os.path.basename(toks[i]) if i < len(toks) else ""
            if prog not in ("cd", "pushd", "popd"):
                ran = False
                continue
            certain, rest = piece.top and bool(PLAIN_CD.match(piece.text)) and (ran or not piece.chained), toks[i + 1:]    # after &&, only when everything before it in the chain is such a cd
            ran = certain
            if prog == "cd":
                dirs = moved(dirs, rest, certain, visited)
            elif prog == "pushd":
                named = [t for t in rest if not t.startswith(("-", "+"))]
                if named and "-n" not in rest:
                    stack.append(dirs)
                    dirs = moved(dirs, named[:1], certain, visited)
                elif not named:
                    dirs = list(dict.fromkeys(dirs + visited))
            elif stack and "-n" not in rest:
                popped = stack.pop()
                dirs = popped if certain else list(dict.fromkeys(dirs + popped))
            visited += [d for d in dirs if d not in visited]


@functools.cache                                     # the files do not change while one command is judged
def run_like(p):
    """True when the directory p holds the record `qargi local prepare` makes: ability and refs.before, or the clone and out directories beside any
    other file of the record (so a run whose two files were moved away is still a run)."""
    if os.path.lexists(os.path.join(p, "ability")) and os.path.lexists(os.path.join(p, "refs.before")):
        return True
    return os.path.isdir(os.path.join(p, "clone")) and os.path.isdir(os.path.join(p, "out")) and any(os.path.lexists(os.path.join(p, m)) for m in RUN_CONTROL)


@functools.cache
def in_a_clone(p):
    """True when p lies below the clone directory of a directory that holds a run's record. A clone is the repository's content, and a repository may hold
    a docs/tmpdir or a whole docs/ability + docs/refs.before: they are not a run, and the member that edits them is not editing the record."""
    q = os.path.dirname(p)
    while q != os.path.dirname(q):
        if os.path.basename(q) == "clone" and run_like(os.path.dirname(q)):
            return True
        q = os.path.dirname(q)
    return False


def is_run(p):
    """True when the directory p is a run directory: it holds the record (run_like) and does not lie inside the clone of another run."""
    return run_like(p) and not in_a_clone(p)


@functools.cache                                     # the files do not change while one command is judged
def run_dir(path):
    """The nearest directory at or above path that `qargi local prepare` made (is_run)."""
    p = os.path.realpath(path) if path else ""
    while p and p != os.path.dirname(p):
        if is_run(p):
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
    """True when the member is read-only by class (its hook) or the run directory says so (its class file, or the review role). Under the class of the
    hook the run is not asked: a run whose files were moved away does not switch the class off (see review_refusal for what it holds the call to)."""
    return CLASS == "read-only" or bool(run) and (ability_of(run) == "review" or run_class(run) == "read-only")


NO_RUN = ("under the read-only class nothing is written or changed here: no run directory (the place of OUT and of the clone) is found from this directory, "
          "so no write can be shown to be the report; run from the clone")


RUN_CONTROL = ("ability", "class", "profile", "refs.before", "refs.after", "refs.diff", "verified", "started", "tmpdir", "applied", "repo.path", "repo.url", "cred.path", "git")


def control_refusal(full):
    """The reason a write to a run directory's own record is refused, or None. RUN_CONTROL is every file of the run directory that `qargi local` reads
    back and trusts: the ability and class the guard is held to, the refs the run is compared with, the directory `local clean` removes (tmpdir), the
    repository and the tip it asks whether the work is merged (repo.path, applied), the credential path, the git wrapper."""
    if os.path.basename(full) in RUN_CONTROL and run_dir(os.path.dirname(full)) == os.path.dirname(full):
        return "%s is the run's own record (the coordinator wrote it); a member does not change it" % full
    return None


def run_dir_refusal(full):
    """The reason a write to the real path full lands in the run directory itself, or None. The run directory holds the record the run is judged by, the
    contract and the git wrapper: a copy into it (`cp -r Y/. ..`), an extraction (`tar -C .. -xf`), a link, a move or a redirection is refused whatever
    way the path is written, for every member. OUT, the clone and TMP (RUN/tmp) are the member's."""
    run = run_dir(full if os.path.isdir(full) else os.path.dirname(full))
    if run and inside(full, run) and os.path.relpath(full, run).split(os.sep)[0] not in ("out", "clone", "tmp"):
        return "%s is in the run directory (%s), outside its OUT, its clone and its TMP: the record and the contract there are the coordinator's" % (full, run)
    return None


def run_refusal(full, here):
    """The reason a command that removes or moves the path full takes the run directory (or a directory above it) away, with the record in it, or None."""
    run = run_dir(here)
    if run and inside(run, full):
        return "%s is the run directory (or holds it): its record and its clone are not for a member to remove or move" % full
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
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


def expand_path(p):
    """p with ~ and the variables of the environment expanded, except PWD and OLDPWD (the shell sets those, the hook's own are another directory's) and
    the variables the environment lacks, which stay as written."""
    return re.sub(r"\$(?:\{(\w+)\}|(\w+))", lambda m: m.group(0) if (m.group(1) or m.group(2)) in ("PWD", "OLDPWD") else os.environ.get(m.group(1) or m.group(2), m.group(0)),
                  os.path.expanduser(p))


@functools.cache                                     # the files do not change while one command is judged
def resolve(here, p):
    """The real path of p (with ~ and environment variables expanded) as seen from the directory here."""
    return os.path.realpath(os.path.join(here, expand_path(p)))


def redirect_dest(toks, k):
    """The word the redirection at toks[k] writes to, None when toks[k] is no redirection that writes a file (a duplicated descriptor, 2>&1, is not). The
    empty string is a redirection with no target in this segment: a substitution or a separator cut it off."""
    m = REDIR.match(toks[k])
    if not m:
        return None
    dest = m.group(1)
    if dest.startswith("&"):                                  # >&2 and >&- duplicate or close a descriptor; >&FILE is &>FILE
        dest = dest[1:] or (toks[k + 1] if k + 1 < len(toks) else "")
        return None if re.fullmatch(r"\d+-?|-", dest) else dest
    return dest or (toks[k + 1] if k + 1 < len(toks) else "")


def attached_dest(t):
    """The target of a redirection written inside a word (echo x>file, cmd 2>>file, x>|file), else None."""
    if ">" not in t or REDIR.match(t):
        return None
    dest = t.rsplit(">", 1)[1].lstrip("|")
    return dest if dest and not dest.startswith("&") and not re.search(r"\s", dest) else None      # a word with blanks after the > is text (a -> b)


def option_value(rest, k, names):
    """The value of the option at rest[k] when it is one of names (a long option as --name=V or --name V, a short one as -oV or -o V), else None."""
    t = rest[k]
    for name in names:
        if name.startswith("--"):
            if t.startswith(name + "="):
                return t.split("=", 1)[1]
            if t == name and k + 1 < len(rest):
                return rest[k + 1]
        elif t == name and k + 1 < len(rest):
            return rest[k + 1]
        elif len(name) == 2 and t.startswith(name) and not t.startswith("--") and len(t) > 2:
            return t[2:]
    return None


def write_targets(toks, i):
    """(what, destination) of everything a segment writes, by its redirections and its program (git included). A destination of "" is a redirection with no
    target left in the segment. Sources that a command removes (mv, rm) are targets too."""
    targets, gitdir = [], None
    for k, t in enumerate(toks):                       # redirections anywhere in the segment
        dest = redirect_dest(toks, k)
        if dest is None:
            dest = attached_dest(t)
        if dest is not None and dest != "/dev/null":
            targets.append(("a redirection", dest))
    if i < len(toks):
        prog, rest = os.path.basename(toks[i]), toks[i + 1:]
        args = [t for t in rest if not t.startswith("-") and not REDIR.match(t)]
        if prog in WRITERS:
            targets += [(prog, a) for a in args]
        elif prog in COPIERS and args:
            targets.append((prog, args[-1]))
            if prog == "mv":
                targets += [(prog, a) for a in args[:-1]]                 # the sources are removed
            if prog == "rsync" and any(t.startswith("--remove-source") for t in rest):
                targets += [(prog, a) for a in args[:-1]]
            for k in range(len(rest)) if prog != "rsync" else ():         # -t DIR, --target-directory=DIR, -tDIR, -rt DIR, -Dt DIR (rsync -t keeps times)
                v = option_value(rest, k, ("--target-directory", "-t"))
                v = cluster_value(rest, k, "t") if v is None else v
                if v is not None:
                    targets.append((prog, v))
        elif prog in INPLACE and any(re.match(r"^-[A-Za-z]*i", t) or t == "--in-place" or t.startswith("--in-place=") for t in rest):   # -i, -i.bak, -pi, -ni
            scripted = any(t in ("-e", "-f", "--expression", "--file") or re.match(r"^-[A-Za-z]*[ef]$", t) for t in rest)
            targets += [(prog + " -i", a) for a in (args if scripted else args[1:])]
        elif prog in TARS and tar_extracts(rest):
            targets += [("tar", d) for d in tar_dirs(rest)] or [("tar", ".")]          # an archive is extracted below -C DIR, else below where the shell is
        elif prog == "unzip" and not set("".join(t[1:] for t in rest if re.fullmatch(r"-[A-Za-z]+", t))) & set("lptZvcz"):
            dirs = [v for v in (cluster_value(rest, k, "d") for k in range(len(rest))) if v is not None]
            targets += [("unzip", d) for d in dirs] or [("unzip", ".")]               # unzip -d DIR, else where the shell is (-l, -p, -t ... only look)
        elif prog in ("curl", "wget"):
            targets += download_targets(prog, rest)
        elif prog == "dd":
            targets += [(prog, t[3:]) for t in rest if t.startswith("of=")]
        elif prog == "sort":
            targets += [("sort -o", v) for v in (option_value(rest, k, ("--output", "-o")) for k in range(len(rest))) if v is not None]
        elif prog == "uniq" and len(args) > 1:
            targets.append((prog, args[1]))                               # uniq INPUT OUTPUT
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
            if sub in GIT_WRITES and not (sub == "tag" and lists_tags(rest[k + 1:])):
                targets.append(("git " + sub, gitdir or "."))
            places = [t for t in rest[k + 1:] if not t.startswith("-")]
            if sub == "clone" and len(places) > 1:                        # git clone URL DIR, git init DIR, git worktree add DIR
                targets.append(("git clone", places[-1]))
            elif sub in ("init", "worktree") and places[sub == "worktree":][:1]:
                targets.append(("git " + sub, places[sub == "worktree":][0]))
            for n in range(k + 1, len(rest)):                             # git log|diff|show --output=FILE, format-patch -o DIR, archive -o FILE, apply --directory=DIR
                v = option_value(rest, n, ("--output", "--output-directory") + (("-o",) if sub in GIT_OUTPUT_DIRS else ()) + (("--directory",) if sub == "apply" else ()))
                if v is not None:
                    targets.append(("git " + sub + " --output", v))
            if sub == "bundle" and rest[k + 1:k + 2] == ["create"] and len(rest) > k + 2:
                targets.append(("git bundle create", rest[k + 2]))
    return targets


def cluster_value(rest, k, letter):
    """The value of the short option LETTER when rest[k] is a cluster of short options that holds it (`-d DIR`, `-dDIR`, `-od DIR`, `-rt DIR`, `-tDIR`): the
    rest of the cluster after the letter, else the next word. None when rest[k] is no such cluster."""
    m = re.match(r"^-[A-Za-z0-9]*?" + re.escape(letter) + r"(.*)$", rest[k])
    if not m:
        return None
    return m.group(1) or (rest[k + 1] if k + 1 < len(rest) else None)


def tar_extracts(rest):
    """True when the tar command line extracts (x, --extract, --get)."""
    modes = [t.lstrip("-") for k, t in enumerate(rest) if re.match(r"^-?[A-Za-z]+$", t) and (k == 0 or t.startswith("-"))]
    return any("x" in m for m in modes) or any(t.split("=")[0] in ("--extract", "--get") for t in rest if t.startswith("--"))


def tar_dirs(rest):
    """The directories a tar command is told to extract into (-C DIR, -CDIR, --directory=DIR, --directory DIR). A cluster that holds C (`-xCf DIR x.tar`)
    leaves it open which word is the directory, so every word after it counts."""
    out = []
    for k, t in enumerate(rest):
        if t == "--directory" and k + 1 < len(rest):
            out.append(rest[k + 1])
        elif t.startswith("--directory="):
            out.append(t.split("=", 1)[1])
        elif re.fullmatch(r"-[A-Za-z]+", t) and "C" in t and t != "-C":
            out += [w for w in rest[k + 1:] if not w.startswith("-")]
        elif t == "-C" and k + 1 < len(rest):
            out.append(rest[k + 1])
        elif t.startswith("-C") and len(t) > 2 and not t.startswith("--"):
            out.append(t[2:])
    return out


def download_targets(prog, rest):
    """What curl and wget write: the file or the directory an option names, else a file in the directory the shell is in (curl -O, wget); curl with no
    output option and wget -O - write to the terminal."""
    out, names, stdout = [], False, False
    for k, t in enumerate(rest):
        if prog == "curl":
            v = option_value(rest, k, ("--output", "--output-dir", "-o")) or cluster_value(rest, k, "o")
            names = names or t in ("-O", "--remote-name", "--remote-name-all") or bool(re.fullmatch(r"-[A-Za-z]*O[A-Za-z]*", t))
        else:
            v = option_value(rest, k, ("--output-document", "--directory-prefix", "-O", "-P")) or cluster_value(rest, k, "O") or cluster_value(rest, k, "P")
            stdout = stdout or v == "-"
            names = True
        if v and v != "-":
            out.append((prog, v))
    return out if out or stdout and not names else [(prog, ".")] if names else out


TAG_FLAGS = {"list", "ignore-case", "omit-empty", "no-omit-empty", "color", "no-color", "column", "no-column", "no-sort", "no-format"}   # change nothing
TAG_FILTERS = {"sort", "format", "points-at", "contains", "no-contains", "merged", "no-merged"}       # list options that take a value (the next word)
TAG_CHANGES = {"annotate", "no-annotate", "sign", "no-sign", "local-user", "force", "no-force", "delete", "no-delete", "verify", "no-verify", "message", "file", "edit",
               "no-edit", "cleanup", "create-reflog", "no-create-reflog", "trailer", "no-trailer"}   # make, replace, delete or check a tag (or take a value for one)


def tag_option(name):
    """The long option of git tag that NAME (without the dashes) stands for, an exact name or a unique abbreviation among those git knows, or None."""
    known = TAG_FLAGS | TAG_FILTERS | TAG_CHANGES
    if name in known:
        return name
    found = [k for k in known if k.startswith(name)]
    return found[0] if len(found) == 1 and name else None


def lists_tags(args):
    """True when `git tag ARGS` only lists tags: -l/--list or no tag name, and no option that makes, replaces or deletes one. Read the way git reads its
    arguments: an option that takes a value (--format, --sort, --contains, --points-at, --merged ...) takes the next word, a long option may be abbreviated
    (--form, --del, --anno), words after -- are names, and an option this does not know is a change."""
    listing, names, k = False, 0, 0
    while k < len(args):
        a = args[k]
        if a == "--":
            names += len(args) - k - 1
            break
        if a.startswith("--"):
            name, eq, _ = a[2:].partition("=")
            opt = tag_option(name)
            if opt is None or opt in TAG_CHANGES or (eq and opt not in ("color", "column", "sort", "format", "points-at", "contains", "no-contains", "merged", "no-merged")):
                return False
            listing = listing or opt == "list"
            if opt in TAG_FILTERS and not eq:
                k += 1
        elif a.startswith("-") and a != "-":
            for n, ch in enumerate(a[1:]):
                if ch == "l":
                    listing = True
                elif ch == "i":
                    continue
                elif ch == "n":                              # -n[NUM]: the number is stuck to it
                    if not a[n + 2:].isdigit() and a[n + 2:]:
                        return False
                    break
                else:
                    return False
        else:
            names += 1
        k += 1
    return listing or names == 0


class MarshalReason(str):
    """A refusal about the marshal: decide() ends it with the marshal's advice instead of the skills'."""


class OwnReason(MarshalReason):
    """A refusal that carries its own advice: decide_call() prints it as it is."""


DEVICE = re.compile(r"^/dev/(?:null|zero|full|tty|stdin|stdout|stderr|fd/\d+)$")           # a device a redirection may name; /dev/shm and the rest are directories
UNKNOWN = re.compile(r"[$`*?\[]")                            # in a word: a variable, a substitution or a glob stands where the guard would read a name
OVERWRITES = {"a redirection", "tee", "cp", "install", "ln", "rsync", "dd", "sort -o", "uniq", "mv", "truncate", "sed -i", "perl -i", "git bundle create"}   # they make or replace the file they name
TOUCHERS = WRITERS | COPIERS | {"dd"}                          # the programs whose every operand is a file they change or take away (a source is moved or removed)
GIT_PLACE = re.compile(r"(?:^|/)(?:\.gitconfig|\.config/git(?:/.*)?|\.git/config|\.git/hooks(?:/.*)?|info/attributes)$")   # what git reads its configuration and its hooks from
RESTRICTED_ENV = {"PATH", "ENV", "BASH_ENV", "IFS", "HOME", "SHELL", "SHELLOPTS", "CDPATH", "GLOBIGNORE", "PAGER", "EDITOR", "VISUAL", "MANPAGER", "LESSOPEN", "TMPDIR",
                  "SSH_ASKPASS", "XDG_CONFIG_HOME", "PROMPT_COMMAND", "RIPGREP_CONFIG_PATH", "NODE_OPTIONS", "RUBYOPT", "PERL5OPT", "PYTHONSTARTUP", "PYTHONPATH",
                  "EXINIT", "VIMINIT", "GREP_OPTIONS", "BROWSER", "PERL5LIB", "RUBYLIB", "NODE_PATH"}
RESTRICTED_ENV_PREFIX = ("GIT_", "LD_", "BASH_", "RIPGREP_")   # what a read-only tool reads its programs and options from
ASSIGNMENT = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[[^=]*\])?\+?=")
NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def restricted_name(name):
    return name in RESTRICTED_ENV or name.startswith(RESTRICTED_ENV_PREFIX)


def env_names(toks, i):
    """The names of the variables a segment sets: VAR=x in front of the program, export|declare|typeset|readonly|local|env NAME=x, printf -v NAME, read NAME."""
    names = [m.group(1) for m in (ASSIGNMENT.match(t) for t in toks[:i + 1]) if m]
    if i < len(toks):
        prog, rest = os.path.basename(toks[i]), toks[i + 1:]
        if prog in ("export", "declare", "typeset", "readonly", "local", "env"):
            names += [m.group(1) for m in (ASSIGNMENT.match(t) for t in rest) if m]
            if prog != "env":
                names += [t for t in rest if NAME.fullmatch(t)]
        elif prog == "printf":
            names += [rest[k + 1] if t == "-v" and k + 1 < len(rest) else t[2:] for k, t in enumerate(rest) if t == "-v" or t.startswith("-v") and len(t) > 2]
        elif prog in ("read", "mapfile", "readarray", "getopts", "let"):
            names += [t for t in rest if NAME.fullmatch(t)]
    return [re.sub(r"\[.*", "", n) for n in names]


def glob_reaches(pattern, destructive):
    """The protected root a glob pattern (an absolute path with the symbolic links of its literal head followed) can name or take in, else None: component by
    component, a root's name is matched against the pattern's. A pattern that names a directory above a root counts for a command that removes or moves a
    directory whole (destructive)."""
    pp = [c for c in pattern.split("/") if c]
    for root in protected_roots():
        rp = [c for c in root.split("/") if c]
        n = min(len(pp), len(rp))
        if all(fnmatch.fnmatchcase(rp[k], pp[k]) for k in range(n)) and (len(pp) >= len(rp) or destructive):
            return root
    return None


def glob_pattern(word, here):
    """The absolute pattern of a word that has a glob: the symbolic links of its literal head followed, the rest as written."""
    first = UNKNOWN.search(word).start()
    lit = word[:first].rpartition("/")[0]
    real = os.path.realpath(os.path.join(here, lit) if lit else here) if not lit.startswith("/") else os.path.realpath(lit or "/")
    return os.path.join(real, word[len(lit):].lstrip("/"))


def unreadable_target(what, dest, here):
    """The reason a file that a command writes or takes away cannot be read from its name, or None. The shell expands a variable, a substitution, a
    brace and a glob, and the guard does not, so a name that holds one is judged by what it could be (a variable the environment has is expanded first):
    a command that makes or replaces its file (OVERWRITES) is refused when a variable or a substitution builds the file name; any command is refused when the
    name is a record file of the run (RUN_CONTROL) in a directory the guard cannot read, or a glob that matches one (`> abilit?`)."""
    if DEVICE.match(dest):
        return None
    for cand in brace_expand(dest):
        c = expand_path(cand)
        if not UNKNOWN.search(c):
            continue
        head, _, base = c.rpartition("/")
        if ("$" in base or "`" in base) and what in OVERWRITES:
            return OwnReason("%s writes to a file whose name a variable or a substitution builds (%s), which the guard cannot read; write the path out" % (what, dest))
        if UNKNOWN.search(head):
            wild = not re.sub(r"[*?\[\]]", "", base)
            hit = [] if wild or "$" in base or "`" in base else [n for n in RUN_CONTROL if fnmatch.fnmatchcase(n, base)]
        elif UNKNOWN.search(base):
            hit = [n for n in RUN_CONTROL if fnmatch.fnmatchcase(n, base) and os.path.lexists(os.path.join(here, head or ".", n))]
        else:
            hit = []
        if hit:
            return OwnReason("%s on %s could name %s, a record of the run (the coordinator wrote it), through a glob, a variable or a substitution the guard cannot read; "
                             "write the path out" % (what, dest, hit[0]))
    return None


def glob_root(what, dest, here):
    """The reason a glob in the file a command writes or takes away can name a protected location (skills, the pack library, credentials ...), or None."""
    if DEVICE.match(dest):
        return None
    for cand in brace_expand(dest):
        c = expand_path(cand)
        if UNKNOWN.search(c) and "$" not in c and "`" not in c:
            root = glob_reaches(glob_pattern(c, here), what in DESTRUCTIVE)
            if root:
                return OwnReason("%s on %s could take in %s, a protected location (skills, the pack library, credentials), through a glob; write the path out" % (what, dest, root))
    return None


def review_refusal(call):
    """The reason a call is refused by what the run and the class hold a member to, or None: the record of the run is the coordinator's; under the read-only
    class (the hook's class, or the run's ability or class file) only the report and the manifest in OUT are written and the clone is not changed."""
    cwd = call.cwd
    if call.kind == "write":
        fp = call.path
        if not fp:
            return None
        full = os.path.realpath(os.path.join(cwd, fp))
        why = control_refusal(full) or run_dir_refusal(full)
        if why:
            return why
        run = run_dir(os.path.dirname(full)) or run_dir(cwd)
        if CLASS == "read-only" and not run:
            return OwnReason(NO_RUN)
        if run and is_review(run) and not inside(full, os.path.join(run, "out")):
            return "under the read-only class only the report and the manifest in OUT may be written (%s is not)" % fp
        return None
    if call.kind != "shell":
        return None
    seen, places, runs_git = set(), [], False
    for n, texts, seg, dirs in walk(call.command, cwd):
        toks = cmd_tokens(seg)
        i = skip_wrappers(toks)
        prog = os.path.basename(toks[i]) if i < len(toks) else ""
        for here in dirs:                                    # a cd that may not happen leaves several: each is judged
            if (seg, here) in seen:                          # the same text from the same directory has been judged
                continue
            seen.add((seg, here))
            why = review_segment(toks, i, here, seg)
            if why:
                return why
            runs_git = runs_git or prog == "git" or (prog in SHELLS or prog in ("eval", "xargs", "find", "make")) and bool(re.search(r"\bgit\b", seg))
            places += [dest for what, dest in write_targets(toks, i) if dest and GIT_PLACE.search(resolve(here, dest))]
    if places and runs_git:
        return OwnReason("%s is where git reads its configuration or its hooks from, and this command also runs git: what it holds, git would run; write it in a command of its own "
                         "or not at all" % places[0])
    return None


def review_segment(toks, i, here, text=""):
    def reading(run):
        return CLASS == "read-only" or bool(run) and is_review(run)
    prog = os.path.basename(toks[i]) if i < len(toks) else ""
    if toks and text.rstrip()[-1:] in ("<", ">", "|", "&") and redirect_dest(toks, len(toks) - 1) == "":
        return OwnReason("a redirection with no file name left in its command (a substitution or a separator stands where it should be) writes where the guard cannot read; "
                         "write the path out")
    if reading(run_dir(here)):                               # what a read-only tool runs or reads its options from is not set by a member
        bad = next((n for n in env_names(toks, i) if restricted_name(n)), None)
        if bad:
            return OwnReason("under the read-only class %s is not set: the tools it runs read their programs and options from it" % bad)
    ro = reading(run_dir(here))
    for what, dest in write_targets(toks, i):
        why = unreadable_target(what, dest, here)
        if why:
            return why
        if ro and UNKNOWN.search(expand_path(dest).rpartition("/")[0]) and not DEVICE.match(dest):
            return OwnReason("under the read-only class %s writes through a directory name that a variable, a substitution or a glob builds (%s), which the guard cannot read "
                             "to tell the clone from OUT; write the path out" % (what, dest))
        full = resolve(here, dest)
        why = control_refusal(full) or run_dir_refusal(full)
        if why:
            return why
        run = run_dir(full if os.path.isdir(full) else os.path.dirname(full)) or run_dir(here)
        if CLASS == "read-only" and not run:
            return OwnReason(NO_RUN)
        if what.split()[0] in DESTRUCTIVE:
            why = run_refusal(full, here)
            if why:
                return why
        if run and reading(run) and inside(full, os.path.join(run, "clone")):
            return "under the read-only class nothing in the clone may be changed (%s into %s)" % (what, dest)
    if prog in TOUCHERS or prog == "find":                    # the sources of cp, mv and ln, and every file a command takes away, are the run's record too
        rest = toks[i + 1:]
        operands = [t for t in rest if not t.startswith("-") and not REDIR.match(t)] + [t[3:] for t in rest if t.startswith(("if=", "of="))]
        if prog == "find" and not any(t in FIND_ACTIONS for t in rest):
            operands = []
        for a in operands[:200]:
            why = unreadable_target(prog + " (operand)", a, here) or control_refusal(resolve(here, a))
            if why:
                return why
            if prog in DESTRUCTIVE | {"find"}:
                why = run_refusal(resolve(here, a), here)
                if why:
                    return why
    return None


# --- skills: who may change one, and where they live

class MemoryReason(MarshalReason):
    """A refusal about a memory tier: decide() prints it as it is (it carries its own advice)."""


def conf_dirs(P, home):
    """The configuration directories a qargi installation may keep its packs, credentials and install record in."""
    return (P.conf(), os.path.join(P.root(), "config"), os.path.join(home, ".qargi", "config"))


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


_ROOTS = {}


def protected_roots():
    """The locations whose content is a skill, the library of them, a credential or the install record (real paths). Worked out once per
    environment (a command of thousands of segments asks for every one)."""
    key = tuple(os.environ.get(k) for k in ("HOME", "QARGI_CONF", "QARGI_HOME", "QARGI_STATE", "XDG_CONFIG_HOME"))
    if key not in _ROOTS:
        _ROOTS[key] = _protected_roots()
    return _ROOTS[key]


def _protected_roots():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import paths as P                                     # here, not at the top: an import failure is then a refusal (see main)
    home = os.path.expanduser("~")
    # the library where the data lives, the default and the QARGI_HOME one beside an override
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
    roots.update(render_roots(P, home))
    roots.update(providers_state_roots(P, home))
    roots.update(feature_roots(P, home))
    roots.update(switch_roots(P, home))
    roots.update(journal_roots(P, home))
    roots.update(memory_roots(P, home))
    return sorted(os.path.realpath(r) for r in roots)


def render_roots(P=None, home=None):
    """The render/ directory of the state: where the renders of every runtime go (state/render/<project>/<runtime>: skills, tools and
    members as a runtime loads them). Found like the other qargi paths: QARGI_STATE, else <root>/state, and the default
    ~/.qargi/state beside an override (real paths, so a link into it is followed)."""
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
    """The features/ directory of the state: the marshal's record of each open feature. Found as render_roots does."""
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


_STATE = {}


def state_dirs(P=None, home=None):
    key = tuple(os.environ.get(k) for k in ("HOME", "QARGI_CONF", "QARGI_HOME", "QARGI_STATE")) if P is None and home is None else None
    if key is not None and key in _STATE:
        return _STATE[key]
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    got = {os.path.realpath(st) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}
    if key is not None:
        _STATE[key] = got
    return got


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
    """The sentence for a refused write: the generic one, or for the render and the marshal's records the reason."""
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
    return any(inside(d, full) and has_key_file(d) for d in key_dirs())


def has_key_file(d):
    try:
        return any(n.startswith(KEY_PREFIX) for n in os.listdir(d))
    except OSError:
        return False


def glob_paths(pattern, limit=200):
    """The paths an absolute glob pattern names (at most limit), found by reading directories component by component: at most GLOB_ENTRIES entries in all
    (TooBroad when the pattern needs more, so `/*/*/*/*/*/*` costs a refusal and not minutes), the time budget watched on the way. Names that start with a
    dot are matched too, which is more than the shell does by default."""
    left, found = [GLOB_ENTRIES], []

    def walk(base, parts):
        if len(found) >= limit:
            return
        tick()
        if not parts:
            if os.path.lexists(base):
                found.append(base)
            return
        head, rest = parts[0], parts[1:]
        if not re.search(r"[*?\[]", head):
            nxt = os.path.join(base, head)
            if not rest or os.path.isdir(nxt):
                walk(nxt, rest)
            return
        try:
            names = sorted(os.listdir(base))
        except OSError:
            return
        left[0] -= len(names)
        if left[0] < 0:
            raise TooBroad()
        for n in names:
            if fnmatch.fnmatchcase(n, head):
                walk(os.path.join(base, n), rest)
    walk("/", [c for c in pattern.split("/") if c])
    return found


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


@functools.cache                                     # the files do not change while one command is judged
def key_named(word, here, recursive):
    """The signing key (or, for a recursive reader, a directory holding it) that one shell word stands for, else None. The word
    is read with ~ and variables expanded, braces and globs expanded, symbolic links followed; `--opt=path`, `-Opath` and a
    `<path` redirection are read as their path too."""
    cands = {word, word.lstrip("<"), re.sub(r"^(?:\d+|&)?[<>]+[&|]?", "", word), word.split("=", 1)[-1]}     # 3<key, <key, <>key, <&key
    if word.startswith("-") and not word.startswith("--"):
        cands.add(word[2:])
    for c in cands:
        if not c or c.startswith("-"):
            continue
        for b in brace_expand(expand_path(c)):
            plain = re.sub(r"/(?:\./)+", "/", re.sub(r"/{2,}", "/", b))        # dir//key and dir/./key are the path dir/key
            if any(d + os.sep + KEY_PREFIX in plain for d in key_dirs()):     # a path inside text, e.g. python -c "open('...')"
                return b
            paths = glob_paths(os.path.join(here, b)) if re.search(r"[*?\[]", b) else []
            for full in [os.path.realpath(os.path.join(here, b))] + [os.path.realpath(x) for x in paths]:
                if is_key(full) or (recursive and holds_key(full)):
                    return b
    return None


def key_refusal_text(prog, word, tool=None):
    return MarshalReason("%s on %s would read the marshal's signing key (credentials/%s*); %s" % (tool or prog, word, KEY_PREFIX, KEY_NOTE))


def key_read(toks, i, here):
    """The reason a Bash segment reads the lead's signing key, or None: any word of it that names the key, whatever the program, the words before the program
    (`<key cat`, `exec 3<key`) and a segment with no program at all. ls, stat and test only look at a file: their own operands are not read, a redirection
    in front of them is."""
    prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
    recursive = prog in KEY_RECURSIVE and (prog != "find" or any(t in FIND_ACTIONS for t in rest))
    recursive = recursive or prog in KEY_LINKERS or (prog == "cp" and any(LINK_FLAGS.match(t) or t in ("--symbolic-link", "--link") for t in rest))
    for t in toks[:i] if prog in KEY_METADATA else toks:
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


@functools.cache                                     # the files do not change while one command is judged
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
    joined = command.replace("\\\n", "")                 # a line continuation joins the lines (segments() does the same, and reads an escaped backslash right)
    if HANDOFF_SUBST.search(joined):
        return MarshalReason("qargi marshal handoff with a command substitution in its arguments could be given --write, which writes a file and is not available to an agent; %s"
                             % MARSHAL_NOTE)
    if PROJECT_SET_SUBST.search(joined):
        return "qargi project set with a command substitution in its arguments takes a path the guard cannot read, which could be a models answer, and is not available to an agent"
    if AUDIT_SUBST.search(joined):
        return "qargi skill accept (packs_audit.py with a command substitution in its arguments could be `store`) changes a skill and is not available to an agent"
    seen = set()                                         # the (text, directory) pairs judged
    for n, texts, seg, dirs in walk(command, here):
        toks = cmd_tokens(seg)
        i = skip_wrappers(toks)
        if any(t.startswith("QARGI_NESTED=") for t in toks[:i]):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
        why = lead_refusal(prog, rest, toks[:i + 1])
        if why:
            return why
        if prog in ("export", "declare", "typeset", "readonly") and any(t.split("=")[0] == "QARGI_NESTED" for t in rest):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        for at in dirs:                                      # a cd that may not happen leaves several directories: each is judged
            if (seg, at) in seen:                            # judged already
                continue
            seen.add((seg, at))
            if i < len(toks) and prog not in ("cd", "pushd", "popd"):
                why = skill_verb(prog, rest, via_xargs=any(os.path.basename(t) == "xargs" for t in toks[:i]), here=at, exe=toks[i])
                if why:
                    return why
                inner = shell_string(prog, rest) if depth < 3 else None
                if inner is not None:
                    inner += " ; " + " ; ".join(texts[n + 1:n + 201]).replace('"', " ").replace("'", " ")      # a `;` inside the quoted string split it: read the pieces that follow as part of it
                    why = bash_skill_refusal(inner, [at], depth + 1)
                    if why:
                        return why
            why = protected_write(toks, i, at) or key_read(toks, i, at)       # redirections alone, or in front of a program, write and read too
            if why:
                return why
    return unreadable_project_verb(command)


@functools.cache
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
    return tuple(out)


def unreadable_project_verb(command):
    """The reason a command runs a `project` verb the guard could not read, or None. The verbs are read from the words of each segment; a quote, a
    substitution, xargs, a brace or a glob can hide which one it is or what it is given. A segment with the word project, one of PROJECT_VERBS after
    it (or a word in the place of the verb that the shell expands), and any expansion in the segment, or xargs in front, is refused whatever it would
    turn out to say. A segment that hands a string to a shell (sh -c, eval) is read again with every quote and backslash taken off, since the string
    is cut into words once more there. This runs after the readable forms were judged (their reasons are the better ones), and does not look at a
    program held in a variable (the limit of the whole guard)."""
    seen = set()
    for seg in segments(command):
        tick()
        if seg in seen:
            continue
        seen.add(seg)
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
    if area == "provider" and verb == "check":
        return "qargi provider check records what it verified of a library pack (and may run the pack's code) and is not available to an agent"
    if area == "provider" and verb == "adapter-run":
        return "qargi provider adapter-run runs the adapter of a runtime, and with --check makes a private copy of a library adapter, and is not available to an agent"
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
    if (area in ("skill", "tool") and verb in SKILL_VERBS) or (area, verb) in (("discover", "install"), ("packs", "apply"), ("packs", "seed"), ("packs", "link"), ("packs", "unlink"), ("local", "run")) \
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
    """The reason a segment writes under a protected location, or None (the heuristic the docstring describes). i is past the last word when the segment
    is redirections alone."""
    prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
    args = [t for t in rest if not t.startswith("-") and not REDIR.match(t)]
    cands = list(write_targets(toks, i))
    if prog in SCRIPTS or (prog in SHELLS or re.match(r"^python[0-9.]*$", prog)) and args and os.path.basename(args[0]) in SCRIPTS:
        words = args if prog in SCRIPTS else args[1:]
        if words[:2] == ["packs", "render"]:                 # render writes its output directory: judge every operand
            cands += [("qargi packs render", c) for t in words[2:] for c in {t, t.split("=", 1)[-1]}]
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
        why = glob_root(what, dest, here)
        if why:
            return why
        root = protected(resolve(here, dest), what.split()[0] in DESTRUCTIVE)
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
    if call.kind == "shell" and "\0" in (call.command or ""):
        return "qargi guard: a NUL byte in a command cuts it short for the shell and hides the rest from this check, so it is not available to an agent. Write the text without it."
    if call.kind == "shell" and len(call.command or "") > MAX_COMMAND:
        return ("qargi guard: a command of more than %d characters cannot be checked in the time the hook has, so it is not available to an agent. "
                "Write the text to a file with the Write tool, or run it in parts." % MAX_COMMAND)
    _DEADLINE[0] = time.monotonic() + BUDGET
    try:
        return decide_call(call)
    except TooNested:
        return ("qargi guard: substitutions nested more than %d deep cannot be checked in the time the hook has, so the command is not available to an agent. "
                "Write it in parts." % MAX_NESTED)
    except TooBroad:
        return ("qargi guard: a glob in this command names too many directories to check (more than %d entries to read), so it is not available to an agent. "
                "Write a narrower path." % GLOB_ENTRIES)
    except TooManyDirs:
        return ("qargi guard: this command changes directory in more than %d ways the guard cannot tell apart (a cd inside ( ), a substitution, a condition or a pipe may "
                "or may not change where the next command runs), so it is not available to an agent. Write it in parts." % MAX_DIRS)
    except TooSlow:
        return ("qargi guard: checking this command took longer than %d seconds, so it is not available to an agent. "
                "Run it in smaller parts." % BUDGET)
    finally:
        _DEADLINE[0] = None


QUOTED = re.compile(r"[\"']|<<")
TEXT_HINT = (" The guard cuts a command at every ; && || | and newline, inside quotes and heredocs too: if the verb is only text (a commit message, a note), "
             "write the text to a file with your file tool and commit with git commit -F FILE.")


def decide_call(call):
    hint = TEXT_HINT if call.kind == "shell" and QUOTED.search(call.command or "") else ""
    why = blocked(call.command) if call.kind == "shell" else None
    if why:
        return "qargi guard: %s. Agents never push; return patches instead.%s" % (why, hint)
    why = skill_refusal(call)
    if isinstance(why, MarshalReason):
        return "qargi guard: %s.%s" % (why, hint if type(why) is MarshalReason else "")
    if why:
        return ("qargi guard: %s. Only a person, through qargi's own skills, changes a skill; propose the change in your report.%s" % (why, hint))
    why = review_refusal(call)
    if isinstance(why, MarshalReason):
        return "qargi guard: %s." % why
    if why:
        return "qargi guard: %s. A review reads the work and writes its report to OUT." % why
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
