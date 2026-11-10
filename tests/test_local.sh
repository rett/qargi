#!/usr/bin/env bash
# The local never-push barrier on a throwaway repository and remote. Run: tests/test_local.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT; fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
git init -q -b main "$T/r" && git -C "$T/r" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git init -q --bare "$T/remote.git" && git -C "$T/r" remote add origin "$T/remote.git" && git -C "$T/r" push -q origin main
# a read-only role (or a profile) is looked up through the repository's project, and its models.provider (there is no default provider)
mkdir -p "$T/c/projects"
jq -n --arg p "$T/r" '{schema:1,project:"rproj",repo:{url:"https://github.com/example/rproj",path:$p,long_lived:["main"]},roles:{build:{base:"main",push:{mode:"none"}}},models:{provider:{local:"claude-code",cloud:"claude-platform"}},memory:{},budget_cents:500}' > "$T/c/projects/rproj.json"
eval "$(./bin/qargi local prepare --repo "$T/r" --base main --slug demo --scratch "$T" | sed '/^$/,$d' | sed 's/^/export /')"
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
[ "$($GIT -C "$CLONE" branch --show-current)" = agent/demo ] && ok "clone is on agent/demo" || no "branch"
echo x > "$CLONE/f"; $GIT -C "$CLONE" add f && $GIT -C "$CLONE" commit -q -m work && ok "commit through the wrapper"
[ "$($GIT -C "$CLONE" log -1 --format=%an)" = qargi ] && ok "author is qargi" || no "author"
$GIT -C "$CLONE" push origin agent/demo >/dev/null 2>&1 && no "git push origin succeeded" || ok "git push origin fails"
git -C "$CLONE" remote -v | grep -q "$T/r" && no "the clone knows the real repository" || ok "the clone does not know the real repository path"
out=$(./bin/qargi local verify "$RUN" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "OUT is empty: the member did not collect" <<<"$out" && ok "verify fails first when the clone has commits and OUT holds neither patches nor a report" || no "verify of an uncollected run (rc=$rc): $out"
echo "# report" > "$RUN/out/report.md"
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && ok "verify passes after a clean run" || no "verify clean"
[ "$(cat "$RUN/ability")" = build ] && ok "the run records its ability (build by default)" || no "ability file"
R2=$(./bin/qargi local prepare --repo "$T/r" --base main --slug rev --scratch "$T" --role review | sed -n '1,/^$/s/^RUN=//p')
[ "$(cat "$R2/ability")" = review ] && ok "--role review is recorded for the guard" || no "review ability"
./bin/qargi local prepare --repo "$T/r" --base main --slug bad --scratch "$T" --role deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
out=$(./bin/qargi local prepare --repo "$T/r" --base main --slug old --scratch "$T" --ability review 2>&1); rc=$?
[ $rc != 0 ] && grep -q "unknown option --ability" <<<"$out" && ok "--ability is gone: an unknown option" || no "--ability still accepted: $out"
git -C "$CLONE" push -q "$T/remote.git" agent/demo 2>/dev/null   # a bypass with plain git
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && no "verify missed a push to the remote" || ok "verify catches a push to the remote"
[ "$(jq -r 'select(.slug=="demo") | .run' "$T/s/local-runs.jsonl")" = "$RUN" ] && [ "$(wc -l < "$T/s/local-runs.jsonl")" = 2 ] && ok "prepare registers each run (one line, run directory, slug, ability, base, start)" || no "registry: $(cat "$T/s/local-runs.jsonl")"
grep -qiE '(^|[^[:alnum:]])token([^[:alnum:]]|$)|secret' "$T/s/local-runs.jsonl" && no "the registry holds a secret" || ok "the registry holds a repository path and no token"
[ "$(jq -r 'select(.slug=="demo") | .tmpdir' "$T/s/local-runs.jsonl")" = "$TMP" ] && [ "$(jq -r 'select(.slug=="demo") | .slug' "$T/s/local-runs.jsonl")" = demo ] \
  && ok "the registry names each run's temporary directory (and its slug): the lead's record of what clean removes" || no "registry tmpdir: $(cat "$T/s/local-runs.jsonl")"
# a submodule the role declares (roles.build.tools, kind submodule) is checked out in the clone from the lead's copy, offline, push disabled
git init -q -b main "$T/sub" && git -C "$T/sub" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git -C "$T/r" -c protocol.file.allow=always submodule add -q "$T/sub" vendor/acme-test && git -C "$T/r" -c user.name=t -c user.email=t@example.net commit -qm sub
git -C "$T/sub" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m two; SUBSHA=$(git -C "$T/sub" rev-parse HEAD)
git -C "$T/r/vendor/acme-test" fetch -q origin && git -C "$T/r/vendor/acme-test" checkout -q "$SUBSHA" && git -C "$T/r" add vendor/acme-test && git -C "$T/r" -c user.name=t -c user.email=t@example.net commit -qm bump
cp "$T/c/projects/rproj.json" "$T/rproj.bak"; jq '.roles.build.tools=[{kind:"submodule",name:"acme-test",path:"vendor/acme-test"}]' "$T/rproj.bak" > "$T/c/projects/rproj.json"
out=$(./bin/qargi local prepare --repo "$T/r" --base main --slug sub1 --scratch "$T" 2>"$T/sub1.err"); S1=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
grep -q '^SUBMODULES=vendor/acme-test$' <<<"$out" && ok "prepare prints SUBMODULES=path for a declared submodule it checked out" || no "SUBMODULES line: $out"
[ "$(git -C "$S1/clone/vendor/acme-test" rev-parse HEAD 2>/dev/null)" = "$SUBSHA" ] && ok "the clone has the submodule at the commit HEAD records (fetched by nobody: the lead's copy)" || no "submodule checkout: $(cat "$T/sub1.err")"
[ "$(git -C "$S1/clone/vendor/acme-test" remote get-url --push origin)" = DISABLED ] && ok "the submodule's push URL is disabled" || no "submodule push url"
case $(git -C "$S1/clone/vendor/acme-test" remote get-url origin) in "$S1"/sub/*) ok "its origin is the run's own copy, not the lead's repository";; *) no "submodule origin: $(git -C "$S1/clone/vendor/acme-test" remote get-url origin)";; esac
git clone -q "$T/r" "$T/rs2"   # a lead's checkout that never initialised the submodule: no objects of it on this host
jq --arg p "$T/rs2" '.project="rs2proj" | .repo.path=$p | .repo.url="https://github.com/example/rs2proj"' "$T/c/projects/rproj.json" > "$T/c/projects/rs2proj.json"
out=$(./bin/qargi local prepare --repo "$T/rs2" --base main --slug sub2 --scratch "$T" 2>"$T/sub2.err"); S2=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
[ -n "$S2" ] && ! grep -q '^SUBMODULES=' <<<"$out" && grep -q 'qargi: note: submodule vendor/acme-test is not initialised in' "$T/sub2.err" && grep -q 'nothing is fetched' "$T/sub2.err" \
  && ok "a submodule whose objects are not on this host is a note, nothing is fetched and the run is still made" || no "unavailable submodule: $out $(cat "$T/sub2.err")"
[ ! -e "$S2/clone/vendor/acme-test/.git" ] && ok "and the clone's submodule is left alone" || no "submodule fetched"
rm -rf "$S1" "$S2" "$T/c/projects/rs2proj.json"; mv "$T/rproj.bak" "$T/c/projects/rproj.json"; sed -i '/"slug":"sub[12]"/d' "$T/s/local-runs.jsonl"
# clean: a collected, verified run goes away with its temporary directory; anything else is refused
git init -q -b main "$T/r2" && git -C "$T/r2" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c1 --scratch "$T"); C1=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); TM=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out")
[ -d "$TM" ] && [ "$(cat "$C1/tmpdir")" = "$TM" ] && ok "prepare makes a private temporary directory and prints it as TMP" || no "TMP: $out"
case $TM in "$T"/qargi-run.*) ok "it is under QARGI_RUN_TMP (tmpfs by default)";; "$C1"/tmp) ok "it is inside the run when there is no tmpfs";; *) no "TMP place $TM";; esac
touch "$TM/sandbox-file"; mkdir -p "$TM/a/b"
./bin/qargi local clean "$C1" >/dev/null 2>&1 && no "clean removed a run with no manifest" || ok "clean refuses a run whose output has no manifest"
[ -d "$C1" ] && [ -d "$TM" ] && ok "and removes nothing" || no "refused clean removed things"
echo '{}' > "$C1/out/manifest.json"
git -C "$T/r2" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m moved
./bin/qargi local clean "$C1" >/dev/null 2>&1 && no "clean removed a run whose refs changed" || ok "clean refuses when the repository's refs changed (evidence)"
[ -d "$C1" ] && ok "the evidence stays" || no "evidence removed"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c2 --scratch "$T"); C2=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); TM2=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out")
echo '{}' > "$C2/out/p--manifest.json"; touch "$TM2/leftover"
./bin/qargi local clean "$C2" >/dev/null 2>&1 && [ ! -e "$C2" ] && [ ! -e "$TM2" ] && ok "clean removes the run and its temporary directory" || no "clean: $C2 $TM2"
[ -d "$TM" ] && ok "another run's temporary directory is untouched" || no "touched another run's tmp"
# the registry (one line per run) records the clean: the line stays, marked cleaned, so a cleaned run is never listed as an open task
regline() { jq -c --arg r "$1" 'select(.run == $r)' "$T/s/local-runs.jsonl"; }
[ "$(regline "$C2" | wc -l)" = 1 ] && [ -n "$(regline "$C2" | jq -r '.cleaned // ""')" ] && [ "$(regline "$C2" | jq -r '.verified // ""')" != "" ] \
  && ok "clean marks the run's registry line cleaned (and the verify it ran, verified), still one line per run" || no "registry after clean: $(regline "$C2")"
[ "$(stat -c %a "$T/s/local-runs.jsonl")" = 600 ] && ok "the registry keeps mode 600 after the mark" || no "registry mode $(stat -c %a "$T/s/local-runs.jsonl")"
[ -z "$(regline "$C1" | jq -r '.cleaned // ""')" ] && ok "a run clean refused is not marked cleaned" || no "refused clean marked: $(regline "$C1")"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c3 --scratch "$T"); C3=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
./bin/qargi local clean "$C3" --discard >/dev/null 2>&1 && [ ! -e "$C3" ] && ok "--discard cleans a run that produced no manifest" || no "discard"
[ -n "$(regline "$C3" | jq -r '.cleaned // ""')" ] && ok "--discard marks the line cleaned too" || no "registry after discard: $(regline "$C3")"
./bin/qargi local clean "$T" >/dev/null 2>&1 && no "clean accepted a directory that is not a run" || ok "clean refuses a directory that prepare did not make"
# clean never drops finished work that is not merged: a run whose clone holds commits needs them applied and merged first
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c4 --scratch "$T"); C4=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); G4=$(sed -n '1,/^$/s/^GIT=//p' <<<"$out"); CL4=$(sed -n '1,/^$/s/^CLONE=//p' <<<"$out")
echo y > "$CL4/g"; $G4 -C "$CL4" add g && $G4 -C "$CL4" commit -q -m work; echo '{}' > "$C4/out/manifest.json"; echo r > "$C4/out/report.md"
./bin/qargi local verify "$C4" >/dev/null 2>&1
./bin/qargi local clean "$C4" >/dev/null 2>&1 && no "clean removed a run with commits that were never applied" || ok "clean refuses a run whose commits were never applied"
[ -d "$C4" ] && ok "and the finished work stays" || no "unapplied work was removed"
TREE=$(git -C "$T/r2" rev-parse 'main^{tree}'); AT=$(git -C "$T/r2" -c user.name=t -c user.email=t@example.net commit-tree -p main -m work "$TREE")
git -C "$T/r2" update-ref refs/heads/agent/c4 "$AT"; printf 'agent/c4 %s now\n' "$AT" > "$C4/applied"
./bin/qargi local clean "$C4" >/dev/null 2>&1 && no "clean removed an applied but unmerged run" || ok "clean refuses a run applied to agent/c4 but not merged into another branch"
git -C "$T/r2" update-ref refs/heads/feature/x "$AT"
./bin/qargi local clean "$C4" >/dev/null 2>&1 && [ ! -e "$C4" ] && ok "clean removes it once the applied tip is on another branch" || no "clean after merge"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c5 --scratch "$T"); C5=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); G5=$(sed -n '1,/^$/s/^GIT=//p' <<<"$out"); CL5=$(sed -n '1,/^$/s/^CLONE=//p' <<<"$out")
echo z > "$CL5/h"; $G5 -C "$CL5" add h && $G5 -C "$CL5" commit -q -m work; echo '{}' > "$C5/out/manifest.json"; echo r > "$C5/out/report.md"; ./bin/qargi local verify "$C5" >/dev/null 2>&1
err=$(./bin/qargi local clean "$C5" --discard 2>&1) && [ ! -e "$C5" ] && grep -q 'dropped 1 unmerged commit' <<<"$err" && ok "--discard drops it on purpose and says how many commits" || no "discard: $err"
# an option that goes with another verb form is a usage error (exit 2), not a failure of the clean
for bad in "--yes" "--scratch $T/ls"; do
  # shellcheck disable=SC2086
  out=$(./bin/qargi local clean "$T/nosuch.run" $bad 2>&1); rcu=$?
  { [ $rcu = 2 ] && grep -q 'is for --' <<<"$out"; } && ok "clean RUN $bad is a usage error (exit 2)" || no "clean RUN $bad (rc=$rcu): $out"
done
# a run whose review apply is under way is not cleaned: the apply holds a pid lock (STATE/apply/RUN-ID.json.run: the pid and its start time), and clean refuses, --discard
# or not, while that process lives; a lock whose process is gone, or whose pid another process now has, does not block
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug lk --scratch "$T"); CLK=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); echo '{}' > "$CLK/out/manifest.json"
LKD=$T/s/apply/$(basename "$CLK").json.run; mkdir -p "$LKD"
sleep 300 & LKP=$!
LKS=$(cat "/proc/$LKP/stat"); read -ra LKA <<<"${LKS##*) }"; printf '%s %s\n' "$LKP" "${LKA[19]}" > "$LKD/pid"
out=$(./bin/qargi local clean "$CLK" 2>&1); rcl=$?; out2=$(./bin/qargi local clean "$CLK" --discard 2>&1); rcl2=$?
{ [ $rcl = 1 ] && [ $rcl2 = 1 ] && grep -q "a review apply of $CLK is running (process $LKP" <<<"$out" && grep -q 'is running' <<<"$out2" && [ -d "$CLK" ] && [ -d "$LKD" ]; } \
  && ok "clean refuses a run whose review apply is running, --discard too, and removes nothing" || no "clean under a live apply lock (rc=$rcl/$rcl2): $out $out2"
printf '%s 1\n' "$LKP" > "$LKD/pid"
out=$(./bin/qargi local clean "$CLK" 2>&1); rcl=$?
{ [ $rcl = 0 ] && [ ! -e "$CLK" ] && [ ! -e "$LKD" ]; } && ok "a lock whose pid has another start time (the pid was reused) does not block clean, and clean removes the lock" || no "reused pid (rc=$rcl): $out"
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug lk2 --scratch "$T"); CLK=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); echo '{}' > "$CLK/out/manifest.json"
LKD=$T/s/apply/$(basename "$CLK").json.run; mkdir -p "$LKD"; kill "$LKP"; wait "$LKP" 2>/dev/null; printf '%s %s\n' "$LKP" "${LKA[19]}" > "$LKD/pid"
out=$(./bin/qargi local clean "$CLK" 2>&1); rcl=$?
{ [ $rcl = 0 ] && [ ! -e "$CLK" ] && [ ! -e "$LKD" ]; } && ok "a stale lock (its process is dead) does not block clean, and clean removes it" || no "stale apply lock (rc=$rcl): $out"
# lead-side moves: strict until a verify has passed, then fast-forwards and new branches are accepted
LC="git -c user.name=t -c user.email=t@example.net"
git init -q -b main "$T/r3" && $LC -C "$T/r3" commit -q --allow-empty -m one && git -C "$T/r3" branch develop && git -C "$T/r3" checkout -q develop
mk() { ./bin/qargi local prepare --repo "$T/r3" --base develop --slug "$1" --scratch "$T"; }
runof() { sed -n '1,/^$/s/^RUN=//p'; }
rc() { ./bin/qargi local verify "$1" >/dev/null 2>&1; echo $?; }
out=$(mk p1); P1=$(runof <<<"$out")
grep -q '^TASK-BLOCK PATHS$' <<<"$out" && ok "prepare prints the TASK-BLOCK PATHS block" || no "no block: $out"
blk=$(sed '1,/^TASK-BLOCK PATHS$/d' <<<"$out")
[ "$(sed -n 's/^RUN_DIR=//p' <<<"$blk")" = "$P1" ] && [ "$(sed -n 's/^CLONE=//p' <<<"$blk")" = "$P1/clone" ] && [ "$(sed -n 's/^OUT=//p' <<<"$blk")" = "$P1/out" ] \
  && [ "$(sed -n 's/^GIT=//p' <<<"$blk")" = "$P1/git" ] && [ "$(sed -n 's/^TMP=//p' <<<"$blk")" = "$(cat "$P1/tmpdir")" ] \
  && [ "$(sed -n 's/^BASE_SHA=//p' <<<"$blk")" = "$(git -C "$T/r3" rev-parse develop)" ] && ok "the block holds RUN_DIR, CLONE, OUT, TMP, GIT and BASE_SHA" || no "block: $blk"
CTD=$(sed -n 's/^CONTRACT=//p' <<<"$blk")
[ -n "$CTD" ] && [ "$CTD" = "$P1/contract" ] && cmp -s "$CTD/contract.md" contract/contract.md && cmp -s "$CTD/output-format.md" contract/output-format.md && cmp -s "$CTD/manifest.example.json" contract/manifest.example.json && [ "$(grep -c '^CONTRACT=' <<<"$blk")" = 1 ] \
  && ok "the block names the run's contract directory (CONTRACT=, a copy of contract.md, output-format.md and manifest.example.json)" || no "CONTRACT: '$CTD' in $blk"
grep -q "manifest.example.json beside this file" "$CTD/output-format.md" && ok "and the output format points at the example that sits beside it in the run" || no "the output format does not point at manifest.example.json"
top=$(sed '/^$/,$d' <<<"$out")
[ "$(sed -n 's/^CONTRACT=//p' <<<"$top")" = "$P1/contract" ] && ! grep -q '^ABILITY=' <<<"$top" \
  && ok "the eval-able block names CONTRACT too, and no longer prints the retired ABILITY alias" || no "eval block: $top"
[ "$(ls "$CTD")" = "$(printf 'contract.md\nmanifest.example.json\noutput-format.md')" ] && ok "a repository that is in no project gets no runtime addendum (no runtime is assumed)" || no "contract dir without a project: $(ls "$CTD")"
# a repository of a stored project: the contract directory also holds the addenda of the project's local runtime
out=$(./bin/qargi local prepare --repo "$T/r" --base main --slug adn --scratch "$T"); PA=$(runof <<<"$out")
CTA=$(sed -n 's/^CONTRACT=//p' <<<"$out" | tail -1)   # the paths block's (the first block names it too)
[ "$CTA" = "$PA/contract" ] && [ -s "$CTA/runtime-addenda.md" ] && [ "$(python3 -I lib/provider.py addenda claude-code local)" = "$(cat "$CTA/runtime-addenda.md")" ] && grep -q "run_in_background" "$CTA/runtime-addenda.md" \
  && ok "the contract directory of a Claude Code project holds the claude-code addenda (runtime-addenda.md)" || no "addenda: $(ls "$CTA") in $out"
./bin/qargi local clean "$PA" --discard >/dev/null 2>&1; [ ! -e "$PA" ] && ok "clean removes the run's copy of the contract with it" || no "clean left $PA"
$LC -C "$T/r3" commit -q --allow-empty -m lead-move && git -C "$T/r3" branch agent/other
[ "$(rc "$P1")" = 2 ] && ok "no passing verify yet: the strict comparison applies (exit 2)" || no "strict: a moved branch was accepted"
out=$(mk p2); P2=$(runof <<<"$out")
[ "$(rc "$P2")" = 0 ] && [ -f "$P2/verified" ] && ok "a passing verify records RUN/verified" || no "verified record"
[ "$(regline "$P2" | wc -l)" = 1 ] && [ -n "$(regline "$P2" | jq -r '.verified // ""')" ] && ok "a passing verify marks the run's registry line verified (one line per run)" || no "registry after verify: $(regline "$P2")"
[ -z "$(regline "$P1" | jq -r '.verified // ""')" ] && ok "a failing verify leaves the line unmarked" || no "registry after a failed verify: $(regline "$P1")"
$LC -C "$T/r3" commit -q --allow-empty -m lead-ff && git -C "$T/r3" branch feature/new && git -C "$T/r3" branch agent/new2
[ "$(rc "$P2")" = 0 ] && ok "after a passing verify, a fast-forward and new agent/feature branches are accepted" || no "ff refused"
git -C "$T/r3" branch stray
[ "$(rc "$P2")" = 2 ] && ok "a new branch outside the allowed namespaces fails with exit 2" || no "stray branch accepted"
git -C "$T/r3" branch -q -D stray
git -C "$T/r3" branch -q -D agent/new2
[ "$(rc "$P2")" = 2 ] && ok "a deleted branch fails" || no "deletion accepted"
git -C "$T/r3" branch agent/new2
[ "$(rc "$P2")" = 0 ] && ok "and passes again once restored" || no "restore"
old=$(git -C "$T/r3" rev-parse develop)
git -C "$T/r3" checkout -q --detach && git -C "$T/r3" branch -f develop "$(git -C "$T/r3" rev-parse develop~1)"
err=$(./bin/qargi local verify "$P2" 2>&1 >/dev/null); r=$?
[ $r = 2 ] && grep -q 'not a fast-forward' <<<"$err" && grep -q develop <<<"$err" && ok "a rewind of develop fails with exit 2 and the diff" || no "rewrite accepted: $r $err"
git -C "$T/r3" branch -f develop "$old"
git -C "$T/r3" checkout -q --detach "$old~1" && $LC -C "$T/r3" commit -q --allow-empty -m other-line && git -C "$T/r3" branch -f develop HEAD
[ "$(rc "$P2")" = 2 ] && ok "a non-ancestor develop is refused" || no "non-ancestor accepted"
git -C "$T/r3" branch -f develop "$old" && git -C "$T/r3" checkout -q develop
# clean after a lead merge
echo '{}' > "$P2/out/manifest.json"
./bin/qargi local clean "$P2" >/dev/null 2>&1 && [ ! -e "$P2" ] && ok "clean accepts lead-side fast-forwards after a passing verify" || no "clean after lead merge"
echo '{}' > "$P1/out/manifest.json"
./bin/qargi local clean "$P1" >/dev/null 2>&1 && no "clean accepted a moved branch with no passing verify" || ok "clean on a run with no passing verify stays strict"
# a remote change fails even after a passing verify
git -C "$T/r3" remote add origin "$T/remote.git"; out=$(mk p3); P3=$(runof <<<"$out")
[ "$(rc "$P3")" = 0 ] && ok "verify passes with a remote" || no "p3 verify"
git -C "$T/r3" fetch -q origin; out=$(./bin/qargi local verify "$P3" 2>&1); r=$?
[ $r = 0 ] && grep -q "origin/main created to what origin has" <<<"$out" && ok "a fetch (remote-tracking refs that say what origin has) is accepted and named" || no "fetch: $r $out"
git --git-dir="$T/remote.git" update-ref refs/heads/elsewhere "$(git --git-dir="$T/remote.git" rev-parse main)"
[ "$(rc "$P3")" = 2 ] && ok "a remote ref change fails with exit 2 after a passing verify" || no "remote change accepted"
git --git-dir="$T/remote.git" update-ref -d refs/heads/elsewhere
git -C "$T/r3" update-ref refs/remotes/origin/zz HEAD
[ "$(rc "$P3")" = 2 ] && ok "a refs/remotes change fails" || no "refs/remotes change accepted"
git -C "$T/r3" update-ref -d refs/remotes/origin/zz
# refs/qargi/ (the marshal refs backend, fetched and pushed by the lead's renewer during a run) is not an agent push; nothing else
# is relaxed: not another namespace that merely starts with the same letters, not a branch
HEAD3=$(git -C "$T/r3" rev-parse HEAD); RHEAD=$(git --git-dir="$T/remote.git" rev-parse main)
out=$(mk p4); P4=$(runof <<<"$out")
grep -q 'refs/qargi' "$P4/refs.before" && no "the snapshot lists refs/qargi/" || ok "the snapshot does not list refs/qargi/ ones"
git -C "$T/r3" update-ref refs/qargi/features/x "$HEAD3"; git --git-dir="$T/remote.git" update-ref refs/qargi/features/x "$RHEAD"
[ "$(rc "$P4")" = 0 ] && ok "refs/qargi/ refs created in the repository and in its remote during a run are not flagged (strict, before a passing verify)" || no "refs/qargi created flagged: $(cat "$P4/refs.diff")"
grep -q 'refs/qargi' "$P4/refs.after" && no "the after snapshot lists refs/qargi/" || ok "the snapshot taken by verify does not list refs/qargi/ either"
git -C "$T/r3" update-ref refs/qargi/features/x "$(git -C "$T/r3" rev-parse HEAD~1 2>/dev/null || echo "$HEAD3")"; git --git-dir="$T/remote.git" update-ref -d refs/qargi/features/x
git -C "$T/r3" update-ref refs/qargi/features/y "$HEAD3"
[ "$(rc "$P4")" = 0 ] && ok "and changing, adding or deleting them stays unflagged after a passing verify" || no "refs/qargi change flagged: $(cat "$P4/refs.diff")"
git -C "$T/r3" update-ref -d refs/qargi/features/x; git -C "$T/r3" update-ref -d refs/qargi/features/y
[ "$(rc "$P4")" = 0 ] && ok "deleting them is unflagged too" || no "refs/qargi deletion flagged"
printf 'local refs/qargi/features/old %s\n' "$HEAD3" >> "$P4/verified"; sort -o "$P4/verified" "$P4/verified"
[ "$(rc "$P4")" = 0 ] && ok "a refs/qargi/ line in an older snapshot is ignored" || no "old snapshot line flagged"
git -C "$T/r3" update-ref refs/qargi-x/features/x "$HEAD3"
[ "$(rc "$P4")" = 2 ] && ok "refs/qargi-x/ is still compared and fails" || no "refs/qargi-x accepted"
git -C "$T/r3" update-ref -d refs/qargi-x/features/x
git -C "$T/r3" branch stray2
[ "$(rc "$P4")" = 2 ] && ok "a branch outside the allowed namespaces still fails alongside refs/qargi/" || no "stray2 accepted"
git -C "$T/r3" branch -q -D stray2
out=$(mk p5); P5=$(runof <<<"$out")
git -C "$T/r3" update-ref refs/qargi/features/z "$HEAD3"; git -C "$T/r3" update-ref refs/heads/moved "$HEAD3"
[ "$(rc "$P5")" = 2 ] && ok "a new refs/heads ref still fails the strict comparison with refs/qargi/ present" || no "heads change accepted"
git -C "$T/r3" update-ref -d refs/heads/moved; git -C "$T/r3" update-ref -d refs/qargi/features/z
git -C "$T/r3" tag t-qargi "$HEAD3"
[ "$(rc "$P5")" = 2 ] && ok "a new tag still fails" || no "tag accepted"
git -C "$T/r3" tag -d t-qargi >/dev/null
# --discard drops a run whose refs changed (the evidence the plain clean keeps), says so, and still only touches what prepare made
mkdir "$T/qargi.zzzzzz"; touch "$T/qargi.zzzzzz/keep"
./bin/qargi local clean "$T/c" --discard >/dev/null 2>&1 && no "--discard cleaned a directory that is not a run" || ok "--discard still refuses a directory prepare did not make"
./bin/qargi local clean "$T/qargi.zzzzzz" --discard >/dev/null 2>&1 && no "--discard cleaned a lookalike directory" || ok "and one that is named like a run but has no refs.before"
[ -d "$T/c" ] && [ -f "$T/qargi.zzzzzz/keep" ] && ok "and removes nothing" || no "a refused --discard removed something"
rm -rf "$T/qargi.zzzzzz"
err=$(./bin/qargi local clean "$C1" --discard 2>&1 >/dev/null); rcd=$?
[ $rcd = 0 ] && [ ! -e "$C1" ] && [ ! -e "$TM" ] && grep -q 'warning: the refs of the repository changed' <<<"$err" && grep -q 'branch moved' <<<"$err" \
  && ok "--discard removes a run whose refs changed, with its temporary directory, and prints the verify outcome as a warning" || no "discard after changed refs (rc=$rcd): $err"
# a recorded temporary directory outside /dev/shm and QARGI_RUN_TMP is not removed
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c6 --scratch "$T"); C6=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); TM6=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out")
settmp() { # RUN PATH: make the registry say that PATH is RUN's temporary directory (what clean trusts)
  jq -c --arg r "$1" --arg t "$2" 'if .run == $r then .tmpdir = $t else . end' "$T/s/local-runs.jsonl" > "$T/s/lr.new" && mv "$T/s/lr.new" "$T/s/local-runs.jsonl"
}
mkdir -p "$T/elsewhere/qargi-run.abcdef"; touch "$T/elsewhere/qargi-run.abcdef/precious"; settmp "$C6" "$T/elsewhere/qargi-run.abcdef"
err=$(./bin/qargi local clean "$C6" --discard 2>&1 >/dev/null); [ ! -e "$C6" ] && [ -f "$T/elsewhere/qargi-run.abcdef/precious" ] && grep -q 'left .* alone' <<<"$err" \
  && ok "a recorded TMP that is not under QARGI_RUN_TMP or the shared tmpfs is left alone, with a note" || no "foreign tmpdir: $err"
rm -rf "$TM6" "$T/elsewhere"
# a recorded temporary directory is never followed: a link to another directory (also written with a trailing slash, which makes rm -rf empty what the
# link leads to), a link inside its path, and a run directory that is itself a link all leave that other directory as it was
VIC=$T/victim; mkdir -p "$VIC/sub"; echo keep > "$VIC/sub/precious"
mkc() { ./bin/qargi local prepare --repo "$T/r2" --base main --slug "$1" --scratch "$T" | sed -n '1,/^$/s/^\(RUN\|TMP\)=//p' | paste -sd' '; }
ln -s "$VIC" "$T/qargi-run.abcde"; ln -s "$VIC" "$T/qargi-run.abcdef"
mkdir -p "$T/realroot/qargi-run.ghijkl"; touch "$T/realroot/qargi-run.ghijkl/precious"; ln -s "$T/realroot" "$T/linkroot"
n=0
for form in 'T/qargi-run.abcde/' 'T/qargi-run.abcde' 'T/qargi-run.abcdef' 'T/qargi-run.abcdef/' 'T/qargi-run.abcdef//' 'RUN/tmp/' 'RUN/tmp' 'T/linkroot/qargi-run.ghijkl' 'T/linkroot/qargi-run.ghijkl/'; do
  n=$((n + 1)); read -r CV TV <<<"$(mkc "lk$n")"
  case $form in
    RUN/tmp*) ln -s "$VIC" "$CV/tmp"; rec="$CV/${form#RUN/}";;
    T/*) rec="$T/${form#T/}";;
  esac
  settmp "$CV" "$rec"
  ./bin/qargi local clean "$CV" --discard >/dev/null 2>&1
  [ -f "$VIC/sub/precious" ] && [ -f "$T/realroot/qargi-run.ghijkl/precious" ] && [ ! -e "$CV" ] && ok "a recorded tmpdir '$form' is left alone: what it leads to is untouched" || no "tmpdir '$form' damaged something"
  rm -rf "$TV"
done
read -r CV TV <<<"$(mkc lk-slash)"; touch "$TV/x"; settmp "$CV" "$TV/"
./bin/qargi local clean "$CV" --discard >/dev/null 2>&1
[ ! -e "$TV" ] && [ ! -e "$CV" ] && ok "a real temporary directory recorded with a trailing slash is removed" || no "trailing slash tmpdir not removed"
read -r CV TV <<<"$(mkc lk-run)"; echo '{}' > "$CV/out/manifest.json"; mv "$CV" "$T/real-$(basename "$CV")"; ln -s "$T/real-$(basename "$CV")" "$CV"
./bin/qargi local clean "$CV/" >/dev/null 2>&1; ./bin/qargi local clean "$CV" >/dev/null 2>&1
[ -f "$T/real-$(basename "$CV")/refs.before" ] && ok "a run directory that is a link is not cleaned, with or without a trailing slash" || no "a linked run dir was cleaned"
rm -f "$CV"; rm -rf "$T/real-$(basename "$CV")" "$TV" "$T/qargi-run.abcde" "$T/qargi-run.abcdef" "$T/linkroot" "$T/realroot"
# the run's own tmpdir file is not trusted: it names another run's temporary directory (also written with // and with a trailing slash), and clean of this run
# removes this run's directory from the registry and leaves the other alone
read -r CX TX <<<"$(mkc fg-x)"; read -r CY TY <<<"$(mkc fg-y)"; touch "$TY/precious"
for form in "$TY" "$TY/" "${TY%/*}//${TY##*/}" "${TY%/*}/./${TY##*/}"; do
  printf '%s\n' "$form" > "$CX/tmpdir"; mkdir -p "$TX"
  ./bin/qargi local clean "$CX" --discard >/dev/null 2>&1
  [ -f "$TY/precious" ] && [ ! -e "$CX" ] && [ ! -e "$TX" ] && ok "a tmpdir file naming another run's temporary directory ('$form') is ignored: the other run's is untouched and this run's own is removed" \
    || no "forged tmpdir file '$form': other=$(ls "$TY" 2>&1) run=$(ls -d "$CX" 2>&1) own=$(ls -d "$TX" 2>&1)"
  read -r CX TX <<<"$(mkc fg-x)"
