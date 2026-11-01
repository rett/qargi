#!/usr/bin/env python3
"""qargi provider: the model-provider descriptors, lib/providers/NAME.json, one schema (lib/providers/schema.json) for all.

As a library (import provider; stdlib only, found beside the descriptors, so it works from a checkout and from /opt/qargi):
  load(name)                           the descriptor as a dict; ProviderError when there is none
  validate(descriptor, name=None)      [("fail"|"warn", message), ...]; name is the file name the provider must carry
  cap(name, surface, capability)       "yes", "partial", "no" or "unverified" (the file says yes or partial, but with no
                                       verified_on date)
  effective(name, surface, capability) what enforcement may rely on: "yes", "partial" or "no". Unverified counts as no, and so
                                       does a surface the provider does not list.
Every function that reads a descriptor takes root= (the providers directory) for tests; the default is beside this file."""
import json
import os
import re
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))
PROVIDERS = os.path.join(HERE, "providers")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SURFACES = ("local", "cloud")
TIERS = ("fast", "balanced", "deep", "frontier")


class ProviderError(Exception):
    pass


def schema():
    with open(os.path.join(PROVIDERS, "schema.json")) as f:
        return json.load(f)


def capabilities():
    return tuple(schema()["properties"]["capabilities"]["properties"])


def names(root=None):
    """The providers that have a descriptor file (schema.json describes them and is not one)."""
    root = root or PROVIDERS
    try:
        files = os.listdir(root)
    except OSError:
        return []
    return sorted(f[:-5] for f in files if f.endswith(".json") and f != "schema.json" and NAME_RE.match(f[:-5]))


def load(name, root=None):
    root = root or PROVIDERS
    if not isinstance(name, str) or not NAME_RE.match(name) or name == "schema":
        raise ProviderError("unknown provider '%s'" % name)
    path = os.path.join(root, name + ".json")
    if not os.path.isfile(path):
        raise ProviderError("unknown provider '%s'; available: %s" % (name, ", ".join(names(root)) or "none"))
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError) as e:
        raise ProviderError("provider '%s' is not readable JSON: %s" % (name, e))
    if not isinstance(d, dict):
        raise ProviderError("provider '%s' is not a JSON object" % name)
    return d


# ---- the schema subset ------------------------------------------------------------------------------------------------

def _is_date(v):
    if not isinstance(v, str) or not re.match(r"^\d{4}-\d{2}-\d{2}$", v):
        return False
    try:
        datetime.strptime(v, "%Y-%m-%d")
    except ValueError:
        return False
    return True


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
    if t == "boolean":
        return isinstance(v, bool)
    return False


def _show(v):
    return repr(v) if isinstance(v, str) else json.dumps(v)


def _check(v, s, root, path, out):
    """Validate v against the schema node s, appending (path, message) to out. Supports type, enum, const, pattern, format
    date, required, properties, additionalProperties false, items, minItems, uniqueItems and a local $ref."""
    if "$ref" in s:
        node = root
        for part in s["$ref"].lstrip("#/").split("/"):
            node = node[part]
        merged = dict(node)
        merged.update({k: x for k, x in s.items() if k != "$ref"})
        return _check(v, merged, root, path, out)
    if "type" in s:
        ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
        if not any(_type_ok(v, t) for t in ts):
            out.append((path, "%s is not of type %s" % (_show(v), ", ".join(ts))))
            return
    if "const" in s and not (type(v) is type(s["const"]) and v == s["const"]):
        what = "the supported version" if path == "schema" else "the required value"
        out.append((path, "%s is not %s %s" % (_show(v), what, _show(s["const"]))))
        return
    if "enum" in s and not any(type(v) is type(e) and v == e for e in s["enum"]):
        out.append((path, "%s is not one of %s" % (_show(v), ", ".join(str(e) for e in s["enum"]))))
        return
    if s.get("format") == "date" and v is not None and not _is_date(v):
        out.append((path, "%s is not a date (YYYY-MM-DD)" % _show(v)))
    if "pattern" in s and isinstance(v, str) and not re.search(s["pattern"], v):
        out.append((path, "%s does not match %s" % (_show(v), s["pattern"])))
    if isinstance(v, dict):
        props = s.get("properties", {})
        for k in s.get("required", []):
            if k not in v:
                if path in ("tier_detail", "tiers"):
                    out.append((path, "missing tier '%s'" % k))
                else:
                    out.append((path, "missing required property '%s'" % k))
        for k, x in v.items():
            sub = (path + "." if path else "") + k
            if k in props:
                _check(x, props[k], root, sub, out)
            elif s.get("additionalProperties") is False:
                out.append((sub, "unknown capability" if path == "capabilities" else "additional property is not allowed"))
    if isinstance(v, list):
        if len(v) < s.get("minItems", 0):
            out.append((path, "needs at least %d item%s" % (s["minItems"], "" if s["minItems"] == 1 else "s")))
        if s.get("uniqueItems") and len(set(json.dumps(x, sort_keys=True) for x in v)) != len(v):
            out.append((path, "has a duplicate item"))
        if "items" in s:
            for i, x in enumerate(v):
                _check(x, s["items"], root, "%s[%d]" % (path, i), out)


