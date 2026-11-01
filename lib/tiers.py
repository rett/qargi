#!/usr/bin/env python3
"""Memory tiers: a project's memory is read from several canon memory-kind stores at fixed ranks. Read-only: nothing here
writes to a tier or to any store.

  python3 -I tiers.py tiers [--project P] [--json] [--ant PATH]   where each tier is, whether it exists, its notes
  python3 -I tiers.py check [--project P] [--ant PATH]            canon check of every existing tier, and the one-tier rule

Tiers, highest first: repo (a directory inside the project's checkout), cloud (the memory store of the project's
answers), project, shared and system (user directories under paths.root()/memory/). The answers may place the four
directory tiers: memory.tiers = {repo: {path}, project: {path}, shared: {path}, system: {path}}; every key is optional.
The reference store is not a tier. A note (canon.is_note) may exist in exactly one tier; the structural files (markers,
READMEs, indexes, tools, archives) repeat in every tier and are exempt. This module is the only one that knows the order.
Importing it creates nothing. QARGI_CANON_FIXTURE_DIR replaces the cloud with <dir>/<store id>.jsonl, as for canon.sh."""
import json, os, re, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import canon, membackend, paths

ORDER = ("repo", "cloud", "project", "shared", "system")
DIRS = ("repo", "project", "shared", "system")
STRUCTURAL = re.compile(r"^/(CANON|README|_template)\.md$|/INDEX\.md$|^/roles/[^/]+/tools/|^/_(archive|conflicts)/")
REPO_DEFAULT = "qargi/memory"
NO_ANT = "ant not installed or not logged in"


def defaults(project, repo_path=""):
    """The four directory tiers where the answers do not place them: {tier: {"kind", "location"}}."""
    base = os.path.join(paths.root(), "memory")
    repo = os.path.join(os.path.expanduser(repo_path), REPO_DEFAULT) if repo_path else ""
    return {"repo": {"kind": "dir", "location": repo},
            "project": {"kind": "dir", "location": os.path.join(base, "projects", project)},
            "shared": {"kind": "dir", "location": os.path.join(base, "shared")},
            "system": {"kind": "dir", "location": os.path.join(base, "system")}}


def problems(tiers):
    """Why memory.tiers is not a valid answer: a list of messages, empty when it is (None and {} are valid)."""
    if tiers is None:
        return []
    if not isinstance(tiers, dict):
        return ["memory.tiers: an object with the keys repo, project, shared, system (each optional)"]
    bad = []
    for k, v in tiers.items():
        p = "memory.tiers.%s" % k
        if k not in DIRS:
            bad.append("%s: not a tier you can place (%s)" % (p, ", ".join(DIRS)))
            continue
        pth = v.get("path") if isinstance(v, dict) else None
        if not isinstance(pth, str) or not pth.strip():
            bad.append("%s: an object {path: a non-empty string}" % p)
        elif k == "repo":
            if pth.startswith(("/", "~")) or ".." in pth.split("/"):
                bad.append("%s.path: a path inside the repository, relative (no leading / or ~, no ..)" % p)
        elif not (pth.startswith("/") or pth == "~" or pth.startswith("~/")):
            bad.append("%s.path: an absolute path or one starting with ~/" % p)
    return bad


def resolve(answers, project):
    """The tiers of a project, in ORDER: [{"tier","kind","location","label","store_id"}]; answers are the stored answers."""
    answers = answers or {}
    mem = answers.get("memory") or {}
    given = mem.get("tiers") if isinstance(mem.get("tiers"), dict) else {}
    repo_path = (answers.get("repo") or {}).get("path") or ""
    d = defaults(project, repo_path)
    for k in DIRS:
        p = (given.get(k) or {}).get("path") if isinstance(given.get(k), dict) else None
        if isinstance(p, str) and p.strip():
            if k == "repo":
                d[k]["location"] = os.path.join(os.path.expanduser(repo_path), p) if repo_path else ""
            else:
                d[k]["location"] = os.path.expanduser(p)
    store = mem.get("memory_store") or None
    out = []
    for t in ORDER:
        if t == "cloud":
            out.append({"tier": t, "kind": "cloud", "location": store or "", "label": "%s-memory" % project, "store_id": store})
        else:
            out.append({"tier": t, "kind": "dir", "location": d[t]["location"], "label": t, "store_id": None})
    return out


def _fixture(tier):
    fd = os.environ.get("QARGI_CANON_FIXTURE_DIR")
    return os.path.join(fd, tier["store_id"] + ".jsonl") if fd and tier.get("store_id") else None


