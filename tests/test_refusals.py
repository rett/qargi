#!/usr/bin/env python3
"""The catalogue of refusals (lib/refusals.json) and lib/refusal.py: the schema and its lint, the renderer (the contract line, the human lines, a
digest for what a lead chose, a list as three and +N, `notice`), the codes a source file raises against the catalogue, the seat codes against the
contract page (skipped, with a line saying so, when the page is absent), the generated page and the ratchet of unclassified `die` calls.
Offline; a scratch home; no project. Run: python3 tests/test_refusals.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import copy, json, os, re, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
sys.path.insert(0, LIB)
import refusal as R  # noqa: E402

PY = [sys.executable, "-B", "-I"]


def real():
    return R.load(ROOT)


def entry(**over):
    """A catalogue entry that passes the lint, changed by over."""
    e = {"rule": "A rule", "why": "a reason", "class": "demo", "exit": 1, "status": "live",
         "fields": {"verb": "verb", "moved": "label-list", "ref": "ref", "refs": "ref-list", "n": "count", "context": "enum:lead,host"},
         "message": "{verb} moved {moved} at {ref} ({refs}, {n})",
         "next": {"lead": "lead: fix {ref}", "host": "host: fix {ref}"}}
    e.update(over)
    return e


def demo(**over):
    return {"schema": 1, "codes": {"demo-code": entry(**over)}}


class Tree(unittest.TestCase):
    """A scratch root laid out like the repository, for the checks that read files."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="refroot.")
        self.addCleanup(shutil.rmtree, self.root, True)
        for d in ("lib", "docs/reference", "tests"):
            os.makedirs(os.path.join(self.root, d))

    def put(self, rel, text):
        with open(os.path.join(self.root, rel), "w", encoding="utf-8") as f:
            f.write(text)

    def cat(self, cat):
        self.put(R.CATALOGUE, json.dumps(cat))


class TheCatalogue(unittest.TestCase):
    def test_the_real_catalogue_passes_the_lint(self):
        problems, notes = R.check(ROOT)
        self.assertEqual(problems, [])

    def test_it_holds_the_verify_environment_codes_the_design_codes_and_the_seat_codes(self):
        codes = real()["codes"]
        self.assertEqual(sum(1 for e in codes.values() if e["class"] == "verify-environment"), 14)
        for c in ("plan-missing", "plan-stale", "approval-missing", "approval-inside-run", "cut-not-covering", "cut-lead-changed", "cut-branch-moved",
                  "cut-fix-outside", "release-notes-empty", "release-fragments-unfolded", "feature-runs-open", "ro-write-outside", "ro-second-tree",
                  "ro-env-restricted", "member-push", "member-lead-verb", "member-run-record"):
            self.assertIn(c, codes)
        self.assertEqual(sum(1 for e in codes.values() if e["class"] in R.SEAT_CLASSES), 31)
        self.assertEqual(len(codes), 14 + 17 + 31)

    def test_each_code_has_every_key_and_its_templates_name_only_its_fields(self):
        for code, e in real()["codes"].items():
            with self.subTest(code=code):
                self.assertTrue({"rule", "why", "class", "exit", "status", "fields", "message", "next"} <= set(e))
                self.assertEqual(set(e["next"]), {"lead", "host"})
                self.assertNotIn("{", e["why"], "why is static")
                for text in (e["message"], e["next"]["lead"], e["next"]["host"]):
                    self.assertLessEqual(set(R.PLACEHOLDER.findall(text)), set(e["fields"]))

    def test_the_lint_rejects_what_breaks_a_rule(self):
        self.assertEqual(R.check_catalogue(demo()), [])
        cases = {
            "an unknown placeholder": demo(message="{nowhere}"),
            "a why with a placeholder": demo(why="because {verb}"),
            "an exit that no class uses": demo(exit=3),
            "a seat-gate code that exits 1": demo(**{"class": "seat-gate"}),
            "an unknown status": demo(status="maybe"),
            "an unknown field type": demo(fields={"x": "string"}, message="m", next={"lead": "a", "host": "a"}),
            "a next with no host": demo(next={"lead": "x"}),
            "two nexts that differ and no context": demo(fields={"verb": "verb"}, message="{verb}", next={"lead": "a", "host": "b"}),
            "a context that is not lead or host": demo(fields={"context": "enum:lead"}, message="m", next={"lead": "a", "host": "a"}),
            "an extra key": demo(extra=1),
            "an empty rule": demo(rule=" "),
            "a verb field of another type": demo(fields={"verb": "label"}, message="m", next={"lead": "a", "host": "a"}),
        }
        for name, cat in cases.items():
            with self.subTest(name):
                self.assertTrue(R.check_catalogue(cat), name)
        self.assertTrue(R.check_catalogue({"schema": 2, "codes": {}}))
        self.assertTrue(R.check_catalogue({"schema": 1, "codes": {"Bad_Code": entry()}}))
        self.assertTrue(R.check_catalogue({"schema": 1, "codes": {}, "extra": 1}))

    def test_a_code_is_never_reused_so_the_file_lists_each_once(self):
        objects = []
        with open(os.path.join(LIB, "refusals.json"), encoding="utf-8") as f:
            json.load(f, object_pairs_hook=lambda pairs: objects.append([k for k, _ in pairs]) or dict(pairs))
        codes = [o for o in objects if "verify-env-invalid" in o]
        self.assertEqual(len(codes), 1)
        self.assertEqual(len(codes[0]), len(set(codes[0])))
        self.assertEqual(len(codes[0]), len(real()["codes"]))


