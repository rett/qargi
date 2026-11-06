#!/usr/bin/env bash
# `qargi review check OUT` checks a collected series; `qargi review apply` is the step between it and `qargi feature merge NAME BRANCH`: put a collected,
# verified series on a task branch of the real repository.
#
#   review.sh check OUT [--allow-empty]                       checks a member's output (RUN_DIR/out, or the run directory) with review_check.py; the
#       lead's lease on the feature the run is based on is renewed first
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
if [ "$verb" = check ]; then
  # qargi review check OUT [--allow-empty]: review_check.py reads one output directory; the lead's registry knows the run it belongs to, so the
  # lead's lease on the feature that run is based on is renewed first (no project is needed, none is loaded)
  . "$(dirname "$0")/marshal.sh"
  # the argument is a run's OUT (the run is its parent directory) or the run directory itself, which review_check.py also takes (RUN/out)
  for a in "$@"; do
    case $a in -*) ;; *)
      if o=$(readlink -f -- "$a" 2>/dev/null); then
        if [ -d "$o/out" ] && [ ! -d "$o/patches" ] && [ ! -e "$o/manifest.json" ]; then marshal_touch_run "$o"; else marshal_touch_run "$(dirname "$o")"; fi
      fi
      break;;
    esac
  done
  exec python3 -I "$(dirname "$0")/review_check.py" "$@"
