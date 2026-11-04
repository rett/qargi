#!/usr/bin/env python3
"""The signing answers of a release and the record of its signature (the part of `qargi release sign|publish|status` that is not shell).

Answers, under `release` in the project's answers file:
  release.sign.key             path of an ssh private key (not a .pub file: that would make ssh-keygen ask an agent)
  release.sign.namespace       the value of ssh-keygen -n
  release.sign.files           files to sign, relative to the repository (each gets a FILE.sig next to it)
  release.sign.verify_command  optional argv list, run in the repository after signing (no shell)
  release.assets               files to attach to the GitHub release, relative to the repository
  release.notes_file           a file with the release notes, relative to the repository; {version} is replaced

The record is $STATE/release/PROJECT-VERSION.sign.json: the tag's commit, the sha256 of every signed file and of its signature, and the
result of the signing and of verify_command. Nothing the person types (the passphrase) ever reaches this file or any argument of it.

  release_sign.py problems AF                    print the problems of the `release` answers; exit 1 if there are any
  release_sign.py config AF [--need-sign]        the same, quiet on success; --need-sign also wants release.sign
  release_sign.py lead-only                      exit 2 in a member run or when QARGI_NESTED is set
  release_sign.py resolve REPO FILE...           print "sha256<TAB>absolute path<TAB>path in the repository" per file; exit 1 if one is no regular
                                                 file inside the repository
  release_sign.py record --state F --repo R --af AF --project P --version V --commit C --sign-rc N --verify-rc N|none
  release_sign.py check --state F --repo R --af AF --commit C     print the verdict; exit 0 only when the record is ok and still true
"""
import hashlib, json, os, re, sys, time

NS_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@:+-]{0,63}")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
RELEASE_KEYS = ("sign", "assets", "notes_file")
SIGN_KEYS = ("key", "namespace", "files", "verify_command")


def rel_ok(p):
    """A path inside the repository, as a name: relative, normal, no control character, nothing the gh asset label syntax (#) or an option (-) could use."""
    return (isinstance(p, str) and p != "" and not p.startswith(("/", "-", "~")) and not CTRL_RE.search(p) and "#" not in p
            and os.path.normpath(p) == p and not p.startswith("../") and p != "..")


def problems(rel):
    """The problems of the `release` answers (a value, or None when the answers have none)."""
    out = []
    if rel is None:
        return out
    if not isinstance(rel, dict):
        return ["release: an object like {sign, assets, notes_file}"]
    for k in rel:
        if k not in RELEASE_KEYS:
            out.append("release.%s: unknown key (%s)" % (k, ", ".join(RELEASE_KEYS)))
    if "assets" in rel:
        a = rel["assets"]
        if not (isinstance(a, list) and all(rel_ok(x) for x in a) and len(set(a)) == len(a)):
            out.append("release.assets: a list of distinct file names relative to the repository (no .., no #, not starting with - or /)")
    if "notes_file" in rel:
        n = rel["notes_file"]
        if not (isinstance(n, str) and rel_ok(n.replace("{version}", "0.0.0"))):
            out.append("release.notes_file: a file name relative to the repository, {version} standing for the version (no .., no #, not starting with - or /)")
    if "sign" in rel:
        s = rel["sign"]
        if not isinstance(s, dict):
            out.append("release.sign: an object like {key, namespace, files, verify_command}")
            return out
        for k in s:
            if k not in SIGN_KEYS:
                out.append("release.sign.%s: unknown key (%s)" % (k, ", ".join(SIGN_KEYS)))
        k = s.get("key")
        if not (isinstance(k, str) and k and not CTRL_RE.search(k) and (k.startswith(("/", "~/"))) and not k.endswith(".pub")):
            out.append("release.sign.key: the path of an ssh private key, absolute or starting with ~/ (not a .pub file)")
        ns = s.get("namespace")
        if not (isinstance(ns, str) and NS_RE.fullmatch(ns)):
            out.append("release.sign.namespace: the ssh-keygen namespace, letters, digits and ._@:+- (for example file)")
        f = s.get("files")
        if not (isinstance(f, list) and f and all(rel_ok(x) for x in f) and len(set(f)) == len(f)):
            out.append("release.sign.files: a non-empty list of distinct file names relative to the repository (for example dist/release/SHA256SUMS)")
        v = s.get("verify_command")
        if v is not None and not (isinstance(v, list) and v and all(isinstance(x, str) and x and "\x00" not in x for x in v)):
            out.append("release.sign.verify_command: a command as a list of words, run without a shell (for example [\"make\", \"release-verify\"])")
    return out


def load_release(af):
    try:
        with open(af, encoding="utf-8") as f:
            return (json.load(f) or {}).get("release")
    except (OSError, ValueError):
        return None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve(repo, name):
    """(absolute real path, name in the repository) of a regular file inside repo; ValueError says why not. An absolute name is accepted when it is inside."""
    root = os.path.realpath(repo)
    if CTRL_RE.search(name) or "#" in name or name == "":
        raise ValueError("%s: not a usable file name" % name.encode("unicode_escape").decode())
    full = os.path.realpath(os.path.join(root, name))
    if not full.startswith(root + os.sep):
        raise ValueError("%s: not inside the repository %s" % (name, root))
    if not os.path.isfile(full):
        raise ValueError("%s: not a file (build it first)" % name)
    return full, os.path.relpath(full, root)


