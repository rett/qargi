#!/usr/bin/env python3
"""Every shipped SKILL.md starts with a frontmatter block that a YAML reader accepts: a `name:` and a `description:` whose value is quoted when it holds ": " or " #"
(an unquoted one is a mapping error for a strict reader, which a cloud skill render is). The check reads only the stdlib: it parses the flat `key: value` lines the
shipped skills use."""
import glob, json, os, sys, unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import hermetic  # noqa: F401  (first: scrubs the caller's environment)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def frontmatter(path):
    lines = open(path, encoding="utf-8").read().split("\n")
    assert lines[0] == "---", path
    end = lines.index("---", 1)
    return lines[1:end]


class Frontmatter(unittest.TestCase):
    def test_every_skill_has_a_frontmatter_a_strict_reader_accepts(self):
        files = sorted(glob.glob(os.path.join(ROOT, "packs", "skills", "*", "SKILL.md")) + glob.glob(os.path.join(ROOT, "skills", "*", "SKILL.md")))
        self.assertTrue(files)
        for f in files:
            keys = {}
            for line in frontmatter(f):
                k, _, v = line.partition(": ")
                self.assertTrue(k and (k.replace("-", "").replace("_", "").isalnum()) or line.startswith((" ", "-")), "%s: a line that is not key: value: %r" % (f, line))
                keys[k] = v
                if v[:1] in "\"'":
                    if v[0] == '"':
                        self.assertEqual(type(json.loads(v)), str, "%s: %s is not a YAML double-quoted string" % (f, k))
                    continue
                self.assertNotIn(": ", v, "%s: the unquoted %s holds ': ' (quote it)" % (f, k))
                self.assertNotIn(" #", v, "%s: the unquoted %s holds ' #' (quote it)" % (f, k))
            self.assertIn("name", keys, f)
            self.assertIn("description", keys, f)
            self.assertEqual(keys["name"], os.path.basename(os.path.dirname(f)), f)


if __name__ == "__main__":
    unittest.main()
