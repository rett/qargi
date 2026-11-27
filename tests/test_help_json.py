#!/usr/bin/env python3
"""`qargi help json [KIND] [--json]` (lib/help.py) against the registry files of lib/kinds/: the list names every kind with its schema, one
kind prints every field path with its type, required or optional and its sentence, --json prints the registry file byte for byte, and an
unknown kind or option exits 2 with a plain line. lib/help.py is called directly (the verb is not in the command table yet, so
tests/test_help.py does not know it); bin/qargi is called once for the route. Offline; no repository state.
Run: python3 tests/test_help_json.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import glob, json, os, re, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "lib")
KINDS = os.path.join(LIB, "kinds")
BIN = os.path.join(ROOT, "bin", "qargi")
HELP = [sys.executable, "-B", "-I", os.path.join(LIB, "help.py"), "show", "json"]


def run(cmd, *args):
    p = subprocess.run(list(cmd) + list(args), capture_output=True)
    return p.returncode, p.stdout, p.stderr


def kind_files():
    return sorted(glob.glob(os.path.join(KINDS, "*.json")))


def registry(path):
    with open(path, "rb") as f:
        return json.loads(f.read())


def expected_fields(shape, defs, prefix=""):
    """{path: required} for every field of a shape, written apart from lib/help.py: refs are followed, arrays add [], maps add .*"""
    out = {}
    stack = [(shape, prefix, ())]
    while stack:
        node, path, seen = stack.pop()
        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[1]
            if name not in seen:
                stack.append((defs[name], path, seen + (name,)))
            continue
        for key, sub in (node.get("properties") or {}).items():
            p = path + "." + key if path else key
            out[p] = key in (node.get("required") or [])
            stack.append((sub, p, seen))
        if isinstance(node.get("items"), dict):
            stack.append((node["items"], path + "[]", seen))
        if isinstance(node.get("additionalProperties"), dict):
            stack.append((node["additionalProperties"], path + ".*", seen))
    return out


def rows(text):
    """{path: (type text, 'required'|'optional')} from the field table of `help json KIND`"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^  (\S+)  (.+), (required|optional)$", line)
        if m:
            out[m.group(1)] = (m.group(2), m.group(3))
    return out


class List(unittest.TestCase):
    def test_every_kind_is_listed_with_its_schema_and_a_line(self):
        rc, out, err = run(HELP)
        self.assertEqual((rc, err), (0, b""))
        text = out.decode()
        files = kind_files()
        self.assertTrue(files)
        flat = re.sub(r"\s+", " ", text)
        for path in files:
            reg = registry(path)
            self.assertEqual(os.path.basename(path), reg["kind"] + ".json")
            self.assertRegex(text, r"(?m)^  %s +\(schema %d, %s\) " % (re.escape(reg["kind"]), reg["schema"], reg["status"]))
            first = re.sub(r"\s+", " ", reg["about"]).split(". ")[0].rstrip(".")
            self.assertIn(first, flat, "the first sentence of the about of %s" % reg["kind"])

    def test_the_rule_is_stated_and_the_list_names_nothing_else(self):
        rc, out, err = run(HELP)
        text = out.decode()
        self.assertIn("`kind`", text)
        self.assertIn("`schema`", text)
        listed = set(re.findall(r"(?m)^  (qargi-[a-z0-9-]+) +\(schema", text))
        self.assertEqual(listed, {registry(p)["kind"] for p in kind_files()})

    def test_no_colour_sequence_when_the_output_is_not_a_terminal(self):
        self.assertNotIn(b"\x1b", run(HELP)[1])
        self.assertNotIn(b"\x1b", run(HELP, "qargi-handoff")[1])


