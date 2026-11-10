#!/usr/bin/env bash
# qargi upstream status|review|sync: a fork that follows a local bare repository acting as upstream, with its overlay on develop.
# Run: tests/test_upstream.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d) && [ -n "$T" ] || exit 1   # an empty T would make the helpers below work in the checkout itself
fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s QARGI_PROJECT=app
export GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
J=$T/s/ref-journal.jsonl; Z=0000000000000000000000000000000000000000
UP="$DA upstream"
sha() { git -C "$R" rev-parse -q --verify "$1" 2>/dev/null || echo none; }
# jhas REF-SUFFIX OLD NEW VERB: the journal holds a line for that ref going from OLD to NEW by VERB
jhas() { [ -f "$J" ] && jq -c --arg r "$1" --arg o "$2" --arg n "$3" --arg v "$4" 'select((.ref | endswith($r)) and .old == $o and .new == $n and .verb == $v)' "$J" | grep -q .; }

# --- the upstream: a bare repository fed from a work tree; shared.txt has room for the overlay and upstream to change different lines
U=$T/up; git init -q -b main "$U"; git init -q --bare "$T/up.git"
printf 'a\nb\nc\nd\ne\nf\ng\nh\n' > "$U/shared.txt"; echo lib > "$U/lib.txt"
uc() { git -C "$U" add -A; git -C "$U" commit -q -m "$1"; git -C "$U" push -q "$T/up.git" main:main; }
uc "upstream base"
base=$(git -C "$U" rev-parse main)
# --- the fork: remote 'upstream', master and develop from the upstream base, the branch 'upstream' carrying the upstream line, the overlay on develop
R=$T/app; git init -q -b master "$R"; git -C "$R" remote add upstream "$T/up.git"; git -C "$R" fetch -q upstream
git -C "$R" reset -q --hard upstream/main; git -C "$R" branch develop; git -C "$R" branch upstream; git -C "$R" checkout -q -b parked
dev() { # commit on develop in a worktree: FILE-EDIT-COMMAND MESSAGE
  local w; w=$(mktemp -d "$T/w.XXXXXX") && [ -n "$w" ] || exit 1
  git -C "$R" worktree add -q "$w" develop || exit 1
  (cd "$w" && eval "$1"); git -C "$w" add -A; git -C "$w" commit -q -m "$2"; git -C "$R" worktree remove --force "$w"
}
dev 'sed -i 1s/a/overlay/ shared.txt; echo o > overlay.txt' "overlay"
dev0=$(sha develop); m0=$(sha master)
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop","upstream"]}, test_command:"true",
  upstream:{remote:"upstream", branch:"main"}}' > "$T/c/projects/app.json"
# upstream moves on: one commit touches a file the overlay changed, one does not; a tag that must not be fetched
printf 'i\n' >> "$U/shared.txt"; uc "upstream: shared"; echo x >> "$U/lib.txt"; uc "upstream: lib"
git -C "$U" tag v9; git -C "$U" push -q "$T/up.git" v9
tip=$(git -C "$U" rev-parse main)

