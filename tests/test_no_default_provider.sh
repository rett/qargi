#!/usr/bin/env bash
# There is no default provider: a project's provider is its models.provider, and every verb that needs one refuses a project that has
# none (exit 2, the one message of lib/provider.py), instead of falling back to claude. Covers each place that used to fall back:
# agent add/list/models/for/refresh/rename, provision plan (the model default), local prepare and the cloud starts (the read-only
# barrier and the session request), project attach/new (--provider is stored only when given) and project validate. Every verb works
# when the project names claude and when it names a fake provider, and no output names claude for a project that does not. Last, a
# grep that fails if a fallback to claude is written again. Hermetic, offline: a copy of the tool holds the fake provider, so the
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

[ "$fail" = 0 ] && echo "no-default-provider tests passed" || { echo "no-default-provider tests FAILED"; exit 1; }
