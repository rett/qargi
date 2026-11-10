#!/usr/bin/env python3
"""qargi env check: is this checkout set up the way the project says, and is the qargi side of it in place.

  env.py check [--project P] [--repo DIR] [--timeout SECONDS] [--json]

Part 1, the project's own check. The effective doctor command (the project's answer env.doctor_command, else the detected
`doctor` or `check` target; see lib/env.py) is run once as an argument list, with no shell, in the repository, with standard input
closed and a minimal environment (PATH without relative entries, HOME, LANG, LC_ALL, TERM, TMPDIR, GIT_TERMINAL_PROMPT), under a
time limit (--timeout, default 300 s). Its lines are read:
  - a line that begins with missing, fail, failure, error, fatal, not ok, stale, absent, [x], [!] or a cross mark, or ends with
    missing, not found, not installed, not initialised or FAIL, reports a missing item;
  - a line that begins with `expected` or contains one of env.known_failures is an expected failure: shown, not red;
  - every other line is information.
A doctor that exits non-zero without reporting a missing item is itself one missing item. Running the doctor runs the project's code, as
test_command does: it is as trusted as the repository.

The tools the roles declare (roles.<role>.tools, lib/tools.py) are checked after it, for a stored project: a go tool or a binary that is
not installed, is another version (go version -m) or another file (sha256), or sits in a directory PATH lacks, and a declared submodule that
is not initialised or at another commit, are missing items.

With no doctor command a built-in minimum runs instead: every submodule of .gitmodules is initialised; tags are present when the
repository has a remote and releases (a VERSION file or a numbered changelog heading); every tool a pin file names is on PATH, answers
`--version` (`go version`) and, where the pin is a version number, matches its major.minor (a go.mod `go` line and a `>=` range are minimums).

Part 2, the qargi layer, for a stored project and read from the facts qargi already keeps, changing nothing: the checkout's skills, agents
and memory are linked; the project's members are current (STALE, DRIFT and MISSING are missing items); the packs render has no drift
(qargi packs check; a project never applied reads `not applied`, a note); the memory tiers pass qargi memory check. A part that cannot be
checked here (no provider set, no render target) is a note, not a missing item.

The verdict is one line: `ENV OK`, or `ENV INCOMPLETE: N missing (...)`. Exit status 0, 1 (incomplete) or 2 (usage, no such project, no
repository). For a stored project the result is recorded under "check" in state/env/PROJECT.json (mode 600): HEAD, time, verdict, exit status, the
commands; the other keys of the file are kept. The output of the doctor is not kept.
"""
import contextlib, io, json, os, re, shlex, shutil, signal, subprocess, sys, tempfile, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import env as E  # noqa: E402
import paths as P  # noqa: E402
import procenv as PE  # noqa: E402
import tools as T  # noqa: E402

TIMEOUT = 300
MAX_TIMEOUT = 3600
SUB_TIMEOUT = 120                       # a qargi verb run for the qargi layer
READ_CAP = 1024 * 1024                  # bytes of the doctor's output that are read
MAX_LINES = 2000
SHELL_WORDS = {"&&", "||", ";", "|", "&", ">", ">>", "<", "<<", "2>&1"}
BAD = re.compile(r"^[\s>*\-•]*(?:(?:missing|fail(?:ed|ure)?|error|fatal|not\s+ok|stale|absent)(?=[\s:\]\)\-]|$)|\[\s*(?:x|!+)\s*\]|[✗✘✖❌×]|!!)", re.I)
BAD_END = re.compile(r"(?:\bmissing|not\s+found|not\s+installed|not\s+initiali[sz]ed|\bFAIL)\s*[.!]?\s*$", re.I)
EXPECTED = re.compile(r"^[\s>*\-•]*expected\b", re.I)
TOOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.+-]{0,40}")
ALIAS = {"golang": "go", "nodejs": "node", "python3": "python", "py": "python"}
FALLBACK = {"python": ["python3"]}
RELEASED = re.compile(r"(?m)^##\s*\[?v?\d+\.\d+")
SEMVER = re.compile(r"(\d+)\.(\d+)")
USAGE = "usage: qargi env check [--project P] [--repo DIR] [--timeout SECONDS] [--json]"


