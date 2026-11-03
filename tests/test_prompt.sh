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
# the stored answers of a project: its cloud runtime supplies the cloud-only part of the prompt
mkdir -p "$T/c/projects"
mkproj() { jq -n --arg p "$1" --argjson v "$2" '{schema:1,project:$p,repo:{url:"https://github.com/example/\($p)",long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:$v},memory:{},budget_cents:500}' > "$T/c/projects/$1.json"; }
mkproj alpha '{"local":"claude-code","cloud":"claude-platform"}'
# a scratch copy of the tool whose skill and preamble can be edited
copy_tool "$PWD" "$T/copy"; DC=$T/copy/bin/qargi

render() { bash -c ". '$1/lib/lib.sh'; agent_prompt build alpha"; }
render "$PWD" > "$FAKE/system"; echo 1 > "$FAKE/aver"
# what a cloud agent's prompt is made of: the contract, the output format, the cloud-only part, then the role; the lead gets none of them
RB=$(render "$PWD"); RL=$(bash -c ". '$PWD/lib/lib.sh'; agent_prompt lead alpha" 2>/dev/null)
for k in "You are a qargi agent" "# Output files" "# In a cloud run" "# Role: build"; do
  grep -qF "$k" <<<"$RB" && ok "the build prompt holds: $k" || no "the build prompt lacks: $k"
