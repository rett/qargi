# shellcheck shell=bash
# Sourced by every shell test, right after `set -u`. Makes the test independent of the caller: no ANTHROPIC_*
# or QARGI_* variable gets through, HOME and qargi's config and state are fresh temporary directories, and the
# first `ant` and `claude` on PATH are stubs that fail, so a test that did not bring its own fake cannot reach
# the real tools. A test overrides any of this after sourcing (most set their own QARGI_CONF, QARGI_STATE, HOME
# and a fake ant). The temporary directory is removed when the test exits.
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
mkdir -p "$HERMETIC/home" "$HERMETIC/bin"
for _t in ant claude; do
  printf '#!/bin/sh\necho "hermetic test: the real %s is not available; put a fake first on PATH" >&2\nexit 127\n' "$_t" > "$HERMETIC/bin/$_t"
  chmod 755 "$HERMETIC/bin/$_t"
done
unset _t
export HOME=$HERMETIC/home QARGI_CONF=$HERMETIC/conf QARGI_STATE=$HERMETIC/state PATH=$HERMETIC/bin:$PATH
export XDG_CONFIG_HOME=$HERMETIC/home/.config XDG_STATE_HOME=$HERMETIC/home/.local/state
trap 'rm -rf "$HERMETIC"' EXIT

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
