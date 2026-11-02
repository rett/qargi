#!/usr/bin/env python3
"""Which skills would a Claude Code session opened in a project's checkout load, and who vouches for each?

qargi manages the skills of its library and renders them for a project, but a session loads more than that: the skills in
CHECKOUT/.claude/skills, in the render, and in ~/.claude/skills. This audit lists every one of them with exactly one state:

  qargi       a library pack with approved content and the same content hash, or a skill under the qargi install's skills/
  accepted    the owner accepted this name with this content (accepted.json)
  drifted     the owner accepted this name, but the content changed since (a finding)
  excluded    set to "off" in skillOverrides of ~/.claude/settings.json, CHECKOUT/.claude/settings.json or settings.local.json
              (hidden from the session, never a finding)
  unmanaged   anything else

Called by packs.sh, which holds the facts only the shell knows (the content hash of a skill directory, the library) in an inputs file:
  {project, state, home, checkout, accepted, skills:[{name, where[], shown, real, hash, lib:{hash,approved}|null}]}
  (`scan` finds the skill directories, the shell hashes them, `report` and `target` judge them.)

  packs_audit.py scan   INPUTS OUT                     write the visible skill directories as JSON
  packs_audit.py report INPUTS                         print the section; exit 1 when a skill is drifted
  packs_audit.py target INPUTS NAME SCOPE OUT          the skill `skill accept` would record (refuses other states); writes it to OUT
  packs_audit.py acceptance FILE SCOPE PROJECT NAME    print one stored acceptance as JSON, or exit 1
  packs_audit.py store accept|unaccept FILE SCOPE PROJECT NAME [HASH PATH APPROVED AT]   the only writer of accepted.json

Settings files are only ever read. accepted.json is written atomically (temporary file, then rename), mode 600.
"""
import json
import os
import re
import sys
import tempfile

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
PLACES = ("checkout", "render", "user")


def die(msg):
    print("qargi: " + msg, file=sys.stderr)
    sys.exit(1)


def load(path):
    with open(path) as fh:
        return json.load(fh)


def places(inp):
    """[(label, directory)] of the three places a session would load skills from."""
    out = []
    co = inp.get("checkout") or ""
    if co and os.path.isabs(co) and os.path.isdir(co):
        out.append(("checkout", os.path.join(co, ".claude", "skills")))
    out.append(("render", os.path.join(os.path.abspath(inp["state"]), "claude", inp["project"], ".claude", "skills")))
    if inp.get("home"):
        out.append(("user", os.path.join(inp["home"], ".claude", "skills")))
    return out


def scan(inp):
    """The skill directories (a directory with SKILL.md, symbolic links to directories followed) of the three places. The same
    directory reached twice (the checkout's link to the render) is one entry that names both places."""
    found = {}
    for label, d in places(inp):
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for n in names:
            p = os.path.join(d, n)
            if os.path.isdir(p) and os.path.isfile(os.path.join(p, "SKILL.md")):
                real = os.path.realpath(p)
                e = found.setdefault((n, real), {"name": n, "where": [], "shown": p, "real": real})
                if label not in e["where"]:
                    e["where"].append(label)
    return [found[k] for k in sorted(found)]


def shipped_roots():
    """The skills/ directories of the qargi install: the one this script runs from, and the one install.sh recorded."""
    roots = [os.path.realpath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "skills"))]
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import paths
        t = paths.installed_tool_root()
        if t:
            roots.append(os.path.join(t, "skills"))
    except Exception:
        pass
    return roots


def under(path, root):
    root = os.path.realpath(root)
    return path == root or path.startswith(root + os.sep)


def read_settings(inp):
    """({skill name: settings file that sets it to "off"}, [notes]). Missing files are fine; unreadable or malformed ones are noted."""
    files = []
    if inp.get("home"):
        files.append(os.path.join(inp["home"], ".claude", "settings.json"))
    co = inp.get("checkout") or ""
    if co and os.path.isabs(co):
        files += [os.path.join(co, ".claude", "settings.json"), os.path.join(co, ".claude", "settings.local.json")]
    off, notes = {}, []
    for f in files:
        if not os.path.lexists(f):
            continue
        try:
            data = load(f)
            ov = data.get("skillOverrides", {}) if isinstance(data, dict) else None
            if not isinstance(ov, dict):
                raise ValueError("not an object" if ov is None else "skillOverrides is not an object")
        except (OSError, ValueError) as e:
            why = e.strerror if isinstance(e, OSError) and e.strerror else str(e).split("\n")[0]
            notes.append("note: cannot read %s (%s): the skills it hides are unknown" % (f, why))
            continue
        for k, v in ov.items():
            if v == "off":
                off.setdefault(k, f)
    return off, notes


