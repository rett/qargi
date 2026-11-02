#!/usr/bin/env python3
"""qargi render: turns a neutral agent definition into the files a runtime reads. Stdlib only (Python 3.11 or later: tomllib).

Emitters (qargi's own, deterministic: UTF-8, LF, exactly one trailing newline, the key order of the map you give):
  emit(fmt, data, body=None)        fmt is one of FORMATS; data is a map; body is the text of a markdown file or of a text file
  emit_json / emit_yaml / emit_toml(data)   emit_markdown(meta, body)   emit_text(text)
Readers, used to verify every render by parsing it back:
  parse(fmt, content)               the data (markdown: (meta, body))
  parse_yaml(text)                  reads exactly what emit_yaml writes and refuses everything else (no comments, anchors, tags,
                                    flow collections but {} and [], single quotes, folded blocks, tabs, CRLF, duplicate keys)
  split_markdown(text)              (meta, body) of a front matter file; parse_toml is tomllib, parse_json is json
  check_roundtrip(fmt, content, data, body=None)   RenderError unless the content parses back to data (same types: a string
                                    "1" is not 1, True is not 1) and, for yaml and markdown, is what the emitter would write
The `map` renderer, from data (see render_map):
  render_map(definition, spec, resolver=None, extra=None)
                                    {path, content, sha256, inputs_hash, notes}; the content has been read back and equals the
                                    mapped values, or RenderError. definition is the neutral agent definition (name, description,
                                    abilities, class write|read-only, tier, effort, tools, body, ...), spec the renderer's data.
Values: text, True/False, ints within 64 bits, lists, maps with text keys; None in json and yaml; finite floats in json only.
Anything else is a RenderError naming the value, never a silent change. Text may not hold NUL or other control characters in a
text file or a markdown body (a table, a map value or a key can: it is escaped).

Everything raises RenderError.
"""
import hashlib
import json
import re
import sys
import tomllib

FORMATS = ("markdown-frontmatter", "yaml", "toml", "json", "text")
MAX_BYTES = 256 * 1024                       # the largest file a render may be
MAX_DEPTH = 32                               # the deepest nesting an emitter or the YAML reader follows
INT_MIN, INT_MAX = -(2 ** 63), 2 ** 63 - 1


class RenderError(Exception):
    pass


def _fail(msg):
    raise RenderError(msg)


def sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- values

def _printable(ch):
    """The characters written as they are inside a quoted string; every other one is escaped."""
    cp = ord(ch)
    return (0x20 <= cp <= 0x7e or 0xa0 <= cp <= 0xd7ff and cp not in (0x2028, 0x2029)
            or 0xe000 <= cp <= 0xfffd and cp != 0xfeff or cp >= 0x10000)


def _check_str(s, where):
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        _fail("%s: not valid Unicode text (a lone surrogate)" % where)


def _check_value(v, fmt, where, depth=0):
    if depth > MAX_DEPTH:
        _fail("%s: nested deeper than %d levels" % (where, MAX_DEPTH))
    if v is None:
        if fmt == "toml":
            _fail("%s: null cannot be written as toml (it has no null)" % where)
    elif isinstance(v, bool):
        pass
    elif isinstance(v, int):
        if not INT_MIN <= v <= INT_MAX:
            _fail("%s: integer out of range (64 bits)" % where)
    elif isinstance(v, float):
        if fmt != "json":
            _fail("%s: a float cannot be written as %s (write it as text)" % (where, fmt))
        if v != v or v in (float("inf"), float("-inf")):
            _fail("%s: a float must be finite" % where)
    elif isinstance(v, str):
        _check_str(v, where)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            _check_value(x, fmt, "%s[%d]" % (where, i), depth + 1)
    elif isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                _fail("%s: a map key must be text, not %s" % (where or "value", type(k).__name__))
            _check_str(k, "%s key" % (where or "value"))
            _check_value(x, fmt, "%s.%s" % (where, k) if where else k, depth + 1)
    else:
        _fail("%s: a %s cannot be written as %s" % (where or "value", type(v).__name__, fmt))


