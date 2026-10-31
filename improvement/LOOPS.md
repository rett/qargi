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
| L8 | The guard hook may fail open on error or timeout | assistant | proposed closed: the guard now exits 2 on any internal error (tested); `onFailure: "block"` and a timeout are set in the member definition, which the hooks documentation supports for command hooks from Claude Code 2.1.295 (the documentation does not say so explicitly for agent frontmatter: confirm on a real run); branch `feature/guard-hardening`, awaiting review | proposed closed |
| L9 | Skill-modification gate: members could run the skill verbs, write the skill directories, and `QARGI_NESTED` skipped the plan check | assistant | proposed closed for members: the verbs and the protected locations (by real path, the clone exempt) are refused and the token check no longer skips for skill and tool imports, seals and `packs apply`; still open: `new, remove, link, unlink, enable, disable` have no token, `--approved` is free text, and `QARGI_NESTED` still serves four provisioning verbs (questions queued) | partly proposed closed |
| L10 | Memory layer known gaps: (1) `canon apply` does not use the new migrate planner; (2) restoring a note whose own `Sources:` line is the placeholder text drops the line; (3) very large stores untested | assistant | (3) proposed closed 2026-10-30: a scratch store of 45 notes (over two 20-item pages) copied out intact, and written back in 37 s with a second plan of 'nothing to do'; both scratch stores archived. (2) proposed closed on `feature/memory-restore-edge`. (1) needs the owner: it touches canon, which is marked owner-review | partly proposed closed |
| L11 | Wording that says "development tasks" and "patches" in the core is not neutral | owner | decided 2026-10-30: do the wording-only change (the audit's first, non-breaking step) with the next release | decided, scheduled |
| L12 | The supervisor is designed, not built | assistant | proposed closed: built on `feature/supervisor` (hook recorders, registry, tick, caps, prepared nudges, printed snippet, report section); it detects nothing locally until you apply the printed hooks snippet to your settings, which I will not do | proposed closed |
| L13 | The self-improvement loop design is in progress | assistant and Fable | analysis, then the owner's answers, then Fable's review of the decisions | in progress |
| L14 | A cost estimate I gave for trial sessions was too low | assistant | recorded in the working notes: state estimates with a margin and report actual spend | closed |
| L15 | The tracker only refreshes a session's row when someone runs `status`, so cost and status go stale (two rows showed cost 1 and `running` for two days; true total spend was 12,144, not 9,460) | assistant | refresh on `report` and on the supervisor tick; show the row's age so staleness is visible | open |
| L16 | The ops work was verified and uncommitted in its worktree | owner | committed, rebased onto `develop`, merged; your installed `qargi` now has `report` | closed |
| L17 | The improvement-loop design is drafted (`improvement/DESIGN.md`); the owner allowed the four automatic knobs, which need their bounds written into policy before anything is built | assistant | write bounds as data when the loop is built; review the draft | open |
| L18 | `develop` is ahead of `origin/develop` by the two merges and the work under them; nothing has been pushed | owner | review, then push when ready (a push is outward-facing and yours to decide) | open |
| L19 | The five builder worktrees (`.claude/worktrees/agent-*`) and the branch pointers remain; the memory one is locked by its finished builder | assistant | owner said yes 2026-10-30, after the merge decision: remove them once `auto/queue` is merged or dropped, unlocking the memory worktree first | open, waiting on the merge decision |
| L20 | The hardened member definition (hook timeout and `onFailure`) applies only to members created after the merge; there is no refresh verb, so existing members keep the old hook | assistant | add `qargi agent refresh NAME` that re-renders a member from the current template keeping its name, abilities, model and effort; until then remove and re-add each member | open |
| L21 | The improvement loop's first version (collect `noticed_not_acted_on`, `mark --why`, the attribution header, `feedback`, refresh stale tracker rows on `report`) is waiting behind the three-branch limit and the owner-review paths | assistant | build after the three queued branches are reviewed or merged | queued |
| L22 | The installed `qargi` follows the main checkout, so every merge into `develop` deploys at once; the owner chose a copy installed from tagged releases (2026-10-30, question 10) | owner | changed 2026-10-30: the installed tool is a checkout at `/opt/qargi` (root-owned; `sudo git clone` from the local repository because `develop` is not pushed), then `/opt/qargi/install.sh --user` re-links the command and skills (no `--force` needed); update with `git -C /opt/qargi pull` or a tag; the assistant does not touch the installation. Open design gaps: no `install.sh --system`, no `qargi upgrade` | open |
| L24 | Qargi's data moves to `~/.qargi/{config,state}` with a per-checkout dev sandbox (branch `feature/qargi-home`, built and verified, not merged); merging it makes every command refuse until `qargi migrate home` is applied to the real data | owner | review the branch, then merge together with running `qargi migrate home` (plan, then apply with a typed go-ahead); the old directories stay as a backup until the owner removes them | awaiting review |
| L23 | `QARGI_NESTED` still lets `canon apply`, `seed-role`, `normalize` and `refresh-prompt` skip the plan-token check; the owner chose to replace it with a parent plan token passed down (question 2) | assistant | a builder reports first which nested callers truly need it, then replaces it; touches `lib/` and tests, so it goes on its own branch and waits for review | queued |

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
