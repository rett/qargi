"""Pure campaign declaration v1: no configuration, source or lifecycle access.

decode(bytes) parses strict UTF-8 JSON, not a validated document. validate(value)
returns a fresh, normalized snapshot; canonicalize(value) returns its ASCII JSON
bytes with a final newline. Neither proves a transition or source existence.
transition(parent, child, rev=N) validates against the caller's actual parent
(None for create, N=1), returning the normalized child. The store must establish
that parent and N=parent revision+1; this module does not establish history.
findings(value) returns deterministic warnings only. constants() states authority.

All refusals raise Invalid with code, path and details['path']; messages and paths
are ASCII safe for text output and never include supplied free text. Codes are
invalid-json, duplicate-json-key, schema, version, bounds, identity, reference,
graph-pin, transition, no-change. Errors are first-error, warnings are separate.

Budgets: decode limits spec bytes to 512 KiB. Depth counts the root as 1; values
include object keys. All APIs bound the tree before copying/encoding it. The
256 KiB budget applies to the canonical *revision envelope*, not input bytes:
snapshots reserve the maximum v1 envelope overhead (9-digit rev, digest parent).
The store must use the documented envelope and still check its final bytes.
No floats are supported: v1 has only integer numeric fields. Text is preserved
exactly (no Unicode, whitespace or date normalization). JSON integer spellings
use Python's integer semantics, including -0 becoming 0.
Free text limits are UTF-8 bytes: label/by/at and opaque pins 128, locator/ref/
basis and graph relation IDs 1024, objective 4096, requirement text 2048.
Grammar fields have their own finite bounds (birth slugs 48, project names 64).
Semantic link identity is (purpose, target), independent of digest/attribution.
"""
import json
import re
import unicodedata

from backlog_graph import DIGEST, SLUG, Invalid as GraphInvalid, at, scalar_words, typed_ref

MAX_SPEC_BYTES = 512 * 1024
MAX_REVISION_BYTES = 256 * 1024
MAX_DEPTH = 16
MAX_VALUES = 32768
MAX_REV = 999999999
MAX_EPOCH = 253402300799
MAX_ATTEMPT = 256
LIMITS = {"participants": 32, "requirements": 128, "work": 128, "coordination": 256}
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
BIRTH = re.compile(r"r([1-9][0-9]{0,8}):(.+)")
PROJECT = re.compile(r"[a-z][a-z0-9-]{0,63}")
PURPOSES = ("prepared-request", "service-receipt", "delivered-output", "verified-snapshot",
            "source-review", "evaluation", "outcome", "release-plan", "prior-declaration")


def _encode(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                       allow_nan=False) + "\n").encode("ascii")


# {} is replaced by the actual canonical document (without its newline).
ENVELOPE_RESERVE = len(_encode(dict(format="campaign-revision", version=1, rev=MAX_REV,
                                   previous="sha256:" + "f" * 64, document={}))) - len(_encode({}))
MAX_DOCUMENT_BYTES = MAX_REVISION_BYTES - ENVELOPE_RESERVE


class Invalid(Exception):
    def __init__(self, code, message, path="$"):
        self.code = code
        self.path = path
        self.details = {"path": path}
        super().__init__(path + ": " + message)


def _need(ok, code, message, path):
    if not ok:
        raise Invalid(code, message, path)


def _tree(value, *, canonical_budget=False):
    """Iterative preflight, including cyclic/aliased caller-owned containers.

    Repeated aliases count repeatedly, matching their serialized allocation.
    Cycles reach the depth bound without recursive Python calls.
    """
    stack = [(value, 1)]
    count = 0
    encoded_size = 1  # final newline
    while stack:
        item, depth = stack.pop()
        count += 1
        _need(count <= MAX_VALUES and depth <= MAX_DEPTH, "bounds", "JSON tree budget exceeded", "$")
        kind = type(item)
        if kind is str:
            _need(len(item) <= 4096, "bounds", "string budget exceeded", "$")
            _need(all(not 0xD800 <= ord(c) <= 0xDFFF for c in item),
                  "schema", "strings must contain Unicode scalar values", "$")
            _need(len(item.encode("utf-8")) <= 4096, "bounds", "string budget exceeded", "$")
            _need(all(unicodedata.category(c) != "Cc" or c == "\n" for c in item),
                  "schema", "control character in string", "$")
            if canonical_budget:
                encoded_size += len(_encode(item)) - 1
        elif kind is dict:
            _need(len(item) * 2 + count + len(stack) <= MAX_VALUES,
                  "bounds", "JSON value budget exceeded", "$")
            for key, val in item.items():
                _need(type(key) is str, "schema", "object keys must be strings", "$")
                stack.extend(((key, depth + 1), (val, depth + 1)))
            encoded_size += 2 + max(0, len(item) - 1) + len(item)  # braces, commas, colons
        elif kind is list:
            _need(len(item) + count + len(stack) <= MAX_VALUES,
                  "bounds", "JSON value budget exceeded", "$")
            stack.extend((val, depth + 1) for val in item)
            encoded_size += 2 + max(0, len(item) - 1)
        elif kind is int:
            _need(abs(item) <= MAX_EPOCH, "bounds", "integer budget exceeded", "$")
            encoded_size += len(str(item))
        else:
            _need(item is None or kind is bool, "schema", "unsupported JSON value type", "$")
            encoded_size += 4 if item is None or item is True else 5
        if canonical_budget:
            _need(encoded_size <= MAX_DOCUMENT_BYTES, "bounds", "canonical revision byte budget exceeded", "$")


