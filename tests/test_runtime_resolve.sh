#!/usr/bin/env bash
# Which runtime a request is resolved in (the second task of the runtime-per-profile design): the order is the task's --runtime, then the runtime a
# profile names (profiles.NAME.runtime), then the project's own; the runtime must be enabled for the project (models.extra_runtimes.local); the
# profile is resolved in that runtime, its tier through the catalog and its effort through the levels of that runtime; qargi agent for and
# qargi agent models name the runtime when the project has extras, and say nothing new when it has none; a prepared request binds the runtime and
# keeps the digests it had for the project's own runtime. Hermetic and offline: a copy of the tool holds the fake runtimes (tests/fakeprov.sh).
# The commands of a group are started together (job) and read afterwards (res), so the step takes what its longest command takes.
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
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/jobs"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
NX=$SRC/tests/fixtures/runtime-no-extras

job() { # ID COMMAND...: run it in the background (eight at a time); its output (standard error too) and exit status are read with res and rc_of
  local id=$1; shift
  [ "$(jobs -rp | wc -l)" -lt 8 ] || wait -n
  ( "$@" > "$T/jobs/$id.out" 2>&1; echo $? > "$T/jobs/$id.rc" ) &
}
res() { cat "$T/jobs/$1.out"; }
rc_of() { cat "$T/jobs/$1.rc"; }
AFJ() { local id=$1; shift; job "$id" "$DA" agent for "$@"; }          # AFJ ID ROLE ARGS...
AMJ() { local id=$1; shift; job "$id" "$DA" agent models "$@"; }       # AMJ ID ARGS...
PRQ() { python3 -I "$TOOL/lib/prepared_request.py" "$@"; }
PRQJ() { local id=$1; shift; job "$id" PRQ "$@"; }                     # PRQJ ID PROJECT RUNTIME ROLE CLASS [PROFILE]

# --- a project without extras: what the verbs answered before the design is on record (tests/fixtures/runtime-no-extras, recorded from the head
# before the change): agent for (the line and the JSON, in session and as a command), agent models, and the prepared request of a command run. The
# digests of the runtime, the catalog and the composition belong to the shipped definitions and are masked; the others are the ones that must not move.
nx_project() { # NAME FIXTURE: the stored answers of a fixture project, with a repository of its own
  mkdir -p "$T/repo-$1"; git init -q "$T/repo-$1"
  jq --arg p "$T/repo-$1" --arg n "$1" '.repo.path = $p | .project = $n' "$NX/$2.json" > "$T/c/projects/$1.json"
}
nx_launch() { # PREFIX PROJECT: agent for (two roles, two profiles) and agent models, started together
  AFJ "$1-1" build --project "$2"; AFJ "$1-2" build --project "$2" --json
  AFJ "$1-3" review --project "$2"; AFJ "$1-4" review --project "$2" --json
  AFJ "$1-5" build --profile worker-fast --project "$2"; AFJ "$1-6" review --profile reviewer-deep --project "$2"
  AMJ "$1-7" --project "$2"; AMJ "$1-8" --project "$2" --json
}
nx_collect() { # PREFIX: what nx_launch started, each with the exit status of its command
  local i label
  i=0
  for label in "agent for build" "agent for build --json" "agent for review" "agent for review --json" "agent for --profile worker-fast" "agent for --profile reviewer-deep" \
               "agent models" "agent models --json"; do
    i=$((i + 1)); echo "--- $label"; res "$1-$i"; echo "exit $(rc_of "$1-$i")"
  done
}
nx_request() { # PROJECT RUNTIME: the prepared request of a build and of a review run, the digests of the shipped definitions masked
  local pair
  for pair in build:write review:read-only; do
    echo "--- request ${pair%%:*}"
    PRQ "$1" "$2" "${pair%%:*}" "${pair##*:}" 2>&1 | jq -S '.binding |= (.runtime = "-" | .catalog = "-" | .composition = "-")' 2>&1
  done
}
nx_project nxsession project
nx_project nxcommand project-command
"$DA" agent add worker --roles build,write,test --project nxsession >/dev/null 2>&1
"$DA" agent add reviewer --roles review --project nxsession >/dev/null 2>&1
if [ -n "${NX_RECORD:-}" ]; then    # the head before the change is run once with NX_RECORD=DIR, and the fixture is what it printed
  nx_launch s nxsession; nx_launch c nxcommand; wait
  nx_collect s > "$NX_RECORD/agent-session.golden"
  nx_collect c > "$NX_RECORD/agent-command.golden"
  nx_request nxcommand codex > "$NX_RECORD/request-command.golden"
  exit 0
