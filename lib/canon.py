#!/usr/bin/env python3
"""Canon planner: pure functions from a store's memories to a list of steps.

Subcommands (all read JSON lines of {"id","path","content"} from --store and print JSON):
  plan    --kind memory|reference --project P --roles dev,docs --default-role R --store F --seed D
  check   --kind K --project P --roles ... --store F   (structure, note format, indexes, hygiene)
  import  --map docs-v0 --role R --src F --memory F --reference F --seed D
The executor (canon.sh) applies the steps with `ant`. Nothing here talks to the API.
"""
import argparse, datetime, json, re, sys

LATEST = 2
KINDS = ("memory", "reference")
# canon/layout.json carries the same vocabulary; tests/test_canon.py keeps them equal.
RUNNABLE = {"memory": ("setup", "gate", "pitfall", "sandbox"), "reference": ()}
DOCUMENT = {"memory": ("history", "status"),
            "reference": ("rule", "convention", "workflow", "architecture", "knowledge", "preference", "review", "guide")}
LIMITS = {"runnable_chars": 3000, "document_chars": 10000, "readme_chars": 3000, "index_chars": 2500, "always_chars": 8000, "stale_days": 90}
HEADER = ("Kind", "Applies to", "Sources", "Check", "Verified", "Supersedes")
FIELD = re.compile(r"^(Kind|Applies to|Sources|Check|Verified|Supersedes):[ \t]*(.*)$")
MEM_FOLDER_KIND = {"sandbox": "sandbox", "setup": "setup", "gates": "gate", "pitfalls": "pitfall"}
MEM_STEM_KIND = {"history": "history", "open-items": "status", "status": "status"}
REF_FOLDER_KIND = {"rules": "rule", "conventions": "convention", "workflow": "workflow", "architecture": "architecture",
                   "knowledge": "knowledge", "preferences": "preference", "review": "review"}
NOT_RECORDED = "origin not recorded"


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
        if n == LATEST:
            return LATEST, "marker"
        if 1 <= n < LATEST:
            return n, "canon version %d" % n
        if n > LATEST:
            return "unknown", "written by a newer qargi (canon %d); this one knows %d" % (n, LATEST)
        return "draft", "marker from an earlier draft of the canon (%d)" % n
    paths = list(mems)
    if not paths:
        return "legacy", "empty store"
    if any(p.startswith(("/shared/", "/roles/")) for p in paths):
        return "legacy", "no marker but canon folders exist: an interrupted migration, resumed"
    if set(paths) <= {"/README.md", "/_template.md"}:
        return "legacy", "only an index file"
    if kind == "memory":
        if any(p.startswith(("/sandbox/", "/repos/")) for p in paths):
            return "legacy", "layout: sandbox/ and repos/ at the root"
    else:
        if any(re.match(r"/\d\d-[^/]+/", p) or re.match(r"/[a-z]+/[^/]+\.md", p) for p in paths):
            return "legacy", "layout: folders at the root"
    return "unknown", "no marker and no known layout"


def is_note(p):
    """A note is a Markdown file under shared/ or roles/<role>/ that is not an index and not under tools/."""
    parts = p.strip("/").split("/")
    return (parts[0] in ("shared", "roles") and len(parts) > 1 and parts[-1].endswith(".md")
            and parts[-1] != "INDEX.md" and not (parts[0] == "roles" and "tools" in parts[2:-1]))


def fenced(lines):
    """Indexes of the lines inside a fenced code block (the fence lines included)."""
    inside, out = False, set()
    for i, l in enumerate(lines):
        if l.lstrip().startswith(("```", "~~~")):
            inside = not inside
            out.add(i)
        elif inside:
            out.add(i)
    return out


def note_fields(c):
    out = {}
    lines = c.splitlines()
    skip = fenced(lines)
    for i, line in enumerate(lines):
        m = FIELD.match(line)
        if m and i not in skip and m.group(1) not in out:
            out[m.group(1)] = m.group(2).strip()
    return out


