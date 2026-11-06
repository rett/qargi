#!/usr/bin/env bash
# What a lead does while a run is out, and what verify and finish say about it:
#   - the lead's own new branches and pushes are accepted once the lead noted them (ref note); the harness's bridge worktree branches are left out;
#     a ref the run's agent could have made or moved, and was not noted, is still found
#   - local close --applied-by-am closes a run whose patches the lead applied by hand: it is no longer open (compact-check, feature finish, marshal status)
#   - local verify says "OUT is empty" when the member did not collect
#   - feature finish is refused while a run of the feature is open
# Run: tests/test_runs_close.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_LEAD=lead HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm QARGI_PROJECT=app
export GIT_AUTHOR_NAME=lead GIT_AUTHOR_EMAIL=lead@example.net GIT_COMMITTER_NAME=lead GIT_COMMITTER_EMAIL=lead@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scr"
J=$T/s/ref-journal.jsonl; Z=0000000000000000000000000000000000000000
A=$T/app; git init -q -b master "$A"; git init -q --bare "$T/origin.git"
mkdir -p "$A/internal"; echo 0.1.0 > "$A/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$A/CHANGELOG.md"; echo a > "$A/internal/a.go"
git -C "$A" add -A && git -C "$A" commit -q -m base && git -C "$A" branch develop && git -C "$A" remote add origin "$T/origin.git" && git -C "$A" push -q origin master develop
git -C "$A" checkout -q -b parked
jq -n --arg p "$A" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
mkrun() { $DA local prepare --repo "$A" --base "${2:-develop}" --slug "$1" --scratch "$T/scr" | sed -n 's/^RUN=//p'; }
verify() { $DA local verify "$1" 2>&1; }
hand() { git -C "$A" commit-tree -p "$1" -m "by hand" "$1^{tree}"; }
mk() { GIT_AUTHOR_DATE="2026-10-27T10:00:00" GIT_COMMITTER_DATE="2026-10-27T10:00:00" git commit -q -m "$1" -m "$2"; }
# commits RUN FILE: one commit in the run's clone (the member worked), nothing collected
commits() { ( cd "$1/clone" || exit 1; echo x >> "internal/$2"; git add -A; mk "change $2" "The $2 file changes." ); }
# collect RUN: patches, a manifest and a report in OUT
collect() {
  local r=$1 base
  base=$(git -C "$r/clone" rev-parse "origin/develop")
  mkdir -p "$r/out/patches"; git -C "$r/clone" format-patch -q -o "$r/out/patches" "$base..HEAD"
  git -C "$r/clone" log --reverse --format='%H%x09%s' "$base..HEAD" | jq -R -s -c '
    [split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})),
       patch_groups:[{name:"g", why:"one change", commits:($c|map(.sha))}]}' > "$r/out/manifest.json"
  echo "# series" > "$r/out/series.md"
}

