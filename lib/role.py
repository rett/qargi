#!/usr/bin/env python3
"""qargi role: what a member or a cloud agent is for. A role is a directory with role.json ({class: write|read-only,
description}) and ROLE.md (its instructions). The four built-in roles (build, write, review, test) ship in <tool>/roles;
yours live in <config>/roles/<name>/. The class fixes what the guard allows (read-only: nothing in the clone changes); the
text of a role never changes the guard.

Usage: role.py list
       role.py show NAME
       role.py prompt NAME     the instructions as a task block carries them
       role.py check [NAME]    validate one role, or all

bin/qargi imports this module (bytecode is cached for an imported module, not for a script) and calls main(). The shell
helpers of lib/lib.sh that other scripts still use (role_dir, role_names, role_class) read the same directories; keep the
two in step. role.json is read the way `jq` read it before this was Python: `.class // "write"` and the like, so a role.json
that is not an object, has a number for a description or holds several values gives the output it always gave."""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

BUILTIN = ("build", "review", "write", "test")
NAME = re.compile(r"[a-z][a-z0-9]{0,23}")
DEFAULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "model-defaults.json")
USAGE = "usage: qargi role list|show|prompt|check ..."


class Exit(Exception):
    def __init__(self, code, message=""):
        self.code, self.message = code, message


def die(message, code=1):
    raise Exit(code, "qargi: %s\n" % message)


def tool():
    return P.tool_root()


def conf():
    return P.conf()


# ---- reading role.json as jq did -------------------------------------------------------------------------------------------

class JqError(Exception):
    pass


def jq_type(v):
    return "null" if v is None else "boolean" if isinstance(v, bool) else "number" if isinstance(v, (int, float)) else \
        "string" if isinstance(v, str) else "array" if isinstance(v, list) else "object"


def read_text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8", "replace")


def parse_stream(text):
    """The JSON values of a file the way jq reads a stream: (values, error): the values before the first thing that does not parse."""
    dec, i, n, vals = json.JSONDecoder(), 0, len(text), []
    while True:
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            return vals, False
        try:
            v, i = dec.raw_decode(text, i)
        except (ValueError, RecursionError):
            return vals, True
        vals.append(v)


def index(v, key):
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get(key)
    raise JqError('Cannot index %s with string ("%s")' % (jq_type(v), key))


def falsy(x):
    return x is None or x is False


def raw(x):
    """jq -r: a string as it is, anything else as JSON."""
    return x if isinstance(x, str) else json.dumps(x, indent=2, ensure_ascii=False)


def jq_run(path, fn):
    """Apply fn to every value of the JSON file (a string, or None for no output); the strings, in order. What jq reports goes to stderr."""
    try:
        text = read_text(path)
    except OSError as e:
        sys.stderr.write("jq: error: Could not open %s: %s\n" % (path, e.strerror))
        return []
    vals, bad = parse_stream(text)
    out = []
    for v in vals:
        try:
            r = fn(v)
        except JqError as e:
            sys.stderr.write("jq: error (at %s:%d): %s\n" % (path, text.count("\n"), e))
            continue
        if r is not None:
            out.append(r)
    if bad:
        sys.stderr.write("qargi: %s is not valid JSON\n" % path)
    return out


def subst(outs):
    """The text of a $(...) around those outputs."""
    return "\n".join(outs).rstrip("\n")


def json_ok(path):
    """jq -e . FILE: some value, the last one not null or false, and nothing that does not parse."""
    try:
        vals, bad = parse_stream(read_text(path))
    except OSError:
        return False
    return not bad and bool(vals) and not falsy(vals[-1])


def with_default(key, default):
    """`.key // default` (`// empty` when default is None)"""
    def fn(v):
        x = index(v, key)
        return default if falsy(x) else raw(x)
    return fn


def role_class_of(path):
    """.class // "write"  (the text of the command substitution)"""
    return subst(jq_run(path, with_default("class", "write")))


# ---- the roles -------------------------------------------------------------------------------------------------------------

def is_base(name):
    """A cloud base (worker, reviewer): model-defaults.json gives it a class. No role may take the name."""
    try:
        with open(DEFAULTS) as f:
            entry = json.load(f)["bases"][name]
        return not falsy(entry["class"])
    except (OSError, ValueError, KeyError, TypeError):
        return False


def role_dir(name):
    if is_base(name):
        return None
    for d in ("%s/roles/%s" % (tool(), name), "%s/roles/%s" % (conf(), name)):
        if os.path.isfile(d + "/role.json") and os.path.isfile(d + "/ROLE.md"):
            return d
    return None