def decode(raw):
    """Parse only bytes; reject duplicates at every depth and noninteger numbers.

    A lexical nesting check bounds decoder recursion before allocation; the raw
    byte limit bounds parser allocation before the exact tree/value preflight.
    """
    _need(type(raw) is bytes, "invalid-json", "input must be UTF-8 bytes", "$")
    _need(len(raw) <= MAX_SPEC_BYTES, "bounds", "spec byte budget exceeded", "$")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeError:
        raise Invalid("invalid-json", "input is not strict UTF-8") from None
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in "[{":
            depth += 1
            _need(depth <= MAX_DEPTH, "bounds", "JSON depth budget exceeded", "$")
        elif char in "]}":
            depth -= 1

    def pairs(items):
        obj = {}
        for key, value in items:
            _need(key not in obj, "duplicate-json-key", "duplicate JSON key", "$")
            obj[key] = value
        return obj

    def integer(token):
        _need(len(token.lstrip("-")) <= 12, "bounds", "integer budget exceeded", "$")
        return int(token)

    def noninteger(_):
        raise Invalid("schema", "v1 numbers must be integers")

    def constant(_):
        raise Invalid("invalid-json", "non-JSON numeric constant")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_int=integer,
                           parse_float=noninteger, parse_constant=constant)
    except (ValueError, RecursionError):
        raise Invalid("invalid-json", "malformed JSON") from None
    _tree(value)
    return value


def _fields(value, names, path):
    _need(type(value) is dict and set(value) == set(names.split()),
          "schema", "expected exactly fields: " + names, path)


def _text(value, limit, path, multiline=False):
    _need(type(value) is str, "schema", "expected text", path)
    _need(len(value.encode("utf-8")) <= limit, "bounds", "text byte budget exceeded", path)
    _need(multiline or "\n" not in value, "schema", "newline not allowed", path)
    try:
        scalar_words(value)
    except GraphInvalid:
        raise Invalid("schema", "text must contain words and Unicode scalar values", path) from None


def _match(value, pattern, path, code="schema"):
    _need(type(value) is str and pattern.fullmatch(value) is not None,
          code, "invalid identifier or reference grammar", path)


def _uuid(value, path):
    _match(value, UUID, path, "identity")
    _need(value != "00000000-0000-0000-0000-000000000000", "identity", "nil UUID refused", path)


def _birth(value, path):
    _match(value, BIRTH, path, "identity")
    slug = value.partition(":")[2]
    _need(len(slug) <= 48 and SLUG.fullmatch(slug) is not None,
          "identity", "invalid birth ID slug", path)


def _integer(value, low, high, path):
    _need(type(value) is int, "schema", "expected integer (not boolean)", path)
    _need(low <= value <= high, "bounds", "integer out of range", path)


def _enum(value, choices, path):
    _need(type(value) is str and value in choices, "schema", "unexpected enum value", path)


def _date(value, path):
    _text(value, 128, path)
    try:
        at(value)
    except GraphInvalid:
        raise Invalid("schema", "expected valid graph ISO8601 date or timestamp", path) from None


def _attribution(value, path):
    _text(value["by"], 128, path + ".by")
    _date(value["at"], path + ".at")


def _typed(value, path):
    _text(value, 1024, path)
    try:
        typed_ref(value)
    except GraphInvalid:
        raise Invalid("schema", "invalid graph typed reference", path) from None


