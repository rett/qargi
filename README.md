# qargi

**A gathering place for agent work: dispatch, review, remember.**

*Qargi* is the Iñupiaq word for the traditional community house, where a village
gathered to make and mend its tools, decide together and hand knowledge on. Here the
work of agents gathers in the same way: tasks go out, patches come back for review,
and what was learned is kept in memory.

Qargi is a set of Claude Code skills and a CLI that dispatch one-off, task-scoped
development tasks to sandboxed agents and take the work back as reviewable patches. An agent
works on one task in its own clone and never pushes; the dispatching session
verifies the result and applies it.

Two kinds of agent do the work:

- **local**: a **member**, a Claude Code subagent you name, working in a scratch clone.
- **cloud**: a Claude Managed Agents deployment of one role, registered as an instance and
  driven through the `ant` CLI.

A **lead** coordinates members on one task (a team): this session, a cloud lead or a lead
started in the console.

Local is the default. Cloud is used only when the user asks for it in that
request.

## Naming convention

Every name follows from the project, so resources are identifiable at a glance.

| Thing | Name | Example |
|---|---|---|
| project | one lower-case token (letters, digits) | `myproject` |
| role | an ability (`build`, `write`, `review`, `test`) or `lead` | `build` |
| member (local agent) | any kebab-case name you choose | `forge` |
| instance (registry) | `<project>-<role>` | `myproject-build` |
| cloud agent | `<project>-<role>` | `myproject-build` |
| environment (shared by the roles) | `<project>-environment` | `myproject-environment` |
| deployment | `<project>-deployment-<role>` | `myproject-deployment-build` |
| memory stores (project-level) | `<project>-memory` (recipes), `<project>-reference` | `myproject-memory` |
| memory folders | `shared/`, `roles/<role>/` | `roles/build/` |
| session | `<instance>-<task-slug>` | `myproject-build-dots-in-usernames` |
| branch (in the agent's clone) | `agent/<task-slug>`, the same slug | `agent/dots-in-usernames` |

Memory belongs to the project, not the instance: every instance of a project
mounts the same recipes store (read-write) and reference store (read-only), so
what one agent learns serves the next. Provisioning attaches existing stores of
that name and creates them only for a new project. `qargi instances normalize
NAME` renames an existing instance's resources to match, and `instances show`
lists the deviations. The role list can be extended with `QARGI_ROLES`.

## Roles, abilities and members

A role is named by its activity. Each of the four abilities is defined by a skill,
which a member loads when the task block names the ability (`ABILITY: build — load
skill qargi-build`) and a cloud agent of that role carries in its prompt:

| Role | Ability | Skill | What it does |
|---|---|---|---|
| `build` | build | `qargi-build` | changes the code with its tests, manual page, help and changelog |
| `write` | write | `qargi-write` | writes the operational documentation on its own branch |
| `review` | review | `qargi-review` | reads a change, runs its checks and reports a verdict; changes no file |
| `test` | test | `qargi-test` | writes and repairs tests, proves them failing first and stable |
| `lead` | (coordinates) | `/qargi-team` | runs a team of members on one task |

The members are yours to name: `qargi agent add forge --abilities build,test` renders
the one member definition qargi ships into `~/.claude/agents/forge.md` (`--project
NAME` puts it in that repository, hidden from git), with the abilities it serves (all
four by default). `qargi agent for build` prints the member that serves an ability,
and dispatch spawns that one; `qargi agent list`, `rename`, `refresh` (re-render from the current definition) and `remove` manage them.
One member may serve every ability, or each ability may have its own.

A role is a directory with `role.json` (its class, write or read-only, and a description) and
`ROLE.md` (its instructions). The four above ship with qargi; `review` is read-only. Add your own
under `~/.qargi/config/roles/NAME/` (one lower-case token, never `lead`). The class decides what the
guard allows; the text of a role cannot change it. `qargi role list` shows the roles and where they
live, `role show NAME` prints one, `role prompt NAME` prints its instructions as a task block carries
them, and `role check [NAME]` validates one role or all. `qargi local prepare --role ROLE` prepares a
local run for that role (default `build`): a read-only role keeps the clone unchanged.

Installations made with the earlier names (roles `dev` and `docs`, the fixed agents
`qargi-dev`, `qargi-docs`, `qargi-review`, `qargi-test`, cloud agents named
`<project>-agent-<role>`) move to these with `qargi migrate roles`: it prints a plan
with every cloud call and a plan token, and applies exactly that plan with `--apply
--plan TOKEN --asked "<your words>"`.

## Methodologies

A methodology is the way a project is developed and released, as data: its branches, versioning and
changelog, test tiers, CI, release steps, deployment options and the generic files a new project
starts with. One ships, `gitflow`; add your own under `~/.qargi/config/methodologies/NAME/`
(`methodology.json` and a `scaffold/` directory). `qargi methodology list` shows them, `show NAME`
prints one, and `check [NAME]` validates one or all. These verbs only read.

- `qargi project new NAME [--dir DIR] [--param test_command='make test'] [--url URL]` starts a new
  project on the methodology's branches with its generic files.
- `qargi project attach [DIR]` reads an existing repository, shows the answers it would store and the
  gaps against the methodology, and changes nothing in the repository.

Both print a plan and a token; they write only when you apply it with `--plan TOKEN --approved "<your
words>"` (`qargi help approvals`).

## Git-flow

A project that follows `gitflow` is driven by the lead with `qargi feature` and `qargi release`
(the `/qargi-flow` skill has the full process). Every merge is `--no-ff`, made in temporary
worktrees: your checkout is never touched, a branch moves only after every merge succeeded, and a
refusal changes nothing.

1. `qargi feature start NAME --purpose "..."` cuts `feature/NAME` from develop. A feature is a broad
   theme; `qargi feature list` shows the open ones and the files two of them both change.
2. Tasks run on `agent/<slug>` (`/qargi-task ... --base feature/NAME`) with targeted checks only.
   Take each verified series in with `qargi feature merge NAME BRANCH`.
3. When the feature is complete: `qargi feature sync NAME` (merges develop in), `qargi feature verify
   NAME` (the one whole-suite run per feature), then `qargi feature finish NAME`, the only merge into
   develop. `qargi feature status NAME` shows commits ahead and whether the whole-suite run is
   current.
4. `qargi release start VERSION` cuts `release/VERSION` from develop (only from a head that passed the
   suite) and bumps `VERSION` and the changelog date. `qargi release push VERSION` opens the pull
   request into master so CI runs on the commit to be released; `qargi release finish VERSION`
   merges into master, tags, merges back into develop and pushes. `release status` and `release
   verify` work as for features.
5. A hotfix is the same with `--hotfix`: `qargi release start VERSION --hotfix` (from master), then
   `release push` and `release finish --hotfix` (into the open release branch instead of develop,
   if there is one).

Merging into develop or master, pushing and tagging each print a plan and a token first; apply it
with `--plan TOKEN --approved "<your words>"`. A merge that conflicts changes nothing and exits 3,
naming a worktree with the merge in progress: resolve and commit there, then run the same command
with `--resolved`.

## Skills and command

Twelve skills, all prefixed `qargi-`, drive one `qargi` command. `/qargi-task` dispatches work; four define the abilities (above); the others configure and manage:

| Skill | Covers |
|---|---|
| `/qargi-task` | dispatch (`/qargi-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/qargi-project` | the one-time project questionnaire: repository, roles, per-role push policy, models, skills, budget, memory, the members |
| `/qargi-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/qargi-provision` | `plan`, `apply`, `add-reference` |
| `/qargi-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), reviewed at import, checked for drift |
| `/qargi-memory` | `lint`, `get`, the canon (`check`, `plan`, `apply`, `import`, `promote`), the session-start autoload |
| `/qargi-verify` | the coordinator's procedure for verifying and applying returned patches |
| `/qargi-flow` | the lead's git-flow process: features, tasks, releases, hotfixes and resolving conflicts |
| `/qargi-team` | a team on one task: a lead coordinating members for build, write and review; led by this session, a cloud lead, or a lead started in the console |

## Help, manual page and completion

- `qargi help` lists the commands by task; `qargi help COMMAND` shows its verbs and `qargi help COMMAND VERB` the arguments and options of one. Every command also takes `--help`. `qargi help approvals`, `naming`, `memory`, `push`, `concepts` and `files` explain the ideas.
- `man qargi` is the complete reference (`qargi help --man | man -l -` if it is not installed).
- Tab completion for bash, zsh and fish offers commands, verbs, options (each once, also as `--option=value`; with a one-line description in zsh and fish) and the values that exist on your machine, each with its description in zsh and fish: your projects (for `lead` and `team`, those that define teams), instances (cloud ones for `start`, `send`, `track`, `instances budget`), sessions narrowed to what the verb can act on (`stop` a running one, `collect` one whose outputs are not downloaded, `close` and `watch` the open ones), a project's teams, roles and packs (skills or tools by command), memory store and deployment ids, model ids, the branches of the project's repository for `--base`, the keys of a project's answers for `project set` with the values each takes, and the usual spend ceilings and wait times. `install.sh --user` installs all three; zsh needs `fpath=(~/.local/share/zsh/site-functions $fpath)` in `~/.zshrc` before `compinit`.
- Inside a project's repository you can leave out the project: `qargi lead status`, `qargi team brief code-docs ...`, `qargi canon check`. A role stands for the instance: `qargi instances show build`. `QARGI_PROJECT` names the project from anywhere. A project you type always wins.

All three, and the checks that keep them true, come from one description of the commands in `lib/commands.py`; `tests/test_help.py` compares it with the scripts. After changing a flag or a verb, describe it there and regenerate the page with `python3 lib/help.py man > man/qargi.1`.

## Members

qargi ships one member definition (`agents/member.md`) and installs none: you create
the members with `qargi agent add`. A member may call `Bash`, `Read`, `Edit`, `Write`,
`Grep`, `Glob`, `Monitor`, `TaskStop`, `ToolSearch` and `Skill`, and every Bash, Edit,
Write and NotebookEdit call passes `qargi __guard`. The guard refuses `git push`, `gh`,
`ssh`, `scp`, `sftp` and changes to a git remote. It also makes review read-only as a
rule rather than a missing tool: a member that only reviews names its class in the hook
command of its definition, and `qargi local prepare --ability review` records the ability
in the run directory for a member that serves several abilities (the guard refuses any
write to that record). Under review the guard refuses an edit outside the run's output
directory and a Bash command that writes into the clone. Whatever the ability,
the guard also refuses a member the verbs that change a skill (`qargi skill|tool new`,
`import`, `seal`, `remove`, `link`, `unlink`, `enable`, `disable`, `qargi discover
install`, `qargi packs apply`) and any write in the pack library, in `credentials/` or `install.json` of the
configuration directory (not the rest of it), in `~/.claude/skills` or
a `.claude/skills` directory outside its clone (also `~/.claude/agents` and
`~/.claude/plugins`); the `skills/` and `.claude/skills` directories of the repository in
the member's clone stay writable, since they are the work product. The guard fails closed on an
internal error, and the member definition sets `onFailure: "block"` on the hook (Claude
Code 2.1.295 or later) so that a hook that cannot run blocks the call; frontmatter
hooks of a project-level agent run only once you trust the workspace. So one definition
serves every ability; what an ability does comes from its skill and the contract, not
from the definition. The guard is a second barrier beside the credential-free git
wrapper; `qargi local verify` remains the proof. A new member is available in Claude
Code sessions started after it is added.

## Splitting, merging and moving memory

A memory store is a directory structure of notes, and `qargi memory` moves notes between two of them. A store is a directory, a `.jsonl` dump (read-only: a source, never a target) or a `memstore_` id; `lib/membackend.py` is the one interface behind all three (the Managed Agents store is reached through `ant`; another backend can be added beside them).

- `qargi memory split FROM TO (--prefix PATH | --role R | --note-kind K) [--archive]` copies the notes the selector picks into `TO`; with `--archive` the originals move to `/_archive/<date>/` in `FROM`.
- `qargi memory copy FROM TO [selector]` copies and leaves `FROM` alone; `qargi memory merge FROM TO` adds every note of `FROM` that `TO` lacks.
- A note that exists on both sides with different content is not overwritten: the incoming one goes to `/_conflicts/<date>/`, as in the reconciler (`--policy keep` leaves it out and reports it instead).

Nothing is ever deleted, and no verb can delete: what leaves a store is archived, and every note written records where it came from by a segment appended to its `Sources:` line (`; copied from NAME:/path@abc123` or `; archived from /path@abc123 on DATE`). So every change can be undone: merging a split's target back into its source moves the archived originals back, byte for byte. A copy from another store is import-only; the source is read, never written.

A note whose name starts with a dot or ends in white space is not a note, and one the target cannot hold (too many path segments, too large for the cloud store) makes the plan refuse, naming the path; narrow the selection with `--prefix`, `--role` or `--note-kind`. `merge` and `copy` without a selector leave the source's `/_archive/` behind.

Each verb prints its plan and a plan token and changes nothing until you run it again with `--plan TOKEN --approved "<your words>"`, which is written to the audit log with the token, the selector and every step (a second line follows when the apply succeeded). A caller's own approval does not stand in for the token. The plan records the digest of every note it read; if an agent wrote to either store in between, the apply is refused before the first change.

## Finding tools

`qargi discover` finds, recommends and installs tools for the roles of a project: skills, MCP servers, packages for the sandbox and built-in tools of the agent.

- `qargi discover search QUERY [--kind K] [--role R] [--online]` searches the reviewed catalog (`catalog/tools.json`) and your library; `--online` adds the official MCP registry and Anthropic's skills repository. Online results are marked as not reviewed.
- `qargi discover recommend [PROJECT] [--role R]` ranks the catalog for each role by the stack it sees in the repository (Go, shell, bats, man pages, Actions, ...) and marks what the role has already.
- `qargi discover show ID` prints an entry: its risk, what it installs and what was verified.
- `qargi discover install ID` asks where it should reach (`user`, `user-role`, `project`, `project-role`) and then uses the existing gates: a skill or an MCP server is imported with its review and your approval of exactly that content, linked at the scope and offered to the cloud agents it reaches (the plan is shown first). A package is added to the role's `apt` list in the project answers; a built-in tool is added to the definitions of the members it reaches. An MCP server from the registry does not list its tools, so you get a draft pack to complete; nothing found online is installed on trust.

## Export and import

`qargi export` writes one archive of what you select, and `qargi import` restores it, on this machine or another:

- **config**: project answers, the instance registry, profiles, the skill and tool library.
  An archive made with the earlier role names (`dev`, `docs`) is imported under the current ones.
- **definitions**: the cloud agents, deployments and environment as they are now, read from the cloud with secret values removed. Import restores them as files; rebuild with `qargi provision`.
- **memories**: every note of the memory and reference stores. Import writes them to the stores named in the project's answers.
- **state**: the session tracker and the audit log (the audit log is only ever appended to).
- **credentials**: token files. Only an encrypted archive may hold them; the tokens in the cloud vault are not exported.

Both ask what to include (or take `--only`/`--project`). Export asks for an optional password; with one the whole archive is encrypted with gpg (AES-256) and the password never appears in a command line (`--password-file` for scripts). Import asks for the password if the archive is encrypted, shows what is inside, asks which parts and projects, and for each part how to treat what exists: `merge` (add what is missing), `overwrite` (also replace what differs) or `replace` (make it match the archive, removing the rest; you must type `replace` to allow the removals). It prints the plan, writes nothing until you confirm, and saves whatever it replaces or removes under `~/.qargi/state/backups/`. The archive is treated as untrusted: names, kinds of entry and checksums are verified before anything is read. `qargi import FILE --dry-run` prints the plan without a terminal.

## Install

```sh
./install.sh --user                    # skills in ~/.claude, command in ~/.local/bin
./install.sh --project /path/to/repo   # skills for one repository only
qargi agent add builder --abilities build    # then name your members, for example
```

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (the whole tool is copied to `~/.local/share/qargi` for `--user`),
`--uninstall` to remove (copies need `--force`). An existing real directory is
never replaced without `--force`. Install at one level only. The command is
always user-level, so install `--user` before `--project`. The instance
registry, session tracker and profiles are per user, under `~/.qargi/config` and
`~/.qargi/state` (`QARGI_HOME` replaces `~/.qargi`), whichever level installs the skills. Repository rules for
agents go in a profile under `~/.qargi/config/profiles/`, also
outside the repository: nothing qargi related is added to a project's
committed files. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

### Where the data lives

Everything qargi keeps about you is under `~/.qargi`: `config/` (projects, instances, profiles, the pack library, credentials, `install.json`) and `state/` (the session tracker, the audit log, runs, backups). `QARGI_HOME` replaces the root; `QARGI_CONF` and `QARGI_STATE` name either directory and win over it. `XDG_CONFIG_HOME` and `XDG_STATE_HOME` are not used (the `ant` CLI keeps its login there).

An earlier version kept the data in `~/.config/qargi` and `~/.local/state/qargi`. While only those exist, every command except `help`, `version`, the completion, the guard and the run-event hooks stops and tells you to run `qargi migrate home`. It prints the plan (every file, mode and digest, and the files whose old paths it rewrites; the records `audit.log`, `supervisor.log` and `run-events/` are copied byte for byte) and a token; with `--plan TOKEN --approved "<words>"` it copies, checks every file by digest and leaves the old directories untouched as a backup. It never creates an empty `~/.qargi` next to old data.

### Running a branch checkout

`install.sh --user` records the tool it installed in `~/.qargi/config/install.json`. A checkout run from anywhere else, for example `bin/qargi` in a worktree, is then a dev run: it keeps its data in `<checkout>/.qargi` (ignored by git), prints `qargi: dev run from ...; data in ...` on stderr once per command, and never touches your live projects, credentials or audit log. The installed copy (for example `/opt/qargi`) is for confirming committed work and managing live projects, and never writes into its own directory. Without `install.json` a checkout behaves as the installed one. To point a dev run at live data on purpose set `QARGI_HOME=~/.qargi`; any explicit `QARGI_HOME`, `QARGI_CONF` or `QARGI_STATE` overrides the sandbox, and `qargi migrate home` refuses in a dev run unless one of them is set. Members call `qargi __guard` and the hooks from `PATH`, which is the installed copy: put `<checkout>/bin` first on `PATH` to test a branch's guard or hooks.

## Cloud profiles per project

`qargi cloud set PROJECT --profile NAME --workspace-id wrkspc_...` binds a project to an `ant` profile and the workspace it must
reach; `qargi cloud login PROJECT` logs that profile in on your terminal, and `qargi cloud check` verifies it. From then on every
command about the project runs `ant` under that profile and refuses to touch another workspace. Without a binding, `ant`'s
active profile is used.

## Upgrading the installed tool

`qargi upgrade --branch develop` fetches that branch of the installed checkout's origin (for example `/opt/qargi`), shows the commits and files that would change and prints a plan token; `qargi upgrade --branch develop --plan TOKEN --approved "..."` applies exactly that (fast-forward only on the current branch, `--tag T` for a tag), re-runs `install.sh --user` and lists the members to refresh. The git commands that write into the root-owned checkout run through `sudo`.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).
