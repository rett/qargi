#!/usr/bin/env bash
# qargi project adopt: closes the safe gaps of an attached repository (missing long-lived branches, missing scaffold files on
# one new branch) behind a plan token, and nothing else. Hermetic: scratch repositories made with git init.
# Run: tests/test_adopt.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
unset QARGI_PROJECT
mkdir -p "$HOME" "$T/c"
cd "$T" || exit 1   # a member run is told by the working directory: the checks below must not depend on where the suite was started
tokof() { sed -n 's/^plan token: \([0-9a-f]*\).*/\1/p' <<<"$1"; }
state() { # a fingerprint of everything a refusal or a plan must leave alone: refs, the checked-out branch, the working tree
  git -C "$1" for-each-ref; git -C "$1" symbolic-ref -q HEAD; git -C "$1" status --porcelain
  find "$1" -path "$1/.git" -prune -o -type f -print | sort | xargs cat | sha256sum
}
attach() { # name dir: attach with a url so that the answers are stored
  local out tok
  out=$($DA project attach "$2" --name "$1" --url "https://github.com/acme/$1" 2>&1); tok=$(tokof "$out")
  $DA project attach "$2" --name "$1" --url "https://github.com/acme/$1" --plan "$tok" --approved go >/dev/null 2>&1 || echo "attach $1 failed: $out"
}

# --- A: only main and a README ---------------------------------------------------------------------------------------
A=$T/a; git init -q -b main "$A"; printf '# Alpha\n\nmine\n' > "$A/README.md"; git -C "$A" add -A; git -C "$A" commit -q -m first
git init -q --bare "$T/a.git"; git -C "$A" remote add origin "$T/a.git"
attach alpha "$A"
head0=$(git -C "$A" rev-parse main); st0=$(state "$A")
out=$($DA project adopt alpha 2>&1); tok=$(tokof "$out")
[ -n "$tok" ] && grep -q "^    develop$" <<<"$out" && ! grep -q "^    master$" <<<"$out" && ok "the plan lists the branch to create (develop; main stands for master)" || no "plan branches: $out"
grep -q "agent/adopt-gitflow" <<<"$out" && grep -q "^    CHANGELOG.md$" <<<"$out" && grep -q "^    CONTRIBUTING.md$" <<<"$out" && grep -q "^    .github/workflows/test.yml$" <<<"$out" && ! grep -q "^    README.md$" <<<"$out" \
  && ok "the plan lists exactly the missing files, on a new agent branch" || no "plan files: $out"
[ "$st0" = "$(state "$A")" ] && ! git -C "$A" rev-parse -q --verify develop >/dev/null && ok "showing the plan changes nothing" || no "plan changed the repository"
$DA project adopt alpha --plan deadbeef0000 --approved go >/dev/null 2>&1 && no "a wrong plan token was accepted" || ok "a wrong plan token is refused"
$DA project adopt alpha --plan "$tok" >/dev/null 2>&1
[ "$st0" = "$(state "$A")" ] && ok "a wrong token, or --plan without --approved, leaves the repository as it was" || no "refused apply changed the repository"
git -C "$A" commit -q --allow-empty -m moved
$DA project adopt alpha --plan "$tok" --approved go >/dev/null 2>&1 && no "the old token was accepted after the repository changed" || ok "the token changes when the repository changes"
git -C "$A" reset -q --hard "$head0"
out=$($DA project adopt alpha --plan "$tok" --approved "go ahead" 2>&1); rc=$?
[ $rc = 0 ] && ok "with the token and an approval it applies" || no "apply rc=$rc: $out"
[ "$(git -C "$A" rev-parse develop 2>/dev/null)" = "$head0" ] && ok "develop was created at the tip of the default branch" || no "develop: $(git -C "$A" branch -a)"
[ "$(git -C "$A" rev-parse main)" = "$head0" ] && [ "$(git -C "$A" symbolic-ref --short HEAD)" = main ] && [ -z "$(git -C "$A" status --porcelain)" ] && ok "main did not move, HEAD stays on it and the tree is clean" || no "main moved or tree dirty"
! git -C "$A" rev-parse -q --verify master >/dev/null && ok "no master was created next to main" || no "master created"
[ "$(git -C "$A" rev-parse agent/adopt-gitflow^)" = "$head0" ] && [ "$(git -C "$A" rev-list --count develop..agent/adopt-gitflow)" = 1 ] && ok "the files are one commit on agent/adopt-gitflow, cut from develop" || no "adopt branch shape"
files=$(git -C "$A" diff --name-only develop agent/adopt-gitflow | LC_ALL=C sort | tr '\n' ' ')
[ "$files" = ".github/workflows/test.yml .gitignore CHANGELOG.md CLAUDE.md CONTRIBUTING.md VERSION " ] && ok "only the missing scaffold files are in it" || no "files: $files"
[ "$(git -C "$A" show agent/adopt-gitflow:README.md)" = "$(git -C "$A" show main:README.md)" ] && git -C "$A" diff --quiet develop main && ok "the existing README and the long-lived branches are untouched" || no "README changed"
[ -z "$(git -C "$A" ls-tree -r --name-only develop | grep -v '^README.md$')" ] && ok "nothing was written on develop" || no "develop has the scaffold"
git -C "$A" log -1 --format=%B agent/adopt-gitflow | grep -q "CHANGELOG.md" && ok "the commit message names the files" || no "commit message"
[ -z "$(git -C "$T/a.git" for-each-ref)" ] && ok "nothing was pushed" || no "pushed"
grep -q "^    develop$\|created branch develop\|created.*develop" <<<"$out" && grep -qi "changelog format\|tag format\|CI" <<<"$out" && ok "the report names what was created and what is left for a human" || no "report: $out"
before=$(state "$A")
out=$($DA project adopt alpha 2>&1); rc=$?
[ $rc = 0 ] && grep -qi "nothing to do" <<<"$out" && ! grep -q "^plan token" <<<"$out" && ok "a second run reports nothing to do" || no "idempotence: rc=$rc $out"
out=$($DA project adopt alpha --plan "$tok" --approved "again" 2>&1); rc=$?
[ $rc = 0 ] && grep -qi "nothing to do" <<<"$out" && [ "$before" = "$(state "$A")" ] && ok "and applying again changes nothing" || no "second apply: rc=$rc $out"

