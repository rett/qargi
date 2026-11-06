#!/usr/bin/env python3
"""The documentation site generator: the Markdown converter (lib/site_md.py) and lib/site.py, offline.
Run: python3 tests/test_site.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
LIB = os.path.join(ROOT, "lib")
SITE = os.path.join(LIB, "site.py")
FIX = os.path.join(HERE, "fixtures", "site")
PAGES = os.path.join(FIX, "pages")
BAD = os.path.join(FIX, "bad")
def slurp(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


RELEASE = slurp(os.path.join(ROOT, "VERSION")).strip()
RELEASE_DATE = re.search(r"## \[%s\] - (\d{4}-\d{2}-\d{2})" % re.escape(RELEASE), slurp(os.path.join(ROOT, "CHANGELOG.md"))).group(1)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


MD = load("t_site_md", os.path.join(LIB, "site_md.py"))
S = load("t_site", SITE)


def spit(path, text, mode="w"):
    with open(path, mode, encoding="utf-8") as f:
        f.write(text)


def run(*args, cwd=None):
    r = subprocess.run([sys.executable, "-I", SITE] + list(args), capture_output=True, text=True, cwd=cwd or ROOT)
    return r.returncode, r.stdout, r.stderr


def pg(pages):
    """--pages PAGES, and --config for the site.json beside the folder when the folder has none (the generator never looks upward)."""
    beside = os.path.join(os.path.dirname(pages), "site.json")
    if os.path.isfile(os.path.join(pages, "site.json")) or not os.path.isfile(beside):
        return ["--pages", pages]
    return ["--pages", pages, "--config", beside]


def build(out, pages=PAGES, *extra):
    return run("build", "--release", RELEASE, "--source", ROOT, *pg(pages), "--out", out, *extra)


class Converter(unittest.TestCase):
    def conv(self, text, **kw):
        return MD.convert(text, **kw)

    def test_supported_constructs(self):
        d = self.conv("## A *b* `c`\n\nSome **bold `code`** and _it_ snake_case x * y [l](/x/#h) \\* \\_\n\n"
                      "- one\n  more\n- two\n\n  para\n\n1. a\n2. b\n   - sub\n\n> q\n> r\n\n"
                      "| a | `x\\|y` |\n|:--|--:|\n| 1 | 2 |\n\n```bash\nqargi x <a>\n```\n\n---\n")
        h = d.html
        self.assertIn('<h2 id="a-b-c">A <em>b</em> <code>c</code> ', h)
        self.assertIn("<strong>bold <code>code</code></strong>", h)
        self.assertIn("snake_case x * y", h)
        self.assertIn('<a href="/x/#h">l</a> * _', h)
        self.assertIn("<ul><li>one\nmore</li><li><p>two</p><p>para</p></li></ul>", h)
        self.assertIn("<ol><li>a</li><li>b<ul><li>sub</li></ul></li></ol>", h)
        self.assertIn("<blockquote><p>q\nr</p></blockquote>", h)
        self.assertIn('<th scope="col" style="text-align:right"><code>x|y</code></th>', h)
        self.assertIn('<code class="language-bash">qargi x &lt;a&gt;</code>', h)
        self.assertIn("<hr>", h)
        self.assertEqual([x[:3] for x in d.headings], [(2, "a-b-c", "A b c")])
        self.assertEqual(d.links, [(3, "/x/#h")])
        self.assertIn((22, "fence:bash", "qargi x <a>"), d.code)

    def test_all_text_is_escaped(self):
        d = self.conv('## T&C "q"\n\nA < b and "x" & \'y\' `<script>` [a&b](https://e.org/?a=1&b=2)\n\n```text\n<img src=x onerror=alert(1)>\n```\n')
        self.assertNotIn("<script", d.html)
        self.assertNotIn("<img", d.html)
        self.assertIn("A &lt; b and &quot;x&quot; &amp; &#x27;y&#x27;", d.html)
        self.assertIn('href="https://e.org/?a=1&amp;b=2"', d.html)
        self.assertIn('id="t-c-q"', d.html)

    def test_refusals_carry_the_line_number(self):
        cases = [
            ("# T\n", 1, "start at ##"),
            ("## A\n\ntext <b>x</b>\n", 3, "raw HTML"),
            ("## A\n\n<div>x</div>\n", 3, "raw HTML"),
            ("## A\n\n![a](b)\n", 3, "images"),
            ("## A\n\n```\nx\n```\n", 3, "language"),
            ("## A\n\n```bash\nnever closed\n", 3, "never closed"),
            ("## A\n\n~~~\nx\n~~~\n", 3, "```"),
            ("## A\n\n* a\n", 3, "use -"),
            ("## A\n\n+ a\n", 3, "use -"),
            ("## A\n\ntext\n- a\n", 4, "blank line"),
            ("## A\n\ntext\n> q\n", 4, "blank line"),
            ("## A\n\n[a][b]\n", 3, "not an inline link"),
            ("## A\n\n[a]: http://x\n", 3, "reference link"),
            ("## A\n\nnote[^1]\n", 3, "footnotes"),
            ("## A\n\n[a](foo.md)\n", 3, "site path"),
            ("## A\n\n[a](javascript:alert(1))\n", 3, "control character"),
            ("## A\n\n[a](javascript:alert1)\n", 3, "use https://"),
            ("## A\n\n[a](//evil.example/x)\n", 3, "protocol-relative"),
            ("## A\n\n[a](https://x.org \"title\")\n", 3, "titles"),
            ("## A\n\n<https://x.org>\n", 3, "raw HTML"),
            ("## A\n\n- a\n  - b\n    - c\n", 5, "deeper than two"),
            ("## A\n\n- a\nlazy\n", 4, "lazy continuation"),
            ("## A\n\n#### B\n", 3, "jumps"),
            ("## A\n\n    code\n", 3, "indentation"),
            ("## A\n\n**bold\n", 3, "unclosed **"),
            ("## A\n\na `tick\n", 3, "unclosed code span"),
            ("## A\n\na &amp; b\n", 3, "character references"),
            ("## A\n\n| a | b |\n|---|---|\n| 1 |\n", 5, "cells"),
            ("## A\n\n| a | b |\n", 3, "table"),
            ("## A\n\nhello\n---\n", 4, "setext"),
            ("## A\n\n- a\n\n  text\n- \n", 6, "empty list item"),
            ("## A\n\n- a\n1. b\n", 4, "mix"),
            ("## A\n\n- > quote\n  # h\n", 4, "headings"),
            ("## A\n\n\tindented\n", 3, "tabs"),
            ("## A\n\n##### deep\n", 3, "deeper than the supported"),
            ("## A\n\n#nospace\n", 3, "heading is"),
            ("## A\n\na \\q b\n", 3, "backslash"),
            ("## A\n\nan _unclosed one\n", 3, "unclosed _"),
        ]
        for text, line, frag in cases:
            with self.assertRaises(MD.MdError, msg=repr(text)) as cm:
                self.conv(text)
            self.assertEqual(cm.exception.line, line, "%r: %s" % (text, cm.exception))
            self.assertIn(frag, cm.exception.msg, repr(text))

    def test_a_line_that_starts_with_a_tag_is_found_outside_fences(self):
        text = "\n".join([
            "a wrapped `qargi x",             # 1
            "<name>` call",                   # 2 found
            "> a quote `y",                   # 3
            "> <other>` and",                 # 4 found
            "- a bullet `z",                  # 5
            "  <third>` and",                 # 6 found
            "1. </close>",                    # 7 found
            "  - > <deep",                    # 8 found
            "<!-- a comment -->",             # 9 allowed
            "<a href=\"x\">link</a>",           # 10 allowed
            "<kbd>Ctrl</kbd> and <br>",       # 11 allowed
            "<details><summary>s</summary>",  # 12 found: block HTML for Kramdown
            "```bash",                        # 13
            "<name> in a fence",              # 14 not found
            "- <name> in a fence",            # 15 not found
            "```",                            # 16
            "text <name> inside a line",      # 17 not at the start
            "<div>raw</div>",                 # 18 found
            "<!doctype html>",                # 19 found
            "</ x",                           # 20 found
        ])
        got = MD.html_starts(text)
        self.assertEqual([ln for ln, _ in got], [2, 4, 6, 7, 8, 12, 18, 19, 20])
        self.assertEqual([ln for ln, _ in MD.html_starts("<summary>s</summary>\n- <sup>x</sup>\n<sub>y</sub>")], [1])
        self.assertIn('starts with "<name"', got[0][1])
        self.assertIn("raw HTML block", got[0][1])
        self.assertIn("keep a code span that holds a placeholder on one line, or put the placeholder after other text", got[0][1])
        self.assertEqual([ln for ln, _ in MD.html_starts(text, first_line=10)][:2], [11, 13])
        self.assertEqual([ln for ln, _ in MD.html_starts("<a>x\n<b>y", allow=())], [1, 2])
        self.assertEqual(MD.html_starts("no tag here\n- a < b\n"), [])

    def test_the_converter_refuses_such_a_line_in_a_paragraph_a_list_and_a_quote(self):
        for text, line in [("## A\n\nwrapped `x\n<name>` text\n", 4),
                           ("## A\n\n- an item `x\n  <name>` text\n", 4),
                           ("## A\n\n> a quote `x\n> <name>` text\n", 4),
                           ("## A\n\n- <name> first\n", 3)]:
            with self.assertRaises(MD.MdError, msg=repr(text)) as cm:
                self.conv(text)
            self.assertEqual(cm.exception.line, line, text)
            self.assertIn("so that no wrapped line begins with <", cm.exception.msg)

    def test_first_line_offsets_the_numbers(self):
        with self.assertRaises(MD.MdError) as cm:
            self.conv("## A\n\n<b>\n", first_line=10)
        self.assertEqual(cm.exception.line, 12)

    def test_tables_are_counted(self):
        d = self.conv("## A\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\ntext\n\n| c |\n|---|\n| 3 |\n")
        self.assertEqual(d.tables, 2)

    def test_heading_ids_are_unique_and_prefixed(self):
        d = self.conv("## Same\n\n### Same\n\n## Same\n", id_prefix="v1-")
        self.assertEqual([h[1] for h in d.headings], ["v1-same", "v1-same-2", "v1-same-3"])

    def test_a_byte_order_mark_is_named(self):
        with self.assertRaises(MD.MdError) as cm:
            MD.parse_front_matter("\ufeff---\ntitle: a\n---\n")
        self.assertIn("byte order mark", cm.exception.msg)

    def test_direction_characters_are_refused_in_link_targets(self):
        for ch in ["\u202e", "\u2066", "\u200f"]:
            with self.assertRaises(MD.MdError, msg=repr(ch)) as cm:
                self.conv("## A\n\n[a](https://example.org/x%sy)\n" % ch)
            self.assertIn("direction character", cm.exception.msg)

    def test_the_heading_anchor_names_its_section(self):
        d = self.conv("## Add *a* member\n")
        self.assertIn('aria-label="Link to: Add a member">#</a>', d.html)

    def test_front_matter(self):
        meta, n = MD.parse_front_matter('---\ntitle: "A: b"\ndescription: d\n---\nbody\n')
        self.assertEqual((meta, n), ({"title": "A: b", "description": "d"}, 4))
        self.assertEqual(MD.parse_front_matter("no front matter\n"), ({}, 0))
        for text, line, frag in [("---\ntitle x\n---\n", 2, "key: value"), ("---\ntitle: a\n", 1, "not closed"),
                                 ("---\ntitle: a\ntitle: b\n---\n", 3, "repeated"), ("---\ncolor: a\n---\n", 2, "not allowed")]:
            with self.assertRaises(MD.MdError) as cm:
                MD.parse_front_matter(text, {"title", "description"})
            self.assertEqual(cm.exception.line, line)
            self.assertIn(frag, cm.exception.msg)

    def test_the_changelog_converts_with_the_literal_option(self):
        text = slurp(os.path.join(ROOT, "CHANGELOG.md"))
        parts = re.split(r"(?m)^## \[(.*?)\].*$", text)
        self.assertGreater(len(parts), 5)
        for k in range(1, len(parts), 2):
            d = MD.convert(parts[k + 1], start_level=3, id_prefix=parts[k] + "-", literal=True)
            self.assertNotRegex(d.html, r"<(?!/?(?:p|ul|ol|li|code|strong|em|a|h\d|pre|blockquote|div|table|thead|tbody|tr|th|td|hr)[ >/])")


class CommandChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cmds = S.load_commands(ROOT)

    def words(self, line):
        out = []
        for seg in S.tokens_of(line):
            if seg and seg[0] == "qargi":
                out.append(S.check_words(self.cmds, seg[1:]))
        return out

    def test_valid_forms(self):
        for line in ["qargi project init acme --answers acme.json", "qargi help approvals", "qargi help project init", "qargi project", "qargi --help",
                     "qargi agent add forge --roles build,test --model=sonnet", "qargi COMMAND [VERB]", "qargi <cmd> run", "qargi project init NAME --force",
                     "qargi review check ./run && qargi review apply ./run", "qargi send acme-build \"$BRIEF\" --label x --asked \"use it\"",
                     "qargi feature start|finish", "qargi project template acme > acme.json", "qargi project init --help"]:
            self.assertEqual(self.words(line), [None] * len(self.words(line)), line)

    def test_invalid_forms(self):
        for line, frag in [("qargi nonesuch", "no command 'nonesuch'"), ("qargi project frobnicate", "no verb 'frobnicate'"),
                           ("qargi project init --nope", "no option --nope"), ("qargi agent add forge --roles build --bogus", "--bogus"),
                           ("qargi help nonesuch", "no command or topic"), ("qargi help project nonesuch", "no verb"),
                           ("qargi project --force init", "put the verb right after"), ("qargi projct init", "did you mean 'project'")]:
            msgs = [m for m in self.words(line) if m]
            self.assertTrue(msgs and frag in msgs[0], "%s -> %s" % (line, msgs))

    def test_spans_and_blocks(self):
        self.assertEqual(list(S.check_code(self.cmds, "span", "--asked REQUEST", 3)), [])
        self.assertEqual(list(S.check_code(self.cmds, "span", "--nope", 3)), [])          # options are checked on qargi command lines only
        self.assertEqual(list(S.check_code(self.cmds, "span", "install.sh --user", 3)), [])
        self.assertEqual(len(list(S.check_code(self.cmds, "span", "qargi project init --nope", 3))), 1)
        self.assertEqual(list(S.check_code(self.cmds, "fence:text", "qargi nonesuch", 1)), [])      # output blocks are not checked
        got = list(S.check_code(self.cmds, "fence:bash", "# qargi nonesuch\nqargi project \\\n  frob\nFOO=1 qargi nope", 10))
        self.assertEqual([g[0] for g in got], [12, 14])


class ShellChecks(unittest.TestCase):
    """S6: fenced shell blocks, read the way a shell reads them."""

    @classmethod
    def setUpClass(cls):
        cls.cmds = S.load_commands(ROOT)

    def lines(self, kind, text):
        return [(ln, m) for ln, m in S.check_code(self.cmds, kind, text, 0)]

    def ok(self, text, kind="fence:bash"):
        self.assertEqual(self.lines(kind, text), [], text)

    def bad(self, text, frag, line=None, kind="fence:bash"):
        got = self.lines(kind, text)
        self.assertTrue(got and frag in got[0][1], "%r -> %r" % (text, got))
        if line is not None:
            self.assertEqual(got[0][0], line, text)

    def test_text_that_is_not_a_command_is_not_checked(self):
        self.ok("cat <<EOF\nqargi nonesuch\nEOF\nqargi project init acme")
        self.ok("cat <<'EOF' > f\nqargi nonesuch\n  EOF\nEOF\n")
        self.ok("cat <<-EOF\n\tqargi nonesuch\n\tEOF\nqargi --version")
        self.ok("qargi send x \"line one\nline two\" --label y")
        self.ok("$ qargi --version\nqargi 0.2.0\n$ qargi project init acme\nreview: ok", kind="fence:console")
        self.ok("$ qargi --version\nqargi 0.2.0", kind="fence:shell-session")
        self.ok("qargi project init acme -- --literal")
        self.ok("qargi project init acme \\")
        self.ok("sudo ./install.sh --user\n./install.sh --user && qargi --version\ncurl -fsSL https://example.org/i.sh | sh -s -- --user")

    def test_the_continuation_of_a_command_is_one_command(self):
        self.bad("qargi project init acme \\\n  --nope", "--nope", line=1)
        self.bad("echo hi\nqargi project \\\n  frobnicate", "frobnicate", line=2)
        self.bad("$ qargi project init acme \\\n  --nope", "--nope", kind="fence:console")

    def test_wrappers_paths_and_substitutions_are_followed(self):
        for line in ["sudo qargi nonesuch", "sudo -u build qargi nonesuch", "env A=1 qargi nonesuch", "env -i A=1 qargi nonesuch", "if qargi nonesuch; then echo y; fi",
                     "for x in a b; do qargi nonesuch; done", "echo `qargi nonesuch`", "echo $(qargi nonesuch)", "./bin/qargi nonesuch", "/usr/local/bin/qargi nonesuch",
                     "A=1 time qargi nonesuch", "nohup qargi nonesuch &", "! qargi nonesuch", "(qargi nonesuch)"]:
            self.bad(line, "no command 'nonesuch'")

    def test_words_after_a_redirection_still_belong_to_the_command(self):
        self.bad("qargi project init acme > log --nope", "--nope")
        self.bad("qargi project init acme 2>&1 --nope", "--nope")
        self.bad("qargi project init acme &> log --nope", "--nope")
        self.ok("qargi project init acme > log 2>&1")
        self.ok("qargi project template acme >> out.json && qargi project init acme")

    def test_an_option_value_that_is_missing_is_found(self):
        self.bad("qargi project init acme --answers --force", "--answers needs a value")
        self.ok("qargi project init acme --answers")                    # a span or a line may name an option without its value
        self.ok("qargi project init acme --answers a.json --force")
        self.ok("qargi project init acme --answers=a.json")
        self.ok("qargi project init acme --answers FILE")

    def test_an_unreadable_command_line_is_reported(self):
        self.bad("qargi send x 'never closed\nsecond", "cannot read", line=1)

    def test_check_options_only_on_qargi_lines_in_a_page(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        pages = os.path.join(t, "pages")
        shutil.copytree(PAGES, pages)
        spit(os.path.join(pages, "first-project.md"), "\n## Install\n\nRun `install.sh --user` and then:\n\n```bash\n./install.sh --user\nqargi --version\n```\n\nThe `--user` option belongs to the installer.\n", "a")
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(pages))
        self.assertEqual((rc, err), (0, ""), out)


class Check(unittest.TestCase):
    def test_clean_pages_pass(self):
        t = tempfile.mkdtemp()                      # a copy outside git: the result does not depend on how the checkout was made
        self.addCleanup(shutil.rmtree, t, True)
        shutil.copytree(FIX, os.path.join(t, "f"))
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(os.path.join(t, "f", "pages")))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("0 error(s), 0 warning(s)", out)
        self.assertIn("note: index.md: no commit date (not in a git repository): no lastmod for this page", out)

    def test_bad_pages_are_reported_with_line_numbers(self):
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(BAD))
        self.assertEqual(rc, 1, out + err)
        want = ["unsupported.md:7: this line starts with \"<div\": a Kramdown (Jekyll) page reads it as the start of a raw HTML block",
                "broken.md:20: contains the forbidden word 'hunter2'",
                "broken.md:11: qargi project has no verb 'frobnicate'",
                "broken.md:12: qargi agent add has no option --no-such-option",
                "broken.md:15: `qargi nonesuch run`: qargi has no command 'nonesuch'",
                "broken.md:19: link /no-such-page/: no such page",
                "broken.md:19: link /reference/set-up/#no-such-heading: page /reference/set-up/ has no heading with id 'no-such-heading'",
                "broken.md:19: link #nowhere: no heading with that id on this page"]
        for w in want:
            self.assertIn("error: " + w, out)
        self.assertNotIn("broken.md:10", out)      # the valid command on line 10 is not reported
        self.assertIn("8 error(s)", out)

    def pages_with(self, body):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        pages = os.path.join(t, "pages")
        os.makedirs(pages)
        spit(os.path.join(pages, "a.md"), "---\ntitle: A page\ndescription: d\n---\n" + body)
        return pages

    def test_a_line_that_starts_with_a_tag_is_refused_with_its_file_line_and_fix(self):
        body = "## One\n\nA wrapped `qargi project\n<name>` call.\n\n> quote `x\n> <y>`\n\n- item `z\n  <w>`\n\n```bash\n<ok>\n```\n"
        rc, out, _ = run("check", "--release", RELEASE, "--source", ROOT, *pg(self.pages_with(body)), "--url", "https://docs.example.org/")
        self.assertEqual(rc, 1, out)
        for ln in (8, 11, 14):
            self.assertRegex(out, r"error: a\.md:%d: this line starts with \"<\w+\".*put the placeholder after other text" % ln)
        self.assertEqual(out.count("this line starts with"), 3)
        self.assertNotIn("a.md:18", out)                       # inside the fence

    def test_a_line_that_starts_with_a_tag_in_the_changelog_is_refused(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        src = source_copy(os.path.join(t, "src"), changelog=lambda x: x.replace("### Added\n", "### Added\n- A wrapped `qargi x\n  <name>` call.\n", 1))
        rc, out, _ = run("check", "--release", RELEASE, "--source", src, *pg(PAGES), "--allow-unreleased")
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"error: CHANGELOG\.md:\d+: this line starts with \"<name\"")
        self.assertIn("so that no wrapped line begins with <", out)

    def test_build_refuses_what_check_refuses(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        rc, out, err = build(os.path.join(t, "o"), BAD)
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(t, "o")))

    def test_the_release_must_match_the_source(self):
        rc, out, _ = run("check", "--release", "9.9.9", "--source", ROOT, *pg(PAGES))
        self.assertEqual(rc, 1)
        self.assertIn("not --release 9.9.9", out)
        rc, out, _ = run("check", "--release", "9.9.9", "--source", ROOT, *pg(PAGES), "--allow-unreleased")
        self.assertEqual(rc, 0, out)

    def test_description_length_warns(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        shutil.copytree(FIX, os.path.join(t, "f"))
        p = os.path.join(t, "f", "pages", "first-project.md")
        text = slurp(p)
        text = re.sub(r"(?m)^description: .*$", "description: Too short.", text)
        spit(p, text)
        rc, out, _ = run("check", "--release", RELEASE, "--source", ROOT, *pg(os.path.join(t, "f", "pages")))
        self.assertEqual(rc, 0, out)
        self.assertIn("warning: first-project.md: description is 10 characters", out)

    def test_front_matter_is_required(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        pages = os.path.join(t, "pages")
        os.makedirs(pages)
        spit(os.path.join(pages, "a.md"), "## No front matter\n")
        spit(os.path.join(pages, "b.md"), "---\ntitle: B\n---\n## Body\n")
        spit(os.path.join(pages, "Bad_Name.md"), "---\ntitle: C\ndescription: d\n---\n## Body\n")
        rc, out, _ = run("check", "--release", RELEASE, "--source", ROOT, *pg(pages), "--url", "https://docs.example.org/")
        self.assertEqual(rc, 1)
        self.assertIn("error: a.md:1: no front matter", out)
        self.assertIn("error: b.md:1: front matter needs description", out)
        self.assertIn("error: Bad_Name.md: page names are lower-case", out)


def source_copy(dest, changelog=None, commands=None):
    """A copy of the source tree the generator needs (lib, VERSION, LICENSE, CHANGELOG), with edits applied by the callables."""
    shutil.copytree(LIB, os.path.join(dest, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
    for n in ("VERSION", "LICENSE", "CHANGELOG.md"):
        shutil.copy(os.path.join(ROOT, n), dest)
    for rel, edit in (("CHANGELOG.md", changelog), (os.path.join("lib", "commands.py"), commands)):
        if edit:
            p = os.path.join(dest, rel)
            spit(p, edit(slurp(p)))
    return dest


class SourceChild(unittest.TestCase):
    """S5: the child that reads lib/commands.py runs the source's code, so it is boxed in."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.probe = os.path.join(self.tmp, "probe.json")

    def src(self, code):
        return source_copy(os.path.join(self.tmp, "src%d" % len(os.listdir(self.tmp))), commands=lambda t: code + "\n" + t)

    def test_the_child_runs_isolated_in_an_empty_folder_with_a_small_environment(self):
        code = ("import json, os, sys\n"
                "json.dump({'env': sorted(os.environ), 'cwd': os.getcwd(), 'home': os.environ.get('HOME'), 'no_site': sys.flags.no_site, 'isolated': sys.flags.isolated,\n"
                "           'dont_write': sys.flags.dont_write_bytecode, 'listing': os.listdir('.'), 'cpu': __import__('resource').getrlimit(__import__('resource').RLIMIT_CPU)[0]},\n"
                "          open(%r, 'w'))\nopen('marker', 'w').write('x')\n" % self.probe)
        src = self.src(code)
        here = os.path.join(self.tmp, "here")
        os.makedirs(here)
        old = os.getcwd()
        os.chdir(here)
        try:
            S.load_commands(src)
        finally:
            os.chdir(old)
        got = json.load(open(self.probe))
        self.assertLessEqual(set(got["env"]), {"PATH", "LANG", "HOME"})
        self.assertEqual((got["no_site"], got["isolated"], got["dont_write"]), (1, 1, 1))
        self.assertNotEqual(got["cwd"], here)
        self.assertEqual(got["home"], got["cwd"])
        self.assertEqual(got["listing"], [])
        self.assertEqual(os.listdir(here), [])                          # nothing was written to the caller's folder
        self.assertFalse(os.path.exists(got["cwd"]))                    # and the empty folder is gone
        self.assertEqual(got["cpu"], S.CHILD_CPU_SECONDS)

    def test_a_runaway_source_is_stopped_and_reported_as_a_refusal(self):
        from unittest import mock
        with mock.patch.object(S, "CHILD_CPU_SECONDS", 1):
            with self.assertRaises(S.Refusal) as cm:
                S.load_commands(self.src("while True:\n    pass\n"))
            self.assertIn("cannot load", str(cm.exception))
        with mock.patch.object(S, "CHILD_MEMORY_BYTES", 256 * 1024 * 1024):
            with self.assertRaises(S.Refusal) as cm:
                S.load_commands(self.src("x = bytearray(2 * 1024 ** 3)\n"))
            self.assertIn("MemoryError", str(cm.exception))
        with mock.patch.object(S, "CHILD_OUTPUT_BYTES", 1024 * 1024):
            with self.assertRaises(S.Refusal):
                S.load_commands(self.src("print('x' * (4 * 1024 * 1024))\n"))
        with mock.patch.object(S, "CHILD_TIMEOUT", 1):
            with self.assertRaises(S.Refusal) as cm:
                S.load_commands(self.src("import time\ntime.sleep(30)\n"))
            self.assertIn("timed out", str(cm.exception))

    def test_the_reported_error_has_no_control_characters(self):
        with self.assertRaises(S.Refusal) as cm:
            S.load_commands(self.src("raise RuntimeError('\\x1b]0;owned\\x07 boom ' + 'y' * 1000)\n"))
        msg = str(cm.exception)
        self.assertIn("boom", msg)
        self.assertNotRegex(msg, r"[\x00-\x08\x0b-\x1f\x7f]")
        self.assertLess(len(msg), 600)


