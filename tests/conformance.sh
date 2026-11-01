#!/usr/bin/env bash
# The conformance suite of a provider adapter: what every lib/providers/NAME/adapter must do, whatever the vendor.
#
# Usage: tests/conformance.sh NAME [--stub DIR] [--tool DIR]
#   NAME       the provider; its descriptor is lib/providers/NAME.json and `adapter` in it names the adapter. A descriptor
#              with adapter null is skipped with a message (exit 0).
#   --stub DIR the provider's test directory, default tests/providers/NAME. It holds `stub` (an executable that stands in
#              for the vendor, exported to the adapter as $QARGI_TRANSPORT; see tests/providers/lib/stub.py), fixtures/
#              (what the stub replays) and, for case 9, definition.json.
#   --tool DIR a tool root (a directory with lib/providers/) other than this checkout; the suite of a fixture uses it.
# Output: one line per case, `ok`, `FAIL` (with the problems indented below) or `skip` (with the reason). Exit 1 when any
# case fails, 2 on a usage error, else 0. Hermetic: HOME, QARGI_CONF and QARGI_STATE are temporary, the adapter's
# transport is the stub, nothing leaves the temporary directory. Needs bash, jq and python3.
#
# Cases (the request and the response of every verb are in lib/providers/adapter-schema.json):
#   1  every implemented verb answers in the schema (and a request that is not JSON is exit 1 or 3 with an error body)
#   2  resolve gives the descriptor's model and alias for every tier and listed surface and the provider's own effort; an
#      effort mapped to null gives effort_native null and a note
#   3  a verb tied to a capability that is effectively no (barrier-check: read_only_barrier; cost: session_budget_ceiling)
#      exits 3, and so does a surface the descriptor does not list
#   4  provision in plan mode makes only read-class transport calls
#   5  a credential sent to a verb is in no argv (the stub's log, and a process-list capture) and in no output
#   6  stop twice exits 0 both times
#   7  cost is in cents, or the amount is null
#   8  the barrier corpus (tests/providers/barrier-corpus.jsonl): every deny comes back deny, every allow allow, for each
#      surface whose read_only_barrier is not effectively no; a request the barrier cannot decide is never an allow
#   9  the definition dispatch-local returns for a read-only member carries the barrier the provider's definition.json
#      names, and the one for a write member does not carry what it says must be absent
# A case whose verb the adapter does not implement (exit 3) is skipped. A mutated copy of the tool tree (the descriptor
# changed, the adapter run from the copy) tests what the descriptor of the provider cannot show on its own: an effort
# with no control, a surface that is not listed. An adapter must therefore find its descriptor and what it needs relative
# to itself, as the adapter contract says.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$HERE")
usage() { echo "usage: tests/conformance.sh NAME [--stub DIR] [--tool DIR]" >&2; exit 2; }

NAME=""; STUBDIR=""; TOOL=$ROOT
while [ $# -gt 0 ]; do
  case $1 in
    --stub) [ $# -ge 2 ] || usage; STUBDIR=$2; shift 2;;
    --tool) [ $# -ge 2 ] || usage; TOOL=$2; shift 2;;
    -*) usage;;
    *) [ -z "$NAME" ] || usage; NAME=$1; shift;;
  esac
done
[ -n "$NAME" ] || usage
for t in jq python3; do command -v "$t" >/dev/null || { echo "conformance: $t is needed" >&2; exit 2; }; done
TOOL=$(cd "$TOOL" 2>/dev/null && pwd) || { echo "conformance: no such tool root" >&2; exit 2; }
[[ $NAME =~ ^[a-z][a-z0-9-]*$ ]] || { echo "conformance: '$NAME' is not a provider name" >&2; exit 2; }
PROV=$TOOL/lib/providers
DESC=$PROV/$NAME.json
[ -f "$DESC" ] || { echo "conformance: no descriptor $DESC" >&2; exit 2; }
jq -e . "$DESC" >/dev/null 2>&1 || { echo "conformance: $DESC is not JSON" >&2; exit 2; }
[ -n "$STUBDIR" ] || STUBDIR=$HERE/providers/$NAME
STUBDIR=$(cd "$STUBDIR" 2>/dev/null && pwd) || STUBDIR=$HERE/providers/$NAME
SCHEMA=$ROOT/lib/providers/adapter-schema.json
VALIDATE=$HERE/providers/lib/validate.py
CORPUS=$HERE/providers/barrier-corpus.jsonl

