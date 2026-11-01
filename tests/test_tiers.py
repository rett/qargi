#!/usr/bin/env python3
"""Memory tiers, slice 1 (read-only): lib/tiers.py and `qargi memory tiers|check`. Offline: tempdir HOME and QARGI_HOME,
directories for the dir tiers, a JSONL fixture (QARGI_CANON_FIXTURE_DIR) for the cloud tier, no real ant.
Run: python3 tests/test_tiers.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
TIERS = os.path.join(LIB, "tiers.py")
sys.path.insert(0, LIB)
import canon as C  # noqa: E402
import tiers as T  # noqa: E402

STORE = "memstore_FIX1"
REF = "memstore_REF1"
P = "demo"
SEED = os.path.join(ROOT, "provision", "canon-seed")


def seed_files(project, roles="build,write"):
    """A canon-2 memory store with no notes: what a plan against an empty store creates."""
    st = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    st.close()
    r = subprocess.run([sys.executable, os.path.join(LIB, "canon.py"), "plan", "--kind", "memory", "--project", project, "--roles", roles,
                        "--default-role", "build", "--seed", SEED, "--today", "2026-10-27", "--store", st.name], capture_output=True, text=True)
    os.unlink(st.name)
    plan = json.loads(r.stdout)
    out = C.simulate({}, plan["ops"])
    return {k: v["content"] for k, v in out.items()}


def put(root, files):
    for p, c in files.items():
        f = os.path.join(root, p.lstrip("/"))
        os.makedirs(os.path.dirname(f), exist_ok=True)
        with open(f, "w") as h:
            h.write(c)


def snapshot(*dirs_and_files):
    """Everything under the given directories (and the given files): directories, files and bytes. Missing stays missing."""
    snap = {}
    for d in dirs_and_files:
        if os.path.isdir(d):
            snap[d] = "dir"
            for base, ds, fs in os.walk(d):
                for n in ds:
                    snap[os.path.join(base, n)] = "dir"
                for n in fs:
                    with open(os.path.join(base, n), "rb") as f:
                        snap[os.path.join(base, n)] = f.read()
        elif os.path.isfile(d):
            with open(d, "rb") as f:
                snap[d] = f.read()
        else:
            snap[d] = None
    return snap


NOTE = "# n\n\nKind: sandbox\nApplies to: any\nSources: test run\nCheck: true\nVerified: 2026-10-27 by test\n"


class Env:
    """A fake home with a project's answers, tier directories and a cloud fixture."""

    def __init__(self, tiers=None, store=STORE, reference=REF, roles=("build", "write")):
        self.tmp = tempfile.mkdtemp(prefix="tiers.")
        self.home = os.path.join(self.tmp, "qhome")           # QARGI_HOME
        self.conf = os.path.join(self.tmp, "conf")
        self.state = os.path.join(self.tmp, "state")
        self.repo = os.path.join(self.tmp, "src", P)
        self.fix = os.path.join(self.tmp, "fixtures")
        for d in (self.home, self.repo, self.fix, os.path.join(self.conf, "projects")):
            os.makedirs(d)
        self.env = dict(os.environ, QARGI_HOME=self.home, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_CANON_FIXTURE_DIR=self.fix)
        self.roles = roles
        self.answers = self.make_answers(tiers, store, reference)
        self.write_answers(self.answers)

    def make_answers(self, tiers, store, reference):
        r = subprocess.run([BIN, "project", "template", P], capture_output=True, text=True, env=self.env)
        a = json.loads(r.stdout)
        a["repo"]["url"] = "https://github.com/example/demo"
        a["repo"]["path"] = self.repo
        a["roles"] = {k: v for k, v in a["roles"].items() if k in self.roles}
        a["memory"] = {"memory_store": store, "reference_store": reference}
        if tiers is not None:
            a["memory"]["tiers"] = tiers
        return a

    def write_answers(self, a):
        with open(os.path.join(self.conf, "projects", P + ".json"), "w") as f:
            json.dump(a, f)

    # the default locations
    def d(self, tier):
        return {"repo": os.path.join(self.repo, "qargi", "memory"), "project": os.path.join(self.home, "memory", "projects", P),
                "shared": os.path.join(self.home, "memory", "shared"), "system": os.path.join(self.home, "memory", "system")}[tier]

    def cloud(self, files, store=STORE):
        with open(os.path.join(self.fix, store + ".jsonl"), "w") as f:
            for i, (p, c) in enumerate(sorted(files.items())):
                f.write(json.dumps({"type": "memory", "id": "m%d" % i, "path": p, "content": c, "content_sha256": ""}) + "\n")

    def snap(self):
        return snapshot(*[self.d(t) for t in ("repo", "project", "shared", "system")], os.path.join(self.fix, STORE + ".jsonl"))

    def qargi(self, *args, env=None):
        return subprocess.run([BIN, *args], capture_output=True, text=True, env=env or self.env)

    def cleanup(self):
        shutil.rmtree(self.tmp, True)


