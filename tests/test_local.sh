#!/usr/bin/env bash
# The local never-push barrier on a throwaway repository and remote. Run: tests/test_local.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0
export QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_RUN_TMP=$T
git init -q -b main "$T/r" && git -C "$T/r" -c user.name=t -c user.email=t@example.net commit -q --allow-empty -m one
git init -q --bare "$T/remote.git" && git -C "$T/r" remote add origin "$T/remote.git" && git -C "$T/r" push -q origin main
eval "$(./bin/qargi local prepare --repo "$T/r" --base main --slug demo --scratch "$T" | sed '/^$/,$d' | sed 's/^/export /')"
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
[ "$($GIT -C "$CLONE" branch --show-current)" = agent/demo ] && ok "clone is on agent/demo" || no "branch"
echo x > "$CLONE/f"; $GIT -C "$CLONE" add f && $GIT -C "$CLONE" commit -q -m work && ok "commit through the wrapper"
[ "$($GIT -C "$CLONE" log -1 --format=%an)" = qargi ] && ok "author is qargi" || no "author"
$GIT -C "$CLONE" push origin agent/demo >/dev/null 2>&1 && no "git push origin succeeded" || ok "git push origin fails"
git -C "$CLONE" remote -v | grep -q "$T/r" && no "the clone knows the real repository" || ok "the clone does not know the real repository path"
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && ok "verify passes after a clean run" || no "verify clean"
[ "$(cat "$RUN/ability")" = build ] && ok "the run records its ability (build by default)" || no "ability file"
R2=$(./bin/qargi local prepare --repo "$T/r" --base main --slug rev --scratch "$T" --ability review | sed -n '1,/^$/s/^RUN=//p')
[ "$(cat "$R2/ability")" = review ] && ok "--ability review is recorded for the guard" || no "review ability"
./bin/qargi local prepare --repo "$T/r" --base main --slug bad --scratch "$T" --ability deploy >/dev/null 2>&1 && no "an unknown ability was accepted" || ok "an unknown ability is refused"
git -C "$CLONE" push -q "$T/remote.git" agent/demo 2>/dev/null   # a bypass with plain git
./bin/qargi local verify "$RUN" >/dev/null 2>&1 && no "verify missed a push to the remote" || ok "verify catches a push to the remote"
[ "$(jq -r 'select(.slug=="demo") | .run' "$T/s/local-runs.jsonl")" = "$RUN" ] && [ "$(wc -l < "$T/s/local-runs.jsonl")" = 2 ] && ok "prepare registers each run (one line, run directory, slug, ability, base, start)" || no "registry: $(cat "$T/s/local-runs.jsonl")"
grep -q "$T/r" "$T/s/local-runs.jsonl" && no "the registry names the repository path" || ok "the registry holds no repository path"
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
out=$(./bin/qargi local prepare --repo "$T/r2" --base main --slug c3 --scratch "$T"); C3=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
./bin/qargi local clean "$C3" --discard >/dev/null 2>&1 && [ ! -e "$C3" ] && ok "--discard cleans a run that produced no manifest" || no "discard"
./bin/qargi local clean "$T" >/dev/null 2>&1 && no "clean accepted a directory that is not a run" || ok "clean refuses a directory that prepare did not make"
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
$LC -C "$T/r3" commit -q --allow-empty -m lead-move && git -C "$T/r3" branch agent/other
[ "$(rc "$P1")" = 2 ] && ok "no passing verify yet: the strict comparison applies (exit 2)" || no "strict: a moved branch was accepted"
out=$(mk p2); P2=$(runof <<<"$out")
[ "$(rc "$P2")" = 0 ] && [ -f "$P2/verified" ] && ok "a passing verify records RUN/verified" || no "verified record"
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
git --git-dir="$T/remote.git" update-ref refs/heads/elsewhere "$(git --git-dir="$T/remote.git" rev-parse main)"
[ "$(rc "$P3")" = 2 ] && ok "a remote ref change fails with exit 2 after a passing verify" || no "remote change accepted"
git --git-dir="$T/remote.git" update-ref -d refs/heads/elsewhere
git -C "$T/r3" update-ref refs/remotes/origin/zz HEAD
[ "$(rc "$P3")" = 2 ] && ok "a refs/remotes change fails" || no "refs/remotes change accepted"
git -C "$T/r3" update-ref -d refs/remotes/origin/zz
rm -rf "$C1" "$TM"
# a Claude Code render of the project (packs apply --target claude-code): prepare warns about drift, never fails, never changes the block
git init -q -b main "$T/r4" && $LC -C "$T/r4" commit -q --allow-empty -m one
mkdir -p "$T/c/projects"
jq -n --arg p "$T/r4" '{schema:1,project:"alpha",repo:{url:"https://github.com/example/x",path:$p,long_lived:["main"]},
  roles:{build:{base:"@dispatcher",push:{mode:"none"},model:"claude-sonnet-5-5",effort:"high",apt:[],skills:[]}},
  memory:{memory_store:"",reference_store:""},budget_cents:500}' > "$T/c/projects/alpha.json"
