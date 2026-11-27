#!/usr/bin/env python3
"""The kinds of the JSON documents qargi prints for a program to read: the registry files of lib/kinds/ and the checker of a document against one.

  jsonkind.py check                    every file of lib/kinds/ is a well-formed registry file, and the kinds are unique
  jsonkind.py check FILE|-             one registry file (- reads standard input)
  jsonkind.py validate KIND FILE|-     a document against the registry file lib/kinds/KIND.json (- reads standard input)

A registry file (format 1) has an envelope of qargi's own keys (registry, kind, schema, status, since, stream (stdout, stderr, or none for a
draft that a verb reads and never prints), verbs, about, writes, history) and `document`, the shape of the document in the keyword subset that lib/provider.py reads for provider definitions: type, enum,
const, pattern, required, properties, items, additionalProperties (a shape for a map, never false) and a local $ref to $defs of the
document. The format check adds what the subset cannot say: the type `number` does not exist (every number is an integer), a document
names its two markers `schema` and `kind`, a field added after the pin is never required, and a reserved field may be null. The
annotations x-text, x-since, x-when, x-reserved, x-open, x-ordered and x-bound, and description, are ignored by a tool that does not know
them.

A document is checked as the rules R-J1 to R-J6 say: one JSON object with `schema` (an integer) and `kind` (a string) equal to the
registry's, no number but an integer within plus or minus 2^53 - 1 (a fraction, an exponent, NaN and Infinity are findings), no
duplicate key, and the shape of `document`. The parser's hooks find what a parsed value no longer shows (a float, a non-finite constant,
a duplicate key), so the text is parsed here and never by the caller.

Each finding is a pair (rule, path) with a sentence: the rule is one of RULES, the path is JSONPath-like ($.features[0].lead). The
command line prints one line per finding on standard error, `LABEL: RULE PATH: sentence`, at most MAX_FINDINGS.

Exit status: 0 valid, 1 invalid (a finding per line on stderr), 2 usage, an unreadable input, an unknown kind or a registry file that is
not well formed. Run as python3 -I lib/jsonkind.py, standard library only."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
KINDS_DIR = os.path.join(HERE, "kinds")
REGISTRY_FORMAT = 1
MAX_INT = 2 ** 53 - 1                 # R-J5: a reader that holds numbers as 64-bit floats loses nothing
MAX_FINDINGS = 100
MAX_DEPTH = 64                        # nesting of a registry shape

KIND_RE = re.compile(r"^qargi-[a-z0-9]+(-[a-z0-9]+)*$")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
REF_RE = re.compile(r"^#/\$defs/([A-Za-z0-9_-]+)$")
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")

ENVELOPE = ("registry", "kind", "schema", "status", "since", "stream", "verbs", "about", "writes", "history", "document")
STATUSES = ("pinned", "draft")
STREAMS = ("stdout", "stderr", "none")        # none: a draft kind that a verb reads and no verb prints
TYPES = ("object", "array", "string", "integer", "boolean", "null")      # no `number`: R-J5
SHAPE_KEYS = ("type", "enum", "const", "pattern", "required", "properties", "items", "additionalProperties", "$ref")
ANNOTATIONS = ("description", "x-text", "x-since", "x-when", "x-reserved", "x-open", "x-ordered", "x-bound")

# Every rule a finding can name, with its sentence. The first group is the rules of a document (R-J1 to R-J6 and section 5.2 of the design),
# the second the rules of the registry format.
RULES = {
    "invalid-json": "the text is not JSON (or not UTF-8)",
    "truncated": "the text ends before the object closes",
    "two-documents": "a second value follows the first",
    "not-an-object": "the document is not one JSON object",
    "schema-missing": "no `schema`",
    "schema-string": "`schema` is a string",
    "schema-float": "`schema` is written with a fraction or an exponent",
    "schema-unknown": "`schema` is an integer the kind does not have",
    "kind-missing": "no `kind`",
    "kind-wrong": "`kind` names another kind",
    "required-missing": "a required field is absent",
    "type-wrong": "a value of another type than declared",
    "integer-string": "an integer field written as a string",
    "enum-unknown": "a word outside the enum",
    "null-not-allowed": "null in a field that is not nullable",
    "const-wrong": "a value other than the declared constant",
    "pattern-mismatch": "a string that does not match the declared pattern",
    "integer-float": "a number with a fraction or an exponent (every number is an integer)",
    "non-finite": "NaN or Infinity",
    "integer-range": "an integer beyond plus or minus 9007199254740991",
    "duplicate-key": "a key written twice in one object",
    "too-deep": "the document is nested too deeply to be read",
    "registry-not-object": "a registry file is one JSON object",
    "registry-version": "`registry` is not the format number 1",
    "envelope-missing": "a key of the envelope is absent",
    "envelope-unknown": "a key the envelope does not have",
    "envelope-type": "an envelope key of the wrong type or form",
    "kind-name": "`kind` is not qargi- and a lower-case name",
    "schema-number": "`schema` is not an integer of 1 or more",
    "status-value": "`status` is not pinned or draft",
    "since-form": "`since` is not a version of the form N.N.N",
    "stream-value": "`stream` is not stdout, stderr or none",
    "stream-none-pinned": "a pinned kind has `stream` stdout or stderr: none is for a draft that a verb reads and never prints",
    "history-entry": "an entry of `history` is not {schema, since, change}",
    "history-order": "`history` is not one entry per integer, ascending, ending at `schema`",
    "history-since": "`since` is not the version of the first entry of `history`",
    "document-not-object": "`document` is not a shape of type object",
    "document-markers": "`document` does not require and fix `schema` and `kind` as the envelope has them",
    "node-not-object": "a shape node is not an object",
    "keyword-unknown": "a keyword outside the subset and the annotations",
    "keyword-needs-type": "a keyword that needs a type the node does not declare",
    "type-number": "the type `number` is not allowed: every number is an integer",
    "type-unknown": "a type outside object, array, string, integer, boolean and null",
    "enum-shape": "`enum` is not a non-empty list of distinct scalars",
    "const-shape": "`const` is not a scalar",
    "value-type-mismatch": "a `const` or `enum` word that the declared type excludes",
    "pattern-invalid": "`pattern` is not a regular expression",
    "required-shape": "`required` is not a list of distinct names",
    "required-unknown": "`required` names a field that `properties` does not declare",
    "required-after-pin": "a field added after the pin (x-since later than `since`) is required",
    "properties-shape": "`properties` is not an object of shape nodes",
    "items-shape": "`items` is not one shape node",
    "additional-shape": "`additionalProperties` is not a shape node (false is never written: a reader must accept unknown fields)",
    "ref-form": "`$ref` is not #/$defs/NAME",
    "ref-unresolved": "`$ref` names a definition that `$defs` does not hold",
    "ref-cycle": "`$ref` leads back to itself without a shape in between",
    "ref-siblings": "a node with `$ref` carries a keyword of the subset: only annotations may stand beside it",
    "defs-shape": "`$defs` is not an object of shape nodes, or stands below the root of the document",
    "annotation-type": "an annotation of the wrong type",
    "annotation-misplaced": "an annotation on a node it does not fit (x-text needs string, x-open an enum, x-ordered an array)",
    "reserved-not-null": "a reserved field whose type excludes null",
    "too-nested": "the shape is nested too deeply",
    "directory-entry": "a file in lib/kinds/ that is not a plain .json file",
    "directory-empty": "the registry directory holds no file",
    "directory-unreadable": "the registry directory cannot be read",
    "file-name": "the file is not named after its kind",
    "kind-duplicate": "two files name the same kind",
}


class Finding(tuple):
    """(rule, path) with a sentence (message) and, from a directory check, the file (where)."""
    def __new__(cls, rule, path, message, where=""):
        self = tuple.__new__(cls, (rule, path))
        self.message, self.where = message, where
        return self

    rule = property(lambda self: self[0])
    path = property(lambda self: self[1])

    def line(self, label=""):
        return "%s: %s %s: %s" % (self.where or label, self[0], self[1], self.message)


class RegistryError(Exception):
    """A registry file that is not well formed: findings holds why."""
    def __init__(self, label, findings):
        Exception.__init__(self, "the registry file %s is not well formed (%s)" % (label, "; ".join("%s %s" % (f[0], f[1]) for f in findings[:3])))
        self.label, self.findings = label, findings


# ---- the parser -----------------------------------------------------------------------------------------------------------

class Flt(float):
    """A number written with a fraction or an exponent: the parser hook for floats gives this, so the value is found where it stands."""


class NonFinite(str):
    """NaN, Infinity or -Infinity: the parser hook for constants gives this."""


class Obj(dict):
    """An object; dups holds the keys that were written more than once (the last value stays)."""
    dups = ()


def _pairs(items):
    o, dups = Obj(), []
    for k, v in items:
        if k in o:
            dups.append(k)
        o[k] = v
    o.dups = tuple(dups)
    return o


def q(v, n=60):
    """A value for a sentence: JSON, plain ASCII, cut."""
    s = json.dumps(v if isinstance(v, (str, int, bool, type(None))) else str(v), ensure_ascii=True)
    return s if len(s) <= n else s[:n - 3] + "..."


def p_key(path, key):
    return path + ("." + key if KEY_RE.match(key) else "[%s]" % json.dumps(key, ensure_ascii=True))


def parse(text):
    """-> (value, None) or (None, Finding). text is str or bytes. The hooks: floats, constants and duplicate keys stay visible in the value."""
    if isinstance(text, (bytes, bytearray)):
        try:
            text = bytes(text).decode("utf-8")
        except UnicodeError:
            return None, Finding("invalid-json", "$", "the text is not UTF-8")
    if not text.strip():
        return None, Finding("truncated", "$", "the text is empty")
    try:
        return json.loads(text, object_pairs_hook=_pairs, parse_float=Flt, parse_constant=NonFinite), None
    except json.JSONDecodeError as e:
        if e.msg.startswith("Extra data"):
            return None, Finding("two-documents", "$", "a second value follows the document (character %d)" % e.pos)
        if e.pos >= len(text.rstrip()) or e.msg.startswith("Unterminated string"):
            return None, Finding("truncated", "$", "the text ends before the object closes: %s" % e.msg)
        return None, Finding("invalid-json", "$", "%s (character %d)" % (e.msg, e.pos))
    except RecursionError:
        return None, Finding("too-deep", "$", "the document is nested too deeply")
    except ValueError as e:
        return None, Finding("invalid-json", "$", str(e)[:100])


def scan(v, path, out):
    """The findings the hooks make possible: a float, a non-finite constant, an integer out of range, a duplicate key, anywhere in the value."""
    if isinstance(v, Obj):
        for k in v.dups:
            out.append(Finding("duplicate-key", p_key(path, k), "the key %s is written twice" % q(k)))
        for k, x in v.items():
            scan(x, p_key(path, k), out)
    elif isinstance(v, list):
        for i, x in enumerate(v):
            scan(x, "%s[%d]" % (path, i), out)
    elif isinstance(v, Flt):
        out.append(Finding("schema-float" if path == "$.schema" else "integer-float", path, "a number with a fraction or an exponent: every number is an integer"))
    elif isinstance(v, NonFinite):
        out.append(Finding("non-finite", path, "%s is not a JSON value" % str(v)))
    elif isinstance(v, int) and not isinstance(v, bool) and abs(v) > MAX_INT:
        out.append(Finding("integer-range", path, "%s is beyond plus or minus %d" % (q(v), MAX_INT)))


def checked_parse(text):
    """-> (value, findings): the parse and the scan of the hooks."""
    v, f = parse(text)
    if f:
        return None, [f]
    out = []
    try:
        scan(v, "$", out)
    except RecursionError:
        out.append(Finding("too-deep", "$", "the document is nested too deeply"))
    return v, out


# ---- the registry format --------------------------------------------------------------------------------------------------

def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def version_of(s):
    return tuple(int(x) for x in s.split(".")) if isinstance(s, str) and VERSION_RE.match(s) else None


def scalar(v):
    return v is None or isinstance(v, (str, bool)) or (is_int(v) and abs(v) <= MAX_INT)


def types_of(node):
    t = node.get("type")
    return None if t is None else ([t] if isinstance(t, str) else (t if isinstance(t, list) else None))


def type_name(v):
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, int):
        return "integer"
    if isinstance(v, str):
        return "string"
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "array"
    return None


def same(a, b):
    return type(a) is type(b) and a == b


class Format:
    """The format check of one registry file."""
    def __init__(self, reg):
        self.reg, self.out = reg, []
        self.defs = set()
        self.since = None

    def add(self, rule, path, message):
        self.out.append(Finding(rule, path, message))

    def run(self):
        reg = self.reg
        if not isinstance(reg, dict):
            self.add("registry-not-object", "$", "a registry file is one JSON object")
            return self.out
        for k in reg:
            if k not in ENVELOPE:
                self.add("envelope-unknown", p_key("$", k), "the envelope has no key %s" % q(k))
        for k in ENVELOPE:
            if k not in reg:
                self.add("envelope-missing", p_key("$", k), "the envelope needs %s" % q(k))
        if "registry" in reg and not (is_int(reg["registry"]) and reg["registry"] == REGISTRY_FORMAT):
            self.add("registry-version", "$.registry", "the format number is %d, not %s" % (REGISTRY_FORMAT, q(reg["registry"])))
        if "kind" in reg and not (isinstance(reg["kind"], str) and KIND_RE.match(reg["kind"])):
            self.add("kind-name", "$.kind", "%s is not qargi- and a lower-case name of digits and single hyphens" % q(reg["kind"]))
        if "schema" in reg and not (is_int(reg["schema"]) and 1 <= reg["schema"] <= MAX_INT):
            self.add("schema-number", "$.schema", "%s is not an integer of 1 or more" % q(reg["schema"]))
        if "status" in reg and reg["status"] not in STATUSES:
            self.add("status-value", "$.status", "%s is not pinned or draft" % q(reg["status"]))
        if "since" in reg:
            self.since = version_of(reg["since"])
            if self.since is None:
                self.add("since-form", "$.since", "%s is not a version of the form N.N.N" % q(reg["since"]))
        if "stream" in reg and reg["stream"] not in STREAMS:
            self.add("stream-value", "$.stream", "%s is not stdout, stderr or none" % q(reg["stream"]))
        elif reg.get("stream") == "none" and reg.get("status") == "pinned":
            self.add("stream-none-pinned", "$.stream", "a pinned kind is printed on stdout or stderr: `none` is for a draft that a verb reads and never prints")
        verbs = reg.get("verbs", [])
        if "verbs" in reg and not (isinstance(verbs, list) and verbs and all(isinstance(x, str) and x.strip() and x == x.strip() for x in verbs)
                                   and len(set(verbs)) == len(verbs)):
            self.add("envelope-type", "$.verbs", "`verbs` is a non-empty list of distinct, non-empty strings")
        for k in ("about", "writes"):
            if k in reg and not (isinstance(reg[k], str) and reg[k].strip() and reg[k] == reg[k].strip() and "\n" not in reg[k]):
                self.add("envelope-type", "$." + k, "`%s` is one non-empty line of text" % k)
        self.history(reg)
        if "document" in reg:
            self.document(reg)
        return self.out

    def history(self, reg):
        h = reg.get("history")
        if "history" not in reg:
            return
        if not (isinstance(h, list) and h):
            self.add("envelope-type", "$.history", "`history` is a non-empty list")
            return
        seen, ok = [], True
        for i, e in enumerate(h):
            here = "$.history[%d]" % i
            if not (isinstance(e, dict) and set(e) == {"schema", "since", "change"} and is_int(e["schema"]) and 1 <= e["schema"] <= MAX_INT
                    and version_of(e["since"]) and isinstance(e["change"], str) and e["change"].strip()):
                self.add("history-entry", here, "an entry is {schema: integer of 1 or more, since: N.N.N, change: text}")
                ok = False
            else:
                seen.append(e["schema"])
        if ok and (seen != sorted(set(seen)) or seen[0] != 1 or seen != list(range(1, len(seen) + 1)) or seen[-1] != reg.get("schema")):
            self.add("history-order", "$.history", "the entries are the integers 1, 2, ... in order, and the last is `schema` (%s)" % q(reg.get("schema")))
        elif ok and self.since is not None and version_of(h[0]["since"]) != self.since:
            self.add("history-since", "$.since", "`since` is %s and the first entry of `history` says %s" % (q(reg.get("since")), q(h[0]["since"])))

    def document(self, reg):
        doc = reg["document"]
        if not (isinstance(doc, dict) and doc.get("type") == "object"):
            self.add("document-not-object", "$.document", "`document` is a shape with the type object")
            return
        defs = doc.get("$defs", {})
        self.defs = set(defs) if isinstance(defs, dict) else set()
        self.node(doc, "$.document", 0, root=True)
        props = doc.get("properties") if isinstance(doc.get("properties"), dict) else {}
        req = doc.get("required") if isinstance(doc.get("required"), list) else []
        for name in ("schema", "kind"):
            node, want = props.get(name), reg.get(name)
            if name not in req or not (isinstance(node, dict) and "const" in node and same(node["const"], want) and not (set(node) & {"type", "enum", "pattern", "$ref"})):
                self.add("document-markers", p_key("$.document.properties", name), "`%s` is required and has the const %s, as the envelope has it" % (name, q(want)))

    def node(self, node, path, depth, root=False):
        if depth > MAX_DEPTH:
            self.add("too-nested", path, "the shape is nested more than %d levels" % MAX_DEPTH)
            return
        if not isinstance(node, dict):
            self.add("node-not-object", path, "a shape node is an object")
            return
        allowed = SHAPE_KEYS + ANNOTATIONS + (("$defs",) if root else ())
        for k in node:
            if k not in allowed:
                self.add("keyword-unknown" if k != "$defs" else "defs-shape", p_key(path, k), "the keyword %s is not in the subset" % q(k))
        if "$ref" in node:
            self.ref(node, path)
        else:
            self.keywords(node, path, depth)
        self.annotations(node, path)
        if root and "$defs" in node:
            d = node["$defs"]
            if not isinstance(d, dict):
                self.add("defs-shape", path + ".$defs", "`$defs` is an object of shape nodes")
            else:
                for name, sub in d.items():
                    self.node(sub, p_key(path + ".$defs", name), depth + 1)
                for name in d:
                    self.cycle(name, d)

    def ref(self, node, path):
        r = node["$ref"]
        m = REF_RE.match(r) if isinstance(r, str) else None
        if not m:
            self.add("ref-form", path + ".$ref", "%s is not #/$defs/NAME" % q(r))
        elif m.group(1) not in self.defs:
            self.add("ref-unresolved", path + ".$ref", "$defs has no %s" % q(m.group(1)))
        for k in node:
            if k in SHAPE_KEYS and k != "$ref":
                self.add("ref-siblings", p_key(path, k), "%s stands beside $ref" % q(k))

    def cycle(self, name, defs):
        seen, cur = {name}, defs.get(name)
        while isinstance(cur, dict) and isinstance(cur.get("$ref"), str):
            m = REF_RE.match(cur["$ref"])
            if not m or m.group(1) not in defs:
                return
            if m.group(1) in seen:
                self.add("ref-cycle", "$.document.$defs." + name, "the definition leads back to itself through $ref alone")
                return
            seen.add(m.group(1))
            cur = defs[m.group(1)]

    def keywords(self, node, path, depth):
        types = types_of(node)
        if "type" in node:
            ts = node["type"]
            if not (isinstance(ts, str) or (isinstance(ts, list) and ts and all(isinstance(x, str) for x in ts) and len(set(ts)) == len(ts))):
                self.add("type-unknown", path + ".type", "`type` is a type name or a list of distinct type names")
                types = None
            else:
                for t in types:
                    if t == "number":
                        self.add("type-number", path + ".type", "every number is an integer: declare integer")
                    elif t not in TYPES:
                        self.add("type-unknown", path + ".type", "%s is not a type of the subset" % q(t))
        for kw, need in (("properties", "object"), ("required", "object"), ("additionalProperties", "object"), ("items", "array"), ("pattern", "string")):
            if kw in node and not (types and need in types):
                self.add("keyword-needs-type", p_key(path, kw), "%s needs the type %s" % (q(kw), need))
        if "const" in node:
            if not scalar(node["const"]):
                self.add("const-shape", path + ".const", "`const` is a string, an integer, a boolean or null")
            elif types and type_name(node["const"]) not in types:
                self.add("value-type-mismatch", path + ".const", "%s is not of the declared type" % q(node["const"]))
        if "enum" in node:
            e = node["enum"]
            if not (isinstance(e, list) and e and all(scalar(x) for x in e) and not any(same(a, b) for i, a in enumerate(e) for b in e[i + 1:])):
                self.add("enum-shape", path + ".enum", "`enum` is a non-empty list of distinct scalars")
            elif types:
                for x in e:
                    if type_name(x) not in types:
                        self.add("value-type-mismatch", path + ".enum", "%s is not of the declared type" % q(x))
        if "pattern" in node:
            try:
                if not isinstance(node["pattern"], str):
                    raise re.error("not a string")
                re.compile(node["pattern"])
            except re.error as e:
                self.add("pattern-invalid", path + ".pattern", "not a regular expression: %s" % e)
        props = node.get("properties")
        if "properties" in node:
            if not isinstance(props, dict):
                self.add("properties-shape", path + ".properties", "`properties` is an object of shape nodes")
                props = None
            else:
                for k, sub in props.items():
                    self.node(sub, p_key(path + ".properties", k), depth + 1)
        if "required" in node:
            r = node["required"]
            if not (isinstance(r, list) and all(isinstance(x, str) for x in r) and len(set(r)) == len(r)):
                self.add("required-shape", path + ".required", "`required` is a list of distinct names")
            elif isinstance(props, dict):
                for k in r:
                    if k not in props:
                        self.add("required-unknown", path + ".required", "%s is not declared in `properties`" % q(k))
                    elif self.since is not None and isinstance(props[k], dict) and version_of(props[k].get("x-since")) and version_of(props[k]["x-since"]) > self.since:
                        self.add("required-after-pin", path + ".required", "%s was added in %s, after the pin: it is optional for good" % (q(k), props[k]["x-since"]))
            elif props is None and "properties" not in node and r:
                self.add("required-unknown", path + ".required", "`required` without `properties`")
        if "items" in node:
            if not isinstance(node["items"], dict):
                self.add("items-shape", path + ".items", "`items` is one shape node")
            else:
                self.node(node["items"], path + ".items", depth + 1)
        if "additionalProperties" in node:
            if not isinstance(node["additionalProperties"], dict):
                self.add("additional-shape", path + ".additionalProperties", "a map is `additionalProperties` with a shape; false is never written")
            else:
                self.node(node["additionalProperties"], path + ".additionalProperties", depth + 1)

    def annotations(self, node, path):
        types = types_of(node) or []
        for k in ("x-text", "x-reserved", "x-open", "x-ordered", "x-bound"):
            if k in node and node[k] is not True:
                self.add("annotation-type", p_key(path, k), "%s is true when it is written" % q(k))
        for k in ("x-since", "x-when", "description"):
            if k in node and not (isinstance(node[k], str) and node[k].strip() and (k != "x-since" or version_of(node[k]))):
                self.add("annotation-type", p_key(path, k), "%s is %s" % (q(k), "a version N.N.N" if k == "x-since" else "non-empty text"))
        if "$ref" in node:
            return
        if node.get("x-text") is True and "string" not in types:
            self.add("annotation-misplaced", path + ".x-text", "x-text is for a node of the type string")
        if node.get("x-open") is True and "enum" not in node:
            self.add("annotation-misplaced", path + ".x-open", "x-open is for a node with an enum")
        if node.get("x-ordered") is True and "array" not in types:
            self.add("annotation-misplaced", path + ".x-ordered", "x-ordered is for a node of the type array")
        if node.get("x-reserved") is True:
            if (types and "null" not in types) or ("enum" in node and isinstance(node["enum"], list) and None not in node["enum"]) \
                    or ("const" in node and node["const"] is not None):
                self.add("reserved-not-null", path, "a reserved field may be null")


def check_registry(reg):
    """The findings of the format check of a parsed registry file (an empty list: well formed)."""
    return Format(reg).run()


def load_registry(path):
    """-> (registry, findings): the file read, parsed with the hooks of the parser and format-checked."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        return None, [Finding("invalid-json", "$", "cannot read: %s" % (e.strerror or "error"))]
    return check_text(raw)


