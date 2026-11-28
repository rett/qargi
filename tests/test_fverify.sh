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
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app QARGI_LEAD=lead-one
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
$DA project template app | jq --arg p "$R" '.repo.url = "https://github.com/acme/app" | .repo.path = $p | .test_command = "true"' > "$T/c/projects/app.json"
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
# the history of the runs ($STATE/history/PROJECT.jsonl, lib/history.py): one entry for each run, evidence and no gate
HF=$T/s/history/app.jsonl
hq() { jq -rs "$1" "$HF"; }   # a jq program over the entries of the history
{ [ "$(hq '[.[] | select(.name == "why")] | map(.result) | join(",")')" = pass,pass,pass ] && [ "$(hq '[.[] | select(.name == "bad")] | length')" = 1 ] && [ "$(hq 'length')" = 4 ]; } \
  && ok "the history holds one entry for each verify so far: three passes of why, one run of bad" || no "history entries: $(cat "$HF" 2>&1)"
bh=$(git -C "$R" rev-parse feature/bad)
hq '.[] | select(.name == "bad")' > "$T/hbad.json"
jq -e --arg h "$bh" --arg t "$(git -C "$R" rev-parse "feature/bad^{tree}")" '.kind == "qargi-history-entry" and .schema == 1 and .entry_kind == "suite" and .project == "app" and .verb == "feature verify" and .branch == "feature/bad"
  and .result == "fail" and .head == $h and .tree == $t and .command == "bash tests/run.sh -j 2" and .environment_id == null and .attempt == 1 and (.id | test("^[0-9a-f]{16}$"))
  and .failing_tests == ["FAIL the second check of the bad step"] and .failing_total == 1 and (.seconds | type) == "number" and (.started | test("Z$")) and (.ended | test("Z$"))' "$T/hbad.json" >/dev/null \
  && ok "a failed run's entry names the head and its tree, the command, the failing test and the attempt" || no "bad entry: $(cat "$T/hbad.json")"
hlog=$(jq -r '.log' "$T/hbad.json")
{ [ "$hlog" = "$T/s/suite-logs/runs/$(jq -r .id "$T/hbad.json").log" ] && [ "$(stat -c %a "$hlog")" = 600 ] && [ "$(stat -c %a "$T/s/history")" = 700 ] && [ "$(stat -c %a "$HF")" = 600 ] && cmp -s "$hlog" "$lg"; } \
  && ok "the log of the run is kept under suite-logs/runs/ID.log (mode 600), as the last-run file has it; the history file is 600 in a 700 directory" || no "kept log: $hlog $(stat -c %a "$hlog" "$HF" 2>&1)"
cp "$HF" "$T/h0"
setcmd 'echo some output; exit 3'
out=$($F verify bad 2>&1); rc=$?
[ $rc = 1 ] && grep -qx 'no failing test name in the output; its last lines:' <<<"$out" && grep -qx '  some output' <<<"$out" && [ "$(tail -n 1 <<<"$out")" = "log of the whole run: $lg" ] \
  && ok "a test command that is no runner: its last lines stand in, then the log" || no "plain command: $out"
# the failure-line patterns any gate may print: ^FAIL( |:), ^FAILED: , ^logs of the failed steps: and the ^--- FAIL: of a Go test run
out=$($F verify bad 2>&1)
{ [ "$(hq '[.[] | select(.name == "bad" and .command == "echo some output; exit 3")] | map("\(.attempt):\(.failing_total)") | join(",")')" = 1:0,2:0 ] && cmp -s -n "$(stat -c %s "$T/h0")" "$T/h0" "$HF"; } \
  && ok "a second run of the same head, tree and command is attempt 2, and what was written before is unchanged" || no "attempts: $(cat "$HF")"
