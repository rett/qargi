#!/usr/bin/env python3
"""The render engine, lib/render.py: qargi's emitters and parse-back readers for five formats, the declarative `map`
renderer and the `command` renderer. Hermetic: every file is made in a temporary directory.
Run: python3 tests/test_render.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, random, shutil, subprocess, sys, tempfile, time, tomllib, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
LIB = os.path.join(HERE, "..", "lib")
sys.path.insert(0, LIB)
import render as R  # noqa: E402

SAMPLE = {
    "name": "builder",
    "description": "Builds things: carefully",
    "count": 3,
    "enabled": True,
    "ratio_text": "1.5",
    "tools": ["Bash", "Read"],
    "empty_list": [],
    "empty_map": {},
    "hooks": {"pre": [{"matcher": "Bash|Edit", "run": "x --y", "timeout": 20}]},
    "prompt": "line one\nline two\n",
    "none_text": "null",
}


class Goldens(unittest.TestCase):
    """The exact bytes of each format. A change here is a change of every stored render: it makes them STALE."""

    def test_yaml(self):
        self.assertEqual(R.emit_yaml(SAMPLE), """\
name: builder
description: "Builds things: carefully"
count: 3
enabled: true
ratio_text: "1.5"
tools:
  - Bash
  - Read
empty_list: []
empty_map: {}
hooks:
  pre:
    - matcher: "Bash|Edit"
      run: x --y
      timeout: 20
prompt: |
  line one
  line two
none_text: "null"
""")

    def test_json(self):
        self.assertEqual(R.emit_json(SAMPLE), """\
{
  "name": "builder",
  "description": "Builds things: carefully",
  "count": 3,
  "enabled": true,
  "ratio_text": "1.5",
  "tools": [
    "Bash",
    "Read"
  ],
  "empty_list": [],
  "empty_map": {},
  "hooks": {
    "pre": [
      {
        "matcher": "Bash|Edit",
        "run": "x --y",
        "timeout": 20
      }
    ]
  },
  "prompt": "line one\\nline two\\n",
  "none_text": "null"
}
""")

    def test_toml(self):
        self.assertEqual(R.emit_toml(SAMPLE), '''\
name = "builder"
description = "Builds things: carefully"
count = 3
enabled = true
ratio_text = "1.5"
tools = ["Bash", "Read"]
empty_list = []
prompt = """
line one
line two
"""
none_text = "null"

[empty_map]

[[hooks.pre]]
matcher = "Bash|Edit"
run = "x --y"
timeout = 20
''')

    def test_markdown_with_front_matter(self):
        meta = {"name": "builder", "description": "Builds things: carefully", "tools": ["Bash", "Read"]}
        self.assertEqual(R.emit_markdown(meta, "You build.\n\nSecond paragraph.\n\n\n"), """\
---
name: builder
description: "Builds things: carefully"
tools:
  - Bash
  - Read
---

You build.

