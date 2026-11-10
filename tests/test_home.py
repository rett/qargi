#!/usr/bin/env python3
"""Where qargi keeps its data: the resolver (lib/paths.py and lib/lib.sh), installed and dev runs, and
the install record install.sh writes. Every run uses a temporary HOME; nothing here touches the real directories."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLEAN = ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_DATA_HOME", "QARGI_PROJECT", "QARGI_NESTED")
BANNER = "qargi: dev run from %s; data in %s/.qargi (QARGI_HOME=~/.qargi uses live data)"


def slurp(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.t, "home")
        os.makedirs(self.home)
        self.env = {k: v for k, v in os.environ.items() if k not in CLEAN}
        self.env["HOME"] = self.home
        self.live = os.path.join(self.home, ".qargi")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def tool(self, name):
        """A copy of the tool under the temp dir: a checkout of its own, with its own real path."""
        d = os.path.join(self.t, name)
        os.makedirs(d)
        for part in ("bin", "lib"):
            shutil.copytree(os.path.join(ROOT, part), os.path.join(d, part), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(os.path.join(ROOT, "VERSION"), d)
        return d

    def run_(self, argv, input=None, **env):
        e = dict(self.env, **env)
        e = {k: v for k, v in e.items() if v is not None}
        return subprocess.run(argv, capture_output=True, text=True, env=e, input=input, stdin=None if input is not None else subprocess.DEVNULL)

    def q(self, tool, *a, **env):
        return self.run_([os.path.join(tool, "bin", "qargi"), *a], **env)

    def where(self, tool, **env):
        """(python, shell) answers to 'where are config and state', from the tool's own copy of each resolver."""
        py = self.run_(["python3", "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import paths as P; print(P.conf(), P.state(), P.dev_run())",
                        os.path.join(tool, "lib")], **env)
        sh = self.run_(["bash", "-c", '. "$1"; echo "$DA_CONF $DA_STATE"', "bash", os.path.join(tool, "lib", "lib.sh")], **env)
        self.assertEqual(py.returncode, 0, py.stderr)
        self.assertEqual(sh.returncode, 0, sh.stderr)
        pc, ps, dev = py.stdout.split()
        self.assertEqual((pc, ps), tuple(sh.stdout.split()), "the Python and shell resolvers disagree")
        return pc, ps, dev == "True"

    def install_record(self, tool_root, home=None):
        d = os.path.join(home or self.live, "config")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "install.json"), "w") as f:
            json.dump({"tool_root": tool_root, "installed_at": "2026-01-01T00:00:00Z", "version": "0"}, f)

    def snapshot(self, path):
        return sorted(os.path.relpath(os.path.join(d, n), path) for d, ds, fs in os.walk(path) for n in ds + fs
                      if "__pycache__" not in d and n != "__pycache__")      # bytecode is ignored by version control, and absent when the tool is read-only


class Resolver(Base):
    def test_default_is_under_the_home(self):
        self.assertEqual(self.where(ROOT), (self.live + "/config", self.live + "/state", False))

    def test_precedence_conf_state_then_qargi_home_then_default(self):
        qh = os.path.join(self.t, "qh")
        self.assertEqual(self.where(ROOT, QARGI_HOME=qh), (qh + "/config", qh + "/state", False))
        c, s = os.path.join(self.t, "c"), os.path.join(self.t, "s")
        self.assertEqual(self.where(ROOT, QARGI_HOME=qh, QARGI_CONF=c), (c, qh + "/state", False))
        self.assertEqual(self.where(ROOT, QARGI_HOME=qh, QARGI_STATE=s), (qh + "/config", s, False))
        self.assertEqual(self.where(ROOT, QARGI_HOME=qh, QARGI_CONF=c, QARGI_STATE=s), (c, s, False))
        self.assertEqual(self.where(ROOT, QARGI_CONF=c, QARGI_STATE=s), (c, s, False))

    def test_xdg_variables_do_not_move_the_data(self):
        r = self.where(ROOT, XDG_CONFIG_HOME=os.path.join(self.t, "x1"), XDG_STATE_HOME=os.path.join(self.t, "x2"))
        self.assertEqual(r, (self.live + "/config", self.live + "/state", False))
        self.assertFalse(os.path.exists(os.path.join(self.t, "x1")))

    def test_first_use_creates_the_root_privately(self):
        r = self.q(ROOT, "project", "list")
        self.assertEqual(r.returncode, 0, r.stderr)
        for d in ("", "/config", "/state"):
            self.assertEqual(stat.S_IMODE(os.stat(self.live + d).st_mode), 0o700, d)
        self.assertTrue(os.path.isfile(self.live + "/config/instances.json"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".config")), "the XDG location was used")

    def test_xdg_directories_that_exist_are_not_data(self):
        os.makedirs(os.path.join(self.home, ".config", "qargi"))
        os.makedirs(os.path.join(self.home, ".local", "state", "qargi"))
        r = self.q(ROOT, "project", "list")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(os.path.isdir(self.live + "/config"), "the new root was not created beside them")


