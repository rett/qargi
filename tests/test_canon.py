#!/usr/bin/env python3
"""Reconciler tests on synthetic stores (no API, no private data).
Run: python3 tests/test_canon.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
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
        args += ["--seed", SEED, "--today", TODAY]
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

    def test_empty_store_plans_the_full_seed_and_the_marker(self):
        """The set-up of an empty store: the seed's own files, nothing moved, the marker last. Tier init (`memory init`) and
        a new project's stores both start here."""
        roles = ["build", "write"]
        subs = {"{{PROJECT}}": "demo", "{{ROLES}}": C.role_lines(roles), "{{ROLE_LIST}}": "build write"}
        for kind in ("memory", "reference"):
            p = plan(kind, {})
            self.assertEqual(p["to_version"], C.LATEST)
            self.assertEqual(p["notes"], [])
            self.assertEqual({o["op"] for o in p["ops"]}, {"create", "marker"})
            self.assertEqual(p["ops"][-1]["path"], "/CANON.md", "the marker is written last")
            self.assertEqual(sorted(o["path"] for o in p["ops"]),
                             sorted(["/CANON.md", "/README.md", "/_template.md", "/shared/INDEX.md", "/roles/build/INDEX.md", "/roles/write/INDEX.md"]))
            by = {o["path"]: o["content"] for o in p["ops"]}
            self.assertEqual(by["/README.md"], C.seed_text(SEED, "README.%s.md" % kind, subs))
            self.assertEqual(by["/_template.md"], slurp(os.path.join(SEED, "_template.%s.md" % kind)))
            self.assertEqual(by["/shared/INDEX.md"], C.seed_text(SEED, "INDEX.shared.%s.md" % kind, subs))
            self.assertEqual(by["/roles/write/INDEX.md"], C.seed_text(SEED, "INDEX.role.%s.md" % kind, dict(subs, **{"{{ROLE}}": "write"})))
            m = C.parse_marker(by["/CANON.md"])
            self.assertEqual((m["canon"], m["kind"], m["project"], m["roles"]), (str(C.LATEST), kind, "demo", "build write"))

    def test_interrupted_setup_resumes(self):
        """The set-up writes its files in order and the marker last, so a run that stops part-way leaves a store with
        set-up files and no marker. That store is still empty for the canon: a rerun creates what is missing, leaves
        what is there as it is, and writes the marker last."""
        for kind in ("memory", "reference"):
            full = plan(kind, {})["ops"]
            order = [o["path"] for o in full if o["op"] == "create"]
            self.assertEqual(order[0], "/shared/INDEX.md")
            for k in range(1, len(order)):               # every point the run could have stopped at
                done = {o["path"]: "edited " + o["path"] for o in full[:k]}
                p = plan(kind, done)
                what = "%s, %d of %d files written" % (kind, k, len(order))
                self.assertEqual(p["from_version"], "empty", what)
                self.assertEqual([o["path"] for o in p["ops"]], order[k:] + ["/CANON.md"], what)
                self.assertEqual(p["ops"][-1]["op"], "marker", what)
                _, after = self.assertConverges(kind, done)
                for path, content in done.items():
                    self.assertEqual(after[path], content, "%s: %s is not overwritten" % (what, path))
                self.assertEqual(sorted(after), sorted(order + ["/CANON.md"]), what)

    def test_setup_files_that_do_not_follow_the_setup_order_are_unknown(self):
        """Only what an interrupted set-up leaves counts as empty; a hand-made or older store without a marker does not."""
        for kind in ("memory", "reference"):
            for what, files in {"a note beside the set-up files": {"/shared/INDEX.md": "i", "/shared/a.md": "# a\n"},
                                "set-up files that skip the shared index": {"/roles/build/INDEX.md": "i"},
                                "the template and the readme without the indexes": {"/_template.md": "t", "/README.md": "r"},
                                "a role the project does not have": {"/shared/INDEX.md": "i", "/roles/other/INDEX.md": "i"}}.items():
                p = plan(kind, files)
                self.assertEqual((p["from_version"], p["ops"]), ("unknown", []), "%s: %s" % (kind, what))

    def test_unknown_layout_is_reported(self):
        self.assertEqual(plan("memory", {"/stuff/x.md": "x"})["from_version"], "unknown")

    def test_layouts_older_than_canon_2_are_unknown(self):
        """The chains from the layouts before the canon, the draft marker and canon 1 are gone: such a store is
        reported as unknown and nothing is planned (a hand-made layout is the owner's to move or import)."""
        old = {"before the canon, memory": ("memory", {"/README.md": "# old\n", "/sandbox/a.md": "# a\n", "/repos/demo/INDEX.md": "x"}),
               "before the canon, reference": ("reference", {"/README.md": "# idx\n", "/01-rules/rules.md": "# R\n"}),
               "a half-moved store": ("memory", {"/README.md": "r", "/_template.md": "t", "/shared/sandbox/a.md": "# a\n"}),
               "only index files": ("memory", {"/README.md": "r", "/_template.md": "t"}),
               "draft marker": ("memory", {"/CANON.md": "# Canon\n\ncanon: 0\nkind: memory\nproject: demo\nroles: build\n", "/README.md": "r"}),
               "canon 1": ("memory", {"/CANON.md": "# Canon\n\ncanon: 1\nkind: memory\nproject: demo\nroles: build\n", "/README.md": "r"})}
        for what, (kind, files) in old.items():
            p = plan(kind, files, roles="build")
            self.assertEqual((p["from_version"], p["ops"]), ("unknown", []), what)
            self.assertTrue(p["notes"], what)
            r = run("check", kind, files, roles="build")
            self.assertEqual(r.returncode, 1, what)
            self.assertIn("store is unknown", r.stdout, what)
        self.assertIn("older than the 2", plan("memory", old["canon 1"][1], roles="build")["why"])

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

    def test_a_newer_marker_is_not_downgraded(self):
        files = {"/CANON.md": "# Canon\n\ncanon: 5\nkind: memory\nproject: demo\nroles: build\n", "/README.md": "r"}
        p = plan("memory", files, roles="build")
        self.assertEqual(p["from_version"], "unknown")
        self.assertEqual(p["ops"], [])

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

    def test_cross_role_folder_for_unused_role_fails(self):
        _, after = self.assertConverges("memory", {})
        after["/roles/ghost/INDEX.md"] = "x"
        self.assertEqual(run("check", "memory", after).returncode, 1)

    def test_seed_readme_keeps_shared_curated(self):
        text = slurp(os.path.join(SEED, "README.memory.md"))
        plain = text.replace("`", "")                  # the seed writes paths in code spans
        self.assertIn("Write only under roles/<your role>/", plain)
        self.assertIn("shared/ is curated", plain)
        self.assertNotIn("Write only under shared/", plain)
        self.assertLess(len(text), 3000)


if __name__ == "__main__":
    unittest.main(verbosity=1)
