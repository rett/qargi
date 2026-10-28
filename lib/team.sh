#!/usr/bin/env bash
# Teams: a lead and the role agents it coordinates on one task (opt-in; see the qargi-team skill).
#   team.sh brief PROJECT TEAM --task TEXT --done CMD [--base BRANCH] [--write-done CMD] [--review-done CMD]
#       prints the TEAM brief for the lead (a cloud lead session or this session acting as lead)
#   team.sh check RUN_DIR
#   team.sh contract
#       prints the lead's contract (the procedure of any lead: this session, a cloud lead, or one started in the console)
#       checks a collected team run: every member's output with the patch/report checker, and the lead's team.json
. "$(dirname "$0")/lib.sh"

here=$(dirname "$(readlink -f "$0")")
verb=${1:-}; shift || true

brief() {
  local project=${1:-} team=${2:-}; shift 2 || true
  local task='' done_cmd='' base='' write_done='' review_done=''
  while [ $# -gt 0 ]; do
    case $1 in
      --task) task=$2; shift 2;;
      --done) done_cmd=$2; shift 2;;
      --base) base=$2; shift 2;;
      --write-done) write_done=$2; shift 2;;
      --review-done) review_done=$2; shift 2;;
      *) die "unknown option $1";;
    esac
  done
  valid_project "$project" || die "usage: team.sh brief PROJECT TEAM --task TEXT --done CMD"
  local f=$DA_CONF/projects/$project.json
  [ -f "$f" ] || die "no stored answers for $project"
  jq -e --arg t "$team" '.teams[$t]' "$f" >/dev/null 2>&1 || die "project $project has no team '$team' (qargi project show $project)"
  [ -n "$task" ] && [ -n "$done_cmd" ] || die "brief needs --task TEXT and --done CMD (an executable check for the builder's part)"
  local build_base; build_base=$(jq -r '.roles.build.base // empty' "$f")
  if [ -z "$base" ]; then
    [ -n "$build_base" ] && [ "$build_base" != "@dispatcher" ] || die "the builder's base is @dispatcher: give --base BRANCH"
    base=$build_base
  fi
  local rdone="test -s /mnt/session/outputs/review--report.md && grep -qiE '^#+ *findings' /mnt/session/outputs/review--report.md"
  printf 'TEAM: %s\nTASK: %s\n' "$team" "$task"
  jq -r --arg t "$team" '.teams[$t] | "STANDARDS: " + ((.standards // []) | if length == 0 then "none" else join(", ") end) + "\nMAX_ROUNDS: \(.max_rounds // 2)"' "$f"
  echo "MEMBERS:"
  local m mbase scope mdone
  for m in $(jq -r --arg t "$team" '.teams[$t].members[]' "$f"); do
    case $m in
      build) mbase=$base; mdone=$done_cmd;;
      write) mbase=$(jq -r '.roles.write.base' "$f"); mdone=${write_done:-$(jq -r --arg t "$team" '.teams[$t].done.write // "make lint"' "$f")};;
      review) mbase=$base; mdone=${review_done:-$rdone};;
      *) mbase=$(jq -r --arg r "$m" '.roles[$r].base' "$f"); [ "$mbase" != "@dispatcher" ] || mbase=$base; mdone=$(jq -r --arg t "$team" --arg r "$m" '.teams[$t].done[$r] // empty' "$f");;
    esac
    [ -n "$mdone" ] || die "member $m has no DONE check: give one in the project's teams.$team.done.$m"
    scope=$(jq -r --arg t "$team" --arg r "$m" '(.teams[$t].scopes[$r] // []) | if length == 0 then "none" else join(", ") end' "$f")
    printf -- '- role: %s\n  ABILITY: %s — load skill qargi-%s\n  BASE: %s\n  SCOPE: %s\n  CLONE: /workspace/%s\n  RUN_DIR: /mnt/session/outputs\n  OUT_PREFIX: %s--\n  DONE: %s\n' "$m" "$m" "$m" "$mbase" "$scope" "$m" "$m" "$mdone"
  done
}

check() {
  local dir=${1:-} rc=0 d r
  [ -d "$dir" ] || die "usage: team.sh check RUN_DIR (a directory made by: qargi collect SID DIR)"
  for d in "$dir"/*/; do
    r=$(basename "$d")
    [ "$r" != lead ] || continue
    echo "== $r"
    python3 -I "$here/review_check.py" "$d" --allow-empty || rc=1
  done
  if [ -f "$dir/lead/team.json" ]; then
    tj=$dir/lead/team.json
    v=$(jq -r '.verdict // .final_verdict // ""' "$tj" 2>/dev/null)   # the lead's own spelling is accepted: verdict or final_verdict
    jq -e '.team and .members' "$tj" >/dev/null 2>&1 && [ -n "$v" ] \
      && echo "== lead: team $(jq -r .team "$tj"), verdict $v, status $(jq -r '.status // "?"' "$tj"), rounds $(jq -r '.rounds // "?"' "$tj")" \
      || { echo "FAIL lead/team.json lacks team, members or verdict"; rc=1; }
    [ "$v" = accept ] || { echo "NOTE the team did not reach accept: read lead/summary.md before anything is applied"; }
    case $(jq -r '.status // ""' "$tj" 2>/dev/null) in BLOCKED*) echo "NOTE the lead reports BLOCKED: $(jq -r '.status_reason // "no reason given"' "$tj" | cut -c1-200)";; esac
  else
    echo "FAIL no lead/team.json: the lead's report is missing"; rc=1
  fi
  return $rc
}

contract() {
  local f=$here/../provision/role-seeds/lead/contract.md
  [ -f "$f" ] || f=$here/provision/role-seeds/lead/contract.md
  cat "$f"
}

case $verb in
  contract) contract;;
  brief) brief "$@";;
  check) check "$@";;
  *) die "usage: team.sh brief|check|contract ...";;
esac
