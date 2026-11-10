#!/usr/bin/env bash
# The finishing verbs are resumable. `feature finish` and `release finish` push origin first and move the local branches after it; a death between
# the two (simulated here by a git shim that kills the verb right after its atomic push) used to leave origin finished and the local refs not,
# and the next run died at "behind or differs from origin" / "the tag exists already". The verbs now write an intent record under the state
# before they tag or push (gitflow.sh, intent_*): a re-run that finds it asks origin, and completes the local steps when origin holds exactly what
# the record intended, starts again when origin holds the old values (the push never happened), and refuses, naming the ref, when it holds
# anything else. `review apply` is in tests/test_review.sh. Offline: a bare repository is the origin, gh is a fake. Run: tests/test_resume.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
trap 'rm -rf "$T" "$HERMETIC"' EXIT
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects" "$T/bin"
cat > "$T/bin/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in *"pr create"*) echo https://example.net/acme/app/pull/1;; esac
G
# a git that kills its parent (the verb's shell) right after the real git ran, once, when the call contains $DIE_AFTER and $DIE_FLAG is not there yet
REALGIT=$(command -v git); export REALGIT
cat > "$T/bin/git" <<'S'
#!/usr/bin/env bash
"$REALGIT" "$@"; rc=$?
if [ -n "${DIE_AFTER:-}" ] && [ ! -e "${DIE_FLAG:-/nonexistent}" ]; then
  case " $* " in *"$DIE_AFTER"*) : > "$DIE_FLAG"; kill -9 "$PPID";; esac
fi
exit $rc
S
chmod +x "$T/bin/gh" "$T/bin/git"; export PATH=$T/bin:$PATH
R=$T/app; O=$T/origin.git; git init -q -b master "$R"; git init -q --bare "$O"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop && git -C "$R" remote add origin "$O" && git -C "$R" push -q origin master develop
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/app.json"
F="$DA feature"; REL="$DA release"
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
rev() { git -C "$1" rev-parse -q --verify "$2" 2>/dev/null || echo none; }
commit_on() { # BRANCH FILE: one commit on BRANCH, made in a temporary worktree
  local w; w=$(mktemp -d "$T/w.XXXXXX"); git -C "$R" worktree add -q "$w" "$1"; echo "$2" > "$w/$2"; git -C "$w" add -A; git -C "$w" commit -q -m "add $2"; git -C "$R" worktree remove --force "$w"
}
INTENT=$T/s/finish-intent

# --- feature finish, cut off after the push
$F start search >/dev/null 2>&1; commit_on feature/search s1.txt; $F verify search >/dev/null 2>&1
t=$($F finish search | tok); d0=$(rev "$R" develop)
DIE_AFTER="push -q --atomic" DIE_FLAG=$T/die-f $F finish search --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc != 0 ] && [ -e "$T/die-f" ] && [ "$(rev "$O" develop)" != "$d0" ] && [ "$(rev "$R" develop)" = "$d0" ] && [ -f "$INTENT/app-feature-search.json" ] \
  && ok "(setup) the finish died after the push: origin has the merge, develop here does not, the intent record is there" || no "setup feature: rc=$rc origin=$(rev "$O" develop) local=$(rev "$R" develop) $(ls "$INTENT" 2>&1)"
out=$($F finish search 2>&1); rc=$?; t2=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "was cut off" <<<"$out" && [ "$(rev "$R" develop)" = "$d0" ] && ok "a re-run says the finish was cut off, prints a plan token and changes nothing" || no "feature resume plan: rc=$rc $out"
out=$($F finish search --plan 000000000000 --approved go 2>&1); rc=$?
[ $rc != 0 ] && grep -q "the plan changed or --plan is missing" <<<"$out" && [ "$(rev "$R" develop)" = "$d0" ] && ok "a wrong token completes nothing" || no "feature resume wrong token: rc=$rc $out"
out=$($F finish search --plan "$t2" --approved "go on" 2>&1); rc=$?
[ $rc = 0 ] && [ "$(rev "$R" develop)" = "$(rev "$O" develop)" ] && [ "$(rev "$R" feature/search)" = none ] && [ ! -e "$INTENT/app-feature-search.json" ] \
  && ok "applying the plan moves develop to what origin has, deletes the feature branch and removes the record" || no "feature resume apply: rc=$rc $out"
