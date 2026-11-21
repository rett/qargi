#!/usr/bin/env python3
"""The catalogue of refusals (lib/refusals.json), its renderer, its lint and the page made from it. Standard library only.

A refusal is a rule that stopped a verb. The catalogue names each rule once: a code, the rule, why it exists, its class and exit status,
its status (`live`: some verb raises it; `planned`: written down, not raised yet; `withdrawn`), the typed `fields` a raise may fill, a `message`,
and a `next` for a lead and for the owner's own session (`host`). A message and a next are templates: `{name}` is a declared field.

  refusal.py refuse [--verb V] [--project P] [--role R] CODE [KEY=VALUE ...]
        prints the refusal on standard error and exits with the code's exit status. The first line is the contract line, `qargi-refusal/1 `
        and one JSON object (code, exit, verb, project, role, epoch, state, tx, detail); then `qargi: refused [CODE] MESSAGE`, `  why: ...`
        and `  next: ...`. `detail` is qargi's own text: the typed fields as `key=value`, a lead-chosen value (ref, path, name and their lists)
        only as a digest of 12 hex digits, a list as three items and `+N`. An unknown code, a code that is not live, an unknown field or a
        value of the wrong type is a defect in the caller: exit 70, nothing else printed but the defect.
  refusal.py notice [same arguments]
        prints the same message and `next:` as `qargi: note [CODE] MESSAGE`, with no contract line, no why and no refusal, and exits 0: a verb
        that did its work and names a rule that will apply later.
  refusal.py check [--root DIR]     the lint: the catalogue against its own rules, against the code that raises it, against the seat contract
                                    (skipped, with a line saying so, when the page is absent), the generated page and the ratchet.
  refusal.py page                   the Markdown page of the catalogue (docs/reference/refusals.md)
  refusal.py sites [--root DIR]     the ratchet file: the unclassified `die` calls of each lib/*.sh
  refusal.py basis store TOKEN LABELS   reads the plan on standard input, one labelled line per label, into STATE/plans/TOKEN.json
  refusal.py basis moved OLD NEW        the labels whose lines differ between two stored plans, comma separated; exit 1 when either is unknown

The environment names the state directory (QARGI_STATE, else the layout of lib/paths.py). Library use: load, render, check, page_text."""
import glob
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOGUE = os.path.join("lib", "refusals.json")
PAGE = os.path.join("docs", "reference", "refusals.md")
SEAT_PAGE = os.path.join("docs", "reference", "lead-seat.md")
RATCHET = os.path.join("tests", "refusal-sites.txt")
CONTRACT = "qargi-refusal/1"
LINE_MAX = 4096
PLAN_DAYS = 7                       # a stored plan is kept this long

