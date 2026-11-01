#!/usr/bin/env bash
# Members: qargi agent add | list | for | rename | remove, in a throwaway home. Run: tests/test_agent.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects"
A=$HOME/.claude/agents
fm() { $DA agent for "$@" --json 2>/dev/null | jq -r .member; }   # the member name only

out=$($DA agent add forge --abilities build,test 2>&1) && [ -f "$A/forge.md" ] && ok "add renders the member definition" || no "add: $out"
grep -q '^name: forge$' "$A/forge.md" && grep -q 'build, test' "$A/forge.md" && grep -q '^model: claude-sonnet-5-5$' "$A/forge.md" && grep -q '^effort: high$' "$A/forge.md" && ok "it carries the name, abilities and model" || no "rendered: $(head -5 "$A/forge.md")"
grep -q 'matcher: "Bash|Edit|Write|NotebookEdit|Read|Grep"' "$A/forge.md" && grep -q 'command: "qargi __guard"$' "$A/forge.md" && ok "the guard covers Bash and the edit tools" || no "hook"
grep -q 'onFailure: "block"' "$A/forge.md" && grep -q '^ *timeout: [0-9]' "$A/forge.md" && ok "the guard hook blocks when it fails or times out" || no "hook failure setting"
! grep -q '{{' "$A/forge.md" && ok "no placeholder is left" || no "placeholder left"
$DA agent add scribe --abilities write --model opus --effort medium >/dev/null 2>&1 && grep -q '^model: opus$' "$A/scribe.md" && ok "model is the one given" || no "model"
$DA agent add omni >/dev/null 2>&1 && jq -e '.omni.abilities == ["build","write","review","test"]' "$T/c/agents.json" >/dev/null && ok "a member serves all four abilities by default" || no "default abilities"
for bad in Forge "two--dashes" "-x" general-purpose Explore statusline-setup review lead forge; do
  $DA agent add "$bad" >/dev/null 2>&1 && no "the name '$bad' was accepted" || ok "the name '$bad' is refused"
done
$DA agent add other --abilities build,deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
touch "$A/taken.md"; $DA agent add taken >/dev/null 2>&1 && no "an existing file was replaced" || ok "a definition that exists is never replaced"

[ "$(fm build)" = forge ] && [ "$(fm test)" = forge ] && ok "for: the first member registered for an ability" || no "for build: $(fm build)"
[ "$(fm write)" = scribe ] && [ "$(fm test)" = forge ] && ok "for: each ability finds its member" || no "for write/test"
$DA agent for review >/dev/null 2>&1 && no "a member that can write was returned for review: $($DA agent for review)" || ok "for: a member serving build and review (write class) never serves review"
$DA agent list | grep -q "scribe .*write .*user .*opus/medium" && ok "list shows abilities, scope, model and effort" || no "list: $($DA agent list)"
$DA agent add judge --abilities review >/dev/null 2>&1 && grep -q 'command: "qargi __guard --class read-only"' "$A/judge.md" && ok "a member that only reviews is read-only by class in its hook" || no "review class"
! grep -q -- '--class' "$A/forge.md" && ! grep -q -- '--class' "$A/scribe.md" 2>/dev/null && ok "a member with other abilities names no class" || no "class on a writer"
$DA agent remove judge >/dev/null 2>&1

