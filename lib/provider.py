#!/usr/bin/env python3
"""qargi provider: the model-provider descriptors, lib/providers/NAME.json, one schema (lib/providers/schema.json) for all.

As a library (import provider; stdlib only, found beside the descriptors, so it works from a checkout and from /opt/qargi):
  load(name)                           the descriptor as a dict; ProviderError when there is none
  validate(descriptor, name=None)      [("fail"|"warn", message), ...]; name is the file name the provider must carry
  cap(name, surface, capability)       "yes", "partial", "no" or "unverified" (the file says yes or partial, but with no
                                       verified_on date)
  effective(name, surface, capability) what enforcement may rely on: "yes", "partial" or "no". Unverified counts as no, and so
                                       does a surface the provider does not list.
  accepted(project, surface)           the project's recorded acceptance of a surface with no read-only barrier, or None
  require_barrier(provider, surface, project)
                                       ("yes"|"partial"|"accepted"|"refused", text): may a read-only role run on this surface?
  layout(name, home=None)              the descriptor's layout: every field of LAYOUT_FIELDS, null when the provider has none; a
                                       leading ~ is expanded with home (default $HOME) when it is read, never in the file
  require(name, field, would)          the layout field, or Unsupported (a ProviderError): "provider NAME has no FACILITY: WOULD"
  require_skills(name, would)          the same refusal when the skills capability is not yes or partial (verified) on local
  memory_dir(name, checkout) / checkout_key(rule, path) / launch_line(name, render)
                                       the layout's templates filled in; project_provider(answers) the project's provider name
Every function that reads a descriptor takes root= (the providers directory) for tests; the default is beside this file.

Usage: provider.py list
       provider.py show NAME [--json]
       provider.py check NAME            exit 1 on a failure, 0 otherwise (warnings do not fail); the adapter, when the
                                         descriptor names one, must exist and be executable
       provider.py accept NAME --surface S --no-barrier [--project P] --asked W [--approved W] [--plan T]
                                         lib/provider.sh does it: plan first, then the token and the approval
       provider.py require-barrier PROVIDER SURFACE [--project P]
                                         exit 0 when a read-only role may run there (a partial barrier prints its note to
                                         stderr), 2 with the qargi provider accept command when it may not
       provider.py effective PROVIDER SURFACE CAPABILITY
                                         prints yes, partial or no (what enforcement may rely on); exit 1 when the provider
                                         does not list the surface
       provider.py layout NAME [FIELD] [--would TEXT] [--home DIR]
                                         the layout as JSON, or one field (a string as it is, an object as JSON); a null
                                         field exits 3 with "provider NAME has no FACILITY: TEXT"
       provider.py require-skills NAME [--would TEXT]
                                         exit 3 with that refusal unless the provider supports skills on the local surface
       provider.py launch NAME RENDER    the command that starts a session on the render directory RENDER (exit 3: none)
Exit status 3 is the degrade refusal: the provider does not support what the verb needs."""
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


class Unsupported(ProviderError):
    """The provider has no such facility (a null layout field, or a capability that is not verified): exit status 3."""


NON_PROVIDERS = ("schema", "adapter-schema")   # JSON files in lib/providers/ that describe descriptors and adapters; they are not providers


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
    return sorted(f[:-5] for f in files if f.endswith(".json") and f[:-5] not in NON_PROVIDERS and NAME_RE.match(f[:-5]))


def load(name, root=None):
    root = root or PROVIDERS
    if not isinstance(name, str) or not NAME_RE.match(name) or name in NON_PROVIDERS:
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


