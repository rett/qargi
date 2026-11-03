#!/usr/bin/env python3
"""qargi provider: the model-provider definitions. Shipped ones are lib/providers/NAME.json (a runtime: one definition on one surface, in
the schema lib/providers/schema-2.json) and lib/providers/catalogs/FAMILY.json (the models of a family); the user's are in the pack
library, QARGI_CONF/packs/providers/NAME/definition.json. A name defined in both places is refused.

As a library (import provider; stdlib only, found beside the descriptors, so it works from a checkout and from /opt/qargi):
  definition(name, surface=None)       the definition of a runtime on its surface (a copy); ProviderError when there is none
  surfaces_of(name) / origin(name)     the surfaces it serves / "shipped" or "library"
  catalog(family) / models_of(name, surface=None) / model_for(models, tier)
                                       a family's catalog; the resolved models of a runtime (catalog followed, '*' expanded); the
                                       model name passed for a tier (alias or id)
  validate2(document, name=None)       [("fail"|"warn", message), ...]; name is the file name the provider must carry. A key or a string with a
                                       control, escape or bidi character (also one written as a JSON escape, \\u001b) is the only failure reported
  vis(text)                            text with control, escape and bidi characters written out; print() of this module (and of local_run.py)
                                       writes every string through it, so nothing a definition holds reaches the terminal raw
  cap(name, surface, capability)       "yes", "partial", "no" or "unverified" (the file says yes or partial, but with no
                                       verified_on date)
  effective(name, surface, capability, project=None)
                                       what enforcement may rely on: "yes", "partial" or "no". Unverified counts as no, and so
                                       does a surface the provider does not list. With a project, the runtime composed with the
                                       extensions the project enabled (compose); cap() is the same with "unverified" kept.
  compose(name, surface, project=None) the effective definition: the runtime plus the project's enabled extensions (models.extensions),
                                       merged in name order, with {key: pack} provenance for every capability, resource, renderer,
                                       dispatch variant, barrier and adapter verb. Two packs adding the same key, or an extension adding
                                       what the runtime has, is Conflict (nothing is overridden). Extensions are per surface: one that is for
                                       another runtime or surface, or whose requires do not hold, is ignored with its reason.
  extension_hash(ext, base, surface)   what a capability an extension provides is verified against: the extension chained to its runtime.
                                       A capability an extension provides counts only after `provider check` (or attest) of THAT extension
                                       on that runtime; a change to the extension or a reseal of the runtime makes the record stale.
  extension_base(ext, project=None)    (runtime, surface) an extension is composed onto, for check and attest
  accepted(project, surface)           the project's recorded acceptance of a surface with no read-only barrier, or None
  require_barrier(provider, surface, project)
                                       ("yes"|"partial"|"accepted"|"refused", text): may a read-only role run on this surface?
  composed(name, surface, project=None) definition() for a project: with a project, compose()'s definition (the one to read resources,
                                       renderers, barrier and capabilities from when a project is known)
  layout(name, home=None, project=None) the layout of a runtime: every field of LAYOUT_FIELDS, null when the runtime has none; read
                                       from the resources of its definition; a leading ~ is expanded with home (default $HOME)
                                       when it is read, never in the file; with a project (here and in the four below) from the composed
                                       definition, so what an enabled extension adds is there
  require(name, field, would, project=None)
                                       the layout field, or Unsupported (a ProviderError): "provider NAME has no FACILITY: WOULD"
  require_skills(name, would, project=None)
                                       the same refusal when the skills capability is not yes or partial (verified) on local
  memory_dir(name, checkout) / checkout_key(rule, path) / launch_line(name, render)
                                       the layout's templates filled in
  adapter_exec(name, surface, verb) / run_adapter(name, surface, verb, data)
                                       the adapter of a runtime (a library pack's only as a sealed private copy; the verb must be one
                                       it lists); the second runs it and removes the copy
  notes_of(project)                    (runtime, {topic: text}): the notes of the definition of the project's local runtime, composed (notes: an
                                       optional object of topic name to one line of text, at most 16 topics of 2000 characters)
  contract_addenda(name, surface)      the texts the runtime's definition adds to the member contract (resources.contract_addenda: files in its
                                       own directory, plain text); ProviderError for one that is missing, is not text or leaves the directory
  discard_exec_copy(directory)         remove what exec_copy made (its parent directory, qargi-exec.XXXX)
  project_provider(answers, project)   models.provider of the project's answers; there is no default: NoProvider (exit 2)
  provider_of(answers, surface)        the runtime for one surface: models.provider is a name (runtime or family) or {local, cloud};
                                       a surface left unset is NoProvider (exit 2). resolve_runtime(name, surface) is the rule: a
                                       runtime of that name, else a family with exactly one runtime on the surface, else Refused
  tree_hash(dir) / pack_record(dir) / seal_state(entry)
                                       a library pack's content hash (every file but .pack.json), its record, and whether it is sealed,
                                       unsealed (made by `provider new`, not yet sealed), changed since sealed (drift) or has no record
                                       (a file put there by hand, never read or approved). Only a sealed pack is used; any other is Drift (exit 2).
  definitions_unsealed(name)           {surface: definition} without the seal check, for a reader that only needs to see what a definition names
  exec_copy(name, rel)                 a private copy of a sealed library pack with the executable rel, after its hash and the pack's were
                                       checked against the record and again on the copy; the only way qargi runs a library pack's code
  verify_record / record_verification  the verified.json of a library definition: hash-bound to the definition (and the pack it is in)
Every function that reads a definition takes root= (the shipped directory) and library= (the pack library) for tests; the defaults are
beside this file and below the configuration directory. A test that names a root sees a library only when it names one too.

Usage: provider.py list
       provider.py show NAME [--project P] [--json]
                                         with a project: the runtime composed with the project's enabled extensions, with the pack that
                                         provided each capability
       provider.py check NAME            exit 1 on a failure, 0 otherwise (warnings do not fail); the adapter, when the
                                         descriptor names one, must exist and be executable
       provider.py accept NAME --surface S --no-barrier [--project P] --asked W [--approved W] [--plan T]
                                         lib/provider.sh does it: plan first, then the token and the approval
       provider.py require-barrier PROVIDER SURFACE [--project P]
                                         exit 0 when a read-only role may run there (a partial barrier prints its note to
                                         stderr), 2 with the qargi provider accept command when it may not
       provider.py effective PROVIDER SURFACE CAPABILITY [--project P]
                                         prints yes, partial or no (what enforcement may rely on; with a project, as composed with its
                                         enabled extensions); exit 1 when the provider does not list the surface, 2 on a conflict
       provider.py layout NAME [FIELD] [--would TEXT] [--home DIR] [--project P]
                                         the layout as JSON, or one field (a string as it is, an object as JSON); a null
                                         field exits 3 with "provider NAME has no FACILITY: TEXT"
       provider.py require-skills NAME [--would TEXT] [--project P]
                                         exit 3 with that refusal unless the provider supports skills on the local surface (with a project:
                                         as composed with its enabled extensions; so for layout and launch)
       provider.py adapter-run NAME SURFACE VERB [--check]
                                         the request on stdin to the adapter's VERB, its answer on stdout, its exit status; --check runs
                                         nothing and exits 3 with the reason unless it could run
       provider.py model NAME SURFACE TIER
                                         the model id of a tier of the runtime on a surface
       provider.py launch NAME RENDER [--project P]   the command that starts a session on the render directory RENDER (exit 3: none)
       provider.py notes [TOPIC] [--project P]
                                         the text of a notes topic of the definition of the project's local runtime (composed with its enabled
                                         extensions; the project is P, else the one in effect), or the topic names when none is given; exit 1
                                         when the runtime has no such topic, 2 when the project has no local runtime
       provider.py skills-dirs [NAME]   the project skills directory of NAME, or of every provider that has one and supports skills (one per line)
       provider.py of PROJECT [--conf DIR] [--surface local|cloud]
                                         prints the project's provider (models.provider); with a surface, the runtime for it (a family
                                         name is resolved, with a notice on stderr); exit 2 when it names none or there is no such project
The library verbs (lib/conformance/library.py; every one that writes is a plan, a token and --approved, and leaves an audit line; a member
is refused all of them by the guard):
       provider.py new NAME [--kind provider|catalog|extension] [--from minimal|command|hook-cli|PROVIDER]    scaffold an unsealed pack
       provider.py import SOURCE [--name N] [--ref R] [--path SUB] [--plan T --approved W [--approve-exec a,b]]   a directory, one JSON file or an https git URL
       provider.py seal NAME [--plan T --approved W [--approve-exec a,b]]       approve the pack as it is now (after you edited it)
       provider.py check NAME|DIR [--project P]    the review, the schema, the hermetic cases; records verified.json for a sealed library pack
       provider.py attest NAME CAP --asked W ...   the plan and the record of a live check you ran; it never runs or spends anything
       provider.py enable|disable PROJECT EXT [--plan T --approved W [--approve-exec a,b]]   an extension for one project
       provider.py remove NAME [--plan T --approved W]
Exit status 3 is the degrade refusal: the provider does not support what the verb needs; 2 is a project with no provider."""
import copy
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import datetime

HERE = os.path.dirname(os.path.realpath(__file__))


def _review():
    """lib/conformance/review.py (the text-only and escape rules, one place for them), or None when this file is run without its neighbours."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        from conformance import review
    except ImportError:
        return None
    return review


def vis(text):
    """text with every control, escape, bidi or surrogate character written out (\\x1b, \\u202e), tab and newline kept. Without
    conformance/ beside this file every character that is not printable is written out, which is the same and a little more."""
    r = _review()
    if r:
        return r.vis(text)
    return "".join(c if c.isprintable() or c in "\t\n" else "\\x%02x" % ord(c) if ord(c) < 256 else "\\u%04x" % ord(c) for c in str(text))


_print = print


def print(*args, **kw):  # noqa: A001  (this module's print: what a definition holds is written through vis)
    """The print of this module. A definition (a name, a note, a command, a path) is read from files a person may not have written, so its
    control, escape or bidi characters are written out and cannot move the cursor, erase or hide a line, or reorder text."""
    _print(*[vis(a) if isinstance(a, str) else a for a in args], **kw)


TOOL = os.path.dirname(HERE)                      # the tool root: the checkout, or the installed copy
PROVIDERS = os.path.join(HERE, "providers")
NAME_RE = re.compile(r"^[a-z][a-z0-9-]*$")
SURFACES = ("local", "cloud")
LIBRARY_VERBS = ("new", "import", "seal", "remove", "enable", "disable", "attest")
TIERS = ("fast", "balanced", "deep", "frontier")


class ProviderError(Exception):
    pass


class NoProvider(ProviderError):
    """The project's answers name no provider (models.provider): exit status 2. There is no default provider."""


class Unsupported(ProviderError):
    """The provider has no such facility (a null layout field, or a capability that is not verified): exit status 3."""


class Refused(ProviderError):
    """A definition that cannot be used as it stands: exit status 2, like a project with no provider."""


class Clash(Refused):
    """The same name is defined twice, as a shipped file and in the pack library."""


class Conflict(Refused):
    """Two packs add the same thing to one runtime (or an extension adds what the runtime has): the composition is refused, never resolved."""


class Drift(Refused):
    """A library pack that is not sealed, or whose files changed since it was sealed: it is not used until it is sealed again."""


class Ambiguous(Refused):
    """A family name that matches more than one runtime on a surface."""


class NotServed(Refused):
    """A runtime of that name exists but does not serve the surface (provider_of turns it into NoProvider for a single name)."""


NON_PROVIDERS = ("schema-2", "adapter-schema")   # JSON files in lib/providers/ that describe definitions and adapters; they are not providers


def _conf():
    try:
        sys.path.insert(0, HERE)
        import paths
        return paths.conf()
    except ImportError:                           # a copy of this file without its neighbours (the tests): the same rule by hand
        return os.environ.get("QARGI_CONF") or os.path.join(os.path.expanduser("~"), ".qargi", "config")


def _state_dir():
    try:
        sys.path.insert(0, HERE)
        import paths
        return paths.state()
    except ImportError:
        return os.environ.get("QARGI_STATE") or os.path.join(os.path.expanduser("~"), ".qargi", "state")


def library_dir():
    """The pack library of provider definitions: QARGI_CONF/packs/providers/NAME/definition.json."""
    return os.path.join(_conf(), "packs", "providers")


def _sources(root, library):
    """(the shipped directory, the library directory or None). With the default shipped directory the library is the user's; a test
    that names its own root sees a library only when it names one too."""
    if root is None:
        return PROVIDERS, (library_dir() if library is None else library)
    return root, library or None


def _json_names(d):
    try:
        return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and NAME_RE.match(f[:-5]))
    except OSError:
        return []


