#!/usr/bin/env bash
# Reconcile a project's memory stores with the canon (canon/CANON.md).
#
#   canon.sh check   PROJECT [--kind memory|reference]
#   canon.sh plan    PROJECT [--kind K]
#   canon.sh apply   PROJECT [--kind K] --approved "<go-ahead>"
#   canon.sh seed-role PROJECT --role R|shared --approved "..."   write the role's baseline (provision/role-seeds/R/; "shared" seeds shared/) without overwriting
#   canon.sh audit   PROJECT [--kind K]        who wrote under which role folder (read-only)
#   canon.sh promote PROJECT --kind K --path /roles/R/... --approved "<go-ahead>"
#
# PROJECT's stores come from its stored answers (qargi project init). Without
# --kind, both stores are handled. `plan` and `check` change nothing.
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
PY=$here/canon.py
SEED=$here/../provision/canon-seed
[ -d "$SEED" ] || SEED=$here/provision/canon-seed

verb=${1:-}; shift || true
PROJECT=${1:-}; shift || true
KIND='' PLAN_ARG='' APPROVED='' ROLE='' PATH_ARG=''
while [ $# -gt 0 ]; do
  case $1 in
    --kind) need_val "$1" $#; KIND=$2; shift 2;;
    --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;;
    --role) need_val "$1" $#; ROLE=$2; shift 2;;
    --path) need_val "$1" $#; PATH_ARG=$2; shift 2;;
    *) usage_die "unknown option $1";;
  esac
done
export PLAN_ARG
valid_project "$PROJECT" || usage_die "usage: canon.sh check|plan|apply|promote PROJECT ..."
PCFG=$DA_CONF/projects/$PROJECT.json
[ -f "$PCFG" ] || die "no stored answers for $PROJECT: run /qargi-project first"
ROLES=$(jq -r '([.roles | keys[]] + (if ((.teams // {}) | length) > 0 then ["lead"] else [] end)) | join(",")' "$PCFG")
TODAY=$(date -u +%F)
# every temporary file and directory of a verb lives under WORK, which is removed when the verb ends, by its status or by die
WORK=$(mktemp -d) || die "cannot make a temporary directory"
trap 'rm -rf "$WORK"' EXIT
case $KIND in ''|memory|reference) ;; *) usage_die "--kind memory|reference";; esac
kinds=${KIND:-"memory reference"}

store_of() { jq -r --arg k "$1" '.memory[$k + "_store"] // ""' "$PCFG"; }

dump() { mem_dump "$@"; }
# probe STORE FILE -> the memories of STORE in FILE; when the store cannot be listed (ant missing, not logged in, no access) it sets WHY to the
# reason and fails: an unreachable store is never an empty one, and nothing is planned from it.
WHY=''
probe() { WHY=$(dump "$1" 2>&1 >"$2") || { rm -f "$2"; return 1; }; }
# reach_all -> every kind's store listed (probe), or one "unreachable: reason" line under its heading for each that is not; status 1 then
reach_all() {
  local k s t bad=0
  for k in $kinds; do
    s=$(store_of "$k"); [ -n "$s" ] || continue
    t=$(mktemp -p "$WORK"); if probe "$s" "$t"; then rm -f "$t"; else echo "== $k store $s"; echo "unreachable: $WHY"; bad=1; fi
  done
  return "$bad"
}

show_plan() { # plan.json
  jq -r '"from \(.from_version) to canon version \(.to_version): \(.ops|length) step(s)"' "$1"
  jq -r '.ops[] | if .op=="move" then "  move   \(.from) -> \(.to)" elif .op=="create" then "  create \(.path)" elif .op=="update" then "  update \(.path)" else "  mark   \(.path)" end' "$1"
  jq -r '.notes[] | "  note: " + .' "$1"
}

exec_ops() { mem_exec_ops "$@"; }

