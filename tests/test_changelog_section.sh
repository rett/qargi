#!/usr/bin/env bash
# lib/changelog_section.sh: the notes of one version, and a loud failure when there are none.
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
S=lib/changelog_section.sh
T=$(mktemp -d); trap 'rm -rf "$T" "$HERMETIC"' EXIT
fail=0; ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
cat > "$T/c.md" <<'MD'
# Changelog

## [Unreleased]

### Added
- not yet

## [1.2.0] - 2026-01-02

### Added
- the new thing

### Fixed
- the old thing

## [1.1.0] - 2026-01-01
- earlier

## [1.0.0] - 2025-12-01

## [0.9.0] - 2025-11-01
- last
MD
out=$(bash $S 1.2.0 "$T/c.md"); rc=$?
[ $rc = 0 ] && [ "$(head -1 <<<"$out")" = "### Added" ] && [ "$(tail -1 <<<"$out")" = "- the old thing" ] && ! grep -q "earlier\|not yet" <<<"$out" && ok "the section of a version, without the neighbours and without blank lines at the ends" || no "1.2.0: rc=$rc $out"
out=$(bash $S 1.1.0 "$T/c.md"); [ "$out" = "- earlier" ] && ok "a section of one line" || no "1.1.0: $out"
out=$(bash $S 0.9.0 "$T/c.md"); [ "$out" = "- last" ] && ok "the last section" || no "0.9.0: $out"
bash $S 1.0.0 "$T/c.md" >/dev/null 2>&1; [ $? = 1 ] && ok "an empty section is refused" || no "empty section"
bash $S 9.9.9 "$T/c.md" >/dev/null 2>&1; [ $? = 1 ] && ok "a missing version is refused" || no "missing version"
bash $S 1.2 "$T/c.md" >/dev/null 2>&1; [ $? = 1 ] && ok "a prefix of a version is not a match" || no "prefix match"
bash $S >/dev/null 2>&1; [ $? = 2 ] && ok "no argument is a usage error" || no "usage"
out=$(bash $S 0.2.0 CHANGELOG.md 2>&1); [ $? = 0 ] && [ -n "$out" ] && ok "the repository's own 0.2.0 section is found" || no "own changelog: $out"
cat > "$T/t.md" <<'MD'
# Changes

## 1.2.0 (2026-01-02)

### Added
- templated new

## 1.2.01 (2026-01-01)
- not this one

# Older

## 1.1.0 (2025-12-01)
- other
MD
H='## {version} ({date})'
out=$(bash $S 1.2.0 "$T/t.md" "$H"); [ $? = 0 ] && [ "$(head -1 <<<"$out")" = "### Added" ] && [ "$(tail -1 <<<"$out")" = "- templated new" ] && ok "a heading template finds the section, whatever the heading looks like" || no "template 1.2.0: $out"
bash $S 1.2 "$T/t.md" "$H" >/dev/null 2>&1; [ $? = 1 ] && ok "a template match is not a prefix of a longer version" || no "template prefix"
bash $S 1.2.0 "$T/c.md" "$H" >/dev/null 2>&1; [ $? = 1 ] && ok "a heading the template does not describe is not found" || no "template mismatch"
out=$(bash $S 1.2.0 "$T/c.md" '## [{version}] - {date}'); [ "$(tail -1 <<<"$out")" = "- the old thing" ] && ok "the Keep a Changelog template reads a Keep a Changelog file" || no "kac template: $out"
out=$(bash $S 1.2.0 "$T/t.md" '# {version} ({date})' 2>&1); [ $? = 1 ] && ok "a template of another level does not match" || no "level: $out"
grep -q "tags:" .github/workflows/release.yml && grep -q "verify-tag" .github/workflows/release.yml && grep -q "is-ancestor" .github/workflows/release.yml && ok "the workflow runs on tags, verifies the tag and checks master" || no "workflow shape"
shellcheck -x -S warning lib/changelog_section.sh tests/test_changelog_section.sh >/dev/null 2>&1 && ok "shellcheck clean" || no "shellcheck"
exit $fail