fi
# pick_author: AUTH_MODE (reset | keep), AUTH ("Name <email>") and AUTH_SRC (where it comes from, or why the member's author stays) from the stored answers.
# review.keep_author true keeps the member's author; else git.author, else the repository's user.name/user.email; with none of them the member's stays.
# Both answers are checked as `project validate` checks them: a hand-edited file that breaks them is refused before anything is applied.
AUTH_RE='^([^<>]*[^<>[:space:]]) <([^<>[:space:]@]+@[^<>[:space:]@]+)>$'
# shellcheck disable=SC2154  # af comes from project_load
pick_author() {
  local keep a n e aj
  # the answers are the run's own, taken into the lead's registry at prepare (run_record: RUN_ANS); a run of an older record reads the stored file
  if [ -n "${RUN_ANS:-}" ]; then aj=$RUN_ANS; else aj=$(cat -- "$af" 2>/dev/null) || aj='{}'; fi
  keep=$(jq -r '(.review // {}) | .keep_author // false | if type == "boolean" then tostring else "bad" end' <<<"$aj" 2>/dev/null) || keep=bad
  [ "$keep" != bad ] || die "review.keep_author in the answers of $PROJ is not true or false (qargi project set $PROJ review.keep_author true); nothing was applied"
  a=$(jq -r '(.git // {}) | .author // "" | if type == "string" then . else error("not a string") end' <<<"$aj" 2>/dev/null) \
    || die "git.author in the answers of $PROJ is not a string like 'Example Author <author@example.com>' (qargi project set $PROJ git.author ...); nothing was applied"
  AUTH='' AUTH_MODE=keep AUTH_SRC=''
  if [ "$keep" = true ]; then AUTH_SRC='answer review.keep_author'; return 0; fi
  if [ -n "$a" ]; then
    { [[ $a =~ $AUTH_RE ]] && [[ $a != *[[:cntrl:]]* ]]; } \
      || die "git.author in the answers of $PROJ is not 'Name <email>' ($a): qargi project set $PROJ git.author 'Example Author <author@example.com>'; nothing was applied"
    AUTH=$a AUTH_MODE=reset AUTH_SRC='answer git.author'; return 0
  fi
  n=$(g config user.name 2>/dev/null || true); e=$(g config user.email 2>/dev/null || true)
  if [ -n "$n" ] && [ -n "$e" ]; then
    # read from the repository's configuration, which a member can also write when it can write the repository: checked as git.author is
    a="$n <$e>"
    { [[ $a =~ $AUTH_RE ]] && [[ $a != *[[:cntrl:]]* ]]; } \
      || die "the repository's user.name and user.email ($a) are not a plain 'Name <email>' (no < > or control characters in the name, no spaces or extra @ in the address): fix them in $REPO, or give git.author (qargi project set $PROJ git.author 'Example Author <author@example.com>'); nothing was applied"
    AUTH=$a AUTH_MODE=reset AUTH_SRC="the repository's user.name and user.email; no answer git.author"; return 0
  fi
  AUTH_SRC='no answer git.author and no user.name and user.email in the repository'
}
# apply_series WT PATCH...: git am of each patch in the worktree, in order; with AUTH_MODE=reset every applied commit then has its author set to AUTH
# (the date stays, the committer is what git am used). MEMBERS gets the distinct authors the patches carried. On failure FAIL is the patch and
# FAILMSG says what failed (a patch that does not apply is aborted, so the worktree is left clean).
apply_series() {
  local wt=$1 p m; shift
  MEMBERS='' failmsg=''
  for p in "$@"; do
    if ! git -C "$wt" am -q --3way "$p" >/dev/null 2>&1; then fail=$p; failmsg="$(basename "$p") does not apply on $sha"; git -C "$wt" am --abort >/dev/null 2>&1 || true; return 0; fi
    m=$(git -C "$wt" log -1 --format='%an <%ae>')
    case "; $MEMBERS;" in *"; $m;"*) ;; *) MEMBERS=${MEMBERS:+$MEMBERS; }$m;; esac
    if [ "$AUTH_MODE" = reset ] && [ "$m" != "$AUTH" ]; then
      # a mechanical rewrite of the commit just made: the lead's hooks do not run on it, it is never signed (no passphrase prompt), and its message is kept
      # as it is (--cleanup=verbatim: a commit.cleanup=strip would drop the lines that start with #)
      git -C "$wt" -c core.hooksPath=/dev/null commit -q --amend --no-edit --cleanup=verbatim --no-gpg-sign --author="$AUTH" >/dev/null 2>&1 \
        || { fail=$p; failmsg="could not reset the author of $(basename "$p") to $AUTH"; return 0; }
    fi
  done
}
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
    marshal_touch_run "$RUN"   # the lead's apply keeps its lease on the feature the run is based on
    [ "$(run_class "$RUN" "$SRC")" != read-only ] \
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
    # the author of the applied commits: the lead's (answer git.author, else the repository's user.name/user.email), unless the answer review.keep_author
    # is true or neither identity exists; the committer is the one above. What the member wrote is recorded in the ref journal and the audit log.
    pick_author
    WT=$(mktemp -d "$DA_STATE/apply-wt.XXXXXX")
    g worktree add -q -b "$BRANCH" "$WT" "$sha" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree for $BRANCH"; }
    fail=''
    apply_series "$WT" "${patches[@]}"
    tip=$(git -C "$WT" rev-parse HEAD)
    cleanup
    if [ -n "$fail" ]; then
      g branch -D "$BRANCH" >/dev/null 2>&1 || true
      die "$failmsg; the worktree and $BRANCH were removed, nothing else changed"
    fi
    if [ "$AUTH_MODE" = reset ]; then AUTH_LINE="author reset to $AUTH ($AUTH_SRC); member author recorded in the ref journal: $MEMBERS"
    else AUTH_LINE="author kept as the member's ($AUTH_SRC): $MEMBERS"; fi
    journal_line "$REPO" "refs/heads/$BRANCH" "" "$tip" review:apply '' "$AUTH_LINE"
    audit_log "review:apply" "$RUN $BRANCH ${tip:0:12}: $AUTH_LINE"
    echo "applied ${#patches[@]} patch(es) on $BRANCH, from ${sha:0:12} to ${tip:0:12}:"
    g log --reverse --format='  %h %s' "$sha..$tip"
    echo "$AUTH_LINE"
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
  *) usage_die "usage: qargi review check OUT [--allow-empty] | qargi review apply RUN_DIR|--from-saved ID [--branch BRANCH] [--project P]";;
esac