done
# a run with no line in the registry loses only RUN/tmp, whatever its tmpdir file says
jq -c --arg r "$CX" 'select(.run != $r)' "$T/s/local-runs.jsonl" > "$T/s/lr.new" && mv "$T/s/lr.new" "$T/s/local-runs.jsonl"
mkdir -p "$CX/tmp"; touch "$CX/tmp/x"; printf '%s\n' "$TY" > "$CX/tmpdir"
./bin/qargi local clean "$CX" --discard >/dev/null 2>&1
[ -f "$TY/precious" ] && [ ! -e "$CX" ] && [ -d "$TX" ] && ok "with no registry line only RUN/tmp goes: the tmpdir file's directory and the unrecorded temporary directory are left" || no "no record: other=$(ls "$TY" 2>&1) run=$(ls -d "$CX" 2>&1)"
rm -rf "$TX" "$TY" "$CY"
# the repository, its URL and the credential path come from the lead's registry, never from the run directory (repo.path, repo.url and cred.path are a member's
# to write): a run whose files disagree with the registry is refused by verify, clean and run before any git is run for it
read -r CF TF <<<"$(mkc rf-a)"; echo '{}' > "$CF/out/manifest.json"
[ "$(jq -r 'select(.slug=="rf-a") | .repo' "$T/s/local-runs.jsonl")" = "$(readlink -f "$T/r2")" ] && [ "$(jq -r 'select(.slug=="rf-a") | has("url")' "$T/s/local-runs.jsonl")" = false ] \
  && [ "$(stat -c %a "$T/s/local-runs.jsonl")" = 600 ] && [ "$(cat "$CF/repo.path")" = "$(readlink -f "$T/r2")" ] \
  && ok "prepare records the repository's real path in the registry (mode 600), the same text as RUN/repo.path" || no "registry repo: $(grep rf-a "$T/s/local-runs.jsonl")"
