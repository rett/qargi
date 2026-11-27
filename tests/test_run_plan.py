#!/usr/bin/env python3
"""The run plan checker (lib/run_plan.py): the format of a plan, every finding code, the order of the nodes in waves, the overlap of scopes, the
documents against their registry files, the exit statuses, and the guarantees (no state, no recursion, the same bytes give the same report).
The fixture plans are in tests/fixtures/run-plan/. Run: python3 tests/test_run_plan.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import ast
import copy
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FIX = os.path.join(HERE, "fixtures", "run-plan")
LIB = os.path.join(ROOT, "lib")
SCRIPT = os.path.join(LIB, "run_plan.py")
sys.path.insert(0, LIB)
import done_words as D  # noqa: E402
import jsonkind as K  # noqa: E402
import run_plan as RP  # noqa: E402


def slurp(path, mode="rb"):
    with open(path, mode) as f:
        return f.read()


def raw(name):
    return slurp(os.path.join(FIX, name + ".json"))


def plan(name):
    return json.loads(raw(name))


def report(name):
    return RP.check_bytes(raw(name))


def dump(doc):
    return json.dumps(doc).encode()


def codes(rep, severity=None):
    return [f["code"] for f in rep["findings"] if severity in (None, f["severity"])]


def finding(rep, code):
    found = [f for f in rep["findings"] if f["code"] == code]
    assert found, (code, rep["findings"])
    return found[0]


def node(ident, scope=("lib/%s.py",), after=None, **more):
    n = {"id": ident, "task": "work", "role": "build", "scope": [s.replace("%s", ident) if isinstance(s, str) else s for s in scope], "done": "python3 tests/test_x.py", "review_kind": "none"}
    if after is not None:
        n["after"] = after
    n.update(more)
    return n


def make(*nodes):
    return {"kind": "qargi-run-plan", "schema": 1, "project": "demo", "target_feature": "next", "nodes": list(nodes)}


def run(*args, cwd=ROOT, env=None):
    p = subprocess.run([sys.executable, "-I", SCRIPT] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                       cwd=cwd, env=env, universal_newlines=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


class Valid(unittest.TestCase):
    def test_a_linear_plan_runs_one_node_in_each_wave(self):
        rep = report("valid-linear")
        self.assertEqual((rep["valid"], rep["findings"]), (True, []))
        self.assertEqual(rep["waves"], [["format"], ["verb"], ["docs"]])
        self.assertEqual((rep["project"], rep["target_feature"], rep["nodes"]), ("demo", "release-next", 3))

    def test_independent_nodes_share_a_wave_and_a_review_is_only_a_note(self):
        rep = report("valid-waves")
        self.assertTrue(rep["valid"], rep["findings"])
        self.assertEqual(rep["waves"], [["alpha", "beta", "epsilon"], ["gamma"], ["delta"]])
        self.assertEqual([(f["code"], f["severity"], f["nodes"]) for f in rep["findings"]],
                         [("review-requested", "note", ["beta"]), ("review-requested", "note", ["delta"])])

    def test_scopes_that_cannot_meet_need_no_order(self):
        rep = report("valid-disjoint-globs")
        self.assertEqual((rep["valid"], rep["findings"], rep["waves"]), (True, [], [["backup", "config", "python", "shell"]]))

    def test_a_node_is_not_assumed_to_write_the_shared_files(self):
        rep = report("valid-shared-not-declared")
        self.assertEqual((rep["valid"], rep["findings"]), (True, []))

    def test_every_fixture_that_is_valid_is_also_a_plan_of_the_registered_shape(self):
        for name in sorted(os.listdir(FIX)):
            with self.subTest(name=name):
                with open(os.path.join(FIX, name), "rb") as f:
                    found = K.validate(K.registry_path("qargi-run-plan"), f.read())
                # the checker refuses more than the shape says (an unknown key, a role): a valid plan is never a finding of the shape
                if name.startswith("valid-"):
                    self.assertEqual([x.line() for x in found], [])

    def test_after_may_be_absent_empty_or_name_several_nodes(self):
        doc = make(node("a", after=[]), node("b"), node("c", after=["a", "b"]))
        rep = RP.check_bytes(dump(doc))
        self.assertTrue(rep["valid"], rep["findings"])
        self.assertEqual(rep["waves"], [["a", "b"], ["c"]])


class Findings(unittest.TestCase):
    def test_a_duplicate_id_names_the_id(self):
        rep = report("duplicate-id")
        f = finding(rep, "duplicate-id")
        self.assertEqual((f["severity"], f["nodes"], f["path"]), ("error", ["same"], "$.nodes[2].id"))
        self.assertFalse(rep["valid"])
        self.assertEqual(rep["waves"], [])

    def test_after_naming_an_unknown_node(self):
        rep = report("unknown-after")
        self.assertEqual((finding(rep, "unknown-after")["nodes"], rep["valid"], rep["waves"]), (["alpha"], False, []))
        self.assertIn("ghost", finding(rep, "unknown-after")["message"])

    def test_after_naming_the_node_itself(self):
        rep = report("self-after")
        self.assertEqual((finding(rep, "self-after")["nodes"], rep["valid"]), (["alpha"], False))

    def test_a_cycle_is_named_once(self):
        rep = report("cycle")
        self.assertEqual(codes(rep), ["cycle"])
        f = finding(rep, "cycle")
        self.assertEqual((f["cycle"], f["nodes"]), (["a", "c", "b"], ["a", "b", "c"]))
        self.assertIn("a after c after b after a", f["message"])
        self.assertEqual(rep["waves"], [])

    def test_two_cycles_name_the_one_through_the_smallest_node(self):
        rep = RP.check_bytes(dump(make(node("x", after=["y"]), node("y", after=["x"]), node("b", after=["c"]), node("c", after=["b"]))))
        self.assertEqual(finding(rep, "cycle")["cycle"], ["b", "c"])
        self.assertEqual(codes(rep).count("cycle"), 1)

    def test_a_key_the_plan_or_a_node_does_not_have_is_refused(self):
        rep = report("unknown-key")
        self.assertEqual(sorted(f["path"] for f in rep["findings"] if f["code"] == "unknown-key"), ["$", "$.nodes[0]"])
        self.assertFalse(rep["valid"])

    def test_a_role_qargi_does_not_know(self):
        rep = report("unknown-role")
        f = finding(rep, "unknown-role")
        self.assertEqual((f["nodes"], f["path"]), (["alpha"], "$.nodes[0].role"))
        self.assertIn("wizard", f["message"])
        self.assertIn("build", f["message"])

    def test_a_scope_that_is_absolute_or_holds_dot_dot(self):
        for name in ("bad-scope-absolute", "bad-scope-dotdot"):
            with self.subTest(name=name):
                rep = report(name)
                f = finding(rep, "bad-scope")
                self.assertEqual((f["nodes"], f["path"], rep["valid"]), (["alpha"], "$.nodes[0].scope[0]", False))

    def test_other_bad_scopes(self):
        for entry in ("", "a b", "a,b", "a/../b", "a//b", "a/./b", "a\tb", "..", "../x", 3, None):
            with self.subTest(entry=entry):
                rep = RP.check_bytes(dump(make(node("a", scope=[entry]))))
                self.assertIn("bad-scope", codes(rep))
        for entry in ("lib", "lib/", "./lib", "lib/*.py", "**", ".", "./", "docs/**/*.md"):
            with self.subTest(entry=entry):
                self.assertTrue(RP.check_bytes(dump(make(node("a", scope=[entry]))))["valid"])
        for scope in ([], "lib", {"a": 1}, 3, None, [f"p{i}" for i in range(101)]):
            with self.subTest(scope=scope):
                doc = make(node("a"))
                doc["nodes"][0]["scope"] = scope
                self.assertIn("bad-scope", codes(RP.check_bytes(dump(doc))))

    def test_a_done_that_reads_as_prose(self):
        rep = report("prose-done")
        f = finding(rep, "bad-done")
        self.assertEqual((f["nodes"], f["path"], rep["valid"]), (["alpha"], "$.nodes[0].done", False))

    def test_the_shape_of_the_plan(self):
        base = make(node("a"))
        cases = {
            "wrong-kind": dict(base, kind="qargi-other"),
            "wrong-schema": dict(base, schema=2),
            "bad-value": dict(base, project="Demo"),
            "empty-nodes": dict(base, nodes=[]),
            "not-an-object": [],
        }
        for code, doc in cases.items():
            with self.subTest(code=code):
                rep = RP.check_bytes(dump(doc))
                self.assertIn(code, codes(rep))
                self.assertFalse(rep["valid"])
        for key, value in (("schema", 1.0), ("schema", True), ("schema", "1"), ("target_feature", "master"), ("target_feature", "develop"),
                           ("target_feature", "A"), ("target_feature", "a" * 41), ("target_feature", 3), ("project", "x" * 25), ("project", "1x"), ("nodes", {})):
            with self.subTest(key=key, value=value):
                self.assertFalse(RP.check_bytes(dump(dict(base, **{key: value})))["valid"])
        self.assertTrue(RP.check_bytes(dump(dict(base, target_feature="a" * 40)))["valid"])

    def test_a_missing_key_is_named(self):
        doc = make(node("a"))
        del doc["project"]
        del doc["nodes"][0]["done"]
        rep = RP.check_bytes(dump(doc))
        self.assertEqual(sorted((f["path"], f["code"]) for f in rep["findings"]), [("$", "missing-key"), ("$.nodes[0]", "missing-key")])

    def test_the_fields_of_a_node(self):
        for key, value, code in (("id", "A", "bad-id"), ("id", "a--b", "bad-id"), ("id", 3, "bad-id"), ("id", "a" * 41, "bad-id"), ("task", "", "bad-value"),
                                 ("task", "  ", "bad-value"), ("task", 3, "bad-value"), ("role", 3, "bad-value"), ("role", "", "bad-value"),
                                 ("done", "", "bad-done"), ("done", 3, "bad-done"), ("done", "true\ntrue", "bad-done"), ("review_kind", "maybe", "bad-review-kind"),
                                 ("review_kind", None, "bad-review-kind"), ("after", "b", "bad-after"), ("after", [3], "bad-after"), ("after", ["Z"], "bad-after"),
                                 ("profile", "Big", "bad-value"), ("profile", 3, "bad-value"), ("runtime", "a b", "bad-value"), ("runtime", "", "bad-value")):
            with self.subTest(key=key, value=value):
                doc = make(node("a"))
                doc["nodes"][0][key] = value
                rep = RP.check_bytes(dump(doc))
                self.assertIn(code, codes(rep, "error"))
                self.assertFalse(rep["valid"])
        doc = make(node("a", after=["b", "b"]), node("b"))
        self.assertIn("bad-after", codes(RP.check_bytes(dump(doc))))
        self.assertTrue(RP.check_bytes(dump(make(node("a", profile="fast-one", runtime="runtime-1"))))["valid"])

    def test_a_node_that_is_not_an_object(self):
        rep = RP.check_bytes(dump(make(node("a"), 3, "x", None, [])))
        self.assertEqual(codes(rep).count("not-an-object"), 4)

    def test_text_that_is_not_a_plan(self):
        for text, code in ((b"", "invalid-json"), (b"[", "invalid-json"), (b"{", "invalid-json"), (b"NaN", "invalid-json"), (b"{\"kind\": Infinity}", "invalid-json"),
                           (b"\xff\xfe", "invalid-json"), (b"{} {}", "invalid-json"), (b"{\"a\": 1, \"a\": 2}", "duplicate-json-key"), (b"3", "not-an-object"),
                           (b"null", "not-an-object"), (b"{}", "wrong-kind"), (b"[" * 100000, "invalid-json")):
            with self.subTest(text=text[:20]):
                rep = RP.check_bytes(text)
                self.assertEqual((codes(rep), rep["valid"]), ([code], False))

    def test_a_duplicate_key_inside_a_node_is_found(self):
        text = raw("valid-linear").decode().replace('"id": "format"', '"id": "format", "id": "other"', 1)
        self.assertEqual(codes(RP.check_bytes(text.encode())), ["duplicate-json-key"])

    def test_limits(self):
        self.assertEqual(codes(RP.check_bytes(b" " * (RP.MAX_BYTES + 1))), ["too-large"])
        many = make(*[node("n%d" % i) for i in range(RP.MAX_NODES + 1)])
        self.assertEqual(codes(RP.check_bytes(dump(many))), ["too-many-nodes"])

    def test_findings_are_sorted_errors_first_and_a_note_never_fails_the_plan(self):
        doc = make(node("a", review_kind="advisor"), node("b", role="wizard"), node("c", review_kind="review"))
        rep = RP.check_bytes(dump(doc))
        self.assertEqual([(f["severity"], f["code"], f["nodes"]) for f in rep["findings"]],
                         [("error", "unknown-role", ["b"]), ("note", "review-requested", ["a"]), ("note", "review-requested", ["c"])])
        self.assertFalse(rep["valid"])
        self.assertTrue(RP.check_bytes(dump(make(node("a", review_kind="advisor"))))["valid"])


class Overlap(unittest.TestCase):
    def test_two_unordered_nodes_that_can_touch_one_path(self):
        rep = report("overlap-direct")
        f = finding(rep, "scope-overlap-unordered")
        self.assertEqual((f["nodes"], f["patterns"], f["severity"], rep["valid"]), (["alpha", "beta"], ["lib/a.py", "lib/"], "error", False))
        self.assertEqual(rep["waves"], [["alpha", "beta"]])

    def test_the_overlap_of_globs_is_found_and_the_pair_is_named(self):
        rep = report("overlap-glob")
        found = [(f["nodes"], f["patterns"]) for f in rep["findings"] if f["code"] == "scope-overlap-unordered"]
        self.assertEqual(found, [(["alpha", "beta"], ["tests/*.py", "tests/test_x.py"]), (["delta", "gamma"], ["lib/a*.py", "lib/*.py"])])

    def test_an_order_by_after_resolves_it_directly_and_through_other_nodes(self):
        self.assertTrue(report("valid-overlap-ordered-transitive")["valid"])
        direct = make(node("a", scope=["lib/"]), node("b", scope=["lib/x.py"], after=["a"]))
        self.assertTrue(RP.check_bytes(dump(direct))["valid"])
        long = make(node("a", scope=["lib/"]), node("b", scope=["docs"], after=["a"]), node("c", scope=["tests"], after=["b"]), node("d", scope=["lib/x.py"], after=["c"]))
        self.assertTrue(RP.check_bytes(dump(long))["valid"])
        # a node that is a sibling of the chain is not ordered with it
        side = make(node("a", scope=["lib/"]), node("b", scope=["docs"], after=["a"]), node("s", scope=["lib/y.py"]))
        self.assertEqual(finding(RP.check_bytes(dump(side)), "scope-overlap-unordered")["nodes"], ["a", "s"])

    def test_a_shared_output_listed_by_two_unordered_nodes(self):
        rep = report("overlap-shared")
        f = finding(rep, "scope-overlap-unordered")
        self.assertEqual((f["nodes"], f["patterns"]), (["alpha", "beta"], ["CHANGELOG.md", "./CHANGELOG.md"]))
        self.assertIn("a file most tasks change", f["message"])
        for shared in RP.SHARED:
            with self.subTest(shared=shared):
                both = make(node("a", scope=[shared]), node("b", scope=[shared]))
                self.assertIn("scope-overlap-unordered", codes(RP.check_bytes(dump(both))))
                ordered = make(node("a", scope=[shared]), node("b", scope=[shared], after=["a"]))
                self.assertTrue(RP.check_bytes(dump(ordered))["valid"])
                self.assertTrue(RP.check_bytes(dump(make(node("a", scope=[shared]), node("b", scope=["lib/b.py"]))))["valid"])

    def test_the_overlap_is_not_looked_for_while_the_order_is_unsound(self):
        rep = RP.check_bytes(dump(make(node("a", scope=["lib/"], after=["ghost"]), node("b", scope=["lib/"]))))
        self.assertEqual(codes(rep), ["unknown-after"])

    def test_the_decision_on_scope_pairs(self):
        yes = [("lib", "lib/a.py"), ("lib/a.py", "lib/a.py"), ("lib/*.py", "lib/a.py"), ("lib/a*.py", "lib/*b.py"), ("**", "x/y"), ("docs/**/*.md", "docs/ref/a.md"),
               ("docs/**/*.md", "docs/a.md"), ("tests/**", "tests"), (".", "lib/a.py"), ("./lib/", "lib/a.py"), ("a/*/c", "a/b/c"), ("lib/[ab].py", "lib/a.py"),
               ("lib/{a}.py", "lib/c.py"), ("lib/a.py/", "lib/a.py/x"), ("a/b", "a"), ("*/x", "y/x"), ("*", "lib"), ("**/*.py", "lib/x.sh"), ("lib/a?c.py", "lib/a*.py")]
        no = [("lib/a.py", "lib/b.py"), ("lib/*.py", "lib/*.sh"), ("lib", "docs"), ("lib/[ab].py", "lib/c.py"), ("a/*/c", "a/b/d"), ("docs/**/*.md", "tests/x.md"),
              ("x*", "y*"), ("lib/a?.py", "lib/b?.py"), ("a/b/c", "a/b/d/e"), ("lib/x", "lib/xy"), ("*.py", "*.sh"), ("a*", "b*/x"), ("lib/*.py", "lib/x.sh/y.py")]
        for a, b in yes:
            with self.subTest(a=a, b=b):
                self.assertTrue(RP.scopes_overlap(RP.scope_entry(a), RP.scope_entry(b)))
                self.assertTrue(RP.scopes_overlap(RP.scope_entry(b), RP.scope_entry(a)))
        for a, b in no:
            with self.subTest(a=a, b=b):
                self.assertFalse(RP.scopes_overlap(RP.scope_entry(a), RP.scope_entry(b)))
                self.assertFalse(RP.scopes_overlap(RP.scope_entry(b), RP.scope_entry(a)))

    def test_a_pattern_that_cannot_be_decided_is_an_overlap(self):
        for a, b in (("lib/\\*.py", "lib/x.py"), ("lib/[!a].py", "lib/{x}.py"), ("lib/*a*", "lib/*b*")):
            with self.subTest(a=a, b=b):
                self.assertTrue(RP.scopes_overlap(RP.scope_entry(a), RP.scope_entry(b)))


class Done(unittest.TestCase):
    """The DONE rule of a prepared run, applied from the current directory."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "scripts"))
        for name in ("scripts/check.sh", "make-it.sh"):
            with open(os.path.join(self.tmp.name, name), "w") as f:
                f.write("#!/bin/sh\n")
        here = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, here)

    def verdict(self, line, scope=("lib/",)):
        """The codes of the errors of a plan of one node whose DONE is line, checked from a directory that holds scripts/check.sh and make-it.sh."""
        rep = RP.check_bytes(dump(make(node("a", scope=list(scope), done=line))))
        return [f["code"] for f in rep["findings"] if f["severity"] == "error"]

    def test_commands_that_are_real(self):
        for line in ("python3 tests/test_x.py", "bash -c true", "true && false", "cd lib && python3 x.py", "FOO=1 python3 x.py", "! false", "if true; then true; fi",
                     "./scripts/check.sh", "scripts/check.sh --fast", "bash scripts/check.sh", "FOO=1 ./make-it.sh && true", "true && ./not-there.sh", "$HOME/bin/x",
                     "`echo true`", "$(echo true)", "[[ -n x ]]", "f() { true; }; f", ":"):
            with self.subTest(line=line):
                self.assertEqual(self.verdict(line), [])

    def test_commands_that_are_not(self):
        for line in ("all the tests pass", "coverage > 80%", "tests pass & lint is clean", "it's done", "", "   ", "true\ntrue", "( true", "# only a comment is no command", "no-such-tool-here arg",
                     "./not-there.sh", "scripts/missing.sh", "/no/such/script"):
            with self.subTest(line=line):
                self.assertEqual(self.verdict(line), ["bad-done"])

    def test_a_script_the_task_may_create_is_found_in_the_scope(self):
        self.assertEqual(self.verdict("./tests/new_check.sh", scope=["tests/"]), [])
        self.assertEqual(self.verdict("tests/new_check.sh", scope=["tests/*.sh"]), [])
        self.assertEqual(self.verdict("tests/new_check.sh", scope=["tests/new_check.sh"]), [])
        self.assertEqual(self.verdict("./tests/new_check.sh", scope=["docs/"]), ["bad-done"])

    def test_an_absolute_path_is_a_file_or_not(self):
        self.assertEqual(self.verdict(os.path.join(self.tmp.name, "make-it.sh")), [])
        self.assertEqual(self.verdict(os.path.join(self.tmp.name, "nope.sh")), ["bad-done"])

    def test_the_scanner_is_the_one_of_the_prepare_check(self):
        self.assertEqual(D.command_words("FOO=1 a b && c | d; (e)"), ["a", "c", "d", "e"])
        self.assertEqual(D.command_words("f() { g; }; f"), ["}"])        # the name the line defines is no command word; the closing brace is a keyword
        self.assertEqual(D.command_words("case x in a) b;; esac"), ["case"])
        self.assertEqual(D.command_words("echo 'a b' \"c d\" `e` 2>/dev/null"), ["echo"])
        self.assertEqual(D.command_words("cmd1; (cmd2; cmd3)"), ["cmd1", "cmd2", "cmd3"])
        self.assertEqual(D.command_words(""), [])
        rc, out, err = run_script("done_words.py", "a && b")
        self.assertEqual((rc, out), (0, "a\nb\n"))
        local = slurp(os.path.join(LIB, "local.sh"), "r")
        self.assertIn("done_words.py", local)
        self.assertNotIn("TB_WORDS_PY", local)


