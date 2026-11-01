#!/usr/bin/env bash
# Default models and efforts: lib/model-defaults.json, qargi agent add and qargi agent models. Run: tests/test_models.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TABLE=$PWD/lib/model-defaults.json
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects"
A=$HOME/.claude/agents

PROV=$PWD/lib/providers
TIERS='["fast","balanced","deep","frontier"]'
jq -e --argjson tiers "$TIERS" '.profiles as $p | ($p | to_entries | all(.value.tier | IN($tiers[])) and all(.value.effort | IN("low","medium","high","xhigh","max")) and all(.value | has("model") | not) and all(.value.purpose | length > 0))
  and ($p | has("lead") and has("build") and has("write") and has("test") and has("review") and has("auditor") and has("advisor") and has("researcher"))
  and (has("roles") | not) and (has("suggested") | not)' "$TABLE" >/dev/null \
  && ok "the table is valid and complete (tiers and efforts, purposes, no model ids, no roles or suggested)" || no "table"
jq -e '.bases == {worker:{abilities:["build","write","test"],class:"write"},reviewer:{abilities:["review"],class:"read-only"}}
  and (.profiles | to_entries | all(.key == "lead" or (.value.base as $b | $b == "worker" or $b == "reviewer")))
  and .profiles.lead.base == null' "$TABLE" >/dev/null && ok "two bases, one per guard class; every profile but the lead names one" || no "bases"
jq -e '.profiles.build.base == "worker" and .profiles.write.base == "worker" and .profiles.test.base == "worker" and ([.profiles.review, .profiles.auditor, .profiles.advisor, .profiles.researcher] | all(.base == "reviewer"))' "$TABLE" >/dev/null && ok "build, write and test use the worker; the review profiles the reviewer" || no "profile bases"
jq -e '[.profiles | to_entries[] | select(.value.opt_in == true) | .key] == ["researcher"] and .profiles.researcher.tier == "frontier" and ([.profiles | to_entries[] | select(.value.tier == "frontier") | .key] == ["researcher"])' "$TABLE" >/dev/null && ok "only the researcher is opt-in and on frontier" || no "opt-in"
jq -e '.escalate == {build:"frontier",write:"frontier",test:"frontier",review:"frontier"}' "$TABLE" >/dev/null && ok "escalate names the tier to offer per role" || no "escalate"
jq -e --argjson tiers "$TIERS" --slurpfile d "$TABLE" '.provider == "claude" and (.tiers | keys | sort) == ($tiers | sort) and (.tiers | all(test("^claude-")))
  and (.aliases == {fast:"haiku",balanced:"sonnet",deep:"opus",frontier:"fable"})
  and ([$d[0].profiles[].tier] | unique | all(. as $t | $tiers | index($t)))' "$PROV/claude.json" >/dev/null \
  && ok "the claude provider file maps every tier the table uses to an id and to an alias" || no "provider file"
jq -e --slurpfile d "$TABLE" '. as $c | [$d[0].profiles[].tier] | unique | all(. as $t | $c.tiers[$t] != null and $c.aliases[$t] != null)' "$PROV/claude.json" >/dev/null && ok "every profile's tier is in both tiers and aliases" || no "tier coverage"
[ "$(find "$PROV" -maxdepth 1 -name '*.json' -printf '%f\n' | sort)" = "$(printf 'claude.json\nschema.json')" ] && ok "claude is the only provider file (beside schema.json, which describes them)" || no "providers: $(ls "$PROV")"

