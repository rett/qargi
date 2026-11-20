#!/usr/bin/env python3
"""qargi doctor [PROJECT] [--project PROJECT] [--json] [--strict]: a read-only check of the host that qargi runs on. One line per check,
`ok|warn|unknown  name: detail`; a warning is followed by indented lines that say what you can do, and nothing is ever run for you.
The command does not fail on a finding: exit 0, or 1 with --strict when any check warns (2 for a usage error or a project that is not stored).

  remove-ipc     logind RemoveIPC (busctl, QARGI_BUSCTL) and the user's linger (loginctl, QARGI_LOGINCTL): with RemoveIPC on and no
                 linger, logind removes the user's IPC objects, among them what lives in /dev/shm, when the last session ends.
  guard          the hook command a member runs, `qargi __guard`, is found on PATH and answers like the guard (a harmless call is
                 allowed, `git push` is refused); with a project, the members whose rendered file is missing, stale or edited.
  shm            free space under the run temporary parent (/dev/shm, or QARGI_RUN_TMP) and the orphaned qargi-run.* directories
                 there (lib/orphans.sh, the listing `qargi local clean --orphans` prints).
  window-source  where the context-window table of the project's runtime comes from (its definition, or the answer
                 lead.context_window) and whether each model id the project's roles name is in it, and the model of the lead's own
                 session (the last turn of its transcript, read only): a model that is in neither warns, since its window is only
                 assumed and no percentage or compact advice is given for it. A lead model that cannot be determined is not a warning.
  tools          flock and timeout are on PATH: flock keeps two runs of a finishing verb, and the writers of the ref journal and the records, apart;
                 timeout bounds the questions put to a remote. A missing one warns, with what each is for and the package that has it.
  install        the install records of install.sh in the live configuration directory (install.d, install.json; read with
                 lib/install_record.py, the lock is not taken): the tool, its source and version, and every runtime installed for
                 the user and in a project. It warns on an install.manifest (or project-N.manifest) of qargi 0.3.1 or earlier still there (no longer read), a recorded
                 link (or copy) that is missing, dangling or now points elsewhere, a recorded version other than the VERSION of the
                 recorded tool, and a record that cannot be read; `unknown` when nothing is installed. --json adds the facts as fields.
  verify-environment
                 the project answer verify.environment (the whole-suite runs of the two verify verbs start under a declared environment):
                 off, or on with what it needs of the host. The cpu part runs the suite in a transient cgroup scope (systemd-run --user
                 --scope, systemd 254 or newer, found on the clean PATH as the launcher finds it), so with the setting on and cpu_quota not
                 null a missing or older systemd-run warns, with the refusal code the verify would give. The declaration is also compared with
                 the one qargi last accepted (the state file verify-env.json): an answers file edited by hand, an invalid declaration or a
                 state file that cannot be read warns. Reads only: no scope is made (the verify verb makes the attempt).
  project-env    the last `qargi env check` recorded for the project (state/env/PROJECT.json): `last env check <verdict> at <time>`, a
                 warning when that verdict is not ENV OK, `unknown  never run` when none was recorded. It only reads the record: the
                 project's doctor is never run here (qargi env check runs it).

A check that cannot be made (no logind, no tool, no project) is `unknown`, never a warning. Only reads: no file is written, no
directory is removed, nothing is changed on the host."""
import contextlib, io, json, os, pwd, re, shutil, subprocess, sys, tempfile  # noqa: E401

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths as PA  # noqa: E402

LOW_FREE_PCT = 10          # a /dev/shm with less free than this warns (QARGI_DOCTOR_MIN_FREE, in percent, moves it)
ORPHAN_DAYS = 2            # the default of `qargi local clean --orphans`
PROBE_SECS = 20            # a tool that does not answer in this time is unknown
USAGE = "usage: qargi doctor [PROJECT | --project PROJECT] [--json] [--strict]"


def clean(v, n=300):
    """Text from a tool or a file made safe to print: control characters become ?, the length is cut."""
    s = "".join(c if c.isprintable() else "?" for c in str(v).strip())
    return s if len(s) <= n else s[:n - 1] + "…"


def check(name, status, detail, fix=()):
    return {"name": name, "status": status, "detail": detail, "fix": list(fix)}


