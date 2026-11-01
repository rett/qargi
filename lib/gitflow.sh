#!/usr/bin/env bash
# shellcheck disable=SC2034  # METH and TESTCMD are read by the scripts that source this file
# Helpers shared by release.sh and feature.sh (sourced after lib.sh). The caller sets REPO, PROJ and RDIR, and
# calls `trap cleanup EXIT`. Merges are made in a detached temporary worktree, and a branch is moved by update-ref only
# after every merge succeeded, so a conflict leaves everything as it was and no working tree is touched.

# The marshal (lib/marshal.sh) says who leads a feature. Source it unless the caller (marshal.sh itself) already has; when the
# script is missing the stubs below make every call a warning, never a refusal.
if ! command -v marshal_check >/dev/null 2>&1; then
  if [ -f "$(dirname "${BASH_SOURCE[0]}")/marshal.sh" ]; then . "$(dirname "${BASH_SOURCE[0]}")/marshal.sh"
  else
    marshal_start() { return 127; }; marshal_check() { return 127; }; marshal_finish() { return 127; }
    marshal_hold_start() { :; }; marshal_hold_stop() { :; }
  fi
fi

g() { git -C "$REPO" "$@"; }
rec() { echo "$RDIR/$PROJ-${1//\//_}.json"; }   # branch -> the file that records its last full-suite run
sha_of() { g rev-parse -q --verify "refs/heads/$1" || true; }
# "SHA pass|fail" of the last whole-suite run of a branch, only if it ran the project's current test command
verified() { local f; f=$(rec "$1"); [ -f "$f" ] && jq -r --arg c "$TESTCMD" 'select(.command == $c) | .sha + " " + .result' "$f" 2>/dev/null; }

# journal_ref REPO REF OLD NEW VERB -> appends one line to the lead's ref journal ($DA_STATE/ref-journal.jsonl) after a local
# branch was created (OLD empty), moved or deleted (NEW empty) by one of qargi's own verbs. `qargi local verify` accepts a branch
# change in a run's strict phase only when this journal names it, so the changes the lead made while a run was out are not blamed
# on the executor. Append only, under flock; the guard (lib/guard.py) keeps an agent from writing it. A failure here is a warning,
# never a failure of the verb: the work is done, only a later `local verify` would then want the lead's changes explained.
journal_ref() {
  local repo ref old new verb zero=0000000000000000000000000000000000000000 f=${DA_STATE:-}/ref-journal.jsonl
  ref=$2 old=${3:-$zero} new=${4:-$zero} verb=$5
  repo=$(readlink -f "$1" 2>/dev/null) || repo=$1
  [ -n "${DA_STATE:-}" ] && case $ref in refs/heads/?*) ;; *) false;; esac \
    && ( umask 077; flock 9 && jq -nc --arg at "$(now)" --argjson ep "$(date +%s)" --arg v "$verb" --arg p "${PROJ:-}" --arg r "$repo" \
           --arg ref "$ref" --arg o "$old" --arg n "$new" --arg by "$(id -un 2>/dev/null || echo unknown)@$(hostname 2>/dev/null || echo unknown)" \
           '{at:$at, epoch:$ep, verb:$v, project:$p, repo:$r, ref:$ref, old:$o, new:$n, by:$by}' >> "$f" ) 9> "$f.lock" \
    || echo "qargi: warning: the ref journal could not be written for $ref ($verb); a later 'qargi local verify' of a run prepared before this may not accept the change" >&2
  return 0
}
branch_exists() { [ -n "$(sha_of "$1")" ]; }

