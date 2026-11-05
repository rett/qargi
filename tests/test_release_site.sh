#!/usr/bin/env bash
# The documentation site of a release: the site answers, `release finish` naming the next step, the site line of `release status`,
# and `qargi release site VERSION`, which builds the tag's site with lib/site.py and commits it on the detached site branch through a
# temporary worktree, behind a plan token, and never pushes. The repository and its origin are temporary; nothing is contacted.
# Run: tests/test_release_site.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; ROOT=$PWD; DA=$ROOT/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
mkdir -p "$HOME" "$T/c/projects"
REL="$DA release"

# --- the answers: site.enabled, site.branch, site.config
base=$($DA project template demo | jq '.repo.url="https://github.com/example/demo"')
chk() { # name expected(0|1) jq-filter
  local f=$T/a.json; jq "$3" <<<"$base" > "$f"
  $DA project validate "$f" >/dev/null 2>&1; local rc=$?
  if [ "$rc" = "$2" ]; then ok "answers: $1"; else no "answers: $1 (exit $rc, wanted $2)"; fi
}
chk "site enabled, the branch defaults to a detached gh-pages" 0 '.repo.detached=["gh-pages"] | .site={enabled:true}'
chk "site with every answer"                0 '.repo.detached=["docs-site"] | .site={enabled:true, branch:"docs-site", config:"web/site.json"}'
chk "site enabled with no branch to use"    1 '.site={enabled:true}'
chk "site.branch that is not detached"      1 '.repo.detached=["gh-pages"] | .site={branch:"develop"}'
chk "site.enabled that is not a boolean"    1 '.repo.detached=["gh-pages"] | .site={enabled:"yes"}'
chk "site.config outside the branch"        1 '.repo.detached=["gh-pages"] | .site={config:"../site.json"}'
chk "site.config absolute"                  1 '.repo.detached=["gh-pages"] | .site={config:"/site.json"}'
chk "site.config not a json file"           1 '.repo.detached=["gh-pages"] | .site={config:"site/site.yml"}'
chk "site.config under the built folder"    1 '.repo.detached=["gh-pages"] | .site={config:"_site/site.json"}'
chk "site: an unknown key"                  1 '.repo.detached=["gh-pages"] | .site={enabled:true, out:"docs"}'
chk "site: not an object"                   1 '.site=true'

# --- a repository: 0.5.0 on master with the tool's lib (the site generator reads its commands.py), develop ahead with a change; an orphan
# gh-pages with the hand pages; the main checkout rests on the parking branch
R=$T/sitepub; git init -q -b master "$R"
cp -r "$ROOT/lib" "$R/lib"; cp "$ROOT/LICENSE" "$ROOT/README.md" "$R/"; echo 0.5.0 > "$R/VERSION"
printf '# Changelog\n\n## [Unreleased]\n\n## [0.5.0] - 2026-03-01\n\n### Added\n- the first thing\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" tag -a 0.5.0 -m 0.5.0 && git -C "$R" branch develop
git -C "$R" checkout -q develop
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n- a second thing\n\n## [0.5.0] - 2026-03-01\n\n### Added\n- the first thing\n' > "$R/CHANGELOG.md"
git -C "$R" commit -q -am two
git -C "$R" checkout -q --orphan gh-pages && git -C "$R" rm -rq --cached . && git -C "$R" clean -fdxq
mkdir -p "$R/site"; cp -r "$ROOT/tests/fixtures/site/pages" "$ROOT/tests/fixtures/site/static" "$ROOT/tests/fixtures/site/site.json" "$R/site/"
echo "hand pages and site configuration" > "$R/README.md"
mkdir -p "$R/_site/old"; echo "a build an earlier qargi committed" > "$R/_site/index.html"; echo old > "$R/_site/old/page.html"   # what the site branch carried before the fix
git -C "$R" add -A && git -C "$R" commit -q -m "Site: the hand pages"
git -C "$R" checkout -q -f -b scratch develop
P0=$(git -C "$R" rev-parse gh-pages)
ans() { jq -n --arg p "$R" --argjson site "$1" '{schema:1, project:"sitepub", methodology:"gitflow", test_command:"true", site:$site,
  repo:{url:"https://github.com/acme/sitepub", path:$p, long_lived:["master","develop","gh-pages"], detached:["gh-pages"]}}' > "$T/c/projects/sitepub.json"; }