def _read(e):
    """The document of a scanned file, as it is. ProviderError when it is not readable JSON or not an object."""
    if "raw" not in e and "error" not in e:
        try:
            with open(e["file"]) as f:
                d = json.load(f)
            if isinstance(d, dict):
                e["raw"] = d
            else:
                e["error"] = "%s '%s' is not a JSON object" % (e["kind"] or "provider", e["name"])
        except (OSError, ValueError) as ex:
            e["error"] = "%s '%s' is not readable JSON: %s" % (e["kind"] or "provider", e["name"], ex)
    if "error" in e:
        raise ProviderError(e["error"])
    return e["raw"]


def _kind(e):
    if e["kind"] is None:                         # a library file says what it is
        try:
            k = _read(e).get("kind", "provider")
            e["kind"] = k if isinstance(k, str) else "provider"
        except ProviderError:
            e["kind"] = "provider"                # unreadable: listed, and refused when it is used
    return e["kind"]


def _scan(root, library):
    """name -> [entry]: the shipped providers (DIR/NAME.json) and catalogs (DIR/catalogs/FAMILY.json) and the library's definitions."""
    root, library = _sources(root, library)
    found = {}
    for n in _json_names(root):
        if n not in NON_PROVIDERS:
            found.setdefault(n, []).append({"name": n, "kind": "provider", "origin": "shipped", "file": os.path.join(root, n + ".json"),
                                            "dir": os.path.join(root, n)})
    for n in _json_names(os.path.join(root, "catalogs")):
        found.setdefault(n, []).append({"name": n, "kind": "catalog", "origin": "shipped",
                                        "file": os.path.join(root, "catalogs", n + ".json"), "dir": os.path.join(root, "catalogs")})
    try:
        dirs = sorted(os.listdir(library)) if library else []
    except OSError:
        dirs = []
    for n in dirs:
        f = os.path.join(library, n, "definition.json")
        if NAME_RE.match(n) and os.path.isfile(f):
            found.setdefault(n, []).append({"name": n, "kind": None, "origin": "library", "file": f, "dir": os.path.join(library, n)})
    return found


# ---- library packs: the content hash, the record, the seal ------------------------------------------------------------------

RECORD = ".pack.json"


def tree_hash(root):
    """sha256 of the content of a pack directory: every file but the record, by relative path, with its executable bit and the sha256 of
    its bytes (a symbolic link by its target), so that a changed byte, a new file, a removed one or a chmod +x all change it."""
    rows = []
    for dp, dns, fns in os.walk(root, followlinks=False):
        for n in sorted(dns + fns):
            p = os.path.join(dp, n)
            rel = os.path.relpath(p, root)
            if rel == RECORD:
                continue
            if os.path.islink(p):
                rows.append("L %s %s" % (rel, os.readlink(p)))
            elif os.path.isfile(p):
                with open(p, "rb") as f:
                    rows.append("F %s %s %s" % (rel, "x" if os.stat(p).st_mode & 0o111 else "-", hashlib.sha256(f.read()).hexdigest()))
    return hashlib.sha256("\n".join(sorted(rows)).encode("utf-8")).hexdigest()


def pack_record(directory):
    """The record of a library pack (its .pack.json) as a dict, or None when there is none or it cannot be read."""
    try:
        with open(os.path.join(directory, RECORD)) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return None
    return d if isinstance(d, dict) else None


def seal_state(e):
    """(state, why) of an entry: shipped; sealed (the record names the content hash and it is the hash now); unsealed (a record that says
    so: `provider new` made it); drift (the content is not what was sealed); unrecorded (a library directory with no record: a file
    put there by hand, which nobody read or approved; it is not used, any more than an unsealed or a changed pack)."""
    if e["origin"] != "library":
        return "shipped", ""
    rec = pack_record(os.path.dirname(e["file"]))
    if rec is None:
        if os.path.lexists(os.path.join(os.path.dirname(e["file"]), RECORD)):
            return "drift", "has a record that cannot be read"
        return "unrecorded", "has no record (put there by hand)"
    if rec.get("sealed") is False or not isinstance(rec.get("sha256"), str):
        return "unsealed", "is not sealed"
    if rec["sha256"] != tree_hash(os.path.dirname(e["file"])):
        return "drift", "changed since it was sealed"
    return "sealed", ""


# ---- the environment pack and runtime code gets ----------------------------------------------------------------------------------

ENV_DENIED = {
    "HOME": "the run's own home is set by qargi, never the real one", "USER": "the login identity is not handed on", "LOGNAME": "the login identity is not handed on",
    "SHELL": "the login shell is not handed on", "PWD": "the working directory is set by qargi", "OLDPWD": "the working directory is set by qargi",
    "TMPDIR": "the run's temporary directory is set by qargi", "TMP": "the run's temporary directory is set by qargi", "TEMP": "the run's temporary directory is set by qargi",
    "PATH": "the search path is qargi's (absolute entries of the caller's PATH); a pack does not replace it", "IFS": "it changes how a shell splits words",
    "CDPATH": "it changes where a shell goes", "ENV": "a shell startup file", "BASH_ENV": "a shell startup file", "SHELLOPTS": "it changes how a shell behaves",
    "BASHOPTS": "it changes how a shell behaves", "PROMPT_COMMAND": "a command a shell runs by itself", "PS4": "a shell prompt that runs commands",
    "NODE_OPTIONS": "it loads code into node", "NODE_PATH": "it changes where node loads code from", "JAVA_TOOL_OPTIONS": "it loads code into java",
    "_JAVA_OPTIONS": "it loads code into java", "CLASSPATH": "it changes where java loads code from", "GCONV_PATH": "it changes where libc loads code from",
    "LOCPATH": "it changes where libc loads code from", "NLSPATH": "it changes where libc loads code from",
    "EDITOR": "a program other tools run by themselves", "VISUAL": "a program other tools run by themselves", "PAGER": "a program other tools run by themselves",
    "MANPAGER": "a program other tools run by themselves", "BROWSER": "a program other tools run by themselves", "GIT": "qargi's git wrapper of the run",
    "GNUPGHOME": "the user's keys", "NETRC": "the user's stored logins", "KRB5CCNAME": "the user's Kerberos credentials",
}
ENV_DENIED_PREFIX = (
    ("GIT_", "the run's git wrapper and its settings are qargi's"), ("QARGI_", "qargi's own settings are not handed on"),
    ("LD_", "it changes what the dynamic loader loads"), ("DYLD_", "it changes what the dynamic loader loads"),
    ("PYTHON", "it changes what python loads"), ("PERL", "it changes what perl loads"), ("RUBY", "it changes what ruby loads"),
    ("BASH_FUNC_", "an exported shell function"), ("XDG_", "the run's own configuration, data and state directories are qargi's"),
    ("SSH_", "the ssh agent and its keys are the user's, and a member never pushes"), ("GPG_", "the user's signing agent"),
    ("GH_", "a forge credential: a member never pushes or calls the forge"), ("GITHUB_", "a forge credential: a member never pushes or calls the forge"),
    ("GITLAB_", "a forge credential: a member never pushes or calls the forge"), ("BITBUCKET_", "a forge credential: a member never pushes or calls the forge"),
)


def env_pass_problem(name):
    """Why a variable of the caller's environment may not be listed in a runtime's dispatch.env_pass, or None when it may. What is refused is
    what would hand the member or a pack the user's own home, search path, code loaders, shell startup, ssh agent or forge credentials, or
    would replace what qargi sets for the run. A name that merely looks like a credential (an API key the vendor's command needs) is
    allowed: it travels by name, and the review shows it (review.scan lists env_pass and flags such names)."""
    if name in ENV_DENIED:
        return ENV_DENIED[name]
    for prefix, why in ENV_DENIED_PREFIX:
        if name.startswith(prefix):
            return why
    return None


def pack_env(home, tmp):
    """The environment pack code runs in when qargi runs it itself (the conformance harness of `provider check`): nothing of the caller's, only
    a search path of absolute entries, a home and temporary directory of the run, a locale and a clock zone. Same shape as the environment a
    renderer command gets (render.py) and a member gets (local_run.py) before its env_pass names."""
    path = os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if p.startswith("/")) or "/usr/local/bin:/usr/bin:/bin"
    return {"PATH": path, "HOME": home, "TMPDIR": tmp, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "TERM": "dumb"}


def exec_copy(name, rel, root=None, library=None, tmp=None):
    """(directory, path): a private copy (mode 0700, in tmp or the temporary directory) of the library pack NAME, and the executable rel in
    it. The pack must be sealed with that executable approved: the content hash and the executable's hash are compared with the record
    before the copy is made and again on the copy, so what runs is what was approved, whatever happens to the library meanwhile. The
    copy sits in a directory of its own, tmp/qargi-exec.XXXX/, and `directory` is the pack inside it (tmp/qargi-exec.XXXX/NAME): what
    the caller removes afterwards is the PARENT of `directory`, so that no empty qargi-exec.XXXX is left behind; discard_exec_copy(directory)
    does exactly that. Refused (Refused) for a pack that is not sealed, or an executable the record does not list."""
    import shutil
    import tempfile
    e = entry_any(name, root, library)
    if e is None or e["origin"] != "library":
        raise Refused("'%s' is not a library pack; only a library pack's executables are checked this way (a shipped one is part of the tool)" % name)
    src = os.path.dirname(e["file"])
    state, why = seal_state(e)
    rec = pack_record(src) or {}
    if state != "sealed":
        raise Drift("pack '%s' %s; its executables are not run" % (name, why or state))
    want = (rec.get("executables") or {}).get(rel)
    n = os.path.normpath(rel) if isinstance(rel, str) else ""
    if not want or n != rel or rel.startswith(("/", "..")):
        raise Refused("'%s' is not an executable approved for the pack '%s'" % (rel, name))
    d = tempfile.mkdtemp(prefix="qargi-exec.", dir=tmp)
    try:
        dst = os.path.join(d, name)
        shutil.copytree(src, dst, symlinks=True)
        got = tree_hash(dst)
        with open(os.path.join(dst, rel), "rb") as f:
            gotx = hashlib.sha256(f.read()).hexdigest()
        if got != rec["sha256"] or gotx != want:
            raise Drift("pack '%s' changed while it was being copied; its executables are not run" % name)
    except BaseException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    return dst, os.path.join(dst, rel)


def discard_exec_copy(directory):
    """Remove what exec_copy made: the temporary directory that holds the copy, given the `directory` exec_copy returned (the pack
    inside it). Refuses to remove anything that is not shaped like that (a directory whose parent is not a qargi-exec.* one), so a wrong
    argument cannot delete the temporary directory itself or anything above it. No error when it is already gone."""
    import shutil
    parent = os.path.dirname(os.path.abspath(directory))
    if not os.path.basename(parent).startswith("qargi-exec."):
        raise ProviderError("%s is not a copy made by exec_copy; not removed" % directory)
    shutil.rmtree(parent, ignore_errors=True)


def names(root=None, library=None):
    """The providers that have a definition: the shipped files (schema-2.json describes them and is not one) and the library's. A name
    defined in both is listed once; using it is refused."""
    return sorted(n for n, es in _scan(root, library).items() if any(_kind(e) == "provider" for e in es))


def _pick(name, kind, root, library):
    """The one entry of this name and kind, or None. A name defined both shipped and in the library is Clash, whatever its kinds."""
    es = _scan(root, library).get(name, [])
    if len({e["origin"] for e in es}) > 1:
        raise Clash("'%s' is defined twice (shipped and library); qargi provider remove %s, or rename it" % (name, name))
    es = [e for e in es if _kind(e) == kind]
    if es and es[0]["origin"] == "library":
        state, why = seal_state(es[0])
        if state == "unrecorded":
            raise Drift("%s '%s' %s and was never reviewed, so it is not used; read it and seal it (qargi provider seal %s), or qargi provider import it from its source"
                        % (kind, name, why, name))
        if state != "sealed":
            raise Drift("%s '%s' %s; qargi provider check %s, then qargi provider seal %s" % (kind, name, why, name, name))
    return es[0] if es else None


def entry_any(name, root=None, library=None):
    """The one entry of this name whatever its kind (provider, catalog or extension), or None. A name defined both shipped and in the
    library is Clash. The seal is not checked: this is for the verbs that manage packs."""
    if not isinstance(name, str) or not NAME_RE.match(name) or name in NON_PROVIDERS:
        return None
    es = _scan(root, library).get(name, [])
    if len({e["origin"] for e in es}) > 1:
        raise Clash("'%s' is defined twice (shipped and library); qargi provider remove %s, or rename it" % (name, name))
    if es:
        _kind(es[0])
    return es[0] if es else None


def _entry(name, root=None, library=None):
    if not isinstance(name, str) or not NAME_RE.match(name) or name in NON_PROVIDERS:
        raise ProviderError("unknown provider '%s'" % name)
    e = _pick(name, "provider", root, library)
    if e is None:
        raise ProviderError("unknown provider '%s'; available: %s" % (name, ", ".join(names(root, library)) or "none"))
    return e


def origin(name, root=None, library=None):
    """shipped or library."""
    return _entry(name, root, library)["origin"]


