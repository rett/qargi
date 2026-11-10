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
[ -n "$tok" ] && grep -q "^    develop$" <<<"$out" && ! grep -q "^    master$" <<<"$out" && ! grep -q "share no history" <<<"$out" && ok "the plan lists the branch to create (develop; main stands for master), and no history gap in a normal repository" || no "plan branches: $out"
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
[ "$files" = ".github/workflows/test.yml .gitignore AGENTS.md CHANGELOG.md CLAUDE.md CONTRIBUTING.md Makefile VERSION " ] && ok "only the missing scaffold files are in it" || no "files: $files"
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
[ "$files" = "AGENTS.md CLAUDE.md CONTRIBUTING.md Makefile " ] && git -C "$F" show master:CHANGELOG | grep -q "old style" && [ "$(git -C "$F" show agent/adopt-gitflow:.gitignore)" = node_modules ] && ok "only the missing files were written; existing ones are byte-identical" || no "files: $files"
[ "$(git -C "$F" rev-parse master)" = "$(git -C "$F" rev-parse agent/adopt-gitflow^)" ] && [ -n "$(git -C "$F" rev-parse -q --verify develop)" ] && ok "develop was created from master and the branch is cut from it" || no "develop"

# an existing CHANGELOG.md of its own is not touched either
G=$T/g; git init -q -b main "$G"; printf '# Changelog\n\nmine\n' > "$G/CHANGELOG.md"; git -C "$G" add -A; git -C "$G" commit -q -m first
attach gimel "$G"
out=$($DA project adopt gimel 2>&1); tok=$(tokof "$out")
$DA project adopt gimel --plan "$tok" --approved go >/dev/null 2>&1 || no "apply gimel"
[ "$(git -C "$G" show agent/adopt-gitflow:CHANGELOG.md)" = "$(printf '# Changelog\n\nmine\n')" ] && ! git -C "$G" diff --name-only develop agent/adopt-gitflow | grep -qx CHANGELOG.md && ok "an existing CHANGELOG.md is not modified" || no "changelog touched"
grep -qi "keep a changelog\|changelog format\|CHANGELOG.md" <<<"$out" && ok "its format is reported as a gap left for a human" || no "format gap: $out"

# a changelog with its own headings (release.changelog.unreleased) is not "not Keep a Changelog", and release.version_file none adds no VERSION
H=$T/h; git init -q -b main "$H"; printf '# Changes\n\n## Next\n\n- x\n' > "$H/CHANGELOG.md"; git -C "$H" add -A; git -C "$H" commit -q -m first
attach hay "$H"
out=$($DA project adopt hay 2>&1); echo "$out" | grep -qi "no '## \[Unreleased\]' heading" && ok "by default a changelog without '## [Unreleased]' is a format gap" || no "default gap: $out"
jq '.release = {version_file: "none", changelog: {unreleased: "## Next", released: "## {version}"}}' "$T/c/projects/hay.json" > "$T/hay.json" && mv "$T/hay.json" "$T/c/projects/hay.json"
out=$($DA project adopt hay 2>&1)
! grep -qi "format" <<<"$out" && ! grep -q "^    VERSION$" <<<"$out" && grep -q "^    CONTRIBUTING.md$" <<<"$out" && ok "with the answers, the changelog's own heading is found and no VERSION file is planned" || no "template gap: $out"
# declared settings are not gaps: release.version_file none is information, apart from what is left for the owner to judge
! grep -q "version_file" <<<"$(sed -n '/left for you/,$p' <<<"$out")" && grep -q "noted, not gaps" <<<"$out" && grep -q "declared: VERSION (not written: release.version_file is none" <<<"$out" \
  && ok "release.version_file none is printed as information, not under left for you to judge" || no "declared setting: $out"
# a versioned unreleased heading right after a release is information too: the heading is started by the next change
V=$T/v; git init -q -b main "$V"; printf '# Changes\n\n## 1.2.3 (2026-01-01)\n\n- x\n' > "$V/CHANGELOG.md"; git -C "$V" add -A; git -C "$V" commit -q -m first
attach vee "$V"
out=$($DA project adopt vee 2>&1); grep -qi "no '## \[Unreleased\]' heading" <<<"$out" && ok "by default a released-only changelog is a format gap" || no "versioned default: $out"
jq '.release = {changelog: {unreleased: "## {version} (unreleased)", released: "## {version} ({date})"}}' "$T/c/projects/vee.json" > "$T/vee.json" && mv "$T/vee.json" "$T/c/projects/vee.json"
out=$($DA project adopt vee 2>&1)
grep -q "noted, not gaps" <<<"$out" && grep -q "changelog: CHANGELOG.md (no unreleased section yet; the last release is 1.2.3" <<<"$out" && ! grep -q -- "- format:" <<<"$out" \
  && ok "adopt: no unreleased section right after a release is information with the last release, not a format gap" || no "versioned adopt: $out"