class ChangelogLinks(unittest.TestCase):
    """S3: links in the changelog are validated like links in the hand pages."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_broken_changelog_links_fail_check_and_build(self):
        head = re.search(r"(?m)^## \[0\.1\.0\] - .*$", slurp(os.path.join(ROOT, "CHANGELOG.md"))).group(0)
        src = source_copy(os.path.join(self.tmp, "src"), changelog=lambda t: t.replace(
            head, head + "\n\nSee [up](/../../../), [nope](/nope/), [frag](#nope) and [ok](/reference/#typical-use).", 1))
        line = slurp(os.path.join(src, "CHANGELOG.md")).split("\n").index(head) + 3
        args = ["--release", RELEASE, "--source", src, *pg(PAGES)]
        rc, out, err = run("check", *args)
        self.assertEqual(rc, 1, out + err)
        self.assertIn("error: CHANGELOG.md:%d: link /nope/: no such page" % line, out)
        self.assertIn("error: CHANGELOG.md:%d: link /../../../: no such page" % line, out)
        self.assertIn("error: CHANGELOG.md:%d: link #nope: no heading with that id on this page" % line, out)
        self.assertNotIn("typical-use", out.split("link #nope")[0])
        self.assertIn("3 error(s)", out)
        o = os.path.join(self.tmp, "o")
        rc, out, err = run("build", *args, "--out", o)
        self.assertEqual(rc, 1, out + err)
        self.assertFalse(os.path.exists(o))


class Build(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.out = os.path.join(cls.tmp, "s")
        # a copy outside any git repository, so the pages have no commit dates and take the release date
        shutil.copytree(FIX, os.path.join(cls.tmp, "fix"))
        cls.rc, cls.stdout, cls.stderr = build(cls.out, os.path.join(cls.tmp, "fix", "pages"))

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def page(self, rel):
        return slurp(os.path.join(self.out, rel))

    def test_builds_and_the_output_checks(self):
        self.assertEqual((self.rc, self.stderr), (0, ""), self.stdout)
        rc, out, err = run("check-output", self.out, "--pages", os.path.join(self.tmp, "fix", "pages"))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_accessibility_markup(self):
        t = self.page("first-project/index.html")
        self.assertRegex(t, r'<pre class="code" tabindex="0" role="region" aria-label="bash code">')
        self.assertIn('aria-label="Link to: Add a member">#</a>', t)
        self.assertNotIn("Link to this section", t)
        self.assertNotIn("Link to this section", self.page("index.html"))
        ref = self.page("reference/set-up/index.html")
        self.assertIn('<div class="table-wrap" tabindex="0" role="region" aria-label="Table">', ref)
        self.assertIn('<nav aria-label="On this page"><details class="toc" open>', ref)
        self.assertRegex(ref, r'<li><a href="\./" aria-current="page">Overview</a></li>')            # the page itself, in its group
        self.assertNotIn('aria-current="true"', ref)                                               # an ancestor is not marked
        self.assertRegex(self.page("reference/index.html"), r'<li><a href="\./" aria-current="page">Overview</a></li>')
        self.assertIn('color-scheme: light dark', self.page("assets/site.css"))
        self.assertIn('<meta name="color-scheme" content="light dark">', t)

    def test_the_files_exist(self):
        for rel in ["index.html", "404.html", "first-project/index.html", "reference/index.html", "reference/set-up/index.html", "reference/topics/index.html",
                    "reference/files/index.html", "reference/environment/index.html", "releases/index.html", "sitemap.xml", "robots.txt", ".nojekyll",
                    "assets/site.css", "verify-acme.html"]:
            self.assertTrue(os.path.isfile(os.path.join(self.out, rel)), rel)
        self.assertEqual(slurp(os.path.join(FIX, "static", "verify-acme.html")), self.page("verify-acme.html"))
        self.assertEqual(os.path.getsize(os.path.join(self.out, ".nojekyll")), 0)

    def test_the_stylesheet_is_one_small_file_with_both_themes(self):
        css = self.page("assets/site.css")
        self.assertLess(len(css.encode()), 15 * 1024)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn("max-width: 48rem", css)
        self.assertNotIn("@import", css)
        self.assertNotIn("url(", css)

    def test_no_inline_script_and_no_external_requests(self):
        for dirpath, _, files in os.walk(self.out):
            for f in files:
                if f.endswith(".html") and f != "verify-acme.html":
                    t = slurp(os.path.join(dirpath, f))
                    for tag in re.findall(r"<script[^>]*>", t):
                        self.assertRegex(tag, r'^<script (?:type="application/ld\+json"|src="(?:\.\./)*assets/search\.js" defer)>$', f)       # no inline code
                    self.assertNotRegex(t, r"\son[a-z]+=", f)
                    for m in re.finditer(r'(?:src|href)="(https?://[^"]+)"', t):
                        if m.group(1).startswith(("https://docs.example.org/qargi/", "https://github.com/example/qargi")):
                            continue
                        self.assertRegex(m.group(1), r"^https?://", f)          # an external link is a link, never a resource
                    self.assertNotRegex(t, r'<(?:link|img|script|iframe)[^>]+(?:src|href)="https?://(?!docs\.example\.org)', f)

    def test_head_tags(self):
        t = self.page("first-project/index.html")
        self.assertIn("<title>Your first project · qargi</title>", t)
        self.assertIn('<link rel="canonical" href="https://docs.example.org/qargi/first-project/">', t)
        self.assertIn('<meta name="description" content="Set up a project called acme', t)
        self.assertIn('<meta property="og:type" content="article">', t)
        self.assertIn('<meta property="og:url" content="https://docs.example.org/qargi/first-project/">', t)
        self.assertIn('<meta name="twitter:card" content="summary">', t)
        self.assertIn('<html lang="en">', t)
        self.assertIn('<meta name="viewport"', t)
        self.assertIn('<meta name="color-scheme" content="light dark">', t)
        self.assertIn('<a class="skip" href="#main">', t)
        self.assertEqual(t.count("<h1>"), 1)
        home = self.page("index.html")
        self.assertIn("<title>qargi documentation</title>", home)
        self.assertIn('<meta property="og:type" content="website">', home)
        self.assertIn('rel="canonical" href="https://docs.example.org/qargi/"', home)

    def ld(self, rel):
        t = self.page(rel)
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', t, re.S)
        return json.loads(m.group(1))

    def test_json_ld(self):
        home = self.ld("index.html")
        types = {n["@type"]: n for n in home["@graph"]}
        app, site = types["SoftwareApplication"], types["WebSite"]
        self.assertEqual((site["name"], site["url"]), ("qargi", "https://docs.example.org/qargi/"))
        self.assertEqual(app["softwareVersion"], RELEASE)
        self.assertEqual(app["license"], "https://opensource.org/licenses/MIT")
        for k in ("offers", "operatingSystem", "author", "aggregateRating"):      # nothing the page does not show
            self.assertNotIn(k, app)
        g = self.ld("reference/set-up/index.html")["@graph"]
        art = [n for n in g if n["@type"] == "TechArticle"][0]
        self.assertEqual(art["headline"], "Reference: Set up")
        self.assertNotIn("author", art)                   # no author unless site.json names one that the footer shows
        crumbs = [n for n in g if n["@type"] == "BreadcrumbList"][0]["itemListElement"]
        self.assertEqual([c["position"] for c in crumbs], [1, 2, 3])
        self.assertEqual(crumbs[0]["item"], "https://docs.example.org/qargi/")
        self.assertEqual(crumbs[1]["item"], "https://docs.example.org/qargi/reference/")
        self.assertEqual(self.ld("first-project/index.html")["@graph"][1]["itemListElement"][1]["name"], "Your first project")

    def test_the_description_is_shown_and_no_date_is_marked_up_that_is_not_shown(self):
        t = self.page("first-project/index.html")
        self.assertRegex(t, r'<h1>Your first project</h1>\n<p class="lede">Set up a project called acme')
        self.assertNotIn("<time", t)                      # these copies have no commit date, so no date is shown or marked up
        self.assertNotIn("dateModified", t)
        ref = self.page("reference/set-up/index.html")
        self.assertIn('<p class="dates">Updated <time datetime="%s">%s</time></p>' % (RELEASE_DATE, RELEASE_DATE), ref)
        self.assertIn('"dateModified":"%s"' % RELEASE_DATE, ref)

    def test_an_author_named_in_the_config_is_shown_in_the_footer_and_marked_up(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        shutil.copytree(FIX, os.path.join(t, "f"))
        cfgp = os.path.join(t, "f", "site.json")
        data = json.loads(slurp(cfgp))
        data["author"] = {"name": "Example Docs Team", "url": "https://example.org/team"}
        spit(cfgp, json.dumps(data))
        o = os.path.join(t, "o")
        rc, out, err = build(o, os.path.join(t, "f", "pages"))
        self.assertEqual(rc, 0, out + err)
        page = slurp(os.path.join(o, "first-project", "index.html"))
        self.assertIn('By <a href="https://example.org/team">Example Docs Team</a>', page)
        ld = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S).group(1))
        art = [n for n in ld["@graph"] if n["@type"] == "TechArticle"][0]
        self.assertEqual(art["author"], {"@type": "Organization", "name": "Example Docs Team", "url": "https://example.org/team"})
        self.assertEqual(run("check-output", o)[0], 0)
        for bad in [{"url": "https://example.org"}, {"name": "x", "extra": 1}, "just a string", {"name": "x", "url": "http://example.org"}]:
            data["author"] = bad
            spit(cfgp, json.dumps(data))
            self.assertEqual(build(os.path.join(t, "o2"), os.path.join(t, "f", "pages"))[0], 2, bad)

    def built_with(self, **fields):
        """Build the fixture with these fields added to its site.json; returns (rc, out dir, output)."""
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        shutil.copytree(FIX, os.path.join(t, "f"))
        cfgp = os.path.join(t, "f", "site.json")
        data = json.loads(slurp(cfgp))
        data.update(fields)
        spit(cfgp, json.dumps(data))
        o = os.path.join(t, "o")
        rc, out, err = build(o, os.path.join(t, "f", "pages"))
        return rc, o, out + err

    PAGES_WITH_FOOTER = ("index.html", "first-project/index.html", "reference/set-up/index.html", "releases/index.html", "404.html")

    def test_copyright_unset_leaves_the_pages_as_they_were(self):
        for rel in self.PAGES_WITH_FOOTER:
            self.assertNotIn("copyright", self.page(rel).lower(), rel)
        rc, o, msg = self.built_with(copyright="(c) 2026 Example Author. MIT licensed.")
        self.assertEqual(rc, 0, msg)
        for rel in self.PAGES_WITH_FOOTER:
            with_it = slurp(os.path.join(o, rel))
            stripped = re.sub(r'<p class="copyright">.*?</p>\n', "", with_it)
            self.assertNotEqual(stripped, with_it, rel)
            self.assertEqual(stripped, self.page(rel), rel)       # nothing else on the page changes

    def test_a_copyright_is_shown_escaped_in_every_footer_including_the_404_page(self):
        rc, o, msg = self.built_with(copyright='(c) 2026 Example & Co "Author". MIT licensed.')
        self.assertEqual(rc, 0, msg)
        want = '<p class="copyright">(c) 2026 Example &amp; Co &quot;Author&quot;. MIT licensed.</p>'
        for rel in self.PAGES_WITH_FOOTER:
            page = slurp(os.path.join(o, rel))
            self.assertIn(want, page, rel)
            self.assertLess(page.index(want), page.index("</footer>"), rel)
        self.assertEqual(run("check-output", o)[0], 0)
        self.assertEqual(run("check-output", o, "--pages", PAGES)[0], 0)

    def test_the_words_mit_licensed_link_to_license_url(self):
        rc, o, msg = self.built_with(copyright="(c) 2026 Example Author. MIT licensed.", license_url="https://example.org/LICENSE")
        self.assertEqual(rc, 0, msg)
        want = '<p class="copyright">(c) 2026 Example Author. <a href="https://example.org/LICENSE">MIT licensed</a>.</p>'
        for rel in self.PAGES_WITH_FOOTER:
            self.assertIn(want, slurp(os.path.join(o, rel)), rel)
        self.assertEqual(run("check-output", o)[0], 0)
        # without those words the address is not shown, and check says so
        rc, o, msg = self.built_with(copyright="(c) 2026 Example Author.", license_url="https://example.org/LICENSE")
        self.assertEqual(rc, 0, msg)
        self.assertIn("license_url", msg)
        home = slurp(os.path.join(o, "index.html"))
        self.assertIn('<p class="copyright">(c) 2026 Example Author.</p>', home)
        self.assertNotIn("example.org/LICENSE", home)

    def test_a_copyright_with_markup_or_too_long_or_a_bad_address_is_refused(self):
        for bad in ["(c) <b>Example</b>", "(c) 2026 <script>alert(1)</script>", "line\nbreak", "tab\there", "", "   ", 5, ["x"], "x" * 201]:
            rc, o, msg = self.built_with(copyright=bad)
            self.assertEqual(rc, 2, (bad, msg))
            self.assertIn("copyright", msg)
            self.assertFalse(os.path.exists(o), bad)
        self.assertEqual(self.built_with(copyright="x" * 200)[0], 0)
        for bad in ["http://example.org/LICENSE", "example.org/LICENSE", "javascript:alert(1)", 5, "https://example.org/a b",
                    "https://user@example.org/", "https://example.org/license?x=1"]:
            rc, o, msg = self.built_with(copyright="(c) 2026 Example Author. MIT licensed.", license_url=bad)
            self.assertEqual(rc, 2, (bad, msg))
            self.assertIn("license_url", msg)

    def test_the_forbidden_words_apply_to_the_copyright(self):
        rc, o, msg = self.built_with(copyright="(c) 2026 Example Author. MIT licensed.", forbidden=["author"])
        self.assertEqual(rc, 1, msg)
        self.assertIn("copyright contains the forbidden word 'author'", msg)

    def test_sitemap_robots_and_404(self):
        root = ET.parse(os.path.join(self.out, "sitemap.xml")).getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        urls = {u.find(ns + "loc").text: u for u in root}
        self.assertIn("https://docs.example.org/qargi/", urls)
        self.assertIn("https://docs.example.org/qargi/reference/set-up/", urls)
        self.assertNotIn("https://docs.example.org/qargi/404.html", urls)
        self.assertEqual(len(urls), 14)
        # the generated pages carry the release date; a hand page with no commit date (these are copies outside git) has no lastmod, never a guess
        for loc, u in urls.items():
            hand = loc in ("https://docs.example.org/qargi/", "https://docs.example.org/qargi/first-project/")
            lm = u.find(ns + "lastmod")
            self.assertEqual(None if hand else RELEASE_DATE, None if lm is None else lm.text, loc)
            self.assertIsNone(u.find(ns + "priority"))
            self.assertIsNone(u.find(ns + "changefreq"))
        self.assertEqual(self.page("robots.txt"), "User-agent: *\nAllow: /\n\nSitemap: https://docs.example.org/qargi/sitemap.xml\n")
        n = self.page("404.html")
        self.assertIn('<meta name="robots" content="noindex">', n)
        self.assertNotIn('rel="canonical"', n)
        self.assertIn('href="https://docs.example.org/qargi/assets/site.css"', n)

    def test_links_are_relative(self):
        t = self.page("reference/set-up/index.html")
        self.assertIn('href="../../assets/site.css"', t)
        self.assertIn('<a href="../../first-project/">First project</a>', t)
        idx = self.page("index.html")
        self.assertIn('<a href="reference/set-up/#project-init">project init</a>', idx)
        self.assertNotRegex(self.page("first-project/index.html"), r'href="/')

    def test_the_reference_covers_every_command_verb_and_option(self):
        sys.path.insert(0, LIB)
        try:
            import commands as C
        finally:
            sys.path.remove(LIB)
        text = "".join(self.page("reference/%s/index.html" % d) for d in ["set-up", "run-a-task", "review-and-apply", "memory", "lead-and-credentials", "export-and-import", "other"])
        ids = set(re.findall(r'<h[23] id="([^"]+)"', text))
        for name, spec in C.COMMANDS.items():
            self.assertIn(name, ids)
            for v, vd in (spec.get("verbs") or {}).items():
                self.assertIn("%s-%s" % (name, v), ids)
                for o in vd["opts"]:
                    self.assertIn("<code>%s</code>" % o["flag"], text)
            for o in spec.get("opts", []):
                self.assertIn("<code>%s</code>" % o["flag"], text)
        topics = self.page("reference/topics/index.html")
        for t, (title, paras) in C.TOPICS.items():
            self.assertIn('id="topic-%s"' % t, topics)
        env = self.page("reference/environment/index.html")
        for k, _ in C.ENVIRONMENT:
            self.assertIn("<code>%s</code>" % k, env)
        files = self.page("reference/files/index.html")
        for p, _ in C.FILES:
            self.assertIn("<code>%s</code>" % p, files)

    def test_a_heading_called_main_does_not_repeat_the_template_id(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        pages = os.path.join(t, "pages")
        shutil.copytree(PAGES, pages)
        p = os.path.join(pages, "first-project.md")
        spit(p, "\n## Main\n\nSee [it](#main) and [the same](#main-2).\n", "a")
        rc, out, err = build(os.path.join(t, "o"), pages, "--url", "https://docs.example.org/qargi/")
        self.assertEqual(rc, 1, out)                       # #main is the page's main element, not the heading
        self.assertIn("link #main: no heading with that id", out)
        text = slurp(p).replace("See [it](#main) and ", "See ")
        spit(p, text)
        rc, out, err = build(os.path.join(t, "o"), pages, "--url", "https://docs.example.org/qargi/")
        self.assertEqual(rc, 0, out + err)
        page = slurp(os.path.join(t, "o", "first-project", "index.html"))
        self.assertIn('<h2 id="main-2">Main', page)
        self.assertEqual(page.count('id="main"'), 1)
        self.assertEqual(run("check-output", os.path.join(t, "o"))[0], 0)

    def test_generated_pages_reserve_the_template_ids(self):
        self.assertIn("main", S.RefBuilder(None).used)
        d = MD.convert("## Main\n", ids=set(S.PAGE_IDS))
        self.assertEqual(d.headings[0][1], "main-2")

    def test_the_releases_page_lists_every_released_version_and_not_unreleased(self):
        t = self.page("releases/index.html")
        self.assertIn('<h2 id="v%s">' % RELEASE.replace(".", "-"), t)
        self.assertIn('<h2 id="v0-1-0">', t)
        self.assertNotIn('id="vunreleased"', t)
        self.assertNotIn(">Unreleased ", t)
        self.assertIn('href="https://github.com/example/qargi/releases/tag/0.1.0"', t)
        self.assertRegex(t, r'<h3 id="v0-1-0-added">Added')

    def test_generated_descriptions_are_the_right_length(self):
        for dirpath, _, files in os.walk(self.out):
            if "index.html" in files:
                rel = os.path.relpath(os.path.join(dirpath, "index.html"), self.out)
                m = re.search(r'<meta name="description" content="([^"]*)"', self.page(rel))
                import html
                n = len(html.unescape(m.group(1)))
                self.assertTrue(120 <= n <= 155, "%s: %d" % (rel, n))
                t = re.search(r"<title>(.*?)</title>", self.page(rel)).group(1)
                self.assertLessEqual(len(html.unescape(t)), 60, rel)

    def test_unreleased_builds_have_no_invented_dates(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        o = os.path.join(t, "o")
        pages = os.path.join(self.tmp, "fix", "pages")        # not in a git repository: no commit dates
        rc, out, err = run("build", "--release", "9.9.9", "--source", ROOT, *pg(pages), "--out", o)
        self.assertEqual(rc, 1)
        rc, out, err = run("build", "--release", "9.9.9", "--source", ROOT, *pg(pages), "--out", o, "--allow-unreleased")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("qargi (unreleased)", slurp(os.path.join(o, "index.html")))
        self.assertIn("Checked against qargi (unreleased).", slurp(os.path.join(o, "index.html")))
        root = ET.parse(os.path.join(o, "sitemap.xml")).getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        for u in root:                    # no release date to give, so no lastmod at all
            self.assertIsNone(u.find(ns + "lastmod"), u.find(ns + "loc").text)
        self.assertEqual(run("check-output", o)[0], 0)

    def test_page_text_cannot_inject_html(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        pages = os.path.join(t, "pages")
        os.makedirs(pages)
        spit(os.path.join(pages, "index.md"), 
            '---\ntitle: "</title><script>alert(1)</script>"\ndescription: "A \\"quoted\\" description that is long enough to read well in a search result and says what the page is about, ok."\n---\n'
            '## Heading "x"\n\nText with `</script>` and a [link](https://example.org/?a=1&b="2").\n')
        rc, out, err = build(os.path.join(t, "o"), pages, "--url", "https://docs.example.org/qargi/")
        self.assertEqual(rc, 1, out)                       # the quote in the link target is refused
        text = slurp(os.path.join(pages, "index.md")).replace('"2"', "2")
        spit(os.path.join(pages, "index.md"), text)
        rc, out, err = build(os.path.join(t, "o2"), pages, "--url", "https://docs.example.org/qargi/")
        self.assertEqual(rc, 0, out + err)
        html_ = slurp(os.path.join(t, "o2", "index.html"))
        self.assertEqual(html_.count("<script"), 2)         # the JSON-LD and the search script, which has no inline code
        self.assertIn('<script src="assets/search.js" defer></script>', html_)
        self.assertNotIn("<script>alert", html_)
        self.assertIn("&lt;/title&gt;&lt;script&gt;", html_)
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html_, re.S)
        self.assertNotIn("</", m.group(1))
        self.assertEqual(json.loads(m.group(1))["@graph"][0]["name"], "qargi")
        rc, out, _ = run("check-output", os.path.join(t, "o2"))
        self.assertEqual(rc, 0, out)


class SidebarAndSearch(unittest.TestCase):
    """The left sidebar on every page but the 404 page and the client-side search: its index and its script."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        shutil.copytree(FIX, os.path.join(cls.tmp, "fix"))
        cls.pages = os.path.join(cls.tmp, "fix", "pages")
        cls.out = os.path.join(cls.tmp, "sub")                  # served under a path: https://docs.example.org/qargi/
        cls.rc, cls.stdout, cls.stderr = build(cls.out, cls.pages)
        cls.root = os.path.join(cls.tmp, "root")                # served at the root of a host
        cls.rc2, cls.stdout2, cls.stderr2 = build(cls.root, cls.pages, "--url", "https://docs.example.org/")
        cls.again = os.path.join(cls.tmp, "again")
        cls.rc3, _, _ = build(cls.again, cls.pages)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def page(self, rel, out=None):
        return slurp(os.path.join(out or self.out, rel))

    def html_files(self, out=None):
        out = out or self.out
        return sorted(os.path.relpath(os.path.join(d, f), out) for d, _, fs in os.walk(out) for f in fs if f.endswith(".html") and f != "verify-acme.html")

    def sidebar(self, rel, out=None):
        m = re.search(r'<div class="sidebar" id="sidebar">\n(.*?)\n</div>\n<main', self.page(rel, out), re.S)
        self.assertIsNotNone(m, rel)
        return m.group(1)

    def sections(self, rel):
        """name -> (open, markup) of the three sections of the sidebar of a page."""
        found = re.findall(r'<details class="side-section"( open)?>\n<summary>([^<]+)</summary>(.*?)\n</details>\n(?=<details class="side-section"|</nav>)', self.sidebar(rel), re.S)
        return {name: (bool(o), body) for o, name, body in found}

    def test_the_builds_succeed(self):
        for rc, out, err in ((self.rc, self.stdout, self.stderr), (self.rc2, self.stdout2, self.stderr2)):
            self.assertEqual((rc, err), (0, ""), out)
        self.assertEqual(self.rc3, 0)

    def test_every_page_but_the_404_page_has_the_sidebar_and_one_current_page(self):
        files = self.html_files()
        self.assertIn("reference/set-up/index.html", files)
        for rel in files:
            if rel == "404.html":
                continue
            t = self.page(rel)
            self.assertEqual(t.count('id="sidebar"'), 1, rel)
            side = self.sidebar(rel)
            self.assertEqual(len(re.findall(r'aria-current="page"', side)), 1, rel)
            self.assertEqual(list(self.sections(rel)), ["Guides", "Reference", "Releases"], rel)
            self.assertIn('<nav aria-label="Site">', side)
            self.assertIn('<label for="menu-toggle" class="menu-button">Menu</label>', t)         # the narrow-screen button needs no script
            self.assertIn('<input type="checkbox" id="menu-toggle" class="menu-toggle" aria-controls="sidebar">', t)
            self.assertIn('class="skip" href="#main"', t)
            self.assertNotIn('<ul>\n<li><a href="../">Home</a></li>\n<li><a href="../first-project/">First project</a></li>\n<li><a href="../reference/">Reference</a>', t)   # the top navigation list is gone
        self.assertRegex(self.sidebar("first-project/index.html"), r'<a href="\./" aria-current="page">First project</a>')
        self.assertRegex(self.sidebar("index.html"), r'<a href="\./" aria-current="page">Home</a>')
        self.assertRegex(self.sidebar("releases/index.html"), r'<a href="\./" aria-current="page">Release notes</a>')

    def test_the_current_section_is_open_and_the_others_are_closed(self):
        want = {"index.html": "Guides", "first-project/index.html": "Guides", "reference/index.html": "Reference",
                "reference/set-up/index.html": "Reference", "reference/topics/index.html": "Reference", "releases/index.html": "Releases"}
        for rel, current in want.items():
            opened = [name for name, (o, _) in self.sections(rel).items() if o]
            self.assertEqual(opened, [current], rel)
        # in the reference only the group of the current page is open
        ref = self.sections("reference/set-up/index.html")["Reference"][1]
        groups = re.findall(r'<details class="side-group"( open)?>\n<summary>([^<]+)</summary>', ref)
        self.assertEqual([name for o, name in groups if o], ["Set up"])
        self.assertGreater(len(groups), 3)
        refs = self.sections("reference/index.html")["Reference"][1]
        self.assertEqual([o for o, _ in re.findall(r'<details class="side-group"( open)?>\n<summary>([^<]+)</summary>', refs) if o], [])

    def test_the_commands_of_each_group_are_listed_under_it(self):
        sys.path.insert(0, LIB)
        try:
            import commands as C
        finally:
            sys.path.remove(LIB)
        side = self.sidebar("index.html")
        for title, names in C.GROUPS:
            m = re.search(r'<summary>%s</summary>\n<ul>\n(.*?)\n</ul>\n</details>' % re.escape(title), side, re.S)
            self.assertIsNotNone(m, title)
            hrefs = re.findall(r'<li><a href="([^"]+)"', m.group(1))
            slug = MD.slugify(title)
            self.assertEqual(hrefs, ["reference/%s/" % slug] + ["reference/%s/#%s" % (slug, n) for n in names], title)

    def resolve(self, rel, href):
        """(file, fragment) a relative link of the page rel leads to."""
        path, _, frag = href.partition("#")
        self.assertFalse(path.startswith("/") or "://" in path, href)
        if path == "":
            return rel, frag
        target = os.path.normpath(os.path.join(os.path.dirname(rel), path))
        return (os.path.join(target, "index.html") if path.endswith("/") else target), frag

    def test_the_links_of_the_sidebar_resolve(self):
        for rel in self.html_files():
            if rel == "404.html":
                continue
            side = self.sidebar(rel)
            hrefs = re.findall(r'href="([^"]+)"', side)
            self.assertGreater(len(hrefs), 20, rel)
            for h in hrefs:
                target, frag = self.resolve(rel, h)
                full = os.path.join(self.out, target)
                self.assertTrue(os.path.isfile(full), "%s: %s" % (rel, h))
                if frag:
                    self.assertIn('id="%s"' % frag, slurp(full), "%s: %s" % (rel, h))
        # the generator's own checker reads them too: breaking one is found
        d = os.path.join(self.tmp, "broken")
        shutil.copytree(self.out, d)
        p = os.path.join(d, "first-project", "index.html")
        t = slurp(p)
        self.assertIn('<li><a href="../releases/">Release notes</a></li>', t)
        spit(p, t.replace('<li><a href="../releases/">Release notes</a></li>', '<li><a href="../gone/">Release notes</a></li>'))
        rc, out, _ = run("check-output", d)
        self.assertEqual(rc, 1)
        self.assertIn("no such file gone/index.html", out)

    def test_the_sidebar_is_absent_from_the_404_page(self):
        for out, base in ((self.out, "https://docs.example.org/qargi/"), (self.root, "https://docs.example.org/")):
            t = self.page("404.html", out)
            self.assertNotIn("sidebar", t)
            self.assertNotIn("menu-toggle", t)
            self.assertNotIn("<script", t)
            self.assertIn('<a href="%s">The documentation home page</a>' % base, t)          # its absolute links stay
            self.assertIn('<a class="brand" href="%s">qargi</a>' % base, t)
            self.assertIn('<nav aria-label="Site">', t)
            self.assertIn('href="%sreference/"' % base, t)

    def test_sub_path_and_root_builds_have_the_same_relative_links(self):
        for rel in self.html_files():
            if rel == "404.html":
                continue
            self.assertEqual(self.sidebar(rel), self.sidebar(rel, self.root), rel)
            for out in (self.out, self.root):
                t = self.page(rel, out)
                self.assertNotRegex(self.sidebar(rel, out), r'href="(?:/|https?:)')
                self.assertRegex(t, r'<script src="(?:\.\./)*assets/search\.js" defer></script>')
        self.assertEqual(self.page("assets/search.js"), self.page("assets/search.js", self.root))
        self.assertEqual(self.page("assets/search-index.json"), self.page("assets/search-index.json", self.root))      # no address in it

    def test_no_inline_script_handler_or_style(self):
        for rel in self.html_files():
            t = self.page(rel)
            for tag in re.findall(r"<script[^>]*>(.*?)</script>", t, re.S):
                self.assertTrue(tag == "" or tag.startswith('{"@context"'), rel)       # nothing inline but the JSON-LD
            self.assertNotRegex(t, r"\son[a-z]+=", rel)
            self.assertNotRegex(t, r"\sstyle=", rel)
            self.assertNotIn("javascript:", t)

    def test_the_index_is_valid_bounded_and_clean(self):
        raw = self.page("assets/search-index.json")
        data = json.loads(raw)
        self.assertEqual(data["version"], 1)
        self.assertLessEqual(len(raw.encode()), S.INDEX_MAX_BYTES)
        self.assertIn("search index: %d entries, %d bytes" % (len(data["entries"]), len(raw.encode())), self.stdout)       # the size is reported
        forbidden = json.loads(slurp(os.path.join(FIX, "site.json")))["forbidden"]
        for w in forbidden:
            self.assertNotIn(w.lower(), raw.lower())
        self.assertNotIn(self.tmp, raw)
        self.assertNotRegex(raw, r"https?://")
        pages = {f[:-len("index.html")] if f.endswith("index.html") else f for f in self.html_files() if f != "404.html"}
        whole = [e["p"] for e in data["entries"] if "#" not in e["p"]]
        self.assertEqual(sorted(whole), sorted(pages))                       # one entry per page, and none for the 404 page
        for e in data["entries"]:
            self.assertEqual(set(e) - {"g"}, {"t", "p", "x"})
            self.assertTrue(e["t"] and e["x"] is not None)
            self.assertLessEqual(len(e["x"]), max(S.INDEX_PAGE_TEXT, S.INDEX_SECTION_TEXT))
            path, _, frag = e["p"].partition("#")
            if frag:
                self.assertIn('id="%s"' % frag, self.page(path + "index.html"))
                self.assertIn("g", e)
            self.assertNotRegex(e["x"], r'&(?:lt|gt|amp|quot|#\d+);|<a |<code|class="')       # plain text: no markup, no entities
        titles = {(e["t"], e["p"]) for e in data["entries"]}
        self.assertIn(("qargi release verify", "reference/run-a-task/#release-verify"), titles)      # a command section is searchable
        self.assertIn(("Your first project", "first-project/"), titles)

    def test_the_index_is_bounded_and_follows_the_pages_on_forbidden_words(self):
        site = type("FakeSite", (), {})()
        site.cfg = None
        site.pages = {"": S.Page("", "home", "Home", "Home page.", "<p>%s</p>" % ("word " * 400)),
                      "a/": S.Page("a/", "hand", "A", "A page.", '<h2 id="x">Sec</h2><p>%s</p>' % ("long " * 400))}
        rep = S.Report()
        data = S.search_index(site, rep)
        self.assertEqual(rep.errors, [])
        entries = json.loads(data)["entries"]
        self.assertEqual([e["p"] for e in entries], ["", "a/", "a/#x"])
        self.assertLessEqual(len(entries[0]["x"]), S.INDEX_PAGE_TEXT)
        self.assertLessEqual(len(entries[2]["x"]), S.INDEX_SECTION_TEXT)
        self.assertFalse(entries[2]["x"].endswith(" "))
        old = S.INDEX_MAX_BYTES
        S.INDEX_MAX_BYTES = 100
        try:
            rep = S.Report()
            S.search_index(site, rep)
        finally:
            S.INDEX_MAX_BYTES = old
        self.assertEqual(len(rep.errors), 1)
        self.assertIn("more than the limit of 100", rep.errors[0])
        # a word the config forbids that only a generated page carries is no error: the reference documents the tool, and the
        # index holds what the pages hold (a hand page with the word fails on its own line, as before)
        d = os.path.join(self.tmp, "forbid")
        shutil.copytree(os.path.join(self.tmp, "fix"), d)
        cfg = os.path.join(d, "site.json")
        data = json.loads(slurp(cfg))
        data["forbidden"] = ["whether the whole suite passed"]
        spit(cfg, json.dumps(data))
        rc, out, err = build(os.path.join(self.tmp, "forbid-out"), os.path.join(d, "pages"))
        self.assertEqual(rc, 0, out + err)
        self.assertNotIn("forbidden word", out + err)

    def test_the_script_is_one_small_file_with_no_dynamic_code_and_no_network_beyond_the_index(self):
        js = self.page("assets/search.js")
        self.assertEqual(js, slurp(os.path.join(LIB, "site", "search.js")))                     # the bytes of the source, nothing stamped in
        self.assertLess(len(js.encode()), S.JS_WARN_BYTES)
        for banned in ("eval(", "new Function", "innerHTML", "outerHTML", "document.write", "insertAdjacentHTML", "setTimeout(\"", "XMLHttpRequest", "importScripts", "http:", "https:", "localStorage", "sendBeacon"):
            self.assertNotIn(banned, js)
        self.assertIn("document.currentScript", js)              # the base is the script's own address, so any base path works
        self.assertIn('"search-index.json"', js)
        self.assertEqual(len(re.findall(r"\bfetch\(", js)), 1)
        self.assertIn("aria-live", js)
        for key in ("ArrowDown", "ArrowUp", "Enter", "Escape"):
            self.assertIn('"%s"' % key, js)

    def test_the_whole_build_is_reproducible(self):
        def tree(root):
            out = {}
            for d, _, fs in os.walk(root):
                for f in fs:
                    with open(os.path.join(d, f), "rb") as fh:
                        out[os.path.relpath(os.path.join(d, f), root)] = fh.read()
            return out
        a, b = tree(self.out), tree(self.again)
        self.assertEqual(sorted(a), sorted(b))
        for k in a:
            self.assertEqual(a[k], b[k], k)
        self.assertIn("assets/search.js", a)
        self.assertIn("assets/search-index.json", a)

    def test_the_stylesheet_has_the_sidebar_the_narrow_menu_and_print(self):
        css = self.page("assets/site.css")
        self.assertLess(len(css.encode()), 15 * 1024)
        self.assertRegex(css, r"@media \(max-width: 48rem\)[^@]*\.menu-toggle:checked ~ \.layout \.sidebar \{ display: block; \}")
        self.assertRegex(css, r"@media print \{[^}]*\.sidebar")
        self.assertIn("position: sticky", css)
        self.assertNotIn("url(", css)


