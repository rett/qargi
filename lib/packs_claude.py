#!/usr/bin/env python3
"""Claude Code adapter for qargi packs: render a project's enabled skills and tools into a state directory
that `claude --add-dir DIR` loads, with a manifest and a drift check.

Called by packs.sh, which gathers the facts only the shell knows (links, review, hashes) into an inputs file:
  {project, state, home, checkout, packs:[{kind,name,path,sha256,approved,review_ok,exists,roles[]}]}

  packs_claude.py prep   INPUTS             validate the output root, create claude/ (the caller then takes the lock)
  packs_claude.py plan   INPUTS TOKENFILE   stage the tree (a private directory), print the plan, write the plan
                                            token and TOKENFILE.stage; nothing is replaced
  packs_claude.py swap   INPUTS STAGEFILE TOKEN   install the staged tree if it is the one the token was made for
  packs_claude.py check  INPUTS             read only; exit 1 on any finding

Layout under <state>/claude/<project>/: .claude/skills/<name>/..., mcp.json, settings.json, MANIFEST.json.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
from datetime import datetime, timezone

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
TOOL_RE = re.compile(r'^[A-Za-z0-9_.-]{1,64}$')
SKIP = ".pack.json"


def die(msg):
    print("qargi: " + msg, file=sys.stderr)
    sys.exit(1)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    with open(path) as f:
        return json.load(f)


def roots(inp):
    """(state realpath, live dir, staging dir); refuses anything that resolves outside the state directory."""
    project = inp["project"]
    if not NAME_RE.match(project) or ".." in project:
        die("not a project name: " + project)
    state = os.path.realpath(inp["state"])
    base = os.path.join(state, "claude")
    if os.path.islink(base) or (os.path.exists(base) and not os.path.realpath(base).startswith(state + os.sep)):
        die("the output root resolves outside the state directory; refusing")
    if os.path.lexists(base) and not os.path.isdir(base):
        die("the output root %s is not a directory; refusing to replace it" % base)
    live = os.path.join(base, project)
    if os.path.islink(live):
        die("the output directory is a symbolic link; refusing")
    if os.path.lexists(live) and not os.path.isdir(live):
        die("the output directory %s is not a directory; refusing to replace it" % live)
    if not os.path.realpath(live).startswith(state + os.sep):
        die("the output directory resolves outside the state directory; refusing")
    return state, live, base


def stage_re(project):
    """Names of staging leftovers of this project: the old fixed name, its fallback-swap leftover, and mkdtemp names."""
    p = re.escape(project)
    return re.compile(r"^\.%s\.new(\.old|\.[A-Za-z0-9_]{8}(\.old)?)?$" % p)


def sweep(base, project):
    """Remove staging leftovers of crashed runs without following links. The caller holds the project's lock."""
    rx = stage_re(project)
    for n in os.listdir(base):
        if rx.match(n):
            rmpath(os.path.join(base, n))


def rmpath(p):
    try:
        if stat.S_ISDIR(os.lstat(p).st_mode):
            shutil.rmtree(p, ignore_errors=True)
        else:
            os.unlink(p)
    except FileNotFoundError:
        pass


def mkdirs(path, stop):
    """Create path and any missing parents below stop, each 0755 whatever the umask is."""
    todo = []
    while path != stop and not os.path.isdir(path):
        todo.append(path)
        path = os.path.dirname(path)
    for d in reversed(todo):
        os.mkdir(d)
        os.chmod(d, 0o755)


def scan(root):
    """(hashes, modes, perms): {relpath: sha256 or SYMLINK} of everything under root except the manifest, {relpath:
    "755" or "644"} of regular files, and findings about group- or world-writable directories and files."""
    out, modes, perms = {}, {}, []

    def writable(p, rel, what):
        m = os.lstat(p).st_mode
        if m & 0o022:
            perms.append("permissions: %s %s is group- or world-writable (%o)" % (what, rel, stat.S_IMODE(m)))

    writable(root, ".", "render directory")
    for d, dirs, files in os.walk(root):
        for n in dirs:
            p = os.path.join(d, n)
            if os.path.islink(p):
                out[os.path.relpath(p, root)] = "SYMLINK"
            else:
                writable(p, os.path.relpath(p, root), "directory")
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if os.path.islink(p):
                out[rel] = "SYMLINK"
                continue
            writable(p, rel, "file")
            if rel == "MANIFEST.json":
                continue
            try:
                with open(p, "rb") as f:
                    out[rel] = sha(f.read())
            except OSError:
                out[rel] = "UNREADABLE"
            modes[rel] = "755" if os.lstat(p).st_mode & 0o111 else "644"
    return out, modes, perms


