#!/usr/bin/env bash
# qargi agent for ROLE --surface cloud --project PROJ: which cloud instance runs a profile, from the instance registry. The base
# instance (<project>-worker or <project>-reviewer) takes the session's model and effort as overrides, so it is used only when the
# provider's per_dispatch_model_override (and per_dispatch_effort_override, when an effort is asked) is verified yes; otherwise the
# legacy role instance (<project>-build ...) runs, and only with the model it was provisioned with. Hermetic: a copy of the tool in
# a temporary root holds the descriptors with the capabilities verified, so the shipped claude.json is never changed. Offline.
# Run: tests/test_agent_cloud.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

# the tool, copied: the verified descriptors live in the copy only. claude: both overrides verified. effunver: the model override
# verified, the effort override not. The shipped tool (SHIP) has neither verified, as in the checkout.
TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
SHIP=$SRC/bin/qargi; YES=$TOOL/bin/qargi
jq '.capabilities.per_dispatch_model_override.cloud |= (.verified_on = "2026-10-31")
  | .capabilities.per_dispatch_effort_override.cloud |= (.verified_on = "2026-10-31")' "$SRC/lib/providers/claude.json" > "$T/claude.json" && mv "$T/claude.json" "$TOOL/lib/providers/claude.json"
jq '.provider = "effunver" | .capabilities.per_dispatch_effort_override.cloud |= (.verified_on = null)' "$TOOL/lib/providers/claude.json" > "$TOOL/lib/providers/effunver.json"
python3 -I "$TOOL/lib/provider.py" check claude >/dev/null && python3 -I "$TOOL/lib/provider.py" check effunver >/dev/null && ok "the verified descriptors are valid" || no "descriptors"
[ "$(python3 -I "$SRC/lib/provider.py" effective claude cloud per_dispatch_model_override)" = no ] && ok "shipped: the cloud model override counts as no (unverified)" || no "shipped capability"
[ "$(python3 -I "$TOOL/lib/provider.py" effective claude cloud per_dispatch_model_override)" = yes ] && [ "$(python3 -I "$TOOL/lib/provider.py" effective effunver cloud per_dispatch_effort_override)" = no ] && ok "the copy: model yes, and effort no for effunver" || no "copy capability"

# the projects: alpha has a base pair and the legacy instances, beta only the legacy ones, gamma only a worker, delta nothing
for p in alpha beta gamma delta epsilon; do
  jq -n --arg p "$p" '{schema:1,project:$p,repo:{url:"https://github.com/example/\($p)",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},memory:{},budget_cents:500}' > "$T/c/projects/$p.json"
done
jq '.models = {provider: "effunver"}' "$T/c/projects/epsilon.json" > "$T/e.json" && mv "$T/e.json" "$T/c/projects/epsilon.json"
inst() { # name model effort -> one cloud instance record
  jq -n --arg m "$2" --arg e "$3" '{location:"cloud",deployment_id:"depl_x",environment_id:"env_1",agent:{id:"agent_x",version_pinned:1,model:$m,effort:$e}}'; }
S=claude-sonnet-5-5; O=claude-opus-5-5; H=claude-haiku-5-5; F=claude-fable-5-1
jq -n --argjson aw "$(inst x $S high)" --argjson ar "$(inst x $O high)" --argjson b "$(inst x $S high)" --argjson r "$(inst x $O high)" --argjson l "$(inst x $S high)" '{
  "alpha-worker": $aw, "alpha-reviewer": $ar, "alpha-build": $b, "alpha-review": $r,
  "beta-build": $b, "beta-review": $r, "beta-test": $l,
  "gamma-worker": $aw,
  "epsilon-worker": $aw, "epsilon-build": $b,
  "delta-build": {location:"local",local:{agent_file:"/nonexistent/a.md",sha256:"x",model:"sonnet",effort:null}}}' > "$T/c/instances.json"
cl() { "$1" agent for "${@:2}" --surface cloud 2>&1; }       # tool, role [options]: stdout and stderr
cj() { "$1" agent for "${@:2}" --surface cloud --json 2>/dev/null; }

