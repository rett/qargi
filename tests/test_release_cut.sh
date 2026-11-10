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
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
cd "$T" || exit 1   # not below the checkout: when that is a member's run directory, approving the cut would be refused as a member's
REL="$DA release"
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
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

# --- the cut: one plan and one approval for start, push, finish and publish
printf '#!/usr/bin/env bash\necho "$*" >> "%s/gh.log"\ncase "$*" in *"pr create"*) echo https://example.net/acme/x/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac\n' "$T" > "$T/gh"
cutstate() { jq -r '[.steps[] as $s | $s + ":" + (if .done[$s] then "done" else "pending" end)] | join(" ")' "$T/s/release/$QARGI_PROJECT-0.2.0.cut.json"; }
mk cut with-origin
: > "$T/gh.log"
out=$($REL plan 0.2.0 --date 2026-03-04 2>&1); ct=$(tok <<<"$out")
[ -n "$ct" ] && grep -q "^1. start: create release/0.2.0 from develop" <<<"$out" && grep -q "^2. push: push release/0.2.0 to origin" <<<"$out" && grep -q "^3. finish: merge release/0.2.0 into master" <<<"$out" \
  && grep -q "THIS IS THE PUSH AND TAG GATE" <<<"$out" && grep -q "^5. publish (optional)" <<<"$out" && ok "plan: one plan lists every step with what moves, and one token" || no "cut plan: $out"
[ ! -e "$T/s/release/cut-0.2.0.cut.json" ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "plan: a plan alone records and changes nothing" || no "the plan changed something"
out=$($REL start 0.2.0 --date 2026-03-04 --plan "$ct" 2>&1); ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "a token of the cut with no approval recorded is no approval: start only prints its plan" || no "start applied without an approval: $out"
out=$($REL plan 0.2.0 --date 2026-03-04 --plan wrongtoken --approved "ship it" 2>&1); rc=$?
[ "$rc" != 0 ] && [ ! -e "$T/s/release/cut-0.2.0.cut.json" ] && ok "approving the cut with another token is refused" || no "wrong token approved: rc=$rc $out"
out=$($REL plan 0.2.0 --date 2026-03-04 --plan "$ct" --approved "ship it" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "$(cutstate)" = "start:pending push:pending finish:pending publish:pending" ] && [ "$(jq -r '.approval.words' "$T/s/release/cut-0.2.0.cut.json")" = "ship it" ] && grep -q "next in the cut $ct: qargi release start 0.2.0 --plan $ct" <<<"$out" \
  && grep -c '"verb":"release:cut"' "$T/s/audit.log" | grep -qx 1 && ok "approving records the words once, the steps and an audit line, and names the next step" || no "approval: rc=$rc $out; $(cat "$T/s/release/cut-0.2.0.cut.json" 2>&1)"
out=$($REL start 0.2.0 --date 2026-03-04 --plan "$ct" --approved again 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "whose approval is recorded" <<<"$out" && ok "a step under the cut takes no words of its own" || no "start with --approved under the cut: rc=$rc $out"
out=$($REL start 0.2.0 --date 2026-04-05 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "does not cover start" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "start under the cut with another date: refused before anything is created" || no "start with another date: rc=$rc $out"
out=$($REL start 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && [ "$(git -C "$R" show release/0.2.0:CHANGELOG.md | grep -c '^## \[0.2.0\] - 2026-03-04')" = 1 ] && [ "$(cutstate)" = "start:done push:pending finish:pending publish:pending" ] \
  && grep -q "next in the cut $ct: qargi release push 0.2.0 --plan $ct" <<<"$out" && grep '"verb":"release:start"' "$T/s/audit.log" | grep -q '"approved":"ship it"' \
  && ok "start --plan alone runs the step: the date is the cut's, the audit line carries the recorded words, the cut shows the step done" || no "start under the cut: rc=$rc $out; $(cutstate)"
out=$($REL finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "the step push of the cut is not done yet" <<<"$out" && ok "finish before push: refused, naming the step" || no "finish before push: rc=$rc $out"
out=$($REL push 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && [ -n "$(git -C "$R" ls-remote origin refs/heads/release/0.2.0)" ] && grep -q "pr create" "$T/gh.log" && [ "$(cutstate)" = "start:done push:done finish:pending publish:pending" ] && ok "push --plan alone pushes the branch and opens the pull request" || no "push under the cut: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$ct" --keep 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q "planned without --keep" <<<"$out" && ok "finish --keep under a cut planned without it is refused" || no "finish --keep: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ -n "$(git -C "$R" ls-remote origin refs/tags/0.2.0)" ] && [ "$(cutstate)" = "start:done push:done finish:done publish:pending" ] \
  && grep '"verb":"release:finish"' "$T/s/audit.log" | grep -q '"approved":"ship it"' && ok "finish --plan alone merges, tags and pushes; the recorded words are on its audit line" || no "finish under the cut: rc=$rc $out"
out=$($REL status 0.2.0 2>&1); grep -q "^  finish: done" <<<"$out" && grep -q "^  publish: pending" <<<"$out" && ok "status shows where the cut is" || no "status: $out"
out=$($REL publish 0.2.0 --plan "$ct" 2>&1); rc=$?
[ "$rc" = 0 ] && grep -q "release create 0.2.0" "$T/gh.log" && [ "$(cutstate)" = "start:done push:done finish:done publish:done" ] && grep -q "is complete" <<<"$out" && ok "publish --plan alone creates the GitHub release; the cut is complete" || no "publish under the cut: rc=$rc $out"
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

exit $fail
