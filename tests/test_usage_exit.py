#!/usr/bin/env python3
"""A usage error ends with exit 2, a refusal with exit 1 (the manual page promises both). In the shell scripts a usage error is
`usage_die` (lib/lib.sh); `die` is exit 1. This lints lib/*.sh: no plain `die` may carry a usage line (a message that begins with
`usage`), whatever its quotes. Offline. Run: python3 tests/test_usage_exit.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, os, re, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# `die` as a command word (not usage_die, not a name that ends in die) followed by a message that begins with "usage"
PLAIN_DIE_USAGE = re.compile(r"(?<![A-Za-z0-9_])die\s+[\"']?usage")


def offenders(text):
    """-> [(line number, line)] of the lines of text that hold a plain die with a usage line."""
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1)
            if not line.lstrip().startswith("#") and PLAIN_DIE_USAGE.search(line)]


class UsageLint(unittest.TestCase):
    def test_the_pattern_finds_a_plain_die_with_a_usage_line_and_nothing_else(self):
        for bad in ('die "usage: x"', "  [ -n \"$a\" ] || die 'usage: x'", "a && die usage", "{ die \"usage takes no --advise\"; }"):
            self.assertTrue(offenders(bad), bad)
        for good in ('usage_die "usage: x"', 'die "no usage here"', 'die "the usage of x"', '# die "usage: x"', 'mydie "usage: x"'):
            self.assertEqual(offenders(good), [], good)

    def test_no_shell_script_ends_a_usage_line_with_a_plain_die(self):
        found = []
        for path in sorted(glob.glob(os.path.join(ROOT, "lib", "*.sh"))):
            with open(path, encoding="utf-8") as f:
                found += ["%s:%d: %s" % (os.path.relpath(path, ROOT), n, line) for n, line in offenders(f.read())]
        self.assertEqual(found, [], "a usage error is usage_die (exit 2), not die (exit 1)")


if __name__ == "__main__":
    unittest.main()
