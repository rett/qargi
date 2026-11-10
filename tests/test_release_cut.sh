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

exit $fail
