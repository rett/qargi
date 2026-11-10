#!/usr/bin/env bash
# The task block `qargi local prepare` writes (RUN/task.md) for every runtime: golden files for a build and a review run, the refusals (a DONE
# that is not a command, an empty or linked task file), and SCOPE as the limit `qargi review check` applies. Run: tests/test_taskblock.sh
# UPDATE_GOLDEN=1 bash tests/test_taskblock.sh rewrites tests/golden/taskblock-*.md (read the diff before committing it).
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
Q=$PWD/bin/qargi; GOLD=$PWD/tests/golden
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
R=$T/fixrepo
git init -q -b main "$R" && mkdir -p "$R/tests" && printf '#!/bin/sh\nexit 0\n' > "$R/tests/check.sh" && chmod +x "$R/tests/check.sh"
git -C "$R" add -A && git -C "$R" -c user.name=t -c user.email=t@example.net commit -q -m one
# a read-only role is looked up through the repository's project (its local provider)
mkdir -p "$T/c/projects" "$T/c/profiles"
jq -n --arg p "$R" '{schema:1,project:"fixproj",repo:{url:"https://github.com/example/fixproj",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/fixproj.json"
printf '# Profile of fixrepo\n\nGates: `make test`.\nRule: no private names.\n' > "$T/c/profiles/fixrepo.md"
printf 'Add the flag --quiet to the tool.\n\nIt prints nothing on success.\n' > "$T/task.txt"
runs() { find "$T" -maxdepth 1 -name 'qargi.??????' | wc -l; }
# prep ARGS...: prepare in the fixture repository; sets RUN, TMPD and BSHA from its output
prep() { local out; out=$($Q local prepare --repo "$R" --base main --scratch "$T" "$@" 2>&1) || { echo "$out"; return 1; }
  PREP=$out; RUN=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); TMPD=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out"); BSHA=$(sed -n '1,/^$/s/^BASE_SHA=//p' <<<"$out"); }
# norm FILE: the paths and the SHA of a run replaced, so the golden file holds nothing of this machine
norm() { sed -e "s|$RUN|<RUN>|g" -e "s|$TMPD|<TMP>|g" -e "s|$BSHA|<BASE_SHA>|g" "$1"; }
golden() { # NAME FILE: compare the normalised task block with tests/golden/NAME
  if [ -n "${UPDATE_GOLDEN:-}" ]; then mkdir -p "$GOLD"; norm "$2" > "$GOLD/$1"; fi
  if norm "$2" | diff -u "$GOLD/$1" - > "$T/golden.diff" 2>&1; then ok "task.md matches tests/golden/$1"; else no "task.md differs from tests/golden/$1"; head -30 "$T/golden.diff"; fi
}

# --- the golden files: a build run (task file, DONE, two scope paths, the repository's profile) and a review run (no scope)
prep --slug gold --role build --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope lib/ --scope ./docs/guide.md || no "prepare with a task block failed"
[ -f "$RUN/task.md" ] && ok "prepare writes RUN/task.md when given --task-file" || no "no RUN/task.md"
golden taskblock-build.md "$RUN/task.md"
grep -qx "TASK_FILE=$RUN/task.md" <<<"$PREP" && ok "prepare prints TASK_FILE=RUN/task.md, the path the lead hands the member" || no "no TASK_FILE line"
grep -q "^BASE_SHA: $(git -C "$R" rev-parse main)$" "$RUN/task.md" && ok "the block names the base SHA" || no "base sha"
grep -q '^SCOPE: lib/, docs/guide.md$' "$RUN/task.md" && ok "SCOPE is one line, the paths comma separated" || no "scope line: $(grep SCOPE: "$RUN/task.md")"
prep --slug goldrev --role review --task-file "$T/task.txt" --done 'bash tests/check.sh' || no "prepare of a review run with a task block failed"
golden taskblock-review.md "$RUN/task.md"
grep -q '^SCOPE: none$' "$RUN/task.md" && ok "without --scope the block says SCOPE: none" || no "scope none"

# --- a run without the flags is as before: no task.md
prep --slug plain || no "plain prepare failed"
[ ! -e "$RUN/task.md" ] && ok "without --task-file there is no task.md (as before)" || no "task.md without the flag"