def read_accepted(path):
    """(the acceptances as {"user": {}, "projects": {}}, [notes]); a file that cannot be read accepts nothing."""
    empty = {"user": {}, "projects": {}}
    if not path or not os.path.lexists(path):
        return empty, []
    try:
        d = load(path)
        if not isinstance(d, dict) or not isinstance(d.get("user", {}), dict) or not isinstance(d.get("projects", {}), dict):
            raise ValueError("unexpected shape")
        return {"user": d.get("user", {}), "projects": d.get("projects", {})}, []
    except (OSError, ValueError) as e:
        return empty, ["note: cannot read %s (%s): nothing is treated as accepted" % (path, str(e).split("\n")[0])]


def recorded(acc, project, name):
    """[(scope, record)] of the acceptances of name that reach project."""
    out = []
    p = acc["projects"].get(project)
    for scope, table in (("project", p if isinstance(p, dict) else {}), ("user", acc["user"])):
        r = table.get(name)
        if isinstance(r, dict) and isinstance(r.get("sha256"), str) and r["sha256"]:
            out.append((scope, r))
    return out


def states(inp):
    """(skills with a state, notes). Each skill: the scanned entry plus state, detail."""
    off, notes = read_settings(inp)
    acc, n2 = read_accepted(inp.get("accepted"))
    notes += n2
    roots = shipped_roots()
    out = []
    for e in inp.get("skills", []):
        e = dict(e)
        h, lib, n = e.get("hash") or "", e.get("lib"), e["name"]
        recs = recorded(acc, inp["project"], n)
        if h and lib and lib.get("approved") and lib["approved"] == lib.get("hash") == h:
            e["state"], e["detail"] = "qargi", "library pack"
        elif any(under(e["real"], r) for r in roots):
            e["state"], e["detail"] = "qargi", "shipped with qargi"
        elif n in off:
            e["state"], e["detail"] = "excluded", "off in " + off[n]
        elif h and any(r["sha256"] == h for _, r in recs):
            e["state"], e["detail"] = "accepted", "accepted for " + next(s for s, r in recs if r["sha256"] == h)
        elif recs:
            e["state"], e["detail"] = "drifted", "accepted as %s, content changed" % recs[0][1]["sha256"][:12]
        else:
            e["state"], e["detail"] = "unmanaged", ""
        out.append(e)
    return out, notes


LEGEND = {"qargi": "managed by qargi", "accepted": "you accepted this content", "drifted": "accepted, but the content changed (a finding)",
          "excluded": "hidden by skillOverrides", "unmanaged": "not managed or accepted by anyone"}


def offers(inp, e):
    p, n = inp["project"], e["name"]
    if e["state"] == "drifted":
        return ["    review it, then accept the new content: qargi skill accept %s %s%s" % (p, n, "" if "checkout" in e["where"] else " --user")]
    if e["state"] != "unmanaged":
        return []
    out = []
    if "checkout" in e["where"]:
        lib = e.get("lib")
        if lib is None:
            out += ["    to keep it in the library: qargi skill import %s" % e["shown"],
                    "                               qargi skill link %s --scope project --project %s" % (n, p)]
        else:
            out += ["    a library pack of this name has other content or is not approved: qargi skill show %s" % n]
        out += ["    or accept it as it is:      qargi skill accept %s %s" % (p, n)]
    else:
        out += ["    to accept it as it is: qargi skill accept %s %s --user" % (p, n)]
    return out


def cmd_report(inp):
    sk, notes = states(inp)
    print("skills a session would load:")
    if not sk:
        print("  (none)")
    for e in sk:
        extra = ["+".join(e["where"]), (e.get("hash") or "unreadable")[:12]] + ([e["detail"]] if e["detail"] else [])
        print("  %-9s %s  (%s)" % (e["state"], e["name"], ", ".join(extra)))
        for o in offers(inp, e):
            print(o)
    for n in notes:
        print("  " + n)
    present = [s for s in LEGEND if any(e["state"] == s for e in sk)]
    if present:
        print("  legend: " + "; ".join("%s: %s" % (s, LEGEND[s]) for s in present))
    sys.exit(1 if any(e["state"] == "drifted" for e in sk) else 0)


