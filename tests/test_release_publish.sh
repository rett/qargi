#!/usr/bin/env bash
# `qargi release status|verify` flag a tag with no GitHub release and a tagged commit without the release workflow, and
# `qargi release publish TAG` creates the GitHub release behind a plan token. gh is a stub (QARGI_GH); GitHub is never contacted.
# Run: tests/test_release_publish.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"
# the stub: logs its arguments; answers `release view` by the mode in $T/mode and copies the notes file of `release create`
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in
  *"release view"*)
    case \$(cat "$T/mode") in
      found) echo "title: x"; exit 0;;
      missing) echo "release not found" >&2; exit 1;;
      unauth) echo "To get started with GitHub CLI, please run:  gh auth login" >&2; exit 4;;
    esac;;
  *"release create"*)
    while [ \$# -gt 0 ]; do [ "\$1" = --notes-file ] && cp "\$2" "$T/notes.copy"; shift; done
    echo "https://github.com/acme/relpub/releases/tag/0.1.0"; exit 0;;
esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh
mode() { echo "$1" > "$T/mode"; : > "$T/gh.log"; }
# a repository: 0.1.0 is tagged on a commit without the workflow; develop later gains it; 0.3.0's changelog section is empty
R=$T/relpub; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.1.0] - 2026-01-01\n\n### Added\n- first thing\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.1.0 -m 0.1.0 && git -C "$R" branch develop
git -C "$R" checkout -q develop && mkdir -p "$R/.github/workflows" && echo "name: release" > "$R/.github/workflows/release.yml"
printf '# Changelog\n\n## [0.3.0] - 2026-02-01\n\n## [0.1.0] - 2026-01-01\n- first thing\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m two && git -C "$R" tag -a 0.3.0 -m 0.3.0 && git -C "$R" tag -a 0.2.0 -m 0.2.0
git -C "$R" checkout -q master
git init -q --bare "$T/origin.git"; git -C "$R" remote add origin "$T/origin.git"
jq -n --arg p "$R" '{schema:1, project:"relpub", methodology:"gitflow", repo:{url:"https://github.com/acme/relpub", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/relpub.json"
export QARGI_PROJECT=relpub