# --- the refusals: each makes no run
refuse() { # LABEL EXPECTED-TEXT ARGS...
  local label=$1 want=$2 before out rc; shift 2; before=$(runs)
  out=$($Q local prepare --repo "$R" --base main --scratch "$T" "$@" 2>&1); rc=$?
  if [ "$rc" = 2 ] && grep -q -- "$want" <<<"$out" && [ "$(runs)" = "$before" ]; then ok "$label is refused (usage error, exit 2), and no run is made"; else no "$label: rc=$rc runs $before -> $(runs): $out"; fi
}
# the same for a refusal that takes its own arguments: prepare with neither --repo nor --repo-url, and a value of an option that cannot be right, are usage errors too
refuse_raw() { # LABEL EXPECTED-TEXT ARGS...: the whole of local prepare's arguments
  local label=$1 want=$2 before out rc; shift 2; before=$(runs)
  out=$($Q local prepare "$@" 2>&1); rc=$?
  if [ "$rc" = 2 ] && grep -q -- "$want" <<<"$out" && [ "$(runs)" = "$before" ]; then ok "$label is a usage error (exit 2), and no run is made"; else no "$label: rc=$rc runs $before -> $(runs): $out"; fi
}
refuse "a prose DONE" "reads as prose" --slug r1 --task-file "$T/task.txt" --done 'the output looks right'
refuse "an empty DONE" "needs --done" --slug r2 --task-file "$T/task.txt" --done ''
refuse "no DONE" "needs --done" --slug r3 --task-file "$T/task.txt"
refuse "a DONE with several lines" "one command line" --slug r4 --task-file "$T/task.txt" --done $'make test\nmake lint'
refuse "a DONE script that does not exist" "not an existing script" --slug r5 --task-file "$T/task.txt" --done './tests/nope.sh'
: > "$T/empty.txt"; printf ' \n\t\n' > "$T/blank.txt"
refuse "an empty task file" "is empty" --slug r6 --task-file "$T/empty.txt" --done 'bash tests/check.sh'
refuse "a blank task file" "is empty" --slug r7 --task-file "$T/blank.txt" --done 'bash tests/check.sh'
ln -s "$T/task.txt" "$T/link.txt"
refuse "a task file that is a link" "is a link" --slug r8 --task-file "$T/link.txt" --done 'bash tests/check.sh'
refuse "a task file that is not there" "no such file" --slug r9 --task-file "$T/missing.txt" --done 'bash tests/check.sh'
printf 'Do it.\nSCOPE: everything\n' > "$T/scoped.txt"
refuse "a task file with its own SCOPE: line" "starts SCOPE:" --slug r10 --task-file "$T/scoped.txt" --done 'bash tests/check.sh'
refuse_raw "prepare with no --repo and no --repo-url" "needs --repo DIR" --base main --scratch "$T" --slug n1
refuse_raw "prepare with a --repo that is no git working tree" "must be a git working tree" --repo "$T" --base main --scratch "$T" --slug n2
refuse_raw "prepare with a --repo-url that is not https" "must be an https URL" --repo-url http://example.invalid/x.git --base main --scratch "$T" --slug n3
refuse_raw "prepare with a --repo-url that carries a user name" "must not carry a user name" --repo-url https://user@example.invalid/x.git --base main --scratch "$T" --slug n4
refuse_raw "prepare with a --credential-file that is not there" "no such file" --repo-url https://example.invalid/x.git --credential-file "$T/nocred" --base main --scratch "$T" --slug n5
refuse_raw "prepare with an unknown --role" "one of" --repo "$R" --role nosuchrole --base main --scratch "$T" --slug n6
refuse_raw "prepare with --role lead" "one of" --repo "$R" --role lead --base main --scratch "$T" --slug n7
refuse_raw "prepare with a --slug of capitals and a space" "lower-case letters" --repo "$R" --base main --scratch "$T" --slug 'Bad Slug'
refuse_raw "prepare with no --slug" "lower-case letters" --repo "$R" --base main --scratch "$T"
refuse_raw "prepare with no --base" "needs --base" --repo "$R" --scratch "$T" --slug n8
refuse_raw "prepare with an option it does not have" "unknown option" --repo "$R" --nosuch x
refuse "an absolute --scope" "relative" --slug r11 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope /etc
refuse "a --scope with .." "relative" --slug r12 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope ../x
refuse "a --scope with a comma" "relative" --slug r13 --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope 'a,b'
refuse "--done without --task-file" "go with --task-file" --slug r14 --done 'bash tests/check.sh'
refuse "--scope without --task-file" "go with --task-file" --slug r15 --scope lib/
# what a DONE may be: an executable, a builtin, a script of the repository, with leading NAME=value words
n=0; for d in 'make test' 'true' 'FOO=1 bash tests/check.sh' './tests/check.sh' 'cd tests && ./check.sh'; do
  n=$((n+1)); prep --slug "d$n" --task-file "$T/task.txt" --done "$d" >/dev/null 2>&1 && grep -qxF "DONE: $d" "$RUN/task.md" && ok "DONE '$d' is accepted" || no "DONE '$d' refused"
