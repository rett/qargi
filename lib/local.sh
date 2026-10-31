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
# prepare also appends one JSON line per run to $QARGI_STATE/local-runs.jsonl (run directory, slug, ability, base,
# start time; never a repository path or a token), so `qargi report` can list the local runs.
. "$(dirname "$0")/lib.sh"

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
    case $BASE in master|develop) ;; esac
    RUN=$(mktemp -d "$SCR/qargi.XXXXXX")
    mkdir -p "$RUN/out" "$RUN/home"
    # a private temporary directory for the run's test sandboxes, on tmpfs when there is one; `clean` removes it, so a run
    # leaves nothing behind in /dev/shm and parallel runs never touch each other's files
    SHM=${QARGI_RUN_TMP:-/dev/shm}   # QARGI_RUN_TMP moves it (the tests do), so a test never leaves anything in /dev/shm
    if [ -d "$SHM" ] && [ -w "$SHM" ]; then TMPD=$(mktemp -d "$SHM/qargi-run.XXXXXX"); else TMPD=$RUN/tmp; mkdir -p "$TMPD"; fi
    printf '%s\n' "$TMPD" > "$RUN/tmpdir"
    printf '%s\n' "$ABILITY" > "$RUN/ability"
    printf '%s\n' "$CLASS" > "$RUN/class"
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
    jq -nc --arg r "$RUN" --arg s "$SLUG" --arg a "$ABILITY" --arg b "$BASE" --arg t "$(now)" \
      '{run:$r, slug:$s, ability:$a, base:$b, started:$t}' >> "$DA_STATE/local-runs.jsonl"
    chmod 600 "$DA_STATE/local-runs.jsonl" 2>/dev/null || true
    echo "RUN=$RUN"
    echo "ABILITY=$ABILITY"
    echo "ROLE=$ABILITY"
    echo "CLASS=$CLASS"
    echo "CLONE=$RUN/clone"
    echo "OUT=$RUN/out"
    echo "TMP=$TMPD"
    echo "GIT=$RUN/git"
    echo "BASE_SHA=$(git -C "$RUN/clone" rev-parse "origin/$BASE")";;
  verify)
    RUN=${1:-}; [ -f "$RUN/refs.before" ] || die "verify needs a RUN dir made by prepare"
    if [ -f "$RUN/repo.url" ]; then
      snapshot_url "$(cat "$RUN/repo.url")" "$(cat "$RUN/cred.path" 2>/dev/null)" > "$RUN/refs.after"
    else
      snapshot "$(cat "$RUN/repo.path")" > "$RUN/refs.after"
    fi
    if diff -u "$RUN/refs.before" "$RUN/refs.after" > "$RUN/refs.diff"; then
      echo "refs unchanged: nothing was pushed to the repository or its remote"
    else
      echo "REFS CHANGED during the run (the agent must not have pushed):" >&2
      cat "$RUN/refs.diff" >&2
      exit 1
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
