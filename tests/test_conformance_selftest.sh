#!/usr/bin/env bash
# The conformance suite (tests/conformance.sh) catches what it claims to catch: it passes the claude-code and claude-platform adapters,
# the command runtime codex and the broken fixture without a fault, and fails the fixture, naming the case, for each fault the fixture can
# be told to have; the command cases 11 to 14 fail on faulty copies of the codex definition and of its stub (one gives a read-only run the
# write class's writable .git).
# Run: tests/test_conformance_selftest.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
T=$(mktemp -d -p "$HERMETIC")
trap 'chmod 755 "$T/inst/zz-sentinel" 2>/dev/null || :; rm -rf "$HERMETIC"' EXIT
ROOT=$PWD
BROKEN=tests/providers/broken
tree_before=$(git status --porcelain --untracked-files=no tests lib 2>/dev/null; git diff tests lib 2>/dev/null | cksum)

# the validator: a good value passes, a bad one is named
V="python3 -I lib/conformance/validate.py"
echo '{"decision":"allow","reason":""}' | $V barrier-check response >/dev/null && ok "validator accepts a good barrier-check response" || no "validator rejects a good response"
e=$(echo '{"decision":"maybe","reason":1,"x":2}' | $V barrier-check response); rc=$?
{ [ $rc = 1 ] && grep -q 'decision' <<<"$e" && grep -q 'reason' <<<"$e" && grep -q 'additional property' <<<"$e"; } && ok "validator names an enum, a type and an extra property" || no "validator on a bad response: rc=$rc $e"
echo '{"error":"x"}' | $V resolve error >/dev/null && ok "validator accepts an error body" || no "validator rejects an error body"
echo '{"surface":"local","class":"write","tool_call":{"tool":"Bash"}}' | $V barrier-check request >/dev/null && no "validator accepts a tool call with neither command nor path" || ok "validator wants a command or a path in a tool call"
echo '{}' | $V nosuchverb response >/dev/null && no "validator accepts an unknown verb" || ok "validator refuses a verb the schema does not have"

# the harness on the real adapter and on the fixture without a fault; the faults run side by side. The fixture is two runtimes of schema 2,
# broken-local (the barrier and the member definition) and broken-cloud (the session verbs); each fault runs on the runtime that has the case.
conf() { bash tests/conformance.sh "$@"; }
for rt in claude-code claude-platform codex; do
  conf "$rt" > "$T/$rt.out" 2>&1; rc=$?
  { [ $rc = 0 ] && ! grep -q '^FAIL' "$T/$rt.out"; } && ok "$rt passes" || { no "$rt does not pass: rc=$rc"; sed 's/^/     /' "$T/$rt.out"; }
  if [ "$rt" = codex ]; then cs="11 12 13 14"; else cs="1 2 3 4 5 6 7 8 9 10"; fi
  for c in $cs; do
    grep -Eq "^(ok|skip) +\[$c\] " "$T/$rt.out" && : || no "$rt: no line for case $c"
  done
done
# the command runtime codex has no adapter and gets the command cases, the others the adapter cases only
grep -q '^skip \[-\] the adapter cases 1 to 10: codex has no adapter' "$T/codex.out" && ok "codex: the adapter cases are one skip (no adapter)" || no "codex: the adapter cases were not skipped"
for c in 11 12 13 14 15; do grep -Eq "^ok +\[$c\] " "$T/codex.out" || no "codex: case $c is not ok"; done
grep -Eq '^ok +\[12\] .*runs: write read-only; usage of [0-9]+ events' "$T/codex.out" && ok "codex: the stub ran once for each class and its usage was added up" || no "codex: case 12 did not run both classes with usage"
for rt in claude-code claude-platform; do grep -q '^skip \[-\] the command cases 11 to 15' "$T/$rt.out" || no "$rt: the command cases were not skipped"; done
# the local runtime holds the barrier, the cloud runtime builds the session body; each other case is a skip with its reason
grep -Eq '^ok +\[8\] ' "$T/claude-code.out" && ok "claude-code: the barrier corpus ran" || no "claude-code: the barrier corpus did not run"
grep -Eq '^ok +\[9\] ' "$T/claude-code.out" && ok "claude-code: the definition carries the barrier" || no "claude-code: case 9"
grep -Eq '^ok +\[10\] ' "$T/claude-platform.out" && ok "claude-platform: the session body carries no tools, skills or mcp_servers" || no "claude-platform: case 10"
grep -Eq '^ok +\[5\] ' "$T/claude-platform.out" && ok "claude-platform: a credential stays out of argv" || no "claude-platform: case 5"
grep -Eq '^skip +\[8\] ' "$T/claude-platform.out" && ok "claude-platform: no barrier corpus (the cloud has no read-only barrier)" || no "claude-platform: case 8 was not skipped"

