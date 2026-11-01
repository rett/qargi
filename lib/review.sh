#!/usr/bin/env bash
# The step between `qargi review check RUN_DIR` and `qargi feature merge NAME BRANCH`: put a collected, verified series on a
# task branch of the real repository.
#
#   review.sh apply RUN_DIR [--branch BRANCH] [--project P]   agent/<slug> at the run's base with the patches applied
#   review.sh prune [--project P] [--yes]                      list (or delete) agent/* branches merged into develop or a feature/*
#
# The branch is made in a temporary worktree of the project's repository (repo.path), so the user's checkout is never touched;
# no ref other than the new branch changes. A patch that does not apply removes the worktree and the branch again.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
RUN_ARG='' BRANCH='' PROJ='' YES=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) PROJ=${2:?--project needs a name}; shift 2;; --branch) BRANCH=${2:?--branch needs a name}; shift 2;; --yes) YES=1; shift;;
    -*) die "unknown option $1";;
    *) [ -z "$RUN_ARG" ] || die "unexpected argument $1"; RUN_ARG=$1; shift;;
  esac
done
. "$(dirname "$0")/gitflow.sh"
# shellcheck disable=SC2154  # PROJ comes from project_load
project_load

case $verb in
  apply)
    RUN=${RUN_ARG%/}; [ -n "$RUN" ] || die "usage: qargi review apply RUN_DIR [--branch BRANCH] [--project P]"
    [ -f "$RUN/refs.before" ] && [ -d "$RUN/out" ] || die "apply needs a RUN dir made by qargi local prepare"
    [ "$(run_class "$RUN")" != read-only ] \
      || die "$RUN is a read-only run ($(cat "$RUN/ability" 2>/dev/null || echo review)): its product is a report, never patches. Read $RUN/out/report.md; nothing was applied"
    [ ! -f "$RUN/applied" ] || die "this run was applied already ($(cut -d' ' -f1 "$RUN/applied")): qargi feature merge, then qargi local clean $RUN"
    lib=$(dirname "$0")
    python3 -I "$lib/review_check.py" "$RUN/out" || die "review check refuses $RUN/out: nothing was applied"
    "$lib/local.sh" verify "$RUN" || die "local verify refuses $RUN: nothing was applied"
    [ -f "$RUN/repo.path" ] && [ "$(readlink -f "$(cat "$RUN/repo.path")")" != "$(readlink -f "$REPO")" ] \
      && die "the run was made from $(cat "$RUN/repo.path"), not from the repository of $PROJ ($REPO)"
    slug=$(jq -r --arg r "$RUN" 'select(.run == $r) | .slug' "$DA_STATE/local-runs.jsonl" 2>/dev/null | tail -1)
    base=$(jq -r --arg r "$RUN" 'select(.run == $r) | .base' "$DA_STATE/local-runs.jsonl" 2>/dev/null | tail -1)
    if [ -z "$slug" ]; then
      b=$(git -C "$RUN/clone" symbolic-ref -q --short HEAD 2>/dev/null || true); slug=${b#agent/}
    fi
    [ -n "$BRANCH" ] || { [ -n "$slug" ] || die "the run records no slug: give --branch"; BRANCH=agent/$slug; }
    git check-ref-format "refs/heads/$BRANCH" || die "'$BRANCH' is not a branch name"
    [ -n "$base" ] || base=$(git -C "$RUN/clone" rev-parse --abbrev-ref origin/HEAD 2>/dev/null | sed 's|^origin/||' || true)
    # the base commit: the one the base branch had when prepare took its snapshot
    sha=$(awk -v b="refs/heads/$base" '$1=="local" && $2==b {print $3}' "$RUN/refs.before")
    [ -n "$sha" ] || sha=$(git -C "$RUN/bare.git" rev-parse -q --verify "refs/heads/$base" 2>/dev/null || true)
    [ -n "$sha" ] || die "cannot tell the run's base commit (branch '$base')"
    g cat-file -e "$sha^{commit}" 2>/dev/null || die "the base commit $sha is not in $REPO"
    branch_exists "$BRANCH" && die "$BRANCH exists already: choose another with --branch, or delete it first"
    patches=$(find "$RUN/out/patches" -maxdepth 1 -name '*.patch' 2>/dev/null | sort)
    [ -n "$patches" ] || die "$RUN/out/patches holds no patches: nothing to apply"
    # the committer: what the repository has configured, else the author of the patches
    if [ -z "$(g config user.name || true)" ] || [ -z "$(g config user.email || true)" ]; then
      first=$(echo "$patches" | head -1)
      GIT_COMMITTER_NAME=$(sed -n 's/^From: \(.*\) <.*>$/\1/p' "$first" | head -1)
      GIT_COMMITTER_EMAIL=$(sed -n 's/^From: .* <\(.*\)>$/\1/p' "$first" | head -1)
      [ -n "$GIT_COMMITTER_NAME" ] && [ -n "$GIT_COMMITTER_EMAIL" ] || die "no git user.name/user.email in $REPO and the first patch has no author"
      export GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
    fi
    WT=$(mktemp -d "$DA_STATE/apply-wt.XXXXXX")
    g worktree add -q -b "$BRANCH" "$WT" "$sha" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree for $BRANCH"; }
    fail=''
    for p in $patches; do
      if ! git -C "$WT" am -q --3way "$p" >/dev/null 2>&1; then fail=$p; git -C "$WT" am --abort >/dev/null 2>&1 || true; break; fi
    done
    tip=$(git -C "$WT" rev-parse HEAD)
    cleanup
    if [ -n "$fail" ]; then
      g branch -D "$BRANCH" >/dev/null 2>&1 || true
      die "$(basename "$fail") does not apply on $sha; the worktree and $BRANCH were removed, nothing else changed"
    fi
    journal_ref "$REPO" "refs/heads/$BRANCH" "" "$tip" review:apply
    echo "applied $(echo "$patches" | wc -l) patch(es) on $BRANCH, from ${sha:0:12} to ${tip:0:12}:"
    g log --reverse --format='  %h %s' "$sha..$tip"
    printf '%s %s %s\n' "$BRANCH" "$tip" "$(now)" > "$RUN/applied"
    # the branch is a change `local verify` would report: record it in the snapshot the run is compared against
    if grep -q '^local ' "$RUN/refs.before"; then
      { { grep '^local ' "$RUN/refs.before"; echo "local refs/heads/$BRANCH $tip"; } | sort; grep -v '^local ' "$RUN/refs.before" || true; } > "$RUN/refs.before.new" \
        && mv "$RUN/refs.before.new" "$RUN/refs.before"
    fi
    echo "next:"
    echo "  qargi feature merge NAME $BRANCH    (NAME: the feature this task belongs to)"
    echo "  qargi local clean $RUN";;
  prune)
    [ -z "$RUN_ARG" ] || die "usage: qargi review prune [--project P] [--yes]"
    targets=$(g for-each-ref --format='%(refname:short)' refs/heads/develop 'refs/heads/feature/*')
    cur=$(g symbolic-ref -q --short HEAD || true); n=0
    while read -r b; do
      [ -n "$b" ] || continue
      [ "$b" != "$cur" ] || { echo "kept $b (checked out)"; continue; }
      [ -z "$(held "$b")" ] || { echo "kept $b (checked out in $(held "$b"))"; continue; }
      sha=$(sha_of "$b"); into=''
      for t in $targets; do g merge-base --is-ancestor "$sha" "$t" && { into=$t; break; }; done
      [ -n "$into" ] || continue
      n=$((n + 1))
      if [ -n "$YES" ]; then g branch -D "$b" >/dev/null && journal_ref "$REPO" "refs/heads/$b" "$sha" "" review:prune && echo "deleted $b (was ${sha:0:12}, merged into $into)"
      else echo "$b (${sha:0:12}) is merged into $into"; fi
    done < <(g for-each-ref --format='%(refname:short)' 'refs/heads/agent/*')
    if [ "$n" = 0 ]; then echo "no merged agent/* branches"; elif [ -z "$YES" ]; then echo "$n branch(es) would be deleted: qargi review prune --yes"; fi;;
  *) die "usage: qargi review apply|prune ...";;
esac