fi
# --- the runtimes: the project's own, two extra ones that can be used and one that cannot (it is not started by a command)
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
fake_command_runtime "$SRC" "$TOOL" fakecx
fake_command_runtime "$SRC" "$TOOL" fakeown
fake_command_runtime "$SRC" "$TOOL" fakeins '.dispatch.mode = "in-session"'
for r in fakecx fakeown; do mkdir -p "$HOME/.$r-members"; echo '{}' > "$HOME/.$r-members/auth.json"; done
mkproj() { # NAME PROVIDER-JSON EXTRAS-JSON PROFILES-JSON: stored answers with a repository of their own (and a worker when the project's own runtime works in the session)
  local repo=$T/repo-$1
  mkdir -p "$repo"; git init -q "$repo"
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" --argjson ex "${3:-null}" --argjson pr "${4:-null}" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"}},review:{base:"main",push:{mode:"none"}}}, profiles:($pr // {}),
    models:({provider:$prov} + (if $ex == null then {} else {extra_runtimes:{local:$ex}} end)),memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
  if [ "$(jq -r .local <<<"$2")" = claude-code ]; then "$DA" agent add worker --roles build,write,test --project "$1" >/dev/null 2>&1; fi
}
CC='{"local":"claude-code","cloud":"claude-platform"}'
PROFILES='{"cx-build":{"base":"worker","tier":"balanced","effort":"high","runtime":"fakecx"},"cx-review":{"base":"reviewer","tier":"deep","runtime":"fakecx"},
  "cx-pin":{"base":"worker","model":"claude-haiku-5-5","runtime":"fakecx"},"gone":{"base":"worker","tier":"fast","runtime":"nosuch"},
  "pin-gpt":{"base":"worker","model":"gpt-6-luna"},"cc-fast":{"base":"worker","tier":"fast","effort":"low"},"cc-own":{"base":"worker","tier":"fast","runtime":"claude-code"},
  "unusable":{"base":"worker","tier":"fast","runtime":"fakeins"},"badname":{"base":"worker","tier":"fast","runtime":"Not A Name"}}'
mkproj two "$CC" '["fakecx","fakeins"]' "$PROFILES"
mkproj plain "$CC" null "$PROFILES"
mkproj cmdplain '{"local":"fakeown"}' null "$PROFILES"
mkproj cmdtwo '{"local":"fakeown"}' '["fakecx"]' "$PROFILES"
mkproj cmdpin '{"local":"fakeown"}' null '{"pin":{"base":"worker","model":"claude-haiku-5-5"}}'

# the commands of the next groups, started together
nx_launch s nxsession; nx_launch c nxcommand
nx_request nxcommand codex > "$T/request.out" 2>&1 &
AFJ own build --project two
AFJ prof build --project two --profile cx-build
AFJ optprof build --project two --profile cx-build --runtime claude-code
AFJ optown build --project two --runtime fakecx
AFJ revopt review --project two --runtime fakecx
AFJ revprof review --project two --profile cx-review
AFJ fast build --project two --profile cc-fast
AFJ fastcx build --project two --profile cc-fast --runtime fakecx
AFJ ccown build --project two --profile cc-own
AFJ jsonin build --project two --json
AFJ jsoncmd build --project two --profile cx-build --json
AFJ plain build --project plain
AFJ plainjson build --project plain --json
AFJ plainown build --project plain --runtime claude-code
AFJ plainprof build --project plain --profile cc-own
AFJ plaincx build --project plain --runtime fakecx
AFJ plainprofcx build --project plain --profile cx-build
AFJ nosuch build --project two --runtime nosuch
AFJ gone build --project two --profile gone
AFJ unusable build --project two --profile unusable
AFJ badname build --project two --profile badname
AFJ badopt1 build --project two --runtime Bad_Name
AFJ badopt2 build --project two --runtime 'x y'
AFJ cloud build --project two --runtime fakecx --surface cloud
job list "$DA" agent list --runtime fakecx
AFJ cxpin build --project two --profile cx-pin
AFJ pingpt build --project two --profile pin-gpt
AFJ pingptcx build --project two --profile pin-gpt --runtime fakecx
AFJ plainpin build --project plain --profile pin-gpt
AFJ cmdpin build --project cmdpin --profile pin
AFJ cmdplain build --project cmdplain
AFJ cmdtwo1 build --project cmdtwo
AFJ cmdtwo2 build --project cmdtwo --profile cx-build --runtime fakeown
AFJ cmdtwo3 build --project cmdtwo --profile cx-build
AMJ mtwo --project two
AMJ mtwojson --project two --json
AMJ mcmdtwo --project cmdtwo
AMJ mplain --project plain
AMJ mplainjson --project plain --json
wait

