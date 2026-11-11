#!/usr/bin/env bash
# The conformance suite of a provider adapter: what every lib/providers/NAME/adapter must do, whatever the vendor.
# It ships with the tool (lib/conformance/), because `qargi provider check` runs it on the adapter of a library pack; tests/conformance.sh
# is a wrapper that runs it for the shipped runtimes with the same arguments and the same output.
#
# Usage: lib/conformance/run.sh NAME [--stub DIR] [--tool DIR]      (tests/conformance.sh prints its own name in the usage line)
#   NAME       the provider (a runtime, for schema 2: claude-code, claude-platform); its descriptor is lib/providers/NAME.json
#              and `adapter` in it names the adapter. A schema 2 definition serves one surface and its models may live in a
#              catalog; the suite reads it through lib/provider.py summary() (surfaces, tier_detail, effort, adapter), so a
#              definition whose models are inline and one that references a catalog are checked the same way. A descriptor
#              with adapter null gets the command cases when it is a command runtime (dispatch.mode command) and is otherwise
#              skipped with a message (exit 0).
#   --stub DIR the provider's test directory, default tests/providers/NAME. It holds `stub` (an executable that stands in
#              for the vendor, exported to the adapter as $QARGI_TRANSPORT, and run by qargi local run in place of the command
#              of a command runtime; see tests/providers/lib/stub.py), fixtures/
#              (what the stub replays), for case 9 definition.json and, for a provider whose start-session builds the body of a
#              session request, start-session/worker.request.json (the request the sample of cases 1, 5 and 10 uses).
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
#   8  the barrier corpus (lib/conformance/barrier-corpus.jsonl): every deny comes back deny, every allow allow, for each
#      surface whose read_only_barrier is not effectively no; a request the barrier cannot decide is never an allow
#   9  the definition dispatch-local returns for a read-only member carries the barrier the provider's definition.json
#      names, and the one for a write member does not carry what it says must be absent
#  10  a start-session that builds the body of a session request (the response has an `agent`): the body has a model that is
#      an object {id, effort}, and no tools, skills or mcp_servers at any depth; a request that carries one of those keys, or
#      lacks a model, an effort or a system prompt, or has a system over 100000 characters, is exit 2 with an error body; a
#      read-only role is exit 2 where the barrier is effectively no, unless the request accepts that
# The command cases, for a runtime whose dispatch.mode is command (qargi local run, lib/local_run.py, starts the stub in place of
# the command argv[0] names, through a wrapper first on PATH that records the environment the command gets):
#  11  barrier sandbox-args: the argv of a read-only run carries the read-only arguments, sets their flags nowhere else and carries no
#      flag with its value of the write class's arguments, such as a writable directory (the case
#      barrier-sandbox-args of lib/conformance/cases.py, which `qargi provider check` runs on a library pack)
#  12  a write run, and a read-only one unless read_only_barrier is no (on a copy where its claim is dated when it is not yet verified),
#      start the stub once with the argv RUN/dispatch.json records and the prompt (task block and class) by the way prompt.via says;
#      each run carries the arguments of its class and none of the other's; OUT/transcript is what the stub printed; with
#      dispatch.output.usage, RUN/dispatch.json adds up a usage from it
#  13  the command gets HOME=RUN/home, no variable of the caller that env_pass does not name, and with dispatch.home its variable at
#      RUN/home/DIR with each link there while it runs (a file of the hermetic home holding a sentinel) and gone after; the sentinel
#      and the source paths are in no output, record or transcript, and the caller's home is unchanged
#  14  with dispatch.run_config.baseline, a write run and a read-only one (as in 12) each get the run's configuration file holding the
#      baseline and nothing else (no tool pack reaches a role in the hermetic home), read back in the format of resources.mcp, found by
#      the command in its run home while it runs (in: home), and recorded in RUN/dispatch.json; whether the runtime honours a key is live
# A case whose verb the adapter does not implement (exit 3) is skipped. A mutated copy of the tool tree (the descriptor
# changed, the adapter run from the copy) tests what the definition of the runtime cannot show on its own: an effort
# with no control (changed where the models live: the catalog the definition references, or the definition itself), a surface that
# is not listed (a definition serves one surface, and asking for the other is the case). An adapter must therefore find its
# definition and what it needs relative to itself, as the adapter contract says.
set -u
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$(dirname "$HERE")")
usage() { echo "usage: ${CONFORMANCE_PROG:-lib/conformance/run.sh} NAME [--stub DIR] [--tool DIR]" >&2; exit 2; }

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
TESTS=$ROOT/tests/providers   # where the shipped runtimes keep their stub and fixtures (not shipped: a library pack names its own with --stub)
[ -n "$STUBDIR" ] || STUBDIR=$TESTS/$NAME
STUBDIR=$(cd "$STUBDIR" 2>/dev/null && pwd) || STUBDIR=$TESTS/$NAME
SCHEMA=$ROOT/lib/providers/adapter-schema.json
VALIDATE=$HERE/validate.py
CORPUS=$HERE/barrier-corpus.jsonl