class Rendering(unittest.TestCase):
    def render(self, pairs, cat=None, **kw):
        return R.render(cat or demo(), "demo-code", pairs, **kw)

    def test_a_refusal_prints_the_contract_line_and_the_human_lines(self):
        text, rc = self.render([("verb", "release push"), ("moved", "head"), ("ref", "release/1.4.0"), ("n", "2")], project="acme", role="lead")
        self.assertEqual(rc, 1)
        lines = text.split("\n")
        self.assertTrue(lines[0].startswith("qargi-refusal/1 {"))
        obj = json.loads(lines[0][len("qargi-refusal/1 "):])
        self.assertEqual(list(obj), ["code", "exit", "verb", "project", "role", "epoch", "state", "tx", "detail"])
        self.assertEqual((obj["code"], obj["exit"], obj["verb"], obj["project"], obj["role"]), ("demo-code", 1, "release push", "acme", "lead"))
        self.assertEqual((obj["epoch"], obj["state"], obj["tx"]), (None, None, None))
        self.assertEqual(lines[1], "qargi: refused [demo-code] release push moved head at release/1.4.0 (?, 2)")
        self.assertEqual(lines[2:5], ["  why: a reason", "  next: lead: fix release/1.4.0", ""])
        self.assertTrue(text.endswith("\n"))

    def test_a_value_a_lead_chose_is_a_digest_in_detail_and_whole_in_the_human_lines(self):
        text, _ = self.render([("ref", "feature/secret-name"), ("refs", "a,b,c,d,e"), ("moved", "head,base"), ("n", "5")])
        obj = json.loads(text.split("\n")[0].split(" ", 1)[1])
        self.assertNotIn("secret-name", obj["detail"])
        self.assertNotIn("a,b", obj["detail"])
        pairs = dict(p.split("=", 1) for p in obj["detail"].split(" "))
        self.assertEqual(list(pairs), ["moved", "ref", "refs", "n"], "the typed fields in the order the catalogue declares them")
        self.assertRegex(pairs["ref"], r"^sha256:[0-9a-f]{12}$")
        self.assertRegex(pairs["refs"], r"^sha256:[0-9a-f]{12}$")
        self.assertEqual((pairs["moved"], pairs["n"]), ("head,base", "5"))
        self.assertIn("feature/secret-name", text.split("\n")[1])
        self.assertIn("(a, b, c +2,", text.split("\n")[1])
        self.assertEqual(pairs["ref"], R.digest("feature/secret-name"))

    def test_a_list_in_detail_has_no_spaces_so_a_pair_ends_at_the_next_space(self):
        text, _ = self.render([("moved", "a,b,c,d,e"), ("n", "1")])
        obj = json.loads(text.split("\n")[0].split(" ", 1)[1])
        self.assertEqual(obj["detail"], "moved=a,b,c,+2 n=1")

    def test_a_list_prints_three_items_and_a_count(self):
        self.assertEqual(R.list_text(["a", "b", "c"]), "a, b, c")
        self.assertEqual(R.list_text(["a", "b", "c", "d"]), "a, b, c +1")
        text, _ = self.render([("moved", "a,b,c,d,e,f")])
        self.assertIn("moved a, b, c +3 at", text.split("\n")[1])

    def test_the_host_reads_its_own_next(self):
        text, _ = self.render([("ref", "x"), ("context", "host")])
        self.assertIn("  next: host: fix x\n", text)
        text, _ = self.render([("ref", "x")])
        self.assertIn("  next: lead: fix x\n", text)

    def test_an_absent_verb_reads_this_verb_and_an_absent_field_a_question_mark(self):
        text, _ = self.render([])
        self.assertIn("this verb moved ? at ?", text.split("\n")[1])
        self.assertIsNone(json.loads(text.split("\n")[0].split(" ", 1)[1])["verb"])
        text, _ = self.render([], verb="feature finish")
        self.assertEqual(json.loads(text.split("\n")[0].split(" ", 1)[1])["verb"], "feature finish")
        text, _ = self.render([("verb", "branch prune")], verb="feature finish")
        self.assertEqual(json.loads(text.split("\n")[0].split(" ", 1)[1])["verb"], "branch prune", "the field wins over the default")

    def test_the_project_and_the_role_are_null_unless_they_are_names(self):
        text, _ = self.render([], project="Not A Name!", role="x" * 99)
        obj = json.loads(text.split("\n")[0].split(" ", 1)[1])
        self.assertEqual((obj["project"], obj["role"]), (None, None))

    def test_the_contract_line_stays_under_four_kib(self):
        cat = demo(fields={"refs": "ref-list", "moved": "label-list"}, message="m", next={"lead": "a", "host": "a"})
        many = ",".join("l%d" % i for i in range(2000))
        text, _ = R.render(cat, "demo-code", [("moved", many)])
        self.assertLess(len(text.split("\n")[0].encode()), R.LINE_MAX)

    def test_a_notice_prints_no_contract_line_and_no_refusal_and_exits_0(self):
        text, rc = self.render([("ref", "x")], notice=True)
        self.assertEqual(rc, 0)
        self.assertEqual(text, "qargi: note [demo-code] this verb moved ? at x (?, ?)\n  next: lead: fix x\n")
        self.assertNotIn("qargi-refusal", text)
        self.assertNotIn("refused", text)
        self.assertNotIn("why:", text)

    def test_a_caller_that_is_wrong_is_a_defect(self):
        bad = [("an unknown field", [("nope", "x")]), ("a field twice", [("n", "1"), ("n", "2")]), ("a count that is not one", [("n", "x")]),
               ("a label with a capital", [("moved", "Head")]), ("an empty label", [("moved", "a,,b")]), ("an enum value", [("context", "owner")]),
               ("a ref with a line break", [("ref", "a\nb")]), ("a verb that is not one", [("verb", "Release Push")]), ("an empty ref", [("ref", "")])]
        for name, pairs in bad:
            with self.subTest(name), self.assertRaises(R.Defect):
                self.render(pairs)
        with self.assertRaises(R.Defect):
            R.render(demo(), "unknown-code", [])
        with self.assertRaises(R.Defect):
            self.render([], verb="Not A Verb")
        for status in ("planned", "withdrawn"):
            with self.subTest(status), self.assertRaises(R.Defect):
                self.render([], cat=demo(status=status))

    def test_the_command_line_exits_with_the_code_and_70_on_a_defect(self):
        def run(*args):
            return subprocess.run(PY + [os.path.join(LIB, "refusal.py")] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        r = run("refuse", "verify-env-signals")
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertTrue(r.stderr.startswith("qargi-refusal/1 {"))
        n = run("notice", "verify-env-signals")
        self.assertEqual((n.returncode, n.stdout), (0, ""))
        self.assertTrue(n.stderr.startswith("qargi: note [verify-env-signals] "))
        for args in (("refuse", "nope-code"), ("refuse", "verify-env-signals", "x=1"), ("refuse", "plan-stale"), ("refuse",), ("refuse", "verify-env-signals", "bare")):
            with self.subTest(args=args):
                d = run(*args)
                self.assertEqual((d.returncode, d.stdout), (70, ""), d.stderr)
                self.assertTrue(d.stderr.startswith("qargi: defect: "))
        self.assertEqual(run("nonsense").returncode, 2)


class WhatTheSourceRaises(Tree):
    def test_a_raise_is_found_at_the_start_of_a_command_and_a_comment_is_not_one(self):
        self.put("lib/a.sh", "x() {\n  # refuse demo-code verb=no\n  [ a ] || refuse demo-code verb=\"$v\" n=2; true\n  if y; then notice demo-code ref=\"$r\"; fi\n"
                             "  refuse plain words here\n  echo \"refuse the-thing\"\n}\n")
        self.put("lib/b.py", "from x import refusal\nrefusal.refuse('demo-code', {})\n# refusal.refuse('other-code')\n")
        self.assertEqual([(p, n, c, k) for p, n, c, k in R.raised(self.root)],
                         [("lib/a.sh", 3, "demo-code", ["verb", "n"]), ("lib/a.sh", 4, "demo-code", ["ref"]), ("lib/b.py", 2, "demo-code", [])])

    def test_an_unknown_code_a_code_that_is_not_live_and_an_undeclared_field_are_problems(self):
        cat = {"schema": 1, "codes": {"demo-code": entry(), "later-code": entry(status="planned")}}
        self.put("lib/a.sh", "refuse demo-code verb=a\nrefuse ghost-code\nrefuse later-code\nrefuse demo-code bogus=1\n")
        problems = R.check_raises(cat, self.root)
        self.assertTrue(any("ghost-code" in p and "not in the catalogue" in p for p in problems), problems)
        self.assertTrue(any("later-code" in p and "planned" in p for p in problems), problems)
        self.assertTrue(any("bogus" in p for p in problems), problems)
        self.assertEqual(len(problems), 3, problems)

    def test_a_live_code_nothing_raises_is_a_problem_unless_it_lists_its_print_sites(self):
        cat = {"schema": 1, "codes": {"demo-code": entry(), "printed-code": entry(sites=[{"verbs": ["x y"], "text": "t"}]), "later-code": entry(status="planned")}}
        self.put("lib/a.sh", "true\n")
        problems = R.check_raises(cat, self.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("demo-code is live and nothing raises it", problems[0])
        self.put("lib/a.sh", "refuse demo-code\n")
        self.assertEqual(R.check_raises(cat, self.root), [])


SEAT = """**R52** (order) text. The codes in order:
`gate-one`, `gate-two`, one reserved place (R93), `gate-three`. Refusal: as each says.

**R70** (door) text.

| Code | Raised when |
| --- | --- |
| `door-one` | when |
| `door-two` | when |

Refusal: as the table says.

**R71** (next).
"""


class TheSeatCodes(Tree):
    def seat_cat(self, gate=("gate-one", "gate-two", "gate-three"), door=("door-one", "door-two")):
        codes = {c: entry(**{"class": "seat-gate", "exit": 77, "status": "planned"}) for c in gate}
        codes.update({c: entry(**{"class": "seat-door", "status": "planned"}) for c in door})
        return {"schema": 1, "codes": codes}

    def test_the_lists_are_read_from_the_page_without_the_reserved_place(self):
        self.assertEqual(R.seat_lists(SEAT), (["gate-one", "gate-two", "gate-three"], ["door-one", "door-two"]))

    def test_the_seat_codes_must_equal_the_pages_lists_with_the_gate_in_the_order_of_r52(self):
        self.put(R.SEAT_PAGE, SEAT)
        self.assertEqual(R.check_seat_codes(self.seat_cat(), self.root), ([], []))
        problems, _ = R.check_seat_codes(self.seat_cat(gate=("gate-two", "gate-one", "gate-three")), self.root)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("R52", problems[0])
        problems, _ = R.check_seat_codes(self.seat_cat(door=("door-one",)), self.root)
        self.assertTrue(problems and "R70" in problems[0], problems)
        problems, _ = R.check_seat_codes(self.seat_cat(door=("door-one", "door-two", "door-three")), self.root)
        self.assertTrue(problems and "R70" in problems[0], problems)

    def test_with_no_contract_page_the_check_is_skipped_and_says_so_without_failing(self):
        problems, notes = R.check_seat_codes(self.seat_cat(), self.root)
        self.assertEqual(problems, [])
        self.assertEqual(notes, ["seat codes: not checked, docs/reference/lead-seat.md is absent at this base"])

    def test_the_command_line_with_no_contract_page_exits_0_and_prints_the_line(self):
        shutil.copytree(LIB, os.path.join(self.root, "lib"), dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "site"))
        for rel in (R.PAGE, R.RATCHET):
            os.makedirs(os.path.dirname(os.path.join(self.root, rel)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, rel), os.path.join(self.root, rel))
        r = subprocess.run(PY + [os.path.join(LIB, "refusal.py"), "check", "--root", self.root], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("seat codes: not checked, docs/reference/lead-seat.md is absent at this base\n", r.stdout)
        self.assertRegex(r.stdout, r"refusals: \d+ codes, 0 problems\n$")
        # and with the page present the same tree is checked, not skipped
        os.makedirs(os.path.join(self.root, "docs", "reference"), exist_ok=True)
        shutil.copy(os.path.join(ROOT, R.SEAT_PAGE), os.path.join(self.root, R.SEAT_PAGE))
        r = subprocess.run(PY + [os.path.join(LIB, "refusal.py"), "check", "--root", self.root], stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("not checked", r.stdout)

    def test_the_real_catalogue_matches_the_real_contract_page(self):
        self.assertEqual(R.check_seat_codes(real(), ROOT), ([], []))
        with open(os.path.join(ROOT, R.SEAT_PAGE), encoding="utf-8") as f:
            r52, r70 = R.seat_lists(f.read())
        self.assertEqual((len(r52), len(r70)), (11, 20))


class ThePage(Tree):
    def test_the_page_is_the_catalogue_rendered(self):
        with open(os.path.join(ROOT, R.PAGE), encoding="utf-8") as f:
            self.assertEqual(f.read(), R.page_text(real()))

    def test_the_page_names_every_code_once_as_a_heading_and_does_not_name_the_lead_chosen_values(self):
        text = R.page_text(real())
        for code in real()["codes"]:
            self.assertEqual(len(re.findall(r"^### %s$" % re.escape(code), text, re.M)), 1, code)

    def test_a_stale_or_missing_page_is_a_problem(self):
        self.cat(real())
        self.assertTrue(any("missing" in p for p in R.check_page(real(), self.root)))
        self.put(R.PAGE, R.page_text(real()))
        self.assertEqual(R.check_page(real(), self.root), [])
        self.put(R.PAGE, R.page_text(real()) + "\nhand edit\n")
        self.assertTrue(any("not the page" in p for p in R.check_page(real(), self.root)))


class TheRatchet(Tree):
    def test_the_real_ratchet_holds(self):
        self.assertEqual(R.check_ratchet(ROOT), [])

    def test_it_counts_the_die_calls_that_are_code_and_not_comments_or_the_definition(self):
        self.put("lib/a.sh", "die() { echo x; exit 1; }\n# die \"in a comment\"\n[ a ] || die \"one\"\ncase $x in *) die \"two\";; esac; die $three\nrefuse x\n")
        self.put("lib/none.sh", "true\n")
        self.assertEqual(R.die_sites(self.root), {"lib/a.sh": 3})

    def test_a_new_die_call_fails_and_a_converted_one_asks_for_the_number_to_be_lowered(self):
        self.put("lib/a.sh", "die \"one\"\ndie \"two\"\n")
        self.put(R.RATCHET, "2 lib/a.sh\n")
        self.assertEqual(R.check_ratchet(self.root), [])
        self.put("lib/a.sh", "die \"one\"\ndie \"two\"\ndie \"three\"\n")
        self.assertTrue(any("allows 2" in p for p in R.check_ratchet(self.root)))
        self.put("lib/a.sh", "die \"one\"\nfail \"two\"\n")
        self.assertTrue(any("lower it" in p for p in R.check_ratchet(self.root)))
        self.put("lib/b.sh", "die \"new file\"\n")
        self.put("lib/a.sh", "die \"one\"\ndie \"two\"\n")
        self.assertTrue(any("lib/b.sh" in p for p in R.check_ratchet(self.root)))

    def test_the_file_is_what_sites_prints(self):
        r = subprocess.run(PY + [os.path.join(LIB, "refusal.py"), "sites"], stdout=subprocess.PIPE, universal_newlines=True)
        with open(os.path.join(ROOT, R.RATCHET), encoding="utf-8") as f:
            self.assertEqual(f.read(), r.stdout)


if __name__ == "__main__":
    unittest.main()