mline() { grep -c "^$2: $3\$" "$A/$1.md"; }
$DA agent add b1 --abilities build >/dev/null 2>&1 && [ "$(mline b1 model claude-sonnet-5-5)" = 1 ] && [ "$(mline b1 effort high)" = 1 ] && ok "add: build gets the table's model and effort" || no "build default: $(head -5 "$A/b1.md")"
$DA agent add r1 --abilities review >/dev/null 2>&1 && [ "$(mline r1 model claude-opus-5-5)" = 1 ] && [ "$(mline r1 effort high)" = 1 ] && ok "add: review gets the review row" || no "review default"
$DA agent add t1 --abilities test,build >/dev/null 2>&1 && [ "$(mline t1 effort low)" = 1 ] && ok "add: the first listed ability decides" || no "first ability"
! grep -q '{{' "$A/b1.md" && sed -n 1,3p "$A/b1.md" | grep -q '^---$' && ! grep -q '^$' <(sed -n '1,/^hooks:/p' "$A/b1.md") && ok "no placeholder and no blank frontmatter line" || no "frontmatter"
jq -e '.b1.model == "claude-sonnet-5-5" and .b1.effort == "high"' "$T/c/agents.json" >/dev/null && ok "the registry records them" || no "registry"

# a custom role falls back to its class
for pair in "tw:write" "ro:read-only"; do
  r=${pair%%:*}; c=${pair##*:}; mkdir -p "$T/c/roles/$r"
  jq -n --arg c "$c" '{class:$c}' > "$T/c/roles/$r/role.json"; echo "the $r role" > "$T/c/roles/$r/ROLE.md"
done
$DA agent add cw --abilities tw >/dev/null 2>&1 && [ "$(mline cw model claude-sonnet-5-5)" = 1 ] && [ "$(mline cw effort high)" = 1 ] && ok "a custom write role falls back to the build row" || no "custom write: $($DA agent add cw2 --abilities tw 2>&1)"
$DA agent add cr --abilities ro >/dev/null 2>&1 && [ "$(mline cr model claude-opus-5-5)" = 1 ] && [ "$(mline cr effort high)" = 1 ] && ok "a custom read-only role falls back to the review row" || no "custom read-only"

# explicit values win
$DA agent add ex --abilities review --model claude-haiku-5-5 --effort max >/dev/null 2>&1 && [ "$(mline ex model claude-haiku-5-5)" = 1 ] && [ "$(mline ex effort max)" = 1 ] && ok "explicit --model and --effort win" || no "explicit"
$DA agent add ex2 --abilities build --effort turbo >/dev/null 2>&1 && no "bad effort accepted" || ok "a bad effort is still refused"

# a project's answers
git init -q "$T/repo"
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-opus-5-5",effort:"xhigh"},
         review:{base:"main",push:{mode:"none"},model:"claude-haiku-5-5",effort:"low"}},
  lead:{model:"claude-opus-5-5",effort:"high"},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
PA=$T/repo/.claude/agents
$DA agent add pb --abilities build --project alpha >/dev/null 2>&1 && grep -q '^model: claude-opus-5-5$' "$PA/pb.md" && grep -q '^effort: xhigh$' "$PA/pb.md" && ok "add --project: the project's answers win" || no "project override: $(head -5 "$PA/pb.md")"
$DA agent add pt --abilities test --project alpha >/dev/null 2>&1 && grep -q '^model: claude-sonnet-5-5$' "$PA/pt.md" && grep -q '^effort: low$' "$PA/pt.md" && ok "a role the project does not answer uses the table" || no "project fallback"
$DA agent add pe --abilities build --project alpha --model claude-haiku-5-5 >/dev/null 2>&1 && grep -q '^model: claude-haiku-5-5$' "$PA/pe.md" && grep -q '^effort: xhigh$' "$PA/pe.md" && ok "explicit model, project effort" || no "mixed"

# refresh keeps the effort
$DA agent add rf --abilities build --model claude-haiku-5-5 --effort medium >/dev/null 2>&1
sed -i '/^effort:/d' "$A/rf.md"
$DA agent refresh rf >/dev/null 2>&1 && [ "$(mline rf effort medium)" = 1 ] && [ "$(mline rf model claude-haiku-5-5)" = 1 ] && ok "refresh keeps the recorded effort and model" || no "refresh"
# an old member without effort has no effort line
jq '.old = {abilities:["build"], file:($f), model:"sonnet", effort:null, project:null, created:"x", seq:99}' --arg f "$A/old.md" "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent refresh old >/dev/null 2>&1; [ -f "$A/old.md" ] && grep -q '^model: sonnet$' "$A/old.md" && ! grep -q '^effort:' "$A/old.md" && ! grep -q '^$' <(sed -n '1,/^hooks:/p' "$A/old.md") && ok "a member without effort renders no effort line" || no "old member"