mkdir -p "$T/fg"; cat > "$T/fg/git" <<SH
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/fg/argv"
exec $(command -v git) "\$@"
SH
chmod 755 "$T/fg/git"
git init -q -b main "$T/evil" && $LC -C "$T/evil" commit -q --allow-empty -m one && git -C "$T/evil" remote add origin ssh://nowhere.invalid/x
git -C "$T/evil" config core.sshCommand "touch $T/pwn-ssh; false"
: > "$T/fg/argv"; cp "$CF/repo.path" "$T/repo.path.keep"; echo "$T/evil" > "$CF/repo.path"
out=$(PATH="$T/fg:$PATH" ./bin/qargi local verify "$CF" 2>&1); rcv=$?
{ [ $rcv != 0 ] && grep -q "registry" <<<"$out" && [ ! -e "$T/pwn-ssh" ] && ! grep -q "$T/evil" "$T/fg/argv"; } \
  && ok "verify refuses a run whose repo.path was changed, and runs no git in the repository it names" || no "forged repo.path (rc=$rcv): $out; git saw: $(cat "$T/fg/argv")"
out=$(PATH="$T/fg:$PATH" ./bin/qargi local clean "$CF" 2>&1); rcc=$?
{ [ $rcc != 0 ] && [ -d "$CF" ] && [ ! -e "$T/pwn-ssh" ] && grep -q "registry" <<<"$out"; } && ok "clean refuses it too and keeps the run" || no "clean forged repo.path (rc=$rcc): $out"
cp "$T/repo.path.keep" "$CF/repo.path"
./bin/qargi local verify "$CF" >/dev/null 2>&1 && ok "with the file as prepare wrote it, verify passes again" || no "verify after restoring repo.path"
# a repository URL and a credential path a member adds: no git call, no token read
printf 'secret-token-text\n' > "$T/secret.txt"; : > "$T/fg/argv"
printf '%s\n' "https://nowhere.invalid/x" > "$CF/repo.url"; printf '%s\n' "$T/secret.txt" > "$CF/cred.path"
out=$(PATH="$T/fg:$PATH" ./bin/qargi local verify "$CF" 2>&1); rcv=$?
{ [ $rcv != 0 ] && grep -q "repo.url" <<<"$out" && ! grep -q "nowhere.invalid" "$T/fg/argv"; } \
  && ok "verify refuses a repo.url and a cred.path the registry does not record: nothing is sent anywhere" || no "forged repo.url (rc=$rcv): $out; git saw: $(cat "$T/fg/argv")"