def cmd_target(inp, name, scope, outfile):
    if not NAME_RE.match(name):
        die("not a skill name: " + name)
    sk, _ = states(inp)
    ents = [e for e in sk if e["name"] == name]
    if not ents:
        die("no skill named %s is visible to a session in %s (qargi packs check --target claude-code %s lists them)" % (name, inp["project"], inp["project"]))
    cand = [e for e in ents if e["state"] in ("unmanaged", "drifted")]
    if not cand:
        e = ents[0]
        hint = {"qargi": "it is managed by qargi already", "excluded": "it is hidden (%s), so a session does not load it" % e["detail"],
                "accepted": "it is accepted already (qargi skill unaccept %s %s first, to change the scope)" % (inp["project"], name)}[e["state"]]
        die("%s is %s: %s; nothing to accept" % (name, e["state"], hint))
    kept = [e for e in ents if e["state"] not in ("qargi", "excluded")]
    if len({e.get("hash") for e in kept}) > 1:
        die("%s is visible with different content in %s: an acceptance covers one name and one content; remove or rename the others first" %
            (name, ", ".join(sorted({" ".join(e["where"]) + " " + e["shown"] for e in kept}))))
    e = cand[0]
    if not e.get("hash"):
        die("cannot read the content of %s" % e["shown"])
    t = {"name": name, "hash": e["hash"], "path": e["shown"], "real": e["real"], "where": e["where"], "state": e["state"], "scope": scope}
    print("accept plan for %s: skill %s (%s, content %s)" % (inp["project"], name, e["state"], e["hash"]))
    print("  at:    %s" % e["shown"])
    print("  scope: %s" % ("every project (--user)" if scope == "user" else "project " + inp["project"]))
    if e["state"] == "drifted":
        print("  %s" % e["detail"])
    print("  accepting records this name and content so that qargi stops reporting it; qargi does not manage the skill, and a later change drifts.")
    with open(outfile, "w") as fh:
        json.dump(t, fh)


def table(data, scope, project, create):
    if scope == "user":
        return data.setdefault("user", {}) if create else data.get("user", {})
    p = data.setdefault("projects", {}) if create else data.get("projects", {})
    return p.setdefault(project, {}) if create else p.get(project, {})


def read_for_write(path):
    if not os.path.lexists(path):
        return {"user": {}, "projects": {}}
    try:
        d = load(path)
    except (OSError, ValueError) as e:
        die("%s cannot be read (%s); fix or remove it first. Nothing was changed" % (path, str(e).split("\n")[0]))
    if not isinstance(d, dict) or not isinstance(d.get("user", {}), dict) or not isinstance(d.get("projects", {}), dict):
        die("%s has an unexpected shape; fix or remove it first. Nothing was changed" % path)
    return d


def write_atomic(path, data):
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".accepted.", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_acceptance(path, scope, project, name):
    r = table(read_for_write(path), scope, project, False).get(name)
    if not isinstance(r, dict):
        die("%s is not accepted %s" % (name, "for every project (--user)" if scope == "user" else "for project " + project))
    print(json.dumps(r))


def cmd_store(verb, path, scope, project, name, rest):
    if not NAME_RE.match(name):
        die("not a skill name: " + name)
    data = read_for_write(path)
    if verb == "accept":
        h, p, approved, at = (rest + ["", "", "", ""])[:4]
        if not h:
            die("internal error: no content hash to record")
        table(data, scope, project, True)[name] = {"sha256": h, "path": p, "approved": approved, "at": at}
    else:
        t = table(data, scope, project, False)
        if name not in t:
            die("%s is not accepted %s" % (name, "for every project (--user)" if scope == "user" else "for project " + project))
        del t[name]
        if scope != "user" and not t:
            data["projects"].pop(project, None)
    write_atomic(path, data)


def main():
    a = sys.argv[1:]
    try:
        if len(a) == 3 and a[0] == "scan":
            with open(a[2], "w") as fh:
                json.dump(scan(load(a[1])), fh)
        elif len(a) == 2 and a[0] == "report":
            cmd_report(load(a[1]))
        elif len(a) == 5 and a[0] == "target":
            cmd_target(load(a[1]), a[2], a[3], a[4])
        elif len(a) == 5 and a[0] == "acceptance":
            cmd_acceptance(*a[1:])
        elif len(a) >= 6 and a[0] == "store" and a[1] in ("accept", "unaccept"):
            cmd_store(a[1], a[2], a[3], a[4], a[5], a[6:])
        else:
            die("usage: packs_audit.py scan|report|target|acceptance|store ...")
    except (OSError, ValueError) as e:
        die("%s: %s" % (getattr(e, "filename", None) or "error", getattr(e, "strerror", None) or e))


if __name__ == "__main__":
    main()
