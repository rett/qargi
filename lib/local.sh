#!/usr/bin/env bash
# Local dispatch without a way to push: the agent works in a clone of a bare copy that
# has no remote, runs git through a credential-less wrapper, and the coordinator
# compares every ref of the real repository (and of its remote) before and after.
#
#   local.sh prepare (--repo DIR | --repo-url URL [--credential-file FILE]) --base BRANCH --slug SLUG --scratch DIR [--role R] [--profile NAME]
#                                        (the submodules the role declares in roles.R.tools are checked out in the clone from the lead's
#                                        copy of their objects, offline, and printed as SUBMODULES=path,...; lib/tools.py)
#   local.sh verify RUN_DIR
#   local.sh verify RUN_DIR | --saved ID     (--saved: the lead's copy of a passed run whose directory is gone, $QARGI_STATE/runs/ID)
#   local.sh close RUN_DIR --applied-by-am   mark a verified run whose patches the lead applied by hand (git am) closed: not open any more, files kept
#   local.sh clean RUN_DIR [--discard]   remove a collected, verified run and its temporary directory (--discard: whatever verify says)
#   local.sh clean --applied --scratch DIR   remove every run under DIR whose work is applied and merged; keep and name the others
#   local.sh clean --stale DAYS --scratch DIR [--yes]   list the finished runs (verified or applied) under DIR older than DAYS; with --yes clean them
#   local.sh clean --orphans [--days N] [--plan TOKEN --approved WORDS]   list the qargi-run.* directories of the run temporary parent (/dev/shm, or QARGI_RUN_TMP)
#                                        that no run of the registry names, each with its age; a plan and token first, then only the ones older than N days (2) are removed
#   local.sh list [--scratch DIR]        read-only: each run (under DIR, else the registry's) with role, slug, age, applied and merged; a run whose
#                                        directory is gone (and that clean did not remove) says "directory gone", and names its saved copy
#   local.sh run RUN_DIR [--task FILE] [--model TIER|ID] [--effort LEVEL] [--timeout SECONDS] [--again] [--dry-run]
#                                        start the member of a prepared run as a command line, for a runtime whose dispatch.mode is "command"
#                                        (lib/local_run.py says how); a runtime that dispatches in the lead's session is refused
#
# This stops every ordinary push (`git push`, `git push origin`, a pushurl, a remote added
# from a config). It is not a sandbox against an agent that deliberately goes around it
# (it runs as the same user): `verify` is what turns such an attempt into a loud failure.
# The run directory records the task's ability (RUN/ability, default build) and, under --profile, the profile (RUN/profile); under review the guard
# (qargi __guard) refuses every change to the clone, so a review writes only to OUT.
# A run based on feature/X of a stored project first asks the marshal (marshal_check): another live lead holds X -> refused, no run
# is made; warnings go to stderr. The lead of X is recorded in the run line as "lead" (null when nobody leads it).
# prepare also appends one JSON line per run to $QARGI_STATE/local-runs.jsonl (run directory, slug, ability, base,
# start time, temporary directory, and the repository: its real path (repo), or its URL (url) and the path of its credential file (cred), never a token;
# the class of the run (class: write or read-only; the class file of the run directory is a member's), the stored project of the repository (project) and a copy of the answers that decide what verification accepts (answers: runs.owned_refs, repo.long_lived,
# repo.parking_branch, git.author, review.keep_author, review.scrub, review.trailer_policy) as they are at prepare; mode 600), so `qargi report` can list the local runs. Verify, clean and
# review apply read those answers from this line and not from the stored project's file, which is not the lead's alone to write: an answer changed after
# prepare takes effect on the runs prepared after it. The registry is the lead's and the only record `verify`, `clean`, `run` and `review apply` believe
# about a run (lib.sh run_record): the repository, the URL and the credential path come from it, and a run whose own repo.path, repo.url or cred.path
# (files a member can write) differ is refused, as is a directory the registry does not name. `clean` removes the temporary directory that this line names
# for the run, not the one the run's own tmpdir file says (a member can write the run directory, and a file there could name another run's temporary directory).
# A --scratch on a tmpfs (stat -f) is warned about on stderr: a reboot empties it and the run is lost. A passing verify copies OUT, a run bundle and
# the snapshots to $QARGI_STATE/runs/<run id>/ (save_run), so `review apply --from-saved ID` can still apply the work after a reboot; clean removes the copy.
# After the TASK-BLOCK PATHS lines it prints TASK-BLOCK MEMORY (tiercontext.py packet: the tier summary, the always rows of the
# indexes and the no-write rule; the repo tier is the clone's committed copy) when the repository belongs to a stored project.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$0")/marshal.sh"
. "$(dirname "$0")/orphans.sh"

# NOREPORT_CAUSE: the likely reason OUT holds no report. A runtime can refuse a member's write tool for a report file (the member is told to return findings as
# text), and the file then never reaches OUT: the member is not late, it is blocked. verify and clean name it where they find OUT without a report.
NOREPORT_CAUSE="A runtime can refuse a member's write tool for a report file, so the file never reaches OUT: tell the member to write its OUT files (report, manifest, series) with the shell, a heredoc, and to collect again."

# drop_qargi_refs -> stdin without the refs under refs/qargi/ (lines "local REF SHA" and "remote SHA REF"). The marshal refs backend
# keeps its records there and the lead's renewer fetches and pushes them during a run; that is not an agent push. Only that
# namespace: refs/qargi-x/ and every other ref stay compared.
drop_qargi_refs() { awk '{ r = ($1 == "local") ? $2 : $3 } r !~ /^refs\/qargi\//'; }

snapshot_url() { # url credential-file(optional) -> sorted refs of the remote
  ( [ -z "${2:-}" ] || git_auth_env "$2"
    u=$1; [ -z "${2:-}" ] || u=${1/https:\/\//https://x-access-token@}
    out=$(timeout 60 git ls-remote --heads --tags "$u" 2>/dev/null </dev/null) && printf '%s\n' "$out" | sed 's/^/remote /' | drop_qargi_refs | sort || echo "remote unavailable" )
}

snapshot() { # repo -> sorted refs of the repository and of its remote
  git -C "$1" for-each-ref --format='local %(refname) %(objectname)' | drop_qargi_refs | sort
  if git -C "$1" remote get-url origin >/dev/null 2>&1; then
    if out=$(timeout 60 git -C "$1" ls-remote --heads --tags origin 2>/dev/null </dev/null); then
      printf '%s\n' "$out" | sed 's/^/remote /' | drop_qargi_refs | sort
    else
      echo "remote unavailable"
    fi
  fi
}

# merged_tip REPO TIP [BRANCH [RUN]] -> 0 when the commit TIP (the second word of a run's applied file, which a member can write) is on a local branch
# other than agent/*, a worktree-bridge-* branch or a ref the run's answers declare owned, 1 when it is not, 2 when there is no tip that is a full hex object name;
# the tip of BRANCH's review:apply line in the lead's ref journal replaces TIP when there is one. A tip the lead rewrote (qargi ref record --rewrite: the same
# tree, journaled as ref:rewrite) counts as merged when the commit it was rewritten to is. The test is lib/merged.py, the one place that knows
# it: lead compact-check and feature finish (lib/lead_usage.py) ask the same function, so a run is settled for list, clean and compact-check alike.
merged_tip() {
  local rc=0 ans=''
  # BRANCH (the first word of the applied file) and RUN: the lead's journal names the tip of that branch's review:apply, and the run's answers in the lead's registry
  # (reg_load first) name the refs that are the runtime's own; neither is read from the run directory
  [ -z "${4:-}" ] || ans=$(reg_json "$4" '.answers // empty')
  python3 -I "$(dirname "$0")/merged.py" "$1" "$2" --state "$DA_STATE" ${3:+--branch "$3"} ${ans:+--answers "$ans"} || rc=$?
  case $rc in 0|2) return "$rc";; *) return 1;; esac
}

