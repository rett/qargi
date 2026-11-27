#!/usr/bin/env python3
"""The static lint of the JSON kinds: lib/kinds/*.json against the fixtures of tests/fixtures/json/ (design J1, section 5.3). It fails when

  1. a file of lib/kinds/ breaks the registry format, or two files name the same kind;
  2. a fixture marked valid does not validate against the live registry, one marked invalid validates or fails by another rule than the one named,
     a fixture breaks an `x-open` enum (a word outside it is no break), or a file the test makes (the minimal and the unknown-field fixtures, the broken files, cases.json, rules.json) differs from what it makes now;
  3. a kind has no v<schema> directory, a rule that applies to the kind has no broken file, or a file of the directory is in no cases.json;
  4. lib/kinds/KIND.json differs from the frozen KIND/vN/registry.json by more than R-J3 allows (a field removed or renamed, a type changed, an enum
     word lost, added to a closed enum, or a null added to any enum, a new entry in `required`, a changed pattern or constant: the fix is a new integer and a new vN directory);
  5. a field of the live registry appears in no valid fixture;
  6. a frozen registry.json differs from the same file at the last release tag (skipped, with one line, where there is no repository history or no tag);
  7. lib/kinds/MANIFEST.json (each kind with its status, schema and the sha256 of its registry file: `python3 lib/jsonkind.py manifest`) is missing or is not
     what the registry files make now, or a file of lib/kinds/ is marked export-ignore, so the release archive would not hold it.

A kind whose `status` is draft is held to point 1 only (and to the rules text of point 2): it has no fixtures, no frozen copy and no case file until it is pinned.

The fixtures are plain files: valid.json is the real output of the scenario of tests/fixtures/json/scenario.sh (the machine's own values replaced by
fixed ones); the other files are made from the valid ones by this file. `--regen` runs the scenario and writes them, `--regen --check` runs it and says
whether the files in the tree are what it makes now (it needs a checkout outside any run directory), `--freeze` copies the live registry files over the
frozen ones (once, at the pin). `--self-test` copies the tree to a scratch directory, breaks it in turn and expects the lint to fail by the right point.
Offline; a scratch home; no fixed sleep.
Run: python3 tests/test_json_registry.py [--root DIR] | --self-test | --regen [--tool DIR] [--check] [--keep-raw DIR] | --freeze"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import argparse, copy, importlib.util, json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.abspath(__file__)
DEFAULT_ROOT = os.path.dirname(HERE)
FIX = os.path.join("tests", "fixtures", "json")
PREFIX_BASE = "qargi-refusal/"
UNKNOWN_FIELD = "x_unknown_field_a_reader_ignores"
FIXED_WORKTREE = "0123456789abcdef"
SCRATCH_LENGTH = 64     # the length of the directory the scenario makes its scratch directory in (regen)
RELEASE_TAG = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")

# The rules of the broken files (design 5.2): id, the sentence, who must reject it (`both`: a reader and qargi's own validator; `writer`: qargi's validator
# and lint, a reader's parser may not see it), and what the kind needs to have a case (None: every kind).
RULES = [
    ("not-an-object", "the document is an array", "both", None),
    ("truncated", "the text ends before the object closes", "both", None),
    ("two-documents", "a second object follows the first", "both", None),
    ("schema-missing", "no `schema`", "both", None),
    ("schema-string", "`schema` is the string \"1\"", "both", None),
    ("schema-unknown", "`schema` is one above the pinned number", "both", None),
    ("kind-missing", "no `kind`", "both", None),
    ("kind-wrong", "`kind` names another registered kind", "both", None),
    ("required-missing", "one required field removed", "both", None),
    ("type-wrong", "a string field holds an object", "both", None),
    ("integer-string", "an integer field written as a string", "both", "integer"),
    ("enum-unknown", "a word outside a closed enum", "both", "enum"),
    ("null-not-allowed", "null in a field that is not nullable", "both", None),
    ("pattern-mismatch", "a string that does not match its pattern", "both", "pattern"),
    ("schema-float", "`schema` written as 1.0", "writer", None),
    ("integer-float", "an integer field written with a fraction (3.0)", "writer", "integer"),
    ("integer-range", "an integer field of 9007199254740992", "writer", "integer"),
    ("non-finite", "an integer field written as NaN", "writer", "integer"),
    ("duplicate-key", "a key written twice", "writer", None),
    ("prefix-missing", "the line has no `qargi-refusal/1 ` prefix", "both", "line"),
    ("prefix-number-differs", "the number in the prefix is not the `schema` of the object", "both", "line"),
]
RULE_IDS = [r[0] for r in RULES]

# The raw outputs of scenario.sh that each valid file of a kind is made from (the file name in the scenario's output directory).
GOLDEN = {
    "qargi-marshal-status": {"valid.json": "status.local.json", "valid-name.json": "status.local-name.json", "valid-refs.json": "status.refs.json"},
    "qargi-marshal-check": {"valid.json": "check.local.json", "valid-name.json": "check.local-name.json", "valid-yours.json": "check.local-yours.json",
                            "valid-refs-name.json": "check.refs-name.json", "valid-refs.json": "check.refs.json", "valid-successor.json": "check.local-successor.json"},
    "qargi-handoff": {"valid.json": "handoff.local.json", "valid-truncated.json": "handoff.local-truncated.json", "valid-refs.json": "handoff.refs.json"},
    "qargi-refusal": {"valid.json": "refusal.held"},
}


def load_module(root, name):
    spec = importlib.util.spec_from_file_location(name + "_" + str(abs(hash(root))), os.path.join(root, "lib", name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


# ---- shapes: types, references, the paths of a registry ---------------------------------------------------------------------------

def types_of(node):
    t = node.get("type")
    return set() if t is None else ({t} if isinstance(t, str) else set(t))


def resolve(node, defs):
    while isinstance(node, dict) and "$ref" in node:
        node = defs[node["$ref"].rsplit("/", 1)[1]]
    return node


def children(node, defs):
    """[(step, child node)] of a resolved shape node: a property name, "[]" for an item, "{}" for the value of a map."""
    out = [(k, v) for k, v in (node.get("properties") or {}).items()]
    if isinstance(node.get("items"), dict):
        out.append(("[]", node["items"]))
    if isinstance(node.get("additionalProperties"), dict):
        out.append(("{}", node["additionalProperties"]))
    return out


def registry_paths(reg):
    """The set of every field path of the live registry's document: ('features', '[]', 'lead', 'id'); a node that is a reference is followed, and a
    reference that leads back to itself is followed once."""
    defs = reg["document"].get("$defs", {})
    seen = set()

    def walk(node, path, trail):
        node = resolve(node, defs)
        if id(node) in trail:
            return
        for step, child in children(node, defs):
            p = path + (step,)
            if step == "[]" and not children(resolve(child, defs), defs):      # an item with no fields of its own: the array says it
                continue
            seen.add(p)
            walk(child, p, trail | {id(node)})
    walk(reg["document"], (), frozenset())
    return seen


def value_paths(reg, doc):
    """The registry paths that this document holds (a key present, even with the value null)."""
    defs = reg["document"].get("$defs", {})
    seen = set()

    def walk(v, node, path):
        node = resolve(node, defs)
        if isinstance(v, dict):
            props = node.get("properties") or {}
            extra = node.get("additionalProperties")
            for k, x in v.items():
                if k in props:
                    seen.add(path + (k,))
                    walk(x, props[k], path + (k,))
                elif isinstance(extra, dict):
                    seen.add(path + ("{}",))
                    walk(x, extra, path + ("{}",))
        elif isinstance(v, list) and isinstance(node.get("items"), dict):
            for x in v:
                seen.add(path + ("[]",))
                walk(x, node["items"], path + ("[]",))
    walk(doc, reg["document"], ())
    return seen


def sites(reg, doc):
    """(path, node, value) of every value of doc that the registry shapes, depth first, the markers left out: where a broken file can break the document."""
    defs = reg["document"].get("$defs", {})
    out = []

    def walk(v, node, path):
        node = resolve(node, defs)
        out.append((path, node, v))
        if isinstance(v, dict):
            props = node.get("properties") or {}
            extra = node.get("additionalProperties")
            for k, x in v.items():
                if len(path) == 0 and k in ("schema", "kind"):
                    continue
                if k in props:
                    walk(x, props[k], path + (k,))
                elif isinstance(extra, dict):
                    walk(x, extra, path + (k,))
        elif isinstance(v, list) and isinstance(node.get("items"), dict):
            for i, x in enumerate(v):
                walk(x, node["items"], path + (i,))
    walk(doc, reg["document"], ())
    return out


def set_at(doc, path, value):
    for k in path[:-1]:
        doc = doc[k]
    doc[path[-1]] = value


# ---- the files made from a valid one -----------------------------------------------------------------------------------------------

def body_text(doc, stderr):
    return json.dumps(doc, separators=(",", ":")) if stderr else json.dumps(doc, indent=1) + "\n"


def file_text(body, stderr, number=1):
    """A fixture file: a document as the verb prints it, or for the line of standard error the prefix, the object and the end of the line."""
    return "%s%d %s\n" % (PREFIX_BASE, number, body.rstrip("\n")) if stderr else body


def minimal(node, v, defs, top=False):
    """The document with only the required fields; a nullable required field is null; an array keeps its first item."""
    node = resolve(node, defs)
    if isinstance(v, dict):
        req = node.get("required") or []
        props = node.get("properties") or {}
        extra = node.get("additionalProperties")
        out = {}
        for k, x in v.items():
            if k in props and k in req:
                kid = resolve(props[k], defs)
                nullable = "null" in types_of(kid) or (None in (kid.get("enum") or [])) or kid.get("x-reserved")
                out[k] = None if nullable and not (top and k in ("schema", "kind")) else minimal(props[k], x, defs)
            elif k not in props and isinstance(extra, dict):
                out[k] = minimal(extra, x, defs)
        return out
    if isinstance(v, list) and isinstance(node.get("items"), dict):
        return [minimal(node["items"], x, defs) for x in v[:1]]
    return v


def with_unknown(node, v, defs):
    """The document with a field the registry does not name in every object that has named fields."""
    node = resolve(node, defs)
    if isinstance(v, dict):
        props = node.get("properties") or {}
        extra = node.get("additionalProperties")
        out = {k: (with_unknown(props[k], x, defs) if k in props else (with_unknown(extra, x, defs) if isinstance(extra, dict) else x)) for k, x in v.items()}
        if props:
            out[UNKNOWN_FIELD] = "a reader ignores a field it does not know"
        return out
    if isinstance(v, list) and isinstance(node.get("items"), dict):
        return [with_unknown(node["items"], x, defs) for x in v]
    return v


def other_kind(kind, kinds):
    rest = [k for k in sorted(kinds) if k != kind]
    return rest[0] if rest else "qargi-other"


def literal(doc, path, lit, stderr):
    """The text of doc with the value at path replaced by the literal text lit (a number JSON has no way to write from a Python value)."""
    d = copy.deepcopy(doc)
    set_at(d, path, "@@LITERAL@@")
    return body_text(d, stderr).replace('"@@LITERAL@@"', lit)


def int_site(reg, doc):
    for path, node, v in sites(reg, doc):
        if path and "integer" in types_of(node) and type(v) is int and "const" not in node:
            return path, v
    return None


def broken(kind, reg, valid, kinds, rule):
    """The text of the broken file of rule, made from the valid document, or None when the kind has no place to break for that rule."""
    stderr = reg["stream"] == "stderr"
    doc = copy.deepcopy(valid)
    top_req = [k for k in reg["document"].get("required", []) if k not in ("schema", "kind")]
    props = reg["document"]["properties"]
    plain = body_text(valid, stderr)
    if rule == "not-an-object":
        return file_text(("[" + body_text(valid, True) + "]") if stderr else (json.dumps([valid], indent=1) + "\n"), stderr)
    if rule == "truncated":
        return file_text(plain.rstrip("\n")[:-1], stderr)
    if rule == "two-documents":
        return file_text(plain.rstrip("\n") + (" " if stderr else "\n") + body_text(valid, True), stderr)
    if rule in ("schema-missing", "kind-missing"):
        del doc[rule.split("-")[0]]
        return file_text(body_text(doc, stderr), stderr)
    if rule == "schema-string":
        doc["schema"] = str(doc["schema"])
        return file_text(body_text(doc, stderr), stderr)
    if rule == "schema-unknown":
        doc["schema"] += 1
        return file_text(body_text(doc, stderr), stderr, number=doc["schema"])
    if rule == "kind-wrong":
        doc["kind"] = other_kind(kind, kinds)
        return file_text(body_text(doc, stderr), stderr)
    if rule == "required-missing":
        del doc[top_req[0]]
        return file_text(body_text(doc, stderr), stderr)
    if rule == "type-wrong":
        key = next((k for k in top_req if types_of(props[k]) == {"string"}), None)
        if key is None:
            return None
        doc[key] = {}
        return file_text(body_text(doc, stderr), stderr)
    if rule == "null-not-allowed":
        key = next((k for k in top_req if "null" not in types_of(resolve(props[k], reg["document"].get("$defs", {}))) and None not in (props[k].get("enum") or [])), None)
        if key is None:
            return None
        doc[key] = None
        return file_text(body_text(doc, stderr), stderr)
    if rule in ("integer-string", "integer-float", "integer-range", "non-finite"):
        site = int_site(reg, doc)
        if site is None:
            return None
        path, v = site
        if rule == "integer-string":
            set_at(doc, path, str(v))
            return file_text(body_text(doc, stderr), stderr)
        lit = {"integer-float": "%d.0" % v, "integer-range": "9007199254740992", "non-finite": "NaN"}[rule]
        return file_text(literal(doc, path, lit, stderr), stderr)
    if rule == "schema-float":
        return file_text(literal(doc, ("schema",), "%d.0" % doc["schema"], stderr), stderr)
    if rule == "enum-unknown":
        for path, node, v in sites(reg, doc):      # a closed enum only: a reader treats a word outside an x-open enum as `unknown`, it is no break
            if path and "enum" in node and isinstance(v, str) and "const" not in node and not node.get("x-open"):
                set_at(doc, path, "not-a-listed-word")
                return file_text(body_text(doc, stderr), stderr)
        return None
    if rule == "pattern-mismatch":
        for path, node, v in sites(reg, doc):
            if path and "pattern" in node and isinstance(v, str):
                set_at(doc, path, "!")
                return file_text(body_text(doc, stderr), stderr)
        return None
    if rule == "duplicate-key":
        marker = '"kind":"%s"' % kind if stderr else '"kind": "%s"' % kind
        return file_text(plain.replace(marker, marker + ("," if stderr else ",\n ") + marker, 1), stderr)
    if rule == "prefix-missing":
        return plain.rstrip("\n") + "\n" if stderr else None
    if rule == "prefix-number-differs":
        return file_text(plain, stderr, number=doc["schema"] + 1) if stderr else None
    raise AssertionError(rule)


def derived_files(kind, reg, valid_docs):
    """{name relative to KIND/vN: text} of every file made from the valid ones: valid-minimal, valid-unknown-field, the broken files, cases.json."""
    stderr = reg["stream"] == "stderr"
    defs = reg["document"].get("$defs", {})
    valid = valid_docs["valid.json"]
    out = {"valid-minimal.json": file_text(body_text(minimal(reg["document"], valid, defs, top=True), stderr), stderr),
           "valid-unknown-field.json": file_text(body_text(with_unknown(reg["document"], valid, defs), stderr), stderr)}
    cases = [{"file": n, "expect": "valid", "rule": None, "applies": "both"} for n in sorted(valid_docs, key=lambda n: (n != "valid.json", n))]
    cases += [{"file": "valid-minimal.json", "expect": "valid", "rule": None, "applies": "both"},
              {"file": "valid-unknown-field.json", "expect": "valid", "rule": None, "applies": "both"}]
    for rule, _, applies, _ in RULES:
        text = broken(kind, reg, valid, KINDS_SEEN, rule)
        if text is None:
            continue
        out["broken/%s.json" % rule] = text
        cases.append({"file": "broken/%s.json" % rule, "expect": "invalid", "rule": rule, "applies": applies})
    out["cases.json"] = json.dumps(cases, indent=1) + "\n"
    return out


KINDS_SEEN = []        # the kinds of the registry directory the lint reads (for the `kind-wrong` file)


def rules_text():
    return json.dumps({"rules": [{"id": i, "sentence": s, "applies": a, "needs": n} for i, s, a, n in RULES]}, indent=1) + "\n"


# ---- the verdict of the validator on a fixture ---------------------------------------------------------------------------------------

PATH_STEP = re.compile(r'\.([A-Za-z_][A-Za-z0-9_-]*)|\[([0-9]+)\]|\[("(?:[^"\\]|\\.)*")\]')


def node_at(reg, path):
    """The shape node of the registry at the JSONPath-like path of a finding ($.gates[0].tier), references followed; None where the registry has no node."""
    defs = reg["document"].get("$defs", {})
    node, pos = reg["document"], 1
    while pos < len(path):
        m = PATH_STEP.match(path, pos)
        if not m:
            return None
        node = resolve(node, defs)
        if m.group(2) is not None:
            node = node.get("items")
        else:
            key = m.group(1) if m.group(1) is not None else json.loads(m.group(3))
            node = (node.get("properties") or {}).get(key, node.get("additionalProperties"))
        if not isinstance(node, dict):
            return None
        pos = m.end()
    return resolve(node, defs)


def open_enum_breaks(J, reg, text, stderr):
    """The paths where the document breaks an enum that the registry declares x-open: a fixture never does, because a word outside such an enum is not a break."""
    if stderr:
        text = text.split(" ", 1)[1] if text.startswith(PREFIX_BASE) else text
    out = []
    for f in J.validate_doc(reg, text):
        node = node_at(reg, f.path) if f.rule == "enum-unknown" else None
        if node and node.get("x-open"):
            out.append(f.path)
    return out


def findings_of(J, reg, text, stderr):
    """The rules the fixture breaks, in order: the line of standard error is first split into prefix and object."""
    if not stderr:
        return [f.rule for f in J.validate_doc(reg, text)]
    line = text[:-1] if text.endswith("\n") else text
    m = re.match(re.escape(PREFIX_BASE) + r"([0-9]+) ", line)
    if not m:
        return ["prefix-missing"]
    rest = line[m.end():]
    found = [f.rule for f in J.validate_doc(reg, rest)]
    doc, fs = J.checked_parse(rest)
    if not fs and isinstance(doc, dict) and J.is_int(doc.get("schema")) and doc["schema"] != int(m.group(1)):
        found.insert(0, "prefix-number-differs")
    return found


# ---- the additive comparison of two registry files (point 4) ---------------------------------------------------------------------------

def compare(frozen, live):
    """The reasons the live registry file is not the frozen one plus additions that R-J3 allows: a list of sentences, empty when it is."""
    out = []
    for k in ("registry", "kind", "schema", "status", "since", "stream", "history"):
        if frozen.get(k) != live.get(k):
            out.append("%s changed: %r is now %r" % (k, frozen.get(k), live.get(k)))
    lost = [v for v in frozen.get("verbs", []) if v not in live.get("verbs", [])]
    if lost:
        out.append("a verb was dropped: %s" % ", ".join(lost))
    fd, ld = frozen["document"].get("$defs", {}), live["document"].get("$defs", {})

    def node(a, b, path):
        a, b = resolve(a, fd), resolve(b, ld)
        where = "$" + "".join(("[]" if s == "[]" else ".{}" if s == "{}" else "." + s) for s in path)
        ta, tb = types_of(a), types_of(b)
        if ta != tb and not (a.get("x-reserved") and not ta):
            out.append("%s: the type changed from %s to %s" % (where, "/".join(sorted(ta)) or "none", "/".join(sorted(tb)) or "none"))
        for k in ("const", "pattern"):
            if a.get(k) != b.get(k):
                out.append("%s: %s changed from %r to %r" % (where, k, a.get(k), b.get(k)))
        if ("enum" in a) != ("enum" in b):
            out.append("%s: an enum was %s" % (where, "added" if "enum" in b else "removed"))
        elif "enum" in a:
            gone = [e for e in a["enum"] if e not in b["enum"]]
            new = [e for e in b["enum"] if e not in a["enum"]]
            if gone:
                out.append("%s: the enum lost %s" % (where, ", ".join(map(repr, gone))))
            if any(e is None for e in new):
                # null is not a word: a reader that was told the field is never null breaks on it, so it raises the integer even where the enum is x-open
                out.append("%s: the enum now allows null (a nullability change, whether or not the enum is x-open)" % where)
            words = [e for e in new if e is not None]
            if words and not a.get("x-open"):
                out.append("%s: the closed enum gained %s (a new word is additive only where the frozen registry declares x-open)" % (where, ", ".join(map(repr, words))))
        if set(a.get("required", [])) != set(b.get("required", [])):
            diff = set(b.get("required", [])) - set(a.get("required", []))
            back = set(a.get("required", [])) - set(b.get("required", []))
            if diff:
                out.append("%s: a new required entry: %s" % (where, ", ".join(sorted(diff))))
            if back:
                out.append("%s: a required field became optional: %s" % (where, ", ".join(sorted(back))))
        if a.get("x-ordered") and not b.get("x-ordered"):
            out.append("%s: the array lost x-ordered" % where)
        pa, pb = a.get("properties") or {}, b.get("properties") or {}
        for k in pa:
            if k not in pb:
                out.append("%s: the field %s was removed or renamed" % (where, k))
            else:
                node(pa[k], pb[k], path + (k,))
        for k in pb:
            if k not in pa and not (isinstance(pb[k], dict) and pb[k].get("x-since")):
                out.append("%s: the new field %s has no x-since (the version that added it)" % (where, k))
        for step in ("items", "additionalProperties"):
            if isinstance(a.get(step), dict) != isinstance(b.get(step), dict):
                out.append("%s: %s was %s" % (where, step, "added" if isinstance(b.get(step), dict) else "removed"))
            elif isinstance(a.get(step), dict):
                node(a[step], b[step], path + (("[]",) if step == "items" else ("{}",)))
    node(frozen["document"], live["document"], ())
    return out


# ---- git: the last release tag ---------------------------------------------------------------------------------------------------------

def git(root, *args):
    p = subprocess.run(["git", "-C", root] + list(args), capture_output=True, text=True)
    return (p.returncode, p.stdout)


def last_release_tag(root):
    rc, out = git(root, "tag", "--list", "--sort=-v:refname")
    if rc != 0:
        return None
    for t in out.split():
        if RELEASE_TAG.match(t):
            return t
    return None


# ---- the lint -----------------------------------------------------------------------------------------------------------------------------

class Lint:
    def __init__(self, root):
        self.root = os.path.abspath(root)
        self.problems = []          # (point, text)
        self.notes = []
        self.J = load_module(self.root, "jsonkind")
        self.kinds_dir = os.path.join(self.root, "lib", "kinds")
        self.fix = os.path.join(self.root, FIX)

    def fail(self, point, text):
        self.problems.append((point, text))

    def run(self):
        J = self.J
        for f in J.check_dir(self.kinds_dir):                                                                   # point 1
            self.fail(1, f.line())
        names = J.kind_names(self.kinds_dir)
        regs = {}
        for n in names:
            reg, fs = J.load_registry(os.path.join(self.kinds_dir, n + ".json"))
            if reg is not None:
                regs[n] = reg
        KINDS_SEEN[:] = sorted(n for n, r in regs.items() if r["status"] != "draft")      # the `kind-wrong` file names a pinned kind, as regen makes it (a draft has no fixtures)
        expected_rules = rules_text()
        if not os.path.isfile(os.path.join(self.fix, "rules.json")) or read(os.path.join(self.fix, "rules.json")) != expected_rules:
            self.fail(2, "%s/rules.json is not the list of rules of this test (python3 tests/test_json_registry.py --regen)" % FIX)
        for kind, reg in sorted(regs.items()):
            if reg["status"] == "draft":      # a draft is registered and may change: its fixtures, frozen copy and release check come with the pin
                self.notes.append("%s is a draft: points 3 to 5 wait for its pin" % kind)
                continue
            try:
                self.kind(kind, reg)
            except (KeyError, IndexError, TypeError, ValueError, AttributeError) as e:
                self.fail(2, "%s: the lint could not read the fixtures or the registry (%s: %s)" % (kind, type(e).__name__, e))
        self.release_tag(regs)
        self.manifest()
        return self.problems

    def manifest(self):
        """Point 7: the manifest is what the registry files make now, and the release archive (git archive of the tag) holds it and them."""
        J = self.J
        text, fs = J.manifest(self.kinds_dir)
        rel = "lib/kinds/" + J.MANIFEST_NAME
        if text is None:
            return                      # the registry files are not well formed: point 1 says which
        p = os.path.join(self.kinds_dir, J.MANIFEST_NAME)
        if not os.path.isfile(p):
            self.fail(7, "%s is missing (python3 lib/jsonkind.py manifest > MANIFEST.new && mv MANIFEST.new %s)" % (rel, rel))
        elif read(p) != text:
            self.fail(7, "%s is not what the registry files make now (python3 lib/jsonkind.py manifest > MANIFEST.new && mv MANIFEST.new %s)" % (rel, rel))
        rc, out = git(self.root, "rev-parse", "--show-toplevel")
        if rc != 0 or os.path.realpath(out.strip()) != os.path.realpath(self.root):
            self.notes.append("point 7: the export-ignore attribute was not read: %s is not the top of a git repository" % self.root)
            return
        names = ["lib/kinds/" + n for n in sorted(os.listdir(self.kinds_dir)) if n.endswith(".json")]
        rc, out = git(self.root, "check-attr", "export-ignore", "--", *names)
        for line in out.splitlines():
            name, _, value = line.rpartition(": export-ignore: ")
            if rc == 0 and value not in ("unspecified", "unset"):
                self.fail(7, "%s is marked export-ignore (%s): the release archive would not hold it" % (name, value))

    def kind(self, kind, reg):
        J = self.J
        stderr = reg["stream"] == "stderr"
        vdir = os.path.join(self.fix, kind, "v%d" % reg["schema"])
        rel = "%s/%s/v%d" % (FIX, kind, reg["schema"])
        if not os.path.isdir(vdir):                                                                              # point 3
            self.fail(3, "%s has no directory %s" % (kind, rel))
            return
        # the valid files, the made files, cases.json
        valid_files = sorted(n for n in os.listdir(vdir) if re.match(r"^valid(-[a-z0-9-]+)?\.json$", n) and n not in ("valid-minimal.json", "valid-unknown-field.json"))
        docs, parsed = {}, {}
        for n in valid_files:
            text = read(os.path.join(vdir, n))
            docs[n] = text
            obj, fs = J.checked_parse(text.split(" ", 1)[1] if stderr and text.startswith(PREFIX_BASE) else text)
            parsed[n] = obj
        if "valid.json" not in docs:
            self.fail(3, "%s: %s/valid.json is missing" % (kind, rel))
            return
        if any(parsed[n] is None for n in docs):
            for n in docs:
                if parsed[n] is None:
                    self.fail(2, "%s/%s: not JSON" % (rel, n))
            return
        made = derived_files(kind, reg, parsed)
        for name, text in sorted(made.items()):                                                                  # point 2: nothing is hand edited
            p = os.path.join(vdir, name)
            if not os.path.isfile(p):
                self.fail(3 if name.startswith("broken/") else 2, "%s/%s is missing (python3 tests/test_json_registry.py --regen)" % (rel, name))
            elif read(p) != text:
                self.fail(2, "%s/%s is not what the test makes from valid.json (python3 tests/test_json_registry.py --regen)" % (rel, name))
        for rule, _, _, needs in RULES:                                                                          # point 3: a rule that applies has a file
            if "broken/%s.json" % rule not in made and needs is None:
                self.fail(3, "%s: the rule %s has no broken file" % (kind, rule))
        try:
            cases = read_json(os.path.join(vdir, "cases.json"))
        except (OSError, ValueError):
            self.fail(3, "%s/cases.json is missing or not JSON" % rel)
            return
        listed = {c.get("file") for c in cases if isinstance(c, dict)}
        for dirpath, _, files in os.walk(vdir):
            for n in files:
                r = os.path.relpath(os.path.join(dirpath, n), vdir)
                if r not in listed and r not in ("registry.json", "cases.json"):
                    self.fail(3, "%s/%s is in no cases.json" % (rel, r))
        for c in cases:                                                                                          # point 2: each case against the live registry
            p = os.path.join(vdir, c["file"])
            if not os.path.isfile(p):
                self.fail(3, "%s lists %s, which does not exist" % (rel + "/cases.json", c["file"]))
                continue
            found = findings_of(J, reg, read(p), stderr)
            for where in open_enum_breaks(J, reg, read(p), stderr):
                self.fail(2, "%s/%s closes the x-open enum at %s: a word outside an x-open enum is not a break (a reader reads it as `unknown`)" % (rel, c["file"], where))
            if c["expect"] == "valid" and found:
                self.fail(2, "%s/%s is marked valid and breaks %s" % (rel, c["file"], ", ".join(found)))
            elif c["expect"] == "invalid":
                if not found:
                    self.fail(2, "%s/%s is marked invalid and validates" % (rel, c["file"]))
                elif set(found) != {c["rule"]}:
                    self.fail(2, "%s/%s is marked %s and breaks %s" % (rel, c["file"], c["rule"], ", ".join(found)))
        # point 4: the frozen copy against the live registry
        fp = os.path.join(vdir, "registry.json")
        if not os.path.isfile(fp):
            self.fail(4, "%s/registry.json is missing (python3 tests/test_json_registry.py --freeze at the pin)" % rel)
        else:
            frozen, fs = J.load_registry(fp)
            if frozen is None:
                self.fail(4, "%s/registry.json is not a well-formed registry file: %s" % (rel, "; ".join(f.line() for f in fs[:2])))
            else:
                for why in compare(frozen, reg):
                    self.fail(4, "%s: the live registry differs from %s/registry.json: %s (a new integer and a new v directory, not an edit)" % (kind, rel, why))
        # point 5: every field of the live registry is in some valid fixture
        seen = set()
        for n, d in parsed.items():
            seen |= value_paths(reg, d)
        for p in sorted(registry_paths(reg) - seen):
            self.fail(5, "%s: the field %s appears in no valid fixture" % (kind, "$" + "".join(("[]" if s == "[]" else ".{}" if s == "{}" else "." + s) for s in p)))

    def release_tag(self, regs):
        """Point 6: a frozen registry.json equals the file at the last release tag."""
        rc, out = git(self.root, "rev-parse", "--show-toplevel")
        if rc != 0 or os.path.realpath(out.strip()) != os.path.realpath(self.root):
            self.notes.append("point 6 skipped: %s is not the top of a git repository (no history here)" % self.root)
            return
        tag = last_release_tag(self.root)
        if tag is None:
            self.notes.append("point 6 skipped: the repository has no release tag (a shallow clone, or no tag fetched)")
            return
        rc, out = git(self.root, "ls-tree", "-r", "--name-only", tag, "--", FIX)
        files = [f for f in out.split("\n") if f.endswith("/registry.json")]
        if rc != 0 or not files:
            self.notes.append("point 6: the release %s has no frozen registry file: nothing to compare" % tag)
            return
        for f in files:
            rc, old = git(self.root, "show", "%s:%s" % (tag, f))
            p = os.path.join(self.root, f)
            if not os.path.isfile(p):
                self.fail(6, "%s was at the release %s and is gone" % (f, tag))
            elif rc != 0 or read(p) != old:
                self.fail(6, "%s differs from the file at the release %s: a frozen registry never changes after the pin" % (f, tag))
        self.notes.append("point 6: %d frozen registry file(s) equal the ones at the release %s" % (len(files), tag))


def lint_main(root):
    lint = Lint(root)
    problems = lint.run()
    for point, text in problems:
        print("FAIL point %d: %s" % (point, text))
    for n in lint.notes:
        print("note: " + n)
    if not problems:
        print("ok: %d kinds, every fixture, rule and registry file of %s/ is as the lint wants" % (len(KINDS_SEEN), FIX))
    return 1 if problems else 0


# ---- regeneration: the scenario -> the valid files -----------------------------------------------------------------------------------------

def normalise(value, ctx):
    """The machine's own values replaced by fixed ones: the scratch directory, the host and the user, the digest of a work tree."""
    scratch = [ctx["scratch"], os.path.realpath(ctx["scratch"])]

    def walk(v, key=None):
        if isinstance(v, dict):
            return {k: walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        if isinstance(v, str):
            if key == "host" and v == ctx["host"]:
                return "host"
            if key == "user" and v == ctx["user"]:
                return "user"
            if key == "worktree" and re.fullmatch(r"[0-9a-f]{16}", v):
                return FIXED_WORKTREE
            for s in scratch:
                v = v.replace(s, "/work")
        return v
    return walk(value)


def make_valid(kind, raw_text, ctx, reg):
    """The text of a valid file from the raw output of the scenario: the same JSON as the verb printed, with the machine's values replaced."""
    stderr = reg["stream"] == "stderr"
    line = raw_text.rstrip("\n")
    if stderr:
        assert line.startswith(PREFIX_BASE + "1 "), line[:40]
        doc = json.loads(line[len(PREFIX_BASE) + 2:])
        assert file_text(body_text(doc, True), True) == raw_text, "the dump of the contract line is not the line the verb printed"
    else:
        doc = json.loads(raw_text)
        assert body_text(doc, False) == raw_text, "the dump of the document is not the text the verb printed"
    return file_text(body_text(normalise(doc, ctx), stderr), stderr)


def regen(root, tool, check, keep=None):
    J = load_module(root, "jsonkind")
    regs = {}
    for n in J.kind_names(os.path.join(root, "lib", "kinds")):
        reg, _ = J.load_registry(os.path.join(root, "lib", "kinds", n + ".json"))
        if reg["status"] != "draft":      # a draft has no fixtures yet
            regs[n] = reg
    KINDS_SEEN[:] = sorted(regs)
    base = os.path.realpath(tempfile.mkdtemp(prefix="j."))
    raw = os.path.join(base, "raw")
    # the size cut of a handoff counts bytes, so the paths the scenario prints must have the same length wherever it runs: its scratch directory is
    # made inside a directory with a name padded to a fixed length
    pad = SCRATCH_LENGTH - len(base) - 1
    if pad < 1:
        print("the temporary directory %s is too long (%d characters of %d): set TMPDIR to a shorter one" % (base, len(base), SCRATCH_LENGTH - 2))
        shutil.rmtree(base, ignore_errors=True)
        return 1
    scratch = os.path.join(base, "p" * pad)
    os.makedirs(scratch)
    try:
        p = subprocess.run(["bash", os.path.join(tool, FIX, "scenario.sh"), raw], capture_output=True, text=True, env=dict(os.environ, TMPDIR=scratch))
        if p.returncode != 0:
            print("the scenario failed (exit %d): %s" % (p.returncode, (p.stdout + p.stderr)[-600:]))
            return 1
        if keep:
            shutil.copytree(raw, keep, dirs_exist_ok=True)     # the raw output, for tests/test_json_live.sh
        ctx = read_json(os.path.join(raw, "_context.json"))
        files = {os.path.join(FIX, "rules.json"): rules_text()}
        for kind, reg in regs.items():
            vdir = os.path.join(FIX, kind, "v%d" % reg["schema"])
            valid = {}
            for name, src in GOLDEN[kind].items():
                text = make_valid(kind, read(os.path.join(raw, src)), ctx, reg)
                files[os.path.join(vdir, name)] = text
                valid[name] = json.loads(text.split(" ", 1)[1] if reg["stream"] == "stderr" else text)
            for name, text in derived_files(kind, reg, valid).items():
                files[os.path.join(vdir, name)] = text
    finally:
        shutil.rmtree(base, ignore_errors=True)
    bad = 0
    for rel, text in sorted(files.items()):
        p = os.path.join(root, rel)
        if check:
            if not os.path.isfile(p) or read(p) != text:
                print("differs: " + rel)
                bad += 1
        else:
            write(p, text)
    if check:
        print("%d file(s) differ from what the scenario makes now" % bad if bad else "ok: %d files are what the scenario makes now" % len(files))
        return 1 if bad else 0
    print("wrote %d files under %s" % (len(files), FIX))
    return 0


def freeze(root):
    J = load_module(root, "jsonkind")
    for n in J.kind_names(os.path.join(root, "lib", "kinds")):
        reg, _ = J.load_registry(os.path.join(root, "lib", "kinds", n + ".json"))
        if reg["status"] == "draft":
            continue
        shutil.copyfile(os.path.join(root, "lib", "kinds", n + ".json"), os.path.join(root, FIX, n, "v%d" % reg["schema"], "registry.json"))
    print("froze the registry files")
    return 0


# ---- the self-test ------------------------------------------------------------------------------------------------------------------------

def strip_key(v, key):
    if isinstance(v, dict):
        v.pop(key, None)
        for x in v.values():
            strip_key(x, key)
    elif isinstance(v, list):
        for x in v:
            strip_key(x, key)


def self_test():
    """Each case copies the tree to a scratch directory (the validator, lib/kinds and the fixtures; a repository only where the case says so), breaks the
    copy in one way and runs this lint on it as a program: it must exit 1 and name the point (and the text) the break belongs to."""
    fails = 0
    tmp = tempfile.mkdtemp(prefix="json-registry-self.")
    env = dict(os.environ, GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")
    count = [0]

    def copy_tree():
        count[0] += 1
        dst = os.path.join(tmp, "t%d" % count[0])
        os.makedirs(os.path.join(dst, "lib"))
        shutil.copy(os.path.join(DEFAULT_ROOT, "lib", "jsonkind.py"), os.path.join(dst, "lib", "jsonkind.py"))
        shutil.copytree(os.path.join(DEFAULT_ROOT, "lib", "kinds"), os.path.join(dst, "lib", "kinds"))
        shutil.copytree(os.path.join(DEFAULT_ROOT, FIX), os.path.join(dst, FIX), ignore=shutil.ignore_patterns("scenario.sh"))
        return dst

    def lint(root):
        p = subprocess.run([sys.executable, "-B", SELF, "--root", root], capture_output=True, text=True, env=env)
        return p.returncode, p.stdout + p.stderr

    def expect(name, root, points, text=None, exact=False, absent=()):
        """The lint on root exits 1 and prints the points (all of them, or exactly them with exact), the text, and none of the points in absent;
        with no points it exits 0 and prints the text."""
        nonlocal fails
        rc, out = lint(root)
        got = sorted({int(m) for m in re.findall(r"^FAIL point ([0-9]+):", out, re.M)})
        if not points:
            good = rc == 0 and not got
        else:
            good = rc == 1 and (got == sorted(points) if exact else set(points) <= set(got)) and not set(absent) & set(got)
        good = good and (text is None or text in out)
        fails += 0 if good else 1
        print("%s self-test: %s (exit %d, points %s)" % ("ok  " if good else "FAIL", name, rc, got))
        if not good:
            print("     wanted points %s%s, text %r; got:\n%s" % (points, " exactly" if exact else "", text, "\n".join("     " + l for l in out.splitlines()[-12:])))

    def edit(root, kind, fn, remake=True):
        """fn changes the registry file of kind in the copy; the manifest is made again (point 7 is not what the case is about), unless remake is False."""
        p = os.path.join(root, "lib", "kinds", kind + ".json")
        reg = read_json(p)
        fn(reg)
        write(p, json.dumps(reg, indent=2) + "\n")
        if remake:
            K = load_module(root, "jsonkind")
            text, _ = K.manifest(os.path.join(root, "lib", "kinds"))
            if text is not None:
                write(os.path.join(root, "lib", "kinds", K.MANIFEST_NAME), text)

    def vdir(root, kind):
        return os.path.join(root, FIX, kind, "v%d" % read_json(os.path.join(root, "lib", "kinds", kind + ".json"))["schema"])

    def fixture(root, kind, name):
        return os.path.join(vdir(root, kind), name)

    try:
        expect("the tree as it is passes", copy_tree(), [])
        # point 4: what R-J2 raises the integer for, done to a live registry copy
        r = copy_tree()
        edit(r, "qargi-marshal-check", lambda g: (g["document"]["properties"].pop("warnings"), g["document"]["required"].remove("warnings")))
        expect("a field removed from a live registry copy fails point 4", r, [4], "the field warnings was removed or renamed")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["$defs"]["feature"]["required"].append("tasks"))
        expect("a name added to `required` fails point 4", r, [4], "a new required entry: tasks")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["$defs"]["feature"]["properties"]["ttl_minutes"].update(type="string"))
        expect("a type changed fails point 4", r, [4], "the type changed from integer to string")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["properties"]["backend"].update(enum=["local"]))
        expect("an enum word lost fails point 4", r, [4], "the enum lost 'refs'")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["properties"]["remote"].update(enum=g["document"]["properties"]["remote"]["enum"] + ["elsewhere"]))
        expect("a word added to a closed enum fails point 4", r, [4], "the closed enum gained 'elsewhere'")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["$defs"]["feature"]["properties"]["integrity"].update(enum=g["document"]["$defs"]["feature"]["properties"]["integrity"]["enum"] + ["fresh"]))
        expect("a word added to an x-open enum passes point 4", r, [], None)
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["$defs"]["feature"]["properties"]["integrity"].update(enum=g["document"]["$defs"]["feature"]["properties"]["integrity"]["enum"] + [None]))
        expect("a null added to an x-open enum fails point 4 as a nullability change", r, [4], "the enum now allows null", exact=True)
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["properties"]["remote"].update(enum=g["document"]["properties"]["remote"]["enum"] + [None]))
        expect("a null added to a closed enum fails point 4 as a nullability change", r, [4], "the enum now allows null")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["properties"].update(extra_field={"type": "string"}))
        expect("a new field without x-since fails point 4", r, [4], "the new field extra_field has no x-since")
        r = copy_tree()
        edit(r, "qargi-marshal-status", lambda g: g["document"]["properties"].update(extra_field={"type": "string", "x-since": "0.3.10"}))
        expect("a new optional field with x-since passes point 4 and fails point 5 until a fixture holds it", r, [5], "extra_field", exact=True)
        # points 1 to 3 and 5
        r = copy_tree()
        shutil.copy(os.path.join(r, "lib", "kinds", "qargi-refusal.json"), os.path.join(r, "lib", "kinds", "qargi-refusal-copy.json"))
        expect("two registry files of one kind fail point 1", r, [1], "kind-duplicate")
        r = copy_tree()
        p = fixture(r, "qargi-marshal-check", "valid.json")
        write(p, read(p).replace('"remote": "none"', '"remote": "maybe"'))
        expect("a valid fixture that does not validate fails point 2", r, [2], "is marked valid and breaks")
        r = copy_tree()
        write(fixture(r, "qargi-handoff", "broken/enum-unknown.json"), read(fixture(r, "qargi-handoff", "valid.json")))
        expect("a broken fixture that validates fails point 2", r, [2], "marked invalid and validates")
        r = copy_tree()
        v = read(fixture(r, "qargi-handoff", "valid.json"))
        assert '"tier": "' in v
        write(fixture(r, "qargi-handoff", "broken/enum-unknown.json"), re.sub(r'"tier": "[a-z]+"', '"tier": "not-a-listed-word"', v, count=1))
        expect("a broken fixture that closes an x-open enum fails point 2", r, [2], "closes the x-open enum at $.gates[0].tier")
        r = copy_tree()
        os.remove(fixture(r, "qargi-marshal-status", "broken/schema-missing.json"))
        expect("a rule with no broken file fails point 3", r, [3], "schema-missing")
        r = copy_tree()
        shutil.rmtree(vdir(r, "qargi-refusal"))
        expect("a kind with no v directory fails point 3", r, [3], "has no directory")
        r = copy_tree()
        for kind in os.listdir(os.path.join(r, FIX)):
            v = vdir(r, kind) if os.path.isfile(os.path.join(r, "lib", "kinds", kind + ".json")) else ""
            for n in (os.listdir(v) if os.path.isdir(v) else []):
                if n.startswith("valid") and n.endswith(".json") and '"signer"' in read(os.path.join(v, n)):
                    d = json.loads(read(os.path.join(v, n)))
                    strip_key(d, "signer")
                    write(os.path.join(v, n), json.dumps(d, indent=1) + "\n")
        expect("a field of the registry that no valid fixture holds fails point 5", r, [5], "the field $.features[].signer appears in no valid fixture")
        # point 6: a frozen copy edited in a scratch repository that has a tag
        r = copy_tree()
        for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@example.net", "commit", "-q", "-m", "pinned"], ["tag", "0.0.1"]):
            subprocess.run(["git", "-C", r] + args, check=True, capture_output=True, env=env)
        expect("a frozen registry equal to the one at the tag passes point 6", r, [], "equal the ones at the release 0.0.1")
        change = lambda g: g["document"]["properties"].update(added_after_the_pin={"type": "string", "x-since": "0.3.10"})
        edit(r, "qargi-marshal-check", change)
        fp = fixture(r, "qargi-marshal-check", "registry.json")
        frozen = read_json(fp)
        change(frozen)
        write(fp, json.dumps(frozen, indent=2) + "\n")
        expect("a frozen copy edited together with the live one is seen by the tag (point 6), not by point 4", r, [6], "differs from the file at the release 0.0.1", absent=(4,))
        expect("a tree with no repository passes, with point 6 skipped", copy_tree(), [], "point 6 skipped")
        # point 7: the manifest of the registry files
        r = copy_tree()
        edit(r, "qargi-refusal", lambda g: g.update(about=g["about"] + " More."), remake=False)
        expect("a registry file changed and the manifest not made again fails point 7", r, [7], "is not what the registry files make now", exact=True)
        r = copy_tree()
        os.remove(os.path.join(r, "lib", "kinds", "MANIFEST.json"))
        expect("a missing manifest fails point 7", r, [7], "MANIFEST.json is missing", exact=True)
        r = copy_tree()
        write(os.path.join(r, "lib", "kinds", "MANIFEST.json"), read(os.path.join(r, "lib", "kinds", "MANIFEST.json")).replace('"pinned"', '"draft"', 1))
        expect("a manifest edited by hand fails point 7", r, [7], "is not what the registry files make now", exact=True)
        r = copy_tree()
        write(os.path.join(r, ".gitattributes"), "lib/kinds/MANIFEST.json export-ignore\n")
        subprocess.run(["git", "-C", r, "init", "-q"], check=True, capture_output=True, env=env)
        expect("a manifest marked export-ignore fails point 7", r, [7], "the release archive would not hold it", exact=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("self-test: %s" % ("every break was found by the point it belongs to" if not fails else "%d unexpected result(s)" % fails))
    return 1 if fails else 0


def main(argv):
    ap = argparse.ArgumentParser(description="the static lint of lib/kinds against tests/fixtures/json")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="the tree to lint (default: this checkout)")
    ap.add_argument("--self-test", action="store_true", help="break a scratch copy of the tree in turn and expect the lint to fail by the right point")
    ap.add_argument("--regen", action="store_true", help="run the scenario and write the fixture files")
    ap.add_argument("--check", action="store_true", help="with --regen: write nothing, say whether the files are what the scenario makes now")
    ap.add_argument("--tool", default=None, help="with --regen: the checkout the scenario runs (default: --root; not inside a run directory)")
    ap.add_argument("--keep-raw", default=None, metavar="DIR", help="with --regen: also copy the raw output of the scenario to DIR (tests/test_json_live.sh validates it)")
    ap.add_argument("--freeze", action="store_true", help="copy the live registry files over the frozen ones (at the pin)")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    if a.regen:
        return regen(os.path.abspath(a.root), os.path.abspath(a.tool or a.root), a.check, os.path.abspath(a.keep_raw) if a.keep_raw else None)
    if a.freeze:
        return freeze(os.path.abspath(a.root))
    return lint_main(a.root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
