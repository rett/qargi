#!/usr/bin/env python3
"""The documentation site generator: the Markdown converter (lib/site_md.py) and lib/site.py, offline.
Run: python3 tests/test_site.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import importlib.util
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

    def test_first_line_offsets_the_numbers(self):
        with self.assertRaises(MD.MdError) as cm:
            self.conv("## A\n\n<b>\n", first_line=10)
        self.assertEqual(cm.exception.line, 12)

    def test_heading_ids_are_unique_and_prefixed(self):
        d = self.conv("## Same\n\n### Same\n\n## Same\n", id_prefix="v1-")
        self.assertEqual([h[1] for h in d.headings], ["v1-same", "v1-same-2", "v1-same-3"])

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
        got = list(S.check_code(self.cmds, "span", "--asked REQUEST", 3))
        self.assertEqual(got, [])
        got = list(S.check_code(self.cmds, "span", "--nope", 3))
        self.assertEqual(got[0][0], 3)
        self.assertEqual(list(S.check_code(self.cmds, "fence:text", "qargi nonesuch", 1)), [])      # output blocks are not checked
        got = list(S.check_code(self.cmds, "fence:bash", "# qargi nonesuch\nqargi project \\\n  frob\nFOO=1 qargi nope", 10))
        self.assertEqual([g[0] for g in got], [12, 14])


class Check(unittest.TestCase):
    def test_clean_pages_pass(self):
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(PAGES))
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("0 error(s), 0 warning(s)", out)

    def test_bad_pages_are_reported_with_line_numbers(self):
        rc, out, err = run("check", "--release", RELEASE, "--source", ROOT, *pg(BAD))
        self.assertEqual(rc, 1, out + err)
        want = ["unsupported.md:7: raw HTML is not supported",
                "broken.md:20: contains the forbidden word 'hunter2'",
                "broken.md:11: qargi project has no verb 'frobnicate'",
                "broken.md:12: qargi agent add has no option --no-such-option",
                "broken.md:15: `qargi nonesuch run`: qargi has no command 'nonesuch'",
                "broken.md:15: no qargi command has the option --also-missing",
                "broken.md:19: link /no-such-page/: no such page",
                "broken.md:19: link /reference/set-up/#no-such-heading: page /reference/set-up/ has no heading with id 'no-such-heading'",
                "broken.md:19: link #nowhere: no heading with that id on this page"]
        for w in want:
            self.assertIn("error: " + w, out)
        self.assertNotIn("broken.md:10", out)      # the valid command on line 10 is not reported
        self.assertIn("9 error(s)", out)

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
        rc, out, err = run("check-output", self.out)
        self.assertEqual((rc, err), (0, ""), out)
        self.assertIn("0 error(s), 0 warning(s)", out)

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

    def test_no_javascript_and_no_external_requests(self):
        for dirpath, _, files in os.walk(self.out):
            for f in files:
                if f.endswith(".html") and f != "verify-acme.html":
                    t = slurp(os.path.join(dirpath, f))
                    self.assertNotRegex(t, r"<script(?![^>]*application/ld\+json)", f)
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
        self.assertIn('<meta name="color-scheme" content="dark light">', t)
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
        self.assertEqual(home["@type"], "SoftwareApplication")
        self.assertEqual(home["offers"]["price"], "0")
        self.assertEqual(home["softwareVersion"], RELEASE)
        self.assertEqual(home["author"], {"@type": "Organization", "name": "qargi"})
        self.assertEqual(home["license"], "https://opensource.org/licenses/MIT")
        self.assertNotIn("aggregateRating", home)
        g = self.ld("reference/set-up/index.html")["@graph"]
        art = [n for n in g if n["@type"] == "TechArticle"][0]
        self.assertEqual(art["headline"], "Reference: Set up")
        self.assertEqual(art["author"], {"@type": "Organization", "name": "qargi"})
        crumbs = [n for n in g if n["@type"] == "BreadcrumbList"][0]["itemListElement"]
        self.assertEqual([c["position"] for c in crumbs], [1, 2, 3])
        self.assertEqual(crumbs[0]["item"], "https://docs.example.org/qargi/")
        self.assertEqual(crumbs[1]["item"], "https://docs.example.org/qargi/reference/")
        self.assertEqual(self.ld("first-project/index.html")["@graph"][1]["itemListElement"][1]["name"], "Your first project")

    def test_sitemap_robots_and_404(self):
        root = ET.parse(os.path.join(self.out, "sitemap.xml")).getroot()
        ns = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
        urls = {u.find(ns + "loc").text: u for u in root}
        self.assertIn("https://docs.example.org/qargi/", urls)
        self.assertIn("https://docs.example.org/qargi/reference/set-up/", urls)
        self.assertNotIn("https://docs.example.org/qargi/404.html", urls)
        self.assertEqual(len(urls), 14)
        # the generated pages carry the release date; the hand pages (untracked or modified here) fall back to it too, never to the build time
        for loc, u in urls.items():
            self.assertEqual(u.find(ns + "lastmod").text, RELEASE_DATE, loc)
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
        self.assertEqual(html_.count("<script"), 1)         # only the JSON-LD
        self.assertNotIn("<script>alert", html_)
        self.assertIn("&lt;/title&gt;&lt;script&gt;", html_)
        m = re.search(r'<script type="application/ld\+json">(.*?)</script>', html_, re.S)
        self.assertNotIn("</", m.group(1))
        self.assertEqual(json.loads(m.group(1))["name"], "qargi")
        rc, out, _ = run("check-output", os.path.join(t, "o2"))
        self.assertEqual(rc, 0, out)


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
        lm = {u.find(ns + "loc").text: u.find(ns + "lastmod").text for u in root}
        self.assertEqual(lm["https://docs.example.org/qargi/first-project/"], "2026-03-02")
        self.assertEqual(lm["https://docs.example.org/qargi/"], RELEASE_DATE)        # fell back to the release date
        self.assertEqual(lm["https://docs.example.org/qargi/releases/"], RELEASE_DATE)
        ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', slurp(os.path.join(out, "first-project", "index.html")), re.S).group(1)
        art = json.loads(ld)["@graph"][0]
        self.assertEqual((art["dateModified"], art["datePublished"]), ("2026-03-02", "2026-01-15"))
        self.assertEqual(run("check-output", out)[0], 0)


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
            ("sitemap", self.sub("sitemap.xml", "<loc>https://docs.example.org/qargi/first-project/</loc>", "<loc>https://docs.example.org/qargi/gone/</loc>"), "is not listed"),
            ("lastmod", self.sub("sitemap.xml", "<lastmod>%s</lastmod>" % RELEASE_DATE, "<lastmod>tomorrow</lastmod>"), "not YYYY-MM-DD"),
            ("robots", self.sub("robots.txt", "Sitemap:", "Nothing:"), "no Sitemap line"),
            ("noindex", self.sub("404.html", '<meta name="robots" content="noindex">', ""), "must be noindex"),
            ("xml", self.sub("sitemap.xml", "</urlset>", ""), "not well-formed"),
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
