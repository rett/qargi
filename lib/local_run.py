#!/usr/bin/env python3
"""qargi local run: start the member of a prepared local run as a command line, from the data of the project's local runtime.

  local_run.py RUN --project P --runtime NAME --class write|read-only [--task FILE] [--model TIER|ID] [--effort LEVEL]
               [--timeout SECONDS] [--dry-run] [--again]

lib/local.sh `run` finds the project and its runtime (the one resolver, `provider.py of`) and calls this. Everything the command line is
made of comes from the definition's `dispatch` (schema 2, mode `command`); nothing here is specific to a runtime:

  dispatch.argv        an ARRAY, never a shell string. Elements are strings (placeholders {name}), or {"if": VAR, "then": [...]} (kept when
                       the placeholder VAR has a value) or {"class": "read-only"|"write", "then": [...]} (kept for that class of the run).
                       Element 0 is the command: a plain word looked up on PATH (a vendor CLI), or a path inside the definition's
                       directory. A library pack's executable runs only as a private copy of the sealed pack (provider.exec_copy) and
                       only when its record approves it; a shipped definition's is read from lib/providers/NAME/.
  dispatch.class_argv  arguments added for the run's class: a list (read-only runs only) or {"read-only": [...], "write": [...]}. They go
                       before the first element that carries the prompt argument, or at the end. For sandbox flags a definition keeps out
                       of argv. The barrier kind `sandbox-args` needs them (or a class element in argv) for a read-only run.
  dispatch.prompt      {via: stdin|file|arg, file: "prompt.md"}: stdin reads the prompt file, file passes its path ({prompt_file}), arg
                       passes the text ({prompt_arg}, at most 120000 bytes). The file is a plain name inside RUN/prompt/, a directory of
                       its own: it can never be a control file of the run (refs.before, class, dispatch.json ...). The prompt is the neutral member body (agents/member.body.md) and
                       the task block, with what qargi recorded about the run (class, paths); the runtime has no agent files to carry it.
  dispatch.cwd         "{clone}" (default) or a directory inside it.
  dispatch.env_pass    names of environment variables handed on (secrets travel by name, never in argv); GIT_* and QARGI_* are refused,
                       and so is what would hand on the user's own home, search path, code loaders, ssh agent or forge credentials
                       (provider.env_pass_problem).
  dispatch.timeout_s   the bound (default 1800, at most 86400); --timeout replaces it.
  dispatch.exit        {"0": "ok", "*": "failed"}: the exit status -> outcome ok|failed|refused|transport.
Placeholders (the closed set): member, model, effort_native, prompt_file, prompt_arg, clone, run_dir, out_dir, project (and the short names
effort, out, prompt). agent_file and session_id belong to runtimes with agent files and to resume; they are refused here.

The process gets the environment of the run's git wrapper (RUN/git: HOME is RUN/home, no global git configuration, no ssh, no prompts,
the author qargi) and TMPDIR of the run, plus PATH and the env_pass names. It runs in its own session without a shell, its standard output goes
to OUT/transcript and its standard error to OUT/transcript.err, and a process group that outlives the bound is killed. A record of what ran is
written to RUN/dispatch.json (argv, class, model, outcome; never an environment value). --dry-run prints the argv and the prompt and writes
nothing. The exit status: 0 ok, 1 failed (or a usage error), 2 refused, 3 the runtime cannot be run this way, 4 transport.
"""
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import provider as P  # noqa: E402

TOOL = os.path.dirname(HERE)
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
ALIASES = {"effort": "effort_native", "out": "out_dir", "prompt": "prompt_arg"}
CLOSED = ("member", "model", "effort_native", "prompt_file", "prompt_arg", "clone", "run_dir", "out_dir", "agent_file", "session_id", "project")
NOT_HERE = ("agent_file", "session_id")
CLASSES = ("write", "read-only")
OUTCOME_EXIT = {"ok": 0, "failed": 1, "refused": 2, "transport": 4}
DEFAULT_TIMEOUT = 1800
MAX_TIMEOUT = 86400
MAX_ARG = 120000          # one argument may not exceed 131072 bytes on Linux
MAX_TASK = 1 << 20
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
PROMPT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
PROMPT_DIR = "prompt"     # where the prompt file goes: a directory of the run for it alone, so no name can reach a control file of the run