def run_script(name, *args):
    p = subprocess.run([sys.executable, "-I", os.path.join(LIB, name)] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       stdin=subprocess.DEVNULL, universal_newlines=True, timeout=60)
    return p.returncode, p.stdout, p.stderr


class Roles(unittest.TestCase):
    def test_the_roles_are_the_ones_role_list_prints(self):
        rc, out, err = run_script("role.py", "list")
        self.assertEqual(rc, 0, err)
        listed = [ln.split()[0] for ln in out.splitlines()[1:] if ln.strip()]
        self.assertEqual(RP.known_roles(), listed)
        for r in ("build", "review", "test", "write"):
            self.assertIn(r, listed)
        self.assertNotIn("lead", listed)

    def test_a_role_of_the_user_is_known_once_it_exists(self):
        conf = tempfile.TemporaryDirectory()
        self.addCleanup(conf.cleanup)
        doc = dump(make(node("a", role="custom")))
        env = dict(os.environ, QARGI_CONF=conf.name)
        path = os.path.join(conf.name, "plan.json")
        with open(path, "wb") as f:
            f.write(doc)
        rc, out, err = run("plan", "check", path, env=env)
        self.assertEqual(rc, 1, out)
        self.assertIn("unknown-role", out)
        os.makedirs(os.path.join(conf.name, "roles", "custom"))
        with open(os.path.join(conf.name, "roles", "custom", "role.json"), "w") as f:
            json.dump({"class": "write", "description": "mine"}, f)
        with open(os.path.join(conf.name, "roles", "custom", "ROLE.md"), "w") as f:
            f.write("# Role: custom\n")
        rc, out, err = run("plan", "check", path, env=env)
        self.assertEqual((rc, err), (0, ""), out)


