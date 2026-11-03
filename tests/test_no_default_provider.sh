#!/usr/bin/env bash
# There is no default provider: a project's provider is its models.provider, and every verb that needs one refuses a project that has
# none (exit 2, the one message of lib/provider.py), instead of falling back to claude. Covers each place that used to fall back:
# agent add/list/models/for/refresh/rename, provision plan (the model default), local prepare and the cloud starts (the read-only
# barrier and the session request), project attach/new (--provider is stored only when given) and project validate. Every verb works
# when the project names claude and when it names a fake provider, and no output names claude for a project that does not. Last, a
# grep that fails if a fallback to claude is written again. A provider per surface (models.provider is {local, cloud}) is covered too:
# each verb asks for the surface it runs on, a surface left out is refused only by the verbs that need it, a string that resolves through
# its family prints the notice, project set/attach/new write and validate the object. Hermetic, offline: a copy of the tool holds the fake provider, so the
# shipped descriptors are never changed. Run: tests/test_no_default_provider.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T FAKE=$T/fake
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE" "$T/scr"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
DA=$TOOL/bin/qargi
# a fake provider: claude's descriptor with other names, models and a pattern of its own (the adapter, the barrier and the layout are shared)
jq '.provider = "fakeprov" | .model_pattern = "^fake-[a-z0-9.-]+$"
  | .tiers = {fast: "fake-s-1", balanced: "fake-m-1", deep: "fake-l-1", frontier: "fake-xl-1"}
  | .aliases = {fast: "tiny", balanced: "mid", deep: "big", frontier: "huge"}
  | .tier_detail |= with_entries(.value.model = ({fast: "fake-s-1", balanced: "fake-m-1", deep: "fake-l-1", frontier: "fake-xl-1"}[.key]) | .value.alias = ({fast: "tiny", balanced: "mid", deep: "big", frontier: "huge"}[.key]))
  | .local.reserved_names = ["fake-builtin"]' "$SRC/lib/providers/claude.json" > "$TOOL/lib/providers/fakeprov.json"
# the per-dispatch overrides on the cloud verified, in the copies only (the shipped descriptor has not verified them), so a cloud base session is built
for d in claude fakeprov; do
  jq '.capabilities.per_dispatch_model_override.cloud |= (.verified_on = "2026-10-31") | .capabilities.per_dispatch_effort_override.cloud |= (.verified_on = "2026-10-31")' \
    "$TOOL/lib/providers/$d.json" > "$T/d.json" && mv "$T/d.json" "$TOOL/lib/providers/$d.json"
done
python3 -I "$TOOL/lib/provider.py" check fakeprov >/dev/null 2>&1 && ok "the fake descriptor is valid" || no "the fake descriptor is not valid: $(python3 -I "$TOOL/lib/provider.py" check fakeprov 2>&1 | head -3)"

# the ant fake: logs its calls, answers a deployment, numbers the session creates
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:deployments)
    if [ "${2:-}" = run ]; then echo '{"session_id":"sesn_1"}'; exit 0; fi
    jq -nc --arg id "$(arg --deployment-id "$@")" '{id: $id, agent: {id: "agent_01", version: 3}, environment_id: "env_01", vault_ids: [],
      budget: {type: "limit", max_list_cost: {amount: "500", currency: "USD"}}, resources: []}';;
  beta:sessions)
    case $2 in
      create) n=$(( $(cat "$FAKE/n" 2>/dev/null || echo 0) + 1 )); echo "$n" > "$FAKE/n"; cat > "$FAKE/body.$n.json"; echo "{\"id\":\"sesn_$n\"}";;
      *) echo '{}';;
    esac;;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

# three projects with a repository each: np names no provider, cl names claude, fk names the fake one. The roles carry no model, so the
# model default comes from the provider (and, with none, from nowhere)
for p in np cl fk; do git init -q -b main "$T/repo-$p" && git -C "$T/repo-$p" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one; done
store() { # project provider-or-empty -> stored answers: roles build and review, the repository above, no role models
  "$DA" project template "$1" | jq --arg p "$2" --arg r "$T/repo-$1" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r
    | .roles.review = .roles.build | .roles.review.apt = [] | del(.roles[].model) | if $p == "" then del(.models) else .models.provider = $p end' > "$T/$1.json"
  "$DA" project init "$1" --answers "$T/$1.json" --force >/dev/null 2>&1 || { echo "FAIL init $1"; fail=1; }
}
store np ""; store cl claude; store fk fakeprov
jq -e '(.models // {}) | has("provider") | not' "$T/c/projects/np.json" >/dev/null && ok "np is stored with no models.provider" || no "np has a provider"
msg() { echo "qargi: project $1 has no provider: set one with qargi project set $1 models.provider NAME"; }   # the one message (lib/provider.py)
refuses() { # name rc output project: exit 2 with the shared message and no word claude
  if [ "$2" = 2 ] && [ "$3" = "$(msg "$4")" ]; then ok "$1"; else no "$1 (rc=$2: $3)"; fi
}
noclaude() { # name output: the output does not name claude (CLAUDE.md, a file of the methodology, is not the provider)
  if sed 's/CLAUDE\.md//g' <<<"$2" | grep -qi claude; then no "$1 names claude: $2"; else ok "$1"; fi
}

# --- the helper and the python side
out=$(python3 -I "$TOOL/lib/provider.py" of np --conf "$T/c" 2>&1); refuses "provider of: a project with none" "$?" "$out" np
out=$(python3 -I "$TOOL/lib/provider.py" of nosuch --conf "$T/c" 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ "$out" = "qargi: no such project 'nosuch'" ]; } && ok "provider of: an unknown project says so" || no "unknown project: rc=$rc $out"
out=$(python3 -I "$TOOL/lib/provider.py" of "" --conf "$T/c" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'pass --project NAME' <<<"$out"; } && ok "provider of: no project at all says to pass --project" || no "no project: rc=$rc $out"
( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c
  p=$(project_provider cl) && [ "$p" = claude ] && q=$(project_provider fk) && [ "$q" = fakeprov ] ) 2>/dev/null && ok "project_provider prints the named provider" || no "project_provider on named providers"
