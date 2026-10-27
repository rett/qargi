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

## Resource names

Every cloud resource is named `<project>-<role>-<component>`, where
`<project>-<role>` is also the instance name in the registry (for example
`tacctl-dev`) and the component is one of `agent`, `environment`, `memory`,
`deployment`, `reference` (`vault` when one is managed). Provisioning
(`--project P --role R`, role defaults to `dev`) creates them that way, and
`registry.sh normalize NAME` renames an existing instance's resources to match.

## Skills and command

Five skills, all prefixed `dev-`, drive one `dev-agent` command:

| Skill | Covers |
|---|---|
| `/dev-agent` | dispatch and session lifecycle: `send`, `start`, `status`, `watch`, `collect`, `stop`, `close` |
| `/dev-instances` | `init`, `list`, `show`, `remove`, `normalize` |
| `/dev-provision` | `plan`, `apply`, `add-reference` |
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
