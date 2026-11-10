#!/usr/bin/env python3
"""lib/procenv.py: the helpers several modules share to start a child process (clean_path, child_env) and the modules that use them
(lib/env_check.py, lib/env_apply.py, lib/local_run.py, lib/tools.py). Offline; no project, no network.
Run: python3 tests/test_procenv.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, shutil, socket, subprocess, sys, tempfile, time, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
sys.path.insert(0, LIB)
import procenv as PE  # noqa: E402

LONG = "/usr/local/bin:/usr/bin:/bin"


def with_path(value):
    """The caller's environment with PATH set to value (None: unset)."""
    env = {k: v for k, v in os.environ.items() if k != "PATH"}
    if value is not None:
        env["PATH"] = value
    return mock.patch.dict(os.environ, env, clear=True)


class CleanPath(unittest.TestCase):
    def test_relative_and_empty_entries_are_dropped(self):
        with with_path("/opt/x/bin::.:rel/bin:/usr/bin:./bin:/bin"):
            self.assertEqual(PE.clean_path(), "/opt/x/bin:/usr/bin:/bin")

    def test_the_fallback_is_the_longer_default_path(self):
        self.assertEqual(PE.DEFAULT_PATH, LONG)
        for value in (None, "", ".", "rel:bin:", "::"):
            with with_path(value):
                self.assertEqual(PE.clean_path(), LONG, repr(value))

    def test_every_module_that_starts_a_child_falls_back_to_the_same_path(self):
        import env_apply, env_check, local_run, tools
        for value in (None, "rel:.", ""):
            with with_path(value):
                self.assertEqual(env_apply.child_env()["PATH"], LONG)
                self.assertEqual(env_check.PE.child_env()["PATH"], LONG)
                self.assertEqual(tools.clean_path(), LONG)
                self.assertEqual(tools.child_env()["PATH"], LONG)
                self.assertEqual(local_run.clean_path(), LONG)
                self.assertEqual(local_run.child_env("/run", "/tmp/t", [])["PATH"], LONG)

    def test_a_path_with_absolute_entries_is_the_same_everywhere(self):
        import env_apply, env_check, local_run, tools
        with with_path("/usr/bin:.:rel/bin:/bin"):
            got = {PE.clean_path(), env_apply.child_env()["PATH"], tools.clean_path(), local_run.clean_path(), env_check.PE.clean_path()}
        self.assertEqual(got, {"/usr/bin:/bin"})


class ChildEnv(unittest.TestCase):
    def test_the_base_environment(self):
        with mock.patch.dict(os.environ, {"HOME": "/h", "USER": "u", "LOGNAME": "u", "TMPDIR": "/t", "SECRET_X": "hunter2", "LANG": "xx", "GOPATH": "/g"}):
            env = PE.child_env()
        self.assertEqual(env["LANG"], "C.UTF-8")
        self.assertEqual((env["LC_ALL"], env["TERM"], env["GIT_TERMINAL_PROMPT"]), ("C.UTF-8", "dumb", "0"))
        self.assertEqual({k: env[k] for k in ("HOME", "USER", "LOGNAME", "TMPDIR")}, {"HOME": "/h", "USER": "u", "LOGNAME": "u", "TMPDIR": "/t"})
        self.assertNotIn("SECRET_X", env)
        self.assertNotIn("GOPATH", env)

    def test_keep_adds_names_and_empty_values_are_not_passed(self):
        with mock.patch.dict(os.environ, {"GOPATH": "/g", "GOBIN": "", "HOME": ""}):
            env = PE.child_env(("GOPATH", "GOBIN"))
        self.assertEqual(env.get("GOPATH"), "/g")
        self.assertNotIn("GOBIN", env)
        self.assertNotIn("HOME", env)

    def test_tools_keeps_the_go_names(self):
        import tools
        with mock.patch.dict(os.environ, {"GOPROXY": "off", "GOFLAGS": "-mod=mod", "SECRET_X": "hunter2"}):
            env = tools.child_env()
        self.assertEqual((env["GOPROXY"], env["GOFLAGS"]), ("off", "-mod=mod"))
        self.assertNotIn("SECRET_X", env)

    def test_env_apply_keeps_its_own_list(self):
        import env_apply
        with mock.patch.dict(os.environ, {"TZ": "UTC", "LANG": "de_DE.UTF-8", "SECRET_X": "hunter2", "GOPATH": "/g"}):
            env = env_apply.child_env()
        self.assertEqual((env["TZ"], env["LANG"]), ("UTC", "de_DE.UTF-8"))      # passed on as they are, not fixed
        self.assertTrue(set(env) <= set(env_apply.KEEP) | {"PATH"})