# --- the verified provider: the base instance wins
[ "$(cl "$YES" build --project alpha)" = "alpha-worker $S high build" ] && ok "verified: the worker base, the profile's model id and effort" || no "worker: $(cl "$YES" build --project alpha)"
cj "$YES" build --project alpha | jq -e '.instance == "alpha-worker" and .base == "worker" and .legacy == false and .model == "claude-sonnet-5-5" and .effort == "high" and .profile == "build" and .class == "write"' >/dev/null && ok "--json: instance, base, legacy, model, effort, profile, class" || no "json: $(cj "$YES" build --project alpha)"
[ "$(cl "$YES" test --project alpha)" = "alpha-worker $S low test" ] && [ "$(cl "$YES" write --project alpha)" = "alpha-worker $S medium write" ] && ok "every write profile maps to the worker" || no "test/write: $(cl "$YES" test --project alpha)"
[ "$(cl "$YES" review --project alpha)" = "alpha-reviewer $O high review" ] && [ "$(cl "$YES" review --profile auditor --project alpha)" = "alpha-reviewer $H low auditor" ] && [ "$(cl "$YES" review --profile advisor --project alpha)" = "alpha-reviewer $O high advisor" ] && ok "reviewer profiles map to the reviewer base, each with its own model" || no "reviewer: $(cl "$YES" review --profile auditor --project alpha)"
cj "$YES" review --project alpha | jq -e '.instance == "alpha-reviewer" and .base == "reviewer" and .class == "read-only"' >/dev/null && ok "the reviewer base is read-only" || no "reviewer json"
e=$("$YES" agent for build --profile review --surface cloud --project alpha 2>&1 >/dev/null); rc=$?
{ [ $rc = 2 ] && grep -q 'review' <<<"$e"; } && ok "build with the review profile: exit 2, with the reason" || no "class refusal: rc=$rc $e"
e=$("$YES" agent for review --profile build --surface cloud --project alpha 2>&1 >/dev/null); [ $? = 2 ] && ok "review with the build profile: exit 2" || no "class refusal 2"
"$YES" agent for build --profile nosuch --surface cloud --project alpha >/dev/null 2>&1; [ $? = 1 ] && ok "an unknown profile is exit 1" || no "unknown profile"
# a role of yours takes its class's row
mkdir -p "$T/c/roles/tw"; echo '{"class":"write"}' > "$T/c/roles/tw/role.json"; echo "the tw role" > "$T/c/roles/tw/ROLE.md"
cj "$YES" tw --project alpha | jq -e '.instance == "alpha-worker" and .profile == "build" and .class == "write"' >/dev/null && ok "a custom write role uses the build row on the worker" || no "custom role: $(cj "$YES" tw --project alpha)"
# the project's profiles
jq '.profiles = {pm:{base:"worker",model:"claude-opus-5-5"}, scout:{base:"reviewer",tier:"fast",effort:"medium"}}' "$T/c/projects/alpha.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/alpha.json"
[ "$(cl "$YES" build --profile pm --project alpha)" = "alpha-worker $O medium pm" ] && ok "verified: a project profile with another model still runs on the worker" || no "pm: $(cl "$YES" build --profile pm --project alpha)"
[ "$(cl "$YES" review --profile scout --project alpha)" = "alpha-reviewer $H medium scout" ] && ok "a project-only reviewer profile" || no "scout"

# --- shipped: the override capability is unverified, so the legacy role instance runs
[ "$(cl "$SHIP" build --project alpha)" = "alpha-build $S high build" ] && ok "unverified: falls back to the legacy build instance" || no "legacy: $(cl "$SHIP" build --project alpha)"
cj "$SHIP" build --project alpha | jq -e '.instance == "alpha-build" and .base == null and .legacy == true and .model == "claude-sonnet-5-5" and .class == "write"' >/dev/null && ok "--json: base null, legacy true" || no "legacy json: $(cj "$SHIP" build --project alpha)"
[ "$(cl "$SHIP" review --project alpha)" = "alpha-review $O high review" ] && ok "unverified: review runs on the legacy review instance" || no "legacy review: $(cl "$SHIP" review --project alpha)"
e=$("$SHIP" agent for review --profile auditor --surface cloud --project alpha 2>&1 >/dev/null); rc=$?
{ [ $rc = 2 ] && grep -q 'alpha-review' <<<"$e" && grep -q "$O" <<<"$e" && grep -q "$H" <<<"$e" && grep -q 'per_dispatch_model_override' <<<"$e"; } && ok "degrade: the legacy instance cannot run another model; exit 2 naming the instance, both models and the capability" || no "degrade refusal: rc=$rc $e"
e=$("$SHIP" agent for build --profile pm --surface cloud --project alpha 2>&1 >/dev/null); [ $? = 2 ] && ok "degrade: a build profile with another model is refused too" || no "pm legacy"
[ "$(cl "$SHIP" test --project beta)" = "beta-test $S low test" ] && ok "the role's own legacy instance comes before the class's row instance" || no "beta test: $(cl "$SHIP" test --project beta)"
[ "$(cl "$SHIP" test --project alpha)" = "alpha-build $S low test" ] && ok "a role with no instance of its own falls back to its class's row instance (the local order), a base registered or not" || no "alpha test: $(cl "$SHIP" test --project alpha)"
# the base is registered, the legacy instance is not
e=$("$SHIP" agent for build --surface cloud --project gamma 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'gamma-worker' <<<"$e" && grep -q 'per_dispatch_model_override' <<<"$e"; } && ok "only an unusable base registered: exit 2 saying why" || no "gamma: rc=$rc $e"
[ "$(cl "$YES" build --project gamma)" = "gamma-worker $S high build" ] && ok "the same base is used once the capability is verified" || no "gamma yes"

