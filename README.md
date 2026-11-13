# qargi

**A gathering place for agent work: dispatch, review, remember.**

Qargi is a CLI and a set of skills that dispatch one-off, task-scoped development tasks to agents and take the work back as
reviewable patches. The skills are instructions for the lead, the agent session you work in, which runs the `qargi` command: Claude Code
and Codex are the leads and local runtimes qargi ships definitions for ([what is verified of Codex](docs/members-and-providers/codex.md)),
and another runtime is defined as data ([Providers and runtimes](docs/members-and-providers/providers.md)). An agent works on one task in its own clone, whose git has no credentials and whose only remote is a copy with its push URL disabled, so an ordinary push has nothing to reach or authenticate with; that is what qargi supports, not a proof that no push can happen, so the dispatching session checks that the real repository's refs did not move, verifies the result and applies it. Local
members are the default and cloud agents are used only when you ask for them in that request; each runs on a runtime the project names for that surface.

Requirements: Linux with bash, GNU coreutils (including `timeout`) and findutils, git, jq, python3 3.11 or newer, `flock` (the locks) and `ssh-keygen` (the marshal's signed records). qargi uses GNU options throughout and nothing checks the platform before a verb runs, so another system is not supported. `make doctor` checks the tools of a checkout.

## Quick start

Choose the installation for your lead's runtime. Both user installations put the command in `~/.local/bin`. For a Claude Code lead, install skills in `~/.claude/skills`:

```sh
./install.sh --user
```

For a Codex lead, install skills in `~/.codex/skills` ([setup](docs/members-and-providers/codex.md)):

```sh
./install.sh --user --runtime codex
```

Attach an existing repository (or use `qargi project new myproject`). Each prints a plan and a token to apply with `--plan TOKEN --approved "<your words>"`; `--provider-local` names the members' runtime. Add a worker and a read-only reviewer:

```sh
qargi project attach ~/src/myproject --name myproject \
  --provider-local claude-code
qargi agent add worker --project myproject
qargi agent add reviewer --project myproject
```

For Codex, attach with `--provider-local codex`. It keeps no member files, so `agent add` refuses it; each task is a run: `qargi local prepare --task-file F --done C ...`, then `qargi local run RUN`.

```sh
qargi project attach ~/src/other --name other --provider-local codex
```

The lead drives the feature loop from an agent session in the repository:

```sh
qargi feature start dots --purpose "..."
/qargi-task "<task>" --done "<check>" --base feature/dots
qargi review apply RUN
qargi feature merge dots agent/<slug>
qargi feature verify dots
qargi feature finish dots
qargi backlog list
```

Start cuts `feature/dots` from develop; the member works in its own clone and returns patches, and review apply puts the checked patches on `agent/<slug>`. Verify runs the whole suite once (`test_command`, or the declared gates of tier feature). Finish is the only merge into develop and names the open backlog items its commits mention. Backlog list shows the open items of the backlog file (the answer `backlog.file`).

`/qargi-task` is the Claude Code slash command of the `qargi-task` skill; another lead loads that skill by name or runs the verbs
it describes (`qargi local prepare`, `qargi local run`, `qargi local verify`); a Codex lead's setup is in
[Codex as the lead](docs/members-and-providers/codex.md#codex-as-the-lead).

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
