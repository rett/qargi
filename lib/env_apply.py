#!/usr/bin/env python3
"""qargi env plan and qargi env apply: look at, then run, a project's bootstrap. The lead's verbs; the member guard refuses both.
A library for lib/env.py, which hands the verbs to this module. It does nothing when run.

  plan   run the dry-run command (make -n bootstrap, ...), show its output, print a plan token
  apply  with that token and your words, run the bootstrap command once

A dry run is not harmless. `make -n` still expands $(shell ...) and runs recipe lines marked + or holding $(MAKE), and the dry-run
forms of the other runners evaluate project code in the same way. So the plan runs project code too, and is refused unless
--approve-exec names the dry-run command's executable. Read the project's files first; qargi cannot judge them.

Both commands run as an argument vector, never through a shell, in the repository, with standard input from /dev/null (plan) and a
minimal environment: PATH (absolute entries only), HOME, USER, LOGNAME, LANG, LC_ALL, LC_CTYPE, TERM, TZ and TMPDIR, nothing else (no token,
no ssh agent, no MAKEFLAGS). The dry run has a time limit (QARGI_ENV_TIMEOUT seconds, default 120) and its output is capped at 1 MB.

The plan token is a hash over the dry-run output, the dry-run and bootstrap commands, the repository and its HEAD, and the host name.
Apply runs the dry run again and refuses when the token is no longer the plan's. The lines and the executables the plan lists are read
from the text of the output (best effort): a recipe can run more than its dry run shows, and a script it calls can call sudo.

The tools the roles declare (roles.<role>.tools, lib/tools.py) are part of the plan: each go tool and binary is listed with its state here
(ok, missing, wrong, or installed in a directory PATH lacks), the submodules with theirs (qargi local prepare checks those out in a member's
clone; apply does nothing with them), and the token covers the list. After a bootstrap that exits 0, apply installs what is missing or wrong:
`go install NAME@VERSION` for a go tool (go must then be named in --approve-exec), and for a binary the file at its URL, downloaded to a
temporary name, kept only when its sha256 is the declared one, made executable and moved to ~/.local/bin/NAME. A tool that fails leaves the
others alone and the verb exits 1 after naming it.

Apply needs --plan, --approved, and --approve-exec naming the executables of the dry-run and the bootstrap commands (it may also name
others the plan listed; a name that is none of them is refused). It refuses privileged lines (sudo, doas, pkexec, su, run0 in a command of
the line) without --allow-root. The bootstrap command runs once with standard input, output and error inherited, so sudo can ask on your terminal;
no password is read or kept. Apply leaves two lines in the audit log (start and result) and the record `env/NAME.json` in the state
directory (mode 600). QARGI_DRY_RUN stops it before the bootstrap runs.
"""
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import env as E  # noqa: E402
import paths as P  # noqa: E402
import procenv as PE  # noqa: E402
import tools as T  # noqa: E402

