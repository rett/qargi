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
jq -n --arg p "$A" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, models:{provider:{local:"claude-code", cloud:"claude-platform"}}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
mkrun() { $DA local prepare --repo "$A" --base "${2:-develop}" --slug "$1" --scratch "$T/scr" ${3:+--role "$3"} | sed -n 's/^RUN=//p'; }
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
grep -q "refuse a member's write tool for a report file" <<<"$out" && grep -q "write its OUT files (report, manifest, series) with the shell, a heredoc" <<<"$out" \
  && ok "verify of an OUT with no report names the likely cause: a refused write tool, and the shell as the way round" || no "verify cause: $out"
grep -q "refs: unchanged by the run" <<<"$out" && grep -q "clean RUN --discard" <<<"$out" && ok "it still compares the refs, says so next to the message, and keeps verify required" || no "uncollected refs line: $out"
git -C "$A" branch stray-by-run develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/stray-by-run" <<<"$out" && grep -q "OUT is empty: the member did not collect" <<<"$out" && ok "a run that changed a ref and did not collect gets the ref verdict (exit 2) and the empty-OUT message" || no "uncollected and refs: rc=$rc $out"
[ ! -f "$R/verified" ] && ok "and still records nothing" || no "verified written for an uncollected run with a ref change"
git -C "$A" branch -D stray-by-run >/dev/null
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
# the tip is named when noting, a rewrite between two notes is refused, and NAME@SHA pins what the lead made
M0=$(git -C "$A" rev-parse feature/mine)
git -C "$A" update-ref refs/heads/feature/mine "$(git -C "$A" commit-tree -m rewritten "$M0^{tree}")"
out=$($DA ref note feature/mine 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not a fast-forward of your last note" <<<"$out" && grep -q "ref record --rewrite" <<<"$out" && ok "a second note refuses a ref that was rewritten since the first, and points to ref record --rewrite" || no "rewritten note: rc=$rc $out"
[ "$(tail -1 "$J" | jq -r .new)" = "$M0" ] && ok "and journals nothing for it" || no "rewritten note journaled: $(tail -1 "$J")"
git -C "$A" update-ref refs/heads/feature/mine "$M0"
M1=$(hand feature/mine)
git -C "$A" update-ref refs/heads/feature/mine "$M1"
out=$($DA ref note "feature/mine@deadbee" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not at deadbee" <<<"$out" && ok "NAME@SHA refuses a ref that is not at SHA" || no "pin mismatch: rc=$rc $out"
out=$($DA ref note "feature/mine@${M1:0:9}" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "after your earlier note) (tip by lead: by hand)" <<<"$out" && ok "NAME@SHA notes a ref that is at SHA, and the note names the tip's author and subject" || no "pin match: rc=$rc $out"
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

# --- 1c. refs a runtime creates in the repository, declared by the lead (answers runs.owned_refs)
own() { jq --argjson p "$1" '.runs = {owned_refs: $p}' "$T/c/projects/app.json" > "$T/app.new" && mv "$T/app.new" "$T/c/projects/app.json"; }
OWNED="accepted: refs/heads/rt-* (owned by the runtime, per runs.owned_refs)"
# the answers a run is checked by are the ones at its prepare (the lead's registry holds the copy): declare first, then prepare
R=$(mkrun owned0)
git -C "$A" branch rt-one develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/rt-one" <<<"$out" && ok "(setup) a branch a runtime made is found while no pattern declares it" || no "undeclared: rc=$rc $out"
own '["refs/heads/rt-*"]'
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/rt-one" <<<"$out" && ok "a pattern declared after a run's prepare does not apply to that run (the registry's copy of the answers does)" || no "late declaration: rc=$rc $out"
git -C "$A" branch -D rt-one >/dev/null; $DA local clean "$R" --discard >/dev/null 2>&1
R=$(mkrun owned1)
jq -e --arg p "$A" 'select(.slug == "owned1") | .project == "app" and .answers.runs.owned_refs == ["refs/heads/rt-*"] and .answers.repo.long_lived == ["master","develop"]' "$T/s/local-runs.jsonl" >/dev/null \
  && ok "prepare records the project and the answers that decide verification in the lead's registry" || no "registry line: $(tail -1 "$T/s/local-runs.jsonl")"
git -C "$A" branch rt-one develop
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -qF "rt-one created; $OWNED" <<<"$out" && grep -q "the refs the project declares the runtime's own" <<<"$out" && [ -f "$R/verified" ] && ok "a declared pattern accepts the ref in the strict phase and verify names the pattern and the answer" || no "declared: rc=$rc $out"
git -C "$A" update-ref refs/heads/rt-one "$(hand rt-one)"
git -C "$A" branch rt-two develop
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -qF "rt-one moved; $OWNED" <<<"$out" && grep -qF "rt-two created; $OWNED" <<<"$out" && ok "and after the passing verify too: moves and new refs of the pattern are named" || no "declared lenient: rc=$rc $out"
git -C "$A" branch -D rt-two >/dev/null
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -qF "rt-two deleted; $OWNED" <<<"$out" && ok "a deletion of a declared ref is accepted and named too" || no "declared deletion: rc=$rc $out"
git -C "$A" branch other-made develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "refs/heads/other-made" <<<"$out" && ! grep -q "other-made.*owned by the runtime" <<<"$out" && ok "a ref the pattern does not match is still found" || no "other ref: rc=$rc $out"
git -C "$A" branch -D other-made >/dev/null
# a decoy project file made after prepare, and a change of the real one, change nothing for the run
jq --arg p "$A" '.repo.path = $p | .runs = {owned_refs: ["refs/heads/evil-*"]} | .repo.long_lived = ["master"]' "$T/c/projects/app.json" > "$T/c/projects/aaa.json"
own '[]'
git -C "$A" branch evil-one develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "refs/heads/evil-one" <<<"$out" && ! grep -q "evil-one.*owned by the runtime" <<<"$out" && ok "a decoy projects/aaa.json for the same repository, created after prepare, accepts nothing" || no "decoy: rc=$rc $out"
git -C "$A" branch -D evil-one >/dev/null
git -C "$A" update-ref refs/heads/rt-one "$(hand rt-one)"
out=$(verify "$R"); rc=$?
[ $rc = 0 ] && grep -qF "rt-one moved; $OWNED" <<<"$out" && ok "and the real answers emptied after prepare still apply to the run that was prepared with them" || no "snapshot kept: rc=$rc $out"
rm -f "$T/c/projects/aaa.json"; own '["refs/heads/rt-*"]'
# clean names it as well
git -C "$A" update-ref refs/heads/rt-one "$(hand rt-one)"
echo '{}' > "$R/out/manifest.json"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -qF "rt-one moved; $OWNED" <<<"$out" && ! grep -q "the lead's own move: rt-one" <<<"$out" && ok "local clean accepts the declared ref and names the pattern" || no "clean owned: rc=$rc $out"
# a member rewriting develop is still caught: the strict phase, a rewrite, a pattern that would reach it
own '["refs/heads/rt-*"]'
R=$(mkrun owned2)
dv=$(git -C "$A" rev-parse develop)
git -C "$A" update-ref refs/heads/develop "$(git -C "$A" commit-tree -m rewritten "$dv^{tree}")"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch moved: refs/heads/develop" <<<"$out" && ok "a rewrite of develop is found though a pattern is declared" || no "develop rewrite: rc=$rc $out"
git -C "$A" update-ref refs/heads/develop "$dv"
own '["refs/heads/dev*"]'
R=$(mkrun owned2b)
git -C "$A" update-ref refs/heads/develop "$(git -C "$A" commit-tree -m rewritten "$dv^{tree}")"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch moved: refs/heads/develop" <<<"$out" && ! grep -q "owned by the runtime" <<<"$out" && ok "a pattern that would match develop (hand-edited answers) is ignored" || no "develop pattern: rc=$rc $out"
git -C "$A" update-ref refs/heads/develop "$dv"
own '["refs/heads/*","refs/heads/ab*"]'
R=$(mkrun owned2c)
git -C "$A" branch abc-made "$dv"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch created: refs/heads/abc-made" <<<"$out" && ! grep -q "owned by the runtime" <<<"$out" && ok "a bare glob and a pattern with a short literal prefix are ignored" || no "short pattern: rc=$rc $out"
git -C "$A" branch -D abc-made >/dev/null
# the base of an open run is never owned
git -C "$A" branch rt-base develop
own '["refs/heads/rt-*"]'
R=$(mkrun owned3 rt-base)
git -C "$A" update-ref refs/heads/rt-base "$(git -C "$A" commit-tree -m rewritten "$dv^{tree}")"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "branch moved: refs/heads/rt-base" <<<"$out" && ok "the base of an open run is not accepted as owned, whatever the pattern says" || no "base owned: rc=$rc $out"
git -C "$A" update-ref refs/heads/rt-base "$dv"
out=$(verify "$R"); [ $? = 0 ] || no "(setup) base restored: $out"
# the match itself refuses the git-flow branches, the tags and the harness's bridge branches, whatever pattern a hand-edited answer holds
echo '{"runs":{"owned_refs":["refs/heads/rel*/0*","refs/heads/age*t/foo-*","refs/tags/v0.*","refs/heads/worktree-*","refs/heads/foo-*"]}}' > "$T/own.json"
OM="python3 -I $PWD/lib/owned_refs.py match $T/own.json"
for n in refs/heads/release/0.2 refs/heads/agent/foo-x refs/tags/v0.2 refs/heads/worktree-bridge-cse_1; do
  $OM "$n" >/dev/null 2>&1 && no "match accepted $n" || ok "match refuses $n whatever the answer holds"
done
[ "$($OM refs/heads/foo-1 2>&1)" = "refs/heads/foo-*" ] && [ "$($OM refs/heads/worktree-other 2>&1)" = "refs/heads/worktree-*" ] && ok "and still accepts a branch the valid patterns name (foo-1, worktree-other)" || no "match valid patterns"
own '["refs/heads/worktree-*","refs/heads/rel*/0*"]'
R=$(mkrun owned4)
git -C "$A" branch worktree-bridge-owned4 develop; git -C "$A" branch release/0.9 develop
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "refs/heads/worktree-bridge-owned4" <<<"$out" && grep -q "refs/heads/release/0.9" <<<"$out" && ! grep -q "owned by the runtime" <<<"$out" && ok "a bridge branch no worktree holds and a release branch are found though patterns that reach them are declared" || no "bridge/release owned: rc=$rc $out"
git -C "$A" branch -D worktree-bridge-owned4 release/0.9 >/dev/null
# the answer is checked by project validate
$DA project template demo | jq '.repo.url = "https://github.com/example/demo" | .runs = {owned_refs: ["refs/heads/dev*"]}' > "$T/bad.json"
out=$($DA project validate "$T/bad.json" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "runs.owned_refs\[0\]: would match refs/heads/develop" <<<"$out" && ok "project validate refuses a pattern that would match develop" || no "validate: rc=$rc $out"
jq 'del(.runs)' "$T/c/projects/app.json" > "$T/app.new" && mv "$T/app.new" "$T/c/projects/app.json"
git -C "$A" branch -D rt-one rt-base >/dev/null 2>&1
for r in "$T"/scr/qargi.*; do $DA local clean "$r" --discard >/dev/null 2>&1; done

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
git -C "$A" branch rogue-after-verify develop
out=$($DA local close "$R" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "refs of the repository changed" <<<"$out" && [ -z "$(jq -r --arg r "$R" 'select(.run == $r) | .closed // empty' "$T/s/local-runs.jsonl")" ] && ok "close checks the refs again: a ref changed after the first verify keeps the run open" || no "close after a ref change: rc=$rc $out"
git -C "$A" branch -D rogue-after-verify >/dev/null
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
R2=$(mkrun ro-run feature/cl review); echo "# report" > "$R2/out/report.md"
out=$($DA local close "$R2" --applied-by-am 2>&1); rc=$?
[ $rc = 1 ] && grep -q "read-only run" <<<"$out" && ok "close refuses a read-only run" || no "close read-only: rc=$rc $out"
$DA local clean "$R2" --discard >/dev/null 2>&1

# --- 3b. a read-only run (a report, no patches) closes with a plain clean
$F start ro >/dev/null 2>&1
R=$(mkrun ro-ok feature/ro review); echo "# report" > "$R/out/report.md"
out=$($DA lead compact-check --project app 2>&1); rc=$?
[ $rc = 1 ] && grep -q "a read-only local run is open: $R" <<<"$out" && grep -q "close it: qargi local clean $R\$" <<<"$out" && ok "compact-check names an open read-only run and its closing command" || no "compact-check read-only: rc=$rc $out"
out=$($F finish ro 2>&1); rc=$?
[ $rc = 1 ] && grep -q "feature ro has 1 open run(s)" <<<"$out" && grep -q "$R (review ro-ok): prepared, not verified" <<<"$out" && grep -q "close it: qargi local clean $R\$" <<<"$out" \
  && ok "feature finish names the open read-only run and the exact command that closes it" || no "finish read-only: rc=$rc $out"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "cleaned $R" <<<"$out" && [ ! -e "$R" ] && ok "a read-only run with a report and unchanged refs closes with a plain clean (no manifest, no --discard)" || no "clean read-only: rc=$rc $out"
out=$($F finish ro 2>&1); grep -q "open run" <<<"$out" && no "a cleaned read-only run still blocks finish: $out" || ok "and no longer blocks feature finish"
R=$(mkrun ro-noreport feature/ro review)
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && grep -q "report.md" <<<"$out" && [ -d "$R" ] && ok "a read-only run with no report is still refused, and the message says what closes it" || no "read-only no report: rc=$rc $out"
grep -q "refuse a member's write tool for a report file" <<<"$out" && grep -q "with the shell, a heredoc" <<<"$out" && ok "clean of an OUT with no report names the cause too" || no "clean cause: $out"
out=$(verify "$R"); rc=$?
grep -q "qargi: note: OUT of the read-only run $R holds no report" <<<"$out" && grep -q "with the shell, a heredoc" <<<"$out" && ok "verify of a read-only run whose OUT holds no report says so, with the cause (a note: the exit status is the refs verdict)" || no "verify read-only no report: rc=$rc $out"
out=$($DA lead compact-check --project app 2>&1)
grep -q "close it: qargi local clean $R (once the member has written OUT/report.md" <<<"$out" && ok "its closing command waits for the report" || no "closing without report: $out"
echo "# report" > "$R/out/report.md"; git -C "$A" branch ro-stray develop
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "refs of the repository changed" <<<"$out" && [ -d "$R" ] && ok "a read-only run whose refs changed is kept as evidence" || no "read-only changed refs: rc=$rc $out"
git -C "$A" branch -D ro-stray >/dev/null
commits "$R" ro1.go
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "never applied" <<<"$out" && [ -d "$R" ] && ok "a read-only run whose clone holds commits is not dropped by a plain clean" || no "read-only with commits: rc=$rc $out"
$DA local clean "$R" --discard >/dev/null 2>&1
R=$(mkrun wr-report feature/ro); echo "# report" > "$R/out/report.md"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && [ -d "$R" ] && ok "a run of work (class write) with only a report still needs its manifest" || no "write with report: rc=$rc $out"
! grep -q "refuse a member's write tool" <<<"$out" && ok "an OUT that holds a report is not blamed on a refused write tool" || no "cause named with a report present: $out"
$DA local clean "$R" --discard >/dev/null 2>&1
R=$(mkrun ro-ok2 feature/ro review); echo "# report" > "$R/out/report.md"; verify "$R" >/dev/null
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "cleaned $R" <<<"$out" && ok "a verified read-only run closes with a plain clean as well" || no "clean verified read-only: rc=$rc $out"

# --- 3c. the class of a run is the lead's registry's: a member's class file, and a report it fakes, change nothing
jq -e 'select(.slug == "ro-ok2") | .class == "read-only"' "$T/s/local-runs.jsonl" >/dev/null && jq -e 'select(.slug == "wr-report") | .class == "write"' "$T/s/local-runs.jsonl" >/dev/null \
  && ok "prepare records the class of the run in the lead's registry" || no "registry class: $(tail -2 "$T/s/local-runs.jsonl")"
R=$(mkrun forged-ro feature/ro); echo read-only > "$R/class"; echo "# report" > "$R/out/report.md"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && [ -d "$R" ] && ok "a write run whose class file a member set to read-only still needs its manifest" || no "forged read-only: rc=$rc $out"
out=$($DA lead compact-check --project app 2>&1)
grep -q "a read-only local run is open: $R" <<<"$out" && no "a forged class file makes a write run read-only for compact-check: $out" || ok "and compact-check does not call it a read-only run"
$DA local clean "$R" --discard >/dev/null 2>&1
R=$(mkrun forged-wr feature/ro review); echo write > "$R/class"; rm -f "$R/class"; echo "# report" > "$R/out/report.md"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "cleaned $R" <<<"$out" && ok "a read-only run whose class file a member removed is still read-only (plain clean with its report)" || no "removed class file: rc=$rc $out"
R=$(mkrun ro-patches feature/ro review); mkdir -p "$R/out/patches"; echo x > "$R/out/patches/0001-x.patch"; echo write > "$R/class"
out=$(verify "$R"); rc=$?
[ $rc = 2 ] && grep -q "is a read-only run" <<<"$out" && ok "a read-only run's patches are refused though a member set the class file to write" || no "ro with patches: rc=$rc $out"
$DA local clean "$R" --discard >/dev/null 2>&1
# a record with no class (a run prepared by an earlier version) falls back to the file, and with neither counts as a run of work
R=$(mkrun oldrec feature/ro); echo "# report" > "$R/out/report.md"; rm -f "$R/class"
jq -c --arg r "$R" 'if .run == $r then del(.class) else . end' "$T/s/local-runs.jsonl" > "$T/reg.new" && mv "$T/reg.new" "$T/s/local-runs.jsonl"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && ok "an older record with no class and no class file is a run of work, not a read-only one" || no "no class at all: rc=$rc $out"
echo read-only > "$R/class"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && ok "an older record falls back to the class file" || no "old record file fallback: rc=$rc $out"
# what counts as a report: a regular file named report.md or NAME-report.md directly in OUT, for clean and for compact-check alike
R=$(mkrun rep-kinds feature/ro review)
ln -s /etc/hostname "$R/out/report.md"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && ok "a link named report.md is no report" || no "link report: rc=$rc $out"
rm -f "$R/out/report.md"; mkdir "$R/out/sub"; echo "# r" > "$R/out/sub/report.md"; echo "# r" > "$R/out/xreport.md"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "holds no manifest" <<<"$out" && ok "a report in a subdirectory, or a file named xreport.md, is no report" || no "sub/other report: rc=$rc $out"
out=$($DA lead compact-check --project app 2>&1)
grep -q "close it: qargi local clean $R (once the member has written OUT/report.md" <<<"$out" && ok "compact-check agrees: it waits for the report" || no "compact-check kinds: $out"
echo "# r" > "$R/out/review-report.md"
out=$($DA lead compact-check --project app 2>&1)
grep -q "close it: qargi local clean $R\$" <<<"$out" && ok "a NAME-report.md file is a report for compact-check" || no "compact-check prefixed report: $out"
out=$($DA local clean "$R" 2>&1); rc=$?
[ $rc = 0 ] && ok "and for clean" || no "prefixed report clean: rc=$rc $out"

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
own '["refs/heads/rt-*"]'
R3=$(mkrun applied-run feature/fn); commits "$R3" c2.go; collect "$R3"; verify "$R3" >/dev/null
$DA review apply "$R3" >/dev/null 2>&1
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "applied, not merged" <<<"$out" && ok "an applied run whose branch is not merged is open" || no "applied not merged: rc=$rc $out"
# a branch a member can make at the applied tip settles nothing: a worktree-bridge-* branch, a branch the run's answers declare owned
R3T=$(git -C "$A" rev-parse agent/applied-run)
git -C "$A" branch worktree-bridge-settle "$R3T"; git -C "$A" branch rt-settle "$R3T"
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "applied, not merged" <<<"$out" && ok "a bridge branch and an owned-ref branch at the applied tip do not settle the run as merged" || no "settled by bridge/owned: rc=$rc $out"
out=$($DA local list --scratch "$T/scr" 2>&1)
grep -E "applied-run +[0-9a-z?]+ +yes +no +$R3" <<<"$out" >/dev/null && ok "local list agrees (merged: no)" || no "list merged: $out"
git -C "$A" branch -D worktree-bridge-settle rt-settle >/dev/null
# RUN/applied is a member's to write: a forged tip that is on develop does not settle it, the lead's journal says what review apply made
printf 'agent/applied-run %s now\n' "$(git -C "$A" rev-parse develop)" > "$R3/applied"
out=$($F finish fn 2>&1); rc=$?
[ $rc = 1 ] && grep -q "applied, not merged" <<<"$out" && ok "a tip forged into RUN/applied is not believed: the tip of the journaled review:apply is tested" || no "forged applied: rc=$rc $out"
printf 'agent/applied-run %s now\n' "$R3T" > "$R3/applied"
$F merge fn agent/applied-run >/dev/null 2>&1
out=$($F finish fn 2>&1)
grep -q "open run" <<<"$out" && no "an applied and merged run blocks finish: $out" || ok "an applied and merged run does not block finish"
$DA local clean "$R3" >/dev/null 2>&1
jq 'del(.runs)' "$T/c/projects/app.json" > "$T/app.new" && mv "$T/app.new" "$T/c/projects/app.json"
out=$($DA local clean "$R" 2>&1)
$F verify fn >/dev/null 2>&1; out=$($F finish fn 2>&1)
grep -q "^plan token:" <<<"$out" && ok "with no run open, feature finish goes on to its plan" || no "finish plan: $out"


rm -rf "$T"
exit $fail
