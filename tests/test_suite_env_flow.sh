#!/usr/bin/env bash
# verify.environment in the flow verbs (lib/gitflow.sh, feature.sh, release.sh; the launcher is lib/suite_env.py): `feature verify` and `release verify`
# run the suite, or each gate, through the launcher when the answer is set and exactly as before when it is off or null; the refusal codes of the attempt,
# the per-run waiver (token, the owner's words, audit line, record), the suite record and its staleness, and an answers file that was edited by hand.
# systemd-run is a stand-in (tests/fixtures/fake-systemd-run) except in the last case, which uses the real one where it works and otherwise prints an
# `expected:` line. Scratch homes only; the real ~/.qargi is never touched.
# Run: tests/test_suite_env_flow.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; SE=$PWD/lib/suite_env.py; ROOT=$PWD
trap 'rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app QARGI_LEAD=lead-one
mkdir -p "$HOME" "$T/c/projects" "$T/s"
R=$T/app; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git -C "$R" checkout -q -b parked
P=$T/c/projects/app.json
$DA project template app | jq --arg p "$R" '.repo.url = "https://github.com/acme/app" | .repo.path = $p | .test_command = "true"' > "$P"
# a verb run from below the directory of a member's run is a member run, where the waiver refuses: the verbs run from the scratch directory, outside any run
cd "$T" || exit 1
F="$DA feature"; REL="$DA release"
FREC=$T/s/releases/app-feature_f.json; DREC=$T/s/releases/app-develop.json
# the stand-in for systemd-run: first on PATH, steered by a mode file, logging each call
mkdir -p "$T/fakebin"; cp "$ROOT/tests/fixtures/fake-systemd-run" "$T/fakebin/systemd-run"; chmod +x "$T/fakebin/systemd-run"
export FAKE_SYSTEMD_MODE_FILE=$T/mode FAKE_SYSTEMD_LOG=$T/fakelog
PATH_PLAIN=$PATH
mode() { printf '%s\n' "$1" > "$T/mode"; }
fake() { PATH=$T/fakebin:$PATH_PLAIN; export PATH; }
nofake() { PATH=$PATH_PLAIN; export PATH; }
fake
run() { "$@" >"$T/o" 2>"$T/e"; rc=$?; }
saw() { out | grep -qE -- "$1"; }
setcmd() { jq --arg c "$1" '.test_command = $c' "$P" > "$P.new" && mv "$P.new" "$P"; }
# the declaration as `project set` leaves it: in the answers, and the same one as the accepted declaration in the state (T2's job; written here by hand)
setenv() {
  jq --argjson d "$1" '.verify = {environment: $d}' "$P" > "$P.new" && mv "$P.new" "$P"
  python3 -I "$SE" approved set app "$1" --by test --state "$T/s" >/dev/null
}
unsetenv() { jq 'del(.verify)' "$P" > "$P.new" && mv "$P.new" "$P"; python3 -I "$SE" approved set app null --by test --state "$T/s" >/dev/null; }
rawenv() { jq --argjson d "$1" '.verify = {environment: $d}' "$P" > "$P.new" && mv "$P.new" "$P"; }   # a hand edit of the answers file only
calls() { grep -c "^argv-ok" "$T/fakelog" 2>/dev/null || true; }
reset() { rm -f "$T/ran" "$T/fakelog" "$FREC" "$DREC"; }
setcmd "echo suite-ran; touch $T/ran"
$F start f >/dev/null 2>&1

# offscen: the verbs with the setting off, run in order and printed normalised (a sha, the scratch directory, the times). tests/fixtures/suite-env-off.golden is
# what the tree before verify.environment printed for it (the tree at 791595a1, before the flow verbs used the launcher); this tree must print the same, byte for byte.
# The one difference is the state listing at its end: the history of the runs (history/PROJECT.jsonl and suite-logs/runs/, lib/history.py) is new, added to the listing by hand.
# OFF_GOLDEN_WRITE=FILE OFF_GOLDEN_ONLY=1 writes the file from the tree under test: only a deliberate change of what the verbs print with the setting off may do that.
offscen() {
  say() { echo "### $*"; "$DA" "$@" 2>&1; echo "rc=$?"; }
  setcmd "echo suite-ran; touch $T/ran"; reset
  say feature verify f; say feature status f; say release verify 0.2.0; say release status 0.2.0
  echo "### records"; jq -S 'del(.at, .seconds)' "$FREC" "$DREC"
  setcmd "echo before-fail; exit 3"
  say feature verify f; say feature status f; say release verify 0.2.0; say release status 0.2.0
  echo "### records"; jq -S 'del(.at, .seconds)' "$FREC" "$DREC"
  echo "### state"; (cd "$T/s" && find . -mindepth 1 -maxdepth 2 | sort | grep -v -e '^./audit' -e '^./ref-journal' -e '^./marshal' -e '^./locks' -e '^./leases')
}
offnorm() { sed -e '/^  lead: /d' -e "s#$T#TMP#g" -e 's/[0-9a-f]\{7,40\}/SHA/g' -e 's/ran [0-9TZ:-]*/ran AT/g' -e 's/took [0-9][0-9]*s/took Ns/g' -e 's/([0-9][0-9]*s)/(Ns)/g'; }
if [ -n "${OFF_GOLDEN_WRITE:-}" ]; then offscen 2>&1 | offnorm > "$OFF_GOLDEN_WRITE"; [ -z "${OFF_GOLDEN_ONLY:-}" ] || exit 0; fi
if [ -z "${OFF_GOLDEN_ONLY:-}" ]; then
  offscen 2>&1 | offnorm > "$T/off.now"
  if diff -u "$ROOT/tests/fixtures/suite-env-off.golden" "$T/off.now" > "$T/off.diff" 2>&1; then ok "off: the output, the records and the state files of feature verify and status and release verify and status are what the tree before verify.environment made, byte for byte"
  else no "off: differs from the tree before verify.environment: $(head -30 "$T/off.diff")"; fi
fi

