#!/usr/bin/env bash
# The notes of a runtime's definition and the verb that reads them: `provider notes [TOPIC] [--project P]` prints the text of TOPIC from the
# definition of the project's local runtime (composed with its extensions; the project is --project, else the one in effect), or lists the
# topics when it is given none. A topic or a runtime with no notes is exit 1 and names both; a project with no local runtime has no
# provider to ask (exit 2, there is no default); the verb changes nothing. Hermetic and offline: a copy of the tool holds the fake runtimes
# (tests/fakeprov.sh), so the shipped definitions are never changed. Run: tests/test_provider_notes.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
SRC=$PWD
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s"
trap 'rm -rf "$T" "$HERMETIC"' EXIT

TOOL=$T/tool; mkdir -p "$TOOL"
copy_tool "$SRC" "$TOOL"
DA=$TOOL/bin/qargi
# shellcheck source=fakeprov.sh
. tests/fakeprov.sh
# notey: a local runtime with two notes of its own; plain: one with none; every other note of the shipped runtime is dropped
fake_runtime "$SRC" "$TOOL" notey local '.notes = {"alpha": "The alpha text.", "beta-2": "The beta text, with a comma."}'
fake_runtime "$SRC" "$TOOL" plain local 'del(.notes)'

mkproj() { # NAME PROVIDER-JSON: stored answers with a repository of their own
  local repo=$T/repo-$1
  mkdir -p "$repo"
  jq -n --arg n "$1" --arg p "$repo" --argjson prov "$2" '{schema:1,project:$n,repo:{url:("https://github.com/example/" + $n),path:$p,long_lived:["main"]},
    roles:{build:{base:"main",push:{mode:"none"},effort:"medium"}},models:{provider:$prov},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"
}
mkproj withnotes '"notey"'
mkproj nonotes '"plain"'
mkproj cloudonly '{"cloud":"claude-platform"}'
mkproj noprov 'null'
jq 'del(.models.provider)' "$T/c/projects/noprov.json" > "$T/np" && mv "$T/np" "$T/c/projects/noprov.json"

# run NAME... : stdout, stderr and status of `qargi provider notes ...` from outside every project
run() { out=$("$DA" provider notes "$@" 2>"$T/err"); rc=$?; err=$(cat "$T/err"); }