# make_plan KIND -> sets PLAN_FILE to the plan json of KIND. Call it in the shell of the verb and not in $(...): a die inside a command
# substitution leaves only that subshell, and the verb would go on with no plan.
PLAN_FILE=''
make_plan() {
  local k=$1 store; store=$(store_of "$k"); [ -n "$store" ] || die "the project has no $k store recorded"
  local tmp; tmp=$(mktemp -d -p "$WORK")
  probe "$store" "$tmp/s.jsonl" || die "the $k store $store is unreachable: $WHY; nothing was planned"
  python3 -I "$PY" plan --kind "$k" --project "$PROJECT" --roles "$ROLES" \
    --store "$tmp/s.jsonl" --seed "$SEED" --today "$TODAY" > "$tmp/plan.json" || die "planning failed for $k"
  if [ "$(jq -r .from_version "$tmp/plan.json")" = unknown ] && [ "$verb" = apply ]; then
    jq -r '.notes[]' "$tmp/plan.json" >&2; die "the $k store has an unrecognised layout; nothing was changed"
  fi
  PLAN_FILE=$tmp/plan.json
}

case $verb in
  check)
    rc=0
    for k in $kinds; do
      store=$(store_of "$k"); [ -n "$store" ] || { echo "$k: no store recorded"; continue; }
      tmp=$(mktemp -p "$WORK"); echo "== $k store $store"
      probe "$store" "$tmp" || { echo "unreachable: $WHY"; rc=1; continue; }
      python3 -I "$PY" check --kind "$k" --project "$PROJECT" --roles "$ROLES" --store "$tmp" || rc=1
      rm -f "$tmp"
    done
    exit $rc;;
  plan)
    reach_all || die "a store is unreachable: nothing was planned"
    declare -A plan=()
    for k in $kinds; do make_plan "$k"; plan[$k]=$PLAN_FILE; done
    tok=$(for k in $kinds; do jq -S -c .ops "${plan[$k]}"; done | plan_token)
    for k in $kinds; do echo "== $k"; show_plan "${plan[$k]}"; done
    echo "plan token: $tok   (apply with: --plan $tok --approved \"...\")";;
  apply)
    [ -n "$APPROVED" ] || die "apply needs --approved \"<the user's go-ahead for the plan shown by: plan>\""
    ant_ok
    reach_all || die "a store is unreachable: nothing was changed"
    declare -A plan=()
    for k in $kinds; do make_plan "$k"; plan[$k]=$PLAN_FILE; done
    tok=$(for k in $kinds; do jq -S -c .ops "${plan[$k]}"; done | plan_token)
    need_plan_nested "$tok"; audit_log canon-apply "$PROJECT"
    for k in $kinds; do
      p=${plan[$k]}; echo "== $k"; show_plan "$p"
      [ "$(jq '.ops|length' "$p")" = 0 ] && { echo "nothing to do"; continue; }
      exec_ops "$(store_of "$k")" "$p"
    done
    echo "reconciled $PROJECT (approved: $APPROVED)";;
  seed-role)
    [ -n "$ROLE" ] || usage_die "seed-role needs --role R"
    [ -n "$APPROVED" ] || die "seed-role needs --approved \"<go-ahead>\""
    [ "$ROLE" = shared ] || printf '%s' "$ROLES" | tr ',' '\n' | grep -qx "$ROLE" || die "role $ROLE is not enabled for $PROJECT"
    RS=$here/../provision/role-seeds/$ROLE; [ -d "$RS" ] || RS=$here/provision/role-seeds/$ROLE
    [ -d "$RS" ] || { echo "no seed for role $ROLE (nothing to write)"; exit 0; }
    ant_ok
    for part in reference memory; do
      [ -d "$RS/$part" ] || continue
      store=$(store_of "$part"); [ -n "$store" ] || { echo "the project has no $part store recorded"; continue; }
      tmp=$(mktemp -p "$WORK"); probe "$store" "$tmp" || die "the $part store $store is unreachable: $WHY; nothing was written"
      (cd "$RS/$part" && find . -type f | sort) | while IFS= read -r f; do
        rel=${f#./}; p="/roles/$ROLE/$rel"; [ "$ROLE" != shared ] || p="/shared/$rel"
        id=$(jq -r --arg p "$p" 'select(.path==$p)|.id' "$tmp")
        if [ -z "$id" ]; then
          printf 'content: "@%s"\n' "$RS/$part/$rel" | ant beta:memory-stores:memories create --memory-store-id "$store" --path "$p" >/dev/null 2>&1 && echo "created $p" || echo "FAILED $p" >&2
        elif [ "$rel" = INDEX.md ] && jq -e --arg p "$p" 'select(.path==$p and (.content|contains("| (none yet) | | |")))' "$tmp" >/dev/null; then
          printf 'content: "@%s"\n' "$RS/$part/$rel" | ant beta:memory-stores:memories update --memory-store-id "$store" --memory-id "$id" >/dev/null 2>&1 && echo "filled  $p" || echo "FAILED $p" >&2
        else echo "kept    $p"; fi
      done
      rm -f "$tmp"
    done;;
  audit)
    # Isolation between roles is by convention; the memory version history makes it auditable:
    # a session titled <project>-<role>-... that wrote under another role's folder is reported. A session of a cloud base is
    # titled <project>-worker-... or <project>-reviewer-...: its role is the one in the local tracker row of the session id
    # (read-only). A session with no row, or a row without a role, is not attributed and is counted in one NOTE at the end.
    bad=0
    declare -A unattr=()
    for k in $kinds; do
      store=$(store_of "$k"); [ -n "$store" ] || continue
      echo "== $k store $store"
      declare -A role_of=()
      while IFS=$'\t' read -r sid path op; do
        [ -n "$sid" ] || continue
        if [ -z "${role_of[$sid]+x}" ]; then
          t=$(ant beta:sessions retrieve --session-id "$sid" </dev/null 2>/dev/null | jq -r '.title // ""')
          r=${t#"$PROJECT"-}; r=${r%%-*}
          case $r in dev) r="build";; docs) r="write";; esac   # sessions titled before the roles were named by ability
          if is_base "$r"; then r=$(jq -r --arg s "$sid" '.[$s].role // empty' "$TRK" 2>/dev/null) || r=''; fi
          role_of[$sid]=$r
        fi
        want=$(printf '%s' "$path" | sed -n 's#^/roles/\([^/]*\)/.*#\1#p')
        r=${role_of[$sid]}
        [ -z "$want" ] || [ -n "$r" ] || unattr[$sid]=1
        if [ -n "$want" ] && [ -n "$r" ] && [ "$want" != "$r" ] && printf '%s' "$ROLES" | tr ',' '\n' | grep -qx "$r"; then
          echo "CROSS-ROLE: session $sid (role $r) $op $path"; bad=1
        fi
      done < <(ant beta:memory-stores:memory-versions list --memory-store-id "$store" --max-items -1 </dev/null 2>/dev/null \
                | jq -r 'select(.created_by.type=="session_actor") | [.created_by.session_id, .path, .operation] | @tsv')
      unset role_of
    done
    [ "$bad" = 0 ] && echo "no cross-role writes found"
    [ "${#unattr[@]}" = 0 ] || echo "NOTE: ${#unattr[@]} session(s) could not be attributed to a role"
    exit $bad;;
  promote)
    [ -n "$KIND" ] && [ -n "$PATH_ARG" ] || usage_die "promote needs --kind K --path /roles/R/..."
    [ -n "$APPROVED" ] || die "promote needs --approved \"<go-ahead>\""
    case $PATH_ARG in /roles/*/*) ;; *) usage_die "--path must be /roles/<role>/<file>";; esac
    store=$(store_of "$KIND"); ant_ok; audit_log canon-promote "$PATH_ARG"
    dest="/shared/${PATH_ARG#/roles/*/}"
    tmp=$(mktemp -p "$WORK"); probe "$store" "$tmp" || die "the $KIND store $store is unreachable: $WHY; nothing was moved"
    id=$(jq -r --arg p "$PATH_ARG" 'select(.path==$p)|.id' "$tmp"); [ -n "$id" ] || die "no such file: $PATH_ARG"
    [ -z "$(jq -r --arg p "$dest" 'select(.path==$p)|.id' "$tmp")" ] || die "$dest already exists; merge by hand"
    ant beta:memory-stores:memories update --memory-store-id "$store" --memory-id "$id" --path "$dest" </dev/null >/dev/null || die "move failed"
    echo "moved $PATH_ARG -> $dest; add its row to shared/INDEX.md and remove it from the role's INDEX.md (approved: $APPROVED)";;
  *) usage_die "usage: canon.sh check|plan|apply|promote PROJECT ...";;
esac
