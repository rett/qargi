#!/usr/bin/env bash
# The git-flow verbs (qargi feature, qargi release) on a throwaway repository with a bare origin and a fake gh.
# Run: tests/test_flow.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
# a fake gh: logs the call; 'pr checks' passes unless $T/ci says fail
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr checks"*) [ "\$(cat "$T/ci" 2>/dev/null)" != fail ];; *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
chmod +x "$T/bin/gh"; export PATH=$T/bin:$PATH
R=$T/app; git init -q -b master "$R"; git init -q --bare "$T/origin.git"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked   # the main checkout is on neither long-lived branch
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"; REL="$DA release"
task() { # name: a task branch with one commit, cut from develop (as an applied, verified series would be)
  git -C "$R" branch "agent/$1" develop; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R" worktree remove --force "$w"
}
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
dev0=$(git -C "$R" rev-parse develop)

# --- features: broad, merged into develop once
$F start search >/dev/null 2>&1 && [ "$(git -C "$R" rev-parse feature/search)" = "$dev0" ] && ok "feature start cuts feature/NAME from develop" || no "start"
$F start search >/dev/null 2>&1 && no "a second start was accepted" || ok "an existing feature is not restarted"
$F start master >/dev/null 2>&1 && no "a long-lived name was accepted" || ok "a long-lived name is refused as a feature"
task t1; task t2
$F merge search agent/t1 >/dev/null 2>&1 && $F merge search agent/t2 >/dev/null 2>&1 && ok "verified task branches merge into the feature" || no "merge: $($F merge search agent/t2 2>&1)"
[ "$(git -C "$R" rev-list --merges --count "develop..feature/search")" = 2 ] && ok "each merge is a --no-ff merge commit" || no "merge commits"
[ "$(git -C "$R" rev-parse develop)" = "$dev0" ] && [ "$(git -C "$R" branch --show-current)" = parked ] && [ -z "$(git -C "$R" status --porcelain)" ] && ok "develop and the main checkout are untouched while the feature grows" || no "touched develop"
$F merge search agent/t1 >/dev/null 2>&1 && no "a branch already merged was merged again" || ok "a task already in the feature is refused"
$F finish search >/dev/null 2>&1 && no "finish without a full-suite run" || ok "finish needs a passing whole-suite run at the head"
$F verify search >/dev/null 2>&1 && $F status search | grep -q "full suite: pass at this head" && ok "verify records the run for this head" || no "verify"
task t3; $F merge search agent/t3 >/dev/null 2>&1
$F status search | grep -q "at an older head" && ok "a merge after verify makes the result stale" || no "stale: $($F status search)"
$F finish search >/dev/null 2>&1 && no "finish accepted a stale run" || ok "and finish refuses it"
$F verify search >/dev/null 2>&1
out=$($F finish search 2>&1); t=$(tok <<<"$out")
grep -q "brings 6 commit(s) into develop" <<<"$out" && grep -q "task t1" <<<"$out" && grep -q "files changed: 3 files changed" <<<"$out" && grep -q "    t3.txt" <<<"$out" && ok "the finish plan lists the commits and files being merged" || no "plan content: $out"
[ -n "$t" ] && [ "$(git -C "$R" rev-parse develop)" = "$dev0" ] && ok "the finish plan changes nothing" || no "plan: $out"
$F finish search --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong plan token is refused"
git -C "$R" checkout -q develop
$F finish search --plan "$t" --approved go >/dev/null 2>&1 && no "develop was moved under a working tree" || ok "a branch checked out in the main checkout is not moved"
git -C "$R" checkout -q parked
out=$($F finish search --plan "$t" --approved "go ahead" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-list --parents -n1 develop | wc -w)" = 3 ] && ok "finish merges the feature into develop with --no-ff" || no "finish rc=$rc: $out"
git -C "$R" rev-parse -q --verify refs/heads/feature/search >/dev/null && no "the feature branch remains" || ok "and deletes the feature branch"
[ "$(git -C "$R" rev-parse develop)" = "$(git -C "$T/origin.git" rev-parse develop)" ] && ok "develop is pushed" || no "push"

