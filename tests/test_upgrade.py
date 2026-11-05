#!/usr/bin/env python3
"""qargi upgrade against a local origin and a stub install.sh. Offline; temporary state. Run: python3 tests/test_upgrade.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
INSTALL = '#!/bin/sh\necho "$@" >> "$QARGI_TEST_MARK"\n'


def git(cwd, *a):
    return subprocess.run(GIT + ["-C", cwd, *a], capture_output=True, text=True, check=True).stdout.strip()


class T(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.origin, self.tool, self.conf, self.state = (os.path.join(self.t, x) for x in ("origin", "tool", "c", "s"))
        self.mark = os.path.join(self.t, "mark")
        for d in (self.conf, self.state):
            os.makedirs(d)
        subprocess.run(["git", "init", "-q", "-b", "develop", self.origin], check=True)
        self.commit("0.1.0", "first")
        subprocess.run(["git", "clone", "-q", self.origin, self.tool], check=True)
        with open(os.path.join(self.conf, "install.json"), "w") as f:
            json.dump({"tool_root": self.tool}, f)
        with open(os.path.join(self.conf, "agents.json"), "w") as f:
            json.dump({"schema": 2, "projects": {"alpha": {"forge": {}}, "beta": {"forge": {}, "scribe": {}}}}, f)
        self.env = dict(os.environ, HOME=self.t, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_SUDO="", QARGI_TEST_MARK=self.mark)

    def commit(self, version, msg):
        with open(os.path.join(self.origin, "VERSION"), "w") as f:
            f.write(version + "\n")
        with open(os.path.join(self.origin, "install.sh"), "w") as f:
            f.write(INSTALL)
        os.chmod(os.path.join(self.origin, "install.sh"), 0o755)
        git(self.origin, "add", "-A")
        git(self.origin, "commit", "-q", "-m", msg)

    def q(self, *a):
        return subprocess.run([BIN, "upgrade", *a], capture_output=True, text=True, env=self.env, stdin=subprocess.DEVNULL)

    def head(self):
        return git(self.tool, "rev-parse", "HEAD")

    def test_up_to_date(self):
        r = self.q("--branch", "develop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already at", r.stdout)

    def test_plan_then_apply(self):
        before = self.head()
        self.commit("0.2.0", "second change")
        r = self.q("--branch", "develop")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("second change", r.stdout)
        self.assertIn("0.1.0 -> 0.2.0", r.stdout)
        self.assertEqual(self.head(), before)                         # a plan changes the checkout's files not at all
        self.assertFalse(os.path.exists(self.mark))
        tok = [l.split()[2] for l in r.stdout.splitlines() if l.startswith("plan token")][0]
        self.assertNotEqual(self.q("--branch", "develop", "--plan", "000000000000", "--approved", "x").returncode, 0)
        self.assertEqual(self.head(), before)
        r = self.q("--branch", "develop", "--plan", tok, "--approved", "go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.head(), git(self.origin, "rev-parse", "HEAD"))
        self.assertIn("--user", open(self.mark).read())              # install.sh --user ran
        for cmd in ("qargi agent refresh forge --project alpha", "qargi agent refresh forge --project beta", "qargi agent refresh scribe --project beta"):
            self.assertIn(cmd, r.stdout)          # a name two projects hold is refreshed once for each

    def old_home(self, body):
        """A hermetic home (QARGI_HOME, nothing else named) whose config holds the installed-tool record and an agents.json of the given text."""
        home = os.path.join(self.t, "h")
        conf = os.path.join(home, "config")
        os.makedirs(conf)
        with open(os.path.join(conf, "install.json"), "w") as f:
            json.dump({"tool_root": self.tool}, f)
        path = os.path.join(conf, "agents.json")
        with open(path, "w") as f:
            f.write(body)
        self.env = {k: v for k, v in dict(os.environ, HOME=self.t, QARGI_HOME=home, QARGI_SUDO="", QARGI_TEST_MARK=self.mark).items()
                    if k not in ("QARGI_CONF", "QARGI_STATE")}
        return path

    def test_old_members_file_is_warned_about(self):
        """An agents.json of an earlier shape makes every agent verb refuse; the plan says so and says what to do, and changes nothing."""
        old = json.dumps({"worker": {"abilities": ["build"], "file": "/x/worker.md", "project": None, "seq": 1}})
        path = self.old_home(old)
        self.commit("0.2.0", "second change")
        before = self.head()
        r = self.q("--branch", "develop")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout + r.stderr
        self.assertIn("agents.json", out)
        self.assertIn(path, out)
        self.assertIn("every agent verb refuses", out)
        self.assertIn("agent add NAME --project P", out)
        self.assertIn("plan token", r.stdout)                         # the plan is still the plan
        self.assertEqual(self.head(), before)
        self.assertEqual(open(path).read(), old)                      # the file is neither moved nor rewritten
        tok = [l.split()[2] for l in r.stdout.splitlines() if l.startswith("plan token")][0]
        r = self.q("--branch", "develop", "--plan", tok, "--approved", "go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("every agent verb refuses", r.stdout + r.stderr)  # and after the upgrade, where the refresh list would have been
        self.assertNotIn("qargi agent refresh", r.stdout)
        self.assertEqual(open(path).read(), old)

    def test_current_members_file_is_not_warned_about(self):
        for body in ('{"schema": 2, "projects": {}}', "{}", json.dumps({"schema": 2, "projects": {"alpha": {"forge": {}}}})):
            self.old_home(body)
            self.commit("0.%d.0" % (len(body) + 2), "next " + body)
            r = self.q("--branch", "develop")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("every agent verb refuses", r.stdout + r.stderr, body)
            subprocess.run(["rm", "-rf", os.path.join(self.t, "h")], check=True)

    def test_default_branch_is_the_current_one(self):
        self.commit("0.2.0", "next")
        self.assertIn("develop", self.q().stdout)

    def test_not_a_fast_forward_is_refused(self):
        self.commit("0.2.0", "second")
        git(self.tool, "fetch", "-q", "origin")
        git(self.tool, "merge", "-q", "--ff-only", "origin/develop")
        git(self.origin, "reset", "-q", "--hard", "HEAD~1")
        self.commit("0.3.0", "rewritten")                            # origin no longer contains what is installed
        r = self.q("--branch", "develop")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a fast-forward", r.stderr)

    def test_tag_is_checked_out_detached(self):
        git(self.origin, "tag", "v0.1.0")
        self.commit("0.2.0", "second")
        tok = [l.split()[2] for l in self.q("--tag", "v0.1.0").stdout.splitlines() if l.startswith("plan token")]
        self.assertEqual(tok, [])                                     # already at the tag's commit? no: the tool is at v0.1.0
        git(self.tool, "fetch", "-q", "origin")
        git(self.tool, "merge", "-q", "--ff-only", "origin/develop")  # now ahead of the tag
        tok = [l.split()[2] for l in self.q("--tag", "v0.1.0").stdout.splitlines() if l.startswith("plan token")][0]
        r = self.q("--tag", "v0.1.0", "--plan", tok, "--approved", "back to the tag")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(git(self.tool, "branch", "--show-current"), "")
        self.assertEqual(open(os.path.join(self.tool, "VERSION")).read().strip(), "0.1.0")

    def test_bad_names_and_unknown_refs(self):
        self.assertNotEqual(self.q("--branch", "--upload-pack=x").returncode, 0)
        self.assertNotEqual(self.q("--branch", "a b").returncode, 0)
        self.assertNotEqual(self.q("--branch", "nosuch").returncode, 0)
        self.assertNotEqual(self.q("--branch", "develop", "--tag", "v1").returncode, 0)

    def test_no_install_record(self):
        os.remove(os.path.join(self.conf, "install.json"))
        r = self.q("--branch", "develop")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("no installed tool", r.stderr)

    def test_guard_refuses_members(self):
        for cmd in ("qargi upgrade --branch develop", "bash lib/upgrade.sh --tag v1"):
            r = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.t}),
                               capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 2, cmd + r.stderr)


if __name__ == "__main__":
    unittest.main()
