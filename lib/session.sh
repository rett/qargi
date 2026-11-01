#!/usr/bin/env bash
# qargi cloud session verbs: track, start, send, status, stop, mark, close.
# Every verb that creates or drives a session needs --asked "<user's request>".
#   session.sh start NAME [--label L] --asked "..."
#   session.sh send NAME "<task text>" [--label L] [--session SID] [--new] --asked "..."
#   session.sh status [SID|NAME]
#   session.sh stop SID
#   session.sh mark SID applied|rejected|pending [--why CODE]   (CODE from lib/reasons.json; only with applied or rejected)
#   session.sh close SID [--no-outputs]   (--no-outputs: the task produced no files, e.g. memory curation)
#   session.sh track NAME SID --asked "..."     (used by init)
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
LABEL='' SESSION='' NEW='' ASKED='' NOOUT='' WHY='' POS=()
while [ $# -gt 0 ]; do
  case $1 in
    --label) LABEL=$2; shift 2;;
    --session) SESSION=$2; shift 2;;
    --new) NEW=1; shift;;
    --no-outputs) NOOUT=1; shift;;
    --asked) ASKED=$2; shift 2;;
    --why) WHY=$2; shift 2;;
    -*) die "unknown option $1";;
    *) POS+=("$1"); shift;;
  esac
done

cloud_inst() {
  local i; i=$(inst_get "$1") || exit 1
  [ "$(jq -r .location <<<"$i")" = cloud ] || die "$1 is a local instance; sessions are cloud only"
  echo "$i"
}

# A budget can only be attached when a session is created, so it lives on the
# deployment (init --budget, or the provisioned deployment file) and sessions
# inherit it. Warn when a session has none.
check_budget() {
  local sid=$1 b
  b=$(ant beta:sessions retrieve --session-id "$sid" 2>/dev/null | jq -r '.budget.max_list_cost.amount // empty')
  if [ -n "$b" ]; then
    json_update "$TRK" '.[$s].budget = $b' --arg s "$sid" --arg b "$b"
  else
    echo "qargi: warning: session $sid has NO budget; set one on the deployment (registry.sh init ... --budget CENTS) before the next session" >&2
    json_update "$TRK" '.[$s].budget = "none"' --arg s "$sid"
  fi
}

# A session is named <instance>-<task-slug> (its title in the console and API).
set_title() { # sid instance label
  [ -n "$3" ] || return 0
  ant beta:sessions update --session-id "$1" --title "$2-$3" >/dev/null 2>&1 \
    || echo "qargi: warning: could not set the title of $1" >&2
}

track() {
  local name=$1 sid=$2 i
  i=$(cloud_inst "$name") || exit 1
  json_update "$TRK" '.[$s] = {instance: $n, label: $l, created: $t, status: "unknown", stop_reason: null,
      last_seen: $t, list_cost: null, budget: $b, outputs_collected: false, review_state: "pending",
      closed_at: null, asked: $a}' \
    --arg s "$sid" --arg n "$name" --arg l "$LABEL" --arg t "$(now)" --arg b "none" --arg a "$ASKED"
  set_title "$sid" "$name" "${LABEL:-standby}"
  trk_refresh "$sid"
  check_budget "$sid"
  LAST_SID=$sid
  echo "tracking session $sid for $name (budget $(jq -r --arg s "$sid" '.[$s].budget' "$TRK"))"
}

