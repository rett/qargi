#!/usr/bin/env bash
# shellcheck disable=SC2154  # REPO and PROJ come from gitflow.sh (project_load)
# The lead's ref journal ($QARGI_STATE/ref-journal.jsonl), written by hand where no flow verb did the move.
#
#   ref.sh record --rewrite REF OLD NEW --why TEXT [--project P]
#       The lead rewrote an agent branch (reworded a message, split or squashed commits, dropped a trailer) without changing what
#       it holds: REF (agent/NAME or refs/heads/agent/NAME) moves from OLD to NEW only when the trees of OLD and NEW are identical
#       (git rev-parse OLD^{tree}) and REF is at OLD now (the move is a compare-and-swap: update-ref REF NEW OLD). The move is
#       journaled with the reason (verb ref:rewrite, why TEXT), so `qargi local verify` and `local clean` of a run prepared before
#       it accept it and name it as a rewrite, and `local clean`, `local list`, `lead compact-check` and `feature finish` follow a recorded run's applied tip to NEW (lib/merged.py).
#       Nothing else changes: no working tree (the trees are the same), no other ref, nothing on origin. The lead's verb: the guard
#       refuses it to a member.
#
#   ref.sh note REF[@SHA]... [--why TEXT] [--project P]
#       The lead made a branch by hand (git branch, git switch -c) or pushed one (git push: the branch is new on origin). Each REF (a branch NAME, or
#       origin/NAME for the branch NAME of origin, whose live value is asked) is journaled (verb ref:note) from absent to what it is now, or, when an
#       earlier note of it exists, from where that note left it (a second push of the same branch). Nothing is moved or created. The line leads from an
#       absent ref (or from the lead's own earlier note), so `local verify` and `local clean` of a run prepared before accept the creation of the ref and
#       name it a ref the lead noted; a ref that already existed when the run was prepared is not explained by it (the journal does not start where that
#       ref was), nor is a ref nobody noted. A second note of a ref is refused when the value of the earlier note is not an ancestor of the current one (the
#       ref was rewritten since, which the lead must inspect; ref record --rewrite records a rewrite of an agent branch that keeps its tree). The note prints
#       the author and the subject of the tip. REF@SHA (SHA of 7 to 40 hex digits) notes REF only while it is at SHA: it pins what the lead looked at or made.
#       The lead's verb: the guard refuses it to a member.
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
USAGE="usage: qargi ref record --rewrite REF OLD NEW --why \"TEXT\" [--project P] | qargi ref note REF[@SHA]... [--why \"TEXT\"] [--project P]"
case $verb in record|note) ;; *) usage_die "$USAGE";; esac
if [ "$verb" = note ]; then
  [ "${#ARGS[@]}" -ge 1 ] || usage_die "ref note takes one or more REF (a branch NAME, or origin/NAME for a branch of origin); $USAGE"
  [ -z "$MODE" ] || usage_die "ref note takes no --rewrite; $USAGE"
  . "$(dirname "$0")/gitflow.sh"
  project_load
  jf=$DA_STATE/ref-journal.jsonl
  rp=$(readlink -f "$REPO" 2>/dev/null) || rp=$REPO
  uk=''; if g remote get-url origin >/dev/null 2>&1; then uk=$(url_key "$(g remote get-url origin)"); fi
  bad=0
  for a in "${ARGS[@]}"; do
    pin=''; if [[ $a =~ ^(.+)@([0-9a-fA-F]{7,40})$ ]]; then a=${BASH_REMATCH[1]}; pin=${BASH_REMATCH[2]}; pin=${pin,,}; fi
    side=local br=$a
    case $a in
      refs/remotes/origin/?*) side=remote br=${a#refs/remotes/origin/};;
      origin/?*) side=remote br=${a#origin/};;
      refs/heads/?*) br=${a#refs/heads/};;
    esac
    if ! git check-ref-format "refs/heads/$br"; then echo "qargi: '$a' is not a branch name; nothing was noted for it" >&2; bad=1; continue; fi
    if [ "$side" = local ]; then
      cur=$(sha_of "$br"); [ -n "$cur" ] || { echo "qargi: no branch $br in $REPO; nothing was noted for it" >&2; bad=1; continue; }
    else
      [ -n "$uk" ] || { echo "qargi: $REPO has no origin; nothing was noted for $a" >&2; bad=1; continue; }
      remote_tip "$br"
      case $RSTATE in
        found) cur=$RTIP;;
        absent) echo "qargi: origin has no branch $br (asked live); nothing was noted for it" >&2; bad=1; continue;;
        *) echo "qargi: origin could not be asked about $br (${RWHY:-no answer}); nothing was noted for it" >&2; bad=1; continue;;
      esac
    fi
    if [ -n "$pin" ] && [[ $cur != "$pin"* ]]; then
      echo "qargi: $a is at ${cur:0:12}, not at $pin: it moved since you looked; nothing was noted for it" >&2; bad=1; continue
    fi
    # from absent, or from where the lead's last note of this ref left it
    old=''
    if [ -f "$jf" ]; then
      old=$(jq -sr --arg r "$rp" --arg ref "refs/heads/$br" --arg side "$side" --arg u "$uk" \
        '[ .[] | select(type == "object" and .verb == "ref:note" and .repo == $r and .ref == $ref and (if $side == "remote" then .remote == "origin" and .url == $u else (has("remote") | not) end)) ] | last | .new // empty' "$jf" 2>/dev/null) || old=''
    fi
    [ "$old" != "$cur" ] || { echo "$a is at ${cur:0:12} as your last note left it: nothing to note"; continue; }
    if [ -n "$old" ]; then   # a second note continues the line only along a fast-forward: a rewrite between the notes is not the lead's to accept unseen
      g merge-base --is-ancestor "$old" "$cur" 2>/dev/null; arc=$?
      if [ "$arc" = 1 ]; then
        echo "qargi: $a is not a fast-forward of your last note (${old:0:12} is not an ancestor of ${cur:0:12}): it was rewritten since. Nothing was noted for it; inspect it first (git log $old..$cur, git diff $old $cur)." >&2
        echo "qargi: a rewrite of an agent branch that keeps its tree is recorded with: qargi ref record --rewrite REF $old $cur --why \"TEXT\"" >&2
        bad=1; continue
      elif [ "$arc" != 0 ]; then
        echo "qargi: $a: cannot tell whether your last note (${old:0:12}) is an ancestor of ${cur:0:12} (a commit is not in $REPO; fetch it); nothing was noted for it" >&2; bad=1; continue
      fi
    fi
    if [ "$side" = local ]; then journal_line "$REPO" "refs/heads/$br" "$old" "$cur" ref:note '' "$WHY"
    else journal_push "refs/heads/$br" "$old" "$cur" ref:note; fi
    audit_log "ref:note" "$PROJ $a ${cur:0:12}"
    tip=$(g log -1 --format='%an: %s' "$cur" 2>/dev/null | LC_ALL=C tr -d '\000-\037\177') || tip=''
    [ -z "$tip" ] || tip=" (tip by $tip)"
    if [ -n "$old" ]; then echo "noted $a: ${old:0:12} to ${cur:0:12} (after your earlier note)$tip"; else echo "noted $a: created at ${cur:0:12}$tip"; fi
  done
  [ "$bad" = 0 ] || exit 1
  exit 0
fi
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
