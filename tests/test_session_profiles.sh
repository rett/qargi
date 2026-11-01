#!/usr/bin/env bash
# Sessions of the two cloud bases (<project>-worker, <project>-reviewer) started and driven for a role and a profile:
#   qargi start|send <project>-worker|-reviewer --role ROLE [--profile P] [--opt-in] --asked "..."
# The session is created with agent_with_overrides (the full model object and the system prompt rendered from qargi's own
# files), the deployment's environment, resources, vaults and budget are copied, the repository credential travels on
# stdin only, a reviewer needs the project's acceptance of the missing read-only barrier, and an idle session is reused only
# for the same role, profile, model and effort. The legacy role instances (<project>-build ...) start exactly as before.
# Hermetic, offline: a fake `ant`, and a copy of the tool whose descriptor has the per-dispatch overrides verified (the
# shipped one has not, so the checkout itself falls back to the legacy instances). Run: tests/test_session_profiles.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE" "$T/secrets"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
SHIP=$SRC/bin/qargi; YES=$TOOL/bin/qargi
jq '.capabilities.per_dispatch_model_override.cloud |= (.verified_on = "2026-10-31")
  | .capabilities.per_dispatch_effort_override.cloud |= (.verified_on = "2026-10-31")' "$SRC/lib/providers/claude.json" > "$T/claude.json" && mv "$T/claude.json" "$TOOL/lib/providers/claude.json"

# the fake ant: logs its arguments, answers a deployment, keeps the body of every session create and numbers the sessions
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:deployments)
    jq -nc --arg id "$(arg --deployment-id "$@")" '{id: $id, agent: {id: "agent_01", version: 3}, environment_id: "env_01", vault_ids: ["vlt_01"],
      budget: {type: "limit", max_list_cost: {amount: "500", currency: "USD"}},
      resources: [{type: "memory_store", memory_store_id: "memstore_01", access: "read_write"}],
      initial_events: [{type: "user.message", content: [{type: "text", text: "Wait for the task."}]}]}';;
  beta:sessions)
    case $2 in
      create) n=$(( $(cat "$FAKE/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE/n"; cat > "$FAKE/body.$n.json"; echo "{\"id\":\"sesn_$n\"}";;
      retrieve) echo '{"status":"idle","budget":{"max_list_cost":{"amount":"500"}},"usage":{"list_cost":{"amount":"0"}}}';;
      *) echo '{}';;
    esac;;
  beta:sessions:events) case $2 in send) printf '%s\n' "$*" >> "$FAKE/sent.log"; echo '{}';; *) :;; esac;;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

TOKEN=ghp_TESTTOKEN0123456789abcdefXYZ
printf '%s\n' "$TOKEN" > "$T/secrets/tok"; chmod 600 "$T/secrets/tok"
# alpha: private repository (a credential); beta: public (none)
for p in alpha beta; do
  jq -n --arg p "$p" --arg f "$([ "$p" = alpha ] && echo "$T/secrets/tok")" '{schema:1,project:$p,repo:{url:"https://github.com/example/\($p)",credential_file:$f,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},memory:{},budget_cents:500}' > "$T/c/projects/$p.json"
done
inst() { jq -n --arg d "$1" '{location:"cloud",deployment_id:$d,environment_id:"env_01",agent:{id:"agent_01",version_pinned:3,model:"claude-sonnet-5-5",effort:"high"}}'; }
jq -n --argjson w "$(inst depl_W)" --argjson r "$(inst depl_R)" --argjson b "$(inst depl_B)" \
  '{"alpha-worker":$w,"alpha-reviewer":$r,"alpha-build":$b,"beta-worker":$w,"beta-reviewer":$r}' > "$T/c/instances.json"
mkdir -p "$T/c/roles/tw"; echo '{"class":"write"}' > "$T/c/roles/tw/role.json"; printf '# Role: tw\n\nA second write role.\n' > "$T/c/roles/tw/ROLE.md"
. lib/lib.sh
n_creates() { ls "$FAKE"/body.*.json 2>/dev/null | wc -l; }
trk() { jq -r --arg s "$1" ".[\$s] | ($2)" "$T/s/sessions.json"; }
S=claude-sonnet-5-5; H=claude-haiku-5-5

