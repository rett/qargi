#!/usr/bin/env bash
# Members: qargi agent add | list | for | rename | remove, in a throwaway home. Run: tests/test_agent.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects"
A=$HOME/.claude/agents

out=$($DA agent add forge --abilities build,test 2>&1) && [ -f "$A/forge.md" ] && ok "add renders the member definition" || no "add: $out"
grep -q '^name: forge$' "$A/forge.md" && grep -q 'build, test' "$A/forge.md" && grep -q '^model: sonnet$' "$A/forge.md" && ok "it carries the name, abilities and model" || no "rendered: $(head -5 "$A/forge.md")"
grep -q 'matcher: "Bash|Edit|Write|NotebookEdit"' "$A/forge.md" && grep -q 'command: "qargi __guard"' "$A/forge.md" && ok "the guard covers Bash and the edit tools" || no "hook"
grep -q 'onFailure: "block"' "$A/forge.md" && grep -q '^ *timeout: [0-9]' "$A/forge.md" && ok "the guard hook blocks when it fails or times out" || no "hook failure setting"
! grep -q '{{' "$A/forge.md" && ok "no placeholder is left" || no "placeholder left"
$DA agent add scribe --abilities write --model opus --effort medium >/dev/null 2>&1 && grep -q '^model: opus$' "$A/scribe.md" && ok "model is the one given" || no "model"
$DA agent add worker >/dev/null 2>&1 && jq -e '.worker.abilities == ["build","write","review","test"]' "$T/c/agents.json" >/dev/null && ok "a member serves all four abilities by default" || no "default abilities"
for bad in Forge "two--dashes" "-x" general-purpose Explore statusline-setup review lead forge; do
  $DA agent add "$bad" >/dev/null 2>&1 && no "the name '$bad' was accepted" || ok "the name '$bad' is refused"
done
$DA agent add other --abilities build,deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
touch "$A/taken.md"; $DA agent add taken >/dev/null 2>&1 && no "an existing file was replaced" || ok "a definition that exists is never replaced"

[ "$($DA agent for build)" = forge ] && [ "$($DA agent for test)" = forge ] && ok "for: the first member registered for an ability" || no "for build: $($DA agent for build)"
[ "$($DA agent for write)" = scribe ] && [ "$($DA agent for review)" = worker ] && ok "for: each ability finds its member" || no "for write/review"
$DA agent list | grep -q "scribe .*write .*user .*opus/medium" && ok "list shows abilities, scope, model and effort" || no "list: $($DA agent list)"

# a project's own member comes first inside its repository
git init -q "$T/repo"
jq -n --arg p "$T/repo" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/alpha",path:$p,long_lived:["main"]},
  roles:{build:{base:"main",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high"}},memory:{},budget_cents:500}' > "$T/c/projects/alpha.json"
$DA agent add smith --abilities build --project alpha >/dev/null 2>&1 && [ -f "$T/repo/.claude/agents/smith.md" ] && ok "--project puts it in the repository" || no "project add"
grep -qx '/.claude/agents/smith.md' "$T/repo/.git/info/exclude" && [ -z "$(git -C "$T/repo" status --porcelain)" ] && ok "and hides it from git" || no "exclude"
[ "$(cd "$T/repo" && $DA agent for build)" = smith ] && [ "$($DA agent for build)" = forge ] && [ "$($DA agent for build --project alpha)" = smith ] && ok "for prefers the project's own member" || no "project for"

$DA agent rename forge anvil >/dev/null 2>&1 && [ -f "$A/anvil.md" ] && [ ! -e "$A/forge.md" ] && grep -q '^name: anvil$' "$A/anvil.md" && [ "$($DA agent for test)" = anvil ] && ok "rename moves the definition and the record" || no "rename"
$DA agent rename anvil scribe >/dev/null 2>&1 && no "rename onto a member" || ok "rename refuses a name in use"
$DA agent remove anvil >/dev/null 2>&1 && [ ! -e "$A/anvil.md" ] && [ "$($DA agent for test)" = worker ] && ok "remove deletes the definition and the record" || no "remove"
$DA agent remove worker >/dev/null 2>&1; $DA agent for review >/dev/null 2>&1 && no "for found a removed member" || ok "for fails, with a hint, when no member serves the ability"
$DA agent for review 2>&1 | grep -q "qargi agent add NAME --abilities review" && ok "the hint names the command" || no "hint"
rm -rf "$T"
exit $fail
