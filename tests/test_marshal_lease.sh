#!/usr/bin/env bash
# The lease of a feature outlives a long worker run: any verb of the lead on the feature renews it (marshal_check, marshal_touch,
# marshal_touch_run), a stranger renews nothing, and release after feature finish is quiet. Time is injected with QARGI_MARSHAL_NOW
# (epoch seconds; the default ttl is 15 minutes), so no step waits.
# Run: tests/test_marshal_lease.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
trap 'rm -rf "$T" "$HERMETIC"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
S=$QARGI_STATE
mkdir -p "$HOME" "$T/c/projects" "$T/shm" "$T/scratch"
cd "$T" || exit 1   # a lead's directory: below a run directory (this test may itself run in a member's clone) the marshal is read only
R=$T/app; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
rec() { echo "$S/features/app-$1.json"; }
j() { jq -r "$2" "$(rec "$1")"; }
out() { cat "$T/o" "$T/e"; }
at() { local now=$1; shift; QARGI_MARSHAL_NOW=$now "$@" >"$T/o" 2>"$T/e"; }   # at NOW CMD...: the clock injected, output in $T/o and $T/e
iso() { date -u -d "@$1" +%Y-%m-%dT%H:%M:%SZ; }
commit_on() { local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"; echo "$1" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "$1 $2"; git -C "$R" worktree remove --force "$w"; }
mkfeat() { git -C "$R" branch "feature/$1" develop; commit_on "feature/$1" "$1.txt"; QARGI_MARSHAL_NOW=$t0 "$DA" marshal claim "$1" --as alice >/dev/null 2>&1; }
t0=1000000; LATE=$((t0 + 1500))   # 25 minutes: the 15 minute lease has lapsed
export QARGI_LEAD=alice

# --- every verb of the lead that asks the marshal renews a lapsed lease of its own
mkfeat l1
[ "$(j l1 .renewed_at)" = "$(iso $t0)" ] && ok "setup: claimed at t0" || no "setup: $(cat "$(rec l1)")"
at $((t0 + 60)) $F status l1
[ "$(j l1 .renewed_at)" = "$(iso $t0)" ] && [ "$(j l1 .rev)" = 1 ] && ok "status: within a third of the lease nothing is written" || no "SPEC throttle: $(cat "$(rec l1)")"
at $LATE $F status l1; rc=$?
[ $rc = 0 ] && [ "$(j l1 .renewed_at)" = "$(iso $LATE)" ] && ok "feature status by the lead renews a lapsed lease" || no "SPEC status renews: rc=$rc $(out) $(cat "$(rec l1)")"
QARGI_LEAD=bob at $((LATE + 600)) "$DA" marshal check l1; rc=$?
[ $rc = 1 ] && grep -q "is led by alice" "$T/e" && ok "after the renewal another identity is refused (the lead is live)" || no "SPEC refusal after renewal: rc=$rc $(out)"

git -C "$R" branch agent/t1 develop; commit_on agent/t1 t1.txt
now=$LATE
for step in "merge l1 agent/t1" "sync l1" "verify l1"; do
  now=$((now + 4000))   # each verb meets a lease that lapsed since the last renewal
  # shellcheck disable=SC2086  # the words of a verb
  at $now $F $step; rc=$?
  [ $rc = 0 ] && [ "$(j l1 .renewed_at)" = "$(iso $now)" ] && ok "feature $step by the lead renews a lapsed lease" || no "SPEC $step renews: rc=$rc $(out) $(j l1 .renewed_at)"
  [ "$step" != "merge l1 agent/t1" ] || commit_on develop "d$now.txt"
done

# a stranger renews nothing and is only warned
mkfeat l2
QARGI_LEAD=bob at $LATE "$DA" marshal check l2; rc=$?
[ $rc = 0 ] && [ "$(j l2 .renewed_at)" = "$(iso $t0)" ] && [ "$(j l2 .lead.id)" = alice ] && grep -qi "stale" "$T/e" && ok "a stranger's check renews nothing and still says the lead is stale" || no "SPEC stranger: rc=$rc $(out) $(cat "$(rec l2)")"
at $LATE "$DA" marshal check l2; rc=$?
[ $rc = 0 ] && [ "$(j l2 .renewed_at)" = "$(iso $t0)" ] && ok "marshal check itself stays a read: it renews nothing" || no "SPEC check is a read: $(cat "$(rec l2)")"

# --- the runs: local verify, clean, review check and apply keep the lease of the feature the run is based on
mkfeat r1
prep() { QARGI_MARSHAL_NOW=$1 "$DA" local prepare --repo "$R" --base feature/r1 --slug "$2" --scratch "$T/scratch" >"$T/o" 2>"$T/e"; }
prep $((t0 + 10)) rt1; rc=$?
RUN=$(sed -n 's/^RUN=//p' "$T/o")
[ $rc = 0 ] && [ -d "$RUN" ] && ok "prepare: a run based on the feature" || no "prepare: rc=$rc $(out)"
printf '# Report\n\n## Findings\n\nnone\n' > "$RUN/out/report.md"
at $((t0 + 1000)) "$DA" review check "$RUN/out"; rc=$?
[ $rc = 0 ] && [ "$(j r1 .renewed_at)" = "$(iso $((t0 + 1000)))" ] && ok "review check on the run's output renews the lease" || no "SPEC review check renews: rc=$rc $(out) $(j r1 .renewed_at)"
at $((t0 + 2500)) "$DA" local verify "$RUN"; rc=$?
[ "$(j r1 .renewed_at)" = "$(iso $((t0 + 2500)))" ] && ok "local verify renews the lease (rc=$rc)" || no "SPEC local verify renews: rc=$rc $(out) $(j r1 .renewed_at)"
at $((t0 + 4000)) "$DA" review apply "$RUN"; rc=$?
[ "$(j r1 .renewed_at)" = "$(iso $((t0 + 4000)))" ] && ok "review apply renews the lease (rc=$rc: this run has no patches)" || no "SPEC review apply renews: rc=$rc $(out) $(j r1 .renewed_at)"
QARGI_LEAD=bob at $((t0 + 6000)) "$DA" local verify "$RUN"
[ "$(j r1 .renewed_at)" = "$(iso $((t0 + 4000)))" ] && ok "another identity's local verify renews nothing" || no "SPEC stranger verify: $(j r1 .renewed_at)"
at $((t0 + 7000)) "$DA" local clean "$RUN" --discard; rc=$?
[ $rc = 0 ] && [ "$(j r1 .renewed_at)" = "$(iso $((t0 + 7000)))" ] && ok "local clean renews the lease" || no "SPEC local clean renews: rc=$rc $(out) $(j r1 .renewed_at)"

# --- release: after feature finish it is quiet; another live lead's feature is still refused
mkfeat f1
at $((t0 + 100)) $F verify f1 >/dev/null 2>&1
at $LATE $F finish f1
tokn=$(sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' "$T/o")
at $((LATE + 1)) $F finish f1 --plan "$tokn" --approved "go ahead"; rc=$?
[ $rc = 0 ] && [ "$(j f1 .status)" = finished ] && ok "finish by a lead whose lease lapsed during the run" || no "finish: rc=$rc $(out)"
at $((LATE + 2)) "$DA" marshal release f1 --note "done"; rc=$?
[ $rc = 0 ] && [ "$(wc -l < "$T/o")" = 1 ] && grep -q "nothing to release" "$T/o" && [ ! -s "$T/e" ] && ok "release after finish: one quiet line, exit 0" || no "SPEC release after finish: rc=$rc $(out)"
at $((LATE + 3)) "$DA" marshal release f1; rc=$?
[ $rc = 0 ] && grep -q "nothing to release" "$T/o" && ok "release after finish needs no note" || no "SPEC release after finish without note: rc=$rc $(out)"
at $((LATE + 4)) "$DA" marshal release never-existed --note n; rc=$?
[ $rc = 0 ] && grep -q "nothing to release" "$T/o" && ok "release of a name with no record and no branch: nothing to release" || no "SPEC release unknown: rc=$rc $(out)"
mkfeat h1
QARGI_LEAD=bob at $((t0 + 100)) "$DA" marshal release h1 --note n; rc=$?
[ $rc = 1 ] && [ "$(j h1 .lead.id)" = alice ] && ok "release of a feature another live lead holds is still refused" || no "SPEC release by non-lead: rc=$rc $(out)"
at $((t0 + 100)) "$DA" marshal release h1 --note "left off"; rc=$?
[ $rc = 0 ] && [ "$(j h1 .status)" = released ] && grep -q "^released h1" "$T/o" && ok "release by the lead: released as before" || no "release by the lead: rc=$rc $(out)"
at $((t0 + 101)) "$DA" marshal release h1 --note again; rc=$?
[ $rc = 0 ] && grep -q "nothing to release" "$T/o" && ok "release of a released feature: nothing to release" || no "release twice: rc=$rc $(out)"
git -C "$R" branch feature/u1 develop
at $t0 "$DA" marshal release u1 --note n; rc=$?
[ $rc = 1 ] && grep -q "no record for feature u1" "$T/e" && ok "release of a feature with a branch and no record is still refused" || no "SPEC release unclaimed: rc=$rc $(out)"

[ "$fail" = 0 ] && echo "marshal lease: all passed" || echo "marshal lease: FAILED"
exit "$fail"