STATUSES = ("live", "planned", "withdrawn")
EXITS = (1, 2, 77)                  # a refusal, a guard's deny, a lead refusal of the seat
LEADS = ("lead", "host")            # the two readers of a `next`
LEAD_CHOSEN = ("ref", "path", "name", "ref-list", "path-list", "name-list")   # text a lead wrote: only a digest of it reaches `detail`
SEAT_CLASSES = ("seat-gate", "seat-door")
CODE_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)+$")
NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
VERB_RE = re.compile(r"^[a-z][a-z0-9:-]*(?: [a-z][a-z0-9:-]*)*$")
LABEL_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
TOKEN_RE = re.compile(r"^[0-9a-f]{12}$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
PROJECT_RE = re.compile(r"^[a-z][a-z0-9]{0,23}$")
ROLE_RE = re.compile(r"^[a-z][a-z0-9-]{0,40}$")
VALUE_MAX = 200                     # a lead-chosen value, and one list item


class Defect(Exception):
    """The caller of the renderer, or the catalogue, is wrong: a defect (exit 70), never a refusal."""


# ---------------------------------------------------------------------------------------------------------------------------- the catalogue

def load(root=None):
    with open(os.path.join(root or ROOT, CATALOGUE), encoding="utf-8") as f:
        return json.load(f)


def split_type(spec):
    """'enum:a,b' -> ('enum', ['a', 'b']); 'label-list' -> ('label-list', None). A spec that is not a type is a ValueError."""
    kind, _, arg = spec.partition(":")
    if kind == "enum":
        words = arg.split(",")
        if not arg or any(not LABEL_RE.match(w) for w in words) or len(set(words)) != len(words):
            raise ValueError("an enum lists its words: enum:a,b")
        return kind, words
    if arg or kind not in ("verb", "label", "label-list", "count", "token", "sha", "sha-list") + LEAD_CHOSEN:
        raise ValueError("unknown field type %r" % spec)
    return kind, None


def items_of(value):
    return value.split(",")


def clean_text(value):
    return 0 < len(value) <= VALUE_MAX and not re.search(r"[\x00-\x1f\x7f]", value)


def value_problem(spec, value):
    """None when the value is of the type, else what is wrong."""
    kind, words = split_type(spec)
    if kind == "enum":
        return None if value in words else "%r is not one of %s" % (value, ", ".join(words))
    if kind == "verb":
        return None if len(value) <= 80 and VERB_RE.match(value) else "%r is not a verb" % value
    if kind in ("label", "label-list"):
        for item in (items_of(value) if kind == "label-list" else [value]):
            if not LABEL_RE.match(item):
                return "%r is not a label (lower case, digits and hyphens)" % item
        return None
    if kind == "count":
        return None if re.match(r"^[0-9]{1,9}$", value) else "%r is not a count" % value
    if kind == "token":
        return None if TOKEN_RE.match(value) else "%r is not a plan token (12 hex digits)" % value
    if kind in ("sha", "sha-list"):
        for item in (items_of(value) if kind == "sha-list" else [value]):
            if not SHA_RE.match(item):
                return "%r is not an abbreviated commit id" % item
        return None
    for item in (items_of(value) if kind.endswith("-list") else [value]):
        if not clean_text(item):
            return "a %s is one line of at most %d characters" % (kind.replace("-list", ""), VALUE_MAX)
    return None


def is_list(spec):
    return split_type(spec)[0].endswith("-list")


def list_text(items):
    """Three items and `+N`."""
    shown = ", ".join(items[:3])
    return shown + (" +%d" % (len(items) - 3) if len(items) > 3 else "")


def human(spec, value):
    return list_text(items_of(value)) if is_list(spec) else value


def digest(value):
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def detail_value(spec, value):
    """What `detail` holds of a value: qargi's own words as they are (a list as three items and +N), a lead-chosen value as a digest."""
    if split_type(spec)[0] in LEAD_CHOSEN:
        return digest(value)
    if is_list(spec):                   # no spaces: a pair of detail ends at the next space
        items = items_of(value)
        return ",".join(items[:3] + (["+%d" % (len(items) - 3)] if len(items) > 3 else []))
    return value


def fill(template, fields, values, spec_of):
    """The template with each {name} replaced: by the value as a person reads it; an absent verb is 'this verb', any other absent field '?'."""
    def one(m):
        name = m.group(1)
        if name in values:
            return human(spec_of[name], values[name])
        return "this verb" if name == "verb" else "?"
    return PLACEHOLDER.sub(one, template)


# ---------------------------------------------------------------------------------------------------------------------------- the renderer

def render(cat, code, pairs, notice=False, verb=None, project=None, role=None):
    """(text, exit): the text to print on standard error and the exit status. Raises Defect for a caller that is wrong."""
    codes = cat["codes"]
    if code not in codes:
        raise Defect("the refusal code %s is not in lib/refusals.json" % code)
    e = codes[code]
    if e["status"] != "live":
        raise Defect("the refusal code %s is %s, not live: it is raised only once a verb of this build raises it" % (code, e["status"]))
    fields = e["fields"]
    values = {}
    for key, value in pairs:
        if key not in fields:
            raise Defect("%s has no field %s (its fields: %s)" % (code, key, ", ".join(fields) or "none"))
        if key in values:
            raise Defect("%s: the field %s is given twice" % (code, key))
        bad = value_problem(fields[key], value)
        if bad:
            raise Defect("%s: the field %s: %s" % (code, key, bad))
        values[key] = value
    who = values.get("context", "lead")
    message = fill(e["message"], fields, values, fields)
    nxt = fill(e["next"][who], fields, values, fields)
    if notice:
        return "qargi: note [%s] %s\n  next: %s\n" % (code, message, nxt), 0
    verb = values.get("verb") or (verb if verb and len(verb) <= 80 and VERB_RE.match(verb) else None)   # the caller's default is an environment value: not a verb is no verb
    detail = " ".join("%s=%s" % (k, detail_value(fields[k], values[k])) for k in fields if k in values and k != "verb")
    obj = {"code": code, "exit": e["exit"], "verb": verb, "project": project if project and PROJECT_RE.match(project) else None,
           "role": role if role and ROLE_RE.match(role) else None, "epoch": None, "state": None, "tx": None, "detail": detail}
    line = CONTRACT + " " + json.dumps(obj, separators=(",", ":"))
    while len(line.encode("utf-8")) >= LINE_MAX and obj["detail"]:
        obj["detail"] = obj["detail"][:max(0, len(obj["detail"]) - 64)]
        line = CONTRACT + " " + json.dumps(obj, separators=(",", ":"))
    return "%s\nqargi: refused [%s] %s\n  why: %s\n  next: %s\n" % (line, code, message, e["why"], nxt), e["exit"]


# ---------------------------------------------------------------------------------------------------------------------------- the stored plans

def state_dir():
    sys.path.insert(0, HERE)
    import paths
    return paths.state()


def basis_lines(text, labels):
    """[(label, [lines])] for the plan text: line N takes label N, and the lines after the last label belong to it."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    out = [[label, []] for label in labels]
    for n, line in enumerate(lines):
        if not out:
            break
        out[min(n, len(out) - 1)][1].append(line)
    return out


def basis_store(token, labels, text, state=None):
    state = state or state_dir()
    d = os.path.join(state, "plans")
    os.makedirs(d, mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    cutoff = time.time() - PLAN_DAYS * 86400
    for p in glob.glob(os.path.join(d, "*.json")):          # a plan is kept seven days
        try:
            if os.path.getmtime(p) < cutoff:
                os.unlink(p)
        except OSError:
            pass
    rec = {"token": token, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "basis": [{"label": label, "lines": lines} for label, lines in basis_lines(text, labels)]}
    path = os.path.join(d, token + ".json")
    tmp = path + ".tmp.%d" % os.getpid()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


def basis_read(token, state=None):
    if not TOKEN_RE.match(token or ""):
        return None
    try:
        with open(os.path.join(state or state_dir(), "plans", token + ".json"), encoding="utf-8") as f:
            rec = json.load(f)
        return {b["label"]: b["lines"] for b in rec["basis"]}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def basis_moved(old, new, state=None):
    """The labels whose lines differ between two stored plans, or None when either is not stored."""
    a, b = basis_read(old, state), basis_read(new, state)
    if a is None or b is None:
        return None
    labels = list(a) + [k for k in b if k not in a]
    return [k for k in labels if a.get(k) != b.get(k)]


# ---------------------------------------------------------------------------------------------------------------------------- the lint

# a raise: `refuse CODE key=value ...` or `notice CODE ...` at the start of a command in a shell file, or refusal.refuse("CODE", ...) in Python
RAISE_SH = re.compile(r"(?:^|[;&|({]|\bthen\b|\belse\b|\bdo\b)\s*(refuse|notice)\s+([a-z][a-z0-9]*(?:-[a-z0-9]+)+)\b([^;&|)\n]*)")
RAISE_PY = re.compile(r"""\brefusal\.(?:refuse|notice)\(\s*["']([a-z][a-z0-9]*(?:-[a-z0-9]+)+)["']""")
KEY_RE = re.compile(r"(?:^|\s)([a-z][a-z0-9_]*)=")


def raised(root):
    """[(path, line number, code, keys)] of every raise in lib/*.sh and lib/*.py."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, "lib", "*.sh")) + glob.glob(os.path.join(root, "lib", "*.py"))):
        rel = os.path.relpath(path, root)
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if line.lstrip().startswith("#"):
                    continue
                if path.endswith(".sh"):
                    for m in RAISE_SH.finditer(line):
                        out.append((rel, n, m.group(2), KEY_RE.findall(m.group(3))))
                else:
                    for m in RAISE_PY.finditer(line):
                        out.append((rel, n, m.group(1), []))
    return out


def seat_lists(text):
    """(the codes of R52 in order, the codes of the table of R70) read from the contract page."""
    m52 = re.search(r"\*\*R52\*\*.*?The codes in order:(.*?)Refusal:", text, re.S)
    m70 = re.search(r"\*\*R70\*\*(.*?)\*\*R71\*\*", text, re.S)
    if not m52 or not m70:
        raise ValueError("R52 or R70 is not where the lint expects it on the contract page")
    r52 = re.findall(r"`([a-z][a-z0-9]*(?:-[a-z0-9]+)+)`", m52.group(1))
    r70 = [c for c in re.findall(r"^\| `([a-z][a-z0-9]*(?:-[a-z0-9]+)+)` \|", m70.group(1), re.M)]
    return r52, r70


def check_seat_codes(cat, root):
    """(problems, notes). The codes of the seat classes are the codes of R52, in its order, and of the table of R70; with no contract page at
    this base the check is skipped and says so."""
    page = os.path.join(root, SEAT_PAGE)
    if not os.path.isfile(page):
        return [], ["seat codes: not checked, %s is absent at this base" % SEAT_PAGE.replace(os.sep, "/")]
    with open(page, encoding="utf-8") as f:
        try:
            r52, r70 = seat_lists(f.read())
        except ValueError as e:
            return [str(e)], []
    problems = []
    codes = cat["codes"]
    gate = [c for c, e in codes.items() if e.get("class") == "seat-gate"]
    door = [c for c, e in codes.items() if e.get("class") == "seat-door"]
    if gate != r52:
        problems.append("the codes of class seat-gate are %s; R52 lists %s, in that order" % (gate, r52))
    if sorted(door) != sorted(r70):
        problems.append("the codes of class seat-door are %s; the table of R70 has %s" % (sorted(door), sorted(r70)))
    return problems, []


def check_catalogue(cat):
    problems = []
    if not isinstance(cat, dict) or set(cat) != {"schema", "codes"} or cat.get("schema") != 1 or not isinstance(cat.get("codes"), dict):
        return ["the catalogue is {schema: 1, codes: {...}} and nothing else"]
    for code, e in cat["codes"].items():
        def bad(msg):
            problems.append("%s: %s" % (code, msg))
        if not CODE_RE.match(code):
            bad("a code is kebab-case")
        if not isinstance(e, dict):
            bad("an entry is an object")
            continue
        need = {"rule", "why", "class", "exit", "status", "fields", "message", "next"}
        if not need <= set(e) or set(e) - need - {"sites"}:
            bad("the keys are %s and sites; found %s" % (sorted(need), sorted(e)))
            continue
        for key in ("rule", "why", "class", "message"):
            if not isinstance(e[key], str) or not e[key].strip():
                bad("%s is a non-empty string" % key)
        if isinstance(e["why"], str) and "{" in e["why"]:
            bad("why is static: no placeholder")
        if e["exit"] not in EXITS or isinstance(e["exit"], bool):
            bad("exit is one of %s" % (EXITS,))
        if e["exit"] != {"seat-gate": 77, "guard": 2}.get(e["class"], 1):
            bad("a seat-gate code exits 77, a guard code 2 and every other code 1")
        if e["status"] not in STATUSES:
            bad("status is one of %s" % (STATUSES,))
        fields = e["fields"]
        if not isinstance(fields, dict):
            bad("fields is an object")
            continue
        for name, spec in fields.items():
            if not NAME_RE.match(name):
                bad("field name %r" % name)
            try:
                split_type(spec)
            except (ValueError, AttributeError) as err:
                bad("field %s: %s" % (name, err))
        names = set(fields)
        nxt = e["next"]
        if not isinstance(nxt, dict) or set(nxt) != set(LEADS) or not all(isinstance(nxt[k], str) and nxt[k].strip() for k in nxt):
            bad("next has a text for each of %s" % (LEADS,))
            continue
        for label, text in [("message", e["message"])] + [("next " + k, nxt[k]) for k in LEADS]:
            if isinstance(text, str):
                for name in PLACEHOLDER.findall(text):
                    if name not in names:
                        bad("%s names {%s}, which is not a field" % (label, name))
        if nxt["lead"] != nxt["host"] and fields.get("context") != "enum:lead,host":
            bad("next differs for lead and host, so the field context is enum:lead,host")
        if "context" in fields and fields["context"] != "enum:lead,host":
            bad("the field context is enum:lead,host")
        if "verb" in fields and fields["verb"] != "verb":
            bad("the field verb is of type verb")
        if "sites" in e:
            if not isinstance(e["sites"], list) or not e["sites"] or not all(isinstance(s, dict) and set(s) == {"verbs", "text"} for s in e["sites"]):
                bad("sites is a list of {verbs, text}")
    return problems


def check_raises(cat, root):
    problems = []
    codes = cat["codes"]
    seen = {}
    for path, n, code, keys in raised(root):
        if path == os.path.join("lib", "refusal.py"):
            continue
        seen.setdefault(code, []).append((path, n))
        e = codes.get(code)
        if e is None:
            problems.append("%s:%d raises %s, which is not in the catalogue" % (path, n, code))
            continue
        if e["status"] != "live":
            problems.append("%s:%d raises %s, which is %s: a code is live once a verb raises it" % (path, n, code, e["status"]))
        for key in keys:
            if key not in e["fields"]:
                problems.append("%s:%d: %s has no field %s" % (path, n, code, key))
    for code, e in codes.items():
        if e.get("status") == "live" and code not in seen and not e.get("sites"):
            problems.append("%s is live and nothing raises it: no refuse or notice names it, and it lists no print sites" % code)
    return problems


def check_page(cat, root):
    try:
        with open(os.path.join(root, PAGE), encoding="utf-8") as f:
            have = f.read()
    except OSError:
        return ["%s is missing: python3 lib/refusal.py page > %s" % (PAGE, PAGE)]
    return [] if have == page_text(cat) else ["%s is not the page of the catalogue: regenerate it with python3 lib/refusal.py page" % PAGE]


DIE_RE = re.compile(r"\bdie\s+[\"'$]")


def die_sites(root):
    """{path: count} of the `die` calls of each lib/*.sh: unclassified refusals, a number that may only go down."""
    out = {}
    for path in sorted(glob.glob(os.path.join(root, "lib", "*.sh"))):
        n = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                if not line.lstrip().startswith("#"):
                    n += len(DIE_RE.findall(line))
        if n:
            out[os.path.relpath(path, root)] = n
    return out


def read_ratchet(root):
    out = {}
    with open(os.path.join(root, RATCHET), encoding="utf-8") as f:
        for line in f:
            if line.strip() and not line.startswith("#"):
                count, _, path = line.strip().partition(" ")
                out[path] = int(count)
    return out


def check_ratchet(root):
    try:
        have = read_ratchet(root)
    except (OSError, ValueError):
        return ["%s is missing or malformed: python3 lib/refusal.py sites > %s" % (RATCHET, RATCHET)]
    now = die_sites(root)
    problems = []
    for path in sorted(set(have) | set(now)):
        a, b = now.get(path, 0), have.get(path, 0)
        if a > b:
            problems.append("%s has %d unclassified die calls, the ratchet allows %d: a new refusal is a refuse (a rule) or a fail (a failure)" % (path, a, b))
        elif a < b:
            problems.append("%s has %d unclassified die calls and the ratchet says %d: lower it (python3 lib/refusal.py sites > %s)" % (path, a, b, RATCHET))
    return problems


def check(root=None):
    """(problems, notes) of the whole lint."""
    root = root or ROOT
    cat = load(root)
    problems = check_catalogue(cat)
    notes = []
    if problems:
        return problems, notes
    sp, notes = check_seat_codes(cat, root)
    return problems + sp + check_raises(cat, root) + check_page(cat, root) + check_ratchet(root), notes


# ---------------------------------------------------------------------------------------------------------------------------- the page

def page_text(cat):
    codes = cat["codes"]
    out = ["# Refusals", "",
           "Generated from `lib/refusals.json` by `python3 lib/refusal.py page`; edit the catalogue, not this page. A refusal is a rule that",
           "stopped a verb. The catalogue names each rule once, with the reason it exists, so that a lead or a member can read the rule before a",
           "verb refuses it.", "",
           "## What a refusal prints", "",
           "On standard error, the contract line first, then the human lines:", "",
           "```",
           CONTRACT + ' {"code":"plan-stale","exit":1,"verb":"release push","project":"acme","role":null,"epoch":null,"state":null,"tx":null,"detail":"moved=head"}',
           "qargi: refused [plan-stale] ...",
           "  why: ...",
           "  next: ...",
           "```", "",
           "`detail` is qargi's own text: the typed fields as `key=value`. A value that a lead chose (a ref, a path or a name) appears in the human",
           "lines only; in `detail` it is a digest of 12 hex digits. A list prints three items and `+N`. The line stays under 4 KiB. `notice`",
           "prints `qargi: note [code] ...` and a `next:` line, with no contract line, and exits 0: the verb did its work and names a rule that",
           "will apply later.", "",
           "## What moved: the basis of a plan", "",
           "`plan_token --basis \"LABELS\"` in a plan hashes its input as `plan_token` always has (a token is the same with or without the basis) and",
           "keeps the labelled lines in `STATE/plans/TOKEN.json` (mode 600, seven days). LABELS are words separated by spaces: line N of the plan is",
           "labelled with word N, and the lines after the last word belong to it. When `--plan` names a token that is no longer the plan's,",
           "`plan-stale` says which labels differ between the plan that was shown and the plan now (`moved`), or `unrecorded` when either plan was",
           "planned without a basis. Nothing is kept in a dry run.", "",
           "## Statuses", "",
           "- `live`: a verb of this build raises the code (or, for the `verify.environment` codes, prints it at the sites the catalogue lists).",
           "- `planned`: written down so that it is reviewed early; no verb raises it yet.",
           "- `withdrawn`: no longer raised; the code is never reused.", "",
           "The codes of the classes `seat-gate` and `seat-door` are the lists of R52 and R70 of the [lead seat contract](lead-seat.md); the lint",
           "compares them with that page.", ""]
    by_class = {}
    for code, e in codes.items():
        by_class.setdefault(e["class"], []).append(code)
    out += ["## Codes", "", "| Code | Class | Exit | Status | Rule |", "| --- | --- | --- | --- | --- |"]
    for cls in sorted(by_class):
        for code in by_class[cls]:
            e = codes[code]
            out.append("| [`%s`](#%s) | %s | %d | %s | %s |" % (code, code, cls, e["exit"], e["status"], e["rule"]))
    out.append("")
    for cls in sorted(by_class):
        out += ["## Class %s" % cls, ""]
        for code in by_class[cls]:
            e = codes[code]
            out += ["### %s" % code, "",
                    "- Rule: %s." % e["rule"].rstrip("."),
                    "- Why: %s." % e["why"].rstrip("."),
                    "- Exit %d, %s." % (e["exit"], e["status"]),
                    "- Fields: %s." % (", ".join("`%s` (%s)" % (k, v) for k, v in e["fields"].items()) or "none"),
                    "- Message: `%s`" % e["message"],
                    "- Next, for a lead: %s" % e["next"]["lead"]]
            if e["next"]["host"] != e["next"]["lead"]:
                out.append("- Next, in the owner's own session (`host`): %s" % e["next"]["host"])
            if e.get("sites"):
                out.append("- Printed at %d sites; [verify.environment](verify-environment.md) describes them." % len(e["sites"]))
            out.append("")
    while out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------------------------------------------------------- the command line

def parse_raise(argv):
    opts = {"verb": None, "project": None, "role": None}
    rest = list(argv)
    while rest and rest[0] in ("--verb", "--project", "--role"):
        if len(rest) < 2:
            raise Defect("%s needs a value" % rest[0])
        opts[rest[0][2:]] = rest[1]
        rest = rest[2:]
    if not rest:
        raise Defect("a refusal code is needed")
    pairs = []
    for word in rest[1:]:
        key, eq, value = word.partition("=")
        if not eq or not NAME_RE.match(key):
            raise Defect("%r is not key=value" % word)
        pairs.append((key, value))
    return rest[0], pairs, opts


def main(argv):
    cmd = argv[0] if argv else ""
    try:
        if cmd in ("refuse", "notice"):
            code, pairs, opts = parse_raise(argv[1:])
            text, rc = render(load(), code, pairs, notice=(cmd == "notice"), **opts)
            sys.stderr.write(text)
            return rc
        if cmd == "check":
            root = argv[2] if len(argv) == 3 and argv[1] == "--root" else ROOT
            problems, notes = check(root)
            for n in notes:
                print(n)
            for p in problems:
                print("fail: " + p)
            print("refusals: %d codes, %d problems" % (len(load(root)["codes"]), len(problems)))
            return 1 if problems else 0
        if cmd == "page":
            sys.stdout.write(page_text(load()))
            return 0
        if cmd == "sites":
            root = argv[2] if len(argv) == 3 and argv[1] == "--root" else ROOT
            print("# unclassified die calls of each lib/*.sh: a shrink-only ratchet (python3 lib/refusal.py sites > tests/refusal-sites.txt)")
            for path, n in die_sites(root).items():
                print("%d %s" % (n, path))
            return 0
        if cmd == "basis" and len(argv) == 4 and argv[1] == "store":
            if not TOKEN_RE.match(argv[2]):
                raise Defect("%r is not a plan token" % argv[2])
            labels = argv[3].split()
            if not labels or any(not LABEL_RE.match(x) for x in labels):
                raise Defect("--basis takes labels: lower case words, digits and hyphens, separated by spaces")
            basis_store(argv[2], labels, sys.stdin.read())
            return 0
        if cmd == "basis" and len(argv) == 4 and argv[1] == "moved":
            moved = basis_moved(argv[2], argv[3])
            if moved is None:
                return 1
            print(",".join(moved))
            return 0
    except Defect as e:
        sys.stderr.write("qargi: defect: %s\n" % e)
        return 70
    except (OSError, ValueError) as e:
        sys.stderr.write("qargi: defect: refusal.py: %s\n" % e)
        return 70
    sys.stderr.write("usage: refusal.py refuse|notice [--verb V] [--project P] [--role R] CODE [KEY=VALUE ...] | check [--root DIR] | page | sites [--root DIR] | basis store TOKEN LABELS | basis moved OLD NEW\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