class Documents(unittest.TestCase):
    def test_the_registry_files_are_the_two_kinds_of_the_checker(self):
        for kind in (RP.PLAN_KIND, RP.CHECK_KIND):
            reg, found = K.load_registry(K.registry_path(kind))
            self.assertEqual([x.line() for x in found], [])
            self.assertEqual((reg["kind"], reg["schema"], reg["status"], reg["stream"]), (kind, 1, "draft", "stdout"))

    def test_the_document_of_every_fixture_is_valid_against_its_kind(self):
        for name in sorted(os.listdir(FIX)):
            with self.subTest(name=name):
                rep = RP.check_bytes(slurp(os.path.join(FIX, name)))
                text, why = RP.json_document(rep)
                self.assertIsNone(why)
                self.assertEqual([x.line() for x in K.validate(K.registry_path(RP.CHECK_KIND), text)], [])
                self.assertEqual(json.loads(text), rep)
                self.assertTrue(text.endswith("}\n") and text.count("\n") > 1)

    def test_the_output_of_the_command_is_one_valid_document_at_exit_0_and_at_exit_1(self):
        for name, rc in (("valid-waves", 0), ("cycle", 1), ("overlap-glob", 1)):
            with self.subTest(name=name):
                code, out, err = run("plan", "check", os.path.join(FIX, name + ".json"), "--json")
                self.assertEqual((code, err), (rc, ""))
                self.assertEqual([x.line() for x in K.validate(K.registry_path(RP.CHECK_KIND), out)], [])
                self.assertEqual(json.loads(out)["valid"], rc == 0)
        # a plan that breaks the shape of the kind is a plan with findings, not a defect
        code, out, err = run("plan", "check", "--json", os.path.join(FIX, "unknown-key.json"))
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)["valid"], False)

    def test_a_report_that_breaks_its_own_registry_file_is_a_defect(self):
        rep = RP.check_bytes(raw("valid-linear"))
        for change in (dict(valid="yes"), dict(waves=[["a"], 3]), dict(nodes=1.5), dict(digest="md5:00"), dict(kind="qargi-run-plan"),
                       dict(findings=[dict(code="x", severity="fatal", message="m", nodes=[], path="$")]), dict(project=3)):
            with self.subTest(change=change):
                text, why = RP.json_document(dict(rep, **change))
                self.assertIsNone(text)
                self.assertIn("breaks its registry file", why)
        text, why = RP.json_document(dict(rep, nodes=float("nan")))
        self.assertEqual((text, "cannot be written as JSON" in why), (None, True))

    def test_the_plan_kind_describes_a_plan_the_checker_accepts(self):
        reg = json.loads(slurp(K.registry_path(RP.PLAN_KIND)))
        node_shape = reg["document"]["$defs"]["node"]
        keys = set(node_shape["properties"])
        self.assertEqual(keys, set(RP.NODE_REQUIRED) | set(RP.NODE_OPTIONAL))
        self.assertEqual(set(node_shape["required"]), set(RP.NODE_REQUIRED))
        self.assertEqual(set(reg["document"]["properties"]) - {"schema"}, set(RP.TOP_KEYS) - {"schema"})
        self.assertEqual(node_shape["properties"]["review_kind"]["enum"], list(RP.REVIEW_KINDS))

    def test_every_code_the_checker_raises_is_listed_in_the_registry_file_and_has_a_case(self):
        reg = json.loads(slurp(K.registry_path(RP.CHECK_KIND)))
        listed = reg["document"]["$defs"]["finding"]["properties"]["code"]["description"]
        raised = {"invalid-json", "duplicate-json-key"}                 # of lib/backlog_graph.py's JSON reader
        for call in ast.walk(ast.parse(slurp(SCRIPT, "r"))):
            if isinstance(call, ast.Call):
                name = getattr(call.func, "attr", getattr(call.func, "id", ""))
                pos = {"require": 1, "add": 0, "Invalid": 0}.get(name)
                if pos is not None and len(call.args) > pos and isinstance(call.args[pos], ast.Constant) and isinstance(call.args[pos].value, str):
                    raised.add(call.args[pos].value)
        self.assertGreaterEqual(len(raised), 20)
        for code in sorted(raised):
            self.assertIn(code, listed)
        for word in re.findall(r"[a-z]+(?:-[a-z]+)+", listed.split(":", 1)[1].split(".")[0]):     # and no word of the list is a code that is not raised
            self.assertIn(word, raised)