# --- 1. off (unset, then null): the suite runs as it always did, and nothing of the launcher is seen
setcmd "cat /proc/\$PPID/comm > $T/ppid; echo suite-ran; touch $T/ran"
reset; run $F verify f
[ "$rc" = 0 ] && saw '^full suite: pass at ' && ! saw 'verify.environment' && [ -f "$T/ran" ] && ok "off (unset): the suite runs and the verdict line is the old one" || no "off: rc=$rc: $(out)"
case $(cat "$T/ppid") in python*) no "off (unset): the suite command is started by the launcher ($(cat "$T/ppid"))";; *) ok "off (unset): the suite command is not started by the launcher (its parent is $(cat "$T/ppid"))";; esac
[ "$(jq -S -c 'del(.at, .seconds) | keys' "$FREC")" = '["command","mode","result","sha"]' ] && ok "off (unset): the record has the old members only, no environment" || no "off record: $(cat "$FREC")"
[ ! -s "$T/fakelog" ] && [ ! -e "$T/s/verify-env.json" ] && ok "off (unset): systemd-run is never asked and no state file is written" || no "off: fakelog $(cat "$T/fakelog" 2>&1)"
v1=$(out | sed 's/[0-9a-f]\{7,\}/SHA/g')
unsetenv; jq '.verify = {environment: null}' "$P" > "$P.new" && mv "$P.new" "$P"
reset; run $F verify f
[ "$rc" = 0 ] && [ "$(out | sed 's/[0-9a-f]\{7,\}/SHA/g')" = "$v1" ] && [ "$(jq -S -c 'del(.at, .seconds) | keys' "$FREC")" = '["command","mode","result","sha"]' ] \
  && ok "off (null): the same output and the same record as unset" || no "off null: rc=$rc: $(out)"
run $F status f
[ "$rc" = 0 ] && saw 'full suite: pass at this head' && ! saw 'verify.environment' && ! saw 'why:' && ok "off: status says nothing of verify.environment" || no "off status: $(out)"

# --- 2. the four codes of the cpu part: nothing runs, nothing is recorded, a token follows
setcmd "echo suite-ran; touch $T/ran"
setenv '{"cpu_quota":"max"}'
mode ok
reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-cpu-readback' && saw '^plan token: [0-9a-f]{12}' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && grep -qx 'argv-ok CPUWeight=100' "$T/fakelog" && ! grep -q 'argv-BAD' "$T/fakelog" \
  && ok "cpu-readback: a run that is not in a scope of its own is refused; the scope route's argument list is the fixed one; nothing ran or was recorded" || no "readback: rc=$rc: $(out); $(cat "$T/fakelog" 2>&1)"
setenv '{"cpu_quota":"200%"}'
reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-cpu-readback' && grep -qx 'argv-ok CPUQuota=200%' "$T/fakelog" && ! grep -q 'argv-BAD' "$T/fakelog" && ok "cpu-readback with a quota: the property is CPUQuota=200%" || no "quota: $(out); $(cat "$T/fakelog" 2>&1)"
setenv '{"cpu_quota":"max"}'
mode old; reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-cpu-systemd-too-old' && saw '254' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ! grep -q argv-ok "$T/fakelog" && ok "cpu-systemd-too-old: systemd 253 is refused before anything runs" || no "old: rc=$rc: $(out)"
mode nouser; reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-cpu-no-user-manager' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "cpu-no-user-manager: a scope that cannot be made is refused, not a test failure" || no "nouser: rc=$rc: $(out)"
mkdir -p "$T/farm"
for d in ${PATH_PLAIN//:/ }; do for f in "$d"/*; do [ -e "$f" ] || continue; b=${f##*/}; case $b in systemd-run*) continue;; esac; [ -e "$T/farm/$b" ] || ln -s "$f" "$T/farm/$b"; done; done
# shellcheck disable=SC2123  # a PATH with no systemd-run in it, on purpose
PATH=$T/farm; export PATH; reset; run $F verify f; nofake; fake
[ "$rc" = 1 ] && saw 'verify-env-cpu-no-systemd-run' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "cpu-no-systemd-run: no systemd-run on PATH is refused" || no "no systemd-run: rc=$rc: $(out)"
# every refusal names the code, the part, what was found and the waiver command
mode nouser; run $F verify f
saw 'qargi: verify-env-cpu-no-user-manager: cpu: ' && saw -- '--waive-environment cpu --plan [0-9a-f]{12} --approved' && ok "a refusal names the code, the part, what was found and the waiver command" || no "refusal text: $(out)"

# --- 3. the waiver: refused parts only, the owner's words, a token for exactly those parts
tok=$(tokof "$(out)")
reset; run $F verify f --waive-environment cpu
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && saw '^plan token: ' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "a waiver without --plan and --approved is refused" || no "waive no words: rc=$rc: $(out)"
run $F verify f --waive-environment cpu --plan "$tok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && [ ! -f "$FREC" ] && ok "a waiver with the token and no words is refused" || no "waive no words 2: $(out)"
run $F verify f --waive-environment cpu --plan 000000000000 --approved "ok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && [ ! -f "$FREC" ] && ok "a waiver with the wrong token is refused" || no "waive wrong token: $(out)"
run $F verify f --waive-environment fds --plan "$tok" --approved "ok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && saw 'does not name every refused part' && [ "$(tokof "$(out)")" = "$tok" ] && [ ! -f "$FREC" ] && [ ! -f "$T/ran" ] && ok "a waiver for another part than the refused one is refused, with a token for the refused one" || no "waive other part: $(out)"
run $F verify f --waive-environment env --plan "$tok" --approved "ok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unknown' && saw 'env cannot fail' && [ ! -f "$FREC" ] && ok "env cannot be waived" || no "waive env: $(out)"
run $F verify f --waive-environment bogus --plan "$tok" --approved "ok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unknown' && [ ! -f "$FREC" ] && ok "a part that is not one is refused as unknown" || no "waive bogus: $(out)"
run $F verify f --waive-environment cpu,cpu,fds --plan "$tok" --approved "ok"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && ok "a waiver for more than the refused parts is refused" || no "waive too many: $(out)"
reset; : > "$T/audit.before"; cp "$T/s/audit.log" "$T/audit.before" 2>/dev/null || true
run $F verify f --waive-environment cpu --plan "$tok" --approved "the owner said run it without the scope"
[ "$rc" = 0 ] && saw '^full suite: pass at [0-9a-f]+ \(verify.environment: cpu waived-failed\)$' && saw 'waived for this run and goes on without it \(verify-env-cpu-no-user-manager\)' && [ -f "$T/ran" ] \
  && ok "with the token and the words the run passes, warns, and the verdict says cpu waived-failed" || no "waived run: rc=$rc: $(out)"
[ "$(jq -r '.environment.parts | [.cpu, .signals, .fds, .tty, .env] | join(",")' "$FREC")" = "waived-failed,applied,applied,applied,applied" ] \
  && [ "$(jq -c '.environment.codes' "$FREC")" = '["verify-env-cpu-no-user-manager"]' ] && [ "$(jq -r '.environment.cleanup' "$FREC")" = pgroup ] \
  && ok "the record: cpu waived-failed with its code, the other parts applied, cleanup by process group" || no "waived record: $(cat "$FREC")"
[ "$(jq -r '.environment.id' "$FREC")" = "$(python3 -I "$SE" id '{"cpu_quota":"max"}')" ] && ok "the record's id is the id of the declaration" || no "record id: $(jq -r '.environment.id' "$FREC")"
[ "$(calls)" = 1 ] && ok "the launcher's attempt (the probe) is the only call of systemd-run: the suite command ran with --no-scope" || no "calls: $(calls): $(cat "$T/fakelog")"
tail -1 "$T/s/audit.log" | jq -e '.verb == "verify:environment-waived" and .approved == "the owner said run it without the scope" and (.detail | test("cpu"))' >/dev/null \
  && ok "the audit log holds verify:environment-waived with the owner's words" || no "audit: $(tail -1 "$T/s/audit.log")"
run $F status f
[ "$rc" = 0 ] && saw 'full suite: pass at this head' && saw 'verify.environment: cpu waived-failed \(verify-env-cpu-no-user-manager\)' && ok "status shows the waiver again" || no "status waiver: $(out)"
run $F finish f
[ "$rc" = 0 ] && saw '^plan token: ' && saw 'verify.environment: cpu waived-failed' && ok "a waived run satisfies finish, and the finish plan shows the waiver again" || no "finish plan: rc=$rc: $(out)"
# a token is good for one run: the same --plan and --approved at the same head are refused (nothing runs, nothing is audited), the refusal of the attempt prints the next
# token, and the retry takes that one
reset; na=$(grep -c 'verify:environment-waived' "$T/s/audit.log")
run $F verify f --waive-environment cpu --plan "$tok" --approved "the owner said run it without the scope"
tokb=$(tokof "$(out)")
[ "$rc" = 1 ] && saw 'verify-env-waive-used' && [ -n "$tokb" ] && [ "$tokb" != "$tok" ] && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = "$na" ] \
  && ok "a second use of the token at the same head is refused: nothing ran, nothing was audited, and the refusal prints the next token" || no "second use: rc=$rc: $(out)"
