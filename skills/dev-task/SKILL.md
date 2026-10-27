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

## Commands

| Verb | Command | Notes |
|---|---|---|
| start | `dev-agent start NAME [--label L] --asked "..."` | New cloud session via the deployment. The spend budget lives on the deployment (a session can only get one at creation). |
| send | `dev-agent send NAME "<task block>" [--label L] [--session SID] [--new] --asked "..."` | Cloud: needs an idle tracked session (`--new` starts one). Never creates one implicitly. Local: see Local flow. |
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

1. Scratch dir under the session scratchpad: `RUN`, `CLONE=$RUN/clone`,
   `OUT=$RUN/out`. `git clone --no-hardlinks <repo> $CLONE`, then
   `git -C $CLONE remote set-url --push origin DISABLED`, then
   `git -C $CLONE checkout -b agent/<slug> origin/<base>`; note the base SHA.
2. Spawn the `dev-agent` subagent (Agent tool, subagent_type `dev-agent`) with
   the task block; pass the instance's recorded model (and effort, if set) as
   the Agent tool's `model` and `effort`: the user chose them at init. No
   opinions on the solution.
3. When it reports, run `/dev-review` on `$OUT`.
