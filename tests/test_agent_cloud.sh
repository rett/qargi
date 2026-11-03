#!/usr/bin/env bash
# qargi agent for ROLE --surface cloud --project PROJ: which cloud instance runs a profile, from the instance registry. The base
# instance (<project>-worker or <project>-reviewer) takes the session's model and effort as overrides, so it is used only when the
# provider's per_dispatch_model_override (and per_dispatch_effort_override, when an effort is asked) is verified yes; otherwise the
# legacy role instance (<project>-build ...) runs, and only with the model it was provisioned with. Hermetic: a copy of the tool in
# a temporary root holds the descriptors with the capabilities verified, so the shipped claude-platform.json is never changed. Offline.
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
# verified, the effort override not. SHIP is a copy with neither verified.
TOOL=$T/tool; mkdir -p "$TOOL"
for d in agents bin lib roles skills provision contract canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$TOOL/"; done
SHIPT=$T/ship; mkdir -p "$SHIPT"
for d in agents bin lib roles skills provision contract canon methodologies VERSION; do [ ! -e "$SRC/$d" ] || cp -r "$SRC/$d" "$SHIPT/"; done
# the checkout once had the cloud overrides unverified; the copy keeps that state so the fallback to the role instances stays tested
jq '.capabilities.per_dispatch_model_override.verified_on = null
  | .capabilities.per_dispatch_effort_override.verified_on = null' "$SRC/lib/providers/claude-platform.json" > "$T/cp.json" && mv "$T/cp.json" "$SHIPT/lib/providers/claude-platform.json"
SHIP=$SHIPT/bin/qargi; YES=$TOOL/bin/qargi
jq '.capabilities.per_dispatch_model_override.verified_on = "2026-10-31"
  | .capabilities.per_dispatch_effort_override.verified_on = "2026-10-31"' "$SRC/lib/providers/claude-platform.json" > "$T/cp.json" && mv "$T/cp.json" "$TOOL/lib/providers/claude-platform.json"
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
fake_runtime "$TOOL" "$TOOL" effunver cloud '.capabilities.per_dispatch_effort_override.verified_on = null'
BOTH='{"local":"claude-code","cloud":"claude-platform"}'; EFFUN='{"local":"claude-code","cloud":"effunver"}'
python3 -I "$TOOL/lib/provider.py" check claude-platform >/dev/null && python3 -I "$TOOL/lib/provider.py" check effunver >/dev/null && ok "the verified descriptors are valid" || no "descriptors"
[ "$(python3 -I "$SHIPT/lib/provider.py" effective claude-platform cloud per_dispatch_model_override)" = no ] && ok "shipped (unverified copy): the cloud model override counts as no (unverified)" || no "shipped capability"
[ "$(python3 -I "$TOOL/lib/provider.py" effective claude-platform cloud per_dispatch_model_override)" = yes ] && [ "$(python3 -I "$TOOL/lib/provider.py" effective effunver cloud per_dispatch_effort_override)" = no ] && ok "the copy: model yes, and effort no for effunver" || no "copy capability"

# the projects: alpha has a base pair and the legacy instances, beta only the legacy ones, gamma only a worker, delta nothing
for p in alpha beta gamma delta epsilon; do
  jq -n --arg p "$p" --argjson v "$BOTH" '{schema:1,project:$p,repo:{url:"https://github.com/example/\($p)",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:$v},memory:{},budget_cents:500}' > "$T/c/projects/$p.json"
done
jq --argjson v "$EFFUN" '.models = {provider: $v}' "$T/c/projects/epsilon.json" > "$T/e.json" && mv "$T/e.json" "$T/c/projects/epsilon.json"
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
jq --argjson v "$EFFUN" '.models = {provider: $v} | .profiles = {pm:{base:"worker",model:"claude-opus-5-5"}}' "$T/c/projects/epsilon.json" > "$T/e.json" && mv "$T/e.json" "$T/c/projects/epsilon.json"
"$YES" agent for build --profile pm --surface cloud --project epsilon >/dev/null 2>&1; [ $? = 2 ] && ok "effort unverified and another model: refused" || no "epsilon pm"

