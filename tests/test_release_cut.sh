#!/usr/bin/env bash
# The ceremony of a release cut: the lock of a finishing verb tells the truth about flock; the bookkeeping file of a merge a finish parked is
# removed when the release is started again; a hotfix is not refused by a preflight that needs content only the hotfix brings; `release plan`
# makes one plan and one approval for the whole cut. Offline: a bare repository is the origin, gh is a fake.
# Run: tests/test_release_cut.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, approving the cut would be refused as a member's
REL="$DA release"
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
mk() { # NAME [with-origin]: a repository with master and develop, a version file and a changelog; the project's answers; the suite recorded as passed
  R=$T/$1; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
  if [ -n "${2:-}" ]; then O=$T/$1-origin.git; git init -q --bare "$O"; git -C "$R" remote add origin "$O"; git -C "$R" push -q origin master develop; fi
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
  $REL verify 0.2.0 >/dev/null 2>&1
}

# --- pid_lock: a flock that fails is reported, not ignored
mk lock
printf '#!/bin/sh\nexit 1\n' > "$T/bin/flock"; chmod +x "$T/bin/flock"
out=$(PATH=$T/bin:$PATH $REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "could not take the lock .*flock on .* failed" <<<"$out" && ok "a flock that fails ends the verb: it says so, and nothing was changed" || no "failing flock: rc=$rc $out"
rm -rf "$T/farm"; mkdir "$T/farm"; for f in /usr/bin/*; do [ "${f##*/}" = flock ] || ln -s "$f" "$T/farm/${f##*/}"; done
out=$(PATH=$HERMETIC/bin:$T/farm $REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "flock command (util-linux) is not installed" <<<"$out" && ok "no flock command: the verb says it is not installed" || no "missing flock: rc=$rc $out"
out=$($REL finish 0.2.0 2>&1); grep -q "could not take the lock" <<<"$out" && no "an ordinary finish was refused by the lock: $out" || ok "with flock the lock is taken as before (the verb goes on to its own checks)"
# the intent record and the ref journal take the same kind of lock: the functions of lib/gitflow.sh, run as they are
LIBD=${DA%/bin/qargi}/lib
{ sed -n '/^intent_file()/,/^intent_unlock()/p' "$LIBD/gitflow.sh"; sed -n '/^journal_line()/,/^}/p' "$LIBD/gitflow.sh"; } > "$T/lockfns.sh"
cat > "$T/lockrun.sh" <<'S'
set -u
die() { echo "die: $*"; exit 1; }
now() { echo 2026-01-01T00:00:00Z; }
DA_STATE=$1; PROJ=app; . "$2"
case $3 in
  intent) intent_write k '{"a":1}';;
  journal) journal_line "$1" refs/heads/x "" abc123 test:verb "";;
esac
S
for how in intent journal; do
  rm -rf "$T/ls"; mkdir -p "$T/ls"
  out=$(PATH=$T/bin:$PATH bash "$T/lockrun.sh" "$T/ls" "$T/lockfns.sh" $how 2>&1); rc=$?
  if [ $how = intent ]; then
    [ "$rc" = 1 ] && grep -q "die: could not take the lock for the intent record .*flock on .* failed.*nothing was changed" <<<"$out" && [ ! -e "$T/ls/finish-intent/app-k.json" ] && ok "intent_write: a flock that fails ends the verb, says so, and writes no record" || no "intent_write failing flock: rc=$rc $out"
  else
    grep -q "warning: the ref journal could not be written for refs/heads/x (test:verb): flock on .* failed" <<<"$out" && ok "the ref journal: a flock that fails is a warning that names the flock" || no "journal failing flock: rc=$rc $out"
  fi
  out=$(PATH=$HERMETIC/bin:$T/farm bash "$T/lockrun.sh" "$T/ls" "$T/lockfns.sh" $how 2>&1); rc=$?
  if [ $how = intent ]; then
    [ "$rc" = 1 ] && grep -q "die: could not take the lock for the intent record .*flock command (util-linux) is not installed" <<<"$out" && [ ! -e "$T/ls/finish-intent/app-k.json" ] && ok "intent_write: no flock command, the verb says it is not installed" || no "intent_write missing flock: rc=$rc $out"
  else
    grep -q "warning: the ref journal could not be written for refs/heads/x (test:verb): the flock command (util-linux) is not installed" <<<"$out" && ok "the ref journal: no flock command, the warning says it is not installed" || no "journal missing flock: rc=$rc $out"
  fi
  out=$(bash "$T/lockrun.sh" "$T/ls" "$T/lockfns.sh" $how 2>&1); rc=$?
  if [ $how = intent ]; then [ "$rc" = 0 ] && [ "$(cat "$T/ls/finish-intent/app-k.json")" = '{"a":1}' ] && ok "intent_write with flock writes the record as before" || no "intent_write: rc=$rc $out"
  else [ "$rc" = 0 ] && [ -z "$out" ] && [ "$(jq -r .ref "$T/ls/ref-journal.jsonl")" = refs/heads/x ] && ok "the ref journal with flock writes its line as before" || no "journal: rc=$rc $out"; fi
