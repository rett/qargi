#!/usr/bin/env bash
# The neutrality of the core: lib/ (apart from lib/providers/, where the runtimes are defined) and bin/ should not name the runtime qargi
# was first built for. Every line that matches claude|anthropic|\bant\b|skilloverrides|\.claude|subagent (case-insensitive) must be
# allowed by an entry of tests/neutral-allowlist.txt, and every entry must still allow at least one line. So the list can only shrink:
# a new hit fails (move it into a runtime's definition, or name it neutrally), and an entry whose hit has gone fails too (delete it).
#
# tests/neutral-allowlist.txt: `FILE:PATTERN` per line, FILE a path from the repository root, PATTERN an extended regular expression
# (case-sensitive) matched against the text of a hit line; the first colon ends the file name. `#` starts a comment, blank lines are
# ignored. Group the entries of a file under a comment that says why they are there.
# Run: tests/test_neutral.sh
set -u
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
T=$(mktemp -d); fail=0
trap 'rm -rf "$T"' EXIT
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
RE='claude|anthropic|\bant\b|skilloverrides|\.claude|subagent'
LIST=$ROOT/tests/neutral-allowlist.txt
[ -f "$LIST" ] || { no "no $LIST"; exit 1; }
mkdir -p "$T/text" "$T/line"

# the hits, one file per source file: the text of each hit line, and in a parallel file its line number
grep -rniE -I --exclude-dir=__pycache__ -e "$RE" lib bin 2>/dev/null | grep -v '^lib/providers/' \
  | awk -v d="$T" -F: '{ f = $1; n = $2; t = substr($0, length(f) + length(n) + 3); k = f; gsub("/", "__", k)
                          print t >> (d "/text/" k); print n >> (d "/line/" k) }'
nfiles=$(find "$T/text" -type f | wc -l)
nhits=$(cat "$T"/text/* 2>/dev/null | wc -l)

# each entry marks the hits it allows
declare -A covered=()
bad=0 entries=0
while IFS= read -r raw || [ -n "$raw" ]; do
  case $raw in ''|'#'*) continue;; esac
  entries=$((entries + 1))
  file=${raw%%:*}; pat=${raw#*:}
  if [ "$file" = "$raw" ] || [ -z "$pat" ]; then no "not FILE:PATTERN: $raw"; bad=1; continue; fi
  key=${file//\//__}
  if [ ! -f "$T/text/$key" ]; then no "stale entry (the file has no hit at all any more): $raw"; bad=1; continue; fi
  matched=$(grep -nE -e "$pat" "$T/text/$key" 2>/dev/null); rc=$?
  if [ $rc -gt 1 ]; then no "not a regular expression: $raw"; bad=1; continue; fi
  if [ -z "$matched" ]; then no "stale entry (it allows no hit): $raw"; bad=1; continue; fi
  while IFS= read -r m; do covered["$key:${m%%:*}"]=1; done <<<"$matched"
done < "$LIST"
[ $bad = 0 ] && ok "all $entries entries of tests/neutral-allowlist.txt allow at least one hit"

# the hits nobody allows
unlisted=0
for tf in "$T"/text/*; do
  key=$(basename "$tf"); n=0
  while IFS= read -r text; do
    n=$((n + 1))
    if [ -z "${covered["$key:$n"]:-}" ]; then
      unlisted=$((unlisted + 1))
      [ $unlisted -gt 40 ] || echo "FAIL not allowed: ${key//__//}:$(sed -n "${n}p" "$T/line/$key"): $(printf '%s' "$text" | cut -c1-140)"
    fi
  done < "$tf"
done
if [ $unlisted = 0 ]; then ok "all $nhits hits in $nfiles files are allowed (lib/ without lib/providers/, and bin/)"
else no "$unlisted hits are not in tests/neutral-allowlist.txt: name the runtime in its definition under lib/providers/ instead, or (if it must stay) add an entry under a comment that says why"; fi
exit $fail