# --- several features at once: list, overlap, and a conflict is resolved, not lost
$F start c1 --purpose "first theme" >/dev/null 2>&1; $F start c2 --purpose "second theme" >/dev/null 2>&1
for n in c1 c2; do w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "feature/$n"; echo "$n" > "$w/clash.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "$n"; git -C "$R" worktree remove --force "$w"; done
out=$($F list 2>&1)
grep -q "feature/c1: 1 ahead, 0 behind develop; first theme" <<<"$out" && grep -q "overlap feature/c1 / feature/c2: clash.txt" <<<"$out" && ok "list shows each open feature's purpose and the files two of them both change" || no "list: $out"
$F verify c1 >/dev/null 2>&1; t=$($F finish c1 | tok); $F finish c1 --plan "$t" --approved go >/dev/null 2>&1
$F status c2 | grep -q "1 commit(s) ahead of develop, [1-9][0-9]* behind" && ok "after c1 landed, c2 is behind develop" || no "behind: $($F status c2)"
$F sync c2 >/dev/null 2>&1; rc=$?
[ $rc = 3 ] && ok "syncing develop into the feature reports the conflict (exit 3)" || no "sync rc=$rc"
cd2=$(ls -d "$T"/s/conflicts/app-feature-c2-sync 2>/dev/null)
[ -n "$cd2" ] && git -C "$cd2" diff --name-only --diff-filter=U | grep -qx clash.txt && ok "a worktree with the merge in progress is kept to resolve it in" || no "no resolution worktree"
f2=$(git -C "$R" rev-parse feature/c2)
$F sync c2 --resolved >/dev/null 2>&1 && no "an unresolved merge was accepted" || ok "--resolved refuses a merge that is not finished"
[ "$(git -C "$R" rev-parse feature/c2)" = "$f2" ] && ok "and the feature did not move" || no "moved"
echo "c1 and c2" > "$cd2/clash.txt"; git -C "$cd2" add clash.txt; git -C "$cd2" commit -q --no-edit
$F sync c2 --resolved >/dev/null 2>&1 && git -C "$R" merge-base --is-ancestor develop feature/c2 && [ "$(git -C "$R" show feature/c2:clash.txt)" = "c1 and c2" ] && ok "after resolving and committing, --resolved applies exactly that merge" || no "resolved: $($F sync c2 --resolved 2>&1)"
[ ! -d "$cd2" ] && ok "and the resolution worktree is gone" || no "worktree remains"
$F verify c2 >/dev/null 2>&1; t=$($F finish c2 | tok); $F finish c2 --plan "$t" --approved go >/dev/null 2>&1 && [ "$(git -C "$R" show develop:clash.txt)" = "c1 and c2" ] && ok "the resolved feature then lands in develop" || no "finish c2"
git -C "$R" worktree prune; [ -z "$(git -C "$R" worktree list | sed -n '2,$p')" ] && ok "no worktree is left behind" || no "left: $(git -C "$R" worktree list)"
# develop moving on is caught before the finish, not as a surprise conflict: the run must have seen what develop holds
$F start d1 >/dev/null 2>&1; $F start d2 >/dev/null 2>&1
for n in d1 d2; do w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "feature/$n"; echo "$n" > "$w/other-$n.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "$n"; git -C "$R" worktree remove --force "$w"; done
$F verify d1 >/dev/null 2>&1; $F verify d2 >/dev/null 2>&1; t=$($F finish d1 | tok); $F finish d1 --plan "$t" --approved go >/dev/null 2>&1
dd0=$(git -C "$R" rev-parse develop); t=$($F finish d2 | tok)
out=$($F finish d2 --plan "$t" --approved go 2>&1) && no "a feature behind develop was finished" || ok "a feature that does not contain develop is refused (sync first)"
grep -q "feature sync d2" <<<"$out" && [ "$(git -C "$R" rev-parse develop)" = "$dd0" ] && ok "with the way forward named and develop unchanged" || no "message: $out"
$F sync d2 >/dev/null 2>&1; $F verify d2 >/dev/null 2>&1; t=$($F finish d2 | tok); $F finish d2 --plan "$t" --approved go >/dev/null 2>&1 && ok "after sync and a fresh run it lands" || no "d2 after sync"
[ "$(jq -r .sha "$T/s/releases/app-develop.json")" = "$(git -C "$R" rev-parse develop)" ] && ok "the feature's run carries over to develop's new head" || no "no carry-over"
t=$($F finish d2 2>&1 | tok); $F start e1 >/dev/null 2>&1; $F verify e1 >/dev/null 2>&1
a1=$($F finish e1 | tok); $F finish e1 --keep --plan "$a1" --approved go >/dev/null 2>&1 && no "--keep applied with a plan made without it" || ok "the plan covers --keep"
$F finish e1 --keep >/dev/null 2>&1; git -C "$R" branch -D feature/e1 >/dev/null 2>&1