class Base(unittest.TestCase):
    def mk(self, **kw):
        e = Env(**kw)
        self.addCleanup(e.cleanup)
        return e

    def environ(self, e):
        old = dict(os.environ)
        os.environ.update(e.env)
        self.addCleanup(lambda: (os.environ.clear(), os.environ.update(old)))


class Resolve(Base):
    def test_order(self):
        self.assertEqual(tuple(T.ORDER), ("repo", "cloud", "project", "shared", "system"))

    def test_resolve_defaults_are_under_qargi_home_not_home(self):
        e = self.mk()
        self.environ(e)
        ts = T.resolve(e.answers, P)
        self.assertEqual([t["tier"] for t in ts], list(T.ORDER))
        by = {t["tier"]: t for t in ts}
        self.assertEqual(os.path.realpath(by["repo"]["location"]), os.path.realpath(e.d("repo")))
        for name in ("project", "shared", "system"):
            loc = os.path.realpath(os.path.expanduser(by[name]["location"]))
            self.assertEqual(loc, os.path.realpath(e.d(name)), name)
            self.assertFalse(loc.startswith(os.path.realpath(os.path.expanduser("~")) + os.sep + ".qargi"), name)
        self.assertEqual(by["repo"]["kind"], "dir")
        self.assertEqual(by["cloud"]["kind"], "cloud")
        for name in ("project", "shared", "system"):
            self.assertEqual(by[name]["kind"], "dir")
        for t in ts:
            self.assertIn("label", t)

    def test_cloud_comes_from_memory_store_and_reference_is_not_a_tier(self):
        e = self.mk()
        self.environ(e)
        ts = T.resolve(e.answers, P)
        self.assertEqual({t["tier"]: t["store_id"] for t in ts}["cloud"], STORE)
        self.assertNotIn(REF, json.dumps(ts))
        self.assertFalse([t for t in ts if t["tier"] == "reference"])

    def test_answers_override(self):
        e = self.mk(tiers={"repo": {"path": "docs/mem"}, "project": {"path": "~/mine/p"}, "shared": {"path": os.path.join("/srv", "sh")},
                           "system": {"path": "/srv/sys"}})
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(os.path.realpath(by["repo"]["location"]), os.path.realpath(os.path.join(e.repo, "docs", "mem")))
        self.assertEqual(os.path.expanduser(by["project"]["location"]), os.path.expanduser("~/mine/p"))
        self.assertEqual(by["shared"]["location"], "/srv/sh")
        self.assertEqual(by["system"]["location"], "/srv/sys")

    def test_partial_override_keeps_other_defaults(self):
        e = self.mk(tiers={"shared": {"path": "/srv/sh"}})
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(by["shared"]["location"], "/srv/sh")
        self.assertEqual(os.path.realpath(os.path.expanduser(by["system"]["location"])), os.path.realpath(e.d("system")))

    def test_no_cloud_store_recorded(self):
        e = self.mk(store="")
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertFalse(by["cloud"].get("store_id"))

    def test_defaults_function(self):
        e = self.mk()
        self.environ(e)
        d = T.defaults(P, e.repo)
        self.assertEqual(set(d), {"repo", "project", "shared", "system"})
        for v in d.values():
            self.assertIn("kind", v)
            self.assertIn("location", v)
        self.assertTrue(os.path.expanduser(d["system"]["location"]).startswith(e.home))


