"""qargi migrate home: copy the data from the earlier XDG directories to ~/.qargi (or $QARGI_HOME).

  migrate.py home                                       print the plan and a plan token; changes nothing
  migrate.py home --plan TOKEN --approved "<the user's words>"      apply exactly that plan

From ${XDG_CONFIG_HOME:-~/.config}/qargi and ${XDG_STATE_HOME:-~/.local/state}/qargi to <root>/config and <root>/state,
the live root (never a dev run's sandbox: a dev run refuses, see build).
The plan lists every directory, file and link it will create (with modes and sha256 digests), the files it skips
(*.lock) and the files whose old absolute paths it rewrites in the copy (a project's credential file, local-runs.jsonl,
anything else that names the old directories; audit.log, supervisor.log and run-events/ are records and are copied byte for byte). The token is a hash of
that plan, so a source that changed after you saw the plan is refused. Apply COPIES: the old directories are not
touched and stay as a backup. It refuses when the new root exists and is not empty, and checks every copied file
by digest after writing it; a failed apply removes what it made. It is idempotent: once applied (a marker in the
new root says so) the plan says there is nothing to do."""
import datetime, hashlib, json, os, re, shutil, stat, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

SCAN_LIMIT = 64 * 1024 * 1024        # larger files are copied as they are, not scanned for old paths
RECORDS = ("audit.log", "supervisor.log", "run-events/")   # state files that record what happened: copied byte for byte


def is_record(side, rel):
    return side == "state" and (rel in RECORDS[:2] or rel.startswith(RECORDS[2]))
MARKER = "migrated-home.json"
NAME_CHARS = r"\w.@+=-"


def die(msg, code=1):
    print("qargi: " + msg, file=sys.stderr)
    raise SystemExit(code)


def digest_bytes(b):
    return hashlib.sha256(b).hexdigest()


def digest_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rules(pairs):
    """[(compiled regex, replacement)] for each old directory: the absolute path, and its ~, $HOME and ${HOME} spellings."""
    home = os.path.expanduser("~")
    out = []
    for old, new in pairs:
        forms = [(old, new)]
        if old.startswith(home + os.sep):
            rel_old = old[len(home):]
            rel_new = new[len(home):] if new.startswith(home + os.sep) else None
            for pre in ("~", "$HOME", "${HOME}"):
                forms.append((pre + rel_old, pre + rel_new if rel_new is not None else new))
        for o, n in forms:
            rx = re.compile(("(?<![/%s])" % NAME_CHARS + re.escape(o) + "(?![%s])" % NAME_CHARS).encode())
            out.append((rx, n.replace("\\", "\\\\").encode()))
    return out


def rewrite(data, rl):
    for rx, new in rl:
        data = rx.sub(new, data)
    return data


def scan(src, side, rl, entries, skipped):
    """Walk one source directory into entries (dicts); symbolic links are not followed."""
    def walk(rel):
        full = os.path.join(src, rel) if rel else src
        entries.append({"kind": "dir", "side": side, "rel": rel, "mode": stat.S_IMODE(os.lstat(full).st_mode)})
        for name in sorted(os.listdir(full)):
            r = os.path.join(rel, name) if rel else name
            p = os.path.join(src, r)
            s = os.lstat(p)
            if stat.S_ISLNK(s.st_mode):
                t = os.readlink(p)
                entries.append({"kind": "link", "side": side, "rel": r, "target": t, "new_target": rewrite(t.encode(), rl).decode()})
            elif stat.S_ISDIR(s.st_mode):
                walk(r)
            elif stat.S_ISREG(s.st_mode):
                if name.endswith(".lock"):
                    skipped.append("%s/%s (lock file)" % (side, r))
                    continue
                e = {"kind": "file", "side": side, "rel": r, "mode": stat.S_IMODE(s.st_mode), "size": s.st_size, "mtime": s.st_mtime, "rewritten": False}
                if s.st_size <= SCAN_LIMIT:
                    with open(p, "rb") as fh:
                        data = fh.read()
                    e["sha"] = digest_bytes(data)
                    if b"\0" not in data:
                        new = rewrite(data, rl)
                        if new != data and is_record(side, r):
                            e["record"] = True              # names an old path, and is left as it is
                        elif new != data:
                            e["rewritten"], e["new_sha"] = True, digest_bytes(new)
                else:
                    e["sha"] = digest_file(p)
                    e["unscanned"] = True
                entries.append(e)
            else:
                skipped.append("%s/%s (not a file, directory or link)" % (side, r))
    walk("")


