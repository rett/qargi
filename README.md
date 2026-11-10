# qargi

**A gathering place for agent work: dispatch, review, remember.**

Qargi is a set of Claude Code skills and a CLI that dispatch one-off, task-scoped development tasks to agents and take the work back as
reviewable patches. An agent works on one task in its own clone and is given no way to push (a git wrapper without credentials, and a guard that refuses the ordinary ways); the dispatching session verifies the result and applies it. Local
members are the default and cloud agents are used only when you ask for them in that request; each runs on a runtime the project names for that surface.

Requirements: Linux with bash, GNU coreutils and findutils, git, jq, python3 3.11 or newer, `flock` and `ssh-keygen` (the marshal's signed records). qargi uses GNU options throughout and nothing checks the platform before a verb runs, so another system is not supported. `make doctor` checks the tools of a checkout.

## Quick start

```sh
./install.sh --user                    # skills in ~/.claude, the command in ~/.local/bin

# a project: attach an existing repository (or `qargi project new myproject`); each prints a plan and a token,
# applied with --plan TOKEN --approved "<your words>"
qargi project attach ~/src/myproject --name myproject --provider-local claude-code
qargi agent add worker --project myproject      # the members that do the work,
qargi agent add reviewer --project myproject    # and the read-only one

# the feature loop; the lead drives it from a Claude Code session in the repository
qargi feature start dots --purpose "..."        # cuts feature/dots from develop
/qargi-task "<task>" --done "<check>" --base feature/dots   # a member works in its own clone and returns patches
qargi review apply RUN                          # puts the checked patches on agent/<slug>
qargi feature merge dots agent/<slug>
qargi feature verify dots                       # the one whole-suite run (test_command, or the declared gates of tier feature)
qargi feature finish dots                       # the only merge into develop; names the open backlog items its commits mention
qargi backlog list                              # the open items of the backlog file (the answer backlog.file)
```

## Documentation

| Topic | Contents |
|---|---|
| [Install and upgrade](docs/install-and-upgrade/README.md) | Install, where the data lives, running a branch checkout, upgrading, cloud profiles, export and import |
| [Flow](docs/flow/README.md) | Naming convention, roles, methodologies, git-flow, the feature marshal |
| [Members and providers](docs/members-and-providers/README.md) | Members and the guard, choosing models, providers and runtimes |
| [Skills, tools and memory](docs/skills-tools-and-memory/README.md) | The skills and the command, packs in a local session, memory tiers, moving memory, finding tools |
| [Reference](docs/reference/README.md) | Help, the manual page, completion, command conventions |
| [Development](docs/development/README.md) | Setting up a checkout, tests, contributing, the [architecture](docs/development/architecture.md) |

The overview of the documentation is [docs/README.md](docs/README.md). Task-oriented guides are on the documentation site, <https://qargi.rettware.com/>.
`man qargi` is the complete reference (`qargi help` lists the commands by task; `qargi help --man | man -l -` if the page is not installed).

Status: pre-release, see [CHANGELOG.md](CHANGELOG.md). Licensed under the MIT license, see [LICENSE](LICENSE).

Copyright (c) 2026 Everett C. Haimes III
