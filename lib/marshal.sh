#!/usr/bin/env bash
# qargi marshal: who leads which open feature of a project (the verbs are described in lib/commands.py).
# The records and every decision live in lib/marshal_store.py (locked, compare-and-swap on rev); this file parses
# the command line, finds the project, reads the lease length and audits a takeover.
#
#   marshal.sh claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] ...
#   marshal.sh enable [--project P] [--plan TOKEN --approved WORDS]   switch this machine to the shared refs backend
#   marshal.sh disable [--project P]                                 switch back to the local records
#   marshal.sh enable --integrity off|advisory|strict [--project P] [--plan TOKEN --approved WORDS]   set how records are signed
#   marshal.sh key init [--principal P] [--plan TOKEN --approved WORDS]   make this machine's signing key
#   marshal.sh signers add --line L | remove P | list [--project P] [--plan TOKEN --approved WORDS]   who is trusted to sign
#   marshal.sh resign NAME [--project P] [--plan TOKEN --approved WORDS]   sign an unsigned open record
# enable without options prints the plan and a plan token; applying is --plan TOKEN --approved WORDS (audit line
# marshal:enable). The switch is the file $DA_STATE/marshal/PROJECT.enabled, written by marshal_refs.py, never a project
# answer (project set refuses marshal.* but marshal.ttl). enable and disable, like every verb that changes a record, are
# refused (exit 2) inside a member run. So are key, signers add|remove, enable --integrity and resign, which are owner verbs too:
# key init, signers add|remove and enable print a plan and a plan token first and apply with --plan TOKEN --approved WORDS (audit
# lines marshal:key-init, marshal:signers, marshal:enable); resign prints the head, the lead and the goal of the record it would sign and
# a plan token that covers them, and applies with --plan TOKEN --approved WORDS (marshal:resign). The signing key is the
# file $DA_CONF/credentials/marshal_ed25519 (mode 600, made by key init, never overwritten, never in an argument list, the audit log
# or the tracker); the trusted signers are the file $DA_STATE/marshal/PROJECT.signers; the mode is the field integrity of the
# switch file (default off). A member may read none of them (lib/guard.py). status and check take --no-fetch: read the cache of the remote refs only (the
# session hook uses it).
#
# The project answer marshal.ttl is the lease length in minutes (integer, default 15): qargi project set P marshal.ttl 20.
# The identity is --as ID, else $QARGI_LEAD, else user@host (anonymous: only ever warns).
# Tests inject the clock with QARGI_MARSHAL_NOW=<epoch seconds> (honoured by marshal_store.py only) and shorten the
# renewer's period with QARGI_MARSHAL_RENEW_SEC=<seconds>.
#
# Shell API for other scripts (source this file after lib.sh; each function takes the project name first, so it needs
# no project_load, and uses the identity above):
#   marshal_start PROJ NAME PURPOSE   create or refresh the record when a feature starts, the current identity leads it;
#                                     returns 1 and prints the refusal when another lead holds it
#   marshal_check PROJ NAME           returns 1 and prints the refusal when another LIVE lead holds NAME or when
#                                     NAME has neither a branch feature/NAME nor a record; warnings
#                                     (stale lead, anonymous identity, overlapping files, no lead) go to stderr; stdout stays empty
#   marshal_finish PROJ NAME          mark NAME finished (no record: nothing to do); returns 1 when another lead holds it
#   marshal_hold_start PROJ NAME      start a background renewer for a long verb: it renews the lease every ttl/3 minutes
#                                     (QARGI_MARSHAL_RENEW_SEC seconds when set), prints nothing, ends on marshal_hold_stop,
#                                     when the renewal is refused (not the lead any more) and when the calling shell is gone;
#                                     an unreachable remote ("remote not checked", exit 3) does not end it: it tries again
#   marshal_hold_stop                 stop the renewer (harmless when none runs)
# The renewer is a background subshell that polls its parent pid once a second, so it needs no trap in the calling script
# and never outlives it, whatever way the script ended.
MARSHAL_LIB=$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")
command -v die >/dev/null 2>&1 || . "$MARSHAL_LIB/lib.sh"