class Now(unittest.TestCase):
    def test_the_stamp_is_utc_to_the_second(self):
        self.assertEqual(PE.now(0), "1970-01-01T00:00:00Z")
        self.assertEqual(PE.now(1700000000), "2023-11-14T22:13:20Z")
        self.assertEqual(PE.now(1700000000.9), "2023-11-14T22:13:20Z")
        self.assertRegex(PE.now(), r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")

    def test_it_is_UTC_whatever_the_zone(self):
        was = os.environ.get("TZ")
        try:
            os.environ["TZ"] = "Asia/Tokyo"
            time.tzset()
            self.assertEqual(PE.now(0), "1970-01-01T00:00:00Z")
        finally:
            if was is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = was
            time.tzset()

    def test_discover_keeps_no_copy_of_it(self):
        import discover
        self.assertFalse(hasattr(discover, "now"))
        self.assertRegex(discover.approval(), r" at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class PlanToken(unittest.TestCase):
    def test_it_is_twelve_hex_digits_of_the_sha256_of_the_parts(self):
        self.assertEqual(PE.plan_token("a"), hashlib.sha256(b"a").hexdigest()[:12])
        self.assertEqual(PE.plan_token("a", "b", "c"), hashlib.sha256(b"a\nb\nc").hexdigest()[:12])
        self.assertEqual(PE.plan_token("é"), hashlib.sha256("é".encode("utf-8")).hexdigest()[:12])
        self.assertNotEqual(PE.plan_token("a", "b"), PE.plan_token("ab"))

    def test_it_is_the_token_the_approvals_library_makes(self):
        from conformance import library as L
        for parts in (("x",), ("verb", "name", "kind"), ("", "")):
            self.assertEqual(PE.plan_token(*parts), L.token_of(*parts))

    def test_env_apply_makes_its_token_with_it(self):
        import env_apply
        ctx = {"dry": "make -n bootstrap", "boot": "make bootstrap", "repo": "/r", "head": "abc", "tools": []}
        want = PE.plan_token(json.dumps({"dry_run_output": "out", "dry_run_command": "make -n bootstrap", "bootstrap_command": "make bootstrap",
                                         "repo": "/r", "head": "abc", "host": socket.gethostname(), "tools": []}, sort_keys=True))
        self.assertEqual(env_apply.token_of("out", ctx), want)


class Audit(unittest.TestCase):
    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="procenv-state.")
        self.addCleanup(shutil.rmtree, self.state, True)
        self.log = os.path.join(self.state, "audit.log")

    def lines(self):
        with open(self.log) as f:
            return [json.loads(ln) for ln in f.read().splitlines()]

    def test_the_line_has_the_fields_and_the_order_the_log_always_had(self):
        PE.audit("env:apply", "make bootstrap", approved="go ahead", state=self.state)
        with open(self.log) as f:
            text = f.read()
        row = self.lines()[0]
        self.assertEqual(list(row), ["ts", "verb", "detail", "asked", "approved", "nested"])
        self.assertEqual((row["verb"], row["detail"], row["asked"], row["approved"], row["nested"]), ("env:apply", "make bootstrap", "", "go ahead", False))
        self.assertRegex(row["ts"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertTrue(text.endswith("}\n") and text.count("\n") == 1)

    def test_a_line_of_the_supervisor_carries_its_origin_last(self):
        PE.audit("supervise:waiting", "k run next", asked="why", origin="supervisor", ts="2026-01-02T03:04:05Z", state=self.state)
        row = self.lines()[0]
        self.assertEqual(list(row), ["ts", "verb", "detail", "asked", "approved", "nested", "origin"])
        self.assertEqual((row["ts"], row["asked"], row["approved"], row["origin"]), ("2026-01-02T03:04:05Z", "why", "", "supervisor"))

    def test_lines_are_appended_and_the_file_is_private(self):
        PE.audit("a", "1", state=self.state)
        PE.audit("b", "2", state=self.state)
        self.assertEqual([r["verb"] for r in self.lines()], ["a", "b"])
        self.assertEqual(os.stat(self.log).st_mode & 0o777, 0o600)
        os.chmod(self.log, 0o644)
        PE.audit("c", "3", state=self.state)
        self.assertEqual(os.stat(self.log).st_mode & 0o777, 0o600)

    def test_the_state_directory_is_made_and_is_the_default(self):
        inner = os.path.join(self.state, "not", "yet")
        PE.audit("a", "1", state=inner)
        self.assertTrue(os.path.isfile(os.path.join(inner, "audit.log")))
        with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):
            PE.audit("d", "4")
        self.assertEqual([r["verb"] for r in self.lines()], ["d"])

    def test_env_apply_and_supervise_write_through_it(self):
        import env_apply, supervise
        with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):
            env_apply.audit("env:apply", "detail", {"--approved": "words"})
        row = self.lines()[0]
        self.assertEqual((row["verb"], row["approved"], "origin" in row), ("env:apply", "words", False))
        with mock.patch.object(supervise, "STATE", self.state):
            supervise.audit("supervise:looping", "k r next", "2026-02-03T04:05:06Z", "ask")
        row = self.lines()[1]
        self.assertEqual((row["ts"], row["verb"], row["asked"], row["approved"], row["origin"]), ("2026-02-03T04:05:06Z", "supervise:looping", "ask", "", "supervisor"))


class Die(unittest.TestCase):
    def run_die(self, *args):
        code = "import sys; sys.path.insert(0, %r); import procenv; procenv.die(*%r)" % (LIB, args)
        return subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, stdin=subprocess.DEVNULL)

    def test_it_says_qargi_and_leaves_with_the_status(self):
        r = self.run_die("no such thing")
        self.assertEqual((r.returncode, r.stdout, r.stderr), (1, "", "qargi: no such thing\n"))
        r = self.run_die("usage: x", 2)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (2, "", "qargi: usage: x\n"))

    def test_discover_says_it_the_same_way(self):
        import discover
        self.assertIs(discover.die, PE.die)
        env = {"PATH": "/usr/bin:/bin", "HOME": os.environ["HOME"], "QARGI_CONF": os.environ.get("QARGI_CONF", "/nonexistent"), "QARGI_STATE": os.environ.get("QARGI_STATE", "/nonexistent")}
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "discover.py"), "show", "no-such-entry"], capture_output=True, text=True, stdin=subprocess.DEVNULL, env=env)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertTrue(r.stderr.startswith("qargi: no entry 'no-such-entry'"), r.stderr)


