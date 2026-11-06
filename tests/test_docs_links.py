#!/usr/bin/env python3
"""The documentation tree: README.md is short and has a Documentation table, one row per docs/<topic>/README.md, and every
relative link of README.md, CONTRIBUTING.md and docs/**/*.md points at a file or directory that exists (a link with a #fragment, at a
heading of the Markdown file it names). Links in code fences and code spans are not links; http(s) and mailto addresses are not checked.
Offline. Run: python3 tests/test_docs_links.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, os, re, sys, tempfile, unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib"))
import commands as C  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_MAX_LINES = 100        # README.md is a front page: the detail lives in docs/

LINK = re.compile(r"(?<!\!)\[(?:[^\]\[]|\[[^\]]*\])*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
FENCE = re.compile(r"^\s*(```+|~~~+)")
CODE_SPAN = re.compile(r"(`+)(?:(?!\1).)+?\1")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
EXTERNAL = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")     # https:, mailto:, ...


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def prose(text):
    """(line number, line) of the lines outside code fences, code spans blanked."""
    out, fence = [], None
    for n, line in enumerate(text.split("\n"), 1):
        m = FENCE.match(line)
        if m:
            if fence is None:
                fence = m.group(1)[0]
            elif m.group(1)[0] == fence:
                fence = None
            continue
        if fence is None:
            out.append((n, CODE_SPAN.sub(lambda s: " " * len(s.group(0)), line)))
    return out


def slug(title):
    """The anchor a Markdown renderer makes of a heading: lower case, no punctuation but - and _, spaces to hyphens."""
    title = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", title).replace("`", "")
    return re.sub(r"[^\w\- ]", "", title.lower()).strip().replace(" ", "-")


def anchors(path):
    seen, out = {}, set()
    for _, line in prose(read(path)):
        m = HEADING.match(line)
        if m:
            s = slug(m.group(2))
            k = seen.get(s, 0)
            seen[s] = k + 1
            out.add(s if k == 0 else "%s-%d" % (s, k))
    return out


def links(path):
    """(line number, target) of every link of a Markdown file."""
    return [(n, m.group(1)) for n, line in prose(read(path)) for m in LINK.finditer(line)]


def problems(path, root):
    """What is wrong with the relative links of one file, as 'file:line: text' strings."""
    bad, here = [], os.path.dirname(path)
    rel = os.path.relpath(path, root)
    for n, target in links(path):
        if EXTERNAL.match(target):
            continue
        base, _, frag = target.partition("#")
        dest = path if not base else os.path.normpath(os.path.join(here, base))
        where = "%s:%d: %s" % (rel, n, target)
        if base.startswith("/"):
            bad.append(where + " (an absolute path)")
        elif os.path.commonpath([os.path.realpath(root), os.path.realpath(dest)]) != os.path.realpath(root):
            bad.append(where + " (leaves the repository)")
        elif not os.path.exists(dest):
            bad.append(where + " (no such file)")
        elif frag and dest.endswith(".md") and os.path.isfile(dest) and frag not in anchors(dest):
            bad.append(where + " (no such heading)")
    return bad


def documents(root):
    return [p for p in [os.path.join(root, "README.md"), os.path.join(root, "CONTRIBUTING.md")] if os.path.isfile(p)] + \
        sorted(glob.glob(os.path.join(root, "docs", "**", "*.md"), recursive=True))


def table_rows(readme):
    """The rows of the table under '## Documentation' of README.md: [(topic cell, contents cell)], header included."""
    rows, inside, table = [], False, False
    for line in read(readme).split("\n"):
        if re.match(r"^## ", line):
            inside = line.strip() == "## Documentation"
            table = False
        elif inside and line.startswith("|"):
            table = True
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
        elif inside and table:
            break
    return rows


class DocsTree(unittest.TestCase):
    def test_every_relative_link_resolves(self):
        docs = documents(ROOT)
        self.assertTrue(any(p.startswith(os.path.join(ROOT, "docs")) for p in docs), "no docs/ pages")
        bad = [b for p in docs for b in problems(p, ROOT)]
        self.assertEqual(bad, [], "broken links:\n" + "\n".join(bad))

    def test_readme_is_a_front_page(self):
        n = len(read(os.path.join(ROOT, "README.md")).rstrip("\n").split("\n"))
        self.assertLessEqual(n, README_MAX_LINES, "README.md has %d lines; the detail belongs in docs/" % n)
        self.assertIn("https://qargi.rettware.com/", read(os.path.join(ROOT, "README.md")))

    def test_documentation_table(self):
        rows = table_rows(os.path.join(ROOT, "README.md"))
        self.assertTrue(rows, "README.md has no table under '## Documentation'")
        self.assertEqual(rows[0], ["Topic", "Contents"])
        self.assertTrue(all(set(c) <= set("-: ") for c in rows[1]) if len(rows) > 1 else False, "no separator row")
        listed = []
        for topic, contents in rows[2:]:
            self.assertTrue(contents, "the row of %s has no contents" % topic)
            m = re.fullmatch(r"\[[^\]]+\]\((docs/[a-z0-9-]+/README\.md)\)", topic)
            self.assertIsNotNone(m, "the topic cell is a link to docs/<topic>/README.md: %s" % topic)
            self.assertTrue(os.path.isfile(os.path.join(ROOT, m.group(1))), "%s does not exist" % m.group(1))
            listed.append(m.group(1))
        self.assertEqual(len(listed), len(set(listed)), "a topic is listed twice")
        on_disk = sorted(os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, "docs", "*", "README.md")))
        self.assertEqual(sorted(listed), on_disk, "the Documentation table and the docs/<topic>/README.md files differ")


    def test_quick_start_names_real_commands(self):
        """Every `qargi COMMAND VERB` line of a code block of README.md is a command and verb of lib/commands.py."""
        seen, fence = [], False
        for line in read(os.path.join(ROOT, "README.md")).split("\n"):
            if FENCE.match(line):
                fence = not fence
            elif fence and line.startswith("qargi "):
                seen.append(line.split("#")[0].split())
        self.assertTrue(seen, "no qargi command in a code block of README.md")
        for words in seen:
            self.assertTrue(words[1] in C.COMMANDS, "not a command: " + " ".join(words))
            verbs = C.COMMANDS[words[1]].get("verbs")
            if isinstance(verbs, dict):
                self.assertTrue(words[2] in verbs, "not a verb: " + " ".join(words))


class Checker(unittest.TestCase):
    """The checks catch what they claim to."""

    def tree(self, files):
        d = tempfile.mkdtemp(dir=tempfile.gettempdir())
        for rel, text in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "w") as f:
                f.write(text)
        return d

    def test_resolves_and_reports(self):
        d = self.tree({"README.md": "# T\n\n[ok](docs/a/README.md) [dir](docs/a) [anchor](docs/a/README.md#second-part) [self](#t)\n"
                                    "[gone](docs/b.md) [bad](docs/a/README.md#nope) [up](../x.md) [web](https://x.example/y)\n"
                                    "`[code](nowhere.md)`\n```\n[fence](nowhere.md)\n```\n",
                       "docs/a/README.md": "# A\n\n## Second part\n\n## Second part\n"})
        bad = problems(os.path.join(d, "README.md"), d)
        self.assertEqual([b.split(" ", 1)[0] for b in bad], ["README.md:4:", "README.md:4:", "README.md:4:"], bad)
        self.assertEqual([b.split("(", 1)[1] for b in bad], ["no such file)", "no such heading)", "leaves the repository)"])

    def test_relative_to_the_file(self):
        d = self.tree({"docs/a/README.md": "[up](../b/README.md#b) [wrong](b/README.md)\n", "docs/b/README.md": "# B\n"})
        bad = problems(os.path.join(d, "docs/a/README.md"), d)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("b/README.md (no such file)", bad[0])

    def test_table(self):
        d = self.tree({"README.md": "# T\n\n## Documentation\n\n| Topic | Contents |\n|---|---|\n| [A](docs/a/README.md) | x |\n\ntext\n"})
        self.assertEqual(table_rows(os.path.join(d, "README.md")), [["Topic", "Contents"], ["---", "---"], ["[A](docs/a/README.md)", "x"]])

    def test_slug(self):
        self.assertEqual(slug("Cloud (ant) profiles per project"), "cloud-ant-profiles-per-project")
        self.assertEqual(slug("Help, manual page and completion"), "help-manual-page-and-completion")
        self.assertEqual(slug("The `qargi` verb [x](y.md)"), "the-qargi-verb-x")


if __name__ == "__main__":
    unittest.main()
