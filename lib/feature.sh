#!/usr/bin/env bash
# Feature branches, by the git-flow rules: cut from develop, merged back into develop with --no-ff when the feature is done.
# A feature is as broad as you like (a theme, not a task): the lead merges the verified series of each related task into it,
# and the whole test suite runs once, when the feature is complete. Nothing reaches develop before that.
#
#   feature.sh start NAME [--purpose TEXT] [--worktree] [--assume-unreachable-ok] [--project P]
#                                                  feature/NAME from develop (a local branch); the purpose says what is related. --worktree also
#                                                  makes its worktree at <worktrees.root>/feature/NAME and prints the path
#   feature.sh list [--project P]                  the open features: purpose, distance from develop, and the files two features both change
#   feature.sh park [--project P]                  refresh the parking branch (answers repo.parking_branch, default scratch) in the main checkout:
#                                                  checkout -B it onto develop; refused for tracked changes or commits develop lacks
#   feature.sh sync NAME [--project P]             merge develop into the feature (do it before its checkpoint, after another feature landed). With the answer
#                                                  release.changelog.numbered it warns of duplicate changelog item numbers (finish refuses them)
#   feature.sh merge NAME BRANCH [--project P]     merge a verified task branch into feature/NAME with --no-ff. NAME may instead be a detached
#                                                  long-lived branch (answers repo.detached): BRANCH must be an agent/* branch and the merge,
#                                                  local only, takes --plan T --approved W. A detached branch never meets develop, master,
#                                                  release, hotfix or feature branches: every merge between them is refused.
#   feature.sh status NAME [--project P]
#   feature.sh verify NAME [--project P] [--waive-environment PARTS --plan T --approved W]
#                                                  the whole suite on the feature's head (the checkpoint before finishing). With the answer
#                                                  verify.environment the suite starts through lib/suite_env.py; a part of it that cannot be
#                                                  applied refuses the run and prints a token (also when the run is refused after a passing
#                                                  attempt), and PARTS (signals, fds, tty, cpu) waives the refused parts for this run only
#                                                  (recorded, audited, shown again by status). Only a refusal yields a token, which is good for
#                                                  one run at that head; nothing refused, nothing to waive; not in a member run
#   feature.sh finish NAME [--project P] [--keep] [--plan T --approved W] [--dry-run]
#                                                  merge into develop with --no-ff and delete the branch; push develop if an
#                                                  origin exists and the answer branches.push_develop is not false (the plan's first line says which).
#                                                  Needs a passing run at the feature's head. A feature behind develop is refused; when
#                                                  both sides changed the same files, the message lists them and says to sync first. Refused, with
#                                                  the runs listed, while a run of the feature is open (not cleaned, discarded, closed or merged).
#                                                  --dry-run (the verb's behaviour; the flag is declared in the help by a later change): the plan and its token, and with --plan
#                                                  the refusals the apply would meet, changing nothing (QARGI_DRY=1: no lease renewed, no lock, no audit line, no file in the state
#                                                  directory, no ref). Origin is asked with ls-remote and never fetched ("not fetched"). Each refusal is printed as the apply prints it,
#                                                  with dry=1 first in the detail of the contract line where the refusal has a code; the last line is `dry-run: N would refuse; nothing
#                                                  was changed`, the status 0, or 1 when any would.
# The marshal (lib/marshal.sh) records who leads each feature: start makes you the lead, merge, sync, verify and finish ask it first
# (another live lead: refused, nothing changes; an anonymous identity only warns). With the shared refs backend a remote that cannot be
# asked is a refusal too (exit 3, nothing changes) unless the verb is given --assume-unreachable-ok, which goes on and writes the audit
# line marshal:unreachable-ok; a marshal that is missing or fails in some other way still only warns. verify and finish keep
# your lease alive while they run, finish marks the record finished, and list and status show the lead.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
# shellcheck disable=SC2034  # QARGI_VERB is read by refuse and notice (lib/lib.sh): the verb of the contract line of a refusal
QARGI_VERB="feature $verb"
NAME_ARG='' EXTRA='' PROJ='' PLAN_ARG='' APPROVED='' KEEP='' RESOLVED='' PURPOSE='' WORKTREE='' ASSUME_UNREACHABLE='' WAIVE_ENV='' WAIVE_SET='' DRY_RUN=''
# shellcheck disable=SC2034  # WAIVE_ENV and WAIVE_SET are read by suite_env_prepare (gitflow.sh)
while [ $# -gt 0 ]; do
  case $1 in
    --waive-environment) need_val "$1" $#; WAIVE_ENV=$2; WAIVE_SET=1; shift 2;;
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;; --keep) KEEP=1; shift;; --resolved) RESOLVED=1; shift;; --purpose) need_val "$1" $#; PURPOSE=$2; shift 2;; --worktree) WORKTREE=1; shift;; --assume-unreachable-ok) ASSUME_UNREACHABLE=1; shift;; --dry-run) DRY_RUN=1; shift;;
    -*) usage_die "unknown option $1";;
    *) if [ -z "$NAME_ARG" ]; then NAME_ARG=$1; else EXTRA=$1; fi; shift;;
  esac