class DevRun(Base):
    def setUp(self):
        super().setUp()
        self.inst, self.dev = self.tool("installed"), self.tool("branch")
        self.install_record(self.inst)

    def test_detection_compares_real_paths(self):
        self.assertEqual(self.where(self.inst), (self.live + "/config", self.live + "/state", False))
        self.assertEqual(self.where(self.dev), (self.dev + "/.qargi/config", self.dev + "/.qargi/state", True))
        self.assertEqual(self.where(self.inst, QARGI_HOME=self.live), (self.live + "/config", self.live + "/state", False))
        # a record that names the tool through a link is still the same tool
        link = os.path.join(self.t, "link-to-installed")
        os.symlink(self.inst, link)
        self.install_record(link)
        self.assertEqual(self.where(self.inst)[2], False)
        self.assertEqual(self.where(self.dev)[2], True)
        # and so is an invocation through a link
        bin_link = os.path.join(self.t, "qargi-link")
        os.symlink(os.path.join(self.inst, "bin", "qargi"), bin_link)
        r = self.run_([bin_link, "project", "list"])
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        bin_link2 = os.path.join(self.t, "qargi-link2")
        os.symlink(os.path.join(self.dev, "bin", "qargi"), bin_link2)
        r = self.run_([bin_link2, "project", "list"])
        self.assertEqual(r.stderr.strip(), BANNER % (self.dev, self.dev))

    def test_a_dev_run_keeps_its_data_in_the_checkout_and_says_so_on_stderr_once(self):
        before = self.snapshot(self.live)
        r = self.q(self.dev, "project", "list")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.strip().splitlines(), [BANNER % (self.dev, self.dev)])
        self.assertTrue(os.path.isfile(self.dev + "/.qargi/config/instances.json"))
        self.assertTrue(os.path.isdir(self.dev + "/.qargi/state"))
        self.assertEqual(self.snapshot(self.dev), sorted([".qargi", ".qargi/config", ".qargi/config/agents.json", ".qargi/config/instances.json",
                                                         ".qargi/state", ".qargi/state/sessions.json", "bin", "bin/qargi", "lib", "VERSION"] +
                                                        [os.path.relpath(os.path.join(d, n), self.dev) for d, ds, fs in os.walk(os.path.join(self.dev, "lib")) if "__pycache__" not in d for n in ds + fs if n != "__pycache__"]), "a dev run wrote outside .qargi")
        self.assertEqual([p for p in self.snapshot(self.live) if p not in before], [], "a dev run touched live data")
        self.assertEqual(r.stdout, self.q(self.inst, "project", "list").stdout)

    def test_the_installed_run_is_silent_and_uses_live_data(self):
        r = self.q(self.inst, "project", "list")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertTrue(os.path.isfile(self.live + "/config/instances.json"))
        self.assertFalse(os.path.exists(self.inst + "/.qargi"), "an installed run wrote into the tool directory")

    def test_no_install_record_means_the_checkout_behaves_as_installed(self):
        os.remove(self.live + "/config/install.json")
        self.assertEqual(self.where(self.dev), (self.live + "/config", self.live + "/state", False))
        r = self.q(self.dev, "project", "list")
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertFalse(os.path.exists(self.dev + "/.qargi"))
        with open(self.live + "/config/install.json", "w") as f:       # a record that cannot be read is no record
            f.write("not json")
        self.assertEqual(self.where(self.dev)[2], False)

    def test_an_explicit_location_overrides_the_sandbox_even_live_data(self):
        for env, want in ((dict(QARGI_HOME=self.live), self.live + "/config"), (dict(QARGI_HOME=os.path.join(self.t, "qh")), os.path.join(self.t, "qh/config")),
                          (dict(QARGI_CONF=os.path.join(self.t, "c")), os.path.join(self.t, "c"))):
            self.assertEqual(self.where(self.dev, **env)[0], want, env)
            r = self.q(self.dev, "project", "list", **env)
            self.assertEqual((r.returncode, r.stderr), (0, ""), env)
        self.assertFalse(os.path.exists(self.dev + "/.qargi"))
        r = self.q(self.dev, "project", "list", QARGI_STATE=os.path.join(self.t, "s"))
        self.assertEqual((r.returncode, r.stderr), (0, ""))

    def test_no_banner_for_help_version_completion_guard_and_hooks(self):
        for argv in (("help",), ("help", "dev"), ("version",), ("__complete", "project"), ("project", "--help"), ("hook", "tool-use")):
            r = self.run_([os.path.join(self.dev, "bin", "qargi"), *argv], input="{}")
            self.assertEqual(r.returncode, 0, argv)
            # the banner is a line of its own on stderr; the text of `help dev` quotes it inside a sentence, wrapped to the width of the terminal
            self.assertNotIn("qargi: dev run from", r.stderr, argv)
            self.assertEqual([l for l in r.stdout.splitlines() if l.startswith("qargi: dev run from")], [], argv)
        r = self.run_([os.path.join(self.dev, "bin", "qargi"), "__guard"], input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}}))
        self.assertEqual((r.returncode, r.stderr, r.stdout), (0, "", ""))
        self.assertFalse(os.path.exists(self.dev + "/.qargi/config"), "help, the guard or a hook created the sandbox config")

    def test_the_guard_of_a_dev_run_protects_the_live_library_and_its_own(self):
        for lib in (self.live + "/config/packs", self.dev + "/.qargi/config/packs"):
            os.makedirs(lib)
            r = self.run_([os.path.join(self.dev, "bin", "qargi"), "__guard"], input=json.dumps(
                {"tool_name": "Write", "tool_input": {"file_path": lib + "/links.json"}, "cwd": self.t}))
            self.assertEqual(r.returncode, 2, (lib, r.stderr))

    def test_the_sandbox_is_ignored_by_version_control(self):
        with open(os.path.join(ROOT, ".gitignore")) as f:
            self.assertIn(".qargi/", f.read().split())