def _msg(path, text):
    return (path + ": " if path else "") + text


def validate(d, name=None):
    """Findings for a descriptor: schema violations and the rules a schema cannot state are "fail"; a missing verified_on
    date is a "warn". name, when given, is the file name the provider must equal."""
    sch = schema()
    raw = []
    _check(d, sch, sch, "", raw)
    out = [("fail", _msg(p, m)) for p, m in raw]
    if not isinstance(d, dict):
        return out
    prov = d.get("provider")
    if name is not None and isinstance(prov, str) and prov != name:
        out.append(("fail", "provider '%s' differs from the file name '%s'" % (prov, name)))
    detail = d.get("tier_detail") if isinstance(d.get("tier_detail"), dict) else {}
    pattern = None
    if isinstance(d.get("model_pattern"), str):
        try:
            pattern = re.compile(d["model_pattern"])
        except re.error as e:
            out.append(("fail", "model_pattern: not a regular expression (%s)" % e))
    for t in TIERS:
        row = detail.get(t)
        if not isinstance(row, dict):
            continue
        if pattern and isinstance(row.get("model"), str) and not pattern.search(row["model"]):
            out.append(("fail", "tier_detail.%s.model: '%s' does not match model_pattern %s" % (t, row["model"], d["model_pattern"])))
        if isinstance(d.get("tiers"), dict) and t in d["tiers"] and d["tiers"][t] != row.get("model"):
            out.append(("fail", "tiers.%s: %s differs from tier_detail.%s.model %s" % (t, _show(d["tiers"][t]), t, _show(row.get("model")))))
        if isinstance(d.get("aliases"), dict) and d["aliases"].get(t) != row.get("alias"):  # a tier with no alias is absent or null
            out.append(("fail", "aliases.%s: %s differs from tier_detail.%s.alias %s" % (t, _show(d["aliases"].get(t)), t, _show(row.get("alias")))))
        if row.get("verified_on") is None and "verified_on" in row:
            out.append(("warn", "tier_detail.%s.verified_on: not verified" % t))
    surfaces = [s for s in d.get("surfaces", []) if s in SURFACES] if isinstance(d.get("surfaces"), list) else []
    caps = d.get("capabilities") if isinstance(d.get("capabilities"), dict) else {}
    for c in capabilities():
        row = caps.get(c) if isinstance(caps.get(c), dict) else {}
        if isinstance(caps.get(c), dict):
            for s in SURFACES:
                if s in row and s not in surfaces:
                    out.append(("fail", "capabilities.%s.%s: the provider does not list the surface '%s'" % (c, s, s)))
        for s in surfaces:
            cell = row.get(s)
            if cell is None:
                out.append(("warn", "capabilities.%s.%s: no entry for the listed surface; it counts as not supported" % (c, s)))
            elif isinstance(cell, dict) and "verified_on" in cell and cell["verified_on"] is None:
                tail = " (counts as not supported)" if cell.get("value") in ("yes", "partial") else ""
                out.append(("warn", "capabilities.%s.%s.verified_on: not verified%s" % (c, s, tail)))
    return out


# ---- capabilities -----------------------------------------------------------------------------------------------------

def cap(name, surface, capability, root=None):
    """yes, partial, no or unverified for one capability on one surface. A yes or partial with no verified_on is unverified."""
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    if capability not in capabilities():
        raise ProviderError("unknown capability '%s'" % capability)
    d = load(name, root)
    if surface not in (d.get("surfaces") or []):
        return "no"
    cell = ((d.get("capabilities") or {}).get(capability) or {}).get(surface)
    if not isinstance(cell, dict) or cell.get("value") not in ("yes", "partial", "no"):
        return "no"
    if cell["value"] != "no" and not cell.get("verified_on"):
        return "unverified"
    return cell["value"]


def effective(name, surface, capability, root=None):
    v = cap(name, surface, capability, root)
    return "no" if v == "unverified" else v
