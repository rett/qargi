#!/usr/bin/env bash
# `qargi release status|verify` flag a tag with no GitHub release and a tagged commit without the release workflow.
# gh is a stub (QARGI_GH); GitHub is never contacted.
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

shellcheck -x -S warning tests/test_release_publish.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