# shellcheck source=hermetic.sh
. "$HERE/hermetic.sh"
W=$HERMETIC/work
mkdir -p "$W/cwd" "$W/proj"
cd "$W/cwd" || exit 2
# the descriptor as summary() shows it, on the first surface it lists (see lib/provider.py)
VIEW=$W/view.json
python3 -I -c 'import json, sys; sys.path.insert(0, sys.argv[1]); import provider as P
try:
    print(json.dumps(P.summary(sys.argv[2], P.surfaces_of(sys.argv[2], root=sys.argv[3])[0], root=sys.argv[3])))
except P.ProviderError as e:
    sys.exit("conformance: %s" % e)' "$ROOT/lib" "$NAME" "$PROV" > "$VIEW" || exit 2
AD_REL=$(jq -r '.adapter // empty' "$VIEW")
MODE=$(jq -r '.dispatch.mode // empty | strings' "$DESC")
if [ -z "$AD_REL" ] && [ "$MODE" != command ]; then
  echo "skip [-] $NAME has no adapter (adapter is null in its descriptor) and is not a command runtime; nothing to check"
  exit 0
fi
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
SURFACES=$(jq -r '.surfaces[]' "$VIEW")
listed() { grep -qx "$1" <<<"$SURFACES"; }
VERBS="resolve dispatch-local barrier-check provision start-session status collect stop cost"
MODEL=$(jq -r '.tier_detail.balanced | .alias // .model' "$VIEW")
SID=sess_conformance

sample() {   # VERB SURFACE: a good request for the verb
  case $1 in
    resolve) jq -nc --arg s "$2" '{surface: $s, tier: "balanced", effort: "high", profile: "conformance"}';;
    dispatch-local) jq -nc --arg m "$MODEL" --arg p "$W/proj" '{member: "conformance-member", abilities: ["build"], class: "write", model: $m, effort: "high", project_dir: $p}';;
    barrier-check) jq -nc --arg s "$2" --arg c "$W/run/clone" '{surface: $s, class: "read-only", tool_call: {tool: "Bash", command: "ls", cwd: $c}}';;
    provision) jq -nc '{surface: "cloud", project: "conformance", role: "build", mode: "plan"}';;
    start-session)
      if [ -f "$STUBDIR/start-session/worker.request.json" ]; then jq -c . "$STUBDIR/start-session/worker.request.json"
      else jq -nc '{surface: "cloud", agent: "conformance-build", task: "conformance task", budget_cents: 100}'; fi;;
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