run $F verify f --waive-environment cpu --plan "$tokb" --approved "the owner said so again"
[ "$rc" = 0 ] && [ -f "$T/ran" ] && [ "$(jq -r '.environment.parts.cpu' "$FREC")" = waived-failed ] && ok "the retry takes the new token and runs under the waiver" || no "retry: rc=$rc: $(out)"
reset; run $F verify f --waive-environment cpu --plan "$tokb" --approved "the owner said so again"
[ "$rc" = 1 ] && saw 'verify-env-waive-used' && [ ! -f "$T/ran" ] && ok "and that token is spent too" || no "third use: rc=$rc: $(out)"
# the token is of this head: a feature that moved needs a new refusal
git -C "$R" branch -q agent/x develop; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" agent/x; echo x > "$w/x.txt"; git -C "$w" add -A; git -C "$w" commit -q -m x; git -C "$R" worktree remove --force "$w"
$F merge f agent/x >/dev/null 2>&1
run $F verify f --waive-environment cpu --plan "$tok" --approved "the owner said run it without the scope"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && ok "the token of an earlier head does not cover the new one" || no "old token: rc=$rc: $(out)"
# a waiver stands on a refusal: with cpu_quota null the attempt passes and refuses nothing, so no token is printed and no waiver is accepted; a part that is off is no part to waive
setenv '{"cpu_quota":null}'
reset; run $F verify f --waive-environment fds
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && saw 'refused no part' && ! saw 'plan token' && [ ! -f "$FREC" ] && [ ! -f "$T/ran" ] && ok "a waiver when the attempt refused nothing is refused and prints no token" || no "waive nothing refused: rc=$rc: $(out)"
run $F verify f --waive-environment fds --plan 000000000000 --approved "owner words"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && ! saw 'plan token' && [ ! -f "$FREC" ] && [ ! -f "$T/ran" ] && ok "with a token and words too: no refusal printed that token" || no "waive nothing refused 2: rc=$rc: $(out)"
run $F verify f --waive-environment cpu --plan 000000000000 --approved "owner words"
[ "$rc" = 1 ] && saw 'verify-env-waive-unknown' && saw 'cpu is off' && ! saw 'plan token' && [ ! -f "$FREC" ] && ok "a part that is off (cpu with cpu_quota null) cannot be waived" || no "waive off part: rc=$rc: $(out)"
# a waiver is the owner's: in a member run (the marked environment, or a directory of a run) --waive-environment with --approved is refused before anything is made, and the same call outside it runs
setenv '{"cpu_quota":"max"}'; mode nouser
reset; run $F verify f
tokm=$(tokof "$(out)"); na=$(grep -c 'verify:environment-waived' "$T/s/audit.log")
reset; QARGI_MEMBER_RUN=1 run $F verify f --waive-environment cpu --plan "$tokm" --approved "a member made these words up"
[ "$rc" = 2 ] && saw 'not available in a member run' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = "$na" ] && ok "a member run (marked environment) cannot waive with --approved: refused, nothing ran, nothing audited" || no "member mark: rc=$rc: $(out)"
mkdir -p "$T/mrun"; : > "$T/mrun/ability"; : > "$T/mrun/refs.before"
cd "$T/mrun" || exit 1; run $F verify f --waive-environment cpu --plan "$tokm" --approved "a member made these words up"; cd "$T" || exit 1
[ "$rc" = 2 ] && saw 'not available in a member run' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "a member run (below a run directory) cannot waive with --approved either" || no "member dir: rc=$rc: $(out)"
run $F verify f --waive-environment cpu --plan "$tokm" --approved "the owner said so"
[ "$rc" = 0 ] && [ -f "$T/ran" ] && [ "$(jq -r '.environment.parts.cpu' "$FREC")" = waived-failed ] && ok "the same call outside a member run is accepted" || no "owner waiver: rc=$rc: $(out)"
# the setting off: nothing to waive
unsetenv
run $F verify f --waive-environment cpu --plan x --approved y
[ "$rc" = 1 ] && saw 'verify-env-waive-unknown' && saw 'off for app' && ok "a waiver with the setting off is refused as unknown" || no "waive off: $(out)"
run $F status f --waive-environment cpu
[ "$rc" = 2 ] && saw 'belongs to feature verify' && ok "--waive-environment is for verify only" || no "waive on status: rc=$rc $(out)"

