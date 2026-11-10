#!/usr/bin/env bash
# Default models and efforts: lib/model-defaults.json, qargi agent add and qargi agent models. Run: tests/test_models.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TABLE=$PWD/lib/model-defaults.json
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$HOME" "$T/c/projects"
# there is no default provider: the provider is a project's models.provider, and a member belongs to a project. pbase is the project in effect
git init -q "$T/repop"
jq -n --arg p "$T/repop" '{schema:1,project:"pbase",repo:{url:"https://github.com/example/pbase",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/pbase.json"
export QARGI_PROJECT=pbase
A=$T/repop/.claude/agents

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
jq -e --argjson tiers "$TIERS" --slurpfile d "$TABLE" '.family == "claude" and (.tiers | keys | sort) == ($tiers | sort) and (.tiers | all(.model | test("^claude-")))
  and (.tiers | map_values(.alias)) == {fast:"haiku",balanced:"sonnet",deep:"opus",frontier:"fable"}
  and ([$d[0].profiles[].tier] | unique | all(. as $t | $tiers | index($t)))' "$PROV/catalogs/claude.json" >/dev/null \
  && ok "the claude catalog maps every tier the table uses to an id and to an alias" || no "catalog file"
jq -e --slurpfile d "$TABLE" '. as $c | [$d[0].profiles[].tier] | unique | all(. as $t | $c.tiers[$t].model != null and $c.tiers[$t].alias != null)' "$PROV/catalogs/claude.json" >/dev/null && ok "every profile's tier has both a model and an alias" || no "tier coverage"
[ "$(find "$PROV" -maxdepth 1 -name '*.json' -printf '%f\n' | LC_ALL=C sort)" = "$(printf 'adapter-schema.json\nclaude-code.json\nclaude-platform.json\nschema-2.json')" ] && ok "claude-code and claude-platform are the provider files (beside the schemas, which describe them)" || no "providers: $(ls "$PROV")"

mline() { grep -c "^$2: $3\$" "$A/$1.md"; }
$DA agent add b1 --project pbase --roles build >/dev/null 2>&1 && [ "$(mline b1 model claude-sonnet-5-5)" = 1 ] && [ "$(mline b1 effort high)" = 1 ] && ok "add: build gets the table's model and effort" || no "build default: $(head -5 "$A/b1.md")"
$DA agent add r1 --project pbase --roles review >/dev/null 2>&1 && [ "$(mline r1 model claude-opus-5-5)" = 1 ] && [ "$(mline r1 effort high)" = 1 ] && ok "add: review gets the review row" || no "review default"
$DA agent add t1 --project pbase --roles test,build >/dev/null 2>&1 && [ "$(mline t1 effort low)" = 1 ] && ok "add: the first listed ability decides" || no "first ability"
! grep -q '{{' "$A/b1.md" && sed -n 1,3p "$A/b1.md" | grep -q '^---$' && ! grep -q '^$' <(sed -n '1,/^hooks:/p' "$A/b1.md") && ok "no placeholder and no blank frontmatter line" || no "frontmatter"
jq -e '.projects.pbase.b1 | .model == "claude-sonnet-5-5" and .effort == "high"' "$T/c/agents.json" >/dev/null && ok "the registry records them" || no "registry"

# a custom role falls back to its class
for pair in "tw:write" "ro:read-only"; do
  r=${pair%%:*}; c=${pair##*:}; mkdir -p "$T/c/roles/$r"
  jq -n --arg c "$c" '{class:$c}' > "$T/c/roles/$r/role.json"; echo "the $r role" > "$T/c/roles/$r/ROLE.md"
done
$DA agent add cw --project pbase --roles tw >/dev/null 2>&1 && [ "$(mline cw model claude-sonnet-5-5)" = 1 ] && [ "$(mline cw effort high)" = 1 ] && ok "a custom write role falls back to the build row" || no "custom write: $($DA agent add cw2 --project pbase --roles tw 2>&1)"
$DA agent add cr --project pbase --roles ro >/dev/null 2>&1 && [ "$(mline cr model claude-opus-5-5)" = 1 ] && [ "$(mline cr effort high)" = 1 ] && ok "a custom read-only role falls back to the review row" || no "custom read-only"

# explicit values win
$DA agent add ex --project pbase --roles review --model claude-haiku-5-5 --effort max >/dev/null 2>&1 && [ "$(mline ex model claude-haiku-5-5)" = 1 ] && [ "$(mline ex effort max)" = 1 ] && ok "explicit --model and --effort win" || no "explicit"
$DA agent add ex2 --project pbase --roles build --effort turbo >/dev/null 2>&1 && no "bad effort accepted" || ok "a bad effort is still refused"

# a project's answers
git init -q "$T/repo"
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-opus-5-5",effort:"xhigh"},
         review:{base:"main",push:{mode:"none"},model:"claude-haiku-5-5",effort:"low"}},
  lead:{model:"claude-opus-5-5",effort:"high"},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
