#!/usr/bin/env bash
# The preflight of `qargi release start`: a man page's .TH line and an empty or missing changelog section refuse the start
# before anything changes; the first commit sets the .TH date and version. Run: tests/test_release_preflight.sh
set -u
cd "$(dirname "$0")/.." || exit 1
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"; n=0
mk() { # name: a repository with develop only (master too), man page and changelog set by the caller afterwards
  R=$T/$1; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
}
seal() { git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch -f develop && $REL verify 0.2.0 >/dev/null 2>&1; }
refuses() { # label expected-text-in-message
  local before out; before=$(git -C "$R" for-each-ref | md5sum)
  out=$($REL start 0.2.0 --date 2026-03-04 2>&1) && { no "$1: started"; return; }
  grep -q "$2" <<<"$out" && [ "$before" = "$(git -C "$R" for-each-ref | md5sum)" ] && ok "$1" || no "$1: $out"
}

mk good; mkdir "$R/man"; printf '.TH APP 1 "2026-01-01" "app 0.1.0"\n.SH NAME\napp\n' > "$R/man/app.1"
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && ok "a good project starts" || no "good start: $($REL start 0.2.0 2>&1)"
[ "$(git -C "$R" show release/0.2.0:man/app.1 | head -1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && [ "$(git -C "$R" rev-list --count develop..release/0.2.0)" = 1 ] && git -C "$R" show release/0.2.0:CHANGELOG.md | grep -q '^## \[0.2.0\] - 2026-03-04' && ok "the first commit sets the .TH date and version, with VERSION and the changelog" || no "th: $(git -C "$R" show release/0.2.0:man/app.1 | head -1)"

mk empthdr; mkdir "$R/man"; printf '.TH APP 1 "" "app 0.1.0"\n' > "$R/man/app.1"; printf '## [Unreleased]\n- x\n' > "$R/CHANGELOG.md"; seal
$REL start 0.2.0 --date 2026-03-04 >/dev/null 2>&1 && [ "$(git -C "$R" show release/0.2.0:man/app.1)" = '.TH APP 1 "2026-03-04" "app 0.2.0"' ] && ok "an empty date field is filled" || no "empty date"

mk noth; mkdir "$R/man"; printf '.SH NAME\napp\n' > "$R/man/app.1"; seal
refuses "a man page without a .TH line refuses" "man/app.1: it has no .TH line"
mk short; mkdir "$R/man"; printf '.TH APP 1\n' > "$R/man/app.1"; seal
refuses "a .TH line without date and version fields refuses" "man/app.1: its .TH line has no date and source"
mk nover; mkdir "$R/man"; printf '.TH APP 1 "2026-01-01" "app"\n' > "$R/man/app.1"; seal
refuses "a source field without a version refuses" "carries no version"

mk emptycl; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n\n## [0.1.0] - 2026-01-01\n- old\n' > "$R/CHANGELOG.md"; seal
refuses "an empty Unreleased refuses" "nothing under '## \[Unreleased\]'"
$REL start 0.2.0 --allow-empty-notes >/dev/null 2>&1 && ok "--allow-empty-notes waives it" || no "allow-empty"
mk nosect; printf '# Changelog\n\n## [0.1.0] - 2026-01-01\n- old\n' > "$R/CHANGELOG.md"; seal
refuses "a changelog without an Unreleased section refuses" "no '## \[Unreleased\]' section"

mk plain; seal
$REL start 0.2.0 >/dev/null 2>&1 && ok "a project with neither man page nor changelog is not checked" || no "plain: $($REL start 0.2.0 2>&1)"
rm -rf "$T"; exit $fail