def check_text(raw):
    reg, fs = checked_parse(raw)
    if fs:
        return None, fs
    fs = check_registry(reg)
    return (None if fs else reg), fs


def check_dir(d=KINDS_DIR):
    """-> findings of every file of d, each with where set, and of the set: one kind per file, named after it."""
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError as e:
        return [Finding("directory-unreadable", "$", "cannot read %s: %s" % (d, e.strerror or "error"))]
    if not names:
        return [Finding("directory-empty", "$", "%s holds no registry file" % d)]
    kinds = {}
    for n in names:
        p = os.path.join(d, n)
        if not n.endswith(".json") or n.startswith(".") or os.path.islink(p) or not os.path.isfile(p):
            out.append(Finding("directory-entry", "$", "%s is not a plain .json file" % q(n), n))
            continue
        try:
            with open(p, "rb") as f:
                reg, fs = checked_parse(f.read())
        except OSError as e:
            reg, fs = None, [Finding("invalid-json", "$", "cannot read: %s" % (e.strerror or "error"))]
        if reg is not None:
            fs = check_registry(reg)
        for f in fs:
            f.where = n
        out += fs
        kind = reg.get("kind") if isinstance(reg, dict) else None
        if isinstance(kind, str) and KIND_RE.match(kind):
            if n != kind + ".json":
                out.append(Finding("file-name", "$.kind", "the file holds the kind %s: it is named %s" % (q(kind), kind + ".json"), n))
            if kind in kinds:
                out.append(Finding("kind-duplicate", "$.kind", "%s is also the kind of %s" % (q(kind), kinds[kind]), n))
            kinds.setdefault(kind, n)
    return out