# --- 3b. the claim of a waiver comes first, and a deleted claim file does not make its token good again
# a second verify that holds the same token and loses the claim (planted during the launcher's attempt, which comes after the token was read and before the claim)
# runs nothing and touches nothing: not the log, not the reports of the winner, not the audit log
setenv '{"cpu_quota":"max"}'; mode nouser
WD=$T/s/verify-env-waivers
reset; run $F verify f; tokr=$(tokof "$(out)")
key=$(printf '%s\n' app feature/f "$(git -C "$R" rev-parse feature/f)" "$(python3 -I "$SE" id '{"cpu_quota":"max"}')" | sha256sum | cut -c1-12)
mkdir -p "$WD" "$T/racebin"
printf '#!/bin/sh\n[ ! -s "$RACE_PLANT" ] || { : > "$(cat "$RACE_PLANT")"; rm -f "$RACE_PLANT"; }\nexec "%s" "$@"\n' "$T/fakebin/systemd-run" > "$T/racebin/systemd-run"; chmod +x "$T/racebin/systemd-run"
nclaims=$(find "$WD" -name "$key.[0-9]*" | wc -l)
mkdir -p "$T/s/suite-logs/app.feature-f.env"; echo winner > "$T/s/suite-logs/app.feature-f.log"; echo winner > "$T/s/suite-logs/app.feature-f.env/gate.json"
printf '%s\n' "$WD/$key.$nclaims" > "$T/plant"; na=$(grep -c 'verify:environment-waived' "$T/s/audit.log")
PATH=$T/racebin:$T/fakebin:$PATH_PLAIN; export PATH
reset; RACE_PLANT=$T/plant run $F verify f --waive-environment cpu --plan "$tokr" --approved "the owner said so"
fake
[ "$rc" = 1 ] && saw 'verify-env-waive-used' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && [ -e "$WD/$key.$nclaims" ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = "$na" ] \
  && [ "$(cat "$T/s/suite-logs/app.feature-f.log")" = winner ] && [ "$(cat "$T/s/suite-logs/app.feature-f.env/gate.json")" = winner ] \
  && ok "a verify that loses the claim of the waiver runs nothing and leaves the log, the reports and the audit log of the winner as they were" || no "lost claim: rc=$rc: $(out)"
reset; run $F verify f; tokr2=$(tokof "$(out)")
reset; run $F verify f --waive-environment cpu --plan "$tokr2" --approved "the owner said so"
[ "$rc" = 0 ] && [ -f "$T/ran" ] && [ "$(cat "$WD/$key.count")" = $((nclaims + 2)) ] && ok "the claim keeps the number of the waivers made at the head" || no "count: rc=$rc: $(cat "$WD/$key.count" 2>&1): $(out)"
rm -f "$WD/$key".[0-9]*
for t in "$tokr" "$tokr2"; do
  reset; run $F verify f --waive-environment cpu --plan "$t" --approved "the owner said so"
  [ "$rc" = 1 ] && saw 'verify-env-waive-used' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "a deleted claim file does not make a spent token good again ($t)" || no "reopened $t: rc=$rc: $(out)"
done
tokr3=$(tokof "$(out)"); [ -n "$tokr3" ] && [ "$tokr3" != "$tokr" ] && [ "$tokr3" != "$tokr2" ] && ok "and the refusal prints the next token" || no "next token: $(out)"
# a count that is no number cannot tell a spent token from a new one: refused, with the code of its own
cp "$WD/$key.count" "$T/count.keep"; echo abc > "$WD/$key.count"
reset; run $F verify f --waive-environment cpu --plan "$tokr3" --approved "the owner said so"
[ "$rc" = 1 ] && saw 'verify-env-waiver-dir' && saw 'does not hold a number' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "a count that is not a number is refused as verify-env-waiver-dir" || no "bad count: rc=$rc: $(out)"
cp "$T/count.keep" "$WD/$key.count"
# a directory for the waivers that cannot be made is a refusal with its own code, not the code of the log
mv "$WD" "$WD.keep"; : > "$WD"
reset; run $F verify f; tokr4=$(tokof "$(out)")
reset; run $F verify f --waive-environment cpu --plan "$tokr4" --approved "the owner said so"
[ "$rc" = 1 ] && saw 'verify-env-waiver-dir' && ! saw 'verify-env-no-log' && saw 'cannot be made' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "a waivers directory that cannot be made is verify-env-waiver-dir, and nothing ran" || no "waiver dir: rc=$rc: $(out)"
rm -f "$WD"; mv "$WD.keep" "$WD"; unsetenv

# --- 4. a passing run through the launcher (no scope: cpu_quota null), the environment the suite sees, the record, and staleness
setcmd "echo \"PARENT=\$(cat /proc/\$PPID/comm)\" > $T/seen; echo \"LEAK=\${LEAK-unset} VERIFY_X=\${VERIFY_X-unset} LANG=\${LANG-unset} OTHER=\${OTHER-unset}\" >> $T/seen; FDS=; for f in /proc/\$\$/fd/*; do [ -e \"\$f\" ] && FDS=\"\$FDS \${f##*/}\"; done; echo \"FDS=\${FDS# }\" >> $T/seen; echo \"IN=\$(readlink /proc/\$\$/fd/0)\" >> $T/seen; echo suite-ran; touch $T/ran"
setenv '{"cpu_quota":null,"env_pass":["LANG"],"env_set":{"VERIFY_X":"1"}}'
reset; LEAK=secret run $F verify f
[ "$rc" = 0 ] && saw '^verify.environment: on \(id [0-9a-f]{12}\): the suite starts through the launcher$' && saw '^full suite: pass at [0-9a-f]+$' && [ -f "$T/ran" ] \
  && ok "on: the suite runs through the launcher and passes; the verdict line has no waiver note" || no "on pass: rc=$rc: $(out)"
case $(sed -n 's/^PARENT=//p' "$T/seen") in python*) ok "on: the suite command is started by the launcher";; *) no "on: parent $(sed -n 's/^PARENT=//p' "$T/seen")";; esac
grep -qx "LEAK=unset VERIFY_X=1 LANG=${LANG-unset} OTHER=unset" "$T/seen" && ok "on: the environment is the allowlist: LANG passed, VERIFY_X set, nothing else of the caller's" || no "env seen: $(cat "$T/seen")"
grep -qx 'FDS=0 1 2' "$T/seen" && grep -qx 'IN=/dev/null' "$T/seen" && ok "on: only descriptors 0-2, standard input from /dev/null" || no "fds seen: $(cat "$T/seen")"
[ "$(jq -r '.environment | [.id, (.launcher | tostring), .declared.cpu_quota // "null", .parts.cpu, .parts.signals, .parts.fds, .parts.tty, .parts.env] | join(",")' "$FREC")" = "$(python3 -I "$SE" id '{"cpu_quota":null,"env_pass":["LANG"],"env_set":{"VERIFY_X":"1"}}'),1,null,off,applied,applied,applied,applied" ] \
  && [ "$(jq -r '.environment.readback.sig_ign, .environment.readback.sig_blk' "$FREC" | tr '\n' ' ')" = "0 0 " ] && jq -e '.environment.readback.env_names == ["HOME","LANG","PATH","VERIFY_X"]' "$FREC" >/dev/null \
  && ok "the record: id, launcher, declaration, parts, and the read-back (signals clean, the environment names only)" || no "record: $(cat "$FREC")"
