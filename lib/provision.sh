#!/usr/bin/env bash
# Provision the cloud resources for a dev-agent instance with `ant apply`:
# environment, agent, memory store and deployment, then register the instance.
#
#   provision.sh plan  NAME [--model M] [--effort E] [--apt "pkg pkg"] [--networking unrestricted|limited]
#   provision.sh apply NAME --asked "<request naming the cloud instance>" --approved "<the user's go-ahead for this plan>"
#
# NAME is <project>-<role> (--project P --role R, role defaults to dev; roles come
# from a fixed list). The agent, environment and deployment are named
# <NAME>-agent, -environment and -deployment. The memory stores belong to the
# project: <project>-memory (recipes) and <project>-reference. Existing ones are
# attached, not duplicated; --memory-store ID and --reference-store ID name them.
# Options also include --budget CENTS (default 500, set on the deployment).
# `plan` renders the files and prints the `ant apply --dry-run` plan; it
# changes nothing. `apply` creates the resources only with --approved (the
# user's go-ahead after seeing the plan), brings new memory stores to the canon
# layout, seeds each enabled role's skeleton and registers the instance. Files and claude-lock.json stay in the
# state directory, outside any repository. Existing resources created in the
# Console or with `ant beta:... create` cannot be adopted: this creates new ones.
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
TPL=$here/../provision/templates
[ -d "$TPL" ] || TPL=$here/provision/templates
[ -d "$TPL" ] || die "templates not found next to the skill"

verb=${1:-}; shift || true
NAME='' PROJECT='' ROLE=dev
if [ $# -gt 0 ] && [ "${1#--}" = "$1" ]; then NAME=$1; shift; fi
PLAN_ARG='' MODEL='' EFFORT='' APT='' APT_SET='' NETWORKING=unrestricted APPROVED='' BUDGET='' MEMORY_STORE='' REFERENCE_STORE='' SKILLS=''
while [ $# -gt 0 ]; do
  case $1 in
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --apt) APT=$2; APT_SET=1; shift 2;;
    --networking) NETWORKING=$2; shift 2;;
    --asked) ASKED=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    --plan) PLAN_ARG=$2; shift 2;;
    --budget) BUDGET=$2; shift 2;;
    --project) PROJECT=$2; shift 2;;
    --role) ROLE=$2; shift 2;;
    --memory-store) MEMORY_STORE=$2; shift 2;;
    --reference-store) REFERENCE_STORE=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done

export PLAN_ARG
[ -n "$NAME" ] || { [ -n "$PROJECT" ] && NAME=$PROJECT-$ROLE; }
[ -n "$NAME" ] || die "give NAME (<project>-<role>) or --project P [--role R]"
split_instance "$NAME"
# The project's stored answers (dev-agent project init) give the defaults; flags win.
PCFG=$DA_CONF/projects/$PROJECT.json
if [ -f "$PCFG" ]; then
  jq -e --arg r "$ROLE" '.roles[$r]' "$PCFG" >/dev/null || die "role '$ROLE' is not enabled for project $PROJECT (dev-agent project show $PROJECT)"
  cfg() { jq -r --arg r "$ROLE" "$1" "$PCFG"; }
  MODEL=${MODEL:-$(cfg '.roles[$r].model')}; EFFORT=${EFFORT:-$(cfg '.roles[$r].effort')}
  [ -n "$APT_SET" ] || APT=$(cfg '.roles[$r].apt | join(" ")')
  BUDGET=${BUDGET:-$(cfg '.budget_cents')}; SKILLS=$(cfg '.roles[$r].skills | join(" ")')
  MEMORY_STORE=${MEMORY_STORE:-$(cfg '.memory.memory_store // ""')}; REFERENCE_STORE=${REFERENCE_STORE:-$(cfg '.memory.reference_store // ""')}
fi
MODEL=${MODEL:-claude-sonnet-5-5}; EFFORT=${EFFORT:-high}; BUDGET=${BUDGET:-500}
case $BUDGET in ''|*[!0-9]*) die "--budget CENTS must be a whole number";; esac
case $NETWORKING in unrestricted|limited) ;; *) die "--networking unrestricted|limited";; esac
ant_ok

# Project-level stores: attach the ones that exist, create the others.
find_store() {
  local l; l=$(ant beta:memory-stores list --max-items -1 2>/dev/null) || return 1
  jq -r --arg n "$1" 'select(.name==$n and (.archived_at // null)==null) | .id' <<<"$l" | head -1
}
if [ -n "$MEMORY_STORE" ]; then MEMID=$MEMORY_STORE; else MEMID=$(find_store "$PROJECT-memory") || die "cannot list memory stores; nothing was changed"; fi
if [ -n "$REFERENCE_STORE" ]; then REFID=$REFERENCE_STORE; else REFID=$(find_store "$PROJECT-reference") || die "cannot list memory stores; nothing was changed"; fi
store_note() { # kind name id
  if [ -n "$3" ]; then echo "$1 store: attach existing store $3 (convention name $2)"; else echo "$1 store: create $2"; fi
}

