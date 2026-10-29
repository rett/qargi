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
and dispatch spawns that one; `qargi agent list`, `rename` and `remove` manage them.
One member may serve every ability, or each ability may have its own.

Installations made with the earlier names (roles `dev` and `docs`, the fixed agents
`qargi-dev`, `qargi-docs`, `qargi-review`, `qargi-test`, cloud agents named
`<project>-agent-<role>`) move to these with `qargi migrate roles`: it prints a plan
with every cloud call and a plan token, and applies exactly that plan with `--apply
--plan TOKEN --asked "<your words>"`.

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
rule rather than a missing tool: `qargi local prepare --ability review` records the
ability in the run directory, and under it the guard refuses an edit outside the run's
output directory and a Bash command that writes into the clone. So one definition
serves every ability; what an ability does comes from its skill and the contract, not
from the definition. The guard is a second barrier beside the credential-free git
wrapper; `qargi local verify` remains the proof. A new member is available in Claude
Code sessions started after it is added.

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

Both ask what to include (or take `--only`/`--project`). Export asks for an optional password; with one the whole archive is encrypted with gpg (AES-256) and the password never appears in a command line (`--password-file` for scripts). Import asks for the password if the archive is encrypted, shows what is inside, asks which parts and projects, and for each part how to treat what exists: `merge` (add what is missing), `overwrite` (also replace what differs) or `replace` (make it match the archive, removing the rest; you must type `replace` to allow the removals). It prints the plan, writes nothing until you confirm, and saves whatever it replaces or removes under `$XDG_STATE_HOME/qargi/backups/`. The archive is treated as untrusted: names, kinds of entry and checksums are verified before anything is read. `qargi import FILE --dry-run` prints the plan without a terminal.

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
registry, session tracker and profiles are per user, under the XDG config and
state directories, whichever level installs the skills. Repository rules for
agents go in a profile under `$XDG_CONFIG_HOME/qargi/profiles/`, also
outside the repository: nothing qargi related is added to a project's
committed files. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).
