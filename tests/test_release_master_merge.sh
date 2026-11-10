#!/usr/bin/env bash
# `release finish` merges the tagged master merge commit into develop (or, for a hotfix with a release open, into the release branch), not the release
# branch a second time. Master then holds no merge commit that develop lacks: develop is not "behind" master, `git describe` on develop reaches the tag.
# A fixture with master-only merge commits (three releases finished the old way, by hand) shows the catch-up; history is not rewritten. Also: a finish
# cut off after its push and cut off again while it is resumed ends on the refs origin has; a hotfix into develop; a hotfix into an open release branch
# whose conflict exits 3, parks a merge of the master commit and resumes with --resolved. Offline: a bare repository is the origin, gh is a fake.
# Run: tests/test_release_master_merge.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
# a git that kills its parent (the verb's shell) right after the real git ran, once per flag file, when the call contains $DIE_AFTER
REALGIT=$(command -v git); export REALGIT
cat > "$T/bin/git" <<'S'
#!/usr/bin/env bash
"$REALGIT" "$@"; rc=$?
if [ -n "${DIE_AFTER:-}" ] && [ ! -e "${DIE_FLAG:-/nonexistent}" ]; then
  case " $* " in *"$DIE_AFTER"*) : > "$DIE_FLAG"; kill -9 "$PPID";; esac
fi
exit $rc
S
chmod +x "$T/bin/gh" "$T/bin/git"; export PATH=$T/bin:$PATH
R=$T/app; O=$T/origin.git; git init -q -b master "$R"; git init -q --bare "$O"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$O"
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
REL="$DA release"
rev() { git -C "$1" rev-parse -q --verify "$2" 2>/dev/null || echo none; }
commit_on() { # BRANCH FILE: one commit on BRANCH, made in a temporary worktree
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"; echo "$2" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "add $2"; git -C "$R" worktree remove --force "$w"
}
merge_on() { # BRANCH FROM MESSAGE [TAG]: a --no-ff merge of FROM into BRANCH in a temporary worktree, tagged TAG when given
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"; git -C "$w" merge -q --no-ff -m "$3" "$2"
  [ -z "${4:-}" ] || git -C "$w" tag -a "$4" -m "$4"; git -C "$R" worktree remove --force "$w"
}
rstart() { # ARGS: release start through its plan and the approval
  local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go >/dev/null 2>&1
}
rpush() { local t; t=$($REL push "$@" | tok); $REL push "$@" --plan "$t" --approved go >/dev/null 2>&1; }
cnt() { git -C "$R" rev-list --count "$1"; }

# --- the fixture: three releases finished the old way (the branch merged into master with a tag, then merged into develop a second time)
for v in 0.1.1 0.1.2 0.1.3; do
  commit_on develop "dev-$v.txt"; git -C "$R" branch "release/$v" develop; commit_on "release/$v" "rel-$v.txt"
  merge_on master "release/$v" "Merge branch 'release/$v'" "$v"; merge_on develop "release/$v" "Merge branch 'release/$v' into develop"; git -C "$R" branch -q -D "release/$v"
done
commit_on develop dev-own.txt
git -C "$R" push -q origin master develop --tags
[ "$(cnt develop..master)" = 3 ] && [ "$(cnt master..develop)" -gt 0 ] && [ "$(rev "$R" "master^{tree}")" != "$(rev "$R" "develop^{tree}")" ] \
  && ok "(setup) master holds three merge commits develop lacks" || no "setup: $(cnt develop..master) $(cnt master..develop)"

# --- a release finished: the second merge is of the tagged master commit
$REL verify 0.2.0 >/dev/null 2>&1; rstart 0.2.0 --date 2026-01-02 && rpush 0.2.0
d0=$(rev "$R" develop); m0=$(rev "$R" master)
out=$($REL finish 0.2.0 2>&1); t=$(tok <<<"$out")
grep -q "merge tag 0.2.0 (the master merge commit) into develop with --no-ff" <<<"$out" && [ -n "$t" ] && [ "$(rev "$R" develop)" = "$d0" ] \
  && ok "the plan says tag 0.2.0 (the master merge commit) is merged into develop, and changes nothing" || no "plan: $out"