class Stop(Exception):
    """A refusal or an error with its exit status."""
    def __init__(self, msg, code=2):
        Exception.__init__(self, msg)
        self.code = code


def fail(msg, code=2):
    raise Stop(msg, code)


# ---- the data -----------------------------------------------------------------------------------------------------------------------

def names_in(s):
    return [ALIASES.get(n, n) for n in PLACEHOLDER.findall(s)]


def walk_strings(items):
    """Every string of an argv-like list, with the strings of nested then-lists."""
    for it in items:
        if isinstance(it, str):
            yield it
        elif isinstance(it, dict):
            yield from walk_strings(it.get("then") if isinstance(it.get("then"), list) else [])


def check_items(items, where, runtime):
    """The shape of an argv-like list: strings and {if|class, then} objects only; every placeholder in the closed set."""
    if not isinstance(items, list):
        fail("%s of %s must be a list (an argument array, never a shell string)" % (where, runtime))
    for it in items:
        if isinstance(it, str):
            if "\0" in it:
                fail("%s of %s holds a NUL" % (where, runtime))
            for n in names_in(it):
                if n not in CLOSED:
                    fail("%s of %s: unknown placeholder {%s}; the set is %s" % (where, runtime, n, ", ".join(CLOSED)))
                if n in NOT_HERE:
                    fail("%s of %s uses {%s}, which a local run does not provide (it has no agent file and starts no resumed session)" % (where, runtime, n), 3)
        elif isinstance(it, dict):
            keys = set(it)
            if keys == {"if", "then"}:
                if not isinstance(it["if"], str) or ALIASES.get(it["if"], it["if"]) not in CLOSED:
                    fail("%s of %s: {\"if\": %s}: not a placeholder name (%s)" % (where, runtime, json.dumps(it["if"]), ", ".join(CLOSED)))
            elif keys == {"class", "then"}:
                if it["class"] not in CLASSES:
                    fail("%s of %s: {\"class\": %s}: one of %s" % (where, runtime, json.dumps(it["class"]), ", ".join(CLASSES)))
            else:
                fail("%s of %s: an object is {\"if\": NAME, \"then\": [...]} or {\"class\": CLASS, \"then\": [...]}, not %s" % (where, runtime, json.dumps(it, sort_keys=True)))
            check_items(it["then"], where, runtime)
        else:
            fail("%s of %s: an element is a string or an object, not %s" % (where, runtime, json.dumps(it)))


def expand(items, values, cls, where, runtime):
    out = []
    for it in items:
        if isinstance(it, str):
            def sub(m, it=it):
                n = ALIASES.get(m.group(1), m.group(1))
                v = values.get(n)
                if v in (None, ""):
                    fail("%s of %s: %s has no value for this run (put it in an {\"if\": \"%s\", \"then\": [...]} group)" % (where, runtime, m.group(0), m.group(1)))
                return v
            out.append(PLACEHOLDER.sub(sub, it))
        elif "if" in it:
            if values.get(ALIASES.get(it["if"], it["if"])) not in (None, ""):
                out += expand(it["then"], values, cls, where, runtime)
        elif it["class"] == cls:
            out += expand(it["then"], values, cls, where, runtime)
    return out


def class_extra(disp, cls, runtime):
    ca = disp.get("class_argv")
    if ca is None:
        return []
    if isinstance(ca, list):
        return ca if cls == "read-only" else []
    if isinstance(ca, dict):
        for k in ca:
            if k not in CLASSES:
                fail("dispatch.class_argv of %s: the key '%s' is not a class (%s)" % (runtime, k, ", ".join(CLASSES)))
        v = ca.get(cls, [])
        return v if isinstance(v, list) else fail("dispatch.class_argv.%s of %s must be a list" % (cls, runtime))
    return fail("dispatch.class_argv of %s must be a list or an object with a list per class" % runtime)


def has_class_args(disp):
    return P.has_class_args(disp)