declare -A WANT=([push]=8 [failopen]=8 [argv]=5 [unsupported]=3 [planmut]=4 [stoptwice]=6 [costunit]=7 [badshape]=1 [badmodel]=2 [nonote]=2 [nodef]=9 [none]=0 [nonecloud]=0)
declare -A RT=([push]=local [failopen]=local [argv]=cloud [unsupported]=cloud [planmut]=cloud [stoptwice]=cloud [costunit]=cloud [badshape]=local [badmodel]=local [nonote]=local [nodef]=local [none]=local [nonecloud]=cloud)
for f in "${!WANT[@]}"; do
  ( CONFORMANCE_BROKEN=${f%cloud} conf "broken-${RT[$f]}" --tool "$BROKEN" --stub "$BROKEN" > "$T/broken.$f.out" 2>&1; echo $? > "$T/broken.$f.rc" ) &
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

# case 10 on two faulty copies of the claude-platform adapter: a body that carries tools, and a request with tools that is let through
for f in body override; do
  mkdir -p "$T/m.$f"; cp -R lib agents "$T/m.$f/"; ad=$T/m.$f/lib/providers/claude-platform/adapter
  case $f in
    body) sed -i 's|^    body\["metadata"\] = meta or {}$|&; body["agent"]["tools"] = []|' "$ad";;
    override) sed -i 's|^    for k in FIXED_ON_THE_AGENT:$|    for k in ():|' "$ad";;
  esac
  cmp -s "$ad" lib/providers/claude-platform/adapter && no "the $f mutation did not change the adapter"
  conf claude-platform --tool "$T/m.$f" > "$T/m.$f.out" 2>&1; rc=$?
  # a body with an extra key also leaves the schema, so case 1 may fail with it; no other case may
  { [ $rc = 1 ] && grep -Eq '^FAIL +\[10\] ' "$T/m.$f.out" && [ "$(grep -E '^FAIL +\[' "$T/m.$f.out" | grep -Evc '^FAIL +\[(1|10)\] ')" = 0 ]; } && ok "a copy of the claude-platform adapter with the '$f' fault fails case 10" || { no "the '$f' fault is not caught by case 10 only: rc=$rc"; sed 's/^/     /' "$T/m.$f.out"; }
done

# the command cases 11 to 14 on faulty copies of the codex definition, of qargi local run (the tool tree copied, codex.json changed by a jq filter) and of its stub:
# each fault fails exactly the cases it names, with the line that says why
declare -A CXF=(
  [norogroup]='.dispatch.argv |= map(select(type != "object" or .class != "read-only"))'
  [twosandbox]='.dispatch.argv |= (.[:2] + ["--sandbox=danger-full-access"] + .[2:])'
  [nousage]='.dispatch.output.usage.select = {"/type": "no.such.event"}'
  [roinwrite]='.dispatch.argv |= (.[:2] + ["--sandbox", "read-only"] + .[2:])'
  [gitinro]='.dispatch.argv |= map(if type == "object" and .class == "read-only" then .then += ["--add-dir", "{clone}/.git"] else . end)'
)
declare -A CXWANT=([norogroup]='11 12 14 15' [twosandbox]='11' [nousage]='12' [roinwrite]='11 12' [gitinro]='11' [homewrite]='13' [nobaseline]='14' [nohide]='15')
declare -A CXWHY=([norogroup]='carries no arguments of its own' [twosandbox]='also sets --sandbox outside its read-only arguments'
  [nousage]='records no usage: dispatch.output.usage matches no line' [roinwrite]='the write run carries the arguments of the read-only class: --sandbox read-only'
  [gitinro]='a read-only run carries --add-dir /conformance/run/clone/.git of the write class'
  [homewrite]='the run changed a file of the caller.s home' [nobaseline]='the run.s configuration file home/.codex/config.toml is missing'
  [nohide]='write, run hidden: qargi local run exited 0, not 2 .refused.')
