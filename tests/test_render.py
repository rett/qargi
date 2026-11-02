#!/usr/bin/env python3
"""The render engine, lib/render.py: qargi's emitters and parse-back readers for five formats, the declarative `map`
renderer and the `command` renderer. Hermetic: every file is made in a temporary directory.
Run: python3 tests/test_render.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, random, sys, tomllib, unittest
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


if __name__ == "__main__":
    unittest.main()