done

# --- the bookkeeping file of a merge a finish parked belongs to the release that was given up: starting the version again removes it
mk stale
CF=$T/s/conflicts; mkdir -p "$CF"
for f in release-0.2.0-into-develop.master release-0.2.0-into-develop.done release-0.2.0-into-master.done release-0.3.0-into-develop.master hotfix-0.2.0-into-develop.master; do echo "x y z" > "$CF/stale-$f"; done
out=$($REL start 0.2.0 2>&1); [ -e "$CF/stale-release-0.2.0-into-develop.master" ] && ok "a plan alone removes nothing" || no "the plan removed the bookkeeping file: $out"
rstart 0.2.0 --date 2026-03-04 >/dev/null 2>&1 || no "stale: start failed: $(rstart 0.2.0 2>&1)"
left=$(ls "$CF" | sort | paste -sd' ')
[ "$left" = "stale-hotfix-0.2.0-into-develop.master stale-release-0.3.0-into-develop.master" ] && ok "start removes the .master and .done files of the release it starts, and no other" || no "left in conflicts: $left"

# --- a hotfix is not refused by a release.preflight that needs content only the hotfix brings: start does not run it for a hotfix (the plan says
# so and when it runs), push runs it in a copy of the branch, before anything is pushed
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; esac\n' "$T" > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh
mk hot with-origin
jq '.release = {preflight: ["test", "-f", "FIXED"]}' "$T/c/projects/hot.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/hot.json"
out=$($REL start 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "preflight (release.preflight): not run now: master does not have the content this hotfix brings. It runs in a copy of hotfix/0.1.1 when you push" <<<"$out" && ok "hotfix start: the plan says the preflight is not run now, and where and when it runs" || no "hotfix plan: rc=$rc $out"
out=$(rstart 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/hotfix/0.1.1 >/dev/null && ok "hotfix start: a preflight that needs the fix does not refuse the start" || no "hotfix start refused: rc=$rc $out"
out=$($REL start 0.1.2 2>&1); grep -q "release.preflight failed" <<<"$out" && ok "a release (not a hotfix) is still refused at start by a failing preflight" || no "release start with a failing preflight: $out"
t=$($REL push 0.1.1 --hotfix | tok); out=$($REL push 0.1.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "release.preflight failed" <<<"$out" && [ -z "$(git -C "$R" ls-remote origin refs/heads/hotfix/0.1.1)" ] && ok "push before the fix: the preflight refuses it and nothing is pushed" || no "push before the fix: rc=$rc $out"
w=$($REL fix 0.1.1 --hotfix | sed -n 's/^worktree: //p'); echo fixed > "$w/FIXED"; git -C "$w" add FIXED && git -C "$w" commit -q -m "the fix"
t=$($REL push 0.1.1 --hotfix | tok); out=$($REL push 0.1.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/hotfix/0.1.1)" ] && ok "push after the fix: the preflight passes in the copy of the branch and the branch is pushed" || no "push after the fix: rc=$rc $out"

# --- release.hotfix_preflight: what push runs for a hotfix instead of release.preflight (a release keeps release.preflight; start runs neither for a hotfix)
mk hot2 with-origin
jq '.release = {preflight: ["false"], hotfix_preflight: ["test", "-f", "FIXED"]}' "$T/c/projects/hot2.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/hot2.json"
out=$($REL start 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "preflight (release.hotfix_preflight): not run now: master does not have the content this hotfix brings. It runs in a copy of hotfix/0.1.1 when you push, before anything is pushed (a non-zero exit refuses the push): test -f FIXED" <<<"$out" \
  && ok "hotfix start: the plan names release.hotfix_preflight, not release.preflight, as the check that runs at push" || no "hotfix_preflight plan: rc=$rc $out"
out=$(rstart 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/hotfix/0.1.1 >/dev/null && ok "hotfix start runs neither preflight (release.preflight would refuse it)" || no "hotfix_preflight start: rc=$rc $out"
out=$($REL push 0.1.1 --hotfix 2>&1); t=$(tok <<<"$out")
grep -q "^preflight (release.hotfix_preflight, run in a copy of hotfix/0.1.1 before the push): test -f FIXED" <<<"$out" && ok "the push plan of a hotfix lists release.hotfix_preflight" || no "hotfix push plan: $out"
out=$($REL push 0.1.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "release.hotfix_preflight failed (exit 1): test -f FIXED" <<<"$out" && [ -z "$(git -C "$R" ls-remote origin refs/heads/hotfix/0.1.1)" ] && ok "push of a hotfix before the fix: release.hotfix_preflight refuses it, nothing is pushed" || no "hotfix push before the fix: rc=$rc $out"
w=$($REL fix 0.1.1 --hotfix | sed -n 's/^worktree: //p'); echo fixed > "$w/FIXED"; git -C "$w" add FIXED && git -C "$w" commit -q -m "the fix"
t=$($REL push 0.1.1 --hotfix | tok); out=$($REL push 0.1.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/hotfix/0.1.1)" ] && ok "after the fix release.hotfix_preflight passes (release.preflight, which always fails here, is not run) and the branch is pushed" || no "hotfix push after the fix: rc=$rc $out"
out=$($REL start 0.1.2 2>&1); grep -q "release.preflight failed" <<<"$out" && ok "a release (not a hotfix) still runs release.preflight, not release.hotfix_preflight" || no "release start with hotfix_preflight set: $out"

# --- the cut: one plan and one approval for start, push, finish and site (publish has its own plan)
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac\n' "$T" > "$T/gh"
cutstate() { jq -r '[.steps[] as $s | $s + ":" + (if .done[$s] then "done" else "pending" end)] | join(" ")' "$T/s/release/$QARGI_PROJECT-0.2.0.cut.json"; }
mk cut with-origin
: > "$T/gh.log"
out=$($REL plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out")
[ -n "$ct" ] && grep -q "^1. start: create release/0.2.0 from develop" <<<"$out" && grep -q "^2. push: push release/0.2.0 to origin" <<<"$out" && grep -q "^3. finish: merge release/0.2.0 into master" <<<"$out" \
  && grep -q "THIS IS THE PUSH AND TAG GATE" <<<"$out" && grep -q "^publish is not in this cut: .*has its own plan after finish" <<<"$out" && ! grep -q "^[0-9]*\. publish" <<<"$out" && ok "plan: one plan lists every step with what moves, and one token; publish is named as outside the cut" || no "cut plan: $out"
[ ! -e "$T/s/release/cut-0.2.0.cut.json" ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "plan: a plan alone records and changes nothing" || no "the plan changed something"
out=$($REL start 0.2.0 --date 2026-03-04 --plan "$ct" 2>&1); ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "a token of the cut with no approval recorded is no approval: start only prints its plan" || no "start applied without an approval: $out"
out=$($REL plan 0.2.0 --date 2026-03-04 --plan wrongtoken --approved "ship it" 2>&1); rc=$?
[ "$rc" != 0 ] && [ ! -e "$T/s/release/cut-0.2.0.cut.json" ] && ok "approving the cut with another token is refused" || no "wrong token approved: rc=$rc $out"
out=$($REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(cutstate)" = "start:pending push:pending finish:pending" ] && [ "$(jq -r '.approval.words' "$T/s/release/cut-0.2.0.cut.json")" = "ship it" ] && grep -q "next in the cut $ct: qargi release start 0.2.0 --plan $ct" <<<"$out" \
  && grep -c '"verb":"release:cut"' "$T/s/audit.log" | grep -qx 1 && ok "approving records the words once, the steps and an audit line, and names the next step" || no "approval: rc=$rc $out; $(cat "$T/s/release/cut-0.2.0.cut.json" 2>&1)"
out=$($REL start 0.2.0 --date 2026-03-04 --plan "$ct" --approved again 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "whose approval is recorded" <<<"$out" && ok "a step under the cut takes no words of its own" || no "start with --approved under the cut: rc=$rc $out"
mkdir -p "$T/memberrun"; : > "$T/memberrun/ability"; : > "$T/memberrun/refs.before"   # what qargi local prepare leaves in a member's run directory
out=$(cd "$T/memberrun" && $REL start 0.2.0 --date 2026-03-04 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 2 ] && grep -q "running a step under the cut of a release .* is not available in a member run" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && [ "$(cutstate)" = "start:pending push:pending finish:pending" ] \
  && ok "a step under the cut is refused in a member run (the recorded words are the owner's): exit 2, nothing created, nothing recorded" || no "start under the cut in a member run: rc=$rc $out"
out=$(QARGI_NESTED=1 $REL start 0.2.0 --date 2026-03-04 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 2 ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "a step under the cut is refused in a nested call too" || no "start under the cut, nested: rc=$rc $out"
out=$($REL start 0.2.0 --date 2026-03-04 --plan wrongtoken 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "a cut of 0.2.0 is recorded and wrongtoken is not its token" <<<"$out" && ! grep -q "^plan token:" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null \
  && ok "a --plan that is not the recorded cut's token (and no --approved) dies and names that a cut is recorded, and prints no plan" || no "start with a wrong token: rc=$rc $out"
out=$($REL push 0.2.0 --plan wrongtoken 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "is recorded and wrongtoken is not its token" <<<"$out" && ok "the same for push" || no "push with a wrong token: rc=$rc $out"
out=$($REL start 0.2.0 --date 2026-04-05 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "does not cover start" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "start under the cut with another date: refused before anything is created" || no "start with another date: rc=$rc $out"
out=$($REL start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && [ "$(git -C "$R" show release/0.2.0:CHANGELOG.md | grep -c '^## \[0.2.0\] - 2026-03-04')" = 1 ] && [ "$(cutstate)" = "start:done push:pending finish:pending" ] \
  && grep -q "next in the cut $ct: qargi release push 0.2.0 --plan $ct" <<<"$out" && grep '"verb":"release:start"' "$T/s/audit.log" | grep -q '"approved":"ship it"' \
  && ok "start --plan alone runs the step: the date is the cut's, the audit line carries the recorded words, the cut shows the step done" || no "start under the cut: rc=$rc $out; $(cutstate)"
out=$($REL finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "the step push of the cut is not done yet" <<<"$out" && ok "finish before push: refused, naming the step" || no "finish before push: rc=$rc $out"
out=$($REL push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && grep -q "pr create" "$T/gh.log" && [ "$(cutstate)" = "start:done push:done finish:pending" ] && ok "push --plan alone pushes the branch and opens the pull request" || no "push under the cut: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$ct" --keep 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "planned without --keep" <<<"$out" && ok "finish --keep under a cut planned without it is refused" || no "finish --keep: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ -n "$(git -C "$R" ls-remote origin refs/tags/0.2.0)" ] && [ "$(cutstate)" = "start:done push:done finish:done" ] \
  && grep '"verb":"release:finish"' "$T/s/audit.log" | grep -q '"approved":"ship it"' && ok "finish --plan alone merges, tags and pushes; the recorded words are on its audit line" || no "finish under the cut: rc=$rc $out"
out=$($REL status 0.2.0 2>&1); grep -q "^  finish: done" <<<"$out" && ! grep -q "^  publish:" <<<"$out" && ok "status shows where the cut is, and publish is not one of its steps" || no "status: $out"
n=$(wc -l < "$T/gh.log")
out=$($REL publish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut $ct of 0.2.0 does not cover publish: run publish with its own plan" <<<"$out" && [ "$(wc -l < "$T/gh.log")" = "$n" ] && ok "publish with the token of the cut is refused, and nothing is published" || no "publish under the cut: rc=$rc $out"
out=$($REL publish 0.2.0 --plan "$ct" --approved "again" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "does not cover publish" <<<"$out" && [ "$(wc -l < "$T/gh.log")" = "$n" ] && ok "publish is refused the cut token with --approved too" || no "publish with the cut token and words: rc=$rc $out"
out=$($REL publish 0.2.0 --plan wrongtoken 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "is recorded and wrongtoken is not its token" <<<"$out" && ok "publish with another token and no words dies too" || no "publish with a wrong token: rc=$rc $out"
t=$($REL publish 0.2.0 | tok); out=$($REL publish 0.2.0 --plan "$t" --approved "publish it" 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "release create 0.2.0" "$T/gh.log" && [ "$(cutstate)" = "start:done push:done finish:done" ] && [ "$(jq -r '.done.publish // "none"' "$T/s/release/cut-0.2.0.cut.json")" = none ] \
  && grep '"verb":"release:publish"' "$T/s/audit.log" | grep -q '"approved":"publish it"' && ok "publish by its own plan and approval creates the GitHub release; the cut does not record it" || no "publish by its own plan: rc=$rc $out"
out=$($REL plan 0.2.0 2>&1); grep -q "is complete: every step is done (publish is not in the cut" <<<"$out" && ok "the cut is complete without publish, and says publish has its own plan" || no "complete: $out"
out=$($REL plan 0.2.0 2>&1); grep -q "is recorded already" <<<"$out" && grep -q "^  start: done" <<<"$out" && ok "plan on a recorded cut shows it and plans nothing new" || no "plan again: $out"

# a fix committed after the cut left the branch: push and finish refuse the cut token; the fix goes by its own plan and the cut goes on from there
mk cut2 with-origin
out=$($REL plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); $REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "go ahead" >/dev/null 2>&1
$REL start 0.2.0 --plan "$ct" >/dev/null 2>&1
w=$($REL fix 0.2.0 | sed -n 's/^worktree: //p'); echo fix > "$w/fix.txt"; git -C "$w" add fix.txt && git -C "$w" commit -q -m "a fix"
out=$($REL push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "does not cover push" <<<"$out" && grep -q "something was committed on it" <<<"$out" && [ -z "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && ok "a commit on the branch after start: push under the cut is refused and nothing is pushed" || no "push after a fix: rc=$rc $out"
t=$($REL push 0.2.0 | tok); out=$($REL push 0.2.0 --plan "$t" --approved "pushing the fix" 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q '"push"' <(jq -c '.done | keys' "$T/s/release/cut2-0.2.0.cut.json") && [ "$(jq -r '.done.push.via' "$T/s/release/cut2-0.2.0.cut.json")" = own ] && ok "the push by its own plan is recorded in the cut as done by its own plan" || no "own push: rc=$rc $out"
git -C "$R" update-ref refs/heads/master "$(git -C "$R" commit-tree -p master -m moved 'master^{tree}')"
out=$($REL finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "does not cover finish" <<<"$out" && grep -q "master is at" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "master moved since the plan: finish under the cut is refused, nothing is tagged" || no "finish after master moved: rc=$rc $out"

# --- release.finish_check: run by finish in a copy of the branch once the plan is approved, before anything is merged, tagged or pushed; the plans list it
printf '#!/usr/bin/env bash\necho "$PWD $1 ${QARGI_RELEASE_VERSION:-} $(cat VERSION)" >> "%s/fc.log"\nif [ -f "%s/fc.fail" ]; then echo "finish check boom"; exit 5; fi\n' "$T" "$T" > "$T/fc.sh"
mk fcheck with-origin
jq --arg s "$T/fc.sh" '.release = {finish_check: ["bash", $s, "{version}"]}' "$T/c/projects/fcheck.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/fcheck.json"
out=$($REL start 0.2.0 --date 2026-03-04 2>&1); rc=$?   # every release verb that relies on the release answers checks them first
[ "$rc" = 0 ] && grep -q "^plan token: " <<<"$out" && ok "release.finish_check is a release answer (the plan of start is made: no verb refuses the answer)" || no "release.finish_check is not a known release answer: rc=$rc $out"
out=$($REL plan 0.2.0 --date 2026-03-04 2>&1)
grep -q "release.finish_check runs in a copy of the branch first, before anything is merged, tagged or pushed (a non-zero exit refuses): bash $T/fc.sh {version}" <<<"$out" && ok "the plan of the cut lists the finish check" || no "cut plan: $out"
rstart 0.2.0 --date 2026-03-04 >/dev/null 2>&1; t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
out=$($REL finish 0.2.0 2>&1); t=$(tok <<<"$out")
grep -q "^finish check (release.finish_check, run in a copy of release/0.2.0 once this plan is approved, before anything is merged, tagged or pushed; a non-zero exit refuses): bash $T/fc.sh {version}" <<<"$out" && [ ! -e "$T/fc.log" ] && ok "the finish plan lists the check and runs nothing" || no "finish plan: $out"
refs() { { git -C "$R" for-each-ref refs/heads refs/tags; git -C "$O" for-each-ref; } | md5sum; }   # the local branches and tags, and every ref of origin
before=$(refs); touch "$T/fc.fail"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "release.finish_check failed (exit 5)" <<<"$out" && grep -q "finish check boom" <<<"$out" && grep -q "nothing was merged, tagged or pushed" <<<"$out" && [ "$before" = "$(refs)" ] \
  && [ -z "$(ls "$T/s/finish-intent" 2>/dev/null)" ] && ok "a failing finish check refuses with the tail of its output; no ref moved here or on origin, no tag, no record" || no "failing finish check: rc=$rc $out"
rm -f "$T/fc.fail"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
read -r cwd arg envv ver < <(tail -1 "$T/fc.log")
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ "$arg" = 0.2.0 ] && [ "$envv" = 0.2.0 ] && [ "$ver" = 0.2.0 ] && [ "$cwd" != "$R" ] && [ ! -e "$cwd" ] \
  && ok "a passing finish check lets the finish go on; it ran in a temporary copy of the branch (its VERSION is the release's), {version} replaced, QARGI_RELEASE_VERSION set" || no "passing finish check: rc=$rc cwd=$cwd arg=$arg $out"
mk fcline
jq '.release = {finish_check: "test -f VERSION && echo {version} > /dev/null"}' "$T/c/projects/fcline.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/fcline.json"
out=$($REL start 0.2.0 --date 2026-03-04 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "^plan token: " <<<"$out" && ok "release.finish_check may be a command line" || no "a command line is refused: rc=$rc $out"

# --- site stays in the cut: start, finish and site under one token; publish with that token is refused (a project with no origin: no push step)
ROOT=${DA%/bin/qargi}
R=$T/cutsite; git init -q -b master "$R"
cp -r "$ROOT/lib" "$R/lib"; cp "$ROOT/LICENSE" "$ROOT/README.md" "$R/"; echo 0.5.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.5.0] - 2026-03-01\n\n### Added\n- the first thing\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.5.0 -m 0.5.0 && git -C "$R" branch develop && git -C "$R" checkout -q develop
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a second thing\n\n## [0.5.0] - 2026-03-01\n\n### Added\n- the first thing\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am two
git -C "$R" checkout -q --orphan gh-pages && git -C "$R" rm -rq --cached . && git -C "$R" clean -fdxq
mkdir -p "$R/site"; cp -r "$ROOT/tests/fixtures/site/pages" "$ROOT/tests/fixtures/site/static" "$ROOT/tests/fixtures/site/site.json" "$R/site/"
echo "hand pages and site configuration" > "$R/README.md"
git -C "$R" add -A && git -C "$R" commit -q -m "Site: the hand pages" && git -C "$R" checkout -q -f -b parked develop
jq -n --arg p "$R" '{schema:1, project:"cutsite", methodology:"gitflow", test_command:"true", site:{enabled:true},
  repo:{url:"https://github.com/acme/cutsite", path:$p, long_lived:["master","develop","gh-pages"], detached:["gh-pages"]}}' > "$T/c/projects/cutsite.json"
export QARGI_PROJECT=cutsite
sstate() { jq -r '[.steps[] as $s | $s + ":" + (if .done[$s] then "done" else "pending" end)] | join(" ")' "$T/s/release/cutsite-0.6.0.cut.json"; }
$REL verify 0.6.0 >/dev/null 2>&1
out=$($REL plan 0.6.0 --date 2026-04-01 2>&1); st=$(tok <<<"$out")
grep -q "^4. site: build the documentation site of the tag 0.6.0" <<<"$out" && grep -q "^publish is not in this cut" <<<"$out" && ! grep -q "^[0-9]*\. publish" <<<"$out" && ok "site plan: site is a step of the cut, publish is not" || no "site cut plan: $out"
$REL plan 0.6.0 --date 2026-04-01 --plan "$st" --approved "ship the site too" >/dev/null 2>&1
[ "$(sstate)" = "start:pending finish:pending site:pending" ] && ok "the recorded cut has start, finish and site (no origin, no push)" || no "site cut steps: $(sstate)"
$REL start 0.6.0 --plan "$st" >/dev/null 2>&1; $REL verify 0.6.0 >/dev/null 2>&1
out=$($REL finish 0.6.0 --plan "$st" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.6.0 >/dev/null && [ "$(sstate)" = "start:done finish:done site:pending" ] && ok "finish under the cut with a site step: the tag is made and the cut goes on to site" || no "site cut finish: rc=$rc $out; $(sstate)"
S0=$(git -C "$R" rev-parse gh-pages)
out=$($REL publish 0.6.0 --plan "$st" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "does not cover publish: run publish with its own plan" <<<"$out" && ok "publish with the token of a cut that has a site step is refused too" || no "site cut publish: rc=$rc $out"
out=$(cd "$T/memberrun" && $REL site 0.6.0 --plan "$st" 2>&1); rc=$?
[ "$rc" = 2 ] && [ "$(git -C "$R" rev-parse gh-pages)" = "$S0" ] && ok "site under the cut is refused in a member run: the site branch did not move" || no "site under the cut in a member run: rc=$rc $out"
out=$($REL site 0.6.0 --plan "$st" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(git -C "$R" rev-parse gh-pages)" != "$S0" ] && [ "$(sstate)" = "start:done finish:done site:done" ] && grep '"verb":"release:site"' "$T/s/audit.log" | grep -q '"approved":"ship the site too"' && grep -q "is complete" <<<"$out" \
  && ok "site --plan alone builds the site on the site branch with the recorded words, and the cut is complete" || no "site under the cut: rc=$rc $out; $(sstate)"

# --- a hotfix of a project whose unreleased heading carries the version: a release renames the heading, so master has none; the hotfix start adds
# the heading of the hotfix (empty), a release start is still refused, and the default layout is unchanged
mk nohead
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/nohead.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/nohead.json"
git -C "$R" checkout -q master; printf '# Changelog\n\n## 1.0.0 (2026-01-01)\n\n- first\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "no unreleased heading" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked; $REL verify 1.0.1 >/dev/null 2>&1
out=$($REL start 1.0.1 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "has no '## {version} (unreleased)' section to release" <<<"$out" && ok "a release start on a master with no unreleased heading is refused" || no "release start without the heading: rc=$rc $out"
out=$($REL start 1.0.1 --allow-empty-notes 2>&1); [ "$?" = 1 ] && grep -q "has no '## {version} (unreleased)' section" <<<"$out" && ok "a release start is refused with --allow-empty-notes too" || no "release start --allow-empty-notes: $out"
out=$($REL start 1.0.1 --hotfix --date 2026-05-06 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "CHANGELOG.md: master has no unreleased heading, so the heading for 1.0.1 was added with no entries" <<<"$out" && ok "hotfix start: the plan says the heading was added because master had none" || no "hotfix plan without the heading: rc=$rc $out"
out=$(rstart 1.0.1 --hotfix --date 2026-05-06 2>&1); rc=$?
cl=$(git -C "$R" show hotfix/1.0.1:CHANGELOG.md 2>&1)
[ "$rc" = 0 ] && [ "$cl" = "$(printf '# Changelog\n\n## 1.0.1 (2026-05-06)\n\n## 1.0.0 (2026-01-01)\n\n- first')" ] && ok "hotfix start: the branch's changelog has the new heading, empty, above the newest one" || no "hotfix start without the heading: rc=$rc $out; $cl"
[ "$(git -C "$R" show master:CHANGELOG.md | grep -c '^## 1[.]0[.]1 (')" = 0 ] && ok "master's changelog is untouched" || no "master changed"
# no heading of that level at all: the heading goes to the end
mk nohead2
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/nohead2.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/nohead2.json"
git -C "$R" checkout -q master; printf '# Changelog\n' > "$R/CHANGELOG.md"; git -C "$R" commit -q -am "bare" && git -C "$R" checkout -q parked
rstart 0.1.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
[ "$(git -C "$R" show hotfix/0.1.1:CHANGELOG.md)" = "$(printf '# Changelog\n\n## 0.1.1 (2026-05-06)')" ] && ok "hotfix start: with no heading of the level the new heading goes to the end" || no "heading at the end: $(git -C "$R" show hotfix/0.1.1:CHANGELOG.md 2>&1)"
# the default layout: master has the section, the hotfix renames nothing new and the plan has no such line
mk deflt
out=$($REL start 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && ! grep -q "has no unreleased heading" <<<"$out" && rstart 0.1.1 --hotfix --date 2026-05-06 >/dev/null 2>&1 \
  && [ "$(git -C "$R" show hotfix/0.1.1:CHANGELOG.md)" = "$(printf '# Changelog\n\n## [Unreleased]\n\n## [0.1.1] - 2026-05-06\n\n### Added\n- a thing')" ] && ok "default layout: the hotfix start is as before (the section is kept, the released heading is added)" || no "default layout hotfix: rc=$rc $out"

# --- the finish of a hotfix refuses (at its plan too, before anything moves) while the branch's changelog has no entries under the heading of the
# version; a branch with no CHANGELOG.md is not checked
mk hfin
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/hfin.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/hfin.json"
git -C "$R" checkout -q master; printf '# Changelog\n\n## 1.0.0 (2026-01-01)\n\n- first\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "no unreleased heading" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 1.0.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
m0=$(git -C "$R" rev-parse master)
out=$($REL finish 1.0.1 --hotfix 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the CHANGELOG.md of hotfix/1.0.1 has no entries under '## 1.0.1'" <<<"$out" && grep -q "record the entries under that heading on hotfix/1.0.1" <<<"$out" && ! grep -q "plan token" <<<"$out" \
  && ok "hotfix finish: an empty section of the version is refused at the plan, naming the file, the heading and the fix" || no "finish with the empty section: rc=$rc $out"
w=$($REL fix 1.0.1 --hotfix | sed -n 's/^worktree: //p')
printf '# Changelog\n\n## 1.0.1 (2026-05-06)\n\n- the fix\n\n## 1.0.0 (2026-01-01)\n\n- first\n' > "$w/CHANGELOG.md"; git -C "$w" commit -q -am "record the fix"
out=$($REL finish 1.0.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "changelog check (built in)" <<<"$out" && [ -n "$(tok <<<"$out")" ] && ok "hotfix finish: with an entry committed under the heading the plan is made, and says the check is built in" || no "finish with an entry: rc=$rc $out"
[ "$(git -C "$R" rev-parse master)" = "$m0" ] && ! git -C "$R" rev-parse -q --verify refs/tags/1.0.1 >/dev/null && ok "hotfix finish: the refusals changed nothing (master, no tag)" || no "the refused finish moved something"
$REL verify 1.0.1 --hotfix >/dev/null 2>&1; t=$(tok <<<"$out")
out=$($REL finish 1.0.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/1.0.1 >/dev/null && ok "hotfix finish: applied once the entry is there (tagged)" || no "finish apply: rc=$rc $out"
mk hnofile
git -C "$R" checkout -q master; git -C "$R" rm -q CHANGELOG.md; git -C "$R" commit -q -m "no changelog" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 0.1.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
out=$($REL finish 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 0 ] && ! grep -q "changelog check" <<<"$out" && [ -n "$(tok <<<"$out")" ] && ok "hotfix finish: a branch with no CHANGELOG.md is not checked" || no "finish without a changelog: rc=$rc $out"

exit $fail
