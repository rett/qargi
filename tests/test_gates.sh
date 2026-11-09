#!/usr/bin/env bash
# Declared gates (the project answer gates): the check at `project set`, `feature verify` running the feature tier in order and stopping at the
# first failure, `release verify` running the feature tier then the release tier, the run record listing each gate, test_command left alone when
# gates are declared and used exactly as before when they are not, and the CI job scan of `release verify` (a warning per job that matches no gate
# name, a note for a name that cannot be read, --strict refusing before anything runs).
# Run: tests/test_gates.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app QARGI_LEAD=lead-one
mkdir -p "$HOME" "$T/c/projects" "$T/s"
R=$T/app; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git -C "$R" checkout -q -b parked
P=$T/c/projects/app.json
$DA project template app | jq --arg p "$R" '.repo.url = "https://github.com/acme/app" | .repo.path = $p | .test_command = "true"' > "$P"
F="$DA feature"; REL="$DA release"
LOG=$T/order
# a gate command that appends its name to the log and exits with the given status
g() { printf 'echo %s >> %s; exit %s' "$1" "$LOG" "${2:-0}"; }
setgates() { jq --argjson g "$1" '.gates = $g' "$P" > "$P.new" && mv "$P.new" "$P"; }   # the answer, written directly
gate() { jq -nc --arg n "$1" --arg c "$2" --arg t "$3" '{name:$n, command:$c, tier:$t}'; }
task() { # name: a task branch with one commit, cut from develop
  git -C "$R" branch "agent/$1" develop; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
devfile() { # path content: a commit on develop that adds a file
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" develop
  mkdir -p "$(dirname "$w/$1")"; printf '%s\n' "$2" > "$w/$1"; git -C "$w" add -A; git -C "$w" commit -q -m "develop $1"
  git -C "$R" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"
}
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }

# --- 1. the answer is checked when it is set
out=$($DA project set app gates '[{"name":"a","command":"true","tier":"feature"},{"name":"a","command":"true","tier":"release"}]' 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'gates\[1\].name: "a" is used twice' <<<"$out" && ! jq -e 'has("gates")' "$P" >/dev/null && ok "set refuses a repeated name, naming the entry, and changes nothing" || no "repeated name rc=$rc: $out"
for bad in '[{"name":"","command":"true","tier":"feature"}]@@gates\[0\].name' '[{"name":"a","command":"","tier":"feature"}]@@gates\[0\].command' \
           '[{"name":"a","command":"true","tier":"nightly"}]@@gates\[0\].tier' '[{"name":"a","command":[],"tier":"feature"}]@@gates\[0\].command' '{"name":"a"}@@gates: a list'; do
  out=$($DA project set app gates "${bad%%@@*}" 2>&1); rc=$?
  [ $rc != 0 ] && grep -q "${bad#*@@}" <<<"$out" && ok "set refuses ${bad%%@@*}" || no "bad gates $bad rc=$rc: $out"
done
out=$($DA project set app gates '[{"name":"build","command":["make","build"],"tier":"feature"},{"name":"package","command":"make package","tier":"release"}]' 2>&1) \
  && jq -e '.gates | length == 2' "$P" >/dev/null && ok "set stores a list of gates (a command as a string or as a list of words)" || no "valid set: $out"
$DA project set app gates '[]' >/dev/null 2>&1 && jq -e '.gates == []' "$P" >/dev/null && ok "an empty list is valid: no gate declared" || no "empty list"
$DA project validate app >/dev/null 2>&1 && ok "project validate accepts the file" || no "validate"
jq 'del(.gates)' "$P" > "$P.new" && mv "$P.new" "$P"

# --- 2. nothing declared: test_command runs, the record has no gates (as before)
$F start plain >/dev/null 2>&1; task p1; $F merge plain agent/p1 >/dev/null 2>&1
jq --arg c "$(g tc)" '.test_command = $c' "$P" > "$P.new" && mv "$P.new" "$P"
: > "$LOG"
out=$($F verify plain 2>&1); rc=$?
[ $rc = 0 ] && grep -q '^full suite: pass at ' <<<"$out" && [ "$(cat "$LOG")" = tc ] && ! grep -q 'gate' <<<"$out" && ! jq -e 'has("gates")' "$T/s/releases/app-feature_plain.json" >/dev/null \
  && ok "without gates test_command runs and no gate is mentioned or recorded" || no "plain verify rc=$rc: $out"
out=$($F status plain 2>&1); ! grep -q 'gates:' <<<"$out" && ok "status shows no gates line" || no "plain status: $out"

# --- 3. feature verify runs the feature tier in order; test_command is not also run
setgates "[$(gate lint "$(g lint)" feature),$(gate unit "$(g unit)" feature),$(gate package "$(g package)" release)]"
$F start gt >/dev/null 2>&1; task g1; $F merge gt agent/g1 >/dev/null 2>&1
: > "$LOG"
out=$($F verify gt 2>&1); rc=$?
[ $rc = 0 ] && [ "$(tr '\n' ' ' < "$LOG")" = "lint unit " ] && ok "the gates of tier feature ran in the order declared, the release gate and test_command did not" || no "feature gates rc=$rc log=$(cat "$LOG"): $out"
grep -q '^full suite: pass at ' <<<"$out" && grep -q '^== gate lint (feature): ' <<<"$out" && grep -q '^== gate unit: pass ' <<<"$out" && ok "the verdict line is unchanged and each gate is shown" || no "gate lines: $out"
grep -q '^note: the answer gates is declared, so ".*" (a test command of the answers) is not run' <<<"$out" && ok "a line says test_command is not run" || no "note: $out"
rec=$T/s/releases/app-feature_gt.json
jq -e '.result == "pass" and (.gates | map(.name + ":" + .result) == ["lint:pass","unit:pass"]) and (.command | startswith("gates: lint="))' "$rec" >/dev/null && ok "the record lists each gate's name and result" || no "record: $(cat "$rec")"
out=$($F status gt 2>&1); grep -q 'full suite: pass at this head' <<<"$out" && grep -qx '  gates: lint pass, unit pass' <<<"$out" && ok "status shows the gates" || no "status: $out"
out=$($F finish gt 2>&1); rc=$?
[ $rc = 0 ] && [ -n "$(tok <<<"$out")" ] && ok "the verified run lets feature finish make its plan" || no "finish plan rc=$rc: $out"
# the same gate under another command is another run
setgates "[$(gate lint "$(g lint2)" feature),$(gate unit "$(g unit)" feature)]"
out=$($F finish gt 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'no passing run' <<<"$out" && ok "a changed gate makes the earlier run stale" || no "stale finish rc=$rc: $out"

# --- 4. the first failure stops the run; the rest is not run
setgates "[$(gate lint "$(g lint)" feature),$(gate unit "$(g unit 1)" feature),$(gate slow "$(g slow)" feature)]"
: > "$LOG"
out=$($F verify gt 2>&1); rc=$?
[ $rc = 1 ] && [ "$(tr '\n' ' ' < "$LOG")" = "lint unit " ] && grep -q '^full suite: fail at ' <<<"$out" && ok "a failing gate stops the run with exit 1 and the fail verdict" || no "failing gate rc=$rc log=$(cat "$LOG"): $out"
grep -qx 'failing gate: unit' <<<"$out" && ok "the failing gate is named" || no "failing gate line: $out"
jq -e '.result == "fail" and (.gates | map(.name + ":" + .result) == ["lint:pass","unit:fail","slow:not run"])' "$rec" >/dev/null && ok "the record has pass, fail and not run" || no "record: $(cat "$rec")"
$F status gt 2>&1 | grep -qx '  gates: lint pass, unit fail, slow not run' && ok "status shows them" || no "status after failure"

# --- 5. a test command that is itself a gate runs once, as a gate; gates that are all release-tier leave a feature verify nothing to run
jq --arg c "$(g unit)" '.test_command = $c' "$P" > "$P.new" && mv "$P.new" "$P"
setgates "[$(gate lint "$(g lint)" feature),$(gate unit "$(g unit)" feature)]"
out=$($F verify gt 2>&1); ! grep -q '^note: the answer gates is declared' <<<"$out" && [ "$(grep -c '^unit$' <<<"$(cat "$LOG")")" -ge 1 ] && ok "no note when test_command is the command of a gate" || no "same command: $out"
setgates "[$(gate package "$(g package)" release)]"
out=$($F verify gt 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'declares no gate of tier feature' <<<"$out" && ok "gates with none of the tier: a verify of nothing is refused" || no "no feature gate rc=$rc: $out"

# --- 6. release verify: the feature tier, then the release tier
setgates "[$(gate lint "$(g lint)" feature),$(gate package "$(g package)" release),$(gate unit "$(g unit)" feature)]"
: > "$LOG"
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 0 ] && [ "$(tr '\n' ' ' < "$LOG")" = "lint unit package " ] && ok "release verify ran the feature gates, then the release gates" || no "release gates rc=$rc log=$(cat "$LOG"): $out"
grep -q '^full suite: pass at ' <<<"$out" && ok "with the same verdict line" || no "release verdict: $out"
rrec=$T/s/releases/app-develop.json
jq -e '.gates | map(.name + ":" + .tier) == ["lint:feature","unit:feature","package:release"]' "$rrec" >/dev/null && ok "its record lists the gates in the order they ran" || no "release record: $(cat "$rrec")"
out=$($REL status 0.9.0 2>&1); grep -qx '  gates: lint pass, unit pass, package pass' <<<"$out" && ok "release status shows them" || no "release status: $out"
setgates "[$(gate lint "$(g lint)" feature),$(gate package "$(g package 1)" release),$(gate late "$(g late)" release)]"
: > "$LOG"
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && [ "$(tr '\n' ' ' < "$LOG")" = "lint package " ] && grep -q '^full suite: fail at ' <<<"$out" && ok "a failing release gate stops the release run" || no "release failure rc=$rc: $out"
setgates "[$(gate lint "$(g lint)" feature)]"
$F verify gt >/dev/null 2>&1
fc=$(jq -r .command "$rec"); $REL verify 0.9.0 >/dev/null 2>&1; rc_=$(jq -r .command "$rrec")
[ "$fc" = "$rc_" ] && ok "with no release gate the two runs have one identity" || no "identities differ: $fc / $rc_"

# --- 7. the CI job scan of release verify
unset_gates() { jq 'del(.gates)' "$P" > "$P.new" && mv "$P.new" "$P"; }
out=$($REL verify 0.9.0 2>&1); [ "$(grep -c 'CI ' <<<"$out")" = 0 ] && ok "no workflow: nothing new is printed" || no "no workflow: $out"
devfile .github/workflows/ci.yml 'name: CI
on: [push]
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - name: not a job
        run: echo hi
  unit:
    name: Unit tests
    runs-on: ubuntu-latest
  deploy:
    name: Deploy to staging
    runs-on: ubuntu-latest
  matrix:
    name: build ${{ matrix.os }}
    runs-on: ubuntu-latest'
setgates "[$(gate lint "$(g lint)" feature),$(gate 'Unit tests' "$(g unit)" feature)]"
: > "$LOG"
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q '^qargi: warning: CI job deploy (Deploy to staging) in .github/workflows/ci.yml matches no declared gate name' <<<"$out" \
  && ! grep -q 'warning: CI job lint' <<<"$out" && ! grep -q 'warning: CI job unit' <<<"$out" && ok "a warning names each job that matches no gate (by id or by name); the verify goes on" || no "warn rc=$rc: $out"
grep -q '^qargi: note: CI job matrix in .github/workflows/ci.yml: its name cannot be read' <<<"$out" && ! grep -q 'warning: CI job matrix' <<<"$out" && ok "a name that cannot be read is a note, not a warning" || no "unknown: $out"
[ "$(tr '\n' ' ' < "$LOG")" = "lint unit " ] && ok "the gates ran" || no "gates after warning: $(cat "$LOG")"
: > "$LOG"
out=$($REL verify 0.9.0 --strict 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'warning: CI job deploy' <<<"$out" && grep -q -- '--strict: 1 CI job(s) match no declared gate name' <<<"$out" && [ ! -s "$LOG" ] && ! grep -q '^running the whole suite' <<<"$out" \
  && ok "--strict refuses before anything runs" || no "strict rc=$rc log=$(cat "$LOG"): $out"
setgates "[$(gate lint "$(g lint)" feature),$(gate 'Unit tests' "$(g unit)" feature),$(gate deploy "$(g deploy)" release)]"
out=$($REL verify 0.9.0 --strict 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q 'warning: CI job' <<<"$out" && grep -q 'note: CI job matrix' <<<"$out" && ok "--strict passes when every job whose name is readable matches (an unknown name never fails)" || no "strict pass rc=$rc: $out"
out=$($F verify gt --strict 2>&1); rc=$?
[ $rc != 0 ] && ok "--strict belongs to release verify" || no "feature --strict: $out"
unset_gates
jq --arg c "$(g tc)" '.test_command = $c' "$P" > "$P.new" && mv "$P.new" "$P"
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 0 ] && [ "$(grep -c '^qargi: warning: CI job' <<<"$out")" = 3 ] && ok "workflows and no gate declared: every job is named as matching no gate, and test_command runs" || no "no gates, workflows rc=$rc: $out"
devfile .github/workflows/flow.yml 'jobs: {a: {runs-on: x}}'
out=$($REL verify 0.9.0 --strict 2>&1); rc=$?
grep -q 'note: CI workflow .github/workflows/flow.yml: its jobs cannot be read' <<<"$out" && ok "a workflow whose jobs cannot be read is a note" || no "flow note: $out"

exit "$fail"
