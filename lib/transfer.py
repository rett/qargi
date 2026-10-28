#!/usr/bin/env python3
"""qargi export / qargi import: move a project's qargi setup between machines, or keep a copy.

  transfer.py export [--project P[,P]] [--only LIST] [--out FILE] [--no-encrypt | --password-file F]
  transfer.py import FILE [--project P[,P]] [--only LIST] [--mode merge|overwrite|replace] [--password-file F] [--dry-run]

An archive is a gzip tar holding manifest.json (what is inside, with a sha256 of every file) and one folder per
component. With a password the whole archive is encrypted by gpg (symmetric AES-256, the passphrase goes over a pipe,
never into an argument). Import reads the archive as untrusted data: names are checked, everything is extracted into
memory, hashes must match, and nothing is written before the plan has been shown and you have said yes.
"""
import datetime, getpass, hashlib, io, json, os, re, shutil, subprocess, sys, tarfile, termios, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
FORMAT = 1
MAX_ARCHIVE = 256 * 1024 * 1024
CONF = os.environ.get("QARGI_CONF") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "qargi")
STATE = os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")
TTY_IN = os.environ.get("QARGI_TTY_IN", "/dev/tty")
TTY_OUT = os.environ.get("QARGI_TTY_OUT", "/dev/tty")

# component -> (archive folder, what it holds, selected by default)
COMPONENTS = {
    "config": ("config", "project answers, the instance registry, profiles and the skill and tool library", True),
    "definitions": ("definitions", "the cloud agents, deployments and environment as they are now (read from the cloud, secrets removed)", True),
    "memories": ("memories", "every note of the memory and reference stores (read from the cloud)", True),
    "state": ("state", "the session tracker and the audit log", False),
    "credentials": ("credentials", "token files (an archive that holds them must be encrypted)", False),
}
ORDER = list(COMPONENTS)
SAFE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._@+=-]*$")
PROJECT = re.compile(r"^[a-z][a-z0-9]{0,23}$")
SECRET_KEY = re.compile(r"token|secret|password|authorization|credential", re.I)
MODES = ("merge", "overwrite", "replace")
MODE_TEXT = {"merge": "add what is missing, keep everything that exists",
             "overwrite": "add what is missing and replace what differs, keep the rest",
             "replace": "make it match the archive: also removes what the archive does not hold (after a backup)"}


def F(name):
    """An option of an external tool (ant, gpg), spelled out here so it is not mistaken for one of qargi's own."""
    return "--" + name


class Stop(Exception):
    pass


def die(msg, code=1):
    print("qargi: " + msg, file=sys.stderr)
    raise SystemExit(code)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def version():
    try:
        with open(os.path.join(ROOT, "VERSION")) as f:
            return f.read().strip()
    except OSError:
        return "0"


# --- terminal ------------------------------------------------------------------------------------------------------
_tin = _tout = None


def tty():
    global _tin, _tout
    if _tin is None:
        try:
            _tin, _tout = open(TTY_IN), open(TTY_OUT, "w")
        except OSError:
            _tin = _tout = False
    return _tin, _tout


def interactive():
    return bool(tty()[0])


def ask(prompt, default=""):
    tin, tout = tty()
    if not tin:
        die("this needs a terminal: run it in a terminal (from Claude Code: ! qargi ...), or give every answer as an option")
    tout.write(prompt + (" [%s] " % default if default else " "))
    tout.flush()
    line = tin.readline()
    if line == "":
        raise Stop("no answer")
    return line.strip() or default


def ask_hidden(prompt):
    tin, tout = tty()
    if not tin:
        die("a password is needed: run it in a terminal or give --password-file")
    tout.write(prompt + " ")
    tout.flush()
    if tin.isatty():
        fd = tin.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~termios.ECHO
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            line = tin.readline()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            tout.write("\n")
    else:
        line = tin.readline()
    if line == "":
        raise Stop("no answer")
    return line.rstrip("\r\n")


