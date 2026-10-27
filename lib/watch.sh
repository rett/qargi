#!/usr/bin/env bash
# Bounded poller for one cloud session. Run with the Bash tool's
# run_in_background; it prints exactly one line when it ends:
#   QARGI WATCH <sid> idle|terminated|budget_reached|timeout|auth|error [stop_reason]
# Usage: watch.sh SID [MAX_SECONDS]   (default 7200, poll every 30 s)
. "$(dirname "$0")/lib.sh"

sid=${1:-}; max=${2:-7200}
[ -n "$sid" ] || die "usage: watch.sh SID [MAX_SECONDS]"

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
    [ "$why" = budget_reached ] && st=budget_reached
    echo "QARGI WATCH $sid $st $why"; exit 0
  fi
  if [ "$elapsed" -ge "$max" ]; then
    echo "QARGI WATCH $sid timeout $why"; exit 2
  fi
  sleep 30
done
