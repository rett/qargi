# Review queue: decisions made while the owner was away (draft)

Status: written during autonomous work started 2026-10-30. Every item here is **provisional**: it was decided
by an Opus review, not by the owner, and says when to revisit it. The owner reviews this file in one read.
Nothing in it was pushed, and nothing was merged into `develop` after the memory layer and the ops work.

## Rules the autonomous work follows

1. All work is done in separate worktrees; the main checkout is never touched, because the installed tool and
   skills are symlinks into it (a checkout or an edit there is a deploy).
2. At most three unreviewed branches at a time; after that, stop and write this queue.
3. Every verified branch is committed on its own `feature/*` branch and listed below. No merges into
   `develop`, no pushes.
4. Closures are proposals: the register rows move to "proposed closed" with evidence; the owner closes them.
5. A diff that touches `skills/`, `agents/`, `guard/`, canon or `install.sh` is marked "owner review required"
   and nothing is stacked on it.
6. Stop after two consecutive failed verifications.

## Branches awaiting review

| Branch | What | Closes (proposed) | Status |
|---|---|---|---|
| `feature/guard-hardening` | guard fails closed on its own errors, denies skill-modifying verbs and writes under installed or library skill directories, removes the plan-token bypass for skill verbs | L8, L9 | in progress |
| `feature/supervisor` | hook recorders, run registry, `qargi supervise tick`, prepared nudges, printed hook snippet | L12 | in progress |

## Provisional decisions (Opus), with when to revisit

| # | Question | Decision | Revisit if |
|---|---|---|---|
| a | After two failed nudges: salvage automatically or only notify? | notify only | false-stall rate under 10% over 20 stalls, or the owner collects by hand right after notices |
| b | Cloud nudges need `--asked` | prepared only until the owner records standing permission | the owner types a standing permission (store it as an exception record) |
| c | How does a local nudge reach a subagent? | the tick writes a nudge file; the coordinating session delivers it with SendMessage and records `delivered_at` | Claude Code offers an external way to message a subagent |
| d | Guard on its own error | fail closed (exit 2) for every tool it matches; bound hook-level failures with an absolute command path and a timeout where documented | false blocks exceed about one a week |
| e | What counts as a skill directory | by realpath: the pack library, `~/.claude/{skills,agents,plugins}`, the targets of installed links, any `.claude/skills|agents` outside the clone, any `.claude/settings*.json`; allowed inside the run's clone | a member needs a scratch Claude home for tests |
| f | `noticed_not_acted_on` | collect at verify and collect time into `events.jsonl`; dispositions followup, dismissed (with a reason code), accepted, superseded; shown in `report` with age | more than about 20 per week |
| g | Initial turn limits and command timeouts | **not applied**: the owner decided "from measured run lengths". Opus suggested generous floors (command timeout 10 minutes; turns 150 build, 150 test, 80 write, 60 review) | the owner accepts floors, or `report` has 20 runs per ability |
| h | Merge autonomous work into `develop`? | no; collect verified branches on one integration branch `auto/queue` for a single review | the install uses `--copy` from tagged releases |

## Questions only the owner can answer

1. May the guard block on its own errors, accepting an occasional false block of a member? (yes or no)
2. Replace `QARGI_NESTED` with a parent plan token passed down, or remove it? (replace or remove; the builder
   will report whether any nested caller truly needs it)
3. Standing permission for supervisor cloud nudges (fixed template, at most 2 per run), and for how long?
4. Accept judgment-based turn and timeout floors now, replaced by `report` data later? (yes or no)
5. May I remove the two builder worktrees under `.claude/worktrees` (loop L19)? (yes or no)
6. Will you apply the printed supervisor hook snippet to your Claude Code settings, or should local detection
   stay file-modification-time only? (apply or mtime-only)
7. Typed memory links: build now with a canon migration, or park until you review the canon? (now or park)
8. Skill spec: review before fixtures are written, or draft fixtures against the draft? (review first or draft)
9. Core wording change (loop L11): now, or with the next release? (now or next release)
10. Should the installed tool keep following the checkout, or switch to a copy installed from tagged
    releases? (follow or copy)
