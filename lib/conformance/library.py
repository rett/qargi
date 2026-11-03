"""The lifecycle of the packs in the provider library (~/.qargi/config/packs/providers/NAME/): a provider (a runtime definition), a
catalog (the models of a family) or an extension (what a project adds to a runtime). The verbs of `qargi provider` that make, change,
check and remove them; lib/provider.py hands the verbs to this module. A library for lib/provider.py: it does nothing when run.

Every verb that writes is a plan first: it prints the review of what would be stored (files, every executable with its sha256, URLs,
network commands, flagged constructs, secret findings), and a token over the content. The same command with `--plan TOKEN --approved
"<the user's go-ahead>"` applies it, but only when the content is still what the plan showed, and, when the pack holds executables,
only with `--approve-exec a,b` naming EVERY one of them (a missing or an extra name refuses). Each applied verb leaves a line in the
audit log. The hashes of the executables are recorded with the pack and checked again before one is run (provider.exec_copy).

  new NAME [--kind K] [--from F]    scaffold an unsealed pack (it cannot be used until it is sealed)
  import SOURCE [--name N] ...      store a pack from a directory, a JSON file or an https git URL; it is sealed on approval
  seal NAME                         approve the pack as it is now, after you edited it; earlier verification records no longer match
  remove NAME                       refused while a project, an extension or a runtime refers to it
  enable | disable PROJECT EXT      switch an extension on or off for one project (models.extensions of its answers)
  check NAME | DIR [--project P]    the review, the schema and the hermetic cases (lib/conformance/cases.py); for a sealed library pack
                                    it writes the verification records of the capabilities whose cases all passed. An extension is
                                    checked composed onto its runtime (the project's, or the one it names), alone, and what it
                                    provides is recorded bound to the extension and that runtime
  attest NAME CAP [--project P] ... the plan and the record of a live check YOU ran; it runs nothing and spends nothing

Trust: a pack with executables is code that runs with the user's rights. Import never enables or links it; enabling is its own plan. The
guard refuses every verb here to a member (the lifecycle verbs write the library and the state), but it cannot contain an approved
executable: it can read what it is given, reach the network and write where the user can."""
import contextlib
import getpass
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.realpath(__file__))
LIB = os.path.dirname(HERE)
if LIB not in sys.path:
    sys.path.insert(0, LIB)
import provider as P  # noqa: E402                         (lib/provider.py puts itself in sys.modules under this name when it is the script)
import gated_answers as GA  # noqa: E402
from conformance import review as R  # noqa: E402

_print = print


def print(*args, **kw):  # noqa: A001  (this module's print: every word is written through R.vis)
    """The print of this module. What a pack holds (file names, lines of its files, strings of its definition) is printed for a person to read
    and approve, so a control, escape or bidi character in it is written out (\\x1b, \\u202e) and cannot erase, hide or reorder a line of the review."""
    _print(*[R.vis(a) if isinstance(a, str) else a for a in args], **kw)


KINDS = ("provider", "catalog", "extension")
KEYS = {"provider": "provider", "catalog": "family", "extension": "extension"}
FROM_KINDS = ("minimal", "command", "hook-cli")
RESULTS = ("pass", "fail")


class Usage(Exception):
    """Wrong arguments: the usage line and exit status 2."""


class Failure(Exception):
    """The verb cannot go on (nothing was changed, unless it says): exit status 1."""


class Refusal(Failure):
    """A refusal by policy (a name that is taken, a pack that is not allowed): exit status 2."""


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def who():
    try:
        return getpass.getuser()
    except Exception:
        return "unknown"


def token_of(*parts):
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def audit(verb, detail, opts):
    """One line in STATE/audit.log, like lib.sh's audit_log: ts, verb, detail, asked, approved, nested."""
    d = P._state_dir()
    os.makedirs(d, exist_ok=True)
    f = os.path.join(d, "audit.log")
    line = {"ts": now(), "verb": verb, "detail": detail, "asked": opts.get("--asked", ""), "approved": opts.get("--approved", ""), "nested": False}
    with open(f, "a") as fh:
        fh.write(json.dumps(line) + "\n")
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def parse(args, valued=(), flags=()):
    opts, pos, i = {}, [], 0
    while i < len(args):
        a = args[i]
        if a in valued:
            if i + 1 >= len(args):
                raise Usage("%s needs a value" % a)
            opts[a] = args[i + 1]
            i += 2
        elif a in flags:
            opts[a] = True
            i += 1
        elif a.startswith("--"):
            raise Usage("unknown option %s" % a)
        else:
            pos.append(a)
            i += 1
    return opts, pos


GATE = ("--plan", "--approved", "--approve-exec", "--asked")


def exec_names(opts):
    raw = opts.get("--approve-exec")
    return sorted({x.strip() for x in raw.split(",") if x.strip()}) if raw else []


def gate(opts, tok, execs, what):
    """True when the verb may apply. Without --approved the plan is over: the token is printed. With it, the token must be the plan's
    and --approve-exec must name exactly the executables (Failure otherwise, nothing changed)."""
    if not opts.get("--approved"):
        cmd = "--plan %s --approved \"<the user's go-ahead after reading the review>\"" % tok
        if execs:
            cmd += " --approve-exec %s" % ",".join(sorted(execs))
        print("plan token: %s   (%s with: %s)" % (tok, what, cmd))
        return False
    if opts.get("--plan") != tok:
        raise Failure("the plan changed or --plan is missing: run the plan, show it to the user, then apply exactly that with --plan %s" % tok)
    named = exec_names(opts)
    missing = sorted(set(execs) - set(named))
    extra = sorted(set(named) - set(execs))
    if missing:
        raise Failure("the pack holds executables that --approve-exec does not name: %s; name every one (the review lists them); nothing was changed" % ", ".join(missing))
    if extra:
        raise Failure("--approve-exec names %s, which %s not an executable of this pack; name exactly the executables the review lists; nothing was changed"
                      % (", ".join(extra), "is" if len(extra) == 1 else "are"))
    return True


def library():
    return P.library_dir()


