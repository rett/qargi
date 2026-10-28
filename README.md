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

Two kinds of agent instance are supported and registered by name:

- **local**: a Claude Code subagent working in a scratch clone.
- **cloud**: a Claude Managed Agents deployment, driven through the `ant` CLI.

Local is the default. Cloud is used only when the user asks for it in that
request.

## Naming convention

Every name follows from the project, so resources are identifiable at a glance.

| Thing | Name | Example |
|---|---|---|
| project | one lower-case token (letters, digits) | `tacctl` |
| role | from a fixed list: `dev`, `review`, `docs`, `test` | `dev` |
| instance (registry) | `<project>-<role>` | `tacctl-dev` |
| agent | `<project>-agent-<role>` | `tacctl-agent-dev` |
| environment (shared by the roles) | `<project>-environment` | `tacctl-environment` |
| deployment | `<project>-deployment-<role>` | `tacctl-deployment-dev` |
| memory stores (project-level) | `<project>-memory` (recipes), `<project>-reference` | `tacctl-memory` |
| session | `<instance>-<task-slug>` | `tacctl-dev-dots-in-usernames` |
| branch (in the agent's clone) | `agent/<task-slug>`, the same slug | `agent/dots-in-usernames` |

Memory belongs to the project, not the instance: every instance of a project
mounts the same recipes store (read-write) and reference store (read-only), so
what one agent learns serves the next. Provisioning attaches existing stores of
that name and creates them only for a new project. `qargi instances normalize
NAME` renames an existing instance's resources to match, and `instances show`
lists the deviations. The role list can be extended with `QARGI_ROLES`.

## Skills and command

Eight skills, all prefixed `qargi-`, drive one `qargi` command. `/qargi-task` dispatches work; the others configure and manage:

| Skill | Covers |
|---|---|
| `/qargi-task` | dispatch (`/qargi-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/qargi-project` | the one-time project questionnaire: repository, roles, per-role push policy, models, skills, budget, memory |
| `/qargi-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/qargi-provision` | `plan`, `apply`, `add-reference` |
| `/qargi-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), reviewed at import, checked for drift |
| `/qargi-memory` | `lint`, `get`, the canon (`check`, `plan`, `apply`, `import`, `promote`), the session-start autoload |
| `/qargi-review` | verifying and applying returned patches |
| `/qargi-team` | a team on one task: a lead coordinating the developer, docs and review agents; led by this session, a cloud lead, or a lead started in the console |

## Help, manual page and completion

- `qargi help` lists the commands by task; `qargi help COMMAND` shows its verbs and `qargi help COMMAND VERB` the arguments and options of one. Every command also takes `--help`. `qargi help approvals`, `naming`, `memory`, `push`, `concepts` and `files` explain the ideas.
- `man qargi` is the complete reference (`qargi help --man | man -l -` if it is not installed).
- Tab completion for bash, zsh and fish offers commands, verbs, options (with a one-line description in zsh and fish), and the values that exist on your machine: your projects, instances, a project's teams, sessions and packs. `install.sh --user` installs all three; zsh needs `fpath=(~/.local/share/zsh/site-functions $fpath)` in `~/.zshrc` before `compinit`.
- Inside a project's repository you can leave out the project: `qargi lead status`, `qargi team brief code-docs ...`, `qargi canon check`. A role stands for the instance: `qargi instances show dev`. `QARGI_PROJECT` names the project from anywhere. A project you type always wins.

All three, and the checks that keep them true, come from one description of the commands in `lib/commands.py`; `tests/test_help.py` compares it with the scripts. After changing a flag or a verb, describe it there and regenerate the page with `python3 lib/help.py man > man/qargi.1`.

## Install

```sh
./install.sh --user                    # skills in ~/.claude, command in ~/.local/bin
./install.sh --project /path/to/repo   # skills and subagent for one repository only
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
