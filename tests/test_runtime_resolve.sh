#!/usr/bin/env bash
# Which runtime a request is resolved in (the second task of the runtime-per-profile design): the order is the task's --runtime, then the runtime a
# profile names (profiles.NAME.runtime), then the project's own; the runtime must be enabled for the project (models.extra_runtimes.local); the
# profile is resolved in that runtime, its tier through the catalog and its effort through the levels of that runtime; qargi agent for and
# qargi agent models name the runtime when the project has extras, and say nothing new when it has none; a prepared request binds the runtime and
# keeps the digests it had for the project's own runtime. Hermetic and offline: a copy of the tool holds the fake runtimes (tests/fakeprov.sh).
# Run: tests/test_runtime_resolve.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
unset QARGI_PROJECT QARGI_LEAD_RUNTIME
mkdir -p "$HOME" "$T/c/projects" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
NX=$SRC/tests/fixtures/runtime-no-extras

# --- a project without extras: what the verbs answered before the design is on record (tests/fixtures/runtime-no-extras, recorded from the head
# before the change): agent for (the line and the JSON, in session and as a command), agent models, and the prepared request of a command run. The
# digests of the runtime, the catalog and the composition belong to the shipped definitions and are masked; the others are the ones that must not move.
nx_project() { # NAME FIXTURE: the stored answers of a fixture project, with a repository of its own
  mkdir -p "$T/repo-$1"; git init -q "$T/repo-$1"
  jq --arg p "$T/repo-$1" --arg n "$1" '.repo.path = $p | .project = $n' "$NX/$2.json" > "$T/c/projects/$1.json"
}
nx_agent() { # PROJECT: agent for (two roles, two profiles) and agent models, each with its exit status
  local r p
  for r in build review; do
    echo "--- agent for $r"; "$DA" agent for "$r" --project "$1" 2>&1; echo "exit $?"
    echo "--- agent for $r --json"; "$DA" agent for "$r" --project "$1" --json 2>&1; echo "exit $?"
  done
  for p in worker-fast reviewer-deep; do
    echo "--- agent for --profile $p"; "$DA" agent for "$([ "$p" = worker-fast ] && echo build || echo review)" --profile "$p" --project "$1" 2>&1; echo "exit $?"
  done
  echo "--- agent models"; "$DA" agent models --project "$1" 2>&1; echo "exit $?"
  echo "--- agent models --json"; "$DA" agent models --project "$1" --json 2>&1; echo "exit $?"
}
nx_request() { # PROJECT RUNTIME: the prepared request of a build and of a review run, the digests of the shipped definitions masked
  local pair
  for pair in build:write review:read-only; do
    echo "--- request ${pair%%:*}"
    python3 -I "$TOOL/lib/prepared_request.py" "$1" "$2" "${pair%%:*}" "${pair##*:}" 2>&1 | jq -S '.binding |= (.runtime = "-" | .catalog = "-" | .composition = "-")' 2>&1
  done
}
nx_project nxsession project
nx_project nxcommand project-command
"$DA" agent add worker --roles build,write,test --project nxsession >/dev/null 2>&1
"$DA" agent add reviewer --roles review --project nxsession >/dev/null 2>&1
if [ -n "${NX_RECORD:-}" ]; then    # the head before the change is run once with NX_RECORD=DIR, and the fixture is what it printed
  nx_agent nxsession > "$NX_RECORD/agent-session.golden"
  nx_agent nxcommand > "$NX_RECORD/agent-command.golden"
  nx_request nxcommand codex > "$NX_RECORD/request-command.golden"
  exit 0
fi
for pair in session:nxsession command:nxcommand; do
  out=$(nx_agent "${pair##*:}" 2>&1)
  [ "$out" = "$(cat "$NX/agent-${pair%%:*}.golden")" ] && echo "ok   no extras: agent for and agent models of the ${pair%%:*} fixture project are as recorded" \
    || { echo "FAIL no extras: agent for and agent models of the ${pair%%:*} fixture project changed:"; diff <(echo "$out") "$NX/agent-${pair%%:*}.golden" | head -10; fail=1; }
done
out=$(nx_request nxcommand codex 2>&1)
[ "$out" = "$(cat "$NX/request-command.golden")" ] && echo "ok   no extras: the prepared request of the command fixture project is as recorded" \
  || { echo "FAIL no extras: the prepared request changed:"; diff <(echo "$out") "$NX/request-command.golden" | head -10; fail=1; }

