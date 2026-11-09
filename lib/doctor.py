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
                 lead.context_window) and whether each model id the project's roles name is in it.

A check that cannot be made (no logind, no tool, no project) is `unknown`, never a warning. Only reads: no file is written, no
directory is removed, nothing is changed on the host."""
import json, os, pwd, re, shutil, subprocess, sys, tempfile  # noqa: E401

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


def run(argv, stdin=None, cwd=None):
    """(returncode, stdout, stderr) of a program, or (None, '', reason) when it is not there or does not answer. The environment is the caller's."""
    try:
        r = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=PROBE_SECS, cwd=cwd,
                           stdin=None if stdin is not None else subprocess.DEVNULL)
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


def member_states(project):
    """[(member, state)] of the project's members whose file is missing, stale or edited (qargi agent list: the one place that knows), or None when that cannot be read."""
    rc, out, _ = run([os.path.join(os.path.dirname(HERE), "bin", "qargi"), "agent", "list", "--project", project])
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
    states = member_states(project)
    if states is None:
        return check(name, "unknown", detail + "; the members of project %s could not be read (qargi agent list)" % project)
    if states:
        return check(name, "warn", detail + ", but the members of project %s are not current: %s" % (project, ", ".join("%s %s" % s for s in states)),
                     ["fix: qargi agent refresh %s --project %s" % (m, project) for m, _ in states])
    return check(name, "ok", detail + "; the members of project %s are current" % project)


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
    ids = []
    for role, spec in sorted((answers.get("roles") or {}).items()) if isinstance(answers.get("roles"), dict) else ():
        m = spec.get("model") if isinstance(spec, dict) else None
        if isinstance(m, str) and m.strip() and m.strip() not in ids:
            ids.append(m.strip())
    if not ids:
        return check(name, "ok", table + "; no role names a model id (the tiers resolve at dispatch)")
    unknown = [] if ans else [m for m in ids if P.transcript_window(tr, m)[1] != "model"]
    if unknown:
        return check(name, "warn", table + "; not in the table: %s (their window is only assumed)" % ", ".join(clean(m, 80) for m in unknown),
                     ["fix: set the answer lead.context_window, or add an entry for the id to the window table of the runtime's definition"])
    return check(name, "ok", table + "; %d model id%s checked" % (len(ids), "" if len(ids) == 1 else "s"))


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
    checks = [check_remove_ipc(), check_guard(project), check_shm(), check_window_source(project)]
    warns = sum(1 for c in checks if c["status"] == "warn")
    code = 1 if strict and warns else 0
    if as_json:
        print(json.dumps({"project": project or None, "checks": checks, "warnings": warns, "strict": strict, "exit": code}, indent=2))
    else:
        print(render(checks))
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