AD_REL=$(jq -r '.adapter // empty' "$DESC")
if [ -z "$AD_REL" ]; then
  echo "skip [-] $NAME has no adapter (adapter is null in its descriptor); nothing to check"
  exit 0
fi

# shellcheck source=hermetic.sh
. "$HERE/hermetic.sh"
W=$HERMETIC/work
mkdir -p "$W/cwd" "$W/proj"
cd "$W/cwd" || exit 2
ADAPTER=$TOOL/$AD_REL
STUB=$STUBDIR/stub
export QARGI_TRANSPORT=$STUB QARGI_STUB_LOG=$W/stub.log CONFORMANCE_TOOL=$TOOL
: > "$QARGI_STUB_LOG"

nok=0; nfail=0; nskip=0
PROB=(); NOTES=(); RAN=0; SKIPWHY=""
begin() { PROB=(); NOTES=(); RAN=0; SKIPWHY=""; }
problem() { PROB+=("$1"); }
note() { NOTES+=("$1"); }
ran() { RAN=1; }
nothing() { [ -n "$SKIPWHY" ] || SKIPWHY=$1; }
finish() {   # NUMBER TITLE
  local n=$1 title=$2 p extra=""
  if [ ${#PROB[@]} -gt 0 ]; then
    printf 'FAIL [%s] %s\n' "$n" "$title"; nfail=$((nfail + 1))
    for p in "${PROB[@]}"; do printf '       - %s\n' "$p"; done
  elif [ "$RAN" = 0 ]; then
    printf 'skip [%s] %s: %s\n' "$n" "$title" "${SKIPWHY:-nothing to check}"; nskip=$((nskip + 1))
  else
    [ ${#NOTES[@]} -eq 0 ] || extra=" ($(printf "%s; " "${NOTES[@]}" | sed "s/; \$//"))"
    printf 'ok   [%s] %s%s\n' "$n" "$title" "$extra"; nok=$((nok + 1))
  fi
}

# ---- helpers -----------------------------------------------------------------------------------------------------------
RC=0; OUT=""
call() {   # VERB REQUEST: runs the adapter; RC, OUT (its stdout)
  OUT=$(printf '%s' "$2" | "$ADAPTER" "$1" 2>"$W/stderr"); RC=$?
}
one_json() {   # OUT is exactly one JSON object on one line
  [ "$(printf '%s\n' "$OUT" | wc -l)" = 1 ] && jq -e 'type == "object"' <<<"$OUT" >/dev/null 2>&1
}
check_schema() {   # VERB KIND VALUE: the problems of the value against adapter-schema.json, one per line
  printf '%s' "$3" | python3 -I "$VALIDATE" --schema "$SCHEMA" "$1" "$2"
}
eff() { python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import provider as P; print(P.effective(sys.argv[2], sys.argv[3], sys.argv[4], root=sys.argv[5]))' "$ROOT/lib" "$NAME" "$1" "$2" "$PROV"; }
SURFACES=$(jq -r '.surfaces[]' "$DESC")
listed() { grep -qx "$1" <<<"$SURFACES"; }
VERBS="resolve dispatch-local barrier-check provision start-session status collect stop cost"
MODEL=$(jq -r '.tier_detail.balanced | .alias // .model' "$DESC")
SID=sess_conformance

sample() {   # VERB SURFACE: a good request for the verb
  case $1 in
    resolve) jq -nc --arg s "$2" '{surface: $s, tier: "balanced", effort: "high", profile: "conformance"}';;
    dispatch-local) jq -nc --arg m "$MODEL" --arg p "$W/proj" '{member: "conformance-member", abilities: ["build"], class: "write", model: $m, effort: "high", project_dir: $p}';;
    barrier-check) jq -nc --arg s "$2" --arg c "$W/run/clone" '{surface: $s, class: "read-only", tool_call: {tool: "Bash", command: "ls", cwd: $c}}';;
    provision) jq -nc '{surface: "cloud", project: "conformance", role: "build", mode: "plan"}';;
    start-session) jq -nc '{surface: "cloud", agent: "conformance-build", task: "conformance task", budget_cents: 100}';;
    status|collect|stop) jq -nc --arg i "$SID" '{surface: "cloud", session_id: $i}';;
    cost) jq -nc --arg s "$2" --arg i "$SID" '{surface: $s, session_id: $i}';;
  esac
}
surfaces_of() {   # VERB: the listed surfaces the verb is asked on
  case $1 in
    resolve|barrier-check|cost) echo "$SURFACES";;
    dispatch-local) listed local && echo local;;
    *) listed cloud && echo cloud;;
  esac
}
ONE=$(echo "$SURFACES" | head -1)

