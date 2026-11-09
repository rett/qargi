#!/usr/bin/env bash
# qargi marshal: who leads which open feature of a project (the verbs are described in lib/commands.py).
# The records and every decision live in lib/marshal_store.py (locked, compare-and-swap on rev); this file parses
# the command line, finds the project, reads the lease length and audits a takeover.
#
#   marshal.sh claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] ...
#   marshal.sh claim NAME --as-successor-of ID   continue as the lead after a restart: the record's lead is ID, its lease is stale, and its
#                                                host, OS user and work tree are this session's (refused otherwise; audited as marshal:succession).
#                                                marshal_start (feature start) does the same on its own; status and check name the command
#   marshal.sh handoff [NAME] [--project P] [--as ID] [--write FILE] [--json]   the note a fresh session starts from (read only, lib/marshal_handoff.py)
#   marshal.sh enable [--project P] [--plan TOKEN --approved WORDS]   switch this machine to the shared refs backend
#   marshal.sh disable [--project P] [--plan TOKEN --approved WORDS]   switch back to the local records (with integrity on: plan, then apply)
#   marshal.sh enable --integrity off|advisory|strict [--project P] [--plan TOKEN --approved WORDS]   set how records are signed
#   marshal.sh key init [--principal P] [--plan TOKEN --approved WORDS]   make this machine's signing key
#   marshal.sh signers add --line L | remove P | list [--project P] [--plan TOKEN --approved WORDS]   who is trusted to sign
#   marshal.sh resign NAME [--project P] [--plan TOKEN --approved WORDS]   sign an unsigned open record
#   marshal.sh forget NAME [--project P] [--plan TOKEN --approved WORDS]   drop this machine's accepted mark of NAME (integrity on)
# enable without options prints the plan and a plan token; applying is --plan TOKEN --approved WORDS (audit line
# marshal:enable). The switch is the file $DA_STATE/marshal/PROJECT.enabled, written by marshal_refs.py, never a project
# answer (project set refuses marshal.* but marshal.lease_minutes). enable and disable, like every verb that changes a record, are
# refused (exit 2) inside a member run. So are key, signers add|remove, enable --integrity and resign, which are owner verbs too:
# key init, signers add|remove and enable print a plan and a plan token first and apply with --plan TOKEN --approved WORDS (audit
# lines marshal:key-init, marshal:signers, marshal:enable); resign prints the head, the lead and the goal of the record it would sign and
# a plan token that covers them, and applies with --plan TOKEN --approved WORDS (marshal:resign). forget is an owner verb of the same kind: it
# drops the accepted high-water mark ($DA_STATE/features/.accepted-PROJECT.json) of one feature, so that a stale mark (left after the feature
# was deleted or re-created on the remote) stops reporting "rollback detected"; the plan prints the rev and the oid of the mark, the token
# covers both, applying a changed mark is refused (marshal:forget); with integrity off, or with no mark for NAME, it exits 2. The signing key is the
# file $DA_CONF/credentials/marshal_ed25519 (mode 600, made by key init, never overwritten, never in an argument list, the audit log
# or the tracker); the trusted signers are the file $DA_STATE/marshal/PROJECT.signers; the mode is the field integrity of the
# switch file (default off). handoff needs no lease and works for a feature someone else leads; it changes no record, ref or audit line and
# fetches nothing (the shared records are read from the cache this machine holds); only --write FILE makes a file (new, mode 600, never
# inside a repository or the qargi directories), which the guard refuses to a member. A member may read none of them (lib/guard.py). status and check take --no-fetch: read the cache of the remote refs only (the
# session hook uses it).
#
# The project answer marshal.lease_minutes is the lease length in minutes (a whole number from 1 to 1440, default 15): qargi project set P marshal.lease_minutes 20.
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
#                                     (stale lead, anonymous identity, overlapping files, no lead) go to stderr; stdout stays empty.
#                                     When this identity leads NAME it also renews the lease (once a third of it has passed, even when
#                                     it lapsed: nobody else holds the feature), so every verb of the lead that asks keeps it alive
#   marshal_touch PROJ NAME           the renewal alone: silent, never fails (verbs that do not gate, such as feature status)
#   marshal_touch_run RUN             the same for the feature that the local run RUN is based on, from the lead's registry (local verify,
#                                     clean, review check and apply, where there is no feature name on the command line)
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
  t=$(jq -r '.marshal.lease_minutes // empty' "$DA_CONF/projects/$1.json" 2>/dev/null) || t=''
  case $t in ''|*[!0-9]*) t=15;; esac
  { [ ${#t} -le 4 ] && [ "$t" -ge 1 ] && [ "$t" -le 1440 ]; } || t=15   # project set and project validate refuse anything else; a hand-edited value gets the default
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

marshal_start() { # a restarted session of the same lead (host, user, work tree; stale lease) continues without a takeover; that is audited
  local af rc=0
  af=$(mktemp "$DA_STATE/.marshal-audit.XXXXXX") || af=/dev/null
  QARGI_MARSHAL_AUDIT_OUT=$af marshal_py "$1" start "$2" --purpose "${3:-}" >/dev/null || rc=$?
  if [ "$af" != /dev/null ]; then if [ "$rc" = 0 ] && [ -s "$af" ]; then audit_log "marshal:succession" "$(cat "$af")"; fi; rm -f "$af"; fi
  return "$rc"
}
marshal_check() { marshal_py "$1" check "$2" --renew >/dev/null; }
marshal_touch() { marshal_py "$1" check "$2" --renew >/dev/null 2>&1 || true; }
marshal_touch_run() { # RUN: renew the lease of the feature that the local run RUN is based on (feature/NAME), when this identity leads it
  local base proj
  base=$( reg_load; reg_get "$1" base ) || return 0
  case $base in feature/?*) ;; *) return 0;; esac
  proj=$( reg_load; run_project "$1" ) || return 0
  [ -z "$proj" ] || marshal_touch "$proj" "${base#feature/}"
}
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
  local usage="usage: qargi marshal claim|status|set|check|renew|release|take|takeover|finish [NAME] [--project P] [--as ID] [--as-successor-of ID] [--goal T] [--plan T] [--note T] [--status S] [--approved WORDS] [--all] [--history] [--brief] [--json] [--no-fetch]
       qargi marshal handoff [NAME] [--project P] [--as ID] [--write FILE] [--json]
       qargi marshal enable [--project P] [--integrity off|advisory|strict] [--plan TOKEN --approved WORDS] | disable [--project P] [--plan TOKEN --approved WORDS]
       qargi marshal key init [--principal P] [--plan TOKEN --approved WORDS]
       qargi marshal signers add --line L | remove PRINCIPAL [--project P] [--plan TOKEN --approved WORDS] | list [--project P]
       qargi marshal resign NAME [--project P] [--plan TOKEN --approved WORDS]
       qargi marshal forget NAME [--project P] [--plan TOKEN --approved WORDS]"
  local name='' PROJ='' as='' all='' brief='' json='' history='' nofetch='' want sub='' line='' principal='' integ=''
  local -a opt=()
  case $verb in
    key) sub=${1:-}; [ "$sub" = init ] || { echo "qargi: $usage" >&2; exit 2; }; shift;;
    signers) sub=${1:-}; case $sub in add|remove|list) shift;; *) echo "qargi: $usage" >&2; exit 2;; esac;;
  esac
  case $verb in
    enable|disable|key|resign|forget) python3 -I "$MARSHAL_LIB/marshal_refs.py" member-check "$verb" || exit $?;;
    signers) [ "$sub" = list ] || python3 -I "$MARSHAL_LIB/marshal_refs.py" member-check "signers $sub" || exit $?;;
  esac
  case $verb in
    enable) want=' --project --plan --approved --integrity ';;
    key) want=' --principal --plan --approved ';;
    signers) want=' --project --line --plan --approved ';;
    resign|forget) want=' --project --plan --approved ';;
    disable) want=' --project --plan --approved ';;
    claim) want=' --project --as --goal --as-successor-of ';;
    status) want=' --project --as --all --history --brief --json --no-fetch ';;
    handoff) want=' --project --as --write --json ';;
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
          --plan) case $verb in enable|key|signers|resign|forget|disable) PLAN_ARG=$2; export PLAN_ARG;; *) opt+=("$1" "$2");; esac;;
          *) opt+=("$1" "$2");;
        esac
        shift 2;;
      -*) echo "qargi: unknown option $1; $usage" >&2; exit 2;;
      *) if [ -z "$name" ]; then name=$1; else echo "qargi: unexpected argument $1; $usage" >&2; exit 2; fi; shift;;
    esac
  done
  case $verb in
    status|check|handoff|enable|disable|key) ;;
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
    QARGI_NESTED='' need_plan "$ktok"
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
    QARGI_NESTED='' need_plan "$tok"
    python3 -I "$MARSHAL_LIB/marshal_refs.py" switch-write --state "$DA_STATE" --project "$PROJ" --remote "$remote" --words "$APPROVED" ${integ:+--integrity "$integ"} || exit $?
    audit_log "marshal:enable" "$PROJ $remote${integ:+ integrity=$integ}"
    # the mode in effect, not only the one asked for: an enable after a disable starts with integrity off and says so
    local eff
    eff=$(jq -r '.integrity // "off"' "$DA_STATE/marshal/$PROJ.enabled" 2>/dev/null) || eff=off
    echo "marshal of $PROJ: shared refs backend enabled (remote $remote), integrity $eff"
    [ "$eff" != off ] || echo "note: integrity is off: nothing is signed or checked (qargi marshal enable --integrity advisory|strict)"
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
    QARGI_NESTED='' need_plan "$stok"
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
    QARGI_NESTED='' need_plan "$rtok"
    marshal_py "$PROJ" resign "$name" --approved "$APPROVED" '--expect-head' "$rhead" || rrc=$?
    if [ "$rrc" = 0 ]; then audit_log "marshal:resign" "$PROJ $name"; fi
    exit "$rrc"
  fi
  if [ "$verb" = forget ]; then
    # the mark is this machine's own file; the plan shows it (rev and oid) and the token covers both, so a mark that moved since the plan is
    # another plan. The drop re-checks the mark under the lock the marshal's own writes take.
    local fmk=$DA_STATE/features/.accepted-$PROJ.json fint fshow frev foid ftok frc=0
    fint=$(jq -r '.integrity // "off"' "$DA_STATE/marshal/$PROJ.enabled" 2>/dev/null) || fint=off
    case $fint in advisory|strict) ;; *) echo "qargi: marshal forget needs integrity advisory or strict on this machine: with integrity off no mark is kept or checked (integrity is $fint for $PROJ)" >&2; exit 2;; esac
    fshow=$(python3 -I "$MARSHAL_LIB/marshal_sign.py" hw show --file "$fmk" --name "$name") || exit $?
    frev=$(sed -n 's/^rev //p' <<<"$fshow"); foid=$(sed -n 's/^oid //p' <<<"$fshow")
    ftok=$(printf 'marshal forget %s %s rev=%s oid=%s' "$PROJ" "$name" "$frev" "$foid" | plan_token)
    if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
      echo "would drop this machine's accepted mark of $name (rev $frev, oid $foid): the next record of $name found on the remote is trusted on first sight again, and a rollback of $name is no longer detected against rev $frev; only the mark of $name goes, the refs on the remote stay as they are"
      echo "plan token: $ftok   (apply with: qargi marshal forget $name --project $PROJ --plan $ftok --approved \"...\")"
      exit 0
    fi
    [ -n "${APPROVED:-}" ] || die "forget needs --approved WORDS (the owner's words): it drops the accepted mark of $name on this machine; run it without options for the plan"
    QARGI_NESTED='' need_plan "$ftok"
    python3 -I "$MARSHAL_LIB/marshal_sign.py" hw drop --file "$fmk" --name "$name" --rev "$frev" --oid "$foid" --lock "$DA_STATE/features/.refs-$PROJ.lock" || frc=$?
    if [ "$frc" = 0 ]; then audit_log "marshal:forget" "$PROJ $name rev=$frev oid=$foid"; echo "marshal of $PROJ: forgot the accepted mark of $name (rev $frev)"; fi
    exit "$frc"
  fi
  if [ "$verb" = disable ]; then
    # disable removes the switch file, and the integrity setting with it: while that is advisory or strict it is an approved step
    local cur dtok
    cur=$(jq -r '.integrity // "off"' "$DA_STATE/marshal/$PROJ.enabled" 2>/dev/null) || cur=off
    [ -n "$cur" ] || cur=off
    if [ "$cur" != off ]; then
      dtok=$(printf 'marshal disable %s integrity=%s' "$PROJ" "$cur" | plan_token)
      if [ -z "${APPROVED:-}" ] && [ -z "${PLAN_ARG:-}" ]; then
        echo "would switch the marshal of $PROJ on this machine back to the local records AND drop its integrity setting ($cur): records are no longer signed or checked here, and a later enable starts with integrity off; the signing key, the allowed signers and the accepted marks stay as they are, and the refs on the remote are left as they are"
        echo "plan token: $dtok   (apply with: qargi marshal disable --project $PROJ --plan $dtok --approved \"...\")"
        exit 0
      fi
      [ -n "${APPROVED:-}" ] || die "disable needs --approved WORDS (the owner's words) while integrity is $cur; run it without options for the plan"
      QARGI_NESTED='' need_plan "$dtok"
    fi
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
  if [ "$verb" = claim ]; then
    local crc=0 caf
    caf=$(mktemp "$DA_STATE/.marshal-audit.XXXXXX")
    QARGI_MARSHAL_AUDIT_OUT=$caf marshal_py "$PROJ" claim "${opt[@]}" || crc=$?
    if [ "$crc" = 0 ] && [ -s "$caf" ]; then audit_log "marshal:succession" "$(cat "$caf")"; fi
    rm -f "$caf"
    exit "$crc"
  fi
  if [ "$verb" = handoff ]; then
    # read only: no lease, no fetch, no record written; the file of --write (and the line in $DA_STATE/handoff that says when it was written) is the only thing it may make
    local hrc=0
    python3 -I "$MARSHAL_LIB/marshal_handoff.py" --state "$DA_STATE" --conf "$DA_CONF" --project "$PROJ" --repo "$(marshal_repo "$PROJ")" --ttl "$(marshal_ttl "$PROJ")" "${opt[@]}" || hrc=$?
    # the stage line (the lead's context, whether a compact is safe now): after the note, never inside --json; on stderr when stdout is the note itself
    if [ "$hrc" = 0 ] && [ -z "$json" ]; then
      case " ${opt[*]} " in *" --write "*) lead_advice;; *) lead_advice >&2;; esac
    fi
    exit "$hrc"
  fi
  marshal_py "$PROJ" "$verb" "${opt[@]}"
}

# executed, not sourced: dispatch the verbs
if [ "${BASH_SOURCE[0]}" = "$0" ]; then marshal_main "$@"; fi
