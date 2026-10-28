#!/usr/bin/env python3
"""The role names before the abilities, and how a thing named with them is brought to the current names.

The work roles were dev, docs, review and test; they are the abilities build, write, review and test now
(review, test and lead keep their names). The local agents were four fixed definitions, qargi-dev, qargi-docs,
qargi-review and qargi-test; they are members you name now (qargi agent add). This module is pure: `qargi migrate
roles` (lib/migrate.sh) and `qargi import` (lib/transfer.py) use it, and only they write.

  roles.py local-plan                    the local renames as JSON lines {what, from, to}
  roles.py local-apply                   do them (registry, tracker, answers, links, saved definitions)
  roles.py store-plan --store F          the steps that bring one memory store's notes to the new role folders,
                                         in the format canon.sh executes ({ops, notes})
"""
import json, os, re, sys

ROLE = {"dev": "build", "docs": "write"}
ABILITIES = ("build", "write", "review", "test")
# the per-role local agents an earlier version installed, and the ability each one served
OLD_AGENTS = {"qargi-dev": "build", "qargi-docs": "write", "qargi-review": "review", "qargi-test": "test"}
MEMBER_DEFAULT = {"build": "builder", "write": "writer", "review": "reviewer", "test": "tester"}
INSTANCE = re.compile(r"^([a-z][a-z0-9]{0,23})-(dev|docs)$")


def role(r):
    return ROLE.get(r, r)


def instance(name):
    m = INSTANCE.match(name or "")
    return "%s-%s" % (m.group(1), ROLE[m.group(2)]) if m else name


def answers(d):
    """A project's stored answers with the role keys renamed (roles, teams' members, scopes and done checks)."""
    d = json.loads(json.dumps(d))
    if isinstance(d.get("roles"), dict):
        d["roles"] = {role(k): v for k, v in d["roles"].items()}
    for t in (d.get("teams") or {}).values():
        if isinstance(t, dict):
            if isinstance(t.get("members"), list):
                t["members"] = [role(m) for m in t["members"]]
            for k in ("scopes", "done"):
                if isinstance(t.get(k), dict):
                    t[k] = {role(r): v for r, v in t[k].items()}
    return d


def links(d):
    d = json.loads(json.dumps(d))
    for l in d.get("links") or []:
        if isinstance(l, dict) and l.get("role"):
            l["role"] = role(l["role"])
    return d


def session(v):
    v = dict(v)
    if v.get("instance"):
        v["instance"] = instance(v["instance"])
    return v


def note_path(p):
    parts = p.split("/")
    if len(parts) > 2 and parts[1] == "roles" and parts[2] in ROLE:
        parts[2] = ROLE[parts[2]]
    return "/".join(parts)


def note_text(path, text):
    """The text of a note with the old role names replaced where they name a role: the role folders, `the dev
    role`, a role index's title, the README's role list and the marker's roles line. Nothing else is touched."""
    out = re.sub(r"\broles/(dev|docs)/", lambda m: "roles/%s/" % ROLE[m.group(1)], text)
    out = re.sub(r"\bthe (dev|docs) role\b", lambda m: "the %s role" % ROLE[m.group(1)], out)
    out = re.sub(r"(?m)^# (dev|docs) (memory|reference) index$", lambda m: "# %s %s index" % (ROLE[m.group(1)], m.group(2)), out)
    if path == "/CANON.md":
        out = re.sub(r"(?m)^(roles:[ \t]*)(.*)$", lambda m: m.group(1) + " ".join(role(r) for r in m.group(2).split()), out)
    return out


def store_plan(mems, today):
    """{ops, notes}: move every note under roles/dev|docs/ to the new folder and fix the role names in the texts.
    A destination that exists already gets the moved note under _conflicts/ instead (canon check warns until merged)."""
    ops, notes = [], []
    taken = set(mems)
    for p, m in sorted(mems.items()):
        new = note_path(p)
        dest = new
        if new != p:
            if new in taken:
                dest = "/_conflicts/%s%s" % (today, p)
                notes.append("conflict: %s exists already; %s goes to %s" % (new, p, dest))
            taken.add(dest)
            ops.append({"op": "move", "id": m["id"], "from": p, "to": dest})
        text = m.get("content") or ""
        fixed = note_text(p, text)
        if fixed != text:
            ops.append({"op": "update", "id": m["id"], "path": dest, "content": fixed, "sha": m.get("content_sha256", "")})
    return {"ops": ops, "notes": notes}