def _layout_problems(lay):
    """The rules of the layout a schema cannot state (the types are the schema's)."""
    if not isinstance(lay, dict):
        return []
    bad = []
    for k in ("project_skills_dir", "project_agents_dir"):
        v = lay.get(k)
        if isinstance(v, str) and (not v or v.startswith(("/", "~")) or ".." in v.split("/")):
            bad.append("layout.%s: '%s' is not a path inside the checkout (relative, no ..)" % (k, v))
    for k in ("user_skills_dir", "user_agents_dir"):
        v = lay.get(k)
        if isinstance(v, str) and not v.startswith("~/"):
            bad.append("layout.%s: '%s' does not start with ~/" % (k, v))
    for i, f in enumerate(lay.get("settings_files") or []):
        v = f.get("path") if isinstance(f, dict) else None
        if isinstance(v, str) and f.get("scope") == "user" and not v.startswith("~/"):
            bad.append("layout.settings_files[%d].path: the user file '%s' does not start with ~/" % (i, v))
        if isinstance(v, str) and isinstance(f, dict) and f.get("scope") != "user" and (not v or v.startswith(("/", "~")) or ".." in v.split("/")):
            bad.append("layout.settings_files[%d].path: '%s' is not a path inside the checkout (relative, no ..)" % (i, v))
    if lay.get("exclusion") is not None and not lay.get("settings_files"):
        bad.append("layout.exclusion: a skill is switched off in a settings file, but settings_files is null or empty")
    mem = lay.get("memory_dir")
    if isinstance(mem, str):
        if "{checkout_key}" in mem and lay.get("checkout_key") is None:
            bad.append("layout.memory_dir: uses {checkout_key} but checkout_key is null")
        if not mem.startswith("~/"):
            bad.append("layout.memory_dir: '%s' does not start with ~/" % mem)
    sl = lay.get("session_launch")
    if isinstance(sl, str) and "{render}" not in sl:
        bad.append("layout.session_launch: the command has no {render}")
    return bad


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
    out += [("fail", m) for m in _layout_problems(d.get("layout"))]
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


# ---- the layout -------------------------------------------------------------------------------------------------------

LAYOUT_FIELDS = ("project_skills_dir", "user_skills_dir", "project_agents_dir", "user_agents_dir", "settings_files", "exclusion",
                 "memory_dir", "checkout_key", "render_target", "session_launch")
FACILITY = {"project_skills_dir": "project skills directory", "user_skills_dir": "user skills directory",
            "project_agents_dir": "project agents directory", "user_agents_dir": "user agents directory",
            "settings_files": "settings files", "exclusion": "way to switch a skill off in a settings file",
            "memory_dir": "memory directory", "checkout_key": "checkout key rule", "render_target": "packs render target",
            "session_launch": "session launch command"}
_HOME_FIELDS = ("user_skills_dir", "user_agents_dir", "memory_dir")


def _home(path, home):
    if isinstance(path, str) and (path == "~" or path.startswith("~/")):
        return home.rstrip("/") + path[1:]
    return path


def layout(name, root=None, home=None):
    """The layout of a provider: every field of LAYOUT_FIELDS (None where the descriptor has none, or has no layout at all).
    A leading ~ is expanded here with home (default: $HOME), so the descriptor stays portable. Project paths stay relative to
    the checkout. A layout that breaks the schema is a ProviderError."""
    d = load(name, root)
    bad = [m for lvl, m in validate(d, name) if lvl == "fail" and m.startswith("layout")]
    if bad:
        raise ProviderError("provider '%s' has a bad layout: %s" % (name, bad[0]))
    raw = d.get("layout") if isinstance(d.get("layout"), dict) else {}
    home = home or os.path.expanduser("~")
    out = {k: raw.get(k) for k in LAYOUT_FIELDS}
    for k in _HOME_FIELDS:
        out[k] = _home(out[k], home)
    if out["settings_files"] is not None:
        out["settings_files"] = [{"scope": f["scope"], "path": _home(f["path"], home)} for f in out["settings_files"]]
    if out["exclusion"] is not None:
        out["exclusion"] = dict(out["exclusion"])
    return out