out=$($DA project attach "$V" --name vee 2>&1); grep -q -- "- format:" <<<"$out" && no "versioned attach: a gap: $out"
grep -q "^noted, not gaps (nothing to close):" <<<"$out" && grep -q "no unreleased section yet; the last release is 1.2.3" <<<"$out" && ok "attach: the same, under information after the gaps" || no "versioned attach: $out"
# --- H: the development environment. A justfile without the targets, a CLAUDE.md of its own; and a README that already has the section ---
H=$T/h2; git init -q -b main "$H"; printf 'default:\n    @true\n' > "$H/justfile"; printf '# Mine\n' > "$H/CLAUDE.md"; git -C "$H" add -A; git -C "$H" commit -q -m first
attach heth "$H"
out=$($DA project attach "$H" --name heth 2>&1)
grep -q "^development environment found: section in none; task runner just; bootstrap none; doctor none" <<<"$out" && grep -q "  - env: bootstrap target" <<<"$out" && grep -q "  - env: doctor target" <<<"$out" \
  && ! grep -q "file: Makefile" <<<"$out" && grep -q "file: AGENTS.md" <<<"$out" && ok "attach reports what environment detection found and lists the missing pieces" || no "attach env: $out"
out=$($DA project adopt heth 2>&1); tok=$(tokof "$out")
grep -q "^    AGENTS.md$" <<<"$out" && ! grep -q "^    Makefile$" <<<"$out" && grep -q "env: bootstrap target (not written" <<<"$out" && grep -q "env: doctor target (not written" <<<"$out" \
  && ok "adopt drafts the section and leaves the targets of an existing runner to the owner" || no "adopt env plan: $out"
$DA project adopt heth --plan "$tok" --approved go >/dev/null 2>&1 || no "apply heth"
a=$(git -C "$H" show agent/adopt-gitflow:AGENTS.md)
grep -q '^## Development environment$' <<<"$a" && grep -q 'git, just,' <<<"$a" && ! grep -q 'bootstrap`\|doctor`' <<<"$a" && ! grep -q '@@' <<<"$a" && ! grep -qiE '(^|[^[:alnum:]])qargi([^[:alnum:]]|$)' <<<"$a" \
  && [ "$(git -C "$H" show agent/adopt-gitflow:CLAUDE.md 2>&1)" = "# Mine" ] && ok "the drafted section names the runner but no bootstrap or doctor command the repository lacks, nothing about qargi, and CLAUDE.md is untouched" || no "drafted AGENTS.md: $a"
