#!/usr/bin/env bash
# Prints the body of one version's section of a changelog: the lines after the heading of VERSION up to the next heading of the same level or above.
# Used by the release workflow and by the publish verb of `qargi release` for the notes of a GitHub release. Exit 1 when the section is missing or empty.
#   changelog_section.sh VERSION [FILE [HEADING]]      (FILE defaults to CHANGELOG.md)
# HEADING is the template of a released section's heading (the answer release.changelog.released), for example "## {version} ({date})":
# the heading of VERSION is the line that begins with the template up to {date}, {version} replaced. Without it the heading is
# "## [VERSION]" and the section ends at the next "## [" (Keep a Changelog).
set -u
version=${1:-}; file=${2:-CHANGELOG.md}; template=${3:-}
[ -n "$version" ] && [ -r "$file" ] || { echo "usage: changelog_section.sh VERSION [FILE [HEADING]]" >&2; exit 2; }
if [ -z "$template" ]; then
  body=$(awk -v v="$version" '
    /^## \[/ { if (on) exit; on = (index($0, "## [" v "]") == 1); next }
    on { print }
  ' "$file")
else
  prefix=${template//\{version\}/$version}; prefix=${prefix%%\{date\}*}
  prefix=$(printf '%s' "$prefix" | sed -e 's/[[:space:]:,(–—-]*$//')   # what stood between the version and {date} is not part of the heading
  level=$(printf '%s' "$template" | sed -e 's/[^#].*$//' | awk '{ print length($0) }')
  body=$(HEAD_PREFIX=$prefix awk -v lvl="$level" '
    BEGIN { p = ENVIRON["HEAD_PREFIX"] }
    /^#+ / { match($0, /^#+/); if (on && RLENGTH <= lvl) exit }
    index($0, p) == 1 && !on && substr($0, length(p) + 1) !~ /^([0-9A-Za-z]|\.[0-9])/ { on = 1; next }
    on { print }
  ' "$file")
fi
# trim leading and trailing blank lines
body=$(printf '%s\n' "$body" | sed -e '/./,$!d' | sed -e ':a' -e '/^\n*$/{$d;N;ba' -e '}')
[ -n "$body" ] || { echo "changelog_section.sh: no section for $version in $file" >&2; exit 1; }
printf '%s\n' "$body"