Second paragraph.
""")

    def test_markdown_without_a_body_or_without_meta(self):
        self.assertEqual(R.emit_markdown({"a": 1}, None), "---\na: 1\n---\n")
        self.assertEqual(R.emit_markdown({"a": 1}, "\n\n"), "---\na: 1\n---\n")
        self.assertEqual(R.emit_markdown({}, "Body\n"), "---\n---\n\nBody\n")

    def test_text(self):
        self.assertEqual(R.emit_text("one\n\ntwo\n\n\n"), "one\n\ntwo\n")

    def test_every_format_ends_in_exactly_one_newline_and_has_no_cr(self):
        for fmt in ("json", "yaml", "toml"):
            out = R.emit(fmt, SAMPLE)
            self.assertTrue(out.endswith("\n") and not out.endswith("\n\n"), fmt)
            self.assertNotIn("\r", out)

    def test_key_order_is_the_order_of_the_map(self):
        a = {"b": 1, "a": 2}
        self.assertEqual(R.emit_yaml(a), "b: 1\na: 2\n")
        self.assertEqual(R.emit_toml(a), "b = 1\na = 2\n")
        self.assertEqual(list(json.loads(R.emit_json(a))), ["b", "a"])

    def test_toml_puts_scalars_before_tables(self):
        d = {"t": {"x": 1}, "s": "v"}
        self.assertEqual(R.emit_toml(d), 's = "v"\n\n[t]\nx = 1\n')

    def test_toml_dotted_and_quoted_table_names(self):
        d = {"a": {"b c": {"d": 1}, "e": {"f": [1, 2]}}}
        out = R.emit_toml(d)
        self.assertEqual(tomllib.loads(out), d)
        self.assertIn('["b c"]', out.replace("a.", ""))


# strings that have to survive every format as the very same string
CORPUS = [
    "", " ", "  leading", "trailing  ", " both ", "a: b", "a:b", "key: value: more", ":", "- item", "-", "# comment", "a #b", "a#b",
    "#", "'single'", '"double"', 'say "hi"', "it's", "back\\slash", "C:\\dir\\file", "\\", "\\n", "tab\there", "line\nbreak",
    "two\n\nlines", "\nleading newline", "trailing newline\n", "\n", "\n\n", "a\r\nb", "cr\rhere", "x\x00y", "bell\x07", "del\x7f",
    "uni\u00e9", "\u00fcber", "\u65e5\u672c\u8a9e", "emoji \U0001F600 here", "\U0001F600", "nel\x85x", "ls\u2028ps\u2029", "bom\ufeffx",
    '"""', 'a"""b', '""""', '"""""', 'ends with quote"', '"starts', "'''", "a'''b", "true", "false", "True", "NO", "yes", "off", "On", "y", "n",
    "null", "Null", "~", "123", "-5", "+5", "007", "0x1f", "0o17", "1e3", "1.5", ".5", ".inf", ".nan", "1_000", "12:30", "2026-11-02",
    "2026-11-02T10:00:00Z", "=", "<<", "!tag", "&anchor", "*alias", "|", ">", "|-", "[a, b]", "{a: b}", "a, b", "%d", "@at", "`tick`",
    "?", "? x", "- - -", "---", "...", "a\n---\nb", "---\nname: x\n---", "{{x}}", "{x}", "$HOME", "a|b", "Bash|Edit", "path/to/file.md",
    "/abs/path", "./rel", "x --y", "line one\nline two\n", "  indented\nline", "line\n  indented", "trailing space \nnext", "a\n \nb",
    "# not a comment\nreally", "key: v\nother: w", "\ttab first", "\u00a0nbsp", "x" * 300, "word " * 80, "a\nb\nc\n\n",
]


def roundtrip(fmt, data, body=None):
    content = R.emit(fmt, data, body)
    R.check_roundtrip(fmt, content, data, body)
    return content


class Corpus(unittest.TestCase):
    def values(self, s):
        return {"v": s, "list": [s, s], "nested": {"inner": {"v": s}}, "items": [{"k": s, "other": 1}], s: "key"}

    def test_every_string_comes_back_in_every_format(self):
        for fmt in ("json", "yaml", "toml"):
            for s in CORPUS:
                with self.subTest(fmt=fmt, s=s):
                    data = self.values(s)
                    content = roundtrip(fmt, data)
                    parsed = R.parse(fmt, content)
                    self.assertEqual(parsed, data)
                    self.assertIs(type(parsed["v"]), str)

    def test_every_string_comes_back_as_markdown_meta_and_body(self):
        for s in CORPUS:
            if "\r" in s or "\x00" in s or "\x07" in s or "\x7f" in s:
                continue  # a body takes no control characters (see the refusals)
            with self.subTest(s=s):
                content = roundtrip("markdown-frontmatter", {"v": s, "list": [s]}, s)
                meta, body = R.split_markdown(content)
                self.assertEqual(meta, {"v": s, "list": [s]})
                self.assertEqual(body, R.normalize_body(s))

    def test_a_string_that_looks_like_something_else_stays_a_string_in_yaml(self):
        words = ("true", "null", "123", "1.5", "2026-11-02", "yes", "~")
        out = R.emit_yaml({"k%d" % i: w for i, w in enumerate(words)})
        self.assertEqual(out.splitlines(), ['k%d: "%s"' % (i, w) for i, w in enumerate(words)])
        self.assertEqual(R.emit_yaml({"yes": 1, "1": 2}), '"yes": 1\n"1": 2\n')

    def test_plain_words_stay_plain_in_yaml(self):
        self.assertEqual(R.emit_yaml({"a": "Bash, Read, Edit", "b": "x --y", "c": "path/to/file.md", "d": "A_b-c"}),
                         "a: Bash, Read, Edit\nb: x --y\nc: path/to/file.md\nd: A_b-c\n")

    def test_booleans_numbers_none_keep_their_type(self):
        data = {"t": True, "f": False, "i": 0, "n": -7, "big": 2 ** 62, "s": "0"}
        for fmt in ("json", "yaml"):
            got = R.parse(fmt, roundtrip(fmt, dict(data, none=None)))
            self.assertIs(got["t"], True)
            self.assertIs(got["f"], False)
            self.assertIs(type(got["i"]), int)
            self.assertEqual((got["i"], got["n"], got["big"], got["s"]), (0, -7, 2 ** 62, "0"))
            self.assertIsNone(got["none"])
        got = tomllib.loads(roundtrip("toml", data))
        self.assertEqual((got["t"], got["f"], got["i"], got["n"], got["s"]), (True, False, 0, -7, "0"))


class Random(unittest.TestCase):
    """Property-style: generated strings, emit then parse back, equal."""

    ALPHABET = list("ab Z09_-./") + [": ", " #", "#", "\"", "'", "\\", "\n", "\t", "\r", "\x00", "\x1f", "\x7f", "\x85", "\u2028", "\ufeff",
                                     "\u00e9", "\u65e5", "\U0001F600", "\"\"\"", "- ", "--- ", ": ", "|", ">", "[", "]", "{", "}", ",", "%", "@", "`", "!", "&", "*", "?"]

    def strings(self, seed, n):
        rng = random.Random(seed)
        out = []
        for _ in range(n):
            out.append("".join(rng.choice(self.ALPHABET) for _ in range(rng.randint(0, 14))))
        return out

    def test_emit_then_parse_is_equal(self):
        strs = self.strings(20261102, 3000)
        for i in range(0, len(strs) - 3, 3):
            a, b, c = strs[i:i + 3]
            data = {a: [b, c], "k": b, "n": {c: [a, b]}, "t": [{c: a}, {b: [c]}]}
            for fmt in ("json", "yaml", "toml"):
                try:
                    content = R.emit(fmt, data)
                except R.RenderError as e:
                    self.fail("%s refused %r: %s" % (fmt, data, e))
                self.assertEqual(R.parse(fmt, content), data, "%s %r" % (fmt, data))
                R.check_roundtrip(fmt, content, data)

    def test_random_markdown_bodies(self):
        for s in self.strings(7, 800):
            if any(c in s for c in "\r\x00\x1f\x7f\x85"):
                continue
            body = s
            content = roundtrip("markdown-frontmatter", {"t": s}, body)
            self.assertEqual(R.split_markdown(content), ({"t": s}, R.normalize_body(body)))


class Refusals(unittest.TestCase):
    def refuses(self, fn, *args, match=""):
        with self.assertRaisesRegex(R.RenderError, match):
            fn(*args)

    def test_unrepresentable_values(self):
        self.refuses(R.emit_toml, {"a": None}, match="null")
        self.refuses(R.emit_toml, {"a": 1.5}, match="float")
        self.refuses(R.emit_yaml, {"a": 1.5}, match="float")
        self.refuses(R.emit_json, {"a": float("nan")}, match="finite")
        self.refuses(R.emit_json, {"a": {1, 2}}, match="set")
        self.refuses(R.emit_json, {1: "x"}, match="key")
        self.refuses(R.emit_yaml, {"a": 2 ** 70}, match="range")
        self.refuses(R.emit_yaml, {"a": "\ud800"}, match="Unicode")
        self.refuses(R.emit_toml, {"a": [{"x": 1}, 2]}, match="mix")
        self.refuses(R.emit_toml, {"a": [[{"x": 1}]]}, match="table")
        self.refuses(R.emit_toml, ["a"], match="table")
        self.refuses(R.emit_yaml, ["a"], match="mapping")
        self.refuses(R.emit_yaml, {"a": (1, 2)}, match="tuple")

    def test_too_deep(self):
        d = cur = {}
        for _ in range(R.MAX_DEPTH + 2):
            cur["n"] = {}
            cur = cur["n"]
        for fmt in ("json", "yaml", "toml"):
            self.refuses(R.emit, fmt, d, match="deep")

    def test_text_and_body_take_no_control_characters(self):
        for bad in ("a\x00b", "a\rb", "a\x07b", "a\x7fb", "a\ud800b"):
            self.refuses(R.emit_text, bad)
            self.refuses(R.emit_markdown, {}, bad)
        self.refuses(R.emit_text, "\n\n", match="empty")
        self.assertEqual(R.emit_text("a\tb"), "a\tb\n")

    def test_output_over_the_limit(self):
        self.refuses(R.emit_text, "x" * R.MAX_BYTES, match="larger")
        self.refuses(R.emit_json, {"a": "x" * R.MAX_BYTES}, match="larger")

    def test_unknown_format(self):
        self.refuses(R.emit, "xml", {}, match="format")
        self.refuses(R.parse, "xml", "", match="format")


class YamlReader(unittest.TestCase):
    """The reader reads what the emitter writes, nothing else, and says so."""

    def rejects(self, text, match=""):
        with self.assertRaisesRegex(R.RenderError, match):
            R.parse_yaml(text)

    def test_what_the_emitter_wrote(self):
        self.assertEqual(R.parse_yaml(R.emit_yaml(SAMPLE)), SAMPLE)

    def test_everything_else_is_refused(self):
        for text in [
            "", "a: 1", "a: 1\n\n", "\na: 1\n", "a: 1\r\n", "a: 1 # c\n", "# c\na: 1\n", "a: 'x'\n", "a: [1, 2]\n", "a: {b: 1}\n",
            "a: &x 1\n", "a: *x\n", "a: !!str 1\n", "a: >\n  x\n", "a: |+\n  x\n\n", "a: |2\n   x\n", "a: 1.5\n", "a: 007\n", "a: +1\n",
            "a: 0x10\n", "a: yes\n", "a: ~\n", "a: Null\n", "a: 2026-11-02\n", "a: x: y\n", "a:b\n", "a:  1\n", "a: 1\na: 2\n",
            "a: 1\n b: 2\n", "a:\n    b: 1\n", "a:\n  - 1\n - 2\n", "a:\n-\n", "a:\n", "- 1\na: 2\n", "a: 1\n- 2\n", "a: \"x\n", "a: \"x\\q\"\n",
            "a: \"x\\x41\"\n", "a: \"\\ud800\"\n", "a: \"x\" y\n", "a: \"tab\there\"\n", "a:\t1\n", "\ta: 1\n", "a: x\ty\n", "a: \"\\u00zz\"\n",
            "a: |\n  x\n\n", "a: |\n   x\n", "a: |\n x\n", "no: 1\n", "a: 99999999999999999999\n", "a: |\n", "a: ?\n", "? a\n", "a: x #y\n",
            "- a\n- b: 1\n  c\n", "a: -\n", "a: [] x\n",
        ]:
            with self.subTest(text=text):
                self.rejects(text)

    def test_the_message_names_the_line(self):
        self.rejects("a: 1\nb: 'x'\n", match="line 2")

    def test_top_level_flow_collections_of_nothing(self):
        self.assertEqual(R.parse_yaml("{}\n"), {})
        self.assertEqual(R.parse_yaml("[]\n"), [])

    def test_non_canonical_but_parseable_is_caught_by_the_roundtrip_check(self):
        # the reader accepts this (a valid subset text) but the emitter would never write the quotes: the check says so
        content = 'a: "x"\n'
        self.assertEqual(R.parse_yaml(content), {"a": "x"})
        with self.assertRaisesRegex(R.RenderError, "canonical"):
            R.check_roundtrip("yaml", content, {"a": "x"})

    def test_a_value_that_does_not_parse_back_to_the_same_value_is_an_error(self):
        with self.assertRaisesRegex(R.RenderError, "differs"):
            R.check_roundtrip("yaml", "a: 1\n", {"a": "1"})
        with self.assertRaisesRegex(R.RenderError, "differs"):
            R.check_roundtrip("json", '{"a": true}', {"a": 1})
        with self.assertRaisesRegex(R.RenderError, "differs"):
            R.check_roundtrip("toml", "a = 1\n", {"a": True})


class Markdown(unittest.TestCase):
    def test_split(self):
        self.assertEqual(R.split_markdown("---\na: 1\n---\n"), ({"a": 1}, None))
        self.assertEqual(R.split_markdown("---\n---\n\nBody\n"), ({}, "Body\n"))
        self.assertEqual(R.split_markdown("---\na: 1\n---\n\n\nlead\n"), ({"a": 1}, "\nlead\n"))

    def test_malformed(self):
        for text in ["", "a: 1\n", "---\na: 1\n", "---\na: 1\n---", "---\na: 1\n---\nno blank\n", "---\na: 1\n---\n\n", "---\na: 1\n---\n\nx\n\n",
                     "---\na: 1\n---\n\nx", "---\r\na: 1\r\n---\r\n", "---\n- 1\n---\n"]:
            with self.subTest(text=text):
                with self.assertRaises(R.RenderError):
                    R.split_markdown(text)


# ---------------------------------------------------------------- the map renderer

DEF = {
    "name": "build-1",
    "abilities": ["build", "test"],
    "class": "write",
    "tier": "balanced",
    "effort": "high",
    "tools": ["bash", "read", "edit"],
    "barrier": {"guard_command": "qargi __guard --provider p"},
    "body": "You are a member.\n\nWork.\n",
}
TOOL_MAP = {"bash": "Bash", "read": "Read", "edit": "Edit", "monitor": "Monitor"}
FIELDS = [
    {"from": "name", "to": "name", "refuse_if_missing": True},
    {"value": "A member (roles: {abilities}): one task at a time", "to": "description"},
    {"from": "tier", "to": "model", "resolve": "model", "refuse_if_missing": True},
    {"from": "effort", "to": "effort", "resolve": "effort"},
    {"from": "tools", "to": "tools", "tool_map": TOOL_MAP, "transform": [{"join": ", "}], "guarantee_for": ["read-only"]},
    {"value": {"PreToolUse": [{"matcher": "Bash|Edit", "hooks": [{"type": "command", "command": "{barrier.guard_command}", "timeout": 20}]}]},
     "to": "hooks"},
]
TABLES = {"model": {"balanced": "m-bal", "deep": "m-deep"}, "effort": {"high": "hi"}}


def resolver(kind, value, definition):
    return TABLES[kind].get(value)


def spec(**kw):
    s = {"engine": "map", "format": "markdown-frontmatter", "path": "{name}.md", "fields": FIELDS}
    s.update(kw)
    return s


def defn(**kw):
    d = json.loads(json.dumps(DEF))
    d.update(kw)
    return {k: v for k, v in d.items() if v is not None}


GOLDEN_MD = """\
---
name: build-1
description: "A member (roles: build, test): one task at a time"
model: m-bal
effort: hi
tools: Bash, Read, Edit
hooks:
  PreToolUse:
    - matcher: "Bash|Edit"
      hooks:
        - type: command
          command: qargi __guard --provider p
          timeout: 20
