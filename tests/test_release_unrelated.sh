#!/usr/bin/env bash
# A master that shares no history with develop (one parentless snapshot commit): `release start` and `status` say so, `finish` refuses with the
# fix, `push` joins the history of master in its plan (a merge keeping the release tree, covered by the plan token), and the finish after it
# is an ordinary --no-ff merge. A repository whose histories are related gets no extra commit.
# Run: tests/test_release_unrelated.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s TMPDIR=$T/tmp GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://github.com/acme/unrel/pull/1;; *"pr checks"*) printf 'suite\tpass\t1m\turl\n';; *"release view"*) echo "release not found" >&2; exit 1;; esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh

# mk NAME unrelated|related: a project with develop, a master and an origin. unrelated: master is a parentless snapshot commit (its tree
# differs from develop's by a file the release does not have); related: master is where develop began.
mk() {
  local R=$T/$1
  git init -q -b develop "$R"
  echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a change\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one
  if [ "$2" = unrelated ]; then
    echo old > "$R/OLD.txt"; git -C "$R" add OLD.txt
    git -C "$R" branch master "$(git -C "$R" commit-tree "$(git -C "$R" write-tree)" -m snapshot)"
    git -C "$R" rm -q --cached OLD.txt; rm "$R/OLD.txt"
  else git -C "$R" branch master; fi
  echo more > "$R/more.txt"; git -C "$R" add more.txt && git -C "$R" commit -q -m two
  git -C "$R" clone -q --bare "$R" "$T/$1.git" && git -C "$R" remote add origin "$T/$1.git" && git -C "$R" fetch -q origin
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/unrel.git", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
}
mk un unrelated; mk rel related
U=$T/un; N=$T/rel
git -C "$U" merge-base master develop >/dev/null 2>&1 && no "the fixture's master shares history with develop" || ok "the fixture: master and develop have no merge base"

# --- unrelated: start says so, with the fix; status warns
export QARGI_PROJECT=un
$REL verify 0.2.0 >/dev/null 2>&1 || no "verify"
out=$($REL start 0.2.0 --date 2026-01-02 2>&1); rc=$?
[ $rc = 0 ] && grep -q "note: master and release/0.2.0 share no history (no merge base" <<<"$out" && grep -q "qargi release push 0.2.0 joins the history of master first" <<<"$out" && ok "start says master has no merge base and what push does" || no "start: rc=$rc $out"
out=$($REL status 0.2.0 2>&1)
grep -q "^warning: master and release/0.2.0 share no history" <<<"$out" && ok "status warns" || no "status: $out"
n0=$(git -C "$U" rev-list --count develop..release/0.2.0); [ "$n0" = 1 ] && ok "start made the version commit only" || no "start made $n0 commits"

