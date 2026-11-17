#!/usr/bin/env bash
# The ceremony of a release cut: the lock of a finishing verb tells the truth about flock; the bookkeeping file of a merge a finish parked is
# removed when the release is started again; a hotfix is not refused by a preflight that needs content only the hotfix brings; `release plan`
# makes one plan and one approval for the whole cut, bound to the lead that approved it. Offline: a bare repository is the origin, gh is a fake.
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

# --- the approval of the cut is bound to the lead that recorded it (the marshal's identity: QARGI_LEAD, else user@host). Another lead is refused every
# step under it, before anything moves, and is told the remedy; a step by its own plan and approval is not bound. Defence in depth only: QARGI_LEAD is
# not authenticated.
asa() { QARGI_LEAD=lead-a $REL "$@"; }
asb() { QARGI_LEAD=lead-b $REL "$@"; }
# snap: the local refs, the work trees, the refs of origin, the cut records and the audit log, as one hash
snap() { { git -C "$R" for-each-ref; git -C "$R" worktree list --porcelain; git -C "$R" status --porcelain; [ -z "${O:-}" ] || git -C "$O" for-each-ref; cat "$T/s/release/"*.cut.json "$T/s/audit.log" 2>/dev/null; } | md5sum; }
other="was approved under another lead: nothing was changed. That lead runs"
remedy="or this lead asks the owner to approve the step with its own plan"
mk cutlead with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
[ "$(jq -r '.lead.id' "$T/s/release/cutlead-0.2.0.cut.json")" = lead-a ] && ok "approving the cut records the lead that approved it" || no "no lead in the cut record: $(cat "$T/s/release/cutlead-0.2.0.cut.json" 2>&1)"
before=$(snap); out=$(asb start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.2.0 $other start under the cut, $remedy (qargi release start 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "$ct" <<<"$out" && [ "$before" = "$(snap)" ] \
  && ok "another lead (QARGI_LEAD) is refused start under the cut: the message names the remedy and not the token; no ref, record or audit line changed" || no "start by another lead: rc=$rc $out"
before=$(snap); out=$($REL start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.2.0 $other start" <<<"$out" && [ "$before" = "$(snap)" ] && ok "no QARGI_LEAD (the anonymous identity) is another lead too: refused, nothing changed" || no "start, anonymous: rc=$rc $out"
before=$(snap); out=$(QARGI_LEAD='not an id' $REL start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the lead identity cannot be determined (.*not valid.*), so start of 0.2.0 cannot run under the cut: nothing was changed" <<<"$out" && grep -q "$remedy" <<<"$out" && [ "$before" = "$(snap)" ] \
  && ok "an identity that cannot be determined is refused, nothing changed" || no "start with an invalid identity: rc=$rc $out"
out=$(asa start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "the lead that approved the cut runs start under it" || no "start by the approving lead: rc=$rc $out"
before=$(snap); out=$(asb push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.2.0 $other push under the cut, $remedy (qargi release push 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "$ct" <<<"$out" && [ "$before" = "$(snap)" ] \
  && [ -z "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && ok "another lead is refused push under the cut: nothing pushed, no ref, record or audit line changed" || no "push by another lead: rc=$rc $out"
out=$(asa push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && ok "the lead that approved the cut runs push under it" || no "push by the approving lead: rc=$rc $out"
before=$(snap); out=$(asb finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.2.0 $other finish under the cut, $remedy (qargi release finish 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "$ct" <<<"$out" && [ "$before" = "$(snap)" ] \
  && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "another lead is refused finish under the cut: nothing merged, tagged or pushed, no record or audit line changed" || no "finish by another lead: rc=$rc $out"
out=$(asa finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ -n "$(git -C "$R" ls-remote origin refs/tags/0.2.0)" ] && grep '"verb":"release:finish"' "$T/s/audit.log" | tail -1 | grep -q '"approved":"ship it"' \
  && ok "the lead that approved the cut runs finish under it as before" || no "finish by the approving lead: rc=$rc $out"
# a step by its own plan and approval is not bound to the lead of the cut
mk cutown with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1; asa start 0.2.0 --plan "$ct" >/dev/null 2>&1
t=$(asb push 0.2.0 | tok); out=$(asb push 0.2.0 --plan "$t" --approved "b pushes" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && [ "$(jq -r '.done.push.via' "$T/s/release/cutown-0.2.0.cut.json")" = own ] && ok "another lead runs push by its own plan and approval" || no "own push by another lead: rc=$rc $out"
t=$(asb finish 0.2.0 | tok); out=$(asb finish 0.2.0 --plan "$t" --approved "b finishes" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ "$(jq -r '.done.finish.via' "$T/s/release/cutown-0.2.0.cut.json")" = own ] && ok "another lead runs finish by its own plan and approval" || no "own finish by another lead: rc=$rc $out"
# a cut record that names no lead (written before the binding) is refused; before start the message says the cut can be approved again
mk cutold with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
jq 'del(.lead)' "$T/s/release/cutold-0.2.0.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutold-0.2.0.cut.json"
before=$(snap); out=$(asa start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut record of 0.2.0 names no lead (it was approved before a cut was bound to the lead that approved it): nothing was changed. The cut can be approved again, because its start step has not run (qargi release plan 0.2.0 --again, then --plan and --approved)" <<<"$out" \
  && [ "$before" = "$(snap)" ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "a cut record that names no lead is refused before start, nothing changed; the message says to approve the cut again" || no "start under a cut with no lead: rc=$rc $out"
# once the cut has started, --again is no remedy (it discards the record and then refuses: the branch exists): the message names the step's own plan
# and not "approve again", and the refused step leaves the record as it was
mk cutold2 with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1; asa start 0.2.0 --plan "$ct" >/dev/null 2>&1
jq 'del(.lead) | del(.done.start)' "$T/s/release/cutold2-0.2.0.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutold2-0.2.0.cut.json"
before=$(snap); out=$(asa push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut record of 0.2.0 names no lead (it was approved before a cut was bound to the lead that approved it): nothing was changed. Approving the cut again is not offered, because the release has begun (plan --again would discard the record, and refuses while release/0.2.0 or the tag 0.2.0 exists): this step and every later one is run with its own plan (qargi release push 0.2.0, then --plan and --approved)" <<<"$out" \
  && ! grep -q "can be approved again" <<<"$out" && ! grep -q "release plan 0.2.0 --again" <<<"$out" && [ "$before" = "$(snap)" ] && [ -f "$T/s/release/cutold2-0.2.0.cut.json" ] && [ -z "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] \
  && ok "a record that names no lead after start is refused with the own-plan route and no 'approve again'; the record and the refs are as they were" || no "push under a cut with no lead after start: rc=$rc $out"
# the state is read from the record too (start done by the cut, the branch gone): the same wording
jq '.done.start.at = "2026-03-04T00:00:00Z"' "$T/s/release/cutold2-0.2.0.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutold2-0.2.0.cut.json"; git -C "$R" branch -q -D release/0.2.0
out=$(asa push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "nothing was changed. Approving the cut again is not offered, because the release has begun (plan --again would discard the record, and refuses while release/0.2.0 or the tag 0.2.0 exists): this step and every later one is run with its own plan (qargi release push 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "can be approved again" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null \
  && ok "the record's own start step also counts as started (no branch, no tag): the message is true there too" || no "no lead, start done in the record: rc=$rc $out"
# the local tag alone also counts as started (no branch, no start in the record)
mk cutold3 with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
jq 'del(.lead)' "$T/s/release/cutold3-0.2.0.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutold3-0.2.0.cut.json"; git -C "$R" tag 0.2.0
before=$(snap); out=$(asa push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "nothing was changed. Approving the cut again is not offered, because the release has begun (plan --again would discard the record, and refuses while release/0.2.0 or the tag 0.2.0 exists): this step and every later one is run with its own plan (qargi release push 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "can be approved again" <<<"$out" && [ "$before" = "$(snap)" ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null \
  && ok "a local tag alone counts as started: the own-plan route, no 'approve again', nothing changed" || no "no lead, only the tag: rc=$rc $out"
# a hotfix cut names --hotfix in the route of the step; the cut is approved again only before start
mk cutoldh with-origin
out=$(asa plan 0.1.1 --hotfix --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.1.1 --hotfix --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
jq 'del(.lead)' "$T/s/release/cutoldh-0.1.1.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutoldh-0.1.1.cut.json"
out=$(asa start 0.1.1 --hotfix --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "The cut can be approved again, because its start step has not run (qargi release plan 0.1.1 --hotfix --again, then --plan and --approved), or this step is run with its own plan (qargi release start 0.1.1 --hotfix, then --plan and --approved)" <<<"$out" \
  && ok "a hotfix cut with no lead before start: the message names --hotfix in both routes" || no "hotfix cut with no lead: rc=$rc $out"
# and after start: the hotfix branch is named and --hotfix is in the own-plan route
mk cutoldh2 with-origin
out=$(asa plan 0.1.1 --hotfix --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.1.1 --hotfix --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1; asa start 0.1.1 --hotfix --plan "$ct" >/dev/null 2>&1
jq 'del(.lead)' "$T/s/release/cutoldh2-0.1.1.cut.json" > "$T/x.json" && mv "$T/x.json" "$T/s/release/cutoldh2-0.1.1.cut.json"
before=$(snap); out=$(asa push 0.1.1 --hotfix --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "refuses while hotfix/0.1.1 or the tag 0.1.1 exists): this step and every later one is run with its own plan (qargi release push 0.1.1 --hotfix, then --plan and --approved)" <<<"$out" && ! grep -q "release/0.1.1" <<<"$out" && [ "$before" = "$(snap)" ] \
  && ok "a hotfix cut with no lead after start: the message names the hotfix branch and --hotfix in the own-plan route" || no "hotfix cut with no lead after start: rc=$rc $out"

# the hotfix cut is bound to its lead too: a second lead is refused a step of it, nothing changed; the approving lead runs it
mk cuthot with-origin
out=$(asa plan 0.1.1 --hotfix --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.1.1 --hotfix --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
before=$(snap); out=$(asb start 0.1.1 --hotfix --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.1.1 $other start under the cut, $remedy (qargi release start 0.1.1 --hotfix, then --plan and --approved)" <<<"$out" && ! grep -q "$ct" <<<"$out" && [ "$before" = "$(snap)" ] \
  && ! git -C "$R" rev-parse -q --verify refs/heads/hotfix/0.1.1 >/dev/null && ok "the hotfix cut: a second lead is refused start, nothing created or recorded" || no "hotfix start by another lead: rc=$rc $out"
out=$(asa start 0.1.1 --hotfix --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/hotfix/0.1.1 >/dev/null && ok "the hotfix cut: the lead that approved it runs start" || no "hotfix start by the approving lead: rc=$rc $out"

# an identity that cannot be determined at approval time: the approval is refused and no cut record is written
mk cutnoid with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out")
before=$(snap); out=$(QARGI_LEAD='not an id' $REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the lead identity cannot be determined (.*not valid.*), so the cut of 0.2.0 cannot be bound to the lead that approves it: nothing was recorded" <<<"$out" && [ ! -e "$T/s/release/cutnoid-0.2.0.cut.json" ] && [ "$before" = "$(snap)" ] \
  && ok "an identity that cannot be determined at approval: the approval is refused, no cut record is written, no audit line" || no "approval with an invalid identity: rc=$rc $out"

# a finish that was cut off after its push resumes under the cut token: the approving lead completes it, a second lead is refused with nothing changed
mkdir -p "$T/shim"; RG=$(command -v git)
printf '#!/usr/bin/env bash\ncase " $* " in *" push -q --atomic "*) [ -z "${PUSH_LIE:-}" ] || { "%s" "$@"; exit 1; };; esac\nexec "%s" "$@"\n' "$RG" "$RG" > "$T/shim/git"; chmod +x "$T/shim/git"
mk cutres with-origin
out=$(asa plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out"); asa plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" >/dev/null 2>&1
asa start 0.2.0 --plan "$ct" >/dev/null 2>&1; asa push 0.2.0 --plan "$ct" >/dev/null 2>&1
out=$(PATH=$T/shim:$PATH PUSH_LIE=1 asa finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && [ -f "$T/s/finish-intent/cutres-release-0.2.0.json" ] && [ -n "$(git -C "$R" ls-remote origin refs/tags/0.2.0)" ] && ok "finish under the cut is cut off after its push: the intent record stays and origin holds the tag" || no "cut-off finish: rc=$rc $out"
snapi() { { snap; cat "$T/s/finish-intent/"*.json 2>/dev/null; } | md5sum; }
before=$(snapi); out=$(asb finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "the cut of 0.2.0 $other finish under the cut, $remedy (qargi release finish 0.2.0, then --plan and --approved)" <<<"$out" && ! grep -q "$ct" <<<"$out" && [ "$before" = "$(snapi)" ] && [ -f "$T/s/finish-intent/cutres-release-0.2.0.json" ] \
  && ok "the resumed finish is refused to a second lead: the intent record, the refs and the cut record are as they were" || no "resume by another lead: rc=$rc $out"
out=$(asa finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "was cut off" <<<"$out" && [ ! -e "$T/s/finish-intent/cutres-release-0.2.0.json" ] && [ "$(git -C "$R" rev-parse master)" = "$(git -C "$R" ls-remote origin refs/heads/master | cut -f1)" ] && [ "$(jq -r '.done.finish.via' "$T/s/release/cutres-0.2.0.cut.json")" = cut ] \
  && ok "the approving lead resumes the cut-off finish under the cut token: master is what origin has, the record is gone, the cut shows finish done" || no "resume by the approving lead: rc=$rc $out"

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
O=''; before=$(snap); out=$(asb site 0.6.0 --plan "$st" 2>&1); rc=$?   # the cut was approved by the anonymous identity: lead-b is another lead
[ "$rc" = 1 ] && grep -q "the cut of 0.6.0 $other site under the cut, $remedy (qargi release site 0.6.0, then --plan and --approved)" <<<"$out" && ! grep -q "$st" <<<"$out" && [ "$before" = "$(snap)" ] \
  && [ "$(git -C "$R" rev-parse gh-pages)" = "$S0" ] && ok "another lead is refused site under the cut: the site branch did not move, no record or audit line changed" || no "site by another lead: rc=$rc $out"
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

# --- the heading is added only for an unreleased template that carries {version}: any other layout whose master lacks it is refused for a hotfix too
mk nover
git -C "$R" checkout -q master; printf '# Changelog\n\n## [0.1.0] - 2026-01-01\n\n- first\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "no unreleased heading" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
out=$($REL start 0.1.1 --hotfix --allow-empty-notes 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "has no '## \[Unreleased\]' section to release. Fix: add one" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/hotfix/0.1.1 >/dev/null && ok "default layout: a master without '## [Unreleased]' is refused for a hotfix (add one), also with --allow-empty-notes" || no "default layout, no heading: rc=$rc $out"
jq '.release = {changelog: {unreleased: "## Next"}}' "$T/c/projects/nover.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/nover.json"
out=$($REL start 0.1.1 --hotfix 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "has no '## Next' section to release" <<<"$out" && ok "an unreleased template without {version}: a hotfix on a master without that heading is refused" || no "template without version: rc=$rc $out"

# --- where the added heading goes: above the first heading that follows the released template (any version and date), not above a `## Format` note, and
# not by a heading inside a fenced block; a file with no trailing newline keeps none; with no heading of the template it goes above the first of the level;
# --allow-empty-notes changes nothing on this path
mk place
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/place.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/place.json"
git -C "$R" checkout -q master; printf '# Changelog\n\n## Format\n\nan entry is a bullet\n\n```\n## 9.9.9 (2020-01-01)\n```\n\n## 1.0.0 (2026-01-01)\n\n- first' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "a note above the sections, a fenced heading, no trailing newline" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 1.0.1 --hotfix --allow-empty-notes --date 2026-05-06 >/dev/null 2>&1
git -C "$R" show hotfix/1.0.1:CHANGELOG.md | cmp -s - <(printf '# Changelog\n\n## Format\n\nan entry is a bullet\n\n```\n## 9.9.9 (2020-01-01)\n```\n\n## 1.0.1 (2026-05-06)\n\n## 1.0.0 (2026-01-01)\n\n- first') \
  && ok "hotfix start: the heading goes above the first version section, not above '## Format' or a fenced heading; no trailing newline is added; --allow-empty-notes is the same" || no "placement: $(git -C "$R" show hotfix/1.0.1:CHANGELOG.md 2>&1)"
mk place2
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/place2.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/place2.json"
git -C "$R" checkout -q master; printf '# Changelog\n\n## Notes\n\n- x\n' > "$R/CHANGELOG.md"; git -C "$R" commit -q -am "no version heading" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 1.0.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
git -C "$R" show hotfix/1.0.1:CHANGELOG.md | cmp -s - <(printf '# Changelog\n\n## 1.0.1 (2026-05-06)\n\n## Notes\n\n- x\n') && ok "hotfix start: with no heading that follows the released template the heading goes above the first of its level" || no "fallback placement: $(git -C "$R" show hotfix/1.0.1:CHANGELOG.md 2>&1)"

# --- CRLF: a changelog with Windows line endings keeps them (the heading is added with the file's own newline, a renamed or inserted heading too), and
# a blank line of such a file under the new heading is not an entry for the finish check
mk crlf
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/crlf.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/crlf.json"
git -C "$R" checkout -q master; printf '# Changelog\r\n\r\n## 1.0.0 (2026-01-01)\r\n\r\n- first\r\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "crlf" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 1.0.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
git -C "$R" show hotfix/1.0.1:CHANGELOG.md | cmp -s - <(printf '# Changelog\r\n\r\n## 1.0.1 (2026-05-06)\r\n\r\n## 1.0.0 (2026-01-01)\r\n\r\n- first\r\n') && ok "CRLF changelog: the added heading uses CRLF and no line ending changes" || no "crlf added heading: $(git -C "$R" show hotfix/1.0.1:CHANGELOG.md 2>&1 | od -c | head -5)"
out=$($REL finish 1.0.1 --hotfix 2>&1); [ "$?" = 1 ] && grep -q "has no entries under '## 1.0.1'" <<<"$out" && ok "CRLF changelog: an empty section is refused by the finish check (a bare CR is not an entry)" || no "crlf finish: $out"
mk crlf2
git -C "$R" checkout -q master; printf '# Changelog\r\n\r\n## [Unreleased]\r\n\r\n### Added\r\n- a thing\r\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am "crlf" && git -C "$R" branch -f develop master && git -C "$R" checkout -q parked
rstart 0.1.1 --hotfix --date 2026-05-06 >/dev/null 2>&1
git -C "$R" show hotfix/0.1.1:CHANGELOG.md | cmp -s - <(printf '# Changelog\r\n\r\n## [Unreleased]\r\n\r\n## [0.1.1] - 2026-05-06\r\n\r\n### Added\r\n- a thing\r\n') && ok "CRLF changelog, default layout: the released heading is inserted with CRLF and nothing else changes" || no "crlf default layout: $(git -C "$R" show hotfix/0.1.1:CHANGELOG.md 2>&1 | od -c | head -8)"

exit $fail