! grep -q secret "$FREC" && ok "the record holds no environment value" || no "record has a value"
run $F status f
[ "$rc" = 0 ] && saw 'full suite: pass at this head' && ! saw 'why:' && ok "status: the run counts" || no "status on: $(out)"
setenv '{"cpu_quota":null,"env_pass":["LANG"],"env_set":{"VERIFY_X":"2"}}'
run $F status f
[ "$rc" = 0 ] && saw 'full suite: not run on this branch' && saw 'why: the last run used verify.environment [0-9a-f]{12}, the answers now give [0-9a-f]{12}' && ok "a changed declaration makes the earlier run stale, and status says why" || no "status changed: $(out)"
run $F finish f
[ "$rc" = 1 ] && saw 'no passing run at the head' && ok "a changed declaration makes finish refuse" || no "finish changed: rc=$rc $(out)"
reset; run $F verify f
[ "$rc" = 0 ] && run $F finish f && [ "$rc" = 0 ] && saw '^plan token: ' && ok "after a verify with the new declaration, finish plans again" || no "finish again: rc=$rc $(out)"
unsetenv
run $F finish f
[ "$rc" = 1 ] && saw 'no passing run at the head' && ok "removing the declaration makes the run stale too" || no "finish removed: rc=$rc $(out)"
run $F status f
saw 'why: the last run used verify.environment [0-9a-f]{12}, the answers now give off' && ok "status says the declaration is gone" || no "status removed: $(out)"
reset; run $F verify f
[ "$rc" = 0 ] && [ "$(jq -S -c 'del(.at, .seconds) | keys' "$FREC")" = '["command","mode","result","sha"]' ] && run $F finish f && [ "$rc" = 0 ] && ok "verified with the setting off again: the record is the old one and finish plans" || no "off again: rc=$rc $(out)"

# --- 5. an answers file edited by hand (revision 3): refused at verify and finish, reported by status, and a raised launcher version is no edit
setenv '{"cpu_quota":null}'
reset; run $F verify f
[ "$rc" = 0 ] && ok "(setup) a run with the declaration on" || no "setup: $(out)"
rawenv null
run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && saw 'differs from the declaration qargi last accepted' && [ ! -s "$T/fakelog" ] && ok "a hand edit to off refuses feature verify" || no "hand edit off: rc=$rc $(out)"
run $F finish f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && ok "a hand edit to off refuses feature finish" || no "hand edit off finish: $(out)"
run $F status f
[ "$rc" = 0 ] && saw 'verify-env-change-unapproved' && ok "status prints the finding and goes on" || no "hand edit status: rc=$rc $(out)"
rawenv '{"cpu_quota":null,"env_set":{"A":"1"}}'
reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && [ ! -f "$T/ran" ] && ok "a hand edit to another declaration refuses too" || no "hand edit other: $(out)"
rawenv '{"cpu_quota":null}'
run $F verify f
[ "$rc" = 0 ] && ok "restoring the answers is accepted again" || no "restored: $(out)"
unsetenv
rawenv '{"cpu_quota":null}'
run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && ok "a declaration in the answers with none accepted (an entry that says off) is refused" || no "hand edit on: $(out)"
unsetenv
rawenv '{"fds":"bogus"}'
run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-invalid' && saw 'fds' && ok "an invalid declaration is refused at load" || no "invalid: $(out)"
run $F finish f
[ "$rc" = 1 ] && saw 'verify-env-invalid' && ok "an invalid declaration refuses feature finish" || no "invalid finish: $(out)"
run $F status f
[ "$rc" = 0 ] && saw 'verify-env-invalid' && saw 'fds' && saw '^full suite: ' && ok "status prints an invalid declaration as a finding and goes on (exit 0)" || no "invalid status: rc=$rc $(out)"
! saw 'answers now give' && saw 'why: .*no usable declaration now' && ok "status with an invalid declaration does not say the answers give off" || no "invalid status why: $(out)"
run $REL status 0.2.0
[ "$rc" = 0 ] && saw 'verify-env-invalid' && saw '^no release/0.2.0 yet' && ok "release status prints it too and goes on" || no "invalid release status: rc=$rc $(out)"
unsetenv
# a state file that cannot be read is a refusal, never a first declaration
echo 'not json' > "$T/s/verify-env.json"
run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && saw 'cannot be read' && ok "a damaged state file refuses" || no "damaged state: rc=$rc $(out)"
run $F status f
[ "$rc" = 0 ] && saw 'verify-env-change-unapproved' && saw 'cannot be read' && saw '^full suite: ' && ok "status prints a damaged state file as a finding and goes on (exit 0)" || no "damaged status: rc=$rc $(out)"
run $REL status 0.2.0
[ "$rc" = 0 ] && saw 'cannot be read' && ok "release status goes on with a damaged state file too" || no "damaged release status: rc=$rc $(out)"
rm -f "$T/s/verify-env.json"
# a raised LAUNCHER_VERSION: no refusal, earlier runs are stale
setenv '{"cpu_quota":null}'
reset; run $F verify f
copy_tool "$ROOT" "$T/tool2"; sed -i 's/^LAUNCHER_VERSION = 1 /LAUNCHER_VERSION = 2 /' "$T/tool2/lib/suite_env.py"
grep -q '^LAUNCHER_VERSION = 2 ' "$T/tool2/lib/suite_env.py" || no "(setup) the copy has no raised LAUNCHER_VERSION"
D2=$T/tool2/bin/qargi
run $D2 feature status f
[ "$rc" = 0 ] && ! saw 'verify-env-change-unapproved' && saw 'full suite: not run on this branch' && saw 'why: the last run used verify.environment' && ok "a raised LAUNCHER_VERSION is not a refusal; the earlier run is stale" || no "launcher version: rc=$rc $(out)"
reset; run $D2 feature verify f
[ "$rc" = 0 ] && ok "a verify with the new launcher version runs" || no "launcher version verify: $(out)"
unsetenv

# --- 6. gates go through the launcher, one report each, merged into the record
setenv '{"cpu_quota":null}'
jq --argjson g '[{"name":"one","tier":"feature","command":"echo g1; touch '"$T"'/g1"},{"name":"two","tier":"feature","command":"echo g2; touch '"$T"'/g2"}]' '.gates = $g' "$P" > "$P.new" && mv "$P.new" "$P"
rm -f "$T/g1" "$T/g2" "$FREC"; run $F verify f
[ "$rc" = 0 ] && [ -f "$T/g1" ] && [ -f "$T/g2" ] && [ "$(find "$T/s/suite-logs/app.feature-f.env" -name 'gate-*.json' | wc -l)" = 2 ] && jq -e '.gates | map(.result) == ["pass","pass"]' "$FREC" >/dev/null \
  && [ "$(jq -r '.environment.parts.signals' "$FREC")" = applied ] && ok "each gate starts through the launcher (a report each) and the record merges them" || no "gates: rc=$rc $(out)"