class Kind(unittest.TestCase):
    def test_every_field_path_is_printed_with_type_and_required(self):
        for path in kind_files():
            reg = registry(path)
            with self.subTest(kind=reg["kind"]):
                rc, out, err = run(HELP, reg["kind"])
                self.assertEqual((rc, err), (0, b""))
                text = out.decode()
                want = expected_fields(reg["document"], reg["document"].get("$defs") or {})
                got = rows(text)
                self.assertEqual(set(got), set(want))
                for p, req in want.items():
                    self.assertEqual(got[p][1], "required" if req else "optional", p)
                self.assertTrue(all(t for t, _ in got.values()))
                self.assertIn("schema %d" % reg["schema"], text.splitlines()[0])
                self.assertIn(reg["kind"], text.splitlines()[0])

    def test_the_sentence_of_a_field_follows_its_row(self):
        rc, out, err = run(HELP, "qargi-marshal-check")
        lines = out.decode().splitlines()
        i = lines.index(next(l for l in lines if l.startswith("  remote  ")))
        self.assertEqual(lines[i], "  remote  enum checked|unchecked|not-asked|none, required")
        self.assertIn("Whether the answer was checked against the remote", lines[i + 1])
        self.assertTrue(lines[i + 1].startswith("      "))

    def test_types_nested_paths_and_optional_fields(self):
        rc, out, err = run(HELP, "qargi-marshal-check")
        got = rows(out.decode())
        self.assertEqual(got["feature"], ("string|null", "required"))
        self.assertEqual(got["schema"][1], "required")
        self.assertEqual(got["lead.worktree"], ("string", "optional"))
        self.assertEqual(got["warnings"], ("array of object", "required"))
        self.assertEqual(got["features"], ("array of object", "optional"))

    def test_the_header_names_the_verbs_and_what_the_verb_writes(self):
        reg = registry(os.path.join(KINDS, "qargi-handoff.json"))
        text = re.sub(r"\s+", " ", run(HELP, "qargi-handoff")[1].decode())
        self.assertIn("qargi marshal handoff --json", text)
        self.assertIn(re.sub(r"\s+", " ", reg["writes"]), text)


class Bytes(unittest.TestCase):
    def test_json_is_the_file_byte_for_byte(self):
        for path in kind_files():
            reg = registry(path)
            with self.subTest(kind=reg["kind"]):
                rc, out, err = run(HELP, reg["kind"], "--json")
                self.assertEqual((rc, err), (0, b""))
                with open(path, "rb") as f:
                    self.assertEqual(out, f.read())
                rc, out2, err = run(HELP, "--json", reg["kind"])
                self.assertEqual((rc, out2), (0, out))

    def test_bin_qargi_reaches_the_verb(self):
        with open(os.path.join(KINDS, "qargi-handoff.json"), "rb") as f:
            want = f.read()
        rc, out, err = run([BIN], "help", "json", "qargi-handoff", "--json")
        self.assertEqual((rc, out, err), (0, want, b""))
        rc, out, err = run([BIN], "help", "json")
        self.assertEqual(rc, 0)
        self.assertIn(b"qargi-handoff", out)
        rc, out, err = run([BIN], "help", "json", "qargi-nonesuch")
        self.assertEqual((rc, out), (2, b""))


class Refused(unittest.TestCase):
    def one_line(self, rc, out, err, *words):
        self.assertEqual((rc, out), (2, b""))
        text = err.decode()
        self.assertEqual(text.count("\n"), 1, text)
        self.assertTrue(text.startswith("qargi: "), text)
        self.assertNotIn("Traceback", text)
        for w in words:
            self.assertIn(w, text)

    def test_an_unknown_kind_exits_2(self):
        self.one_line(*run(HELP, "qargi-nonesuch"), "qargi-nonesuch", "qargi help json")
        self.one_line(*run(HELP, "qargi-nonesuch", "--json"), "qargi-nonesuch")

    def test_a_name_that_is_a_path_is_an_unknown_kind(self):
        self.one_line(*run(HELP, "../kinds/qargi-handoff"), "no JSON kind")
        self.one_line(*run(HELP, "qargi-handoff.json"), "no JSON kind")

    def test_more_than_one_kind_and_a_bare_json_exit_2(self):
        self.one_line(*run(HELP, "qargi-handoff", "qargi-refusal"), "one kind")
        self.one_line(*run(HELP, "--json"), "KIND")

    def test_an_option_it_does_not_have_exits_2(self):
        self.one_line(*run(HELP, "qargi-handoff", "--yaml"), "--yaml")


if __name__ == "__main__":
    unittest.main()
