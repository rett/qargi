#!/usr/bin/env bash
# The two cloud bases (worker: write class, reviewer: read-only class) and the safety rules around them: the class of an
# instance name comes from the bases in lib/model-defaults.json and fails closed (an unknown class is read-only, never write);
# a read-only or coordinator class has the edit and write tools off in the cloud; worker and reviewer are reserved names no
# role may take; the read-only barrier guard fires for <project>-reviewer; provision plan renders both bases (tools, role-neutral
# system, full model object, skills of the class) and leaves the role instances as they were. Hermetic, offline. Run: tests/test_cloud_bases.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/bin" "$FAKE"

# the ant fake: logs its calls, logged in, answers a deployment run with a session id, everything else with nothing
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
case $1 in
  beta:deployments) if [ "${2:-}" = run ]; then echo '{"session_id":"sesn_1"}'; else echo '{}'; fi;;
  beta:sessions) echo '{"status":"idle","budget":{"max_list_cost":{"amount":"500"}}}';;
esac
exit 0
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH

# roles of yours: one read-only, one write, one with a class the guard does not know
mkdir -p "$T/c/roles/audit" "$T/c/roles/probe" "$T/c/roles/odd"
printf '{"class":"read-only"}\n' > "$T/c/roles/audit/role.json"; printf '# Role: audit\n\nList the dependencies.\n' > "$T/c/roles/audit/ROLE.md"
printf '{"class":"write"}\n' > "$T/c/roles/probe/role.json"; printf '# Role: probe\n\nTry things.\n' > "$T/c/roles/probe/ROLE.md"
printf '{"class":"sudo"}\n' > "$T/c/roles/odd/role.json"; printf '# Role: odd\n\nUnknown class.\n' > "$T/c/roles/odd/ROLE.md"

. lib/lib.sh

# --- the class of an instance name
cls() { instance_class "$1" 2>/dev/null; }
[ "$(cls worker)" = write ] && ok "the worker base is write" || no "worker: $(cls worker)"
[ "$(cls reviewer)" = read-only ] && ok "the reviewer base is read-only" || no "reviewer: $(cls reviewer)"
[ "$(cls build)" = write ] && [ "$(cls write)" = write ] && [ "$(cls test)" = write ] && ok "legacy build, write and test stay write" || no "legacy write roles"
[ "$(cls review)" = read-only ] && ok "legacy review stays read-only" || no "review: $(cls review)"
[ "$(cls lead)" = coordinator ] && ok "lead is the coordinator class" || no "lead: $(cls lead)"
[ "$(cls audit)" = read-only ] && [ "$(cls probe)" = write ] && ok "roles of yours keep their class" || no "own roles: $(cls audit) $(cls probe)"
[ "$(cls nosuch)" = read-only ] && ok "an unknown name fails closed: read-only" || no "nosuch: '$(cls nosuch)'"
[ "$(cls odd)" = read-only ] && ok "a role with an unknown class fails closed: read-only" || no "odd: '$(cls odd)'"
[ "$(cls '')" = read-only ] && ok "an empty name fails closed: read-only" || no "empty: '$(cls '')'"
# a defaults table that cannot be read must not turn a base into write
( _QARGI_DEFAULTS=$T/missing.json; [ "$(instance_class reviewer 2>/dev/null)" = read-only ] ) && ok "a base class that cannot be read is read-only" || no "unreadable defaults"
# the old helper is unchanged: it fails for a name it does not know
role_class worker >/dev/null 2>&1 && no "role_class answered for a base name" || ok "role_class itself still fails for a base name (callers use instance_class)"

# --- the tools off in the cloud
off() { tools_off "$1" "${2:-}"; }
has() { case " $1 " in *" $2 "*) return 0;; esac; return 1; }
o=$(off reviewer); has "$o" edit && has "$o" write && has "$o" web_search && has "$o" web_fetch && ok "reviewer: web_search web_fetch edit write off" || no "reviewer off: $o"
o=$(off worker); has "$o" edit || has "$o" write && no "worker lost edit or write: $o" || ok "worker keeps edit and write"
has "$o" web_search && has "$o" web_fetch && ok "worker keeps the web tools off, as before" || no "worker off: $o"
o=$(off review); has "$o" edit && has "$o" write && ok "legacy review: edit and now write off" || no "review off: $o"
[ "$(off build)" = "web_search web_fetch" ] && ok "legacy build is unchanged" || no "build off: $(off build)"
o=$(off lead); has "$o" edit && has "$o" write && ok "lead (coordinator): edit and write off" || no "lead off: $o"
o=$(off nosuch); has "$o" edit && has "$o" write && ok "an unknown class: edit and write off (fail closed)" || no "nosuch off: $o"
o=$(off odd); has "$o" edit && has "$o" write && ok "a role with an unknown class: edit and write off" || no "odd off: $o"
P=$T/proj.json
jq -n '{roles: {reviewer: {tools_off: ["web_search"]}, worker: {tools_off: ["bash"]}, review: {tools_off: []}}}' > "$P"
[ "$(off reviewer "$P")" = web_search ] && [ "$(off worker "$P")" = bash ] && [ "$(off review "$P")" = "" ] && ok "an explicit roles.<role>.tools_off still overrides the default" || no "override: $(off reviewer "$P")|$(off worker "$P")|$(off review "$P")"