# a copy of the tool tree whose descriptor is changed by a jq filter; MUT is the adapter in the copy
MUT=""
mutate() {   # JQ-FILTER
  local d
  rm -rf "$W/mut"; mkdir -p "$W/mut"
  cp -R "$TOOL/lib" "$W/mut/lib" && { [ ! -d "$TOOL/agents" ] || cp -R "$TOOL/agents" "$W/mut/agents"; } || return 1
  d=$W/mut/lib/providers/$NAME.json
  jq "$1" "$DESC" > "$d.new" && mv "$d.new" "$d" || return 1
  MUT=$W/mut/$AD_REL
}
call_mut() { OUT=$(printf '%s' "$2" | "$MUT" "$1" 2>"$W/stderr"); RC=$?; }

# ---- 1: every implemented verb answers in the schema -----------------------------------------------------------------
case1() {
  begin
  local verb s req impl=() bad
  for verb in $VERBS; do
    for s in $(surfaces_of "$verb"); do
      req=$(sample "$verb" "$s")
      bad=$(check_schema "$verb" request "$req") || problem "internal: the sample request of $verb is not in the schema: $bad"
      call "$verb" "$req"; ran
      if [ "$RC" = 0 ]; then
        if ! one_json; then problem "$verb ($s): stdout is not one JSON object: ${OUT:0:200}"; continue; fi
        bad=$(check_schema "$verb" response "$OUT") || problem "$verb ($s): $(echo "$bad" | paste -sd';' -)"
        [[ " ${impl[*]:-} " == *" $verb "* ]] || impl+=("$verb")
      elif [ "$RC" = 3 ]; then
        one_json && bad=$(check_schema "$verb" error "$OUT") || problem "$verb ($s): exit 3 without an error body: ${OUT:0:200}"
      else
        problem "$verb ($s): exit $RC for a request the schema defines: ${OUT:0:200}"
      fi
    done
    call "$verb" "this is not JSON"
    if [ "$RC" != 1 ] && [ "$RC" != 3 ]; then problem "$verb: a request that is not JSON gave exit $RC, not 1 (or 3)"
    else one_json && bad=$(check_schema "$verb" error "$OUT") || problem "$verb: the error body of a bad request is not {error}: ${OUT:0:200}"; fi
  done
  [ ${#impl[@]} -gt 0 ] || problem "no verb is implemented"
  note "implemented: ${impl[*]:-none}"
  finish 1 "every implemented verb answers in adapter-schema.json"
}

# ---- 2: resolve ------------------------------------------------------------------------------------------------------
case2() {
  begin
  local s tier e want_model want_alias want_native req nulls
  for s in $SURFACES; do
    for tier in fast balanced deep frontier; do
      want_model=$(jq -r --arg t "$tier" '.tier_detail[$t].model' "$DESC"); want_alias=$(jq -r --arg t "$tier" '.tier_detail[$t].alias' "$DESC")
      req=$(jq -nc --arg s "$s" --arg t "$tier" '{surface: $s, tier: $t, effort: "high", profile: "conformance"}')
      call resolve "$req"; ran
      if [ "$RC" != 0 ]; then problem "resolve $s/$tier: exit $RC: ${OUT:0:200}"; continue; fi
      [ "$(jq -r .model <<<"$OUT")" = "$want_model" ] || problem "resolve $s/$tier: model $(jq -r .model <<<"$OUT"), the descriptor says $want_model"
      [ "$(jq -r .alias <<<"$OUT")" = "$want_alias" ] || problem "resolve $s/$tier: alias $(jq -r .alias <<<"$OUT"), the descriptor says $want_alias"
    done
  done
  nulls=$(jq -r '.effort | to_entries[] | select(.value == null) | .key' "$DESC")
  for e in low medium high xhigh max; do
    want_native=$(jq -r --arg e "$e" '.effort[$e] // "null"' "$DESC")
    call resolve "$(jq -nc --arg s "$ONE" --arg e "$e" '{surface: $s, tier: "balanced", effort: $e}')"
    [ "$RC" = 0 ] || { problem "resolve effort $e: exit $RC: ${OUT:0:200}"; continue; }
    [ "$(jq -r '.effort_native // "null"' <<<"$OUT")" = "$want_native" ] || problem "resolve effort $e: effort_native $(jq -c .effort_native <<<"$OUT"), the descriptor says $want_native"
    if [ "$want_native" = null ]; then
      [ "$(jq '.notes | length' <<<"$OUT")" -ge 1 ] || problem "resolve effort $e: no control for it, but no note"
    fi
  done
  call resolve "$(jq -nc --arg s "$ONE" '{surface: $s, tier: "balanced"}')"
  [ "$RC" = 0 ] && [ "$(jq -r '.effort_native' <<<"$OUT")" = null ] || problem "resolve with no effort asked: effort_native is not null (exit $RC)"
  if [ -z "$nulls" ]; then   # the descriptor maps every effort; change one in a copy to see the rule at work
    if mutate '.effort.max = null'; then
      call_mut resolve "$(jq -nc --arg s "$ONE" '{surface: $s, tier: "deep", effort: "max"}')"
      if [ "$RC" != 0 ]; then problem "resolve with an effort that has no control (a copy of the descriptor): exit $RC: ${OUT:0:200}"
      else
        [ "$(jq -r .effort_native <<<"$OUT")" = null ] || problem "an effort with no control: effort_native is not null"
        [ "$(jq '.notes | length' <<<"$OUT")" -ge 1 ] || problem "an effort with no control: no note"
        [ "$(jq -r .model <<<"$OUT")" = "$(jq -r .tier_detail.deep.model "$DESC")" ] || problem "an effort with no control changed the model"
        note "effort null rule on a changed copy"
      fi
    else problem "internal: could not make a changed copy of the tool tree"; fi
  fi
  finish 2 "resolve follows the descriptor"
}

# ---- 3: unsupported ------------------------------------------------------------------------------------------------
case3() {
  begin
  local row verb capname s x checked=0 req
  for row in "barrier-check read_only_barrier" "cost session_budget_ceiling"; do
    read -r verb capname <<<"$row"
    for s in $SURFACES; do
      [ "$(eff "$s" "$capname")" = no ] || continue
      req=$(sample "$verb" "$s"); call "$verb" "$req"; ran; checked=$((checked + 1))
      if [ "$RC" != 3 ]; then problem "$verb on $s: $capname is effectively no there, but the adapter exited $RC, not 3: ${OUT:0:160}"
      else one_json && [ -z "$(check_schema "$verb" error "$OUT")" ] || problem "$verb on $s: exit 3 without an error body"; fi
    done
  done
  for x in local cloud; do
    listed "$x" && continue
    call resolve "$(jq -nc --arg s "$x" '{surface: $s, tier: "fast"}')"; ran; checked=$((checked + 1))
    [ "$RC" = 3 ] || problem "resolve on the unlisted surface $x: exit $RC, not 3: ${OUT:0:160}"
  done
  if [ "$(echo "$SURFACES" | wc -l)" -gt 1 ]; then   # every surface is listed: take one away in a copy
    x=$(echo "$SURFACES" | tail -1)
    if mutate ".surfaces -= [\"$x\"] | del(.capabilities[][\"$x\"])"; then
      call_mut resolve "$(jq -nc --arg s "$x" '{surface: $s, tier: "fast"}')"; ran; checked=$((checked + 1))
      [ "$RC" = 3 ] || problem "resolve on a surface that a changed copy of the descriptor does not list ($x): exit $RC, not 3: ${OUT:0:160}"
      call_mut resolve "$(jq -nc --arg s "$ONE" '{surface: $s, tier: "fast"}')"
      [ "$RC" = 0 ] || problem "resolve on the surface that stays listed ($ONE) in the changed copy: exit $RC"
      note "an unlisted surface on a changed copy"
    else problem "internal: could not make a changed copy of the tool tree"; fi
  fi
  [ "$checked" -gt 0 ] || nothing "nothing is effectively no and every surface is listed"
  note "$checked checked"
  finish 3 "unsupported is exit 3"
}

# ---- 4: provision in plan mode makes no mutating call ------------------------------------------------------------------
case4() {
  begin
  if ! listed cloud; then nothing "the provider has no cloud surface"; finish 4 "provision in plan mode is read-only"; return; fi
  : > "$QARGI_STUB_LOG"
  call provision "$(sample provision cloud)"
  if [ "$RC" = 3 ]; then nothing "provision is not implemented (exit 3)"
  elif [ "$RC" != 0 ]; then ran; problem "provision in plan mode: exit $RC: ${OUT:0:200}"
  else
    ran
    [ "$(jq -r '.mode, .applied' <<<"$OUT" | paste -sd' ' -)" = "plan false" ] || problem "provision in plan mode did not answer mode plan, applied false: ${OUT:0:160}"
    local m t calls=0
    while IFS=$'\t' read -r m t; do
      calls=$((calls + 1))
      case $m in GET|HEAD|OPTIONS|LIST|SHOW|RETRIEVE|DESCRIBE|READ) ;; *) problem "provision in plan mode made a mutating transport call: $m $t";; esac
    done < <(jq -r '[(.argv[0] | ascii_upcase), (.argv[1] // "")] | @tsv' "$QARGI_STUB_LOG")
    note "$calls transport call(s), all read-class"
  fi
  finish 4 "provision in plan mode is read-only"
}