class LastMod(unittest.TestCase):
    def git(self, d, *a, date=None):
        env = {"PATH": os.environ["PATH"], "HOME": d, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        if date:
            env["GIT_COMMITTER_DATE"] = env["GIT_AUTHOR_DATE"] = date
        subprocess.run(["git", "-C", d] + list(a), check=True, capture_output=True, env=env)

    def test_hand_pages_take_their_last_commit_date(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        f = os.path.join(t, "f")
        shutil.copytree(FIX, f)
        self.git(f, "init", "-q", "-b", "main")
        self.git(f, "add", "-A")
        self.git(f, "commit", "-q", "-m", "first", date="2026-01-15T10:00:00+00:00")
        p = os.path.join(f, "pages", "first-project.md")
        spit(p, "\nOne more line.\n", "a")
        self.git(f, "add", "-A")
        self.git(f, "commit", "-q", "-m", "second", date="2026-03-02T10:00:00+00:00")
        spit(os.path.join(f, "pages", "index.md"), "\nUncommitted.\n", "a")      # modified: no commit date can be trusted
        out = os.path.join(t, "o")
        rc, so, se = build(out, os.path.join(f, "pages"))
        self.assertEqual(rc, 0, so + se)
        root = ET.parse(os.path.join(out, "sitemap.xml")).getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        lm = {u.find(ns + "loc").text: getattr(u.find(ns + "lastmod"), "text", None) for u in root}
        self.assertEqual(lm["https://docs.example.org/qargi/first-project/"], "2026-03-02")
        self.assertIsNone(lm["https://docs.example.org/qargi/"])                      # modified: no date to give, none invented
        self.assertEqual(lm["https://docs.example.org/qargi/releases/"], RELEASE_DATE)
        self.assertIn("note: index.md: no commit date", so)
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', slurp(os.path.join(out, "first-project", "index.html")), re.S).group(1)
        art = json.loads(ld)["@graph"][0]
        self.assertEqual((art["dateModified"], art["datePublished"]), ("2026-03-02", "2026-01-15"))
        page = slurp(os.path.join(out, "first-project", "index.html"))
        self.assertIn('<p class="dates">Published <time datetime="2026-01-15">2026-01-15</time> · Updated <time datetime="2026-03-02">2026-03-02</time></p>', page)
        self.assertEqual(run("check-output", out)[0], 0)
        spit(os.path.join(out, "first-project", "index.html"), page.replace('<time datetime="2026-03-02">', '<time datetime="2026-03-03">'))
        rc, so, se = run("check-output", out)
        self.assertEqual(rc, 1, so)
        self.assertIn("dateModified 2026-03-02 is not shown on the page", so)

    def make_repo(self, t):
        f = os.path.join(t, "f")
        shutil.copytree(FIX, f)
        self.git(f, "init", "-q", "-b", "main")
        self.git(f, "add", "-A")
        self.git(f, "commit", "-q", "-m", "first", date="2026-01-15T10:00:00+00:00")
        return f

    def test_a_shallow_clone_has_no_page_dates_and_says_so(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        f = self.make_repo(t)
        spit(os.path.join(f, "unrelated.txt"), "x")
        self.git(f, "add", "-A")
        self.git(f, "commit", "-q", "-m", "second", date="2026-11-01T10:00:00+00:00")
        self.git(t, "clone", "-q", "--depth", "1", "file://" + f, "c")
        c = os.path.join(t, "c")
        out = os.path.join(t, "o")
        rc, so, se = build(out, os.path.join(c, "pages"))
        self.assertEqual(rc, 0, so + se)
        self.assertIn("warning: pages: shallow clone", so)
        root = ET.parse(os.path.join(out, "sitemap.xml")).getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        for u in root:                                 # not the tip commit's date, which says nothing about the page
            self.assertEqual(u.find(ns + "lastmod").text, RELEASE_DATE, u.find(ns + "loc").text)
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', slurp(os.path.join(out, "first-project", "index.html")), re.S).group(1)
        self.assertNotIn("datePublished", ld)
        self.assertEqual(run("check-output", out)[0], 0)

    def test_git_runs_nothing_the_repository_configures(self):
        if not shutil.which("git"):
            self.skipTest("git is not installed")
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        f = self.make_repo(t)
        marker = os.path.join(t, "ran")
        script = os.path.join(t, "evil.sh")
        spit(script, "#!/bin/sh\necho ran >> %s\nexit 1\n" % marker)
        os.chmod(script, 0o755)
        self.git(f, "config", "core.fsmonitor", script)
        self.git(f, "config", "filter.evil.clean", script)
        self.git(f, "config", "core.hooksPath", os.path.join(t, "hooks"))
        spit(os.path.join(f, ".gitattributes"), "*.md filter=evil\n")
        self.git(f, "config", "core.fsmonitor", script)
        before = os.path.exists(marker)
        rc, so, se = build(os.path.join(t, "o"), os.path.join(f, "pages"))
        self.assertEqual(rc, 0, so + se)
        self.assertFalse(os.path.exists(marker) and not before, "the repository's fsmonitor or filter program ran")


class Safety(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_pages_outside_the_allowed_roots_are_refused(self):
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, "--pages", "/etc", cwd=self.tmp)
        self.assertEqual(rc, 2, out)
        self.assertIn("outside the allowed roots", err)

    def test_a_symlinked_page_or_folder_is_refused(self):
        pages = os.path.join(self.tmp, "pages")
        os.makedirs(pages)
        shutil.copy(os.path.join(PAGES, "index.md"), pages)
        os.symlink("/etc/hostname", os.path.join(pages, "evil.md"))
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(pages))
        self.assertEqual(rc, 2, out)
        self.assertIn("symbolic link", err)
        link = os.path.join(self.tmp, "link")
        os.symlink("/etc", link)
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(link))
        self.assertEqual(rc, 2)
        self.assertIn("outside the allowed roots", err)

    def test_out_must_be_new_or_empty(self):
        out = os.path.join(self.tmp, "o")
        os.makedirs(out)
        spit(os.path.join(out, "keep.txt"), "x")
        rc, so, se = build(out)
        self.assertEqual(rc, 2)
        self.assertIn("not empty", se)
        self.assertEqual(os.listdir(out), ["keep.txt"])
        empty = os.path.join(self.tmp, "e")
        os.makedirs(empty)
        self.assertEqual(build(empty)[0], 0)
        f = os.path.join(self.tmp, "file")
        spit(f, "x")
        self.assertEqual(build(f)[0], 2)

    def test_out_cannot_contain_the_source_or_the_pages(self):
        for out in [ROOT, os.path.dirname(ROOT), os.sep]:
            rc, so, se = build(out)
            self.assertEqual(rc, 2, out)
        pages = os.path.join(self.tmp, "o", "pages")
        os.makedirs(pages)
        shutil.copy(os.path.join(PAGES, "index.md"), pages)
        os.remove(os.path.join(pages, "index.md"))
        rc, so, se = build(os.path.join(self.tmp, "o"), pages)
        self.assertEqual(rc, 2)

    def test_build_needs_an_https_address(self):
        rc, so, se = run("build", "--release", RELEASE, "--source", ROOT, "--out", os.path.join(self.tmp, "o"))
        self.assertEqual(rc, 2)
        self.assertIn("site address", se)
        rc, so, se = run("build", "--release", RELEASE, "--source", ROOT, "--out", os.path.join(self.tmp, "o"), "--url", "http://x.example/")
        self.assertEqual(rc, 2)
        self.assertIn("https://", se)
        rc, so, se = run("build", "--release", RELEASE, "--source", ROOT, "--out", os.path.join(self.tmp, "o"), "--url", "https://x.example/")
        self.assertEqual(rc, 0, so + se)           # no hand pages: a generated home page lists the others
        self.assertEqual(run("check-output", os.path.join(self.tmp, "o"))[0], 0)


class ConfigTrust(unittest.TestCase):
    """B1, S10, N2: where site.json and static/ come from, and who may own them."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = os.path.join(self.tmp, "f")
        shutil.copytree(FIX, self.f)
        self.pages = os.path.join(self.f, "pages")
        self.cfg = os.path.join(self.f, "site.json")

    def raw(self, *extra, pages=None):
        return run("build", "--release", RELEASE, "--source", ROOT, "--pages", pages or self.pages, "--out", os.path.join(self.tmp, "o"), *extra)

    def test_no_site_json_is_taken_from_the_parent_folder(self):
        rc, out, err = self.raw()
        self.assertEqual(rc, 2, out)                      # the parent's site.json (and its url) are not used
        self.assertIn("site address", err)
        rc, out, err = self.raw("--url", "https://docs.example.org/qargi/")
        self.assertEqual(rc, 0, out + err)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "o", "verify-acme.html")))     # nor its static/ folder
        self.assertNotIn("github.com", slurp(os.path.join(self.tmp, "o", "index.html")))

    def test_the_config_comes_from_config_or_pages(self):
        rc, out, err = self.raw("--config", self.cfg)
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(os.path.join(self.tmp, "o", "verify-acme.html")))
        shutil.rmtree(os.path.join(self.tmp, "o"))
        shutil.copy(self.cfg, self.pages)
        rc, out, err = self.raw()
        self.assertEqual(rc, 0, out + err)
        self.assertIn("github.com/example/qargi", slurp(os.path.join(self.tmp, "o", "index.html")))
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "o", "verify-acme.html")))     # static/ is beside the config, here pages/static

    def test_a_symlinked_config_is_refused(self):
        other = os.path.join(self.tmp, "other")
        os.makedirs(os.path.join(other, "static"))
        spit(os.path.join(other, "static", "from-other.txt"), "x")
        shutil.copy(self.cfg, os.path.join(other, "site.json"))
        os.symlink(os.path.join(other, "site.json"), os.path.join(self.pages, "site.json"))
        rc, out, err = self.raw()
        self.assertEqual(rc, 2, out)
        self.assertIn("symbolic link", err)
        rc, out, err = self.raw("--config", os.path.join(self.pages, "site.json"))
        self.assertEqual(rc, 2, out)
        self.assertIn("symbolic link", err)

    def test_a_pages_folder_that_is_a_symlink_is_refused(self):
        link = os.path.join(self.tmp, "link")
        os.symlink(self.pages, link)
        rc, out, err = self.raw("--config", self.cfg, pages=link)
        self.assertEqual(rc, 2, out)
        self.assertIn("symbolic link", err)

    def test_a_config_folder_others_can_write_is_refused(self):
        os.chmod(self.f, 0o757)
        rc, out, err = self.raw("--config", self.cfg)
        self.assertEqual(rc, 2, out)
        self.assertIn("can be written by other users", err)
        os.chmod(self.f, 0o755)
        os.chmod(os.path.join(self.f, "static"), 0o757)
        rc, out, err = self.raw("--config", self.cfg)
        self.assertEqual(rc, 2, out)
        self.assertIn("static", err)

    def test_a_config_or_static_file_of_another_user_is_refused(self):
        from unittest import mock
        roots = S.allowed_roots(ROOT, [self.tmp])

        class A:
            config = self.cfg
        with mock.patch.object(S.os, "geteuid", return_value=os.geteuid() + 1):
            with self.assertRaises(S.Refusal) as cm:
                S.find_config(A, self.pages, roots)
            self.assertIn("owned by another user", str(cm.exception))
        with mock.patch.object(S.os, "getegid", return_value=os.getegid() + 1):
            os.chmod(self.f, 0o775)
            with self.assertRaises(S.Refusal) as cm:
                S.find_config(A, self.pages, roots)
            self.assertIn("written by other users", str(cm.exception))      # group-writable, and the group is not the user's own
        os.chmod(self.f, 0o775)
        self.assertIsNotNone(S.find_config(A, self.pages, roots))          # the user's own group may write

    def test_a_hard_linked_static_file_is_refused(self):
        outside = os.path.join(self.tmp, "outside.txt")
        spit(outside, "secret")
        os.link(outside, os.path.join(self.f, "static", "hl.txt"))
        rc, out, err = self.raw("--config", self.cfg)
        self.assertEqual(rc, 2, out)
        self.assertIn("hard link", err)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "o")))


class StaticAndOut(unittest.TestCase):
    """S2, N1, N2: static files against generated paths, building in a temporary folder, --out placement."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.f = os.path.join(self.tmp, "f")
        shutil.copytree(FIX, self.f)
        self.static = os.path.join(self.f, "static")
        self.out = os.path.join(self.tmp, "o")

    def b(self, *extra):
        return build(self.out, os.path.join(self.f, "pages"), *extra)

    def test_a_static_file_on_a_generated_path_is_an_error_before_anything_is_written(self):
        for name in ["first-project", "assets", "reference", "releases", "sitemap.xml", "Index.html", "FIRST-PROJECT", "404.html", "index.html/x"]:
            d = os.path.join(self.f, "static", *name.split("/")[:-1])
            os.makedirs(d, exist_ok=True)
            spit(os.path.join(self.static, *name.split("/")), "x")
            rc, out, err = self.b()
            self.assertEqual((rc, "Traceback" in err), (1, False), "%s: %s%s" % (name, out, err))
            self.assertIn("static/%s: collides with a generated file or folder" % name, out)
            self.assertFalse(os.path.exists(self.out), name)
            shutil.rmtree(self.static)
            shutil.copytree(os.path.join(FIX, "static"), self.static)

    def test_two_static_files_that_differ_only_by_case_are_an_error(self):
        spit(os.path.join(self.static, "Notes.txt"), "a")
        spit(os.path.join(self.static, "notes.txt"), "b")
        rc, out, err = self.b()
        self.assertEqual(rc, 1, out)
        self.assertIn("differs only by case", out)

    def test_a_failed_build_leaves_nothing_and_a_good_one_leaves_only_the_site(self):
        from unittest import mock
        argv = ["build", "--release", RELEASE, "--source", ROOT, "--pages", os.path.join(self.f, "pages"), "--config", os.path.join(self.f, "site.json"), "--out", self.out]
        with mock.patch.object(S, "render_page", side_effect=S.Refusal("boom")):
            self.assertEqual(S.main(argv), 2)
        self.assertEqual(os.listdir(self.tmp), ["f"])
        os.makedirs(self.out)                                  # an empty folder that existed stays empty
        with mock.patch.object(S, "render_page", side_effect=S.Refusal("boom")):
            self.assertEqual(S.main(argv), 2)
        self.assertEqual(os.listdir(self.out), [])
        self.assertEqual(sorted(os.listdir(self.tmp)), ["f", "o"])
        self.assertEqual(S.main(argv), 0)
        self.assertEqual(sorted(os.listdir(self.tmp)), ["f", "o"])
        self.assertTrue(os.path.isfile(os.path.join(self.out, "index.html")))
        self.assertTrue(os.stat(self.out).st_mode & 0o005)      # readable by a web server: not the private mode of a temporary folder

    def test_out_inside_pages_or_static_is_refused(self):
        for sub in [os.path.join(self.f, "pages", "site"), os.path.join(self.static, "out"), self.static]:
            rc, out, err = build(sub, os.path.join(self.f, "pages"))
            self.assertEqual(rc, 2, sub + out)
            self.assertIn("would be inside", err)
            self.assertFalse(os.path.exists(os.path.join(sub, "index.html")))

    def test_well_known_is_copied_other_hidden_folders_are_reported_and_readme_is_not_published(self):
        os.makedirs(os.path.join(self.static, ".well-known"))
        spit(os.path.join(self.static, ".well-known", "security.txt"), "Contact: mailto:security@example.org\n")
        os.makedirs(os.path.join(self.static, ".hidden"))
        spit(os.path.join(self.static, ".hidden", "x.txt"), "x")
        spit(os.path.join(self.static, "README.md"), "# Notes for the maintainers\n")
        rc, out, err = self.b()
        self.assertEqual(rc, 0, out + err)
        self.assertTrue(os.path.isfile(os.path.join(self.out, ".well-known", "security.txt")))
        self.assertFalse(os.path.exists(os.path.join(self.out, ".hidden")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "README.md")))
        self.assertIn("warning: static/.hidden: a hidden folder is not published", out)
        self.assertIn("note: static/README.md: not published", out)
        self.assertEqual(run("check-output", self.out)[0], 0)


