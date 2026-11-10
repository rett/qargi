#!/usr/bin/env python3
"""A usage error ends with exit 2, a refusal with exit 1 (the manual page promises both). In the shell scripts a usage error is
`usage_die` (lib/lib.sh); `die` is exit 1. This lints lib/*.sh: no plain `die` may carry a usage line (a message that begins with
`usage`), whatever its quotes. Offline. Run: python3 tests/test_usage_exit.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, json, os, re, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QARGI = os.path.join(ROOT, "bin", "qargi")
# `die` as a command word (not usage_die, not a name that ends in die) followed by a message that begins with "usage"
PLAIN_DIE_USAGE = re.compile(r"(?<![A-Za-z0-9_])die\s+[\"']?usage")


def offenders(text):
    """-> [(line number, line)] of the lines of text that hold a plain die with a usage line."""
    return [(n, line.strip()) for n, line in enumerate(text.splitlines(), 1)
            if not line.lstrip().startswith("#") and PLAIN_DIE_USAGE.search(line)]


def qargi(*argv, **kw):
    p = subprocess.run([QARGI, *argv], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       universal_newlines=True, timeout=60, **kw)
    return p.returncode, p.stdout


# a stub ant for qargi instances init --location cloud: a deployment with a budget whose name has no letters or digits
ANT = r'''#!/bin/sh
case "$1 $2" in
  "auth status") exit 0;;
  "beta:deployments retrieve") echo '{"id":"dep_x","name":"***","archived_at":null,"budget":{"type":"limit"},"agent":{"id":"agent_x","version":1},"environment_id":"env_x"}';;
  "beta:agents retrieve") echo '{"id":"agent_x","version":1,"model":{"id":"m"}}';;
  *) echo '{}';;
esac
'''


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


class MissingArgument(unittest.TestCase):
    """An argument or an option the command needs and was not given is a usage error: exit 2 with the message."""

    def assertUsage(self, argv, text, **kw):
        rc, out = qargi(*argv, **kw)
        self.assertEqual(rc, 2, "%s -> %s" % (" ".join(argv), out))
        self.assertIn(text, out)

    def test_packs_load_names_the_project(self):
        with tempfile.TemporaryDirectory() as cwd:   # a directory no project is inferred from
            self.assertUsage(["packs", "load", "--role", "build"], "load: name the project with --project P", cwd=cwd)

    def test_skill_import_needs_a_name_when_the_source_has_none(self):
        with tempfile.TemporaryDirectory() as t:
            src = os.path.join(t, "src")
            os.mkdir(src)
            with open(os.path.join(src, "SKILL.md"), "w") as f:
                f.write("no front matter\n")
            self.assertUsage(["skill", "import", src, "--compatible", "any"], "cannot work out a valid name; pass --name")

    def test_instances_init_cloud_needs_a_name_when_the_deployment_gives_none(self):
        with tempfile.TemporaryDirectory() as t:
            os.mkdir(os.path.join(t, "bin"))
            with open(os.path.join(t, "bin", "ant"), "w") as f:
                f.write(ANT)
            os.chmod(os.path.join(t, "bin", "ant"), 0o755)
            env = dict(os.environ, PATH=os.path.join(t, "bin") + ":" + os.environ["PATH"])
            self.assertUsage(["instances", "init", "--location", "cloud", "--deployment", "dep_x", "--asked", "a test"],
                             "empty instance name; pass --name", env=env)


if __name__ == "__main__":
    unittest.main()