class Git(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="procenv-git.")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.repo = os.path.join(self.t, "repo")
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True, capture_output=True)

    def test_exit_stdout_and_stderr_as_git_wrote_them(self):
        rc, out, err = PE.git("rev-parse", "--git-dir", repo=self.repo)
        self.assertEqual((rc, out, err), (0, ".git\n", ""))
        rc, out, err = PE.git("rev-parse", "HEAD", repo=self.repo)
        self.assertNotEqual(rc, 0)
        self.assertIn("HEAD", err)

    def test_repo_cwd_and_git_dir_choose_the_repository(self):
        self.assertEqual(PE.git("rev-parse", "--show-toplevel", repo=self.repo)[1], os.path.realpath(self.repo) + "\n")
        self.assertEqual(PE.git("rev-parse", "--show-toplevel", cwd=self.repo)[1], os.path.realpath(self.repo) + "\n")
        self.assertEqual(PE.git("rev-parse", "--is-bare-repository", git_dir=os.path.join(self.repo, ".git"))[1], "false\n")

    def test_the_environment_has_no_prompt_and_no_optional_lock_and_none_of_the_callers_secrets(self):
        with mock.patch.dict(os.environ, {"SECRET_X": "hunter2"}):
            rc, out, _ = PE.git("e", repo=self.repo, config=("alias.e=!env",))
        self.assertEqual(rc, 0)
        lines = out.splitlines()
        self.assertIn("GIT_TERMINAL_PROMPT=0", lines)
        self.assertIn("GIT_OPTIONAL_LOCKS=0", lines)
        self.assertNotIn("SECRET_X=hunter2", lines)
        rc, out, _ = PE.git("e", repo=self.repo, config=("alias.e=!env",), env={"PATH": "/usr/bin:/bin", "ONLY_THIS": "1"})
        self.assertIn("ONLY_THIS=1", out.splitlines())
        self.assertNotIn("GIT_OPTIONAL_LOCKS=0", out.splitlines())

    def test_a_git_that_cannot_run_or_takes_too_long_has_no_exit_status(self):
        rc, out, err = PE.git("status", env={"PATH": "/nonexistent"})
        self.assertEqual((rc, out), (None, ""))
        self.assertTrue(err)
        rc, out, err = PE.git("s", repo=self.repo, config=("alias.s=!sleep 5",), timeout=0.2)
        self.assertEqual((rc, out), (None, ""))
        self.assertTrue(err)

    def test_env_check_and_tools_keep_their_shapes(self):
        import env_check, tools
        self.assertEqual(env_check.git(self.repo, "rev-parse", "--git-dir"), (0, ".git\n"))
        rc, out = env_check.git(self.repo, "rev-parse", "HEAD")
        self.assertNotEqual(rc, 0)
        with mock.patch.dict(os.environ, {"PATH": "/nonexistent"}):
            self.assertEqual(env_check.git(self.repo, "status"), (1, ""))
            self.assertEqual(tools.git("status", cwd=self.repo)[:2], (1, ""))
            self.assertIs(tools.submodule_state(self.repo, "vendor/x"), False)
        self.assertEqual(tools.git("rev-parse", "--git-dir", cwd=self.repo), (0, ".git", ""))
        gd = os.path.join(self.repo, ".git")
        self.assertEqual(tools.git("rev-parse", "--git-dir", git_dir=gd)[:2], (0, gd))
        self.assertIsNone(tools.submodule_state(self.repo, "vendor/x"))
        self.assertIs(tools.submodule_state(self.t, "vendor/x"), False)       # not a git work tree