mk4() { ./bin/qargi local prepare --repo "$T/r4" --base main --slug "$1" --scratch "$T" 2>"$T/err"; }
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
out=$(mk4 w0); [ ! -s "$T/err" ] && ok "no render: prepare prints no warning" || no "no render: $(cat "$T/err")"
Q=./bin/qargi
$Q skill new s-w >/dev/null; sed -i "s/^description: .*/description: Use for s-w./" "$T/c/packs/skills/s-w/SKILL.md"
$Q skill seal s-w --plan "$($Q skill seal s-w | tokof)" --approved test >/dev/null
$Q skill link s-w --scope project --project alpha >/dev/null
$Q packs apply --target claude-code alpha --plan "$($Q packs apply --target claude-code alpha | tokof)" --approved test >/dev/null
out=$(mk4 w1); [ -f "$T/s/claude/alpha/MANIFEST.json" ] && [ ! -s "$T/err" ] && ok "a clean render: no warning" || no "clean render: $(cat "$T/err")"
echo tamper >> "$T/s/claude/alpha/.claude/skills/s-w/SKILL.md"
out=$(mk4 w2); rcw=$?
grep -q '^WARNING: the Claude Code render of project alpha' "$T/err" && grep -q 'SKILL.md' "$T/err" && grep -q 'fix: qargi packs apply --target claude-code alpha' "$T/err" && [ $rcw = 0 ] \
  && ok "a drifted render: a WARNING with the findings and the fix, and prepare still succeeds" || no "drift: $rcw $(cat "$T/err")"
blk=$(sed '1,/^TASK-BLOCK PATHS$/d' <<<"$out"); W2=$(runof <<<"$out")
[ "$(sed -n '1p' <<<"$blk")" = "RUN_DIR=$W2" ] && [ "$(wc -l <<<"$blk")" = 6 ] && ! grep -q WARNING <<<"$out" && ok "the paths block is intact and the warning is not in stdout" || no "block: $blk"
rm -rf "$T/s/claude/alpha"; out=$(mk4 w3); [ ! -s "$T/err" ] && ok "no render again: no warning" || no "removed render: $(cat "$T/err")"

# prepare --profile: the resolver is asked before any clone; the run records the profile
Q=./bin/qargi
$Q agent add pj-judge --abilities review >/dev/null 2>&1; $Q agent add pj-forge --abilities build >/dev/null 2>&1
out=$($Q local prepare --repo "$T/r" --base main --slug pf1 --scratch "$T" --role review --profile advisor 2>&1); PR=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
[ "$(cat "$PR/profile" 2>/dev/null)" = advisor ] && grep -qx 'PROFILE=advisor' <<<"$out" && grep -qx 'MEMBER=pj-judge' <<<"$out" && grep -qx 'MODEL=opus' <<<"$out" && grep -q '^EFFORT=.' <<<"$out" \
  && ok "--profile records RUN/profile and prints PROFILE, MEMBER, MODEL, EFFORT" || no "profile: $out"
[ "$(jq -r 'select(.slug=="pf1") | .profile' "$T/s/local-runs.jsonl")" = advisor ] && ok "the run line carries the profile" || no "jsonl profile"
n1=$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l)
out=$($Q local prepare --repo "$T/r" --base main --slug pf2 --scratch "$T" --role build --profile auditor 2>&1); rcp=$?
[ "$rcp" != 0 ] && grep -q 'read-only' <<<"$out" && [ "$(find "$T" -maxdepth 1 -name 'qargi.*' | wc -l)" = "$n1" ] && ! grep -q pf2 "$T/s/local-runs.jsonl" \
  && ok "a profile of the wrong class dies with the resolver's reason and leaves no run directory" || no "class conflict: $rcp $out"
out=$($Q local prepare --repo "$T/r" --base main --slug pf3 --scratch "$T" --role build 2>&1); P3=$(sed -n '1,/^$/s/^RUN=//p' <<<"$out")
grep -qx 'PROFILE=build' <<<"$out" && ! grep -q '^MODEL=' <<<"$out" && [ ! -e "$P3/profile" ] && [ "$(jq -r 'select(.slug=="pf3") | .profile' "$T/s/local-runs.jsonl")" = build ] \
  && ok "without --profile: PROFILE=<role> and nothing else changes" || no "no profile: $out"
exit $fail
