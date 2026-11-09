#!/usr/bin/env bash
# qargi project new: plan first, then the directory, the repository, the branches and the generic files.
# Run: tests/test_new.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c"
D=$T/acme

out=$($DA project new acme --dir "$D" --param test_command="make check" 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
[ -n "$tok" ] && grep -q "^    CHANGELOG.md" <<<"$out" && grep -q "github-release .*can be done for you" <<<"$out" && ok "the plan lists the files and the deployment options" || no "plan: $out"
[ ! -e "$D" ] && ok "showing the plan creates nothing" || no "created without approval"
$DA project new acme --dir "$D" --param test_command="make check" --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong plan token is refused"
[ ! -e "$D" ] && ok "and creates nothing" || no "created on a wrong token"
$DA project new acme --dir "$D" --param test_command="make test" --plan "$tok" --approved go >/dev/null 2>&1 && no "options changed after the plan" || ok "the plan covers the options: a changed one is refused"

out=$($DA project new acme --dir "$D" --param test_command="make check" --deployment github-release --plan "$tok" --approved go 2>&1) && no "a changed --deployment was accepted with the old token" || ok "adding an option changes the plan"
out=$($DA project new acme --dir "$D" --param test_command="make check" --deployment github-release 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
out=$($DA project new acme --dir "$D" --param test_command="make check" --deployment github-release --plan "$tok" --approved "go ahead" 2>&1); rc=$?
[ $rc = 0 ] && [ -d "$D/.git" ] && ok "with the token and an approval the project is created" || no "create rc=$rc: $out"
[ "$(git -C "$D" branch --show-current)" = develop ] && git -C "$D" rev-parse -q --verify master >/dev/null && ok "master and develop exist and work starts on develop" || no "branches: $(git -C "$D" branch -a)"
[ "$(git -C "$D" log --oneline | wc -l)" = 1 ] && [ -z "$(git -C "$D" status --porcelain)" ] && ok "one first commit and a clean tree" || no "history"
grep -q 'run: make check' "$D/.github/workflows/test.yml" && grep -qx '0.1.0' "$D/VERSION" && ok "the parameters are filled in" || no "params"
grep -rqi qargi "$D" --exclude-dir=.git && no "the project mentions qargi" || ok "nothing in the project mentions qargi"
[ "$(head -1 "$D/CLAUDE.md")" = "@AGENTS.md" ] && grep -qx '## Development environment' "$D/AGENTS.md" && grep -q '`make bootstrap`' "$D/AGENTS.md" && grep -q '`make -n bootstrap`' "$D/AGENTS.md" \
  && grep -q '`make doctor`' "$D/AGENTS.md" && grep -q '`make check`' "$D/AGENTS.md" && ok "CLAUDE.md imports AGENTS.md, which has the Development environment section with the project's commands" || no "AGENTS.md: $(cat "$D/AGENTS.md")"
dout=$(make -C "$D" doctor 2>&1); drc=$?
[ "$drc" != 0 ] && grep -q '^missing: ' <<<"$dout" && make -C "$D" bootstrap 2>&1 | grep -q 'nothing is installed yet' && ok "the doctor stub exits non-zero with a missing line until it is filled in; the bootstrap stub says what to fill in" || no "stubs: rc=$drc $dout"
ev=$($DA env show --repo "$D" 2>&1)
grep -q "^section:.*AGENTS.md" <<<"$ev" && grep -q "^bootstrap:.*make bootstrap" <<<"$ev" && ! grep -q "^gap:" <<<"$ev" && ok "env show finds the section and the targets of a new project and no gap" || no "env show: $ev"
grep -q "gh release create" <<<"$out" && ok "the chosen deployment's instructions are printed" || no "instructions: $out"
[ ! -e "$T/c/projects/acme.json" ] && grep -q "no --url" <<<"$($DA project new other --dir "$T/o" 2>&1)" && ok "without --url no answers are stored" || no "answers stored without a url"

$DA project new acme --dir "$D" >/dev/null 2>&1 && no "an existing directory was reused" || ok "a directory that is not empty is refused"
mkdir "$T/empty"; $DA project new e1 --dir "$T/empty" >/dev/null 2>&1 && ok "an empty existing directory is accepted" || no "empty dir"
$DA project new Bad >/dev/null 2>&1 && no "a bad name was accepted" || ok "a malformed name is refused"
$DA project new zz --dir "$T/zz" --deployment nosuch >/dev/null 2>&1 && no "an unknown deployment option was accepted" || ok "an unknown deployment option is refused"

# with a URL the answers are stored too, and they validate
out=$($DA project new widget --dir "$T/widget" --url https://github.com/acme/widget 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project new widget --dir "$T/widget" --url https://github.com/acme/widget --plan "$tok" --approved go >/dev/null 2>&1 \
  && jq -e '.project == "widget" and .repo.url == "https://github.com/acme/widget" and (.repo.long_lived | index("develop"))' "$T/c/projects/widget.json" >/dev/null \
  && $DA project validate widget >/dev/null 2>&1 && ok "with --url the answers are stored and validate" || no "url store"
jq -e 'has("gates") | not' "$T/c/projects/widget.json" >/dev/null && ok "without --param gates no gates are stored" || no "gates stored without being given"

# --param gates=JSON: the files name the gates, so the stored answers declare them too (feature verify and the CI scan read the answers)
GJ='[{"name":"lint","command":"make lint","tier":"feature"},{"name":"pack","command":["make","pack it"],"tier":"release"}]'
out=$($DA project new gw --dir "$T/gw" --url https://github.com/acme/gw --param "gates=$GJ" 2>&1); tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DA project new gw --dir "$T/gw" --url https://github.com/acme/gw --param "gates=$GJ" --plan "$tok" --approved go >/dev/null 2>&1 \
  && grep -qx '  gate2:' "$T/gw/.github/workflows/test.yml" \
  && jq -e --argjson g "$GJ" '.gates == $g' "$T/c/projects/gw.json" >/dev/null && $DA project validate gw >/dev/null 2>&1 \
  && ok "project new --param gates stores the gates in the answers, as the files name them" || no "gates not stored: $(jq -c .gates "$T/c/projects/gw.json" 2>&1)"
[ -z "$(python3 lib/gates.py scan "$T/c/projects/gw.json" "$T/gw")" ] && ok "the CI scan reads the stored gates and finds every job of the new project matched" || no "scan: $(python3 lib/gates.py scan "$T/c/projects/gw.json" "$T/gw")"
$DA project new gx --dir "$T/gx" --url https://github.com/acme/gx --param 'gates=[{"name":"a"}]' >/dev/null 2>&1 && no "invalid gates were accepted by project new" || ok "invalid gates are refused by project new before anything is created"
[ ! -e "$T/gx" ] && [ ! -e "$T/c/projects/gx.json" ] && ok "and nothing is created or stored" || no "gx created"
rm -rf "$T"
exit $fail
