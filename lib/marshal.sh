#!/usr/bin/env bash
# qargi marshal: who leads which open feature of a project (the verbs are described in lib/commands.py).
# The records and every decision live in lib/marshal_store.py (locked, compare-and-swap on rev); this file parses
# the command line, finds the project, reads the lease length and audits a takeover.
#
#   marshal.sh claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] ...
#   marshal.sh enable [--project P] [--plan TOKEN --approved WORDS]   switch this machine to the shared refs backend
#   marshal.sh disable [--project P]                                 switch back to the local records
# enable without options prints the plan and a plan token; applying is --plan TOKEN --approved WORDS (audit line
# marshal:enable). The switch is the file $DA_STATE/marshal/PROJECT.enabled, written by marshal_refs.py, never a project
# answer (project set refuses marshal.* but marshal.ttl). enable and disable, like every verb that changes a record, are
# refused (exit 2) inside a member run. status and check take --no-fetch: read the cache of the remote refs only (the
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
  python3 -I "$MARSHAL_LIB/marshal_store.py" "$verb" --state "$DA_STATE" --project "$proj" --repo "$(marshal_repo "$proj")" --ttl "$(marshal_ttl "$proj")" "$@"
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
       qargi marshal enable [--project P] [--plan TOKEN --approved WORDS] | disable [--project P]"
  local name='' PROJ='' as='' all='' brief='' json='' history='' nofetch='' want
  local -a opt=()
  case $verb in
    enable|disable) python3 -I "$MARSHAL_LIB/marshal_refs.py" member-check "$verb" || exit $?;;
  esac
  case $verb in
    enable) want=' --project --plan --approved ';;
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
          --plan) if [ "$verb" = enable ]; then PLAN_ARG=$2; export PLAN_ARG; else opt+=("$1" "$2"); fi;;
          *) opt+=("$1" "$2");;
        esac
        shift 2;;
      -*) echo "qargi: unknown option $1; $usage" >&2; exit 2;;
      *) if [ -z "$name" ]; then name=$1; else echo "qargi: unexpected argument $1; $usage" >&2; exit 2; fi; shift;;
    esac
  done
  case $verb in
    status|check|enable|disable) ;;
    *) [ -n "$name" ] || { echo "qargi: marshal $verb needs a feature NAME; $usage" >&2; exit 2; };;
  esac
  [ -z "$history" ] || [ -n "$all" ] || { echo "qargi: marshal status --history goes with --all" >&2; exit 2; }
  [ "$verb" != status ] || [ -z "$all" ] || [ -z "$name" ] || { echo "qargi: marshal status takes NAME or --all, not both" >&2; exit 2; }
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
    tok=$(printf 'marshal enable %s %s' "$PROJ" "$remote" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      echo "would switch the marshal of $PROJ on this machine to the shared refs backend: the records live in refs/qargi/ on the remote $remote (claims, renewals and finishes are pushed there)"
      echo "plan token: $tok   (apply with: qargi marshal enable --project $PROJ --plan $tok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "enable needs --approved WORDS (the owner's words); run it without options for the plan"
    need_plan "$tok"
    python3 -I "$MARSHAL_LIB/marshal_refs.py" switch-write --state "$DA_STATE" --project "$PROJ" --remote "$remote" --words "$APPROVED" || exit $?
    audit_log "marshal:enable" "$PROJ $remote"
    echo "marshal of $PROJ: shared refs backend enabled (remote $remote)"
    exit 0
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