jq --argjson g '[{"name":"one","tier":"feature","command":"exit 3"},{"name":"two","tier":"feature","command":"touch '"$T"'/g2"}]' '.gates = $g' "$P" > "$P.new" && mv "$P.new" "$P"
rm -f "$T/g2" "$FREC"; run $F verify f
[ "$rc" = 1 ] && [ ! -f "$T/g2" ] && [ "$(jq -r '.result' "$FREC")" = fail ] && saw 'failing gate: one' && ok "a failing gate is a fail of the suite, and the next gate is not run" || no "gate fail: rc=$rc $(out)"
jq 'del(.gates)' "$P" > "$P.new" && mv "$P.new" "$P"; unsetenv
# a record is written only on the reports of the launcher, and only when they agree on the declaration and the launcher: the second gate edits the first one's report
ENVD=$T/s/suite-logs/app.feature-f.env; setenv '{"cpu_quota":null}'
for edit in '.id = "deadbeefdead"' '.launcher = 99'; do
  jq --arg c "jq '$edit' $ENVD/gate-000.json > $ENVD/t.new && mv $ENVD/t.new $ENVD/gate-000.json" --argjson g '[{"name":"one","tier":"feature","command":"true"}]' '.gates = ($g + [{"name":"two","tier":"feature","command":$c}])' "$P" > "$P.new" && mv "$P.new" "$P"
  rm -f "$FREC"; run $F verify f
  [ "$rc" = 1 ] && saw 'differ in their id or launcher' && saw 'nothing is recorded' && [ ! -f "$FREC" ] && ok "reports that differ ($edit) are no record: the verb stops and nothing counts" || no "report $edit: rc=$rc $(out)"
done
jq 'del(.gates)' "$P" > "$P.new" && mv "$P.new" "$P"; unsetenv
( export SUITE_ENV='{}' SUITE_ENV_ID=abc; ENV_DIR=$T/noreports; mkdir -p "$ENV_DIR"; eval "$(sed -n '/^suite_env_record() {/,/^}/p' "$ROOT/lib/gitflow.sh")";suite_env_record > "$T/o" 2> "$T/e" ); rc=$?
[ "$rc" != 0 ] && [ ! -s "$T/o" ] && grep -q 'no launcher report' "$T/e" && ok "with the setting on and no report of the launcher there is no environment member to record" || no "no report: rc=$rc $(out)"

# --- 7. a log that cannot be made is a refusal with the setting on and nothing new with it off
setcmd "echo suite-ran; touch $T/ran"
mv "$T/s/suite-logs" "$T/s/suite-logs.keep"; : > "$T/s/suite-logs"
setenv '{"cpu_quota":null}'
reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-no-log' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "verify-env-no-log: with the setting on a suite log that cannot be created refuses" || no "no log on: rc=$rc $(out)"
# under a waiver the claim comes before the log is made, so a log that cannot be made stops a run whose token is spent and audited: the message says so
setenv '{"cpu_quota":"max"}'
mode nouser; reset; run $F verify f; tokl=$(tokof "$(out)")
na=$(grep -c 'verify:environment-waived' "$T/s/audit.log")
reset; run $F verify f --waive-environment cpu --plan "$tokl" --approved "the owner said so"
[ "$rc" = 1 ] && saw 'verify-env-no-log' && saw 'nothing was run\. The waiver token was spent' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = $((na + 1)) ] \
  && ok "verify-env-no-log under a waiver: the token is spent, an audit line is written, and the message says the token was spent" || no "no log waived: rc=$rc $(out)"
reset; run $F verify f --waive-environment cpu --plan "$tokl" --approved "the owner said so"
[ "$rc" = 1 ] && saw 'verify-env-waive-used' && ok "the token that the refused log spent is spent" || no "no log token again: rc=$rc $(out)"
mode ok
unsetenv
reset; run $F verify f
[ "$rc" = 0 ] && [ -f "$T/ran" ] && ok "with the setting off a missing log directory changes nothing (the suite runs without a log)" || no "no log off: rc=$rc $(out)"
rm -f "$T/s/suite-logs"; mv "$T/s/suite-logs.keep" "$T/s/suite-logs"

# --- 8. release verify: the same seam, the same waiver
setenv '{"cpu_quota":"max"}'
mode nouser; reset; run $REL verify 0.2.0
[ "$rc" = 1 ] && saw 'verify-env-cpu-no-user-manager' && saw -- 'release verify 0.2.0 --waive-environment cpu --plan' && [ ! -f "$T/ran" ] && [ ! -f "$DREC" ] && ok "release verify: the attempt refuses with the code and the release waiver command" || no "release refuse: rc=$rc $(out)"
tokr=$(tokof "$(out)")
run $REL verify 0.2.0 --waive-environment cpu --plan "$tokr" --approved "the owner said so"
[ "$rc" = 0 ] && saw '^full suite: pass at [0-9a-f]+ \(verify.environment: cpu waived-failed\)$' && [ "$(jq -r '.environment.parts.cpu' "$DREC")" = waived-failed ] && [ -f "$T/ran" ] \
  && ok "release verify with the token and the words passes, recorded cpu waived-failed" || no "release waived: rc=$rc $(out)"
run $REL status 0.2.0
[ "$rc" = 0 ] && saw 'verify.environment: cpu waived-failed' && ok "release status shows the waiver again" || no "release status: $(out)"
run $REL status 0.2.0 --waive-environment cpu
[ "$rc" = 2 ] && saw 'belongs to release verify' && ok "release: --waive-environment is for verify only" || no "release waive on status: rc=$rc $(out)"
unsetenv
run $REL status 0.2.0
[ "$rc" = 0 ] && ! saw 'pass at' && saw 'full suite: not run' && saw 'why: the last run used verify.environment [0-9a-f]{12}, the answers now give off' && ! saw 'does not count.*pass' \
  && ok "release status: a run made under another declaration is not reported as a pass; one line says it does not count" || no "release status stale: rc=$rc $(out)"
reset; run $REL verify 0.2.0
[ "$rc" = 0 ] && [ "$(jq -S -c 'del(.at, .seconds) | keys' "$DREC")" = '["command","mode","result","sha"]' ] && ok "release verify with the setting off writes the old record" || no "release off: rc=$rc $(out)"

