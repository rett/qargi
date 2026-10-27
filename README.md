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

## Install

```sh
./install.sh --user                    # every project on this machine
./install.sh --project /path/to/repo   # one repository only
```

Both link to this checkout, so `git pull` updates them; add `--copy` for real
files (use that when the project's `.claude` directory is committed or
shared), `--uninstall` to remove. An existing real directory is never
replaced without `--force`. Install at one level only. The instance registry
and session tracker are always per user, under the XDG config and state
directories, whichever level installs the skill. Repository rules for
agents go in `.dev-agent/profile.md` in the target repository.

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT
license, see [LICENSE](LICENSE).
