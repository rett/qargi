#!/usr/bin/env bash
# shellcheck disable=SC2154  # af, REPO, PROJ come from gitflow.sh (project_load)
# The backlog of a project: a markdown file the answer backlog.file names (a path; ~/ and a path relative to the repository work; the file may
# live outside the repository, in a memory store for instance). lib/backlog.py reads and writes it.
#
#   backlog.sh list [--json] [--project P]     the open items with their ids; an item without an id is shown as unnumbered; a duplicated id is flagged
#   backlog.sh add ID TEXT [--detail TEXT] [--project P]
#                                              append the item `- [ID] TEXT` (the detail as indented lines) at the end of the list: of the section when
#                                              backlog.section is set, else of the file. An id that is no slug, or is taken anywhere in the file, is refused.
#   backlog.sh done ID [ID...] --evidence TEXT [--project P] [--plan T --approved W]
#                                              move the items, with the evidence and the date, to NAME-archive-YYYY-MM.md beside the backlog file
#                                              (appended; created when absent) and remove them from the backlog. One plan and one token for the whole
#                                              batch, the same evidence archived with each id: nothing is deleted without them. The plan shows the
#                                              items and the file they go to; an id that is missing, used twice or named twice refuses the batch.
#   Answers read besides backlog.file: backlog.archive (the directory the archives go to, or a path ending in .md for the one archive file; default: beside the
#   backlog file) and backlog.section (a heading: only the list under it holds items).
# An item is a top-level list line, `- [ID] text`, ID a lowercase slug (letters, digits, hyphens; two characters or more), with the indented
# lines after it. feature finish and release finish list the open items whose id the merged commits' messages name (lib/gitflow.sh backlog_note).
. "$(dirname "$0")/lib.sh"

verb=${1:-}; shift || true
PROJ='' PLAN_ARG='' APPROVED='' JSON='' EVIDENCE='' EVSET='' DETAIL='' DETSET='' POS=()
USAGE="usage: qargi backlog list [--json] [--project P] | add ID TEXT [--detail TEXT] [--project P] | done ID [ID...] --evidence TEXT [--project P] [--plan T --approved WORDS]"
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --plan) need_val "$1" $#; PLAN_ARG=$2; shift 2;; --approved) need_val "$1" $#; APPROVED=$2; shift 2;;
    --evidence) need_val "$1" $#; EVIDENCE=$2; EVSET=1; shift 2;;
    --detail) need_val "$1" $#; DETAIL=$2; DETSET=1; shift 2;;
    --json) JSON=1; shift;;
    -*) usage_die "unknown option $1";;
    *) POS+=("$1"); shift;;
  esac
done
export PLAN_ARG   # need_plan reads it
case $verb in
  list) [ ${#POS[@]} = 0 ] && [ -z "$EVSET" ] && [ -z "$DETSET" ] && [ -z "$PLAN_ARG" ] && [ -z "$APPROVED" ] || usage_die "$USAGE";;
  add) [ ${#POS[@]} = 2 ] && [ -z "$JSON" ] && [ -z "$EVSET" ] && [ -z "$PLAN_ARG" ] && [ -z "$APPROVED" ] || usage_die "$USAGE";;
  done) [ ${#POS[@]} -ge 1 ] && [ -z "$JSON" ] && [ -z "$DETSET" ] || usage_die "$USAGE";;
  *) usage_die "$USAGE";;
esac
. "$(dirname "$0")/gitflow.sh"
project_load
BF=$(backlog_file) || exit 1
BL=$(dirname "$0")/backlog.py
# backlog.archive (a directory, or a path ending in .md for one archive file; ~/ and a path relative to the repository work) and backlog.section (a
# heading: only the list under it holds items) go to backlog.py as options; without them the archive is beside the file and the whole file is read
BO=()
ba=$(jq -r '.backlog.archive // ""' "$af" 2>/dev/null) || ba=''
if [ -n "$ba" ]; then ba=${ba/#\~/$HOME}; case $ba in /*) ;; *) ba=$REPO/$ba;; esac; BO+=(--archive "$ba"); fi
bs=$(jq -r '.backlog.section // ""' "$af" 2>/dev/null) || bs=''
[ -z "$bs" ] || BO+=(--section "$bs")

case $verb in
  list)
    if [ -n "$JSON" ]; then python3 -I "$BL" list "$BF" --json ${BO[@]+"${BO[@]}"}; else python3 -I "$BL" list "$BF" ${BO[@]+"${BO[@]}"}; fi;;
  add)
    if [ -n "$DETSET" ]; then python3 -I "$BL" add "$BF" "${POS[0]}" "${POS[1]}" "$DETAIL" ${BO[@]+"${BO[@]}"} || exit 1
    else python3 -I "$BL" add "$BF" "${POS[0]}" "${POS[1]}" ${BO[@]+"${BO[@]}"} || exit 1; fi
    audit_log "backlog:add" "$PROJ ${POS[0]}";;
  done)
    [ -n "$EVSET" ] || usage_die "done needs --evidence TEXT: the words that show the item is done (they go into the archive)"
    for i in "${POS[@]}"; do case $i in *,*) usage_die "ID: one id at a time, separated by spaces, not commas (got '$i')";; esac; done
    IDS=$(IFS=,; echo "${POS[*]}")   # the ids, joined by commas for backlog.py
    SHOWN=${POS[*]}
    plan=$(python3 -I "$BL" plan "$BF" "$IDS" "$EVIDENCE" ${BO[@]+"${BO[@]}"}) || exit 1
    tok=$(python3 -I "$BL" token "$BF" "$IDS" "$EVIDENCE" ${BO[@]+"${BO[@]}"}) || exit 1
    printf '%s\n' "$plan"
    if [ -z "$APPROVED" ]; then echo "plan token: $tok   (apply with: qargi backlog done $SHOWN --evidence \"...\" --plan $tok --approved \"...\")"; exit 0; fi
    need_plan "$tok"   # a caller that is itself approved has not approved this plan: the token is always needed
    python3 -I "$BL" apply "$BF" "$IDS" "$EVIDENCE" ${BO[@]+"${BO[@]}"} || exit 1
    audit_log "backlog:done" "$PROJ $SHOWN";;
esac
