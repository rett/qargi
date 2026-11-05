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

rm -rf "$T"
exit $fail
