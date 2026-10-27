#!/usr/bin/env bash
# dev-agent registry verbs: init, list, show, remove.
# Usage: registry.sh init --location cloud --deployment ID [--name N] [--no-session] --asked "..."
#        registry.sh init --location cloud --deployment ID --model M --effort E --asked "..." [--approved "..."]
#                         (changes the existing agent's model/effort; shows the change first)
#        registry.sh init --location cloud --provision --name N [--model M] [--effort E] [--apt "pkg ..."]
#                         [--networking unrestricted|limited] --asked "..." [--approved "..."]
#                         (creates new resources through provision.sh; without --approved it only prints the plan)
#        registry.sh init --location local --agent FILE [--name N] [--model M] [--effort E]
#        registry.sh list [--reconcile]
#        registry.sh show NAME [--reconcile]
#        registry.sh remove NAME
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
LOC='' DEP='' AGENT_FILE='' NAME='' NOSESS='' ASKED='' RECON='' ARG='' MODEL='' EFFORT='' PROVISION='' APT='' NETWORKING='' APPROVED=''
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
    -*) die "unknown option $1";;
    *) ARG=$1; shift;;
  esac
done

case $EFFORT in ''|low|medium|high|xhigh|max) ;; *) die "--effort low|medium|high|xhigh|max";; esac
[ -z "$MODEL" ] || printf '%s' "$MODEL" | grep -Eq '^[a-z0-9][a-z0-9.-]*$' || die "--model: a model alias or id (letters, digits, . -)"

slug() { printf '%s' "$1" | tr '[:upper:] _' '[:lower:]--' | tr -cd 'a-z0-9-' | sed 's/--*/-/g; s/^-//; s/-$//'; }

init_cloud() {
  need_asked; ant_ok
  [ -n "$DEP" ] || die "init --location cloud needs --deployment ID"
  local d name rec run sid
  d=$(ant beta:deployments retrieve --deployment-id "$DEP" 2>/dev/null) || die "cannot read deployment $DEP"
  [ "$(jq -r '.archived_at' <<<"$d")" = null ] || die "deployment is archived"
  local ag aid aver cur_m cur_e new_m new_e
  aid=$(jq -r .agent.id <<<"$d")
  ag=$(ant beta:agents retrieve --agent-id "$aid" 2>/dev/null) || die "cannot read agent $aid"
  aver=$(jq -r .version <<<"$ag"); cur_m=$(jq -r .model.id <<<"$ag"); cur_e=$(jq -r '.model.effort.type // "default"' <<<"$ag")
  new_m=${MODEL:-$cur_m}; new_e=${EFFORT:-$cur_e}
  if [ "$new_m" != "$cur_m" ] || { [ -n "$EFFORT" ] && [ "$new_e" != "$cur_e" ]; }; then
    echo "PLAN: agent $aid v$aver: model $cur_m -> $new_m, effort $cur_e -> $new_e (creates a new agent version and re-points the deployment)"
    [ -n "$APPROVED" ] || { echo "re-run with --approved \"<the user's go-ahead>\" to apply; nothing changed"; return 0; }
    ant beta:agents update --agent-id "$aid" --version "$aver" --model "{id: $new_m, effort: $new_e}" >/dev/null 2>&1 || die "agent update failed"
    ant beta:deployments update --deployment-id "$DEP" --agent "$aid" >/dev/null 2>&1 || die "deployment re-point failed (agent was updated)"
    d=$(ant beta:deployments retrieve --deployment-id "$DEP" 2>/dev/null) || die "cannot re-read deployment"
    ag=$(ant beta:agents retrieve --agent-id "$aid" 2>/dev/null)
    echo "agent updated to v$(jq -r .version <<<"$ag"); deployment now pins v$(jq -r .agent.version <<<"$d")"
  fi
  name=${NAME:-$(slug "$(jq -r '.name' <<<"$d")")}
  [ -n "$name" ] || die "empty instance name; pass --name"
  rec=$(jq -n --argjson d "$d" --argjson ag "$ag" --arg t "$(now)" '{
      location: "cloud", created: $t, deployment_id: $d.id,
      agent: {id: $d.agent.id, version_pinned: $d.agent.version,
              model: $ag.model.id, effort: ($ag.model.effort.type // "default")},
      environment_id: $d.environment_id,
      resources: ($d.resources // []), vault_ids: ($d.vault_ids // []),
      budget_default_cents: 500}')
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
  if [ -z "$APPROVED" ]; then
    "$(dirname "$0")/provision.sh" plan "${args[@]}"
    echo "plan only; show it to the user, then re-run with --approved \"<the user's go-ahead>\""
    return 0
  fi
  "$(dirname "$0")/provision.sh" apply "${args[@]}" --asked "$ASKED" --approved "$APPROVED" || return 1
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

case $verb in
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