out=$( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c; project_provider np 2>&1 ); refuses "project_provider: a project with none is refused" "$?" "$out" np
out=$( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c; project_provider 2>&1 ); rc=$?
{ [ "$rc" = 2 ] && grep -q 'pass --project NAME' <<<"$out"; } && ok "project_provider: no project is refused" || no "project_provider with no project: rc=$rc $out"

# --- agent: add, list, models, for, refresh, rename
out=$("$DA" agent add m1 --project np 2>&1); refuses "agent add: a project with none is refused" "$?" "$out" np
out=$("$DA" agent add m1 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q -- '--project NAME' <<<"$out" && ! grep -qi claude <<<"$out"; } && ok "agent add: no --project is refused and says to pass it" || no "agent add without a project: rc=$rc $out"
out=$("$DA" agent add m1 --project nosuch 2>&1); rc=$?
{ [ "$rc" = 2 ] && [ "$out" = "qargi: no such project 'nosuch'" ]; } && ok "agent add: an unknown project says so" || no "agent add unknown project: rc=$rc $out"
[ "$(jq length "$T/c/agents.json" 2>/dev/null || echo 0)" = 0 ] && [ ! -e "$T/repo-np/.claude/agents" ] && ok "and nothing was made" || no "a member was made for a project with no provider"
out=$("$DA" agent models --project np 2>&1); refuses "agent models --project: a project with none is refused" "$?" "$out" np
out=$("$DA" agent for build --project np 2>&1); refuses "agent for --project: a project with none is refused" "$?" "$out" np
out=$("$DA" agent for build --project np --surface cloud 2>&1); refuses "agent for --surface cloud: a project with none is refused" "$?" "$out" np
out=$(cd "$T/repo-np" && "$DA" agent models 2>&1); refuses "agent models from the project's checkout: the inferred project is refused" "$?" "$out" np
out=$(cd "$T" && "$DA" agent models 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'pass --project NAME' <<<"$out" && ! grep -qi claude <<<"$out"; } && ok "agent models outside any project: refused, pass --project" || no "agent models outside a project: rc=$rc $out"
out=$(cd "$T" && "$DA" agent for build 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'pass --project NAME' <<<"$out"; } && ok "agent for outside any project: refused, pass --project" || no "agent for outside a project: rc=$rc $out"
"$DA" agent list >/dev/null 2>&1 && ok "agent list needs no provider" || no "agent list"

out=$("$DA" agent add mc --project cl 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r '.mc.model' "$T/c/agents.json")" = claude-sonnet-5-5 ]; } && ok "agent add: claude, the model default is its balanced model" || no "agent add claude: rc=$rc $out"
out=$("$DA" agent add mf --project fk 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r '.mf.model' "$T/c/agents.json")" = fake-m-1 ]; } && ok "agent add: the fake provider, the model default is its balanced model" || no "agent add fake: rc=$rc $out"
"$DA" agent add fake-builtin --project fk >/dev/null 2>&1 && no "a reserved name of the fake provider was accepted" || ok "agent add: the reserved names are the project's provider's"
"$DA" agent add general-purpose --project fk >/dev/null 2>&1 && ok "and claude's reserved names are not reserved for another provider" || no "claude's reserved name refused for the fake provider"
out=$("$DA" agent models --project cl --json 2>&1); { [ "$(jq -r .provider <<<"$out")" = claude ] && jq -e '.profiles[] | select(.name == "build") | .model_id == "claude-sonnet-5-5"' <<<"$out" >/dev/null; } && ok "agent models: claude" || no "models claude: $out"
out=$("$DA" agent models --project fk --json 2>&1); { [ "$(jq -r .provider <<<"$out")" = fakeprov ] && jq -e '.profiles[] | select(.name == "build") | .model_id == "fake-m-1"' <<<"$out" >/dev/null; } && ok "agent models: the fake provider" || no "models fake: $out"
noclaude "agent models --project fk names no claude" "$(jq -c 'del(.members)' <<<"$out")"
out=$("$DA" agent for build --project fk --json 2>&1); { jq -e '.model_id == "fake-m-1"' <<<"$out" >/dev/null && ! grep -qi claude <<<"$out"; } && ok "agent for: the fake provider's model, no claude" || no "for fake: $out"
out=$("$DA" agent for build --project cl --json 2>&1); jq -e '.model_id == "claude-sonnet-5-5"' <<<"$out" >/dev/null && ok "agent for: claude's model" || no "for claude: $out"
# refresh and rename: a member needs its project's provider; the provider is looked up again at refresh
out=$("$DA" agent refresh mc 2>&1); rc=$?; { [ "$rc" = 0 ] && grep -q 'current' <<<"$out"; } && ok "agent refresh: claude" || no "refresh claude: rc=$rc $out"
out=$("$DA" agent refresh mf 2>&1); rc=$?; { [ "$rc" = 0 ] && grep -q 'current' <<<"$out"; } && ok "agent refresh: the fake provider" || no "refresh fake: rc=$rc $out"
cp "$T/c/projects/cl.json" "$T/cl.keep"; jq 'del(.models)' "$T/cl.keep" > "$T/c/projects/cl.json"
out=$("$DA" agent refresh mc 2>&1); refuses "agent refresh: the project lost its provider, refused" "$?" "$out" cl
out=$("$DA" agent rename mc mc2 2>&1); refuses "agent rename: the project lost its provider, refused" "$?" "$out" cl
cp "$T/cl.keep" "$T/c/projects/cl.json"
out=$("$DA" agent rename mc mc2 2>&1); [ "$?" = 0 ] && ok "agent rename: works again once the provider is back" || no "rename: $out"
# a user-level member (no --project) takes the provider of the project in effect, each time it is rendered; with none in effect it is refused
QARGI_PROJECT=cl "$DA" agent add ul >/dev/null 2>&1 && ok "agent add: a user-level member takes the provider of the project in effect (QARGI_PROJECT)" || no "user-level add under QARGI_PROJECT"
out=$("$DA" agent refresh ul 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'pass --project NAME' <<<"$out" && ! grep -qi claude <<<"$out"; } && ok "agent refresh: a member of no project, with no project in effect: refused, pass --project" || no "user-level refresh: rc=$rc $out"
out=$(QARGI_PROJECT=np "$DA" agent refresh ul 2>&1); refuses "agent refresh: the project in effect has no provider: refused" "$?" "$out" np
out=$(QARGI_PROJECT=cl "$DA" agent refresh ul 2>&1); rc=$?; { [ "$rc" = 0 ] && grep -q 'current' <<<"$out"; } && ok "agent refresh: the project in effect names claude" || no "user-level refresh with a project: rc=$rc $out"

