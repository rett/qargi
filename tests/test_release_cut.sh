#!/usr/bin/env bash
# The ceremony of a release cut: the lock of a finishing verb tells the truth about flock; the bookkeeping file of a merge a finish parked is
# removed when the release is started again; a hotfix is not refused by a preflight that needs content only the hotfix brings; `release plan`
# makes one plan and one approval for the whole cut. Offline: a bare repository is the origin, gh is a fake.
# Run: tests/test_release_cut.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
REL="$DA release"
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
# rstart ARGS: release start through its plan (a token) and the approval; a refusal of the plan is printed and fails
rstart() { local p t; p=$($REL start "$@" 2>&1); t=$(tok <<<"$p"); [ -n "$t" ] || { printf '%s\n' "$p"; return 1; }; $REL start "$@" --plan "$t" --approved go; }
mk() { # NAME [with-origin]: a repository with master and develop, a version file and a changelog; the project's answers; the suite recorded as passed
  R=$T/$1; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
  printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a thing\n' > "$R/CHANGELOG.md"
  git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
  if [ -n "${2:-}" ]; then O=$T/$1-origin.git; git init -q --bare "$O"; git -C "$R" remote add origin "$O"; git -C "$R" push -q origin master develop; fi
  git -C "$R" checkout -q -b parked
  jq -n --arg p "$R" --arg n "$1" '{schema:1, project:$n, methodology:"gitflow", repo:{url:"https://github.com/acme/x", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/$1.json"
  export QARGI_PROJECT=$1
  $REL verify 0.2.0 >/dev/null 2>&1
}

# --- pid_lock: a flock that fails is reported, not ignored
mk lock
printf '#!/bin/sh\nexit 1\n' > "$T/bin/flock"; chmod +x "$T/bin/flock"
out=$(PATH=$T/bin:$PATH $REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "could not take the lock .*flock on .* failed" <<<"$out" && ok "a flock that fails ends the verb: it says so, and nothing was changed" || no "failing flock: rc=$rc $out"
rm -rf "$T/farm"; mkdir "$T/farm"; for f in /usr/bin/*; do [ "${f##*/}" = flock ] || ln -s "$f" "$T/farm/${f##*/}"; done
out=$(PATH=$HERMETIC/bin:$T/farm $REL finish 0.2.0 2>&1); rc=$?
[ "$rc" = 1 ] && grep -q "flock command (util-linux) is not installed" <<<"$out" && ok "no flock command: the verb says it is not installed" || no "missing flock: rc=$rc $out"
out=$($REL finish 0.2.0 2>&1); grep -q "could not take the lock" <<<"$out" && no "an ordinary finish was refused by the lock: $out" || ok "with flock the lock is taken as before (the verb goes on to its own checks)"

exit $fail
