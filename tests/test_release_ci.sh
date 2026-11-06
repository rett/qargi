#!/usr/bin/env bash
# `qargi release` and the pull request's CI: fix makes a worktree on the release branch and --push re-pushes it, push says "updated PR #N" when
# the pull request is open, status shows the checks and the checklist after the release, finish lists the checks and refuses on failing or
# pending ones unless --ignore-checks gives the person's words. GitHub is a stub ($QARGI_GH), never reached.
# Run: tests/test_release_ci.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s TMPDIR=$T/tmp GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects" "$T/s" "$T/tmp"
REL="$DA release"; tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
# the stub: files beside it say what GitHub answers. pr.num: an open pull request; checks.out and checks.rc: what `pr checks` prints and exits
# with; release.state: found or missing; assets.out: the names of the release's assets
cat > "$T/gh" <<G
#!/usr/bin/env bash
echo "\$*" >> "$T/gh.log"
case "\$*" in
  *"pr create"*) if [ -f "$T/pr.num" ]; then echo "a pull request for branch \"x\" into branch \"master\" already exists:" >&2; echo "https://github.com/acme/relci/pull/\$(cat "$T/pr.num")" >&2; exit 1; fi
                 echo https://github.com/acme/relci/pull/1;;
  *"pr list"*) [ ! -f "$T/pr.num" ] || echo "\$(cat "$T/pr.num") https://github.com/acme/relci/pull/\$(cat "$T/pr.num")";;
  *"pr checks"*) if [ -f "$T/nopr" ]; then echo 'no pull requests found for branch "x"' >&2; exit 1; fi
                 [ ! -f "$T/checks.out" ] || cat "$T/checks.out"; exit "\$(cat "$T/checks.rc" 2>/dev/null || echo 0)";;
  *"release view"*"--json assets"*) cat "$T/assets.out" 2>/dev/null;;
  *"release view"*) if [ "\$(cat "$T/release.state" 2>/dev/null)" = found ]; then echo "title"; else echo "release not found" >&2; exit 1; fi;;
esac
G
chmod +x "$T/gh"; export QARGI_GH=$T/gh
tab=$'\t'
setchecks() { printf '%s' "$2" > "$T/checks.out"; echo "$1" > "$T/checks.rc"; }
R=$T/relci; git init -q -b master "$R"
echo 0.1.0 > "$R/VERSION"; printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a change\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git clone -q --bare "$R" "$T/origin.git" && git -C "$R" remote add origin "$T/origin.git" && git -C "$R" fetch -q origin
git -C "$R" checkout -q -b parked
jq -n --arg p "$R" '{schema:1, project:"relci", methodology:"gitflow", repo:{url:"https://github.com/acme/relci.git", path:$p, long_lived:["master","develop"]}, test_command:"true"}' > "$T/c/projects/relci.json"
export QARGI_PROJECT=relci
setans() { jq "$1" "$T/c/projects/relci.json" > "$T/ans.tmp" && mv "$T/ans.tmp" "$T/c/projects/relci.json"; }

$REL verify 0.2.0 >/dev/null 2>&1 && $REL start 0.2.0 --date 2026-01-02 >/dev/null 2>&1 && ok "a release starts" || no "start 0.2.0"

# --- fix: a worktree under the state directory, a clear next step, the same worktree on a second run
out=$($REL fix 0.2.0 2>&1); rc=$?
WTP=$T/s/worktrees/relci/release/0.2.0
[ $rc = 0 ] && grep -qx "worktree: $WTP" <<<"$out" && [ "$(git -C "$WTP" rev-parse --abbrev-ref HEAD)" = release/0.2.0 ] && grep -q "release fix 0.2.0 --push" <<<"$out" \
  && ok "release fix makes a worktree on release/0.2.0, prints its path and the next step" || no "fix: rc=$rc $out"
out=$($REL fix 0.2.0 2>&1); rc=$?
[ $rc = 0 ] && grep -qx "worktree: $WTP" <<<"$out" && grep -q "checked out in $WTP already" <<<"$out" && ok "a second fix names the same worktree" || no "fix again: rc=$rc $out"
out=$($REL fix 9.9.9 2>&1); rc=$?
[ $rc = 1 ] && grep -q "no branch release/9.9.9" <<<"$out" && ok "fix of a branch that does not exist is refused" || no "fix nothing: rc=$rc $out"
out=$($REL start 0.2.0 --push 2>&1); rc=$?
[ $rc = 1 ] && grep -q -- "--push belongs to release fix" <<<"$out" && ok "--push belongs to fix alone" || no "start --push: rc=$rc $out"