# --- the runtimes: the project's own, two extra ones that can be used and one that cannot (it is not started by a command)
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
fake_command_runtime "$SRC" "$TOOL" fakecx
fake_command_runtime "$SRC" "$TOOL" fakeown
fake_command_runtime "$SRC" "$TOOL" fakeins '.dispatch.mode = "in-session"'
for r in fakecx fakeown; do mkdir -p "$HOME/.$r-members"; echo '{}' > "$HOME/.$r-members/auth.json"; done
ok() { echo "ok $1"; }            # the named cases below print `ok NAME`

mkproj() { # NAME PROVIDER-JSON EXTRAS-JSON PROFILES-JSON: stored answers with a repository of their own (and a member of each base when the project's own runtime works in the session)
  local repo=$T/repo-$1
  mkdir -p "$repo"; git init -q "$repo"
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" --argjson ex "${3:-null}" --argjson pr "${4:-null}" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"}},review:{base:"main",push:{mode:"none"}}}, profiles:($pr // {}),
    models:({provider:$prov} + (if $ex == null then {} else {extra_runtimes:{local:$ex}} end)),memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
  if [ "$(jq -r .local <<<"$2")" = claude-code ]; then
    "$DA" agent add worker --roles build,write,test --project "$1" >/dev/null 2>&1
    "$DA" agent add reviewer --roles review --project "$1" >/dev/null 2>&1
  fi
}
CC='{"local":"claude-code","cloud":"claude-platform"}'
PROFILES='{"cx-build":{"base":"worker","tier":"balanced","effort":"high","runtime":"fakecx"},"cx-review":{"base":"reviewer","tier":"deep","runtime":"fakecx"},
  "cx-pin":{"base":"worker","model":"claude-haiku-5-5","runtime":"fakecx"},"gone":{"base":"worker","tier":"fast","runtime":"nosuch"},
  "pin-gpt":{"base":"worker","model":"gpt-6-luna"},"cc-fast":{"base":"worker","tier":"fast","effort":"low"},"cc-own":{"base":"worker","tier":"fast","runtime":"claude-code"},
  "unusable":{"base":"worker","tier":"fast","runtime":"fakeins"},"badname":{"base":"worker","tier":"fast","runtime":"Not A Name"}}'
mkproj two "$CC" '["fakecx","fakeins"]' "$PROFILES"
mkproj plain "$CC" null "$PROFILES"
mkproj cmdplain '{"local":"fakeown"}' null "$PROFILES"
AF() { "$DA" agent for "$@"; }
refusal_code() { sed -n 's/^qargi-refusal\/1 .*"code":"\([a-z-]*\)".*/\1/p' <<<"$1"; }

# --- the order: the task's --runtime, then the profile's runtime, then the project's own
out=$(AF build --project two 2>&1)
[ "$out" = "worker sonnet high build claude-code" ] && ok resolve-own-runtime || no "own runtime: $out"
out=$(AF build --project two --profile cx-build 2>&1)
[ "$out" = "worker gpt-6.1-terra high cx-build fakecx" ] && ok resolve-profile-runtime || no "profile runtime: $out"
out=$(AF build --project two --profile cx-build --runtime claude-code 2>&1)
[ "$out" = "worker sonnet high cx-build claude-code" ] && ok resolve-option-over-profile || no "option over profile: $out"
out=$(AF build --project two --runtime fakecx 2>&1)
[ "$out" = "worker gpt-6.1-terra high build fakecx" ] && ok resolve-option-over-own || no "option over own: $out"
out=$(AF review --project two --runtime fakecx 2>&1); out2=$(AF review --project two --profile cx-review 2>&1)
{ [ "$out" = "reviewer gpt-6.1-sol high review fakecx" ] && [ "$out2" = "reviewer gpt-6.1-sol medium cx-review fakecx" ]; } && ok resolve-read-only-role || no "review: $out | $out2"
# the profile is resolved in the runtime that serves it: the same tier is another model there, and the effort the profile names is kept
out=$(AF build --project two --profile cc-fast 2>&1); out2=$(AF build --project two --profile cc-fast --runtime fakecx 2>&1)
{ [ "$out" = "worker haiku low cc-fast claude-code" ] && [ "$out2" = "worker gpt-6-luna low cc-fast fakecx" ]; } && ok resolve-tier-in-runtime || no "tier in runtime: $out | $out2"
out=$(AF build --project two --profile cc-own 2>&1)
[ "$out" = "worker haiku medium cc-own claude-code" ] && ok resolve-profile-names-own || no "profile names the own runtime: $out"

