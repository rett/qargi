# shellcheck shell=bash
# Sourced by every shell test, right after `set -u`. Makes the test independent of the caller: no ANTHROPIC_*
# or QARGI_* variable gets through, HOME and qargi's config and state are fresh temporary directories, and the
# first `ant` and `claude` on PATH are stubs that fail, so a test that did not bring its own fake cannot reach
# the real tools. A test overrides any of this after sourcing (most set their own QARGI_CONF, QARGI_STATE, HOME
# and a fake ant). The temporary directory is removed when the test exits.
for _v in $(compgen -e); do case $_v in ANTHROPIC_*|QARGI_*) unset "$_v";; esac; done
unset _v
HERMETIC=$(mktemp -d)
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
