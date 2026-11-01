#!/usr/bin/env bash
# qargi marshal: who leads which feature (identity, lease, status, handoff, takeover, the shell API and its renewer).
# Written from the SPEC of the feature, not from its code. Time is injected with QARGI_MARSHAL_NOW (epoch seconds); only the
# renewer tests run in real time (QARGI_MARSHAL_RENEW_SEC=1).
# Run: tests/test_marshal.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TOOL=$PWD
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home
export QARGI_CONF=$T/c QARGI_STATE=$T/home/.qargi/state GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
S=$QARGI_STATE; AUDIT=$S/audit.log
mkdir -p "$HOME" "$T/c/projects" "$S/features"
R=$T/app; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
feat() { # name file...: branch feature/NAME from develop with one commit per file (each file holds its own name)
  local n=$1 w f; shift; git -C "$R" branch "feature/$n" develop
  [ $# -gt 0 ] || return 0
  w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "feature/$n"
  for f in "$@"; do echo "$n" > "$w/$f"; git -C "$w" add -A; git -C "$w" commit -q -m "$n $f"; done
  git -C "$R" worktree remove --force "$w"
}
for n in f1 f2 f3 f5 f6 f7 f8 f9 old; do feat "$n"; done
feat ov1 shared.txt; feat ov2 shared.txt
ttl() { jq --argjson n "$1" '.marshal.ttl = $n' "$T/c/projects/app.json" > "$T/c/p.tmp" && mv "$T/c/p.tmp" "$T/c/projects/app.json"; }  # the project answer marshal.ttl, minutes
rec() { echo "$S/features/app-$1.json"; }
j() { jq -r "$2" "$(rec "$1")"; }            # j NAME FILTER
# M NOW ARGS...: marshal at the injected time; stdout and stderr in $T/o and $T/e, exit status returned
M() { local now=$1; shift; QARGI_MARSHAL_NOW=$now "$DA" marshal "$@" >"$T/o" 2>"$T/e"; }
out() { cat "$T/o" "$T/e"; }
t0=1000000; TTL=900   # the default ttl is 15 minutes

# --- claim: the first marshal assertion (everything below needs it)
M $t0 claim f1 --as alice --goal "ship the thing"; rc=$?
if [ $rc != 0 ]; then no "SPEC claim: claim of an unled feature by alice must exit 0 and make her lead (rc=$rc): $(out)"; echo "stopping: nothing else can be checked without claim"; exit 1; fi
ok "claim: an unled feature gets its lead"
[ "$(j f1 .lead.id)" = alice ] && [ "$(j f1 .status)" = active ] && [ "$(j f1 .goal)" = "ship the thing" ] && [ "$(j f1 .rev)" = 1 ] && ok "claim: record has lead alice, status active, the goal, rev 1" || no "SPEC claim record: $(cat "$(rec f1)")"
for k in feature project status goal plan note rev lead renewed_at updated_at finished_at; do jq -e "has(\"$k\")" "$(rec f1)" >/dev/null || no "SPEC record: key $k missing in $(cat "$(rec f1)")"; done
jq -e '.lead | has("id") and has("user") and has("host") and has("since")' "$(rec f1)" >/dev/null && ok "record keys: the lead has id, user, host, since" || no "SPEC lead keys: $(j f1 .lead)"
M $t0 claim f1 --as alice && ok "claim: the same identity again is idempotent" || no "SPEC claim idempotent: $(out)"
M $t0 claim nosuch --as alice; [ $? = 1 ] && ok "claim: needs the branch feature/NAME (exit 1)" || no "SPEC claim without branch feature/NAME must exit 1"
M $((t0 + 10)) claim f1 --as bob; rc=$?
[ $rc = 1 ] && grep -q "is led by" <(out) && grep -q alice <(out) && ok "claim: another LIVE lead refuses, naming 'is led by' and the id" || no "SPEC live claim: rc=$rc $(out)"

# --- live and stale at the ttl boundary (default 15 minutes), on a record claimed at t0
M $((t0 + TTL - 1)) check f1 --as bob; [ $? = 1 ] && ok "ttl: one second before the ttl the lead is still LIVE" || no "SPEC live: now-renewed_at < ttl means live: $(out)"
M $((t0 + TTL)) claim f1 --as bob; rc=$?
[ $rc = 1 ] && grep -qi "takeover" <(out) && ok "claim on a STALE lead exits 1 and mentions takeover" || no "SPEC stale claim: rc=$rc $(out)"
M $((t0 + TTL)) check f1 --as bob; rc=$?
[ $rc = 0 ] && grep -qi "takeover" "$T/e" && grep -qi "alice" "$T/e" && ok "check on a stale lead: exit 0 and a stderr warning about takeover" || no "SPEC stale check: rc=$rc $(out)"

# --- check
M $t0 check f2 --as bob; rc=$?
[ $rc = 0 ] && grep -qi free "$T/o" && ok "check: an unled feature is 'free'" || no "SPEC check free: rc=$rc $(out)"
M $((t0 + 1)) check f1 --as alice; rc=$?
[ $rc = 0 ] && grep -qi yours "$T/o" && ok "check: the lead gets 'yours'" || no "SPEC check yours: rc=$rc $(out)"
[ -s "$T/e" ] && no "SPEC check yours: warnings printed for the lead with no overlap: $(cat "$T/e")" || ok "check yours: stderr is quiet"
M $t0 check f2 --as bob; grep -qi "no lead" "$T/e" && ok "check: warns on stderr when there is no lead" || no "SPEC check no lead warning: $(out)"
M $((t0 + 2)) check; rc=$?
[ $rc = 0 ] && grep -q "f1" "$T/o" && grep -Eq "^f1 +lead=alice +active +ship the thing" "$T/o" && ok "check without NAME prints the brief status of all features, exit 0" || no "SPEC check (no name): rc=$rc $(out)"

# --- status
M $((t0 + 3)) status f1 --as bob; rc=$?
[ $rc = 0 ] && grep -q alice "$T/o" && grep -qi live "$T/o" && grep -q active "$T/o" && grep -q "ship the thing" "$T/o" && ok "status: lead id, live, status, goal" || no "SPEC status NAME: rc=$rc $(out)"
M $((t0 + TTL)) status f1 --brief; grep -Eq "^f1 +lead=stale\(alice\) +active +ship the thing" "$T/o" && ok "status --brief: 'NAME  lead=stale(ID)  status  goal'" || no "SPEC brief stale: $(out)"
M $t0 status f2 --brief; grep -Eq "^f2 +lead=none +" "$T/o" && ok "status --brief: lead=none" || no "SPEC brief none: $(out)"
M $((t0 + 3)) status --all --brief
n=0; for f in f1 f2 f3 f5 f6 f7 f8 f9 old ov1 ov2; do grep -Eq "^$f +lead=" "$T/o" && n=$((n + 1)); done
[ $n = 11 ] && ok "status --all lists every open feature, one line each" || no "SPEC status --all: $n of 11 features listed: $(out)"
M $t0 status f1 --json; jq -e . "$T/o" >/dev/null 2>&1 && grep -q alice "$T/o" && grep -q "ship the thing" "$T/o" && ok "status --json is valid JSON with the same data" || no "SPEC --json: $(out)"
M $t0 status --all --json; jq -e . "$T/o" >/dev/null 2>&1 && grep -q '"f2"\|f2' "$T/o" && ok "status --all --json is valid JSON" || no "SPEC --all --json: $(out)"
# derived: tasks (local runs on base feature/NAME), unmerged agent branches, overlap with another open feature
printf '%s\n' '{"run":"r1","slug":"derivedtask","base":"feature/f1","branch":"agent/derivedtask"}' '{"run":"r2","slug":"othertask","base":"feature/f2","branch":"agent/othertask"}' > "$S/local-runs.jsonl"
git -C "$R" update-ref refs/heads/agent/derivedtask "$(git -C "$R" commit-tree -p feature/f1 -m "task work" "feature/f1^{tree}")"   # one commit the feature lacks: unmerged
M $t0 status f1 --as alice
grep -q derivedtask "$T/o" && ! grep -q othertask "$T/o" && ok "status: derived tasks are the local runs whose base is feature/NAME" || no "SPEC derived tasks: $(out)"
grep -q "agent/derivedtask" "$T/o" && ok "status: lists unmerged agent/* branches" || no "SPEC agent branches: $(out)"
M $t0 status ov1 --as alice; grep -q "shared.txt" "$T/o" && grep -q ov2 "$T/o" && ok "status: overlapping files with another open feature" || no "SPEC overlap: $(out)"
M $t0 claim ov1 --as alice; M $t0 check ov1 --as alice; rc=$?
[ $rc = 0 ] && grep -q shared.txt "$T/e" && ok "check: file overlap is a warning on stderr, exit 0" || no "SPEC overlap warning: rc=$rc $(out)"
git -C "$R" worktree add -q "$T/wt-f1" feature/f1; M $t0 status f1 --as alice; grep -q "$T/wt-f1" "$T/o" && ok "status: lists worktrees" || no "SPEC worktrees: $(out)"
git -C "$R" worktree remove --force "$T/wt-f1"
# ghost: a record whose branch is gone, and an old record without the new keys
jq -n '{feature:"ghost", project:"app", status:"active", rev:1, lead:null}' > "$(rec ghost)"
M $t0 status --all; grep -q ghost "$T/o" && grep -q "branch gone" "$T/o" && grep -q abandoned "$T/o" && ok "status --all: a record without a branch is a ghost (abandoned, 'branch gone')" || no "SPEC ghost: $(out)"
jq -n '{purpose:"legacy", started:"2026-01-01T00:00:00Z"}' > "$(rec old)"
M $t0 status old --brief; grep -Eq "^old +lead=none" "$T/o" && ok "an old record without the new keys reads as unled" || no "SPEC old record: $(out)"
M $t0 claim old --as alice && [ "$(j old .lead.id)" = alice ] && [ "$(j old .purpose)" = legacy ] && ok "an old record can be claimed and keeps its purpose" || no "SPEC old record claim: $(out) $(cat "$(rec old)")"

# --- set: only the lead; renews the lease
M $((t0 + 100)) set f1 --as bob --goal hijack; [ $? = 1 ] && [ "$(j f1 .goal)" = "ship the thing" ] && ok "set: not the lead exits 1 and changes nothing" || no "SPEC set by non-lead: $(out)"
r0=$(j f1 .renewed_at); rev0=$(j f1 .rev)
M $((t0 + 800)) set f1 --as alice --plan "1. a 2. b" --note "mind the cache" --status blocked; rc=$?
[ $rc = 0 ] && [ "$(j f1 .plan)" = "1. a 2. b" ] && [ "$(j f1 .note)" = "mind the cache" ] && [ "$(j f1 .status)" = blocked ] && ok "set: the lead sets plan, note and status" || no "SPEC set: rc=$rc $(out) $(cat "$(rec f1)")"
[ "$(j f1 .rev)" -gt "$rev0" ] && [ "$(j f1 .renewed_at)" != "$r0" ] && ok "set: rev goes up and the lease is renewed" || no "SPEC set renews: rev $rev0 -> $(j f1 .rev), renewed_at $r0 -> $(j f1 .renewed_at)"
M $((t0 + 800 + TTL - 1)) check f1 --as bob; [ $? = 1 ] && ok "set renewed the lease: live well after the original ttl" || no "SPEC renew by set: $(out)"
M $((t0 + 801)) set f1 --as alice --status bogus; [ $? != 0 ] && ok "set: an unknown status is refused" || no "SPEC set status values are planned|active|blocked|verifying"

# --- renew
M $((t0 + 900)) renew f1 --as bob; [ $? = 1 ] && ok "renew: only the lead" || no "SPEC renew by non-lead: $(out)"
M $((t0 + 900)) renew f1 --as alice; rc=$?
M $((t0 + 900 + TTL - 1)) check f1 --as bob; rc2=$?
[ $rc = 0 ] && [ $rc2 = 1 ] && ok "renew: the lead renews, the lease runs from then" || no "SPEC renew: rc=$rc then check rc=$rc2 $(out)"

# --- release, take
M $((t0 + 1000)) release f1 --as bob --note x; [ $? = 1 ] && ok "release: not the lead exits 1" || no "SPEC release by non-lead"
M $((t0 + 1000)) release f1 --as alice; [ $? = 1 ] && ok "release: the note is required" || no "SPEC release needs --note"
M $((t0 + 1000)) release f1 --as alice --note ""; [ $? = 1 ] && [ "$(j f1 .lead.id)" = alice ] && ok "release: an empty note is refused" || no "SPEC release empty note"
M $((t0 + 1000)) release f1 --as alice --note "left off at step 2"; rc=$?
[ $rc = 0 ] && [ "$(j f1 .lead)" = null ] && [ "$(j f1 .status)" = released ] && [ "$(j f1 .note)" = "left off at step 2" ] && ok "release: lead null, status released, handoff note kept" || no "SPEC release: rc=$rc $(out) $(cat "$(rec f1)")"
M $((t0 + 1001)) status f1 --brief; grep -Eq "^f1 +lead=none +released" "$T/o" && ok "status --brief of a released feature" || no "SPEC brief released: $(out)"
M $((t0 + 1002)) take f1 --as bob; rc=$?
[ $rc = 0 ] && [ "$(j f1 .lead.id)" = bob ] && ok "take: a released feature goes to the taker" || no "SPEC take: rc=$rc $(out)"
M $((t0 + 1003)) take f1 --as carol; [ $? = 1 ] && [ "$(j f1 .lead.id)" = bob ] && ok "take: refused while another lead holds the feature" || no "SPEC take of a led feature must exit 1"
# two simultaneous takers: exactly one wins and rev advances once
M $((t0 + 1010)) release f1 --as bob --note "again"
rev0=$(j f1 .rev)
QARGI_MARSHAL_NOW=$((t0 + 1020)) "$DA" marshal take f1 --as carol >/dev/null 2>&1 & p1=$!
QARGI_MARSHAL_NOW=$((t0 + 1020)) "$DA" marshal take f1 --as dave >/dev/null 2>&1 & p2=$!
wait $p1; r1=$?; wait $p2; r2=$?
if [ $((r1 + r2)) = 1 ] && { [ $r1 = 0 ] || [ $r2 = 0 ]; }; then ok "take: of two simultaneous takers exactly one exits 0 and the other 1"; else no "SPEC take race: exit codes $r1 and $r2 (want one 0 and one 1)"; fi
[ "$(j f1 .rev)" = $((rev0 + 1)) ] && ok "take race: rev advanced once" || no "SPEC take race: rev $rev0 -> $(j f1 .rev), want +1"
case $(j f1 .lead.id) in carol|dave) ok "take race: the record names the winner";; *) no "SPEC take race: lead is $(j f1 .lead.id)";; esac
W=$(j f1 .lead.id)