# agent models
$DA agent add rs --abilities review --model claude-fable-5-1 --effort high >/dev/null 2>&1
out=$($DA agent models 2>&1)
grep -E '^ *review ' <<<"$out" | grep -q 'deep -> opus -> claude-opus-5-5/high' && grep -E '^ *build ' <<<"$out" | grep -q 'balanced -> sonnet -> claude-sonnet-5-5/high' && ok "models: tier, alias, id and effort per profile" || no "tier text: $out"
grep -q 'provider: claude' <<<"$out" && ok "models: the active provider" || no "provider line"
grep -E '^ *(worker|reviewer) ' <<<"$out" | grep -q 'write' && grep -E '^ *reviewer ' <<<"$out" | grep -q 'read-only' && ok "models: the bases come first, with their class" || no "bases text: $out"
[ "$(grep -n -E '^bases' <<<"$out" | cut -d: -f1)" -lt "$(grep -n -E '^profiles' <<<"$out" | cut -d: -f1)" ] && [ "$(grep -n -E '^profiles' <<<"$out" | cut -d: -f1)" -lt "$(grep -n -E '^members' <<<"$out" | cut -d: -f1)" ] && ok "models: bases, profiles, then members" || no "section order"
grep -q 'offer frontier (claude-fable-5-1) for a hard task: only when asked' <<<"$out" && ok "models: the escalate line" || no "escalate line"
grep -E '^ *researcher ' <<<"$out" | grep -q 'opt-in' && ! grep -E '^ *(auditor|advisor|review) ' <<<"$out" | grep -q 'opt-in' && ok "models: only the researcher is marked opt-in" || no "opt-in text"
grep -E '^ *lead ' <<<"$out" | grep -q 'never dispatched' && ok "models: the lead is shown, never dispatched" || no "lead row"
grep -E '^ *rs ' <<<"$out" | grep -q 'frontier model outside the researcher' && ! grep -E '^ *b1 ' <<<"$out" | grep -q frontier && ok "models: a member on the frontier model is flagged" || no "frontier flag: $out"
{ grep -q 'lead.*claude-sonnet-5-5/medium' <<<"$out" && grep -q 'auditor.*fast -> haiku -> claude-haiku-5-5/low' <<<"$out" && grep -q 'test.*claude-sonnet-5-5/low' <<<"$out"; } && ok "models: the lead and profile rows" || no "models text: $out"
grep -E '^ *b1 ' <<<"$out" | grep -q 'claude-sonnet-5-5/high' && ok "models: members with model and effort" || no "members: $out"
! grep -q 'override\|project' <<<"$out" && ok "models: no project source without a project" || no "override shown"
j=$($DA agent models --json 2>&1)
jq -e 'keys == ["aliases","bases","escalate","members","profiles","provider","warnings"] and .warnings == (.warnings | arrays) and .profiles.lead.base == null and .profiles.researcher.opt_in == true and .profiles.auditor.model == "haiku" and .profiles.auditor.model_id == "claude-haiku-5-5"
  and .bases.worker.registered == false and .escalate.build.tier == "frontier" and (.members | length > 0)' <<<"$j" >/dev/null && ok "models --json: bases, profiles, aliases, escalate, members" || no "json keys: $j"