# A session with the project's repository mounted (private repositories). The token is read
# from the credential file and goes to ant on stdin; it is in no argument and no log.
start_with_repo() { # name [credential-file] -> session id (the lead always starts this way: its members are threads of one session)
  local i dep url body
  i=$(inst_get "$1") || exit 1
  dep=$(ant beta:deployments retrieve --deployment-id "$(jq -r .deployment_id <<<"$i")" </dev/null 2>/dev/null) || die "cannot read the deployment"
  url=$(jq -r .repo.url "$DA_CONF/projects/${1%%-*}.json")
  body=$(jq -n --argjson d "$dep" --arg url "$url" --rawfile tok "${2:-/dev/null}" '{
      agent: {id: $d.agent.id, type: "agent", version: $d.agent.version},
      environment_id: $d.environment_id, vault_ids: ($d.vault_ids // []),
      resources: (($d.resources // []) + (if ($tok | length) > 0 then [{type: "github_repository", url: $url, authorization_token: ($tok | rtrimstr("\n"))}] else [] end)),
      initial_events: $d.initial_events, metadata: {deployment_id: $d.id}}
      + (if $d.budget then {budget: $d.budget} else {} end)')
  audit_log session-with-repo "$1 credential file $(basename "${2:-none}")"
  if [ -n "${QARGI_DRY_RUN:-}" ]; then jq '.resources |= map(if .authorization_token then .authorization_token="***" else . end)' <<<"$body"; return 0; fi
  printf '%s' "$body" | ant beta:sessions create 2>/dev/null | jq -r '.id // empty'
}

start() {
  need_asked
  local name=$1 i run sid cf
  i=$(cloud_inst "$name") || exit 1
  split_instance "$name"
  # an instance of a read-only role needs a read-only barrier on the cloud surface, or the project's recorded acceptance that there is none
  [ "$(role_class "$ROLE" 2>/dev/null)" != read-only ] || barrier_guard cloud "$PROJECT"
  ant_ok
  cf=$(cred_file "$PROJECT")
  if [ -n "$cf" ] || [ "$ROLE" = lead ]; then
    sid=$(start_with_repo "$name" "$cf") || exit 1
    [ -n "${QARGI_DRY_RUN:-}" ] && exit 0
    [ -n "$sid" ] || die "could not create the session with the repository mounted (check: qargi credential check $PROJECT)"
    track "$name" "$sid"; return 0
  fi
  run=$(ant beta:deployments run --deployment-id "$(jq -r .deployment_id <<<"$i")" 2>/dev/null) || die "deployments run failed"
  sid=$(jq -r '.session_id // .session.id // empty' <<<"$run")
  [ -n "$sid" ] || { echo "$run" >&2; die "no session id in the run response"; }
  track "$name" "$sid"
}

send() {
  need_asked; ant_ok
  local name=$1 task=$2 sid i
  valid_slug "$LABEL" || die "send needs --label <task-slug> (lower-case letters, digits, '-'): the session is named <instance>-<task-slug>; use the same slug for the agent/<slug> branch"
  i=$(cloud_inst "$name") || exit 1
  [ -n "$task" ] || die "send needs the task text"
  if [ -n "$NEW" ]; then
    start "$name" >/dev/null
    sid=$LAST_SID
  else
    sid=${SESSION:-$(inst_idle_session "$name")}
    [ -n "$sid" ] || die "no idle tracked session for $name; use --new or start"
  fi
  trk_refresh "$sid" || die "cannot read session $sid"
  check_budget "$sid" 2>/dev/null
  [ "$(jq -r --arg s "$sid" '.[$s].budget' "$TRK")" != none ] || die "session $sid has no spend budget; set one on the deployment (qargi instances budget $name CENTS --asked ...) and start a new session"
  [ "$(jq -r --arg s "$sid" '.[$s].status' "$TRK")" = idle ] || die "session $sid is not idle (see: status)"
  json_update "$TRK" '.[$s].label = $l' --arg s "$sid" --arg l "$LABEL"
  set_title "$sid" "$name" "$LABEL"
  ant beta:sessions:events send --session-id "$sid" \
    --event "$(jq -n --arg t "$task" '{type: "user.message", content: [{type: "text", text: $t}]}')" >/dev/null \
    || die "could not send the task"
  json_update "$TRK" '.[$s] += {status: "running", outputs_collected: false, review_state: "pending", sent_at: $t, interrupt_sent_at: null}' \
    --arg s "$sid" --arg t "$(now)"
  echo "sent to $sid; next: watch.sh $sid (Bash run_in_background)"
}

status() {
  local target=${POS[0]:-} sid
  if [ -z "$target" ]; then
    for sid in $(jq -r 'to_entries[]|select(.value.closed_at==null)|.key' "$TRK"); do trk_refresh "$sid"; done
    jq -r 'to_entries[]|select(.value.closed_at==null)|"\(.key) \(.value.instance) \(.value.status) \(.value.stop_reason // "-") cost=\(.value.list_cost // "-")/\(.value.budget) collected=\(.value.outputs_collected) review=\(.value.review_state)"' "$TRK"
    return 0
  fi
  case $target in sesn_*) sid=$target;; *) sid=$(inst_idle_session "$target");; esac
  [ -n "$sid" ] || die "no session found for $target"
  trk_refresh "$sid" || die "cannot read $sid"
  jq --arg s "$sid" '.[$s]' "$TRK"
}

stop() {
  local sid=${POS[0]:-}; [ -n "$sid" ] || die "stop needs SID"
  ant beta:sessions:events send --session-id "$sid" --event '{type: user.interrupt}' >/dev/null || die "interrupt failed"
  # an interrupted turn ends with stop_reason end_turn, like a finished one: keep what tells them apart
  json_update "$TRK" 'if has($s) then .[$s].interrupt_sent_at = $t else . end' --arg s "$sid" --arg t "$(now)"
  echo "interrupt sent to $sid; the session returns to idle, then collect.sh"
}

mark() {
  local sid=${POS[0]:-} st=${POS[1]:-}
  case $st in applied|rejected|pending) ;; *) die "mark SID applied|rejected|pending [--why CODE]";; esac
  jq -e --arg s "$sid" 'has($s)' "$TRK" >/dev/null || die "session $sid is not tracked"
  if [ -n "$WHY" ]; then
    [ "$st" != pending ] || die "--why goes with applied or rejected"
    jq -e --arg w "$WHY" '.codes | index($w)' "$(dirname "$(readlink -f "$0")")/reasons.json" >/dev/null \
      || die "--why is one of: $(jq -r '.codes | join(", ")' "$(dirname "$(readlink -f "$0")")/reasons.json")"
  fi
  json_update "$TRK" '.[$s].review_state = $r | .[$s].review_reason = (if $w == "" then null else $w end)
      | .[$s].reviewed_at = (if $r == "pending" then null else $t end)' --arg s "$sid" --arg r "$st" --arg w "$WHY" --arg t "$(now)"
}