# --- finish before the join refuses with the fix and changes nothing
m0=$(git -C "$U" rev-parse master)
out=$($REL finish 0.2.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "share no history" <<<"$out" && grep -q "Run qargi release push 0.2.0" <<<"$out" && ! grep -q "fatal\|plan token" <<<"$out" && ok "finish refuses before the join and names the fix" || no "finish before the join: rc=$rc $out"

# --- push: the plan lists the join; the token covers it
out=$($REL push 0.2.0 2>&1); t=$(tok <<<"$out")
grep -q "have no merge base" <<<"$out" && grep -q "join the history of master: merge master into the release branch keeping the release tree (-s ours --allow-unrelated-histories)" <<<"$out" && ok "the push plan has the join line" || no "push plan: $out"
h0=$(git -C "$U" rev-parse release/0.2.0); tree0=$(git -C "$U" rev-parse 'release/0.2.0^{tree}')
git -C "$U" update-ref refs/heads/master "$(git -C "$U" commit-tree "$(git -C "$U" rev-parse 'master^{tree}')" -p master -m moved)" master
out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(git -C "$U" rev-parse release/0.2.0)" = "$h0" ] && ok "a token made before master moved is refused; the branch did not move" || no "stale token: rc=$rc $out"
git -C "$U" update-ref refs/heads/master "$m0"
out=$($REL push 0.2.0 2>&1); t=$(tok <<<"$out")
: > "$T/gh.log"
out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
h1=$(git -C "$U" rev-parse release/0.2.0)
[ $rc = 0 ] && [ "$h1" != "$h0" ] && grep -q "joined the history of master" <<<"$out" && ok "push applied the join" || no "push: rc=$rc $out"
[ "$(git -C "$U" rev-parse "$h1^{tree}")" = "$tree0" ] && ok "the tree of the branch is unchanged by the join" || no "the join changed the tree"
[ "$(git -C "$U" rev-parse "$h1^1")" = "$h0" ] && [ "$(git -C "$U" rev-parse "$h1^2")" = "$m0" ] && ok "the join commit merges the branch and master" || no "parents of the join: $(git -C "$U" log -1 --format=%P "$h1")"
[ "$(git -C "$U" rev-list --count --first-parent "$h0..$h1")" = 1 ] && [ "$(git -C "$U" log -1 --format=%s "$h1")" = "Join the history of master" ] && ok "one join commit, after the version bump" || no "commits added: $(git -C "$U" log --first-parent --format=%s "$h0..$h1")"
git -C "$U" merge-base master release/0.2.0 >/dev/null 2>&1 && ok "master and the branch have a merge base now" || no "still no merge base"
[ "$(git -C "$T/un.git" rev-parse refs/heads/release/0.2.0)" = "$h1" ] && grep -q "pr create --base master --head release/0.2.0" "$T/gh.log" && ok "the joined head is what was pushed and the pull request opened" || no "origin/gh: $(git -C "$T/un.git" rev-parse refs/heads/release/0.2.0) $(cat "$T/gh.log")"
out=$($REL status 0.2.0 2>&1); ! grep -q "share no history" <<<"$out" && ok "status no longer warns" || no "status after: $out"
out=$($REL push 0.2.0 2>&1); ! grep -q "join the history" <<<"$out" && ok "a second push plan has no join" || no "second push plan: $out"

# --- the finish is an ordinary --no-ff merge
out=$($REL finish 0.2.0 2>&1); t=$(tok <<<"$out")
! grep -q "fatal\|no merge base\|share no history" <<<"$out" && grep -Eq "files changed: [0-9]+ file" <<<"$out" && ok "the finish plan names the files" || no "finish plan: $out"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
nm=$(git -C "$U" rev-parse master)
[ $rc = 0 ] && [ "$(git -C "$U" rev-parse "$nm^1")" = "$m0" ] && [ "$(git -C "$U" rev-parse "$nm^2")" = "$h1" ] && [ "$(git -C "$U" rev-parse "$nm^{tree}")" = "$tree0" ] && git -C "$U" rev-parse -q --verify refs/tags/0.2.0 >/dev/null \
  && ok "master is a --no-ff merge of the joined branch, tagged, with the release tree" || no "finish: rc=$rc $out"
[ -z "$(git -C "$U" ls-tree --name-only master OLD.txt)" ] && ok "the snapshot's own file is not kept: the release tree wins" || no "OLD.txt is still on master"
git -C "$U" merge-base --is-ancestor "$h1" develop && ok "develop has the release" || no "develop lacks the release"

# --- a join that would change the tree is refused and undone (a hook that edits the merge)
$REL verify 0.3.0 >/dev/null 2>&1
git -C "$U" update-ref -d refs/heads/master
git -C "$U" branch master "$(git -C "$U" commit-tree "$(git -C "$U" rev-parse 'develop^{tree}')" -m snapshot2)"
$REL start 0.3.0 --allow-empty-notes >/dev/null 2>&1 || no "start 0.3.0: $($REL start 0.3.0 2>&1)"
mkdir -p "$T/shim"; realgit=$(command -v git); shim=$T/shim/git
cat > "$shim" <<G
#!/usr/bin/env bash
"$realgit" "\$@" || exit \$?
case " \$* " in *" -s ours "*) d=\$2; echo changed > "\$d/evil.txt"; "$realgit" -C "\$d" add evil.txt; "$realgit" -C "\$d" commit -q --amend --no-edit;; esac
G
chmod +x "$shim"
h0=$(git -C "$U" rev-parse release/0.3.0)
t=$($REL push 0.3.0 | tok); out=$(PATH=$T/shim:$PATH $REL push 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "would change the tree" <<<"$out" && [ "$(git -C "$U" rev-parse release/0.3.0)" = "$h0" ] && ! git -C "$T/un.git" rev-parse -q --verify refs/heads/release/0.3.0 >/dev/null && ok "a join that changes the tree is refused: nothing moved, nothing pushed" || no "tree check: rc=$rc $out"
[ -z "$(find "$T/s" -maxdepth 1 -name 'release-wt.*')" ] && ok "no temporary worktree is left" || no "left: $(find "$T/s" -maxdepth 1 -name 'release-wt.*')"

# --- a repository with related histories is unchanged: no extra commit, no join in the plan, no note
export QARGI_PROJECT=rel
$REL verify 0.2.0 >/dev/null 2>&1
out=$($REL start 0.2.0 --date 2026-01-02 2>&1); ! grep -q "share no history" <<<"$out" && ok "start has no note in a normal repository" || no "normal start: $out"
out=$($REL push 0.2.0 2>&1); t=$(tok <<<"$out")
! grep -q "join the history\|no merge base" <<<"$out" && ok "the push plan has no join in a normal repository" || no "normal push plan: $out"
h0=$(git -C "$N" rev-parse release/0.2.0)
out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$N" rev-parse release/0.2.0)" = "$h0" ] && [ "$(git -C "$N" rev-list --count develop..release/0.2.0)" = 1 ] && ok "push added no commit" || no "normal push: rc=$rc $out"
t=$($REL finish 0.2.0 | tok); out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$N" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && [ "$(git -C "$N" rev-parse master^2)" = "$h0" ] && ok "the normal finish is unchanged" || no "normal finish: rc=$rc $out"

rm -rf "$T"
exit $fail
