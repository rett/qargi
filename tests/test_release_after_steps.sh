#!/usr/bin/env bash
# The answer release.after_steps: a list of commands or reminders that `release finish` prints as "after the release:" lines and records
# under the state for `release status`; qargi never runs them. gh is a stub (QARGI_GH); GitHub is never contacted.
# Run: tests/test_release_after_steps.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; ROOT=$PWD; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://github.com/acme/relaf/pull/1;; *"release view"*) echo "release not found" >&2; exit 1;; esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh

# --- the answer
base=$($DA project template relaf | jq '.repo.url="https://github.com/acme/relaf"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"; $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then ok "answers: $1"; else no "answers: $1 (exit $rc, wanted $2)"; fi
}
chk "after_steps as a list of strings"  0 '.release={after_steps:["announce {version}","update the docs"]}'
chk "after_steps an empty list"         0 '.release={after_steps:[]}'
chk "after_steps a string"              1 '.release={after_steps:"announce"}'
chk "after_steps an empty step"         1 '.release={after_steps:[""]}'
chk "after_steps a step with a newline" 1 '.release={after_steps:["a\nb"]}'
chk "after_steps a number"              1 '.release={after_steps:[3]}'

# --- a repository with an origin, and a release through push and finish
R=$T/relaf; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git clone -q --bare "$R" "$T/origin.git" && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" fetch -q origin
git -C "$R" checkout -q -b parked
jq --arg p "$R" --arg t "$T" '.repo={url:"https://github.com/acme/relaf", path:$p, long_lived:["master","develop"]} | .test_command="true"
  | .release={after_steps:["announce {version} to the list", ("touch " + $t + "/ran-by-qargi"), "tag the docs repository for {version}"]}' <<<"$base" > "$T/c/projects/relaf.json"
export QARGI_PROJECT=relaf
cd "$T" || exit 1
$REL verify 0.2.0 >/dev/null 2>&1 && $REL start 0.2.0 --date 2026-01-02 >/dev/null 2>&1 || no "release 0.2.0 could not start"
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.2.0 | tok)
! grep -q "after the release" <<<"$($REL finish 0.2.0)" && ok "the finish plan does not show the steps yet (nothing is finished)" || no "plan shows steps"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "the release finishes" || no "finish: rc=$rc $out"
exp=$(printf 'after the release: announce 0.2.0 to the list\nafter the release: touch %s/ran-by-qargi\nafter the release: tag the docs repository for 0.2.0\n' "$T")
[ "$(grep '^after the release:' <<<"$out")" = "$exp" ] && ok "finish prints each step as an 'after the release:' line, {version} replaced, in order" || no "lines: $out"
[ ! -e "$T/ran-by-qargi" ] && ok "a step is never run" || no "a step was run"
rec=$T/s/release/relaf-0.2.0.after.json
[ "$(jq -r '.steps | length' "$rec")" = 3 ] && [ "$(jq -r '.steps[0]' "$rec")" = "announce 0.2.0 to the list" ] && [ "$(jq -r '.version' "$rec")" = 0.2.0 ] \
  && ok "the steps are recorded under the state (release/PROJECT-VERSION.after.json) for release status" || no "record: $(cat "$rec" 2>&1)"

# --- no steps: nothing is printed and nothing recorded
jq 'del(.release)' "$T/c/projects/relaf.json" > "$T/x.json" && mv "$T/x.json" "$T/c/projects/relaf.json"
git -C "$R" checkout -q develop 2>/dev/null; echo "- b" >> "$R/CHANGELOG.md"; git -C "$R" commit -q -am b; git -C "$R" checkout -q parked
git -C "$R" push -q origin develop 2>/dev/null
$REL verify 0.3.0 >/dev/null 2>&1; $REL start 0.3.0 --allow-empty-notes >/dev/null 2>&1 || no "release 0.3.0 could not start"
t=$($REL push 0.3.0 | tok); $REL push 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.3.0 | tok); out=$($REL finish 0.3.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && ! grep -q "after the release" <<<"$out" && [ ! -e "$T/s/release/relaf-0.3.0.after.json" ] && ok "without release.after_steps finish prints and records nothing of the kind" || no "no steps: rc=$rc $out"

cd "$ROOT" || exit 1
shellcheck -x -S warning tests/test_release_after_steps.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