CAP = 1024 * 1024
TIMEOUT = 120
KEEP = ("HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "TZ", "TMPDIR")
PRIVILEGED = ("sudo", "doas", "pkexec", "su", "run0")
WRAPPERS = ("sudo", "doas", "pkexec", "run0", "env", "command", "nohup", "time", "exec", "nice", "ionice", "setsid", "timeout")
SHELLS = ("sh", "bash", "dash", "zsh", "ksh")
KEYWORDS = ("if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "in", "{", "}", "!", "function", "select")
BUILTINS = ("echo", "printf", "cd", "test", "[", "[[", "export", "set", "unset", "true", "false", ":", "exit", "pwd", "read", "shift", "return",
            "trap", "umask", "wait", "local", "declare", "readonly", "alias", "type", "hash", "ulimit")
SUDO_VALUE_OPTS = ("-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T")
USAGE = {"plan": "usage: qargi env plan [--project P] [--repo DIR] --approve-exec NAME",
         "apply": "usage: qargi env apply [--project P] [--repo DIR] --plan TOKEN --approved WORDS --approve-exec NAMES [--allow-root]"}
OPTS = {"plan": ((("--project", "--repo", "--approve-exec")), ()),
        "apply": ((("--project", "--repo", "--plan", "--approved", "--approve-exec")), ("--allow-root",))}


class Stop(Exception):
    """The verb ends here with this exit status (2: refused or wrong arguments, 1: it could not go on) and this message."""

    def __init__(self, msg, code=1):
        super().__init__(msg)
        self.code = code


def vis(s):
    """s with every character that is not printable written out (\\x1b, \\u202e), so a line from a project cannot hide or reorder what is shown."""
    return "".join(c if c.isprintable() else (c.encode("unicode_escape").decode("ascii") if c != "\t" else "\\t") for c in s)


def library():
    from conformance import library as L          # the existing helpers of the approvals: token_of, exec_names, audit
    return L


def timeout():
    try:
        n = int(os.environ.get("QARGI_ENV_TIMEOUT", ""))
    except ValueError:
        return TIMEOUT
    return n if n > 0 else TIMEOUT


def child_env():
    env = PE.pass_env(KEEP)
    env["PATH"] = PE.clean_path()
    return env


def argv_of(cmd, what):
    """The words of a command line, for running without a shell; a line that needs a shell is refused."""
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        raise Stop("the %s command is not a command line (%s): %s" % (what, e, vis(cmd)), 2)
    bad = [w for w in argv if re.fullmatch(r"[;&|<>()]+", w)]
    if not argv or bad:
        raise Stop("the %s command needs a shell (%s): commands run without one; put it in a script or a target and name that: %s"
                   % (what, bad[0] if bad else "empty", vis(cmd)), 2)
    return argv


def which(argv0, env, repo):
    """The file argv0 names for a command run in repo with env's PATH, else None (a name with a slash is relative to repo)."""
    if "/" in argv0:
        full = argv0 if os.path.isabs(argv0) else os.path.join(repo, argv0)
        return full if os.path.isfile(full) and os.access(full, os.X_OK) else None
    return shutil.which(argv0, path=env["PATH"])


def head_of(repo, env):
    try:
        r = subprocess.run(["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=repo, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "none"
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else "none"


def dry_run(argv, repo, env):
    """(output text, seconds): the dry-run command run in repo, stdin from /dev/null, standard error folded into the output. A non-zero
    exit status, a time out and an output over the cap are Stops."""
    t0, limit = time.time(), timeout()
    with tempfile.TemporaryFile() as out:
        try:
            p = subprocess.Popen(argv, cwd=repo, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as e:
            raise Stop("could not run %s: %s" % (vis(argv[0]), e.strerror or "error"))
        try:
            rc = p.wait(limit)
        except subprocess.TimeoutExpired:
            os.killpg(p.pid, signal.SIGKILL)
            p.wait()
            raise Stop("the dry run did not finish in %d seconds and was stopped (QARGI_ENV_TIMEOUT changes the limit); no plan" % limit)
        size = out.seek(0, 2)
        if size > CAP:
            raise Stop("the dry run printed more than %d KB; no plan" % (CAP // 1024))
        out.seek(0)
        text = out.read().decode("utf-8", "replace")
    if rc != 0:
        shown = "\n".join("  " + vis(ln) for ln in text.splitlines()[-20:])
        raise Stop("the dry run exited with status %d; no plan%s" % (rc, ("\nits last lines:\n" + shown) if shown else ""))
    return text, time.time() - t0


def words_of(line):
    """The words of one output line with the shell's operators as words of their own; falls back to blanks when a quote is open."""
    lx = shlex.shlex(line, posix=True, punctuation_chars=True)
    lx.whitespace_split = True
    try:
        return list(lx)
    except ValueError:
        return re.findall(r"&&|\|\||[;|&()]|[^\s;|&()]+", line)


def scan(line, depth=0):
    """(names, privileged) for one line of dry-run output: the commands in it, read as text. A command after && || ; | ( ) is a command; a
    redirection's target is not; a wrapper (sudo, env, time ...) is listed and the command it runs too; sh -c STRING is read again."""
    names, priv, seg, skip = [], False, [], False
    toks = words_of(line) + [";"]
    for t in toks:
        if skip:
            skip = False
            continue
        if re.fullmatch(r"[;&|<>()]+", t):
            if "<" in t or ">" in t:
                skip = True
                continue
            n, p = command(seg, depth)
            names, priv, seg = names + n, priv or p, []
            continue
        seg.append(t)
    return names, priv


def command(words, depth):
    names, priv = [], False
    while words and (re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0]) or words[0] in KEYWORDS):
        words = words[1:]
    if words:
        words = [words[0].lstrip("@-+")] + words[1:]
    while words and words[0]:
        name = words[0]
        if name.endswith(":") and not names:
            break                                           # "make: Nothing to be done": a label, not a command
        if name in PRIVILEGED:
            priv = True
        if name not in BUILTINS:
            names.append(name)
        if name in SHELLS and "-c" in words[1:] and depth < 2 and words.index("-c") + 1 < len(words):
            n, p = scan(words[words.index("-c") + 1], depth + 1)
            names, priv = names + n, priv or p
        if name not in WRAPPERS:
            break
        words = words[1:]
        while words and (words[0].startswith("-") or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", words[0])):
            words = words[2:] if name in PRIVILEGED and words[0] in SUDO_VALUE_OPTS else words[1:]
    return names, priv


def analyse(text):
    """{lines: [(number, line, privileged)], executables: sorted names} for a dry-run output."""
    lines, exes = [], set()
    for i, ln in enumerate(text.splitlines(), 1):
        names, priv = scan(ln)
        lines.append((i, ln, priv))
        exes.update(names)
    return {"lines": lines, "executables": sorted(exes)}


def token_of(text, ctx):
    L = library()
    return L.token_of(json.dumps({"dry_run_output": text, "dry_run_command": ctx["dry"], "bootstrap_command": ctx["boot"], "repo": ctx["repo"],
                                  "head": ctx["head"], "host": socket.gethostname(), "tools": ctx["tools"]}, sort_keys=True))


def tool_rows(ctx):
    """[(entry, state, text)] for the tools the roles declare, each looked at here once (go version -m runs for a go tool that is there)."""
    return [(t,) + T.status(t, ctx["repo"]) for t in ctx["tools"]]


def pending(rows):
    """The go tools and binaries apply would install: missing, or there but not what is declared."""
    return [t for t, state, _ in rows if t["kind"] in ("go", "binary") and state in ("missing", "wrong")]


def say_tools(rows):
    if not rows:
        return
    print("\ntools the roles declare (roles.<role>.tools), %d; apply installs the ones that are missing or wrong, after the bootstrap:" % len(rows))
    for t, state, text in rows:
        print("  %-8s%s   [%s]   %s" % (state, T.label(t), ", ".join(t["roles"]), vis(text)))


def parse(verb, argv):
    valued, flags = OPTS[verb]
    opts, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a in valued and i + 1 < len(argv):
            opts[a] = argv[i + 1]
            i += 2
        elif a in flags:
            opts[a] = True
            i += 1
        else:
            raise Stop(USAGE[verb], 2)
    return opts


def context(verb, opts):
    """The project, repository and commands this run is about."""
    try:
        project, answers, repo = E.resolve(opts.get("--project"), opts.get("--repo"))
    except E.Problem as e:
        raise Stop(str(e), 2)
    d = E.effective(repo, answers)
    dry, boot = d["commands"]["dry_run_command"]["command"], d["commands"]["bootstrap_command"]["command"]
    if not dry or not boot:
        raise Stop("%s has no %s: add a bootstrap target (qargi env show) or set env.%s" % (
            repo, "bootstrap target" if not boot else "dry-run command", "bootstrap_command" if not boot else "dry_run_command"), 2)
    env = child_env()
    return {"project": project, "repo": repo, "dry": dry, "boot": boot, "dry_argv": argv_of(dry, "dry-run"), "boot_argv": argv_of(boot, "bootstrap"),
            "env": env, "head": head_of(repo, env), "detected": d, "tools": T.declared(answers)}


def say_command(ctx):
    print("environment of %s (%s)" % (ctx["project"] or "no stored project", ctx["repo"]))
    print("dry run:   %s" % vis(ctx["dry"]))
    print("bootstrap: %s" % vis(ctx["boot"]))


def plan(argv):
    opts = parse("plan", argv)
    ctx = context("plan", opts)
    names = sorted({x.strip() for x in opts.get("--approve-exec", "").split(",") if x.strip()})
    first = ctx["dry_argv"][0]
    if names != [first]:
        say_command(ctx)
        print("\nnothing was run. The plan runs the dry-run command in the repository: without a shell, with standard input from /dev/null, a minimal environment")
        print("(%s), and a limit of %d seconds." % (", ".join(sorted(ctx["env"])), timeout()))
        print("A dry run is not harmless: make -n still expands $(shell ...) and runs the recipe lines marked + or holding $(MAKE), and the dry run of the other")
        print("runners evaluates project code as well. Read the project's files, then run the same command with --approve-exec %s." % first)
        if names:
            raise Stop("--approve-exec names %s; the dry-run command's executable is %s" % (", ".join(names), first), 2)
        raise Stop("env plan needs --approve-exec %s" % first, 2)
    if which(first, ctx["env"], ctx["repo"]) is None:
        raise Stop("%s is not on the PATH of the dry run (absolute entries of PATH: %s)" % (vis(first), ctx["env"]["PATH"]), 2)
    text, secs = dry_run(ctx["dry_argv"], ctx["repo"], ctx["env"])
    a = analyse(text)
    tok = token_of(text, ctx)
    say_command(ctx)
    print("ran the dry run in %.1f s: %d lines of output, HEAD %s" % (secs, len(a["lines"]), ctx["head"][:12]))
    priv = [x for x in a["lines"] if x[2]]
    other = [x for x in a["lines"] if not x[2]]
    print("\nprivileged lines (%d): a command in the line is sudo, doas, pkexec, su or run0; apply needs --allow-root" % len(priv))
    for n, ln, _ in priv:
        print("  %4d: %s" % (n, vis(ln)))
    print("\nother lines (%d):" % len(other))
    for n, ln, _ in other:
        print("  %4d: %s" % (n, vis(ln)))
    print("\nexecutables seen in the lines (best effort, read from the text; a recipe can run more than its dry run shows, and a script it calls can call sudo):")
    for x in a["executables"] or ["none"]:
        print("  " + vis(x))
    for label, argv0 in (("dry run", ctx["dry_argv"][0]), ("bootstrap", ctx["boot_argv"][0])):
        print("%s runs %s -> %s" % (label, vis(argv0), which(argv0, ctx["env"], ctx["repo"]) or "not on the PATH"))
    rows = tool_rows(ctx)
    say_tools(rows)
    need = sorted({ctx["dry_argv"][0], ctx["boot_argv"][0]} | exec_for(pending(rows)))
    print("\nplan token: %s   (apply with: qargi env apply --plan %s --approved \"<the user's go-ahead after reading this plan>\" --approve-exec %s%s)"
          % (tok, tok, ",".join(vis(x) for x in need), " --allow-root" if priv else ""))
    return 0


def exec_for(todo):
    """The executables the tool installs run: go, for a go tool (a binary is downloaded and run by nothing)."""
    return {"go"} if any(t["kind"] == "go" for t in todo) else set()


def install(todo, ctx):
    """Install the pending tools in order; [(entry, exit status, text)]. go is looked up on the PATH of the child environment now, after the bootstrap."""
    out = []
    go = which("go", ctx["env"], ctx["repo"])
    for t in todo:
        if t["kind"] == "go":
            if go is None:
                out.append((t, 1, "go is not on the PATH (absolute entries of PATH: %s); not installed" % ctx["env"]["PATH"]))
                continue
            print("running: go install %s@%s" % (t["name"], t["version"]), flush=True)
            rc, text = T.install_go(t, go, ctx["repo"])
        else:
            print("downloading %s -> %s/%s (checked against its sha256)" % (vis(t["url"]), T.BIN_DIR, t["name"]), flush=True)
            rc, text = T.install_binary(t)
        out.append((t, rc, text))
    return out


def audit(verb, detail, opts):
    library().audit(verb, detail, {"--approved": opts.get("--approved", "")})


def record_name(ctx):
    n = ctx["project"] or re.sub(r"[^A-Za-z0-9._-]", "-", os.path.basename(ctx["repo"]))[:40].lstrip(".-")
    return n or "repository"


def write_record(ctx, entry):
    """env/NAME.json in the state directory (mode 600): the object read again, "apply" set to entry, written through a temporary file."""
    d = os.path.join(P.state(), "env")
    os.makedirs(d, mode=0o700, exist_ok=True)
    f = os.path.join(d, record_name(ctx) + ".json")
    try:
        with open(f) as fh:
            cur = json.load(fh)
    except (OSError, ValueError):
        cur = {}
    cur = cur if isinstance(cur, dict) else {}
    cur["apply"] = entry
    tmp = "%s.%d.tmp" % (f, os.getpid())
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(cur, fh, indent=2, sort_keys=True)
        fh.write("\n")
    os.replace(tmp, f)
    os.chmod(f, 0o600)
    return f


def check_after(ctx):
    """Run `env check` (the project's doctor, so project code, as the bootstrap was) and return its exit status."""
    cmd = [sys.executable, "-I"] + (["-B"] if sys.dont_write_bytecode else []) + [os.path.join(HERE, "env.py"), "check", "--repo", ctx["repo"]] + (["--project", ctx["project"]] if ctx["project"] else [])
    print("running: qargi env check", flush=True)
    return subprocess.run(cmd, cwd=ctx["repo"], env=dict(os.environ)).returncode


def apply(argv):
    opts = parse("apply", argv)
    if not opts.get("--plan") or not opts.get("--approved"):
        raise Stop("env apply needs --plan TOKEN and --approved WORDS from a plan you showed to the person (qargi env plan --approve-exec NAME)\n" + USAGE["apply"], 2)
    ctx = context("apply", opts)
    L = library()
    named = set(L.exec_names(opts))
    rows = tool_rows(ctx)
    todo = pending(rows)
    commands = {ctx["dry_argv"][0], ctx["boot_argv"][0]}
    required = commands | exec_for(todo)
    if required - named:
        raise Stop("--approve-exec must name %s (the dry-run and bootstrap executables%s) and does not name %s; nothing was run"
                   % (", ".join(sorted(required)), ", and go for the go tools of the plan" if "go" in required else "", ", ".join(sorted(required - named))), 2)
    for argv0 in sorted(commands):
        if which(argv0, ctx["env"], ctx["repo"]) is None:
            raise Stop("%s is not on the PATH (absolute entries of PATH: %s); nothing was run" % (vis(argv0), ctx["env"]["PATH"]), 2)
    text, _ = dry_run(ctx["dry_argv"], ctx["repo"], ctx["env"])
    a = analyse(text)
    tok = token_of(text, ctx)
    if opts["--plan"] != tok:
        raise Stop("the plan changed since it was made (the dry-run output, the commands, HEAD or the host differ): run qargi env plan again and show it; nothing was run")
    extra = sorted(named - required - set(a["executables"]))
    if extra:
        raise Stop("--approve-exec names %s, which %s neither the dry-run or bootstrap executable nor one the plan listed; nothing was run"
                   % (", ".join(extra), "is" if len(extra) == 1 else "are"), 2)
    priv = [x for x in a["lines"] if x[2]]
    if priv and not opts.get("--allow-root"):
        raise Stop("the plan has %d privileged line(s) (first: %s) and --allow-root is not given; nothing was run" % (len(priv), vis(priv[0][1])), 2)
    say_command(ctx)
    say_tools(rows)
    if os.environ.get("QARGI_DRY_RUN"):
        print("QARGI_DRY_RUN is set: the plan matches and the bootstrap command would run now%s; it was not run"
              % (", then %d tool install(s)" % len(todo) if todo else ""))
        return 0
    detail = "%s %s token %s head %s" % (record_name(ctx), ctx["boot"], tok, ctx["head"][:12])
    audit("env:apply", detail + (" allow-root" if priv else ""), opts)
    print("running: %s   (in %s, with your terminal)" % (vis(ctx["boot"]), ctx["repo"]), flush=True)
    t0, rc = time.time(), None
    try:
        rc = subprocess.run(ctx["boot_argv"], cwd=ctx["repo"], env=ctx["env"]).returncode
    except KeyboardInterrupt:
        rc = 130
    except OSError as e:
        print("qargi: could not run %s: %s" % (vis(ctx["boot_argv"][0]), e.strerror or "error"), file=sys.stderr)
        rc = 127
    audit("env:apply-result", "%s exit %d" % (detail, rc), opts)
    done = install(todo, ctx) if rc == 0 else []
    failed = [(t, msg) for t, trc, msg in done if trc != 0]
    for t, trc, msg in done:
        print("%s: %s" % (T.label(t), "installed" if trc == 0 else "FAILED"), flush=True)
        for ln in msg.splitlines():
            print("  " + vis(ln))
    f = write_record(ctx, {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seconds": round(time.time() - t0, 1), "exit": rc, "command": ctx["boot"],
                           "dry_run_command": ctx["dry"], "token": tok, "head": ctx["head"], "host": socket.gethostname(), "repo": ctx["repo"],
                           "dry_run_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "allow_root": bool(priv),
                           "tools": [{"kind": t["kind"], "name": t["name"], "version": t.get("version"), "exit": trc} for t, trc, _ in done]})
    print("recorded in %s" % f)
    if rc != 0:
        print("qargi: the bootstrap command exited with status %d%s" % (rc, "; the %d tool install(s) were not run" % len(todo) if todo else ""), file=sys.stderr)
        return 1
    if failed:
        print("qargi: %d tool(s) could not be installed: %s" % (len(failed), ", ".join(T.label(t) for t, _ in failed)), file=sys.stderr)
        return 1
    return check_after(ctx)


def main(verb, argv):
    try:
        return {"plan": plan, "apply": apply}[verb](argv)
    except Stop as e:
        print(str(e) if str(e).startswith("usage") else "qargi: " + str(e), file=sys.stderr)
        return e.code
    except library().Failure as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    print("lib/env_apply.py is the library of qargi env plan and apply; run qargi env", file=sys.stderr)
    sys.exit(2)