done
export PLAN_ARG   # need_plan reads it
if [ "$verb" = list ] || [ "$verb" = park ]; then NAME_ARG=-; fi
[ -n "$NAME_ARG" ] || usage_die "usage: qargi feature start|list|park|sync|merge|status|verify|finish NAME [BRANCH] [--project P]"
{ [ "$verb" = list ] || [ "$verb" = park ]; } || printf '%s' "$NAME_ARG" | grep -Eq '^[a-z0-9]+(-[a-z0-9]+)*$' && [ "${#NAME_ARG}" -le 40 ] || die "'$NAME_ARG' is not a feature name: kebab-case, lower-case letters, digits and single '-' (at most 40)"
case $NAME_ARG in master|develop) die "'$NAME_ARG' is a long-lived branch";; esac
case $verb in status|verify) actor_check feature "feature $verb" "$NAME_ARG" || exit $?;; esac   # a coordinator label: the feature this verb acts on is its own, checked where the name is resolved
export RESOLVED
[ -z "$WORKTREE" ] || [ "$verb" = start ] || die "--worktree belongs to feature start"
[ -z "$WAIVE_SET" ] || [ "$verb" = verify ] || usage_die "--waive-environment belongs to feature verify"
[ -z "$DRY_RUN" ] || [ "$verb" = finish ] || usage_die "--dry-run belongs to feature finish"
case $verb in start|sync|merge|verify|finish) ;; *) [ -z "$ASSUME_UNREACHABLE" ] || die "--assume-unreachable-ok belongs to the verbs that ask the marshal first: feature start, sync, merge, verify and finish";; esac
. "$(dirname "$0")/gitflow.sh"
PSF=/dev/null DRYTMP=''   # PSF: the text of the plan, kept for a dry run (tee in the plan of finish), so --plan can be compared with it; DRYTMP: a scratch directory of the dry run
[ -z "$DRY_RUN" ] || { dry_on; PSF=$(mktemp) || fail "could not make a temporary file"; }   # QARGI_DRY=1 before anything reads the project: from here the helpers that write stop, and g passes only what reads
feat_exit() {   # the one EXIT handler: what gitflow.sh cleans up, the temporary files of a dry run, and in a dry run the last line
  local rc=$?
  [ "$PSF" = /dev/null ] || rm -f "$PSF"; [ -z "$DRYTMP" ] || rm -rf "$DRYTMP"
  on_exit
  dry_finish "$rc"
}
trap feat_exit EXIT
# shellcheck disable=SC2154  # PROJ and TESTCMD come from project_load
project_load "feature $verb"
# the declared gates (the answer gates; lib/gates.py) replace test_command in the verbs that read or make the whole-suite record: the feature tier
case $verb in status|verify|finish) gates_load feature;; esac
# verify.environment (lib/suite_env.py): the declaration, and the id that `verified` selects the suite record by; status only reports a finding
case $verb in status) suite_env_load report;; verify|finish) suite_env_load refuse;; esac
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
  tok=$(printf '%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$d" "$h" "$EXTRA" "$t" | plan_token --basis "project:name detached:ref head:sha task:ref task-head:sha" --verb "feature merge" --target "$PROJ:$d")
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
# open_run_gate NAME -> refuses (feature-runs-open: the count and the names of the runs, and a `more:` line that lists each run with the command that closes it) when a run of
# feature/NAME is open: prepared and not verified, verified and not applied, or applied and not merged (lead_usage.py open-runs, the list compact-check reads). A cleaned run, a
# discarded one (clean --discard), a closed one (local close --applied-by-am) and an applied run whose branch is merged are not open. Nothing is changed. In a dry run the refusal
# is listed and the checks that follow go on (it is declared independent of them). A reader that fails is a failure, not this refusal.
# shellcheck disable=SC2034  # REFUSE_MORE and DRY_INDEP are read by refuse (lib/gitflow.sh)
open_run_gate() {
  local out rc=0 d sl ro st cmd extra n=0 lines='' rname
  local -a names=()
  # The strict command validates and enumerates one snapshot. This gate does not
  # coordinate new preparation through the eventual merge.
  out=$(pymod lead_usage open-runs --state "$DA_STATE" --conf "$DA_CONF" --project "$PROJ" --feature "$1" </dev/null 2>&1) || rc=$?
  if [ "$rc" = 0 ] && [ -z "$out" ]; then return 0; fi
  [ "$rc" = 1 ] && [ -n "$out" ] || die "could not list the open runs of feature/$1 (lead_usage.py exited $rc): $out; finish refused. Nothing was changed."
  while IFS=$'\t' read -r d sl ro st cmd extra; do
    [ -n "$d" ] || continue
    [ -n "$sl" ] && [ -n "$ro" ] && [ -n "$st" ] && [ -n "$cmd" ] && [ -z "$extra" ] \
      || die "could not list the open runs of feature/$1 (invalid reader output); finish refused. Nothing was changed."
    n=$((n + 1)); lines+="  $d ($ro $sl): $st"$'\n'"    close it: ${cmd:-qargi local clean $d}"$'\n'
    # the name of a run is its directory's: a value the lead chose, so it is shown, and only a digest of the list reaches the contract line (no comma: it separates the names)
    rname=${d%/}; rname=$(printf '%s' "${rname##*/}" | tr -d '[:cntrl:]' | tr ',' '_' | cut -c1-200); names+=("${rname:-run}")
  done <<<"$out"
  [ "$n" -gt 0 ] || die "could not list the open runs of feature/$1 (empty reader output); finish refused. Nothing was changed."
  REFUSE_MORE="feature $1 has $n open run(s); finish it when they are taken in or dropped:"$'\n'"${lines%$'\n'}"$'\n'"A read-only run (a report, no patches) closes with qargi local clean RUN; a run of work with qargi local clean RUN after its work is applied and merged (--discard drops it on purpose), or qargi local close RUN --applied-by-am when you applied its patches by hand (git am). Nothing was changed."
  DRY_INDEP=1
  refuse feature-runs-open verb="feature finish" count="$n" runs="$(IFS=,; echo "${names[*]}")"
  DRY_INDEP=''
}
# sync_numbers REF: with the answer release.changelog.numbered, a warning when the changelog at REF has duplicate item numbers (the sync is done either way;
# feature finish refuses until they are renumbered)
sync_numbers() {
  local r
  r=$(changelog_check "$1") || { echo "qargi: warning: $BR has duplicate changelog item numbers (release.changelog.numbered); feature finish refuses until they are renumbered:" >&2; printf '%s\n' "$r" | sed 's/^/  /' >&2; }
}

# feature_finish_tail -> everything `finish` does once the merge is made and (with a push) pushed: the journal line, develop, the suite record, the deletion of
# the branch, the audit line, the marshal, the notices. It reads d0 rd0 MERGED h k pushd pushwhy rdel KEEP (set by the finish, or loaded from the intent
# record by feature_finish_resume) and marks each step in the record (gitflow.sh, intent_*), so a run that was cut off does only what is left. The record goes last.
feature_finish_tail() {
  local key=feature-$NAME_ARG
  if ! intent_marked "$key" journal; then
    [ -z "$pushd" ] || journal_push refs/heads/develop "$rd0" "$MERGED" feature:finish
    intent_mark "$key" journal
  fi
  if ! intent_marked "$key" refs; then
    move_ref refs/heads/develop "$MERGED" "$d0" || die "origin has the merge but develop moved locally meanwhile: git fetch origin, then check develop against origin"
    journal_ref "$REPO" refs/heads/develop "$d0" "$MERGED" feature:finish
    merge_forget "$k"
    # develop contains the feature, so the merge has the tree the whole suite just passed: the same run stands for develop's new head
    [ ! -f "$(rec "$BR")" ] || jq -c --arg s "$MERGED" '.sha = $s' "$(rec "$BR")" > "$(rec develop)"
    intent_mark "$key" refs
  fi
  if [ -z "$KEEP" ] && ! intent_marked "$key" branch; then
    # commits the lead made on the branch with git moved it without a journal line, so the journal is first brought up to the merged head (journal_reach):
    # a run prepared before such a commit then finds the deletion too
    if [ "$(sha_of "$BR")" = "$h" ]; then wt_drop "$BR"; g update-ref -d "refs/heads/$BR" "$h"; journal_reach local "refs/heads/$BR" "$h" feature:finish; journal_ref "$REPO" "refs/heads/$BR" "$h" "" feature:finish
    elif branch_exists "$BR"; then echo "note: $BR is at $(sha_of "$BR") now, not at the merged ${h:0:7}: it is not deleted" >&2; fi
    intent_mark "$key" branch
  fi
  if ! intent_marked "$key" audit; then audit_log "feature:finish" "$PROJ $NAME_ARG"; intent_mark "$key" audit; fi
  hold_end
  marshal_finish "$PROJ" "$NAME_ARG" || echo "qargi: warning: the marshal record of $NAME_ARG was not marked finished (see above); the merge is done" >&2
  echo "merged $BR into develop ($(g rev-parse --short develop))$([ -n "$KEEP" ] || echo "; deleted $BR"); the whole-suite run carries over to develop"
  parking_follow
  if g remote get-url origin >/dev/null 2>&1; then
    if [ -n "$rdel" ]; then
      if g push -q --force-with-lease="refs/heads/$BR:$rdel" origin ":refs/heads/$BR" 2>/dev/null; then journal_reach remote "refs/heads/$BR" "$rdel" feature:finish; journal_push "refs/heads/$BR" "$rdel" "" feature:finish; echo "deleted origin/$BR"
      else echo "note: could not delete origin/$BR (it moved, or origin refused)" >&2; fi
    fi
  fi
  if [ -n "$pushd" ]; then echo "pushed develop"; else echo "develop was not pushed ($pushwhy)"; fi
  lead_advice
  intent_clear "$key"
}
# feat_dry_end TOKEN LABELS [CHECK...] -> the end of the plan of a dry run (--dry-run), once the plan and its token line are printed; it ends the verb. Without --plan it says what would
# invalidate the plan (its labels, the words plan_token --basis keeps). With --plan it does what the apply does first: need_plan, so plan-stale names the labels that moved (the plan of
# --plan was stored when it was shown; this one is not stored in a dry run, so it is put in a scratch state beside a copy of that one), then the CHECK command (the apply's checks that
# only read). The refusals are printed as the apply prints them, with dry=1 in the detail of the contract line.
feat_dry_end() {
  local tok=$1 labels=$2
  shift 2
  if [ -z "$PLAN_ARG" ]; then echo "invalidated by: ${labels// /, }"; exit 0; fi
  DRYTMP=$(mktemp -d) || fail "could not make a temporary directory"; mkdir "$DRYTMP/plans"
  [ ! -f "$DA_STATE/plans/$PLAN_ARG.json" ] || cp "$DA_STATE/plans/$PLAN_ARG.json" "$DRYTMP/plans/"
  QARGI_STATE=$DRYTMP python3 -I "$QARGI_TOOL/lib/refusal.py" basis scratch "$tok" "$labels" < "$PSF" 2>/dev/null || true
  DA_STATE=$DRYTMP need_plan "$tok"
  [ $# = 0 ] || "$@"
  [ "$DRYN" != 0 ] || echo "the plan $tok is the one shown: the apply of finish would go on"
  echo "not run in a dry run: the finish itself (the merge into develop, where a conflict is found when it is made, the push of develop and the deletion of the branches)"
  exit 0
}
# feat_finish_checks -> what the apply of finish checks after the token and before it merges: develop and the branch are not checked out anywhere (a clean worktree of qargi's may hold the branch)
feat_finish_checks() { need_free develop; need_free_wt "$BR"; }
# feat_resume_checks -> the same for the completion of a finish that was cut off (feature_finish_resume): the merge commit of the record is here, develop and the branch are free
feat_resume_checks() {
  g cat-file -e "$MERGED^{commit}" 2>/dev/null || die "the merge commit of the interrupted finish is not in $REPO: nothing was changed"
  need_free develop; [ -n "$KEEP" ] || need_free_wt "$BR"
}
# marshal_dry NAME -> the marshal's answer without a write: no lease is renewed (no --renew) and nothing is fetched (--no-fetch: a shared marshal is read from the cache this machine holds).
# A refusal (status 1, the message already printed) ends the verb, as marshal_gate's does; any other failure is a warning.
marshal_dry() {
  local rc=0
  marshal_py "$PROJ" check "$1" --no-fetch >/dev/null || rc=$?
  [ "$rc" = 0 ] && return 0
  [ "$rc" != 1 ] || exit 1
  echo "qargi: warning: the marshal could not be asked (status $rc); going on" >&2
}
# feature_finish_resume -> a finish of the feature that was cut off after its push (intent_probe said so): shows what is left, and with --plan and --approved
# does it (feature_finish_tail). The values are the record's, not the command line's; the plan token covers the record.
feature_finish_resume() {
  local key=feature-$NAME_ARG f tok
  f=$(intent_file "$key")
  d0=$(jq -r '.refs[0].local_old' "$f"); rd0=$(jq -r '.refs[0].origin_old' "$f"); MERGED=$(jq -r '.refs[0].new' "$f")
  h=$(jq -r '.ctx.head' "$f"); KEEP=$(jq -r '.ctx.keep' "$f"); pushd=$(jq -r '.ctx.pushd' "$f"); pushwhy=$(jq -r '.ctx.pushwhy' "$f"); rdel=$(jq -r '.ctx.rdel' "$f"); k=$(jq -r '.ctx.k' "$f")
  tok=$(jq -S -c 'del(.done)' "$f" | tee "$PSF" | plan_token --basis "record:name" --verb "feature finish" --target "$PROJ:$NAME_ARG")
  echo "finish feature $NAME_ARG of $PROJ was cut off$([ -n "$pushd" ] && echo ": origin holds the merge into develop (asked just now)" || echo " (develop was not to be pushed)"); finishing it:"
  echo "  develop ${d0:0:7} -> ${MERGED:0:7}${KEEP:+; $BR is kept}$([ -n "$KEEP" ] || echo "; $BR is deleted")${rdel:+; origin/$BR is deleted (${rdel:0:7})}"
  echo "  steps already done: $(jq -r '.done | if length == 0 then "none" else join(", ") end' "$f")"
  # as in the plan of the finish: the commits made with git that the deletions still to come take into the journal
  [ -n "$KEEP" ] || intent_marked "$key" branch || [ "$(sha_of "$BR")" != "$h" ] || journal_reach_plan local "refs/heads/$BR" "$h"
  [ -z "$rdel" ] || journal_reach_plan remote "refs/heads/$BR" "$rdel"
  if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi feature finish $NAME_ARG --plan $tok --approved \"...\")"; [ -n "$DRY_RUN" ] || exit 0; fi
  [ -z "$DRY_RUN" ] || feat_dry_end "$tok" "record" feat_resume_checks
  need_plan "$tok"
  feat_resume_checks
  hold_begin "$NAME_ARG"
  feature_finish_tail
}

# stale_why BRANCH RAN -> why the whole-suite result at RAN no longer stands for BRANCH: the commits on its first-parent line since RAN
# (a merge of develop is a sync, a merge of another branch is a task merge), oldest first, at most five
stale_why() {
  local sha subj n=0 total what
  if ! g merge-base --is-ancestor "$2" "$1" 2>/dev/null; then echo "  why: the run's commit is not in the history of $1 (the branch was reset or rebuilt since)"; return 0; fi
  total=$(g rev-list --first-parent --count "$2..$1")
  echo "  why: $1 moved after that run by $total commit(s):"
  while read -r sha subj; do
    case $subj in
      "Merge branch 'develop' into "*) what="develop was synced in";;
      "Merge branch '"*) what="a branch was merged in";;
      *) what="a commit";;
    esac
    echo "    $sha $subj ($what)"; n=$((n + 1))
  done < <(g log --first-parent --reverse --format='%h %s' "$2..$1" | head -5)
  [ "$total" -le "$n" ] || echo "    ... and $((total - n)) more"
}