# --- effort: asked, so its override must be verified too
[ "$(cl "$YES" build --project epsilon | cut -d' ' -f1)" = "epsilon-build" ] && ok "effort override unverified: an effort is asked, so the legacy instance" || no "epsilon: $(cl "$YES" build --project epsilon)"
cl "$YES" build --project epsilon | head -1 | grep -q "^epsilon-build $S high build$" && ok "and it keeps the profile's effort in the answer" || no "epsilon line"
jq '.models = {provider: "effunver"} | .profiles = {pm:{base:"worker",model:"claude-opus-5-5"}}' "$T/c/projects/epsilon.json" > "$T/e.json" && mv "$T/e.json" "$T/c/projects/epsilon.json"
"$YES" agent for build --profile pm --surface cloud --project epsilon >/dev/null 2>&1; [ $? = 2 ] && ok "effort unverified and another model: refused" || no "epsilon pm"

# --- opt-in profiles
e=$("$YES" agent for review --profile researcher --surface cloud --project alpha 2>&1 >/dev/null); rc=$?
{ [ $rc = 2 ] && grep -q 'opt-in' <<<"$e"; } && ok "researcher is refused without --opt-in (exit 2)" || no "researcher: rc=$rc $e"
[ "$("$YES" agent for review --profile researcher --opt-in --surface cloud --project alpha 2>&1)" = "alpha-reviewer $F high researcher" ] && ok "researcher with --opt-in: the reviewer base at the frontier model" || no "researcher opt-in"
"$YES" agent for review --profile researcher --opt-in --surface cloud --project alpha --json | jq -e '.model == "claude-fable-5-1" and .profile == "researcher"' >/dev/null && ok "and --json carries it" || no "researcher json"
"$SHIP" agent for review --profile researcher --opt-in --surface cloud --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "opt-in does not lift the degrade rule (legacy review runs opus)" || no "researcher legacy"

# --- nothing registered
e=$("$YES" agent for build --surface cloud --project delta 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q 'delta' <<<"$e" && grep -q 'registered' <<<"$e"; } && ok "no cloud instance (a local one does not count): exit 1 with a clear message" || no "delta: rc=$rc $e"
"$YES" agent for build --surface cloud --project nosuchproject >/dev/null 2>&1; [ $? = 1 ] && ok "a project with no instances: exit 1" || no "nosuchproject"
e=$("$YES" agent for review --surface cloud --project beta 2>&1); [ "$e" = "beta-review $O high review" ] && ok "a project with only the legacy reviewer works" || no "beta review: $e"
echo '{}' > "$T/c/instances.json"; "$YES" agent for build --surface cloud --project alpha >/dev/null 2>&1; [ $? = 1 ] && ok "an empty registry: exit 1, none invented" || no "empty registry"
[ "$(cat "$T/c/instances.json")" = '{}' ] && ok "and the registry is left as it was" || no "registry changed"

# --- the surface option
"$YES" agent for build --surface elsewhere --project alpha >/dev/null 2>&1; [ $? != 0 ] && ok "an unknown surface is an error" || no "bad surface"
"$YES" agent for build --surface cloud >/dev/null 2>&1; [ $? != 0 ] && ok "cloud needs a project (none is inferred outside one)" || no "cloud without project"

# --- local is unchanged: absent and --surface local give the same bytes, members and all
$YES agent add builder --abilities build,test >/dev/null 2>&1; $YES agent add judge --abilities review >/dev/null 2>&1
for args in "build" "test" "review" "review --profile auditor" "build --profile review" "build --profile nosuch" "build --json"; do
  a=$($YES agent for $args 2>&1; echo "rc=$?"); b=$($YES agent for $args --surface local 2>&1; echo "rc=$?")
  [ "$a" = "$b" ] && ok "local: 'for $args' is the same with --surface local" || no "local differs for $args: [$a] vs [$b]"
done
[ "$($YES agent for build)" = "builder sonnet high build" ] && [ "$($YES agent for review)" = "judge opus high review" ] && ok "local output keeps its shape: MEMBER ALIAS EFFORT PROFILE" || no "local shape: $($YES agent for build)"
exit $fail