ans '{"enabled": true}'
export QARGI_PROJECT=sitepub
cd "$T" || exit 1   # the lead works outside any run directory

# --- release finish ends with the next step, from the methodology's after_release data
tok() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p'; }
$REL verify 0.6.0 >/dev/null 2>&1 && $REL start 0.6.0 --date 2026-04-01 >/dev/null 2>&1 && $REL verify 0.6.0 >/dev/null 2>&1 || no "release 0.6.0 could not start: $($REL status 0.6.0 2>&1)"
t=$($REL finish 0.6.0 2>&1 | tok)
out=$($REL finish 0.6.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 0 ] && git -C "$R" rev-parse -q --verify refs/tags/0.6.0 >/dev/null && [ "$(tail -n 1 <<<"$out")" = "next: qargi release site 0.6.0" ] \
  && ok "release finish ends with: next: qargi release site 0.6.0" || no "finish: rc=$rc $out"
[ "$(git -C "$R" rev-parse gh-pages)" = "$P0" ] && ok "release finish leaves the site branch alone" || no "finish moved gh-pages"
python3 -I "$ROOT/lib/release_site.py" next "$T/c/projects/sitepub.json" gitflow 1.2.3 | grep -qx "next: qargi release site 1.2.3" && ok "the next line comes from the methodology data" || no "next from data"
jq '.site.enabled=false' "$T/c/projects/sitepub.json" > "$T/off.json"
[ -z "$(python3 -I "$ROOT/lib/release_site.py" next "$T/off.json" gitflow 1.2.3)" ] && ok "without site.enabled there is no next line" || no "next with the site off"

# --- release status: not built yet
out=$($REL status 0.6.0 2>&1)
grep -qx "site: not built for 0.6.0" <<<"$out" && ok "status: site: not built for 0.6.0" || no "status not built: $out"
ans '{"enabled": false}'
out=$($REL status 0.6.0 2>&1); ! grep -q "^site:" <<<"$out" && ok "status has no site line while site.enabled is not true" || no "status site off: $out"
out=$($REL site 0.6.0 2>&1) && no "release site ran with the site off" || { grep -q "is not enabled" <<<"$out" && ok "release site refuses while site.enabled is not true" || no "site off: $out"; }
ans '{"enabled": true}'

# --- release site: the plan
wts() { git -C "$R" worktree list | wc -l; }
out=$($REL site 0.6.0 2>&1); rc=$?; t=$(tok <<<"$out")
[ $rc = 0 ] && [ -n "$t" ] && grep -q "^build the documentation site of sitepub 0.6.0: the tree of tag 0.6.0" <<<"$out" && grep -q "hand pages of gh-pages (${P0:0:7}) in site/pages" <<<"$out" \
  && grep -q "^  changes: .*files\? changed" <<<"$out" && ok "the plan names the tag, the site branch and the change" || no "plan: rc=$rc $out"
[ "$(git -C "$R" rev-parse gh-pages)" = "$P0" ] && [ "$(wts)" = 1 ] && [ -z "$(find "$T/s" -maxdepth 1 -name 'release-*')" ] && ok "the plan changes nothing and leaves no worktree or extracted tag" || no "plan left: $(git -C "$R" worktree list) $(ls "$T/s")"
$REL site 0.6.0 --plan 000000000000 --approved go >/dev/null 2>&1 && no "a wrong token was accepted" || { [ "$(git -C "$R" rev-parse gh-pages)" = "$P0" ] && ok "a wrong plan token refuses" || no "wrong token moved gh-pages"; }
out=$($REL site 0.6.0 --hotfix 2>&1) && no "--hotfix accepted" || ok "--hotfix does not belong to release site"
out=$($REL site 0.9.0 2>&1) && no "a missing tag was built" || { grep -q "no tag 0.9.0" <<<"$out" && ok "refuses a version with no tag" || no "no tag: $out"; }