class Command(unittest.TestCase):
    def test_exit_0_for_a_valid_plan_with_notes_and_1_for_an_invalid_one(self):
        rc, out, err = run("plan", "check", os.path.join(FIX, "valid-waves.json"))
        self.assertEqual((rc, err), (0, ""))
        self.assertTrue(out.startswith("run plan check: valid\n"), out)
        self.assertIn("    wave 1: alpha, beta, epsilon\n    wave 2: gamma\n    wave 3: delta\n", out)
        self.assertIn("note review-requested [beta]:", out)
        rc, out, err = run("plan", "check", os.path.join(FIX, "cycle.json"))
        self.assertEqual((rc, err), (1, ""))
        self.assertTrue(out.startswith("run plan check: invalid\n"), out)
        self.assertIn("error cycle [a, b, c]:", out)

    def test_exit_2_for_a_wrong_call_or_a_file_that_cannot_be_read(self):
        for args in ((), ("plan", "check"), ("check", "x"), ("plan", "check", "a", "b"), ("plan", "check", "x", "--nope")):
            with self.subTest(args=args):
                rc, out, err = run(*args)
                self.assertEqual((rc, out), (2, ""), err)
        with tempfile.TemporaryDirectory() as d:
            for path in (os.path.join(d, "missing.json"), d):
                rc, out, err = run("plan", "check", path)
                self.assertEqual((rc, out), (2, ""))
                self.assertIn("cannot read", err)
                rc, out, err = run("plan", "check", path, "--json")
                self.assertEqual((rc, out), (2, ""))

    def test_the_same_bytes_give_the_same_output(self):
        for name in sorted(os.listdir(FIX)):
            with self.subTest(name=name):
                first, second = RP.check_bytes(raw(name[:-5])), RP.check_bytes(raw(name[:-5]))
                self.assertEqual(RP.json_document(first), RP.json_document(second))
                self.assertEqual(RP.text_report(first), RP.text_report(second))
        for name in ("valid-waves", "overlap-glob"):                    # and the command, as a process of its own, twice
            for extra in ((), ("--json",)):
                with self.subTest(name=name, extra=extra):
                    args = ("plan", "check", os.path.join(FIX, name + ".json")) + extra
                    first, second = run(*args), run(*args)
                    self.assertEqual(first, second)
                    self.assertIn(first[0], (0, 1))

    def test_the_order_of_the_nodes_in_the_file_does_not_change_the_waves(self):
        doc = plan("valid-waves")
        shuffled = dict(doc, nodes=list(reversed(doc["nodes"])))
        a, b = RP.check_bytes(dump(doc)), RP.check_bytes(dump(shuffled))
        self.assertEqual(a["waves"], b["waves"])
        self.assertEqual([f["code"] for f in a["findings"]], [f["code"] for f in b["findings"]])
        self.assertEqual(sorted(f["nodes"] for f in a["findings"]), sorted(f["nodes"] for f in b["findings"]))

    def test_it_reads_the_plan_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            env = dict(os.environ, QARGI_STATE=os.path.join(d, "state"), QARGI_CONF=os.path.join(d, "conf"), HOME=os.path.join(d, "home"))
            work = os.path.join(d, "work")
            os.makedirs(work)
            before = sorted(os.listdir(d))
            rc, out, err = run("plan", "check", os.path.join(FIX, "valid-linear.json"), "--json", cwd=work, env=env)
            self.assertEqual((rc, err), (0, ""))
            self.assertEqual((sorted(os.listdir(d)), os.listdir(work)), (before, []))
            self.assertFalse(os.path.exists(env["QARGI_STATE"]))

    def test_a_long_chain_and_a_deep_document_do_not_recurse(self):
        chain = make(*[node("n%d" % i, after=["n%d" % (i - 1)] if i else None) for i in range(300)])
        rep = RP.check_bytes(dump(chain))
        self.assertTrue(rep["valid"], rep["findings"][:2])
        self.assertEqual(len(rep["waves"]), 300)
        ring = copy.deepcopy(chain)
        ring["nodes"][0]["after"] = ["n299"]
        rep = RP.check_bytes(dump(ring))
        self.assertEqual(finding(rep, "cycle")["cycle"][:2], ["n0", "n299"])
        self.assertEqual(len(finding(rep, "cycle")["cycle"]), 300)
        src = slurp(SCRIPT, "r")
        self.assertNotIn("sys.setrecursionlimit", src)

    def test_the_text_of_a_message_cannot_break_the_report(self):
        doc = make(node("a", role="x\x1b[31m‮"))
        rc, out, err = run("plan", "check", self.put(dump(doc)))
        self.assertEqual(rc, 1)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("‮", out)

    def put(self, data):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        path = os.path.join(d.name, "plan.json")
        with open(path, "wb") as f:
            f.write(data)
        return path


if __name__ == "__main__":
    unittest.main()
