#!/usr/bin/env bash
# `qargi release assets VERSION` builds the release files in a clean worktree of the tag with the project's release.assets_command, and
# `release sign` and `release publish` take the files from that worktree: release.assets globs, --asset, --asset-dir and a full path inside
# any worktree of the repository. gh and ssh-keygen are stubs (QARGI_GH, a fake first on PATH); GitHub is never contacted.
# Run: tests/test_release_assets.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; ROOT=$PWD; DA=$ROOT/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/fakebin"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in
  *"release view"*) echo "release not found" >&2; exit 1;;
  *"release create"*) echo "https://github.com/acme/relas/releases/tag/0.1.0"; exit 0;;
esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh
cat > "$T/fakebin/ssh-keygen" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/keygen.log"
f=\${@: -1}; echo "signature of \$(sha256sum < "\$f")" > "\$f.sig"
G
chmod +x "$T/fakebin/ssh-keygen"; PATH=$T/fakebin:$PATH; echo key > "$T/relkey"

# a repository: the tagged commit holds the script that builds the release files; the main checkout rests on another branch
R=$T/relas; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n### Added\n- first thing\n' > "$R/CHANGELOG.md"
cat > "$R/build.sh" <<'B'
#!/usr/bin/env bash
mkdir -p dist; echo "app $1" > "dist/app-$1.tar"; echo "docs" > dist/docs.zip; echo "sums" > dist/SUMS; echo "$QARGI_RELEASE_VERSION" > dist/built-for
B
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.1.0 -m 0.1.0 && git -C "$R" branch develop
echo more > "$R/more.txt"; git -C "$R" add -A && git -C "$R" commit -q -m two && git -C "$R" tag -a 0.2.0 -m 0.2.0   # 0.2.0 is another commit than 0.1.0
git -C "$R" checkout -q -b parked
$DA project template relas | jq --arg p "$R" '.repo={url:"https://github.com/acme/relas", path:$p, long_lived:["master","develop"]} | .test_command="true"' > "$T/c/projects/relas.json"
export QARGI_PROJECT=relas
setans() { jq "$1" "$T/c/projects/relas.json" > "$T/ans.tmp" && mv "$T/ans.tmp" "$T/c/projects/relas.json"; }
cd "$T" || exit 1   # the lead works outside any run directory
AW=$(realpath -m "$T/s")/release-assets/relas-0.1.0; REC=$T/s/release/relas-0.1.0.assets.json
creates() { grep -c "release create" "$T/gh.log"; }
: > "$T/gh.log"

# --- the answer: release.assets_command (a command line or a list of words), release.assets globs
chk() { # name expected(0|1) jq-filter
  local f=$T/chk.json; jq "$3" "$T/c/projects/relas.json" > "$f"; $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then ok "answers: $1"; else no "answers: $1 (exit $rc, wanted $2)"; fi
}
chk "assets_command as a command line"   0 '.release={assets_command:"make dist"}'
chk "assets_command as a list of words"  0 '.release={assets_command:["make","dist","V={version}"]}'
chk "assets_command empty"               1 '.release={assets_command:""}'
chk "assets_command an empty list"       1 '.release={assets_command:[]}'
chk "assets_command a number"            1 '.release={assets_command:3}'
chk "assets_command with a newline"      1 '.release={assets_command:"make\nrm -rf x"}'
chk "assets as globs"                    0 '.release={assets:["dist/*.tar","dist/app-{version}.zip"]}'
chk "assets outside the repository"      1 '.release={assets:["../dist/*"]}'
$DA project set relas release.assets_command '["bash","build.sh","{version}"]' >/dev/null 2>&1 && ok "qargi project set takes release.assets_command" || no "project set"