def confirm(prompt):
    return ask(prompt + " [y/N]").lower() in ("y", "yes")


def pick(items, prompt, default):
    """Ask for a comma separated list of the given names or numbers; Enter takes the default list."""
    got = ask(prompt, ",".join(default))
    chosen = []
    for w in [x.strip() for x in got.replace(" ", ",").split(",") if x.strip()]:
        n = items[int(w) - 1] if w.isdigit() and 0 < int(w) <= len(items) else w
        if n not in items:
            die("'%s' is not one of: %s" % (w, ", ".join(items)))
        if n not in chosen:
            chosen.append(n)
    return chosen


def audit(verb, detail, approved=""):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    f = os.path.join(STATE, "audit.log")
    with open(f, "a") as fh:
        fh.write(json.dumps({"ts": now(), "verb": verb, "detail": detail, "asked": "", "approved": approved, "nested": False}) + "\n")
    os.chmod(f, 0o600)


# --- files and the cloud -------------------------------------------------------------------------------------------
def read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def write_file(path, data, mode=0o600):
    d = os.path.dirname(path) or "."
    os.makedirs(d, mode=0o700, exist_ok=True)
    tmp = "%s.tmp%d" % (path, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    os.replace(tmp, path)


def jload(path, default):
    raw = read(path)
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def jdump(obj):
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


def ant(args, stdin=None):
    """Run the ant CLI; returns (returncode, stdout). stdin is None (closed) unless given."""
    try:
        r = subprocess.run(["ant"] + args, input=stdin if stdin is not None else b"", capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return r.returncode, r.stdout.decode("utf-8", "replace")


def ant_json(args):
    rc, out = ant(args)
    if rc != 0:
        return None
    try:
        return json.loads(out)
    except ValueError:
        return None


def scrub(obj, counter):
    """Remove the values of keys that look like secrets (a name is kept, a value never)."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if SECRET_KEY.search(k) and v not in (None, "", False, [], {}) and not isinstance(v, (dict, list)):
                out[k] = "<removed>"
                counter[0] += 1
            else:
                out[k] = scrub(v, counter)
        return out
    if isinstance(obj, list):
        return [scrub(v, counter) for v in obj]
    return obj


def project_files():
    d = os.path.join(CONF, "projects")
    return sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json") and PROJECT.match(f[:-5])) if os.path.isdir(d) else []


def project_answers(p):
    return jload(os.path.join(CONF, "projects", p + ".json"), {})


def stores_of(answers):
    m = answers.get("memory") or {}
    return {"memory": m.get("memory_store") or "", "reference": m.get("reference_store") or ""}


def profile_owner(fname, projects):
    stem = fname.rsplit(".", 1)[0]
    for p in projects:
        base = os.path.basename((project_answers(p).get("repo") or {}).get("path") or "").lower()
        if stem == p or (base and stem == base):
            return p
    return None


# --- what a component holds ----------------------------------------------------------------------------------------
def store_notes(store):
    """{path: bytes} of every note of a memory store, or None when it cannot be read."""
    rc, out = ant(["beta:memory-stores:memories", "list", F("memory-store-id"), store, F("path-prefix"), "/", F("view"), "full", F("max-items"), "-1"])
    if rc != 0:
        return None
    notes, dec, i = {}, json.JSONDecoder(), 0
    while True:   # ant prints the notes as a stream of JSON values (pretty-printed, or one per line)
        while i < len(out) and out[i] in " \t\r\n,[]":
            i += 1
        if i >= len(out):
            break
        try:
            m, i = dec.raw_decode(out, i)
        except ValueError:
            break
        if isinstance(m, dict) and "path" in m:
            notes[m["path"]] = (m.get("content") or "").encode()
            notes.setdefault("\0id", {})[m["path"]] = m.get("id")
    return notes


def gather_local(comp, projects):
    """{archive path: (bytes, project or None)} of the local items of a component for the given projects."""
    out, warn = {}, []
    if comp == "config":
        for p in projects:
            raw = read(os.path.join(CONF, "projects", p + ".json"))
            if raw is not None:
                out["config/projects/%s.json" % p] = (raw, p)
        inst = jload(os.path.join(CONF, "instances.json"), {})
        for name, v in sorted(inst.items()):
            if name.split("-")[0] in projects:
                out["config/instances/%s.json" % name] = (jdump(v), name.split("-")[0])
        pdir = os.path.join(CONF, "profiles")
        for f in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
            owner = profile_owner(f, projects)
            if owner and os.path.isfile(os.path.join(pdir, f)):
                out["config/profiles/" + f] = (read(os.path.join(pdir, f)), owner)
        pk = os.path.join(CONF, "packs")
        for dp, _, fs in os.walk(pk):
            for f in sorted(fs):
                full = os.path.join(dp, f)
                if os.path.isfile(full) and not os.path.islink(full):
                    out["config/packs/" + os.path.relpath(full, pk)] = (read(full), None)
    elif comp == "definitions":
        inst = jload(os.path.join(CONF, "instances.json"), {})
        for name, v in sorted(inst.items()):
            if name.split("-")[0] not in projects or v.get("location") != "cloud":
                continue
            ids = {"agent": ("beta:agents", F("agent-id"), (v.get("agent") or {}).get("id")),
                   "deployment": ("beta:deployments", F("deployment-id"), v.get("deployment_id")),
                   "environment": ("beta:environments", F("environment-id"), v.get("environment_id"))}
            removed = [0]
            for kind, (cmd, flag, rid) in ids.items():
                if not rid:
                    continue
                data = ant_json([cmd, "retrieve", flag, rid])
                if data is None:
                    warn.append("could not read the %s of %s from the cloud (is ant logged in?)" % (kind, name))
                    continue
                out["definitions/%s/%s.json" % (name, kind)] = (jdump(scrub(data, removed)), name.split("-")[0])
            if removed[0]:
                warn.append("%s: %d secret value(s) removed from the definitions" % (name, removed[0]))
    elif comp == "memories":
        for p in projects:
            for kind, store in stores_of(project_answers(p)).items():
                if not store:
                    continue
                notes = store_notes(store)
                if notes is None:
                    warn.append("could not read the %s store of %s (%s)" % (kind, p, store))
                    continue
                for path, data in notes.items():
                    if path == "\0id" or ".." in path.split("/"):
                        continue
                    out["memories/%s/%s/%s" % (p, kind, path.lstrip("/"))] = (data, p)
    elif comp == "state":
        sess = jload(os.path.join(STATE, "sessions.json"), {})
        for sid, v in sorted(sess.items()):
            if str(v.get("instance", "")).split("-")[0] in projects or not v.get("instance"):
                out["state/sessions/%s.json" % sid] = (jdump(v), str(v.get("instance", "-")).split("-")[0] or None)
        raw = read(os.path.join(STATE, "audit.log"))
        if raw is not None:
            out["state/audit.log"] = (raw, None)
    elif comp == "credentials":
        cdir = os.path.join(CONF, "credentials")
        for f in sorted(os.listdir(cdir)) if os.path.isdir(cdir) else []:
            full = os.path.join(cdir, f)
            if os.path.isfile(full) and f.split("-")[0] in projects:
                out["credentials/" + f] = (read(full), f.split("-")[0])
    return out, warn


# --- encryption ----------------------------------------------------------------------------------------------------
def gpg(args, data, password):
    if not shutil.which("gpg"):
        die("encryption needs gpg (install gnupg), or leave the password empty")
    r, w = os.pipe()
    os.write(w, (password + "\n").encode())
    os.close(w)
    try:
        p = subprocess.run(["gpg", F("batch"), F("yes"), F("quiet"), F("pinentry-mode"), "loopback", F("passphrase-fd"), str(r)] + args,
                           input=data, capture_output=True, pass_fds=(r,))
    finally:
        os.close(r)
    return p.returncode, p.stdout, p.stderr.decode("utf-8", "replace")


def encrypt(data, password):
    rc, out, err = gpg([F("symmetric"), F("cipher-algo"), "AES256", "--s2k-mode", "3", "--s2k-digest-algo", "SHA512", "--s2k-count", "65011712", "-o", "-"], data, password)
    if rc != 0:
        die("encryption failed" + (": " + err.strip().splitlines()[-1] if err.strip() else ""))
    return out


def is_encrypted(head):
    return not head.startswith(b"\x1f\x8b")


# --- export --------------------------------------------------------------------------------------------------------
def build_archive(items, comps, projects):
    manifest = {"format": FORMAT, "qargi": version(), "created": now(), "projects": projects, "components": {}, "files": {}}
    for comp in comps:
        manifest["components"][comp] = sum(1 for k in items if k.startswith(COMPONENTS[comp][0] + "/"))
    for path, (data, proj) in items.items():
        manifest["files"][path] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "project": proj}
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        def add(name, data):
            ti = tarfile.TarInfo(name)
            ti.size, ti.mode, ti.mtime = len(data), 0o600, int(time.time())
            tf.addfile(ti, io.BytesIO(data))
        add("manifest.json", jdump(manifest))
        for path in sorted(items):
            add(path, items[path][0])
    return buf.getvalue(), manifest


def parse_list(text, allowed, what):
    got = [x for x in re.split(r"[,\s]+", text) if x]
    for g in got:
        if g not in allowed:
            die("unknown %s '%s'; choose from: %s" % (what, g, ", ".join(allowed)))
    return got


def cmd_export(args):
    projects_arg = only = out = pwfile = None
    noenc = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == F("project"): projects_arg = args[i + 1]; i += 2
        elif a == F("only"): only = args[i + 1]; i += 2
        elif a == F("out"): out = args[i + 1]; i += 2
        elif a == F("password-file"): pwfile = args[i + 1]; i += 2
        elif a == F("no-encrypt"): noenc = True; i += 1
        else: die("unknown option %s (qargi help export)" % a)
    allp = project_files()
    if not allp:
        die("no project is stored yet: qargi help project")
    if projects_arg:
        projects = parse_list(projects_arg, allp, "project")
    elif len(allp) == 1 or not interactive():
        projects = allp
    else:
        tty()[1].write("Projects: %s\n" % ", ".join(allp))
        projects = pick(allp, "Which projects?", allp)
    if only:
        comps = parse_list(only, ORDER, "component")
    elif interactive():
        tout = tty()[1]
        tout.write("\nWhat to export:\n")
        for n, c in enumerate(ORDER, 1):
            tout.write("  %d) %-12s %s\n" % (n, c, COMPONENTS[c][1]))
        comps = pick(ORDER, "Which components? (numbers or names, comma separated)", [c for c in ORDER if COMPONENTS[c][2]])
    else:
        die("say what to export: --only %s" % ",".join(ORDER))
    if not comps:
        die("nothing selected")
    # password
    password = ""
    if pwfile:
        raw = read(pwfile)
        if raw is None: die("cannot read %s" % pwfile)
        password = raw.decode().rstrip("\r\n")
        if not password: die("%s is empty" % pwfile)
    elif noenc:
        password = ""
    elif not interactive():
        die("say how to protect the archive: --password-file FILE, or --no-encrypt")
    else:
        while True:
            password = ask_hidden("Password to encrypt the archive (empty = none):")
            if not password:
                break
            if ask_hidden("Again:") == password:
                break
            print("The two did not match.", file=sys.stderr)
    if "credentials" in comps and not password:
        die("the credentials component holds tokens: give a password (or leave the component out)")
    # gather
    items, warns = {}, []
    for comp in comps:
        got, w = gather_local(comp, projects)
        items.update(got)
        warns += w
    if not items:
        die("nothing to export for %s in %s" % (", ".join(projects), ", ".join(comps)))
    data, manifest = build_archive(items, comps, projects)
    if len(data) > MAX_ARCHIVE:
        die("the archive would be larger than %d MB" % (MAX_ARCHIVE >> 20))
    if password:
        data = encrypt(data, password)
    name = out or "qargi-export-%s.tar.gz%s" % (datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"), ".gpg" if password else "")
    if os.path.exists(name):
        die("%s exists: give another --out" % name)
    write_file(name, data, 0o600)
    for w in warns:
        print("note: " + w, file=sys.stderr)
    print("Wrote %s (%d bytes, %s)" % (name, len(data), "encrypted with the password" if password else "NOT encrypted"))
    for comp in comps:
        print("  %-12s %d file(s)" % (comp, manifest["components"][comp]))
    audit("export", "%s -> %s%s" % (",".join(comps), os.path.basename(name), " (encrypted)" if password else ""))
    return 0


# --- import --------------------------------------------------------------------------------------------------------
def load_archive(path, pwfile):
    raw = read(path)
    if raw is None:
        die("cannot read %s" % path)
    if len(raw) > MAX_ARCHIVE:
        die("%s is larger than %d MB" % (path, MAX_ARCHIVE >> 20))
    if is_encrypted(raw[:16]):
        if pwfile:
            pw = read(pwfile)
            if pw is None: die("cannot read %s" % pwfile)
            rc, data, err = gpg(["-d", "-o", "-"], raw, pw.decode().rstrip("\r\n"))
            if rc != 0: die("the password does not open %s" % path)
        else:
            for attempt in range(3):
                rc, data, err = gpg(["-d", "-o", "-"], raw, ask_hidden("Password for %s:" % os.path.basename(path)))
                if rc == 0:
                    break
                print("That password does not open it.", file=sys.stderr)
            else:
                die("giving up after three tries")
        raw = data
    return read_tar(raw)


def safe_name(name):
    parts = name.split("/")
    return bool(name) and not name.startswith("/") and all(p not in ("", ".", "..") and "\0" not in p for p in parts)


def read_tar(raw):
    files, total = {}, 0
    try:
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            for ti in tf:
                if not ti.isreg() or not safe_name(ti.name):
                    die("the archive holds an entry that is not a plain file with a plain name (%r): refusing it" % ti.name[:80])
                if ti.name != "manifest.json" and ti.name.split("/")[0] not in {c[0] for c in COMPONENTS.values()}:
                    die("the archive holds a file outside the known folders (%r): refusing it" % ti.name[:80])
                total += ti.size
                if total > MAX_ARCHIVE:
                    die("the archive unpacks to more than %d MB: refusing it" % (MAX_ARCHIVE >> 20))
                files[ti.name] = tf.extractfile(ti).read()
    except (tarfile.TarError, OSError, EOFError) as e:
        die("this is not a qargi archive (%s)" % e)
    if "manifest.json" not in files:
        die("this is not a qargi archive: no manifest.json")
    try:
        manifest = json.loads(files.pop("manifest.json"))
    except ValueError:
        die("the manifest is not valid JSON")
    if manifest.get("format") != FORMAT:
        die("this archive is format %s; this qargi reads format %d (update qargi)" % (manifest.get("format"), FORMAT))
    listed = manifest.get("files") or {}
    if set(listed) != set(files):
        die("the archive and its manifest disagree about the files: refusing it")
    for p, data in files.items():
        if hashlib.sha256(data).hexdigest() != listed[p].get("sha256"):
            die("%s does not match its checksum: the archive is damaged or was changed" % p)
    return {p: (files[p], listed[p].get("project")) for p in files}, manifest


def comp_of(path):
    folder = path.split("/")[0]
    return next(c for c, v in COMPONENTS.items() if v[0] == folder)


def valid_item(path):
    rest = path.split("/", 1)[1] if "/" in path else ""
    comp = comp_of(path)
    parts = rest.split("/")
    if comp in ("config", "definitions", "state", "credentials"):
        if not all(SAFE.match(p) for p in parts):
            return False
    if comp == "config":
        if parts[0] == "projects": return len(parts) == 2 and parts[1].endswith(".json") and bool(PROJECT.match(parts[1][:-5]))
        if parts[0] == "instances": return len(parts) == 2 and parts[1].endswith(".json")
        return parts[0] in ("profiles", "packs") and len(parts) >= 2
    if comp == "definitions": return len(parts) == 2 and parts[1].split(".")[0] in ("agent", "deployment", "environment")
    if comp == "state": return rest == "audit.log" or (len(parts) == 2 and parts[0] == "sessions" and parts[1].endswith(".json"))
    if comp == "credentials": return len(parts) == 1
    if comp == "memories": return len(parts) >= 3 and parts[1] in ("memory", "reference") and bool(PROJECT.match(parts[0])) and all(parts)
    return False


def local_scope(comp, projects, archive_items):
    """What exists locally for the same projects, to compare with and to find what 'replace' would remove."""
    got, _ = gather_local(comp, projects) if comp != "definitions" else (read_definitions(projects), [])
    if comp == "config":   # the library is global: compare only when the archive carries one
        if not any(k.startswith("config/packs/") for k in archive_items):
            got = {k: v for k, v in got.items() if not k.startswith("config/packs/")}
    return got


def read_definitions(projects):
    out = {}
    base = os.path.join(STATE, "definitions")
    for inst in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        if inst.split("-")[0] in projects:
            for f in sorted(os.listdir(os.path.join(base, inst))):
                out["definitions/%s/%s" % (inst, f)] = (read(os.path.join(base, inst, f)), inst.split("-")[0])
    return out


def build_plan(archive, comps, projects, modes):
    """[(path, action, comp)] with action add|change|same|delete|append."""
    plan = []
    for comp in comps:
        mine = {k: v for k, v in archive.items() if comp_of(k) == comp and (v[1] in projects or v[1] is None or comp == "config" and k.startswith("config/packs/"))}
        if comp == "memories":   # memory notes of a project need the project's local stores
            mine = {k: v for k, v in mine.items() if k.split("/")[1] in projects}
        local = local_scope(comp, projects, mine)
        for k in sorted(mine):
            if k == "state/audit.log":
                have = set((local.get(k, (b"", 0))[0] or b"").decode("utf-8", "replace").splitlines())
                new = [l for l in mine[k][0].decode("utf-8", "replace").splitlines() if l not in have]
                plan.append((k, "append" if new else "same", comp))
            elif k not in local:
                plan.append((k, "add", comp))
            elif local[k][0] == mine[k][0]:
                plan.append((k, "same", comp))
            else:
                plan.append((k, "change" if modes[comp] != "merge" else "keep", comp))
        if modes[comp] == "replace":
            for k in sorted(local):
                if k not in mine and k != "state/audit.log":
                    plan.append((k, "delete", comp))
    return plan


def memory_target(project, kind):
    return stores_of(project_answers(project)).get(kind) or ""


def backup_dir():
    d = os.path.join(STATE, "backups", "import-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
    os.makedirs(d, mode=0o700, exist_ok=True)
    return d


def apply_plan(plan, archive, projects):
    bdir = backup_dir()
    done = {"add": 0, "change": 0, "delete": 0, "append": 0}
    inst_path = os.path.join(CONF, "instances.json")
    sess_path = os.path.join(STATE, "sessions.json")
    cache = {}   # store id -> notes

    def keep(path, data):
        if data is not None:
            write_file(os.path.join(bdir, path), data)

    for path, action, comp in plan:
        if action in ("same", "keep"):
            continue
        rest = path.split("/", 1)[1]
        parts = rest.split("/")
        if comp == "memories":
            proj, kind, notepath = parts[0], parts[1], "/" + "/".join(parts[2:])
            store = memory_target(proj, kind)
            if not store:
                print("skipped %s: %s has no %s store" % (path, proj, kind), file=sys.stderr)
                continue
            if store not in cache:
                cache[store] = store_notes(store) or {}
            ids = cache[store].get("\0id", {})
            old = cache[store].get(notepath)
            keep(path, old)
            if action == "delete":
                ant(["beta:memory-stores:memories", "delete", F("memory-store-id"), store, F("memory-id"), ids.get(notepath, "")])
            else:
                tmp = os.path.join(bdir, ".upload")
                write_file(tmp, archive[path][0])
                stdin = ('content: "@%s"\n' % tmp).encode()
                if notepath in cache[store]:
                    rc, _ = ant(["beta:memory-stores:memories", "update", F("memory-store-id"), store, F("memory-id"), ids.get(notepath, "")], stdin)
                else:
                    rc, _ = ant(["beta:memory-stores:memories", "create", F("memory-store-id"), store, F("path"), notepath], stdin)
                os.remove(tmp)
                if rc != 0:
                    die("could not write %s to the store; stopped (the backup is in %s)" % (notepath, bdir))
        elif comp == "config" and parts[0] == "instances":
            inst = jload(inst_path, {})
            name = parts[1][:-5]
            keep(path, jdump(inst[name]) if name in inst else None)
            if action == "delete": inst.pop(name, None)
            else: inst[name] = json.loads(archive[path][0])
            write_file(inst_path, jdump(inst))
        elif comp == "state" and parts[0] == "sessions":
            sess = jload(sess_path, {})
            sid = parts[1][:-5]
            keep(path, jdump(sess[sid]) if sid in sess else None)
            if action == "delete": sess.pop(sid, None)
            else: sess[sid] = json.loads(archive[path][0])
            write_file(sess_path, jdump(sess))
        elif path == "state/audit.log":
            have = set((read(os.path.join(STATE, "audit.log")) or b"").decode("utf-8", "replace").splitlines())
            new = [l for l in archive[path][0].decode("utf-8", "replace").splitlines() if l not in have]
            with open(os.path.join(STATE, "audit.log"), "a") as fh:
                fh.write("".join(l + "\n" for l in new))
        else:
            target = {"config": CONF, "credentials": CONF, "definitions": os.path.join(STATE, "definitions"), "state": STATE}[comp]
            full = os.path.join(target, "credentials/" + rest if comp == "credentials" else rest)
            keep(path, read(full))
            if action == "delete":
                try: os.remove(full)
                except OSError: pass
            else:
                write_file(full, archive[path][0], 0o600)
        done[action] += 1
    return done, bdir


def cmd_import(args):
    file = only = projects_arg = mode_arg = pwfile = None
    dry = False
    i = 0
    while i < len(args):
        a = args[i]
        if a == F("only"): only = args[i + 1]; i += 2
        elif a == F("project"): projects_arg = args[i + 1]; i += 2
        elif a == F("mode"): mode_arg = args[i + 1]; i += 2
        elif a == F("password-file"): pwfile = args[i + 1]; i += 2
        elif a == F("dry-run"): dry = True; i += 1
        elif a.startswith("-"): die("unknown option %s (qargi help import)" % a)
        elif file is None: file = a; i += 1
        else: die("one archive at a time")
    if not file:
        die("usage: qargi import FILE [--dry-run] (qargi help import)")
    if mode_arg and mode_arg not in MODES:
        die("--mode is one of: %s" % ", ".join(MODES))
    if not dry and not interactive():
        die("import changes your configuration and the cloud memories, so it asks you at a terminal: run it in one, or use --dry-run to see the plan")
    archive, manifest = load_archive(file, pwfile)
    bad = [k for k in archive if not valid_item(k)]
    if bad:
        die("the archive holds a name that is not valid for its folder (%r): refusing it" % bad[0][:80])
    out = tty()[1] or sys.stdout
    present = [c for c in ORDER if manifest["components"].get(c)]
    aprojects = manifest.get("projects") or []
    print("Archive from %s, qargi %s: projects %s" % (manifest.get("created", "?"), manifest.get("qargi", "?"), ", ".join(aprojects) or "none"))
    for c in present:
        print("  %-12s %d file(s)  %s" % (c, manifest["components"][c], COMPONENTS[c][1]))
    if only:
        comps = parse_list(only, present, "component in this archive")
    elif dry:
        comps = [c for c in present if c != "credentials"]
    else:
        comps = pick(present, "\nWhat to import? (names or numbers, comma separated)", [c for c in present if c != "credentials"])
    if not comps:
        die("nothing selected")
    if projects_arg:
        projects = parse_list(projects_arg, aprojects, "project in this archive")
    elif len(aprojects) <= 1 or dry:
        projects = aprojects
    else:
        projects = pick(aprojects, "Which projects? (%s)" % ", ".join(aprojects), aprojects)
    modes = {}
    for c in comps:
        if mode_arg:
            modes[c] = mode_arg
        elif dry:
            modes[c] = "merge"
        else:
            tout = tty()[1]
            tout.write("\n%s: how to treat what already exists?\n" % c)
            for n, m in enumerate(MODES, 1):
                tout.write("  %d) %-9s %s\n" % (n, m, MODE_TEXT[m]))
            modes[c] = pick(list(MODES), "Mode for %s?" % c, ["merge"])[0]
    plan = build_plan(archive, comps, projects, modes)
    counts = {}
    for p, a, c in plan:
        counts.setdefault(c, {}).setdefault(a, []).append(p)
    print("\nPlan (nothing is written until you confirm):")
    for c in comps:
        cc = counts.get(c, {})
        print("  %-12s mode %-9s add %d, change %d, keep %d, same %d, remove %d%s" % (
            c, modes[c], len(cc.get("add", [])), len(cc.get("change", [])), len(cc.get("keep", [])), len(cc.get("same", [])),
            len(cc.get("delete", [])), (", append %d line-set" % len(cc.get("append", []))) if cc.get("append") else ""))
        for a in ("change", "delete", "add"):
            names = cc.get(a, [])
            for n in names[:10]:
                print("      %-6s %s" % (a, n))
            if len(names) > 10:
                print("      ... and %d more %s" % (len(names) - 10, a))
    todo = [x for x in plan if x[1] in ("add", "change", "delete", "append")]
    if dry:
        print("\n(dry run: nothing changed)")
        return 0
    if not todo:
        print("\nNothing to do.")
        return 0
    if any(a == "delete" for _, a, _ in plan):
        n = sum(1 for _, a, _ in plan if a == "delete")
        print("\n%d item(s) would be removed. A backup of everything replaced or removed is saved first." % n)
        if ask("Type 'replace' to allow the removals:") != "replace":
            print("Nothing changed.")
            return 1
    if not confirm("\nApply this plan?"):
        print("Nothing changed.")
        return 1
    approval = "interactive: confirmed at the terminal by %s at %s" % (getpass.getuser(), now())
    done, bdir = apply_plan(plan, archive, projects)
    audit("import", "%s from %s: %d added, %d changed, %d removed, %d appended" % (",".join(comps), os.path.basename(file), done["add"], done["change"], done["delete"], done["append"]), approval)
    print("\nDone: %d added, %d changed, %d removed. Backup of what was replaced: %s" % (done["add"], done["change"], done["delete"], bdir))
    if "memories" in comps:
        print("Check the stores with: qargi memory lint STORE_ID")
    if "config" in comps:
        print("The project answers were imported as they were: check paths and ids with: qargi project show NAME")
    return 0


def main(argv):
    if not argv or argv[0] not in ("export", "import"):
        print("usage: transfer.py export|import ...", file=sys.stderr)
        return 2
    try:
        return cmd_export(argv[1:]) if argv[0] == "export" else cmd_import(argv[1:])
    except Stop as e:
        print("qargi: stopped (%s); nothing was changed by this step" % e, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nqargi: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