def pack_dir(name):
    return os.path.join(library(), name)


def valid_name(name):
    return isinstance(name, str) and bool(P.NAME_RE.match(name)) and len(name) <= 40 and name not in P.NON_PROVIDERS


def read_definition(directory):
    f = os.path.join(directory, "definition.json")
    try:
        with open(f, encoding="utf-8") as fh:
            d = json.load(fh)
    except OSError:
        raise Failure("%s has no definition.json" % directory)
    except ValueError as e:
        raise Failure("definition.json is not valid JSON: %s" % e)
    if not isinstance(d, dict):
        raise Failure("definition.json is not a JSON object")
    return d


def name_of(doc):
    k = KEYS.get(doc.get("kind"))
    return doc.get(k) if k else None


def doc_findings(doc, name, directory=None):
    """(fail, warn) message lists for a definition document, whatever its kind. With the pack's directory, a provider's contract addenda must
    be there too."""
    if not isinstance(doc, dict) or doc.get("kind") not in KINDS:
        return ["kind: %r is not one of %s" % (doc.get("kind") if isinstance(doc, dict) else None, ", ".join(KINDS))], []
    f = P.validate2(doc, name)
    fails = [m for lvl, m in f if lvl == "fail"]
    if doc["kind"] == "provider" and P.barrier_claim_problem(doc):      # a claimed barrier with nothing behind it is a fail-open: never verified
        fails.append(P.barrier_claim_problem(doc))
    if directory and doc["kind"] == "provider":
        fails += P.addenda_problems(doc, directory)
    warns = [m for lvl, m in f if lvl == "warn" and "verified_on: not verified" not in m]   # a library claim is verified by check or attest, not by a date
    if doc["kind"] == "provider" and isinstance(doc.get("models"), dict) and "catalog" in doc["models"]:
        try:
            known = P._pick(doc["models"]["catalog"], "catalog", None, None) is not None
        except P.Refused:
            known = True                                           # defined twice or not sealed: the catalog is there, and says what is wrong when it is used
        if not known:
            warns.append("models.catalog: no catalog '%s' yet (a runtime that references it cannot resolve its models until it exists)" % doc["models"]["catalog"])
    return fails, warns


def capability_lines(doc):
    """The capabilities a provider claims, and what each counts as until it is verified."""
    out = []
    caps = doc.get("capabilities") if isinstance(doc.get("capabilities"), dict) else {}
    claimed = [(c, cl) for c, cl in caps.items() if isinstance(cl, dict) and cl.get("value") in ("yes", "partial")]
    if claimed:
        out.append("capabilities claimed (each counts as NO until `qargi provider check` or `attest` records a verification of this exact content):")
        for c, cl in claimed:
            out.append("  %-34s %-8s %s" % (c, cl["value"], cl.get("note", "")))
    else:
        out.append("capabilities claimed: none")
    return out


def summary_lines(doc):
    k = doc.get("kind")
    out = []
    if k == "provider":
        out.append("provider %s on the %s surface%s" % (doc.get("provider"), doc.get("surface"), ", family %s" % doc["family"] if doc.get("family") else ""))
        d = doc.get("dispatch") if isinstance(doc.get("dispatch"), dict) else {}
        out.append("dispatch: %s; barrier: %s; adapter: %s" % (d.get("mode", "none"), (doc.get("barrier") or {}).get("kind", "none") if isinstance(doc.get("barrier"), dict) else "none",
                                                                doc.get("adapter") or "none"))
        out += capability_lines(doc)
    elif k == "catalog":
        out.append("catalog of the family %s, version %s" % (doc.get("family"), doc.get("version")))
    elif k == "extension":
        out.append("extension %s extends %s, provides: %s" % (doc.get("extension"), doc.get("extends"), ", ".join(doc.get("provides") or []) or "nothing"))
    return out


def tree_token(verb, name, kind, directory, execs, extra=""):
    return token_of(verb, name, kind, P.tree_hash(directory), json.dumps(execs, sort_keys=True), extra)


# ---- the sources ------------------------------------------------------------------------------------------------------------------