def kind_for(kind, p):
    """The kind a note at path p is expected to have (None when the path does not say)."""
    parts = p.strip("/").split("/")
    inner = parts[2:] if parts[0] == "roles" else parts[1:]
    if kind == "memory":
        for part in inner[:-1]:
            if part in MEM_FOLDER_KIND:
                return MEM_FOLDER_KIND[part]
        return MEM_STEM_KIND.get(inner[-1][:-3]) if inner else None
    if len(inner) > 2 and inner[0] == "repos":
        inner = inner[2:]
    return REF_FOLDER_KIND.get(inner[0], "guide") if len(inner) > 1 else "guide"


def applies_for(kind, p, project):
    parts = p.strip("/").split("/")
    if "repos" in parts[:-1]:
        i = parts.index("repos")
        if i + 1 < len(parts) - 1:
            return parts[i + 1]
    return "any" if kind_for(kind, p) == "sandbox" else project


def add_header(kind, p, content, project, today):
    """Insert the header lines a note lacks; the body is never edited. -> (content, [added fields])"""
    f = note_fields(content)
    want = []
    k = kind_for(kind, p)
    if "Kind" not in f and k:
        want.append(("Kind", k))
    if "Applies to" not in f:
        want.append(("Applies to", applies_for(kind, p, project)))
    if "Sources" not in f:
        m = re.match(r"\d{4}-\d{2}-\d{2}\s+by\s+(.+?)(?:\s+on\s+.*)?$", f.get("Verified", ""))
        src = "%s, %s" % (m.group(1), f["Verified"][:10]) if m else "carried over by the canon %d migration on %s; %s" % (LATEST, today, NOT_RECORDED)
        want.append(("Sources", src))
    if not want:
        return content, []
    L = content.split("\n")
    for name, val in want:                        # in canonical order, each after the nearest field before it
        skip = fenced(L)
        t = next((i for i, l in enumerate(L) if l.startswith("# ") and i not in skip), -1)
        pos = {FIELD.match(l).group(1): i for i, l in reversed(list(enumerate(L))) if FIELD.match(l) and i not in skip and i > t}
        before = [pos[f] for f in HEADER[:HEADER.index(name)] if f in pos and pos[f] - t <= 8]
        later = [pos[f] for f in HEADER[HEADER.index(name) + 1:] if f in pos and pos[f] - t <= 8]
        line = "%s: %s" % (name, val)
        if before:
            L.insert(max(before) + 1, line)
        elif later:
            L.insert(min(later), line)
        else:
            ins = ([""] if t >= 0 else []) + [line]
            if t + 1 < len(L) and L[t + 1].strip():
                ins.append("")
            L[t + 1:t + 1] = ins
    return "\n".join(L), [k for k, _ in want]


LOAD_WHEN = re.compile(r"(?m)^(\|\s*Path\s*\|\s*Purpose\s*\|\s*)Load when(\s*\|)")


def fix_index(content):
    return LOAD_WHEN.sub(r"\1Load\2", content)


def slurp(path):
    with open(path) as f:
        return f.read()


def seed_text(seed, name, subs):
    s = slurp("%s/%s" % (seed, name))
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
    if "/_template.md" not in mems:
        new.append(("/_template.md", slurp("%s/_template.%s.md" % (seed, kind))))
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
    # the root README is regenerated from the seed (it names the layout); a text that is
    # not the seed's stays available under _conflicts
    old = mems.get("/README.md")
    if old:
        subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
        new = seed_text(seed, "README.%s.md" % kind, subs)
        if new != old["content"]:
            was = seed_text(seed, "v1/README.%s.md" % kind, subs)
            keep = "/_conflicts/%s/README.md" % today
            if old["content"] != was and keep not in mems:
                ops.append({"op": "create", "path": keep, "content": old["content"]})
                notes.append("the root README is replaced; the old text is kept at %s" % keep)
            ops.append({"op": "update", "id": old["id"], "path": "/README.md", "content": new,
                        "sha": old.get("content_sha256", "")})
    return ops, notes