# --- a release
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" develop; echo late > "$w/late.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "a commit straight on develop"; git -C "$R" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"
$REL start 0.2.0 >/dev/null 2>&1 && no "a release started from an unverified develop" || ok "a release does not start before develop's head passed the whole suite"
$REL verify 0.2.0 >/dev/null 2>&1 && ok "verify runs on develop's head before the release exists" || no "verify develop"
echo 'false' > "$T/cmd"; jq '.test_command = "true # changed"' "$T/c/projects/app.json" > "$T/c/projects/app.new" && mv "$T/c/projects/app.new" "$T/c/projects/app.json"
$REL start 0.2.0 >/dev/null 2>&1 && no "a run made with another test command was accepted" || ok "a run made with a different test command no longer counts"
jq '.test_command = "true"' "$T/c/projects/app.json" > "$T/c/projects/app.new" && mv "$T/c/projects/app.new" "$T/c/projects/app.json"
$REL start 0.2.0 --date 2026-01-02 >/dev/null 2>&1 && [ "$(git -C "$R" show release/0.2.0:VERSION)" = 0.2.0 ] && git -C "$R" show release/0.2.0:CHANGELOG.md | grep -q '^## \[0.2.0\] - 2026-01-02' && ok "start cuts release/VERSION; the first commit bumps VERSION and dates the changelog" || no "start: $($REL status 0.2.0 2>&1)"
[ "$(git -C "$R" log -1 --format=%s release/0.2.0)" = "Bumped version number to 0.2.0" ] && [ "$(git -C "$R" rev-parse release/0.2.0~1)" = "$(git -C "$R" rev-parse develop)" ] && ok "it is one commit on develop's head" || no "bump commit"
out=$($REL push 0.2.0); t=$(tok <<<"$out")
! git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "the push plan pushes nothing" || no "pushed on plan"
$REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && grep -q "pr create --base master --head release/0.2.0" "$T/gh.log" && ok "push publishes the branch and opens the pull request into master" || no "push: $(cat "$T/gh.log")"
rb=$(git -C "$R" rev-parse release/0.2.0); w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" release/0.2.0; echo untested > "$w/untested.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "never seen by CI"; git -C "$R" update-ref refs/heads/release/0.2.0 "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"
t=$($REL finish 0.2.0 | tok); $REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && no "finished a head CI never saw" || ok "a head that differs from what was pushed is refused"
git -C "$R" update-ref refs/heads/release/0.2.0 "$rb"
echo fail > "$T/ci"; t=$($REL finish 0.2.0 | tok)
m0=$(git -C "$R" rev-parse master); $REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1 && no "finished with failing checks" || ok "failing CI checks stop the finish"
[ "$(git -C "$R" rev-parse master)" = "$m0" ] && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "and nothing was merged or tagged" || no "partial finish"
rm "$T/ci"
$REL finish 0.2.0 --plan 000000000000 --approved go >/dev/null 2>&1 && no "wrong token" || ok "a wrong plan token is refused"
rs=$(git -C "$R" rev-parse release/0.2.0)
$REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" cat-file -t 0.2.0)" = tag ] && [ "$(git -C "$R" rev-parse "0.2.0^{commit}")" = "$(git -C "$R" rev-parse master)" ] && ok "finish tags master with an annotated tag" || no "tag rc=$rc"
git -C "$R" merge-base --is-ancestor "$rs" develop && git -C "$R" merge-base --is-ancestor "$rs" master && ok "the release is merged into both master and develop" || no "no back-merge"
[ "$(git -C "$R" show master:VERSION)" = 0.2.0 ] && ok "master carries the released version" || no "master VERSION"
! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ! git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "the release branch is deleted locally and on origin" || no "branch kept"
[ "$(git -C "$T/origin.git" rev-parse master)" = "$(git -C "$R" rev-parse master)" ] && git -C "$T/origin.git" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "master, develop and the tag are pushed" || no "push all"
$REL start 0.2.0 >/dev/null 2>&1 && no "a tag that exists was reused" || ok "a released version cannot be started again"

