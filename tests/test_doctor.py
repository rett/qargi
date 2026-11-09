#!/usr/bin/env python3
"""qargi doctor, lib/doctor.py: the read-only check of the host. logind and loginctl are fakes (QARGI_BUSCTL, QARGI_LOGINCTL) that record what they
were asked; the run temporary parent is a directory of the test (QARGI_RUN_TMP), never the real one; the project is invented. Nothing waits for a
fixed time. Offline. Run: python3 tests/test_doctor.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, stat, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import doctor as D  # noqa: E402

BUSCTL = """#!/bin/sh
echo "busctl $*" >> "$FAKE_LOG"
case "$FAKE_IPC" in
  fail) echo "Failed to connect to bus: No such file or directory" >&2; exit 1;;
  garbage) echo "s hello";;
  *) echo "b $FAKE_IPC";;
esac
"""
LOGINCTL = """#!/bin/sh
echo "loginctl $*" >> "$FAKE_LOG"
case "$FAKE_LINGER" in
  fail) echo "Failed to get user: User ID 1 is not logged in or lingering" >&2; exit 1;;
  garbage) echo "Linger=perhaps";;
  *) echo "Linger=$FAKE_LINGER";;
esac
"""
ALLOW_ALL_GUARD = "#!/bin/sh\ncat >/dev/null\nexit 0\n"
ROW = "app  worker  build,write  m/high  /x/worker.md (STALE, DRIFT: qargi agent refresh worker --project app)\napp  reviewer  review  m/high  /x/reviewer.md\n"


def script(path, text):
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, 0o755)
    return path


def tree(path):
    """Everything below path with its type and modification time, to see that nothing changed."""
    out = {}
    for d, ds, fs in os.walk(path):
        for n in ds + fs:
            p = os.path.join(d, n)
            out[p] = (os.path.islink(p), os.lstat(p).st_mtime_ns)
    return out


def snapshot(*paths):
    """Everything below each path (and the path itself, or its absence) with type, mode, size and modification time: what must be the same after a read."""
    out = {}
    for top in paths:
        if not os.path.lexists(top):
            out[top] = None
            continue
        for d, ds, fs in os.walk(top):
            for n in [""] + ds + fs:
                p = os.path.join(d, n) if n else d
                st = os.lstat(p)
                out[p] = (stat.S_IFMT(st.st_mode), stat.S_IMODE(st.st_mode), st.st_size, st.st_mtime_ns)
    return out


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="doctor.")
        self.fakes = os.path.join(self.t, "fakes")
        self.shm = os.path.join(self.t, "shm")
        for d in (self.fakes, self.shm, os.environ["QARGI_CONF"] + "/projects"):
            os.makedirs(d, exist_ok=True)
        self.log = os.path.join(self.t, "calls.log")
        open(self.log, "w").close()
        script(os.path.join(self.fakes, "busctl"), BUSCTL)
        script(os.path.join(self.fakes, "loginctl"), LOGINCTL)
        os.symlink(BIN, os.path.join(self.fakes, "qargi"))                    # the guard a member calls from PATH is this checkout's
        self.env = dict(os.environ, PATH=self.fakes + os.pathsep + os.environ["PATH"], FAKE_LOG=self.log, FAKE_IPC="false", FAKE_LINGER="no",
                        QARGI_BUSCTL=os.path.join(self.fakes, "busctl"), QARGI_LOGINCTL=os.path.join(self.fakes, "loginctl"),
                        QARGI_RUN_TMP=self.shm, QARGI_DOCTOR_MIN_FREE="0")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)
        p = os.path.join(os.environ["QARGI_CONF"], "projects", "app.json")
        if os.path.exists(p):
            os.remove(p)

    def doctor(self, *args, **env):
        e = dict(self.env, **env)
        r = subprocess.run([BIN, "doctor", *args], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)
        return r.returncode, r.stdout, r.stderr

    def lines(self, out):
        """{check name: (status, whole text of the check with its fix lines)}"""
        found, cur = {}, None
        for line in out.splitlines():
            if line.startswith("    "):
                found[cur] = (found[cur][0], found[cur][1] + "\n" + line)
                continue
            status, rest = line.split("  ", 1)
            cur = rest.split(":", 1)[0]
            found[cur] = (status, line)
        return found

    def project(self, **answers):
        a = {"schema": 1, "project": "app", "repo": {"url": "https://example.net/acme/app", "path": ""}, "models": {"provider": {"local": "claude-code"}}, "roles": {}}
        a.update(answers)
        with open(os.path.join(os.environ["QARGI_CONF"], "projects", "app.json"), "w") as f:
            json.dump(a, f)

    def orphan(self, name, days_old, link=False):
        p = os.path.join(self.shm, "qargi-run." + name)
        if link:
            os.symlink(self.t, p)
            return p
        os.makedirs(p)
        with open(os.path.join(p, "f"), "w") as f:
            f.write("x")
        subprocess.run(["touch", "-d", "%d days ago" % days_old, os.path.join(p, "f"), p], check=True)
        return p


class RemoveIpc(Base):
    def test_the_matrix(self):
        for ipc, linger, status in (("false", "no", "ok"), ("true", "yes", "ok"), ("true", "no", "warn")):
            rc, out, _ = self.doctor(FAKE_IPC=ipc, FAKE_LINGER=linger)
            self.assertEqual(rc, 0, out)
            self.assertEqual(self.lines(out)["remove-ipc"][0], status, "%s %s: %s" % (ipc, linger, out))

    def test_a_warning_prints_the_fix_and_runs_nothing(self):
        rc, out, _ = self.doctor(FAKE_IPC="true", FAKE_LINGER="no")
        text = self.lines(out)["remove-ipc"][1]
        for want in ("/etc/systemd/logind.conf.d/remove-ipc.conf", "[Login]", "RemoveIPC=no", "sudo systemctl reload systemd-logind", "loginctl enable-linger"):
            self.assertIn(want, text)
        with open(self.log) as f:
            calls = f.read().splitlines()
        user = D.user_name()
        self.assertEqual(calls, ["busctl get-property org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager RemoveIPC",
                                 "loginctl show-user %s -p Linger" % user])

    def test_loginctl_is_asked_only_when_remove_ipc_is_on(self):
        self.doctor(FAKE_IPC="false")
        with open(self.log) as f:
            self.assertEqual(len(f.read().splitlines()), 1)

    def test_what_cannot_be_read_is_unknown_never_a_warning(self):
        cases = [dict(FAKE_IPC="fail"), dict(FAKE_IPC="garbage"), dict(FAKE_IPC="true", FAKE_LINGER="fail"), dict(FAKE_IPC="true", FAKE_LINGER="garbage"),
                 dict(QARGI_BUSCTL=os.path.join(self.t, "no-such-busctl")), dict(FAKE_IPC="true", QARGI_LOGINCTL=os.path.join(self.t, "no-such-loginctl"))]
        for env in cases:
            rc, out, _ = self.doctor("--strict", **env)
            self.assertEqual(self.lines(out)["remove-ipc"][0], "unknown", "%s: %s" % (env, out))
            self.assertEqual(rc, 0, "%s: an unknown check does not make --strict fail: %s" % (env, out))


class Guard(Base):
    def test_the_guard_of_this_checkout_answers(self):
        rc, out, _ = self.doctor()
        self.assertEqual(self.lines(out)["guard"][0], "ok", out)
        self.assertIn("refuses git push", out)

    def test_qargi_missing_from_path_warns_with_the_fix(self):
        with mock.patch.object(D.shutil, "which", return_value=None):
            c = D.check_guard(None)
        self.assertEqual(c["status"], "warn")
        self.assertIn("not on PATH", c["detail"])
        self.assertTrue(c["fix"])

    def test_a_hook_that_allows_everything_warns(self):
        d = os.path.join(self.t, "lax")
        os.makedirs(d)
        script(os.path.join(d, "qargi"), ALLOW_ALL_GUARD)
        with mock.patch.dict(os.environ, {"PATH": d}):
            c = D.check_guard(None)
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("git push: exit status 0, wanted 2", c["detail"])

    def test_stale_members_of_the_project_warn_and_name_the_fix(self):
        real = D.run

        def fake(argv, **kw):
            if "agent" in argv:
                self.assertEqual(argv[-3:], ["list", "--project", "app"])
                return 0, ROW, ""
            return real(argv, **kw)
        with mock.patch.dict(os.environ, {"PATH": self.fakes + os.pathsep + os.environ["PATH"]}), mock.patch.object(D, "run", fake):
            c = D.check_guard("app")
        self.assertEqual(c["status"], "warn", c)
        self.assertIn("worker STALE+DRIFT", c["detail"])
        self.assertNotIn("reviewer", c["detail"])
        self.assertEqual(c["fix"], ["fix: qargi agent refresh worker --project app"])

    def test_members_that_are_current_are_ok(self):
        real = D.run
        fake = lambda argv, **kw: (0, "app  worker  build  m/high  /x/w.md\n", "") if "agent" in argv else real(argv, **kw)  # noqa: E731
        with mock.patch.dict(os.environ, {"PATH": self.fakes + os.pathsep + os.environ["PATH"]}), mock.patch.object(D, "run", fake):
            c = D.check_guard("app")
        self.assertEqual(c["status"], "ok", c)
        self.assertIn("are current", c["detail"])


class Shm(Base):
    def test_an_empty_parent_is_ok(self):
        rc, out, _ = self.doctor()
        self.assertEqual(self.lines(out)["shm"][0], "ok", out)
        self.assertIn("0 orphaned", out)

    def test_an_old_unnamed_directory_is_an_orphan_and_nothing_is_removed(self):
        a, b = self.orphan("AAAAAA", 5), self.orphan("BBBBBB", 3)
        new, link = self.orphan("NEWNEW", 0), self.orphan("LINKED", 0, link=True)
        named = self.orphan("NAMED1", 9)
        os.makedirs(os.environ["QARGI_STATE"], exist_ok=True)
        with open(os.path.join(os.environ["QARGI_STATE"], "local-runs.jsonl"), "w") as f:
            f.write(json.dumps({"run": os.path.join(self.t, "run-gone"), "tmpdir": named}) + "\n")
        before = tree(self.shm)
        rc, out, _ = self.doctor()
        st, text = self.lines(out)["shm"]
        self.assertEqual((rc, st), (0, "warn"), out)
        self.assertIn("2 orphaned", text)
        self.assertIn("qargi local clean --orphans", text)
        self.assertEqual(tree(self.shm), before, "doctor removed or touched something")
        for p in (a, b, new, link, named):
            self.assertTrue(os.path.lexists(p), p)

    def test_the_count_is_the_listing_of_clean_orphans(self):
        self.orphan("AAAAAA", 5)
        self.orphan("FRESHF", 5)
        with open(os.path.join(self.shm, "qargi-run.FRESHF", "g"), "w") as f:                    # an old directory with a file that is new: kept
            f.write("new")
        r = subprocess.run([BIN, "local", "clean", "--orphans"], capture_output=True, text=True, env=self.env)
        self.assertEqual(sum(1 for line in r.stdout.splitlines() if line.startswith("orphan ")), 1, r.stdout)
        self.assertIn("1 orphaned", self.doctor()[1])

    def test_little_free_space_warns(self):
        rc, out, _ = self.doctor(QARGI_DOCTOR_MIN_FREE="101")
        st, text = self.lines(out)["shm"]
        self.assertEqual(st, "warn", out)
        self.assertIn("less than 101% is free", text)

    def test_the_default_limit_is_ten_percent(self):
        class St:
            f_frsize, f_blocks, f_bavail = 1024, 1000, 99
        env = {k: v for k, v in os.environ.items() if k != "QARGI_DOCTOR_MIN_FREE"}
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.dict(os.environ, {"QARGI_RUN_TMP": self.shm}), mock.patch.object(D.os, "statvfs", return_value=St):
            low = D.check_shm()
            St.f_bavail = 100
            enough = D.check_shm()
        self.assertEqual((low["status"], enough["status"]), ("warn", "ok"), (low, enough))

    def test_a_parent_that_is_not_a_directory_is_unknown(self):
        rc, out, _ = self.doctor(QARGI_RUN_TMP=os.path.join(self.t, "nowhere"))
        self.assertEqual(self.lines(out)["shm"][0], "unknown", out)


class WindowSource(Base):
    def test_no_project_is_unknown(self):
        rc, out, _ = self.doctor()
        self.assertEqual(self.lines(out)["window-source"][0], "unknown", out)

    def test_ids_in_the_table_are_ok_and_the_source_is_named(self):
        self.project(roles={"build": {"model": "model-a-1m"}, "review": {"model": "model-b[1m]"}})
        rc, out, _ = self.doctor("app")
        st, text = self.lines(out)["window-source"]
        self.assertEqual(st, "ok", out)
        self.assertIn("table of claude-code (shipped, lib/providers/claude-code.json): 2 entries, 200,000 assumed otherwise", text)
        self.assertIn("2 model ids checked", text)

    def test_an_id_that_is_not_in_the_table_warns(self):
        self.project(roles={"build": {"model": "model-a-1m"}, "write": {"model": "plain-model"}, "test": {"model": None}})
        rc, out, _ = self.doctor("app")
        st, text = self.lines(out)["window-source"]
        self.assertEqual((rc, st), (0, "warn"), out)
        self.assertIn("not in the table: plain-model", text)
        self.assertNotIn("model-a-1m (", text)
        self.assertEqual(self.doctor("app", "--strict")[0], 1)

    def test_the_answer_overrides_the_table(self):
        self.project(roles={"write": {"model": "plain-model"}}, lead={"context_window": 300000})
        st, text = self.lines(self.doctor("app")[1])["window-source"]
        self.assertEqual(st, "ok", text)
        self.assertIn("answer lead.context_window = 300,000 overrides", text)

    def test_no_model_id_is_ok(self):
        self.project(roles={"build": {"model": None}})
        st, text = self.lines(self.doctor("app")[1])["window-source"]
        self.assertEqual(st, "ok", text)
        self.assertIn("no role names a model id", text)

    def test_a_project_without_a_runtime_is_unknown(self):
        self.project(models={"provider": ""})
        self.assertEqual(self.lines(self.doctor("app")[1])["window-source"][0], "unknown")

    def test_project_option_is_the_same_as_the_argument(self):
        self.project(roles={"write": {"model": "plain-model"}})
        self.assertEqual(self.lines(self.doctor("--project", "app")[1])["window-source"][0], "warn")

    def test_the_project_in_effect_is_used(self):
        self.project(roles={"write": {"model": "plain-model"}})
        rc, out, _ = self.doctor(QARGI_PROJECT="app")
        self.assertEqual(self.lines(out)["window-source"][0], "warn", out)


class Command(Base):
    def test_the_lines_are_status_name_detail_and_exit_is_zero(self):
        rc, out, err = self.doctor()
        self.assertEqual(rc, 0, err)
        for name in ("remove-ipc", "guard", "shm", "window-source"):
            self.assertIn(name, self.lines(out))
        for line in out.splitlines():
            if not line.startswith("    "):
                self.assertRegex(line, r"^(ok|warn|unknown)  [a-z-]+: ")

    def test_strict_exits_one_on_a_warning_only(self):
        self.assertEqual(self.doctor("--strict")[0], 0)
        self.assertEqual(self.doctor("--strict", FAKE_IPC="true")[0], 1)
        self.assertEqual(self.doctor(FAKE_IPC="true")[0], 0)

    def test_json(self):
        rc, out, _ = self.doctor("--json", "--strict", FAKE_IPC="true")
        doc = json.loads(out)
        self.assertEqual((rc, doc["exit"], doc["warnings"], doc["strict"]), (1, 1, 1, True))
        self.assertEqual([c["name"] for c in doc["checks"]], ["remove-ipc", "guard", "shm", "window-source"])
        ipc = doc["checks"][0]
        self.assertEqual(ipc["status"], "warn")
        self.assertTrue(any("RemoveIPC=no" in line for line in ipc["fix"]))

    def test_usage_errors_exit_two(self):
        for args in (["--bogus"], ["a", "b"], ["no-such-project"], ["--project"], ["--project", "no-such-project"]):
            rc, out, err = self.doctor(*args)
            self.assertEqual(rc, 2, (args, out, err))
            self.assertEqual(out, "")

    def test_nothing_is_written_to_the_run_parent_or_the_log(self):
        self.orphan("AAAAAA", 5)
        before = tree(self.shm)
        self.doctor("--json")
        self.assertEqual(tree(self.shm), before)
        self.assertFalse(os.path.exists(os.path.join(os.environ["QARGI_STATE"], "audit.log")))

    def test_nothing_is_created_or_changed_on_a_host_that_never_ran_qargi(self):
        """The data directories of qargi are absent (as on a new host): doctor makes none of them, nor their files, and does not change the mode of anything."""
        home = os.path.join(self.t, "home")
        os.makedirs(home)
        conf, state = os.path.join(self.t, "d", "conf"), os.path.join(self.t, "d", "state")
        self.orphan("AAAAAA", 5)                                  # the orphan scan reads the registry of the state directory, which is not there
        for args in ((), ("--json",)):
            before = snapshot(home, conf, state, os.path.join(self.t, "d"))
            rc, out, err = self.doctor(*args, HOME=home, QARGI_CONF=conf, QARGI_STATE=state)
            self.assertEqual(rc, 0, out + err)
            self.assertIn("qargi-run", out)                           # the scan did run
            self.assertEqual(snapshot(home, conf, state, os.path.join(self.t, "d")), before, args)
        self.assertFalse(os.path.lexists(conf) or os.path.lexists(state))

    def test_nothing_is_created_in_the_home_when_no_location_is_named(self):
        """Without QARGI_CONF, QARGI_STATE and QARGI_HOME the data is under HOME/.qargi: doctor leaves HOME as it was (no .qargi, no chmod of it)."""
        home = os.path.join(self.t, "home")
        os.makedirs(home)
        env = {k: v for k, v in self.env.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME")}
        env["HOME"] = home
        self.orphan("AAAAAA", 5)
        before = snapshot(home)
        r = subprocess.run([BIN, "doctor"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("qargi-run", r.stdout)
        self.assertEqual(snapshot(home), before)
        self.assertFalse(os.path.lexists(os.path.join(home, ".qargi")))

    def test_the_conf_and_state_directories_are_left_as_they_are_with_a_project(self):
        """A project is named and the directories exist with modes qargi would not set (755), with a members file but no registry: nothing is created, no mode changes."""
        conf, state = os.environ["QARGI_CONF"], os.environ["QARGI_STATE"]
        os.makedirs(state, exist_ok=True)
        for d in (conf, state):
            os.chmod(d, 0o755)
        self.project()
        with open(os.path.join(conf, "agents.json"), "w") as f:
            json.dump({"schema": 2, "projects": {"app": {}}}, f)
        os.chmod(os.path.join(conf, "agents.json"), 0o644)
        self.orphan("AAAAAA", 5)
        before = snapshot(conf, state, os.environ["HOME"])
        for args in (("app",), ("app", "--json")):
            rc, out, err = self.doctor(*args)
            self.assertEqual(rc, 0, out + err)
            if "--json" not in args:
                self.assertEqual(self.lines(out)["guard"][0], "ok", out)    # the members were read (none)
            self.assertEqual(snapshot(conf, state, os.environ["HOME"]), before, args)

    def test_a_project_on_a_host_with_no_members_file_makes_none(self):
        """No agents.json: no member is recorded on this host, which the member check says (ok), not that the members could not be read; the file is not made by asking."""
        self.project()
        conf = os.environ["QARGI_CONF"]
        self.assertFalse(os.path.exists(os.path.join(conf, "agents.json")))
        rc, out, err = self.doctor("app")
        self.assertEqual(rc, 0, out + err)
        status, text = self.lines(out)["guard"]
        self.assertEqual(status, "ok", out)
        self.assertIn("no member is recorded on this host", text, out)
        self.assertNotIn("could not be read", out)
        rc, out, err = self.doctor("app", "--json")
        self.assertEqual(rc, 0, out + err)
        self.assertIn("no member is recorded on this host", out)
        self.assertNotIn("could not be read", out)
        self.assertFalse(os.path.exists(os.path.join(conf, "agents.json")))
        self.assertFalse(os.path.exists(os.path.join(conf, "instances.json")))

    def test_help_describes_it(self):
        r = subprocess.run([BIN, "doctor", "--help"], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0)
        for word in ("--strict", "--json", "QARGI_BUSCTL", "RemoveIPC", "remove-ipc.conf"):
            self.assertIn(word, " ".join(r.stdout.split()), word)


if __name__ == "__main__":
    unittest.main()
