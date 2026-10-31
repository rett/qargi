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
