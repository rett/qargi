#!/usr/bin/env bash
# Local dispatch without a way to push: the agent works in a clone of a bare copy that
# has no remote, runs git through a credential-less wrapper, and the coordinator
# compares every ref of the real repository (and of its remote) before and after.
#
#   local.sh prepare (--repo DIR | --repo-url URL [--credential-file FILE]) --base BRANCH --slug SLUG --scratch DIR [--role R]
#   local.sh verify RUN_DIR
#   local.sh clean RUN_DIR [--discard]   remove a collected, verified run and its temporary directory
#
# This stops every ordinary push (`git push`, `git push origin`, a pushurl, a remote added
# from a config). It is not a sandbox against an agent that deliberately goes around it
# (it runs as the same user): `verify` is what turns such an attempt into a loud failure.
# The run directory records the task's ability (RUN/ability, default build); under review the guard
# (qargi __guard) refuses every change to the clone, so a review writes only to OUT.
# A run based on feature/X of a stored project first asks the marshal (marshal_check): another live lead holds X -> refused, no run
# is made; warnings go to stderr. The lead of X is recorded in the run line as "lead" (null when nobody leads it).
# prepare also appends one JSON line per run to $QARGI_STATE/local-runs.jsonl (run directory, slug, ability, base,
# start time; never a repository path or a token), so `qargi report` can list the local runs.
# After the TASK-BLOCK PATHS lines it prints TASK-BLOCK MEMORY (tiercontext.py packet: the tier summary, the always rows of the
# indexes and the no-write rule; the repo tier is the clone's committed copy) when the repository belongs to a stored project.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$0")/marshal.sh"

