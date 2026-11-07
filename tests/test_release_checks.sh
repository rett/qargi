#!/usr/bin/env bash
# The generic release checks of the answers release.version_files (other files that must carry the version: listed by `start`, shown by `status`
# and `verify`) and release.notes_file (the notes must mention every item of the changelog section: a warning in the plan of `push`).
# gh is never contacted. Run: tests/test_release_checks.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"
printf '#!/usr/bin/env bash\nexit 1\n' > "$T/gh"; chmod +x "$T/gh"; export QARGI_GH=$T/gh
mk() { # name release-answers-json: a repository with develop and an origin, the answers with test_command true
  R=$T/$1; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  jq -n --arg p "$R" --arg n "$1" --argjson r "${2:-{\}}" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true", release:$r}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
seal() { git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch -f develop && $REL verify 0.2.0 >/dev/null 2>&1
  git clone -q --bare "$R" "$T/$1.git" && git -C "$R" remote add origin "$T/$1.git"; }

# --- the answer
base=$($DA project template relchk | jq '.repo.url="https://github.com/acme/relchk"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"; $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then ok "answers: $1"; else no "answers: $1 (exit $rc, wanted $2)"; fi
}
chk "version_files as a list of paths"   0 '.release={version_files:["package.json","docs/version.txt"]}'
chk "version_files an empty list"        0 '.release={version_files:[]}'
chk "version_files a string"             1 '.release={version_files:"package.json"}'
chk "version_files an absolute path"     1 '.release={version_files:["/etc/x"]}'
chk "version_files a path outside"       1 '.release={version_files:["../x"]}'
chk "version_files a repeated path"      1 '.release={version_files:["a","a"]}'

# --- version_files: start lists the files that lack the new version
mk vf '{"version_files":["package.json","docs/v.txt","gone.txt"]}'; mkdir "$R/docs"
echo '{"version": "0.1.0"}' > "$R/package.json"; echo 'v0.2.10' > "$R/docs/v.txt"; seal vf
out=$($REL start 0.2.0 --date 2026-03-04 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^warning: release.version_files: package.json, docs/v.txt, gone.txt on release/0.2.0 do not contain 0.2.0: bump these on the release branch" <<<"$out" \
  && ! grep -q "yours to bump" <<<"$out" && ok "start lists the version files that lack the new version (0.2.10 is not 0.2.0, a missing file lacks it) and still creates the branch" || no "start list: rc=$rc $out"
out=$($REL status 0.2.0 2>&1)
grep -q "^warning: release.version_files: package.json, docs/v.txt, gone.txt on release/0.2.0 do not contain 0.2.0: bump these" <<<"$out" && ok "status shows the same check" || no "status: $out"
out=$($REL verify 0.2.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "^warning: release.version_files: package.json, docs/v.txt, gone.txt on release/0.2.0" <<<"$out" && ok "verify shows it too and keeps the suite's exit status" || no "verify: rc=$rc $out"
wt=$($REL fix 0.2.0 | sed -n 's/^worktree: //p')
echo '{"version": "0.2.0"}' > "$wt/package.json"; echo 'v0.2.0' > "$wt/docs/v.txt"; echo 'version=0.2.0' > "$wt/gone.txt"
git -C "$wt" add -A && git -C "$wt" commit -q -m "bump the version files"
out=$($REL status 0.2.0 2>&1)
grep -q "^version files (release.version_files): all 3 contain 0.2.0" <<<"$out" && ! grep -q "^warning: release.version_files" <<<"$out" && ok "once bumped on the release branch the check passes" || no "bumped: $out"

mk vfnone; seal vfnone
out=$($REL start 0.2.0 2>&1)
grep -q "yours to bump" <<<"$out" && ! grep -q "release.version_files" <<<"$out" && ! grep -q "release.version_files" <<<"$($REL status 0.2.0 2>&1)" && ok "no answer, no check: the old note stays" || no "no answer: $out"

mk vfself '{"version_files":["VERSION"]}'; seal vfself
out=$($REL start 0.2.0 2>&1)
grep -q "^version files (release.version_files): all 1 contain 0.2.0" <<<"$out" && ok "the version file itself is already bumped by start" || no "self: $out"

shellcheck -x -S warning tests/test_release_checks.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