# --- with extras every answer names its runtime: a fifth word, and a key of the JSON; `mode` stays where it was
out=$(AF build --project two --json 2>&1)
jq -e '.runtime == "claude-code" and (has("mode") | not) and .member == "worker" and .model == "sonnet"' <<<"$out" >/dev/null && ok resolve-json-runtime-insession || no "json in session: $out"
out=$(AF build --project two --profile cx-build --json 2>&1)
jq -e '.runtime == "fakecx" and .mode == "command" and .model_id == "gpt-6.1-terra"' <<<"$out" >/dev/null && ok resolve-json-runtime-command || no "json command: $out"
[ "$(jq -r 'keys_unsorted[-1]' <<<"$out")" = runtime ] && ok resolve-json-runtime-last || no "json order: $out"

# --- a project without extras sees no new word
out=$(AF build --project plain 2>&1); out2=$(AF build --project plain --json 2>&1)
{ [ "$out" = "worker sonnet high build" ] && ! jq -e 'has("runtime")' <<<"$out2" >/dev/null; } && ok resolve-no-extras-no-word || no "no extras: $out | $out2"
out=$(AF build --project plain --runtime claude-code 2>&1)
[ "$out" = "worker sonnet high build" ] && ok resolve-no-extras-own-runtime-option || no "no extras, own runtime: $out"
out=$(AF build --project plain --profile cc-own 2>&1)
[ "$out" = "worker haiku medium cc-own" ] && ok resolve-no-extras-profile-own-runtime || no "no extras, profile names own: $out"
out=$(AF build --project plain --runtime fakecx 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ] && grep -q 'refused \[runtime-not-enabled\] the runtime fakecx is not enabled for this project' <<<"$out"; } \
  && ok resolve-no-extras-not-enabled || no "no extras, --runtime: rc=$rc $out"
out=$(AF build --project plain --profile cx-build 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ]; } && ok resolve-no-extras-profile-not-enabled || no "no extras, profile runtime: rc=$rc $out"

# --- the runtime must be enabled, and an extra must still be usable
out=$(AF build --project two --runtime nosuch 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ] && grep -q '"detail":"name=nosuch"' <<<"$out"; } && ok resolve-not-enabled-option || no "not enabled, option: rc=$rc $out"
out=$(AF build --project two --profile gone 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ]; } && ok resolve-not-enabled-profile || no "not enabled, profile: rc=$rc $out"
out=$(AF build --project two --profile unusable 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-unusable ] && grep -q 'name=fakeins why=not-command' <<<"$out"; } && ok resolve-unusable || no "unusable: rc=$rc $out"
out=$(AF build --project two --profile badname 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'not a runtime name' <<<"$out"; } && ok resolve-profile-runtime-not-a-name || no "bad name in profile: rc=$rc $out"
for bad in 'Bad_Name' 'x y'; do
  AF build --project two --runtime "$bad" >"$T/o" 2>&1; rc=$?
  [ "$rc" = 2 ] || no "--runtime '$bad': rc=$rc $(cat "$T/o")"
done
ok resolve-option-not-a-name
AF build --project two --runtime fakecx --surface cloud >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && grep -q -- '--runtime is for the local surface' "$T/o"; } && ok resolve-option-not-for-cloud || no "cloud: rc=$rc $(cat "$T/o")"
"$DA" agent list --runtime fakecx >"$T/o" 2>&1; rc=$?
{ [ "$rc" = 2 ] && grep -q 'only qargi agent for takes it' "$T/o"; } && ok resolve-option-only-for || no "agent list --runtime: rc=$rc $(cat "$T/o")"

# --- a profile's own model belongs to the runtime it is resolved in
out=$(AF build --project two --profile cx-pin 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-profile-model ] && grep -q 'name=fakecx profile=cx-pin' <<<"$out"; } && ok resolve-profile-model-command || no "model in command runtime: rc=$rc $out"
out=$(AF build --project two --profile pin-gpt 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-profile-model ] && grep -q 'name=claude-code profile=pin-gpt' <<<"$out"; } && ok resolve-profile-model-insession || no "model in session: rc=$rc $out"
out=$(AF build --project two --profile pin-gpt --runtime fakecx 2>&1)
[ "$out" = "worker gpt-6-luna medium pin-gpt fakecx" ] && ok resolve-profile-model-offered || no "model offered: $out"
out=$(AF build --project plain --profile pin-gpt 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q 'qargi-refusal/1' <<<"$out"; } && ok resolve-no-extras-profile-model-as-before || no "no extras, a model in session: rc=$rc $out"
mkproj cmdpin '{"local":"fakeown"}' null '{"pin":{"base":"worker","model":"claude-haiku-5-5"}}'
out=$(AF build --project cmdpin --profile pin 2>&1); rc=$?
{ [ "$rc" = 2 ] && ! grep -q 'qargi-refusal/1' <<<"$out" && grep -q 'the pin profile is refused on fakeown: model claude-haiku-5-5 is not in the catalog of fakeown' <<<"$out"; } \
  && ok resolve-no-extras-profile-model-message-kept || no "no extras, a model of a command runtime: rc=$rc $out"