# a project's own member comes first inside its repository
git init -q "$T/repo"
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high"}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
$DA agent add smith --abilities build --project alpha >/dev/null 2>&1 && [ -f "$T/repo/.claude/agents/smith.md" ] && ok "--project puts it in the repository" || no "project add"
grep -qx '/.claude/agents/smith.md' "$T/repo/.git/info/exclude" && [ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "and hides it from git" || no "exclude"
[ "$(cd "$T/repo" && fm build)" = smith ] && [ "$(fm build)" = forge ] && [ "$(fm build --project alpha)" = smith ] && ok "for prefers the project's own member" || no "project for"

$DA agent rename forge anvil >/dev/null 2>&1 && [ -f "$A/anvil.md" ] && [ ! -e "$A/forge.md" ] && grep -q '^name: anvil$' "$A/anvil.md" && [ "$(fm test)" = anvil ] && ok "rename moves the definition and the record" || no "rename"
$DA agent rename anvil scribe >/dev/null 2>&1 && no "rename onto a member" || ok "rename refuses a name in use"
sed -i '/onFailure/d;/timeout: 20/d' "$A/anvil.md"; cp "$A/anvil.md" "$T/old.md"
$DA agent refresh anvil >/dev/null 2>&1 && grep -q 'onFailure: "block"' "$A/anvil.md" && grep -q '^name: anvil$' "$A/anvil.md" && grep -q 'build, test' "$A/anvil.md" && [ "$(fm test)" = anvil ] && ok "refresh re-renders from the current definition, keeping name and abilities" || no "refresh"
$DA agent refresh anvil 2>&1 | grep -q "is current" && ok "refresh of a current member says so" || no "refresh idempotent"
$DA agent refresh nobody >/dev/null 2>&1 && no "refresh of an unknown member" || ok "refresh refuses an unknown member"
$DA agent remove anvil >/dev/null 2>&1 && [ ! -e "$A/anvil.md" ] && [ "$(fm test)" = omni ] && ok "remove deletes the definition and the record" || no "remove"
$DA agent remove omni >/dev/null 2>&1; $DA agent for review >/dev/null 2>&1 && no "for found a removed member" || ok "for fails, with a hint, when no member serves the ability"
$DA agent for review 2>&1 | grep -q "qargi agent add NAME --abilities review" && ok "the hint names the command" || no "hint"

# a base name takes only the abilities of its class
$DA agent add worker --abilities review >/dev/null 2>&1 && no "worker accepted review" || ok "add worker refuses an ability of the read-only class"
$DA agent add worker --abilities build,review >/dev/null 2>&1 && no "worker accepted build,review" || ok "add worker refuses a mixed list"
$DA agent add reviewer --abilities build >/dev/null 2>&1 && no "reviewer accepted build" || ok "add reviewer refuses an ability of the write class"
$DA agent add reviewer --abilities review,test >/dev/null 2>&1 && no "reviewer accepted review,test" || ok "add reviewer refuses a mixed list"
$DA agent add worker --abilities tw >/dev/null 2>&1; [ ! -e "$A/worker.md" ] && ok "a refused base leaves no definition" || no "worker.md written"
e=$($DA agent add reviewer --abilities write 2>&1); grep -q 'reviewer' <<<"$e" && grep -q 'read-only' <<<"$e" && ok "and says which class the base has" || no "base message: $e"
mkdir -p "$T/c/roles/tw"; jq -n '{class:"write"}' > "$T/c/roles/tw/role.json"; echo "the tw role" > "$T/c/roles/tw/ROLE.md"
$DA agent add worker --abilities tw,test >/dev/null 2>&1 && jq -e '.worker.abilities == ["tw","test"]' "$T/c/agents.json" >/dev/null && ok "a custom write role fits the worker" || no "worker tw"
$DA agent remove worker >/dev/null 2>&1
$DA agent add worker >/dev/null 2>&1 && jq -e '.worker.abilities == ["build","write","test"]' "$T/c/agents.json" >/dev/null && ok "add worker with no list serves the base's abilities" || no "worker default"
$DA agent add reviewer >/dev/null 2>&1 && jq -e '.reviewer.abilities == ["review"]' "$T/c/agents.json" >/dev/null && grep -q -- '--class read-only' "$A/reviewer.md" && ok "add reviewer with no list serves review, read-only by class" || no "reviewer default"
$DA agent remove worker >/dev/null 2>&1; $DA agent remove reviewer >/dev/null 2>&1

# profiles: the base member, the legacy order, the class rules
for m in $($DA agent list | cut -d' ' -f1); do $DA agent remove "$m" >/dev/null 2>&1; done
for pair in "tw:write" "ro:read-only"; do
  r=${pair%%:*}; c=${pair##*:}; mkdir -p "$T/c/roles/$r"
  jq -n --arg c "$c" '{class:$c}' > "$T/c/roles/$r/role.json"; echo "the $r role" > "$T/c/roles/$r/ROLE.md"
done
$DA agent add builder --abilities build,test >/dev/null 2>&1
[ "$($DA agent for build)" = "builder sonnet high build" ] && ok "for: one line, MEMBER MODEL EFFORT PROFILE" || no "plain line: $($DA agent for build)"
jq -e . <<<"$($DA agent for build --json)" >/dev/null && $DA agent for build --json | jq -e '.member == "builder" and .legacy == true and .role == "build" and .class == "write" and .profile == "build" and .profile_source == "shipped" and .base == "worker"
  and .member_scope == "user" and .tier == "balanced" and .model == "sonnet" and .model_id == "claude-sonnet-5-5" and .effort == "high" and .opt_in == false and (.purpose | length > 0)' >/dev/null && ok "for --json: the whole answer, legacy when only an older member serves" || no "json: $($DA agent for build --json)"
$DA agent add worker --abilities build,write,test >/dev/null 2>&1
[ "$($DA agent for build)" = "worker sonnet high build" ] && [ "$($DA agent for test)" = "worker sonnet low test" ] && [ "$($DA agent for write)" = "worker sonnet medium write" ] && ok "for: the base member wins over an older one" || no "worker wins: $($DA agent for build)"
$DA agent for build --json | jq -e '.member == "worker" and .legacy == false' >/dev/null && ok "and is not legacy" || no "worker json"
$DA agent for tw --json | jq -e '.member == "worker" and .legacy == false and .profile == "build" and .profile_source == "class-fallback" and .class == "write"' >/dev/null && ok "a custom write role with no profile uses the build row" || no "custom write: $($DA agent for tw --json 2>&1)"
$DA agent for ro >/dev/null 2>&1 && no "a read-only role resolved with no read-only member" || ok "a read-only role never resolves to a write member"
$DA agent add judge --abilities review >/dev/null 2>&1
[ "$($DA agent for review)" = "judge opus high review" ] && $DA agent for review --json | jq -e '.legacy == true and .member == "judge"' >/dev/null && ok "review: the legacy read-only member when there is no reviewer" || no "legacy review: $($DA agent for review)"
[ "$($DA agent for ro)" = "judge opus high review" ] && $DA agent for ro --json | jq -e '.profile_source == "class-fallback" and .profile == "review"' >/dev/null && ok "a custom read-only role uses the review row" || no "custom ro"
$DA agent add mix --abilities build,review >/dev/null 2>&1
$DA agent remove judge >/dev/null 2>&1
$DA agent for review >/dev/null 2>&1 && no "mixed member returned for review: $($DA agent for review)" || ok "a mixed member is write class and never serves review"
$DA agent for build --json | jq -e '.member == "worker"' >/dev/null && ok "a mixed member still serves its write abilities" || no "mix build"
$DA agent add reviewer --abilities review >/dev/null 2>&1
[ "$($DA agent for review)" = "reviewer opus high review" ] && [ "$($DA agent for review --profile auditor)" = "reviewer haiku low auditor" ] && ok "for --profile auditor: the reviewer at haiku low" || no "auditor: $($DA agent for review --profile auditor)"
[ "$($DA agent for review --profile advisor)" = "reviewer opus high advisor" ] && $DA agent for review --profile researcher --json | jq -e '.model == "fable" and .opt_in == true and .effort == "high"' >/dev/null && ok "advisor and researcher" || no "advisor/researcher"
$DA agent for ro --profile auditor | grep -q '^reviewer haiku low auditor$' && ok "a custom read-only role can take a read-only profile" || no "ro auditor"
for args in "review --profile build" "build --profile review" "build --profile auditor" "tw --profile review" "ro --profile build" "build --profile lead"; do
  e=$($DA agent for $args 2>&1 >/dev/null); rc=$?
  { [ $rc = 2 ] && [ -n "$e" ]; } && ok "for $args: refused (exit 2) with a reason" || no "for $args: rc=$rc $e"
done
$DA agent for build --profile nosuch >/dev/null 2>&1 && no "an unknown profile was accepted" || ok "an unknown profile is an error"
$DA agent for build --profile 'Bad Name' >/dev/null 2>&1 && no "a bad profile name was accepted" || ok "a bad profile name is an error"
# a member named like the base but of the wrong class is not the base member
jq '.reviewer.abilities = ["build","review"]' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"
$DA agent for review >/dev/null 2>&1 && no "a mixed reviewer served review" || ok "a member named reviewer that can write is not used for review"
jq '.reviewer.abilities = ["review"]' "$T/c/agents.json" > "$T/a.json" && mv "$T/a.json" "$T/c/agents.json"

# a project's profiles
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-haiku-5-5",effort:"low"}},
  profiles:{wrong:{base:"worker",abilities:["review"]}, nobase:{base:"nosuch"}, pm:{base:"worker",model:"claude-opus-5-5"},
    odd:{base:"worker",model:"claude-odd-9"}, scout:{base:"reviewer",tier:"fast",effort:"medium",purpose:"looks around"},
    auditor:{effort:"high"}, junk:7, bad:{base:[],tier:3}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
e=$($DA agent for build --profile wrong --project alpha 2>&1); rc=$?
{ [ $rc = 2 ] && grep -qi 'abilit' <<<"$e"; } && ok "a project profile whose abilities differ in class from its base is refused at dispatch" || no "wrong abilities: rc=$rc $e"
$DA agent for review --profile wrong --project alpha >/dev/null 2>&1; [ $? = 2 ] && ok "whatever the role" || no "wrong, review"
e=$($DA agent for build --profile nobase --project alpha 2>&1); rc=$?
{ [ $rc = 2 ] && grep -q 'nosuch' <<<"$e"; } && ok "a project profile with an unknown base is refused" || no "nobase: rc=$rc $e"
[ "$($DA agent for build --profile pm --project alpha)" = "worker opus medium pm" ] && $DA agent for build --profile pm --project alpha --json | jq -e '.model == "opus" and .model_id == "claude-opus-5-5" and .profile_source == "project"' >/dev/null && ok "a full model id in a project profile maps to its alias" || no "pm: $($DA agent for build --profile pm --project alpha 2>&1)"
out=$($DA agent for build --profile odd --project alpha 2>$T/err); [ "$out" = "worker - medium odd" ] && grep -q "claude-odd-9" "$T/err" && grep -qi 'definition' "$T/err" && ok "a model id with no alias prints - and warns that the member's definition applies" || no "odd: $out / $(cat "$T/err")"
$DA agent for build --profile odd --project alpha --json 2>/dev/null | jq -e '.model == null and .model_id == "claude-odd-9"' >/dev/null && ok "--json: model null, the id kept" || no "odd json"
[ "$($DA agent for review --profile scout --project alpha)" = "reviewer haiku medium scout" ] && ok "a project-only profile" || no "scout"
[ "$($DA agent for review --profile auditor --project alpha)" = "reviewer haiku high auditor" ] && ok "a project entry merges over the shipped profile of its name" || no "auditor merge: $($DA agent for review --profile auditor --project alpha)"
[ "$($DA agent for build --project alpha)" = "worker haiku low build" ] && ok "a role answer still sets the profile named after the role" || no "legacy roles: $($DA agent for build --project alpha)"
[ "$($DA agent for test --project alpha)" = "worker sonnet low test" ] && ok "and only that one" || no "test unaffected"
$DA agent for build --profile junk --project alpha >/dev/null 2>&1 && no "a malformed entry was usable" || ok "a malformed entry is ignored, not a crash"
jq '.profiles = 5' "$T/c/projects/alpha.json" > "$T/a.json" && mv "$T/a.json" "$T/c/projects/alpha.json"
[ "$($DA agent for build --project alpha)" = "worker haiku low build" ] && ok "profiles of the wrong type are ignored" || no "profiles=5"
rm -rf "$T"
exit $fail
