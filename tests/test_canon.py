#!/usr/bin/env python3
"""Reconciler tests on synthetic stores (no API, no private data).
Run: python3 tests/test_canon.py"""
import datetime, json, os, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
SEED = os.path.join(HERE, "..", "provision", "canon-seed")
sys.path.insert(0, LIB)
import canon as C  # noqa: E402

TODAY = "2026-10-27"
GOOD = "Kind: setup\nApplies to: any\nCheck: true\nVerified: %s by test\n" % datetime.date.today().isoformat()


def write(files):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for i, (p, c) in enumerate(sorted(files.items())):
        f.write(json.dumps({"type": "memory", "id": "m%d" % i, "path": p, "content": c, "content_sha256": ""}) + "\n")
    f.close()
    return f.name


def run(cmd, kind, files, roles="dev,docs"):
    st = write(files)
    args = [sys.executable, os.path.join(LIB, "canon.py"), cmd, "--kind", kind, "--project", "demo", "--roles", roles, "--store", st]
    if cmd == "plan":
        args += ["--default-role", "dev", "--seed", SEED, "--today", TODAY]
    r = subprocess.run(args, capture_output=True, text=True)
    os.unlink(st)
    return r


def plan(kind, files, roles="dev,docs"):
    return json.loads(run("plan", kind, files, roles).stdout)


def apply_plan(files, p):
    mems = {k: {"type": "memory", "id": "m_%s" % k, "path": k, "content": v, "content_sha256": ""} for k, v in files.items()}
    out = C.simulate(mems, p["ops"])
    return {k: v["content"] for k, v in out.items()}


def converge(kind, files, roles="dev,docs"):
    p = plan(kind, files, roles)
    after = apply_plan(files, p)
    again = plan(kind, after, roles)
    chk = run("check", kind, after, roles)
    return p, after, again, chk


class Canon(unittest.TestCase):
    def assertConverges(self, kind, files, roles="dev,docs"):
        p, after, again, chk = converge(kind, files, roles)
        self.assertEqual(again["from_version"], 1, again)
        self.assertEqual(again["ops"], [], "second plan must be a no-op: %s" % again["ops"])
        self.assertEqual(chk.returncode, 0, chk.stdout)
        return p, after

    def test_empty_store(self):
        for kind in ("memory", "reference"):
            self.assertConverges(kind, {})

    def test_legacy_memory(self):
        files = {"/README.md": "# old\n\n| Path | Purpose | Load when |\n|---|---|---|\n| sandbox/a.md | a | always |\n",
                 "/_template.md": "t", "/sandbox/a.md": "# a\n" + GOOD,
                 "/repos/demo/INDEX.md": "| setup/s.md | s | x |\n", "/repos/demo/setup/s.md": "# s\n" + GOOD}
        p, after = self.assertConverges("memory", files)
        self.assertIn("/shared/sandbox/a.md", after)
        self.assertIn("sandbox/a.md", after["/shared/INDEX.md"])  # index rows were carried over

    def test_legacy_reference_numbers_become_names(self):
        files = {"/README.md": "# idx\n01-rules/rules.md\n", "/01-rules/rules.md": "see 02-workflow/w.md\n", "/02-workflow/w.md": "w\n"}
        p, after = self.assertConverges("reference", files)
        self.assertIn("/roles/dev/rules/rules.md", after)
        self.assertEqual(after["/roles/dev/rules/rules.md"], "see workflow/w.md\n")

    def test_draft_marker_is_migrated(self):
        files = {"/CANON.md": "# Canon\n\ncanon: 2\nkind: reference\nproject: demo\nroles: dev docs\n",
                 "/README.md": "r", "/shared/INDEX.md": "s", "/roles/dev/INDEX.md": "d", "/roles/docs/INDEX.md": "d",
                 "/roles/dev/01-rules/rules.md": "x 01-rules y\n"}
        p, after = self.assertConverges("reference", files)
        self.assertEqual(after["/roles/dev/rules/rules.md"], "x rules y\n")
        self.assertIn("canon: 1", after["/CANON.md"])

    def test_interrupted_migration_resumes(self):
        # moves done, nothing else: no marker, no shared index
        files = {"/README.md": "old readme", "/_template.md": "t", "/shared/sandbox/a.md": "# a\n" + GOOD}
        self.assertEqual(plan("memory", files)["from_version"], "legacy")
        self.assertConverges("memory", files)

    def test_unknown_layout_is_reported(self):
        self.assertEqual(plan("memory", {"/stuff/x.md": "x"})["from_version"], "unknown")

    def test_role_added_after_the_fact(self):
        _, after = self.assertConverges("memory", {}, roles="dev")
        p = plan("memory", after, roles="dev,docs")
        self.assertEqual(p["from_version"], 1)
        paths = [o["path"] for o in p["ops"]]
        self.assertIn("/roles/docs/INDEX.md", paths)
        self.assertIn("/CANON.md", paths)
        after2 = apply_plan(after, p)
        self.assertEqual(run("check", "memory", after2, "dev,docs").returncode, 0)

    def test_dropped_role_is_reported_not_removed(self):
        _, after = self.assertConverges("memory", {}, roles="dev,docs")
        after["/roles/docs/x.md"] = "x"
        p = plan("memory", after, roles="dev")
        self.assertTrue(any("docs" in n for n in p["notes"]))
        self.assertFalse(any(o["op"] == "move" for o in p["ops"]))

    def test_conflict_goes_to_conflicts_not_overwritten(self):
        files = {"/README.md": "r", "/sandbox/a.md": "new", "/shared/sandbox/a.md": "existing"}
        p = plan("memory", files)
        moves = [o for o in p["ops"] if o["op"] == "move"]
        self.assertTrue(moves and moves[0]["to"].startswith("/_conflicts/"), moves)

    def test_canon_one_check_is_structural_only(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/sandbox/x.md"] = "# x\nKind: setup\n"   # incomplete recipe: not a canon 1 matter
        self.assertEqual(run("check", "memory", after).returncode, 0)

    def test_content_rules_catch_incomplete_recipes_and_secrets(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/sandbox/x.md"] = "# x\nKind: setup\n"
        after["/shared/sandbox/y.md"] = "token = abcdefghijklmnop\n"
        st = write(after)
        r = subprocess.run([sys.executable, os.path.join(LIB, "canon.py"), "content", "--kind", "memory", "--store", st], capture_output=True, text=True)
        os.unlink(st)
        self.assertEqual(r.returncode, 1)
        self.assertIn("no Applies to", r.stdout)
        self.assertIn("looks like a secret", r.stdout)

    def test_cross_role_folder_for_unused_role_fails(self):
        _, after = self.assertConverges("memory", {})
        after["/roles/ghost/INDEX.md"] = "x"
        self.assertEqual(run("check", "memory", after).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