def usage_error(msg=None):
    if msg:
        print("qargi: " + msg, file=sys.stderr)
    print(USAGE, file=sys.stderr)
    return 2


# ---- running a command ----------------------------------------------------------------------------------------------

def run(argv, cwd, timeout):
    """{exit, timed_out, seconds, text, error}: argv run without a shell in cwd, stdin closed, stdout and stderr together (the first READ_CAP
    bytes are read), in its own session so a timeout ends everything it started."""
    env = PE.child_env()
    exe = argv[0]
    if "/" not in exe and shutil.which(exe, path=env["PATH"]) is None:
        return {"exit": None, "timed_out": False, "seconds": 0.0, "text": "", "error": "%s is not on PATH" % E.clean(exe, 60)}
    t0 = time.monotonic()
    with tempfile.TemporaryFile() as out:
        try:
            proc = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            return {"exit": None, "timed_out": False, "seconds": 0.0, "text": "", "error": "could not run %s: %s" % (E.clean(exe, 60), e.strerror or "error")}
        timed_out = False
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        else:
            with contextlib.suppress(OSError):
                os.killpg(proc.pid, signal.SIGKILL)          # anything it left running
        out.seek(0)
        text = out.read(READ_CAP).decode("utf-8", "replace")
    return {"exit": proc.returncode, "timed_out": timed_out, "seconds": round(time.monotonic() - t0, 1), "text": text, "error": None}


def git(repo, *args):
    """(exit, stdout) of a git command in repo: no prompt, no optional lock, no pager."""
    rc, out, _ = PE.git(*args, repo=repo)
    return (1 if rc is None else rc), out


# ---- the project's doctor --------------------------------------------------------------------------------------------

def known(line, known_failures):
    flat = " ".join(line.split())
    return any(" ".join(k.split()) in flat for k in known_failures if k.strip())


def classify(line, known_failures):
    """ok | missing | expected for one line (information lines are ok)."""
    bad = BAD.search(line) is not None or BAD_END.search(line) is not None
    if EXPECTED.search(line) or (bad and known(line, known_failures)):
        return "expected"
    return "missing" if bad else "ok"


def parse(text, known_failures):
    """([(kind, line)] of the missing and expected lines, the number of other lines)."""
    found, other = [], 0
    for raw in text.splitlines()[:MAX_LINES]:
        line = E.clean(raw.strip(), 160)
        if not line:
            continue
        kind = classify(line, known_failures)
        if kind == "ok":
            other += 1
        else:
            found.append((kind, line))
    return found, other


def doctor(command, repo, known_failures, timeout):
    """The result of running the doctor command: {command, exit, seconds, lines, other, items: [(kind, text)]}. kind is missing or expected."""
    res = {"command": command, "exit": None, "seconds": 0.0, "other": 0, "items": []}
    try:
        argv = shlex.split(command)
    except ValueError as e:
        res["items"].append(("missing", "doctor command is not valid: %s" % e))
        return res
    if not argv or any(a in SHELL_WORDS for a in argv):
        res["items"].append(("missing", "doctor command uses shell syntax and is run without a shell: name a target or a script"))
        return res
    r = run(argv, repo, timeout)
    res["exit"], res["seconds"] = r["exit"], r["seconds"]
    if r["error"]:
        res["items"].append(("missing", "doctor command: " + r["error"]))
        return res
    found, res["other"] = parse(r["text"], known_failures)
    res["items"] = found
    if r["timed_out"]:
        res["items"].append(("missing", "doctor did not finish within %d s" % timeout))
    elif r["exit"] != 0 and not any(k == "missing" for k, _ in found):
        if found:                                            # non-zero, and every item it names is one the owner accepts
            res["note"] = "the doctor exited %d; every item it reports is expected" % r["exit"]
        else:
            res["items"].append(("missing", "doctor exited %d and named no missing item" % r["exit"]))
    return res


# ---- the built-in minimum ------------------------------------------------------------------------------------------------