# --- 3. verify says plainly that the member did not collect
R=$(mkrun nocollect)
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && ok "(setup) a run with no commits and an empty OUT verifies: nothing to collect" || no "empty run: rc=$rc $out"
commits "$R" a1.go; rm -f "$R/verified"
out=$(verify "$R"); rc=$?
[ $rc = 1 ] && grep -q "OUT is empty: the member did not collect" <<<"$out" && grep -q "ls OUT/patches" <<<"$out" && ok "verify fails fast, naming the missing collect, when the clone has commits and OUT is empty" || no "uncollected: rc=$rc $out"
[ ! -f "$R/verified" ] && ok "and records nothing" || no "verified written for an uncollected run"
collect "$R"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && ok "after the member collects, verify passes" || no "collected: rc=$rc $out"
out=$($DA local clean "$R" --discard 2>&1); rc=$?
[ $rc = 0 ] && ok "(setup) clean --discard still drops a run" || no "discard: rc=$rc $out"
R=$(mkrun reportonly); echo "# report" > "$R/out/report.md"; commits "$R" a2.go
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && ok "a report in OUT is a collect too (the check is for patches or a report)" || no "report only: rc=$rc $out"
out=$($DA local clean "$R" --discard 2>&1)
R=$(mkrun nocollect2); commits "$R" a3.go
out=$($DA local clean "$R" --discard 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q "OUT is empty" <<<"$out" && ok "clean --discard of an uncollected run does not call it a refs change or an empty OUT" || no "discard uncollected: rc=$rc $out"

# --- 1a. the harness's bridge worktree and branch
R=$(mkrun bridge)
mkdir -p "$A/.claude/worktrees"
git -C "$A" worktree add -q -b worktree-bridge-cse_x1 "$A/.claude/worktrees/bridge-cse_x1" develop
git -C "$A" worktree lock --reason "claude agent bridge-cse_x1" "$A/.claude/worktrees/bridge-cse_x1"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -q "worktree-bridge-cse_x1 created" <<<"$out" && ok "verify leaves out a worktree-bridge-* branch held by its bridge worktree, and names it" || no "bridge: rc=$rc $out"
R=$(mkrun bridge2)
git -C "$A" branch worktree-bridge-lonely develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-lonely" <<<"$out" && ok "a worktree-bridge-* branch that no bridge worktree holds is still found" || no "lonely bridge branch: rc=$rc $out"
R=$(mkrun bridge3)
git -C "$A" worktree add -q -b worktree-bridge-other "$A/.claude/worktrees/elsewhere-other" develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-other" <<<"$out" && ok "nor is one whose worktree is not .claude/worktrees/bridge-NAME" || no "other worktree: rc=$rc $out"
git -C "$A" worktree remove --force "$A/.claude/worktrees/elsewhere-other"; git -C "$A" branch -D worktree-bridge-other worktree-bridge-lonely >/dev/null
R=$(mkrun bridge4)
mkdir -p "$T/outside/worktrees"
git -C "$A" worktree add -q -b worktree-bridge-y "$T/outside/worktrees/bridge-y" develop
git -C "$A" worktree lock --reason "member" "$T/outside/worktrees/bridge-y"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-y" <<<"$out" && ok "nor is a locked worktree bridge-NAME outside <main worktree>/.claude/worktrees" || no "outside worktree: rc=$rc $out"
git -C "$A" worktree unlock "$T/outside/worktrees/bridge-y"; git -C "$A" worktree remove --force "$T/outside/worktrees/bridge-y"; git -C "$A" branch -D worktree-bridge-y >/dev/null
R=$(mkrun bridge5)
git -C "$A" worktree add -q -b worktree-bridge-open "$A/.claude/worktrees/bridge-open" develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-open" <<<"$out" && ok "nor is a worktree bridge-NAME that is not locked" || no "unlocked worktree: rc=$rc $out"
git -C "$A" worktree remove --force "$A/.claude/worktrees/bridge-open"; git -C "$A" branch -D worktree-bridge-open >/dev/null
B0=$(git -C "$A" rev-parse worktree-bridge-cse_x1)
R=$(mkrun bridge6)
git -C "$A" update-ref refs/heads/worktree-bridge-cse_x1 "$(git -C "$A" commit-tree -m rewritten "$B0^{tree}")"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-cse_x1" <<<"$out" && ok "a rewrite of the bridge branch (not a fast-forward) is found, though its worktree holds it" || no "bridge rewrite: rc=$rc $out"
git -C "$A" update-ref refs/heads/worktree-bridge-cse_x1 "$B0"
R=$(mkrun bridge7)
git -C "$A" update-ref refs/heads/worktree-bridge-cse_x1 "$(git -C "$A" commit-tree -p "$B0" -m ahead "$B0^{tree}")"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -q "worktree-bridge-cse_x1 moved" <<<"$out" && ok "a fast-forward of the bridge branch is the harness's" || no "bridge fast-forward: rc=$rc $out"
git -C "$A" update-ref refs/heads/worktree-bridge-cse_x1 "$B0"
R=$(mkrun bridge8)
git -C "$A" update-ref -d refs/heads/worktree-bridge-cse_x1
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "worktree-bridge-cse_x1" <<<"$out" && ok "a deletion of the bridge branch while its worktree is still there is found" || no "bridge deletion: rc=$rc $out"
git -C "$A" update-ref refs/heads/worktree-bridge-cse_x1 "$B0"
git -C "$A" worktree add -q -b worktree-bridge-gone "$A/.claude/worktrees/bridge-gone" develop
git -C "$A" worktree lock --reason "claude agent bridge-gone" "$A/.claude/worktrees/bridge-gone"
R=$(mkrun bridge9)
git -C "$A" worktree unlock "$A/.claude/worktrees/bridge-gone"; git -C "$A" worktree remove --force "$A/.claude/worktrees/bridge-gone"; git -C "$A" branch -D worktree-bridge-gone >/dev/null
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -q "worktree-bridge-gone deleted" <<<"$out" && ok "the deletion of a bridge branch whose worktree is gone is the harness's" || no "bridge removed: rc=$rc $out"

# --- 1b. a branch the lead made or pushed
R=$(mkrun lead-branch)
git -C "$A" branch feature/mine develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/feature/mine" <<<"$out" && ok "(setup) a branch the lead made by hand is found by verify before it is noted" || no "unnoted branch: rc=$rc $out"
out=$($DA ref note feature/mine 2>&1); rc=$?
[ $rc = 0 ] && grep -q "noted feature/mine: created at" <<<"$out" && ok "ref note journals the branch" || no "note: rc=$rc $out"
jq -e 'select(.verb == "ref:note" and .ref == "refs/heads/feature/mine" and .old == "'$Z'")' "$J" >/dev/null && ok "the journal line starts at an absent ref (verb ref:note)" || no "journal: $(tail -2 "$J")"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -q "feature/mine created by qargi ref note" <<<"$out" && ok "after the note verify passes and names the note" || no "noted branch: rc=$rc $out"
# a push
R=$(mkrun lead-push)
git -C "$A" push -q origin feature/mine
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "ref of origin created: refs/heads/feature/mine" <<<"$out" && ok "(setup) the lead's git push of a new branch is found before it is noted" || no "unnoted push: rc=$rc $out"
out=$($DA ref note origin/feature/mine 2>&1); rc=$?
[ $rc = 0 ] && grep -q "noted origin/feature/mine: created at" <<<"$out" && ok "ref note origin/NAME journals the branch of origin (asked live)" || no "note origin: rc=$rc $out"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -q "feature/mine on origin created by qargi ref note" <<<"$out" && ok "after the note verify passes: nothing was pushed by the run" || no "noted push: rc=$rc $out"
# a second push of the same branch continues the line
R=$(mkrun lead-push2)
git -C "$A" update-ref refs/heads/feature/mine "$(hand feature/mine)"
git -C "$A" push -q origin feature/mine
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && ok "(setup) a second push moves the branch of origin and its local tip: found before it is noted" || no "second push: rc=$rc $out"
out=$($DA ref note feature/mine origin/feature/mine 2>&1); rc=$?
[ $rc = 0 ] && [ "$(grep -c "after your earlier note" <<<"$out")" = 2 ] && ok "a second note continues from the first" || no "second note: rc=$rc $out"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && ok "and the run, prepared before both pushes, verifies" || no "second noted: rc=$rc $out"
out=$($DA ref note feature/mine 2>&1); rc=$?
[ $rc = 0 ] && grep -q "nothing to note" <<<"$out" && ok "noting a ref that has not moved since the last note changes nothing" || no "renote: rc=$rc $out"
# the barrier: what is not noted, and what existed before, is still found
git -C "$A" branch feature/pre develop
R=$(mkrun barrier)
git -C "$A" branch agent-made develop; git -C "$A" push -q origin agent-made
git -C "$A" update-ref refs/heads/feature/pre "$(hand feature/pre)"
out=$($DA ref note feature/pre 2>&1)
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/agent-made" <<<"$out" && grep -q "ref of origin created: refs/heads/agent-made" <<<"$out" && ok "a branch and a branch of origin nobody noted are still found" || no "unnoted: rc=$rc $out"
[ $rc = 2 ] && grep -q "branch moved: refs/heads/feature/pre" <<<"$out" && ok "and so is a branch that existed when the run was prepared and moved, though it was noted: a note starts at an absent ref" || no "moved existing: rc=$rc $out"
out=$($DA ref note nosuch 2>&1); rc=$?
[ $rc = 1 ] && grep -q "no branch nosuch" <<<"$out" && ok "ref note refuses a branch that does not exist" || no "nosuch: rc=$rc $out"
out=$($DA ref note origin/nosuch 2>&1); rc=$?
[ $rc = 1 ] && grep -q "origin has no branch nosuch" <<<"$out" && ok "and a branch origin does not have" || no "origin nosuch: rc=$rc $out"
out=$($DA ref note 2>&1); rc=$?
[ $rc = 2 ] && ok "ref note without a REF is a usage error" || no "no ref: rc=$rc $out"
git -C "$A" branch -D agent-made >/dev/null; git -C "$A" push -q origin :agent-made

# --- 2. local close --applied-by-am
for r in "$T"/scr/qargi.*; do $DA local clean "$r" --discard >/dev/null 2>&1; done
$F start cl >/dev/null 2>&1
R=$(mkrun closed-run feature/cl); commits "$R" b1.go; collect "$R"
out=$($DA local close "$R" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "no passing verify" <<<"$out" && ok "close is refused for a run that was never verified" || no "close unverified: rc=$rc $out"
out=$($DA local close "$R" 2>&1); rc=$?
[ $rc = 2 ] && ok "close without --applied-by-am is a usage error" || no "close no flag: rc=$rc $out"
out=$(verify "$R"); [ $? = 0 ] || no "(setup) verify: $out"
out=$($DA lead compact-check --project app 2>&1); rc=$?
[ $rc = 1 ] && grep -q "a local run is verified and not applied: $R" <<<"$out" && grep -q "qargi local close $R --applied-by-am" <<<"$out" && ok "(setup) a verified run is open for compact-check, which names the way to close it" || no "compact-check: rc=$rc $out"
# applied by hand
git -C "$A" checkout -q parked 2>/dev/null
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q --detach "$w" feature/cl
git -C "$w" am -q "$R"/out/patches/*.patch && git -C "$A" update-ref refs/heads/feature/cl "$(git -C "$w" rev-parse HEAD)"; git -C "$A" worktree remove --force "$w"
out=$($DA local close "$R" --applied-by-am 2>&1); rc=$?
[ $rc = 0 ] && grep -q "closed $R" <<<"$out" && [ -d "$R/clone" ] && [ -d "$R/out" ] && ok "close marks the run and keeps its files" || no "close: rc=$rc $out"
reg=$T/s/local-runs.jsonl
jq -e --arg r "$R" 'select(.run == $r and .closed_by == "applied-by-am" and (.closed | length) > 0)' "$reg" >/dev/null && ok "the lead's registry records it (closed, closed_by)" || no "registry: $(tail -1 "$reg")"
out=$($DA local close "$R" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "closed already" <<<"$out" && ok "a run is closed once" || no "close twice: rc=$rc $out"
out=$($DA lead compact-check --project app 2>&1)
grep -q "$R" <<<"$out" && no "a closed run is still an open run for compact-check: $out" || ok "compact-check no longer lists the closed run (not verified-and-not-applied)"
grep -q "open runs: none" <<<"$out" && ok "and the restart block says no run is open" || no "restart block: $out"
out=$($DA local list --scratch "$T/scr" 2>&1)
grep -E "closed-run +[0-9a-z?]+ +closed +- " <<<"$out" >/dev/null && ok "local list shows the run as closed" || no "list: $out"
out=$($DA marshal status cl 2>&1)
grep -q "closed (applied by hand): closed-run" <<<"$out" && ! grep -q "$R  closed-run" <<<"$out" && ok "marshal status lists it as closed, not as a task" || no "marshal status: $out"
out=$($DA review apply "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "this run was closed" <<<"$out" && [ -z "$(git -C "$A" branch --list agent/closed-run)" ] && ok "review apply refuses a closed run: its patches are not applied a second time" || no "apply closed: rc=$rc $out"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "cleaned $R" <<<"$out" && ok "clean removes a closed run without asking for an applied tip" || no "clean closed: rc=$rc $out"
# a read-only run is not closed this way, and a discarded or cleaned run does not block finish
R2=$(mkrun ro-run feature/cl); echo "# report" > "$R2/out/report.md"; echo read-only > "$R2/class"
out=$($DA local close "$R2" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "read-only run" <<<"$out" && ok "close refuses a read-only run" || no "close read-only: rc=$rc $out"
$DA local clean "$R2" --discard >/dev/null 2>&1

# --- 4. feature finish is refused while a run of the feature is open
$F start fn >/dev/null 2>&1
R=$(mkrun fin-run feature/fn); commits "$R" c1.go; collect "$R"
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "feature fn has 1 open run(s)" <<<"$out" && grep -q "$R (build fin-run): prepared, not verified" <<<"$out" && ok "a prepared run is open: feature finish is refused" || no "prepared open: rc=$rc $out"
verify "$R" >/dev/null
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "feature fn has 1 open run(s)" <<<"$out" && grep -q "$R (build fin-run): verified, not applied" <<<"$out" && grep -q "qargi local close RUN --applied-by-am" <<<"$out" && grep -q "qargi local clean RUN" <<<"$out" && grep -q "Nothing was changed" <<<"$out" \
  && ok "feature finish is refused, with the open run listed and the way to close it" || no "finish with open run: rc=$rc $out"
$F start ot >/dev/null 2>&1
out=$($F finish ot 2>&1); grep -q "open run" <<<"$out" && no "a run of feature/fn blocks another feature: $out" || ok "an open run of one feature does not block another"
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$A" worktree add -q --detach "$w" feature/fn
git -C "$w" am -q "$R"/out/patches/*.patch && git -C "$A" update-ref refs/heads/feature/fn "$(git -C "$w" rev-parse HEAD)"; git -C "$A" worktree remove --force "$w"
$DA local close "$R" --applied-by-am >/dev/null 2>&1
out=$($F finish fn 2>&1)
grep -q "open run" <<<"$out" && no "a closed run still blocks finish: $out" || ok "a run closed with --applied-by-am does not block finish"
R2=$(mkrun disc-run feature/fn)
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "1 open run(s)" <<<"$out" || no "(setup) a new run is open: rc=$rc $out"
$DA local clean "$R2" --discard >/dev/null 2>&1
out=$($F finish fn 2>&1)
grep -q "open run" <<<"$out" && no "a discarded run still blocks finish: $out" || ok "a discarded run does not block finish"
R3=$(mkrun applied-run feature/fn); commits "$R3" c2.go; collect "$R3"; verify "$R3" >/dev/null
$DA review apply "$R3" >/dev/null 2>&1
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "applied, not merged" <<<"$out" && ok "an applied run whose branch is not merged is open" || no "applied not merged: rc=$rc $out"
$F merge fn agent/applied-run >/dev/null 2>&1
out=$($F finish fn 2>&1)
grep -q "open run" <<<"$out" && no "an applied and merged run blocks finish: $out" || ok "an applied and merged run does not block finish"
$DA local clean "$R3" >/dev/null 2>&1
out=$($DA local clean "$R" 2>&1)
$F verify fn >/dev/null 2>&1; out=$($F finish fn 2>&1)
grep -q "^plan token:" <<<"$out" && ok "with no run open, feature finish goes on to its plan" || no "finish plan: $out"


rm -rf "$T"
exit $fail
