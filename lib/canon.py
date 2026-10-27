#!/usr/bin/env python3
"""Canon planner: pure functions from a store's memories to a list of steps.

Subcommands (all read JSON lines of {"id","path","content"} from --store and print JSON):
  plan    --kind memory|reference --project P --roles dev,docs --default-role R --store F --seed D
  check   --kind K --project P --roles ... --store F
  import  --map docs-v0 --role R --src F --memory F --reference F --seed D
The executor (canon.sh) applies the steps with `ant`. Nothing here talks to the API.
"""
import argparse, datetime, json, re, sys

LATEST = 1
KINDS = ("memory", "reference")


def load(path):
    out = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = json.loads(line)
            if m.get("type", "memory") != "memory":
                continue
            out[m["path"]] = m
    return out


def canon_marker(kind, project, roles, version, frm=None, today=None):
    lines = ["# Canon", "", "canon: %d" % version, "kind: %s" % kind, "project: %s" % project,
             "roles: %s" % " ".join(roles)]
    if frm is not None:
        lines.append("reconciled: %s from %s" % (today, frm))
    return "\n".join(lines) + "\n"


def parse_marker(text):
    d = {}
    for l in text.splitlines():
        m = re.match(r"^(canon|kind|project|roles|reconciled):\s*(.*)$", l)
        if m:
            d[m.group(1)] = m.group(2).strip()
    return d


def detect(kind, mems):
    """-> (state, why). state is LATEST (conforms), "draft" (a marker from an earlier
    draft of this spec), "legacy" (the layout before the canon) or "unknown"."""
    if "/CANON.md" in mems:
        d = parse_marker(mems["/CANON.md"]["content"])
        try:
            n = int(d.get("canon", ""))
        except ValueError:
            return "unknown", "unreadable /CANON.md"
        return (LATEST, "marker") if n == LATEST else ("draft", "marker from an earlier draft of the canon (%d)" % n)
    paths = list(mems)
    if not paths:
        return "legacy", "empty store"
    if kind == "memory":
        if any(p.startswith(("/sandbox/", "/repos/")) for p in paths):
            return "legacy", "layout: sandbox/ and repos/ at the root"
    else:
        if any(re.match(r"/\d\d-[^/]+/", p) or re.match(r"/[a-z]+/[^/]+\.md", p) for p in paths):
            return "legacy", "layout: folders at the root"
    return "unknown", "no marker and no known layout"


def seed_text(seed, name, subs):
    s = open("%s/%s" % (seed, name)).read()
    for k, v in subs.items():
        s = s.replace(k, v)
    return s


def role_lines(roles):
    return "\n".join("- `roles/%s/INDEX.md`: the %s role" % (r, r) for r in roles)