# --- takeover
tk=$((t0 + 1020))
M $((tk + 10)) takeover f1 --as bob --approved "the lead is gone"; rc=$?
[ $rc = 1 ] && grep -qi live <(out) && [ "$(j f1 .lead.id)" = "$W" ] && ok "takeover: a LIVE lead exits 1 and says 'live'" || no "SPEC takeover live: rc=$rc $(out)"
M $((tk + TTL)) takeover f1 --as bob; [ $? != 0 ] && [ "$(j f1 .lead.id)" = "$W" ] && ok "takeover: needs --approved" || no "SPEC takeover without words"
M $((tk + TTL)) takeover f1 --as bob --approved ""; [ $? != 0 ] && [ "$(j f1 .lead.id)" = "$W" ] && ok "takeover: empty words are refused" || no "SPEC takeover empty words"
M $((tk + TTL)) takeover f1 --as bob --approved "$W went home, I own f1"; rc=$?
[ $rc = 0 ] && [ "$(j f1 .lead.id)" = bob ] && ok "takeover: a STALE lead is replaced" || no "SPEC takeover stale: rc=$rc $(out)"
grep -q "$W went home, I own f1" "$AUDIT" 2>/dev/null && grep -q bob "$AUDIT" && ok "takeover: the audit log holds the words and both lead ids" || no "SPEC takeover audit ($AUDIT): $(cat "$AUDIT" 2>&1)"
M $t0 takeover f2 --as bob --approved "no lead there"; rc=$?
[ $rc = 0 ] && [ "$(j f2 .lead.id)" = bob ] && ok "takeover: a feature with no lead may be taken over" || no "SPEC takeover no lead: rc=$rc $(out)"