# --- the body of a worker session, from the dry run (alpha has a credential)
body=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role build --asked "start the build base" 2>"$T/err"); rc=$?
[ $rc = 0 ] && jq -e . <<<"$body" >/dev/null 2>&1 && ok "dry run: start alpha-worker --role build prints a JSON body" || no "dry run (rc=$rc): $body $(cat "$T/err")"
jq -e '.agent.type == "agent_with_overrides" and .agent.id == "agent_01" and .agent.version == 3' <<<"$body" >/dev/null && ok "the agent is agent_with_overrides, with the deployment's agent id and version" || no "agent: $(jq -c .agent <<<"$body")"
jq -e --arg m "$S" '.agent.model == {id: $m, effort: "high"}' <<<"$body" >/dev/null && ok "the model is a full object {id, effort} of the build profile" || no "model: $(jq -c .agent.model <<<"$body")"
[ "$(jq -r .agent.system <<<"$body")" = "$(agent_prompt build alpha)" ] && ok "the system is agent_prompt build alpha (qargi's own files)" || no "system differs from agent_prompt build alpha"
jq -e 'has("tools") or has("skills") or has("mcp_servers") or (.agent|has("tools") or has("skills") or has("mcp_servers")) | not' <<<"$body" >/dev/null && ok "no tools, skills or mcp_servers in the body" || no "fixed fields in the body"
jq -e '.environment_id == "env_01" and .vault_ids == ["vlt_01"] and .metadata == {deployment_id: "depl_W"}' <<<"$body" >/dev/null && ok "environment, vaults and metadata are the deployment's" || no "env: $(jq -c '[.environment_id,.vault_ids,.metadata]' <<<"$body")"
jq -e '.budget == {type: "limit", max_list_cost: {amount: "500", currency: "USD"}}' <<<"$body" >/dev/null && ok "the deployment's budget is copied (send refuses a session without one)" || no "budget: $(jq -c .budget <<<"$body")"
jq -e '.resources[0].type == "memory_store" and (.resources | map(select(.type == "github_repository")) | length == 1)' <<<"$body" >/dev/null && ok "the deployment's resources, then the repository" || no "resources: $(jq -c .resources <<<"$body")"
jq -e '.resources[] | select(.type == "github_repository") | .url == "https://github.com/example/alpha" and .authorization_token == "***"' <<<"$body" >/dev/null && ok "the repository is mounted with the token redacted" || no "repository resource"
grep -q "$TOKEN" <<<"$body" && no "THE DRY RUN PRINTED THE TOKEN" || ok "the dry run never prints the token"
jq -e '.initial_events | length == 1' <<<"$body" >/dev/null && ok "the deployment's initial events are kept" || no "initial_events"
[ "$(n_creates)" = 0 ] && ok "a dry run creates no session" || no "the dry run created a session"
body=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role build --profile test --asked "start the test profile" 2>&1)
jq -e --arg m "$S" '.agent.model == {id: $m, effort: "low"}' <<<"$body" >/dev/null && ok "--profile test: sonnet with effort low" || no "profile test: $(jq -c .agent.model <<<"$body" 2>/dev/null || echo "$body")"
body=$(QARGI_DRY_RUN=1 "$YES" start beta-worker --role tw --asked "no credential" 2>&1)
jq -e '.resources | map(.type) == ["memory_store"]' <<<"$body" >/dev/null && ok "a project with no credential mounts no repository" || no "beta resources: $(jq -c .resources <<<"$body" 2>/dev/null || echo "$body")"

# --- the reviewer is refused until the project accepts that cloud has no read-only barrier
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-reviewer --role review --asked "review" 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q "qargi provider accept claude --surface cloud --no-barrier --project alpha --asked" <<<"$out"; } && ok "start alpha-reviewer: refused (exit 2) with the accept command" || no "reviewer without acceptance (rc=$rc): $out"
out=$("$YES" send alpha-reviewer "review it" --role review --label rv --new --asked "review" 2>&1); rc=$?
[ $rc = 2 ] && [ "$(n_creates)" = 0 ] && ok "send --new: refused too, and no session was created" || no "send reviewer without acceptance (rc=$rc, creates=$(n_creates)): $out"
tok=$("$YES" provider accept claude --surface cloud --no-barrier --project alpha --asked "I accept it" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
"$YES" provider accept claude --surface cloud --no-barrier --project alpha --asked "I accept it" --plan "$tok" --approved go >"$T/acc.out" 2>&1 || no "accept: tok=$tok $(cat "$T/acc.out")"
body=$(QARGI_DRY_RUN=1 "$YES" start alpha-reviewer --role review --profile auditor --asked "audit" 2>&1); rc=$?
[ $rc = 0 ] && jq -e --arg m "$H" '.agent.type == "agent_with_overrides" and .agent.id == "agent_01" and .agent.model == {id: $m, effort: "low"}' <<<"$body" >/dev/null && ok "after the acceptance: the reviewer body, haiku with effort low for the auditor profile" || no "reviewer accepted (rc=$rc): $body"
[ "$(jq -r .agent.system <<<"$body")" = "$(agent_prompt review alpha)" ] && ok "the reviewer's system is agent_prompt review alpha" || no "reviewer system"
jq -e '.metadata == {deployment_id: "depl_R"}' <<<"$body" >/dev/null && ok "and it copies the reviewer deployment" || no "reviewer metadata"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-reviewer --role review --profile researcher --asked "research" 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'opt-in' <<<"$out"; } && ok "an opt-in profile needs --opt-in" || no "researcher (rc=$rc): $out"
QARGI_DRY_RUN=1 "$YES" start alpha-reviewer --role review --profile researcher --opt-in --asked "research" 2>&1 | jq -e '.agent.model.id == "claude-fable-5-1"' >/dev/null && ok "--opt-in passes it on" || no "researcher with --opt-in"