done
# the ordinary command lines of a project are DONE lines: the isolated suite run, an assignment with a substitution, a subshell, a script the task creates (it is
# under --scope), a chain, an environment prefix, a negation. A compound line is accepted when bash parses it (only its syntax is checked).
# shellcheck disable=SC2016  # the lines are text for --done
dones=(
  # hermetic: allow tmp (text given to --done, a path the test never touches)
  'T=$(mktemp -d -p /dev/shm); mkdir $T/h; HOME=$T/h bash tests/run.sh'
  'HOME="$(mktemp -d)" bash tests/check.sh' '(cd lib && python3 -m pytest)' 'bash tests/check.sh && bash tests/check.sh' 'FOO=1 BAR=2 make test'
  '! grep -q x README.md' 'env -i make test' 'tests/new_test.sh' 'bash tests/never_made.sh && true' 'make test | tail -n 5' 'FOO="a b" bash tests/check.sh'
  'make test 2>&1 | tail -n 5' 'make test >/dev/null || true' 'diff <(true) <(true)' 'f() { :; }; f && make test' 'if make test; then true; fi' 'echo "a; b > c" && make test'
  'cd tests && ./not_here_after_cd.sh')
for d in "${dones[@]}"; do
  n=$((n+1)); prep --slug "d$n" --task-file "$T/task.txt" --done "$d" --scope tests/new_test.sh >/dev/null 2>&1 && grep -qxF "DONE: $d" "$RUN/task.md" && ok "DONE '$d' is accepted" || no "DONE '$d' refused"
done
# what is plainly not a command line: prose (a sentence whose first word is a path that is not a script, one that bash cannot parse), and a script that is neither at BASE nor under a --scope path
# A line that merely contains an operator is prose too: every command word is checked, not only the first of a simple command (a word that is no command in the middle of
# a line, after ; & && || | or ( or $( ). 'coverage' is left out when the machine has such a command.
prose=('OUT/report.md ends with a verdict line' "the review is done and it's right" 'the output (looks right)' 'tests/never_made.sh' 'bash tests/check.sh; then' 'FOO=1 nothingtorun'
  'tests pass & lint is clean' 'speedup > 2x' 'make test && everything is clean' 'make test; the report has no errors' 'make test | nothingtoread' 'make test || nothing < in.txt'
  'echo $(nothingtorun)' '(cd tests && nothingtorun)' '! nothingtorun' 'if nothingtorun; then true; fi' 'FOO=1 nothingtorun 2>&1' 'tests/never_made.sh && true')
type -P coverage >/dev/null || prose+=('coverage > 80%')
for d in "${prose[@]}"; do
  n=$((n+1)); before=$(runs); out=$($Q local prepare --repo "$R" --base main --scratch "$T" --slug "d$n" --task-file "$T/task.txt" --done "$d" --scope tests/new_test.sh 2>&1); rc=$?
  if [ $rc = 2 ] && [ "$(runs)" = "$before" ]; then ok "DONE '$d' is refused (usage error), and no run is made"; else no "DONE '$d': rc=$rc $out"; fi
