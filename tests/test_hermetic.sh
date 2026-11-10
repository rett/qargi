#!/usr/bin/env bash
# The tests' temporary directory can disappear while they run: logind removes every file of the user in /dev/shm when the user's
# last session ends (RemoveIPC, on by default), and a member's TMPDIR lives there. A test must then stop, not go on with an empty
# T=$(mktemp -d) or w=$(mktemp -d "$T/w.XXXXXX") and run git in the checkout it was started from. tests/hermetic.sh stops a shell
# test whose mktemp fails and refuses a TMPDIR that is not a writable directory; tests/hermetic.py refuses that TMPDIR too. A test
# that runs normally leaves its TMPDIR and what lies beside it alone.
# The same file holds the other checks of a hermetic suite: the environment hermetic.sh and hermetic.py build, spawn_bg and kill_bg, and the
# lint (tests/hermetic_lint.py) that fails when a test file does not source tests/hermetic.sh (or import hermetic), names a literal /tmp,
# /dev/shm or /run path, kills by pattern (pkill, killall, pgrep -f), waits with a bare sleep outside a poll loop, removes a directory it
# did not make, binds a fixed TCP port, keeps a lock or socket outside its directory, compares a wall-clock difference with a constant, or
# asserts that a short token (under six characters, not a whole word or anchored) is absent from output that holds a random temporary path.
# A justified case carries `hermetic: allow RULE (reason)` on its line or the line above.
# Run: tests/test_hermetic.sh
set -u
cd "$(dirname "$0")/.." || exit 1
SRC=$PWD
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }

# a probe test: sources hermetic.sh, makes T, (wipe) removes its TMPDIR as logind would, then does what test_flow.sh does with a
# worktree directory: git -C "$w", which with an empty w runs in the current directory (the checkout)
cat > "$T/probe.sh" <<EOF
#!/usr/bin/env bash
set -u
. "$SRC/tests/hermetic.sh"
T=\$(mktemp -d)
trap 'rm -rf "\$T" "\$HERMETIC"; : > "$T/trap-ran"' EXIT
[ "\${1:-}" != wipe ] || rm -rf "\$TMPDIR"
w=\$(mktemp -d "\$T/w.XXXXXX")
git -C "\$w" init -q
: > "$T/went-on"
EOF
mkdir -p "$T/checkout"

