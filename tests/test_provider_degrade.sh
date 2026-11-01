#!/usr/bin/env bash
# How qargi degrades on a provider that cannot do something: a surface with no read-only barrier refuses read-only roles until
# the project records `qargi provider accept`; a provider with no effort control drops effort; one that cannot override the model
# per dispatch refuses a profile whose model is not the member's. Hermetic: a copy of the tool in a temporary root holds the
# fake providers (nobarrier, nomodel), so the shipped descriptors are never changed. Offline. Run: tests/test_provider_degrade.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T FAKE=$T/fake
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

# the tool, copied: the fake providers live in the copy only
TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
DA=$TOOL/bin/qargi
# nobarrier: no read-only barrier on either surface, no effort control. nomodel: claude, but the model cannot be set per dispatch.
jq '.provider = "nobarrier" | .effort |= map_values(null)
  | .capabilities.read_only_barrier[] |= (.value = "no" | .note = "nothing stops a write")' \
  "$SRC/lib/providers/claude.json" > "$TOOL/lib/providers/nobarrier.json"
jq '.provider = "nomodel" | .capabilities.per_dispatch_model_override.local |= (.value = "no" | .note = "one model per agent")' \
  "$SRC/lib/providers/claude.json" > "$TOOL/lib/providers/nomodel.json"
python3 -I "$TOOL/lib/provider.py" check nobarrier >/dev/null && python3 -I "$TOOL/lib/provider.py" check nomodel >/dev/null && ok "the fake descriptors are valid" || no "fake descriptors"

# the ant fake: logs its calls, logged in, answers a deployment run with a session id, everything else with nothing
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
case $1 in
  beta:deployments) if [ "${2:-}" = run ]; then echo '{"session_id":"sesn_1"}'; else echo '{}'; fi;;
  beta:sessions) echo '{"status":"idle","budget":{"max_list_cost":{"amount":"500"}}}';;
esac
exit 0
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

# three projects, each with a repository: alpha on nobarrier, beta on nomodel, gamma on claude
for p in alpha beta gamma; do git init -q -b main "$T/repo-$p" && git -C "$T/repo-$p" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one; done
store() { # project provider -> stored answers: roles build and review, the repository above
  "$DA" project template "$1" | jq --arg p "$2" --arg r "$T/repo-$1" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r
    | .roles.review = .roles.build | .roles.review.apt = [] | .models.provider = $p' > "$T/$1.json"
  "$DA" project init "$1" --answers "$T/$1.json" --force >/dev/null 2>&1 || { echo "FAIL init $1"; fail=1; }
}
store alpha nobarrier; store beta nomodel; store gamma claude
acc() { jq -c '.models.accept_no_barrier // {}' "$T/c/projects/${1:-alpha}.json"; }
audit() { local n; n=$(grep -c "provider:accept" "$T/s/audit.log" 2>/dev/null); echo "${n:-0}"; }

# --- provider accept: validation, plan, token, apply
ACCEPT=("$DA" provider accept nobarrier --surface cloud --no-barrier --project alpha)
out=$("${ACCEPT[@]}" --asked "review on cloud is fine for this repo" 2>&1); rc=$?
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
{ [ "$rc" = 0 ] && [ -n "$tok" ] && grep -q 'models.accept_no_barrier.cloud' <<<"$out" && [ "$(acc)" = '{}' ] && [ "$(audit)" = 0 ]; } \
  && ok "without --plan and --approved it prints what would be recorded and a token, and changes nothing" || no "plan: rc=$rc $out"