# --- the role must belong to the base's class, the base must be usable, and the options are for bases
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role review --asked "x" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "read-only class" <<<"$out" && ! jq -e . <<<"$out" >/dev/null 2>&1 && ok "a read-only role on the worker base is refused" || no "review on worker (rc=$rc): $out"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-reviewer --role build --asked "x" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "write class" <<<"$out" && ! jq -e . <<<"$out" >/dev/null 2>&1 && ok "a write role on the reviewer base is refused" || no "build on reviewer (rc=$rc): $out"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role build --profile review --asked "x" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "review" <<<"$out" && ! jq -e . <<<"$out" >/dev/null 2>&1 && ok "a profile of the other class is refused" || no "review profile on worker (rc=$rc): $out"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role nosuch --asked "x" 2>&1); [ $? != 0 ] && grep -q -- "--role: a role of" <<<"$out" && ok "an unknown role is refused" || no "unknown role"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --role lead --asked "x" 2>&1); [ $? != 0 ] && grep -q -- "--role: a role of" <<<"$out" && ok "lead is not a role of a base" || no "lead role"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-worker --profile test --asked "x" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'need --role' <<<"$out"; } && ok "--profile without --role is refused: a base without a role is the standby session, as before" || no "profile without role (rc=$rc): $out"
out=$(QARGI_DRY_RUN=1 "$YES" start alpha-build --role build --asked "x" 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'are for the bases' <<<"$out"; } && ok "--role is for the bases: a legacy instance refuses it" || no "legacy with --role (rc=$rc): $out"
out=$(QARGI_DRY_RUN=1 "$SHIP" start alpha-worker --role build --asked "x" 2>&1); rc=$?
{ [ $rc != 0 ] && ! jq -e . <<<"$out" >/dev/null 2>&1 && grep -q 'not usable yet' <<<"$out"; } && ok "the shipped tool (overrides unverified) falls back to the legacy instance: the base is refused" || no "legacy fallback (rc=$rc): $out"
[ "$(n_creates)" = 0 ] && ok "none of these created a session" || no "a refused start created a session"