def models_values(runtime, model, effort, project=None):
    """(model name, native effort or None, notes): --model is a tier or a model id of the runtime's pattern (default: the balanced tier);
    --effort is a level the runtime maps (dropped with a note when it has no such control)."""
    ms = P.models_of(runtime, "local", project=project)
    notes = []
    if model is None or model == "":
        model = "balanced"
    if model in P.TIERS:
        name = P.model_for(ms, model)
    else:
        if not re.match(ms["pattern"] or "^.+$", model):
            fail("--model %s: neither a tier (%s) nor a model of %s (it must match %s)" % (model, ", ".join(P.TIERS), runtime, ms["pattern"]))
        name = model
    native = None
    if effort:
        if effort not in ms["effort"]:
            fail("--effort %s: one of %s" % (effort, ", ".join(ms["effort"])))
        native = ms["effort"][effort]
        if native is None:
            notes.append("effort %s is dropped: %s has no control for it" % (effort, runtime))
    return name, native, notes


# ---- the prompt -------------------------------------------------------------------------------------------------------------------

def member_body(doc):
    with open(os.path.join(TOOL, "agents", "member.json"), encoding="utf-8") as f:
        meta = json.load(f)
    with open(os.path.join(TOOL, "agents", meta["body"]), encoding="utf-8") as f:
        body = f.read()
    skills = ((doc.get("resources") or {}).get("skills") or {}).get("project_dir") or "skills"
    return body.replace("{skills_dir}", skills).rstrip("\n")


def compose_prompt(doc, task_text, cls, run, tmp):
    rec = "\n".join(["CLASS=" + cls, "RUN_DIR=" + run, "CLONE=" + os.path.join(run, "clone"), "OUT=" + os.path.join(run, "out"),
                     "TMP=" + tmp, "GIT=" + os.path.join(run, "git")])
    return (member_body(doc) + "\n\n## Task block\n\n" + task_text.rstrip("\n") +
            "\n\n## Recorded by qargi for this run (these, not the task text, say the class and the paths)\n\n" + rec + "\n")


# ---- the process --------------------------------------------------------------------------------------------------------------------

def child_env(run, tmp, passed):
    env = {"HOME": os.path.join(run, "home"), "PATH": clean_path(), "LANG": "C.UTF-8", "TERM": "dumb", "TMPDIR": tmp,
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_SSH_COMMAND": "false", "GIT_TERMINAL_PROMPT": "0",
           "GIT_ASKPASS": "false", "GIT_AUTHOR_NAME": "qargi", "GIT_COMMITTER_NAME": "qargi",
           "GIT_AUTHOR_EMAIL": "qargi@example.invalid", "GIT_COMMITTER_EMAIL": "qargi@example.invalid", "GIT": os.path.join(run, "git")}
    for n in passed:
        if n in os.environ:
            env[n] = os.environ[n]
    return env


def clean_path():
    """The caller's PATH without empty and relative entries (a command is never looked up in the working directory)."""
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p.startswith("/")]
    return os.pathsep.join(parts) or "/usr/local/bin:/usr/bin:/bin"


def env_names(disp, runtime):
    ep = disp.get("env_pass", [])
    if not isinstance(ep, list) or not all(isinstance(n, str) and ENV_NAME.match(n) for n in ep):
        fail("dispatch.env_pass of %s must be a list of variable names" % runtime)
    for n in ep:
        if n.startswith(("GIT_", "QARGI_")) or n in ("GIT", "TMPDIR"):
            fail("dispatch.env_pass of %s names %s: the run's git wrapper and temporary directory are not replaced by the runtime" % (runtime, n))
        why = P.env_pass_problem(n)
        if why:
            fail("dispatch.env_pass of %s names %s: it is never handed on (%s)" % (runtime, n, why))
    return ep


