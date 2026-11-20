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
F="$DA feature"; REL="$DA release"
FREC=$T/s/releases/app-feature_f.json; DREC=$T/s/releases/app-develop.json
# the stand-in for systemd-run: first on PATH, steered by a mode file, logging each call
mkdir -p "$T/fakebin"; cp tests/fixtures/fake-systemd-run "$T/fakebin/systemd-run"; chmod +x "$T/fakebin/systemd-run"
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
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && saw 'exactly the refused parts' && [ ! -f "$FREC" ] && [ ! -f "$T/ran" ] && ok "a waiver for another part than the refused one is refused, with a token for the refused one" || no "waive other part: $(out)"
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
# the token is of this head: a feature that moved needs a new refusal
git -C "$R" branch -q agent/x develop; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" agent/x; echo x > "$w/x.txt"; git -C "$w" add -A; git -C "$w" commit -q -m x; git -C "$R" worktree remove --force "$w"
$F merge f agent/x >/dev/null 2>&1
run $F verify f --waive-environment cpu --plan "$tok" --approved "the owner said run it without the scope"
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && ok "the token of an earlier head does not cover the new one" || no "old token: rc=$rc: $(out)"
# a waiver when the attempt passes is recorded applied: `cpu_quota` null has no cpu part at all, so the waiver of fds is checked against a passing attempt
setenv '{"cpu_quota":null}'
run $F verify f --waive-environment fds
tok2=$(tokof "$(out)")
[ "$rc" = 1 ] && saw 'verify-env-waive-unapproved' && [ -n "$tok2" ] && ok "a waiver of a part the attempt did not refuse still needs the token and the words" || no "waive passing: $(out)"
reset; run $F verify f --waive-environment fds --plan "$tok2" --approved "owner words"
[ "$rc" = 0 ] && [ "$(jq -r '.environment.parts.fds' "$FREC")" = applied ] && ! saw 'waived-failed' && ok "a waived part that succeeds is recorded applied" || no "waive applied: rc=$rc: $(out); $(cat "$FREC")"
# the setting off: nothing to waive
unsetenv
run $F verify f --waive-environment cpu --plan x --approved y
[ "$rc" = 1 ] && saw 'verify-env-waive-unknown' && saw 'off for app' && ok "a waiver with the setting off is refused as unknown" || no "waive off: $(out)"
run $F status f --waive-environment cpu
[ "$rc" = 2 ] && saw 'belongs to feature verify' && ok "--waive-environment is for verify only" || no "waive on status: rc=$rc $(out)"

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
unsetenv
# a state file that cannot be read is a refusal, never a first declaration
echo 'not json' > "$T/s/verify-env.json"
run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-change-unapproved' && saw 'cannot be read' && ok "a damaged state file refuses" || no "damaged state: rc=$rc $(out)"
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

# --- 7. a log that cannot be made is a refusal with the setting on and nothing new with it off
setcmd "echo suite-ran; touch $T/ran"
mv "$T/s/suite-logs" "$T/s/suite-logs.keep"; : > "$T/s/suite-logs"
setenv '{"cpu_quota":null}'
reset; run $F verify f
[ "$rc" = 1 ] && saw 'verify-env-no-log' && [ ! -f "$T/ran" ] && [ ! -f "$FREC" ] && ok "verify-env-no-log: with the setting on a suite log that cannot be created refuses" || no "no log on: rc=$rc $(out)"
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
reset; run $REL verify 0.2.0
[ "$rc" = 0 ] && [ "$(jq -S -c 'del(.at, .seconds) | keys' "$DREC")" = '["command","mode","result","sha"]' ] && ok "release verify with the setting off writes the old record" || no "release off: rc=$rc $(out)"

# --- 9. the real scope, where systemd-run makes one (systemd 254 or newer); otherwise an expected line
real=$(PATH=$PATH_PLAIN command -v systemd-run || true)
rv=0; [ -n "$real" ] && rv=$("$real" --version 2>/dev/null | sed -n '1s/^systemd \([0-9]*\).*/\1/p')
if [ -n "$real" ] && [ "${rv:-0}" -ge 254 ] && "$real" --user --scope --quiet --collect -p CPUQuota=200% -- true >/dev/null 2>&1; then
  nofake
  # M1: the cpu.max files under app.slice are the same before and during the run (the controller is switched on only for our own slice)
  cg=$(sed -n 's/^0:://p' /proc/self/cgroup); app=''; case $cg in *app.slice*) app=/sys/fs/cgroup${cg%%/app.slice*}/app.slice;; esac
  lscpu() { [ -z "$app" ] || find "$app" -name cpu.max 2>/dev/null | sort; }
  lscpu > "$T/cpumax.before"
  setcmd "echo '\${VERIFY_X}' pid=\$\$; { find '${app:-/nonexistent}' -name cpu.max 2>/dev/null | sort > $T/cpumax.during; } ; setsid sleep 300 &"
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
  unsetenv
else
  echo "expected: no real user scope here (systemd-run ${rv:-absent}, needs --user --scope to work on 254 or newer): the real-scope cases did not run"
fi

[ "$fail" = 0 ] && echo "all suite-env flow tests passed"
exit "$fail"