# ---- 5: a credential is in no argv -------------------------------------------------------------------------------------
SENT=SENTINEL-credential-$$-$RANDOM$RANDOM   # unique to this run: the process-list capture sees every process of the host, other runs' too
case5() {
  begin
  local verb req bad hits n=0 tried=""
  listed cloud || { nothing "the provider has no cloud surface"; finish 5 "credentials stay out of argv"; return; }
  printf '%s' "$SENT" > "$W/sentinel"
  for verb in $(jq -r '.verbs | to_entries[] | select(.value.request.properties.credentials != null) | .key' "$SCHEMA"); do
    req=$(sample "$verb" cloud | jq -c --arg c "$SENT" '. + {credentials: {api_key: $c, token: $c}}')
    bad=$(check_schema "$verb" request "$req") || problem "internal: the sample request of $verb with credentials is not in the schema: $bad"
    : > "$QARGI_STUB_LOG"; : > "$W/ps.hits"; : > "$W/polling"
    ( while [ -e "$W/polling" ]; do
        for f in /proc/[0-9]*/cmdline; do grep -qaF -f "$W/sentinel" "$f" 2>/dev/null && echo hit >> "$W/ps.hits"; done
        sleep 0.02
      done ) &
    poller=$!
    QARGI_STUB_DELAY=0.3 call "$verb" "$req"
    rm -f "$W/polling"; wait "$poller" 2>/dev/null
    if [ "$RC" = 3 ]; then continue; fi
    ran; n=$((n + 1)); tried="$tried $verb"
    [ "$RC" = 0 ] || problem "$verb with credentials: exit $RC: ${OUT:0:200}"
    hits=$(jq -r --arg c "$SENT" 'select(.argv | map(contains($c)) | any) | .argv | join(" ")' "$QARGI_STUB_LOG" | head -1)
    [ -z "$hits" ] || problem "$verb: the credential is in the transport's argv (the stub's log): ${hits//$SENT/<credential>}"
    [ ! -s "$W/ps.hits" ] || problem "$verb: the credential showed in the process list while the adapter ran"
    grep -qF -- "$SENT" <<<"$OUT" && problem "$verb: the credential is in the adapter's output"
    grep -qF -- "$SENT" "$W/stderr" && problem "$verb: the credential is in the adapter's stderr"
  done
  [ "$n" -gt 0 ] || nothing "no implemented verb takes credentials"
  [ "$n" -eq 0 ] || note "verbs:$tried"
  finish 5 "credentials stay out of argv"
}

