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
jq -e --argjson tiers "$TIERS" '([.lead, .roles[], .suggested[]] | all(.tier | IN($tiers[])) and all(.effort | IN("low","medium","high","xhigh","max")))
  and ([.lead, .roles[], .suggested[]] | all(has("model") | not))
  and (.roles | has("build") and has("write") and has("test") and has("review"))
  and (.suggested | has("auditor") and has("advisor") and has("researcher"))
  and ([.suggested[]] | all(.abilities | length > 0) and all(.purpose | length > 0))' "$TABLE" >/dev/null \
  && ok "the table is valid and complete (tiers and efforts, no model ids)" || no "table"
jq -e '.suggested | to_entries | map(select(.value.tier == "frontier") | .key) == ["researcher"]' "$TABLE" >/dev/null && ok "only the researcher is suggested on frontier" || no "frontier suggested"
jq -e '.escalate == {build:"frontier",write:"frontier",test:"frontier",review:"frontier"}' "$TABLE" >/dev/null && ok "escalate names the tier to offer per role" || no "escalate"
jq -e --argjson tiers "$TIERS" --slurpfile d "$TABLE" '.provider == "claude" and (.tiers | keys | sort) == ($tiers | sort) and (.tiers | all(test("^claude-")))
  and ([$d[0].lead, $d[0].roles[], $d[0].suggested[]] | map(.tier) | unique - ($tiers) == [])
  and ([$d[0].lead, $d[0].roles[], $d[0].suggested[]] | map(.tier) | all(. as $t | $tiers | index($t)))' "$PROV/claude.json" >/dev/null \
  && ok "the claude provider file is valid and maps every tier the table uses" || no "provider file"
[ "$(ls "$PROV")" = claude.json ] && ok "claude is the only provider file" || no "providers: $(ls "$PROV")"

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
grep -E '^ *review ' <<<"$out" | grep -q 'deep -> claude-opus-5-5' && grep -E '^ *build ' <<<"$out" | grep -q 'balanced -> claude-sonnet-5-5' && ok "models: tier and resolved model per row" || no "tier text: $out"
grep -q 'provider: claude' <<<"$out" && ok "models: the active provider" || no "provider line"
grep -q 'offer frontier (claude-fable-5-1) for a hard task: only when asked' <<<"$out" && ok "models: the escalate line" || no "escalate line"
grep -q 'qargi agent add researcher --abilities review --model claude-fable-5-1 --effort high' <<<"$out" && ok "models: the researcher is suggested with its add command" || no "researcher line"
grep -E '^ *rs ' <<<"$out" | grep -q 'frontier (opt-in)' && ! grep -E '^ *b1 ' <<<"$out" | grep -q frontier && ok "models: a member on the frontier model is flagged" || no "frontier flag: $out"
{ grep -q 'lead.*claude-sonnet-5-5.*medium' <<<"$out" && grep -q 'review.*claude-opus-5-5.*high' <<<"$out" && grep -q 'test.*claude-sonnet-5-5.*low' <<<"$out"; } && ok "models: the lead and role rows" || no "models text: $out"
grep -q 'qargi agent add auditor --abilities review --model claude-haiku-5-5 --effort low' <<<"$out" && grep -q 'qargi agent add advisor --abilities review --model claude-opus-5-5 --effort high' <<<"$out" && ok "models: the suggested commands" || no "suggested"
grep -E '^ *b1 ' <<<"$out" | grep -q 'claude-sonnet-5-5/high' && grep -E '^ *old ' <<<"$out" | grep -q 'alias (unpinned)' && ! grep -E '^ *b1 ' <<<"$out" | grep -q unpinned && ok "models: members, alias marked unpinned" || no "members: $out"
! grep -q override <<<"$out" && ok "models: no override without a project" || no "override shown"
out=$($DA agent models --project alpha 2>&1)
grep -E '^ *build ' <<<"$out" | grep -q 'override.*claude-opus-5-5.*xhigh' && grep -E '^ *lead ' <<<"$out" | grep -q 'override.*claude-opus-5-5.*high' && grep -E '^ *test ' <<<"$out" | grep -vq override && ok "models --project: overrides marked" || no "override: $out"
j=$($DA agent models --project alpha --json 2>&1)
jq -e '(.lead.model) and .roles.build.model and (.suggested.auditor.model == "claude-haiku-5-5") and .provider == "claude" and .roles.review.tier == "deep" and .roles.review.model == "claude-opus-5-5" and .escalate.build.tier == "frontier" and .escalate.build.model == "claude-fable-5-1" and (.members | length > 0) and (.members | map(select(.name == "old"))[0].pinned == false)' <<<"$j" >/dev/null && ok "models --json is one object with lead, roles, suggested, members" || no "json: $j"
jq -e '.roles.build.override.model == "claude-opus-5-5" and .roles.build.model == "claude-sonnet-5-5"' <<<"$j" >/dev/null && ok "json carries the default and the project value" || no "json shape"
$DA agent models --json | jq -e 'keys == ["escalate","lead","members","provider","roles","suggested"]' >/dev/null && ok "json without a project" || no "json keys"
[ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "models is read-only" || no "models wrote"
# the researcher is read-only when added
$DA agent add res2 --abilities review --model claude-fable-5-1 --effort high >/dev/null 2>&1 && grep -q -- '--class read-only' "$A/res2.md" && ok "a researcher (review ability) is read-only by class" || no "researcher class"

# the provider: from the project's models.provider
jq '.models = {provider:"claude"}' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent add pp --abilities review --project alpha >/dev/null 2>&1 && grep -q '^model: claude-haiku-5-5$' "$PA/pp.md" && ok "models.provider claude resolves through the provider file" || no "provider claude"
# a different provider, with a file of its own in a copy of the tree, resolves its own ids
jq '.models.provider = "nope"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
e=$($DA agent add pq --abilities build --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude' <<<"$e" && [ ! -e "$PA/pq.md" ]; } && ok "an unknown models.provider is an error listing the providers (add)" || no "unknown provider add: $e"
e=$($DA agent models --project alpha 2>&1); rc=$?
{ [ $rc != 0 ] && grep -q 'nope' <<<"$e" && grep -q 'available: claude' <<<"$e"; } && ok "an unknown models.provider is an error listing the providers (models)" || no "unknown provider models: $e"
jq '.models.provider = "Bad Name"' "$T/c/projects/alpha.json" > "$T/c/a.json" && mv "$T/c/a.json" "$T/c/projects/alpha.json"
$DA agent models --project alpha >/dev/null 2>&1 && no "bad provider token accepted" || ok "a provider that is not a lower-case token is an error"
$DA project template alpha | jq -e '.roles.build.model == "claude-sonnet-5-5" and .roles.write.model == "claude-sonnet-5-5" and .roles.build.effort == "high"' >/dev/null && ok "project template writes the resolved claude ids" || no "template"

shellcheck -x -S warning lib/agent.sh lib/project.sh tests/test_models.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"
exit $fail
