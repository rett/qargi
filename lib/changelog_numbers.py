#!/usr/bin/env python3
"""Numbered changelog items (the part of `qargi changelog` and of the feature verbs that reads and rewrites them).

A project opts in with the answer release.changelog.numbered: true. Under the unreleased heading of its changelog (the answer
release.changelog.unreleased, default "## [Unreleased]"; the section runs to the next heading of that level or above), an item is a line that
starts with a number, a dot and a space ("12. text") or with "- ", the number, a dot and a space ("- 12. text"); its continuation lines are the
lines up to the next item. Lines inside a fenced code block and indented lines are not items. Two branches that each add "item 5" leave two items
numbered 5 after they are merged: that is a duplicate.

Renumbering gives the items consecutive numbers in file order, starting at the number of the first item, and only when a number is duplicated. A
cross-reference "(item N)" inside the section follows the item it means: with a duplicated N, the nearest item numbered N at or before the line that
holds the reference (an item's own lines count), else the nearest after it. A reference to a number no item has is left as it is.

  changelog_numbers.py renumber FILE AF [--check]
      FILE is the changelog, AF the project's answers file. Without --check the duplicates are renumbered and FILE is rewritten. With --check
      nothing is written. Exit 0: no duplicate (or renumbered); 1: --check found duplicates (listed); 2: usage; 3: no such file or no unreleased heading.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import release_layout as RL  # noqa: E402

ITEM_RE = re.compile(r"^(- )?(\d+)\. ")
REF_RE = re.compile(r"\(item (\d+)\)")
FENCE_RE = re.compile(r"^ {0,3}(```|~~~)")


def section(text, template):
    """(heading, start, end): the unreleased heading line as written and the character range of the section below it, or None."""
    m = RL.find_unreleased(text, template)
    if not m:
        return None
    start = m.end()
    return m.group(0).strip(), start, start + RL.section_end(text[start:], RL.level(template))


def items(lines):
    """[(line index, number)] of the items in the lines of a section."""
    out, fenced = [], False
    for i, l in enumerate(lines):
        if FENCE_RE.match(l):
            fenced = not fenced
            continue
        m = None if fenced else ITEM_RE.match(l)
        if m:
            out.append((i, int(m.group(2))))
    return out


def duplicates(its):
    """{number: [line indexes]} of the numbers more than one item has."""
    seen = {}
    for i, n in its:
        seen.setdefault(n, []).append(i)
    return {n: ix for n, ix in seen.items() if len(ix) > 1}


def renumbered(lines, its):
    """(new lines, [(line index, old, new)] of the items whose number changed, number of references rewritten)."""
    start = its[0][1]
    new_of = {i: start + k for k, (i, _) in enumerate(its)}
    by_num = {}
    for i, n in its:
        by_num.setdefault(n, []).append(i)
    refs = [0]

    def target(n, at):
        ix = by_num.get(n)
        if not ix:
            return None
        before = [i for i in ix if i <= at]
        return before[-1] if before else ix[0]

    def fix_refs(s, at):
        def one(m):
            t = target(int(m.group(1)), at)
            if t is None or new_of[t] == int(m.group(1)):
                return m.group(0)
            refs[0] += 1
            return "(item %d)" % new_of[t]
        return REF_RE.sub(one, s)

    out, changed = [], []
    for i, l in enumerate(lines):
        m = ITEM_RE.match(l) if i in new_of else None
        if m:
            if new_of[i] != int(m.group(2)):
                changed.append((i, int(m.group(2)), new_of[i]))
            out.append("%s%d. %s" % (m.group(1) or "", new_of[i], fix_refs(l[m.end():], i)))
        else:
            out.append(fix_refs(l, i))
    return out, changed, refs[0]


def cmd_renumber(args):
    check = "--check" in args
    args = [a for a in args if a != "--check"]
    if len(args) != 2:
        print("usage: changelog_numbers.py renumber FILE AF [--check]", file=sys.stderr)
        return 2
    path, af = args
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print("qargi: %s: %s" % (path, e.strerror or e), file=sys.stderr)
        return 3
    unrel, _ = RL.templates(RL.load_release(af))
    sec = section(text, unrel)
    if not sec:
        print("qargi: %s has no '%s' section (release.changelog.unreleased) to number the items of" % (os.path.basename(path), unrel), file=sys.stderr)
        return 3
    head, a, b = sec
    lines = text[a:b].split("\n")
    its = items(lines)
    dups = duplicates(its)
    base = text[:a].count("\n")                    # the section's first line is line base + 1 of the file
    if not dups:
        print("no duplicate item numbers under '%s' (%d item(s))" % (head, len(its)))
        return 0
    if check:
        print("%s: duplicate item numbers under '%s':" % (os.path.basename(path), head))
        for n in sorted(dups):
            print("  %d: lines %s" % (n, ", ".join(str(base + i + 1) for i in dups[n])))
        print("Fix: qargi changelog renumber in the checkout that holds the file, commit it, and run the whole suite again.")
        return 1
    new, changed, nrefs = renumbered(lines, its)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text[:a] + "\n".join(new) + text[b:])
    print("renumbered %d item(s) under '%s' in %s, %d cross-reference(s) rewritten:" % (len(changed), head, os.path.basename(path), nrefs))
    for i, old, nw in changed:
        print("  line %d: item %d -> %d" % (base + i + 1, old, nw))
    print("%s is changed and not committed: review it, commit it, and run the whole suite again before a finish" % path)
    return 0


def main(argv):
    if argv and argv[0] == "renumber":
        return cmd_renumber(argv[1:])
    print("usage: changelog_numbers.py renumber FILE AF [--check]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