ok() { echo "ok $1"; }            # the named cases below print `ok NAME`
refusal_code() { sed -n 's/^qargi-refusal\/1 .*"code":"\([a-z-]*\)".*/\1/p' <<<"$1"; }

for pair in session:s command:c; do
  out=$(nx_collect "${pair##*:}" 2>&1)
  [ "$out" = "$(cat "$NX/agent-${pair%%:*}.golden")" ] && echo "ok   no extras: agent for and agent models of the ${pair%%:*} fixture project are as recorded" \
    || { echo "FAIL no extras: agent for and agent models of the ${pair%%:*} fixture project changed:"; diff <(echo "$out") "$NX/agent-${pair%%:*}.golden" | head -10; fail=1; }
done
out=$(cat "$T/request.out")
[ "$out" = "$(cat "$NX/request-command.golden")" ] && echo "ok   no extras: the prepared request of the command fixture project is as recorded" \
  || { echo "FAIL no extras: the prepared request changed:"; diff <(echo "$out") "$NX/request-command.golden" | head -10; fail=1; }

# --- the order: the task's --runtime, then the profile's runtime, then the project's own
out=$(res own)
[ "$out" = "worker sonnet high build claude-code" ] && ok resolve-own-runtime || no "own runtime: $out"
out=$(res prof)
[ "$out" = "worker gpt-6.1-terra high cx-build fakecx" ] && ok resolve-profile-runtime || no "profile runtime: $out"
out=$(res optprof)
[ "$out" = "worker sonnet high cx-build claude-code" ] && ok resolve-option-over-profile || no "option over profile: $out"
out=$(res optown)
[ "$out" = "worker gpt-6.1-terra high build fakecx" ] && ok resolve-option-over-own || no "option over own: $out"
out=$(res revopt); out2=$(res revprof)
{ [ "$out" = "reviewer gpt-6.1-sol high review fakecx" ] && [ "$out2" = "reviewer gpt-6.1-sol medium cx-review fakecx" ]; } && ok resolve-read-only-role || no "review: $out | $out2"
# the profile is resolved in the runtime that serves it: the same tier is another model there, and the effort the profile names is kept
out=$(res fast); out2=$(res fastcx)
{ [ "$out" = "worker haiku low cc-fast claude-code" ] && [ "$out2" = "worker gpt-6-luna low cc-fast fakecx" ]; } && ok resolve-tier-in-runtime || no "tier in runtime: $out | $out2"
out=$(res ccown)
[ "$out" = "worker haiku medium cc-own claude-code" ] && ok resolve-profile-names-own || no "profile names the own runtime: $out"

# --- with extras every answer names its runtime: a fifth word, and a key of the JSON; `mode` stays where it was
out=$(res jsonin)
jq -e '.runtime == "claude-code" and (has("mode") | not) and .member == "worker" and .model == "sonnet"' <<<"$out" >/dev/null && ok resolve-json-runtime-insession || no "json in session: $out"
out=$(res jsoncmd)
jq -e '.runtime == "fakecx" and .mode == "command" and .model_id == "gpt-6.1-terra"' <<<"$out" >/dev/null && ok resolve-json-runtime-command || no "json command: $out"
[ "$(jq -r 'keys_unsorted[-1]' <<<"$out")" = runtime ] && ok resolve-json-runtime-last || no "json order: $out"