# Close = archive, only after outputs are collected and a review verdict exists.
close() {
  local sid=${POS[0]:-} row
  [ -n "$sid" ] || die "close needs SID"
  row=$(jq -e --arg s "$sid" '.[$s]' "$TRK") || die "session $sid is not tracked"
  trk_refresh "$sid" || die "cannot read $sid"
  [ "$(jq -r --arg s "$sid" '.[$s].status' "$TRK")" != running ] || die "session is running; stop it first"
  if [ -z "$NOOUT" ]; then
    [ "$(jq -r .outputs_collected <<<"$row")" = true ] || die "outputs not collected; run collect.sh first (or pass --no-outputs if the task produced no files)"
  else
    json_update "$TRK" '.[$s].outputs_collected = "not-applicable"' --arg s "$sid"
  fi
  [ "$(jq -r --arg s "$sid" '.[$s].review_state' "$TRK")" != pending ] || die "review verdict pending; mark applied or rejected first"
  ant beta:sessions archive --session-id "$sid" >/dev/null || die "archive failed"
  json_update "$TRK" '.[$s].closed_at = $t | .[$s].status = "archived"' --arg s "$sid" --arg t "$(now)"
  echo "archived $sid (not deleted)"
}

case $verb in
  track) track "${POS[0]:-}" "${POS[1]:-}";;
  start) start "${POS[0]:-}";;
  send) send "${POS[0]:-}" "${POS[1]:-}";;
  status) status;;
  stop) stop;;
  mark) mark;;
  close) close;;
  *) die "usage: session.sh track|start|send|status|stop|mark|close ...";;
esac