def _array(value, limit, path):
    _need(type(value) is list, "schema", "expected array", path)
    _need(len(value) <= limit, "bounds", "array budget exceeded", path)


def _source(source, participant, path):
    if source is None:
        return
    _fields(source, "kind ref pin", path)
    kind = source["kind"]
    _enum(kind, ("backlog", "feature", "external"), path + ".kind")
    if kind == "external":
        _text(source["ref"], 1024, path + ".ref")
    else:
        _typed(source["ref"], path + ".ref")
        _need(source["ref"].startswith(kind + ":"), "schema", "source kind/ref mismatch", path)
        _need(participant["qargi_project"] is not None,
              "reference", "typed source requires declared project binding", path)
    pin = source["pin"]
    if pin is not None:
        _fields(pin, "type value", path + ".pin")
        _enum(pin["type"], ("item-digest", "file-digest", "commit", "opaque"), path + ".pin.type")
        permitted = {"item-digest": ("backlog",), "file-digest": ("backlog", "external"),
                     "commit": ("backlog", "feature", "external"), "opaque": ("external",)}
        _need(kind in permitted[pin["type"]], "schema", "pin type incompatible with source kind", path)
        if pin["type"] in ("item-digest", "file-digest"):
            _match(pin["value"], DIGEST, path + ".pin.value")
        elif pin["type"] == "commit":
            _match(pin["value"], re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})"), path + ".pin.value")
        else:
            _text(pin["value"], 128, path + ".pin.value")


def _link(link, path):
    _fields(link, "purpose target digest status by at", path)
    _enum(link["purpose"], PURPOSES, path + ".purpose")
    _enum(link["status"], ("unresolved",), path + ".status")
    _attribution(link, path)
    if link["digest"] is not None:
        _match(link["digest"], DIGEST, path + ".digest")
    target = link["target"]
    _need(type(target) is dict, "schema", "target must be object", path + ".target")
    if target.get("kind") == "ref":
        _fields(target, "kind ref", path + ".target")
        _text(target["ref"], 1024, path + ".target.ref")
    else:
        _fields(target, "kind run prepared_identity prepared_epoch attempt", path + ".target")
        _enum(target["kind"], ("qargi-attempt",), path + ".target.kind")
        _match(target["run"], re.compile(r"qargi\.[A-Za-z0-9]{6}"), path + ".target.run")
        if target["prepared_identity"] is not None:
            _match(target["prepared_identity"], re.compile(r"[0-9a-f]{32}"), path + ".target.prepared_identity")
        for key, low, high in (("prepared_epoch", 0, MAX_EPOCH), ("attempt", 1, MAX_ATTEMPT)):
            if target[key] is not None:
                _integer(target[key], low, high, path + ".target." + key)


def _graph_pin(pin, dependent, upstream, path):
    if pin is None:
        return
    _fields(pin, "graph relation kind from to status verification", path)
    _fields(pin["graph"], "locator digest", path + ".graph")
    _text(pin["graph"]["locator"], 1024, path + ".graph.locator")
    _match(pin["graph"]["digest"], DIGEST, path + ".graph.digest")
    _match(pin["relation"], SLUG, path + ".relation")
    _need(len(pin["relation"].encode("utf-8")) <= 1024, "bounds", "relation slug budget exceeded", path)
    _enum(pin["kind"], ("requires", "contains"), path + ".kind")
    _enum(pin["status"], ("proposed", "confirmed"), path + ".status")
    _enum(pin["verification"], ("unverified",), path + ".verification")
    for key in ("from", "to"):
        _typed(pin[key], path + "." + key)
    _need(dependent["participant"] == upstream["participant"],
          "graph-pin", "graph endpoints require same participant", path)
    for key, work in (("from", dependent), ("to", upstream)):
        source = work["source"]
        _need(source is not None and source["kind"] in ("backlog", "feature")
              and source["ref"] == pin[key], "graph-pin", "graph endpoint/source mismatch", path)


def _id_order(ident):
    number, _, slug = ident[1:].partition(":")
    return int(number), slug