# --- the names are reserved
mkdir -p "$T/c/roles/worker" "$T/c/roles/reviewer"
for n in worker reviewer; do printf '{"class":"write"}\n' > "$T/c/roles/$n/role.json"; echo "# Role: $n (squatter)" > "$T/c/roles/$n/ROLE.md"; done
$DA role list | grep -qE "^(worker|reviewer) " && no "a base name was listed as a role" || ok "worker and reviewer directories are not roles"
$DA role check worker >/dev/null 2>&1 && no "role check passed for worker" || ok "role check refuses worker"
out=$($DA role check reviewer 2>&1); grep -q "reserved" <<<"$out" && ok "and says the name is reserved" || no "check reviewer: $out"
[ "$(cls reviewer)" = read-only ] && [ "$(cls worker)" = write ] && ok "a role directory cannot change the class of a base" || no "squatter changed a class: $(cls reviewer) $(cls worker)"
agent_prompt reviewer p | grep -q squatter && no "the prompt of a base carries a squatter's text" || ok "the prompt of a base never carries a role directory's text"
BS=$PWD/provision/templates/base-system.md
[ "$(agent_prompt reviewer p)" = "$(cat "$BS")" ] && [ "$(agent_prompt worker p)" = "$(cat "$BS")" ] && ok "agent_prompt of a base is the short role-neutral fallback" || no "agent_prompt of a base"
grep -qiE 'do not write|never write|no memor' "$BS" && [ "$(wc -l < "$BS")" -le 20 ] && ok "the fallback is short and forbids memory writes" || no "fallback shape"
rm -rf "$T/c/roles/worker" "$T/c/roles/reviewer"

# --- the barrier guard fires for <project>-reviewer (claude has no read-only barrier on cloud)
refused() { # name rc output project
  [ "$2" = 2 ] && grep -q "qargi provider accept claude --surface cloud --no-barrier --project $4 --asked" <<<"$3" && ok "$1" || no "$1 (rc=$2: $3)"
}
out=$($DA provision plan --project delta --role reviewer 2>&1); rc=$?
refused "provision plan: the reviewer base is refused where cloud has no barrier" "$rc" "$out" delta
out=$($DA provision apply --project delta --role reviewer --asked x --approved y --plan z 2>&1); rc=$?
refused "provision apply: the reviewer base is refused too" "$rc" "$out" delta
$DA provision plan --project delta --role worker >/dev/null 2>&1 && ok "the worker base passes the guard" || no "worker plan: $($DA provision plan --project delta --role worker 2>&1 | tail -3)"
$DA provision plan --project delta --role review >/dev/null 2>&1; [ $? = 2 ] && ok "legacy review is still refused" || no "legacy review plan"

git init -q -b main "$T/repo" && git -C "$T/repo" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
$DA project template gamma | jq --arg r "$T/repo" '.repo.url = "https://github.com/example/\(.project)" | .repo.path = $r | .models.provider = "claude"' > "$T/gamma.json"
$DA project init gamma --answers "$T/gamma.json" --force >/dev/null 2>&1 || no "init gamma"
jq -n '{"gamma-reviewer":{location:"cloud",deployment_id:"depl_R",environment_id:"env_1",agent:{id:"agent_R",version_pinned:1}},
  "gamma-worker":{location:"cloud",deployment_id:"depl_W",environment_id:"env_1",agent:{id:"agent_W",version_pinned:1}}}' > "$T/c/instances.json"
: > "$FAKE/ant.log"
out=$($DA start gamma-reviewer --asked "start the review" 2>&1); rc=$?
refused "start: the reviewer base is refused until the project accepts" "$rc" "$out" gamma
out=$($DA send gamma-reviewer "review it" --label rv --new --asked "review it" 2>&1); rc=$?
refused "send --new: the reviewer base is refused too" "$rc" "$out" gamma
grep -q 'deployments run' "$FAKE/ant.log" && no "a session was created" || ok "and no session was created"

