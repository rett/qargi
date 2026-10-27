#!/usr/bin/env bash
# Provision the cloud resources for a dev-agent instance with `ant apply`:
# environment, agent, memory store and deployment, then register the instance.
#
#   provision.sh plan  NAME [--model M] [--effort E] [--apt "pkg pkg"] [--networking unrestricted|limited]
#   provision.sh apply NAME --asked "<request naming the cloud instance>" --approved "<the user's go-ahead for this plan>"
#
# Resources are named <NAME>-agent, -environment, -memory and -deployment, where
# NAME is <project>-<role> (--project P --role R, role defaults to dev).
# Options also include --budget CENTS (default 500, set on the deployment).
# `plan` renders the files and prints the `ant apply --dry-run` plan; it
# changes nothing. `apply` creates the resources only with --approved (the
# user's go-ahead after seeing the plan), seeds the recipes store with its
# README and registers the instance. Files and claude-lock.json stay in the
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
MODEL=claude-sonnet-5-5 EFFORT=high APT='' NETWORKING=unrestricted APPROVED='' BUDGET=500
while [ $# -gt 0 ]; do
  case $1 in
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --apt) APT=$2; shift 2;;
    --networking) NETWORKING=$2; shift 2;;
    --asked) ASKED=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    --budget) BUDGET=$2; shift 2;;
    --project) PROJECT=$2; shift 2;;
    --role) ROLE=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done

[ -n "$NAME" ] || { [ -n "$PROJECT" ] && NAME=$PROJECT-$ROLE; }
printf '%s' "$NAME" | grep -Eq '^[a-z][a-z0-9]*(-[a-z0-9]+)+$' || die "name must be <project>-<role> in kebab-case (for example tacctl-dev); give NAME or --project P [--role R]"
[ ${#NAME} -le 40 ] || die "name too long (40 characters at most)"
case $BUDGET in ''|*[!0-9]*) die "--budget CENTS must be a whole number";; esac
case $NETWORKING in unrestricted|limited) ;; *) die "--networking unrestricted|limited";; esac
ant_ok

W=$DA_STATE/provision/$NAME
D=$W/agents/$NAME
LOCK=$W/claude-lock.json

render() {
  local apt_list sys
  # YAML flow list from the space-separated package names
  apt_list="[$(printf '%s' "$APT" | xargs -n1 2>/dev/null | paste -sd, - | sed 's/,/, /g')]"
  mkdir -p "$D"
  sys=$(cat "$TPL/cloud-preamble.md" "$here/../skills/dev-agent/agent-contract.md")
  python3 -I - "$TPL" "$D" "$NAME" "$MODEL" "$EFFORT" "$apt_list" "$NETWORKING" "$BUDGET" "$sys" <<'EOF'
import sys, pathlib
tpl, out, name, model, effort, apt, net, budget, system = sys.argv[1:10]
t = pathlib.Path(tpl); o = pathlib.Path(out)
sub = {"{{NAME}}": name, "{{MODEL}}": model, "{{EFFORT}}": effort,
       "{{APT}}": apt, "{{NETWORKING}}": net, "{{BUDGET}}": budget}
def r(src, dst, extra=None):
    s = (t / src).read_text()
    for k, v in {**sub, **(extra or {})}.items():
        s = s.replace(k, v)
    (o / dst).write_text(s)
r("agent.md.tmpl", "agent.md", {"{{SYSTEM}}": system})
r("environment.yaml.tmpl", "environment.yaml")
r("memory_store-recipes.yaml.tmpl", "memory_store-recipes.yaml")
r("memory_store-reference.yaml.tmpl", "memory_store-reference.yaml")
r("deployment-standby.yaml.tmpl", "deployment-standby.yaml")
EOF
}

FILES=(agents/"$NAME"/deployment-standby.yaml)

case $verb in
  plan)
    render
    echo "files rendered in $D"
    (cd "$W" && ant apply --dry-run -v --lock-file "$LOCK" "${FILES[@]}");;
  apply)
    need_asked
    [ -n "$APPROVED" ] || die "apply needs --approved \"<the user's go-ahead for the plan shown by: plan $NAME>\""
    render
    (cd "$W" && ant apply --yes --lock-file "$LOCK" "${FILES[@]}") || die "ant apply failed"
    key() { jq -r --arg k "$1" '.resources | to_entries[] | select(.key|test($k)) | .value.id' "$LOCK" | head -1; }
    dep=$(key 'deployment-standby'); store=$(key 'memory_store-recipes'); refstore=$(key 'memory_store-reference')
    [ -n "$dep" ] || die "deployment id not found in $LOCK"
    if [ -n "$store" ]; then
      "$here/memory.sh" seed "$store" || echo "dev-agent: warning: could not seed the memory store" >&2
    fi
    if [ -n "$refstore" ]; then
      # ant apply attaches a referenced store read-write; the reference store must be read-only.
      arr=$(jq -nc --arg r "$store" --arg f "$refstore" '[
        {type:"memory_store", memory_store_id:$r, access:"read_write", instructions:"Recipes: verified how-to facts. Read README.md first, load what the task needs."},
        {type:"memory_store", memory_store_id:$f, access:"read_only", instructions:"Development reference (rules, workflow, conventions, architecture). Read README.md first, then load only what the task needs. Read-only."}]')
      ant beta:deployments update --deployment-id "$dep" --resource "$arr" >/dev/null 2>&1 \
        || die "could not set the reference store read-only on the deployment; fix it before running a session"
      "$here/memory.sh" seed-reference "$refstore" || echo "dev-agent: warning: could not seed the reference store" >&2
    fi
    "$here/registry.sh" init --location cloud --deployment "$dep" --name "$NAME" --no-session --asked "$ASKED"
    echo "provisioned $NAME: deployment $dep (approved: $APPROVED)";;
  add-reference)
    need_asked
    [ -n "$APPROVED" ] || die "add-reference needs --approved \"<the user's go-ahead>\" (it creates a memory store and changes the deployment)"
    inst=$(jq -e --arg n "$NAME" '.[$n]' "$REG") || die "no instance named $NAME"
    dep=$(jq -r .deployment_id <<<"$inst")
    cur=$(ant beta:deployments retrieve --deployment-id "$dep" 2>/dev/null) || die "cannot read the deployment"
    desc=$(sed -n 's/^description: //p' "$TPL/memory_store-reference.yaml.tmpl")
    refstore=$(ant beta:memory-stores create --name "$NAME-reference" --description "$desc" 2>/dev/null | jq -r .id)
    [ -n "$refstore" ] && [ "$refstore" != null ] || die "could not create the reference store"
    "$here/memory.sh" seed-reference "$refstore" || die "could not seed $refstore"
    arr=$(jq -c --arg f "$refstore" '.resources + [{type:"memory_store", memory_store_id:$f, access:"read_only", instructions:"Development reference (rules, workflow, conventions, architecture). Read README.md first, then load only what the task needs. Read-only."}]' <<<"$cur")
    ant beta:deployments update --deployment-id "$dep" --resource "$arr" >/dev/null 2>&1 || die "could not attach $refstore to the deployment (store created: $refstore)"
    new=$(ant beta:deployments retrieve --deployment-id "$dep" 2>/dev/null | jq -c '.resources')
    json_update "$REG" '.[$n].resources = $r' --arg n "$NAME" --argjson r "$new"
    echo "reference store $refstore ($NAME-reference) created, seeded and attached read-only to $dep (approved: $APPROVED)";;
  *) die "usage: provision.sh plan|apply NAME [options]";;
esac
