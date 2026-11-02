#!/usr/bin/env python3
"""Which skills would a session of the project's provider, opened in the project's checkout, load, and who vouches for each?

qargi manages the skills of its library and renders them for a project, but a session loads more than that: the skills in the
checkout's project skills directory, in the render, and in the user's skills directory. Where those are, which settings files hide
a skill and under which key all come from the provider's layout (lib/providers/NAME.json, read through lib/provider.py); nothing
here names a provider. A provider without a project skills directory, or without verified skills support, is refused with exit
status 3; one without a user skills directory or a way to hide a skill is audited without those and the section says so.
This audit lists every skill with exactly one state:

  qargi       a library pack with approved content and the same content hash, or a skill under the qargi install's skills/
  accepted    the owner accepted this name with this content (accepted.json)
  drifted     the owner accepted this name, but the content changed since (a finding)
  excluded    switched off in one of the provider's settings files, as its layout says (hidden from the session, never a finding)
  unmanaged   anything else

Content is compared with strict_hash(), not with the shell's content_hash (the hash the library's approvals and the renders record,
which sees regular files only and drops a .pack.json at any depth): strict_hash covers symbolic links (path and target), the
executable bit of a file, empty directories and every .pack.json but the library pack's own record (the top-level one, skipped when
the library pack is hashed). A skill that differs in any of those is not the library pack, and an acceptance covers exactly this
content. The library's approval itself is still the shell's: lib.approved == lib.hash says the pack was not edited since it was approved.

Called by packs.sh, which holds the facts only the shell knows (the library) in an inputs file:
  {project, provider, state, home, checkout, accepted, skills:[{name, where[], shown, real, hash, lib:{hash,approved}|null}]}
  (`scan` finds the skill directories and hashes them with strict_hash, `report` and `target` judge them; lib.hash and lib.approved
  are the shell's content hash of the library pack and the one recorded when it was approved.)

  packs_audit.py scan   INPUTS OUT                     write the visible skill directories as JSON
  packs_audit.py report INPUTS                         print the section; exit 1 when a skill is drifted
  packs_audit.py target INPUTS NAME SCOPE OUT          the skill `skill accept` would record (refuses other states); writes it to OUT
  packs_audit.py acceptance FILE SCOPE PROJECT NAME    print one stored acceptance as JSON, or exit 1
  packs_audit.py store accept|unaccept FILE SCOPE PROJECT NAME [HASH PATH APPROVED AT]   the only writer of accepted.json

Settings files are only ever read. accepted.json is written atomically (temporary file, then rename), mode 600. `store` refuses in a
member run (a directory `qargi local prepare` made, at or above the working directory) and writes only <conf>/packs/accepted.json,
the configuration directory being the environment's (paths.conf(), as the shell's DA_CONF): another FILE is refused.
"""
import hashlib
import json
import os
import re
import shlex
import stat
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marshal_refs  # noqa: E402  (in_member_run)
import paths  # noqa: E402
import provider  # noqa: E402

NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')   # used with fullmatch: a `$` would let a trailing newline through
PLACES = ("checkout", "render", "user")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean(s):
    """s without control characters: names and paths come from the checkout, the render and the home directory."""
    return CTRL_RE.sub("", s) if isinstance(s, str) else str(s)


def say(text=""):
    """print text with the control characters removed from every line (the newlines between lines stay)."""
    print("\n".join(clean(line) for line in text.split("\n")))


def q(s):
    """A word safe to paste into a shell: control characters out, then quoted."""
    return shlex.quote(clean(s))


def die(msg):
    print("qargi: " + clean(msg), file=sys.stderr)
    sys.exit(1)


def load(path):
    with open(path) as fh:
        return json.load(fh)


WOULD = "audit the skills a session would load"


def layout(inp):
    """The provider's layout (with ~ expanded for inp["home"]); exit 3 unless it can serve an audit."""
    provider.require_skills(inp["provider"], WOULD)
    provider.require(inp["provider"], "project_skills_dir", WOULD)
    return provider.layout(inp["provider"], home=inp.get("home") or None)


