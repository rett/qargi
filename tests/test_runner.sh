#!/usr/bin/env bash
# tests/run.sh and tests/suite.txt: the manifest and its inventory check, --only, --tier, --shard, --changed-files/--changed-from, --plan, --shuffle, --repeat, -j (the
# same verdict at -j 1 and -j 4), the timeout, a process left running, the budget warning and --enforce-budgets, the usage
# errors. The runner is run on a scratch copy with small steps of its own, and once on the real manifest to prove its inventory.
# Run: tests/test_runner.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh

# the real manifest: every test file is listed, every listed file exists (--only with nothing matching runs no step)
out=$(bash tests/run.sh --only '^no step has this command$' 2>&1); rc=$?
[ "$rc" = 0 ] && ok "the real inventory is complete: every tests/test_* is in tests/suite.txt and every listed file exists" || no "real inventory: rc=$rc $out"
grep -q '^total: [0-9]*s (passed)$' <<<"$out" && ok "and the last line is the total" || no "total line: $out"

# a scratch copy: tests/run.sh with steps of its own
S=$T/s; mkdir -p "$S/tests"; cp tests/run.sh "$S/tests/run.sh"
for n in a1 a2 a3 a4 a5 a6; do printf '#!/bin/sh\necho "ok   step %s"\n' "$n" > "$S/tests/test_$n.sh"; done
printf '#!/bin/sh\necho "FAIL boom"\necho "kept on stderr" >&2\nexit 1\n' > "$S/tests/test_bad.sh"
base() {
  cat <<'EOF'
# scratch manifest
serial | serial | 60 | 2 | sh tests/test_a6.sh
fast | par | 60 | 9 | sh tests/test_a1.sh | lib/a.sh
fast | par | 60 | 8 | sh tests/test_a2.sh
full | par | 60 | 7 | sh tests/test_a3.sh
fast | par | 60 | 3 | sh tests/test_a4.sh
full | par | 60 | 2 | sh tests/test_a5.sh
fast | par | 60 | 5 | sh tests/test_bad.sh
EOF
}
base | sed 's/^serial | serial/full | serial/' > "$S/tests/suite.txt"
R() { (cd "$S" && bash tests/run.sh "$@" 2>&1); }
steps() { grep -E '^== ' <<<"$1" | grep -v '^== summary' | sed 's/^== //'; }

out=$(R -j 1); rc=$?
[ "$rc" = 1 ] && grep -q '^FAILED: sh tests/test_bad.sh$' <<<"$out" && grep -q '^total: [0-9]*s (FAILED)$' <<<"$out" && ok "a failing step: FAILED line, total line FAILED, exit 1" || no "failing: rc=$rc $out"
grep -q '^kept on stderr$' <<<"$out" && grep -q '^exit status 1, [1-9][0-9]* bytes of output$' <<<"$out" && ok "a failing step's block carries what it wrote to standard error, and its exit status" || no "stderr: $out"
grep -q '^FAIL boom$' <<<"$out" && grep -q '^   ([0-9]*s)$' <<<"$out" && ok "its FAIL line and its seconds are in its block" || no "block: $out"
[ "$(steps "$out" | tr '\n' ' ')" = "sh tests/test_a1.sh sh tests/test_a2.sh sh tests/test_a3.sh sh tests/test_a4.sh sh tests/test_a5.sh sh tests/test_bad.sh sh tests/test_a6.sh " ] \
  && ok "-j 1 runs the steps in the manifest's order (the serial step last)" || no "order: $(steps "$out" | tr '\n' ' ')"
grep -qE '^== summary: 7 of 7 steps; -j 1 \(nproc [0-9?]+, load .*\), tier all, only none, shard none, shuffle seed none, repeat 1$' <<<"$out" && ok "the summary records the mode, the load and nproc" || no "summary: $out"
grep -q '^slowest:$' <<<"$out" && grep -q '^failed steps (1):$' <<<"$out" && ok "the summary lists the failed steps and the slowest" || no "summary lists: $out"

j1=$(steps "$(R -j 1)" | sort | tr '\n' ' '); fl1=$(R -j 1 | grep '^FAILED' | sort | tr '\n' ' ')
j4=$(steps "$(R -j 4)" | sort | tr '\n' ' '); fl4=$(R -j 4 | grep '^FAILED' | sort | tr '\n' ' ')
[ "$j1" = "$j4" ] && [ "$fl1" = "$fl4" ] && ok "-j 4 runs the same steps and fails the same ones as -j 1" || no "j1/j4: $j1 // $j4 // $fl1 // $fl4"
o4=$(R -j 4); [ "$(steps "$o4" | tail -1)" = "sh tests/test_a6.sh" ] && ok "the serial step runs after the pool" || no "serial last: $(steps "$o4")"