done
# a script is looked up at BASE (the tip of the base branch), not in the lead's working tree: one that only the checkout has is refused, one that only BASE has is accepted
echo untracked > "$R/tests/untracked.sh"
refuse "a script that exists in the checkout but not at BASE" "not an existing script" --slug u1 --task-file "$T/task.txt" --done './tests/untracked.sh'
git -C "$R" checkout -q -b withx && echo x > "$R/tests/atbase.sh" && git -C "$R" add tests/atbase.sh && git -C "$R" -c user.name=t -c user.email=t@example.net commit -q -m x && git -C "$R" checkout -q main
[ ! -e "$R/tests/atbase.sh" ] || no "setup: the checkout has the script"
out=$($Q local prepare --repo "$R" --base withx --scratch "$T" --slug u2 --task-file "$T/task.txt" --done './tests/atbase.sh' 2>&1); rc=$?
[ $rc = 0 ] && ok "a script that exists at BASE is accepted although the checkout is on another branch without it" || no "script at BASE: rc=$rc $out"
refuse "that script on another base" "not an existing script" --slug u3 --task-file "$T/task.txt" --done './tests/atbase.sh'
rm -f "$R/tests/untracked.sh"

# --- P3: a run prepared with --scope; review check fails a patch outside it and passes one inside
sc() { # NAME FILES...: a run with --scope lib/, a member series that changes the given files, its OUT
  local name=$1 f; shift
  prep --slug "$name" --task-file "$T/task.txt" --done 'bash tests/check.sh' --scope lib/ || { no "prepare $name"; return; }
  G=$RUN/git; C=$RUN/clone
  for f in "$@"; do mkdir -p "$C/$(dirname "$f")"; echo x > "$C/$f"; done
  "$G" -C "$C" add -A; "$G" -C "$C" commit -q -m "change the files" -m "The files change because the task says so."
  mkdir -p "$RUN/out/patches"; "$G" -C "$C" format-patch -q -o "$RUN/out/patches" "$BSHA..HEAD"
  "$G" -C "$C" log --format='%H%x09%s' "$BSHA..HEAD" | jq -R -s -c '[split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
    | {status:"DONE", commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})), patch_groups:[{name:"g", why:"one change", commits:($c|map(.sha))}]}' > "$RUN/out/manifest.json"
  echo "# series" > "$RUN/out/series.md"
}
sc inside lib/a.sh lib/sub/b.sh
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a patch inside the prepared SCOPE passes review check" || no "inside: rc=$rc $out"
sc outside lib/a.sh docs/other.md
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q 'outside SCOPE (lib/): docs/other.md' <<<"$out" && ok "a patch that touches another path fails review check, the path named" || no "outside: rc=$rc $out"
jq '.scope = ["lib/", "docs/"]' "$RUN/out/manifest.json" > "$RUN/out/m.json" && mv "$RUN/out/m.json" "$RUN/out/manifest.json"
$Q review check "$RUN/out" 2>&1 | grep -q 'outside SCOPE' && ok "the member's own scope[] does not widen the prepared SCOPE" || no "scope[] widened the limit"