# --- a project without extras sees no new word
out=$(res plain); out2=$(res plainjson)
{ [ "$out" = "worker sonnet high build" ] && ! jq -e 'has("runtime")' <<<"$out2" >/dev/null; } && ok resolve-no-extras-no-word || no "no extras: $out | $out2"
out=$(res plainown)
[ "$out" = "worker sonnet high build" ] && ok resolve-no-extras-own-runtime-option || no "no extras, own runtime: $out"
out=$(res plainprof)
[ "$out" = "worker haiku medium cc-own" ] && ok resolve-no-extras-profile-own-runtime || no "no extras, profile names own: $out"
out=$(res plaincx); rc=$(rc_of plaincx)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ] && grep -q 'refused \[runtime-not-enabled\] the runtime fakecx is not enabled for this project' <<<"$out"; } \
  && ok resolve-no-extras-not-enabled || no "no extras, --runtime: rc=$rc $out"
out=$(res plainprofcx); rc=$(rc_of plainprofcx)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ]; } && ok resolve-no-extras-profile-not-enabled || no "no extras, profile runtime: rc=$rc $out"

# --- the runtime must be enabled, and an extra must still be usable
out=$(res nosuch); rc=$(rc_of nosuch)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ] && grep -q '"detail":"name=nosuch"' <<<"$out"; } && ok resolve-not-enabled-option || no "not enabled, option: rc=$rc $out"
out=$(res gone); rc=$(rc_of gone)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-not-enabled ]; } && ok resolve-not-enabled-profile || no "not enabled, profile: rc=$rc $out"
out=$(res unusable); rc=$(rc_of unusable)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-unusable ] && grep -q 'name=fakeins why=not-command' <<<"$out"; } && ok resolve-unusable || no "unusable: rc=$rc $out"
out=$(res badname); rc=$(rc_of badname)
{ [ "$rc" = 2 ] && grep -q 'not a runtime name' <<<"$out"; } && ok resolve-profile-runtime-not-a-name || no "bad name in profile: rc=$rc $out"
{ [ "$(rc_of badopt1)" = 2 ] && [ "$(rc_of badopt2)" = 2 ] && grep -q -- '--runtime: a runtime name' "$T/jobs/badopt1.out"; } && ok resolve-option-not-a-name || no "--runtime not a name: $(res badopt1) $(res badopt2)"
{ [ "$(rc_of cloud)" = 2 ] && grep -q -- '--runtime is for the local surface' "$T/jobs/cloud.out"; } && ok resolve-option-not-for-cloud || no "cloud: $(rc_of cloud) $(res cloud)"
{ [ "$(rc_of list)" = 2 ] && grep -q 'only qargi agent for takes it' "$T/jobs/list.out"; } && ok resolve-option-only-for || no "agent list --runtime: $(rc_of list) $(res list)"

# --- a profile's own model belongs to the runtime it is resolved in
out=$(res cxpin); rc=$(rc_of cxpin)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-profile-model ] && grep -q 'name=fakecx profile=cx-pin' <<<"$out"; } && ok resolve-profile-model-command || no "model in command runtime: rc=$rc $out"
out=$(res pingpt); rc=$(rc_of pingpt)
{ [ "$rc" = 1 ] && [ "$(refusal_code "$out")" = runtime-profile-model ] && grep -q 'name=claude-code profile=pin-gpt' <<<"$out"; } && ok resolve-profile-model-insession || no "model in session: rc=$rc $out"
out=$(res pingptcx)
[ "$out" = "worker gpt-6-luna medium pin-gpt fakecx" ] && ok resolve-profile-model-offered || no "model offered: $out"
out=$(res plainpin); rc=$(rc_of plainpin)
{ [ "$rc" = 0 ] && ! grep -q 'qargi-refusal/1' <<<"$out"; } && ok resolve-no-extras-profile-model-as-before || no "no extras, a model in session: rc=$rc $out"
out=$(res cmdpin); rc=$(rc_of cmdpin)
{ [ "$rc" = 2 ] && ! grep -q 'qargi-refusal/1' <<<"$out" && grep -q 'the pin profile is refused on fakeown: model claude-haiku-5-5 is not in the catalog of fakeown' <<<"$out"; } \
  && ok resolve-no-extras-profile-model-message-kept || no "no extras, a model of a command runtime: rc=$rc $out"