# a verb that is killed after its suite ran leaves an entry too: the suite command kills the verb (its pid is written by the shell that becomes the verb)
cp "$T/s/releases/app-feature_bad.json" "$T/rec0"
setcmd "kill -TERM \$(cat '$T/vp'); exit 1"
out=$(bash -c 'echo $$ > "$1"; shift; exec "$@"' _ "$T/vp" $DA feature verify bad 2>&1); rc=$?
{ [ "$rc" = 143 ] && [ "$(hq '[.[] | select(.name == "bad")] | last | .result')" = interrupted ] && ! grep -q 'full suite: ' <<<"$out" && [ ! -e "$T/s/busy/app.verify.pid" ]; } \
  && ok "a verify that is killed after its suite ran still leaves its entry, with the result interrupted (and no verdict)" || no "interrupted: rc=$rc $out $(tail -n 1 "$HF")"
cmp -s "$T/rec0" "$T/s/releases/app-feature_bad.json" && ok "the interrupted run changed no verdict: the record of the branch's last run is as it was" || no "the record after the interrupt: $(cat "$T/s/releases/app-feature_bad.json")"
setcmd 'printf "%s\n" "--- FAIL: TestParse (0.00s)" "FAIL: check two" "FAIL check three" "FAILED: step four" "logs of the failed steps: /logs/five"; exit 1'
out=$($F verify bad 2>&1); rc=$?
[ $rc = 1 ] && grep -qx 'failing tests:' <<<"$out" && grep -qx '  --- FAIL: TestParse (0.00s)' <<<"$out" && grep -qx '  FAIL: check two' <<<"$out" && grep -qx '  FAIL check three' <<<"$out" \
  && grep -qx 'failing steps:' <<<"$out" && grep -qx '  step four' <<<"$out" && grep -qx 'logs of the failed steps: /logs/five' <<<"$out" && ! grep -q 'no failing test name' <<<"$out" \
  && ok "--- FAIL: , FAIL: , FAIL , FAILED:  and logs of the failed steps: lines are all named" || no "failure-line patterns: $out"
hlp=$($DA help feature verify 2>&1 | tr '\n' ' ' | tr -s ' ')
grep -qF '^FAILED:' <<<"$hlp" && grep -qF '^FAIL( |:)' <<<"$hlp" && grep -qF '^--- FAIL:' <<<"$hlp" && grep -qF '^logs of the failed steps:' <<<"$hlp" \
  && ok "the help of feature verify names the failure-line patterns" || no "help: $hlp"