def kind_names(d=KINDS_DIR):
    try:
        return sorted(n[:-5] for n in os.listdir(d) if n.endswith(".json") and KIND_RE.match(n[:-5]))
    except OSError:
        return []


def registry_path(kind, d=KINDS_DIR):
    return os.path.join(d, kind + ".json")


# ---- a document against a kind --------------------------------------------------------------------------------------------

def resolve(node, defs):
    while isinstance(node, dict) and "$ref" in node:
        node = defs[REF_RE.match(node["$ref"]).group(1)]
    return node


def walk(v, node, defs, path, out, top=False):
    """The findings of v against the shape node. Values the scan already named (a float, a constant) are not named again."""
    if isinstance(v, (Flt, NonFinite)):
        return
    node = resolve(node, defs)
    t = type_name(v)
    types = types_of(node)
    if types and t not in types:
        if v is None:
            out.append(Finding("null-not-allowed", path, "null where %s is declared" % "/".join(types)))
        elif "integer" in types and t == "string":
            out.append(Finding("integer-string", path, "%s is a string where an integer is declared" % q(v)))
        else:
            out.append(Finding("type-wrong", path, "a value of type %s where %s is declared" % (t, "/".join(types))))
        return
    if "const" in node and not same(v, node["const"]):
        out.append(Finding("const-wrong", path, "%s is not the constant %s" % (q(v), q(node["const"]))))
        return
    if "enum" in node and not any(same(v, e) for e in node["enum"]):
        if v is None:
            out.append(Finding("null-not-allowed", path, "null is not one of %s" % ", ".join(q(e) for e in node["enum"])))
        else:
            out.append(Finding("enum-unknown", path, "%s is not one of %s" % (q(v), ", ".join(q(e) for e in node["enum"]))))
        return
    if "pattern" in node and isinstance(v, str) and not re.search(node["pattern"], v):
        out.append(Finding("pattern-mismatch", path, "%s does not match %s" % (q(v), q(node["pattern"], 80))))
    if isinstance(v, dict):
        props = node.get("properties", {})
        for k in node.get("required", []):
            if k not in v and not (top and k in ("schema", "kind")):
                out.append(Finding("required-missing", p_key(path, k), "the required field %s is absent" % q(k)))
        extra = node.get("additionalProperties")
        for k, x in v.items():
            if top and k in ("schema", "kind"):
                continue
            if k in props:
                walk(x, props[k], defs, p_key(path, k), out)
            elif isinstance(extra, dict):
                walk(x, extra, defs, p_key(path, k), out)
    elif isinstance(v, list) and isinstance(node.get("items"), dict):
        for i, x in enumerate(v):
            walk(x, node["items"], defs, "%s[%d]" % (path, i), out)


