#!/usr/bin/env bash
# qargi suite: the queue of the whole-suite runs of one user (lib/suite_queue.py, lib/suite_queue.sh; docs/reference/suite-queue.md).
#
#   suite.sh run -- COMMAND [ARGS...]     take a slot of the queue (waiting its turn, first in, first out, as feature verify and release verify do), run COMMAND with its
#                                         standard input, output and error as they are, let the slot go and exit with the status of COMMAND. For a suite that is run by
#                                         hand, or by a supervisor to verify a run. It records nothing in the history of the whole-suite runs: that is for feature
#                                         verify and release verify, which say what was verified. The slot is held while COMMAND runs and not a moment longer.
#   suite.sh status [--json]              the holder and the waiters (position, project, verb, name, age); with --json one document of the draft kind qargi-suite-queue
#
# Moving a run forward in the queue is not offered: the order is the order of arrival.
. "$(dirname "$0")/lib.sh"
. "$(dirname "$0")/suite_queue.sh"

verb=${1:-}; shift || true
case $verb in
  run)
    [ "${1:-}" = -- ] || usage_die "usage: qargi suite run -- COMMAND [ARGS...] (the command follows --, so that its own options are its own)"
    shift
    [ $# -gt 0 ] || usage_die "usage: qargi suite run -- COMMAND [ARGS...] (no command after --)"
    # shellcheck disable=SC2034  # PROJ is read by squeue_acquire (lib/suite_queue.sh): the project the run is recorded under, none outside a project
    PROJ=$(python3 -I "$SQ_PY" project 2>/dev/null) || PROJ=''
    trap 'squeue_release' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    name=$(basename -- "$1")   # what the queue shows: the command and, when it is a word and no option, its first argument (never the rest of the line)
    if [ $# -ge 2 ]; then case $2 in -*|*=*) ;; *) name="$name $(basename -- "$2")";; esac; fi
    squeue_acquire "suite run" "$name" ""
    rc=0
    squeue_closed squeue_sub command -- "$@" || rc=$?
    squeue_release
    exit "$rc";;
  status)
    json=''
    for a in "$@"; do
      case $a in
        --json) json=--json;;
        *) usage_die "usage: qargi suite status [--json]";;
      esac
    done
    exec python3 -I "$SQ_PY" status --state "$DA_STATE" ${json:+"$json"};;
  *) usage_die "usage: qargi suite run -- COMMAND [ARGS...] | qargi suite status [--json]";;
esac
