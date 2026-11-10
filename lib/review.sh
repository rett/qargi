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
#   review.sh save RUN [--force]                              the final message of a read-only run (standard input) stored as RUN/out/report.md, with a minimal
#       manifest.json when OUT has none; the lead's, for a member whose file tool was refused. No overwrite of a report without --force.
#
# The branch is made in a temporary worktree of the project's repository (repo.path), so the user's checkout is never touched;
# no ref other than the new branch changes. A patch that does not apply removes the worktree and the branch again.
. "$(dirname "$0")/lib.sh"

# scrub_declared RUN -> 0 when the lead's registry holds, for the run, a take-in scrub (review.scrub) or a trailer policy (review.trailer_policy reject).
# The answers are the copy `local prepare` took into the registry, never the stored project's file; a run with no copy has none.
# SCRUB_CMD gets the command (a JSON string or list of words), SCRUB_TRAILERS the policy, SCRUB_EXTRA the trailer keys review.reject_trailers adds to the
# built-in two (a JSON list of strings; they count only under the policy reject).
scrub_declared() {
  local a
  SCRUB_CMD='' SCRUB_TRAILERS=none SCRUB_EXTRA='[]'
  reg_load; reg_has "$1" || return 1
  a=$(reg_json "$1" 'if (.answers | type) == "object" then .answers else empty end'); [ -n "$a" ] || return 1
  SCRUB_CMD=$(jq -c '(.review? // {}) | objects | .scrub // empty' <<<"$a" 2>/dev/null) || SCRUB_CMD=''
  SCRUB_TRAILERS=$(jq -r '(.review? // {}) | objects | .trailer_policy // "none"' <<<"$a" 2>/dev/null) || SCRUB_TRAILERS=none
  SCRUB_EXTRA=$(jq -c '(.review? // {}) | objects | .reject_trailers // [] | if type == "array" then . else ["?"] end' <<<"$a" 2>/dev/null) || SCRUB_EXTRA='["?"]'
  [ -n "$SCRUB_CMD" ] || [ "$SCRUB_TRAILERS" = reject ]
}
# scrub_trailer_hit MESSAGE -> prints "LINE:TEXT<TAB>WHY" for the first line of the commit message that the trailer policy rejects (the built-in two: a co-author
# and a generated-with trailer; then each key of review.reject_trailers, a trailer key of letters, digits and hyphens where * stands for any run of them), the
# line counted from the first line of the message; prints nothing when none is. A key that is no such thing is not guessed at: it is a hit that says so.
scrub_trailer_hit() {
  local hit k ere
  hit=$(grep -inE -m1 '^[^[:alnum:]]*(co-authored-by[[:space:]]*:|generated[ -](with|by)([^[:alnum:]]|$))' <<<"$1" || true)
  if [ -n "$hit" ]; then printf '%s\treview.trailer_policy is reject\n' "$hit"; return 0; fi
  while IFS= read -r k; do
    [ -n "$k" ] || continue
    if ! [[ $k =~ ^[A-Za-z0-9*-]+$ ]]; then printf '1:%s\treview.reject_trailers has an entry that is no trailer key\n' "$k"; return 0; fi
    ere=${k//\*/[A-Za-z0-9-]*}
    hit=$(grep -inE -m1 "^[^[:alnum:]]*($ere)[[:space:]]*:" <<<"$1" || true)
    if [ -n "$hit" ]; then printf '%s\treview.reject_trailers names %s\n' "$hit" "$k"; return 0; fi
  done < <(jq -r '.[]? | tostring' <<<"$SCRUB_EXTRA" 2>/dev/null)
  return 0
}
# scrub_first_lines TEXT -> the first three non-empty lines of TEXT on one line, joined with ' | ', control characters dropped, at most 300 characters
scrub_first_lines() {
  printf '%s\n' "$1" | LC_ALL=C tr -d '\000-\010\013-\037\177' | sed -e '/^[[:space:]]*$/d' | head -n 3 | awk 'NR > 1 {printf " | "} {printf "%s", $0}' | cut -c1-300
}
# scrub_run RUN OUT [FILES] -> prints the one verdict line and returns 0 (ok) or 1 (FAIL). The series (OUT/patches, applied with git am on the commit the run's base
# branch had at prepare, as review apply applies it) is made in a throw-away shared clone of the run's repository (the registry's, never the run directory's):
# no worktree entry, branch or tag is made in the repository itself, so no temporary ref is left behind. The policy is checked on the applied commits first;
# then the command runs in the clone, checked out at the tip, with QARGI_SCRUB_BASE and QARGI_SCRUB_TIP set to the range. FILES is where the run's refs.before and
# bare.git are (default RUN; the saved copy for a run applied with --from-saved, whose directory is gone).
scrub_run() {
  local tmp rc=0
  tmp=$(mktemp -d "$DA_STATE/scrub-wt.XXXXXX") || { echo "scrub: FAIL could not make a temporary directory"; return 1; }
  scrub_in "$1" "$2" "$tmp" "${3:-$1}" || rc=$?
  rm -rf -- "$tmp"
  return "$rc"
}
scrub_in() {
  local run=$1 out=$2 tmp=$3 files=$4 repo base sha tip c hit why text rc=0 p
  local -a patches=() cmd
  repo=$(reg_get "$run" repo); base=$(reg_get "$run" base)
  [ -n "$repo" ] || { echo "scrub: FAIL the registry names no local repository for the run"; return 1; }
  sha=$(awk -v b="refs/heads/$base" '$1=="local" && $2==b {print $3}' "$files/refs.before" 2>/dev/null || true)
  [ -n "$sha" ] || sha=$(git -C "$files/bare.git" rev-parse -q --verify "refs/heads/$base" 2>/dev/null || true)
  if [ -z "$sha" ] || ! git -C "$repo" cat-file -e "$sha^{commit}" 2>/dev/null; then echo "scrub: FAIL cannot tell the run's base commit (branch '$base')"; return 1; fi
  while IFS= read -r -d '' p; do patches+=("$p"); done < <(find "$out/patches" -maxdepth 1 -name '*.patch' -type f -print0 2>/dev/null | sort -z)
  if ! { git clone -q --shared --no-checkout -- "$repo" "$tmp/t" && git -C "$tmp/t" -c advice.detachedHead=false checkout -q --detach "$sha"; } >/dev/null 2>&1; then
    echo "scrub: FAIL could not make a temporary checkout of ${sha:0:12}"; return 1
  fi
  for p in "${patches[@]}"; do
    # the lead's hooks and signing do not run on a throw-away commit; the committer is a fixed one (the author is the patch's)
    if ! git -C "$tmp/t" -c core.hooksPath=/dev/null -c commit.gpgsign=false -c user.name=qargi-scrub -c user.email=scrub@localhost am -q --3way "$p" >/dev/null 2>&1; then
      echo "scrub: FAIL $(basename "$p") does not apply on ${sha:0:12}"; return 1
    fi
  done
  tip=$(git -C "$tmp/t" rev-parse HEAD)
  if [ "$SCRUB_TRAILERS" = reject ]; then
    while IFS= read -r c; do
      hit=$(scrub_trailer_hit "$(git -C "$tmp/t" log -1 --format=%B "$c")")
      if [ -n "$hit" ]; then
        why=${hit#*$'\t'}; hit=${hit%%$'\t'*}
        echo "scrub: FAIL $why: ${c:0:12} line ${hit%%:*} of its message carries \"$(scrub_first_lines "${hit#*:}")\""; return 1
      fi
    done < <(git -C "$tmp/t" rev-list --reverse "$sha..$tip")
  fi
  if [ -n "$SCRUB_CMD" ]; then
    if [ "$(jq -r 'type' <<<"$SCRUB_CMD")" = array ]; then mapfile -d '' -t cmd < <(jq -j '.[], "\u0000"' <<<"$SCRUB_CMD")
    else cmd=(bash -c "$(jq -r '.' <<<"$SCRUB_CMD")"); fi
    text=$(run_clean "$tmp/t" env QARGI_SCRUB_BASE="$sha" QARGI_SCRUB_TIP="$tip" "${cmd[@]}" </dev/null 2>&1) || rc=$?
    if [ "$rc" != 0 ]; then text=$(scrub_first_lines "$text"); echo "scrub: FAIL ${text:-exit $rc, no output}"; return 1; fi
  fi
  echo "scrub: ok"
}
# The verdict of a passing scrub is recorded for the series it passed. scrub_series_hash OUT -> the sha256 of the names and contents of OUT/patches/*.patch in order,
# then of the declared scrub (SCRUB_CMD, SCRUB_TRAILERS and SCRUB_EXTRA, so a changed command or trailer list is never taken as passed). The record is the lead's, in its state directory (the run
# directory is a member's to write, and the saved copy of a run has none): scrub_ok/RUN-ID holds that hash. `review check` writes it when the scrub passes and removes
# it when the scrub or the check fails; `review apply` skips the scrub when the record names the series it is about to apply, and runs it otherwise.
scrub_series_hash() {
  { ( cd "$1/patches" 2>/dev/null && find . -maxdepth 1 -name '*.patch' -type f -print0 | LC_ALL=C sort -z | xargs -0 -r sha256sum ); printf '%s\n%s\n%s\n' "$SCRUB_CMD" "$SCRUB_TRAILERS" "$SCRUB_EXTRA"; } \
    | sha256sum | cut -d' ' -f1
}
scrub_ok_file() { printf '%s/scrub_ok/%s' "$DA_STATE" "${1##*/}"; }
scrub_ok_set() { # RUN OUT
  local f rec; f=$(scrub_ok_file "$1"); mkdir -p "$(dirname "$f")" 2>/dev/null || return 0
  rec=$(mktemp "$f.XXXXXX") || return 0
  scrub_series_hash "$2" > "$rec" && mv -T -- "$rec" "$f" || rm -f "$rec"
}
scrub_ok_clear() { rm -f -- "$(scrub_ok_file "$1")"; }
scrub_ok_has() { # RUN OUT -> 0 when the record names this series
  local f; f=$(scrub_ok_file "$1"); [ -f "$f" ] && [ ! -L "$f" ] && [ "$(head -n 1 -- "$f" 2>/dev/null)" = "$(scrub_series_hash "$2")" ]
}

verb=${1:-}; shift || true
if [ "$verb" = check ]; then
  # qargi review check OUT [--allow-empty]: review_check.py reads one output directory; the lead's registry knows the run it belongs to, so the
  # lead's lease on the feature that run is based on is renewed first (no project is needed, none is loaded)
  . "$(dirname "$0")/marshal.sh"
  # the argument is a run's OUT (the run is its parent directory) or the run directory itself, which review_check.py also takes (RUN/out)
  SRUN='' SOUT=''
  for a in "$@"; do
    case $a in -*) ;; *)
      if o=$(readlink -f -- "$a" 2>/dev/null); then
        if [ -d "$o/out" ] && [ ! -d "$o/patches" ] && [ ! -e "$o/manifest.json" ]; then SRUN=$o SOUT=$o/out; else SRUN=$(dirname "$o") SOUT=$o; fi
        marshal_touch_run "$SRUN"
      fi
      break;;
    esac
  done
  rc=0; python3 -I "$(dirname "$0")/review_check.py" "$@" || rc=$?
  # The project's declared take-in scrub (answers review.scrub and review.trailer_policy; neither set: nothing more is checked or printed) runs on a series
  # that has patches, after the check above; a failing scrub fails the check
  if [ "$rc" != 2 ] && [ -n "$SRUN" ] && compgen -G "$SOUT/patches/*.patch" >/dev/null && scrub_declared "$SRUN"; then
    # a member's check (the mark `qargi local run` sets in a member's environment) never runs the lead's command or makes the checkout: the lead's check runs it
    if [ -n "${QARGI_MEMBER_RUN:-}" ]; then echo "scrub: not run (a member's check; the lead's check runs it)"
    elif [ "$rc" != 0 ]; then echo "scrub: not run (the series check failed)"
    elif scrub_run "$SRUN" "$SOUT"; then scrub_ok_set "$SRUN" "$SOUT"   # review apply skips the scrub it has just seen pass for this series
    else rc=1; fi
    [ "$rc" = 0 ] || scrub_ok_clear "$SRUN"
  fi
  exit "$rc"
fi
if [ "$verb" = save ]; then
  # qargi review save RUN [--force]: a read-only run whose member returned its report as its final message (its file tool refused, or it has none): the lead
  # stores the message from standard input as RUN/out/report.md, with a minimal manifest.json when OUT has none. No shell text of the member is involved.
  SRUN='' FORCE=''
  for a in "$@"; do
    case $a in
      --force) FORCE=1;;
      -*) usage_die "unknown option $a (usage: qargi review save RUN [--force] < MESSAGE)";;
      *) [ -z "$SRUN" ] || usage_die "unexpected argument $a (usage: qargi review save RUN [--force] < MESSAGE)"; SRUN=$a;;
    esac
  done
  [ -n "${SRUN%/}" ] || usage_die "usage: qargi review save RUN [--force] < MESSAGE (the member's final message on standard input)"
  [ -z "${QARGI_MEMBER_RUN:-}" ] || die "qargi review save is the lead's: a member returns its report in its final message and the lead stores it"
  SRUN=${SRUN%/}
  [ -d "$SRUN" ] && [ ! -L "$SRUN" ] || die "$SRUN is not a run directory (a link, or no such directory): nothing was written"
  RUN=$(readlink -f -- "$SRUN") || die "no such run directory: $SRUN"
  SOUT=$RUN/out
  { [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] && case ${RUN##*/} in qargi.??????) true;; *) false;; esac; } \
    || die "$RUN is not a run prepared by qargi local prepare: nothing was written"
  reg_load; reg_has "$RUN" || die "the lead's registry names no run $RUN (a directory a member made is not one): nothing was written"
  [ "$(run_class "$RUN")" = read-only ] \
    || die "$RUN is not a read-only run ($(cat "$RUN/ability" 2>/dev/null || echo build)): its product is patches, and the lead takes them in with qargi local verify; nothing was written"
  [ -d "$SOUT" ] && [ ! -L "$SOUT" ] || die "$SOUT is a link or not a directory: a member put it there (look at the run); nothing was written"
  [ ! -t 0 ] || usage_die "give the member's final message on standard input: qargi review save $SRUN < message.md"
  MSG=$(mktemp "$SOUT/.report.XXXXXX") || die "could not write in $SOUT: nothing was written"
  MAN=''
  trap 'rm -f -- "${MSG:-}" "${MAN:-}"' EXIT
  cat > "$MSG" || die "could not read the message from standard input: nothing was written"
  grep -q '[^[:space:]]' "$MSG" || die "the message on standard input is empty: nothing was written"
  [ -z "$(tail -c 1 "$MSG")" ] || echo >> "$MSG"
  if [ -z "$FORCE" ] && { [ -e "$SOUT/report.md" ] || [ -L "$SOUT/report.md" ]; }; then
    die "$SOUT/report.md exists already: nothing was written (--force replaces it)"
  fi
  chmod 644 "$MSG"; mv -T -- "$MSG" "$SOUT/report.md" || die "could not write $SOUT/report.md"
  echo "wrote $SOUT/report.md ($(wc -c < "$SOUT/report.md" | tr -d ' ') bytes)"
  if [ -e "$SOUT/manifest.json" ] || [ -L "$SOUT/manifest.json" ]; then
    echo "kept $SOUT/manifest.json (the member wrote one)"
  else
    sbase=$(reg_get "$RUN" base)
    sha=$(awk -v b="refs/heads/$sbase" '$1=="local" && $2==b {print $3}' "$RUN/refs.before" 2>/dev/null | head -n 1)
    MAN=$(mktemp "$SOUT/.manifest.XXXXXX") || die "could not write the manifest in $SOUT"
    jq -n --arg b "$sbase" --arg s "$sha" --arg slug "$(reg_get "$RUN" slug)" --arg role "$(reg_get "$RUN" ability)" \
      '{status:"DONE", blocked_reason:"", task:("read-only run " + $role + " " + $slug + ": the report is the final message, stored by the lead (qargi review save)"),
        base:{branch:$b, sha:$s}, branch:"", scope:[], done:{command:"", exit_code:null, output_tail:""}, gates:[], commits:[], touched_paths:[],
        artifacts:[{path:"report.md", kind:"report"}]}' > "$MAN" || die "could not make the manifest"
    chmod 644 "$MAN"; mv -T -- "$MAN" "$SOUT/manifest.json" || die "could not write $SOUT/manifest.json"
    echo "wrote $SOUT/manifest.json (status DONE, commits: [])"
  fi
  echo "next: qargi review check $SOUT"
  exit 0
fi
# pick_author: AUTH_MODE (reset | keep), AUTH ("Name <email>") and AUTH_SRC (where it comes from, or why the member's author stays) from the run's answers.
# review.keep_author true keeps the member's author; else git.author, else the repository's user.name/user.email; with none of them the member's stays.
# Both answers are checked as `project validate` checks them: a hand-edited file that breaks them is refused before anything is applied.
AUTH_RE='^([^<>]*[^<>[:space:]]) <([^<>[:space:]@]+@[^<>[:space:]@]+)>$'
pick_author() {
  local keep a n e aj
  # the answers are the run's own, taken into the lead's registry at prepare (run_record: RUN_ANS); the stored file is not read
  aj=${RUN_ANS:-}; [ -n "$aj" ] || aj='{}'
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

# The apply marker. A run is applied once, and what says so is a record in the lead's own state, $DA_STATE/apply/RUNID.json, not the file `applied` in the run directory
# (a member's to write, and kept only because local.sh reads it). The record is made (exclusively) before the branch is, and says how far the apply got:
# status started (the branch is being made), built (the branch is at `tip`; the remaining steps are not all done), done. A run that finds it started or built
# does not die at "the branch exists already": a started apply left a branch that is only the base plus some of the patches, which is removed and made again;
# a built one is finished from the record (apply_record), the patches are not read again. steps lists the ones of apply_record that are done.
# The path rule is shared with `qargi local clean RUN` (apply_state_drop in local.sh), which removes the record of a run it cleans: apply/RUN-ID.json. The temporary
# directories of an apply carry the run's id in their names (apply-in.RUN-ID.XXXXXX holds the copy of the patches, apply-wt.RUN-ID.XXXXXX the worktree), so the ones
# an apply that was killed leaves are attributed to their run by clean, and to none by `local clean --orphans`.
apply_rec_file() { printf '%s/apply/%s.json' "$DA_STATE" "${1##*/}"; }   # RUN
apply_mark() { json_update "$amark" '.steps = ((.steps + [$s]) | unique)' --arg s "$1"; }   # STEP
apply_marked() { jq -e --arg s "$1" '.steps | index($s) != null' "$amark" >/dev/null 2>&1; }
# apply_record -> the steps after the branch is built: the journal line, the audit line, the scrub record, the `applied` file of the run (and of its saved copy), the
# snapshot the run is compared against; the marker is `done` last. Reads RUN SRC SAVED BRANCH sha tip AUTH_LINE npatch amark (set by the apply, or from the marker).
apply_record() {
  local rec
  apply_marked journal || { journal_line "$REPO" "refs/heads/$BRANCH" "" "$tip" review:apply '' "$AUTH_LINE"; apply_mark journal; }
  apply_marked audit || { audit_log "review:apply" "$RUN $BRANCH ${tip:0:12}: $AUTH_LINE"; apply_mark audit; }
  echo "applied $npatch patch(es) on $BRANCH, from ${sha:0:12} to ${tip:0:12}:"
  g log --reverse --format='  %h %s' "$sha..$tip"
  echo "$AUTH_LINE"
  scrub_ok_clear "$RUN"
  # The run directory is a member's to write: what is recorded there is written in the lead's state directory and renamed into place (mv -T replaces a link
  # that stands in the name, it never writes through it).
  if ! apply_marked run_file; then
    rec=$(mktemp "$DA_STATE/apply-rec.XXXXXX") || die "could not record the application in $SRC: $BRANCH was made at ${tip:0:12}; write 'agent/... TIP NOW' to $SRC/applied by hand"
    printf '%s %s %s\n' "$BRANCH" "$tip" "$(now)" > "$rec" && mv -T -- "$rec" "$SRC/applied" || { rm -f "$rec"; die "could not write $SRC/applied ($BRANCH was made at ${tip:0:12})"; }
    apply_mark run_file
  fi
  # the branch is a change `local verify` would report: record it in the snapshot the run is compared against
  if ! apply_marked snapshot; then
    if grep -q '^local ' "$SRC/refs.before"; then
      rec=$(mktemp "$DA_STATE/apply-rec.XXXXXX") || die "could not record the branch in the snapshot of $SRC"
      { { grep '^local ' "$SRC/refs.before" | grep -v "^local refs/heads/$BRANCH " || true; echo "local refs/heads/$BRANCH $tip"; } | sort; grep -v '^local ' "$SRC/refs.before" || true; } > "$rec" \
        && mv -T -- "$rec" "$SRC/refs.before" || { rm -f "$rec"; die "could not update the snapshot $SRC/refs.before"; }
    fi
    apply_mark snapshot
  fi
  # a run applied from its directory: the saved copy records it too, so it is never applied twice
  if [ -z "$SAVED" ] && [ -d "$DA_STATE/runs/${RUN##*/}" ] && [ ! -L "$DA_STATE/runs/${RUN##*/}" ]; then cp -- "$SRC/applied" "$DA_STATE/runs/${RUN##*/}/applied" 2>/dev/null || true; fi
  json_update "$amark" '.status = "done"'
  echo "next:"
  echo "  qargi feature merge NAME $BRANCH    (NAME: the feature this task belongs to)"
  echo "  qargi local clean $RUN${SAVED:+   (its directory is gone: once the work is merged, clean drops its record and the saved copy)}"
}
# apply_resume -> a marker of this run exists (amark): done, refuse; built, finish it; started, remove what it left and go on (the caller then applies the series again)
apply_resume() {
  local st mb mbase cur wt pid ptoken
  st=$(jq -r '.status' "$amark" 2>/dev/null) || st=''
  mb=$(jq -r '.branch' "$amark" 2>/dev/null) || mb=''
  # the process that made the record (its pid and start time) is still running: that apply is under way, not cut off (the lock above says the same; the record
  # is the second witness, for a lock directory that was removed). Only a record whose process is gone is resumed.
  if [ "$st" = started ] || [ "$st" = built ]; then
    pid=$(jq -r '.pid // empty' "$amark" 2>/dev/null) || pid=''; ptoken=$(jq -r '.ptoken // empty' "$amark" 2>/dev/null) || ptoken=''
    [ -n "$pid" ] || die "$amark has no process id, so I cannot tell whether the apply that made it is still running: remove it if you are sure it is not. Nothing was changed"
    ! proc_alive "$pid" "$ptoken" || die "another apply of $RUN is under way (process $pid, $amark): nothing was changed"
  fi
  case $st in
    done) die "this run was applied already ($mb at $(jq -r '.tip' "$amark" | cut -c1-12)): qargi feature merge, then qargi local clean $RUN";;
    built)
      BRANCH=$mb; tip=$(jq -r '.tip' "$amark"); sha=$(jq -r '.base' "$amark"); AUTH_LINE=$(jq -r '.auth_line' "$amark"); npatch=$(jq -r '.npatch' "$amark")
      cur=$(sha_of "$BRANCH")
      [ "$cur" = "$tip" ] || die "an earlier apply of $RUN built $BRANCH at ${tip:0:12} and was cut off before it finished, but $BRANCH is $([ -n "$cur" ] && echo "at ${cur:0:12}" || echo gone) now: look at it; when it is right, remove $amark (and write $SRC/applied) by hand. Nothing was changed"
      echo "an earlier apply of $RUN was cut off after $BRANCH was built at ${tip:0:12}: finishing it (the patches are not applied again)"
      apply_record; exit 0;;
    started)
      mbase=$(jq -r '.base' "$amark")
      cur=$(sha_of "$mb")
      if [ -n "$cur" ]; then
        g merge-base --is-ancestor "$mbase" "$cur" 2>/dev/null \
          || die "an earlier apply of $RUN was cut off while making $mb, but $mb is not the base ${mbase:0:12} plus patches (it is at ${cur:0:12}): look at it; delete it and remove $amark when it is not wanted. Nothing was changed"
        # the temporary worktree of the cut-off apply (the lead's own, under the state directory) still holds the branch: it goes first
        wt=$(held "$mb")
        case $wt in "$DA_STATE"/apply-wt.*) g worktree remove --force "$wt" >/dev/null 2>&1 || true; rm -rf -- "$wt";; esac
        g worktree prune 2>/dev/null || true
        g branch -D "$mb" >/dev/null 2>&1 || die "could not remove $mb, which an earlier apply of $RUN left half made: git branch -D $mb, then run again"
        echo "an earlier apply of $RUN was cut off while making $mb (${cur:0:12}): removed it, applying the series again"
      fi
      rm -f "$amark" "$amark.lock"
      ;;
    *) die "$amark is not a record of an apply (status '$st'): remove it if you are sure the run was not applied. Nothing was changed";;
  esac
}

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
    [ "$(run_class "$RUN")" != read-only ] \
      || die "$RUN is a read-only run ($(cat "$SRC/ability" 2>/dev/null || echo review)): its product is a report, never patches. Read $SRC/out/report.md; nothing was applied"
    appid=${RUN##*/}; amark=$(apply_rec_file "$RUN")
    # one apply of a run at a time: a second one finds the lock of the first (a pid lock, like the finishing verbs') and stops before it touches the record,
    # the branch or the worktree; the lock of an apply that was killed is taken over
    pid_lock "$amark.run" "apply of $RUN"
    if [ -e "$amark" ] || [ -L "$amark" ]; then apply_resume; fi   # a record of an earlier apply of this run: refuse, finish it or clear what it left
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
    # The patches are the files of out/patches, copied once into a directory of the lead's own (the run directory is a member's to write, and a member's process
    # may still be alive): the hash of the series, the scrub and git am all read that copy, so what was scrubbed is what is applied. A link that took the place of a
    # file in the meantime is copied as a link and refused. Read as a list, so a name with a space or a newline in it stays one name.
    AP=$(mktemp -d "$DA_STATE/apply-in.$appid.XXXXXX") || die "could not make a temporary directory in $DA_STATE for the patches"
    trap 'on_exit; [ -z "${AP:-}" ] || rm -rf -- "$AP"' EXIT
    mkdir "$AP/patches" || die "could not make a directory for the patches in $AP"
    n=0
    while IFS= read -r -d '' p; do cp -P -- "$p" "$AP/patches/" 2>/dev/null || die "could not copy $p: nothing was applied"; n=$((n + 1)); done \
      < <(find "$SRC/out/patches" -maxdepth 1 -name '*.patch' -type f -print0 2>/dev/null | sort -z)
    patches=()
    while IFS= read -r -d '' p; do patches+=("$p"); done < <(find "$AP/patches" -maxdepth 1 -name '*.patch' -type f -print0 | sort -z)
    [ ${#patches[@]} -gt 0 ] || die "$SRC/out/patches holds no patches: nothing to apply"
    [ ${#patches[@]} = "$n" ] || die "a patch of $SRC/out/patches changed while it was copied (not a regular file): nothing was applied"
    # The declared take-in scrub (review.scrub, review.trailer_policy) is the lead's: it runs here, before anything is made, unless a passing `review check` recorded
    # the same series (the record is over the patches and the declared scrub; a change to either runs it again). A member's apply never runs it, as its check does not.
    if scrub_declared "$RUN"; then
      if [ -n "${QARGI_MEMBER_RUN:-}" ]; then echo "scrub: not run (a member's apply; the lead's apply runs it)"
      elif scrub_ok_has "$RUN" "$AP"; then echo "scrub: skipped (review check passed it for this series)"
      else
        text=$(scrub_run "$RUN" "$AP" "$SRC") || { echo "$text"; die "the declared scrub refuses the series: nothing was applied"; }
        echo "$text"
      fi
    fi
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
    # the apply record is made before the branch is, in the lead's state (made exclusively: a second apply of the run finds it)
    mkdir -p "$(dirname "$amark")"
    ( set -C; umask 077; jq -nc --arg run "$RUN" --arg src "$SRC" --arg b "$BRANCH" --arg base "$sha" --arg at "$(now)" \
        --arg pid "$$" --arg ptoken "$(proc_token $$)" \
        '{schema:1, run:$run, src:$src, branch:$b, base:$base, status:"started", steps:[], at:$at, pid:($pid|tonumber), ptoken:$ptoken}' > "$amark" ) 2>/dev/null \
      || die "could not make the apply record $amark (is another apply of $RUN under way?): nothing was applied"
    WT=$(mktemp -d "$DA_STATE/apply-wt.$appid.XXXXXX")
    g worktree add -q -b "$BRANCH" "$WT" "$sha" 2>/dev/null || { rm -rf "$WT"; WT=''; rm -f "$amark" "$amark.lock"; die "could not make a temporary worktree for $BRANCH"; }
    fail=''
    apply_series "$WT" "${patches[@]}"
    tip=$(git -C "$WT" rev-parse HEAD)
    cleanup
    if [ -n "$fail" ]; then
      g branch -D "$BRANCH" >/dev/null 2>&1 || true
      rm -f "$amark" "$amark.lock"
      die "$failmsg; the worktree and $BRANCH were removed, nothing else changed"
    fi
    if [ "$AUTH_MODE" = reset ]; then AUTH_LINE="author reset to $AUTH ($AUTH_SRC); member author recorded in the ref journal: $MEMBERS"
    else AUTH_LINE="author kept as the member's ($AUTH_SRC): $MEMBERS"; fi
    json_update "$amark" '.status = "built" | .tip = $t | .auth_line = $a | .npatch = ($n | tonumber)' --arg t "$tip" --arg a "$AUTH_LINE" --arg n "${#patches[@]}"
    npatch=${#patches[@]}
    apply_record;;
  *) usage_die "usage: qargi review check OUT [--allow-empty] | qargi review save RUN [--force] < MESSAGE | qargi review apply RUN_DIR|--from-saved ID [--branch BRANCH] [--project P]";;
esac