def _docs(e):
    """surface -> definition of an entry: the one surface a runtime serves. ProviderError when the file is not a definition of schema 2."""
    raw = _read(e)
    if not (type(raw.get("schema")) is int and raw["schema"] == 2):
        raise ProviderError("'%s' is not a definition of schema 2 (its schema is %s); see lib/providers/schema-2.json" % (e["name"], _show(raw.get("schema"))))
    if raw.get("kind") != "provider":
        raise ProviderError("'%s' is a %s, not a provider" % (e["name"], raw.get("kind")))
    if e["origin"] == "library" and raw.get("provider") != e["name"]:
        raise ProviderError("library definition '%s' declares provider '%s'; the directory and the name must agree" % (e["name"], raw.get("provider")))
    if raw.get("surface") not in SURFACES:
        raise ProviderError("provider '%s' has no valid surface (one of %s)" % (e["name"], ", ".join(SURFACES)))
    return {raw["surface"]: raw}


def surfaces_of(name, root=None, library=None):
    """The surfaces a provider serves, in the order its definition lists them."""
    return list(_docs(_entry(name, root, library)))


def definition(name, surface=None, root=None, library=None):
    """The definition of a runtime on its surface (a copy). Without a surface the runtime must serve only one, which is always so."""
    docs = _docs(_entry(name, root, library))
    if surface is None:
        if len(docs) != 1:
            raise ProviderError("provider %s serves %s; name the surface" % (name, ", ".join(docs) or "no surface"))
        surface = next(iter(docs))
    if surface not in docs:
        raise ProviderError("the provider %s does not list the surface %s" % (name, surface))
    return copy.deepcopy(docs[surface])


def composed(name, surface=None, project=None, root=None, library=None, conf=None):
    """The definition a consumer of a PROJECT acts on: definition(name, surface), and with a project the runtime composed with the
    extensions the project enabled (compose()), so the resources, renderers, barrier and capabilities an extension adds are there. The
    same as definition() without a project, or when the project enables none. Without a surface the runtime must serve only one."""
    base = definition(name, surface, root, library)
    if not project:
        return base
    return compose(name, base["surface"], project, root=root, library=library, conf=conf)["definition"]


def definitions_unsealed(name, root=None, library=None):
    """{surface: schema 2 definition} of a provider WITHOUT looking at its seal: for a reader that must see what a definition names
    (the directories the guard protects) even while the pack is unsealed or changed and so not used. Never use it to run or trust
    anything. ProviderError when there is no such provider or it does not load."""
    e = entry_any(name, root, library)
    if e is None or _kind(e) != "provider":
        raise ProviderError("unknown provider '%s'" % name)
    return copy.deepcopy(_docs(e))


def catalog(family, root=None, library=None):
    """The catalog (schema 2 document) of a family. ProviderError when there is none or the file is not one; Clash when it is defined
    in both places."""
    e = _pick(family, "catalog", root, library) if isinstance(family, str) and NAME_RE.match(family) else None
    if e is None:
        raise ProviderError("no catalog '%s'" % family)
    raw = _read(e)
    if not (type(raw.get("schema")) is int and raw["schema"] == 2 and raw.get("kind") == "catalog"):
        raise ProviderError("catalog '%s' is not a catalog (schema 2, kind catalog)" % family)
    return raw


def models_of(name, surface=None, root=None, library=None, project=None, conf=None):
    """The models of a runtime, resolved: {pattern, tiers: {TIER: {model, alias, verified_on, source}} for every tier, effort: {LEVEL:
    native or None} for every level, use: alias, id or None, catalog: the family or None}. A catalog reference is followed; a tier
    not given takes '*'. With a project, the definition is the runtime composed with the project's enabled extensions (composed())."""
    return _resolve_models(composed(name, surface, project, root, library, conf), root, library)


def _resolve_models(doc, root=None, library=None):
    m = doc.get("models") if isinstance(doc.get("models"), dict) else {}
    if "catalog" in m:
        cat = catalog(m["catalog"], root, library)
        pattern, tiers, effort, use = cat.get("pattern"), cat.get("tiers"), cat.get("effort"), m.get("use")
    else:
        pattern, tiers, effort, use = m.get("pattern"), m.get("tiers"), m.get("effort"), None
    tiers = tiers if isinstance(tiers, dict) else {}
    out = {}
    for t in TIERS:
        row = tiers.get(t) if isinstance(tiers.get(t), dict) else tiers.get("*")
        if not isinstance(row, dict):
            raise ProviderError("provider %s: tier '%s' resolves to no model" % (doc.get("provider"), t))
        out[t] = copy.deepcopy(row)
    effort = effort if isinstance(effort, dict) else {}
    return {"pattern": pattern, "tiers": out, "effort": {k: effort.get(k) for k in EFFORTS}, "use": use, "catalog": m.get("catalog")}


def model_for(models, tier):
    """The model name qargi passes for a tier: the alias when the runtime uses aliases and the tier has one, else the id."""
    row = models["tiers"][tier]
    return row["alias"] if models.get("use") == "alias" and row.get("alias") else row["model"]


def summary(name, surface=None, root=None, library=None):
    """What a reader needs of a runtime on one surface, flat: {provider, surface, surfaces, model_pattern, use, tier_detail: {TIER: {model,
    alias, verified_on, source}}, tiers: {TIER: model id}, aliases: {TIER: alias or None}, effort: {LEVEL: native or None}, reserved_names,
    adapter}. It is definition() and models_of() read together; the adapter is the path of a shipped runtime's adapter relative to the tool
    root (None for a library pack's, which runs only as a sealed copy, and for a runtime that names none). Without a surface the runtime
    must serve only one. ProviderError when there is no such runtime or it does not serve the surface."""
    doc = definition(name, surface, root, library)
    m = _resolve_models(doc, root, library)
    ad = doc.get("adapter")
    return {"provider": doc["provider"], "surface": doc["surface"], "surfaces": surfaces_of(name, root, library),
            "model_pattern": m["pattern"], "use": m["use"], "tier_detail": m["tiers"],
            "tiers": {t: m["tiers"][t]["model"] for t in TIERS}, "aliases": {t: m["tiers"][t].get("alias") for t in TIERS},
            "effort": m["effort"], "reserved_names": list(_dict(doc.get("agents")).get("reserved_names") or []),
            "adapter": "lib/providers/%s/%s" % (doc["provider"], ad) if isinstance(ad, str) and _entry(name, root, library)["origin"] == "shipped" else None}