# the environment gaps are measured against the effective environment: a command the answers declare (env.bootstrap_command) is not a missing target
H3=$T/h3; git init -q -b main "$H3"; printf 'default:\n    @true\n' > "$H3/justfile"; git -C "$H3" add -A; git -C "$H3" commit -q -m first
attach heth3 "$H3"
out=$($DA project adopt heth3 2>&1); grep -q "env: bootstrap target (not written" <<<"$out" && grep -q "env: doctor target (not written" <<<"$out" && ok "without env answers both targets are missing" || no "env answers absent: $out"
jq '.env = {bootstrap_command: "just setup-all", doctor_command: "just verify-all"}' "$T/c/projects/heth3.json" > "$T/h3.json" && mv "$T/h3.json" "$T/c/projects/heth3.json"
out=$($DA project adopt heth3 2>&1); tok=$(tokof "$out")
! grep -q "env: bootstrap target" <<<"$out" && ! grep -q "env: doctor target" <<<"$out" && ok "adopt: declared env.bootstrap_command and env.doctor_command close the target gaps" || no "env answers adopt: $out"
out=$($DA project attach "$H3" --name heth3 2>&1)
! grep -q "env: bootstrap target" <<<"$out" && ! grep -q "env: doctor target" <<<"$out" && grep -q "bootstrap just setup-all; doctor just verify-all" <<<"$out" && ok "attach: the same, and the environment line shows the declared commands" || no "env answers attach: $out"
$DA project adopt heth3 --plan "$tok" --approved go >/dev/null 2>&1 || no "apply heth3"
a=$(git -C "$H3" show agent/adopt-gitflow:AGENTS.md)
grep -q '`just setup-all`' <<<"$a" && grep -q '`just verify-all`' <<<"$a" && ok "the AGENTS.md written names the declared commands" || no "heth3 AGENTS.md: $a"
I=$T/i; git init -q -b main "$I"; printf '# Iota\n\n## Setup\n\nmake bootstrap\n' > "$I/README.md"; printf 'bootstrap:\n\t@true\ndoctor:\n\t@true\n' > "$I/Makefile"
git -C "$I" add -A; git -C "$I" commit -q -m first
attach iota "$I"
out=$($DA project adopt iota 2>&1)
! grep -q "^    AGENTS.md$" <<<"$out" && ! grep -q "^    Makefile$" <<<"$out" && ! grep -q "env:" <<<"$out" && ok "a repository that has the section and the targets gets neither file and no gap" || no "adopt iota: $out"
J=$T/j; git init -q -b main "$J"; printf '# Jot\n' > "$J/AGENTS.md"; printf 'doctor:\n\t@true\n' > "$J/Makefile"; git -C "$J" add -A; git -C "$J" commit -q -m first
attach jot "$J"
out=$($DA project adopt jot 2>&1)
grep -q "env: Development environment section (not written" <<<"$out" && grep -q "env: bootstrap target (not written" <<<"$out" && ! grep -q "env: doctor target" <<<"$out" && ok "an AGENTS.md without the section and a Makefile without bootstrap are listed, not edited" || no "adopt jot: $out"

# --- L: the repository's own instructions: said, not edited; the changelog sentence follows the project's headings; --show prints what the token covers ---
Lb=$T/l; git init -q -b main "$Lb"; printf '# Lam\n' > "$Lb/README.md"; git -C "$Lb" add -A; git -C "$Lb" commit -q -m first
attach lam "$Lb"
jq '.release = {changelog: {unreleased: "## Next", released: "## {version}", numbered: true}}' "$T/c/projects/lam.json" > "$T/lam.json" && mv "$T/lam.json" "$T/c/projects/lam.json"
out=$($DA project adopt lam --show 2>&1); tok=$(tokof "$out")
grep -q "^covered by the plan token" <<<"$out" && grep -q "^file CONTRIBUTING.md:$" <<<"$out" && grep -q '^  | - Every user-visible change gets a changelog entry as the next numbered item under `Next`, in the same commit as the change\.$' <<<"$out" \
  && grep -q '^  | ## Next$' <<<"$out" && ! grep -q 'Unreleased' <<<"$out" && ok "L: --show prints the content of each file, and the changelog sentence and the new changelog follow release.changelog (heading Next, numbered)" || no "L show: $out"
