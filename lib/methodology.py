#!/usr/bin/env python3
"""Methodologies: the way a project is developed and released, as data.

A methodology is a directory with methodology.json and a scaffold/ directory of file templates. One ships with
qargi (<tool>/methodologies/gitflow); yours live under <config>/methodologies/NAME/. A name is one lower-case token,
unique across both places. This module only reads: `qargi project new|adopt` write, and only through a plan.

  methodology.py list
  methodology.py show NAME
  methodology.py check [NAME]
  methodology.py files NAME --param k=v ...      the scaffold rendered as JSON [{dest, content}], nothing written
  methodology.py deployment NAME [ID]            the deployment options, or one option's instructions

A template's {{name}} is replaced by the parameter of that name; a {{...}} that is not a declared parameter is left
alone (it may belong to the file's own language), but a declared parameter with no value is an error.
The optional parameter gates is the project's declared gates (lib/gates.py) as one line of JSON, an array of {name, command, tier}. A template
may hold, each marker alone on its line: {{#gates}} ... {{/gates}} (the lines between are kept when gates are declared), {{^gates}} ... {{/gates}}
(kept when none are), and {{#gate}} ... {{/gate}} (repeated for each gate, the feature tier first, in the order declared, with {{gate_id}} (gate1,
gate2, ...), {{gate_name}}, {{gate_name_quoted}} (a YAML single-quoted scalar: the name in quotes, a quote doubled, no escape, so the CI scan of lib/gates.py reads it), {{gate_tier}} and {{gate_command}} filled in). Without gates the
output is the template's {{^gates}} part, which is what it was before gates existed. A parameter may carry a
"pattern" (a regular expression the whole value must match). A scaffold entry may say "env": "section" (the file holds the
Development environment section) or "targets" (the file holds the bootstrap and doctor targets of a task runner): project attach
and adopt then treat the entry as present when the repository already has the piece in another file.
The optional after_release list names the steps that follow a release, each {id, when, next, help}: `qargi release finish` ends with
"next: NEXT" ({version} replaced) for each step whose `when`, a dotted project answer such as site.enabled, is true.
"""
import json, os, re, sys, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402
import gates as G  # noqa: E402

NAME = re.compile(r"^[a-z][a-z0-9]{0,23}$")
PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")
# the placeholders of a template's {{#gate}} loop, filled for each declared gate; they are not parameters
GATE_VARS = ("gate_id", "gate_name", "gate_name_quoted", "gate_tier", "gate_command")
GATES_IF = re.compile(r"^\{\{([#^])gates\}\}\n(.*?)^\{\{/gates\}\}(?:\n|\Z)", re.M | re.S)
GATE_LOOP = re.compile(r"^\{\{#gate\}\}\n(.*?)^\{\{/gate\}\}(?:\n|\Z)", re.M | re.S)


def usage_exit(msg):
    """A usage error: the message on stderr and exit 2, as the other verbs do."""
    print(msg if msg.startswith("qargi: ") else "qargi: " + msg, file=sys.stderr)
    raise SystemExit(2)


def roots():
    """[(where, directory)]: the built-in methodologies, then yours."""
    return [("built-in", os.path.join(P.tool_root(), "methodologies")), ("user", os.path.join(P.conf(), "methodologies"))]


def find(name):
    """(where, directory) of the methodology, or None."""
    for where, base in roots():
        d = os.path.join(base, name)
        if NAME.match(name or "") and os.path.isfile(os.path.join(d, "methodology.json")):
            return where, d
    return None


def names():
    out, seen = [], set()
    for where, base in roots():
        try:
            entries = sorted(os.listdir(base))
        except OSError:
            continue
        for n in entries:
            if n not in seen and find(n):
                seen.add(n)
                out.append(n)
    return out


def shadowing():
    """Names in your directory that a built-in methodology already has (the built-in wins; yours is never used)."""
    mine, builtin = roots()[1][1], roots()[0][1]
    try:
        return [n for n in sorted(os.listdir(mine)) if os.path.isfile(os.path.join(mine, n, "methodology.json")) and os.path.isfile(os.path.join(builtin, n, "methodology.json"))]
    except OSError:
        return []


def load(name):
    f = find(name)
    if not f:
        raise SystemExit("qargi: no methodology named %s (qargi methodology list)" % name)
    with open(os.path.join(f[1], "methodology.json")) as fh:
        data = json.load(fh)
    return f[0], f[1], data


