#!/usr/bin/env python3
"""qargi migrate home: the copy from the XDG directories to ~/.qargi. Every test runs under a temporary HOME."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, shutil, stat, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import migrate_home as MH  # noqa: E402

CLEAN = ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "QARGI_PROJECT", "QARGI_NESTED")


def tree(path):
    """{relative path: (kind, mode, sha256 or link target)} of a directory, links not followed."""
    out = {}
    for d, dirs, files in os.walk(path):
        for n in dirs + files:
            p = os.path.join(d, n)
            st = os.lstat(p)
            rel = os.path.relpath(p, path)
            if stat.S_ISLNK(st.st_mode):
                out[rel] = ("link", os.readlink(p))
            elif stat.S_ISDIR(st.st_mode):
                out[rel] = ("dir", stat.S_IMODE(st.st_mode))
            else:
                with open(p, "rb") as f:
                    out[rel] = ("file", stat.S_IMODE(st.st_mode), hashlib.sha256(f.read()).hexdigest())
    return out


class Home(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.t, "home")
        self.oc, self.os_ = (os.path.join(self.home, ".config", "qargi"), os.path.join(self.home, ".local", "state", "qargi"))
        self.new = os.path.join(self.home, ".qargi")
        for d in ("projects", "credentials", "packs/skills/s", "profiles"):
            os.makedirs(os.path.join(self.oc, d))
        for d in ("runs/r1", "run-events"):
            os.makedirs(os.path.join(self.os_, d))
        os.chmod(os.path.join(self.oc, "credentials"), 0o700)
        self.put(self.oc, "credentials/acme-lead-push", "ghp_secret\n", 0o600)
        self.put(self.oc, "projects/acme.json", json.dumps({"project": "acme", "repo": {"credential_file": self.oc + "/credentials/acme-lead-push"},
                                                            "notes": ["~/.config/qargi/credentials/x", "$HOME/.config/qargi/profiles/acme.md",
                                                                      self.oc + "-other/keep", "/mnt/backup" + self.oc + "/keep", self.oc + ".bak"]}), 0o600)
        self.put(self.oc, "instances.json", "{}", 0o600)
        self.put(self.oc, "packs/skills/s/SKILL.md", "# s\n", 0o644)
        self.put(self.oc, "profiles/acme.md", "gates\n", 0o644)
        self.put(self.os_, "sessions.json", "{}", 0o600)
        self.put(self.os_, "sessions.json.lock", "", 0o600)
        self.put(self.os_, "local-runs.jsonl", json.dumps({"run": self.os_ + "/runs/r1"}) + "\n" + json.dumps({"run": "/tmp/elsewhere"}) + "\n", 0o600)
        self.put(self.os_, "audit.log", json.dumps({"verb": "x", "detail": self.oc}) + "\n", 0o600)
        self.put(self.os_, "run-events/a1.jsonl", json.dumps({"ev": "tool", "run": self.os_ + "/runs/r1"}) + "\n", 0o600)
        self.put(self.os_, "run-events/quiet.jsonl", json.dumps({"ev": "stop"}) + "\n", 0o600)
        self.put(self.os_, "supervisor.log", "nudged %s/runs/r1\n" % self.os_, 0o644)
        self.put(self.os_, "runs/r1/log.txt", "ran in %s\n" % self.os_, 0o644)
        os.symlink(self.oc + "/profiles/acme.md", os.path.join(self.oc, "profiles", "current"))
        self.before = (tree(self.oc), tree(self.os_))
        self.env = {k: v for k, v in os.environ.items() if k not in CLEAN}
        self.env["HOME"] = self.home

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def put(self, base, rel, text, mode):
        p = os.path.join(base, rel)
        with open(p, "w") as f:
            f.write(text)
        os.chmod(p, mode)

    def q(self, *a, **env):
        e = dict(self.env, **env)
        return subprocess.run([BIN, *a], capture_output=True, text=True, env=e, stdin=subprocess.DEVNULL)

    def token(self, r):
        for line in r.stdout.splitlines():
            if line.startswith("plan token: "):
                return line.split()[2]
        self.fail("no plan token: %s %s" % (r.stdout, r.stderr))

    def apply(self, **env):
        tok = self.token(self.q("migrate", "home", **env))
        return self.q("migrate", "home", "--plan", tok, "--approved", "copy my data", **env)

    # -- the plan

    def test_the_plan_lists_everything_and_changes_nothing(self):
        r = self.q("migrate", "home")
        self.assertEqual(r.returncode, 0, r.stderr)
        for want in ("config/credentials/acme-lead-push", "config/projects/acme.json", "state/local-runs.jsonl", "state/runs/r1/log.txt",
                     "config/packs/skills/s/SKILL.md", "config/profiles/current", "state/audit.log", "state/sessions.json.lock (lock file)",
                     "Rewritten in the copy (old config and state paths -> the new ones): config/profiles/current, config/projects/acme.json, state/local-runs.jsonl, state/runs/r1/log.txt"):
            self.assertIn(want, r.stdout)
        self.assertIn("0700", r.stdout)
        self.assertRegex(r.stdout, r"plan token: [0-9a-f]{12}")
        self.assertFalse(os.path.lexists(self.new), "the plan created the new root")
        self.assertEqual((tree(self.oc), tree(self.os_)), self.before)

    def test_nothing_to_migrate_without_the_old_directories(self):
        shutil.rmtree(self.oc), shutil.rmtree(self.os_)
        r = self.q("migrate", "home")
        self.assertEqual(r.returncode, 0)
        self.assertIn("nothing to migrate", r.stdout)
        self.assertFalse(os.path.lexists(self.new))

    # -- apply

    def test_apply_copies_rewrites_keeps_modes_and_leaves_the_old_directories(self):
        r = self.apply()
        self.assertEqual(r.returncode, 0, r.stderr)
        nc, ns = os.path.join(self.new, "config"), os.path.join(self.new, "state")
        self.assertEqual((tree(self.oc), tree(self.os_)), self.before, "the old directories changed")
        mode = lambda p: stat.S_IMODE(os.stat(p).st_mode)
        self.assertEqual(mode(os.path.join(nc, "credentials")), 0o700)
        self.assertEqual(mode(os.path.join(nc, "credentials/acme-lead-push")), 0o600)
        self.assertEqual(mode(os.path.join(nc, "packs/skills/s/SKILL.md")), 0o644)
        self.assertEqual(mode(self.new), 0o700)
        self.assertFalse(os.path.exists(os.path.join(ns, "sessions.json.lock")), "a lock file was copied")
        self.assertEqual(open(os.path.join(nc, "credentials/acme-lead-push")).read(), "ghp_secret\n")
        proj = json.load(open(os.path.join(nc, "projects/acme.json")))
        self.assertEqual(proj["repo"]["credential_file"], nc + "/credentials/acme-lead-push")
        self.assertEqual(proj["notes"], ["~/.qargi/config/credentials/x", "$HOME/.qargi/config/profiles/acme.md", self.oc + "-other/keep",
                                        "/mnt/backup" + self.oc + "/keep", self.oc + ".bak"])      # only whole old prefixes are rewritten
        runs = [json.loads(x) for x in open(os.path.join(ns, "local-runs.jsonl"))]
        self.assertEqual(runs, [{"run": ns + "/runs/r1"}, {"run": "/tmp/elsewhere"}])
        self.assertEqual(open(os.path.join(ns, "runs/r1/log.txt")).read(), "ran in %s\n" % ns)
        self.assertEqual(os.readlink(os.path.join(nc, "profiles/current")), nc + "/profiles/acme.md")
        first = open(os.path.join(ns, "audit.log")).read().splitlines()[0]
        self.assertIn(self.oc, first, "audit.log is a record and is copied as it is")
        last = json.loads(open(os.path.join(ns, "audit.log")).read().splitlines()[-1])
        self.assertEqual((last["verb"], last["approved"]), ("migrate-home", "copy my data"))
        self.assertEqual(mode(os.path.join(ns, "audit.log")), 0o600)

    def test_records_are_copied_byte_for_byte_and_the_plan_says_so(self):
        r = self.q("migrate", "home")
        line = next(x for x in r.stdout.splitlines() if x.startswith("Copied verbatim (records"))
        for rec in ("state/audit.log", "state/supervisor.log", "state/run-events/a1.jsonl"):
            self.assertIn(rec, line.split("): ", 1)[1])
        self.assertNotIn("run-events/quiet.jsonl", line.split("): ", 1)[1])      # it names no old path, so the exemption changes nothing
        rewritten = next(x for x in r.stdout.splitlines() if x.startswith("Rewritten in the copy"))
        for rec in ("audit.log", "supervisor.log", "run-events"):
            self.assertNotIn(rec, rewritten)
        self.assertEqual(self.apply().returncode, 0)
        ns = os.path.join(self.new, "state")
        for rel in ("audit.log", "supervisor.log", "run-events/a1.jsonl", "run-events/quiet.jsonl"):
            with open(os.path.join(self.os_, rel), "rb") as a, open(os.path.join(ns, rel), "rb") as b:
                body = a.read()
                if rel == "audit.log":
                    self.assertTrue(b.read().startswith(body), rel)          # the migration appended its own line
                else:
                    self.assertEqual(b.read(), body, rel)
        self.assertIn(self.os_.encode(), open(os.path.join(ns, "supervisor.log"), "rb").read())
        # everything else that names an old path is still rewritten
        for rel in ("local-runs.jsonl", "runs/r1/log.txt"):
            self.assertNotIn(self.os_, open(os.path.join(ns, rel)).read(), rel)
            self.assertIn(ns, open(os.path.join(ns, rel)).read(), rel)

    def test_the_token_covers_the_record_exemption(self):
        with_records = MH.token(self.build())
        real = MH.is_record
        MH.is_record = lambda side, rel: False
        self.addCleanup(setattr, MH, "is_record", real)
        self.assertNotEqual(with_records, MH.token(self.build()))

    def test_after_apply_qargi_works_and_a_second_plan_has_nothing_to_do(self):
        self.assertEqual(self.q("project", "list").returncode, 1, "the legacy refusal should hold before the copy")
        self.assertEqual(self.apply().returncode, 0)
        r = self.q("project", "list")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.q("migrate", "home")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("nothing to do", r.stdout)
        self.assertNotIn("plan token", r.stdout)

    def test_the_token_must_match_the_plan_and_the_approval_is_required(self):
        tok = self.token(self.q("migrate", "home"))
        for args in (("--plan", "000000000000", "--approved", "ok"), ("--approved", "ok")):
            r = self.q("migrate", "home", *args)
            self.assertEqual(r.returncode, 1, args)
            self.assertIn("plan changed or --plan is missing", r.stderr)
        self.assertFalse(os.path.lexists(self.new))
        r = self.q("migrate", "home", "--plan", tok)             # a token without --approved is a plan
        self.assertEqual(r.returncode, 0)
        self.assertFalse(os.path.lexists(self.new))

    def test_a_source_that_changed_after_the_plan_is_refused(self):
        tok = self.token(self.q("migrate", "home"))
        self.put(self.oc, "profiles/acme.md", "gates changed\n", 0o644)
        r = self.q("migrate", "home", "--plan", tok, "--approved", "ok")
        self.assertEqual(r.returncode, 1)
        self.assertIn("plan changed", r.stderr)
        self.assertFalse(os.path.lexists(self.new))

    def test_a_new_root_that_is_not_empty_is_refused_but_an_empty_one_is_filled(self):
        os.makedirs(os.path.join(self.new, "config"))
        self.put(self.new, "config/instances.json", "{}", 0o600)
        for args in ((), ("--plan", "x", "--approved", "ok")):
            r = self.q("migrate", "home", *args)
            self.assertEqual(r.returncode, 1)
            self.assertIn("not empty", r.stderr)
        self.assertEqual(os.listdir(self.new), ["config"])
        shutil.rmtree(self.new)
        os.makedirs(self.new)
        self.assertEqual(self.apply().returncode, 0)

    def test_qargi_home_names_the_destination_and_conf_state_overrides_refuse(self):
        dest = os.path.join(self.t, "elsewhere")
        r = self.apply(QARGI_HOME=dest)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(dest, "config/projects/acme.json")))
        self.assertIn(dest + "/config/credentials/acme-lead-push", open(os.path.join(dest, "config/projects/acme.json")).read())
        self.assertFalse(os.path.lexists(self.new))
        r = self.q("migrate", "home", QARGI_CONF=os.path.join(self.t, "c"))
        self.assertEqual(r.returncode, 1)
        self.assertIn("unset QARGI_CONF and QARGI_STATE", r.stderr)

    def test_the_earlier_directories_are_found_through_the_xdg_variables(self):
        xc, xs = os.path.join(self.t, "xc"), os.path.join(self.t, "xs")
        os.makedirs(xc), os.makedirs(xs)
        shutil.move(self.oc, os.path.join(xc, "qargi")), shutil.move(self.os_, os.path.join(xs, "qargi"))
        env = dict(XDG_CONFIG_HOME=xc, XDG_STATE_HOME=xs)
        self.put(os.path.join(xc, "qargi"), "projects/acme.json", json.dumps({"repo": {"credential_file": xc + "/qargi/credentials/acme-lead-push"}}), 0o600)
        r = self.apply(**env)
        self.assertEqual(r.returncode, 0, r.stderr)
        proj = json.load(open(os.path.join(self.new, "config/projects/acme.json")))
        self.assertEqual(proj["repo"]["credential_file"], self.new + "/config/credentials/acme-lead-push")

    # -- the checks inside apply

    def build(self):
        env = os.environ.copy()
        os.environ.update(self.env)
        for k in CLEAN:
            os.environ.pop(k, None)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(env)))
        return MH.build()

    def test_a_copy_that_does_not_match_its_digest_stops_and_is_removed(self):
        plan = self.build()
        real = MH.rewrite
        MH.rewrite = lambda data, rl: real(data, rl) + b"x"         # the written content no longer matches the planned digest
        self.addCleanup(setattr, MH, "rewrite", real)
        with self.assertRaises(SystemExit):
            MH.apply(plan, MH.token(plan), "ok")
        self.assertFalse(os.path.lexists(self.new), "a failed copy left files behind")
        self.assertEqual((tree(self.oc), tree(self.os_)), self.before)

    def test_a_source_that_changes_while_copying_stops_and_is_removed(self):
        plan = self.build()
        self.put(self.oc, "instances.json", '{"changed": 1}', 0o600)
        with self.assertRaises(SystemExit):
            MH.apply(plan, MH.token(plan), "ok")
        self.assertFalse(os.path.lexists(self.new))

    def test_the_token_covers_the_digests_and_the_file_list(self):
        a = MH.token(self.build())
        self.assertEqual(a, MH.token(self.build()))
        self.put(self.oc, "profiles/acme.md", "other\n", 0o644)
        b = MH.token(self.build())
        self.assertNotEqual(a, b)
        self.put(self.oc, "profiles/new.md", "x\n", 0o644)
        self.assertNotEqual(b, MH.token(self.build()))
        os.chmod(os.path.join(self.oc, "profiles/new.md"), 0o600)
        c = MH.token(self.build())
        os.chmod(os.path.join(self.oc, "profiles/new.md"), 0o644)
        self.assertNotEqual(c, MH.token(self.build()))


if __name__ == "__main__":
    unittest.main()