def run(argv, stdin=None, cwd=None, env=None):
    """(returncode, stdout, stderr) of a program, or (None, '', reason) when it is not there or does not answer. The environment is the caller's, plus env."""
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=PROBE_SECS, cwd=cwd,
                           env=dict(os.environ, **env) if env else None, stdin=None if stdin is not None else subprocess.DEVNULL)
    except FileNotFoundError:
        return None, "", "%s not found" % argv[0]
    except PermissionError:
        return None, "", "%s cannot be run" % argv[0]
    except subprocess.TimeoutExpired:
        return None, "", "%s did not answer within %d seconds" % (os.path.basename(argv[0]), PROBE_SECS)
    except OSError as e:
        return None, "", "%s: %s" % (argv[0], e.strerror or e.__class__.__name__)
    return r.returncode, r.stdout, r.stderr


def first_line(text):
    for line in str(text).splitlines():
        if line.strip():
            return clean(line)
    return ""


# ---------------------------------------------------------------------------------------------------------------- remove-ipc

def user_name():
    try:
        return pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return os.environ.get("USER") or str(os.getuid())


def check_remove_ipc():
    name = "remove-ipc"
    busctl = os.environ.get("QARGI_BUSCTL") or "busctl"
    loginctl = os.environ.get("QARGI_LOGINCTL") or "loginctl"
    rc, out, err = run([busctl, "get-property", "org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager", "RemoveIPC"])
    if rc is None:
        return check(name, "unknown", "cannot ask logind: %s (no systemd, or QARGI_BUSCTL names a program that is not there)" % clean(err))
    if rc != 0:
        return check(name, "unknown", "logind did not answer: %s" % (first_line(err) or "busctl exit status %d" % rc))
    words = out.split()
    if len(words) != 2 or words[0] != "b" or words[1] not in ("true", "false"):
        return check(name, "unknown", "logind answered something else than a boolean: %s" % clean(out))
    if words[1] == "false":
        return check(name, "ok", "logind RemoveIPC is no: the user's IPC objects are kept when the last session ends")
    user = user_name()
    rc, out, err = run([loginctl, "show-user", user, "-p", "Linger"])
    if rc is None:
        return check(name, "unknown", "logind RemoveIPC is yes, and the linger of %s cannot be read: %s" % (user, clean(err)))
    if rc != 0:
        return check(name, "unknown", "logind RemoveIPC is yes, and the linger of %s cannot be read: %s" % (user, first_line(err) or "loginctl exit status %d" % rc))
    linger = ""
    for line in out.splitlines():
        if line.startswith("Linger="):
            linger = line[len("Linger="):].strip()
    if linger == "yes":
        return check(name, "ok", "logind RemoveIPC is yes, but %s lingers: the user never fully logs out, so the IPC objects stay" % user)
    if linger != "no":
        return check(name, "unknown", "logind RemoveIPC is yes, and loginctl did not say whether %s lingers: %s" % (user, clean(out)))
    return check(name, "warn",
                 "logind RemoveIPC is yes and %s has no linger: when the last session of %s ends, logind removes the user's IPC objects, "
                 "among them what lives in /dev/shm, and the temporary directories of the runs that are still going with it" % (user, user),
                 ["fix, either (nothing is run for you):",
                  "  a drop-in /etc/systemd/logind.conf.d/remove-ipc.conf with the two lines",
                  "      [Login]",
                  "      RemoveIPC=no",
                  "    then: sudo systemctl reload systemd-logind",
                  "  or keep the user logged in in the background: loginctl enable-linger %s" % user])


# ---------------------------------------------------------------------------------------------------------------- guard

PROBES = (("a harmless call", "true", 0), ("git push", "git push origin HEAD", 2))


def members_recorded():
    """True when this host has a members file (qargi agent add makes it): without one no member is recorded."""
    return os.path.isfile(os.path.join(PA.conf(), "agents.json"))