case $verb in
  park)
    # the main checkout rests on the parking branch (answers repo.parking_branch, default scratch), so qargi can move develop under it
    branch_exists develop || die "no develop branch to park on"
    [ -z "$(git -C "$REPO" status --porcelain --untracked-files=no)" ] || die "the main checkout $REPO has uncommitted changes: commit or discard them, then qargi feature park"
    w=$(held "$PARK"); [ -z "$w" ] || [ "$(readlink -f "$w")" = "$(readlink -f "$REPO")" ] || die "$PARK is checked out in $w, not in the main checkout: leave it there first"
    old=$(sha_of "$PARK")
    if [ -n "$old" ] && [ "$(g rev-list --count "develop..$PARK")" != 0 ]; then
      echo "qargi: $PARK has commit(s) that develop lacks (not refreshed):" >&2
      g log --format='  %h %s' "develop..$PARK" | head -20 >&2
      die "re-implement them with an agent task based on develop (qargi local prepare --base develop), or keep them on a branch of their own (git branch NAME $PARK), then run qargi feature park again"
    fi
    git -C "$REPO" checkout -q --no-overwrite-ignore -B "$PARK" develop || die "could not check out $PARK in $REPO"
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
    # the marshal keeps the record (purpose, started) and makes this identity the lead. It is asked first: a shared marshal that cannot be reached
    # refuses the start (exit 3) before anything is made, unless --assume-unreachable-ok; any other failure leaves the feature without a record
    mrc=0; marshal_flow marshal_start "$PROJ" "$NAME_ARG" "$PURPOSE" || mrc=$?
    if [ "$mrc" = 3 ] && [ -z "$ASSUME_UNREACHABLE" ]; then marshal_unreachable_refuse "$NAME_ARG"; fi
    g branch "$BR" develop
    journal_ref "$REPO" "refs/heads/$BR" "" "$(sha_of "$BR")" feature:start
    [ "$mrc" = 0 ] || echo "qargi: warning: the marshal record of $NAME_ARG was not written (see above); $BR exists" >&2
    echo "created $BR from develop ($(g rev-parse --short "$BR")); merge each verified task into it: qargi feature merge $NAME_ARG BRANCH"
    echo "tasks branch from here: dispatch them with --base $BR"
    if [ -n "$WORKTREE" ]; then
      mkdir -p "$(dirname "$wtp")" && g worktree add -q "$wtp" "$BR" || die "$BR was created, but its worktree at $wtp could not be"
      echo "worktree: $wtp"
    fi
    push_feature "$BR";;
  merge)
    [ -z "$DET" ] || { [ -n "$EXTRA" ] || usage_die "usage: qargi feature merge $NAME_ARG BRANCH"; merge_detached; exit 0; }
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
    v=$(verified "$BR"); ran=${v%% *}
    if [ -z "$v" ]; then echo "full suite: not run on this branch"; echo "  next: qargi feature verify $NAME_ARG"
    elif [ "$ran" = "$h" ]; then echo "full suite: ${v##* } at this head"; gates_line "$BR"
    else echo "full suite: ${v##* } at an older head ($(g rev-parse --short "$ran" 2>/dev/null || echo "$ran"))"; stale_why "$BR" "$ran"; echo "  next: qargi feature verify $NAME_ARG"; fi
    suite_env_status "$BR" "qargi feature verify $NAME_ARG"
    remote_report "$BR"; remote_report develop
    wt_outside_report
    if mout=$("$(dirname "$0")/marshal.sh" status "$NAME_ARG" --project "$PROJ" 2>/dev/null); then printf '%s\n' "$mout"; fi;;
  verify)
    marshal_gate "$NAME_ARG"
    h=$(sha_of "$BR"); [ -n "$h" ] || die "no branch $BR (qargi feature start $NAME_ARG)"
    if [ -n "$GATES" ]; then gates_need feature; else [ -n "$TESTCMD" ] || die "no test_command in the answers for $PROJ: qargi project set $PROJ test_command '...'"; fi
    suite_env_prepare "qargi feature verify $NAME_ARG" "$BR" "$h"   # the launcher's attempt and the waiver, before anything is made (verify.environment)
    worktree "$h"
    suite_env_claim_now   # the waiver is used here, after the worktree and before the log (a refusal above spends nothing)
    echo "running the whole suite on $BR at $(g rev-parse --short "$BR"): $TESTCMD"
    [ -z "$SUITE_ENV" ] || echo "verify.environment: on (id $SUITE_ENV_ID): the suite starts through the launcher$([ -z "$ENV_WAIVE" ] || echo ", waiving $ENV_WAIVE")"
    gates_note
    other_runs_warning
    hold_begin "$NAME_ARG"; busy_begin verify "$NAME_ARG"
    t0=$SECONDS
    if run_suite_logged "feature-$NAME_ARG"; then res=pass; else res=fail; fi
    busy_end; hold_end
    suite_env_settle
    record_suite "$BR" "$h" "$res" "$((SECONDS - t0))"
    echo "full suite: $res at $(g rev-parse --short "$BR")$(suite_env_note "$BR")"
    [ "$res" = pass ] || suite_failure_report
    [ "$res" = pass ];;
  finish)
    if [ -z "$DRY_RUN" ]; then marshal_gate "$NAME_ARG"
    else
      # a dry run renews no lease and takes no lock; the marshal is asked only for a branch that exists (a record of a branch that is gone is abandoned by the question)
      [ -z "$(sha_of "$BR")" ] || marshal_dry "$NAME_ARG"
    fi
    # a finish that was cut off after its push left a record (gitflow.sh, intent_*): complete it, or drop it when the push never happened
    [ -n "$DRY_RUN" ] || intent_lock "feature-$NAME_ARG"
    if intent_has "feature-$NAME_ARG"; then
      intent_probe "feature-$NAME_ARG"
      if [ "$IP" = old ]; then
        # the record is removed with the apply (after the plan token is checked), never by a plan alone
        STALE_REC=1
        if [ -z "$APPROVED" ]; then echo "note: an earlier finish of $NAME_ARG stopped before anything reached origin or moved here; its record is removed when this plan is applied" >&2; fi
      else
        feature_finish_resume; exit 0
      fi
    fi
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
      otip=''
      if [ -n "$DRY_RUN" ]; then
        # not fetched: origin is asked with ls-remote, and develop there is compared when its commit is already here
        echo "not fetched: origin is asked with ls-remote (the apply fetches it first)"
        remote_tip develop
        case $RSTATE in
          found)
            if g cat-file -e "$RTIP^{commit}" 2>/dev/null; then otip=$RTIP
            else echo "origin/develop is at ${RTIP:0:7}, which this repository does not have yet: the apply fetches it, then compares it with develop"; fi;;
          unchecked) fail "fetch failed (origin could not be asked: $RWHY)";;
        esac
      else
        g fetch -q origin 2>/dev/null || die "fetch failed"
        otip=$(g rev-parse -q --verify refs/remotes/origin/develop || true)
      fi
      [ -z "$otip" ] || g merge-base --is-ancestor "$otip" develop || die "develop is behind or differs from origin/develop: reconcile them first"
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
    # whether develop is pushed: origin exists and the answer branches.push_develop is not false (default true)
    pushd='' pushwhy=''
    if ! g remote get-url origin >/dev/null 2>&1; then pushwhy="the repository has no origin"
    elif [ "$PUSH_DEVELOP" = false ]; then pushwhy="branches.push_develop is false"
    else pushd=1; fi
    tok=$(printf '%s\n%s\n%s\n%s\n%s\n%s\n%s\n%s\n' "$PROJ" "$BR" "$h" "$d0" "$KEEP" "$DELETE_MERGED" "$rdel" "$pushd" | tee "$PSF" | plan_token --basis "project:name branch:ref head:sha develop:sha keep:label delete-merged:label origin-branch:sha push:label" --verb "feature finish" --target "$PROJ:$NAME_ARG")
    if [ -n "$pushd" ]; then echo "will push develop to origin"; else echo "local only, will not push ($pushwhy)"; fi
    echo "finish feature $NAME_ARG of $PROJ: merge $BR into develop with --no-ff${KEEP:+, keep the branch}$([ -n "$KEEP" ] || echo ", delete the branch")${rdel:+, delete origin/$BR (${rdel:0:7})}${pushd:+, push develop}"
    [ -z "$rnote" ] || echo "  note: $rnote"
    # the commits the lead made with git on the branch, which the deletion takes into the journal (journal_reach): how many, and from where to where
    [ -n "$KEEP" ] || journal_reach_plan local "refs/heads/$BR" "$h"
    [ -z "$rdel" ] || journal_reach_plan remote "refs/heads/$BR" "$rdel"
    remote_report develop; remote_report "$BR"
    suite_env_waived_line "$BR"
    show_incoming develop "$BR"; backlog_note develop "$BR"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi feature finish $NAME_ARG${KEEP:+ --keep} --plan $tok --approved \"...\")"; [ -n "$DRY_RUN" ] || exit 0; fi
    [ -z "$DRY_RUN" ] || feat_dry_end "$tok" "project branch head develop keep delete-merged origin-branch push" feat_finish_checks
    need_plan "$tok"
    if [ -n "${STALE_REC:-}" ]; then intent_drop "feature-$NAME_ARG"; echo "note: an earlier finish of $NAME_ARG stopped before anything reached origin or moved here; its record is removed and this one starts again" >&2; fi
    feat_finish_checks
    hold_begin "$NAME_ARG"
    k="feature-$NAME_ARG-into-develop"
    merge_step "$d0" "refs/heads/$BR" "$k" "Merge branch '$BR' into develop"
    # the intent record comes before the push: a death after the push is finished by the next run (feature_finish_resume)
    rd0=''; [ -z "$pushd" ] || rd0=$(remote_was develop)   # what origin has (fetched above): the journal line of the push starts there
    intent_write "feature-$NAME_ARG" "$(jq -nc --arg name "$NAME_ARG" --arg project "$PROJ" --argjson pushed "$([ -n "$pushd" ] && echo true || echo false)" \
      --arg d0 "$d0" --arg rd0 "$rd0" --arg m "$MERGED" --arg h "$h" --arg keep "$KEEP" --arg pushd "$pushd" --arg pushwhy "$pushwhy" --arg rdel "$rdel" --arg k "$k" \
      '{schema:1, verb:"feature:finish", project:$project, name:$name, pushed:$pushed, refs:[{ref:"refs/heads/develop", local_old:$d0, origin_old:$rd0, new:$m}],
        ctx:{head:$h, keep:$keep, pushd:$pushd, pushwhy:$pushwhy, rdel:$rdel, k:$k}, done:[]}')"
    if [ -n "$pushd" ]; then
      # a push that exits non-zero may still have reached origin (the answer was lost): the record stays, and the next run asks origin
      g push -q --atomic origin "$MERGED:refs/heads/develop" \
        || die "the push reported a failure, and origin may hold the merge anyway (develop here was not moved): run qargi feature finish $NAME_ARG again; it asks origin, then completes the finish or starts it over"
    fi
    feature_finish_tail;;
  *) usage_die "usage: qargi feature start|list|park|sync|merge|status|verify|finish NAME [BRANCH] [--project P]";;
esac