# --- provision plan: the model default comes from the project's provider (the answers here name no role model)
mdl() { sed -n '/^model:/,/^[a-z]/p' "$T/s/provision/$1-build/agents/$1-build/agent.md" 2>/dev/null | tr -d '\n'; }   # the model block of the rendered agent
out=$("$DA" provision plan --project np --role build 2>&1); refuses "provision plan: no model, and the project has no provider: refused" "$?" "$out" np
grep -q 'apply' "$FAKE/ant.log" 2>/dev/null && no "ant was asked to apply" || ok "and the cloud was not asked"
out=$("$DA" provision plan --project nosuch --role build 2>&1); rc=$?
{ [ "$rc" != 0 ] && ! grep -qi claude <<<"$out"; } && ok "provision plan: a project that is not stored is refused, with no claude in the message" || no "provision plan nosuch: rc=$rc $out"
out=$("$DA" provision plan --project cl --role build 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'claude-sonnet-5-5' <<<"$(mdl cl)"; } && ok "provision plan: claude, the balanced model" || no "provision claude: rc=$rc [$(mdl cl)] $(head -5 <<<"$out")"
out=$("$DA" provision plan --project fk --role build 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'fake-m-1' <<<"$(mdl fk)"; } && ok "provision plan: the fake provider's balanced model" || no "provision fake: rc=$rc [$(mdl fk)] $(head -5 <<<"$out")"
out=$("$DA" provision plan --project np --role build --model fake-m-1 2>&1); rc=$?
[ "$rc" = 0 ] && ok "provision plan: a model given on the command line needs no provider lookup" || no "np with --model: rc=$rc $out"

# --- local prepare: a read-only role needs the project's provider for its barrier
prep() { # repo slug role
  "$DA" local prepare --repo "$1" --base main --slug "$2" --scratch "$T/scr" --role "$3" 2>&1
}
out=$(prep "$T/repo-np" rv1 review); refuses "local prepare --role review: a project with none is refused" "$?" "$out" np
[ -z "$(ls "$T/scr")" ] && ok "and no run directory was made" || no "run dir made: $(ls "$T/scr")"
git init -q -b main "$T/repo-none" && git -C "$T/repo-none" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
out=$(prep "$T/repo-none" rv2 review); rc=$?
{ [ "$rc" = 2 ] && grep -q 'no stored project has this repository' <<<"$out" && ! grep -qi claude <<<"$out"; } && ok "local prepare --role review: a repository of no project is refused" || no "repo of no project: rc=$rc $out"
out=$(prep "$T/repo-cl" rv3 review); rc=$?; { [ "$rc" = 0 ] && grep -q 'partial read-only barrier on local' <<<"$out"; } && ok "local prepare --role review: claude passes with its note" || no "review claude: rc=$rc $out"
out=$(prep "$T/repo-fk" rv4 review); rc=$?; [ "$rc" = 0 ] && ok "local prepare --role review: the fake provider passes" || no "review fake: rc=$rc $out"
out=$(prep "$T/repo-np" b1 build); rc=$?; [ "$rc" = 0 ] && ok "a write role needs no provider: prepare goes on" || no "build prepare: rc=$rc $out"

# --- the cloud starts: an instance of a read-only role (the barrier) and a session of a base (the request)
inst() { jq -n --arg d "$1" '{location:"cloud",deployment_id:$d,environment_id:"env_01",agent:{id:"agent_01",version_pinned:3,model:"x",effort:"high"}}'; }
jq -n --argjson i "$(inst depl_1)" '{"np-review":$i,"cl-review":$i,"fk-review":$i,"np-worker":$i,"cl-worker":$i,"fk-worker":$i,"np-reviewer":$i,"cl-reviewer":$i}' > "$T/c/instances.json"
: > "$FAKE/ant.log"
out=$("$DA" start np-review --asked "start the review" 2>&1); refuses "start: a read-only instance of a project with none is refused" "$?" "$out" np
out=$("$DA" start np-reviewer --role review --asked "start" 2>&1); refuses "start: a reviewer base of a project with none is refused" "$?" "$out" np
out=$(QARGI_DRY_RUN=1 "$DA" start np-worker --role build --asked "start the build base" 2>&1); refuses "start: a worker base of a project with none is refused before the request is built" "$?" "$out" np
grep -q 'sessions create\|deployments run' "$FAKE/ant.log" && no "a session was created" || ok "and no session was created"
# the session request is built by the adapter of the project's provider: claude and the fake one (the copies have the cloud overrides verified)
for p in cl fk; do
  out=$(QARGI_DRY_RUN=1 "$DA" start "$p-worker" --role build --asked "start the build base" 2>&1); rc=$?
  { [ "$rc" = 0 ] && jq -e '.agent.type == "agent_with_overrides"' <<<"$out" >/dev/null; } && ok "start: a worker base session of $p is built (dry run)" || no "start base $p: rc=$rc $(head -c 400 <<<"$out")"