def defined_in(name, *funcs):
    """The names of funcs that the source file lib/NAME.py defines at the top level."""
    import ast
    with open(os.path.join(LIB, name + ".py")) as f:
        tree = ast.parse(f.read())
    return sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in funcs)


class NoCopies(unittest.TestCase):
    def test_the_modules_define_no_copy_of_a_shared_helper(self):
        want = {"env_check": ("clean_path", "child_env", "now"), "env_apply": ("clean_path", "now"), "local_run": ("clean_path", "now"),
                "tools": ("clean_path", "now"), "supervise": ("now",), "discover": ("now", "die")}
        for name, funcs in want.items():
            self.assertEqual(defined_in(name, *funcs), [], "lib/%s.py defines its own copy" % name)


class AsScriptAndModule(unittest.TestCase):
    def test_it_does_nothing_when_run(self):
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "procenv.py")], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))

    def test_the_modules_import_it_when_run_as_scripts_and_as_modules(self):
        for name in ("tools", "env_check", "env_apply", "local_run"):
            r = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); import %s; print(%s.PE.clean_path() if hasattr(%s, 'PE') else 'ok')"
                                % (LIB, name, name, name)], capture_output=True, text=True, stdin=subprocess.DEVNULL, env={"PATH": "/usr/bin:/bin"})
            self.assertEqual((r.returncode, r.stderr), (0, ""), name)
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "tools.py"), "checkout"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2, "tools.py as a script finds procenv beside it")
        self.assertNotIn("Traceback", r.stderr)


if __name__ == "__main__":
    unittest.main()
