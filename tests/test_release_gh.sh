#!/usr/bin/env bash
# `qargi release` talks to GitHub only through $QARGI_GH (a stub here), names the repository without a trailing .git, titles the
# pull request like the release, refuses to start a version whose tag exists, and leaves no temporary file behind.
# Run: tests/test_release_gh.sh
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
out=$($REL start 0.9.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the tag 0.9.0 exists already" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.9.0 >/dev/null && ok "release start refuses a version whose tag exists" || no "start with a tag: rc=$rc $out"
out=$($REL start 0.9.0 --hotfix 2>&1); rc=$?
[ $rc = 1 ] && grep -q "the tag 0.9.0 exists already" <<<"$out" && ok "and so does a hotfix start" || no "hotfix start with a tag: rc=$rc $out"

# push and finish name the repository without .git, go through the stub, and title the pull request like the release
$REL verify 0.2.0 >/dev/null 2>&1 && $REL start 0.2.0 --date 2026-01-02 >/dev/null 2>&1 && ok "a release starts" || no "start 0.2.0"
: > "$T/gh.log"
t=$($REL push 0.2.0 | tok); out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q -- "pr create --base master --head release/0.2.0 --title relgh 0.2.0 " "$T/gh.log" && ok "the pull request is titled like the release: project and version" || no "push rc=$rc: $out $(cat "$T/gh.log")"
t=$($REL finish 0.2.0 | tok); out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -qx -- "-R acme/relgh pr checks release/0.2.0" "$T/gh.log" && ok "finish asks for the checks of acme/relgh, without .git" || no "finish rc=$rc: $out $(cat "$T/gh.log")"

# a gh that is not there is looked for as $QARGI_GH, not as gh on the path: the branch is pushed, the pull request is left to you
$REL verify 0.3.0 >/dev/null 2>&1 && $REL start 0.3.0 --allow-empty-notes >/dev/null 2>&1 || no "start 0.3.0"
t=$($REL push 0.3.0 | tok); out=$(QARGI_GH=$T/nogh $REL push 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "pushed release/0.3.0, but gh is not installed" <<<"$out" && git -C "$T/origin.git" rev-parse -q --verify refs/heads/release/0.3.0 >/dev/null && ok "push without the stub's gh pushes and says gh is missing" || no "push without gh: rc=$rc $out"
t=$($REL finish 0.3.0 | tok); out=$(QARGI_GH=$T/nogh $REL finish 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "gh is needed to read the pull request's checks" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/tags/0.3.0 >/dev/null && ok "finish without gh refuses and tags nothing" || no "finish without gh: rc=$rc $out"

# publish leaves no notes file behind: on a plan, after a refused token, after a refusal before the plan
git -C "$R" tag -a 0.8.0 -m x master
$REL publish 0.2.0 >/dev/null 2>&1; $REL publish 0.8.0 >/dev/null 2>&1; $REL publish 0.2.0 --plan 000000000000 --approved go >/dev/null 2>&1
[ -z "$(find "$T/s" "$T/tmp" -name '.release-notes.*' 2>/dev/null)" ] && ok "release publish removes its notes file whatever way it ends" || no "a notes file is left: $(find "$T/s" "$T/tmp" -name '.release-notes.*')"
rm -rf "$T"
exit $fail
