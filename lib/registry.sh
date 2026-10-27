#!/usr/bin/env bash
# qargi registry verbs: init, list, show, remove.
# Usage: registry.sh init --location cloud --deployment ID [--name N] [--no-session] --asked "..."
#        registry.sh init --location cloud --deployment ID [--budget CENTS] --model M --effort E --asked "..." [--approved "..."]
#                         (changes the existing agent's model/effort; shows the change first)
#        registry.sh init --location cloud --provision --name N [--model M] [--effort E] [--apt "pkg ..."]
#                         [--networking unrestricted|limited] --asked "..." [--approved "..."]
#                         (creates new resources through provision.sh; without --approved it only prints the plan)
#        registry.sh init --location local --agent FILE [--name N] [--model M] [--effort E]
#        registry.sh list [--reconcile]
#        registry.sh show NAME [--reconcile]
#        registry.sh remove NAME
#        registry.sh budget NAME CENTS --asked "..."   (change the spend ceiling of the instance's deployment)
#        registry.sh refresh-prompt NAME --asked "..." [--plan TOKEN --approved "..."]   (rebuild the agent's prompt from the current contract)
#        registry.sh normalize NAME --asked "..." [--approved "..."]   (rename an instance's resources to <NAME>-agent|environment|memory|deployment)
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PLAN_ARG='' SESSION_ARG='' ARG2=''
LOC='' DEP='' AGENT_FILE='' NAME='' NOSESS='' ASKED='' RECON='' ARG='' MODEL='' EFFORT='' PROVISION='' APT='' NETWORKING='' APPROVED='' BUDGET=''
while [ $# -gt 0 ]; do
  case $1 in
    --location) LOC=$2; shift 2;;
    --deployment) DEP=$2; shift 2;;
    --agent) AGENT_FILE=$2; shift 2;;
    --name) NAME=$2; shift 2;;
    --no-session) NOSESS=1; shift;;
    --asked) ASKED=$2; shift 2;;
    --reconcile) RECON=1; shift;;
    --model) MODEL=$2; shift 2;;
    --effort) EFFORT=$2; shift 2;;
    --provision) PROVISION=1; shift;;
    --apt) APT=$2; shift 2;;
    --networking) NETWORKING=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    --plan) PLAN_ARG=$2; shift 2;;
    --budget) BUDGET=$2; shift 2;;
    --session) SESSION_ARG=$2; shift 2;;
    -*) die "unknown option $1";;
    *) if [ -z "$ARG" ]; then ARG=$1; else ARG2=$1; fi; shift;;
  esac
done

export PLAN_ARG
case $EFFORT in ''|low|medium|high|xhigh|max) ;; *) die "--effort low|medium|high|xhigh|max";; esac
[ -z "$MODEL" ] || printf '%s' "$MODEL" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' || die "--model: a model alias or id (letters, digits, . -)"

case $BUDGET in ''|*[!0-9]*) [ -z "$BUDGET" ] || die "--budget CENTS must be a whole number";; esac

slug() { printf '%s' "$1" | tr '[:upper:] _' '[:lower:]--' | tr -cd 'a-z0-9-' | sed 's/--*/-/g; s/^-//; s/-$//'; }