# --- finish
M $((tk + TTL + 1)) finish f1 --as eve; [ $? = 1 ] && [ "$(j f1 .status)" != finished ] && ok "finish: another LIVE lead exits 1" || no "SPEC finish by non-lead: $(out)"
M $((tk + TTL + 5)) finish f1 --as bob; rc=$?
[ $rc = 0 ] && [ "$(j f1 .status)" = finished ] && [ "$(j f1 .lead)" = null ] && [ "$(j f1 .finished_at)" != null ] && ok "finish: status finished, finished_at set, lead null" || no "SPEC finish: rc=$rc $(out) $(cat "$(rec f1)")"
M $t0 finish f9 --as zed; rc=$?
[ $rc = 0 ] && [ "$(j f9 .status)" = finished ] && ok "finish: a feature with no lead can be finished by anyone" || no "SPEC finish no lead: rc=$rc $(out)"

# --- identity: --as, QARGI_LEAD, anonymous user@host
QARGI_LEAD=sess-9 QARGI_MARSHAL_NOW=$t0 "$DA" marshal claim f3 >"$T/o" 2>"$T/e"; rc=$?
[ $rc = 0 ] && [ "$(j f3 .lead.id)" = sess-9 ] && ok "identity: QARGI_LEAD is used" || no "SPEC identity QARGI_LEAD: rc=$rc $(out) $(cat "$(rec f3)")"
QARGI_LEAD=sess-9 QARGI_MARSHAL_NOW=$t0 "$DA" marshal renew f3 --as other >"$T/o" 2>&1; [ $? = 1 ] && ok "identity: --as overrides QARGI_LEAD" || no "SPEC --as must override QARGI_LEAD (other is not the lead)"
QARGI_LEAD=sess-9 QARGI_MARSHAL_NOW=$t0 "$DA" marshal renew f3 >"$T/o" 2>&1 && ok "identity: QARGI_LEAD renews its own lease" || no "SPEC QARGI_LEAD renew: $(cat "$T/o")"
QARGI_MARSHAL_NOW=$t0 "$DA" marshal claim f5 >"$T/o" 2>"$T/e"; rc=$?
id=$(j f5 .lead.id)
[ $rc = 0 ] && [[ $id == *@* ]] && [ -s "$T/e" ] && ok "identity: anonymous is user@host, warns on stderr, never refuses" || no "SPEC anonymous: rc=$rc id=$id stderr=$(cat "$T/e")"
QARGI_MARSHAL_NOW=$t0 "$DA" marshal check f5 >"$T/o" 2>"$T/e"; rc=$?
[ $rc = 0 ] && grep -qi yours "$T/o" && [ -s "$T/e" ] && ok "identity: check as the anonymous lead is 'yours' with a stderr warning" || no "SPEC anonymous check: rc=$rc $(out)"