"${ACCEPT[@]}" --asked "review on cloud is fine for this repo" --plan wrong --approved "go" >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong token is refused"
"${ACCEPT[@]}" --asked "something else" --plan "$tok" --approved "go" >/dev/null 2>&1 && no "a token of another --asked was accepted" || ok "the token covers the words asked"
[ "$(acc)" = '{}' ] && ok "a refused apply records nothing" || no "recorded after a refusal: $(acc)"
"${ACCEPT[@]}" --plan "$tok" --approved "go" >/dev/null 2>&1 && no "accepted without --asked" || ok "--asked is required"
"$DA" provider accept nobarrier --surface cloud --project alpha --asked x >/dev/null 2>&1 && no "accepted without --no-barrier" || ok "--no-barrier is required"
"$DA" provider accept nope --surface cloud --no-barrier --project alpha --asked x >/dev/null 2>&1 && no "an unknown provider was accepted" || ok "an unknown provider is refused"
"$DA" provider accept nobarrier --surface moon --no-barrier --project alpha --asked x >/dev/null 2>&1 && no "an unknown surface was accepted" || ok "an unknown surface is refused"
"$DA" provider accept nobarrier --surface cloud --no-barrier --project nosuch --asked x >/dev/null 2>&1 && no "a project without answers was accepted" || ok "a project without stored answers is refused"
out=$("$DA" provider accept claude --surface local --no-barrier --project alpha --asked x 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'nothing to accept' <<<"$out" && [ "$(acc)" = '{}' ]; } && ok "a surface with a barrier (partial counts) has nothing to accept: exit 0, nothing recorded" || no "nothing to accept: rc=$rc $out"
out=$("${ACCEPT[@]}" --asked "review on cloud is fine for this repo" --plan "$tok" --approved "go ahead" 2>&1); rc=$?
{ [ "$rc" = 0 ] && jq -e '.cloud | .by == "'"$(id -un)"'" and (.at | test("^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$")) and .reason == "review on cloud is fine for this repo" and (keys == ["at","by","reason"])' <<<"$(acc)" >/dev/null; } \
  && ok "applied: models.accept_no_barrier.cloud = {by, at, reason} with the words asked" || no "apply: rc=$rc $out $(acc)"
{ [ "$(audit)" = 1 ] && tail -1 "$T/s/audit.log" | jq -e '.verb == "provider:accept" and .approved == "go ahead" and .asked == "review on cloud is fine for this repo" and (.detail | test("nobarrier cloud alpha"))' >/dev/null; } \
  && ok "and one audit line says who asked and what was approved" || no "audit: $(tail -2 "$T/s/audit.log")"
"$DA" project validate alpha >/dev/null 2>&1 && ok "the answers stay valid for project validate" || no "validate after accept"
out=$("${ACCEPT[@]}" --asked "again" 2>&1); [ $? = 0 ] && grep -q 'accepted this already' <<<"$out" && [ "$(audit)" = 1 ] && ok "accepting again says so and records nothing more" || no "again: $out"
[ "$(acc beta)" = '{}' ] && [ "$(jq -r '.models.provider' "$T/c/projects/alpha.json")" = nobarrier ] && ok "other answers and other projects are untouched" || no "collateral"
# put alpha back for the refusals below
store alpha nobarrier

# --- the helper: require-barrier
rb() { python3 -I "$TOOL/lib/provider.py" require-barrier "$@"; }
out=$(rb nobarrier cloud --project alpha 2>&1); rc=$?
{ [ "$rc" = 2 ] && grep -q 'qargi provider accept nobarrier --surface cloud --no-barrier --project alpha --asked' <<<"$out"; } && ok "require-barrier: exit 2 and the exact accept command" || no "require-barrier refusal: rc=$rc $out"
out=$(rb claude local 2>&1); rc=$?
{ [ "$rc" = 0 ] && [ "$(grep -c 'partial read-only barrier' <<<"$out")" = 1 ]; } && ok "a partial barrier passes and prints its note once" || no "partial: rc=$rc $out"
[ -z "$(rb claude cloud --project gamma 2>&1)" ] && no "claude cloud passed with nothing accepted" || ok "claude on cloud is refused until accepted"

# --- the four enforcement points: refused until accepted, each surface on its own
refused() { # name rc output: the exit was 2 and the message carries the accept command for the surface
  [ "$2" = 2 ] && grep -q "qargi provider accept $4 --surface $5 --no-barrier --project $6 --asked" <<<"$3" && ok "$1" || no "$1 (rc=$2: $3)"
}
# 1. qargi agent add: a member that only reviews is read-only, on the local surface
out=$("$DA" agent add judge --abilities review --project alpha 2>&1); rc=$?
refused "agent add: a reviewing member is refused where local has no barrier" "$rc" "$out" nobarrier local alpha
{ [ "$(jq 'has("judge")' "$T/c/agents.json")" = false ] && [ ! -e "$T/repo-alpha/.claude/agents/judge.md" ]; } && ok "and nothing was made" || no "judge was made"
"$DA" agent add forge --abilities build,review --project alpha >/dev/null 2>&1 && ok "a member that can write is not a read-only role: allowed" || no "forge refused"
"$DA" agent add reviewer --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "the reviewer base is read-only too" || no "reviewer base"
out=$("$DA" agent add gjudge --abilities review --project gamma 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'partial read-only barrier on local' <<<"$out"; } && ok "claude local: a partial barrier passes and prints its note" || no "claude local: rc=$rc $out"
# 2. provision: the plan of a read-only role, cloud
out=$("$DA" provision plan --project alpha --role review 2>&1); rc=$?
refused "provision plan: a read-only role is refused where cloud has no barrier" "$rc" "$out" nobarrier cloud alpha
grep -q 'apply' "$FAKE/ant.log" 2>/dev/null && no "ant was called" || ok "and the cloud was not asked"
"$DA" provision plan --project alpha --role build >/dev/null 2>&1 && ok "a write role provisions as before" || no "build plan refused"
out=$("$DA" provision plan --project gamma --role review 2>&1); rc=$?
refused "provision plan: claude has no cloud barrier either" "$rc" "$out" claude cloud gamma
out=$("$DA" provision apply --project alpha --role review --asked "x" --approved "y" --plan z 2>&1); rc=$?
refused "provision apply is refused too" "$rc" "$out" nobarrier cloud alpha
# 3. session start and send --new, for an instance whose role is read-only
jq -n '{"alpha-review":{location:"cloud",deployment_id:"depl_R",environment_id:"env_1",agent:{id:"agent_R",version_pinned:1}},
  "alpha-build":{location:"cloud",deployment_id:"depl_B",environment_id:"env_1",agent:{id:"agent_B",version_pinned:1}},
  "gamma-review":{location:"cloud",deployment_id:"depl_G",environment_id:"env_1",agent:{id:"agent_G",version_pinned:1}}}' > "$T/c/instances.json"