# --- the DONE of the task block is the check the lead set: review check fails a manifest whose done.command is another command (a missing one is a warning)
sc doneok lib/a.sh
out=$($Q review check "$RUN/out" 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'WARN manifest has no done.command; the DONE of the task block is `bash tests/check.sh`' <<<"$out"; } && ok "a manifest with no done.command passes review check with a warning that names the DONE" || no "no done: rc=$rc $out"
jq '.done = {command: "bash tests/check.sh", exit_code: 0}' "$RUN/out/manifest.json" > "$RUN/out/m.json" && mv "$RUN/out/m.json" "$RUN/out/manifest.json"
out=$($Q review check "$RUN/out" 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q 'done.command' <<<"$out"; } && ok "a manifest whose done.command is the DONE of the task block passes, with no warning" || no "same done: rc=$rc $out"
jq '.done.command = "make test"' "$RUN/out/manifest.json" > "$RUN/out/m.json" && mv "$RUN/out/m.json" "$RUN/out/manifest.json"
out=$($Q review check "$RUN/out" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'FAIL the manifest.s done.command (`make test`) is not the DONE of the task block (`bash tests/check.sh`)' <<<"$out"; } && ok "a manifest whose done.command is another command fails review check, both commands named" || no "other done: rc=$rc $out"
# a task text with a line of its own that starts DONE: is not mistaken for the DONE of the block
printf 'Fix the thing.\nDONE: not the check\n\nMore text.\n' > "$T/task-done.txt"
prep --slug donetext --task-file "$T/task-done.txt" --done 'bash tests/check.sh' --scope lib/ || no "prepare donetext"
mkdir -p "$RUN/out/patches"; G=$RUN/git; C=$RUN/clone; mkdir -p "$C/lib"; echo x > "$C/lib/a.sh"; "$G" -C "$C" add -A; "$G" -C "$C" commit -q -m "change a file" -m "The file changes because the task says so."
"$G" -C "$C" format-patch -q -o "$RUN/out/patches" "$BSHA..HEAD"; echo "# series" > "$RUN/out/series.md"
"$G" -C "$C" log --format='%H%x09%s' "$BSHA..HEAD" | jq -R -s -c '[split("\n")[] | select(length>0) | split("\t") | {sha:.[0], subject:.[1]}] as $c
  | {status:"DONE", done:{command:"bash tests/check.sh", exit_code:0}, commits:$c, commit_advice:($c|map(. + {why_separate:"x", depends_on:[], builds_alone:true})), patch_groups:[{name:"g", why:"one change", commits:($c|map(.sha))}]}' > "$RUN/out/manifest.json"
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "a DONE: line in the task text does not stand for the DONE of the block" || no "done in task text: rc=$rc $out"
# a run that returns no commits is held to the same command
printf '%s\n' '{"status":"BLOCKED","blocked_reason":"no","commits":[],"done":{"command":"make test"}}' > "$RUN/out/manifest.json"; rm -rf "$RUN/out/patches"
out=$($Q review check "$RUN/out" 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q 'is not the DONE of the task block' <<<"$out"; } && ok "a BLOCKED manifest with no commits is held to the DONE of the task block too" || no "blocked other done: rc=$rc $out"
printf '%s\n' '{"status":"BLOCKED","blocked_reason":"no","commits":[],"done":{"command":"bash tests/check.sh"}}' > "$RUN/out/manifest.json"
out=$($Q review check "$RUN/out" 2>&1); rc=$?
[ "$rc" = 0 ] && ok "and passes with the same command" || no "blocked same done: rc=$rc $out"

# --- the skills tell the lead to use the flags and to hand the member RUN/task.md, not to assemble a block
grep -q -- '--task-file' skills/qargi-task/SKILL.md && grep -q -- '--done' skills/qargi-task/SKILL.md && ok "qargi-task has the lead call prepare with --task-file and --done" || no "qargi-task does not name the flags"
grep -q 'RUN/task.md' skills/qargi-task/SKILL.md && ! grep -q 'ROLE_TEXT\|paste them into the task block' skills/qargi-task/SKILL.md && ok "qargi-task hands the member RUN/task.md; the hand assembly text is gone" || no "qargi-task still describes a hand-assembled block"
grep -q 'RUN_DIR/task.md' skills/qargi-verify/SKILL.md && ok "qargi-verify compares the manifest and the DONE check with RUN_DIR/task.md" || no "qargi-verify does not name task.md"
# the DONE the qargi-flow skill gives the advisor is a command prepare accepts (it was a sentence, which prepare refuses)
fd=$(sed -n "s/.*--done '\([^']*\)'.*/\1/p" skills/qargi-flow/SKILL.md | head -1)
[ -n "$fd" ] && PATH=$PWD/bin:$PATH prep --slug flowdone --task-file "$T/task.txt" --done "$fd" >/dev/null 2>&1 && grep -qxF "DONE: $fd" "$RUN/task.md" && ok "the DONE of the advisor sign-off in qargi-flow ('$fd') is accepted by prepare" || no "the advisor DONE of qargi-flow ('$fd') is not a command prepare accepts"

exit $fail