# rewrite_hint REPO BRANCH -> nothing, or the sentence that names the fix when the lead rewrote the applied branch by hand: BRANCH is at a commit other than the
# tip of its review:apply line in the lead's ref journal (the tip merged_tip tests), the two commits have the same tree (what qargi ref record --rewrite
# records), and no rewrite of the journaled tip is recorded yet. The branch and the tips are checked before they reach git or the terminal: BRANCH is the
# first word of the member's applied file, the journal is the lead's.
rewrite_hint() {
  local jt cur rp qb
  [ -n "${1:-}" ] && [ -n "${2:-}" ] && [ -f "$DA_STATE/ref-journal.jsonl" ] || return 0
  git check-ref-format "refs/heads/$2" 2>/dev/null || return 0
  case $2 in agent/?*) ;; *) return 0;; esac   # the one kind of branch qargi ref record --rewrite moves
  rp=$(readlink -f -- "$1" 2>/dev/null) || rp=$1
  jt=$(jq -r --arg r "$rp" --arg b "refs/heads/$2" 'select(type == "object" and .verb == "review:apply" and .repo == $r and .ref == $b and (has("remote") | not) and (.new | type) == "string") | .new' \
    "$DA_STATE/ref-journal.jsonl" 2>/dev/null | tail -n 1)
  [[ $jt =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || return 0
  cur=$(git -C "$1" rev-parse -q --verify "refs/heads/$2^{commit}" 2>/dev/null) || return 0
  [ "$cur" != "$jt" ] || return 0
  jq -e --arg r "$rp" --arg o "$jt" 'select(type == "object" and .verb == "ref:rewrite" and .repo == $r and .old == $o)' "$DA_STATE/ref-journal.jsonl" >/dev/null 2>&1 && return 0   # recorded already
  [ "$(git -C "$1" rev-parse -q --verify "$jt^{tree}" 2>/dev/null)" = "$(git -C "$1" rev-parse -q --verify "$cur^{tree}" 2>/dev/null)" ] || return 0
  qb=$(printf '%q' "$2")   # the two commands are meant to be pasted: a name with a $ or a ; in it (git allows both) stays one word
  printf '%s' "$2 is at $cur, not at the tip $jt that review apply journaled: it was rewritten by hand (the same tree). Put it back and record the rewrite, so that clean follows it: git branch -f $qb $jt, then qargi ref record --rewrite $qb $jt $cur --why \"...\""
}

# journal_steps SIDE NAME OLD NEW -> 0 and the verbs, in order, of the lead's ref journal ($DA_STATE/ref-journal.jsonl) that explain the change
# of the ref NAME from OLD to NEW (a sha, or 40 zeros for absent) since the run began (JSTART, an epoch); SIDE is local (a branch or tag of
# the repository CREPO) or remote (a ref of its origin; for the run of a repository URL, the lines of that URL, CURLK). NEW must be reachable
# from OLD by following lines of this repository, side and ref with epoch >= JSTART, each from its old value to its new one. Lines that
# start elsewhere (an earlier creation made in the same second as the run) are not on the path, and an unjournaled hand anywhere breaks it,
# because no line starts where the hand left the ref. A rewrite (qargi ref record --rewrite) is named with the reason the lead gave.
# Trusted only as far as the state directory is (the guard keeps an agent from writing it; same-user code could).
journal_steps() {
  local f=$DA_STATE/ref-journal.jsonl rp='' out
  [ -f "$f" ] && [ -n "${JSTART:-}" ] || return 1
  [ -z "${CREPO:-}" ] || { rp=$(readlink -f "$CREPO" 2>/dev/null) || rp=$CREPO; }
  [ -n "$rp" ] || [ -n "${CURLK:-}" ] || return 1
  out=$(jq -sre --arg r "$rp" --arg u "${CURLK:-}" --arg side "$1" --arg n "$2" --arg o "$3" --arg w "$4" --argjson s "$JSTART" '
    def mine: if $side == "remote" then .remote == "origin" and (($r != "" and .repo == $r) or ($u != "" and .url == $u))
              else (has("remote") | not) and $r != "" and .repo == $r end;
    [ .[] | select(type == "object" and .ref == $n and ((.epoch // 0) >= $s) and mine and (.old | type) == "string" and (.new | type) == "string") ] as $e
    | reduce range(0; ($e | length) + 1) as $i ({($o): -1};
        reduce range(0; $e | length) as $j (.; if has($e[$j].old) and (has($e[$j].new) | not) then .[$e[$j].new] = $j else . end))
    | select($w != $o and has($w)) | . as $p
    | [ $w | recurse(if . != $o then $e[$p[.]].old else empty end) | select(. != $o) | $e[$p[.]] ] | reverse
    | map(if .verb == "ref:rewrite" then "a rewrite (qargi ref record --rewrite: " + ((.why // "") | tostring) + ")" else "qargi " + ((.verb // "?") | tostring | sub(":"; " ")) end)
    | reduce .[] as $v ([]; if index([$v]) then . else . + [$v] end) | join(", ")' "$f" 2>/dev/null) && [ -n "$out" ] || return 1
  printf '%s\n' "$out" | LC_ALL=C tr -d '\000-\011\013-\037\177'   # the reason is the lead's text: no control or escape byte reaches the terminal
}

# save_run RUN -> a copy of what a passed run returned, in the lead's state: $DA_STATE/runs/<run id>/ holds out/ (the run's OUT, links copied as links,
# never followed), run.bundle (when the run directory has one beside OUT), the snapshots and records verify and apply read (refs.before, verified,
# started, ability, class, profile, applied) and record.json (the registry's line). Made in a temporary directory and renamed into place; a failure is a
# warning, never a failure of verify.
save_run() {
  local run id d tmp f rr
  run=$(readlink -f -- "$1") || return 0; id=${run##*/}; d=$DA_STATE/runs/$id
  case $id in qargi.??????) ;; *) return 0;; esac   # a directory prepare made: never an empty or a dotted name, whatever the caller wrote
  { mkdir -p "$DA_STATE/runs" && tmp=$(mktemp -d "$DA_STATE/runs/.save.XXXXXX"); } || { echo "qargi: warning: could not save a copy of $run in $DA_STATE/runs" >&2; return 0; }
  if cp -R --no-dereference --preserve=mode,timestamps -- "$run/out" "$tmp/out" 2>/dev/null; then
    [ ! -f "$run/run.bundle" ] || [ -L "$run/run.bundle" ] || cp -- "$run/run.bundle" "$tmp/run.bundle"
    for f in refs.before verified started ability class profile applied; do [ ! -f "$run/$f" ] || [ -L "$run/$f" ] || cp -- "$run/$f" "$tmp/$f"; done
    rr=$(readlink -m -- "$run"); printf '%s\n' "${LRUNS[$rr]:-}" > "$tmp/record.json"
    if [ ! -L "$d" ] && rm -rf --one-file-system -- "$d" && mv -T -- "$tmp" "$d"; then echo "saved a copy of the run's output in $d (qargi review apply --from-saved $id applies it if the run directory is lost)"; return 0; fi
  fi
  rm -rf --one-file-system -- "$tmp"
  echo "qargi: warning: could not save a copy of $run in $d" >&2
}
# saved_of RUN -> the lead's saved copy of RUN ($DA_STATE/runs/<run id>), when there is one (a directory, not a link)
saved_of() { local d=$DA_STATE/runs/${1##*/}; case ${1##*/} in qargi.??????) ;; *) return 0;; esac; [ -d "$d" ] && [ ! -L "$d" ] && echo "$d"; return 0; }
# scrub_ok_drop RUN: remove the record `review check` keeps for a run whose take-in scrub passed (scrub_ok/RUN-ID in the lead's state, the path rule of
# scrub_ok_file in review.sh): a run that was checked and never applied leaves it, and clean removes the run
scrub_ok_drop() { local id=${1##*/}; case $id in qargi.??????) rm -f -- "$DA_STATE/scrub_ok/$id";; esac; return 0; }
# gone_runs SCR -> the runs of the registry (reg_load first) directly under SCR (a real path; every run of the registry when empty) whose directory is
# gone and that clean did not remove: a reboot emptied a tmpfs, or the directory was removed by hand
gone_runs() {
  local d
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do
    [ -z "$1" ] || [ "${d%/*}" = "$1" ] || continue
    case ${d##*/} in qargi.??????) ;; *) continue;; esac
    [ ! -e "$d" ] && [ ! -L "$d" ] && [ -z "$(reg_get "$d" cleaned)" ] && printf '%s\n' "$d"
  done
  return 0
}
# scratch_of DIR -> the real path of a --scratch DIR; a directory that is gone is still one when the registry names runs under it (a reboot removed it)
scratch_of() {
  local s
  if [ -d "$1" ]; then readlink -f -- "$1"; return 0; fi
  s=$(readlink -m -- "$1"); [ -n "$(gone_runs "$s")" ] || return 1
  echo "$s"
}

# parking_of -> the parking branch of the answers of the run being checked (run_answers: repo.parking_branch), else scratch
parking_of() {
  local p
  p=$(run_answers | jq -r '((.repo | objects | .parking_branch) // "") | strings' 2>/dev/null) || p=''
  echo "${p:-scratch}"
}

# bridge_ref REPO NAME OLD NEW -> 0 when the change of the local branch NAME (refs/heads/worktree-bridge-S) is the harness's own. A branch that exists now
# (NEW) is the harness's when the worktree that holds it is the real path <main worktree>/<the harness directory>/worktrees/bridge-S, is locked (the harness locks it), and
# the move (OLD, when there was one) is a fast-forward. A branch that is gone (NEW empty) is the harness's only when no worktree named bridge-S is left
# and none holds the branch. Anything else, a rewrite of the lead's own bridge branch or a worktree a member added elsewhere, is not.
bridge_ref() {
  local repo=$1 ref=$2 old=$3 new=$4 s main='' held=0 k p l
  s=${ref#refs/heads/worktree-bridge-}
  while IFS=$'\t' read -r k p l; do
    case $k in M) main=$(readlink -f -- "$p");; H) held=1; [ -n "$new" ] || return 1
      [ -n "$main" ] && [ "$(readlink -f -- "$p")" = "$main/.claude/worktrees/bridge-$s" ] && [ "$l" = locked ] && held=2;; esac
  done < <(git -C "$repo" worktree list --porcelain 2>/dev/null | awk -v ref="$ref" -v tail="/worktrees/bridge-$s" '
    function chk() { if (n++ == 0) printf "M\t%s\t\n", p; else if (br == ref || (length(p) > length(tail) && substr(p, length(p) - length(tail) + 1) == tail)) printf "H\t%s\t%s\n", p, (lk ? "locked" : "-")
      p = ""; br = ""; lk = 0; open = 0 }
    /^worktree / { if (open) chk(); p = substr($0, 10); open = 1; next } /^branch / { br = $2 } /^locked/ { lk = 1 } /^$/ { if (open) chk() } END { if (open) chk() }')
  [ -n "$new" ] || return 0                       # gone: no worktree of that name is left
  [ "$held" = 2 ] || return 1
  [ -z "$old" ] || git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null
}

# owned_declared -> succeeds when the answers of the run being checked (run_answers: the snapshot in the lead's registry, taken at prepare) declare
# runtime-owned refs (runs.owned_refs, a list of glob patterns the lead set); owned_bases -> one --base BRANCH pair per line for the base of every run of
# the registry that is not cleaned or closed: the ref a run is based on is never taken as owned, whatever a pattern says. lib/owned_refs.py decides what a
# pattern may be and whether a ref matches (hardened: a literal prefix of 3 characters, never develop, master, a long-lived branch, the git-flow branches,
# a tag or a bridge branch).
owned_declared() {
  run_answers | jq -e '((.runs | objects | .owned_refs) // []) | type == "array" and length > 0' >/dev/null 2>&1
}
owned_bases() {
  local d b
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do
    [ -z "$(reg_get "$d" cleaned)" ] && [ -z "$(reg_get "$d" closed)" ] || continue
    b=$(reg_get "$d" base); [ -z "$b" ] || printf '%s\n%s\n' --base "$b"
  done
  return 0
}

# compare REPO REF AFTER [strict] [ACCEPTED] -> prints each offending change, returns 1 if there is one; each change it accepts is named in
# the file ACCEPTED, one line each. Refs under refs/qargi/ are not compared (see drop_qargi_refs). A change is accepted, in either phase, when
#   - the lead's ref journal explains it (journal_steps): a branch or a tag of the repository, or a branch or tag of its origin, moved,
#     created or deleted by qargi's own verbs (feature finish and park, release and hotfix finish, branch prune, review apply, the
#     parking branch following develop, a rewrite the lead recorded ...); a peeled tag line of origin (TAG^{}) goes with its tag;
#   - a remote-tracking ref refs/remotes/origin/X now says what origin has (a fetch or a push did that; origin's own ref is compared
#     on its own line), or a tag of the repository is now origin's tag of the same name (fetched);
#   - the parking branch (answers repo.parking_branch, default scratch) was fast-forwarded to develop's tip, by hand or by qargi;
#   - a branch worktree-bridge-S of the harness's bridge worktree, a directory worktrees/bridge-S (bridge_ref: while that worktree, locked, at <main worktree>/<the harness directory>/worktrees/bridge-S, holds it and the move is a fast-forward, or when no such worktree is left).
# A branch, or a branch of origin, that the lead made and noted (qargi ref note) is the journal's case above: its line starts where the ref was absent.
#   - a local ref that matches a pattern of the answer runs.owned_refs (refs a runtime or harness creates in the repository, set by the lead, validated by
#     project validate; lib/owned_refs.py: a literal prefix of 3 characters, never develop, master, a long-lived or git-flow branch, a tag, a bridge branch
#     or the base of a run). The answers are the run's own: the copy prepare took into the lead's registry (run_answers), not the stored file of today:
#     accepted in either phase and named with the pattern. A ref that matches none is checked as before, in the strict phase too.
# Without strict (after the run's first passing verify, against RUN/verified) also: a fast-forward of develop, master or an
# agent|feature|release|hotfix/* branch, and a new agent|feature|release|hotfix/* branch: the lead's own merges. Everything else, a rewrite
# or a deletion nobody journaled, a tag or a push made by hand, any other ref, is offending.
compare() {
  local repo=$1 ref=$2 aft=$3 strict=${4:-} acc=${5:-/dev/null} bad=0 k kind name old new steps park='' dev tgt short a b c uo='' un='' hasr=''
  local zero=0000000000000000000000000000000000000000 why=" (not in the lead's ref journal)"
  local -A O=() N=() ACC=()
  local ownf='' pat='' obase=() oans=''   # oans: the answers of the run (run_answers), read once
  while read -r a b c; do case $a in local) O["local $b"]=$c;; remote) if [ "$b" = unavailable ] && [ -z "$c" ]; then uo=1; else O["remote $c"]=$b; fi;; esac; done < <(drop_qargi_refs < "$ref")
  while read -r a b c; do case $a in local) N["local $b"]=$c;; remote) if [ "$b" = unavailable ] && [ -z "$c" ]; then un=1; else N["remote $c"]=$b; fi;; esac; done < <(drop_qargi_refs < "$aft")
  if [ "$uo" != "$un" ]; then
    echo "origin could not be asked $([ -n "$un" ] && echo "now" || echo "when the snapshot was taken"): its refs cannot be compared"; bad=1
  fi
  [ -z "$repo" ] || ! git -C "$repo" remote get-url origin >/dev/null 2>&1 || [ -n "$un" ] || hasr=1
  dev=${N["local refs/heads/develop"]:-}
  if owned_declared; then ownf=1; oans=$(run_answers); mapfile -t obase < <(owned_bases); fi
  allowed() { case $1 in refs/heads/develop|refs/heads/master|refs/heads/agent/*|refs/heads/feature/*|refs/heads/release/*|refs/heads/hotfix/*) return 0;; esac; return 1; }
  shortref() { case $1 in refs/heads/*) echo "${1#refs/heads/}";; refs/tags/*) echo "tag ${1#refs/tags/}";; *) echo "$1";; esac; }
  while read -r k; do
    [ -n "$k" ] || continue
    kind=${k%% *}; name=${k#* }; old=${O[$k]:-}; new=${N[$k]:-}
    [ "$old" != "$new" ] || continue
    short=$(shortref "$name"); [ "$kind" = local ] || short="$short on origin"
    if [ -z "$old" ]; then a=created; elif [ -z "$new" ]; then a=deleted; else a=moved; fi
    # the lead's ref journal: qargi's own verbs
    case $name in
      *'^{}') if [ "$kind" = remote ] && [ -n "${ACC["remote ${name%'^{}'}"]:-}" ]; then ACC[$k]=1; continue; fi;;
      refs/heads/?*|refs/tags/?*)
        if steps=$(journal_steps "$kind" "$name" "${old:-$zero}" "${new:-$zero}"); then ACC[$k]=1; echo "$short $a by $steps" >> "$acc"; continue; fi;;
    esac
    if [ "$kind" = local ] && [[ $name == refs/heads/worktree-bridge-?* ]] && bridge_ref "$repo" "$name" "$old" "$new"; then
      ACC[$k]=1; echo "$short $a (the harness's bridge branch of a worktree bridge-NAME)" >> "$acc"; continue
    fi
    if [ "$kind" = local ] && [ -n "$ownf" ] && pat=$(python3 -I "$(dirname "$0")/owned_refs.py" match - "$name" ${obase[@]+"${obase[@]}"} <<<"$oans"); then
      ACC[$k]=1; echo "$short $a; accepted: $pat (owned by the runtime, per runs.owned_refs)" >> "$acc"; continue
    fi
    if [ "$kind" = local ]; then
      # a remote-tracking ref of origin that says what origin has now, and a tag fetched from origin
      case $name in
        refs/remotes/origin/HEAD)
          tgt=$(git -C "$repo" symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null) || tgt=''
          if [ -n "$hasr" ] && [ -n "$tgt" ] && [ "$new" = "${N["local $tgt"]:-}" ]; then ACC[$k]=1; continue; fi;;
        refs/remotes/origin/?*)
          if [ -n "$hasr" ] && [ "$new" = "${N["remote refs/heads/${name#refs/remotes/origin/}"]:-}" ]; then ACC[$k]=1; echo "origin/${name#refs/remotes/origin/} $a to what origin has (a fetch or a push)" >> "$acc"; continue; fi;;
        refs/tags/?*)
          if [ -n "$hasr" ] && [ -n "$new" ] && [ "$new" = "${N["remote $name"]:-}" ]; then ACC[$k]=1; echo "$short $a as origin has it (fetched)" >> "$acc"; continue; fi;;
      esac
      # the parking branch fast-forwarded to develop's tip
      if [ -n "$old" ] && [ -n "$new" ] && [ "$new" = "$dev" ] && [[ $name == refs/heads/?* ]]; then
        [ -n "$park" ] || park=$(parking_of)
        if [ "$name" = "refs/heads/$park" ] && git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null; then
          ACC[$k]=1; echo "$short (the parking branch) fast-forwarded to develop" >> "$acc"; continue
        fi
      fi
      # after a passing verify: the lead's fast-forwards and new branches
      if [ -z "$strict" ] && [[ $name == refs/heads/?* ]]; then
        if [ -n "$old" ] && [ -n "$new" ] && allowed "$name"; then
          if git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null; then ACC[$k]=1; echo "$short fast-forwarded (a lead-side move after the run's passing verify)" >> "$acc"; continue; fi
          echo "branch rewritten (not a fast-forward): $name $old -> $new$why"; bad=1; continue
        fi
        if [ -z "$old" ] && allowed "$name"; then
          case $name in refs/heads/develop|refs/heads/master) ;; *) ACC[$k]=1; echo "$short created (a lead-side branch after the run's passing verify)" >> "$acc"; continue;; esac
        fi
        if [ -z "$new" ]; then echo "branch deleted: $name (was $old)$why"
        elif [ -z "$old" ]; then echo "branch created, not an allowed branch: $name $new$why"
        else echo "branch moved, not an allowed branch: $name $old -> $new$why"; fi
        bad=1; continue
      fi
    fi
    case $kind:$name in
      local:refs/heads/*)
        if [ -z "$new" ]; then echo "branch deleted: $name (was $old)$why"
        elif [ -z "$old" ]; then echo "branch created: $name $new$why"
        else echo "branch moved: $name $old -> $new$why"; fi;;
      local:refs/tags/*) echo "tag $a: $name ${old:-(none)} -> ${new:-(none)}$why";;
      local:refs/remotes/*) echo "remote-tracking ref $a: $name ${old:-(none)} -> ${new:-(none)} (it does not say what origin has)";;
      local:*) echo "ref $a: $name ${old:-(none)} -> ${new:-(none)}";;
      remote:*) echo "ref of origin $a: $name ${old:-(none)} -> ${new:-(none)}$why";;
    esac
    bad=1
  done < <({ printf '%s\n' "${!O[@]}"; printf '%s\n' "${!N[@]}"; } | LC_ALL=C sort -u)
  return $bad
}

# check RUN [DIR] -> 0 and records DIR/verified when the refs are as the rule allows (DIR/refs.accepted names the changes it accepted); 2 otherwise;
# 3 when the registry does not vouch for RUN. DIR holds the snapshots: the run directory, or the lead's saved copy of the run (verify --saved).
check_run() {
  local run=$1 dir=${2:-$1} ref strict=1
  if [ "$dir" = "$run" ]; then run_record "$run" || return 3   # the repository and the credential come from the lead's registry, never from the run directory
  else reg_record "$run" || return 3; fi
  ref=$dir/refs.before
  # the run's start (an epoch) bounds the lead's ref journal: prepare records it in RUN/started; with none, no change is journaled
  JSTART=$(cat "$dir/started" 2>/dev/null || true); [[ $JSTART =~ ^[0-9]{1,12}$ ]] || JSTART=''
  [ ! -f "$dir/verified" ] || { ref=$dir/verified; strict=''; }
  CREPO=$RUN_REPO CURLK=''
  if [ -n "$RUN_URL" ]; then
    CURLK=$(url_key "$RUN_URL")
    snapshot_url "$RUN_URL" "$RUN_CRED" > "$dir/refs.after"
  else
    snapshot "$RUN_REPO" > "$dir/refs.after"
  fi
  : > "$dir/refs.accepted"
  if compare "$RUN_REPO" "$ref" "$dir/refs.after" "$strict" "$dir/refs.accepted" > "$dir/refs.diff"; then
    [ -z "${NOREC:-}" ] || return 0   # NOREC: a verify that cannot pass (the member did not collect) compares the refs but records nothing
    cp "$dir/refs.after" "$dir/verified"
    return 0
  fi
  return 2
}

# render_warning REPO URL -> when the project this run belongs to has a render of its packs (packs apply --target T, T the render target of its
# provider; the render is state/render/PROJECT/RUNTIME), runs the read-only check of the render and, on findings, prints a WARNING block to stderr. Never fails the caller: a stale
# render must not block work. The project is the stored answers whose repo.path (or repo.url) is the one given; none found, nothing printed.
# No render directory (the usual case) costs no process: the glob below is the shell's own.
# A project with no provider cannot be checked (there is no default one): one note line says so and that the check was skipped. The check
# is asked for the render only ('--render-only'): the section about the skills a session would load is no part of whether the render is
# out of date, and a drifted accepted skill must not read as one. A provider that cannot render at all (exit 3) is nothing to warn about.
render_warning() {
  local m d prj f rp ru out rc pv rt pe lb
  for m in "$DA_STATE"/render/*/*/MANIFEST.json; do
    [ -f "$m" ] || continue
    d=$(dirname "$m"); prj=$(basename "$(dirname "$d")"); f=$DA_CONF/projects/$prj.json
    [ -f "$f" ] || continue
    rp=$(jq -r '.repo.path // ""' "$f" 2>/dev/null); rp=${rp/#\~/$HOME}; ru=$(jq -r '.repo.url // ""' "$f" 2>/dev/null)
    if [ -n "$1" ]; then [ -n "$rp" ] && [ "$(readlink -f "$rp")" = "$(readlink -f "$1")" ] || continue
    else [ -n "$ru" ] && [ "${ru%.git}" = "${2%.git}" ] || continue; fi
    rc=0; pv=$(python3 -I "$(dirname "$0")/provider.py" of "$prj" --conf "$DA_CONF" --surface local 2>/dev/null </dev/null) || rc=$?
    if [ "$rc" = 2 ]; then   # the render is the local surface's: an object that names only a cloud runtime is the same as none
      pe=$(python3 -I "$(dirname "$0")/provider.py" of "$prj" --conf "$DA_CONF" --surface local 2>&1 </dev/null) || true
      case $pe in
        *"has no local provider"*) echo "note: project $prj has no local provider (qargi project set $prj models.provider.local NAME); the render check was skipped" >&2;;
        *) echo "note: project $prj has no provider (qargi project set $prj models.provider NAME); the render check was skipped" >&2;;
      esac
      return 0
    fi
    # the render of a runtime is that runtime's; a project that has moved to another runtime has no render of it to check here
    [ "$rc" = 0 ] && [ "$pv" = "$(basename "$d")" ] || continue
    rt=$(python3 -I "$(dirname "$0")/provider.py" layout "$pv" render_target 2>/dev/null </dev/null) || return 0
    rc=0; out=$("$(dirname "$0")/packs.sh" packs check --target "$rt" '--render-only' "$prj" 2>&1) || rc=$?
    [ "$rc" != 0 ] && [ "$rc" != 3 ] || return 0
    lb=$(python3 -I "$(dirname "$0")/packs_render.py" label "$pv" 2>/dev/null </dev/null) || lb=$pv
    { echo "WARNING: the $lb render of project $prj is out of date or altered (the run goes on):"
      sed 's/^/  /' <<<"$out"
      echo "  fix: qargi packs apply --target $rt $prj"
      echo; } >&2
    return 0
  done
  return 0
}

verb=${1:-}; shift || true
case $verb in
  prepare)
    REPO='' URL='' CRED='' BASE='' SLUG='' SCR='' ROLE=build PROFILE=''
    while [ $# -gt 0 ]; do
      case $1 in --repo) need_val "$1" $#; REPO=$2; shift 2;; --repo-url) need_val "$1" $#; URL=$2; shift 2;; --credential-file) need_val "$1" $#; CRED=$2; shift 2;; --base) need_val "$1" $#; BASE=$2; shift 2;; --slug) need_val "$1" $#; SLUG=$2; shift 2;; --scratch) need_val "$1" $#; SCR=$2; shift 2;; --role) need_val "$1" $#; ROLE=$2; shift 2;; --profile) need_val "$1" $#; PROFILE=$2; shift 2;; *) usage_die "unknown option $1";; esac
    done
    if [ -n "$URL" ]; then
      [ -z "$REPO" ] || usage_die "give --repo or --repo-url, not both"
      case $URL in https://*) ;; *) die "--repo-url must be an https URL";; esac
      uauth=${URL#https://}; uauth=${uauth%%[/?#]*}
      case $uauth in *@*) die "--repo-url must not carry a user name or a password (https://USER@host): the URL is recorded and put in commands; give the token with --credential-file";; esac
      [ -z "$CRED" ] || { CRED=${CRED/#\~/$HOME}; [ -f "$CRED" ] || die "--credential-file: no such file"; CRED=$(readlink -f -- "$CRED"); }
    else
      [ -d "$REPO/.git" ] || [ -f "$REPO/.git" ] || die "--repo must be a git working tree"
      REPO=$(readlink -f -- "$REPO")   # recorded as a real path: the registry and RUN/repo.path say the same text
    fi
    [ "$ROLE" != lead ] && valid_role "$ROLE" || die "--role: one of $DA_ROLES (qargi role list)"
    CLASS=$(role_class "$ROLE")
    # a read-only role needs a read-only barrier on the local surface, or the project's recorded acceptance that there is none
    if [ "$CLASS" = read-only ]; then
      BPJ=$(project_of "$REPO" "$URL")
      [ -n "$BPJ" ] || { echo "qargi: no stored project has this repository, so no provider is known and a read-only role cannot start: store it (qargi project attach) and give it a provider (qargi project set PROJECT models.provider NAME)" >&2; exit 2; }
      barrier_guard local "$BPJ"
    fi
    valid_slug "$SLUG" || die "--slug: lower-case letters, digits and '-'"
    [ -n "$BASE" ] && [ -d "$SCR" ] || usage_die "prepare needs --base BRANCH and --scratch DIR"
    SCR=$(readlink -f -- "$SCR")   # an absolute run directory: the registry and every later verb name it from any working directory
    # a tmpfs (a ramfs) is emptied by a reboot: the clone, the commits and the output of a run there are lost
    case $(stat -f -c %T -- "$SCR" 2>/dev/null) in
      tmpfs|ramfs) echo "qargi: warning: --scratch $SCR is on a tmpfs: a reboot loses the run (its clone, commits and output). Prefer a directory on disk, for example ~/.cache/qargi-runs; a passing verify saves a copy of the output in $DA_STATE/runs" >&2;;
    esac
    # a profile is resolved (by the one resolver, `agent for`) before anything is made: a refusal leaves no run directory
    MEMBER='' MODEL='' EFFORT=''
    if [ -n "$PROFILE" ]; then
      PPJ=$(project_of "$REPO" "$URL"); pargs0=(for "$ROLE" --profile "$PROFILE" --json)
      [ -z "$PPJ" ] || pargs0+=(--project "$PPJ")
      PRES=$("$(dirname "$0")/agent.sh" "${pargs0[@]}" 2>&1 </dev/null) || die "${PRES#qargi: }"
      MEMBER=$(jq -r '.member // ""' <<<"$PRES"); MODEL=$(jq -r '.model // "-"' <<<"$PRES"); EFFORT=$(jq -r '.effort // "-"' <<<"$PRES")
    else
      PROFILE=$ROLE
    fi
    # the contract addenda of the project's runtime on the local surface (resources.contract_addenda of its definition), read before anything
    # is made; a repository in no project, or a project with no local runtime, gets the core's contract alone (no runtime is assumed)
    ADDENDA='' CPJ=$(project_of "$REPO" "$URL")
    # what verification and review apply will believe of the lead's answers is taken now, into the lead's registry line (the stored project's file is not read again for this run):
    # the project's name and the answers runs.owned_refs, repo.long_lived, repo.parking_branch, git.author and review.keep_author, scrub and trailer_policy, as they are today
    ANS='{}'
    if [ -n "$CPJ" ]; then
      ANS=$(jq -c 'def at(f): first(f, null); def own(k): if type == "object" then {(k): at(.[k])} else . end; def owns(ks): if type == "object" then . as $o | reduce ks[] as $k ({}; .[$k] = ($o | at(.[$k]))) else . end;
        {runs: ((at(.runs) | own("owned_refs"))), repo: {long_lived: at(.repo | objects | .long_lived), parking_branch: at(.repo | objects | .parking_branch)},
         git: (at(.git) | own("author")), review: (at(.review) | owns(["keep_author", "scrub", "trailer_policy"]))}' "$DA_CONF/projects/$CPJ.json" 2>/dev/null) \
        || die "the answers of project $CPJ cannot be read, so the run could not record them; nothing was made (qargi project validate $CPJ)"
    fi
    if [ -n "$CPJ" ]; then
      # a provider that is set but does not resolve is refused here, not left out of the contract
      CPROV=$(project_provider_if_set "$CPJ" local) || die "the local provider of project $CPJ does not resolve, so the contract addenda of its runtime cannot be added; nothing was made (qargi project show $CPJ)"
      [ -z "$CPROV" ] || ADDENDA=$(python3 -I "$(dirname "$0")/provider.py" addenda "$CPROV" local </dev/null) || die "could not read the contract addenda of the local runtime $CPROV (qargi provider check $CPROV)"
    fi
    LEAD=''
    case $BASE in
      feature/?*)
        MPROJ=$(project_of "$REPO" "$URL")
        if [ -n "$MPROJ" ]; then
          mrc=0; merr=$(mktemp "$DA_STATE/.marshal-gate.XXXXXX" 2>/dev/null) || merr=/dev/null
          marshal_check "$MPROJ" "${BASE#feature/}" 2>"$merr" || mrc=$?
          if [ "$merr" != /dev/null ]; then
            cat "$merr" >&2
            if [ "$mrc" = 1 ] && grep -q '^Traceback' "$merr"; then mrc=70; fi   # an exception also exits 1, but it is not a refusal
            rm -f "$merr"
          fi
          [ "$mrc" -ne 1 ] || exit 1   # another live lead holds the feature: the message is printed, no run is made
          [ "$mrc" -eq 0 ] || echo "qargi: warning: the marshal could not be asked (status $mrc); the run goes on" >&2
          LEAD=$("$(dirname "$0")/marshal.sh" status "${BASE#feature/}" --project "$MPROJ" --json 2>/dev/null | jq -r '.lead.id // empty' 2>/dev/null) || LEAD=''
        fi;;
    esac
    RUN=$(mktemp -d "$SCR/qargi.XXXXXX")
    mkdir -p "$RUN/out" "$RUN/home" "$RUN/contract"
    # the member reads the contract from the run: the core's files, then the runtime's addenda as one more file (CONTRACT below)
    cp "$(prompt_root)/contract/"*.md "$RUN/contract/" || die "could not copy the contract"
    [ -z "$ADDENDA" ] || printf '%s\n' "$ADDENDA" > "$RUN/contract/runtime-addenda.md"
    # a private temporary directory for the run's test sandboxes, on tmpfs when there is one; `clean` removes it, so a run
    # leaves nothing behind in /dev/shm and parallel runs never touch each other's files
    SHM=${QARGI_RUN_TMP:-/dev/shm}   # QARGI_RUN_TMP moves it (the tests do), so a test never leaves anything in /dev/shm
    while [ "${SHM%/}" != "$SHM" ] && [ "$SHM" != / ]; do SHM=${SHM%/}; done   # clean compares the parent as written
    if [ -d "$SHM" ] && [ -w "$SHM" ]; then TMPD=$(mktemp -d "$SHM/qargi-run.XXXXXX"); else TMPD=$RUN/tmp; mkdir -p "$TMPD"; fi
    printf '%s\n' "$TMPD" > "$RUN/tmpdir"
    printf '%s\n' "$ROLE" > "$RUN/ability"
    printf '%s\n' "$CLASS" > "$RUN/class"
    [ -z "$MEMBER" ] || printf '%s\n' "$PROFILE" > "$RUN/profile"
    date +%s > "$RUN/started"   # the epoch the lead's ref journal is read from by `verify`
    if [ -n "$URL" ]; then
      snapshot_url "$URL" "$CRED" > "$RUN/refs.before"
      printf '%s\n' "$URL" > "$RUN/repo.url"; [ -z "$CRED" ] || printf '%s\n' "$CRED" > "$RUN/cred.path"   # a path, never the token
      ( [ -z "$CRED" ] || git_auth_env "$CRED"
        u=$URL; [ -z "$CRED" ] || u=${URL/https:\/\//https://x-access-token@}
        git clone -q --bare "$u" "$RUN/bare.git" </dev/null ) || die "could not clone $URL (is the credential valid?)"
    else
      snapshot "$REPO" > "$RUN/refs.before"
      echo "$REPO" > "$RUN/repo.path"
      git clone -q --bare --no-hardlinks "$REPO" "$RUN/bare.git" || die "bare copy failed"
    fi
    git -C "$RUN/bare.git" remote remove origin 2>/dev/null || true
    git -C "$RUN/bare.git" config --unset-all remote.origin.url 2>/dev/null || true
    git clone -q --no-hardlinks "$RUN/bare.git" "$RUN/clone" || die "clone failed"
    git -C "$RUN/clone" remote set-url --push origin DISABLED
    git -C "$RUN/clone" rev-parse --verify -q "origin/$BASE" >/dev/null || die "no branch $BASE in the repository"
    git -C "$RUN/clone" checkout -q -b "agent/$SLUG" "origin/$BASE"
    # the submodules the role declares (roles.ROLE.tools, kind submodule) are checked out in the clone from the lead's copy of their objects,
    # offline (lib/tools.py checkout): a commit that is not on this host, or a run cloned from a URL, is a note on stderr and nothing is fetched
    SUBS='' SPROJ=$(project_of "$REPO" "$URL")
    if [ -n "$SPROJ" ]; then
      sargs=(checkout --answers "$DA_CONF/projects/$SPROJ.json" --role "$ROLE" --clone "$RUN/clone" --copies "$RUN/sub")
      [ -z "$REPO" ] || sargs+=(--source "$REPO")
      SUBS=$(python3 -I "$(dirname "$0")/tools.py" "${sargs[@]}" </dev/null) || SUBS=''
    fi
    cat > "$RUN/git" <<WRAP
#!/usr/bin/env bash
# git without credentials: no home, no global config, no ssh, no prompts.
exec env -i HOME="$RUN/home" PATH="\$PATH" LANG=C.UTF-8 TERM=dumb \\
  GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_SSH_COMMAND=false \\
  GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=false \\
  GIT_AUTHOR_NAME=qargi GIT_COMMITTER_NAME=qargi \\
  GIT_AUTHOR_EMAIL=qargi@example.invalid GIT_COMMITTER_EMAIL=qargi@example.invalid \\
  git "\$@"
WRAP
    chmod 755 "$RUN/git"
    jq -nc --arg r "$RUN" --arg s "$SLUG" --arg a "$ROLE" --arg b "$BASE" --arg t "$(now)" --arg l "$LEAD" --arg p "$PROFILE" --arg d "$TMPD" --arg rp "$REPO" --arg ru "$URL" --arg rc "$CRED" --arg pj "$CPJ" --argjson ans "$ANS" --arg cl "$CLASS" \
      '{run:$r, slug:$s, ability:$a, profile:$p, base:$b, started:$t, lead:(if $l == "" then null else $l end), tmpdir:$d, class:$cl, project:$pj, answers:$ans}
       + (if $ru == "" then {repo:$rp} else {url:$ru} + (if $rc == "" then {} else {cred:$rc} end) end)' | ( umask 077; flock 9 && cat >> "$DA_STATE/local-runs.jsonl" ) 9> "$DA_STATE/local-runs.jsonl.lock"
    chmod 600 "$DA_STATE/local-runs.jsonl" 2>/dev/null || true
    render_warning "$REPO" "$URL"
    echo "RUN=$RUN"
    echo "ROLE=$ROLE"
    echo "CLASS=$CLASS"
    echo "PROFILE=$PROFILE"
    [ -z "$MEMBER" ] || { echo "MEMBER=$MEMBER"; echo "MODEL=$MODEL"; echo "EFFORT=$EFFORT"; }
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    BSHA=$(git -C "$RUN/clone" rev-parse "origin/$BASE")
    echo "BASE_SHA=$BSHA"
    echo "CONTRACT=$RUN/contract"
    [ -z "$SUBS" ] || echo "$SUBS"
    echo
    echo "TASK-BLOCK PATHS"
    echo "RUN_DIR=$RUN"
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    echo "BASE_SHA=$BSHA"
    echo "CONTRACT=$RUN/contract"
    # the memory context packet: the tier summary and the always rows, for a repository that belongs to a stored project.
    # It never changes prepare's result: a failure or a timeout prints nothing.
    PPROJ=$(project_of "$REPO" "$URL")
    if [ -n "$PPROJ" ]; then
      tc=$(dirname "$(readlink -f "$0")")/tiercontext.py
      prel=$(timeout 3 python3 -I "$tc" repo-rel --project "$PPROJ" 2>/dev/null </dev/null) || prel=''
      pargs=(--project "$PPROJ" --role "$ROLE")
      [ -z "$prel" ] || pargs+=(--repo-tier "$RUN/clone/$prel")
      [ -z "$REPO" ] || [ -z "$prel" ] || pargs+=(--checkout "$REPO")
      if pkt=$(timeout 8 python3 -I "$tc" packet "${pargs[@]}" </dev/null) && [ -n "$pkt" ]; then
        printf '\nTASK-BLOCK MEMORY\n%s\n' "$pkt"
      fi
    fi;;
  verify)
    SAVED=''
    if [ "${1:-}" = --saved ]; then
      # the lead's saved copy of a passed run whose directory is gone: its snapshots are compared (against its last passing verify) as the run's own would be
      need_val "$1" $#; SAVED=${2:-}; [ $# = 2 ] || usage_die "verify --saved takes one ID"
      case $SAVED in qargi.??????) ;; *) usage_die "verify --saved takes the id of a run: the name of its directory, qargi.XXXXXX";; esac
      SRC=$DA_STATE/runs/$SAVED
      [ -d "$SRC" ] && [ ! -L "$SRC" ] && [ -f "$SRC/refs.before" ] || die "no saved copy of $SAVED in $DA_STATE/runs (local verify saves one when a run passes)"
      reg_load; RUN=$(reg_id "$SAVED") || { echo "qargi: the lead's registry names no run $SAVED (or more than one)" >&2; exit 3; }
    else
      RUN=${1:-}; [ -f "$RUN/refs.before" ] || usage_die "verify needs a RUN dir made by prepare"
      SRC=$RUN
    fi
    # a read-only run's product is a report, never patches: patches in its output are not to be applied or accepted
    if [ "$(run_class "$RUN" "$SRC")" = read-only ] && [ -n "$(find "$SRC/out" -maxdepth 2 \( -name '*.patch' -o -name run.bundle \) 2>/dev/null | head -1)" ]; then
      echo "qargi: $RUN is a read-only run ($(cat "$SRC/ability" 2>/dev/null || echo review)) and its output holds patches. A read-only run's product is a report, never patches: read $SRC/out/report.md, and do not apply or accept the patches." >&2
      exit 2
    fi
    marshal_touch_run "$RUN"   # the lead's verify keeps its lease on the feature the run is based on
    # the member did not collect: the clone holds commits past BASE_SHA and OUT holds neither patches nor a report. The refs are compared all the same (a run
    # that broke out and did not collect still gets its ref verdict) and said next to the message, but nothing is recorded: the run is not verified, and apply
    # and close need a passing verify. (clean asks verify for the refs alone, QARGI_VERIFY_REFS_ONLY: it has its own check for the manifest.) Not for a saved
    # copy, which exists only for a passed run.
    NOREC='' EMPTY=''
    if [ -z "$SAVED" ] && [ -z "${QARGI_VERIFY_REFS_ONLY:-}" ]; then
      ncm=$(git -C "$RUN/clone" rev-list --count --branches HEAD --not --remotes=origin 2>/dev/null || echo 0)
      if [ "${ncm:-0}" -gt 0 ] && [ -z "$(find "$RUN/out" -maxdepth 2 -name '*.patch' 2>/dev/null | head -1)" ] && ! out_has_report "$RUN/out"; then
        EMPTY="qargi: OUT is empty: the member did not collect. $RUN/clone holds $ncm commit(s) past BASE_SHA, but $RUN/out holds no patches and no report. The member's DONE needs \`ls OUT/patches\` to list the patches (git format-patch --binary BASE_SHA..HEAD into OUT/patches, then the manifest and report). This run is not verified, and apply and close need a passing verify: send it back to collect and verify again, or take the commits from the clone yourself and drop the run with qargi local clean RUN --discard. $NOREPORT_CAUSE"
        NOREC=1
      fi
    fi
    # a read-only run's product is its report: none in OUT is said (a note; the refs verdict below is the exit status), with the likely cause
    if [ -z "$SAVED" ] && [ -z "${QARGI_VERIFY_REFS_ONLY:-}" ] && [ "$(run_class "$RUN" "$SRC")" = read-only ] && ! out_has_report "$RUN/out"; then
      echo "qargi: note: OUT of the read-only run $RUN holds no report (report.md or NAME-report.md). $NOREPORT_CAUSE" >&2
    fi
    reg_load; crc=0; NOREC=$NOREC check_run "$RUN" "$SRC" || crc=$?
    if [ "$crc" = 3 ]; then
      exit 3   # run_record said why: the registry does not vouch for this run directory, so no repository was asked
    elif [ -n "$EMPTY" ]; then
      if [ "$crc" = 0 ]; then echo "refs: unchanged by the run (compared all the same; nothing was recorded)" >&2
      else
        echo "REFS CHANGED during the run (the agent must not have pushed):" >&2
        cat "$SRC/refs.diff" >&2
        if [ -s "$SRC/refs.accepted" ]; then echo "accepted as the lead's own moves:" >&2; sed 's/^/  /' "$SRC/refs.accepted" >&2; fi
      fi
      echo "$EMPTY" >&2
      exit $((crc == 0 ? 1 : 2))
    elif [ "$crc" = 0 ]; then
      reg_mark "$RUN" verified "$(now)"   # the registry says so after the run directory is gone (marshal status, handoff: "verified", never "not verified")
      if [ -s "$SRC/refs.accepted" ]; then
        if grep -q 'per runs\.owned_refs)$' "$SRC/refs.accepted"; then echo "refs differ from the snapshot only by the lead's own moves and the refs the project declares the runtime's own (runs.owned_refs); nothing was pushed by the run:"
        else echo "refs differ from the snapshot only by the lead's own moves; nothing was pushed by the run:"; fi
        sed 's/^/  /' "$SRC/refs.accepted"
      else echo "refs unchanged: nothing was pushed to the repository or its remote"; fi
      [ -n "$SAVED" ] || save_run "$RUN"   # what the run returned outlives its directory (a reboot that empties a tmpfs)
    else
      echo "REFS CHANGED during the run (the agent must not have pushed):" >&2
      cat "$SRC/refs.diff" >&2
      if [ -s "$SRC/refs.accepted" ]; then echo "accepted as the lead's own moves:" >&2; sed 's/^/  /' "$SRC/refs.accepted" >&2; fi
      [ ! -f "$SRC/verified" ] && echo "(before the run's first passing verify a ref may differ only as far as the lead's ref journal names it, a remote-tracking ref follows origin, or the parking branch is fast-forwarded to develop)" >&2 \
        || echo "(after a passing verify the lead's fast-forwards and new branches are accepted too; nothing else that the lead's ref journal does not name)" >&2
      exit 2
    fi;;
  clean)
    # after the series is collected and verified: remove the run (clone, bare copy, output, wrapper) and its temporary directory.
    #   clean RUN [--discard]            one run; --discard drops it on purpose, whatever verify says and whatever it holds
    #   clean --applied --scratch DIR    every run directly under DIR whose work is recorded applied (RUN/applied) and merged
    #   clean --stale DAYS --scratch DIR [--yes]   the finished runs (RUN/verified or RUN/applied) older than DAYS: a plan, removed only with --yes
    CLEAN_RUN='' DISCARD='' ALL='' SCR='' STALE='' YES='' ORPH='' DAYS='' PLAN_ARG='' APPROVED=''
    while [ $# -gt 0 ]; do
      case $1 in
        --discard) DISCARD=1; shift;;
        --applied) ALL=1; shift;;
        --stale) need_val "$1" $#; STALE=${2:-}; shift 2;;
        --yes) YES=1; shift;;
        --orphans) ORPH=1; shift;;
        --days) need_val "$1" $#; DAYS=${2:-}; shift 2;;
        --plan) need_val "$1" $#; PLAN_ARG=${2:-}; shift 2;;
        --approved) need_val "$1" $#; APPROVED=${2:-}; shift 2;;
        --scratch) need_val "$1" $#; SCR=${2:-}; shift 2;;
        -*) usage_die "clean: unknown option $1";;
        *) [ -z "$CLEAN_RUN" ] || usage_die "clean takes one RUN dir"; CLEAN_RUN=$1; shift;;
      esac
    done
    [ -n "$ORPH" ] || [ -z "$DAYS$PLAN_ARG$APPROVED" ] || usage_die "clean: --days, --plan and --approved are for --orphans"
    if [ -n "$ORPH" ]; then
      # the private temporary directories prepare makes (qargi-run.XXXXXX under /dev/shm, or QARGI_RUN_TMP) that no run of the lead's registry names: a prepare that
      # failed after making one, a registry line that was dropped, a state directory that was replaced. Each is listed with its age and whether the registry names it.
      # Only an unnamed one that is older than N days (default 2) and has nothing in it newer than that is ever removed, and only behind a plan token and the lead's
      # words. A named directory is never removed here, live or not: clean RUN removes it with its run.
      [ -z "$ALL$CLEAN_RUN$DISCARD$STALE$YES$SCR" ] || usage_die "clean --orphans takes no RUN dir, no --applied, --discard, --stale, --yes and no --scratch"
      DAYS=${DAYS:-2}
      case $DAYS in ''|*[!0-9]*|0) usage_die "clean --orphans --days needs a whole number of days, at least 1 (a directory prepare made a moment ago is not yet named), got '$DAYS'";; esac
      oroot=${QARGI_RUN_TMP:-/dev/shm}
      while [ "${oroot%/}" != "$oroot" ] && [ "$oroot" != / ]; do oroot=${oroot%/}; done
      [ -d "$oroot" ] && [ ! -L "$oroot" ] || die "clean --orphans: $oroot is not a directory"
      oroot=$(readlink -f -- "$oroot")
      orphan_scan "$oroot" "$DAYS"   # lib/orphans.sh: the listing, which qargi doctor reads too
      orph=(${ORPH_LIST[@]+"${ORPH_LIST[@]}"}); okept=$ORPH_KEPT; ototal=$ORPH_TOTAL
      echo "$ototal qargi-run.* director(ies) under $oroot: ${#orph[@]} orphaned for more than $DAYS day(s), $okept kept"
      if [ "${#orph[@]}" = 0 ]; then echo "plan: nothing to remove under $oroot"; exit 0; fi
      otok=$({ printf '%s\n%s\n' "$oroot" "$DAYS"; printf '%s\n' "${orph[@]}"; } | plan_token)
      if [ -z "$APPROVED" ]; then
        echo "plan: remove ${#orph[@]} orphaned director(ies) under $oroot (the ones marked orphan above); nothing changed"
        echo "plan token: $otok   (apply with: qargi local clean --orphans --days $DAYS --plan $otok --approved \"...\")"
        exit 0
      fi
      QARGI_NESTED='' need_plan "$otok"   # a caller that is itself approved (QARGI_NESTED) has not approved this removal: the token is always needed
      rm_n=0; rk_n=0
      for ent in "${orph[@]}"; do
        e=${ent% *}; reg_load
        # checked again at the moment of removal: still a real directory directly under the parent, still named by no registry
        rp=$(realpath -- "$e" 2>/dev/null) || rp=''
        named=''; for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do t=$(reg_get "$d" tmpdir); if [ -n "$t" ] && [ "$(readlink -m -- "$t")" = "$e" ]; then named=$d; fi; done
        if [ -L "$e" ] || [ "$rp" != "$e" ] || [ "$(dirname -- "$rp")" != "$oroot" ] || [ -n "$named" ]; then echo "kept $e: it changed since the plan"; rk_n=$((rk_n + 1)); continue; fi
        if rm -rf --one-file-system -- "$rp"; then echo "removed $e"; rm_n=$((rm_n + 1)); else echo "kept $e: it could not be removed"; rk_n=$((rk_n + 1)); fi
      done
      audit_log "local:clean-orphans" "$oroot $rm_n removed $rk_n kept (older than $DAYS day(s))"
      echo "removed $rm_n orphaned director(ies), kept $rk_n"
      [ "$rk_n" = 0 ] || exit 1
      exit 0
    fi
    if [ -n "$STALE" ]; then
      [ -z "$ALL$CLEAN_RUN$DISCARD" ] || usage_die "clean --stale takes no RUN dir, no --applied and no --discard: it cleans only finished runs, and each by the rules of clean"
      case $STALE in ''|*[!0-9]*) usage_die "clean --stale needs a whole number of days, got '$STALE'";; esac
      [ -n "$SCR" ] || usage_die "clean --stale needs --scratch DIR, the directory the runs were prepared in"
      reg_load; scr=$(scratch_of "$SCR") || die "clean --stale: no such directory $SCR"
      nowe=$(date +%s); plan_n=0; done_n=0; kept_n=0; bad_n=0
      for d in "$scr"/qargi.??????; do
        [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" || continue   # a directory prepare made (the registry says so), directly under DIR
        [ -f "$d/verified" ] || [ -f "$d/applied" ] || continue                                      # a run still in progress is never stale
        st=$(cat "$d/started" 2>/dev/null || true)
        [[ $st =~ ^[0-9]{1,12}$ ]] || { echo "skipped $d: no start time recorded, so its age is unknown"; continue; }   # the file is a member's: only digits reach the arithmetic
        age=$(( (nowe - st) / 86400 )); [ "$age" -ge "$STALE" ] || continue
        st=verified; [ ! -f "$d/applied" ] || st=applied
        if [ -z "$YES" ]; then echo "would clean $d ($st, ${age}d old)"; plan_n=$((plan_n + 1)); continue; fi
        if ! why=$("$0" clean "$d" 2>&1 </dev/null); then echo "kept $d: ${why#qargi: }"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        echo "$why"; done_n=$((done_n + 1))
      done
      # the runs whose directory is gone: their record (and a saved copy whose work is applied and merged, or none) is dropped; a saved copy whose work
      # was never applied is kept and named, since it is the only place that work is left
      while IFS= read -r d; do
        [ -n "$d" ] || continue
        st=$(reg_get "$d" started); ste=$(date -d "$st" +%s 2>/dev/null) || ste=''
        [[ $ste =~ ^[0-9]{1,12}$ ]] || { echo "skipped $d: directory gone, and no start time recorded, so its age is unknown"; continue; }
        age=$(( (nowe - ste) / 86400 )); [ "$age" -ge "$STALE" ] || continue
        sv=$(saved_of "$d")
        if [ -z "$YES" ]; then echo "would drop the record of $d (directory gone${sv:+, saved copy $sv}, ${age}d old)"; plan_n=$((plan_n + 1)); continue; fi
        if [ -n "$sv" ] && [ ! -f "$sv/applied" ]; then
          echo "kept $d: directory gone, and its saved copy $sv holds work that was never applied: qargi review apply --from-saved ${d##*/}, or qargi local clean $d --discard"
          kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue
        fi
        cargs=("$d"); [ -n "$sv" ] || cargs+=(--discard)   # nothing of it is left but the record
        if ! why=$("$0" clean "${cargs[@]}" 2>&1 </dev/null); then echo "kept $d: ${why#qargi: }"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        echo "$why"; done_n=$((done_n + 1))
      done < <(gone_runs "$scr")
      if [ -z "$YES" ]; then echo "plan: $plan_n finished run(s) older than $STALE day(s) under $scr; nothing changed, add --yes to clean them"; exit 0; fi
      echo "cleaned $done_n run(s), kept $kept_n"
      [ "$bad_n" = 0 ] || exit 1   # a stale run that clean refused (never applied, not merged, refs changed) stays, named, with the reason
      exit 0
    fi
    [ -z "$YES" ] || die "clean: --yes is for --stale"
    if [ -n "$ALL" ]; then
      [ -z "$CLEAN_RUN$DISCARD" ] || usage_die "clean --applied takes no RUN dir and no --discard: it cleans only what is applied and merged"
      [ -d "$SCR" ] || usage_die "clean --applied needs --scratch DIR, the directory the runs were prepared in"
      scr=$(readlink -f "$SCR"); done_n=0; kept_n=0; bad_n=0; reg_load
      for d in "$scr"/qargi.??????; do
        [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" || continue   # a directory prepare made (the registry says so), directly under DIR
        if [ ! -f "$d/applied" ] && [ -z "$(reg_get "$d" closed)" ]; then echo "kept $d: its work is not recorded applied"; kept_n=$((kept_n + 1)); continue; fi
        if [ -z "$(reg_get "$d" repo)" ] && [ -z "$(reg_get "$d" closed)" ]; then echo "kept $d: whether it is merged cannot be checked for a run of a repository URL"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        if ! why=$("$0" clean "$d" 2>&1 </dev/null); then echo "kept $d: ${why#qargi: }"; kept_n=$((kept_n + 1)); bad_n=$((bad_n + 1)); continue; fi
        echo "$why"; done_n=$((done_n + 1))
      done
      echo "cleaned $done_n run(s), kept $kept_n"
      [ "$bad_n" = 0 ] || exit 1   # an applied run that was refused (not merged, refs changed); a run still in progress is no failure
      exit 0
    fi
    [ -z "$SCR" ] || die "clean: --scratch is for --applied and --stale"
    reg_load
    RUN=$CLEAN_RUN
    while [ "${RUN%/}" != "$RUN" ] && [ "$RUN" != / ]; do RUN=${RUN%/}; done   # a trailing slash makes rm -rf follow a link
    marshal_touch_run "$RUN"   # the lead's clean keeps its lease on the feature the run is based on
    if [ -n "$RUN" ] && [ ! -e "$RUN" ] && [ ! -L "$RUN" ]; then
      # the run directory is gone (a reboot that emptied a tmpfs, or removed by hand): only the registry's record and the saved copy are left
      case ${RUN##*/} in qargi.??????) ;; *) usage_die "clean needs a RUN dir made by prepare";; esac
      reg_has "$RUN" || usage_die "clean needs a RUN dir made by prepare ($RUN is gone and the lead's registry does not name it)"
      [ -z "$(reg_get "$RUN" cleaned)" ] || die "$RUN was cleaned already"
      sv=$(saved_of "$RUN")
      if [ -z "$DISCARD" ] && [ -z "$(reg_get "$RUN" closed)" ]; then   # a closed run (local close) is taken as applied by hand
        [ -n "$sv" ] || die "$RUN is gone (directory gone) and nothing of it was saved: qargi local clean $RUN --discard drops its record"
        [ -f "$sv/applied" ] || die "$RUN is gone (directory gone), and its saved copy $sv holds work that was never applied: qargi review apply --from-saved ${RUN##*/}, then qargi feature merge (--discard drops the record and the copy on purpose)"
        read -r _ab atip _ < "$sv/applied"; rp=$(reg_get "$RUN" repo)
        [ -n "$rp" ] || die "$RUN is gone and was made from a repository URL, so whether its work is merged cannot be checked: --discard drops it on purpose"
        mrc=0; merged_tip "$rp" "${atip:-}" "${_ab:-}" "$RUN" || mrc=$?
        [ "$mrc" = 0 ] || die "$RUN's work (${atip:0:12}) is not merged into any branch yet: qargi feature merge NAME $_ab, then clean (--discard drops it on purpose)$(rwh=$(rewrite_hint "$rp" "$_ab"); [ -z "$rwh" ] || printf '\n%s' "$rwh")"
      fi
      [ -z "$sv" ] || rm -rf --one-file-system -- "$sv"
      scrub_ok_drop "$RUN"
      reg_edit "$RUN" drop || die "could not drop the record of $RUN from $DA_STATE/local-runs.jsonl"
      echo "dropped the record of $RUN (directory gone)${sv:+ and its saved copy $sv}"
      exit 0
    fi
    [ ! -L "$RUN" ] || die "clean: $RUN is a link, not a directory prepare made"
    [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] && case $(basename "$RUN") in qargi.??????) ;; *) false;; esac \
      || usage_die "clean needs a RUN dir made by prepare"
    # a read-only run (its class in the lead's registry: an advisor, a review) returns a report and no manifest: its OUT holds a report.md (or NAME-report.md, a
    # regular file) and it closes with a plain clean, when its refs are unchanged (the check below) and its clone holds no commit (the check after that)
    [ -n "$DISCARD" ] || [ -f "$RUN/out/manifest.json" ] || [ -n "$(find "$RUN/out" -name '*manifest.json' 2>/dev/null | head -1)" ] \
      || { [ "$(run_class "$RUN")" = read-only ] && out_has_report "$RUN/out"; } \
      || die "$RUN/out holds no manifest: collect the work first, or --discard to drop a run that produced none$([ "$(run_class "$RUN")" != read-only ] || echo " (a read-only run closes with a plain clean once its OUT holds report.md)")$(out_has_report "$RUN/out" || printf '\n%s' "$NOREPORT_CAUSE")"
    # changed refs are evidence: kept, unless the run is dropped on purpose (--discard), which says so and goes on
    vrc=0; vout=$(QARGI_VERIFY_REFS_ONLY=1 "$0" verify "$RUN" 2>&1 </dev/null) || vrc=$?
    if [ "$vrc" = 3 ]; then   # the registry does not vouch for the run directory: nothing was asked of any repository
      [ -n "$DISCARD" ] || die "${vout#qargi: }"
      echo "qargi: warning: the lead's registry does not vouch for $RUN; dropped on purpose:" >&2
      sed 's/^/  /' <<<"$vout" >&2
    elif [ "$vrc" != 0 ]; then
      [ -n "$DISCARD" ] || die "the refs of the repository changed during this run: keep $RUN as evidence and tell the user (qargi local verify $RUN)"
      echo "qargi: warning: the refs of the repository changed during this run; dropped on purpose:" >&2
      sed 's/^/  /' <<<"$vout" >&2
    fi
    acc=''; [ "$vrc" != 0 ] || acc=$(sed -n -e '/per runs\.owned_refs)$/s/^  //p' -e '/per runs\.owned_refs)$/!s/^  /accepted, the lead'"'"'s own move: /p' <<<"$vout")   # what verify accepted, named again when the run is cleaned
    # finished work is never dropped before it is merged: commits in the clone must be applied (review apply) and the applied tip must
    # be on a branch other than agent/*, in the real repository. --discard is the deliberate way to drop them.
    nc=$(git -C "$RUN/clone" rev-list --count HEAD --not --remotes=origin 2>/dev/null || echo 0)
    if [ "${nc:-0}" -gt 0 ] && [ -n "$(reg_get "$RUN" closed)" ]; then
      echo "qargi: note: $RUN was closed as $(reg_get "$RUN" closed_by): its $nc commit(s) are taken as applied by hand" >&2
    elif [ "${nc:-0}" -gt 0 ]; then
      if [ -n "$DISCARD" ]; then echo "qargi: dropped $nc unmerged commit(s) of $RUN on purpose" >&2
      else
        [ -f "$RUN/applied" ] || die "$RUN holds $nc commit(s) that were never applied: qargi review apply $RUN, then qargi feature merge, then clean (--discard drops them on purpose)"
        read -r _ab atip _ < "$RUN/applied"
        rp=$(reg_get "$RUN" repo)   # the lead's registry, never RUN/repo.path
        if [ -n "$rp" ]; then
          mrc=0; merged_tip "$rp" "${atip:-}" "${_ab:-}" "$RUN" || mrc=$?
          [ "$mrc" != 2 ] || die "$RUN/applied does not hold a commit name as its second word, so whether the work is merged cannot be checked: look at it, or --discard drops the run on purpose"
          [ "$mrc" = 0 ] || die "$RUN's work (${atip:0:12}) is not merged into any branch yet: qargi feature merge NAME $_ab, then clean (--discard drops it on purpose)$(rwh=$(rewrite_hint "$rp" "$_ab"); [ -z "$rwh" ] || printf '\n%s' "$rwh")"
        fi
      fi
    fi
    # the run's temporary directory is the one the lead's registry names for this run directory ($DA_STATE/local-runs.jsonl, written by prepare), else RUN/tmp:
    # never the run's own tmpdir file, which a member can write and which could name another run's directory. It is removed only when it is where prepare puts
    # one: RUN/tmp, or qargi-run.XXXXXX directly under /dev/shm (QARGI_RUN_TMP, when prepare was told to use another parent); a recorded path anywhere else is
    # left alone. The recorded text is only a claim until checked: the trailing slashes are stripped (rm -rf on a link with one empties what the link leads
    # to), a link is refused after that, the real path of the directory must be directly under the real path of that parent (no link in between), and what
    # is removed is that real path, on its own file system.
    t=$(reg_get "$RUN" tmpdir)
    [ -n "$t" ] || t=$RUN/tmp
    while [ "${t%/}" != "$t" ] && [ "$t" != / ]; do t=${t%/}; done
    rt=''
    if [ -n "$t" ] && [ ! -L "$t" ] && [ -d "$t" ]; then
      name=$(basename -- "$t"); par=$(dirname -- "$t"); rp=$(realpath -- "$t" 2>/dev/null || true)
      if [ -n "$rp" ] && [ "$(basename -- "$rp")" = "$name" ]; then
        case $name in
          qargi-run.??????)
            for b in /dev/shm "${QARGI_RUN_TMP:-}"; do
              while [ "${b%/}" != "$b" ] && [ "$b" != / ]; do b=${b%/}; done
              [ -n "$b" ] && [ "$par" = "$b" ] && [ "$(dirname -- "$rp")" = "$(realpath -- "$b" 2>/dev/null)" ] && rt=$rp
            done;;
          tmp) [ "$(dirname -- "$rp")" = "$(realpath -- "$RUN")" ] && rt=$rp;;
        esac
      fi
    fi
    if [ -z "$rt" ] && [ -n "$t" ]; then echo "qargi: note: left $t alone: it is not a directory prepare makes under /dev/shm, QARGI_RUN_TMP or the run" >&2; fi
    [ -z "$rt" ] || rm -rf --one-file-system -- "$rt"
    rrun=$(readlink -f -- "$RUN" 2>/dev/null) || rrun=$RUN   # the registry's name of the run, taken while the directory is there
    rm -rf --one-file-system -- "$RUN"
    sv=$(saved_of "$RUN"); [ -z "$sv" ] || rm -rf --one-file-system -- "$sv"   # the copy verify saved: the work is merged, or dropped on purpose
    scrub_ok_drop "$RUN"   # the record of a passed scrub that review check kept for a run never applied
    reg_edit "$rrun" cleaned || echo "qargi: warning: could not mark $RUN cleaned in $DA_STATE/local-runs.jsonl (report and list may show it as directory gone)" >&2
    [ -z "$acc" ] || printf '%s\n' "$acc"
    echo "cleaned $RUN${rt:+ and $rt}";;
  close)
    # the lead took a verified run's patches in by hand (git am): the run is closed, so it is no longer open (compact-check, feature finish, marshal status). The
    # mark is in the lead's registry (closed: a time, closed_by: applied-by-am), never in the run directory, which a member can write. The files are kept: clean removes them.
    CLOSE_RUN='' HOW=''
    while [ $# -gt 0 ]; do
      case $1 in
        --applied-by-am) HOW=applied-by-am; shift;;
        -*) usage_die "close: unknown option $1";;
        *) [ -z "$CLOSE_RUN" ] || usage_die "close takes one RUN dir"; CLOSE_RUN=$1; shift;;
      esac
    done
    [ -n "$CLOSE_RUN" ] && [ -n "$HOW" ] || usage_die "usage: qargi local close RUN_DIR --applied-by-am   (the way the run was taken in: its patches applied by hand with git am)"
    RUN=$CLOSE_RUN
    while [ "${RUN%/}" != "$RUN" ] && [ "$RUN" != / ]; do RUN=${RUN%/}; done
    [ -d "$RUN" ] && [ ! -L "$RUN" ] && [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] && case $(basename "$RUN") in qargi.??????) ;; *) false;; esac \
      || usage_die "close needs a RUN dir made by prepare"
    reg_load; reg_has "$RUN" || die "$RUN is not in the lead's registry ($DA_STATE/local-runs.jsonl): only a run made by qargi local prepare on this machine is closed"
    [ -z "$(reg_get "$RUN" cleaned)" ] || die "$RUN was cleaned already"
    [ -z "$(reg_get "$RUN" closed)" ] || die "$RUN is closed already ($(reg_get "$RUN" closed_by)): qargi local clean $RUN removes its files"
    [ "$(run_class "$RUN")" != read-only ] || die "$RUN is a read-only run: it has no patches to apply. qargi local clean $RUN removes it"
    if [ -f "$RUN/applied" ]; then
      read -r _ab _ < "$RUN/applied"
      die "$RUN was applied with qargi review apply ($(cut -d' ' -f1 "$RUN/applied")): merge that branch (qargi feature merge), then qargi local clean $RUN$(rwh=$(rewrite_hint "$(reg_get "$RUN" repo)" "${_ab:-}"); [ -z "$rwh" ] || printf '\n%s' "$rwh")"
    fi
    [ -n "$(reg_get "$RUN" verified)" ] || [ -f "$RUN/verified" ] || die "$RUN has no passing verify: qargi local verify $RUN first (the refs of the repository must be checked before the run is closed)"
    # the refs are checked again now (a ref may have changed since the first verify): changed refs are evidence, the run stays open
    vrc=0; vout=$(QARGI_VERIFY_REFS_ONLY=1 "$0" verify "$RUN" 2>&1 </dev/null) || vrc=$?
    [ "$vrc" = 0 ] || die "the refs of the repository changed, or could not be checked, since the run's passing verify: keep $RUN as evidence and look at it (qargi local verify $RUN)${vout:+
