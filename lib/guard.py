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

Publishing: git push, send-pack, http-push and svn dcommit (only the subcommand, the first word after git's global options, counts: `git commit -m push` is no
push), the programs git-push, git-send-pack, git-http-push and git-receive-pack, gh, ssh, scp, sftp, an rsync operand of the form host:path or rsync://, and
changing a remote. Git is also refused every way to run another command under a name the guard does not know: `-c` and `--config-env` with a key that defines an alias,
runs a program or reads another configuration file (GIT_RUNS_CODE: alias.*, core.pager|editor|fsmonitor|hooksPath|sshCommand|askPass|gitProxy, include.path, includeIf.*.path,
diff.external, credential.*, filter.*, gpg.*, url.*.insteadOf, remote.*.url|uploadpack ...), and `git config` that writes such a key for later (set, --add, --replace-all or
KEY VALUE, in any scope or --file, after -C, the key read in any case), or that can write any key (--edit, a section renamed), or whose key a variable or xargs brings
(config_refusal); `--exec-path=DIR`, and the variables GIT_CONFIG_*, GIT_EXEC_PATH, GIT_SSH* in front of it. A git subcommand, or a qargi area or a verb of a gated area, that a variable or a substitution builds is refused.

Review is read-only as a rule. A member whose definition passes `--class read-only` (the hook command in its frontmatter,
under the protected ~/.claude/agents) is held to it on every task. A member that serves several abilities passes no class
and falls back on `qargi local prepare`, which writes the task's ability to RUN/ability; the guard refuses any write to
that file and to the rest of the run's record (RUN_CONTROL), so a member cannot change the ability it is judged by. When the class says read-only, or
the nearest run directory above the call's cwd or file path says review, the guard also refuses an edit outside OUT (RUN/out: the report
and the manifest) and TMP (the temporary directory the lead's registry names for the run, and RUN/tmp), and a Bash command that writes anywhere else: a
redirection, a command that creates, changes or removes files, or a git command that changes the work tree or the history (bisect, symbolic-ref with a value,
reflog expire and delete, hash-object -w, unpack-objects and git lfs included).

Skills: only a person, through qargi's own skills, changes a skill, so the guard refuses a member
  - the lead's runs and agents: qargi local run|prepare|verify|close|clean (`local clean --discard` removes another run with no token), agent remove, project new,
    team run and task;
  - the verbs that change one: qargi skill|tool new|import|seal|remove|unlink|link|enable|disable, qargi skill accept|unaccept
    (they record which skills the owner accepts, in <packs>/accepted.json), qargi discover
    install, qargi packs apply|seed|link|unlink, qargi project link|unlink (they link the project's skills, agents and memory into the
    checkout and the runtime's memory directory, which changes what a session loads) and qargi import (it restores the pack library).
    Read-only verbs (list, show, check, effective, search, render, export) stay allowed. The verb is found after wrappers, inside `sh|bash -c STRING` and
    `eval STRING`, in the program a shell reads on its standard input (below), inside $(...) and backticks, and when the script is named directly (packs.sh, discover.py, and the scripts the shell
    verbs call: env_apply.py is env apply in any use (qargi env plan and apply run the project's dry-run and bootstrap commands: project code; env.py is env,
    found like linker.py, so env show stays open), packs_link.py is packs link|unlink and project_link.py is project link|unlink in any use, packs_audit.py store is skill accept|unaccept, marshal_handoff.py is marshal handoff,
    linker.py (the link engine) is packs link in any use, and render.py (it can run the command a definition names) is refused in any use;
    the last two have names a project may use for its own scripts, so only the files in the lib directory of the tool or of the installed
    copy count, found from the directory the command runs in);
  - qargi project init (it stores a whole answers file, so it is a way to models.extensions and models.accept_no_barrier, which have gated verbs;
    found like the skill verbs), and qargi project set of any models answer, of release.*, of test_command, of env.*, of site.* (the commands, environment and site the lead later runs or builds), of packs.* (the opt-out of the render check) and of
    roles.<role>.tools, a whole role or roles (the tools env apply installs and local prepare checks out; the other answers stay open). A project verb the guard cannot read is
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
    its skills, tools and members from: what `packs apply --target RUNTIME` makes), the providers/ directory of the state, the memory tiers (<root>/memory and
    ~/.qargi/memory), ~/.config/anthropic, the lead's own git configuration (~/.gitconfig, ~/.config/git, ~/.git: `git config --global|--system`, `--file` outside
    the clone and `git init` of the home directory included) and the lead's session files (lead_files: ~/.claude/settings.json, settings.local.json, CLAUDE.md,
    commands/, hooks/, ~/.claude.json, the shell startup files such as ~/.bashrc, ~/.ssh/config and authorized_keys), for every member whatever its class. Inside the clone, found from the nearest `qargi local
    prepare` run directory, a project directory such as .claude/skills is the work product and stays writable; the path is resolved first, so a
    symbolic link in the clone that leads to a protected root is still denied. Edit, Write and
    NotebookEdit are decided by the resolved path (symbolic links followed). A Bash command is decided by a heuristic:
    a command that names a protected path as the destination of a write construct: a redirection (also `>file`
    without a space), tee, cp, mv, rm, ln, install, rsync, touch, mkdir, chmod, chown, truncate, shred, patch,
    `sed|perl -i`, `awk -i inplace`, ex, vi, vim, ed, rename, sqlite3, setfacl, mkfifo, `dd of=`, a git command that changes the tree (`--work-tree` and GIT_WORK_TREE
    name the place as -C does), find with -delete or -exec (rooted above a protected directory too when it removes), the command after find -exec|-execdir|-ok|-okdir
    and parallel (a command of its own), ln of a protected location or a directory above one, and any argument of
    tar, unzip, curl or wget. `~`, $HOME, $QARGI_CONF, ${NAME:-x} and ${NAME%/} (by the value of NAME when the environment has it, else a write through it is
    refused) and cd are followed (a brace word is judged as the words it stands for; $OUT is the run's out
    directory when nothing in the command could set it; a cd only as the next paragraph says). What an agent edits in its own clone, the
    repository's `skills/` directory included, and in its run directories stays allowed: protection is by the
    resolved path relative to the roots above, never by the word `skills`.
