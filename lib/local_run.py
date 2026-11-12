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
                       only when its record approves it; a shipped definition's is read from lib/providers/NAME/. A word is resolved on
                       the lead's PATH, entry by entry, to the first regular executable file whose real path has that name (or the name
                       with an extension, a launcher NAME.js, or with a suffix after a dash, a release binary NAME-x86_64-unknown-linux-musl),
                       and that real path runs (COMMAND=, `command` in dispatch.json): a wrapper or a shim linked to a program of another
                       name (a version manager's) is passed over with a note, since under the run's HOME it would look for the tool there;
                       with none left the run is refused (exit 3), naming each entry and why. The member's own PATH is the lead's, unchanged.
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
                       directory. What a runtime does to a link during the run (a sign-in refreshed): written through the link, it lands in the
                       source, which qargi cannot prevent (a note says the source changed); the link deleted, the source is untouched (a note); the
                       link replaced by a file of its own (an atomic replace), qargi never writes that file to the source (another run, a session of
                       the runtime or a sign-in of yours may have written the source meanwhile): it is kept as NAME.from-run (mode 600) in the run
                       home, named in the HOME_RESIDUE= line and in home.residue of dispatch.json (the name, never a value), with a note that says
                       whether the source is still what it was when the run started (its sha256 then, kept in memory, never printed or recorded);
                       you reconcile it yourself. qargi local list and verify name it and qargi local clean removes it. A variable env set in the
                       lead's environment to another directory than the links' sources is a note. provider.home_problems states the rules.
  dispatch.run_config  {in: home|run, file, baseline}: the configuration file of the run, rendered when the run starts in the format of
                       resources.mcp: the baseline (the definition's own settings, the same for every run) at its root, and the MCP servers
                       from resources.mcp (lib/packs_render.py run_config) for the run's role, as the lead's registry records it (never a file
                       of the run directory), and the run's class: each server lists the tools a member may call (lib/packs_mcp.py: never an
                       always_ask tool, under the read-only class only a declared read). in home: RUN/home/DIR/FILE, the run home of
                       dispatch.home, which a runtime reads by itself; in run: RUN/config/FILE. {run_config} is its path. Without a baseline it
                       is empty when no tool pack gives the role a tool: then nothing is written and a file of that name left there is removed.
                       It is written without following a link a member may have put in the run directory. --dry-run prints its path, the tool
                       names and the baseline (RUN_CONFIG=, RUN_CONFIG_TOOLS=, RUN_CONFIG_BASELINE=), never the servers' addresses.
  dispatch.hidden_paths {prefixes, shown, note}: the places the runtime's sandbox hides from the member's commands (a sandbox that mounts a /dev
                       of its own hides everything under /dev/shm), and, per class, the run paths it shows anyway (the places it binds in,
                       such as the writable directories of a write class). A run path the member of the class works with (provider.MEMBER_NEEDS:
                       CLONE, CONTRACT and GIT, and for a write run OUT and TMP too) whose path or real path lies under a prefix and that its
                       class does not show refuses the run before anything starts (exit 2), naming the path, the prefix and the fix (another
                       --scratch, or QARGI_RUN_TMP); local prepare refuses the same run before it makes anything.
  dispatch.timeout_s   the bound (default 1800, at most 86400); --timeout replaces it.
  dispatch.exit        {"0": "ok", "*": "failed"}: the exit status -> outcome ok|failed|refused|transport.
  dispatch.output      {format: text|jsonl, usage: {select, skip, tokens, fields, model}}: with usage (jsonl only), when the run ends every line
                       of OUT/transcript that is a JSON object the rule selects (and does not skip) is a report of the tokens the runtime
                       used; each field of the object at `tokens` is added up over those lines, and the sums go to dispatch.json (usage:
                       events, tokens, model) and to a USAGE= line. Only whole numbers count; a line that is not JSON is passed over. A field
                       that no such line reports is left out of tokens and named in unreported (absent is not zero).
Placeholders (the closed set): member, model, effort_native, prompt_file, prompt_arg, clone, run_dir, out_dir, project, run_config, final_message
(and the short names effort, out, prompt). agent_file and session_id belong to runtimes with agent files and to resume; they are refused here.
A path of the run in the argv ({clone}, {out_dir}, {run_dir}, alone or followed by a path such as {clone}/.git) stays inside its directory and, where it
exists, passes through no link, or the run is refused: a sandbox may be told to let the member write it.
  {final_message}      the file a runtime writes the member's last message to (a flag of its own, such as an output-last-message option): never a
                       file of OUT, but RUN/final.XXXXXXXXXXXX/message.md, in a directory of the run made new for each run (mode 700, a name no
                       earlier run used). When the process has ended the lead opens it without following a link or waiting for a writer and takes
                       it only as a regular file with one name, of text, at most 1 MiB; then it is published as OUT/report.md through a new file
                       renamed over that name (a link, a pipe or a second name there is replaced, never written through). The report of an earlier
                       run (--again) is set aside as OUT/report.md.previous before the member starts: a run that publishes a report replaces it, a run
                       that publishes none leaves it there, where no check takes it for this run's report. A report.md that is not a plain file of
                       its own refuses the run before anything starts. RUN/dispatch.json (report) and the REPORT= and PREVIOUS_REPORT= lines say
                       what became of both.
                       A read-only run with a final message is packaged by the lead, since its member may write nothing, OUT included: when the
                       outcome is ok, the report was published and OUT holds no patch, OUT/manifest.json is written in the minimal report-only format
                       of `qargi review save` (status, base, commits [], the report in artifacts), with what the lead recorded of the run (run: id,
                       role, runtime, class, model and effort as passed, start, seconds, exit, outcome), taken from the lead's registry and from
                       RUN/refs.before as read before the member started, never from the member. No test result and no verdict is written: review
                       check still reads the verdict in the report. The manifest of an earlier run is set aside as OUT/manifest.json.previous like
                       the report, and the MANIFEST= and PREVIOUS_MANIFEST= lines and dispatch.json (manifest) say what became of both.

The process gets the environment of the run's git wrapper (RUN/git: HOME is RUN/home, no global git configuration, no ssh, no prompts,
the author qargi) and TMPDIR of the run, plus QARGI_MEMBER_RUN (the run directory: the mark that tells the marshal a member is running, wherever the
member changes to), PATH, the env_pass names and the variable of dispatch.home. It runs in its own session without a shell, its standard output goes
to OUT/transcript and its standard error to OUT/transcript.err, and a process group that outlives the bound is stopped (kill_group). A record of what ran is
written to RUN/dispatch.json (argv, class, model, outcome; never an environment value): when the run starts (outcome running, with the process ids of
the runner and, once started, of the member), and again when it ends, whatever ended it: the member's exit, the bound, a run home, configuration file or
transcript that cannot be made (refused, with the error), a command that cannot be started (transport), or SIGINT, SIGTERM or SIGHUP to the runner
(interrupted, with the signal: the member's process group gets TERM, is watched for 5 seconds, then KILL for what is left of it, and the run
home's links are removed; the output says the group was stopped only when none of it is alive, and otherwise how many of its processes survived). SIGKILL leaves the start
record: the next start of the run refuses while that runner or its member still runs (the member is found by QARGI_MEMBER_RUN in its environment),
and otherwise needs --again, which replaces the links left in the run home and removes the stale last-message directories; qargi local clean
removes the run with them, and qargi local list and verify name the links left. A run home a member moved or replaced is searched for the links
qargi made, which are removed where found and named where not. When the member could write the clone's .git (git_watch: the argv names it, or the
run's class has no sandbox arguments of its own), what git in the clone would run (.git/config, hooks/, info/) is read before the member starts and
compared when it ends; a change other than what git branch sets is named (GITDIR=, git_dir in dispatch.json: key and entry names, never a value), not
restored, so the lead knows not to run git in that clone (worktree_changes runs it there only with what the member could set switched off).
--dry-run prints the argv and the prompt and writes nothing. The exit status: 0 ok, 1 failed (or a usage error), 2 refused, 3 the runtime cannot be
run this way, 4 transport, 128+N interrupted by signal N.
"""
import errno
import json
import os
import re
import secrets
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
from lead_usage import pointer  # noqa: E402  (the JSON pointer the transcript usage rule of a definition is read with)

_print = print


def print(*args, **kw):  # noqa: A001  (this module's print: what a definition names is written through P.vis)
    """The print of this module: a command, an argument or a note that comes from a runtime definition is written with its control, escape and
    bidi characters shown (\\x1b), so that --dry-run and the outcome lines cannot move the cursor or hide a line. The prompt is written as it is."""
    _print(*[P.vis(a) if isinstance(a, str) else a for a in args], **kw)


TOOL = os.path.dirname(HERE)
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
ALIASES = {"effort": "effort_native", "out": "out_dir", "prompt": "prompt_arg"}
CLOSED = ("member", "model", "effort_native", "prompt_file", "prompt_arg", "clone", "run_dir", "out_dir", "agent_file", "session_id", "project", "run_config",
          "final_message")
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
CONFIG_DIR = "config"     # where a run_config of "in": "run" goes, for the same reason
FINAL_PREFIX = "final."   # RUN/final.XXXXXXXXXXXX/: where the runtime writes the last message ({final_message}), a directory made new for each run
FINAL_NAME = "message.md"
REPORT = "report.md"      # what the last message is published as, in OUT
MANIFEST = "manifest.json"
PREVIOUS = ".previous"    # the report (and the lead's manifest) of an earlier run, set aside under this suffix: no check reads it as a report
MAX_REPORT = 1 << 20      # the bound of a published report, as qargi local report and review save have it


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


RUN_PATH = re.compile(r"\{(clone|out_dir|out|run_dir)\}(/[^\s=:,]*)?")


def check_run_paths(items, values, runtime):
    """A path the argv gives the runtime inside the run ({clone}, {out_dir}, {run_dir}, alone or with a path after it, such as {clone}/.git, which a
    sandbox may be told to let the member write): it must stay inside its directory (no '..' out of it) and, where it exists, pass through no link.
    The run directory is a member's to write: a link planted as RUN/clone/.git by an earlier run would point a writable root of the sandbox anywhere."""
    for s in walk_strings(items):
        for m in RUN_PATH.finditer(s):
            base = values.get(ALIASES.get(m.group(1), m.group(1)))
            if not base:
                continue
            path = os.path.normpath(base + (m.group(2) or ""))
            if path != base and not path.startswith(base + os.sep):
                fail("dispatch.argv of %s: %s leaves the directory {%s} names" % (runtime, m.group(0), m.group(1)))
            if os.path.lexists(path) and os.path.realpath(path) != path:
                fail("%s (%s in dispatch.argv of %s) passes through a link; a path the runtime is given in the run must be the run's own, so the run is refused"
                     % (path, m.group(0), runtime))


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
    links, missing, notes = [], [], []
    for ln in h.get("link", []):
        src = os.path.join(home, ln["from"][2:])
        if not os.path.lexists(src):
            missing.append(ln["to"])
            continue
        why = source_problem(src)[1]
        if why:                                          # the message names the link, never where its source resolves to
            fail("dispatch.home.link of %s: the source of '%s' is refused: %s" % (runtime, ln["to"], why))
        links.append((ln["to"], src))
    # the runtime's own variable set in the lead's environment to another directory: the run home's links come from the sources the definition names,
    # so a sign-in kept in that other directory is not linked (said, never the value)
    mine = os.environ.get(h["env"])
    froms = {os.path.realpath(os.path.dirname(os.path.join(home, ln["from"][2:]))) for ln in h.get("link", [])}
    if mine and froms and os.path.realpath(os.path.expanduser(mine)) not in froms:
        notes.append("%s is set in your environment to another directory than the one the run home's links come from (%s): the run links %s from there, "
                     "and a sign-in kept in the directory %s names is not used" % (h["env"], ", ".join(sorted({os.path.dirname(ln["from"]) for ln in h.get("link", [])})),
                                                                                   ", ".join(ln["from"] for ln in h.get("link", [])), h["env"]))
    return {"env": h["env"], "dir": h["dir"], "path": os.path.join(run, "home", h["dir"]), "links": links, "missing": missing, "notes": notes, "start": {},
            "residue": []}


def source_problem(src):
    """(real path, None) for a source of a run home's link that may be linked, or (real path, why not): its real path must be
    under the user's home, outside qargi's directories and the credential stores home_link_problem refuses, and a regular file."""
    home = os.path.realpath(os.path.expanduser("~"))
    mine = [os.path.realpath(d) for d in (paths.conf(), paths.state())]
    real = os.path.realpath(src)
    rel = os.path.relpath(real, home)
    if rel == ".." or rel.startswith(".." + os.sep):
        return real, "it resolves outside the home"
    if P.home_link_problem("~/" + rel) or any(real == m or real.startswith(m + os.sep) for m in mine):
        return real, "it resolves into qargi's own directories or a credential store that is never linked"
    if not os.path.isfile(real):
        return real, "it is not a regular file"
    return real, None


MAX_SIGNIN = 1 << 20      # the bound of a source digest_of reads (a larger one is not compared)


def digest_of(path):
    """The sha256 of the file at path (followed, as the runtime reads it through the link), read in memory only and never printed or recorded; None
    when it is not a regular file of at most MAX_SIGNIN bytes."""
    import hashlib
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_SIGNIN:
            return None
        h = hashlib.sha256()
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            h.update(chunk)
        return h.hexdigest()
    finally:
        os.close(fd)


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
                    fail("%s is in the run home and is not a link qargi made (a file a runtime wrote there in a run that did not end, or a member's); "
                         "remove it, or the run is refused" % os.path.join(home["path"], to))
                os.unlink(to, dir_fd=fd)
            home["start"][to] = (os.path.realpath(src), digest_of(src))   # what the source was when the run started: in memory only
            os.symlink(src, to, dir_fd=fd)
            made.append(to)
    except BaseException:
        clear_home(run, home, made)
        raise
    finally:
        os.close(fd)
    return made


def sweep_home(run, home, names):
    """The run home is not the directory the run made (moved away, or replaced by a link): the links qargi made (a link whose target is the source of
    one of names) are looked for anywhere under RUN/home, without following a link or entering one, and removed. Notes that say what was found where,
    and what could not be: a link moved out of RUN/home is not seen, so it is never said to be gone."""
    srcs = {src for to, src in home["links"] if to in names}
    found, kept = [], []
    try:
        top = sub_fd(run, "home")
    except OSError:
        return ["the run home %s is gone and so is %s: the link%s qargi made (%s) cannot be looked for; if the member moved %s out of the run "
                "directory, it is still there" % (home["path"], os.path.join(run, "home"), "s" if len(names) > 1 else "", ", ".join(names), "them" if len(names) > 1 else "it")]
    try:
        for dirpath, dirnames, filenames, dfd in os.fwalk(".", dir_fd=top, follow_symlinks=False):
            for n in dirnames + filenames:
                try:
                    if stat.S_ISLNK(os.lstat(n, dir_fd=dfd).st_mode) and os.readlink(n, dir_fd=dfd) in srcs:
                        os.unlink(n, dir_fd=dfd)
                        found.append(os.path.normpath(os.path.join(run, "home", dirpath, n)))
                except OSError:
                    kept.append(os.path.normpath(os.path.join(run, "home", dirpath, n)))
    finally:
        os.close(top)
    what = "gone" if not os.path.lexists(home["path"]) else "a link the member put there, left in place and not followed" if os.path.islink(home["path"]) \
        else "not a plain directory"
    notes = ["the run home %s is not the directory the run made (%s)" % (home["path"], what)]
    if found:
        notes.append("the link%s qargi made %s found under %s and removed: %s" % ("s" if len(found) > 1 else "", "were" if len(found) > 1 else "was",
                                                                                  os.path.join(run, "home"), ", ".join(found)))
    if len(found) < len(names):
        notes.append("%d link%s qargi made (%s) %s not found under %s: if the member moved it out of there it is still there; qargi local clean %s "
                     "removes the run directory" % (len(names) - len(found), "s" if len(names) - len(found) > 1 else "", ", ".join(names),
                                                     "was" if len(names) - len(found) == 1 else "were", os.path.join(run, "home"), run))
    for p in kept:
        notes.append("%s could not be checked or removed" % p)
    return notes


def clear_home(run, home, names):
    """Remove the links of the run home (names), without following a link; notes for what was not as it was left: a source written through its link,
    a file in place of a link (the runtime replaced it: kept as NAME.from-run, keep_replacement), or a run home a member replaced."""
    notes = []
    if not names:
        return notes
    fd = home_dir_fd(run, home, False)
    if fd is None:
        return sweep_home(run, home, names)
    try:
        for to in names:
            src = dict(home["links"]).get(to)
            real0, sum0 = home["start"].get(to, (None, None))
            try:
                st = os.lstat(to, dir_fd=fd)
            except FileNotFoundError:
                notes.append("%s was removed from the run home during the run (by the runtime or the member); its source is untouched" % to)
                continue
            if stat.S_ISLNK(st.st_mode):
                target = os.readlink(to, dir_fd=fd)
                os.unlink(to, dir_fd=fd)                 # the name only: what it points to is untouched
                if target != src:
                    notes.append("%s in the run home pointed elsewhere at the end of the run; the link is removed, what it pointed to is untouched" % to)
                elif sum0 is not None and digest_of(src) != sum0:
                    notes.append("the source of %s changed during the run (written through the link, such as a sign-in the runtime refreshed in place, "
                                 "or by another program); it keeps what was written: a write through the link reaches the source, which qargi cannot "
                                 "prevent" % to)
            elif stat.S_ISREG(st.st_mode):
                notes.append(keep_replacement(fd, to, src, real0, sum0, home))
            else:
                notes.append("%s in the run home is not a link or a file any more; it was left in place" % to)
    finally:
        os.close(fd)
    return notes


KEPT = ".from-run"   # a file a runtime put in place of a run home's link is kept in the run home under this suffix; qargi never writes it to the source


def keep_replacement(fd, to, src, real0, sum0, home):
    """A regular file in place of the link `to` at the end of the run: the runtime (or the member) replaced the link with a file of its own (a sign-in
    written anew by an atomic replace, which does not write through a link). qargi never writes it to the source: another run, a session of the
    runtime or a sign-in of yours may write the source at any moment, and no check qargi makes before a rename keeps such a writer out, so a newer
    sign-in would be lost. The file is kept in the run home as NAME.from-run (mode 600), over one an earlier run left there, and its name goes to
    home["residue"]: you compare it with yours and put it in place yourself. A second name of another file is removed (a name only). The note says
    which, and whether the source is still the file it was when the run started (the same real path and sha256), never a value."""
    here = os.path.join(home["path"], to)
    try:
        rfd = os.open(to, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    except OSError:
        return "%s in the run home could not be read at the end of the run; it was left in place" % to
    try:
        st = os.fstat(rfd)
        if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1:
            os.unlink(to, dir_fd=fd)
            return "%s in the run home was replaced during the run by a second name of another file; the name is removed, and the source is untouched" % to
        if src is None or real0 is None or sum0 is None:
            now = "the source was not read when the run started, so whether it changed since is not known"
        else:
            real, bad = source_problem(src)
            now = ("your file is unchanged since the run started" if not bad and real == real0 and digest_of(real) == sum0
                   else "your file changed since the run started (another sign-in, another run, or another program): keep yours")
        try:
            try:
                earlier = bool(os.lstat(to + KEPT, dir_fd=fd))
            except FileNotFoundError:
                earlier = False
            os.fchmod(rfd, 0o600)
            os.rename(to, to + KEPT, src_dir_fd=fd, dst_dir_fd=fd)
        except OSError as e:
            return ("%s in the run home was replaced during the run by a file of its own; qargi does not write it to your file, and it could not be set aside "
                    "as %s (%s), so it was left in place" % (to, here + KEPT, e.strerror or e))
        home["residue"].append(to + KEPT)
        return ("%s in the run home was replaced during the run by a file of its own (a sign-in written anew, or the member's); qargi never writes it to your "
                "file. It is kept as %s (mode 600)%s; %s. Compare it with yours and, to use it, move it over yours yourself; qargi local clean removes it "
                "with the run" % (to, here + KEPT, ", in place of the one an earlier run kept there" if earlier else "", now))
    finally:
        os.close(rfd)


# ---- the configuration file of the run (dispatch.run_config) -------------------------------------------------------------------------

def merge_into(doc, add, where=""):
    """Put every key of add into doc, objects key by key; a key both set to something other than two objects is a refusal (the rules of
    provider.run_config_problems keep the baseline out of the servers' place, so this is the last check, not the first)."""
    for k, v in add.items():
        if k in doc and isinstance(doc[k], dict) and isinstance(v, dict):
            merge_into(doc[k], v, where + "/" + k)
        elif k in doc:
            fail("the baseline of the run's configuration file and its MCP servers both set %s/%s" % (where, k))
        else:
            doc[k] = v


def config_bytes(mcp, baseline, data):
    """The bytes of the run's file: the MCP servers (data, bytes in the format of resources.mcp, or None) with the baseline at the root, written in that
    format (the TOML writer of lib/packs_render.py, or JSON); None when there is neither."""
    if not baseline:
        return data
    import copy
    import packs_render
    fmt = (mcp or {}).get("format", "json")
    doc = copy.deepcopy(baseline)
    if data is not None:
        import tomllib
        merge_into(doc, tomllib.loads(data.decode("utf-8")) if fmt == "toml" else json.loads(data))
    return packs_render.toml_dumps(doc) if fmt == "toml" else (json.dumps(doc, indent=2, sort_keys=True) + "\n").encode()


def plan_run_config(disp, doc, run, home, project, cls, runtime):
    """None, or the configuration file of the run: {in, file, path, data (bytes or None: no baseline and no tool for the run, the file is removed),
    tools, servers, role, baseline, note}. The role is the one the lead's registry records for the run; the class is the run's. The rules are
    provider.run_config_problems. Nothing is written here."""
    rc = disp.get("run_config")
    if rc is None:
        return None
    bad = P.run_config_problems(disp, doc.get("resources"))
    if bad:
        fail("%s of %s" % (bad[0], runtime))
    where = home["path"] if rc["in"] == "home" else os.path.join(run, CONFIG_DIR)
    mcp = (doc.get("resources") or {}).get("mcp")
    base = rc.get("baseline") or None
    plan = {"in": rc["in"], "file": rc["file"], "path": os.path.join(where, rc["file"]), "data": None, "tools": [], "servers": {}, "role": None,
            "baseline": base, "note": None}
    import packs_mcp
    import packs_render
    role = registry_line(run).get("ability")
    got = None
    if not isinstance(role, str) or not role:
        plan["note"] = "the lead's registry names no role for this run, so it is given no MCP tool"
    else:
        plan["role"] = role
        try:
            got = packs_render.run_config(paths.conf(), project, [role], {role: cls == "read-only"}, mcp)
        except (packs_mcp.McpError, ValueError, OSError) as e:      # the links, the answers or a pack cannot be read: no run is started from a guess
            fail("the MCP file of the run (dispatch.run_config of %s) cannot be made: %s" % (runtime, e))
        if got:
            plan.update(tools=got["tools"], servers=got["servers"])
    try:
        plan["data"] = config_bytes(mcp, base, got["data"] if got else None)
    except ValueError as e:                                          # a value the writer does not write, or a file that does not read back
        fail("the configuration file of the run (dispatch.run_config of %s) cannot be made: %s" % (runtime, e))
    return plan


def config_dir_fd(run, plan, home):
    """A descriptor of the directory of the run's configuration file, made when missing, opened part by part without following a link (home_dir_fd for the run
    home; RUN/config otherwise)."""
    if plan["in"] == "home":
        return home_dir_fd(run, home, True)
    fd = os.open(run, O_DIR)
    try:
        try:
            os.mkdir(CONFIG_DIR, 0o700, dir_fd=fd)
        except FileExistsError:
            pass
        try:
            return os.open(CONFIG_DIR, O_DIR, dir_fd=fd)
        except OSError as e:
            fail("%s is not a plain directory of the run; the configuration file of the run goes there and nowhere else (%s)" % (os.path.join(run, CONFIG_DIR), e.strerror or e))
    finally:
        os.close(fd)


def put_run_config(run, plan, home):
    """Write the run's configuration file (mode 600, a new or regular file of its own, never through a link), or, with no baseline and no tool for the
    run, remove a file of that name left there (a link or a regular file; anything else is a refusal), so the runtime reads none."""
    fd = config_dir_fd(run, plan, home)
    try:
        try:
            st = os.lstat(plan["file"], dir_fd=fd)
        except FileNotFoundError:
            st = None
        if st is not None and not (stat.S_ISREG(st.st_mode) or stat.S_ISLNK(st.st_mode)):
            fail("%s is in the place of the run's configuration file and is not a file; remove it, or the run is refused" % plan["path"])
        if st is not None and (stat.S_ISLNK(st.st_mode) or st.st_nlink != 1 or plan["data"] is None):
            os.unlink(plan["file"], dir_fd=fd)                  # a link or a second name is never written through
        if plan["data"] is None:
            return
        wfd = os.open(plan["file"], os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        os.fchmod(wfd, 0o600)
        with os.fdopen(wfd, "wb") as f:
            f.write(plan["data"])
    finally:
        os.close(fd)


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


EXTENSION = re.compile(r"[A-Za-z0-9]+\Z")
SUFFIX = re.compile(r"[A-Za-z0-9_.-]+\Z")


def program_named(real, exe):
    """Is the file at the real path real the program exe names: its name is exe, exe with an extension (a launcher NAME.js or NAME.py
    that a package manager links as NAME) or exe with a suffix after a dash (a release binary NAME-x86_64-unknown-linux-musl linked as NAME)?
    A wrapper or a shim that is a link to a program of another name (a version manager's multi-call program) is not."""
    b = os.path.basename(real)
    return b == exe or (b.startswith(exe + ".") and bool(EXTENSION.match(b[len(exe) + 1:]))) \
        or (b.startswith(exe + "-") and bool(SUFFIX.match(b[len(exe) + 1:])))


def resolve_on_path(exe):
    """(real path or None, passed over): the first entry of the lead's PATH, in order, that holds a regular executable file named exe whose real
    path is the program exe names (program_named), as that real path; passed over is [(path, why)] for each entry before it that holds
    something named exe and is not that. The member's own PATH is not changed by this: only what runs as argv[0] is."""
    passed, seen = [], set()
    for d in clean_path().split(os.pathsep):
        if d in seen:
            continue
        seen.add(d)
        cand = os.path.join(d, exe)
        if not os.path.lexists(cand):
            continue
        real = os.path.realpath(cand)
        if not os.path.exists(real):
            passed.append((cand, "a link to nothing"))
        elif not os.path.isfile(real):
            passed.append((cand, "not a regular file"))
        elif not os.access(real, os.X_OK):
            passed.append((cand, "not executable"))
        elif not program_named(real, exe):
            passed.append((cand, "it resolves to %s, a program named %s, not %s: a wrapper or a shim, which under the run's home would look for "
                                 "the tool there" % (real, os.path.basename(real), exe)))
        else:
            return real, passed
    return None, passed


def find_command(runtime, exe, run, keep):
    """(path, how, notes): where the command of argv[0] is run from. keep collects a directory to remove afterwards (an exec copy)."""
    if not isinstance(exe, str) or not exe or PLACEHOLDER.search(exe):
        fail("dispatch.argv[0] of %s must be a plain command: a word looked up on PATH, or a path inside the definition's directory" % runtime)
    if "/" not in exe:
        found, passed = resolve_on_path(exe)
        if not found and not passed:
            fail("the command '%s' of runtime %s is not on PATH; install it first (it is run by name, as you would run it)" % (exe, runtime), 3)
        if not found:
            fail("the command '%s' of runtime %s has no program of that name on PATH that a run can start; passed over: %s. Put the directory of "
                 "the real program first on PATH (for a version manager, the directory it installed the tool in): a run never starts a wrapper"
                 % (exe, runtime, "; ".join("%s (%s)" % p for p in passed)), 3)
        if found.startswith(os.path.realpath(run) + os.sep):
            fail("the command '%s' resolves into the run directory; refused" % exe)
        return found, "on PATH", ["%s on PATH is passed over (%s); the run starts %s" % (p, why, found) for p, why in passed]
    n = os.path.normpath(exe)
    if os.path.isabs(exe) or n != exe or n.startswith(".."):
        fail("dispatch.argv[0] '%s' of %s is not a path inside the definition's directory" % (exe, runtime))
    if P.origin(runtime) == "library":
        d, path = P.exec_copy(runtime, exe)              # Drift or Refused unless the pack is sealed and approves exactly this executable
        keep.append(os.path.dirname(d))                  # exec_copy makes TMP/qargi-exec.XXXX/NAME; the whole of it goes
        return path, "sealed copy of pack %s" % runtime, []
    path = os.path.join(P.PROVIDERS, runtime, exe)
    if not os.path.isfile(path) or not os.access(path, os.X_OK) or not os.path.realpath(path).startswith(os.path.realpath(os.path.join(P.PROVIDERS, runtime)) + os.sep):
        fail("dispatch.argv[0] '%s' of %s is not an executable inside lib/providers/%s/" % (exe, runtime, runtime), 3)
    return path, "shipped with %s" % runtime, []


def registry_line(run):
    """The lead's registry line ($QARGI_STATE/local-runs.jsonl, written by prepare) for this run directory, the last one wins, or {}. What it says
    of a run is believed over the run's own files: a member can write the run directory (the same rule as `local clean`)."""
    real, found = os.path.realpath(run), {}
    try:
        with open(os.path.join(paths.state(), "local-runs.jsonl"), encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and isinstance(e.get("run"), str) and os.path.realpath(e["run"]) == real:
                    found = e
    except OSError:
        pass
    return found


def registry_tmp(run):
    """The run's temporary directory as the lead's registry names it for this run directory, else "". The run's own tmpdir file is never read: it
    could name another run's directory. Only an absolute path is taken."""
    t = registry_line(run).get("tmpdir")
    return (t.rstrip("/") or "") if isinstance(t, str) and os.path.isabs(t) else ""


def base_sha(run, base):
    """The commit of BASE that `local prepare` recorded in RUN/refs.before (the line `local refs/heads/BASE SHA`), else "". Read as a file of the run:
    no link followed, no writer waited for, a regular file only (as review save and local report read it)."""
    want = "local refs/heads/%s " % base
    try:
        fd = os.open(os.path.join(run, "refs.before"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return ""
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return ""
        with os.fdopen(fd, "rb", closefd=False) as f:
            for raw in f:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith(want):
                    sha = line[len(want):].strip()
                    return sha if re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", sha) else ""
    finally:
        os.close(fd)
    return ""


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
    bad = P.output_usage_problems(disp.get("output"), shape=True)
    if bad:
        fail("%s of %s" % (bad[0], runtime))
    home = plan_home(disp, run, runtime)
    rcfg = plan_run_config(disp, doc, run, home, project, cls, runtime)
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
    bad = P.hidden_paths_problems(disp, shape=True)
    if bad:
        fail("%s of %s" % (bad[0], runtime))
    hidden = P.hidden_run_paths(disp, cls, {"clone": clone, "contract": os.path.join(run, "contract"), "git": os.path.join(run, "git"), "out": out, "tmp": tmp})
    if hidden:
        fail(P.hidden_message(runtime, cls, hidden, disp))
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
    final = package = None
    if "final_message" in used:                          # a name no earlier run used: the directory is made new when the run starts (make_final)
        stage = FINAL_PREFIX + secrets.token_hex(6)
        final = {"dir": stage, "path": os.path.join(run, stage, FINAL_NAME)}
        if cls == "read-only":                           # what the lead's manifest says of the run, read before the member starts
            reg = registry_line(run)
            base = reg.get("base") if isinstance(reg.get("base"), str) else ""
            package = {"registered": bool(reg), "role": reg.get("ability") if isinstance(reg.get("ability"), str) else "",
                       "slug": reg.get("slug") if isinstance(reg.get("slug"), str) else "", "base": base,
                       "base_sha": base_sha(run, base) if base else "", "effort": effort or None}
    values = {"member": member, "model": mname, "effort_native": native or "", "prompt_file": pfile, "prompt_arg": prompt if via == "arg" else "",
              "clone": clone, "run_dir": run, "out_dir": out, "project": project, "run_config": rcfg["path"] if rcfg and rcfg["data"] is not None else "",
              "final_message": final["path"] if final else ""}
    argv = expand(argv_t, values, cls, "dispatch.argv", runtime)
    extra = expand(class_extra(disp, cls, runtime), values, cls, "dispatch.class_argv", runtime)
    check_run_paths(argv_t + class_extra(disp, cls, runtime), values, runtime)
    if extra:
        at = next((i for i, a in enumerate(argv) if via == "arg" and prompt in a), len(argv))
        argv[at:at] = extra
    cwd = expand([disp.get("cwd", "{clone}")], values, cls, "dispatch.cwd", runtime)[0]
    real = os.path.realpath(cwd)
    if real != os.path.realpath(clone) and not real.startswith(os.path.realpath(clone) + os.sep):
        fail("dispatch.cwd of %s is %s, outside the clone" % (runtime, cwd))
    exe, how, exe_notes = find_command(runtime, argv[0], run, keep)
    watched = git_watch(argv_t, class_extra(disp, cls, runtime), cls, argv, clone)
    return {"runtime": runtime, "class": cls, "argv": argv, "exe": exe, "exe_from": how, "cwd": cwd, "via": via, "prompt": prompt, "prompt_file": pfile,
            "timeout_s": to, "env_pass": passed, "env": child_env(run, tmp, passed, home), "exit": ex, "model": mname, "effort_native": native,
            "home": home, "notes": exe_notes + notes + ([note] if note else []) + home_notes(home) + ([rcfg["note"]] if rcfg and rcfg["note"] else []),
            "output_format": (disp.get("output") or {}).get("format", "text"), "usage": (disp.get("output") or {}).get("usage"), "run_config": rcfg,
            "final": final, "package": package, "git_watch": watched}


def home_notes(home):
    return ["the source of the run home's link '%s' does not exist, so it is not linked: the runtime starts without it" % n for n in (home or {}).get("missing", [])] \
        + (home or {}).get("notes", [])


def dry(plan, run):
    exe = plan["exe"] if plan["exe_from"] == "on PATH" else "<%s>/%s" % (plan["exe_from"], plan["argv"][0])
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
    rc = plan["run_config"]
    if rc:                                                 # the path and the tool names only: the file holds the servers' addresses
        if rc["data"] is None:
            print("RUN_CONFIG=none: no tool pack gives %s a tool; nothing is written and a file %s left there is removed"
                  % ("the role %s of this run" % rc["role"] if rc["role"] else "this run", rc["path"]))
        else:
            print("RUN_CONFIG=" + rc["path"])
        print("RUN_CONFIG_TOOLS=" + ",".join(rc["tools"]))
        if rc["baseline"]:                                 # the definition's own settings, the same for every run of the runtime
            print("RUN_CONFIG_BASELINE=" + json.dumps(rc["baseline"], sort_keys=True, separators=(",", ":")))
    print("PROMPT_VIA=" + plan["via"])
    print("PROMPT_FILE=" + plan["prompt_file"])
    print("TRANSCRIPT=" + os.path.join(run, "out", "transcript"))
    if plan["final"]:
        print("FINAL_MESSAGE=%s (its directory is made new when the run starts; the file is published as %s)" % (plan["final"]["path"], os.path.join(run, "out", REPORT)))
    for n in plan["notes"]:
        print("NOTE=" + n)
    print("PROMPT:")
    sys.stdout.write(plan["prompt"])
    sys.stdout.flush()


USAGE_SCAN_MAX = 256 * 1024 * 1024    # bytes of a transcript read for the usage; past it the sums are of what was read, and say so


def read_usage(path, rule):
    """{events, tokens: {field: sum}, unreported?, model?, note?} of the transcript at path under the usage rule of dispatch.output, or None when it
    cannot be read as a file of the run (it is opened without following a link or waiting for a writer, as a regular file only). A line counts when
    it is a JSON object whose select pointers all have their values, none of whose skip pointers has its value, and whose tokens pointer is an
    object; each field that is a whole number of at least 0 is added. A field that no counted line reports is left out of tokens and named in
    unreported: absent is not zero. model: the last text at the model pointer, when the rule has one."""
    fields = list(rule["fields"])
    sums, events, model, read, note = {}, 0, None, 0, None
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            return None
        with os.fdopen(fd, "rb", closefd=False) as f:
            for raw in f:
                read += len(raw)
                if read > USAGE_SCAN_MAX:
                    note = "only the first %d bytes of the transcript were read" % USAGE_SCAN_MAX
                    break
                try:
                    rec = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(rec, dict):
                    continue
                if any(pointer(rec, k) != v for k, v in (rule.get("select") or {}).items()):
                    continue
                if any(pointer(rec, k) is not None and pointer(rec, k) == v for k, v in (rule.get("skip") or {}).items()):
                    continue
                counts = pointer(rec, rule.get("tokens") or "")
                if not isinstance(counts, dict):
                    continue
                events += 1
                for k in fields:
                    n = counts.get(k)
                    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                        sums[k] = sums.get(k, 0) + n
                if rule.get("model"):
                    m = pointer(rec, rule["model"])
                    if isinstance(m, str) and m:
                        model = m[:80]
    finally:
        os.close(fd)
    got = {"events": events, "tokens": {f: sums[f] for f in fields if f in sums}}
    if events and len(sums) < len(fields):
        got["unreported"] = [f for f in fields if f not in sums]
    if rule.get("model"):
        got["model"] = model
    if note:
        got["note"] = note
    return got


def usage_line(u):
    if u is None:
        return "USAGE=unknown: the transcript could not be read as a file of the run"
    if not u["events"]:
        return "USAGE=none: no line of the transcript is a usage report of the runtime (dispatch.output.usage)"
    return "USAGE=%s (%d event%s%s%s)" % (" ".join("%s=%d" % kv for kv in u["tokens"].items()) or "unreported", u["events"], "" if u["events"] == 1 else "s",
                                         "; not reported, so not counted: " + ",".join(u["unreported"]) if u.get("unreported") else "",
                                         "; " + u["note"] if u.get("note") else "")


INTERRUPT = (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)


class Interrupted(BaseException):
    """A SIGINT, SIGTERM or SIGHUP to the runner (Signals): the member's process group is stopped and the run ends as interrupted."""
    def __init__(self, signum):
        BaseException.__init__(self, signum)
        self.signum = signum


class Signals:
    """SIGINT, SIGTERM and SIGHUP while a run is under way. The first one is recorded: while the lead waits for the member (armed) it is raised there
    (Interrupted), so the member's process group is stopped (kill_group: TERM, the group watched for 5 seconds, then KILL for what is left) and the
    run home is cleared;
    before the member starts it is acted on at the next check, and after the member has ended it is only noted, so the run's end is never cut short.
    A later one is recorded by nothing. A signal the runner was started with set to be ignored (nohup) stays ignored. SIGKILL cannot be caught:
    then RUN/dispatch.json still says running, with the runner's and the member's process ids, and the next start or qargi local clean clears it."""
    def __init__(self):
        self.sig, self.armed, self.old = None, False, {}

    def install(self):
        for s in INTERRUPT:
            cur = signal.getsignal(s)
            if cur == signal.SIG_IGN:
                continue
            self.old[s] = cur
            signal.signal(s, self.handle)

    def handle(self, signum, frame):
        if self.sig is not None:
            return
        self.sig = signum
        if self.armed:
            self.armed = False
            raise Interrupted(signum)

    def check(self):
        if self.sig is not None:
            raise Interrupted(self.sig)

    def restore(self):
        for s, h in self.old.items():
            signal.signal(s, h if h is not None else signal.SIG_DFL)


def clear_stale_finals(run):
    """Remove what a killed run left of its {final_message} directories (RUN/final.*): the message file, a name only, and the directory. A link in place
    of one is not followed and a directory in place of the file is left."""
    try:
        with os.scandir(run) as it:
            stale = [e.name for e in it if e.name.startswith(FINAL_PREFIX) and e.is_dir(follow_symlinks=False)]
    except OSError:
        return
    for name in stale:
        try:
            sfd = sub_fd(run, name)
        except OSError:
            continue
        try:
            if not stat.S_ISDIR(os.lstat(FINAL_NAME, dir_fd=sfd).st_mode):
                os.unlink(FINAL_NAME, dir_fd=sfd)
        except OSError:
            pass
        finally:
            os.close(sfd)
        try:
            rfd = os.open(run, O_DIR)
            try:
                os.rmdir(name, dir_fd=rfd)
            finally:
                os.close(rfd)
        except OSError:
            pass


def proc_of_run(pid, run, what):
    """Is pid a live process of this run: the runner (its command line names local_run.py and the run) or the member (its environment carries
    QARGI_MEMBER_RUN=run, which the member's runtime and its children inherit)? Read from /proc; False when it cannot be told. A relative path in the
    runner's command line is taken from the runner's working directory (/proc/PID/cwd), never from the checker's."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return False
    try:
        with open("/proc/%d/%s" % (pid, "cmdline" if what == "runner" else "environ"), "rb") as f:
            items = f.read(1 << 20).split(b"\0")
    except OSError:
        return False
    if what == "runner":
        if not any(i.endswith(b"local_run.py") for i in items):
            return False
        try:
            cwd = os.readlink("/proc/%d/cwd" % pid)
        except OSError:
            cwd = None
        names = [os.fsdecode(i) for i in items if i]
        return any(os.path.realpath(n) == run if os.path.isabs(n) else cwd is not None and os.path.realpath(os.path.join(cwd, n)) == run for n in names)
    return ("QARGI_MEMBER_RUN=" + run).encode() in items


def earlier_start(run, again):
    """Refuse a start while an earlier one of this run is under way or its member still runs; a start record left by a runner that is gone (killed
    with SIGKILL, or by a reboot) needs --again, which clears what it left. A record of a run that ended needs --again as before."""
    path = os.path.join(run, "dispatch.json")
    if not os.path.lexists(path):
        return
    try:
        rec = json.loads(read_run_file(path, 1 << 20, "the dispatch record") or "{}")
    except (ValueError, Stop):
        rec = {}
    if isinstance(rec, dict) and rec.get("outcome") == "running":
        if proc_of_run(rec.get("runner"), run, "runner"):
            fail("%s is being run now (qargi local run, process %d); it is started once at a time" % (run, rec["runner"]))
        if proc_of_run(rec.get("member"), run, "member"):
            fail("the member of an earlier start of %s is still running (process group %d), its runner is gone: stop it first (kill -TERM -- -%d), then "
                 "qargi local run %s --again" % (run, rec["member"], rec["member"], run))
        if not again:
            fail("%s was started and did not end: its runner is gone (killed with SIGKILL, or the machine restarted), so %s still says running and the run "
                 "home may still hold its links. qargi local run %s --again starts it again and replaces them; qargi local clean %s --discard drops the run"
                 % (run, path, run, run))
    elif not again:
        fail("%s has been run already (%s); --again runs it again and replaces the transcript" % (run, path))


KILL_GRACE = 5   # seconds kill_group watches the member's process group after TERM, and again after KILL


def group_left(pgid):
    """The pids of the live processes (not zombies) in the process group pgid, read from /proc; when /proc cannot be read, [pgid] while
    the group can still be signalled, else []."""
    try:
        names = os.listdir("/proc")
    except OSError:
        try:
            os.killpg(pgid, 0)
            return [pgid]
        except OSError:
            return []
    want, left = str(pgid).encode(), []
    for n in names:
        if not n.isdigit():
            continue
        try:
            with open("/proc/%s/stat" % n, "rb") as f:
                st = f.read()
        except OSError:
            continue
        rest = st[st.rfind(b")") + 2:].split()      # after the command name: state, ppid, pgrp, ...
        if len(rest) > 2 and rest[0] not in (b"Z", b"X") and rest[2] == want:
            left.append(int(n))
    return left


def kill_group(proc, grace=KILL_GRACE):
    """Stop the member's process group: TERM to the group, which is then watched (the group, not only the member: a descendant may ignore TERM
    after the member has ended) until none of it is alive or grace seconds have passed; then KILL to what is left, watched the same way. The member
    is reaped. The number of the group's processes still alive at the end: 0 when the group is gone. A process that moved to a process group of
    its own is not in the group and is not reached."""
    pg = proc.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(pg, sig)
        except ProcessLookupError:
            break
        except PermissionError:
            pass
        end = time.monotonic() + grace
        while True:
            proc.poll()
            if not group_left(pg):
                proc.poll()
                return 0
            if time.monotonic() >= end:
                break
            time.sleep(0.05)
    proc.poll()
    return len(group_left(pg))


def stopped_text(left):
    """What became of the member's process group, for the output: stopped only when none of it is alive."""
    if not left:
        return "the member's process group was stopped"
    return ("a descendant survived: %d process%s of the member's process group still alive after TERM and KILL" % (left, "" if left == 1 else "es"))


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


# ---- the member's last message ({final_message}) -------------------------------------------------------------------------------------

def kind_of(mode):
    for test, name in ((stat.S_ISLNK, "a link"), (stat.S_ISDIR, "a directory"), (stat.S_ISFIFO, "a pipe"), (stat.S_ISSOCK, "a socket"),
                       (stat.S_ISCHR, "a device"), (stat.S_ISBLK, "a device")):
        if test(mode):
            return name
    return "not a regular file"


def sub_fd(run, name):
    """A descriptor of the directory RUN/name, opened without following a link."""
    fd = os.open(run, O_DIR)
    try:
        return os.open(name, O_DIR, dir_fd=fd)
    finally:
        os.close(fd)


def set_aside(ofd, name):
    """OUT/name of an earlier run is renamed name.previous (over an older one), so nothing of an earlier run reads as this run's. True when there
    is one now: just set aside, or set aside by an earlier run that published none. check_own has refused, before anything was made, a name there
    that is not a plain file of its own; a rename moves the name only."""
    try:
        os.lstat(name, dir_fd=ofd)
    except FileNotFoundError:
        try:
            os.lstat(name + PREVIOUS, dir_fd=ofd)
            return True
        except FileNotFoundError:
            return False
    try:
        os.rename(name, name + PREVIOUS, src_dir_fd=ofd, dst_dir_fd=ofd)
    except OSError as e:
        fail("%s of an earlier run cannot be set aside as %s: %s; remove it, or the run is refused" % (name, name + PREVIOUS, e.strerror or e))
    return True


def make_final(run, final):
    """Make the directory of {final_message}, RUN/final.XXXXXXXXXXXX, new (mode 700): one of that name that exists refuses the run."""
    fd = os.open(run, O_DIR)
    try:
        os.mkdir(final["dir"], 0o700, dir_fd=fd)
    except OSError as e:
        fail("the directory of the member's last message %s cannot be made: %s" % (os.path.join(run, final["dir"]), e.strerror or e))
    finally:
        os.close(fd)


def take_final(run, final):
    """After the process: (state, data, why, kept). state is "ok" (data: the bytes to publish), "none" (no file), "empty" or "refused". The file is
    opened in the directory the run made (a link in its place is not followed), without following a link and without waiting for a writer, and taken
    only as a regular file with one name, of UTF-8 text without NUL, at most MAX_REPORT bytes. A name that is not taken is removed when it is a name
    only (a link, a pipe, a socket, a second name of a file elsewhere); a file of its own that is too large or not text is kept for the lead to read
    (kept: its path); a directory is left. The directory goes when it is empty."""
    try:
        sfd = sub_fd(run, final["dir"])
    except OSError as e:
        return "refused", None, "its directory %s is not the one the run made (%s)" % (os.path.join(run, final["dir"]), e.strerror or e), None
    state, data, why, keep = "refused", None, None, False
    try:
        try:
            fd = os.open(FINAL_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=sfd)
        except FileNotFoundError:
            fd, state, why = None, "none", "the runtime wrote no last message to %s" % final["path"]
        except OSError as e:
            fd = None
            why = "%s is %s" % (final["path"], "a link" if e.errno == errno.ELOOP else "a socket" if e.errno == errno.ENXIO else "not readable (%s)" % (e.strerror or e))
        if fd is not None:
            try:
                st = os.fstat(fd)
                if not stat.S_ISREG(st.st_mode):
                    why = "%s is %s, not a file" % (final["path"], kind_of(st.st_mode))
                elif st.st_nlink != 1:
                    why = "%s has another name (a hard link to a file elsewhere)" % final["path"]
                else:
                    raw, keep = b"", True
                    while len(raw) <= MAX_REPORT:
                        chunk = os.read(fd, MAX_REPORT + 1 - len(raw))
                        if not chunk:
                            break
                        raw += chunk
                    try:
                        text = raw.decode("utf-8")
                    except UnicodeDecodeError:
                        text = None
                    if len(raw) > MAX_REPORT:
                        why = "%s is over %d bytes" % (final["path"], MAX_REPORT)
                    elif text is None or "\0" in text:
                        why = "%s is not text" % final["path"]
                    elif not text.strip():
                        state, why, keep = "empty", "the runtime's last message in %s is empty" % final["path"], False
                    else:
                        state, data, keep = "ok", (raw if raw.endswith(b"\n") else raw + b"\n"), False
            finally:
                os.close(fd)
        try:
            st = os.lstat(FINAL_NAME, dir_fd=sfd)
            if not keep and not stat.S_ISDIR(st.st_mode):
                os.unlink(FINAL_NAME, dir_fd=sfd)            # a name only: what a link or a second name points to is untouched
        except OSError:
            pass
    finally:
        os.close(sfd)
    try:
        rfd = os.open(run, O_DIR)
        try:
            os.rmdir(final["dir"], dir_fd=rfd)
        finally:
            os.close(rfd)
    except OSError:
        pass
    return state, data, why, (final["path"] if keep else None)


def publish(ofd, name, data):
    """Write data as OUT/name: a new file (mode 644) renamed over the name, so a link, a pipe or a second name there is replaced, never written
    through or waited on. None, or why it was not published (the new file is removed then)."""
    tmp = ".%s.%s" % (name, secrets.token_hex(6))
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644, dir_fd=ofd)
    except OSError as e:
        return e.strerror or str(e)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), 0o644)
            f.write(data)
        os.rename(tmp, name, src_dir_fd=ofd, dst_dir_fd=ofd)
    except OSError as e:
        try:
            os.unlink(tmp, dir_fd=ofd)
        except OSError:
            pass
        return e.strerror or str(e)
    return None


def drop_previous(ofd, name):
    """Remove name.previous now that this run published name (a link or a file: the name only; a directory is left)."""
    try:
        if not stat.S_ISDIR(os.lstat(name + PREVIOUS, dir_fd=ofd).st_mode):
            os.unlink(name + PREVIOUS, dir_fd=ofd)
    except OSError:
        pass


def finish_report(run, out, final, previous):
    """Take the member's last message from its private file and publish it as OUT/report.md; (the record of what became of it and of the report of
    an earlier run (previous: one was set aside), for dispatch.json and the output; the bytes published, or None)."""
    state, data, why, kept = take_final(run, final)
    rec = {"final_message": final["path"], "report": None, "bytes": None, "state": state, "why": why, "kept": kept}
    if state == "ok":
        ofd = sub_fd(run, "out")
        try:
            bad = publish(ofd, REPORT, data)
            if bad is None:
                drop_previous(ofd, REPORT)
        finally:
            os.close(ofd)
        if bad is None:
            rec.update(state="published", report=os.path.join(out, REPORT), bytes=len(data))
        else:
            rec.update(state="refused", why="it could not be published as %s: %s" % (os.path.join(out, REPORT), bad))
    published = rec["state"] == "published"
    rec["previous"] = "none" if not previous else "replaced" if published else "kept"
    return rec, (data if published else None)


def report_lines(rec, out):
    lines = []
    if rec["state"] == "published":
        lines.append("REPORT=%s (%d bytes: the member's last message)" % (rec["report"], rec["bytes"]))
    else:
        lines.append("REPORT=none: %s%s" % (rec["why"], "; the file is kept for you to read" if rec["kept"] else ""))
    if rec["previous"] == "replaced":
        lines.append("PREVIOUS_REPORT=replaced: the report of the earlier run is replaced by this run's")
    elif rec["previous"] == "kept":
        lines.append("PREVIOUS_REPORT=kept as %s: this run published no report, so the earlier one is not taken for this run's" % os.path.join(out, REPORT + PREVIOUS))
    return lines


def out_has_patches(out):
    """Does OUT hold a patch or a bundle (*.patch or run.bundle in OUT or a directory directly in it, as local verify looks)? No link is followed."""
    def names(d):
        try:
            with os.scandir(d) as it:
                return [(e.name, e.path, e.is_dir(follow_symlinks=False)) for e in it]
        except OSError:
            return []
    for name, path, isdir in names(out):
        if name.endswith(".patch") or name == "run.bundle":
            return True
        if isdir and any(n.endswith(".patch") or n == "run.bundle" for n, _, _ in names(path)):
            return True
    return False


WORKTREE_TIMEOUT = 60


def worktree_changes(clone):
    """None (it cannot be told), or (tracked, untracked): the paths of the clone with uncommitted changes to tracked files (staged or not, deleted
    included) and the untracked files git does not ignore. The clone is a member's to write, its .git included: git runs on it with no system or
    global configuration, the work tree named outright (not the clone's core.worktree), no fsmonitor and every filter driver the clone's
    configuration names emptied, so nothing the member put in its configuration runs; it reads and writes nothing else (no optional locks)."""
    if not os.path.isdir(clone) or os.path.islink(clone) or os.path.islink(os.path.join(clone, ".git")) or not os.path.isdir(os.path.join(clone, ".git")):
        return None
    env = {"PATH": clean_path(), "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_ATTR_NOSYSTEM": "1",
           "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "GIT_DIR": os.path.join(clone, ".git"), "GIT_WORK_TREE": clone}
    def git(args):
        return subprocess.run(["git"] + args, cwd=clone, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                              timeout=WORKTREE_TIMEOUT, check=False)
    try:
        cf = git(["config", "-z", "--name-only", "--get-regexp", r"^filter\."])
        off = ["-c", "core.fsmonitor=false", "-c", "core.untrackedCache=false", "-c", "core.hooksPath=/dev/null"]
        for name in sorted({k.decode("utf-8", "replace")[len("filter."):].rpartition(".")[0] for k in cf.stdout.split(b"\0") if k.startswith(b"filter.")}):
            if not name or "=" in name:
                return None                                  # a driver that cannot be emptied on the command line: git is not run over it
            off += [a for k in ("clean", "smudge", "process") for a in ("-c", "filter.%s.%s=" % (name, k))] + ["-c", "filter.%s.required=false" % name]
        st = git(off + ["status", "--porcelain=v1", "-z", "--no-renames", "--ignore-submodules=all", "--untracked-files=all"])
    except (OSError, subprocess.SubprocessError):
        return None
    if st.returncode != 0:
        return None
    tracked, untracked = [], []
    for ent in st.stdout.split(b"\0"):
        if len(ent) > 3:
            (untracked if ent[:2] == b"??" else tracked).append(ent[3:].decode("utf-8", "replace"))
    return tracked, untracked


def worktree_line(work, run):
    clone = os.path.join(run, "clone")
    if work["refused"]:
        return ("WORKTREE=uncommitted: %s holds %d changed tracked file(s)%s and OUT holds no patches: the member did not commit and collect, so the run is a "
                "refusal, not a finished task (read its report and send it back; to keep the change, copy the changed files out of the clone: never run git "
                "in a write member's clone, whose .git it could set to run a program as you)"
                % (clone, work["tracked"], " and %d untracked file(s)" % work["untracked"] if work["untracked"] else ""))
    return ("WORKTREE=untracked: %s holds %d untracked file(s) no commit has and OUT holds no patches: new files never added are reported, not a "
            "refusal (the refusal covers changes to tracked files), and they are lost with the clone when the run is cleaned (qargi local clean warns): "
            "if they are the task's work, send the run back to commit and collect them" % (clone, work["untracked"]))


# ---- what git in the clone would run (the clone's .git) --------------------------------------------------------------------------------

GIT_WATCHED = ("hooks", "info")   # beside config: the directories of a clone's .git whose files git runs (hooks) or reads as rules (info/attributes)
GIT_CONFIG_SAFE = re.compile(r"branch\..+\.(remote|merge|rebase|description)\Z", re.S)   # what git branch and git checkout -b set: no program
GIT_ENTRIES_MAX = 4096
GIT_CONFIG_MAX = 1 << 20
GIT_NAMED_MAX = 20


def git_watch(argv_t, extra_t, cls, argv, clone):
    """Why the clone's .git of this run is compared before and after (git_state), or None: "granted" when the run's argv names the clone's .git or a
    path in it (a sandbox told to let the member write it, as the write class of codex does), "unsandboxed" when the definition gives the run's class
    no arguments of its own (no class_argv and no {"class": CLASS} group), so nothing of the runtime holds the member's writes. A class with sandbox
    arguments that do not name the .git is not compared: its sandbox is what keeps the .git as it was."""
    gd = os.path.join(clone, ".git")
    if any(a == gd or a.startswith(gd + os.sep) or a.endswith("=" + gd) or ("=" + gd + os.sep) in a for a in argv):
        return "granted"
    def has_group(items):
        return any(isinstance(it, dict) and ((it.get("class") == cls and it.get("then")) or ("if" in it and has_group(it.get("then") or [])))
                   for it in items)
    return None if extra_t or has_group(argv_t) else "unsandboxed"


def _git_sig(path):
    st = os.lstat(path)
    fmt = stat.S_IFMT(st.st_mode)
    if stat.S_ISLNK(st.st_mode):
        return (fmt, os.readlink(path))
    if stat.S_ISDIR(st.st_mode):
        return (fmt, stat.S_IMODE(st.st_mode), st.st_ino)
    return (fmt, stat.S_IMODE(st.st_mode), st.st_size, st.st_ino, st.st_mtime_ns, st.st_ctime_ns)


def git_state(clone):
    """What git in the clone reads that can make it run a program, read by the lead without following a link and without running git there: the bytes
    of .git/config (None when there is none, a text when it is not a regular file or too big), and each entry under .git/hooks and .git/info by its type,
    mode, size, inode and times (a change of a file's content changes its ctime, which no one sets by hand). None when it cannot be read at all."""
    gd = os.path.join(clone, ".git")
    try:
        fd = os.open(os.path.join(gd, "config"), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except FileNotFoundError:
        config = None
    except OSError as e:
        config = "not a file it can read (%s)" % (e.strerror or e)
    else:
        try:
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                config = "not a regular file"
            else:
                with os.fdopen(fd, "rb", closefd=False) as f:
                    config = f.read(GIT_CONFIG_MAX + 1)
                if len(config) > GIT_CONFIG_MAX:
                    config = "larger than %d bytes" % GIT_CONFIG_MAX
        finally:
            os.close(fd)
    tree = {}
    try:
        for top in GIT_WATCHED:
            p = os.path.join(gd, top)
            if not os.path.lexists(p):
                continue
            tree[top] = _git_sig(p)
            if not stat.S_ISDIR(tree[top][0]):
                continue
            for root, dirs, files in os.walk(p):         # a link is an entry, never followed
                for n in sorted(dirs + files):
                    if len(tree) >= GIT_ENTRIES_MAX:
                        tree["..."] = "more than %d entries" % GIT_ENTRIES_MAX
                        return {"config": config, "tree": tree}
                    q = os.path.join(root, n)
                    try:
                        tree[os.path.relpath(q, gd)] = _git_sig(q)
                    except OSError:
                        tree[os.path.relpath(q, gd)] = "unreadable"
    except OSError:
        return None
    return {"config": config, "tree": tree}


def config_entries(data):
    """{key: [values]} of a git configuration file's bytes, read by git from a private copy (no include followed, no system, global or repository
    configuration, nothing run), or None when git cannot read it."""
    import tempfile
    d = tempfile.mkdtemp(prefix="qargi-gitcfg.")
    try:
        p = os.path.join(d, "config")
        with open(p, "wb") as f:
            f.write(data)
        env = {"PATH": clean_path(), "HOME": "/nonexistent", "LC_ALL": "C", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0"}
        r = subprocess.run(["git", "config", "--file", p, "--no-includes", "--list", "-z"], cwd=d, env=env, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=WORKTREE_TIMEOUT, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    finally:
        shutil.rmtree(d, ignore_errors=True)
    if r.returncode != 0:
        return None
    out = {}
    for ent in r.stdout.split(b"\0"):
        if ent:
            k, _, v = ent.decode("utf-8", "replace").partition("\n")
            out.setdefault(k, []).append(v)
    return out


def git_changes(before, after):
    """What changed between two git_states, as short texts naming a configuration key or an entry (never a value); [] when nothing did that could
    make git run something. A key git branch or git checkout -b sets (GIT_CONFIG_SAFE) is no change."""
    if before is None or after is None:
        return ["the clone's .git could not be read"]
    out = []
    a, b = before["config"], after["config"]
    if a != b:
        if isinstance(a, bytes) and isinstance(b, bytes):
            ea, eb = config_entries(a), config_entries(b)
            if ea is None or eb is None:
                out.append("config (git cannot read it)")
            else:
                keys = sorted(k for k in set(ea) | set(eb) if ea.get(k) != eb.get(k) and not GIT_CONFIG_SAFE.match(k))
                out += ["config %s" % k for k in keys]
        else:
            out.append("config (%s)" % (b if isinstance(b, str) else "removed" if b is None else "added" if a is None else "replaced"))
    ta, tb = before["tree"], after["tree"]
    for name in sorted(set(ta) | set(tb)):
        if ta.get(name) != tb.get(name):
            out.append("%s (%s)" % (name, "added" if name not in ta else "removed" if name not in tb else "changed"))
    if len(out) > GIT_NAMED_MAX:
        out = out[:GIT_NAMED_MAX] + ["and %d more" % (len(out) - GIT_NAMED_MAX)]
    return out


def gitdir_line(changed, run):
    return ("GITDIR=changed: the member changed what git reads in %s: %s. Never run git in this clone: a hook, core.fsmonitor, an alias or a filter "
            "driver set there runs as you. Take the work from the patches in OUT, copy files out, or make a clean copy first with git clone --no-local "
            "(as git(1) advises under SECURITY); qargi restores nothing" % (os.path.join(run, "clone", ".git"), "; ".join(changed)))


BLOCKED_FIRST = re.compile(r"[#*_>`\s]*(?:(?i:status)[*_`]*\s*:[#*_>`\s]*)?BLOCKED(?![A-Za-z0-9])")


def report_blocked(text):
    """Does a report say BLOCKED on its first line that is not blank: BLOCKED, or Status: BLOCKED, after any Markdown marks (a heading #, a quote >,
    emphasis * or _, code `), as **BLOCKED**, # BLOCKED, > BLOCKED or **Status:** BLOCKED? The word is the contract's, in capitals."""
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return BLOCKED_FIRST.match(first) is not None


def package(run, out, plan, report, text, outcome, code, started, seconds, previous):
    """The lead's OUT/manifest.json for a read-only run whose report is the runtime's last message: the minimal report-only format of `review save`,
    with what the lead recorded of the run. It is written only for a run the lead's registry names, whose outcome is ok, whose report was published
    and whose OUT holds no patch; it claims no test and no verdict (review check reads the verdict in the report). The record for dispatch.json."""
    pk = plan["package"]
    rec = {"manifest": None, "state": "none", "why": None}
    if not pk["registered"]:
        rec["why"] = "the lead's registry names no run %s, so nothing vouches for what a manifest would say" % run
    elif out_has_patches(out):
        rec["why"] = "OUT holds patches: a read-only run's product is a report, never patches (qargi local verify refuses the run)"
    elif outcome != "ok":
        rec["why"] = "the run's outcome is %s" % outcome
    elif report["state"] != "published":
        rec["why"] = "no report was published"
    else:
        blocked = report_blocked(text.decode("utf-8"))                                            # the report as it was published
        man = {"status": "BLOCKED" if blocked else "DONE", "blocked_reason": "the member's report begins with BLOCKED" if blocked else "",
               "task": "read-only run %s %s: the report is the member's last message, packaged by the lead (qargi local run)" % (pk["role"], pk["slug"]),
               "base": {"branch": pk["base"], "sha": pk["base_sha"]}, "branch": "", "scope": [],
               "done": {"command": "", "exit_code": None, "output_tail": ""}, "gates": [], "commits": [], "touched_paths": [],
               "artifacts": [{"path": REPORT, "kind": "report"}],
               "run": {"id": os.path.basename(run), "role": pk["role"], "runtime": plan["runtime"], "class": plan["class"], "model": plan["model"],
                       "effort": pk["effort"], "effort_native": plan["effort_native"], "started": PE.now(started), "seconds": seconds, "exit": code,
                       "outcome": outcome, "packaged_by": "qargi local run"}}
        ofd = sub_fd(run, "out")
        try:
            bad = publish(ofd, MANIFEST, (json.dumps(man, indent=2) + "\n").encode("utf-8"))
            if bad is None:
                drop_previous(ofd, MANIFEST)
        finally:
            os.close(ofd)
        if bad is None:
            rec.update(state="written", manifest=os.path.join(out, MANIFEST), status=man["status"])
        else:
            rec["why"] = "it could not be written as %s: %s" % (os.path.join(out, MANIFEST), bad)
    rec["previous"] = "none" if not previous else "replaced" if rec["state"] == "written" else "kept"
    return rec


def manifest_lines(rec, out):
    lines = []
    if rec["state"] == "written":
        lines.append("MANIFEST=%s (written by the lead: status %s, commits [], the report in artifacts; no test and no verdict)" % (rec["manifest"], rec["status"]))
    else:
        lines.append("MANIFEST=none: %s" % rec["why"])
    if rec["previous"] == "replaced":
        lines.append("PREVIOUS_MANIFEST=replaced: the manifest of the earlier run is replaced by this run's")
    elif rec["previous"] == "kept":
        lines.append("PREVIOUS_MANIFEST=kept as %s: this run wrote none, so the earlier one is not taken for this run's" % os.path.join(out, MANIFEST + PREVIOUS))
    return lines


def run_it(plan, run):
    out = os.path.join(run, "out")
    if os.path.islink(out) or (os.path.exists(out) and not os.path.isdir(out)):
        fail("%s is not a plain directory of the run; the transcript goes there and nowhere else" % out)
    os.makedirs(out, exist_ok=True)
    if os.path.realpath(out) != os.path.join(os.path.realpath(run), "out"):
        fail("%s is not inside the run" % out)
    dispatch = os.path.join(run, "dispatch.json")
    check_own(dispatch, "the dispatch record")
    fin, pk = plan["final"], plan["package"]
    if fin:                                              # a report.md the lead would not set aside refuses the run before anything is made
        check_own(os.path.join(out, REPORT), "the report of an earlier run")
    if pk:                                               # and so does a manifest.json of a read-only run, whose manifest is the lead's
        check_own(os.path.join(out, MANIFEST), "the manifest of an earlier run")
    write_prompt(run, plan["prompt_file"], plan["prompt"])
    clear_stale_finals(run)
    argv = [plan["exe"]] + plan["argv"][1:]
    home = plan["home"]
    head = {"runtime": plan["runtime"], "class": plan["class"], "argv": plan["argv"], "command_from": plan["exe_from"], "cwd": plan["cwd"],
            "command": plan["exe"] if plan["exe_from"] == "on PATH" else None,
            "model": plan["model"], "effort_native": plan["effort_native"], "prompt_via": plan["via"], "timeout_s": plan["timeout_s"]}
    started = time.time()
    # the start record: an earlier run's outcome never stays, and a runner killed with SIGKILL leaves "running" with its process and the member's, and
    # the links the run home will hold (qargi local list and verify name the ones left)
    begun = dict(head, started=PE.now(started), outcome="running", runner=os.getpid(), member=None)
    if home:
        begun["home"] = {"env": home["env"], "dir": home["dir"], "links": [to for to, _ in home["links"]]}
    write_private(dispatch, json.dumps(begun, indent=2, sort_keys=True) + "\n")
    sig = Signals()
    sig.install()
    made, home_left, staged = [], [], False
    git0 = git_state(os.path.join(run, "clone")) if plan["git_watch"] else None   # before the member starts: what git in the clone would run
    proc = code = error = outcome = left = None
    timed_out, stop_code = False, 2
    previous = prev_manifest = False
    try:
        try:
            if home:
                made = make_home(run, home)              # the links exist for the length of the run only
            sig.check()
            if plan["run_config"]:
                put_run_config(run, plan["run_config"], home)
            sin = open(plan["prompt_file"], "rb") if plan["via"] == "stdin" else subprocess.DEVNULL
            try:
                with os.fdopen(open_own(os.path.join(out, "transcript"), "the transcript"), "wb") as so, \
                        os.fdopen(open_own(os.path.join(out, "transcript.err"), "the error transcript"), "wb") as se:
                    if fin:                              # the last moment before the member starts: nothing of an earlier run is left as this run's
                        ofd = sub_fd(run, "out")
                        try:
                            previous = set_aside(ofd, REPORT)
                            prev_manifest = set_aside(ofd, MANIFEST) if pk else False
                        finally:
                            os.close(ofd)
                        make_final(run, fin)
                        staged = True
                    sig.check()
                    try:
                        proc = subprocess.Popen(argv, cwd=plan["cwd"], env=plan["env"], stdin=sin, stdout=so, stderr=se, shell=False, start_new_session=True)
                    except OSError as e:
                        outcome, error = "transport", "could not start %s: %s" % (plan["argv"][0], e.strerror or e)
                    if proc is not None:
                        write_private(dispatch, json.dumps(dict(begun, member=proc.pid), indent=2, sort_keys=True) + "\n")
                        try:
                            sig.armed = True             # from here a signal stops the member where the lead waits for it
                            sig.check()
                            code = proc.wait(timeout=plan["timeout_s"])
                            sig.armed = False
                            if group_left(proc.pid):
                                left = kill_group(proc)
                        except subprocess.TimeoutExpired:
                            sig.armed = False
                            timed_out = True
                            left = kill_group(proc)
                            code = proc.returncode
                        finally:
                            sig.armed = False
            finally:
                if sin is not subprocess.DEVNULL:
                    sin.close()
        except Interrupted:
            sig.armed = False
            outcome = "interrupted"
            if proc is not None:
                left = kill_group(proc)
                code = proc.returncode
        except Stop as e:                                # the run home, the configuration file, the transcripts or the report could not be made as the run needs
            outcome, error, stop_code = "refused", str(e), e.code
            if proc is not None:                         # the start record could not be rewritten once the member had started: it is stopped, never
                left = kill_group(proc)                  # left running after the runner has gone
                code = proc.returncode
    finally:
        sig.armed = False
        home_left = clear_home(run, home, made) if home else []
    if outcome is None:
        outcome = "failed" if timed_out else plan["exit"].get(str(code), plan["exit"].get("*", "failed"))
        if left and outcome == "ok":
            outcome = "failed"
    seconds = round(time.time() - started, 1)
    gitdir = None
    if plan["git_watch"] and proc is not None:
        gitdir = {"watched": plan["git_watch"], "changed": git_changes(git0, git_state(os.path.join(run, "clone")))}
    work = None
    if plan["class"] == "write" and outcome == "ok" and not out_has_patches(out):
        ch = worktree_changes(os.path.join(run, "clone"))
        if ch is not None and (ch[0] or ch[1]):
            work = {"tracked": len(ch[0]), "untracked": len(ch[1]), "patches": False, "refused": bool(ch[0])}
            if ch[0]:                                    # a change to a tracked file left uncommitted with nothing collected is a refusal, never a
                outcome = "refused"                      # finished task; new files never added (untracked) are only reported
    if staged:
        report, text = finish_report(run, out, fin, previous)
    elif fin:                                            # the member was never started: nothing of it to publish, an earlier report stays set aside
        report, text = {"final_message": fin["path"], "report": None, "bytes": None, "state": "none", "kept": None, "previous": "kept" if previous else "none",
                        "why": "the member was not started"}, None
    else:
        report, text = None, None
    manifest = package(run, out, plan, report, text, outcome, code, started, seconds, prev_manifest) if pk else None
    rec = dict(head, started=PE.now(started), seconds=seconds, exit=code, timed_out=timed_out, outcome=outcome, transcript=os.path.join(out, "transcript"))
    if outcome == "interrupted":
        rec["signal"] = signal.Signals(sig.sig).name
    if left is not None:                                 # the member's process group was stopped: how many of its processes are still alive
        rec["group_left"] = left
    if error:
        rec["error"] = error
    if home:
        rec["home"] = {"env": home["env"], "dir": home["dir"], "links": made, "not_linked": home["missing"], "left": home_left,
                       "residue": home["residue"]}     # names in the run home, never a value
    if plan["usage"] and proc is not None:
        rec["usage"] = read_usage(rec["transcript"], plan["usage"])
    rc = plan["run_config"]
    if rc:                                                 # names only, never the file
        rec["run_config"] = {"file": rc["path"] if rc["data"] is not None else None, "role": rc["role"], "tools": rc["tools"]}
        if rc["baseline"]:
            rec["run_config"]["baseline"] = rc["baseline"]
    if report:
        rec["report"] = report
    if manifest:
        rec["manifest"] = manifest
    if work:
        rec["worktree"] = work
    if gitdir:
        rec["git_dir"] = gitdir
    write_private(dispatch, json.dumps(rec, indent=2, sort_keys=True) + "\n")
    if error:
        print("qargi: %s" % error, file=sys.stderr)
    print("RUNTIME=" + plan["runtime"])
    print("OUTCOME=" + outcome + (" (timed out after %ds%s)" % (plan["timeout_s"], "; " + stopped_text(left) if left else "") if timed_out else "")
          + (" (%s: %s)" % (rec["signal"], stopped_text(left) if proc is not None else "the member was not started")
             if outcome == "interrupted" else "")
          + (" (the runtime ended ok, but the clone holds uncommitted changes and OUT holds no patches)" if work and work["refused"] else ""))
    print("EXIT=%s" % ("" if code is None else code))
    print("TRANSCRIPT=" + rec["transcript"])
    if work:
        print(worktree_line(work, run))
    if gitdir and gitdir["changed"]:
        print(gitdir_line(gitdir["changed"], run))
    if report:
        for line in report_lines(report, out):
            print(line)
    if manifest:
        for line in manifest_lines(manifest, out):
            print(line)
    if "usage" in rec:
        print(usage_line(rec["usage"]))
    for n in (home["residue"] if home else []):
        print("HOME_RESIDUE=%s (the runtime replaced the link with a file of its own; qargi did not write it to your file: compare it with yours and "
              "reconcile it yourself)" % os.path.join(home["path"], n))
    for n in home_left:
        print("qargi: note: " + n, file=sys.stderr)
    if left:
        print("qargi: note: %d process%s of the member's process group %d survived TERM and KILL and may still be running: look at it with ps -g %d"
              % (left, "" if left == 1 else "es", proc.pid, proc.pid), file=sys.stderr)
    if sig.sig is not None and outcome != "interrupted":
        print("qargi: note: %s arrived after the member had ended; the run was finished first" % signal.Signals(sig.sig).name, file=sys.stderr)
    sig.restore()
    print("next: read the transcript and OUT, then qargi local verify " + run)
    if outcome == "interrupted":
        return 128 + sig.sig
    if error and outcome == "refused":
        return stop_code
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
        if not o["dry"]:
            earlier_start(run, o["again"])
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