# --- release assets: refusals before anything is made
setans 'del(.release)'
out=$($REL assets 0.1.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "release.assets_command is not set for relas" <<<"$out" && [ ! -e "$AW" ] && ok "refuses with a clear message while release.assets_command is unset" || no "unset: rc=$rc $out"
setans '.release.assets_command=["bash","build.sh","{version}"]'
out=$($REL assets 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "no tag 0.9.0" <<<"$out" && ok "refuses a version with no tag" || no "no tag: rc=$rc $out"
out=$($REL assets 0.1.0 --asset x 2>&1) && no "assets took --asset" || { grep -q "belong to release publish" <<<"$out" && ok "--asset belongs to publish only" || no "assets --asset: $out"; }
out=$($REL publish 0.1.0 --recreate 2>&1) && no "publish took --recreate" || { grep -q "belongs to release assets" <<<"$out" && ok "--recreate belongs to assets only" || no "publish --recreate: $out"; }
mkdir -p "$T/run/clone"; : > "$T/run/ability"; : > "$T/run/refs.before"
out=$(cd "$T/run/clone" && $REL assets 0.1.0 2>&1); rc=$?
[ $rc = 2 ] && grep -q "not available in a member run" <<<"$out" && [ ! -e "$AW" ] && ok "refused (exit 2) in a member run" || no "member: rc=$rc $out"
out=$(QARGI_NESTED=1 $REL assets 0.1.0 2>&1); rc=$?
[ $rc = 2 ] && [ ! -e "$AW" ] && ok "refused (exit 2) in a nested call" || no "nested: rc=$rc $out"

# --- release assets: the build, in a clean worktree of the tag
TC=$(git -C "$R" rev-parse "0.1.0^{commit}")
out=$($REL assets 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "in a clean worktree of the tag (${TC:0:7}): $AW\$" <<<"$out" && grep -q "^running: bash build.sh 0.1.0\$" <<<"$out" && ok "assets: builds in a worktree of the tag with the command (version replaced)" || no "assets: rc=$rc $out"
[ "$(cat "$AW/dist/app-0.1.0.tar")" = "app 0.1.0" ] && [ "$(cat "$AW/dist/built-for")" = 0.1.0 ] && [ "$(git -C "$AW" rev-parse HEAD)" = "$TC" ] && ok "the files are in the worktree, at the tag, and the command saw QARGI_RELEASE_VERSION" || no "worktree: $(ls "$AW" "$AW/dist" 2>&1)"
[ ! -e "$R/dist" ] && [ "$(git -C "$R" branch --show-current)" = parked ] && [ -z "$(git -C "$R" status --porcelain)" ] && ok "the repository's own checkout is untouched" || no "main checkout: $(git -C "$R" status --porcelain)"
git -C "$R" worktree list | grep -q "$AW" && [ "$(jq -r .worktree "$REC")" = "$AW" ] && [ "$(jq -r .commit "$REC")" = "$TC" ] && ok "the worktree is recorded under the state (path and tag commit)" || no "record: $(cat "$REC" 2>&1)"
grep -q "^  dist/app-0.1.0.tar\$" <<<"$out" && grep -q "^next: qargi release publish 0.1.0 " <<<"$out" && ! grep -q "release sign" <<<"$out" && ok "it lists the files made and names publish as the next command (no release.sign)" || no "listing: $out"
grep -q '"verb":"release:assets"' "$T/s/audit.log" && ok "the run is audited" || no "audit"
out=$($REL assets 0.1.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "exists already" <<<"$out" && grep -q -- "--recreate" <<<"$out" && ok "an existing asset worktree is kept unless --recreate" || no "twice: rc=$rc $out"
echo stray > "$AW/stray"; setans '.release.assets_command="bash build.sh \"$QARGI_RELEASE_VERSION\""'
out=$($REL assets 0.1.0 --recreate 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^running: bash -c bash build.sh" <<<"$out" && [ ! -e "$AW/stray" ] && [ -f "$AW/dist/app-0.1.0.tar" ] && ok "--recreate starts again from the tag (a command line runs by bash -c)" || no "recreate: rc=$rc $out"
# a failing command leaves the worktree to look at and no record
setans '.release.assets_command=["bash","-c","exit 3"]'
AW2=$(realpath -m "$T/s")/release-assets/relas-0.2.0
out=$($REL assets 0.2.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "release.assets_command failed (exit 3)" <<<"$out" && [ -d "$AW2" ] && [ ! -e "$T/s/release/relas-0.2.0.assets.json" ] && ok "a failing command is reported, leaves the worktree and records nothing" || no "failing: rc=$rc $out"
git -C "$R" worktree remove --force "$AW2"
setans '.release.assets_command=["bash","build.sh","{version}"]'

# --- release publish: the assets come from the asset worktree
asset_plan() { $REL publish 0.1.0 "$@" 2>&1; }
setans '.release.assets=["dist/app-{version}.tar","dist/*.zip"]'
out=$(asset_plan); t=$(tok <<<"$out")
grep -q "^assets (2), attached" <<<"$out" && grep -q "  dist/app-0.1.0.tar\$" <<<"$out" && grep -q "  dist/docs.zip\$" <<<"$out" && grep -q "^run: .*--notes-file NOTES $AW/dist/app-0.1.0.tar $AW/dist/docs.zip\$" <<<"$out" \
  && ok "release.assets (a name and a glob, {version} replaced) are taken in the asset worktree" || no "glob plan: $out"
$REL publish 0.1.0 --plan "$t" --approved go >/dev/null 2>&1
grep -Eq "release create 0.1.0 --verify-tag --title relas 0.1.0 --notes-file [^ ]+ $AW/dist/app-0.1.0.tar $AW/dist/docs.zip\$" "$T/gh.log" && ok "gh release create attaches the files of the worktree" || no "apply: $(cat "$T/gh.log")"
setans '.release.assets=["dist/*.nothing"]'
out=$(asset_plan) && no "a glob with no match was accepted" || { grep -q "no file matches" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "a glob that matches nothing refuses" || no "no match: $out"; }
setans 'del(.release.assets)'
out=$(asset_plan --asset-dir dist); t=$(tok <<<"$out")
grep -q "^assets (4)," <<<"$out" && ok "--asset-dir attaches every regular file of the directory" || no "asset-dir: $out"
mkdir "$AW/dist/sub"; echo x > "$AW/dist/sub/inner"; mkdir "$AW/emptydir"
out=$(asset_plan --asset-dir dist); grep -q "^assets (4)," <<<"$out" && ! grep -q "inner" <<<"$out" && ok "--asset-dir does not descend into subdirectories" || no "asset-dir sub: $out"
out=$(asset_plan --asset-dir emptydir) && no "an empty directory was accepted" || { grep -q "no regular file in it" <<<"$out" && ok "--asset-dir of an empty directory refuses" || no "empty dir: $out"; }
out=$(asset_plan --asset-dir nodir) && no "a missing directory was accepted" || ok "--asset-dir of a missing directory refuses"
out=$(asset_plan --asset-dir /etc) && no "a directory outside was accepted" || { grep -q "not inside the repository or one of its worktrees" <<<"$out" && ok "--asset-dir outside the worktrees refuses" || no "dir outside: $out"; }
out=$(asset_plan --asset dist/SUMS --asset-dir dist); grep -q "^assets (4)," <<<"$out" && ok "a file named twice is attached once" || no "twice: $out"
ln -s /etc/passwd "$AW/dist/link"
out=$(asset_plan --asset-dir dist) && no "a symbolic link to a file outside was accepted" || { grep -q "not inside the repository or one of its worktrees" <<<"$out" && ok "a symbolic link that leaves the worktrees refuses" || no "symlink: $out"; }
rm -f "$AW/dist/link"
# git's own files are never assets: by name, and through a symbolic link that resolves into the repository's .git
out=$(asset_plan --asset .git) && no "the .git file was accepted" || { grep -q "a .git component" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "a name with a .git component refuses" || no ".git name: $out"; }
ln -s "$R/.git/config" "$AW/dist/cfg"
out=$(asset_plan --asset-dir dist) && no "a link into .git was accepted" || { grep -q "has a .git component" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "a symbolic link that resolves into .git refuses" || no "link into .git: $out"; }
out=$(asset_plan --asset dist/cfg) && no "a link into .git was accepted by name" || ok "and by name"
rm -f "$AW/dist/cfg"
# two files of one base name would be one asset
mkdir -p "$AW/dist/sub"; echo other > "$AW/dist/sub/SUMS"
out=$(asset_plan --asset dist/SUMS --asset dist/sub/SUMS) && no "two assets of one base name were accepted" || { grep -q "have the same base name SUMS" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "two assets with the same base name refuse" || no "same base: $out"; }
setans '.release.assets=["dist/SUMS","dist/**/SUMS"]'
out=$(asset_plan) && no "a glob and a name of one base name were accepted" || { grep -q "have the same base name SUMS" <<<"$out" && ok "so do a release.assets name and a glob that finds another file of that name" || no "glob same base: $out"; }
setans 'del(.release.assets)'
rm -rf "$AW/dist/sub"
# a full path inside another worktree of the repository
git -C "$R" worktree add -q --detach "$T/other" master; echo extra > "$T/other/extra.bin"; mkdir "$T/outside"; echo no > "$T/outside/x.bin"
out=$(asset_plan --asset "$(realpath "$T/other")/extra.bin"); t=$(tok <<<"$out")
grep -q "^assets (1)," <<<"$out" && grep -q "  extra.bin\$" <<<"$out" && ok "a full path inside another worktree of the repository is accepted" || no "other worktree: $out"
out=$(asset_plan --asset "$T/outside/x.bin") && no "a file outside every worktree was accepted" || { ! grep -q "plan token" <<<"$out" && ok "a full path outside every worktree refuses" || no "outside: $out"; }
out=$(asset_plan --asset ../outside/x.bin) && no "a .. path was accepted" || ok "a relative path that leaves the worktree refuses"
git -C "$R" worktree remove --force "$T/other"

# --- release sign: the files are signed in the asset worktree, whatever the main checkout is on
setans ".release.sign={key:\"$T/relkey\", namespace:\"relsign\", files:[\"dist/SUMS\"], verify_command:[\"test\",\"-s\",\"dist/SUMS.sig\"]}"
out=$($REL status 0.1.0 2>&1)
grep -q "^awaiting signature: no signature is recorded" <<<"$out" && grep -q "^0.1.0 is ready for signing: qargi release sign 0.1.0\$" <<<"$out" && ok "status: ready for signing although the main checkout is on another branch" || no "status ready: $out"
SIGN="python3 $ROOT/tests/pty_run.py $ROOT/bin/qargi release sign 0.1.0"
out=$($SIGN 2>&1); rc=$?
[ $rc = 0 ] && [ "$(cat "$T/keygen.log")" = "-Y sign -f $T/relkey -n relsign $AW/dist/SUMS" ] && [ -s "$AW/dist/SUMS.sig" ] && [ ! -e "$R/dist" ] && ok "release sign signs the file in the asset worktree" || no "sign: rc=$rc $out | $(cat "$T/keygen.log")"
out=$($REL status 0.1.0 2>&1); grep -q "^signature: signed and verified at .*dist/SUMS" <<<"$out" && ok "status shows the signature of the worktree's file" || no "status signed: $out"
out=$(asset_plan --asset-dir dist); t=$(tok <<<"$out")
grep -q "^signature: signed and verified" <<<"$out" && ! grep -q "is not among the assets" <<<"$out" && grep -q "  dist/SUMS.sig\$" <<<"$out" && ok "publish: the .sig beside the signed file is among the assets" || no "signed plan: $out"
: > "$T/gh.log"; $REL publish 0.1.0 --asset-dir dist --plan "$t" --approved go >/dev/null 2>&1; [ "$(creates)" = 1 ] && ok "signed: publish attaches the directory's files" || no "signed apply: $(cat "$T/gh.log")"
echo tampered >> "$AW/dist/SUMS"
out=$(asset_plan --asset-dir dist); ! grep -q "plan token" <<<"$out" && grep -q "dist/SUMS changed since it was signed" <<<"$out" && ok "a signed file that changed in the worktree refuses publish" || no "tampered: $out"
git -C "$AW" checkout -q --detach 0.2.0
out=$($REL status 0.1.0 2>&1)
grep -q "^awaiting signature" <<<"$out" && grep -q "no longer at the tag" <<<"$out" && ok "an asset worktree that is no longer at the tag is ignored (with a note)" || no "off tag: $out"
git -C "$AW" checkout -q --detach 0.1.0

# --- the record outlives nothing it should not: a worktree removed by hand is ignored with a note, and the repository is used
git -C "$R" worktree remove --force "$AW"
setans 'del(.release.sign)'; echo relfile > "$R/dist-file"
out=$(asset_plan --asset dist-file 2>&1); grep -q "is gone or no longer at the tag" <<<"$out" && grep -q "  dist-file\$" <<<"$out" && ok "with the worktree gone, publish says so and takes the file from the repository" || no "gone: $out"
rm -f "$R/dist-file"

cd "$ROOT" || exit 1
shellcheck -x -S warning tests/test_release_assets.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
