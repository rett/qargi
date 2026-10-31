#!/usr/bin/env python3
"""qargi cloud: the per-project ant profile binding, with a stub ant. Offline; temporary state.
Run: python3 tests/test_cloud.py"""
import json, os, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
WS, OTHER = "wrkspc_01QargiQargiQargi", "wrkspc_01OtherOtherOther"
STUB = r'''#!/bin/sh
# a stub ant: profiles qargi -> WS_QARGI, claude -> WS_CLAUDE; records the profile each call ran under
p=${ANTHROPIC_PROFILE:-claude}
while [ $# -gt 0 ]; do case $1 in --profile) p=$2; shift 2;; *) break;; esac; done
echo "$p $*" >> "$STUB_LOG"
case "$1 $2" in
  "profile list") printf '* claude\n  qargi\n';;
  "profile get") case $p in qargi) echo "$STUB_QARGI_WS";; claude) echo wrkspc_01ClaudeClaudeClaude;; *) exit 1;; esac;;
  "auth status") exit 0;;
  "auth login") echo "login $*" >> "$STUB_LOG";;
  *) echo '{}';;
esac
'''


class T(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.conf, self.state, self.bin = (os.path.join(self.t, x) for x in ("c", "s", "b"))
        for d in (self.conf, self.state, self.bin, os.path.join(self.conf, "projects")):
            os.makedirs(d, exist_ok=True)
        self.log = os.path.join(self.t, "log")
        open(self.log, "w").close()
        with open(os.path.join(self.bin, "ant"), "w") as f:
            f.write(STUB)
        os.chmod(os.path.join(self.bin, "ant"), 0o755)
        self.env = dict(os.environ, HOME=self.t, QARGI_STATE=self.state, QARGI_CONF=self.conf, STUB_LOG=self.log, STUB_QARGI_WS=WS,
                        PATH=self.bin + ":" + os.environ["PATH"])
        self.env.pop("ANTHROPIC_PROFILE", None)
        self.env.pop("QARGI_PROJECT", None)
        self.proj = os.path.join(self.conf, "projects", "alpha.json")
        with open(self.proj, "w") as f:
            json.dump({"schema": 1, "project": "alpha", "repo": {"url": "https://github.com/example/alpha", "long_lived": ["main"]},
                       "roles": {"build": {"base": "main", "push": {"mode": "none"}, "model": "m", "effort": "high"}}, "memory": {}, "budget_cents": 500}, f)

    def q(self, *a, **kw):
        return subprocess.run([BIN, *a], capture_output=True, text=True, env=kw.get("env", self.env), stdin=subprocess.DEVNULL)

    def calls(self):
        with open(self.log) as f:
            return f.read().splitlines()

    def test_set_show_unset_and_validation(self):
        self.assertIn("no cloud binding", self.q("cloud", "show", "alpha").stdout)
        self.assertEqual(self.q("cloud", "set", "alpha", "--profile", "bad name", "--workspace-id", WS).returncode, 2)
        self.assertEqual(self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", "nope").returncode, 2)
        self.assertEqual(self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS).returncode, 0)
        self.assertIn(WS, self.q("cloud", "show", "alpha").stdout)
        self.assertIn("qargi -> " + WS, self.q("cloud", "list").stdout)
        self.assertEqual(oct(os.stat(self.proj).st_mode & 0o777), "0o600")
        self.assertEqual(self.q("project", "show", "alpha").returncode, 0)          # the answers stay readable
        self.q("cloud", "unset", "alpha")
        self.assertIn("no cloud binding", self.q("cloud", "show", "alpha").stdout)

    def test_check(self):
        self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS)
        self.assertEqual(self.q("cloud", "check", "alpha").returncode, 0)
        self.env["STUB_QARGI_WS"] = OTHER                                           # the profile was re-bound elsewhere
        r = self.q("cloud", "check", "alpha")
        self.assertEqual(r.returncode, 1)
        self.assertIn("not " + WS, r.stderr)
        self.q("cloud", "set", "alpha", "--profile", "ghost", "--workspace-id", WS)
        self.assertIn("does not exist", self.q("cloud", "check", "alpha").stderr)

    def test_login_needs_a_terminal_and_runs_nothing_here(self):
        self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS)
        r = self.q("cloud", "login", "alpha")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("own terminal", r.stderr)
        self.assertFalse([l for l in self.calls() if "login" in l])

    def test_commands_run_under_the_projects_profile(self):
        self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS)
        with open(os.path.join(self.conf, "instances.json"), "w") as f:
            json.dump({"alpha-build": {"location": "cloud", "agent": {"id": "a"}, "deployment_id": "dep_1"}}, f)
        open(self.log, "w").close()
        # a command about the project's instance: the profile is chosen from the name
        r = self.q("instances", "show", "alpha-build")
        self.assertNotIn("does not reach", r.stderr)
        calls = [l for l in self.calls() if l.strip()]
        self.assertTrue(any("deployments retrieve" in l for l in calls), calls)       # a cloud call really happened
        self.assertTrue(all(l.startswith("qargi ") for l in calls), calls)

    def test_refuses_when_the_workspace_differs(self):
        self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS)
        with open(os.path.join(self.conf, "instances.json"), "w") as f:
            json.dump({"alpha-build": {"location": "cloud", "agent": {"id": "a"}, "deployment_id": "dep_1"}}, f)
        self.env["STUB_QARGI_WS"] = OTHER
        r = self.q("instances", "show", "alpha-build")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("does not reach workspace " + WS, r.stderr)

    def test_a_conflicting_profile_in_the_environment_is_refused(self):
        self.q("cloud", "set", "alpha", "--profile", "qargi", "--workspace-id", WS)
        r = self.q("instances", "show", "alpha-build", env=dict(self.env, ANTHROPIC_PROFILE="claude"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("ANTHROPIC_PROFILE is claude", r.stderr)

    def test_unbound_projects_are_untouched(self):
        with open(os.path.join(self.conf, "instances.json"), "w") as f:
            json.dump({"alpha-build": {"location": "cloud", "agent": {"id": "a"}, "deployment_id": "dep_1"}}, f)
        self.q("instances", "show", "alpha-build")
        calls = [l for l in self.calls() if l.strip()]
        self.assertTrue(any("deployments retrieve" in l for l in calls), calls)
        self.assertTrue(all(l.startswith("claude ") for l in calls), calls)

    def test_guard_refuses_members(self):
        for cmd in ("qargi cloud set alpha --profile x --workspace-id " + WS, "qargi cloud login alpha", "python3 lib/cloud.py unset alpha"):
            r = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": self.t}),
                               capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 2, cmd + r.stderr)
        r = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "qargi cloud check alpha"}, "cwd": self.t}),
                           capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)


if __name__ == "__main__":
    unittest.main()