marshal_ttl() { # PROJ -> the lease length in minutes
  local t
  t=$(jq -r '.marshal.ttl // empty' "$DA_CONF/projects/$1.json" 2>/dev/null) || t=''
  case $t in ''|*[!0-9]*|0) t=15;; esac
  echo "$t"
}
marshal_repo() { # PROJ -> the repository path of the answers (REPO when the caller set it)
  local r=${REPO:-}
  [ -n "$r" ] || { r=$(jq -r '.repo.path // ""' "$DA_CONF/projects/$1.json" 2>/dev/null) || r=''; r=${r/#\~/$HOME}; }
  echo "$r"
}
marshal_py() { # PROJ VERB [args...]
  local proj=$1 verb=$2; shift 2
  python3 -I "$MARSHAL_LIB/marshal_store.py" "$verb" --state "$DA_STATE" --conf "$DA_CONF" --project "$proj" --repo "$(marshal_repo "$proj")" --ttl "$(marshal_ttl "$proj")" "$@"
}

marshal_start() { marshal_py "$1" start "$2" --purpose "${3:-}" >/dev/null; }
marshal_check() { marshal_py "$1" check "$2" >/dev/null; }
marshal_finish() { marshal_py "$1" finish "$2" --lenient >/dev/null; }

MARSHAL_HOLD_PID=''
marshal_hold_stop() {
  [ -z "$MARSHAL_HOLD_PID" ] || { kill "$MARSHAL_HOLD_PID" 2>/dev/null || true; wait "$MARSHAL_HOLD_PID" 2>/dev/null || true; }
  MARSHAL_HOLD_PID=''
}
marshal_hold_start() { # PROJ NAME
  local proj=$1 name=$2 parent=$$ period tick
  marshal_hold_stop
  period=${QARGI_MARSHAL_RENEW_SEC:-$(( $(marshal_ttl "$proj") * 60 / 3 ))}
  case $period in ''|*[!0-9]*|0) period=1;; esac
  (
    exec >/dev/null 2>&1 </dev/null
    sp=''
    trap '[ -z "$sp" ] || kill "$sp" 2>/dev/null; exit 0' TERM INT
    tick=0
    while kill -0 "$parent" 2>/dev/null; do
      sleep 1 & sp=$!
      wait "$sp" || true
      sp=''
      tick=$((tick + 1))
      if [ "$tick" -ge "$period" ]; then
        tick=0
        # stop when the renewal is refused (exit 1: another lead holds the feature) or cannot succeed (usage); exit 3 is "remote not
        # checked": the lease is not lost, try again next round
        rc=0; marshal_py "$proj" renew "$name" || rc=$?
        [ "$rc" -eq 3 ] || [ "$rc" -eq 0 ] || exit 0
      fi
    done
  ) &
  MARSHAL_HOLD_PID=$!
}

marshal_main() {
  set -eu
  # the options of this call are the only source of the approval and the plan token; a value inherited from the environment is not
  # (feature.sh and cred.sh do the same)
  APPROVED='' PLAN_ARG=''
  local verb=${1:-}; shift || true
  local usage="usage: qargi marshal claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] [--goal T] [--plan T] [--note T] [--status S] [--approved WORDS] [--all] [--history] [--brief] [--json] [--no-fetch]
       qargi marshal enable [--project P] [--integrity off|advisory|strict] [--plan TOKEN --approved WORDS] | disable [--project P]
       qargi marshal key init [--principal P] [--plan TOKEN --approved WORDS]
       qargi marshal signers add --line L | remove PRINCIPAL [--project P] [--plan TOKEN --approved WORDS] | list [--project P]
       qargi marshal resign NAME [--project P] [--plan TOKEN --approved WORDS]"
  local name='' PROJ='' as='' all='' brief='' json='' history='' nofetch='' want sub='' line='' principal='' integ=''
  local -a opt=()
  case $verb in
    key) sub=${1:-}; [ "$sub" = init ] || { echo "qargi: $usage" >&2; exit 2; }; shift;;
    signers) sub=${1:-}; case $sub in add|remove|list) shift;; *) echo "qargi: $usage" >&2; exit 2;; esac;;
  esac
  case $verb in
    enable|disable|key|resign) python3 -I "$MARSHAL_LIB/marshal_refs.py" member-check "$verb" || exit $?;;
    signers) [ "$sub" = list ] || python3 -I "$MARSHAL_LIB/marshal_refs.py" member-check "signers $sub" || exit $?;;
  esac
  case $verb in
    enable) want=' --project --plan --approved --integrity ';;
    key) want=' --principal --plan --approved ';;
    signers) want=' --project --line --plan --approved ';;
    resign) want=' --project --plan --approved ';;
    disable) want=' --project ';;
    claim) want=' --project --as --goal ';;
    status) want=' --project --as --all --history --brief --json --no-fetch ';;
    set) want=' --project --as --goal --plan --note --status ';;
    check) want=' --project --as --no-fetch ';;
    renew|take|finish) want=' --project --as ';;
    release) want=' --project --as --note ';;
    takeover) want=' --project --as --approved ';;
    *) echo "qargi: $usage" >&2; exit 2;;
  esac
  while [ $# -gt 0 ]; do
    case $1 in
      --all|--history|--brief|--json|--no-fetch)
        case $want in *" $1 "*) ;; *) echo "qargi: unknown option $1 for marshal $verb; $usage" >&2; exit 2;; esac
        case $1 in --all) all=1;; --history) history=1;; --brief) brief=1;; --json) json=1;; --no-fetch) nofetch=1;; esac; shift;;
      --*)
        case $want in *" $1 "*) ;; *) echo "qargi: unknown option $1 for marshal $verb; $usage" >&2; exit 2;; esac
        [ $# -ge 2 ] || { echo "qargi: $1 needs a value; $usage" >&2; exit 2; }
        case $1 in
          --project) PROJ=$2;;
          --as) as=$2;;
          --approved) APPROVED=$2; export APPROVED;;
          --line) line=$2;;
          --principal) principal=$2;;
          --integrity) integ=$2;;
          --plan) case $verb in enable|key|signers|resign) PLAN_ARG=$2; export PLAN_ARG;; *) opt+=("$1" "$2");; esac;;
          *) opt+=("$1" "$2");;
        esac
        shift 2;;
      -*) echo "qargi: unknown option $1; $usage" >&2; exit 2;;
      *) if [ -z "$name" ]; then name=$1; else echo "qargi: unexpected argument $1; $usage" >&2; exit 2; fi; shift;;
    esac
  done
  case $verb in
    status|check|enable|disable|key) ;;
    signers) case $sub in
        remove) [ -n "$name" ] || { echo "qargi: marshal signers remove needs the PRINCIPAL to drop; $usage" >&2; exit 2; };;
        *) [ -z "$name" ] || { echo "qargi: unexpected argument $name; $usage" >&2; exit 2; };;
      esac;;
    *) [ -n "$name" ] || { echo "qargi: marshal $verb needs a feature NAME; $usage" >&2; exit 2; };;
  esac
  [ -z "$integ" ] || case $integ in off|advisory|strict) ;; *) echo "qargi: --integrity is off, advisory or strict, not '$integ'" >&2; exit 2;; esac
  if [ "$verb" = signers ] && [ "$sub" = add ] && [ -z "$line" ]; then echo "qargi: marshal signers add needs --line L (one allowed signers line: PRINCIPAL namespaces=\"qargi-marshal\" ssh-ed25519 KEY)" >&2; exit 2; fi
  [ -z "$history" ] || [ -n "$all" ] || { echo "qargi: marshal status --history goes with --all" >&2; exit 2; }
  [ "$verb" != status ] || [ -z "$all" ] || [ -z "$name" ] || { echo "qargi: marshal status takes NAME or --all, not both" >&2; exit 2; }
  if [ "$verb" = key ]; then
    # the key belongs to this machine, not to a project
    local keyf=$DA_CONF/credentials/marshal_ed25519 ktok kline
    if [ -e "$keyf" ] || [ -L "$keyf" ]; then die "a signing key exists already ($keyf): it is never overwritten; to rotate, remove it yourself (and the .pub beside it), then run key init again"; fi
    ktok=$(printf 'marshal key init %s' "${principal:-default}" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      echo "would make this machine's signing key $keyf (ed25519, mode 600, no passphrase; it never leaves this machine) for the signer ${principal:-user@host}, and print the line the other machines trust for it"
      echo "plan token: $ktok   (apply with: qargi marshal key init${principal:+ --principal $principal} --plan $ktok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "key init needs --approved WORDS (the owner's words); run it without options for the plan"
    need_plan "$ktok"
    kline=$(python3 -I "$MARSHAL_LIB/marshal_sign.py" keygen --key "$keyf" ${principal:+--principal "$principal"}) || exit $?
    audit_log "marshal:key-init" "${kline%% *}"
    echo "made $keyf (mode 600); keep it on this machine"
    echo "trust this line on every machine that reads the records, each with: qargi marshal signers add --line '...'"
    echo "$kline"
    exit 0
  fi
  . "$MARSHAL_LIB/gitflow.sh"
  # shellcheck disable=SC2154  # REPO comes from project_load
  project_load
  [ -z "$as" ] || opt+=(--as "$as")
  [ -z "$name" ] || opt=("$name" "${opt[@]}")
  [ -z "$brief" ] || opt+=(--brief)
  [ -z "$json" ] || opt+=(--json)
  [ -z "$history" ] || opt+=(--history)
  [ -z "$nofetch" ] || opt+=(--no-fetch)
  if [ "$verb" = enable ]; then
    local remote=origin tok
    git -C "$(marshal_repo "$PROJ")" remote get-url "$remote" >/dev/null 2>&1 || die "the repository of $PROJ has no remote '$remote' to keep the shared refs on"
    tok=$(printf 'marshal enable %s %s%s' "$PROJ" "$remote" "${integ:+ integrity=$integ}" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      echo "would switch the marshal of $PROJ on this machine to the shared refs backend: the records live in refs/qargi/ on the remote $remote (claims, renewals and finishes are pushed there)${integ:+, with integrity $integ: off signs and checks nothing, advisory signs and shows whether each record is signed, strict ignores records that are not signed by a trusted key}"
      echo "plan token: $tok   (apply with: qargi marshal enable --project $PROJ${integ:+ --integrity $integ} --plan $tok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "enable needs --approved WORDS (the owner's words); run it without options for the plan"
    need_plan "$tok"
    python3 -I "$MARSHAL_LIB/marshal_refs.py" switch-write --state "$DA_STATE" --project "$PROJ" --remote "$remote" --words "$APPROVED" ${integ:+--integrity "$integ"} || exit $?
    audit_log "marshal:enable" "$PROJ $remote${integ:+ integrity=$integ}"
    echo "marshal of $PROJ: shared refs backend enabled (remote $remote)${integ:+, integrity $integ}"
    case $integ in
      advisory|strict)
        [ -e "$DA_CONF/credentials/marshal_ed25519" ] || echo "note: this machine has no signing key yet (qargi marshal key init); its records stay unsigned$([ "$integ" != strict ] || echo ' and strict refuses to write them')"
        [ -s "$DA_STATE/marshal/$PROJ.signers" ] || echo "note: no signer is trusted yet (qargi marshal signers add --line L): every signed record reads as INVALID";;
    esac
    exit 0
  fi
  if [ "$verb" = signers ]; then
    local sf=$DA_STATE/marshal/$PROJ.signers stok dry
    if [ "$sub" = list ]; then python3 -I "$MARSHAL_LIB/marshal_sign.py" signers list --file "$sf"; exit $?; fi
    if [ -L "$sf" ]; then die "$sf is a symlink: it is neither trusted nor written through"; fi
    stok=$(printf 'marshal signers %s %s %s' "$sub" "$PROJ" "${line:-$name}" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      if [ "$sub" = add ]; then
        # the line is checked against a copy of the file before a plan is printed for it
        dry=$(mktemp -d "$DA_STATE/.marshal-signers.XXXXXX")
        if [ -f "$sf" ]; then cp -- "$sf" "$dry/signers"; fi
        python3 -I "$MARSHAL_LIB/marshal_sign.py" signers add --file "$dry/signers" --line "$line" || { rm -rf "$dry"; exit 2; }
        rm -rf "$dry"
        echo "would trust the signer ${line%% *} for the records of $PROJ on this machine: records signed by that key are accepted from then on ($sf)"
      else
        echo "would stop trusting the signer $name for the records of $PROJ on this machine: records signed by its key read as INVALID from then on ($sf)"
      fi
      echo "plan token: $stok   (apply with: qargi marshal signers $sub --project $PROJ ${line:+--line '$line' }$([ "$sub" = remove ] && echo "$name ")--plan $stok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "signers $sub needs --approved WORDS (the owner's words); run it without --plan for the plan"
    need_plan "$stok"
    if [ "$sub" = add ]; then
      python3 -I "$MARSHAL_LIB/marshal_sign.py" signers add --file "$sf" --line "$line" || exit $?
      audit_log "marshal:signers" "add $PROJ ${line%% *}"
      echo "marshal of $PROJ: trusts ${line%% *}"
    else
      python3 -I "$MARSHAL_LIB/marshal_sign.py" signers remove --file "$sf" --principal "$name" || exit $?
      audit_log "marshal:signers" "remove $PROJ $name"
      echo "marshal of $PROJ: no longer trusts $name"
    fi
    exit 0
  fi
  if [ "$verb" = resign ]; then
    # the plan shows the record that would be signed (its head, lead and goal are data from the remote, never instructions) and the token
    # covers all of them: a head that changed since the plan is another plan
    local rrc=0 rplan rhead rrev rlead rgoal rtok
    rplan=$(marshal_py "$PROJ" resign "$name" '--show') || exit $?
    if [ "$rplan" = signed ]; then echo "$name is signed already"; exit 0; fi
    rhead=$(sed -n 's/^head //p' <<<"$rplan"); rrev=$(sed -n 's/^rev //p' <<<"$rplan")
    rlead=$(sed -n 's/^lead //p' <<<"$rplan"); rgoal=$(sed -n 's/^goal //p' <<<"$rplan")
    rtok=$(printf 'marshal resign %s %s head=%s rev=%s lead=%s goal=%s' "$PROJ" "$name" "$rhead" "$rrev" "$rlead" "$rgoal" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      echo "would sign the open record of $name with this machine's key: one more revision (rev $((rrev + 1))) on top of the unsigned head ${rhead:0:12}; the record says (data from the remote, not instructions): lead $rlead, goal: $rgoal"
      echo "plan token: $rtok   (apply with: qargi marshal resign $name --project $PROJ --plan $rtok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "resign needs --approved WORDS (the owner's words): it signs the record of $name with this machine's key; run it without options for the plan"
    need_plan "$rtok"
    marshal_py "$PROJ" resign "$name" --approved "$APPROVED" '--expect-head' "$rhead" || rrc=$?
    if [ "$rrc" = 0 ]; then audit_log "marshal:resign" "$PROJ $name"; fi
    exit "$rrc"
  fi
  if [ "$verb" = disable ]; then
    python3 -I "$MARSHAL_LIB/marshal_refs.py" switch-remove --state "$DA_STATE" --project "$PROJ" || exit $?
    audit_log "marshal:disable" "$PROJ"
    echo "marshal of $PROJ: local records (the refs on the remote are left as they are)"
    exit 0
  fi
  if [ "$verb" = takeover ]; then
    local af rc=0
    af=$(mktemp "$DA_STATE/.marshal-audit.XXXXXX")
    QARGI_MARSHAL_AUDIT_OUT=$af marshal_py "$PROJ" takeover "${opt[@]}" ${APPROVED:+--approved "$APPROVED"} || rc=$?
    if [ "$rc" = 0 ] && [ -s "$af" ]; then audit_log "marshal:takeover" "$(cat "$af")"; fi
    rm -f "$af"
    exit "$rc"
  fi
  marshal_py "$PROJ" "$verb" "${opt[@]}"
}

# executed, not sourced: dispatch the verbs
if [ "${BASH_SOURCE[0]}" = "$0" ]; then marshal_main "$@"; fi