rm -f "$CF/repo.url" "$CF/cred.path"
# the other way: the files of the run are gone, or the run is not in the registry at all
mv "$CF/repo.path" "$T/repo.path.gone"
./bin/qargi local verify "$CF" >/dev/null 2>&1 && no "verify accepted a run with no repo.path" || ok "a missing repo.path is a disagreement too"
mv "$T/repo.path.gone" "$CF/repo.path"
cp "$T/s/local-runs.jsonl" "$T/lr.keep"; jq -c --arg r "$CF" 'select(.run != $r)' "$T/lr.keep" > "$T/s/local-runs.jsonl"
out=$(./bin/qargi local verify "$CF" 2>&1); rcv=$?; out2=$(./bin/qargi local clean "$CF" 2>&1); rcc=$?
{ [ $rcv != 0 ] && [ $rcc != 0 ] && [ -d "$CF" ] && grep -q "not in the lead's registry" <<<"$out$out2"; } && ok "a run the registry does not name is refused by verify and clean" || no "unregistered (rc=$rcv,$rcc): $out $out2"
cp "$T/lr.keep" "$T/s/local-runs.jsonl"
# a run of a repository URL: the URL and the credential path the registry records are the ones used (the files must agree with it)
jq -c --arg r "$CF" 'if .run == $r then del(.repo) | .url = "https://nowhere.invalid/real" | .cred = "'"$T"'/secret.txt" else . end' "$T/lr.keep" > "$T/s/local-runs.jsonl"
rm -f "$CF/repo.path"; printf '%s\n' "https://nowhere.invalid/real" > "$CF/repo.url"; printf '%s\n' "$T/secret.txt" > "$CF/cred.path"; : > "$T/fg/argv"
out=$(PATH="$T/fg:$PATH" ./bin/qargi local verify "$CF" 2>&1)
{ grep -q "x-access-token@nowhere.invalid/real" "$T/fg/argv" && ! grep -q "secret-token-text" "$T/fg/argv"; } \
  && ok "a URL run asks the URL of the registry (with the token passed in the environment, never in argv)" || no "URL run: $out; git saw: $(cat "$T/fg/argv")"
cp "$T/lr.keep" "$T/s/local-runs.jsonl"; cp "$T/repo.path.keep" "$CF/repo.path"; rm -f "$CF/repo.url" "$CF/cred.path"
./bin/qargi local clean "$CF" --discard >/dev/null 2>&1; rm -rf "$TF" "$T/evil" "$T/fg" "$T/repo.path.keep" "$T/repo.path.gone" "$T/lr.keep" "$T/secret.txt"
# list prints no control or escape byte a run's files hold
read -r CZ TZ <<<"$(mkc ls-ctl)"; printf 'bui\033]0;pwn\007ld\n' > "$CZ/ability"
jq -c --arg r "$CZ" 'if .run == $r then .slug = "s\u001b[2Jl\u0007ug" else . end' "$T/s/local-runs.jsonl" > "$T/s/lr.new" && mv "$T/s/lr.new" "$T/s/local-runs.jsonl"
out=$(./bin/qargi local list --scratch "$T"); outr=$(./bin/qargi local list)
{ ! LC_ALL=C grep -q "$(printf '[\001-\010\013-\037\177]')" <<<"$out" && ! LC_ALL=C grep -q "$(printf '[\001-\010\013-\037\177]')" <<<"$outr" && grep -q 'bui\]0;pwnld' <<<"$out" && grep -q 's\[2Jlug' <<<"$outr"; } \
  && ok "list prints the files of a run without control or escape bytes (also the slug the registry holds)" || no "list printed raw bytes: $(cat -v <<<"$out" | grep ls-ctl)"
rm -rf "$CZ" "$TZ"
# list and clean --applied: the runs of one scratch directory
git init -q -b main "$T/r6" && $LC -C "$T/r6" commit -q --allow-empty -m one
mkdir -p "$T/ls" "$T/ls2"
lrun() { # slug scratch -> the run directory, with one commit in its clone, a manifest and a passing verify
  local o r g c
  o=$(./bin/qargi local prepare --repo "$T/r6" --base main --slug "$1" --scratch "$2") || return 1
  r=$(sed -n '1,/^$/s/^RUN=//p' <<<"$o"); g=$(sed -n '1,/^$/s/^GIT=//p' <<<"$o"); c=$(sed -n '1,/^$/s/^CLONE=//p' <<<"$o")
  echo "$1" > "$c/f-$1"; "$g" -C "$c" add "f-$1"; "$g" -C "$c" commit -q -m "work $1"; echo '{}' > "$r/out/manifest.json"; echo r > "$r/out/report.md"
  ./bin/qargi local verify "$r" >/dev/null 2>&1; echo "$r"
}
applied() { # run branch -> a commit on top of main named for the run, recorded in RUN/applied; prints the sha
  local sha; sha=$($LC -C "$T/r6" commit-tree -p main -m "applied $1" "$(git -C "$T/r6" rev-parse 'main^{tree}')")
  printf '%s %s now\n' "$2" "$sha" > "$1/applied"; echo "$sha"
}
LA=$(lrun la "$T/ls"); LB=$(lrun lb "$T/ls"); LCC=$(lrun lc "$T/ls"); LD=$(lrun ld "$T/ls2")
TMA=$(cat "$LA/tmpdir"); TMB=$(cat "$LB/tmpdir")
SA=$(applied "$LA" agent/la); git -C "$T/r6" update-ref refs/heads/feature/la "$SA"
SB=$(applied "$LB" agent/lb); git -C "$T/r6" update-ref refs/heads/agent/lb "$SB"
SD=$(applied "$LD" agent/ld); git -C "$T/r6" update-ref refs/heads/feature/ld "$SD"
before=$(find "$T/ls" "$T/ls2" -type f -printf '%p %T@ %s\n' | sort | sha256sum)
out=$(./bin/qargi local list --scratch "$T/ls"); rcl=$?
[ $rcl = 0 ] && [ "$(head -1 <<<"$out" | awk '{print $1,$2,$3,$4,$5,$6}')" = "ROLE SLUG AGE APPLIED MERGED RUN" ] \
  && [ "$(awk '$2=="la"{print $1,$4,$5,$6}' <<<"$out")" = "build yes yes $LA" ] && [ "$(awk '$2=="lb"{print $1,$4,$5}' <<<"$out")" = "build yes no" ] \
  && [ "$(awk '$2=="lc"{print $1,$4,$5}' <<<"$out")" = "build no no" ] && ! grep -q "$LD" <<<"$out" && [ "$(wc -l <<<"$out")" = 4 ] \
  && ok "list --scratch DIR: role, slug, age, applied and merged of each run in that directory only" || no "list: rc=$rcl $out"
