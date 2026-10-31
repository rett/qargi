#!/usr/bin/env bash
# Stale cloud-agent prompts: the hash recorded at provision and refresh, instances list/show, refresh-prompt --if-stale.
# Offline (fake ant). The prompt is changed in a scratch copy of the tool, never in the checkout. Run: tests/test_prompt.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
mkdir -p "$T/c" "$T/s" "$T/bin" "$FAKE"
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
case $1 in
  auth) exit 0;;
  beta:agents)
    case $2 in
      retrieve) jq -nc --rawfile s "$FAKE/system" --argjson v "$(cat "$FAKE/aver")" '{id:"agent_B",version:$v,archived_at:null,name:"alpha-build",system:($s|rtrimstr("\n"))}';;
      update) arg --system "$@" > "$FAKE/system"; echo $(( $(cat "$FAKE/aver") + 1 )) > "$FAKE/aver"; echo '{}';;
    esac;;
  beta:deployments)
    case $2 in
      retrieve) jq -nc --argjson v "$(cat "$FAKE/aver")" '{id:"depl_B",status:"active",archived_at:null,name:"alpha-deployment-build",agent:{id:"agent_B",version:$v}}';;
      *) echo '{}';;
    esac;;
  beta:environments) echo '{"name":"alpha-environment"}';;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
DA=$PWD/bin/qargi
# a scratch copy of the tool whose skill and preamble can be edited
mkdir "$T/copy"; cp -r bin lib roles skills provision "$T/copy/"; DC=$T/copy/bin/qargi

render() { bash -c ". '$1/lib/lib.sh'; agent_prompt build alpha"; }
render "$PWD" > "$FAKE/system"; echo 1 > "$FAKE/aver"
# an old registry entry (no prompt hash) and a local one
jq -n '{"alpha-build":{location:"cloud",deployment_id:"depl_B",environment_id:"env_1",agent:{id:"agent_B",version_pinned:1,model:"claude-sonnet-5-5",effort:"high"}},
        "alpha-local":{location:"local",local:{agent_file:"/nonexistent/a.md",sha256:"x",model:"m",effort:null}}}' > "$T/c/instances.json"

# unknown, not stale
$DA instances list 2>&1 | grep -q STALE && no "an entry without a hash was marked STALE" || ok "an entry with no recorded hash is not marked STALE in the list"
$DA instances show alpha-build 2>&1 | grep -q "PROMPT: unknown" && ok "show says the prompt state is unknown" || no "show unknown: $($DA instances show alpha-build 2>&1 | tail -4)"
$DA instances show alpha-local 2>&1 | grep -q "PROMPT" && no "a local instance got a prompt line" || ok "a local instance has no prompt state"

# --if-stale with no hash falls through to the normal check, which records the hash when the cloud prompt is current
out=$($DA instances refresh-prompt alpha-build --if-stale --asked "t" 2>&1)
echo "$out" | grep -q "no prompt hash is recorded" && echo "$out" | grep -q "is current" && ok "--if-stale with no hash checks the cloud and finds it current" || no "unknown path: $out"
jq -e '.["alpha-build"].prompt | (.sha | length) == 16 and (.skill | length) == 16' "$T/c/instances.json" >/dev/null && ok "the hashes were recorded" || no "recorded: $(cat "$T/c/instances.json")"

# current: no cloud call, no --asked needed
n1=$(wc -l < "$FAKE/ant.log")
out=$($DA instances refresh-prompt alpha-build --if-stale 2>&1); rc=$?
n2=$(wc -l < "$FAKE/ant.log")
[ $rc = 0 ] && echo "$out" | grep -q "unchanged since it was last rendered.*nothing done" && [ "$n1" = "$n2" ] && ok "--if-stale on a current prompt says so and makes no cloud call" || no "current: rc=$rc n=$n1/$n2 $out"
$DA instances show alpha-build 2>&1 | grep -q "PROMPT: current" && ok "show says the prompt is current" || no "show current"
$DA instances list 2>&1 | grep -q STALE && no "current prompt marked STALE" || ok "list does not mark a current prompt"

