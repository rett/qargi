#!/usr/bin/env bash
# The tests' temporary directory can disappear while they run: logind removes every file of the user in /dev/shm when the user's
# last session ends (RemoveIPC, on by default), and a member's TMPDIR lives there. A test must then stop, not go on with an empty
# T=$(mktemp -d) or w=$(mktemp -d "$T/w.XXXXXX") and run git in the checkout it was started from. tests/hermetic.sh stops a shell
# test whose mktemp fails and refuses a TMPDIR that is not a writable directory; tests/hermetic.py refuses that TMPDIR too. A test
# that runs normally leaves its TMPDIR and what lies beside it alone.
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

[ $fail = 0 ] && echo "hermetic: all passed"
exit $fail