def _finish(out, fmt):
    if len(out.encode("utf-8")) > MAX_BYTES:
        _fail("the %s output is larger than %d KiB" % (fmt, MAX_BYTES // 1024))
    return out


def _same(a, b):
    """Equal and of the same types all the way down (True is not 1, 1 is not 1.0); map order does not count."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


# ---------------------------------------------------------------- text and quoting

_ESC = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\t": "\\t", "\r": "\\r"}


def _dq(s):
    """A double-quoted string for yaml and toml (and a toml key): backslash escapes for \\ " newline tab CR, \\uXXXX for the rest."""
    out = []
    for ch in s:
        if ch in _ESC:
            out.append(_ESC[ch])
        elif _printable(ch):
            out.append(ch)
        else:
            out.append("\\u%04x" % ord(ch))
    return '"' + "".join(out) + '"'


def _check_plain_text(s, what):
    _check_str(s, what)
    for ch in s:
        if ch != "\n" and ch != "\t" and (ord(ch) < 0x20 or ord(ch) == 0x7f):
            _fail("%s holds the control character U+%04X (a text file or a body takes none)" % (what, ord(ch)))


def normalize_body(body):
    """The body a markdown file holds: its trailing newlines replaced by exactly one; None when nothing is left."""
    if body is None:
        return None
    b = body.rstrip("\n")
    return b + "\n" if b else None


# ---------------------------------------------------------------- json

def emit_json(data):
    _check_value(data, "json", "")
    return _finish(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", "json")


# ---------------------------------------------------------------- yaml

_YAML_WORDS = frozenset(("true", "false", "yes", "no", "on", "off", "y", "n", "null", "nil", "none", "~"))
_PLAIN_RE = re.compile(r"[A-Za-z_/][A-Za-z0-9_./ ,()+=@%-]*\Z")      # a letter, _ or / first: never a number, date, flag or indicator
_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_-]*\Z")
_INT_RE = re.compile(r"-?(0|[1-9][0-9]*)\Z")


def _plain_ok(s):
    return bool(_PLAIN_RE.match(s)) and s == s.rstrip(" ") and s.lower() not in _YAML_WORDS


def _yaml_key(k):
    return k if _KEY_RE.match(k) and k.lower() not in _YAML_WORDS else _dq(k)


def _yaml_block_ok(s):
    """A string written as a literal block: several lines of plain printable text, no line with a trailing space, one
    trailing newline at most. Anything else is double-quoted."""
    if "\n" not in s or s[0] in " \n" or s.endswith("\n\n"):
        return False
    for ch in s:
        if ch != "\n" and not _printable(ch):
            return False
    return all(line == line.rstrip(" ") for line in s.split("\n"))


def _yaml_inline(v):
    if v is None:
        return "null"
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v if v and _plain_ok(v) else _dq(v)
    return "[]" if isinstance(v, list) else "{}"


def _yaml_emit(v, indent, out):
    pad = " " * indent
    if isinstance(v, dict):
        for k, x in v.items():
            _yaml_item(pad + _yaml_key(k) + ":", x, indent, out, False)
    else:
        for x in v:
            _yaml_item(pad + "-", x, indent, out, True)


def _yaml_item(head, x, indent, out, dash):
    if isinstance(x, (dict, list)) and x:
        sub = []
        _yaml_emit(x, indent + 2, sub)
        if dash:
            sub[0] = " " * indent + "- " + sub[0][indent + 2:]
            out.extend(sub)
        else:
            out.append(head)
            out.extend(sub)
    elif isinstance(x, str) and _yaml_block_ok(x):
        out.append(head + (" |" if x.endswith("\n") else " |-"))
        for line in (x[:-1] if x.endswith("\n") else x).split("\n"):
            out.append(" " * (indent + 2) + line if line else "")
    else:
        out.append(head + " " + _yaml_inline(x))


def emit_yaml(data):
    if not isinstance(data, dict):
        _fail("yaml: the top level must be a mapping")
    _check_value(data, "yaml", "")
    if not data:
        return "{}\n"
    out = []
    _yaml_emit(data, 0, out)
    return _finish("\n".join(out) + "\n", "yaml")


class _YamlReader:
    def __init__(self, text):
        if not isinstance(text, str):
            _fail("yaml: not text")
        if not text.endswith("\n"):
            _fail("yaml: the text does not end with a newline")
        for ch in text:
            if ch != "\n" and not _printable(ch):
                _fail("yaml: the character U+%04X is not in the supported subset (tabs, CR and controls are not)" % ord(ch))
        self.lines = text[:-1].split("\n")
        self.i = 0
        self.depth = 0

    def err(self, msg, at=None):
        _fail("yaml line %d: %s" % ((self.i if at is None else at) + 1, msg))

    def parse(self):
        if len(self.lines) == 1 and self.lines[0] in ("{}", "[]"):
            return {} if self.lines[0] == "{}" else []
        v = self.block(0)
        if self.i != len(self.lines):
            self.err("unexpected content")
        return v

    def indent_of(self, line):
        return len(line) - len(line.lstrip(" "))

    def block(self, indent):
        self.depth += 1
        if self.depth > MAX_DEPTH:
            self.err("nested deeper than %d levels" % MAX_DEPTH)
        if self.i >= len(self.lines):
            self.err("a nested block is missing", len(self.lines) - 1)
        line = self.lines[self.i]
        if self.indent_of(line) != indent:
            self.err("expected an indent of %d" % indent)
        body = line[indent:]
        v = self.seq(indent) if body.startswith("- ") or body == "-" else self.map(indent)
        self.depth -= 1
        return v

    def seq(self, indent):
        out = []
        while self.i < len(self.lines):
            line = self.lines[self.i]
            ind = self.indent_of(line)
            if line == "" or ind < indent:
                break
            if ind > indent:
                self.err("unexpected indentation")
            body = line[indent:]
            if not body.startswith("- "):
                self.err("expected a '- ' item")
            rest = body[2:]
            if rest == "" or rest[0] == " ":
                self.err("an item needs its value on its line")
            if rest.startswith("- ") or self.is_key(rest):
                self.lines[self.i] = " " * (indent + 2) + rest     # the item is a block that starts on the dash line
                out.append(self.block(indent + 2))
            else:
                out.append(self.scalar(rest, indent))
        return out

    def map(self, indent):
        out = {}
        while self.i < len(self.lines):
            line = self.lines[self.i]
            ind = self.indent_of(line)
            if line == "" or ind < indent:
                break
            if ind > indent:
                self.err("unexpected indentation")
            key, rest = self.key(line[indent:])
            if key in out:
                self.err("duplicate key %s" % json.dumps(key))
            if rest is None:
                self.i += 1
                if self.i >= len(self.lines):
                    self.err("a nested block is missing", self.i - 1)
                out[key] = self.block(indent + 2)
            else:
                out[key] = self.scalar(rest, indent)
        return out

    def is_key(self, rest):
        if rest[0] == '"':
            try:
                _, end = self.dq(rest)
            except RenderError:
                return False
            return rest[end:end + 1] == ":" and rest[end + 1:end + 2] in ("", " ")
        m = re.match(r"[A-Za-z_][A-Za-z0-9_-]*:( |\Z)", rest)
        return bool(m)

    def key(self, body):
        if body.startswith('"'):
            k, end = self.dq(body)
            if body[end:end + 1] != ":":
                self.err("expected ':' after the key")
            pos = end + 1
        else:
            m = re.match(r"([A-Za-z_][A-Za-z0-9_-]*):", body)
            if not m or m.group(1).lower() in _YAML_WORDS:
                self.err("expected a key (a plain key that is not a yaml word, or a double-quoted one)")
            k, pos = m.group(1), m.end()
        if pos == len(body):
            return k, None
        if body[pos] != " " or body[pos + 1:pos + 2] in ("", " "):
            self.err("expected one space after ':'")
        return k, body[pos + 1:]

    def dq(self, s):
        """(string, index after the closing quote) of the double-quoted string at the start of s."""
        out = []
        i = 1
        while i < len(s):
            ch = s[i]
            if ch == '"':
                return "".join(out), i + 1
            if ch == "\\":
                nxt = s[i + 1:i + 2]
                if nxt in ('\\', '"'):
                    out.append(nxt)
                    i += 2
                elif nxt in ("n", "t", "r"):
                    out.append({"n": "\n", "t": "\t", "r": "\r"}[nxt])
                    i += 2
                elif nxt == "u" and re.match(r"[0-9a-fA-F]{4}\Z", s[i + 2:i + 6]):
                    cp = int(s[i + 2:i + 6], 16)
                    if 0xd800 <= cp <= 0xdfff:
                        self.err("a surrogate escape is not text")
                    out.append(chr(cp))
                    i += 6
                else:
                    self.err("an escape other than \\\\ \\\" \\n \\t \\r \\uXXXX")
            elif _printable(ch):
                out.append(ch)
                i += 1
            else:
                self.err("a character that must be escaped")
        self.err("a double-quoted string is not closed")

    def scalar(self, rest, col):
        if rest in ("|", "|-"):
            return self.literal(rest, col)
        self.i += 1
        if rest[0] == '"':
            s, end = self.dq(rest)
            if end != len(rest):
                self.err("text after a quoted string", self.i - 1)
            return s
        if rest == "{}":
            return {}
        if rest == "[]":
            return []
        if _INT_RE.match(rest):
            v = int(rest)
            if not INT_MIN <= v <= INT_MAX:
                self.err("integer out of range", self.i - 1)
            return v
        if rest in ("true", "false"):
            return rest == "true"
        if rest == "null":
            return None
        if _plain_ok(rest):
            return rest
        self.err("%r is not in the supported subset (quote it, or the emitter would have)" % rest, self.i - 1)

    def literal(self, marker, col):
        pad = " " * (col + 2)
        j = self.i + 1
        content = []
        while j < len(self.lines) and (self.lines[j] == "" or self.lines[j].startswith(pad)):
            content.append(self.lines[j][len(pad):])
            j += 1
        if not content or content[-1] == "" or content[0][:1] in ("", " "):
            self.err("a literal block must start with text, end with text and be indented by 2")
        self.i = j
        text = "\n".join(content)
        return text + "\n" if marker == "|" else text


def parse_yaml(text):
    return _YamlReader(text).parse()


# ---------------------------------------------------------------- toml

_TOML_BARE = re.compile(r"[A-Za-z0-9_-]+\Z")


def _toml_key(k):
    return k if _TOML_BARE.match(k) else _dq(k)


def _toml_ml(s):
    n = len(s)
    out = []
    for i, ch in enumerate(s):
        if ch == "\n":
            out.append("\n")
        elif ch == '"':
            adjacent = (i > 0 and s[i - 1] == '"') or (i + 1 < n and s[i + 1] == '"') or i == n - 1
            out.append('\\"' if adjacent else '"')
        else:
            out.append(_dq(ch)[1:-1])
    return '"""\n' + "".join(out) + '"""'


def _toml_inline(v, where):
    if v is True:
        return "true"
    if v is False:
        return "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return _dq(v)
    if isinstance(v, list):
        return "[" + ", ".join(_toml_inline(x, where) for x in v) + "]"
    _fail("%s: a table inside an array of arrays cannot be written" % where)


def _toml_table(lines, path, d, aot):
    scalars, subs = [], []
    for k, v in d.items():
        where = ".".join(path + [k])
        if isinstance(v, dict):
            subs.append((k, v, False))
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            subs.append((k, v, True))
        elif isinstance(v, list) and any(isinstance(x, dict) for x in v):
            _fail("%s: an array of tables cannot mix tables with other values" % where)
        else:
            scalars.append((k, v, where))
    if path and (aot or scalars or not d):
        if lines:
            lines.append("")
        lines.append(("[[%s]]" if aot else "[%s]") % ".".join(path))
    for k, v, where in scalars:
        lines.append("%s = %s" % (_toml_key(k), _toml_ml(v) if isinstance(v, str) and "\n" in v else _toml_inline(v, where)))
    for k, v, is_aot in subs:
        p = path + [_toml_key(k)]
        for el in (v if is_aot else [v]):
            _toml_table(lines, p, el, is_aot)


def emit_toml(data):
    if not isinstance(data, dict):
        _fail("toml: the top level must be a table (a map)")
    _check_value(data, "toml", "")
    lines = []
    _toml_table(lines, [], data, False)
    return _finish("\n".join(lines) + "\n", "toml")


def parse_toml(text):
    try:
        return tomllib.loads(text)
    except (tomllib.TOMLDecodeError, RecursionError) as e:
        _fail("toml: %s" % e)


def parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, RecursionError) as e:
        _fail("json: %s" % e)


# ---------------------------------------------------------------- markdown with front matter, text

def emit_markdown(meta, body):
    if not isinstance(meta, dict):
        _fail("markdown: the front matter must be a map")
    if body is not None:
        _check_plain_text(body, "the body")
    head = emit_yaml(meta) if meta else ""
    out = "---\n" + head + "---\n"
    b = normalize_body(body)
    if b is not None:
        out += "\n" + b
    return _finish(out, "markdown")


def split_markdown(text):
    """(meta, body) of a file emit_markdown could have written; body is None when the file has none."""
    if not isinstance(text, str) or not text.startswith("---\n") or not text.endswith("\n"):
        _fail("markdown: a front matter file starts with a --- line and ends with a newline")
    lines = text.split("\n")
    try:
        end = lines.index("---", 1)
    except ValueError:
        _fail("markdown: the front matter is not closed by a --- line")
    meta = parse_yaml("\n".join(lines[1:end]) + "\n") if end > 1 else {}
    if not isinstance(meta, dict):
        _fail("markdown: the front matter must be a map")
    rest = "\n".join(lines[end + 1:])
    if rest == "":
        return meta, None
    if not rest.startswith("\n"):
        _fail("markdown: a blank line separates the front matter from the body")
    body = rest[1:]
    if body.rstrip("\n") == "" or body.endswith("\n\n"):
        _fail("markdown: the body must end with exactly one newline and not be empty")
    return meta, body


def emit_text(text):
    if not isinstance(text, str):
        _fail("text: not text")
    _check_plain_text(text, "the text")
    b = normalize_body(text)
    if b is None:
        _fail("text: the file would be empty")
    return _finish(b, "text")


# ---------------------------------------------------------------- the pair

def emit(fmt, data, body=None):
    if fmt == "json":
        return emit_json(data)
    if fmt == "yaml":
        return emit_yaml(data)
    if fmt == "toml":
        return emit_toml(data)
    if fmt == "markdown-frontmatter":
        return emit_markdown(data, body)
    if fmt == "text":
        return emit_text(body if data is None else data)
    _fail("unknown format %r (one of %s)" % (fmt, ", ".join(FORMATS)))


def parse(fmt, content):
    if fmt == "json":
        return parse_json(content)
    if fmt == "yaml":
        return parse_yaml(content)
    if fmt == "toml":
        return parse_toml(content)
    if fmt == "markdown-frontmatter":
        return split_markdown(content)
    if fmt == "text":
        return content
    _fail("unknown format %r (one of %s)" % (fmt, ", ".join(FORMATS)))


def check_roundtrip(fmt, content, data, body=None):
    """RenderError unless content parses back to data (and body). For yaml and markdown the content must also be what the
    emitter writes for what it parsed to: the reader accepts a little more than the emitter writes, the check does not."""
    if fmt == "markdown-frontmatter":
        meta, got_body = parse(fmt, content)
        if not _same(meta, data) or got_body != normalize_body(body):
            _fail("markdown: the front matter or the body read back differs from what was rendered")
        if emit_markdown(meta, got_body) != content:
            _fail("markdown: the content is not in canonical form")
        return
    if fmt == "text":
        if content != emit_text(body if data is None else data):
            _fail("text: the content read back differs from what was rendered")
        return
    got = parse(fmt, content)
    if not _same(got, data):
        _fail("%s: the content read back differs from what was rendered" % fmt)
    if fmt == "yaml" and emit_yaml(got) != content:
        _fail("yaml: the content is not in canonical form")


# ---------------------------------------------------------------- the map renderer
#
# spec = {
#   "engine": "map",                       optional
#   "format": one of FORMATS,
#   "path": "agents/{name}.md",            the file, relative to the runtime's agents directory; {var} from the definition
#   "fields": [ field, ... ],              the file's keys, in this order
#   "body": "body",                        markdown-frontmatter and text: where the body is in the definition (null: none)
#   "body_required": false,
#   "template": "...{key}...{body}",       text only: placeholders are the `to` keys of the fields, and body
#   "resolve": {"model": {tier: native}, "effort": {...}}      tables for fields with "resolve" when no resolver is passed
# }
# field = {
#   "to": "model",                         the key in the file
#   "from": "tier" | ["a", "b"],           a path in the definition (dots go into maps); a list: the first that is set
#   "value": any,                          or a constant; strings in it may hold {path}, {a|b}, {{ and }}
#   "default": any,                        when the definition does not set it
#   "resolve": "model",                    the value goes through resolver(kind, value, definition); None means "cannot say"
#   "tool_map": {neutral: native | [native]},   from "tools" only: required tools without a native name refuse the render,
#                                          optional ones are dropped with a note
#   "transform": t | [t, ...],             t is a name or {name: arg}: join(sep) lower upper strip prefix(s) suffix(s) map({..})
#   "refuse_if_missing": false,            the field must end up in the file
#   "degrade": "omit" | "refuse",          what to do with a value the runtime cannot express: leave it out with a note, or refuse
#   "guarantee_for": ["read-only"],        for these classes the field is a guarantee: missing or inexpressible always refuses
#   "when": {"class": "read-only"}         the field applies to this class only
# }
# A value that is not there (missing, null, "", [] or {}) is left out of the file silently unless the field is required.

ENGINE_VERSION = 1                           # part of inputs_hash: a change of the emitters or of this engine makes renders STALE
CLASSES = ("write", "read-only")
_MISSING = object()
_REF_RE = re.compile(r"[A-Za-z0-9_-]+(\.[A-Za-z0-9_-]+)*\Z")
_ONE_RE = re.compile(r"\{([^{}]+)\}\Z")
_TOKEN_RE = re.compile(r"\{\{|\}\}|\{([^{}]*)\}")
_MAP_KEYS = {"engine", "format", "path", "fields", "body", "body_required", "template", "resolve"}
_FIELD_KEYS = {"to", "from", "value", "default", "resolve", "tool_map", "transform", "refuse_if_missing", "degrade", "guarantee_for", "when"}
_DEF_TEXT_KEYS = ("name", "description", "tier", "effort", "model", "body")


def canonical_json(v, what="value"):
    try:
        return json.dumps(v, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as e:
        _fail("%s is not JSON data: %s" % (what, e))


def _get(obj, ref):
    for part in ref.split("."):
        if not isinstance(obj, dict) or part not in obj:
            return _MISSING
        obj = obj[part]
    return obj


def _missing(v):
    return v is _MISSING or v is None or v == "" or v == [] or v == {}


def _as_text(v, where):
    if isinstance(v, str):
        return v
    if v is True or v is False:
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, list) and all(isinstance(x, (str, int)) and not isinstance(x, bool) for x in v):
        return ", ".join(str(x) for x in v)
    _fail("%s: a value of this kind cannot be put inside text" % where)


def _interp(t, lookup, where, typed=True, conv=_as_text):
    """The string t with its {ref} / {a|b} placeholders replaced; {{ and }} are braces. A string that is exactly one
    placeholder gives the value itself (a list stays a list) when typed."""
    def ref_value(ref):
        names = [r.strip() for r in ref.split("|")]
        for n in names:
            if not _REF_RE.match(n):
                _fail("%s: %r is not a name in a placeholder" % (where, n))
        for n in names:
            v = lookup(n)
            if not _missing(v):
                return v
        _fail("%s: {%s} is not set" % (where, ref))

    if "{" not in t and "}" not in t:
        return t
    rest = _TOKEN_RE.sub("", t)
    if "{" in rest or "}" in rest:
        _fail("%s: a stray brace in %r (write {{ and }} for braces)" % (where, t))
    m = _ONE_RE.match(t)
    if typed and m:
        return ref_value(m.group(1))

    def sub(m):
        if m.group(0) in ("{{", "}}"):
            return m.group(0)[0]
        return conv(ref_value(m.group(1)), where)
    return _TOKEN_RE.sub(sub, t)


def _interp_value(v, lookup, where):
    if isinstance(v, str):
        return _interp(v, lookup, where)
    if isinstance(v, list):
        return [_interp_value(x, lookup, where) for x in v]
    if isinstance(v, dict):
        return {k: _interp_value(x, lookup, where) for k, x in v.items()}
    return v


# ---- transforms: a closed set

def _each(v, fn, name, where):
    def one(x):
        if not isinstance(x, str):
            _fail("%s: transform %s needs text, got %s" % (where, name, type(x).__name__))
        return fn(x)
    return [one(x) for x in v] if isinstance(v, list) else one(v)


def _t_join(v, arg, where):
    if not isinstance(v, list):
        _fail("%s: transform join needs a list" % where)
    for x in v:
        if not isinstance(x, (str, int)) or isinstance(x, bool):
            _fail("%s: transform join needs a list of text or numbers" % where)
    return (", " if arg is None else arg).join(str(x) for x in v)


def _t_map(v, arg, where):
    def look(x):
        if x not in arg:
            _fail("%s: transform map has no entry for %r" % (where, x))
        return arg[x]
    return _each(v, look, "map", where)


_TRANSFORMS = {            # name: (function, argument kind: None, "text?" (optional text), "text", "table")
    "join": (_t_join, "text?"),
    "lower": (lambda v, a, w: _each(v, str.lower, "lower", w), None),
    "upper": (lambda v, a, w: _each(v, str.upper, "upper", w), None),
    "strip": (lambda v, a, w: _each(v, str.strip, "strip", w), None),
    "prefix": (lambda v, a, w: _each(v, lambda x: a + x, "prefix", w), "text"),
    "suffix": (lambda v, a, w: _each(v, lambda x: x + a, "suffix", w), "text"),
    "map": (_t_map, "table"),
}


def _transform_list(tf, where):
    items = tf if isinstance(tf, list) else [tf]
    out = []
    for t in items:
        if isinstance(t, str):
            name, arg = t, None
        elif isinstance(t, dict) and len(t) == 1:
            (name, arg), = t.items()
        else:
            _fail("%s: a transform is a name or a one-entry map {name: argument}, not %s" % (where, canonical_json(t)))
        if name not in _TRANSFORMS:
            _fail("%s: unknown transform %r (one of %s)" % (where, name, ", ".join(sorted(_TRANSFORMS))))
        kind = _TRANSFORMS[name][1]
        ok = ((kind is None and arg is None) or (kind == "text?" and (arg is None or isinstance(arg, str))) or (kind == "text" and isinstance(arg, str))
              or (kind == "table" and isinstance(arg, dict) and all(isinstance(v, (str, int)) and isinstance(k, str) for k, v in arg.items())))
        if not ok:
            _fail("%s: transform %s takes %s as its argument" % (where, name, {None: "none", "text?": "an optional text", "text": "a text", "table": "a table of text keys"}[kind]))
        out.append((name, arg))
    return out


# ---- the definition and the spec

def _check_definition(d):
    if not isinstance(d, dict):
        _fail("definition: must be a map")
    canonical_json(d, "definition")
    for k in _DEF_TEXT_KEYS:
        if k in d and d[k] is not None and not isinstance(d[k], str):
            _fail("definition: %s must be text" % k)
    if d.get("abilities") is not None and not (isinstance(d["abilities"], list) and all(isinstance(x, str) for x in d["abilities"])):
        _fail("definition: abilities must be a list of text")
    t = d.get("tools")
    if t is not None:
        lists = [t] if isinstance(t, list) else None
        if isinstance(t, dict):
            if set(t) - {"required", "optional"}:
                _fail("definition: tools takes a list, or a map with required and optional")
            lists = [t.get("required", []), t.get("optional", [])]
        if lists is None or not all(isinstance(x, list) and all(isinstance(y, str) for y in x) for x in lists):
            _fail("definition: tools must be a list of names, or {required: [..], optional: [..]}")
    cls = d.get("class")
    if cls is None and isinstance(d.get("read_only"), bool):
        cls = "read-only" if d["read_only"] else "write"
    if cls not in CLASSES:
        _fail("definition: class must be write or read-only (or read_only true or false), not %r" % (cls,))
    ns = dict(d)
    ns["class"] = cls
    return ns


def _check_spec(spec):
    if not isinstance(spec, dict):
        _fail("spec: must be a map")
    canonical_json(spec, "spec")
    if set(spec) - _MAP_KEYS:
        _fail("spec: unknown key %s" % ", ".join(sorted(set(spec) - _MAP_KEYS)))
    if spec.get("engine", "map") != "map":
        _fail("spec: the engine is %r, not map" % spec.get("engine"))
    fmt = spec.get("format")
    if fmt not in FORMATS:
        _fail("spec: format must be one of %s" % ", ".join(FORMATS))
    if not isinstance(spec.get("path"), str) or not spec["path"]:
        _fail("spec: path must be a non-empty template")
    if not isinstance(spec.get("fields"), list):
        _fail("spec: fields must be a list")
    if fmt == "text":
        if not isinstance(spec.get("template"), str):
            _fail("spec: a text format needs a template")
    elif "template" in spec:
        _fail("spec: template is for the text format only")
    if "body" in spec and spec["body"] is not None and fmt not in ("markdown-frontmatter", "text"):
        _fail("spec: body is for markdown-frontmatter and text only")
    if spec.get("body") is not None and not isinstance(spec.get("body", ""), str):
        _fail("spec: body names a path in the definition, or is null")
    if not isinstance(spec.get("body_required", False), bool):
        _fail("spec: body_required must be true or false")
    res = spec.get("resolve", {})
    if not isinstance(res, dict) or not all(isinstance(t, dict) for t in res.values()):
        _fail("spec: resolve is a map of kind to a table")
    for i, f in enumerate(spec["fields"]):
        _check_field(f, "field %d" % i)


def _check_field(f, where):
    if not isinstance(f, dict):
        _fail("%s: must be a map" % where)
    if set(f) - _FIELD_KEYS:
        _fail("%s: unknown key %s" % (where, ", ".join(sorted(set(f) - _FIELD_KEYS))))
    if not isinstance(f.get("to"), str) or not f["to"]:
        _fail("%s: to must name the key in the file" % where)
    where = "field %s" % f["to"]
    if ("from" in f) == ("value" in f):
        _fail("%s: give exactly one of from and value" % where)
    if "from" in f:
        paths = f["from"] if isinstance(f["from"], list) else [f["from"]]
        if not paths or not all(isinstance(p, str) and _REF_RE.match(p) for p in paths):
            _fail("%s: from is a path (letters, digits, _ - and dots) or a list of them" % where)
    if "resolve" in f and not (isinstance(f["resolve"], str) and f["resolve"]):
        _fail("%s: resolve names a kind (model, effort, ...)" % where)
    if "tool_map" in f:
        tm = f["tool_map"]
        if f.get("from") != "tools":
            _fail("%s: tool_map goes with from: tools" % where)
        if not isinstance(tm, dict) or not all(isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)) for v in tm.values()):
            _fail("%s: tool_map maps a neutral name to a native name or a list of them" % where)
    if "transform" in f:
        _transform_list(f["transform"], where)
    if not isinstance(f.get("refuse_if_missing", False), bool):
        _fail("%s: refuse_if_missing must be true or false" % where)
    if f.get("degrade", "omit") not in ("omit", "refuse"):
        _fail("%s: degrade is omit or refuse" % where)
    g = f.get("guarantee_for", [])
    if not isinstance(g, list) or not all(c in CLASSES for c in g):
        _fail("%s: guarantee_for is a list of %s" % (where, " / ".join(CLASSES)))
    w = f.get("when")
    if w is not None and not (isinstance(w, dict) and set(w) == {"class"} and w["class"] in CLASSES):
        _fail("%s: when is {class: write | read-only}" % where)


