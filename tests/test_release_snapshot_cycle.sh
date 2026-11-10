#!/usr/bin/env bash
# A whole release on a repository whose master is an unrelated snapshot commit (parentless, no merge base with develop) and whose develop has real history,
# with local bare repositories as origin: release start -> release push (which joins the history of master) -> release finish, each through its plan
# token and approval. Master gets the release merged and tagged, develop gets the merge, origin receives the pushes as fast-forwards only (the bare
# repository refuses a non-fast-forward and logs every ref update), and no earlier commit is lost or rewritten.
# Run: tests/test_release_snapshot_cycle.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s TMPDIR=$T/tmp GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
# stage VERB ARGS: the plan, then the apply with its token; prints the apply's output
stage() { local p t; p=$($REL "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL "$@" --plan "$t" --approved go 2>&1; }
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://github.com/acme/snap/pull/1;; *"pr checks"*) printf 'suite\tpass\t1m\turl\n';; *"release view"*) echo "release not found" >&2; exit 1;; esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh

# the project: develop has real history (a feature merged with --no-ff among plain commits), master is one parentless snapshot of an older tree
R=$T/snap; O=$T/snap.git
git init -q -b develop "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- first\n' > "$R/CHANGELOG.md"; echo a > "$R/a.txt"
git -C "$R" add -A && git -C "$R" commit -q -m "first"
echo old > "$R/snapshot-only.txt"; git -C "$R" add snapshot-only.txt
git -C "$R" branch master "$(git -C "$R" commit-tree "$(git -C "$R" write-tree)" -m "Snapshot of the code")"
git -C "$R" rm -q --cached snapshot-only.txt; rm "$R/snapshot-only.txt"
echo b > "$R/b.txt"; git -C "$R" add b.txt && git -C "$R" commit -q -m "second"
git -C "$R" checkout -q -b feature/x; echo x > "$R/x.txt"; git -C "$R" add x.txt && git -C "$R" commit -q -m "feature x"
git -C "$R" checkout -q develop; git -C "$R" merge -q --no-ff -m "Merge branch 'feature/x' into develop" feature/x; git -C "$R" branch -q -d feature/x
echo c > "$R/c.txt"; git -C "$R" add c.txt && git -C "$R" commit -q -m "third"
git init -q --bare -b develop "$O"
git -C "$O" config receive.denyNonFastForwards true; git -C "$O" config receive.denyDeletes true
git -C "$R" remote add origin "$O"; git -C "$R" push -q origin develop master
# the origin logs every ref update it accepts: old new ref
printf '#!/bin/sh\necho "$2 $3 $1" >> "%s/updates.log"\n' "$T" > "$O/hooks/update"; chmod +x "$O/hooks/update"
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"snap", methodology:"gitflow", repo:{url:"https://github.com/acme/snap.git", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/snap.json"
export QARGI_PROJECT=snap

git -C "$R" merge-base master develop >/dev/null 2>&1 && no "the fixture's master shares history with develop" || ok "the fixture: master is a parentless snapshot, develop has history, no merge base"
[ "$(git -C "$R" rev-list --count develop)" -ge 5 ] && [ "$(git -C "$R" rev-list --count --parents master | wc -l)" = 1 ] && [ -z "$(git -C "$R" rev-list --max-parents=0 master | grep -x "$(git -C "$R" rev-list --max-parents=0 develop)")" ] && ok "develop has $(git -C "$R" rev-list --count develop) commits, master one" || no "fixture shape"
before=$(git -C "$R" rev-list --all | sort)      # every commit there is before the release
m0=$(git -C "$R" rev-parse master); d0=$(git -C "$R" rev-parse develop)
[ "$(git -C "$O" rev-parse master)" = "$m0" ] && [ "$(git -C "$O" rev-parse develop)" = "$d0" ] && ok "origin has master and develop as they are" || no "origin fixture"

# --- start
$REL verify 0.2.0 >/dev/null 2>&1 || no "verify"
out=$(rstart 0.2.0 --date 2026-01-02 2>&1); rc=$?
[ $rc = 0 ] && [ "$(git -C "$R" rev-parse release/0.2.0^)" = "$d0" ] && [ "$(git -C "$R" show release/0.2.0:VERSION)" = 0.2.0 ] && grep -q "share no history" <<<"$out" && ok "start: release/0.2.0 is one version commit on develop, and the note says master has no merge base" || no "start: rc=$rc $out"

# --- push joins the history of master
out=$(stage push 0.2.0); rc=$?
rh=$(git -C "$R" rev-parse release/0.2.0)
[ $rc = 0 ] && grep -q "joined the history of master" <<<"$out" && [ "$(git -C "$R" rev-parse "$rh^2")" = "$m0" ] && ok "push: the branch is now a merge of the release and master" || no "push: rc=$rc $out"
[ "$(git -C "$O" rev-parse refs/heads/release/0.2.0)" = "$rh" ] && ok "push: origin has the joined head" || no "push: origin has $(git -C "$O" rev-parse refs/heads/release/0.2.0)"
[ "$(git -C "$R" rev-parse "$rh^{tree}")" = "$(git -C "$R" rev-parse "$rh^1^{tree}")" ] && ok "push: the join kept the release tree" || no "push: the join changed the tree"

# --- finish: master, develop and the tag, pushed together
out=$(stage finish 0.2.0); rc=$?
[ $rc = 0 ] || no "finish: rc=$rc $out"
nm=$(git -C "$R" rev-parse master); nd=$(git -C "$R" rev-parse develop)
[ "$(git -C "$R" rev-parse "$nm^1")" = "$m0" ] && [ "$(git -C "$R" rev-parse "$nm^2")" = "$rh" ] && [ "$(git -C "$R" rev-parse "$nm^{tree}")" = "$(git -C "$R" rev-parse "$rh^{tree}")" ] && ok "master: a --no-ff merge of the snapshot and the release branch, with the release tree" || no "master: $(git -C "$R" log -1 --format='%P' master)"
[ "$(git -C "$R" rev-parse 'refs/tags/0.2.0^{commit}')" = "$nm" ] && [ "$(git -C "$R" show master:VERSION)" = 0.2.0 ] && ok "master carries the tag 0.2.0 and the version 0.2.0" || no "tag: $(git -C "$R" rev-parse -q --verify refs/tags/0.2.0)"
[ "$(git -C "$R" rev-parse "$nd^1")" = "$d0" ] && [ "$(git -C "$R" rev-parse "$nd^2")" = "$nm" ] && git -C "$R" merge-base --is-ancestor "$rh" develop && ok "develop: a --no-ff merge of the tagged master commit (which holds the release branch) on its old head" || no "develop: $(git -C "$R" log -1 --format='%P' develop)"
[ "$(git -C "$R" show develop:b.txt)" = b ] && git -C "$R" cat-file -e develop:x.txt && git -C "$R" cat-file -e develop:c.txt && ok "develop keeps its own files" || no "develop lost files"
! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "the local release branch is gone" || no "release branch left behind"

# --- nothing was rewritten: every earlier commit is still there, and the old tips are ancestors of the new ones
lost=$(comm -23 <(printf '%s\n' "$before") <(git -C "$R" rev-list --all | sort))
[ -z "$lost" ] && ok "every commit that existed before is still reachable" || no "lost commits: $lost"
git -C "$R" merge-base --is-ancestor "$m0" master && git -C "$R" merge-base --is-ancestor "$d0" develop && git -C "$R" merge-base --is-ancestor "$d0" master && ok "the old master and develop are ancestors of the new ones, and develop's whole history is now in master" || no "old tips are not ancestors"
for c in $(git -C "$R" rev-list "$d0"); do git -C "$R" merge-base --is-ancestor "$c" master || { no "commit ${c:0:7} of develop is not in master"; break; }; done

# --- origin: the same refs, reached by fast-forwards (the bare repository refuses anything else)
[ "$(git -C "$O" rev-parse master)" = "$nm" ] && [ "$(git -C "$O" rev-parse develop)" = "$nd" ] && [ "$(git -C "$O" rev-parse 'refs/tags/0.2.0^{commit}')" = "$nm" ] && ok "origin: master, develop and the tag are what the repository has" || no "origin refs: $(git -C "$O" for-each-ref --format='%(refname) %(objectname:short)')"
bad=''
while read -r old new ref; do
  case $old in 0000000*) continue;; esac       # a new ref (the release branch, the tag)
  git -C "$O" merge-base --is-ancestor "$old" "$new" || bad="$bad $ref"
done < "$T/updates.log"
[ -z "$bad" ] && grep -q " refs/heads/master$" "$T/updates.log" && grep -q " refs/heads/develop$" "$T/updates.log" && ok "origin: every update of an existing ref was a fast-forward (no force push)" || no "origin updates: bad=[$bad] $(cat "$T/updates.log")"

# --- a second release now finds related histories: no join
$REL verify 0.3.0 >/dev/null 2>&1
out=$(rstart 0.3.0 --date 2026-02-03 --allow-empty-notes 2>&1); rc=$?
git -C "$R" merge-base master release/0.3.0 >/dev/null 2>&1 && ok "the next release starts with a merge base to master" || no "0.3.0: master and the branch still have no merge base"
! grep -q "share no history" <<<"$out" && [ $rc = 0 ] && ok "the next release start has no history note" || no "0.3.0 start: rc=$rc $out"
out=$($REL push 0.3.0 2>&1); ! grep -q "join the history\|no merge base" <<<"$out" && ok "the next push plan has no join" || no "0.3.0 push plan: $out"

rm -rf "$T"
exit $fail
