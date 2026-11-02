#!/usr/bin/env bash
# `qargi feature verify` and `qargi release verify` run the test command without the project's cloud binding in the
# environment. Run: tests/test_verify_env.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects"
R=$T/app; git init -q -b master "$R"; echo 0.1.0 > "$R/VERSION"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" branch feature/f
jq -n --arg p "$R" --arg c "env > $T/env.out" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:$c}' > "$T/c/projects/app.json"
bound() { ANTHROPIC_PROFILE=p QARGI_CLOUD_WORKSPACE=wrkspc_x QARGI_CLOUD_PROJECT=app "$@"; }
check() { # label
  if [ -f "$T/env.out" ] && ! grep -Eq '^(ANTHROPIC_PROFILE|QARGI_CLOUD_WORKSPACE|QARGI_CLOUD_PROJECT)=' "$T/env.out"; then ok "$1: the suite runs without the cloud binding"; else no "$1: binding visible: $(grep -E '^(ANTHROPIC|QARGI_CLOUD)' "$T/env.out" 2>&1)"; fi
  rm -f "$T/env.out"
}
bound "$DA" feature verify f >/dev/null 2>&1; check "feature verify"
bound "$DA" release verify 0.2.0 >/dev/null 2>&1; check "release verify"
rm -rf "$T"; exit $fail
