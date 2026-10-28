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
GOOD = "Kind: sandbox\nApplies to: any\nSources: test run\nCheck: true\nVerified: %s by test\n" % datetime.date.today().isoformat()


def slurp(path):
    with open(path) as f:
        return f.read()


def write(files):
    f = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    for i, (p, c) in enumerate(sorted(files.items())):
        f.write(json.dumps({"type": "memory", "id": "m%d" % i, "path": p, "content": c, "content_sha256": ""}) + "\n")
    f.close()
    return f.name


def run(cmd, kind, files, roles="build,write"):
    st = write(files)
    args = [sys.executable, os.path.join(LIB, "canon.py"), cmd, "--kind", kind, "--project", "demo", "--roles", roles, "--store", st]
    if cmd == "plan":
        args += ["--default-role", "build", "--seed", SEED, "--today", TODAY]
    r = subprocess.run(args, capture_output=True, text=True)
    os.unlink(st)
    return r


def plan(kind, files, roles="build,write"):
    return json.loads(run("plan", kind, files, roles).stdout)


def apply_plan(files, p):
    mems = {k: {"type": "memory", "id": "m_%s" % k, "path": k, "content": v, "content_sha256": ""} for k, v in files.items()}
    out = C.simulate(mems, p["ops"])
    return {k: v["content"] for k, v in out.items()}


def converge(kind, files, roles="build,write"):
    p = plan(kind, files, roles)
    after = apply_plan(files, p)
    again = plan(kind, after, roles)
    chk = run("check", kind, after, roles)
    return p, after, again, chk