---

You are a member.

Work.
"""


class MapRenderer(unittest.TestCase):
    def render(self, d=None, s=None, **kw):
        return R.render_map(defn() if d is None else d, spec() if s is None else s, resolver=kw.pop("resolver", resolver), **kw)

    def refuses(self, match, d=None, s=None, **kw):
        with self.assertRaisesRegex(R.RenderError, match):
            self.render(d, s, **kw)

    def test_markdown_golden_and_result_shape(self):
        r = self.render()
        self.assertEqual(r["content"], GOLDEN_MD)
        self.assertEqual(r["path"], "build-1.md")
        self.assertEqual(r["sha256"], hashlib.sha256(GOLDEN_MD.encode()).hexdigest())
        self.assertRegex(r["inputs_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(r["notes"], [])
        self.assertEqual(sorted(r), ["content", "inputs_hash", "notes", "path", "sha256"])

    def test_the_same_fields_as_yaml_toml_json(self):
        flat = [f for f in FIELDS if f["to"] != "hooks"]
        yaml_ = self.render(s=spec(format="yaml", fields=flat, path="agents/{name}.yaml", body=None))
        self.assertEqual(yaml_["content"], 'name: build-1\ndescription: "A member (roles: build, test): one task at a time"\n'
                                           'model: m-bal\neffort: hi\ntools: Bash, Read, Edit\n')
        self.assertEqual(yaml_["path"], "agents/build-1.yaml")
        toml_ = self.render(s=spec(format="toml", fields=flat, path="{name}.toml", body=None))
        self.assertEqual(toml_["content"], 'name = "build-1"\ndescription = "A member (roles: build, test): one task at a time"\n'
                                           'model = "m-bal"\neffort = "hi"\ntools = "Bash, Read, Edit"\n')
        json_ = self.render(s=spec(format="json", fields=flat, path="{name}.json", body=None))
        self.assertEqual(json.loads(json_["content"]), json.loads(json.dumps({
            "name": "build-1", "description": "A member (roles: build, test): one task at a time", "model": "m-bal", "effort": "hi", "tools": "Bash, Read, Edit"})))

    def test_a_tools_list_stays_a_list_without_join_and_nested_values_are_typed(self):
        fields = [{"from": "tools", "to": "tools", "tool_map": TOOL_MAP}, {"value": {"a": {"b": ["{name}", "x"], "n": 3, "t": True}}, "to": "obj"}]
        r = self.render(s=spec(format="toml", fields=fields, path="{name}.toml", body=None))
        self.assertEqual(tomllib.loads(r["content"]), {"tools": ["Bash", "Read", "Edit"], "obj": {"a": {"b": ["build-1", "x"], "n": 3, "t": True}}})

    def test_text_format(self):
        s = spec(format="text", path="{name}.txt", fields=FIELDS[:3], template="agent {name} on {model} ({description})\n\n{body}")
        r = self.render(s=s)
        self.assertEqual(r["content"], "agent build-1 on m-bal (A member (roles: build, test): one task at a time)\n\nYou are a member.\n\nWork.\n")
        s["template"] = "{missing}"
        self.refuses("missing", s=s)
        s["template"] = "{{literal}} {name}"
        self.assertEqual(self.render(s=s)["content"], "{literal} build-1\n")

    def test_the_body_may_come_from_elsewhere_or_be_absent(self):
        r = self.render(d=defn(prompt="Other.\n"), s=spec(body="prompt"))
        self.assertTrue(r["content"].endswith("---\n\nOther.\n"))
        r = self.render(s=spec(body=None))
        self.assertTrue(r["content"].endswith("---\n"))
        self.refuses("body", d=defn(body=None), s=spec(body_required=True))
        self.refuses("body", s=spec(format="json", body="body"))

    def test_deterministic_for_the_same_input_and_for_any_insertion_order(self):
        a = self.render()
        self.assertEqual(a, self.render())
        d = defn()
        reordered = {k: d[k] for k in reversed(list(d))}
        reordered["barrier"] = dict(reversed(list(d["barrier"].items())))
        b = self.render(d=reordered)
        self.assertEqual(a, b)
        self.assertEqual(a["content"].splitlines()[1], "name: build-1")

    def test_the_order_of_the_file_is_the_order_of_the_field_table(self):
        fields = list(reversed(FIELDS[:4]))
        r = self.render(s=spec(fields=fields, body=None))
        keys = [line.split(":")[0] for line in r["content"].splitlines()[1:-1]]
        self.assertEqual(keys, ["effort", "model", "description", "name"])

    def test_inputs_hash_follows_the_inputs_and_only_them(self):
        base = self.render()["inputs_hash"]
        self.assertNotEqual(base, self.render(d=defn(description="x"))["inputs_hash"])
        self.assertNotEqual(base, self.render(d=defn(body="Other.\n"))["inputs_hash"])
        self.assertNotEqual(base, self.render(s=spec(path="x-{name}.md"))["inputs_hash"])
        self.assertNotEqual(base, self.render(extra={"catalog": "abc"})["inputs_hash"])
        self.assertEqual(self.render(extra={"catalog": "abc"})["inputs_hash"], self.render(extra={"catalog": "abc"})["inputs_hash"])
        changed = lambda kind, value, d: "other-model" if kind == "model" else TABLES[kind].get(value)  # noqa: E731
        self.assertNotEqual(base, self.render(resolver=changed)["inputs_hash"])      # a catalog change makes the render STALE
        self.assertEqual(base, self.render(resolver=lambda k, v, d: TABLES[k].get(v))["inputs_hash"])

    def test_the_resolver_may_be_tables_in_the_spec(self):
        r = R.render_map(defn(), spec(resolve=TABLES))
        self.assertEqual(r["content"], GOLDEN_MD)
        with self.assertRaisesRegex(R.RenderError, "resolver"):
            R.render_map(defn(), spec())

    def test_required_fields(self):
        d = defn()
        del d["name"]
        self.refuses("name", d=d)
        self.refuses("name", d=defn(name=""))
        self.refuses("model", d=defn(tier=None))
        fields = [dict(f, default="fallback") if f["to"] == "name" else f for f in FIELDS]
        d = defn()
        del d["name"]
        self.assertIn("name: fallback", self.render(d=d, s=spec(fields=fields, path="x.md"))["content"])
        self.refuses("path|name", d=d, s=spec(fields=fields))

    def test_an_optional_field_that_is_absent_is_left_out_silently(self):
        r = self.render(d=defn(effort=None))
        self.assertNotIn("effort", r["content"])
        self.assertEqual(r["notes"], [])

    def test_degrade_a_value_the_runtime_cannot_express_is_dropped_with_a_note(self):
        r = self.render(d=defn(effort="extreme"))
        self.assertNotIn("effort", r["content"])
        self.assertEqual(r["notes"], ["effort: omitted, the runtime has no effort for 'extreme'"])

    def test_degrade_refuse_and_required_refuse_instead(self):
        fields = [dict(f, degrade="refuse") if f["to"] == "effort" else f for f in FIELDS]
        self.refuses("effort", d=defn(effort="extreme"), s=spec(fields=fields))
        self.refuses("model", d=defn(tier="fast"))

    def test_a_guarantee_is_never_dropped_for_the_class_it_guards(self):
        d = defn(**{"class": "read-only"})
        d_no_tools = defn(tools=None, **{"class": "read-only"})
        self.assertIn("tools: Bash, Read, Edit", self.render(d=d)["content"])
        self.refuses("tools", d=d_no_tools)                                          # absent for a read-only member
        self.assertNotIn("tools", self.render(d=defn(tools=None))["content"])         # absent for a write member: fine
        fields = [dict(f, tool_map={"bash": "Bash"}) if f["to"] == "tools" else f for f in FIELDS]
        self.refuses("tool", d=d, s=spec(fields=fields))                             # an unmapped REQUIRED tool always refuses

    def test_tools_policy_required_and_optional(self):
        tools = {"required": ["bash"], "optional": ["monitor", "unknown"]}
        r = self.render(d=defn(tools=tools))
        self.assertIn("tools: Bash, Monitor\n", r["content"])
        self.assertEqual(r["notes"], ["tools: the optional tool 'unknown' has no native name and was dropped"])
        self.refuses("unknown", d=defn(tools={"required": ["unknown"]}))
        fields = [dict(f, tool_map={"a": ["A", "B"], "b": "A"}) if f["to"] == "tools" else f for f in FIELDS]
        self.assertIn("tools: A, B\n", self.render(d=defn(tools=["a", "b"]), s=spec(fields=fields))["content"])      # one tool, several natives; no repeats

    def test_when_class(self):
        fields = FIELDS + [{"value": "plan", "to": "mode", "when": {"class": "read-only"}}]
        self.assertNotIn("\nmode:", self.render(s=spec(fields=fields))["content"])
        self.assertIn("mode: plan", self.render(d=defn(**{"class": "read-only"}), s=spec(fields=fields))["content"])

    def test_the_class_may_come_as_read_only_flag(self):
        d = defn(**{"read_only": True})
        del d["class"]
        fields = [{"value": "{class}", "to": "c"}]
        self.assertIn("c: read-only", self.render(d=d, s=spec(fields=fields))["content"])
        d["read_only"] = False
        self.assertIn("c: write", self.render(d=d, s=spec(fields=fields))["content"])
        d = defn()
        del d["class"]
        self.refuses("class", d=d)
        self.refuses("class", d=defn(**{"class": "admin"}))

    def test_transforms(self):
        def one(value, transform, **kw):
            fields = [{"value": value, "to": "k", "transform": transform}]
            return tomllib.loads(self.render(s=spec(format="toml", fields=fields, body=None), **kw)["content"])["k"]
        self.assertEqual(one("AbC", "lower"), "abc")
        self.assertEqual(one("AbC", "upper"), "ABC")
        self.assertEqual(one("  x ", "strip"), "x")
        self.assertEqual(one("x", {"prefix": "qargi-"}), "qargi-x")
        self.assertEqual(one("x", {"suffix": ".md"}), "x.md")
        self.assertEqual(one("x", {"map": {"x": "y"}}), "y")
        self.assertEqual(one(["A", "B"], "lower"), ["a", "b"])                       # elementwise on a list
        self.assertEqual(one(["a", "b"], {"join": "+"}), "a+b")
        self.assertEqual(one(["a", "b"], {"join": ""}), "ab")
        self.assertEqual(one(["a", 2], "join"), "a, 2")
        self.assertEqual(one(["b", "a"], [{"map": {"a": "A", "b": "B"}}, "lower", {"prefix": "<"}, {"join": " "}]), "<b <a")
        self.assertEqual(one("read-only", {"map": {"write": 1, "read-only": True}}), True)

    def test_transform_errors(self):
        def one(value, transform):
            self.refuses("transform|join|map|text|string|needs", s=spec(format="toml", fields=[{"value": value, "to": "k", "transform": transform}], body=None))
        one("x", "shout")                                  # unknown
        one("x", {"shout": 1})
        one("x", {"prefix": 3})
        one("x", {"prefix": "a", "suffix": "b"})           # one name per entry
        one("x", {"lower": 1})
        one("x", {"map": "nope"})
        one("x", {"map": {"y": "z"}})                      # no entry
        one("x", {"map": {"x": [1]}})
        one("x", "join")                                   # not a list
        one([[1]], "join")
        one(5, "lower")
        one(True, {"prefix": "x"})
        one("x", 5)

    def test_unknown_transform_is_refused_even_on_a_field_that_does_not_apply(self):
        fields = [{"value": "x", "to": "k", "transform": "shout", "when": {"class": "read-only"}}]
        self.refuses("shout", s=spec(fields=fields))

    def test_interpolation(self):
        def val(template, d=None):
            fields = [{"value": template, "to": "k"}]
            return tomllib.loads(self.render(d=d, s=spec(format="toml", fields=fields, body=None))["content"])["k"]
        self.assertEqual(val("{name}"), "build-1")
        self.assertEqual(val("{abilities}"), ["build", "test"])                      # exactly one placeholder: its type
        self.assertEqual(val("x {abilities} y"), "x build, test y")
        self.assertEqual(val("{missing|name}"), "build-1")                          # first non-empty
        self.assertEqual(val("{description|name}", defn(description="")), "build-1")
        self.assertEqual(val("{{name}} {name}"), "{name} build-1")
        self.assertEqual(val("{barrier.guard_command}"), "qargi __guard --provider p")
        for bad in ("{nope}", "{nope|also}", "{barrier}x", "a { b", "a } b", "{}", "{a b}", "{name"):
            with self.subTest(bad=bad):
                self.refuses("", s=spec(format="toml", fields=[{"value": bad, "to": "k"}], body=None))

    def test_path_template(self):
        self.assertEqual(self.render(s=spec(path="agents/{name}.md"))["path"], "agents/build-1.md")
        self.assertEqual(self.render(s=spec(path=".dot/{name}.md"))["path"], ".dot/build-1.md")
        for bad in ("{name}/../x.md", "/abs/{name}.md", "../{name}.md", "a//{name}.md", "{nope}.md", "", "a\\{name}.md", "./{name}.md", "{name}.md\n"):
            with self.subTest(bad=bad):
                self.refuses("path|nope", s=spec(path=bad))
        for name in ("a/b", "..", ".", "a\\b", "x\ny", "x\x00y"):
            with self.subTest(name=name):
                self.refuses("path|name", d=defn(name=name))

    def test_spec_errors(self):
        for bad in [
            {"format": "xml"}, {"fields": "x"}, {"fields": ["x"]}, {"path": 3}, {"engine": "other"}, {"nope": 1}, {"template": "x"}, {"resolve": 3},
            {"fields": [{"to": "a"}]}, {"fields": [{"from": "name"}]}, {"fields": [{"from": "name", "value": "x", "to": "a"}]},
            {"fields": [{"from": "name", "to": "a", "nope": 1}]}, {"fields": [{"from": "name", "to": ""}]}, {"fields": [{"from": "n me", "to": "a"}]},
            {"fields": [{"from": "name", "to": "a", "tool_map": {}}]}, {"fields": [{"from": "tools", "to": "a", "tool_map": {"a": 1}}]},
            {"fields": [{"from": "name", "to": "a", "degrade": "shrug"}]}, {"fields": [{"from": "name", "to": "a", "guarantee_for": ["x"]}]},
            {"fields": [{"from": "name", "to": "a", "when": {"class": "x"}}]}, {"fields": [{"from": "name", "to": "a", "refuse_if_missing": "yes"}]},
            {"format": "text"}, {"format": "text", "template": 5},
        ]:
            with self.subTest(bad=bad):
                self.refuses("", s=spec(**bad))
        self.refuses("two fields", s=spec(fields=[{"from": "name", "to": "a"}, {"value": "x", "to": "a"}]))

    def test_definition_errors(self):
        for bad in [[], "x", {"name": 3, "class": "write"}, defn(abilities="build"), defn(abilities=[1]), defn(tools="bash"), defn(tools=[1]),
                    defn(tools={"required": "x"}), defn(tools={"other": []}), defn(tier=3), defn(body=3), defn(extra={1, 2})]:
            with self.subTest(bad=bad):
                self.refuses("", d=bad)

    def test_a_value_the_format_cannot_hold_is_an_error(self):
        self.refuses("float", s=spec(format="toml", fields=[{"value": 1.5, "to": "f"}], body=None))
        self.refuses("control|U\\+", s=spec(format="markdown-frontmatter", fields=FIELDS[:1]), d=defn(body="a\x00b"))

    def test_a_broken_emitter_is_caught_by_the_parse_back(self):
        orig = R.emit_yaml
        with mock.patch.object(R, "emit_yaml", lambda data: orig({k: v for k, v in data.items() if k != "name"})):
            self.refuses("differs", s=spec(format="yaml", fields=FIELDS[:2], body=None))
        origj = R.emit_json
        with mock.patch.object(R, "emit_json", lambda data: origj(dict(data, name=True))):
            self.refuses("differs", s=spec(format="json", fields=FIELDS[:2], body=None))
        origt = R.emit_toml
        with mock.patch.object(R, "emit_toml", lambda data: origt(dict(data, name="other"))):
            self.refuses("differs", s=spec(format="toml", fields=FIELDS[:2], body=None))
        origm = R.emit_markdown
        with mock.patch.object(R, "emit_markdown", lambda meta, body: origm(meta, "tampered\n")):
            self.refuses("differs")

    def test_resolver_failures(self):
        def boom(kind, value, d):
            raise KeyError(value)
        self.refuses("resolver failed", resolver=boom)
        self.refuses("resolver", resolver=lambda k, v, d: {1, 2})

        def custom(kind, value, d):
            raise R.RenderError("catalog has no tier %s" % value)
        self.refuses("catalog has no tier", resolver=custom)

    def test_the_result_is_valid_for_the_cli_json(self):
        r = self.render()
        self.assertEqual(json.loads(json.dumps(r)), r)


# ---------------------------------------------------------------- the command renderer

class CommandBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="render.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "pack")
        os.makedirs(os.path.join(self.root, "renderers"))
        self.n = 0

    def script(self, body, name=None, mode=0o755, shebang=True):
        """An executable python script in the pack; returns its path relative to the root."""
        self.n += 1
        rel = name or "renderers/r%d" % self.n
        with open(os.path.join(self.root, rel), "w") as f:
            f.write(("#!%s\n" % sys.executable if shebang else "") + body)
        os.chmod(os.path.join(self.root, rel), mode)
        return rel

    def spec(self, rel, *args, **kw):
        s = {"engine": "command", "command": [rel] + list(args), "path": "{name}.out"}
        s.update(kw)
        return s

    def run_(self, body, d=None, **kw):
        return R.render_command(defn() if d is None else d, self.spec(self.script(body), *kw.pop("args", ())), root=self.root, **kw)

    def refuses(self, match, *a, **kw):
        with self.assertRaisesRegex(R.RenderError, match):
            self.run_(*a, **kw)

    ECHO = "import json, sys\nd = json.load(sys.stdin)\nprint('name=' + d['definition']['name'])\n"


class CommandRenderer(CommandBase):

    def test_the_output_is_the_file(self):
        r = self.run_(self.ECHO)
        self.assertEqual(r["content"], "name=build-1\n")
        self.assertEqual(r["path"], "build-1.out")
        self.assertEqual(r["sha256"], hashlib.sha256(b"name=build-1\n").hexdigest())
        self.assertRegex(r["inputs_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(sorted(r), ["content", "inputs_hash", "notes", "path", "sha256"])

    def test_stdin_holds_the_definition_the_spec_and_what_the_resolver_said(self):
        body = "import json, sys\nsys.stdout.write(json.dumps(json.load(sys.stdin), sort_keys=True))\n"
        spec = self.spec(self.script(body))
        r = R.render_command(defn(), spec, root=self.root, resolver=resolver)
        got = json.loads(r["content"])
        self.assertEqual(got["definition"], defn())
        self.assertEqual(got["spec"], spec)
        self.assertEqual(got["resolved"], {"model": "m-bal", "effort": "hi"})
        got = json.loads(R.render_command(defn(), spec, root=self.root)["content"])
        self.assertEqual(got["resolved"], {})

    def test_no_shell_arguments_are_literal(self):
        body = "import sys\nprint(sys.argv[1] + '|' + sys.argv[2])\n"
        evil = "$(touch %s); `x` * ;" % os.path.join(self.tmp, "pwned")
        r = R.render_command(defn(), self.spec(self.script(body), evil, "a b"), root=self.root)
        self.assertEqual(r["content"], evil + "|a b\n")
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "pwned")))

    def test_the_environment_is_a_fixed_small_set_and_the_cwd_a_temporary_directory(self):
        body = "import json, os\nprint(json.dumps({'env': sorted(os.environ), 'cwd': os.getcwd(), 'home': os.environ['HOME'], 'path': os.environ['PATH']}))\n"
        with mock.patch.dict(os.environ, {"QARGI_SECRET": "x", "ANTHROPIC_API_KEY": "k", "PATH": "/nonexistent", "PYTHONPATH": "/x", "LD_PRELOAD": "/x"}):
            got = json.loads(self.run_(body)["content"])
        self.assertEqual(got["env"], sorted(R.CHILD_ENV_KEYS))
        self.assertNotEqual(got["path"], "/nonexistent")
        self.assertEqual(got["home"], got["cwd"])
        self.assertNotEqual(os.path.realpath(got["cwd"]), os.path.realpath(os.getcwd()))
        self.assertFalse(os.path.exists(got["cwd"]), "the temporary directory is removed")

    def test_exit_status_not_zero_is_an_error_with_the_stderr(self):
        self.refuses("status 3.*boom: no catalog", "import sys\nprint('partial')\nsys.stderr.write('boom: no catalog\\n')\nsys.exit(3)\n")
        self.refuses("signal", "import os, signal\nos.kill(os.getpid(), signal.SIGKILL)\n")

    def test_timeout(self):
        t0 = time.monotonic()
        with self.assertRaisesRegex(R.RenderError, "timed out"):
            R.render_command(defn(), self.spec(self.script("import time\ntime.sleep(30)\n"), timeout=0.5), root=self.root)
        self.assertLess(time.monotonic() - t0, 10)   # hermetic: allow clock (the script sleeps 30 s: the bound is its cut-off at 0.5 s, with a margin)
        with self.assertRaisesRegex(R.RenderError, "timed out"):                        # the caller's limit is an upper bound
            R.render_command(defn(), self.spec(self.script("import time\ntime.sleep(30)\n"), timeout=100), root=self.root, timeout=0.5)
        with self.assertRaisesRegex(R.RenderError, "timed out"):                        # the default limit applies without either
            with mock.patch.object(R, "DEFAULT_TIMEOUT", 0.5):
                R.render_command(defn(), self.spec(self.script("import time\ntime.sleep(30)\n")), root=self.root)

    def test_the_whole_process_group_is_killed_on_timeout(self):
        pidfile = os.path.join(self.tmp, "child.pid")
        body = ("import os, subprocess, sys, time\nc = subprocess.Popen(['sleep', '60'])\nprint(c.pid, file=open(%r, 'w'))\ntime.sleep(60)\n" % pidfile)
        with self.assertRaisesRegex(R.RenderError, "timed out"):
            R.render_command(defn(), self.spec(self.script(body), timeout=1.5), root=self.root)
        with open(pidfile) as f:
            pid = int(f.read())
        for _ in range(50):
            try:
                os.kill(pid, 0)
                with open("/proc/%d/stat" % pid) as f:
                    if f.read().split(")")[-1].split()[0] == "Z":
                        break
            except (ProcessLookupError, FileNotFoundError):
                break
            time.sleep(0.1)
        else:
            self.fail("the child of the renderer is still running")

    def test_a_script_that_never_reads_a_big_definition_does_not_hang(self):
        big = defn(body="x" * 1_000_000)
        r = R.render_command(big, self.spec(self.script("print('done')\n")), root=self.root)
        self.assertEqual(r["content"], "done\n")
        with self.assertRaisesRegex(R.RenderError, "larger"):
            R.render_command(defn(body="x" * (5 * 1024 * 1024)), self.spec(self.script("print('done')\n")), root=self.root)

    def test_the_output_must_be_utf8_text_of_a_sane_size(self):
        self.refuses("UTF-8", "import sys\nsys.stdout.buffer.write(b'ok \\xff\\xfe')\n")
        self.refuses("NUL", "import sys\nsys.stdout.buffer.write(b'ok\\x00ok')\n")
        self.refuses("nothing|empty", "pass\n")
        self.refuses("larger", "import sys\nsys.stdout.write('x' * %d)\n" % (R.MAX_BYTES + 1))
        self.assertEqual(len(self.run_("import sys\nsys.stdout.write('x' * %d)\n" % R.MAX_BYTES)["content"]), R.MAX_BYTES)
        t0 = time.monotonic()
        self.refuses("larger", "import sys\nwhile True:\n    sys.stdout.write('x' * 65536)\n    sys.stdout.flush()\n")      # never stops: killed at the cap
        self.assertLess(time.monotonic() - t0, 20)   # hermetic: allow clock (a script that never stops: the bound is the cap that kills it)

    def test_the_declared_format_is_checked(self):
        spec = self.spec(self.script("print('{\"a\": 1}')\n"), format="json")
        self.assertEqual(R.render_command(defn(), spec, root=self.root)["content"], '{"a": 1}\n')
        for fmt, text, ok in (("json", "{nope", False), ("toml", "a = 1\\n", True), ("toml", "a = = 1\\n", False),
                              ("markdown-frontmatter", "---\\nanything: [at all]\\n---\\n\\nbody\\n", True), ("markdown-frontmatter", "no front matter\\n", False),
                              ("yaml", "a: &x [free, form]\\n", True), ("text", "words\\n", True)):
            with self.subTest(fmt=fmt, text=text):
                spec = self.spec(self.script("import sys\nsys.stdout.write('%s')\n" % text), format=fmt)
                if ok:
                    R.render_command(defn(), spec, root=self.root)
                else:
                    with self.assertRaisesRegex(R.RenderError, fmt):
                        R.render_command(defn(), spec, root=self.root)

    def test_deterministic_and_the_hash_follows_the_script(self):
        rel = self.script(self.ECHO)
        spec = self.spec(rel)
        a = R.render_command(defn(), spec, root=self.root)
        self.assertEqual(a, R.render_command(defn(), spec, root=self.root))
        with open(os.path.join(self.root, rel), "a") as f:
            f.write("# a comment\n")
        b = R.render_command(defn(), spec, root=self.root)
        self.assertEqual(a["content"], b["content"])
        self.assertNotEqual(a["inputs_hash"], b["inputs_hash"])                           # a changed script makes the render stale
        self.assertNotEqual(b["inputs_hash"], R.render_command(defn(description="x"), spec, root=self.root)["inputs_hash"])
        self.assertNotEqual(b["inputs_hash"], R.render_command(defn(), spec, root=self.root, extra={"catalog": 1})["inputs_hash"])

    # ---- which file may be run

    def test_the_command_must_stay_inside_the_root(self):
        rel = self.script(self.ECHO)
        outside = os.path.join(self.tmp, "outside")
        with open(outside, "w") as f:
            f.write("#!%s\nprint('outside')\n" % sys.executable)
        os.chmod(outside, 0o755)
        os.symlink(outside, os.path.join(self.root, "renderers", "link-out"))
        os.symlink(os.path.join(self.root, rel), os.path.join(self.root, "renderers", "link-in"))
        os.symlink(self.tmp, os.path.join(self.root, "dirlink"))
        ok = [rel, "renderers/../" + rel, "./" + rel, os.path.join(self.root, rel), "renderers/link-in"]
        for c in ok:
            with self.subTest(ok=c):
                self.assertEqual(R.render_command(defn(), self.spec(c), root=self.root)["content"], "name=build-1\n")
        for c in ["../outside", "renderers/../../outside", outside, "renderers/link-out", "dirlink/outside", "/bin/sh", "", "renderers/missing", "renderers"]:
            with self.subTest(refused=c):
                with self.assertRaises(R.RenderError):
                    R.render_command(defn(), self.spec(c), root=self.root)

    def test_a_relative_command_needs_a_root(self):
        rel = self.script(self.ECHO)
        with self.assertRaisesRegex(R.RenderError, "root"):
            R.render_command(defn(), self.spec(rel), root=None)
        # an absolute one is the caller's choice when it gives no root
        self.assertEqual(R.render_command(defn(), self.spec(os.path.join(self.root, rel)), root=None)["content"], "name=build-1\n")

    def test_only_a_regular_executable_text_file(self):
        os.mkfifo(os.path.join(self.root, "fifo"))
        with self.assertRaisesRegex(R.RenderError, "regular"):
            R.render_command(defn(), self.spec("fifo"), root=self.root)
        with self.assertRaisesRegex(R.RenderError, "regular"):
            R.render_command(defn(), self.spec("renderers"), root=self.root)
        with self.assertRaisesRegex(R.RenderError, "executable"):
            R.render_command(defn(), self.spec(self.script(self.ECHO, mode=0o644)), root=self.root)
        for name, data in (("elf", b"\x7fELF\x02\x01\x01\x00" + bytes(100)), ("latin", b"#!/bin/sh\necho caf\xe9\n"), ("zip", b"PK\x03\x04" + bytes(50))):
            with self.subTest(name=name):
                path = os.path.join(self.root, name)
                with open(path, "wb") as f:
                    f.write(data)
                os.chmod(path, 0o755)
                with self.assertRaisesRegex(R.RenderError, "text"):
                    R.render_command(defn(), self.spec(name), root=self.root)
        big = os.path.join(self.root, "big")
        with open(big, "w") as f:
            f.write("#!/bin/sh\n" + "# pad\n" * 300000)
        os.chmod(big, 0o755)
        with self.assertRaisesRegex(R.RenderError, "larger"):
            R.render_command(defn(), self.spec("big"), root=self.root)

    def test_a_text_file_the_system_cannot_run(self):
        self.script("print(1)\n", name="renderers/noshebang", shebang=False)
        with self.assertRaisesRegex(R.RenderError, "cannot run"):
            R.render_command(defn(), self.spec("renderers/noshebang"), root=self.root)

    def test_bad_argv_and_spec(self):
        rel = self.script(self.ECHO)
        for bad in ({"command": []}, {"command": rel}, {"command": [rel, 3]}, {"command": [rel, "a\x00b"]}, {"command": [3]}, {"timeout": 0}, {"timeout": "5"},
                    {"timeout": True}, {"format": "xml"}, {"nope": 1}, {"engine": "map"}, {"path": 3}, {"path": "../x"}):
            with self.subTest(bad=bad):
                spec = self.spec(rel)
                spec.update(bad)
                with self.assertRaises(R.RenderError):
                    R.render_command(defn(), spec, root=self.root)
        with self.assertRaises(R.RenderError):
            R.render_command(defn(), {"engine": "command", "path": "x"}, root=self.root)

    def test_the_definition_is_checked_like_the_map_renderers(self):
        with self.assertRaisesRegex(R.RenderError, "class"):
            R.render_command(defn(**{"class": "root"}), self.spec(self.script(self.ECHO)), root=self.root)


class Dispatch(CommandBase):
    def test_render_picks_the_engine(self):
        self.assertEqual(R.render(defn(), spec(), resolver=resolver)["content"], GOLDEN_MD)
        self.assertEqual(R.render(defn(), self.spec(self.script(self.ECHO)), root=self.root)["content"], "name=build-1\n")
        with self.assertRaisesRegex(R.RenderError, "engine"):
            R.render(defn(), {"engine": "adapter"})
        with self.assertRaisesRegex(R.RenderError, "spec"):
            R.render(defn(), [])


class Cli(CommandBase):
    def cli(self, *args):
        return subprocess.run([sys.executable, os.path.join(LIB, "render.py")] + list(args), capture_output=True, text=True, timeout=60)

    def files(self, d, s):
        for name, v in (("spec.json", s), ("def.json", d)):
            with open(os.path.join(self.root, name), "w") as f:
                json.dump(v, f)
        return os.path.join(self.root, "spec.json"), os.path.join(self.root, "def.json")

    def test_render_prints_the_result_as_json(self):
        sp, df = self.files(defn(), spec(resolve=TABLES))
        r = self.cli("render", sp, df)
        self.assertEqual((r.returncode, r.stderr), (0, ""))
        self.assertEqual(json.loads(r.stdout), R.render_map(defn(), spec(resolve=TABLES)))
        self.assertEqual(json.loads(r.stdout)["content"], GOLDEN_MD)

    def test_a_command_spec_is_relative_to_the_spec_file(self):
        sp, df = self.files(defn(), self.spec(self.script(self.ECHO)))
        r = self.cli("render", sp, df)
        self.assertEqual((r.returncode, json.loads(r.stdout)["content"]), (0, "name=build-1\n"))
        sp, df = self.files(defn(), self.spec("../outside"))
        r = self.cli("render", sp, df)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertIn("root", r.stderr)

    def test_errors_exit_1_and_usage_exits_2(self):
        sp, df = self.files(defn(), spec())                       # no resolver for the model field
        r = self.cli("render", sp, df)
        self.assertEqual((r.returncode, r.stdout), (1, ""))
        self.assertRegex(r.stderr, r"^render: .*resolver")
        self.assertEqual(self.cli("render", sp, os.path.join(self.root, "missing.json")).returncode, 1)
        with open(os.path.join(self.root, "bad.json"), "w") as f:
            f.write("{nope")
        self.assertEqual(self.cli("render", sp, os.path.join(self.root, "bad.json")).returncode, 1)
        for args in ([], ["render"], ["render", sp], ["render", sp, df, "x"], ["emit", sp, df]):
            r = self.cli(*args)
            self.assertEqual(r.returncode, 2, args)
            self.assertIn("usage:", r.stderr)


if __name__ == "__main__":
    unittest.main()
