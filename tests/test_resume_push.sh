#!/usr/bin/env bash
# A push that exits non-zero may still have reached origin (the connection dropped after the server applied it). `feature finish` and `release finish`
# keep their intent record (and the release's local tag) when the push reports a failure, and say origin may hold the result; the re-run asks origin and
# either completes the finish (origin holds the new values) or starts it over (origin holds the old ones). A git shim makes the atomic push do the real
# push and exit 1 (PUSH_MODE=lie), or exit 1 without pushing (PUSH_MODE=fail). Offline: a bare repository is the origin, gh is a fake.
# Run: tests/test_resume_push.sh. The kill-after-push cases are in tests/test_resume.sh.
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
# shellcheck source=fixtures.sh
. tests/fixtures.sh
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
# PUSH_MODE=lie: the atomic push reaches origin and git exits 1 (the answer was lost); PUSH_MODE=fail: it exits 1 and origin is unchanged
REALGIT=$(command -v git); export REALGIT
cat > "$T/bin/git" <<'S'
#!/usr/bin/env bash
case " $* " in *" push -q --atomic "*) case "${PUSH_MODE:-}" in lie) "$REALGIT" "$@"; exit 1;; fail) exit 1;; esac;; esac
exec "$REALGIT" "$@"
S
chmod +x "$T/bin/gh" "$T/bin/git"; export PATH=$T/bin:$PATH
R=$T/app; O=$T/origin.git; git init -q -b master "$R"; git init -q --bare "$O"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$O" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"; REL="$DA release"
rev() { git -C "$1" rev-parse -q --verify "$2" 2>/dev/null || echo none; }
commit_on() { # BRANCH FILE: one commit on BRANCH, made in a temporary worktree
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"; echo "$2" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "add $2"; git -C "$R" worktree remove --force "$w"
}
INTENT=$T/s/finish-intent

# --- a push that exits non-zero: it may have reached origin (the answer was lost) or not; the record (and the release's tag) stay, and the re-run asks origin
$F start lie >/dev/null 2>&1; commit_on feature/lie l1.txt; $F verify lie >/dev/null 2>&1
t=$($F finish lie | tok); d0=$(rev "$R" develop)
out=$(PUSH_MODE=lie $F finish lie --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(rev "$O" develop)" != "$d0" ] && [ "$(rev "$R" develop)" = "$d0" ] && [ -f "$INTENT/app-feature-lie.json" ] && grep -q "origin may hold the merge anyway" <<<"$out" && ! grep -q "nothing was changed locally or on origin" <<<"$out" \
  && ok "feature: a push that reached origin but exited 1 keeps the record and says origin may hold the merge" || no "feature lie: rc=$rc $out"
out=$($F finish lie 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "was cut off" <<<"$out" && ok "the re-run asks origin and offers to complete the finish" || no "feature lie re-run: rc=$rc $out"
out=$($F finish lie --plan "$t2" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" develop)" = "$(rev "$O" develop)" ] && [ ! -e "$INTENT/app-feature-lie.json" ] && ok "and the finish completes: develop here is what origin has, the record is gone" || no "feature lie apply: rc=$rc $out"
$F start bad >/dev/null 2>&1; commit_on feature/bad b1.txt; $F verify bad >/dev/null 2>&1
t=$($F finish bad | tok); d0=$(rev "$R" develop); od=$(rev "$O" develop)
out=$(PUSH_MODE=fail $F finish bad --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(rev "$O" develop)" = "$od" ] && [ -f "$INTENT/app-feature-bad.json" ] && ok "feature: a push that really failed also keeps the record" || no "feature bad: rc=$rc $out"
out=$($F finish bad 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "stopped before anything reached origin" <<<"$out" && ! grep -q "was cut off" <<<"$out" && [ -f "$INTENT/app-feature-bad.json" ] && ok "the re-run finds origin unchanged and starts over with a fresh plan (the plan alone keeps the record)" || no "feature bad re-run: rc=$rc $out"
out=$($F finish bad --plan "$t2" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" develop)" = "$(rev "$O" develop)" ] && [ "$(rev "$O" develop)" != "$od" ] && [ ! -e "$INTENT/app-feature-bad.json" ] && ok "and that finish goes through" || no "feature bad apply: rc=$rc $out"
rel_ready() { # VERSION: a release branch ready to finish
  commit_on develop "r$1.txt"; $REL verify "$1" >/dev/null 2>&1
  p=$($REL start "$1" --date 2026-02-01 --allow-empty-notes 2>&1); t=$(tok <<<"$p"); $REL start "$1" --date 2026-02-01 --allow-empty-notes --plan "$t" --approved go >/dev/null 2>&1
  t=$($REL push "$1" | tok); $REL push "$1" --plan "$t" --approved go >/dev/null 2>&1
}
rel_ready 0.4.0
t=$($REL finish 0.4.0 | tok); m0=$(rev "$R" master)
out=$(PUSH_MODE=lie $REL finish 0.4.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(rev "$O" refs/tags/0.4.0)" != none ] && [ "$(rev "$R" refs/tags/0.4.0)" != none ] && [ "$(rev "$R" master)" = "$m0" ] && [ -f "$INTENT/app-release-0.4.0.json" ] && grep -q "origin may hold the release anyway" <<<"$out" \
  && ok "release: a push that reached origin but exited 1 keeps the record and the local tag" || no "release lie: rc=$rc $out"
out=$($REL finish 0.4.0 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "was cut off" <<<"$out" && ok "the re-run asks origin and offers to complete the release" || no "release lie re-run: rc=$rc $out"
out=$($REL finish 0.4.0 --plan "$t2" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] && [ "$(rev "$R" master)" != "$m0" ] && [ ! -e "$INTENT/app-release-0.4.0.json" ] && ok "and the release finish completes" || no "release lie apply: rc=$rc $out"
rel_ready 0.5.0
t=$($REL finish 0.5.0 | tok); m0=$(rev "$R" master)
out=$(PUSH_MODE=fail $REL finish 0.5.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && [ "$(rev "$O" refs/tags/0.5.0)" = none ] && [ -f "$INTENT/app-release-0.5.0.json" ] && [ "$(rev "$R" refs/tags/0.5.0)" != none ] && ok "release: a push that really failed keeps the record and the tag too" || no "release bad: rc=$rc $out"
out=$($REL finish 0.5.0 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "stopped before anything reached origin" <<<"$out" && [ -f "$INTENT/app-release-0.5.0.json" ] && [ "$(rev "$R" refs/tags/0.5.0)" != none ] && ok "the re-run finds origin unchanged and plans afresh (the plan alone keeps the tag and the record)" || no "release bad re-run: rc=$rc $out"
out=$($REL finish 0.5.0 --plan "$t2" --approved go 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] && [ "$(rev "$R" master)" != "$m0" ] && [ "$(rev "$O" refs/tags/0.5.0)" != none ] && [ ! -e "$INTENT/app-release-0.5.0.json" ] && ok "and that release goes through" || no "release bad apply: rc=$rc $out"
exit $fail
