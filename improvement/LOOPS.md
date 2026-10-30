# Closed loops and the open-loop register (draft 1)

Status: draft for review. Nothing here is implemented.

## Principle (Decided, from the owner)

All feedback loops must be closed, and we purposely look for open ones and offer ways to close them.

**A loop** is any signal, decision, proposal, alert, approval, question or follow-up that something produces
and expects someone or something to act on. **A loop is closed** only when an outcome is recorded: decided,
applied, rejected, expired into skip, superseded, or fixed and verified. "Recorded" and "noticed" are not
closed. An open loop is not a failure; an open loop with no owner and no age is.

## Design rule for every producer of a signal

Before a signal, field, log or alert is added, name: its **consumer** (who or what reads it), the **action**
that follows, the **evidence** that the action worked, and its **aging** (when an unclosed instance becomes
an alert). A signal with no consumer is removed or given one. Review this at design time and in the
periodic loop audit below.

## The register

| Id | Open loop | Owner | How to close it | State |
|---|---|---|---|---|
| L1 | Memory backend work was committed on `feature/memory-backends`, not merged | owner | merged into `develop` on 2026-10-30 with the ops work rebased on top; suite exit 0 (26 suites); local only, not pushed | closed |
| L2 | The five design drafts and the skill spec await review | owner | review, then approve; fixtures follow approval | open |
| L3 | 18 open questions across the drafts | owner | answer in one pass, grouped as needed-now, needed-when-built, parked (see below) | open |
| L4 | Five cloud sessions waiting on the owner (another project) | owner | checked on 2026-10-30: all 31 patches are in the repository (25 identical diffs, 6 with a same-subject commit and 76-99% of lines present; the gaps are release-time edits); marked applied and archived; cloud shows archived_at for each | closed |
| L5 | `noticed_not_acted_on` in agent manifests is written and never read | builder (in the verify and report path) | collect these notes in `qargi-verify` and `qargi report`, with a disposition per item: file a follow-up, dismiss, or accept; age unanswered ones | open |
| L6 | The idle stop reason was read from a field that does not exist, so it was empty everywhere | ops builder | fixed to read the idle event; verified; merged into `develop` | closed |
| L7 | Trial cost and turns were not in the spec | assistant | recorded in the trial result (above) | closed |
| L8 | The guard hook may fail open on error or timeout (claim from the docs, not yet re-read) | assistant | read the current hooks documentation; if confirmed, set the hook to block on failure for members; test | open |
| L9 | Skill-modification gate: the member guard has no rule against the skill verbs; `QARGI_NESTED` skips the plan check in `packs.sh` | assistant | add the guard rule; remove the bypass for those verbs; test | queued |
| L10 | Memory layer known gaps: `canon apply` does not use the new migrate planner; restoring a note whose own `Sources:` line is the placeholder text drops the line; very large stores are untested | assistant | decide per item: fix, document as a limit, or test at scale on a scratch store | open |
| L11 | Wording that says "development tasks" and "patches" in the core is not neutral | owner | decide when to do the wording-only change (the audit's first, non-breaking step) | open |
| L12 | The supervisor is designed, not built; it needs the run registry and the idle-reason fix first | assistant | build after the ops builder lands | queued |
| L13 | The self-improvement loop design is in progress | assistant and Fable | analysis, then the owner's answers, then Fable's review of the decisions | in progress |
| L14 | A cost estimate I gave for trial sessions was too low | assistant | recorded in the working notes: state estimates with a margin and report actual spend | closed |
| L15 | The tracker only refreshes a session's row when someone runs `status`, so cost and status go stale (two rows showed cost 1 and `running` for two days; true total spend was 12,144, not 9,460) | assistant | refresh on `report` and on the supervisor tick; show the row's age so staleness is visible | open |
| L16 | The ops work was verified and uncommitted in its worktree | owner | committed, rebased onto `develop`, merged; your installed `qargi` now has `report` | closed |
| L17 | The improvement-loop design is drafted (`improvement/DESIGN.md`); the owner allowed the four automatic knobs, which need their bounds written into policy before anything is built | assistant | write bounds as data when the loop is built; review the draft | open |
| L18 | `develop` is ahead of `origin/develop` by the two merges and the work under them; nothing has been pushed | owner | review, then push when ready (a push is outward-facing and yours to decide) | open |
| L19 | The two builder worktrees (`.claude/worktrees/agent-*`) and the branch pointers remain; the memory one is locked by its finished builder | assistant | remove them after the owner confirms the merge, unlocking the memory worktree first | open |

## The open questions, grouped

**Needed before the next code-development step:** the supervisor's initial per-ability turn limits and command
timeouts (set from `qargi report` data once it exists); whether a salvage after two failed nudges collects
automatically or only tells the owner; whether a refused memory note should ever be skipped with a warning
instead of refusing the whole plan.

**Needed when the component is built (guardrails engine, connectors, skill validator):** whether any run may
use unrestricted networking while it reads data above `internal`; which non-code effect class ships first;
whether `human` verification suffices for an unattended run that ends in an external deliverable; who answers
a cloud approval and the expiry (15 minutes proposed); which data classes agents will handle; the first three
connector providers; whether a deployment may host a public HTTPS document; whether enterprise-managed
authorization is a requirement; what counts as money-moving; the signing envelope, identity proof for live
task exchange and catalog archive format (federation).

**Parked until the frontend and inbound API:** personal or shared deployments for the phone; internet
reachability; push relay; languages; text rendering of widgets in the CLI; Markdown policy.

## The loop audit (Proposed)

A periodic pass, a skill-shaped procedure run by a sanctioned skill and reviewed by the owner, that reads the
register, `qargi report`, the audit log and the drafts, and lists: signals with no consumer, loops older than
their aging threshold, proposals with no outcome, approvals that expired, alerts nobody acknowledged,
questions that block something already built, and metrics with no owner. Its output is a short list with a
suggested closure each; it never closes a loop on its own. Cadence follows the adaptive schedule: weekly while
things change, backing off when a pass finds nothing new.

## What closing looks like per kind of loop

| Loop kind | Closed by |
|---|---|
| Alert or notification | acknowledged, or expired into an escalation, never silently dropped |
| Approval request | decided, or expired into skip; the outcome is recorded |
| Agent observation (`noticed_not_acted_on`) | a disposition: follow-up filed, dismissed, or accepted |
| Feedback on a run | linked to the run, skill and prompt versions, and counted in a review |
| Improvement proposal | trialled, then approved or rejected, with the result recorded against the digest |
| Open question | answered and written into the draft, or explicitly parked with a trigger |
| Bug or limit | fixed with a test, or documented as a limit with an owner |
| Pending review of finished work | applied, rejected, or closed with a reason |