out=$(R -j 2 --tier fast)
[ "$(steps "$out" | sort | tr '\n' ' ')" = "sh tests/test_a1.sh sh tests/test_a2.sh sh tests/test_a4.sh sh tests/test_bad.sh " ] && grep -q 'of 7 steps' <<<"$out" && ok "--tier fast runs the fast steps only" || no "tier: $(steps "$out")"
out=$(R -j 2 --only 'a[35]|test_a6'); [ "$(steps "$out" | head -2 | sort | tr '\n' ' ')" = "sh tests/test_a3.sh sh tests/test_a5.sh " ] && [ "$(steps "$out" | tail -1)" = "sh tests/test_a6.sh" ] && ok "--only runs the matching steps, the serial one last" || no "only: $(steps "$out")"
out=$(R --only 'a[1-2]' -j 1); [ "$(steps "$out" | tr '\n' ' ')" = "sh tests/test_a1.sh sh tests/test_a2.sh " ] && ok "--only with -j 1 keeps the manifest's order" || no "only j1: $(steps "$out")"

# shards: together the selection, apart from each other, balanced by the budgets
s1=$(steps "$(R -j 1 --shard 1/2)" | sort); s2=$(steps "$(R -j 1 --shard 2/2)" | sort); all=$(steps "$(R -j 1)" | sort)
[ "$(printf '%s\n%s\n' "$s1" "$s2" | sort)" = "$all" ] && [ -z "$(comm -12 <(echo "$s1") <(echo "$s2"))" ] && ok "--shard 1/2 and 2/2 together run every step, none twice" || no "shards: [$s1] [$s2] [$all]"
out=$(R -j 1 --shard 1/2)
grep -q '^shard plan (planned seconds): 1/2=[0-9]*s([0-9]* steps) 2/2=[0-9]*s([0-9]* steps)$' <<<"$out" && ok "the plan of every shard is printed" || no "plan: $out"
p=$(sed -n 's/^shard plan.* 1\/2=\([0-9]*\)s.* 2\/2=\([0-9]*\)s.*/\1 \2/p' <<<"$out"); set -- $p
d=$(( $1 > $2 ? $1 - $2 : $2 - $1 )); [ "$d" -le 9 ] && ok "and the two parts are balanced (planned $1 s and $2 s)" || no "balance: $p"
printf '4 sh tests/test_a2.sh\n1 sh tests/test_a1.sh\n' > "$T/durs"
out=$(R -j 1 --shard 1/2 --durations "$T/durs"); grep -q ' 1/2=[0-9]*s' <<<"$out" && ok "--durations is read (a step with no duration counts as its budget)" || no "durations: $out"
out=$(R -j 1 --save-durations "$T/saved" >/dev/null; cat "$T/saved"); [ "$(wc -l <<<"$out")" = 7 ] && grep -q '^[0-9]* sh tests/test_a1.sh$' <<<"$out" && ok "--save-durations writes seconds and command" || no "save: $out"

