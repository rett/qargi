#!/usr/bin/env bash
# shellcheck disable=SC2154  # af and REPO come from gitflow.sh (project_load)
# The numbered items of a project's changelog (the opt-in answer release.changelog.numbered; lib/changelog_numbers.py holds the format).
#
#   changelog.sh renumber [--project P] [--check]
#       Finds the duplicate item numbers under the unreleased heading of CHANGELOG.md (the answer release.changelog.unreleased, default
#       '## [Unreleased]') in the work tree around the current directory, which must be a work tree of the project (the feature's worktree, not the
#       main checkout while it rests on the parking branch). An item is a line that starts 'N. ' or '- N. '. Without --check the items are numbered
#       again in file order and the '(item N)' cross-references follow; the file is rewritten and left uncommitted. With --check nothing is written
#       and the exit status is 1 when a number is duplicated. feature sync and feature finish run the check when the answer is true.
. "$(dirname "$0")/lib.sh"

USAGE="usage: qargi changelog renumber [--project P] [--check]"
verb=${1:-}; shift || true
PROJ='' CHECK=''
while [ $# -gt 0 ]; do
  case $1 in
    --project) need_val "$1" $#; PROJ=$2; shift 2;; --check) CHECK=--check; shift;;
    -*) usage_die "unknown option $1";;
    *) usage_die "$USAGE";;
  esac
done
[ "$verb" = renumber ] || usage_die "$USAGE"
. "$(dirname "$0")/gitflow.sh"
project_load
top=$(git rev-parse --show-toplevel 2>/dev/null) || die "run this in a work tree of $PROJ (the feature's worktree): $PWD is in no git work tree"
[ "$(readlink -f "$(git -C "$top" rev-parse --path-format=absolute --git-common-dir)")" = "$(readlink -f "$(git -C "$REPO" rev-parse --path-format=absolute --git-common-dir)")" ] \
  || die "$top is not a work tree of $PROJ ($REPO): run this in one of its work trees"
rc=0
python3 -I "$(dirname "$0")/changelog_numbers.py" renumber "$top/CHANGELOG.md" "$af" $CHECK || rc=$?
[ "$rc" = 0 ] || exit 1