def lib_hashes(p):
    """{rendered relpath: sha256} of what a skill pack's library directory should render to."""
    out = {}
    src = p["path"]
    for d, dirs, files in os.walk(src):
        for n in files:
            f = os.path.join(d, n)
            if os.path.islink(f) or (n == SKIP and d == src):
                continue
            with open(f, "rb") as fh:
                out[os.path.join(".claude", "skills", p["name"], os.path.relpath(f, src))] = sha(fh.read())
    return out


def vet(inp, strict):
    """Findings about the library side of each pack: missing, failing review, changed since approved."""
    bad = []
    for p in inp["packs"]:
        e = p["kind"] + ":" + p["name"]
        if not NAME_RE.match(p["name"]) or ".." in p["name"]:
            bad.append("%s: not a pack name" % e)
        elif not p["exists"]:
            bad.append("%s: linked but not in the library" % e)
        elif not p["review_ok"]:
            bad.append("%s: fails its review (qargi %s check)" % (e, p["kind"]))
        elif p["approved"] and p["approved"] != p["sha256"]:
            bad.append("%s: library drift, changed since it was approved (%s -> %s); review it and seal it again"
                       % (e, p["approved"], p["sha256"]))
    seen = {}
    for p in inp["packs"]:
        seen.setdefault(p["name"], set()).add(p["kind"])
    for n, kinds in sorted(seen.items()):
        if len(kinds) > 1:
            bad.append("%s: a skill and a tool pack have this name (names are globally unique); unlink one" % n)
    return bad


def check_front_matter(name, data):
    """Refuse a SKILL.md whose front matter would make Claude Code load it under another name, or that never ends."""
    lines = data.decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return
    names, closed = [], False
    for ln in lines[1:]:
        if ln.strip() == "---":
            closed = True
            break
        m = re.match(r"^name\s*:\s*(.*?)\s*$", ln)
        if m:
            names.append(m.group(1).strip("'\""))
    if not closed:
        die("skill %s: the front matter of SKILL.md is never closed (no second ---); refusing" % name)
    if len(names) > 1:
        die("skill %s: SKILL.md has %d name: keys in its front matter; refusing" % (name, len(names)))
    if names and names[0] != name:
        die("skill %s: SKILL.md says name: %s, which differs from the pack name; refusing" % (name, names[0]))


def tool_parts(p):
    """(server entry, allow rules, ask rules) of one tool pack; refuses tool names that are not plain names."""
    t = load(p["path"])
    allow, ask = [], []
    for tool, pol in sorted((t.get("tools") or {}).items()):
        if not isinstance(tool, str) or not TOOL_RE.match(tool):
            die("tool %s: tool name %r is not a plain name (letters, digits, _ . -, 1-64 characters); a rule with a "
                "wildcard or quote would defeat the allowlist; refusing" % (p["name"], tool))
        rule = "mcp__%s__%s" % (p["name"], tool)
        if pol == "always_allow":
            allow.append(rule)
        elif pol == "always_ask":
            ask.append(rule)
    return {"type": "http", "url": t["url"]}, allow, ask, bool(t.get("vault_ids"))


