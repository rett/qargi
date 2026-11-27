#!/usr/bin/env bash
# shellcheck disable=SC2034  # SQ_WAIT is read by history_end (gitflow.sh) and SQFD by the callers
# The shell side of the queue of the whole-suite runs (lib/suite_queue.py; docs/reference/suite-queue.md), sourced by lib/gitflow.sh (feature verify, release verify)
# and lib/suite.sh (qargi suite run). The caller has sourced lib.sh (DA_STATE, QARGI_TOOL).
#
# The slot is a flock on $DA_STATE/suite-queue/lock. The descriptor is opened by THIS shell and kept only while the suite runs: python takes the lock on it (an
# inherited descriptor: the lock belongs to the open file description, so it stays with this shell when python exits). The lock is the kernel's, so it cannot be left
# held: it is freed when the last process that has the descriptor ends, whatever way it ends. Those are this shell and the subshell that waits for the suite (a fork
# keeps the descriptor). What the suite starts never has it (squeue_closed closes it, and a program that is exec'd would not keep a copy), so a daemon a test leaves
# behind cannot keep the slot. A verb that is killed while its suite runs therefore leaves the slot taken until that suite ends, and not a moment longer.
#
#   squeue_acquire VERB NAME HEAD [BOUND]   wait in line (BOUND seconds at most, none: for ever), take the slot and set SQ_WAIT to the whole seconds waited; at the
#                                           bound the verb is refused as suite-queue-busy (exit 1, nothing taken, nothing left behind)
#   squeue_release                          let the slot go (the record of the holder, then the descriptor); safe to call again and from an exit trap
#   squeue_closed COMMAND...                run COMMAND (in this shell) with the descriptor of the slot closed, so that what it starts has no copy
#   squeue_sub COMMAND...                   run COMMAND in a subshell that waits for it and returns its status: with squeue_closed, the one process besides this shell
#                                           that keeps the slot while COMMAND runs (squeue_closed squeue_sub COMMAND...)
SQ_PY=$(dirname "${BASH_SOURCE[0]}")/suite_queue.py
SQFD=''          # the descriptor of the lock file while this shell holds the slot (or waits for it)
SQ_WAIT=0        # whole seconds this run waited for the slot, not counted in the seconds of its suite
SQ_PID=''        # the python process that waits on behalf of this shell
SQ_DIR=''        # the queue directory of this run
squeue_acquire() {
  local verb=$1 name=$2 head=${3:-} bound=${4:-} res rc=0 status='' waited=0 holder='' k v
  SQ_WAIT=0
  SQ_DIR=$(python3 -I "$SQ_PY" prepare --state "$DA_STATE") || fail "could not make the suite queue directory under $DA_STATE; nothing was run"
  exec {SQFD}< "$SQ_DIR/lock" || fail "could not open the lock file of the suite queue ($SQ_DIR/lock); nothing was run"
  res=$SQ_DIR/result.$$
  rm -f "$res"
  # a background job, waited for: a signal that has a trap (the verb's INT and TERM traps, hold_begin) runs at once, not when python ends, and squeue_release then stops it
  python3 -I "$SQ_PY" acquire --state "$DA_STATE" --fd "$SQFD" --owner "$$" --project "${PROJ:-}" --verb "$verb" --name "$name" --head "$head" \
    ${bound:+--bound "$bound"} --result "$res" </dev/null &
  SQ_PID=$!
  wait "$SQ_PID" || rc=$?
  SQ_PID=''
  if [ -f "$res" ]; then
    while IFS='=' read -r k v; do
      case $k in status) status=$v;; waited) waited=$v;; holder) holder=$v;; esac
    done < "$res"
    rm -f "$res"
  fi
  case $rc:$status in
    0:ok) case $waited in ''|*[!0-9]*) waited=0;; esac; SQ_WAIT=$waited; return 0;;
    4:busy) squeue_release; case $waited in ''|*[!0-9]*) waited=0;; esac
            # shellcheck disable=SC2034  # QARGI_VERB is read by refuse (lib/lib.sh): the verb of the contract line (release.sh sets none of its own)
            QARGI_VERB=$verb
            refuse suite-queue-busy verb="$verb" holder="${holder:-unknown}" waited="$waited";;
    *) squeue_release; fail "could not take the slot of the suite queue (status $rc); nothing was run";;
  esac
}
squeue_release() {
  [ -z "$SQ_PID" ] || { kill "$SQ_PID" 2>/dev/null; wait "$SQ_PID" 2>/dev/null; SQ_PID=''; }
  [ -n "$SQFD" ] || return 0
  python3 -I "$SQ_PY" release --state "$DA_STATE" --owner "$$" 2>/dev/null || true
  exec {SQFD}<&-
  SQFD=''
}
squeue_closed() { # COMMAND...
  if [ -n "$SQFD" ]; then "$@" {SQFD}<&-; else "$@"; fi
}
squeue_sub() { ( "$@"; exit $? ); }   # the exit keeps the subshell from replacing itself with the last command