setcmd 'bash tests/run.sh -j 2'
out=$($REL verify 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && grep -qx '  sh tests/test_bad.sh' <<<"$out" && [ "$(tail -n 1 <<<"$out")" = "log of the whole run: $T/s/suite-logs/app.release-0.9.0.log" ] && ok "release verify ends the same way" || no "release verify: $out"
hq '.[] | select(.name == "0.9.0")' > "$T/hrel.json"
jq -e --arg h "$(git -C "$R" rev-parse develop)" '.entry_kind == "suite" and .verb == "release verify" and .branch == "develop" and .result == "fail" and .head == $h and .attempt == 1
  and .failing_tests == ["FAIL the second check of the bad step"] and .log != null' "$T/hrel.json" >/dev/null \
  && ok "release verify leaves its entry too (the version as the name, develop as the branch it ran on)" || no "release entry: $(cat "$T/hrel.json")"
setcmd 'exit 0'

# --- 3. the finish plan says whether develop is pushed, by the answer branches.push_develop
feat() { $F start "$1" >/dev/null 2>&1; task "$2"; $F merge "$1" "agent/$2" >/dev/null 2>&1; $F verify "$1" >/dev/null 2>&1; }
feat pd1 e1
out=$($F finish pd1 2>&1); t_true=$(tok <<<"$out")
[ "$(head -n 1 <<<"$out")" = "push: yes, to origin/develop" ] && [ "$(sed -n 2p <<<"$out")" = "merge into: develop" ] && ok "the first lines of the plan say develop will be pushed, to origin/develop, and is the merge destination (the default)" || no "default plan: $out"
out=$($DA project set app branches.push_develop false 2>&1) && grep -q 'branches.push_develop = false' <<<"$out" && ok "project set accepts branches.push_develop false" || no "project set: $out"
out=$($DA project set app branches.push_develop maybe 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'branches.push_develop: true' <<<"$out" && [ "$(jq -r '.branches.push_develop' "$T/c/projects/app.json")" = false ] && ok "and refuses anything but true or false, changing nothing" || no "project set maybe rc=$rc: $out"
d0=$(git -C "$R" rev-parse develop); od0=$(git -C "$T/origin.git" rev-parse develop)
out=$($F finish pd1 2>&1); t_false=$(tok <<<"$out")
[ "$(head -n 1 <<<"$out")" = "push: no, develop stays local (branches.push_develop is false)" ] && [ "$(sed -n 2p <<<"$out")" = "merge into: develop" ] && ! grep -q ', push develop' <<<"$out" && [ -n "$t_false" ] && [ "$t_false" != "$t_true" ] && ok "false: the plan says local only, and its token is another plan" || no "false plan: $out"
$F finish pd1 --plan "$t_true" --approved go >/dev/null 2>&1 && no "the token of the pushing plan was accepted after the policy changed" || ok "the token of the earlier plan is refused"
[ "$(git -C "$R" rev-parse develop)" = "$d0" ] && ok "a refused token changes nothing" || no "develop moved on a refused token"
out=$($F finish pd1 --plan "$t_false" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-parse develop)" != "$d0" ] && [ "$(git -C "$T/origin.git" rev-parse develop)" = "$od0" ] && grep -q 'develop was not pushed (branches.push_develop is false)' <<<"$out" && ! grep -qx 'pushed develop' <<<"$out" \
  && ok "finish merges locally and leaves origin's develop alone" || no "local finish rc=$rc: $out"
$DA project set app branches.push_develop true >/dev/null 2>&1
feat pd2 e2
out=$($F finish pd2 2>&1); t=$(tok <<<"$out")
[ "$(head -n 1 <<<"$out")" = "push: yes, to origin/develop" ] && ok "true: the plan says it will push" || no "true plan: $out"
$F finish pd2 --plan "$t" --approved go >/dev/null 2>&1
[ "$(git -C "$T/origin.git" rev-parse develop)" = "$(git -C "$R" rev-parse develop)" ] && ok "and finish pushes develop (the local-only merge of before goes with it)" || no "push after true"
git -C "$R" remote remove origin
feat pd3 e3
out=$($F finish pd3 2>&1)
[ "$(head -n 1 <<<"$out")" = "push: no, develop stays local (the repository has no origin)" ] && ok "a repository with no origin: local only, whatever the answer" || no "no origin plan: $out"

# --- 4. verify warns, and goes on, when another suite may be running
$F start wn >/dev/null 2>&1; task g1; $F merge wn agent/g1 >/dev/null 2>&1
warns() { grep -c '^qargi: warning: \(another whole-suite run\|the local run\|tests/run.sh is running\)' <<<"$1" || true; }
out=$($F verify wn 2>&1); rc=$?
[ $rc = 0 ] && [ "$(warns "$out")" = 0 ] && ok "nothing else running: no warning" || no "quiet verify rc=$rc: $out"
# a whole-suite run of the project in progress (a live pid in the busy directory)
sleep 60 & spid=$!
mkdir -p "$T/s/busy"; echo "$spid" > "$T/s/busy/app.verify.other.pid"
out=$($F verify wn 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^qargi: warning: another whole-suite run of app is in progress (verify.other, pid $spid)" <<<"$out" && grep -q '^full suite: pass' <<<"$out" && ok "a live whole-suite run of the project: a warning, and the verify goes on" || no "busy warning rc=$rc: $out"
kill "$spid" 2>/dev/null; wait "$spid" 2>/dev/null
out=$($F verify wn 2>&1)
[ "$(warns "$out")" = 0 ] && ok "a pid file whose process is gone is ignored" || no "dead pid: $out"
rm -f "$T/s/busy/app.verify.other.pid"
# a local run of this repository with recent activity
RUN=$T/run1; mkdir -p "$RUN/clone/.git" "$RUN/out"; echo x > "$RUN/started"; echo y > "$RUN/clone/.git/index"
jq -nc --arg r "$RUN" --arg p "$R" '{run:$r, slug:"x", repo:$p}' > "$T/s/local-runs.jsonl"
out=$($F verify wn 2>&1)
grep -q "^qargi: warning: the local run $RUN of app had activity in the last 10 minutes" <<<"$out" && ok "a local run of the repository with a recent file: a warning" || no "recent run: $out"
find "$RUN" -exec touch -d '3 hours ago' {} +
out=$($F verify wn 2>&1)
[ "$(warns "$out")" = 0 ] && ok "the same run, quiet for hours: no warning" || no "old run: $out"
touch "$RUN/clone/.git/index"; out=$(QARGI_ACTIVE_MINUTES=0 $F verify wn 2>&1)
[ "$(warns "$out")" = 0 ] && ok "QARGI_ACTIVE_MINUTES sets how recent counts" || no "minutes: $out"
jq -nc --arg r "$RUN" --arg p "$R" --arg c "2026-01-01T00:00:00Z" '{run:$r, slug:"x", repo:$p, cleaned:$c}' > "$T/s/local-runs.jsonl"
out=$($F verify wn 2>&1)
[ "$(warns "$out")" = 0 ] && ok "a cleaned run is not counted" || no "cleaned run: $out"
jq -nc --arg r "$RUN" --arg p "$T/elsewhere" '{run:$r, slug:"x", repo:$p}' > "$T/s/local-runs.jsonl"
out=$($F verify wn 2>&1)
[ "$(warns "$out")" = 0 ] && ok "nor is a run of another repository" || no "other repo run: $out"
# a tests/run.sh process whose directory belongs to this repository (Linux: /proc)
if [ -d /proc/$$ ]; then
  mkdir -p "$R/sleeper/tests" "$T/other/tests"; git init -q "$T/other"
  printf '#!/bin/bash\ntrap '"'"'kill $p'"'"' TERM\nsleep 600 &\np=$!\nwait $p\n' | tee "$R/sleeper/tests/run.sh" > "$T/other/tests/run.sh"
  (cd "$T/other" && exec bash tests/run.sh) & opid=$!
  out=$($F verify wn 2>&1)
  [ "$(warns "$out")" = 0 ] && ok "a tests/run.sh of another repository is not counted" || no "other repo process: $out"
  (cd "$R/sleeper" && exec bash tests/run.sh) & rpid=$!
  for _ in $(seq 20); do
    out=$($F verify wn 2>&1); rc=$?
    grep -q "^qargi: warning: tests/run.sh is running" <<<"$out" && break
    sleep 0.5
  done
  [ $rc = 0 ] && grep -q "^qargi: warning: tests/run.sh is running in this repository (pid $rpid, in $R/sleeper)" <<<"$out" && ok "a tests/run.sh running in the repository: a warning" || no "process warning rc=$rc: $out"
  out=$($REL verify 0.9.1 2>&1); rc=$?
  [ $rc = 0 ] && grep -q "^qargi: warning: tests/run.sh is running in this repository (pid $rpid" <<<"$out" && grep -q '^full suite: pass' <<<"$out" && ok "release verify warns the same way and goes on" || no "release warning rc=$rc: $out"
  kill "$opid" "$rpid" 2>/dev/null; wait "$opid" "$rpid" 2>/dev/null
  out=$($F verify wn 2>&1)
  [ "$(warns "$out")" = 0 ] && ok "and nothing once it has ended" || no "after: $out"
  # a process that exits between the listing and the read: the function says no and prints nothing (the shell opens a redirection before
  # a 2>/dev/null written after it applies, so the "no such file" of the open has to be silenced by a group)
  gone=4194305   # above the largest pid_max of Linux, so no such process
  bash -c '. "$1/lib/gitflow.sh"; suite_cmdline "$2"' _ "${DA%/bin/qargi}" "$gone" 2>"$T/gone.err"; rc=$?
  [ $rc = 1 ] && [ ! -s "$T/gone.err" ] && ok "suite_cmdline of a pid that is gone: status 1, nothing on standard error" || no "gone pid rc=$rc: $(cat "$T/gone.err")"
fi

# --- 5. the queue of the whole-suite runs: one slot for each user, first in, first out (lib/suite_queue.py)
# A tiny fake suite: it says it started (its pid, one line of FAKE_STARTS), then waits, bounded, for the file FAKE_GO. No fixed sleep decides what the test sees: it polls for
# the lines and the files the runs write.
SQ="python3 -I ${DA%/bin/qargi}/lib/suite_queue.py"
printf '#!/bin/bash\necho "$$" >> "$FAKE_STARTS"\n for _ in $(seq 1500); do [ -e "$FAKE_GO" ] && break; sleep 0.02; done\n' > "$T/fake.sh"
setcmd "bash $T/fake.sh"
nstarts() { if [ -f "$T/starts" ]; then wc -l < "$T/starts"; else echo 0; fi; }
started() { [ "$(nstarts)" -ge "$1" ]; }
qstatus() { $SQ status --state "$T/s" --json; }
waited_for() { qstatus | jq -e --argjson n "$1" '.waiting[0].waiting_seconds >= $n' >/dev/null 2>&1; }       # the first waiter has waited N seconds, by the queue's own clock
no_waiters() { [ "$(qstatus | jq '.waiting | length')" = 0 ]; }
reap() { # PID: waits, bounded, for a background verb; its status in rc_ (KILLED when it had to be stopped)
  local i
  for i in $(seq 1200); do kill -0 "$1" 2>/dev/null || break; sleep 0.05; done
  if kill -0 "$1" 2>/dev/null; then kill -9 "$1" 2>/dev/null; rc_=KILLED; else wait "$1"; rc_=$?; fi
}
for n in qa qb qc qd; do $F start $n >/dev/null 2>&1; task "i$n"; $F merge $n "agent/i$n" >/dev/null 2>&1; done
rm -f "$T/starts" "$T/go"
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qa > "$T/qa.out" 2>&1 & pa=$!
wait_until 'started 1' 30 && ok "the first verify's suite is running" || no "the first suite did not start: $(cat "$T/qa.out")"
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qb > "$T/qb.out" 2>&1 & pb=$!
on_line() { grep -q '^qargi: suite queue: position 1, holder is app feature verify qa (running ' "$T/qb.out"; }
wait_until on_line 30 && ok "a second verify, started while the first's suite runs, waits and prints the holder and its place" || no "no queue line: $(cat "$T/qb.out")"
wait_until 'waited_for 4' 30 && ok "it has waited four seconds by the queue's clock" || no "no waiter: $(qstatus)"
[ "$(cat "$T/s/busy/app.verify.qb.pid" 2>/dev/null)" = "$pb" ] && ok "its busy mark stands while it waits (a second verify of this name is seen, a compact is not safe)" || no "no busy mark of the waiting verify: $(ls "$T/s/busy" 2>&1)"
doc=$(qstatus)
{ [ "$(nstarts)" = 1 ] && jq -e --argjson p "$pa" '.state == "held" and .holder.pid == $p and .holder.project == "app" and .holder.verb == "feature verify" and .holder.name == "qa" and (.waiting | length) == 1
    and .waiting[0].position == 1 and .waiting[0].name == "qb" and .waiting[0].verb == "feature verify"' <<<"$doc" >/dev/null; } \
  && ok "its suite has not started; the queue names the holder and the waiter" || no "queue while waiting: starts=$(nstarts) $doc"
! grep -q 'warning: another whole-suite run' "$T/qb.out" && ok "the holder is named by the queue, not warned about as an unexplained busy run" || no "busy warning: $(cat "$T/qb.out")"
touch "$T/go"
reap "$pa"; ra=$rc_; reap "$pb"; rb=$rc_
{ [ "$ra" = 0 ] && [ "$rb" = 0 ] && grep -q '^full suite: pass' "$T/qa.out" && grep -q '^full suite: pass' "$T/qb.out" && [ "$(nstarts)" = 2 ]; } \
  && ok "both pass, one after the other" || no "after go: ra=$ra rb=$rb starts=$(nstarts): $(cat "$T/qa.out" "$T/qb.out")"
{ [ "$(grep -c 'suite queue:' "$T/qb.out")" = 1 ] && ! grep -q 'suite queue:' "$T/qa.out"; } && ok "the line is printed once while nothing changes, and not at all by the run that did not wait" || no "queue lines: $(cat "$T/qa.out" "$T/qb.out")"
{ [ "$(hq '[.[] | select(.name == "qa")] | length')" = 1 ] && [ "$(hq '[.[] | select(.name == "qb")] | length')" = 1 ] && [ "$(hq '.[] | select(.name == "qa") | .queue_wait_s')" = 0 ]; } \
  && ok "both runs are in the history, the first with queue_wait_s 0" || no "history: $(tail -n 2 "$HF")"
qw=$(hq '.[] | select(.name == "qb") | .queue_wait_s'); sec=$(hq '.[] | select(.name == "qb") | .seconds'); rsec=$(jq -r .seconds "$T/s/releases/app-feature_qb.json")
{ [ "$qw" -ge 4 ] && [ "$((sec + 2))" -le "$qw" ] && [ "$((rsec + 2))" -le "$qw" ]; } \
  && ok "the second records queue_wait_s $qw, which is not in its seconds ($sec in the history, $rsec in the record of the branch)" || no "queue_wait_s=$qw seconds=$sec record=$rsec"
jq -e '.queue_wait_s | type == "number"' <<<"$(hq '.[] | select(.name == "qb")')" >/dev/null && ok "queue_wait_s is a JSON integer of the entry" || no "queue_wait_s type"
{ [ "$(stat -c %a "$T/s/suite-queue")" = 700 ] && [ "$(ls "$T/s/suite-queue")" = lock ] && [ "$(stat -c %a "$T/s/suite-queue/lock")" = 600 ]; } \
  && ok "nothing but the lock file is left in the queue directory (mode 700), and the status says free" || no "queue directory: $(ls -la "$T/s/suite-queue")"
[ "$(qstatus | jq -r '.state')" = free ] || no "status after: $(qstatus)"
# --queue-wait: the bound ends the wait with a refusal and records nothing
rm -f "$T/starts" "$T/go"
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qc > "$T/qc.out" 2>&1 & pc=$!
wait_until 'started 1' 30 || no "the holder did not start: $(cat "$T/qc.out")"
nh=$(hq 'length')
out=$($F verify qd --queue-wait 0 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q '"code":"suite-queue-busy"' <<<"$out" && grep -q '"exit":1' <<<"$out" && grep -q '"verb":"feature verify"' <<<"$out" \
    && grep -q 'qargi: refused \[suite-queue-busy\] the suite queue is busy: app feature verify qc holds the slot, and the wait of 0 s reached --queue-wait' <<<"$out"; } \
  && ok "--queue-wait 0 refuses at once with suite-queue-busy (exit 1), naming the holder and the seconds waited" || no "queue-wait 0 rc=$rc: $out"
{ [ "$(hq 'length')" = "$nh" ] && [ ! -e "$T/s/releases/app-feature_qd.json" ] && [ ! -e "$T/s/suite-logs/app.feature-qd.log" ] && [ "$(nstarts)" = 1 ] && no_waiters && [ ! -e "$T/s/busy/app.verify.qd.pid" ]; } \
  && ok "the refusal recorded nothing: no history entry, no record, no log, no waiter left, nothing run" || no "after the refusal: $(tail -n 1 "$HF") $(ls "$T/s/suite-queue")"
out=$($REL verify 0.9.3 --queue-wait 0 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q '"code":"suite-queue-busy"' <<<"$out" && grep -q '"verb":"release verify"' <<<"$out" && [ "$(hq 'length')" = "$nh" ]; } \
  && ok "release verify --queue-wait 0 is refused the same way, with nothing recorded" || no "release queue-wait 0 rc=$rc: $out"
$F verify qd --queue-wait 2>/dev/null; r1=$?; $F verify qd --queue-wait soon >/dev/null 2>&1; r2=$?; $F status qd --queue-wait 1 >/dev/null 2>&1; r3=$?; $REL status 0.9.3 --queue-wait 1 >/dev/null 2>&1; r4=$?
[ "$r1$r2$r3$r4" = 2222 ] && ok "--queue-wait needs a whole number and belongs to the two verify verbs (exit 2)" || no "usage errors: $r1 $r2 $r3 $r4"
touch "$T/go"; reap "$pc"
[ "$rc_" = 0 ] && ok "the holder went on to pass" || no "holder rc=$rc_: $(cat "$T/qc.out")"
$F verify qd >/dev/null 2>&1
[ "$(hq '[.[] | select(.name == "qd")] | map(.attempt) | join(",")')" = 1 ] && ok "the refused run counted no attempt: the one that ran is attempt 1" || no "attempts of qd: $(hq '[.[] | select(.name == "qd")]')"
# a waiter that is killed leaves nothing in the way; a holder that is killed leaves no stale lock, but its suite is still running, so the slot stays taken until that suite ends
rm -f "$T/starts" "$T/go"
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qa > "$T/qa.out" 2>&1 & pa=$!
wait_until 'started 1' 30 || no "the holder did not start: $(cat "$T/qa.out")"
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qb > "$T/qb.out" 2>&1 & pb=$!
wait_until on_line 30 || no "no queue line: $(cat "$T/qb.out")"
kill -9 "$pb"; wait "$pb" 2>/dev/null
wait_until no_waiters 30 && ok "a waiter killed with SIGKILL is no longer in the queue" || no "the dead waiter stays: $(qstatus)"
kill -9 "$pa"; wait "$pa" 2>/dev/null
FAKE_STARTS=$T/starts FAKE_GO=$T/go $F verify qc > "$T/qc.out" 2>&1 & pc=$!
on_gone() { grep -q '^qargi: suite queue: position 1, holder is app feature verify qa, whose verb is gone' "$T/qc.out"; }
wait_until on_gone 30 && ok "a holder killed with SIGKILL: its suite still runs, so the next verify waits, and the line says whose verb is gone" || no "no line for a killed holder: $(cat "$T/qc.out")"
{ [ "$(nstarts)" = 1 ] && jq -e '.state == "held" and .holder == null and (.waiting | length) == 1 and .waiting[0].name == "qc"' <<<"$(qstatus)" >/dev/null; } && ok "nothing overlaps: the second suite has not started, and the queue shows the lock held with its waiter" || no "orphaned holder: starts=$(nstarts) $(qstatus)"
touch "$T/go"; reap "$pc"
{ [ "$rc_" = 0 ] && [ "$(nstarts)" = 2 ] && grep -q '^full suite: pass' "$T/qc.out"; } && ok "the slot is free when the orphaned suite has ended, and the waiter then runs and passes" || no "qc rc=$rc_ starts=$(nstarts): $(cat "$T/qc.out")"
fake_alive() { local p; while read -r p; do kill -0 "$p" 2>/dev/null && return 0; done < "$T/starts"; return 1; }
wait_until '! fake_alive' 30 && ok "no fake suite is left running" || no "a fake suite is still running"
# two verifies of one name: the second waits for the slot, and the first has read the log, the gate list and the reports of its suite (history entry, record of the branch) before the
# slot is let go, because the second rewrites them as soon as it holds it. The suite of the second says, when it starts, what it finds: the entries of the history of this name, and
# whether the record of the branch is there.
$F start qe >/dev/null 2>&1; task iqe; $F merge qe agent/iqe >/dev/null 2>&1
{
  echo '#!/bin/bash'
  echo 'echo "$$" >> "$FAKE_STARTS"'
  echo '{ jq -s "[.[] | select(.name == \"qe\")] | length" "$FAKE_HIST"; [ ! -f "$FAKE_REC" ] || echo record; } >> "$FAKE_SEEN"'
  echo 'echo "FAIL the check of qe"'
  echo 'for _ in $(seq 1500); do [ -e "$FAKE_GO" ] && break; sleep 0.02; done'
  echo 'exit 1'
} > "$T/fake2.sh"
setcmd "bash $T/fake2.sh"
rm -f "$T/starts" "$T/go" "$T/seen"
export FAKE_STARTS=$T/starts FAKE_GO=$T/go FAKE_HIST=$HF FAKE_SEEN=$T/seen FAKE_REC=$T/s/releases/app-feature_qe.json
$F verify qe > "$T/qe1.out" 2>&1 & pe1=$!
wait_until 'started 1' 30 || no "the first verify of qe did not start: $(cat "$T/qe1.out")"
$F verify qe > "$T/qe2.out" 2>&1 & pe2=$!
on_line_qe() { grep -q '^qargi: suite queue: position 1, holder is app feature verify qe (running ' "$T/qe2.out"; }
wait_until on_line_qe 30 || no "the second verify of qe did not wait: $(cat "$T/qe2.out")"
touch "$T/go"
reap "$pe1"; r1=$rc_; reap "$pe2"; r2=$rc_
unset FAKE_STARTS FAKE_GO FAKE_HIST FAKE_SEEN FAKE_REC
{ [ "$r1" = 1 ] && [ "$r2" = 1 ] && [ "$(nstarts)" = 2 ] && [ "$(tr '\n' ' ' < "$T/seen")" = "0 1 record " ]; } \
  && ok "the second verify of a name starts its suite only after the first has written its history entry and its record" || no "same name: r1=$r1 r2=$r2 starts=$(nstarts) seen=$(tr '\n' ' ' < "$T/seen")"
grep -q 'the check of qe' "$T/qe1.out" && grep -q '^failing tests:' "$T/qe1.out" && ok "and the first's report of its failure names its test" || no "report of the first: $(cat "$T/qe1.out")"
{ [ "$(hq '[.[] | select(.name == "qe")] | length')" = 2 ] && [ ! -e "$T/s/busy/app.verify.qe.pid" ]; } && ok "both are in the history, and no busy mark is left" || no "after the two: $(hq '[.[] | select(.name == "qe")] | length') $(ls "$T/s/busy")"
setcmd "bash $T/fake.sh"
# a tests/run.sh below a run of the queue (qargi suite run -- ...) is named by the queue, not warned about as another suite in the repository (the one that no queue holds is, above)
if [ -d /proc/$$ ]; then
  mkdir -p "$R/sleeper2/tests"
  printf '#!/bin/bash\n for _ in $(seq 1500); do [ -e "%s" ] && break; sleep 0.02; done\n' "$T/stop2" > "$R/sleeper2/tests/run.sh"
  (cd "$R/sleeper2" && exec "$DA" suite run -- bash tests/run.sh) & qpid=$!
  held_by_run() { qstatus | jq -e '.holder.verb == "suite run"' >/dev/null; }
  wait_until held_by_run 30 || no "the suite run did not take the slot: $(qstatus)"
  out=$($F verify qd --queue-wait 0 2>&1); rc=$?
  { [ $rc = 1 ] && grep -q 'qargi: refused \[suite-queue-busy\] the suite queue is busy: app suite run bash run.sh holds the slot' <<<"$out" && [ "$(warns "$out")" = 0 ]; } \
    && ok "a tests/run.sh below a run of the queue is named by the queue (suite run bash run.sh) and not warned about" || no "queued run.sh: rc=$rc $out"
  touch "$T/stop2"; reap "$qpid"
  [ "$rc_" = 0 ] && ok "and the suite run ends with the status of its command" || no "suite run rc=$rc_"
fi

[ "$fail" = 0 ] && echo "all fverify tests passed"
exit "$fail"