done
grep -qF "# In a cloud run" <<<"$RL" && no "the lead got the cloud-only part" || ok "the lead's prompt has no cloud-only part"
# the cloud-only part is the addendum of the project's cloud runtime, after the output format; the core's contract directory has none
[ ! -e contract/cloud-run.md ] && [ -f lib/providers/claude-platform/cloud-run.md ] && ok "cloud-run.md is a resource of the claude-platform definition, not of contract/" || no "cloud-run.md is in the wrong place"
[ "$(grep -nE -e '^# (Output files|In a cloud run|Role: build)' <<<"$RB" | cut -d: -f2- | sed 's/ (.*//' | paste -sd,)" = "# Output files,# In a cloud run,# Role: build" ] && ok "the addendum follows the contract and the output format" || no "order: $(grep -n '^# ' <<<"$RB" | head)"
grep -qF "OUT is /mnt/session/outputs" <<<"$RB" && ok "the addendum states the cloud output directory" || no "no output directory in the addendum"
# the neutral texts hold no hosted directory and no rule that conflicts with the contract (outputs go to OUT, memory notes are proposed)
grep -rq "mnt/session" contract provision/templates provision/role-seeds && no "a neutral text names the hosted output directory" || ok "the contract, the preamble and the role seeds do not name the hosted output directory"
grep -q "RUN_DIR" provision/templates/cloud-preamble.md provision/role-seeds/lead/contract.md && no "the preamble or the lead contract names RUN_DIR as a place" || ok "the preamble and the lead contract send outputs to OUT"
grep -rqE "write (new )?(verified )?(facts )?only (to|under)|members write only" provision/templates provision/role-seeds/lead/contract.md && no "a prompt text lets an agent write the memory store on its own" || ok "no prompt text lets an agent write the memory store on its own"
grep -q "RUN_DIR" <<<"$RB" && no "the build prompt names RUN_DIR" || ok "the build prompt does not name RUN_DIR"
# the contract is neutral about the runtime's tools and says each rule once: the Bash tool, run_in_background and Monitor are the claude-code addendum's,
# the detached start is the cloud addendum's, and a cloud member's prompt holds one no-push rule and one background-command rule
grep -qE "run_in_background|Monitor|Bash tool" contract/*.md && no "the contract names a runtime's tools" || ok "the contract does not name a runtime's tools (Bash tool, run_in_background, Monitor)"
grep -qF "run_in_background" lib/providers/claude-code/local-run.md && grep -qF "nohup" lib/providers/claude-platform/cloud-run.md && ok "each runtime's addendum carries its own way to start a long command" || no "an addendum lost its recipe"
grep -qiw "push" provision/templates/cloud-preamble.md lib/providers/claude-platform/cloud-run.md && no "the preamble or the cloud addendum repeats the contract's no-push rule" || ok "the contract alone says never to push (the preamble and the cloud addendum do not repeat it)"
grep -qi "detached" provision/templates/cloud-preamble.md && no "the preamble repeats the detached-start recipe" || ok "the cloud addendum alone owns the detached-start recipe"
for k in 'mktemp -d -p "$TMP"' 'TMPDIR="$TMP"' 'interpret-trailers --parse' 'pgrep -f' '"always" gates' "profile's rules for examples"; do
  grep -qF -- "$k" <<<"$RB" && ok "the build prompt holds: $k" || no "the build prompt lacks: $k"
done
# no project, a project without a cloud runtime, one whose runtime does not resolve, an unknown one: no addendum, and no default runtime
mkproj nocloud '{"local":"claude-code"}'; mkproj ghost '{"cloud":"nosuchrt"}'
for pr in "" nocloud ghost nosuchproj; do
  out=$(bash -c ". '$PWD/lib/lib.sh'; agent_prompt build $pr" 2>/dev/null)
  grep -qF "# Output files" <<<"$out" && ! grep -qF "# In a cloud run" <<<"$out" && ok "project '${pr:-none}': the contract without the cloud-only part" || no "project '${pr:-none}': $(grep -c 'cloud run' <<<"$out")"
done
grep -q "RUN_DIR" contract/contract.md contract/output-format.md && no "the contract names RUN_DIR" || ok "the contract and the output format do not name RUN_DIR as a place"
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
# the cloud runtime's addendum is part of the contract hash: a change to it is the skill part
cp "$T/copy/lib/providers/claude-platform/cloud-run.md" "$T/addendum.orig"
echo "An added rule of the cloud runtime." >> "$T/copy/lib/providers/claude-platform/cloud-run.md"
$DC instances show alpha-build 2>&1 | grep -q "STALE: the prompt rendered now differs.*(skill)" && ok "a changed addendum is reported as the skill" || no "show stale addendum: $($DC instances show alpha-build 2>&1 | tail -4)"
cp "$T/addendum.orig" "$T/copy/lib/providers/claude-platform/cloud-run.md"
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

# an addendum that cannot be read fails the prompt: refresh-prompt makes no cloud call and prints no plan, and the stamp is not a hash of what was left
chmod 644 "$T/copy/lib/providers/claude-platform/cloud-run.md"; cp "$T/addendum.orig" "$T/copy/lib/providers/claude-platform/cloud-run.md"
jq '.["alpha-build"].prompt = {sha: "0000000000000000", skill: "0000000000000000"}' "$T/c/instances.json" > "$T/i.json" && mv "$T/i.json" "$T/c/instances.json"
chmod 000 "$T/copy/lib/providers/claude-platform/cloud-run.md"
n1=$(wc -l < "$FAKE/ant.log")
out=$($DC instances refresh-prompt alpha-build --asked "t" 2>&1); rc=$?
n2=$(wc -l < "$FAKE/ant.log")
[ $rc != 0 ] && [ "$n1" = "$n2" ] && ! grep -q "plan token" <<<"$out" && grep -q "could not render the system prompt" <<<"$out" && ok "refresh-prompt with an unreadable addendum stops before any cloud call and plans nothing" || no "unreadable addendum: rc=$rc ant calls $n1/$n2 $out"
out=$($DC instances show alpha-build 2>&1 | grep "PROMPT")
grep -q "PROMPT: unknown" <<<"$out" && ok "the prompt state with an unreadable addendum is unknown, not stale" || no "show unreadable: $out"
st=$(bash -c ". '$T/copy/lib/lib.sh'; prompt_stamp build alpha" 2>/dev/null); rc=$?
[ $rc != 0 ] && [ -z "$st" ] && ok "prompt_stamp prints nothing and fails when the prompt cannot be rendered" || no "stamp: rc=$rc '$st'"
chmod 644 "$T/copy/lib/providers/claude-platform/cloud-run.md"
rm -rf "$T"; exit $fail
