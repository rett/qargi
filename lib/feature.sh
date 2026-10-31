#!/usr/bin/env bash
# Feature branches, by the git-flow rules: cut from develop, merged back into develop with --no-ff when the feature is done.
# A feature is as broad as you like (a theme, not a task): the lead merges the verified series of each related task into it,
# and the whole test suite runs once, when the feature is complete. Nothing reaches develop before that.
#
#   feature.sh start NAME [--purpose TEXT] [--project P]   feature/NAME from develop (a local branch); the purpose says what is related
#   feature.sh list [--project P]                  the open features: purpose, distance from develop, and the files two features both change
#   feature.sh sync NAME [--project P]             merge develop into the feature (do it before its checkpoint, after another feature landed)
#   feature.sh merge NAME BRANCH [--project P]     merge a verified task branch into feature/NAME with --no-ff
#   feature.sh status NAME [--project P]
#   feature.sh verify NAME [--project P]           the whole suite on the feature's head (the checkpoint before finishing)
#   feature.sh finish NAME [--project P] [--keep] [--plan T --approved W]
#                                                  merge into develop with --no-ff and delete the branch; push develop if an
#                                                  origin exists. Needs a passing run at the feature's head.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
NAME_ARG='' EXTRA='' PROJ='' PLAN_ARG='' APPROVED='' KEEP='' RESOLVED='' PURPOSE=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) PROJ=$2; shift 2;; --plan) PLAN_ARG=$2; shift 2;; --approved) APPROVED=$2; shift 2;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --purpose) PURPOSE=$2; shift 2;;
    -*) die "unknown option $1";;
    *) if [ -z "$NAME_ARG" ]; then NAME_ARG=$1; else EXTRA=$1; fi; shift;;
  esac
done
export PLAN_ARG   # need_plan reads it
if [ "$verb" = list ]; then NAME_ARG=-; fi
[ -n "$NAME_ARG" ] || die "usage: qargi feature start|list|sync|merge|status|verify|finish NAME [BRANCH] [--project P]"
[ "$verb" = list ] || printf '%s' "$NAME_ARG" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#NAME_ARG}" -le 40 ] || die "'$NAME_ARG' is not a feature name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
case $NAME_ARG in master|develop) die "'$NAME_ARG' is a long-lived branch";; esac
export RESOLVED
. "$(dirname "$0")/gitflow.sh"
# shellcheck disable=SC2154  # PROJ and TESTCMD come from project_load
project_load
BR=feature/$NAME_ARG