class Status(Base):
    def test_dir_statuses(self):
        e = self.mk()
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(T.status(by["project"]), "missing")
        os.makedirs(e.d("project"))
        self.assertEqual(T.status(by["project"]), "empty")
        os.makedirs(os.path.join(e.d("project"), "emptysub"))
        self.assertEqual(T.status(by["project"]), "empty")             # directories alone are not notes
        put(e.d("project"), {"/a.md": "x"})
        self.assertEqual(T.status(by["project"]), "present")

    def test_cloud_present_with_ant_and_fixture(self):
        e = self.mk()
        self.environ(e)
        e.cloud(seed_files(P))
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(T.status(by["cloud"]), "present")

    def test_cloud_unreachable_without_ant_never_raises(self):
        e = self.mk()
        self.environ(e)
        keep = [d for d in os.environ["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "ant"))]
        os.environ["PATH"] = os.pathsep.join(keep)
        os.environ.pop("QARGI_CANON_FIXTURE_DIR")
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(T.status(by["cloud"]), "unreachable")
        self.assertIsNone(T.listing(by["cloud"]))

    def test_cloud_without_store_does_not_raise(self):
        e = self.mk(store="")
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertIn(T.status(by["cloud"]), ("missing", "unreachable"))

    def test_status_never_raises_on_a_file_where_a_dir_should_be(self):
        e = self.mk()
        self.environ(e)
        os.makedirs(os.path.dirname(e.d("shared")))
        with open(e.d("shared"), "w") as f:
            f.write("not a directory")
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertIn(T.status(by["shared"]), ("missing", "empty", "unreachable"))


class Listing(Base):
    def test_dir_listing(self):
        e = self.mk()
        self.environ(e)
        put(e.d("project"), {"/shared/a.md": NOTE, "/roles/build/b.md": NOTE})
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        l = T.listing(by["project"])
        self.assertEqual(sorted(l), ["/roles/build/b.md", "/shared/a.md"])
        self.assertIsNone(T.listing(by["system"]))                     # missing

    def test_cloud_listing_from_fixture(self):
        e = self.mk()
        self.environ(e)
        e.cloud({"/shared/x.md": NOTE})
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        self.assertEqual(sorted(T.listing(by["cloud"])), ["/shared/x.md"])


class Collisions(Base):
    def test_structural_exemptions(self):
        for p in ("/README.md", "/CANON.md", "/_template.md", "/shared/INDEX.md", "/roles/build/INDEX.md", "/shared/repos/x/INDEX.md",
                  "/roles/build/tools/run.py", "/roles/build/tools/README.md", "/_archive/2026-01-01/shared/a.md", "/_conflicts/2026-01-01/a.md"):
            self.assertTrue(T.STRUCTURAL.search(p), p)
        for p in ("/shared/x.md", "/roles/build/y.md", "/shared/sandbox/a.md", "/roles/build/notes/INDEX.txt"):
            self.assertFalse(T.STRUCTURAL.search(p), p)

    def test_structural_files_may_repeat(self):
        same = {"/README.md": "r", "/CANON.md": "c", "/_template.md": "t", "/shared/INDEX.md": "i", "/roles/build/tools/t.py": "p",
                "/_archive/2026/x.md": "a", "/_conflicts/2026/y.md": "c"}
        self.assertEqual(T.collisions({"repo": dict(same), "project": dict(same), "shared": dict(same)}), [])

    def test_one_tier_rule_two_and_three(self):
        l = {"repo": {"/shared/x.md": {}, "/roles/build/y.md": {}, "/shared/only-repo.md": {}},
             "project": {"/shared/x.md": {}, "/shared/only-project.md": {}},
             "shared": {"/roles/build/y.md": {}, "/shared/x.md": {}}}
        got = {p: list(ts) for p, ts in T.collisions(l)}
        self.assertEqual(got, {"/shared/x.md": ["repo", "project", "shared"], "/roles/build/y.md": ["repo", "shared"]})

    def test_no_collision_when_paths_differ(self):
        self.assertEqual(T.collisions({"repo": {"/shared/a.md": {}}, "project": {"/shared/b.md": {}}}), [])

    def test_missing_tiers_are_ignored(self):
        self.assertEqual(T.collisions({"repo": {"/shared/a.md": {}}, "project": None, "cloud": None}), [])


class CheckArgs(Base):
    def test_repo_and_project_use_the_project_name(self):
        e = self.mk()
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        for name in ("repo", "project", "cloud"):
            proj, roles = T.check_args(by[name], P, ["build", "test"], ["build"])
            self.assertEqual(proj, P, name)

    def test_shared_and_system_use_the_tier_name_and_union_of_roles(self):
        e = self.mk()
        self.environ(e)
        by = {t["tier"]: t for t in T.resolve(e.answers, P)}
        for name in ("shared", "system"):
            proj, roles = T.check_args(by[name], P, ["build", "test"], "# Canon\n\ncanon: 2\nkind: memory\nproject: %s\nroles: build write\n" % name)
            self.assertEqual(proj, name)
            self.assertEqual(set(roles.split(",")), {"build", "test", "write"})
            self.assertNotIn(" ", roles)


def tiers_json(r):
    return json.loads(r.stdout)


class Validation(Base):
    def validate(self, e, tiers):
        a = json.loads(json.dumps(e.answers))
        if tiers is None:
            a["memory"].pop("tiers", None)
        else:
            a["memory"]["tiers"] = tiers
        f = os.path.join(e.tmp, "a.json")
        with open(f, "w") as h:
            json.dump(a, h)
        return e.qargi("project", "validate", f)

    def test_valid_answers(self):
        e = self.mk()
        for t in (None, {}, {"repo": {"path": "docs/mem"}}, {"project": {"path": "~/m/p"}, "shared": {"path": "/srv/s"}, "system": {"path": "/srv/y"}}):
            r = self.validate(e, t)
            self.assertEqual(r.returncode, 0, "%s: %s%s" % (t, r.stdout, r.stderr))

    def test_invalid_answers(self):
        e = self.mk()
        for t in ({"bogus": {"path": "x"}}, {"cloud": {"path": "x"}}, {"reference": {"path": "x"}},
                  {"repo": {"path": "/abs/mem"}}, {"repo": {"path": "../mem"}}, {"repo": {"path": "a/../../b"}},
                  {"repo": {"path": ""}}, {"shared": {"path": ""}}, {"project": {"path": 3}}, {"shared": "/x"}, {"system": {}},
                  {"shared": {"path": "relative/dir"}}, "text", ["repo"]):
            r = self.validate(e, t)
            self.assertEqual(r.returncode, 1, "%r accepted: %s%s" % (t, r.stdout, r.stderr))
            self.assertIn("memory.tiers", r.stdout + r.stderr, t)

    def test_template_has_empty_tiers(self):
        e = self.mk()
        r = e.qargi("project", "template", P)
        self.assertEqual(json.loads(r.stdout)["memory"].get("tiers"), {})


class Cli(Base):
    def populated(self):
        e = self.mk()
        put(e.d("repo"), seed_files(P))
        put(e.d("repo"), {"/shared/r.md": NOTE})
        e.cloud(seed_files(P))
        put(e.d("shared"), seed_files("shared"))
        os.makedirs(e.d("system"))                                       # empty
        return e                                                         # project tier missing

    def test_tiers_lines(self):
        e = self.populated()
        r = e.qargi("memory", "tiers", "--project", P)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        lines = [l for l in r.stdout.splitlines() if l.strip()]
        names = [l.split()[0] for l in lines]
        self.assertEqual(names, ["repo", "cloud", "project", "shared", "system", "reference:"], r.stdout)
        by = {l.split()[0]: l for l in lines}
        self.assertRegex(by["repo"], r"^repo\s+dir\s+\S*qargi/memory\s+present\s+\d+ notes?")
        self.assertRegex(by["cloud"], r"^cloud\s+cloud\s+%s .*present" % STORE)
        self.assertRegex(by["project"], r"^project\s+dir\s+\S+\s+missing")
        self.assertRegex(by["shared"], r"^shared\s+dir\s+\S+\s+present")
        self.assertRegex(by["system"], r"^system\s+dir\s+\S+\s+empty")
        self.assertIn("reference: %s (optional, read-only, not composed)" % REF, by["reference:"])

    def test_tiers_dev_run_never_reads_the_real_home(self):
        e = self.populated()
        r = e.qargi("memory", "tiers", "--project", P)
        self.assertIn(e.home, r.stdout)

    def test_tiers_json_shape(self):
        e = self.populated()
        r = e.qargi("memory", "tiers", "--project", P, "--json")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        j = tiers_json(r)
        self.assertEqual(j["project"], P)
        self.assertEqual([t["tier"] for t in j["tiers"]], list(T.ORDER))
        for t in j["tiers"]:
            for k in ("tier", "kind", "location", "status"):
                self.assertIn(k, t)
        self.assertEqual({t["tier"]: t["status"] for t in j["tiers"]},
                         {"repo": "present", "cloud": "present", "project": "missing", "shared": "present", "system": "empty"})
        self.assertIn(REF, json.dumps(j["reference"]))
        self.assertNotIn("reference", [t["tier"] for t in j["tiers"]])

    def test_tiers_unreachable_without_ant(self):
        e = self.populated()
        keep = [d for d in e.env["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "ant"))]
        env = dict(e.env, PATH=os.pathsep.join(keep))
        env.pop("QARGI_CANON_FIXTURE_DIR")
        r = e.qargi("memory", "tiers", "--project", P, env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        cloud = [l for l in r.stdout.splitlines() if l.startswith("cloud")][0]
        self.assertIn("unreachable", cloud)
        self.assertIn("(ant not installed or not logged in)", cloud)

    def test_tiers_exit_codes(self):
        e = self.mk()
        self.assertEqual(e.qargi("memory", "tiers", "--project", "nosuch").returncode, 1)
        self.assertEqual(e.qargi("memory", "tiers", "--project", P, "--bogus").returncode, 2)
        bad = json.loads(json.dumps(e.answers))
        bad["memory"]["tiers"] = {"repo": {"path": "/abs"}}
        e.write_answers(bad)
        r = e.qargi("memory", "tiers", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("memory.tiers", r.stdout + r.stderr)
        r = e.qargi("memory", "check", "--project", P)
        self.assertEqual(r.returncode, 1)

    def test_module_usage_error_is_2(self):
        r = subprocess.run([sys.executable, "-I", TIERS, "frobnicate"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_check_sections_and_clean_exit(self):
        e = self.populated()
        r = e.qargi("memory", "check", "--project", P)
        out = r.stdout
        self.assertIn("== tier repo (dir %s)" % e.d("repo"), out)
        self.assertIn("== tier cloud (cloud %s" % STORE, out)
        self.assertIn("== tier shared (dir %s)" % e.d("shared"), out)
        self.assertNotIn("== tier project", out)                         # missing: not checked
        self.assertIn("== tiers", out)
        self.assertRegex(out, r"INFO tier project: missing \(qargi memory init project\)")
        self.assertRegex(out, r"INFO tier system: .*empty|INFO tier system: missing")
        self.assertRegex(out.strip().splitlines()[-1], r"^\d+ fail, \d+ warn, 3 tiers checked$")

    def test_check_collision_is_a_fail(self):
        e = self.populated()
        put(e.d("shared"), {"/shared/r.md": NOTE})                       # also in the repo tier
        r = e.qargi("memory", "check", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL /shared/r.md: in tiers repo, shared (a note lives in one tier; qargi memory move PATH --from T --to T)", r.stdout)
        self.assertRegex(r.stdout.strip().splitlines()[-1], r"^[1-9]\d* fail, \d+ warn, \d+ tiers checked$")

    def test_check_collision_across_three_tiers(self):
        e = self.populated()
        put(e.d("shared"), {"/shared/r.md": NOTE})
        e.cloud({**seed_files(P), "/shared/r.md": NOTE})
        r = e.qargi("memory", "check", "--project", P)
        self.assertEqual(r.returncode, 1)
        self.assertIn("FAIL /shared/r.md: in tiers repo, cloud, shared (a note lives in one tier; qargi memory move PATH --from T --to T)", r.stdout)

    def test_check_structural_repeats_are_not_collisions(self):
        e = self.populated()
        r = e.qargi("memory", "check", "--project", P)                    # README, CANON, _template, INDEX repeat in every tier
        self.assertNotIn("a note lives in one tier", r.stdout)

    def test_check_unreachable_cloud_is_info(self):
        e = self.populated()
        keep = [d for d in e.env["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "ant"))]
        env = dict(e.env, PATH=os.pathsep.join(keep))
        env.pop("QARGI_CANON_FIXTURE_DIR")
        r = e.qargi("memory", "check", "--project", P, env=env)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertIn("INFO tier cloud: unreachable, collisions computed without it", r.stdout)
        self.assertNotIn("FAIL tier cloud", r.stdout)

    def test_check_unknown_canon_in_repo_tier_names_the_answer(self):
        e = self.mk()
        put(e.d("repo"), {"/CANON.md": "# Canon\n\ncanon: 99\nkind: memory\nproject: demo\nroles: build write\n"})
        r = e.qargi("memory", "check", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout)
        hint = [l for l in r.stdout.splitlines() if "project set %s memory.tiers.repo.path" % P in l]
        self.assertEqual(len(hint), 1, r.stdout)
        self.assertTrue(hint[0].startswith("FAIL"), hint)
        self.assertRegex(r.stdout.strip().splitlines()[-1], r"^1 fail, \d+ warn, 1 tiers checked$")

    def test_shared_tier_is_checked_as_shared_for_the_union_of_roles(self):
        e = self.mk(roles=("build", "test"))
        put(e.d("repo"), seed_files(P, "build,test"))
        put(e.d("shared"), seed_files("shared", "build,write"))           # written for build,write
        r = e.qargi("memory", "check", "--project", P)
        sect = r.stdout.split("== tier shared", 1)[1].split("== ", 1)[0]
        self.assertNotIn("FAIL", sect, r.stdout)

    def test_nothing_is_ever_written(self):
        e = self.populated()
        put(e.d("shared"), {"/shared/r.md": NOTE})
        before = e.snap()
        for args in (("tiers",), ("tiers", "--json"), ("check",)):
            e.qargi("memory", *args, "--project", P)
        keep = [d for d in e.env["PATH"].split(os.pathsep) if not os.path.exists(os.path.join(d, "ant"))]
        env = dict(e.env, PATH=os.pathsep.join(keep))
        e.qargi("memory", "check", "--project", P, env=env)
        self.assertEqual(e.snap(), before)
        self.assertFalse(os.path.exists(e.d("project")))                 # a missing tier is not created


class Slice2Messages(Base):
    """Slice 2 makes `qargi memory init` and `move` real: the hints of the check name them without "later slice" or "comes later"."""
    populated = Cli.populated

    def test_missing_and_empty_hints_name_init_without_later_slice(self):
        e = self.populated()
        r = e.qargi("memory", "check", "--project", P)
        self.assertNotIn("later slice", r.stdout)
        self.assertRegex(r.stdout, r"INFO tier project: missing \(qargi memory init project\)")
        self.assertRegex(r.stdout, r"INFO tier system: empty \(qargi memory init system\)")

    def test_collision_hint_names_the_move_verb(self):
        e = self.populated()
        put(e.d("shared"), {"/shared/r.md": NOTE})
        r = e.qargi("memory", "check", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAIL /shared/r.md: in tiers repo, shared (a note lives in one tier; qargi memory move PATH --from T --to T)", r.stdout)
        self.assertNotIn("comes later", r.stdout)


if __name__ == "__main__":
    unittest.main()