def table_resolver(tables):
    """A resolver from {kind: {value: native}}; a value with no entry is None (cannot say)."""
    def resolve(kind, value, definition):
        if kind not in tables:
            _fail("no table to resolve %r" % kind)
        return tables[kind].get(value) if isinstance(value, str) else None
    return resolve


def _check_relpath(p, what="path"):
    if not isinstance(p, str) or not p or len(p) > 1024:
        _fail("%s: empty or too long" % what)
    _check_str(p, what)
    if any(ord(c) < 0x20 or ord(c) == 0x7f for c in p) or "\\" in p:
        _fail("%s: %r has a control character or a backslash" % (what, p))
    if p.startswith("/"):
        _fail("%s: %r must be relative" % (what, p))
    for c in p.split("/"):
        if c in ("", ".", "..") or len(c.encode("utf-8")) > 255:
            _fail("%s: %r has an empty, '.', '..' or too long component" % (what, p))
    return p


def render_path(template, ns):
    def lookup(ref):
        v = _get(ns, ref)
        if _missing(v):
            return _MISSING
        if isinstance(v, bool) or not isinstance(v, (str, int)):
            _fail("path: {%s} must be text or a number" % ref)
        return v

    def piece(v, where):
        t = str(v)
        if t in (".", "..") or "/" in t or "\\" in t or any(ord(c) < 0x20 or ord(c) == 0x7f for c in t):
            _fail("path: %r cannot be part of a file name" % t)
        return t
    return _check_relpath(_interp(template, lookup, "path", typed=False, conv=piece))