def problems(name):
    """The reasons a methodology is not usable, as a list of strings."""
    bad = []
    f = find(name)
    if not f:
        return ["%s: no such methodology (needs methodology.json)" % name]
    where, d = f
    try:
        m = json.load(open(os.path.join(d, "methodology.json")))
    except (OSError, ValueError) as e:
        return ["%s: methodology.json is not valid JSON (%s)" % (name, e)]
    if m.get("schema") != 1:
        bad.append("%s: schema must be 1" % name)
    if m.get("name") != name:
        bad.append("%s: methodology.json names %r" % (name, m.get("name")))
    params = m.get("params") or {}
    if not isinstance(params, dict) or "project" not in params:
        bad.append("%s: params must declare project" % name)
    br = m.get("branches") or {}
    ll = br.get("long_lived")
    if not (isinstance(ll, list) and ll and all(isinstance(x, str) and x for x in ll)):
        bad.append("%s: branches.long_lived is a list of branch names" % name)
    for k, need in (("release", "{version}"), ("task", "{slug}")):
        if not (isinstance(br.get(k), str) and need in br[k]):
            bad.append("%s: branches.%s is a pattern containing %s" % (name, k, need))
    seen = set()
    for item in m.get("scaffold") or []:
        src, dest = (item or {}).get("src", ""), (item or {}).get("dest", "")
        if not src or not dest or dest.startswith("/") or ".." in dest.split("/") or src.startswith("/") or ".." in src.split("/"):
            bad.append("%s: scaffold entry %r needs a relative src and dest" % (name, item))
            continue
        if item.get("env") not in (None, "section", "targets"):
            bad.append("%s: scaffold entry %s: env is section (the Development environment section) or targets (the bootstrap and doctor targets)" % (name, dest))
        if dest in seen:
            bad.append("%s: scaffold writes %s twice" % (name, dest))
        seen.add(dest)
        p = os.path.join(d, "scaffold", src)
        if not os.path.isfile(p):
            bad.append("%s: scaffold/%s is missing" % (name, src))
            continue
        for ph in set(PLACEHOLDER.findall(open(p, encoding="utf-8").read())):
            if ph not in params and ph not in GATE_VARS:
                bad.append("%s: scaffold/%s uses {{%s}}, which params does not declare" % (name, src, ph))
    ar = m.get("after_release", [])
    if not isinstance(ar, list):
        bad.append("%s: after_release is a list of steps {id, when, next, help}" % name)
        ar = []
    aids = []
    for s in ar:
        if not isinstance(s, dict) or set(s) - {"id", "when", "next", "help"}:
            bad.append("%s: after_release step %r: an object {id, when, next, help}" % (name, s))
            continue
        aids.append(s.get("id"))
        if not (isinstance(s.get("id"), str) and NAME.match(s["id"])):
            bad.append("%s: after_release step %r: id is one lower-case token" % (name, s.get("id")))
        if not (isinstance(s.get("when"), str) and re.fullmatch(r"[a-z_]+(\.[a-z_]+)*", s["when"])):
            bad.append("%s: after_release step %s: when is the dotted name of a project answer that must be true (for example site.enabled)" % (name, s.get("id")))
        nx = s.get("next")
        if not (isinstance(nx, str) and nx.startswith("qargi ") and "\n" not in nx):
            bad.append("%s: after_release step %s: next is the one qargi command line to run next ({version} stands for the version)" % (name, s.get("id")))
    if len(aids) != len(set(aids)):
        bad.append("%s: after_release step ids are unique" % name)
    ids = [o.get("id") for o in (m.get("deployment") or {}).get("options", [])]
    if len(ids) != len(set(ids)) or any(not i for i in ids):
        bad.append("%s: deployment option ids are unique and not empty" % name)
    for o in (m.get("deployment") or {}).get("options", []):
        if not o.get("instructions"):
            bad.append("%s: deployment option %s has no instructions" % (name, o.get("id")))
    return bad


def render(name, given):
    """The scaffold with the parameters filled in: [{dest, content}]."""
    where, d, m = load(name)
    bad = problems(name)
    if bad:
        raise SystemExit("qargi: " + "; ".join(bad))
    params = {}
    for k, spec in (m.get("params") or {}).items():
        v = given.get(k, spec.get("default"))
        if k == "year" and not v:
            v = str(datetime.date.today().year)
        if v in (None, "") and spec.get("required"):
            raise SystemExit("qargi: --param %s=VALUE is required (%s)" % (k, spec.get("help", "")))
        params[k] = "" if v is None else str(v)
        if spec.get("pattern") and not re.fullmatch(spec["pattern"], params[k]):
            raise SystemExit("qargi: --param %s=%s: not of the form %s (%s)" % (k, params[k], spec["pattern"], spec.get("help", "")))
    unknown = sorted(set(given) - set(params))
    if unknown:
        raise SystemExit("qargi: unknown parameter %s (this methodology has: %s)" % (", ".join(unknown), ", ".join(params)))
    if not re.fullmatch(r"[a-z][a-z0-9]{0,23}", params.get("project", "")):
        raise SystemExit("qargi: project: one lower-case token (letters, digits)")
    for k, v in params.items():
        if "\n" in v or "\r" in v:
            raise SystemExit("qargi: %s is one line" % k)
    gates = declared_gates(params.get("gates", ""))
    out = []
    for item in m.get("scaffold") or []:
        text = open(os.path.join(d, "scaffold", item["src"]), encoding="utf-8").read()
        # the declared gates choose the template's parts first, then the parameters fill in, and the gates' own text goes in last and once
        text = GATES_IF.sub(lambda mo: mo.group(2) if (mo.group(1) == "#") == bool(gates) else "", text)
        text = PLACEHOLDER.sub(lambda mo: params[mo.group(1)] if mo.group(1) in params else mo.group(0), text)
        text = GATE_LOOP.sub(lambda mo: "".join(gate_text(mo.group(1), i, g) for i, g in enumerate(gates, 1)), text)
        out.append({"dest": item["dest"], "content": text})
    return out