sum=$(sed -n '/^file VERSION:$/,/^$/p' <<<"$out" | sed -n 's/^  | //p' | sha256sum | cut -d' ' -f1)
grep -q "\"dest\": \"VERSION\"" <<<"$out" && grep -q "\"sha256\": \"$sum\"" <<<"$out" && ok "L: the sha256 in the basis the token covers is that of the content shown" || no "L sha: $sum"
$DA project adopt lam --show --approved go >/dev/null 2>&1; [ $? = 2 ] && ok "L: --show with --approved is a usage error" || no "L show approved"
$DA project adopt lam --plan "$tok" --approved go >/dev/null 2>&1 || no "L apply"
c=$(git -C "$Lb" show agent/adopt-gitflow:CLAUDE.md); k=$(git -C "$Lb" show agent/adopt-gitflow:CHANGELOG.md)
grep -q 'entry as the next numbered item under `Next`, in the same commit\.' <<<"$c" && ! grep -q 'Unreleased' <<<"$c" && grep -q '^## Next$' <<<"$k" && ! grep -q 'Unreleased' <<<"$k" && ok "L: the CLAUDE.md written says where entries go from the stored headings" || no "L claude: $c"
jq 'del(.release)' "$T/c/projects/lam.json" > "$T/lam.json" && mv "$T/lam.json" "$T/c/projects/lam.json"
M2=$T/m2; git init -q -b main "$M2"; printf '# Mu\n' > "$M2/README.md"; git -C "$M2" add -A; git -C "$M2" commit -q -m first
attach mu "$M2"; out=$($DA project adopt mu --show 2>&1)
grep -q '^  | - Every user-visible change gets a changelog entry under `\[Unreleased\]`, in the same commit as the change\.$' <<<"$out" && grep -q '^  | ## \[Unreleased\]$' <<<"$out" && ok "L: without release answers the sentence and the heading are the Keep a Changelog ones" || no "L default: $out"
grep -q 'make bootstrap' <<<"$out" && grep -q 'make doctor' <<<"$out" && ok "L: a repository with no task runner still gets the conventional commands (the Makefile written has the targets)" || no "L conventional: $out"
# a CLAUDE.md of its own and no AGENTS.md: AGENTS.md gets the environment section only, and the import line is for the owner
Lc=$T/lc; git init -q -b main "$Lc"; printf '# Mine\n\nmy rules\n' > "$Lc/CLAUDE.md"; git -C "$Lc" add -A; git -C "$Lc" commit -q -m first
attach lcc "$Lc"; out=$($DA project adopt lcc 2>&1); tok=$(tokof "$out")
grep -q "the repository's own instructions (adopt edits no existing file):" <<<"$out" && grep -q "    - CLAUDE.md: exists and is not edited; adopt writes AGENTS.md with its Development environment section only" <<<"$out" \
  && grep -q '    - CLAUDE.md: has no `@AGENTS.md` import line: add it' <<<"$out" && ok "L: a CLAUDE.md of its own is named, with what adopt writes and the import line left to the owner" || no "L claude only: $out"
$DA project adopt lcc --plan "$tok" --approved go >/dev/null 2>&1 || no "L apply lcc"
a=$(git -C "$Lc" show agent/adopt-gitflow:AGENTS.md)
grep -q '^## Development environment$' <<<"$a" && ! grep -q 'Instructions for coding agents' <<<"$a" && [ "$(git -C "$Lc" show agent/adopt-gitflow:CLAUDE.md)" = "$(printf '# Mine\n\nmy rules')" ] && ok "L: that AGENTS.md is the environment section only, and CLAUDE.md is as it was" || no "L agents: $a"
# an AGENTS.md of its own, CLAUDE.md missing / both present
Ld=$T/ld; git init -q -b main "$Ld"; printf '# Mine\n\n## Development environment\n\nmake bootstrap\n' > "$Ld/AGENTS.md"; git -C "$Ld" add -A; git -C "$Ld" commit -q -m first
attach ldd "$Ld"; out=$($DA project adopt ldd 2>&1)
grep -q "    - AGENTS.md: exists and is not edited; adopt writes CLAUDE.md, which imports it (@AGENTS.md)" <<<"$out" && ! grep -q "import line" <<<"$out" && ok "L: an AGENTS.md of its own is named, and the CLAUDE.md written imports it" || no "L agents only: $out"
Le=$T/le; git init -q -b main "$Le"; printf '# A\n' > "$Le/AGENTS.md"; printf '@AGENTS.md\n' > "$Le/CLAUDE.md"; git -C "$Le" add -A; git -C "$Le" commit -q -m first
attach lee "$Le"; out=$($DA project adopt lee 2>&1)
grep -q "    - AGENTS.md, CLAUDE.md: both exist: adopt writes neither and edits neither" <<<"$out" && ! grep -q "import line" <<<"$out" && ok "L: with both present adopt says it writes neither, and an existing import line is not asked for" || no "L both: $out"
out=$($DA project adopt alpha 2>&1); ! grep -q "own instructions" <<<"$out" && ok "L: a repository with neither file gets no instructions list" || no "L neither: $out"