def build():
    if P.dev_run():
        die("this is a dev run (%s, not the installed copy), so it would fill its own sandbox instead of your live data: "
            "run the installed qargi, or name the destination with QARGI_HOME" % P.tool_root())
    if os.environ.get("QARGI_CONF") or os.environ.get("QARGI_STATE"):
        die("migrate home moves the default locations: unset QARGI_CONF and QARGI_STATE (QARGI_HOME may name the new root)")
    root = P.live_root()
    dsts = {"config": os.path.join(root, "config"), "state": os.path.join(root, "state")}
    srcs = {"config": P.legacy_conf(), "state": P.legacy_state()}
    present = [(srcs[s], dsts[s], s) for s in ("config", "state") if os.path.isdir(srcs[s])]
    plan = {"root": root, "from": [o for o, _, _ in present], "entries": [], "skipped": [], "done": None}
    if not present:
        return plan
    if os.path.lexists(root) and not os.path.isdir(root):
        die("%s exists and is not a directory; nothing was changed" % root)
    if os.path.isdir(root) and os.listdir(root):
        mk = os.path.join(root, MARKER)
        if os.path.isfile(mk):
            try:
                with open(mk) as fh:
                    plan["done"] = json.load(fh)
            except ValueError:
                plan["done"] = {}
            return plan
        die("%s exists and is not empty, so nothing was copied: move it away, or point QARGI_HOME at an empty place" % root)
    rl = rules([(srcs[s], dsts[s]) for s in srcs])
    for o, _, s in present:
        scan(o, s, rl, plan["entries"], plan["skipped"])
    return plan


def token(plan):
    body = json.dumps({"root": plan["root"], "from": plan["from"], "skipped": plan["skipped"],
                       "entries": [{k: v for k, v in e.items() if k != "mtime"} for e in plan["entries"]]}, sort_keys=True)
    return hashlib.sha256(body.encode()).hexdigest()[:12]


def show(plan):
    es = plan["entries"]
    files = [e for e in es if e["kind"] == "file"]
    print("From:   %s" % "\n        ".join(plan["from"]))
    print("To:     %s (config/ and state/)" % plan["root"])
    print("It copies %d directories, %d files (%d bytes) and %d links; the old directories are not touched." % (
        sum(e["kind"] == "dir" for e in es), len(files), sum(e["size"] for e in files), sum(e["kind"] == "link" for e in es)))
    for e in es:
        where = "%s/%s" % (e["side"], e["rel"]) if e["rel"] else e["side"] + "/"
        if e["kind"] == "dir":
            print("  dir   %-48s %04o" % (where, e["mode"]))
        elif e["kind"] == "file":
            note = ("  rewrites old paths -> sha256 %s" % e["new_sha"][:12]) if e["rewritten"] else ("  record: copied verbatim" if e.get("record") else None) or ("  (too large to scan for old paths)" if e.get("unscanned") else "")
            print("  file  %-48s %04o sha256 %s%s" % (where, e["mode"], e["sha"][:12], note))
        else:
            print("  link  %-48s -> %s%s" % (where, e["new_target"], "" if e["new_target"] == e["target"] else " (was %s)" % e["target"]))
    rew = [e for e in es if (e["kind"] == "file" and e["rewritten"]) or (e["kind"] == "link" and e["new_target"] != e["target"])]
    print("Rewritten in the copy (old config and state paths -> the new ones): %s" % (", ".join("%s/%s" % (e["side"], e["rel"]) for e in rew) or "none"))
    rec = [e for e in es if e.get("record")]
    print("Copied verbatim (records: state/audit.log, state/supervisor.log and state/run-events/ are never rewritten, even where they name an old path): %s" % (
        ", ".join("state/" + e["rel"] for e in rec) or "none of them names one"))
    for s in plan["skipped"]:
        print("  skip  %s" % s)