def declared_gates(value):
    """The gates of the parameter gates (one line of JSON; empty or [] declares none) as [{name, tier, command}] with the command as one line,
    the feature tier first and each tier in the order declared. Exits when the value is not a valid list of gates."""
    if not value.strip():
        return []
    try:
        data = json.loads(value)
    except ValueError as e:
        raise SystemExit("qargi: --param gates=...: not JSON (%s); an array of {name, command, tier}" % e)
    bad = G.problems(data)
    if bad:
        raise SystemExit("qargi: --param gates=...: " + "; ".join(bad))
    return G.select(data or [], list(G.TIERS))


def gate_text(body, n, gate):
    """One pass of a {{#gate}} loop body for the gate."""
    vals = {"gate_id": "gate%d" % n, "gate_name": gate["name"], "gate_name_quoted": "'" + gate["name"].replace("'", "''") + "'", "gate_tier": gate["tier"], "gate_command": gate["command"]}
    return PLACEHOLDER.sub(lambda mo: vals.get(mo.group(1), mo.group(0)), body)


def main(argv):
    verb = argv[0] if argv else ""
    rest = argv[1:]
    if verb == "list":
        print("%-12s %-9s %s" % ("METHODOLOGY", "WHERE", "DESCRIPTION"))
        for n in names():
            where, d, m = load(n)
            print("%-12s %-9s %s" % (n, where, m.get("description", "")))
    elif verb == "show":
        if not rest:
            usage_exit("usage: qargi methodology show NAME")
        where, d, m = load(rest[0])
        print("methodology: %s (%s, %s)\ndir: %s\n" % (m.get("name"), where, "version %s" % m.get("version"), d))
        print(m.get("description", ""))
        br = m.get("branches", {})
        print("\nbranches: long-lived %s; release %s; task %s" % (", ".join(br.get("long_lived", [])), br.get("release"), br.get("task")))
        print("tests: per task, %s; per collection, %s" % (m.get("tests", {}).get("task"), m.get("tests", {}).get("collection")))
        print("ci: %s (%s)" % (m.get("ci", {}).get("provider"), m.get("ci", {}).get("file")))
        print("\nrelease:")
        for i, step in enumerate(m.get("release", []), 1):
            print("  %d. %s" % (i, step))
        if m.get("after_release"):
            print("\nafter a release (release finish names the step when the answer is true):")
            for s in m["after_release"]:
                print("  %-12s when %s: %s (%s)" % (s.get("id"), s.get("when"), s.get("next"), s.get("help", "")))
        print("\nparameters:")
        for k, spec in (m.get("params") or {}).items():
            print("  %-13s %s%s" % (k, spec.get("help", ""), " (required)" if spec.get("required") else (" (default %s)" % spec.get("default") if spec.get("default") else "")))
        print("\nscaffold:")
        for item in m.get("scaffold", []):
            print("  " + item["dest"])
        print("\ndeployment options:")
        for o in (m.get("deployment") or {}).get("options", []):
            print("  %-16s %s" % (o["id"], o.get("title", "")))
    elif verb == "check":
        rc = 0
        for n in shadowing():
            print("%s: a built-in methodology of this name exists; yours is never used (rename it)" % n)
            rc = 1
        for n in (rest[:1] or names()):
            bad = problems(n)
            for b in bad:
                print(b)
            rc = rc or (1 if bad else 0)
        if rc == 0:
            print("methodologies: ok")
        sys.exit(rc)
    elif verb == "files":
        if not rest:
            usage_exit("usage: qargi methodology files NAME --param k=v ...")
        given, i = {}, 1
        while i < len(rest):
            if rest[i] == "--param" and i + 1 < len(rest) and "=" in rest[i + 1]:
                k, v = rest[i + 1].split("=", 1)
                given[k] = v
                i += 2
            else:
                usage_exit("qargi: unknown option %s" % rest[i])
        print(json.dumps(render(rest[0], given), indent=2))
    elif verb == "deployment":
        if not rest:
            usage_exit("usage: qargi methodology deployment NAME [ID]")
        where, d, m = load(rest[0])
        opts = (m.get("deployment") or {}).get("options", [])
        if len(rest) > 1:
            o = next((x for x in opts if x["id"] == rest[1]), None)
            if not o:
                raise SystemExit("qargi: no deployment option %s (%s)" % (rest[1], ", ".join(x["id"] for x in opts)))
            print("%s: %s\ncan be done for you: %s\n\n%s" % (o["id"], o.get("title", ""), "yes" if o.get("automatable") else "no", o["instructions"]))
        else:
            print((m.get("deployment") or {}).get("note", ""))
            print()
            for o in opts:
                print("%-16s %s%s" % (o["id"], o.get("title", ""), "  (can be done for you)" if o.get("automatable") else ""))
    else:
        usage_exit("usage: qargi methodology list|show|check|files|deployment ...")


if __name__ == "__main__":
    main(sys.argv[1:])
