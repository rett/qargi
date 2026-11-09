#!/usr/bin/env python3
"""lib/backlog.py: how a markdown file is read as items, which ids it takes, what `named` finds and how an item is removed."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import backlog as B  # noqa: E402


def items(text):
    return B.parse(text.split("\n"))


class Parse(unittest.TestCase):
    def test_ids_and_unnumbered_lines(self):
        got = items("# Title\n\n- [fix-names] Rename it\n* [two-2] starred\n- plain\n- [x] box\n- [a-] bad\n- [Up] case\n- [ok-id]\n  more\nparagraph\n")
        self.assertEqual([i["id"] for i in got], ["fix-names", "two-2", None, None, None, None, None])
        self.assertEqual(got[0]["text"], "Rename it")
        self.assertEqual(got[3]["text"], "[x] box")
        self.assertEqual(got[6]["full"], ["- [ok-id]", "  more"])   # an id with no text is no id: the whole line is the text

    def test_continuation_lines_and_blank_lines(self):
        got = items("- [aa] one\n  second\n\n  third after a blank\n\n- [bb] two\n\nplain paragraph\n- [cc] three\n\t- tabbed\n")
        self.assertEqual([i["id"] for i in got], ["aa", "bb", "cc"])
        self.assertEqual(got[0]["full"], ["- [aa] one", "  second", "", "  third after a blank"])
        self.assertEqual(got[1]["full"], ["- [bb] two"])
        self.assertEqual(got[2]["full"], ["- [cc] three", "\t- tabbed"])

    def test_fenced_blocks_and_headings_are_no_items(self):
        got = items("# - [head] not an item\n```\n- [in-fence] no\n```\n- [real] yes\n  ```\n  - [inner] no\n  ```\n- [after] yes\n")
        self.assertEqual([i["id"] for i in got], ["real", "after"])

    def test_duplicates(self):
        dup, seen = B.duplicates(items("- [aa] x\n- [bb] y\n- [aa] z\n- plain\n"))
        self.assertEqual(dup, ["aa"])
        self.assertEqual(seen["aa"], [1, 3])


class Named(unittest.TestCase):
    def named(self, backlog, messages):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write(backlog)
            old = sys.stdin
            sys.stdin = io.StringIO(messages)
            out = io.StringIO()
            old_out, sys.stdout = sys.stdout, out
            try:
                B.cmd_named(path)
            finally:
                sys.stdin, sys.stdout = old, old_out
            return out.getvalue().strip()

    def test_whole_ids_only_in_backlog_order(self):
        bl = "- [add-cache] a\n- [late-one] b\n- [ci-fix] c\n- plain\n"
        self.assertEqual(self.named(bl, "Cache it (late-one)\n\nand add-cache, too"), "add-cache, late-one")
        self.assertEqual(self.named(bl, "xadd-cache add-cache-more late-one2 pre-late-one"), "")
        self.assertEqual(self.named(bl, "CI-FIX in capitals, ci-fix.\n"), "ci-fix")
        self.assertEqual(self.named(bl, "late-one late-one"), "late-one")
        self.assertEqual(self.named(bl, ""), "")


class Remove(unittest.TestCase):
    def done(self, text, ident):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write(text)
            os.environ["QARGI_NOW"] = "2026-11-08"
            old_out, sys.stdout = sys.stdout, io.StringIO()
            try:
                B.cmd_apply(path, ident, "shown by a test")
            finally:
                sys.stdout = old_out
                del os.environ["QARGI_NOW"]
            with open(path) as f:
                rest = f.read()
            with open(os.path.join(d, "backlog-archive-2026-11.md")) as f:
                return rest, f.read()

    def test_the_item_and_its_lines_go_and_one_blank_line_stays(self):
        rest, arch = self.done("# T\n\n- [aa] one\n  more\n\n- [bb] two\n\n- [cc] three\n", "bb")
        self.assertEqual(rest, "# T\n\n- [aa] one\n  more\n\n- [cc] three\n")
        self.assertEqual(arch, "# backlog archive 2026-11\n\n### 2026-11-08: bb\n\n- [bb] two\n\nEvidence: shown by a test\n")

    def test_first_and_last_items(self):
        rest, _ = self.done("- [aa] one\n  more\n- [bb] two\n", "aa")
        self.assertEqual(rest, "- [bb] two\n")
        rest, _ = self.done("intro\n\n- [aa] one\n- [bb] two\n  more\n", "bb")
        self.assertEqual(rest, "intro\n\n- [aa] one\n")

    def test_the_file_without_a_final_newline_keeps_none(self):
        rest, _ = self.done("- [aa] one\n- [bb] two", "aa")
        self.assertEqual(rest, "- [bb] two")


if __name__ == "__main__":
    unittest.main()