W=$DA_STATE/provision/$NAME
D=$W/agents/$NAME
LOCK=$W/claude-lock.json

render() {
  local apt_list sys
  # YAML flow list from the space-separated package names
  apt_list="[$(printf '%s' "$APT" | xargs -n1 2>/dev/null | paste -sd, - | sed 's/,/, /g')]"
  mkdir -p "$D"
  RS=$here/../provision/role-seeds/$ROLE; [ -d "$RS" ] || RS=$here/provision/role-seeds/$ROLE
  sys=$(sed "s/{{ROLE}}/$ROLE/g" "$TPL/cloud-preamble.md"; cat "$here/../skills/dev-task/agent-contract.md"; [ ! -f "$RS/contract.md" ] || cat "$RS/contract.md")
  python3 -I - "$TPL" "$D" "$NAME" "$MODEL" "$EFFORT" "$apt_list" "$NETWORKING" "$BUDGET" "$sys" "$PROJECT" "${MEMID:+x}" "${REFID:+x}" "$SKILLS" <<'EOF'
import sys, pathlib
tpl, out, name, model, effort, apt, net, budget, system, project, have_mem, have_ref, skills = sys.argv[1:14]
t = pathlib.Path(tpl); o = pathlib.Path(out)
res = []
if not have_mem: res.append("  - ./memory_store-recipes.yaml")
if not have_ref: res.append("  - ./memory_store-reference.yaml")
resources = ("resources:\n" + "\n".join(res)) if res else "resources: []"
sk = "".join("\n  - {type: anthropic, skill_id: %s, version: latest}" % x for x in skills.split())
skills_yaml = ("skills:" + sk) if sk else "skills: []"
sub = {"{{SKILLS}}": skills_yaml, "{{PROJECT}}": project, "{{RESOURCES}}": resources, "{{NAME}}": name, "{{MODEL}}": model, "{{EFFORT}}": effort,
       "{{APT}}": apt, "{{NETWORKING}}": net, "{{BUDGET}}": budget}
def r(src, dst, extra=None):
    s = (t / src).read_text()
    for k, v in {**sub, **(extra or {})}.items():
        s = s.replace(k, v)
    (o / dst).write_text(s)
r("agent.md.tmpl", "agent.md", {"{{SYSTEM}}": system})
r("environment.yaml.tmpl", "environment.yaml")
if not have_mem: r("memory_store-recipes.yaml.tmpl", "memory_store-recipes.yaml")
if not have_ref: r("memory_store-reference.yaml.tmpl", "memory_store-reference.yaml")
r("deployment-standby.yaml.tmpl", "deployment-standby.yaml")
EOF
}

FILES=(agents/"$NAME"/deployment-standby.yaml)

# What apply would create: the rendered files, the stores it attaches, the budget.
plan_hash() {
  { find "$D" -type f -print0 | sort -z | xargs -0 cat; printf '%s|%s|%s|%s\n' "$MEMID" "$REFID" "$BUDGET" "$NAME"; } | plan_token
}

# New stores get the canon layout and each enabled role's skeleton. The stores' ids are
# recorded in the project's stored answers so `dev-agent canon` finds them.
canonise() {
  if [ ! -f "$PCFG" ]; then
    echo "dev-agent: warning: no stored answers for $PROJECT, so the new stores are empty; run /dev-project, then: dev-agent canon apply $PROJECT --approved \"...\"" >&2
    return 0
  fi
  [ -z "${store:-}" ] || "$here/project.sh" set "$PROJECT" memory.memory_store "$store" >/dev/null
  [ -z "${refstore:-}" ] || "$here/project.sh" set "$PROJECT" memory.reference_store "$refstore" >/dev/null
  DEV_AGENT_NESTED=1 "$here/canon.sh" apply "$PROJECT" --approved "provisioning $NAME" >/dev/null || echo "dev-agent: warning: could not bring the new stores to the canon" >&2
  local r
  for r in $(jq -r '.roles | keys[]' "$PCFG"); do
    DEV_AGENT_NESTED=1 "$here/canon.sh" seed-role "$PROJECT" --role "$r" --approved "provisioning $NAME" >/dev/null || echo "dev-agent: warning: could not seed role $r" >&2
  done
}

