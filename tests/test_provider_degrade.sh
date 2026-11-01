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
for d in bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
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
case $1:${2:-} in
  beta:deployments) [ "${2:-}" = run ] && echo '{"session_id":"sesn_1"}' || echo '{}';;
  beta:sessions) echo '{"status":"idle","budget":{"max_list_cost":{"amount":"500"}}}';;
esac
exit 0
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

# a repository, and three projects: alpha on nobarrier, beta on nomodel, gamma on claude
git init -q -b main "$T/repo" && git -C "$T/repo" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
store() { # project provider -> stored answers: roles build and review, the repository above
  "$DA" project template "$1" | jq --arg p "$2" --arg r "$T/repo" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r
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

exit $fail