# remote_tip BRANCH -> RSTATE and RTIP, RWHY: asks the live remote (git ls-remote, bounded by QARGI_REMOTE_TIMEOUT, 10s) what
# refs/heads/BRANCH is there, because the remote-tracking refs are as old as the last fetch. RSTATE is none (no origin),
# found (RTIP), absent, or unchecked (RWHY says why). It never fails and never prompts.
remote_tip() {
  local out rc
  RSTATE=none RTIP='' RWHY=''
  g remote get-url origin >/dev/null 2>&1 || return 0
  command -v timeout >/dev/null 2>&1 || { RSTATE=unchecked RWHY="no timeout command to bound the check"; return 0; }
  out=$(GIT_TERMINAL_PROMPT=0 timeout "${QARGI_REMOTE_TIMEOUT:-10}" git -C "$REPO" ls-remote origin "refs/heads/$1" 2>&1) && rc=0 || rc=$?
  if [ "$rc" = 124 ]; then RSTATE=unchecked RWHY="no answer from origin within ${QARGI_REMOTE_TIMEOUT:-10}s"; return 0; fi
  if [ "$rc" != 0 ]; then RSTATE=unchecked RWHY=$(printf '%s' "$out" | grep -v '^[[:space:]]*$' | head -1 | cut -c1-120); RWHY=${RWHY:-"git ls-remote failed"}; return 0; fi
  RTIP=$(printf '%s\n' "$out" | awk -v r="refs/heads/$1" '$2 == r {print $1; exit}')
  if [ -n "$RTIP" ]; then RSTATE=found; else RSTATE=absent; fi
}
# remote_report BRANCH: one line saying where the branch is on the live origin next to the local tip (nothing without an origin)
remote_report() {
  local b=$1 l n m
  remote_tip "$b"; l=$(sha_of "$b")
  case $RSTATE in
    none) ;;
    unchecked) echo "  origin $b: remote not checked ($RWHY)";;
    absent) echo "  origin $b: not on origin${l:+ (local ${l:0:7})}";;
    found)
      if [ -z "$l" ]; then echo "  origin $b: remote ${RTIP:0:7}, no local branch"
      elif [ "$l" = "$RTIP" ]; then echo "  origin $b: remote ${RTIP:0:7}, local ${l:0:7} (same)"
      elif g cat-file -e "$RTIP^{commit}" 2>/dev/null; then
        n=$(g rev-list --count "$RTIP..$l"); m=$(g rev-list --count "$l..$RTIP")
        echo "  origin $b: remote ${RTIP:0:7}, local ${l:0:7} (local is $n ahead, $m behind)"
      else echo "  origin $b: remote ${RTIP:0:7}, local ${l:0:7} (differ; the remote tip is not fetched yet)"; fi;;
  esac
}

WT=''
cleanup() { [ -z "$WT" ] || { g worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"; WT=''; }; }
on_exit() { marshal_hold_stop; cleanup; }
trap on_exit EXIT   # the lease renewer never outlives the verb, whatever way it ended
worktree() { # commit-ish -> a detached temporary worktree there (WT)
  WT=$(mktemp -d "$DA_STATE/release-wt.XXXXXX")
  g worktree add -q --detach "$WT" "$1" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree of $1"; }
}
held() { g worktree list --porcelain | awk -v b="refs/heads/$1" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==b {print w}' | head -1; }
need_free() { local b w; for b in "$@"; do w=$(held "$b"); [ -z "$w" ] || die "$b is checked out in $w: check out another branch there first, for example git -C $w checkout --detach (qargi moves $b without touching a working tree)"; done; }
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

# marshal_gate NAME -> asks the marshal whether this identity may change feature NAME. Only an explicit refusal (status 1, the
# message already printed) ends the verb with exit 1 and changes nothing; warnings pass through on stderr, and any other failure
# (script missing, an exception) is a warning too: an unreachable marshal never blocks work.
marshal_gate() {
  local rc=0 err
  err=$(mktemp "$DA_STATE/.marshal-gate.XXXXXX" 2>/dev/null) || err=/dev/null
  marshal_check "$PROJ" "$1" 2>"$err" || rc=$?
  if [ "$err" != /dev/null ]; then
    cat "$err" >&2
    if [ "$rc" = 1 ] && grep -q '^Traceback' "$err"; then rc=70; fi   # an exception also exits 1, but it is not a refusal
    rm -f "$err"
  fi
  [ "$rc" -ne 0 ] || return 0
  [ "$rc" -ne 1 ] || exit 1
  echo "qargi: warning: the marshal could not be asked (status $rc); going on" >&2
}
# hold_begin NAME / hold_end -> the lease of NAME is renewed while a long step runs. An interrupt leaves through the EXIT trap,
# which stops the renewer; hold_end stops it at once and puts the interrupt traps back.
hold_begin() { trap 'exit 130' INT; trap 'exit 143' TERM; marshal_hold_start "$PROJ" "$1"; }
hold_end() { marshal_hold_stop; trap - INT TERM; }
