#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ, DETACHED, PARK come from gitflow.sh (project_load)
# Branch housekeeping by the git-flow rules.
#
#   branch.sh prune [--project P] [--remote] [--plan T --approved W] [--dry-run]
#   branch.sh prune --agents [--project P] [--dry-run]
#       The merged agent/* and feature/* branches of the project, and the worktrees of the ones qargi made, as a plan and a token;
#       with --plan and --approved they are deleted. --remote adds the same branches on origin (asked live). A branch is merged when
#       it was merged with --no-ff into develop, into a branch of repo.long_lived or repo.detached (a feature or an agent branch), or into
#       an open feature/* (an agent branch), and is still in that branch's history; a branch that only sits at the tip of one of them
#       was never merged and is kept.
#       Never touched: master, develop, the branches of repo.long_lived and repo.detached, the parking branch, an unmerged branch, a
#       branch checked out in a worktree that qargi did not make (the main checkout, any worktree inside the repository, the runtime's own worktrees, one outside the root) or in a dirty one.
#       Nothing is pushed except the deletions on origin, each as a lease on the tip the plan showed.
#       --agents: the one deletion that is not gated. It deletes the merged agent/* branches of this repository, at once: it prints what it deletes (the plan), takes no token and no
#       approval, and is the lead's (a member run is refused, exit 2). Each branch is brought into the ref journal first (journal_reach: the commits made with git on it), then deleted
#       only if it is still at the tip the plan showed, then journaled as deleted (branch:prune). It deletes branches only, never a worktree: a branch held by any worktree is kept
#       ("held by worktree W; the gated prune removes it": git does not list the ignored files of a worktree, and the removal of the directory would take them), and so is a branch
#       whose journal does not reach its tip (a branch rewritten by hand, a journal line that is not JSON). Its tip stays reachable from the merge it was merged by. feature/* branches and --remote stay gated: --agents with --remote, --plan or --approved is a usage error (exit 2).
#       --dry-run (the verb's behaviour; the flag is declared in the help by a later change): the plan and its token, and with --plan the refusal the apply would meet (plan-stale
#       naming the labels that moved), changing nothing (QARGI_DRY=1: no ref, no file in the state directory, no audit line). With --remote origin is asked with ls-remote and never
#       fetched ("not fetched"). The last line is `dry-run: N would refuse; nothing was changed`, the status 0, or 1 when any would.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PROJ='' REMOTE='' PLAN_ARG='' APPROVED='' DRY_RUN='' AGENTS=''
USAGE="usage: qargi branch prune [--project P] [--remote] [--plan T --approved WORDS] [--dry-run] | qargi branch prune --agents [--project P] [--dry-run]"
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --remote) REMOTE=1; shift;; --dry-run) DRY_RUN=1; shift;; --agents) AGENTS=1; shift;;
    -*) usage_die "unknown option $1";;
    *) usage_die "$USAGE";;
  esac
done
export PLAN_ARG   # need_plan reads it
[ "$verb" = prune ] || usage_die "$USAGE"
if [ -n "$AGENTS" ]; then
  [ -z "$REMOTE" ] || usage_die "--agents is local only: the branches on origin (--remote) take a plan and an approval"
  [ -z "$PLAN_ARG$APPROVED" ] || usage_die "--agents takes no --plan or --approved: it deletes the merged agent/* branches here, at once; the feature branches and the branches on origin take a plan and an approval"
  # the lead's verb: a member run, or a call nested in an approved apply, is refused (nothing is deleted under a plan, so it must be the lead who runs it); a dry run deletes nothing
  if [ -z "$DRY_RUN" ]; then
    python3 -I -c 'import sys; sys.path.insert(0, sys.argv[1]); import marshal_refs as m; sys.exit(2 if m.in_member_run() else 0)' "$(dirname "$0")" && [ -z "${QARGI_NESTED:-}" ] \
      || { echo "qargi: branch prune --agents is not available in a member run or a nested call: it is the lead's" >&2; exit 2; }
  fi