def validate(document):
    """Validate a supplied snapshot, returning a detached normalized copy.

    Structural validity permits past birth/design revisions; use transition for
    creation or changes. Entity omission only changes the current planning window.
    """
    _tree(document, canonical_budget=True)
    _fields(document, "format version campaign label objective continues participants requirements work coordination provenance", "$")
    _enum(document["format"], ("campaign",), "$.format")
    _need(type(document["version"]) is int and document["version"] == 1,
          "version", "version must be integer 1", "$.version")
    _uuid(document["campaign"], "$.campaign")
    _text(document["label"], 128, "$.label")
    _text(document["objective"], 4096, "$.objective", multiline=True)
    predecessor = document["continues"]
    if predecessor is not None:
        _fields(predecessor, "campaign revision", "$.continues")
        _uuid(predecessor["campaign"], "$.continues.campaign")
        _match(predecessor["revision"], DIGEST, "$.continues.revision")
    for key, limit in LIMITS.items():
        _array(document[key], limit, "$." + key)
    participants = {}
    for i, p in enumerate(document["participants"]):
        path = "$.participants[%d]" % i
        _fields(p, "id label locator qargi_project", path)
        _uuid(p["id"], path + ".id")
        _need(p["id"] not in participants, "identity", "duplicate participant UUID", path)
        _text(p["label"], 128, path + ".label")
        if p["locator"] is not None:
            _text(p["locator"], 1024, path + ".locator")
        if p["qargi_project"] is not None:
            _match(p["qargi_project"], PROJECT, path + ".qargi_project")
        participants[p["id"]] = p
    entities = {}
    for group in ("requirements", "work", "coordination"):
        for i, entity in enumerate(document[group]):
            path = "$.%s[%d]" % (group, i)
            _need(type(entity) is dict, "schema", "entity must be object", path)
            _birth(entity.get("id"), path + ".id")
            _need(entity["id"] not in entities, "identity", "duplicate campaign-owned ID", path)
            entities[entity["id"]] = group
    requirements = {r["id"] for r in document["requirements"]}
    for i, r in enumerate(document["requirements"]):
        path = "$.requirements[%d]" % i
        _fields(r, "id text state", path)
        _text(r["text"], 2048, path + ".text", multiline=True)
        _enum(r["state"], ("active", "withdrawn"), path + ".state")
    work = {}
    for i, w in enumerate(document["work"]):
        path = "$.work[%d]" % i
        _fields(w, "id participant state requirements source design links", path)
        _uuid(w["participant"], path + ".participant")
        _need(w["participant"] in participants, "reference", "undeclared participant", path)
        _enum(w["state"], ("active", "withdrawn"), path + ".state")
        _array(w["requirements"], LIMITS["requirements"], path + ".requirements")
        seen = set()
        for ident in w["requirements"]:
            _birth(ident, path + ".requirements")
            _need(ident in requirements, "reference", "undeclared requirement", path)
            _need(ident not in seen, "reference", "duplicate requirement link", path)
            seen.add(ident)
        _source(w["source"], participants[w["participant"]], path + ".source")
        design = w["design"]
        if design is not None:
            _fields(design, "rev state ref by at", path + ".design")
            _integer(design["rev"], 1, MAX_REV, path + ".design.rev")
            _enum(design["state"], ("provisional", "settled"), path + ".design.state")
            _text(design["ref"], 1024, path + ".design.ref")
            _attribution(design, path + ".design")
        _array(w["links"], 32, path + ".links")
        semantics = set()
        for j, link in enumerate(w["links"]):
            _link(link, path + ".links[%d]" % j)
            # Attribution/digest changes cannot disguise the same semantic link.
            semantic = (link["purpose"], _encode(link["target"]))
            _need(semantic not in semantics, "reference", "duplicate semantic link", path + ".links")
            semantics.add(semantic)
        work[w["id"]] = w
    pairs = set()
    for i, c in enumerate(document["coordination"]):
        path = "$.coordination[%d]" % i
        _fields(c, "id dependent upstream briefed graph_pin", path)
        for key in ("dependent", "upstream"):
            _birth(c[key], path + "." + key)
            _need(c[key] in work, "reference", "undeclared work endpoint", path)
        pair = c["dependent"], c["upstream"]
        _need(pair[0] != pair[1] and pair not in pairs,
              "reference", "self or duplicate coordination pair", path)
        pairs.add(pair)
        upstream = work[c["upstream"]]
        _need(upstream["design"] is not None, "reference", "upstream requires declared design", path)
        briefed = c["briefed"]
        if briefed is not None:
            _fields(briefed, "design_rev ref by at", path + ".briefed")
            _integer(briefed["design_rev"], 1, MAX_REV, path + ".briefed.design_rev")
            _need(briefed["design_rev"] <= upstream["design"]["rev"],
                  "reference", "briefing claim exceeds declared design revision", path)
            _text(briefed["ref"], 1024, path + ".briefed.ref")
            _attribution(briefed, path + ".briefed")
        _graph_pin(c["graph_pin"], work[c["dependent"]], upstream, path + ".graph_pin")
    _fields(document["provenance"], "by at basis", "$.provenance")
    _attribution(document["provenance"], "$.provenance")
    _text(document["provenance"]["basis"], 1024, "$.provenance.basis")
    # Copy only after the bounded tree has passed all structural checks.
    normalized = json.loads(_encode(document))
    normalized["participants"].sort(key=lambda p: p["id"])
    for group in ("requirements", "work", "coordination"):
        normalized[group].sort(key=lambda entity: _id_order(entity["id"]))
    for w in normalized["work"]:
        w["requirements"].sort(key=_id_order)
        w["links"].sort(key=_encode)
    _need(len(_encode(normalized)) <= MAX_DOCUMENT_BYTES,
          "bounds", "canonical revision byte budget exceeded (including envelope reserve)", "$")
    return normalized