def now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def audit(state, detail, approved):
    os.makedirs(state, mode=0o700, exist_ok=True)
    f = os.path.join(state, "audit.log")
    with open(f, "a") as fh:
        fh.write(json.dumps({"ts": now(), "verb": "migrate-home", "detail": detail, "asked": "", "approved": approved, "nested": False}) + "\n")
    os.chmod(f, 0o600)


def undo(root, made_root):
    if made_root:
        shutil.rmtree(root, ignore_errors=True)
        return
    for name in os.listdir(root):
        p = os.path.join(root, name)
        if os.path.isdir(p) and not os.path.islink(p):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.remove(p)


def apply(plan, tok, approved):
    root = plan["root"]
    srcs = {"config": P.legacy_conf(), "state": P.legacy_state()}
    dsts = {"config": os.path.join(root, "config"), "state": os.path.join(root, "state")}
    rl = rules([(srcs[s], dsts[s]) for s in srcs])
    made_root = not os.path.exists(root)
    try:
        os.makedirs(root, mode=0o700, exist_ok=True)
        for e in plan["entries"]:
            d, s = dsts[e["side"]], srcs[e["side"]]
            target = os.path.join(d, e["rel"]) if e["rel"] else d
            src = os.path.join(s, e["rel"]) if e["rel"] else s
            if e["kind"] == "dir":
                os.makedirs(target, mode=0o700, exist_ok=True)
            elif e["kind"] == "link":
                os.symlink(e["new_target"], target)
            elif e["size"] <= SCAN_LIMIT:
                with open(src, "rb") as fh:
                    data = fh.read()
                if digest_bytes(data) != e["sha"]:
                    raise RuntimeError("%s changed while it was copied" % src)
                fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(rewrite(data, rl) if e["rewritten"] else data)
            else:
                shutil.copyfile(src, target)
            if e["kind"] == "file":
                os.chmod(target, e["mode"])
                os.utime(target, (e["mtime"], e["mtime"]))
                if digest_file(target) != (e["new_sha"] if e["rewritten"] else e["sha"]):
                    raise RuntimeError("the copy of %s does not match its digest" % target)
        for e in reversed(plan["entries"]):         # directory modes last: a read-only directory would block its files
            if e["kind"] == "dir":
                os.chmod(os.path.join(dsts[e["side"]], e["rel"]) if e["rel"] else dsts[e["side"]], e["mode"])
        mk = os.path.join(root, MARKER)
        with open(mk, "w") as fh:
            json.dump({"from": plan["from"], "plan": tok, "at": now()}, fh)
        os.chmod(mk, 0o600)
        audit(dsts["state"], "plan %s: %d files copied from %s" % (tok, sum(e["kind"] == "file" for e in plan["entries"]), ", ".join(plan["from"])), approved)
    except (OSError, RuntimeError) as ex:
        undo(root, made_root)
        die("stopped, and what was copied is removed again (the old directories were not touched): %s" % ex)


def main(argv):
    tok_arg, approved, i = "", "", 0
    while i < len(argv):
        if argv[i] == "--plan" and i + 1 < len(argv):
            tok_arg = argv[i + 1]; i += 2
        elif argv[i] == "--approved" and i + 1 < len(argv):
            approved = argv[i + 1]; i += 2
        else:
            die("unknown argument %s (qargi help migrate home)" % argv[i], 2)
    plan = build()
    if not plan["from"]:
        print("nothing to migrate: neither earlier directory exists")
        return 0
    if plan["done"] is not None:
        print("nothing to do: %s was filled from the earlier directories%s. They remain as a backup; remove them yourself once you no longer need them." % (
            plan["root"], (" on " + plan["done"]["at"]) if plan["done"].get("at") else ""))
        return 0
    tok = token(plan)
    print("qargi migrate home: %s" % ("applying this plan" if approved else "plan (nothing is changed)"))
    show(plan)
    if not approved:
        print("plan token: %s   (apply with: qargi migrate home --plan %s --approved \"<the user's go-ahead>\")" % (tok, tok))
        return 0
    if tok_arg != tok:
        die("the plan changed or --plan is missing: run qargi migrate home, show the plan to the user, then apply exactly that with --plan %s" % tok)
    apply(plan, tok, approved)
    print("migrated: %d files copied to %s; the earlier directories are untouched. Run qargi migrate home again to confirm nothing is left." % (
        sum(e["kind"] == "file" for e in plan["entries"]), plan["root"]))
    return 0
