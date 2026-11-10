#!/usr/bin/env bash
# The wiring of the git-flow verbs (qargi feature, qargi local prepare) to the feature marshal.
# Written from the SPEC of the wiring, not from its code. Fixtures and conventions follow tests/test_marshal.sh (identity from
# QARGI_LEAD) and tests/test_flow.sh (a project with a bare origin and a fake gh). The leases are real (the default ttl is 15
# minutes, so no lead goes stale during the run); only the verify tests take real time (a suite of about 3 seconds with
# QARGI_MARSHAL_RENEW_SEC=1 and marshal.lease_minutes 1 minute).
# Run: tests/test_marshal_flow.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi; TOOL=$PWD
trap 'jobs -p | xargs -r kill 2>/dev/null; rm -rf "$T" "$HERMETIC"' EXIT
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T/shm GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
S=$QARGI_STATE
mkdir -p "$HOME" "$T/c/projects" "$T/bin" "$T/shm" "$T/scratch"
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr checks"*) true;; *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
chmod +x "$T/bin/gh"; export PATH=$T/bin:$PATH
R=$T/app; git init -q -b master "$R"; git init -q --bare "$T/origin.git"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"
rec() { echo "$S/features/app-$1.json"; }
j() { jq -r "$2" "$(rec "$1")"; }            # j NAME FILTER
run() { "$@" >"$T/o" 2>"$T/e"; }             # run CMD...: stdout and stderr in $T/o and $T/e, the status returned
tip() { git -C "$R" rev-parse "$1"; }
commit_on() { # BRANCH FILE: one commit on BRANCH (in a temporary worktree)
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"
  echo "$1" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "$1 $2"; git -C "$R" worktree remove --force "$w"
}
task() { git -C "$R" branch "agent/$1" develop; commit_on "agent/$1" "$1.txt"; }   # a task branch with one commit
mkfeat() { # NAME LEAD: branch feature/NAME and, for a LEAD, a record led by it, made with the marshal itself (not by the verbs under test)
  git -C "$R" branch "feature/$1" develop
  if [ -n "$2" ]; then "$DA" marshal claim "$1" --as "$2" >/dev/null 2>&1; fi
}
ttl() { jq --argjson n "$1" '.marshal.lease_minutes = $n' "$T/c/projects/app.json" > "$T/c/p.tmp" && mv "$T/c/p.tmp" "$T/c/projects/app.json"; }
tc() { jq --arg c "$1" '.test_command = $c' "$T/c/projects/app.json" > "$T/c/p.tmp" && mv "$T/c/p.tmp" "$T/c/projects/app.json"; }

# --- start: the first wiring assertion (the record the marshal keeps appears with the branch)
export QARGI_LEAD=alice
run $F start w1 --purpose "wire the thing"; rc=$?
if [ $rc != 0 ]; then no "SPEC start: feature start must still succeed (rc=$rc): $(out)"; exit 1; fi
if ! jq -e '.lead.id' "$(rec w1)" >/dev/null 2>&1; then no "SPEC start: feature start w1 must make the starter (QARGI_LEAD=alice) the lead in the marshal record $(rec w1): $(cat "$(rec w1)" 2>&1)"; echo "stopping: the wiring is absent"; exit 1; fi
[ "$(j w1 .purpose)" = "wire the thing" ] && [ -n "$(j w1 .started)" ] && [ "$(j w1 .started)" != null ] && ok "start: the record holds the purpose and started" || no "SPEC start record: $(cat "$(rec w1)")"
[ "$(j w1 .lead.id)" = alice ] && [ "$(j w1 .status)" = active ] && ok "start: the starter (QARGI_LEAD) is the lead, status active" || no "SPEC start lead: $(cat "$(rec w1)")"
git -C "$R" rev-parse -q --verify feature/w1 >/dev/null && ok "start: the branch exists too" || no "start: no branch"

