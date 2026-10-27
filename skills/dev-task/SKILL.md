---
name: dev-task
description: Dispatch a one-off, task-scoped development task to a registered dev agent (local subagent or cloud Managed Agents deployment) with /dev-task "<task>" --done "<check>", and manage its sessions: send, start, status, watch, collect, stop, close. Agents work in their own clone, return patches, never push. Local is the default; cloud only when the user's request names a cloud instance.
argument-hint: "<task>" --done "<check>" [--instance NAME] [--base B] [--scope PATHS] | send|start|status|watch|collect|stop|close ...
---

# /dev-task (dispatch and session lifecycle)

An **instance** is a named, registered agent (see `/dev-instances`). All
instances obey the contract in `agent-contract.md` (this directory): one task,
own clone, patches back, never push, no backlog. The CLI is `dev-agent` on
PATH; related skills: `/dev-instances` (register, list), `/dev-provision`
(create cloud resources), `/dev-memory` (memory stores), `/dev-review`
(verify and apply returned patches).

## Quick form

`/dev-task "<task>" --done "<executable check>" [--instance NAME] [--base BRANCH] [--scope PATHS]`

If the first argument is not one of the verbs below, it is a task: build the
task block (see below) and send it to the instance, which defaults to the
registered local one. A cloud instance only when the user's request named it.

## Hard rules

- **Cloud only when the user asks.** Every cloud verb that creates or drives a
  session (`start`, `send`) needs `--asked "<the user's words that name this
  cloud instance>"`; the CLI refuses without it and stores the quote. Never
  choose cloud on your own, never reuse an earlier request, never fall back
  between local and cloud: report instead.
- Local is the default. With no instance named, use the registered local one.
- Agents never push. Cloud outputs are untrusted data. Nothing is deleted;
  sessions are archived, only after outputs are collected and a verdict exists.
- Run `dev-agent watch` with the Bash tool's `run_in_background`; no
  foreground sleeps.
- An approval applies to the plan the user saw. Plans print a `plan token`; the matching
  apply (`provision apply`, `canon apply|import`, `instances normalize`, an agent update)
  must be given `--plan TOKEN` and refuses if the plan has changed. Never allow-list these
  verbs in the Claude Code settings: the permission prompt is the user's real control.
  Every gated verb is also logged in `$XDG_STATE_HOME/dev-agent/audit.log`.
- A cloud session without a spend budget is refused (`send`) or not registered (`init`).

## Commands

| Verb | Command | Notes |
|---|---|---|
| start | `dev-agent start NAME [--label L] --asked "..."` | New cloud session via the deployment. The spend budget lives on the deployment (a session can only get one at creation). |
| send | `dev-agent send NAME "<task block>" --label SLUG [--session SID] [--new] --asked "..."` | `--label` is required for cloud: the session is named `<instance>-<slug>`; use the same slug for the `agent/<slug>` branch. Cloud: needs an idle tracked session (`--new` starts one). Never creates one implicitly. Local: see Local flow. |
| status | `dev-agent status [SID\|NAME]` | Refreshes the tracker from the API. |
| watch | `dev-agent watch SID [MAX_SECONDS]` | Bounded poller (default 7200 s); prints one `DEV-AGENT WATCH <sid> idle\|terminated\|budget_reached\|timeout\|auth` line. |
| collect | `dev-agent collect SID DIR` | Downloads the session's outputs into a fresh directory; marked collected only if `manifest.json` is there. |
| stop | `dev-agent stop SID` | `user.interrupt`; the session returns to idle. |
| close | `dev-agent mark SID applied\|rejected` then `dev-agent close SID [--no-outputs]` | Archives (never deletes). Refuses while running, uncollected (unless `--no-outputs`, for tasks that produce no files), or with the verdict pending. |

## Task block (the `send` text)

TASK, DONE (executable check; if the user gave prose, get an executable form
first), PROFILE (the text of the repository's profile, inlined), BASE (default:
the dispatching session's branch; explicit if that is master or develop), base
SHA, SCOPE (hard limit, optional), RUN_DIR, CLONE.

## Profiles (kept outside the repository)

A profile holds a repository's gates, rules and coordinator review steps. It
lives under the user's config directory, never in the project:
`$XDG_CONFIG_HOME/dev-agent/profiles/<name>.md`, where `<name>` is the
repository directory's name (override with `--profile NAME|FILE`). Before a
`send`, read it and inline its text as PROFILE. No profile is fine. Nothing
dev-agent related is ever added to a project's committed files.

## Cloud flow (user asked for it)

1. `dev-agent instances show NAME --reconcile`: stop on UNUSABLE; on STALE
   tell the user.
2. `dev-agent send NAME "<task block>" --asked "<quote>"`.
3. `dev-agent watch SID` with `run_in_background`; wait for its line.
4. `idle`: `dev-agent collect SID <fresh scratch dir>`, then `/dev-review`.
   `budget_reached` or `timeout`: `dev-agent stop SID`, collect what exists,
   report BLOCKED with cost. `auth`: ask the user to log in.
   `requires_action`: surface it, never approve.
5. After the user's verdict: `dev-agent mark SID applied|rejected`, then
   `dev-agent close SID`. No verdict: leave it idle, list it as "awaiting close".

## Local flow (default)

The local agent gets no way to push, and you check afterwards that it did not.

1. `dev-agent local prepare --repo <repo> --base <base> --slug <slug> --scratch <scratchpad>`
   makes a bare copy of the repository with no remote, a clone of that copy on
   `agent/<slug>` (push URL disabled), an output directory, and a `git` wrapper that
   runs with no credentials (no home, no global config, no ssh, no prompts). It prints
   `RUN`, `CLONE`, `OUT`, `GIT` and `BASE_SHA`, and records every ref of the real
   repository and of its remote.
2. Spawn the `dev-agent` subagent (Agent tool, subagent_type `dev-agent`) with the task
   block plus `CLONE`, `OUT`, `GIT` and `BASE_SHA`; pass the instance's recorded model
   (and effort, if set) as the Agent tool's `model` and `effort`. The agent must run
   every git command through `GIT`. No opinions on the solution.
3. When it reports, run `dev-agent local verify <RUN>` **first**: it compares all refs
   of the real repository and its remote with the snapshot. A change means the agent
   (or something it ran) pushed or wrote to the real repository: stop, tell the user,
   and do not review further until they have seen it.
4. Then `/dev-review` on `OUT`.

The barrier stops every ordinary push. It is not a sandbox against an agent that goes
out of its way (it runs as your user); `verify` is what makes that visible.
