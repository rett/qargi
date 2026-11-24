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
  refusal.py basis store TOKEN LABELS --verb VERB --target PROJECT:OBJECT
                                        reads the plan on standard input, one labelled line per label, into STATE/plans/TOKEN.json: the record
                                        `qargi.plan/0` (LABELS are `label` or `label:kind`; qargi plan show prints it)
  refusal.py basis scratch TOKEN LABELS the same without them: the scratch copy of a dry run, only {token, basis}, which `plan show` does not know
  refusal.py basis moved OLD NEW        the labels whose lines differ between two stored plans, comma separated; exit 1 when either is unknown

The environment names the state directory (QARGI_STATE, else the layout of lib/paths.py). Library use: load, render, check, page_text."""
import calendar
import errno
import glob
import hashlib
import json
import os
import re
import stat
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
CATALOGUE = os.path.join("lib", "refusals.json")
PAGE = os.path.join("docs", "reference", "refusals.md")
SEAT_PAGE = os.path.join("docs", "reference", "lead-seat.md")
RATCHET = os.path.join("tests", "refusal-sites.txt")
SITES_SEE = {"verify-environment": "[verify.environment](verify-environment.md) describes them.",       # per class: where the sites of a code that no verb raises are described
             "guard": "`qargi help guard` says what a member's guard refuses."}
CONTRACT = "qargi-refusal/1"
LINE_MAX = 4096
PLAN_DAYS = 7                       # a stored plan is kept this long
PLAN_SCHEMA = "qargi.plan/0"        # draft: it may change without notice until a consumer publishes it as qargi.plan/1
PLAN_KINDS = ("ref", "path", "name", "sha", "label", "count")   # what a line of a stored plan is, in the types of the catalogue; ref, path and name are lead-chosen
PLAN_DEFAULT_KIND = "name"          # a label given without a kind: the conservative one, a lead-chosen text
PLAN_MAX = 1 << 20                  # a stored plan is read up to this size
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"

STATUSES = ("live", "planned", "withdrawn")
EXITS = (1, 2, 77)                  # a refusal, a guard's deny or a verb that does not apply to the project's methodology, a lead refusal of the seat
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
        if not arg or any(not LABEL_RE.fullmatch(w) for w in words) or len(set(words)) != len(words):
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
        return None if len(value) <= 80 and VERB_RE.fullmatch(value) else "%r is not a verb" % value
    if kind in ("label", "label-list"):
        for item in (items_of(value) if kind == "label-list" else [value]):
            if not LABEL_RE.fullmatch(item):
                return "%r is not a label (lower case, digits and hyphens)" % item
        return None
    if kind == "count":
        return None if re.fullmatch(r"[0-9]{1,9}", value) else "%r is not a count" % value
    if kind == "token":
        return None if TOKEN_RE.fullmatch(value) else "%r is not a plan token (12 hex digits)" % value
    if kind in ("sha", "sha-list"):
        for item in (items_of(value) if kind == "sha-list" else [value]):
            if not SHA_RE.fullmatch(item):
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
    verb = values.get("verb") or (verb if verb and len(verb) <= 80 and VERB_RE.fullmatch(verb) else None)   # the caller's default is an environment value: not a verb is no verb
    detail = " ".join("%s=%s" % (k, detail_value(fields[k], values[k])) for k in fields if k in values and k != "verb")
    obj = {"code": code, "exit": e["exit"], "verb": verb, "project": project if project and PROJECT_RE.fullmatch(project) else None,
           "role": role if role and ROLE_RE.fullmatch(role) else None, "epoch": None, "state": None, "tx": None, "detail": detail}
    line = CONTRACT + " " + json.dumps(obj, separators=(",", ":"))
    while len(line.encode("utf-8")) >= LINE_MAX and obj["detail"]:
        obj["detail"] = obj["detail"][:max(0, len(obj["detail"]) - 64)]
        line = CONTRACT + " " + json.dumps(obj, separators=(",", ":"))
    return "%s\nqargi: refused [%s] %s\n  why: %s\n  next: %s\n" % (line, code, message, e["why"], nxt), e["exit"]


def refuse(code, pairs=(), verb=None, project=None, role=None, out=None):
    """Print the refusal on standard error (or out) as `refuse` of lib/lib.sh does, and return its exit status: for a verb written in Python. A Defect for a caller that is wrong."""
    text, rc = render(load(), code, list(pairs), verb=verb, project=project, role=role)
    (out or sys.stderr).write(text)
    return rc


# ---------------------------------------------------------------------------------------------------------------------------- the stored plans

def state_dir():
    sys.path.insert(0, HERE)
    import paths
    return paths.state()


def now_epoch():
    """The clock of the plan records: the time, or QARGI_PLAN_NOW (UTC, YYYY-MM-DDTHH:MM:SSZ) when that is set (tests)."""
    given = os.environ.get("QARGI_PLAN_NOW", "")
    if given:
        try:
            return calendar.timegm(time.strptime(given, TIME_FORMAT))
        except ValueError:
            raise Defect("QARGI_PLAN_NOW is %r, not a time like 2026-11-22T10:00:00Z" % given)
    return int(time.time())


def stamp(epoch):
    return time.strftime(TIME_FORMAT, time.gmtime(epoch))


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


def parse_labels(words):
    """[(label, kind)] of the words `label` or `label:kind`; a label without a kind is PLAN_DEFAULT_KIND. A word that is neither is a Defect."""
    out = []
    for word in words:
        label, colon, kind = word.partition(":")
        if not LABEL_RE.fullmatch(label) or (colon and kind not in PLAN_KINDS):
            raise Defect("--basis takes labels: lower case words, digits and hyphens, each with an optional :kind (%s), separated by spaces" % ", ".join(PLAN_KINDS))
        out.append((label, kind or PLAN_DEFAULT_KIND))
    return out


def plan_lines(text, specs):
    """[{label, kind, value}], one for each line of the plan text, in order: the label of line N is the Nth, the last one for every line after it."""
    lines = text.split("\n")
    if text.endswith("\n"):
        lines.pop()
    elif text == "":
        lines = []
    return [{"label": specs[min(n, len(specs) - 1)][0], "kind": specs[min(n, len(specs) - 1)][1], "value": value} for n, value in enumerate(lines)]


def plan_input(lines, newline):
    """The text the lines of a record were made from: the bytes that were hashed."""
    return "\n".join(x["value"] for x in lines) + ("\n" if newline else "")


def target_of(spec):
    """(project, object) of PROJECT:OBJECT; a Defect for anything else."""
    project, _, obj = spec.partition(":")
    if not PROJECT_RE.fullmatch(project) or not clean_text(obj):
        raise Defect("--target is PROJECT:OBJECT: a project and the one object the verb acts on, one line of at most %d characters" % VALUE_MAX)
    return project, obj


def basis_store(token, specs, text, verb=None, target=None, state=None):
    """Keep the plan as the record qargi.plan/0 in STATE/plans/TOKEN.json: mode 600, in a directory of mode 700, by a temporary file and a rename.
    specs is [(label, kind)], target (project, object). The old `basis` key, which `basis moved` reads, stays. With no verb it keeps only {token, basis}: the scratch copy
    a dry run compares a token with, which `plan show` does not know (plan-unknown)."""
    state = state or state_dir()
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if verb is not None and token != digest[:12]:
        raise Defect("the token %s is not the start of the hash of the plan" % token)
    if verb is not None and not (len(verb) <= 80 and VERB_RE.fullmatch(verb)):
        raise Defect("%r is not a verb" % verb)
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
    basis = []
    for label, lines in basis_lines(text, [x[0] for x in specs]):
        if basis and basis[-1]["label"] == label:       # a label given once for each of several lines (the parts of a waiver): the basis groups them
            basis[-1]["lines"] += lines
        else:
            basis.append({"label": label, "lines": lines})
    created = now_epoch()
    rec = {"token": token, "basis": basis} if verb is None else {
        "schema": PLAN_SCHEMA, "verb": verb, "context": "lead", "target": {"project": target[0], "object": target[1]},
        "lines": plan_lines(text, specs), "input_sha256": digest, "input_newline": text.endswith("\n"), "token": token,
        "created": stamp(created), "expires": stamp(created + PLAN_DAYS * 86400), "basis": basis}
    path = os.path.join(d, token + ".json")
    tmp = path + ".tmp.%d" % os.getpid()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)                # exactly 600: a leftover temporary file of another mode (O_TRUNC keeps it) or a umask is not the record's mode
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f, separators=(",", ":"))
        f.write("\n")
    os.replace(tmp, path)


class PlanRefusal(Exception):
    """A plan record that cannot be shown: the code of the refusal and its fields."""

    def __init__(self, code, pairs):
        Exception.__init__(self, code)
        self.code, self.pairs = code, pairs


PLAN_KEYS = {"schema", "verb", "context", "target", "lines", "input_sha256", "input_newline", "token", "created", "expires"}


def plan_problem(rec, token):
    """None when rec is a sound record of the token, else a word (a label) for what is wrong. The hash (input_sha256) binds the lines and input_newline only; the verb, the
    target, the context, the labels, the kinds and the times are checked for their form (the types of the catalogue, and expires being created plus PLAN_DAYS days), not signed."""
    if not isinstance(rec, dict) or not PLAN_KEYS <= set(rec) or set(rec) - PLAN_KEYS - {"basis"}:
        return "bad-form"
    if rec["schema"] != PLAN_SCHEMA:
        return "unknown-schema"
    verb, target, lines = rec["verb"], rec["target"], rec["lines"]
    if not (isinstance(verb, str) and len(verb) <= 80 and VERB_RE.fullmatch(verb)) or rec["context"] not in LEADS:
        return "bad-form"
    if not (isinstance(target, dict) and set(target) == {"project", "object"} and isinstance(target["project"], str) and PROJECT_RE.fullmatch(target["project"])
            and isinstance(target["object"], str) and clean_text(target["object"])):
        return "bad-form"
    if not isinstance(lines, list) or not all(isinstance(x, dict) and set(x) == {"label", "kind", "value"} and isinstance(x["label"], str) and LABEL_RE.fullmatch(x["label"])
                                              and x["kind"] in PLAN_KINDS and isinstance(x["value"], str) and "\n" not in x["value"] for x in lines):
        return "bad-form"
    if not isinstance(rec["input_newline"], bool) or "basis" in rec and not isinstance(rec["basis"], list):
        return "bad-form"
    for key in ("created", "expires"):
        if not isinstance(rec[key], str) or not time_of(rec[key]):
            return "bad-form"
    if time_of(rec["expires"]) != time_of(rec["created"]) + PLAN_DAYS * 86400:
        return "bad-form"               # the hash does not cover the times: a record is kept seven days from its creation, so another life is an edit
    digest = rec["input_sha256"]
    if not (isinstance(digest, str) and re.fullmatch(r"[0-9a-f]{64}", digest) and rec["token"] == token and digest.startswith(token)):
        return "bad-form"
    try:
        if hashlib.sha256(plan_input(lines, rec["input_newline"]).encode("utf-8")).hexdigest() != digest:
            return "hash-mismatch"
    except UnicodeError:
        return "hash-mismatch"
    return None


def time_of(text):
    try:
        return calendar.timegm(time.strptime(text, TIME_FORMAT))
    except ValueError:
        return None


def plan_read(token, state=None):
    """The stored record of the token, a dict, after every check; PlanRefusal (plan-unknown, plan-record-invalid, plan-expired) otherwise. Reads only:
    the directory and the file are opened without following a link, the file must be a regular file of one link and mode 600, nothing is removed."""
    def invalid(problem):
        return PlanRefusal("plan-record-invalid", [("token", token), ("problem", problem)])
    def unknown():
        return PlanRefusal("plan-unknown", [("given", token)] if clean_text(token) else [])
    if not TOKEN_RE.fullmatch(token or ""):
        raise unknown()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        sfd = os.open(state or state_dir(), flags | os.O_DIRECTORY)
    except OSError:
        raise unknown()
    try:
        try:
            pfd = os.open("plans", flags | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=sfd)
        except FileNotFoundError:
            raise unknown()
        except OSError as e:            # a link or not a directory, or one that cannot be opened
            raise invalid("bad-directory" if e.errno in (errno.ELOOP, errno.ENOTDIR) else "unreadable")
        try:
            try:
                fd = os.open(token + ".json", flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=pfd)
            except FileNotFoundError:
                raise unknown()
            except OSError as e:
                raise invalid("link" if e.errno == errno.ELOOP else "unreadable")
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    raise invalid("not-a-file")
                if st.st_nlink != 1:
                    raise invalid("links")
                if stat.S_IMODE(st.st_mode) != 0o600:
                    raise invalid("wrong-mode")
                data = b""
                while len(data) <= PLAN_MAX:
                    chunk = os.read(fd, PLAN_MAX + 1 - len(data))
                    if not chunk:
                        break
                    data += chunk
            except OSError:
                raise invalid("unreadable")
            finally:
                os.close(fd)
        finally:
            os.close(pfd)
    finally:
        os.close(sfd)
    if len(data) > PLAN_MAX:
        raise invalid("too-large")
    try:
        rec = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError, RecursionError):      # RecursionError: a file of brackets nested deeper than the parser goes
        raise invalid("bad-json")
    if isinstance(rec, dict) and "schema" not in rec:
        raise unknown()                 # a record of before this schema: {token, at, basis}
    problem = plan_problem(rec, token)
    if problem:
        raise invalid(problem)
    if time_of(rec["expires"]) <= now_epoch():
        raise PlanRefusal("plan-expired", [("token", token)])
    return rec


def basis_read(token, state=None):
    if not TOKEN_RE.fullmatch(token or ""):
        return None
    try:
        with open(os.path.join(state or state_dir(), "plans", token + ".json"), encoding="utf-8") as f:
            rec = json.load(f)
        out = {}
        for b in rec["basis"]:
            label, lines = b["label"], b["lines"]
            if not (isinstance(label, str) and LABEL_RE.fullmatch(label) and isinstance(lines, list) and all(isinstance(x, str) for x in lines)):
                return None             # a damaged or hand-edited file is no record: the caller says "unrecorded"
            out[label] = lines
        return out
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
        if not CODE_RE.fullmatch(code):
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
        if e["exit"] != {"seat-gate": 77, "guard": 2, "methodology": 2}.get(e["class"], 1):
            bad("a seat-gate code exits 77, a guard or methodology code 2 and every other code 1")
        if e["status"] not in STATUSES:
            bad("status is one of %s" % (STATUSES,))
        fields = e["fields"]
        if not isinstance(fields, dict):
            bad("fields is an object")
            continue
        for name, spec in fields.items():
            if not NAME_RE.fullmatch(name):
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
           "`plan_token --basis \"LABELS\" --verb VERB --target PROJECT:OBJECT` in a plan hashes its input as `plan_token` always has (a token is the same with or without the basis) and",
           "keeps the plan in `STATE/plans/TOKEN.json` (mode 600, seven days) as the record `qargi.plan/0`, which `qargi plan show TOKEN` prints. LABELS are words separated by spaces,",
           "each `label` or `label:kind` (`ref`, `path`, `name`, `sha`, `label` or `count`; a label with no kind is `name`): line N of the plan is",
           "labelled with word N, and the lines after the last word belong to it. When `--plan` names a token that is no longer the plan's,",
           "`plan-stale` says which labels differ between the plan that was shown and the plan now (`moved`), or `unrecorded` when either plan was",
           "planned without a basis. Nothing is kept in a dry run.", "",
           "## Statuses", "",
           "- `live`: a verb of this build raises the code (or, for the `verify.environment` codes and the guard's, prints it at the sites the catalogue lists).",
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
                n = len(e["sites"])
                out.append("- Printed at %d site%s; %s" % (n, "" if n == 1 else "s", SITES_SEE.get(e["class"], "the catalogue lists them.")))
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
        if not eq or not NAME_RE.fullmatch(key):
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
        if cmd == "basis" and len(argv) >= 4 and argv[1] in ("store", "scratch"):
            if not TOKEN_RE.fullmatch(argv[2]):
                raise Defect("%r is not a plan token" % argv[2])
            specs = parse_labels(argv[3].split()) if argv[3].split() else []
            if not specs:
                raise Defect("--basis takes labels: lower case words, digits and hyphens, separated by spaces")
            given = dict(zip(argv[4::2], argv[5::2]))
            if argv[1] == "store" and (len(argv) % 2 or set(given) != {"--verb", "--target"} or len(given) * 2 != len(argv) - 4):
                raise Defect("basis store takes the labels, then --verb VERB and --target PROJECT:OBJECT")
            if argv[1] == "scratch" and len(argv) != 4:
                raise Defect("basis scratch takes the token and the labels")
            raw = sys.stdin.buffer.read()
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                return 1                # a plan that is not UTF-8 cannot be kept: not a defect, the caller says so and goes on
            try:
                if argv[1] == "scratch":
                    basis_store(argv[2], specs, text)
                else:
                    basis_store(argv[2], specs, text, given["--verb"], target_of(given["--target"]))
            except OSError:
                return 1                # the plan cannot be kept (a state directory that cannot be written): not a defect, the caller says so and goes on
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
    sys.stderr.write("usage: refusal.py refuse|notice [--verb V] [--project P] [--role R] CODE [KEY=VALUE ...] | check [--root DIR] | page | sites [--root DIR] | basis store TOKEN LABELS --verb VERB --target PROJECT:OBJECT | basis scratch TOKEN LABELS | basis moved OLD NEW\n")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
