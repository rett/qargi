# shellcheck shell=bash
# Sourced by the conformance harness (lib/conformance/run.sh), right after `set -u`. A copy of tests/hermetic.sh, so that the
# harness, which ships with the tool, needs nothing from tests/. Makes the run independent of the caller: no ANTHROPIC_* or
# QARGI_* variable gets through, HOME and qargi's config and state are fresh temporary directories, and the first `ant`,
# `claude` and `codex` on PATH are stubs that fail, so a check that did not bring its own fake cannot reach the real tools. The
# temporary directory is removed when the run exits.
for _v in $(compgen -e); do case $_v in ANTHROPIC_*|QARGI_*) unset "$_v";; esac; done
unset _v
HERMETIC=$(mktemp -d)
mkdir -p "$HERMETIC/home" "$HERMETIC/bin"
for _t in ant claude codex; do
  printf '#!/bin/sh\necho "hermetic test: the real %s is not available; put a fake first on PATH" >&2\nexit 127\n' "$_t" > "$HERMETIC/bin/$_t"
  chmod 755 "$HERMETIC/bin/$_t"
done
unset _t
export HOME=$HERMETIC/home QARGI_CONF=$HERMETIC/conf QARGI_STATE=$HERMETIC/state PATH=$HERMETIC/bin:$PATH
export XDG_CONFIG_HOME=$HERMETIC/home/.config XDG_STATE_HOME=$HERMETIC/home/.local/state
trap 'rm -rf "$HERMETIC"' EXIT
