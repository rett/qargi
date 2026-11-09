#!/usr/bin/env bash
# The answer release.after_steps: a list of steps (a string, or an object {name, command, who, evidence}) that `release finish` prints as
# "after the release: [pending] NAME (WHO): COMMAND" lines and records as pending under the state for `release status`; `release step` marks
# one done. qargi never runs them. gh is a stub (QARGI_GH); GitHub is never contacted.
# Run: tests/test_release_after_steps.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; ROOT=$PWD; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://github.com/acme/relaf/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh

# --- the answer
base=$($DA project template relaf | jq '.repo.url="https://github.com/acme/relaf"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"; $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then ok "answers: $1"; else no "answers: $1 (exit $rc, wanted $2)"; fi
}
chk "after_steps as a list of strings"  0 '.release={after_steps:["announce {version}","update the docs"]}'
chk "after_steps an empty list"         0 '.release={after_steps:[]}'
chk "after_steps a string"              1 '.release={after_steps:"announce"}'
chk "after_steps an empty step"         1 '.release={after_steps:[""]}'
chk "after_steps a step with a newline" 1 '.release={after_steps:["a\nb"]}'
chk "after_steps a number"              1 '.release={after_steps:[3]}'
chk "after_steps objects"               0 '.release={after_steps:[{name:"a"},{name:"b",command:"c {version}",who:"owner",evidence:"a line"},"c"]}'
chk "after_steps a step without a name" 1 '.release={after_steps:[{command:"c"}]}'
chk "after_steps an empty name"         1 '.release={after_steps:[{name:""}]}'
chk "after_steps a name with a newline" 1 '.release={after_steps:[{name:"a\nb"}]}'
chk "after_steps who is neither"        1 '.release={after_steps:[{name:"a",who:"member"}]}'
chk "after_steps who is not a string"   1 '.release={after_steps:[{name:"a",who:1}]}'
chk "after_steps an unknown key"        1 '.release={after_steps:[{name:"a",run:"x"}]}'
chk "after_steps command not a string"  1 '.release={after_steps:[{name:"a",command:["x"]}]}'
chk "after_steps evidence not a string" 1 '.release={after_steps:[{name:"a",evidence:true}]}'
chk "after_steps the same name twice"   1 '.release={after_steps:[{name:"a"},{name:"a",who:"owner"}]}'
chk "after_steps a string and an object of one name" 1 '.release={after_steps:["a",{name:"a"}]}'
jq '.release={after_steps:[{name:"a"},{name:"a"}]}' <<<"$base" > "$T/a.json"
$DA project validate "$T/a.json" 2>&1 | grep -q "used twice" && ok "answers: a repeated name is named" || no "answers: repeated name message"

# --- a repository with an origin, and a release through push and finish
R=$T/relaf; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git clone -q --bare "$R" "$T/origin.git" && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" fetch -q origin
git -C "$R" checkout -q -b parked
jq --arg p "$R" --arg t "$T" '.repo={url:"https://github.com/acme/relaf", path:$p, long_lived:["master","develop"]} | .test_command="true"
  | .release={after_steps:["announce {version} to the list",
      {name:"post the notes", command:("touch " + $t + "/ran-by-qargi"), who:"lead", evidence:"the address of the post"},
      {name:"tag the docs repository", command:"git tag {version}", who:"owner"}]}' <<<"$base" > "$T/c/projects/relaf.json"