# --- local state ---------------------------------------------------------------------------------------------------
def conf():
    return os.environ.get("QARGI_CONF") or os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "qargi")


def state():
    return os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")


def jload(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def jwrite(path, obj):
    tmp = path + ".migrate.tmp"
    with open(tmp, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def local_steps():
    """[(what, from, to, apply)] for everything kept on this machine."""
    steps = []
    reg_path = os.path.join(conf(), "instances.json")
    reg = jload(reg_path, {})
    renames = {k: instance(k) for k in reg if instance(k) != k}
    for old, new in sorted(renames.items()):
        if new in reg:
            raise SystemExit("qargi: the registry holds both %s and %s; remove one (qargi instances remove NAME), then plan again" % (old, new))
    if renames:
        def do_reg():
            r = jload(reg_path, {})
            jwrite(reg_path, {renames.get(k, k): v for k, v in r.items()})
        steps += [("registry", o, n, None) for o, n in sorted(renames.items())]
        steps.append(("", "", "", do_reg))
    trk_path = os.path.join(state(), "sessions.json")
    trk = jload(trk_path, {})
    moved = sorted(sid for sid, v in trk.items() if isinstance(v, dict) and session(v) != v)
    if moved:
        steps += [("tracker", "session %s of %s" % (sid, trk[sid]["instance"]), instance(trk[sid]["instance"]), None) for sid in moved]
        steps.append(("", "", "", lambda: jwrite(trk_path, {k: (session(v) if isinstance(v, dict) else v) for k, v in jload(trk_path, {}).items()})))
    pdir = os.path.join(conf(), "projects")
    for f in sorted(os.listdir(pdir)) if os.path.isdir(pdir) else []:
        if not f.endswith(".json"):
            continue
        path = os.path.join(pdir, f)
        cur = jload(path, None)
        if not isinstance(cur, dict):
            continue
        new = answers(cur)
        if new != cur:
            what = []
            if list(cur.get("roles") or {}) != list(new.get("roles") or {}):
                what.append("roles %s -> %s" % (" ".join(cur.get("roles") or {}), " ".join(new.get("roles") or {})))
            if json.dumps(cur.get("teams")) != json.dumps(new.get("teams")):
                what.append("team members, scopes and done checks")
            steps.append(("answers", f[:-5], "; ".join(what), (lambda p=path, n=new: jwrite(p, n))))
    lpath = os.path.join(conf(), "packs", "links.json")
    cur = jload(lpath, None)
    if isinstance(cur, dict) and links(cur) != cur:
        n = sum(1 for a, b in zip(cur.get("links") or [], links(cur).get("links") or []) if a != b)
        steps.append(("pack links", "%d link(s) of a renamed role" % n, "", (lambda c=links(cur): jwrite(lpath, c))))
    ddir = os.path.join(state(), "definitions")
    for d in sorted(os.listdir(ddir)) if os.path.isdir(ddir) else []:
        if instance(d) != d:
            src, dst = os.path.join(ddir, d), os.path.join(ddir, instance(d))
            if os.path.exists(dst):
                raise SystemExit("qargi: both %s and %s exist; remove one, then plan again" % (src, dst))
            steps.append(("saved definitions", d, instance(d), (lambda s=src, t=dst: os.rename(s, t))))
    return steps


def main(argv):
    if argv[:1] == ["local-plan"]:
        for what, a, b, _ in local_steps():
            if what:
                print(json.dumps({"what": what, "from": a, "to": b}))
        return 0
    if argv[:1] == ["local-apply"]:
        n = 0
        for what, a, b, fn in local_steps():
            if fn:
                fn()
                n += 1
        print("local state: %d file(s) rewritten" % n)
        return 0
    if argv[:1] == ["store-plan"] and len(argv) >= 3 and argv[1] == "--store":
        mems = {}
        with open(argv[2]) as f:
            for line in f:
                if line.strip():
                    m = json.loads(line)
                    if m.get("type", "memory") == "memory":
                        mems[m["path"]] = m
        today = argv[4] if len(argv) >= 5 and argv[3] == "--today" else ""
        print(json.dumps(store_plan(mems, today or __import__("datetime").date.today().isoformat())))
        return 0
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