# --- O: accepted deviations (methodology_accepted, the lead's): apart from the open gaps, left out of what adopt writes, and a gone gap says so ---
Ob=$T/o; git init -q -b main "$Ob"; printf '# Omi\n' > "$Ob/README.md"; git -C "$Ob" add -A; git -C "$Ob" commit -q -m first
attach omi "$Ob"
acc='[{"gap":"file: CONTRIBUTING.md","reason":"the workflow lives in the wiki","date":"2026-11-10"},{"gap":"branch: develop","reason":"trunk based","date":"2026-11-10"},{"gap":"file: GONE.md","reason":"was missing once","date":"2026-10-01"}]'
$DA project set omi methodology_accepted '[{"gap":"x"}]' >/dev/null 2>&1 && no "O: an entry without reason and date was accepted" || ok "O: methodology_accepted entries need gap, reason and date"
$DA project set omi methodology_accepted '[{"gap":"file: A","reason":"r","date":"yesterday"}]' >/dev/null 2>&1 && no "O: a bad date was accepted" || ok "O: the date is YYYY-MM-DD"
(cd "$T/run" && $DA project set omi methodology_accepted "$acc" >/dev/null 2>&1); [ $? = 2 ] && ! jq -e 'has("methodology_accepted")' "$T/c/projects/omi.json" >/dev/null && ok "O: a member run may not record accepted deviations" || no "O: member set"
$DA project set omi methodology_accepted "$acc" >/dev/null 2>&1 && $DA project validate omi >/dev/null 2>&1 && ok "O: the lead records them" || no "O: set"
out=$($DA project attach "$Ob" --name omi 2>&1); gapsec=$(sed -n '/^gaps against/,/^accepted deviations/p' <<<"$out")
! grep -q -- "- file: CONTRIBUTING.md" <<<"$gapsec" && ! grep -q -- "- branch: develop" <<<"$gapsec" && grep -q -- "- file: README.md\|- file: VERSION" <<<"$gapsec" \
  && grep -q "^accepted deviations (set by the lead in methodology_accepted; not open gaps):" <<<"$out" && grep -q -- "^  - file: CONTRIBUTING.md (accepted: the workflow lives in the wiki; 2026-11-10)$" <<<"$out" \
  && grep -q -- "^  - file: GONE.md (accepted, no longer applies: was missing once; 2026-10-01)$" <<<"$out" && ok "O: attach lists the accepted ones apart, drops them from the gaps, and says a gone gap no longer applies" || no "O attach: $out"
out=$($DA project adopt omi 2>&1); tok=$(tokof "$out")
! grep -q "^    CONTRIBUTING.md$" <<<"$out" && ! grep -q "^    develop$" <<<"$out" && grep -q "^    README.md$\|^    VERSION$" <<<"$out" && grep -q "^  accepted deviations (set by the lead" <<<"$out" \
  && grep -q -- "^    - file: CONTRIBUTING.md (accepted: the workflow lives in the wiki; 2026-11-10)$" <<<"$out" && grep -q -- "^    - file: GONE.md (accepted, no longer applies" <<<"$out" \
  && ok "O: adopt leaves an accepted file and branch out of the plan, lists them apart, and a gone gap says so" || no "O adopt: $out"
$DA project adopt omi --plan "$tok" --approved go >/dev/null 2>&1 || no "O: apply"
git -C "$Ob" rev-parse -q --verify develop >/dev/null && no "O: the accepted branch was created" || ok "O: the accepted branch was not created"
git -C "$Ob" ls-tree -r --name-only agent/adopt-gitflow 2>/dev/null | grep -qx "CONTRIBUTING.md" && no "O: the accepted file was written" || ok "O: the accepted file was not written"
jq '.methodology_accepted |= map(select(.gap != "file: GONE.md"))' "$T/c/projects/omi.json" > "$T/omi.json" && mv "$T/omi.json" "$T/c/projects/omi.json"
out=$($DA project adopt omi 2>&1); grep -q "accepted: the workflow lives in the wiki" <<<"$out" && ! grep -q "GONE.md" <<<"$out" && ok "O: the list follows the answers" || no "O list: $out"

# --- K: a master made as a snapshot has no merge base with develop: adopt names it, joins nothing and changes no branch ---
K=$T/k; git init -q -b develop "$K"; printf '# Kappa\n' > "$K/README.md"; git -C "$K" add -A; git -C "$K" commit -q -m first
git -C "$K" branch master "$(git -C "$K" commit-tree "$(git -C "$K" write-tree)" -m snapshot)"
git -C "$K" merge-base master develop >/dev/null 2>&1 && no "the snapshot master shares history" || ok "K: master is a snapshot with no merge base to develop"
attach kappa "$K"
st0=$(state "$K")
out=$($DA project adopt kappa 2>&1); tok=$(tokof "$out")
grep -q "^    - history: master and develop share no history (no merge base) (adopt changes no existing branch, so it does not join them" <<<"$out" && grep -q "Next step: the first release joins them (qargi release start VERSION, then qargi release push VERSION, whose plan joins the history of master" <<<"$out" \
  && grep -q "git switch develop && git merge -s ours --allow-unrelated-histories master (keeps the tree of develop)" <<<"$out" \
  && ok "K: the plan names the missing merge base as left for the owner, and the next step (the release verbs, or the git merge)" || no "K plan: $out"
