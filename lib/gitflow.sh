#!/usr/bin/env bash
# shellcheck disable=SC2034  # METH and TESTCMD are read by the scripts that source this file
# Helpers shared by release.sh and feature.sh (sourced after lib.sh). The caller sets REPO, PROJ and RDIR, and
# calls `trap cleanup EXIT`. Merges are made in a detached temporary worktree, and a branch is moved by update-ref only
# after every merge succeeded, so a conflict leaves everything as it was and no working tree is touched.

g() { git -C "$REPO" "$@"; }
rec() { echo "$RDIR/$PROJ-${1//\//_}.json"; }   # branch -> the file that records its last full-suite run
sha_of() { g rev-parse -q --verify "refs/heads/$1" || true; }
# "SHA pass|fail" of the last whole-suite run of a branch, only if it ran the project's current test command
verified() { local f; f=$(rec "$1"); [ -f "$f" ] && jq -r --arg c "$TESTCMD" 'select(.command == $c) | .sha + " " + .result' "$f" 2>/dev/null; }
branch_exists() { [ -n "$(sha_of "$1")" ]; }

WT=''
cleanup() { [ -z "$WT" ] || { g worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"; WT=''; }; }
trap cleanup EXIT
worktree() { # commit-ish -> a detached temporary worktree there (WT)
  WT=$(mktemp -d "$DA_STATE/release-wt.XXXXXX")
  g worktree add -q --detach "$WT" "$1" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree of $1"; }
}
held() { g worktree list --porcelain | awk -v b="refs/heads/$1" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==b {print w}' | head -1; }
need_free() { local b w; for b in "$@"; do w=$(held "$b"); [ -z "$w" ] || die "$b is checked out in $w: check out another branch there first (qargi moves $b without touching a working tree)"; done; }
run_suite() { # runs the project's test command in the worktree WT without the project's cloud binding: the suite must not see it
  (cd "$WT" && env -u ANTHROPIC_PROFILE -u QARGI_CLOUD_WORKSPACE -u QARGI_CLOUD_PROJECT bash -c "$TESTCMD")
}
wcommit() { git -C "$WT" commit -q "$@" || die "the commit failed (is a git user.name and user.email set?)"; }


# merge_step INTO_SHA FROM KEY MESSAGE -> MERGED (the merge commit); a --no-ff merge made in a temporary worktree.
# On a conflict nothing moves: the worktree is kept as the place to resolve it (STATE/conflicts/PROJ-KEY) with the merge in
# progress, the conflicted files are listed and the command exits 3. Resolve and commit there, then run the same command with
# --resolved: the commit is used if it is a merge of exactly INTO_SHA and FROM, with nothing left unmerged. Running the command
# again without --resolved while a resolution is waiting is refused, not overwritten.
merge_step() {
  local into=$1 from=$2 key=$3 msg=$4 dir from_sha files out donef di df dm
  dir=$DA_STATE/conflicts/$PROJ-$key; donef=$dir.done
  from_sha=$(g rev-parse "$from")
  if [ -n "${RESOLVED:-}" ]; then
    # a merge resolved earlier in this command whose refs have not moved yet: used again, so it is never resolved twice
    if [ -f "$donef" ] && read -r di df dm < "$donef" && [ "$di" = "$into" ] && [ "$df" = "$from_sha" ]; then MERGED=$dm; return 0; fi
    if [ -d "$dir" ]; then
      [ -z "$(git -C "$dir" diff --name-only --diff-filter=U)" ] && [ ! -f "$(git -C "$dir" rev-parse --git-path MERGE_HEAD)" ] \
        || die "the merge in $dir is not finished: resolve the conflicts, git add them, git commit, then run this again with --resolved"
      [ "$(git -C "$dir" rev-parse HEAD^1 2>/dev/null)" = "$into" ] && [ "$(git -C "$dir" rev-parse HEAD^2 2>/dev/null)" = "$from_sha" ] \
        || die "the commit in $dir is not a merge of $from into the current head (the branches moved, or it is not a merge commit): remove it with git worktree remove --force $dir and start over"
      MERGED=$(git -C "$dir" rev-parse HEAD)
      printf '%s %s %s\n' "$into" "$from_sha" "$MERGED" > "$donef"
      g worktree remove --force "$dir" >/dev/null 2>&1 || rm -rf "$dir"
      return 0
    fi
  elif [ -d "$dir" ]; then
    die "a merge is waiting to be resolved in $dir: finish it there (git add, git commit) and run this again with --resolved, or abandon it with git worktree remove --force $dir"
  elif [ -f "$donef" ] && read -r di df _ < "$donef" && [ "$di" = "$into" ] && [ "$df" = "$from_sha" ]; then
    die "a merge you resolved is waiting to be applied: run this again with --resolved (or abandon it with rm $donef)"
  fi
  rm -f "$donef"
  worktree "$into"
  if out=$(git -C "$WT" merge -q --no-ff "$from" -m "$msg" 2>&1); then MERGED=$(git -C "$WT" rev-parse HEAD); cleanup; return 0; fi
  files=$(git -C "$WT" diff --name-only --diff-filter=U)
  if [ -z "$files" ]; then cleanup; die "merging $from failed without a conflict: $out"; fi
  mkdir -p "$DA_STATE/conflicts"
  g worktree move "$WT" "$dir" >/dev/null 2>&1 || { cleanup; die "the merge of $from conflicts, and the worktree to resolve it in could not be kept; nothing was changed"; }
  WT=''
  echo "qargi: merging $from conflicts. Nothing was changed. Conflicted files:" >&2
  echo "$files" | sed 's/^/  /' >&2
  echo "Resolve them in $dir (the merge is in progress there): edit, git add, git commit." >&2
  echo "Then run the same command again with --resolved. (git worktree remove --force $dir abandons it.)" >&2
  exit 3
}
merge_forget() { local k; for k in "$@"; do rm -f "$DA_STATE/conflicts/$PROJ-$k.done"; done; }   # after the refs moved

# what a merge would bring in, for the plan the person approves: BASE BRANCH
show_incoming() {
  local base=$1 br=$2 n
  n=$(g rev-list --count "$base..$br")
  echo "  brings $n commit(s) into $base:"
  g log --format='    %h %s' "$base..$br" | head -30
  [ "$n" -le 30 ] || echo "    ... and $((n - 30)) more"
  echo "  files changed: $(g diff --shortstat "$base...$br" | sed 's/^ *//')"
  g diff --name-only "$base...$br" | head -30 | sed 's/^/    /'
  [ "$(g diff --name-only "$base...$br" | wc -l)" -le 30 ] || echo "    ... (more files)"
}
project_load() { # PROJ (or inferred) -> af, REPO, TESTCMD, METH
  [ -n "$PROJ" ] || PROJ=$(python3 -I "$(dirname "$0")/help.py" infer)
  af=$DA_CONF/projects/$PROJ.json
  [ -f "$af" ] || die "no stored answers for '$PROJ': qargi project attach DIR, or --project"
  REPO=$(jq -r '.repo.path // ""' "$af"); REPO=${REPO/#\~/$HOME}
  [ -d "$REPO/.git" ] || [ -f "$REPO/.git" ] || die "the answers for $PROJ name no local repository (repo.path)"
  METH=$(jq -r '.methodology // "gitflow"' "$af")
  TESTCMD=$(jq -r '.test_command // ""' "$af")
  RDIR=$DA_STATE/releases; mkdir -p "$RDIR"
}