def require(name, field, would, root=None, home=None):
    """The layout field, or Unsupported: provider NAME has no FACILITY: WOULD (what the verb would have done with it)."""
    if field not in LAYOUT_FIELDS:
        raise ProviderError("unknown layout field '%s'" % field)
    v = layout(name, root, home)[field]
    if v is None or v == []:
        raise Unsupported("provider %s has no %s: %s" % (name, FACILITY[field], would))
    return v


def require_skills(name, would, root=None):
    """Unsupported unless the provider's skills capability is yes or partial (with a verification date) on the local surface,
    where a session loads skills from the directories of the layout."""
    if effective(name, "local", "skills", root) == "no":
        raise Unsupported("provider %s has no skills support on the local surface: %s" % (name, would))


def project_provider(answers):
    """The provider name of a project's stored answers (models.provider), claude when there is none or it is not a name."""
    models = answers.get("models") if isinstance(answers, dict) else None
    p = models.get("provider") if isinstance(models, dict) else None
    return p if isinstance(p, str) and NAME_RE.match(p) else "claude"


def checkout_key(rule, path):
    """The key of a checkout under a rule of the descriptor; nonalnum-dash replaces every non-alphanumeric character by -."""
    if rule != "nonalnum-dash":
        raise ProviderError("unknown checkout key rule '%s'" % rule)
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))


def memory_dir(name, checkout, root=None, home=None):
    """The provider's own memory directory for a checkout, or Unsupported."""
    tpl = require(name, "memory_dir", "locate the provider's own memory notes for a checkout", root, home)
    if "{checkout_key}" in tpl:
        tpl = tpl.replace("{checkout_key}", checkout_key(require(name, "checkout_key", "name the provider's memory directory of a checkout", root, home), checkout))
    return tpl


def launch_line(name, render, root=None):
    """The command that starts a session on the render directory, or Unsupported. A [...] group of the template stays only when
    the file named by its last word exists once {render} is filled in."""
    tpl = require(name, "session_launch", "print the command that starts a session on the render", root).replace("{render}", render)

    def group(m):
        words = m.group(1).split()
        return m.group(1) if words and os.path.isfile(words[-1]) else ""
    return re.sub(r"\[([^\]]*)\]", group, tpl)


# ---- the read-only barrier ----------------------------------------------------------------------------------------------

def _conf():
    sys.path.insert(0, HERE)
    import paths
    return paths.conf()