export QARGI_PROJECT=relaf
cd "$T" || exit 1
$REL verify 0.2.0 >/dev/null 2>&1 && rstart 0.2.0 --date 2026-01-02 >/dev/null 2>&1 || no "release 0.2.0 could not start"
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.2.0 | tok)
! grep -q "after the release" <<<"$($REL finish 0.2.0)" && ok "the finish plan does not show the steps yet (nothing is finished)" || no "plan shows steps"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "the release finishes" || no "finish: rc=$rc $out"
exp=$(printf 'after the release: [pending] announce 0.2.0 to the list (lead)\nafter the release: [pending] post the notes (lead): touch %s/ran-by-qargi [evidence needed: the address of the post]\nafter the release: [pending] tag the docs repository (owner): waits for the owner: run git tag 0.2.0\n' "$T")
[ "$(grep '^after the release:' <<<"$out")" = "$exp" ] && ok "finish prints each step as an 'after the release: [pending] NAME (WHO): COMMAND' line, {version} replaced, in order" || no "lines: $out"
[ ! -e "$T/ran-by-qargi" ] && ok "a step is never run" || no "a step was run"
rec=$T/s/release/relaf-0.2.0.after.json
[ "$(jq -r '.steps | length' "$rec")" = 3 ] && [ "$(jq -r '.steps[0].name' "$rec")" = "announce 0.2.0 to the list" ] && [ "$(jq -r '.version' "$rec")" = 0.2.0 ] \
  && [ "$(jq -r '[.steps[] | select(.state == "pending")] | length' "$rec")" = 3 ] && [ "$(jq -r '.steps[0].who' "$rec")" = lead ] && [ "$(jq -r '.steps[2].who' "$rec")" = owner ] \
  && ok "the steps are recorded as pending under the state (release/PROJECT-VERSION.after.json) for release status" || no "record: $(cat "$rec" 2>&1)"
out=$($REL status 0.2.0 2>&1)
[ "$(grep -c '^    \[pending\] ' <<<"$out")" = 3 ] && grep -qxF -- "    [pending] announce 0.2.0 to the list (lead)" <<<"$out" && ok "release status shows the recorded steps as pending" || no "status steps: $out"
grep -qxF -- "    [pending] tag the docs repository (owner): waits for the owner: run git tag 0.2.0" <<<"$out" && ok "an owner's step waits for the owner: run COMMAND" || no "owner line: $out"

