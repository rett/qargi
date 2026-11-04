#!/usr/bin/env bash
# The neutrality of the core: lib/ (apart from lib/providers/, where the runtimes are defined) and bin/ should not name the runtime qargi
# was first built for. Every line that matches claude|anthropic|\bant\b|skilloverrides|\.claude|subagent (case-insensitive) must be
# allowed by an entry of tests/neutral-allowlist.txt, and every entry must still allow at least one line. So the list can only shrink:
# a new hit fails (move it into a runtime's definition, or name it neutrally), and an entry whose hit has gone fails too (delete it).
#
# tests/neutral-allowlist.txt: `FILE:PATTERN` per line, FILE a path from the repository root, PATTERN an extended regular expression
# (case-sensitive) matched against the text of a hit line; the first colon ends the file name. `#` starts a comment, blank lines are
# ignored. Group the entries of a file under a comment that says why they are there.
#
# A second section holds the texts a member or a lead loads, and what the tool writes into a repository, to the same rule: skills/, roles/, agents/,
# contract/, packs/skills/, provision/templates/*.md and methodologies/ should not name a vendor, a model family or the vendor's cloud CLI (case-insensitive: claude, anthropic, managed agents, haiku, sonnet, opus, ant as a
# word, the Agent tool). A runtime is reached through the notes of its definition. tests/vendor-words-allowlist.txt lists what may stay as
# `FILE:COUNT` (COUNT is the number of lines of FILE with a hit): a file with more hits than that, or a file not listed that has one, fails,
# and so does an entry that is more than the hits of its file ("lower it"). So the list can only shrink. Group the entries under a
# comment that says why they stay (a runtime name that is the thing explained, the file name CLAUDE.md that repositories use).
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

# the texts a member or a lead loads
VRE='claude|anthropic|managed agents?|haiku|sonnet|opus|\bant\b|agent tool'
VLIST=$ROOT/tests/vendor-words-allowlist.txt
[ -f "$VLIST" ] || { no "no $VLIST"; exit 1; }
declare -A vallowed=() vhits=()
vbad=0
while IFS= read -r raw || [ -n "$raw" ]; do
  case $raw in ''|'#'*) continue;; esac
  vf=${raw%:*}; vn=${raw##*:}
  if [ "$vf" = "$raw" ] || ! [[ $vn =~ ^[1-9][0-9]*$ ]] || [ ! -f "$vf" ]; then no "$VLIST: not FILE:COUNT of a file that exists: $raw"; vbad=1; continue; fi
  [ -z "${vallowed[$vf]:-}" ] || { no "$VLIST: $vf is listed twice"; vbad=1; continue; }
  vallowed[$vf]=$vn
done < "$VLIST"
while IFS=: read -r vf vn; do
  [ "$vn" = 0 ] || vhits[$vf]=$vn
done < <(grep -rIicE -e "$VRE" skills roles agents contract packs/skills methodologies provision/templates/*.md 2>/dev/null | sort)
vnfiles=$(find skills roles agents contract packs/skills methodologies provision/templates -type f \( -path 'provision/templates/*' -name '*.md' -o ! -path 'provision/templates/*' \) | wc -l)
[ "$vnfiles" -gt 30 ] || { no "found only $vnfiles files: the lookup is broken"; vbad=1; }
for vf in "${!vhits[@]}"; do
  if [ -z "${vallowed[$vf]:-}" ]; then no "vendor word in $vf (${vhits[$vf]} lines): $(grep -iEm1 -e "$VRE" "$vf" | cut -c1-110) (say it neutrally, or point at the notes of the runtime)"; vbad=1
  elif [ "${vhits[$vf]}" -gt "${vallowed[$vf]}" ]; then no "more vendor words in $vf: ${vhits[$vf]} lines, the allowlist has ${vallowed[$vf]}"; vbad=1; fi
done
for vf in "${!vallowed[@]}"; do
  if [ -z "${vhits[$vf]:-}" ]; then no "stale entry in $VLIST: $vf has no vendor word any more (delete the line)"; vbad=1
  elif [ "${vhits[$vf]}" -lt "${vallowed[$vf]}" ]; then no "stale entry in $VLIST: $vf has ${vhits[$vf]} lines, the entry allows ${vallowed[$vf]} (lower it)"; vbad=1; fi
done
[ $vbad = 0 ] && ok "the $vnfiles files of skills/, roles/, agents/, contract/, packs/skills/, provision/templates/*.md and methodologies/ name a vendor only where tests/vendor-words-allowlist.txt allows (${#vallowed[@]} files)"
exit $fail
