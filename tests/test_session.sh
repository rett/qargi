#!/usr/bin/env bash
# Why a session went idle: the tracker's stop_reason is read from the last session.status_idle event, because the
# session object itself carries no stop_reason. The fake ant returns the shapes the real one does (a session object
# without stop_reason; events with stop_reason and, for requires_action, event_ids). Offline. Run: tests/test_session.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export QARGI_CONF=$T/c QARGI_STATE=$T/s FAKE=$T/fake
mkdir -p "$T/c" "$T/s" "$T/bin" "$FAKE"
cat > "$T/bin/ant" <<'EOS'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE/ant.log"
arg() { local k=$1; shift; while [ $# -gt 0 ]; do [ "$1" = "$k" ] && { echo "$2"; return; }; shift; done; }
sid=$(arg --session-id "$@")
case $1 in
  auth) exit 0;;
  beta:sessions)
    case $2 in
      retrieve)
        # the first read of a session with a "flip" file says running, later ones idle
        if [ -f "$FAKE/flip.$sid" ] && [ ! -f "$FAKE/flipped.$sid" ]; then st=running; touch "$FAKE/flipped.$sid"; else st=$(cat "$FAKE/status.$sid" 2>/dev/null || echo idle); fi
        jq -nc --arg id "$sid" --arg st "$st" '{agent:{id:"agent_B"},archived_at:null,budget:{type:"limit",max_list_cost:{amount:"3000",currency:"USD"}},
          created_at:"2026-10-30T10:00:00Z",deployment_id:"depl_B",environment_id:"env_1",id:$id,metadata:{},outcome_evaluations:[],resources:[],
          stats:{active_seconds:12},status:$st,title:"alpha-build-x",type:"session",updated_at:"2026-10-30T10:30:00Z",
          usage:{list_cost:{amount:"120",currency:"USD"}},vault_ids:[]}';;
      *) echo '{}';;
    esac;;
  beta:sessions:events)
    case $2 in
      list) cat "$FAKE/events.$sid" 2>/dev/null;;
      send) printf '%s\n' "$*" >> "$FAKE/sent.log"; echo '{}';;
    esac;;
  *) echo '{}';;
esac
EOS
chmod 755 "$T/bin/ant"; export PATH=$T/bin:$PATH
jq -n '{"alpha-build":{location:"cloud",deployment_id:"depl_B",environment_id:"env_1",agent:{id:"agent_B",version_pinned:1}}}' > "$T/c/instances.json"
row() { jq -n --arg s "$1" '{($s): {instance:"alpha-build",label:"x",created:"2026-10-30T10:00:00Z",status:"unknown",stop_reason:null,last_seen:"2026-10-30T10:00:00Z",list_cost:null,
  budget:"3000",outputs_collected:false,review_state:"pending",closed_at:null,asked:"a"}}'; }
{ row sesn_a; row sesn_b; row sesn_c; row sesn_d; row sesn_e; row sesn_w; row sesn_v; } | jq -s add > "$T/s/sessions.json"
trk() { jq -r --arg s "$1" ".[\$s] | ($2)" "$T/s/sessions.json"; }

# the events, as the real CLI emits them: one JSON object per event, with other event types and a thread_status_idle mixed in
cat > "$FAKE/events.sesn_a" <<'EOF'
{"id":"sevt_1","type":"agent.message","processed_at":"2026-10-30T10:00:01Z"}
{"id":"sevt_2","type":"session.status_idle","processed_at":"2026-10-30T10:05:00Z","stop_reason":{"type":"requires_action","event_ids":["sevt_9"]},"stop_details":null}
{"id":"sevt_3","type":"session.status_running","processed_at":"2026-10-30T10:06:00Z"}
{"id":"sevt_4","type":"session.status_idle","processed_at":"2026-10-30T10:20:00Z","stop_reason":{"type":"end_turn"},"stop_details":null}
{"id":"sevt_5","type":"session.thread_status_idle","processed_at":"2026-10-30T10:21:00Z","agent_name":"x","session_thread_id":"t","stop_reason":{"type":"retries_exhausted"}}
EOF
$DA status sesn_a >/dev/null 2>&1
[ "$(trk sesn_a .stop_reason)" = end_turn ] && ok "the last session.status_idle event gives the stop reason (a thread_status_idle after it is ignored)" || no "end_turn: $(trk sesn_a .stop_reason)"
[ "$(trk sesn_a .status)" = idle ] && [ "$(trk sesn_a .list_cost)" = 120 ] && ok "status and cost are still read from the session object" || no "status/cost"

