#!/usr/bin/env bash
# Reconcile a project's memory stores with the canon (canon/CANON.md).
#
#   canon.sh check   PROJECT [--kind memory|reference]
#   canon.sh plan    PROJECT [--kind K] [--default-role R]
#   canon.sh apply   PROJECT [--kind K] [--default-role R] --approved "<go-ahead>"
#   canon.sh import  PROJECT --from STORE_ID --role R --map docs-v0 [--approved "<go-ahead>"]
#   canon.sh seed-role PROJECT --role R|shared --approved "..."   write the role's baseline (provision/role-seeds/R/; "shared" seeds shared/) without overwriting
#   canon.sh audit   PROJECT [--kind K]        who wrote under which role folder (read-only)
#   canon.sh promote PROJECT --kind K --path /roles/R/... --approved "<go-ahead>"
#
# PROJECT's stores come from its stored answers (qargi project init). Without
# --kind, both stores are handled. `plan` and `check` change nothing. The source
# of an import is read, never modified.
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
PY=$here/canon.py
SEED=$here/../provision/canon-seed
[ -d "$SEED" ] || SEED=$here/provision/canon-seed

verb=${1:-}; shift || true
PROJECT=${1:-}; shift || true
KIND='' DEFAULT_ROLE=build PLAN_ARG='' APPROVED='' FROM='' ROLE='' MAP='' PATH_ARG=''
while [ $# -gt 0 ]; do
  case $1 in
    --kind) KIND=$2; shift 2;;
    --default-role) DEFAULT_ROLE=$2; shift 2;;
    --approved) APPROVED=$2; shift 2;;
    --plan) PLAN_ARG=$2; shift 2;;
    --from) FROM=$2; shift 2;;
    --role) ROLE=$2; shift 2;;
    --map) MAP=$2; shift 2;;
    --path) PATH_ARG=$2; shift 2;;
    *) die "unknown option $1";;
  esac
done
export PLAN_ARG
valid_project "$PROJECT" || die "usage: canon.sh check|plan|apply|import|promote PROJECT ..."
PCFG=$DA_CONF/projects/$PROJECT.json
[ -f "$PCFG" ] || die "no stored answers for $PROJECT: run /qargi-project first"
ROLES=$(jq -r '([.roles | keys[]] + (if ((.teams // {}) | length) > 0 then ["lead"] else [] end)) | join(",")' "$PCFG")
TODAY=$(date -u +%F)
case $KIND in ''|memory|reference) ;; *) die "--kind memory|reference";; esac
kinds=${KIND:-"memory reference"}

store_of() { jq -r --arg k "$1" '.memory[$k + "_store"] // ""' "$PCFG"; }

dump() { # store_id -> JSONL of full memories on stdout
  if [ -n "${QARGI_CANON_FIXTURE_DIR:-}" ]; then cat "$QARGI_CANON_FIXTURE_DIR/$1.jsonl"; return; fi
  ant beta:memory-stores:memories list --memory-store-id "$1" --path-prefix / --view full --max-items -1 </dev/null 2>/dev/null \
    | jq -c 'select(.type=="memory") | {type, id, path, content, content_sha256}'
}

show_plan() { # plan.json
  jq -r '"from \(.from_version) to canon version \(.to_version): \(.ops|length) step(s)"' "$1"
  jq -r '.ops[] | if .op=="move" then "  move   \(.from) -> \(.to)" elif .op=="create" then "  create \(.path)" elif .op=="update" then "  update \(.path)" else "  mark   \(.path)" end' "$1"
  jq -r '.notes[] | "  note: " + .' "$1"
}

exec_ops() { # store_id plan.json
  local store=$1 plan=$2 n=0 op f
  while IFS= read -r op <&3; do
    case $(jq -r .op <<<"$op") in
      move)
        ant beta:memory-stores:memories update --memory-store-id "$store" --memory-id "$(jq -r .id <<<"$op")" \
          --path "$(jq -r .to <<<"$op")" </dev/null >/dev/null 2>&1 || die "move failed: $(jq -r .from <<<"$op")";;
      create|marker|update)
        f=$(mktemp); jq -j .content <<<"$op" > "$f"
        if [ -n "$(jq -r '.id // empty' <<<"$op")" ]; then
          sha=$(jq -r '.sha // empty' <<<"$op"); pre=()
          [ -z "$sha" ] || pre=(--precondition "{type: content_sha256, content_sha256: \"$sha\"}")
          printf 'content: "@%s"\n' "$f" | ant beta:memory-stores:memories update --memory-store-id "$store" \
            --memory-id "$(jq -r .id <<<"$op")" "${pre[@]}" >/dev/null 2>&1 || { rm -f "$f"; die "update failed (changed meanwhile?): $(jq -r .path <<<"$op")"; }
        else
          printf 'content: "@%s"\n' "$f" | ant beta:memory-stores:memories create --memory-store-id "$store" \
            --path "$(jq -r .path <<<"$op")" >/dev/null 2>&1 || { rm -f "$f"; die "create failed: $(jq -r .path <<<"$op")"; }
        fi
        rm -f "$f";;
    esac
    n=$((n+1))
  done 3< <(jq -c '.ops[]' "$plan")
  echo "applied $n step(s)"
}

