#!/usr/bin/env python3
"""Memory tiers, slice 2: writing a tier. `qargi memory init TIER` and `qargi memory move PATH --from T --to T` (lib/tierwrite.sh,
planned and applied by lib/tierplan.py), and the plan helpers they share with `memplan split`. Offline: tempdir QARGI_HOME,
QARGI_CONF and QARGI_STATE, directories for the dir tiers, a JSONL fixture (QARGI_CANON_FIXTURE_DIR) for the cloud tier and a
fake `ant` that only answers `auth status` (the fixture is the store). The fixtures and the Env come from test_tiers.py.
Run: python3 tests/test_tierplan.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, subprocess, sys, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from test_tiers import Env, NOTE, P, STORE, seed_files, put, snapshot  # noqa: E402
LIB = os.path.join(HERE, "..", "lib")
TIERPLAN = os.path.join(LIB, "tierplan.py")
MEMPLAN = os.path.join(LIB, "memplan.py")
TOKEN = re.compile(r"plan token: ([0-9a-f]{12})")
DATE = r"\d{4}-\d\d-\d\d"


def rd(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def files_under(root):
    out = {}
    for base, _, fs in os.walk(root):
        for n in fs:
            out["/" + os.path.relpath(os.path.join(base, n), root)] = rd(os.path.join(base, n))
    return out


def git(repo, *args):
    return subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.net", *args], capture_output=True, text=True)


class Base(unittest.TestCase):
    def mk(self, **kw):
        e = Env(**kw)
        self.addCleanup(e.cleanup)
        bindir = os.path.join(e.tmp, "bin")                       # a fake ant: logged in, and nothing else
        os.makedirs(bindir)
        with open(os.path.join(bindir, "ant"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(bindir, "ant"), 0o755)
        e.env["PATH"] = bindir + os.pathsep + e.env["PATH"]
        return e

    def git_repo(self, e):
        git(e.repo, "init", "-q", "-b", "main")
        git(e.repo, "commit", "-q", "--allow-empty", "-m", "one")

    def token_of(self, r):
        m = TOKEN.search(r.stdout)
        self.assertTrue(m, "no plan token in: " + r.stdout + r.stderr)
        return m.group(1)

    def init(self, e, tier, approve=True):
        r = e.qargi("memory", "init", tier, "--project", P)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        if not approve:
            return r
        r = e.qargi("memory", "init", tier, "--project", P, "--plan", self.token_of(r), "--approved", "test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r


class Init(Base):
    def test_without_approved_it_prints_a_plan_and_changes_nothing(self):
        e = self.mk()
        before = e.snap()
        r = e.qargi("memory", "init", "shared", "--project", P)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"plan only, nothing was changed; plan token: [0-9a-f]{12}   \(apply with: --plan [0-9a-f]{12} --approved \"\.\.\.\"\)")
        self.assertEqual(e.snap(), before)
        self.assertFalse(os.path.exists(e.d("shared")))

    def test_a_wrong_token_is_refused_and_writes_nothing(self):
        e = self.mk()
        r = e.qargi("memory", "init", "shared", "--project", P, "--plan", "000000000000", "--approved", "test")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(e.d("shared")))
        r = e.qargi("memory", "init", "shared", "--project", P, "--approved", "test")        # --approved without --plan
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(e.d("shared")))

    def test_apply_creates_a_store_that_the_check_passes(self):
        e = self.mk()
        r = self.init(e, "shared")
        self.assertRegex(r.stdout, r"init done: tier shared at %s \(\d+ files\); nothing was committed" % re.escape(e.d("shared")))
        files = files_under(e.d("shared"))
        self.assertIn("/CANON.md", files)
        self.assertRegex(files["/CANON.md"], r"(?m)^project: shared$")
        self.assertRegex(files["/CANON.md"], r"(?m)^canon: 2$")
        for f in ("/README.md", "/shared/INDEX.md", "/roles/build/INDEX.md", "/roles/write/INDEX.md", "/_template.md"):
            self.assertIn(f, files)
        c = e.qargi("memory", "check", "--project", P)
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)
        self.assertIn("== tier shared (dir %s)" % e.d("shared"), c.stdout)
        self.assertRegex(c.stdout.strip().splitlines()[-1], r"^0 fail, \d+ warn, 1 tiers checked$")

    def test_project_and_system_carry_the_marker_of_their_own_kind(self):
        e = self.mk()
        self.init(e, "project")
        self.init(e, "system")
        self.assertRegex(files_under(e.d("project"))["/CANON.md"], r"(?m)^project: demo$")
        self.assertRegex(files_under(e.d("system"))["/CANON.md"], r"(?m)^project: system$")
        for t in ("project", "system"):
            self.assertEqual(os.stat(e.d(t)).st_mode & 0o777, 0o700, t)         # created with umask 077

    def test_the_audit_log_records_the_plan_and_that_it_was_applied(self):
        e = self.mk()
        self.init(e, "shared")
        lines = [json.loads(l) for l in rd(os.path.join(e.state, "audit.log")).splitlines()]
        verbs = [l["verb"] for l in lines]
        self.assertIn("memory-init", verbs)
        self.assertIn("memory-init-applied", verbs)
        self.assertGreater(verbs.index("memory-init-applied"), verbs.index("memory-init"))

    def test_again_it_is_already_initialised(self):
        e = self.mk()
        self.init(e, "shared")
        before = e.snap()
        r = e.qargi("memory", "init", "shared", "--project", P)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tier shared is already initialised at %s; nothing to do" % e.d("shared"), r.stdout + r.stderr)
        self.assertNotIn("plan token", r.stdout)
        self.assertEqual(e.snap(), before)

    def test_a_non_empty_directory_without_a_canon_marker_is_refused(self):
        e = self.mk()
        put(e.d("shared"), {"/mine.txt": "keep me\n"})
        before = e.snap()
        for extra in ((), ("--plan", "000000000000", "--approved", "test")):
            r = e.qargi("memory", "init", "shared", "--project", P, *extra)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn("not empty and not a canon-2 store; use qargi canon plan or another path", r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_a_marker_of_another_version_is_refused(self):
        e = self.mk()
        put(e.d("shared"), {"/CANON.md": "# Canon\n\ncanon: 1\nkind: memory\nproject: shared\nroles: build write\n"})
        before = e.snap()
        r = e.qargi("memory", "init", "shared", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("not empty and not a canon-2 store; use qargi canon plan or another path", r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_the_cloud_tier_is_not_created_here(self):
        e = self.mk()
        r = e.qargi("memory", "init", "cloud", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("the cloud tier is created by qargi provision", r.stdout + r.stderr)

    def test_a_bad_tier_is_a_usage_error(self):
        e = self.mk()
        for args in (("memory", "init", "frobnicate", "--project", P), ("memory", "init", "--project", P)):
            r = e.qargi(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertNotIn("not implemented yet", r.stderr)
            self.assertIn("usage", r.stderr.lower())

    def test_overlapping_locations_are_refused(self):
        base = None
        for inner in ("/inner", ""):                                  # nested, then the very same directory
            e = self.mk()
            base = os.path.join(e.tmp, "ov")
            e.write_answers(dict(e.answers, memory=dict(e.answers["memory"], tiers={"shared": {"path": base}, "system": {"path": base + inner}})))
            for tier in ("shared", "system"):                         # the answers overlap, so neither tier may be created
                r = e.qargi("memory", "init", tier, "--project", P)
                self.assertEqual(r.returncode, 1, (inner, tier, r.stdout + r.stderr))
                self.assertFalse(os.path.exists(base), (inner, tier))

    def test_the_repo_tier_needs_a_git_checkout(self):
        e = self.mk()                                                 # the repo directory is not a git work tree
        r = e.qargi("memory", "init", "repo", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(e.d("repo")))
        self.git_repo(e)
        a = json.loads(json.dumps(e.answers))
        a["repo"]["path"] = ""
        e.write_answers(a)
        r = e.qargi("memory", "init", "repo", "--project", P)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(e.d("repo")))

    def test_a_repo_symlink_pointing_out_of_the_checkout_is_refused(self):
        e = self.mk()
        self.git_repo(e)
        outside = os.path.join(e.tmp, "outside")
        os.makedirs(outside)
        os.symlink(outside, os.path.join(e.repo, "qargi"))
        for extra in ((), ("--plan", "000000000000", "--approved", "test")):
            r = e.qargi("memory", "init", "repo", "--project", P, *extra)
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(os.listdir(outside), [])

    def test_the_repo_tier_warns_writes_untracked_files_and_commits_nothing(self):
        e = self.mk()
        self.git_repo(e)
        head = git(e.repo, "rev-parse", "HEAD").stdout
        r = e.qargi("memory", "init", "repo", "--project", P)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARNING: this writes into the repository checkout %s at qargi/memory; qargi never commits it: review and commit it yourself, or ignore it in git." % e.repo, r.stdout)
        self.assertFalse(os.path.exists(e.d("repo")))
        r = e.qargi("memory", "init", "repo", "--project", P, "--plan", self.token_of(r), "--approved", "test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing was committed", r.stdout)
        st = git(e.repo, "status", "--porcelain", "--untracked-files=all").stdout
        self.assertIn("?? qargi/memory/CANON.md", st)
        self.assertEqual(git(e.repo, "rev-parse", "HEAD").stdout, head)
        self.assertEqual(git(e.repo, "log", "--oneline").stdout.count("\n"), 1)
        self.assertEqual(git(e.repo, "diff", "--cached", "--name-only").stdout, "")     # and nothing staged either


class Plans(Base):
    """The plan helper on its own: lib/tierplan.py plan-init|plan-move|show|apply, exit 1 for a refusal and 2 for usage."""
    def run_plan(self, e, *args):
        return subprocess.run([sys.executable, "-I", TIERPLAN, *args], capture_output=True, text=True, env=e.env)

    def test_plan_show_apply_roundtrip(self):
        e = self.mk()
        f = os.path.join(e.tmp, "plan.json")
        r = self.run_plan(e, "plan-init", "shared", "--project", P, "--out", f)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(f))
        self.assertFalse(os.path.exists(e.d("shared")))               # planning writes the plan file only
        r = self.run_plan(e, "show", f)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("/CANON.md", r.stdout)
        r = self.run_plan(e, "apply", f)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("/CANON.md", files_under(e.d("shared")))

    def test_usage_and_refusals_have_their_exit_codes(self):
        e = self.mk()
        f = os.path.join(e.tmp, "plan.json")
        for args in (("frobnicate",), (), ("plan-init",), ("plan-init", "shared"), ("plan-move", "/shared/a.md", "--from", "project"), ("show",), ("apply",)):
            self.assertEqual(self.run_plan(e, *args).returncode, 2, args)
        r = self.run_plan(e, "plan-init", "cloud", "--project", P, "--out", f)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(f))
        r = self.run_plan(e, "plan-move", "/shared/a.md", "--from", "project", "--to", "shared", "--project", P, "--out", f)    # neither tier exists
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(os.path.exists(f))


class Move(Base):
    """Two present tiers (project, shared) holding canon stores; notes live in the project tier."""
    def two(self, extra=None, cloud=None):
        e = self.mk()
        proj = seed_files(P)
        idx = proj["/roles/build/INDEX.md"].replace("| (none yet) | | |", "| r.md | a recipe | always |\n| sub/a.md | one | when debugging builds |\n| sub/b.md | two | when debugging builds |")
        proj.update({"/roles/build/INDEX.md": idx, "/roles/build/r.md": NOTE, "/roles/build/sub/a.md": NOTE.replace("# n", "# a"), "/roles/build/sub/b.md": NOTE.replace("# n", "# b")})
        proj.update(extra or {})
        put(e.d("project"), proj)
        put(e.d("shared"), seed_files("shared"))
        if cloud is not None:
            e.cloud(cloud)
        return e

    def plan(self, e, path, frm="project", to="shared"):
        return e.qargi("memory", "move", path, "--from", frm, "--to", to, "--project", P)

    def apply(self, e, path, frm="project", to="shared"):
        r = self.plan(e, path, frm, to)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r2 = e.qargi("memory", "move", path, "--from", frm, "--to", to, "--project", P, "--plan", self.token_of(r), "--approved", "test")
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        return r2

    def test_plan_only_changes_nothing_and_warns_about_an_unreachable_third_tier(self):
        e = self.two()
        before = e.snap()
        r = self.plan(e, "/roles/build/r.md")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertRegex(r.stdout, r"plan only, nothing was changed; plan token: [0-9a-f]{12}")
        self.assertIn("WARNING: tier cloud unreachable; collisions with it not checked", r.stdout + r.stderr)    # no fixture for the store
        self.assertEqual(e.snap(), before)

    def test_one_note_moves_with_its_provenance_and_its_index_row(self):
        e = self.two()
        old = rd(os.path.join(e.d("project"), "roles/build/r.md"))
        r = self.apply(e, "/roles/build/r.md")
        self.assertRegex(r.stdout, r"move done \(approved: test\); nothing was deleted; source archived under /_archive/%s/" % DATE)
        dst = files_under(e.d("shared"))
        self.assertIn("/roles/build/r.md", dst)
        self.assertRegex(dst["/roles/build/r.md"], r"copied from tier-project:/roles/build/r\.md@[0-9a-f]{12}")
        src = files_under(e.d("project"))
        self.assertNotIn("/roles/build/r.md", src)
        arch = [p for p in src if re.match(r"/_archive/%s/roles/build/r\.md$" % DATE, p)]
        self.assertEqual(len(arch), 1, sorted(src))
        self.assertRegex(src[arch[0]], r"archived from /roles/build/r\.md@[0-9a-f]{12} on %s" % DATE)
        self.assertIn("Verified: 2026-10-27 by test", src[arch[0]])      # the archived text is the note, not a stub
        self.assertEqual(old.count("Kind: sandbox"), src[arch[0]].count("Kind: sandbox"))
        self.assertRegex(dst["/roles/build/INDEX.md"], r"(?m)^\| r\.md \|[^|\n]*\| always \|$")
        self.assertNotRegex(src["/roles/build/INDEX.md"], r"(?m)^\| r\.md \|")
        self.assertRegex(src["/roles/build/INDEX.md"], r"(?m)^\| sub/a\.md \|")       # the other rows stay
        c = e.qargi("memory", "check", "--project", P)
        self.assertEqual(c.returncode, 0, c.stdout + c.stderr)

    def test_a_prefix_moves_every_note_under_it(self):
        e = self.two()
        self.apply(e, "/roles/build/sub")
        dst, src = files_under(e.d("shared")), files_under(e.d("project"))
        for n in ("a", "b"):
            self.assertIn("/roles/build/sub/%s.md" % n, dst)
            self.assertNotIn("/roles/build/sub/%s.md" % n, src)
            self.assertTrue([p for p in src if re.match(r"/_archive/%s/roles/build/sub/%s\.md$" % (DATE, n), p)])
            self.assertRegex(dst["/roles/build/INDEX.md"], r"(?m)^\| sub/%s\.md \|" % n)
            self.assertNotRegex(src["/roles/build/INDEX.md"], r"(?m)^\| sub/%s\.md \|" % n)
        self.assertIn("/roles/build/r.md", src)                           # a sibling outside the prefix stays

    def test_a_prefix_picks_notes_only(self):
        e = self.two({"/roles/build/tools/t.md": "# t\n", "/_archive/2026-01-01/roles/build/old.md": NOTE, "/_conflicts/2026-01-01/shared/c.md": NOTE})
        self.apply(e, "/roles/build")
        dst, src = files_under(e.d("shared")), files_under(e.d("project"))
        self.assertIn("/roles/build/r.md", dst)
        self.assertNotIn("/roles/build/tools/t.md", dst)
        self.assertIn("/roles/build/tools/t.md", src)
        self.assertIn("/roles/build/INDEX.md", src)                       # the source keeps its index
        self.assertNotRegex(dst["/roles/build/INDEX.md"], r"INDEX\.md \|")  # and the target does not get the source's index as a row
        self.assertIn("/_archive/2026-01-01/roles/build/old.md", src)
        self.assertNotIn("/_archive/2026-01-01/roles/build/old.md", dst)
        self.assertNotIn("/_conflicts/2026-01-01/shared/c.md", dst)
        self.assertIn("/_conflicts/2026-01-01/shared/c.md", src)
        self.assertIn("project: shared", dst["/CANON.md"])                # the target keeps its own marker

    def test_a_missing_target_index_is_created_from_the_seed(self):
        e = self.two()
        os.unlink(os.path.join(e.d("shared"), "roles/build/INDEX.md"))
        self.apply(e, "/roles/build/r.md")
        self.assertRegex(rd(os.path.join(e.d("shared"), "roles/build/INDEX.md")), r"(?m)^\| r\.md \|")

    def test_structural_and_misplaced_paths_are_never_selected(self):
        e = self.two()
        before = e.snap()
        for path in ("/roles/build/INDEX.md", "/shared/INDEX.md", "/README.md", "/CANON.md", "/_template.md", "/_archive/x.md", "/_conflicts/x.md",
                     "/roles/build/tools/t.md", "/roles/build/none", "roles/build/r.md", "/roles/../CANON.md", "/roles/build/../../CANON.md", "/other/x.md", "/"):
            r = self.plan(e, path)
            self.assertEqual(r.returncode, 1, (path, r.stdout + r.stderr))
            self.assertNotIn("plan token", r.stdout, path)
        r = self.plan(e, "/roles/build/none")
        self.assertIn("no note under /roles/build/none in tier project", r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_the_tiers_must_differ_and_exist(self):
        e = self.two()
        before = e.snap()
        self.assertEqual(self.plan(e, "/roles/build/r.md", "project", "project").returncode, 1)
        r = self.plan(e, "/roles/build/r.md", "project", "system")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("tier system is missing: qargi memory init system", r.stdout + r.stderr)
        r = self.plan(e, "/roles/build/r.md", "project", "cloud")        # the store has no fixture: unreachable
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"tier cloud is unreachable|unreachable \(")
        self.assertEqual(self.plan(e, "/roles/build/r.md", "project", "frobnicate").returncode, 2)
        self.assertEqual(e.snap(), before)

    def test_a_collision_in_the_target_is_refused_with_nothing_changed(self):
        e = self.two()
        put(e.d("shared"), {"/roles/build/r.md": NOTE.replace("sandbox", "other")})
        before = e.snap()
        r = self.plan(e, "/roles/build/r.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("refused: /roles/build/r.md is also in tier shared; resolve it first (qargi memory check)", r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)
        r = self.plan(e, "/roles/build")                                  # one colliding note refuses the whole prefix
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_a_collision_in_a_third_tier_is_refused_with_nothing_changed(self):
        e = self.two(cloud={**seed_files(P), "/roles/build/r.md": NOTE})
        before = e.snap()
        r = self.plan(e, "/roles/build/r.md")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("refused: /roles/build/r.md is also in tier cloud; resolve it first (qargi memory check)", r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_a_stale_source_fails_the_apply_with_nothing_written(self):
        e = self.two()
        f = os.path.join(e.tmp, "plan.json")
        r = subprocess.run([sys.executable, "-I", TIERPLAN, "plan-move", "/roles/build/r.md", "--from", "project", "--to", "shared", "--project", P, "--out", f],
                           capture_output=True, text=True, env=e.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.isfile(f), "plan-move wrote no plan file")
        with open(f) as h:
            plan = json.load(h)
        self.assertIn("/roles/build/r.md", plan["source"]["expect"])      # the digests the plan read of the source
        put(e.d("project"), {"/roles/build/r.md": NOTE + "\nedited after the plan\n"})
        before = e.snap()
        r = subprocess.run([sys.executable, "-I", TIERPLAN, "apply", f], capture_output=True, text=True, env=e.env)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertRegex(r.stdout + r.stderr, r"changed since the plan was made|plan again")
        self.assertEqual(e.snap(), before)                                # neither tier was written

    def test_a_stale_plan_through_the_verb_is_not_applied(self):
        e = self.two()
        r = self.plan(e, "/roles/build/r.md")
        tok = self.token_of(r)
        put(e.d("project"), {"/roles/build/r.md": NOTE + "\nedited after the plan\n"})
        before = e.snap()
        r = e.qargi("memory", "move", "/roles/build/r.md", "--from", "project", "--to", "shared", "--project", P, "--plan", tok, "--approved", "test")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(e.snap(), before)

    def test_the_audit_log_names_the_move(self):
        e = self.two()
        self.apply(e, "/roles/build/r.md")
        verbs = [json.loads(l)["verb"] for l in rd(os.path.join(e.state, "audit.log")).splitlines()]
        self.assertIn("memory-move", verbs)
        self.assertIn("memory-move-applied", verbs)

    def test_a_repo_tier_end_prints_the_checkout_warning(self):
        e = self.two()
        self.git_repo(e)
        put(e.d("repo"), seed_files(P))
        r = self.plan(e, "/roles/build/r.md", "project", "repo")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("WARNING: this writes into the repository checkout %s at qargi/memory; qargi never commits it" % e.repo, r.stdout)

    def test_the_cloud_as_the_source(self):
        e = self.two(cloud={**seed_files(P), "/roles/build/c.md": NOTE})
        self.apply(e, "/roles/build/c.md", "cloud", "shared")
        self.assertIn("/roles/build/c.md", files_under(e.d("shared")))
        fx = [json.loads(l)["path"] for l in rd(os.path.join(e.fix, STORE + ".jsonl")).splitlines()]
        self.assertNotIn("/roles/build/c.md", fx)
        self.assertTrue([p for p in fx if re.match(r"/_archive/%s/roles/build/c\.md$" % DATE, p)], fx)

    def test_the_cloud_as_the_target(self):
        e = self.two(cloud=seed_files(P))
        self.apply(e, "/roles/build/r.md", "project", "cloud")
        fx = {}
        for l in rd(os.path.join(e.fix, STORE + ".jsonl")).splitlines():
            m = json.loads(l)
            fx[m["path"]] = m["content"]
        self.assertIn("/roles/build/r.md", fx)
        self.assertRegex(fx["/roles/build/r.md"], r"copied from tier-project:/roles/build/r\.md@[0-9a-f]{12}")
        self.assertNotIn("/roles/build/r.md", files_under(e.d("project")))


class SplitUnchanged(Base):
    """`memplan split` is refactored (archive_ops); what it plans stays the same."""
    def test_split_with_archive_keeps_its_plan(self):
        e = self.mk()
        src, dst, out = (os.path.join(e.tmp, n) for n in ("src", "dst", "plan.json"))
        put(src, {"/roles/build/r.md": NOTE, "/roles/build/INDEX.md": "# i\n"})
        put(dst, {})
        os.makedirs(dst, exist_ok=True)
        r = subprocess.run([sys.executable, "-I", MEMPLAN, "plan", "split", "--source", src, "--target", dst, "--prefix", "/roles/build/r.md", "--archive",
                            "--today", "2026-10-27", "--out", out], capture_output=True, text=True, env=e.env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        with open(out) as h:
            plan = json.load(h)
        self.assertEqual([(o["op"], o["path"]) for o in plan["target"]["ops"]], [("create", "/roles/build/r.md")])
        self.assertRegex(plan["target"]["ops"][0]["content"], r"Sources: [^\n]*; copied from [^:]+:/roles/build/r\.md@[0-9a-f]{12}")
        sops = plan["source"]["ops"]
        self.assertEqual([(o["op"], o["from"], o["to"]) for o in sops], [("archive", "/roles/build/r.md", "/_archive/2026-10-27/roles/build/r.md")])
        self.assertRegex(sops[0]["content"], r"archived from /roles/build/r\.md@[0-9a-f]{12} on 2026-10-27")
        self.assertEqual(plan["source"]["expect"]["/_archive/2026-10-27/roles/build/r.md"], None)
        self.assertEqual(plan["verb"], "split")


if __name__ == "__main__":
    unittest.main()