def member_states(project):
    """[(member, state)] of the project's members whose file is missing, stale or edited (qargi agent list: the one place that knows), or None when that cannot be read
    (qargi agent list fails). A host with no members file has no member to be stale: [] (agent list is not run, since it would make the file)."""
    if not members_recorded():
        return []      # no member was ever added on this host; agent list would make the file, and doctor makes nothing
    rc, out, _ = run([os.path.join(os.path.dirname(HERE), "bin", "qargi"), "agent", "list", "--project", project], env={"DA_NOSETUP": "1"})
    if rc != 0:
        return None
    found = []
    for line in out.splitlines():
        m = re.search(r"\(((?:MISSING|STALE|DRIFT)(?:, (?:MISSING|STALE|DRIFT))*): qargi agent refresh ", line)
        words = line.split()
        if m and len(words) > 1:
            found.append((clean(words[1], 80), m.group(1).replace(", ", "+")))
    return found


def check_guard(project):
    name = "guard"
    qargi = shutil.which("qargi")
    if not qargi:
        return check(name, "warn", "qargi is not on PATH, so the hook command of a member, qargi __guard, cannot run and a member is not held back",
                     ["fix: install the tool (install.sh --user) or put the bin directory of a checkout first on PATH; the hook calls qargi from PATH"])
    seen = []
    for what, command, want in PROBES:
        call = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": "/"})
        rc, _, err = run([qargi, "__guard"], stdin=call)
        if rc is None:
            return check(name, "warn", "%s does not answer as a guard: %s" % (qargi, clean(err)),
                         ["fix: reinstall the tool (install.sh --user); a hook that does not answer leaves the member unguarded or blocked"])
        if rc != want:
            seen.append("%s: exit status %d, wanted %d" % (what, rc, want))
    if seen:
        return check(name, "warn", "%s __guard does not behave as the guard (%s)" % (qargi, "; ".join(seen)),
                     ["fix: reinstall the tool (install.sh --user), or put the bin directory of the checkout you mean first on PATH"])
    detail = "%s __guard allows a harmless call and refuses git push" % qargi
    if not project:
        return check(name, "ok", detail + " (no project, so the members were not checked)")
    if not members_recorded():
        return check(name, "ok", detail + "; no member is recorded on this host, so there is none to be stale")
    states = member_states(project)
    if states is None:
        return check(name, "unknown", detail + "; the members of project %s could not be read (qargi agent list)" % project)
    if states:
        return check(name, "warn", detail + ", but the members of project %s are not current: %s" % (project, ", ".join("%s %s" % s for s in states)),
                     ["fix: qargi agent refresh %s --project %s" % (m, project) for m, _ in states])
    return check(name, "ok", detail + "; the members of project %s are current" % project)


# ---------------------------------------------------------------------------------------------------------------- tools

# the programs qargi's scripts call that a minimal host may lack: name, what qargi uses it for
TOOLS = (("flock", "the locks of the finishing verbs and the writers of the ref journal and the records"),
         ("timeout", "the bound on a question put to a remote"))


def check_tools():
    name = "tools"
    missing = [(t, why) for t, why in TOOLS if shutil.which(t) is None]
    if not missing:
        return check(name, "ok", "%s found on PATH" % " and ".join(t for t, _ in TOOLS))
    detail = "; ".join("%s is not on PATH (%s)" % (t, why) for t, why in missing)
    fix = ["fix: install %s (util-linux has flock, coreutils has timeout; make bootstrap installs both), or put the directory that has it on PATH" % " and ".join(t for t, _ in missing)]
    return check(name, "warn", detail, fix)


# ---------------------------------------------------------------------------------------------------------------- verify-environment

def systemd_run_version():
    """-> (path, version, first line): systemd-run found on the clean PATH, as the launcher finds it, and its version number (None when its
    first line gives none). path is None when it is not there."""
    import procenv
    path = shutil.which("systemd-run", path=procenv.clean_path())
    if not path:
        return None, None, "systemd-run is not on PATH"
    rc, out, err = run([path, "--version"])
    line = first_line(out) or first_line(err)
    m = re.match(r"systemd (\d+)", line)
    return path, (int(m.group(1)) if m else None), line or "no version line"