# --- a hotfix goes into the open release branch when there is one; the version conflict the model warns about is resolved
$REL verify 0.3.0 >/dev/null 2>&1; $REL start 0.3.0 --allow-empty-notes >/dev/null 2>&1
$REL start 0.2.1 --hotfix --allow-empty-notes >/dev/null 2>&1 && [ "$(git -C "$R" rev-parse hotfix/0.2.1~1)" = "$(git -C "$R" rev-parse master)" ] && ok "a hotfix is cut from master" || no "hotfix start"
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" hotfix/0.2.1; echo fix > "$w/fix.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "the fix"; git -C "$R" worktree remove --force "$w"
t=$($REL push 0.2.1 --hotfix | tok); $REL push 0.2.1 --hotfix --plan "$t" --approved go >/dev/null 2>&1
d2=$(git -C "$R" rev-parse develop); r2=$(git -C "$R" rev-parse release/0.3.0); m2=$(git -C "$R" rev-parse master)
t=$($REL finish 0.2.1 --hotfix | tok); $REL finish 0.2.1 --hotfix --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc = 3 ] && [ "$(git -C "$R" rev-parse master)" = "$m2" ] && [ "$(git -C "$R" rev-parse release/0.3.0)" = "$r2" ] && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.1 >/dev/null && ok "the version conflict stops the finish with nothing moved and nothing tagged" || no "hotfix conflict rc=$rc"
cd3=$(ls -d "$T"/s/conflicts/app-hotfix-0.2.1-into-release_0.3.0 2>/dev/null)
git -C "$cd3" diff --name-only --diff-filter=U | grep -qx VERSION && ok "the conflicted files are named (VERSION)" || no "files: $(git -C "$cd3" status --short 2>&1)"
echo 0.3.0 > "$cd3/VERSION"; git -C "$cd3" checkout -q --ours CHANGELOG.md 2>/dev/null; git -C "$cd3" add -A; git -C "$cd3" commit -q --no-edit
hout=$($REL finish 0.2.1 --hotfix --resolved --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" cat-file -e release/0.3.0:fix.txt 2>/dev/null && [ "$(git -C "$R" show release/0.3.0:VERSION)" = 0.3.0 ] && [ "$(git -C "$R" rev-parse develop)" = "$d2" ] && ok "resolved, the hotfix lands in the open release branch and not in develop" || no "hotfix resolved rc=$rc: $hout"
git -C "$R" show master:fix.txt >/dev/null 2>&1 && git -C "$R" rev-parse -q --verify refs/tags/0.2.1 >/dev/null && ok "and in master, tagged" || no "hotfix master"

# --- two conflicting merges in one finish are each resolved once; a forgotten --resolved does not destroy a resolution
$REL verify 0.4.0 >/dev/null 2>&1; $REL start 0.4.0 --allow-empty-notes >/dev/null 2>&1
t=$($REL push 0.4.0 | tok); $REL push 0.4.0 --plan "$t" --approved go >/dev/null 2>&1
side() { w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q --detach "$w" "$1"; echo "$2" > "$w/VERSION"; git -C "$w" add -A; git -C "$w" commit -q -m "$2"; git -C "$R" update-ref "refs/heads/$1" "$(git -C "$w" rev-parse HEAD)"; git -C "$R" worktree remove --force "$w"; }
side master master-side; side develop develop-side
t=$($REL finish 0.4.0 | tok)
$REL finish 0.4.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
cm=$T/s/conflicts/app-release-0.4.0-into-master
[ $rc = 3 ] && [ -d "$cm" ] && ok "the first conflict (master) exits 3 with a worktree to resolve it in" || no "master conflict rc=$rc"
echo 0.4.0 > "$cm/VERSION"; git -C "$cm" add -A; git -C "$cm" commit -q --no-edit; msha=$(git -C "$cm" rev-parse HEAD)
$REL finish 0.4.0 --resolved --plan "$t" --approved go >/dev/null 2>&1; rc=$?
cd4=$T/s/conflicts/app-release-0.4.0-into-develop
[ $rc = 3 ] && [ -d "$cd4" ] && [ -f "$cm.done" ] && ok "after resolving master, the develop merge conflicts next and the first resolution is kept" || no "second conflict rc=$rc"
$REL finish 0.4.0 --plan "$t" --approved go >/dev/null 2>&1 && no "a rerun without --resolved went through" || ok "a rerun without --resolved is refused"
[ -d "$cd4" ] && ok "and does not destroy the waiting resolution" || no "resolution destroyed"
echo 0.4.0 > "$cd4/VERSION"; git -C "$cd4" add -A; git -C "$cd4" commit -q --no-edit
fout=$($REL finish 0.4.0 --resolved --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-parse master)" = "$msha" ] && ok "both resolved merges are used, each resolved once" || no "final rc=$rc: $fout"
[ ! -f "$cm.done" ] && [ "$(git -C "$T/origin.git" rev-parse master)" = "$msha" ] && git -C "$T/origin.git" rev-parse -q --verify refs/tags/0.4.0 >/dev/null && ok "pushed together with the tag, and the bookkeeping is cleared" || no "push/bookkeeping"
# a refused push changes nothing (a fresh repository, so no earlier history interferes)
R2=$T/app2; git init -q -b master "$R2"; git init -q --bare "$T/origin2.git"
echo 0.1.0 > "$R2/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R2/CHANGELOG.md"
git -C "$R2" add -A && git -C "$R2" commit -q -m one && git -C "$R2" branch develop && git -C "$R2" remote add origin "$T/origin2.git" && git -C "$R2" push -q origin master develop
git -C "$R2" checkout -q -b parked
jq -n --arg p "$R2" '{schema:1, project:"app2", methodology:"gitflow", repo:{url:"https://github.com/acme/app2", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app2.json"
export QARGI_PROJECT=app2
$REL verify 0.5.0 >/dev/null 2>&1; $REL start 0.5.0 >/dev/null 2>&1; t=$($REL push 0.5.0 | tok); $REL push 0.5.0 --plan "$t" --approved go >/dev/null 2>&1
printf '#!/bin/sh\necho rejected >&2\nexit 1\n' > "$T/origin2.git/hooks/pre-receive"; chmod +x "$T/origin2.git/hooks/pre-receive"
m5=$(git -C "$R2" rev-parse master); t=$($REL finish 0.5.0 | tok)
fout=$($REL finish 0.5.0 --plan "$t" --approved go 2>&1) && no "finished with a rejected push" || ok "a rejected push fails the finish"
grep -q "nothing was changed locally or on origin" <<<"$fout" && ok "and says nothing changed" || no "message: $fout"
[ "$(git -C "$R2" rev-parse master)" = "$m5" ] && ! git -C "$R2" rev-parse -q --verify refs/tags/0.5.0 >/dev/null && git -C "$R2" rev-parse -q --verify refs/heads/release/0.5.0 >/dev/null && ok "nothing moved locally: no moved branch, no tag, the release branch stays" || no "partial state"
[ "$(git -C "$T/origin2.git" rev-parse master)" = "$m5" ] && ok "and nothing reached origin (the push is all or none)" || no "origin changed"
rm "$T/origin2.git/hooks/pre-receive"
fout=$($REL finish 0.5.0 --plan "$t" --approved go 2>&1) && ok "so it can simply be run again" || no "rerun after push failure: $fout"
[ "$(git -C "$T/origin2.git" rev-parse master)" = "$(git -C "$R2" rev-parse master)" ] && git -C "$T/origin2.git" rev-parse -q --verify refs/tags/0.5.0 >/dev/null && ok "and then master and the tag are on origin" || no "after rerun"
rm -rf "$T"
exit $fail
