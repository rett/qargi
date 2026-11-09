#!/usr/bin/env bash
# The weight of the texts a member or a lead loads, and five ways it is held in place.
#
# The texts: skills/**/*.md, contract/*.md, roles/*/ROLE.md, agents/member.md and agents/member.body.md, provision/templates/*.md,
# packs/skills/**/*.md and the contract addenda of the shipped runtimes (lib/providers/*/*.md, which a cloud agent's prompt or a local run's contract directory carries). Every word of them costs context in every session that loads them, so:
#
#  1. Budget. tests/skill-budget.txt holds `PATH MAX_WORDS` per line (sorted; `#` starts a comment). A ceiling is exact: a text
#     over its ceiling fails, and so does one under it ("lower the ceiling to N"), so a longer text and a text with slack both
#     need an edit of the file, which shows in review. A text that is not listed fails, and a listed text that is gone fails.
#  2. Duplicates. A sentence of 12 words or more (case and spacing ignored, fenced code left out) that stands in two or more
#     different texts fails, unless tests/skill-dup-allowlist.txt lists it (`SHA12 file, file`, sorted) with exactly the texts it
#     stands in: a sentence allowed in two texts fails when a third has it. An entry whose sentence is no longer duplicated, or
#     no longer in those texts, fails: edit or delete it.
#  3. Verbs. Every `qargi X Y` example in backticks (and every line of a code block that starts with `qargi `) must name a
#     command of lib/commands.py (the table tests/test_help.py checks against the scripts) and, when that command has verbs,
#     one of its verbs. Words that are placeholders (NAME, <x>, [x]), flags and quoted text end the example; `a|b` stands for
#     both. A miss fails unless tests/skill-verbs-allowlist.txt lists it (`qargi X Y`, sorted); a stale entry fails too.
#  4. Reference files. Every .md under skills/*/ other than SKILL.md is loaded on demand, so its first line must start with
#     `Load when ` (the model decides from that line alone whether to read it), and the SKILL.md of its skill must send a session
#     there: its path inside the skill, as a markdown link or inside backticks, on a line that also says "load" (any case), or
#     nothing would tell the session when to read it. A file under skills/ that is not .md is budgeted like the texts (it needs a
#     line in tests/skill-budget.txt and must be text), so a script or a data file cannot be added unseen.
#
#  5. Raising a ceiling. A ceiling above its value at the merge base with origin/develop (`git merge-base HEAD origin/develop`;
#     the check is skipped with a notice when there is none) must carry a comment on its own line that says why:
#         PATH 330 # raised: the new section on X, reviewed by NAME
#     so a bigger text cannot be made to pass by editing the number alone. A new line (no value at the merge base), an unchanged
#     one and a lowered one need no comment. The check itself is tried on small files each time the test runs.
#
# The notes of a runtime's definition (lib/providers/*.json, `notes`) are loaded on demand by `qargi provider notes`. All its topics
# together are one text here, listed as `lib/providers/NAME.json:notes` with the words of the topic texts. They are not scanned for
# vendor words (tests/test_neutral.sh): a runtime's definition is where its vendor is named.
#
# Run: tests/test_skill_budget.sh          the check
#      tests/test_skill_budget.sh --report  the same, and every text with its count, ceiling and slack (nothing is changed)
set -u
cd "$(dirname "$0")/.." || exit 1
# shellcheck source=hermetic.sh
. tests/hermetic.sh
fail=0
ok() { echo "ok   $1"; }; no() { echo "FAIL $1"; fail=1; }
report=0
case ${1:-} in
  '') ;;
  --report) report=1;;
  *) echo "usage: $0 [--report]" >&2; exit 2;;
esac
BUDGET=tests/skill-budget.txt DUPS=tests/skill-dup-allowlist.txt VERBS=tests/skill-verbs-allowlist.txt
for f in "$BUDGET" "$DUPS" "$VERBS"; do [ -f "$f" ] || { no "no $f"; exit 1; }; done
# the three lists are sorted (byte order, comments and blank lines left out), so a change to one is a small diff
for f in "$BUDGET" "$DUPS" "$VERBS"; do
  if [ "$(grep -vE '^[[:space:]]*(#|$)' "$f")" = "$(grep -vE '^[[:space:]]*(#|$)' "$f" | LC_ALL=C sort)" ]; then ok "$f is sorted"
  else no "$f is not sorted (LC_ALL=C sort it, comments first)"; fi