def version_of(text):
    """(major, minor) of the first number like 1.22 in a tool's answer, else None."""
    m = SEMVER.search(text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def wanted(version):
    """[(op, major, minor or None)] the pin allows (any one of them), or None when the pin is not a version number. op is = or >=; ^ and ~ read as >=."""
    out = []
    for part in re.split(r"[\s,]+|\|\|", version):
        if not part:
            continue
        m = re.fullmatch(r"(>=|=|\^|~)?v?(?:go)?(\d+)(?:\.(\d+))?(?:\.\d+)?(?:[-+][0-9A-Za-z.+-]*)?", part)
        if not m:
            return None                                     # latest, system, lts/*, a range with x or a bound we do not read
        out.append((">=" if m.group(1) in (">=", "^", "~") else "=", int(m.group(2)), None if m.group(3) is None else int(m.group(3))))
    return out or None


def matches(have, op, major, minor):
    if minor is None:
        return have[0] >= major if op == ">=" else have[0] == major
    return have >= (major, minor) if op == ">=" else have == (major, minor)


def pinned_tools(pins):
    """{tool: [(file, version)]}: the tools a pin file names that can be asked for their version. A go.mod go line is a minimum."""
    tools = {}
    for p in pins:
        tool = ALIAS.get(p["tool"], p["tool"])
        if tool == "toolchain" or not TOOL_NAME.fullmatch(tool):
            continue                  # go.mod's toolchain line repeats its go line; a backend-qualified name (npm:x, aqua:y/z) is not asked
        version = ">=" + p["version"] if p["file"] == "go.mod" else p["version"]
        tools.setdefault(tool, []).append((p["file"], version))
    return tools


def check_tool(tool, pinned, repo):
    """The missing items of one tool: not on PATH, no answer to --version, or a version that is not what a pin names."""
    path = PE.child_env()["PATH"]
    name = next((n for n in [tool] + FALLBACK.get(tool, []) if shutil.which(n, path=path)), None)
    if name is None:
        return ["%s is not installed (pinned in %s)" % (tool, ", ".join(sorted({f for f, _ in pinned})))]
    cmd = [name, "version"] if name == "go" else [name, '--version']
    r = run(cmd, repo, 10)
    if r["error"] or r["timed_out"] or r["exit"] != 0:
        return ["%s does not answer %s" % (tool, " ".join(cmd[1:]))]
    have = version_of(r["text"])
    items = []
    for f, v in pinned:
        w = wanted(v)
        if w is None or have is None:
            continue
        if not any(matches(have, *x) for x in w):
            items.append("%s %d.%d does not match %s %s" % (tool, have[0], have[1], f, E.clean(v, 40)))
    return items


def builtin(d, repo):
    """The built-in minimum when the project has no doctor command: {items: [(kind, text)], notes: [], checked: [what was looked at]}."""
    items, notes, checked = [], [], []
    repo_ok = git(repo, "rev-parse", "HEAD")[0] == 0
    if d["submodules"]:
        if not repo_ok:
            notes.append(".gitmodules lists submodules but this is not a git work tree: not checked")
        else:
            rc, out = git(repo, "submodule", "status")
            state = {}
            for ln in out.splitlines():
                m = re.match(r"^([ +\-U])[0-9a-f]{40,64} (.+?)(?: \(.*\))?$", ln)
                if m:
                    state[m.group(2)] = m.group(1)
            for m in d["submodules"]:
                path = m["path"] or m["name"]
                if rc != 0 or state.get(path) in (None, "-", "U"):
                    items.append(("missing", "submodule %s is not initialised (git submodule update --init --recursive)" % E.clean(path, 80)))
            checked.append("%d submodule(s)" % len(d["submodules"]))
    if repo_ok:
        has_remote = bool(git(repo, "remote")[1].strip())
        tags = bool(git(repo, "tag", "-l")[1].strip())
        versioned = os.path.isfile(os.path.join(repo, "VERSION")) or any(RELEASED.search(_read(repo, f)) for f in ("CHANGELOG.md", "CHANGES.md"))
        if has_remote and not tags:
            if versioned:
                items.append(("missing", "no tags are fetched but the project has releases (git fetch --tags)"))
            else:
                notes.append("the repository has a remote and no tags; if the remote has some, git fetch --tags")
        checked.append("tags")
    tools = pinned_tools(d["pins"])
    for tool in sorted(tools):
        items += [("missing", t) for t in check_tool(tool, tools[tool], repo)]
    if tools:
        checked.append("%d pinned tool(s)" % len(tools))
    return {"items": items, "notes": notes, "checked": checked}


def _read(repo, rel):
    try:
        with open(os.path.join(repo, rel), "rb") as f:
            return f.read(65536).decode("utf-8", "replace")
    except OSError:
        return ""


# ---- the tools the roles declare ---------------------------------------------------------------------------------------------

def declared_tools(answers, repo):
    """{rows, items, notes} for roles.<role>.tools: one row, and a missing item for each tool that is not there, not the declared one, or off PATH."""
    rows, items, notes, counts = [], [], [], {"ok": 0}
    entries = T.declared(answers)
    if not entries:
        return {"rows": [], "items": [], "notes": []}
    for t in entries:
        state, text = T.status(t, repo)
        counts[state] = counts.get(state, 0) + 1
        if state == "note":
            notes.append(text)
        elif state != "ok":
            items.append(("missing", text))
    rows.append(("tools", "%d declared (roles.<role>.tools): %s" % (len(entries), ", ".join("%d %s" % (n, k) for k, n in counts.items() if n))))
    return {"rows": rows, "items": items, "notes": notes}


# ---- the qargi layer ---------------------------------------------------------------------------------------------------

def sub(args, width=160):
    """(exit, output lines) of a qargi verb run read-only for the qargi layer, each line made safe to print and cut to width characters (a caller
    that parses the end of a line asks for more). (Flags of other commands are in single quotes: the help test reads a double-quoted flag as one
    this script parses.)"""
    qargi = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "qargi")
    try:
        r = subprocess.run([qargi] + args, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=SUB_TIMEOUT)
    except subprocess.TimeoutExpired:
        return None, ["timed out after %d s" % SUB_TIMEOUT]
    except OSError as e:
        return None, ["could not run: %s" % e.__class__.__name__]
    return r.returncode, [E.clean(x.strip(), width) for x in (r.stdout + r.stderr).splitlines() if x.strip()]