# --- merge and sync: only the live lead moves the branch
task t1; task t2; task t3; task t4
mkfeat m1 alice
b0=$(tip feature/m1)
QARGI_LEAD=bob run $F merge m1 agent/t1; rc=$?
[ $rc = 1 ] && grep -q alice <(out) && ok "merge: another identity while the lead is LIVE exits 1 and names the lead" || no "SPEC merge by non-lead: rc=$rc $(out)"
[ "$(tip feature/m1)" = "$b0" ] && ok "merge: and the branch did not move" || no "SPEC merge by non-lead moved the branch"
run $F merge m1 agent/t1; rc=$?
[ $rc = 0 ] && [ "$(tip feature/m1)" != "$b0" ] && ok "merge: the lead merges" || no "merge by the lead: rc=$rc $(out)"
commit_on develop dev1.txt
b1=$(tip feature/m1)
QARGI_LEAD=bob run $F sync m1; rc=$?
[ $rc = 1 ] && grep -q alice <(out) && [ "$(tip feature/m1)" = "$b1" ] && ok "sync: another identity while the lead is LIVE exits 1, names the lead, moves nothing" || no "SPEC sync by non-lead: rc=$rc $(out)"
run $F sync m1; rc=$?
[ $rc = 0 ] && [ "$(tip feature/m1)" != "$b1" ] && ok "sync: the lead syncs" || no "sync by the lead: rc=$rc $(out)"
# an unled record, and a feature without any record (started before the marshal)
mkfeat m2 alice; "$DA" marshal release m2 --as alice --note n >/dev/null 2>&1
QARGI_LEAD=bob run $F merge m2 agent/t2; rc=$?
[ $rc = 0 ] && grep -qi "no lead" "$T/e" && ok "merge: an unled feature merges, with 'no lead' on stderr" || no "SPEC merge, unled: rc=$rc $(out)"
mkfeat m3 ""
b3=$(tip feature/m3); QARGI_LEAD=bob run $F merge m3 agent/t3; rc=$?
[ $rc = 0 ] && [ "$(tip feature/m3)" != "$b3" ] && grep -qi "no lead" "$T/e" && ok "merge: a feature without a record merges, with 'no lead' on stderr" || no "SPEC merge, no record: rc=$rc $(out)"
commit_on develop dev2.txt
QARGI_LEAD=bob run $F sync m3; rc=$?
[ $rc = 0 ] && grep -qi "no lead" "$T/e" && ok "sync: a feature without a lead syncs, with 'no lead' on stderr" || no "SPEC sync, no lead: rc=$rc $(out)"
# the anonymous identity (QARGI_LEAD unset) leads what it started, and only ever warns
unset QARGI_LEAD
run $F start anon1; rc=$?
[ $rc = 0 ] && ok "anonymous: start succeeds" || no "anonymous start: rc=$rc $(out)"
run $F merge anon1 agent/t4; rc=$?
[ $rc = 0 ] && grep -qi anonymous "$T/e" && ok "anonymous: merge succeeds and warns about the identity" || no "SPEC anonymous merge: rc=$rc $(out)"
export QARGI_LEAD=alice

# --- status and list show the marshal's view
run $F status w1; rc=$?
grep -q '^  lead: alice' "$T/o" && grep -q '^feature w1 of app$' "$T/o" && ok "status: the output ends with the marshal's view (lead: alice)" || no "SPEC status: rc=$rc $(cat "$T/o")"
run $F list
grep -q 'feature/w1: .*\[lead alice\]' "$T/o" && ok "list: a led feature shows [lead alice]" || no "SPEC list lead: $(cat "$T/o")"
grep -q 'feature/m3: .*\[lead none\]' "$T/o" && ok "list: a feature without a lead shows [lead none]" || no "SPEC list none: $(cat "$T/o")"