for f in "${!CXF[@]}"; do
  mkdir -p "$T/cx.$f"; cp -R lib agents "$T/cx.$f/"
  jq "${CXF[$f]}" lib/providers/codex.json > "$T/cx.$f/lib/providers/codex.json" || no "the codex mutation $f did not apply"
  cmp -s "$T/cx.$f/lib/providers/codex.json" lib/providers/codex.json && no "the codex mutation $f changed nothing"
done
# a qargi local run that drops the baseline of dispatch.run_config: a run with no tool pack gets no configuration file
mkdir -p "$T/cx.nobaseline"; cp -R lib agents "$T/cx.nobaseline/"
sed -i 's|^    base = rc.get("baseline") or None$|    base = None|' "$T/cx.nobaseline/lib/local_run.py"
cmp -s "$T/cx.nobaseline/lib/local_run.py" lib/local_run.py && no "the local run mutation nobaseline changed nothing"
# a qargi local run that does not ask whether the sandbox hides a run path: a run in the hidden place starts
mkdir -p "$T/cx.nohide"; cp -R lib agents "$T/cx.nohide/"
sed -i 's|^    if hidden:$|    if False:|' "$T/cx.nohide/lib/local_run.py"
cmp -s "$T/cx.nohide/lib/local_run.py" lib/local_run.py && no "the local run mutation nohide changed nothing"
# a stub that writes through the sign-in file the run home links in: the caller's own file changes
mkdir -p "$T/cxstub"; cp -R tests/providers/codex tests/providers/lib "$T/cxstub/"
mv "$T/cxstub/codex/stub" "$T/cxstub/codex/stub.real"
printf '#!/bin/sh\nprintf x >> "$CODEX_HOME/auth.json"\nexec "$(dirname "$0")/stub.real" "$@"\n' > "$T/cxstub/codex/stub"; chmod 755 "$T/cxstub/codex/stub"
for f in "${!CXWANT[@]}"; do
  if [ "$f" = homewrite ]; then args=(--stub "$T/cxstub/codex"); else args=(--tool "$T/cx.$f"); fi
  ( conf codex "${args[@]}" > "$T/cx.$f.out" 2>&1; echo $? > "$T/cx.$f.rc" ) &
done
wait
for f in "${!CXWANT[@]}"; do
  rc=$(cat "$T/cx.$f.rc"); want=${CXWANT[$f]}; failed=$(grep -Eo '^FAIL +\[[0-9]+\]' "$T/cx.$f.out" | tr -dc '0-9\n' | paste -sd' ' -)
  { [ "$rc" = 1 ] && [ "$failed" = "$want" ] && grep -Eq -- "^ +- .*${CXWHY[$f]}" "$T/cx.$f.out"; } && ok "codex fault '$f' fails case(s) $want and says why" \
    || { no "codex fault '$f' does not fail exactly case(s) $want: rc=$rc, failed: ${failed:-none}"; sed 's/^/     /' "$T/cx.$f.out"; }
done

# a copy of codex whose barrier claim has no date counts as having no barrier; the read-only runs of cases 12 and 14 still run, on a copy
# where the claim is dated, since what they check is what a run carries, not the claim
mkdir -p "$T/cx.undated"; cp -R lib agents "$T/cx.undated/"
jq '.capabilities.read_only_barrier.verified_on = null' lib/providers/codex.json > "$T/cx.undated/lib/providers/codex.json"
conf codex --tool "$T/cx.undated" > "$T/cx.undated.out" 2>&1; rc=$?
{ [ "$rc" = 0 ] && ! grep -q '^FAIL' "$T/cx.undated.out" && grep -Eq '^ok +\[12\] .*runs: write read-only;' "$T/cx.undated.out" \
  && grep -Eq '^ok +\[14\] .*runs: write read-only;' "$T/cx.undated.out"; } \
  && ok "codex with an undated barrier claim: both classes still run in cases 12 and 14" || { no "codex undated: rc=$rc"; sed 's/^/     /' "$T/cx.undated.out"; }