fi
# shellcheck disable=SC2034  # QARGI_VERB is read by refuse and notice (lib/lib.sh): the verb of the contract line of a refusal
QARGI_VERB="branch $verb"
. "$(dirname "$0")/gitflow.sh"
PSF=/dev/null DRYTMP=''   # PSF: the text of the plan, kept for a dry run (tee in the plan), so --plan can be compared with it; DRYTMP: a scratch directory of the dry run
[ -z "$DRY_RUN" ] || { dry_on; PSF=$(mktemp) || fail "could not make a temporary file"; }   # QARGI_DRY=1 before anything reads the project: from here the helpers that write stop, and g passes only what reads
prune_exit() {   # the one EXIT handler: what gitflow.sh cleans up, the temporary files of a dry run, and in a dry run the last line
  local rc=$?
  [ "$PSF" = /dev/null ] || rm -f "$PSF"; [ -z "$DRYTMP" ] || rm -rf "$DRYTMP"
  on_exit
  dry_finish "$rc"
}
trap prune_exit EXIT
# prune_dry_end TOKEN LABELS -> the end of the plan of a dry run, once the plan and its token line are printed; it ends the verb. Without --plan it says what would invalidate the plan
# (its labels, the words plan_token --basis keeps). With --plan it does what the apply does first, need_plan: plan-stale names the labels that moved (the plan of --plan was stored
# when it was shown; this one is not stored in a dry run, so it is put in a scratch state beside a copy of that one).
prune_dry_end() {
  if [ -z "$PLAN_ARG" ]; then echo "invalidated by: ${2// /, }"; exit 0; fi
  DRYTMP=$(mktemp -d) || fail "could not make a temporary directory"; mkdir "$DRYTMP/plans"
  [ ! -f "$DA_STATE/plans/$PLAN_ARG.json" ] || cp "$DA_STATE/plans/$PLAN_ARG.json" "$DRYTMP/plans/"
  QARGI_STATE=$DRYTMP python3 -I "$QARGI_TOOL/lib/refusal.py" basis scratch "$1" "$2" < "$PSF" 2>/dev/null || true
  DA_STATE=$DRYTMP need_plan "$1"
  [ "$DRYN" != 0 ] || echo "the plan $1 is the one shown: the apply of branch prune would go on"
  echo "not run in a dry run: the deletion of the branches, of the worktrees qargi made and, with --remote, of the branches on origin"
  exit 0
}
project_load "branch $verb"
branch_exists develop || die "no develop branch"
LL=$(jq -r '(.repo.long_lived // [])[]' "$af")

protected() { # BRANCH -> 0 for a branch prune never touches
  case $1 in master|develop) return 0;; esac
  printf '%s\n%s\n%s\n' "$LL" "$DETACHED" "$PARK" | grep -Fxq -- "$1"
}
# the tips of everything merged with --no-ff into develop, into a branch of repo.long_lived or repo.detached that exists, or into an open
# feature: the second parents of their merge commits. A detached branch that origin accepts only through a pull request lags behind origin/BRANCH locally
# (the merge happens on origin), so the remote-tracking branch of each detached branch counts as a place a branch is merged into too; --remote fetches first.
if [ -n "$REMOTE" ]; then
  g remote get-url origin >/dev/null 2>&1 || die "the repository has no origin remote"
  command -v timeout >/dev/null 2>&1 || die "no timeout command to bound the check of origin"
  if [ -n "$DRY_RUN" ]; then echo "not fetched: origin is asked with ls-remote (the apply fetches it first); a branch of origin whose tip this repository does not have is kept below, and the apply may prune it"
  else g fetch -q origin 2>/dev/null || die "fetch failed"; fi
fi
mapfile -t feats < <(g for-each-ref --format='%(refname)' 'refs/heads/feature/*')
longs=()
while IFS= read -r l; do [ -z "$l" ] || [ "$l" = develop ] || ! branch_exists "$l" || longs+=("$l"); done < <(printf '%s\n%s\n' "$LL" "$DETACHED" | sort -u)
rems=()   # origin/BRANCH of each detached branch the repository has a remote-tracking branch of
while IFS= read -r l; do [ -z "$l" ] || ! g rev-parse -q --verify "refs/remotes/origin/$l" >/dev/null 2>&1 || rems+=("origin/$l"); done <<<"$DETACHED"
TIPS=$(g rev-list --merges --parents develop ${longs[@]+"${longs[@]}"} ${rems[@]+"${rems[@]/#/refs/remotes/}"} "${feats[@]}" | awk 'NF > 2 {for (i = 3; i <= NF; i++) print $i}' | sort -u)
merged_into() { # SHA KIND(agent|feature) -> the branch it is merged into, else nothing
  local sha=$1 t tt targets=develop f
  [ "${#longs[@]}" = 0 ] || targets="$targets ${longs[*]}"
  if [ "$2" = agent ]; then for f in "${feats[@]}"; do targets="$targets ${f#refs/heads/}"; done; fi
  printf '%s\n' "$TIPS" | grep -Fxq -- "$sha" || return 0
  for t in $targets; do
    tt=$(sha_of "$t")
    if [ "$sha" != "$tt" ] && g merge-base --is-ancestor "$sha" "$t" 2>/dev/null; then echo "$t"; return 0; fi
  done
  for t in ${rems[@]+"${rems[@]}"}; do
    tt=$(g rev-parse -q --verify "refs/remotes/$t" || true)
    if [ "$sha" != "$tt" ] && g merge-base --is-ancestor "$sha" "refs/remotes/$t" 2>/dev/null; then echo "$t"; return 0; fi
  done
}