def places(inp):
    """[(label, directory)] of the three places a session would load skills from."""
    lay = layout(inp)
    out = []
    co = inp.get("checkout") or ""
    if co and os.path.isabs(co) and os.path.isdir(co):
        out.append(("checkout", os.path.join(co, lay["project_skills_dir"])))
    out.append(("render", os.path.join(os.path.abspath(inp["state"]), inp["provider"], inp["project"], lay["project_skills_dir"])))
    if inp.get("home") and lay["user_skills_dir"]:
        out.append(("user", lay["user_skills_dir"]))
    return out


def strict_hash(path, skip_record=False):
    """The strict content hash of the directory path (16 hex digits), or "" when something in it cannot be read. One line per entry,
    sorted by path and encoded as JSON (so no name can fake another line): a symbolic link as its target (it is never followed), a
    regular file as its sha256 and whether any executable bit is set, an empty directory as itself, anything else (a socket, a
    device) by its type. The mode bits other than the executable one, owners and times are not part of it. skip_record leaves out
    the top-level .pack.json: the library pack's record of its own approval, which is not part of the skill."""
    h = hashlib.sha256()

    def add(*rec):
        h.update((json.dumps(rec, ensure_ascii=True) + "\n").encode())

    def walk(d, rel):
        names = sorted(os.listdir(d))
        if not names and rel:
            add("D", rel)
        for n in names:
            r = rel + "/" + n if rel else n
            if skip_record and r == ".pack.json":
                continue
            full = os.path.join(d, n)
            st = os.lstat(full)
            if stat.S_ISLNK(st.st_mode):
                add("L", r, os.readlink(full))
            elif stat.S_ISDIR(st.st_mode):
                walk(full, r)
            elif stat.S_ISREG(st.st_mode):
                f = hashlib.sha256()
                with open(full, "rb") as fh:
                    for chunk in iter(lambda: fh.read(65536), b""):
                        f.update(chunk)
                add("F", r, bool(st.st_mode & 0o111), f.hexdigest())
            else:
                add("O", r, stat.S_IFMT(st.st_mode))

    try:
        walk(path, "")
    except OSError:
        return ""
    return h.hexdigest()[:16]


def library_hash(name, conf=None):
    """strict_hash of the library pack of that name (without its record), or None when the library has no such directory."""
    d = os.path.join(conf or paths.conf(), "packs", "skills", name)
    if not os.path.isdir(d) or os.path.islink(d):
        return None
    return strict_hash(d, skip_record=True)


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
    for e in found.values():
        e["hash"] = strict_hash(e["real"])
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
    """({skill name: settings file that switches it off}, [notes]). The files, the key and the off value are the provider's
    (layout.settings_files, layout.exclusion). Missing files are fine; unreadable or malformed ones are noted."""
    lay = layout(inp)
    exc, off, notes = lay["exclusion"], {}, []
    if not exc or not lay["settings_files"]:
        return off, ["note: provider %s has no way to switch a skill off in a settings file: no skill is reported as excluded" % inp["provider"]]
    key, off_value = exc["file_key"], exc["off_value"]
    co = inp.get("checkout") or ""
    files = []
    for sf in lay["settings_files"]:
        if os.path.isabs(sf["path"]):
            files.append(sf["path"])
        elif co and os.path.isabs(co):
            files.append(os.path.join(co, sf["path"]))
    for f in files:
        if not os.path.lexists(f):
            continue
        try:
            data = load(f)
            ov = data.get(key, {}) if isinstance(data, dict) else None
            if not isinstance(ov, dict):
                raise ValueError("not an object" if ov is None else "%s is not an object" % key)
        except (OSError, ValueError) as e:
            why = e.strerror if isinstance(e, OSError) and e.strerror else str(e).split("\n")[0]
            notes.append("note: cannot read %s (%s): the skills it hides are unknown" % (f, why))
            continue
        for k, v in ov.items():
            if v == off_value:
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
    if not layout(inp)["user_skills_dir"]:
        notes.append("note: provider %s has no user skills directory: user-level skills are not listed" % inp["provider"])
    acc, n2 = read_accepted(inp.get("accepted"))
    notes += n2
    roots = shipped_roots()
    out = []
    for e in inp.get("skills", []):
        e = dict(e)
        h, lib, n = e.get("hash") or "", e.get("lib"), e["name"]
        recs = recorded(acc, inp["project"], n)
        if h and lib and lib.get("approved") and lib["approved"] == lib.get("hash") and library_hash(n) == h:
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
          "excluded": "hidden by {key}", "unmanaged": "not managed or accepted by anyone"}