# --- B: already complete (made by project new) ---------------------------------------------------------------------------
B=$T/b
out=$($DA project new beta --dir "$B" --url https://github.com/acme/beta 2>&1); tok=$(tokof "$out")
$DA project new beta --dir "$B" --url https://github.com/acme/beta --plan "$tok" --approved go >/dev/null 2>&1 || no "project new beta"
stb=$(state "$B")
out=$($DA project adopt beta 2>&1); rc=$?
[ $rc = 0 ] && grep -qi "nothing to do" <<<"$out" && [ "$stb" = "$(state "$B")" ] && ok "a complete repository has nothing to do" || no "complete: rc=$rc $out"

# --- C: dirty, detached, no commits, unattached, member run -----------------------------------------------------------------
C=$T/c1; git init -q -b main "$C"; echo x > "$C/README.md"; git -C "$C" add -A; git -C "$C" commit -q -m first
attach gamma "$C"
echo more >> "$C/README.md"; stc=$(state "$C")
out=$($DA project adopt gamma 2>&1); rc=$?
[ $rc = 2 ] && grep -qi "uncommitted\|dirty" <<<"$out" && [ "$stc" = "$(state "$C")" ] && ok "a dirty working tree is refused with exit 2" || no "dirty: rc=$rc $out"
printf 'untracked\n' > "$T/u"; git -C "$C" checkout -q -- README.md; cp "$T/u" "$C/new.txt"
$DA project adopt gamma >/dev/null 2>&1; [ $? = 2 ] && ok "an untracked file counts as dirty" || no "untracked"
rm "$C/new.txt"
git -C "$C" checkout -q --detach
out=$($DA project adopt gamma 2>&1); rc=$?
[ $rc = 2 ] && grep -qi "detached" <<<"$out" && ok "a detached HEAD is refused with exit 2" || no "detached: rc=$rc $out"
git -C "$C" checkout -q main
out=$($DA project adopt nosuch 2>&1); rc=$?
[ $rc = 2 ] && grep -qi "attach" <<<"$out" && ok "an unattached project is refused with exit 2" || no "unattached: rc=$rc $out"
mkdir "$T/run"; : > "$T/run/ability"; : > "$T/run/refs.before"
out=$(cd "$T/run" && $DA project adopt gamma 2>&1); rc=$?
[ $rc = 2 ] && grep -qi "member" <<<"$out" && [ -z "$(git -C "$C" branch --list develop)" ] && ok "a member run is refused with exit 2" || no "member: rc=$rc $out"
# no commits: the answers are stored while the repository still had one; point the project at an empty repository
E=$T/e; git init -q -b main "$E"
jq --arg p "$E" '.repo.path = $p' "$T/c/projects/gamma.json" > "$T/g.json" && cp "$T/g.json" "$T/c/projects/gamma.json"
out=$($DA project adopt gamma 2>&1); rc=$?
[ $rc = 2 ] && grep -qi "no commit" <<<"$out" && ok "a repository with no commits is refused with exit 2" || no "no commits: rc=$rc $out"

# --- D: an existing develop is never moved ------------------------------------------------------------------------------------
D=$T/d; git init -q -b main "$D"; echo d > "$D/README.md"; git -C "$D" add -A; git -C "$D" commit -q -m first
git -C "$D" checkout -q -b develop; echo more > "$D/work.txt"; git -C "$D" add -A; git -C "$D" commit -q -m "work on develop"; git -C "$D" checkout -q main
attach delta "$D"
dev0=$(git -C "$D" rev-parse develop); main0=$(git -C "$D" rev-parse main)
out=$($DA project adopt delta 2>&1); tok=$(tokof "$out")
! grep -q "^    develop$" <<<"$out" && grep -q "^    CHANGELOG.md$" <<<"$out" && ok "an existing develop is not in the plan" || no "plan: $out"
$DA project adopt delta --plan "$tok" --approved go >/dev/null 2>&1 || no "apply delta"
[ "$(git -C "$D" rev-parse develop)" = "$dev0" ] && [ "$(git -C "$D" rev-parse main)" = "$main0" ] && ok "develop and main did not move" || no "branches moved"
[ "$(git -C "$D" rev-parse agent/adopt-gitflow^)" = "$dev0" ] && git -C "$D" ls-tree -r --name-only agent/adopt-gitflow | grep -qx work.txt && ok "the adopt branch is cut from develop, not from main" || no "cut from"

# --- F: what exists in another form or other content is left alone -------------------------------------------------------------
F=$T/f; git init -q -b master "$F"; mkdir -p "$F/.github/workflows"
printf '# Changes\n\n* old style\n' > "$F/CHANGELOG"; printf 'readme\n' > "$F/readme.md"; printf '{"name":"x","version":"2.0.0"}\n' > "$F/package.json"
printf 'on: push\n' > "$F/.github/workflows/ci.yml"; printf 'node_modules\n' > "$F/.gitignore"
git -C "$F" add -A; git -C "$F" commit -q -m first; git -C "$F" tag 1.0; git -C "$F" tag release-2
attach phi "$F"
out=$($DA project adopt phi 2>&1); tok=$(tokof "$out")
grep -q "^    CONTRIBUTING.md$" <<<"$out" && grep -q "^    CLAUDE.md$" <<<"$out" && ! grep -q "^    CHANGELOG.md$" <<<"$out" && ! grep -q "^    README.md$" <<<"$out" && ! grep -q "^    VERSION$" <<<"$out" \
  && ! grep -q "^    .github/workflows/test.yml$" <<<"$out" && ! grep -q "^    .gitignore$" <<<"$out" && ok "a changelog, readme, version or CI in another form, and an existing .gitignore, are not duplicated" || no "plan: $out"
grep -qi "CHANGELOG" <<<"$out" && grep -qi "left for you\|left for" <<<"$out" && grep -qi "tag" <<<"$out" && ok "the skipped files and the tag and changelog format are listed as left for a human" || no "left: $out"
$DA project adopt phi --plan "$tok" --approved go >/dev/null 2>&1 || no "apply phi"
files=$(git -C "$F" diff --name-only master agent/adopt-gitflow | LC_ALL=C sort | tr '\n' ' ')
[ "$files" = "CLAUDE.md CONTRIBUTING.md " ] && git -C "$F" show master:CHANGELOG | grep -q "old style" && [ "$(git -C "$F" show agent/adopt-gitflow:.gitignore)" = node_modules ] && ok "only the missing files were written; existing ones are byte-identical" || no "files: $files"
[ "$(git -C "$F" rev-parse master)" = "$(git -C "$F" rev-parse agent/adopt-gitflow^)" ] && [ -n "$(git -C "$F" rev-parse -q --verify develop)" ] && ok "develop was created from master and the branch is cut from it" || no "develop"

# an existing CHANGELOG.md of its own is not touched either
G=$T/g; git init -q -b main "$G"; printf '# Changelog\n\nmine\n' > "$G/CHANGELOG.md"; git -C "$G" add -A; git -C "$G" commit -q -m first
attach gimel "$G"
out=$($DA project adopt gimel 2>&1); tok=$(tokof "$out")
$DA project adopt gimel --plan "$tok" --approved go >/dev/null 2>&1 || no "apply gimel"
[ "$(git -C "$G" show agent/adopt-gitflow:CHANGELOG.md)" = "$(printf '# Changelog\n\nmine\n')" ] && ! git -C "$G" diff --name-only develop agent/adopt-gitflow | grep -qx CHANGELOG.md && ok "an existing CHANGELOG.md is not modified" || no "changelog touched"
grep -qi "keep a changelog\|changelog format\|CHANGELOG.md" <<<"$out" && ok "its format is reported as a gap left for a human" || no "format gap: $out"

# the audit line, and a bad methodology
grep -q '"verb":"project:adopt"' "$T/s/audit.log" && ok "applying leaves an audit line" || no "audit"
$DA project adopt alpha --methodology nosuch >/dev/null 2>&1 && no "an unknown methodology was accepted" || ok "an unknown methodology is refused"
rm -rf "$T"
exit $fail