TAB=$(printf '\t')
pats=('refs/heads/agent/*'); [ -n "$AGENTS" ] || pats+=('refs/heads/feature/*')   # --agents prunes the agent branches only
what='agent/* or feature/*'; [ -z "$AGENTS" ] || what='agent/*'
MAINWT=$(wt_path "$(g worktree list --porcelain | sed -n '1s/^worktree //p')")   # the main worktree: the first entry of the list
wt_made() { # PATH -> 0 for a worktree qargi made: under the root, and neither the main worktree nor inside the repository (a root may contain the repository; the runtime makes worktrees in it)
  local p; p=$(wt_path "$1")
  [ "$p" != "$MAINWT" ] && [ "$p" != "$(wt_path "$REPO")" ] || return 1
  case $p in "$(wt_path "$REPO")"/*) return 1;; esac
  wt_in_root "$1"
}
LOCAL=() REM=() KEPT=()   # tab-separated. LOCAL: branch, sha, merged into, worktree to remove (or empty); REM: branch, sha, merged into
while IFS= read -r ref; do
  b=${ref#refs/heads/}
  protected "$b" && continue
  sha=$(sha_of "$b"); kind=${b%%/*}
  into=$(merged_into "$sha" "$kind"); [ -n "$into" ] || continue
  w=$(held "$b")
  if [ -n "$w" ] && ! wt_made "$w"; then KEPT+=("$b: checked out in $w, which qargi did not make"); continue; fi
  if [ -n "$w" ] && [ -n "$(git -C "$w" status --porcelain 2>/dev/null)" ]; then KEPT+=("$b: its worktree $w has uncommitted changes"); continue; fi
  if [ -n "$AGENTS" ]; then
    # --agents deletes branches only: no worktree is removed (git status does not list ignored files, so a clean worktree may hold some), and a branch the journal does not reach keeps its deletion for the gated prune
    if [ -n "$w" ]; then KEPT+=("$b: held by worktree $w; the gated prune removes it"); continue; fi
    journal_reach_scan local "refs/heads/$b" "$sha"
    if [ -n "$REACH_NONE" ]; then KEPT+=("$b: its journal does not reach ${sha:0:7} ($REACH_NONE); the gated prune deletes it"); continue; fi
  fi
  LOCAL+=("$b$TAB$sha$TAB$into$TAB$w")
done < <(g for-each-ref --format='%(refname)' "${pats[@]}")

if [ -n "$REMOTE" ]; then
  rl=$(GIT_TERMINAL_PROMPT=0 timeout "${QARGI_REMOTE_TIMEOUT:-10}" git -C "$REPO" ls-remote --heads origin 'refs/heads/agent/*' 'refs/heads/feature/*' 2>/dev/null) || die "origin could not be asked (no answer within ${QARGI_REMOTE_TIMEOUT:-10}s, or it refused)"
  while read -r sha ref; do
    [ -n "$sha" ] || continue
    b=${ref#refs/heads/}
    protected "$b" && continue
    if ! g cat-file -e "$sha^{commit}" 2>/dev/null; then KEPT+=("origin/$b: its tip ${sha:0:7} is not fetched"); continue; fi
    into=$(merged_into "$sha" "${b%%/*}"); [ -n "$into" ] || continue
    REM+=("$b$TAB$sha$TAB$into")
  done <<<"$rl"
fi

if [ "${#LOCAL[@]}" = 0 ] && [ "${#REM[@]}" = 0 ]; then
  echo "no merged $what branches to prune${REMOTE:+ (local or on origin)}"
  for k in "${KEPT[@]}"; do echo "  kept $k"; done
  exit 0
fi

tok=$({ printf '%s\n' "$PROJ" "${REMOTE:-0}"; printf 'local %s\n' "${LOCAL[@]}"; printf 'remote %s\n' "${REM[@]}"; } | tee "$PSF" | plan_token --basis "project:name remote:count branches:ref" --verb "branch prune" --target "$PROJ:merged-branches${REMOTE:++origin}")
if [ -n "$AGENTS" ]; then echo "prune the merged agent branches of $PROJ: ${#LOCAL[@]} local (--agents: no plan token and no approval; each tip stays reachable from the merge that took it in)"
else echo "prune the merged branches of $PROJ: ${#LOCAL[@]} local, ${#REM[@]} on origin"; fi
for e in "${LOCAL[@]}"; do
  IFS=$TAB read -r b sha into w <<<"$e"
  echo "  delete local $b (${sha:0:7}, merged into $into)${w:+; remove its worktree $w}"
  journal_reach_plan local "refs/heads/$b" "$sha" '    '   # the commits made with git on it that the deletion takes into the journal: how many, from where to where
done
for e in "${REM[@]}"; do
  IFS=$TAB read -r b sha into <<<"$e"
  echo "  delete origin/$b (${sha:0:7}, merged into $into)"
  journal_reach_plan remote "refs/heads/$b" "$sha" '    '
done
for k in "${KEPT[@]}"; do echo "  kept $k"; done
if [ -n "$AGENTS" ]; then
  [ -z "$DRY_RUN" ] || { echo "the apply of --agents would delete these ${#LOCAL[@]} branches at once"; exit 0; }
  n=0
  for e in "${LOCAL[@]}"; do
    IFS=$TAB read -r b sha _ <<<"$e"   # no worktree: the plan kept every branch a worktree holds
    [ "$(sha_of "$b")" = "$sha" ] || { echo "qargi: warning: kept $b (it moved since the plan)" >&2; continue; }
    # first: the commits made with git on the branch are journaled before it goes, so a run prepared earlier is explained; a journal that no longer reaches the tip keeps the branch
    journal_catchup local "refs/heads/$b" "$sha" branch:prune || { echo "qargi: warning: kept $b (its journal does not reach ${sha:0:7}: $REACH_NONE)" >&2; continue; }
    if g update-ref -d "refs/heads/$b" "$sha"; then journal_ref "$REPO" "refs/heads/$b" "$sha" "" branch:prune; n=$((n + 1)); echo "deleted $b"
    else echo "qargi: warning: could not delete $b (it moved meanwhile)" >&2; fi
  done
  audit_log "branch:prune" "$PROJ $n local 0 remote (--agents)"
  echo "pruned $n local branch(es)"
  exit 0
fi
if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi branch prune${REMOTE:+ --remote} --plan $tok --approved \"...\")"; [ -n "$DRY_RUN" ] || exit 0; fi
[ -z "$DRY_RUN" ] || prune_dry_end "$tok" "project remote branches"
need_plan "$tok"
n=0 m=0
for e in "${LOCAL[@]}"; do
  IFS=$TAB read -r b sha _ w <<<"$e"
  [ -z "$w" ] || wt_drop "$b"
  # journal_reach first: a branch the lead committed on with git since the journal's last line of it is brought up to the pruned tip, so the deletion is found from there
  if g update-ref -d "refs/heads/$b" "$sha"; then journal_reach local "refs/heads/$b" "$sha" branch:prune; journal_ref "$REPO" "refs/heads/$b" "$sha" "" branch:prune; n=$((n + 1)); echo "deleted $b"
  else echo "qargi: warning: could not delete $b (it moved meanwhile)" >&2; fi
done
for e in "${REM[@]}"; do
  IFS=$TAB read -r b sha _ <<<"$e"
  if g push -q --force-with-lease="refs/heads/$b:$sha" origin ":refs/heads/$b" 2>/dev/null; then journal_reach remote "refs/heads/$b" "$sha" branch:prune; journal_push "refs/heads/$b" "$sha" "" branch:prune; m=$((m + 1)); echo "deleted origin/$b"
  else echo "qargi: warning: could not delete origin/$b (it moved, or origin refused)" >&2; fi
done
audit_log "branch:prune" "$PROJ $n local $m remote"
echo "pruned $n local and $m remote branch(es)"
