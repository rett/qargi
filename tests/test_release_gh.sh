#!/usr/bin/env bash
# `qargi release` talks to GitHub only through $QARGI_GH (a stub here), names the repository without a trailing .git, titles the
# pull request like the release, refuses to start a version whose tag exists, and leaves no temporary file behind.
# Run: tests/test_release_gh.sh
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
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://github.com/acme/relgh/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh
R=$T/relgh; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git clone -q --bare "$R" "$T/origin.git" && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" fetch -q origin
git -C "$R" checkout -q -b parked   # the main checkout is on neither long-lived branch
jq -n --arg p "$R" '{schema:1, project:"relgh", methodology:"gitflow", repo:{url:"https://github.com/acme/relgh.git", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/relgh.json"
export QARGI_PROJECT=relgh

# start refuses a version whose tag exists, before it asks anything else
git -C "$R" tag -a 0.9.0 -m 0.9.0 master
out=$(rstart 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the tag 0.9.0 exists already" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.9.0 >/dev/null && ok "release start refuses a version whose tag exists" || no "start with a tag: rc=$rc $out"
out=$(rstart 0.9.0 --hotfix 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the tag 0.9.0 exists already" <<<"$out" && ok "and so does a hotfix start" || no "hotfix start with a tag: rc=$rc $out"

# push and finish name the repository without .git, go through the stub, and title the pull request like the release
$REL verify 0.2.0 >/dev/null 2>&1 && rstart 0.2.0 --date 2026-01-02 >/dev/null 2>&1 && ok "a release starts" || no "start 0.2.0"
: > "$T/gh.log"
t=$($REL push 0.2.0 | tok); out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q -- "pr create --base master --head release/0.2.0 --title relgh 0.2.0 " "$T/gh.log" && ok "the pull request is titled like the release: project and version" || no "push rc=$rc: $out $(cat "$T/gh.log")"
t=$($REL finish 0.2.0 | tok); out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -qx -- "-R acme/relgh pr checks release/0.2.0" "$T/gh.log" && ok "finish asks for the checks of acme/relgh, without .git" || no "finish rc=$rc: $out $(cat "$T/gh.log")"

# a gh that is not there is looked for as $QARGI_GH, not as gh on the path: the branch is pushed, the pull request is left to you
$REL verify 0.3.0 >/dev/null 2>&1 && rstart 0.3.0 --allow-empty-notes >/dev/null 2>&1 || no "start 0.3.0"
t=$($REL push 0.3.0 | tok); out=$(QARGI_GH=$T/nogh $REL push 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "pushed release/0.3.0, but gh is not installed" <<<"$out" && git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.3.0 >/dev/null && ok "push without the stub's gh pushes and says gh is missing" || no "push without gh: rc=$rc $out"
t=$($REL finish 0.3.0 | tok); out=$(QARGI_GH=$T/nogh $REL finish 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "gh is needed to read the pull request's checks" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/tags/0.3.0 >/dev/null && ok "finish without gh refuses and tags nothing" || no "finish without gh: rc=$rc $out"

# a caller that is itself approved (QARGI_NESTED) has not approved this plan: start and push still need the token
$REL verify 0.4.0 >/dev/null 2>&1
out=$(QARGI_NESTED=1 $REL start 0.4.0 --allow-empty-notes --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.4.0 >/dev/null && ok "release start applies with no token even when QARGI_NESTED is set: refused, nothing created" || no "nested start, no token: rc=$rc $out"
out=$(QARGI_NESTED=1 $REL start 0.4.0 --allow-empty-notes --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.4.0 >/dev/null && ok "and a wrong token is refused under QARGI_NESTED too" || no "nested start, wrong token: rc=$rc $out"
t=$($REL start 0.4.0 --allow-empty-notes | tok); out=$(QARGI_NESTED=1 $REL start 0.4.0 --allow-empty-notes --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify refs/heads/release/0.4.0 >/dev/null && ok "the right token still applies under QARGI_NESTED" || no "nested start, right token: rc=$rc $out"
out=$(QARGI_NESTED=1 $REL push 0.4.0 --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && ! git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.4.0 >/dev/null && ok "release push with no token under QARGI_NESTED is refused, nothing pushed" || no "nested push, no token: rc=$rc $out"
# publish leaves no notes file behind: on a plan, after a refused token, after a refusal before the plan
git -C "$R" tag -a 0.8.0 -m x master
$REL publish 0.2.0 >/dev/null 2>&1; $REL publish 0.8.0 >/dev/null 2>&1; $REL publish 0.2.0 --plan 000000000000 --approved go >/dev/null 2>&1
[ -z "$(find "$T/s" "$T/tmp" -name '.release-notes.*' 2>/dev/null)" ] && ok "release publish removes its notes file whatever way it ends" || no "a notes file is left: $(find "$T/s" "$T/tmp" -name '.release-notes.*')"
# --- release sign: ssh-keygen (a fake first on PATH, never the real one) runs on the person's terminal, from the tag only
# The run is under a pseudo-terminal (tests/pty_run.py), because the verb refuses a stdin that is no terminal; nothing is ever typed to it.
mkdir -p "$T/fakebin" "$R/dist"
cat > "$T/fakebin/ssh-keygen" <<G
#!/usr/bin/env bash
t0=n; t1=n; t2=n; [ -t 0 ] && t0=y; [ -t 1 ] && t1=y; [ -t 2 ] && t2=y
echo "\$* | agent=\${SSH_AUTH_SOCK:-none} askpass=\${SSH_ASKPASS:-none} tty=\$t0\$t1\$t2" >> "$T/keygen.log"
[ -z "\${FAKE_FAIL:-}" ] || exit 1
f=\${@: -1}; echo "signature of \$(sha256sum < "\$f")" > "\$f.sig"
G
chmod +x "$T/fakebin/ssh-keygen"; export PATH=$T/fakebin:$PATH
echo "key" > "$T/relkey"; echo "abc  a.tar.gz" > "$R/dist/SHA256SUMS"
RR=$(realpath "$R"); SIGN=$DA' release sign 0.2.0'
PTYRUN=$PWD/tests/pty_run.py; pty() { python3 "$PTYRUN" "$@"; }
cd "$T" || exit 1   # the lead works outside any run directory (a checkout inside one is taken for a member run, where sign refuses)
: > "$T/keygen.log"
out=$($REL sign 0.2.0 2>&1 </dev/null); rc=$?
[ $rc = 2 ] && grep -q "signing is not enabled for this project (set release.sign in the project answers)" <<<"$out" && ok "sign exits 2 for a project with no release.sign: signing is opt-in" || no "sign without answers: rc=$rc $out"
out=$(pty $SIGN 2>&1); rc=$?
[ $rc = 2 ] && grep -q "signing is not enabled for this project" <<<"$out" && [ ! -s "$T/keygen.log" ] && ok "and on a terminal too, without reaching ssh-keygen" || no "sign without answers on a tty: rc=$rc $out"
setans() { jq "$1" "$T/c/projects/relgh.json" > "$T/ans.tmp" && mv "$T/ans.tmp" "$T/c/projects/relgh.json"; }   # the answers of the fixture are not a whole project: edit the file
setans ".release.sign={key:\"$T/relkey\", namespace:\"relsign\", files:[\"dist/SHA256SUMS\"], verify_command:[\"touch\",\"verified.flag\"]}" && ok "release.sign is stored as an answer" || no "set release.sign"
git -C "$R" checkout -q parked
out=$(pty $SIGN 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not the tag 0.2.0" <<<"$out" && ok "sign is refused off the tag (a parked branch)" || no "sign off tag: rc=$rc $out"
git -C "$R" checkout -q develop
out=$(pty $SIGN 2>&1); rc=$?
[ $rc = 1 ] && grep -q "not the tag 0.2.0" <<<"$out" && ok "sign is refused on develop" || no "sign on develop: rc=$rc $out"
git -C "$R" checkout -q -b other 0.2.0
out=$(pty $SIGN 2>&1); rc=$?
[ $rc = 1 ] && grep -q "is on branch other" <<<"$out" && ok "sign is refused on another branch even at the tag's commit" || no "sign on other: rc=$rc $out"
git -C "$R" checkout -q --detach 0.2.0
out=$($SIGN 2>&1 </dev/null); rc=$?
[ $rc = 1 ] && grep -q "needs a terminal on stdin" <<<"$out" && ok "sign is refused when stdin is no terminal" || no "sign no tty: rc=$rc $out"
out=$(QARGI_NESTED=1 pty $SIGN 2>&1); rc=$?
[ $rc = 2 ] && grep -q "not available in a member run or a nested call" <<<"$out" && ok "sign is refused when QARGI_NESTED is set" || no "sign nested: rc=$rc $out"
mkdir -p "$T/run/clone"; : > "$T/run/ability"; : > "$T/run/refs.before"
out=$(cd "$T/run/clone" && pty $SIGN 2>&1); rc=$?
[ $rc = 2 ] && grep -q "not available in a member run" <<<"$out" && ok "sign is refused in a member run" || no "sign member: rc=$rc $out"
echo "x" >> "$R/VERSION"
out=$(pty $SIGN 2>&1); rc=$?
git -C "$R" checkout -q -- VERSION
[ $rc = 1 ] && grep -q "tracked files of .* are modified" <<<"$out" && ok "sign is refused when a tracked file is modified" || no "sign dirty: rc=$rc $out"
mv "$R/dist/SHA256SUMS" "$T/SHA256SUMS.away"
out=$(pty $SIGN 2>&1); rc=$?
mv "$T/SHA256SUMS.away" "$R/dist/SHA256SUMS"
[ $rc = 1 ] && grep -q "dist/SHA256SUMS of release.sign.files does not exist" <<<"$out" && ok "sign is refused when a file to sign is not built" || no "sign missing file: rc=$rc $out"
[ ! -s "$T/keygen.log" ] && ok "none of those refusals reached ssh-keygen" || no "ssh-keygen ran: $(cat "$T/keygen.log")"
out=$(SSH_AUTH_SOCK=/nowhere SSH_ASKPASS=/bin/false pty $SIGN 2>&1); rc=$?
rec=$T/s/release/relgh-0.2.0.sign.json
[ $rc = 0 ] && [ "$(cat "$T/keygen.log")" = "-Y sign -f $T/relkey -n relsign $RR/dist/SHA256SUMS | agent=none askpass=none tty=yyy" ] && ok "sign runs ssh-keygen -Y sign -f KEY -n NAMESPACE FILE on the terminal, with no agent or askpass" || no "sign: rc=$rc $out | $(cat "$T/keygen.log")"
[ -f "$R/dist/SHA256SUMS.sig" ] && [ -f "$R/verified.flag" ] && ok "verify_command ran in the repository as an argv" || no "verify did not run: $(ls "$R" "$R/dist")"
[ "$(jq -r '.result' "$rec")" = ok ] && [ "$(jq -r '.commit' "$rec")" = "$(git -C "$R" rev-parse "0.2.0^{commit}")" ] && [ "$(jq -r '.files["dist/SHA256SUMS"].sha256' "$rec")" = "$(sha256sum < "$R/dist/SHA256SUMS" | cut -d' ' -f1)" ] \
  && [ "$(stat -c %a "$rec")" = 600 ] && ok "the result is recorded under the state: tag commit, hashes, ok" || no "record: $(cat "$rec" 2>/dev/null)"
grep -q '"verb":"release:sign"' "$T/s/audit.log" && grep -q 'relgh 0.2.0 ok' "$T/s/audit.log" && ok "the signing is audited" || no "audit: $(tail -2 "$T/s/audit.log")"
rm -f "$R/verified.flag"; : > "$T/keygen.log"
setans '.release.sign.verify_command=["false"]'
out=$(pty $SIGN 2>&1); rc=$?
[ $rc = 1 ] && grep -q "verify_command exited 1" <<<"$out" && [ "$(jq -r '.result' "$rec")" = verify-failed ] && ok "a failing verify_command is recorded as verify-failed and exits 1" || no "verify fail: rc=$rc $out $(cat "$rec")"
out=$(FAKE_FAIL=1 pty $SIGN 2>&1); rc=$?
[ $rc = 1 ] && grep -q "signing dist/SHA256SUMS failed" <<<"$out" && [ "$(jq -r '.result' "$rec")" = sign-failed ] && [ ! -e "$R/dist/SHA256SUMS.sig" ] && ok "a failed ssh-keygen is recorded as sign-failed and leaves no stale signature" || no "sign fail: rc=$rc $out $(cat "$rec")"
git -C "$R" checkout -q parked
rm -rf "$T"
exit $fail
