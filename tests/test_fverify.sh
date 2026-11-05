#!/usr/bin/env bash
# The feature checkpoint reads: why `feature status` calls the whole-suite result stale, what a failed `feature verify` prints last, what the
# `feature finish` plan says about pushing develop, and the warning of `feature verify` and `release verify` when another suite may be running.
# Run: tests/test_fverify.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/s"
R=$T/app; git init -q -b master "$R"; git init -q --bare "$T/origin.git"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n' > "$R/CHANGELOG.md"
# the repository carries the suite runner of this repository and a manifest of two steps of its own: one passes, one fails with a named test
mkdir -p "$R/tests"; cp tests/run.sh "$R/tests/run.sh"
printf '#!/bin/sh\necho "ok   fine"\n' > "$R/tests/test_good.sh"
printf '#!/bin/sh\necho "ok   fine"\necho "FAIL the second check of the bad step"\nexit 1\n' > "$R/tests/test_bad.sh"
printf 'fast | par | 30 | 5 | sh tests/test_good.sh\nfast | par | 30 | 5 | sh tests/test_bad.sh\n' > "$R/tests/suite.txt"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
task() { # name: a task branch with one commit, cut from develop
  git -C "$R" branch "agent/$1" develop; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
devcommit() { # name: a commit on develop
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" develop
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "develop $1"
  git -C "$R" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"
}
setcmd() { jq --arg c "$1" '.test_command = $c' "$T/c/projects/app.json" > "$T/c/projects/app.new" && mv "$T/c/projects/app.new" "$T/c/projects/app.json"; }   # the project's test command
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }

# --- 1. status says why the result is stale, and what to do
$F start why >/dev/null 2>&1
out=$($F status why 2>&1)
grep -q "full suite: not run on this branch" <<<"$out" && grep -q "next: qargi feature verify why" <<<"$out" && ok "status of a feature never verified names the next step" || no "never verified: $out"
task a1; task a2; $F merge why agent/a1 >/dev/null 2>&1; $F verify why >/dev/null 2>&1
out=$($F status why 2>&1)
grep -q "full suite: pass at this head" <<<"$out" && ! grep -q "next: qargi feature verify" <<<"$out" && ! grep -q "^  why: " <<<"$out" && ok "a current result says nothing more" || no "current: $out"
ran=$(git -C "$R" rev-parse --short feature/why)
$F merge why agent/a2 >/dev/null 2>&1; m1=$(git -C "$R" rev-parse --short feature/why)
out=$($F status why 2>&1)
grep -q "full suite: pass at an older head ($ran)" <<<"$out" && grep -q "why: feature/why moved after that run by 1 commit(s):" <<<"$out" \
  && grep -q "    $m1 Merge branch 'agent/a2' into feature/why (a branch was merged in)" <<<"$out" && grep -q "next: qargi feature verify why" <<<"$out" \
  && ok "after a task merge it names the merge commit and the next step" || no "after merge: $out"
$F verify why >/dev/null 2>&1; devcommit d1; $F sync why >/dev/null 2>&1; m2=$(git -C "$R" rev-parse --short feature/why)
out=$($F status why 2>&1)
grep -q "    $m2 Merge branch 'develop' into feature/why (develop was synced in)" <<<"$out" && ok "after a sync it says develop was synced in" || no "after sync: $out"
$F verify why >/dev/null 2>&1
for i in 1 2 3 4 5 6 7; do task "b$i"; $F merge why "agent/b$i" >/dev/null 2>&1; done
out=$($F status why 2>&1)
grep -q "moved after that run by 7 commit(s)" <<<"$out" && grep -q "\.\.\. and 2 more" <<<"$out" && [ "$(grep -c "^    [0-9a-f]\{7,\} Merge" <<<"$out")" = 5 ] && ok "a long stale stretch lists five commits and counts the rest" || no "long: $out"
git -C "$R" update-ref refs/heads/feature/why "$(git -C "$R" rev-parse develop)"
out=$($F status why 2>&1)
grep -q "why: the run's commit is not in the history of feature/why" <<<"$out" && ok "a branch reset since the run is told so" || no "reset: $out"

# --- 2. a failed verify ends with the failing steps and tests, and the log
REL="$DA release"
setcmd 'bash tests/run.sh -j 2'
$F start bad >/dev/null 2>&1; task c1; $F merge bad agent/c1 >/dev/null 2>&1
out=$($F verify bad 2>&1); rc=$?
tail -n 6 <<<"$out" > "$T/last"
[ $rc = 1 ] && grep -q '^full suite: fail at ' <<<"$out" && ok "a failed verify exits 1 and says the suite failed" || no "failed verify rc=$rc: $out"
lg=$T/s/suite-logs/app.feature-bad.log
grep -qx 'failing steps:' "$T/last" && grep -qx '  sh tests/test_bad.sh' "$T/last" && grep -qx 'failing tests:' "$T/last" && grep -qx '  FAIL the second check of the bad step' "$T/last" \
  && ! grep -q 'test_good' "$T/last" && ok "the last lines name the failing step and test, not the passing ones" || no "last lines: $(cat "$T/last")"
[ "$(tail -n 1 <<<"$out")" = "log of the whole run: $lg" ] && [ -f "$lg" ] && grep -q '^total: .*FAILED' "$lg" && [ "$(stat -c %a "$lg")" = 600 ] && ok "the last line is the log of the run, which holds the whole report (mode 600)" || no "log line: $(tail -n 1 <<<"$out")"
grep -q '^logs of the failed steps: ' <<<"$out" && ok "the runner's own step logs are named too" || no "step logs: $out"
$F status bad 2>&1 | grep -q 'full suite: fail at this head' && ok "status says fail at this head" || no "status after failed verify"
setcmd 'echo some output; exit 3'
out=$($F verify bad 2>&1); rc=$?
[ $rc = 1 ] && grep -qx 'no failing test name in the output; its last lines:' <<<"$out" && grep -qx '  some output' <<<"$out" && [ "$(tail -n 1 <<<"$out")" = "log of the whole run: $lg" ] \
  && ok "a test command that is no runner: its last lines stand in, then the log" || no "plain command: $out"
setcmd 'bash tests/run.sh -j 2'
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && grep -qx '  sh tests/test_bad.sh' <<<"$out" && [ "$(tail -n 1 <<<"$out")" = "log of the whole run: $T/s/suite-logs/app.release-0.9.0.log" ] && ok "release verify ends the same way" || no "release verify: $out"
setcmd 'exit 0'

[ "$fail" = 0 ] && echo "all fverify tests passed"
exit "$fail"