Provider: `qargi provider accept` (it records that the owner accepts a provider surface with no read-only barrier, which lets a
read-only role run there) is refused to a member, found like the skill verbs, and so is every other provider verb that changes the
definitions (new, import, seal, remove, rename, enable, disable, attest, and any verb added later: only the ones in
PROVIDER_READ, list, show, effective, require-barrier, skills-dirs, of, layout, require-skills, launch, addenda, notes and model, stay allowed;
check records what it verified and may run a pack's code, and adapter-run runs the adapter, so both are refused with their own reasons).
Release: `qargi release publish` (it creates the GitHub release of a tag), `qargi release sign` (it signs the release files with the
lead's key), `qargi release site` (it commits the built documentation site on the lead's site branch), `qargi release assets` (it runs the
project's release.assets_command, project code, in a worktree of the tag) and `qargi release fix` (it makes a worktree on the release branch
and, with --push, pushes it) are refused to a member, found like the skill verbs, also as a verb held in a variable and through
lib/release.sh and lib/release_sign.py; the other release verbs stay allowed (they need a plan token and approval of their own).
Changelog: `qargi changelog renumber` without --check (it rewrites the changelog of a work tree) is the lead's, found like the skill verbs, also through
lib/changelog.sh and lib/changelog_numbers.py and when a word is held in a variable; `renumber --check` only reads and stays allowed.
Marshal: the feature marshal (`qargi marshal`) is changed only by the lead. The guard refuses a member
  - the verbs that change it: qargi marshal claim|set|renew|release|take|takeover|finish|enable|disable, found like the skill verbs
    (after wrappers, in `sh -c`, `eval`, $(...), through a path to bin/qargi or marshal.sh). status and check stay allowed, and so
    does handoff, which only reads, unless it is given --write (that makes a file, as only the lead's session may) or an argument
    held in a variable (it could be --write); any other verb,
    none, or one held in a variable is refused (fail closed);
  - the feature verbs that write the marshal: qargi feature start|finish|verify (start and finish create and finish the lead's record
    and push it with the lead's credentials, verify keeps the lease renewed), found the same way. list, status, merge and sync stay
    allowed (merge and sync ask the marshal, and status, merge and sync renew the lease of a feature this identity leads); any other verb or one held in
    a variable is refused. The marshal tells a member run by the working directory (below a run directory) and by the variable QARGI_MEMBER_RUN
    that `qargi local run` puts in the member's environment (a member that changes directory still renews nothing); the guard refuses a command that sets or
    unsets that variable, as it does QARGI_LEAD. A member started some other way carries no variable and is told by its directory alone;
    `qargi feature park` (it resets the parking branch to develop in the main checkout) and `qargi branch prune` (it deletes merged branches
    and the worktrees qargi made, and with --remote branches on origin; also through lib/branch.sh, and a verb held in a variable) are the
    lead's too, and are refused with wording of their own; so are `qargi upstream status` (it fetches into the lead's repository, which changes
    the remote-tracking refs that `qargi local verify` compares against a run's snapshot) and `qargi upstream sync` (it fast-forwards the branch
    that carries the upstream line and journals the move, from a plan and a token), also through lib/upstream.sh and as a verb held in a
    variable; `qargi upstream review` only reads the last fetch and stays allowed, and so is `qargi ref` (record --rewrite moves an agent branch and journals it, note journals a branch the lead made; any verb, also through lib/ref.sh);
  - a write under the features/ directory of the state ($QARGI_STATE, else <root>/state, and ~/.qargi/state), where the
    marshal keeps one record per open feature (and, beside them, the `.observed-<project>.json` clock cache of the shared-refs
    backend): decided like the other protected roots, reading stays allowed;
  - a write under the marshal/ directory of the state, where `marshal enable` keeps the per-project `.enabled` switch of the
    shared-refs backend: found and decided like features/, reading stays allowed;
  - a write under the runs/ directory of the state, where `qargi local verify` saves a copy of each passed run (OUT, the snapshots, the
    record) that `qargi review apply --from-saved` applies: decided like features/, reading stays allowed;
  - a write under the handoff/ and busy/ directories of the state, where `marshal handoff --write` records when the note was written and
    feature verify and release verify record the whole-suite run in progress: `qargi lead compact-check` reads them. Found and decided
    like features/, reading stays allowed. `qargi lead usage` and `compact-check` only read and stay allowed;
  - a write to the ref journal of the state ($QARGI_STATE/ref-journal.jsonl, its lock and any rotated or temporary file next to
    it, e.g. ref-journal.jsonl.lock, .1, .tmp): the lead's record of the branch moves its own verbs made, which `qargi local verify`
    accepts as lead-side changes; and the same for the registry of local runs ($QARGI_STATE/local-runs.jsonl and the files like it), which names the
    temporary directory `qargi local clean` removes for each run. Decided like features/; reading stays allowed. The journal is trusted only as far as the state
    directory is: an executor running as the same OS user could still edit the file by code the guard cannot see (HMAC-signed
    records are a later feature);
  - the verbs of the signed records: qargi marshal key|signers|resign (the lead's signing key, the allowed signers, a record signed
    with the key), refused with their own reason; and a write to the allowed signers ($QARGI_STATE/marshal/<project>.signers, under
    the marshal/ root above) or to the acceptance marks ($QARGI_STATE/features/.accepted-<project>.json, under features/), which the
    refusal names;
  - setting or unsetting QARGI_LEAD (the lead identity): an assignment, export, declare, printf -v, read or mapfile, unset or env -u in a command.
Signing key: the one credential a member may not even read is the lead's signing key for the marshal records,
  credentials/marshal_* (the private key and its public half) in any of the configuration directories above. The guard refuses
  the Read and Grep tools on it, and a Bash segment with any word that names it: after ~ and variables, braces,
  globs and symbolic links are resolved, in a `<` redirection (also one before the program, `exec 3<key`, or with no program at all), an `--opt=path` and in the text of a `-c` program. A directory that holds the key
  is refused as a source to the recursive readers (cp, rsync, tar, zip, ln, mv), not as the place they write to (`cp src ~/`, `tar -C ~ -x`); grep, rg, ag, find
  with an action and Grep are refused on the credentials directory itself only (a search that starts above it, `grep -r TODO ~`, is no read of the key; one that
  names the key is). ls, stat and test only look at it and stay allowed; the other credentials stay readable.
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
Reading a Bash command (passes(), segments()): a word quoted $'...' (ANSI-C) or $"..." is read as the plain string it stands for (ansi_c); then the plain, conservative split. The line is cut at every ; && || | & and newline whatever the quotes, a comment
or a heredoc body, so a refused verb is found wherever a command could start, and it is refused as text too: `git commit -m "Docs; qargi packs seed" && make` is
refused, and a member writes a message to a file with its file tool and commits with `git commit -F FILE`. The one narrowing (mask_data(), for the verbs that change
a skill or the marshal; push, gh and ssh are read in the whole text): when EVERY command of the line is echo, cat, tee, grep or git commit|log|status|diff|show|add
(they print, write or search the text and run nothing from it; not printf, whose -v assigns a variable), the ; | & and newlines inside a quoted string are blanks and a heredoc body is cut out, so
`git commit -m "Docs; qargi packs seed"` and a message written with `cat > msg <<'E'` are data. Another program in the line (a shell, make, a script, a
function, an assignment, a keyword, a group), a comment, a backslash, a substitution, $'..', ${..}, a quote or heredoc never closed, or a heredoc
delimiter that starts with # keeps the plain split; a file named in quotes (in a word with < or > or the word after one, or a file of tee) is never
blanked. As the plain split never sees such a name whole, a word that still holds a ; | & or newline after quote removal and resolves into a protected
location (or names the signing key) is refused as a path (separator_path_refusal). A $( ), <( ), >( ) or backtick substitution, also
inside double quotes, is a command of its own (the line is cut at it, and the text inside it is cut again on its own, so `cat <<<"$(qargi upgrade) x"` is read);
a line continuation is read both ways; `>|` is a redirection and is not cut; the keywords and groupings that a command follows (if, then, do, !, {, (, case
patterns, function definitions) and redirections written before it are skipped; an unbalanced quote falls back on the words with the quotes taken off.
A string handed to a shell (sh -c STRING, eval STRING) is read again, with the segments that follow it. So is the program a shell (sh, bash, dash, zsh, ksh; source
and . of /dev/stdin, /dev/fd/0, /proc/self/fd/0 or -) takes from its standard input (sh -s, sh - or no file, the words xargs brings, -I included) or from a file a
command of the same line writes, when the line shows it (program_fed): a here-string, an echo or printf piped in (through cat and tee; printf's format filled in,
escapes decoded) or written to that file; a heredoc body is read by the plain split already, and a redirection glued to the shell (bash<<<TEXT) is a word of its own.
A program the line does not show is refused, since the guard cannot read it: a pipe from cat FILE, curl or any other program, `bash < FILE`, a descriptor, a process
substitution, a here-string or an echo that a variable or a substitution builds, a file cp, a download or any other writer makes in the same line. The member writes
the script with its file tool and runs `bash FILE`. No other file is guessed to be run later.
Where the shell is: the line is cut more than once (the substitutions cut out, left whole, and each on its own), and every cut starts in the directory of
the call. A plain `cd DIR` at the top level (and pushd, popd, and a cd after an && whose chain is cds alone) changes the directory of what follows when DIR
is there; a cd to a word a variable, a substitution or a glob builds, with a CDPATH, or `env -C DIR` (and `builtin cd`) leaves the directory unknown (UNKNOWN_DIR),
and a write to a path that is not absolute is refused there; any other cd (inside ( ), a substitution, if/for/while/case, braces, a function, after || or `cmd &&`, before a pipe or &, in quoted text, a
here-document or a comment, an option, two directories, a DIR that is not there yet) leaves the old directory among those the shell may be in, `cd -` is
any directory the line has been in, and each command is judged from each of them (walk(); more than MAX_DIRS at once is refused).
A NUL byte, a command over 262144 characters, checks that take over BUDGET seconds (read inside the loops over words, targets, braces and project words, not
once per segment), a brace word that stands for more than MAX_BRACE words (or MAX_BRACE_WORK in all) and a glob that needs more than GLOB_ENTRIES directory
entries read are refused, since a hook that times out does not block.
Write targets (write_targets()): a redirection (> >> >| <> &> >&FILE, N-prefixed, stuck to its word or not, alone or in front of the program), tee, cp mv ln
install rsync ditto (every operand of mv: the sources are removed; -t DIR, also in a cluster: -rt DIR), tar and unzip extraction (below -C / -d, else where the
shell is), curl and wget output, patch (where the shell is, or -d DIR), git apply --directory, clone, init and worktree add DIR, dd of=, sort -o|--output, uniq INPUT OUTPUT, sed|perl -i, git --output=FILE, format-patch -o, archive -o, bundle create, and the
git subcommands that change the tree or the repository. A target the shell would expand and the guard cannot read (a glob or a variable, a command
substitution) is refused when it could name a record file of the run (`> abilit?`, `> $F`, `cp x $D/ability`) or, for a command that makes or replaces
its file, whenever a variable or a substitution builds the name; a glob that can name a protected location is refused for a write. A directory that only lies above a protected location or the run
(/tmp, $HOME) is refused as an mv destination only when something moved into it is, holds or has the name of the place (fits_beside), and always with -T. Under the read-only class the
variables a read-only tool takes its programs and options from (PATH, GIT_*, PAGER, BASH_ENV, RIPGREP_CONFIG_PATH, LD_* ...) are not set, and a write to
a git configuration or hook file (GIT_PLACE: ~/.gitconfig, ~/.config/git, .git/config, .git/hooks, .git/modules, .git/worktrees, config.worktree, info/attributes) in a
command that also runs git is refused for every member.
The run: a directory is a run when it holds ability and refs.before, or the clone and out directories beside any file of the record (RUN_CONTROL), and it is not
below the clone directory of another (a repository may hold a docs/tmpdir). RUN_CONTROL files are not written, moved, removed, copied or linked, nothing is
the run directory itself is no destination (a copy over it, an extraction, a link; run_dir_refusal), and the run directory is not removed or moved; under
`--class read-only` the run is not asked whether the member is read-only: a run that cannot be found refuses every write (NO_RUN).
Not seen: a script built by code (python -c ...), a program or a verb held in a variable, the output of a substitution handed to sh -c (`bash -c "$(echo qargi upgrade)"`),
a wrapper's option that takes a value (sudo -u root qargi ...; the ones of xargs are read).

Failure: the guard fails closed. Any unexpected exception ends in exit 2 with the reason on stderr. Input that is not
JSON is still let through (exit 0), as before. Known limits outside this file: a hook that cannot start, exits other than 0 or 2, times out or prints invalid
JSON is a non-blocking error for the runtime and the action goes ahead, so agents/member.md sets `onFailure: "block"` and a `timeout` (a runtime that does not
enforce `onFailure` lets such a failure through), and the frontmatter hooks of a project-level agent file run only after the workspace is trusted: until then the
member runs without this guard."""
import collections, fnmatch, functools, json, os, re, shlex, sys, time

SEPARATOR = re.compile(r"(&&|\|\||;|\||\n|(?<![<>&])&(?![>&]))")           # the separators, kept (re.split hands them back between the pieces); no \s* around them: a long run of blanks made that quadratic
NOCLOBBER_SEPARATOR = re.compile(r"(&&|\|\||;|(?<!>)\||\n|(?<![<>&])&(?![>&]))")
SUBST = re.compile(r"\$\(|`|[<>]\(")                       # command substitution and process substitution start a command of their own
HANDOFF_SUBST = re.compile(r"(?:marshal(?:\.sh)?[\"']*\s+[\"']*handoff|marshal_handoff\.py)[\"']*")   # `marshal handoff ... $(...)`: the substitution may produce --write, and splitting it off hides that
PROJECT_SET_SUBST = re.compile(r"project(?:\.sh)?[\"']*\s+[\"']*set[\"']*\s")   # `project set ... $(...)`: the substitution may produce a models path, and splitting it off hides that
AUDIT_SUBST = re.compile(r"packs_audit\.py[\"']*")   # `packs_audit.py ... $(...)`: the substitution may produce `store`, and splitting it off hides that
UNREADABLE = "$`{}*?[]"                                     # in a word: a variable, a substitution, a brace or a glob builds it, so the guard cannot read what it is
EXECUTED_ANSWERS = ("release", "test_command", "env", "upstream", "site")   # the answers the lead later runs, passes to a process, fetches from or builds from (release site): a member may not set them (project set)
ROLE_TOOLS_PATH = re.compile(r"roles|roles\.[^.]+|roles\.[^.]+\.tools(?:\..*)?")   # roles.<role>.tools: what env apply installs and local prepare checks out; a whole role, or all of them, holds it
PROJECT_VERBS = ("set", "init", "link", "unlink")           # the project verbs a member may not run (set: the models answers; init: the whole file; link, unlink: what a session loads)
XARGS_VALUE_OPTS = {"-I", "-a", "-d", "-E", "-L", "-n", "-P", "-s", "--arg-file", "--delimiter", "--max-lines", "--max-args", "--max-procs", "--max-chars", "--process-slot-var"}   # take the next word
WRAP = {"sudo", "env", "command", "builtin", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice", "parallel"}
WRITERS = {"rm", "rmdir", "touch", "mkdir", "chmod", "chown", "truncate", "tee", "patch", "unlink", "shred",
           "ex", "vi", "vim", "nvim", "ed", "rename", "sqlite3", "setfacl", "mkfifo"}      # the editors and the like write the files they are given
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
           "memory.sh", "tierwrite.sh", "tierplan.py", "memplan.py", "packs_link.py", "project_link.py", "gated_answers.py", "project.sh", "packs_audit.py", "marshal_handoff.py", "linker.py", "render.py", "local_run.py", "local.sh", "release.sh", "release_sign.py",
           "agent.sh", "team.sh", "env.py", "env_apply.py", "branch.sh", "changelog.sh", "changelog_numbers.py", "upstream.sh", "ref.sh")
# the command and the scripts behind the refused verbs (packs_link.py is packs link|unlink, packs_audit.py store is skill accept|unaccept,
# marshal_handoff.py is marshal handoff: the shell verbs call them, and a member could call them directly with a hand-made inputs file;
# linker.py, the link engine packs_link.py calls, is packs link, and render.py renders member definitions and runs the command a definition names)
OWN_ONLY = ("linker.py", "render.py", "env.py")                       # names too common to refuse by name alone: only the file of the tool is the script (own_script)
# Known limit, by design: the scripts are recognized by the NAME the command gives. `python3 LINK` where LINK is a symlink to lib/linker.py or
# lib/render.py, a copy of them under another name, and `python3 -c 'import linker'` (with lib on the path) are not recognized. A check on the
# resolved path would catch only a link that already exists when the call is judged, not one made earlier in the same command line
# (`ln -s .../linker.py x && python3 x`), and an import can be spelled in too many ways (importlib, __import__, string joins) to read from
# the command text; a half check would suggest a guarantee the guard does not give. Like the rest of the shell reading it is a heuristic
# against a mistake, not a wall against a member that works to get round it; the local verify of the patches is the backstop.
MEMORY_VERBS = ("init", "move", "split", "merge", "copy")                          # qargi memory verbs that change a memory tier
MEMORY_READ = ("tiers", "check", "get", "lint")
PROVIDER_READ = ("", "list", "show", "effective", "require-barrier", "skills-dirs", "of", "layout", "require-skills", "launch", "addenda", "notes", "model")   # the provider verbs that only read; the rest, and any verb added later, change the definitions or run code (check, adapter-run)
BUILT_VERB_AREAS = {"skill", "tool", "packs", "discover", "project", "local", "cloud", "memory"}   # a verb the shell builds in these is refused: one of the verbs that change something may be what it builds
ENV_LEAD = ("plan", "apply")                                   # the verbs of qargi env that run a project's commands (lib/env_apply.py)
LEAD_VERBS = {("local", "clean"), ("local", "close"), ("local", "prepare"), ("local", "verify"), ("agent", "remove"), ("project", "new"), ("team", "run")}   # the lead's runs and agents: `local clean --discard` removes another run with no token
MEMORY_NOTE = "propose it in your report"
MARSHAL_READ = ("status", "check", "handoff")                # handoff only reads; with --write it makes a file and is refused (skill_verb)
MARSHAL_SIGNING = {"key": "manages the marshal's signing key", "signers": "manages the marshal's allowed signers",
                   "resign": "signs a marshal record with the lead's key"}      # the verbs of the signed records, each refused with its own reason
MEMBER_MARK = "QARGI_MEMBER_RUN"                             # the variable `qargi local run` puts in a member's environment (marshal_refs.in_member_run reads it): setting or unsetting it is refused
FEATURE_OPEN = ("", "list", "status", "merge", "sync")       # the feature verbs that start, finish or verify nothing; status, merge and sync still renew the lead's own lease (check --renew), so what keeps a member from renewing it is the member mark (QARGI_MEMBER_RUN) and the run directory it works in, not this list (the rest writes, or is unknown)
UPSTREAM_OPEN = ("", "review")                               # the upstream verbs that only read: status fetches into the lead's repository and sync moves a branch (the rest is unknown)
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
BUDGET = 5.0                                                 # seconds of checking before a call is refused, counted from the start of judge() and checked in every loop (tick): the hook is killed at its timeout, and a hook that times out does not block
MAX_BRACE = 256                                              # words one brace expression may stand for; more is refused, not cut (the words past the cut would be unchecked)
MAX_BRACE_WORK = 20000                                       # brace words, in all, that one call may expand
_DEADLINE = [None]
_CLOCK = [time.monotonic]                                   # the clock the budget is counted on (judge sets the deadline, tick reads it); a test injects one it advances itself


class TooSlow(Exception):
    """The checks of one call took longer than BUDGET: the call is refused, as a hook that is killed would let it through."""


class TooManyBraces(TooSlow):
    """A brace expression that stands for more than MAX_BRACE words, or braces that together stand for more than MAX_BRACE_WORK: the call is refused."""


class TooNested(TooSlow):
    """Substitutions nested more than MAX_NESTED deep: the texts inside them, each holding the next, cost more than the time a hook has."""


class TooBroad(TooSlow):
    """A glob in a word would need more directory entries read than GLOB_ENTRIES to be expanded (`cat /*/*/*/*/*/*`): the call is refused, not expanded."""


def tick():
    if _DEADLINE[0] is not None and _CLOCK[0]() > _DEADLINE[0]:
        raise TooSlow()


SUBST_START = re.compile(r"\$\(|`")


def word_then_subst(word, text):
    """True when a command (the text between separators) has the pattern word and, after its first occurrence, a command substitution (`handoff ... $(...)`).
    The first occurrence is the one with the most text after it, so this is what the pattern word followed by [^;&|\\n]* and a substitution said, in one pass and
    not one scan of the rest of the command per occurrence (a long run of the word took minutes)."""
    for chunk in re.split(r"[;&|\n]", text):
        m = word.search(chunk)
        if m and SUBST_START.search(chunk, m.end()):
            return True
    return False


GIT_VALUE_OPTS = ("-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--config-env")   # git's global options that take the next word
GIT_PUSHERS = {"push", "send-pack", "http-push"}             # the git subcommands that publish
GIT_PUSH_PROGRAMS = {"git-push", "git-send-pack", "git-http-push", "git-receive-pack"}   # and the programs behind them, run by their own name
# the git configuration keys that make git run a program, read another configuration file, or give a command or a remote another name: refused in
# `git -c KEY=V`, `--config-env KEY=V` and every `git config` that writes one (one list; git reads the section and the key whatever their case)
GIT_RUNS_CODE = re.compile(r"^(?:alias\..*|include(?:if\..*)?\.path|core\.(?:pager|editor|fsmonitor|hookspath|sshcommand|askpass|gitproxy|alternaterefscommand)|"
                           r"diff\.external|pager\..*|sequence\.editor|credential\..*|gpg\..*|filter\..*|diff\..*\.(?:command|textconv)|merge\..*\.driver|"
                           r"(?:diff|merge)tool\..*\.cmd|submodule\..*\.update|uploadpack\..*|receivepack\..*|url\..*\.(?:insteadof|pushinsteadof)|"
                           r"remote\..*\.(?:receivepack|uploadpack|vcs|url|pushurl)|protocol\.(?:ext\.)?allow)$", re.I)
GIT_ENV_RUNS_CODE = re.compile(r"^(?:GIT_CONFIG_(?:COUNT|KEY_\d+|VALUE_\d+|PARAMETERS|GLOBAL|SYSTEM)|GIT_EXEC_PATH|GIT_SSH(?:_COMMAND)?|GIT_PROXY_COMMAND|GIT_ASKPASS|GIT_EXTERNAL_DIFF|"
                               r"GIT_PAGER|GIT_EDITOR|GIT_SEQUENCE_EDITOR)$")
REMOTE_CHANGES = ("add", "set-url", "remove", "rm", "rename", "set-branches", "set-head")
def remote_operand(w):
    """True when the word names a place on another host (host:path, user@host:path, [::1]:path, rsync://host/m), not a local path or an option's text. Not a
    regular expression: an optional user@ in front of a host made one quadratic on a long run of at signs."""
    head, colon, _ = w.partition(":")
    return w.startswith("rsync://") or bool(colon and head and "/" not in head and not head.isspace() and not re.search(r"\s", head))


def git_global(rest):
    """([(option, value)], k): the global options of a git command line (-C DIR, -c K=V, --work-tree=D, --no-pager ...) and the index in rest of the subcommand
    (len(rest) when there is none). value is None for an option with none."""
    opts, k = [], 0
    while k < len(rest) and rest[k].startswith("-"):
        t = rest[k]
        if t in GIT_VALUE_OPTS and k + 1 < len(rest):
            opts.append((t, rest[k + 1]))
            k += 2
        else:
            name, eq, val = t.partition("=")
            opts.append((name, val if eq else None))
            k += 1
    return opts, k


def builds_word(w):
    """True when a variable or a substitution takes part in the word, so the guard cannot read what it stands for."""
    return "$" in w or "`" in w


def git_refusal(pre, rest):
    """The reason a git command line (pre: the words before git, with the assignments in front of it; rest: the words after) publishes, reaches out under another
    name or runs a program a member names, or None. Only the subcommand counts: the first word after the global options (`git commit -m push` is no push)."""
    opts, k = git_global(rest)
    sub, args = (rest[k], rest[k + 1:]) if k < len(rest) else ("", [])
    if sub in GIT_PUSHERS:
        return "git %s is not available to an agent" % sub
    if sub == "svn" and "dcommit" in args:
        return "git svn dcommit is not available to an agent"
    nonopt = [t for t in args if not t.startswith("-")]
    if sub == "remote" and nonopt[:1] and nonopt[0] in REMOTE_CHANGES:
        return "changing a git remote is not available to an agent"
    if builds_word(sub):
        return "a git subcommand that a variable or a substitution builds (%s) could be a push or any other verb and is not available to an agent" % sub
    if sub == "config":
        why = config_refusal(args, any(os.path.basename(t) == "xargs" for t in pre))
        if why:
            return why
    for name, val in opts:
        key = (val or "").partition("=")[0]
        if (name in ("-c", "--config-env") and GIT_RUNS_CODE.match(key)) or (name == "--exec-path" and val):
            return ("git %s %s sets a git configuration that runs a program or gives a git command another name (an alias can be a push) and is not available to an agent"
                    % (name, val))
    for t in pre:
        m = ASSIGNMENT.match(t)
        if m and GIT_ENV_RUNS_CODE.match(m.group(1)):
            return "git with %s set reads a configuration that runs a program or gives a git command another name (an alias can be a push) and is not available to an agent" % m.group(1)
    return None


CONFIG_VALUE_OPTS = {"--file", "-f", "--blob", "--type", "-t", "--default", "--comment", "--value", "--url"}   # git config options that take the next word
CONFIG_VERBS = {"set", "get", "list", "unset", "rename-section", "remove-section", "edit"}       # the subcommands of git config (2.46): a key always has a dot
CONFIG_ANY = {"--edit", "-e", "--rename-section", "edit", "rename-section"}                       # can make any key: an editor on the file, a section renamed to alias


def config_written(args):
    """The keys `git config ARGS` writes: the key of set, --add, --replace-all or NAME VALUE; [] for a read (--get, --list, a key alone), an unset or a section
    removed; None when it can make any key (--edit, a section renamed)."""
    names, opts, skip = [], [], False
    for a in args:
        if skip:
            skip = False
        elif a in CONFIG_VALUE_OPTS:
            skip = True
        elif a.startswith("-"):
            opts.append(a.split("=", 1)[0])
        else:
            names.append(a)
    if names[:1] and names[0] in CONFIG_VERBS:
        verb, names = names[0], names[1:]
        return None if verb in CONFIG_ANY else names[:1] if verb == "set" else []
    if any(o in CONFIG_ANY for o in opts):
        return None
    if any(o in CONFIG_READS or o in ("--unset", "--unset-all", "--remove-section") for o in opts):
        return []
    return names[:1] if len(names) > 1 or any(o in ("--add", "--replace-all") for o in opts) else []


def config_refusal(args, via_xargs):
    """The reason `git config ARGS` writes a key in GIT_RUNS_CODE (in any scope or file), one a variable or xargs brings, or any key, or None."""
    keys = config_written(args)
    if keys is None:
        return ("git config --edit and a renamed section can write any key, one that runs a program or gives a git command another name (an alias can be a push) "
                "among them, and are not available to an agent")
    if via_xargs and not any(a.split("=", 1)[0] in CONFIG_READS for a in args):
        return "git config through xargs writes a key the guard cannot read, which could run a program or give a git command another name, and is not available to an agent"
    for key in keys:
        if builds_word(key) or GIT_RUNS_CODE.match(key):
            return ("git config %s sets a git configuration that runs a program, reads another configuration file or gives a git command or a remote another name "
                    "(an alias can be a push) and is not available to an agent" % key)
    return None


def blocked(command, depth=0):
    seen = set()
    for seg in segments(command):
        tick()
        if seg in seen:
            continue
        seen.add(seg)
        toks, i = parsed(seg)
        if i >= len(toks):
            continue
        prog = os.path.basename(toks[i])
        rest = toks[i + 1:]
        if prog in ("gh", "ssh", "scp", "sftp"):
            return "%s is not available to an agent" % prog
        if prog in GIT_PUSH_PROGRAMS or prog in ("svn", "git-svn") and "dcommit" in rest:
            return "%s is not available to an agent" % prog
        if prog == "rsync" and any(remote_operand(t) for t in rest if not t.startswith("-")):
            return "rsync to or from another host is not available to an agent"
        if prog == "git":
            why = git_refusal(toks[:i], rest)
            if why:
                return why
        inner = shell_string(prog, rest) if depth < 3 else None
        why = blocked(inner, depth + 1) if inner is not None else None
        if why:
            return why
    for _, ps in passes(command) if depth < 3 else ():       # a shell fed its program on its standard input or in a file the line writes: the text the line shows is read again
        for n, p in enumerate(ps):
            toks, i = parsed(p.text)
            if i < len(toks) and (os.path.basename(toks[i]) in SHELLS or os.path.basename(toks[i]) in SOURCES):
                for text in program_fed(ps, n, ".")[0]:
                    why = blocked(as_program(text), depth + 1)
                    if why:
                        return why
    return None


ANSI_ESCAPES = {"a": "\a", "b": "\b", "e": "\x1b", "E": "\x1b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v", "\\": "\\", "'": "'", '"': '"', "?": "?"}
ANSI_CODE = re.compile(r"x([0-9A-Fa-f]{1,2})|([0-7]{1,3})|u([0-9A-Fa-f]{1,4})|U([0-9A-Fa-f]{1,8})|c(.)", re.S)


def ansi_c(text):
    """text with every $'...' (ANSI-C quoting: the shell decodes \\n, \\xHH, \\NNN, \\uHHHH ...) written as the plain single-quoted string it stands for, and
    $"..." as "...": a word quoted so (git $'push') is the word it decodes to for every check that reads the words. A $' inside a quote is no
    ANSI-C quote and is left. One pass over the text."""
    if "$'" not in text and '$"' not in text:
        return text
    out, quote, k, n = [], "", 0, len(text)
    while k < n:
        c = text[k]
        if quote == "'":
            quote = "" if c == "'" else quote
        elif c == "\\" and k + 1 < n:
            out.append(text[k:k + 2])
            k += 2
            continue
        elif c == "'" and quote == "":
            quote = "'"
        elif c == '"':
            quote = "" if quote else '"'
        elif c == "$" and quote == "" and text[k + 1:k + 2] == '"':
            k += 1                                           # $"..." is "..." (a translated string)
            continue
        elif c == "$" and quote == "" and text[k + 1:k + 2] == "'":
            buf, k = [], k + 2
            while k < n and text[k] != "'":
                k = escape_at(text, k, buf)
            out.append("'" + "".join(buf).replace("'", "'\\''") + "'")
            k += 1
            continue
        out.append(c)
        k += 1
    return "".join(out)


def escape_at(text, k, buf):
    """Append to buf what the character at text[k] stands for in an ANSI-C string (a backslash escape: \\n, \\xHH, \\NNN, \\uHHHH, \\cX ...; else the
    character itself) and return the index after it."""
    n = len(text)
    if text[k] != "\\" or k + 1 >= n:
        buf.append(text[k])
        return k + 1
    m = ANSI_CODE.match(text, k + 1)
    if text[k + 1] in ANSI_ESCAPES:
        buf.append(ANSI_ESCAPES[text[k + 1]])
        return k + 2
    if m and m.group(5) is not None:
        buf.append(chr(ord(m.group(5)) & 31))
        return m.end()
    if m:
        code = int(m.group(1) or m.group(3) or m.group(4) or m.group(2), 16 if m.group(2) is None else 8)
        buf.append(chr(code) if 0 < code < 0x110000 else "")
        return m.end()
    buf.append(text[k:k + 2])
    return k + 2


def escapes_decoded(text):
    """text with its backslash escapes decoded as an ANSI-C string decodes them (what echo -e, printf and %b print for them)."""
    if "\\" not in text:
        return text
    buf, k = [], 0
    while k < len(text):
        k = escape_at(text, k, buf)
    return "".join(buf)


@functools.cache
def split_words(seg):
    """shlex.split of one segment, cut once per text (the checks of a call all ask); raises ValueError for an unbalanced quote."""
    return tuple(shlex.split(ansi_c(seg)))


def tokens(seg):
    try:
        toks = list(split_words(seg))
    except ValueError:                                       # an unbalanced quote (a substitution cut out of a quoted string): the words with the quotes taken off
        toks = re.sub(r"[\\'\"]", "", ansi_c(seg)).split()
    return toks


KEYWORDS = {"if", "then", "elif", "else", "while", "until", "do", "!", "{", "(", "coproc"}   # a command follows them
LEADING_REDIR = re.compile(r"^(?:\d*|&)(?:<<<|<<-?|<>|>>|>\||>&?|<&?|&>>?)")
BARE_REDIR = re.compile(r"^(?:\d*|&)(?:<<<|<<-?|<>|>>|>\||>&?|<&?|&>>?)$")           # the operator alone: its target is the next word


def skip_wrappers(toks):
    """The index of the program: past assignments (VAR=x), wrappers (sudo, env, time ...), their options, the keywords a command can follow (then, do, !) and
    redirections written before the program (> f, 2>&1)."""
    i, env, xargs = 0, False, False
    while i < len(toks):
        t = toks[i]
        if t in ("-C", "--chdir") and env:
            i += 2                                           # env -C DIR PROGRAM: DIR is where PROGRAM runs, not the program
        elif xargs and t in XARGS_VALUE_OPTS:
            i += 2                                           # xargs -I {} sh -c '{}': {} is the replace string, not the program
        elif "=" in t.split("/")[0] and not t.startswith("-") or os.path.basename(t) in WRAP or t.isdigit() or (t.startswith("-") and i) or t in KEYWORDS:
            env = env or os.path.basename(t) == "env"
            xargs = xargs or os.path.basename(t) == "xargs"
            i += 1
        elif LEADING_REDIR.match(t):
            i += 2 if BARE_REDIR.match(t) else 1
        else:
            break
    return i


GLUED_SHELL = re.compile(r"^([^<>]+)([<>].*)$", re.S)     # a program word with a redirection glued to it


@functools.cache
def parsed(seg):
    """(the words of a segment without what the grammar puts around a command, the index of its program): _cmd_tokens and skip_wrappers, once per text (every check
    asks). The list is shared: not to be changed."""
    toks = list(_cmd_tokens(seg))
    i = skip_wrappers(toks)
    m = GLUED_SHELL.match(toks[i]) if i < len(toks) else None
    if m and (os.path.basename(m.group(1)) in SHELLS or m.group(1) in SOURCES):
        toks[i:i + 1] = [m.group(1), m.group(2)]               # bash<<<TEXT, sh<FILE: the redirection glued to the program is a word of its own for the shell
    return toks, i


@functools.cache
def _cmd_tokens(seg):
    """The words of a segment, without what the grammar puts around a command: the ( stuck to the first word, a case pattern (x)), and the ) that closes
    a group or a substitution stuck to the last. Cut once per text (a command is asked about by several checks)."""
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


Piece = collections.namedtuple("Piece", "text top chained piped")   # top: a plain cd here, if it is one, changes the directory of what follows if the command before it in its && chain ran (see pieces()); chained: it follows an &&; piped: it follows a | (its standard input is the output of the piece before it)
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
    out, depth, quote, heredoc, comment, piped = [], 0, "", False, False, False
    for k in range(0, len(parts), 2):
        tick()
        piece = parts[k]
        before, after = (parts[k - 1] if k else ""), (parts[k + 1] if k + 1 < len(parts) else "")
        piped = piped or before.strip() == "|"                # `a |& b` and `a |<newline> b` leave an empty piece between the | and the command
        opens, closes = counted.get(k - 1, (0, 0))
        ahead = counted.get(k + 1, (0, 0))[0]                # a substitution starts behind this piece: its command goes on after it
        if "\n" in before:
            comment = False
        depth = max(0, depth + opens - closes)
        top_level = (top and depth == 0 and not quote and not heredoc and not comment and before.strip() in SEQUENCE + ("&&",) and after.strip() not in ("|", "&")
                     and not ahead and not opens and not closes)
        if piece.strip():
            out.append(Piece(piece.strip(), top_level, before.strip() == "&&", piped))
            piped = False
        words = piece.split()
        first = words[0] if words else ""
        depth = max(0, depth + piece.count("(") - piece.count(")") + (first in KEYWORDS_OPEN) - (first in KEYWORDS_CLOSE) + words.count("{") - words.count("}"))
        comment = comment or (not quote and bool(re.search(r"(?:^|\s)#", piece)))
        heredoc = heredoc or bool(re.search(r"<<(?!<)", piece))
        quote = quote_after(piece, quote)
    return tuple(out)


FIND_EXEC = re.compile(r"-(?:exec|execdir|ok|okdir)\s")


def find_commands(text):
    """The commands that find -exec, -execdir, -ok and -okdir run in a piece of a command line: what follows each of them, up to the next one."""
    return [c.strip() for c in re.split(r"(?:^|\s)-(?:exec|execdir|ok|okdir)(?=\s)", text)[1:] if c.strip()]


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
        if FIND_EXEC.search(form):                           # the command after -exec is a command of its own (find . -exec git X {} \;)
            extra = [c for p in out[-1][1] for c in find_commands(p.text)]
            if extra:
                out.append(("inner", pieces("\n".join(extra), top=False)))
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


INERT = {"echo", "cat", "tee", "grep", "egrep", "fgrep"}   # programs that do nothing with the text of an argument or of their input but print, write or search it (not printf: -v assigns)
INERT_GIT = {"commit", "log", "status", "diff", "show", "add"}       # git subcommands that are in the same case (git commit -m TEXT, git commit -F -)
MASK_BAIL = re.compile(r"[\\`\0\r\x0b\x0c]|\$[\[\x27\"({]|[<>]\(")  # a backslash, a substitution, $'..', $"..", ${..}, $[..], a control character: not read here
MASK_TOKEN = re.compile(r"""'|"|<<<|<<-?|[;|&\n()]|[ \t]+|#|[^'"<;|&\n()# \t]+|.""", re.S)
HEREDOC_WORD = re.compile(r"""[ \t]*(?:'([^'\n]*)'|"([^"\n]*)"|([^\s;&|<>()'"]+))(?=[ \t\n;&|)<>]|$)""")
MASK_SEPARATORS = re.compile(r"[;|&\n]")
REDIRECT_END = re.compile(r"[<>][|&]?$")                    # a word that is a redirection whose file is the next word (>, &>, 2>>, {fd}>, >|, >&)


def inert_command(words):
    """True when the command whose words are given does nothing with the text of its arguments or its input (see mask_data)."""
    return bool(words) and (words[0] in INERT or (words[0] == "git" and len(words) > 1 and words[1] in INERT_GIT))   # a quoted word carries \x01: it is no name here


def mask_data(command):
    """The command with its data made harmless to the plain split, or the command itself. The split (segments) cuts a line at every ; | & and newline,
    inside quotes and heredocs too, so `git commit -m "Docs; qargi packs seed"` and a heredoc that a commit message is written from were refused as the
    verb they mention. When EVERY command of the line is one that only prints, writes or searches (INERT: echo, cat, tee, grep, git commit|log|status|
    diff|show|add; not printf, whose -v NAME assigns a variable, and an array subscript in NAME runs a substitution), a quoted string of it cannot run
    anything, and a heredoc body is the input of such a command: the separators in the quoted strings become blanks and the heredoc bodies are cut out
    (the delimiter line stays), and nothing else changes, so a redirection or a path in the line is still judged. Any other command in the line (a shell,
    make, find, a script, a function, an assignment, a keyword, a group), a comment, a backslash, a substitution, $'..', ${..}, a quote or heredoc that
    is never closed, a heredoc delimiter that starts with # (bash reads it as a comment): the command is returned as it is, and the plain split reads all of it. A quoted string that names a file is not blanked: one in a
    word that holds a < or > (`>"a;b"`, `&>"a;b"`, `&>>"a;b"`, `x>"a;b"`, `{fd}>"a;b"`) or in the word after one (`> "a;b"`), and the command is returned
    as it is when a quoted string with a separator is among the words of tee (the files it writes). Used for the verbs that change a skill or the
    marshal, not for push/gh/ssh (blocked() reads the whole text); separator_path_refusal() judges such a name as a path."""
    if not QUOTED.search(command) or MASK_BAIL.search(command):
        return command
    n, pos, count = len(command), 0, 0
    words, cur, spans, pending = [], [], [], []                 # cur: the pieces of the word being read, joined when it ends (one long word stays linear)
    redir = False                                               # the word being read holds a < or >
    quotes = []                                                 # (start, end) of the quoted strings that hold a separator

    def end_word():
        nonlocal redir
        if cur:
            words.append("".join(cur))
            cur.clear()
        redir = False

    while pos < n:
        count += 1
        if not count & 255:
            tick()
        t = MASK_TOKEN.match(command, pos).group()
        end = pos + len(t)
        if t in ("'", '"'):
            j = command.find(t, end)
            if j < 0:
                return command                              # never closed
            target = redir or (not cur and bool(words) and bool(REDIRECT_END.search(words[-1])))   # a file a redirection names
            if MASK_SEPARATORS.search(command, end, j):
                if words and words[0] == "tee":
                    return command                          # a file tee writes: the plain split reads it, and separator_path_refusal the name
                if not target:
                    quotes.append((end, j))
            cur.append("\x01")
            end = j + 1
        elif t == "<<<":
            end_word()
            words.append(t)
        elif t in ("<<", "<<-"):
            end_word()
            m = HEREDOC_WORD.match(command, end)
            if not m or (m.group(3) or "").startswith("#"):
                return command                              # no delimiter, or one bash reads as a comment (`cat <<#E`)
            pending.append((next(g for g in m.groups() if g is not None), t == "<<-"))
            end = m.end()
        elif t == "(" or t == ")":
            return command
        elif t == "#":
            if not cur:
                return command                              # a comment
            cur.append(t)
        elif t == "&" and (command[pos - 1:pos] in ("<", ">") or command[end:end + 1] == ">"):
            cur.append(t)                                   # 2>&1, <&3, &>file: a redirection, not a separator
        elif t == "|" and command[pos - 1:pos] == ">":
            cur.append(t)                                   # >| file
        elif t in (";", "|", "&", "\n"):
            end_word()
            if words and not inert_command(words):
                return command
            words = []
            if t == "\n" and pending:
                s = end
                for delim, tabs in pending:
                    body = s
                    while True:
                        nl = command.find("\n", s)
                        line = command[s:n if nl < 0 else nl]
                        if (line.lstrip("\t") if tabs else line) == delim:
                            break
                        if nl < 0:
                            return command                  # the delimiter never comes
                        s = nl + 1
                        count += 1
                        if not count & 255:
                            tick()
                    spans.append((body, s))
                    s = n if nl < 0 else nl + 1
                pending = []
                end = s
        elif t in (" ", "\t"):
            end_word()
        else:
            cur.append(t)
            redir = redir or "<" in t or ">" in t
        pos = end
    end_word()
    if pending or (words and not inert_command(words)):
        return command
    cuts = sorted([(a, b, False) for a, b in quotes] + [(a, b, True) for a, b in spans])
    if not cuts:
        return command
    out, last = [], 0
    for a, b, body in cuts:
        out.append(command[last:a])
        if not body:
            out.append(MASK_SEPARATORS.sub(" ", command[a:b]))
        last = b
    out.append(command[last:])
    return "".join(out)


UNKNOWN_DIR = "\0unknown"                                   # in the directories the shell may be in: a directory the guard cannot name (`cd $(dirname $PWD)`, `cd "$d"`, `env -C $d`)
MAX_DIRS = 24                                                # directories the shell may be in at once, at most: a cd that may or may not happen doubles them
CD_FLAGS = ("-P", "-L", "-e", "-@", "--")
PLAIN_CD = re.compile(r"\s*(?:cd|pushd|popd)(?:\s|$)")


class TooManyDirs(TooSlow):
    """A command line that changes directory in more than MAX_DIRS ways that cannot be told apart (each cd that may not happen doubles the places the next
    command may run in): the call is refused, not judged from some of them."""


def moved(dirs, args, certain, visited, cdpath=False):
    """The directories the shell may be in after `cd ARGS` from any of dirs. certain: the cd is a plain command of the top level, so it changes the
    directory when the directory is there (a directory that is not there yet may be made by a command before it: both are kept). Anything else keeps
    the directory it was in as well. `cd -` is any directory the line has been in."""
    ops = [t for t in args if t not in CD_FLAGS]
    if ops == ["-"]:
        return list(dict.fromkeys(dirs + visited))
    target = ops[0] if ops else "~"
    unknown = bool(UNKNOWN.search(expand_path(target))) or cdpath
    certain = certain and len(ops) <= 1 and not target.startswith("-") and not unknown
    new = [UNKNOWN_DIR] if unknown else []                    # the shell is in a directory the guard cannot name: relative writes are refused there (unknown_dir_refusal)
    for d in dirs:
        tick()
        if d == UNKNOWN_DIR:
            r = resolve("/", target) if target.startswith(("/", "~")) else None
            new += [r] if r and certain else [d] + ([r] if r else [])
            continue
        r = resolve(d, target)
        new += [r] if certain and os.path.isdir(r) else [d, r]
    new = list(dict.fromkeys(new))
    if len(new) > MAX_DIRS:
        raise TooManyDirs()
    return new


def env_chdir(toks, i):
    """The directory `env -C DIR` or `env --chdir=DIR` among the words before the program (toks[:i]) names, else None: the program runs there."""
    env = False
    for k in range(min(i, len(toks))):
        t = toks[k]
        if os.path.basename(t) == "env":
            env = True
        elif env and t in ("-C", "--chdir") and k + 1 < len(toks):
            return toks[k + 1]
        elif env and t.startswith("--chdir="):
            return t.split("=", 1)[1]
    return None


def walk(command, here):
    """Every piece of every cut of the command, with the directories the shell may be in when it runs it: (n, ps, text, dirs). ps: the pieces of the
    cut and n the place of this one in it. here: the directory the call runs in (or a list of them). A plain `cd` at the top level of the line changes
    them for what follows (after an && only if the commands before it in the chain are plain cds too: `pushd d && popd && cmd`); a cd anywhere else (a
    subshell, a substitution, an if, after || or `cmd &&`, before a pipe, with an option or two directories ...)
    leaves the directory it was in among them, and every command is judged from each. pushd and popd are followed like cd. Each cut starts in the
    directory of the call, and a substitution's own text in any directory the line has been in, so a cd is never applied twice to one command."""
    start = list(dict.fromkeys([here] if isinstance(here, str) else here))
    visited = list(start)
    cdpath = "CDPATH" in command or bool(os.environ.get("CDPATH"))      # a CDPATH can send any cd to another directory than the one it names
    for kind, ps in passes(command):
        dirs = list(start) if kind == "main" else list(visited)
        if len(dirs) > MAX_DIRS:
            raise TooManyDirs()
        stack, ran = [], False                               # ran: the piece before was a cd that is certain
        for n, piece in enumerate(ps):
            tick()
            toks, i = parsed(piece.text)
            chdir = env_chdir(toks, i)
            yield n, ps, piece.text, (moved(dirs, [chdir], False, visited, cdpath) if chdir else dirs)     # env -C DIR PROGRAM runs PROGRAM in DIR, once
            prog = os.path.basename(toks[i]) if i < len(toks) else ""
            if prog not in ("cd", "pushd", "popd"):
                ran = False
                continue
            certain, rest = piece.top and bool(PLAIN_CD.match(piece.text)) and (ran or not piece.chained), toks[i + 1:]    # after &&, only when everything before it in the chain is such a cd
            ran = certain
            if prog == "cd":
                dirs = moved(dirs, rest, certain, visited, cdpath)
            elif prog == "pushd":
                named = [t for t in rest if not t.startswith(("-", "+"))]
                if named and "-n" not in rest:
                    stack.append(dirs)
                    dirs = moved(dirs, named[:1], certain, visited, cdpath)
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


RUN_CONTROL = ("ability", "class", "profile", "refs.before", "refs.after", "refs.diff", "refs.accepted", "verified", "started", "tmpdir", "applied", "repo.path", "repo.url", "cred.path", "git", "dispatch.json", "task.md", "refs.before.new")


def control_refusal(full):
    """The reason a write to a run directory's own record is refused, or None. RUN_CONTROL is every file of the run directory that `qargi local` reads
    back or that names something it uses: the ability and class the guard is held to, the refs the run is compared with, the temporary directory prepare made
    (tmpdir: `local clean` takes the one to remove from the lead's registry, never from this file), the repository and the tip it asks whether the work is
    merged (repo.path, applied), the credential path, the git wrapper."""
    if os.path.basename(full) in RUN_CONTROL and run_dir(os.path.dirname(full)) == os.path.dirname(full):
        return "%s is the run's own record (the coordinator wrote it); a member does not change it" % full
    return None


def run_dir_refusal(full):
    """The reason a write to the real path full is a write to the run directory itself, or None. A copy over the directory (`cp -r Y/. ..`), an
    extraction (`tar -C .. -xf`, `cd .. && tar xf`, `unzip -d ..`), `install -Dt ..`, a move or a link into it names no file: the files are made under the
    names they have in the source, which can be the run's record. Refused whatever way the path to it is written (`.`, `..`, a trailing `/.`, a
    relative path from where the shell is), for every member. A file with a name of its own in the run directory is the record's names (control_refusal)
    and nothing else; OUT, the clone and TMP are the member's."""
    run = run_dir(full if os.path.isdir(full) else os.path.dirname(full))
    if run and full == run:
        return "%s is the run directory: a copy, an extraction, a link or a move into it can make any file of the run's record; name the files in out/ or the clone" % full
    return None


@functools.cache                                     # the files do not change while one command is judged
def run_tmps(run):
    """The temporary directories of a run that are the member's (TMP): the one the lead's registry names for it, as `qargi local clean` reads it (the run's own
    tmpdir file is not read: a member can write it), and run/tmp, where prepare puts it when there is no /dev/shm."""
    real = os.path.realpath(run)
    out = [os.path.join(real, "tmp")]
    for st in state_dirs():
        try:
            with open(os.path.join(st, REGISTRY), encoding="utf-8", errors="replace") as f:
                for n, line in enumerate(f):
                    if not n % 256:
                        tick()
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if isinstance(e, dict) and isinstance(e.get("run"), str) and isinstance(e.get("tmpdir"), str) and os.path.realpath(e["run"]) == real and os.path.isabs(e["tmpdir"]):
                        out.append(os.path.realpath(e["tmpdir"]))
        except OSError:
            pass
    return tuple(out)


def member_space(full, run):
    """True when the real path full is in OUT or TMP of the run: all that a member of the read-only class writes."""
    return inside(full, os.path.join(os.path.realpath(run), "out")) or any(inside(full, t) for t in run_tmps(run))


def run_refusal(full, here):
    """The reason a command that removes or moves the path full takes the run directory (or a directory above it) away, with the record in it, or None."""
    run = run_dir(here)
    if run and inside(run, full):
        return "%s is the run directory (or holds it): its record and its clone are not for a member to remove or move" % full
    return None


@functools.cache
def run_class(run):
    try:
        with open(os.path.join(run, "class")) as f:
            return f.read().strip()
    except OSError:
        return ""


@functools.cache                                     # the files do not change while one command is judged
def ability_of(run):
    try:
        with open(os.path.join(run, "ability")) as f:
            return f.read().strip()
    except OSError:
        return ""


def inside(path, base):
    return path == base or path.startswith(base.rstrip(os.sep) + os.sep)


_OUT = [None]                                        # the run's out directory, for a command that uses $OUT and nothing in it could set it (out_dir)
SETTERS = re.compile(r"\b(?:eval|declare|typeset|readonly|export|local|read|mapfile|readarray|getopts|let|source|env|set|printf\s+-v)\b|\$\{!|(?:^|[\s;&|(])\.\s|"
                     r"\b(?:sh|bash|zsh|dash|ksh)\b")      # what can set a variable by a name the text does not show


def out_dir(call):
    """The out directory of the run the call is made in when the command writes through $OUT or ${OUT}, the hook's environment has no OUT, and nothing in the
    command could give it a value (no other mention of the name, no eval, export, read, source, sh -c ...), else None. The task block names OUT, and a
    member that has it in its shell uses it; the guard cannot expand it and refused it. A value the command gives it is a path the guard cannot read."""
    c = call.command or ""
    if call.kind != "shell" or "OUT" in os.environ or "OUT" not in c:
        return None
    if re.search(r"(?<![A-Za-z0-9_])OUT(?![A-Za-z0-9_])", re.sub(r"\$\{OUT\}|\$OUT(?![A-Za-z0-9_])", "", c)) or SETTERS.search(c):
        return None
    run = run_dir(call.cwd)
    return os.path.join(run, "out") if run else None


def expand_path(p):
    """p with ~ and the variables of the environment expanded: $NAME, ${NAME}, and ${NAME<anything>} (${NAME:-x}, ${NAME%/}, ${NAME:+y}) as the value of NAME when
    the environment has it, whatever the rest says (a trimmed or defaulted value is read as the value, close enough to judge the path). Not PWD and OLDPWD (the shell
    sets those, the hook's own are another directory's), and the variables the environment lacks, which stay as written (a ${NAME...} that stays is refused
    in a write and for a key by the callers; OUT is the run's out directory, see out_dir)."""
    def value(m):
        name, rest = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), "")
        if name in ("PWD", "OLDPWD"):
            return m.group(0)
        got = os.environ.get(name)
        if got is None and name == "OUT" and not rest and _OUT[0]:
            got = _OUT[0]
        return m.group(0) if got is None else got
    return re.sub(r"\$(?:\{(\w+)([^{}]*)\}|(\w+))", value, os.path.expanduser(p))


@functools.cache
def real_dir(d):
    return os.path.realpath(d)


@functools.cache                                     # the files do not change while one command is judged
def resolve(here, p):
    """The real path of p (with ~ and environment variables expanded) as seen from the directory here. The directory part is resolved once for all the names
    in it: a name below it that is no link is the directory's real path and the name."""
    q = expand_path(p)
    head, _, base = q.rpartition("/")
    if base not in ("", ".", ".."):
        full = os.path.join(real_dir(os.path.join(here, head) if head else here if not q.startswith("/") else "/"), base)
        if not os.path.islink(full):
            return full
    return os.path.realpath(os.path.join(here, q))


def operands(words, stdin_names=False):
    """The words of a command that are its operands: no option, and no redirection with the file it names (`< r.md`, `0<r.md`, `> f`, `2>&1`, `<<< text`).
    stdin_names: the command is run by xargs, whose operands come from its standard input, so a `< FILE` may be them: only the output redirections are left out."""
    if stdin_names:
        return [t for t in words if not t.startswith("-") and not REDIR.match(t)]
    out, k = [], 0
    while k < len(words):
        t = words[k]
        if BARE_REDIR.match(t):                               # the operator alone: its target is the next word
            k += 2
            continue
        if not t.startswith("-") and not LEADING_REDIR.match(t) and not REDIR.match(t):
            out.append(t)
        k += 1
    return out


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


def script_values_off(rest):
    """rest without the words that -e, -f, --expression and --file hand a sed or perl script (or the file of one): they are no files to change, whatever
    characters the script holds (a glob, a $, a -S)."""
    out, skip = [], False
    for t in rest:
        if skip:
            skip = False
            continue
        skip = t in ("--expression", "--file") or bool(re.match(r"^-[A-Za-z]*[ef]$", t))
        out.append(t)
    return out


def write_targets(toks, i):
    """(what, destination) of everything a segment writes, by its redirections and its program (git included). A destination of "" is a redirection with no
    target left in the segment. Sources that a command removes (mv, rm) are targets too."""
    targets, gitdir = [], None
    for k, t in enumerate(toks):                       # redirections anywhere in the segment
        if not k % 64:
            tick()
        dest = redirect_dest(toks, k)
        if dest is None:
            dest = attached_dest(t)
        if dest is not None and dest != "/dev/null":
            targets.append(("a redirection", dest))
    if i < len(toks):
        prog, rest = os.path.basename(toks[i]), toks[i + 1:]
        args = operands(rest, any(os.path.basename(t) == "xargs" for t in toks[:i]))
        if prog in WRITERS:
            targets += [(prog, a) for a in args]
            if prog == "patch" and not any(cluster_value(rest, k, "d") is not None for k in range(len(rest))):
                targets.append((prog, "."))                                   # patch writes the files the patch names, below where the shell is (or -d DIR)
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
        elif prog in ("awk", "gawk", "mawk") and any(t in ("inplace", "-iinplace", "--include=inplace") for t in rest):    # gawk -i inplace edits its files
            targets += [("awk -i inplace", a) for a in (args if any(t in ("-f", "--file") for t in rest) else args[1:])]
        elif prog in INPLACE and any(re.match(r"^-[A-Za-z]*i", t) or t == "--in-place" or t.startswith("--in-place=") for t in rest):   # -i, -i.bak, -pi, -ni
            scripted = any(t in ("-e", "-f", "--expression", "--file") or re.match(r"^-[A-Za-z]*[ef]$", t) or t.startswith(("--expression=", "--file="))
                           or re.match(r"^-[A-Za-z]*[ef]\S", t) for t in rest)        # a script given by an option: every operand is a file (-es/a/b/ and -ifoo count too: more files, never fewer)
            files = operands(script_values_off(rest), any(os.path.basename(t) == "xargs" for t in toks[:i]))     # sed -i -e SCRIPT FILE: the script is no file
            targets += [(prog + " -i", a) for a in (files if scripted else args[1:])]
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
            opts, k = git_global(rest)
            gitdir = next((v for n, v in reversed(opts) if n == "-C" and v), None)
            trees = [v for n, v in opts if n == "--work-tree" and v] + [t.split("=", 1)[1] for t in toks[:i] if t.startswith("GIT_WORK_TREE=")]
            sub = rest[k] if k < len(rest) else ""
            if sub in GIT_WRITES and not (sub == "tag" and lists_tags(rest[k + 1:])):
                targets.append(("git " + sub, gitdir or "."))
                targets += [("git " + sub, tree) for tree in trees]                # --work-tree DIR and GIT_WORK_TREE=DIR name where the tree is changed, as -C does
            if sub not in GIT_WRITES and git_mutates(sub, rest[k + 1:]):
                targets.append(("git " + sub, gitdir or "."))
                targets += [("git " + sub, tree) for tree in trees]
            if sub == "config":
                targets += git_config_targets(rest[k + 1:])
                if config_written(rest[k + 1:]) != []:                         # a write: GIT_CONFIG=FILE in front of it names the file, as --file does
                    targets += [("git config --file", t.split("=", 1)[1]) for t in toks[:i] if t.startswith("GIT_CONFIG=")]
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


def git_mutates(sub, args):
    """True when `git SUB ARGS` changes the repository though SUB is not one of GIT_WRITES (a subcommand that reads or writes by its arguments): bisect (it checks out
    commits), symbolic-ref with a value or -d, reflog expire|delete, hash-object -w, unpack-objects and lfs (all but the listing ones)."""
    first = next((a for a in args if not a.startswith("-")), "")
    if sub == "bisect":
        return first not in ("log", "visualize", "view", "replay")
    if sub == "symbolic-ref":
        return len([a for a in args if not a.startswith("-")]) > 1 or any(a in ("-d", "--delete") for a in args)
    if sub == "reflog":
        return first in ("expire", "delete") or any(a.startswith("--expire") for a in args)
    if sub == "hash-object":
        return any(a == "--write" or (re.fullmatch(r"-[A-Za-z]+", a) is not None and "w" in a) for a in args)
    if sub == "unpack-objects":
        return True
    if sub == "lfs":
        return first not in ("ls-files", "status", "env", "version", "locks", "logs", "help")
    return False


CONFIG_READS = {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "--get-color", "--get-colorbool", "--list", "-l", "--show-origin", "--show-scope", "--name-only"}   # git config options that only read


def git_config_targets(args):
    """What `git config ARGS` writes outside the repository: the lead's own configuration for --global and --system (~/.gitconfig, which git reads for every
    repository of the lead), and the file --file|-f names. A read (--get, --list ..., or a key alone) writes nothing."""
    if any(a in CONFIG_READS for a in args):
        return []
    names, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a in ("--file", "-f", "--blob", "-t", "--type", "--default"):
            skip = True
        elif not a.startswith("-"):
            names.append(a)
    files = [v for v in (option_value(args, n, ("--file", "-f")) for n in range(len(args))) if v is not None]
    scope = next((a for a in args if a in ("--global", "--system")), None)
    if len(names) < 2 and not any(a in ("--add", "--unset", "--unset-all", "--replace-all", "--edit", "-e", "--rename-section", "--remove-section") for a in args):
        return []                                                  # `git config --global user.name`: a key alone is a read
    return ([("git config " + scope, "~/.gitconfig")] if scope else []) + [("git config --file", f) for f in files]


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


class TextReason(MarshalReason):
    """A refusal that carries its own advice, and the advice about text when the command holds a quote or a heredoc (the plain split may have read text as a command)."""


DEVICE = re.compile(r"^/dev/(?:null|zero|full|tty|stdin|stdout|stderr|fd/\d+)$")           # a device a redirection may name; /dev/shm and the rest are directories
UNKNOWN = re.compile(r"[$`*?\[]")                            # in a word: a variable, a substitution or a glob stands where the guard would read a name
OVERWRITES = {"a redirection", "tee", "cp", "install", "ln", "rsync", "dd", "sort -o", "uniq", "mv", "truncate", "sed -i", "perl -i", "git bundle create"}   # they make or replace the file they name
TOUCHERS = WRITERS | COPIERS | {"dd"}                          # the programs whose every operand is a file they change or take away (a source is moved or removed)
GIT_PLACE = re.compile(r"(?:^|/)(?:\.gitconfig|\.config/git(?:/.*)?|\.git/config|\.git/hooks(?:/.*)?|\.git/modules(?:/.*)?|\.git/worktrees(?:/.*)?|config\.worktree|"
                       r"info/attributes)$")   # what git reads its configuration and its hooks from (a submodule's and a worktree's too)
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
        if "${" in head:
            return OwnReason("%s writes to %s through a ${...} expansion whose value the guard cannot read (the variable is not in its environment, or it is trimmed or defaulted); "
                             "write the path out" % (what, dest))
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


def unknown_dir_refusal(toks, i):
    """The reason a command run in a directory the guard cannot name (after a cd to a word a variable, a substitution or a glob builds, `env -C $d`, a CDPATH) is
    refused, or None: a write to a path that is not absolute could land in the run's record, a skills directory or the pack library, and the command is judged from
    its other directories only by the paths it names in full. The target of a git command (the repository it is run in) is left."""
    for what, dest in write_targets(toks, i):
        if dest and not DEVICE.match(dest) and not dest.startswith(("/", "~", "$", "`")) and not (what.startswith("git ") and dest == "."):
            return OwnReason("%s on %s writes below a directory that a variable, a substitution or a glob built in a cd (or an env -C or a CDPATH), which the guard cannot read, so it cannot tell "
                             "where %s is; write the directory out" % (what, dest, dest))
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
        if run and is_review(run) and not member_space(full, run):
            return "under the read-only class only the report and the manifest in OUT, and the temporary directory (TMP), may be written (%s is not)" % fp
        return None
    if call.kind != "shell":
        return None
    seen, places, runs_git = set(), [], False
    for n, ps, seg, dirs in walk(call.command, cwd):
        toks, i = parsed(seg)
        prog = os.path.basename(toks[i]) if i < len(toks) else ""
        for here in dirs:                                    # a cd that may not happen leaves several: each is judged
            if (seg, here) in seen:                          # the same text from the same directory has been judged
                continue
            seen.add((seg, here))
            if here == UNKNOWN_DIR:
                why = unknown_dir_refusal(toks, i)
                if why:
                    return why
                continue
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
    src_last = None                                          # cp -t DIR SRC: write_targets names SRC too (as it always did); it is read, not written
    if prog in COPIERS and prog != "rsync" and any(cluster_value(toks[i + 1:], n, "t") is not None or toks[i + 1 + n].startswith("--target-directory") for n in range(len(toks) - i - 1)):
        src_last = (operands(toks[i + 1:]) or [None])[-1]
    for what, braced in write_targets(toks, i):
        for dest in brace_expand(braced):                  # echo x > OUT/{a,../clone/b}: each word it stands for
            tick()
            why = unreadable_target(what, dest, here)
            if why:
                return why
            if ro and UNKNOWN.search(expand_path(dest).rpartition("/")[0]) and not DEVICE.match(dest):
                return OwnReason("under the read-only class %s writes through a directory name that a variable, a substitution or a glob builds (%s), which the guard cannot read "
                                 "to tell the clone from OUT; write the path out" % (what, dest))
            full = resolve(here, dest)
            why = control_refusal(full) or (None if what == "git config" and dest == "." else run_dir_refusal(full))     # git config --list in the run directory reads: its "." is where it was run
            if why:
                return why
            run = run_dir(full if os.path.isdir(full) else os.path.dirname(full)) or run_dir(here)
            if CLASS == "read-only" and not run:
                return OwnReason(NO_RUN)
            if what.split()[0] in DESTRUCTIVE:
                why = run_refusal(full, here)
                if why and not (what == "mv" and fits_beside(move_places(toks[i + 1:]), dest, full, here, lambda p: run_refusal(p, here))):
                    return why
            if run and reading(run) and not DEVICE.match(dest) and not member_space(full, run) and braced != src_last:
                return "under the read-only class only OUT and the temporary directory (TMP) are written: nothing in the clone or anywhere else may be changed (%s into %s)" % (what, dest)
    if prog in TOUCHERS or prog == "find":                    # the sources of cp, mv and ln, and every file a command takes away, are the run's record too
        rest = toks[i + 1:]
        files = operands(rest, any(os.path.basename(t) == "xargs" for t in toks[:i])) + [t[3:] for t in rest if t.startswith(("if=", "of="))]
        if prog == "find" and not any(t in FIND_ACTIONS for t in rest):
            files = []
        for a in files[:200]:
            why = unreadable_target(prog + " (operand)", a, here) or control_refusal(resolve(here, a))
            if why:
                return why
            if prog in DESTRUCTIVE | {"find"}:
                why = run_refusal(resolve(here, a), here)
                if why and not (prog == "mv" and fits_beside(move_places(rest), a, resolve(here, a), here, lambda p: run_refusal(p, here))):
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
    roots.update(lead_state_roots(P, home))
    roots.update(saved_runs_roots(P, home))
    roots.update(journal_roots(P, home))
    roots.update(memory_roots(P, home))
    roots.update(lead_roots(home) | lead_files(home))
    lead = lead_files(home)                                   # the skills, the library and the like first: a refusal names the most specific reason
    return sorted(r for r in {os.path.realpath(r) for r in roots} if r not in lead) + sorted(lead)


LEAD_FILES = (".claude/settings.json", ".claude/settings.local.json", ".claude/CLAUDE.md", ".claude.json", ".claude/commands", ".claude/hooks", ".bashrc", ".bash_profile",
              ".bash_login", ".profile", ".zshrc", ".zshenv", ".zprofile", ".ssh/config", ".ssh/authorized_keys")   # the settings and startup files of the lead's own session


def lead_files(home=None):
    """The lead's own session settings (~/.claude/settings.json, CLAUDE.md, commands/, hooks/, ~/.claude.json) and the files its shell and ssh read at start
    (~/.bashrc ... ~/.ssh/config): a hook, a command or a program set there runs in the lead's session (real paths). The skills and agents directories are
    the provider definitions' own (resource_dirs); the rest of ~/.claude (projects, todos ...) is the runtime's working space and stays open."""
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(home, f)) for f in LEAD_FILES}