PA=$T/repo/.claude/agents
$DA agent add pb --roles build --project alpha >/dev/null 2>&1 && grep -q '^model: claude-opus-5-5$' "$PA/pb.md" && grep -q '^effort: xhigh$' "$PA/pb.md" && ok "add --project: the project's answers win" || no "project override: $(head -5 "$PA/pb.md")"
$DA agent add pt --roles test --project alpha >/dev/null 2>&1 && grep -q '^model: claude-sonnet-5-5$' "$PA/pt.md" && grep -q '^effort: low$' "$PA/pt.md" && ok "a role the project does not answer uses the table" || no "project fallback"
$DA agent add pe --roles build --project alpha --model claude-haiku-5-5 >/dev/null 2>&1 && grep -q '^model: claude-haiku-5-5$' "$PA/pe.md" && grep -q '^effort: xhigh$' "$PA/pe.md" && ok "explicit model, project effort" || no "mixed"

# refresh keeps the effort
$DA agent add rf --project pbase --roles build --model claude-haiku-5-5 --effort medium >/dev/null 2>&1
sed -i '/^effort:/d' "$A/rf.md"
$DA agent refresh rf >/dev/null 2>&1 && [ "$(mline rf effort medium)" = 1 ] && [ "$(mline rf model claude-haiku-5-5)" = 1 ] && ok "refresh keeps the recorded effort and model" || no "refresh"
# an old member without effort has no effort line
jq '.projects.pbase.old = {roles:["build"], file:($f), model:"sonnet", effort:null, created:"x", seq:99}' --arg f "$A/old.md" "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent refresh old >/dev/null 2>&1; [ -f "$A/old.md" ] && grep -q '^model: sonnet$' "$A/old.md" && ! grep -q '^effort:' "$A/old.md" && ! grep -q '^$' <(sed -n '1,/^hooks:/p' "$A/old.md") && ok "a member without effort renders no effort line" || no "old member"

# agent models
$DA agent add rs --project pbase --roles review --model claude-fable-5-1 --effort high >/dev/null 2>&1
out=$($DA agent models 2>&1)
grep -E '^ *review ' <<<"$out" | grep -q 'deep -> opus -> claude-opus-5-5/high' && grep -E '^ *build ' <<<"$out" | grep -q 'balanced -> sonnet -> claude-sonnet-5-5/high' && ok "models: tier, alias, id and effort per profile" || no "tier text: $out"
grep -q 'provider: claude-code' <<<"$out" && ok "models: the active provider" || no "provider line"
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
jq -e 'keys == ["aliases","bases","effort_control","escalate","members","profiles","provider","warnings"] and .warnings == (.warnings | arrays) and .profiles.lead.base == null and .profiles.researcher.opt_in == true and .profiles.auditor.model == "haiku" and .profiles.auditor.model_id == "claude-haiku-5-5"
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
$DA agent add res2 --project pbase --roles review --model claude-fable-5-1 --effort high >/dev/null 2>&1 && grep -q -- '--class read-only' "$A/res2.md" && ok "a researcher (review ability) is read-only by class" || no "researcher class"

# problems are flagged rows, never an error
W=$T/w; mkdir -p "$W/home" "$W/c/projects"; git init -q "$W/repow"
jq -n --arg p "$W/repow" '{schema:1,project:"wbase",repo:{url:"https://github.com/example/wbase",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$W/c/projects/wbase.json"
wd() { HOME=$W/home QARGI_CONF=$W/c QARGI_STATE=$W/s QARGI_PROJECT=wbase "$DA" "$@"; }
wm() { HOME=$W/home QARGI_CONF=$W/c QARGI_STATE=$W/s QARGI_PROJECT=wbase "$DA" agent models "$@"; }
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'no reviewer: review profiles cannot dispatch' <<<"$out" && grep -E '^ *reviewer ' <<<"$out" | grep -q 'no reviewer'; } && ok "models: a missing base is flagged (no reviewer)" || no "missing base: rc=$rc $out"
wm --json | jq -e '[.warnings[] | select(.message | test("no reviewer: review profiles cannot dispatch"))] | length == 1' >/dev/null && ok "models --json: the same problem in warnings[]" || no "warnings json"
wd agent add builder --project wbase --roles build,test >/dev/null 2>&1
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q 'no worker: build,write,test profiles cannot dispatch' <<<"$out" && grep -E '^ *builder ' <<<"$out" | grep -q 'not a base (reviewer, worker)'; } && ok "models: a member that is not a base is flagged, and the missing worker is still flagged (nothing else stands in for it)" || no "not a base: $out"
wd agent add worker --project wbase --roles build,write,test >/dev/null 2>&1
out=$(wm 2>&1)
grep -E '^ *builder ' <<<"$out" | grep -q 'not a base' && ! grep -E '^ *worker +build' <<<"$out" | grep -q 'not a base' && ! grep -q 'no worker' <<<"$out" && ok "models: once the worker exists the missing-base flag is gone; the worker itself is a base" || no "worker registered: $out"
wm --json | jq -e '[.warnings[] | select(.kind == "member" and .name == "builder")][0].message | startswith("not a base")' >/dev/null && wm --json | jq -e '(.members[] | select(.name == "builder") | .flags | length) == 1' >/dev/null && ok "models --json: member flags and warnings agree" || no "member warnings json"
wd agent add mix --project wbase --roles build,review >/dev/null 2>&1
out=$(wm 2>&1)
grep -E '^ *mix ' <<<"$out" | grep -q 'write class; never serves review' && ok "models: a mixed-class member is flagged write class" || no "mixed flag: $out"
wd agent add gone --project wbase --roles test >/dev/null 2>&1; rm -f "$W/repow/.claude/agents/gone.md"
out=$(wm 2>&1); rc=$?
{ [ $rc = 0 ] && grep -E '^ *gone ' <<<"$out" | grep -q 'MISSING: the file is not there'; } && ok "models: a member whose definition file is missing is flagged" || no "missing file: $out"
wd agent add deepthought --project wbase --roles review --model claude-fable-5-1 >/dev/null 2>&1; wd agent add sage --project wbase --roles review --model fable >/dev/null 2>&1; wd agent add researcher --project wbase --roles review --model fable >/dev/null 2>&1
out=$(wm 2>&1)
{ grep -E '^ *deepthought ' <<<"$out" | grep -q frontier && grep -E '^ *sage ' <<<"$out" | grep -q frontier && ! grep -E '^ *researcher +review +fable' <<<"$out" | grep -q frontier; } && ok "models: a member on the frontier model is flagged unless it is the researcher" || no "frontier: $out"
jq -n --arg p "$W" '{schema:1,project:"beta",repo:{url:"https://github.com/example/beta",path:$p,long_lived:["main"]},roles:{},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500,
  profiles:{ghost:{base:"nosuch"}, clash:{base:"worker",abilities:["review"]}, tiny:{base:"reviewer",tier:"ultra"}, odd:{base:"worker",model:"claude-odd-9"}}}' > "$W/c/projects/beta.json"
