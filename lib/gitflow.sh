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
    marshal_hold_start() { :; }; marshal_hold_stop() { :; }; marshal_touch() { :; }; marshal_touch_run() { :; }
  fi
fi

g() { git -C "$REPO" "$@"; }
rec() { echo "$RDIR/$PROJ-${1//\//_}.json"; }   # branch -> the file that records its last full-suite run
sha_of() { g rev-parse -q --verify "refs/heads/$1" || true; }
# "SHA pass|fail" of the last whole-suite run of a branch, only if it ran the project's current test command
verified() { local f; f=$(rec "$1"); [ -f "$f" ] && jq -r --arg c "$TESTCMD" 'select(.command == $c) | .sha + " " + .result' "$f" 2>/dev/null; }

# journal_ref REPO REF OLD NEW VERB -> appends one line to the lead's ref journal ($DA_STATE/ref-journal.jsonl) after a local
# branch or tag was created (OLD empty), moved or deleted (NEW empty) by one of qargi's own verbs. `qargi local verify` and
# `local clean` accept a change of a run's refs that this journal explains, and name the verb, so the changes the lead made while
# a run was out are not blamed on the executor. Append only, under flock; the guard (lib/guard.py) keeps an agent from writing it.
# A failure here is a warning, never a failure of the verb: the work is done, only a later `local verify` would then want the lead's
# changes explained.
journal_ref() { journal_line "$1" "$2" "${3:-}" "${4:-}" "$5" ''; }
# journal_push REF OLD NEW VERB -> the same for a ref of origin that VERB just pushed (NEW empty: deleted there). The line also
# carries remote "origin" and the origin URL as url_key writes it, so the run of a repository URL finds it. OLD is what origin had
# (the remote-tracking ref after a fetch, or the live answer); when that was not so, the journal does not lead to origin's value
# and verify names the change: the safe side.
journal_push() {
  local u; u=$(g remote get-url origin 2>/dev/null) || u=''
  journal_line "$REPO" "$1" "${2:-}" "${3:-}" "$4" "$(url_key "$u")"
}
journal_line() { # REPO REF OLD NEW VERB URL [WHY]: one line; with URL a ref of origin, with WHY the reason the lead gave (qargi ref record)
  local repo ref old new verb zero=0000000000000000000000000000000000000000 f=${DA_STATE:-}/ref-journal.jsonl
  ref=$2 old=${3:-$zero} new=${4:-$zero} verb=$5
  repo=$(readlink -f "$1" 2>/dev/null) || repo=$1
  [ -n "${DA_STATE:-}" ] && case $ref in refs/heads/?*|refs/tags/?*) ;; *) false;; esac \
    && ( umask 077; flock 9 && jq -nc --arg at "$(now)" --argjson ep "$(date +%s)" --arg v "$verb" --arg p "${PROJ:-}" --arg r "$repo" \
           --arg ref "$ref" --arg o "$old" --arg n "$new" --arg by "$(id -un 2>/dev/null || echo unknown)@$(hostname 2>/dev/null || echo unknown)" \
           --arg u "$6" --arg w "${7:-}" \
           '{at:$at, epoch:$ep, verb:$v, project:$p, repo:$r, ref:$ref, old:$o, new:$n, by:$by}
            + (if $u == "" then {} else {remote:"origin", url:$u} end) + (if $w == "" then {} else {why:$w} end)' >> "$f" ) 9> "$f.lock" \
    || echo "qargi: warning: the ref journal could not be written for $ref ($verb); a later 'qargi local verify' of a run prepared before this may not accept the change" >&2
  return 0
}
# remote_was BRANCH -> what origin had for BRANCH as far as this repository knows: the remote-tracking ref (current after a fetch)
remote_was() { g rev-parse -q --verify "refs/remotes/origin/$1" 2>/dev/null || true; }
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
# changelog_check REF -> with the answer release.changelog.numbered true: 0 when CHANGELOG.md at REF has no duplicate item number under the
# unreleased heading, 1 when it has (the report is printed, see lib/changelog_numbers.py). 0 without the answer, without a CHANGELOG.md at REF
# or without the heading: nothing to check.
changelog_check() {
  local tmp out rc=0
  jq -e '(.release? // {}).changelog.numbered == true' "$af" >/dev/null 2>&1 || return 0
  g cat-file -e "$1:CHANGELOG.md" 2>/dev/null || return 0
  tmp=$(mktemp -d "$DA_STATE/.changelog.XXXXXX") || return 0
  g show "$1:CHANGELOG.md" > "$tmp/CHANGELOG.md" 2>/dev/null
  out=$(python3 -I "$(dirname "${BASH_SOURCE[0]}")/changelog_numbers.py" renumber "$tmp/CHANGELOG.md" "$af" --check 2>/dev/null) || rc=$?
  rm -rf "$tmp"
  [ "$rc" = 1 ] || return 0
  printf '%s\n' "$out"
  return 1
}