# --- verify: the lease is renewed while the suite runs, the renewer is gone afterwards
ttl 1; export QARGI_MARSHAL_RENEW_SEC=1
V1=v1p$$ V2=v2p$$   # unique per test process: the pgrep below must not match a parallel run
mkfeat $V1 alice; commit_on feature/$V1 $V1.txt
tc "sleep 3"
r0=$(j $V1 .renewed_at)
run $F verify $V1; rc=$?
r1=$(j $V1 .renewed_at)
[ $rc = 0 ] && ok "verify: the suite passes" || no "verify rc=$rc $(out)"
[ "$r0" != "$r1" ] && [ "$r1" != null ] && ok "verify: renewed_at advanced while the 3 s suite ran" || no "SPEC verify renews: renewed_at stayed $r0"
# hermetic: allow pgrep (the pattern holds $V1, unique to this process)
pgrep -f "feature verify $V1" >/dev/null && no "SPEC verify: a renewer of the run is still alive: $(pgrep -af "feature verify $V1")" || ok "verify: no renewer of the run remains"
run $F status $V1
grep -q "full suite: pass at this head" "$T/o" && ok "verify: the verified record exists (status reports it)" || no "verify record: $(out)"
mkfeat $V2 alice; commit_on feature/$V2 $V2.txt
tc "sleep 2; false"
r0=$(j $V2 .renewed_at)
run $F verify $V2; rc=$?
r1=$(j $V2 .renewed_at)
[ $rc = 1 ] && ok "verify: a failing suite fails the verb" || no "verify failing rc=$rc"
[ "$r0" != "$r1" ] && ok "verify: the lease was renewed during a suite that failed" || no "SPEC verify (failing) renews: renewed_at stayed $r0"
# hermetic: allow pgrep (the pattern holds $V2, unique to this process)
pgrep -f "feature verify $V2" >/dev/null && no "SPEC verify: a renewer remains after a failing suite: $(pgrep -af "feature verify $V2")" || ok "verify: a failing suite stops the renewer"
# refused: another LIVE lead holds the feature, the suite does not run
mkfeat v3 alice; commit_on feature/v3 v3.txt
tc "touch '$T/suite-ran'"
QARGI_LEAD=bob run $F verify v3; rc=$?
[ $rc = 1 ] && grep -q alice <(out) && [ ! -e "$T/suite-ran" ] && ok "verify: refused while another LIVE lead holds the feature; the suite did not run" || no "SPEC verify by non-lead: rc=$rc ran=$([ -e "$T/suite-ran" ] && echo yes || echo no) $(out)"
unset QARGI_MARSHAL_RENEW_SEC; tc true; ttl 15

# --- finish: the lead finishes, the record follows; a refused finish leaves it alone
mkfeat f1 alice; commit_on feature/f1 f1.txt
run $F finish f1; rc=$?
[ $rc != 0 ] && [ "$(j f1 .status)" = active ] && [ "$(j f1 .lead.id)" = alice ] && ok "finish: a refused finish (no whole-suite run) leaves the record active with the lead" || no "refused finish: rc=$rc $(cat "$(rec f1)")"
$F verify f1 >/dev/null 2>&1; t=$($F finish f1 2>/dev/null | tok)
QARGI_LEAD=bob run $F finish f1 --plan "$t" --approved go; rc=$?
[ $rc != 0 ] && [ "$(j f1 .status)" = active ] && git -C "$R" rev-parse -q --verify feature/f1 >/dev/null && ok "finish: another identity is refused and nothing is finished" || no "SPEC finish by non-lead: rc=$rc $(out)"
run $F finish f1 --plan "$t" --approved "go ahead"; rc=$?
[ $rc = 0 ] && ok "finish: the lead finishes" || no "finish by the lead: rc=$rc $(out)"
[ "$(j f1 .status)" = finished ] && [ "$(j f1 .lead)" = null ] && ok "finish: the record is finished and has no lead" || no "SPEC finish record: $(cat "$(rec f1)")"

# --- local prepare --base feature/N
mkfeat p1 alice; mkfeat p2 carol; "$DA" marshal release p2 --as carol --note n >/dev/null 2>&1
prep() { QARGI_LEAD=$1 "$DA" local prepare --repo "$R" --base "$2" --slug "$3" --scratch "$T/scratch" >"$T/o" 2>"$T/e"; }
nruns() { find "$T/scratch" -mindepth 1 -maxdepth 1 | wc -l; }
n0=$(nruns); prep bob feature/p1 pt1; rc=$?
[ $rc = 1 ] && grep -q alice <(out) && [ "$(nruns)" = "$n0" ] && ok "prepare: refused (exit 1) when another LIVE lead holds the feature; no RUN directory" || no "SPEC prepare by non-lead: rc=$rc runs $n0 -> $(nruns) $(out)"
prep alice feature/p1 pt2; rc=$?
[ $rc = 0 ] && [ "$(nruns)" = $((n0 + 1)) ] && ok "prepare: the lead may prepare" || no "prepare by the lead: rc=$rc $(out)"
[ "$(jq -r 'select(.slug == "pt2") | .lead' "$S/local-runs.jsonl" 2>/dev/null)" = alice ] && ok "prepare: local-runs.jsonl gains \"lead\":\"alice\"" || no "SPEC prepare lead field: $(cat "$S/local-runs.jsonl" 2>&1)"
prep bob feature/p2 pt3; rc=$?
[ $rc = 0 ] && grep -qi "no lead" "$T/e" && ok "prepare: an unled feature is allowed with a 'no lead' warning" || no "SPEC prepare, unled: rc=$rc $(out)"
prep bob develop pt4; rc=$?
[ $rc = 0 ] && ! grep -qiw "lead" "$T/e" && ok "prepare: --base develop is unaffected" || no "prepare develop: rc=$rc $(out)"

