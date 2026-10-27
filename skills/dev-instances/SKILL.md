---
name: dev-instances
description: Register, list, inspect, rename-resources and remove dev-agent instances (local subagent definitions or cloud Managed Agents deployments), with model and effort selection at init. Registry lives outside every repository.
argument-hint: init|list|show|remove|normalize ...
---

# /dev-instances

The registry (`$XDG_CONFIG_HOME/dev-agent/instances.json`) and the session
tracker (`$XDG_STATE_HOME/dev-agent/sessions.json`) are per user and never in a
repository. Cloud verbs need `--asked "<the user's request that names the cloud
instance>"`; changes to existing resources also need `--approved "<go-ahead>"`
after you have shown the printed PLAN.

| Verb | Command | Notes |
|---|---|---|
| init (cloud, existing) | `dev-agent instances init --location cloud --deployment ID [--name N] [--budget CENTS] [--model M] [--effort E] [--no-session] --asked "..." [--approved "..."]` | Reads the deployment and its agent; records pinned version, model, effort, environment, resources, vault ids; runs the deployment (standby session) and starts tracking. `--budget` sets the deployment's spend ceiling (sessions inherit it). A differing `--model`/`--effort` prints a PLAN; with `--approved` the agent gets a new version and the deployment is re-pointed. |
| init (cloud, new) | `dev-agent instances init --location cloud --provision --name N [--model M] [--effort E] [--budget CENTS] [--apt "pkg ..."] [--networking unrestricted\|limited] --asked "..." [--approved "..."]` | Creates new resources via `/dev-provision`: plan without `--approved`; with it, creates, seeds both memory stores, registers and starts a session. |
| init (local) | `dev-agent instances init --location local --agent FILE [--name N] [--model M] [--effort E]` | Records path, sha256, model and effort. |
| list | `dev-agent instances list [--reconcile]` | Instances plus active sessions; `--reconcile` flags live sessions missing from the tracker (ORPHAN, never touched). |
| show | `dev-agent instances show NAME [--reconcile]` | Full record plus staleness: agent newer than pinned, agent file changed, deployment/agent archived or paused. |
| normalize | `dev-agent instances normalize NAME --asked "..." [--approved "..."]` | Renames the agent, environment and deployment to `<NAME>-agent`, `-environment`, `-deployment` and the memory and reference stores to `<project>-memory`, `<project>-reference`; plan first. `show` lists the deviations as NAMING lines. |
| remove | `dev-agent instances remove NAME` | Registry entry only; refuses with open sessions. |

Instance names are `<project>-<role>` with a role from the fixed list (`dev`, `review`, `docs`, `test`), for example `tacctl-dev`; `init` for an existing deployment needs a conforming `--name`.