# a refusal of the verb's own pre-run checks (--strict with a CI job that matches no gate) comes before the claim of the waiver: the token is not spent, nothing is
# written to the waiver directory and no audit line says a waiver was made for a run that never ran
setenv '{"cpu_quota":"max"}'; mode nouser
dev0=$(git -C "$R" rev-parse develop)
ix=$T/ci-index; wf=$(printf 'name: CI\non: [push]\njobs:\n  deploy:\n    runs-on: ubuntu-latest\n' | git -C "$R" hash-object -w --stdin)
GIT_INDEX_FILE=$ix git -C "$R" read-tree develop && GIT_INDEX_FILE=$ix git -C "$R" update-index --add --cacheinfo "100644,$wf,.github/workflows/ci.yml"
git -C "$R" update-ref refs/heads/develop "$(git -C "$R" commit-tree "$(GIT_INDEX_FILE=$ix git -C "$R" write-tree)" -p develop -m ci)"
reset; run $REL verify 0.2.0
tokc=$(tokof "$(out)"); [ -n "$tokc" ] && ok "(setup) a release verify at a head with a CI job and no gate is refused by the launcher and prints a token" || no "strict setup: rc=$rc $(out)"
na=$(grep -c 'verify:environment-waived' "$T/s/audit.log"); nw=$(find "$WD" | wc -l); cnt=$(cat "$WD"/*.count 2>/dev/null | tr '\n' ' ')
reset; run $REL verify 0.2.0 --strict --waive-environment cpu --plan "$tokc" --approved "the owner said so"
[ "$rc" = 1 ] && saw -- '--strict: 1 CI job' && ! saw 'verify-env-waive' && [ ! -f "$T/ran" ] && [ ! -f "$DREC" ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = "$na" ] \
  && [ "$(find "$WD" | wc -l)" = "$nw" ] && [ "$(cat "$WD"/*.count 2>/dev/null | tr '\n' ' ')" = "$cnt" ] \
  && ok "a --strict refusal spends nothing: no claim file, no count, no audit line, nothing ran" || no "strict refusal: rc=$rc $(out)"
reset; run $REL verify 0.2.0 --waive-environment cpu --plan "$tokc" --approved "the owner said so"
[ "$rc" = 0 ] && [ -f "$T/ran" ] && [ "$(jq -r '.environment.parts.cpu' "$DREC")" = waived-failed ] && [ "$(grep -c 'verify:environment-waived' "$T/s/audit.log")" = $((na + 1)) ] \
  && ok "and the same token still runs once the refusal is out of the way, with one audit line" || no "token after the strict refusal: rc=$rc $(out)"
git -C "$R" update-ref refs/heads/develop "$dev0"; unsetenv

# --- 9. the real scope, where systemd-run makes one (systemd 254 or newer); otherwise an expected line
real=$(PATH=$PATH_PLAIN command -v systemd-run || true)
rv=0; [ -n "$real" ] && rv=$("$real" --version 2>/dev/null | sed -n '1s/^systemd \([0-9]*\).*/\1/p')
if [ -n "$real" ] && [ "${rv:-0}" -ge 254 ] && "$real" --user --scope --quiet --collect -p CPUQuota=200% -- true >/dev/null 2>&1; then
  nofake
  # M1: the cpu.max files under app.slice are the same before and during the run (the controller is switched on only for our own slice)
  cg=$(sed -n 's/^0:://p' /proc/self/cgroup); app=''; case $cg in *app.slice*) app=/sys/fs/cgroup${cg%%/app.slice*}/app.slice;; esac
  cpumax_files() { [ -z "$app" ] || find "$app" -name cpu.max 2>/dev/null | sort; }
  cpumax_files > "$T/cpumax.before"
  setcmd "echo '\${VERIFY_X}' pid=\$\$; { find '${app:-/nonexistent}' -name cpu.max 2>/dev/null | sort > $T/cpumax.during; } ; setsid sleep 300 & p=\$!; until [ \"\$(cat /proc/\$p/comm)\" != bash ]; do :; done"
  for q in '"200%"' '"max"' ''; do
    case $q in '') d='{}'; want_max='max 100000';; '"max"') d='{"cpu_quota":"max"}'; want_max='max 100000';; *) d="{\"cpu_quota\":$q}"; want_max='200000 100000';; esac
    setenv "$d"; reset
    ( trap '' HUP; python3 -c 'import os, signal, sys; signal.pthread_sigmask(signal.SIG_BLOCK, [signal.SIGUSR1, signal.SIGUSR2]); os.execvp(sys.argv[1], sys.argv[1:])' "$DA" feature verify f ) >"$T/o" 2>"$T/e"; rc=$?
    log=$T/s/suite-logs/app.feature-f.log
    [ "$rc" = 0 ] && grep -qF '${VERIFY_X}' "$log" && grep -qE 'pid=[0-9]+' "$log" && ok "real scope ($d): the command reaches the suite as text ($d: the literal \${VERIFY_X}, a pid)" || no "real $d: rc=$rc $(out)"
    [ "$(jq -r '.environment.readback.cpu_max' "$FREC")" = "$want_max" ] && ok "real scope ($d): cpu.max is $want_max" || no "real $d cpu_max: $(jq -c '.environment.readback' "$FREC")"
    case $q in '"200%"') ;; *) [ "$(jq -r '.environment.readback.cpu_weight' "$FREC")" = 100 ] && ok "real scope ($d): cpu.weight is 100" || no "real $d weight: $(jq -c '.environment.readback' "$FREC")";; esac
    jq -r '.environment.readback.cgroup' "$FREC" | grep -q 'qargi-verify.slice' && ok "real scope ($d): the cgroup is below qargi-verify.slice" || no "real $d cgroup: $(jq -c '.environment.readback' "$FREC")"
    lp=$(jq -r '[.environment.leftovers[] | select(.comm == "sleep" or .comm == "setsid") | .pid][0] // empty' "$FREC")
    [ -n "$lp" ] && ! kill -0 "$lp" 2>/dev/null && ok "real scope ($d): the sleep that outlived the command is in leftovers and gone afterwards" || no "real $d leftovers: $(jq -c '.environment.leftovers' "$FREC") pid=$lp"
  done
  [ -z "$app" ] || { [ -s "$T/cpumax.during" ] && [ -z "$(comm -13 "$T/cpumax.before" "$T/cpumax.during")" ] && ok "real scope: no cpu.max file appears under app.slice during the run (the controller is switched on for our own slice only)" || no "app.slice cpu.max: during $(wc -l < "$T/cpumax.during") file(s); new: $(comm -13 "$T/cpumax.before" "$T/cpumax.during" | head -3)"; }
  # a scope that cannot be made after a passing attempt: not a failure of the suite, and nothing recorded
  setcmd "echo suite-ran; touch $T/ran"; setenv '{"cpu_quota":"max"}'
  mkdir -p "$T/flaky"
  printf '#!/usr/bin/env bash\nn=$(cat "%s" 2>/dev/null || echo 0)\nif [ "${1:-}" = --version ]; then exec "%s" --version; fi\nn=$((n + 1)); echo "$n" > "%s"\nif [ "$n" = 1 ]; then exec "%s" "$@"; fi\nexit 1\n' "$T/flaky/n" "$real" "$T/flaky/n" "$real" > "$T/flaky/systemd-run"
  chmod +x "$T/flaky/systemd-run"
  reset; PATH=$T/flaky:$PATH_PLAIN; export PATH; run $F verify f; nofake
  [ "$rc" = 1 ] && saw 'verify-env-cpu-no-user-manager' && saw 'left no report' && [ ! -f "$FREC" ] && ! saw '^full suite: fail' && ok "a scope that fails after a passing attempt is verify-env-cpu-no-user-manager, no record, never a fail" || no "flaky: rc=$rc $(out)"
  # the attempt passes and the run is then refused (the second call of systemd-run asks for another quota than the declared one, so the read-back in the scope refuses):
  # the refusal prints the token the message promises, for the refused part, and the retry takes it: the attempt passes, so the waiver is of a part nothing refused this time
  setenv '{"cpu_quota":"200%"}'
  mkdir -p "$T/tamper"; rm -f "$T/tamper/n"
  cat > "$T/tamper/systemd-run" <<EOF