# --- release site: refused in a member run and a nested call
mkdir -p "$T/run/clone"; : > "$T/run/ability"; : > "$T/run/refs.before"
out=$(cd "$T/run/clone" && $REL site 0.6.0 2>&1); rc=$?
[ $rc = 2 ] && grep -q "not available in a member run" <<<"$out" && ok "refused (exit 2) in a member run" || no "member: rc=$rc $out"
out=$(QARGI_NESTED=1 $REL site 0.6.0 --plan "$t" --approved go 2>&1); rc=$?
[ $rc = 2 ] && [ "$(git -C "$R" rev-parse gh-pages)" = "$P0" ] && ok "refused (exit 2) in a nested call" || no "nested: rc=$rc $out"

# --- release site: refused while the site branch is checked out
git -C "$R" worktree add -q "$T/pages-wt" gh-pages
out=$($REL site 0.6.0 2>&1) && no "built with gh-pages checked out" || { grep -q "gh-pages is checked out in" <<<"$out" && ok "refuses while the site branch is checked out" || no "checked out: $out"; }
git -C "$R" worktree remove "$T/pages-wt"

# --- release site: apply
$REL site 0.6.0 --plan "$t" --approved "yes, commit the site" > "$T/o" 2>&1; rc=$?
P1=$(git -C "$R" rev-parse gh-pages)
[ $rc = 0 ] && [ "$P1" != "$P0" ] && [ "$(git -C "$R" rev-parse "$P1^")" = "$P0" ] && ok "applied: one commit on gh-pages" || no "apply: rc=$rc $(cat "$T/o")"
[ "$(git -C "$R" log -1 --format=%s gh-pages)" = "Site: built from release 0.6.0" ] && ok "the commit says which release it built" || no "subject: $(git -C "$R" log -1 --format=%s gh-pages)"
[ -z "$(git -C "$R" ls-tree -r --name-only gh-pages | grep '^_site/' || true)" ] && git -C "$R" cat-file -e "$P0:_site/index.html" \
  && ok "the built site is not committed: no _site/ on gh-pages, and the one the branch carried is removed" || no "_site/ on gh-pages: $(git -C "$R" ls-tree -r --name-only gh-pages | grep '^_site/')"
[ "$(git -C "$R" diff --name-only "$P1^" "$P1" | grep -v '^_site/')" = "site/site.json" ] && ok "the commit changes site/site.json (and removes _site/) and nothing else" || no "files of the commit: $(git -C "$R" diff --name-only "$P1^" "$P1")"
[ "$(git -C "$R" show gh-pages:site/site.json | jq -r .release)" = 0.6.0 ] && [ "$(git -C "$R" show gh-pages:site/site.json | jq -r .url)" = "https://docs.example.org/qargi/" ] \
  && ok "site.json records release 0.6.0 and keeps its other answers" || no "site.json: $(git -C "$R" show gh-pages:site/site.json)"
grep -q "^push it with: git -C .* push origin gh-pages" "$T/o" && no "a push command without an origin" || { grep -q "nothing was pushed" "$T/o" && grep -q "no origin remote" "$T/o" && ok "nothing is pushed; without origin it says so" || no "apply output: $(cat "$T/o")"; }
[ "$(git -C "$R" branch --show-current)" = scratch ] && [ -z "$(git -C "$R" status --porcelain)" ] && [ ! -e "$R/_site" ] && [ "$(wts)" = 1 ] \
  && ok "the main checkout is untouched and no worktree is left" || no "main checkout: $(git -C "$R" status --porcelain) $(git -C "$R" worktree list)"