def check_verify_environment(project):
    """The answer verify.environment of the project: off, or on with what the cpu part needs of this host (systemd-run, MIN_SYSTEMD or newer),
    and whether the answers still hold the declaration qargi last accepted. Reads the answers, the state entry and systemd-run --version."""
    name = "verify-environment"
    if not project:
        return check(name, "unknown", "no project (name one, or run inside its repository): the setting belongs to the project")
    import provider as P
    import suite_env as SE
    answers = P.project_answers(project, PA.conf())
    if not answers:
        return check(name, "unknown", "no stored answers for project %s" % clean(project, 80))
    verify = answers.get("verify")
    decl = verify.get("environment") if isinstance(verify, dict) else None
    change = "qargi project set %s verify.environment JSON (a loosening takes a plan token and the owner's words)" % clean(project, 80)
    try:
        norm = SE.normalise(decl)
    except SE.Invalid as e:
        return check(name, "warn", "verify.environment of project %s is not valid (%s); verify refuses with %s" % (
                     clean(project, 80), clean("; ".join(e.problems), 300), SE.CODE_INVALID), ["fix: " + change])
    sink = io.StringIO()
    state = SE.state_file(PA.state())
    try:
        with contextlib.redirect_stderr(sink):
            same = SE.approved_check(project, decl, PA.state())
    except SystemExit:
        return check(name, "warn", "the declarations qargi accepted cannot be read (%s: %s); verify refuses with %s" % (
                     clean(tilde(state), 160), first_line(sink.getvalue()) or "damaged", SE.CODE_CHANGE_UNAPPROVED),
                     ["fix: restore %s, or remove it by hand and declare again with %s" % (clean(tilde(state), 160), change)])
    if not same["equal"]:
        return check(name, "warn", "verify.environment in the answers of project %s (%s) is not the declaration qargi last accepted (%s); verify refuses with %s" % (
                     clean(project, 80), same["answers"][:12], same["state"][:12], SE.CODE_CHANGE_UNAPPROVED),
                     ["fix: restore the answers, or change the setting with " + change])
    if norm is None:
        return check(name, "ok", "off for project %s: whole-suite runs start as they always did" % clean(project, 80))
    quota = norm["cpu_quota"]
    on = "on for project %s (id %s, fds %s, cpu_quota %s)" % (clean(project, 80), SE.suite_env_id(norm), norm["fds"], json.dumps(quota))
    if quota is None:
        return check(name, "ok", on + "; the cpu part is off, so no scope and no systemd-run is needed")
    path, version, line = systemd_run_version()
    if path is None:
        return check(name, "warn", on + "; systemd-run is not on PATH, so verify refuses with %s" % SE.CODE_NO_SYSTEMD_RUN,
                     ["fix: install systemd %d or newer with its user manager, or declare cpu_quota null (the cpu part off)" % SE.MIN_SYSTEMD,
                      "  to run once without it: qargi feature verify NAME --waive-environment cpu --plan TOKEN --approved WORDS (the token comes from a refusal)"])
    if version is None or version < SE.MIN_SYSTEMD:
        return check(name, "warn", on + "; systemd-run reports %r, %d or newer is needed, so verify refuses with %s" % (clean(line, 80), SE.MIN_SYSTEMD, SE.CODE_SYSTEMD_TOO_OLD),
                     ["fix: update systemd, or declare cpu_quota null (the cpu part off)"])
    return check(name, "ok", on + "; systemd-run %d is on PATH (the user manager is not asked here: the verify verb makes the attempt)" % version)


# ---------------------------------------------------------------------------------------------------------------- install

LIST_MAX = 3              # paths named in the line of a finding; --json lists them all


def tilde(p):
    """A path as a reader wants it: the home directory as ~."""
    home = os.path.expanduser("~").rstrip("/")
    return "~" + p[len(home):] if home and home != "/" and (p == home or p.startswith(home + "/")) else p


def some(paths):
    shown = ", ".join(clean(tilde(p), 160) for p in paths[:LIST_MAX])
    return shown + (" and %d more" % (len(paths) - LIST_MAX) if len(paths) > LIST_MAX else "")


def link_findings(m):
    """(missing, moved) of the paths manifest m says the install made: a link or copy that is not there (or a link whose target is gone),
    and a link that now points elsewhere or was replaced by something else. Paths only: nothing is opened but the links."""
    missing, moved = [], []
    for k, p, t in m.lines:
        if k == "L":
            if not os.path.lexists(p):
                missing.append({"path": p, "target": t, "why": "not there"})
            elif not os.path.islink(p):
                moved.append({"path": p, "target": t, "now": None, "why": "no longer a link"})
            else:
                now = os.readlink(p)
                if now != t:
                    moved.append({"path": p, "target": t, "now": now, "why": "points elsewhere"})
                elif not os.path.exists(p):
                    missing.append({"path": p, "target": t, "why": "its target is gone"})
        elif k == "C" and not os.path.lexists(p):
            missing.append({"path": p, "target": None, "why": "not there"})
    return missing, moved