run alpha --project withnotes
{ [ $rc = 0 ] && [ "$out" = "The alpha text." ] && [ -z "$err" ]; } && ok "a topic prints its text and nothing else" || no "alpha: rc=$rc out=$out err=$err"
run --project withnotes beta-2
{ [ $rc = 0 ] && [ "$out" = "The beta text, with a comma." ]; } && ok "--project may come first" || no "beta-2: rc=$rc out=$out err=$err"
run --project withnotes
{ [ $rc = 0 ] && [ "$out" = "alpha
beta-2" ]; } && ok "no topic lists the topic names, one per line" || no "list: rc=$rc out=$out err=$err"

# the project in effect: inside its repository, or QARGI_PROJECT
out=$(cd "$T/repo-withnotes" && "$DA" provider notes alpha 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$out" = "The alpha text." ]; } && ok "inside a project's repository the project is the one in effect" || no "in effect: rc=$rc $out"
out=$(QARGI_PROJECT=withnotes "$DA" provider notes beta-2 2>&1); rc=$?
{ [ $rc = 0 ] && [ "$out" = "The beta text, with a comma." ]; } && ok "QARGI_PROJECT names the project" || no "QARGI_PROJECT: rc=$rc $out"
run alpha
{ [ $rc = 2 ] && grep -q "no project" <<<"$err" && [ -z "$out" ]; } && ok "with no project in effect it is exit 2 and says so" || no "no project: rc=$rc out=$out err=$err"
run alpha --project nosuch
{ [ $rc = 2 ] && grep -q "no such project 'nosuch'" <<<"$err"; } && ok "an unknown project is exit 2" || no "unknown project: rc=$rc err=$err"

# a topic that does not exist: exit 1, the message names the topic and the runtime and lists the topics there are
run gamma --project withnotes
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "notey" <<<"$err" && grep -q "gamma" <<<"$err" && grep -q "alpha, beta-2" <<<"$err"; } \
  && ok "an unknown topic is exit 1 naming the topic and the runtime and listing the topics" || no "unknown topic: rc=$rc out=$out err=$err"
run 'Not A Topic' --project withnotes
{ [ $rc = 1 ] && grep -q "Not A Topic" <<<"$err"; } && ok "a topic that cannot be a name is an unknown topic too" || no "bad topic: rc=$rc err=$err"

# a runtime with no notes
run alpha --project nonotes
{ [ $rc = 1 ] && [ -z "$out" ] && grep -q "plain" <<<"$err" && grep -q "alpha" <<<"$err" && grep -q "no notes" <<<"$err"; } \
  && ok "a runtime with no notes is exit 1 naming the topic and the runtime" || no "no notes: rc=$rc out=$out err=$err"
run --project nonotes
{ [ $rc = 1 ] && grep -q "plain" <<<"$err" && grep -q "no notes" <<<"$err"; } && ok "listing the topics of a runtime with none is exit 1" || no "list no notes: rc=$rc out=$out err=$err"

# no default provider: a project with none, or with none for the local surface, is exit 2 and falls back to nothing
run alpha --project noprov
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "has no provider" <<<"$err" && ! grep -qi "claude" <<<"$err"; } && ok "a project with no provider is exit 2 (no default)" || no "no provider: rc=$rc out=$out err=$err"
run alpha --project cloudonly
{ [ $rc = 2 ] && [ -z "$out" ] && grep -q "no local provider" <<<"$err"; } && ok "a project with no local runtime is exit 2 (the verb asks for the local surface)" || no "cloud only: rc=$rc out=$out err=$err"

# the shipped runtime of Claude Code has the topics the skills point at, and the text of a topic is what the verb prints
mkproj onclaude '{"local":"claude-code","cloud":"claude-platform"}'
run --project onclaude
{ [ $rc = 0 ] && [ "$out" = "commands
exploration
identity
session-model
skills-dir
spawn" ]; } && ok "the shipped claude-code lists its topics" || no "claude-code topics: rc=$rc out=$out err=$err"
run spawn --project onclaude
{ [ $rc = 0 ] && grep -q 'subagent_type' <<<"$out"; } && ok "claude-code says how a lead spawns a member" || no "claude-code spawn: rc=$rc out=$out err=$err"
topics=$(grep -rhoE 'qargi provider notes [a-z][a-z0-9-]*' skills packs contract roles agents 2>/dev/null | awk '{print $4}' | sort -u)
missing=
for t in $topics; do run "$t" --project onclaude; [ $rc = 0 ] || missing="$missing $t"; done
[ -z "$missing" ] && ok "every topic a skill points at exists in claude-code${topics:+ ($(tr '\n' ' ' <<<"$topics" | sed 's/ $//'))}" || no "skills point at topics claude-code lacks:$missing"
run spawn --project cloudonly
[ $rc = 2 ] && ok "claude-platform is a cloud runtime: a project with only it has no local notes" || no "cloud only spawn: rc=$rc"

# usage
run a b --project withnotes
[ $rc = 2 ] && ok "two topics are a usage error" || no "two topics: rc=$rc"
run alpha --project
[ $rc = 2 ] && ok "--project with no name is a usage error" || no "--project alone: rc=$rc"

# read-only: the definitions and the answers are what they were
before=$(cd "$T" && find tool/lib/providers c -type f -exec sha256sum {} + | sort | sha256sum)
run alpha --project withnotes; run --project withnotes; run gamma --project withnotes
after=$(cd "$T" && find tool/lib/providers c -type f -exec sha256sum {} + | sort | sha256sum)
[ "$before" = "$after" ] && ok "the verb changes nothing" || no "the verb changed a file"

exit $fail