def markers(doc, reg, out):
    """R-J1: `schema` and `kind` of the document are the registry's."""
    if "schema" not in doc:
        out.append(Finding("schema-missing", "$.schema", "the document has no `schema`"))
    else:
        s = doc["schema"]
        if isinstance(s, str) and not isinstance(s, NonFinite):
            out.append(Finding("schema-string", "$.schema", "%s is a string: `schema` is an integer" % q(s)))
        elif is_int(s) and abs(s) <= MAX_INT and s != reg["schema"]:
            out.append(Finding("schema-unknown", "$.schema", "the schema %d is not the one of %s (%d)" % (s, reg["kind"], reg["schema"])))
        elif not is_int(s) and not isinstance(s, (Flt, NonFinite)):
            out.append(Finding("type-wrong", "$.schema", "`schema` is an integer"))
    if "kind" not in doc:
        out.append(Finding("kind-missing", "$.kind", "the document has no `kind`"))
    else:
        k = doc["kind"]
        if not isinstance(k, str) or isinstance(k, NonFinite):
            out.append(Finding("type-wrong", "$.kind", "`kind` is a string"))
        elif k != reg["kind"]:
            out.append(Finding("kind-wrong", "$.kind", "%s is not %s" % (q(k), q(reg["kind"]))))


def validate_doc(reg, text):
    """The findings of the document text against the parsed, well-formed registry reg (an empty list: valid)."""
    doc, out = checked_parse(text)
    if doc is None and out:
        return out
    if not isinstance(doc, dict):
        return [Finding("not-an-object", "$", "the document is %s, not one JSON object" % type_name(doc))]
    markers(doc, reg, out)
    try:
        walk(doc, reg["document"], reg["document"].get("$defs", {}), "$", out, top=True)
    except RecursionError:
        out.append(Finding("too-deep", "$", "the document is nested too deeply"))
    return out