# --- really creating: the body goes to ant on stdin only, the session is tracked with its role, profile, model and effort
: > "$FAKE/ant.log"
out=$("$YES" send alpha-worker "do the build" --role build --label first --new --asked "build it" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(n_creates)" = 1 ] && ok "send --new creates one session" || no "send --new (rc=$rc, creates=$(n_creates)): $out"
jq -e --arg m "$S" '.agent.type == "agent_with_overrides" and .agent.model == {id: $m, effort: "high"} and .budget.max_list_cost.amount == "500"' "$FAKE/body.1.json" >/dev/null && ok "the body ant received is the dry-run body" || no "created body"
jq -e --arg t "$TOKEN" '.resources[] | select(.type == "github_repository") | .authorization_token == $t' "$FAKE/body.1.json" >/dev/null && ok "the token reaches ant in the body on stdin" || no "token missing from the created body"
grep -q "$TOKEN" "$FAKE/ant.log" && no "THE TOKEN IS IN AN ARGUMENT" || ok "the token is in no command-line argument"
grep -rq "$TOKEN" "$T/s" && no "THE TOKEN IS IN THE STATE DIRECTORY" || ok "the token is in neither the tracker nor the audit log"
SH=$(printf '%s' "$(agent_prompt build alpha)" | sha256sum | cut -c1-16)
[ "$(trk sesn_1 .instance)" = alpha-worker ] && [ "$(trk sesn_1 .role)" = build ] && [ "$(trk sesn_1 .profile)" = build ] && [ "$(trk sesn_1 .model)" = "$S" ] && [ "$(trk sesn_1 .effort)" = high ] && ok "tracker: instance, role, profile, model and effort" || no "tracker: $(trk sesn_1 '[.instance,.role,.profile,.model,.effort]|join(" ")')"
[ "$(trk sesn_1 .prompt_sha)" = "$SH" ] && ok "tracker: prompt_sha is the first 16 of the sha256 of the system" || no "prompt_sha: $(trk sesn_1 .prompt_sha) want $SH"
[ "$(trk sesn_1 .label)" = first ] && [ "$(trk sesn_1 .budget)" = 500 ] && grep -q 'sessions:events send --session-id sesn_1' "$FAKE/sent.log" && ok "the task was sent to the new session, which has its label and budget" || no "send after create: $(trk sesn_1 '[.label,.budget]|join(" ")')"
[ "$(trk sesn_1 .asked)" = "build it" ] && ok "tracker keeps the usual fields" || no "asked"

# --- reuse: only for the same role, profile, model and effort (a finished session is idle again once status has read it)
"$YES" status >/dev/null 2>&1
: > "$FAKE/sent.log"
out=$("$YES" send alpha-worker "again" --role build --label second --asked "again" 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$(n_creates)" = 1 ] && grep -q 'session-id sesn_1' "$FAKE/sent.log"; } && ok "same role, profile, model and effort: the idle session is reused" || no "reuse (rc=$rc, creates=$(n_creates)): $out"
"$YES" status >/dev/null 2>&1
for spec in "--role build --profile test" "--role write" "--role tw"; do
  out=$("$YES" send alpha-worker "other" $spec --label third --asked "other" 2>&1); rc=$?
  { [ $rc != 0 ] && grep -q 'started for' <<<"$out" && grep -q -- '--new' <<<"$out" && [ "$(n_creates)" = 1 ]; } && ok "reuse refused for '$spec', which says to use --new" || no "reuse '$spec' (rc=$rc, creates=$(n_creates)): $out"
done
out=$("$YES" send alpha-worker "other" --role tw --label third --new --asked "other" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(n_creates)" = 2 ] && [ "$(trk sesn_2 .role)" = tw ] && [ "$(trk sesn_2 .profile)" = build ] && ok "with --new a session of the other role is created" || no "--new tw (rc=$rc): $out"
: > "$FAKE/sent.log"
"$YES" status >/dev/null 2>&1
"$YES" send alpha-worker "to tw" --role tw --label fourth --asked "tw" >/dev/null 2>&1
grep -q 'session-id sesn_2' "$FAKE/sent.log" && ok "and each role finds its own idle session" || no "reuse picks the wrong session: $(cat "$FAKE/sent.log")"
: > "$FAKE/sent.log"
out=$("$YES" send alpha-worker "x" --role write --label fifth --session sesn_1 --asked "x" 2>&1); rc=$?
[ $rc != 0 ] && grep -q 'was not started for' <<<"$out" && [ ! -s "$FAKE/sent.log" ] && ok "--session of a session of another role is refused too" || no "--session mismatch (rc=$rc): $out"
jq '.sesn_1 |= del(.role)' "$T/s/sessions.json" > "$T/x.json" && mv "$T/x.json" "$T/s/sessions.json"
out=$("$YES" send alpha-worker "x" --role build --label sixth --session sesn_1 --asked "x" 2>&1); [ $? != 0 ] && grep -q 'was not started for' <<<"$out" && ok "a session with no recorded role is not reused for a base" || no "untracked role reused"

# --- the reviewer, created for real (accepted above)
out=$("$YES" send alpha-reviewer "review it" --role review --profile auditor --label rv --new --asked "review" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(trk sesn_3 .role)" = review ] && [ "$(trk sesn_3 .profile)" = auditor ] && [ "$(trk sesn_3 .model)" = "$H" ] && [ "$(trk sesn_3 .effort)" = low ] && ok "a reviewer session is tracked with role review, profile auditor, haiku, low" || no "reviewer create (rc=$rc): $out"

# --- the legacy instances start exactly as before (golden: the body ant receives, the token being the credential's)
want=$(jq -nS --arg t "$TOKEN" '{agent: {id: "agent_01", type: "agent", version: 3}, environment_id: "env_01", vault_ids: ["vlt_01"],
  resources: [{type: "memory_store", memory_store_id: "memstore_01", access: "read_write"},
              {type: "github_repository", url: "https://github.com/example/alpha", authorization_token: $t}],
  initial_events: [{type: "user.message", content: [{type: "text", text: "Wait for the task."}]}],
  metadata: {deployment_id: "depl_B"}, budget: {type: "limit", max_list_cost: {amount: "500", currency: "USD"}}}')
before=$(n_creates)
"$YES" send alpha-build "legacy task" --label legacy --new --asked "legacy" >/dev/null 2>&1
last=$(n_creates)
[ "$last" = $((before + 1)) ] && ok "a legacy session is created" || no "legacy create"
got=$(jq -S . "$FAKE/body.$last.json" 2>&1)
[ "$got" = "$want" ] && ok "legacy start: the request body is unchanged" || { no "legacy golden"; diff <(echo "$want") <(echo "$got") | head -10; }
[ "$(trk "sesn_$last" .instance)" = alpha-build ] && [ "$(trk "sesn_$last" .role)" = null ] && [ "$(trk "sesn_$last" .prompt_sha)" = null ] && ok "and it is tracked with no role fields, as before" || no "legacy tracker row"

[ $fail = 0 ] && echo "session profile tests passed" || { echo "session profile tests FAILED"; exit 1; }
