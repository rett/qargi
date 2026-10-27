#!/usr/bin/env bash
# Provision the cloud resources for a dev-agent instance with `ant apply`:
# environment, agent, memory store and deployment, then register the instance.
#
#   provision.sh plan  NAME [--model M] [--effort E] [--apt "pkg pkg"] [--networking unrestricted|limited]
#   provision.sh apply NAME --asked "<request naming the cloud instance>" --approved "<the user's go-ahead for this plan>"
#
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
NAME=${1:-}; shift || true
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
    *) die "unknown option $1";;
  esac
done

case $NAME in ''|*[!a-z0-9-]*|-*) die "NAME must be kebab-case (a-z, 0-9, -)";; esac
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
  sys=$(cat "$TPL/cloud-preamble.md" "$here/agent-contract.md")
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
    dep=$(key 'deployment-standby'); store=$(key 'memory_store-recipes')
    [ -n "$dep" ] || die "deployment id not found in $LOCK"
    if [ -n "$store" ]; then
      "$here/memory.sh" seed "$store" || echo "dev-agent: warning: could not seed the memory store" >&2
    fi
    "$here/registry.sh" init --location cloud --deployment "$dep" --name "$NAME" --no-session --asked "$ASKED"
    echo "provisioned $NAME: deployment $dep (approved: $APPROVED)";;
  *) die "usage: provision.sh plan|apply NAME [options]";;
esac
