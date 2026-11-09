#!/usr/bin/env bash
# Methodologies: list, show, check, the rendered scaffold, deployment options, and your own. Run: tests/test_methodology.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s
mkdir -p "$HOME" "$T/c"

$DA methodology list | grep -q "^gitflow .*built-in" && ok "list shows the built-in methodology" || no "list: $($DA methodology list)"
$DA methodology check >/dev/null 2>&1 && ok "the built-in methodology checks out" || no "check: $($DA methodology check 2>&1)"
$DA methodology show gitflow | grep -q "release/{version}" && ok "show prints the branch model" || no "show"
out=$($DA methodology files gitflow --param project=acme --param test_command="make check" --param version=0.3.0 2>&1)
for f in README.md VERSION CHANGELOG.md CONTRIBUTING.md CLAUDE.md .gitignore .github/workflows/test.yml; do jq -e --arg f "$f" 'any(.[]; .dest == $f)' <<<"$out" >/dev/null 2>&1 || no "scaffold lacks $f"; done
jq -r '.[] | select(.dest=="VERSION") | .content' <<<"$out" | grep -qx 0.3.0 && ok "the version parameter fills VERSION" || no "VERSION: $out"
jq -r '.[] | select(.dest==".github/workflows/test.yml") | .content' <<<"$out" | grep -q 'run: make check' && ok "the test command fills the CI workflow" || no "workflow"
jq -r '.[] | select(.dest==".github/workflows/test.yml") | .content' <<<"$out" | grep -qF '${{ github.ref }}' && ok "a template's own {{ }} syntax is left alone" || no "github expression changed"
wf() { jq -r '.[] | select(.dest==".github/workflows/test.yml") | .content' <<<"$1"; }
wf "$out" | grep -qx '    timeout-minutes: 30' && ok "the CI job's time limit is the ci_timeout_minutes default" || no "default timeout: $(wf "$out")"
out2=$($DA methodology files gitflow --param project=acme --param ci_timeout_minutes=45 2>&1)
wf "$out2" | grep -qx '    timeout-minutes: 45' && ! wf "$out2" | grep -q '{{ci_timeout_minutes}}' && ok "--param ci_timeout_minutes fills the CI job's time limit" || no "timeout 45: $(wf "$out2")"
for v in 0 abc 3.5 "45 minutes" -5; do $DA methodology files gitflow --param project=acme --param "ci_timeout_minutes=$v" >/dev/null 2>&1 && no "ci_timeout_minutes=$v was accepted" || ok "ci_timeout_minutes=$v is refused (a positive whole number of minutes)"; done
jq -r '.[] | select(.dest==".gitignore") | .content' <<<"$out" | grep -qx '.claude/worktrees/' && jq -r '.[] | select(.dest==".gitignore") | .content' <<<"$out" | grep -qx '.claude/settings.local.json' && ok "the .gitignore excludes Claude Code's worktrees and local settings, not all of .claude" || no ".gitignore lines"
jq -r '.[].content' <<<"$out" | grep -qi qargi && no "the scaffold mentions qargi" || ok "the scaffold carries no reference to qargi"
jq -r '.[].content' <<<"$out" | grep -q '{{[a-z_]*}}' && no "an unfilled placeholder remains" || ok "no declared placeholder is left"
$DA methodology files gitflow >/dev/null 2>&1 && no "a missing project was accepted" || ok "the project parameter is required"
$DA methodology files gitflow --param project=Bad >/dev/null 2>&1 && no "a bad project name was accepted" || ok "a malformed project name is refused"
$DA methodology files gitflow --param project=a --param nope=1 >/dev/null 2>&1 && no "an unknown parameter was accepted" || ok "an unknown parameter is refused"
$DA methodology files gitflow --param project=a --param "test_command=a
b" >/dev/null 2>&1 && no "a multi-line command was accepted" || ok "a multi-line test command is refused"

# declared gates: the scaffold names them where it names the test command; without gates it is as before
GJ='[{"name":"lint","command":"make lint","tier":"feature"},{"name":"pack","command":["make","pack it"],"tier":"release"},{"name":"unit: fast","command":"make check","tier":"feature"}]'
gout=$($DA methodology files gitflow --param project=acme --param test_command="make suite" --param "gates=$GJ" 2>&1)
doc() { jq -r --arg f "$2" '.[] | select(.dest == $f) | .content' <<<"$1"; }
for f in README.md AGENTS.md CLAUDE.md CONTRIBUTING.md; do
  doc "$gout" "$f" | grep -q 'make suite' && no "gates: $f still names the test command" || true
  [ "$(doc "$gout" "$f" | grep -E '^ *(- )?`(lint|unit: fast|pack)` \((feature|release)\): ' | tr -s ' ' | sed 's/^ *//; s/^- //' | tr '\n' '|')" = '`lint` (feature): `make lint`|`unit: fast` (feature): `make check`|`pack` (release): `make '"'"'pack it'"'"'`|' ] \
    && ok "gates: $f lists the gates, the feature tier first, in the order declared, a command given as words as one line" || no "gates $f: $(doc "$gout" "$f" | grep -n 'lint\|unit\|pack')"