make_plan() { # kind -> prints plan json path
  local k=$1 store; store=$(store_of "$k"); [ -n "$store" ] || die "the project has no $k store recorded"
  local tmp; tmp=$(mktemp -d)
  dump "$store" > "$tmp/s.jsonl"
  python3 -I "$PY" plan --kind "$k" --project "$PROJECT" --roles "$ROLES" --default-role "$DEFAULT_ROLE" \
    --store "$tmp/s.jsonl" --seed "$SEED" --today "$TODAY" > "$tmp/plan.json" || die "planning failed for $k"
  if [ "$(jq -r .from_version "$tmp/plan.json")" = unknown ] && [ "$verb" = apply ]; then
    jq -r '.notes[]' "$tmp/plan.json" >&2; die "the $k store has an unrecognised layout; nothing was changed"
  fi
  echo "$tmp/plan.json"
}

case $verb in
  check)
    rc=0
    for k in $kinds; do
      store=$(store_of "$k"); [ -n "$store" ] || { echo "$k: no store recorded"; continue; }
      tmp=$(mktemp); dump "$store" > "$tmp"
      echo "== $k store $store"
      python3 -I "$PY" check --kind "$k" --project "$PROJECT" --roles "$ROLES" --store "$tmp" || rc=1
      rm -f "$tmp"
    done
    exit $rc;;
  plan)
    tok=$(for k in $kinds; do p=$(make_plan "$k"); jq -S -c .ops "$p"; done | plan_token)
    for k in $kinds; do echo "== $k"; p=$(make_plan "$k"); show_plan "$p"; done
    echo "plan token: $tok   (apply with: --plan $tok --approved \"...\")";;
  apply)
    [ -n "$APPROVED" ] || die "apply needs --approved \"<the user's go-ahead for the plan shown by: plan>\""
    ant_ok
    tok=$(for k in $kinds; do p=$(make_plan "$k"); jq -S -c .ops "$p"; done | plan_token)
    need_plan "$tok"; audit_log canon-apply "$PROJECT"
    for k in $kinds; do
      echo "== $k"; p=$(make_plan "$k"); show_plan "$p"
      [ "$(jq '.ops|length' "$p")" = 0 ] && { echo "nothing to do"; continue; }
      exec_ops "$(store_of "$k")" "$p"
    done
    echo "reconciled $PROJECT (approved: $APPROVED)";;
  import)
    [ -n "$FROM" ] && [ -n "$ROLE" ] && [ -n "$MAP" ] || die "import needs --from STORE_ID --role R --map docs-v0"
    printf '%s' "$ROLES" | tr ',' '\n' | grep -qx "$ROLE" || die "role $ROLE is not enabled for $PROJECT"
    tmp=$(mktemp -d)
    dump "$FROM" > "$tmp/src.jsonl"; dump "$(store_of memory)" > "$tmp/mem.jsonl"; dump "$(store_of reference)" > "$tmp/ref.jsonl"
    python3 -I "$PY" import --map "$MAP" --project "$PROJECT" --role "$ROLE" --src "$tmp/src.jsonl" --memory "$tmp/mem.jsonl" --reference "$tmp/ref.jsonl" --today "$TODAY" > "$tmp/imp.json"
    for k in memory reference; do
      jq -c '{from_version:"-", to_version:"-", ops: .[$k], notes: (if $k=="memory" then .notes else [] end)}' --arg k "$k" "$tmp/imp.json" > "$tmp/$k.plan.json"
      echo "== $k store: $(jq '.ops|length' "$tmp/$k.plan.json") file(s) to add under roles/$ROLE/"
      jq -r '.ops[] | "  create \(.path)  (\(.content|length) chars)"' "$tmp/$k.plan.json" | head -60
    done
    jq -r '.notes[] | "  note: " + .' "$tmp/imp.json"
    tok=$(cat "$tmp/memory.plan.json" "$tmp/reference.plan.json" | jq -S -c .ops | plan_token)
    if [ -n "$APPROVED" ]; then
      ant_ok; need_plan "$tok"; audit_log canon-import "$PROJECT from $FROM into $ROLE"
      for k in memory reference; do [ "$(jq '.ops|length' "$tmp/$k.plan.json")" = 0 ] || exec_ops "$(store_of "$k")" "$tmp/$k.plan.json"; done
      echo "imported $FROM into $PROJECT roles/$ROLE (approved: $APPROVED); the source is untouched"
    else
      echo "plan only; plan token: $tok   (apply with: --plan $tok --approved \"...\")"
    fi;;
  seed-role)
    [ -n "$ROLE" ] || die "seed-role needs --role R"
    [ -n "$APPROVED" ] || die "seed-role needs --approved \"<go-ahead>\""
    [ "$ROLE" = shared ] || printf '%s' "$ROLES" | tr ',' '\n' | grep -qx "$ROLE" || die "role $ROLE is not enabled for $PROJECT"
    RS=$here/../provision/role-seeds/$ROLE; [ -d "$RS" ] || RS=$here/provision/role-seeds/$ROLE
    [ -d "$RS" ] || { echo "no seed for role $ROLE (nothing to write)"; exit 0; }
    ant_ok
    for part in reference memory; do
      [ -d "$RS/$part" ] || continue
      store=$(store_of "$part"); [ -n "$store" ] || { echo "the project has no $part store recorded"; continue; }
      tmp=$(mktemp); dump "$store" > "$tmp"
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
    # a session titled <project>-<role>-... that wrote under another role's folder is reported.
    bad=0
    for k in $kinds; do
      store=$(store_of "$k"); [ -n "$store" ] || continue
      echo "== $k store $store"
      declare -A role_of=()
      while IFS=$'\t' read -r sid path op; do
        [ -n "$sid" ] || continue
        if [ -z "${role_of[$sid]+x}" ]; then
          t=$(ant beta:sessions retrieve --session-id "$sid" </dev/null 2>/dev/null | jq -r '.title // ""')
          r=${t#"$PROJECT"-}; r=${r%%-*}
          role_of[$sid]=$r
        fi
        want=$(printf '%s' "$path" | sed -n 's#^/roles/\([^/]*\)/.*#\1#p')
        r=${role_of[$sid]}
        if [ -n "$want" ] && [ -n "$r" ] && [ "$want" != "$r" ] && printf '%s' "$ROLES" | tr ',' '\n' | grep -qx "$r"; then
          echo "CROSS-ROLE: session $sid (role $r) $op $path"; bad=1
        fi
      done < <(ant beta:memory-stores:memory-versions list --memory-store-id "$store" --max-items -1 </dev/null 2>/dev/null \
                | jq -r 'select(.created_by.type=="session_actor") | [.created_by.session_id, .path, .operation] | @tsv')
      unset role_of
    done
    [ "$bad" = 0 ] && echo "no cross-role writes found"
    exit $bad;;
  promote)
    [ -n "$KIND" ] && [ -n "$PATH_ARG" ] || die "promote needs --kind K --path /roles/R/..."
    [ -n "$APPROVED" ] || die "promote needs --approved \"<go-ahead>\""
    case $PATH_ARG in /roles/*/*) ;; *) die "--path must be /roles/<role>/<file>";; esac
    store=$(store_of "$KIND"); ant_ok; audit_log canon-promote "$PATH_ARG"
    dest="/shared/${PATH_ARG#/roles/*/}"
    tmp=$(mktemp); dump "$store" > "$tmp"
    id=$(jq -r --arg p "$PATH_ARG" 'select(.path==$p)|.id' "$tmp"); [ -n "$id" ] || die "no such file: $PATH_ARG"
    [ -z "$(jq -r --arg p "$dest" 'select(.path==$p)|.id' "$tmp")" ] || die "$dest already exists; merge by hand"
    ant beta:memory-stores:memories update --memory-store-id "$store" --memory-id "$id" --path "$dest" </dev/null >/dev/null || die "move failed"
    echo "moved $PATH_ARG -> $dest; add its row to shared/INDEX.md and remove it from the role's INDEX.md (approved: $APPROVED)";;
  *) die "usage: canon.sh check|plan|apply|import|promote PROJECT ...";;
esac
