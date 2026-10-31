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

**One combined branch: `auto/queue`** (cut from `develop`, with the three branches below merged in; no
conflicts; the man page regenerates identically; the full suite exits 0 across 27 suites). To review it:
`git diff develop...auto/queue --stat`, and to take all of it: `git switch develop && git merge --no-ff auto/queue`
(your installed `qargi` follows the checkout, so that merge deploys it). Any one branch can also be merged alone.

| Branch | What | Closes (proposed) | Status |
|---|---|---|---|
| `feature/guard-hardening` (`f4ba06f`) | guard fails closed on its own errors, denies skill-modifying verbs and writes under installed or library skill directories, removes the plan-token bypass for skill verbs | L8, L9 | `f4ba06f` verified: suite exit 0, 26 suites; a member may edit its own clone including `.claude/skills`, and a symlink out of the clone, the pack library, `~/.claude/{skills,agents,plugins}` and a project's installed `.claude/skills` are refused (I tested each); 45 plus 10 mutations killed; owner review required: it touches `agents/` and the guard |
| `feature/supervisor` (`447b4e2`) | hook recorders, run registry, `qargi supervise tick`, prepared nudges, printed hook snippet, a supervisor section in `report` | L12 (proposed closed) | verified: suite exit 0, 27 suites; hook handlers exit 0 on garbage and store no text (hostile payload tested); 35 mutations, all caught or equivalent; nothing installed in your settings |
| `feature/memory-restore-edge` (`ecb86d0`) | a note whose own `Sources:` line is the placeholder text round-trips exactly through archive and restore, no format change | L10 (2) (proposed closed) | verified: suite exit 0, 26 suites; 7 of 8 mutations caught, the survivor is equivalent |

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

### Owner answers (2026-10-30, typed in chat)

After the review pass of `auto/queue` (suite re-run on an exported copy: 27 steps, exit 0) the owner wrote
"answer the ten questions as recommended". The recommendations were these; they are the owner's answers now.

| # | Answer | What it means |
|---|---|---|
| 1 | yes | the guard may refuse on its own errors; revisit if false blocks exceed about one a week |
| 2 | replace | `QARGI_NESTED` becomes a parent plan token passed down; queued as L23, not urgent (the guard already stops a member setting it) |
| 3 | not yet | cloud nudges stay prepared only; revisit with real stall data |
| 4 | not yet | no turn or timeout floors until `report` has about 20 runs per ability |
| 5 | yes, after the merge decision | the five builder worktrees (not two) stay until the owner decides on `auto/queue`; unlock the memory one first (L19) |
| 6 | mtime-only | local detection stays file-modification-time only until the owner applies the printed hooks snippet; the assistant never edits the settings |
| 7 | park | typed memory links wait for the owner's canon review |
| 8 | review first | no skill-spec fixtures before the owner approves the spec |
| 9 | next release | the core wording change (L11) ships with the next release |
| 10 | copy | the installed tool should come from a copy of a tagged release; the switch is the owner's to run (L22) |

**Not decided by these answers:** merging `auto/queue` into `develop` and pushing `develop`. Both stay the
owner's explicit words. The builders' saved questions below are still open.

## Questions the builders saved for you

**Supervisor**
- The printed cloud nudge is `qargi supervise nudge SID --asked "<your words>"`, not a bare send, so the caps and
  count live in one place. Keep that, or print the literal send line?
- A registered local run that no hook has reported on gets a placeholder row. Keep those, or supervise only runs
  that hooks reported on?
- Old registry runs older than 7 days are ignored. Is 7 days right?
- Which channel comes after the terminal line (desktop notification, email or chat webhook, mobile push)?
- After two failed nudges the tick only prints `salvage`; it never runs `collect`. (Provisional: keep.)
- Local detection is quiet unless you apply the printed hooks snippet to your Claude Code settings. Apply it or
  stay mtime-only? (Also asked above.)

**Guard hardening**
- `skill|tool new|remove|link|unlink|enable|disable` have no plan-token gate at all, and `--approved` is free
  text everywhere. Only the existing tokens were protected from the `QARGI_NESTED` skip. Adding tokens to the
  other verbs changes `discover install` and its tests: yours to decide.
- Input that is not JSON still passes the guard (a hook payload is always JSON). Refuse it instead?
- `QARGI_NESTED` still lets `canon apply`, `seed-role`, `normalize` and `refresh-prompt` skip the token check;
  the guard stops a member from setting it. Removing it entirely needs a narrower mechanism.
- Not built: a `qargi local verify` check that hashes the pack library before and after a run.
- To confirm on a real Claude Code run: `onFailure: "block"` in an agent's frontmatter hook. The documentation
  (https://code.claude.com/docs/en/hooks) says frontmatter hooks use the same format as settings hooks and that
  `onFailure` needs Claude Code 2.1.295 or later (you have 2.1.314), but it does not say so for frontmatter
  explicitly. Frontmatter hooks of a project agent also run only after the folder is trusted.

**Memory restore edge**
- Add a visible "inserted by qargi" marker for human readers? It would change the format; left out.

**Process**
- The builders shared one scratch directory and overwrote each other's files; later builders get their own
  subdirectory.

## What I stopped on, and why

Three verified branches await review and the guard touches the paths marked for owner review, so I did not
stack more work on top (the safeguards above). Waiting behind that: the improvement loop's first version
(loop L21), a refresh verb for existing members (L20), and the items that are yours to schedule (typed memory
links, the skill-spec fixtures, the core wording change, `canon apply` through the new executor, removing the
builder worktrees).