# ---- 6: stop twice -----------------------------------------------------------------------------------------------------
case6() {
  begin
  local req rc1
  listed cloud || { nothing "the provider has no cloud surface"; finish 6 "stop twice exits 0"; return; }
  req=$(sample stop cloud)
  : > "$QARGI_STUB_LOG"
  call stop "$req"; rc1=$RC
  if [ "$rc1" = 3 ]; then nothing "stop is not implemented (exit 3)"
  else
    ran
    [ "$rc1" = 0 ] || problem "the first stop exited $rc1: ${OUT:0:160}"
    call stop "$req"
    [ "$RC" = 0 ] || problem "the second stop exited $RC, not 0: ${OUT:0:160}"
  fi
  finish 6 "stop twice exits 0"
}

# ---- 7: cost ----------------------------------------------------------------------------------------------------------
case7() {
  begin
  local s
  for s in $SURFACES; do
    call cost "$(sample cost "$s")"
    [ "$RC" != 3 ] || continue
    ran
    if [ "$RC" != 0 ]; then problem "cost on $s: exit $RC: ${OUT:0:160}"; continue; fi
    if ! jq -e '.amount == null or (.unit == "cents" and (.amount | type) == "number" and (.amount | floor) == .amount and .amount >= 0)' <<<"$OUT" >/dev/null 2>&1; then
      problem "cost on $s: the unit is not cents and the amount is not null: ${OUT:0:160}"
    fi
  done
  [ "$RAN" = 1 ] || nothing "cost is not implemented (exit 3 on every surface)"
  finish 7 "cost is in cents or null"
}

