# Supervisor for stalled agents (design draft 1)

Status: draft for review. Nothing here is implemented. Decisions the owner made are marked **Decided**;
the rest is a proposal from a design analysis whose documentation facts were read on 2026-10-30 and are
not all verified. A fact I checked myself is marked **Verified**.

## Requirement

"Agents stalling out, it would be nice to have a supervisor/marshal that can poke a sleeping agent session
or trigger a user notification to address a pressing matter." In the owner's experience it is mostly local
Claude Code subagents that stall; they have not used the cloud agents enough to have an opinion.

## What is true today

- **Verified:** qargi's tracker (`sessions.json`) holds cloud sessions only (`lib/session.sh`, "sessions are
  cloud only"). Local subagent runs leave no record except their run directory and the agent's final
  `manifest.json`. So qargi cannot see local stalls at all.
- **Verified:** the cloud session object has no `stop_reason` key. `trk_refresh` and `watch.sh` read it
  from the session, so the tracker's `stop_reason` is empty on every row. The reason lives on the
  `session.status_idle` event (`stop_reason.type`, observed `end_turn`, plus `stop_details`).
- **Verified:** a session stopped by `user.interrupt` also reports `end_turn`, so qargi must record that it
  sent the interrupt to tell "finished" from "stopped by us".
- A local background agent can end its turn while its own background command still runs; the harness then
  reports an interim result and the agent reports again later. Duplicate or interim reports are not stalls.

## Decided

- **Shape.** Hooks are passive sensors: they record, never act. One idempotent `qargi supervise tick` is the
  only actor, run on a timer or a loop. The tick backs off by the adaptive-schedule rule when nothing changes.
- **Reach.** Notify first; then at most **two** nudges per run, each a fixed system template, with a cooldown
  of at least 10 minutes. Never a nudge while the run waits on an approval or has little budget left. If it
  is still stalled after the nudges, stop and salvage the partial work. A nudge is never an approval.
- **Bounds.** qargi sets conservative defaults per ability for a turn limit and a command timeout on its
  local members, overridable per task, so a hung command ends with a partial result instead of a silent
  stall. The numbers are set from measured run lengths (`qargi report`), not guessed.
- **Channels.** The terminal line now. Desktop notification, email or chat webhook and mobile push are
  recorded as future desires. Polling only: no public webhook endpoint.

## Taxonomy of "stalled" (and the signal for each)

| Class | Local signal | Cloud signal |
|---|---|---|
| finished, awaiting review | `SubagentStop`; `manifest.json` exists | `session.status_idle`, `end_turn` |
| interim: turn ended, own background work running | parent `Stop` lists a running background task; no manifest | idle while work remains open |
| waiting on approval or input | `PermissionRequest` or `Notification` (headless: the call is denied, not hung) | `requires_action` with event ids |
| hung tool | `PostToolUseFailure` timeout; no tool call for a long while | `agent.tool_use` with no matching result |
| rate limit, quota, auth | `StopFailure` error class | `rescheduling`, `session.error` |
| looping | identical tool digest repeated | repeated `agent.tool_use` digests |
| context exhaustion | compaction events | `agent.thread_context_compacted` |
| turn limit | partial result marked partial | n/a |
| budget exhausted | `--max-budget-usd` | `budget_reached` |
| crashed | subagent marked failed; `SessionEnd` | `terminated` |
| silently dead | no positive signal: only stale activity | stale `processed_at` while running |

## What to record (a run registry, one row per agent, keyed by `agent_id`, never by name)

Written by hooks without reading content: `run_id`, `agent_id`, `agent_type`, `ability`, `slug`,
`started_at`, `transcript_path`, `out_dir`, `parent_session_id`, `last_tool_at`, `tool_calls`,
`last_tool_digest` (a hash of the tool name and input, never the command text), `repeat_count`, `failures`,
`last_error_class`, `compactions`, `waiting_on`, `waiting_since`, `stop_failure`, `ended_at`,
`end_kind` (`final` or `interim`), `report_count`, `manifest_present`. Cloud rows add `stop_reason`,
`stop_event_ids`, `interrupt_sent_at`, `last_processed_at`. Derived: `last_activity_at` is the latest of the
last tool call, the transcript modification time and the output-directory modification time.

## Detection order (deterministic first)

1. `waiting_on` set: a pending ask, not a stall. 2. `end_kind` interim: wait for the second report, at most
about 35 minutes. 3. Three or more identical tool digests in a row: looping. 4. Tokens since the last commit
or output change far above the role's median: burning. 5. Stale activity beyond the threshold: suspected
dead. A model judge reads only the tail of a transcript, returns a verdict only, and is never fed back as a
prompt. Thresholds are adaptive per ability (about p90 of past gaps times 1.5, with floors) once enough
runs are recorded; a fixed floor is used until then.

## Intervention ladder

report; notify the owner; poke (a fixed template, from the system, trust below the user, never derived from
agent output, so an injected agent cannot write its own nudge); stop and salvage. Answering a pending
approval, auto-resuming and restarting are not in the first version. A hook that blocks a subagent from
stopping must not be used as a nudge, because it bypasses the budget guards.

## Where it lives

`qargi supervise tick` reads the run registry and `sessions.json`, applies the rules, writes decisions to
the audit log and updates a single writer lock. It runs under a loop while a Claude Code session is open, or
a timer otherwise. It records `last_tick_at`; the session-start hook warns if that is older than twice the
interval. Hooks append to a per-run log the tick folds in, so they never contend with it.

## Metrics

Per run: detected class, time to detect, pokes, poke outcome, false pokes (the owner marks them), tokens
after a poke, estimated wasted tokens, interim reports. Reported by `qargi report`: stall rate per ability,
median time to detect, false-poke rate (target below 10%), estimated cost saved.

## Test plan (no model)

A fake agent script emits hook payloads and touches files: finished with manifest; interim then final;
interim that never finishes; permission wait; loop; dead; rate limit; cloud fixtures for `requires_action`,
`budget_reached`, `rescheduling`, and `end_turn` after an interrupt. Assert the class, the rung, the caps
(a third nudge is refused) and the audit lines.

## Risks and deferrals

Regret if not designed now: `agent_id` as the key, `end_kind`, `interrupt_sent_at`, nudge counters and
cooldowns in the registry, the fixed origin-tagged nudge template, and a `supervisor` origin in the audit
log. Deferred: event-stream tailing, webhooks, a model judge, auto-answering any input, auto-resume,
desktop, email and mobile channels.

## Open questions

1. Which channel(s) beyond the terminal matter first once local detection works?
2. What are the initial per-ability turn limits and command timeouts? (Set after `qargi report` shows
   typical run lengths.)
3. Should a salvage after two failed nudges run `collect` automatically, or only tell the owner?