cat > "$FAKE/events.sesn_b" <<'EOF'
{"id":"sevt_4","type":"session.status_idle","processed_at":"2026-10-30T10:20:00Z","stop_reason":{"type":"requires_action","event_ids":["sevt_9","sevt_10"]},"stop_details":null}
{"id":"sevt_2","type":"session.status_idle","processed_at":"2026-10-30T10:05:00Z","stop_reason":{"type":"end_turn"},"stop_details":null}
EOF
$DA status sesn_b >/dev/null 2>&1
[ "$(trk sesn_b .stop_reason)" = requires_action ] && [ "$(trk sesn_b '.stop_event_ids|join(",")')" = "sevt_9,sevt_10" ] && ok "requires_action is recorded with the events it waits on, whatever order the events come in" || no "requires_action: $(trk sesn_b '.stop_reason, .stop_event_ids')"

$DA status sesn_c >/dev/null 2>&1
[ "$(trk sesn_c .stop_reason)" = null ] && ok "no status_idle event: the field stays empty" || no "no events: $(trk sesn_c .stop_reason)"

cp "$FAKE/events.sesn_a" "$FAKE/events.sesn_d"; echo running > "$FAKE/status.sesn_d"
jq '.sesn_d.stop_reason = "end_turn"' "$T/s/sessions.json" > "$T/x.json" && mv "$T/x.json" "$T/s/sessions.json"
$DA status sesn_d >/dev/null 2>&1
[ "$(trk sesn_d .stop_reason)" = null ] && ok "a running session has no stop reason (an earlier one is cleared)" || no "running: $(trk sesn_d .stop_reason)"
grep -q "sessions:events list --session-id sesn_d" "$FAKE/ant.log" && no "events were listed for a running session" || ok "events are only read for an idle session"

# the interrupt: end_turn also follows qargi stop, so stop records it
cp "$FAKE/events.sesn_a" "$FAKE/events.sesn_e"
$DA stop sesn_e >/dev/null 2>&1; $DA status sesn_e >/dev/null 2>&1
[ "$(trk sesn_e .stop_reason)" = end_turn ] && [ "$(trk sesn_e .interrupt_sent_at)" != null ] && ok "stop records interrupt_sent_at next to the end_turn it causes" || no "interrupt: $(trk sesn_e '.stop_reason, .interrupt_sent_at')"
grep -q "user.interrupt" "$FAKE/sent.log" && ok "stop still sends the interrupt" || no "interrupt not sent"
[ "$(trk sesn_a .interrupt_sent_at)" = null ] && ok "a session nobody stopped has no interrupt mark" || no "mark on another session"
out=$($DA report 2>&1)
echo "$out" | grep -q "stopped by qargi (interrupt sent, end_turn): 1" && echo "$out" | grep -q "awaiting review (finished, end_turn): 1" && ok "report separates the stopped session from the finished one" || no "report: $out"
echo "$out" | grep -q "stopped needing input: requires_action 1" && ok "report shows the session that stopped needing input" || no "report needs input"
$DA send alpha-build "next task" --label again --asked "t" --session sesn_e >/dev/null 2>&1
[ "$(trk sesn_e .status)" = running ] && [ "$(trk sesn_e .interrupt_sent_at)" = null ] && ok "sending a new task clears the interrupt mark" || no "send: $(trk sesn_e '.status, .interrupt_sent_at')"

# watch prints the recovered reason (the poller sleeps 30 s between reads, so the two run side by side)
cat > "$FAKE/events.sesn_w" <<'EOF'
{"id":"sevt_4","type":"session.status_idle","processed_at":"2026-10-30T10:20:00Z","stop_reason":{"type":"end_turn"}}
EOF
cat > "$FAKE/events.sesn_v" <<'EOF'
{"id":"sevt_4","type":"session.status_idle","processed_at":"2026-10-30T10:20:00Z","stop_reason":{"type":"budget_reached"}}
EOF
touch "$FAKE/flip.sesn_w" "$FAKE/flip.sesn_v"
timeout 90 "$DA" watch sesn_w 60 > "$T/w.out" 2>&1 &
p1=$!
timeout 90 "$DA" watch sesn_v 60 > "$T/v.out" 2>&1 &
p2=$!
wait "$p1"; wait "$p2"
[ "$(cat "$T/w.out")" = "QARGI WATCH sesn_w idle end_turn" ] && ok "watch reports the stop reason read from the events" || no "watch end_turn: $(cat "$T/w.out")"
[ "$(cat "$T/v.out")" = "QARGI WATCH sesn_v budget_reached budget_reached" ] && ok "watch reports budget_reached, which the session object never carried" || no "watch budget: $(cat "$T/v.out")"
rm -rf "$T"; exit $fail
