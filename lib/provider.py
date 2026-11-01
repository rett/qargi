#!/usr/bin/env python3
"""qargi provider: the model-provider descriptors, lib/providers/NAME.json, one schema (lib/providers/schema.json) for all.

As a library (import provider; stdlib only, found beside the descriptors, so it works from a checkout and from /opt/qargi):
  load(name)                           the descriptor as a dict; ProviderError when there is none
  validate(descriptor, name=None)      [("fail"|"warn", message), ...]; name is the file name the provider must carry
  cap(name, surface, capability)       "yes", "partial", "no" or "unverified" (the file says yes or partial, but with no
                                       verified_on date)
  effective(name, surface, capability) what enforcement may rely on: "yes", "partial" or "no". Unverified counts as no, and so
                                       does a surface the provider does not list.
Every function that reads a descriptor takes root= (the providers directory) for tests; the default is beside this file.

Usage: provider.py list
       provider.py show NAME [--json]
       provider.py check NAME            exit 1 on a failure, 0 otherwise (warnings do not fail); the adapter, when the
                                         descriptor names one, must exist and be executable"""
import json
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))
TOOL = os.path.dirname(HERE)                      # the tool root: the checkout, or the installed copy
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
    ad = d.get("adapter")
    if isinstance(ad, str) and (os.path.isabs(ad) or ".." in ad.split("/") or not ad.startswith("lib/providers/")):
        out.append(("fail", "adapter: '%s' is not a path under lib/providers/ of the tool" % ad))
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


# ---- the verbs --------------------------------------------------------------------------------------------------------

def _count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _state(findings):
    f = sum(1 for lvl, _ in findings if lvl == "fail")
    w = sum(1 for lvl, _ in findings if lvl == "warn")
    return _count(f, "failure") if f else (_count(w, "warning") if w else "clean")


def _surfaces(d):
    s = d.get("surfaces")
    return [x for x in s if x in SURFACES] if isinstance(s, list) else []


def cmd_list():
    for n in names():
        try:
            d = load(n)
            findings = validate(d, n)
        except ProviderError as e:
            print("%-12s %-12s %s" % (n, "-", "1 failure (%s)" % e))
            continue
        print("%-12s %-12s %s" % (n, ",".join(_surfaces(d)) or "-", _state(findings)))
    return 0


def _verified(cell):
    return "verified %s" % cell["verified_on"] if cell.get("verified_on") else "not verified" + (", counts as no" if cell.get("value") != "no" else "")


def cmd_show(name, as_json):
    d = load(name)
    bad = [m for lvl, m in validate(d, name) if lvl == "fail"]
    if bad:
        print("qargi: provider '%s' breaks the schema (qargi provider check %s)" % (name, name), file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(d, indent=2))
        return 0
    print("%s  (surfaces: %s)" % (name, ", ".join(d["surfaces"])))
    print("model pattern: %s" % d["model_pattern"])
    print("tiers")
    for t in TIERS:
        r = d["tier_detail"][t]
        ver = "verified %s" % r["verified_on"] if r["verified_on"] else "verified: no"
        print("  %-9s %-22s alias %-8s %s  (%s)" % (t, r["model"], r["alias"] or "-", ver, r["source"]))
    print("effort")
    for k, v in d["effort"].items():
        print("  %-7s %s" % (k, v if v is not None else "- (no control)"))
    print("capabilities")
    for c in capabilities():
        print("  %s" % c)
        for s in d["surfaces"]:
            cell = d["capabilities"].get(c, {}).get(s)
            if cell is None:
                print("    %-6s %-8s no entry" % (s, "no"))
                continue
            print("    %-6s %-8s %-28s %s" % (s, cell["value"], _verified(cell), cell["note"]))
    return 0


def adapter_problem(d, tool=None):
    """None when the descriptor has no adapter or the adapter file exists and is executable, else what is wrong."""
    ad = d.get("adapter")
    if not isinstance(ad, str) or os.path.isabs(ad) or ".." in ad.split("/"):
        return None                               # no adapter, or a path validate() already refused
    path = os.path.join(tool or TOOL, ad)
    if not os.path.isfile(path):
        return "adapter: %s does not exist" % ad
    if not os.access(path, os.X_OK):
        return "adapter: %s is not executable" % ad
    return None


def cmd_check(name):
    d = load(name)
    findings = validate(d, name)
    bad = adapter_problem(d)
    if bad:
        findings.append(("fail", bad))
    fails = [m for lvl, m in findings if lvl == "fail"]
    warns = [m for lvl, m in findings if lvl == "warn"]
    print("%s: %s, %s" % (name, _count(len(fails), "failure"), _count(len(warns), "warning")))
    for m in fails:
        print("fail: %s" % m)
    for m in warns:
        print("warn: %s" % m)
    if fails:
        return 1
    print("adapter: %s" % ("%s (exists, executable)" % d["adapter"] if d.get("adapter") else "none (what needs one is refused)"))
    rows, cannot = [], []
    for s in _surfaces(d):
        for c in capabilities():
            v = cap(name, s, c)
            if v in ("no", "unverified"):
                rows.append("  %s: %-32s %s" % (s, c, "unverified (counts as no)" if v == "unverified" else "no"))
        if effective(name, s, "read_only_barrier") == "no":
            cannot.append("the review role cannot be served on %s" % s)
    print("degrades:" if rows else "nothing degrades")
    for r in rows:
        print(r)
    for line in cannot:
        print(line)
    return 0


def main(argv):
    usage = "usage: qargi provider list | show NAME [--json] | check NAME"
    if not argv:
        print(usage, file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    try:
        if verb == "list" and not rest:
            return cmd_list()
        pos = [a for a in rest if a != "--json"]
        if verb == "show" and len(pos) == 1 and len(rest) - len(pos) <= 1:
            return cmd_show(pos[0], "--json" in rest)
        if verb == "check" and len(rest) == 1:
            return cmd_check(rest[0])
    except ProviderError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