def skills_of(m):
    """The qargi-* skills manifest m records directly in its skills directories."""
    return sorted({os.path.basename(p) for k, p, _ in m.lines if k in "LC" and os.path.dirname(p) in m.header["root"]})


def check_install():
    """The install records of install.sh, read only (lib/install_record.py reads and checks them; the lock is not taken, a run that holds it
    may be half way)."""
    name = "install"
    import install_record as IR
    conf = PA.live_conf()
    facts = {"conf": conf, "tool_root": None, "source": None, "version": None, "tool_version": None, "runtimes": [], "projects": [],
             "legacy": [], "missing": [], "moved": [], "unreadable": []}
    problems, fix = [], []
    try:       # the records of qargi 0.3.1 or earlier: install.sh no longer reads them
        legacy = [os.path.join(conf, n) for n in sorted(os.listdir(conf))
                  if (n == "install.manifest" or re.match(r"^project-[0-9]+\.manifest$", n)) and os.path.isfile(os.path.join(conf, n))]
    except OSError:
        legacy = []
    facts["legacy"] = legacy
    try:
        with open(os.path.join(conf, "install.json")) as f:
            rec = json.load(f)
        rec = rec if isinstance(rec, dict) else {}
    except FileNotFoundError:
        rec = None
    except (OSError, ValueError) as e:
        rec = {}
        facts["unreadable"].append({"path": os.path.join(conf, "install.json"), "why": e.__class__.__name__})
    if rec:
        facts.update({k: rec.get(k) if isinstance(rec.get(k), str) and rec.get(k) else None for k in ("tool_root", "source", "version")})
    root, source = facts["tool_root"], facts["source"]
    try:
        found = IR.manifests(conf, key=None)
        records = IR.records_dir(conf)
        names = sorted(os.listdir(records)) if os.path.isdir(records) else []
    except (IR.Refused, OSError) as e:
        found, names = [], []
        facts["unreadable"].append({"path": os.path.join(conf, "install.d"), "why": str(e)})
    found += [("project", IR.PROJECT_FILE.match(n).group(2), os.path.join(records, n)) for n in names if IR.PROJECT_FILE.match(n)]
    for kind, rt, path in found:
        try:
            m = IR.read(path)
        except IR.Refused as e:
            facts["unreadable"].append({"path": path, "why": str(e)})
            continue
        missing, moved = link_findings(m)
        for x in missing + moved:
            x["manifest"] = path
        facts["missing"] += missing
        facts["moved"] += moved
        if kind == "runtime":
            facts["runtimes"].append({"name": rt, "skills_dir": m.header["root"], "skills": len(skills_of(m)), "manifest": path})
        elif kind == "project":
            facts["projects"].append({"name": rt, "project": m.header["project"], "skills_dir": m.header["root"], "skills": len(skills_of(m)),
                                      "manifest": path})
    if not (rec is not None or found or legacy or facts["unreadable"]):
        return dict(check(name, "unknown", "no install record in %s (install.sh --user installs the tool and records it)" % clean(tilde(conf))), **facts)

    # the tool the user install came from, and what each runtime holds
    head = []
    if root:
        try:
            with open(os.path.join(root, "VERSION")) as f:
                facts["tool_version"] = f.read().strip() or None
        except (OSError, UnicodeDecodeError):
            pass
        head.append("%s (%s, %s)" % (clean(tilde(root)), clean(source or "source not recorded", 40), clean(facts["version"] or "no version", 40)))
    rts = ", ".join("%s (%d skill%s in %s)" % (clean(r["name"], 60), r["skills"], "" if r["skills"] == 1 else "s", ", ".join(clean(tilde(d)) for d in r["skills_dir"]))
                    for r in facts["runtimes"])
    head.append("runtimes " + rts if rts else "no user runtime recorded")
    if facts["projects"]:
        head.append("in projects " + ", ".join("%s (%d skill%s in %s)" % (clean(p["name"], 60), p["skills"], "" if p["skills"] == 1 else "s",
                                                                          clean(tilde(p["project"]))) for p in facts["projects"]))
    install = "%s/install.sh --user" % root if root and source != "copy" else "install.sh --user%s (from the checkout you installed)" % (
        " --copy" if source == "copy" else "")

    # the findings
    for u in facts["unreadable"]:
        problems.append("%s cannot be read: %s" % (clean(tilde(u["path"])), clean(u["why"], 400)))
    if facts["unreadable"]:
        fix.append("fix: a record that cannot be read is not used by install.sh either: move it aside, then remove by hand what it lists and install again")
    if legacy:
        problems.append("%s from qargi 0.3.1 or earlier is no longer read" % some(legacy))
        fix.append("fix: it can be removed by hand after checking that install.d holds the records of your installs (%s writes them)" % install)
    if rec is not None and not root and not facts["unreadable"]:
        problems.append("install.json records no tool_root")
        fix.append("fix: %s records it again" % install)
    if rec is None and facts["runtimes"]:
        problems.append("runtimes are recorded but install.json is not there")
        fix.append("fix: %s records the tool again" % install)
    if rec is not None and root and not facts["runtimes"] and not facts["unreadable"]:
        problems.append("install.json names the tool, but no user runtime is recorded in install.d")
        fix.append("fix: %s installs the lead skills (the default runtime; --runtime NAME for another)" % install)
    if facts["missing"]:
        problems.append("%d recorded path%s missing: %s" % (len(facts["missing"]), " is" if len(facts["missing"]) == 1 else "s are",
                                                           some([x["path"] for x in facts["missing"]])))
    if facts["moved"]:
        problems.append("%d recorded link%s no longer what the install made: %s" % (len(facts["moved"]), " is" if len(facts["moved"]) == 1 else "s are",
                                                                                 some([x["path"] for x in facts["moved"]])))
    if facts["missing"] or facts["moved"]:
        fix.append("fix: %s puts back what is missing (install.sh --project DIR for a project); a link you pointed elsewhere is kept (by --uninstall too) "
                   "until you remove it or install again with --force" % install)
    if facts["version"] and facts["tool_version"] and facts["version"] != facts["tool_version"]:
        problems.append("install.json records version %s, the tool at %s is %s" % (clean(facts["version"], 40), clean(tilde(root)), clean(facts["tool_version"], 40)))
        fix.append("fix: the tool changed without an install (a git pull, say): %s records it as it is now" % install)
    detail = "; ".join(head + problems)
    return dict(check(name, "warn" if problems else "ok", detail, fix), **facts)


