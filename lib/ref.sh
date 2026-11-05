#!/usr/bin/env bash
# shellcheck disable=SC2154  # REPO and PROJ come from gitflow.sh (project_load)
# The lead's ref journal ($QARGI_STATE/ref-journal.jsonl), written by hand where no flow verb did the move.
#
#   ref.sh record --rewrite REF OLD NEW --why TEXT [--project P]
#       The lead rewrote an agent branch (reworded a message, split or squashed commits, dropped a trailer) without changing what
#       it holds: REF (agent/NAME or refs/heads/agent/NAME) moves from OLD to NEW only when the trees of OLD and NEW are identical
#       (git rev-parse OLD^{tree}) and REF is at OLD now (the move is a compare-and-swap: update-ref REF NEW OLD). The move is
#       journaled with the reason (verb ref:rewrite, why TEXT), so `qargi local verify` and `local clean` of a run prepared before
#       it accept it and name it as a rewrite, and `local clean` and `local list` follow a recorded run's applied tip to NEW.
#       Nothing else changes: no working tree (the trees are the same), no other ref, nothing on origin. The lead's verb: the guard
#       refuses it to a member.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PROJ='' MODE='' WHY='' ARGS=()
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;;
    --rewrite) MODE=rewrite; shift;;
    --why) need_val "$1" $#; WHY=$2; shift 2;;
    -*) usage_die "unknown option $1";;
    *) ARGS+=("$1"); shift;;
  esac
done
USAGE="usage: qargi ref record --rewrite REF OLD NEW --why \"TEXT\" [--project P]"
[ "$verb" = record ] || usage_die "$USAGE"
[ "$MODE" = rewrite ] || usage_die "ref record needs --rewrite (the one kind of move it records); $USAGE"
[ "${#ARGS[@]}" = 3 ] || usage_die "ref record --rewrite takes REF, OLD and NEW; $USAGE"
[ -n "$WHY" ] || usage_die "ref record --rewrite needs --why \"TEXT\": the reason is journaled and verify names it"
. "$(dirname "$0")/gitflow.sh"
project_load
ref=${ARGS[0]}; ref=${ref#refs/heads/}
case $ref in agent/?*) ;; *) die "only an agent/* branch is rewritten this way (not $ref): a long-lived, feature, release or hotfix branch is never rewritten";; esac
git check-ref-format "refs/heads/$ref" || die "'$ref' is not a branch name"
old=$(g rev-parse -q --verify "${ARGS[1]}^{commit}" 2>/dev/null) || die "OLD (${ARGS[1]}) is not a commit of $REPO"
new=$(g rev-parse -q --verify "${ARGS[2]}^{commit}" 2>/dev/null) || die "NEW (${ARGS[2]}) is not a commit of $REPO"
[ "$old" != "$new" ] || die "OLD and NEW are the same commit: there is nothing to record"
cur=$(sha_of "$ref"); [ -n "$cur" ] || die "no branch $ref in $REPO"
[ "$cur" = "$old" ] || die "$ref is at ${cur:0:12}, not at OLD (${old:0:12}): nothing was moved"
[ "$(g rev-parse "$old^{tree}")" = "$(g rev-parse "$new^{tree}")" ] \
  || die "the trees of OLD (${old:0:12}) and NEW (${new:0:12}) differ: a rewrite recorded here changes no content (git diff $old $new); nothing was moved"
g update-ref -m "qargi ref record --rewrite: $WHY" "refs/heads/$ref" "$new" "$old" || die "could not move $ref (it changed meanwhile): nothing was moved"
journal_line "$REPO" "refs/heads/$ref" "$old" "$new" ref:rewrite '' "$WHY"
audit_log "ref:rewrite" "$PROJ $ref ${old:0:12} ${new:0:12}"
echo "moved $ref from ${old:0:12} to ${new:0:12} (the same tree) and journaled it as a rewrite: $WHY"
