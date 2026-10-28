#!/usr/bin/env bash
# Teams: the definition in the project answers, the lead's provisioning render, the brief, the split
# of a team's collected outputs, the team check and the session-start hook. Offline (fake ant).
# Run: tests/test_team.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
mkdir -p "$T/c/projects" "$T/s" "$T/bin" "$FAKE/mem" "$FAKE/ref" "$FAKE/blobs" "$T/repo"
# A fake ant: memory stores are directories (file name = path with / as ~), output files come from $FAKE/files.jsonl.
cat > "$T/bin/ant" <<'EOF'
#!/usr/bin/env bash
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:memory-stores:memories)
    s=$(arg --memory-store-id "$@"); d=$FAKE/mem; [ "$s" = memstore_REF ] && d=$FAKE/ref
    case $2 in
      list) for f in "$d"/*; do [ -f "$f" ] || continue; n=$(basename "$f"); jq -nc --arg p "$(printf '%s' "$n" | tr '~' '/')" --arg i "$n" '{type:"memory",path:$p,id:$i}'; done;;
      retrieve) jq -Rs '{content: .}' "$d/$(arg --memory-id "$@")";;
    esac;;
  beta:files)
    case $2 in
      list) cat "$FAKE/files.jsonl";;
      download) cp "$FAKE/blobs/$(arg --file-id "$@")" "$(arg --output "$@")";;
    esac;;
  *) echo "{}";;
esac
EOF
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

proj() { jq -n --arg p "$1" --arg path "$T/repo" '{schema:1,project:$p,repo:{url:"https://github.com/example/x",path:$path,long_lived:["main"]},
  roles:{dev:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:["groff"],skills:[]},
         docs:{base:"gh-pages",push:{mode:"none"},model:"claude-opus-5-5",effort:"medium",apt:[],skills:["pdf"]},
         review:{base:"@dispatcher",push:{mode:"none"},model:"claude-opus-5-5",effort:"high",apt:["shellcheck"],skills:[]}},
  lead:{model:"claude-opus-5-5",effort:"high"},
  teams:{"code-docs":{members:["dev","docs","review"],max_rounds:2,budget_cents:3000,standards:["shared/rules/rules.md"],scopes:{docs:["site/"]},done:{docs:"make check-site"}}},
  memory:{memory_store:"memstore_MEM",reference_store:"memstore_REF"},budget_cents:500}' > "$T/c/projects/$1.json"; }
proj alpha

# --- the definition is validated
$DA project validate alpha >/dev/null 2>&1 && ok "a project with a valid team passes" || no "valid team refused"
bad() { # description jq-filter
  jq "$2" "$T/c/projects/alpha.json" > "$T/c/projects/badt.json"; sed -i 's/"project": "alpha"/"project": "badt"/' "$T/c/projects/badt.json"
  $DA project validate badt >/dev/null 2>&1 && no "$1 was accepted" || ok "$1 is refused"; rm -f "$T/c/projects/badt.json"; }
bad "a team of one member" '.teams["code-docs"].members=["dev"]'
bad "a team with a role the project does not enable" '.teams["code-docs"].members=["dev","test"]'
bad "teams without a lead model" 'del(.lead)'
bad "a role named lead" '.roles.lead=.roles.dev'
bad "standards that escape the store" '.teams["code-docs"].standards=["../x"]'
bad "more than five revise rounds" '.teams["code-docs"].max_rounds=9'

# --- the brief
out=$($DA team brief alpha code-docs --task "Rename the verb" --done "make test" --base feature/x 2>&1)
echo "$out" | grep -q "^TEAM: code-docs" && echo "$out" | grep -q "OUT_PREFIX: docs--" && echo "$out" | grep -q "BASE: gh-pages" && echo "$out" | grep -q "SCOPE: site/" && echo "$out" | grep -q "DONE: make check-site" \
  && ok "the brief gives each member its base, scope, prefix and check" || no "brief: $out"
echo "$out" | grep -A6 "role: review" | grep -q "BASE: feature/x" && ok "the reviewer reviews the developer's base" || no "review base"
$DA team brief alpha code-docs --task t --done d >/dev/null 2>&1 && no "a brief without a base was made while the developer's base is @dispatcher" || ok "a brief needs --base while the developer's base is @dispatcher"
$DA team brief alpha nosuch --task t --done d --base b >/dev/null 2>&1 && no "unknown team accepted" || ok "an unknown team is refused"

# --- the lead's provisioning: members are the registered role agents, the prompt carries the team definition
$DA provision plan --project alpha --role lead >/dev/null 2>&1 && no "a lead was planned without registered members" || ok "a lead needs its members provisioned first"
jq -n '{"alpha-dev":{location:"cloud",agent:{id:"agent_DEV",version:3,version_pinned:3}},"alpha-docs":{location:"cloud",agent:{id:"agent_DOCS",version:2,version_pinned:2}},"alpha-review":{location:"cloud",agent:{id:"agent_REV",version:1}}}' > "$T/c/instances.json"
$DA provision plan --project alpha --role lead >/dev/null 2>&1
A=$T/s/provision/alpha-lead/agents/alpha-lead/agent.md
grep -q "type: coordinator" "$A" && grep -q "id: agent_DOCS, version: 2" "$A" && grep -q "id: agent_REV, version: 1" "$A" && ok "the lead's members are the role agents, pinned to their versions" || no "multiagent block: $(sed -n 1,16p "$A")"
grep -q "^name: alpha-agent-lead" "$A" && ok "the lead agent is named by the convention" || no "lead name"
# front matter is YAML: a colon followed by a space in a plain scalar breaks it
for f in "$A" "$T/s/provision/alpha-lead/agents/alpha-lead/deployment-standby.yaml"; do
  sed -n '/^---$/,/^---$/p;' "$f" | sed '1d;$d' | grep -E '^(name|description): .*: ' >/dev/null && no "a colon in a plain scalar in $(basename "$f")"
done; ok "the rendered front matter has no colon in a plain scalar"
grep -q "Team code-docs" "$A" && grep -q "Scopes: docs: site/" "$A" && grep -q "Standards for the reviewer: shared/rules/rules.md" "$A" && ok "the lead's prompt carries the team definition" || no "teams block"
grep -q "never push" "$A" && ok "the lead's prompt says it never pushes" || no "lead push rule"
grep -q "You are a qargi agent" "$A" && no "the lead got the worker contract" || ok "the lead does not get the worker contract"
$DA provision plan --project alpha --role dev >/dev/null 2>&1; grep -q "multiagent" "$T/s/provision/alpha-dev/agents/alpha-dev/agent.md" && no "a worker got a multiagent block" || ok "a worker has no multiagent block"

# --- a team's outputs are split per member
mkdir -p "$T/out"
: > "$FAKE/files.jsonl"
add() { printf '%s' "$2" > "$FAKE/blobs/$1"; jq -nc --arg i "$1" --arg n "$3" '{id:$i,filename:$n}' >> "$FAKE/files.jsonl"; }
add f1 '{"status":"DONE"}' "/mnt/session/outputs/dev--manifest.json"
add f2 'patch one' "/mnt/session/outputs/dev--0001-names-accept-periods.patch"
add f3 '{"status":"DONE"}' "/mnt/session/outputs/docs--manifest.json"
add f4 'patch docs' "/mnt/session/outputs/docs--0001-docs-describe.patch"
add f5 '# Review\n\n## Findings\n\nnone\n' "/mnt/session/outputs/review--report.md"
add f6 '{"status":"DONE"}' "/mnt/session/outputs/review--manifest.json"
add f7 '{"team":"code-docs","members":[],"verdict":"accept","rounds":1}' "/mnt/session/outputs/lead--team.json"
add f8 'summary' "/mnt/session/outputs/lead--summary.md"
$DA collect sesn_x "$T/out" >/dev/null 2>&1
[ -f "$T/out/dev/manifest.json" ] && [ -f "$T/out/dev/patches/0001-names-accept-periods.patch" ] && [ -f "$T/out/docs/patches/0001-docs-describe.patch" ] && [ -f "$T/out/review/report.md" ] && [ -f "$T/out/lead/team.json" ] \
  && ok "collect splits a team's files into one directory per member, patches under patches/" || no "split: $(cd "$T/out" && find . -type f | sort | tr '\n' ' ')"
# a lead-only run (no member manifests) is collected too
mkdir -p "$T/leadonly"; : > "$FAKE/files.jsonl"; add h1 '{"team":"check","members":[],"verdict":"accept"}' "/mnt/session/outputs/lead--team.json"; add h2 'ok' "/mnt/session/outputs/lead--summary.md"
$DA collect sesn_z "$T/leadonly" >/dev/null 2>&1 && [ -f "$T/leadonly/lead/team.json" ] && ok "a lead-only run is collected" || no "lead-only collect"
# a solo run is untouched
mkdir -p "$T/solo"; : > "$FAKE/files.jsonl"; add g1 '{"status":"DONE"}' "/mnt/session/outputs/manifest.json"; add g2 'p' "/mnt/session/outputs/0001-x.patch"
$DA collect sesn_y "$T/solo" >/dev/null 2>&1; [ -f "$T/solo/manifest.json" ] && [ -f "$T/solo/0001-x.patch" ] && ok "a single agent's outputs stay flat" || no "solo collect"

# --- the team check
rm -rf "$T/chk"; mkdir -p "$T/chk/review" "$T/chk/lead"
printf '# Review\n\n## Findings\n\nnone\n' > "$T/chk/review/report.md"
$DA team check "$T/chk" >/dev/null 2>&1 && no "a team without team.json passed" || ok "a team run without the lead's team.json fails"
echo '{"team":"code-docs","members":[],"verdict":"revise","rounds":2}' > "$T/chk/lead/team.json"
out=$($DA team check "$T/chk" 2>&1); echo "$out" | grep -q "did not reach accept" && ok "a team that did not reach accept is flagged" || no "check: $out"

# a member with no commits (blocked, or nothing to change) is not a failure in a team
rm -rf "$T/chk2"; mkdir -p "$T/chk2/dev" "$T/chk2/lead"; echo '{"status":"DONE","commits":[]}' > "$T/chk2/dev/manifest.json"
echo '{"team":"t","members":[],"verdict":"accept","rounds":0}' > "$T/chk2/lead/team.json"
$DA team check "$T/chk2" >/dev/null 2>&1 && ok "a team member that returned no commits passes the team check" || no "empty member refused"
$DA review check "$T/chk2/dev" >/dev/null 2>&1 && no "a single run with DONE and no commits passed" || ok "a single run that claims DONE with no commits still fails"

# --- the session-start hook
printf '# alpha memory\nREADME\n' > "$FAKE/mem/~README.md"; printf '# Shared\n' > "$FAKE/mem/~shared~INDEX.md"
printf '# alpha reference\n' > "$FAKE/ref/~README.md"; printf '| Path | Purpose | Load |\n|---|---|---|\n| workflow/team.md | handoffs | always |\n' > "$FAKE/ref/~roles~lead~INDEX.md"
printf '# Team workflow\nHandoffs go through you.\n' > "$FAKE/ref/~roles~lead~workflow~team.md"
out=$(cd "$T/repo" && $DA hook session-start 2>&1)
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | contains("alpha memory") and contains("Handoffs go through you")' >/dev/null 2>&1 \
  && ok "inside a project's repository the hook loads the lead's README, indexes and always-notes" || no "hook: $out"
[ -z "$(cd /tmp && $DA hook session-start 2>&1)" ] && ok "outside a project the hook prints nothing" || no "hook outside"
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | length < 6000' >/dev/null && ok "the hook output is small" || no "hook size"

# --- the push grant
printf 'tok' > "$T/tok"; chmod 600 "$T/tok"
good() { jq "$1" "$T/c/projects/alpha.json" > "$T/c/projects/pushp.json"; sed -i 's/"project": "alpha"/"project": "pushp"/' "$T/c/projects/pushp.json"; }
good '.lead.push={local:true,cloud:"none",branch_pattern:"agent/*",merge:"ask",release:"ask"}'; $DA project validate pushp >/dev/null 2>&1 && ok "a local-only push grant is accepted" || no "local grant refused"
good ".lead.push={cloud:\"branches\",credential_file:\"$T/tok\"}"; $DA project validate pushp >/dev/null 2>&1 && ok "a cloud grant with a token file outside any repository is accepted" || no "cloud grant refused: $($DA project validate pushp 2>&1)"
for case in '.lead.push={cloud:"branches"}|a cloud grant without a token file' '.lead.push={local:true,merge:"auto"}|an automatic merge' '.lead.push={local:true,release:"auto"}|an automatic release' '.lead.push={local:true,branch_pattern:"develop"}|a branch pattern outside agent/' '.lead.push={cloud:"everything"}|an unknown cloud mode'; do
  good "${case%%|*}"; $DA project validate pushp >/dev/null 2>&1 && no "${case##*|} was accepted" || ok "${case##*|} is refused"; done
chmod 644 "$T/tok"; good ".lead.push={cloud:\"branches\",credential_file:\"$T/tok\"}"; $DA project validate pushp >/dev/null 2>&1 && no "a world-readable token file was accepted" || ok "a world-readable token file is refused"; chmod 600 "$T/tok"
rm -f "$T/c/projects/pushp.json"
# the lead's prompt and the autoload carry the grant (or its absence)
grep -q "You never push" "$A" && ok "without a grant the lead's prompt says it never pushes" || no "no-grant prompt"
jq ".lead.push={cloud:\"branches\",credential_file:\"$T/tok\",branch_pattern:\"agent/*\",vault_id:\"vlt_X\"}" "$T/c/projects/alpha.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/alpha.json"
$DA provision plan --project alpha --role lead >/dev/null 2>&1
grep -q "branches named agent/\*" "$A" && grep -q "asked of the person by the platform" "$A" && ok "with a cloud grant the prompt names the branches and says merges and releases are asked of the person" || no "grant prompt"
jq '.lead.push.local=true' "$T/c/projects/alpha.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/alpha.json"
out=$(cd "$T/repo" && $DA hook session-start 2>&1)
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | contains("Push grant") and contains("merge it")' >/dev/null && ok "the autoload tells this session its push grant" || no "hook grant"
jq 'del(.lead.push)' "$T/c/projects/alpha.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/alpha.json"
out=$(cd "$T/repo" && $DA hook session-start 2>&1)
echo "$out" | jq -e '.hookSpecificOutput.additionalContext | contains("No push grant")' >/dev/null && ok "without a grant the autoload says to ask before every push" || no "hook no grant"
exit $fail