def quietly(fn, *a, keep=()):
    """fn(*a), or RuntimeError with the refusal text of a call that dies (the link engine prints and exits). Its printing is held back;
    the exceptions in keep pass through."""
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            return fn(*a)
    except SystemExit:
        said = (err.getvalue() or out.getvalue()).strip().removeprefix("qargi: ").splitlines()
        raise RuntimeError(E.clean(said[-1] if said else "refused", 160))
    except keep:
        raise
    except Exception as e:                                    # a broken answers file or definition must not stop the check
        raise RuntimeError(E.clean(str(e) or e.__class__.__name__, 160))


def links(project, repo):
    """[(row text, missing item or None)] for the checkout's skills, agents and memory links."""
    import project_link as PL, linker
    keep = (PL.Skip, PL.Missing)
    rows = []
    here = os.getcwd()
    try:
        os.chdir(repo)
        ctx = quietly(PL.Context, project)
        for res in PL.RESOURCES:
            try:
                lk = quietly(ctx.link_of, res, keep=keep)
                facts = quietly(linker.plan, "link", lk, keep=keep)
            except RuntimeError as e:
                rows.append(("%s: not checked, %s" % (res, e), None))
                continue
            except PL.Skip as e:
                rows.append(("%s: not linked by this runtime (%s)" % (res, E.clean(str(e), 100)), None))
                continue
            except PL.Missing as e:
                rows.append(("%s: nothing to link yet (%s)" % (res, E.clean(str(e), 100)), None))
                continue
            if facts["state"] == "linked":
                rows.append(("%s: linked" % res, None))
            else:
                rows.append(("%s: not linked in this checkout (qargi project link %s --resource %s)" % (res, project, res),
                             "%s are not linked in this checkout" % res))
    finally:
        os.chdir(here)
    return rows


