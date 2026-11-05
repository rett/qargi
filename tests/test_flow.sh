#!/usr/bin/env bash
# The git-flow verbs (qargi feature, qargi release) on a throwaway repository with a bare origin and a fake gh.
# Run: tests/test_flow.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
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
grep -q "both changed" <<<"$out" && no "the d2 refusal named files although none overlap" || ok "a feature behind develop with no file both changed gets the plain refusal, not the list"
$F sync d2 >/dev/null 2>&1; $F verify d2 >/dev/null 2>&1; t=$($F finish d2 | tok); $F finish d2 --plan "$t" --approved go >/dev/null 2>&1 && ok "after sync and a fresh run it lands" || no "d2 after sync"
[ "$(jq -r .sha "$T/s/releases/app-develop.json")" = "$(git -C "$R" rev-parse develop)" ] && ok "the feature's run carries over to develop's new head" || no "no carry-over"
t=$($F finish d2 2>&1 | tok); $F start e1 >/dev/null 2>&1; $F verify e1 >/dev/null 2>&1
a1=$($F finish e1 | tok); $F finish e1 --keep --plan "$a1" --approved go >/dev/null 2>&1 && no "--keep applied with a plan made without it" || ok "the plan covers --keep"
$F finish e1 --keep >/dev/null 2>&1; git -C "$R" branch -D feature/e1 >/dev/null 2>&1
# behind develop with a file both sides changed: finish refuses before it makes a plan, names the files and sync, and changes nothing
$F start g1 >/dev/null 2>&1; $F start g2 >/dev/null 2>&1
for n in g1 g2; do w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "feature/$n"; echo "$n" > "$w/shared-g.txt"; echo "$n" > "$w/own-$n.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "$n"; git -C "$R" worktree remove --force "$w"; done
$F verify g1 >/dev/null 2>&1; $F verify g2 >/dev/null 2>&1; t=$($F finish g1 | tok); $F finish g1 --plan "$t" --approved go >/dev/null 2>&1
dg=$(git -C "$R" rev-parse develop); gg=$(git -C "$R" rev-parse feature/g2)
out=$($F finish g2 2>&1); rc=$?
[ $rc = 1 ] && grep -q "^  shared-g.txt$" <<<"$out" && ! grep -q "own-g" <<<"$out" && grep -q "qargi feature sync g2 first" <<<"$out" && ok "finish of a feature behind develop that shares a changed file refuses (exit 1), lists that file and says to sync first" || no "overlap refusal rc=$rc: $out"
t=$(tok <<<"$out"); [ -z "$t" ] && [ "$(git -C "$R" rev-parse develop)" = "$dg" ] && [ "$(git -C "$R" rev-parse feature/g2)" = "$gg" ] && ok "and no plan is made and nothing moved" || no "overlap refusal changed something"
git -C "$R" branch -D feature/g2 >/dev/null 2>&1

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
# --- refusals exit non-zero; what is pushed is read from the live remote, not from stale tracking refs
R3=$T/app3; O3=$T/origin3.git; U3=file://$T/origin3.git; git init -q -b master "$R3"; git init -q --bare "$O3"
echo 0.1.0 > "$R3/VERSION"; git -C "$R3" add -A && git -C "$R3" commit -q -m one && git -C "$R3" branch develop && git -C "$R3" remote add origin "$O3" && git -C "$R3" push -q origin master develop
git -C "$R3" checkout -q -b parked
jq -n --arg p "$R3" '{schema:1, project:"app3", methodology:"gitflow", repo:{url:"https://github.com/acme/app3", path:$p, long_lived:["master","develop"]}}' > "$T/c/projects/app3.json"
export QARGI_PROJECT=app3
$F start v1 >/dev/null 2>&1
out=$($F verify v1 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no test_command" <<<"$out" && ok "feature verify with no test_command refuses with a non-zero exit" || no "feature verify refusal rc=$rc: $out"
out=$($REL verify 0.1.1 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no test_command" <<<"$out" && ok "release verify with no test_command refuses with a non-zero exit" || no "release verify refusal rc=$rc: $out"
$F verify nosuch >/dev/null 2>&1; rc1=$?; $REL verify 0.1.1 --hotfix >/dev/null 2>&1; rc2=$?
[ $rc1 != 0 ] && [ $rc2 != 0 ] && ok "the other verify refusals (no branch, no test_command) exit non-zero too" || no "refusals rc=$rc1,$rc2"
jq '.test_command = "false"' "$T/c/projects/app3.json" > "$T/c/projects/app3.new" && mv "$T/c/projects/app3.new" "$T/c/projects/app3.json"
$F verify v1 >/dev/null 2>&1; rc1=$?; $REL verify 0.1.1 >/dev/null 2>&1; rc2=$?
[ $rc1 = 1 ] && [ $rc2 = 1 ] && ok "a suite that fails keeps its exit code (1)" || no "failing suite rc=$rc1,$rc2"
jq '.test_command = "true"' "$T/c/projects/app3.json" > "$T/c/projects/app3.new" && mv "$T/c/projects/app3.new" "$T/c/projects/app3.json"
# develop is sent to origin by a file:// URL (not the remote's own), so refs/remotes/origin/develop stays where it was: only the live remote knows
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R3" worktree add -q --detach "$w" develop; echo more > "$w/more.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "pushed develop"
git -C "$R3" update-ref refs/heads/develop "$(git -C "$w" rev-parse HEAD)"; git -C "$R3" worktree remove --force "$w"
git -C "$R3" push -q "$U3" develop; d3=$(git -C "$R3" rev-parse --short develop)
[ "$(git -C "$R3" rev-parse origin/develop)" != "$(git -C "$R3" rev-parse develop)" ] && ok "(setup) the tracking ref of origin/develop is stale" || no "setup: tracking ref is fresh"
out=$($F status v1 2>&1)
grep -q "origin develop: remote $d3, local $d3 (same)" <<<"$out" && ok "feature status reads the live remote: develop is pushed" || no "feature status: $out"
grep -q "origin feature/v1: not on origin" <<<"$out" && ok "and says a feature branch is not on origin" || no "feature status v1: $out"
git -C "$R3" push -q "$U3" develop:refs/heads/feature/v1
git -C "$R3" update-ref refs/heads/feature/v1 "$(git -C "$R3" rev-parse develop~1)"
out=$($F status v1 2>&1)
grep -q "origin feature/v1: remote $d3, local .* (local is 0 ahead, 1 behind)" <<<"$out" && ok "a branch that differs shows both tips and the distance" || no "feature status differs: $out"
$REL verify 0.1.1 >/dev/null 2>&1
out=$($REL start 0.1.1 --allow-empty-notes 2>&1; $REL push 0.1.1 2>&1)
grep -q "origin release/0.1.1: not on origin" <<<"$out" && ok "the release push plan says where the branch is on origin" || no "release push plan: $out"
git -C "$R3" push -q "$U3" release/0.1.1; r3=$(git -C "$R3" rev-parse --short release/0.1.1)
out=$($REL status 0.1.1 2>&1)
grep -q "origin release/0.1.1: remote $r3, local $r3 (same)" <<<"$out" && grep -q "origin develop: remote $d3, local $d3 (same)" <<<"$out" && ok "release status reads the live remote for the branch and for develop" || no "release status: $out"
out=$($REL finish 0.1.1 2>&1)
grep -q "origin master: remote" <<<"$out" && grep -q "origin develop: remote $d3" <<<"$out" && ok "the release finish plan shows the live remote tips" || no "release finish plan: $out"
git -C "$R3" remote set-url origin "$T/nonexistent.git"
out=$($F status v1 2>&1); rc=$?
[ $rc = 0 ] && grep -q "origin develop: remote not checked (" <<<"$out" && ok "an unreachable origin is reported as 'remote not checked (reason)' and status still succeeds" || no "unreachable feature status rc=$rc: $out"
out=$($REL status 0.1.1 2>&1); rc=$?
[ $rc = 0 ] && grep -q "remote not checked (" <<<"$out" && ok "so does release status" || no "unreachable release status rc=$rc: $out"
out=$($F start unreach 2>&1); rc=$?
[ $rc = 0 ] && grep -q "remote not checked (" <<<"$out" && git -C "$R3" rev-parse -q --verify refs/heads/feature/unreach >/dev/null && ok "an unreachable origin does not stop feature start (it says so)" || no "unreachable start rc=$rc: $out"
git -C "$R3" remote set-url origin "$O3"

# --- feature start refuses a name that origin already has (asked live), unless the local branch exists
git -C "$R3" push -q "$U3" develop:refs/heads/feature/theirs
! git -C "$R3" rev-parse -q --verify refs/remotes/origin/feature/theirs >/dev/null && ok "(setup) feature/theirs is on origin and not in the tracking refs" || no "setup: theirs is tracked"
out=$($F start theirs 2>&1); rc=$?
[ $rc != 0 ] && grep -q "origin already has feature/theirs" <<<"$out" && ! git -C "$R3" rev-parse -q --verify refs/heads/feature/theirs >/dev/null && ok "feature start refuses a branch that exists only on origin and creates nothing" || no "start theirs rc=$rc: $out"
out=$($F start v1 2>&1); rc=$?
[ $rc != 0 ] && grep -q "feature/v1 exists already" <<<"$out" && ok "an existing local branch keeps its message even when origin has it too" || no "start v1 rc=$rc: $out"
git -C "$R3" fetch -q origin; git -C "$R3" push -q "$U3" --delete feature/theirs
out=$($F start theirs 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R3" rev-parse -q --verify refs/heads/feature/theirs >/dev/null && ok "a stale tracking ref of a branch that is gone from origin does not block the start" || no "start after delete rc=$rc: $out"
# --- the parking branch: the main checkout rests on it, qargi moves develop under it and fast-forwards it
R5=$T/app5; O5=$T/origin5.git; git init -q -b master "$R5"; git init -q --bare "$O5"
echo 0.1.0 > "$R5/VERSION"; git -C "$R5" add -A && git -C "$R5" commit -q -m one && git -C "$R5" branch develop && git -C "$R5" remote add origin "$O5" && git -C "$R5" push -q origin master develop
git -C "$R5" checkout -q develop
jq -n --arg p "$R5" '{schema:1, project:"app5", methodology:"gitflow", repo:{url:"https://github.com/acme/app5", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app5.json"
export QARGI_PROJECT=app5
feat() { # name: a verified feature with one commit
  $F start "$1" >/dev/null 2>&1; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R5" worktree add -q "$w" "feature/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "feature $1"; git -C "$R5" worktree remove --force "$w"; $F verify "$1" >/dev/null 2>&1
}
feat p1; t=$($F finish p1 | tok)
out=$($F finish p1 --plan "$t" --approved go 2>&1) && no "develop was moved under the main checkout" || { grep -q "git -C $R5 switch -c scratch develop" <<<"$out" && ok "a branch held by the main checkout is refused with the parking branch to switch to" || no "message: $out"; }
out=$($F park 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R5" branch --show-current)" = scratch ] && [ "$(git -C "$R5" rev-parse scratch)" = "$(git -C "$R5" rev-parse develop)" ] && ok "park creates the parking branch at develop and checks it out in the main checkout" || no "park rc=$rc: $out"
echo wip > "$R5/wip.txt"
out=$($F park 2>&1) && no "park accepted a dirty tree" || { grep -q "uncommitted changes" <<<"$out" && ok "park refuses a dirty main checkout" || no "dirty message: $out"; }
rm "$R5/wip.txt"
git -C "$R5" switch -q develop; git -C "$R5" switch -q -c other; git -C "$R5" switch -q scratch
git -C "$R5" commit -q --allow-empty -m "kept on scratch"
out=$($F park 2>&1) && no "park discarded commits of the parking branch" || { grep -q "kept on scratch" <<<"$out" && grep -q "agent task" <<<"$out" && ok "park refuses a parking branch with commits develop lacks, lists them and says what to do" || no "ahead message: $out"; }
[ "$(git -C "$R5" log -1 --format=%s scratch)" = "kept on scratch" ] && ok "and the branch is untouched" || no "scratch changed"
git -C "$R5" switch -q other
out=$($F finish p1 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q "parking branch scratch: not advanced (the main checkout is on other)" <<<"$out" && ok "after a finish, a main checkout elsewhere gets one line saying the parking branch was left" || no "finish rc=$rc: $out"
git -C "$R5" switch -q scratch
feat p2; t=$($F finish p2 | tok)
out=$($F finish p2 --plan "$t" --approved go 2>&1)
grep -q "parking branch scratch: not advanced (scratch has 1 commit(s) that develop lacks)" <<<"$out" && ok "a parking branch with commits of its own is not advanced (and the line says so)" || no "ahead finish: $out"
git -C "$R5" reset -q --hard develop
feat p3; t=$($F finish p3 | tok); d_old=$(git -C "$R5" rev-parse develop)
echo dirty > "$R5/dirty.txt"
out=$($F finish p3 --plan "$t" --approved go 2>&1)
grep -q "parking branch scratch: not advanced (the main checkout has uncommitted changes)" <<<"$out" && [ "$(git -C "$R5" rev-parse scratch)" = "$d_old" ] && ok "a dirty main checkout is not touched" || no "dirty finish: $out"
rm "$R5/dirty.txt"; git -C "$R5" merge -q --ff-only develop
feat p4; t=$($F finish p4 | tok)
out=$($F finish p4 --plan "$t" --approved go 2>&1)
grep -q "parking branch scratch: fast-forwarded to develop" <<<"$out" && [ "$(git -C "$R5" rev-parse scratch)" = "$(git -C "$R5" rev-parse develop)" ] && [ "$(git -C "$R5" branch --show-current)" = scratch ] && [ -z "$(git -C "$R5" status --porcelain)" ] && ok "after a finish, a clean main checkout on the parking branch is fast-forwarded to develop" || no "ff finish: $out"
[ -z "$(git -C "$O5" for-each-ref refs/heads/scratch)" ] && ok "the parking branch is never pushed" || no "scratch pushed"
$F park >/dev/null 2>&1 && jq '.repo.parking_branch = "rest"' "$T/c/projects/app5.json" > "$T/c/projects/app5.new" && mv "$T/c/projects/app5.new" "$T/c/projects/app5.json" && $F park >/dev/null 2>&1 && [ "$(git -C "$R5" branch --show-current)" = rest ] && ok "repo.parking_branch names another branch" || no "custom parking branch"
# --- branch lifecycle answers: branches.delete_merged and branches.push_features
R6=$T/app6; O6=$T/origin6.git; git init -q -b master "$R6"; git init -q --bare "$O6"
echo 0.1.0 > "$R6/VERSION"; git -C "$R6" add -A && git -C "$R6" commit -q -m one && git -C "$R6" branch develop && git -C "$R6" remote add origin "$O6" && git -C "$R6" push -q origin master develop
git -C "$R6" checkout -q -b parked
jq -n --arg p "$R6" '{schema:1, project:"app6", methodology:"gitflow", repo:{url:"https://github.com/acme/app6", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app6.json"
export QARGI_PROJECT=app6
setans() { jq "$1" "$T/c/projects/app6.json" > "$T/c/projects/app6.new" && mv "$T/c/projects/app6.new" "$T/c/projects/app6.json"; }
oref() { git -C "$O6" rev-parse -q --verify "refs/heads/$1" 2>/dev/null; }
feat6() { # name: a verified feature with one commit
  $F start "$1" >/dev/null 2>&1; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R6" worktree add -q "$w" "feature/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "feature $1"; git -C "$R6" worktree remove --force "$w"; $F verify "$1" >/dev/null 2>&1
}
$F start never >/dev/null 2>&1
[ -z "$(oref feature/never)" ] && ok "branches.push_features defaults to never: feature start pushes nothing" || no "pushed by default"
setans '.branches={push_features:"when-shared"}'; $F start shared1 >/dev/null 2>&1
[ -z "$(oref feature/shared1)" ] && ok "when-shared: a branch origin does not have is not pushed" || no "when-shared pushed a new branch"
git -C "$R6" push -q origin feature/shared1; task6() { git -C "$R6" branch "agent/$1" "feature/shared1"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R6" worktree add -q "$w" "agent/$1"; echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R6" worktree remove --force "$w"; }
task6 s1; $F merge shared1 agent/s1 >/dev/null 2>&1
[ "$(oref feature/shared1)" = "$(git -C "$R6" rev-parse feature/shared1)" ] && ok "when-shared: a branch origin has is pushed after a merge into it" || no "when-shared did not push"
setans '.branches={push_features:"always"}'; $F start pushed1 >/dev/null 2>&1
[ "$(oref feature/pushed1)" = "$(git -C "$R6" rev-parse feature/pushed1)" ] && ok "always: feature start pushes the new branch" || no "always did not push"
setans '.branches={}'
# default: finish deletes the local branch only; origin keeps its copy
feat6 q1; git -C "$R6" push -q origin feature/q1; t=$($F finish q1 | tok)
$F finish q1 | grep -q "delete origin/" && no "the default plan deletes on origin" || ok "by default the finish plan does not delete the branch on origin"
$F finish q1 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc = 0 ] && ! git -C "$R6" rev-parse -q --verify refs/heads/feature/q1 >/dev/null && [ -n "$(oref feature/q1)" ] && ok "branches.delete_merged local: the local branch goes and origin keeps its copy" || no "default finish rc=$rc"
setans '.branches={delete_merged:"local+remote"}'
feat6 q2; git -C "$R6" push -q origin feature/q2; out=$($F finish q2); t=$(tok <<<"$out")
grep -q "delete origin/feature/q2" <<<"$out" && ok "local+remote: the finish plan shows the deletion on origin" || no "plan: $out"
$F finish q2 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc = 0 ] && [ -z "$(oref feature/q2)" ] && ! git -C "$R6" rev-parse -q --verify refs/heads/feature/q2 >/dev/null && ok "and the finish deletes the branch on origin too" || no "remote delete rc=$rc"
feat6 q3; git -C "$R6" push -q origin feature/q3; out=$($F finish q3); t=$(tok <<<"$out")
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R6" worktree add -q --detach "$w" feature/q3; echo extra > "$w/extra.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "pushed by somebody else"
git -C "$w" push -q origin HEAD:refs/heads/feature/q3; git -C "$R6" worktree remove --force "$w"
$F finish q3 --plan "$t" --approved go >/dev/null 2>&1 && no "a plan made before origin's branch moved was applied" || ok "the plan token covers origin's tip: a branch that moved there is a new plan"
out=$($F finish q3); t=$(tok <<<"$out")
grep -q "has commits the feature lacks" <<<"$out" && ! grep -q "delete origin/feature/q3" <<<"$out" && ok "a branch on origin with commits the feature lacks is not offered for deletion" || no "plan q3: $out"
$F finish q3 --plan "$t" --approved go >/dev/null 2>&1; [ -n "$(oref feature/q3)" ] && ok "and stays on origin" || no "q3 deleted"
feat6 q4; t=$($F finish q4 | tok); $F finish q4 --plan "$t" --approved go >/dev/null 2>&1 && ok "a feature that origin never had finishes with local+remote" || no "q4"
# --- the worktree root: feature start --worktree, finish removes it, a worktree outside the root is flagged
R7=$T/app7; git init -q -b master "$R7"; echo 0.1.0 > "$R7/VERSION"; git -C "$R7" add -A && git -C "$R7" commit -q -m one && git -C "$R7" branch develop
git -C "$R7" checkout -q -b parked
jq -n --arg p "$R7" '{schema:1, project:"app7", methodology:"gitflow", repo:{url:"https://github.com/acme/app7", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app7.json"
export QARGI_PROJECT=app7
out=$($F start w0 --worktree 2>&1)
grep -q "^worktree: $T/s/worktrees/app7/feature/w0\$" <<<"$out" && [ "$(git -C "$T/s/worktrees/app7/feature/w0" branch --show-current)" = feature/w0 ] && ok "feature start --worktree makes the worktree under <state>/worktrees/PROJECT/<branch> by default and prints it" || no "default root: $out"
git -C "$R7" worktree remove "$T/s/worktrees/app7/feature/w0"; git -C "$R7" branch -q -D feature/w0
WR=$T/wtroot; jq --arg r "$WR" '.worktrees={root:$r}' "$T/c/projects/app7.json" > "$T/c/projects/app7.new" && mv "$T/c/projects/app7.new" "$T/c/projects/app7.json"
$F start w1 --worktree --purpose "in a worktree" 2>&1 | grep -q "^worktree: $WR/feature/w1\$" && ok "worktrees.root moves the root" || no "custom root"
mkdir -p "$WR/feature/w4"; out=$($F start w4 --worktree 2>&1) && no "a start over an existing path was accepted" || { grep -q "exists already" <<<"$out" && ! git -C "$R7" rev-parse -q --verify refs/heads/feature/w4 >/dev/null && ok "a path in the way is refused before the branch is made" || no "w4: $out"; }
rmdir "$WR/feature/w4"
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R7" worktree add -q "$w" -b agent/wa develop; echo a > "$w/a.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task wa"; git -C "$R7" worktree remove --force "$w"
$F merge w1 agent/wa >/dev/null 2>&1; rc=$?
[ $rc = 0 ] && [ -f "$WR/feature/w1/a.txt" ] && [ "$(git -C "$WR/feature/w1" rev-parse HEAD)" = "$(git -C "$R7" rev-parse feature/w1)" ] && [ "$(git -C "$WR/feature/w1" branch --show-current)" = feature/w1 ] && ok "a merge into a feature whose worktree is under the root brings the worktree along" || no "merge with worktree rc=$rc"
echo wip > "$WR/feature/w1/wip.txt"
w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R7" worktree add -q "$w" -b agent/wb develop; echo b > "$w/b.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task wb"; git -C "$R7" worktree remove --force "$w"
out=$($F merge w1 agent/wb 2>&1) && no "a merge went under a dirty worktree" || { grep -q "uncommitted changes" <<<"$out" && ok "a dirty worktree of the feature stops a merge into it" || no "dirty merge: $out"; }
$F verify w1 >/dev/null 2>&1
out=$($F finish w1 2>&1) && no "finish planned over a dirty worktree" || { grep -q "uncommitted changes" <<<"$out" && ok "and the finish, before any plan" || no "dirty finish: $out"; }
rm "$WR/feature/w1/wip.txt"
t=$($F finish w1 | tok); out=$($F finish w1 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ ! -e "$WR/feature/w1" ] && ! git -C "$R7" rev-parse -q --verify refs/heads/feature/w1 >/dev/null && git -C "$R7" worktree prune && [ -z "$(git -C "$R7" worktree list | sed -n '2,$p')" ] && ok "feature finish removes the qargi-made worktree of the branch and deletes the branch" || no "finish worktree rc=$rc: $out"
git -C "$R7" cat-file -e develop:a.txt && ok "(and the merge landed)" || no "merge missing"
# a worktree outside the root is flagged by list and status
$F start w5 >/dev/null 2>&1; git -C "$R7" worktree add -q "$T/elsewhere" feature/w5
mkdir -p "$R7/.claude/worktrees"; git -C "$R7" worktree add -q --detach "$R7/.claude/worktrees/runtime" develop
out=$($F list 2>&1)
grep -q "worktree outside the root: $T/elsewhere (feature/w5): mkdir -p $WR/feature && git worktree move $T/elsewhere $WR/feature/w5" <<<"$out" && ok "feature list flags a worktree outside the root with the git worktree move that fixes it" || no "list: $out"
! grep -q "\.claude/worktrees" <<<"$out" && ! grep -q "outside the root: $R7 " <<<"$out" && ok "but not the runtime's own worktrees nor the main checkout" || no "false flag: $out"
$F status w5 2>&1 | grep -q "worktree outside the root: $T/elsewhere" && ok "feature status flags it too" || no "status flag"
mkdir -p "$WR/feature" && git -C "$R7" worktree move "$T/elsewhere" "$WR/feature/w5" && out=$($F list 2>&1) && ! grep -q "outside the root" <<<"$out" && ok "after the move nothing is flagged" || no "after move: $out"
# --- branch prune: a plan and a token for the merged agent/* and feature/* branches and their worktrees
R8=$T/app8; O8=$T/origin8.git; B="$DA branch"; git init -q -b master "$R8"; git init -q --bare "$O8"
echo 0.1.0 > "$R8/VERSION"; git -C "$R8" add -A && git -C "$R8" commit -q -m one && git -C "$R8" branch develop && git -C "$R8" remote add origin "$O8" && git -C "$R8" push -q origin master develop
git -C "$R8" branch scratch develop; git -C "$R8" checkout -q --orphan docs; git -C "$R8" rm -q -rf .; echo d > "$R8/d.md"; git -C "$R8" add -A; git -C "$R8" commit -q -m docs; git -C "$R8" checkout -q -b parked develop
jq -n --arg p "$R8" '{schema:1, project:"app8", methodology:"gitflow", repo:{url:"https://github.com/acme/app8", path:$p, long_lived:["master","develop","docs"], detached:["docs"]}, test_command:"true"}' > "$T/c/projects/app8.json"
export QARGI_PROJECT=app8
task8() { # name [base]: agent/NAME with one commit
  git -C "$R8" branch "agent/$1" "${2:-develop}"; local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R8" worktree add -q "$w" "agent/$1"
  echo "$1" > "$w/$1.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "task $1"; git -C "$R8" worktree remove --force "$w"
}
$F start f1 --worktree >/dev/null 2>&1; task8 ta; task8 tb; $F merge f1 agent/ta >/dev/null 2>&1; $F merge f1 agent/tb >/dev/null 2>&1; $F verify f1 >/dev/null 2>&1
t=$($F finish f1 --keep | tok); $F finish f1 --keep --plan "$t" --approved go >/dev/null 2>&1
task8 open; git -C "$R8" branch agent/fresh develop; $F start f2 >/dev/null 2>&1; $F start f3 >/dev/null 2>&1; task8 tc feature/f3; $F merge f3 agent/tc >/dev/null 2>&1
mkdir -p "$R8/.claude/worktrees"; git -C "$R8" worktree add -q "$R8/.claude/worktrees/rt" agent/tb; git -C "$R8" checkout -q parked 2>/dev/null
git -C "$R8" push -q origin feature/f1 agent/ta agent/open
WT8=$T/s/worktrees/app8/feature/f1
[ -d "$WT8" ] && ok "(setup) feature f1 is finished and kept, with its worktree; ta, tb are in it; tc is in the open f3" || no "setup: $(git -C "$R8" worktree list)"
heads8=$(git -C "$R8" for-each-ref --format='%(refname)' refs/heads | sort | md5sum)
out=$($B prune 2>&1); t=$(tok <<<"$out")
grep -q "delete local feature/f1 (.*merged into develop); remove its worktree $WT8" <<<"$out" && grep -q "delete local agent/ta (.*merged into develop)" <<<"$out" && grep -q "delete local agent/tc (.*merged into feature/f3)" <<<"$out" && ok "the plan lists merged feature and agent branches and the worktree qargi made" || no "plan: $out"
! grep -E "delete .*(agent/open|agent/fresh|feature/f2|feature/f3|scratch|docs|master|develop)( |\$)" <<<"$out" >/dev/null && ok "and not an unmerged branch, a branch at a tip, an open feature, the parking, detached or long-lived branches" || no "over-pruned: $out"
grep -q "kept agent/tb: checked out in .*/.claude/worktrees/rt, which qargi did not make" <<<"$out" && ok "a branch held by a worktree qargi did not make is kept, with the reason" || no "kept: $out"
[ "$(git -C "$R8" for-each-ref --format='%(refname)' refs/heads | sort | md5sum)" = "$heads8" ] && [ -d "$WT8" ] && ok "the plan changes nothing" || no "plan changed something"
$B prune --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong plan token is refused"
$B prune --remote --plan "$t" --approved go >/dev/null 2>&1 && no "a token of the local plan applied the remote one" || ok "the token covers --remote"
out=$($B prune --plan "$t" --approved "prune them" 2>&1); rc=$?
[ $rc = 0 ] && ! git -C "$R8" rev-parse -q --verify refs/heads/feature/f1 >/dev/null && ! git -C "$R8" rev-parse -q --verify refs/heads/agent/ta >/dev/null && ! git -C "$R8" rev-parse -q --verify refs/heads/agent/tc >/dev/null && [ ! -e "$WT8" ] && ok "with the token it deletes the branches and removes the worktree" || no "apply rc=$rc: $out"
for b in agent/open agent/fresh agent/tb feature/f2 feature/f3 scratch docs master develop; do git -C "$R8" rev-parse -q --verify "refs/heads/$b" >/dev/null || no "$b was deleted"; done; ok "every other branch is still there"
[ -n "$(git -C "$O8" for-each-ref refs/heads/agent/ta)" ] && ok "without --remote origin is not touched" || no "origin changed"
git -C "$R8" worktree remove --force "$R8/.claude/worktrees/rt"
out=$($B prune --remote 2>&1); t=$(tok <<<"$out")
grep -q "delete origin/feature/f1" <<<"$out" && grep -q "delete origin/agent/ta" <<<"$out" && ! grep -q "origin/agent/open" <<<"$out" && grep -q "delete local agent/tb" <<<"$out" && ok "--remote plans the merged branches on origin, not the unmerged one, and the local branch whose runtime worktree is gone" || no "remote plan: $out"
out=$($B prune --remote --plan "$t" --approved "and origin" 2>&1); rc=$?
[ $rc = 0 ] && [ -z "$(git -C "$O8" for-each-ref refs/heads/agent/ta refs/heads/feature/f1)" ] && [ -n "$(git -C "$O8" for-each-ref refs/heads/agent/open)" ] && [ -n "$(git -C "$O8" for-each-ref refs/heads/develop)" ] && ok "and deletes them there, leaving the unmerged branch and develop" || no "remote apply rc=$rc: $out"
rm -rf "$T"
exit $fail
