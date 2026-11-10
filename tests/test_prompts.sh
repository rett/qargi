#!/usr/bin/env bash
# The rules a member's prompt states, each once and in the place that owns it: the contract (contract/), the role texts
# (roles/*/ROLE.md), the packs a member loads and the runtime addenda. A rule that moves or is stated twice fails here.
# Run: tests/test_prompts.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
C=contract/contract.md
has() { tr '\n' ' ' < "$1" | tr -s ' ' | grep -qiE -- "$2"; }   # has FILE PATTERN: the file holds the pattern, line breaks read as spaces (case ignored)
# the files a member's prompt is made of, apart from the contract
OTHERS=(contract/output-format.md roles/*/ROLE.md agents/member.body.md packs/skills/*/SKILL.md lib/providers/claude-code/local-run.md)

# P1: reports and commit messages are written with the file tool; the shell is not a fallback
has $C 'file-writing tool' && has $C 'git commit -F FILE' && ok "the contract says to write outputs and commit messages with the file tool and commit with -F FILE" || no "the contract names the file tool and git commit -F FILE"
! has $C 'use the shell' && ! has $C 'shell \(a heredoc\)' && ok "the contract does not send a refused write tool to the shell" || no "the contract still falls back to a shell heredoc"
has $C 'final message' && ok "the contract says a read-only role whose file tool is refused reports in its final message" || no "the contract names the final-message fallback"
has $C 'guard refusal is a result' && ok "the contract says a guard refusal is reported, not worked around" || no "the contract says to report a guard refusal"
rest=$(grep -liE 'heredoc|commit -F|-F FILE|cuts a command' "${OTHERS[@]}" || true)
[ -z "$rest" ] && ok "no other prompt text repeats the heredoc and commit-message rules" || no "these texts repeat a rule the contract states: $rest"
if python3 -I -c 'import json,sys; sys.exit("heredoc" in json.load(open("lib/providers/claude-code.json"))["notes"]["member-out"])'; then ok "the member-out note does not name a heredoc"; else no "the member-out note still names a heredoc"; fi

# P2: a member never stashes and is told what to do instead; no text sends it to a WIP commit
has $C 'git worktree add' && has $C 'git restore' && has $C 'nothing to set aside' && ok "the contract says how to see BASE and how to drop an experiment instead of stashing" || no "the contract names git worktree add and git restore"
! has $C 'WIP' && ! grep -qE 'WIP commit|git stash' "${OTHERS[@]}" && ok "no prompt text sends a member to a WIP commit or repeats the stash rule" || no "a WIP commit or a stash rule is still stated outside the contract's one sentence"

# P3: SCOPE is one instruction (stay inside; BLOCKED naming the path; the rest in noticed_not_acted_on), checked by `review check`
has $C 'SCOPE lists the only paths' && has $C 'git diff --name-only BASE_SHA' && has $C 'report BLOCKED naming the path' && has $C 'noticed_not_acted_on' && ok "the contract gives one SCOPE instruction: compare, BLOCKED naming the path, noticed_not_acted_on" || no "the contract's SCOPE instruction"
! grep -rqE 'Needs from the lead|SCOPE is a hard limit' contract packs/skills roles agents && ok "no second SCOPE instruction (Needs from the lead, a hard limit) is left" || no "a second SCOPE instruction is left"
! grep -qE 'Stay inside SCOPE' packs/skills/gitflow-member/SKILL.md && ok "gitflow-member leaves SCOPE to the contract" || no "gitflow-member repeats the SCOPE rule"

# P9: the manifest's required keys are named in the output format and shown in the example
req=$(python3 -I -c 'import re; t=open("contract/output-format.md").read(); m=re.search(r"required keys: (.*?)Other keys", t, re.S); print(" ".join(re.findall(r"\b(status|base|done|gates|commits|scope|touched_paths)\b", m.group(1))))')
want="status base done gates commits scope touched_paths"
[ "$req" = "$want" ] && ok "the output format names the required manifest keys ($want)" || no "required keys in the output format: '$req'"
if python3 -I -c 'import json,sys; m=json.load(open("contract/manifest.example.json")); sys.exit(0 if all(k in m for k in sys.argv[1:]) and m["status"] in ("DONE","BLOCKED") and m["gates"] and m["commits"] else 1)' $want; then ok "contract/manifest.example.json is valid and holds every required key"; else no "contract/manifest.example.json is missing a required key"; fi

# P4: claims and cadence
has $C 'Record each check in `log.txt`' && has $C 'Report only what you ran' && has $C '`not run` with the reason, never `pass`' && ok "the contract says to log each check, report only what was run, and that an unrun check is not run, never pass" || no "the contract's rule on recording and claiming checks"
has $C 'Commit as you go' && has $C 'sent back' && ok "the contract says to commit as you go and that a batch at the end is sent back" || no "the contract's commit-as-you-go rule"

# P5: one review vocabulary, in every text that describes a report
F=contract/output-format.md
has $F 'severity high\|medium\|low' && has $F '# Checked' && has $F 'ends with one line: `verdict: accept` or `verdict: revise`' && ok "the output format gives the report shape: severity high|medium|low, # Checked, a last verdict line" || no "the output format's read-only paragraph"
for f in roles/review/ROLE.md packs/skills/review-findings/SKILL.md provision/role-seeds/review/reference/conventions/findings.md; do
  has $f '`verdict: accept` or `verdict: revise`' && has $f 'medium' && has $f '# Checked' && ok "$f uses the report words: high/medium/low, # Checked, the verdict line" || no "$f does not use the report words"
done
has provision/role-seeds/review/reference/workflow/workflow.md 'last line `verdict: accept` or `verdict: revise`' && ok "the review workflow ends the report with the verdict line" || no "the review workflow names the verdict line"
bad=$(grep -rlE 'CONFIRMED|PLAUSIBLE|not ready|ready with changes|High, Medium|\*\*High' roles packs/skills provision/role-seeds contract agents skills || true)
[ -z "$bad" ] && ok "no review text keeps another vocabulary (CONFIRMED, PLAUSIBLE, not ready, ready with changes, capitalised severities)" || no "another review vocabulary in: $bad"

# P6: the advisor sign-off is a run: prepared, given a full task block, taken in with review check, closed with local clean
FL=skills/qargi-flow/SKILL.md
has $FL 'qargi local prepare --role review --profile advisor' && has $FL 'full task block' && has $FL 'DONE "OUT/report.md ends with a verdict line"' && has $FL 'qargi review check OUT' && has $FL 'qargi local clean' && ok "the advisor sign-off prepares a review run, gives it a full task block, checks and closes it" || no "the advisor sign-off step of qargi-flow"
! has $FL 'spawn it on that file' && ok "the advisor is not spawned on a bare file" || no "qargi-flow still spawns the advisor on a file with no run"

exit $fail