# --- an extension the project enabled counts: fakecloud is a runtime of the pack library (data and a sealed adapter, no file in lib/providers)
# that claims no per-dispatch override; ovext, an extension pack, provides both. Once ovext has been verified for THIS runtime, the project
# that enabled it runs sessions on the base; before that, and for a project that did not enable it, the legacy instance runs.
FC=$T/ext/fc; OV=$T/ext/ovext; mkdir -p "$FC" "$OV"
cat > "$FC/adapter" <<'EOS'
#!/bin/sh
case $1 in
  resolve) printf '{"model":"fake-cloud-m","effort_native":"h"}\n';;
  start-session) jq -c --arg p "$0" '. + {fake_adapter: $p}';;
  *) echo '{"error":"no such verb"}'; exit 3;;
esac
EOS
chmod 755 "$FC/adapter"
jq -n '{schema:2,kind:"provider",provider:"fakecloud",family:null,surface:"cloud",
  models:{pattern:"^fake-.+$",tiers:{"*":{model:"fake-cloud-m",alias:null,verified_on:null,source:"test"}},effort:{low:"l",medium:"m",high:"h",xhigh:null,max:null}},
  capabilities:{},agents:null,resources:{},barrier:{kind:"none"},dispatch:{mode:"adapter"},adapter:"adapter",adapter_verbs:["resolve","start-session"]}' > "$FC/definition.json"
jq -n '{schema:2,kind:"extension",extension:"ovext",description:"per-dispatch overrides of fakecloud",extends:"fakecloud",provides:["per_dispatch_effort_override","per_dispatch_model_override"],
  adds:{capabilities:{per_dispatch_model_override:{value:"yes",note:"n"},per_dispatch_effort_override:{value:"yes",note:"n"}}}}' > "$OV/definition.json"
