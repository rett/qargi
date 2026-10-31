#!/usr/bin/env bash
# The supervisor of stalled agent runs (design: supervisor/DESIGN.md). Hooks only record (qargi hook ...); the one
# actor is the idempotent tick. Nothing here sends a message by itself.
#   supervise.sh tick [--now ISO] [--json]       fold the events, classify the runs, print QARGI SUPERVISE lines, prepare nudges
#   supervise.sh status [--now ISO] [--json]     the runs by class; warns when the last tick is older than twice the interval
#   supervise.sh delivered KEY [--now ISO]       record that the coordinating session delivered a local run's prepared nudge
#   supervise.sh nudge SID --asked "..." [--now ISO]   send the fixed nudge template to a cloud session, only when the caps allow
#   supervise.sh hooks [--qargi COMMAND]         print the settings.json hook snippet; never writes the file
# The logic is lib/supervise.py; the numbers are lib/supervise-defaults.json. The cloud send is the only part that needs
# the cloud tool (ant) and the user's request (--asked), like every cloud verb.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
py() { python3 -I "$(dirname "$(readlink -f "$0")")/supervise.py" "$@"; }
case $verb in
  tick|status|delivered|hooks) py "$verb" "$@"; exit $?;;
  nudge)
    SID='' NOW='' ASKED=''
    while [ $# -gt 0 ]; do
      case $1 in
        --asked) ASKED=${2:-}; shift 2 || die "--asked needs the request";;
        --now) NOW=${2:-}; shift 2 || die "--now needs a time";;
        -*) die "unknown option $1";;
        *) [ -z "$SID" ] || die "nudge takes one session id"; SID=$1; shift;;
      esac
    done
    [ -n "$SID" ] || die "usage: supervise.sh nudge SID --asked \"<the user's request to nudge it>\""
    nowarg=(); [ -z "$NOW" ] || nowarg=(--now "$NOW")
    export ASKED
    need_asked
    chk=$(py nudge-check "$SID" "${nowarg[@]}") || exit $?
    if [ "$(jq -r .ok <<<"$chk")" != true ]; then
      AUDIT_ORIGIN=supervisor audit_log "supervise:nudge-refused" "$SID $(jq -r .reason <<<"$chk")"
      die "nudge refused: $(jq -r .reason <<<"$chk")"
    fi
    ant_ok
    ant beta:sessions:events send --session-id "$SID" \
      --event "$(jq -n --arg t "$(jq -r .text <<<"$chk")" '{type: "user.message", content: [{type: "text", text: $t}]}')" >/dev/null \
      || die "could not send the nudge"
    n=$(py nudge-record "$SID" "${nowarg[@]}")
    AUDIT_ORIGIN=supervisor audit_log "supervise:nudge-sent" "$SID nudge $n of $(jq -r .max <<<"$chk")"
    echo "nudge $n of $(jq -r .max <<<"$chk") sent to $SID (a nudge is not an approval; the next one is allowed after the cooldown)";;
  *) die "usage: supervise.sh tick|status|nudge|delivered|hooks ...";;
esac
