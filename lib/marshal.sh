#!/usr/bin/env bash
# qargi marshal: who leads which open feature of a project (the verbs are described in lib/commands.py).
# The records and every decision live in lib/marshal_store.py (locked, compare-and-swap on rev); this file parses
# the command line, finds the project, reads the lease length and audits a takeover.
#
#   marshal.sh claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] ...
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
#                                     when the renewal is refused (not the lead any more) and when the calling shell is gone
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
        marshal_py "$proj" renew "$name" || exit 0
      fi
    done
  ) &
  MARSHAL_HOLD_PID=$!
}

marshal_main() {
  set -eu
  local verb=${1:-}; shift || true
  local usage="usage: qargi marshal claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] [--goal T] [--plan T] [--note T] [--status S] [--approved WORDS] [--all] [--history] [--brief] [--json]"
  local name='' PROJ='' as='' all='' brief='' json='' history='' want
  local -a opt=()
  case $verb in
    claim) want=' --project --as --goal ';;
    status) want=' --project --as --all --history --brief --json ';;
    set) want=' --project --as --goal --plan --note --status ';;
    check|renew|take|finish) want=' --project --as ';;
    release) want=' --project --as --note ';;
    takeover) want=' --project --as --approved ';;
    *) echo "qargi: $usage" >&2; exit 2;;
  esac
  while [ $# -gt 0 ]; do
    case $1 in
      --all|--history|--brief|--json)
        case $want in *" $1 "*) ;; *) echo "qargi: unknown option $1 for marshal $verb; $usage" >&2; exit 2;; esac
        case $1 in --all) all=1;; --history) history=1;; --brief) brief=1;; --json) json=1;; esac; shift;;
      --*)
        case $want in *" $1 "*) ;; *) echo "qargi: unknown option $1 for marshal $verb; $usage" >&2; exit 2;; esac
        [ $# -ge 2 ] || { echo "qargi: $1 needs a value; $usage" >&2; exit 2; }
        case $1 in
          --project) PROJ=$2;;
          --as) as=$2;;
          --approved) APPROVED=$2; export APPROVED;;
          *) opt+=("$1" "$2");;
        esac
        shift 2;;
      -*) echo "qargi: unknown option $1; $usage" >&2; exit 2;;
      *) if [ -z "$name" ]; then name=$1; else echo "qargi: unexpected argument $1; $usage" >&2; exit 2; fi; shift;;
    esac
  done
  case $verb in
    status|check) ;;
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
  if [ "$verb" = takeover ]; then
    local af rc=0
    af=$(mktemp "$DA_STATE/.marshal-audit.XXXXXX")
    QARGI_MARSHAL_AUDIT_OUT=$af marshal_py "$PROJ" takeover "${opt[@]}" ${APPROVED+--approved "$APPROVED"} || rc=$?
    if [ "$rc" = 0 ] && [ -s "$af" ]; then audit_log "marshal:takeover" "$(cat "$af")"; fi
    rm -f "$af"
    exit "$rc"
  fi
  marshal_py "$PROJ" "$verb" "${opt[@]}"
}

# executed, not sourced: dispatch the verbs
if [ "${BASH_SOURCE[0]}" = "$0" ]; then marshal_main "$@"; fi