# ---- 8: the barrier corpus ---------------------------------------------------------------------------------------------
RUNDIR=$W/run
mkrun() {
  mkdir -p "$RUNDIR/clone/src" "$RUNDIR/out"
  : > "$RUNDIR/clone/src/a.go"; : > "$RUNDIR/refs.before"
  printf 'build\n' > "$RUNDIR/ability"; printf 'write\n' > "$RUNDIR/class"; printf 'build\n' > "$RUNDIR/profile"
}
subst() {   # strips the placeholders of the corpus from a JSON line on stdin
  jq -c --arg run "$RUNDIR" --arg clone "$RUNDIR/clone" --arg out "$RUNDIR/out" \
    'walk(if type == "string" then gsub("\\{RUN\\}"; $run) | gsub("\\{CLONE\\}"; $clone) | gsub("\\{OUT\\}"; $out) else . end)'
}
case8() {
  begin
  local eligible="" s line row req expect why n=0 d bad
  for s in $SURFACES; do [ "$(eff "$s" read_only_barrier)" = no ] || eligible="$eligible $s"; done
  if [ -z "$eligible" ]; then nothing "read_only_barrier is effectively no on every surface"; finish 8 "the barrier corpus"; return; fi
  [ -f "$CORPUS" ] || { ran; problem "no corpus at $CORPUS"; finish 8 "the barrier corpus"; return; }
  mkrun
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    row=$(subst <<<"$line")
    s=$(jq -r .surface <<<"$row")
    [[ " $eligible " == *" $s "* ]] || continue
    req=$(jq -c '{surface, class, tool_call}' <<<"$row"); expect=$(jq -r .expect <<<"$row"); why=$(jq -r .why <<<"$row")
    call barrier-check "$req"; ran; n=$((n + 1))
    d=$(jq -r '.decision // "none"' <<<"$OUT" 2>/dev/null)
    if [ "$RC" != 0 ]; then
      if [ "$expect" = deny ] && [ "$RC" = 2 ]; then continue; fi
      problem "expected $expect ($why), the barrier exited $RC: $(jq -c '.tool_call | del(.cwd)' <<<"$req") ${OUT:0:120}"
    elif [ "$d" != "$expect" ]; then
      problem "expected $expect, got $d ($why): $(jq -c '.class as $c | .tool_call | del(.cwd) | {class: $c} + .' <<<"$req")"
    elif [ "$d" = deny ] && [ -z "$(jq -r '.reason' <<<"$OUT")" ]; then
      problem "a deny with no reason ($why)"
    fi
  done < "$CORPUS"
  [ "$n" -gt 0 ] || problem "the corpus has no case for the surfaces$eligible"
  # fail closed: a request the barrier cannot decide is a refusal or a bad request, never an allow
  local bads=0 b
  while IFS= read -r b; do
    bads=$((bads + 1))
    call barrier-check "$(subst <<<"$b")" ; ran
    d=$(jq -r '.decision // "none"' <<<"$OUT" 2>/dev/null)
    if [ "$RC" = 0 ] && [ "$d" != deny ]; then problem "fail closed: a request the barrier cannot decide was answered '$d' (exit 0): $b"
    elif [ "$RC" != 0 ] && [ "$RC" != 1 ] && [ "$RC" != 2 ]; then problem "fail closed: a malformed request gave exit $RC: $b"; fi
  done <<'BADREQ'
{"surface":"local","class":"read-only","tool_call":"git push"}
{"surface":"local","class":"read-only","tool_call":{"tool":"Bash","command":7,"cwd":"{CLONE}"}}
{"surface":"local","class":"read-only","tool_call":{"tool":"Bash","cwd":"{CLONE}"}}
{"surface":"local","class":"root","tool_call":{"tool":"Bash","command":"git push","cwd":"{CLONE}"}}
{"surface":"local","tool_call":{"tool":"Bash","command":"git push","cwd":"{CLONE}"}}
{"surface":"local","class":"read-only","tool_call":{"command":"git push","cwd":"{CLONE}"}}
{"surface":"local","class":"read-only","tool_call":{"tool":"Bash","command":"git push","cwd":9}}
{}
BADREQ
  call barrier-check "not JSON at all"; ran
  { [ "$RC" = 1 ] || { [ "$RC" = 0 ] && [ "$(jq -r .decision <<<"$OUT" 2>/dev/null)" = deny ]; }; } || problem "fail closed: a request that is not JSON gave exit $RC"
  note "$n corpus calls on$eligible, $((bads + 1)) malformed"
  finish 8 "the barrier corpus"
}