# --- a feature that does not exist is refused by the gate; start still makes a brand-new one; need_free says how to free a branch
run $F merge nosuch-$$ agent/t3; rc=$?
[ $rc = 1 ] && grep -q "qargi: no feature nosuch-$$ in app (no branch feature/nosuch-$$ and no record)" "$T/e" && ok "gate: a feature without branch and record is refused (exit 1, message shown)" || no "SPEC gate unknown feature: rc=$rc $(out)"
run $F start brandnew-$$; rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify "feature/brandnew-$$" >/dev/null && ok "start: a brand-new name still works" || no "SPEC start new name: rc=$rc $(out)"
mkfeat held1 alice; git -C "$R" worktree add -q "$T/held-wt" feature/held1
run $F merge held1 agent/t3; rc=$?
[ $rc != 0 ] && grep -q "checked out in $T/held-wt" "$T/e" && grep -q "checkout --detach" "$T/e" && ok "need_free: the message says how to free the branch (checkout --detach)" || no "SPEC need_free message: rc=$rc $(out)"
git -C "$R" worktree remove --force "$T/held-wt"

# --- a marshal that is missing or fails is never a reason to stop a verb
cp_tree() { rm -rf "$1"; copy_tool "$TOOL" "$1"; }
for kind in absent exit2; do
  cp_tree "$T/tree-$kind"
  if [ $kind = absent ]; then rm -f "$T/tree-$kind/lib/marshal.sh"
  else
    cat > "$T/tree-$kind/lib/marshal.sh" <<'EOS'
marshal_start() { return 2; }; marshal_check() { return 2; }; marshal_finish() { return 2; }; marshal_hold_start() { return 2; }; marshal_hold_stop() { return 2; }
if [ "${BASH_SOURCE[0]}" = "$0" ]; then exit 2; fi
EOS
  fi
  B=$T/tree-$kind/bin/qargi
  run "$B" feature start br-$kind; rc=$?
  [ $rc = 0 ] && git -C "$R" rev-parse -q --verify "feature/br-$kind" >/dev/null && ok "marshal $kind: feature start still works" || no "SPEC marshal $kind: start rc=$rc $(out)"
  [ -s "$T/e" ] && ok "marshal $kind: and warns on stderr" || no "SPEC marshal $kind: no warning for a marshal that failed"
  task br-$kind; b=$(tip "feature/br-$kind")
  run "$B" feature merge br-$kind agent/br-$kind; rc=$?
  [ $rc = 0 ] && [ "$(tip "feature/br-$kind")" != "$b" ] && ok "marshal $kind: feature merge still works" || no "SPEC marshal $kind: merge rc=$rc $(out)"
done