def role_names():
    """The built-in roles, then yours in name order."""
    names = list(BUILTIN)
    base = conf() + "/roles"
    try:
        entries = sorted(e for e in os.listdir(base) if not e.startswith(".") and os.path.isdir(base + "/" + e))
    except OSError:
        entries = []
    for r in entries:
        d = base + "/" + r
        if r in BUILTIN or not NAME.fullmatch(r) or r == "lead" or is_base(r):
            continue
        if os.path.isfile(d + "/role.json") and os.path.isfile(d + "/ROLE.md"):
            names.append(r)
    return names


def role_class(name):
    if name == "lead":
        return "coordinator"
    return role_class_of(role_dir(name) + "/role.json")


def check_one(n):
    """-> (the problems, 0 or 1)"""
    if is_base(n):
        return ["%s: reserved for a cloud base (worker, reviewer); no role may take it" % n], 1
    d = role_dir(n)
    if d is None:
        return ["%s: no such role (needs role.json and ROLE.md)" % n], 1
    if not json_ok(d + "/role.json"):
        return ["%s: role.json is not valid JSON" % n], 1
    out, bad = [], 0
    c = subst(jq_run(d + "/role.json", with_default("class", None)))
    if c not in ("write", "read-only"):
        out.append("%s: class must be write or read-only (got '%s')" % (n, c or "none"))
        bad = 1
    if not NAME.fullmatch(n):
        out.append("%s: the name is one lower-case token (letters, digits)" % n)
        bad = 1
    if n == "lead":
        out.append("lead is reserved for the team coordinator")
        bad = 1
    try:
        empty = os.stat(d + "/ROLE.md").st_size == 0
    except OSError:
        empty = True
    if empty:
        out.append("%s: ROLE.md is empty" % n)
        bad = 1
    return out, bad


# ---- the verbs -------------------------------------------------------------------------------------------------------------

class Out:
    def __init__(self):
        self.parts = []

    def line(self, s=""):
        self.parts.append((s + "\n").encode("utf-8", "surrogateescape"))

    def bytes(self, b):
        self.parts.append(b)

    def flush(self):
        sys.stdout.flush()
        sys.stdout.buffer.write(b"".join(self.parts))
        sys.stdout.buffer.flush()
        self.parts = []


def cat(out, path):
    """cat FILE; the status of cat."""
    try:
        with open(path, "rb") as f:
            out.bytes(f.read())
        return 0
    except OSError as e:
        out.flush()
        sys.stderr.write("cat: %s: %s\n" % (path, e.strerror))
        return 1


def verb_list(out):
    out.line("%-12s %-10s %-9s %s" % ("ROLE", "CLASS", "WHERE", "DESCRIPTION"))
    for r in role_names():
        d = role_dir(r)
        if d is None:
            continue
        where = "built-in" if d.startswith(tool() + "/") else "user"
        cls = role_class_of(d + "/role.json")
        desc = subst(jq_run(d + "/role.json", with_default("description", "")))
        out.line("%-12s %-10s %-9s %s" % (r, cls, where, desc))
    return 0


def named(args, what):
    n = args[0] if args else ""
    if not n:
        die("usage: qargi role %s NAME" % what, 2)
    d = role_dir(n)
    if d is None:
        die("no role named %s (qargi role list)" % n)
    return n, d


def description_line(v):
    """"description: " + (.description // "")"""
    x = index(v, "description")
    x = "" if falsy(x) else x
    if not isinstance(x, str):
        raise JqError('string ("description: ") and %s (%s) cannot be added' % (jq_type(x), json.dumps(x, separators=(",", ":"), ensure_ascii=False)))
    return "description: " + x


def verb_show(out, args):
    n, d = named(args, "show")
    out.line("role: " + n)
    out.line("dir: " + d)
    out.line("class: " + role_class(n))
    for s in jq_run(d + "/role.json", description_line):
        out.line(s)
    out.line()
    return cat(out, d + "/ROLE.md")


def verb_prompt(out, args):
    n, d = named(args, "prompt")
    return cat(out, d + "/ROLE.md")


def verb_check(out, args):
    # the shell word-split an unquoted argument: "a b" names two roles
    names = re.split(r"[ \t\n]+", args[0]) if args and args[0] else role_names()
    rc = 0
    for n in names:
        if not n:
            continue
        lines, bad = check_one(n)
        for s in lines:
            out.line(s)
        rc = rc or bad
    if rc == 0:
        out.line("roles: ok")
    return rc


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    verb, args = (argv[0] if argv else ""), argv[1:]
    out = Out()
    try:
        if verb == "list":
            rc = verb_list(out)
        elif verb == "show":
            rc = verb_show(out, args)
        elif verb == "prompt":
            rc = verb_prompt(out, args)
        elif verb == "check":
            rc = verb_check(out, args)
        else:
            die(USAGE, 2)
    except Exit as e:
        out.flush()
        sys.stderr.write(e.message)
        return e.code
    out.flush()
    return rc


if __name__ == "__main__":
    sys.exit(main())
