#!/usr/bin/env bash
# Feature branches, by the git-flow rules: cut from develop, merged back into develop with --no-ff when the feature is done.
# A feature is as broad as you like (a theme, not a task): the lead merges the verified series of each related task into it,
# and the whole test suite runs once, when the feature is complete. Nothing reaches develop before that.
#
#   feature.sh start NAME [--purpose TEXT] [--worktree] [--project P]
#                                                  feature/NAME from develop (a local branch); the purpose says what is related. --worktree also
#                                                  makes its worktree at <worktrees.root>/feature/NAME and prints the path
#   feature.sh list [--project P]                  the open features: purpose, distance from develop, and the files two features both change
#   feature.sh park [--project P]                  refresh the parking branch (answers repo.parking_branch, default scratch) in the main checkout:
#                                                  checkout -B it onto develop; refused when the tree is dirty or the branch has commits develop lacks
#   feature.sh sync NAME [--project P]             merge develop into the feature (do it before its checkpoint, after another feature landed). With the answer
#                                                  release.changelog.numbered it warns of duplicate changelog item numbers (finish refuses them)
#   feature.sh merge NAME BRANCH [--project P]     merge a verified task branch into feature/NAME with --no-ff. NAME may instead be a detached
#                                                  long-lived branch (answers repo.detached): BRANCH must be an agent/* branch and the merge,
#                                                  local only, takes --plan T --approved W. A detached branch never meets develop, master,
#                                                  release, hotfix or feature branches: every merge between them is refused.
#   feature.sh status NAME [--project P]
#   feature.sh verify NAME [--project P]           the whole suite on the feature's head (the checkpoint before finishing)
#   feature.sh finish NAME [--project P] [--keep] [--plan T --approved W]
#                                                  merge into develop with --no-ff and delete the branch; push develop if an
#                                                  origin exists. Needs a passing run at the feature's head. A feature behind develop is refused; when
#                                                  both sides changed the same files, the message lists them and says to sync first. Refused, with
#                                                  the runs listed, while a run of the feature is open (not cleaned, discarded, closed or merged).
# The marshal (lib/marshal.sh) records who leads each feature: start makes you the lead, merge, sync, verify and finish ask it first
# (another live lead: refused, nothing changes; an anonymous identity or an unreachable marshal only warns), verify and finish keep
# your lease alive while they run, finish marks the record finished, and list and status show the lead.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
NAME_ARG='' EXTRA='' PROJ='' PLAN_ARG='' APPROVED='' KEEP='' RESOLVED='' PURPOSE='' WORKTREE=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --purpose) need_val "$1" $#; PURPOSE=$2; shift 2;; --worktree) WORKTREE=1; shift;;
    -*) usage_die "unknown option $1";;
    *) if [ -z "$NAME_ARG" ]; then NAME_ARG=$1; else EXTRA=$1; fi; shift;;
  esac
done
export PLAN_ARG   # need_plan reads it
if [ "$verb" = list ] || [ "$verb" = park ]; then NAME_ARG=-; fi
[ -n "$NAME_ARG" ] || usage_die "usage: qargi feature start|list|park|sync|merge|status|verify|finish NAME [BRANCH] [--project P]"
{ [ "$verb" = list ] || [ "$verb" = park ]; } || printf '%s' "$NAME_ARG" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#NAME_ARG}" -le 40 ] || die "'$NAME_ARG' is not a feature name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
case $NAME_ARG in master|develop) die "'$NAME_ARG' is a long-lived branch";; esac
export RESOLVED
[ -z "$WORKTREE" ] || [ "$verb" = start ] || die "--worktree belongs to feature start"
. "$(dirname "$0")/gitflow.sh"
# shellcheck disable=SC2154  # PROJ and TESTCMD come from project_load
project_load
# NAME is a feature, or (feature merge only) a detached long-lived branch of the answers (repo.detached): the target of a merge, no feature
DET=''
if [ "$verb" != list ] && [ "$verb" != park ]; then
  if is_detached "$NAME_ARG"; then
    [ "$verb" = merge ] || die "$NAME_ARG is a detached long-lived branch (repo.detached): it has no feature flow. Cut tasks from it (--base $NAME_ARG) and merge them with qargi feature merge $NAME_ARG BRANCH"
    DET=1
  else
    printf '%s' "$NAME_ARG" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#NAME_ARG}" -le 40 ] || die "'$NAME_ARG' is not a feature name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
    case $NAME_ARG in master|develop) die "'$NAME_ARG' is a long-lived branch";; esac
  fi
