#!/usr/bin/env bash
# Bounded poller for one cloud session. Run with the Bash tool's
# run_in_background; it prints exactly one line when it ends:
#   QARGI WATCH <sid> idle|terminated|budget_reached|budget_tight|timeout|auth|error [stop_reason]
# Usage: watch.sh SID [MAX_SECONDS] [--warn PCT]   (default 7200, poll every 30 s)
# budget_tight: the session's cost reached PCT percent of its spend ceiling (default 85, 0 = never). It ends
# the watch early, with the cost and the ceiling in cents, so the coordinator can offer to raise the ceiling
# (qargi instances budget NAME CENTS --session SID) and watch again.
. "$(dirname "$0")/lib.sh"

sid=${1:-}; max=7200; warn=85; shift || true
while [ $# -gt 0 ]; do
  case $1 in
    --warn) warn=${2:-}; shift 2 || die "--warn needs a percent";;
    *[!0-9]*|'') die "usage: watch.sh SID [MAX_SECONDS] [--warn PCT]";;
    *) max=$1; shift;;
  esac
done
[ -n "$sid" ] || die "usage: watch.sh SID [MAX_SECONDS] [--warn PCT]"
case $warn in ''|*[!0-9]*) die "--warn is a whole percent (0 turns it off)";; esac

start=$(date +%s); seen_running=
while :; do
  if ! s=$(ant beta:sessions retrieve --session-id "$sid" 2>/dev/null); then
    ant auth status >/dev/null 2>&1 || { echo "QARGI WATCH $sid auth"; exit 3; }
    sleep 30; continue
  fi
  st=$(jq -r .status <<<"$s"); why=$(jq -r '.stop_reason.type // "-"' <<<"$s")
  [ "$st" = running ] && seen_running=1
  elapsed=$(( $(date +%s) - start ))
  # Just after a send the session can still read idle; give it 90 s to start.
  if [ "$st" != running ] && { [ -n "$seen_running" ] || [ "$elapsed" -ge 90 ]; }; then
    trk_refresh "$sid" >/dev/null 2>&1
    # the session object carries no stop reason; trk_refresh read it from the last session.status_idle event
    [ "$why" != "-" ] || why=$(jq -r --arg s "$sid" '.[$s].stop_reason // "-"' "$TRK" 2>/dev/null || echo -)
    [ "$why" = budget_reached ] && st=budget_reached
    echo "QARGI WATCH $sid $st $why"; exit 0
  fi
  if [ "$warn" -gt 0 ] && [ "$st" = running ]; then
    cost=$(jq -r '.usage.list_cost.amount // empty' <<<"$s"); lim=$(jq -r '.budget.max_list_cost.amount // empty' <<<"$s")
    if [ -n "$cost" ] && [ -n "$lim" ] && [ "$lim" -gt 0 ] 2>/dev/null && [ $(( cost * 100 / lim )) -ge "$warn" ]; then
      echo "QARGI WATCH $sid budget_tight $cost/$lim"; exit 4
    fi
  fi
  if [ "$elapsed" -ge "$max" ]; then
    echo "QARGI WATCH $sid timeout $why"; exit 2
  fi
  sleep 30
done