#!/usr/bin/env bash
if [ "\${1:-}" = --version ]; then exec "$real" --version; fi
n=\$(cat "$T/tamper/n" 2>/dev/null || echo 0); n=\$((n + 1)); echo "\$n" > "$T/tamper/n"
args=("\$@")
if [ "\$n" = 2 ]; then for i in "\${!args[@]}"; do case \${args[i]} in CPUQuota=*) args[i]=CPUQuota=300%;; esac; done; fi
exec "$real" "\${args[@]}"
EOF
  chmod +x "$T/tamper/systemd-run"
  reset; PATH=$T/tamper:$PATH_PLAIN; export PATH; run $F verify f; tokt=$(tokof "$(out)")
  [ "$rc" = 1 ] && saw 'verify-env-cpu-readback' && saw 'the launcher refused this run' && [ -n "$tokt" ] && [ "$(grep -c '^plan token: ' "$T/o")" = 1 ] && saw -- '--waive-environment cpu --plan [0-9a-f]{12} --approved' \
    && [ ! -f "$FREC" ] && ok "the attempt passed and the run was refused: the token the message promises is printed, for the refused part; nothing was recorded" || no "refused after a passing attempt: rc=$rc $(out)"
  reset; run $F verify f --waive-environment cpu --plan "$tokt" --approved "the owner said so"
  [ "$rc" = 0 ] && saw 'waived for this run, and the attempt before it applied every part' && [ "$(jq -r '.environment.parts.cpu' "$FREC")" = applied ] && ! saw 'waived-failed' && [ -f "$T/ran" ] \
    && ok "the retry takes that token: the part the run refused once is applied this time, recorded applied" || no "retry after a refused run: rc=$rc $(out)"
  reset; run $F verify f --waive-environment cpu --plan "$tokt" --approved "the owner said so"
  [ "$rc" = 1 ] && saw 'verify-env-waive-used' && ! saw '^plan token: ' && [ ! -f "$T/ran" ] && ok "that token is spent: used again it is refused, and with nothing refused no new one is printed" || no "reuse after a refused run: rc=$rc $(out)"
  nofake; unsetenv
else
  echo "expected: no real user scope here (systemd-run ${rv:-absent}, needs --user --scope to work on 254 or newer): the real-scope cases did not run"
fi

# two verifies of the same name share one directory for the reports of the launcher, and the second would delete the first's: with the setting on a second verify of
# a name whose first is alive is refused before anything is made (no run, no waiver spent, the first's reports and busy mark untouched); a dead pid, another name
# and the setting off are not refused
fake; mode ok; setenv '{"cpu_quota":null}'; setcmd "echo suite-ran; touch $T/ran"
mkdir -p "$T/s/busy" "$T/s/suite-logs/app.feature-f.env" "$T/s/suite-logs/app.release-0.2.0.env"
echo first > "$T/s/suite-logs/app.feature-f.env/gate.json"; echo first > "$T/s/suite-logs/app.release-0.2.0.env/gate.json"
sleep 300 & HOLDER=$!
printf '%s\n' "$HOLDER" > "$T/s/busy/app.verify.f.pid"; printf '%s\n' "$HOLDER" > "$T/s/busy/app.release-verify.0.2.0.pid"
reset; run $F verify f
[ "$rc" = 1 ] && saw "another verify of f is running \(pid $HOLDER, busy mark $T/s/busy/app.verify.f.pid\)" && saw "remove $T/s/busy/app.verify.f.pid" && saw 'Nothing was run' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && [ "$(cat "$T/s/suite-logs/app.feature-f.env/gate.json")" = first ] \
  && [ "$(cat "$T/s/busy/app.verify.f.pid")" = "$HOLDER" ] && [ ! -s "$T/fakelog" ] \
  && ok "feature verify: a second verify of the name is refused while the first is alive; nothing runs and the first's reports and busy mark stay" || no "second feature verify: rc=$rc: $(out)"
reset; run $REL verify 0.2.0
[ "$rc" = 1 ] && saw "another release-verify of 0.2.0 is running \(pid $HOLDER, busy mark " && [ ! -f "$T/ran" ] && [ "$(cat "$T/s/suite-logs/app.release-0.2.0.env/gate.json")" = first ] \
  && ok "release verify: the same refusal" || no "second release verify: rc=$rc: $(out)"
reset; run $REL verify 0.3.0
[ "$rc" = 0 ] && [ -f "$T/ran" ] && ok "a verify of another name is not refused" || no "other name: rc=$rc: $(out)"
unsetenv; reset; run $F verify f
[ "$rc" = 0 ] && [ -f "$T/ran" ] && saw 'another whole-suite run of app is in progress' && ok "with the setting off a live first is only a warning, as it always was" || no "setting off: rc=$rc: $(out)"
setenv '{"cpu_quota":null}'; kill "$HOLDER"; wait "$HOLDER" 2>/dev/null
reset; run $F verify f
[ "$rc" = 0 ] && [ -f "$T/ran" ] && ok "a busy mark whose pid is gone is ignored" || no "dead pid: rc=$rc: $(out)"
unsetenv

[ "$fail" = 0 ] && echo "all suite-env flow tests passed"
exit "$fail"