out=$(wm --project beta 2>&1); rc=$?
{ [ $rc = 0 ] && grep -E '^ *ghost ' <<<"$out" | grep -q 'refused' && grep -E '^ *clash ' <<<"$out" | grep -q 'refused'; } && ok "models: a project profile with an unknown base or a class conflict is refused (exit 0)" || no "refused: rc=$rc $out"
{ grep -E '^ *tiny ' <<<"$out" | grep -q 'tier ultra has no alias' && grep -E '^ *odd ' <<<"$out" | grep -q 'no alias'; } && ok "models: a tier or model with no alias is flagged" || no "no alias: $out"
wm --project beta --json | jq -e '[.warnings[] | select(.kind == "profile") | .name] | (index("ghost") and index("clash") and index("tiny") and index("odd"))' >/dev/null && ok "models --json: profile problems in warnings[]" || no "profile warnings"
rm -f "$W/c/agents.json"; echo '{}' > "$W/c/agents.json"
wm >/dev/null 2>&1 && ok "models with no member at all still exits 0" || no "no members"

# the provider: from the project's models.provider
jq '.models = {provider:"claude"}' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent add pp --roles review --project alpha >/dev/null 2>&1 && grep -q '^model: claude-haiku-5-5$' "$PA/pp.md" && ok "models.provider claude (the family name) resolves to claude-code and through its catalog" || no "provider claude"
# a different provider, with a file of its own in a copy of the tree, resolves its own ids
jq '.models.provider = "nope"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
e=$($DA agent add pq --roles build --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude, claude-code' <<<"$e" && [ ! -e "$PA/pq.md" ]; } && ok "an unknown models.provider is an error listing the providers (add)" || no "unknown provider add: $e"
e=$($DA agent models --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude, claude-code' <<<"$e"; } && ok "an unknown models.provider is an error listing the providers (models)" || no "unknown provider models: $e"
jq '.models.provider = "schema-2"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
e=$($DA agent models --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q "no runtime or family 'schema-2'" <<<"$e" && grep -q 'available: claude, claude-code' <<<"$e"; } && ok "schema-2.json is not a provider (the file that describes them)" || no "schema as provider: $e"
jq '.models.provider = "Bad Name"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent models --project alpha >/dev/null 2>&1 && no "bad provider token accepted" || ok "a provider that is not a lower-case token is an error"
$DA project template alpha | jq -e '.roles | all(.[]; .model == null) and (.build.effort == "high") and (.write.effort == "medium")' >/dev/null && ok "project template names no model (a role takes its provider's tier once one is set)" || no "template models"
$DA project template alpha | jq -e '.models.provider == ""' >/dev/null && ! $DA project template alpha | grep -qi claude && ok "project template names no provider and no vendor" || no "template provider"

# models needs a project (--project, else the one in effect: the provider is the project's); its help must not promise a listing of every project
out=$(QARGI_PROJECT='' $DA agent models 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'project' <<<"$out"; } && ok "models with no project in effect: exit 2, and says why" || no "models without a project: rc=$rc $out"
hp=$($DA help agent models 2>&1)
! grep -qi 'every project' <<<"$hp" && ! grep -q 'PROJECT/NAME' <<<"$hp" && ok "and its help does not describe a listing of every project" || no "models help promises a listing of every project"

shellcheck -x -S warning lib/agent.sh lib/project.sh tests/test_models.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"
exit $fail
