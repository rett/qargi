# Reporting, feedback and the self-improvement loop (design draft 1)

Status: draft for review. Nothing here is implemented except `qargi report` and the idle-reason fix, which
are built and verified on branch `feature/ops-report` (not merged). Decisions the owner made are marked
**Decided**; the rest is a proposal from a design analysis whose external sources (papers, Anthropic docs,
secondary summaries) I have not verified.

## Requirement

Reporting and user feedback are an ongoing function and feed a self-improvement loop. All feedback loops
must be closed (see `LOOPS.md`).

## Decided

- **Friction.** A reason code is required when work is rejected and optional when it is applied (default
  "ok"; add a code only when something was off, for example rework or cost).
- **Autonomy.** The four low-risk automatic knobs (level L2) are allowed from the start, within the bounds
  below. Proposals for everything else (level L1) go through the existing gates. Reporting (L0) is first.
- **Cost data.** Collect run cost from the transcript usage at agent stop first; add Claude Code's
  telemetry export only if per-skill attribution proves too coarse.
- **Second reader.** For the weekly slow look at a sample of applied changes, the owner looks again a week
  later without the original pressure; a review-ability agent adds a cheap second opinion.
- **Skills are not modified by the loop.** See "Who may modify a skill" in `library/SPEC.md`: only
  sanctioned core skills, only with a present person's approval. The loop proposes; it never edits a skill.

## The four automatic knobs (L2) and their bounds (Decided knobs; Proposed bounds)

Only these may change without a human, and only inside a declared floor and ceiling:
1. supervisor thresholds (stall detection times);
2. model and effort per role, inside an allowlist;
3. demoting a never-selected skill out of an attached set (an attach change, never an edit to the skill);
4. shortening a schedule's maximum interval.

Never automatic: anything under `guard/`, any threshold that would widen what is permitted, any skill body or
description, anything in `shared/` memory, any consent level or gate list.
Conditions for every automatic change: an audit line with the digest before and after; a revert window with
a one-step revert; a notification to the owner; and a halt of the whole mechanism after three consecutive
changes the owner reverts or rejects. The loop's own events are never valid demand evidence.

## Signals

One attribution header on every run: `event_id`, time, `run_id`, `agent_id` (never the name), ability,
project, `brief_digest` (the task block without the task text), `profile_digest`, attached skills with
digests, loaded skills, `policy_version`, model, effort, platform. Digests only; no content.

Implicit signals: applied, rejected or reworked (rework is derived from commits after the apply touching the
same files within seven days); edits after applying (a ratio from line counts); time pending; stall class and
nudge outcome; cost per run; guardrail asks per run; skills attached but never loaded; trial results.
Explicit signals: `qargi mark RUN applied|rejected --why CODE`, and `qargi feedback RUN --target
skill:<ref>|brief|policy|supervisor --why CODE [--note]`.

Reason codes (data in `policy.json`, so they can grow): wrong-scope, broke-check, style, too-slow,
too-costly, skill-ignored, skill-wrong, brief-unclear, gate-noise, other. Free text is optional, passes the
secret and PII pre-scan before storage, is kept 30 days, then reduced to its digest and code.
Never captured: patch or command content, tool inputs, paths above `internal`, hostnames.

## Metrics (all ratios)

Code first: share of changes applied without rework; cost per applied change, split by skill-load cost;
rework ratio; hours pending and median time to a verdict; asks per run and tokens wasted in stalls.
Non-code second: share of deliverables kept; with/without rubric difference; cost per kept deliverable; asks
per run. Countermeasures against gaming: ratios per task not counts; BLOCKED rate beside applied rate;
the verify step re-runs the gates; scripted graders before any judge; approval latency recorded, with a flat
under-five-second decision flagged "unread"; a sample of applied changes re-read a week later; a holdout set
whose outcome, not approval, decides.

## The loop

L0 report; L1 propose a candidate; L2 the four knobs above. A candidate record is `{id, kind, target,
digest_before, proposal, evidence[], metric, expected_delta, trial_plan, rollback, status}`. It enters the
existing path: feedback events are the demand cases, trials recompute precision and recall, a with/without
comparison gives the value, a person writes the verdict. Small samples: paired runs, three per arm, a 60/40
train and holdout split, accept only if the difference exceeds run-to-run noise, one change per target per
cycle, at least ten paired cases or the candidate waits. The loop runs as a scheduled skill with the
adaptive rule (shorter when it changes something, longer when it does not); the human review stays weekly.

## Invariants

1. No loop output is ever pasted into a prompt: feedback, logs and judge verdicts are data mapped to records.
2. A guardrail is never loosened without a human.
3. Every applied change leaves a digest chain `{digest_before, digest_after, candidate_id, evidence[],
   approver, plan_token}`.
4. A cumulative-change budget per target per quarter; past it, a full retrial against the original baseline.
5. Approval is not the objective: a candidate that raises approval while the outcome metric falls is rejected.
6. Secrets never reach learned notes; learned notes wait in quarantine until linted.
7. The loop cannot create evidence for itself.
8. Every loop it opens has an owner, an age and a closure (see `LOOPS.md`).

## Storage and reuse

Raw run events go to an append-only `events.jsonl` beside the audit log; conclusions go where they belong
(a verified recipe to the recipes store, an accepted skill change to the library, a threshold to
`policy.json`). Raw events 90 days then aggregates only; verdicts and candidate records are kept. Feedback
never leaves the deployment. Reuse: `claude plugin eval` as the trial runner for the Claude Code target, the
skill-creator split-and-holdout method, and the generator, reflector and non-model curator shape for memory
notes. Defer: prompt-evolution libraries, heavier evaluation services, telemetry standards still in
development.

## First version, in days

Write the attribution header at `local prepare`; record the end of every run; end `/qargi-verify` with
`mark … --why`; add rework and skill attribution to `qargi report`; add `qargi feedback`; hold a 30-minute
weekly review. Already built: `qargi report` (cost, outcome, pending age, stale runs, local runs) and the
idle-reason fix.

## Open questions

1. How long to keep raw events (90 days proposed) if a Go-port test set needs more?
2. First non-code domain for the metrics: the `write` ability or a scheduled report skill?