def shared_files(servers, allow, ask):
    """{name: bytes} of mcp.json and settings.json for the tool packs, or {} when there are none."""
    if not servers:
        return {}
    return {name: (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
            for name, obj in (("mcp.json", {"mcpServers": servers}),
                              ("settings.json", {"permissions": {"allow": allow, "ask": ask, "deny": []}}))}


def render(inp, out):
    """Write the tree into out; returns the manifest's pack list and the tool details."""
    mkdirs(os.path.join(out, ".claude", "skills"), os.path.dirname(out))
    packs, servers, allow, ask, creds = [], {}, [], [], []
    for p in sorted(inp["packs"], key=lambda x: (x["kind"], x["name"])):
        entry = {"kind": p["kind"], "name": p["name"], "sha256": p["sha256"], "roles": sorted(p["roles"]), "files": {}, "modes": {}}
        if p["kind"] == "skill":
            src, dst = p["path"], os.path.join(out, ".claude", "skills", p["name"])
            for d, dirs, files in os.walk(src):
                dirs.sort()
                for n in dirs:
                    if os.path.islink(os.path.join(d, n)):
                        die("symbolic link in skill %s; refusing" % p["name"])
                for n in sorted(files):
                    f = os.path.join(d, n)
                    if os.path.islink(f):
                        die("symbolic link in skill %s; refusing" % p["name"])
                    if n == SKIP and d == src:
                        continue
                    rel = os.path.relpath(f, src)
                    target = os.path.join(dst, rel)
                    mkdirs(os.path.dirname(target), out)
                    try:
                        with open(f, "rb") as fh:
                            data = fh.read()
                        mode = 0o755 if os.stat(f).st_mode & 0o111 else 0o644
                    except OSError as e:
                        die("cannot read %s in skill %s: %s; refusing" % (rel, p["name"], e.strerror or e))
                    if rel == "SKILL.md":
                        check_front_matter(p["name"], data)
                    with open(target, "wb") as fh:
                        fh.write(data)
                    os.chmod(target, mode)
                    key = os.path.join(".claude", "skills", p["name"], rel)
                    entry["files"][key] = sha(data)
                    entry["modes"][key] = "%o" % mode
        else:
            try:
                server, a, k, cred = tool_parts(p)
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
                die("tool %s: cannot be read as a tool pack (%s); refusing" % (p["name"], e))
            servers[p["name"]] = server
            allow += a
            ask += k
            if cred:
                creds.append(p["name"])
        packs.append(entry)
    shared = {}
    for name, data in shared_files(servers, allow, ask).items():
        with open(os.path.join(out, name), "wb") as fh:
            fh.write(data)
        os.chmod(os.path.join(out, name), 0o644)
        shared[name] = sha(data)
    return packs, shared, creds


def shadows(inp, packs):
    homes = [("~/.claude/skills", os.path.join(inp["home"], ".claude", "skills"))]
    if inp.get("checkout") and os.path.isabs(inp["checkout"]):
        homes.append(("the project checkout's .claude/skills", os.path.join(inp["checkout"], ".claude", "skills")))
    out = []
    for p in packs:
        if p["kind"] != "skill":
            continue
        for label, d in homes:
            if os.path.lexists(os.path.join(d, p["name"])):
                out.append("skill %s is also in %s, which would override or hide the rendered one" % (p["name"], label))
    return out


def identity(manifest):
    """The part of a manifest that says what is rendered (not when)."""
    return {k: v for k, v in manifest.items() if k != "generated"}


def valid_manifest(m):
    """None when m has the shape this adapter writes, else a sentence saying what is wrong."""
    if not isinstance(m, dict):
        return "the manifest is not a JSON object"
    if m.get("schema") != 1:
        return "schema is not 1"
    if not isinstance(m.get("project"), str):
        return "project is not a string"
    if not isinstance(m.get("packs"), list):
        return "packs is not a list"
    for i, p in enumerate(m["packs"]):
        if not isinstance(p, dict):
            return "packs[%d] is not an object" % i
        for k in ("kind", "name", "sha256"):
            if not isinstance(p.get(k), str):
                return "packs[%d].%s is not a string" % (i, k)
        if not isinstance(p.get("roles"), list) or not all(isinstance(r, str) for r in p["roles"]):
            return "packs[%d].roles is not a list of strings" % i
        for k in ("files", "modes"):
            v = p.get(k, {})
            if not isinstance(v, dict) or not all(isinstance(a, str) and isinstance(b, str) for a, b in v.items()):
                return "packs[%d].%s is not an object of strings" % (i, k)
        if "files" not in p:
            return "packs[%d].files is missing" % i
    f = m.get("files", {})
    if not isinstance(f, dict) or not all(isinstance(a, str) and isinstance(b, str) for a, b in f.items()):
        return "files is not an object of strings"
    return None


def read_manifest(live):
    """The live manifest, or None when there is none or it does not have the right shape."""
    mpath = os.path.join(live, "MANIFEST.json")
    if not os.path.isfile(mpath):
        return None
    try:
        m = load(mpath)
    except (ValueError, OSError):
        return None
    return m if valid_manifest(m) is None else None


def token_of(manifest, old):
    return sha(json.dumps([identity(manifest), identity(old) if old else None], sort_keys=True).encode())[:12]


def cmd_prep(inp):
    state, live, base = roots(inp)
    os.makedirs(base, exist_ok=True)


def cmd_plan(inp, tokenfile):
    bad = vet(inp, True)
    if bad:
        die("refusing to render:\n  " + "\n  ".join(bad))
    state, live, base = roots(inp)
    os.makedirs(base, exist_ok=True)
    sweep(base, inp["project"])
    stage = tempfile.mkdtemp(prefix="." + inp["project"] + ".new.", dir=base)
    done = False
    try:
        os.chmod(stage, 0o755)
        packs, shared, creds = render(inp, stage)
        old = read_manifest(live)
        manifest = {"schema": 1, "project": inp["project"], "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "role_scoping": "advisory", "packs": packs, "files": shared}
        if old and identity(old) == identity(manifest):
            manifest["generated"] = old.get("generated", manifest["generated"])
        with open(os.path.join(stage, "MANIFEST.json"), "w") as fh:
            fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        os.chmod(os.path.join(stage, "MANIFEST.json"), 0o644)
        tok = token_of(manifest, old)
        with open(tokenfile + ".stage", "w") as fh:
            json.dump({"stage": stage, "token": tok}, fh)
        report(inp, live, manifest, old, creds)
        with open(tokenfile, "w") as fh:
            fh.write(tok)
        done = True
    finally:
        if not done:
            rmpath(stage)


def report(inp, live, manifest, old, creds):
    packs, shared = manifest["packs"], manifest["files"]
    oldp = {(p["kind"], p["name"]): p for p in (old or {}).get("packs", [])}
    newp = {(p["kind"], p["name"]): p for p in packs}
    print("claude-code target for %s -> %s" % (inp["project"], live))
    print("  role scoping is advisory: Claude Code cannot enforce per-role skills; the set is the union over the project's roles")
    if not old:
        print("  no earlier render")
    changes = 0
    for k in sorted(newp):
        n = newp[k]
        if k not in oldp:
            tag = "added"
        elif (oldp[k]["sha256"] != n["sha256"] or oldp[k]["roles"] != n["roles"] or oldp[k]["files"] != n["files"]
              or oldp[k].get("modes", {}) != n["modes"]):
            tag = "changed"
        else:
            continue
        changes += 1
        print("  %-8s %s %s  sha256 %s  roles %s" % (tag, k[0], k[1], n["sha256"], ",".join(n["roles"])))
        for rel, h in sorted(n["files"].items()):
            print("             %s  %s" % (h[:12], rel))
    for k in sorted(oldp):
        if k not in newp:
            changes += 1
            print("  removed  %s %s  (was sha256 %s)" % (k[0], k[1], oldp[k]["sha256"]))
    if not changes:
        print("  no change in packs" if old else "  no packs enabled")
    if old and old.get("files") != shared:
        print("  tool files (mcp.json, settings.json) differ from the last render")
    for k in sorted(newp):
        if k[0] == "tool":
            print("  tool entry: mcp__%s__*  (see mcp.json and settings.json)" % k[1])
    if creds:
        print("  needs credentials you configure yourself (vault_ids cannot authenticate locally): " + ", ".join(creds))
    for w in shadows(inp, packs):
        print("  WARNING: " + w)


def cmd_swap(inp, stagefile, token):
    state, live, base = roots(inp)
    try:
        info = load(stagefile)
        stage = info["stage"]
    except (OSError, ValueError, KeyError, TypeError):
        die("nothing staged; run the plan first")
    if (os.path.dirname(stage) != base or not stage_re(inp["project"]).match(os.path.basename(stage))
            or os.path.islink(stage) or not os.path.isdir(stage)):
        die("nothing staged; run the plan first")
    # Only the tree this invocation built and the user approved goes live: its manifest (without the timestamp),
    # together with the live one, must hash to the approved token, and its files must be what that manifest says.
    try:
        staged = load(os.path.join(stage, "MANIFEST.json"))
    except (OSError, ValueError):
        die("the staged manifest is unreadable; refusing to install it")
    if valid_manifest(staged) is not None or info.get("token") != token or token_of(staged, read_manifest(live)) != token:
        die("the staged tree is not the one the approved plan describes (or the live render changed since); nothing was installed")
    have, modes, _ = scan(stage)
    want = dict(staged.get("files", {}))
    wmodes = {}
    for p in staged["packs"]:
        want.update(p["files"])
        wmodes.update(p.get("modes", {}))
    if have != want or any(modes[r] != wmodes.get(r, "644") for r in modes):
        die("the staged files differ from the approved manifest; nothing was installed")
    if not os.path.lexists(live):
        os.rename(stage, live)
        return
    try:  # atomic exchange of the two directories (Linux renameat2 RENAME_EXCHANGE); the old tree ends up at stage
        libc = ctypes.CDLL(None, use_errno=True)
        ok = libc.renameat2(-100, stage.encode(), -100, live.encode(), 2) == 0
    except (OSError, AttributeError):
        ok = False
    if not ok:
        old = stage + ".old"
        rmpath(old) if os.path.lexists(old) else None
        os.rename(live, old)
        os.rename(stage, live)
        stage = old
    rmpath(stage)


def cmd_check(inp):
    state, live, base = roots(inp)
    findings = []
    mpath = os.path.join(live, "MANIFEST.json")
    if not os.path.isfile(mpath):
        print("FAIL manifest missing: %s (run: qargi packs apply --target claude-code %s)" % (mpath, inp["project"]))
        sys.exit(1)
    try:
        m = load(mpath)
    except (ValueError, OSError):
        print("FAIL manifest is not valid JSON: " + mpath)
        sys.exit(1)
    err = valid_manifest(m)
    if err:
        print("FAIL manifest has the wrong shape: %s (%s)" % (err, mpath))
        print("qargi: the manifest %s is malformed; re-apply to rewrite it" % mpath, file=sys.stderr)
        sys.exit(1)
    findings += ["library: " + b for b in vet(inp, False)]
    if m["project"] != inp["project"]:
        findings.append("manifest: project is %r, expected %r" % (m["project"], inp["project"]))
    if m.get("role_scoping") != "advisory":
        findings.append("manifest: role_scoping is %r, expected 'advisory'" % (m.get("role_scoping"),))
    mp = {(p["kind"], p["name"]): p for p in m["packs"]}
    cur = {(p["kind"], p["name"]): p for p in inp["packs"]}
    for k in sorted(cur):
        if k not in mp:
            findings.append("enablement: %s %s is enabled now but not in the render" % k)
        else:
            if sorted(cur[k]["roles"]) != mp[k]["roles"]:
                findings.append("enablement: %s %s roles changed (%s -> %s)" % (k + (",".join(mp[k]["roles"]), ",".join(sorted(cur[k]["roles"])))))
            if cur[k]["exists"] and cur[k]["sha256"] != mp[k]["sha256"]:
                findings.append("library: %s %s changed since it was rendered (%s -> %s)" % (k + (mp[k]["sha256"], cur[k]["sha256"])))
    for k in sorted(mp):
        if k not in cur:
            findings.append("enablement: %s %s is rendered but no longer enabled" % k)
    want = dict(m.get("files", {}))
    wmodes = {}
    for p in m["packs"]:
        want.update(p["files"])
        wmodes.update(p.get("modes", {}))
    have, modes, perms = scan(live)
    for rel in sorted(set(want) | set(have)):
        if rel not in have:
            findings.append("rendered: missing file " + rel)
        elif rel not in want:
            findings.append("rendered: extra file " + rel)
        elif have[rel] != want[rel]:
            findings.append("rendered: file differs from the manifest: " + rel)
        elif modes.get(rel, "644") != wmodes.get(rel, "644"):
            findings.append("rendered: mode of %s is %s, the manifest says %s" % (rel, modes.get(rel), wmodes.get(rel, "644")))
    # the library is the one witness the render cannot edit together with its manifest
    for k, p in sorted(cur.items()):
        if k[0] == "skill" and p["exists"] and p["review_ok"]:
            try:
                for rel, h in sorted(lib_hashes(p).items()):
                    if rel in have and have[rel] != h:
                        findings.append("rendered: file differs from the library copy: " + rel)
            except OSError as e:
                findings.append("library: cannot read skill %s: %s" % (k[1], e.strerror or e))
    tools = [p for p in inp["packs"] if p["kind"] == "tool"]
    if tools and all(p["exists"] and p["review_ok"] for p in tools):
        try:
            servers, allow, ask = {}, [], []
            for p in tools:
                servers[p["name"]], a, kk, _ = tool_parts(p)
                allow += a
                ask += kk
            for name, data in shared_files(servers, sorted(allow), sorted(ask)).items():
                if name in have and have[name] != sha(data):
                    findings.append("rendered: file differs from the library copy: " + name)
        except (SystemExit, OSError, ValueError, KeyError, TypeError):
            findings.append("library: a tool pack cannot be rendered")
    findings += perms
    findings += ["shadowing: " + s for s in shadows(inp, m["packs"])]
    if findings:
        for f in findings:
            print("FAIL " + f)
        sys.exit(1)
    print("ok   %s: %d packs, rendered tree matches the manifest, nothing shadowed" % (inp["project"], len(mp)))


def main():
    if len(sys.argv) < 3:
        die("usage: packs_claude.py prep|plan|swap|check INPUTS [TOKENFILE | STAGEFILE TOKEN]")
    try:
        inp = load(sys.argv[2])
        verb = sys.argv[1]
        if verb == "prep":
            cmd_prep(inp)
        elif verb == "plan" and len(sys.argv) > 3:
            cmd_plan(inp, sys.argv[3])
        elif verb == "swap" and len(sys.argv) > 4:
            cmd_swap(inp, sys.argv[3], sys.argv[4])
        elif verb == "check":
            cmd_check(inp)
        else:
            die("unknown verb or missing argument: " + verb)
    except OSError as e:
        die("%s: %s" % (e.filename or "file system error", e.strerror or e))


if __name__ == "__main__":
    main()