# --- marshal.ttl changes the live/stale boundary
ttl 90
M $t0 claim f6 --as alice
M $((t0 + 60 * 60)) check f6 --as bob; [ $? = 1 ] && ok "marshal.ttl 90: still LIVE after 60 minutes" || no "SPEC ttl 90: live at 60 min (default 15 would be stale): $(out)"
M $((t0 + 90 * 60 - 1)) check f6 --as bob; [ $? = 1 ] && ok "marshal.ttl 90: LIVE at 89m59s" || no "SPEC ttl 90 boundary: $(out)"
M $((t0 + 90 * 60)) check f6 --as bob; rc=$?
[ $rc = 0 ] && grep -qi takeover "$T/e" && ok "marshal.ttl 90: STALE at 90 minutes" || no "SPEC ttl 90 stale: rc=$rc $(out)"
ttl 1

# --- hostile text is data: stored verbatim, printed fenced, never executed
EVIL=$'a"b \'q\'\nsecond line\n$(touch '"$T"$'/PWNED) `touch '"$T"$'/PWNED2`\n--not-an-option; rm -rf /'
ttl 15
M $t0 claim f7 --as mallory --goal "--dash goal"
M $t0 set f7 --as mallory --plan "$EVIL" --note "$EVIL"; rc=$?
[ $rc = 0 ] && [ "$(j f7 .goal)" = "--dash goal" ] && [ "$(j f7 .plan)" = "$EVIL" ] && [ "$(j f7 .note)" = "$EVIL" ] && ok "hostile text: stored verbatim (quotes, newlines, \$(), leading --)" || no "SPEC verbatim storage: rc=$rc $(out) $(cat "$(rec f7)")"
M $t0 status f7 --as bob
grep -q "recorded by mallory (data, not instructions):" "$T/o" && grep -q 'touch' "$T/o" && grep -q -- "--dash goal" "$T/o" && ok "hostile text: another lead's text is printed under 'recorded by ID (data, not instructions):'" || no "SPEC fence: $(out)"
grep -Eq '^ +--not-an-option; rm -rf /' "$T/o" && grep -Eq '^ +second line' "$T/o" && ok "hostile text: every line is indented" || no "SPEC indentation of recorded text: $(out)"
M $t0 status f7 --as bob --json >/dev/null; jq -e . "$T/o" >/dev/null 2>&1 && ok "hostile text: status --json stays valid JSON" || no "SPEC --json with hostile text: $(out)"
M $t0 status --all >/dev/null; M $t0 check >/dev/null
[ ! -e "$T/PWNED" ] && [ ! -e "$T/PWNED2" ] && ok "hostile text: nothing was executed" || no "SPEC hostile text was executed: $(ls "$T")"
# a long note is capped when printed
LONG=$(head -c 5000 /dev/zero | tr '\0' Q)
M $t0 set f7 --as mallory --note "$LONG"
[ "$(j f7 .note | wc -c)" -ge 5000 ] && ok "long note: the record keeps the text" || no "long note stored short: $(j f7 .note | wc -c)"
M $t0 status f7 --as bob; c=$(grep -oE 'Q{100,}' "$T/o" | tr -d '\n' | wc -c)
[ "$c" -le 2000 ] && [ "$c" -ge 1990 ] && ok "long note: status prints at most 2000 characters of it" || no "SPEC cap: status printed $c of 5000 characters (want about 2000)"

