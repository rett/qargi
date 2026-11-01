#!/usr/bin/env bash
# Write a memory tier (memory.sh dispatches here):
#   tierwrite.sh init TIER [--project P] [--plan TOKEN --approved "..."]
#   tierwrite.sh move PATH --from TIER --to TIER [--project P] [--plan TOKEN --approved "..."]
# TIER is repo, project, shared or system for init (the cloud tier is created by qargi provision); move also takes cloud.
# Without --approved this prints the plan and its token and changes nothing. The write happens only for the plan the
# token names, and every tier is checked against the notes the plan read before the first change (lib/tierplan.py).
# Nothing is deleted and nothing is committed: a move archives the source note, init into the repo tier only writes files.
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")

usage() { echo "usage: qargi memory init TIER | move PATH --from TIER --to TIER   [--project P] [--plan TOKEN --approved \"...\"]" >&2; exit 2; }

v=${1:-}; shift || true
case $v in init|move) ;; *) usage;; esac
unset QARGI_NESTED   # a caller that is itself approved has not approved this plan: the token is always needed
ARG1='' FROM='' TO='' PROJECT='' PLAN_ARG='' APPROVED=''
export PLAN_ARG
while [ $# -gt 0 ]; do
  case $1 in
    --project) [ $# -ge 2 ] || usage; PROJECT=$2; shift 2;;
    --from) [ $# -ge 2 ] || usage; FROM=$2; shift 2;;
    --to) [ $# -ge 2 ] || usage; TO=$2; shift 2;;
    --plan) [ $# -ge 2 ] || usage; PLAN_ARG=$2; shift 2;;
    --approved) [ $# -ge 2 ] || usage; APPROVED=$2; shift 2;;
    -*) die "unknown option $1";;
    *) [ -z "$ARG1" ] || usage; ARG1=$1; shift;;
  esac
done
[ -n "$ARG1" ] || usage
if [ "$v" = init ]; then
  [ -z "$FROM$TO" ] || die "init takes a tier only; --from and --to are for move"
else
  [ -n "$FROM" ] && [ -n "$TO" ] || usage
fi

# a cloud tier at either end is reached with ant (a test's fixture replaces it)
if [ -z "${QARGI_CANON_FIXTURE_DIR:-}" ] && { [ "$FROM" = cloud ] || [ "$TO" = cloud ]; }; then ant_ok; fi

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
args=(--out "$tmp/plan.json")
[ -z "$PROJECT" ] || args+=(--project "$PROJECT")
if [ "$v" = init ]; then
  python3 -I "$here/tierplan.py" plan-init "$ARG1" "${args[@]}"; rc=$?
else
  python3 -I "$here/tierplan.py" plan-move "$ARG1" --from "$FROM" --to "$TO" "${args[@]}"; rc=$?
fi
[ "$rc" -eq 0 ] || exit "$rc"
[ -s "$tmp/plan.json" ] || exit 0   # nothing to plan (already initialised: the planner said so)

tok=$(jq -S -c . "$tmp/plan.json" | plan_token)
python3 -I "$here/tierplan.py" show "$tmp/plan.json" || exit 1
if [ -z "$APPROVED" ]; then
  echo "plan only, nothing was changed; plan token: $tok   (apply with: --plan $tok --approved \"...\")"; exit 0
fi
[ -n "$tok" ] || die "no plan token could be computed; nothing was changed"
[ -n "$PLAN_ARG" ] || die "$v needs --plan $tok (the token of the plan shown above) with --approved; nothing was changed"
need_plan "$tok"
if [ -z "${QARGI_CANON_FIXTURE_DIR:-}" ] && [ "$(jq -r .needs_ant "$tmp/plan.json")" = true ]; then ant_ok; fi
# what was approved goes to the audit log: token, tiers and every step; a second line says it was applied
detail=$(jq -nc --arg v "$v" --arg arg "$ARG1" --arg from "$FROM" --arg to "$TO" --arg tok "$tok" --slurpfile plan "$tmp/plan.json" \
  '{verb:$v, arg:$arg, from:$from, to:$to, token:$tok,
    steps:[$plan[0] | ("target","source") as $k | (.[$k].ops // [])[] | {store:$k, op:.op, path:(.path // .from), to:(.to // null)}]}')
audit_log "memory-$v" "$detail"
python3 -I "$here/tierplan.py" apply "$tmp/plan.json" > "$tmp/applied.txt" || exit 1
audit_log "memory-$v-applied" "$tok"
if [ "$v" = init ]; then
  loc=$(jq -r '.stores.target' "$tmp/plan.json"); n=$(sed -n 's/^files: //p' "$tmp/applied.txt")
  echo "init done: tier $ARG1 at $loc (${n:-0} files); nothing was committed"
else
  echo "move done (approved: $APPROVED); nothing was deleted; source archived under /_archive/$(jq -r '[.source.ops[]? | select(.op=="archive") | .to | split("/")[2]] | first // empty' "$tmp/plan.json")/"
fi