def migrate_v2(kind, mems, project, roles, default_role, seed, today):
    """Version 1 (structure only) to 2 (the note format): add what a note lacks, never edit a body."""
    ops, notes = [], []
    subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
    for p, m in sorted(mems.items()):
        c, new = m["content"], m["content"]
        if is_note(p):
            new, added = add_header(kind, p, c, project, today)
            if "Kind" not in note_fields(new):
                notes.append("kind not derivable from the path, set Kind: by hand: %s" % p)
        elif p.endswith("/INDEX.md"):
            new = fix_index(c)
        if new != c:
            ops.append({"op": "update", "id": m["id"], "path": p, "content": new, "sha": m.get("content_sha256", "")})
    for name, v1, v2 in (("README.md", "%s/v1/README.%s.md" % (seed, kind), seed_text(seed, "README.%s.md" % kind, subs)),
                         ("_template.md", "%s/v1/_template.md" % seed if kind == "memory" else None,
                          slurp("%s/_template.%s.md" % (seed, kind)))):
        cur = mems.get("/" + name)
        if cur is None:
            ops.append({"op": "create", "path": "/" + name, "content": v2})
        elif cur["content"] != v2:
            was = slurp(v1) if v1 else ""
            for k_, v_ in subs.items():
                was = was.replace(k_, v_)
            keep = "/_conflicts/%s/%s" % (today, name)
            if cur["content"] != was and keep not in mems:
                ops.append({"op": "create", "path": keep, "content": cur["content"]})
                notes.append("%s differed from the version 1 seed: the old text is kept at %s" % (name, keep))
            ops.append({"op": "update", "id": cur["id"], "path": "/" + name, "content": v2, "sha": cur.get("content_sha256", "")})
    return ops, notes


# Each state reaches LATEST through an ordered chain of steps.
CHAINS = {"legacy": [migrate_legacy, migrate_draft, migrate_v2], "draft": [migrate_draft, migrate_v2], 1: [migrate_v2]}


def maintain(kind, mems, project, roles, seed, today):
    """At the current version: create missing indexes, keep the marker's roles current."""
    ops, notes = [], []
    subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
    if "/shared/INDEX.md" not in mems:
        ops.append({"op": "create", "path": "/shared/INDEX.md", "content": seed_text(seed, "INDEX.shared.%s.md" % kind, subs)})
    for r in roles:
        p = "/roles/%s/INDEX.md" % r
        if p not in mems:
            ops.append({"op": "create", "path": p, "content": seed_text(seed, "INDEX.role.%s.md" % kind, dict(subs, **{"{{ROLE}}": r}))})
    d = parse_marker(mems["/CANON.md"]["content"])
    if sorted(d.get("roles", "").split()) != sorted(roles):
        ops.append({"op": "marker", "path": "/CANON.md", "id": mems["/CANON.md"]["id"],
                    "content": canon_marker(kind, project, roles, LATEST, "roles %s" % d.get("roles", ""), today)})
    known = set(roles)
    for p in sorted(mems):
        parts = p.strip("/").split("/")
        if parts[0] == "roles" and len(parts) > 2 and parts[1] not in known:
            notes.append("role folder left in place, the project does not use that role: /roles/%s/" % parts[1])
    readme = mems.get("/README.md", {}).get("content", "")
    for r in roles:
        if "roles/%s/INDEX.md" % r not in readme:
            notes.append("the README does not list roles/%s/INDEX.md (edit it, the reconciler does not rewrite a README at the current version)" % r)
    return ops, sorted(set(notes))


def cmd_plan(a):
    mems = load(a.store)
    roles = a.roles.split(",")
    state, why = detect(a.kind, mems)
    today = a.today or datetime.date.today().isoformat()
    out = {"from_version": state, "to_version": LATEST, "why": why, "ops": [], "notes": []}
    if state == "unknown":
        out["notes"].append("layout unrecognised (%s): nothing can be planned" % why)
        print(json.dumps(out)); return 0
    if state == LATEST:
        out["ops"], out["notes"] = maintain(a.kind, mems, a.project, roles, a.seed, today)
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


