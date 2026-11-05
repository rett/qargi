#!/usr/bin/env python3
"""The tools a role declares: roles.<role>.tools in a project's answers, a list of entries of three kinds.

  {"kind": "go", "name": "github.com/acme/lint/cmd/acme-lint", "version": "v1.2.0"}            go install NAME@VERSION
  {"kind": "binary", "name": "acme-fmt", "version": "2.0.1", "url": "https://...", "sha256": "..."}   one file, downloaded, checked, put in ~/.local/bin
  {"kind": "submodule", "name": "acme-test", "path": "vendor/acme-test"}                       a submodule of the repository the member's clone needs

apt (and pip) packages stay the plain lists roles.<role>.apt and roles.<role>.pip: the cloud environment installs them and the project's own
bootstrap owns them on a host; nothing in them is pinned, hashed or checked out. The tools list is what qargi itself installs, checks or checks out:
  - qargi env plan lists the tools of every role with their state here and env apply installs the go tools (go named in --approve-exec) and the
    binaries (the file's sha256 must be the declared one) after the bootstrap (lib/env_apply.py);
  - qargi env check reports a tool that is missing, at another version, or a binary whose sha256 differs (lib/env_check.py);
  - qargi local prepare checks the declared submodules out in the member's clone from the lead's copy of their objects, offline (checkout below);
  - the cloud provision adds the go tools to the environment's go packages (lib/provision.sh).
A member may not set roles.<role>.tools (lib/guard.py): the lead installs and runs what it names.

  tools.py checkout --answers FILE --role ROLE --clone DIR --copies DIR [--source REPO]
      for each submodule entry of the role: find the commit the clone's HEAD records for its path, take the objects from the lead's checkout
      (REPO/PATH, else its modules directory), copy them to DIR/NAME.git (a mirror with no remote; the commit pinned under refs/heads/qargi-pin)
      and run git submodule update --init in the clone from that copy, with the push URL disabled. Nothing is fetched from a remote: a commit
      that is not in REPO, or no --source (the run was cloned from a URL), is a note on stderr and the submodule is left alone. Prints
      SUBMODULES=path,... for the ones checked out. Exit 0 (2: usage).

As a module: problems(prefix, tools), conflicts(roles), declared(answers), status(entry, repo), install helpers for env apply.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

KINDS = ("go", "binary", "submodule")
KEYS = {"go": ("kind", "name", "version"), "binary": ("kind", "name", "version", "url", "sha256"), "submodule": ("kind", "name", "path")}
GO_PATH = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~/-]{0,200}")
GO_VERSION = re.compile(r"v\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.+-]*)?")
BIN_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,40}")
VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,40}")
SUB_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,120}")
SHA256 = re.compile(r"[0-9a-f]{64}")
URL = re.compile(r"https?://[^\s'\"<>]{1,500}")
BIN_DIR = "~/.local/bin"
GO_KEEP = ("GOPATH", "GOBIN", "GOPROXY", "GOFLAGS", "GOTOOLCHAIN", "GONOSUMDB", "GONOSUMCHECK", "GOPRIVATE", "GOINSECURE")
DOWNLOAD_CAP = 512 * 1024 * 1024
DOWNLOAD_TIMEOUT = 120
GIT_TIMEOUT = 300


# ---- the answers -------------------------------------------------------------------------------------------------------

def problems(prefix, tools):
    """Messages for a roles.<role>.tools value that is not valid (project validation prints them); prefix is roles.<role>."""
    if tools is None:
        return []
    if not isinstance(tools, list):
        return ["%s.tools: a list of {kind: go|binary|submodule, name, ...}" % prefix]
    bad, seen = [], set()
    for i, t in enumerate(tools):
        p = "%s.tools[%d]" % (prefix, i)
        if not isinstance(t, dict) or t.get("kind") not in KINDS:
            bad.append("%s: an object with kind go, binary or submodule" % p)
            continue
        kind = t["kind"]
        extra = sorted(set(t) - set(KEYS[kind]))
        missing = [k for k in KEYS[kind] if not (isinstance(t.get(k), str) and t[k].strip())]
        if extra:
            bad.append("%s: unknown key %s (a %s entry has %s)" % (p, ", ".join(extra), kind, ", ".join(KEYS[kind])))
        if missing:
            bad.append("%s: %s needs %s, each a non-empty string" % (p, kind, ", ".join(missing)))
            continue
        name = t["name"]
        if kind == "go":
            if not GO_PATH.fullmatch(name) or "@" in name or ".." in name:
                bad.append("%s.name: a Go package path such as github.com/acme/lint/cmd/acme-lint (no @version: that is version)" % p)
            if not GO_VERSION.fullmatch(t["version"]):
                bad.append("%s.version: a tagged version such as v1.2.0 (never latest: the install is pinned)" % p)
        elif kind == "binary":
            if not BIN_NAME.fullmatch(name):
                bad.append("%s.name: the file name the binary gets in %s (letters, digits, . _ + -)" % (p, BIN_DIR))
            if not VERSION.fullmatch(t["version"]):
                bad.append("%s.version: a version text of at most 41 characters" % p)
            if not URL.fullmatch(t["url"]):
                bad.append("%s.url: an http(s) URL of the file itself (not an archive)" % p)
            if not SHA256.fullmatch(t["sha256"]):
                bad.append("%s.sha256: the 64 hex digits of the file's sha256 (lower case)" % p)
        else:
            if not SUB_NAME.fullmatch(name):
                bad.append("%s.name: the submodule's name in .gitmodules" % p)
            path = t["path"]
            if not (SUB_NAME.fullmatch(path) and not path.startswith("/") and ".." not in path.split("/") and not path.endswith("/") and "//" not in path):
                bad.append("%s.path: the submodule's path in the repository, relative, no .. segment" % p)
        key = (kind, t["path"] if kind == "submodule" else name)
        if key in seen:
            bad.append("%s: %s %s is listed twice" % (p, kind, key[1]))
        seen.add(key)
    return bad


def key_of(t):
    return (t["kind"], t["path"] if t["kind"] == "submodule" else t["name"])


def conflicts(roles):
    """Messages for two roles that pin the same tool differently (the lead installs one copy of each on a host)."""
    first, bad = {}, []
    for rn, cfg in sorted((roles or {}).items()):
        tl = cfg.get("tools") if isinstance(cfg, dict) else None
        if not isinstance(tl, list) or problems("roles.%s" % rn, tl):
            continue
        for t in tl:
            k = key_of(t)
            if k in first and first[k][1] != t:
                bad.append("roles.%s.tools and roles.%s.tools declare %s %s differently; one entry per tool, the same in every role"
                           % (first[k][0], rn, k[0], k[1]))
            first.setdefault(k, (rn, t))
    return bad


def declared(answers, role=None):
    """The tools of the project's roles (of one role with role), each entry with a roles list, the same tool once; a role whose list is not
    valid contributes nothing."""
    out, order = {}, []
    roles = (answers or {}).get("roles") if isinstance(answers, dict) else None
    for rn, cfg in sorted((roles or {}).items()):
        if role is not None and rn != role:
            continue
        tl = cfg.get("tools") if isinstance(cfg, dict) else None
        if not isinstance(tl, list) or problems("roles.%s" % rn, tl):
            continue
        for t in tl:
            k = key_of(t)
            if k not in out:
                out[k] = dict(t, roles=[])
                order.append(k)
            if rn not in out[k]["roles"]:
                out[k]["roles"].append(rn)
    return [out[k] for k in order]


def binary_name(t):
    """The file a tool is run as: a binary's name; for a go tool the last element of its path (a major-version suffix skipped)."""
    if t["kind"] == "binary":
        return t["name"]
    parts = [p for p in t["name"].split("/") if p]
    if len(parts) > 1 and re.fullmatch(r"v\d+", parts[-1]):
        parts.pop()
    return parts[-1] if parts else t["name"]