out=$(./bin/qargi local list); for sl in la lb lc ld; do awk -v s=$sl '$2==s{f=1} END{exit !f}' <<<"$out" || no "the registry list lacks $sl"; done
awk '$2=="ld"{f=1} END{exit !f}' <<<"$out" && ok "list with no --scratch reads the registry (runs that still exist)" || no "registry list: $out"
[ "$before" = "$(find "$T/ls" "$T/ls2" -type f -printf '%p %T@ %s\n' | sort | sha256sum)" ] && ok "and list changes nothing" || no "list changed a file"
./bin/qargi local list --scratch "$T/nonexistent" >/dev/null 2>&1 && no "list accepted a missing directory" || ok "list refuses a directory that does not exist"
for bad in "--applied" "--applied --scratch $T/ls $LA" "--applied --discard --scratch $T/ls" "--scratch $T/ls $LA" "--applied --scratch $T/nonexistent"; do
  # shellcheck disable=SC2086
  ./bin/qargi local clean $bad >/dev/null 2>&1 && no "clean $bad was accepted" || ok "clean $bad is refused"
done
[ -d "$LA" ] && [ -d "$LB" ] && [ -d "$LCC" ] && [ -d "$LD" ] && ok "and the refused calls removed nothing" || no "a refused call removed a run"
mkdir "$T/ls/qargi.zzzzzz"; touch "$T/ls/qargi.zzzzzz/keep"; ln -s "$LD" "$T/ls/qargi.linkdd"
out=$(./bin/qargi local clean --applied --scratch "$T/ls" 2>&1); rca=$?
[ ! -e "$LA" ] && [ ! -e "$TMA" ] && grep -q "^cleaned $LA" <<<"$out" && ok "clean --applied removes a run whose work is applied and merged, with its temporary directory" || no "applied+merged run: $out"
[ -d "$LB" ] && [ -d "$TMB" ] && [ $rca = 1 ] && grep -q "kept $LB: .*not merged into any branch" <<<"$out" && ok "an applied run that is not merged is kept, named, with the reason (exit 1)" || no "unmerged run (rc=$rca): $out"
[ -d "$LCC" ] && grep -q "kept $LCC: its work is not recorded applied" <<<"$out" && ok "a run that was never applied is kept" || no "unapplied run: $out"
[ -d "$LD" ] && [ -f "$T/ls/qargi.zzzzzz/keep" ] && [ -L "$T/ls/qargi.linkdd" ] && ok "nothing outside the directory's own run directories is touched (another scratch, a lookalike, a link)" || no "outside the scope: $out"
git -C "$T/r6" update-ref refs/heads/feature/lb "$SB"
out=$(./bin/qargi local clean --applied --scratch "$T/ls" 2>&1); rca=$?
[ ! -e "$LB" ] && [ ! -e "$TMB" ] && [ -d "$LCC" ] && [ $rca = 0 ] && ok "once merged it is removed, and a run still in progress is no failure (exit 0)" || no "after merge (rc=$rca): $out"
rm -f "$T/ls/qargi.linkdd"; rm -rf "$T/ls/qargi.zzzzzz"
git -C "$T/r6" tag t-evidence "$SA"
out=$(./bin/qargi local clean --applied --scratch "$T/ls2" 2>&1); rca=$?
[ $rca = 1 ] && [ -d "$LD" ] && grep -q "kept $LD: .*refs of the repository changed" <<<"$out" && ok "an applied and merged run whose refs changed is kept as evidence" || no "changed refs (rc=$rca): $out"
git -C "$T/r6" tag -d t-evidence >/dev/null
# the second word of RUN/applied (a member can write it) is a full hex commit name or nothing: an option-like word never reaches git
mkdir -p "$T/ls4" "$T/gl"; LX=$(lrun lx "$T/ls4")
cat > "$T/gl/git" <<SH
#!/usr/bin/env bash
printf '%s\n' "\$*" >> "$T/gl/argv"
exec $(command -v git) "\$@"
SH
chmod 755 "$T/gl/git"
for w in --merged=HEAD --no-contains --help abc1234 "$(printf 'a%.0s' $(seq 1 41))" 'x;y'; do
  printf 'agent/lx %s now\n' "$w" > "$LX/applied"; : > "$T/gl/argv"
  out=$(PATH="$T/gl:$PATH" ./bin/qargi local list --scratch "$T/ls4" 2>&1); rcl=$?
  { [ $rcl = 0 ] && [ "$(awk '$2=="lx"{print $4,$5}' <<<"$out")" = "yes ?" ] && ! grep -q -- "$w" "$T/gl/argv"; } \
    && ok "list: an applied word '$w' that is no full commit name is not passed to git (merged shows ?)" || no "list '$w' (rc=$rcl): $out; git saw: $(cat "$T/gl/argv")"
  : > "$T/gl/argv"
  out=$(PATH="$T/gl:$PATH" ./bin/qargi local clean "$LX" 2>&1); rcc=$?
  { [ $rcc != 0 ] && [ -d "$LX" ] && grep -q 'second word' <<<"$out" && ! grep -q -- "$w" "$T/gl/argv"; } \
    && ok "clean refuses it with a message and keeps the run ('$w')" || no "clean '$w' (rc=$rcc): $out; git saw: $(cat "$T/gl/argv")"
done
SX=$(applied "$LX" agent/lx); git -C "$T/r6" update-ref refs/heads/feature/lx "$SX"
out=$(./bin/qargi local list --scratch "$T/ls4" 2>&1)
[ "$(awk '$2=="lx"{print $4,$5}' <<<"$out")" = "yes yes" ] && ok "a full commit name still shows merged" || no "list after fix: $out"
# the registry decides what a run is: a directory a member makes beside its own run (refs.before, ability ...) is not listed and not cleaned, and what a
# run's files hold never reaches the lead's shell (`started` is read as a number; text in an array subscript would run a command substitution)
mkdir -p "$T/ls6"; LG=$(lrun lg "$T/ls6"); FG=$T/ls6/qargi.forged
mkdir -p "$FG/out"; cat "$LG/refs.before" > "$FG/refs.before"; echo build > "$FG/ability"; echo '{}' > "$FG/out/manifest.json"
printf 'a[$(touch %s/pwn-forged)]\n' "$T" > "$FG/started"; printf 'agent/lg %s now\n' "$(git -C "$T/r6" rev-parse main)" > "$FG/applied"
echo "$T/r6" > "$FG/repo.path"; cat "$FG/refs.before" > "$FG/verified"
LGS=$(applied "$LG" agent/lg); git -C "$T/r6" update-ref refs/heads/feature/lg "$LGS"
printf 'a[$(touch %s/pwn-reg)]\n' "$T" > "$LG/started"
out=$(./bin/qargi local list --scratch "$T/ls6" 2>&1); outr=$(./bin/qargi local list 2>&1)
{ [ ! -e "$T/pwn-forged" ] && [ ! -e "$T/pwn-reg" ] && ! grep -q forged <<<"$out$outr" && [ "$(awk '$2=="lg"{print $3}' <<<"$out")" = '?' ] && [ "$(awk '$2=="lg"{print $3}' <<<"$outr")" = '?' ]; } \
  && ok "list: a sibling directory the registry does not name is not listed, and a started file with a command substitution runs nothing (age ?)" || no "list forged: $out; $outr; $(find "$T" -maxdepth 1 -name "pwn-*")"
out=$(./bin/qargi local clean --applied --scratch "$T/ls6" 2>&1); out2=$(./bin/qargi local clean --stale 0 --scratch "$T/ls6" --yes 2>&1)
{ [ -d "$FG" ] && [ ! -e "$T/pwn-forged" ] && [ ! -e "$T/pwn-reg" ] && ! grep -q forged <<<"$out$out2"; } \
  && ok "clean --applied and --stale leave a directory the registry does not name alone" || no "clean forged: $out; $out2"
[ ! -e "$LG" ] && ok "and still clean the registered run" || no "the registered run was not cleaned: $out"
rm -rf "$FG" "$T/ls6"
# clean --stale DAYS --scratch DIR: a plan of the finished runs older than DAYS, cleaned only with --yes, each by the rules of clean
mkdir -p "$T/ls5"
SOLD=$(lrun so "$T/ls5"); SKEEP=$(lrun sk "$T/ls5"); SNEW=$(lrun sn "$T/ls5"); SPROG=$(lrun sp "$T/ls5"); rm -f "$SPROG/verified"
SOA=$(applied "$SOLD" agent/so); git -C "$T/r6" update-ref refs/heads/feature/so "$SOA"
TMSO=$(cat "$SOLD/tmpdir")
SNA=$(applied "$SNEW" agent/sn); git -C "$T/r6" update-ref refs/heads/feature/sn "$SNA"
for r in "$SOLD" "$SKEEP" "$SPROG"; do printf '%s\n' "$(( $(date +%s) - 20 * 86400 ))" > "$r/started"; done
for bad in "--stale" "--stale x --scratch $T/ls5" "--stale 5" "--stale 5 --scratch $T/nonexistent" "--stale 5 --applied --scratch $T/ls5" "--stale 5 --discard --scratch $T/ls5" "--stale 5 --scratch $T/ls5 $SOLD" "--yes --scratch $T/ls5" "--yes $SOLD"; do
  # shellcheck disable=SC2086
  ./bin/qargi local clean $bad >/dev/null 2>&1 && no "clean $bad was accepted" || ok "clean $bad is refused"
done
before=$(find "$T/ls5" -type f -printf '%p %T@ %s\n' | sort | sha256sum)
out=$(./bin/qargi local clean --stale 7 --scratch "$T/ls5" 2>&1); rcs=$?
{ [ $rcs = 0 ] && grep -q "^would clean $SOLD (applied, 20d old)\$" <<<"$out" && grep -q "^would clean $SKEEP (verified, 20d old)\$" <<<"$out" \
  && ! grep -q "$SNEW" <<<"$out" && ! grep -q "$SPROG" <<<"$out" && grep -q '^plan: 2 finished run(s) older than 7 day(s)' <<<"$out" \
  && [ "$before" = "$(find "$T/ls5" -type f -printf '%p %T@ %s\n' | sort | sha256sum)" ]; } \
  && ok "clean --stale is a plan: the finished runs older than DAYS are named, a newer run and one in progress are not, nothing changes" || no "stale plan (rc=$rcs): $out"