# a schema 2 definition whose models are inline (no catalog) is read the same way, and the effort rule is tried on its own models
mkdir -p "$T/inline"; cp -R lib agents "$T/inline/"
jq --slurpfile c lib/providers/catalogs/claude.json '.models = {pattern: $c[0].pattern, tiers: $c[0].tiers, effort: $c[0].effort}' \
  lib/providers/claude-platform.json > "$T/inline/lib/providers/claude-platform.json"
conf claude-platform --tool "$T/inline" > "$T/inline.out" 2>&1; rc=$?
{ [ $rc = 0 ] && ! grep -q '^FAIL' "$T/inline.out" && grep -q 'effort null rule on a changed copy' "$T/inline.out"; } && ok "a schema 2 definition with inline models passes, and the effort rule runs on its models" || { no "inline models: rc=$rc"; sed 's/^/     /' "$T/inline.out"; }

# An unreadable unrelated entry in an installed layout must never be copied.
if [ "$(id -u)" = 0 ]; then
  echo "skip: the sentinel check needs a non-root user"
else
  copy_tool "$ROOT" "$T/inst"
  mkdir "$T/inst/zz-sentinel" && echo x > "$T/inst/zz-sentinel/f" && chmod 000 "$T/inst/zz-sentinel" || no "(setup) sentinel"
  bash "$T/inst/lib/conformance/run.sh" codex --stub "$ROOT/tests/providers/codex" > "$T/inst.out" 2>&1; rc=$?
  chmod 755 "$T/inst/zz-sentinel"
  { [ "$rc" = 0 ] && ! grep -q '^FAIL' "$T/inst.out" && grep -Eq '^ok +\[12\] .*runs: write read-only' "$T/inst.out"; } \
    && ok "installed layout ignores an unrelated root entry" || { no "sentinel: rc=$rc"; sed 's/^/     /' "$T/inst.out"; }
fi

# an adapter that is null is a skip, not a failure; an unknown provider is a usage error
mkdir -p "$T/null/lib/providers/catalogs"; cp lib/providers/catalogs/claude.json "$T/null/lib/providers/catalogs/"
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
fake_runtime "$ROOT" "$T/null" nullp local '.adapter = null' 
o=$(conf nullp --tool "$T/null" 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q '^skip' <<<"$o" && grep -q 'no adapter' <<<"$o"; } && ok "a descriptor with adapter null is skipped with a message, exit 0" || no "null adapter: rc=$rc $o"
conf nosuchprovider >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown provider is a usage error (exit 2)" || no "unknown provider exit"
conf >/dev/null 2>&1; [ $? = 2 ] && ok "no provider is a usage error (exit 2)" || no "no provider exit"

# hermetic: the caller's environment does not reach it, and it leaves nothing behind
mkdir "$T/tmp"
TMPDIR=$T/tmp QARGI_CONF=/nonexistent QARGI_STATE=/nonexistent QARGI_TRANSPORT=/bin/false ANTHROPIC_API_KEY=x conf claude-platform >/dev/null 2>&1 \
  && TMPDIR=$T/tmp QARGI_CONF=/nonexistent QARGI_STATE=/nonexistent QARGI_TRANSPORT=/bin/false ANTHROPIC_API_KEY=x conf claude-code >/dev/null 2>&1 \
  && TMPDIR=$T/tmp QARGI_CONF=/nonexistent QARGI_STATE=/nonexistent QARGI_TRANSPORT=/bin/false OPENAI_API_KEY=x conf codex >/dev/null 2>&1 && ok "a polluted caller environment does not change the result" || no "pollution changed the result"
[ -z "$(ls -A "$T/tmp")" ] && ok "the harness removes its temporary files" || no "temporary files left behind: $(ls "$T/tmp")"
cd "$ROOT" || exit 1
tree_after=$(git status --porcelain --untracked-files=no tests lib 2>/dev/null; git diff tests lib 2>/dev/null | cksum)
[ "$tree_before" = "$tree_after" ] && ok "the run changes no tracked file" || no "a tracked file changed"
[ $fail = 0 ] && echo "conformance selftest: all checks passed"
exit $fail
