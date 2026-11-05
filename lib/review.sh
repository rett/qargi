#!/usr/bin/env bash
# The step between `qargi review check RUN_DIR` and `qargi feature merge NAME BRANCH`: put a collected, verified series on a
# task branch of the real repository.
#
#   review.sh apply RUN_DIR [--branch BRANCH] [--project P]   agent/<slug> at the run's base with the patches applied
#   review.sh apply --from-saved ID [--branch BRANCH] [--project P]
#       the same from the copy `local verify` saved of the run when it passed ($QARGI_STATE/runs/ID: its OUT, its snapshots, its record),
#       for a run whose directory is gone (a reboot that emptied a tmpfs); the same checks: review check of the saved OUT, local verify
#       --saved ID (the refs against the saved snapshot), the lead's registry for the repository, slug and base. Refused while the run
#       directory still exists (apply that), and once applied (the saved copy records it, as RUN/applied does).
#
# The branch is made in a temporary worktree of the project's repository (repo.path), so the user's checkout is never touched;
# no ref other than the new branch changes. A patch that does not apply removes the worktree and the branch again.
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
RUN_ARG='' BRANCH='' PROJ='' SAVED=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --branch) need_val "$1" $#; BRANCH=$2; shift 2;;
    --from-saved) need_val "$1" $#; SAVED=$2; shift 2;;
    -*) usage_die "unknown option $1";;
    *) [ -z "$RUN_ARG" ] || usage_die "unexpected argument $1"; RUN_ARG=$1; shift;;
  esac
done
. "$(dirname "$0")/gitflow.sh"
# shellcheck disable=SC2154  # PROJ comes from project_load
project_load