# --changed-files / --changed-from: the fast tier plus the steps whose covers globs match a changed file (or whose command names it);
# a step with no covers is not added by its globs; --plan prints the selection and runs nothing
cat > "$T/cov.txt" <<'XEOF'
fast | par | 60 | 1 | sh tests/test_a1.sh | lib/a.sh
full | par | 60 | 1 | sh tests/test_a2.sh | lib/b*.sh docs/*
full | par | 60 | 1 | sh tests/test_a3.sh | lib/c.sh
full | par | 60 | 1 | sh tests/test_a4.sh
full | par | 60 | 1 | sh tests/test_a5.sh
full | par | 60 | 1 | sh tests/test_a6.sh | lib/zzz
full | par | 60 | 1 | sh tests/test_bad.sh
XEOF
printf 'lib/bx.sh\nREADME.md\ntests/test_a5.sh\n' > "$T/changed"
plan() { (cd "$S" && bash tests/run.sh --manifest "$T/cov.txt" --plan "$@" 2>&1 | sed 's/^[0-9]* //' | sort | tr '\n' ' '); }
[ "$(plan --tier fast)" = "sh tests/test_a1.sh " ] && ok "--tier fast alone selects the fast steps" || no "fast plan: $(plan --tier fast)"
[ "$(plan --tier fast --changed-files "$T/changed")" = "sh tests/test_a1.sh sh tests/test_a2.sh sh tests/test_a5.sh " ] && ok "--changed-files adds a step by its covers glob (lib/b*.sh) and one whose command names the changed file, and not one without covers" || no "changed plan: $(plan --tier fast --changed-files "$T/changed")"
printf 'docs/x/y.md\n' > "$T/changed2"
[ "$(plan --tier fast --changed-files "$T/changed2")" = "sh tests/test_a1.sh sh tests/test_a2.sh " ] && ok "a glob's * crosses a directory (docs/*)" || no "glob: $(plan --tier fast --changed-files "$T/changed2")"
: > "$T/changed3"
[ "$(plan --tier fast --changed-files "$T/changed3")" = "sh tests/test_a1.sh " ] && ok "no changed file adds nothing" || no "empty: $(plan --tier fast --changed-files "$T/changed3")"
out=$(R -j 1 --tier fast --changed-files "$T/changed" --manifest "$T/cov.txt" --only 'test_a[25]'); grep -q '^== summary: 2 of 7 steps, 3 changed files;' <<<"$out" && grep -q '^== sh tests/test_a5.sh$' <<<"$out" && ok "a selected step runs, and the summary counts the changed files" || no "changed run: $out"
G=$T/g; mkdir -p "$G/tests"; cp tests/run.sh "$G/tests/"; cp "$S"/tests/test_a*.sh "$S/tests/test_bad.sh" "$G/tests/"; cp "$T/cov.txt" "$G/tests/suite.txt"
git -C "$G" init -q -b main && git -C "$G" add -A && git -C "$G" -c user.name=t -c user.email=t@example.invalid commit -q -m base && git -C "$G" tag base
mkdir -p "$G/lib"; echo x > "$G/lib/c.sh"; git -C "$G" add -A && git -C "$G" -c user.name=t -c user.email=t@example.invalid commit -q -m change
out=$(cd "$G" && bash tests/run.sh --tier fast --changed-from base --plan 2>&1 | sed 's/^[0-9]* //' | sort | tr '\n' ' ')
[ "$out" = "sh tests/test_a1.sh sh tests/test_a3.sh " ] && ok "--changed-from REF reads the files changed since REF from git" || no "changed-from: $out"
out=$(cd "$G" && bash tests/run.sh --tier fast --changed-from nosuchref --plan 2>&1); rc=$?
[ "$rc" = 2 ] && ok "--changed-from with an unknown revision is a usage error" || no "changed-from bad: rc=$rc $out"
out=$(R -j 1 --shard 1/2 --only 'test_a[12]\.sh'); grep -qE '^shard 1/2: planned [0-9]+s, the steps took [0-9]+s together$' <<<"$out" && ok "a shard's summary says what was planned and what the steps took" || no "shard line: $out"

# shuffle and repeat
a=$(steps "$(R -j 1 --shuffle 5)" | tr '\n' ' '); b=$(steps "$(R -j 1 --shuffle 5)" | tr '\n' ' '); c=$(steps "$(R -j 1 --shuffle 6)" | tr '\n' ' ')
[ "$a" = "$b" ] && [ "$a" != "$c" ] && ok "--shuffle SEED: the same seed, the same order; another seed, another" || no "shuffle: $a // $b // $c"
[ "$(awk '{print $NF}' <<<"$a")" = "tests/test_a6.sh" ] && ok "the serial step is still last when shuffled" || no "shuffle serial: $a"
grep -q 'shuffle seed 5,' <<<"$(R -j 1 --shuffle 5)" && ok "the seed is in the summary" || no "seed in summary"
out=$(R -j 1 --only 'a1|a6' --repeat 3)
[ "$(grep -c '^== sh tests/test_a1.sh' <<<"$out")" = 3 ] && grep -q '^== sh tests/test_a1.sh (run 3 of 3)$' <<<"$out" && [ "$(steps "$out" | tail -3 | grep -c 'test_a6\.sh')" = 3 ] && ok "--repeat 3 runs each step three times, the serial ones last" || no "repeat: $out"

# the processes of a step
printf '#!/bin/sh\nsleep 3211\n' > "$S/tests/test_hang.sh"
printf '#!/bin/sh\nsleep 3217 </dev/null >/dev/null 2>&1 &\necho $! > "%s/leak.pid"\nexit 0\n' "$S" > "$S/tests/test_leak.sh"
printf '#!/bin/sh\nsleep 3\necho slow done\n' > "$S/tests/test_slow.sh"
printf '#!/bin/sh\nread -r x; echo "stdin: [$x]"\nls /proc/self/fd | tr "\\n" " "; echo\n' > "$S/tests/test_env.sh"
for n in a1 a2 a3 a4 a5 a6 bad hang leak slow env; do
  case $n in hang) t=2;; *) t=60;; esac
  echo "full | par | $t | 1 | sh tests/test_$n.sh"
done > "$S/tests/suite.txt"
t=$SECONDS; out=$(R -j 4 --only 'hang|env'); took=$((SECONDS - t))
grep -q '^TIMEOUT: sh tests/test_hang.sh was stopped after 2s$' <<<"$out" && grep -q '^FAILED: sh tests/test_hang.sh$' <<<"$out" && grep -q '^log: .*qargi-suite-logs' <<<"$out" && ok "a step over its timeout is stopped, named TIMEOUT and FAILED, with its log path" || no "timeout: $out"
[ "$took" -le 12 ] && ok "and it was stopped on time (${took}s of a 30 s sleep)" || no "timeout took ${took}s"
grep -q '^stdin: \[\]$' <<<"$out" && ok "a step has no standard input" || no "stdin: $out"
grep -qE '^[0-9 ]*$' <<<"$(grep -A1 '^stdin' <<<"$out" | tail -1)" && [ "$(grep -A1 '^stdin' <<<"$out" | tail -1 | wc -w)" -le 4 ] && ok "and no open file but 0, 1, 2 (and the one ls reads with)" || no "fds: $(grep -A1 '^stdin' <<<"$out")"
out=$(R -j 2 --only 'leak'); if grep -q '^LEFT RUNNING after sh tests/test_leak.sh' <<<"$out" && grep -q 'sleep 3217' <<<"$out" && grep -q '^FAILED: sh tests/test_leak.sh$' <<<"$out"; then ok "a process left running by a step that passed fails it, and is killed"; else no "leak: $out"; fi
lp=$(cat "$S/leak.pid" 2>/dev/null); gone=no
for _ in $(seq 50); do { [ -n "$lp" ] && kill -0 "$lp" 2>/dev/null; } || { gone=yes; break; }; sleep 0.1; done   # hermetic: allow sleep (poll)
[ -n "$lp" ] && [ "$gone" = yes ] && ok "the leaked process is gone" || no "the leaked sleep (pid ${lp:-unknown}) is still running"

# budgets
out=$(R -j 2 --only slow); grep -q 'WARN over budget: [0-9]*s, budget 1s' <<<"$out" && grep -q 'over 1.5x their budget (warning)' <<<"$out" && ! grep -q '^FAILED' <<<"$out" && grep -q '(passed)$' <<<"$out" && ok "over 1.5x its budget: a warning, the run passes" || no "budget warn: $out"
out=$(R -j 2 --only slow --enforce-budgets); rc=$?; [ "$rc" = 1 ] && grep -q '^OVER BUDGET: ' <<<"$out" && grep -q '^FAILED: sh tests/test_slow.sh$' <<<"$out" && ok "--enforce-budgets fails it" || no "enforce: rc=$rc $out"

# the shared place: the top level of the suite's TMPDIR. A step that removes a directory there it did not make, or leaves a new one, is named
# with the directories in its block and in the summary, as a warning. A step runs with a TMPDIR of its own, not the suite's.
SIB=$TMPDIR/sibling; LEFT=$TMPDIR/leftover; mkdir "$SIB"
printf '#!/bin/sh\nrm -rf "%s"\nmkdir "%s"\necho "ok   dirs"\n' "$SIB" "$LEFT" > "$S/tests/test_dirs.sh"
printf '#!/bin/sh\n[ "$TMPDIR" != "%s" ] && [ -w "$TMPDIR" ] && echo "own tmpdir: ${TMPDIR##*/}"\n' "$TMPDIR" > "$S/tests/test_tmp.sh"
printf 'full | par | 60 | 1 | sh tests/test_dirs.sh\nfull | par | 60 | 1 | sh tests/test_tmp.sh\n' >> "$S/tests/suite.txt"
out=$(R -j 2 --only dirs); rc=$?
grep -q "^   WARN directories outside its own changed: removed $SIB, left $LEFT\$" <<<"$out" && grep -q "^directories outside a step's own changed (warning; the top level of $TMPDIR):\$" <<<"$out" \
  && grep -q "^  sh tests/test_dirs.sh: removed $SIB, left $LEFT\$" <<<"$out" && ok "a step that removes a directory it did not make at the top level of the suite's TMPDIR, or leaves one, is named with them in its block and in the summary" || no "dirs: $out"