out=$(./bin/qargi local clean --stale 30 --scratch "$T/ls5" 2>&1); grep -q '^plan: 0 ' <<<"$out" && ok "no run is that old: an empty plan" || no "stale 30: $out"
out=$(./bin/qargi local clean --stale 7 --scratch "$T/ls5" --yes 2>&1); rcs=$?
{ [ $rcs = 1 ] && [ ! -e "$SOLD" ] && [ ! -e "$TMSO" ] && grep -q "^cleaned $SOLD" <<<"$out" && [ -d "$SKEEP" ] && grep -q "kept $SKEEP: .*never applied" <<<"$out" \
  && [ -d "$SNEW" ] && [ -d "$SPROG" ] && grep -q '^cleaned 1 run(s), kept 1' <<<"$out"; } \
  && ok "--yes cleans a stale applied and merged run, keeps and names a stale run whose work was never applied (exit 1), and leaves the new and the unfinished" || no "stale --yes (rc=$rcs): $out"
# a run with no started file, or one that is not a number, has an unknown age: it is named as skipped, never aged from another file's date
rm -f "$SKEEP/started"; touch -d '20 days ago' "$SKEEP/refs.before"
out=$(./bin/qargi local clean --stale 7 --scratch "$T/ls5" 2>&1); { ! grep -q "^would clean $SKEEP " <<<"$out" && grep -q "^skipped $SKEEP: no start time recorded" <<<"$out"; } && ok "a run with no started file is skipped by --stale (its age is unknown), and named" || no "no started: $out"
echo notanumber > "$SKEEP/started"
out=$(./bin/qargi local clean --stale 7 --scratch "$T/ls5" 2>&1); { ! grep -q "^would clean $SKEEP " <<<"$out" && grep -q "^skipped $SKEEP: no start time recorded" <<<"$out"; } && ok "so is one whose started file is not a number" || no "bad started: $out"
out=$(./bin/qargi local list --scratch "$T/ls5" 2>&1); [ "$(awk '$2=="sk"{print $3}' <<<"$out")" = '?' ] && ok "and list shows its age as ?" || no "list age: $out"
# a relative --repo and --scratch are recorded as real paths, and a QARGI_RUN_TMP written with a trailing slash still cleans; a URL with a user in it is refused
ROOTD=$PWD; mkdir -p "$T/relscr"
out=$(cd "$T" && "$ROOTD/bin/qargi" local prepare --repo ./r2 --base main --slug rel1 --scratch ./relscr 2>&1); RR=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
{ [ "$RR" = "$T/relscr/$(basename "$RR")" ] && [ "$(jq -r 'select(.slug=="rel1") | .run' "$T/s/local-runs.jsonl")" = "$RR" ] && [ "$(jq -r 'select(.slug=="rel1") | .repo' "$T/s/local-runs.jsonl")" = "$T/r2" ] && [ "$(cat "$RR/repo.path")" = "$T/r2" ]; } \
  && ok "a relative --repo and --scratch are recorded as real paths (the run directory, the registry and RUN/repo.path)" || no "relative prepare: $out; $(grep rel1 "$T/s/local-runs.jsonl")"
echo '{}' > "$RR/out/manifest.json"; out=$(cd "$T/relscr" && "$ROOTD/bin/qargi" local clean "$(basename "$RR")" 2>&1); [ ! -e "$RR" ] && ok "and a run prepared with relative paths is cleaned from another directory" || no "relative clean: $out"
out=$(QARGI_RUN_TMP="$T/" ./bin/qargi local prepare --repo "$T/r2" --base main --slug slash1 --scratch "$T"); SR=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out"); STM=$(sed -n '1,/^$/s/^TMP=//p' <<<"$out")
echo '{}' > "$SR/out/manifest.json"; QARGI_RUN_TMP="$T/" ./bin/qargi local clean "$SR" >/dev/null 2>&1
{ [ "$STM" = "$T/$(basename "$STM")" ] && [ ! -e "$SR" ] && [ ! -e "$STM" ]; } && ok "a QARGI_RUN_TMP with a trailing slash: the temporary directory is removed with the run" || no "trailing slash QARGI_RUN_TMP: TMP=$STM run=$(ls -d "$SR" 2>&1)"
nreg=$(wc -l < "$T/s/local-runs.jsonl")
for u in https://user@example.invalid/x.git https://user:pw@example.invalid/x.git https://x-access-token@example.invalid/x; do
  out=$(./bin/qargi local prepare --repo-url "$u" --base main --slug ui --scratch "$T" 2>&1); rcu=$?
  { [ $rcu != 0 ] && grep -q "must not carry a user name" <<<"$out" && ! grep -q "pw@\|user@" <<<"$out" && [ "$(wc -l < "$T/s/local-runs.jsonl")" = "$nreg" ]; } && ok "--repo-url $u is refused, without echoing it and with no run made" || no "userinfo URL $u (rc=$rcu): $out"
done
# a Claude Code render of the project (packs apply --target claude-code): prepare warns about drift, never fails, never changes the block
git init -q -b main "$T/r4" && $LC -C "$T/r4" commit -q --allow-empty -m one
mkdir -p "$T/c/projects"
jq -n --arg p "$T/r4" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/x",path:$p,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  models:{provider:"claude-code"},memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha.json"
mk4() { # stderr in $T/err, without the tmpfs warning (checked on its own below): $T may be on a tmpfs
  local rc=0; ./bin/qargi local prepare --repo "$T/r4" --base main --slug "$1" --scratch "$T" 2>"$T/err.all" || rc=$?
  grep -v 'is on a tmpfs: a reboot loses the run' "$T/err.all" > "$T/err"; return $rc; }
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
out=$(mk4 w0); [ ! -s "$T/err" ] && ok "no render: prepare prints no warning" || no "no render: $(cat "$T/err")"
Q=./bin/qargi
$Q skill new s-w --compatible any >/dev/null; sed -i "s/^description: .*/description: Use for s-w./" "$T/c/packs/skills/s-w/SKILL.md"
$Q skill seal s-w --plan "$($Q skill seal s-w | tokof)" --approved test >/dev/null
$Q skill link s-w --scope project --project alpha >/dev/null
$Q packs apply --target claude-code alpha --plan "$($Q packs apply --target claude-code alpha | tokof)" --approved test >/dev/null
out=$(mk4 w1); [ -f "$T/s/render/alpha/claude-code/MANIFEST.json" ] && [ ! -s "$T/err" ] && ok "a clean render: no warning" || no "clean render: $(cat "$T/err")"
echo tamper >> "$T/s/render/alpha/claude-code/.claude/skills/s-w/SKILL.md"
out=$(mk4 w2); rcw=$?
grep -q '^WARNING: the Claude Code render of project alpha' "$T/err" && grep -q 'SKILL.md' "$T/err" && grep -q 'fix: qargi packs apply --target claude-code alpha' "$T/err" && [ $rcw = 0 ] \
  && ok "a drifted render: a WARNING with the findings and the fix, and prepare still succeeds" || no "drift: $rcw $(cat "$T/err")"
blk=$(sed '1,/^TASK-BLOCK PATHS$/d' <<<"$out"); W2=$(runof <<<"$out")
[ "$(sed -n '1p' <<<"$blk")" = "RUN_DIR=$W2" ] && [ "$(wc -l <<<"$blk")" = 7 ] && ! grep -q WARNING <<<"$out" && ok "the paths block is intact and the warning is not in stdout" || no "block: $blk"
rm -rf "$T/s/render/alpha/claude-code"; out=$(mk4 w3); [ ! -s "$T/err" ] && ok "no render again: no warning" || no "removed render: $(cat "$T/err")"
# a project with no provider: the check cannot run (there is no default provider), and the note says so in one line, not "out of date"
$Q packs apply --target claude-code alpha --plan "$($Q packs apply --target claude-code alpha | tokof)" --approved test >/dev/null
jq 'del(.models)' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
echo tamper >> "$T/s/render/alpha/claude-code/.claude/skills/s-w/SKILL.md"
out=$(mk4 w4); rcw=$?
[ "$(cat "$T/err")" = "note: project alpha has no provider (qargi project set alpha models.provider NAME); the render check was skipped" ] && [ $rcw = 0 ] && ! grep -q 'WARNING\|out of date\|altered' "$T/err" \
  && ok "no provider: one note line, the render check skipped, prepare still succeeds" || no "no provider: $rcw $(cat "$T/err")"
out=$(mk4 w4b); [ "$(wc -l < "$T/err")" = 1 ] && ok "(and only one line)" || no "lines: $(cat "$T/err")"
# the render is the local surface's: an object that names only a cloud runtime has no local provider, and the note names the surface
jq '.models = {provider: {cloud: "claude-platform"}}' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
out=$(mk4 w4c); rcw=$?
[ "$(cat "$T/err")" = "note: project alpha has no local provider (qargi project set alpha models.provider.local NAME); the render check was skipped" ] && [ $rcw = 0 ] \
  && ok "only a cloud provider: the note names the local surface and the command, the check is skipped" || no "cloud-only provider: $rcw $(cat "$T/err")"
jq '.models = {provider: "claude-code"}' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"
rm -rf "$T/s/render/alpha/claude-code"
# an accepted skill of the checkout that drifted makes `packs check` exit 1, but the render is fine: no render warning
$Q packs apply --target claude-code alpha --plan "$($Q packs apply --target claude-code alpha | tokof)" --approved test >/dev/null
QA=$PWD/bin/qargi; mkdir -p "$T/r4/.claude/skills/mine"; printf -- '---\nname: mine\ndescription: Use for mine.\n---\n' > "$T/r4/.claude/skills/mine/SKILL.md"
( cd "$T" && "$QA" skill accept alpha mine --plan "$("$QA" skill accept alpha mine | tokof)" --approved test ) >/dev/null 2>&1
echo drift >> "$T/r4/.claude/skills/mine/SKILL.md"
$Q packs check --target claude-code alpha >"$T/chk" 2>&1; rcc=$?
out=$(mk4 w5); [ $rcc = 1 ] && grep -qE '^ +drifted +mine ' "$T/chk" && [ ! -s "$T/err" ] \
  && ok "a drifted accepted skill fails the check but is not blamed on the render" || no "audit drift as render drift: check rc=$rcc, warning: $(cat "$T/err")"
echo tamper >> "$T/s/render/alpha/claude-code/.claude/skills/s-w/SKILL.md"
out=$(mk4 w6); grep -q '^WARNING: the Claude Code render of project alpha' "$T/err" && ! grep -q 'drifted' "$T/err" && ok "a tampered render still warns, without the skills section" || no "tampered render: $(cat "$T/err")"
rm -rf "$T/s/render/alpha/claude-code" "$T/r4/.claude"
# a local runtime that is set but does not resolve is refused (the contract addenda would be left out); none set, or no project, is not
setmodels() { jq --argjson m "$1" '.models = $m' "$T/c/projects/alpha.json" > "$T/p.tmp" && mv "$T/p.tmp" "$T/c/projects/alpha.json"; }
setmodels '{"provider":{"local":"nosuchrt","cloud":"claude-platform"}}'
nrun=$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l); nreg=$(wc -l < "$T/s/local-runs.jsonl")
out=$(mk4 gh1); rcg=$?; out="$out$(cat "$T/err")"
{ [ $rcg != 0 ] && grep -q 'nosuchrt' <<<"$out" && grep -q 'contract addenda' <<<"$out" && [ "$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l)" = "$nrun" ] && [ "$(wc -l < "$T/s/local-runs.jsonl")" = "$nreg" ]; } \
  && ok "a local provider that is set but does not resolve: prepare fails with the reason, and makes no run" || no "unresolved provider (rc=$rcg): $out"