fi
BR=feature/$NAME_ARG
# merge_detached: feature merge DETACHED BRANCH -> an agent/* task branch merged into the detached branch with --no-ff, local only.
# A long-lived branch, so it takes a plan token and an approval like a merge into develop; no marshal record (it is no feature).
merge_detached() {
  local d=$NAME_ARG h t tok
  h=$(sha_of "$d"); [ -n "$h" ] || die "no detached branch $d (repo.detached names it, but the repository has no such branch)"
  case $EXTRA in agent/*) ;; *) die "only an agent/* task branch is merged into the detached branch $d (not $EXTRA)";; esac
  t=$(sha_of "$EXTRA"); [ -n "$t" ] || die "no local branch $EXTRA (apply the verified series to a branch first: /qargi-verify)"
  g merge-base --is-ancestor "$t" "$h" && die "$EXTRA is already in $d"
  run_warning "$EXTRA"
  detached_mix "$EXTRA" "$d"
  tok=$(printf '%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$d" "$h" "$EXTRA" "$t" | plan_token)
  echo "merge $EXTRA into the detached branch $d with --no-ff (local only: nothing is pushed)"
  show_incoming "$d" "$EXTRA"
  if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi feature merge $d $EXTRA --plan $tok --approved \"...\")"; return 0; fi
  need_plan "$tok"
  need_free "$d"
  merge_step "$h" "refs/heads/$EXTRA" "detached-${d//\//_}-merge-${EXTRA//\//_}" "Merge branch '$EXTRA' into $d"
  g update-ref "refs/heads/$d" "$MERGED" "$h" || die "could not move $d (it changed meanwhile)"
  journal_ref "$REPO" "refs/heads/$d" "$h" "$MERGED" feature:merge
  merge_forget "detached-${d//\//_}-merge-${EXTRA//\//_}"
  audit_log "feature:merge" "$PROJ $d $EXTRA"
  echo "merged $EXTRA into the detached branch $d ($(g rev-parse --short "$d"))"
}

# run_warning BRANCH -> a warning on stderr for each run of BRANCH (an agent/SLUG branch: the registry's line with that slug, of this repository, not
# cleaned, its directory still there) that has no passing verify (neither the registry's mark nor RUN/verified): its refs were never checked. The
# merge goes on; the lead decides.
run_warning() {
  local slug=${1#agent/} rp d line
  reg_load; rp=$(readlink -f -- "$REPO" 2>/dev/null) || rp=$REPO
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do
    line=${LRUNS[$d]}
    [ "$(jq -r --arg s "$slug" --arg p "$rp" 'select(.slug == $s and ((.repo // "") == "" or .repo == $p) and ((.cleaned // "") == "")) | "x"' <<<"$line" 2>/dev/null)" = x ] || continue
    [ -d "$d" ] || continue
    [ -z "$(jq -r '.verified // ""' <<<"$line" 2>/dev/null)" ] && [ ! -f "$d/verified" ] || continue
    echo "qargi: warning: the run $d of $1 has no passing verify (qargi local verify $d): the refs of the repository were never checked for it" >&2
  done
}
# open_run_gate NAME -> dies, listing them, when a run of feature/NAME is open: prepared and not verified, verified and not applied, or applied and not
# merged (lead_usage.py open-runs, the list compact-check reads). A cleaned run, a discarded one (clean --discard), a closed one (local close
# --applied-by-am) and an applied run whose branch is merged are not open. Nothing is changed.
open_run_gate() {
  local out rc=0 d sl ro st n=0 lines=''
  out=$(python3 -I "$(dirname "$0")/lead_usage.py" open-runs --state "$DA_STATE" --conf "$DA_CONF" --project "$PROJ" --feature "$1" </dev/null 2>/dev/null) || rc=$?
  [ "$rc" != 0 ] || return 0
  [ "$rc" = 1 ] || { echo "qargi: warning: could not list the open runs of feature/$1 (lead_usage.py exited $rc): finishing goes on without that check" >&2; return 0; }
  while IFS=$'\t' read -r d sl ro st; do
    [ -n "$d" ] || continue
    n=$((n + 1)); lines+="  $d ($ro $sl): $st"$'\n'
  done <<<"$out"
  die "feature $1 has $n open run(s); finish it when they are taken in or dropped:"$'\n'"${lines%$'\n'}"$'\n'"close each one: qargi local clean RUN (after its work is applied and merged; --discard drops it on purpose), or qargi local close RUN --applied-by-am when you applied its patches by hand (git am). Nothing was changed."
}
# sync_numbers REF: with the answer release.changelog.numbered, a warning when the changelog at REF has duplicate item numbers (the sync is done either way;
# feature finish refuses until they are renumbered)
sync_numbers() {
  local r
  r=$(changelog_check "$1") || { echo "qargi: warning: $BR has duplicate changelog item numbers (release.changelog.numbered); feature finish refuses until they are renumbered:" >&2; printf '%s\n' "$r" | sed 's/^/  /' >&2; }
}

case $verb in
  park)
    # the main checkout rests on the parking branch (answers repo.parking_branch, default scratch), so qargi can move develop under it
    branch_exists develop || die "no develop branch to park on"
    [ -z "$(git -C "$REPO" status --porcelain)" ] || die "the main checkout $REPO has uncommitted changes: commit or discard them, then qargi feature park"
    w=$(held "$PARK"); [ -z "$w" ] || [ "$(readlink -f "$w")" = "$(readlink -f "$REPO")" ] || die "$PARK is checked out in $w, not in the main checkout: leave it there first"
    old=$(sha_of "$PARK")
    if [ -n "$old" ] && [ "$(g rev-list --count "develop..$PARK")" != 0 ]; then
      echo "qargi: $PARK has commit(s) that develop lacks (not refreshed):" >&2
      g log --format='  %h %s' "develop..$PARK" | head -20 >&2
      die "re-implement them with an agent task based on develop (qargi local prepare --base develop), or keep them on a branch of their own (git branch NAME $PARK), then run qargi feature park again"
    fi
    git -C "$REPO" checkout -q -B "$PARK" develop || die "could not check out $PARK in $REPO"
    journal_ref "$REPO" "refs/heads/$PARK" "$old" "$(sha_of "$PARK")" feature:park
    echo "$REPO is on $PARK at develop ($(g rev-parse --short develop))$([ -n "$old" ] || echo "; created $PARK")";;
  start)
    branch_exists "$BR" && die "$BR exists already"
    branch_exists develop || die "no develop branch to start from"
    # a branch of this name that only exists on origin is somebody's work: ask the live remote, not the tracking refs
    remote_tip "$BR"
    case $RSTATE in
      found) die "origin already has $BR (at ${RTIP:0:7}) and there is no local $BR: pick it up with git fetch origin && git branch $BR origin/$BR, or choose another name";;
      unchecked)
        echo "qargi: remote not checked ($RWHY)" >&2
        g rev-parse -q --verify "refs/remotes/origin/$BR" >/dev/null && die "origin/$BR was seen at the last fetch and origin cannot be asked now: fetch it or choose another name";;
    esac
    if [ -n "$WORKTREE" ]; then wtp=$WT_ROOT/$BR; [ ! -e "$wtp" ] || die "$wtp exists already: nothing was created"; fi
    g branch "$BR" develop
    journal_ref "$REPO" "refs/heads/$BR" "" "$(sha_of "$BR")" feature:start
    # the marshal keeps the record (purpose, started) and makes this identity the lead; the feature exists either way
    marshal_start "$PROJ" "$NAME_ARG" "$PURPOSE" || echo "qargi: warning: the marshal record of $NAME_ARG was not written (see above); $BR exists" >&2
    echo "created $BR from develop ($(g rev-parse --short "$BR")); merge each verified task into it: qargi feature merge $NAME_ARG BRANCH"
    echo "tasks branch from here: dispatch them with --base $BR"
    if [ -n "$WORKTREE" ]; then
      mkdir -p "$(dirname "$wtp")" && g worktree add -q "$wtp" "$BR" || die "$BR was created, but its worktree at $wtp could not be"
      echo "worktree: $wtp"
    fi
    push_feature "$BR";;
  merge)
    [ -z "$DET" ] || { [ -n "$EXTRA" ] || die "usage: qargi feature merge $NAME_ARG BRANCH"; merge_detached; exit 0; }
    marshal_gate "$NAME_ARG"
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    [ -n "$EXTRA" ] || usage_die "usage: qargi feature merge $NAME_ARG BRANCH"
    t=$(g rev-parse -q --verify "refs/heads/$EXTRA" || true); [ -n "$t" ] || die "no local branch $EXTRA (apply the verified series to a branch first: /qargi-verify)"
    g merge-base --is-ancestor "$t" "$h" && die "$EXTRA is already in $BR"
    run_warning "$EXTRA"
    detached_mix "$EXTRA" "$BR"
    need_free_wt "$BR"
    merge_step "$h" "refs/heads/$EXTRA" "feature-$NAME_ARG-merge-${EXTRA//\//_}" "Merge branch '$EXTRA' into $BR"
    g update-ref "refs/heads/$BR" "$MERGED" "$h" || die "could not move $BR (it changed meanwhile)"
    wt_follow "$BR" "$MERGED"
    journal_ref "$REPO" "refs/heads/$BR" "$h" "$MERGED" feature:merge
    merge_forget "feature-$NAME_ARG-merge-${EXTRA//\//_}"
    echo "merged $EXTRA into $BR ($(g rev-parse --short "$BR")); the earlier full-suite result no longer applies to the new head"
    push_feature "$BR"
    lead_advice --feature "$NAME_ARG";;
  sync)
    marshal_gate "$NAME_ARG"
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    g merge-base --is-ancestor develop "$BR" && { echo "$BR already contains develop"; sync_numbers "$h"; exit 0; }
    detached_mix develop "$BR"
    need_free_wt "$BR"
    merge_step "$h" refs/heads/develop "feature-$NAME_ARG-sync" "Merge branch 'develop' into $BR"
    g update-ref "refs/heads/$BR" "$MERGED" "$h" || die "could not move $BR (it changed meanwhile)"
    wt_follow "$BR" "$MERGED"
    journal_ref "$REPO" "refs/heads/$BR" "$h" "$MERGED" feature:sync
    merge_forget "feature-$NAME_ARG-sync"
    echo "merged develop into $BR ($(g rev-parse --short "$BR")); the earlier full-suite result no longer applies to the new head"
    sync_numbers "$MERGED"
    push_feature "$BR";;
  list)
    branches=$(g for-each-ref --format='%(refname:short)' 'refs/heads/feature/*')
    [ -n "$branches" ] || { echo "no open features (qargi feature start NAME)"; wt_outside_report; exit 0; }
    # the lead of each feature, from the marshal's brief lines "NAME  lead=ID  ..."; unavailable -> no suffix
    leads=$("$(dirname "$0")/marshal.sh" status --all --brief --project "$PROJ" 2>/dev/null) || leads=''
    for b in $branches; do
      n=${b#feature/}; pj=$DA_STATE/features/$PROJ-$n.json
      ld=$(printf '%s\n' "$leads" | awk -v n="$n" '$1 == n && $2 ~ /^lead=/ {print substr($2, 6); exit}')
      echo "$b: $(g rev-list --count "develop..$b") ahead, $(g rev-list --count "$b..develop") behind develop; $([ -f "$pj" ] && jq -r '.purpose | if . == "" then "no purpose recorded" else . end' "$pj" || echo "no purpose recorded")${ld:+ [lead $ld]}"
      g diff --name-only "develop...$b" > "$DA_STATE/.files.$$.$n" 2>/dev/null || true
    done
    any=''
    for a in $branches; do for b in $branches; do
      [ "$a" \< "$b" ] || continue
      ov=$(comm -12 <(sort "$DA_STATE/.files.$$.${a#feature/}") <(sort "$DA_STATE/.files.$$.${b#feature/}") | head -10)
      if [ -n "$ov" ]; then any=1; echo "overlap $a / $b: $(echo "$ov" | tr '\n' ' ')(expect a conflict whichever lands second; keep related work in one feature)"; fi
    done; done
    rm -f "$DA_STATE"/.files.$$.*
    [ -n "$any" ] || echo "no file is changed by more than one open feature"
    wt_outside_report;;
  status)
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    marshal_touch "$PROJ" "$NAME_ARG"   # the lead's own command keeps its lease (a read of the feature, never a refusal)
    echo "feature $NAME_ARG of $PROJ on $BR at $(g rev-parse --short "$BR"), $(g rev-list --count "develop..$BR") commit(s) ahead of develop, $(g rev-list --count "$BR..develop") behind"
    g log --format='  %h %s' "develop..$BR" | head -20
    v=$(verified "$BR"); if [ -z "$v" ]; then echo "full suite: not run on this branch"; elif [ "${v%% *}" = "$h" ]; then echo "full suite: ${v##* } at this head"; else echo "full suite: ${v##* } at an older head"; fi
    remote_report "$BR"; remote_report develop
    wt_outside_report
    if mout=$("$(dirname "$0")/marshal.sh" status "$NAME_ARG" --project "$PROJ" 2>/dev/null); then printf '%s\n' "$mout"; fi;;
  verify)
    marshal_gate "$NAME_ARG"
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    [ -n "$TESTCMD" ] || die "no test_command in the answers for $PROJ: qargi project set $PROJ test_command '...'"
    worktree "$h"
    echo "running the whole suite on $BR at $(g rev-parse --short "$BR"): $TESTCMD"
    hold_begin "$NAME_ARG"; busy_begin verify "$NAME_ARG"
    t0=$SECONDS
    if run_suite; then res=pass; else res=fail; fi
    busy_end; hold_end
    record_suite "$BR" "$h" "$res" "$((SECONDS - t0))"
    echo "full suite: $res at $(g rev-parse --short "$BR")"; [ "$res" = pass ];;
  finish)
    marshal_gate "$NAME_ARG"
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    open_run_gate "$NAME_ARG"
    # behind develop, with files both sides changed since they parted: a sync is due, and the files are named. A feature behind develop
    # with no such file is not refused here: the check on develop below says the same without the list.
    if branch_exists develop && ! g merge-base --is-ancestor develop "$BR"; then
      ov=$(comm -12 <(g diff --name-only --no-renames "develop...$BR" | sort) <(g diff --name-only --no-renames "$BR...develop" | sort))
      [ -z "$ov" ] || die "$BR is behind develop, and both changed these files since they parted:"$'\n'"$(printf '%s\n' "$ov" | head -20 | sed 's/^/  /')"$'\n'"run qargi feature sync $NAME_ARG first (resolve any conflict), verify again, then finish. Nothing was changed."
    fi
    cdups=$(changelog_check "$BR") || die "$BR has duplicate changelog item numbers (release.changelog.numbered):"$'\n'"$(printf '%s\n' "$cdups" | sed 's/^/  /')"$'\n'"Nothing was changed."
    [ "$(verified "$BR")" = "$h pass" ] || die "the whole suite has no passing run at the head of $BR (qargi feature verify $NAME_ARG); the branch must not move after it"
    d0=$(sha_of develop); [ -n "$d0" ] || die "no develop branch"
    g merge-base --is-ancestor "$d0" "$BR" || die "develop has moved on since $BR was cut: qargi feature sync $NAME_ARG, verify again, then finish (the run must have seen what develop now holds)"
    if g remote get-url origin >/dev/null 2>&1; then
      g fetch -q origin 2>/dev/null || die "fetch failed"
      if g rev-parse -q --verify refs/remotes/origin/develop >/dev/null; then g merge-base --is-ancestor origin/develop develop || die "develop is behind or differs from origin/develop: reconcile them first"; fi
    fi
    detached_mix "$BR" develop
    [ -z "$(wt_of "$BR")" ] || need_free_wt "$BR"   # a dirty worktree of the branch is found before the plan, not after the merge
    # branches.delete_merged local+remote: the feature branch is deleted on origin too, when origin has it (asked live) and everything on
    # it is in the feature. The plan says so and its token covers the remote tip, so a branch that moved there is a new plan.
    rdel='' rnote=''
    if [ -z "$KEEP" ] && [ "$DELETE_MERGED" = local+remote ] && g remote get-url origin >/dev/null 2>&1; then
      remote_tip "$BR"
      case $RSTATE in
        found) if g merge-base --is-ancestor "$RTIP" "$h" 2>/dev/null; then rdel=$RTIP; else rnote="origin/$BR (${RTIP:0:7}) has commits the feature lacks: it is not deleted there"; fi;;
        unchecked) rnote="origin could not be asked ($RWHY): origin/$BR is not deleted";;
      esac
    fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$BR" "$h" "$d0" "$KEEP" "$DELETE_MERGED" "$rdel" | plan_token)
    echo "finish feature $NAME_ARG of $PROJ: merge $BR into develop with --no-ff${KEEP:+, keep the branch}$([ -n "$KEEP" ] || echo ", delete the branch")${rdel:+, delete origin/$BR (${rdel:0:7})}$(g remote get-url origin >/dev/null 2>&1 && echo ", push develop")"
    [ -z "$rnote" ] || echo "  note: $rnote"
    remote_report develop; remote_report "$BR"
    show_incoming develop "$BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi feature finish $NAME_ARG${KEEP:+ --keep} --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"
    need_free develop
    need_free_wt "$BR"
    hold_begin "$NAME_ARG"
    k="feature-$NAME_ARG-into-develop"
    merge_step "$d0" "refs/heads/$BR" "$k" "Merge branch '$BR' into develop"
    # develop contains the feature, so the merge has the tree the whole suite just passed: the same run stands for develop's new head
    if g remote get-url origin >/dev/null 2>&1; then
      rd0=$(remote_was develop)   # what origin has (fetched above): the journal line of the push starts there
      g push -q --atomic origin "$MERGED:refs/heads/develop" || die "the push failed; nothing was changed locally or on origin (run it again)"
      journal_push refs/heads/develop "$rd0" "$MERGED" feature:finish
    fi
    g update-ref refs/heads/develop "$MERGED" "$d0" || die "origin has the merge but develop moved locally meanwhile: git fetch origin, then check develop against origin"
    journal_ref "$REPO" refs/heads/develop "$d0" "$MERGED" feature:finish
    merge_forget "$k"
    jq -c --arg s "$MERGED" '.sha = $s' "$(rec "$BR")" > "$(rec develop)"
    if [ -z "$KEEP" ]; then wt_drop "$BR"; g update-ref -d "refs/heads/$BR" "$h"; journal_ref "$REPO" "refs/heads/$BR" "$h" "" feature:finish; fi
    audit_log "feature:finish" "$PROJ $NAME_ARG"
    hold_end
    marshal_finish "$PROJ" "$NAME_ARG" || echo "qargi: warning: the marshal record of $NAME_ARG was not marked finished (see above); the merge is done" >&2
    echo "merged $BR into develop ($(g rev-parse --short develop))$([ -n "$KEEP" ] || echo "; deleted $BR"); the whole-suite run carries over to develop"
    parking_follow
    if g remote get-url origin >/dev/null 2>&1; then
      if [ -n "$rdel" ]; then
        if g push -q --force-with-lease="refs/heads/$BR:$rdel" origin ":refs/heads/$BR" 2>/dev/null; then journal_push "refs/heads/$BR" "$rdel" "" feature:finish; echo "deleted origin/$BR"
        else echo "note: could not delete origin/$BR (it moved, or origin refused)" >&2; fi
      fi
      echo "pushed develop"
    fi
    lead_advice;;
  *) usage_die "usage: qargi feature start|list|park|sync|merge|status|verify|finish NAME [BRANCH] [--project P]";;
esac