out=$($REL finish 0.2.0 --plan "$t" --approved "go on" 2>&1); rc=$?
tg=$(rev "$R" "refs/tags/0.2.0^{commit}")
[ $rc = 0 ] && grep -q "tag 0.2.0 (the master merge commit ${tg:0:7}) into develop" <<<"$out" && ok "finish reports the merge of the master commit into develop" || no "finish rc=$rc: $out"
[ "$(rev "$R" master)" = "$tg" ] && [ "$(rev "$R" develop^1)" = "$d0" ] && [ "$(rev "$R" develop^2)" = "$tg" ] && [ "$(rev "$R" develop^3)" = none ] \
  && [ "$(git -C "$R" log -1 --format=%s develop)" = "Merge tag '0.2.0' into develop" ] && ok "develop is a --no-ff merge of the old develop and the tagged master commit, titled Merge tag '0.2.0' into develop" || no "develop shape"
[ "$(rev "$R" master^1)" = "$m0" ] && [ "$(rev "$R" master^2)" != none ] && [ "$(git -C "$R" log -1 --format=%s master)" = "Merge branch 'release/0.2.0'" ] \
  && ok "master is the usual --no-ff merge of the release branch" || no "master shape"
[ "$(cnt develop..master)" = 0 ] && ok "no commit is on master and not on develop (it was 3)" || no "develop..master = $(cnt develop..master)"
[ "$(cnt master..develop)" -gt 0 ] && ok "develop has commits master lacks (its own, and the merge)" || no "master..develop = $(cnt master..develop)"
[ "$(git -C "$R" describe --tags --abbrev=0 develop)" = 0.2.0 ] && git -C "$R" describe --tags develop | grep -q '^0\.2\.0' && ok "git describe --tags develop names 0.2.0" || no "describe: $(git -C "$R" describe --tags develop)"
[ "$(rev "$R" "develop^{tree}")" = "$(rev "$R" "master^{tree}")" ] && ok "the trees of develop and master are equal" || no "trees differ"
for v in 0.1.1 0.1.2 0.1.3; do git -C "$R" merge-base --is-ancestor "$v" develop || { no "the old tag $v is not in develop"; break; }; done
git -C "$R" merge-base --is-ancestor master develop && ok "the earlier master-only merge commits arrived with the one merge (master is an ancestor of develop)" || no "master not in develop"
[ "$(rev "$R" "refs/tags/0.1.2")" != none ] && git -C "$R" cat-file -e "master~1" && ok "history already on master is not rewritten (the old tags and merges are where they were)" || no "rewritten"
[ "$(rev "$R" develop)" = "$(rev "$O" refs/heads/develop)" ] && [ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] && [ "$(rev "$O" "refs/tags/0.2.0^{commit}")" = "$tg" ] \
  && ok "origin has the same master, develop and tag" || no "origin differs"
out=$($REL status 0.2.0 2>&1)
grep -q "origin develop: .*(same)" <<<"$out" && ! grep -Eq "local is [0-9]+ ahead, [0-9]+ behind" <<<"$out" && ok "release status after the finish reports no divergence" || no "status: $out"
[ "$(git -C "$O" rev-list --count develop..master)" = 0 ] && ok "and origin has master not ahead of develop either" || no "origin ahead"
[ ! -e "$T/s/conflicts/app-release-0.2.0-into-develop.master" ] && [ -z "$(ls "$T/s/finish-intent" 2>/dev/null)" ] && ok "no record or bookkeeping file is left" || no "left: $(ls "$T/s/conflicts" "$T/s/finish-intent" 2>&1)"