# a project's profiles and its old role answers
jq '.profiles = {build:{model:"claude-opus-5-5",effort:"xhigh"}, scout:{base:"reviewer",tier:"fast"}, auditor:{tier:"deep"}, "Bad Name":{base:"worker"}, broken:"x", worse:{base:7,tier:[],model:{},effort:"turbo"}}' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
out=$($DA agent models --project alpha 2>&1)
j=$($DA agent models --project alpha --json 2>&1)
jq -e '.profiles.build | .model == "opus" and .model_id == "claude-opus-5-5" and .effort == "xhigh" and .tier == "deep" and .source == "project" and .base == "worker"' <<<"$j" >/dev/null && ok "a project entry merges key by key over the shipped profile; a full id maps to its alias" || no "merge: $j"
jq -e '.profiles.scout | .base == "reviewer" and .model == "haiku" and .source == "project" and .opt_in == false' <<<"$j" >/dev/null && ok "a project-only profile with a tier" || no "scout: $j"
jq -e '.profiles.auditor | .model == "opus" and .effort == "low" and .purpose != ""' <<<"$j" >/dev/null && ok "a tier in the entry replaces the shipped tier, the rest stays" || no "auditor merge"
jq -e '(.profiles | has("Bad Name") | not) and (.profiles | has("broken") | not) and (.profiles.worse.refused != null)' <<<"$j" >/dev/null && ok "malformed entries are ignored and never crash" || no "malformed: $j"
jq -e '.profiles.review.model == "haiku" and .profiles.review.effort == "low" and .profiles.review.source == "project" and .profiles.review.via_roles == true and .profiles.lead.model == "opus" and .profiles.lead.effort == "high" and .profiles.test.source == "shipped"' <<<"$j" >/dev/null && ok "a role answer (roles.<R>.model/effort, lead) still sets the profile named after the role" || no "legacy roles: $j"
grep -E '^ *build ' <<<"$out" | grep -q 'project' && grep -E '^ *test ' <<<"$out" | grep -q 'shipped' && ok "models --project: the source of each row" || no "source text: $out"
[ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "models is read-only" || no "models wrote"
jq '.profiles = "nonsense"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent models --project alpha --json | jq -e '.profiles.build.source == "project"' >/dev/null && ok "profiles of the wrong type are ignored" || no "profiles type"
# the researcher is read-only when added
$DA agent add res2 --abilities review --model claude-fable-5-1 --effort high >/dev/null 2>&1 && grep -q -- '--class read-only' "$A/res2.md" && ok "a researcher (review ability) is read-only by class" || no "researcher class"

# problems are flagged rows, never an error
W=$T/w; mkdir -p "$W/home" "$W/c/projects"
wd() { HOME=$W/home QARGI_CONF=$W/c QARGI_STATE=$W/s "$DA" "$@"; }
wm() { HOME=$W/home QARGI_CONF=$W/c QARGI_STATE=$W/s "$DA" agent models "$@"; }
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'no reviewer: review profiles cannot dispatch' <<<"$out" && grep -E '^ *reviewer ' <<<"$out" | grep -q 'no reviewer'; } && ok "models: a missing base is flagged (no reviewer)" || no "missing base: rc=$rc $out"
wm --json | jq -e '[.warnings[] | select(.message | test("no reviewer: review profiles cannot dispatch"))] | length == 1' >/dev/null && ok "models --json: the same problem in warnings[]" || no "warnings json"
wd agent add builder --abilities build,test >/dev/null 2>&1
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -E '^ *builder ' <<<"$out" | grep -q 'legacy (in use: no worker)'; } && ok "models: a legacy member in use while there is no worker" || no "legacy in use: $out"
wd agent add worker --abilities build,write,test >/dev/null 2>&1
out=$(wm 2>&1)
grep -E '^ *builder ' <<<"$out" | grep -q 'legacy: retire after worker exists' && ! grep -E '^ *worker +build' <<<"$out" | grep -q legacy && ok "models: a legacy member once the worker exists; the worker itself is not legacy" || no "legacy retire: $out"
wm --json | jq -e '[.warnings[] | select(.kind == "member" and .name == "builder")][0].message == "legacy: retire after worker exists" and (.members[] | select(.name == "builder") | .flags | length) == 1' >/dev/null && ok "models --json: member flags and warnings agree" || no "member warnings json"
wd agent add mix --abilities build,review >/dev/null 2>&1
out=$(wm 2>&1)
grep -E '^ *mix ' <<<"$out" | grep -q 'write class; never serves review' && ok "models: a mixed-class member is flagged write class" || no "mixed flag: $out"
wd agent add gone --abilities test >/dev/null 2>&1; rm -f "$W/home/.claude/agents/gone.md"
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -E '^ *gone ' <<<"$out" | grep -q 'definition file missing'; } && ok "models: a member whose definition file is missing is flagged" || no "missing file: $out"
wd agent add deepthought --abilities review --model claude-fable-5-1 >/dev/null 2>&1; wd agent add sage --abilities review --model fable >/dev/null 2>&1; wd agent add researcher --abilities review --model fable >/dev/null 2>&1
out=$(wm 2>&1)
{ grep -E '^ *deepthought ' <<<"$out" | grep -q frontier && grep -E '^ *sage ' <<<"$out" | grep -q frontier && ! grep -E '^ *researcher +review +fable' <<<"$out" | grep -q frontier; } && ok "models: a member on the frontier model is flagged unless it is the researcher" || no "frontier: $out"
jq -n --arg p "$W" '{schema:1,project:"beta",repo:{url:"https://github.com/example/beta",path:$p,long_lived:["main"]},roles:{},memory:{},budget_cents:500,
  profiles:{ghost:{base:"nosuch"}, clash:{base:"worker",abilities:["review"]}, tiny:{base:"reviewer",tier:"ultra"}, odd:{base:"worker",model:"claude-odd-9"}}}' > "$W/c/projects/beta.json"
