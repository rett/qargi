#!/usr/bin/env bash
# The conformance suite (tests/conformance.sh) catches what it claims to catch: it passes the claude adapter and the
# broken fixture without a fault, and fails the fixture, naming the case, for each fault the fixture can be told to have.
# Run: tests/test_conformance_selftest.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
T=$(mktemp -d -p "$HERMETIC")
ROOT=$PWD
BROKEN=tests/providers/broken
tree_before=$(git status --porcelain --untracked-files=no tests lib 2>/dev/null; git diff tests lib 2>/dev/null | cksum)

# the validator: a good value passes, a bad one is named
V="python3 -I tests/providers/lib/validate.py"
echo '{"decision":"allow","reason":""}' | $V barrier-check response >/dev/null && ok "validator accepts a good barrier-check response" || no "validator rejects a good response"
e=$(echo '{"decision":"maybe","reason":1,"x":2}' | $V barrier-check response); rc=$?
{ [ $rc = 1 ] && grep -q 'decision' <<<"$e" && grep -q 'reason' <<<"$e" && grep -q 'additional property' <<<"$e"; } && ok "validator names an enum, a type and an extra property" || no "validator on a bad response: rc=$rc $e"
echo '{"error":"x"}' | $V resolve error >/dev/null && ok "validator accepts an error body" || no "validator rejects an error body"
echo '{"surface":"local","class":"write","tool_call":{"tool":"Bash"}}' | $V barrier-check request >/dev/null && no "validator accepts a tool call with neither command nor path" || ok "validator wants a command or a path in a tool call"
echo '{}' | $V nosuchverb response >/dev/null && no "validator accepts an unknown verb" || ok "validator refuses a verb the schema does not have"

# the harness on the real adapter and on the fixture without a fault; the faults run side by side
conf() { bash tests/conformance.sh "$@"; }
conf claude > "$T/claude.out" 2>&1; rc=$?
{ [ $rc = 0 ] && ! grep -q '^FAIL' "$T/claude.out"; } && ok "claude passes" || { no "claude does not pass: rc=$rc"; sed 's/^/     /' "$T/claude.out"; }
for c in 1 2 3 4 5 6 7 8 9; do
  grep -Eq "^(ok|skip) +\[$c\] " "$T/claude.out" && : || no "claude: no line for case $c"
done
grep -Eq '^ok +\[8\] ' "$T/claude.out" && ok "claude: the barrier corpus ran" || no "claude: the barrier corpus did not run"
grep -Eq '^ok +\[9\] ' "$T/claude.out" && ok "claude: the definition carries the barrier" || no "claude: case 9"

declare -A WANT=([push]=8 [failopen]=8 [argv]=5 [unsupported]=3 [planmut]=4 [stoptwice]=6 [costunit]=7 [badshape]=1 [badmodel]=2 [nonote]=2 [nodef]=9 [none]=0)
for f in "${!WANT[@]}"; do
  ( CONFORMANCE_BROKEN=$f conf broken --tool "$BROKEN" > "$T/broken.$f.out" 2>&1; echo $? > "$T/broken.$f.rc" ) &
done
wait
for f in "${!WANT[@]}"; do
  rc=$(cat "$T/broken.$f.rc"); want=${WANT[$f]}
  if [ "$want" = 0 ]; then
    { [ "$rc" = 0 ] && ! grep -q '^FAIL' "$T/broken.$f.out"; } && ok "the fixture without a fault passes (so a failure below is the fault's)" || { no "the fixture without a fault fails: rc=$rc"; sed 's/^/     /' "$T/broken.$f.out"; }
  else
    { [ "$rc" = 1 ] && grep -Eq "^FAIL +\[$want\] " "$T/broken.$f.out"; } && ok "fault '$f' fails case $want" || { no "fault '$f' does not fail case $want: rc=$rc"; sed 's/^/     /' "$T/broken.$f.out"; }
    # and only that case (a changed answer shape also fails the schema case 1 and what reads the answer, case 2)
    also=1; [ "$f" = badshape ] && also=1\|2
    others=$(grep -E '^FAIL +\[' "$T/broken.$f.out" | grep -Evc "^FAIL +\[($want|$also)\] ")
    [ "$others" = 0 ] || { no "fault '$f' fails cases other than $want"; grep -E '^FAIL' "$T/broken.$f.out" | sed 's/^/     /'; }
  fi
done
grep -q 'git push' "$T/broken.push.out" && ok "the push fault names the call it let through" || no "the push failure does not name the call"
{ grep -Eq '^FAIL +\[5\] ' "$T/broken.argv.out" && ! grep -q 'SENTINEL-credential' "$T/broken.argv.out"; } && ok "the report of the argv fault does not print the credential itself" || no "the report of the argv fault prints the credential"

# an adapter that is null is a skip, not a failure; an unknown provider is a usage error
mkdir -p "$T/null/lib/providers"
jq '.provider = "nullp" | .adapter = null' lib/providers/claude.json > "$T/null/lib/providers/nullp.json"
o=$(conf nullp --tool "$T/null" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q '^skip' <<<"$o" && grep -q 'no adapter' <<<"$o"; } && ok "a descriptor with adapter null is skipped with a message, exit 0" || no "null adapter: rc=$rc $o"
conf nosuchprovider >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown provider is a usage error (exit 2)" || no "unknown provider exit"
conf >/dev/null 2>&1; [ $? = 2 ] && ok "no provider is a usage error (exit 2)" || no "no provider exit"

# hermetic: the caller's environment does not reach it, and it leaves nothing behind
mkdir "$T/tmp"
TMPDIR=$T/tmp QARGI_CONF=/nonexistent QARGI_STATE=/nonexistent QARGI_TRANSPORT=/bin/false ANTHROPIC_API_KEY=x conf claude >/dev/null 2>&1 && ok "a polluted caller environment does not change the result" || no "pollution changed the result"
[ -z "$(ls -A "$T/tmp")" ] && ok "the harness removes its temporary files" || no "temporary files left behind: $(ls "$T/tmp")"
cd "$ROOT" || exit 1
tree_after=$(git status --porcelain --untracked-files=no tests lib 2>/dev/null; git diff tests lib 2>/dev/null | cksum)
[ "$tree_before" = "$tree_after" ] && ok "the run changes no tracked file" || no "a tracked file changed"
[ $fail = 0 ] && echo "conformance selftest: all checks passed"
exit $fail
