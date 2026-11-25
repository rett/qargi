#!/usr/bin/env python3
"""The catalogue of refusals (lib/refusals.json) and lib/refusal.py: the schema and its lint, the renderer (the contract line, the human lines, a
digest for what a lead chose, a list as three and +N, `notice`), the codes a source file raises against the catalogue, the seat codes against the
contract page (skipped, with a line saying so, when the page is absent), the generated page and the ratchet of unclassified `die` calls.
Offline; a scratch home; no project. Run: python3 tests/test_refusals.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, re, shutil, subprocess, sys, tempfile, time, unittest

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
        self.assertTrue(any(e["class"] == "verify-environment" for e in codes.values()))
        for c in ("plan-missing", "plan-stale", "approval-missing", "approval-inside-run", "cut-not-covering", "cut-lead-changed", "cut-branch-moved",
                  "cut-fix-outside", "release-notes-empty", "release-fragments-unfolded", "feature-runs-open", "ro-write-outside", "ro-second-tree",
                  "ro-env-restricted", "member-push", "member-lead-verb", "member-run-record"):
            self.assertIn(c, codes)
        self.assertTrue(any(e["class"] in R.SEAT_CLASSES for e in codes.values()))

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
               ("a ref with a line break", [("ref", "a\nb")]), ("a verb that is not one", [("verb", "Release Push")]), ("an empty ref", [("ref", "")]),
               ("a verb with a trailing line break", [("verb", "release push\n")]), ("a label with a trailing line break", [("moved", "head\n")]),
               ("a count with a trailing line break", [("n", "2\n")])]
        for name, pairs in bad:
            with self.subTest(name), self.assertRaises(R.Defect):
                self.render(pairs)
        with self.assertRaises(R.Defect):
            R.render(demo(), "unknown-code", [])
        text, _ = self.render([], verb="Not A Verb")
        self.assertIsNone(json.loads(text.split("\n")[0].split(" ", 1)[1])["verb"], "a default that is not a verb is no verb, never a defect")
        text, _ = self.render([], verb="release push\n", project="acme\n", role="lead\n")
        obj = json.loads(text.split("\n")[0].split(" ", 1)[1])
        self.assertEqual((obj["verb"], obj["project"], obj["role"]), (None, None, None), "a trailing line break makes none of them a verb or a name")
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
        for args in (("refuse", "nope-code"), ("refuse", "verify-env-signals", "x=1"), ("refuse", "approval-missing"), ("refuse",), ("refuse", "verify-env-signals", "bare")):
            with self.subTest(args=args):
                d = run(*args)
                self.assertEqual((d.returncode, d.stdout), (70, ""), d.stderr)
                self.assertTrue(d.stderr.startswith("qargi: defect: "))
        self.assertEqual(run("nonsense").returncode, 2)


def sh(script, **env):
    """Runs a bash script that has sourced lib/lib.sh, in the scratch home of the test; (status, standard output, standard error)."""
    e = dict(os.environ, **env)
    r = subprocess.run(["bash", "-c", 'set -u; . "$1/lib.sh"; shift; ' + script, "bash", LIB], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, env=e)
    return r.returncode, r.stdout, r.stderr


def contract(err):
    """The JSON object of the contract line in a standard error text."""
    lines = [l for l in err.split("\n") if l.startswith("qargi-refusal/1 ")]
    assert len(lines) == 1, err
    return json.loads(lines[0][len("qargi-refusal/1 "):])


class TheShellHelpers(unittest.TestCase):
    def test_refuse_prints_the_refusal_and_exits_with_the_code_status(self):
        rc, out, err = sh('verb=push; refuse plan-stale moved=head,base token=0123456789ab; echo not-reached', PROJECT="acme", QARGI_ROLE="lead")
        self.assertEqual((rc, out), (1, ""))
        obj = contract(err)
        self.assertEqual((obj["code"], obj["exit"], obj["verb"], obj["project"], obj["role"]), ("plan-stale", 1, "push", "acme", "lead"))
        self.assertEqual(obj["detail"], "moved=head,base token=0123456789ab")
        lines = err.strip().split("\n")
        self.assertEqual(len(lines), 4)
        self.assertTrue(lines[1].startswith("qargi: refused [plan-stale] "))
        self.assertTrue(lines[2].startswith("  why: "))
        self.assertIn("--plan 0123456789ab", lines[3])

    def test_refuse_names_the_verb_from_qargi_verb_before_the_scripts_own_and_a_field_wins(self):
        _, _, err = sh('verb=push; refuse plan-missing', QARGI_VERB="release push")
        self.assertEqual(contract(err)["verb"], "release push")
        _, _, err = sh('verb=push; refuse plan-missing verb="branch prune"')
        self.assertEqual(contract(err)["verb"], "branch prune")
        _, _, err = sh('verb="--help"; refuse plan-missing')
        self.assertIsNone(contract(err)["verb"], "a script word that is not a verb is no verb")

    def test_a_caller_that_is_wrong_exits_70_and_prints_no_refusal(self):
        for script in ("refuse no-such-code", "refuse plan-missing nofield=1", "refuse plan-missing token=nothex", "refuse approval-missing token=a1b2c3d4e5f6",
                       "refuse", "notice no-such-code", "notice plan-missing token=x"):
            with self.subTest(script=script):
                rc, out, err = sh(script + "; echo after")
                self.assertEqual((rc, out), (70, ""), err)
                self.assertNotIn("qargi-refusal", err)
                self.assertTrue(err.startswith("qargi: defect: "), err)

    def test_notice_returns_and_the_verb_goes_on(self):
        rc, out, err = sh('notice plan-missing verb="release push" token=0123456789ab; echo after')
        self.assertEqual((rc, out), (0, "after\n"))
        self.assertTrue(err.startswith("qargi: note [plan-missing] "), err)
        self.assertNotIn("qargi-refusal", err)
        self.assertNotIn("refused", err)
        self.assertEqual(len(err.strip().split("\n")), 2)

    def test_fail_and_die_print_one_line_and_exit_1(self):
        for word in ("fail", "die"):
            with self.subTest(word):
                self.assertEqual(sh('%s "it broke:" x; echo after' % word), (1, "", "qargi: it broke: x\n"))

    def test_need_plan_passes_the_token_and_refuses_a_missing_or_a_stale_one_with_its_own_code(self):
        rc, out, err = sh('PLAN_ARG=0123456789ab; need_plan 0123456789ab; echo ok')
        self.assertEqual((rc, out, err), (0, "ok\n", ""))
        rc, out, err = sh('PLAN_ARG=; verb=merge; need_plan 0123456789ab; echo not-reached')
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(contract(err)["code"], "plan-missing")
        self.assertIn("--plan 0123456789ab", err)
        rc, out, err = sh('PLAN_ARG=ba9876543210; verb=merge; need_plan 0123456789ab; echo not-reached')
        self.assertEqual((rc, out), (1, ""))
        obj = contract(err)
        self.assertEqual((obj["code"], obj["verb"]), ("plan-stale", "merge"))
        self.assertIn("--plan 0123456789ab", err)
        rc, out, err = sh('unset PLAN_ARG; need_plan 0123456789ab')
        self.assertEqual((rc, contract(err)["code"]), (1, "plan-missing"), "an unset --plan is a missing one")

    def test_the_two_refusals_keep_the_words_the_scripts_tests_look_for(self):
        for script in ("PLAN_ARG=; need_plan 0123456789ab", "PLAN_ARG=ba9876543210; need_plan 0123456789ab"):
            _, _, err = sh(script)
            self.assertIn("the plan changed or --plan is missing", err)

    def test_a_token_that_is_not_twelve_hex_digits_is_left_out_and_is_still_a_refusal(self):
        for tok in ("short", "0123456789AB", "0123456789abc", "0123456789ab\n"):
            with self.subTest(token=tok):
                rc, out, err = sh('PLAN_ARG=; need_plan "$TOK"; echo after', TOK=tok)
                self.assertEqual((rc, out), (1, ""), err)
                obj = contract(err)
                self.assertEqual(obj["code"], "plan-missing")
                self.assertNotIn("token=", obj["detail"])
                self.assertIn("--plan ?", err)

    def test_the_nested_variable_does_not_stand_in_for_the_token_except_for_need_plan_nested(self):
        rc, out, err = sh('PLAN_ARG=; need_plan 0123456789ab; echo after', QARGI_NESTED="1")
        self.assertEqual((rc, contract(err)["code"]), (1, "plan-missing"))
        rc, out, err = sh('PLAN_ARG=; need_plan_nested 0123456789ab; echo after', QARGI_NESTED="1")
        self.assertEqual((rc, out, err), (0, "after\n", ""))
        rc, out, err = sh('PLAN_ARG=; need_plan_nested 0123456789ab; echo after')
        self.assertEqual((rc, contract(err)["code"]), (1, "plan-missing"))


def plans_dir():
    return os.path.join(os.environ["QARGI_STATE"], "plans")


def stored(token):
    with open(os.path.join(plans_dir(), token + ".json"), encoding="utf-8") as f:
        return json.load(f)


class ThePlanBasis(unittest.TestCase):
    PLAN = "head abc\nbase def\nfiles a b\n"

    def token(self, text, labels=None, **env):
        """plan_token (with --basis LABELS when given) on the text: (status, token, standard error)."""
        script = 'printf "%s" "$PLAN" | plan_token' + (' --basis "$LABELS"' if labels is not None else "")
        rc, out, err = sh(script, PLAN=text, LABELS=labels or "", **env)
        return rc, out.strip(), err

    def test_the_token_is_the_same_with_and_without_the_basis(self):
        plain = hashlib.sha256(b"head abc\nbase def\nfiles a b\n").hexdigest()[:12]
        self.assertEqual(self.token(self.PLAN), (0, plain, ""))
        self.assertEqual(self.token(self.PLAN, "head base files"), (0, plain, ""))
        self.assertEqual(self.token("", "head"), (0, hashlib.sha256(b"").hexdigest()[:12], ""))

    def test_the_labelled_lines_are_kept_in_a_file_of_mode_600_in_a_directory_of_mode_700(self):
        _, tok, _ = self.token(self.PLAN, "head base files")
        rec = stored(tok)
        self.assertEqual(rec["token"], tok)
        self.assertEqual(rec["basis"], [{"label": "head", "lines": ["head abc"]}, {"label": "base", "lines": ["base def"]}, {"label": "files", "lines": ["files a b"]}])
        self.assertEqual(os.stat(os.path.join(plans_dir(), tok + ".json")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(plans_dir()).st_mode & 0o777, 0o700)

    def test_the_lines_after_the_last_label_belong_to_it_and_a_surplus_label_has_none(self):
        self.assertEqual(R.basis_lines("a\nb\nc\nd\n", ["x", "y"]), [["x", ["a"]], ["y", ["b", "c", "d"]]])
        self.assertEqual(R.basis_lines("a\n", ["x", "y"]), [["x", ["a"]], ["y", []]])
        self.assertEqual(R.basis_lines("", ["x"]), [["x", []]])

    def test_a_stale_token_names_the_labels_that_moved(self):
        _, old, _ = self.token("head abc\nbase def\nfiles a b\n", "head base files")
        _, new, _ = self.token("head abc\nbase f00\nfiles a b c\n", "head base files")
        self.assertNotEqual(old, new)
        rc, out, err = sh('PLAN_ARG="$OLD"; verb=push; need_plan "$NEW"', OLD=old, NEW=new)
        self.assertEqual((rc, out), (1, ""))
        obj = contract(err)
        self.assertEqual((obj["code"], obj["verb"]), ("plan-stale", "push"))
        self.assertEqual(obj["detail"], "moved=base,files token=" + new)
        self.assertIn("(moved: base, files)", err)

    def test_a_plan_made_without_a_basis_is_unrecorded(self):
        _, old, _ = self.token("one\n")
        _, new, _ = self.token("two\n", "line")
        rc, out, err = sh('PLAN_ARG="$OLD"; need_plan "$NEW"', OLD=old, NEW=new)
        self.assertEqual(rc, 1)
        self.assertEqual(contract(err)["detail"], "moved=unrecorded token=" + new)
        rc, out, err = sh('PLAN_ARG=0123456789ab; need_plan "$NEW"', NEW=new)
        self.assertEqual(contract(err)["detail"], "moved=unrecorded token=" + new, "a token that was never planned is unrecorded too")
        rc, out, err = sh('PLAN_ARG="../../x"; need_plan "$NEW"', NEW=new)
        self.assertEqual((rc, contract(err)["detail"]), (1, "moved=unrecorded token=" + new), "a --plan that is no token reads no file")

    def test_nothing_is_kept_in_a_dry_run(self):
        rc, tok, err = self.token("a dry plan\n", "line", QARGI_DRY="1")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(tok, hashlib.sha256(b"a dry plan\n").hexdigest()[:12])
        self.assertFalse(os.path.exists(os.path.join(plans_dir(), tok + ".json")))

    def test_only_one_is_a_dry_run_so_unset_empty_and_zero_keep_the_plan(self):
        for value in ("", "0"):
            with self.subTest(QARGI_DRY=value):
                rc, tok, err = self.token("a plan for %r\n" % value, "line", QARGI_DRY=value)
                self.assertEqual((rc, err), (0, ""))
                self.assertEqual(stored(tok)["token"], tok)

    def test_a_basis_that_cannot_be_kept_is_a_note_and_the_token_is_still_printed(self):
        d = tempfile.mkdtemp(prefix="nobasis.")
        self.addCleanup(shutil.rmtree, d, True)
        state = os.path.join(d, "state")
        os.makedirs(state)
        with open(os.path.join(state, "plans"), "w") as f:      # a regular file where the directory of the plans belongs
            f.write("in the way\n")
        rc, tok, err = self.token(self.PLAN, "head base files", QARGI_STATE=state, QARGI_CONF=os.path.join(d, "conf"))
        self.assertEqual(rc, 0, err)
        self.assertEqual(tok, hashlib.sha256(self.PLAN.encode()).hexdigest()[:12])
        self.assertIn("qargi: note: the basis of the plan could not be kept", err)
        self.assertNotIn("defect", err)

    def test_a_damaged_or_hand_edited_record_is_unrecorded_and_never_a_defect(self):
        _, old, _ = self.token("one\n", "line")
        _, new, _ = self.token("two\n", "line")
        records = ('{"token":"%s","basis":[{"label":"X Y","lines":["a"]}]}', '{"token":"%s","basis":[{"label":"ok","lines":"a"}]}',
                   '{"token":"%s","basis":[{"label":"ok","lines":[1]}]}', '{"token":"%s","basis":[{"label":7,"lines":[]}]}', '{"token":"%s","basis":[{"label":"ok\\n","lines":[]}]}',
                   '{"token":"%s","basis":"line"}', '[1]', 'not json')
        for text in records:
            with self.subTest(record=text):
                with open(os.path.join(plans_dir(), old + ".json"), "w", encoding="utf-8") as f:
                    f.write((text % old if "%s" in text else text) + "\n")
                self.assertIsNone(R.basis_read(old))
                rc, out, err = sh('PLAN_ARG="$OLD"; need_plan "$NEW"', OLD=old, NEW=new)
                self.assertEqual(rc, 1, err)
                self.assertEqual(contract(err)["detail"], "moved=unrecorded token=" + new)

    def test_a_plan_is_kept_seven_days_and_no_longer(self):
        os.makedirs(plans_dir(), mode=0o700, exist_ok=True)
        old, fresh, other = (os.path.join(plans_dir(), n) for n in ("aaaaaaaaaaaa.json", "bbbbbbbbbbbb.json", "keep.txt"))
        for p in (old, fresh, other):
            with open(p, "w") as f:
                f.write("{}")
        long_ago = time.time() - 8 * 86400
        os.utime(old, (long_ago, long_ago))
        os.utime(other, (long_ago, long_ago))
        self.token("prune\n", "line")
        self.assertFalse(os.path.exists(old))
        self.assertTrue(os.path.exists(fresh))
        self.assertTrue(os.path.exists(other), "only plan files are pruned")

    def test_labels_that_are_not_words_are_a_defect_and_a_missing_label_list_a_usage_error(self):
        rc, out, err = self.token("x\n", "Bad,Label")
        self.assertEqual(rc, 70)
        rc, out, err = sh('echo x | plan_token --basis')
        self.assertEqual(rc, 2)
        self.assertIn("needs the labels", err)
        rc, _, err = sh('echo x | plan_token --basis ""')
        self.assertEqual(rc, 70, err)

    def test_the_stored_plans_are_read_by_token_only(self):
        self.assertIsNone(R.basis_read("../x"))
        self.assertIsNone(R.basis_read("0123456789ab\n"))
        self.assertIsNone(R.basis_read("0123456789ab"))
        self.assertIsNone(R.basis_moved("0123456789ab", "ba9876543210"))
        self.assertEqual(R.basis_moved(self.token("a\n", "x y")[1], self.token("a\n", "x y")[1]), [])


class TheDryStops(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="drystop.")
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.state = os.path.join(self.dir, "state")
        os.makedirs(self.state)
        self.file = os.path.join(self.dir, "data.json")
        with open(self.file, "w") as f:
            f.write('{"n":1}\n')
        self.run_sh("true")             # the first load makes the state and the configuration: what a dry run must not add is what comes after

    def run_sh(self, script, **env):
        return sh(script, QARGI_STATE=self.state, QARGI_CONF=os.path.join(self.dir, "conf"), DATA=self.file, **env)

    def listing(self):
        return sorted(os.listdir(self.state)) + sorted(os.listdir(os.path.join(self.dir, "conf"))) + sorted(os.listdir(self.dir))

    def test_audit_log_writes_one_line_outside_a_dry_run(self):
        rc, out, err = self.run_sh('audit_log demo "some detail"')
        self.assertEqual((rc, out, err), (0, "", ""))
        with open(os.path.join(self.state, "audit.log"), encoding="utf-8") as f:
            lines = f.read().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual((json.loads(lines[0])["verb"], json.loads(lines[0])["detail"]), ("demo", "some detail"))
        for value in ("", "0"):
            with self.subTest(QARGI_DRY=value):
                rc, _, err = self.run_sh('audit_log demo again', QARGI_DRY=value)
                self.assertEqual(rc, 0, "only QARGI_DRY=1 is a dry run: " + err)

    def test_audit_log_in_a_dry_run_is_a_defect_that_writes_nothing_and_takes_no_lock(self):
        before = self.listing()
        rc, out, err = self.run_sh('audit_log demo x; echo after', QARGI_DRY="1")
        self.assertEqual((rc, out), (70, ""))
        self.assertEqual(err, "qargi: defect: audit_log was reached in a dry run (QARGI_DRY is set): a dry run changes nothing, so this path must not write\n")
        self.assertEqual(self.listing(), before)
        self.assertFalse(os.path.exists(os.path.join(self.state, "audit.log")))
        self.assertFalse(os.path.exists(os.path.join(self.state, "audit.log.lock")))

    def test_need_asked_audits_first_so_it_stops_in_a_dry_run_too(self):
        rc, out, err = self.run_sh('verb=start; need_asked; echo after', QARGI_DRY="1")
        self.assertEqual((rc, out), (70, ""))
        self.assertIn("audit_log was reached", err)

    def test_json_update_updates_outside_a_dry_run(self):
        rc, out, err = self.run_sh('json_update "$DATA" ".n = 2"')
        self.assertEqual((rc, out, err), (0, "", ""))
        with open(self.file) as f:
            self.assertEqual(json.load(f), {"n": 2})
        self.assertTrue(os.path.exists(self.file + ".lock"))
        for value in ("", "0"):
            with self.subTest(QARGI_DRY=value):
                rc, out, err = self.run_sh('json_update "$DATA" ".n = 3"', QARGI_DRY=value)
                self.assertEqual((rc, out, err), (0, "", ""), "only QARGI_DRY=1 is a dry run")
                with open(self.file) as f:
                    self.assertEqual(json.load(f), {"n": 3})

    def test_json_update_in_a_dry_run_is_a_defect_that_changes_nothing_and_makes_no_lock_file(self):
        before = self.listing()
        rc, out, err = self.run_sh('json_update "$DATA" ".n = 2"; echo after', QARGI_DRY="1")
        self.assertEqual((rc, out), (70, ""))
        self.assertIn("qargi: defect: json_update was reached in a dry run", err)
        with open(self.file) as f:
            self.assertEqual(f.read(), '{"n":1}\n')
        self.assertEqual(self.listing(), before)
        self.assertFalse(os.path.exists(self.file + ".lock"))
        self.assertFalse(os.path.exists(self.file + ".tmp"))

    def test_dry_stop_is_for_any_writing_helper_and_names_it(self):
        self.assertEqual(self.run_sh('dry_stop journal_line; echo after')[:2], (0, "after\n"))
        rc, out, err = self.run_sh('dry_stop journal_line; echo after', QARGI_DRY="1")
        self.assertEqual((rc, out), (70, ""))
        self.assertIn("journal_line was reached in a dry run", err)
        for value in ("", "0"):
            with self.subTest(QARGI_DRY=value):
                self.assertEqual(self.run_sh('dry_stop journal_line; echo after', QARGI_DRY=value)[:2], (0, "after\n"), "only QARGI_DRY=1 is a dry run")


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
        self.assertTrue(r52 and r70, "the page lists the gate and the door codes")


class ThePage(Tree):
    def test_the_page_is_the_catalogue_rendered(self):
        with open(os.path.join(ROOT, R.PAGE), encoding="utf-8") as f:
            self.assertEqual(f.read(), R.page_text(real()))

    def test_the_page_names_every_code_once_as_a_heading_and_does_not_name_the_lead_chosen_values(self):
        text = R.page_text(real())
        for code in real()["codes"]:
            self.assertEqual(len(re.findall(r"^### %s$" % re.escape(code), text, re.M)), 1, code)

    def test_the_print_sites_of_a_code_are_counted_and_pointed_at_by_its_class(self):
        """One site is `1 site`; a verify.environment code points at that page and a guard code at the guard's own text, never at the other's."""
        text = R.page_text(real())
        self.assertIsNone(re.search(r"(?<!\d)1 sites", text))
        for code, e in real()["codes"].items():
            if not e.get("sites"):
                continue
            n = len(e["sites"])
            body = text.split("### %s\n" % code, 1)[1].split("\n### ", 1)[0]
            line = next(l for l in body.splitlines() if l.startswith("- Printed at "))
            self.assertTrue(line.startswith("- Printed at %d site%s; " % (n, "" if n == 1 else "s")), (code, line))
            self.assertEqual("(verify-environment.md)" in line, e["class"] == "verify-environment", (code, line))
            self.assertEqual("qargi help guard" in line, e["class"] == "guard", (code, line))

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
