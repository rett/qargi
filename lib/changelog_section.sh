#!/usr/bin/env bash
# Prints the body of one version's section of a Keep a Changelog file: the lines after "## [VERSION]" up to the next "## [".
# Used by the release workflow for the notes of a GitHub release. Exit 1 when the section is missing or empty.
#   changelog_section.sh VERSION [FILE]      (FILE defaults to CHANGELOG.md)
set -u
version=${1:-}; file=${2:-CHANGELOG.md}
[ -n "$version" ] && [ -r "$file" ] || { echo "usage: changelog_section.sh VERSION [FILE]" >&2; exit 2; }
body=$(awk -v v="$version" '
  /^## \[/ { if (on) exit; on = (index($0, "## [" v "]") == 1); next }
  on { print }
' "$file")
# trim leading and trailing blank lines
body=$(printf '%s\n' "$body" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')
[ -n "$body" ] || { echo "changelog_section.sh: no section for $version in $file" >&2; exit 1; }
printf '%s\n' "$body"