done
wfg=$(doc "$gout" .github/workflows/test.yml)
[ "$(grep -c '^    name: ' <<<"$wfg")" = 3 ] && grep -qx "    name: 'unit: fast'" <<<"$wfg" && grep -qx '  gate1:' <<<"$wfg" && grep -qx '  gate3:' <<<"$wfg" && grep -qx "          make 'pack it'" <<<"$wfg" && ! grep -q 'run: make check' <<<"$wfg" && ! grep -qx '  test:' <<<"$wfg" \
  && ok "gates: the workflow has a job for each gate, named after it (a name with a colon is quoted)" || no "gates workflow: $wfg"
# a feature-tier gate runs on every pull request; a release-tier gate only on release and hotfix branches (and by hand), as only a release runs it
[ "$(grep -c '^    if: ' <<<"$wfg")" = 3 ] && [ "$(grep -c "^    if: \${{ 'feature' == 'feature' || startsWith(github.head_ref, 'release/') || startsWith(github.head_ref, 'hotfix/') || github.event_name == 'workflow_dispatch' }}\$" <<<"$wfg")" = 2 ] \
  && [ "$(grep -c "^    if: \${{ 'release' == 'feature' || startsWith(github.head_ref, 'release/') || startsWith(github.head_ref, 'hotfix/') || github.event_name == 'workflow_dispatch' }}\$" <<<"$wfg")" = 1 ] \
  && ok "gates: each job has a condition by tier (release tier only on release and hotfix branches)" || no "gates workflow conditions: $(grep -n 'if:' <<<"$wfg")"
if python3 -c 'import yaml' 2>/dev/null; then
  python3 -I -c 'import sys, yaml
d = yaml.safe_load(sys.stdin.read())
j = d["jobs"]
sys.exit(0 if len(j) == 3 and all(isinstance(v["if"], str) and v["if"].startswith("${{") for v in j.values()) else 1)' <<<"$wfg" \
    && ok "gates: the rendered workflow is valid YAML and every job has its condition" || no "gates workflow does not parse as expected"
fi
doc "$gout" CONTRIBUTING.md | grep -q 'run in parallel, not in order; a job of a release-tier gate runs only on a pull request from' && ! doc "$($DA methodology files gitflow --param project=acme --param test_command='make suite' 2>&1)" CONTRIBUTING.md | grep -q 'in parallel' \
  && ok "gates: CONTRIBUTING says CI runs the gates in parallel and the release tier only on release branches" || no "gates CONTRIBUTING lacks the CI clause"
mkdir -p "$T/ci/.github/workflows"; doc "$gout" .github/workflows/test.yml > "$T/ci/.github/workflows/test.yml"; jq -n --argjson g "$GJ" '{gates: $g}' > "$T/ci/answers.json"
[ -z "$(python3 lib/gates.py scan "$T/ci/answers.json" "$T/ci")" ] && ok "gates: the CI scan of release verify matches every job of the rendered workflow" || no "gates scan: $(python3 lib/gates.py scan "$T/ci/answers.json" "$T/ci")"
# a name that needs a JSON escape (a quote, a backslash, a non-ASCII letter) is written so that the scan reads it back and matches the job
HG=$(jq -nc '[{name:"say \"hi\"",command:"true",tier:"feature"},{name:"a\\b",command:"true",tier:"feature"},{name:"tést ü",command:"true",tier:"release"},{name:"it'"'"'s",command:"true",tier:"feature"}]')
hout=$($DA methodology files gitflow --param project=acme --param "gates=$HG" 2>&1)
mkdir -p "$T/ci2/.github/workflows"; doc "$hout" .github/workflows/test.yml > "$T/ci2/.github/workflows/test.yml"; jq -n --argjson g "$HG" '{gates: $g}' > "$T/ci2/answers.json"
[ -n "$(doc "$hout" .github/workflows/test.yml)" ] && [ -z "$(python3 lib/gates.py scan "$T/ci2/answers.json" "$T/ci2")" ] && ok "gates: names with a quote, a backslash, a non-ASCII letter and an apostrophe are read back by the CI scan" || no "gates hostile names: $(python3 lib/gates.py scan "$T/ci2/answers.json" "$T/ci2")"
if python3 -c 'import yaml' 2>/dev/null; then
  python3 -I -c 'import sys, json, yaml
