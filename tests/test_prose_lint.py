#!/usr/bin/env python3
"""Prompt text is one paragraph per line. The texts a member or the lead loads (contract/*.md, roles/*/*.md, agents/*.md,
packs/skills/*/*.md, skills/*/*.md, provision/templates/*.md, lib/providers/*/*.md) are hard-wrapped nowhere: a paragraph, a
list item, is ONE physical line, so a viewer narrower than the text wraps it whole instead of showing ragged fragments. Outside front matter and fenced code, a line fails when the line before
it is non-blank prose or a list item and the line itself is not blank, a heading, a list item, a table row, a quote or a fence;
a line with trailing spaces fails too. The lint is unit-tested on fixtures, then run over the directories.
Offline. Run: python3 tests/test_prose_lint.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, os, re, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The texts under the rule, as globs relative to the repository root.
GLOBS = ["contract/*.md", "roles/*/*.md", "agents/*.md", "packs/skills/*/*.md", "skills/*/*.md", "provision/templates/*.md",
         "lib/providers/*/*.md"]

FENCE = re.compile(r"^\s*(```+|~~~+)")
HEADING = re.compile(r"^\s{0,3}#{1,6}(\s|$)")
LIST_ITEM = re.compile(r"^\s*([-*]|\d+\.)\s")
TABLE_ROW = re.compile(r"^\s*\|")
QUOTE = re.compile(r"^\s*>")


def kinds(text):
    """(number, line, kind) per line; kind is front, fence, code, blank, heading, list, table, quote or prose."""
    lines = text.split("\n")
    out, fence, i = [], None, 0
    if lines and lines[0] == "---":
        for j in range(1, len(lines)):
            if lines[j] == "---":
                i = j + 1
                break
        else:
            i = 0
        out = [(n + 1, lines[n], "front") for n in range(i)]
    for n in range(i, len(lines)):
        line = lines[n]
        m = FENCE.match(line)
        if fence is not None:
            if m and m.group(1)[0] == fence:
                fence = None
                out.append((n + 1, line, "fence"))
            else:
                out.append((n + 1, line, "code"))
        elif m:
            fence = m.group(1)[0]
            out.append((n + 1, line, "fence"))
        elif not line.strip():
            out.append((n + 1, line, "blank"))
        elif HEADING.match(line):
            out.append((n + 1, line, "heading"))
        elif LIST_ITEM.match(line):
            out.append((n + 1, line, "list"))
        elif TABLE_ROW.match(line):
            out.append((n + 1, line, "table"))
        elif QUOTE.match(line):
            out.append((n + 1, line, "quote"))
        else:
            out.append((n + 1, line, "prose"))
    return out


def lint(text):
    """[(line number, message)] for the lines of TEXT that break the rule."""
    found, prev = [], "blank"
    for n, line, kind in kinds(text):
        if kind not in ("front", "fence", "code") and line != line.rstrip():
            found.append((n, "trailing spaces"))
        if kind == "prose" and prev in ("prose", "list"):
            found.append((n, "join this line to the one before (a paragraph or a list item is one line)"))
        prev = kind
    return found


def files():
    return sorted(p for g in GLOBS for p in glob.glob(os.path.join(ROOT, g)))


class LintUnit(unittest.TestCase):
    def test_wrapped_paragraph_fails(self):
        found = lint("# T\n\nfirst words of a paragraph\nthat goes on here\n")
        self.assertEqual([n for n, _ in found], [4])
        self.assertIn("join this line to the one before", found[0][1])

    def test_wrapped_list_item_fails(self):
        found = lint("- an item that starts here\n  and goes on here\n- the next one\n")
        self.assertEqual([n for n, _ in found], [2])
        found = lint("1. a numbered item\ncontinued here\n")
        self.assertEqual([n for n, _ in found], [2])

    def test_clean_text_passes(self):
        text = ("---\nname: x\ndescription: a\n  b\n---\n\n# Title\nA paragraph on one line.\n\n"
                "- an item\n- another item\n  - nested item\n1. one\n2. two\n\n| a | b |\n| - | - |\n| 1 | 2 |\n\n"
                "> a quote\n> goes on\n\n```\ncode line one\ncode line two\n```\nAfter the fence.\n\n"
                "~~~\nmore code\n~~~\n")
        self.assertEqual(lint(text), [])

    def test_front_matter_and_fences_are_left_alone(self):
        self.assertEqual(lint("---\nkey: one\nsecond: two  \n---\ntext\n"), [])
        self.assertEqual(lint("```\nwrapped  \ncode\n```\n"), [])

    def test_trailing_spaces_fail(self):
        found = lint("a line \n")
        self.assertEqual(found, [(1, "trailing spaces")])

    def test_prose_after_a_heading_table_or_quote_is_not_a_join(self):
        self.assertEqual(lint("# H\nprose\n"), [])
        self.assertEqual(lint("| a |\nprose\n"), [])
        self.assertEqual(lint("> q\nprose\n"), [])


class Texts(unittest.TestCase):
    def test_there_are_texts(self):
        names = {os.path.relpath(p, ROOT) for p in files()}
        for need in ("contract/contract.md", "roles/build/ROLE.md", "agents/member.md", "agents/member.body.md",
                     "packs/skills/gitflow-member/SKILL.md"):
            self.assertIn(need, names)

    def test_every_text_is_one_paragraph_per_line(self):
        bad = []
        for path in files():
            with open(path, encoding="utf-8") as f:
                for n, msg in lint(f.read()):
                    bad.append("%s:%d: %s" % (os.path.relpath(path, ROOT), n, msg))
        self.assertEqual(bad, [], "\n" + "\n".join(bad[:40]))


if __name__ == "__main__":
    unittest.main(verbosity=1)