done
out=$("$DA" start cl-review --asked "start the review" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept claude --surface cloud --no-barrier --project cl' <<<"$out"; } && ok "start: claude names itself in the barrier refusal (it has no cloud barrier)" || no "start claude review: rc=$rc $out"
out=$("$DA" start fk-review --asked "start the review" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept fakeprov --surface cloud --no-barrier --project fk' <<<"$out" && ! grep -qi claude <<<"$out"; } && ok "start: the fake provider's barrier refusal names it, never claude" || no "start fake review: rc=$rc $out"
out=$("$DA" start fk-worker --asked "start" 2>&1); rc=$?; [ "$rc" = 0 ] && ok "start: a worker of the fake provider starts" || no "start fake worker: rc=$rc $out"

# --- project attach and new: --provider is stored only when given, and the roles' models are the named provider's
git init -q -b main "$T/att" && git -C "$T/att" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git -C "$T/att" remote add origin https://github.com/example/att.git
out=$("$DA" project attach "$T/att" --name att 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^finding: models.provider is not set' <<<"$out"; } && ok "attach without --provider: the finding line is printed" || no "attach no provider: rc=$rc $out"
noclaude "attach without --provider names no claude" "$out"
grep -q 'after the provider is chosen' <<<"$out" && ok "and it says the models are set after the provider is chosen" || no "no 'after the provider is chosen' in: $out"
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
"$DA" project attach "$T/att" --name att --plan "$tok" --approved "go" >/dev/null 2>&1
jq -e 'has("models") | not' "$T/c/projects/att.json" >/dev/null && jq -e '[.roles[] | has("model")] | any | not' "$T/c/projects/att.json" >/dev/null && ok "attach without --provider stores no models key and no role model" || no "stored: $(jq -c '[.models, .roles]' "$T/c/projects/att.json")"
"$DA" project validate att >/dev/null 2>&1 && ok "and the stored answers validate" || no "validate att"
"$DA" project set att models.provider claude >/dev/null 2>&1 && ok "project set models.provider works on them (no role model is needed)" || no "set provider on att"
"$DA" project set att models.provider fakeprov >/dev/null 2>&1; "$DA" project validate att >/dev/null 2>&1 && ok "and a provider can be changed" || no "change provider"
rm -f "$T/c/projects/att.json"

out=$("$DA" project attach "$T/att" --name att --provider claude 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q '^finding:' <<<"$out" && grep -q '"provider": "claude"' <<<"$out"; } && ok "attach --provider claude: the plan shows it and there is no finding" || no "attach claude plan: rc=$rc $out"
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
"$DA" project attach "$T/att" --name att --provider claude --plan "$tok" --approved "go" >/dev/null 2>&1
{ [ "$(jq -r .models.provider "$T/c/projects/att.json")" = claude ] && jq -e '[.roles[].model] | all(. == "claude-sonnet-5-5")' "$T/c/projects/att.json" >/dev/null; } && ok "attach --provider claude stores models.provider and claude's models" || no "stored claude: $(jq -c '[.models, .roles]' "$T/c/projects/att.json")"
rm -f "$T/c/projects/att.json"
out=$("$DA" project attach "$T/att" --name att --provider fakeprov 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
"$DA" project attach "$T/att" --name att --provider fakeprov --plan "$tok" --approved "go" >/dev/null 2>&1
{ [ "$(jq -r .models.provider "$T/c/projects/att.json")" = fakeprov ] && jq -e '[.roles[].model] | all(. == "fake-m-1")' "$T/c/projects/att.json" >/dev/null; } && ok "attach --provider fakeprov stores it and its models" || no "stored fake: $(jq -c '[.models, .roles]' "$T/c/projects/att.json")"
noclaude "attach --provider fakeprov names no claude" "$out"
out=$("$DA" project attach "$T/att" --name att --provider nosuch 2>&1); rc=$?
{ [ "$rc" = 1 ] && grep -q "unknown provider 'nosuch'" <<<"$out"; } && ok "attach --provider with no descriptor is refused" || no "attach nosuch: rc=$rc $out"
out=$("$DA" project attach "$T/att" --name att --provider claude --force 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
[ "$?" = 0 ] && out2=$("$DA" project attach "$T/att" --name att --provider claude --force --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q "stored with the provider 'fakeprov'" <<<"$out$out2"; } && ok "attach --force --provider does not replace a stored provider" || no "force replaced: rc=$rc $out $out2"
[ "$(jq -r .models.provider "$T/c/projects/att.json")" = fakeprov ] && ok "and the stored provider is unchanged" || no "provider changed"
# a stored project with no provider: --force --provider fills it in
jq 'del(.models)' "$T/c/projects/att.json" > "$T/a.tmp" && mv "$T/a.tmp" "$T/c/projects/att.json"
out=$("$DA" project attach "$T/att" --name att --provider fakeprov --force 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
"$DA" project attach "$T/att" --name att --provider fakeprov --force --plan "$tok" --approved go >/dev/null 2>&1
[ "$(jq -r .models.provider "$T/c/projects/att.json")" = fakeprov ] && ok "attach --force --provider fills in a provider that is not set" || no "force fill: $(jq -c .models "$T/c/projects/att.json")"

# project new: the plan names the provider (or says none is chosen), a descriptor-less one is refused before anything is made
out=$("$DA" project new nw --dir "$T/nw" --provider nosuch 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ ! -e "$T/nw" ]; } && ok "new --provider with no descriptor is refused before anything is made" || no "new nosuch: rc=$rc $out"
out=$("$DA" project new nw --dir "$T/nw" --url https://github.com/example/nw 2>&1)
grep -q 'provider: not chosen' <<<"$out" && ok "new: the plan says no provider is chosen" || no "new plan: $out"
noclaude "new without --provider names no claude" "$out"
out=$("$DA" project new nw --dir "$T/nw" --url https://github.com/example/nw --provider fakeprov 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
grep -q 'provider: fakeprov' <<<"$out" && ok "new --provider: the plan names it" || no "new plan fake: $out"
"$DA" project new nw --dir "$T/nw" --url https://github.com/example/nw --plan "$tok" --approved "go" >/dev/null 2>&1 && no "a plan without the provider was approved for the other options" || ok "new: the token covers the provider"
out=$("$DA" project new nw --dir "$T/nw" --url https://github.com/example/nw --provider fakeprov --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(jq -r .models.provider "$T/c/projects/nw.json")" = fakeprov ] && ! grep -q '^finding:' <<<"$out"; } && ok "new --provider stores it with --url" || no "new stored: rc=$rc $out"
out=$("$DA" project new nx --dir "$T/nx" --url https://github.com/example/nx 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
out=$("$DA" project new nx --dir "$T/nx" --url https://github.com/example/nx --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e 'has("models") | not' "$T/c/projects/nx.json" >/dev/null && grep -q '^finding: models.provider is not set' <<<"$out"; } && ok "new without --provider stores no models key and prints the finding" || no "new no provider: rc=$rc $out"

# --- project validate: no provider skips the provider's checks (the finding stays, the exit status does not change); an unknown one is a finding
v() { jq "$1" "$T/np.json" > "$T/v.json"; "$DA" project validate "$T/v.json" 2>&1; }
out=$(v '.roles.build.model = "any-model-1"'); rc=$?
{ [ "$rc" = 0 ] && grep -q '^finding: models.provider is not set' <<<"$out"; } && ok "validate: no provider, a model id is only checked to look like one; the finding stays, exit 0" || no "validate no provider: rc=$rc $out"
out=$(v '.roles.build.model = "NOT VALID"'); rc=$?; [ "$rc" = 1 ] && ok "validate: no provider, a model that cannot be an id is still refused" || no "bad model without provider: rc=$rc $out"
noclaude "validate with no provider names no claude" "$(v '.')"
out=$(v '.models.provider = "claude" | .roles.build.model = "gpt"'); rc=$?; { [ "$rc" = 1 ] && grep -q 'claude-sonnet-5-5' <<<"$out"; } && ok "validate: claude, its pattern applies" || no "bad model with claude: rc=$rc $out"
out=$(v '.models.provider = "fakeprov" | .roles.build.model = "claude-sonnet-5-5"'); rc=$?; { [ "$rc" = 1 ] && grep -q 'fake-m-1' <<<"$out" && ! grep -qi claude <<<"$(grep -v '^roles' <<<"$out")" ; } && ok "validate: the fake provider's pattern applies, and its own example is shown" || no "bad model with the fake: rc=$rc $out"
out=$(v '.models.provider = "fakeprov" | .roles.build.model = "fake-m-1"'); rc=$?; { [ "$rc" = 0 ] && ! grep -q '^finding:' <<<"$out"; } && ok "validate: the fake provider's model is accepted" || no "good model with the fake: rc=$rc $out"
out=$(v '.models.provider = "nosuchprov"'); rc=$?
{ [ "$rc" = 0 ] && grep -q "^finding: models.provider 'nosuchprov' has no descriptor" <<<"$out"; } && ok "validate: a provider with no descriptor is a finding (exit status unchanged)" || no "unknown provider: rc=$rc $out"

# --- a provider per surface: models.provider is {local, cloud}; members run on local, instances and sessions on cloud, and a surface the
# answers leave out is refused (exit 2) only by the verbs that run on it. ob names both, ol only local, oc only cloud.
storeo() { # project models.provider-as-JSON -> stored answers like store(), with the object (or string) form given as JSON
  "$DA" project template "$1" | jq --argjson p "$2" --arg r "$T/repo-$1" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r
    | .roles.review = .roles.build | .roles.review.apt = [] | del(.roles[].model) | .models.provider = $p' > "$T/$1.json"
  "$DA" project init "$1" --answers "$T/$1.json" --force >/dev/null 2>&1 || { echo "FAIL init $1"; fail=1; }
}
for p in ob ol oc fm sa sb; do git init -q -b main "$T/repo-$p" && git -C "$T/repo-$p" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one; done
storeo ob '{"local":"fakeprov","cloud":"claude"}'; storeo ol '{"local":"fakeprov"}'; storeo oc '{"cloud":"claude"}'
jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/ob.json" >/dev/null && ok "ob is stored with a runtime for each surface" || no "ob not stored: $(jq -c .models "$T/c/projects/ob.json")"
msgs() { echo "qargi: project $1 has no $2 provider: set one with qargi project set $1 models.provider.$2 NAME"; }   # the message of a surface left out
refuses_s() { # name rc output project surface: exit 2 with the message that names the surface and the project set command
  if [ "$2" = 2 ] && [ "$3" = "$(msgs "$4" "$5")" ]; then ok "$1"; else no "$1 (rc=$2: $3)"; fi
}
# the python side and the helper
out=$(python3 -I "$TOOL/lib/provider.py" of ob --conf "$T/c" --surface local 2>&1); [ "$out" = fakeprov ] && ok "provider of --surface local: the local runtime" || no "of ob local: $out"
out=$(python3 -I "$TOOL/lib/provider.py" of ob --conf "$T/c" --surface cloud 2>&1); [ "$out" = claude ] && ok "provider of --surface cloud: the cloud runtime" || no "of ob cloud: $out"
out=$(python3 -I "$TOOL/lib/provider.py" of ob --conf "$T/c" 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider of ob --surface' <<<"$out"; } && ok "provider of with no surface: refused when the surfaces differ, and it says to name one" || no "of ob: rc=$rc $out"
( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c
  [ "$(project_provider ob local)" = fakeprov ] && [ "$(project_provider ob cloud)" = claude ] && [ "$(project_provider cl local)" = claude ] && [ "$(project_provider cl cloud)" = claude ] ) 2>/dev/null \
  && ok "project_provider PROJECT SURFACE: each surface's runtime (and a string names the same one on both)" || no "project_provider with a surface"
out=$( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c; project_provider ol cloud 2>&1 ); refuses_s "project_provider: a surface left out is refused, naming it" "$?" "$out" ol cloud
out=$( . "$TOOL/lib/lib.sh"; DA_CONF=$T/c; project_provider oc local 2>&1 ); refuses_s "project_provider: ... the local one too" "$?" "$out" oc local
# both surfaces named: the member is the local runtime's, the instance's model the cloud runtime's
"$DA" agent add mob --project ob >/dev/null 2>&1
[ "$(jq -r '.mob.model // "none"' "$T/c/agents.json")" = fake-m-1 ] && ok "ob: a member takes the local runtime's balanced model" || no "ob member model: $(jq -c .mob "$T/c/agents.json")"
out=$("$DA" agent models --project ob --json 2>&1); [ "$(jq -r .provider <<<"$out" 2>/dev/null)" = fakeprov ] && ok "ob: agent models shows the local runtime" || no "ob models: $out"
out=$("$DA" agent for build --project ob --json 2>&1); jq -e '.model_id == "fake-m-1"' <<<"$out" >/dev/null && ok "ob: agent for resolves on the local runtime" || no "ob for: $out"
out=$("$DA" provision plan --project ob --role build 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'claude-sonnet-5-5' <<<"$(mdl ob)" && ! grep -q 'fake-m-1' <<<"$(mdl ob)"; } && ok "ob: provision plan takes the cloud runtime's balanced model" || no "ob provision: rc=$rc [$(mdl ob)] $(head -3 <<<"$out")"
jq '. + {"ob-worker": .["np-worker"], "ol-worker": .["np-worker"], "ol-review": .["np-review"], "oc-worker": .["np-worker"], "oc-review": .["np-review"]}' "$T/c/instances.json" > "$T/i.tmp" && mv "$T/i.tmp" "$T/c/instances.json"
# only local named: members work, everything on the cloud surface is refused with the surface and the command
"$DA" agent add mol --project ol >/dev/null 2>&1; [ "$(jq -r '.mol.model // "none"' "$T/c/agents.json")" = fake-m-1 ] && ok "ol: a member works on the local runtime" || no "ol member: $(jq -c .mol "$T/c/agents.json")"
out=$("$DA" agent for build --project ol --json 2>&1); jq -e '.model_id == "fake-m-1"' <<<"$out" >/dev/null && ok "ol: agent for (local) works" || no "ol for: $out"
out=$("$DA" provision plan --project ol --role build 2>&1); refuses_s "ol: provision plan needs the cloud runtime and says so" "$?" "$out" ol cloud
out=$("$DA" agent for build --project ol --surface cloud 2>&1); refuses_s "ol: agent for --surface cloud is refused" "$?" "$out" ol cloud
out=$("$DA" start ol-review --asked "start" 2>&1); refuses_s "ol: start of a read-only instance is refused" "$?" "$out" ol cloud
out=$(QARGI_DRY_RUN=1 "$DA" start ol-worker --role build --asked "start" 2>&1); refuses_s "ol: start of a base is refused" "$?" "$out" ol cloud
# only cloud named: the cloud verbs work, members and the local barrier are refused
out=$("$DA" agent add moc --project oc 2>&1); refuses_s "oc: agent add needs the local runtime and says so" "$?" "$out" oc local
out=$("$DA" agent models --project oc 2>&1); refuses_s "oc: agent models is refused" "$?" "$out" oc local
out=$(prep "$T/repo-oc" rv5 review); refuses_s "oc: local prepare --role review is refused (the local barrier)" "$?" "$out" oc local
out=$(prep "$T/repo-oc" b2 build); [ "$?" = 0 ] && ok "oc: a write role needs no provider: prepare goes on" || no "oc build prepare: $out"
out=$("$DA" provision plan --project oc --role build 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'claude-sonnet-5-5' <<<"$(mdl oc)"; } && ok "oc: provision plan works on the cloud runtime" || no "oc provision: rc=$rc [$(mdl oc)] $(head -3 <<<"$out")"
out=$(QARGI_DRY_RUN=1 "$DA" start oc-worker --role build --asked "start" 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.agent.type == "agent_with_overrides"' <<<"$out" >/dev/null; } && ok "oc: a base session is built on the cloud runtime" || no "oc start: rc=$rc $(head -c 300 <<<"$out")"
out=$(QARGI_DRY_RUN=1 "$DA" start ob-worker --role build --asked "start" 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.agent.type == "agent_with_overrides"' <<<"$out" >/dev/null; } && ok "ob: a base session is built on the cloud runtime (claude), not the local one" || no "ob start: rc=$rc $(head -c 300 <<<"$out")"

# a single name that resolves through its family says so (stderr), per surface; the runtimes here are in the library
LIB=$T/c/packs/providers; mkdir -p "$LIB/fam-cli" "$LIB/fam-hosted"
rt() { jq -n --arg n "$1" --arg s "$2" '{schema:2, kind:"provider", provider:$n, family:"fam", surface:$s,
  models:{pattern:"^.+$", tiers:{"*":{model:"fam-model", alias:null, verified_on:null, source:"test"}}, effort:null},
  dispatch:{mode:"command", argv:[$n, "run", "--model", "{model}"], prompt:{via:"stdin"}, cwd:"{clone}", output:{format:"text"}},
  agents:null, resources:{}, barrier:{kind:"none"}}'; }
rt fam-cli local > "$LIB/fam-cli/definition.json"; rt fam-hosted cloud > "$LIB/fam-hosted/definition.json"
storeo fm '"fam"'
jq -e '.models.provider == "fam"' "$T/c/projects/fm.json" >/dev/null && ok "fm is stored with the family name (a string)" || no "fm not stored: $(jq -c .models "$T/c/projects/fm.json" 2>&1)"
out=$(python3 -I "$TOOL/lib/provider.py" of fm --conf "$T/c" --surface local 2>"$T/err"); rc=$?
{ [ "$rc" = 0 ] && [ "$out" = fam-cli ] && grep -q "models.provider is the single name 'fam'; on the local surface it resolves to fam-cli through the family" "$T/err" && grep -q 'qargi project set fm models.provider.local fam-cli' "$T/err"; } \
  && ok "a family name: the runtime of the surface, and the notice says what to set" || no "of fm local: rc=$rc $out $(cat "$T/err")"
out=$(python3 -I "$TOOL/lib/provider.py" of fm --conf "$T/c" --surface cloud 2>/dev/null); [ "$out" = fam-hosted ] && ok "and the family has another runtime on the other surface" || no "of fm cloud: $out"
out=$(prep "$T/repo-fm" rv6 review); rc=$?
{ [ "$rc" = 2 ] && grep -q "resolves to fam-cli through the family" <<<"$out" && grep -q 'qargi provider accept fam-cli --surface local --no-barrier --project fm' <<<"$out"; } \
  && ok "a verb on a string family name works on the runtime and prints the notice (here the barrier is refused for it)" || no "fm prepare: rc=$rc $out"
out=$("$DA" project validate fm 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^finding: models.provider is the single name 'fam'" <<<"$out" && ! grep -q 'no descriptor' <<<"$out"; } && ok "project validate: the string family name is a finding with the notice, not an error" || no "validate fm: rc=$rc $out"
out=$("$DA" project validate cl 2>&1); [ "$out" = ok ] && ok "project validate: a runtime name that serves both surfaces has no finding" || no "validate cl: $out"

# project set: models.provider.local|cloud writes one surface of the object
storeo sa '{}'; jq 'del(.models)' "$T/c/projects/sa.json" > "$T/sa.tmp" && mv "$T/sa.tmp" "$T/c/projects/sa.json"
out=$("$DA" project set sa models.provider.local fakeprov 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider == {"local":"fakeprov"}' "$T/c/projects/sa.json" >/dev/null && grep -q '^finding: models.provider.cloud is not set' <<<"$out" && grep -q 'qargi project set sa models.provider.cloud NAME' <<<"$out"; } \
  && ok "project set models.provider.local on a project with none writes the object and names what is left" || no "set local: rc=$rc $out $(jq -c .models "$T/c/projects/sa.json")"
out=$("$DA" project set sa models.provider.cloud claude 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/sa.json" >/dev/null && ! grep -q '^finding' <<<"$out"; } && ok "project set models.provider.cloud completes it, with no finding" || no "set cloud: rc=$rc $out"
out=$("$DA" agent add msa --project sa 2>&1); [ "$(jq -r .msa.model "$T/c/agents.json")" = fake-m-1 ] && ok "and the verbs work on it" || no "agent add on sa: $out"
storeo sb '"claude"'
out=$("$DA" project set sb models.provider.local fakeprov 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/sb.json" >/dev/null && grep -q "was the single name 'claude'" <<<"$out"; } \
  && ok "project set models.provider.local on a string: the object is made, the other surface keeps the old name, and the note says so" || no "set on string: rc=$rc $out $(jq -c .models "$T/c/projects/sb.json")"
out=$("$DA" project set sb models.provider.moon claude 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'models.provider.moon: not a surface (local, cloud)' <<<"$out" && jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/sb.json" >/dev/null; } && ok "project set: a key that is not a surface is refused and nothing changed" || no "set moon: rc=$rc $out"
out=$("$DA" project set sb models.provider.cloud 5 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'models.provider.cloud: a provider or family name' <<<"$out"; } && ok "project set: a surface value that is not a name is refused" || no "set 5: rc=$rc $out"
out=$("$DA" project set sb models.provider.cloud nosuchprov 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q "^finding: models.provider.cloud 'nosuchprov' cannot be used" <<<"$out"; } && ok "project set: a name with no definition is stored with a finding (as for the string form)" || no "set nosuch: rc=$rc $out"
# a runtime that exists but does not serve the surface is refused (exit 2, nothing changed), as attach and new refuse it; the unset case and an
# unknown name keep their finding
cp "$T/c/projects/sb.json" "$T/sb.before"
out=$("$DA" project set sb models.provider.cloud claude-code 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'claude-code does not serve the cloud surface (it serves local)' <<<"$out" && grep -q 'models.provider.cloud' <<<"$out" && cmp -s "$T/sb.before" "$T/c/projects/sb.json"; } \
  && ok "project set: a runtime that does not serve the surface is refused, exit 2, nothing changed" || no "set claude-code on cloud: rc=$rc $out"
out=$("$DA" project set sb models.provider.local claude-platform 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'claude-platform does not serve the local surface (it serves cloud)' <<<"$out" && cmp -s "$T/sb.before" "$T/c/projects/sb.json"; } \
  && ok "project set: the same on the local surface" || no "set claude-platform on local: rc=$rc $out"
storeo sc '"claude-code"'; cp "$T/c/projects/sc.json" "$T/sc.before"
out=$("$DA" project set sc models.provider.cloud claude-code 2>&1); rc=$?
{ [ "$rc" = 2 ] && cmp -s "$T/sc.before" "$T/c/projects/sc.json" && ! grep -q 'was the single name' <<<"$out"; } \
  && ok "project set: refused before a single name is turned into the object" || no "set on string: rc=$rc $out"
out=$("$DA" project set sc models.provider.local claude-code 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider.local == "claude-code"' "$T/c/projects/sc.json" >/dev/null; } && ok "project set: a runtime that serves the surface is stored" || no "set claude-code on local: rc=$rc $out"
out=$("$DA" project set sc models.provider.cloud 2>&1); rc=$?; [ "$rc" != 0 ] && ok "project set: a surface with no value is still refused" || no "set no value: rc=$rc $out"

# project validate: the model ids of the roles are checked against the runtimes of the surfaces named
vo() { jq "$1" "$T/ob.json" > "$T/v.json"; "$DA" project validate "$T/v.json" 2>&1; }
out=$(vo '.roles.build.model = "fake-m-1"'); rc=$?; [ "$rc" = 0 ] && ok "validate: a model of the local runtime is accepted" || no "validate ob fake: rc=$rc $out"
out=$(vo '.roles.build.model = "claude-sonnet-5-5"'); rc=$?; [ "$rc" = 0 ] && ok "validate: a model of the cloud runtime is accepted" || no "validate ob claude: rc=$rc $out"
out=$(vo '.roles.build.model = "gpt"'); rc=$?; { [ "$rc" = 1 ] && grep -q 'fake-m-1' <<<"$out" && grep -q 'claude-sonnet-5-5' <<<"$out"; } && ok "validate: a model neither accepts is refused, with the example of each" || no "validate ob gpt: rc=$rc $out"
out=$(vo '.models.provider = {"local": "fakeprov", "moon": "claude"}'); rc=$?; { [ "$rc" = 1 ] && grep -q 'models.provider.moon: not a surface' <<<"$out"; } && ok "validate: an unknown surface key is an error" || no "validate moon: rc=$rc $out"
out=$(vo '.models.provider = {"local": "fakeprov"}'); rc=$?
{ [ "$rc" = 0 ] && grep -q '^finding: models.provider.cloud is not set' <<<"$out" && ! grep -q 'models.provider.local is not set' <<<"$out"; } && ok "validate: one surface left out is a finding for that surface only (exit 0)" || no "validate one surface: rc=$rc $out"
out=$(vo '.models.provider = {}'); rc=$?; { [ "$rc" = 0 ] && grep -q '^finding: models.provider is not set' <<<"$out"; } && ok "validate: an empty object is the same as none" || no "validate empty object: rc=$rc $out"

# project attach and new: --provider is one name for both surfaces; --provider-local and --provider-cloud are the object form
git init -q -b main "$T/att2" && git -C "$T/att2" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git -C "$T/att2" remote add origin https://github.com/example/att2.git
plan_of() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; }
out=$("$DA" project attach "$T/att2" --name att2 --provider-local fakeprov --provider-cloud claude 2>&1); rc=$?
{ [ "$rc" = 0 ] && ! grep -q '^finding:' <<<"$out" && grep -q '"cloud": "claude"' <<<"$out" && grep -q '"local": "fakeprov"' <<<"$out"; } && ok "attach --provider-local and --provider-cloud: the plan shows the object, no finding" || no "attach object plan: rc=$rc $out"
tok=$(plan_of "$out")
"$DA" project attach "$T/att2" --name att2 --provider-local fakeprov --provider-cloud claude --plan "$tok" --approved go >/dev/null 2>&1
jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/att2.json" >/dev/null && ok "and it is stored as the object" || no "stored att2: $(jq -c .models "$T/c/projects/att2.json" 2>&1)"
jq -e '[.roles[].model] | all(. == null)' "$T/c/projects/att2.json" >/dev/null && ok "(the runtimes disagree on the balanced model, so no role model is stored)" || no "role models: $(jq -c '[.roles[].model]' "$T/c/projects/att2.json")"
rm -f "$T/c/projects/att2.json"
out=$("$DA" project attach "$T/att2" --name att2 --provider-local claude 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^finding: models.provider.cloud is not set' <<<"$out" && grep -q '^  - models.provider.cloud: no cloud provider was named' <<<"$out" && grep -q '"local": "claude"' <<<"$out"; } \
  && ok "attach --provider-local alone: the cloud surface is a question and a finding" || no "attach local only: rc=$rc $out"
jq -e . /dev/null; out=$("$DA" project attach "$T/att2" --name att2 --provider claude --provider-local claude 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'not both' <<<"$out"; } && ok "attach: --provider with --provider-local is refused" || no "attach both forms: rc=$rc $out"
out=$("$DA" project attach "$T/att2" --name att2 --provider-cloud nosuch 2>&1); rc=$?; [ "$rc" != 0 ] && ok "attach --provider-cloud with no such runtime or family is refused" || no "attach nosuch cloud: rc=$rc $out"
# a stored project: the object options fill the surfaces not set, and never replace one that is
cp "$T/c/projects/ol.json" "$T/ol.keep"
out=$("$DA" project attach "$T/repo-ol" --name ol --provider-cloud claude --force 2>&1); tok=$(plan_of "$out")
out2=$("$DA" project attach "$T/repo-ol" --name ol --provider-cloud claude --force --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/ol.json" >/dev/null; } && ok "attach --force --provider-cloud fills the surface that is not set and keeps the other" || no "force fill surface: rc=$rc $out2 $(jq -c .models "$T/c/projects/ol.json")"
out=$("$DA" project attach "$T/repo-ol" --name ol --provider-cloud fakeprov --force 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'a provider per surface' <<<"$out"; } && ok "attach --force --provider-cloud does not replace a surface that is set" || no "force replace surface: rc=$rc $out"
out=$("$DA" project attach "$T/repo-ol" --name ol --provider claude --force 2>&1); rc=$?
{ [ "$rc" != 0 ] && grep -q 'a provider per surface' <<<"$out"; } && ok "attach --force --provider does not replace the object either" || no "force string over object: rc=$rc $out"
cp "$T/ol.keep" "$T/c/projects/ol.json"
out=$("$DA" project new nq --dir "$T/nq" --url https://github.com/example/nq --provider-local fakeprov --provider-cloud claude 2>&1); tok=$(plan_of "$out")
grep -q 'provider: local fakeprov, cloud claude' <<<"$out" && ok "new --provider-local --provider-cloud: the plan names both" || no "new object plan: $out"
out=$("$DA" project new nq --dir "$T/nq" --url https://github.com/example/nq --provider-local fakeprov --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" != 0 ] && [ ! -e "$T/nq" ]; } && ok "new: the token covers each surface" || no "new token: rc=$rc $out"
out=$("$DA" project new nq --dir "$T/nq" --url https://github.com/example/nq --provider-local fakeprov --provider-cloud claude --plan "$tok" --approved go 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.models.provider == {"local":"fakeprov","cloud":"claude"}' "$T/c/projects/nq.json" >/dev/null; } && ok "new stores the object with --url" || no "new object: rc=$rc $out"
out=$("$DA" project new nr --dir "$T/nr" --provider-local nosuch 2>&1); rc=$?
{ [ "$rc" = 1 ] && [ ! -e "$T/nr" ]; } && ok "new --provider-local with no such runtime is refused before anything is made" || no "new nosuch local: rc=$rc $out"
out=$("$DA" project new nr --dir "$T/nr" --provider claude --provider-cloud claude 2>&1); rc=$?
{ [ "$rc" != 0 ] && [ ! -e "$T/nr" ]; } && ok "new: --provider with --provider-cloud is refused" || no "new both forms: rc=$rc $out"

# --- no fallback to claude is written in the code (the claude adapter, its shim and its descriptor are the only places that name it)
hits=$(grep -nE '// *"claude"|default claude|load\("claude"\)|\.get\([^)]*"claude"\)|p=claude|_prov=claude|:-claude\}' lib/*.sh lib/*.py bin/qargi 2>/dev/null | grep -vE '^lib/(packs_claude\.py|guard\.py):')
[ -z "$hits" ] && ok "no fallback to claude in lib/*.sh, lib/*.py or bin/qargi" || no "a fallback to claude is written: $hits"
# the check itself finds each form (a self-test with the forbidden strings built here, so this file is not a hit)
f=$T/forbidden.sh; q='"'
{ echo "x=\$(jq -r '.models.provider // ${q}claude${q}' f)"; echo "# the default claude"; echo "PV.load(${q}claude${q})"; echo 'p=claude'; } > "$f"
[ "$(grep -cE '// *"claude"|default claude|load\("claude"\)|p=claude' "$f")" = 4 ] && ok "the grep finds each form it is for" || no "the grep misses a form"

[ "$fail" = 0 ] && echo "no-default-provider tests passed" || { echo "no-default-provider tests FAILED"; exit 1; }