: > "$FAKE/ant.log"
out=$("$DA" start alpha-review --asked "start the review" 2>&1); rc=$?
refused "start: a read-only instance is refused" "$rc" "$out" nobarrier cloud alpha
out=$("$DA" send alpha-review "review it" --label rv --new --asked "review it" 2>&1); rc=$?
refused "send --new is refused too" "$rc" "$out" nobarrier cloud alpha
out=$("$DA" start gamma-review --asked "start the review" 2>&1); rc=$?
refused "claude cloud is refused until accepted" "$rc" "$out" claude cloud gamma
grep -q 'deployments run' "$FAKE/ant.log" && no "a session was created" || ok "and no session was created"
"$DA" start alpha-build --asked "build" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_B' "$FAKE/ant.log" && ok "a write instance starts as before" || no "build start"
# 4. local prepare: the role's class is read-only, local
mkdir -p "$T/scr"
out=$("$DA" local prepare --repo "$T/repo-alpha" --base main --slug rv1 --scratch "$T/scr" --role review 2>&1); rc=$?
refused "local prepare: a read-only role is refused where local has no barrier" "$rc" "$out" nobarrier local alpha
[ -z "$(ls "$T/scr")" ] && ok "and no run directory was made" || no "run dir made: $(ls "$T/scr")"
"$DA" local prepare --repo "$T/repo-alpha" --base main --slug b1 --scratch "$T/scr" --role build >/dev/null 2>&1 && ok "a write role prepares as before" || no "build prepare refused"
out=$("$DA" local prepare --repo "$T/repo-gamma" --base main --slug rv2 --scratch "$T/scr" --role review 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q 'partial read-only barrier on local' <<<"$out"; } && ok "claude local: prepare passes with the note" || no "claude prepare: rc=$rc $out"

# --- after provider accept: allowed, on that surface only
acceptp() { # surface -> accept alpha's nobarrier on the surface through the plan
  local t; t=$("$DA" provider accept nobarrier --surface "$1" --no-barrier --project alpha --asked "I accept $1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
  "$DA" provider accept nobarrier --surface "$1" --no-barrier --project alpha --asked "I accept $1" --plan "$t" --approved "go" >/dev/null
}
acceptp cloud
"$DA" provision plan --project alpha --role review >/dev/null 2>&1 && ok "cloud accepted: the read-only role provisions" || no "provision after accept"
: > "$FAKE/ant.log"
"$DA" start alpha-review --asked "start the review" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_R' "$FAKE/ant.log" && ok "cloud accepted: the read-only instance starts" || no "start after accept"
"$DA" send alpha-review "review it" --label rv --new --asked "review it" >/dev/null 2>&1; [ "$(grep -c 'deployments run --deployment-id depl_R' "$FAKE/ant.log")" = 2 ] && ok "cloud accepted: send --new starts one" || no "send --new after accept"
"$DA" agent add judge --abilities review --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "the cloud acceptance does not cover local" || no "local covered by cloud"
"$DA" local prepare --repo "$T/repo-alpha" --base main --slug rv3 --scratch "$T/scr" --role review >/dev/null 2>&1; [ $? = 2 ] && ok "prepare is still refused on local" || no "prepare after cloud accept"
acceptp local
"$DA" agent add judge --abilities review --project alpha >/dev/null 2>&1 && jq -e 'has("judge")' "$T/c/agents.json" >/dev/null && ok "local accepted: the reviewing member is added" || no "agent add after accept"
out=$("$DA" local prepare --repo "$T/repo-alpha" --base main --slug rv3 --scratch "$T/scr" --role review 2>&1); rc=$?
{ [ "$rc" = 0 ] && grep -q '^CLASS=read-only' <<<"$out"; } && ok "local accepted: prepare makes the read-only run" || no "prepare after accept: rc=$rc $out"
[ "$(audit)" = 3 ] && ok "each acceptance left its audit line (the first section made one)" || no "audit count $(audit)"

exit $fail