def label(t):
    if t["kind"] == "go":
        return "go %s@%s" % (t["name"], t["version"])
    if t["kind"] == "binary":
        return "binary %s %s" % (t["name"], t["version"])
    return "submodule %s" % t["path"]


# ---- where a tool is and what it is -------------------------------------------------------------------------------------------

def clean_path():
    return os.pathsep.join(p for p in os.environ.get("PATH", "").split(os.pathsep) if p.startswith("/")) or "/usr/bin:/bin"


def go_bin_dir():
    """Where go install puts binaries: GOBIN, else GOPATH/bin, else ~/go/bin."""
    if os.environ.get("GOBIN"):
        return os.environ["GOBIN"]
    gp = (os.environ.get("GOPATH") or "").split(os.pathsep)[0]
    return os.path.join(gp or os.path.expanduser("~/go"), "bin")


def find(t):
    """(file, on_path) of the tool's binary: on PATH, else in the directory it is installed to (go: GOBIN or GOPATH/bin; binary: ~/.local/bin)."""
    name = binary_name(t)
    hit = shutil.which(name, path=clean_path())
    if hit:
        return hit, True
    d = go_bin_dir() if t["kind"] == "go" else os.path.expanduser(BIN_DIR)
    f = os.path.join(d, name)
    return (f, False) if os.path.isfile(f) and os.access(f, os.X_OK) else (None, False)


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def go_version_of(file, go=None):
    """The module version a go binary was built from (go version -m), None when go is absent, or (False, text) when it is not a go build."""
    go = go or shutil.which("go", path=clean_path())
    if not go:
        return None
    try:
        r = subprocess.run([go, "version", "-m", file], capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=30, env=child_env())
    except (OSError, subprocess.SubprocessError):
        return (False, "go version -m failed")
    if r.returncode != 0:
        return (False, (r.stderr.strip().splitlines() or ["not a go build"])[-1][:120])
    for ln in r.stdout.splitlines():
        w = ln.strip().split("\t")
        if len(w) >= 3 and w[0] == "mod":
            return w[2]
    return (False, "go version -m names no module")