done

# the shipped texts
mapfile -t TEXTS < <({ find skills -type f; find packs/skills contract lib/providers -type f -name '*.md'; ls roles/*/ROLE.md agents/member.md agents/member.body.md provision/templates/*.md; } 2>/dev/null | sort)
[ "${#TEXTS[@]}" -gt 10 ] || no "found only ${#TEXTS[@]} texts: the lookup is broken"

# 1. the budget
# the notes of a runtime's definition count as one more text each (words of the topic texts): NAME.json:notes
declare -A words=()
for t in "${TEXTS[@]}"; do words[$t]=$(wc -w < "$t"); done
ITEMS=("${TEXTS[@]}")
for j in lib/providers/*.json; do
  n=$(jq -r 'if (.notes | type) == "object" then [.notes[] | strings] | join("\n") else empty end' "$j" 2>/dev/null | wc -w)
  [ "$n" -gt 0 ] || continue
  words[$j:notes]=$n; ITEMS+=("$j:notes")
done
# budget_read FILE ARRAY_CEIL ARRAY_COMMENT: the lines `PATH MAX_WORDS [# comment]` of FILE; prints what is wrong with a line
budget_read() {
  local -n _c=$2 _m=$3; local line body path max extra bad=0
  while IFS= read -r line || [ -n "$line" ]; do
    body=${line%%#*}; path='' max='' extra=''
    read -r path max extra <<<"$body"
    [ -n "$path" ] || continue
    if [ -n "$extra" ] || ! [[ ${max:-} =~ ^[0-9]+$ ]]; then echo "$1: not 'PATH MAX_WORDS [# comment]': $line"; bad=1; continue; fi
    if [ -n "${_c[$path]:-}" ]; then echo "$1: $path is listed twice"; bad=1; continue; fi
    _c[$path]=$max; [ "$body" = "$line" ] || _m[$path]=${line#*#}
  done < "$1"
  return $bad
}
# raised_without_reason OLD NEW: a line of NEW whose ceiling is above its value in OLD (a path OLD lacks is new, not raised) and
# that has no `# raised: REASON` comment
raised_without_reason() {
  # shellcheck disable=SC2034  # om is filled through a name reference
  local -A oc=() om=() nc=() nm=(); local p
  budget_read "$1" oc om >/dev/null || true
  budget_read "$2" nc nm >/dev/null || true
  for p in "${!nc[@]}"; do
    [ -n "${oc[$p]:-}" ] && [ "${nc[$p]}" -gt "${oc[$p]}" ] || continue
    [[ ${nm[$p]:-} =~ ^[[:space:]]*raised:[[:space:]]*[^[:space:]] ]] || echo "$p: ${oc[$p]} -> ${nc[$p]}"
  done | LC_ALL=C sort
}
RT=$(mktemp -d); trap 'rm -rf "$RT" "$HERMETIC"' EXIT
# shellcheck disable=SC2034
declare -A ceil=() cmt=()   # cmt is filled through a name reference
bad=0
budget_read "$BUDGET" ceil cmt > "$RT/msgs" || bad=1       # not in a subshell: it fills ceil
while IFS= read -r m; do no "$m"; done < "$RT/msgs"
over=0 missing=0 stale=0
for t in "${ITEMS[@]}"; do
  n=${words[$t]}
  if [ -z "${ceil[$t]:-}" ]; then no "not in $BUDGET: $t ($n words); add it with a ceiling of $n"; missing=$((missing + 1)); continue; fi
  [ "$report" = 0 ] || printf '%6d words  ceiling %6d  slack %5d  %s\n' "$n" "${ceil[$t]}" $((${ceil[$t]} - n)) "$t"
  if [ "$n" -gt "${ceil[$t]}" ]; then no "over its ceiling: $t has $n words, ceiling ${ceil[$t]} (shorten it)"; over=$((over + 1)); fi
  if [ "$n" -lt "${ceil[$t]}" ]; then no "under its ceiling: $t has $n words, ceiling ${ceil[$t]} (lower the ceiling to $n in $BUDGET)"; over=$((over + 1)); fi
done
for p in "${!ceil[@]}"; do
  if [ -z "${words[$p]:-}" ]; then
    case $p in
      *.json:notes) no "stale entry in $BUDGET: ${p%:notes} has no notes any more (delete the line)";;
      *) no "stale entry in $BUDGET: $p is gone or is not one of the shipped texts (delete the line)";;
    esac
    stale=$((stale + 1))
  fi
done
[ $((bad + over + missing + stale)) != 0 ] || ok "all ${#ITEMS[@]} texts (the notes of the runtimes among them) are listed, each with a ceiling equal to its word count"

# 5. a raised ceiling carries its reason. First the check on files of its own, then on the budget against the merge base with develop.
printf '%s\n' '# c' 'a.md 10' 'b.md 10' 'c.md 10' 'd.md 10' 'e.md 10' > "$RT/old"
printf '%s\n' '# c' 'a.md 12' 'b.md 12 # raised: the new section' 'c.md 9' 'd.md 10 # note' 'e.md 11 # raised:' 'f.md 99' > "$RT/new"
got=$(raised_without_reason "$RT/old" "$RT/new" | tr '\n' ';')
if [ "$got" = "a.md: 10 -> 12;e.md: 10 -> 11;" ]; then ok "the raised-ceiling check flags a bare raise and an empty reason, not a reasoned one, a lowered, an unchanged or a new line"
else no "the raised-ceiling check is wrong: it flagged '$got'"; fi
if base=$(git merge-base HEAD origin/develop 2>/dev/null) && git show "$base:$BUDGET" > "$RT/base" 2>/dev/null; then
  raised=$(raised_without_reason "$RT/base" "$BUDGET")
  if [ -z "$raised" ]; then ok "no ceiling is above its value at the merge base with origin/develop without a '# raised: reason' comment"
  else while IFS= read -r m; do no "ceiling raised without a reason (add '# raised: why' to its line in $BUDGET): $m"; done <<<"$raised"; fi
else echo "note: no merge base with origin/develop (or no $BUDGET there): the check for raised ceilings was skipped"; fi

# 4. the reference files of the skills
nref=0 refbad=0
while IFS= read -r f; do
  if ! tr -d '\000' < "$f" | cmp -s - "$f"; then no "$f: a file under skills/ that is not .md must be text (it has a NUL byte)"; refbad=1; fi
done < <(find skills -type f ! -name '*.md' | sort)
while IFS= read -r f; do
  nref=$((nref + 1))
  rel=${f#skills/}; skill=${rel%%/*}; name=${rel#*/}
  first=$(head -n 1 "$f")
  case $first in
    'Load when '?*) ;;
    *) no "$f: the first line must start with 'Load when ' (it is: ${first:0:50})"; refbad=1;;
  esac
  grep -i -- load "skills/$skill/SKILL.md" | grep -qF -e "\`$name\`" -e "]($name)" \
    || { no "skills/$skill/SKILL.md does not send a session to $name (a line with 'load' that has \`$name\` in backticks or as a link target)"; refbad=1; }