def probe(tier, ant="ant"):
    """-> (status, listing or None, why). status: missing, empty, present or unreachable. Never raises."""
    try:
        if tier["kind"] == "cloud":
            if not tier.get("store_id"):
                return "missing", None, "no memory store recorded"
            fx = _fixture(tier)
            if fx:
                if not os.path.isfile(fx):
                    return "unreachable", None, "no fixture for %s" % tier["store_id"]
                lst = membackend.FixtureBackend(fx).list()
            elif not shutil.which(ant):
                return "unreachable", None, NO_ANT
            else:
                lst = membackend.CloudBackend(tier["store_id"], ant).list()
        else:
            loc = tier.get("location") or ""
            if not loc:
                return "missing", None, "repo.path is not set"
            if not os.path.isdir(loc):
                return "missing", None, "not initialised"
            lst = membackend.DirBackend(loc).list()
    except (membackend.StoreError, OSError, ValueError, KeyError, TypeError) as e:
        return "unreachable", None, NO_ANT if tier["kind"] == "cloud" else "cannot be read: %s" % str(e).splitlines()[0][:120]
    return ("present" if lst else "empty"), lst, ""


def status(tier, ant="ant"):
    return probe(tier, ant)[0]


def listing(tier, ant="ant"):
    """{path: note} of a tier that is present, else None."""
    return probe(tier, ant)[1] or None


def notes_of(lst):
    return sorted(p for p in (lst or {}) if canon.is_note(p) and not STRUCTURAL.search(p))


def collisions(listings):
    """[(path, [tiers])] for a note path held by two or more tiers; listings is {tier: listing or None}."""
    held = {}
    for t in ORDER:
        for p in notes_of(listings.get(t)):
            held.setdefault(p, []).append(t)
    return sorted((p, ts) for p, ts in held.items() if len(ts) > 1)


def check_args(tier, project, roles, marker=None):
    """-> (project_arg, roles_csv) for canon.py check. shared and system carry their own name as the project and the roles
    of the project plus those their marker lists; the others carry the project's name and roles."""
    name = tier["tier"] if isinstance(tier, dict) else tier
    rs = roles.split(",") if isinstance(roles, str) else list(roles)
    if name in ("shared", "system"):
        if isinstance(marker, str):
            marker = canon.parse_marker(marker)
        extra = (marker or {}).get("roles", "").split() if isinstance(marker, dict) else []
        return name, ",".join(sorted(set(r for r in rs + extra if r)))
    return project, ",".join(rs)


def _project(argv_project):
    if argv_project:
        return argv_project
    p = os.environ.get("QARGI_PROJECT")
    if p:
        return p
    try:
        import help as H
        return H.infer_project()
    except BaseException:
        return None


def _answers(project):
    """-> (answers, error)"""
    if not re.fullmatch(r"[a-z][a-z0-9]{0,23}", project or ""):
        return None, "no project: run inside its repository or give --project"
    f = os.path.join(paths.conf(), "projects", project + ".json")
    try:
        with open(f) as h:
            a = json.load(h)
    except OSError:
        return None, "no stored answers for %s: run /qargi-project first" % project
    except ValueError:
        return None, "the stored answers of %s are not valid JSON" % project
    if not isinstance(a, dict):
        return None, "the stored answers of %s are not an object" % project
    bad = problems((a.get("memory") or {}).get("tiers") if isinstance(a.get("memory"), dict) else None)
    if bad:
        return None, "invalid memory.tiers for %s:\n  " % project + "\n  ".join(bad)
    return a, None


def _roles(a):
    r = a.get("roles") if isinstance(a.get("roles"), dict) else {}
    out = list(r)
    if isinstance(a.get("teams"), dict) and a["teams"]:
        out.append("lead")
    return out


def _where(t):
    return t["location"] or "-"


def cmd_tiers(project, a, as_json, ant):
    rows = []
    for t in resolve(a, project):
        st, lst, why = probe(t, ant)
        rows.append(dict(t, status=st, notes=len(notes_of(lst)) if lst is not None else None, why=why))
    ref = (a.get("memory") or {}).get("reference_store") or None
    if as_json:
        print(json.dumps({"project": project, "tiers": [{k: r[k] for k in ("tier", "kind", "location", "label", "store_id", "status", "notes")} for r in rows],
                          "reference": ref}, indent=2))
        return 0
    locs = [_where(r) + (" (%s)" % r["label"] if r["kind"] == "cloud" and r["store_id"] else "") for r in rows]
    w = max(len(x) for x in locs)
    for r, loc in zip(rows, locs):
        if r["status"] == "present":
            n = r["notes"]
            detail = "%d note%s" % (n, "" if n == 1 else "s")
        elif r["status"] == "empty":
            detail = ""
        else:
            detail = "(%s)" % r["why"]
        print(("%-8s %-6s %-*s %-11s %s" % (r["tier"], r["kind"], w, loc, r["status"], detail)).rstrip())
    if ref:
        print("reference: %s (optional, read-only, not composed)" % ref)
    return 0