def child_env():
    env = {"PATH": clean_path(), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "GIT_TERMINAL_PROMPT": "0"}
    for k in ("HOME", "USER", "LOGNAME", "TMPDIR") + GO_KEEP:
        if os.environ.get(k):
            env[k] = os.environ[k]
    return env


def submodule_state(repo, path):
    """' ' (at the recorded commit), '+' (another commit), '-' (not initialised), 'U' (conflicts), None (no such submodule), or False (not a work tree)."""
    try:
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", repo, "submodule", "status", "--", path], capture_output=True, text=True,
                           stdin=subprocess.DEVNULL, env=dict(child_env(), GIT_OPTIONAL_LOCKS="0"), timeout=60)
    except (OSError, subprocess.SubprocessError):
        return False
    if r.returncode != 0:
        return False if "not a git repository" in r.stderr else None
    for ln in r.stdout.splitlines():
        m = re.match(r"^([ +\-U])[0-9a-f]{40,64} (.+?)(?: \(.*\))?$", ln)
        if m and m.group(2) == path:
            return m.group(1)
    return None


def status(t, repo=None):
    """(state, text) of one declared tool on this host: ok, missing, wrong (there, but not what is declared), path (the declared one, in a
    directory PATH lacks) or note (cannot be checked here). env check reports everything but ok and note; env apply installs missing and wrong."""
    where = "roles %s" % ", ".join(t.get("roles") or []) if t.get("roles") else "roles.<role>.tools"
    if t["kind"] == "submodule":
        if not repo:
            return "note", "%s: no repository to look in" % label(t)
        s = submodule_state(repo, t["path"])
        if s is False:
            return "note", "%s: %s is not a git work tree" % (label(t), repo)
        if s is None:
            return "missing", "no submodule at %s in the repository (%s; .gitmodules and HEAD name none)" % (t["path"], where)
        if s == "-":
            return "missing", "submodule %s is not initialised (git submodule update --init -- %s; a member clone gets it from qargi local prepare)" % (t["path"], t["path"])
        if s == " ":
            return "ok", "submodule %s is at the commit HEAD records" % t["path"]
        return "wrong", "submodule %s is %s (git submodule update -- %s)" % (t["path"], "at another commit than HEAD records" if s == "+" else "in a merge conflict", t["path"])
    name = binary_name(t)
    file, on_path = find(t)
    if file is None:
        return "missing", "%s is not installed (%s: %s; qargi env apply installs it)" % (name, where, label(t))
    if t["kind"] == "binary":
        if sha256_of(file) != t["sha256"]:
            return "wrong", "%s at %s is not the file %s pins (sha256 differs; version %s)" % (name, file, where, t["version"])
    else:
        v = go_version_of(file)
        if v is None:
            return "note", "%s is at %s; its version cannot be read: go is not on PATH" % (name, file)
        if isinstance(v, tuple):
            return "wrong", "%s at %s is not a go build of %s (%s)" % (name, file, t["name"], v[1])
        if v != t["version"]:
            return "wrong", "%s at %s is %s; %s pins %s" % (name, file, v, where, t["version"])
    if not on_path:
        return "path", "%s %s is installed in %s, which is not on PATH" % (name, t["version"], os.path.dirname(file))
    return "ok", "%s %s at %s" % (name, t["version"], file)