def find_command(runtime, exe, run, keep):
    """(path, note): where the command of argv[0] is run from. keep collects a directory to remove afterwards (an exec copy)."""
    if not isinstance(exe, str) or not exe or PLACEHOLDER.search(exe):
        fail("dispatch.argv[0] of %s must be a plain command: a word looked up on PATH, or a path inside the definition's directory" % runtime)
    if "/" not in exe:
        found = shutil.which(exe, path=clean_path())
        if not found:
            fail("the command '%s' of runtime %s is not on PATH; install it first (it is run by name, as you would run it)" % (exe, runtime), 3)
        if os.path.realpath(found).startswith(os.path.realpath(run) + os.sep):
            fail("the command '%s' resolves into the run directory; refused" % exe)
        return found, "on PATH"
    n = os.path.normpath(exe)
    if os.path.isabs(exe) or n != exe or n.startswith(".."):
        fail("dispatch.argv[0] '%s' of %s is not a path inside the definition's directory" % (exe, runtime))
    if P.origin(runtime) == "library":
        d, path = P.exec_copy(runtime, exe)              # Drift or Refused unless the pack is sealed and approves exactly this executable
        keep.append(os.path.dirname(d))                  # exec_copy makes TMP/qargi-exec.XXXX/NAME; the whole of it goes
        return path, "sealed copy of pack %s" % runtime
    path = os.path.join(P.PROVIDERS, runtime, exe)
    if not os.path.isfile(path) or not os.access(path, os.X_OK) or not os.path.realpath(path).startswith(os.path.realpath(os.path.join(P.PROVIDERS, runtime)) + os.sep):
        fail("dispatch.argv[0] '%s' of %s is not an executable inside lib/providers/%s/" % (exe, runtime, runtime), 3)
    return path, "shipped with %s" % runtime


