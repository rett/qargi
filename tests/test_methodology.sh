#!/usr/bin/env bash
# Methodologies: list, show, check, the rendered scaffold, deployment options, and your own. Run: tests/test_methodology.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$HOME" "$T/c"

$DA methodology list | grep -q "^gitflow .*built-in" && ok "list shows the built-in methodology" || no "list: $($DA methodology list)"
$DA methodology check >/dev/null 2>&1 && ok "the built-in methodology checks out" || no "check: $($DA methodology check 2>&1)"
$DA methodology show gitflow | grep -q "feature/{version}" && ok "show prints the branch model" || no "show"
out=$($DA methodology files gitflow --param project=acme --param test_command="make check" --param version=0.3.0 2>&1)
for f in README.md VERSION CHANGELOG.md CONTRIBUTING.md CLAUDE.md .gitignore .github/workflows/test.yml; do jq -e --arg f "$f" 'any(.[]; .dest == $f)' <<<"$out" >/dev/null 2>&1 || no "scaffold lacks $f"; done
jq -r '.[] | select(.dest=="VERSION") | .content' <<<"$out" | grep -qx 0.3.0 && ok "the version parameter fills VERSION" || no "VERSION: $out"
jq -r '.[] | select(.dest==".github/workflows/test.yml") | .content' <<<"$out" | grep -q 'run: make check' && ok "the test command fills the CI workflow" || no "workflow"
jq -r '.[] | select(.dest==".github/workflows/test.yml") | .content' <<<"$out" | grep -qF '${{ github.ref }}' && ok "a template's own {{ }} syntax is left alone" || no "github expression changed"
jq -r '.[] | select(.dest==".gitignore") | .content' <<<"$out" | grep -qx '.claude/worktrees/' && jq -r '.[] | select(.dest==".gitignore") | .content' <<<"$out" | grep -qx '.claude/settings.local.json' && ok "the .gitignore excludes Claude Code's worktrees and local settings, not all of .claude" || no ".gitignore lines"
jq -r '.[].content' <<<"$out" | grep -qi qargi && no "the scaffold mentions qargi" || ok "the scaffold carries no reference to qargi"
jq -r '.[].content' <<<"$out" | grep -q '{{[a-z_]*}}' && no "an unfilled placeholder remains" || ok "no declared placeholder is left"
$DA methodology files gitflow >/dev/null 2>&1 && no "a missing project was accepted" || ok "the project parameter is required"
$DA methodology files gitflow --param project=Bad >/dev/null 2>&1 && no "a bad project name was accepted" || ok "a malformed project name is refused"
$DA methodology files gitflow --param project=a --param nope=1 >/dev/null 2>&1 && no "an unknown parameter was accepted" || ok "an unknown parameter is refused"
$DA methodology files gitflow --param project=a --param "test_command=a
b" >/dev/null 2>&1 && no "a multi-line command was accepted" || ok "a multi-line test command is refused"
$DA methodology deployment gitflow | grep -q "^github-release .*can be done for you" && ok "deployment options are listed" || no "deployment list"
$DA methodology deployment gitflow container-image | grep -q "Containerfile" && ok "an option's instructions are printed" || no "instructions"
$DA methodology deployment gitflow nosuch >/dev/null 2>&1 && no "an unknown option answered" || ok "an unknown deployment option is refused"

# your own
M=$T/c/methodologies/lean; mkdir -p "$M/scaffold"
jq '.name="lean" | .scaffold=[{"src":"README.md","dest":"README.md"}]' methodologies/gitflow/methodology.json > "$M/methodology.json"
cp methodologies/gitflow/scaffold/README.md "$M/scaffold/README.md"
$DA methodology list | grep -q "^lean .*user" && $DA methodology check lean >/dev/null 2>&1 && ok "a methodology of yours is listed and checks out" || no "user methodology"
jq 'length' <<<"$($DA methodology files lean --param project=x)" | grep -qx 1 && ok "and renders" || no "render lean"
jq '.scaffold=[{"src":"missing.md","dest":"../escape"}]' "$M/methodology.json" > "$M/m.tmp" && mv "$M/m.tmp" "$M/methodology.json"
$DA methodology check lean >/dev/null 2>&1 && no "an escaping scaffold path passed" || ok "a scaffold path that leaves the project fails the check"
mkdir -p "$T/c/methodologies/gitflow"; cp methodologies/gitflow/methodology.json "$T/c/methodologies/gitflow/"
$DA methodology check 2>&1 | grep -q "yours is never used" && ok "a methodology that shadows a built-in is reported" || no "shadow"
rm -rf "$T"
exit $fail