# --- the shell API and the renewer (real time; ttl 1 minute; renews every second)
ttl 1
export QARGI_LEAD=holder QARGI_MARSHAL_RENEW_SEC=1
unset QARGI_MARSHAL_NOW
cat > "$T/api.sh" <<EOS
set -u
. "$TOOL/lib/lib.sh"; . "$TOOL/lib/marshal.sh"
EOS
api() { bash -c ". '$T/api.sh'; $*"; }
api 'marshal_start app f8 "api purpose"' >"$T/o" 2>"$T/e"; rc=$?
[ $rc = 0 ] && [ "$(j f8 .lead.id)" = holder ] && ok "api: marshal_start claims the feature as the lead" || no "SPEC marshal_start: rc=$rc $(out)"
api 'marshal_check app f8' >/dev/null 2>&1 && ok "api: marshal_check passes for the lead" || no "SPEC marshal_check for the lead"
QARGI_LEAD=other api 'marshal_check app f8' >/dev/null 2>&1 && no "SPEC marshal_check: another LIVE lead must fail" || ok "api: marshal_check refuses when another LIVE lead holds it"
api 'marshal_finish app f8' >/dev/null 2>&1; [ "$(j f8 .status)" = finished ] && ok "api: marshal_finish finishes the feature" || no "SPEC marshal_finish: $(cat "$(rec f8)")"
# a holder: keeps the lease while running, prints nothing, stops with marshal_hold_stop
mkfifo "$T/ff"; exec 9<>"$T/ff"
M "$(date +%s)" claim f9 --as holder; M "$(date +%s)" release f9 --as holder --note n >/dev/null 2>&1
unset QARGI_MARSHAL_NOW
cat > "$T/holder.sh" <<EOS
. '$T/api.sh'
marshal_start app f9 "held" || exit 3
marshal_hold_start app f9 >"$T/hold.out" 2>&1
pgrep -P \$\$ | tr '\n' ' ' > "$T/hold.kids"
echo ready
read -r cmd <&9
[ "\$cmd" = stop ] && { marshal_hold_stop; pgrep -P \$\$ | tr '\n' ' ' > "$T/hold.kids2"; echo stopped; read -r _ <&9; }
EOS
bash "$T/holder.sh" >"$T/holder.log" 2>&1 & hp=$!
for _ in $(seq 1 50); do grep -q ready "$T/holder.log" 2>/dev/null && break; sleep 0.1; done
grep -q ready "$T/holder.log" || no "SPEC holder did not start: $(cat "$T/holder.log")"
[ ! -s "$T/hold.out" ] && ok "api: marshal_hold_start prints nothing" || no "SPEC hold_start output must be invisible: $(cat "$T/hold.out")"
kids=$(cat "$T/hold.kids" 2>/dev/null)
[ -n "$kids" ] && ok "api: marshal_hold_start runs a background renewer" || no "SPEC hold_start: no child process"
a=$(j f9 .renewed_at); sleep 3; b=$(j f9 .renewed_at)
[ "$a" != "$b" ] && ok "renewer: renewed_at advanced while the holder ran for 3 real seconds" || no "SPEC renewer: renewed_at stayed $a for 3 s with QARGI_MARSHAL_RENEW_SEC=1"
QARGI_LEAD=other "$DA" marshal check f9 >/dev/null 2>&1; [ $? = 1 ] && ok "renewer: the lead stays live with ttl 1 minute" || no "SPEC lead lost while held"
echo stop >&9
for _ in $(seq 1 50); do grep -q stopped "$T/holder.log" 2>/dev/null && break; sleep 0.1; done
alive=''; for k in $kids; do kill -0 "$k" 2>/dev/null && alive="$alive $k"; done
[ -z "$alive" ] && ok "api: marshal_hold_stop stops the renewer" || no "SPEC hold_stop: renewer still alive:$alive"
echo fin >&9; wait $hp 2>/dev/null
# a killed holder (kill -9) leaves no renewer behind
bash "$T/holder.sh" >"$T/holder.log" 2>&1 & hp=$!
for _ in $(seq 1 50); do grep -q ready "$T/holder.log" 2>/dev/null && break; sleep 0.1; done
kids=$(cat "$T/hold.kids" 2>/dev/null)
kill -9 "$hp"; wait "$hp" 2>/dev/null
gone=''; for _ in $(seq 1 30); do
  alive=''; for k in $kids; do kill -0 "$k" 2>/dev/null && alive="$alive $k"; done
  [ -z "$alive" ] && { gone=1; break; }; sleep 0.1
done
[ -n "$kids" ] && [ -n "$gone" ] && ok "renewer: exits within 3 s when its parent is killed (no orphan)" || no "SPEC renewer must exit when its parent is gone: kids='$kids' still alive:$alive"
exec 9>&-

[ "$fail" = 0 ] && echo "marshal: all passed" || echo "marshal: FAILED"
exit "$fail"
