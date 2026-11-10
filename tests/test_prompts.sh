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
has() { grep -qiE -- "$2" "$1"; }                     # has FILE PATTERN: the file holds the pattern (case ignored)
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

exit $fail