setmodels '{"provider":{"cloud":"claude-platform"}}'
out=$(mk4 gh2); rcg=$?; GH2=$(runof <<<"$out")
{ [ $rcg = 0 ] && [ "$(ls "$GH2/contract")" = "$(printf 'contract.md\nmanifest.example.json\noutput-format.md')" ]; } && ok "no local provider set: prepare goes on with the core's contract alone" || no "no local provider (rc=$rcg): $out"
setmodels '{"provider":"claude-code"}'

# prepare --profile: the resolver is asked before any clone; the run records the profile
Q=./bin/qargi
QARGI_PROJECT=rproj $Q agent add reviewer --project rproj >/dev/null 2>&1; QARGI_PROJECT=rproj $Q agent add worker --project rproj >/dev/null 2>&1
out=$($Q local prepare --repo "$T/r" --base main --slug pf1 --scratch "$T" --role review --profile advisor 2>&1); PR=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
[ "$(cat "$PR/profile" 2>/dev/null)" = advisor ] && grep -qx 'PROFILE=advisor' <<<"$out" && grep -qx 'MEMBER=reviewer' <<<"$out" && grep -qx 'MODEL=opus' <<<"$out" && grep -q '^EFFORT=.' <<<"$out" \
  && ok "--profile records RUN/profile and prints PROFILE, MEMBER, MODEL, EFFORT" || no "profile: $out"
hlp=$($Q help local prepare 2>&1); miss=''
for k in $(sed '/^$/,$d' <<<"$out" | grep -E '^[A-Z_]+=' | cut -d= -f1); do
  grep -qw "$k" <<<"$hlp" || miss="$miss help:$k"; grep -q "\`$k\`" skills/qargi-task/SKILL.md || miss="$miss skill:$k"
done
[ -z "$miss" ] && ok "every key prepare prints is named in the help text and in the qargi-task skill" || no "keys not documented:$miss"
[ "$(jq -r 'select(.slug=="pf1") | .profile' "$T/s/local-runs.jsonl")" = advisor ] && ok "the run line carries the profile" || no "jsonl profile"
n1=$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l)
out=$($Q local prepare --repo "$T/r" --base main --slug pf2 --scratch "$T" --role build --profile auditor 2>&1); rcp=$?
[ "$rcp" != 0 ] && grep -q 'read-only' <<<"$out" && [ "$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l)" = "$n1" ] && ! grep -qw pf2 "$T/s/local-runs.jsonl" \
  && ok "a profile of the wrong class dies with the resolver's reason and leaves no run directory" || no "class conflict: $rcp $out"
out=$($Q local prepare --repo "$T/r" --base main --slug pf3 --scratch "$T" --role build 2>&1); P3=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
grep -qx 'PROFILE=build' <<<"$out" && ! grep -q '^MODEL=' <<<"$out" && [ ! -e "$P3/profile" ] && [ "$(jq -r 'select(.slug=="pf3") | .profile' "$T/s/local-runs.jsonl")" = build ] \
  && ok "without --profile: PROFILE=<role> and nothing else changes" || no "no profile: $out"

# --- runs that survive a reboot
# a --scratch on a tmpfs is warned about (the risk and a disk directory); one that is not, is not
git init -q -b main "$T/r7" && $LC -C "$T/r7" commit -q --allow-empty -m one
# hermetic: allow tmp (the warning is for a tmpfs, and /dev/shm is the one: the test makes its own directory in it and removes it)
if [ "$(stat -f -c %T /dev/shm 2>/dev/null)" = tmpfs ]; then
  SHMS=$(mktemp -d -p /dev/shm qargi-test-scratch.XXXXXX)   # hermetic: allow tmp (see above)
  out=$(./bin/qargi local prepare --repo "$T/r7" --base main --slug tf1 --scratch "$SHMS" 2>&1 >/dev/null); rcw=$?
  { [ $rcw = 0 ] && grep -q "warning: --scratch $SHMS is on a tmpfs: a reboot loses the run" <<<"$out" && grep -q "directory on disk" <<<"$out"; } \
    && ok "prepare warns that a --scratch on a tmpfs is lost on a reboot, and suggests a disk directory" || no "tmpfs warning (rc=$rcw): $out"
  for d in "$SHMS"/qargi.??????; do ./bin/qargi local clean "$d" --discard >/dev/null 2>&1; done; rm -rf "$SHMS"
else ok "(no tmpfs at the shared memory directory: the tmpfs warning is not checked here)"; fi
out=$(./bin/qargi local prepare --repo "$T/r7" --base main --slug tf2 --scratch "$T" 2>&1 >/dev/null)
if [ "$(stat -f -c %T "$T")" = tmpfs ]; then grep -q "is on a tmpfs" <<<"$out" && ok "(the test directory is a tmpfs: warned too)" || no "tmpfs \$T not warned: $out"
else ! grep -q "is on a tmpfs" <<<"$out" && ok "a --scratch on disk is not warned about" || no "disk scratch warned: $out"; fi
# a passing verify saves OUT, the bundle and the snapshots in the state; the copy outlives the run directory
mkdir -p "$T/rb"
rbrun() { # slug -> a run under $T/rb with one commit, a manifest, a bundle beside OUT, and a passing verify (its output in $T/vout)
  local o r g c
  o=$(./bin/qargi local prepare --repo "$T/r7" --base main --slug "$1" --scratch "$T/rb" 2>/dev/null) || return 1
  r=$(sed -n '1,/^$/s/^RUN=//p' <<<"$o"); g=$(sed -n '1,/^$/s/^GIT=//p' <<<"$o"); c=$(sed -n '1,/^$/s/^CLONE=//p' <<<"$o")
  echo "$1" > "$c/f-$1"; "$g" -C "$c" add "f-$1"; "$g" -C "$c" commit -q -m "work $1"; echo '{"status":"DONE"}' > "$r/out/manifest.json"; echo r > "$r/out/report.md"
  "$g" -C "$c" bundle create -q "$r/run.bundle" main..HEAD 2>/dev/null
  ./bin/qargi local verify "$r" > "$T/vout" 2>&1; echo "$r"
}
RB1=$(rbrun rb1); ID1=$(basename "$RB1"); SV1=$T/s/runs/$ID1
{ [ -f "$SV1/out/manifest.json" ] && [ -f "$SV1/run.bundle" ] && [ -f "$SV1/refs.before" ] && [ -f "$SV1/verified" ] && [ -f "$SV1/started" ] && [ "$(cat "$SV1/class")" = write ] \
  && [ "$(jq -r .slug "$SV1/record.json")" = rb1 ] && grep -q "saved a copy of the run's output in $SV1" "$T/vout"; } \
  && ok "a passing verify copies OUT, the run bundle, the snapshots and the registry's record to <state>/runs/<run id>/" || no "saved copy: $(ls -A "$SV1" 2>&1); $(cat "$T/vout")"
ln -s /etc/hostname "$RB1/out/link-out"; ./bin/qargi local verify "$RB1" >/dev/null 2>&1
[ -L "$SV1/out/link-out" ] && ok "a link in OUT is copied as a link, never followed" || no "link in OUT: $(ls -l "$SV1/out")"
# the directory vanishes (a reboot that emptied a tmpfs): list and report say so and name the saved copy; clean keeps the work
TRB1=$(jq -r --arg r "$RB1" 'select(.run == $r) | .tmpdir' "$T/s/local-runs.jsonl"); rm -rf "$RB1" "$TRB1"
out=$(./bin/qargi local list); outs=$(./bin/qargi local list --scratch "$T/rb")
{ grep -q "^build .*rb1 .*$RB1  directory gone, saved copy $SV1 (qargi review apply --from-saved $ID1)" <<<"$out" && grep -q "$RB1  directory gone" <<<"$outs"; } \
  && ok "list (the registry's and --scratch) shows a vanished run as directory gone, with its saved copy" || no "list gone: $out / $outs"
out=$(./bin/qargi report 2>&1); grep -q "directory gone [1-9]" <<<"$out" && grep -q "review apply --from-saved $ID1" <<<"$out" && ok "report counts it as directory gone and names the saved copy" || no "report gone: $out"
out=$(./bin/qargi local clean "$RB1" 2>&1); rc=$?
[ $rc != 0 ] && grep -q "never applied" <<<"$out" && grep -q "from-saved $ID1" <<<"$out" && [ -d "$SV1" ] && grep -q "$RB1" "$T/s/local-runs.jsonl" \
  && ok "clean of a vanished run whose saved work was never applied keeps the record and the copy, and says how to apply it" || no "clean gone, unapplied (rc=$rc): $out"
out=$(./bin/qargi local clean "$RB1" --discard 2>&1); rc=$?
{ [ $rc = 0 ] && grep -q "dropped the record of $RB1 (directory gone) and its saved copy" <<<"$out" && [ ! -e "$SV1" ] && ! grep -q "$RB1" "$T/s/local-runs.jsonl" \
  && [ "$(stat -c %a "$T/s/local-runs.jsonl")" = 600 ] && ! grep -q "$RB1" <<<"$(./bin/qargi local list)"; } \
  && ok "clean --discard of a vanished run drops its registry entry and its saved copy (the registry stays mode 600)" || no "discard gone (rc=$rc): $out"
./bin/qargi local clean "$RB1" --discard >/dev/null 2>&1 && no "a run dropped from the registry was cleaned again" || ok "and then the run is unknown"
# a clean marks the registry's line cleaned and removes the saved copy: the run is not listed as gone afterwards
RB2=$(rbrun rb2); SV2=$T/s/runs/$(basename "$RB2")
./bin/qargi local clean "$RB2" --discard >/dev/null 2>&1
{ [ ! -e "$RB2" ] && [ ! -e "$SV2" ] && [ -n "$(jq -r --arg r "$RB2" 'select(.run == $r) | .cleaned // empty' "$T/s/local-runs.jsonl")" ] && ! grep -q "$RB2" <<<"$(./bin/qargi local list)"; } \
  && ok "clean marks the run cleaned in the registry and removes its saved copy; list does not show it as gone" || no "clean marks: $(grep rb2 "$T/s/local-runs.jsonl")"