# a copy of the tool tree in which one file of lib/providers is changed by a jq filter; MUT is the adapter in the copy
MUT=""
mutate_file() {   # FILE-UNDER-lib/providers JQ-FILTER
  local d
  rm -rf "$W/mut"; mkdir -p "$W/mut"
  cp -R "$TOOL/lib" "$W/mut/lib" && { [ ! -d "$TOOL/agents" ] || cp -R "$TOOL/agents" "$W/mut/agents"; } || return 1
  d=$W/mut/lib/providers/$1
  jq "$2" "$TOOL/lib/providers/$1" > "$d.new" && mv "$d.new" "$d" || return 1
  MUT=$W/mut/$AD_REL
}
mutate() { mutate_file "$NAME.json" "$1"; }   # JQ-FILTER on the descriptor itself
mutate_effort_none() {   # LEVEL: that effort level has no control, in the file that holds the effort map
  local cat
  cat=$(jq -r '.models.catalog // empty' "$DESC")
  if [ -n "$cat" ]; then mutate_file "catalogs/$cat.json" ".effort.$1 = null"; else mutate ".models.effort.$1 = null"; fi
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
      want_model=$(jq -r --arg t "$tier" '.tier_detail[$t].model' "$VIEW"); want_alias=$(jq -r --arg t "$tier" '.tier_detail[$t].alias' "$VIEW")
      req=$(jq -nc --arg s "$s" --arg t "$tier" '{surface: $s, tier: $t, effort: "high", profile: "conformance"}')
      call resolve "$req"; ran
      if [ "$RC" != 0 ]; then problem "resolve $s/$tier: exit $RC: ${OUT:0:200}"; continue; fi
      [ "$(jq -r .model <<<"$OUT")" = "$want_model" ] || problem "resolve $s/$tier: model $(jq -r .model <<<"$OUT"), the descriptor says $want_model"
      [ "$(jq -r .alias <<<"$OUT")" = "$want_alias" ] || problem "resolve $s/$tier: alias $(jq -r .alias <<<"$OUT"), the descriptor says $want_alias"
    done
  done
  nulls=$(jq -r '.effort | to_entries[] | select(.value == null) | .key' "$VIEW")
  for e in low medium high xhigh max; do
    want_native=$(jq -r --arg e "$e" '.effort[$e] // "null"' "$VIEW")
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
    if mutate_effort_none max; then
      call_mut resolve "$(jq -nc --arg s "$ONE" '{surface: $s, tier: "deep", effort: "max"}')"
      if [ "$RC" != 0 ]; then problem "resolve with an effort that has no control (a copy of the descriptor): exit $RC: ${OUT:0:200}"
      else
        [ "$(jq -r .effort_native <<<"$OUT")" = null ] || problem "an effort with no control: effort_native is not null"
        [ "$(jq '.notes | length' <<<"$OUT")" -ge 1 ] || problem "an effort with no control: no note"
        [ "$(jq -r .model <<<"$OUT")" = "$(jq -r .tier_detail.deep.model "$VIEW")" ] || problem "an effort with no control changed the model"
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

# ---- 10: a session body never carries what the agent has fixed ---------------------------------------------------------
case10() {
  begin
  local title="a session body carries no tools, skills or mcp_servers" req k want
  if ! listed cloud; then nothing "the provider has no cloud surface"; finish 10 "$title"; return; fi
  req=$(sample start-session cloud)
  call start-session "$req"
  if [ "$RC" = 3 ]; then nothing "start-session is not implemented (exit 3)"; finish 10 "$title"; return; fi
  if [ "$RC" != 0 ] || ! one_json || [ "$(jq 'has("agent")' <<<"$OUT" 2>/dev/null)" != true ]; then
    nothing "start-session starts a session itself; there is no request body to check"; finish 10 "$title"; return
  fi
  ran
  jq -e '.agent.model | type == "object" and (.id | type == "string") and (.effort | type == "string")' <<<"$OUT" >/dev/null 2>&1 \
    || problem "the model of the session is not an object {id, effort}: $(jq -c .agent.model <<<"$OUT" | cut -c1-120)"
  jq -e '[.. | objects | keys[]] | any(. == "tools" or . == "skills" or . == "mcp_servers") | not' <<<"$OUT" >/dev/null 2>&1 \
    || problem "the body of the session carries tools, skills or mcp_servers"
  refuses() {   # LABEL JQ-FILTER: the sample request changed by the filter must be exit 2 with an error body
    call start-session "$(jq -c "$2" <<<"$req")"
    if [ "$RC" != 2 ]; then problem "$1: exit $RC, not 2: ${OUT:0:120}"
    elif ! one_json || [ -n "$(check_schema start-session error "$OUT")" ]; then problem "$1: exit 2 without an error body"
    elif [ ! -s "$W/stderr" ]; then problem "$1: refused without a message on stderr"; fi
  }
  for k in tools skills mcp_servers; do refuses "a request with $k" ". + {$k: []}"; done
  for k in model effort system; do refuses "a request without $k" "del(.$k)"; done
  refuses "a system over 100000 characters" '.system = ("x" * 100001)'
  call start-session "$(jq -c '.system = ("x" * 100000)' <<<"$req")"
  [ "$RC" = 0 ] || problem "a system of exactly 100000 characters: exit $RC: ${OUT:0:120}"
  if [ "$(eff cloud read_only_barrier)" = no ]; then
    refuses "a read-only role with no barrier and no acceptance" '.role = "reviewer" | .profile = "review" | del(.accept_no_barrier)'
    call start-session "$(jq -c '.role = "reviewer" | .profile = "review" | .accept_no_barrier = true' <<<"$req")"
    [ "$RC" = 0 ] || problem "a read-only role that accepts having no barrier: exit $RC: ${OUT:0:120}"
    want="read-only gate"
  else want="no gate (the barrier exists)"; fi
  note "$want"
  finish 10 "$title"
}

# ---- 11-13: a command runtime: qargi local run (lib/local_run.py) starts the stub in place of the command ------------------------
CMD0=$(jq -r '.dispatch.argv[0] // empty | strings' "$DESC")
HOMEENV=$(jq -r '.dispatch.home.env // empty | strings' "$DESC")
HOMEREL=$(jq -r '.dispatch.home.dir // empty | strings' "$DESC")
CFGIN=$(jq -r '.dispatch.run_config.in // empty | strings' "$DESC")
CFGFILE=$(jq -r '.dispatch.run_config.file // empty | strings' "$DESC")
CBIN=$W/cbin
CRUN=""; CRC=0; COUT=""
pycases() {   # PYTHON-CODE ARG...: the code with sys.argv[1] the lib of this suite (lib/conformance/cases.py is `cases`) and the descriptor as doc
  python3 -I -c 'import json, sys; sys.path.insert(0, sys.argv[1])
from conformance import cases
with open(sys.argv[2]) as f:
    doc = json.load(f)
'"$1" "$ROOT/lib" "$DESC" "${@:2}"
}
stub_ready() {   # the wrapper named argv[0] first on PATH: it records its environment and the links of the run home, then runs the stub
  [[ $CMD0 =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || return 1
  mkdir -p "$CBIN"
  { printf '#!/bin/sh\n'
    printf "env > '%s'\n" "$W/cmd.env"
    if [[ $HOMEENV =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
      printf 'd=$(printenv %s)\n' "$HOMEENV"
      printf "for f in \"\$d\"/* \"\$d\"/.[!.]*; do [ ! -L \"\$f\" ] || echo \"\${f##*/}\"; done > '%s'\n" "$W/cmd.home"
      if [ "$CFGIN" = home ] && [[ $CFGFILE =~ ^[A-Za-z0-9_][A-Za-z0-9._-]*$ ]]; then   # the run's configuration file as the command finds it
        printf "[ ! -f \"\$d/%s\" ] || cp \"\$d/%s\" '%s'\n" "$CFGFILE" "$CFGFILE" "$W/cmd.cfg"
      fi
    fi
    printf "QARGI_STUB_LOG='%s' exec '%s' \"\$@\"\n" "$W/cmd.log" "$STUB"
  } > "$CBIN/$CMD0" && chmod 755 "$CBIN/$CMD0"
  local from to rel
  while IFS=$'\t' read -r from to; do   # each source of the run home's links (~/PATH), a file of this run's home holding the sentinel
    rel=${from#\~/}
    { [ "$rel" != "$from" ] && [ -n "$rel" ] && [[ $rel != *..* ]]; } || continue
    mkdir -p "$(dirname "$HOME/$rel")" && printf '%s\n' "$SENT" > "$HOME/$rel"
  done < <(jq -r '.dispatch.home.link[]? | [(.from | strings), (.to | strings)] | @tsv' "$DESC")
}
cmdrun() {   # CLASS LIB: one run of LIB/local_run.py of the class with the stub in place of the command; CRUN (the run), CRC, COUT
  local cls=$1
  CRUN=$W/crun.$cls
  rm -rf "$CRUN"; mkdir -p "$CRUN/clone/src" "$CRUN/out"
  : > "$CRUN/refs.before"; : > "$CRUN/clone/src/a.go"
  if [ "$cls" = write ]; then printf 'build\n' > "$CRUN/ability"; else printf 'review\n' > "$CRUN/ability"; fi
  printf 'TASK: conformance task\nDONE: true\n' > "$CRUN/task.md"
  : > "$W/cmd.log"; rm -f "$W/cmd.env" "$W/cmd.home" "$W/cmd.cfg"
  COUT=$(CONFORMANCE_CALLER_SECRET=caller-$$ PATH="$CBIN:$PATH" python3 -I "$2/local_run.py" "$CRUN" --project conformance --runtime "$NAME" --class "$cls" 2>"$W/cmd.err"); CRC=$?
}
cmd_skip() {   # why case 12 or 13 cannot run, or nothing
  if ! listed local; then echo "the provider has no local surface"
  elif [[ ! $CMD0 =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then echo "dispatch.argv[0] is not a command looked up on PATH, so the stub cannot stand in for it"
  fi
}

case11() {
  begin
  local title="a read-only run carries the sandbox arguments" res
  if [ "$(jq -r '.barrier.kind // empty' "$DESC")" != sandbox-args ]; then nothing "the barrier kind is not sandbox-args"; finish 11 "$title"; return; fi
  ran
  res=$(pycases 'print(json.dumps(cases.barrier_sandbox_args(doc, None, sys.argv[3], False, False)["barrier-sandbox-args"]))' "$NAME") \
    || { problem "internal: the case barrier-sandbox-args of lib/conformance/cases.py did not run"; finish 11 "$title"; return; }
  case $(jq -r .status <<<"$res") in
    pass) note "$(jq -r '.notes | join("; ")' <<<"$res")";;
    *) problem "$(jq -r '.notes | join("; ")' <<<"$res")";;
  esac
  finish 11 "$title"
}

case12() {
  begin
  local title="a run of the stub gets the argv, the prompt and the output" why cls lib pf fx m bad runs="" usage=""
  why=$(cmd_skip)
  if [ -n "$why" ]; then nothing "$why"; finish 12 "$title"; return; fi
  stub_ready || { ran; problem "internal: could not put the stub in place of $CMD0"; finish 12 "$title"; return; }
  for cls in write read-only; do
    lib=$TOOL/lib
    if [ "$cls" = read-only ] && [ "$(eff local read_only_barrier)" = no ]; then
      if [ "$(jq -r '.capabilities.read_only_barrier.value // "no"' "$DESC")" = no ]; then note "no read-only run: read_only_barrier is no"; continue; fi
      # claimed and not yet verified: a copy where the claim is dated, as it is once verified (what a run carries is the case, not the claim)
      mutate ".capabilities.read_only_barrier.verified_on = \"$(date +%F)\"" || { ran; problem "internal: could not make a changed copy of the tool tree"; continue; }
      lib=$W/mut/lib
    fi
    cmdrun "$cls" "$lib"; ran
    if [ "$CRC" != 0 ]; then problem "$cls: qargi local run exited $CRC: $(tail -2 "$W/cmd.err" | paste -sd' ' - | cut -c1-200)"; continue; fi
    grep -qx 'OUTCOME=ok' <<<"$COUT" || problem "$cls: the outcome is not ok: $(grep '^OUTCOME=' <<<"$COUT")"
    if [ "$(grep -c . "$W/cmd.log")" != 1 ]; then problem "$cls: the stub was called $(grep -c . "$W/cmd.log") times, not once"; continue; fi
    [ "$(jq -c .argv "$W/cmd.log")" = "$(jq -c '.argv[1:]' "$CRUN/dispatch.json")" ] || problem "$cls: the stub got other arguments than RUN/dispatch.json records"
    pf=$(find "$CRUN/prompt" -maxdepth 1 -type f | head -1)
    { [ -n "$pf" ] && grep -q '^TASK: conformance task$' "$pf" && grep -qx "CLASS=$cls" "$pf"; } || problem "$cls: the prompt lacks the task block or the class qargi recorded"
    case $(jq -r .prompt_via "$CRUN/dispatch.json") in
      stdin) [ "$(jq -r .stdin "$W/cmd.log")" = "$(cat "$pf")" ] || problem "$cls: the stub's standard input is not the prompt";;
      file) jq -e --arg p "$pf" '.argv | index([$p])' "$W/cmd.log" >/dev/null || problem "$cls: the prompt file is not among the stub's arguments";;
      arg) jq -e --rawfile p "$pf" '.argv | any(. == $p)' "$W/cmd.log" >/dev/null || problem "$cls: the prompt is not among the stub's arguments";;
    esac
    bad=$(pycases '
argv = json.loads(open(sys.argv[3]).readline())["argv"]
cls = sys.argv[4]
other = "write" if cls == "read-only" else "read-only"
for g in cases.group_args(doc.get("dispatch") or {}, cls):
    if not cases.carries(argv, g):
        print("the %s run lacks its arguments %s" % (cls, " ".join(g)))
for g in cases.group_args(doc.get("dispatch") or {}, other):
    if cases.literal(g) and cases.carries(argv, g):
        print("the %s run carries the arguments of the %s class: %s" % (cls, other, " ".join(g)))' "$W/cmd.log" "$cls") || bad="internal: the class arguments could not be compared"
    [ -z "$bad" ] || while IFS= read -r m; do problem "$m"; done <<<"$bad"
    m=0; for fx in "$STUBDIR"/fixtures/*; do cmp -s "$fx" "$CRUN/out/transcript" && m=1; done
    [ "$m" = 1 ] || problem "$cls: OUT/transcript is not what the stub printed"
    if jq -e '.dispatch.output.usage | type == "object"' "$DESC" >/dev/null 2>&1; then
      if jq -e '.usage.events >= 1 and ([.usage.tokens[]] | add // 0) > 0' "$CRUN/dispatch.json" >/dev/null 2>&1; then usage="usage of $(jq -r .usage.events "$CRUN/dispatch.json") events"
      else problem "$cls: RUN/dispatch.json records no usage: dispatch.output.usage matches no line the stub printed ($(jq -c .usage "$CRUN/dispatch.json"))"; fi
    fi
    runs="$runs $cls"
  done
  [ -z "$runs" ] || note "runs:$runs"
  [ -z "$usage" ] || note "$usage"
  finish 12 "$title"
}

case13() {
  begin
  local title="the member's environment and run home" why f from to hd src s0 s1 links=""
  why=$(cmd_skip)
  if [ -n "$why" ]; then nothing "$why"; finish 13 "$title"; return; fi
  stub_ready || { ran; problem "internal: could not put the stub in place of $CMD0"; finish 13 "$title"; return; }
  s0=$(find "$HOME" -type f -exec sha256sum {} + | sort)
  cmdrun write "$TOOL/lib"; ran
  if [ "$CRC" != 0 ] || [ ! -s "$W/cmd.env" ]; then problem "qargi local run exited $CRC or the stub recorded no environment: $(tail -2 "$W/cmd.err" | paste -sd' ' - | cut -c1-200)"; finish 13 "$title"; return; fi
  if ! jq -e '.dispatch.env_pass // [] | index(["CONFORMANCE_CALLER_SECRET"])' "$DESC" >/dev/null 2>&1; then
    grep -q '^CONFORMANCE_CALLER_SECRET=' "$W/cmd.env" && problem "a variable of the caller that dispatch.env_pass does not name reached the command"
  fi
  grep -qx "HOME=$CRUN/home" "$W/cmd.env" || problem "HOME of the command is not the run's own home"
  for f in "$W/cmd.env" "$W/cmd.log" "$W/cmd.err" "$CRUN/dispatch.json" "$CRUN/out/transcript"; do
    grep -qF -- "$SENT" "$f" && problem "the content of a linked file is in ${f##*/}"
  done
  grep -qF -- "$SENT" <<<"$COUT" && problem "the content of a linked file is in the output of qargi local run"
  if [ -n "$HOMEENV" ]; then
    hd=$CRUN/home/$HOMEREL
    grep -qx "$HOMEENV=$hd" "$W/cmd.env" || problem "$HOMEENV is not RUN/home/$HOMEREL"
    while IFS=$'\t' read -r from to; do
      src=$HOME/${from#\~/}
      [ -f "$src" ] || continue
      links="$links $to"
      grep -qx -- "$to" "$W/cmd.home" 2>/dev/null || problem "$to was not a link in the run home while the command ran"
      { [ ! -e "$hd/$to" ] && [ ! -L "$hd/$to" ]; } || problem "$to is still in the run home after the run"
    done < <(jq -r '.dispatch.home.link[]? | [(.from | strings), (.to | strings)] | @tsv' "$DESC")
    grep -qF -- "$HOME/" <<<"$COUT" && problem "the output of qargi local run names a source path of the run home's links"
    grep -qF -- "$HOME/" "$CRUN/dispatch.json" && problem "RUN/dispatch.json names a source path of the run home's links"
    note "$HOMEENV=RUN/home/$HOMEREL; links:${links:- none}"
  else
    note "no run home"
  fi
  s1=$(find "$HOME" -type f -exec sha256sum {} + | sort)
  [ "$s0" = "$s1" ] || problem "the run changed a file of the caller's home"
  finish 13 "$title"
}

case14() {
  begin
  local title="every run's configuration file holds the baseline" why cls lib f got want fmt runs=""
  if [ "$(jq -r '.dispatch.run_config.baseline | type' "$DESC" 2>/dev/null)" != object ]; then nothing "dispatch.run_config has no baseline"; finish 14 "$title"; return; fi
  why=$(cmd_skip)
  if [ -n "$why" ]; then nothing "$why"; finish 14 "$title"; return; fi
  stub_ready || { ran; problem "internal: could not put the stub in place of $CMD0"; finish 14 "$title"; return; }
  want=$(jq -cS .dispatch.run_config.baseline "$DESC"); fmt=$(jq -r '.resources.mcp.format // "json"' "$DESC")
  for cls in write read-only; do
    lib=$TOOL/lib
    if [ "$cls" = read-only ] && [ "$(eff local read_only_barrier)" = no ]; then
      if [ "$(jq -r '.capabilities.read_only_barrier.value // "no"' "$DESC")" = no ]; then note "no read-only run: read_only_barrier is no"; continue; fi
      mutate ".capabilities.read_only_barrier.verified_on = \"$(date +%F)\"" || { ran; problem "internal: could not make a changed copy of the tool tree"; continue; }
      lib=$W/mut/lib
    fi
    cmdrun "$cls" "$lib"; ran
    if [ "$CRC" != 0 ]; then problem "$cls: qargi local run exited $CRC: $(tail -2 "$W/cmd.err" | paste -sd' ' - | cut -c1-200)"; continue; fi
    if [ "$CFGIN" = home ]; then f=$CRUN/home/$HOMEREL/$CFGFILE; else f=$CRUN/config/$CFGFILE; fi
    # no tool pack reaches a role in the hermetic home, so the file is the baseline and nothing else, in the format of resources.mcp
    if ! got=$(python3 -I -c 'import json, sys, tomllib
data = open(sys.argv[1], "rb").read()
print(json.dumps(tomllib.loads(data.decode()) if sys.argv[2] == "toml" else json.loads(data), sort_keys=True, separators=(",", ":")))' "$f" "$fmt" 2>/dev/null); then
      problem "$cls: the run's configuration file ${f#"$CRUN"/} is missing or cannot be read as $fmt"; continue
    fi
    [ "$got" = "$want" ] || problem "$cls: the run's configuration file is not the baseline alone: $(cut -c1-200 <<<"$got")"
    jq -e --argjson b "$want" '.run_config.baseline == $b' "$CRUN/dispatch.json" >/dev/null 2>&1 || problem "$cls: RUN/dispatch.json does not record the baseline (run_config.baseline)"
    if [ "$CFGIN" = home ] && ! cmp -s "$f" "$W/cmd.cfg"; then problem "$cls: the command did not find the file in its run home while it ran"; fi
    runs="$runs $cls"
  done
  [ -z "$runs" ] || note "runs:$runs; each got the baseline, $(jq -r 'keys | length' <<<"$want") top-level keys"
  finish 14 "$title"
}

echo "conformance: $NAME (${AD_REL:-no adapter}${MODE:+, dispatch $MODE})"
if [ -n "$AD_REL" ] && [ ! -x "$ADAPTER" ]; then echo "FAIL [0] the adapter $AD_REL does not exist or is not executable"; exit 1; fi
if [ ! -x "$STUB" ]; then echo "FAIL [0] no stub at $STUB (an executable; see tests/providers/lib/stub.py)"; exit 1; fi
if [ -n "$AD_REL" ]; then case1; case2; case3; case4; case5; case6; case7; case8; case9; case10
else echo "skip [-] the adapter cases 1 to 10: $NAME has no adapter (adapter is null in its descriptor)"; fi
if [ "$MODE" = command ]; then case11; case12; case13; case14
else echo "skip [-] the command cases 11 to 14: $NAME is not a command runtime (dispatch.mode is ${MODE:-not set})"; fi
echo "conformance: $NAME: $nok ok, $nfail FAIL, $nskip skip"
[ "$nfail" = 0 ]