# --- status and verify: the two warnings
mode missing; out=$($REL status 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^warning: tag 0.1.0 has no GitHub release" <<<"$out" && ok "status warns about a tag without a GitHub release" || no "status missing: rc=$rc $out"
grep -q "^warning: tag 0.1.0 .* lacks .github/workflows/release.yml" <<<"$out" && ok "status warns about a tagged commit without the release workflow" || no "status workflow: $out"
grep -qx -- "-R acme/relpub release view 0.1.0" "$T/gh.log" && [ "$(wc -l < "$T/gh.log")" = 1 ] && ok "the only gh call is the read-only release view" || no "gh log: $(cat "$T/gh.log")"
mode found; out=$($REL status 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q "no GitHub release" <<<"$out" && grep -q "lacks .github/workflows/release.yml" <<<"$out" && ok "a tag with its release is not flagged (the workflow warning stays)" || no "status found: rc=$rc $out"
mode unauth; out=$($REL status 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^note: gh is not authenticated" <<<"$out" && ! grep -q "has no GitHub release" <<<"$out" && ok "an unauthenticated gh is a note, not a failure" || no "status unauth: rc=$rc $out"
mode missing; out=$(QARGI_GH=$T/nogh $REL status 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^note: gh is not installed" <<<"$out" && ok "a missing gh is a note, not a failure" || no "status no gh: rc=$rc $out"
mode missing; out=$($REL status 0.2.0 2>&1); rc=$?
! grep -q "lacks .github/workflows" <<<"$out" && grep -q "^warning: tag 0.2.0 has no GitHub release" <<<"$out" && ok "a tagged commit that has the workflow is not flagged for it" || no "status 0.2.0: rc=$rc $out"
mode missing; out=$($REL status 0.9.0 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q "warning:\|note:" <<<"$out" && [ ! -s "$T/gh.log" ] && ok "without a tag nothing is checked and GitHub is not asked" || no "status no tag: rc=$rc $out"
mode missing; out=$($REL verify 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^full suite: pass" <<<"$out" && grep -q "^warning: tag 0.1.0 has no GitHub release" <<<"$out" && grep -q "lacks .github/workflows/release.yml" <<<"$out" && ok "verify reports both warnings and keeps its exit status" || no "verify: rc=$rc $out"
R2=$T/norigin; git init -q -b master "$R2"; echo 0.1.0 > "$R2/VERSION"; git -C "$R2" add -A && git -C "$R2" commit -q -m one && git -C "$R2" tag -a 0.1.0 -m 0.1.0 && git -C "$R2" branch develop
jq -n --arg p "$R2" '{schema:1, project:"norigin", methodology:"gitflow", repo:{url:"https://github.com/acme/norigin", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/norigin.json"
mode missing; out=$(QARGI_PROJECT=norigin $REL status 0.1.0 2>&1); rc=$?
[ $rc = 0 ] && [ ! -s "$T/gh.log" ] && ok "a repository without origin is not asked about GitHub" || no "no origin: rc=$rc $out $(cat "$T/gh.log")"

# --- publish
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
mode missing; out=$($REL publish 0.1.0 2>&1); rc=$?; t=$(tok <<<"$out")
c=$(git -C "$R" rev-parse --short "0.1.0^{commit}")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "$c" <<<"$out" && grep -q -- "- first thing" <<<"$out" && grep -q 'release create 0.1.0 --verify-tag --title "relpub 0.1.0" --notes-file' <<<"$out" && ok "the plan shows the tag, its commit, the notes and the command" || no "plan: rc=$rc $out"
! grep -q "release create" "$T/gh.log" && ok "planning creates nothing" || no "plan created: $(cat "$T/gh.log")"
$REL publish 0.1.0 --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || { ! grep -q "release create" "$T/gh.log" && ok "a wrong plan token refuses" || no "wrong token created"; }
$REL publish 0.1.0 --plan "$t" --approved "go ahead" > "$T/o" 2>&1; rc=$?
grep -q "release create 0.1.0 --verify-tag --title relpub 0.1.0 --notes-file" "$T/gh.log" && [ "$(cat "$T/notes.copy")" = "$(printf '### Added\n- first thing')" ] && [ $rc = 0 ] && grep -q "releases/tag/0.1.0" "$T/o" && ok "applied: gh release create runs with the changelog section as notes" || no "apply: rc=$rc $(cat "$T/o") $(cat "$T/gh.log")"
grep -q '"verb":"release:publish"' "$T/s/audit.log" && grep -q '"approved":"go ahead"' "$T/s/audit.log" && ok "the apply is audited" || no "audit: $(cat "$T/s/audit.log" 2>/dev/null)"
mode found; out=$($REL publish 0.1.0 2>&1) && no "published over an existing release" || { grep -q "already has a GitHub release" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "refuses when the release exists" || no "exists: $out"; }
mode missing; out=$($REL publish 0.9.0 2>&1) && no "published a missing tag" || { grep -q "no tag 0.9.0" <<<"$out" && ok "refuses when the tag is missing" || no "no tag: $out"; }
out=$($REL publish 0.3.0 2>&1) && no "published an empty section" || { grep -q "no changelog section for 0.3.0" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "refuses when the changelog section is empty" || no "empty: $out"; }
out=$(QARGI_GH=$T/nogh $REL publish 0.1.0 2>&1); t2=$(tok <<<"$out")
grep -q "^note: gh is not installed" <<<"$out" && [ -n "$t2" ] && ok "the plan is shown without gh, with a note" || no "plan no gh: $out"
QARGI_GH=$T/nogh $REL publish 0.1.0 --plan "$t2" --approved go >/dev/null 2>&1 && no "applied without gh" || ok "applying without gh refuses"
mode unauth; out=$($REL publish 0.1.0 --plan "$t" --approved go 2>&1) && no "applied unauthenticated" || ok "applying with an unauthenticated gh refuses"

# --- publish: assets in the same create call, a notes file, and the signature gate
ROOT=$PWD; cd "$T" || exit 1   # the lead works outside any run directory (inside one, release sign is refused as a member's)
RR=$(realpath "$R"); mkdir -p "$R/dist" "$T/fakebin"
echo "binary" > "$R/dist/a.tar.gz"; echo "other" > "$R/dist/b.zip"; printf 'Notes of 0.1.0.\n\n- the file notes\n' > "$R/dist/NOTES-0.1.0.md"; : > "$R/dist/EMPTY.md"
echo "abc  a.tar.gz" > "$R/dist/SHA256SUMS"
setans() { jq "$1" "$T/c/projects/relpub.json" > "$T/ans.tmp" && mv "$T/ans.tmp" "$T/c/projects/relpub.json"; }   # the fixture's answers are not a whole project
creates() { grep -c "release create" "$T/gh.log"; }
mode missing
out=$($REL publish 0.1.0 --asset dist/a.tar.gz 2>&1); t=$(tok <<<"$out")
sum=$(sha256sum < "$R/dist/a.tar.gz" | cut -d' ' -f1)
grep -q "^assets (1), attached by the same gh release create:" <<<"$out" && grep -q "| $sum  dist/a.tar.gz" <<<"$out" && grep -q "^run: .*--notes-file NOTES $RR/dist/a.tar.gz\$" <<<"$out" && ok "the plan lists the asset with its hash and the command that attaches it" || no "asset plan: $out"
$REL publish 0.1.0 --asset dist/a.tar.gz --plan "$t" --approved go > "$T/o" 2>&1; rc=$?
[ $rc = 0 ] && [ "$(creates)" = 1 ] && grep -Eq "release create 0.1.0 --verify-tag --title relpub 0.1.0 --notes-file [^ ]+ $RR/dist/a.tar.gz\$" "$T/gh.log" && ok "the asset is attached in the one gh release create call" || no "asset apply: rc=$rc $(cat "$T/o") $(cat "$T/gh.log")"
mode missing
out=$($REL publish 0.1.0 --asset dist/a.tar.gz 2>&1); t=$(tok <<<"$out"); echo "changed" >> "$R/dist/a.tar.gz"
$REL publish 0.1.0 --asset dist/a.tar.gz --plan "$t" --approved go >/dev/null 2>&1 && no "applied a plan whose asset changed" || { [ "$(creates)" = 0 ] && ok "an asset that changed since the plan refuses the token" || no "changed asset created"; }
for bad in ../x.zip /etc/passwd dist/missing.bin dist; do
  out=$($REL publish 0.1.0 --asset "$bad" 2>&1) && no "accepted the asset $bad" || { ! grep -q "plan token" <<<"$out" && ok "the asset $bad is refused" || no "asset $bad: $out"; }
done
setans '.release.assets=["dist/b.zip"]'
out=$($REL publish 0.1.0 --asset dist/b.zip --asset dist/a.tar.gz 2>&1); t=$(tok <<<"$out")
grep -q "^assets (2)," <<<"$out" && ok "release.assets and --asset are joined, a file named twice once" || no "assets join: $out"
out=$($REL status 0.1.0 --asset dist/a.tar.gz 2>&1) && no "status took --asset" || { grep -q "belong to release publish" <<<"$out" && ok "--asset belongs to publish only" || no "status --asset: $out"; }
setans 'del(.release.assets)'
mode missing
out=$($REL publish 0.1.0 --notes-file dist/NOTES-0.1.0.md 2>&1); t=$(tok <<<"$out")
grep -q "^notes (the file dist/NOTES-0.1.0.md):" <<<"$out" && grep -q -- "- the file notes" <<<"$out" && ! grep -q "first thing" <<<"$out" && ok "--notes-file replaces the changelog section in the plan" || no "notes plan: $out"
$REL publish 0.1.0 --notes-file dist/NOTES-0.1.0.md --plan "$t" --approved go >/dev/null 2>&1
[ "$(cat "$T/notes.copy")" = "$(cat "$R/dist/NOTES-0.1.0.md")" ] && ok "gh release create gets the notes file's text" || no "notes copy: $(cat "$T/notes.copy")"
setans '.release.notes_file="dist/NOTES-{version}.md"'
mode missing; rm -f "$T/notes.copy"
out=$($REL publish 0.1.0 2>&1); t=$(tok <<<"$out"); $REL publish 0.1.0 --plan "$t" --approved go >/dev/null 2>&1
grep -q "^notes (the file dist/NOTES-0.1.0.md):" <<<"$out" && [ "$(cat "$T/notes.copy")" = "$(cat "$R/dist/NOTES-0.1.0.md")" ] && ok "release.notes_file with {version} is the notes without --notes-file" || no "answer notes: $out"
out=$($REL publish 0.1.0 --notes-file dist/EMPTY.md 2>&1) && no "an empty notes file was accepted" || { grep -q "notes file dist/EMPTY.md is empty" <<<"$out" && ok "an empty notes file is refused" || no "empty notes: $out"; }
out=$($REL publish 0.1.0 --notes-file /etc/passwd 2>&1) && no "a notes file outside the repository was accepted" || ok "a notes file outside the repository is refused"
setans 'del(.release.notes_file)'
# the signature gate
cat > "$T/fakebin/ssh-keygen" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/keygen.log"
f=\${@: -1}; echo "signature of \$(sha256sum < "\$f")" > "\$f.sig"
G
chmod +x "$T/fakebin/ssh-keygen"; PATH=$T/fakebin:$PATH; echo key > "$T/relkey"; : > "$T/keygen.log"
setans ".release.sign={key:\"$T/relkey\", namespace:\"relsign\", files:[\"dist/SHA256SUMS\"], verify_command:[\"test\",\"-s\",\"dist/SHA256SUMS.sig\"]}"
mode missing
out=$($REL publish 0.1.0 --asset dist/b.zip 2>&1); rc=$?
[ $rc = 1 ] && grep -q "awaiting signature: no signature is recorded" <<<"$out" && ! grep -q "plan token" <<<"$out" && [ "$(creates)" = 0 ] && ok "publish refuses until the tag is signed" || no "unsigned: rc=$rc $out"
out=$($REL status 0.1.0 2>&1)
grep -q "^awaiting signature: no signature is recorded" <<<"$out" && grep -q "^0.1.0 is ready for signing: qargi release sign 0.1.0\$" <<<"$out" && ok "status says awaiting signature and that the release is ready for signing" || no "status unsigned: $out"
git -C "$R" checkout -q --detach 0.3.0
out=$($REL status 0.1.0 2>&1)
grep -q "^awaiting signature: " <<<"$out" && ! grep -q "is ready for signing" <<<"$out" && grep -q "^  not ready for signing: HEAD of .* not the tag 0.1.0" <<<"$out" && ok "status does not say ready when the repository is not at the tag" || no "status off tag: $out"
git -C "$R" checkout -q master
mode found; out=$($REL status 0.1.0 2>&1); ! grep -q "awaiting signature" <<<"$out" && ok "status is silent about signing once GitHub has the release" || no "status found: $out"
mode missing
SIGN="python3 $ROOT/tests/pty_run.py $ROOT/bin/qargi release sign 0.1.0"
out=$($SIGN 2>&1); rc=$?
[ $rc = 0 ] && [ "$(cat "$T/keygen.log")" = "-Y sign -f $T/relkey -n relsign $RR/dist/SHA256SUMS" ] && ok "release sign signs the file (fake ssh-keygen)" || no "sign: rc=$rc $out | $(cat "$T/keygen.log")"
out=$($REL status 0.1.0 2>&1)
grep -q "^signature: signed and verified at" <<<"$out" && ! grep -q "awaiting signature" <<<"$out" && ok "status shows the recorded signature" || no "status signed: $out"
out=$($REL publish 0.1.0 --asset dist/b.zip --asset dist/SHA256SUMS 2>&1); t=$(tok <<<"$out")
grep -q "^signature: signed and verified at .*dist/SHA256SUMS" <<<"$out" && grep -q "note: dist/SHA256SUMS.sig is not among the assets" <<<"$out" && ok "the plan shows the signature and warns about an unattached .sig" || no "signed plan: $out"
$REL publish 0.1.0 --asset dist/b.zip --asset dist/SHA256SUMS --asset dist/SHA256SUMS.sig --plan "$(tok <<<"$($REL publish 0.1.0 --asset dist/b.zip --asset dist/SHA256SUMS --asset dist/SHA256SUMS.sig)")" --approved go > "$T/o" 2>&1; rc=$?
[ $rc = 0 ] && [ "$(creates)" = 1 ] && grep -q "$RR/dist/b.zip $RR/dist/SHA256SUMS $RR/dist/SHA256SUMS.sig\$" "$T/gh.log" && ok "signed: publish attaches the files and the signature" || no "signed apply: rc=$rc $(cat "$T/o") $(cat "$T/gh.log")"
mode missing
echo "tampered" >> "$R/dist/SHA256SUMS"
out=$($REL publish 0.1.0 --asset dist/b.zip 2>&1); rc=$?
[ $rc = 1 ] && grep -q "dist/SHA256SUMS changed since it was signed" <<<"$out" && [ "$(creates)" = 0 ] && ok "publish refuses when a signed file changed after the signature" || no "tampered: rc=$rc $out"
out=$($REL status 0.1.0 2>&1); grep -q "^awaiting signature: dist/SHA256SUMS changed since it was signed" <<<"$out" && ok "status says awaiting signature again after a signed file changed" || no "status tampered: $out"
sed -i '$d' "$R/dist/SHA256SUMS"; echo "forged" > "$R/dist/SHA256SUMS.sig"
out=$($REL publish 0.1.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "dist/SHA256SUMS.sig changed since it was recorded" <<<"$out" && ok "publish refuses when a signature file changed" || no "forged sig: rc=$rc $out"
cd "$ROOT" || exit 1
shellcheck -x -S warning tests/test_release_publish.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