# --- release step
sf() { $REL step "$@"; }
out=$(sf 0.2.0 "announce 0.2.0 to the list" 2>&1); rc=$?
[ $rc = 0 ] && grep -q "only the record changed" <<<"$out" && ok "release step marks a step done (the record changes, the command is not run)" || no "step: rc=$rc $out"
[ "$(jq -r '.steps[0].state' "$rec")" = "done" ] && [ -n "$(jq -r '.steps[0].done_at' "$rec")" ] && ok "the record keeps the state and the time" || no "step record: $(cat "$rec")"
out=$(sf 0.2.0 "announce 0.2.0 to the list" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "marked done already" <<<"$out" && grep -q -- "--again" <<<"$out" && ok "a step marked done is refused a second time" || no "again: rc=$rc $out"
out=$(sf 0.2.0 "announce 0.2.0 to the list" --again --evidence "second try" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(jq -r '.steps[0].evidence' "$rec")" = "second try" ] && ok "--again records it again" || no "--again: rc=$rc $out"
# a write that fails is told in qargi's words (the record is being written by another command; run it again), not in jq's, and the exit status stays 1
cp "$rec" "$T/rec.keep"
if [ "$(id -u)" != 0 ]; then
  chmod a-w "$(dirname "$rec")"
  out=$(sf 0.2.0 "tag the docs repository" 2>&1); rc=$?
  chmod u+w "$(dirname "$rec")"
  [ $rc = 1 ] && grep -q "could not write the step record" <<<"$out" && grep -q "being written by another command" <<<"$out" && grep -q "run this again" <<<"$out" && ! grep -q "jq:" <<<"$out" \
    && cmp -s "$rec" "$T/rec.keep" && ok "a step record that cannot be written is refused in plain words, exit 1, and the record is unchanged" || no "write failure: rc=$rc $out"
fi
# the other command wins the race: a jq that marks the step done just before the locked write reads the record
REALJQ=$(command -v jq); mkdir -p "$T/shim"
cat > "$T/shim/jq" <<J
#!/usr/bin/env bash
case "\$*" in *"marked done meanwhile"*) "$REALJQ" '(.steps[] | select(.name == "tag the docs repository")) |= (.state = "done")' "$rec" > "$T/rec.other" && mv "$T/rec.other" "$rec";; esac
exec "$REALJQ" "\$@"
J
chmod +x "$T/shim/jq"
out=$(PATH="$T/shim:$PATH" sf 0.2.0 "tag the docs repository" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "was marked done by another command" <<<"$out" && grep -q "run this again with --again" <<<"$out" && ! grep -q "jq:" <<<"$out" \
  && ok "two marks at the same moment: the second is told in plain words to run again with --again, exit 1" || no "race: rc=$rc $out"
cp "$T/rec.keep" "$rec"
out=$(sf 0.2.0 "post the notes" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "needs evidence (the address of the post)" <<<"$out" && [ "$(jq -r '.steps[1].state' "$rec")" = pending ] && ok "a step with an evidence is refused without --evidence" || no "evidence: rc=$rc $out"
out=$(sf 0.2.0 "post the notes" --evidence "   " 2>&1); rc=$?
[ $rc != 0 ] && [ "$(jq -r '.steps[1].state' "$rec")" = pending ] && ok "a blank --evidence is refused" || no "blank evidence: rc=$rc $out"
out=$(sf 0.2.0 "post the notes" --evidence $'two\nlines' 2>&1); rc=$?
[ $rc != 0 ] && [ "$(jq -r '.steps[1].state' "$rec")" = pending ] && ok "a multi-line --evidence is refused" || no "multiline evidence: rc=$rc $out"
out=$(sf 0.2.0 "no such step" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no after-step named 'no such step'" <<<"$out" && grep -q "post the notes" <<<"$out" && ok "an unknown name is refused and the names are listed" || no "unknown name: rc=$rc $out"
out=$(sf 0.9.9 "post the notes" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no record of the after-steps of 0.9.9" <<<"$out" && ok "a version with no record is refused" || no "unknown version: rc=$rc $out"
out=$(sf 0.2.0 2>&1); rc=$?
[ $rc != 0 ] && grep -q "usage: qargi release step" <<<"$out" && ok "release step without a name is refused" || no "no name: rc=$rc $out"
out=$($REL status 0.2.0 --evidence x 2>&1); rc=$?
[ $rc != 0 ] && grep -q "belong to release step" <<<"$out" && ok "--evidence belongs to release step" || no "stray option: rc=$rc $out"
out=$(sf 0.2.0 "post the notes" --evidence "https://example.net/p/1" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(jq -r '.steps[1].evidence' "$rec")" = "https://example.net/p/1" ] && ok "an evidence-required step is marked done with its evidence" || no "evidence done: rc=$rc $out"
[ ! -e "$T/ran-by-qargi" ] && ok "release step never runs the command" || no "release step ran the command"
out=$($REL status 0.2.0 2>&1)
sect=$(sed -n '/after-steps/,$p' <<<"$out")
[ "$(grep -c '^    \[done\] ' <<<"$sect")" = 2 ] && grep -qE '^    \[done\] post the notes \(lead, [0-9T:Z-]+, evidence: https://example.net/p/1\)$' <<<"$sect" \
  && [ "$(grep -c '^    \[pending\] ' <<<"$sect")" = 1 ] && ok "release status shows [done] name (evidence) from the record" || no "status done: $sect"
[ "$(sed -n '$p' <<<"$sect")" = "    [pending] tag the docs repository (owner): waits for the owner: run git tag 0.2.0" ] && ok "pending steps are listed last" || no "pending last: $sect"
# kept across restarts: it is a file; a fresh process reads the same
out=$($REL status 0.2.0 2>&1) && grep -q '^    \[done\] announce 0.2.0 to the list' <<<"$out" && ok "the state is a file in the state directory, read again by a later status" || no "restart: $out"
jq '.steps[2].name="the recorded third step"' "$rec" > "$T/x.json" && mv "$T/x.json" "$rec"
out=$($REL status 0.2.0 2>&1)
grep -q "^    \[pending\] the recorded third step" <<<"$out" && ! grep -q "tag the docs repository" <<<"$out" && ok "status shows what was recorded, not the answer as it is now" || no "status record: $out"

# --- steps recorded at the same moment: the record is changed under a lock and through a temporary file of its own, so none is lost
jq '.steps |= map(.state = "pending" | .done_at = "" | .evidence = "")' "$rec" > "$T/x.json" && mv "$T/x.json" "$rec"
exec 8> "$rec.lock"; flock 8   # the test holds the lock: the three steps below queue behind it, and the waiters are read from /proc/locks
sf 0.2.0 "the recorded third step" >/dev/null 2>&1 8>&- & p1=$!
sf 0.2.0 "post the notes" --evidence "https://example.net/p/2" >/dev/null 2>&1 8>&- & p2=$!
sf 0.2.0 "announce 0.2.0 to the list" >/dev/null 2>&1 8>&- & p3=$!
ino=$(stat -c %i "$rec.lock")
if [ -r /proc/locks ]; then
  w=0; for _ in $(seq 400); do [ "$(grep -c -- "-> FLOCK.* [0-9a-f]*:[0-9a-f]*:$ino " /proc/locks)" -ge 3 ] && { w=1; break; }; sleep 0.05; done
  [ $w = 1 ] && ok "three steps wait for the record's lock while it is held" || no "the steps did not wait for the lock: $(cat /proc/locks)"
fi
[ "$(jq -r '[.steps[] | select(.state == "done")] | length' "$rec")" = 0 ] && ok "the record is not touched while the lock is held" || no "a step wrote without the lock"
flock -u 8; exec 8>&-
wait "$p1" && wait "$p2" && wait "$p3" && ok "the queued steps all finish" || no "a queued step failed"
[ "$(jq -r '[.steps[] | select(.state == "done")] | length' "$rec")" = 3 ] && [ "$(jq -r '.steps[1].evidence' "$rec")" = "https://example.net/p/2" ] && ok "three steps recorded at the same moment are all in the record" || no "a step was lost: $(jq -c .steps "$rec")"
[ "$(find "$T/s/release" -name 'relaf-0.2.0.after.json.*' ! -name '*.lock' | wc -l)" = 0 ] && ok "no temporary file of the record is left" || no "a temporary file is left: $(ls "$T/s/release")"
for i in 1 2 3 4 5 6; do sf 0.2.0 "announce 0.2.0 to the list" --again --evidence "r$i" >/dev/null 2>&1 & done; wait
[ "$(jq -r '[.steps[] | select(.state == "done")] | length' "$rec")" = 3 ] && jq -e '.schema == 2' "$rec" >/dev/null && ok "steps repeated at once leave a whole record" || no "the record is damaged: $(cat "$rec")"

# --- no steps: nothing is printed and nothing recorded
jq 'del(.release)' "$T/c/projects/relaf.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/relaf.json"
git -C "$R" checkout -q develop 2>/dev/null; echo "- b" >> "$R/CHANGELOG.md"; git -C "$R" commit -q -am b; git -C "$R" checkout -q parked
git -C "$R" push -q origin develop 2>/dev/null
$REL verify 0.3.0 >/dev/null 2>&1; rstart 0.3.0 --allow-empty-notes >/dev/null 2>&1 || no "release 0.3.0 could not start"
t=$($REL push 0.3.0 | tok); $REL push 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.3.0 | tok); out=$($REL finish 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q "after the release" <<<"$out" && [ ! -e "$T/s/release/relaf-0.3.0.after.json" ] && ok "without release.after_steps finish prints and records nothing of the kind" || no "no steps: rc=$rc $out"

cd "$ROOT" || exit 1
shellcheck -x -S warning tests/test_release_after_steps.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