out=$(wm --project beta 2>&1); rc=$?
{ [ $rc = 0 ] && grep -E '^ *ghost ' <<<"$out" | grep -q 'refused' && grep -E '^ *clash ' <<<"$out" | grep -q 'refused'; } && ok "models: a project profile with an unknown base or a class conflict is refused (exit 0)" || no "refused: rc=$rc $out"
{ grep -E '^ *tiny ' <<<"$out" | grep -q 'tier ultra has no alias' && grep -E '^ *odd ' <<<"$out" | grep -q 'no alias'; } && ok "models: a tier or model with no alias is flagged" || no "no alias: $out"
wm --project beta --json | jq -e '[.warnings[] | select(.kind == "profile") | .name] | (index("ghost") and index("clash") and index("tiny") and index("odd"))' >/dev/null && ok "models --json: profile problems in warnings[]" || no "profile warnings"
rm -f "$W/c/agents.json"; echo '{}' > "$W/c/agents.json"
wm >/dev/null 2>&1 && ok "models with no member at all still exits 0" || no "no members"

# the provider: from the project's models.provider
jq '.models = {provider:"claude"}' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent add pp --abilities review --project alpha >/dev/null 2>&1 && grep -q '^model: claude-haiku-5-5$' "$PA/pp.md" && ok "models.provider claude resolves through the provider file" || no "provider claude"
# a different provider, with a file of its own in a copy of the tree, resolves its own ids
jq '.models.provider = "nope"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
e=$($DA agent add pq --abilities build --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude$' <<<"$e" && [ ! -e "$PA/pq.md" ]; } && ok "an unknown models.provider is an error listing the providers (add)" || no "unknown provider add: $e"
e=$($DA agent models --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude$' <<<"$e"; } && ok "an unknown models.provider is an error listing the providers (models)" || no "unknown provider models: $e"
jq '.models.provider = "schema"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
e=$($DA agent models --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "models.provider 'schema'" <<<"$e" && grep -q 'available: claude$' <<<"$e"; } && ok "schema.json is not a provider (the file that describes them)" || no "schema as provider: $e"
jq '.models.provider = "Bad Name"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent models --project alpha >/dev/null 2>&1 && no "bad provider token accepted" || ok "a provider that is not a lower-case token is an error"
[ "$($DA project template alpha | sha256sum | cut -d' ' -f1)" = 8efee3c2ababf5b293c2f7ea9b9a4e3afdbbb6f1706a55a08eb826002e91d293 ] && ok "project template output is byte-identical to before the profiles" || no "template"
$DA project template alpha | jq -e '.roles.build.model == "claude-sonnet-5-5" and .roles.write.model == "claude-sonnet-5-5" and .roles.build.effort == "high"' >/dev/null && ok "project template writes the resolved claude ids" || no "template ids"

shellcheck -x -S warning lib/agent.sh lib/project.sh tests/test_models.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"
exit $fail