def qargi_layer(project, answers, repo):
    """{rows: [(label, text)], items: [(kind, text)]}: link, members, packs and memory, each read from what qargi already keeps."""
    rows, items = [], []

    def row(label, text, missing=None):
        rows.append((label, text))
        if missing:
            items.append(("missing", missing))

    row("project", "%s (answers found)" % project)
    try:
        for text, miss in links(project, repo):
            row("link", text, miss)
    except RuntimeError as e:
        row("link", "not checked, %s" % e)
    except Exception as e:
        row("link", "not checked, %s" % e.__class__.__name__)
    rc, lines = sub(["agent", "list", "--project", project], width=8192)   # the state is at the end of a line, after the member file's path: never cut
    members = [ln for ln in lines if re.match(r"^\S+\s+\S+\s+\S+\s+\S+/\S+\s+\S+", ln)]
    if rc != 0:
        row("members", "not checked: %s" % (E.clean(lines[0], 160) if lines else "agent list failed"))
    elif not members:
        row("members", "none yet")
    else:
        bad = []
        for ln in members:
            m = re.search(r"\(((?:STALE|DRIFT|MISSING)(?:, (?:STALE|DRIFT|MISSING))*)(?:: [^)]*)?\)\s*$", ln)
            if m:
                bad.append("%s %s" % (ln.split()[1], m.group(1).replace(", ", "+")))
        row("members", "%d current" % (len(members) - len(bad)) + (", " + "; ".join(bad) if bad else ""),
            "members not current: " + "; ".join(bad) + " (qargi agent refresh NAME --project %s)" % project if bad else None)
    target = packs_target(answers, project)
    if target is None:
        row("packs", "not checked: no local runtime with a render target")
    else:
        rc, lines = sub(["packs", "check", '--target', target, project])
        findings = [ln for ln in lines if not ln.startswith(("skills a session would load", "note:")) and re.match(r"^(?:drift|finding|problem|FAIL|missing|shadow|tamper|warning)", ln, re.I)] or lines
        if rc == 0 and any(ln.startswith("not applied") for ln in lines):   # no render yet: packs check passes, and there is nothing to have drifted
            row("packs", "not applied (qargi packs apply --target %s %s)" % (target, project))
        elif rc == 0:
            row("packs", "no drift")
        else:
            row("packs", "drift (qargi packs check --target %s %s): %s" % (target, project, findings[0] if findings else "exit %s" % rc),
                "packs drift (qargi packs check --target %s %s)" % (target, project))
    rc, lines = sub(["memory", "check", "--project", project])
    if rc == 0:
        row("memory", "tiers pass the canon")
    else:
        why = next((ln for ln in lines if re.search(r"fail|error|twice|two tiers|in 2|duplicate", ln, re.I)), lines[0] if lines else "exit %s" % rc)
        row("memory", "check failed: %s" % why, "memory check failed: %s" % why)
    return {"rows": rows, "items": items}


def packs_target(answers, project):
    """The render target of the project's local runtime, else None."""
    try:
        import provider
        rt = quietly(provider.provider_of, answers, "local", project)
        return quietly(provider.require, rt, "render_target", "check the packs render")
    except Exception:
        return None


# ---- the verb ----------------------------------------------------------------------------------------------------------

def parse_args(argv):
    o = {"project": None, "repo": None, "timeout": TIMEOUT, "json": False}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--project", "--repo", "--timeout") and i + 1 < len(argv):
            o[a[2:]] = argv[i + 1]
            i += 2
        elif a == "--json":
            o["json"] = True
            i += 1
        else:
            return None
    try:
        o["timeout"] = int(o["timeout"])
    except ValueError:
        return None
    if not 1 <= o["timeout"] <= MAX_TIMEOUT:
        return None
    return o


def resolve(o):
    """(project, answers, repo) or (None, message) when the project or the repository cannot be found."""
    project, repo = o["project"], o["repo"]
    answers = None
    if project is not None:
        answers = E.answers_of(project)
        if answers is None:
            return None, "no such project '%s' (qargi project list)" % project
    elif repo is None:
        project = os.environ.get("QARGI_PROJECT") or E.project_for_dir(os.getcwd())
        answers = E.answers_of(project) if project else None
        project = project if answers is not None else None
    else:
        project = E.project_for_dir(repo)
        answers = E.answers_of(project) if project else None
    if repo is None:
        rp = ((answers or {}).get("repo") or {}).get("path") or ""
        if project is not None and not rp:
            return None, "project %s has no repo.path; give --repo DIR" % project
        repo = os.path.expanduser(rp) if rp else E.repo_root_of(os.getcwd())
    if not os.path.isdir(repo):
        return None, "%s is not a directory" % repo
    return (project, answers, os.path.realpath(repo)), None


def verdict_of(missing):
    if not missing:
        return "ENV OK"
    shown = "; ".join(E.clean(t, 70) for t in missing[:5]) + ("; and %d more" % (len(missing) - 5) if len(missing) > 5 else "")
    return "ENV INCOMPLETE: %d missing (%s)" % (len(missing), shown)