class SmallInputs(unittest.TestCase):
    """N3, N5, N6."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_control_and_direction_characters_are_refused_in_the_site_address(self):
        for bad in ["https://example.org/a\x01b/", "https://example.org/a\x7fb/", "https://example.org/a\u202eb/"]:
            with self.assertRaises(S.Refusal, msg=repr(bad)):
                S.normalize_url(bad)
        self.assertEqual(S.normalize_url("https://example.org/a"), "https://example.org/a/")

    def test_a_page_listed_twice_in_the_menu_is_an_error(self):
        f = os.path.join(self.tmp, "f")
        shutil.copytree(FIX, f)
        cfgp = os.path.join(f, "site.json")
        data = json.loads(slurp(cfgp))
        data["pages"] = ["first-project", "first-project"]
        spit(cfgp, json.dumps(data))
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(os.path.join(f, "pages")))
        self.assertEqual(rc, 1, out)
        self.assertIn("error: site.json: pages lists 'first-project' twice", out)

    def test_an_address_with_a_path_says_where_robots_txt_is_read(self):
        f = os.path.join(self.tmp, "f")
        shutil.copytree(FIX, f)
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(os.path.join(f, "pages")))
        self.assertEqual(rc, 0, out)
        self.assertIn("note: url: the address has a path: crawlers read robots.txt only at the root of the host", out)
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(os.path.join(f, "pages")), "--url", "https://docs.example.org/")
        self.assertNotIn("note: url", out)


class CheckOutput(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.good = os.path.join(cls.tmp, "good")
        rc, out, err = build(cls.good)
        assert rc == 0, out + err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def broken(self, name, edit):
        d = os.path.join(self.tmp, name)
        shutil.copytree(self.good, d)
        edit(d)
        rc, out, err = run("check-output", d)
        return rc, out

    def h4(self, d):
        p = os.path.join(d, "first-project", "index.html")
        spit(p, re.sub(r'<h2 id="add-a-member">(.*?)</h2>', r'<h4 id="add-a-member">\1</h4>', slurp(p)))

    def sub(self, rel, old, new):
        def edit(d):
            p = os.path.join(d, rel)
            t = slurp(p)
            assert old in t, (rel, old)
            spit(p, t.replace(old, new, 1))
        return edit

    def drop_entry(self, path):
        def edit(d):
            p = os.path.join(d, "assets", "search-index.json")
            data = json.loads(slurp(p))
            data["entries"] = [e for e in data["entries"] if e["p"] != path]
            spit(p, json.dumps(data))
        return edit

    def test_each_defect_is_found(self):
        cases = [
            ("dupid", self.sub("first-project/index.html", 'id="add-a-member"', 'id="store-the-answers"'), "id 'store-the-answers' is used more than once"),
            ("badlink", self.sub("first-project/index.html", 'href="../releases/"', 'href="../nope/"'), "no such file nope/index.html"),
            ("badfrag", self.sub("first-project/index.html", 'href="../reference/set-up/#project-init"', 'href="../reference/set-up/#nope"'), "no element with id 'nope'"),
            ("noslash", self.sub("first-project/index.html", 'href="../releases/"', 'href="../releases"'), "should end with /"),
            ("unclosed", self.sub("first-project/index.html", "</blockquote>", ""), "</article> closes <blockquote>"),
            ("mismatch", self.sub("first-project/index.html", "</ol>", "</ul>"), "</ul> closes <ol>"),
            ("img", self.sub("first-project/index.html", "<article>", '<article><img src="../assets/site.css">'), "<img> without alt text"),
            ("h1", self.sub("first-project/index.html", "<h1>Your first project</h1>", "<h1>Your first project</h1><h1>Two</h1>"), "exactly one h1"),
            ("skip", self.h4, "heading level jumps from h2 to h4"),
            ("canon", self.sub("first-project/index.html", 'rel="canonical" href="https://docs.example.org/qargi/first-project/"', 'rel="canonical" href="https://docs.example.org/qargi/other/"'), "canonical is"),
            ("lang", self.sub("first-project/index.html", '<html lang="en">', "<html>"), 'needs lang="en"'),
            ("desc", self.sub("first-project/index.html", '<meta name="description" content="Set up', '<meta name="x" content="Set up'), "no meta description"),
            ("ld", self.sub("first-project/index.html", '"headline":"Your first project"', '"headline":"Something else"'), "headline"),
            ("js", self.sub("first-project/index.html", 'href="../releases/"', 'href="javascript:alert(1)"'), "javascript: links"),
            ("data", self.sub("first-project/index.html", 'href="../releases/"', 'href="data:text/html,x"'), "data:"),
            ("vbs", self.sub("first-project/index.html", 'href="../releases/"', 'href="vbscript:msgbox(1)"'), "scheme"),
            ("jsmixed", self.sub("first-project/index.html", 'href="../releases/"', 'href=" Java&#10;Script:alert(1)"'), "javascript: links"),
            ("ftp", self.sub("first-project/index.html", 'href="../releases/"', 'href="ftp://example.org/x"'), "scheme"),
            ("onclick", self.sub("first-project/index.html", "<article>", '<article onclick="x()">'), "event handler"),
            ("inline", self.sub("first-project/index.html", "<article>", "<article><script>alert(1)</script>"), "script that is not JSON-LD"),
            ("iframe", self.sub("first-project/index.html", "<article>", '<article><iframe src="https://evil.example/"></iframe>'), "<iframe> is not allowed"),
            ("noindex", self.sub("first-project/index.html", "</head>", '<meta name="robots" content="noindex"></head>'), "noindex"),
            ("graph", self.sub("first-project/index.html", '"@graph":[', '"@graph":[7,"x",null,'), "not an object"),
            ("graphstr", self.sub("first-project/index.html", '"@graph":[', '"@graph":"x","y":['), "@graph"),
            ("website", self.sub("index.html", '"@type":"WebSite"', '"@type":"Thing"'), "and WebSite JSON-LD"),
            ("shown", self.sub("reference/set-up/index.html", '<time datetime="%s">' % RELEASE_DATE, '<time datetime="2000-01-01">'), "is not shown on the page"),
            ("sitemap", self.sub("sitemap.xml", "<loc>https://docs.example.org/qargi/first-project/</loc>", "<loc>https://docs.example.org/qargi/gone/</loc>"), "is not listed"),
            ("lastmod", self.sub("sitemap.xml", "<lastmod>%s</lastmod>" % RELEASE_DATE, "<lastmod>tomorrow</lastmod>"), "not YYYY-MM-DD"),
            ("robots", self.sub("robots.txt", "Sitemap:", "Nothing:"), "no Sitemap line"),
            ("noindex404", self.sub("404.html", '<meta name="robots" content="noindex">', ""), "must be noindex"),
            ("xml", self.sub("sitemap.xml", "</urlset>", ""), "not well-formed"),
            ("nosidebar", self.sub("first-project/index.html", 'id="sidebar"', 'id="side"'), "no sidebar"),
            ("twocurrent", self.sub("first-project/index.html", '<li><a href="../">Home</a></li>', '<li><a href="../" aria-current="page">Home</a></li>'), 'exactly one link with aria-current="page", has 2'),
            ("nocurrent", self.sub("first-project/index.html", ' aria-current="page">First project</a>', '>First project</a>'), 'exactly one link with aria-current="page", has 0'),
            ("sidebar404", self.sub("404.html", '<div class="layout solo">', '<div class="layout solo"><div class="sidebar" id="sidebar"></div>'), "the 404 page has no sidebar"),
            ("script404", self.sub("404.html", "</head>", '<script src="assets/search.js" defer></script></head>'), "the 404 page has no sidebar and no script"),
            ("noscript", self.sub("first-project/index.html", '<script src="../assets/search.js" defer></script>', ""), "no search script"),
            ("foreignscript", self.sub("first-project/index.html", '<script src="../assets/search.js" defer></script>', '<script src="https://evil.example/x.js" defer></script>'), "script that is not JSON-LD or the search script"),
            ("asyncscript", self.sub("first-project/index.html", '<script src="../assets/search.js" defer>', '<script src="../assets/search.js" async onload="x">'), "script that is not JSON-LD or the search script"),
            ("inlinejs", self.sub("first-project/index.html", '<script src="../assets/search.js" defer></script>', '<script src="../assets/search.js" defer>alert(1)</script>'), "an inline script"),
            ("nojs", lambda d: os.remove(os.path.join(d, "assets", "search.js")), "assets/search.js: missing"),
            ("noindexfile", lambda d: os.remove(os.path.join(d, "assets", "search-index.json")), "assets/search-index.json: missing"),
            ("badindex", lambda d: spit(os.path.join(d, "assets", "search-index.json"), "{not json"), "search-index.json: not valid JSON"),
            ("bigindex", lambda d: spit(os.path.join(d, "assets", "search-index.json"), " " * (S.INDEX_MAX_BYTES + 1)), "larger than"),
            ("shapeindex", lambda d: spit(os.path.join(d, "assets", "search-index.json"), '{"version":1,"entries":[{"t":1}]}'), "entry 0 needs the text fields"),
            ("pageless", self.drop_entry("first-project/"), "no entry for the page first-project/index.html"),
            ("deadentry", self.sub("assets/search-index.json", '"p":"first-project/"', '"p":"gone/"'), "points at /gone/, which is not a page"),
            ("deadanchor", self.sub("assets/search-index.json", '"p":"first-project/#add-a-member"', '"p":"first-project/#nope"'), "has no element with id 'nope'"),
        ]
        for name, edit, frag in cases:
            rc, out = self.broken(name, edit)
            self.assertEqual(rc, 1, "%s: %s" % (name, out))
            self.assertIn(frag, out, name)

    def test_a_missing_file_is_found(self):
        def edit(d):
            os.remove(os.path.join(d, ".nojekyll"))
            os.remove(os.path.join(d, "robots.txt"))
        rc, out = self.broken("missing", edit)
        self.assertEqual(rc, 1)
        self.assertIn(".nojekyll: missing", out)
        self.assertIn("robots.txt: missing", out)

    def test_a_symlink_in_the_output_is_found(self):
        def edit(d):
            os.symlink("/etc/hostname", os.path.join(d, "link.txt"))
        rc, out = self.broken("symlink", edit)
        self.assertEqual(rc, 1)
        self.assertIn("a symbolic link", out)

    def test_not_a_directory_is_a_refusal(self):
        rc, out, err = run("check-output", os.path.join(self.tmp, "nope"))
        self.assertEqual(rc, 2)


class RenderCheck(unittest.TestCase):
    """What a reader sees: the built pages against their sources, and no Markdown marks left in their text."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        shutil.copytree(FIX, os.path.join(cls.tmp, "fix"))
        cls.pages = os.path.join(cls.tmp, "fix", "pages")
        cls.good = os.path.join(cls.tmp, "good")
        rc, out, err = build(cls.good, cls.pages)
        assert rc == 0, out + err

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, True)

    def check(self, name, edit, *extra):
        d = os.path.join(self.tmp, name)
        shutil.copytree(self.good, d)
        edit(d)
        rc, out, err = run("check-output", d, "--pages", self.pages, *extra)
        return rc, out

    def sub(self, rel, old, new):
        def edit(d):
            p = os.path.join(d, rel)
            t = slurp(p)
            assert old in t, (rel, old)
            spit(p, t.replace(old, new, 1))
        return edit

    def cut_after(self, rel, marker, tail):
        """What Kramdown makes of a line that starts with a tag: the page up to the line, the rest as escaped Markdown text."""
        def edit(d):
            p = os.path.join(d, rel)
            t = slurp(p)
            k = t.index(marker)
            spit(p, t[:k] + "<p>" + tail + "</p></article></main></div></body></html>\n")
        return edit

    def test_the_built_pages_match_their_sources(self):
        rc, out = self.check("clean", lambda d: None)
        self.assertEqual(rc, 0, out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_the_marks_check_needs_no_source(self):
        d = os.path.join(self.tmp, "nosrc")
        shutil.copytree(self.good, d)
        self.sub("first-project/index.html", "<article>", "<article><p>a `tick`</p>")(d)
        rc, out, _ = run("check-output", d)
        self.assertEqual(rc, 1, out)
        self.assertIn("first-project/index.html:", out)
        self.assertIn("holds a backtick", out)

    def test_a_page_cut_short_is_found_by_its_headings_code_blocks_and_tables(self):
        rc, out = self.check("cut", self.cut_after("first-project/index.html", '<h2 id="add-a-member">', "plain text"))
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"error: first-project\.md:20: the heading 'Add a member' is not in the built page")
        self.assertIn("a line that starts with <", out)
        self.assertIn("the source has 2 fenced code block(s), the built page 1 pre element(s)", out)
        self.assertIn("the source has 1 table(s), the built page 0 table element(s)", out)

    def test_the_marks_of_unrendered_markdown_are_found(self):
        cases = [
            ("tick", "a `tick` here", "holds a backtick"),
            ("bold", "a **bold** here", "holds ** "),
            ("link", "a [text](https://example.org/) here", "holds ]("),
            ("tilde", "~~~", "holds a ~~~ fence mark"),
            ("fence", "```bash", "holds a backtick"),
            ("head", "text\n## A heading", "starts with '## A heading'"),
            ("row", "text\n| a | b |", "starts with '| a | b |'"),
        ]
        for name, text, frag in cases:
            rc, out = self.check(name, self.sub("first-project/index.html", "<article>", "<article><p>%s</p>" % text))
            self.assertEqual(rc, 1, name + out)
            self.assertIn(frag, out, name)

    def test_code_and_the_heading_anchor_may_hold_the_marks(self):
        rc, out = self.check("incode", self.sub("first-project/index.html", "<article>",
                             "<article><p>use <code>`x` **y** [a](b) # not a heading</code></p><pre><code>```\n| a |\n# c\n</code></pre>"))
        self.assertEqual(rc, 1, out)                       # the added pre element is one more than the source has
        self.assertIn("3 pre element(s)", out)
        self.assertNotIn("holds", out)
        self.assertNotIn("starts with", out)

    def test_the_command_reference_may_hold_a_backtick_but_no_other_mark(self):
        rc, out = self.check("ref", self.sub("reference/set-up/index.html", "<article>", "<article><p>an `x` quote</p>"))
        self.assertEqual(rc, 0, out)
        rc, out = self.check("ref2", self.sub("reference/set-up/index.html", "<article>", "<article><p>**x**</p>"))
        self.assertEqual(rc, 1, out)

    def test_a_missing_built_page_is_found(self):
        def edit(d):
            shutil.rmtree(os.path.join(d, "first-project"))
        rc, out = self.check("gone", edit)
        self.assertEqual(rc, 1, out)
        self.assertIn("first-project.md: the page source has no built page first-project/index.html", out)

    def test_headings_are_compared_in_order_and_at_levels_two_and_three(self):
        doc = MD.convert("## A\n\n### B\n\n#### D\n\n## C\n", start_level=2)
        m = S.Main()
        m.feed('<main id="main"><h2 id="a">A <a class="anchor" href="#a">#</a></h2><h3 id="b">B</h3><h2 id="c">C</h2></main>')
        self.assertEqual(S.structure_problems(m, doc), [])
        m = S.Main()
        m.feed('<main id="main"><h2 id="c">C</h2><h3 id="b">B</h3><h2 id="a">A</h2></main>')
        got = S.structure_problems(m, doc)
        self.assertEqual(len(got), 1)
        self.assertIn("'B'", got[0][1])
        self.assertEqual(got[0][0], 3)
        m = S.Main()
        m.feed('<main id="main"><h2 id="a">A</h2><h2 id="b">B</h2><h2 id="c">C</h2></main>')      # B is an h2 here, not an h3
        self.assertIn("'B'", S.structure_problems(m, doc)[0][1])

    def test_text_outside_main_is_not_read(self):
        m = S.Main()
        m.feed('<body><nav>```</nav><main id="main"><p>fine <code>`x`</code></p></main><footer>**</footer></body>')
        self.assertEqual(S.residue_problems(m), [])

    def test_the_build_removes_a_site_that_does_not_show_its_pages(self):
        t = os.path.join(self.tmp, "regress")
        orig = S.render_page

        def broken(site, p):
            html = orig(site, p)
            k = html.find('<h2 id="add-a-member">')
            if p.path == "first-project/" and k >= 0:
                return html[:k] + "<p>## Add a member\n```bash\nx\n```</p></article></main></div></body></html>\n"
            return html
        S.render_page = broken
        self.addCleanup(setattr, S, "render_page", orig)
        buf = io.StringIO()
        show = S.Report.show
        S.Report.show = lambda rep, label, file=None: show(rep, label, buf)        # the report's output stream is fixed when it is defined
        self.addCleanup(setattr, S.Report, "show", show)
        with contextlib.redirect_stdout(buf):
            rc = S.main(["build", "--release", RELEASE, "--source", ROOT, *pg(self.pages), "--out", t])
        self.assertEqual(rc, 1, buf.getvalue())
        self.assertIn("error: first-project.md:20: the heading 'Add a member' is not in the built page", buf.getvalue())
        self.assertFalse(os.path.exists(t))