case $verb in
  plan)
    render
    echo "files rendered in $D"
    store_note memory "$PROJECT-memory" "$MEMID"
    store_note reference "$PROJECT-reference" "$REFID"
    echo "plan token: $(plan_hash)   (apply with: --plan <token> --approved \"...\")"
    (cd "$W" && ant apply --dry-run -v --lock-file "$LOCK" "${FILES[@]}");;
  apply)
    need_asked
    [ -n "$APPROVED" ] || die "apply needs --approved \"<the user's go-ahead for the plan shown by: plan $NAME>\""
    render
    need_plan "$(plan_hash)"; audit_log provision-apply "$NAME"
    (cd "$W" && ant apply --yes --lock-file "$LOCK" "${FILES[@]}") || die "ant apply failed"
    key() { jq -r --arg k "$1" '.resources | to_entries[] | select(.key|test($k)) | .value.id' "$LOCK" | head -1; }
    dep=$(key 'deployment-standby')
    [ -n "$dep" ] || die "deployment id not found in $LOCK"
    store=$MEMID; refstore=$REFID
    newstores=
    if [ -z "$store" ]; then store=$(key 'memory_store-recipes'); newstores=1; fi
    if [ -z "$refstore" ]; then refstore=$(key 'memory_store-reference'); newstores=1; fi
    if [ -n "$refstore" ] && [ -n "$store" ]; then
      # ant apply attaches a referenced store read-write; the reference store must be read-only.
      arr=$(jq -nc --arg r "$store" --arg f "$refstore" '[
        {type:"memory_store", memory_store_id:$r, access:"read_write", instructions:"Recipes: verified how-to facts. Read README.md first, load what the task needs."},
        {type:"memory_store", memory_store_id:$f, access:"read_only", instructions:"Development reference (rules, workflow, conventions, architecture). Read README.md first, then load only what the task needs. Read-only."}]')
      ant beta:deployments update --deployment-id "$dep" --resource "$arr" >/dev/null 2>&1 \
        || die "could not set the stores' access on the deployment; fix it before running a session"
    fi
    if [ -f "$PCFG" ]; then   # record the ids of attached stores too
      [ "$(jq -r '.memory.memory_store // ""' "$PCFG")" = "$store" ] || "$here/project.sh" set "$PROJECT" memory.memory_store "$store" >/dev/null
      [ "$(jq -r '.memory.reference_store // ""' "$PCFG")" = "$refstore" ] || "$here/project.sh" set "$PROJECT" memory.reference_store "$refstore" >/dev/null
    fi
    if [ -n "$newstores" ]; then canonise; fi
    "$here/registry.sh" init --location cloud --deployment "$dep" --name "$NAME" --no-session --asked "$ASKED"
    echo "provisioned $NAME: deployment $dep (approved: $APPROVED)";;
  add-reference)
    need_asked; audit_log provision-add-reference "$NAME"
    [ -n "$APPROVED" ] || die "add-reference needs --approved \"<the user's go-ahead>\" (it creates a memory store and changes the deployment)"
    inst=$(jq -e --arg n "$NAME" '.[$n]' "$REG") || die "no instance named $NAME"
    dep=$(jq -r .deployment_id <<<"$inst")
    cur=$(ant beta:deployments retrieve --deployment-id "$dep" 2>/dev/null) || die "cannot read the deployment"
    desc=$(sed -n 's/^description: //p' "$TPL/memory_store-reference.yaml.tmpl")
    refstore=$(ant beta:memory-stores create --name "$PROJECT-reference" --description "$desc" 2>/dev/null | jq -r .id)
    [ -n "$refstore" ] && [ "$refstore" != null ] || die "could not create the reference store"
    arr=$(jq -c --arg f "$refstore" '.resources + [{type:"memory_store", memory_store_id:$f, access:"read_only", instructions:"Development reference (rules, workflow, conventions, architecture). Read README.md first, then load only what the task needs. Read-only."}]' <<<"$cur")
    ant beta:deployments update --deployment-id "$dep" --resource "$arr" >/dev/null 2>&1 || die "could not attach $refstore to the deployment (store created: $refstore)"
    new=$(ant beta:deployments retrieve --deployment-id "$dep" 2>/dev/null | jq -c '.resources')
    json_update "$REG" '.[$n].resources = $r' --arg n "$NAME" --argjson r "$new"
    store=''; canonise
    echo "reference store $refstore ($PROJECT-reference) created, brought to the canon and attached read-only to $dep (approved: $APPROVED)";;
  *) die "usage: provision.sh plan|apply NAME [options]";;
esac