# clean --stale: vanished runs older than DAYS are cleaned too (they were left at 0 before), a saved copy that was never applied is kept
RB3=$(rbrun rb3); RB4=$(rbrun rb4); RB5=$(rbrun rb5); SV5=$T/s/runs/$(basename "$RB5")
rm -rf "$T/s/runs/$(basename "$RB3")"                                         # nothing saved of rb3
A5=$($LC -C "$T/r7" commit-tree -p main -m "applied rb5" "$(git -C "$T/r7" rev-parse 'main^{tree}')"); git -C "$T/r7" update-ref refs/heads/feature/rb5 "$A5"
printf 'agent/rb5 %s now\n' "$A5" > "$SV5/applied"                            # applied (from the saved copy) and merged
old=$(date -u -d '20 days ago' +%Y-%m-%dT%H:%M:%SZ)
for r in "$RB3" "$RB4" "$RB5"; do jq -c --arg r "$r" --arg t "$old" 'if .run == $r then .started = $t else . end' "$T/s/local-runs.jsonl" > "$T/s/lr.new" && mv "$T/s/lr.new" "$T/s/local-runs.jsonl"; rm -rf "$r"; done
chmod 600 "$T/s/local-runs.jsonl"
out=$(./bin/qargi local clean --stale 7 --scratch "$T/rb" 2>&1); rcs=$?
{ [ $rcs = 0 ] && grep -q "^would drop the record of $RB3 (directory gone, 20d old)" <<<"$out" && grep -q "^would drop the record of $RB4 (directory gone, saved copy" <<<"$out" \
  && grep -q "^plan: 3 " <<<"$out" && grep -q "$RB3" "$T/s/local-runs.jsonl"; } && ok "clean --stale plans the vanished runs older than DAYS, and changes nothing" || no "stale gone plan (rc=$rcs): $out"
out=$(./bin/qargi local clean --stale 7 --scratch "$T/rb" --yes 2>&1); rcs=$?
{ [ $rcs = 1 ] && grep -q "dropped the record of $RB3" <<<"$out" && grep -q "dropped the record of $RB5 (directory gone) and its saved copy" <<<"$out" \
  && grep -q "kept $RB4: directory gone, and its saved copy .* never applied" <<<"$out" && grep -q '^cleaned 2 run(s), kept 1' <<<"$out" \
  && ! grep -q "$RB3\|$RB5" "$T/s/local-runs.jsonl" && grep -q "$RB4" "$T/s/local-runs.jsonl"; } \
  && ok "clean --stale --yes drops the vanished runs (none saved, or applied and merged) and keeps the one whose saved work was never applied" || no "stale gone --yes (rc=$rcs): $out"
rm -rf "$T/rb"
out=$(./bin/qargi local list --scratch "$T/rb" 2>&1); rcl=$?
[ $rcl = 0 ] && grep -q "$RB4  directory gone" <<<"$out" && ok "a scratch directory that is gone itself is still listed from the registry" || no "list of a gone scratch (rc=$rcl): $out"
./bin/qargi local clean "$RB4" --discard >/dev/null 2>&1

# clean --orphans: the qargi-run.* directories of the temporary parent that no registry names. A fake parent (QARGI_RUN_TMP), never /dev/shm: the real one is only
# listed before and after, to show it was not touched.
# hermetic: allow tmp (the real parent of the run directories: only listed, never written or removed)
real_runs() { ls -d /dev/shm/qargi-run.* 2>/dev/null | sort | sha256sum; }
SHM0=$(real_runs)
OS=$T/shm-o; mkdir -p "$OS" "$T/os-scr"
mkorph() { # NAME DAYS_OLD -> $OS/qargi-run.NAME, with a file in it, both that old
  mkdir -p "$OS/qargi-run.$1" && echo x > "$OS/qargi-run.$1/f" && touch -d "$2 days ago" "$OS/qargi-run.$1/f" "$OS/qargi-run.$1"
}
OL=$(QARGI_RUN_TMP=$OS ./bin/qargi local prepare --repo "$T/r6" --base main --slug orlive --scratch "$T/os-scr" | sed -n '1,/^$/s/^RUN=//p')
OLT=$(cat "$OL/tmpdir"); touch -d "10 days ago" "$OLT"                       # a live run's directory, old
OG=$(QARGI_RUN_TMP=$OS ./bin/qargi local prepare --repo "$T/r6" --base main --slug orgone --scratch "$T/os-scr" | sed -n '1,/^$/s/^RUN=//p')
OGT=$(cat "$OG/tmpdir"); rm -rf "$OG"; touch -d "10 days ago" "$OGT"          # its run directory is gone, the registry still names the temporary one
mkorph AAAAAA 5; mkorph BBBBBB 3; mkorph NEWNEW 0; mkorph FRESHF 5; echo y > "$OS/qargi-run.FRESHF/g"; touch -d "5 days ago" "$OS/qargi-run.FRESHF"   # an old directory with a file that is new
mkdir -p "$T/victim" && echo v > "$T/victim/keep"; ln -s "$T/victim" "$OS/qargi-run.LINKED"; echo f > "$OS/qargi-run.AFILES"
orph() { QARGI_RUN_TMP=$OS ./bin/qargi local clean --orphans "$@" 2>&1; }
out=$(orph); rcs=$?
tok=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
{ [ $rcs = 0 ] && [ -n "$tok" ] && grep -q "^orphan $OS/qargi-run.AAAAAA (5d old, named by no registry)" <<<"$out" && grep -q "^orphan $OS/qargi-run.BBBBBB (3d old" <<<"$out" \
  && grep -q "^kept $OLT (10d old): named by the registry (its run directory $OL exists)" <<<"$out" && grep -q "^kept $OGT (10d old): named by the registry (the run directory $OG is gone)" <<<"$out" \
  && grep -q "^kept $OS/qargi-run.NEWNEW (0d old): named by no registry, but it or something in it changed within 2 day" <<<"$out" && grep -q "^kept $OS/qargi-run.FRESHF (5d old): named by no registry, but" <<<"$out" \
  && grep -q "^kept $OS/qargi-run.LINKED: not a directory" <<<"$out" && grep -q "^kept $OS/qargi-run.AFILES: not a directory" <<<"$out" && grep -q " 2 orphaned for more than 2 day" <<<"$out" \
  && ! grep -q "^orphan .*\(NEWNEW\|FRESHF\|LINKED\|AFILES\|$(basename "$OLT")\|$(basename "$OGT")\)" <<<"$out" \
  && [ -d "$OS/qargi-run.AAAAAA" ] && [ -d "$OS/qargi-run.BBBBBB" ] && [ -f "$T/victim/keep" ]; } \
  && ok "clean --orphans lists each directory with its age and whether the registry names it, prints a plan and a token, and removes nothing" || no "orphans plan (rc=$rcs): $out"
out=$(orph --approved "go"); rcs=$?
{ [ $rcs != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ -d "$OS/qargi-run.AAAAAA" ]; } && ok "--approved without the plan token removes nothing" || no "approved without plan (rc=$rcs): $out"
out=$(orph --plan 000000000000 --approved "go"); rcs=$?
{ [ $rcs != 0 ] && [ -d "$OS/qargi-run.AAAAAA" ] && [ -d "$OS/qargi-run.BBBBBB" ]; } && ok "a wrong token removes nothing" || no "wrong token (rc=$rcs): $out"
out=$(QARGI_NESTED=1 orph --approved "go"); rcs=$?
{ [ $rcs != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ -d "$OS/qargi-run.AAAAAA" ]; } && ok "QARGI_NESTED does not stand in for the token: --approved alone removes nothing" || no "nested, no token (rc=$rcs): $out"
out=$(QARGI_NESTED=1 orph --plan 000000000000 --approved "go"); rcs=$?
{ [ $rcs != 0 ] && [ -d "$OS/qargi-run.AAAAAA" ] && [ -d "$OS/qargi-run.BBBBBB" ]; } && ok "and a wrong token removes nothing under QARGI_NESTED either" || no "nested, wrong token (rc=$rcs): $out"
out=$(orph --days 4); tok4=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
{ grep -q "^orphan $OS/qargi-run.AAAAAA" <<<"$out" && ! grep -q "^orphan $OS/qargi-run.BBBBBB" <<<"$out" && grep -q "^kept $OS/qargi-run.BBBBBB (3d old): named by no registry, but" <<<"$out" && [ "$tok4" != "$tok" ]; } \
  && ok "--days 4 lists only what is older than 4 days, with its own token" || no "days 4: $out"
out=$(orph --days 4 --plan "$tok" --approved "go"); rcs=$?
{ [ $rcs != 0 ] && [ -d "$OS/qargi-run.AAAAAA" ]; } && ok "the token of another plan is refused" || no "token of another plan (rc=$rcs): $out"
mkorph CCCCCC 9                                                                # a new orphan after the plan: the plan changed
out=$(orph --plan "$tok" --approved "go"); rcs=$?
{ [ $rcs != 0 ] && grep -q "the plan changed" <<<"$out" && [ -d "$OS/qargi-run.AAAAAA" ] && [ -d "$OS/qargi-run.CCCCCC" ]; } && ok "a directory that appeared since the plan changes it: nothing is removed" || no "plan changed (rc=$rcs): $out"
out=$(orph); tok=$(sed -n 's/^plan token: \([0-9a-f]*\) .*/\1/p' <<<"$out")
out=$(orph --plan "$tok" --approved "the owner said go"); rcs=$?
{ [ $rcs = 0 ] && grep -q "^removed $OS/qargi-run.AAAAAA\$" <<<"$out" && grep -q "^removed $OS/qargi-run.BBBBBB\$" <<<"$out" && grep -q "^removed $OS/qargi-run.CCCCCC\$" <<<"$out" \
  && grep -q "removed 3 orphaned director" <<<"$out" && [ ! -e "$OS/qargi-run.AAAAAA" ] && [ ! -e "$OS/qargi-run.BBBBBB" ] && [ ! -e "$OS/qargi-run.CCCCCC" ]; } \
  && ok "with the token and the words, the orphans older than the limit are removed" || no "orphans apply (rc=$rcs): $out"
{ [ -d "$OLT" ] && [ -d "$OS/qargi-run.NEWNEW" ] && [ -d "$OS/qargi-run.FRESHF" ] && [ -L "$OS/qargi-run.LINKED" ] && [ -f "$T/victim/keep" ] && [ -f "$OS/qargi-run.AFILES" ] && [ -d "$OGT" ] && [ -d "$OL" ]; } \
  && ok "a live run's directory, a named one, a recent one, a link and a file are left alone" || no "orphans left alone: $(ls -A "$OS")"
jq -e 'select(.verb == "local:clean-orphans" and .approved == "the owner said go")' "$T/s/audit.log" >/dev/null 2>&1 && ok "the removal is in the audit log with the words" || no "audit: $(tail -2 "$T/s/audit.log" 2>&1)"
out=$(orph); grep -q "plan: nothing to remove" <<<"$out" && ok "and the next plan is empty" || no "second plan: $out"
for bad in "--orphans --scratch $T/os-scr" "--orphans $OL" "--orphans --discard" "--orphans --applied" "--orphans --stale 5" "--orphans --yes" "--orphans --days 0" "--orphans --days x" "--days 3" "--plan abc" "--approved go"; do
  # shellcheck disable=SC2086
  out=$(QARGI_RUN_TMP=$OS ./bin/qargi local clean $bad 2>&1); rcs=$?
  [ $rcs = 2 ] && [ -d "$OLT" ] && ok "clean $bad is a usage error" || no "clean $bad (rc=$rcs): $out"
done
[ "$SHM0" = "$(real_runs)" ] && ok "the tests listed and removed only in the fake parent: the real parent is as it was" || no "the real parent changed"
./bin/qargi local clean "$OL" --discard >/dev/null 2>&1; rm -rf "$OS"
exit $fail
