# dev-agent

A Claude Code skill that dispatches one-off, task-scoped development tasks to
sandboxed agents and takes the work back as reviewable patches. An agent
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
| agent, environment, deployment | `<instance>-agent`, `-environment`, `-deployment` | `tacctl-dev-agent` |
| memory stores (project-level) | `<project>-memory` (recipes), `<project>-reference` | `tacctl-memory` |
| session | `<instance>-<task-slug>` | `tacctl-dev-dots-in-usernames` |
| branch (in the agent's clone) | `agent/<task-slug>`, the same slug | `agent/dots-in-usernames` |

Memory belongs to the project, not the instance: every instance of a project
mounts the same recipes store (read-write) and reference store (read-only), so
what one agent learns serves the next. Provisioning attaches existing stores of
that name and creates them only for a new project. `dev-agent instances normalize
NAME` renames an existing instance's resources to match, and `instances show`
lists the deviations. The role list can be extended with `DEV_AGENT_ROLES`.

## Skills and command

Seven skills, all prefixed `dev-`, drive one `dev-agent` command. `/dev-task` dispatches work; the others configure and manage:

| Skill | Covers |
|---|---|
| `/dev-task` | dispatch (`/dev-task "<task>" --done "<check>"`) and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/dev-project` | the one-time project questionnaire: repository, roles, per-role push policy, models, skills, budget, memory |
| `/dev-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/dev-provision` | `plan`, `apply`, `add-reference` |
| `/dev-packs` | skills and tools in one library, attached by scope (user, user-role, project, project-role), reviewed at import, checked for drift |
| `/dev-memory` | `seed`, `seed-reference`, `lint`, migrating a flat store |
| `/dev-review` | verifying and applying returned patches |

## Install

```sh
./install.sh --user                    # skills in ~/.claude, command in ~/.local/bin
./install.sh --project /path/to/repo   # skills and subagent for one repository only
```

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (the whole tool is copied to `~/.local/share/dev-agent` for `--user`),
`--uninstall` to remove (copies need `--force`). An existing real directory is
never replaced without `--force`. Install at one level only. The command is
always user-level, so install `--user` before `--project`. The instance
registry, session tracker and profiles are per user, under the XDG config and
state directories, whichever level installs the skills. Repository rules for
agents go in a profile under `$XDG_CONFIG_HOME/dev-agent/profiles/`, also
outside the repository: nothing dev-agent related is added to a project's
committed files. `--project` installs are hidden from git through the
repository's local `.git/info/exclude`.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).