def _canon_check(name, t, lst, project, roles):
    """Run canon.py check on a dump of the listing -> (output lines, fails, warns)."""
    pa, rcsv = check_args(t, project, roles, (lst.get("/CANON.md") or {}).get("content"))
    fd, dump = tempfile.mkstemp(prefix="qargi-tier-", suffix=".jsonl")
    try:
        with os.fdopen(fd, "w") as f:
            for p in sorted(lst):
                f.write(json.dumps({"type": "memory", "id": lst[p].get("id", ""), "path": p, "content": lst[p]["content"]}) + "\n")
        r = subprocess.run([sys.executable, "-I", os.path.join(HERE, "canon.py"), "check", "--kind", "memory", "--project", pa,
                            "--roles", rcsv, "--store", dump], capture_output=True, text=True)
    finally:
        try:
            os.unlink(dump)
        except OSError:
            pass
    lines = r.stdout.splitlines()
    m = re.match(r"^(\d+) fail, (\d+) warn$", lines[-1]) if lines else None
    if not m:
        return ["FAIL tier %s: the canon check did not run (%s)" % (name, " ".join((r.stderr or "").split())[-120:] or "no output")], 1, 0
    return lines, int(m.group(1)), int(m.group(2))


def cmd_check(project, a, ant):
    tiers = resolve(a, project)
    roles = _roles(a)
    fails = warns = checked = 0
    lists, infos = {}, []
    for t in tiers:
        name = t["tier"]
        st, lst, why = probe(t, ant)
        if st == "present":
            lists[name] = lst
            checked += 1
            print("== tier %s (%s %s)" % (name, t["kind"], t["location"]))
            state, _ = canon.detect("memory", lst)
            if state == "unknown":
                how = ("qargi project set %s memory.memory_store ID" % project) if t["kind"] == "cloud" else \
                      ("qargi project set %s memory.tiers.%s.path DIR" % (project, name))
                print("FAIL tier %s: no canon marker and no known layout; if the directory is wrong, correct it with: %s" % (name, how))
                fails += 1
                continue
            lines, f, w = _canon_check(name, t, lst, project, roles)
            print("\n".join(lines))
            fails += f
            warns += w
        elif st == "missing":
            infos.append("INFO tier %s: missing (qargi memory init %s)" % (name, name) if t["kind"] == "dir"
                         else "INFO tier %s: missing (%s)" % (name, why))
        elif st == "empty":
            infos.append("INFO tier %s: empty (qargi memory init %s)" % (name, name))
        else:
            infos.append("INFO tier %s: unreachable, collisions computed without it (%s)" % (name, why))
    print("== tiers")
    for p, ts in collisions(lists):
        print("FAIL %s: in tiers %s (a note lives in one tier; qargi memory move PATH --from T --to T)" % (p, ", ".join(ts)))
        fails += 1
    for i in infos:
        print(i)
    print("%d fail, %d warn, %d tiers checked" % (fails, warns, checked))
    return 1 if fails else 0


def main(argv):
    usage = "usage: tiers.py tiers|check [--project P] [--json] [--ant PATH]"
    if not argv or argv[0] not in ("tiers", "check"):
        print(usage, file=sys.stderr)
        return 2
    verb, project, as_json, ant, i = argv[0], None, False, "ant", 1
    while i < len(argv):
        o = argv[i]
        if o == "--project" and i + 1 < len(argv):
            project, i = argv[i + 1], i + 2
        elif o == "--ant" and i + 1 < len(argv):
            ant, i = argv[i + 1], i + 2
        elif o == "--json" and verb == "tiers":
            as_json, i = True, i + 1
        else:
            print(usage, file=sys.stderr)
            return 2
    try:
        project = _project(project)
        a, err = _answers(project)
        if err:
            print("qargi: " + err, file=sys.stderr)
            return 1
        return cmd_tiers(project, a, as_json, ant) if verb == "tiers" else cmd_check(project, a, ant)
    except BrokenPipeError:
        return 0
    except Exception as e:
        print("qargi: memory %s failed: %s" % (verb, e), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