class Install(Base):
    def install(self, *a, **env):
        return self.run_(["bash", os.path.join(ROOT, "install.sh"), *a], **env)

    def record(self, base=None):
        with open(os.path.join(base or self.live, "config", "install.json")) as f:
            return json.load(f)

    def test_user_install_records_the_checkout(self):
        r = self.install("--user")
        self.assertEqual(r.returncode, 0, r.stderr)
        rec = self.record()
        self.assertEqual(rec["tool_root"], ROOT)
        self.assertEqual(rec["version"], slurp(os.path.join(ROOT, "VERSION")).strip())
        self.assertRegex(rec["installed_at"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertEqual(stat.S_IMODE(os.stat(self.live + "/config/install.json").st_mode), 0o600)
        self.assertEqual(self.where_installed(), False)

    def where_installed(self):
        return subprocess.run(["python3", "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import paths as P; print(P.dev_run())", os.path.join(ROOT, "lib")],
                              capture_output=True, text=True, env=self.env).stdout.strip() == "True"

    def test_copy_install_records_the_copied_tool(self):
        r = self.install("--user", "--copy")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["tool_root"], os.path.join(self.home, ".local", "share", "qargi"))
        r = self.install("--user", "--copy", "--force", XDG_DATA_HOME=os.path.join(self.t, "data"))
        self.assertEqual(self.record()["tool_root"], os.path.join(self.t, "data", "qargi"))
        self.assertTrue(self.where_installed(), "the checkout is a dev run once the copy is the installed tool")

    def test_a_second_install_replaces_the_record_and_uninstall_removes_it(self):
        self.install("--user", "--copy")
        self.assertEqual(self.install("--user", "--force").returncode, 0)
        self.assertEqual(self.record()["tool_root"], ROOT)
        r = self.install("--user", "--uninstall")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.live + "/config/install.json"))

    def test_a_project_install_writes_only_its_manifest(self):
        # the live location gets the project's install manifest and nothing else: no install.json, so no run turns into a dev run
        proj = os.path.join(self.t, "proj")
        os.makedirs(proj)
        r = self.install("--project", proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        written = [os.path.relpath(os.path.join(d, f), self.live) for d, _, fs in os.walk(self.live) for f in fs]
        self.assertEqual(len(written), 1, written)
        self.assertRegex(written[0], r"^config/project-\d+\.manifest$")
        self.assertEqual(self.where_installed(), False)
        self.assertEqual(self.install("--project", proj, "--uninstall").returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.live, written[0])), "the project uninstall removes its manifest")
        self.install("--project", proj)
        self.install("--user")
        before = slurp(self.live + "/config/install.json")
        self.assertEqual(self.install("--project", proj, "--uninstall").returncode, 0)
        self.assertEqual(slurp(self.live + "/config/install.json"), before)

    def test_the_record_goes_to_the_live_location_that_is_named(self):
        qh = os.path.join(self.t, "qh")
        self.assertEqual(self.install("--user", QARGI_HOME=qh).returncode, 0)
        self.assertEqual(self.record(qh)["tool_root"], ROOT)
        self.assertFalse(os.path.lexists(self.live))
        c = os.path.join(self.t, "c")
        self.assertEqual(self.install("--user", QARGI_CONF=c).returncode, 0)
        self.assertTrue(os.path.isfile(c + "/install.json"))

    def test_the_earlier_xdg_directories_do_not_hold_the_record_back(self):
        os.makedirs(os.path.join(self.home, ".config", "qargi"))
        r = self.install("--user")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.record()["tool_root"], ROOT)