# --- a finish cut off after its push, and cut off again while it is resumed, ends on the refs origin has
commit_on develop late.txt; $REL verify 0.3.0 >/dev/null 2>&1; rstart 0.3.0 --date 2026-01-03 --allow-empty-notes && rpush 0.3.0
t=$($REL finish 0.3.0 | tok); d0=$(rev "$R" develop)
DIE_AFTER="push -q --atomic" DIE_FLAG=$T/die-a $REL finish 0.3.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
rec=$T/s/finish-intent/app-release-0.3.0.json
nd=$(rev "$O" refs/heads/develop); nm=$(rev "$O" refs/heads/master)
[ $rc != 0 ] && [ -e "$T/die-a" ] && [ "$nd" != "$d0" ] && [ "$(rev "$R" develop)" = "$d0" ] && [ -f "$rec" ] \
  && [ "$(jq -r '.refs[1].new' "$rec")" = "$nd" ] && [ "$(jq -r '.refs[0].new' "$rec")" = "$nm" ] && [ "$(jq -r '.refs[1].local_old' "$rec")" = "$d0" ] \
  && ok "(setup) it died after the push: the record holds the develop merge commit origin has" || no "setup: rc=$rc $(cat "$rec" 2>&1)"
[ "$(git -C "$O" rev-parse "$nd^2")" = "$nm" ] && ok "origin's develop is the merge of the master commit" || no "origin develop parent"
out=$($REL finish 0.3.0 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && grep -q "was cut off" <<<"$out" && grep -q "develop ${d0:0:7} -> ${nd:0:7}" <<<"$out" && [ "$(rev "$R" develop)" = "$d0" ] && ok "the re-run shows develop going to the merge commit origin has and changes nothing" || no "resume plan: rc=$rc $out"
DIE_AFTER="update-ref -d" DIE_FLAG=$T/die-b $REL finish 0.3.0 --plan "$t2" --approved go >/dev/null 2>&1; rc=$?
[ $rc != 0 ] && [ -e "$T/die-b" ] && [ "$(rev "$R" develop)" = "$nd" ] && [ "$(rev "$R" master)" = "$nm" ] && [ -f "$rec" ] && ok "(setup) the resume was cut off too, after the refs moved" || no "second death: rc=$rc $(cat "$rec" 2>&1)"
out=$($REL finish 0.3.0 2>&1); rc=$?; t3=$(tok <<<"$out")
[ $rc = 0 ] && grep -q "was cut off" <<<"$out" && [ -n "$t3" ] || no "second resume plan: rc=$rc $out"
out=$($REL finish 0.3.0 --plan "$t3" --approved "go on" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" develop)" = "$nd" ] && [ "$(rev "$R" master)" = "$nm" ] && [ "$(rev "$R" "refs/tags/0.3.0^{commit}")" = "$nm" ] && [ "$(rev "$R" release/0.3.0)" = none ] && [ ! -e "$rec" ] \
  && ok "resumed twice, it ends on the refs origin has, with the release branch deleted and the record gone" || no "twice resumed: rc=$rc $out"
[ "$(rev "$R" develop^2)" = "$nm" ] && [ "$(cnt develop..master)" = 0 ] && [ "$(rev "$R" "develop^{tree}")" = "$(rev "$R" "master^{tree}")" ] && ok "and develop is the merge of the tagged master commit" || no "develop after resume"
[ "$(jq -rs '[.[] | select(.verb == "release:finish")] | length' "$T/s/audit.log")" = 2 ] && ok "the audit line of each release is written once" || no "audit: $(cat "$T/s/audit.log")"

# --- a hotfix with no release open: master merge and tag, then the tagged master commit into develop
$REL verify 0.3.1 >/dev/null 2>&1; rstart 0.3.1 --hotfix --allow-empty-notes && commit_on hotfix/0.3.1 fix1.txt && rpush 0.3.1 --hotfix
d0=$(rev "$R" develop); out=$($REL finish 0.3.1 --hotfix 2>&1); t=$(tok <<<"$out")
grep -q "merge tag 0.3.1 (the master merge commit) into develop" <<<"$out" && ok "the hotfix plan says the master merge commit is merged into develop" || no "hotfix plan: $out"
out=$($REL finish 0.3.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?; tg=$(rev "$R" "refs/tags/0.3.1^{commit}")
[ $rc = 0 ] && [ "$(rev "$R" master)" = "$tg" ] && [ "$(rev "$R" develop^1)" = "$d0" ] && [ "$(rev "$R" develop^2)" = "$tg" ] && [ "$(git -C "$R" log -1 --format=%s develop)" = "Merge tag '0.3.1' into develop" ] \
  && git -C "$R" cat-file -e develop:fix1.txt && ok "the hotfix reaches develop as a merge of the tagged master commit" || no "hotfix to develop rc=$rc: $out"
[ "$(cnt develop..master)" = 0 ] && [ "$(git -C "$R" describe --tags --abbrev=0 develop)" = 0.3.1 ] && [ "$(rev "$R" develop)" = "$(rev "$O" refs/heads/develop)" ] && [ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] \
  && ok "master is not ahead of develop, describe names 0.3.1, origin matches" || no "after hotfix: $(cnt develop..master)"

# --- a hotfix with a release open goes into the release branch; the version conflict exits 3, parks a merge of the master commit and resumes
$REL verify 0.4.0 >/dev/null 2>&1; rstart 0.4.0 --date 2026-01-04 --allow-empty-notes && rpush 0.4.0
rstart 0.3.2 --hotfix --allow-empty-notes && commit_on hotfix/0.3.2 fix2.txt && rpush 0.3.2 --hotfix
d0=$(rev "$R" develop); r0=$(rev "$R" release/0.4.0); m0=$(rev "$R" master)
out=$($REL finish 0.3.2 --hotfix 2>&1); t=$(tok <<<"$out")
grep -q "merge tag 0.3.2 (the master merge commit) into release/0.4.0" <<<"$out" && ok "the plan names the open release branch as the second target" || no "hotfix to release plan: $out"
cout=$($REL finish 0.3.2 --hotfix --plan "$t" --approved go 2>&1); rc=$?
cp=$T/s/conflicts/app-hotfix-0.3.2-into-release_0.4.0
[ $rc = 3 ] && [ -d "$cp" ] && [ "$(rev "$R" master)" = "$m0" ] && [ "$(rev "$R" release/0.4.0)" = "$r0" ] && [ "$(rev "$R" refs/tags/0.3.2)" = none ] && ok "the conflict exits 3 with nothing moved and nothing tagged" || no "conflict rc=$rc"
nmc=$(cut -d' ' -f3 "$cp.master")
grep -q "qargi: merging tag 0.3.2 (the master merge commit ${nmc:0:7}) conflicts" <<<"$cout" && ok "the conflict message names the tag, not a bare sha" || no "conflict message: $cout"
mh=$(git -C "$cp" rev-parse MERGE_HEAD 2>/dev/null || echo none)
[ "$(git -C "$cp" rev-parse HEAD)" = "$r0" ] && [ "$mh" != none ] && [ "$(git -C "$R" log -1 --format=%s "$mh")" = "Merge branch 'hotfix/0.3.2'" ] && [ "$(git -C "$R" rev-parse "$mh^2")" = "$(rev "$R" hotfix/0.3.2)" ] \
  && ok "the parked worktree holds a merge of the master merge commit into the release branch" || no "parked merge: head=$(git -C "$cp" rev-parse HEAD) merge_head=$mh"
$REL finish 0.3.2 --hotfix --plan "$t" --approved go >/dev/null 2>&1 && no "a rerun without --resolved went through" || ok "a rerun without --resolved is refused"
[ -d "$cp" ] && [ "$(git -C "$cp" rev-parse MERGE_HEAD)" = "$mh" ] && ok "and the waiting merge is kept" || no "waiting merge lost"
git -C "$cp" diff --name-only --diff-filter=U | grep -qx VERSION && ok "the conflicted file is named (VERSION)" || no "conflicted: $(git -C "$cp" status --short)"
echo 0.4.0 > "$cp/VERSION"; git -C "$cp" checkout -q --ours CHANGELOG.md 2>/dev/null; git -C "$cp" add -A; git -C "$cp" commit -q --no-edit
out=$($REL finish 0.3.2 --hotfix --resolved --plan "$t" --approved go 2>&1); rc=$?; tg=$(rev "$R" "refs/tags/0.3.2^{commit}")
[ $rc = 0 ] && [ "$tg" = "$mh" ] && [ "$(rev "$R" master)" = "$mh" ] && [ "$(rev "$R" release/0.4.0^1)" = "$r0" ] && [ "$(rev "$R" release/0.4.0^2)" = "$mh" ] && [ "$(rev "$R" develop)" = "$d0" ] \
  && ok "resolved, the release branch is the merge of the tagged master commit and develop did not move" || no "resolved rc=$rc: $out"
[ "$(rev "$R" release/0.4.0)" = "$(rev "$O" refs/heads/release/0.4.0)" ] && [ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] && [ ! -d "$cp" ] && [ ! -e "$cp.master" ] && [ ! -e "$cp.done" ] \
  && ok "pushed with the tag, and the parked worktree and its files are gone" || no "push or bookkeeping: $(ls "$T/s/conflicts")"
# the release that was open is then finished: it contains the hotfix, and the one merge brings the hotfix's master commit into develop
t=$($REL finish 0.4.0 | tok)
out=$($REL finish 0.4.0 --plan "$t" --approved go 2>&1); rc=$?; tg=$(rev "$R" "refs/tags/0.4.0^{commit}")
[ $rc = 0 ] && [ "$(rev "$R" develop^2)" = "$tg" ] && [ "$(cnt develop..master)" = 0 ] && [ "$(rev "$R" "develop^{tree}")" = "$(rev "$R" "master^{tree}")" ] \
  && git -C "$R" merge-base --is-ancestor 0.3.2 develop && ok "finishing that release: develop gets the hotfix's tag too, master is not ahead, the trees are equal" || no "release after hotfix rc=$rc: $out"
out=$($REL status 0.4.0 2>&1)
grep -q "origin develop: .*(same)" <<<"$out" && ! grep -Eq "local is [0-9]+ ahead, [0-9]+ behind" <<<"$out" && ok "and release status reports no divergence" || no "final status: $out"

# --- the bookkeeping file of the master merge commit is used only when it names a merge of this master and this branch head; any other is removed
rstart 0.4.1 --hotfix --allow-empty-notes && commit_on hotfix/0.4.1 fix3.txt && rpush 0.4.1 --hotfix
m0=$(rev "$R" master); hh=$(rev "$R" hotfix/0.4.1); bogus=$(rev "$R" develop); mf=$T/s/conflicts/app-hotfix-0.4.1-into-develop.master
mkdir -p "$T/s/conflicts"; echo "$m0 $hh $bogus" > "$T/s/conflicts/app-hotfix-0.4.1-into-develop.master"
t=$($REL finish 0.4.1 --hotfix | tok)
out=$($REL finish 0.4.1 --hotfix --plan "$t" --approved go 2>&1); rc=$?; tg=$(rev "$R" "refs/tags/0.4.1^{commit}")
[ $rc = 0 ] && [ "$tg" != "$bogus" ] && [ "$(git -C "$R" rev-list --parents -n 1 "$tg")" = "$tg $m0 $hh" ] && [ "$(rev "$R" master)" = "$tg" ] && [ "$(rev "$R" develop^2)" = "$tg" ] && [ ! -e "$mf" ] \
  && ok "a file naming a commit that is not a merge of this master and this branch head is not used: the tag is on a new merge of them, and the file is gone" || no "bogus bookkeeping: rc=$rc tag=$tg: $out"
exit $fail
