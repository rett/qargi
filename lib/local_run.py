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
                       A read-only run is held by nothing else here: the kinds `hook` (no agent file carries the hook) and `adapter` (barrier-check is not
                       called) are refused for a read-only run unless these arguments are there, or the project accepted no barrier.
  dispatch.prompt      {via: stdin|file|arg, file: "prompt.md"}: stdin reads the prompt file, file passes its path ({prompt_file}), arg
                       passes the text ({prompt_arg}, at most 120000 bytes). The file is a plain name inside RUN/prompt/, a directory of
                       its own: it can never be a control file of the run (refs.before, class, dispatch.json ...). The prompt is the neutral member body (agents/member.body.md) and
                       the task block, with what qargi recorded about the run (class, paths); the runtime has no agent files to carry it.
  dispatch.cwd         "{clone}" (default) or a directory inside it.
  dispatch.env_pass    names of environment variables handed on (secrets travel by name, never in argv); GIT_* and QARGI_* are refused,
                       and so is what would hand on the user's own home, search path, code loaders, ssh agent or forge credentials
                       (provider.env_pass_problem).
  dispatch.home        {env, dir, link: [{from, to}]}: the member's own home directory RUN/home/DIR, named by the variable env (a runtime that
                       reads its configuration and sign-in from a directory of its own). Each file `from` (~/PATH, under the user's home) is
                       linked into it as `to` when the run starts and the link is removed when it ends: the file is never copied and the
                       link's target is never printed (--dry-run names the links, HOME_LINKS=). A source that does not exist is left out with
                       a note. The directory is made and the links are removed without following a link a member may have put in the run
                       directory; a file that replaced a link during the run is removed too. provider.home_problems states the rules.
  dispatch.timeout_s   the bound (default 1800, at most 86400); --timeout replaces it.
  dispatch.exit        {"0": "ok", "*": "failed"}: the exit status -> outcome ok|failed|refused|transport.
Placeholders (the closed set): member, model, effort_native, prompt_file, prompt_arg, clone, run_dir, out_dir, project (and the short names
effort, out, prompt). agent_file and session_id belong to runtimes with agent files and to resume; they are refused here.

The process gets the environment of the run's git wrapper (RUN/git: HOME is RUN/home, no global git configuration, no ssh, no prompts,
the author qargi) and TMPDIR of the run, plus QARGI_MEMBER_RUN (the run directory: the mark that tells the marshal a member is running, wherever the
member changes to), PATH, the env_pass names and the variable of dispatch.home. It runs in its own session without a shell, its standard output goes
to OUT/transcript and its standard error to OUT/transcript.err, and a process group that outlives the bound is killed. A record of what ran is
written to RUN/dispatch.json (argv, class, model, outcome; never an environment value). --dry-run prints the argv and the prompt and writes
nothing. The exit status: 0 ok, 1 failed (or a usage error), 2 refused, 3 the runtime cannot be run this way, 4 transport.
"""
import errno
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import provider as P  # noqa: E402
import paths  # noqa: E402
import procenv as PE  # noqa: E402
from procenv import clean_path  # noqa: E402

_print = print


def print(*args, **kw):  # noqa: A001  (this module's print: what a definition names is written through P.vis)
    """The print of this module: a command, an argument or a note that comes from a runtime definition is written with its control, escape and
    bidi characters shown (\\x1b), so that --dry-run and the outcome lines cannot move the cursor or hide a line. The prompt is written as it is."""
    _print(*[P.vis(a) if isinstance(a, str) else a for a in args], **kw)


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

def child_env(run, tmp, passed, home=None):
    env = {"HOME": os.path.join(run, "home"), "PATH": clean_path(), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TZ": "UTC", "TERM": "dumb", "TMPDIR": tmp,
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1", "GIT_SSH_COMMAND": "false", "GIT_TERMINAL_PROMPT": "0",
           "GIT_ASKPASS": "false", "GIT_AUTHOR_NAME": "qargi", "GIT_COMMITTER_NAME": "qargi",
           "GIT_AUTHOR_EMAIL": "qargi@example.invalid", "GIT_COMMITTER_EMAIL": "qargi@example.invalid", "GIT": os.path.join(run, "git"),
           "QARGI_MEMBER_RUN": run}
    for n in passed:
        if n in os.environ:
            env[n] = os.environ[n]
    if home:
        env[home["env"]] = home["path"]
    return env


# ---- the run home (dispatch.home) -----------------------------------------------------------------------------------------------------

def plan_home(disp, run, runtime):
    """None, or what the run home of dispatch.home is: {env, dir, path, links: [(to, source)], missing: [to]}. The rules are provider.home_problems;
    a source is taken when it is a regular file whose real path is still under the user's home, outside qargi's directories and the credential
    stores home_link_problem refuses (a ~/.codex that is a link to elsewhere is followed, then checked). Nothing is made here."""
    h = disp.get("home")
    if h is None:
        return None
    bad = P.home_problems(h, disp.get("env_pass") if isinstance(disp.get("env_pass"), list) else ())
    if bad:
        fail("%s of %s" % (bad[0], runtime))
    home = os.path.realpath(os.path.expanduser("~"))
    mine = [os.path.realpath(d) for d in (paths.conf(), paths.state())]
    links, missing = [], []
    for ln in h.get("link", []):
        src = os.path.join(home, ln["from"][2:])
        real = os.path.realpath(src)
        if not os.path.lexists(src):
            missing.append(ln["to"])
            continue
        rel = os.path.relpath(real, home)
        if rel == ".." or rel.startswith(".." + os.sep):
            why = "it resolves outside the home"
        elif P.home_link_problem("~/" + rel) or any(real == m or real.startswith(m + os.sep) for m in mine):
            why = "it resolves into qargi's own directories or a credential store that is never linked"
        elif not os.path.isfile(real):
            why = "it is not a regular file"
        else:
            why = None
        if why:                                          # the message names the link, never where its source resolves to
            fail("dispatch.home.link of %s: the source of '%s' is refused: %s" % (runtime, ln["to"], why))
        links.append((ln["to"], src))
    return {"env": h["env"], "dir": h["dir"], "path": os.path.join(run, "home", h["dir"]), "links": links, "missing": missing}


O_DIR = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


def home_dir_fd(run, home, create):
    """A descriptor of RUN/home/DIR, opened part by part without following a link (a member can write the run directory: a link planted as
    RUN/home or as a part of DIR is refused, never followed). create: make the parts that are missing. None when a part is missing and
    create is off, or a part is not a plain directory (a refusal when create is on)."""
    fd = os.open(run, O_DIR)
    try:
        for part in ["home"] + home["dir"].split("/"):
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                nfd = os.open(part, O_DIR, dir_fd=fd)
            except OSError as e:
                if create:
                    fail("the run home %s cannot be made: %s is not a plain directory of the run (%s)" % (home["path"], part, e.strerror or e))
                return None
            os.close(fd)
            fd = nfd
        return os.dup(fd)
    finally:
        os.close(fd)


def make_home(run, home):
    """Make RUN/home/DIR and its links; the names linked. A link that an earlier run left there is replaced; anything else in its place is a refusal."""
    fd = home_dir_fd(run, home, True)
    made = []
    try:
        for to, src in home["links"]:
            try:
                st = os.lstat(to, dir_fd=fd)
            except FileNotFoundError:
                st = None
            if st is not None:
                if not stat.S_ISLNK(st.st_mode):
                    fail("%s is in the run home and is not a link qargi made; remove it, or the run is refused" % os.path.join(home["path"], to))
                os.unlink(to, dir_fd=fd)
            os.symlink(src, to, dir_fd=fd)
            made.append(to)
    except BaseException:
        clear_home(run, home, made)
        raise
    finally:
        os.close(fd)
    return made


def clear_home(run, home, names):
    """Remove the links of the run home (names), without following a link; notes for what was not as it was left: a file in place of a link
    (the runtime replaced it: it is removed too, so no copy of the source stays in the run), or a run home a member replaced."""
    notes = []
    if not names:
        return notes
    fd = home_dir_fd(run, home, False)
    if fd is None:
        return ["the run home %s is not the directory the run made (gone or replaced by a link); its links were not looked for there" % home["path"]]
    try:
        for to in names:
            try:
                st = os.lstat(to, dir_fd=fd)
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(st.st_mode) or stat.S_ISREG(st.st_mode):
                os.unlink(to, dir_fd=fd)
                if not stat.S_ISLNK(st.st_mode):
                    notes.append("%s in the run home was replaced during the run by a file, not the link; it is removed and its source was not updated" % to)
            else:
                notes.append("%s in the run home is not a link or a file any more; it was left in place" % to)
    finally:
        os.close(fd)
    return notes


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


def registry_tmp(run):
    """The run's temporary directory as the lead's registry ($QARGI_STATE/local-runs.jsonl, written by prepare) names it for this run
    directory, else "". The run's own tmpdir file is never read: a member can write the run directory, and that file could name another
    run's directory (the same rule as `local clean`). The last line for the run wins; only an absolute path is taken."""
    real, found = os.path.realpath(run), ""
    try:
        with open(os.path.join(paths.state(), "local-runs.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("run"), str) and isinstance(e.get("tmpdir"), str) \
                        and os.path.realpath(e["run"]) == real and os.path.isabs(e["tmpdir"]):
                    found = e["tmpdir"].rstrip("/") or ""
    except OSError:
        pass
    return found


def read_run_file(path, limit, what):
    """The text of a file of the run directory, "" when it is absent. The run directory is a member's to write: the file is opened without following a
    link and without waiting for a writer (a pipe in its place would stop the lead), and must be a regular file, or the run is refused."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        return ""
    except OSError as e:
        fail("%s (%s) cannot be read as a file of the run: %s" % (what, path, e.strerror or e))
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            fail("%s (%s) is not a regular file; the run is refused" % (what, path))
        with os.fdopen(fd, "rb", closefd=False) as f:
            data = f.read(limit + 1)
    finally:
        os.close(fd)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        fail("%s (%s) is not text" % (what, path))


def build(run, project, runtime, cls, task_file, model, effort, timeout, keep):
    """Everything a run needs, as a dict; Stop for a refusal. Nothing is written."""
    if not os.path.isfile(os.path.join(run, "refs.before")) or not os.path.isdir(os.path.join(run, "clone")):
        fail("run needs a RUN dir made by qargi local prepare", 1)
    out = os.path.join(run, "out")
    clone = os.path.join(run, "clone")
    tmp = registry_tmp(run) or os.path.join(run, "tmp")
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
    home = plan_home(disp, run, runtime)
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
        elif (doc.get("barrier") or {}).get("kind") in ("hook", "adapter") and state in ("yes", "partial") and not P.accepted(project, "local") and not has_class_args(disp):
            # the runtime's own barrier is a hook (it lives in the member file of a runtime that loads agent files; a local run has none) or an adapter's
            # barrier-check (a local run never calls it): nothing in this run applies it, so the capability that reads as held holds nothing here
            kind = doc["barrier"]["kind"]
            fail("the read-only barrier of %s on local is a %s, which a local run does not apply (%s) and its dispatch supplies no read-only arguments "
                 "(class_argv, or a {\"class\": \"read-only\"} group in argv), so it would start this member without a barrier: a read-only run is refused here.\n"
                 "Dispatch it where that barrier is applied, or, on your own responsibility, record that you accept no barrier for the project:\n  %s"
                 % (runtime, kind, "a local run has no agent file to carry the hook" if kind == "hook" else "a local run never calls the adapter's barrier-check",
                    P.accept_command(runtime, "local", project)))
        elif (doc.get("barrier") or {}).get("kind") == "sandbox-args" and not has_class_args(disp):
            fail("the barrier of %s is sandbox-args but its dispatch supplies no read-only arguments (class_argv, or a {\"class\": \"read-only\"} group in argv)" % runtime)
        note = text if state == "partial" else ""
    else:
        note = ""
    if task_file is None:
        task_text = read_run_file(os.path.join(run, "task.md"), MAX_TASK, "the task block")
        if not task_text:
            fail("no task block: write it to %s or give --task FILE" % os.path.join(run, "task.md"), 1)
    else:
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
    member = read_run_file(os.path.join(run, "profile"), 256, "the run's profile").strip()
    member = member or read_run_file(os.path.join(run, "ability"), 256, "the run's ability").strip()
    if not member:
        fail("%s is missing or empty: a run made by qargi local prepare records its ability there" % os.path.join(run, "ability"))
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
            "timeout_s": to, "env_pass": passed, "env": child_env(run, tmp, passed, home), "exit": ex, "model": mname, "effort_native": native,
            "home": home, "notes": notes + ([note] if note else []) + home_notes(home), "output_format": (disp.get("output") or {}).get("format", "text")}


def home_notes(home):
    return ["the source of the run home's link '%s' does not exist, so it is not linked: the runtime starts without it" % n for n in (home or {}).get("missing", [])]


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
    if plan["home"]:
        print("HOME_ENV=" + plan["home"]["env"])
        print("HOME_DIR=" + plan["home"]["path"])
        print("HOME_LINKS=" + ",".join(to for to, _ in plan["home"]["links"]))
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


def open_own(path, what):
    """Open path to write, new or replacing a file of its own, and return the file descriptor. It is refused when the final name is a link (O_NOFOLLOW),
    when it is anything but a regular file (a pipe in its place would stop the lead; a device or a socket is not ours to write) or when it has a second
    name (a hard link to a file elsewhere): the run directory is a member's to write, and a link planted as transcript, transcript.err or dispatch.json
    would make the lead truncate and overwrite the file it points to. The truncation comes after the checks, on the descriptor."""
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    except OSError as e:
        fail("cannot write %s (%s): %s" % (what, path, "it is a link or a pipe, not a plain file of its own" if e.errno in (errno.ELOOP, errno.ENXIO) else (e.strerror or e)))
    st = os.fstat(fd)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
        os.close(fd)
        fail("%s (%s) is not a plain file of its own (a pipe, a device or a file with another name); it is written only as a new or a regular file" % (what, path))
    os.set_blocking(fd, True)
    os.ftruncate(fd, 0)
    return fd


def check_own(path, what):
    """Refuse, before anything is run, a path that open_own would refuse (a run that cannot record its end is not started)."""
    if os.path.lexists(path):
        st = os.lstat(path)
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            fail("%s (%s) is not a plain file of its own; remove it, or the run is refused" % (what, path))


def write_private(path, text):
    fd = open_own(path, "the run record")
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
    if os.path.islink(out) or (os.path.exists(out) and not os.path.isdir(out)):
        fail("%s is not a plain directory of the run; the transcript goes there and nowhere else" % out)
    os.makedirs(out, exist_ok=True)
    if os.path.realpath(out) != os.path.join(os.path.realpath(run), "out"):
        fail("%s is not inside the run" % out)
    dispatch = os.path.join(run, "dispatch.json")
    check_own(dispatch, "the dispatch record")
    write_prompt(run, plan["prompt_file"], plan["prompt"])
    argv = [plan["exe"]] + plan["argv"][1:]
    home = plan["home"]
    made = make_home(run, home) if home else []          # the links exist for the length of the run only
    home_left = []
    started = time.time()
    timed_out = False
    try:
        sin = open(plan["prompt_file"], "rb") if plan["via"] == "stdin" else subprocess.DEVNULL
        with os.fdopen(open_own(os.path.join(out, "transcript"), "the transcript"), "wb") as so, \
                os.fdopen(open_own(os.path.join(out, "transcript.err"), "the error transcript"), "wb") as se:
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
    finally:
        home_left = clear_home(run, home, made) if home else []
    if timed_out:
        outcome = "failed"
    else:
        outcome = plan["exit"].get(str(code), plan["exit"].get("*", "failed"))
    rec = {"runtime": plan["runtime"], "class": plan["class"], "argv": plan["argv"], "command_from": plan["exe_from"], "cwd": plan["cwd"],
           "model": plan["model"], "effort_native": plan["effort_native"], "prompt_via": plan["via"], "timeout_s": plan["timeout_s"],
           "started": PE.now(started), "seconds": round(time.time() - started, 1),
           "exit": code, "timed_out": timed_out, "outcome": outcome, "transcript": os.path.join(out, "transcript")}
    if home:
        rec["home"] = {"env": home["env"], "dir": home["dir"], "links": made, "not_linked": home["missing"], "left": home_left}
    write_private(dispatch, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    print("RUNTIME=" + plan["runtime"])
    print("OUTCOME=" + outcome + (" (timed out after %ds)" % plan["timeout_s"] if timed_out else ""))
    print("EXIT=%s" % code)
    print("TRANSCRIPT=" + rec["transcript"])
    for n in home_left:
        print("qargi: note: " + n, file=sys.stderr)
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
        if not o["dry"] and not o["again"] and os.path.lexists(os.path.join(run, "dispatch.json")):
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
