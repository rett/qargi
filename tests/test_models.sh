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

jq -e '(.lead.model | test("^claude-")) and (.lead.effort | IN("low","medium","high","xhigh","max"))
  and ([.roles.build, .roles.write, .roles.test, .roles.review] | all(.model | test("^claude-")))
  and ([.roles[], .lead] | all(.effort | IN("low","medium","high","xhigh","max")))
  and (.suggested | has("auditor") and has("advisor"))
  and ([.suggested[]] | all(.abilities | length > 0) and all(.purpose | length > 0) and all(.model | test("^claude-")))' "$TABLE" >/dev/null \
  && ok "the table is valid and complete" || no "table"

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
out=$($DA agent models 2>&1)
{ grep -q 'lead.*claude-sonnet-5-5.*medium' <<<"$out" && grep -q 'review.*claude-opus-5-5.*high' <<<"$out" && grep -q 'test.*claude-sonnet-5-5.*low' <<<"$out"; } && ok "models: the lead and role rows" || no "models text: $out"
grep -q 'qargi agent add auditor --abilities review --model claude-haiku-5-5 --effort low' <<<"$out" && grep -q 'qargi agent add advisor --abilities review --model claude-opus-5-5 --effort high' <<<"$out" && ok "models: the suggested commands" || no "suggested"
grep -E '^ *b1 ' <<<"$out" | grep -q 'claude-sonnet-5-5/high' && grep -E '^ *old ' <<<"$out" | grep -q 'alias (unpinned)' && ! grep -E '^ *b1 ' <<<"$out" | grep -q unpinned && ok "models: members, alias marked unpinned" || no "members: $out"
! grep -q override <<<"$out" && ok "models: no override without a project" || no "override shown"
out=$($DA agent models --project alpha 2>&1)
grep -E '^ *build ' <<<"$out" | grep -q 'override.*claude-opus-5-5.*xhigh' && grep -E '^ *lead ' <<<"$out" | grep -q 'override.*claude-opus-5-5.*high' && grep -E '^ *test ' <<<"$out" | grep -vq override && ok "models --project: overrides marked" || no "override: $out"
j=$($DA agent models --project alpha --json 2>&1)
jq -e '(.lead.model) and .roles.build.model and (.suggested.auditor.model == "claude-haiku-5-5") and (.members | length > 0) and (.members | map(select(.name == "old"))[0].pinned == false)' <<<"$j" >/dev/null && ok "models --json is one object with lead, roles, suggested, members" || no "json: $j"
jq -e '.roles.build.override.model == "claude-opus-5-5" and .roles.build.model == "claude-sonnet-5-5"' <<<"$j" >/dev/null && ok "json carries the default and the project value" || no "json shape"
$DA agent models --json | jq -e 'keys == ["lead","members","roles","suggested"]' >/dev/null && ok "json without a project" || no "json keys"
[ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "models is read-only" || no "models wrote"
shellcheck -x -S warning lib/agent.sh lib/project.sh tests/test_models.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"
exit $fail