# ---- installing (qargi env apply) ----------------------------------------------------------------------------------------------

def install_go(t, go, cwd):
    """go install NAME@VERSION with go's own variables kept; (exit status, last lines of output)."""
    env = child_env()
    try:
        r = subprocess.run([go, "install", "%s@%s" % (t["name"], t["version"])], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return 1, "go install did not finish in 1800 s"
    except OSError as e:
        return 1, "could not run %s: %s" % (go, e.strerror or "error")
    return r.returncode, "\n".join((r.stdout + r.stderr).strip().splitlines()[-5:])


def install_binary(t):
    """Download the file to a temporary name next to its place, check its sha256, make it executable and move it to ~/.local/bin/NAME.
    (exit status, text): 0 and the path, else 1 and why; a file whose sha256 differs is removed and never installed."""
    import tempfile
    import urllib.request
    d = os.path.expanduser(BIN_DIR)
    os.makedirs(d, mode=0o755, exist_ok=True)
    dest = os.path.join(d, t["name"])
    fd, tmp = tempfile.mkstemp(prefix=".%s." % t["name"], dir=d)
    h, size = hashlib.sha256(), 0
    try:
        with os.fdopen(fd, "wb") as out:
            req = urllib.request.Request(t["url"], headers={"User-Agent": "qargi"})
            with urllib.request.urlopen(req, timeout=DOWNLOAD_TIMEOUT) as resp:  # noqa: S310 (an http(s) URL the answers declare; the sha256 is checked)
                for block in iter(lambda: resp.read(1 << 20), b""):
                    size += len(block)
                    if size > DOWNLOAD_CAP:
                        raise ValueError("more than %d MB" % (DOWNLOAD_CAP >> 20))
                    h.update(block)
                    out.write(block)
        got = h.hexdigest()
        if got != t["sha256"]:
            return 1, "the file at %s has sha256 %s, not the declared %s; not installed" % (t["url"], got, t["sha256"])
        os.chmod(tmp, 0o755)
        os.replace(tmp, dest)
    except (OSError, ValueError) as e:
        return 1, "could not download %s: %s" % (t["url"], getattr(e, "reason", None) or str(e) or e.__class__.__name__)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return 0, dest


# ---- qargi local prepare: the submodules in a member's clone -------------------------------------------------------------------------

def git(*args, cwd=None, git_dir=None):
    """(exit, stdout, stderr) of a git command: no prompt, no fsmonitor."""
    cmd = ["git", "-c", "core.fsmonitor=false", "-c", "protocol.file.allow=always"] + (["--git-dir", git_dir] if git_dir else []) + list(args)
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, env=dict(child_env(), GIT_OPTIONAL_LOCKS="0"), timeout=GIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as e:
        return 1, "", str(e)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


def gitmodules_names(clone):
    """{path: name} of the clone's .gitmodules."""
    rc, out, _ = git("config", "-f", ".gitmodules", "--get-regexp", r"^submodule\..*\.path$", cwd=clone)
    names = {}
    for ln in out.splitlines() if rc == 0 else []:
        k, _, v = ln.partition(" ")
        m = re.fullmatch(r"submodule\.(.+)\.path", k)
        if m and v:
            names[v] = m.group(1)
    return names


def source_git_dir(source, path, name):
    """The git directory of the lead's copy of a submodule: the checkout at REPO/PATH, else the modules directory of its name; None when neither is one."""
    sub = os.path.join(source, path)
    if os.path.isdir(sub):
        rc, top, _ = git("rev-parse", "--show-toplevel", cwd=sub)
        if rc == 0 and os.path.realpath(top) == os.path.realpath(sub):
            rc, gd, _ = git("rev-parse", "--absolute-git-dir", cwd=sub)
            if rc == 0:
                return gd
    for flag in ("--absolute-git-dir", "--git-common-dir"):
        rc, gd, _ = git("rev-parse", "--path-format=absolute", flag, cwd=source)
        cand = os.path.join(gd, "modules", name) if rc == 0 and gd else ""
        if cand and os.path.isfile(os.path.join(cand, "HEAD")):
            return cand
    return None


def checkout(entries, clone, copies, source=None):
    """Check the submodule entries out in clone from the lead's copies; (paths checked out, notes)."""
    done, notes = [], []
    names = gitmodules_names(clone)
    for t in entries:
        path, declared_name = t["path"], t["name"]
        gname = names.get(path)
        if gname is None:
            notes.append("submodule %s (%s) is not in the .gitmodules of the base branch; not checked out" % (path, declared_name))
            continue
        rc, out, _ = git("ls-tree", "-d", "HEAD", "--", path, cwd=clone)
        m = re.match(r"^160000 commit ([0-9a-f]{40,64})\t", out) if rc == 0 else None
        if not m:
            notes.append("submodule %s: HEAD of the base branch records no submodule commit at that path; not checked out" % path)
            continue
        sha = m.group(1)
        if not source:
            notes.append("submodule %s: the run was cloned from a URL, so its objects are not on this host and are not fetched; not checked out" % path)
            continue
        src = source_git_dir(source, path, gname)
        if src is None:
            notes.append("submodule %s is not initialised in %s; nothing is fetched: git -C %s submodule update --init -- %s, then prepare again" % (path, source, source, path))
            continue
        rc, _, _ = git("cat-file", "-e", sha + "^{commit}", git_dir=src)
        if rc != 0:
            notes.append("submodule %s: the commit HEAD records (%s) is not in %s; nothing is fetched: git -C %s/%s fetch, then prepare again" % (path, sha[:12], src, source, path))
            continue
        copy = os.path.join(copies, gname + ".git")
        os.makedirs(os.path.dirname(copy), exist_ok=True)
        steps = (("clone", "-q", "--mirror", "--no-hardlinks", src, copy), ("--git-dir", copy, "update-ref", "refs/heads/qargi-pin", sha),
                 ("--git-dir", copy, "remote", "remove", "origin"), ("-C", clone, "config", "submodule.%s.url" % gname, copy),
                 ("-C", clone, "submodule", "update", "-q", "--init", "--", path), ("-C", os.path.join(clone, path), "remote", "set-url", "--push", "origin", "DISABLED"))
        failed = None
        for step in steps:
            rc, _, err = git(*step)
            if rc != 0:
                failed = (step, err)
                break
        if failed:
            notes.append("submodule %s: git %s failed (%s); not checked out" % (path, " ".join(failed[0][:3]), (failed[1].splitlines() or ["no message"])[-1][:160]))
            continue
        done.append(path)
    return done, notes


def main(argv):
    if argv[:1] != ["checkout"]:
        print("usage: tools.py checkout --answers FILE --role ROLE --clone DIR --copies DIR [--source REPO]", file=sys.stderr)
        return 2
    opts, i = {}, 1
    while i < len(argv):
        if argv[i] in ("--answers", "--role", "--clone", "--copies", "--source") and i + 1 < len(argv):
            opts[argv[i]] = argv[i + 1]
            i += 2
        else:
            print("usage: tools.py checkout --answers FILE --role ROLE --clone DIR --copies DIR [--source REPO]", file=sys.stderr)
            return 2
    if any(k not in opts for k in ("--answers", "--role", "--clone", "--copies")):
        print("usage: tools.py checkout --answers FILE --role ROLE --clone DIR --copies DIR [--source REPO]", file=sys.stderr)
        return 2
    try:
        with open(opts["--answers"]) as f:
            answers = json.load(f)
    except (OSError, ValueError) as e:
        print("qargi: note: the answers could not be read (%s); no submodule checked out" % e, file=sys.stderr)
        return 0
    entries = [t for t in declared(answers, opts["--role"]) if t["kind"] == "submodule"]
    if not entries:
        return 0
    done, notes = checkout(entries, opts["--clone"], opts["--copies"], opts.get("--source"))
    for n in notes:
        print("qargi: note: " + n, file=sys.stderr)
    if done:
        print("SUBMODULES=" + ",".join(done))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