def _tools_of(ns):
    t = ns.get("tools")
    if isinstance(t, dict):
        return list(t.get("required") or []), list(t.get("optional") or [])
    return list(t or []), []


def _map_fields(ns, spec, resolve, log, notes):
    mapped = {}
    cls = ns["class"]
    for f in spec["fields"]:
        to = f["to"]
        if "when" in f and f["when"]["class"] != cls:
            continue
        guard = cls in f.get("guarantee_for", [])
        must = guard or f.get("refuse_if_missing", False)
        refuse_drop = must or f.get("degrade", "omit") == "refuse"
        where = "field %s" % to

        def lookup(ref):
            return _get(ns, ref)
        if "value" in f:
            raw = _interp_value(f["value"], lookup, where)
        else:
            raw = _MISSING
            for path in (f["from"] if isinstance(f["from"], list) else [f["from"]]):
                v = _get(ns, path)
                if not _missing(v):
                    raw = v
                    break
        if _missing(raw) and "default" in f:
            raw = f["default"]
        if _missing(raw):
            if must:
                _fail("%s: is required and the definition does not set it" % where)
            continue

        def cannot(reason):
            if refuse_drop:
                _fail("%s: %s" % (where, reason))
            notes.append("%s: omitted, %s" % (to, reason))

        if "tool_map" in f:
            required, optional = _tools_of(ns)
            native = []
            for name in required + optional:
                got = f["tool_map"].get(name)
                if got is None:
                    if name in required:
                        _fail("%s: the tool %r has no native name in this runtime" % (where, name))
                    notes.append("%s: the optional tool %r has no native name and was dropped" % (to, name))
                    continue
                for n in ([got] if isinstance(got, str) else got):
                    if n not in native:
                        native.append(n)
            raw = native
            if not raw:
                cannot("no tool can be expressed in this runtime")
                continue
        if "resolve" in f:
            out = resolve(f["resolve"], raw)
            if _missing(out):
                cannot("the runtime has no %s for %r" % (f["resolve"], raw))
                continue
            raw = out
        for name, arg in _transform_list(f.get("transform", []), where):
            raw = _TRANSFORMS[name][0](raw, arg, where)
        if _missing(raw):
            cannot("nothing is left of it after the transforms")
            continue
        if to in mapped:
            _fail("%s: two fields write the key %r" % (where, to))
        mapped[to] = raw
    return mapped