# --- a project whose own runtime is a command runtime: the same order, the answer names the own runtime
out=$(AF build --project cmdplain 2>&1)
[ "$out" = "worker gpt-6.1-terra high build" ] && ok resolve-command-own-no-extras || no "command own, no extras: $out"
mkproj cmdtwo '{"local":"fakeown"}' '["fakecx"]' "$PROFILES"
out=$(AF build --project cmdtwo 2>&1); out2=$(AF build --project cmdtwo --profile cx-build --runtime fakeown 2>&1); out3=$(AF build --project cmdtwo --profile cx-build 2>&1)
{ [ "$out" = "worker gpt-6.1-terra high build fakeown" ] && [ "$out2" = "worker gpt-6.1-terra high cx-build fakeown" ] && [ "$out3" = "worker gpt-6.1-terra high cx-build fakecx" ]; } \
  && ok resolve-command-own-with-extras || no "command own, extras: $out | $out2 | $out3"

# --- agent models: a RUNTIME column and each profile resolved in its own runtime, on the same condition
out=$("$DA" agent models --project two 2>&1)
{ grep -q "^runtimes: claude-code (the project's own), fakecx, fakeins\$" <<<"$out" \
  && grep -E '^ *build ' <<<"$out" | grep -q 'claude-code *balanced -> sonnet -> claude-sonnet-5-5' \
  && grep -E '^ *cx-build ' <<<"$out" | grep -q 'fakecx *gpt-6.1-terra/high' \
  && grep -E '^ *cx-review ' <<<"$out" | grep -q 'fakecx *gpt-6.1-sol/medium' \
  && grep -E '^ *cx-pin ' <<<"$out" | grep -q 'fakecx .*! refused: .*model claude-haiku-5-5 is not in the catalog of fakecx' \
  && grep -E '^ *gone ' <<<"$out" | grep -q 'nosuch .*! refused: the runtime nosuch is not enabled for this project' \
  && grep -E '^ *unusable ' <<<"$out" | grep -q 'fakeins .*! refused: the runtime fakeins cannot be used' \
  && grep -E '^ *pin-gpt ' <<<"$out" | grep -q 'claude-code .*! refused: .*model gpt-6-luna is not in the catalog of claude-code' \
  && grep -E '^ *worker ' <<<"$out" | grep -q 'claude-sonnet-5-5/high'; } && ok models-runtime-column || no "models text: $out"
out=$("$DA" agent models --project two --json 2>&1)
jq -e '.runtimes == {primary: "claude-code", extra: ["fakecx", "fakeins"]} and .profiles["cx-build"].runtime == "fakecx" and .profiles["cx-build"].selected == "gpt-6.1-terra" and .profiles["cx-build"].mode == "command"
  and .profiles.build.runtime == "claude-code" and .profiles.build.model == "sonnet" and .profiles.gone.runtime == "nosuch" and (.profiles.gone.refused | test("not enabled"))
  and ([.warnings[] | select(.kind == "profile" and .name == "cx-pin")] | length == 1) and (.members | length == 2) and ([.profiles[] | .runtime] | all(type == "string"))' <<<"$out" >/dev/null \
  && ok models-json-runtime || no "models json: $out"
out=$("$DA" agent models --project cmdtwo 2>&1)
{ grep -q "^runtimes: fakeown (the project's own), fakecx\$" <<<"$out" && grep -E '^ *build ' <<<"$out" | grep -q 'fakeown *gpt-6.1-terra/high' && ! grep -q '^members' <<<"$out"; } \
  && ok models-command-own-with-extras || no "models, command own: $out"
out=$("$DA" agent models --project plain 2>&1)
{ ! grep -q 'runtime' <<<"$out" && ! "$DA" agent models --project plain --json | jq -e 'has("runtimes") or ([.profiles[] | has("runtime")] | any)' >/dev/null; } && ok models-no-extras-no-column || no "models, no extras: $out"

exit $fail