class RecordedToolRoot(Base):
    """paths.installed_tool_root reads install.json once while it is unchanged (the guard asks it dozens of times in one call) and returns
    what it always did: the real path of the recorded tool root, or None."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, os.path.join(ROOT, "lib"))
        import paths
        self.paths = paths
        self.conf = os.path.join(self.t, "conf")
        os.makedirs(self.conf)
        self.rec = os.path.join(self.conf, "install.json")
        self.tool_dir = os.path.join(self.t, "tool")
        os.makedirs(self.tool_dir)
        self.link = os.path.join(self.t, "link")
        os.symlink(self.tool_dir, self.link)
        old = {k: os.environ.get(k) for k in CLEAN + ("HOME",)}
        self.addCleanup(lambda: [os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v) for k, v in old.items()])
        for k in CLEAN:
            os.environ.pop(k, None)
        os.environ.update(HOME=self.home, QARGI_CONF=self.conf)

    def write(self, doc):
        with open(self.rec, "w") as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))

    def reads(self, n=5):
        """The answers of n calls, and how many times the file was opened for them."""
        import builtins
        real, opened = builtins.open, []

        def counting(p, *a, **k):
            if str(p).endswith("install.json"):
                opened.append(p)
            return real(p, *a, **k)
        builtins.open = counting
        try:
            got = [self.paths.installed_tool_root() for _ in range(n)]
        finally:
            builtins.open = real
        return got, len(opened)

    def test_it_reads_the_record_once_and_returns_the_real_path(self):
        self.write({"tool_root": self.link})
        got, opened = self.reads()
        self.assertEqual(got, [self.tool_dir] * 5)                   # the link is resolved, as before
        self.assertEqual(opened, 1)
        self.assertEqual(self.reads(3), ([self.tool_dir] * 3, 0))     # nothing changed: not read again

    def test_a_changed_removed_or_moved_record_is_seen_at_once(self):
        self.assertEqual(self.reads(2), ([None, None], 0))            # no record
        self.write({"tool_root": self.tool_dir})
        self.assertEqual(self.reads(2)[0], [self.tool_dir] * 2)
        other = os.path.join(self.t, "other")
        os.makedirs(other)
        self.write({"tool_root": other})                              # rewritten in place (a different size)
        self.assertEqual(self.reads(2)[0], [other] * 2)
        self.write({"tool_root": self.tool_dir})                      # rewritten with the same size is a new mtime/ctime
        self.assertEqual(self.reads(2)[0], [self.tool_dir] * 2)
        os.remove(self.rec)
        self.assertEqual(self.reads(2), ([None, None], 0))
        self.write("{not json")                                       # unreadable: None, and read again each time (nothing is kept for it)
        self.assertEqual(self.reads(2), ([None, None], 2))
        self.write({"tool_root": ""})
        self.assertEqual(self.reads(1)[0], [None])
        self.write([1])
        self.assertEqual(self.reads(1)[0], [None])
        self.write({"tool_root": self.tool_dir})
        moved = os.path.join(self.t, "conf2")                         # another configuration directory is another record
        os.makedirs(moved)
        os.environ["QARGI_CONF"] = moved
        self.assertEqual(self.reads(2), ([None, None], 0))
        os.environ["QARGI_CONF"] = self.conf
        self.assertEqual(self.reads(2)[0], [self.tool_dir] * 2)

    def test_what_follows_from_it_is_unchanged(self):
        """dev_run compares the record with this checkout; a record for another checkout makes this one a dev run until it changes."""
        self.write({"tool_root": os.path.join(self.t, "elsewhere")})
        os.environ.pop("QARGI_CONF")
        os.environ["HOME"] = self.home
        os.makedirs(os.path.join(self.home, ".qargi", "config"))
        self.rec = os.path.join(self.home, ".qargi", "config", "install.json")
        self.write({"tool_root": os.path.join(self.t, "elsewhere")})
        self.assertTrue(self.paths.dev_run())
        self.write({"tool_root": self.paths.tool_root()})
        self.assertFalse(self.paths.dev_run())


if __name__ == "__main__":
    unittest.main()
