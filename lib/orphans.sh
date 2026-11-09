#!/usr/bin/env bash
# The qargi-run.XXXXXX directories under the run temporary parent (/dev/shm, or QARGI_RUN_TMP) that no run of the lead's registry names: the one scan that
# `qargi local clean --orphans` and `qargi doctor` both read. It only reads; nothing is removed here (clean removes, behind a plan token and the lead's words).
#
#   orphan_scan ROOT DAYS    ROOT is the parent, already checked to be a real directory and made absolute; DAYS a whole number, at least 1.
#                            Prints one line per entry (kept ... or orphan ...) and sets ORPH_LIST (the orphans, each "PATH MTIME"), ORPH_KEPT and ORPH_TOTAL.
#   orphans.sh ROOT DAYS     the same from the command line: the lines, then "total N orphan M kept K"; exit 2 when ROOT is no directory.
# Run as a program (qargi doctor does) it only reads: lib.sh is loaded without its setup, so a host that never ran qargi gets no directory or file from it.
type reg_load >/dev/null 2>&1 || DA_NOSETUP=1 . "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

orphan_scan() {
  local oroot=$1 days=$2 nowe cutoff d t e mt age rd rst
  local -A named=()
  nowe=$(date +%s); cutoff=$((nowe - days * 86400))
  reg_load
  for d in ${LRUNS_ORDER[@]+"${LRUNS_ORDER[@]}"}; do
    t=$(reg_get "$d" tmpdir); [ -n "$t" ] || continue
    named[$(readlink -m -- "$t")]=$d
  done
  ORPH_LIST=(); ORPH_KEPT=0; ORPH_TOTAL=0
  for e in "$oroot"/qargi-run.??????; do
    [ -e "$e" ] || [ -L "$e" ] || continue
    ORPH_TOTAL=$((ORPH_TOTAL + 1))
    if [ -L "$e" ] || [ ! -d "$e" ]; then echo "kept $e: not a directory prepare makes (a link or a file)"; ORPH_KEPT=$((ORPH_KEPT + 1)); continue; fi
    mt=$(stat -c %Y -- "$e" 2>/dev/null) || mt=''
    [[ $mt =~ ^[0-9]{1,12}$ ]] || { echo "kept $e: its age cannot be read"; ORPH_KEPT=$((ORPH_KEPT + 1)); continue; }
    age=$(( (nowe - mt) / 86400 ))
    if [ -n "${named[$e]+x}" ]; then
      rd=${named[$e]}; if [ -d "$rd" ]; then rst="its run directory $rd exists"; else rst="the run directory $rd is gone"; fi
      echo "kept $e (${age}d old): named by the registry ($rst)"; ORPH_KEPT=$((ORPH_KEPT + 1)); continue
    fi
    if [ ! -O "$e" ]; then echo "kept $e (${age}d old): not owned by this user"; ORPH_KEPT=$((ORPH_KEPT + 1)); continue; fi
    if [ "$mt" -gt "$cutoff" ] || [ -n "$(find "$e" -xdev -newermt "@$cutoff" -print -quit 2>/dev/null)" ]; then
      echo "kept $e (${age}d old): named by no registry, but it or something in it changed within ${days} day(s)"; ORPH_KEPT=$((ORPH_KEPT + 1)); continue
    fi
    echo "orphan $e (${age}d old, named by no registry)"; ORPH_LIST+=("$e $mt")
  done
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  [ $# = 2 ] && [ -d "$1" ] && [ ! -L "$1" ] || { echo "usage: orphans.sh ROOT DAYS (ROOT a directory, not a link)" >&2; exit 2; }
  orphan_scan "$(readlink -f -- "$1")" "$2"
  echo "total $ORPH_TOTAL orphan ${#ORPH_LIST[@]} kept $ORPH_KEPT"
fi