# --- the shared marshal cannot be asked: the flow verbs refuse (exit 3, nothing changes) unless --assume-unreachable-ok, which is audited
GONE=$T/gone.git; AUD=$S/audit.log
break_origin() { git -C "$R" remote set-url origin "$GONE"; }
mend_origin() { git -C "$R" remote set-url origin "$T/origin.git"; }
export QARGI_REMOTE_TIMEOUT=2
task un1; task un2; task un3
# a project whose marshal is local never asks the remote: an unreachable origin changes nothing for it, the flag is accepted and nothing is audited
mkfeat un0 alice; break_origin
a0=$(wc -l < "$AUD"); b=$(tip feature/un0)
run $F merge un0 agent/un1; rc=$?
[ $rc = 0 ] && [ "$(tip feature/un0)" != "$b" ] && ! grep -qi "marshal could not be asked\|marshal.*remote not checked" "$T/e" && ok "local marshal: an unreachable origin does not matter to feature merge (exit 0, no warning)" || no "local marshal with a broken origin: rc=$rc $(out)"
b=$(tip feature/un0)
run $F merge un0 agent/un2 --assume-unreachable-ok; rc=$?
[ $rc = 0 ] && [ "$(tip feature/un0)" != "$b" ] && ! tail -n +"$((a0 + 1))" "$AUD" | grep -q unreachable-ok && ok "local marshal: the flag is accepted and writes no audit line" || no "local marshal with the flag: rc=$rc $(out)"
mend_origin
# switch the project to the shared refs backend the way the owner does, claim with the origin reachable, then lose the origin
WORDS="the shared refs are fine for this project"
run "$DA" marshal enable; tk=$(tokof)
run "$DA" marshal enable --plan "$tk" --approved "$WORDS"; rc=$?
[ $rc = 0 ] && ok "shared marshal: enabled for the test" || no "marshal enable: rc=$rc $(out)"
mkfeat un7 alice; commit_on develop un7-dev.txt
break_origin
b=$(tip feature/un7); a1=$(wc -l < "$AUD")
run $F merge un7 agent/un3; rc=$?
[ $rc = 3 ] && [ "$(tip feature/un7)" = "$b" ] && grep -q "could not be reached" <(out) && grep -q -- "--assume-unreachable-ok" "$T/e" && grep -q "feature merge un7 is refused" "$T/e" \
  && ok "unreachable: feature merge is refused (exit 3), names what could not be reached and the flag, and the branch did not move" || no "SPEC unreachable merge: rc=$rc $(out)"
run $F sync un7; rc=$?
[ $rc = 3 ] && [ "$(tip feature/un7)" = "$b" ] && grep -q -- "--assume-unreachable-ok" "$T/e" && ok "unreachable: feature sync is refused too" || no "SPEC unreachable sync: rc=$rc $(out)"
tc "touch '$T/suite-ran2'"
run $F verify un7; rc=$?
[ $rc = 3 ] && [ ! -e "$T/suite-ran2" ] && grep -q -- "--assume-unreachable-ok" "$T/e" && ok "unreachable: feature verify is refused and the suite did not run" || no "SPEC unreachable verify: rc=$rc $(out)"
run $F finish un7; rc=$?
[ $rc = 3 ] && grep -q -- "--assume-unreachable-ok" "$T/e" && ok "unreachable: feature finish is refused" || no "SPEC unreachable finish: rc=$rc $(out)"
[ "$(wc -l < "$AUD")" = "$a1" ] && ok "unreachable: a refusal writes no audit line" || no "a refusal was audited: $(tail -n +"$((a1 + 1))" "$AUD")"
run $F list; rc=$?
[ $rc = 0 ] && ok "unreachable: a read (feature list) is not refused" || no "feature list with an unreachable marshal: rc=$rc $(out)"
run $F status un7 --assume-unreachable-ok; rc=$?
[ $rc != 0 ] && grep -q -- "--assume-unreachable-ok belongs to" "$T/e" && ok "the flag is refused where no marshal is asked first (feature status)" || no "flag on status: rc=$rc $(out)"
run $F merge un7 agent/un3 --assume-unreachable-ok; rc=$?
[ $rc = 0 ] && [ "$(tip feature/un7)" != "$b" ] && ok "--assume-unreachable-ok: feature merge goes on" || no "merge with the flag: rc=$rc $(out)"
tail -n +"$((a1 + 1))" "$AUD" | grep -q '"verb":"marshal:unreachable-ok"' && tail -n +"$((a1 + 1))" "$AUD" | grep -q "app un7 verb=check remote=origin" \
  && ok "--assume-unreachable-ok: the audit log has marshal:unreachable-ok (project, feature, verb, remote)" || no "SPEC audit line of the flow verb: $(tail -n +"$((a1 + 1))" "$AUD")"
b=$(tip feature/un7)
run $F sync un7 --assume-unreachable-ok; rc=$?
[ $rc = 0 ] && [ "$(tip feature/un7)" != "$b" ] && ok "--assume-unreachable-ok: feature sync goes on" || no "sync with the flag: rc=$rc $(out)"
mend_origin; unset QARGI_REMOTE_TIMEOUT

[ "$fail" = 0 ] && echo "marshal flow: all passed" || echo "marshal flow: FAILED"
exit "$fail"