[ "$rc" = 0 ] && ! grep -q '^FAILED' <<<"$out" && grep -q '(passed)$' <<<"$out" && [ ! -e "$SIB" ] && [ -d "$LEFT" ] && ok "it is a warning: the run passes (and the runner itself puts nothing back and removes nothing)" || no "dirs rc=$rc: $out"
out=$(R -j 2 --only 'tmp|a1'); rc=$?
[ "$rc" = 0 ] && grep -q '^own tmpdir: tmp-[0-9]*$' <<<"$out" && ! grep -q 'directories outside' <<<"$out" && ok "a step has a TMPDIR of its own under the runner's directory, and a step that changes nothing is not named" || no "own tmpdir rc=$rc: $out"
rmdir "$LEFT"; rm -f "$S/tests/test_dirs.sh" "$S/tests/test_tmp.sh"

# the inventory
printf 'full | par | 60 | 1 | sh tests/test_a1.sh\n' > "$S/tests/suite.txt"
out=$(R -j 2); rc=$?
[ "$rc" = 1 ] && grep -q '^tests/test_a2.sh is not listed in tests/suite.txt$' <<<"$out" && grep -q '^FAILED: inventory$' <<<"$out" && ok "a test file the manifest does not list fails the inventory" || no "unlisted: rc=$rc $out"
printf 'full | par | 60 | 1 | sh tests/test_a1.sh\nfull | par | 60 | 1 | sh tests/test_gone.sh\n' > "$S/tests/suite.txt"
for n in a2 a3 a4 a5 a6 bad hang leak slow env; do echo "full | par | 60 | 1 | sh tests/test_$n.sh" >> "$S/tests/suite.txt"; done
out=$(R -j 2 --only a1); rc=$?
[ "$rc" = 1 ] && grep -q 'lists tests/test_gone.sh, which does not exist' <<<"$out" && ok "a listed file that does not exist fails the inventory" || no "missing: rc=$rc $out"
# a rename of a listed test, in a copy of the real repository files
cp -r tests "$T/real-tests"; mkdir -p "$T/real"; mv "$T/real-tests" "$T/real/tests"
mv "$T/real/tests/test_role.sh" "$T/real/tests/test_roles.sh"
out=$(cd "$T/real" && bash tests/run.sh --only '^no step has this command$' 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q 'tests/test_roles.sh is not listed' <<<"$out" && grep -q 'lists tests/test_role.sh, which does not exist' <<<"$out" && grep -q '^FAILED: inventory$' <<<"$out" && ok "renaming a listed test in a copy of tests/ fails the inventory (both sides)" || no "rename: rc=$rc $out"
printf 'fast | par | 60 | 1 | sh tests/test_a1.sh\nfull | par | 60 | 1 | sh tests/test_a1.sh\n' > "$S/tests/suite.txt"
out=$(R -j 2 --only '^$'); grep -q "lists 'sh tests/test_a1.sh' twice" <<<"$out" && ok "a step listed twice fails the inventory" || no "twice: $out"
printf 'fast | maybe | 60 | 1 | sh tests/test_a1.sh\nfast | par | x | 1 | sh tests/test_a1.sh\nsoon | par | 60 | 1 | sh tests/test_a1.sh\n' > "$S/tests/suite.txt"
out=$(R -j 2 --only '^$'); [ "$(grep -c 'suite.txt:[0-9]*: ' <<<"$out")" = 3 ] && ok "a line with a bad tier, mode or number is named by line" || no "bad lines: $out"

# usage errors exit 2
for a in "-j 0" "-j x" "--tier slow" "--shard 3/2" "--shard x" "--repeat 0" "--shuffle x" "--bogus" "--only" "--manifest /nonexistent"; do
  # shellcheck disable=SC2086
  (cd "$S" && bash tests/run.sh $a >/dev/null 2>&1); rc=$?
  [ "$rc" = 2 ] && ok "usage error exits 2: $a" || no "usage $a: rc=$rc"
done
exit $fail