[ "$st0" = "$(state "$K")" ] && ok "K: showing the plan changes nothing" || no "K: the plan changed the repository"
$DA project adopt kappa --plan "$tok" --approved go >/dev/null 2>&1 || no "K: apply"
git -C "$K" merge-base master develop >/dev/null 2>&1 && no "K: apply joined the histories" || ok "K: applying does not join the histories or move master and develop"
out=$($DA project adopt kappa 2>&1); grep -q "share no history" <<<"$out" && ok "K: it is still named after the apply" || no "K: second plan: $out"

# the audit line, and a bad methodology
grep -q '"verb":"project:adopt"' "$T/s/audit.log" && ok "applying leaves an audit line" || no "audit"
$DA project adopt alpha --methodology nosuch >/dev/null 2>&1 && no "an unknown methodology was accepted" || ok "an unknown methodology is refused"

# --- declared gates: the files adopt writes name the gates where they would name the test command, test_command otherwise
for f in AGENTS.md CLAUDE.md CONTRIBUTING.md .github/workflows/test.yml; do
  git -C "$A" show "agent/adopt-gitflow:$f" | grep -q "declared gates" && no "gates: $f names gates in a project without any"
done
git -C "$A" show agent/adopt-gitflow:.github/workflows/test.yml | grep -qx "  test:" && git -C "$A" show agent/adopt-gitflow:CONTRIBUTING.md | grep -q 'merged into `develop`: `make test`\.$' && ok "gates: without gates the files name the test command and the CI has the one job test" || no "gates absent: the files changed"
Gd=$T/gdemo; git init -q -b main "$Gd"; printf '# Gdemo\n' > "$Gd/README.md"; git -C "$Gd" add -A; git -C "$Gd" commit -q -m first
attach gdemo "$Gd"
jq '.gates = [{name:"lint",command:"make lint",tier:"feature"},{name:"unit",command:["make","check"],tier:"feature"},{name:"pack",command:"make pack",tier:"release"}]' "$T/c/projects/gdemo.json" > "$T/g.json" && cp "$T/g.json" "$T/c/projects/gdemo.json"
out=$($DA project adopt gdemo 2>&1); tok=$(tokof "$out")
$DA project adopt gdemo --plan "$tok" --approved go >/dev/null 2>&1 || no "gates: apply: $out"
sh_() { git -C "$Gd" show "agent/adopt-gitflow:$1"; }
for f in AGENTS.md CLAUDE.md CONTRIBUTING.md; do
  sh_ "$f" | grep -qx '  - `lint` (feature): `make lint`' && sh_ "$f" | grep -qx '  - `unit` (feature): `make check`' && sh_ "$f" | grep -qx '  - `pack` (release): `make pack`' && ! sh_ "$f" | grep -q 'make test' && ok "gates: $f lists the declared gates in order" || no "gates $f: $(sh_ "$f" | grep -n 'gate\|make')"
done
wf=$(sh_ .github/workflows/test.yml)
grep -qx "    name: 'lint'" <<<"$wf" && grep -qx "    name: 'unit'" <<<"$wf" && grep -qx "    name: 'pack'" <<<"$wf" && grep -qx '          make check' <<<"$wf" && ! grep -qx '  test:' <<<"$wf" && [ "$(grep -c 'runs-on' <<<"$wf")" = 3 ] \
  && ok "gates: the CI workflow has one job for each gate, named after it" || no "gates workflow: $wf"
mkdir -p "$T/tree/.github/workflows"; sh_ .github/workflows/test.yml > "$T/tree/.github/workflows/test.yml"
python3 "${DA%/bin/qargi}/lib/gates.py" scan "$T/c/projects/gdemo.json" "$T/tree" >"$T/scan.out" 2>&1 && [ ! -s "$T/scan.out" ] && ok "gates: the scan of the written workflow finds every job matched by a gate" || no "gates scan: $(cat "$T/scan.out")"
rm -rf "$T"
exit $fail