imp() { local t; t=$("$SHIP" provider import "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); "$SHIP" provider import "$1" --plan "$t" --approved test ${2:+--approve-exec "$2"} >/dev/null 2>&1; }
imp "$FC" adapter && imp "$OV" && ok "a library cloud runtime and an extension pack are imported" || no "import fakecloud / ovext"
for p in zeta eta; do
  jq -n --arg p "$p" '{schema:1,project:$p,repo:{url:"https://github.com/example/\($p)",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{cloud:"fakecloud"}},memory:{},budget_cents:500}' > "$T/c/projects/$p.json"
done
jq '.models.extensions = ["ovext"]' "$T/c/projects/zeta.json" > "$T/e.json" && mv "$T/e.json" "$T/c/projects/zeta.json"
jq --argjson w "$(inst x fake-cloud-m h)" '. + {"zeta-worker":$w,"zeta-build":$w,"eta-worker":$w,"eta-build":$w}' "$T/c/instances.json" > "$T/e.json" && mv "$T/e.json" "$T/c/instances.json"
[ "$(cl "$SHIP" build --project eta | cut -d' ' -f1)" = eta-build ] && [ "$(cl "$SHIP" build --project zeta | cut -d' ' -f1)" = zeta-build ] && ok "unverified extension: the legacy instance runs, as it does for a project that did not enable it" || no "extension unverified: $(cl "$SHIP" build --project zeta) / $(cl "$SHIP" build --project eta)"
python3 -I - "$SHIPT/lib" <<'PY'
import sys; sys.path.insert(0, sys.argv[1])
import provider as P
h = P.extension_hash("ovext", "fakecloud", "cloud")
P.record_verification("ovext", {c: {"hash": h, "by": "attest", "at": "2026-11-02", "note": "test"} for c in ("per_dispatch_model_override", "per_dispatch_effort_override")})
PY
[ "$(cl "$SHIP" build --project zeta)" = "zeta-worker fake-cloud-m h build" ] && ok "verified extension: the base runs for the project that enabled it, on the model and effort the library adapter resolved" || no "extension verified: $(cl "$SHIP" build --project zeta)"
[ "$(cl "$SHIP" build --project eta | cut -d' ' -f1)" = eta-build ] && ok "and a project that did not enable it still runs the legacy instance" || no "eta after verification: $(cl "$SHIP" build --project eta)"
leftover=''; for d in "${TMPDIR:-/tmp}"/qargi-exec.*; do [ ! -e "$d" ] || leftover=$d; done
[ -z "$leftover" ] && ok "the adapter ran as a private copy that was removed" || no "an exec copy was left: $leftover"

# --- opt-in profiles
e=$("$YES" agent for review --profile researcher --surface cloud --project alpha 2>&1 >/dev/null); rc=$?
{ [ $rc = 2 ] && grep -q 'opt-in' <<<"$e"; } && ok "researcher is refused without --opt-in (exit 2)" || no "researcher: rc=$rc $e"
[ "$("$YES" agent for review --profile researcher --opt-in --surface cloud --project alpha 2>&1)" = "alpha-reviewer $F high researcher" ] && ok "researcher with --opt-in: the reviewer base at the frontier model" || no "researcher opt-in"
"$YES" agent for review --profile researcher --opt-in --surface cloud --project alpha --json | jq -e '.model == "claude-fable-5-1" and .profile == "researcher"' >/dev/null && ok "and --json carries it" || no "researcher json"
"$SHIP" agent for review --profile researcher --opt-in --surface cloud --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "opt-in does not lift the degrade rule (legacy review runs opus)" || no "researcher legacy"

# --- nothing registered
e=$("$YES" agent for build --surface cloud --project delta 2>&1); rc=$?
{ [ $rc = 1 ] && grep -q 'delta' <<<"$e" && grep -q 'registered' <<<"$e"; } && ok "no cloud instance (a local one does not count): exit 1 with a clear message" || no "delta: rc=$rc $e"
e=$("$YES" agent for build --surface cloud --project nosuchproject 2>&1); rc=$?
{ [ $rc = 2 ] && [ "$e" = "qargi: no such project 'nosuchproject'" ]; } && ok "a project that is not stored: exit 2 and it says so (there is no provider to look up)" || no "nosuchproject: rc=$rc $e"
e=$("$YES" agent for review --surface cloud --project beta 2>&1); [ "$e" = "beta-review $O high review" ] && ok "a project with only the legacy reviewer works" || no "beta review: $e"
echo '{}' > "$T/c/instances.json"; "$YES" agent for build --surface cloud --project alpha >/dev/null 2>&1; [ $? = 1 ] && ok "an empty registry: exit 1, none invented" || no "empty registry"
[ "$(cat "$T/c/instances.json")" = '{}' ] && ok "and the registry is left as it was" || no "registry changed"

# --- the surface option
"$YES" agent for build --surface elsewhere --project alpha >/dev/null 2>&1; [ $? != 0 ] && ok "an unknown surface is an error" || no "bad surface"
"$YES" agent for build --surface cloud >/dev/null 2>&1; [ $? != 0 ] && ok "cloud needs a project (none is inferred outside one)" || no "cloud without project"

# --- local is unchanged: absent and --surface local give the same bytes, members and all
export QARGI_PROJECT=alpha   # a member belongs to a project, and the project's models.provider renders it: alpha gets a checkout
git init -q "$T/repoa"; jq --arg p "$T/repoa" '.repo.path = $p' "$T/c/projects/alpha.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/alpha.json"
$YES agent add worker --project alpha >/dev/null 2>&1; $YES agent add reviewer --project alpha >/dev/null 2>&1
for args in "build" "test" "review" "review --profile auditor" "build --profile review" "build --profile nosuch" "build --json"; do
  a=$($YES agent for $args 2>&1; echo "rc=$?"); b=$($YES agent for $args --surface local 2>&1; echo "rc=$?")
  [ "$a" = "$b" ] && ok "local: 'for $args' is the same with --surface local" || no "local differs for $args: [$a] vs [$b]"
done
[ "$($YES agent for build)" = "worker sonnet high build" ] && [ "$($YES agent for review)" = "reviewer opus high review" ] && ok "local output keeps its shape: MEMBER ALIAS EFFORT PROFILE" || no "local shape: $($YES agent for build)"
exit $fail