snapshot_url() { # url credential-file(optional) -> sorted refs of the remote
  ( [ -z "${2:-}" ] || git_auth_env "$2"
    u=$1; [ -z "${2:-}" ] || u=${1/https:\/\//https://x-access-token@}
    out=$(timeout 60 git ls-remote --heads --tags "$u" 2>/dev/null </dev/null) && printf '%s\n' "$out" | sed 's/^/remote /' | sort || echo "remote unavailable" )
}

snapshot() { # repo -> sorted refs of the repository and of its remote
  git -C "$1" for-each-ref --format='local %(refname) %(objectname)' | sort
  if git -C "$1" remote get-url origin >/dev/null 2>&1; then
    if out=$(timeout 60 git -C "$1" ls-remote --heads --tags origin 2>/dev/null </dev/null); then
      printf '%s\n' "$out" | sed 's/^/remote /' | sort
    else
      echo "remote unavailable"
    fi
  fi
}

# journaled REPO NAME OLD NEW -> 0 when the lead's ref journal ($DA_STATE/ref-journal.jsonl) explains the change of the local branch
# NAME from OLD to NEW (a sha, or 40 zeros for absent) since the run began (JSTART, an epoch): NEW is reachable from OLD by
# following entries of this repository and ref with epoch >= JSTART, each from its old value to its new one. Entries that start
# elsewhere (an earlier creation made in the same second as the run) are not on the path, and an unjournaled hand anywhere
# breaks it, because no entry starts where the hand left the ref. Trusted only as far as the state directory is (the guard keeps
# an agent from writing it; same-user code could).
journaled() {
  local f=$DA_STATE/ref-journal.jsonl rp
  [ -n "$1" ] && [ -f "$f" ] && [ -n "${JSTART:-}" ] || return 1
  rp=$(readlink -f "$1" 2>/dev/null) || rp=$1
  jq -sre --arg r "$rp" --arg n "$2" --arg o "$3" --arg w "$4" --argjson s "$JSTART" '
    [ .[] | select(type == "object" and .repo == $r and .ref == $n and ((.epoch // 0) >= $s)) ] as $e
    | reduce range(0; ($e | length) + 1) as $i ([$o]; . as $seen | . + [ $e[] | select(.old as $x | $seen | index($x)) | .new ] | unique)
    | ($w != $o) and (index($w) != null)' "$f" >/dev/null 2>&1
}

# compare REPO REF AFTER [strict] -> prints each offending change, returns 1 if there is one. Everything but a local branch
# (remote refs, refs/remotes, tags, stash, ...) must be identical. A local branch may only move forward (old tip is an
# ancestor of the new one) or be created, and only develop/master and agent|feature|release|hotfix/*: that is what the
# lead's own merges do. Used with refs.before while the run has no passing verify, with RUN/verified after one.
compare() {
  local repo=$1 ref=$2 aft=$3 strict=${4:-} bad=0 name old new
  local hd='^local refs/heads/' zero=0000000000000000000000000000000000000000 why=" (not in the lead's ref journal)"
  if ! diff -u <(grep -v "$hd" "$ref") <(grep -v "$hd" "$aft"); then bad=1; fi
  if [ -n "$strict" ]; then
    # strict: a local branch may differ only as far as the lead's ref journal explains it; nothing else (no fast-forward rule)
    while read -r name; do
      old=$(awk -v n="$name" '$1=="local" && $2==n {print $3}' "$ref"); new=$(awk -v n="$name" '$1=="local" && $2==n {print $3}' "$aft")
      [ "$old" != "$new" ] || continue
      if journaled "$repo" "$name" "${old:-$zero}" "${new:-$zero}"; then continue; fi
      if [ -z "$new" ]; then echo "branch deleted: $name (was $old)$why"
      elif [ -z "$old" ]; then echo "branch created: $name $new$why"
      else echo "branch moved: $name $old -> $new$why"; fi
      bad=1
    done < <({ grep "$hd" "$ref"; grep "$hd" "$aft"; } | awk '{print $2}' | sort -u)
    return $bad
  fi
  allowed() { case $1 in refs/heads/develop|refs/heads/master|refs/heads/agent/*|refs/heads/feature/*|refs/heads/release/*|refs/heads/hotfix/*) return 0;; esac; return 1; }
  while read -r _ name old; do
    new=$(awk -v n="$name" '$1=="local" && $2==n {print $3}' "$aft")
    if [ -z "$new" ]; then echo "branch deleted: $name (was $old)"; bad=1
    elif [ "$new" != "$old" ]; then
      if ! allowed "$name"; then echo "branch moved, not an allowed branch: $name $old -> $new"; bad=1
      elif ! git -C "$repo" merge-base --is-ancestor "$old" "$new" 2>/dev/null; then echo "branch rewritten (not a fast-forward): $name $old -> $new"; bad=1; fi
    fi
  done < <(grep "$hd" "$ref")
  while read -r _ name new; do
    grep -q "^local $name " "$ref" && continue
    case $name in refs/heads/develop|refs/heads/master) ;; *) allowed "$name" && continue;; esac
    echo "branch created, not an allowed branch: $name $new"; bad=1
  done < <(grep "$hd" "$aft")
  return $bad
}

# check RUN -> 0 and records RUN/verified when the refs are as the rule allows; 2 otherwise
check_run() {
  local run=$1 repo='' ref strict=1
  ref=$run/refs.before
  # the run's start (an epoch) bounds the lead's ref journal: prepare records it in RUN/started; an older run falls back to refs.before
  JSTART=$(cat "$run/started" 2>/dev/null || stat -c %Y "$run/refs.before" 2>/dev/null || true)
  [ ! -f "$run/verified" ] || { ref=$run/verified; strict=''; }
  if [ -f "$run/repo.url" ]; then
    snapshot_url "$(cat "$run/repo.url")" "$(cat "$run/cred.path" 2>/dev/null)" > "$run/refs.after"
  else
    repo=$(cat "$run/repo.path"); snapshot "$repo" > "$run/refs.after"
  fi
  if compare "$repo" "$ref" "$run/refs.after" "$strict" > "$run/refs.diff"; then
    cp "$run/refs.after" "$run/verified"
    return 0
  fi
  return 2
}

# render_warning REPO URL -> when the project this run belongs to has a Claude Code render (packs apply --target claude-code),
# runs its read-only check and, on findings, prints a WARNING block to stderr. Never fails the caller: a stale render must not
# block work. The project is the stored answers whose repo.path (or repo.url) is the one given; none found, nothing printed.
# No render directory (the usual case) costs no process: the glob below is the shell's own.
render_warning() {
  local m d prj f rp ru out
  for m in "$DA_STATE"/claude/*/MANIFEST.json; do
    [ -f "$m" ] || continue
    d=$(dirname "$m"); prj=$(basename "$d"); f=$DA_CONF/projects/$prj.json
    [ -f "$f" ] || continue
    rp=$(jq -r '.repo.path // ""' "$f" 2>/dev/null); rp=${rp/#\~/$HOME}; ru=$(jq -r '.repo.url // ""' "$f" 2>/dev/null)
    if [ -n "$1" ]; then [ -n "$rp" ] && [ "$(readlink -f "$rp")" = "$(readlink -f "$1")" ] || continue
    else [ -n "$ru" ] && [ "${ru%.git}" = "${2%.git}" ] || continue; fi
    out=$("$(dirname "$0")/packs.sh" packs check --target claude-code "$prj" 2>&1) && return 0
    { echo "WARNING: the Claude Code render of project $prj is out of date or altered (the run goes on):"
      sed 's/^/  /' <<<"$out"
      echo "  fix: qargi packs apply --target claude-code $prj"
      echo; } >&2
    return 0
  done
  return 0
}

# project_of REPO URL -> the stored project whose repo.path (or repo.url) is the one given; nothing when there is none
project_of() {
  local f rp ru
  for f in "$DA_CONF"/projects/*.json; do
    [ -f "$f" ] || continue
    rp=$(jq -r '.repo.path // ""' "$f" 2>/dev/null); rp=${rp/#\~/$HOME}; ru=$(jq -r '.repo.url // ""' "$f" 2>/dev/null)
    if [ -n "$1" ]; then [ -n "$rp" ] && [ "$(readlink -f "$rp")" = "$(readlink -f "$1")" ] || continue
    else [ -n "$ru" ] && [ "${ru%.git}" = "${2%.git}" ] || continue; fi
    basename "$f" .json; return 0
  done
  return 0
}

verb=${1:-}; shift || true
case $verb in
  prepare)
    REPO='' URL='' CRED='' BASE='' SLUG='' SCR='' ABILITY=build
    while [ $# -gt 0 ]; do
      case $1 in --repo) REPO=$2; shift 2;; --repo-url) URL=$2; shift 2;; --credential-file) CRED=$2; shift 2;; --base) BASE=$2; shift 2;; --slug) SLUG=$2; shift 2;; --scratch) SCR=$2; shift 2;; --ability|--role) ABILITY=$2; shift 2;; *) die "unknown option $1";; esac
    done
    if [ -n "$URL" ]; then
      [ -z "$REPO" ] || die "give --repo or --repo-url, not both"
      case $URL in https://*) ;; *) die "--repo-url must be an https URL";; esac
      [ -z "$CRED" ] || { CRED=${CRED/#\~/$HOME}; [ -f "$CRED" ] || die "--credential-file: no such file"; }
    else
      [ -d "$REPO/.git" ] || [ -f "$REPO/.git" ] || die "--repo must be a git working tree"
    fi
    [ "$ABILITY" != lead ] && valid_role "$ABILITY" || die "--role: one of $DA_ROLES (qargi role list)"
    CLASS=$(role_class "$ABILITY")
    valid_slug "$SLUG" || die "--slug: lower-case letters, digits and '-'"
    [ -n "$BASE" ] && [ -d "$SCR" ] || die "prepare needs --base BRANCH and --scratch DIR"
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
    mkdir -p "$RUN/out" "$RUN/home"
    # a private temporary directory for the run's test sandboxes, on tmpfs when there is one; `clean` removes it, so a run
    # leaves nothing behind in /dev/shm and parallel runs never touch each other's files
    SHM=${QARGI_RUN_TMP:-/dev/shm}   # QARGI_RUN_TMP moves it (the tests do), so a test never leaves anything in /dev/shm
    if [ -d "$SHM" ] && [ -w "$SHM" ]; then TMPD=$(mktemp -d "$SHM/qargi-run.XXXXXX"); else TMPD=$RUN/tmp; mkdir -p "$TMPD"; fi
    printf '%s\n' "$TMPD" > "$RUN/tmpdir"
    printf '%s\n' "$ABILITY" > "$RUN/ability"
    printf '%s\n' "$CLASS" > "$RUN/class"
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
    jq -nc --arg r "$RUN" --arg s "$SLUG" --arg a "$ABILITY" --arg b "$BASE" --arg t "$(now)" --arg l "$LEAD" \
      '{run:$r, slug:$s, ability:$a, base:$b, started:$t, lead:(if $l == "" then null else $l end)}' >> "$DA_STATE/local-runs.jsonl"
    chmod 600 "$DA_STATE/local-runs.jsonl" 2>/dev/null || true
    render_warning "$REPO" "$URL"
    echo "RUN=$RUN"
    echo "ABILITY=$ABILITY"
    echo "ROLE=$ABILITY"
    echo "CLASS=$CLASS"
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    BSHA=$(git -C "$RUN/clone" rev-parse "origin/$BASE")
    echo "BASE_SHA=$BSHA"
    echo
    echo "TASK-BLOCK PATHS"
    echo "RUN_DIR=$RUN"
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    echo "BASE_SHA=$BSHA"
    # the memory context packet: the tier summary and the always rows, for a repository that belongs to a stored project.
    # It never changes prepare's result: a failure or a timeout prints nothing.
    PPROJ=$(project_of "$REPO" "$URL")
    if [ -n "$PPROJ" ]; then
      tc=$(dirname "$(readlink -f "$0")")/tiercontext.py
      prel=$(timeout 3 python3 -I "$tc" repo-rel --project "$PPROJ" 2>/dev/null </dev/null) || prel=''
      pargs=(--project "$PPROJ" --role "$ABILITY")
      [ -z "$prel" ] || pargs+=(--repo-tier "$RUN/clone/$prel")
      [ -z "$REPO" ] || [ -z "$prel" ] || pargs+=(--checkout "$REPO")
      if pkt=$(timeout 8 python3 -I "$tc" packet "${pargs[@]}" </dev/null) && [ -n "$pkt" ]; then
        printf '\nTASK-BLOCK MEMORY\n%s\n' "$pkt"
      fi
    fi;;
  verify)
    RUN=${1:-}; [ -f "$RUN/refs.before" ] || die "verify needs a RUN dir made by prepare"
    if check_run "$RUN"; then
      if cmp -s "$RUN/refs.before" "$RUN/refs.after"; then echo "refs unchanged: nothing was pushed to the repository or its remote"
      else echo "refs differ from the snapshot only by lead-side fast-forwards and new branches; nothing was pushed"; fi
    else
      echo "REFS CHANGED during the run (the agent must not have pushed):" >&2
      cat "$RUN/refs.diff" >&2
      [ ! -f "$RUN/verified" ] && echo "(before the run's first passing verify a local branch may differ only as far as the lead's ref journal names it; every other ref must be identical)" >&2 \
        || echo "(a ref outside the allowed lead-side branch moves changed; the lead's ref journal does not apply after a passing verify)" >&2
      exit 2
    fi;;
  clean)
    # after the series is collected and verified: remove the run (clone, bare copy, output, wrapper) and its temporary directory
    RUN=${1:-}; shift || true; DISCARD=''
    [ "${1:-}" != --discard ] || DISCARD=1
    [ -f "$RUN/refs.before" ] && [ -f "$RUN/ability" ] && case $(basename "$RUN") in qargi.??????) ;; *) false;; esac \
      || die "clean needs a RUN dir made by prepare"
    [ -n "$DISCARD" ] || [ -f "$RUN/out/manifest.json" ] || [ -n "$(find "$RUN/out" -name '*manifest.json' 2>/dev/null | head -1)" ] \
      || die "$RUN/out holds no manifest: collect the work first, or --discard to drop a run that produced none"
    "$0" verify "$RUN" >/dev/null 2>&1 || die "the refs of the repository changed during this run: keep $RUN as evidence and tell the user (qargi local verify $RUN)"
    t=$(cat "$RUN/tmpdir" 2>/dev/null || true)
    case $t in */qargi-run.??????|"$RUN"/tmp) [ ! -d "$t" ] || rm -rf -- "$t";; esac
    rm -rf -- "$RUN"
    echo "cleaned $RUN${t:+ and $t}";;
  *) die "usage: local.sh prepare|verify|clean ...";;
esac