def canonicalize(document):
    """Return normalized document bytes, not a revision envelope or digest."""
    return _encode(validate(document))


def transition(parent, child, *, rev):
    """Check a child against an actual parent; do not infer a parent from a spec."""
    _integer(rev, 1, MAX_REV, "$.revision")
    current = validate(child)
    old = None if parent is None else validate(parent)
    _need((old is None) == (rev == 1), "transition", "create requires revision 1 and no parent", "$")
    if old is not None:
        for key in ("campaign", "continues"):
            _need(current[key] == old[key], "transition", "immutable campaign lineage changed", "$." + key)
    old_groups = {} if old is None else {
        e["id"]: group for group in ("requirements", "work", "coordination") for e in old[group]}
    for group in ("requirements", "work", "coordination"):
        previous = {} if old is None else {e["id"]: e for e in old[group]}
        for entity in current[group]:
            path = "$." + group
            prior = previous.get(entity["id"])
            birth = _id_order(entity["id"])[0]
            _need(old_groups.get(entity["id"], group) == group
                  and birth <= rev and (prior is not None or birth == rev),
                  "identity", "ID must be retained in same array or born in this revision", path)
            if group == "coordination" and prior is not None:
                _need(all(entity[k] == prior[k] for k in ("dependent", "upstream")),
                      "transition", "retained coordination endpoints changed", path)
            if group != "work":
                continue
            if prior is not None:
                _need(entity["participant"] == prior["participant"],
                      "transition", "retained work participant changed", path)
            design = entity["design"]
            before = None if prior is None else prior["design"]
            if before is None:
                _need(design is None or design["rev"] == 1,
                      "transition", "initial design must be null or revision 1", path)
            elif design != before:
                _need(design is not None and design["rev"] == before["rev"] + 1,
                      "transition", "changed design must advance exactly one revision", path)
    _need(old is None or current != old, "no-change", "document equals parent after normalization", "$")
    return current


def constants():
    """Authority constants for pure supplied-document reports; fresh each call."""
    return dict(authority="declarations-only", source_observation="not-performed",
                acceptance="not-recorded", invalidation_policy="undecided",
                coordination_scope="supplied-document", measurements="not-computed",
                merge_review="fresh review against the actual dependency required; not enforced here")


def findings(document):
    """Return warnings for a valid snapshot; never infer lifecycle or delivery."""
    doc = validate(document)
    result = []

    def warn(code, message, ident):
        result.append(dict(code=code, severity="warning", message=message, entity=ident))

    covered = {ident for w in doc["work"] if w["state"] == "active" for ident in w["requirements"]}
    for r in doc["requirements"]:
        if r["state"] == "active" and r["id"] not in covered:
            warn("requirement-uncovered", "active requirement has no active declared work", r["id"])
    work = {w["id"]: w for w in doc["work"]}
    for c in doc["coordination"]:
        if c["briefed"] is None:
            warn("brief-claim-missing", "no recorded briefing claim", c["id"])
        elif c["briefed"]["design_rev"] < work[c["upstream"]]["design"]["rev"]:
            warn("brief-claim-behind", "recorded briefing claim is behind declared design revision", c["id"])
        if any(work[c[k]]["state"] == "withdrawn" for k in ("dependent", "upstream")):
            warn("coordination-target-withdrawn", "coordination endpoint is declared withdrawn", c["id"])
    return result
