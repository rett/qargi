# qargi documentation

**A gathering place for agent work: dispatch, review, remember.**

*Qargi* is the Iñupiaq word for the traditional community house, where a village
gathered to make and mend its tools, decide together and hand knowledge on. Here the
work of agents gathers in the same way: tasks go out, patches come back for review,
and what was learned is kept in memory.

Qargi is a set of Claude Code skills and a CLI that dispatch one-off, task-scoped
development tasks to agents and take the work back as reviewable patches. An agent
works on one task in its own clone, whose git has no credentials and whose only remote is
a copy with its push URL disabled; the dispatching session checks that the real repository's
refs did not move, verifies the result and applies it.

Two kinds of agent do the work, each on a **runtime** the project names for that surface (see
[Providers and runtimes](members-and-providers/providers.md); there is no default):

- **local**: a **member**, an agent you name, run by the project's local runtime in a scratch clone:
  a Claude Code subagent (`claude-code`), a Codex process (`codex`, see
  [Codex as lead and as member](members-and-providers/codex.md)), or a command-line runtime you define as data.
- **cloud**: a hosted agent of one role, registered as an instance; today a Claude Managed Agents
  deployment (`claude-platform`) driven through the `ant` CLI.

A **lead** coordinates members on one task (a team): this session, a cloud lead or a lead
started in the console.

Local is the default. Cloud is used only when the user asks for it in that
request.

## Topics

| Topic | Contents |
|---|---|
| [Install and upgrade](install-and-upgrade/README.md) | Install, where the data lives, running a branch checkout, upgrading the installed tool, cloud profiles per project, export and import |
| [Flow](flow/README.md) | Naming convention, roles and members, methodologies, git-flow (features, releases, hotfixes, detached and parking branches), the feature marshal |
| [Members and providers](members-and-providers/README.md) | Members and the guard, choosing models, providers and runtimes, Codex as lead and as member |
| [Skills, tools and memory](skills-tools-and-memory/README.md) | The skills and the command, skills and tools in a local session, baseline packs, memory tiers, splitting, merging and moving memory, finding tools |
| [Reference](reference/README.md) | Help, the manual page, completion, command conventions |
| [Development](development/README.md) | Setting up a checkout, tests, contributing, the [architecture](development/architecture.md) |

The task-oriented guides are on the documentation site, <https://qargi.rettware.com/>.
