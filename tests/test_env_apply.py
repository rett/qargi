#!/usr/bin/env python3
"""qargi env plan and env apply (lib/env_apply.py): a dry run runs project code, so the plan needs --approve-exec; the plan token, the refusals of
apply, the audit line and the record. Fixture repositories are invented (acme); the bootstrap recipe records its argv in a file, sudo is a fake that
records and runs its arguments. Offline. Run: python3 tests/test_env_apply.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, stat, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
import env_apply as A  # noqa: E402
from test_env import Fixtures, put  # noqa: E402

MAKEFILE = """# acme
$(shell touch parsed-marker)
$(info secret=[$(shell printenv SECRET_X)] path_has_dot=[$(findstring :.:,:$(PATH):)])
.PHONY: bootstrap doctor
doctor:
\t./record.sh doctor
bootstrap:
\t./record.sh bootstrap one two
\t@echo done
"""
RECORD = '#!/bin/sh\necho "$*" >> "$(dirname "$0")/record"\n'
SUDO = '#!/bin/sh\necho "sudo $*" >> "$(dirname "$0")/sudo-log"\nexec "$@"\n'
GO = "install the tools"


def slurp(p):
    with open(p) as f:
        return f.read()


class Apply(Fixtures):
    def setUp(self):
        super().setUp()
        self.bin = os.path.join(self.t, "fakebin")
        self.sudolog = os.path.join(self.bin, "sudo-log")
        os.chmod(put(self.bin, "sudo", SUDO), 0o755)
        self.env = dict(self.env, PATH=self.bin + os.pathsep + os.environ["PATH"], SECRET_X="hunter2")
        self.d = self.repo("acme", {"Makefile": MAKEFILE, "record.sh": RECORD})
        os.chmod(os.path.join(self.d, "record.sh"), 0o755)
        self.answers("acme", self.d)

    def ran(self, name="record"):
        p = os.path.join(self.d, name)
        return slurp(p) if os.path.exists(p) else None

    def plan(self, *extra):
        return self.q("env", "plan", "--repo", self.d, *extra)

    def token(self, *extra):
        r = self.plan("--approve-exec", "make", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        m = re.search(r"^plan token: ([0-9a-f]{12})\b", r.stdout, re.M)
        self.assertTrue(m, r.stdout)
        return m.group(1)

    def apply(self, tok, *extra, env=None):
        return self.q("env", "apply", "--repo", self.d, "--plan", tok, "--approved", GO, *extra, env=env)

    def set_makefile(self, text):
        put(self.d, "Makefile", text)

    def audit_lines(self):
        f = os.path.join(self.t, "state", "audit.log")
        return [json.loads(ln) for ln in slurp(f).splitlines()] if os.path.exists(f) else []

    # plan
    def test_plan_without_approve_exec_runs_nothing(self):
        for extra in ((), ("--approve-exec", "sh"), ("--approve-exec", "make,sh")):
            r = self.plan(*extra)
            self.assertEqual(r.returncode, 2, extra)
            self.assertIn("make -n bootstrap", r.stdout)                  # what it would run
            self.assertIn("--approve-exec make", r.stdout)
            self.assertIn("$(shell", r.stdout)                            # why
            self.assertFalse(os.path.exists(os.path.join(self.d, "parsed-marker")), "project code ran without approval")
        self.assertIsNone(self.ran())

    def test_plan_lists_the_lines_the_executables_and_a_token(self):
        r = self.plan("--approve-exec", "make")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        self.assertIn("dry run:   make -n bootstrap", out)
        self.assertIn("bootstrap: make bootstrap", out)
        self.assertIn("privileged lines (0)", out)
        self.assertRegex(out, r"(?m)^\s+\d+: \./record\.sh bootstrap one two$")
        self.assertIn("other lines (", out)
        seen = out.split("executables seen")[1].split("dry run runs")[0]
        self.assertIn("./record.sh", seen)
        self.assertNotIn("echo", seen)                                    # a shell builtin is not listed
        self.assertIn("best effort", out)
        self.assertRegex(out, r"(?m)^plan token: [0-9a-f]{12}   \(apply with: qargi env apply --plan [0-9a-f]{12} --approved .* --approve-exec make\)$")
        self.assertTrue(os.path.exists(os.path.join(self.d, "parsed-marker")), "$(shell) is run by the dry run: that is why plan is gated")
        self.assertIsNone(self.ran(), "the dry run ran the recipe")

    def test_the_child_gets_a_minimal_environment_and_no_stdin(self):
        r = self.plan("--approve-exec", "make")
        self.assertIn("secret=[]", r.stdout)                              # SECRET_X of the caller did not get through
        self.assertNotIn("hunter2", r.stdout)
        env = A.child_env()
        self.assertTrue(set(env) <= set(A.KEEP) | {"PATH"})
        os.environ["PATH"] = "/usr/bin:.:rel/bin:/bin"
        try:
            self.assertEqual(A.child_env()["PATH"], "/usr/bin:/bin")      # relative entries are dropped
        finally:
            os.environ["PATH"] = self.env["PATH"].split(os.pathsep, 1)[1]

    def test_the_token_follows_the_recipe_the_head_and_the_commands(self):
        t1 = self.token()
        self.assertEqual(self.token(), t1)                                # stable
        self.set_makefile(MAKEFILE.replace("one two", "one three"))
        t2 = self.token()
        self.assertNotEqual(t1, t2)
        subprocess.run(["git", "init", "-q"], cwd=self.d, check=True)
        t3 = self.token()                                                  # no commit: HEAD is none, as before
        self.assertEqual(t2, t3)
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.test", "commit", "-q", "--allow-empty", "-m", "x"], cwd=self.d, check=True)
        t4 = self.token()
        self.assertNotEqual(t3, t4)
        self.answers("acme", self.d, env={"bootstrap_command": "make bootstrap PROFILE=ci"})
        self.assertNotEqual(self.token(), t4)                             # the bootstrap command is part of it

    def test_privileged_lines_are_grouped(self):
        # hermetic: allow tmp (a word of the Makefile text that is judged, never run)
        self.set_makefile(MAKEFILE + "\tsudo ./record.sh rooted\n\tcd /tmp && doas whoami\n\tenv A=1 sh -c 'pkexec id'\n\t@echo sudo is a word here\n")
        r = self.plan("--approve-exec", "make")
        self.assertEqual(r.returncode, 0, r.stderr)
        priv = r.stdout.split("privileged lines (")[1].split("other lines (")[0]
        self.assertTrue(priv.startswith("3)"), priv)
        for needle in ("sudo ./record.sh rooted", "doas whoami", "pkexec id"):
            self.assertIn(needle, priv)
        self.assertNotIn("is a word here", priv)
        self.assertIn("--allow-root", r.stdout.split("plan token:")[1])
        seen = r.stdout.split("executables seen")[1]
        for x in ("sudo", "doas", "pkexec", "id", "whoami", "./record.sh"):
            self.assertRegex(seen, r"(?m)^  %s$" % re.escape(x))

    def test_scan(self):
        self.assertEqual(A.scan("sudo -u root pacman -S --needed git"), (["sudo", "pacman"], True))
        self.assertEqual(A.scan("make: Nothing to be done for 'bootstrap'."), ([], False))
        self.assertEqual(A.scan("FOO=1 curl -fsSL x > out.sh; sh out.sh"), (["curl", "sh"], False))
        self.assertEqual(A.scan("echo 'a && sudo b'"), ([], False))
        self.assertEqual(A.scan("bash -c 'apt-get update && sudo apt-get install -y git'"), (["bash", "apt-get", "sudo", "apt-get"], True))
        self.assertEqual(A.scan("echo don't"), ([], False))                  # an open quote falls back to blanks
        self.assertEqual(A.scan("if true; then ls; fi"), (["ls"], False))
        self.assertEqual(A.scan("echo $(date) | tr a b"), (["date", "tr"], False))

    def test_output_is_shown_escaped(self):
        self.set_makefile(MAKEFILE + "\t@printf '\\033[31mred\\342\\200\\256 done'\n")
        out = self.plan("--approve-exec", "make").stdout
        self.assertNotIn("\x1b", out)
        self.assertNotIn("\u202e", out)

    def test_a_failing_or_slow_dry_run_makes_no_plan(self):
        self.set_makefile(MAKEFILE + "$(error broken)\n")
        r = self.plan("--approve-exec", "make")
        self.assertEqual(r.returncode, 1)
        self.assertIn("exited with status", r.stderr)
        self.assertNotIn("plan token", r.stdout)
        self.set_makefile(MAKEFILE + "$(shell sleep 20)\n")
        r = self.q("env", "plan", "--repo", self.d, "--approve-exec", "make", env=dict(self.env, QARGI_ENV_TIMEOUT="1"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("did not finish in 1 seconds", r.stderr)

    def test_a_command_that_needs_a_shell_or_is_missing_is_refused(self):
        self.answers("acme", self.d, env={"dry_run_command": "make -n bootstrap && true"})
        r = self.plan("--approve-exec", "make")
        self.assertEqual(r.returncode, 2)
        self.assertIn("needs a shell", r.stderr)
        self.answers("acme", self.d, env={"dry_run_command": "nosuchtool -n"})
        r = self.plan("--approve-exec", "nosuchtool")
        self.assertEqual(r.returncode, 2)
        self.assertIn("not on the PATH", r.stderr)
        e = self.repo("bare", {})
        r = self.q("env", "plan", "--repo", e, "--approve-exec", "make")
        self.assertEqual(r.returncode, 2)
        self.assertIn("no bootstrap target", r.stderr)
        self.assertEqual(self.q("env", "plan", "--bogus").returncode, 2)
        self.assertEqual(self.q("env", "apply", "--repo", self.d).returncode, 2)

    # apply
    def test_apply_runs_the_bootstrap_once_and_records_it(self):
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ran(), "bootstrap one two\ndoctor\n")            # then env check runs the doctor
        self.assertIn("running: make bootstrap", r.stdout)
        self.assertIn("running: qargi env check", r.stdout)
        self.assertTrue(r.stdout.rstrip().endswith("ENV OK"), r.stdout)
        lines = [x for x in self.audit_lines() if x["verb"].startswith("env:apply")]
        self.assertEqual([x["verb"] for x in lines], ["env:apply", "env:apply-result"])
        self.assertEqual(lines[0]["approved"], GO)
        self.assertIn(tok, lines[0]["detail"])
        self.assertTrue(lines[1]["detail"].endswith("exit 0"))
        f = os.path.join(self.t, "state", "env", "acme.json")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        doc = json.loads(slurp(f))
        self.assertEqual((doc["check"]["verdict"], doc["check"]["exit"]), ("ENV OK", 0))       # check kept apply's key and added its own
        rec = doc["apply"]
        self.assertEqual((rec["exit"], rec["command"], rec["token"], rec["allow_root"]), (0, "make bootstrap", tok, False))
        self.assertEqual(len(rec["dry_run_sha256"]), 64)

    def test_apply_keeps_what_else_the_record_holds(self):
        f = os.path.join(self.t, "state", "env", "acme.json")
        put(os.path.dirname(f), "acme.json", json.dumps({"note": {"kept": True}, "check": {"verdict": "old"}}))
        self.assertEqual(self.apply(self.token(), "--approve-exec", "make").returncode, 0)
        d = json.loads(slurp(f))
        self.assertEqual(d["note"], {"kept": True})
        self.assertEqual(d["check"]["verdict"], "ENV OK")                  # check replaced its own key
        self.assertEqual(d["apply"]["exit"], 0)
        self.assertEqual(self.q("env", "check", "--repo", self.d).returncode, 0)
        self.assertEqual(json.loads(slurp(f))["apply"]["exit"], 0)         # and a check alone keeps apply's

    def test_apply_refuses_a_stale_token(self):
        tok = self.token()
        self.set_makefile(MAKEFILE.replace("one two", "changed"))
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the plan changed", r.stderr)
        self.assertIsNone(self.ran())
        r = self.apply("0123456789ab", "--approve-exec", "make")
        self.assertEqual(r.returncode, 1)
        self.assertEqual([x for x in self.audit_lines() if x["verb"].startswith("env:apply")], [])

    def test_apply_refuses_without_the_approvals(self):
        tok = self.token()
        r = self.q("env", "apply", "--repo", self.d, "--plan", tok, "--approve-exec", "make")           # no --approved
        self.assertEqual(r.returncode, 2)
        r = self.q("env", "apply", "--repo", self.d, "--approved", GO, "--approve-exec", "make")        # no --plan
        self.assertEqual(r.returncode, 2)
        r = self.apply(tok)                                                                              # no --approve-exec
        self.assertEqual(r.returncode, 2)
        self.assertIn("--approve-exec must name make", r.stderr)
        r = self.apply(tok, "--approve-exec", "git")                                                     # not the executable
        self.assertEqual(r.returncode, 2)
        r = self.apply(tok, "--approve-exec", "make,nosuchname")                                         # a name the plan did not list
        self.assertEqual(r.returncode, 2)
        self.assertIn("nosuchname", r.stderr)
        self.assertIsNone(self.ran())
        self.assertFalse(os.path.exists(os.path.join(self.t, "state", "env")))

    def test_apply_needs_the_bootstrap_executable_named_too(self):
        self.answers("acme", self.d, env={"bootstrap_command": "sh ./record.sh viash"})
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 2)
        self.assertIn("does not name sh", r.stderr)
        self.assertIsNone(self.ran())
        r = self.apply(tok, "--approve-exec", "make,sh")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ran(), "viash\ndoctor\n")

    def test_apply_refuses_privileged_lines_without_allow_root(self):
        self.set_makefile(MAKEFILE + "\tsudo ./record.sh rooted\n")
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--allow-root", r.stderr)
        self.assertIn("sudo ./record.sh rooted", r.stderr)
        self.assertIsNone(self.ran())
        self.assertFalse(os.path.exists(self.sudolog))
        r = self.apply(tok, "--approve-exec", "make,sudo", "--allow-root")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.ran(), "bootstrap one two\nrooted\ndoctor\n")
        self.assertEqual(slurp(self.sudolog), "sudo ./record.sh rooted\n")
        self.assertIn("allow-root", [x for x in self.audit_lines() if x["verb"] == "env:apply"][0]["detail"])
        self.assertTrue(json.loads(slurp(os.path.join(self.t, "state", "env", "acme.json")))["apply"]["allow_root"])

    def test_apply_exits_with_the_check_when_the_environment_is_still_incomplete(self):
        self.set_makefile(MAKEFILE.replace("./record.sh doctor", "@echo missing: acme-tool"))
        r = self.apply(self.token(), "--approve-exec", "make")
        self.assertEqual(r.returncode, 1)
        self.assertIn("ENV INCOMPLETE: 1 missing", r.stdout)
        self.assertEqual(json.loads(slurp(os.path.join(self.t, "state", "env", "acme.json")))["apply"]["exit"], 0)

    def test_a_failing_bootstrap_is_audited_and_fails(self):
        self.answers("acme", self.d, env={"bootstrap_command": "make nosuchtarget"})
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 1)
        self.assertIn("exited with status 2", r.stderr)
        self.assertNotIn("env check", r.stdout)
        lines = [x for x in self.audit_lines() if x["verb"].startswith("env:apply")]
        self.assertTrue(lines[-1]["detail"].endswith("exit 2"), lines)
        self.assertEqual(json.loads(slurp(os.path.join(self.t, "state", "env", "acme.json")))["apply"]["exit"], 2)

    def test_qargi_dry_run_stops_before_the_bootstrap(self):
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make", env=dict(self.env, QARGI_DRY_RUN="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("not run", r.stdout)
        self.assertIsNone(self.ran())
        self.assertEqual([x for x in self.audit_lines() if x["verb"].startswith("env:apply")], [])
        self.assertFalse(os.path.exists(os.path.join(self.t, "state", "env")))

    def test_the_bootstrap_keeps_the_terminal(self):
        """Standard input is inherited by the bootstrap command (sudo asks there) and the caller's secrets are not."""
        self.set_makefile(MAKEFILE + "\t@read -r line < /dev/stdin && echo \"$$line $${SECRET_X:-none}\" >> stdin-record\n")
        tok = self.token()
        r = subprocess.run([A.__file__.replace("lib/env_apply.py", "bin/qargi"), "env", "apply", "--repo", self.d, "--plan", tok, "--approved", GO, "--approve-exec", "make"],
                           input="typed\n", capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(slurp(os.path.join(self.d, "stdin-record")), "typed none\n")

    def test_the_old_placeholder_is_gone(self):
        import env as E
        self.assertFalse(hasattr(E, "LEAD_ONLY"))
        self.assertNotIn("not built yet", self.q("env", "plan").stderr)



class Tools(Apply):
    """roles.<role>.tools in the plan and the apply: a go tool (go install, a fake go) and a binary (downloaded from a local server, checked
    against its sha256), the token over them, go in --approve-exec, and env check reporting what is missing or wrong."""
    GO_TOOL = {"kind": "go", "name": "github.com/acme/lint/cmd/acme-lint", "version": "v1.2.0"}

    def setUp(self):
        super().setUp()
        import shutil, threading
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        shutil.copy(os.path.join(ROOT, "tests", "fixtures", "fake-go.sh"), os.path.join(self.bin, "go"))
        os.chmod(os.path.join(self.bin, "go"), 0o755)
        self.gobin = os.path.join(self.t, "gobin")
        self.local_bin = os.path.join(self.t, ".local", "bin")
        self.env = dict(self.env, GOBIN=self.gobin, PATH=self.gobin + os.pathsep + self.local_bin + os.pathsep + self.env["PATH"])
        self.www = os.path.join(self.t, "www")
        self.payload = b"#!/bin/sh\necho acme-fmt 2.0.1\n"
        with open(put(self.www, "acme-fmt-2.0.1", ""), "wb") as f:
            f.write(self.payload)
        handler = type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *a: None})
        self.srv = HTTPServer(("127.0.0.1", 0), lambda *a: handler(*a, directory=self.www))
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.url = "http://127.0.0.1:%d/acme-fmt-2.0.1" % self.srv.server_address[1]
        self.sha = __import__("hashlib").sha256(self.payload).hexdigest()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        super().tearDown()

    def binary(self, **kw):
        return dict({"kind": "binary", "name": "acme-fmt", "version": "2.0.1", "url": self.url, "sha256": self.sha}, **kw)

    def declare(self, build, test=None):
        a = {"schema": 1, "project": "acme", "repo": {"url": "https://github.com/acme/acme", "path": self.d, "long_lived": ["master", "develop"]},
             "roles": {"build": {"base": "develop", "push": {"mode": "none"}, "effort": "high", "tools": build}}}
        if test is not None:
            a["roles"]["test"] = {"base": "develop", "push": {"mode": "none"}, "effort": "high", "tools": test}
        put(self.conf, "projects/acme.json", json.dumps(a))

    def go_log(self):
        p = os.path.join(self.bin, "go-log")
        return slurp(p) if os.path.exists(p) else ""

    def test_the_plan_lists_the_tools_with_their_state_and_names_go(self):
        self.declare([self.GO_TOOL, self.binary(), {"kind": "submodule", "name": "acme-test", "path": "vendor/acme-test"}], test=[self.GO_TOOL])
        r = self.plan("--approve-exec", "make")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("tools the roles declare (roles.<role>.tools), 3;", r.stdout)
        self.assertRegex(r.stdout, r"(?m)^  missing go github\.com/acme/lint/cmd/acme-lint@v1\.2\.0   \[build, test\]   acme-lint is not installed")
        self.assertRegex(r.stdout, r"(?m)^  missing binary acme-fmt 2\.0\.1   \[build\]   acme-fmt is not installed")
        self.assertRegex(r.stdout, r"(?m)^  note    submodule vendor/acme-test   \[build\]   submodule vendor/acme-test: .* is not a git work tree")
        self.assertRegex(r.stdout, r"(?m)^plan token: [0-9a-f]{12}   \(apply with: .* --approve-exec go,make\)$")
        self.assertEqual(self.go_log(), "")                                # the plan installs nothing
        self.assertFalse(os.path.exists(os.path.join(self.local_bin, "acme-fmt")))

    def test_the_token_covers_the_tools(self):
        self.declare([self.GO_TOOL])
        t1 = self.token()
        self.declare([dict(self.GO_TOOL, version="v1.3.0")])
        t2 = self.token()
        self.assertNotEqual(t1, t2)
        r = self.apply(t1, "--approve-exec", "make,go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the plan changed", r.stderr)
        self.assertIsNone(self.ran())

    def test_apply_needs_go_named_and_installs_after_the_bootstrap(self):
        self.declare([self.GO_TOOL, self.binary()])
        tok = self.token()
        r = self.apply(tok, "--approve-exec", "make")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("and go for the go tools of the plan) and does not name go; nothing was run", r.stderr)
        self.assertIsNone(self.ran())
        r = self.apply(tok, "--approve-exec", "make,go")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.ran(), "bootstrap one two\ndoctor\n")
        self.assertEqual(self.go_log(), "install github.com/acme/lint/cmd/acme-lint@v1.2.0\n")
        self.assertLess(r.stdout.index("running: make bootstrap"), r.stdout.index("running: go install github.com/acme/lint/cmd/acme-lint@v1.2.0"))
        self.assertIn("go github.com/acme/lint/cmd/acme-lint@v1.2.0: installed", r.stdout)
        self.assertIn("binary acme-fmt 2.0.1: installed", r.stdout)
        f = os.path.join(self.local_bin, "acme-fmt")
        with open(f, "rb") as fh:
            self.assertEqual(fh.read(), self.payload)
        self.assertTrue(os.stat(f).st_mode & stat.S_IXUSR)
        self.assertTrue(r.stdout.rstrip().endswith("ENV OK"), r.stdout)    # env check finds both, at the declared version and hash
        rec = json.loads(slurp(os.path.join(self.t, "state", "env", "acme.json")))["apply"]
        self.assertEqual(rec["tools"], [{"kind": "go", "name": "github.com/acme/lint/cmd/acme-lint", "version": "v1.2.0", "exit": 0},
                                        {"kind": "binary", "name": "acme-fmt", "version": "2.0.1", "exit": 0}])
        # a second apply has nothing to install: the tools are ok, go need not be named
        r = self.apply(self.token(), "--approve-exec", "make")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.go_log(), "install github.com/acme/lint/cmd/acme-lint@v1.2.0\n")
        self.assertIn("  ok      go github.com/acme/lint/cmd/acme-lint@v1.2.0", r.stdout)

    def test_a_binary_whose_sha256_differs_is_not_installed(self):
        self.declare([self.binary(sha256="f" * 64)])
        r = self.apply(self.token(), "--approve-exec", "make")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("binary acme-fmt 2.0.1: FAILED", r.stdout)
        self.assertIn("has sha256 %s, not the declared %s; not installed" % (self.sha, "f" * 64), r.stdout)
        self.assertIn("1 tool(s) could not be installed: binary acme-fmt 2.0.1", r.stderr)
        self.assertEqual(os.listdir(self.local_bin), [])                   # no file, no temporary left behind
        self.assertNotIn("env check", r.stdout)

    def test_a_wrong_version_is_reinstalled_and_a_failing_go_install_is_named(self):
        subprocess.run([os.path.join(self.bin, "go"), "install", "github.com/acme/lint/cmd/acme-lint@v1.1.0"], check=True, env=self.env)
        self.declare([self.GO_TOOL])
        r = self.plan("--approve-exec", "make")
        self.assertRegex(r.stdout, r"(?m)^  wrong   go github\.com/acme/lint/cmd/acme-lint@v1\.2\.0   \[build\]   acme-lint at .* is v1\.1\.0; roles build pins v1\.2\.0")
        r = self.apply(self.token(), "--approve-exec", "make,go")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.go_log().endswith("install github.com/acme/lint/cmd/acme-lint@v1.2.0\n"))
        self.declare([dict(self.GO_TOOL, version="v0.0.0-broken")])
        r = self.apply(self.token(), "--approve-exec", "make,go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("go github.com/acme/lint/cmd/acme-lint@v0.0.0-broken: FAILED", r.stdout)
        self.assertIn("no matching version", r.stdout)

    def test_a_failing_bootstrap_installs_no_tool_and_dry_run_stops_before_both(self):
        self.declare([self.GO_TOOL])
        put(self.conf, "projects/acme.json", json.dumps(dict(json.loads(slurp(os.path.join(self.conf, "projects", "acme.json"))), env={"bootstrap_command": "make nosuchtarget"})))
        r = self.apply(self.token(), "--approve-exec", "make,go")
        self.assertEqual(r.returncode, 1)
        self.assertIn("the 1 tool install(s) were not run", r.stderr)
        self.assertEqual(self.go_log(), "")
        self.declare([self.GO_TOOL])
        r = self.apply(self.token(), "--approve-exec", "make,go", env=dict(self.env, QARGI_DRY_RUN="1"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("then 1 tool install(s); it was not run", r.stdout)
        self.assertEqual(self.go_log(), "")

    def test_env_check_reports_a_missing_or_wrong_tool(self):
        self.declare([self.GO_TOOL, self.binary()])
        r = self.q("env", "check", "--project", "acme")
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("tools:    2 declared (roles.<role>.tools): 2 missing", r.stdout)
        self.assertIn("missing:  acme-lint is not installed (roles build: go github.com/acme/lint/cmd/acme-lint@v1.2.0; qargi env apply installs it)", r.stdout)
        self.assertIn("missing:  acme-fmt is not installed", r.stdout)
        self.assertIn("ENV INCOMPLETE: 2 missing", r.stdout)
        subprocess.run([os.path.join(self.bin, "go"), "install", "github.com/acme/lint/cmd/acme-lint@v1.1.0"], check=True, env=self.env)
        os.makedirs(self.local_bin)
        with open(os.path.join(self.local_bin, "acme-fmt"), "wb") as f:
            f.write(b"other\n")
        os.chmod(os.path.join(self.local_bin, "acme-fmt"), 0o755)
        r = self.q("env", "check", "--project", "acme", "--json")
        j = json.loads(r.stdout)
        self.assertEqual(len(j["missing"]), 2, j["missing"])
        self.assertTrue(any("is v1.1.0; roles build pins v1.2.0" in m for m in j["missing"]), j["missing"])
        self.assertTrue(any("sha256 differs" in m for m in j["missing"]), j["missing"])
        self.assertEqual(self.ran(), "doctor\ndoctor\n")                   # the doctor still ran each time; the tools come after it

    def test_two_roles_pinning_a_tool_differently_fail_validation(self):
        self.declare([self.GO_TOOL], test=[dict(self.GO_TOOL, version="v1.3.0")])
        r = self.q("project", "validate", "acme")
        self.assertEqual(r.returncode, 1)
        self.assertIn("roles.build.tools and roles.test.tools declare go github.com/acme/lint/cmd/acme-lint differently", r.stdout)
        self.assertEqual(self.plan("--approve-exec", "make").returncode, 0)   # the plan still runs (with the first entry); project set would not store this

if __name__ == "__main__":
    unittest.main()
