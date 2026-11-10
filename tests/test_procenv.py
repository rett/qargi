#!/usr/bin/env python3
"""lib/procenv.py: the helpers several modules share to start a child process (clean_path, child_env) and the modules that use them
(lib/env_check.py, lib/env_apply.py, lib/local_run.py, lib/tools.py). Offline; no project, no network.
Run: python3 tests/test_procenv.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import os, subprocess, sys, time, unittest
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


def defined_in(name, *funcs):
    """The names of funcs that the source file lib/NAME.py defines at the top level."""
    import ast
    with open(os.path.join(LIB, name + ".py")) as f:
        tree = ast.parse(f.read())
    return sorted(n.name for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in funcs)


class NoCopies(unittest.TestCase):
    def test_the_modules_define_no_copy_of_a_shared_helper(self):
        want = {"env_check": ("clean_path", "child_env", "now"), "env_apply": ("clean_path", "now"), "local_run": ("clean_path", "now"),
                "tools": ("clean_path", "now"), "supervise": ("now",), "discover": ("now",)}
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