def validate(kind_file, text):
    """The findings of the document text (str or bytes) against the registry file kind_file: [] when it is valid. A registry file that is not
    well formed raises RegistryError. This is what a writer calls before it prints (R-J9)."""
    reg, fs = load_registry(kind_file)
    if reg is None:
        raise RegistryError(kind_file, fs)
    return validate_doc(reg, text)


# ---- the command line -----------------------------------------------------------------------------------------------------

USAGE = "usage: jsonkind.py check | check FILE|- | validate KIND FILE|-"


def say(*a):
    print("jsonkind: " + " ".join(a), file=sys.stderr)


def read_input(name):
    if name == "-":
        return sys.stdin.buffer.read()
    with open(name, "rb") as f:
        return f.read()


def report(findings, label):
    for f in findings[:MAX_FINDINGS]:
        print(f.line(label), file=sys.stderr)
    if len(findings) > MAX_FINDINGS:
        print("%s: and %d more findings" % (label, len(findings) - MAX_FINDINGS), file=sys.stderr)


def main(argv):
    try:
        if argv == ["check"]:
            fs = check_dir()
            report(fs, "lib/kinds")
            if not fs:
                print("ok: %d registry files in %s" % (len(kind_names()), KINDS_DIR))
            return 1 if fs else 0
        if len(argv) == 2 and argv[0] == "check":
            reg, fs = check_text(read_input(argv[1]))
            report(fs, argv[1])
            return 1 if fs else 0
        if len(argv) == 3 and argv[0] == "validate":
            kind, name = argv[1], argv[2]
            if not KIND_RE.match(kind) or not os.path.isfile(registry_path(kind)):
                say("no kind %s (the kinds: %s)" % (q(kind), " ".join(kind_names()) or "none"))
                return 2
            reg, fs = load_registry(registry_path(kind))
            if reg is None:
                report(fs, "%s.json" % kind)
                say("the registry file of %s is not well formed" % kind)
                return 2
            fs = validate_doc(reg, read_input(name))
            report(fs, name)
            return 1 if fs else 0
    except OSError as e:
        say("cannot read %s: %s" % (q(argv[-1]), e.strerror or "error"))
        return 2
    print(USAGE, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
