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


class Section(unittest.TestCase):
    TEXT = "# T\n\n- [top] before\n\n## Now\n\n- [aa] one\n### Deeper\n- [bb] two\n```\n## Not a heading\n```\n- [cc] three\n\n## Later\n\n- [dd] four\n\n# Other\n- [ee] five\n"

    def test_only_the_list_under_the_heading_holds_items(self):
        got = B.parse(self.TEXT.split("\n"), "Now")
        self.assertEqual([i["id"] for i in got], ["aa", "bb", "cc"])   # a deeper heading and a fenced line belong to it, ## Later ends it
        self.assertEqual([i["id"] for i in B.parse(self.TEXT.split("\n"), "## Later")], ["dd"])   # the name may carry its #s
        self.assertEqual([i["id"] for i in B.parse(self.TEXT.split("\n"))], ["top", "aa", "bb", "cc", "dd", "ee"])

    def test_a_higher_heading_ends_it_and_a_missing_heading_is_an_error(self):
        self.assertEqual([i["id"] for i in B.parse(self.TEXT.split("\n"), "Later")], ["dd"])
        with self.assertRaises(B.BacklogError):
            B.parse(self.TEXT.split("\n"), "Absent")
        with self.assertRaises(B.BacklogError):
            B.parse(self.TEXT.split("\n"), "Not a heading")   # inside a code fence

    def test_the_archive_option(self):
        os.environ["QARGI_NOW"] = "2026-11-08"
        try:
            B.OPTS["archive"] = None
            self.assertEqual(B.archive_path("/x/backlog.md"), "/x/backlog-archive-2026-11.md")
            B.OPTS["archive"] = "/y/archives"
            self.assertEqual(B.archive_path("/x/backlog.md"), "/y/archives/backlog-archive-2026-11.md")
            B.OPTS["archive"] = "/y/all.md"
            self.assertEqual(B.archive_path("/x/backlog.md"), "/y/all.md")
        finally:
            B.OPTS["archive"] = None
            del os.environ["QARGI_NOW"]

    def test_named_ignores_items_outside_the_section_and_a_missing_heading(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write(self.TEXT)
            def named(section):
                B.OPTS["section"] = section
                old, old_out = sys.stdin, sys.stdout
                sys.stdin, sys.stdout = io.StringIO("top aa dd"), io.StringIO()
                try:
                    B.cmd_named(path)
                    return sys.stdout.getvalue().strip()
                finally:
                    sys.stdin, sys.stdout = old, old_out
                    B.OPTS["section"] = None
            self.assertEqual(named(None), "top, aa, dd")
            self.assertEqual(named("Now"), "aa")
            self.assertEqual(named("Absent"), "")


class Add(unittest.TestCase):
    def add(self, text, ident, line, detail=None, section=None):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write(text)
            B.OPTS["section"] = section
            old_out, sys.stdout = sys.stdout, io.StringIO()
            try:
                B.cmd_add(path, ident, line, detail)
            finally:
                sys.stdout = old_out
                B.OPTS["section"] = None
            with open(path) as f:
                return f.read()

    def test_appended_after_the_last_item_and_before_the_trailing_blank_lines(self):
        self.assertEqual(self.add("# T\n\n- [aa] one\n  more\n", "bb", "two"), "# T\n\n- [aa] one\n  more\n- [bb] two\n")
        self.assertEqual(self.add("- [aa] one\n\n\n", "bb", "two"), "- [aa] one\n- [bb] two\n\n\n")

    def test_the_detail_is_indented_and_stays_with_the_item(self):
        got = self.add("- [aa] one\n", "bb", "two", "first line\nsecond line")
        self.assertEqual(got, "- [aa] one\n- [bb] two\n  first line\n  second line\n")
        items = B.parse(got.split("\n"))
        self.assertEqual(items[1]["full"], ["- [bb] two", "  first line", "  second line"])

    def test_a_file_without_a_final_newline_keeps_none(self):
        self.assertEqual(self.add("- [aa] one", "bb", "two"), "- [aa] one\n- [bb] two")

    def test_a_heading_before_the_list_gets_a_blank_line(self):
        self.assertEqual(self.add("# Backlog\n", "aa", "one"), "# Backlog\n\n- [aa] one\n")

    def test_it_goes_to_the_end_of_the_section(self):
        text = "# T\n\n## Now\n\n- [aa] one\n\n## Later\n\n- [bb] two\n"
        self.assertEqual(self.add(text, "cc", "three", section="Now"), "# T\n\n## Now\n\n- [aa] one\n- [cc] three\n\n## Later\n\n- [bb] two\n")
        self.assertEqual(self.add("## Now\n## Later\n", "cc", "three", section="Now"), "## Now\n\n- [cc] three\n\n## Later\n")
        self.assertEqual(self.add(text, "cc", "three", section="Later"), text.replace("- [bb] two\n", "- [bb] two\n- [cc] three\n"))

    def test_refusals(self):
        for ident, line, kw in (("Bad Id", "x", {}), ("a", "x", {}), ("aa", "  ", {}), ("aa", "one\ntwo", {}), ("aa", "x\x01", {}), ("aa", "x", {"detail": " "}),
                                ("dup-id", "again", {}), ("aa", "x", {"section": "Absent"})):
            with self.assertRaises(B.BacklogError, msg=(ident, line, kw)):
                self.add("- [dup-id] there\n## Now\n", ident, line, **kw)
        with self.assertRaises(B.BacklogError):    # the id is taken in another section: still refused
            self.add("## Now\n\n- [aa] one\n\n## Later\n\n- [bb] two\n", "bb", "again", section="Now")


class Batch(unittest.TestCase):
    def run_done(self, text, ids):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write(text)
            os.environ["QARGI_NOW"] = "2026-11-08"
            old_out, sys.stdout = sys.stdout, io.StringIO()
            try:
                B.cmd_apply(path, ids, "shown by a test")
            finally:
                sys.stdout = old_out
                del os.environ["QARGI_NOW"]
            with open(path) as f:
                rest = f.read()
            with open(os.path.join(d, "backlog-archive-2026-11.md")) as f:
                return rest, f.read()

    def test_several_items_go_with_the_same_evidence_in_one_archive_write(self):
        rest, arch = self.run_done("# T\n\n- [aa] one\n\n- [bb] two\n  more\n\n- [cc] three\n\n- [dd] four\n", "dd,aa,cc")
        self.assertEqual(rest, "# T\n\n- [bb] two\n  more\n")
        self.assertEqual(arch.count("Evidence: shown by a test"), 3)
        self.assertEqual([ln for ln in arch.splitlines() if ln.startswith("### ")], ["### 2026-11-08: dd", "### 2026-11-08: aa", "### 2026-11-08: cc"])

    def test_one_id_is_as_before_and_the_token_covers_every_id(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            with open(path, "w") as f:
                f.write("- [aa] one\n- [bb] two\n- [cc] three\n")
            self.assertNotEqual(B.plan_token(path, "aa,bb", "e"), B.plan_token(path, "aa", "e"))
            self.assertNotEqual(B.plan_token(path, "aa,bb", "e"), B.plan_token(path, "aa,cc", "e"))
            self.assertEqual(B.plan_token(path, "aa,bb", "e"), B.plan_token(path, "aa,bb", "e"))

    def test_a_missing_or_repeated_id_refuses_the_batch_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "backlog.md")
            text = "- [aa] one\n- [bb] two\n"
            with open(path, "w") as f:
                f.write(text)
            for ids in ("aa,zz", "aa,aa", "aa,B"):
                with self.assertRaises(B.BacklogError, msg=ids):
                    B.cmd_apply(path, ids, "e")
            with open(path) as f:
                self.assertEqual(f.read(), text)
            self.assertEqual(os.listdir(d), ["backlog.md"])


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