grep -q '"verb":"release:site"' "$T/s/audit.log" && grep -q '"approved":"yes, commit the site"' "$T/s/audit.log" && ok "the apply is audited" || no "audit"
grep -q '"verb":"release:site".*"ref":"refs/heads/gh-pages"' "$T/s/ref-journal.jsonl" && ok "the branch move is in the ref journal" || no "journal: $(cat "$T/s/ref-journal.jsonl" 2>/dev/null)"
out=$($REL site 0.6.0 2>&1); rc=$?
[ $rc = 0 ] && grep -q "already the build of 0.6.0: nothing to commit" <<<"$out" && ! grep -q "plan token" <<<"$out" && ok "a second run finds nothing to commit" || no "rerun: rc=$rc $out"

# --- release status: built, then pushed
out=$($REL status 0.6.0 2>&1)
grep -qx "site: built at ${P1:0:7}, not pushed (no origin remote)" <<<"$out" && ok "status: site: built at SHA, not pushed (no origin)" || no "status built: $out"
git init -q --bare "$T/origin.git"; git -C "$R" remote add origin "$T/origin.git"; git -C "$R" push -q origin master develop 0.6.0
out=$($REL status 0.6.0 2>&1)
grep -qx "site: built at ${P1:0:7}, not pushed" <<<"$out" && ok "status: site: built at SHA, not pushed" || no "status not pushed: $out"
git -C "$R" push -q origin gh-pages
out=$($REL status 0.6.0 2>&1)
grep -qx "site: pushed" <<<"$out" && ok "status: site: pushed" || no "status pushed: $out"
out=$($REL status 0.5.0 2>&1); grep -qx "site: not built for 0.5.0" <<<"$out" && ok "another version is not built" || no "status 0.5.0: $out"

# --- release site from an older tag, with an origin: the push command; a hand page the tag's command line refutes stops the build
out=$($REL site 0.5.0 2>&1); t=$(tok <<<"$out")
$REL site 0.5.0 --plan "$t" --approved go > "$T/o" 2>&1
grep -q "^push it with: git -C $R push origin gh-pages\$" "$T/o" && [ "$(git -C "$R" rev-parse origin/gh-pages)" = "$P1" ] && ok "with an origin it prints the push command and pushes nothing" || no "push line: $(cat "$T/o")"
grep -q "^preview it before you push: " "$T/o" && ok "it tells the lead to preview the built site before pushing it" || no "no preview hint before the push"
P2=$(git -C "$R" rev-parse gh-pages)
git -C "$R" checkout -q gh-pages
printf -- '---\ntitle: Broken\ndescription: A page that names a command the release does not have, so that the build of the site refuses it.\n---\n\n## 1. Run\n\n```bash\nqargi nosuchverb\n```\n' > "$R/site/pages/broken.md"
git -C "$R" add -A && git -C "$R" commit -q -m "Site: a broken page" && git -C "$R" checkout -q scratch
P3=$(git -C "$R" rev-parse gh-pages)
out=$($REL site 0.6.0 2>&1); rc=$?
[ $rc = 1 ] && grep -q "did not build; nothing was changed" <<<"$out" && grep -q "nosuchverb" <<<"$out" && ! grep -q "plan token" <<<"$out" \
  && [ "$(git -C "$R" rev-parse gh-pages)" = "$P3" ] && [ "$(wts)" = 1 ] && ok "a build error refuses with the generator's report and changes nothing" || no "broken: rc=$rc $out"
[ "$P2" != "$P1" ] || no "0.5.0 was not built"

# --- the site answers point elsewhere: another branch and config
ans '{"enabled": true, "branch": "gh-pages", "config": "nowhere/site.json"}'
out=$($REL site 0.6.0 2>&1) && no "a missing site.config was used" || { grep -q "gh-pages has no nowhere/site.json" <<<"$out" && ok "refuses a site.config the branch lacks" || no "config: $out"; }

cd "$ROOT" || exit 1
shellcheck -x -S warning tests/test_release_site.sh lib/release.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
rm -rf "$T"; exit $fail
