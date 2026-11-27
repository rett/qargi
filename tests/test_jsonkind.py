#!/usr/bin/env python3
"""lib/jsonkind.py and the registry files of lib/kinds/: the parser hooks (a float, a non-finite constant, a duplicate key), the rules of a
document (R-J1 to R-J6, one broken case for each), the rules of the registry format (each broken once), the directory check, and the command
line (`check`, `check FILE|-`, `validate KIND FILE|-` on standard input and on a file, the exit statuses). A valid and an invalid document of
each of the four first kinds. Offline; a scratch home; no repository state. Run: python3 tests/test_jsonkind.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import copy, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
KINDS = os.path.join(LIB, "kinds")
sys.path.insert(0, LIB)
import jsonkind as J  # noqa: E402

PY = [sys.executable, "-B", "-I", os.path.join(LIB, "jsonkind.py")]
FIRST_KINDS = ("qargi-refusal", "qargi-handoff", "qargi-marshal-status", "qargi-marshal-check")
DRAFT_KINDS = ("qargi-run-plan", "qargi-run-plan-check")      # registered, not pinned: no fixtures yet (tests/test_json_registry.py skips them)
MAX_NEST = J.MAX_DEPTH
RULE_NAMES = list(J.RULES)
DOC_RULES = RULE_NAMES[:RULE_NAMES.index("registry-not-object")]
FORMAT_RULES = RULE_NAMES[RULE_NAMES.index("registry-not-object"):]


def run(*args, stdin=None):
    p = subprocess.run(PY + list(args), input=stdin, capture_output=True)
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def registry(kind):
    with open(os.path.join(KINDS, kind + ".json")) as f:
        return json.load(f)


def dump(v):
    return json.dumps(v)


def rules(findings):
    return {f[0] for f in findings}


# ---- documents that are valid against the four kinds ------------------------------------------------------------------------------

LEAD = {"id": "lead-a", "user": "someone", "host": "somehost", "since": "2026-01-02T03:04:05Z"}


def feature_row(**over):
    d = {"feature": "demo", "project": "proj", "status": "active", "lead": dict(LEAD), "lease": "live", "lease_clock": "wall",
         "minutes_since_renewal": 3, "ttl_minutes": 15, "renewed_at": "2026-01-02T03:04:05Z", "rev": 4, "branch": True, "ghost": False,
         "updated_by": "lead-a", "purpose": "", "goal": "a goal", "plan": "", "note": "", "finished_at": None}
    d.update(over)
    return d


def task(**over):
    t = {"run": "r1", "slug": "s", "role": "build", "started": "2026-01-02T03:04:05Z", "verified": True, "applied": False, "cleaned": False,
         "closed": False, "directory_gone": False, "state": "verified"}
    t.update(over)
    return t


def status_doc(**over):
    row = dict(feature_row(), tasks=[task()], agent_branches=["agent/s"], worktrees=[{"path": "/w", "branch": "agent/s"}], overlap={"other": ["a.txt"]})
    d = {"schema": 1, "kind": "qargi-marshal-status", "project": "proj", "backend": "refs", "remote": "checked", "features": [row],
         "agent_unattributed": [{"branch": "agent/x", "base": ""}]}
    d.update(over)
    return d


def check_doc(**over):
    d = {"schema": 1, "kind": "qargi-marshal-check", "project": "proj", "backend": "local", "remote": "none", "feature": "demo", "answer": "free-stale",
         "lead": dict(LEAD), "warnings": ["the lead is stale"]}
    d.update(over)
    return d


def head(**over):
    h = {"path": "/repo", "branch": "develop", "detached": False, "sha": "0" * 40}
    h.update(over)
    return h


def handoff_doc(**over):
    feat = {"name": "demo", "branch_exists": True, "tip": "1" * 40, "ahead": 2, "behind": None,
            "suite": {"state": "at-tip", "text": "pass at this tip", "sha": "1" * 40, "result": "pass", "at": "2026-01-02T03:04:05Z"},
            "agent_merged": ["agent/a"], "agent_unmerged": [["agent/b", 1], ["agent/c", None]], "commits": ["abc1234 a subject"],
            "worktrees": [{"path": "/w", "branch": "feature/demo"}], "tasks": [task()], "overlap": {},
            "record": {"status": "active", "lease": "live", "minutes_since_renewal": 0, "ttl_minutes": 15, "rev": 1, "ghost": False,
                       "finished_at": None, "updated_by": "lead-a", "lead": dict(LEAD), "has_record": True,
                       "data": {"purpose": "", "goal": "g", "plan": "", "note": "", "truncated": [], "from": "lead-a"}}}
    d = {"schema": 1, "kind": "qargi-handoff", "project": "proj", "generated_at": "2026-01-02T03:04:05Z", "generated_by": "lead-a",
         "where": {"repo": "/repo", "repo_is_work_tree": True, "head": head(), "cwd": None, "develop": "0" * 40, "host": "somehost", "user": "someone",
                   "qargi_data_present": True, "answers_file": "/conf/projects/proj.json"},
         "gates": [{"tier": "feature", "name": "unit", "command": "make test"}],
         "deviations": {"accepted": [{"gap": "g", "reason": "r", "date": "2026-01-01", "status": "accepted"}], "open_gaps": None},
         "features": [feat], "worktrees_unattributed": [], "agent_unattributed": [], "backend": "local", "remote": "none", "backend_fallback": False,
         "integrity": "off",
         "packs": {"provider": "rt", "unsupported": None, "render_dir": "/r", "render_exists": True, "skills_dir": "skills", "linked": True,
                   "launch": "rt --x", "launch_why": "", "render_target": "rt", "check_why": "",
                   "link_path": "/repo/skills", "check": {"exit": 0, "first": ["ok"], "last": [], "omitted": 0}},
         "environment": {"recorded": True, "check": {"head": "abc", "at_head": False, "verdict": "ENV OK", "exit": 0, "missing": 0, "expected": 0,
                                                       "time": "2026-01-02T03:04:05Z", "doctor_command": "make doctor", "builtin_minimum": False},
                         "apply": None},
         "read_first": {"memory": [{"tier": "project", "kind": "dir", "location": "/m", "indexes": ["/m/INDEX.md"]}], "repo_docs": [],
                        "status_command": "qargi marshal status --all", "successor": [{"feature": "demo", "lead": "lead-a"}]},
         "do_not_assume": ["a sentence"], "notes": [], "truncated": False}
    d.update(over)
    return d


def refusal_doc(**over):
    d = {"schema": 1, "kind": "qargi-refusal", "code": "plan-missing", "exit": 1, "verb": None, "project": None, "role": None,
         "epoch": None, "state": None, "tx": None, "detail": ""}
    d.update(over)
    return d


VALID = {"qargi-refusal": refusal_doc, "qargi-handoff": handoff_doc, "qargi-marshal-status": status_doc, "qargi-marshal-check": check_doc}

# One invalid document for each kind, by a change a real writer could make.
INVALID = {
    "qargi-refusal": (refusal_doc(schema=2), "schema-unknown"),
    "qargi-handoff": (handoff_doc(truncated="no"), "type-wrong"),
    "qargi-marshal-status": (status_doc(remote="maybe"), "enum-unknown"),
    "qargi-marshal-check": (check_doc(answer="held"), "enum-unknown"),
}


class Tmp(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="jsonkind.")
        self.addCleanup(shutil.rmtree, self.dir, True)

    def put(self, name, text):
        p = os.path.join(self.dir, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text if isinstance(text, str) else dump(text))
        return p


class ParserHooks(unittest.TestCase):
    def test_float_is_found_where_it_stands(self):
        for text, path in (('{"a": 1.5}', "$.a"), ('{"a": [1, 2e3]}', "$.a[1]"), ('{"a": {"b": 3.0}}', "$.a.b"), ('{"a": 1E-2}', "$.a")):
            v, fs = J.checked_parse(text)
            self.assertEqual([(f.rule, f.path) for f in fs], [("integer-float", path)], text)
            self.assertIsInstance(v, dict)

    def test_the_float_hook_marks_the_value(self):
        v, _ = J.parse('{"a": 1.0, "b": 1}')
        self.assertIsInstance(v["a"], J.Flt)
        self.assertNotIsInstance(v["b"], J.Flt)

    def test_non_finite_constants_are_found(self):
        for word in ("NaN", "Infinity", "-Infinity"):
            v, fs = J.checked_parse('{"a": [%s]}' % word)
            self.assertEqual([(f.rule, f.path) for f in fs], [("non-finite", "$.a[0]")], word)
            self.assertIsInstance(v["a"][0], J.NonFinite)

    def test_duplicate_key_is_found_at_any_depth(self):
        _, fs = J.checked_parse('{"a": 1, "a": 2}')
        self.assertEqual([(f.rule, f.path) for f in fs], [("duplicate-key", "$.a")])
        _, fs = J.checked_parse('{"x": [{"b": 1, "c": 2, "b": 3}]}')
        self.assertEqual([(f.rule, f.path) for f in fs], [("duplicate-key", "$.x[0].b")])

    def test_integer_range_is_plus_or_minus_two_to_the_53_minus_1(self):
        for n, ok in ((2 ** 53 - 1, True), (-(2 ** 53 - 1), True), (2 ** 53, False), (-(2 ** 53), False)):
            _, fs = J.checked_parse('{"n": %d}' % n)
            self.assertEqual(fs == [], ok, n)
            if not ok:
                self.assertEqual(fs[0].rule, "integer-range")

    def test_a_boolean_is_not_an_integer_and_a_clean_document_has_no_finding(self):
        v, fs = J.checked_parse('{"a": true, "b": [1, -2, 0], "c": "1.5", "d": null}')
        self.assertEqual(fs, [])
        self.assertEqual(v["b"], [1, -2, 0])

    def test_text_that_is_not_one_document(self):
        for text, rule in (("", "truncated"), ("  \n", "truncated"), ('{"a": ', "truncated"), ('{"a": 1', "truncated"), ('{"a": 1} {"b": 2}', "two-documents"),
                           ('{"a": 1} x', "two-documents"), ("{'a': 1}", "invalid-json"), ('{"a" 1}', "invalid-json")):
            _, fs = J.checked_parse(text)
            self.assertEqual([f.rule for f in fs], [rule], repr(text))
        _, fs = J.checked_parse(b"\xff\xfe")
        self.assertEqual([f.rule for f in fs], ["invalid-json"])


class Documents(unittest.TestCase):
    """The rules of a document, each broken once, on the status kind (schema 1)."""
    def check(self, text, kind="qargi-marshal-status"):
        return J.validate(os.path.join(KINDS, kind + ".json"), text)

    def test_every_rule_of_a_document_has_a_broken_case(self):
        good = dump(status_doc())
        broken = {
            "invalid-json": "{'a': 1}",
            "truncated": good[:len(good) // 2],
            "two-documents": good + "\n" + good,
            "not-an-object": "[1, 2]",
            "schema-missing": dump({k: v for k, v in status_doc().items() if k != "schema"}),
            "schema-string": dump(status_doc(schema="1")),
            "schema-float": good.replace('"schema": 1,', '"schema": 1.0,', 1),
            "schema-unknown": dump(status_doc(schema=2)),
            "kind-missing": dump({k: v for k, v in status_doc().items() if k != "kind"}),
            "kind-wrong": dump(status_doc(kind="qargi-marshal-check")),
            "required-missing": dump({k: v for k, v in status_doc().items() if k != "project"}),
            "type-wrong": dump(status_doc(features={})),
            "integer-string": dump(status_doc(features=[feature_row(ttl_minutes="15")])),
            "enum-unknown": dump(status_doc(backend="cloud")),
            "null-not-allowed": dump(status_doc(project=None)),
            "pattern-mismatch": None,
            "const-wrong": None,
            "integer-float": dump(status_doc(features=[feature_row(minutes_since_renewal=3.0)])),
            "non-finite": good.replace('"rev": 4', '"rev": NaN', 1),
            "integer-range": dump(status_doc(features=[feature_row(rev=2 ** 53)])),
            "duplicate-key": good.replace('"project": "proj",', '"project": "proj", "project": "proj",', 1),
            "too-deep": '{"deep": ' + "[" * 5000 + "]" * 5000 + "}",
        }
        self.assertEqual(sorted(k for k in broken if k not in ("pattern-mismatch", "const-wrong")), sorted(set(DOC_RULES) - {"pattern-mismatch", "const-wrong"}))
        for rule, text in broken.items():
            if text is None:
                continue
            fs = self.check(text)
            self.assertIn(rule, rules(fs), "%s: %s" % (rule, [f.line() for f in fs]))
            self.assertTrue(fs, rule)

    def test_pattern_and_const_of_a_nested_field(self):
        reg = copy.deepcopy(registry("qargi-refusal"))
        reg["document"]["properties"]["detail"] = {"type": "string", "pattern": "^a+$"}
        reg["document"]["properties"]["code"] = {"type": "string", "const": "plan-missing"}
        self.assertEqual(J.check_registry(reg), [])
        self.assertEqual(J.validate_doc(reg, dump(refusal_doc(detail="aaa"))), [])
        self.assertEqual([f.rule for f in J.validate_doc(reg, dump(refusal_doc(detail="b")))], ["pattern-mismatch"])
        self.assertEqual([f.rule for f in J.validate_doc(reg, dump(refusal_doc(detail="a", code="other-code")))], ["const-wrong"])

    def test_rules_of_a_float_in_schema_and_a_float_among_unknown_fields(self):
        self.assertEqual([f[0] for f in self.check('{"schema": 1.0, "kind": "qargi-marshal-status"}')][:1], ["schema-float"])
        fs = self.check(dump(status_doc(extra_field=1.5)))
        self.assertEqual(sorted(rules(fs)), ["integer-float"])
        self.assertEqual([f.path for f in fs], ["$.extra_field"])

    def test_an_unknown_field_is_accepted(self):
        doc = status_doc(brand_new={"a": [1, 2]})
        doc["features"][0]["also_new"] = "x"
        self.assertEqual(self.check(dump(doc)), [])

    def test_findings_are_pairs_with_a_sentence_and_a_path(self):
        fs = self.check(dump(status_doc(features=[feature_row(status="gone")])))
        self.assertEqual(len(fs), 1)
        rule, path = fs[0]
        self.assertEqual((rule, path), ("enum-unknown", "$.features[0].status"))
        self.assertIn("gone", fs[0].message)

    def test_a_registry_that_is_not_well_formed_is_an_error_not_a_finding(self):
        d = tempfile.mkdtemp(prefix="jsonkind.")
        self.addCleanup(shutil.rmtree, d, True)
        p = os.path.join(d, "x.json")
        with open(p, "w") as f:
            f.write('{"registry": 1}')
        with self.assertRaises(J.RegistryError):
            J.validate(p, "{}")

    def test_a_valid_and_an_invalid_document_of_each_kind(self):
        for kind in FIRST_KINDS:
            self.assertEqual(self.check(dump(VALID[kind]()), kind), [], kind)
            doc, rule = INVALID[kind]
            fs = self.check(dump(doc), kind)
            self.assertEqual([f.rule for f in fs], [rule], "%s: %s" % (kind, [f.line() for f in fs]))

    def test_the_minimal_document_of_each_kind_needs_only_the_required_fields(self):
        for kind in FIRST_KINDS:
            reg = registry(kind)
            doc = VALID[kind]()
            for k in list(doc):
                if k not in reg["document"]["required"]:
                    del doc[k]
            self.assertEqual(self.check(dump(doc), kind), [], kind)

    def test_each_required_field_of_each_kind_is_needed(self):
        for kind in FIRST_KINDS:
            reg = registry(kind)
            for k in reg["document"]["required"]:
                if k in ("schema", "kind"):
                    continue
                doc = VALID[kind]()
                del doc[k]
                self.assertEqual([f.rule for f in self.check(dump(doc), kind)], ["required-missing"], "%s %s" % (kind, k))

    def test_the_status_row_of_a_refs_record_with_a_float_age_is_refused(self):
        # the defect of the code before the pin (the age was a float on the refs backend): the registry says an integer
        fs = self.check(dump(status_doc(features=[feature_row(minutes_since_renewal=3.0)])))
        self.assertEqual([(f.rule, f.path) for f in fs], [("integer-float", "$.features[0].minutes_since_renewal")])

    def test_the_marker_of_a_refusal_equals_the_number_of_its_prefix(self):
        self.assertEqual(registry("qargi-refusal")["document"]["properties"]["schema"], {"const": 1})
        self.assertEqual(registry("qargi-refusal")["stream"], "stderr")


class RegistryFormat(Tmp):
    """The rules of the registry format, each broken once on a copy of a real file."""
    def reg(self):
        return copy.deepcopy(registry("qargi-marshal-check"))

    def test_the_real_files_are_well_formed(self):
        self.assertEqual(J.check_dir(), [])
        for kind in FIRST_KINDS:
            self.assertEqual(J.check_registry(registry(kind)), [], kind)
            self.assertEqual(registry(kind)["kind"], kind)

    def test_every_rule_of_the_format_is_broken_once(self):
        def doc(fn):
            r = self.reg()
            fn(r["document"])
            return r

        def top(fn):
            r = self.reg()
            fn(r)
            return r
        props = lambda d: d["properties"]
        deep = {"type": "array", "items": {}}
        cur = deep
        for _ in range(MAX_NEST + 2):
            cur["items"] = {"type": "array", "items": {}}
            cur = cur["items"]
        cases = {
            "registry-version": top(lambda r: r.update(registry=2)),
            "envelope-missing": top(lambda r: r.pop("about")),
            "envelope-unknown": top(lambda r: r.update(extra="x")),
            "envelope-type": top(lambda r: r.update(verbs=[])),
            "kind-name": top(lambda r: r.update(kind="Check")),
            "schema-number": top(lambda r: r.update(schema=0)),
            "status-value": top(lambda r: r.update(status="released")),
            "since-form": top(lambda r: r.update(since="0.3")),
            "stream-value": top(lambda r: r.update(stream="file")),
            "history-entry": top(lambda r: r.update(history=[{"schema": 1}])),
            "history-order": top(lambda r: r.update(schema=2)),
            "history-since": top(lambda r: r["history"][0].update(since="0.3.8")),
            "document-not-object": top(lambda r: r.update(document={"type": "array"})),
            "document-markers": doc(lambda d: d["required"].remove("kind")),
            "node-not-object": doc(lambda d: props(d).update(project="string")),
            "keyword-unknown": doc(lambda d: props(d)["project"].update(maxLength=3)),
            "keyword-needs-type": doc(lambda d: props(d).update(project={"pattern": "^a$"})),
            "type-number": doc(lambda d: props(d).update(project={"type": "number"})),
            "type-unknown": doc(lambda d: props(d).update(project={"type": "date"})),
            "enum-shape": doc(lambda d: props(d).update(project={"enum": []})),
            "const-shape": doc(lambda d: props(d).update(project={"const": [1]})),
            "value-type-mismatch": doc(lambda d: props(d).update(project={"type": "string", "const": 1})),
            "pattern-invalid": doc(lambda d: props(d).update(project={"type": "string", "pattern": "("})),
            "required-shape": doc(lambda d: d.update(required="project")),
            "required-unknown": doc(lambda d: d["required"].append("ghost_field")),
            "required-after-pin": doc(lambda d: props(d)["project"].update({"x-since": "0.4.0"})),
            "properties-shape": doc(lambda d: props(d).update(project={"type": "object", "properties": []})),
            "items-shape": doc(lambda d: props(d).update(project={"type": "array", "items": []})),
            "additional-shape": doc(lambda d: props(d).update(project={"type": "object", "additionalProperties": False})),
            "ref-form": doc(lambda d: props(d).update(project={"$ref": "lead"})),
            "ref-unresolved": doc(lambda d: props(d).update(project={"$ref": "#/$defs/nope"})),
            "ref-cycle": doc(lambda d: d["$defs"].update(a={"$ref": "#/$defs/b"}, b={"$ref": "#/$defs/a"})),
            "ref-siblings": doc(lambda d: props(d).update(project={"$ref": "#/$defs/lead", "type": "object"})),
            "defs-shape": doc(lambda d: props(d).update(project={"type": "string", "$defs": {}})),
            "annotation-type": doc(lambda d: props(d)["project"].update({"x-text": "yes"})),
            "annotation-misplaced": doc(lambda d: props(d)["project"].update({"x-ordered": True})),
            "reserved-not-null": doc(lambda d: props(d).update(project={"type": "string", "x-reserved": True})),
            "too-nested": doc(lambda d: props(d).update(project=deep)),
        }
        self.assertEqual(sorted(cases), sorted(set(FORMAT_RULES) - {"registry-not-object", "directory-entry", "directory-empty", "directory-unreadable",
                                                                    "file-name", "kind-duplicate"}))
        for rule, reg in cases.items():
            self.assertIn(rule, rules(J.check_registry(reg)), rule)

    def test_a_break_names_the_rule_and_the_path(self):
        r = self.reg()
        r["document"]["properties"]["project"] = {"type": "number"}
        fs = J.check_registry(r)
        self.assertEqual([(f.rule, f.path) for f in fs], [("type-number", "$.document.properties.project.type")])

    def test_registry_not_object(self):
        self.assertEqual([f.rule for f in J.check_registry([])], ["registry-not-object"])
        _, fs = J.check_text(b"[]")
        self.assertEqual([f.rule for f in fs], ["registry-not-object"])

    def test_the_parser_hooks_apply_to_a_registry_file_too(self):
        text = dump(self.reg())
        for rule, bad in (("duplicate-key", text.replace('"registry": 1,', '"registry": 1, "registry": 1,', 1)),
                          ("integer-float", text.replace('"registry": 1,', '"registry": 1.0,', 1)),
                          ("schema-float", text.replace('"schema": 1,', '"schema": 1.0,', 1)),
                          ("non-finite", text.replace('"registry": 1', '"registry": NaN', 1)),
                          ("truncated", text[:50])):
            reg, fs = J.check_text(bad)
            self.assertIsNone(reg, rule)
            self.assertIn(rule, rules(fs), rule)

    def test_the_directory_rules(self):
        good = dump(self.reg())
        # an empty directory
        self.assertEqual([f.rule for f in J.check_dir(self.dir)], ["directory-empty"])
        self.assertEqual([f.rule for f in J.check_dir(os.path.join(self.dir, "missing"))], ["directory-unreadable"])
        self.put("qargi-marshal-check.json", good)
        self.assertEqual(J.check_dir(self.dir), [])
        # a file that is not named after its kind, a second file with the same kind, a file that is not a plain .json file, a link
        self.put("qargi-other.json", good)
        self.put("notes.txt", "x")
        os.symlink(os.path.join(self.dir, "qargi-marshal-check.json"), os.path.join(self.dir, "link.json"))
        os.mkdir(os.path.join(self.dir, "sub.json"))
        fs = J.check_dir(self.dir)
        self.assertEqual(sorted((f.where, f.rule) for f in fs),
                         [("link.json", "directory-entry"), ("notes.txt", "directory-entry"), ("qargi-other.json", "file-name"),
                          ("qargi-other.json", "kind-duplicate"), ("sub.json", "directory-entry")])

    def test_a_broken_file_in_the_directory_is_named(self):
        self.put("qargi-marshal-check.json", self.reg())
        r = self.reg()
        r["kind"] = "qargi-second"
        r["history"] = [{"schema": 1, "since": "0.3.9", "change": "x"}]
        r["document"]["properties"]["kind"] = {"const": "qargi-second"}
        r["document"]["properties"]["project"] = {"type": "number"}
        self.put("qargi-second.json", r)
        fs = J.check_dir(self.dir)
        self.assertEqual([(f.where, f.rule) for f in fs], [("qargi-second.json", "type-number")])

    def test_every_rule_has_a_sentence(self):
        for r in RULE_NAMES:
            self.assertTrue(J.RULES[r].strip(), r)

    def test_the_four_first_kinds_are_pinned_at_the_first_release_and_named_after_their_files(self):
        self.assertEqual(J.kind_names(), sorted(FIRST_KINDS + DRAFT_KINDS))
        for kind in FIRST_KINDS:
            r = registry(kind)
            self.assertEqual((r["registry"], r["schema"], r["status"], r["since"]), (1, 1, "pinned", "0.3.9"), kind)

    def test_the_run_plan_kinds_are_drafts_of_the_release_that_adds_them(self):
        for kind in DRAFT_KINDS:
            r = registry(kind)
            self.assertEqual((r["registry"], r["schema"], r["status"], r["since"]), (1, 1, "draft", "0.3.10"), kind)



class CommandLine(Tmp):
    def test_check_of_the_directory(self):
        rc, out, err = run("check")
        self.assertEqual((rc, err), (0, ""), err)
        self.assertTrue(out.startswith("ok: %d registry files" % len(FIRST_KINDS + DRAFT_KINDS)), out)

    def test_check_file_and_stdin(self):
        p = os.path.join(KINDS, "qargi-handoff.json")
        self.assertEqual(run("check", p), (0, "", ""))
        with open(p, "rb") as f:
            self.assertEqual(run("check", "-", stdin=f.read()), (0, "", ""))

    def test_check_names_each_finding_on_its_own_line_of_stderr(self):
        r = registry("qargi-marshal-check")
        r["status"], r["stream"] = "released", "file"
        p = self.put("bad.json", r)
        rc, out, err = run("check", p)
        self.assertEqual((rc, out), (1, ""))
        self.assertEqual(sorted(ln.split(": ")[1].split(" ")[0] for ln in err.splitlines()), ["status-value", "stream-value"])
        for ln in err.splitlines():
            self.assertTrue(ln.startswith(p + ": "), ln)
        rc, out, err = run("check", "-", stdin=dump(r).encode())
        self.assertEqual(rc, 1)
        self.assertTrue(all(ln.startswith("-: ") for ln in err.splitlines()), err)

    def test_check_stdin_finds_a_float_a_constant_and_a_duplicate(self):
        for text, rule in (('{"registry": 1.0}', "integer-float"), ('{"registry": NaN}', "non-finite"), ('{"registry": 1, "registry": 1}', "duplicate-key"),
                           ('{"registry": 1', "truncated"), ("", "truncated")):
            rc, out, err = run("check", "-", stdin=text.encode())
            self.assertEqual(rc, 1, text)
            self.assertIn(" %s " % rule, err, text)
            self.assertNotIn("Traceback", err)

    def test_validate_on_stdin_for_each_kind(self):
        for kind in FIRST_KINDS:
            self.assertEqual(run("validate", kind, "-", stdin=dump(VALID[kind]()).encode()), (0, "", ""), kind)
            doc, rule = INVALID[kind]
            rc, out, err = run("validate", kind, "-", stdin=dump(doc).encode())
            self.assertEqual((rc, out), (1, ""), kind)
            self.assertEqual(len(err.splitlines()), 1, err)
            self.assertTrue(err.startswith("-: %s " % rule), err)

    def test_validate_on_a_file(self):
        p = self.put("doc.json", status_doc())
        self.assertEqual(run("validate", "qargi-marshal-status", p), (0, "", ""))
        q = self.put("bad.json", status_doc(project=None))
        rc, out, err = run("validate", "qargi-marshal-status", q)
        self.assertEqual(rc, 1)
        self.assertEqual(err, "%s: null-not-allowed $.project: null where string is declared\n" % q)

    def test_validate_stdin_finds_a_float_a_constant_a_duplicate_and_two_documents(self):
        good = dump(refusal_doc())
        cases = (("integer-float", good.replace('"exit": 1', '"exit": 1.0')), ("non-finite", good.replace('"exit": 1', '"exit": Infinity')),
                 ("duplicate-key", good.replace('"exit": 1,', '"exit": 1, "exit": 1,')), ("two-documents", good + "\n" + good),
                 ("schema-float", good.replace('"schema": 1', '"schema": 1.0')))
        for rule, text in cases:
            rc, out, err = run("validate", "qargi-refusal", "-", stdin=text.encode())
            self.assertEqual((rc, out), (1, ""), rule)
            self.assertIn(": %s " % rule, err, "%s: %s" % (rule, err))

    def test_a_line_of_a_refusal_is_a_document_without_its_prefix(self):
        line = 'qargi-refusal/1 ' + dump(refusal_doc())
        rc, _, err = run("validate", "qargi-refusal", "-", stdin=line.split(" ", 1)[1].encode())
        self.assertEqual(rc, 0, err)
        rc, _, err = run("validate", "qargi-refusal", "-", stdin=line.encode())
        self.assertEqual(rc, 1)
        self.assertIn(" invalid-json ", err)

    def test_usage_is_exit_2(self):
        for args in ((), ("bogus",), ("check", "a", "b"), ("validate",), ("validate", "qargi-refusal"), ("validate", "qargi-refusal", "a", "b")):
            rc, out, err = run(*args)
            self.assertEqual((rc, out), (2, ""), args)
            self.assertIn("usage:", err)

    def test_an_unknown_kind_names_the_kinds(self):
        rc, out, err = run("validate", "qargi-nothing", "-", stdin=b"{}")
        self.assertEqual((rc, out), (2, ""))
        for kind in FIRST_KINDS:
            self.assertIn(kind, err)
        rc, out, err = run("validate", "../kinds/qargi-refusal", "-", stdin=b"{}")
        self.assertEqual(rc, 2)

    def test_an_unreadable_input_is_exit_2(self):
        for args in (("check", os.path.join(self.dir, "none.json")), ("validate", "qargi-refusal", os.path.join(self.dir, "none.json"))):
            rc, out, err = run(*args)
            self.assertEqual((rc, out), (2, ""), args)
            self.assertIn("cannot read", err)
            self.assertNotIn("Traceback", err)

    def test_a_document_that_is_not_utf8_is_invalid_not_a_crash(self):
        rc, out, err = run("validate", "qargi-refusal", "-", stdin=b'{"a": "\xff"}')
        self.assertEqual(rc, 1)
        self.assertIn(" invalid-json ", err)

    def test_findings_are_capped(self):
        doc = status_doc(features=[feature_row(ttl_minutes="x") for _ in range(J.MAX_FINDINGS + 20)])
        rc, out, err = run("validate", "qargi-marshal-status", "-", stdin=dump(doc).encode())
        self.assertEqual(rc, 1)
        lines = err.splitlines()
        self.assertEqual(len(lines), J.MAX_FINDINGS + 1)
        self.assertIn("and 20 more findings", lines[-1])

    def test_the_module_runs_as_a_script_under_python_dash_i(self):
        p = subprocess.run([sys.executable, "-B", "-I", os.path.join(LIB, "jsonkind.py"), "check"], capture_output=True, cwd=self.dir)
        self.assertEqual(p.returncode, 0, p.stderr)


if __name__ == "__main__":
    unittest.main()