# ---------------------------------------------------------------------------------------------------------------- shm

def check_shm():
    name = "shm"
    root = os.environ.get("QARGI_RUN_TMP") or "/dev/shm"
    while len(root) > 1 and root.endswith("/"):
        root = root[:-1]
    if os.path.islink(root) or not os.path.isdir(root):
        return check(name, "unknown", "%s is not a directory" % root)
    try:
        st = os.statvfs(root)
    except OSError as e:
        return check(name, "unknown", "cannot read the free space of %s (%s)" % (root, e.strerror or e.__class__.__name__))
    total, free = st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize
    if total <= 0:
        return check(name, "unknown", "%s reports no size" % root)
    pct = free * 100.0 / total
    try:
        low = float(os.environ.get("QARGI_DOCTOR_MIN_FREE", LOW_FREE_PCT))
    except ValueError:
        low = LOW_FREE_PCT
    mib = lambda n: "%d MiB" % (n // (1024 * 1024))  # noqa: E731
    rc, out, err = run(["bash", os.path.join(HERE, "orphans.sh"), os.path.realpath(root), str(ORPHAN_DAYS)])
    orphans = None
    if rc == 0:
        for line in out.splitlines():
            if line.startswith("total "):
                w = line.split()
                if len(w) == 6 and w[2] == "orphan" and w[3].isdigit():
                    orphans = int(w[3])
    space = "%s free of %s (%.0f%%) under %s" % (mib(free), mib(total), pct, root)
    if orphans is None:
        return check(name, "unknown", space + "; the qargi-run.* directories could not be listed (%s)" % (first_line(err) or "orphans.sh exit status %s" % rc))
    detail = "%s; %d orphaned qargi-run.* director%s (older than %d days, named by no registry)" % (space, orphans, "y" if orphans == 1 else "ies", ORPHAN_DAYS)
    fix = []
    if orphans:
        fix.append("fix: qargi local clean --orphans lists them and prints a plan; it removes nothing without your --approved")
    if pct < low:
        fix.append("fix: less than %g%% is free; see what takes the space: du -sh %s/* | sort -h" % (low, root))
    return check(name, "warn" if fix else "ok", detail, fix)


# ---------------------------------------------------------------------------------------------------------------- window-source

def where(path):
    """A definition's path as a reader wants it: below the tool as lib/..., else as it is."""
    top = os.path.dirname(HERE)
    return os.path.relpath(path, top) if path == top or path.startswith(top + os.sep) else path


def lead_session_model(project, conf):
    """-> (model, found): the model id of the last turn of the lead's own session (lib/lead_usage.py, which only reads the transcript the
    project's runtime keeps), and when there is none what was found instead: no transcript, a transcript with no counted turn, a turn with no
    model id (a transcript that cannot be read is no transcript found)."""
    try:
        import argparse
        import lead_usage as LU
        u = LU.measure(argparse.Namespace(project=project, session=None, transcript=None, cwd="", json=False, advise=False), conf)
    except Exception:                                           # noqa: BLE001  (a check that cannot be made is unknown, never an error)
        return "", "no transcript of its session"
    if not u.get("known"):
        if u.get("transcript") and str(u.get("why", "")).startswith("no turn"):
            return "", "its transcript has no counted turn"
        return "", "no transcript of its session"
    if not u.get("model"):
        return "", "the last turn of its transcript names no model id"
    return u["model"], ""


def check_window_source(project):
    name = "window-source"
    if not project:
        return check(name, "unknown", "no project (name one, or run inside its repository): the table belongs to the project's runtime")
    import provider as P
    conf = PA.conf()
    answers = P.project_answers(project, conf)
    if not answers:
        return check(name, "unknown", "no stored answers for project %s" % clean(project, 80))
    try:
        prov = P.provider_of(answers, "local", project)
        tr = P.transcripts(prov, os.getcwd(), conf=conf)
        src = P._entry(prov)
    except P.Unsupported as e:
        return check(name, "unknown", "the runtime has no window table: %s" % clean(e))
    except P.ProviderError as e:
        return check(name, "unknown", "the runtime of project %s cannot be read: %s" % (clean(project, 80), clean(e)))
    table = "table of %s (%s, %s): %d entr%s, %s assumed otherwise" % (prov, src["origin"], where(src["file"]), len(tr["windows"]),
                                                                       "y" if len(tr["windows"]) == 1 else "ies", format(tr["window"], ","))
    lead = answers.get("lead") if isinstance(answers.get("lead"), dict) else {}
    ans = lead.get("context_window")
    ans = ans if isinstance(ans, int) and not isinstance(ans, bool) and ans >= 1000 else None
    if ans:
        table = "answer lead.context_window = %s overrides the %s" % (format(ans, ","), table)
    else:
        table += " (the table gives the API's window, the runtime may cap it lower on some plans; the answer lead.context_window overrides it)"
    ids = []
    for role, spec in sorted((answers.get("roles") or {}).items()) if isinstance(answers.get("roles"), dict) else ():
        m = spec.get("model") if isinstance(spec, dict) else None
        if isinstance(m, str) and m.strip() and m.strip() not in ids:
            ids.append(m.strip())
    lead_model, lead_found = ("", "") if ans else lead_session_model(project, conf)       # the answer settles the window of every model: nothing to look up
    unknown = [] if ans else [m for m in ids if P.transcript_window(tr, m)[1] != "model"]
    lead_unknown = bool(lead_model) and P.transcript_window(tr, lead_model)[1] != "model"
    if unknown or lead_unknown:
        said = []
        if unknown:
            said.append("not in the table: %s (their window is only assumed)" % ", ".join(clean(m, 80) for m in unknown))
        if lead_unknown:
            said.append("the lead's own model is not in the table: %s (its window is only assumed, so there is no percentage and no compact advice)" % clean(lead_model, 80))
        return check(name, "warn", table + "; " + "; ".join(said),
                     ["fix: set the answer lead.context_window, or add an entry for the id to the window table of the runtime's definition"])
    if not ids and not ans and not lead_model:
        return check(name, "unknown", table + "; no role names a model id and the lead's own model cannot be determined (%s)" % lead_found)
    lead = "" if ans else ("; the lead's own model %s is in the table" % clean(lead_model, 80) if lead_model else "; the lead's own model cannot be determined (%s)" % lead_found)
    if not ids:
        return check(name, "ok", table + "; no role names a model id (the tiers resolve at dispatch)" + lead)
    return check(name, "ok", table + "; %d model id%s checked" % (len(ids), "" if len(ids) == 1 else "s") + lead)


def check_project_env(project):
    """The last `qargi env check` recorded for the project (state/env/PROJECT.json, key check): its verdict and time. It only reads that file:
    the project's own doctor is never run here, that is what qargi env check does."""
    name = "project-env"
    if not project:
        return check(name, "unknown", "no project (name one, or run inside its repository): the record belongs to the project")
    fix = ["fix: qargi env check --project %s runs the project's doctor and records the result (it runs the project's code, so it is not part of this command)" % clean(project, 80)]
    rec = os.path.join(PA.state(), "env", project + ".json")
    try:
        with open(rec) as f:
            doc = json.load(f)
    except FileNotFoundError:
        return check(name, "unknown", "never run", fix)
    except (OSError, ValueError) as e:
        return check(name, "unknown", "the record %s cannot be read: %s" % (where(rec), clean(e.__class__.__name__)), fix)
    last = doc.get("check") if isinstance(doc, dict) else None
    if not isinstance(last, dict) or not isinstance(last.get("verdict"), str) or not last["verdict"].strip():
        return check(name, "unknown", "never run", fix)
    when = clean(last.get("time") or "an unknown time", 40)
    head = last.get("head")
    detail = "last env check %s at %s%s" % (clean(last["verdict"], 120), when, " (HEAD %s)" % clean(head, 12) if isinstance(head, str) and head else "")
    good = last["verdict"].strip() == "ENV OK"
    return check(name, "ok" if good else "warn", detail, [] if good else fix)


# ---------------------------------------------------------------------------------------------------------------- main

def project_of(arg):
    """The project to check: the one named, else the one in effect (None when there is none). A named one that is not stored is a usage error."""
    if arg:
        if not os.path.isfile(os.path.join(PA.conf(), "projects", arg + ".json")) or "/" in arg:
            return False
        return arg
    import help as H
    return H.infer_project()


def render(checks):
    lines = []
    for c in checks:
        lines.append("%s  %s: %s" % (c["status"], c["name"], c["detail"]))
        lines += ["    " + f for f in c["fix"]]
    return "\n".join(lines)


def main(argv):
    as_json = strict = False
    names = []
    argv = list(argv)
    while argv:
        a = argv.pop(0)
        if a == "--project":
            if not argv:
                print("qargi doctor: --project needs a value\n%s" % USAGE, file=sys.stderr)
                return 2
            names.append(argv.pop(0))
        elif a == "--json":
            as_json = True
        elif a == "--strict":
            strict = True
        elif a.startswith("-"):
            print("qargi doctor: unknown option %s\n%s" % (a, USAGE), file=sys.stderr)
            return 2
        else:
            names.append(a)
    if len(names) > 1:
        print(USAGE, file=sys.stderr)
        return 2
    project = project_of(names[0] if names else None)
    if project is False:
        print("qargi doctor: no stored project '%s'" % names[0], file=sys.stderr)
        return 2
    checks = [check_remove_ipc(), check_guard(project), check_shm(), check_tools(), check_install(), check_window_source(project), check_verify_environment(project), check_project_env(project)]
    warns = sum(1 for c in checks if c["status"] == "warn")
    code = 1 if strict and warns else 0
    if as_json:
        print(json.dumps({"project": project or None, "checks": checks, "warnings": warns, "strict": strict, "exit": code}, indent=2))
    else:
        print(render(checks))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