class Canon(unittest.TestCase):
    def assertConverges(self, kind, files, roles="build,write"):
        p, after, again, chk = converge(kind, files, roles)
        self.assertEqual(again["from_version"], C.LATEST, again)
        self.assertEqual(again["ops"], [], "second plan must be a no-op: %s" % again["ops"])
        self.assertEqual(chk.returncode, 0, chk.stdout)
        return p, after

    def test_empty_store(self):
        for kind in ("memory", "reference"):
            self.assertConverges(kind, {})

    def test_legacy_memory(self):
        files = {"/README.md": "# old\n\n| Path | Purpose | Load when |\n|---|---|---|\n| sandbox/a.md | a | always |\n| repos/demo/INDEX.md | d | x |\n",
                 "/_template.md": "t", "/sandbox/a.md": "# a\n" + GOOD,
                 "/repos/demo/INDEX.md": "| Path | Purpose | Load when |\n|---|---|---|\n| setup/s.md | s | x |\n",
                 "/repos/demo/setup/s.md": "# s\n" + GOOD.replace("sandbox", "setup")}
        p, after = self.assertConverges("memory", files)
        self.assertIn("/shared/sandbox/a.md", after)
        self.assertIn("sandbox/a.md", after["/shared/INDEX.md"])  # index rows were carried over

    def test_legacy_reference_numbers_become_names(self):
        files = {"/README.md": "# idx\n01-rules/rules.md\n", "/01-rules/rules.md": "# R\n\nsee 02-workflow/w.md\n", "/02-workflow/w.md": "# W\n\nw\n"}
        p, after = self.assertConverges("reference", files)
        self.assertIn("/roles/build/rules/rules.md", after)
        self.assertTrue(after["/roles/build/rules/rules.md"].endswith("\nsee workflow/w.md\n"))

    def test_draft_marker_is_migrated(self):
        files = {"/CANON.md": "# Canon\n\ncanon: 0\nkind: reference\nproject: demo\nroles: build write\n",
                 "/README.md": "r", "/shared/INDEX.md": "s", "/roles/build/INDEX.md": "d", "/roles/write/INDEX.md": "d",
                 "/roles/build/01-rules/rules.md": "# R\n\nx 01-rules y\n"}
        p, after = self.assertConverges("reference", files)
        self.assertTrue(after["/roles/build/rules/rules.md"].endswith("\nx rules y\n"))
        self.assertIn("canon: 2", after["/CANON.md"])

    def test_interrupted_migration_resumes(self):
        # moves done, nothing else: no marker, no shared index
        files = {"/README.md": "old readme", "/_template.md": "t", "/shared/sandbox/a.md": "# a\n" + GOOD}
        self.assertEqual(plan("memory", files)["from_version"], "legacy")
        self.assertConverges("memory", files)

    def test_unknown_layout_is_reported(self):
        self.assertEqual(plan("memory", {"/stuff/x.md": "x"})["from_version"], "unknown")

    def test_role_added_after_the_fact(self):
        _, after = self.assertConverges("memory", {}, roles="build")
        p = plan("memory", after, roles="build,write")
        self.assertEqual(p["from_version"], C.LATEST)
        paths = [o["path"] for o in p["ops"]]
        self.assertIn("/roles/write/INDEX.md", paths)
        self.assertIn("/CANON.md", paths)
        after2 = apply_plan(after, p)
        self.assertEqual(run("check", "memory", after2, "build,write").returncode, 0)
        self.assertIn("roles/write/INDEX.md", after2["/README.md"])      # the README's role list follows

    def test_dropped_role_is_reported_not_removed(self):
        _, after = self.assertConverges("memory", {}, roles="build,write")
        after["/roles/write/x.md"] = "x"
        p = plan("memory", after, roles="build")
        self.assertTrue(any("write" in n for n in p["notes"]))
        self.assertFalse(any(o["op"] == "move" for o in p["ops"]))

    def test_conflict_goes_to_conflicts_not_overwritten(self):
        files = {"/README.md": "r", "/sandbox/a.md": "new", "/shared/sandbox/a.md": "existing"}
        p = plan("memory", files)
        moves = [o for o in p["ops"] if o["op"] == "move"]
        self.assertTrue(moves and moves[0]["to"].startswith("/_conflicts/"), moves)

    def test_note_rules_catch_incomplete_notes_and_secrets(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/sandbox/x.md"] = "# x\nKind: sandbox\n"
        after["/shared/sandbox/y.md"] = "# y\n" + GOOD + "token = abcd1234efgh5678ijkl\n"
        after["/shared/sandbox/z.md"] = "# z\n" + GOOD + "A fine-grained token: Contents read/write; token: process.env.CMA_GITHUB_TOKEN\n"
        r = run("check", "memory", after)
        self.assertEqual(r.returncode, 1)
        for want in ("x.md: no Applies to", "x.md: no Sources", "x.md: no Check", "x.md: no Verified", "y.md: looks like a secret"):
            self.assertIn(want, r.stdout)
        self.assertNotIn("FAIL /shared/sandbox/z.md", r.stdout)   # prose about tokens is not a secret

    def test_kind_must_match_store_and_folder(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/repos/demo/INDEX.md"] = "| Path | Purpose | Load |\n|---|---|---|\n| pitfalls/a.md | a | x |\n"
        after["/shared/INDEX.md"] += "| repos/demo/INDEX.md | demo | x |\n"
        after["/shared/repos/demo/pitfalls/a.md"] = "# a\n" + GOOD.replace("sandbox", "setup")   # Kind: setup in pitfalls/
        after["/shared/sandbox/b.md"] = "# b\n" + GOOD.replace("sandbox", "rule")
        r = run("check", "memory", after)
        self.assertIn("a.md: Kind is setup, this folder holds pitfall", r.stdout)
        self.assertIn("b.md: Kind is rule", r.stdout)

    def test_staleness_future_and_unrecorded_sources(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/sandbox/old.md"] = "# o\n" + GOOD.replace(datetime.date.today().isoformat(), "2020-01-01")
        after["/shared/sandbox/new.md"] = "# n\n" + GOOD.replace(datetime.date.today().isoformat(), "2999-01-01")
        after["/shared/sandbox/src.md"] = "# s\n" + GOOD.replace("test run", "origin not recorded")
        r = run("check", "memory", after)
        self.assertIn("old.md: verified", r.stdout)
        self.assertIn("new.md: Verified date is in the future", r.stdout)
        self.assertIn("src.md: Sources: origin not recorded", r.stdout)

    def test_verified_date_is_judged_in_utc(self):
        """The cloud agents date their notes in UTC; a machine west of it must not call today's note a future one."""
        _, after = self.assertConverges("memory", {})
        utc = datetime.datetime.now(datetime.timezone.utc).date().isoformat()
        after["/shared/sandbox/today.md"] = "# t\n" + GOOD.replace(datetime.date.today().isoformat(), utc)
        old = os.environ.get("TZ")
        os.environ["TZ"] = "Etc/GMT+12"
        try:
            r = run("check", "memory", after)
        finally:
            os.environ.pop("TZ") if old is None else os.environ.__setitem__("TZ", old)
        self.assertNotIn("today.md: Verified date is in the future", r.stdout)

    def test_reference_document_notes(self):
        _, after = self.assertConverges("reference", {})
        after["/shared/INDEX.md"] += "| rules/r.md | r | always |\n"
        after["/shared/rules/r.md"] = "# r\n\nKind: rule\nApplies to: demo\nSources: docs/x.md@abc1234\n\n## Contents\n\nbe nice\n"
        self.assertEqual(run("check", "reference", after).returncode, 0)
        after["/shared/rules/q.md"] = "# q\n\nKind: setup\nApplies to: demo\nSources: x\n"      # a memory kind
        self.assertIn("q.md: Kind is setup, this store's kinds are", run("check", "reference", after).stdout)

    def test_tools_and_indexes_are_not_notes(self):
        _, after = self.assertConverges("reference", {})
        after["/roles/build/tools/run.py"] = "print(1)\n"
        after["/roles/build/tools/README.md"] = "no header\n"
        r = run("check", "reference", after)
        self.assertNotIn("no Kind", r.stdout)

    def test_v1_store_gains_headers_and_keeps_bodies(self):
        v1 = {"/CANON.md": "# Canon\n\ncanon: 1\nkind: memory\nproject: demo\nroles: build write\n",
              "/README.md": "custom readme\n", "/_template.md": slurp(os.path.join(SEED, "v1", "_template.md")),
              "/shared/INDEX.md": "| Path | Purpose | Load when |\n|---|---|---|\n| repos/demo/INDEX.md | d | x |\n",
              "/roles/build/INDEX.md": "x", "/roles/write/INDEX.md": "x",
              "/shared/repos/demo/INDEX.md": "| Path | Purpose | Load when |\n|---|---|---|\n| pitfalls/a.md | a | x |\n",
              "/shared/repos/demo/pitfalls/a.md": "# a\n\nKind: pitfall\nApplies to: demo\n\nFact: f\n\nCheck: true\nVerified: %s by run7 on linux\n" % datetime.date.today().isoformat(),
              "/roles/write/project/history.md": "# History\n\nlines\n"}
        p, after = self.assertConverges("memory", v1)
        self.assertEqual(p["from_version"], 1)
        a = after["/shared/repos/demo/pitfalls/a.md"]
        self.assertIn("Sources: run7, %s" % datetime.date.today().isoformat(), a)
        self.assertIn("Fact: f\n", a)
        h = after["/roles/write/project/history.md"]
        self.assertTrue(h.startswith("# History\n\nKind: history\nApplies to: demo\nSources: carried over"), h)
        self.assertTrue(h.endswith("\nlines\n"))
        self.assertIn("| Load |", after["/shared/INDEX.md"])
        self.assertIn("canon: 2", after["/CANON.md"])
        self.assertEqual(after["/_conflicts/%s/README.md" % TODAY], "custom readme\n")   # a customised README is kept
        self.assertIn("Kind: setup | gate", after["/_template.md"])

    def test_unedited_v1_readme_is_replaced_without_conflict(self):
        text = slurp(os.path.join(SEED, "v1", "README.memory.md")).replace("{{PROJECT}}", "demo")
        text = text.replace("{{ROLES}}", C.role_lines(["build", "write"]))
        v1 = {"/CANON.md": "# Canon\n\ncanon: 1\nkind: memory\nproject: demo\nroles: build write\n", "/README.md": text,
              "/shared/INDEX.md": "x", "/roles/build/INDEX.md": "x", "/roles/write/INDEX.md": "x"}
        p, after = self.assertConverges("memory", v1)
        self.assertFalse([k for k in after if k.startswith("/_conflicts/")])
        self.assertIn("Sources", after["/README.md"])

    def test_vocabulary_matches_layout_json(self):
        lay = json.loads(slurp(os.path.join(HERE, "..", "canon", "layout.json")))
        self.assertEqual(lay["version"], C.LATEST)
        for k in C.KINDS:
            self.assertEqual(tuple(lay["note_kinds"][k]["runnable"]), C.RUNNABLE[k])
            self.assertEqual(tuple(lay["note_kinds"][k]["document"]), C.DOCUMENT[k])
        self.assertEqual(lay["limits"], C.LIMITS)
        self.assertEqual(tuple(lay["header"]), C.HEADER)

    def test_header_fields_are_inserted_in_canonical_order(self):
        c, added = C.add_header("memory", "/shared/sandbox/a.md",
                                "# a\n\nKind: sandbox\nApplies to: any\n\nFact: f\n\nCheck: true\nVerified: 2026-10-01 by r on x\n", "demo", TODAY)
        self.assertEqual(added, ["Sources"])
        self.assertTrue(c.startswith("# a\n\nKind: sandbox\nApplies to: any\nSources: r, 2026-10-01\n\nFact: f"), c)

    def test_fenced_lines_are_not_header_fields(self):
        body = "# b\n\n```\n$ make gate\nCheck: ok\n```\n"
        self.assertEqual(C.note_fields(body), {})
        c, _ = C.add_header("memory", "/shared/sandbox/b.md", body, "demo", TODAY)
        self.assertTrue(c.startswith("# b\n\nKind: sandbox\nApplies to: any\nSources:"), c)
        self.assertTrue(c.endswith(body.split("\n\n", 1)[1]))

    def test_customised_readme_survives_the_draft_chain(self):
        files = {"/CANON.md": "# Canon\n\ncanon: 0\nkind: memory\nproject: demo\nroles: build write\n", "/README.md": "my custom readme\n",
                 "/shared/INDEX.md": "x", "/roles/build/INDEX.md": "x", "/roles/write/INDEX.md": "x"}
        p, after = self.assertConverges("memory", files)
        self.assertEqual(after["/_conflicts/%s/README.md" % TODAY], "my custom readme\n")

    def test_customised_template_is_kept_in_conflicts(self):
        v1 = {"/CANON.md": "# Canon\n\ncanon: 1\nkind: memory\nproject: demo\nroles: build write\n", "/_template.md": "mine\n", "/README.md": "r",
              "/shared/INDEX.md": "x", "/roles/build/INDEX.md": "x", "/roles/write/INDEX.md": "x"}
        p, after = self.assertConverges("memory", v1)
        self.assertEqual(after["/_conflicts/%s/_template.md" % TODAY], "mine\n")
        self.assertIn("Sources:", after["/_template.md"])

    def test_a_newer_marker_is_not_downgraded(self):
        files = {"/CANON.md": "# Canon\n\ncanon: 5\nkind: memory\nproject: demo\nroles: build\n", "/README.md": "r"}
        p = plan("memory", files, roles="build")
        self.assertEqual(p["from_version"], "unknown")
        self.assertEqual(p["ops"], [])

    def test_index_edit_is_anchored_to_the_header_row(self):
        t = "| Path | Purpose | Load when |\n|---|---|---|\n| a.md | Path map of demo | Load when touching demo |\n"
        self.assertEqual(C.fix_index(t), "| Path | Purpose | Load |\n|---|---|---|\n| a.md | Path map of demo | Load when touching demo |\n")

    def test_role_readme_is_a_note_and_repo_rules_are_rules(self):
        self.assertTrue(C.is_note("/roles/write/maintainer/README.md"))
        self.assertFalse(C.is_note("/roles/write/tools/README.md"))
        self.assertTrue(C.is_note("/shared/tools/x.md"))
        self.assertEqual(C.kind_for("reference", "/shared/repos/demo/rules/x.md"), "rule")

    def test_version_strings_are_not_addresses(self):
        _, after = self.assertConverges("memory", {})
        after["/shared/INDEX.md"] += "| sandbox/v.md | v | x |\n"
        after["/shared/sandbox/v.md"] = "# v\n" + GOOD + "pam-tacplus-1.7.0.1 and v1.2.3.4 and 8.8.4.4\n"
        out = run("check", "memory", after).stdout
        self.assertIn("address 8.8.4.4", out)
        self.assertNotIn("1.7.0.1", out)
        self.assertNotIn("1.2.3.4", out)

    def test_import_reports_an_underivable_kind(self):
        src = {"/README.md": "# i\n", "/07-project/notes.md": "# N\n\nx\n"}
        out = subprocess.run([sys.executable, os.path.join(LIB, "canon.py"), "import", "--map", "docs-v0", "--project", "demo", "--role", "write",
                              "--src", write(src), "--memory", write({}), "--reference", write({}), "--today", TODAY], capture_output=True, text=True)
        self.assertTrue(any("set Kind: by hand" in n for n in json.loads(out.stdout)["notes"]))

    def test_load_triggers_and_budget(self):
        _, after = self.assertConverges("reference", {})
        after["/shared/INDEX.md"] = ("| Path | Purpose | Load |\n|---|---|---|\n| rules/a.md | a | always |\n| rules/b.md | b | when unsure what is wanted |\n"
                                     "| rules/c.md | c | working on x |\n| rules/d.md | d | running make lint |\n")
        for n in "abcd":
            after["/shared/rules/%s.md" % n] = "# %s\n\nKind: rule\nApplies to: demo\nSources: x\n\n%s\n" % (n, "x" * (6000 if n == "a" else 10))
        out = run("check", "reference", after).stdout
        self.assertIn("Load of rules/b.md is 'when unsure what is wanted'", out)
        self.assertIn("Load of rules/c.md is 'working on x'", out)
        self.assertNotIn("Load of rules/d.md", out)
        self.assertNotIn("always-loaded set", out)          # 6 KB is inside the budget
        after["/shared/rules/a.md"] = after["/shared/rules/a.md"] + "y" * 4000
        out = run("check", "reference", after).stdout
        self.assertIn("always-loaded set of the build role", out)
        self.assertIn("chars; split it", out)               # and the note itself is over 10000

    def test_import_adds_the_header(self):
        src = {"/README.md": "# idx\n", "/01-rules/rules.md": "# Rules\n\nSources: x\n\nbe nice\n"}
        s, m, r = write(src), write({}), write({})
        out = subprocess.run([sys.executable, os.path.join(LIB, "canon.py"), "import", "--map", "docs-v0", "--project", "demo",
                              "--role", "write", "--src", s, "--memory", m, "--reference", r, "--today", TODAY], capture_output=True, text=True)
        imp = json.loads(out.stdout)
        c = [o for o in imp["reference"] if o["path"].endswith("rules/rules.md")][0]["content"]
        self.assertIn("Kind: rule\nApplies to: demo\n", c)
        self.assertIn("be nice\n", c)

    def test_cross_role_folder_for_unused_role_fails(self):
        _, after = self.assertConverges("memory", {})
        after["/roles/ghost/INDEX.md"] = "x"
        self.assertEqual(run("check", "memory", after).returncode, 1)


if __name__ == "__main__":
    unittest.main(verbosity=1)