# --- answers
jq 'del(.upstream)' "$T/c/projects/app.json" > "$T/a.json"; cp "$T/c/projects/app.json" "$T/keep.json"; cp "$T/a.json" "$T/c/projects/app.json"
out=$($UP status 2>&1); rc=$?
[ $rc != 0 ] && grep -q "upstream.remote" <<<"$out" && ok "a project with no upstream answers is told which to set" || no "no answers: rc=$rc $out"
cp "$T/keep.json" "$T/c/projects/app.json"
jq '.upstream.remote="nosuch"' "$T/keep.json" > "$T/c/projects/app.json"
out=$($UP status 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no remote named nosuch" <<<"$out" && ok "a remote the repository lacks is refused" || no "bad remote: rc=$rc $out"
cp "$T/keep.json" "$T/c/projects/app.json"
$UP frobnicate >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown verb is a usage error (exit 2)" || no "unknown verb"
$UP review --limit 0 >/dev/null 2>&1; [ $? = 2 ] && ok "--limit 0 is a usage error" || no "limit 0"

# --- review and sync read the last fetch; without one they say so
git -C "$R" update-ref -d refs/remotes/upstream/main
out=$($UP review 2>&1); rc=$?
[ $rc != 0 ] && grep -q "not fetched yet" <<<"$out" && ok "review without a fetch says to run status" || no "review unfetched: rc=$rc $out"
out=$($UP sync 2>&1); rc=$?
[ $rc != 0 ] && grep -q "not fetched yet" <<<"$out" && ok "sync without a fetch says to run status" || no "sync unfetched: rc=$rc $out"

# --- status fetches that branch and reports behind and ahead
out=$($UP status 2>&1); rc=$?
[ $rc = 0 ] && grep -q "upstream upstream/main at ${tip:0:7} (fetched); upstream at ${base:0:7}: 2 behind, 0 ahead" <<<"$out" && ok "status fetches and reports 2 behind, 0 ahead" || no "status: rc=$rc $out"
grep -q "upstream: lib" <<<"$out" && grep -q "upstream: shared" <<<"$out" && ok "status lists the new upstream commits" || no "status commits: $out"
[ "$(git -C "$R" rev-parse refs/remotes/upstream/main)" = "$tip" ] && ok "the remote-tracking ref is at the upstream tip" || no "tracking ref"
[ -z "$(git -C "$R" tag)" ] && ok "the fetch brings no tags" || no "tags fetched: $(git -C "$R" tag)"
[ "$(sha upstream)" = "$base" ] && [ "$(sha develop)" = "$dev0" ] && [ "$(sha master)" = "$m0" ] && ok "status moves no local branch" || no "status moved a branch"
[ ! -f "$J" ] && ok "status journals nothing" || no "status journaled: $(cat "$J")"

# --- review: the commits not yet in the branch, their files, and the mark on the ones that touch the overlay
out=$($UP review 2>&1); rc=$?
[ $rc = 0 ] && grep -q "upstream commits not in upstream: 2 " <<<"$out" && grep -q "overlay: 2 file(s) develop changed" <<<"$out" && ok "review counts the commits and the overlay's files" || no "review: rc=$rc $out"
grep -q "upstream: shared  \[overlay: shared.txt\]" <<<"$out" && ok "a commit that touches a file the overlay changed is marked with the file" || no "mark: $out"
grep "upstream: lib" <<<"$out" | grep -q "overlay" && no "a commit that touches no overlay file is marked" || ok "a commit that touches no overlay file is not marked"
grep -q "^      lib.txt$" <<<"$out" && grep -q "^      shared.txt$" <<<"$out" && ok "review lists the files each commit touches" || no "files: $out"
grep -q "^1 of the 2 listed touch a file the overlay changed" <<<"$out" && ok "review sums up the marked commits" || no "summary: $out"
out=$($UP review --limit 1 2>&1)
grep -q "upstream: lib" <<<"$out" && ! grep -q "upstream: shared" <<<"$out" && grep -q "and 1 more (--limit N)" <<<"$out" && ok "--limit N shows the newest N and says how many more" || no "limit: $out"
[ "$(sha upstream)" = "$base" ] && [ ! -f "$J" ] && ok "review changes nothing" || no "review changed something"

# --- sync: a plan and a token, then a fast-forward only
out=$($UP sync 2>&1); rc=$?; t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "fast-forward upstream from ${base:0:7} to upstream/main (${tip:0:7}): 2 commit(s), local only (nothing is pushed, nothing is merged into develop)" <<<"$out" \
  && grep -q "brings 2 commit(s) into upstream" <<<"$out" && ok "the sync plan shows the fast-forward and its commits with a token" || no "plan: rc=$rc $out"
[ "$(sha upstream)" = "$base" ] && [ ! -f "$J" ] && ok "the plan changes nothing" || no "plan moved the branch"
$UP sync --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || ok "a wrong plan token is refused"
out=$(QARGI_NESTED=1 $UP sync --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ "$(sha upstream)" = "$base" ] && ok "sync with no token under QARGI_NESTED is refused, the branch did not move" || no "nested sync, no token: rc=$rc $out"
out=$(QARGI_NESTED=1 $UP sync --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ "$(sha upstream)" = "$base" ] && ok "and a wrong token is refused under QARGI_NESTED too" || no "nested sync, wrong token: rc=$rc $out"
[ "$(sha upstream)" = "$base" ] && ok "and the branch did not move" || no "moved on a wrong token"
git -C "$R" checkout -q upstream
$UP sync --plan "$t" --approved go >/dev/null 2>&1 && no "the branch was moved under the main checkout" || ok "a branch checked out in the main checkout is not moved"
git -C "$R" checkout -q parked
out=$($UP sync --plan "$t" --approved "take them" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(sha upstream)" = "$tip" ] && ok "sync fast-forwards the branch to the upstream tip" || no "sync: rc=$rc $out"
[ "$(sha develop)" = "$dev0" ] && [ "$(sha master)" = "$m0" ] && ok "develop and master are untouched" || no "develop or master moved"
jhas upstream "$base" "$tip" upstream:sync && ok "the move is in the lead's ref journal" || no "journal: $(cat "$J" 2>&1)"
grep -q "next: qargi feature start upstream-${tip:0:7}" <<<"$out" && grep -q "qargi feature merge upstream-${tip:0:7} upstream" <<<"$out" && ok "the next step is a feature that merges the branch, never develop directly" || no "next step: $out"
[ "$(git -C "$T/up.git" rev-parse main)" = "$tip" ] && [ -z "$(git -C "$R" remote | grep -v upstream)" ] && ok "nothing was pushed" || no "pushed"
grep -q "upstream:sync" "$T/s/audit.log" && ok "the audit log has the sync" || no "audit"
out=$($UP sync 2>&1); rc=$?
[ $rc = 0 ] && grep -q "upstream is at upstream/main already" <<<"$out" && [ -z "$(tok <<<"$out")" ] && ok "a branch at the tip has nothing to sync (no plan)" || no "already: rc=$rc $out"
out=$($UP status 2>&1)
grep -q "0 behind, 0 ahead" <<<"$out" && grep -q "nothing new upstream" <<<"$out" && ok "status then says nothing is new" || no "status after sync: $out"

# --- a token is for one plan: after upstream moved on, the old token no longer applies
echo y >> "$U/lib.txt"; uc "upstream: lib again"; tip2=$(git -C "$U" rev-parse main)
$UP status >/dev/null 2>&1
out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "plan changed" <<<"$out" && [ "$(sha upstream)" = "$tip" ] && ok "a token from an earlier plan is refused once upstream moved on" || no "token reuse: rc=$rc $out"
t=$($UP sync | tok); $UP sync --plan "$t" --approved go >/dev/null 2>&1
[ "$(sha upstream)" = "$tip2" ] && ok "a fresh plan and token apply" || no "fresh token"
n=$(wc -l < "$J")

# --- diverged: the branch has a commit of its own, so there is no fast-forward
w=$(mktemp -d "$T/w.XXXXXX") && [ -n "$w" ] || exit 1; git -C "$R" worktree add -q "$w" upstream || exit 1; echo own > "$w/own.txt"; git -C "$w" add -A; git -C "$w" commit -q -m "own commit"; git -C "$R" worktree remove --force "$w"
own=$(sha upstream)
echo z >> "$U/lib.txt"; uc "upstream: lib once more"; tip3=$(git -C "$U" rev-parse main)
out=$($UP status 2>&1)
grep -q "1 behind, 1 ahead" <<<"$out" && grep -q "sync will refuse (not a fast-forward)" <<<"$out" && ok "status shows the branch ahead and warns" || no "status ahead: $out"
out=$($UP sync 2>&1); rc=$?
[ $rc != 0 ] && grep -q "not a fast-forward" <<<"$out" && grep -q "own commit" <<<"$out" && [ -z "$(tok <<<"$out")" ] && ok "sync refuses a branch with commits of its own, names them and prints no token" || no "diverged plan: rc=$rc $out"
t=$(printf '%s\n%s\n%s\n%s\n' app upstream "$own" "$tip3" | sha256sum | cut -c1-12)
out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(sha upstream)" = "$own" ] && [ "$(wc -l < "$J")" = "$n" ] && ok "and with a token it still refuses: the branch and the journal are unchanged" || no "diverged apply: rc=$rc $out"
git -C "$R" branch -q -f upstream "$tip2"

# --- the overlay check runs on a trial merge of the branch into develop, after the fast-forward
jq '.upstream.overlay_check=["sh","-c","test -f overlay.txt && test -f lib.txt && grep -q overlay shared.txt"]' "$T/keep.json" > "$T/c/projects/app.json"
out=$($UP sync 2>&1); t=$(tok <<<"$out")
grep -q "then the overlay check runs on a trial merge of upstream into develop: sh -c" <<<"$out" && ok "the plan names the overlay check" || no "plan overlay: $out"
out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q "overlay check: pass" <<<"$out" && [ "$(sha upstream)" = "$tip3" ] && ok "a passing overlay check: exit 0 after the fast-forward" || no "overlay pass: rc=$rc $out"
[ "$(sha develop)" = "$dev0" ] && git -C "$R" worktree prune && [ -z "$(git -C "$R" worktree list | sed -n '2,$p')" ] && ok "the trial merge touched no branch and left no worktree" || no "trial merge: $(git -C "$R" worktree list)"
jq '.upstream.overlay_check=["false"]' "$T/keep.json" > "$T/c/projects/app.json"
echo w >> "$U/lib.txt"; uc "upstream: lib yet again"; tip4=$(git -C "$U" rev-parse main); $UP status >/dev/null 2>&1
t=$($UP sync | tok); out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "overlay check: fail (false" <<<"$out" && grep -q "the fast-forward stands" <<<"$out" && [ "$(sha upstream)" = "$tip4" ] && ok "a failing overlay check exits 1 and the fast-forward stands" || no "overlay fail: rc=$rc $out"
# a conflict in the trial merge: upstream now changes the line the overlay changed
jq '.upstream.overlay_check=["true"]' "$T/keep.json" > "$T/c/projects/app.json"
sed -i 1s/a/theirs/ "$U/shared.txt"; uc "upstream: first line"; tip5=$(git -C "$U" rev-parse main); $UP status >/dev/null 2>&1
t=$($UP sync | tok); out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "overlay check: not run; merging upstream into develop conflicts in: shared.txt" <<<"$out" && [ "$(sha upstream)" = "$tip5" ] && ok "a trial merge that conflicts names the files and exits 1" || no "overlay conflict: rc=$rc $out"
[ "$(sha develop)" = "$dev0" ] && git -C "$R" worktree prune && [ -z "$(git -C "$R" worktree list | sed -n '2,$p')" ] && ok "and leaves develop and the worktrees alone" || no "conflict leftovers: $(git -C "$R" worktree list)"
cp "$T/keep.json" "$T/c/projects/app.json"

# --- no branch yet: sync creates it at the upstream tip
git -C "$R" branch -q -D upstream
out=$($UP status 2>&1)
grep -q "no local branch upstream yet" <<<"$out" && ok "status says when the branch does not exist yet" || no "status no branch: $out"
out=$($UP review 2>&1); rc=$?
[ $rc != 0 ] && grep -q "no local branch upstream" <<<"$out" && ok "review needs the branch" || no "review no branch: rc=$rc $out"
out=$($UP sync 2>&1); t=$(tok <<<"$out")
grep -q "create upstream at upstream/main (${tip5:0:7})" <<<"$out" && [ -n "$t" ] && ok "the plan says the branch is created" || no "create plan: $out"
out=$($UP sync --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(sha upstream)" = "$tip5" ] && jhas upstream "$Z" "$tip5" upstream:sync && ok "sync creates the branch at the tip and journals the creation" || no "create: rc=$rc $out"

# --- the answer upstream.into names another branch
jq '.upstream.into="vendor"' "$T/keep.json" > "$T/c/projects/app.json"
git -C "$R" branch vendor "$base"
out=$($UP status 2>&1)
grep -q "vendor at ${base:0:7}:" <<<"$out" && ok "upstream.into picks the branch" || no "into: $out"

[ $fail = 0 ] && echo "test_upstream: all passed" || { echo "test_upstream: FAILED"; exit 1; }