def migrate_legacy(kind, mems, project, roles, default_role, seed, today):
    ops, notes = [], []
    taken = set(mems)
    moved_to = {}

    def dest_for(p):
        if kind == "memory":
            if p.startswith(("/sandbox/", "/repos/")):
                return "/shared" + p
        else:
            if re.match(r"/\d\d-[^/]+/", p) or p.startswith("/tools/"):
                return "/roles/%s%s" % (default_role, p)
        return None

    for p, m in sorted(mems.items()):
        if p in ("/README.md", "/_template.md", "/CANON.md"):
            continue
        if p.startswith(("/shared/", "/roles/", "/_conflicts/")):
            continue
        d = dest_for(p)
        if d is None:
            notes.append("left in place, not part of any known layout: %s" % p)
            continue
        if d in taken:
            d = "/_conflicts/%s%s" % (today, p)
            notes.append("conflict: %s already exists; %s goes to %s" % (p, p, d))
        taken.add(d)
        moved_to[p] = d
        ops.append({"op": "move", "id": m["id"], "from": p, "to": d})

    subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
    old_readme = mems.get("/README.md")

    if kind == "memory":
        rows = []
        if old_readme:
            rows = [l for l in old_readme["content"].splitlines() if re.match(r"^\| (sandbox|repos)/", l)]
        idx = seed_text(seed, "INDEX.shared.memory.md", subs)
        if rows:
            idx = idx.replace("| (none yet) | | |\n", "\n".join(rows) + "\n")
        shared_index = ("/shared/INDEX.md", idx)
    else:
        shared_index = ("/shared/INDEX.md", seed_text(seed, "INDEX.shared.reference.md", subs))
        if old_readme:
            d = "/roles/%s/INDEX.md" % default_role
            if d in taken:
                d = "/_conflicts/%s/README.md" % today
                notes.append("conflict: the old index goes to %s" % d)
            taken.add(d)
            ops.append({"op": "move", "id": old_readme["id"], "from": "/README.md", "to": d})

    new = []
    if shared_index[0] not in taken:
        new.append(shared_index)
        taken.add(shared_index[0])
    for r in roles:
        p = "/roles/%s/INDEX.md" % r
        if p not in taken:
            new.append((p, seed_text(seed, "INDEX.role.%s.md" % kind, dict(subs, **{"{{ROLE}}": r}))))
            taken.add(p)
    if kind == "memory" and "/_template.md" not in mems:
        new.append(("/_template.md", open("%s/_template.md" % seed).read()))
    for p, c in new:
        ops.append({"op": "create", "path": p, "content": c})

    readme_content = seed_text(seed, "README.%s.md" % kind, subs)
    if kind == "memory" and old_readme:
        ops.append({"op": "update", "id": old_readme["id"], "path": "/README.md", "content": readme_content,
                    "sha": old_readme.get("content_sha256", "")})
    else:
        ops.append({"op": "create", "path": "/README.md", "content": readme_content})
    return ops, notes


NUM = re.compile(r"^\d\d-")


def strip_num(name):
    return NUM.sub("", name)


def rewrite_refs(text, folders):
    """Replace old numbered folder names with the new ones wherever they are named."""
    for old in sorted(folders, key=len, reverse=True):
        text = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(old), folders[old], text)
    return text


def simulate(mems, ops):
    """Apply steps to an in-memory store: {path: {id, path, content, content_sha256}}."""
    out = {p: dict(m) for p, m in mems.items()}
    n = 0
    for op in ops:
        if op["op"] == "move":
            m = out.pop(op["from"]); m["path"] = op["to"]; out[op["to"]] = m
        elif op["op"] in ("create", "marker", "update"):
            cur = None
            if op.get("id"):
                cur = next((v for v in out.values() if v["id"] == op["id"]), None)
            if cur is None:
                n += 1
                out[op["path"]] = {"type": "memory", "id": "new_%d" % n, "path": op["path"], "content": op["content"], "content_sha256": ""}
            else:
                cur["content"] = op["content"]; cur["content_sha256"] = ""
    return out


def migrate_draft(kind, mems, project, roles, default_role, seed, today):
    """Numbered prefixes (01-rules) become plain names (rules): folders are renamed and
    the references to them inside the files of the same scope are rewritten."""
    ops, notes = [], []
    taken = set(mems)
    scopes = ["/shared/"] + ["/roles/%s/" % r for r in roles]
    moved = {}
    for scope in scopes:
        folders = {}
        for p in mems:
            if p.startswith(scope):
                top = p[len(scope):].split("/")[0]
                if "/" in p[len(scope):] and NUM.match(top):
                    folders[top] = strip_num(top)
        if not folders:
            continue
        for p, m in sorted(mems.items()):
            if not p.startswith(scope):
                continue
            rest = p[len(scope):]
            top = rest.split("/")[0]
            if "/" in rest and top in folders:
                d = scope + folders[top] + rest[len(top):]
                if d in taken:
                    d = "/_conflicts/%s%s" % (today, p)
                    notes.append("conflict: %s already exists; %s goes to %s" % (scope + folders[top] + rest[len(top):], p, d))
                taken.add(d)
                moved[p] = d
                ops.append({"op": "move", "id": m["id"], "from": p, "to": d})
        for p, m in sorted(mems.items()):
            if not p.startswith(scope):
                continue
            new = rewrite_refs(m["content"], folders)
            if new != m["content"]:
                ops.append({"op": "update", "id": m["id"], "path": moved.get(p, p), "content": new,
                            "sha": m.get("content_sha256", "")})
        notes.append("%s: %s" % (scope, ", ".join("%s -> %s" % kv for kv in sorted(folders.items()))))
    # the root README is regenerated from the seed (it names the layout)
    old = mems.get("/README.md")
    if old:
        subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
        new = seed_text(seed, "README.%s.md" % kind, subs)
        if new != old["content"]:
            ops.append({"op": "update", "id": old["id"], "path": "/README.md", "content": new,
                        "sha": old.get("content_sha256", "")})
    return ops, notes


