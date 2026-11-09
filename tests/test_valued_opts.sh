#!/usr/bin/env bash
# A valued option given as the last word ends the command with exit 2 and "OPT needs a value": it never hangs and never
# dies on an unbound variable. The options come from the parsers themselves: every `--opt) need_val` branch of every
# lib/*.sh option loop is run as the last word of the verbs that script serves (SCRIPTS below), and a branch that reads
# its value without need_val, or a script with valued options that SCRIPTS does not name, fails the test.
# The same holds for the other usage errors: an unknown option and a missing argument end with exit 2.
# Run: tests/test_valued_opts.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
T=$(mktemp -d -p "$HERMETIC"); export TMPDIR=$T
mkdir -p "$QARGI_CONF/projects" "$QARGI_STATE"
echo '{}' > "$QARGI_CONF/projects/demo.json"   # verbs that look the project up before they read their options

# run_last "verb words" OPTION: prints the output and exit status of the command with OPTION as its last word
run_last() {
  local out rc
  # shellcheck disable=SC2086
  out=$(timeout 10 ./bin/qargi $1 "$2" 2>&1 </dev/null); rc=$?
  printf '%s\n%s' "$rc" "$out"
}
needs_value() { # "verb words" OPTION: true when the command ends with exit 2 and "OPTION needs a value"
  local res; res=$(run_last "$1" "$2")
  [ "${res%%$'\n'*}" = 2 ] && grep -q -- "$2 needs a value" <<<"${res#*$'\n'}" && ! grep -q 'unbound variable' <<<"$res"
}

# script -> the verbs (with their positional words) that reach its option loops. An option is tested against every verb
# of its script and passes when one of them reports that it needs a value.
declare -A SCRIPTS=(
  [agent.sh]="agent for build|agent add forge|agent list|agent models"
  [canon.sh]="canon check demo|canon plan demo|canon apply demo|canon seed-role demo|canon promote demo"
  [cred.sh]="credential check demo|credential setup lead-push demo"
  [feature.sh]="feature start x|feature list x|feature merge x y"
  [hook.sh]="hook session-start"
  [lead.sh]="lead grant demo|lead status demo|lead revoke demo"
  [local.sh]="local prepare|local clean|local list|local verify|local run"
  [memory.sh]="memory copy a b|memory split a b|memory merge a b|memory lint memstore_x|memory get memstore_x /a.md|memory init repo|memory move /a.md"
  [packs.sh]="skill list|skill new x|skill import x|tool list|tool import x|packs render|packs check"
  [project.sh]="project init demo|project new demo|project attach|project adopt demo|project link demo|project unlink demo|project set demo a b|project profile check demo"
  [provider.sh]="provider accept x"
  [provision.sh]="provision plan x|provision apply x"
  [release.sh]="release start|release finish"
  [registry.sh]="instances init|instances list|instances show x"
  [branch.sh]="branch prune"
  [changelog.sh]="changelog renumber"
  [upstream.sh]="upstream status|upstream review|upstream sync"
  [backlog.sh]="backlog list|backlog done x"
  [ref.sh]="ref record"
  [review.sh]="review apply x"
  [session.sh]="start x|send x|track x|status|stop x|close x"
  [supervise.sh]="supervise nudge x|supervise tick"
  [team.sh]="team brief demo t"
  [tierwrite.sh]="memory init repo|memory move /a.md"
  [upgrade.sh]="upgrade"
  [watch.sh]="watch x"
)

for f in lib/*.sh; do
  b=${f#lib/}
  case $b in lib.sh|marshal.sh) continue;; esac   # marshal.sh checks its options against a per-verb list: tests/test_marshal*.sh
  # a valued branch (its first statement reads the second word, or it shifts two words) without need_val
  bad=$(grep -oE -- '--[a-z][a-z-]*\) [^;]*(\$2|\$\{2)[^;]*|--[a-z][a-z-]*\) [^;]*; *shift 2' "$f" | grep -v 'need_val' || true)
  if [ -n "$bad" ]; then no "$b: valued branch without need_val: $bad"; fi
  opts=$(grep -oE -- '--[a-z][a-z-]*\) need_val' "$f" | sed 's/) need_val//' | sort -u)
  [ -n "$opts" ] || continue
  if [ -z "${SCRIPTS[$b]:-}" ]; then no "$b has valued options but is not named in SCRIPTS"; continue; fi
  IFS='|' read -ra verbs <<<"${SCRIPTS[$b]}"
  for o in $opts; do
    hit=''
    for v in "${verbs[@]}"; do if needs_value "$v" "$o"; then hit=$v; break; fi; done
    if [ -n "$hit" ]; then ok "$b: $hit $o"; else
      res=$(run_last "${verbs[0]}" "$o"); no "$b: $o is not rejected as a last word by any of: ${SCRIPTS[$b]} (first verb exit ${res%%$'\n'*}: ${res#*$'\n'})"
    fi
  done
done

# an unknown option is a usage error, exit 2, on every verb of every script (lib/release.sh has its own work in hand)
for b in "${!SCRIPTS[@]}"; do
  [ "$b" != release.sh ] || continue
  IFS='|' read -ra verbs <<<"${SCRIPTS[$b]}"
  hit=''
  for v in "${verbs[@]}"; do
    res=$(run_last "$v" --no-such-option)
    if [ "${res%%$'\n'*}" = 2 ] && grep -q "unknown option --no-such-option\|usage:" <<<"${res#*$'\n'}"; then hit=$v; break; fi
  done
  if [ -n "$hit" ]; then ok "$b: unknown option exits 2 ($hit)"; else no "$b: no verb of ${SCRIPTS[$b]} exits 2 on an unknown option (${verbs[0]}: ${res%%$'\n'*} ${res#*$'\n'})"; fi
done
# the Python verbs, and the shell verbs with a missing argument
usage_exit2() { # "verb words": an unknown option ends with exit 2 and a message
  local res; res=$(run_last "$1" --no-such-option)
  if [ "${res%%$'\n'*}" = 2 ] && [ -n "${res#*$'\n'}" ]; then ok "exit 2: $1 --no-such-option"; else no "$1 --no-such-option: exit ${res%%$'\n'*}: ${res#*$'\n'}"; fi
}
for w in "cloud" "discover search" "discover recommend" "discover install" "export" "import" "methodology files x" "report" "noticed" "review check"; do usage_exit2 "$w"; done
missing_arg() { # "verb words": no argument it needs -> exit 2 and a message
  local out rc
  # shellcheck disable=SC2086
  out=$(timeout 10 ./bin/qargi $1 2>&1 </dev/null); rc=$?
  if [ "$rc" = 2 ] && [ -n "$out" ]; then ok "exit 2: $1 (no argument)"; else no "$1 (no argument): exit $rc: $out"; fi
}
for w in "watch" "collect" "instances show" "instances remove" "project set demo" "team check" "agent rename" "agent refresh" "agent remove" "memory get" "provider accept" "role show"; do missing_arg "$w"; done
exit $fail
