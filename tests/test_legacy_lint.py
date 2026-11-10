#!/usr/bin/env python3
"""No code for earlier versions (qargi is alpha: there is no backwards compatibility to keep). lib/ may not contain the phrases
"older record", "migrat" and "earlier version" (any case) except where tests/legacy-allowlist.txt names the file and the phrase,
with a comment that says why. The allowlist only shrinks: a line whose file no longer holds its phrase fails, so it is deleted
when the code is. Offline. Run: python3 tests/test_legacy_lint.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import os, re, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PHRASES = ("older record", "migrat", "earlier version")
ALLOWLIST = os.path.join(ROOT, "tests", "legacy-allowlist.txt")


def hits(lib_dir, root):
    """-> {(path relative to root, phrase)} for every phrase found in a text file under lib_dir."""
    found = {}
    for d, dirs, files in os.walk(lib_dir):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__")
        for name in sorted(files):
            path = os.path.join(d, name)
            if name.endswith((".pyc", ".pyo")) or os.path.islink(path):
                continue
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read().lower()
            for ph in PHRASES:
                n = text.count(ph)
                if n:
                    found[(os.path.relpath(path, root), ph)] = n
    return found


def allowed(path):
    """-> ({(file, phrase)}, [problems]) from the allowlist: `FILE: PHRASE  # reason`, a comment on every line."""
    out, bad = set(), []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            m = re.fullmatch(r"(\S+): (.+?)\s+# (\S.*)", line)
            if not m:
                bad.append("line %d is not `FILE: PHRASE  # reason`: %s" % (n, line))
            elif m.group(2) not in PHRASES:
                bad.append("line %d: %r is not one of the phrases %s" % (n, m.group(2), PHRASES))
            else:
                out.add((m.group(1), m.group(2)))
    return out, bad


class LegacyLint(unittest.TestCase):
    def test_lib_holds_no_phrase_of_an_earlier_version_but_the_allowlisted(self):
        ok, bad = allowed(ALLOWLIST)
        self.assertEqual(bad, [])
        found = hits(os.path.join(ROOT, "lib"), ROOT)
        extra = sorted("%s: %s (x%d)" % (f, ph, n) for (f, ph), n in found.items() if (f, ph) not in ok)
        self.assertEqual(extra, [], "code for an earlier version: delete it (qargi keeps no backwards compatibility), or, for a rule of the "
                                    "current format that has to say it, add `FILE: PHRASE  # reason` to tests/legacy-allowlist.txt")

    def test_the_allowlist_only_shrinks(self):
        ok, _ = allowed(ALLOWLIST)
        found = hits(os.path.join(ROOT, "lib"), ROOT)
        stale = sorted("%s: %s" % k for k in ok if k not in found)
        self.assertEqual(stale, [], "these allowlist lines no longer match anything: delete them from tests/legacy-allowlist.txt")

    def test_the_lint_finds_a_phrase_and_the_allowlist_reads_its_lines(self):
        with tempfile.TemporaryDirectory() as t:
            os.makedirs(os.path.join(t, "lib"))
            with open(os.path.join(t, "lib", "a.sh"), "w") as f:
                f.write("# an Older Record has none\n# a MIGRATION\n")
            with open(os.path.join(t, "list.txt"), "w") as f:
                f.write("# comment\n\nlib/a.sh: older record  # reason\nlib/b.sh: migrat\nlib/c.sh: nothing  # reason\n")
            self.assertEqual(set(hits(os.path.join(t, "lib"), t)), {("lib/a.sh", "older record"), ("lib/a.sh", "migrat")})
            ok, bad = allowed(os.path.join(t, "list.txt"))
            self.assertEqual(ok, {("lib/a.sh", "older record")})
            self.assertEqual(len(bad), 2)


if __name__ == "__main__":
    unittest.main(verbosity=1)