done < <(find skills -mindepth 2 -type f -name '*.md' ! -name SKILL.md | sort)
[ "$refbad" != 0 ] || ok "all $nref reference files under skills/ start with 'Load when ' and are loaded from their SKILL.md; no file under skills/ is binary"

# 2 and 3, from the same texts
python3 -I - "$DUPS" "$VERBS" "${TEXTS[@]}" <<'PY' || fail=1
import hashlib, os, re, sys
sys.path.insert(0, os.path.join(os.getcwd(), "lib"))
import commands as C  # the command table that tests/test_help.py checks against the scripts

dups_file, verbs_file, texts = sys.argv[1], sys.argv[2], sys.argv[3:]
bad = False


def say(ok, msg):
    global bad
    print(("ok   " if ok else "FAIL ") + msg)
    bad = bad or not ok


def entries(path, key):
    out = {}
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if line.strip() and not line.lstrip().startswith("#"):
            out[key(line)] = line
    return out


def blocks(text):
    """The prose of a text as blocks (paragraphs, list items, headings, table rows), fenced code left out; and the
    lines of the code blocks that start with `qargi `."""
    prose, code, cur, fenced = [], [], [], False

    def flush():
        if cur:
            prose.append(" ".join(cur))
            cur.clear()
    for line in text.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            flush()
            fenced = not fenced
            continue
        if fenced:
            if s.startswith("qargi "):
                code.append(re.sub(r"\s+#.*$", "", s))
            continue
        if not s:
            flush()
            continue
        if re.match(r"([-*+]|\d+[.)])\s|#|\|", s):
            flush()
            s = re.sub(r"^([-*+]|\d+[.)])\s+", "", s)
        cur.append(s)
    flush()
    return prose, code


