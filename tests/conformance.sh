#!/usr/bin/env bash
# The conformance suite of a provider adapter, for the runtimes this repository ships (claude-code, claude-platform, the fixtures
# under tests/providers/). The suite itself is lib/conformance/run.sh, which ships with the tool because `qargi provider check` runs
# it on the adapter of a library pack; this wrapper keeps the arguments, the output and the exit status of the command the
# tests and CONTRIBUTING use.
#
# Usage: tests/conformance.sh NAME [--stub DIR] [--tool DIR]      (the arguments are run.sh's; see its header for the cases)
CONFORMANCE_PROG=tests/conformance.sh exec bash "$(dirname "${BASH_SOURCE[0]}")/../lib/conformance/run.sh" "$@"