[ "$(jq -rs '[.[] | select(.verb == "feature:finish")] | length' "$T/s/audit.log")" = 1 ] && ok "and the audit line is written once" || no "audit: $(cat "$T/s/audit.log")"
[ "$(jq -rs --arg r refs/heads/develop '[.[] | select(.ref == $r and .verb == "feature:finish" and .remote == "origin")] | length' "$T/s/ref-journal.jsonl")" = 1 ] \
  && [ "$(jq -rs --arg r refs/heads/develop '[.[] | select(.ref == $r and .verb == "feature:finish" and .remote == null)] | length' "$T/s/ref-journal.jsonl")" = 1 ] && ok "the ref journal has the push and the local move, once each" || no "journal"

# --- release finish, cut off after the push
commit_on develop late.txt
$REL verify 0.2.0 >/dev/null 2>&1
p=$($REL start 0.2.0 --date 2026-01-02 2>&1); t=$(tok <<<"$p"); $REL start 0.2.0 --date 2026-01-02 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL push 0.2.0 | tok); $REL push 0.2.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.2.0 | tok); m0=$(rev "$R" master)
DIE_AFTER="push -q --atomic" DIE_FLAG=$T/die-r $REL finish 0.2.0 --plan "$t" --approved go >/dev/null 2>&1; rc=$?
[ $rc != 0 ] && [ -e "$T/die-r" ] && [ "$(rev "$O" refs/tags/0.2.0)" != none ] && [ "$(rev "$R" master)" = "$m0" ] && [ "$(rev "$R" refs/tags/0.2.0)" != none ] && [ -f "$INTENT/app-release-0.2.0.json" ] \
  && ok "(setup) the release finish died after the push: origin has master and the tag, master here does not, the record is there" || no "setup release: rc=$rc $(ls "$INTENT" 2>&1)"
out=$($REL finish 0.2.0 2>&1); rc=$?; t2=$(tok <<<"$out")
grep -q "the tag 0.2.0 exists already" <<<"$out" && no "the re-run died at the tag that exists already" || ok "the re-run does not die at \"the tag exists already\""
[ $rc = 0 ] && [ -n "$t2" ] && grep -q "was cut off" <<<"$out" && [ "$(rev "$R" master)" = "$m0" ] && ok "it says the finish was cut off, prints a plan token and changes nothing" || no "release resume plan: rc=$rc $out"
out=$($REL finish 0.2.0 --plan "$t2" --approved "go on" 2>&1); rc=$?
nm=$(rev "$O" refs/heads/master)
[ $rc = 0 ] && [ "$(rev "$R" master)" = "$nm" ] && [ "$(rev "$R" develop)" = "$(rev "$O" refs/heads/develop)" ] && [ "$(rev "$R" release/0.2.0)" = none ] && [ ! -e "$INTENT/app-release-0.2.0.json" ] \
  && ok "applying the plan moves master and develop to what origin has, deletes the release branch and removes the record" || no "release resume apply: rc=$rc $out"
[ "$(rev "$R" "refs/tags/0.2.0^{commit}")" = "$nm" ] && ok "the tag stays on the merge origin has" || no "tag"
[ "$(jq -rs '[.[] | select(.verb == "release:finish")] | length' "$T/s/audit.log")" = 1 ] && ok "and the audit line is written once" || no "audit: $(cat "$T/s/audit.log")"
[ "$(jq -rs '[.[] | select(.ref == "refs/tags/0.2.0")] | length' "$T/s/ref-journal.jsonl")" = 2 ] && ok "the ref journal has the tag's push and its local line, once each" || no "journal: $(grep -c . "$T/s/ref-journal.jsonl")"