def lead_roots(home=None):
    """The lead's own git configuration: ~/.gitconfig, ~/.config/git (also below XDG_CONFIG_HOME) and ~/.git. Git reads them for every repository of the lead, and an
    alias, a hook path or a program set there runs in the lead's own commands (real paths, so a link to them is followed)."""
    home = home or os.path.expanduser("~")
    xdg = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    return {os.path.realpath(r) for r in (os.path.join(home, ".gitconfig"), os.path.join(home, ".config", "git"), os.path.join(xdg, "git"), os.path.join(home, ".git"))}


def state_sub(name, P=None, home=None):
    """The directory `name` of the state, in each of the places qargi keeps it: QARGI_STATE, else <root>/state, and the default ~/.qargi/state beside an override
    (real paths, so a link into it is followed)."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(st, name)) for st in (P.state(), os.path.join(P.root(), "state"), os.path.join(home, ".qargi", "state"))}


def render_roots(P=None, home=None):
    """The render/ directory of the state: where the renders of every runtime go (state/render/<project>/<runtime>: skills, tools and members as a runtime loads
    them)."""
    return state_sub("render", P, home)


def providers_state_roots(P=None, home=None):
    """The providers/ directory of the state: the verification records (verified.json) that decide which capabilities of a library runtime count. Written only by
    `provider check` and `provider attest`."""
    return state_sub("providers", P, home)


def feature_roots(P=None, home=None):
    """The features/ directory of the state: the marshal's record of each open feature."""
    return state_sub("features", P, home)