$vout}"
    reg_mark "$RUN" closed "$(now)"; reg_mark "$RUN" closed_by "$HOW"
    reg_load; [ -n "$(reg_get "$RUN" closed)" ] || die "could not mark $RUN closed in $DA_STATE/local-runs.jsonl"
    audit_log "local:close" "$HOW $RUN"
    echo "closed $RUN: its patches were applied by hand ($HOW). It is no longer an open run (lead compact-check, feature finish); its files are kept: qargi local clean $RUN removes them";;
  list)
    # read-only: the runs under --scratch DIR (the directories prepare made), else the runs of the registry that still exist; then the runs of the
    # registry (under DIR) whose directory is gone and that clean did not remove, each marked "directory gone" with its saved copy
    SCR=''
    while [ $# -gt 0 ]; do
      case $1 in --scratch) need_val "$1" $#; SCR=${2:-}; shift 2;; *) usage_die "list: unknown option $1";; esac
    done
    runs=(); reg_load; scr=''
    if [ -n "$SCR" ]; then
      scr=$(scratch_of "$SCR") || die "list: no such directory $SCR"
      for d in "$scr"/qargi.??????; do [ -d "$d" ] && [ ! -L "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && reg_has "$d" && runs+=("$d"); done
    else
      for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do [ -d "$d" ] && [ -f "$d/refs.before" ] && [ -f "$d/ability" ] && runs+=("$d"); done
    fi
    mapfile -t gone < <(gone_runs "$scr")
    printf '%-10s %-18s %-10s %-6s %-8s %s\n' ROLE SLUG AGE APPLIED MERGED RUN
    nowe=$(date +%s)
    plain() { LC_ALL=C tr -d '\000-\037\177'; }   # the files of a run are a member's to write: no control or escape byte reaches the terminal
    for d in ${runs[@]+"${runs[@]}"}; do
      sl=$(reg_get "$d" slug)
      st=$(cat "$d/started" 2>/dev/null || true)
      if [[ $st =~ ^[0-9]{1,12}$ ]]; then   # the file is a member's: only digits ever reach the arithmetic
        age=$((nowe - st))
        if [ "$age" -ge 86400 ]; then ag="$((age / 86400))d"; elif [ "$age" -ge 3600 ]; then ag="$((age / 3600))h"; else ag="$((age / 60))m"; fi
      else ag='?'; fi
      ap=no; mg=no
      if [ -f "$d/applied" ]; then
        ap=yes; read -r _ab atip _ < "$d/applied"; rp=$(reg_get "$d" repo)
        if [ -z "$rp" ]; then mg='?'
        else mrc=0; merged_tip "$rp" "${atip:-}" "${_ab:-}" "$d" || mrc=$?; case $mrc in 0) mg=yes;; 2) mg='?';; esac; fi
      elif [ -n "$(reg_get "$d" closed)" ]; then ap=closed; mg=-   # local close --applied-by-am: applied by hand, no tip to follow
      fi
      printf '%-10s %-18s %-10s %-6s %-8s %s\n' "$( (cat "$d/ability" 2>/dev/null || echo '?') | plain)" "$(printf '%s' "${sl:--}" | plain)" "$ag" "$ap" "$mg" "$(printf '%s' "$d" | plain)"
    done
    for d in ${gone[@]+"${gone[@]}"}; do
      [ -n "$d" ] || continue
      sl=$(reg_get "$d" slug); ste=$(date -d "$(reg_get "$d" started)" +%s 2>/dev/null) || ste=''
      if [[ $ste =~ ^[0-9]{1,12}$ ]]; then
        age=$((nowe - ste))
        if [ "$age" -ge 86400 ]; then ag="$((age / 86400))d"; elif [ "$age" -ge 3600 ]; then ag="$((age / 3600))h"; else ag="$((age / 60))m"; fi
      else ag='?'; fi
      sv=$(saved_of "$d"); ap=no; mg=no
      if [ -n "$sv" ] && [ -f "$sv/applied" ]; then
        ap=yes; read -r _ab atip _ < "$sv/applied"; rp=$(reg_get "$d" repo)
        if [ -z "$rp" ]; then mg='?'
        else mrc=0; merged_tip "$rp" "${atip:-}" "${_ab:-}" "$d" || mrc=$?; case $mrc in 0) mg=yes;; 2) mg='?';; esac; fi
      elif [ -n "$(reg_get "$d" closed)" ]; then ap=closed; mg=-
      fi
      printf '%-10s %-18s %-10s %-6s %-8s %s\n' "$(printf '%s' "$(reg_get "$d" ability)" | plain)" "$(printf '%s' "${sl:--}" | plain)" "$ag" "$ap" "$mg" \
        "$(printf '%s  directory gone%s' "$d" "${sv:+, saved copy $sv (qargi review apply --from-saved ${d##*/})}" | plain)"
    done;;
  run)
    # the project of the run is the stored one that has its repository; its local runtime says how to start the member (lib/local_run.py)
    RUN=${1:-}; shift || true
    [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] || usage_die "run needs a RUN dir made by prepare"
    for a in "$@"; do case $a in --project|--runtime|--class) die "run: $a is not an option (the project and its runtime come from the run)";; esac; done
    reg_load; run_record "$RUN" || exit 2   # the project is found by the repository the lead's registry records, not by files in the run directory
    RPJ=$(run_project "$RUN")   # the project prepare recorded in the lead's registry, not the first stored project whose repository it is
    [ -f "$DA_CONF/projects/$RPJ.json" ] && valid_project "$RPJ" || RPJ=''   # a project stored since removed is no project
    [ -n "$RPJ" ] || { echo "qargi: no stored project has the repository of this run, so no runtime is known: store it (qargi project attach) and give it a local provider (qargi project set PROJECT models.provider.local NAME)" >&2; exit 2; }
    RPROV=$(project_provider "$RPJ" local) || exit $?
    exec python3 -I "$(dirname "$0")/local_run.py" "$RUN" --project "$RPJ" --runtime "$RPROV" --class "$(run_class "$RUN")" "$@";;
  *) usage_die "usage: local.sh prepare|verify|close|clean|list|run ...";;
esac
