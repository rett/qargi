#!/usr/bin/env bash
# qargi changelog renumber (duplicate item numbers under the unreleased heading, cross-references) and the check that feature sync and
# feature finish run when the answer release.changelog.numbered is true. Run: tests/test_changelog_renumber.sh
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
T=$(mktemp -d); fail=0; DA=$PWD/bin/qargi
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
export HOME=$T/home QARGI_CONF=$T/c QARGI_STATE=$T/s GIT_AUTHOR_NAME=t GIT_AUTHOR_EMAIL=t@example.net GIT_COMMITTER_NAME=t GIT_COMMITTER_EMAIL=t@example.net
export QARGI_PROJECT=app
mkdir -p "$HOME" "$T/c/projects"
R=$T/app; git init -q -b master "$R"
printf '# Changelog\n\n## [Unreleased]\n\n### Added\n1. first\n2. second\n\nfiller 1\nfiller 2\nfiller 3\nfiller 4\n\n### Changed\n\n## [0.1.0] - 2026-01-01\n\n### Added\n1. old\n1. old twin (a released section is not checked)\n' > "$R/CHANGELOG.md"
git -C "$R" add -A && git -C "$R" commit -q -m one && git -C "$R" branch develop
git -C "$R" checkout -q -b parked
AF=$T/c/projects/app.json
answers() { jq -n --arg p "$R" --argjson n "$1" '{schema:1, project:"app", methodology:"gitflow", repo:{url:"https://github.com/acme/app", path:$p, long_lived:["master","develop"]}, test_command:"true", release:{changelog:{numbered:$n}}}' > "$AF"; }
answers true
F="$DA feature"; C="$DA changelog"
W=$T/wt; git -C "$R" worktree add -q --detach "$W" develop
setcl() { printf '%b' "$1" > "$W/CHANGELOG.md"; }   # the changelog of the work tree, from printf text
inwt() { (cd "$W" && "$@"); }
HEAD0='# Changelog\n\n## [Unreleased]\n\n'

# --- the check and the rewrite
setcl "${HEAD0}### Added\n1. a\n2. b\n3. c\n\n## [0.1.0] - 2026-01-01\n1. old\n1. twin\n"
out=$(inwt $C renumber --check 2>&1); rc=$?
[ $rc = 0 ] && grep -q "no duplicate item numbers under '## \[Unreleased\]' (3 item(s))" <<<"$out" && ok "--check on numbers without a duplicate exits 0 (a released section is not read)" || no "no duplicate rc=$rc: $out"
cp "$W/CHANGELOG.md" "$T/before.md"; inwt $C renumber >/dev/null 2>&1; cmp -s "$W/CHANGELOG.md" "$T/before.md" && ok "and renumber then leaves the file as it is" || no "renumber changed a clean file"

setcl "${HEAD0}### Added\n1. first\n2. second\n3. from the feature (item 3)\n   continued, see (item 3) and (item 1)\n\n### Changed\n3. from develop (item 3)\n   read (item 2) and then (item 3)\nsee also (item 3), and (item 9) which no item has\n4. last\n\n## [0.1.0] - 2026-01-01\n(item 3)\n"
cp "$W/CHANGELOG.md" "$T/before.md"
out=$(inwt $C renumber --check 2>&1); rc=$?
[ $rc = 1 ] && grep -q "^  3: lines 8, 12$" <<<"$out" && cmp -s "$W/CHANGELOG.md" "$T/before.md" && ok "--check lists the duplicated number with the lines that hold it, exits 1 and writes nothing" || no "check rc=$rc: $out"
out=$(inwt $C renumber 2>&1); rc=$?
printf '%b' "${HEAD0}### Added\n1. first\n2. second\n3. from the feature (item 3)\n   continued, see (item 3) and (item 1)\n\n### Changed\n4. from develop (item 4)\n   read (item 2) and then (item 4)\nsee also (item 4), and (item 9) which no item has\n5. last\n\n## [0.1.0] - 2026-01-01\n(item 3)\n" > "$T/expected.md"
[ $rc = 0 ] && cmp -s "$W/CHANGELOG.md" "$T/expected.md" && ok "renumber numbers the items in file order and each cross-reference follows the nearest item it names (earlier first, then later); other sections are untouched" || { no "renumber rc=$rc: $out"; diff "$T/expected.md" "$W/CHANGELOG.md" | head -10; }
grep -q "renumbered 2 item(s)" <<<"$out" && grep -q "line 12: item 3 -> 4" <<<"$out" && grep -q "line 15: item 4 -> 5" <<<"$out" && ok "and reports what changed" || no "report: $out"
[ "$(git -C "$W" status --porcelain | wc -l)" = 1 ] && ok "the rewrite is left uncommitted" || no "status: $(git -C "$W" status --porcelain)"
inwt $C renumber --check >/dev/null 2>&1 && ok "after it --check passes" || no "check after renumber"