d = yaml.safe_load(open(sys.argv[1]).read())
names = [j["name"] for j in d["jobs"].values()]
sys.exit(0 if sorted(names) == sorted(g["name"] for g in json.loads(sys.argv[2])) else 1)' "$T/ci2/.github/workflows/test.yml" "$HG" && ok "gates: the YAML parser reads each hostile name back unchanged" || no "gates hostile names parse differently"
fi
# a backtick in a gate does not end the inline code of the markdown files: the span is fenced by a longer run of backticks
BG=$(jq -nc '[{name:"a`b",command:"echo `date` ``x``",tier:"feature"},{name:"`edge`",command:"`cmd`",tier:"release"}]')
bout=$($DA methodology files gitflow --param project=acme --param "gates=$BG" 2>&1)
for f in README.md AGENTS.md CLAUDE.md CONTRIBUTING.md; do
  [ "$(doc "$bout" "$f" | grep -c -F -e '``a`b`` (feature): ``` echo `date` ``x`` ```' -e '`` `edge` `` (release): `` `cmd` ``')" = 2 ] \
    && ok "gates: $f writes a gate with backticks as inline code that holds together" || no "gates backticks $f: $(doc "$bout" "$f" | grep -n 'edge\|date')"
done
grep -qF '${{ github.ref }}' <<<"$wfg" && ! grep -q '{{#\|{{/\|{{^\|{{gate' <<<"$gout" && ok "gates: no template marker is left and the file's own {{ }} syntax stays" || no "gates markers: $(grep -n '{{' <<<"$gout")"
[ "$gout" = "$($DA methodology files gitflow --param project=acme --param test_command="make suite" --param "gates=$GJ" 2>&1)" ] && ok "gates: the output is deterministic" || no "gates: output differs between runs"
nog=$($DA methodology files gitflow --param project=acme --param test_command="make suite" 2>&1)
[ "$nog" = "$($DA methodology files gitflow --param project=acme --param test_command="make suite" --param 'gates=[]' 2>&1)" ] && [ "$nog" = "$($DA methodology files gitflow --param project=acme --param test_command="make suite" --param 'gates=' 2>&1)" ] \
  && doc "$nog" AGENTS.md | grep -qx -- '- Tests: `make suite`.' && ! jq -r '.[].content' <<<"$nog" | grep -qi 'declared gates' && ok "gates: none, [] and empty give the scaffold with the test command" || no "gates none"
for bad in 'nope' '{"name":"x"}' '[{"name":"x","command":"c","tier":"later"}]' '[{"name":"x","command":"c","tier":"feature"},{"name":"x","command":"d","tier":"release"}]'; do
  $DA methodology files gitflow --param project=acme --param "gates=$bad" >/dev/null 2>&1 && no "gates=$bad was accepted" || ok "gates=$bad is refused"
done
# a Unicode line break (U+2028, U+2029, U+0085) ends a line in YAML and in the markdown: refused in a gate name or command and in a parameter
for esc in 2028 2029 0085; do
  lb=$(python3 -c "import sys; sys.stdout.write(chr(0x$esc))")
  gn="[{\"name\":\"n\\u$esc\",\"command\":\"c\",\"tier\":\"feature\"}]"; gc="[{\"name\":\"n\",\"command\":\"c\\u$esc\",\"tier\":\"feature\"}]"
  $DA methodology files gitflow --param project=acme --param "gates=$gn" >/dev/null 2>&1 && no "a gate name with U+$esc was accepted" || ok "a gate name with U+$esc is refused"
  $DA methodology files gitflow --param project=acme --param "gates=$gc" >/dev/null 2>&1 && no "a gate command with U+$esc was accepted" || ok "a gate command with U+$esc is refused"
  $DA methodology files gitflow --param project=acme --param "test_command=a${lb}b" >/dev/null 2>&1 && no "a test_command with U+$esc was accepted" || ok "a parameter with U+$esc is refused"
done
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
$DA methodology show gitflow | grep -q "^  site  *when site.enabled: qargi release site {version}" && ok "show lists the after_release step" || no "show after_release: $($DA methodology show gitflow)"
jq '.scaffold=[{"src":"README.md","dest":"README.md"}] | .after_release=[{"id":"site","when":"site.enabled","next":"rm -rf /"}]' methodologies/gitflow/methodology.json | jq '.name="lean"' > "$M/methodology.json"
$DA methodology check lean 2>&1 | grep -q "after_release step site: next is the one qargi command line" && ok "an after_release step that is no qargi command fails the check" || no "after_release next"
jq '.after_release=[{"id":"site","when":"Site Enabled","next":"qargi x"},{"id":"site","when":"a.b","next":"qargi y","extra":1}]' "$M/methodology.json" > "$M/m.tmp" && mv "$M/m.tmp" "$M/methodology.json"
out=$($DA methodology check lean 2>&1)
grep -q "when is the dotted name of a project answer" <<<"$out" && grep -q "an object {id, when, next, help}" <<<"$out" && ok "a bad when and an unknown key of an after_release step fail the check" || no "after_release check: $out"
mkdir -p "$T/c/methodologies/gitflow"; cp methodologies/gitflow/methodology.json "$T/c/methodologies/gitflow/"
$DA methodology check 2>&1 | grep -q "yours is never used" && ok "a methodology that shadows a built-in is reported" || no "shadow"
rm -rf "$T"
exit $fail