# --- a project whose own runtime is a command runtime: the same order, and the answer names the own runtime when there are extras
out=$(res cmdplain)
[ "$out" = "worker gpt-6.1-terra high build" ] && ok resolve-command-own-no-extras || no "command own, no extras: $out"
out=$(res cmdtwo1); out2=$(res cmdtwo2); out3=$(res cmdtwo3)
{ [ "$out" = "worker gpt-6.1-terra high build fakeown" ] && [ "$out2" = "worker gpt-6.1-terra high cx-build fakeown" ] && [ "$out3" = "worker gpt-6.1-terra high cx-build fakecx" ]; } \
  && ok resolve-command-own-with-extras || no "command own, extras: $out | $out2 | $out3"

# --- agent models: a RUNTIME column and each profile resolved in its own runtime, on the same condition
out=$(res mtwo)
{ grep -q "^runtimes: claude-code (the project's own), fakecx, fakeins\$" <<<"$out" \
  && grep -E '^ *build ' <<<"$out" | grep -q 'claude-code *balanced -> sonnet -> claude-sonnet-5-5' \
  && grep -E '^ *cx-build ' <<<"$out" | grep -q 'fakecx *gpt-6.1-terra/high' \
  && grep -E '^ *cx-review ' <<<"$out" | grep -q 'fakecx *gpt-6.1-sol/medium' \
  && grep -E '^ *cx-pin ' <<<"$out" | grep -q 'fakecx .*! refused: .*model claude-haiku-5-5 is not in the catalog of fakecx' \
  && grep -E '^ *gone ' <<<"$out" | grep -q 'nosuch .*! refused: the runtime nosuch is not enabled for this project' \
  && grep -E '^ *unusable ' <<<"$out" | grep -q 'fakeins .*! refused: the runtime fakeins cannot be used' \
  && grep -E '^ *pin-gpt ' <<<"$out" | grep -q 'claude-code .*! refused: .*model gpt-6-luna is not in the catalog of claude-code' \
  && grep -E '^ *worker ' <<<"$out" | grep -q 'claude-sonnet-5-5/high'; } && ok models-runtime-column || no "models text: $out"
out=$(res mtwojson)
jq -e '.runtimes == {primary: "claude-code", extra: ["fakecx", "fakeins"]} and .profiles["cx-build"].runtime == "fakecx" and .profiles["cx-build"].selected == "gpt-6.1-terra" and .profiles["cx-build"].mode == "command"
  and .profiles.build.runtime == "claude-code" and .profiles.build.model == "sonnet" and .profiles.gone.runtime == "nosuch" and (.profiles.gone.refused | test("not enabled"))
  and ([.warnings[] | select(.kind == "profile" and .name == "cx-pin")] | length == 1) and (.members | length == 1) and ([.profiles[] | .runtime] | all(type == "string"))' <<<"$out" >/dev/null \
  && ok models-json-runtime || no "models json: $out"
out=$(res mcmdtwo)
{ grep -q "^runtimes: fakeown (the project's own), fakecx\$" <<<"$out" && grep -E '^ *build ' <<<"$out" | grep -q 'fakeown *gpt-6.1-terra/high' && ! grep -q '^members' <<<"$out"; } \
  && ok models-command-own-with-extras || no "models, command own: $out"
out=$(res mplain)
{ ! grep -q 'runtime' <<<"$out" && ! jq -e 'has("runtimes") or ([.profiles[] | has("runtime")] | any)' "$T/jobs/mplainjson.out" >/dev/null; } && ok models-no-extras-no-column || no "models, no extras: $out"

