---
name: qargi-instances
description: Register, list, inspect, rename-resources and remove qargi instances (local subagent definitions or cloud Managed Agents deployments), with model and effort selection at init. Registry lives outside every repository.
argument-hint: init|list|show|remove|normalize ...
---

# /qargi-instances

The registry (`~/.qargi/config/instances.json`) and the session
tracker (`~/.qargi/state/sessions.json`) are per user and never in a
repository. Cloud verbs need `--asked "<the user's request that names the cloud
instance>"`; changes to existing resources also need `--approved "<go-ahead>"`
after you have shown the printed PLAN.

| Verb | Command | Notes |
|---|---|---|
| init (cloud, existing) | `qargi instances init --location cloud --deployment ID [--name N] [--budget CENTS] [--model M] [--effort E] [--no-session] --asked "..." [--approved "..."]` | Reads the deployment and its agent; records pinned version, model, effort, environment, resources, vault ids; runs the deployment (standby session) and starts tracking. `--budget` sets the deployment's spend ceiling (sessions inherit it). A differing `--model`/`--effort` prints a PLAN; with `--approved` the agent gets a new version and the deployment is re-pointed. |
| init (cloud, new) | `qargi instances init --location cloud --provision --name N [--model M] [--effort E] [--budget CENTS] [--apt "pkg ..."] [--networking unrestricted\|limited] --asked "..." [--approved "..."]` | Creates new resources via `/qargi-provision`: plan without `--approved`; with it, creates, seeds both memory stores, registers and starts a session. |
| init (local) | `qargi instances init --location local --agent FILE [--name N] [--model M] [--effort E]` | Records path, sha256, model and effort. The local workers are members, created with `qargi agent add NAME --roles LIST --project P`; dispatch spawns the member named first on the line `qargi agent for ROLE` prints, with its model and effort (see Members below). |
| models | `qargi agent models [--project P] [--json]` | Shows the two bases (`worker`: build, write, test, write class; `reviewer`: review, read-only), the profiles (shipped: build, write, test, review, auditor, advisor, researcher, lead; a project adds or overrides `profiles.<name>`) and the members, with legacy one-per-ability members flagged. Everything but the bases is a profile (base, tier, effort), resolved at dispatch, not a member. A member that is `STALE` or has `DRIFT` is flagged on its row (below). Migrate with `qargi agent add worker --project P` and `qargi agent add reviewer --project P` (each defaults to its base's abilities), check `qargi agent models`, then retire builder, writer and tester with `qargi agent remove`; auditor, advisor and researcher are profiles now, so `qargi agent remove` them if you added them. |
| list | `qargi instances list [--reconcile]` | Instances (a cloud one whose prompt changed since it was last pushed is marked `prompt STALE`) plus active sessions; `--reconcile` flags live sessions missing from the tracker (ORPHAN, never touched). |
| show | `qargi instances show NAME [--reconcile]` | Full record plus staleness: the prompt hash against the prompt rendered now (STALE, current or unknown), agent newer than pinned, agent file changed, deployment/agent archived or paused. |
| budget | `qargi instances budget NAME CENTS --asked "..." [--session SID]` | Sets the spend ceiling on the instance's deployment; new sessions inherit it. `--session` also changes a running session that already has a budget (a session cannot gain one after creation). |
| refresh-prompt | `qargi instances refresh-prompt NAME [--if-stale] --asked "..." [--plan TOKEN --approved "..."]` | `--if-stale` does nothing, with no cloud call, when the recorded prompt hash matches the prompt rendered now. Rebuilds the cloud agent's system prompt from the current contract, preamble and role addendum; prints what changes and a plan token. Applying creates a new agent version and re-points the deployment. Run it after the contract changes. |
| normalize | `qargi instances normalize NAME --asked "..." [--approved "..."]` | Renames the agent, environment and deployment to `<project>-<role>`, `<project>-environment`, `<project>-deployment-<role>` and the memory and reference stores to `<project>-memory`, `<project>-reference`; plan first. `show` lists the deviations as NAMING lines. |
| remove | `qargi instances remove NAME` | Registry entry only; refuses with open sessions. |

Instance names are `<project>-<role>` with a role from the fixed list (`build`, `review`, `write`, `test`, and `lead`), for example `myproject-build`, or a base: `<project>-worker` (class write) or `<project>-reviewer` (read-only; the project must first accept the missing cloud read-only barrier with `qargi provider accept NAME --surface cloud --no-barrier`); `init` for an existing deployment needs a conforming `--name`.

## Members (the local instances)

A member is written, not copied: qargi keeps one neutral member definition and the project's local
runtime (`models.provider.local`) renders it into that runtime's own file, with the model and effort
of the member's profile mapped through the runtime's catalog. The record is in
`~/.qargi/config/agents.json` with the hash of the file and of what it was rendered from.

- Placement: `qargi agent add NAME --roles LIST --project P` writes where the runtime links
  project agents: the project's member render, `~/.qargi/state/render/P/RUNTIME.agents` (linked into a
  work tree by `qargi project link P --resource agents`), or the checkout's own agents directory,
  hidden from git. Every member belongs to a project (`--project` is required); nothing is written to the runtime's user-level directory.
  A project with no local runtime, or a runtime with no agent files, is refused (exit 2).
- `qargi agent list` and `agent models` flag a member `STALE` (the member definition, the model
  catalog, the runtime's renderer or an extension changed since it was rendered) and `DRIFT` (the
  file was edited by hand), or `MISSING`. `qargi agent refresh NAME` renders it
  again, keeping its name, abilities and model; a `DRIFT` file is replaced, so look at the edit first.
  Sessions started afterwards use the new file.
- Dispatch depends on the runtime's `dispatch.mode`: with `in-session` (Claude Code) the lead spawns
  the member the line `qargi agent for ROLE` prints with the Agent tool; with `command` there is
  no member file, and `qargi local run RUN` runs the CLI with the member's prompt composed in
  (`/qargi-task`). A new runtime is added in `/qargi-providers`.