# 1. a TMPDIR that is gone: the test does not run
rm -rf "$T/qargi-run.gone00"
out=$(cd "$T/checkout" && TMPDIR=$T/qargi-run.gone00 bash "$T/probe.sh" 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q 'TMPDIR=.*qargi-run.gone00 is not a writable directory' <<<"$out" && [ ! -e "$T/went-on" ] && [ ! -e "$T/checkout/.git" ] \
  && ok "a TMPDIR that does not exist: the test stops at once (exit 1) and writes nothing" || no "missing TMPDIR: rc=$rc $out"
rm -f "$T/trap-ran" "$T/went-on"

# 2. the TMPDIR is removed while the test runs: the next mktemp stops the test, its EXIT trap runs, git never runs in the checkout
mkdir -p "$T/qargi-run.wipe00"
out=$(cd "$T/checkout" && TMPDIR=$T/qargi-run.wipe00 bash "$T/probe.sh" wipe 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q 'hermetic test: mktemp .* failed' <<<"$out" && [ ! -e "$T/went-on" ] && [ ! -e "$T/checkout/.git" ] \
  && ok "TMPDIR removed under a running test: the failed mktemp stops it (exit $rc), nothing is done in the checkout" || no "wiped TMPDIR: rc=$rc went-on=$([ -e "$T/went-on" ] && echo yes) checkout-git=$([ -e "$T/checkout/.git" ] && echo yes) $out"
[ -e "$T/trap-ran" ] && ok "the stopped test's EXIT trap still runs (its cleanup)" || no "the EXIT trap did not run: $out"
rm -f "$T/trap-ran" "$T/went-on"

# 3. a normal run leaves its TMPDIR (named like a run's) and what lies beside it alone, and removes only what it made
mkdir -p "$T/qargi-run.keep00" "$T/qargi-run.other0"; : > "$T/qargi-run.keep00/precious"; : > "$T/qargi-run.other0/precious"
out=$(cd "$T/checkout" && TMPDIR=$T/qargi-run.keep00 bash "$T/probe.sh" 2>&1); rc=$?
left=$(find "$T/qargi-run.keep00" -mindepth 1 | sed "s|^$T/||" | sort | tr '\n' ' ')
[ "$rc" = 0 ] && [ -e "$T/went-on" ] && [ "$left" = "qargi-run.keep00/precious " ] && [ -f "$T/qargi-run.other0/precious" ] && [ ! -e "$T/checkout/.git" ] \
  && ok "a normal run: its TMPDIR and the directory beside it are untouched, its own directories are gone" || no "normal run: rc=$rc left=$left $out"

# 4. the Python tests: hermetic.py refuses a TMPDIR that is gone instead of falling back to /tmp
out=$(cd / && TMPDIR=$T/qargi-run.gone00 python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import hermetic' "$SRC/tests" 2>&1); rc=$?
[ "$rc" != 0 ] && grep -q 'TMPDIR=.*qargi-run.gone00 is not a writable directory' <<<"$out" && ok "hermetic.py: a TMPDIR that is gone stops the test" || no "hermetic.py missing TMPDIR: rc=$rc $out"
out=$(cd / && TMPDIR=$T/qargi-run.keep00 python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import hermetic; print(hermetic.ROOT)' "$SRC/tests" 2>&1); rc=$?
[ "$rc" = 0 ] && [ "${out#"$T"/qargi-run.keep00/}" != "$out" ] && ok "hermetic.py: a usable TMPDIR is where its directory goes" || no "hermetic.py TMPDIR: rc=$rc $out"


# 5. the environment of a hermetic shell test: one directory holds HOME, TMPDIR, config and state; git reads no host configuration; the
#    time zone, locale and umask are fixed; what the caller had in its environment does not get through
cat > "$T/env.sh" <<EOF
#!/usr/bin/env bash
set -u
. "$SRC/tests/hermetic.sh"
printf 'home=%s tmp=%s tz=%s lang=%s umask=%s gcg=%s nosys=%s branch=%s py=%s%s term=%s\n' "\$HOME" "\$TMPDIR" "\$TZ" "\$LANG" "\$(umask)" \
  "\$GIT_CONFIG_GLOBAL" "\$GIT_CONFIG_NOSYSTEM" "\$(git config init.defaultBranch)" "\$PYTHONNOUSERSITE" "\$PYTHONDONTWRITEBYTECODE" "\$TERM"
printf 'leak=%s%s%s%s%s\n' "\${GIT_DIR-} " "\${SSH_AUTH_SOCK-} " "\${PYTHONPATH-} " "\${QARGI_PROJECT-}" "\${ANTHROPIC_API_KEY-}"
printf 'root=%s\n' "\$HERMETIC"
EOF
mkdir -p "$T/outer"
out=$(cd "$T/outer" && env TMPDIR="$T/outer" GIT_DIR=/nowhere SSH_AUTH_SOCK=/nowhere PYTHONPATH=/nowhere ANTHROPIC_API_KEY=k QARGI_PROJECT=leaky TZ=Asia/Tokyo LC_ALL=de_DE.UTF-8 bash "$T/env.sh" 2>&1)
root=$(sed -n 's/^root=//p' <<<"$out")
case $root in "$T"/outer/*) in_outer=1;; *) in_outer=;; esac
grep -q "^home=$root/home tmp=$root/tmp tz=UTC lang=C\.UTF-8 umask=0022 gcg=/dev/null nosys=1 branch=master py=11 term=dumb\$" <<<"$out" \
  && ok "the environment: HOME and TMPDIR under one directory, UTC, C.UTF-8, umask 022, git without host configuration, a default branch" || no "environment: $out"
grep -q '^leak= *$' <<<"$out" && ok "the environment: GIT_DIR, SSH_AUTH_SOCK, PYTHONPATH and the caller's ANTHROPIC_* do not get through" || no "leaks: $out"
[ -n "$in_outer" ] && [ ! -e "$root" ] && [ -z "$(ls -A "$T/outer")" ] && ok "the directory of the test is made in the caller's TMPDIR and gone when the test ends, which is left empty" || no "root $root: $(ls -A "$T/outer")"

# 6. the python tests have the same environment, and what tempfile makes goes into their directory
out=$(cd / && env TMPDIR="$T/outer" GIT_DIR=/nowhere PYTHONPATH=/nowhere TZ=Asia/Tokyo python3 -I -c '
import sys, os, tempfile
sys.path.insert(0, sys.argv[1]); import hermetic
d = tempfile.mkdtemp()
print(os.path.dirname(d) == os.path.join(hermetic.ROOT, "tmp"), os.environ["TZ"], os.environ["LANG"], oct(os.umask(0o022)), os.environ["GIT_CONFIG_GLOBAL"],
      "GIT_DIR" in os.environ, "PYTHONPATH" in os.environ, os.environ["PYTHONDONTWRITEBYTECODE"], os.environ["TERM"], os.environ["HOME"].startswith(hermetic.ROOT))' "$SRC/tests" 2>&1)
[ "$out" = "True UTC C.UTF-8 0o22 /dev/null False False 1 dumb True" ] && ok "hermetic.py: the same environment, and tempfile works in the test's own directory" || no "hermetic.py environment: $out"
[ -z "$(ls -A "$T/outer")" ] && ok "hermetic.py: nothing is left in the caller's TMPDIR" || no "hermetic.py left: $(ls -A "$T/outer")"

# 7. spawn_bg records the pid of a background process and kill_bg (the EXIT trap of hermetic.sh) kills it by pid
cat > "$T/bg.sh" <<EOF
#!/usr/bin/env bash
set -u
. "$SRC/tests/hermetic.sh"
spawn_bg sleep 300
echo "\$SPAWNED_PID" > "$T/bg.pid"
[ "\$(cat "\$HERMETIC/pids")" = "\$SPAWNED_PID" ] || exit 7
kill -0 "\$SPAWNED_PID" || exit 8
EOF
bash "$T/bg.sh"; rc=$?
pid=$(cat "$T/bg.pid" 2>/dev/null)
for _ in $(seq 1 50); do kill -0 "$pid" 2>/dev/null || break; sleep 0.1; done
[ "$rc" = 0 ] && [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null && ok "spawn_bg: the process it started is killed by pid when the test ends" || { no "spawn_bg: rc=$rc pid=$pid"; kill "$pid" 2>/dev/null; }

# 7b. python writes no bytecode into the source tree: python3 -I ignores PYTHONDONTWRITEBYTECODE, so the python3 first on PATH is a wrapper
#     that adds -B. A copy of bin/ and lib/ is run through qargi verbs that import lib modules (the help preamble); nothing may appear in it.
#     The control runs the same verb with the real python3 (the caller's PATH, the variable set as the suite sets it): it does write, so the
#     check can fail. python tests: the same in hermetic.py, started as tests/run.sh starts a step (PYTHONDONTWRITEBYTECODE=1, which lets the
#     python3 that imports hermetic.py skip its own bytecode; started by hand it writes tests/__pycache__, which git ignores).
copy_tool "$SRC" "$T/pyc" bin lib
find "$T/pyc" -name __pycache__ -prune -exec rm -rf {} +
"$T/pyc/bin/qargi" role list >/dev/null 2>&1; "$T/pyc/bin/qargi" project list >/dev/null 2>&1
n=$(find "$T/pyc" -name '*.pyc' | wc -l)
[ "$n" = 0 ] && [ "$(command -v python3)" = "$HERMETIC/bin/python3" ] && ok "no bytecode: running qargi verbs through the hermetic python3 writes no __pycache__" || no "bytecode: $n files, python3 is $(command -v python3): $(find "$T/pyc" -name '*.pyc' | head -3)"
PATH=${PATH#"$HERMETIC/bin:"} PYTHONDONTWRITEBYTECODE=1 "$T/pyc/bin/qargi" role list >/dev/null 2>&1
n=$(find "$T/pyc" -name '*.pyc' | wc -l)
[ "$n" -gt 0 ] && ok "no bytecode: the control (the real python3 with PYTHONDONTWRITEBYTECODE=1 under -I) does write, so the check can fail" || no "control wrote no bytecode: the check proves nothing"
rm -rf "$T/pyc"; copy_tool "$SRC" "$T/pyc" bin lib tests; find "$T/pyc" -name __pycache__ -prune -exec rm -rf {} +
out=$(cd / && env -i PATH="${PATH#"$HERMETIC/bin:"}" HOME="$T" PYTHONDONTWRITEBYTECODE=1 python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import hermetic, subprocess; subprocess.run(["python3", "-I", "-c", "import sys; sys.path.insert(0, sys.argv[2]); import help", "x", sys.argv[2]])' "$T/pyc/tests" "$T/pyc/lib" 2>&1)
[ "$(find "$T/pyc" -name '*.pyc' | wc -l)" = 0 ] && ok "no bytecode: a python test (hermetic.py) and what it starts with python3 -I write no __pycache__" || no "hermetic.py bytecode: $(find "$T/pyc" -name '*.pyc' | head -3) $out"

# 8. the lint: the tests pass it; every rule finds its sample, and a clean sample is left alone
lint=$(python3 -I tests/hermetic_lint.py tests 2>&1); rc=$?
[ "$rc" = 0 ] && [ -z "$lint" ] && ok "lint: no test file breaks a rule" || no "lint of the tests: $lint"
lint=$(python3 -I tests/hermetic_lint.py tests/fixtures/hermetic-lint 2>&1)
for want in test_nosource.sh:source test_py.py:source test_tmp.sh:tmp test_pgrep.sh:pgrep test_sleep.sh:sleep test_py.py:sleep test_rm.sh:rm \
            test_port.sh:port test_lock.sh:lock test_clock.sh:clock test_py.py:clock test_absent.sh:absent; do
  grep -q "^${want%%:*}:[0-9]*: ${want##*:}:" <<<"$lint" && ok "lint: ${want%%:*} breaks rule ${want##*:}" || no "lint misses ${want%%:*} / ${want##*:}: $lint"
done
[ "$(grep -c '^test_tmp.sh:' <<<"$lint")" = 3 ] && [ "$(grep -c '^test_pgrep.sh:' <<<"$lint")" = 3 ] && [ "$(grep -c '^test_rm.sh:' <<<"$lint")" = 3 ] \
  && ok "lint: each line of a sample is found (three shared places, three ways to kill by pattern, three directories not made by the test)" || no "lint: lines found: $lint"
[ "$(grep -c '^test_absent.sh:' <<<"$lint")" = 7 ] && ok "lint: each of the seven short absent tokens of a sample is found (! grep, && no, a count of 0, an empty capture, one alternative of a pattern)" || no "lint: absent lines found: $lint"
grep -q '^test_clean.sh\|^test_pyclean.py' <<<"$lint" && no "lint flags a clean sample: $(grep '^test_clean\|^test_pyclean' <<<"$lint")" \
  || ok "lint: a poll loop, an allowed line, a comment, a quoted command and a short token that is present, whole-word, anchored, hyphenated or long are not findings"

[ $fail = 0 ] && echo "hermetic: all passed"
exit $fail