# ---- 9: the definition carries the barrier -----------------------------------------------------------------------------
case9() {
  begin
  local exp=$STUBDIR/definition.json req text str title="the definition carries the barrier"
  if ! listed local; then nothing "the provider has no local surface"; finish 9 "$title"; return; fi
  if [ "$(eff local read_only_barrier)" = no ]; then nothing "read_only_barrier is effectively no on local"; finish 9 "$title"; return; fi
  [ -f "$exp" ] || { nothing "no definition.json in $STUBDIR"; finish 9 "$title"; return; }
  req=$(sample dispatch-local local | jq -c '. + {member: "conformance-ro", abilities: ["review"], class: "read-only"}')
  call dispatch-local "$req"
  if [ "$RC" = 3 ]; then nothing "dispatch-local is not implemented (exit 3)"; finish 9 "$title"; return; fi
  ran
  if [ "$RC" != 0 ]; then problem "dispatch-local for a read-only member: exit $RC: ${OUT:0:160}"
  else
    text=$(jq -r .definition.text <<<"$OUT")
    while IFS= read -r str; do [[ $text == *"$str"* ]] || problem "the definition of a read-only member lacks: $str"; done < <(jq -r '.["read-only"].contains // [] | .[]' "$exp")
    while IFS= read -r str; do [[ $text != *"$str"* ]] || problem "the definition of a read-only member carries: $str"; done < <(jq -r '.["read-only"].absent // [] | .[]' "$exp")
  fi
  call dispatch-local "$(sample dispatch-local local)"
  if [ "$RC" != 0 ]; then problem "dispatch-local for a write member: exit $RC: ${OUT:0:160}"
  else
    text=$(jq -r .definition.text <<<"$OUT")
    while IFS= read -r str; do [[ $text != *"$str"* ]] || problem "the definition of a write member carries: $str"; done < <(jq -r '.write.absent // [] | .[]' "$exp")
    while IFS= read -r str; do [[ $text == *"$str"* ]] || problem "the definition of a write member lacks: $str"; done < <(jq -r '.write.contains // [] | .[]' "$exp")
  fi
  finish 9 "$title"
}

echo "conformance: $NAME ($AD_REL)"
if [ ! -x "$ADAPTER" ]; then echo "FAIL [0] the adapter $AD_REL does not exist or is not executable"; exit 1; fi
if [ ! -x "$STUB" ]; then echo "FAIL [0] no stub transport at $STUB (an executable; see tests/providers/lib/stub.py)"; exit 1; fi
case1; case2; case3; case4; case5; case6; case7; case8; case9
echo "conformance: $NAME: $nok ok, $nfail FAIL, $nskip skip"
[ "$nfail" = 0 ]