case $verb in
  apply)
    lib=$(dirname "$0")
    if [ -n "$SAVED" ]; then
      # SRC is the lead's saved copy of the run: what the run directory would hold for apply (out, refs.before, class, ability, applied)
      [ -z "$RUN_ARG" ] || usage_die "give RUN_DIR or --from-saved ID, not both"
      case $SAVED in qargi.??????) ;; *) usage_die "--from-saved takes the id of a run: the name of its directory, qargi.XXXXXX";; esac
      SRC=$DA_STATE/runs/$SAVED
      [ -d "$SRC" ] && [ ! -L "$SRC" ] && [ -d "$SRC/out" ] && [ -f "$SRC/refs.before" ] || die "no saved copy of $SAVED in $DA_STATE/runs (local verify saves one when a run passes)"
      reg_load; RUN=$(reg_id "$SAVED") || die "the lead's registry names no run $SAVED (or more than one): nothing was applied"
      [ ! -e "$RUN" ] || die "the run directory $RUN still exists: apply it (qargi review apply $RUN); nothing was applied"
    else
      [ -n "${RUN_ARG%/}" ] || usage_die "usage: qargi review apply RUN_DIR|--from-saved ID [--branch BRANCH] [--project P]"
      RUN=$(readlink -f -- "$RUN_ARG") || die "no such run directory: $RUN_ARG"   # the registry names real paths, and git -C WT am is given paths of the run
      SRC=$RUN
    fi
    [ -f "$SRC/refs.before" ] && [ -d "$SRC/out" ] || usage_die "apply needs a RUN dir made by qargi local prepare"
    [ "$(run_class "$SRC")" != read-only ] \
      || die "$RUN is a read-only run ($(cat "$SRC/ability" 2>/dev/null || echo review)): its product is a report, never patches. Read $SRC/out/report.md; nothing was applied"
    [ ! -L "$SRC/applied" ] && { [ ! -e "$SRC/applied" ] || [ -f "$SRC/applied" ]; } || die "$SRC/applied is a link or not a plain file: a member put it there (look at the run; nothing was applied)"
    [ ! -f "$SRC/applied" ] || die "this run was applied already ($(cut -d' ' -f1 "$SRC/applied")): qargi feature merge, then qargi local clean $RUN"
    reg_load; [ -z "$(reg_get "$RUN" closed)" ] || die "this run was closed ($(reg_get "$RUN" closed_by)): its patches were applied by hand. qargi local clean $RUN removes it; nothing was applied"
    python3 -I "$lib/review_check.py" "$SRC/out" || die "review check refuses $SRC/out: nothing was applied"
    if [ -n "$SAVED" ]; then "$lib/local.sh" verify --saved "$SAVED" || die "local verify refuses the saved copy $SAVED: nothing was applied"
    else "$lib/local.sh" verify "$RUN" || die "local verify refuses $RUN: nothing was applied"; fi
    # the repository, the slug and the base are the lead's registry's (looked up by real path, so ./run and run/ are the same run), never the run directory's own files
    reg_load
    if [ -n "$SAVED" ]; then reg_record "$RUN" || exit 1; else run_record "$RUN" || exit 1; fi
    [ -z "$RUN_REPO" ] || [ "$(readlink -f "$RUN_REPO")" = "$(readlink -f "$REPO")" ] \
      || die "the run was made from $RUN_REPO, not from the repository of $PROJ ($REPO)"
    slug=$(reg_get "$RUN" slug); base=$(reg_get "$RUN" base)
    [ -n "$BRANCH" ] || { [ -n "$slug" ] || die "the run records no slug: give --branch"; BRANCH=agent/$slug; }
    git check-ref-format "refs/heads/$BRANCH" || die "'$BRANCH' is not a branch name"
    [ -n "$base" ] || die "the registry records no base branch for $RUN"
    # the base commit: the one the base branch had when prepare took its snapshot
    sha=$(awk -v b="refs/heads/$base" '$1=="local" && $2==b {print $3}' "$SRC/refs.before")
    [ -n "$sha" ] || [ "$SRC" != "$RUN" ] || sha=$(git -C "$RUN/bare.git" rev-parse -q --verify "refs/heads/$base" 2>/dev/null || true)
    [ -n "$sha" ] || die "cannot tell the run's base commit (branch '$base')"
    g cat-file -e "$sha^{commit}" 2>/dev/null || die "the base commit $sha is not in $REPO"
    branch_exists "$BRANCH" && die "$BRANCH exists already: choose another with --branch, or delete it first"
    # the patches are the files of out/patches: read as a list, so a name with a space or a newline in it stays one name
    patches=()
    while IFS= read -r -d '' p; do patches+=("$p"); done < <(find "$SRC/out/patches" -maxdepth 1 -name '*.patch' -type f -print0 2>/dev/null | sort -z)
    [ ${#patches[@]} -gt 0 ] || die "$SRC/out/patches holds no patches: nothing to apply"
    # the committer: what the repository has configured, else the author of the patches
    if [ -z "$(g config user.name || true)" ] || [ -z "$(g config user.email || true)" ]; then
      first=${patches[0]}
      GIT_COMMITTER_NAME=$(sed -n 's/^From: \(.*\) <.*>$/\1/p' "$first" | head -1)
      GIT_COMMITTER_EMAIL=$(sed -n 's/^From: .* <\(.*\)>$/\1/p' "$first" | head -1)
      [ -n "$GIT_COMMITTER_NAME" ] && [ -n "$GIT_COMMITTER_EMAIL" ] || die "no git user.name/user.email in $REPO and the first patch has no author"
      export GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL
    fi
    WT=$(mktemp -d "$DA_STATE/apply-wt.XXXXXX")
    g worktree add -q -b "$BRANCH" "$WT" "$sha" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree for $BRANCH"; }
    fail=''
    for p in "${patches[@]}"; do
      if ! git -C "$WT" am -q --3way "$p" >/dev/null 2>&1; then fail=$p; git -C "$WT" am --abort >/dev/null 2>&1 || true; break; fi
    done
    tip=$(git -C "$WT" rev-parse HEAD)
    cleanup
    if [ -n "$fail" ]; then
      g branch -D "$BRANCH" >/dev/null 2>&1 || true
      die "$(basename "$fail") does not apply on $sha; the worktree and $BRANCH were removed, nothing else changed"
    fi
    journal_ref "$REPO" "refs/heads/$BRANCH" "" "$tip" review:apply
    echo "applied ${#patches[@]} patch(es) on $BRANCH, from ${sha:0:12} to ${tip:0:12}:"
    g log --reverse --format='  %h %s' "$sha..$tip"
    # The run directory is a member's to write: what is recorded there is written in the lead's state directory and renamed into place (mv -T replaces a link
    # that stands in the name, it never writes through it).
    rec=$(mktemp "$DA_STATE/apply-rec.XXXXXX") || die "could not record the application in $SRC: $BRANCH was made at ${tip:0:12}; write 'agent/... TIP NOW' to $SRC/applied by hand"
    printf '%s %s %s\n' "$BRANCH" "$tip" "$(now)" > "$rec" && mv -T -- "$rec" "$SRC/applied" || { rm -f "$rec"; die "could not write $SRC/applied ($BRANCH was made at ${tip:0:12})"; }
    # the branch is a change `local verify` would report: record it in the snapshot the run is compared against
    if grep -q '^local ' "$SRC/refs.before"; then
      rec=$(mktemp "$DA_STATE/apply-rec.XXXXXX") || die "could not record the branch in the snapshot of $SRC"
      { { grep '^local ' "$SRC/refs.before"; echo "local refs/heads/$BRANCH $tip"; } | sort; grep -v '^local ' "$SRC/refs.before" || true; } > "$rec" \
        && mv -T -- "$rec" "$SRC/refs.before" || { rm -f "$rec"; die "could not update the snapshot $SRC/refs.before"; }
    fi
    # a run applied from its directory: the saved copy records it too, so it is never applied twice
    if [ -z "$SAVED" ] && [ -d "$DA_STATE/runs/${RUN##*/}" ] && [ ! -L "$DA_STATE/runs/${RUN##*/}" ]; then cp -- "$SRC/applied" "$DA_STATE/runs/${RUN##*/}/applied" 2>/dev/null || true; fi
    echo "next:"
    echo "  qargi feature merge NAME $BRANCH    (NAME: the feature this task belongs to)"
    echo "  qargi local clean $RUN${SAVED:+   (its directory is gone: once the work is merged, clean drops its record and the saved copy)}";;
  *) usage_die "usage: qargi review apply RUN_DIR|--from-saved ID [--branch BRANCH] [--project P]";;
esac