def record(project, d, repo, verdict, code, expected, missing, command, builtin_used):
    """state/env/PROJECT.json, mode 600: the file is read again and its "check" key set (HEAD, time, the verdict without the names of what is
    missing, which are lines the doctor printed, the commands); every other key, such as apply's, is kept; written through a temporary file."""
    rc, head = git(repo, "rev-parse", "HEAD")
    dest = os.path.join(P.state(), "env")
    os.makedirs(dest, mode=0o700, exist_ok=True)
    entry = {"repo": repo, "head": head.strip() if rc == 0 else "",
           "time": PE.now(), "verdict": verdict.split(" (")[0], "exit": code,
           "missing": len(missing), "expected": expected, "doctor_command": command, "builtin_minimum": builtin_used,
           "dry_run_command": d["commands"]["dry_run_command"]["command"]}
    final = os.path.join(dest, project + ".json")
    try:
        with open(final) as f:
            doc = json.load(f)
    except (OSError, ValueError):
        doc = {}
    doc = doc if isinstance(doc, dict) else {}
    doc["check"] = entry
    fd, tmp = tempfile.mkstemp(prefix=".%s." % project, dir=dest)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(doc, f, indent=2, sort_keys=True)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, final)
    except OSError:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def check(argv):
    o = parse_args(argv)
    if o is None:
        return usage_error()
    found, why = resolve(o)
    if found is None:
        return usage_error(why)
    project, answers, repo = found
    d = E.effective(repo, answers)
    cmd = d["commands"]["doctor_command"]
    items, notes, rows = [], list(d["notes"]), []
    if cmd["command"]:
        res = doctor(cmd["command"], repo, d["known_failures"], o["timeout"])
        items += res["items"]
        notes += [res["note"]] if res.get("note") else []
        rows.append(("doctor", "%s   [%s]   %s, %.1f s, %d other line(s)" % (cmd["command"], cmd["source"], "exit %s" % res["exit"] if res["exit"] is not None else "not run", res["seconds"], res["other"])))
        doctor_json = {"command": cmd["command"], "source": cmd["source"], "exit": res["exit"], "seconds": res["seconds"]}
    else:
        b = builtin(d, repo)
        items += b["items"]
        notes += b["notes"]
        rows.append(("doctor", "none; built-in minimum (%s)" % (", ".join(b["checked"]) or "nothing to check: no submodule, tag rule or pin applies")))
        doctor_json = {"command": None, "builtin": b["checked"]}
    layer = None
    if project is not None:
        tl = declared_tools(answers, repo)
        rows += tl["rows"]
        items += tl["items"]
        notes += tl["notes"]
        layer = qargi_layer(project, answers, repo)
        items += layer["items"]
    # an item that matches an accepted failure is expected, whichever part found it
    items = [("expected", t) if k == "missing" and known(t, d["known_failures"]) else (k, t) for k, t in items]
    missing = [t for k, t in items if k == "missing"]
    expected = [t for k, t in items if k == "expected"]
    verdict = verdict_of(missing)
    code = 1 if missing else 0
    if o["json"]:
        out = {"project": project, "repo": repo, "verdict": verdict, "exit": code, "missing": missing, "expected": expected, "doctor": doctor_json,
               "qargi": [{"part": a, "text": b} for a, b in layer["rows"]] if layer else None, "notes": notes}
        print(json.dumps(out, indent=2, sort_keys=True))
    else:
        print("environment check of %s (%s)" % (project or "no stored project", repo))
        for a, b in rows + (layer["rows"] if layer else []):
            print("%-10s%s" % (a + ":", b))
        for t in missing:
            print("%-10s%s" % ("missing:", E.clean(t, 160)))
        for t in expected:
            print("%-10s%s" % ("expected:", E.clean(t, 160)))
        for t in notes:
            print("%-10s%s" % ("note:", E.clean(t, 200)))
        print(verdict)
    if project is not None:
        try:
            record(project, d, repo, verdict, code, len(expected), missing, cmd["command"], not cmd["command"])
        except OSError as e:
            print("qargi: the result could not be recorded: %s" % (e.strerror or "error"), file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(check(sys.argv[1:]))