def render_map(definition, spec, resolver=None, extra=None):
    """Render the neutral definition through the map spec. resolver(kind, value, definition) turns a tier into a native model
    and an effort into the runtime's own, or returns None when it cannot; without one the spec's `resolve` tables are used.
    extra (JSON) is anything else the render depends on, such as the hash of the effective runtime definition; it goes into
    inputs_hash. Returns {path, content, sha256, inputs_hash, notes}."""
    ns = _check_definition(definition)
    _check_spec(spec)
    fmt = spec["format"]
    log, notes = [], []
    base = resolver or (table_resolver(spec["resolve"]) if "resolve" in spec else None)

    def resolve(kind, value):
        if base is None:
            _fail("a field needs a resolver for %r and none was given" % kind)
        try:
            out = base(kind, value, definition)
        except RenderError:
            raise
        except Exception as e:                                       # a resolver is the caller's code: report, do not crash
            _fail("the resolver failed for %s %r: %s: %s" % (kind, value, type(e).__name__, e))
        canonical_json(out, "the resolver's answer")
        log.append([kind, value, out])
        return out

    mapped = _map_fields(ns, spec, resolve, log, notes)
    body = None
    if fmt in ("markdown-frontmatter", "text"):
        ref = spec.get("body", "body")
        got = _get(ns, ref) if ref else _MISSING
        if not _missing(got):
            if not isinstance(got, str):
                _fail("body: %s must be text" % ref)
            body = got
        elif spec.get("body_required"):
            _fail("body: %s is required and the definition does not set it" % (ref or "(the spec names none)"))
    if fmt == "text":
        flat = dict(mapped)
        flat["body"] = body if body is not None else _MISSING
        text = _interp(spec["template"], lambda ref: flat.get(ref, _MISSING), "template", typed=False)
        content = emit_text(text)
        check_roundtrip(fmt, content, None, text)
    else:
        content = emit(fmt, mapped, body)
        check_roundtrip(fmt, content, mapped, body)
    path = render_path(spec["path"], ns)
    inputs = canonical_json({"engine": "map", "version": ENGINE_VERSION, "definition": definition, "spec": spec, "resolved": log, "extra": extra})
    return {"path": path, "content": content, "sha256": sha256_text(content), "inputs_hash": sha256_text(inputs), "notes": notes}