case $verb in
  start)
    branch_exists "$BR" && die "$BR exists already"
    branch_exists develop || die "no develop branch to start from"
    g branch "$BR" develop
    mkdir -p "$DA_STATE/features"; jq -nc --arg p "$PURPOSE" --arg t "$(now)" '{purpose:$p, started:$t}' > "$DA_STATE/features/$PROJ-$NAME_ARG.json"
    echo "created $BR from develop ($(g rev-parse --short "$BR")); merge each verified task into it: qargi feature merge $NAME_ARG BRANCH"
    echo "tasks branch from here: dispatch them with --base $BR";;
  merge)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    [ -n "$EXTRA" ] || die "usage: qargi feature merge $NAME_ARG BRANCH"
    t=$(g rev-parse -q --verify "refs/heads/$EXTRA" || true); [ -n "$t" ] || die "no local branch $EXTRA (apply the verified series to a branch first: /qargi-verify)"
    g merge-base --is-ancestor "$t" "$h" && die "$EXTRA is already in $BR"
    need_free "$BR"
    merge_step "$h" "refs/heads/$EXTRA" "feature-$NAME_ARG-merge-${EXTRA//\//_}" "Merge branch '$EXTRA' into $BR"
    g update-ref "refs/heads/$BR" "$MERGED" "$h" || die "could not move $BR (it changed meanwhile)"
    merge_forget "feature-$NAME_ARG-merge-${EXTRA//\//_}"
    echo "merged $EXTRA into $BR ($(g rev-parse --short "$BR")); the earlier full-suite result no longer applies to the new head";;
  sync)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    g merge-base --is-ancestor develop "$BR" && { echo "$BR already contains develop"; exit 0; }
    need_free "$BR"
    merge_step "$h" refs/heads/develop "feature-$NAME_ARG-sync" "Merge branch 'develop' into $BR"
    g update-ref "refs/heads/$BR" "$MERGED" "$h" || die "could not move $BR (it changed meanwhile)"
    merge_forget "feature-$NAME_ARG-sync"
    echo "merged develop into $BR ($(g rev-parse --short "$BR")); the earlier full-suite result no longer applies to the new head";;
  list)
    branches=$(g for-each-ref --format='%(refname:short)' 'refs/heads/feature/*')
    [ -n "$branches" ] || { echo "no open features (qargi feature start NAME)"; exit 0; }
    for b in $branches; do
      n=${b#feature/}; pj=$DA_STATE/features/$PROJ-$n.json
      echo "$b: $(g rev-list --count "develop..$b") ahead, $(g rev-list --count "$b..develop") behind develop; $([ -f "$pj" ] && jq -r '.purpose | if . == "" then "no purpose recorded" else . end' "$pj" || echo "no purpose recorded")"
      g diff --name-only "develop...$b" > "$DA_STATE/.files.$$.$n" 2>/dev/null || true
    done
    any=''
    for a in $branches; do for b in $branches; do
      [ "$a" \< "$b" ] || continue
      ov=$(comm -12 <(sort "$DA_STATE/.files.$$.${a#feature/}") <(sort "$DA_STATE/.files.$$.${b#feature/}") | head -10)
      if [ -n "$ov" ]; then any=1; echo "overlap $a / $b: $(echo "$ov" | tr '\n' ' ')(expect a conflict whichever lands second; keep related work in one feature)"; fi
    done; done
    rm -f "$DA_STATE"/.files.$$.*
    [ -n "$any" ] || echo "no file is changed by more than one open feature";;
  status)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    echo "feature $NAME_ARG of $PROJ on $BR at $(g rev-parse --short "$BR"), $(g rev-list --count "develop..$BR") commit(s) ahead of develop, $(g rev-list --count "$BR..develop") behind"
    g log --format='  %h %s' "develop..$BR" | head -20
    v=$(verified "$BR"); if [ -z "$v" ]; then echo "full suite: not run on this branch"; elif [ "${v%% *}" = "$h" ]; then echo "full suite: ${v##* } at this head"; else echo "full suite: ${v##* } at an older head"; fi;;
  verify)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    [ -n "$TESTCMD" ] || die "no test_command in the answers for $PROJ: qargi project set $PROJ test_command '...'"
    worktree "$h"
    echo "running the whole suite on $BR at $(g rev-parse --short "$BR"): $TESTCMD"
    if (cd "$WT" && bash -c "$TESTCMD"); then res=pass; else res=fail; fi
    jq -nc --arg s "$h" --arg r "$res" --arg t "$(now)" --arg c "$TESTCMD" '{sha:$s, result:$r, at:$t, command:$c}' > "$(rec "$BR")"
    echo "full suite: $res at $(g rev-parse --short "$BR")"; [ "$res" = pass ];;
  finish)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    [ "$(verified "$BR")" = "$h pass" ] || die "the whole suite has no passing run at the head of $BR (qargi feature verify $NAME_ARG); the branch must not move after it"
    d0=$(sha_of develop); [ -n "$d0" ] || die "no develop branch"
    g merge-base --is-ancestor "$d0" "$BR" || die "develop has moved on since $BR was cut: qargi feature sync $NAME_ARG, verify again, then finish (the run must have seen what develop now holds)"
    if g remote get-url origin >/dev/null 2>&1; then
      g fetch -q origin 2>/dev/null || die "fetch failed"
      if g rev-parse -q --verify refs/remotes/origin/develop >/dev/null; then g merge-base --is-ancestor origin/develop develop || die "develop is behind or differs from origin/develop: reconcile them first"; fi
    fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$BR" "$h" "$d0" "$KEEP" | plan_token)
    echo "finish feature $NAME_ARG of $PROJ: merge $BR into develop with --no-ff${KEEP:+, keep the branch}$([ -n "$KEEP" ] || echo ", delete the branch")$(g remote get-url origin >/dev/null 2>&1 && echo ", push develop")"
    show_incoming develop "$BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi feature finish $NAME_ARG${KEEP:+ --keep} --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    need_free develop "$BR"
    k="feature-$NAME_ARG-into-develop"
    merge_step "$d0" "refs/heads/$BR" "$k" "Merge branch '$BR' into develop"
    # develop contains the feature, so the merge has the tree the whole suite just passed: the same run stands for develop's new head
    if g remote get-url origin >/dev/null 2>&1; then
      g push -q --atomic origin "$MERGED:refs/heads/develop" || die "the push failed; nothing was changed locally or on origin (run it again)"
    fi
    g update-ref refs/heads/develop "$MERGED" "$d0" || die "origin has the merge but develop moved locally meanwhile: git fetch origin, then check develop against origin"
    merge_forget "$k"
    jq -c --arg s "$MERGED" '.sha = $s' "$(rec "$BR")" > "$(rec develop)"
    [ -n "$KEEP" ] || g update-ref -d "refs/heads/$BR" "$h"
    audit_log "feature:finish" "$PROJ $NAME_ARG"
    echo "merged $BR into develop ($(g rev-parse --short develop))$([ -n "$KEEP" ] || echo "; deleted $BR"); the whole-suite run carries over to develop"
    if g remote get-url origin >/dev/null 2>&1; then
      if [ -z "$KEEP" ] && g rev-parse -q --verify "refs/remotes/origin/$BR" >/dev/null; then g push -q origin --delete "$BR" || echo "note: could not delete origin/$BR" >&2; fi
      echo "pushed develop"
    fi;;
  *) die "usage: qargi feature start|list|sync|merge|status|verify|finish NAME [BRANCH] [--project P]";;
esac
