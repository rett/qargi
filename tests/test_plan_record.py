#!/usr/bin/env python3
"""The stored plan record (qargi.plan/0): what `plan_token --basis LABELS --verb V --target P:O` keeps in STATE/plans/TOKEN.json, and `qargi plan show TOKEN [--json]`.
The record binds the exact bytes that were hashed (input_sha256, input_newline), has one entry for each hashed line with its label and kind, and keeps the old `basis` key.
`plan show` is read only (no file made, changed or removed, also under QARGI_DRY=1), opens the directory and the file without following a link, and refuses with
plan-unknown, plan-expired or plan-record-invalid, each leaving the plans directory as it was. The five verbs that keep a record are driven by tests/test_plan_record.sh.
Offline; a scratch home. Run: python3 tests/test_plan_record.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
QARGI = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import refusal as R  # noqa: E402


def sh(script, **env):
    """A bash script that has sourced lib/lib.sh: (status, standard output, standard error)."""
    r = subprocess.run(["bash", "-c", 'set -u; . "$1/lib.sh"; shift; ' + script, "bash", LIB], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       universal_newlines=True, env=dict(os.environ, **env))
    return r.returncode, r.stdout, r.stderr


def qargi(*args, **env):
    """`qargi plan ...`, always through bin/qargi (which routes the command to lib/plan.py): the route is part of what is tested."""
    r = subprocess.run([QARGI] + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, env=dict(os.environ, **env))
    return r.returncode, r.stdout, r.stderr


def contract(err):
    lines = [l for l in err.split("\n") if l.startswith("qargi-refusal/1 ")]
    assert len(lines) == 1, err
    return json.loads(lines[0][len("qargi-refusal/1 "):])


def plans_dir():
    return os.path.join(os.environ["QARGI_STATE"], "plans")


def listing():
    """Everything below the state directory: the names, the kinds, the sizes, the modes and the times of change (the nanoseconds too)."""
    out = []
    for base, dirs, files in os.walk(os.environ["QARGI_STATE"]):
        for n in sorted(dirs + files):
            p = os.path.join(base, n)
            st = os.lstat(p)
            out.append((p, st.st_mode, st.st_size, st.st_mtime_ns, st.st_nlink))
    return sorted(out)


def keep(text, labels, verb="release start", target="acme:0.4.0", **env):
    """plan_token --basis on the text: (status, token, standard error)."""
    rc, out, err = sh('printf "%s" "$PLAN" | plan_token --basis "$LABELS" --verb "$VERB" --target "$TARGET"', PLAN=text, LABELS=labels, VERB=verb, TARGET=target, **env)
    return rc, out.strip(), err


def stored(token):
    with open(os.path.join(plans_dir(), token + ".json"), encoding="utf-8") as f:
        return json.load(f)


def rebuild(rec):
    return "\n".join(x["value"] for x in rec["lines"]) + ("\n" if rec["input_newline"] else "")


class Scratch(unittest.TestCase):
    """A state directory of its own for each test."""

    def setUp(self):
        self.state = tempfile.mkdtemp(prefix="planstate.")
        self.addCleanup(shutil.rmtree, self.state, True)
        old = os.environ.get("QARGI_STATE")
        os.environ["QARGI_STATE"] = self.state
        self.addCleanup(lambda: os.environ.__setitem__("QARGI_STATE", old) if old is not None else os.environ.pop("QARGI_STATE", None))


class TheRecord(Scratch):
    PLAN = "acme\nrelease\n0.4.0\nREADME.md\nsrc/a b.py\n"

    def test_the_record_has_the_fields_of_the_design_and_the_old_basis_key(self):
        rc, tok, err = keep(self.PLAN, "project:name kind:label version:name files:path", QARGI_PLAN_NOW="2026-11-22T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        rec = stored(tok)
        self.assertEqual(list(rec), ["schema", "verb", "context", "target", "lines", "input_sha256", "input_newline", "token", "created", "expires", "basis"])
        self.assertEqual((rec["schema"], rec["verb"], rec["context"], rec["target"], rec["token"]), ("qargi.plan/0", "release start", "lead", {"project": "acme", "object": "0.4.0"}, tok))
        self.assertEqual((rec["created"], rec["expires"]), ("2026-11-22T10:00:00Z", "2026-11-29T10:00:00Z"))
        self.assertEqual(rec["basis"], [{"label": "project", "lines": ["acme"]}, {"label": "kind", "lines": ["release"]}, {"label": "version", "lines": ["0.4.0"]},
                                        {"label": "files", "lines": ["README.md", "src/a b.py"]}])
        self.assertEqual(os.stat(os.path.join(plans_dir(), tok + ".json")).st_mode & 0o777, 0o600)
        self.assertEqual(os.stat(plans_dir()).st_mode & 0o777, 0o700)
        self.assertEqual(tok, hashlib.sha256(self.PLAN.encode()).hexdigest()[:12], "the token is the one plan_token always made")

    def test_the_lines_rebuild_the_input_and_hash_to_the_token_with_and_without_a_final_newline(self):
        for text in ("a\nb\nc\n", "a\nb\nc", "a\n\nb\n\n", "\n", "", "one", "a\r\nb\n", "café ✓\nx\n"):
            with self.subTest(text=text):
                rc, tok, err = keep(text, "x:name y:ref z:path")
                self.assertEqual((rc, err), (0, ""))
                rec = stored(tok)
                self.assertEqual(rebuild(rec), text)
                self.assertEqual(rec["input_newline"], text.endswith("\n"))
                self.assertEqual(rec["input_sha256"], hashlib.sha256(text.encode()).hexdigest())
                self.assertEqual(rec["input_sha256"][:12], tok)
                self.assertEqual(R.plan_problem(rec, tok), None)

    def test_each_line_has_an_entry_with_its_label_and_a_repeated_label_is_written_out(self):
        _, tok, _ = keep("p\nr\nb1\nb2\nb3\n", "project:name remote:count branches:ref")
        self.assertEqual([(x["label"], x["kind"], x["value"]) for x in stored(tok)["lines"]],
                         [("project", "name", "p"), ("remote", "count", "r"), ("branches", "ref", "b1"), ("branches", "ref", "b2"), ("branches", "ref", "b3")])

    def test_a_label_given_again_for_the_next_line_covers_both_and_the_basis_groups_them(self):
        # a list in the middle of a plan (the assets of a publish, the parts of a waiver) has as many words as it has lines: the basis key that plan-stale reads
        # keeps one entry for the label, with the lines of all its words, so that `moved` names the label once and sees a change of any of its lines
        text = "p\nv\nx1\nx2\nx3\nsig\n"
        rc, tok, err = keep(text, "project:name version:name part:label part:label part:label sig:sha")
        self.assertEqual((rc, err), (0, ""))
        rec = stored(tok)
        self.assertEqual([x["label"] for x in rec["lines"]], ["project", "version", "part", "part", "part", "sig"])
        self.assertEqual(rec["basis"], [{"label": "project", "lines": ["p"]}, {"label": "version", "lines": ["v"]}, {"label": "part", "lines": ["x1", "x2", "x3"]}, {"label": "sig", "lines": ["sig"]}])
        self.assertEqual(rebuild(rec), text)
        _, tok2, _ = keep("p\nv\nx1\nx2\nCHANGED\nsig\n", "project:name version:name part:label part:label part:label sig:sha")
        self.assertEqual(R.basis_moved(tok, tok2, self.state), ["part"])

    def test_a_label_list_longer_than_the_input_has_entries_only_for_the_lines_and_a_shorter_one_takes_the_rest(self):
        _, tok, _ = keep("a\nb\n", "one:sha two:sha three:sha four:sha")
        rec = stored(tok)
        self.assertEqual([x["label"] for x in rec["lines"]], ["one", "two"])
        self.assertEqual([b["label"] for b in rec["basis"]], ["one", "two", "three", "four"], "the old key keeps a label that has no line")
        _, tok, _ = keep("a\nb\nc\nd\n", "head:sha rest:path")
        self.assertEqual([(x["label"], x["kind"]) for x in stored(tok)["lines"]], [("head", "sha"), ("rest", "path"), ("rest", "path"), ("rest", "path")])

    def test_a_label_without_a_kind_is_a_name_and_a_kind_that_is_not_one_is_a_defect(self):
        _, tok, _ = keep("a\nb\n", "plain other:count")
        self.assertEqual([x["kind"] for x in stored(tok)["lines"]], ["name", "count"])
        rc, out, err = keep("a\n", "x:secret")
        self.assertEqual(rc, 70, err)
        for bad in ("x:", "X:name", "x:name:ref"):
            with self.subTest(labels=bad):
                self.assertEqual(keep("a\n", bad)[0], 70)

    def test_the_verb_and_the_target_are_the_call_sites_to_say_and_a_bad_one_is_a_defect(self):
        rc, out, err = sh('echo x | plan_token --basis "line"')
        self.assertEqual(rc, 2)
        self.assertIn("needs --verb VERB and --target PROJECT:OBJECT", err)
        rc, out, err = sh('echo x | plan_token --basis "line" --verb "release start"')
        self.assertEqual(rc, 2)
        rc, out, err = sh('echo x | plan_token --basis "line" --who me')
        self.assertEqual(rc, 2)
        for verb, target in (("Release Start", "acme:0.4.0"), ("release start", "acme"), ("release start", "Acme:x"), ("release start", ":x"), ("release start", "acme:")):
            with self.subTest(verb=verb, target=target):
                self.assertEqual(keep("a\n", "x", verb=verb, target=target)[0], 70)
        _, tok, _ = keep("a\n", "x", target="acme:a:b c")
        self.assertEqual(stored(tok)["target"], {"project": "acme", "object": "a:b c"}, "the object is what follows the first colon")

    def test_nothing_is_kept_in_a_dry_run_and_the_token_is_the_same(self):
        rc, tok, err = keep("a dry plan\n", "line", QARGI_DRY="1")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(tok, hashlib.sha256(b"a dry plan\n").hexdigest()[:12])
        self.assertFalse(os.path.exists(os.path.join(plans_dir(), tok + ".json")))

    def test_the_scratch_copy_of_a_dry_run_is_not_a_record_and_is_still_read_by_moved(self):
        d = os.path.join(os.environ["QARGI_STATE"], "scratch")
        os.makedirs(os.path.join(d, "plans"))
        _, a, _ = keep("x\ny\n", "one two")
        _, b, _ = keep("x\nz\n", "one two")
        rc, out, err = sh('printf "x\\nz\\n" | QARGI_STATE="$D" python3 -I "$QARGI_TOOL/lib/refusal.py" basis scratch "$B" "one two"', D=d, B=b, QARGI_TOOL=ROOT)
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(sorted(stored_scratch(d, b)), ["basis", "token"])
        self.assertEqual(R.basis_moved(b, b, d), [])
        with self.assertRaises(R.PlanRefusal) as ctx:
            R.plan_read(b, d)
        self.assertEqual(ctx.exception.code, "plan-unknown")
        self.assertNotEqual(a, b)


def stored_scratch(d, token):
    with open(os.path.join(d, "plans", token + ".json"), encoding="utf-8") as f:
        return json.load(f)


class ThePlanShow(Scratch):
    def setUp(self):
        Scratch.setUp(self)
        _, self.tok, _ = keep("acme\nrelease\n0.4.0\nREADME.md\nsrc/a.py\n", "project:name kind:label version:name files:path", QARGI_PLAN_NOW="2026-11-22T10:00:00Z")
        self.path = os.path.join(plans_dir(), self.tok + ".json")

    def refused(self, token, code, **env):
        """plan show must refuse with code, change nothing and print nothing on standard output."""
        before = listing()
        rc, out, err = qargi("plan", "show", token, **env)
        self.assertEqual((rc, out), (1, ""), err)
        obj = contract(err)
        self.assertEqual((obj["code"], obj["exit"], obj["verb"]), (code, 1, "plan show"), err)
        self.assertEqual(listing(), before, "a refused show changes no file")
        return obj, err

    def rewrite(self, rec):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(rec, f)
        os.chmod(self.path, 0o600)

    def test_a_valid_record_is_shown_as_text_and_as_json_and_nothing_changes(self):
        before = listing()
        rc, out, err = qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out.split("\n"), ["plan %s: release start (lead)" % self.tok, "target: acme 0.4.0", "  project  acme", "  kind     release", "  version  0.4.0",
                                           "  files    README.md", "  files    src/a.py", "created: 2026-11-22T10:00:00Z", "expires: 2026-11-29T10:00:00Z", ""])
        rc, out, err = qargi("plan", "show", self.tok, "--json", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        shown = json.loads(out)
        self.assertEqual(shown.pop("state"), "valid")
        self.assertEqual(shown, stored(self.tok))
        self.assertEqual(listing(), before)

    def test_it_works_under_a_dry_run(self):
        rc, out, err = qargi("plan", "show", self.tok, QARGI_DRY="1", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("release start", out)
        rc, out, err = qargi("plan", "show", self.tok, "--json", QARGI_DRY="1", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, json.loads(out)["state"]), (0, "valid"))

    def test_it_writes_no_audit_line_and_prunes_nothing(self):
        old = os.path.join(plans_dir(), "aaaaaaaaaaaa.json")
        with open(old, "w") as f:
            f.write("{}")
        os.utime(old, (1, 1))
        before = listing()
        self.assertEqual(qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0], 0)
        self.assertEqual(listing(), before)
        self.assertTrue(os.path.exists(old), "pruning stays in the store")
        self.assertFalse(os.path.exists(os.path.join(os.environ["QARGI_STATE"], "audit.log")))

    def test_an_unknown_token_and_a_malformed_one_are_plan_unknown(self):
        for token in ("0123456789ab", "short", "0123456789AB", "0123456789abc", "../../x", "0123456789ab\n", "%s.json" % self.tok):
            with self.subTest(token=token):
                self.refused(token, "plan-unknown")

    def test_a_record_of_before_the_schema_is_plan_unknown(self):
        self.rewrite({"token": self.tok, "at": "2026-11-22T10:00:00Z", "basis": [{"label": "project", "lines": ["acme"]}]})
        self.refused(self.tok, "plan-unknown")

    def test_a_record_past_its_expiry_is_plan_expired_and_stays(self):
        before = listing()
        rc, out, err = qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-29T10:00:00Z")
        self.assertEqual((rc, out, contract(err)["code"]), (1, "", "plan-expired"))
        self.assertTrue(os.path.exists(self.path))
        self.assertEqual(listing(), before)
        rc, out, err = qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-29T09:59:59Z")
        self.assertEqual(rc, 0, err)
        self.refused(self.tok, "plan-expired", QARGI_PLAN_NOW="2027-01-01T00:00:00Z")

    def test_an_edited_record_is_not_shown(self):
        rec = stored(self.tok)
        rec["lines"][2]["value"] = "0.4.1"
        self.rewrite(rec)
        obj, err = self.refused(self.tok, "plan-record-invalid")
        self.assertIn("problem=hash-mismatch", obj["detail"])
        rec = stored(self.tok)
        rec["lines"][2]["value"] = "0.4.0"
        rec["input_newline"] = False
        self.rewrite(rec)
        self.assertIn("problem=hash-mismatch", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        rec = stored(self.tok)
        rec["input_newline"] = True
        rec["token"] = "ffffffffffff"
        self.rewrite(rec)
        self.assertIn("problem=bad-form", self.refused(self.tok, "plan-record-invalid")[0]["detail"], "a token that is not the file's and the hash's")

    def test_a_record_that_is_malformed_or_of_another_schema_is_not_shown(self):
        base = stored(self.tok)
        cases = {"unknown-schema": dict(base, schema="qargi.plan/1"), "bad-form": dict(base, extra=1)}
        for key in ("verb", "context", "target", "lines", "input_sha256", "input_newline", "created", "expires"):
            cases["missing %s" % key] = {k: v for k, v in base.items() if k != key}
        cases["a verb that is not one"] = dict(base, verb="Release Start")
        cases["context"] = dict(base, context="owner")
        cases["target"] = dict(base, target={"project": "acme"})
        cases["kind"] = dict(base, lines=[dict(x, kind="secret") for x in base["lines"]])
        cases["label"] = dict(base, lines=[dict(x, label="A B") for x in base["lines"]])
        cases["lines"] = dict(base, lines="x")
        cases["time"] = dict(base, expires="tomorrow")
        cases["newline"] = dict(base, input_newline="yes")
        cases["a verb of 81 characters"] = dict(base, verb="a" * 81)
        cases["a label that is too long"] = dict(base, lines=[dict(x, label="a" * 42) for x in base["lines"]])
        cases["a project that is not one"] = dict(base, target={"project": "Acme", "object": "0.4.0"})
        cases["an object with a control character"] = dict(base, target={"project": "acme", "object": "0.4\x01"})
        cases["a context of the wrong type"] = dict(base, context=["lead"])
        for name, rec in cases.items():
            with self.subTest(name):
                self.rewrite(rec)
                self.assertRegex(self.refused(self.tok, "plan-record-invalid")[0]["detail"], r"problem=(bad-form|unknown-schema)$")
        for text in ("not json", "[1]", "", "\xff"):
            with self.subTest(text=text):
                with open(self.path, "wb") as f:
                    f.write(text.encode("latin-1"))
                os.chmod(self.path, 0o600)
                if text == "[1]":
                    self.assertIn("problem=bad-form", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
                else:
                    self.assertIn("problem=bad-json", self.refused(self.tok, "plan-record-invalid")[0]["detail"])

    def test_a_record_that_does_not_live_seven_days_is_not_shown(self):
        # the hash does not cover the times, so the form does: expires is exactly created plus seven days
        for expires in ("2026-11-30T10:00:00Z", "2026-11-28T10:00:00Z", "2026-11-29T10:00:01Z", "2099-01-01T00:00:00Z", "2026-11-22T10:00:00Z"):
            with self.subTest(expires=expires):
                self.rewrite(dict(stored(self.tok), expires=expires))
                self.assertIn("problem=bad-form", self.refused(self.tok, "plan-record-invalid", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0]["detail"])
        self.rewrite(dict(stored(self.tok), created="2026-11-22T10:00:01Z", expires="2026-11-29T10:00:01Z"))
        self.assertEqual(qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0], 0, "a record made at another time is whole")

    def test_the_hash_binds_the_lines_only_so_an_edited_verb_target_or_label_is_still_shown(self):
        # documents a limit of qargi.plan/0: a hand edit that keeps the verb, the target, the labels and the kinds well formed is not detected. The file is the owner's.
        rec = stored(self.tok)
        rec.update(verb="release push", target={"project": "other", "object": "9.9.9"})
        rec["lines"] = [dict(x, label="renamed", kind="ref") for x in rec["lines"]]
        self.rewrite(rec)
        rc, out, err = qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("release push (lead)", out)
        self.assertIn("target: other 9.9.9", out)
        self.assertEqual(json.loads(qargi("plan", "show", self.tok, "--json", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[1])["state"], "valid")

    def test_a_file_of_the_wrong_mode_or_kind_is_not_shown(self):
        os.chmod(self.path, 0o644)
        self.assertIn("problem=wrong-mode", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.chmod(self.path, 0o640)
        self.assertIn("problem=wrong-mode", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.chmod(self.path, 0o600)
        os.link(self.path, self.path + ".again")
        self.assertIn("problem=links", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.unlink(self.path + ".again")
        self.assertEqual(qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0], 0)

    def test_a_link_in_place_of_the_file_or_the_directory_is_not_followed(self):
        saved = os.path.join(os.environ["QARGI_STATE"], "saved.json")
        os.rename(self.path, saved)
        os.symlink(saved, self.path)
        self.assertIn("problem=link", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.unlink(self.path)
        os.rename(saved, self.path)
        moved = os.path.join(os.environ["QARGI_STATE"], "plans.real")
        os.rename(plans_dir(), moved)
        os.symlink(moved, plans_dir())
        self.assertIn("problem=bad-directory", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.unlink(plans_dir())
        os.rename(moved, plans_dir())
        self.assertEqual(qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0], 0)

    def test_a_directory_a_pipe_or_a_missing_plans_directory_is_no_record(self):
        os.unlink(self.path)
        os.mkdir(self.path)
        self.assertIn("problem=not-a-file", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.rmdir(self.path)
        os.mkfifo(self.path, 0o600)
        self.assertIn("problem=not-a-file", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        os.unlink(self.path)
        self.refused(self.tok, "plan-unknown")
        os.rmdir(plans_dir())
        self.refused(self.tok, "plan-unknown")

    def test_a_record_that_is_too_large_is_not_shown(self):
        with open(self.path, "w") as f:
            f.write('{"pad":"%s"}' % ("x" * (R.PLAN_MAX + 1)))
        self.assertIn("problem=too-large", self.refused(self.tok, "plan-record-invalid")[0]["detail"])

    def test_the_command_is_reached_through_bin_qargi(self):
        rc, out, err = qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("release start", out)

    def test_a_record_nested_deeper_than_the_parser_goes_is_bad_json_and_not_a_traceback(self):
        for text in ("[" * 100000, '{"a":' * 100000 + "1"):
            with self.subTest(text=text[:6]):
                with open(self.path, "w") as f:
                    f.write(text)
                os.chmod(self.path, 0o600)
                obj, err = self.refused(self.tok, "plan-record-invalid")
                self.assertIn("problem=bad-json", obj["detail"])
                self.assertNotIn("Traceback", err)

    @unittest.skipIf(os.geteuid() == 0, "root opens a file of mode 000")
    def test_a_file_or_a_directory_that_cannot_be_opened_is_unreadable_and_not_a_link(self):
        os.chmod(self.path, 0)
        obj, err = self.refused(self.tok, "plan-record-invalid")
        self.assertIn("problem=unreadable", obj["detail"])
        self.assertNotIn("problem=link", err)
        os.chmod(self.path, 0o600)
        os.chmod(plans_dir(), 0)
        try:
            self.assertIn("problem=unreadable", self.refused(self.tok, "plan-record-invalid")[0]["detail"])
        finally:
            os.chmod(plans_dir(), 0o700)
        self.assertEqual(qargi("plan", "show", self.tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")[0], 0)

    def test_the_text_prints_a_control_character_of_a_value_as_xnn(self):
        lines = ["acme", "release", "0.4.0", "bad\x1b[31mred\x07\x7f\x85\ttab\rcr", "plain \\x41 café ✓"]
        rec = stored(self.tok)
        rec.update(lines=[dict(label="v", kind="name", value=v) for v in lines], input_newline=True)
        rec["input_sha256"] = hashlib.sha256(rebuild(rec).encode()).hexdigest()
        rec["token"] = tok = rec["input_sha256"][:12]
        self.path = os.path.join(plans_dir(), tok + ".json")
        self.rewrite(rec)
        rc, out, err = qargi("plan", "show", tok, QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("  v  bad\\x1b[31mred\\x07\\x7f\\x85\\x09tab\\x0dcr\n", out)
        self.assertIn("  v  plain \\x41 café ✓\n", out, "a backslash and other characters are printed as they are")
        self.assertNotRegex(out.replace("\n", ""), r"[\x00-\x1f\x7f-\x9f]")
        rc, out, err = qargi("plan", "show", tok, "--json", QARGI_PLAN_NOW="2026-11-23T10:00:00Z")
        self.assertEqual(json.loads(out)["lines"][3]["value"], lines[3], "--json is the record as stored")

    def test_the_record_is_exactly_mode_600_whatever_a_leftover_temporary_file_had(self):
        tok = hashlib.sha256(b"a\nb\n").hexdigest()[:12]
        tmp = os.path.join(plans_dir(), tok + ".json.tmp.4242")
        with open(tmp, "w") as f:
            f.write("old")
        os.chmod(tmp, 0o666)
        old = os.umask(0)
        try:
            with mock.patch("os.getpid", return_value=4242):
                R.basis_store(tok, [("x", "name"), ("y", "name")], "a\nb\n", verb="release start", target=("acme", "0.4.0"), state=self.state)
        finally:
            os.umask(old)
        self.assertEqual(os.stat(os.path.join(plans_dir(), tok + ".json")).st_mode & 0o777, 0o600)

    def test_the_arguments_are_checked_before_the_state_is_read(self):
        for args in ((), ("show",), ("show", self.tok, "extra"), ("show", "--bad"), ("list",)):
            with self.subTest(args=args):
                rc, out, err = qargi("plan", *args)
                self.assertEqual((rc, out), (2, ""), err)

    def test_the_refusals_are_in_the_catalogue_as_live_plan_codes(self):
        codes = R.load(ROOT)["codes"]
        for code in ("plan-unknown", "plan-expired", "plan-record-invalid"):
            self.assertEqual((codes[code]["class"], codes[code]["exit"], codes[code]["status"]), ("plan", 1, "live"))


if __name__ == "__main__":
    unittest.main()
