#!/usr/bin/env python3
"""Canon planner: pure functions from a store's memories to a list of steps.

Subcommands (all read JSON lines of {"id","path","content"} from --store and print JSON):
  plan    --kind memory|reference --project P --roles build,write --store F --seed D
  check   --kind K --project P --roles ... --store F   (structure, note format, indexes, hygiene)
The executor (canon.sh) applies the steps with `ant`. Nothing here talks to the API.
"""
import argparse, datetime, json, os, re, sys

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


def setup_paths(roles):
    """The files `init` creates, in the order it creates them (the marker follows)."""
    return ["/shared/INDEX.md"] + ["/roles/%s/INDEX.md" % r for r in roles] + ["/_template.md", "/README.md"]


def detect(kind, mems, roles=None):
    """-> (state, why). state is LATEST (conforms), "empty" (no memories, or only the first files of a set-up that was
    interrupted before it wrote the marker: it is set up from the seed) or "unknown" (a marker this qargi does not read,
    or no marker). Layouts older than canon 2 are not migrated. Without `roles` a store with no marker is empty only
    when it holds no memories."""
    if "/CANON.md" in mems:
        d = parse_marker(mems["/CANON.md"]["content"])
        try:
            n = int(d.get("canon", ""))
        except ValueError:
            return "unknown", "unreadable /CANON.md"
        if n == LATEST:
            return LATEST, "marker"
        if n > LATEST:
            return "unknown", "written by a newer qargi (canon %d); this one knows %d" % (n, LATEST)
        return "unknown", "canon version %d is older than the %d this qargi reads, and it no longer migrates it" % (n, LATEST)
    if not mems:
        return "empty", "empty store: it is set up from the seed"
    order = setup_paths(roles) if roles else []
    if sorted(mems) == sorted(order[:len(mems)]):
        return "empty", "an interrupted set-up (no marker yet): it is finished from the seed"
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


def init(kind, mems, project, roles, seed, today):
    """An empty store: the seed's README, template, shared index and one index per role. The marker follows (make_plan).
    A file already there is left as it is: a set-up that was interrupted is finished, not redone."""
    subs = {"{{PROJECT}}": project, "{{ROLES}}": role_lines(roles), "{{ROLE_LIST}}": " ".join(roles)}
    text = {"/shared/INDEX.md": lambda: seed_text(seed, "INDEX.shared.%s.md" % kind, subs),
            "/_template.md": lambda: slurp("%s/_template.%s.md" % (seed, kind)),
            "/README.md": lambda: seed_text(seed, "README.%s.md" % kind, subs)}
    for r in roles:
        text["/roles/%s/INDEX.md" % r] = lambda r=r: seed_text(seed, "INDEX.role.%s.md" % kind, dict(subs, **{"{{ROLE}}": r}))
    return [{"op": "create", "path": p, "content": text[p]()} for p in setup_paths(roles) if p not in mems], []


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


# A state reaches LATEST through its steps: an empty store is set up; a store at LATEST is only maintained (below).
CHAINS = {"empty": [init]}


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
    rd = mems.get("/README.md")
    readme = rd["content"] if rd else ""
    block = re.compile(r"(Roles in this project:\n\n)((?:- `roles/[^\n]*\n?)+)")
    if rd and block.search(readme):   # the README's own role list follows the project's roles
        fixed = block.sub(lambda m: m.group(1) + role_lines(roles) + ("\n" if m.group(2).endswith("\n") else ""), readme, count=1)
        if fixed != readme:
            ops.append({"op": "update", "id": rd["id"], "path": "/README.md", "content": fixed, "sha": rd.get("content_sha256", "")})
            readme = fixed
    for r in roles:
        if "roles/%s/INDEX.md" % r not in readme:
            notes.append("the README does not list roles/%s/INDEX.md (edit it)" % r)
    return ops, sorted(set(notes))


def make_plan(kind, mems, project, roles, seed, today):
    """The steps from a store's memories to the current canon: {from_version, to_version, why, ops, notes}."""
    state, why = detect(kind, mems, roles)
    out = {"from_version": state, "to_version": LATEST, "why": why, "ops": [], "notes": []}
    if state == "unknown":
        out["notes"].append("layout unrecognised (%s): nothing can be planned" % why)
        return out
    if state == LATEST:
        out["ops"], out["notes"] = maintain(kind, mems, project, roles, seed, today)
    else:
        for step in CHAINS[state]:
            ops, notes = step(kind, mems, project, roles, seed, today)
            out["ops"] += ops
            out["notes"] += notes
        out["ops"].append({"op": "marker", "path": "/CANON.md", "content":
                           canon_marker(kind, project, roles, LATEST, state, today),
                           "id": mems.get("/CANON.md", {}).get("id", "")})
    return out


def cmd_plan(a):
    today = a.today or datetime.datetime.now(datetime.timezone.utc).date().isoformat()
    print(json.dumps(make_plan(a.kind, load(a.store), a.project, a.roles.split(","), a.seed, today)))
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
    today = datetime.datetime.now(datetime.timezone.utc).date()
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
    ver, why = detect(a.kind, mems, roles)
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
            elif parts[0] == "_archive":   # optional: notes qargi memory split moved aside; each says where from in Sources:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # run as python3 -I: the lib directory is not on the path
                import memplan             # here, not at the top: memplan imports this module
                if memplan.origin(mems[p]["content"])[0] != "archived":
                    W(p, "an archived note without the `archived from` segment qargi puts on its Sources: line; where did it come from?")
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
            s.add_argument("--seed", required=True)
    a = ap.parse_args()
    sys.exit({"plan": cmd_plan, "check": cmd_check}[a.cmd](a))


if __name__ == "__main__":
    main()