def _dict(v):
    return v if isinstance(v, dict) else {}


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
    date, required, properties, minProperties, additionalProperties false, items, minItems, minLength, uniqueItems and a local $ref."""
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
    if "minLength" in s and isinstance(v, str) and len(v) < s["minLength"]:
        out.append((path, "is shorter than %d character%s" % (s["minLength"], "" if s["minLength"] == 1 else "s")))
    if isinstance(v, dict):
        props = s.get("properties", {})
        if len(v) < s.get("minProperties", 0):
            out.append((path, "needs at least %d propert%s" % (s["minProperties"], "y" if s["minProperties"] == 1 else "ies")))
        for k in s.get("required", []):
            if k not in v:
                if path == "tiers":
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


def _control_problems(d):
    """[("fail", message)] for a control, escape or bidi character in any key or string of a parsed definition, whether it was written raw or
    as a JSON escape (the bytes of the file are then plain ASCII, so a scan of the file cannot see it). It is the only finding returned for
    such a document: the other messages would carry the key or the value they complain about."""
    r = _review()
    if r:
        return [("fail", m) for m in r.strings_problems(d)]
    out = []

    def walk(x, path):                           # without conformance/: the same rule, tested with str.isprintable (a little stricter)
        if isinstance(x, dict):
            for k, v in x.items():
                here = "%s.%s" % (path, k) if path else str(k)
                if isinstance(k, str) and not k.isprintable():
                    out.append(("fail", "%s: the key has a control or bidi character, which can change what a reader sees; a definition holds plain one-line text" % vis(here)))
                walk(v, here)
        elif isinstance(x, list):
            for i, v in enumerate(x):
                walk(v, "%s[%d]" % (path, i))
        elif isinstance(x, str) and not x.isprintable():
            out.append(("fail", "%s: the value has a control or bidi character, which can change what a reader sees; a definition holds plain one-line text" % vis(path or "the document")))
    walk(d, "")
    return out[:10]


# ---- the schema: kinds, capabilities, the rules a schema cannot state -----------------------------------------------------------

KINDS = ("provider", "catalog")
EFFORTS = ("low", "medium", "high", "xhigh", "max")


def schema2():
    with open(os.path.join(PROVIDERS, "schema-2.json")) as f:
        return json.load(f)


def capabilities2():
    """The capability names a definition can claim."""
    return tuple(schema2()["$defs"]["provider"]["properties"]["capabilities"]["properties"])


def _inside(v):
    """A path inside the checkout: relative, not empty, no ..  (the paths of a definition are data, never trusted)."""
    return isinstance(v, str) and bool(v) and not v.startswith(("/", "~")) and ".." not in v.split("/")


def _in_home(v):
    return isinstance(v, str) and v.startswith("~/") and ".." not in v.split("/")


def _tier_problems(pattern, tiers, prefix, pat_path):
    """The rules of a tier map a schema cannot state: the pattern compiles, every model matches it, every tier resolves."""
    bad, rx = [], None
    if isinstance(pattern, str):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            bad.append("%s: not a regular expression (%s)" % (pat_path, e))
    if not isinstance(tiers, dict):
        return bad
    for slot, row in tiers.items():
        if rx and isinstance(row, dict) and isinstance(row.get("model"), str) and not rx.search(row["model"]):
            bad.append("%s%s.model: '%s' does not match pattern %s" % (prefix, slot, row["model"], pattern))
    for t in TIERS:
        if t not in tiers and "*" not in tiers:
            bad.append("%s: tier '%s' resolves to no model (give it or '*')" % (prefix.rstrip("."), t))
    return bad


def _models_problems(m):
    if not isinstance(m, dict):
        return []
    has_ref = "catalog" in m
    inline = [k for k in ("pattern", "tiers", "effort") if k in m]
    if has_ref and inline:
        return ["models: a catalog reference and inline models are two forms; give one"]
    if has_ref:
        return [] if "use" in m else ["models: a catalog reference needs use (alias or id)"]
    if "use" in m:
        return ["models: use belongs to a catalog reference"]
    if not ("pattern" in m or "tiers" in m):
        return ["models: needs a catalog reference or inline models (pattern and tiers)"]
    bad = [] if "tiers" in m else ["models: inline models need tiers"]
    bad += [] if "pattern" in m else ["models: inline models need pattern"]
    return bad or _tier_problems(m["pattern"], m["tiers"], "models.tiers.", "models.pattern")


def _path_problem(label, v, user_ok, inside_ok=True):
    """None, or why the path v of a definition is refused: a checkout path is relative with no .., a user path starts with ~/."""
    if not isinstance(v, str):
        return None
    if _in_home(v) and user_ok:
        return None
    if _inside(v) and inside_ok:
        return None
    if user_ok and not inside_ok:
        return "%s: '%s' does not start with ~/" % (label, v)
    return "%s: '%s' is not a path inside the checkout (relative, no ..)" % (label, v)


EXCLUSION_NEEDS = {"settings-key": ("files", "pointer", "shape", "off"), "config-list": ("file", "format", "pointer", "match", "off"),
                   "deny-list": ("file", "format", "pointer")}


def _exclusion_problems(label, ex, settings_scopes):
    if not isinstance(ex, dict) or ex.get("form") not in EXCLUSION_NEEDS:
        return []
    need = EXCLUSION_NEEDS[ex["form"]]
    if any(k not in ex for k in need):
        return ["%s: form %s needs %s" % (label, ex["form"], ", ".join(need[:-1]) + " and " + need[-1])]
    bad = []
    if ex["form"] != "settings-key":
        p = _path_problem(label + ".file", ex.get("file"), True)
        bad += [p] if p else []
    for sc in ex.get("files") or []:
        if sc not in settings_scopes:
            bad.append("%s.files: scope '%s' is not among resources.settings.files" % (label, sc))
    return bad


def _plain_relative(v):
    """A relative path as normpath writes it, inside its directory: not empty, not absolute, no ~, no .. , no . or empty part, no trailing /."""
    return isinstance(v, str) and bool(v) and not v.startswith(("/", "~")) and os.path.normpath(v) == v and v != "." and ".." not in v.split("/")


def _resource_problems(res, extension=False):
    """The rules of the resources a schema cannot state (the types are the schema's): project paths stay inside the checkout, user
    paths start with ~/, {checkout_key} needs a rule, an exclusion has the keys its form reads."""
    if not isinstance(res, dict):
        return []
    bad = []

    def add(p):
        if p:
            bad.append(p)
    st = res.get("settings") if isinstance(res.get("settings"), dict) else {}
    scopes = {f.get("scope") for f in st.get("files") or [] if isinstance(f, dict)}
    for kind in ("skills", "agents"):
        r = res.get(kind)
        if not isinstance(r, dict):
            continue
        add(_path_problem("resources.%s.project_dir" % kind, r.get("project_dir"), False))
        add(_path_problem("resources.%s.user_dir" % kind, r.get("user_dir"), True, inside_ok=False))
        bad += _exclusion_problems("resources.%s.exclusion" % kind, r.get("exclusion"), scopes)
    ins = res.get("instructions")
    if isinstance(ins, dict):
        for i, n in enumerate(ins.get("project_file") or []):
            if not isinstance(n, str) or not n or "/" in n or n in (".", ".."):
                bad.append("resources.instructions.project_file[%d]: '%s' is not a plain file name" % (i, n))
        add(_path_problem("resources.instructions.user_file", ins.get("user_file"), True, inside_ok=False))
    mcp = res.get("mcp")
    if isinstance(mcp, dict):
        add(_path_problem("resources.mcp.file", mcp.get("file"), True))
    for i, f in enumerate(st.get("files") or []):
        if isinstance(f, dict) and isinstance(f.get("path"), str):
            lab = "resources.settings.files[%d].path" % i
            if f.get("scope") == "user":
                if not _in_home(f["path"]):
                    bad.append("%s: the user file '%s' does not start with ~/" % (lab, f["path"]))
            else:
                add(_path_problem(lab, f["path"], False))
    ca = res.get("contract_addenda")
    if extension and ca is not None:
        bad.append("resources.contract_addenda: an extension cannot add contract addenda (only a runtime's own definition has them)")
    for i, n in enumerate(ca if isinstance(ca, list) and not extension else ()):
        if isinstance(n, str) and not _plain_relative(n):
            bad.append("resources.contract_addenda[%d]: '%s' is not a file inside the definition's directory (a relative path, no .., no ~, no empty part)" % (i, n))
    mem = res.get("memory")
    if isinstance(mem, dict) and isinstance(mem.get("user_dir"), str):
        add(_path_problem("resources.memory.user_dir", mem["user_dir"], True, inside_ok=False))
        if "{checkout_key}" in mem["user_dir"] and mem.get("checkout_key") is None:
            bad.append("resources.memory.user_dir: uses {checkout_key} but checkout_key is null")
    return bad


NOTE_TOPIC_RE = re.compile(r"^[a-z][a-z0-9-]{0,31}$")
NOTE_MAX, NOTES_MAX = 2000, 16


def _notes_problems(notes):
    """The rules of a definition's notes (topic name -> text) that a schema cannot state: at most NOTES_MAX topics, each topic a lower case
    name of at most 32 characters, each text a non-empty string of at most NOTE_MAX characters with no format, private-use or unassigned
    character (the control characters, tab and newline too, are refused for every string of a definition by _control_problems)."""
    if not isinstance(notes, dict):
        return []                                  # the schema reports the type
    bad = []
    if len(notes) > NOTES_MAX:
        bad.append("notes: %d topics are more than the %d a definition may hold" % (len(notes), NOTES_MAX))
    for topic, text in notes.items():
        if not NOTE_TOPIC_RE.match(topic):
            bad.append("notes: the topic name %s is not a name (lower case letters, digits and -, starting with a letter, at most 32 characters)" % _show(topic))
        elif not isinstance(text, str):
            bad.append("notes.%s: %s is not of type string" % (topic, _show(text)))
        elif not text:
            bad.append("notes.%s: the text is empty" % topic)
        elif len(text) > NOTE_MAX:
            bad.append("notes.%s: the text is longer than %d characters" % (topic, NOTE_MAX))
        elif _addendum_has_bad_character(text):
            bad.append("notes.%s: the text is not plain text (no control, format, private-use or unassigned characters)" % topic)
    return bad


EXTENSION_KEYS = ("schema", "kind", "extension", "description", "extends", "surface", "provides", "requires", "adds")
EXTENSION_ADDS = ("capabilities", "resources", "renderers", "dispatch", "barrier", "adapter_verbs")
RESOURCES = ("skills", "agents", "instructions", "mcp", "settings", "memory")


def validate_extension(d, name=None):
    """The findings for an extension pack (schema 2, kind extension): the node of schema-2.json, then the rules a schema cannot state
    (the name equals the directory name, provides equals the capabilities that adds names, every path stays inside the pack or the
    checkout). The name it carries is `extension`. A message worded by a rule below replaces the schema's own for the same field."""
    out = _control_problems(d)
    if out:
        return out
    for k in d:
        if k not in EXTENSION_KEYS:
            out.append(("fail", "%s: additional property is not allowed" % k))
    if d.get("schema") != 2 or type(d.get("schema")) is not int:
        out.append(("fail", "schema: %s is not the supported version 2" % _show(d.get("schema"))))
    nm = d.get("extension")
    if not isinstance(nm, str) or not NAME_RE.match(nm) or len(nm) > 40:
        out.append(("fail", "extension: %s is not a name (lower case letters, digits and -, starting with a letter, at most 40 characters)" % _show(nm)))
    elif name is not None and nm != name:
        out.append(("fail", "extension '%s' differs from the file name '%s'" % (nm, name)))
    ex = d.get("extends")
    if not isinstance(ex, str) or not NAME_RE.match(ex):
        out.append(("fail", "extends: %s is not a runtime or family name" % _show(ex)))
    caps = capabilities2()
    pv = d.get("provides")
    if not isinstance(pv, list) or not all(isinstance(c, str) for c in pv):
        out.append(("fail", "provides: a list of capability names"))
    else:
        out += [("fail", "provides: unknown capability '%s'" % c) for c in pv if c not in caps]
    adds = d.get("adds")
    if not isinstance(adds, dict):
        out.append(("fail", "adds: an object"))
    else:
        cells = adds.get("capabilities") if isinstance(adds.get("capabilities"), dict) else {}
        if isinstance(pv, list) and sorted(set(pv)) != sorted(cells):
            out.append(("fail", "provides must equal the capability names of adds.capabilities (%s)" % (", ".join(sorted(cells)) or "none")))
        for c, cl in cells.items():
            if not isinstance(cl, dict) or cl.get("value") not in ("yes", "partial", "no"):
                out.append(("fail", "adds.capabilities.%s: a cell with value yes, partial or no" % c))
        verbs = adds.get("adapter_verbs")
        if verbs is not None and not (isinstance(verbs, dict) and all(isinstance(v, str) and _inside(v) for v in verbs.values())):
            out.append(("fail", "adds.adapter_verbs: {VERB: a path inside the pack}"))
        if isinstance(adds.get("resources"), dict):
            out += [("fail", "adds." + m) for m in _resource_problems(adds["resources"], extension=True)]
        if "notes" in adds:
            out.append(("fail", "adds.notes: an extension cannot add notes (only a runtime's own definition has them)"))
    rq = d.get("requires")
    if rq is not None and not isinstance(rq, dict):
        out.append(("fail", "requires: an object"))
    elif isinstance(rq, dict) and isinstance(rq.get("capabilities"), list):
        out += [("fail", "requires.capabilities: unknown capability '%s'" % c) for c in rq["capabilities"] if isinstance(c, str) and c not in caps]
    have = [m for _, m in out]
    sch = schema2()
    raw = []
    _check(d, {"$ref": sch["kinds"]["extension"]}, sch, "", raw)
    for path, text in raw:
        if not any(m.startswith(path) for m in have if path):
            out.append(("fail", _msg(path, text)))
    return out


def validate2(d, name=None):
    """Findings for a definition or a catalog: the node of schema-2.json for its kind, then the rules a schema cannot state; "fail" for a
    violation, "warn" for a capability that is claimed and not verified. name, when given, is the file (or directory) name the document
    must carry. An extension goes to validate_extension()."""
    if not isinstance(d, dict):
        return [("fail", "the document is not a JSON object")]
    ctl = _control_problems(d)
    if ctl:
        return ctl
    if d.get("kind") == "extension":
        return validate_extension(d, name)
    sch = schema2()
    raw = []
    _check(d, {"type": "object", "required": ["schema", "kind"], "properties": {"schema": {"const": 2}, "kind": {"enum": list(KINDS) + ["extension"]}}},
           sch, "", raw)
    kind = d.get("kind")
    if kind not in KINDS:
        return [("fail", _msg(p, m)) for p, m in raw]
    raw = []
    _check(d, {"$ref": sch["kinds"][kind]}, sch, "", raw)
    out = [("fail", _msg(p, m)) for p, m in raw]
    key = "provider" if kind == "provider" else "family"
    if name is not None and isinstance(d.get(key), str) and d[key] != name:
        out.append(("fail", "%s '%s' differs from the file name '%s'" % (key, d[key], name)))
    if kind == "catalog":
        out += [("fail", m) for m in _tier_problems(d.get("pattern"), d.get("tiers"), "tiers.", "pattern")]
        return out
    out += [("fail", m) for m in _models_problems(d.get("models"))]
    out += [("fail", m) for m in _resource_problems(d.get("resources"))]
    out += [("fail", m) for m in _notes_problems(d.get("notes"))]
    disp =d.get("dispatch")
    if isinstance(disp, dict) and isinstance(disp.get("env_pass"), list):
        out += [("fail", "dispatch.env_pass: %s is never handed on: %s" % (n, env_pass_problem(n))) for n in disp["env_pass"] if isinstance(n, str) and env_pass_problem(n)]
    ad = d.get("adapter")
    if isinstance(ad, str) and (not ad or os.path.isabs(ad) or ad.startswith("~") or ".." in ad.split("/")):
        out.append(("fail", "adapter: '%s' is not a path inside the definition's directory" % ad))
    for c, c_cell in (d.get("capabilities") or {}).items() if isinstance(d.get("capabilities"), dict) else ():
        if isinstance(c_cell, dict) and c_cell.get("value") in ("yes", "partial") and not c_cell.get("verified_on"):
            out.append(("warn", "capabilities.%s.verified_on: not verified (counts as not supported until verified)" % c))
    return out


def has_class_args(disp):
    """Does a dispatch carry arguments for a read-only member: a non-empty class_argv (a list, or the list under "read-only"), or a
    {"class": "read-only"} group with an argument in argv (also inside an {"if": ..., "then": [...]})? Arguments for any other class, an empty
    list and an empty group hold nothing, so they do not count."""
    def has(items, ro):
        for i in items if isinstance(items, list) else ():
            if isinstance(i, str):
                if ro:
                    return True
            elif isinstance(i, dict):
                if "class" in i:
                    if i["class"] == "read-only" and has(i.get("then"), True):         # a group of another class is never expanded for a read-only run
                        return True
                elif has(i.get("then"), ro):
                    return True
        return False
    disp = disp if isinstance(disp, dict) else {}
    ca = disp.get("class_argv")
    return has(ca.get("read-only") if isinstance(ca, dict) else ca, True) or has(disp.get("argv"), False)


def barrier_claim_problem(doc, by=None):
    """Why a definition's claim of read_only_barrier (yes or partial) is a fail-open, or None. The claim is true of nothing when the barrier
    kind is none (or absent) and the dispatch has no read-only arguments: no hook, no sandbox, no adapter and no class arguments hold a
    read-only member, yet the capability reads as a barrier, so a read-only run would be treated as held. doc is a runtime definition or
    a composition of a runtime and extensions (compose()); by names the extension that gives the claim, for the message."""
    cell = _dict(_dict(doc.get("capabilities")).get("read_only_barrier")) if isinstance(doc, dict) else {}
    if cell.get("value") not in ("yes", "partial"):
        return None
    bar = doc.get("barrier")
    kind = bar.get("kind") if isinstance(bar, dict) else None
    if kind not in (None, "none") or has_class_args(doc.get("dispatch")):
        return None
    return ("capabilities.read_only_barrier: %s claims %s on %s, but barrier.kind is none and the dispatch has no read-only arguments (class_argv, or a "
            "{\"class\": \"read-only\"} group in argv), so nothing holds a read-only member and it would be treated as held; set barrier.kind (hook, "
            "sandbox-args or adapter, with what that kind needs), or declare the capability not supported (value no)"
            % (by or doc.get("provider") or "the definition", cell["value"], doc.get("surface") or "its surface"))


# ---- capabilities -----------------------------------------------------------------------------------------------------

VERIFIERS = ("conformance", "attest")


def definition_hash(name, root=None, library=None):
    """sha256 of the definition as it is now: its document and, when it references one, its catalog; for a sealed library pack also the
    content hash of the pack (its executables and every other file), and of the catalog's pack. A change to any of them changes the
    hash, so a verification record made earlier no longer matches. Extensions are not in it: a runtime's own records do not depend on the
    extensions a project enables (an extension adds, never overrides); an extension's records chain to this hash (extension_hash).
    ProviderError when the catalog it references is missing."""
    e = _entry(name, root, library)
    raw = _read(e)
    body = {"definition": raw}
    sealed = _sealed_hash(e)
    if sealed:
        body["pack"] = sealed
    if isinstance(raw.get("models"), dict) and "catalog" in raw["models"]:
        body["catalog"] = catalog(raw["models"]["catalog"], root, library)
        ce = _pick(raw["models"]["catalog"], "catalog", root, library)
        if ce is not None and _sealed_hash(ce):
            body["catalog_pack"] = _sealed_hash(ce)
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _sealed_hash(e):
    """The content hash a sealed library entry's record names, else None (a shipped entry: the document alone is what counts)."""
    if e["origin"] != "library":
        return None
    rec = pack_record(os.path.dirname(e["file"])) or {}
    return rec["sha256"] if rec.get("sealed") is not False and isinstance(rec.get("sha256"), str) else None


def verification(name, state=None):
    """The verification records of a library definition: STATE/providers/NAME/verified.json, {capability: {hash, by, at, note}}. {} when
    there is none or it cannot be read."""
    try:
        with open(os.path.join(state or _state_dir(), "providers", name, "verified.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def record_verification(name, records, state=None):
    """Write STATE/providers/NAME/verified.json: {capability: {hash, by, at, note}}, atomically, the directory 0700 and the file 0600. Only
    `provider check` (by conformance) and `provider attest` (by attest) call this; the loader trusts a record only when its hash is the
    definition's hash now. An empty map removes the file."""
    d = os.path.join(state or _state_dir(), "providers", name)
    f = os.path.join(d, "verified.json")
    if not records:
        try:
            os.unlink(f)
        except OSError:
            pass
        return f
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = "%s.tmp.%d" % (f, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(records, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, f)
    return f


def _backed(e, cell, capability, root, library, state, base=None, surface=None):
    """Is the claim of a capability cell backed? A shipped definition says so with verified_on. A library definition has a record that
    names a verifier and carries the hash of the definition as it is now; for an extension (base= the runtime it is composed onto, on
    surface) the hash is the extension's, which chains to the runtime's."""
    if e["origin"] == "shipped":
        return bool(cell.get("verified_on"))
    rec = verification(e["name"], state).get(capability)
    if not isinstance(rec, dict) or rec.get("by") not in VERIFIERS or not isinstance(rec.get("hash"), str):
        return False
    try:
        return rec["hash"] == (extension_hash(e["name"], base, surface, root, library) if base else definition_hash(e["name"], root, library))
    except ProviderError:
        return False


def cap(name, surface, capability, root=None, library=None, state=None, project=None, conf=None):
    """yes, partial, no or unverified for one capability on one surface. A yes or partial that is not verified is unverified. With a
    project, the runtime is the one the project's enabled extensions are composed onto: a capability an extension provides is backed by
    the verification of THAT extension (extension_hash), the others by the runtime's. A conflict between the packs is Conflict."""
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    if capability not in capabilities2():
        raise ProviderError("unknown capability '%s'" % capability)
    e = _entry(name, root, library)
    doc = _docs(e).get(surface)
    if doc is None:
        return "no"
    pack = name
    if project:
        comp = compose(name, surface, project, root=root, library=library, conf=conf)
        doc, pack = comp["definition"], comp["provenance"].get("capabilities." + capability, name)
    cell = _dict(doc.get("capabilities")).get(capability)
    if not isinstance(cell, dict) or cell.get("value") not in ("yes", "partial", "no"):
        return "no"
    if cell["value"] != "no":
        by = e if pack == name else _pick(pack, "extension", root, library)
        if not _backed(by, cell, capability, root, library, state, None if pack == name else name, surface):
            return "unverified"
        if capability == "read_only_barrier" and barrier_claim_problem(doc):
            return "no"                  # claimed, even attested, with nothing behind it (barrier kind none, no read-only arguments): fail closed
    return cell["value"]


def effective(name, surface, capability, root=None, library=None, state=None, project=None, conf=None):
    """What enforcement may rely on: yes, partial or no (unverified counts as no). With project=, the runtime composed with the
    project's enabled extensions (cap())."""
    v = cap(name, surface, capability, root, library, state, project, conf)
    return "no" if v == "unverified" else v


# ---- extensions: a runtime plus what the project enabled ------------------------------------------------------------------------

def project_extensions(project, conf=None):
    """models.extensions of the project's answers, sorted: the names of the extensions it enabled ([] for none, or no such project)."""
    models = (project_answers(project, conf) or {}).get("models")
    ex = models.get("extensions") if isinstance(models, dict) else None
    return sorted({x for x in ex if isinstance(x, str) and x}) if isinstance(ex, list) else []


def _extension(name, root, library):
    """(entry, document) of an extension pack. Drift when it is unsealed or changed since it was sealed; Refused when there is none."""
    e = _pick(name, "extension", root, library) if isinstance(name, str) and NAME_RE.match(name) and name not in NON_PROVIDERS else None
    if e is None:
        raise Refused("extension '%s' is enabled, but there is no such extension pack (qargi provider list); qargi provider disable PROJECT %s" % (name, name))
    raw = _read(e)
    bad = [m for lvl, m in validate_extension(raw, name) if lvl == "fail"]
    if bad:
        raise Refused("extension '%s' breaks its schema (%s); qargi provider check %s" % (name, bad[0], name))
    return e, raw


def extension_hash(ext, base, surface, root=None, library=None):
    """sha256 an extension's verification record is bound to: the extension's document and, when it is a sealed library pack, the content
    hash of the pack, chained to the hash of the runtime it is composed onto (definition_hash(base)) and the surface. Any change to the
    extension or the runtime (a reseal, a new catalog) makes its records stale. ProviderError when the runtime does not load."""
    e = _pick(ext, "extension", root, library)
    if e is None:
        raise ProviderError("no extension '%s'" % ext)
    body = {"extension": _read(e), "base": definition_hash(base, root, library), "base_name": base, "surface": surface}
    sealed = _sealed_hash(e)
    if sealed:
        body["pack"] = sealed
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def extension_backing(ext, capability, cell, base, surface, state=None):
    """What stands behind a capability an extension provides on base, for show: its date (a shipped extension), the record, or the lack of one."""
    x = _pick(ext, "extension", None, None)
    if x is not None and x["origin"] == "shipped":
        return "verified %s" % cell["verified_on"] if cell.get("verified_on") else "not verified, counts as no"
    rec = verification(ext, state).get(capability)
    if not isinstance(rec, dict):
        return "no record, counts as no"
    return "verified by %s" % rec["by"] if x is not None and _backed(x, cell, capability, None, None, state, base, surface) else "record is stale, counts as no"


def _contract_verbs():
    try:
        with open(os.path.join(PROVIDERS, "adapter-schema.json")) as f:
            return tuple(json.load(f)["verbs"])
    except (OSError, ValueError, KeyError):
        return ("resolve", "dispatch-local", "barrier-check", "provision", "start-session", "status", "collect", "stop", "cost")


def _base_provenance(doc, name):
    """{path: pack} of what the runtime itself has, that an extension may not take: a claimed capability (a cell that says no is a
    runtime saying it does not have it, so an extension may provide it), a resource, a renderer, a dispatch variant, a barrier, an
    adapter verb (the verbs it names, else every verb of the adapter contract)."""
    prov = {}
    for c, cl in _dict(doc.get("capabilities")).items():
        if isinstance(cl, dict) and cl.get("value") in ("yes", "partial"):
            prov["capabilities." + c] = name
    for r, v in _dict(doc.get("resources")).items():
        if v is not None:
            prov["resources." + r] = name
    for r in _dict(doc.get("renderers")):
        prov["renderers." + r] = name
    disp = doc.get("dispatch") if isinstance(doc.get("dispatch"), dict) else {}
    for v in _dict(disp.get("variants")):
        prov["dispatch.variants." + v] = name
    bar = doc.get("barrier")
    if isinstance(bar, dict) and bar.get("kind") not in (None, "none"):
        prov["barrier"] = name
    if isinstance(doc.get("adapter"), str) and doc["adapter"]:
        verbs = doc.get("adapter_verbs")
        for v in (verbs if isinstance(verbs, list) else _contract_verbs()):
            prov["adapter_verbs." + str(v)] = name
    return prov


def _version_tuple(v):
    return tuple(int(x) for x in v.split("."))


def _qargi_version():
    try:
        with open(os.path.join(TOOL, "VERSION")) as f:
            return f.read().split()[0]
    except (OSError, IndexError):
        return None


def _applies(doc, name, surface, base, root=None, library=None):
    """(True, "") when the extension is for this runtime on this surface, else (False, why). It extends a runtime by name or a family; it
    applies on one surface: its surface, else the only surface of the runtime it names (a family needs surface)."""
    ex = doc["extends"]
    if ex != name and ex != base.get("family"):
        return False, "extends %s, not %s" % (ex, name)
    s = doc.get("surface")
    if s is None:
        if ex != name:
            return False, "extends the family %s and names no surface, so it applies to no runtime; add \"surface\"" % ex
        served = surfaces_of(name, root, library)
        if len(served) != 1:
            return False, "extends %s, which serves %s, and names no surface; add \"surface\"" % (name, " and ".join(served))
        s = served[0]
    if s != surface:
        return False, "extends %s on %s, not %s" % (ex, s, surface)
    return True, ""


def _unmet(doc, name, surface, base, root, library, state):
    """Why the extension's requires do not hold on the runtime alone, or None."""
    rq = doc.get("requires") if isinstance(doc.get("requires"), dict) else {}
    for r in rq.get("resources") or []:
        if _dict(base.get("resources")).get(r) is None:
            return "needs the %s resource, which %s does not have" % (r, name)
    for c in rq.get("capabilities") or []:
        if effective(name, surface, c, root, library, state) == "no":
            return "needs %s, which %s does not have verified" % (c, name)
    q = rq.get("qargi")
    if isinstance(q, str):
        have = _qargi_version()
        try:
            if have is None or _version_tuple(have) < _version_tuple(q[2:]):
                return "needs qargi %s (this is %s)" % (q, have or "of unknown version")
        except ValueError:
            return "needs qargi %s (this is %s)" % (q, have or "of unknown version")
    return None


def _claim(prov, path, pack, name):
    if path in prov:
        if prov[path] == name:
            raise Conflict("extension %s adds %s, which the runtime %s already has; an extension never overrides (qargi provider disable PROJECT %s)" % (pack, path, name, pack))
        raise Conflict("extensions %s and %s both add %s; neither overrides the other (qargi provider disable PROJECT one of them)" % (prov[path], pack, path))
    prov[path] = pack


def _merge(out, x, doc, prov, name):
    """Add what extension x provides to the composition (out), claiming every key in prov first. Conflict leaves out half-built: the
    caller drops it."""
    d, adds = out["definition"], doc["adds"]
    for c, cl in sorted(_dict(adds.get("capabilities")).items()):
        _claim(prov, "capabilities." + c, x, name)
        d.setdefault("capabilities", {})
        d["capabilities"] = dict(_dict(d["capabilities"]), **{c: copy.deepcopy(cl)})
    for r, v in sorted(_dict(adds.get("resources")).items()):
        _claim(prov, "resources." + r, x, name)
        d["resources"] = dict(_dict(d.get("resources")), **{r: copy.deepcopy(v)})
    for r, v in sorted(_dict(adds.get("renderers")).items()):
        _claim(prov, "renderers." + r, x, name)
        d["renderers"] = dict(_dict(d.get("renderers")), **{r: copy.deepcopy(v)})
    variants = _dict(_dict(adds.get("dispatch")).get("variants"))
    if variants and not isinstance(d.get("dispatch"), dict):
        raise Refused("extension %s adds dispatch variants, but the runtime %s has no dispatch" % (x, name))
    for v, val in sorted(variants.items()):
        _claim(prov, "dispatch.variants." + v, x, name)
        d["dispatch"] = dict(d["dispatch"], variants=dict(_dict(d["dispatch"].get("variants")), **{v: copy.deepcopy(val)}))
    if isinstance(adds.get("barrier"), dict):
        _claim(prov, "barrier", x, name)
        d["barrier"] = copy.deepcopy(adds["barrier"])
    for v, path in sorted(_dict(adds.get("adapter_verbs")).items()):
        _claim(prov, "adapter_verbs." + v, x, name)
        out["definition"].setdefault("extension_verbs", {})[v] = {"pack": x, "path": path}


def compose(name, surface, project=None, extensions=None, root=None, library=None, conf=None):
    """The effective definition of a runtime on one surface: the definition plus the extensions the project enabled (models.extensions),
    merged in name order. {definition: the merged schema 2 definition (a copy; extension_verbs: {VERB: {pack, path}} is added),
    provenance: {path: pack} for what the runtime and the extensions provide (capabilities.CAP, resources.NAME, renderers.NAME,
    dispatch.variants.NAME, barrier, adapter_verbs.VERB), extensions: [the ones merged], ignored: [{extension, why}]}.
    Without a project (and without extensions=[...], used by check to compose one extension alone) it is the definition. An extension
    that is for another runtime or surface, or whose requires do not hold, is ignored with its reason; the project must run the runtime
    on that surface for any to apply. Two packs adding the same key, or an extension adding what the runtime has, is Conflict (a Refused):
    nothing is overridden. An enabled extension that is missing is Refused, one that is unsealed or changed is Drift."""
    base = definition(name, surface, root, library)
    out = {"definition": copy.deepcopy(base), "provenance": _base_provenance(base, name), "extensions": [], "ignored": [], "runtime": name, "surface": surface}
    if extensions is None:
        extensions = project_extensions(project, conf) if project else []
        bound = None
        if extensions:
            try:
                bound = resolve_project(project_answers(project, conf) or {}, surface, project, root, library)[0]
            except ProviderError:
                bound = None
        if bound != name:
            out["ignored"] = [{"extension": x, "why": "project %s does not run %s on %s" % (project, name, surface)} for x in extensions]
            extensions = []
    prov = out["provenance"]
    for x in sorted(set(extensions)):
        e, doc = _extension(x, root, library)
        ok, why = _applies(doc, name, surface, base, root, library)
        if ok:
            why = _unmet(doc, name, surface, base, root, library, None)
            ok = why is None
        if not ok:
            out["ignored"].append({"extension": x, "why": why})
            continue
        _merge(out, x, doc, prov, name)
        out["extensions"].append(x)
    return out


def extension_base(ext, project=None, root=None, library=None, conf=None):
    """(runtime, surface) an extension is composed onto: with a project, the runtime the project runs on the extension's surface; without,
    the runtime it names (a family or a runtime on several surfaces needs a project). Refused, saying why, when it applies to none."""
    e, doc = _extension(ext, root, library)
    ex, s = doc["extends"], doc.get("surface")
    if project:
        answers = project_answers(project, conf) or {}
        why = []
        for sf in ([s] if s else SURFACES):
            try:
                rt = resolve_project(answers, sf, project, root, library)[0]
                base = definition(rt, sf, root, library)
            except ProviderError:
                continue
            ok, w = _applies(doc, rt, sf, base, root, library)
            if ok:
                return rt, sf
            why.append("%s runs %s on %s: %s" % (project, rt, sf, w))
        raise Refused("extension '%s' applies to nothing in project %s%s" % (ext, project, " (" + "; ".join(why) + ")" if why else ""))
    try:
        base = definition(ex, s, root, library)
    except ProviderError as err:
        raise Refused("extension '%s' extends %s, which is not a runtime of one surface (%s); pass --project NAME to say which runtime to check it on" % (ext, ex, err))
    sf = s or base["surface"]
    ok, w = _applies(doc, ex, sf, base, root, library)
    if not ok:
        raise Refused("extension '%s' %s" % (ext, w))
    return ex, sf


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


def _layout_from(doc):
    """The layout fields of a definition, from its resources and session. Home is not expanded. An exclusion that is not a settings key
    with one pointer segment is None here."""
    res = _dict(doc.get("resources"))
    sk, ag, st, mem = (_dict(res.get(k)) for k in ("skills", "agents", "settings", "memory"))
    ses = _dict(doc.get("session"))
    ex = _dict(sk.get("exclusion"))
    exclusion = None
    if ex.get("form") == "settings-key" and isinstance(ex.get("pointer"), str) and ex["pointer"].count("/") == 1 and isinstance(ex.get("off"), str):
        exclusion = {"file_key": ex["pointer"][1:], "off_value": ex["off"]}
    files = [{"scope": f["scope"], "path": f["path"]} for f in st.get("files") or [] if isinstance(f, dict) and "scope" in f and "path" in f]
    return {"project_skills_dir": sk.get("project_dir"), "user_skills_dir": sk.get("user_dir"),
            "project_agents_dir": ag.get("project_dir"), "user_agents_dir": ag.get("user_dir"),
            "settings_files": files or None, "exclusion": exclusion, "memory_dir": mem.get("user_dir"), "checkout_key": mem.get("checkout_key"),
            "render_target": ses.get("render_target"), "session_launch": ses.get("launch")}


def layout(name, root=None, home=None, library=None, project=None, conf=None):
    """The layout of a provider: every field of LAYOUT_FIELDS (None where the definition has none, or has no resources at all). It is
    read from the resources and the session. A leading ~ is expanded here with home (default:
    $HOME), so the definition stays portable. Project paths stay relative to the checkout. With a project, the resources are those of the
    runtime composed with the project's enabled extensions (a resource an extension adds is there; the runtime's own are unchanged).
    Resources that break the schema are a ProviderError."""
    e = _entry(name, root, library)
    docs = _docs(e)
    bad = [m for lvl, m in validate2(_read(e), name) if lvl == "fail" and m.startswith("resources")]
    if bad:
        raise ProviderError("provider '%s' has a bad layout: %s" % (name, bad[0]))
    doc = docs.get("local") or next(iter(docs.values()), {})
    if project and doc:
        doc = compose(name, doc["surface"], project, root=root, library=library, conf=conf)["definition"]
    out = _layout_from(doc)
    home = home or os.path.expanduser("~")
    for k in _HOME_FIELDS:
        out[k] = _home(out[k], home)
    if out["settings_files"] is not None:
        out["settings_files"] = [{"scope": f["scope"], "path": _home(f["path"], home)} for f in out["settings_files"]]
    if out["exclusion"] is not None:
        out["exclusion"] = dict(out["exclusion"])
    return out


def require(name, field, would, root=None, home=None, library=None, project=None, conf=None):
    """The layout field, or Unsupported: provider NAME has no FACILITY: WOULD (what the verb would have done with it)."""
    if field not in LAYOUT_FIELDS:
        raise ProviderError("unknown layout field '%s'" % field)
    v = layout(name, root, home, library, project, conf)[field]
    if v is None or v == []:
        raise Unsupported("provider %s has no %s: %s" % (name, FACILITY[field], would))
    return v


def require_skills(name, would, root=None, library=None, project=None, conf=None):
    """Unsupported unless the provider's skills capability is yes or partial (with a verification date) on the local surface,
    where a session loads skills from the directories of the layout. With a project, a skills capability an enabled extension provides
    and has verified counts."""
    if effective(name, "local", "skills", root, library, project=project, conf=conf) == "no":
        raise Unsupported("provider %s has no skills support on the local surface: %s" % (name, would))


def _provider_answer(answers):
    """models.provider of the answers: a non-empty string (stripped), a dict {local, cloud}, or None for anything else."""
    models = answers.get("models") if isinstance(answers, dict) else None
    p = models.get("provider") if isinstance(models, dict) else None
    if isinstance(p, str) and p.strip():
        return p.strip()
    return p if isinstance(p, dict) else None


def _no_provider(project, surface=None):
    project = project or "PROJECT"
    if surface is None:
        return NoProvider("project %s has no provider: set one with qargi project set %s models.provider NAME" % (project, project))
    return NoProvider("project %s has no %s provider: set one with qargi project set %s models.provider.%s NAME" % (project, surface, project, surface))


def project_provider(answers, project, surface=None, root=None, library=None):
    """The provider of a project: models.provider of its stored answers. There is no default: absent or empty is NoProvider (exit
    2). A name with no descriptor is refused later, by load(), like any unknown provider. A string is returned as it is, unresolved
    (the earlier behaviour); an object {local, cloud} is returned only when it names one thing for both surfaces, else the verb must
    say which surface it means (provider_of) and Refused is raised. With a surface this is provider_of()."""
    if surface is not None:
        return provider_of(answers, surface, project, root, library)
    p = _provider_answer(answers)
    if isinstance(p, str):
        return p
    if isinstance(p, dict):
        values = {v.strip() for v in p.values() if isinstance(v, str) and v.strip()}
        if len(values) == 1 and all(isinstance(p.get(s), str) and p[s].strip() for s in SURFACES):
            return values.pop()
        raise Refused("project %s names a runtime per surface (models.provider is %s); this verb has to ask for one surface: "
                      "qargi provider of %s --surface local|cloud" % (project or "PROJECT", json.dumps(p, sort_keys=True), project or "PROJECT"))
    raise _no_provider(project)


def resolve_project(answers, surface, project=None, root=None, library=None):
    """(runtime, notice) for one surface of a project: models.provider is a name (runtime or family, for every surface) or an object
    {local, cloud}. A surface the answers leave unset is NoProvider (exit 2); there is no default. The notice is None, or says that a
    single name was resolved through its family and what to set instead."""
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    p = _provider_answer(answers)
    if p is None:
        raise _no_provider(project)
    if isinstance(p, dict):
        for k in p:
            if k not in SURFACES:
                raise Refused("models.provider: unknown surface '%s'; one of %s" % (k, ", ".join(SURFACES)))
        name = p.get(surface)
        if not isinstance(name, str) or not name.strip():
            raise _no_provider(project, surface)
        return _resolve(name.strip(), surface, root, library)[0], None
    try:
        runtime, by_family = _resolve(p, surface, root, library)
    except NotServed as e:
        raise NoProvider("project %s has no %s provider: its provider '%s' does not serve that surface; set one with qargi project set %s "
                         "models.provider.%s NAME" % (project or "PROJECT", surface, p, project or "PROJECT", surface)) from e
    notice = None
    if by_family:
        notice = ("models.provider is the single name '%s'; on the %s surface it resolves to %s through the family. Name a runtime for each "
                  "surface: qargi project set %s models.provider.%s %s" % (p, surface, runtime, project or "PROJECT", surface, runtime))
    return runtime, notice


def provider_of(answers, surface=None, project=None, root=None, library=None):
    """The runtime a project uses on one surface (resolve_project() without the notice). The earlier call provider_of(PROJECT, conf) is
    provider_of_project()."""
    if isinstance(answers, str):
        return provider_of_project(answers, surface)
    if surface is None:
        raise ProviderError("provider_of needs a surface (one of %s)" % ", ".join(SURFACES))
    return resolve_project(answers, surface, project, root, library)[0]


def provider_of_project(project, conf=None, surface=None, root=None, library=None):
    """The provider of a stored project. A project with no stored answers is NoProvider too (exit 2), but says so: "no such project 'X'"
    is not "project X has no provider", whose fix (qargi project set) would fail for a name that is not a project. No project at all (a
    verb given none, and none inferred from the checkout) is a refusal that says what to pass. With a surface the name is resolved for
    it (provider_of); without, project_provider() answers."""
    return project_provider(_stored_answers(project, conf), project, surface, root, library)


def _stored_answers(project, conf=None):
    """The stored answers of a project, or NoProvider saying why there are none."""
    if not project:
        raise NoProvider("no project given, so no provider: a provider belongs to a project; pass --project NAME (or run from a project checkout)")
    if not NAME_RE.match(project) or not os.path.lexists(os.path.join(conf or _conf(), "projects", project + ".json")):
        raise NoProvider("no such project '%s'" % project)
    answers = project_answers(project, conf)
    if answers is None:
        raise NoProvider("cannot read the stored answers of project '%s' (qargi project show %s)" % (project, project))
    return answers


def _runtime_docs(e):
    try:
        return _docs(e)
    except ProviderError:
        return {}


def resolve_runtime(name, surface, root=None, library=None):
    """The runtime a name stands for on a surface: (1) a runtime of that name that serves the surface; (2) a family name matching exactly
    ONE runtime (shipped or library) of the surface; (3) otherwise Refused, saying what is available. Naming is explicit; nothing here
    picks a default."""
    return _resolve(name, surface, root, library)[0]


def _resolve(name, surface, root, library):
    """(runtime, True when the name was a family)."""
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise Refused("'%s' is not a provider or family name" % name)
    own = _pick(name, "provider", root, library)
    served = list(_runtime_docs(own)) if own else []
    if own and surface in served:
        return name, False
    found = _scan(root, library)
    candidates, runtimes, families = [], set(), set()
    for n, es in sorted(found.items()):
        provs = [e for e in es if _kind(e) == "provider"]
        docs = [d for e in provs for d in [_runtime_docs(e).get(surface)] if d is not None]
        if not docs:
            continue
        if len({e["origin"] for e in es}) > 1:                         # defined twice: it matters only if it could be this family
            if any(d.get("family") == name for d in docs):
                raise Clash("'%s' is defined twice (shipped and library); qargi provider remove %s, or rename it" % (n, n))
            continue
        runtimes.add(n)
        families.add(docs[0].get("family"))
        if docs[0].get("family") == name:
            candidates.append(n)
    if len(candidates) == 1:
        return candidates[0], True
    if len(candidates) > 1:
        raise Ambiguous("the family '%s' has more than one runtime on the %s surface (%s); name one of them" % (name, surface, ", ".join(candidates)))
    if own:
        raise NotServed("the provider %s does not serve the %s surface (it serves %s)" % (name, surface, ", ".join(served) or "none"))
    available = sorted(runtimes | {f for f in families if f})
    raise Refused("no runtime or family '%s' for the %s surface; available: %s" % (name, surface, ", ".join(available) or "none"))


def skills_dirs(name=None, root=None, library=None):
    """The project skills directories, relative to a checkout: NAME's (none when it has none), or the distinct ones of every provider
    that has one and supports skills on the local surface. For a hint about a repository whose project names no provider yet."""
    out = []
    for n in ([name] if name else names(root, library)):
        try:
            require_skills(n, "list the skills directory", root, library)
            d = layout(n, root, library=library)["project_skills_dir"]
        except ProviderError:
            continue
        if d and d not in out:
            out.append(d)
    return out


def checkout_key(rule, path):
    """The key of a checkout under a rule of the definition: nonalnum-dash replaces every non-alphanumeric character of the absolute
    path by -; sha256-16 is the first 16 hex digits of the sha256 of that path; none is the empty string."""
    if rule == "nonalnum-dash":
        return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(path))
    if rule == "sha256-16":
        return hashlib.sha256(os.path.abspath(path).encode("utf-8")).hexdigest()[:16]
    if rule == "none":
        return ""
    raise ProviderError("unknown checkout key rule '%s'" % rule)


def memory_dir(name, checkout, root=None, home=None, library=None, project=None, conf=None):
    """The provider's own memory directory for a checkout, or Unsupported."""
    tpl = require(name, "memory_dir", "locate the provider's own memory notes for a checkout", root, home, library, project, conf)
    if "{checkout_key}" in tpl:
        tpl = tpl.replace("{checkout_key}", checkout_key(require(name, "checkout_key", "name the provider's memory directory of a checkout", root, home, library, project, conf), checkout))
    return tpl


def launch_line(name, render, root=None, library=None, project=None, conf=None):
    """The command that starts a session on the render directory, or Unsupported. A [...] group of the template stays only when
    the file named by its last word exists once {render} is filled in."""
    tpl = require(name, "session_launch", "print the command that starts a session on the render", root, library=library, project=project, conf=conf).replace("{render}", render)

    def group(m):
        words = m.group(1).split()
        return m.group(1) if words and os.path.isfile(words[-1]) else ""
    return re.sub(r"\[([^\]]*)\]", group, tpl)


# ---- the read-only barrier ----------------------------------------------------------------------------------------------

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


def require_barrier(provider, surface, project=None, root=None, conf=None, library=None):
    """May a read-only role run on this surface of the provider? (state, text): state is yes, partial (text is the note),
    accepted (the project recorded that it accepts no barrier here) or refused (text says why and names the command). The barrier
    is the runtime's composed with the project's enabled extensions (a barrier an extension provides counts once it is verified)."""
    v = effective(provider, surface, "read_only_barrier", root, library, project=project, conf=conf)
    if v == "yes":
        return "yes", ""
    entry = _entry(provider, root, library)
    doc = _docs(entry).get(surface)
    comp = None
    if doc is not None and project:
        comp = compose(provider, surface, project, root=root, library=library, conf=conf)
        doc = comp["definition"]
    cell = _dict(_dict(doc and doc.get("capabilities")).get("read_only_barrier"))
    if v == "partial":
        return "partial", "%s has only a partial read-only barrier on %s: %s" % (provider, surface, cell.get("note") or "see qargi provider show %s" % provider)
    if accepted(project, surface, conf):
        return "accepted", ""
    by = (comp["provenance"] if comp else {}).get("capabilities.read_only_barrier")
    claim = barrier_claim_problem(doc, by=by if by != provider else None) if doc is not None else None
    why = claim or ("not supported" if cell.get("value") == "no" or doc is None else "not verified, so it counts as not supported")
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


def cmd_effective(provider, surface, capability, project=None):
    if surface not in SURFACES:
        raise ProviderError("unknown surface '%s'; one of %s" % (surface, ", ".join(SURFACES)))
    if surface not in surfaces_of(provider):
        raise ProviderError("the provider %s does not list the surface %s" % (provider, surface))
    print(effective(provider, surface, capability, project=project))
    return 0


# ---- the verbs --------------------------------------------------------------------------------------------------------

def _count(n, word):
    return "%d %s%s" % (n, word, "" if n == 1 else "s")


def _state(findings):
    f = sum(1 for lvl, _ in findings if lvl == "fail")
    w = sum(1 for lvl, _ in findings if lvl == "warn")
    return _count(f, "failure") if f else (_count(w, "warning") if w else "clean")


def findings_of(name, root=None, library=None):
    """(entry, document, findings) for one provider: the validation of its file and of what it points at (its catalog), plus why it
    cannot be read as a definition at all (a file that is not schema 2, a directory that disagrees with the name)."""
    e = _entry(name, root, library)
    raw = _read(e)
    findings = validate2(raw, name)
    if raw.get("kind") == "provider" and barrier_claim_problem(raw):
        findings.append(("fail", barrier_claim_problem(raw)))
    if raw.get("kind") == "provider" and isinstance(raw.get("models"), dict) and "catalog" in raw["models"]:
        try:
            catalog(raw["models"]["catalog"], root, library)
        except Clash:
            raise
        except ProviderError as ex:
            findings.append(("fail", "models.catalog: %s" % ex))
    try:
        _docs(e)
    except ProviderError as ex:
        findings.append(("fail", str(ex)))
    if raw.get("kind") == "provider":
        findings += [("fail", m) for m in addenda_problems(raw, e["dir"])]
    return e, raw, findings


def _library_module():
    """lib/conformance/library.py (the lifecycle of library packs), or None when this file is run without its neighbours."""
    sys.path.insert(0, HERE)
    sys.modules.setdefault("provider", sys.modules[__name__])      # the module the library imports is this one, also when this file is the script
    try:
        from conformance import library
    except ImportError:
        return None
    return library


def cmd_list():
    for n in names():
        try:
            e, raw, findings = findings_of(n)
        except ProviderError as ex:
            print("%-12s %-12s %s" % (n, "-", "1 failure (%s)" % ex))
            continue
        surfaces = [raw["surface"]] if raw.get("surface") in SURFACES else []
        sealed = seal_state(e)[0]
        note = "  (library%s)" % (", unsealed" if sealed == "unsealed" else ", changed since sealed" if sealed == "drift" else ", not sealed: no record" if sealed == "unrecorded" else "") if e["origin"] == "library" else ""
        print("%-12s %-12s %s%s" % (n, ",".join(surfaces) or "-", _state(findings), note))
    lib = _library_module()
    if lib:
        lib.list_other_kinds()
    return 0


def _verified(cell):
    return "verified %s" % cell["verified_on"] if cell.get("verified_on") else "not verified" + (", counts as no" if cell.get("value") != "no" else "")


def _backing(name, surface, c, cell):
    """What stands behind a claimed capability, for show: a shipped definition, its date; a library one, the record or the lack of one."""
    if cell.get("value") == "no":
        return "-"
    if origin(name) == "shipped":
        return "verified %s" % cell["verified_on"] if cell.get("verified_on") else "not verified, counts as no"
    rec = verification(name).get(c)
    if cap(name, surface, c) == "unverified":
        return "no record, counts as no" if not isinstance(rec, dict) else "record is stale, counts as no"
    return "verified by %s" % rec["by"]


def _backing_comp(name, surface, c, cell, comp, project):
    """_backing() for a composed capability: the runtime's own as before, an extension's by the record of THAT extension."""
    pack = comp["provenance"].get("capabilities." + c, name)
    if pack == name:
        return _backing(name, surface, c, cell)
    if cell.get("value") == "no":
        return "-"
    return extension_backing(pack, c, cell, name, surface)


def _print_extensions(comp, project):
    print("extensions of project %s" % project)
    for x in comp["extensions"]:
        prov = sorted(k for k, v in comp["provenance"].items() if v == x)
        print("  %-14s applied (adds %s)" % (x, ", ".join(prov) or "nothing"))
    for i in comp["ignored"]:
        print("  %-14s ignored: %s" % (i["extension"], i["why"]))
    if not comp["extensions"] and not comp["ignored"]:
        print("  none enabled")


def _show2(name, e, doc, project=None):
    s = doc["surface"]
    comp = compose(name, s, project) if project else None
    if comp:
        doc = comp["definition"]
    m = _resolve_models(doc)
    print("%s  (%s, %s%s)" % (name, s, e["origin"], "; family %s" % doc["family"] if doc.get("family") else ""))
    if doc.get("description"):
        print(doc["description"])
    if m["catalog"]:
        print("models: catalog %s (%s), passes the %s" % (m["catalog"], catalog(m["catalog"])["version"], m["use"]))
    elif len({json.dumps(r, sort_keys=True) for r in m["tiers"].values()}) == 1:
        print("models: single model %s for every tier" % m["tiers"]["fast"]["model"])
    print("model pattern: %s" % m["pattern"])
    print("tiers")
    for t in TIERS:
        r = m["tiers"][t]
        print("  %-9s %-22s alias %-8s %s" % (t, r["model"], r["alias"] or "-", "verified %s" % r["verified_on"] if r.get("verified_on") else "verified: no"))
    print("effort")
    if all(v is None for v in m["effort"].values()):
        print("  no control")
    else:
        for k, v in m["effort"].items():
            print("  %-7s %s" % (k, v if v is not None else "- (no control)"))
    print("capabilities" + (" (composed for project %s; [pack] provided it)" % project if comp and (comp["extensions"] or comp["ignored"]) else ""))
    for c in capabilities2():
        cl = _dict(doc.get("capabilities")).get(c)
        if isinstance(cl, dict) and comp and (comp["extensions"] or comp["ignored"]):
            print("  %-34s %-8s %-30s %-12s %s" % (c, cl.get("value"), _backing_comp(name, s, c, cl, comp, project), "[%s]" % comp["provenance"].get("capabilities." + c, name), cl.get("note", "")))
        elif isinstance(cl, dict):
            print("  %-34s %-8s %-30s %s" % (c, cl.get("value"), _backing(name, s, c, cl), cl.get("note", "")))
    if comp and (comp["extensions"] or comp["ignored"]):
        _print_extensions(comp, project)
    return 0


def cmd_show(name, as_json, project=None):
    e, d, findings = findings_of(name)
    if any(lvl == "fail" for lvl, _ in findings):
        print("qargi: provider '%s' breaks the schema (qargi provider check %s)" % (name, name), file=sys.stderr)
        return 1
    if as_json and project:
        print(json.dumps(dict(compose(name, d["surface"], project), project=project), indent=2))
        return 0
    if as_json:
        print(json.dumps(d, indent=2))
        return 0
    return _show2(name, e, next(iter(_docs(e).values())), project)


def adapter_problem(d, directory):
    """None when the definition has no adapter or the adapter file exists and is executable, else what is wrong. The adapter is a path
    relative to directory, the definition's directory."""
    ad = d.get("adapter")
    if not isinstance(ad, str) or os.path.isabs(ad) or ".." in ad.split("/"):
        return None                               # no adapter, or a path validate2() already refused
    path = os.path.join(directory, ad)
    if not os.path.isfile(path):
        return "adapter: %s does not exist" % ad
    if not os.access(path, os.X_OK):
        return "adapter: %s is not executable" % ad
    return None


ADDENDUM_MAX = 16384
# a character no contract text may hold: a control (but tab and newline), any format character (Cf: tags U+E0000-E007F, zero-width, bidi, the
# byte order mark, the soft hyphen), a private-use, surrogate or unassigned code point, and the line and paragraph separators
_ADDENDUM_BAD_CATEGORIES = frozenset(("Cc", "Cf", "Co", "Cs", "Cn", "Zl", "Zp"))


def _addendum_has_bad_character(text):
    return any(unicodedata.category(ch) in _ADDENDUM_BAD_CATEGORIES for ch in text if ch not in "\t\n")


def _read_addendum(directory, rel):
    """The text of the contract addendum rel in directory, or ProviderError saying why not: it must be a file that stays inside the directory
    (a link that points out of it is refused), UTF-8 text with no control, format (tag, zero-width, bidi, byte order mark), private-use or unassigned character but tab and newline, and at most ADDENDUM_MAX bytes."""
    path = os.path.join(directory, rel)
    if not os.path.lexists(path):
        raise ProviderError("contract_addenda: %s does not exist" % rel)
    real, base = os.path.realpath(path), os.path.realpath(directory)
    if not real.startswith(base + os.sep):
        raise ProviderError("contract_addenda: %s leaves the definition's directory" % rel)
    if not os.path.isfile(real):
        raise ProviderError("contract_addenda: %s is not a file" % rel)
    try:
        with open(real, "rb") as f:
            raw = f.read(ADDENDUM_MAX + 1)
    except OSError as ex:
        raise ProviderError("contract_addenda: %s cannot be read (%s)" % (rel, ex.strerror)) from ex
    if len(raw) > ADDENDUM_MAX:
        raise ProviderError("contract_addenda: %s is longer than %d bytes" % (rel, ADDENDUM_MAX))
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = None
    if text is None or _addendum_has_bad_character(text):
        raise ProviderError("contract_addenda: %s is not text (UTF-8 with no control, format, private-use or unassigned characters)" % rel)
    return text


def _addenda_names(doc):
    """The names doc lists under resources.contract_addenda; ProviderError for a list that is not what the schema says."""
    res = doc.get("resources") if isinstance(doc.get("resources"), dict) else {}
    names = res.get("contract_addenda")
    if names is None:
        return []
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names) or len(set(names)) != len(names):
        raise ProviderError("resources.contract_addenda: an array of distinct file names")
    for i, n in enumerate(names):
        if not _plain_relative(n):
            raise ProviderError("resources.contract_addenda[%d]: '%s' is not a file inside the definition's directory" % (i, n))
    return names


def addenda_problems(doc, directory):
    """[message] for the contract addenda of a definition document that cannot be used from directory (the definition's own): none for a
    definition that lists none. The same refusals as contract_addenda(), for `provider check` and the review of a pack."""
    try:
        names = _addenda_names(doc)
    except ProviderError:
        return []                                  # the shape is validate2()'s to report
    bad = []
    for n in names:
        try:
            _read_addendum(directory, n)
        except ProviderError as ex:
            bad.append(str(ex))
    return bad


def contract_addenda(name, surface, root=None, library=None):
    """The texts that the definition of a runtime adds to the member contract, in the order it lists them (resources.contract_addenda), []
    when it lists none. A cloud agent's prompt carries them after the contract; they are the runtime's own rules about its surface, so the
    neutral contract never names it. ProviderError when the runtime does not serve the surface, a file is missing, is not plain text or leaves
    the definition's directory; for a library pack Drift when it is not what was sealed (also when it changed while it was read)."""
    e = _entry(name, root, library)
    doc = _docs(e).get(surface)
    if doc is None:
        raise ProviderError("the provider %s does not list the surface %s" % (name, surface))
    texts = [_read_addendum(e["dir"], n) for n in _addenda_names(doc)]
    if texts and e["origin"] == "library":
        state, why = seal_state(e)
        if state != "sealed":
            raise Drift("pack '%s' %s while it was read; its contract addenda are not used" % (name, why or state))
    return texts


def cmd_addenda(args):
    """addenda NAME SURFACE: the contract addenda of a runtime, as they are added to the contract, to standard output (nothing when it has none)."""
    if len(args) != 2 or args[1] not in SURFACES:
        print("usage: qargi provider addenda NAME local|cloud", file=sys.stderr)
        return 2
    sys.stdout.write("".join(contract_addenda(args[0], args[1])))
    return 0


def adapter_exec(name, surface, verb, root=None, library=None):
    """(path, cleanup) of the adapter of a runtime on a surface, ready to run for VERB. A shipped adapter is the file in the tool; a library
    pack's is run only as a private copy of the sealed pack (exec_copy: the content and the executable's hash are checked against the
    record), and cleanup is the directory discard_exec_copy() removes afterwards (None for a shipped one). Unsupported when the runtime has
    no adapter on that surface or its adapter_verbs do not list VERB;
    Drift or Refused when a library pack is not sealed or does not approve its adapter."""
    e = _entry(name, root, library)
    doc = _docs(e).get(surface)
    if doc is None:
        raise ProviderError("the provider %s does not list the surface %s" % (name, surface))
    ad = doc.get("adapter")
    if not isinstance(ad, str) or not ad:
        raise Unsupported("provider %s has no adapter on the %s surface: it cannot %s" % (name, surface, verb))
    verbs = doc.get("adapter_verbs")
    if isinstance(verbs, list) and verb not in verbs:
        raise Unsupported("the adapter of provider %s does not serve %s" % (name, verb))
    if os.path.isabs(ad) or os.path.normpath(ad) != ad or ad.startswith(".."):
        raise ProviderError("the adapter of provider %s, '%s', is not a path inside the definition's directory" % (name, ad))
    if e["origin"] == "library":
        directory, path = exec_copy(name, ad, root, library)
        return path, directory
    path = os.path.join(e["dir"], ad)
    if not os.path.isfile(path) or not os.access(path, os.X_OK) or not os.path.realpath(path).startswith(os.path.realpath(e["dir"]) + os.sep):
        raise Unsupported("the adapter of provider %s, %s, is missing or not an executable inside the tool" % (name, ad))
    return path, None


def run_adapter(name, surface, verb, data, root=None, library=None, env=None):
    """(exit status, stdout, stderr) of the adapter's VERB with the request `data` (text) on its standard input; the private copy of a
    library adapter is removed afterwards. The errors of adapter_exec() are raised."""
    import subprocess
    path, cleanup = adapter_exec(name, surface, verb, root, library)
    try:
        r = subprocess.run([path, verb], input=data, capture_output=True, text=True, env=env)
        return r.returncode, r.stdout, r.stderr
    finally:
        if cleanup:
            discard_exec_copy(cleanup)


def cmd_adapter(args):
    """adapter-run NAME SURFACE VERB [--check]: the request on standard input goes to the adapter's VERB, its answer to standard output
    and its error output to standard error; the exit status is the adapter's. --check only says whether it could run (exit 3 and
    why when it could not), and runs nothing."""
    check = "--check" in args
    pos = [a for a in args if a != "--check"]
    if len(pos) != 3 or pos[1] not in SURFACES:
        print("usage: qargi provider adapter-run NAME local|cloud VERB [--check]", file=sys.stderr)
        return 2
    name, surface, verb = pos
    if check:
        path, cleanup = adapter_exec(name, surface, verb)
        if cleanup:
            discard_exec_copy(cleanup)
        return 0
    data = sys.stdin.read()
    rc, out, err = run_adapter(name, surface, verb, data)
    sys.stdout.write(out)
    sys.stderr.write(err)
    return rc


def cmd_model(args):
    """model NAME SURFACE TIER: the model id of a tier of the runtime on a surface."""
    if len(args) != 3 or args[1] not in SURFACES or args[2] not in TIERS:
        print("usage: qargi provider model NAME local|cloud %s" % "|".join(TIERS), file=sys.stderr)
        return 2
    print(models_of(args[0], args[1])["tiers"][args[2]]["model"])
    return 0


def _project_in_effect():
    """The project in effect (QARGI_PROJECT, else the one whose repository holds the current directory), or None: lib/help.py's rule."""
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    try:
        import help as H
        return H.infer_project()
    except Exception:
        return None


def notes_of(project, conf=None, root=None, library=None):
    """(runtime, {topic: text}) of a project: the notes of the definition of its local runtime, as composed with the extensions the project
    enabled. NoProvider (exit 2) when the project does not exist or names no provider for the local surface; there is no default."""
    runtime, _ = resolve_project(_stored_answers(project, conf), "local", project, root, library)
    doc = composed(runtime, "local", project, root, library, conf)
    notes = doc.get("notes")
    return runtime, notes if isinstance(notes, dict) else {}


def cmd_notes(args):
    """notes [TOPIC] [--project P]: the text of a notes topic of the project's local runtime, or the topic names when none is given. Exit 1
    when the runtime has no such topic (the message names both and lists the topics there are)."""
    topics, project, i = [], None, 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args) and project is None:
            project, i = args[i + 1], i + 2
        elif args[i].startswith("--"):
            topics = [None, None]
            break
        else:
            topics.append(args[i])
            i += 1
    if len(topics) > 1:
        print("usage: qargi provider notes [TOPIC] [--project P]", file=sys.stderr)
        return 2
    runtime, notes = notes_of(project or _project_in_effect())
    if not topics:
        if not notes:
            print("qargi: the runtime %s has no notes" % runtime, file=sys.stderr)
            return 1
        print("\n".join(sorted(notes)))
        return 0
    if topics[0] not in notes:
        print("qargi: the runtime %s has no notes topic '%s'%s" % (runtime, topics[0], "; its topics: " + ", ".join(sorted(notes)) if notes else " (it has no notes)"),
              file=sys.stderr)
        return 1
    print(notes[topics[0]])
    return 0


def cmd_check(name):
    e, d, findings = findings_of(name)
    bad = adapter_problem(d, e["dir"])
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
    for s in surfaces_of(name):
        for c in capabilities2():
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


def cmd_layout(name, field, would, home, project=None):
    lay = layout(name, home=home, project=project)
    if field is None:
        print(json.dumps(lay, indent=2))
        return 0
    if field not in LAYOUT_FIELDS:
        print("qargi: unknown layout field '%s'; one of %s" % (field, ", ".join(LAYOUT_FIELDS)), file=sys.stderr)
        return 2
    v = require(name, field, would or "the verb needs it", home=home, project=project)
    print(v if isinstance(v, str) else json.dumps(v))
    return 0


def cmd_of(args):
    """of PROJECT [--conf DIR] [--surface local|cloud]: the project's provider. With a surface it is that surface's runtime (a family
    name is resolved; a notice goes to stderr when it was); without, what models.provider says when it is one name."""
    opts, pos, i = {}, [], 0
    while i < len(args):
        if args[i] in ('--conf', "--surface") and i + 1 < len(args):
            opts[args[i]], i = args[i + 1], i + 2
        else:
            pos.append(args[i])
            i += 1
    if len(pos) != 1 or "--surface" in opts and opts["--surface"] not in SURFACES or any(a.startswith("--") for a in pos):
        print("usage: qargi provider of PROJECT [--conf DIR] [--surface local|cloud]", file=sys.stderr)
        return 2
    project, conf, surface = pos[0], opts.get('--conf'), opts.get("--surface")
    if surface is None:
        print(provider_of_project(project, conf))
        return 0
    runtime, notice = resolve_project(_stored_answers(project, conf), surface, project)
    if notice:
        print("qargi: note: " + notice, file=sys.stderr)
    print(runtime)
    return 0


def main(argv):
    usage = ("usage: qargi provider list | show NAME [--project P] [--json] | effective RUNTIME SURFACE CAP [--project P] | check NAME|DIR [--project P] | new NAME [--kind K] [--from F] | import SOURCE [--name N] | seal NAME | remove NAME "
             "| enable|disable PROJECT EXT | attest NAME CAP --asked W ... | accept NAME --surface S --no-barrier [--project P] --asked WORDS "
             "[--approved WORDS] [--plan TOKEN] | layout NAME [FIELD] [--project P] | require-skills NAME [--project P] | launch NAME RENDER [--project P] | adapter-run NAME SURFACE VERB [--check] | addenda NAME SURFACE | notes [TOPIC] [--project P] | model NAME SURFACE TIER | of PROJECT [--surface S]")
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
        project = None
        if "--project" in pos and pos.index("--project") == len(pos) - 2:
            project, pos = pos[-1], pos[:-2]
        if verb == "show" and len(pos) == 1 and len(rest) - len(pos) - (2 if project else 0) <= 1:
            lib = _library_module()
            rc = lib.show_pack(pos[0], "--json" in rest, project) if lib else None   # a library catalog or extension; a provider is shown below
            return rc if rc is not None else cmd_show(pos[0], "--json" in rest, project)
        if verb in LIBRARY_VERBS or verb == "check":
            lib = _library_module()
            if lib is None and verb != "check":
                print("qargi: provider %s needs lib/conformance/, which is not beside this file" % verb, file=sys.stderr)
                return 1
            rc = lib.run(verb, rest) if lib else None
            if rc is not None:
                return rc
            if verb == "check" and len(rest) == 1 and not rest[0].startswith("--"):
                return cmd_check(rest[0])                              # a shipped definition (or no such name): the report this file has always made
        if verb == "effective" and len(rest) == 3:
            return cmd_effective(rest[0], rest[1], rest[2])
        if verb == "effective" and len(rest) == 5 and rest[3] == "--project":
            return cmd_effective(rest[0], rest[1], rest[2], rest[4])
        if verb == "require-barrier" and len(rest) in (2, 4) and (len(rest) == 2 or rest[2] == "--project"):
            return cmd_require_barrier(rest[0], rest[1], rest[3] if len(rest) == 4 else None)
        if verb == "skills-dirs" and len(rest) <= 1:
            for d in skills_dirs(rest[0] if rest else None):
                print(d)
            return 0
        if verb == "adapter-run":
            return cmd_adapter(rest)
        if verb == "addenda":
            return cmd_addenda(rest)
        if verb == "notes":
            return cmd_notes(rest)
        if verb == "model":
            return cmd_model(rest)
        if verb == "of":
            return cmd_of(rest)
        if verb in ("layout", "require-skills", "launch"):
            opts, pos, i = {}, [], 0
            while i < len(rest):
                if rest[i] in ('--would', '--home', '--project') and i + 1 < len(rest):
                    opts[rest[i]], i = rest[i + 1], i + 2
                else:
                    pos.append(rest[i])
                    i += 1
            if verb == "layout" and len(pos) in (1, 2):
                return cmd_layout(pos[0], pos[1] if len(pos) == 2 else None, opts.get('--would'), opts.get('--home'), opts.get('--project'))
            if verb == "require-skills" and len(pos) == 1:
                require_skills(pos[0], opts.get('--would') or "the verb needs it", project=opts.get('--project'))
                return 0
            if verb == "launch" and len(pos) == 2:
                print(launch_line(pos[0], pos[1], project=opts.get('--project')))
                return 0
    except Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 3
    except (NoProvider, Refused) as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2
    except ProviderError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    print(usage, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