# Each state reaches LATEST through an ordered chain of steps.
CHAINS = {"legacy": [migrate_legacy, migrate_draft], "draft": [migrate_draft]}


def cmd_plan(a):
    mems = load(a.store)
    roles = a.roles.split(",")
    state, why = detect(a.kind, mems)
    today = a.today or datetime.date.today().isoformat()
    out = {"from_version": state, "to_version": LATEST, "why": why, "ops": [], "notes": []}
    if state == "unknown":
        out["notes"].append("layout unrecognised (%s): nothing can be planned" % why)
        print(json.dumps(out)); return 0
    if state != LATEST:
        cur = mems
        for step in CHAINS[state]:
            ops, notes = step(a.kind, cur, a.project, roles, a.default_role, a.seed, today)
            out["ops"] += ops
            out["notes"] += notes
            cur = simulate(cur, ops)
        out["ops"].append({"op": "marker", "path": "/CANON.md", "content":
                           canon_marker(a.kind, a.project, roles, LATEST, state, today),
                           "id": mems.get("/CANON.md", {}).get("id", "")})
    print(json.dumps(out))
    return 0


def cmd_check(a):
    mems = load(a.store)
    roles = a.roles.split(",")
    ver, why = detect(a.kind, mems)
    fails, warns = [], []
    F = lambda p, s: fails.append("FAIL %s: %s" % (p, s))
    W = lambda p, s: warns.append("WARN %s: %s" % (p, s))
    if ver != LATEST:
        F("/CANON.md", "store is %s (%s); the canon is at version %d: run `dev-agent canon plan`" % (ver, why, LATEST))
    else:
        d = parse_marker(mems["/CANON.md"]["content"])
        if d.get("kind") != a.kind: F("/CANON.md", "kind is %s, expected %s" % (d.get("kind"), a.kind))
        if d.get("project") != a.project: F("/CANON.md", "project is %s, expected %s" % (d.get("project"), a.project))
        if sorted(d.get("roles", "").split()) != sorted(roles):
            W("/CANON.md", "roles %s differ from the project's %s" % (d.get("roles"), " ".join(roles)))
        readme = mems.get("/README.md")
        if not readme: F("/README.md", "missing")
        elif len(readme["content"]) > 3000: F("/README.md", "%d chars, limit 3000" % len(readme["content"]))
        if "/shared/INDEX.md" not in mems: F("/shared/INDEX.md", "missing")
        for r in roles:
            if "/roles/%s/INDEX.md" % r not in mems: F("/roles/%s/INDEX.md" % r, "missing")
        for p in sorted(mems):
            if p in ("/CANON.md", "/README.md", "/_template.md"): continue
            parts = p.strip("/").split("/")
            if parts[0] == "roles":
                if len(parts) < 3 or parts[1] not in roles:
                    F(p, "a role folder for a role the project does not use (%s)" % (parts[1] if len(parts) > 1 else "?"))
            elif parts[0] == "shared":
                pass
            elif parts[0] == "_conflicts":
                W(p, "unresolved conflict: merge it or delete it")
            else:
                F(p, "outside the canon layout")
        # every file is listed in its index (shared or role INDEX), by relative path
        scopes = {"/shared/": mems.get("/shared/INDEX.md", {}).get("content", "")}
        for r in roles:
            scopes["/roles/%s/" % r] = mems.get("/roles/%s/INDEX.md" % r, {}).get("content", "")
        for p in sorted(mems):
            m = re.match(r"^(/(?:shared|roles/[^/]+)/)(repos/[^/]+/)(.+)$", p)
            if m:
                scope, repo, rest = m.group(1), m.group(2), m.group(3)
                if rest == "INDEX.md":
                    if "%sINDEX.md" % repo not in scopes.get(scope, ""):
                        W(p, "not listed in %sINDEX.md" % scope)
                else:
                    ridx = mems.get(scope + repo + "INDEX.md", {}).get("content", "")
                    if rest not in ridx:
                        W(p, "not listed in %s%sINDEX.md" % (scope, repo))
                continue
            for pre, idx in scopes.items():
                if p.startswith(pre) and not p.endswith("INDEX.md") and p[len(pre):] not in idx:
                    W(p, "not listed in %sINDEX.md" % pre)
    secrets = [r"sk-ant-[A-Za-z0-9_-]{8,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}",
               r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY"]
    for p, m in sorted(mems.items()):
        for pat in secrets:
            if re.search(pat, m["content"]): F(p, "looks like a secret")
    out = fails + warns
    print("\n".join(out) if out else "clean: canon %s, %d files" % (ver, len(mems)))
    print("%d fail, %d warn" % (len(fails), len(warns)))
    return 1 if fails else 0


def rename_top(p, folders):
    top = p.strip('/').split('/')[0]
    return '/' + folders.get(top, top) + p[len(top) + 1:]


def import_docs_v0(a):
    src = load(a.src)
    mem, ref = load(a.memory), load(a.reference)
    today = a.today or datetime.date.today().isoformat()
    role = a.role
    taken = {"memory": set(mem), "reference": set(ref)}
    ops = {"memory": [], "reference": []}
    notes = []
    # numbered source folders become plain names; references to them are rewritten
    folders = {}
    for p in src:
        top = p.strip("/").split("/")[0]
        if NUM.match(top):
            folders[top] = strip_num(top)
    if folders:
        notes.append("renamed: " + ", ".join("%s -> %s" % kv for kv in sorted(folders.items())))
    src = {p: dict(m, content=rewrite_refs(m["content"], folders)) for p, m in src.items()}
    for p, m in sorted(src.items()):
        if p == "/README.md":
            kind, dest = "reference", "/roles/%s/INDEX.md" % role
            content = ("> Imported from the documentation store; paths below are relative to this role folder.\n\n"
                       + m["content"])
        elif re.match(r"/0[1-6]-", p) or p.startswith(("/08-maintainer/", "/tools/")):
            kind, dest, content = "reference", "/roles/%s%s" % (role, rename_top(p, folders)), m["content"]
        elif p.startswith("/07-project/"):
            kind, dest, content = "memory", "/roles/%s%s" % (role, rename_top(p, folders)), m["content"]
        else:
            notes.append("not imported, unknown part of the source layout: %s" % p)
            continue
        if dest in taken[kind]:
            existing = (ref if kind == "reference" else mem).get(dest)
            if existing and existing["content"] == content:
                continue
            if existing and "| (none yet) | | |" in existing["content"]:
                ops[kind].append({"op": "update", "id": existing["id"], "path": dest, "content": content})
                continue
            dest = "/_conflicts/%s%s" % (today, dest)
            notes.append("conflict: goes to %s" % dest)
        taken[kind].add(dest)
        ops[kind].append({"op": "create", "path": dest, "content": content})
    print(json.dumps({"memory": ops["memory"], "reference": ops["reference"], "notes": notes}))
    return 0


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "check"):
        s = sub.add_parser(name)
        s.add_argument("--kind", choices=KINDS, required=True)
        s.add_argument("--project", required=True)
        s.add_argument("--roles", required=True)
        s.add_argument("--store", required=True)
        s.add_argument("--today")
        if name == "plan":
            s.add_argument("--default-role", required=True)
            s.add_argument("--seed", required=True)
    s = sub.add_parser("import")
    s.add_argument("--map", required=True, choices=["docs-v0"])
    s.add_argument("--role", required=True)
    s.add_argument("--src", required=True)
    s.add_argument("--memory", required=True)
    s.add_argument("--reference", required=True)
    s.add_argument("--today")
    a = ap.parse_args()
    sys.exit({"plan": cmd_plan, "check": cmd_check, "import": import_docs_v0}[a.cmd](a))


if __name__ == "__main__":
    main()