def build(run, project, runtime, cls, task_file, model, effort, timeout, keep):
    """Everything a run needs, as a dict; Stop for a refusal. Nothing is written."""
    if not os.path.isfile(os.path.join(run, "refs.before")) or not os.path.isdir(os.path.join(run, "clone")):
        fail("run needs a RUN dir made by qargi local prepare", 1)
    out = os.path.join(run, "out")
    clone = os.path.join(run, "clone")
    tmp = ""
    try:
        with open(os.path.join(run, "tmpdir"), encoding="utf-8") as f:
            tmp = f.read().strip()
    except OSError:
        pass
    tmp = tmp or os.path.join(run, "tmp")
    comp = P.compose(runtime, "local", project)          # the definition the project's extensions complete, not the runtime's alone
    doc = comp["definition"]
    disp = doc.get("dispatch")
    if not isinstance(disp, dict) or not disp.get("mode"):
        fail("the runtime %s has no dispatch data, so it cannot be started by qargi local run" % runtime, 3)
    mode = disp["mode"]
    if mode == "in-session":
        fail("the runtime %s dispatches in the lead's own session (dispatch.mode in-session), so qargi local run does not start it: dispatch the member with the Agent tool "
             "(qargi agent for ROLE --json gives the member, model and effort)" % runtime)
    if mode != "command":
        fail("the runtime %s dispatches by mode '%s'; qargi local run starts mode 'command' only" % (runtime, mode), 3)
    argv_t = disp.get("argv")
    check_items(argv_t, "dispatch.argv", runtime)
    if not argv_t:
        fail("dispatch.argv of %s must not be empty" % runtime)
    if not isinstance(argv_t[0], str):
        fail("dispatch.argv[0] of %s must be a plain command" % runtime)
    if "class_argv" in disp:
        class_extra(disp, cls, runtime)                  # its shape
        ca = disp["class_argv"]
        check_items(ca if isinstance(ca, list) else [x for v in ca.values() for x in (v if isinstance(v, list) else [])], "dispatch.class_argv", runtime)
    pr = disp.get("prompt") if isinstance(disp.get("prompt"), dict) else {}
    via = pr.get("via", "stdin")
    if via not in ("stdin", "file", "arg"):
        fail("dispatch.prompt.via of %s: one of stdin, file, arg" % runtime)
    pname = pr.get("file", "prompt.md")
    if not isinstance(pname, str) or not PROMPT_NAME.match(pname):
        fail("dispatch.prompt.file of %s must be a plain file name" % runtime)
    ca = disp.get("class_argv")
    ca_all = ca if isinstance(ca, list) else [x for v in (ca or {}).values() if isinstance(v, list) for x in v]
    used = {n for s in walk_strings(argv_t + ca_all) for n in names_in(s)}
    need = {"stdin": None, "file": "prompt_file", "arg": "prompt_arg"}[via]
    if need and need not in used:
        fail("dispatch.prompt.via of %s is '%s' but dispatch.argv has no {%s}" % (runtime, via, need))
    if via != "arg" and "prompt_arg" in used:
        fail("dispatch.argv of %s uses {prompt_arg} but dispatch.prompt.via is '%s'" % (runtime, via))
    to = timeout if timeout is not None else disp.get("timeout_s", DEFAULT_TIMEOUT)
    if type(to) is not int or not 1 <= to <= MAX_TIMEOUT:
        fail("the timeout of %s must be a whole number of seconds from 1 to %d" % (runtime, MAX_TIMEOUT))
    ex = disp.get("exit", {"0": "ok", "*": "failed"})
    if not isinstance(ex, dict) or any(v not in OUTCOME_EXIT for v in ex.values()):
        fail("dispatch.exit of %s maps an exit status to one of %s" % (runtime, ", ".join(OUTCOME_EXIT)))
    passed = env_names(disp, runtime)
    if cls == "read-only":
        state, text = P.require_barrier(runtime, "local", project)
        if state == "refused":
            fail(text)
        prov = comp["provenance"] or {}
        by = next((x for x in (prov.get("barrier"), prov.get("capabilities.read_only_barrier")) if x not in (None, runtime)), None)
        if by is not None:
            # the barrier is an extension's: nothing in a local run applies it (an extension adds no class_argv), so it is no barrier here
            if state in ("yes", "partial") and not P.accepted(project, "local"):
                fail("the read-only barrier of %s on local is provided by the extension %s (barrier kind %s), and qargi local run applies only the barrier the runtime's own "
                     "dispatch carries (class_argv, or a class group in argv), so it would start this member without it: a read-only run is refused here.\n"
                     "Dispatch it where that barrier is applied, or, on your own responsibility, record that you accept no barrier for the project:\n  %s"
                     % (runtime, by, (doc.get("barrier") or {}).get("kind"), P.accept_command(runtime, "local", project)))
        elif state in ("yes", "partial") and not P.accepted(project, "local") and P.barrier_claim_problem(doc):
            # the definition claims a barrier it does not have (kind none, no read-only arguments): nothing in this run would hold the member
            fail("the definition of %s claims a read-only barrier on local, but its barrier kind is none and its dispatch supplies no read-only arguments "
                 "(class_argv, or a {\"class\": \"read-only\"} group in argv), so nothing holds the member and a read-only run is refused here.\n"
                 "Fix the definition (set the barrier kind, or declare the capability not supported), or, on your own responsibility, record that you accept no "
                 "barrier for the project:\n  %s" % (runtime, P.accept_command(runtime, "local", project)))
        elif (doc.get("barrier") or {}).get("kind") == "sandbox-args" and not has_class_args(disp):
            fail("the barrier of %s is sandbox-args but its dispatch supplies no read-only arguments (class_argv, or a {\"class\": \"read-only\"} group in argv)" % runtime)
        note = text if state == "partial" else ""
    else:
        note = ""
    if task_file is None:
        task_file = os.path.join(run, "task.md")
    try:
        with open(task_file, encoding="utf-8") as f:
            task_text = f.read(MAX_TASK + 1)
    except (OSError, ValueError) as e:
        fail("no task block: write it to %s or give --task FILE (%s)" % (os.path.join(run, "task.md"), e.__class__.__name__), 1)
    if len(task_text) > MAX_TASK or "\0" in task_text or not task_text.strip():
        fail("the task block must be non-empty text of at most %d bytes" % MAX_TASK, 1)
    prompt = compose_prompt(doc, task_text, cls, run, tmp)
    if via == "arg" and len(prompt.encode("utf-8")) > MAX_ARG:
        fail("the prompt is %d bytes, too long for an argument (%d); use a runtime whose dispatch.prompt.via is stdin or file" % (len(prompt.encode("utf-8")), MAX_ARG))
    mname, native, notes = models_values(runtime, model, effort, project)
    pfile = os.path.join(run, PROMPT_DIR, pname)
    member = ""
    try:
        with open(os.path.join(run, "profile"), encoding="utf-8") as f:
            member = f.read().strip()
    except OSError:
        pass
    member = member or open(os.path.join(run, "ability"), encoding="utf-8").read().strip()
    values = {"member": member, "model": mname, "effort_native": native or "", "prompt_file": pfile, "prompt_arg": prompt if via == "arg" else "",
              "clone": clone, "run_dir": run, "out_dir": out, "project": project}
    argv = expand(argv_t, values, cls, "dispatch.argv", runtime)
    extra = expand(class_extra(disp, cls, runtime), values, cls, "dispatch.class_argv", runtime)
    if extra:
        at = next((i for i, a in enumerate(argv) if via == "arg" and prompt in a), len(argv))
        argv[at:at] = extra
    cwd = expand([disp.get("cwd", "{clone}")], values, cls, "dispatch.cwd", runtime)[0]
    real = os.path.realpath(cwd)
    if real != os.path.realpath(clone) and not real.startswith(os.path.realpath(clone) + os.sep):
        fail("dispatch.cwd of %s is %s, outside the clone" % (runtime, cwd))
    exe, how = find_command(runtime, argv[0], run, keep)
    return {"runtime": runtime, "class": cls, "argv": argv, "exe": exe, "exe_from": how, "cwd": cwd, "via": via, "prompt": prompt, "prompt_file": pfile,
            "timeout_s": to, "env_pass": passed, "env": child_env(run, tmp, passed), "exit": ex, "model": mname, "effort_native": native,
            "notes": notes + ([note] if note else []), "output_format": (disp.get("output") or {}).get("format", "text")}