ROW = re.compile(r"(?m)^\|\s*`?([A-Za-z0-9._/-]+\.md)`?\s*\|([^|\n]*)\|([^|\n]*)\|\s*$")
VAGUE = re.compile(r"(?i)unsure|if needed|as needed|when relevant|sometimes|working on")


def load_ok(cell):
    c = cell.strip().lower()
    return bool(c) and not VAGUE.search(c)


def always_set(mems, role):
    """Paths an agent of this role loads before it knows the task: README, indexes, rows marked always."""
    out = ["/README.md", "/shared/INDEX.md", "/roles/%s/INDEX.md" % role]
    for idx in out[1:]:
        base = idx.rsplit("/", 1)[0]
        for ref, _, load in ROW.findall(mems.get(idx, {}).get("content", "")):
            if load.strip().lower() == "always" and not ref.endswith("INDEX.md"):
                out.append(base + "/" + ref)
    return [p for p in out if p in mems]


def notes_check(kind, mems, roles, F, W):
    """Canon 2: the note format, freshness, index form and hygiene."""
    assign = re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)\b\s*[:=]\s*[\"']?([A-Za-z0-9+/_=-]{16,})(?![\w(.])")
    docip = re.compile(r"^(192\.0\.2|198\.51\.100|203\.0\.113|127\.|0\.|10\.|172\.|192\.168\.)")
    banned = re.compile(r"(?i)\b(backlog|roadmap|todo|planned|plans?|later|ideas?)\b")
    today = datetime.date.today()
    vocab = RUNNABLE[kind] + DOCUMENT[kind]
    for p, m in sorted(mems.items()):
        c = m["content"]
        for g in assign.finditer(c):
            v = g.group(2)
            if re.search(r"\d", v) and re.search(r"[A-Za-z]", v):
                F(p, "looks like a secret (%s assigned a long mixed value)" % g.group(1).lower()); break
        if re.search(r"/home/(?!user/|u/)[a-z][a-z0-9_-]*/", c): W(p, "contains a home path")
        for ip in re.findall(r"(?<![\w.-])(\d{1,3}(?:\.\d{1,3}){3})(?![\w.-])", c):
            if all(int(x) <= 255 for x in ip.split(".")) and not docip.match(ip):
                W(p, "contains address %s (use documentation addresses)" % ip)
        if p.endswith("/INDEX.md"):
            if LOAD_WHEN.search(c):
                W(p, "the index column is `Load when`; canon 2 names it `Load`")
            elif not re.search(r"(?m)^\|\s*Path\s*\|\s*Purpose\s*\|\s*Load\s*\|", c):
                W(p, "no `| Path | Purpose | Load |` table")
            base = p.rsplit("/", 1)[0]
            if len(c) > LIMITS["index_chars"]: W(p, "%d chars; an index is read every session, keep it under %d" % (len(c), LIMITS["index_chars"]))
            for ref, _, load in ROW.findall(c):
                if base + "/" + ref not in mems:
                    W(p, "lists %s, which does not exist" % ref)
                if not load_ok(load):
                    W(p, "Load of %s is %r: say `always` or the task that needs it" % (ref, load.strip()))
            continue
        if not is_note(p):
            continue
        if kind == "memory" and banned.search(p): W(p, "path suggests backlog or planning material")
        f = note_fields(c)
        k = f.get("Kind", "")
        if not c.lstrip().startswith("# "): W(p, "no `# Title` line first")
        if not k: F(p, "no Kind: line")
        elif k not in vocab: F(p, "Kind is %s, this store's kinds are %s" % (k, ", ".join(vocab)))
        else:
            want = kind_for(kind, p)
            if want in RUNNABLE[kind] and k != want: F(p, "Kind is %s, this folder holds %s" % (k, want))
            elif kind == "reference" and want not in (None, "guide") and k != want: W(p, "Kind is %s, the folder suggests %s" % (k, want))
        for fld in ("Applies to", "Sources"):
            if not f.get(fld): F(p, "no %s: line" % fld)
        if NOT_RECORDED in f.get("Sources", ""): W(p, "Sources: %s; source it or remove it" % NOT_RECORDED)
        if k in RUNNABLE[kind]:
            if not f.get("Check"): F(p, "no Check: line (a %s note needs one)" % k)
            if not f.get("Verified"): F(p, "no Verified: line (a %s note needs one)" % k)
            if len(c) > LIMITS["runnable_chars"]: W(p, "%d chars; one fact per note, split it" % len(c))
        elif len(c) > LIMITS["document_chars"]:
            W(p, "%d chars; split it" % len(c))
        if f.get("Verified"):
            v = re.match(r"(\d{4}-\d{2}-\d{2})\b", f["Verified"])
            try:
                d = datetime.date.fromisoformat(v.group(1))
            except (AttributeError, ValueError):
                F(p, "Verified is not YYYY-MM-DD"); continue
            if d > today: F(p, "Verified date is in the future")
            elif k in RUNNABLE[kind] and (today - d).days > LIMITS["stale_days"]:
                W(p, "verified %d days ago; re-check" % (today - d).days)
        if not re.fullmatch(r"[a-z0-9][a-z0-9.-]*\.md", p.rsplit("/", 1)[1]) and p.rsplit("/", 1)[1] != "README.md":
            W(p, "file name should be kebab-case")


