#!/usr/bin/env python3
"""Validate a request or a response of a provider adapter verb against lib/providers/adapter-schema.json.

Usage: validate.py [--schema FILE] VERB request|response|error     reads one JSON value on stdin
       exit 0 valid; 1 invalid (one problem per line on stdout); 2 usage or an unreadable schema
As a library: check(value, node, root) -> [(path, message)]; problems(schema, verb, kind, value) -> [str].

A stdlib subset of JSON Schema, enough for adapter-schema.json: type (a name or a list), enum, const, pattern, required,
properties, additionalProperties (false or a schema), items, minItems, minLength, minimum, anyOf and a local $ref.
Run isolated: python3 -I."""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.realpath(__file__))
DEFAULT = os.path.normpath(os.path.join(HERE, "..", "..", "..", "lib", "providers", "adapter-schema.json"))


def _type_ok(v, t):
    if t == "null":
        return v is None
    if t == "string":
        return isinstance(v, str)
    if t == "object":
        return isinstance(v, dict)
    if t == "array":
        return isinstance(v, list)
    if t == "integer":
        return isinstance(v, int) and not isinstance(v, bool)
    if t == "number":
        return isinstance(v, (int, float)) and not isinstance(v, bool)
    if t == "boolean":
        return isinstance(v, bool)
    return False


def _same(a, b):
    return type(a) is type(b) and a == b


def _show(v):
    return json.dumps(v)


def check(v, s, root, path="$"):
    out = []
    if "$ref" in s:
        node = root
        for part in s["$ref"].lstrip("#/").split("/"):
            node = node[part]
        merged = dict(node)
        merged.update({k: x for k, x in s.items() if k != "$ref"})
        return check(v, merged, root, path)
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in ts):
            return [(path, "%s is not of type %s" % (_show(v), "/".join(ts)))]
    if "const" in s and not _same(v, s["const"]):
        return [(path, "%s is not the required value %s" % (_show(v), _show(s["const"])))]
    if "enum" in s and not any(_same(v, e) for e in s["enum"]):
        return [(path, "%s is not one of %s" % (_show(v), ", ".join(_show(e) for e in s["enum"])))]
    if "anyOf" in s and not any(not check(v, alt, root, path) for alt in s["anyOf"]):
        out.append((path, "matches none of the alternatives (%s)" % " | ".join(
            "requires " + "+".join(alt["required"]) if "required" in alt else "an alternative" for alt in s["anyOf"])))
    if isinstance(v, str):
        if "pattern" in s and not re.search(s["pattern"], v):
            out.append((path, "%s does not match %s" % (_show(v), s["pattern"])))
        if len(v) < s.get("minLength", 0):
            out.append((path, "is shorter than %d" % s["minLength"]))
    if isinstance(v, (int, float)) and not isinstance(v, bool) and "minimum" in s and v < s["minimum"]:
        out.append((path, "%s is below %s" % (_show(v), s["minimum"])))
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                out.append((path, "missing required property '%s'" % k))
        for k, x in v.items():
            if k in props:
                out.extend(check(x, props[k], root, path + "." + k))
            elif s.get("additionalProperties") is False:
                out.append((path + "." + k, "additional property is not allowed"))
            elif isinstance(s.get("additionalProperties"), dict):
                out.extend(check(x, s["additionalProperties"], root, path + "." + k))
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            out.append((path, "needs at least %d item(s)" % s["minItems"]))
        if "items" in s:
            for i, x in enumerate(v):
                out.extend(check(x, s["items"], root, "%s[%d]" % (path, i)))
    return out


def problems(schema, verb, kind, value):
    """The problems of value as the request, the response or the error body of verb; a missing verb or kind is a problem."""
    if kind == "error":
        node = schema["error"]
    else:
        node = schema.get("verbs", {}).get(verb, {}).get(kind)
        if node is None:
            return ["the schema has no %s for the verb '%s'" % (kind, verb)]
    return ["%s: %s" % p for p in check(value, node, schema)]


def main(argv):
    path = DEFAULT
    if argv[:1] == ["--schema"] and len(argv) >= 2:
        path, argv = argv[1], argv[2:]
    if len(argv) != 2 or argv[1] not in ("request", "response", "error"):
        print("usage: validate.py [--schema FILE] VERB request|response|error  < JSON", file=sys.stderr)
        return 2
    try:
        with open(path) as f:
            schema = json.load(f)
    except (OSError, ValueError) as e:
        print("validate.py: cannot read the schema %s: %s" % (path, e), file=sys.stderr)
        return 2
    try:
        value = json.loads(sys.stdin.read())
    except ValueError as e:
        print("not JSON: %s" % e)
        return 1
    found = problems(schema, argv[0], argv[1], value)
    for p in found:
        print(p)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
