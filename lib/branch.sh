#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ, DETACHED, PARK come from gitflow.sh (project_load)
# Branch housekeeping by the git-flow rules.
#
#   branch.sh prune [--project P] [--remote] [--plan T --approved W]
#       The merged agent/* and feature/* branches of the project, and the worktrees of the ones qargi made, as a plan and a token;
#       with --plan and --approved they are deleted. --remote adds the same branches on origin (asked live). A branch is merged when
#       it was merged with --no-ff into develop, into a branch of repo.long_lived or repo.detached (a feature or an agent branch), or into
#       an open feature/* (an agent branch), and is still in that branch's history; a branch that only sits at the tip of one of them
#       was never merged and is kept.
#       Never touched: master, develop, the branches of repo.long_lived and repo.detached, the parking branch, an unmerged branch, a
#       branch checked out in a worktree that qargi did not make (the main checkout, the runtime's own worktrees) or in a dirty one.
#       Nothing is pushed except the deletions on origin, each as a lease on the tip the plan showed.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PROJ='' REMOTE='' PLAN_ARG='' APPROVED=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --remote) REMOTE=1; shift;;
    -*) usage_die "unknown option $1";;
    *) usage_die "usage: qargi branch prune [--project P] [--remote] [--plan T --approved WORDS]";;
  esac
done
export PLAN_ARG   # need_plan reads it
[ "$verb" = prune ] || usage_die "usage: qargi branch prune [--project P] [--remote] [--plan T --approved WORDS]"
. "$(dirname "$0")/gitflow.sh"
project_load
branch_exists develop || die "no develop branch"
LL=$(jq -r '(.repo.long_lived // [])[]' "$af")

protected() { # BRANCH -> 0 for a branch prune never touches
  case $1 in master|develop) return 0;; esac
  printf '%s\n%s\n%s\n' "$LL" "$DETACHED" "$PARK" | grep -Fxq -- "$1"
}
# the tips of everything merged with --no-ff into develop, into a branch of repo.long_lived or repo.detached that exists, or into an open
# feature: the second parents of their merge commits
mapfile -t feats < <(g for-each-ref --format='%(refname)' 'refs/heads/feature/*')
longs=()
while IFS= read -r l; do [ -z "$l" ] || [ "$l" = develop ] || ! branch_exists "$l" || longs+=("$l"); done < <(printf '%s\n%s\n' "$LL" "$DETACHED" | sort -u)
TIPS=$(g rev-list --merges --parents develop ${longs[@]+"${longs[@]}"} "${feats[@]}" | awk 'NF > 2 {for (i = 3; i <= NF; i++) print $i}' | sort -u)
merged_into() { # SHA KIND(agent|feature) -> the branch it is merged into, else nothing
  local sha=$1 t tt targets=develop f
  [ "${#longs[@]}" = 0 ] || targets="$targets ${longs[*]}"
  if [ "$2" = agent ]; then for f in "${feats[@]}"; do targets="$targets ${f#refs/heads/}"; done; fi
  printf '%s\n' "$TIPS" | grep -Fxq -- "$sha" || return 0
  for t in $targets; do
    tt=$(sha_of "$t")
    if [ "$sha" != "$tt" ] && g merge-base --is-ancestor "$sha" "$t" 2>/dev/null; then echo "$t"; return 0; fi
  done
}

TAB=$(printf '\t')
LOCAL=() REM=() KEPT=()   # tab-separated. LOCAL: branch, sha, merged into, worktree to remove (or empty); REM: branch, sha, merged into
while IFS= read -r ref; do
  b=${ref#refs/heads/}
  protected "$b" && continue
  sha=$(sha_of "$b"); kind=${b%%/*}
  into=$(merged_into "$sha" "$kind"); [ -n "$into" ] || continue
  w=$(held "$b")
  if [ -z "$w" ]; then LOCAL+=("$b$TAB$sha$TAB$into$TAB")
  elif wt_in_root "$w"; then
    if [ -z "$(git -C "$w" status --porcelain 2>/dev/null)" ]; then LOCAL+=("$b$TAB$sha$TAB$into$TAB$w")
    else KEPT+=("$b: its worktree $w has uncommitted changes"); fi
  else KEPT+=("$b: checked out in $w, which qargi did not make"); fi
done < <(g for-each-ref --format='%(refname)' 'refs/heads/agent/*' 'refs/heads/feature/*')

if [ -n "$REMOTE" ]; then
  g remote get-url origin >/dev/null 2>&1 || die "the repository has no origin remote"
  command -v timeout >/dev/null 2>&1 || die "no timeout command to bound the check of origin"
  g fetch -q origin 2>/dev/null || die "fetch failed"
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
  echo "no merged agent/* or feature/* branches to prune${REMOTE:+ (local or on origin)}"
  for k in "${KEPT[@]}"; do echo "  kept $k"; done
  exit 0
fi

tok=$({ printf '%s\n' "$PROJ" "${REMOTE:-0}"; printf 'local %s\n' "${LOCAL[@]}"; printf 'remote %s\n' "${REM[@]}"; } | plan_token)
echo "prune the merged branches of $PROJ: ${#LOCAL[@]} local, ${#REM[@]} on origin"
for e in "${LOCAL[@]}"; do
  IFS=$TAB read -r b sha into w <<<"$e"
  echo "  delete local $b (${sha:0:7}, merged into $into)${w:+; remove its worktree $w}"
done
for e in "${REM[@]}"; do
  IFS=$TAB read -r b sha into <<<"$e"
  echo "  delete origin/$b (${sha:0:7}, merged into $into)"
done
for k in "${KEPT[@]}"; do echo "  kept $k"; done
if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi branch prune${REMOTE:+ --remote} --plan $tok --approved \"...\")"; exit 0; fi
QARGI_NESTED='' need_plan "$tok"
n=0 m=0
for e in "${LOCAL[@]}"; do
  IFS=$TAB read -r b sha _ w <<<"$e"
  [ -z "$w" ] || wt_drop "$b"
  if g update-ref -d "refs/heads/$b" "$sha"; then journal_ref "$REPO" "refs/heads/$b" "$sha" "" branch:prune; n=$((n + 1)); echo "deleted $b"
  else echo "qargi: warning: could not delete $b (it moved meanwhile)" >&2; fi
done
for e in "${REM[@]}"; do
  IFS=$TAB read -r b sha _ <<<"$e"
  if g push -q --force-with-lease="refs/heads/$b:$sha" origin ":refs/heads/$b" 2>/dev/null; then journal_push "refs/heads/$b" "$sha" "" branch:prune; m=$((m + 1)); echo "deleted origin/$b"
  else echo "qargi: warning: could not delete origin/$b (it moved, or origin refused)" >&2; fi
done
audit_log "branch:prune" "$PROJ $n local $m remote"
echo "pruned $n local and $m remote branch(es)"
