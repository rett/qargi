#!/usr/bin/env python3
"""Claude Code adapter for qargi packs: render a project's enabled skills and tools into a state directory
that `claude --add-dir DIR` loads, with a manifest and a drift check.

Called by packs.sh, which gathers the facts only the shell knows (links, review, hashes) into an inputs file:
  {project, state, home, checkout, packs:[{kind,name,path,sha256,approved,review_ok,exists,roles[]}]}

  packs_claude.py plan   INPUTS TOKENFILE   stage the tree, print the plan, write the plan token; nothing is replaced
  packs_claude.py swap   INPUTS             replace the live directory with the staged one (atomic exchange)
  packs_claude.py check  INPUTS             read only; exit 1 on any finding

Layout under <state>/claude/<project>/: .claude/skills/<name>/..., mcp.json, settings.json, MANIFEST.json.
"""
import ctypes
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
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
    live = os.path.join(base, project)
    if os.path.islink(live):
        die("the output directory is a symbolic link; refusing")
    if not os.path.realpath(live).startswith(state + os.sep):
        die("the output directory resolves outside the state directory; refusing")
    return state, live, os.path.join(base, "." + project + ".new")


def tree_files(root):
    """{relpath: sha256} of every regular file under root except the manifest; a symlink is an error entry."""
    out = {}
    for d, dirs, files in os.walk(root):
        for n in dirs + files:
            p = os.path.join(d, n)
            if os.path.islink(p):
                out[os.path.relpath(p, root)] = "SYMLINK"
        for n in files:
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root)
            if rel == "MANIFEST.json" or os.path.islink(p):
                continue
            with open(p, "rb") as f:
                out[rel] = sha(f.read())
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
    return bad


def render(inp, out):
    """Write the tree into out; returns the manifest's pack list and the tool details."""
    os.makedirs(os.path.join(out, ".claude", "skills"), mode=0o755)
    packs, servers, allow, ask, creds = [], {}, [], [], []
    for p in sorted(inp["packs"], key=lambda x: (x["kind"], x["name"])):
        entry = {"kind": p["kind"], "name": p["name"], "sha256": p["sha256"], "roles": sorted(p["roles"]), "files": {}}
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
                    os.makedirs(os.path.dirname(target), mode=0o755, exist_ok=True)
                    with open(f, "rb") as fh:
                        data = fh.read()
                    with open(target, "wb") as fh:
                        fh.write(data)
                    os.chmod(target, 0o755 if os.stat(f).st_mode & 0o111 else 0o644)
                    entry["files"][os.path.join(".claude", "skills", p["name"], rel)] = sha(data)
        else:
            t = load(p["path"])
            servers[p["name"]] = {"type": "http", "url": t["url"]}
            for tool, pol in sorted((t.get("tools") or {}).items()):
                rule = "mcp__%s__%s" % (p["name"], tool)
                if pol == "always_allow":
                    allow.append(rule)
                elif pol == "always_ask":
                    ask.append(rule)
            if t.get("vault_ids"):
                creds.append(p["name"])
        packs.append(entry)
    shared = {}
    if servers:
        for name, obj in (("mcp.json", {"mcpServers": servers}),
                          ("settings.json", {"permissions": {"allow": allow, "ask": ask, "deny": []}})):
            data = (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()
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


def cmd_plan(inp, tokenfile):
    bad = vet(inp, True)
    if bad:
        die("refusing to render:\n  " + "\n  ".join(bad))
    state, live, stage = roots(inp)
    shutil.rmtree(stage, ignore_errors=True)
    os.makedirs(os.path.dirname(stage), exist_ok=True)
    os.makedirs(stage, mode=0o755)
    try:
        packs, shared, creds = render(inp, stage)
    except SystemExit:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    old = None
    mpath = os.path.join(live, "MANIFEST.json")
    if os.path.isfile(mpath):
        try:
            old = load(mpath)
        except ValueError:
            old = None
    manifest = {"schema": 1, "project": inp["project"], "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "role_scoping": "advisory", "packs": packs, "files": shared}
    if old and identity(old) == identity(manifest):
        manifest["generated"] = old.get("generated", manifest["generated"])
    with open(os.path.join(stage, "MANIFEST.json"), "w") as fh:
        fh.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    os.chmod(os.path.join(stage, "MANIFEST.json"), 0o644)

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
        elif oldp[k]["sha256"] != n["sha256"] or oldp[k]["roles"] != n["roles"] or oldp[k]["files"] != n["files"]:
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
    identity_bytes = json.dumps([identity(manifest), identity(old) if old else None], sort_keys=True).encode()
    with open(tokenfile, "w") as fh:
        fh.write(sha(identity_bytes)[:12])


def cmd_swap(inp):
    state, live, stage = roots(inp)
    if not os.path.isdir(stage):
        die("nothing staged; run the plan first")
    if not os.path.exists(live):
        os.rename(stage, live)
        return
    try:  # atomic exchange of the two directories (Linux renameat2 RENAME_EXCHANGE); the old tree ends up at stage
        libc = ctypes.CDLL(None, use_errno=True)
        ok = libc.renameat2(-100, stage.encode(), -100, live.encode(), 2) == 0
    except (OSError, AttributeError):
        ok = False
    if not ok:
        old = stage + ".old"
        shutil.rmtree(old, ignore_errors=True)
        os.rename(live, old)
        os.rename(stage, live)
        stage = old
    shutil.rmtree(stage, ignore_errors=True)


def cmd_check(inp):
    state, live, stage = roots(inp)
    findings = []
    mpath = os.path.join(live, "MANIFEST.json")
    if not os.path.isfile(mpath):
        print("FAIL manifest missing: %s (run: qargi packs apply --target claude-code %s)" % (mpath, inp["project"]))
        sys.exit(1)
    try:
        m = load(mpath)
    except ValueError:
        print("FAIL manifest is not valid JSON: " + mpath)
        sys.exit(1)
    findings += ["library: " + b for b in vet(inp, False)]
    mp = {(p["kind"], p["name"]): p for p in m.get("packs", [])}
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
    for p in m.get("packs", []):
        want.update(p["files"])
    have = tree_files(live)
    for rel in sorted(set(want) | set(have)):
        if rel not in have:
            findings.append("rendered: missing file " + rel)
        elif rel not in want:
            findings.append("rendered: extra file " + rel)
        elif have[rel] != want[rel]:
            findings.append("rendered: file differs from the manifest: " + rel)
    findings += ["shadowing: " + s for s in shadows(inp, m.get("packs", []))]
    if findings:
        for f in findings:
            print("FAIL " + f)
        sys.exit(1)
    print("ok   %s: %d packs, rendered tree matches the manifest, nothing shadowed" % (inp["project"], len(mp)))


def main():
    if len(sys.argv) < 3:
        die("usage: packs_claude.py plan|swap|check INPUTS [TOKENFILE]")
    inp = load(sys.argv[2])
    if sys.argv[1] == "plan":
        cmd_plan(inp, sys.argv[3])
    elif sys.argv[1] == "swap":
        cmd_swap(inp)
    elif sys.argv[1] == "check":
        cmd_check(inp)
    else:
        die("unknown verb " + sys.argv[1])


if __name__ == "__main__":
    main()