def git_clone(url, ref, tmp):
    home = os.path.join(tmp, "home")
    os.makedirs(home, exist_ok=True)
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": home, "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
           "GIT_ASKPASS": "false", "GIT_SSH_COMMAND": "false"}
    cmd = ["git", "-c", "protocol.allow=never", "-c", "protocol.https.allow=always", "clone", "-q", '--depth', "1"]
    if ref:
        cmd += ['--branch', ref]
    dst = os.path.join(tmp, "repo")
    r = subprocess.run(cmd + [url, dst], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise Failure("could not clone %s" % url)
    rev = subprocess.run(["git", "-C", dst, "rev-parse", "HEAD"], capture_output=True, text=True, env=env).stdout.strip()
    return dst, rev


def subpath(base, sub):
    if not sub:
        return base
    n = os.path.normpath(sub)
    if os.path.isabs(sub) or n == ".." or n.startswith("../"):
        raise Failure("--path %s is not a path inside the source" % sub)
    p = os.path.join(base, n)
    if not os.path.realpath(p).startswith(os.path.realpath(base) + os.sep):
        raise Failure("--path %s leaves the source" % sub)
    return p


def acquire(source, opts, tmp, into):
    """Stage the pack of SOURCE in the new directory `into` (the files copied, nothing run). Returns (source text for the record, failures
    of the copy). A directory (with definition.json), one JSON file, or an https git URL; a plain https file is not fetched."""
    bad = []
    if source.startswith("https://"):
        repo, rev = git_clone(source, opts.get("--ref"), tempfile.mkdtemp(dir=tmp))
        src = subpath(repo, opts.get("--path"))
        rec = "%s@%s%s" % (source, rev, " path " + opts["--path"] if opts.get("--path") else "")
    elif source.startswith(("http://", "ssh://", "git@", "ftp://", "file://")):
        raise Refusal("%s: only an https git URL, a directory or a JSON file is imported (a plain download is not fetched, and a pack never comes over an unencrypted or ssh transport)" % source)
    else:
        src = subpath(source, opts.get("--path")) if os.path.isdir(source) else source
        rec = source + (" path " + opts["--path"] if opts.get("--path") and os.path.isdir(source) else "")
    if not os.path.exists(src):
        raise Failure("no such source: %s" % source)
    if os.path.isfile(src):
        if opts.get("--path"):
            raise Failure("--path is for a directory source")
        if os.path.getsize(src) > R.MAX_FILE:
            raise Failure("%s is larger than %d bytes" % (source, R.MAX_FILE))
        os.makedirs(into, mode=0o700)
        shutil.copyfile(src, os.path.join(into, "definition.json"))
        os.chmod(os.path.join(into, "definition.json"), 0o600)
    elif os.path.isdir(src):
        bad = R.stage(src, into)
    else:
        raise Failure("%s is neither a directory nor a file" % source)
    return rec, bad


def rename_key(directory, doc, new):
    """The definition of a pack made to carry another name (import --name)."""
    d = dict(doc)
    d[KEYS[doc["kind"]]] = new
    with open(os.path.join(directory, "definition.json"), "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2)
        f.write("\n")
    return d


def prepare(source, opts, tmp, where):
    """Stage a source and judge it: (stage directory, document, name, source text, review, fail list, warn list)."""
    into = os.path.join(where, "pack")
    rec, bad = acquire(source, opts, tmp, into)
    doc = read_definition(into)
    kind = doc.get("kind")
    if kind not in KINDS:
        raise Failure("definition.json: kind must be one of %s, not %r" % (", ".join(KINDS), kind))
    natural = name_of(doc)
    name = opts.get("--name") or natural
    if not valid_name(name):
        raise Failure("cannot work out a valid name (lower case letters, digits and -, starting with a letter, at most 40 characters); pass --name")
    if name != natural:
        doc = rename_key(into, doc, name)
    fails, warns = doc_findings(doc, name, into)
    rv = R.scan(into, doc)
    return into, doc, name, rec, rv, bad + rv["fail"] + fails, warns + rv["warn"]


def taken(name):
    """Why a name cannot be used for a new pack, or None. The shipped names and the library's share one namespace."""
    e = P.entry_any(name)
    if e is None:
        return None
    if e["origin"] == "shipped":
        return "'%s' is a name qargi ships (a %s); import it under another name (--name)" % (name, e["kind"] or "provider")
    return "'%s' is already in the library; remove it first (qargi provider remove %s) or import it under another name (--name)" % (name, name)


# ---- new -------------------------------------------------------------------------------------------------------------------------

def scaffold(kind, name, base):
    today = datetime.now().strftime("%Y-%m-%d")
    tier = {"model": "my-model", "alias": None, "verified_on": None, "source": "edit me: where you learned this model id"}
    if kind == "catalog":
        return {"schema": 2, "kind": "catalog", "family": name, "description": "the models of the %s family: edit me" % name, "version": today,
                "pattern": "^.+$", "tiers": {"*": dict(tier)}, "effort": None}
    if kind == "extension":
        return {"schema": 2, "kind": "extension", "extension": name, "description": "what %s adds to a runtime: edit me" % name, "extends": "runtime-or-family",
                "provides": [], "requires": {}, "adds": {"capabilities": {}}}
    if base == "minimal" or base is None:
        d = {"schema": 2, "kind": "provider", "provider": name, "family": None, "surface": "local", "description": "%s: edit me" % name,
             "models": {"pattern": "^.+$", "tiers": {"*": dict(tier)}, "effort": None}, "capabilities": {}, "resources": {}, "agents": None,
             "dispatch": None, "barrier": {"kind": "none"}}
    elif base == "command":
        d = {"schema": 2, "kind": "provider", "provider": name, "family": None, "surface": "local", "description": "%s: edit me" % name,
             "models": {"pattern": "^.+$", "tiers": {"*": dict(tier)}, "effort": None}, "capabilities": {}, "resources": {}, "agents": None,
             "dispatch": {"mode": "command", "argv": ["my-llm", "run", '--model', "{model}"], "prompt": {"via": "stdin"}, "cwd": "{clone}",
                          "output": {"format": "text"}}, "barrier": {"kind": "none"}}
    elif base == "hook-cli":
        d = {"schema": 2, "kind": "provider", "provider": name, "family": None, "surface": "local", "description": "%s: edit me" % name,
             "models": {"pattern": "^.+$", "tiers": {"*": dict(tier)}, "effort": None}, "capabilities": {}, "resources": {}, "agents": None,
             "dispatch": {"mode": "command", "argv": ["my-llm", "run", '--model', "{model}"], "prompt": {"via": "stdin"}, "cwd": "{clone}",
                          "output": {"format": "text"}},
             "barrier": {"kind": "hook", "hook": {"input": "json-stdin", "tool_pointer": "/tool", "command_pointer": "/args/command", "cwd_pointer": "/cwd",
                                                  "path_pointers": {"write": ["/args/path"], "read": ["/args/path"]},
                                                  "tool_names": {"shell": ["shell"], "write": ["edit", "write"], "read": ["read"]},
                                                  "deny": {"exit": 2, "stream": "stderr"}, "allow": {"exit": 0}}}}
    else:
        try:
            src = P.definition(base)
        except P.ProviderError as e:
            raise Failure("--from %s: %s" % (base, e))
        d = json.loads(json.dumps(src))
        d["provider"], d["family"] = name, None
        d["description"] = "%s, copied from %s: edit me" % (name, base)
        d.pop("adapter", None)
        d.pop("adapter_verbs", None)
        for c in list((d.get("capabilities") or {})):
            d["capabilities"][c] = dict(d["capabilities"][c], verified_on=None)
        if isinstance(d.get("models"), dict) and "catalog" in d["models"]:
            c = P.models_of(base, d["surface"])
            d["models"] = {"pattern": c["pattern"], "tiers": c["tiers"], "effort": c["effort"]}
    return d


README = """# {name}

A {kind} pack for qargi, made by `qargi provider new`. It is unsealed: it cannot be used until you have read it and sealed it.

    qargi provider check {name}      the review, the schema and the hermetic checks; records what is verified (once sealed)
    qargi provider seal {name}       approve it as it is now (a plan first, then --plan TOKEN --approved "...")

Only text files belong here: scripts you can read, never a compiled program, an archive or an encoded blob. A vendor CLI is installed by
you and named in definition.json; the review lists it as "needs on PATH". Every executable is approved by name when the pack is sealed.
"""


def cmd_new(args):
    opts, pos = parse(args, ("--kind", "--from") + GATE)
    if len(pos) != 1:
        raise Usage("usage: qargi provider new NAME [--kind provider|catalog|extension] [--from minimal|command|hook-cli|PROVIDER]")
    name, kind = pos[0], opts.get("--kind", "provider")
    base = opts.get("--from")
    if kind not in KINDS:
        raise Usage("--kind is one of %s" % ", ".join(KINDS))
    if base and kind != "provider":
        raise Usage("--from is for a provider pack")
    if not valid_name(name):
        raise Failure("'%s' is not a pack name (lower case letters, digits and -, starting with a letter, at most 40 characters)" % name)
    why = taken(name)
    if why:
        raise Refusal(why)
    doc = scaffold(kind, name, base)
    fails, _ = doc_findings(doc, name)
    if fails:
        raise Failure("internal: the scaffold does not meet its own schema: %s" % fails[0])
    tok = token_of("new", name, kind, base or "", json.dumps(doc, sort_keys=True))
    print("new %s pack %s%s: create %s/definition.json, README.md and a record that says unsealed" % (kind, name, " from " + base if base else "", pack_dir(name)))
    print("it cannot be used until you edit it, check it and seal it")
    if not gate(opts, tok, [], "create"):
        return 0
    d = pack_dir(name)
    os.makedirs(library(), mode=0o700, exist_ok=True)
    stage = tempfile.mkdtemp(prefix=".stage-", dir=library())
    try:
        os.chmod(stage, 0o700)
        with open(os.path.join(stage, "definition.json"), "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
        with open(os.path.join(stage, "README.md"), "w", encoding="utf-8") as f:
            f.write(README.format(name=name, kind=kind))
        for fn in ("definition.json", "README.md"):
            os.chmod(os.path.join(stage, fn), 0o600)
        write_record(stage, {"kind": kind, "name": name, "source": "created", "sealed": False, "stored": now()})
        audit("provider:new", "%s %s" % (kind, name), opts)
        os.rename(stage, d)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    print("created %s pack %s: %s (unsealed)" % (kind, name, d))
    print("edit it, then: qargi provider check %s; qargi provider seal %s" % (name, name))
    return 0


def write_record(directory, rec):
    f = os.path.join(directory, P.RECORD)
    tmp = f + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(rec, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, f)


def sealed_record(directory, kind, name, source, rv, opts, keep=None):
    rec = dict(keep or {})
    rec.update({"kind": kind, "name": name, "source": source, "sealed": True, "sha256": P.tree_hash(directory), "stored": now(),
                "executables": R.executables(rv),
                "approved": {"words": opts.get("--approved", ""), "by": who(), "at": now(), "exec": exec_names(opts)}})
    return rec


# ---- import ----------------------------------------------------------------------------------------------------------------------

def show_review(rv, doc, title, warns):
    for ln in R.lines(rv, title):
        print(ln)
    for ln in summary_lines(doc):
        print(ln)
    for w in warns:
        if w not in rv["warn"]:
            print("warn: %s" % w)


def cmd_import(args):
    opts, pos = parse(args, ("--name", "--ref", "--path") + GATE)
    if len(pos) != 1:
        raise Usage("usage: qargi provider import SOURCE [--name N] [--ref REF] [--path SUB] [--plan TOKEN --approved \"...\" [--approve-exec a,b]]")
    source = pos[0]
    tmp = tempfile.mkdtemp(prefix="qargi-import.")
    try:
        os.chmod(tmp, 0o700)
        into, doc, name, rec, rv, fails, warns = prepare(source, opts, tmp, tmp)
        why = taken(name)
        if why:
            raise Refusal(why)
        show_review(rv, doc, "%s pack %s from %s" % (doc["kind"], name, rec), warns)
        if fails:
            for m in fails:
                if m not in rv["fail"]:
                    print("FAIL: %s" % m)
            print("refused: fix the source first", file=sys.stderr)
            return 1
        execs = R.executables(rv)
        tok = tree_token("import", name, doc["kind"], into, execs)
        if not gate(opts, tok, execs, "store it"):
            return 0
        os.makedirs(library(), mode=0o700, exist_ok=True)
        stage = tempfile.mkdtemp(prefix=".stage-", dir=library())
        try:
            os.chmod(stage, 0o700)
            into2, doc2, name2, rec2, rv2, fails2, _ = prepare(source, opts, tmp, stage)
            tok2 = tree_token("import", name2, doc2["kind"], into2, R.executables(rv2))
            if fails2 or tok2 != tok:
                raise Failure("the source changed since the plan was made; nothing was stored. Run the plan again")
            target = pack_dir(name)
            if os.path.lexists(target) or taken(name):
                raise Refusal("'%s' appeared in the library while you were reading; nothing was stored" % name)
            write_record(into2, sealed_record(into2, doc2["kind"], name, rec2, rv2, opts))
            audit("provider:import", "%s %s from %s %s" % (doc2["kind"], name, rec2, tok), opts)
            os.rename(into2, target)
        finally:
            shutil.rmtree(stage, ignore_errors=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("stored %s pack %s (content %s)%s" % (doc["kind"], name, P.tree_hash(pack_dir(name))[:16],
                                                "; %d executable%s approved" % (len(execs), "" if len(execs) == 1 else "s") if execs else ""))
    print("it is not enabled or linked by this; qargi provider check %s records what it can verify" % name)
    return 0


# ---- seal ------------------------------------------------------------------------------------------------------------------------

def library_entry(name):
    e = P.entry_any(name)
    if e is None:
        raise Failure("no pack '%s' in the library (qargi provider list)" % name)
    if e["origin"] != "library":
        raise Refusal("'%s' is shipped with qargi; it is not a library pack" % name)
    if os.path.islink(os.path.dirname(e["file"])):
        raise Refusal("the library entry '%s' is a symbolic link; refusing to change what it points at" % name)
    return e


def cmd_seal(args):
    opts, pos = parse(args, GATE)
    if len(pos) != 1:
        raise Usage("usage: qargi provider seal NAME [--plan TOKEN --approved \"...\" [--approve-exec a,b]]")
    name = pos[0]
    e = library_entry(name)
    d = os.path.dirname(e["file"])
    doc = read_definition(d)
    rv = R.scan(d, doc)
    fails, warns = doc_findings(doc, name, d)
    fails = rv["fail"] + fails
    old = P.pack_record(d) or {}
    show_review(rv, doc, "%s pack %s" % (doc.get("kind"), name), warns)
    state, why = P.seal_state(e)
    print("state: %s%s" % (state, ": " + why if why else ""))
    if fails:
        for m in fails:
            if m not in rv["fail"]:
                print("FAIL: %s" % m)
        print("refused: fix it first", file=sys.stderr)
        return 1
    execs = R.executables(rv)
    tok = tree_token("seal", name, doc["kind"], d, execs)
    if not gate(opts, tok, execs, "approve this content"):
        return 0
    audit("provider:seal", "%s %s %s" % (doc["kind"], name, tok), opts)
    write_record(d, sealed_record(d, doc["kind"], name, old.get("source", "created"), rv, opts, keep={k: v for k, v in old.items() if k in ("note",)}))
    print("sealed %s pack %s (content %s)" % (doc["kind"], name, P.tree_hash(d)[:16]))
    if os.path.exists(os.path.join(P._state_dir(), "providers", name, "verified.json")):
        print("its verification records no longer match this content: run qargi provider check %s" % name)
    return 0


# ---- references, remove ---------------------------------------------------------------------------------------------------------

def projects():
    d = os.path.join(P._conf(), "projects")
    try:
        names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and P.NAME_RE.match(f[:-5]))
    except OSError:
        return []
    return names


def project_models(project):
    a = P.project_answers(project) or {}
    m = a.get("models")
    return m if isinstance(m, dict) else {}


def references(name, kind):
    """Why a pack cannot go: what refers to it (project answers, extensions, runtimes)."""
    out = []
    for p in projects():
        m = project_models(p)
        prov = m.get("provider")
        names = [prov] if isinstance(prov, str) else [v for v in prov.values() if isinstance(v, str)] if isinstance(prov, dict) else []
        if kind == "provider" and name in [n.strip() for n in names]:
            out.append("project %s runs it (models.provider)" % p)
        if kind == "extension" and isinstance(m.get("extensions"), list) and name in m["extensions"]:
            out.append("project %s has it enabled (models.extensions)" % p)
    for n, es in sorted(P._scan(None, None).items()):
        for ent in es:
            if n == name and ent["origin"] == "library":
                continue
            try:
                raw = P._read(ent)
            except P.ProviderError:
                continue
            if kind == "provider" and raw.get("kind") == "extension" and raw.get("extends") == name:
                out.append("extension %s extends it" % n)
            if kind == "catalog" and raw.get("kind") == "provider" and isinstance(raw.get("models"), dict) and raw["models"].get("catalog") == name:
                out.append("runtime %s takes its models from it" % n)
    return out


def cmd_remove(args):
    opts, pos = parse(args, GATE)
    if len(pos) != 1:
        raise Usage("usage: qargi provider remove NAME [--plan TOKEN --approved \"...\"]")
    name = pos[0]
    e = library_entry(name)
    d = os.path.dirname(e["file"])
    kind = e["kind"] or "provider"
    refs = references(name, kind)
    if refs:
        raise Failure("%s '%s' is in use: %s; nothing was removed" % (kind, name, "; ".join(refs)))
    vdir = os.path.join(P._state_dir(), "providers", name)
    print("remove %s pack %s: %s (%d files) and its verification records %s" % (kind, name, d, sum(len(fs) for _, _, fs in os.walk(d)), vdir))
    tok = token_of("remove", name, kind, P.tree_hash(d))
    if not gate(opts, tok, [], "remove it"):
        return 0
    audit("provider:remove", "%s %s %s" % (kind, name, tok), opts)
    shutil.rmtree(d)
    shutil.rmtree(vdir, ignore_errors=True)
    print("removed %s pack %s" % (kind, name))
    return 0


# ---- enable, disable -------------------------------------------------------------------------------------------------------------

def project_names(project):
    """The runtime names and families the project runs (local and cloud), for deciding what an extension may extend."""
    out = set()
    answers = P.project_answers(project) or {}
    for s in P.SURFACES:
        try:
            r = P.resolve_project(answers, s, project)[0]
        except P.ProviderError:
            continue
        out.add(r)
        try:
            fam = P.definition(r, s).get("family")
        except P.ProviderError:
            fam = None
        if fam:
            out.add(fam)
    return out


def project_runtimes(project):
    """{surface: runtime} the project runs (a surface it names no provider for is left out)."""
    out = {}
    answers = P.project_answers(project) or {}
    for sf in P.SURFACES:
        try:
            out[sf] = P.resolve_project(answers, sf, project)[0]
        except P.ProviderError:
            continue
    return out


def set_answer(project, path, value):
    # project set and project init refuse models.extensions and models.accept_no_barrier for every caller: the gated verbs (enable, disable)
    # store them after their own gate, through lib/gated_answers.py, which is no verb and has no switch a caller can set
    try:
        GA.store(project, path, value)
    except GA.Refused as err:
        raise Failure("could not record it in the answers of %s; nothing changed: %s" % (project, err))


def cmd_enable(verb, args):
    opts, pos = parse(args, GATE)
    if len(pos) != 2:
        raise Usage("usage: qargi provider %s PROJECT EXTENSION [--plan TOKEN --approved \"...\" [--approve-exec a,b]]" % verb)
    project, ext = pos
    if not P.NAME_RE.match(project) or P.project_answers(project) is None:
        raise Failure("no stored answers for project '%s' (qargi project list)" % project)
    cur = project_models(project).get("extensions")
    cur = [x for x in cur if isinstance(x, str)] if isinstance(cur, list) else []
    e = P.entry_any(ext)
    if e is None or (e["kind"] or "provider") != "extension":
        if verb == "disable" and ext in cur:
            e = None
        else:
            raise Failure("no extension '%s' (qargi provider list)" % ext)
    execs, tokparts = {}, ""
    if verb == "enable":
        if e["origin"] != "library":
            raise Refusal("'%s' is shipped; an extension is a library pack" % ext)
        state, why = P.seal_state(e)
        if state != "sealed":
            raise Refusal("extension '%s' %s; seal it first (qargi provider seal %s): enabling approves code only after it was reviewed" % (ext, why or state, ext))
        d = os.path.dirname(e["file"])
        doc = read_definition(d)
        fails, _ = doc_findings(doc, ext)
        rv = R.scan(d, doc)
        if fails or rv["fail"]:
            raise Failure("extension '%s' fails its review: %s" % (ext, (rv["fail"] + fails)[0]))
        names = project_names(project)
        if doc.get("extends") not in names:
            raise Refusal("extension '%s' extends %s; project %s runs %s" % (ext, doc.get("extends"), project, ", ".join(sorted(names)) or "no provider"))
        new = sorted(set(cur) | {ext})
        applied, applied_why = [], []
        for sf, rt in sorted(project_runtimes(project).items()):
            try:
                comp = P.compose(rt, sf, extensions=new)
            except P.Conflict as err:
                raise Refusal("%s; nothing was enabled" % err)
            except P.ProviderError as err:
                raise Failure("cannot compose %s on %s with %s: %s" % (rt, sf, ", ".join(new), err))
            applied += [(sf, rt)] * (ext in comp["extensions"])
            applied_why += [i["why"] for i in comp["ignored"] if i["extension"] == ext]
        if not applied:
            raise Refusal("extension '%s' applies to nothing in project %s: %s" % (ext, project, "; ".join(sorted(set(applied_why))) or "it is for no runtime of the project"))
        execs = R.executables(rv)
        tokparts = P.tree_hash(d)
        for ln in R.lines(rv, "extension %s for project %s" % (ext, project)):
            print(ln)
        for ln in summary_lines(doc):
            print(ln)
        if ext in cur:
            print("nothing to do: %s is enabled for %s already" % (ext, project))
            return 0
        print("applies to: %s" % ", ".join("%s on %s" % (rt, sf) for sf, rt in applied))
        print("effect: models.extensions of project %s becomes %s; what it provides counts only after it is checked (qargi provider check %s --project %s)" % (project, json.dumps(new), ext, project))
    else:
        if ext not in cur:
            print("nothing to do: %s is not enabled for %s" % (ext, project))
            return 0
        new = [x for x in cur if x != ext]
        print("effect: models.extensions of project %s becomes %s" % (project, json.dumps(new)))
    tok = token_of(verb, project, ext, tokparts, json.dumps(execs, sort_keys=True), json.dumps(cur))
    if not gate(opts, tok, execs, verb):
        return 0
    audit("provider:%s" % verb, "%s %s %s" % (project, ext, tok), opts)
    set_answer(project, "models.extensions", new)
    print("%sd extension %s for project %s" % (verb, ext, project))
    return 0


# ---- check -----------------------------------------------------------------------------------------------------------------------

def check_target(target):
    """(directory, name or None, entry or None) of what `check` was asked about: a path to a pack directory, or a pack name."""
    if "/" in target or (os.path.isdir(target) and P.entry_any(target) is None):
        if not os.path.isdir(target):
            raise Failure("no such directory: %s" % target)
        d = os.path.realpath(target)
        return d, None, None
    e = P.entry_any(target)
    if e is None:
        return None, target, None                                  # no such pack: provider.py's own report says so
    return os.path.dirname(e["file"]) if e["origin"] == "library" else None, target, e


def cmd_check(args):
    from conformance import cases
    opts, pos = parse(args, ("--project",))
    if len(pos) != 1:
        raise Usage("usage: qargi provider check NAME|DIR [--project P]")
    d, name, e = check_target(pos[0])
    if e is None and d is None or e is not None and e["origin"] == "shipped":
        return None                                                # a shipped definition, or none: the report provider.py has always made
    doc = read_definition(d)
    label = name or os.path.basename(d)
    kind = doc.get("kind")
    state = P.seal_state(e)[0] if e is not None else "directory"
    if state == "unrecorded":                                      # nobody read it or approved it: nothing of it is judged, recorded or run
        raise Refusal("pack '%s' has no record (put there by hand) and was never reviewed, so it is not checked; read it and seal it (qargi provider seal %s), "
                      "or qargi provider import it from its source" % (name, name))
    rv = R.scan(d, doc)
    fails, warns = doc_findings(doc, name if name else name_of(doc), d)
    fails = rv["fail"] + fails
    warns = rv["warn"] + warns
    print("%s: %s pack, %s; %s, %s" % (label, kind, {"sealed": "sealed", "unsealed": "UNSEALED", "drift": "CHANGED since it was sealed", "unrecorded": "no record (put there by hand)",
                                                      "directory": "a directory outside the library"}[state],
                                       P._count(len(fails), "failure"), P._count(len(warns), "warning")))
    for m in fails:
        print("fail: %s" % m)
    for m in warns:
        print("warn: %s" % m)
    print("review: %d files, %d executable%s, %d flagged construct%s, %d network mention%s, secret findings %s" % (
        rv["count"], len(rv["executables"]), "" if len(rv["executables"]) == 1 else "s", len(rv["flags"]), "" if len(rv["flags"]) == 1 else "s",
        len(rv["network"]), "" if len(rv["network"]) == 1 else "s", "found" if rv["secrets"] else "none"))
    if rv["executables"]:
        print("executables: %s" % ", ".join(sorted(R.executables(rv))))
    if fails:
        print("nothing is verified while the pack fails")
        if name and state == "sealed":
            P.record_verification(name, {})
        return 1
    if kind == "extension":
        return check_extension(doc, d, name, e, state, opts)
    if kind != "provider":
        print("a %s has no capabilities to verify" % kind)
        return 0
    results = cases.run(doc, d, name, e, sealed=(state == "sealed"), opts=opts, rv=rv)
    return record_results(doc, results, name, state, lambda: P.definition_hash(name))


def check_extension(doc, d, name, e, state, opts):
    """check of an extension pack in the library: compose it alone onto its runtime (the project's, or the one it names), run the cases of
    the capabilities it provides, and record those that passed bound to the extension and that runtime (provider.extension_hash)."""
    from conformance import cases
    if name is None or e is None:
        print("an extension is checked composed onto its runtime, from the library: qargi provider import it first; nothing is recorded")
        return 0
    try:
        base, surface = P.extension_base(name, opts.get("--project"))
        comp = P.compose(base, surface, extensions=[name])
    except P.Conflict as err:
        print("fail: %s" % err)
        print("nothing is verified while the pack fails")
        if state == "sealed":
            P.record_verification(name, {})
        return 1
    except P.ProviderError as err:                                 # no runtime to compose it onto (a fresh scaffold, say): the pack is fine, nothing is verified
        print("warn: %s" % err)
        print("nothing is verified: there is no runtime to compose it onto")
        return 0
    if name not in comp["extensions"]:
        print("warn: %s is not applied to %s on %s: %s" % (name, base, surface, "; ".join(i["why"] for i in comp["ignored"])))
        print("nothing is verified: it does not apply there")
        return 0
    print("composed onto %s on %s%s" % (base, surface, " (project %s)" % opts["--project"] if opts.get("--project") else ""))
    why = P.barrier_claim_problem(comp["definition"], by="%s (composed onto %s)" % (name, base)) if comp["provenance"].get("capabilities.read_only_barrier") == name else None
    if why:                                                        # the claim is the extension's and the composition has nothing behind it
        print("fail: %s" % why)
        print("nothing is verified while the pack fails")
        if state == "sealed":
            P.record_verification(name, {})
        return 1
    results = cases.run_extension(comp, name, d, opts)
    mine = {c[13:]: comp["definition"]["capabilities"][c[13:]] for c, pack in comp["provenance"].items() if pack == name and c.startswith("capabilities.")}
    return record_results({"capabilities": mine}, results, name, state, lambda: P.extension_hash(name, base, surface))


def record_results(doc, results, name, state, hash_now):
    """Print the cases and the verdict per claimed capability; for a sealed library pack record the verified ones (keeping the attested
    records of the same content) under the hash hash_now() gives. Exit status: 1 when a case failed."""
    from conformance import cases
    bad = 0
    for cid in sorted(results):
        r = results[cid]
        print("%-4s %s%s" % ({"pass": "ok", "fail": "FAIL", "skip": "skip", "na": "-"}[r["status"]], cid, ": " + "; ".join(r["notes"]) if r["notes"] else ""))
        bad += r["status"] == "fail"
    verdicts = cases.verdicts(doc, results)
    records = {}
    for cap in sorted(verdicts):
        ok, why = verdicts[cap]
        print("%-34s %s" % (cap, "verified (%s)" % why if ok else "not verified: %s" % why))
        if ok:
            records[cap] = why
    if name is None:
        print("a directory is not recorded: put the pack in the library (qargi provider import) to have a verification recorded")
        return 1 if bad else 0
    if state != "sealed":
        print("nothing recorded: %s; seal it (qargi provider seal %s) and check again" % ("the pack is " + state, name))
        return 1 if bad else 0
    h = hash_now()
    keep = {c: r for c, r in P.verification(name).items() if isinstance(r, dict) and r.get("by") == "attest" and r.get("hash") == h}
    recs = dict(keep)
    for cap, why in records.items():
        recs[cap] = {"hash": h, "by": "conformance", "at": now(), "note": why}
    P.record_verification(name, recs)
    print("recorded %d verification%s in %s" % (len(records), "" if len(records) == 1 else "s", os.path.join(P._state_dir(), "providers", name, "verified.json")))
    return 1 if bad else 0


# ---- attest ----------------------------------------------------------------------------------------------------------------------

ASK = """attest is asked EACH TIME: a live check is never pre-approved for a runtime, and this verb never runs or spends anything. It records a
check YOU ran, with the owner's words, for this exact content. Before any run, tell the owner:
  1. the runtime and the capability
  2. the exact command or API calls, and the scratch resources they use
  3. the smallest model and effort that can show it
  4. the hard ceiling (cents or tokens), enforced by the run where it can be
  5. the expected cost, and how the scratch resources are cleaned up afterwards
Only on the owner's go-ahead run it, then record it:
  qargi provider attest NAME CAP --asked "<the owner's words>" --did "<what you ran>" --result pass|fail --cost-cents N --cleanup "<state>" [--note TEXT]
  (then the plan token it prints: apply with --plan TOKEN --approved "<the owner's go-ahead to record it>")
A free local check that makes no API call (an OS sandbox test, say) needs no spend ask, but is recorded the same way, with --cost-cents 0."""


def cmd_attest(args):
    opts, pos = parse(args, ("--did", "--result", "--cost-cents", "--cleanup", "--note", "--project") + GATE)
    if len(pos) != 2:
        raise Usage("usage: qargi provider attest NAME CAP [--project P] --asked WORDS --did TEXT --result pass|fail --cost-cents N --cleanup TEXT [--plan TOKEN --approved WORDS]\n" + ASK)
    name, cap = pos
    e = library_entry(name)
    if (e["kind"] or "provider") not in ("provider", "extension"):
        raise Failure("'%s' is a %s; only a provider or an extension has capabilities" % (name, e["kind"]))
    if cap not in P.capabilities2():
        raise Failure("unknown capability '%s'; one of %s" % (cap, ", ".join(P.capabilities2())))
    state = P.seal_state(e)[0]
    if state != "sealed":
        raise Refusal("pack '%s' %s; seal it first (qargi provider seal %s), so that the attestation is bound to the content that was reviewed" % (name, P.seal_state(e)[1] or state, name))
    ext = e["kind"] == "extension"
    if ext:
        try:
            base, surface = P.extension_base(name, opts.get("--project"))
        except P.Refused as err:
            raise Failure(str(err))
        doc = {"capabilities": ((P._read(e).get("adds") or {}).get("capabilities") or {})}
    else:
        doc = P.definition(name)
    cell = (doc.get("capabilities") or {}).get(cap)
    if not isinstance(cell, dict) or cell.get("value") not in ("yes", "partial"):
        raise Failure("%s does not claim %s (its definition says %s); there is nothing to attest" % (name, cap, cell.get("value") if isinstance(cell, dict) else "nothing"))
    given = [k for k in ("--asked", "--did", "--result", "--cost-cents", "--cleanup") if k in opts]
    if len(given) < 5:
        print(ASK)
        if given:
            print("\nmissing: %s" % ", ".join(k for k in ("--asked", "--did", "--result", "--cost-cents", "--cleanup") if k not in opts), file=sys.stderr)
            return 2
        print("\nnothing is recorded and nothing was run")
        return 0
    if not opts["--asked"].strip() or not opts["--did"].strip() or not opts["--cleanup"].strip():
        raise Usage("--asked, --did and --cleanup need words")
    if opts["--result"] not in RESULTS:
        raise Usage("--result is pass or fail")
    if not re.fullmatch(r"[0-9]{1,9}", opts["--cost-cents"]):
        raise Usage("--cost-cents is the whole number of cents the run cost (0 for a free local check)")
    h = P.extension_hash(name, base, surface) if ext else P.definition_hash(name)
    print("attest %s %s on %s%s (content %s)" % (cap, "claimed " + cell["value"], name, " composed onto %s on %s" % (base, surface) if ext else "", h[:16]))
    print("  asked:   %s" % opts["--asked"])
    print("  ran:     %s" % opts["--did"])
    print("  result:  %s; cost %s cents; cleanup: %s" % (opts["--result"], opts["--cost-cents"], opts["--cleanup"]))
    if opts["--result"] != "pass":
        print("a check that failed proves nothing: nothing is recorded (an earlier record for %s on this content is removed if you apply)" % cap)
    else:
        print("effect: %s counts as %s for %s while its content stays as it is now; any edit makes it stale" % (cap, cell["value"], name))
    tok = token_of("attest", name, cap, h, opts["--asked"], opts["--did"], opts["--result"], opts["--cost-cents"], opts["--cleanup"], opts.get("--note", ""))
    if not gate(opts, tok, [], "record it"):
        return 0
    recs = P.verification(name)
    recs = {c: r for c, r in recs.items() if isinstance(r, dict)}
    if opts["--result"] == "pass":
        recs[cap] = {"hash": h, "by": "attest", "at": now(), "note": opts.get("--note", ""), "asked": opts["--asked"], "did": opts["--did"],
                     "cost_cents": int(opts["--cost-cents"]), "cleanup": opts["--cleanup"], "approved": opts["--approved"]}
    else:
        recs.pop(cap, None)
    audit("provider:attest", "%s %s %s %s" % (name, cap, opts["--result"], tok), opts)
    P.record_verification(name, recs)
    print("recorded: %s" % ("%s attested for %s" % (cap, name) if opts["--result"] == "pass" else "nothing (the check failed)"))
    return 0


# ---- list, show for the packs that are not providers ---------------------------------------------------------------------------

def list_other_kinds():
    """Lines for the library's catalogs and extensions (providers are listed by provider.py)."""
    for n, es in sorted(P._scan(None, None).items()):
        for e in es:
            if e["origin"] != "library":
                continue
            kind = P._kind(e)
            if kind == "provider":
                continue
            state, _ = P.seal_state(e)
            print("%-12s %-12s %s  (library%s)" % (n, kind, "-", "" if state == "sealed" else ", " + {"unsealed": "unsealed", "unrecorded": "not sealed: no record"}.get(state, "changed since sealed")))


def show_pack(name, as_json, project=None):
    e = P.entry_any(name)
    if e is None or e["origin"] != "library" or P._kind(e) == "provider":
        return None
    d = os.path.dirname(e["file"])
    doc = read_definition(d)
    if as_json:
        print(json.dumps(doc, indent=2))
        return 0
    state, why = P.seal_state(e)
    print("%s  (%s, library, %s)" % (name, e["kind"], state + (": " + why if why else "")))
    for ln in summary_lines(doc):
        print(ln)
    if e["kind"] == "extension" and state == "sealed" and not [1 for lvl, _ in P.validate_extension(doc, name) if lvl == "fail"]:
        try:
            base, surface = P.extension_base(name, project)
        except P.ProviderError as err:
            print("composed onto: nothing (%s)" % err)
            return 0
        print("composed onto %s on %s%s" % (base, surface, " (project %s)" % project if project else ""))
        for c, cl in sorted(((doc.get("adds") or {}).get("capabilities") or {}).items()):
            print("  %-34s %-8s %s" % (c, cl["value"], "-" if cl["value"] == "no" else P.extension_backing(name, c, cl, base, surface)))
    return 0


def run(verb, rest):
    """The exit status of a library verb; the caller prints Usage/Failure."""
    try:
        if verb == "new":
            return cmd_new(rest)
        if verb == "import":
            return cmd_import(rest)
        if verb == "seal":
            return cmd_seal(rest)
        if verb == "remove":
            return cmd_remove(rest)
        if verb in ("enable", "disable"):
            return cmd_enable(verb, rest)
        if verb == "attest":
            return cmd_attest(rest)
        if verb == "check":
            return cmd_check(rest)
    except Usage as e:
        print(str(e), file=sys.stderr)
        return 2
    except Refusal as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2
    except Failure as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    raise ValueError(verb)


def quiet(fn, *a, **k):
    """fn(*a, **k) with standard output and error captured: (result or the SystemExit code, output)."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            return fn(*a, **k), out.getvalue()
        except SystemExit as e:
            return e.code, out.getvalue()