WT=''
cleanup() { [ -z "$WT" ] || { g worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"; WT=''; }; }
# busy_begin KIND NAME / busy_end: a whole-suite run is in progress. The pid file $DA_STATE/busy/PROJECT.KIND.NAME.pid is what
# `qargi lead compact-check` reads (a live pid: not now); busy_end and the EXIT trap remove it, and a file whose pid is gone is ignored.
BUSY=''
busy_begin() { mkdir -p "$DA_STATE/busy" 2>/dev/null; BUSY=$DA_STATE/busy/$PROJ.$1.${2//\//_}.pid; echo "$$" > "$BUSY" 2>/dev/null || BUSY=''; }
busy_end() { [ -z "$BUSY" ] || rm -f "$BUSY"; BUSY=''; }
# lead_advice [--feature NAME]: the one line of the stage verbs (feature finish, the last merge of a feature, release finish, marshal handoff):
# the lead's context in use and whether a compact is safe now (lib/lead_usage.py). Fail-soft: it never changes the status of the verb.
lead_advice() {
  python3 -I "$(dirname "${BASH_SOURCE[0]}")/lead_usage.py" advice --state "$DA_STATE" --conf "$DA_CONF" --project "${PROJ:-}" "$@" 2>/dev/null || true
}
on_exit() { marshal_hold_stop; busy_end; cleanup; }
trap on_exit EXIT   # the lease renewer never outlives the verb, whatever way it ended
worktree() { # commit-ish -> a detached temporary worktree there (WT)
  WT=$(mktemp -d "$DA_STATE/release-wt.XXXXXX")
  g worktree add -q --detach "$WT" "$1" 2>/dev/null || { rm -rf "$WT"; WT=''; die "could not make a temporary worktree of $1"; }
}
held() { g worktree list --porcelain | awk -v b="refs/heads/$1" '/^worktree /{w=substr($0,10)} $1=="branch" && $2==b {print w}' | head -1; }
need_free() { # BRANCH... -> dies when one is checked out anywhere; for the project's main checkout it names the parking branch
  local b w hint
  for b in "$@"; do
    w=$(held "$b"); [ -z "$w" ] && continue
    if [ "$(readlink -f "$w")" = "$(readlink -f "$REPO")" ]; then
      if branch_exists "${PARK:-scratch}"; then hint="git -C $w switch ${PARK:-scratch}, then qargi feature park"; else hint="git -C $w switch -c ${PARK:-scratch} develop"; fi
      die "$b is checked out in $w, the project's main checkout: leave it on the parking branch (answers repo.parking_branch): $hint (qargi moves $b without touching a working tree)"
    fi
    die "$b is checked out in $w: check out another branch there first, for example git -C $w checkout --detach (qargi moves $b without touching a working tree)"
  done
}
# Worktrees. qargi makes them under the root (answers worktrees.root, default <state>/worktrees/<project>), one per branch at ROOT/<branch>
# (feature start --worktree), so every worktree of the project is found in one place.
wt_path() { readlink -f -m -- "$1"; }
wt_in_root() { case $(wt_path "$1") in "$(wt_path "$WT_ROOT")"/*) return 0;; esac; return 1; }   # PATH is under the root
# wt_of BRANCH -> the worktree holding BRANCH, only when it is under the root (a worktree qargi made); nothing otherwise
wt_of() { local w; w=$(held "$1"); [ -n "$w" ] && wt_in_root "$w" && echo "$w"; return 0; }
# need_free_wt BRANCH -> like need_free, but a clean worktree under the root may hold it (it is brought up to date by wt_follow); a dirty one dies
need_free_wt() {
  local w; w=$(wt_of "$1")
  if [ -n "$w" ]; then
    [ -z "$(git -C "$w" status --porcelain 2>/dev/null)" ] || die "$1 is checked out in $w, which has uncommitted changes: commit or discard them there first"
    return 0
  fi
  need_free "$1"
}
# wt_follow BRANCH NEW -> after BRANCH moved to NEW by update-ref: the clean worktree under the root that holds it is brought along
wt_follow() { local w; w=$(wt_of "$1"); [ -z "$w" ] || git -C "$w" reset -q --hard "$2" || echo "qargi: warning: could not bring the worktree $w up to date with $1" >&2; }
# wt_drop BRANCH -> detaches and removes the worktree under the root that holds BRANCH (it is clean: need_free_wt checked), before the branch is deleted
wt_drop() {
  local w; w=$(wt_of "$1"); [ -n "$w" ] || return 0
  git -C "$w" checkout -q --detach 2>/dev/null
  if g worktree remove "$w" 2>/dev/null; then echo "removed the worktree $w"; rmdir -p "$(dirname "$w")" 2>/dev/null || true
  else echo "qargi: warning: could not remove the worktree $w; remove it yourself: git worktree remove $w" >&2; fi
}
# wt_outside_report -> a line for each worktree of the project that is not under the root, with the git worktree move that fixes it. Not
# reported: the main checkout, any worktree inside it (the agent runtime makes its own there; qargi never does, validate forbids a root
# inside the repository) and qargi's temporary worktrees under the state directory.
wt_outside_report() {
  local w first=1 b
  while IFS=$'\t' read -r w b; do
    if [ -n "$first" ]; then first=''; continue; fi
    wt_in_root "$w" && continue
    case $(wt_path "$w") in "$(wt_path "$REPO")"/*) continue;; "$(wt_path "$DA_STATE")"/*) continue;; esac
    echo "worktree outside the root: $w (${b:-detached}): mkdir -p $(dirname "$WT_ROOT/${b:-$(basename "$w")}") && git worktree move $w $WT_ROOT/${b:-$(basename "$w")}"
  done < <(g worktree list --porcelain | awk '/^worktree /{if (w != "") print w "\t" b; w=substr($0,10); b=""} $1=="branch"{b=$2; sub("^refs/heads/","",b)} END{if (w != "") print w "\t" b}')
}
# push_feature BRANCH -> pushes a feature branch the flow just created or moved, as the answers branches.push_features say: never (the
# default), when-shared (only when origin already has the branch: it is live-checked) or always. A plain push, never forced; a failure
# is a warning. Nothing but a feature branch is pushed here (develop and master keep their plans and tokens).
push_feature() {
  case ${PUSH_FEATURES:-never} in never) return 0;; when-shared|always) ;; *) return 0;; esac
  local was
  g remote get-url origin >/dev/null 2>&1 || return 0
  if [ "$PUSH_FEATURES" = when-shared ]; then remote_tip "$1"; [ "$RSTATE" = found ] || return 0; was=$RTIP; else was=$(remote_was "$1"); fi
  if g push -q origin "refs/heads/$1:refs/heads/$1" 2>/dev/null; then journal_push "refs/heads/$1" "$was" "$(sha_of "$1")" feature:push; echo "pushed $1 to origin (branches.push_features: $PUSH_FEATURES)"
  else echo "qargi: warning: could not push $1 to origin (branches.push_features: $PUSH_FEATURES); origin is unchanged" >&2; fi
}
# parking_follow -> one status line. After qargi moved develop: the main checkout on the parking branch, clean and with no commit
# of its own, is fast-forwarded to develop (git merge --ff-only in that checkout); otherwise the line says why it was left. The
# parking branch is never pushed and never merged anywhere.
parking_follow() {
  local cur old n why
  cur=$(git -C "$REPO" branch --show-current 2>/dev/null)
  if [ "$cur" != "$PARK" ]; then why="the main checkout is on ${cur:-a detached head}"
  elif [ -n "$(git -C "$REPO" status --porcelain 2>/dev/null)" ]; then why="the main checkout has uncommitted changes"
  else
    n=$(g rev-list --count "develop..$PARK"); old=$(sha_of "$PARK")
    if [ "$n" != 0 ]; then why="$PARK has $n commit(s) that develop lacks"
    elif [ "$old" = "$(sha_of develop)" ]; then echo "parking branch $PARK: already at develop"; return 0
    elif git -C "$REPO" merge -q --ff-only develop >/dev/null 2>&1; then
      journal_ref "$REPO" "refs/heads/$PARK" "$old" "$(sha_of "$PARK")" park:follow
      echo "parking branch $PARK: fast-forwarded to develop ($(g rev-parse --short develop))"; return 0
    else why="the fast-forward failed"; fi
  fi
  echo "parking branch $PARK: not advanced ($why)"
}
# Detached long-lived branches (answers repo.detached) never meet the git-flow branches: no merge in either direction.
is_detached() { [ -n "${DETACHED:-}" ] && printf '%s\n' "$DETACHED" | grep -Fxq -- "$1"; }
# history_of SRC INTO OTHER -> 0 when merging SRC into INTO would bring in commits of OTHER that INTO lacks (a best common ancestor
# of SRC and OTHER that INTO does not contain), so a branch cut from OTHER, or OTHER itself, is caught whatever it is called
history_of() { local mb; for mb in $(g merge-base --all "$1" "$3" 2>/dev/null); do g merge-base --is-ancestor "$mb" "$2" || return 0; done; return 1; }
# detached_mix SRC INTO -> dies when merging the branch SRC into the branch INTO would join a detached branch with develop, master,
# a release, hotfix or feature branch. Nothing has changed when it dies. Merging an agent branch cut from a detached branch into it is fine.
detached_mix() {
  local src=$1 into=$2 x
  [ -n "${DETACHED:-}" ] || return 0
  if is_detached "$into"; then
    is_detached "$src" || case $src in master|develop|release/*|hotfix/*|feature/*) die "$src is a git-flow branch and $into is a detached branch (repo.detached): they are never merged";; esac
    for x in $(g for-each-ref --format='%(refname:short)' refs/heads/master refs/heads/develop 'refs/heads/release/*' 'refs/heads/hotfix/*' 'refs/heads/feature/*'); do
      ! history_of "$src" "$into" "$x" || die "merging $src into $into would bring in history of $x; $into is a detached branch (repo.detached) and never meets develop, master, release, hotfix or feature branches. Task branches for it are cut from $into"
    done
  else
    ! is_detached "$src" || die "$src is a detached branch (repo.detached) and $into is not: they are never merged"
    for x in $DETACHED; do
      ! branch_exists "$x" || ! history_of "$src" "$into" "$x" || die "merging $src into $into would bring in history of $x, a detached branch (repo.detached) that never meets develop, master, release, hotfix or feature branches"
    done
  fi
}
run_clean() { # DIR COMMAND...: runs a command in DIR without the project's cloud binding: a suite or a release check must not see it
  local dir=$1; shift
  (cd "$dir" && env -u ANTHROPIC_PROFILE -u QARGI_CLOUD_WORKSPACE -u QARGI_CLOUD_PROJECT "$@")
}
run_suite() { run_clean "$WT" bash -c "$TESTCMD"; }   # the project's test command in the worktree WT
# run_suite_logged NAME -> run_suite with its output (both streams, on stdout) shown as it comes and kept in
# $DA_STATE/suite-logs/PROJECT.NAME.log (SUITE_LOG; mode 600; the last run of that name). The status is the suite's.
run_suite_logged() {
  local rc
  SUITE_LOG=$DA_STATE/suite-logs/$PROJ.${1//\//_}.log
  if ( umask 077; mkdir -p "$DA_STATE/suite-logs" && : > "$SUITE_LOG" ) 2>/dev/null; then
    run_suite 2>&1 | tee "$SUITE_LOG"
    rc=${PIPESTATUS[0]}
  else SUITE_LOG=''; run_suite; rc=$?; fi
  return "$rc"
}
# suite_failure_report -> after a failed run_suite_logged, the last lines of the verb's output: the failing steps (`FAILED: step` lines of
# tests/run.sh) and failing tests (`FAIL name` lines) its report holds, where its own logs of the failed steps are, and the log of the
# whole run. A test command that is no tests/run.sh has neither: its last lines stand in.
suite_failure_report() {
  local f=${SUITE_LOG:-} steps names dir
  if [ -n "$f" ] && [ -s "$f" ]; then
    steps=$(sed -n 's/^FAILED: //p' "$f" | awk '!s[$0]++')
    names=$(grep -E '^FAIL( |:)' "$f" | awk '!s[$0]++')
    dir=$(sed -n 's/^logs of the failed steps: //p' "$f" | tail -1)
    if [ -n "$steps" ]; then echo "failing steps:"; printf '%s\n' "$steps" | head -20 | sed 's/^/  /'; fi
    if [ -n "$names" ]; then echo "failing tests:"; printf '%s\n' "$names" | head -20 | sed 's/^/  /'; fi
    if [ -z "$steps$names" ]; then echo "no failing test name in the output; its last lines:"; tail -5 "$f" | sed 's/^/  /'; fi
    [ -z "$dir" ] || echo "logs of the failed steps: $dir"
  fi
  [ -z "$f" ] || echo "log of the whole run: $f"
}
# git_common DIR -> the real path of the common git directory of the repository DIR belongs to
git_common() {
  local c; c=$(git -C "$1" rev-parse --git-common-dir 2>/dev/null) || return 1
  case $c in /*) ;; *) c=$1/$c;; esac
  readlink -f -- "$c"
}
# suite_cmdline PID -> 0 when the process is a shell running a tests/run.sh
suite_cmdline() {
  local cl; cl=$(tr '\0' ' ' < "/proc/$1/cmdline" 2>/dev/null) || return 1
  [[ $cl =~ ^(([^\ ]*/)?(bash|sh|dash|zsh)\ +(-[^\ ]+\ +)*)?([^\ ]*/)?tests/run\.sh(\ |$) ]]
}
# other_runs_warning -> warnings on stderr (the verb goes on) when something else of this project may be running a suite: a whole-suite
# run of qargi in progress (a live pid in $DA_STATE/busy), a local run of the registry for this repository with a file changed in the
# last QARGI_ACTIVE_MINUTES (default 10), or a tests/run.sh process whose directory belongs to this repository (Linux: /proc). Two suites
# at once slow each other and fail on timeouts they would not meet alone.
other_runs_warning() {
  local rp mins=${QARGI_ACTIVE_MINUTES:-10} f b pid d line p cwd common anc q
  rp=$(readlink -f -- "$REPO" 2>/dev/null) || rp=$REPO
  case $mins in ''|*[!0-9]*) mins=10;; esac
  for f in "$DA_STATE/busy/$PROJ."*.pid; do
    [ -e "$f" ] || continue
    pid=$(cat "$f" 2>/dev/null) || continue
    case $pid in ''|*[!0-9]*) continue;; esac
    kill -0 "$pid" 2>/dev/null || continue
    b=${f##*/}; b=${b#"$PROJ".}; b=${b%.pid}
    echo "qargi: warning: another whole-suite run of $PROJ is in progress ($b, pid $pid): two suites at once slow both and can fail on timeouts; going on" >&2
  done
  reg_load
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do
    line=${LRUNS[$d]}
    [ "$(jq -r --arg p "$rp" 'select(.repo == $p and ((.cleaned // "") == "")) | "x"' <<<"$line" 2>/dev/null)" = x ] || continue
    [ -d "$d" ] || continue
    [ -n "$(find "$d" -maxdepth 4 -mmin "-$mins" -print -quit 2>/dev/null)" ] || continue
    echo "qargi: warning: the local run $d of $PROJ had activity in the last $mins minutes: its member may be running tests; going on" >&2
  done
  [ -d "/proc/$$" ] || return 0
  common=$(git_common "$REPO") || return 0
  anc=" "; q=$$
  while [ -n "$q" ] && [ "$q" -gt 1 ]; do anc="$anc$q "; q=$(awk '/^PPid:/ {print $2}' "/proc/$q/status" 2>/dev/null); done
  for p in /proc/[0-9]*; do
    pid=${p#/proc/}
    case $anc in *" $pid "*) continue;; esac
    suite_cmdline "$pid" || continue
    q=$(awk '/^PPid:/ {print $2}' "$p/status" 2>/dev/null)
    [ -z "$q" ] || ! suite_cmdline "$q" || continue   # a worker of a run counted already
    cwd=$(readlink "$p/cwd" 2>/dev/null) || continue
    [ "$(git_common "$cwd")" = "$common" ] || continue
    echo "qargi: warning: tests/run.sh is running in this repository (pid $pid, in $cwd): two suites at once slow both and can fail on timeouts; going on" >&2
  done
}
# suite_mode COMMAND -> how a suite command runs its steps, from its words: "-j N" and/or "shard I/K" ("" when it names neither)
suite_mode() {
  local mode=''
  if [[ $1 =~ (^|[[:space:]])-j[[:space:]]*([0-9]+)([[:space:]]|$) ]]; then mode="-j ${BASH_REMATCH[2]}"; fi
  if [[ $1 =~ --shard[[:space:]]+([0-9]+/[0-9]+)([[:space:]]|$) ]]; then mode="${mode:+$mode, }shard ${BASH_REMATCH[1]}"; fi
  printf '%s' "$mode"
}
# record_suite BRANCH SHA RESULT SECONDS: the record of the last whole-suite run of BRANCH (the head, the verdict, when, the command, how
# long it took and the mode the command names), which `release status` shows
record_suite() {
  jq -nc --arg s "$2" --arg r "$3" --arg t "$(now)" --arg c "$TESTCMD" --argjson d "$4" --arg m "$(suite_mode "$TESTCMD")" \
    '{sha:$s, result:$r, at:$t, command:$c, seconds:$d, mode:$m}' > "$(rec "$1")"
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
  DETACHED=$(jq -r '(.repo.detached // [])[]' "$af")   # newline-separated: the detached long-lived branches
  DELETE_MERGED=$(jq -r '.branches.delete_merged // "local"' "$af")   # local | local+remote: where feature finish deletes the merged feature branch
  PUSH_FEATURES=$(jq -r '.branches.push_features // "never"' "$af")   # never | when-shared | always: whether the flow pushes feature branches
  PUSH_DEVELOP=$(jq -r 'if .branches.push_develop == false then "false" else "true" end' "$af")   # true (default) | false: whether feature finish pushes develop
  WT_ROOT=$(jq -r '.worktrees.root // ""' "$af"); WT_ROOT=${WT_ROOT/#\~/$HOME}   # where qargi makes worktrees: ROOT/<branch>
  [ -n "$WT_ROOT" ] || WT_ROOT=$DA_STATE/worktrees/$PROJ
  PARK=$(jq -r '.repo.parking_branch // "scratch"' "$af")   # the branch the main checkout rests on while qargi moves develop
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