class Diff(unittest.TestCase):
    def test_diff_lists_changes_and_the_pages_that_still_name_them(self):
        t = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, t, True)
        new = os.path.join(t, "new")
        shutil.copytree(LIB, os.path.join(new, "lib"), ignore=shutil.ignore_patterns("__pycache__"))
        p = os.path.join(new, "lib", "commands.py")
        text = slurp(p)
        self.assertIn('"template": verb("Print an answers file with defaults"', text)
        text = text.replace('"template": verb("Print an answers file with defaults"', '"scaffold": verb("Print a scaffold with defaults"')
        text = text.replace('opt("--force", "replace stored answers")', 'opt("--overwrite", "replace stored answers")', 1)
        spit(p, text)
        rc, out, err = run("diff", "0.2.0", "0.3.0", "--source-old", ROOT, "--source-new", new)
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("removed: qargi project template", out)
        self.assertIn("added: qargi project scaffold", out)
        self.assertIn("option removed: qargi project init --force", out)
        self.assertIn("option added: qargi project init --overwrite", out)
        rc, out, err = run("diff", "0.2.0", "0.3.0", "--source-old", ROOT, "--source-new", new, "--pages", PAGES)
        self.assertEqual(rc, 1, out)
        self.assertIn("blocking: first-project.md:14: qargi project has no verb 'template'", out)
        rc, out, err = run("diff", "0.2.0", "0.2.0", "--source-old", ROOT, "--source-new", ROOT, "--pages", PAGES)
        self.assertEqual(rc, 0, out)
        self.assertIn("  none", out)


class Helpers(unittest.TestCase):
    def test_relative_links(self):
        f = S.rel_link
        self.assertEqual(f("", "install/"), "install/")
        self.assertEqual(f("", ""), "./")
        self.assertEqual(f("a/b/", ""), "../../")
        self.assertEqual(f("a/b/", "a/"), "../")
        self.assertEqual(f("a/b/", "c/#x"), "../../c/#x")
        self.assertEqual(f("a/", "assets/site.css"), "../assets/site.css")
        self.assertEqual(f("a/", "a/#top"), "./#top")

    def test_json_ld_cannot_close_the_script(self):
        s = S.json_ld({"a": "</script><b>&"})
        self.assertNotIn("<", s)
        self.assertNotIn(">", s)
        self.assertEqual(json.loads(s)["a"], "</script><b>&")


if __name__ == "__main__":
    unittest.main(verbosity=1)