init_cloud() {
  need_asked; ant_ok
  [ -n "$DEP" ] || die "init --location cloud needs --deployment ID"
  local d name rec run sid
  d=$(ant beta:deployments retrieve --deployment-id "$DEP" 2>/dev/null) || die "cannot read deployment $DEP"
  [ "$(jq -r '.archived_at' <<<"$d")" = null ] || die "deployment is archived"
  local ag aid aver cur_m cur_e new_m new_e
  if [ -n "$BUDGET" ]; then
    ant beta:deployments update --deployment-id "$DEP" \
      --budget "{type: limit, max_list_cost: {amount: \"$BUDGET\", currency: USD}}" >/dev/null 2>&1 || die "could not set the deployment budget"
    d=$(ant beta:deployments retrieve --deployment-id "$DEP" 2>/dev/null) || die "cannot re-read deployment"
    echo "deployment budget set to $BUDGET"
  fi
  [ "$(jq -r '.budget // empty' <<<"$d")" != "" ] || die "the deployment has no spend budget; pass --budget CENTS (sessions would otherwise run unbounded)"
  aid=$(jq -r .agent.id <<<"$d")
  ag=$(ant beta:agents retrieve --agent-id "$aid" 2>/dev/null) || die "cannot read agent $aid"
  aver=$(jq -r .version <<<"$ag"); cur_m=$(jq -r .model.id <<<"$ag"); cur_e=$(jq -r '.model.effort.type // "default"' <<<"$ag")
  new_m=${MODEL:-$cur_m}; new_e=${EFFORT:-$cur_e}
  if [ "$new_m" != "$cur_m" ] || { [ -n "$EFFORT" ] && [ "$new_e" != "$cur_e" ]; }; then
    echo "PLAN: agent $aid v$aver: model $cur_m -> $new_m, effort $cur_e -> $new_e (creates a new agent version and re-points the deployment)"
    ptok=$(printf '%s' "$aid|$aver|$new_m|$new_e" | plan_token)
    [ -n "$APPROVED" ] || { echo "plan token: $ptok   (re-run with --plan $ptok --approved \"<the user's go-ahead>\" to apply; nothing changed)"; return 0; }
    need_plan "$ptok"; audit_log agent-update "$aid $cur_m->$new_m $cur_e->$new_e"
    ant beta:agents update --agent-id "$aid" --version "$aver" --model "{id: $new_m$([ "$new_e" = default ] || printf ', effort: %s' "$new_e")}" >/dev/null 2>&1 || die "agent update failed"
    ant beta:deployments update --deployment-id "$DEP" --agent "$aid" >/dev/null 2>&1 || die "deployment re-point failed (agent was updated)"
    d=$(ant beta:deployments retrieve --deployment-id "$DEP" 2>/dev/null) || die "cannot re-read deployment"
    ag=$(ant beta:agents retrieve --agent-id "$aid" 2>/dev/null)
    echo "agent updated to v$(jq -r .version <<<"$ag"); deployment now pins v$(jq -r .agent.version <<<"$d")"
  fi
  name=${NAME:-$(slug "$(jq -r '.name' <<<"$d")")}
  [ -n "$name" ] || die "empty instance name; pass --name"
  split_instance "$name"
  rec=$(jq -n --argjson d "$d" --argjson ag "$ag" --arg t "$(now)" '{
      location: "cloud", created: $t, deployment_id: $d.id,
      agent: {id: $d.agent.id, version_pinned: $d.agent.version,
              model: $ag.model.id, effort: ($ag.model.effort.type // "default")},
      environment_id: $d.environment_id,
      resources: ($d.resources // []), vault_ids: ($d.vault_ids // []),
      budget: ($d.budget.max_list_cost.amount // null)}')
  json_update "$REG" '.[$n] = $v' --arg n "$name" --argjson v "$rec"
  echo "registered cloud instance: $name"
  [ -n "$NOSESS" ] && return 0
  run=$(ant beta:deployments run --deployment-id "$DEP" 2>/dev/null) || die "deployments run failed; instance is registered, use: session.sh start $name"
  sid=$(jq -r '.session_id // .session.id // empty' <<<"$run")
  [ -n "$sid" ] || { echo "$run" >&2; die "could not find the session id in the run response"; }
  "$(dirname "$0")/session.sh" track "$name" "$sid" --asked "$ASKED"
}

init_provision() {
  need_asked
  [ -n "$NAME" ] || die "--provision needs --name"
  local args=("$NAME")
  [ -z "$MODEL" ] || args+=(--model "$MODEL")
  [ -z "$EFFORT" ] || args+=(--effort "$EFFORT")
  [ -z "$APT" ] || args+=(--apt "$APT")
  [ -z "$NETWORKING" ] || args+=(--networking "$NETWORKING")
  [ -z "$BUDGET" ] || args+=(--budget "$BUDGET")
  if [ -z "$APPROVED" ]; then
    "$(dirname "$0")/provision.sh" plan "${args[@]}"
    echo "plan only; show it to the user, then re-run with --plan <token from the plan> --approved \"<the user's go-ahead>\""
    return 0
  fi
  "$(dirname "$0")/provision.sh" apply "${args[@]}" --asked "$ASKED" --approved "$APPROVED" --plan "$PLAN_ARG" || return 1
  [ -n "$NOSESS" ] || "$(dirname "$0")/session.sh" start "$NAME" --asked "$ASKED"
}

init_local() {
  [ -f "$AGENT_FILE" ] || die "agent file not found: $AGENT_FILE"
  local f name sha model rec
  f=$(readlink -f "$AGENT_FILE")
  name=${NAME:-$(slug "$(basename "$f" .md)")}-local
  [ -n "${NAME:-}" ] && name=$NAME
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  model=$(sed -n 's/^model:[[:space:]]*//p' "$f" | head -1)
  [ -z "$MODEL" ] || model=$MODEL
  rec=$(jq -n --arg f "$f" --arg s "$sha" --arg m "$model" --arg e "$EFFORT" --arg t "$(now)" \
    '{location: "local", created: $t, local: {agent_file: $f, sha256: $s, model: $m, effort: (if $e=="" then null else $e end)}}')
  json_update "$REG" '.[$n] = $v' --arg n "$name" --argjson v "$rec"
  echo "registered local instance: $name"
}

# Staleness checks for one cloud instance; prints findings.
stale_checks() {
  local n=$1 i a latest dep
  i=$(inst_get "$n") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || {
    local f sha
    f=$(jq -r .local.agent_file <<<"$i"); sha=$(jq -r .local.sha256 <<<"$i")
    [ -f "$f" ] || echo "STALE: agent file missing"
    [ -f "$f" ] && [ "$(sha256sum "$f" | cut -d' ' -f1)" != "$sha" ] && echo "STALE: agent file changed since init"
    return 0; }
  ant_ok
  dep=$(ant beta:deployments retrieve --deployment-id "$(jq -r .deployment_id <<<"$i")" 2>/dev/null) || { echo "UNUSABLE: deployment not readable"; return 0; }
  [ "$(jq -r .archived_at <<<"$dep")" != null ] && echo "UNUSABLE: deployment archived"
  [ "$(jq -r .status <<<"$dep")" != active ] && echo "UNUSABLE: deployment $(jq -r '.status + " " + (.paused_reason // "")' <<<"$dep")"
  a=$(ant beta:agents retrieve --agent-id "$(jq -r .agent.id <<<"$i")" 2>/dev/null) || { echo "UNUSABLE: agent not readable"; return 0; }
  latest=$(jq -r .version <<<"$a")
  [ "$(jq -r .archived_at <<<"$a")" != null ] && echo "UNUSABLE: agent archived"
  [ "$latest" -gt "$(jq -r .agent.version_pinned <<<"$i")" ] && echo "STALE: agent v$latest is newer than pinned v$(jq -r .agent.version_pinned <<<"$i"); re-point the deployment, then re-init"
  [ "$(jq -r .agent.version <<<"$dep")" != "$(jq -r .agent.version_pinned <<<"$i")" ] && echo "STALE: deployment now pins agent v$(jq -r .agent.version <<<"$dep")"
  return 0
}

reconcile() {
  local n=$1 i dep
  i=$(inst_get "$n") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || return 0
  dep=$(jq -r .deployment_id <<<"$i")
  ant beta:sessions list --deployment-id "$dep" --status idle --status running --status rescheduling --max-items -1 2>/dev/null \
    | jq -r '.id // empty' | while read -r sid; do
      jq -e --arg s "$sid" 'has($s)' "$TRK" >/dev/null || echo "ORPHAN: session $sid is live but not tracked (left untouched)"
    done
}

normalize() {
  [ "${2:-}" = plan ] || need_asked
  ant_ok
  local n=$1 i aid eid mid did ag env mem dep aver changes=0 rid ref rname
  i=$(inst_get "$n") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || die "normalize applies to cloud instances"
  split_instance "$n"
  aid=$(jq -r .agent.id <<<"$i"); eid=$(jq -r .environment_id <<<"$i"); did=$(jq -r .deployment_id <<<"$i")
  mid=$(jq -r '[.resources[] | select(.type=="memory_store" and .access=="read_write")][0].memory_store_id // empty' <<<"$i")
  ag=$(ant beta:agents retrieve --agent-id "$aid" 2>/dev/null) || die "cannot read agent"
  env=$(ant beta:environments retrieve --environment-id "$eid" 2>/dev/null) || die "cannot read environment"
  dep=$(ant beta:deployments retrieve --deployment-id "$did" 2>/dev/null) || die "cannot read deployment"
  aver=$(jq -r .version <<<"$ag")
  local plan_text=''
  show() { # kind old new
    if [ "$2" = "$3" ]; then echo "  $1: $2 (ok)"; else echo "  $1: $2 -> $3"; changes=1; plan_text+="$1:$2>$3;"; fi
  }
  echo "PLAN: resource names for $n"
  show agent "$(jq -r .name <<<"$ag")" "$n-agent"
  show environment "$(jq -r .name <<<"$env")" "$n-environment"
  if [ -n "$mid" ]; then
    mem=$(ant beta:memory-stores retrieve --memory-store-id "$mid" 2>/dev/null) || die "cannot read memory store"
    show memory "$(jq -r .name <<<"$mem")" "$PROJECT-memory"
    [ "$(jq -r .name <<<"$mem")" = "$PROJECT-memory" ] || echo "  note: the memory mount path becomes /mnt/memory/$PROJECT-memory in NEW sessions"
  fi
  rid=$(jq -r '[.resources[]? | select(.type=="memory_store" and .access=="read_only") | .memory_store_id] | .[]' <<<"$i" | while read -r x; do
      nm=$(ant beta:memory-stores retrieve --memory-store-id "$x" </dev/null 2>/dev/null | jq -r .name)
      case $nm in *-reference) echo "$x"; break;; esac
    done)
  if [ -n "$rid" ]; then
    ref=$(ant beta:memory-stores retrieve --memory-store-id "$rid" 2>/dev/null); rname=$(jq -r .name <<<"$ref")
    show reference "$rname" "$PROJECT-reference"
  fi
  show deployment "$(jq -r .name <<<"$dep")" "$n-deployment"
  [ "${2:-}" != plan ] || return 0
  [ "$changes" = 1 ] || { echo "nothing to rename"; return 0; }
  local ntok; ntok=$(printf '%s|%s' "$n" "$plan_text" | plan_token)
  [ -n "$APPROVED" ] || { echo "plan token: $ntok   (re-run with --plan $ntok --approved \"<the user's go-ahead>\" to rename; nothing changed)"; return 0; }
  need_plan "$ntok"; audit_log normalize "$n"
  if [ "$(jq -r .name <<<"$ag")" != "$n-agent" ]; then
    ant beta:agents update --agent-id "$aid" --version "$aver" --name "$n-agent" >/dev/null 2>&1 || die "agent rename failed"
    ant beta:deployments update --deployment-id "$did" --agent "$aid" >/dev/null 2>&1 || die "deployment re-point failed (agent was renamed)"
  fi
  [ "$(jq -r .name <<<"$env")" = "$n-environment" ] || ant beta:environments update --environment-id "$eid" --name "$n-environment" >/dev/null 2>&1 || die "environment rename failed"
  [ -z "$mid" ] || [ "$(jq -r .name <<<"$mem")" = "$PROJECT-memory" ] || ant beta:memory-stores update --memory-store-id "$mid" --name "$PROJECT-memory" >/dev/null 2>&1 || die "memory store rename failed"
  [ -z "$rid" ] || [ "$rname" = "$PROJECT-reference" ] || ant beta:memory-stores update --memory-store-id "$rid" --name "$PROJECT-reference" >/dev/null 2>&1 || die "reference store rename failed"
  [ "$(jq -r .name <<<"$dep")" = "$n-deployment" ] || ant beta:deployments update --deployment-id "$did" --name "$n-deployment" >/dev/null 2>&1 || die "deployment rename failed"
  dep=$(ant beta:deployments retrieve --deployment-id "$did" 2>/dev/null)
  json_update "$REG" '.[$n].agent.version_pinned = $v' --arg n "$n" --argjson v "$(jq .agent.version <<<"$dep")"
  echo "renamed; the deployment now pins agent v$(jq -r .agent.version <<<"$dep")"
}

budget_set() {
  need_asked; ant_ok
  local n=$1 cents=${2:-} i did
  audit_log budget "$n $cents"
  case $cents in ''|*[!0-9]*) die "budget needs NAME CENTS (a whole number)";; esac
  i=$(inst_get "$n") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || die "budget applies to cloud instances"
  did=$(jq -r .deployment_id <<<"$i")
  ant beta:deployments update --deployment-id "$did" \
    --budget "{type: limit, max_list_cost: {amount: \"$cents\", currency: USD}}" >/dev/null 2>&1 || die "could not set the deployment budget"
  json_update "$REG" '.[$n].budget = $b' --arg n "$n" --arg b "$cents"
  echo "$n: deployment budget is now $cents; sessions created from now on inherit it (a running session keeps its own: qargi budget NAME CENTS --session SID)"
  if [ -n "${SESSION_ARG:-}" ]; then
    ant beta:sessions update --session-id "$SESSION_ARG" --budget "{type: limit, max_list_cost: {amount: \"$cents\", currency: USD}}" >/dev/null 2>&1 \
      && echo "session $SESSION_ARG raised/lowered to $cents" || echo "qargi: could not change session $SESSION_ARG (it must already have a budget)" >&2
  fi
}

refresh_prompt() {
  need_asked; ant_ok
  local n=$1 i aid ag cur new aver ptok nv
  i=$(inst_get "$n") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || die "refresh-prompt applies to cloud instances"
  split_instance "$n"; aid=$(jq -r .agent.id <<<"$i")
  ag=$(ant beta:agents retrieve --agent-id "$aid" </dev/null 2>/dev/null) || die "cannot read the agent"
  aver=$(jq -r .version <<<"$ag"); cur=$(jq -r '.system // ""' <<<"$ag"); new=$(agent_prompt "$ROLE")
  [ "$cur" != "$new" ] || { echo "the prompt of $aid v$aver is current"; return 0; }
  echo "PLAN: rebuild the system prompt of $aid v$aver ($PROJECT/$ROLE) from the current contract; changes:"
  diff <(printf '%s\n' "$cur") <(printf '%s\n' "$new") | grep -E '^[<>]' | sed 's/^</  -/;s/^>/  +/' | cut -c1-150 | head -60
  ptok=$(printf '%s|%s' "$aver" "$new" | plan_token)
  [ -n "$APPROVED" ] || { echo "plan token: $ptok   (re-run with --plan $ptok --approved \"<the user's go-ahead>\" to apply; nothing changed)"; return 0; }
  need_plan "$ptok"; audit_log refresh-prompt "$n $aid v$aver"
  ant beta:agents update --agent-id "$aid" --version "$aver" --system "$new" </dev/null >/dev/null 2>&1 || die "agent update failed"
  ant beta:deployments update --deployment-id "$(jq -r .deployment_id <<<"$i")" --agent "$aid" </dev/null >/dev/null 2>&1 || die "agent updated but re-pointing the deployment failed"
  nv=$(ant beta:deployments retrieve --deployment-id "$(jq -r .deployment_id <<<"$i")" </dev/null 2>/dev/null | jq .agent.version)
  json_update "$REG" '.[$n].agent.version_pinned = $v' --arg n "$n" --argjson v "$nv"
  echo "prompt refreshed; the deployment now pins agent v$nv"
}

case $verb in
  refresh-prompt) [ -n "$ARG" ] || die "refresh-prompt needs NAME"; refresh_prompt "$ARG";;
  budget) [ -n "$ARG" ] || die "budget needs NAME CENTS"; budget_set "$ARG" "${ARG2:-}";;
  normalize) [ -n "$ARG" ] || die "normalize needs NAME"; normalize "$ARG";;
  init)
    case $LOC in
      cloud) if [ -n "$PROVISION" ]; then init_provision; else init_cloud; fi;;
      local) init_local;;
      *) die "init needs --location local|cloud";;
    esac;;
  list)
    jq -r 'to_entries[] | "\(.key)\t\(.value.location)\t" +
        (if .value.location=="cloud" then "agent v\(.value.agent.version_pinned) \(.value.agent.model // "?")/\(.value.agent.effort // "?")\tenv \(.value.environment_id)"
         else "model \(.value.local.model)/\(.value.local.effort // "default")\t\(.value.local.agent_file)" end)' "$REG" | column -t -s "$(printf '\t')"
    echo "-- active sessions --"
    jq -r 'to_entries[] | select(.value.closed_at==null) | "\(.key)\t\(.value.instance)\t\(.value.status)\tlabel=\(.value.label // "-")\tcost=\(.value.list_cost // "-")\tcollected=\(.value.outputs_collected)\treview=\(.value.review_state)"' "$TRK" | column -t -s "$(printf '\t')"
    [ -n "$RECON" ] && for n in $(jq -r 'keys[]' "$REG"); do reconcile "$n"; done
    exit 0;;
  show)
    [ -n "$ARG" ] || die "show needs NAME"
    inst_get "$ARG" | jq .
    jq --arg n "$ARG" 'to_entries | map(select(.value.instance==$n)) | map({session: .key} + .value)' "$TRK"
    stale_checks "$ARG"
    if [ "$(jq -r .location <<<"$(inst_get "$ARG")")" = cloud ]; then
      normalize "$ARG" plan 2>&1 | grep -E -- '->|note:|not a standard' | sed 's/^/NAMING: /' || true
    fi
    [ -n "$RECON" ] && reconcile "$ARG"
    exit 0;;
  remove)
    [ -n "$ARG" ] || die "remove needs NAME"
    inst_get "$ARG" >/dev/null
    live=$(jq -r --arg n "$ARG" '[to_entries[] | select(.value.instance==$n and .value.closed_at==null)] | length' "$TRK")
    [ "$live" = 0 ] || die "$live open session(s) for $ARG; close them first (the registry entry is all this removes)"
    json_update "$REG" 'del(.[$n])' --arg n "$ARG"
    echo "removed registry entry $ARG (deployment, agent and environment untouched)";;
  *) die "usage: registry.sh init|list|show|remove ...";;
esac