setcl "${HEAD0}- 1. dash item\n- 1. its twin (item 1)\n  - 7. indented, not an item\n\`\`\`\n1. inside a fence\n\`\`\`\n1. third\n"
inwt $C renumber >/dev/null 2>&1
[ "$(cat "$W/CHANGELOG.md")" = "$(printf '%b' "${HEAD0}- 1. dash item\n- 2. its twin (item 2)\n  - 7. indented, not an item\n\`\`\`\n1. inside a fence\n\`\`\`\n3. third\n")" ] && ok "items are 'N. ' or '- N. ' at the start of a line; indented lines and fenced code are not items" || no "dash format: $(cat "$W/CHANGELOG.md")"

setcl "# Changelog\n\n# Next\n\n5. x\n5. y\n\n# v1\n1. z\n1. w\n"
cp "$T/c/projects/app.json" "$T/app.json.keep"
jq '.release.changelog.unreleased = "# Next"' "$AF" > "$T/x.json" && mv "$T/x.json" "$AF"
inwt $C renumber >/dev/null 2>&1; [ "$(cat "$W/CHANGELOG.md")" = "$(printf '# Changelog\n\n# Next\n\n5. x\n6. y\n\n# v1\n1. z\n1. w')" ] && ok "the heading is release.changelog.unreleased, and the numbering starts at the first item's number" || no "custom heading: $(cat "$W/CHANGELOG.md")"
cp "$T/app.json.keep" "$AF"
setcl "# Changelog\n\n## [0.1.0] - 2026-01-01\n1. x\n"
out=$(inwt $C renumber 2>&1) && no "a changelog without the heading was accepted" || { grep -q "has no '## \[Unreleased\]' section" <<<"$out" && ok "a changelog without the unreleased heading exits 1 and says which heading" || no "no heading: $out"; }
mkdir "$T/plain"; out=$(cd "$T/plain" && $C renumber --check 2>&1) && no "outside a work tree was accepted" || { grep -q "is in no git work tree" <<<"$out" && ok "outside any work tree it refuses" || no "outside: $out"; }
git init -q "$T/other"; out=$(cd "$T/other" && $C renumber --check 2>&1) && no "another repository's work tree was accepted" || { grep -q "is not a work tree of app" <<<"$out" && ok "another repository's work tree is refused" || no "other repo: $out"; }
$C renumber --nope >/dev/null 2>&1; [ $? = 2 ] && $C >/dev/null 2>&1; [ $? = 2 ] && ok "an unknown option and a missing verb are usage errors (exit 2)" || no "usage exits"
$C renumber --project >/dev/null 2>&1; [ $? = 2 ] && ok "--project without a value is a usage error" || no "--project value"
git -C "$R" worktree remove --force "$W"

# --- feature sync warns and feature finish refuses while the answer is true
$F start cl --worktree >/dev/null 2>&1
FW=$T/s/worktrees/app/feature/cl
printf '%b' "${HEAD0}### Added\n1. first\n2. second\n3. from the feature (item 3)\n\nfiller 1\nfiller 2\nfiller 3\nfiller 4\n\n### Changed\n\n## [0.1.0] - 2026-01-01\n\n### Added\n1. old\n1. old twin (a released section is not checked)\n" > "$FW/CHANGELOG.md"
git -C "$FW" commit -q -am "feature item"
printf '%b' "${HEAD0}### Added\n1. first\n2. second\n\nfiller 1\nfiller 2\nfiller 3\nfiller 4\n\n### Changed\n3. from develop (item 3)\n\n## [0.1.0] - 2026-01-01\n\n### Added\n1. old\n1. old twin (a released section is not checked)\n" > "$T/dev.md"
DW=$T/dw; git -C "$R" worktree add -q --detach "$DW" develop; cp "$T/dev.md" "$DW/CHANGELOG.md"; git -C "$DW" commit -q -am "develop item"
git -C "$R" update-ref refs/heads/develop "$(git -C "$DW" rev-parse HEAD)"; git -C "$R" worktree remove --force "$DW"
out=$($F sync cl 2>&1); rc=$?
[ $rc = 0 ] && grep -q "warning: feature/cl has duplicate changelog item numbers" <<<"$out" && grep -q "^  *3: lines 8, 16$" <<<"$out" && ok "sync merges, then warns (exit 0) about the duplicate item numbers the merge produced" || no "sync rc=$rc: $out"
$F verify cl >/dev/null 2>&1
h0=$(git -C "$R" rev-parse feature/cl); d0=$(git -C "$R" rev-parse develop)
out=$($F finish cl 2>&1); rc=$?
[ $rc = 1 ] && grep -q "feature/cl has duplicate changelog item numbers" <<<"$out" && grep -q "3: lines 8, 16" <<<"$out" && grep -q "Nothing was changed" <<<"$out" && ! grep -q "plan token" <<<"$out" && [ "$(git -C "$R" rev-parse feature/cl)" = "$h0" ] && [ "$(git -C "$R" rev-parse develop)" = "$d0" ] && ok "finish refuses (exit 1) before it makes a plan, names the numbers, and changes nothing" || no "finish rc=$rc: $out"
answers false
out=$($F finish cl 2>&1); rc=$?
[ $rc = 0 ] && grep -q "plan token" <<<"$out" && ok "without the answer (false, the default) neither verb looks at the numbers" || no "numbered false rc=$rc: $out"
answers true
(cd "$FW" && $C renumber >/dev/null 2>&1) && git -C "$FW" commit -q -am "renumber"
grep -qx '4. from develop (item 4)' "$FW/CHANGELOG.md" && ok "renumber works in the feature's worktree" || no "worktree renumber: $(cat "$FW/CHANGELOG.md")"
$F verify cl >/dev/null 2>&1; out=$($F finish cl 2>&1); rc=$?
[ $rc = 0 ] && grep -q "plan token" <<<"$out" && ok "after the renumber is committed and verified, finish makes its plan" || no "finish after renumber rc=$rc: $out"
rm -rf "$T"
exit $fail