def sentences(block):
    b = re.sub(r"[*`]", "", block)
    for s in re.split(r"(?<=[.!?])\s+", b):
        s = " ".join(s.lower().split())
        if len(s.split()) >= 12:
            yield s


# 2. the duplicated sentences
where, spans = {}, []
for t in texts:
    prose, code = blocks(open(t, encoding="utf-8").read())
    for b in prose:
        spans += [(t, m.group(1)) for m in re.finditer(r"`([^`\n]+)`", b)]
        for s in sentences(b):
            where.setdefault(s, set()).add(t)
    spans += [(t, c) for c in code]
dup = {hashlib.sha1(s.encode()).hexdigest()[:12]: (s, sorted(f)) for s, f in where.items() if len(f) > 1}
allowed = entries(dups_file, lambda line: line.split()[0])
new = sorted(h for h in dup if h not in allowed)
for h in new:
    s, f = dup[h]
    say(False, "a sentence of %d words is in %d texts (say it once, where it is needed): %s | %s ... | %s" % (len(s.split()), len(f), h, s[:60], ", ".join(f)))
for h in sorted(set(allowed) - set(dup)):
    say(False, "stale entry in %s (the sentence is no longer in two texts; delete the line): %s" % (dups_file, allowed[h]))


def allowed_files(line):
    return sorted(x.strip() for x in line.split(None, 1)[1].split(",")) if len(line.split(None, 1)) > 1 else []


moved = [h for h in sorted(set(allowed) & set(dup)) if allowed_files(allowed[h]) != dup[h][1]]
for h in moved:
    say(False, "the sentence %s is allowed in %s but stands in %s (a sentence allowed in some texts is not allowed in another; fix the text or the line)"
        % (h, ", ".join(allowed_files(allowed[h])) or "no text", ", ".join(dup[h][1])))
if not new and not moved and set(allowed) <= set(dup):
    say(True, "no sentence of 12 words or more is in two texts, apart from the %d of %s" % (len(allowed), dups_file))


# 3. the verbs
def words(tok):
    alts = tok.replace("\\|", "|").split("|")
    return alts if all(re.fullmatch(r"[a-z][a-z0-9-]*", a) for a in alts) else None


def pairs(span):
    for m in re.finditer(r"(?:^|(?<=[\s(]))qargi\s+(\S+)(?:\s+(\S+))?", span):
        cmds = words(m.group(1))
        if cmds is None:
            continue
        verbs = words(m.group(2)) if m.group(2) else None
        for c in cmds:
            for v in verbs or [None]:
                yield c, v


miss, checked = {}, 0
for t, span in spans:
    for c, v in pairs(span):
        checked += 1
        spec = C.COMMANDS.get(c)
        vs = spec.get("verbs") if spec else None
        if spec is None or (v is not None and isinstance(vs, dict) and v not in vs):
            miss.setdefault("qargi %s%s" % (c, " " + v if v and spec else ""), set()).add(t)
allowed = entries(verbs_file, lambda line: line.strip())
new = sorted(k for k in miss if k not in allowed)
for k in new:
    say(False, "`%s` is in %s but lib/commands.py has no such command or verb (fix the text)" % (k, ", ".join(sorted(miss[k]))))
for k in sorted(set(allowed) - set(miss)):
    say(False, "stale entry in %s (the example is gone or now resolves; delete the line): %s" % (verbs_file, k))
if not new and set(allowed) <= set(miss):
    say(True, "all %d `qargi X Y` examples name a command and verb of lib/commands.py, apart from the %d of %s" % (checked, len(allowed), verbs_file))
sys.exit(1 if bad else 0)
PY
# the member pack uses the word gates for the declared gates only (the lead's), and calls the checks of the profile for the touched paths what they are
gfirst=$(sed -n '/^## Checks/,/^## /p' packs/skills/gitflow-member/SKILL.md | sed -n 2p)
grep -q 'the DONE check and the PROFILE checks' <<<"$gfirst" && ! grep -qi 'gate' <<<"$gfirst" \
  && ok "gitflow-member: the first Checks line names the PROFILE checks and does not call them gates" || no "gitflow-member: the first Checks line calls the profile's checks something else, or gates: $gfirst"
exit $fail
