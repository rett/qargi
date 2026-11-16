#!/usr/bin/env python3
"""qargi upgrade against a local origin and a stub install.sh. Offline; temporary state. Run: python3 tests/test_upgrade.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
INSTALL = '#!/bin/sh\necho "$@" >> "$QARGI_TEST_MARK"\n'
sys.path.insert(0, os.path.join(ROOT, "lib"))
import install_record as IR  # noqa: E402


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
        self.runtime(self.conf, "claude-code")
        with open(os.path.join(self.conf, "agents.json"), "w") as f:
            json.dump({"schema": 2, "projects": {"alpha": {"forge": {}}, "beta": {"forge": {}, "scribe": {}}}}, f)
        self.env = dict(os.environ, HOME=self.t, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_SUDO="", QARGI_TEST_MARK=self.mark)

    def runtime(self, conf, name):
        """Record the lead skills of runtime NAME for the install in conf, as install.sh does (lib/install_record.py writes the manifest)."""
        root = os.path.join(self.t, "." + name, "skills")
        os.makedirs(os.path.join(conf, "install.d"), exist_ok=True)
        IR.write(os.path.join(conf, "install.d", "runtime-%s.manifest" % name), {"kind": "runtime", "name": name, "root": [root], "data": [], "slot": []},
                 [("L", os.path.join(root, "qargi-task"), os.path.join(self.tool, "skills", "qargi-task"))])
        return root

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
        self.assertEqual(self.marked(), "--user\n")                   # install.sh --user ran: it relinks every recorded runtime itself
        for cmd in ("qargi agent refresh forge --project alpha", "qargi agent refresh forge --project beta", "qargi agent refresh scribe --project beta"):
            self.assertIn(cmd, r.stdout)          # a name two projects hold is refreshed once for each

    def old_home(self, body):
        """A hermetic home (QARGI_HOME, nothing else named) whose config holds the installed-tool record and an agents.json of the given text."""
        home = os.path.join(self.t, "h")
        conf = os.path.join(home, "config")
        os.makedirs(conf)
        with open(os.path.join(conf, "install.json"), "w") as f:
            json.dump({"tool_root": self.tool}, f)
        self.runtime(conf, "claude-code")
        path = os.path.join(conf, "agents.json")
        with open(path, "w") as f:
            f.write(body)
        self.env = {k: v for k, v in dict(os.environ, HOME=self.t, QARGI_HOME=home, QARGI_SUDO="", QARGI_TEST_MARK=self.mark).items()
                    if k not in ("QARGI_CONF", "QARGI_STATE")}
        return path

    def test_upgrade_says_nothing_about_the_shape_of_the_members_file(self):
        """The plan and the apply neither read the shape of agents.json nor warn about it (no migration aid for an older shape), and leave the file alone."""
        old = json.dumps({"worker": {"abilities": ["build"], "file": "/x/worker.md", "project": None, "seq": 1}})
        for n, body in enumerate((old, '{"schema": 2, "projects": {}}', "{}")):
            path = self.old_home(body)
            self.commit("0.%d.0" % (n + 2), "next %d" % n)
            r = self.q("--branch", "develop")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("plan token", r.stdout)
            self.assertNotIn("agents.json", r.stdout + r.stderr, body)
            tok = [l.split()[2] for l in r.stdout.splitlines() if l.startswith("plan token")][0]
            r = self.q("--branch", "develop", "--plan", tok, "--approved", "go")
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertNotIn("agents.json", r.stdout + r.stderr, body)
            self.assertNotIn("every agent verb refuses", r.stdout + r.stderr, body)
            self.assertEqual(open(path).read(), body)
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

    def with_lib(self, version):
        os.makedirs(os.path.join(self.origin, "lib"), exist_ok=True)
        with open(os.path.join(self.origin, "lib", "mod.py"), "w") as f:
            f.write("X = %r\n" % version)
        self.commit(version, "with lib " + version)

    def apply_upgrade(self):
        tok = [l.split()[2] for l in self.q("--branch", "develop").stdout.splitlines() if l.startswith("plan token")][0]
        return self.q("--branch", "develop", "--plan", tok, "--approved", "go")

    def test_the_root_owned_checkout_is_compiled_through_sudo(self):
        """A checkout the user cannot write to: the git writes and the bytecode of lib/ (bin/qargi imports the guard from it) go through QARGI_SUDO,
        before install.sh --user runs; a failed compile is a note, not a failure of the upgrade."""
        log = os.path.join(self.t, "sudo.log")
        stub = os.path.join(self.t, "sudo")
        with open(stub, "w") as f:                                   # a sudo that notes its command, and lets the (not really root-owned) checkout be written
            f.write('#!/bin/sh\necho "$*" >> "$QARGI_TEST_SUDO"\nchmod u+w "$QARGI_TEST_TOOL/.git"\ncase "$*" in *compileall*) [ -z "$QARGI_TEST_NOCOMPILE" ] || exit 1;; esac\n"$@"; rc=$?\nchmod a-w "$QARGI_TEST_TOOL/.git"\nexit $rc\n')
        os.chmod(stub, 0o755)
        self.with_lib("0.2.0")
        self.env.update(QARGI_SUDO=stub, QARGI_TEST_SUDO=log, QARGI_TEST_TOOL=self.tool)
        os.chmod(os.path.join(self.tool, ".git"), 0o555)
        try:
            r = self.apply_upgrade()
            self.assertEqual(r.returncode, 0, r.stderr)
            with open(log) as f:
                calls = f.read().splitlines()
            self.assertTrue(any("git" in c and "merge" in c for c in calls), calls)
            self.assertTrue(any(c.endswith("python3 -I -m compileall -q %s" % os.path.join(self.tool, "lib")) for c in calls), calls)
            self.assertTrue(any(n.startswith("mod.") for n in os.listdir(os.path.join(self.tool, "lib", "__pycache__"))))
            with open(self.mark) as f:
                self.assertIn("--user", f.read())                    # install.sh --user ran after it
            self.with_lib("0.3.0")
            self.env["QARGI_TEST_NOCOMPILE"] = "1"
            r = self.apply_upgrade()
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("bytecode", r.stderr)
            self.assertIn("upgraded", r.stdout)
        finally:
            os.chmod(os.path.join(self.tool, ".git"), 0o755)

    def test_a_checkout_the_user_can_write_is_left_to_install_sh(self):
        self.with_lib("0.2.0")
        r = self.apply_upgrade()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.tool, "lib", "__pycache__")))   # install.sh --user compiles it (a stub here)

    def marked(self):
        """What the stub install.sh was called with, one line per call."""
        with open(self.mark) as f:
            return f.read()

    def plan_token(self, out):
        return [l.split()[2] for l in out.splitlines() if l.startswith("plan token")][0]

    def test_the_plan_lists_every_recorded_runtime(self):
        claude = os.path.join(self.t, ".claude-code", "skills")
        codex = self.runtime(self.conf, "codex")
        self.commit("0.2.0", "next")
        r = self.q("--branch", "develop")
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        i = lines.index("runtimes (install.sh --user relinks each):")
        self.assertEqual(lines[i + 1:i + 3], ["  claude-code in " + claude, "  codex in " + codex])
        self.assertTrue(lines[i + 3].startswith("plan token"), lines)

    def test_the_token_does_not_bind_the_runtimes(self):
        """The runtimes are shown, not bound: one recorded between the plan and the apply leaves the token as it was (install.sh decides)."""
        self.commit("0.2.0", "next")
        tok = self.plan_token(self.q("--branch", "develop").stdout)
        self.runtime(self.conf, "codex")
        self.assertEqual(self.plan_token(self.q("--branch", "develop").stdout), tok)
        r = self.q("--branch", "develop", "--plan", tok, "--approved", "go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.marked(), "--user\n")

    def test_the_apply_refuses_without_a_runtime_before_anything_is_fetched_or_moved(self):
        before, fetched = self.head(), git(self.tool, "rev-parse", "origin/develop")
        self.commit("0.2.0", "next")
        os.remove(os.path.join(self.conf, "install.d", "runtime-claude-code.manifest"))
        r = self.q("--branch", "develop")
        self.assertEqual(r.returncode, 0, r.stderr)                    # the plan still shows what would move, and says the apply refuses
        self.assertIn("runtimes: none recorded in %s/install.d, so the apply refuses" % self.conf, r.stdout)
        tok = self.plan_token(r.stdout)
        git(self.tool, "update-ref", "refs/remotes/origin/develop", fetched)    # as it was before the plan fetched
        log = os.path.join(self.t, "sudo.log")
        stub = os.path.join(self.t, "sudo")
        with open(stub, "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "$QARGI_TEST_SUDO"\n"$@"\n')
        os.chmod(stub, 0o755)
        self.env.update(QARGI_SUDO=stub, QARGI_TEST_SUDO=log)
        os.chmod(os.path.join(self.tool, ".git"), 0o555)               # a checkout the user cannot write: every write would go through sudo
        try:
            r = self.q("--branch", "develop", "--plan", tok, "--approved", "go")
        finally:
            os.chmod(os.path.join(self.tool, ".git"), 0o755)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("no runtime is recorded for the install in %s/install.d" % self.conf, r.stderr)
        self.assertIn("%s/install.sh --user" % self.tool, r.stderr)
        self.assertFalse(os.path.exists(log), "sudo ran")
        self.assertEqual((self.head(), git(self.tool, "rev-parse", "origin/develop")), (before, fetched))
        self.assertFalse(os.path.exists(self.mark))
        self.assertFalse(os.path.exists(os.path.join(self.state, "audit.log")))

    def test_a_record_that_cannot_be_read_stops_the_plan_and_the_apply(self):
        self.commit("0.2.0", "next")
        with open(os.path.join(self.conf, "install.d", "runtime-claude-code.manifest"), "a") as f:
            f.write("f\t/etc/passwd\n")
        for args in ((), ("--plan", "000000000000", "--approved", "go")):
            r = self.q("--branch", "develop", *args)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("cannot be read", r.stderr)
            self.assertNotIn("plan token", r.stdout)
        self.assertFalse(os.path.exists(self.mark))

    def test_guard_refuses_members(self):
        for cmd in ("qargi upgrade --branch develop", "bash lib/upgrade.sh --tag v1"):
            r = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.t}),
                               capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 2, cmd + r.stderr)


if __name__ == "__main__":
    unittest.main()