def offers(inp, e):
    """The commands that would deal with a skill, as text to paste: every name and path quoted. A name that is not a pack name gets
    none ("skipped: unusual name"): it could not be imported or accepted by name, and its text is the repository's, not ours."""
    p, n = inp["project"], e["name"]
    if e["state"] not in ("drifted", "unmanaged"):
        return []
    if not NAME_RE.fullmatch(n):
        return ["    skipped: unusual name (no command is offered for it)"]
    if e["state"] == "drifted":
        return ["    review it, then accept the new content: qargi skill accept %s %s%s" % (q(p), q(n), "" if "checkout" in e["where"] else " --user")]
    out = []
    if "checkout" in e["where"]:
        lib = e.get("lib")
        if lib is None:
            out += ["    to keep it in the library: qargi skill import %s" % q(e["shown"]),
                    "                               qargi skill link %s --scope project --project %s" % (q(n), q(p))]
        else:
            out += ["    a library pack of this name has other content or is not approved: qargi skill show %s" % q(n)]
        out += ["    or accept it as it is:      qargi skill accept %s %s" % (q(p), q(n))]
    else:
        out += ["    to accept it as it is: qargi skill accept %s %s --user" % (q(p), q(n))]
    return out


def cmd_report(inp):
    sk, notes = states(inp)
    say("skills a session would load:")
    if not sk:
        say("  (none)")
    for e in sk:
        extra = ["+".join(e["where"]), (e.get("hash") or "unreadable")[:12]] + ([e["detail"]] if e["detail"] else [])
        say("  %-9s %s  (%s)" % (e["state"], clean(e["name"]), clean(", ".join(extra))))
        for o in offers(inp, e):
            say(o)
    for n in notes:
        say("  " + clean(n))
    present = [s for s in LEGEND if any(e["state"] == s for e in sk)]
    if present:
        exc = layout(inp)["exclusion"] or {}
        say("  legend: " + "; ".join("%s: %s" % (s, LEGEND[s].replace("{key}", exc.get("file_key", "the provider's settings"))) for s in present))
    sys.exit(1 if any(e["state"] == "drifted" for e in sk) else 0)


def cmd_target(inp, name, scope, outfile):
    if not NAME_RE.fullmatch(name):
        die("not a skill name: " + name)
    sk, _ = states(inp)
    ents = [e for e in sk if e["name"] == name]
    if not ents:
        target = layout(inp)["render_target"]
        die("no skill named %s is visible to a session in %s%s" % (name, inp["project"], " (qargi packs check --target %s %s lists them)" % (target, inp["project"]) if target else ""))
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
    say("accept plan for %s: skill %s (%s, content %s)" % (clean(inp["project"]), name, e["state"], e["hash"]))
    say("  at:    %s" % clean(e["shown"]))
    say("  scope: %s" % ("every project (--user)" if scope == "user" else "project " + inp["project"]))
    if e["state"] == "drifted":
        say("  %s" % clean(e["detail"]))
    say("  accepting records this name and content so that qargi stops reporting it; qargi does not manage the skill, and a later change drifts.")
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
    # the text fields are printed by the shell in the unaccept plan: no control character (a newline would forge a line of the plan)
    print(json.dumps({k: clean(v) if k in ("path", "approved", "at") else v for k, v in r.items()}))


def cmd_store(verb, path, scope, project, name, rest):
    if not NAME_RE.fullmatch(name):
        die("not a skill name: " + name)
    if marshal_refs.in_member_run():
        die("skill %s is not available in a member run: only the lead's session records which skills are accepted; nothing was changed" % verb)
    mine = os.path.join(os.path.abspath(paths.conf()), "packs", "accepted.json")
    if os.path.abspath(path) != mine:
        die("the acceptances are written to %s only, not to %s; nothing was changed" % (mine, path))
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
    except provider.Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        sys.exit(3)
    except provider.ProviderError as e:
        die(str(e))
    except (OSError, ValueError) as e:
        die("%s: %s" % (getattr(e, "filename", None) or "error", getattr(e, "strerror", None) or e))


if __name__ == "__main__":
    main()