def cmd_check(a):
    mems = load(a.store)
    roles = a.roles.split(",")
    ver, why = detect(a.kind, mems)
    fails, warns = [], []
    F = lambda p, s: fails.append("FAIL %s: %s" % (p, s))
    W = lambda p, s: warns.append("WARN %s: %s" % (p, s))
    if ver != LATEST:
        F("/CANON.md", "store is %s (%s); the canon is at version %d: run `qargi canon plan`" % (ver, why, LATEST))
    else:
        d = parse_marker(mems["/CANON.md"]["content"])
        if d.get("kind") != a.kind: F("/CANON.md", "kind is %s, expected %s" % (d.get("kind"), a.kind))
        if d.get("project") != a.project: F("/CANON.md", "project is %s, expected %s" % (d.get("project"), a.project))
        if sorted(d.get("roles", "").split()) != sorted(roles):
            W("/CANON.md", "roles %s differ from the project's %s" % (d.get("roles"), " ".join(roles)))
        readme = mems.get("/README.md")
        if not readme: F("/README.md", "missing")
        elif len(readme["content"]) > LIMITS["readme_chars"]: F("/README.md", "%d chars, limit %d" % (len(readme["content"]), LIMITS["readme_chars"]))
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
        notes_check(a.kind, mems, roles, F, W)
        for r in roles:
            n = sum(len(mems[q]["content"]) for q in always_set(mems, r))
            if n > LIMITS["always_chars"]:
                W("/roles/%s/INDEX.md" % r, "the always-loaded set of the %s role is %d chars (limit %d): trim the README or the indexes, or load a note only when its task needs it" % (r, n, LIMITS["always_chars"]))

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
        if is_note(dest) and not p.endswith("INDEX.md"):
            content, _ = add_header(kind, dest, content, a.project, today)
            if "Kind" not in note_fields(content):
                notes.append("kind not derivable from the path, set Kind: by hand: %s" % dest)
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
    s.add_argument("--project", required=True)
    s.add_argument("--role", required=True)
    s.add_argument("--src", required=True)
    s.add_argument("--memory", required=True)
    s.add_argument("--reference", required=True)
    s.add_argument("--today")
    a = ap.parse_args()
    sys.exit({"plan": cmd_plan, "check": cmd_check, "import": import_docs_v0}[a.cmd](a))


if __name__ == "__main__":
    main()