# --- origin holds something else than the record intended: refused, and what differs is named
commit_on develop late2.txt   # the changelog has nothing under Unreleased now: the start is told so (--allow-empty-notes)
$REL verify 0.3.0 >/dev/null 2>&1
p=$($REL start 0.3.0 --date 2026-01-03 --allow-empty-notes 2>&1); t=$(tok <<<"$p"); $REL start 0.3.0 --date 2026-01-03 --allow-empty-notes --plan "$t" --approved go >/dev/null 2>&1
t=$($REL push 0.3.0 | tok); $REL push 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
t=$($REL finish 0.3.0 | tok); m0=$(rev "$R" master); d0=$(rev "$R" develop)
DIE_AFTER="push -q --atomic" DIE_FLAG=$T/die-r2 $REL finish 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
rm0=$(jq -r '.refs[0].origin_old' "$INTENT/app-release-0.3.0.json"); rd0=$(jq -r '.refs[1].origin_old' "$INTENT/app-release-0.3.0.json")
git -C "$O" update-ref refs/heads/master "$(rev "$O" refs/heads/develop)"
out=$($REL finish 0.3.0 2>&1); rc=$?
[ $rc != 0 ] && grep -q "origin refs/heads/master is" <<<"$out" && [ "$(rev "$R" master)" = "$m0" ] && [ -f "$INTENT/app-release-0.3.0.json" ] \
  && ok "when origin holds another master the finish is refused, the ref is named and nothing changes" || no "differs: rc=$rc $out"
# --- origin at the old values: the push never happened, the record and the tag are dropped and the finish starts again
git -C "$O" update-ref refs/heads/master "$rm0"; git -C "$O" update-ref refs/heads/develop "$rd0"; git -C "$O" tag -d 0.3.0 >/dev/null
out=$($REL finish 0.3.0 2>&1); rc=$?; t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "stopped before anything reached origin" <<<"$out" && [ ! -e "$INTENT/app-release-0.3.0.json" ] && [ "$(rev "$R" refs/tags/0.3.0)" = none ] && [ "$(rev "$R" master)" = "$m0" ] \
  && ok "origin at the old values: the tag and the record are dropped and a fresh plan is made" || no "stale: rc=$rc $out"
$REL finish 0.3.0 --plan "$t" --approved go >/dev/null 2>&1
[ "$(rev "$R" master)" = "$(rev "$O" refs/heads/master)" ] && [ "$(rev "$R" master)" != "$m0" ] && [ "$(rev "$O" refs/tags/0.3.0)" != none ] && [ ! -e "$INTENT/app-release-0.3.0.json" ] \
  && ok "and that finish goes through" || no "stale then finish: master=$(rev "$R" master) origin=$(rev "$O" refs/heads/master)"
# --- a finish that is running is not mistaken for one that was cut off: its lock names a live process, a dead one is taken over
$F start busy >/dev/null 2>&1
sleep 60 & sp=$!
mkdir -p "$INTENT/app-feature-busy.json.run"; echo "$sp" > "$INTENT/app-feature-busy.json.run/pid"
out=$($F finish busy 2>&1); rc=$?
[ $rc != 0 ] && grep -q "another finish of feature-busy is running" <<<"$out" && ok "a second finish of a name whose lock names a live process is refused" || no "lock live: rc=$rc $out"
kill "$sp"; wait "$sp" 2>/dev/null
out=$($F finish busy 2>&1); rc=$?
[ $rc != 0 ] && ! grep -q "another finish" <<<"$out" && [ ! -d "$INTENT/app-feature-busy.json.run" ] && ok "and once that process is gone the lock is taken over and removed at exit" || no "lock dead: rc=$rc $out"
exit $fail
