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
