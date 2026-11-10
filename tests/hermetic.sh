# shellcheck shell=bash
# Sourced by every shell test, right after `set -u`. Makes the test independent of the caller. The environment is the caller's with an
# allowlist applied as explicit exports and unsets (a full `env -i` would drop what the tests need to find their tools, the PATH
# search for git, jq and python3 and the shell's own variables, and every test would then have to rebuild it): no ANTHROPIC_* or QARGI_*
# variable gets through; HOME, TMPDIR, qargi's config and state are fresh directories under one temporary directory (HERMETIC); the
# first `ant` and `claude` on PATH are stubs that fail, so a test that did not bring its own fake cannot reach the real tools; the
# locale, time zone and umask are fixed (LANG=C.UTF-8, TZ=UTC, umask 022); git reads no configuration of the host or the user
# (GIT_CONFIG_GLOBAL=/dev/null, GIT_CONFIG_NOSYSTEM=1) and has a default branch name from the environment (no identity: a test that commits sets
# its own, in the repository or in GIT_AUTHOR_*, as it did when HOME was a fresh directory); no
# GIT_DIR, GIT_WORK_TREE, SSH_AUTH_SOCK, SSH_ASKPASS, PYTHONPATH or PYTHONSTARTUP; python writes no bytecode into the source tree
# (PYTHONDONTWRITEBYTECODE is ignored under `python3 -I`, which qargi's scripts and the tests use throughout, so the first `python3` on PATH
# is a wrapper that adds -B; tests/test_hermetic.sh checks that a run, the conformance suite included, leaves no __pycache__: the provider adapters, the
# guard command they run and lib/conformance/cases.py start python again with sys.executable -I and pass -B on when the process that starts them has it)
# and reads no user site; output has no colour, 80 columns, a dumb terminal. A test overrides any of this after sourcing (most set their
# own QARGI_CONF, QARGI_STATE, HOME and a fake ant). The temporary directory is removed when the test exits. tests/hermetic.py is the
# same environment for the python tests.
# A test stops when mktemp fails (exit status 1, or 143 when the call is inside $(...)): the directory it makes its files in is gone
# (TMPDIR removed under it, as logind does to /dev/shm when the user's last session ends and RemoveIPC is on). Without the stop,
# T=$(mktemp -d) and w=$(mktemp -d "$T/w.XXXXXX") come back empty and the test goes on in /, in $HOME or in the checkout it runs from.
for _v in $(compgen -e); do case $_v in ANTHROPIC_*|QARGI_*) unset "$_v";; esac; done
unset _v
mktemp() {
  command mktemp "$@" && return 0
  printf 'hermetic test: mktemp %s failed (TMPDIR=%s): the test stops before it works outside its temporary directory\n' "$*" "${TMPDIR:-unset}" >&2
  kill -TERM "$$"; exit 1
}
if [ -n "${TMPDIR:-}" ] && { [ ! -d "$TMPDIR" ] || [ ! -w "$TMPDIR" ]; }; then
  printf 'hermetic test: TMPDIR=%s is not a writable directory: the test does not run\n' "$TMPDIR" >&2; exit 1
fi
HERMETIC=$(command mktemp -d) || { echo "hermetic test: cannot make a temporary directory" >&2; exit 1; }
mkdir -p "$HERMETIC/home" "$HERMETIC/bin" "$HERMETIC/tmp"
for _t in ant claude; do
  printf '#!/bin/sh\necho "hermetic test: the real %s is not available; put a fake first on PATH" >&2\nexit 127\n' "$_t" > "$HERMETIC/bin/$_t"
  chmod 755 "$HERMETIC/bin/$_t"
done
unset _t
# the wrapper: the real python3 with -B. `python3 -I` ignores PYTHONDONTWRITEBYTECODE, and every qargi script and test starts that way.
if _py=$(command -v python3); then
  printf '#!/bin/sh\nexec %s -B "$@"\n' "'$_py'" > "$HERMETIC/bin/python3"
  chmod 755 "$HERMETIC/bin/python3"
fi
unset _py
export HOME=$HERMETIC/home QARGI_CONF=$HERMETIC/conf QARGI_STATE=$HERMETIC/state PATH=$HERMETIC/bin:$PATH
export XDG_CONFIG_HOME=$HERMETIC/home/.config XDG_STATE_HOME=$HERMETIC/home/.local/state
# what the test and the verbs it runs make with mktemp goes into the test's own temporary directory (HERMETIC), removed with it; the
# directory of the caller (HERMETIC's parent) is left as it was
export TMPDIR=$HERMETIC/tmp
if locale -a 2>/dev/null | grep -qix 'c\.utf-\?8'; then export LANG=C.UTF-8; else export LANG=C; fi
unset LC_ALL LANGUAGE
export TZ=UTC NO_COLOR=1 COLUMNS=80 TERM=dumb PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1
unset GIT_DIR GIT_WORK_TREE GIT_INDEX_FILE SSH_AUTH_SOCK SSH_ASKPASS PYTHONPATH PYTHONSTARTUP
umask 022
export GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1 GIT_TERMINAL_PROMPT=0
export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=init.defaultBranch GIT_CONFIG_VALUE_0=master
trap 'kill_bg; rm -rf "$HERMETIC"' EXIT

# spawn_bg CMD [ARG...] [REDIRECTIONS]: starts CMD in the background, writes its pid to HERMETIC/pids and leaves it in SPAWNED_PID.
# kill_bg kills every pid spawn_bg recorded, by pid (never by a pattern over the command lines, which also finds the processes of other
# runs). The EXIT trap of this file calls kill_bg; a test that sets its own EXIT trap calls kill_bg in it.
spawn_bg() { "$@" & SPAWNED_PID=$!; echo "$SPAWNED_PID" >> "$HERMETIC/pids"; }
kill_bg() {
  local p
  [ -f "$HERMETIC/pids" ] || return 0
  while read -r p; do kill "$p" 2>/dev/null; done < "$HERMETIC/pids"
  : > "$HERMETIC/pids"
}

# What a test copies to run a modified copy of the tool: the top-level directories and files below, whichever exist in the source. A new
# top-level directory of the repository is added here once (tests/test_tool_copy.sh fails until it is, or is named there as not needed);
# tests/hermetic.py reads this line.
TOOL_DIRS="agents bin lib roles skills provision contract canon methodologies packs catalog VERSION"
# copy_tool SRC DEST [NAME...]: copies the entries of TOOL_DIRS that exist in SRC (or only the NAMEs given) into DEST, made if missing.
copy_tool() {
  local src=$1 dest=$2 d; shift 2
  local -a names=("$@")
  [ ${#names[@]} -gt 0 ] || read -ra names <<<"$TOOL_DIRS"
  mkdir -p "$dest"
  for d in "${names[@]}"; do [ ! -e "$src/$d" ] || cp -r "$src/$d" "$dest/"; done
}
