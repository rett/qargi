#!/usr/bin/env bash
# The weight of the texts a member or a lead loads, and three ways it can only shrink.
#
# The texts: skills/**/*.md, roles/*/ROLE.md, agents/member.md and agents/member.body.md, provision/templates/*.md and
# packs/skills/**/*.md. Every word of them costs context in every session that loads them, so:
#
#  1. Budget. tests/skill-budget.txt holds `PATH MAX_WORDS` per line (sorted; `#` starts a comment). A text over its ceiling
#     fails, a text that is not listed fails, and a listed text that is gone fails. When you shorten a text, lower its
#     ceiling to the new `wc -w`; raising one is a review decision and is done by editing the file, never by a flag here.
#  2. Duplicates. A sentence of 12 words or more (case and spacing ignored, fenced code left out) that stands in two or more
#     different texts fails, unless tests/skill-dup-allowlist.txt lists it (`SHA12 prefix`, sorted). An entry whose sentence
#     is no longer duplicated fails: delete it. So the list only shrinks.
#  3. Verbs. Every `qargi X Y` example in backticks (and every line of a code block that starts with `qargi `) must name a
#     command of lib/commands.py (the table tests/test_help.py checks against the scripts) and, when that command has verbs,
#     one of its verbs. Words that are placeholders (NAME, <x>, [x]), flags and quoted text end the example; `a|b` stands for
#     both. A miss fails unless tests/skill-verbs-allowlist.txt lists it (`qargi X Y`, sorted); a stale entry fails too.
#
# Run: tests/test_skill_budget.sh          the check
#      tests/test_skill_budget.sh --report  the same, and every text with its count, ceiling and slack (nothing is changed)
set -u
cd "$(dirname "$0")/.." || exit 1
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

# the shipped texts
mapfile -t TEXTS < <({ find skills packs/skills -type f -name '*.md'; ls roles/*/ROLE.md agents/member.md agents/member.body.md provision/templates/*.md; } 2>/dev/null | sort)
[ "${#TEXTS[@]}" -gt 10 ] || no "found only ${#TEXTS[@]} texts: the lookup is broken"

# 1. the budget
declare -A ceil=()
bad=0
while read -r path max extra; do
  case $path in ''|'#'*) continue;; esac
  if [ -n "$extra" ] || ! [[ ${max:-} =~ ^[0-9]+$ ]]; then no "$BUDGET: not 'PATH MAX_WORDS': $path ${max:-} $extra"; bad=1; continue; fi
  if [ -n "${ceil[$path]:-}" ]; then no "$BUDGET: $path is listed twice"; bad=1; continue; fi
  ceil[$path]=$max
done < "$BUDGET"
over=0 missing=0 stale=0
for t in "${TEXTS[@]}"; do
  n=$(wc -w < "$t")
  if [ -z "${ceil[$t]:-}" ]; then no "not in $BUDGET: $t ($n words); add it with a ceiling of $n"; missing=$((missing + 1)); continue; fi
  [ "$report" = 0 ] || printf '%6d words  ceiling %6d  slack %5d  %s\n' "$n" "${ceil[$t]}" $((${ceil[$t]} - n)) "$t"
  if [ "$n" -gt "${ceil[$t]}" ]; then no "over its ceiling: $t has $n words, ceiling ${ceil[$t]} (shorten it)"; over=$((over + 1)); fi
done
for p in "${!ceil[@]}"; do
  [ -f "$p" ] || { no "stale entry in $BUDGET: $p is gone (delete the line)"; stale=$((stale + 1)); continue; }
  found=0; for t in "${TEXTS[@]}"; do [ "$t" != "$p" ] || { found=1; break; }; done
  [ "$found" = 1 ] || { no "stale entry in $BUDGET: $p is not one of the shipped texts (delete the line)"; stale=$((stale + 1)); }
done
[ $((bad + over + missing + stale)) != 0 ] || ok "all ${#TEXTS[@]} texts are listed and within their ceilings"

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
if not new and set(allowed) <= set(dup):
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
exit $fail