def dry(plan, run):
    exe = plan["argv"][0] if plan["exe_from"] == "on PATH" else "<%s>/%s" % (plan["exe_from"], plan["argv"][0])
    print("dry run: nothing is run and nothing is written")
    print("RUNTIME=" + plan["runtime"])
    print("CLASS=" + plan["class"])
    print("MODEL=" + plan["model"])
    print("EFFORT_NATIVE=" + (plan["effort_native"] or ""))
    print("COMMAND=" + exe)
    print("ARGV=" + json.dumps(plan["argv"], separators=(",", ":")))
    print("CWD=" + plan["cwd"])
    print("TIMEOUT_S=%d" % plan["timeout_s"])
    print("ENV_PASS=" + ",".join(plan["env_pass"]))
    print("PROMPT_VIA=" + plan["via"])
    print("PROMPT_FILE=" + plan["prompt_file"])
    print("TRANSCRIPT=" + os.path.join(run, "out", "transcript"))
    for n in plan["notes"]:
        print("NOTE=" + n)
    print("PROMPT:")
    sys.stdout.write(plan["prompt"])
    sys.stdout.flush()


def kill_group(proc):
    for sig, wait in ((signal.SIGTERM, 5), (signal.SIGKILL, 5)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        try:
            proc.wait(timeout=wait)
            return
        except subprocess.TimeoutExpired:
            continue


def write_private(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def write_prompt(run, path, text):
    """Write the prompt file in RUN/prompt/ and nowhere else: the directory must be a real directory of the run (not a link out of it),
    the file a new or regular one (not a link, not a pipe), so the prompt can never overwrite what qargi recorded about the run."""
    d = os.path.join(run, PROMPT_DIR)
    if os.path.islink(d) or (os.path.exists(d) and not os.path.isdir(d)):
        fail("%s is not a plain directory of the run; the prompt file goes there and nowhere else" % d)
    os.makedirs(d, mode=0o700, exist_ok=True)
    if os.path.realpath(d) != os.path.join(os.path.realpath(run), PROMPT_DIR) or os.path.dirname(path) != d:
        fail("the prompt file %s is not inside %s" % (path, d))
    if os.path.lexists(path) and (os.path.islink(path) or not os.path.isfile(path)):
        fail("%s is not a plain file; the prompt file replaces only a file of its own" % path)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    except OSError as e:
        fail("cannot write the prompt file %s: %s" % (path, e.strerror or e))
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)


def run_it(plan, run):
    out = os.path.join(run, "out")
    os.makedirs(out, exist_ok=True)
    write_prompt(run, plan["prompt_file"], plan["prompt"])
    argv = [plan["exe"]] + plan["argv"][1:]
    started = time.time()
    timed_out = False
    sin = open(plan["prompt_file"], "rb") if plan["via"] == "stdin" else subprocess.DEVNULL
    with open(os.path.join(out, "transcript"), "wb") as so, open(os.path.join(out, "transcript.err"), "wb") as se:
        try:
            proc = subprocess.Popen(argv, cwd=plan["cwd"], env=plan["env"], stdin=sin, stdout=so, stderr=se, shell=False, start_new_session=True)
        except OSError as e:
            if sin is not subprocess.DEVNULL:
                sin.close()
            fail("could not start %s: %s" % (plan["argv"][0], e.strerror or e), 4)
        try:
            code = proc.wait(timeout=plan["timeout_s"])
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_group(proc)
            code = proc.returncode
        except BaseException:
            kill_group(proc)
            raise
        finally:
            if sin is not subprocess.DEVNULL:
                sin.close()
    if timed_out:
        outcome = "failed"
    else:
        outcome = plan["exit"].get(str(code), plan["exit"].get("*", "failed"))
    rec = {"runtime": plan["runtime"], "class": plan["class"], "argv": plan["argv"], "command_from": plan["exe_from"], "cwd": plan["cwd"],
           "model": plan["model"], "effort_native": plan["effort_native"], "prompt_via": plan["via"], "timeout_s": plan["timeout_s"],
           "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)), "seconds": round(time.time() - started, 1),
           "exit": code, "timed_out": timed_out, "outcome": outcome, "transcript": os.path.join(out, "transcript")}
    write_private(os.path.join(run, "dispatch.json"), json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print("RUNTIME=" + plan["runtime"])
    print("OUTCOME=" + outcome + (" (timed out after %ds)" % plan["timeout_s"] if timed_out else ""))
    print("EXIT=%s" % code)
    print("TRANSCRIPT=" + rec["transcript"])
    print("next: read the transcript and OUT, then qargi local verify " + run)
    return OUTCOME_EXIT[outcome]


def parse(argv):
    if len(argv) < 1 or argv[0].startswith("--"):
        fail("usage: local_run.py RUN --project P --runtime NAME --class write|read-only [--task FILE] [--model M] [--effort E] [--timeout S] [--dry-run] [--again]", 1)
    o = {"run": argv[0], "task": None, "model": None, "effort": None, "timeout": None, "dry": False, "again": False, "project": None, "runtime": None, "class": None}
    i = 1
    flags = {"--project": "project", "--runtime": "runtime", "--class": "class", "--task": "task", "--model": "model", "--effort": "effort", "--timeout": "timeout"}
    while i < len(argv):
        a = argv[i]
        if a == "--dry-run":
            o["dry"], i = True, i + 1
        elif a == "--again":
            o["again"], i = True, i + 1
        elif a in flags and i + 1 < len(argv):
            o[flags[a]], i = argv[i + 1], i + 2
        else:
            fail("unknown option or missing value: %s" % a, 1)
    if o["timeout"] is not None:
        if not o["timeout"].isdigit():
            fail("--timeout: a whole number of seconds", 1)
        o["timeout"] = int(o["timeout"])
    if not (o["project"] and o["runtime"] and o["class"] in CLASSES):
        fail("--project, --runtime and --class are needed (qargi local run supplies them)", 1)
    return o


def main(argv):
    keep = []
    try:
        o = parse(argv)
        run = os.path.realpath(o["run"])
        if not o["dry"] and not o["again"] and os.path.exists(os.path.join(run, "dispatch.json")):
            fail("%s has been run already (%s); --again runs it again and replaces the transcript" % (run, os.path.join(run, "dispatch.json")))
        plan = build(run, o["project"], o["runtime"], o["class"], o["task"], o["model"], o["effort"], o["timeout"], keep)
        for n in plan["notes"]:
            if not o["dry"]:
                print("qargi: note: " + n, file=sys.stderr)
        if o["dry"]:
            dry(plan, run)
            return 0
        return run_it(plan, run)
    except Stop as e:
        print("qargi: %s" % e, file=sys.stderr)
        return e.code
    except P.Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 3
    except (P.NoProvider, P.Refused) as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2
    except P.ProviderError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    finally:
        for d in keep:
            if os.path.basename(d).startswith("qargi-exec."):
                shutil.rmtree(d, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