def lead_state_roots(P=None, home=None):
    """The handoff/ and busy/ directories of the state: when the lead's last handoff note was written, and the whole-suite runs in progress. `qargi lead
    compact-check` reads both to say whether a compact is safe, so a member must not write them."""
    return state_sub("handoff", P, home) | state_sub("busy", P, home)


def saved_runs_roots(P=None, home=None):
    """The runs/ directory of the state: the copies `qargi local verify` saves of a passed run (its OUT, its snapshots, its record), which
    `qargi review apply --from-saved` applies after the run directory is lost. A member must not plant or change one."""
    return state_sub("runs", P, home)


def switch_roots(P=None, home=None):
    """The marshal/ directory of the state: the per-project `.enabled` switch files of the shared-refs backend."""
    return state_sub("marshal", P, home)


def memory_roots(P=None, home=None):
    """The memory tiers qargi keeps by default: <root>/memory (project, shared and system) and ~/.qargi/memory. Reading stays allowed; a tier placed elsewhere by
    the project's answers is not guarded."""
    if P is None:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths as P
    home = home or os.path.expanduser("~")
    return {os.path.realpath(os.path.join(r, "memory")) for r in (P.root(), os.path.join(home, ".qargi"))}


JOURNAL = "ref-journal.jsonl"
REGISTRY = "local-runs.jsonl"                                # the lead's registry of local runs: which temporary directory `qargi local clean` removes for each


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
    """The lead's ref journal of the state and its lock, and the registry of local runs and its lock (real paths). Rotated and temporary files next to
    them are found by journal_sibling. Trusted only as far as the state directory is: see the module docstring."""
    return {os.path.join(st, n) for st in state_dirs(P, home) for n in (JOURNAL, JOURNAL + ".lock", REGISTRY, REGISTRY + ".lock")}