# --- provisioning a base when the project has stored answers (roles build and write; no roles.worker, no roles.reviewer)
PD=$T/s/provision
: > "$FAKE/ant.log"
out=$($DA provision plan --project gamma --role reviewer 2>&1); rc=$?
refused "provision plan with stored answers: the reviewer base is refused" "$rc" "$out" gamma
[ ! -e "$PD/gamma-reviewer" ] && ok "and nothing was rendered for it" || no "files were rendered for a refused reviewer"
out=$($DA provision apply gamma-reviewer --asked x --approved y --plan z 2>&1); rc=$?
refused "provision apply with stored answers: the reviewer base is refused too" "$rc" "$out" gamma
grep -q 'apply --yes' "$FAKE/ant.log" && no "ant apply ran for a refused reviewer" || ok "and ant apply never ran"
$DA start gamma-worker --asked "build" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_W' "$FAKE/ant.log" && ok "the worker base starts as before" || no "worker start"
tok=$($DA provider accept claude --surface cloud --no-barrier --project gamma --asked "I accept it" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p')
$DA provider accept claude --surface cloud --no-barrier --project gamma --asked "I accept it" --plan "$tok" --approved go >/dev/null 2>&1 || no "accept"
: > "$FAKE/ant.log"
$DA start gamma-reviewer --asked "start the review" >/dev/null 2>&1; grep -q 'deployments run --deployment-id depl_R' "$FAKE/ant.log" && ok "after the project accepts, the reviewer base starts" || no "reviewer start after accept"

# --- the legacy role instances render exactly as before (golden: the front matter, the system and the deployment)
front() { awk 'f&&/^---$/{exit} /^---$/{f=1;next} f' "$1"; }                 # the agent's front matter
system_of() { sed '1,/^---$/d' "$1" | sed '1{/^$/d}'; }          # everything after it
A=$PD/gamma-build/agents/gamma-build
$DA provision plan --project gamma --role build >/dev/null 2>&1 || no "plan gamma-build"
want='name: gamma-build
description: Task-scoped build agent for the qargi cloud backend (one task, own clone, returns patches, never pushes).
model:
  id: claude-sonnet-5-5
  effort: high

skills: []

tools:
  - type: agent_toolset_20260401
    default_config: {permission_policy: {type: auto}}
    configs:
      - {name: web_search, enabled: false}
      - {name: web_fetch, enabled: false}'
[ "$(front "$A/agent.md")" = "$want" ] && ok "legacy gamma-build: the front matter is unchanged" || { no "legacy gamma-build front matter"; diff <(echo "$want") <(front "$A/agent.md") | head -8; }
[ "$(system_of "$A/agent.md")" = "$(agent_prompt build gamma)" ] && ok "legacy gamma-build: the system is agent_prompt build gamma" || no "legacy gamma-build system"
want='name: gamma-deployment-build
description: Manual-run deployment for gamma-build. No schedule; each run starts a standby session.
agent: ./agent.md
environment_id: ./environment.yaml
vault_ids: []
budget: {type: limit, max_list_cost: {amount: "500", currency: USD}}
resources:
  - ./memory_store-recipes.yaml
  - ./memory_store-reference.yaml
initial_events:
  - type: user.message
    content:
      - type: text
        text: |
          You are on standby for the /qargi-task cloud backend. Do no repository work until the coordinator sends a task with a --done check. Reply only: ready.'
[ "$(cat "$A/deployment-standby.yaml")" = "$want" ] && ok "legacy gamma-build: the deployment is unchanged" || no "legacy gamma-build deployment"
$DA provision plan --project gamma --role write >/dev/null 2>&1 || no "plan gamma-write"
A=$PD/gamma-write/agents/gamma-write
[ "$(front "$A/agent.md" | sed -n '2,8p')" = 'description: Task-scoped write agent for the qargi cloud backend (one task, own clone, returns patches, never pushes).
model:
  id: claude-sonnet-5-5
  effort: medium

skills:
  - {type: anthropic, skill_id: pdf, version: latest}' ] && ok "legacy gamma-write: model, effort and skills are unchanged" || no "legacy gamma-write front matter"
$DA provision plan gamma-build 2>&1 | grep -q '^plan token: [0-9a-f]\{12\}' && ok "legacy plans still print a plan token" || no "legacy plan token"

# --- skills of the classes: one skill linked to each ability, so the union can be told from one role's
sealit() { local t; t=$($DA skill seal "$1" | sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'); $DA skill seal "$1" --plan "$t" --approved test >/dev/null; }
for pair in sk-build:build sk-write:write sk-review:review sk-audit:audit; do
  n=${pair%%:*}; r=${pair##*:}
  $DA skill new "$n" >/dev/null; sed -i "s/^description: .*/description: Use for the $r ability./" "$T/c/packs/skills/$n/SKILL.md"; sealit "$n"
  $DA skill link "$n" --scope user-role --role "$r" >/dev/null 2>&1 || no "link $n"
done

# --- <project>-worker: write class, with the web tools off only
BAL=$(jq -r .tiers.balanced lib/providers/claude.json)
out=$($DA provision plan --project gamma --role worker 2>&1); rc=$?
[ $rc = 0 ] && grep -q '^plan token: [0-9a-f]\{12\}' <<<"$out" && ok "provision plan gamma-worker succeeds with stored answers and no roles.worker" || no "worker plan (rc=$rc): $(tail -3 <<<"$out")"
A=$PD/gamma-worker/agents/gamma-worker
f=$(front "$A/agent.md")
grep -q '^name: gamma-worker$' <<<"$f" && ok "the agent is named gamma-worker" || no "worker name"
[ "$(sed -n '/^model:/,/^$/p' <<<"$f" | tr -d '\n')" = "model:  id: $BAL  effort: medium" ] && ok "worker model: the balanced tier of the provider as a full model object with effort medium" || no "worker model: $(sed -n '/^model:/,/^$/p' <<<"$f" | tr '\n' '|')"
off=$(grep -o 'name: [a-z_]*, enabled: false' <<<"$f" | sed 's/name: //;s/, enabled: false//' | paste -sd' ' -)
[ "$off" = "web_search web_fetch" ] && ok "worker tools: only web_search and web_fetch are off" || no "worker tools off: $off"
grep -q 'skill_id: pdf' <<<"$f" && ok "worker skills: the stored anthropic skill of a role of the class (pdf from write)" || no "worker pdf skill"
sk=$(ls "$A/skills" 2>/dev/null | paste -sd' ' -)
[ "$sk" = "sk-build sk-write" ] && grep -q './skills/sk-build' <<<"$f" && grep -q './skills/sk-write' <<<"$f" && ok "worker skills: the union of build and write, and not review" || no "worker skills: $sk"
[ "$(system_of "$A/agent.md")" = "$(cat "$BS")" ] && ok "worker system: the role-neutral fallback, not a role's prompt" || no "worker system differs from $BS"
grep -qi 'agent contract\|Task-scoped' <<<"$(system_of "$A/agent.md")" && no "the fallback carries a role's contract" || ok "the fallback names no role"

# --- <project>-reviewer: refused until the project accepts (done above), then read-only class
out=$($DA provision plan --project gamma --role reviewer 2>&1); rc=$?
[ $rc = 0 ] && ok "after the project accepts the missing barrier, provision plan gamma-reviewer succeeds" || no "reviewer plan after accept (rc=$rc): $(tail -3 <<<"$out")"
A=$PD/gamma-reviewer/agents/gamma-reviewer
f=$(front "$A/agent.md")
[ "$(sed -n '/^model:/,/^$/p' <<<"$f" | tr -d '\n')" = "model:  id: $BAL  effort: medium" ] && ok "reviewer model: balanced tier, effort medium, a full model object" || no "reviewer model"
off=$(grep -o 'name: [a-z_]*, enabled: false' <<<"$f" | sed 's/name: //;s/, enabled: false//' | paste -sd' ' -)
[ "$off" = "web_search web_fetch edit write" ] && ok "reviewer tools: web_search web_fetch edit write off" || no "reviewer tools off: $off"
sk=$(ls "$A/skills" 2>/dev/null | paste -sd' ' -)
[ "$sk" = "sk-review" ] && ok "reviewer skills: those of the review ability only" || no "reviewer skills: $sk"
[ "$(system_of "$A/agent.md")" = "$(cat "$BS")" ] && ok "reviewer system: the same fallback" || no "reviewer system"
$DA provision plan gamma-reviewer --model claude-opus-5-5 --effort high 2>&1 | grep -q '^plan token' && grep -q 'id: claude-opus-5-5' "$A/agent.md" && grep -q 'effort: high' "$A/agent.md" && ok "--model and --effort still win for a base" || no "flags for a base"

# --- the legacy roles still get their own skills only, and apply gets past the role check for a base
$DA provision plan --project gamma --role build >/dev/null 2>&1; [ "$(ls "$PD/gamma-build/agents/gamma-build/skills" | paste -sd' ' -)" = "sk-build" ] && ok "legacy build still gets only its own skill" || no "legacy build skills"
out=$($DA provision apply gamma-worker --asked "provision the worker" --approved go --plan 000000000000 2>&1); rc=$?
grep -qi 'plan' <<<"$out" && ! grep -q 'not enabled' <<<"$out" && [ $rc != 0 ] && ok "apply of a base reaches the plan-token check (a wrong token is refused)" || no "worker apply: rc=$rc $out"
grep -q 'apply --yes' "$FAKE/ant.log" && no "ant apply ran on a wrong token" || ok "and nothing was created"

[ $fail = 0 ] && echo "cloud bases tests passed" || { echo "cloud bases tests FAILED"; exit 1; }