def project_answers(project, conf=None):
    """The project's stored answers as a dict, or None when there are none (or they cannot be read)."""
    if not project or not NAME_RE.match(project):
        return None
    try:
        with open(os.path.join(conf or _conf(), "projects", project + ".json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def accepted(project, surface, conf=None):
    """The project's models.accept_no_barrier.<surface> record {by, at, reason}, or None. A record that is not exactly that
    (a hand edit) is no acceptance."""
    models = (project_answers(project, conf) or {}).get("models")
    rec = ((models or {}).get("accept_no_barrier") or {}).get(surface) if isinstance(models, dict) and isinstance(models.get("accept_no_barrier"), dict) else None
    if isinstance(rec, dict) and set(rec) == {"by", "at", "reason"} and all(isinstance(v, str) and v.strip() for v in rec.values()):
        return rec
    return None


def accept_command(provider, surface, project=None):
    return 'qargi provider accept %s --surface %s --no-barrier --project %s --asked "<your words>"' % (provider, surface, project or "PROJECT")


def require_barrier(provider, surface, project=None, root=None, conf=None):
    """May a read-only role run on this surface of the provider? (state, text): state is yes, partial (text is the note),
    accepted (the project recorded that it accepts no barrier here) or refused (text says why and names the command)."""
    v = effective(provider, surface, "read_only_barrier", root)
    if v == "yes":
        return "yes", ""
    d = load(provider, root)
    cell = (((d.get("capabilities") or {}).get("read_only_barrier") or {}).get(surface)) or {}
    if v == "partial":
        return "partial", "%s has only a partial read-only barrier on %s: %s" % (provider, surface, cell.get("note") or "see qargi provider show %s" % provider)
    if accepted(project, surface, conf):
        return "accepted", ""
    why = "not supported" if cell.get("value") == "no" or surface not in (d.get("surfaces") or []) else "not verified, so it counts as not supported"
    return "refused", ("the provider %s has no read-only barrier on %s (%s), so a read-only role is refused there.\n"
                       "To run it anyway, on your own responsibility, record that you accept this for the project:\n  %s"
                       % (provider, surface, why, accept_command(provider, surface, project)))


def cmd_require_barrier(provider, surface, project):
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    state, text = require_barrier(provider, surface, project)
    if state == "refused":
        print("qargi: " + text, file=sys.stderr)
        return 2
    if state == "partial":
        print("qargi: note: " + text, file=sys.stderr)
    return 0


def cmd_effective(provider, surface, capability):
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    if surface not in (load(provider).get("surfaces") or []):
        raise ProviderError("the provider %s does not list the surface %s" % (provider, surface))
    print(effective(provider, surface, capability))
    return 0


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
    lay = layout(name)
    rows += ["  layout: %-32s no (the verb that needs it is refused with exit 3)" % f for f in LAYOUT_FIELDS if lay[f] is None]
    print("degrades:" if rows else "nothing degrades")
    for r in rows:
        print(r)
    for line in cannot:
        print(line)
    return 0


def cmd_layout(name, field, would, home):
    lay = layout(name, home=home)
    if field is None:
        print(json.dumps(lay, indent=2))
        return 0
    if field not in LAYOUT_FIELDS:
        print("qargi: unknown layout field '%s'; one of %s" % (field, ", ".join(LAYOUT_FIELDS)), file=sys.stderr)
        return 2
    v = require(name, field, would or "the verb needs it", home=home)
    print(v if isinstance(v, str) else json.dumps(v))
    return 0


def main(argv):
    usage = ("usage: qargi provider list | show NAME [--json] | check NAME | accept NAME --surface S --no-barrier [--project P] --asked WORDS "
             "[--approved WORDS] [--plan TOKEN] | layout NAME [FIELD] | require-skills NAME | launch NAME RENDER")
    if not argv:
        print(usage, file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "accept":                          # plan, token, audit line and the write to the answers are shell (lib.sh)
        sh = os.path.join(HERE, "provider.sh")
        sys.stdout.flush()
        os.execv(sh, [sh, "accept"] + rest)
    try:
        if verb == "list" and not rest:
            return cmd_list()
        pos = [a for a in rest if a != "--json"]
        if verb == "show" and len(pos) == 1 and len(rest) - len(pos) <= 1:
            return cmd_show(pos[0], "--json" in rest)
        if verb == "check" and len(rest) == 1:
            return cmd_check(rest[0])
        if verb == "effective" and len(rest) == 3:
            return cmd_effective(rest[0], rest[1], rest[2])
        if verb == "require-barrier" and len(rest) in (2, 4) and (len(rest) == 2 or rest[2] == "--project"):
            return cmd_require_barrier(rest[0], rest[1], rest[3] if len(rest) == 4 else None)
        if verb in ("layout", "require-skills", "launch"):
            opts, pos, i = {}, [], 0
            while i < len(rest):
                if rest[i] in ("--would", "--home") and i + 1 < len(rest):
                    opts[rest[i]], i = rest[i + 1], i + 2
                else:
                    pos.append(rest[i])
                    i += 1
            if verb == "layout" and len(pos) in (1, 2):
                return cmd_layout(pos[0], pos[1] if len(pos) == 2 else None, opts.get("--would"), opts.get("--home"))
            if verb == "require-skills" and len(pos) == 1:
                require_skills(pos[0], opts.get("--would") or "the verb needs it")
                return 0
            if verb == "launch" and len(pos) == 2:
                print(launch_line(pos[0], pos[1]))
                return 0
    except Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 3
    except ProviderError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