# --- push opens the pull request the first time, and updates it when it is open
: > "$T/gh.log"; rm -f "$T/pr.num"
t=$($REL push 0.2.0 | tok); out=$($REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q "pushed release/0.2.0 and opened: https://github.com/acme/relci/pull/1" <<<"$out" && ok "the first push opens the pull request" || no "first push: rc=$rc $out"
echo 7 > "$T/pr.num"
echo fix > "$WTP/fixed.txt"; git -C "$WTP" add fixed.txt; git -C "$WTP" commit -q -m "A fix"
echo dirty >> "$WTP/fixed.txt"
out=$($REL fix 0.2.0 --push 2>&1); rc=$?
t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "pull request #7 of release/0.2.0 is open already" <<<"$out" && grep -q "warning: .*uncommitted changes" <<<"$out" && ok "fix --push is a push: the plan names the open pull request and warns of uncommitted changes" || no "fix --push plan: rc=$rc $out"
: > "$T/gh.log"
out=$($REL fix 0.2.0 --push --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q "updated PR #7" <<<"$out" && ! grep -q "pr create failed" <<<"$out" && ! grep -q "pr create" "$T/gh.log" \
  && [ "$(git -C "$T/origin.git" rev-parse release/0.2.0)" = "$(git -C "$R" rev-parse release/0.2.0)" ] && ok "re-pushing says updated PR #7, opens nothing and moves origin's branch" || no "update: rc=$rc $out $(cat "$T/gh.log")"
git -C "$WTP" checkout -q -- fixed.txt
# a pull request that cannot be listed but exists: the refusal of pr create names it
echo 8 > "$T/pr.num"; git -C "$WTP" commit -q --allow-empty -m "Another fix"
sed 's/^  \*"pr list"\*).*$/  *"pr list"*) exit 1;;/' "$T/gh" > "$T/gh2"; chmod +x "$T/gh2"
t=$($REL push 0.2.0 | tok); out=$(QARGI_GH=$T/gh2 $REL push 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && grep -q "updated PR #8" <<<"$out" && ! grep -q "pr create failed" <<<"$out" && ok "an existing pull request that pr list could not show is found from the refusal of pr create" || no "pr create refusal: rc=$rc $out"

# --- status: the checks of the pull request
setchecks 1 "build${tab}fail${tab}1m${tab}https://example.net/1
lint${tab}pass${tab}10s${tab}https://example.net/2
docs${tab}pending${tab}0${tab}https://example.net/3
"
out=$($REL status 0.2.0 2>&1)
grep -q "pull request checks of release/0.2.0: 1 failing, 1 pending, 1 passed" <<<"$out" && grep -qx "  check build: fail" <<<"$out" && grep -qx "  check lint: pass" <<<"$out" && grep -qx "  check docs: pending" <<<"$out" \
  && ok "status lists each check with pass, fail or pending" || no "status checks: $out"
rm -f "$T/checks.out"; touch "$T/nopr"
out=$($REL status 0.2.0 2>&1)
grep -q "warning: no pull request for release/0.2.0" <<<"$out" && ok "status says when there is no pull request" || no "status nopr: $out"
rm -f "$T/nopr"
out=$(QARGI_GH=$T/nogh $REL status 0.2.0 2>&1)
grep -q "warning: gh is not installed, so the pull request checks" <<<"$out" && ok "status without gh warns" || no "status nogh: $out"

# --- finish: the plan lists the checks and refuses while one fails or is pending
setchecks 1 "build${tab}fail${tab}1m${tab}https://example.net/1
lint${tab}pass${tab}10s${tab}https://example.net/2
"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "checks of the pull request of release/0.2.0 are failing" <<<"$out" && grep -qx "  check build: fail" <<<"$out" && [ -z "$(tok <<<"$out")" ] && ok "a failing check refuses the plan, which names the check and gives no token" || no "finish failing: rc=$rc $out"
setchecks 8 "build${tab}pending${tab}0${tab}https://example.net/1
"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "are pending" <<<"$out" && grep -q -- "--ignore-checks" <<<"$out" && ok "a pending check refuses the plan and names the way past" || no "finish pending: rc=$rc $out"
out=$($REL finish 0.2.0 --ignore-checks "" 2>&1); rc=$?
[ $rc = 1 ] && grep -q "needs the reason" <<<"$out" && ok "--ignore-checks needs words" || no "ignore empty: rc=$rc $out"
out=$($REL start 0.2.0 --ignore-checks x 2>&1); rc=$?
[ $rc = 1 ] && grep -q "belongs to release finish" <<<"$out" && ok "--ignore-checks belongs to finish alone" || no "start ignore: rc=$rc $out"
out=$($REL finish 0.2.0 --ignore-checks "the docs job is known to be slow" 2>&1); rc=$?
t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "ignored on your word: the docs job is known to be slow" <<<"$out" && grep -q -- '--ignore-checks "the docs job is known to be slow"' <<<"$out" && ok "with --ignore-checks the plan goes on, and the apply line carries the words" || no "finish ignore plan: rc=$rc $out"
# the token covers the words: another reason is another plan
out=$($REL finish 0.2.0 --ignore-checks "another reason" --plan "$t" --approved go 2>&1); rc=$?
[ $rc != 0 ] && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "a plan made for other words does not apply" || no "token for other words: rc=$rc $out"
# the apply reads the checks again: a check that fails after the plan refuses it
setchecks 0 "build${tab}pass${tab}1m${tab}https://example.net/1
"
t=$($REL finish 0.2.0 | tok)
setchecks 1 "build${tab}fail${tab}1m${tab}https://example.net/1
"
out=$($REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "checks of the pull request of release/0.2.0 are failing" <<<"$out" && ! git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && ok "a check that fails between plan and apply refuses the apply and tags nothing" || no "apply failing: rc=$rc $out"
# no gh: the plan warns, the apply refuses unless the words are given
out=$(QARGI_GH=$T/nogh $REL finish 0.2.0 2>&1); rc=$?
t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "warning: gh is not installed" <<<"$out" && ok "without gh the plan warns and goes on" || no "finish nogh plan: rc=$rc $out"
out=$(QARGI_GH=$T/nogh $REL finish 0.2.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 1 ] && grep -q "gh is needed to read the pull request's checks" <<<"$out" && ok "and the apply refuses" || no "finish nogh apply: rc=$rc $out"
# no pull request: a warning in the plan
touch "$T/nopr"
out=$($REL finish 0.2.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "warning: no pull request for release/0.2.0" <<<"$out" && ok "no pull request is a warning in the plan" || no "finish nopr: rc=$rc $out"
rm -f "$T/nopr"
# the apply with the words, over a failing check: the worktree of the fix is removed, the words are recorded
t=$($REL finish 0.2.0 --ignore-checks "reviewed by hand" | tok)
out=$($REL finish 0.2.0 --ignore-checks "reviewed by hand" --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.2.0 >/dev/null && grep -q "checks ignored on your word: reviewed by hand" <<<"$out" && grep -q 'checks ignored: reviewed by hand' "$T/s/audit.log" \
  && ok "finish with --ignore-checks merges, tags and records the words in its output and the audit log" || no "finish ignored: rc=$rc $out"
[ ! -e "$WTP" ] && ! git -C "$R" rev-parse -q --verify refs/heads/release/0.2.0 >/dev/null && ok "finish removed the fix worktree and the branch" || no "worktree left: $(git -C "$R" worktree list)"

# --- status after the release: the checklist
setans '.release.assets=["dist/app.tar.gz"] | .release.sign={key:"/nowhere", namespace:"relci", files:["dist/app.tar.gz"]} | .release.after_steps=["update the website for {version}","announce it"]'
echo missing > "$T/release.state"; : > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "after the release 0.2.0" <<<"$out" && grep -q "tag 0.2.0: pushed to origin" <<<"$out" && grep -q "GitHub release: MISSING (qargi release publish 0.2.0)" <<<"$out" && grep -q "after-steps (release.after_steps" <<<"$out" \
  && grep -q -- "- update the website for 0.2.0" <<<"$out" && grep -q -- "- announce it" <<<"$out" && ok "status after the release: tag pushed, release missing, the after-steps" || no "checklist missing: $out"
echo found > "$T/release.state"; echo "app.tar.gz" > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "GitHub release: published" <<<"$out" && grep -q "asset app.tar.gz: present" <<<"$out" && grep -q "signature app.tar.gz.sig: UNSIGNED" <<<"$out" && ok "a published release: the asset is present, its signature is not" || no "checklist found: $out"
printf 'app.tar.gz\napp.tar.gz.sig\n' > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "signature app.tar.gz.sig: attached" <<<"$out" && ok "an attached signature is said so" || no "checklist signed: $out"
: > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "asset app.tar.gz: MISSING from the release" <<<"$out" && ok "an asset that is not on the release is missing" || no "checklist asset missing: $out"
# a glob and a {version} entry are matched by their base name against the release's assets
setans '.release.assets=["dist/*.tar.gz","dist/app-{version}.zip","out/none-*.txt"]'
printf 'app.tar.gz\napp-0.2.0.zip\n' > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "asset \*.tar.gz: present (app.tar.gz)" <<<"$out" && grep -q "asset app-0.2.0.zip: present" <<<"$out" && grep -q "asset none-\*.txt: MISSING from the release" <<<"$out" && ! grep -q "asset app-{version}" <<<"$out" \
  && ok "a glob and a {version} entry of release.assets are matched against the assets of the release" || no "glob assets: $out"
: > "$T/assets.out"
out=$($REL status 0.2.0 2>&1)
grep -q "asset \*.tar.gz: MISSING from the release" <<<"$out" && grep -q "asset app-0.2.0.zip: MISSING from the release" <<<"$out" && ok "and are missing when no asset matches" || no "glob assets missing: $out"
setans '.release.assets=["dist/app.tar.gz"]'
git -C "$R" push -q origin :refs/tags/0.2.0 2>/dev/null || git -C "$T/origin.git" tag -d 0.2.0 >/dev/null
out=$($REL status 0.2.0 2>&1)
grep -q "tag 0.2.0: NOT on origin" <<<"$out" && ok "a tag that origin does not have is said so" || no "checklist tag: $out"
setans 'del(.release.after_steps)'
out=$($REL status 0.2.0 2>&1)
! grep -q "after-steps" <<<"$out" && ok "no after_steps, no such lines" || no "after steps without the answer: $out"
git -C "$R" checkout -q parked 2>/dev/null
rm -rf "$T"
exit $fail