# the skill changes: stale, and the part is named
echo "A new rule added to the build skill." >> "$T/copy/roles/build/ROLE.md"
$DC instances list 2>&1 | grep "alpha-build" | grep -q "prompt STALE" && ok "list marks the instance STALE" || no "list stale: $($DC instances list 2>&1)"
$DC instances show alpha-build 2>&1 | grep -q "STALE: the prompt rendered now differs.*(skill)" && ok "show says STALE and that the skill changed" || no "show stale skill: $($DC instances show alpha-build 2>&1 | tail -4)"
# only the preamble changes: stale prompt, not skill
cp "$T/copy/roles/build/ROLE.md" "$T/skill.mod"; cp roles/build/ROLE.md "$T/copy/roles/build/ROLE.md"
echo "extra preamble line" >> "$T/copy/provision/templates/cloud-preamble.md"
$DC instances show alpha-build 2>&1 | grep -q "STALE: the prompt rendered now differs.*(prompt)" && ok "a change outside the skill is reported as the prompt" || no "show stale prompt: $($DC instances show alpha-build 2>&1 | tail -4)"
cp "$T/skill.mod" "$T/copy/roles/build/ROLE.md"

# --if-stale on a stale prompt plans the refresh (and still needs --asked)
$DC instances refresh-prompt alpha-build --if-stale >/dev/null 2>&1 && no "--if-stale on a stale prompt ran without --asked" || ok "a stale prompt still needs --asked"
out=$($DC instances refresh-prompt alpha-build --if-stale --asked "t" 2>&1)
echo "$out" | grep -q "changed since it was last rendered" && echo "$out" | grep -q "+ extra preamble line" && echo "$out" | grep -q "plan token" && ok "--if-stale on a stale prompt shows the plan and a token" || no "stale plan: $out"
[ "$(cat "$FAKE/aver")" = 1 ] && ok "the plan changed nothing" || no "plan pushed"
tok=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$out")
$DC instances refresh-prompt alpha-build --if-stale --asked "t" --plan "$tok" --approved "go ahead" >/dev/null 2>&1
[ "$(cat "$FAKE/aver")" = 2 ] && grep -q "extra preamble line" "$FAKE/system" && ok "the approved plan pushed the new prompt" || no "apply: aver=$(cat "$FAKE/aver")"
$DC instances show alpha-build 2>&1 | grep -q "PROMPT: current" && ok "after the refresh the new hash is recorded and the prompt is current" || no "after refresh: $($DC instances show alpha-build 2>&1 | tail -3)"
n1=$(wc -l < "$FAKE/ant.log"); $DC instances refresh-prompt alpha-build --if-stale >/dev/null 2>&1; [ "$(wc -l < "$FAKE/ant.log")" = "$n1" ] && ok "--if-stale now does nothing" || no "--if-stale called the cloud"

# plain refresh-prompt keeps its behaviour: it compares with the cloud whatever the hash says
echo "someone edited the prompt in the console" > "$FAKE/system"
out=$($DC instances refresh-prompt alpha-build --asked "t" 2>&1)
echo "$out" | grep -q "PLAN: update agent_B" && echo "$out" | grep -q "plan token" && ok "plain refresh-prompt still plans from the cloud's prompt" || no "plain: $out"
$DC instances refresh-prompt alpha-build >/dev/null 2>&1 && no "plain refresh-prompt ran without --asked" || ok "plain refresh-prompt still needs --asked"
# and the gate is unchanged: apply without the token is refused
$DC instances refresh-prompt alpha-build --asked "t" --approved "go" >/dev/null 2>&1 && no "apply without --plan succeeded" || ok "apply without the plan token is still refused"

# a registry made by an older release (hash missing the skill field) is stale on a changed prompt, not on a missing hash
jq '.["alpha-build"].prompt = {sha: "0000000000000000"}' "$T/c/instances.json" > "$T/i.json" && mv "$T/i.json" "$T/c/instances.json"
$DA instances show alpha-build 2>&1 | grep -q "STALE: the prompt rendered now differs.*(prompt)" && ok "a hash without a skill part still compares (reported as the prompt)" || no "partial hash"
# prompt_record (what provision apply and refresh-prompt call) writes the hashes, and invents no entry for an unknown name
jq 'del(.["alpha-build"].prompt)' "$T/c/instances.json" > "$T/i.json" && mv "$T/i.json" "$T/c/instances.json"
bash -c ". '$PWD/lib/lib.sh'; prompt_record alpha-build; prompt_record alpha-ghost"
jq -e '.["alpha-build"].prompt.sha != null and .["alpha-build"].prompt.at != null and (has("alpha-ghost") | not)' "$T/c/instances.json" >/dev/null && ok "prompt_record stores the hashes and does not create an entry" || no "prompt_record: $(cat "$T/c/instances.json")"
rm -rf "$T"; exit $fail