def sig_hash(full):
    p = full + ".sig"
    return sha256(p) if os.path.isfile(p) else None


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def args_of(argv, names, flags=()):
    out, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            out[a] = True
            i += 1
        elif a in names and i + 1 < len(argv):
            out[a] = argv[i + 1]
            i += 2
        else:
            raise SystemExit("qargi: release_sign.py: unexpected argument %s" % a)
    return out


def sign_files(af, repo):
    s = (load_release(af) or {}).get("sign") or {}
    return [resolve(repo, n) for n in s.get("files", [])]


def cmd_record(argv):
    a = args_of(argv, ("--state", "--repo", "--af", "--project", "--version", "--commit", "--sign-rc", "--verify-rc"))
    s = (load_release(a["--af"]) or {}).get("sign") or {}
    files, result = {}, "ok"
    for full, rel in sign_files(a["--af"], a["--repo"]):
        files[rel] = {"sha256": sha256(full), "sig_sha256": sig_hash(full)}
        if files[rel]["sig_sha256"] is None:
            result = "sign-failed"
    if a["--sign-rc"] != "0":
        result = "sign-failed"
    elif a["--verify-rc"] != "none" and a["--verify-rc"] != "0":
        result = "verify-failed"
    rec = {"schema": 1, "project": a["--project"], "version": a["--version"], "commit": a["--commit"], "at": now(), "result": result,
           "namespace": s.get("namespace"), "key": s.get("key"), "verify_command": s.get("verify_command"),
           "verify_exit": None if a["--verify-rc"] == "none" else int(a["--verify-rc"]), "files": files}
    os.makedirs(os.path.dirname(a["--state"]), exist_ok=True)
    tmp = a["--state"] + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f, indent=1)
        f.write("\n")
    os.replace(tmp, a["--state"])
    print(result)
    return 0 if result == "ok" else 1


def cmd_check(argv):
    a = args_of(argv, ("--state", "--repo", "--af", "--commit"))
    try:
        with open(a["--state"], encoding="utf-8") as f:
            rec = json.load(f)
    except (OSError, ValueError):
        print("no signature is recorded")
        return 1
    s = (load_release(a["--af"]) or {}).get("sign") or {}
    if rec.get("result") != "ok":
        print("the last signing ended with %s" % rec.get("result"))
        return 1
    if rec.get("commit") != a["--commit"]:
        print("the signature was made at another commit than the tag")
        return 1
    if (rec.get("namespace"), rec.get("key"), rec.get("verify_command")) != (s.get("namespace"), s.get("key"), s.get("verify_command")) \
            or sorted(rec.get("files", {})) != sorted(s.get("files", [])):
        print("release.sign changed since the signature was made")
        return 1
    try:
        cur = {rel: (sha256(full), sig_hash(full)) for full, rel in sign_files(a["--af"], a["--repo"])}
    except ValueError as e:
        print("a signed file is gone: %s" % e)
        return 1
    for rel, h in rec["files"].items():
        if cur[rel][0] != h["sha256"]:
            print("%s changed since it was signed" % rel)
            return 1
        if cur[rel][1] != h["sig_sha256"]:
            print("%s.sig changed since it was recorded" % rel)
            return 1
    print("signed and verified at %s (%s)" % (rec["at"], ", ".join(sorted(rec["files"]))))
    return 0


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd in ("problems", "config"):
        if not rest:
            return 2
        flags = [x for x in rest[1:] if x != "--need-sign"]
        if flags:
            return 2
        rel = load_release(rest[0])
        found = problems(rel)
        if "--need-sign" in rest and not (isinstance(rel, dict) and "sign" in rel):
            found.append("release.sign is not set: qargi project set PROJECT release.sign '{\"key\": ..., \"namespace\": ..., \"files\": [...]}'")
        if found:
            print("\n".join(found), file=sys.stderr if cmd == "config" else sys.stdout)
            return 1
        return 0
    if cmd == "lead-only":
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import marshal_refs
        if os.environ.get("QARGI_NESTED") or marshal_refs.in_member_run():
            print("qargi: release sign is not available in a member run or a nested call: the passphrase is typed by the person at their own terminal", file=sys.stderr)
            return 2
        return 0
    if cmd == "resolve":
        if len(rest) < 2:
            return 2
        try:
            for name in rest[1:]:
                full, rel = resolve(rest[0], name)
                print("%s\t%s\t%s" % (sha256(full), full, rel))
        except ValueError as e:
            print("qargi: %s" % e, file=sys.stderr)
            return 1
        return 0
    if cmd in ("record", "check"):
        try:
            return (cmd_record if cmd == "record" else cmd_check)(rest)
        except ValueError as e:
            print("qargi: %s" % e, file=sys.stderr)
            return 1
    print("qargi: release_sign.py: unknown command %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