# --- the prepared request: the profile is resolved in the run's runtime; the request of the project's own runtime is the request it was without extras
CURRENT() { # PROJECT RUNTIME CLASS REQUEST-JSON: prepared_request.current(), whose drift is an Invalid
  python3 -I -c 'import json, sys
sys.path.insert(0, sys.argv[1] + "/lib")
import prepared_request as PR
try:
    PR.current(json.loads(sys.argv[5]), sys.argv[2], sys.argv[3], sys.argv[4])
except PR.Invalid as e:
    print(e)
    sys.exit(2)' "$TOOL" "$@"
}
mkproj cmdx '{"local":"fakeown"}' null "$PROFILES"
PRQJ ownb cmdx fakeown build write; PRQJ selb cmdx fakeown build write cc-fast
wait
own_before=$(res ownb); sel_before=$(res selb)
mkproj cmdx '{"local":"fakeown"}' '["fakecx"]' "$PROFILES"
PRQJ owna cmdx fakeown build write; PRQJ sela cmdx fakeown build write cc-fast
PRQJ ext cmdx fakecx build write; PRQJ extprof cmdx fakecx build write cx-build; PRQJ ownprof cmdx fakeown build write cx-build; PRQJ extrev cmdx fakecx review read-only
job curown CURRENT cmdx fakeown write "$own_before"
wait
own_after=$(res owna); sel_after=$(res sela); ext=$(res ext)
{ jq -e '.runtime == "fakeown" and .binding.policy != null' <<<"$own_before" >/dev/null && [ "$own_before" = "$own_after" ] && [ "$sel_before" = "$sel_after" ]; } \
  && ok request-own-unchanged-by-extras || no "own request moved: $own_before | $own_after"
[ "$(rc_of curown)" = 0 ] && ok request-open-run-before-enable-current || no "an own request prepared before the enable is stale: $(res curown)"
{ jq -e '.runtime == "fakecx" and .model == "gpt-6.1-terra" and .profile == "build" and .binding.policy != null' <<<"$ext" >/dev/null \
  && [ "$(jq -r .binding.policy <<<"$ext")" != "$(jq -r .binding.policy <<<"$own_after")" ] && [ "$(jq -r .binding.runtime <<<"$ext")" != "$(jq -r .binding.runtime <<<"$own_after")" ]; } \
  && ok request-extra-runtime || no "extra request: $ext"
out=$(res extprof)
jq -e '.runtime == "fakecx" and .profile == "cx-build" and .selector == "cx-build" and .effort == "high"' <<<"$out" >/dev/null && ok request-profile-in-its-runtime || no "request, profile of the extra: $out"
out=$(res ownprof)
{ jq -e '.runtime == "fakeown" and .profile == "cx-build"' <<<"$out" >/dev/null && [ "$(jq -r .binding.runtime <<<"$out")" = "$(jq -r .binding.runtime <<<"$own_after")" ]; } \
  && ok request-option-over-profile-runtime || no "request, the project's own against a profile of an extra: $out"
out=$(res extrev)
jq -e '.runtime == "fakecx" and .base == "reviewer" and .class == "read-only"' <<<"$out" >/dev/null && ok request-read-only-extra || no "request, review on the extra: $out"
CURRENT cmdx fakecx write "$ext" >"$T/o" 2>&1 && ok request-extra-current || no "an extra request is not current: $(cat "$T/o")"
mkproj cmdx '{"local":"fakeown"}' null "$PROFILES"
job curext CURRENT cmdx fakecx write "$ext"; job curown2 CURRENT cmdx fakeown write "$own_before"; PRQJ notenabled cmdx fakecx build write
wait
out=$(res curext)
{ [ "$(rc_of curext)" = 2 ] && grep -q 'cannot be resolved' <<<"$out" && grep -q 'runtime-not-enabled' <<<"$out" && grep -q 're-prepare with qargi local prepare' <<<"$out" && ! grep -q 'qargi-refusal/1' <<<"$out"; } \
  && ok request-extra-disabled-drifts || no "a request of a disabled runtime: rc=$(rc_of curext) $out"
[ "$(rc_of curown2)" = 0 ] && ok request-own-still-current || no "the own request after the disable: $(res curown2)"
out=$(res notenabled)
{ [ "$(rc_of notenabled)" = 2 ] && grep -q 'runtime-not-enabled' <<<"$out" && ! grep -q 'qargi-refusal/1' <<<"$out"; } && ok request-not-enabled || no "request, runtime not enabled: rc=$(rc_of notenabled) $out"

exit $fail