def journal_sibling(full):
    """The journal (or registry) root when full is a file next to it named like it (ref-journal.jsonl.1, .tmp, ...), else None."""
    for st in state_dirs():
        for n in (JOURNAL, REGISTRY):
            if os.path.dirname(full) == st and os.path.basename(full).startswith(n):
                return os.path.join(st, n)
    return None


def refusal_text(what, dest, root):
    """The sentence for a refused write: the generic one, or for the render and the marshal's records the reason."""
    if os.path.basename(root).startswith(REGISTRY) and (root in journal_roots() or journal_sibling(root)):
        return MarshalReason("%s on %s would change %s, the lead's registry of local runs (it says which temporary directory `qargi local clean` removes for each run); %s"
                             % (what, dest, root, MARSHAL_NOTE))
    if root in journal_roots() or journal_sibling(root):
        return MarshalReason("%s on %s would change %s, the lead's ref journal of branch moves; %s" % (what, dest, root, MARSHAL_NOTE))
    name = os.path.basename(dest.rstrip("/"))
    if root in feature_roots() and name.startswith(".accepted-"):
        return MarshalReason("%s on %s would change %s, the marshal's acceptance marks (the newest signed record this machine has accepted, "
                             "which a rollback is measured against); %s" % (what, dest, root, MARSHAL_NOTE))
    if root in feature_roots():
        return MarshalReason("%s on %s would change %s, the marshal's record of the open features; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in lead_state_roots():
        return MarshalReason("%s on %s would change %s, where the lead's handoff note and whole-suite runs are recorded (qargi lead compact-check reads them); %s"
                             % (what, dest, root, MARSHAL_NOTE))
    if root in saved_runs_roots():
        return OwnReason("%s on %s would change %s, the lead's saved copies of passed local runs (review apply --from-saved applies them); "
                         "a member writes only its own OUT" % (what, dest, root))
    if root in switch_roots() and name.endswith(".signers"):
        return MarshalReason("%s on %s would change %s, the marshal's allowed signers (the keys whose records are accepted); %s"
                             % (what, dest, root, MARSHAL_NOTE))
    if root in switch_roots():
        return MarshalReason("%s on %s would change %s, the marshal's per-project switch of the shared-refs backend; %s" % (what, dest, root, MARSHAL_NOTE))
    if root in lead_files():
        return OwnReason("%s on %s would change %s, a setting or startup file of the lead's own session (a hook, a command or a program set there runs in the lead's session); "
                         "a member does not change it, propose the change in your report" % (what, dest, root))
    if root in lead_roots():
        return OwnReason("%s on %s would change %s, the lead's own git configuration (git reads it for every repository, so an alias or a hook set there runs in the lead's commands); "
                         "a member does not change it, propose the change in your report" % (what, dest, root))
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


def below_key_dir(full):
    """True when the real path full is a credentials directory with a signing key in it: a search that walks down from it reaches the key (one that starts below it,
    or above it, at the home directory, does not name it)."""
    return any(full == d and has_key_file(d) for d in key_dirs())


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


_BRACE_WORK = [0]


@functools.cache
def brace_expand(word, limit=MAX_BRACE):
    """The words a simple shell brace expression stands for (a{b,c}d -> abd, acd); one level per pass. A word that stands for more than limit words is
    refused (TooManyBraces), and so are braces that together stand for more than MAX_BRACE_WORK: cutting the list would leave the words past it unchecked."""
    if "{" not in word:
        return (word,)
    words, out = [word], []
    while words:
        tick()
        w = words.pop()
        m = re.search(r"\{([^{}]*,[^{}]*)\}", w)
        if not m:
            out.append(w)
        else:
            words += [w[:m.start()] + alt + w[m.end():] for alt in m.group(1).split(",")]
        if len(words) + len(out) > limit:
            raise TooManyBraces()
    _BRACE_WORK[0] += len(out)
    if _BRACE_WORK[0] > MAX_BRACE_WORK:
        raise TooManyBraces()
    return tuple(out)


TRIMMED = re.compile(r"\$\{\w+(?:%%?|##?)[^{}]*\}")       # ${NAME%PATTERN}, ${NAME%%PATTERN}, ${NAME#PATTERN}, ${NAME##PATTERN}: a part of the variable's own value


@functools.cache                                     # the files do not change while one command is judged
def key_named(word, here, recursive):
    """The signing key (or, for a recursive reader, a directory holding it) that one shell word stands for, else None. The word
    is read with ~ and variables expanded, braces and globs expanded, symbolic links followed; `--opt=path`, `-Opath` and a
    `<path` redirection are read as their path too."""
    tick()
    cands = {word, word.lstrip("<"), re.sub(r"^(?:\d+|&)?[<>]+[&|]?", "", word), word.split("=", 1)[-1]}     # 3<key, <key, <>key, <&key
    if word.startswith("-") and not word.startswith("--"):
        cands.add(word[2:])
    for c in cands:
        if not c or c.startswith("-"):
            continue
        for b in brace_expand(expand_path(c)):
            if "${" in b:
                base = os.path.basename(TRIMMED.sub("x", b))      # ${f%%:*}, ${f%/*}, ${f##*/}: the * and the / belong to the pattern, not to the path
                if bool(recursive) or base.startswith(KEY_PREFIX) or re.search(r"[*?\[]", base):
                    return b                                  # ${X:-dir}/marshal_*: a directory the guard cannot read could be the credentials directory
            plain = re.sub(r"/(?:\./)+", "/", re.sub(r"/{2,}", "/", b))        # dir//key and dir/./key are the path dir/key
            if any(d + os.sep + KEY_PREFIX in plain for d in key_dirs()):     # a path inside text, e.g. python -c "open('...')"
                return b
            paths = glob_paths(os.path.join(here, b)) if re.search(r"[*?\[]", b) else []
            for full in [resolve(here, b)] + [os.path.realpath(x) for x in paths]:
                if is_key(full) or (recursive == "tree" and holds_key(full)) or (recursive == "below" and below_key_dir(full)):
                    return b
    return None


def key_refusal_text(prog, word, tool=None):
    return MarshalReason("%s on %s would read the marshal's signing key (credentials/%s*); %s" % (tool or prog or "a redirection", word, KEY_PREFIX, KEY_NOTE))


KEY_SEARCHERS = {"grep", "egrep", "fgrep", "rg", "ag", "find"}   # these walk down from the path they are given, so only the credentials directory itself reaches the key (one above it, the home directory, is a search of everything else)


def operand_positions(words):
    """The indexes in words of the operands (no option, no redirection and the file it names), as operands() takes them."""
    out, k = [], 0
    while k < len(words):
        t = words[k]
        if BARE_REDIR.match(t):
            k += 2
            continue
        if not t.startswith("-") and not LEADING_REDIR.match(t) and not REDIR.match(t):
            out.append(k)
        k += 1
    return out


def key_destinations(prog, toks, i):
    """The indexes in toks of the words that only say where a copy, a move, a link or an extraction PUTS its files (the last operand, -t DIR, tar -C DIR when it extracts):
    a directory above the credentials directory (the home directory) is a place to write to there, and reads nothing."""
    rest = toks[i + 1:]
    out = set()
    if prog in COPIERS or prog in KEY_LINKERS or prog == "cp":
        targeted = False
        for k, t in enumerate(rest):
            m = re.match(r"^-[A-Za-z0-9]*?t(.*)$", t) if prog != "rsync" and t.startswith("-") and not t.startswith("--") else None
            if m or t == "--target-directory" or t.startswith("--target-directory="):
                out.add(i + 1 + k if (m and m.group(1)) or "=" in t else i + 2 + k)       # -tDIR and --target-directory=DIR are one word, -t DIR and -rt DIR two
                targeted = True
        pos = operand_positions(rest)
        if pos and not targeted:
            out.add(i + 1 + pos[-1])
    elif prog in TARS and tar_extracts(rest):
        for k, t in enumerate(rest):
            if t in ("-C", "--directory"):
                out.add(i + 2 + k)
            elif t.startswith("--directory=") or (t.startswith("-C") and len(t) > 2 and not t.startswith("--")):
                out.add(i + 1 + k)
    return out


def key_read(toks, i, here):
    """The reason a Bash segment reads the lead's signing key, or None: any word of it that names the key, whatever the program, the words before the program
    (`<key cat`, `exec 3<key`) and a segment with no program at all. ls, stat and test only look at a file: their own operands are not read, a redirection
    in front of them is. A recursive reader (cp, rsync, tar, zip ...) also reads a directory that holds the key, but not the one it only writes into
    (`cp src/a.go ~/`); grep and find read it only when the path they walk down from is the credentials directory."""
    prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
    mode = False
    if prog in KEY_SEARCHERS:
        mode = "below" if prog != "find" or any(t in FIND_ACTIONS for t in rest) else False
    elif prog in KEY_RECURSIVE or prog in KEY_LINKERS or (prog == "cp" and any(LINK_FLAGS.match(t) or t in ("--symbolic-link", "--link") for t in rest)):
        mode = "tree"
    skip = key_destinations(prog, toks, i) if mode == "tree" else set()
    for k, t in enumerate(toks[:i] if prog in KEY_METADATA else toks):
        tick()
        if k in skip:
            continue
        named = key_named(t, here, mode)
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
        return key_refusal_text(call.name, fp) if full and (is_key(full) or (call.kind == "search" and below_key_dir(full))) else None
    if call.kind != "shell":
        return None
    return bash_skill_refusal(mask_data(call.command), call.cwd, 0) or separator_path_refusal(call.command, call.cwd)


SEPARATOR_WORD = re.compile(r"[;|&\n]")
WORD_QUOTING = re.compile(r"[\"'\\]")


def separator_path_refusal(command, here):
    """A backstop of the plain split, which cuts a word at a ; | & or newline even inside quotes and so never judges it whole as a path: a word that,
    after quote removal, still holds one of them and resolves into a protected location, or names the signing key, is refused (`echo x > "s;/x/SKILL.md"`
    or `tee 's;/x/SKILL.md'` with a link `s;` to a skills directory). A read of such a name is refused too: which words a command writes is not read here.
    The directory is the one of the call (a cd in the line is not followed), and a word longer than a path can be is no path."""
    if not WORD_QUOTING.search(command) or not SEPARATOR_WORD.search(command):
        return None
    try:
        lex = shlex.shlex(command, posix=True, punctuation_chars=True)   # the redirection operators are words of their own: `x>"a;b"` is x, >, a;b
        lex.whitespace_split, lex.commenters = True, ""
        words = set(lex)
    except ValueError:                                       # an open quote (an apostrophe in a heredoc body): the quoted strings alone
        words = {a or b for a, b in re.findall(r"'([^']*)'|\"([^\"]*)\"", command)}
    for w in words:
        tick()
        if len(w) > 4096 or not SEPARATOR_WORD.search(w):
            continue
        full = resolve(here, w)
        root = protected(full)
        if root:
            return refusal_text("a command", w, root)
        if is_key(full) or below_key_dir(full):
            return key_refusal_text("", w, "a command")
    return None


def names_lead(t, name="QARGI_LEAD"):
    """True when a word assigns, exports or unsets NAME, QARGI_LEAD by default (QARGI_LEAD=x, QARGI_LEAD+=x, -u QARGI_LEAD, -uQARGI_LEAD, --unset=QARGI_LEAD, bare name)."""
    lhs, _, rhs = t.partition("=")
    return lhs.rstrip("+") == name or (lhs in ("--unset", "-u") and rhs == name) or t == "-u" + name


def lead_refusal(toks, i):
    """The reason a segment (its words toks, the program at i) sets or unsets QARGI_LEAD, or None. The names it sets are env_names()'s, as for QARGI_NESTED
    (VAR=x in front, export|declare|... NAME, printf -v NAME and -vNAME, read|mapfile NAME); names_lead() adds the words that unset it (unset NAME, env -u
    NAME) and the operands of the builtins."""
    prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
    if "QARGI_LEAD" in env_names(toks, i) or any(names_lead(t) for t in toks[:i + 1]) or (prog in LEAD_BUILTINS and any(names_lead(t) for t in rest)):
        return MarshalReason("setting or unsetting QARGI_LEAD changes who the lead is and is not available to an agent; " + MARSHAL_NOTE)
    if MEMBER_MARK in env_names(toks, i) or any(names_lead(t, MEMBER_MARK) for t in toks[:i + 1]) or (prog in LEAD_BUILTINS and any(names_lead(t, MEMBER_MARK) for t in rest)):
        return MarshalReason("setting or unsetting %s removes the mark that tells the marshal a member is running, so that its commands renew nothing, and is not available to an agent; %s"
                             % (MEMBER_MARK, MARSHAL_NOTE))
    return None


def bash_skill_refusal(command, here, depth):
    joined = ansi_c(command.replace("\\\n", ""))        # a line continuation joins the lines (segments() does the same, and reads an escaped backslash right)
    if word_then_subst(HANDOFF_SUBST, joined):
        return MarshalReason("qargi marshal handoff with a command substitution in its arguments could be given --write, which writes a file and is not available to an agent; %s"
                             % MARSHAL_NOTE)
    if word_then_subst(PROJECT_SET_SUBST, joined):
        return "qargi project set with a command substitution in its arguments takes a path the guard cannot read, which could be a models answer, and is not available to an agent"
    if word_then_subst(AUDIT_SUBST, joined):
        return "qargi skill accept (packs_audit.py with a command substitution in its arguments could be `store`) changes a skill and is not available to an agent"
    seen = set()                                         # the (text, directory) pairs judged
    for n, ps, seg, dirs in walk(command, here):
        toks, i = parsed(seg)
        if any(t.startswith("QARGI_NESTED=") for t in toks[:i]):
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        prog, rest = (os.path.basename(toks[i]), toks[i + 1:]) if i < len(toks) else ("", [])
        why = lead_refusal(toks, i)
        if why:
            return why
        if "QARGI_NESTED" in env_names(toks, i):             # export|declare|typeset|readonly|local NAME, printf -v NAME, read NAME
            return "setting QARGI_NESTED skips a plan-token check and is not available to an agent"
        for at in dirs:                                      # a cd that may not happen leaves several directories: each is judged
            if (seg, at) in seen:                            # judged already
                continue
            seen.add((seg, at))
            if at == UNKNOWN_DIR:
                why = unknown_dir_refusal(toks, i)
                if why:
                    return why
                continue
            if i < len(toks) and prog not in ("cd", "pushd", "popd"):
                why = skill_verb(prog, rest, via_xargs=any(os.path.basename(t) == "xargs" for t in toks[:i]), here=at, exe=toks[i])
                if why:
                    return why
                inner = shell_string(prog, rest) if depth < 3 else None
                if inner is not None:
                    inner += " ; " + " ; ".join(p.text for p in ps[n + 1:n + 201]).replace('"', " ").replace("'", " ")      # a `;` inside the quoted string split it: read the pieces that follow as part of it
                    why = bash_skill_refusal(inner, [at], depth + 1)
                    if why:
                        return why
                if prog in SHELLS or prog in SOURCES:            # its program on its standard input, or in a file this line writes: read again what the line shows of it
                    fed, unread = program_fed(ps, n, at)
                    if unread or (fed and depth >= 3):
                        return fed_refusal(prog, unread or "a program nested more than three shells deep")
                    for text in fed:
                        why = bash_skill_refusal(as_program(text), [at], depth + 1)
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
    seg = ansi_c(seg)
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
            expands, xargs = any(e for _, e in words), False
            for k, w in enumerate(names):
                tick()
                if os.path.basename(w) in ("project", "project.sh"):
                    rest = []                                # the first three words after it that are no option
                    for j in range(k + 1, len(names)):
                        if not names[j].startswith("-"):
                            rest.append((names[j], words[j][1]))
                            if len(rest) == 3:
                                break
                    named = [n for n, _ in rest if n in PROJECT_VERBS]
                    if (named or (rest and rest[0][1])) and (expands or xargs):
                        return ("qargi project %s with a variable, a substitution, a brace, a glob or xargs in the command takes words the guard cannot read, and project set of a models answer, "
                                "project init and project link are not available to an agent" % (named[0] if named else "(a verb the shell builds)"))
                xargs = xargs or os.path.basename(w) == "xargs"
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
    return None if text is None else as_program(text)


def as_program(text):
    """A program text a shell is handed, made ready to be read again as shell_string reads one (its quotes dropped, `\\$` and `\\`` as the expansions)."""
    return text.replace('"', "").replace("'", "").replace("\\$", "$").replace("\\`", "`")


# --- a shell that reads its program from its standard input or from a file the line writes (sh -s, bash <<< TEXT, echo TEXT | sh, . /dev/stdin)

SOURCES = {"source", "."}                                    # run a file in the shell itself, as sh FILE does in a new one
STDIN_NAMES = {"-", "/dev/stdin", "/dev/fd/0", "/proc/self/fd/0"}   # the names of the standard input
SHELL_VALUE_OPTS = re.compile(r"^(?:[-+][A-Za-z]*[oO]|--rcfile|--init-file)$")   # shell options that take the next word (-o pipefail, -euo pipefail, -O extglob, --rcfile F)
SHELL_STDIN_OPT = re.compile(r"^-[A-Za-z]*s[A-Za-z]*$")      # -s: the program is read from the standard input, the words are its arguments
STDIN_REDIR = re.compile(r"^0?(<<<|<<-?|<>|<&|<)(.*)$", re.S)   # a redirection of the standard input: here-string, heredoc, file, descriptor
XARGS_REPLACE = re.compile(r"^(?:-I|-i|--replace)")          # xargs puts its input into the words of the command (sh -c '{}')
PRINTERS = {"echo", "printf"}                                # print the words they are given: the line shows what they write
PASSERS = {"cat", "tee"}                                     # hand their standard input on (cat with no file, tee always)
PRINTF_CONV = re.compile(r"%(?:%|[-+ 0#']*(\*|\d+)?(?:\.(\*|\d*))?([a-zA-Z]))")
FED_NOTE = ("write the script to a file with your file tool and run it with `bash FILE` (a heredoc on the command line is read too)")


def shell_source(prog, rest, pre):
    """Where a shell (or source and .) takes its program from: "string" (sh -c: shell_string reads it), ("file", NAME), "stdin" (sh -s, sh -, no file, a name of
    the standard input, or the words xargs brings from its own), or None when prog is no shell. pre: the words before the program (xargs among them)."""
    if prog not in SHELLS and prog not in SOURCES:
        return None
    x = next((k for k, t in enumerate(pre) if os.path.basename(t) == "xargs"), None)
    replaces = x is not None and any(XARGS_REPLACE.match(t) for t in pre[x + 1:])
    words, k = [], 0
    while k < len(rest):                                     # the words without the redirections; a process substitution is a word (the name of a file)
        t = rest[k]
        if t.startswith(("<(", ">(")) or not LEADING_REDIR.match(t):
            words.append(t)
        elif BARE_REDIR.match(t):
            k += 1
        k += 1
    k = 0
    if prog in SHELLS:
        while k < len(words):
            t = words[k]
            if SHELL_C.match(t):
                return "stdin" if x is not None and (k + 1 >= len(words) or replaces) else "string"
            if SHELL_STDIN_OPT.match(t):
                return "stdin"
            if t in ("-", "--"):
                k += 1
                break
            if not t.startswith(("-", "+")) or len(t) < 2:
                break
            k += 2 if SHELL_VALUE_OPTS.match(t) else 1
    elif words[:1] == ["--"]:
        k = 1
    if k < len(words):
        return "stdin" if words[k] in STDIN_NAMES else ("file", words[k])
    return "stdin" if prog in SHELLS or x is not None else None   # no file: the standard input (xargs brings the name of one from it)


def stdin_redirect(toks):
    """The last redirection of the standard input among the words of a command, as (operator, word): ("<<<", TEXT), ("<<", DELIM), ("<", FILE), ("<&", N), or None."""
    last, k = None, 0
    while k < len(toks):
        t = toks[k]
        m = STDIN_REDIR.match(t)
        if m and not t.startswith("<("):
            op, val = m.group(1), m.group(2)
            if not val and k + 1 < len(toks):
                val, k = toks[k + 1], k + 1
            last = (op, val)
        elif BARE_REDIR.match(t):
            k += 1
        k += 1
    return last


def here_string_expands(seg):
    """True when the outer shell expands the word of the last here-string of a segment (a variable, a substitution or a glob in it, outside single quotes)."""
    words, out = lex(seg), False
    for k, (w, e) in enumerate(words):
        m = re.match(r"^0?<<<", w)
        if m:
            out = e if w[m.end():] else (k + 1 < len(words) and words[k + 1][1])
    return out


def printf_text(fmt, args):
    """What printf FORMAT ARGS prints, close enough to read a command in it: the escapes decoded, a conversion given its argument as it is (%b decoded, %c its
    first character, no width padding), and the format used again while arguments are left."""
    fmt, args, out = escapes_decoded(fmt), list(args), []
    while True:
        used, last = False, 0
        for m in PRINTF_CONV.finditer(fmt):
            tick()
            out.append(fmt[last:m.start()])
            last = m.end()
            if m.group() == "%%":
                out.append("%")
                continue
            for star in (m.group(1), m.group(2)):
                if star == "*" and args:
                    args.pop(0)
            a, used = (args.pop(0) if args else ""), True
            out.append(escapes_decoded(a) if m.group(3) == "b" else a[:1] if m.group(3) == "c" else a)
        out.append(fmt[last:])
        if not args or not used:
            return "".join(out)


def printed(prog, words):
    """The texts echo or printf prints for its words (the redirections left out): echo's words as they are and with their escapes decoded (echo -e, and sh's
    echo, decode them), printf's format filled in; nothing for printf -v, which assigns."""
    if prog == "echo":
        k = 0
        while k < len(words) and re.fullmatch(r"-[neE]+", words[k]):
            k += 1
        raw = " ".join(words[k:])
        return list(dict.fromkeys([raw, escapes_decoded(raw)]))
    if words[:1] == ["--"]:
        words = words[1:]
    if not words or words[0].startswith("-v"):
        return []
    return [printf_text(words[0], words[1:])]


def plain_words(rest):
    """The words of a command without its redirections and the words they name."""
    out, k = [], 0
    while k < len(rest):
        t = rest[k]
        if BARE_REDIR.match(t):
            k += 1
        elif not LEADING_REDIR.match(t) and not REDIR.match(t):
            out.append(t)
        k += 1
    return out


def input_of(ps, n, depth=0):
    """What the command ps[n] (a piece of a cut) reads on its standard input: (texts, why). texts: the text the line shows for it (a here-string, an echo or a
    printf piped in, through cat and tee); why: what gives it when the guard cannot read it (another program, a file, a descriptor), else None. A heredoc
    gives nothing to read again, since the plain split reads its body as commands, and a command with no redirection and no pipe reads the call's own input."""
    seg = ps[n].text
    r = stdin_redirect(parsed(seg)[0])
    if r:
        op, val = r
        if op == "<<<":
            return ([], "a here-string that a variable, a substitution or a glob builds") if here_string_expands(seg) else ([val], None)
        if op in ("<<", "<<-") or (op == "<" and val == "/dev/null") or (op == "<&" and val == "-"):
            return [], None
        if not ((op == "<" and val in STDIN_NAMES - {"-"}) or (op == "<&" and val == "0")):
            if not val or val.startswith(("<(", "(")):
                return [], "a process substitution"           # `bash < <(curl x)`: the cut that takes the substitution out leaves the < with no word
            return [], ("descriptor %s" % val) if op == "<&" else ("the file %s" % val)
    if ps[n].piped and n > 0:
        return output_of(ps, n - 1, depth)
    return [], None


def output_of(ps, m, depth=0):
    """What the command ps[m] writes to its standard output, as input_of says it: the text of echo and printf (unless the shell builds a word of it), what cat
    with no file and tee hand on, and for any other program its name as the reason."""
    seg = ps[m].text
    toks, i = parsed(seg)
    if i >= len(toks):
        return [], "a command the guard cannot read"
    prog, rest = os.path.basename(toks[i]), toks[i + 1:]
    if prog in PRINTERS:
        if any(e for _, e in lex(seg)):
            return [], "%s of a word that a variable, a substitution or a glob builds" % prog
        return printed(prog, plain_words(rest)), None
    if prog in PASSERS and depth < 8:
        if prog == "cat" and [t for t in operands(rest) if t != "-"]:
            return [], "the files cat reads"
        return input_of(ps, m, depth + 1)
    return [], "the output of %s" % prog


@functools.lru_cache(maxsize=64)
def pass_writes(ps, here):
    """{real path: (index, what)} of every file the pieces of one cut write, the first writer of each (write_targets), seen from the directory here."""
    out = {}
    for m, p in enumerate(ps):
        tick()
        toks, i = parsed(p.text)
        for what, dest in write_targets(toks, i):
            if dest:
                out.setdefault(resolve(here, dest), (m, what))
    return out


def program_fed(ps, n, here):
    """What the shell ps[n] runs when that is not a -c string (shell_string) or a file that was there before the command: (texts, why), as input_of says it.
    Its standard input (sh -s, sh with no file, a name of the standard input, the words of xargs), or a file a command of the same line writes: what
    an echo or printf writes there is read, a heredoc is read already, and any other writer (cp, curl, a download, a copy) is why."""
    toks, i = parsed(ps[n].text)
    if i >= len(toks):
        return [], None
    src = shell_source(os.path.basename(toks[i]), toks[i + 1:], toks[:i])
    if src == "stdin":
        return input_of(ps, n)
    if not isinstance(src, tuple):
        return [], None
    name = src[1]
    if name.startswith(("<(", ">(")):
        return [], "a process substitution"
    w = pass_writes(ps, here).get(resolve(here, name))
    if w is None:
        return [], None
    m, what = w
    if what == "a redirection":
        return output_of(ps, m)
    if what == "tee":
        return input_of(ps, m)
    return [], "%s, which writes %s in the same command" % (what, name)


def fed_refusal(prog, why):
    return TextReason("%s takes its program from %s, which the guard cannot read, so it is not available to an agent; %s" % (prog, why, FED_NOTE))


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
    # a ) with no ( in a word closes a substitution or group whose start the plain split cut off (`printf -v x 'b[%s(true; qargi upgrade)]' $`
    # runs `qargi upgrade` in an arithmetic subscript): the command ends there, so the verb is read without it
    words = [t.split(")")[0] if ")" in t and "(" not in t else t for t in rest if not t.startswith("-")]
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
    if name == "env.py":                                 # qargi env: show reads; plan and apply are refused below
        words = ["env"] + words
    if name == "env_apply.py":                           # the library of env plan and apply: any use of it is the verb
        words = ["env", "apply"]
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
    if name == "branch.sh":
        words = ["branch"] + words
    if name in ("changelog.sh", "changelog_numbers.py"):   # the script of the verb and its library: any use is the verb
        words = ["changelog"] + words
    if name == "upstream.sh":
        words = ["upstream"] + words
    if name == "ref.sh":
        words = ["ref"] + words
    if name == "release.sh":
        words = ["release"] + words
    if name == "release_sign.py":                        # the record of a signature and the checks of release sign: any use of the script is the verb
        words = ["release", "sign"]
    if name == "packs_link.py":                          # plan and apply both: any use of the script is the verb (the shell makes its inputs)
        words = ["packs", "unlink" if "unlink" in words[:2] else "link"]
    if name == "project_link.py":                        # plan, apply and members-dir alike: any use of the script is the verb (the shell checks the plan token)
        words = ["project", "unlink" if "unlink" in words[:2] else "link"]
    if name == "local_run.py":                           # any use of the script is `local run`
        words = ["local", "run"]
    if name == "local.sh":
        words = ["local"] + words
    if name == "agent.sh":
        words = ["agent"] + words
    if name == "team.sh":
        words = ["team"] + words
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
    if area == "ref":
        return OwnReason("qargi ref %s writes the lead's ref journal, which local verify trusts (record --rewrite also moves a branch of the lead's repository), and is the lead's to run; "
                         "report in your task output a branch you think should be rewritten or noted" % (verb or "(no verb)"))
    if area == "branch":
        return OwnReason("qargi branch %s deletes merged branches and the worktrees qargi made (with --remote, branches on origin with the lead's credentials) and is the lead's "
                         "to run, from a plan and a token; report in your task output which branches are merged" % (verb or "(no verb)"))
    if area == "changelog":
        # renumber writes the changelog of a work tree and only --check reads; a --check that is the value of --project is no flag, and a word a variable
        # or a substitution builds could be anything. Help alone reads.
        check = any(t == "--check" and (i == 0 or rest[i - 1] != "--project") for i, t in enumerate(rest))
        if not ((verb == "renumber" and check and not via_xargs and not any("$" in t or "`" in t for t in rest))
                or (verb == "" and any(t in ("-h", "--help") for t in rest))):
            return OwnReason("qargi changelog %s rewrites the changelog of a work tree and is the lead's to run; only qargi changelog renumber --check (it writes nothing) is available to an agent; "
                             "report the duplicate item numbers in your task output" % (verb or "(no verb)"))
    if area == "upstream" and verb not in UPSTREAM_OPEN:
        return OwnReason("qargi upstream %s %s and is the lead's to run (qargi upstream review only reads the last fetch and is allowed); "
                         "report in your task output that the upstream line needs looking at"
                         % (verb or "(no verb)", "fetches into the lead's repository, which changes the remote-tracking refs that qargi local verify compares" if verb == "status"
                            else "fast-forwards the branch that carries the upstream line (and journals the move), from a plan and a token,"))
    if (name == "qargi" and builds_word(area)) or (area in BUILT_VERB_AREAS and builds_word(verb)):
        return "qargi %s %s: a verb that a variable or a substitution builds (it could be any of the verbs that change a skill or the marshal) is not available to an agent" % (area, verb)
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
        if path in EXECUTED_ANSWERS or path.startswith(tuple(a + "." for a in EXECUTED_ANSWERS)):
            return "qargi project set of %s changes a command or an environment the lead later runs, the remote it fetches from or the site it builds (the release answers, test_command, env, upstream, the site answers qargi release site builds from) and is not available to an agent: propose the value in your report" % path
        if path == "packs" or path.startswith("packs."):
            return "qargi project set of %s opts the project out of the packs render check (packs.none) and is not available to an agent: propose the value in your report" % path
        if ROLE_TOOLS_PATH.fullmatch(path):
            return "qargi project set of %s changes the tools the lead later installs and checks out (roles.<role>.tools: go install, a downloaded binary, a submodule) and is not available to an agent: propose the entry in your report" % path
    if area == "provider" and verb == "accept":
        return "qargi provider accept records that you accept a provider with no read-only barrier and is not available to an agent"
    if area == "provider" and verb == "check":
        return "qargi provider check records what it verified of a library pack (and may run the pack's code) and is not available to an agent"
    if area == "provider" and verb == "adapter-run":
        return "qargi provider adapter-run runs the adapter of a runtime, and with --check makes a private copy of a library adapter, and is not available to an agent"
    if area == "provider" and verb not in PROVIDER_READ:
        return "qargi provider %s changes the provider definitions and is not available to an agent" % verb
    if area == "release" and any(w == "site" for w in words[1:4]):
        return "qargi release site commits the built documentation site on the lead's site branch and is not available to an agent; report that the site of the release needs building"
    if area == "release" and any(w == "sign" for w in words[1:4]):
        return "qargi release sign signs the release files with the lead's key, whose passphrase only the person types, and is not available to an agent; report that the tag needs signing"
    if area == "release" and any(w == "assets" for w in words[1:4]):
        return "qargi release assets runs the project's release.assets_command, which is project code, with the lead's rights, and is not available to an agent; report that the release files need building"
    if area == "release" and any(w == "fix" for w in words[1:4]):
        return "qargi release fix makes a worktree on the release branch and can push it with the lead's credentials, and is not available to an agent; report the fix the release branch needs"
    # qargi env: show only reads files, so a member may run it. plan runs the project's dry-run command (make -n still runs $(shell ...) and + lines) and
    # apply runs its bootstrap: both run project code, with the lead's rights and terminal, and are the lead's. A verb held in a variable could be either
    if area == "env" and (verb in ENV_LEAD or builds_word(verb)):
        return ("qargi env %s runs the project's dry-run or bootstrap command, which is project code, with the lead's rights, and is not available to an agent "
                "(qargi env show only reads); report what you need in your task output" % (verb if verb in ENV_LEAD else "plan|apply"))
    if area == "release" and any(w == "publish" or "$" in w or "`" in w for w in words[1:4]):   # a verb held in a variable could be publish
        return "qargi release publish creates a GitHub release and is not available to an agent; report that the tag needs publishing"
    if area == "feature" and verb == "park":
        return OwnReason("qargi feature park resets the parking branch to develop and checks it out in the main checkout (and journals the move), which is the lead's to do; "
                         "report in your task output that the main checkout needs parking")
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
    if (area, verb) in LEAD_VERBS or area == "task":
        return ("qargi %s%s is the lead's (it prepares, verifies or removes runs and agents, or dispatches work, with the lead's credentials and its own record) and is not "
                "available to an agent; report what you need in your task output" % (area, " " + verb if verb else ""))
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
    args = operands(rest, any(os.path.basename(t) == "xargs" for t in toks[:i]))
    cands = list(write_targets(toks, i))
    if prog in SCRIPTS or (prog in SHELLS or re.match(r"^python[0-9.]*$", prog)) and args and os.path.basename(args[0]) in SCRIPTS:
        words = args if prog in SCRIPTS else args[1:]
        if words[:2] == ["packs", "render"]:                 # render writes its output directory: judge every operand
            cands += [("qargi packs render", c) for t in words[2:] for c in {t, t.split("=", 1)[-1]}]
    if prog == "find" and any(t in FIND_ACTIONS for t in rest):
        removes = "-delete" in rest or any(os.path.basename(t) in DESTRUCTIVE for t in rest)        # find -delete and -exec rm walk the tree below the path and remove it
        cands += [("find -delete" if removes else "find", t) for t in rest if not t.startswith("-") and t not in ("(", "!")][:8]
    if prog == "tar":
        cands += [(prog, a) for a in tar_targets(rest)]
    elif prog in EXTRACTORS:
        for t in rest:
            cands += [(prog, c) for c in {t, t.split("=", 1)[-1], t[2:] if t.startswith("-") and not t.startswith("--") else t}]
    if prog == "ln":                                         # ln -s PROT DST; echo x > DST/x: the link is a name the guard has not seen when the write is judged
        links = [a for a in (args if any(t in ("-t", "--target-directory") or t.startswith("--target-directory=") for t in rest) else args[:-1])]
        beside = os.path.dirname(resolve(here, args[-1])) if args else here
        for a in links:
            tick()
            for one in brace_expand(a):
                heres = [here] + ([beside] if not one.startswith(("/", "~")) else [])
                root = next((r for r in (protected(resolve(h, one), True) for h in heres) if r), None)
                if root and root not in key_dirs():              # a link to the credentials directory is the signing key's own refusal (key_read), with its own reason
                    return OwnReason("ln of %s makes a link to %s (or a directory that holds it), a protected location, under a name the guard cannot follow in the same command line; "
                                     "link to something else" % (a, root))
    for what, dest in cands:
        tick()
        if not dest or dest.startswith("-") and dest != "-":
            continue
        for one in brace_expand(dest):                       # cp a DIR/{x,packs}/: each word it stands for
            why = glob_root(what, one, here)
            if why:
                return why
            full = resolve(here, one)
            if what == "git init" and full == real_dir(os.path.expanduser("~")):
                return OwnReason("git init in the home directory makes it a repository whose .git/config and hooks the lead's own commands would read; a member does not do it")
            if what == "git config --file" and not in_clone(full):
                return OwnReason("git config --file %s writes a git configuration file outside the clone (a path in GIT_CONFIG_GLOBAL or an include can make git read it); "
                                 "a member changes the configuration of its clone only" % dest)
            root = protected(full, what.split()[0] in DESTRUCTIVE or what == "find -delete")
            if root and what == "mv" and protected(full) is None and fits_beside(move_places(rest), one, full, here, lambda p: protected(p, True)):
                continue                                     # only a directory above the protected location, and what is moved into it neither is, holds nor meets one
            if root:
                return refusal_text(what, dest, root)
    return None


def move_places(rest):
    """(directories, sources) of an mv command: the words of -t DIR, --target-directory=DIR (the sources are then every other operand), else the last operand
    (the sources are the rest); ([], []) for -T, which makes the source the destination itself."""
    dirs, drop = [], set()
    if any(t == "--no-target-directory" or re.match(r"^-[A-Za-z]*T", t) for t in rest):
        return [], []                                            # -T renames the source to DIR itself: nothing is "moved into" it
    for k, t in enumerate(rest):
        v = option_value(rest, k, ("--target-directory", "-t"))
        v = cluster_value(rest, k, "t") if v is None else v
        if v is not None:
            dirs.append(v)
            m = re.match(r"^-[A-Za-z0-9]*?t(.*)$", t)
            if k + 1 < len(rest) and (t == "--target-directory" or m and not m.group(1)):
                drop.add(k + 1)                                  # the value is the next word, not an operand to move
    args = operands([t for k, t in enumerate(rest) if k not in drop])
    return (dirs, args) if dirs else (args[-1:], args[:-1])


def fits_beside(moves, one, full, here, taken):
    """True when the word `one` (the real path full), which is above a place the guard keeps (a protected location, the run directory), is only the directory an
    mv moves things into: it is a directory and no source is, holds or takes the place of that place (taken(path) says so), nor has a name the guard cannot
    read (it could be the child). Moving a file into /tmp does not change /tmp/x/conf/credentials; moving a directory over it, or a file named like it, does."""
    dirs, sources = moves
    if not sources or not os.path.isdir(full) or not any(one in brace_expand(d) for d in dirs):
        return False
    for s in sources:
        name = os.path.basename(s.rstrip("/"))
        if name in ("", ".", "..") or re.search(r"[$`*?\[{~\\]", name) or taken(resolve(here, s)) or taken(os.path.join(full, name)):
            return False
    return True


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
    "tool_names": {"shell": ["Bash"], "write": ["Edit", "Write", "NotebookEdit"], "read": ["Read"], "search": ["Grep"]},
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

def clear_caches():
    """Forget what was read from the files and the environment: a call is judged from one reading of them (a hook is one call; a test judges many)."""
    _BRACE_WORK[0] = 0
    for cache in (_RESOURCE_DIRS, _ROOTS, _KEY_DIRS, _STATE):          # read from the library, the environment and the state: a judge that outlives one call must not keep them
        cache.clear()
    for f in (real_dir, resolve, run_like, in_a_clone, run_dir, protected, key_named, ability_of, run_class, brace_expand, run_tmps, pass_writes):
        f.cache_clear()


def judge(call):
    """The refusal (a sentence for the member, ending in what to do instead) a Call earns, or None. The neutral core."""
    if call.kind == "shell" and "\0" in (call.command or ""):
        return "qargi guard: a NUL byte in a command cuts it short for the shell and hides the rest from this check, so it is not available to an agent. Write the text without it."
    if call.kind == "shell" and len(call.command or "") > MAX_COMMAND:
        return ("qargi guard: a command of more than %d characters cannot be checked in the time the hook has, so it is not available to an agent. "
                "Write the text to a file with the Write tool, or run it in parts." % MAX_COMMAND)
    clear_caches()
    _DEADLINE[0] = _CLOCK[0]() + BUDGET
    try:
        _OUT[0] = out_dir(call)
        return decide_call(call)
    except TooNested:
        return ("qargi guard: substitutions nested more than %d deep cannot be checked in the time the hook has, so the command is not available to an agent. "
                "Write it in parts." % MAX_NESTED)
    except TooBroad:
        return ("qargi guard: a glob in this command names too many directories to check (more than %d entries to read), so it is not available to an agent. "
                "Write a narrower path." % GLOB_ENTRIES)
    except TooManyBraces:
        return ("qargi guard: a brace expression in this command stands for more than %d words (or the braces of the command for more than %d), which cannot be checked one by one "
                "in the time the hook has, so it is not available to an agent. Write the paths out or run it in parts." % (MAX_BRACE, MAX_BRACE_WORK))
    except TooManyDirs:
        return ("qargi guard: this command changes directory in more than %d ways the guard cannot tell apart (a cd inside ( ), a substitution, a condition or a pipe may "
                "or may not change where the next command runs), so it is not available to an agent. Write it in parts." % MAX_DIRS)
    except TooSlow:
        return ("qargi guard: checking this command took longer than %d seconds, so it is not available to an agent. "
                "Run it in smaller parts." % BUDGET)
    finally:
        _DEADLINE[0] = _OUT[0] = None


QUOTED = re.compile(r"[\"']|<<")
TEXT_HINT = (" The guard cuts a command at every ; && || | and newline, inside quotes and heredocs too (not when every command of the line is echo, cat, tee, grep "
             "or git commit|log|status|diff|show|add, with no comment, backslash or substitution): if the verb is only text (a commit message, a note), "
             "write the text to a file with your file tool and commit with git commit -F FILE.")


def decide_call(call):
    hint = TEXT_HINT if call.kind == "shell" and QUOTED.search(call.command or "") else ""
    why = blocked(call.command) if call.kind == "shell" else None
    if why:
        return "qargi guard: %s. Agents never push; return patches instead.%s" % (why, hint)
    why = skill_refusal(call)
    if isinstance(why, MarshalReason):
        return "qargi guard: %s.%s" % (why, hint if type(why) in (MarshalReason, TextReason) else "")
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
