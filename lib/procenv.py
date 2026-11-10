#!/usr/bin/env python3
"""The small helpers that several qargi modules need to start a child process or write a line of the record, in one place.

A library; it does nothing when run. Modules import it by its sibling name once lib/ is on sys.path (every module that does puts its own
directory there first, so it works as a script and as a module):

  clean_path()          the caller's PATH with empty and relative entries dropped (a command is never looked up in the working directory);
                        DEFAULT_PATH when nothing is left
  pass_env(names)       {name: value} of the names that are set and not empty in the caller's environment
  now(t=None)           the time stamp of the record, UTC, `2026-01-02T03:04:05Z`, of the epoch seconds t or of now
  plan_token(*parts)    the token of a plan: the first 12 hex digits of the sha256 of the parts joined by newlines
  audit(verb, detail, ...)  one line in STATE/audit.log: ts, verb, detail, asked, approved, nested (and origin when given)
  die(msg, code=1)      `qargi: MSG` on standard error and the exit status code
  git(*args, repo=, cwd=, git_dir=, config=, timeout=, env=)
                        (exit, stdout, stderr) of a git command with no prompt, no optional lock and no fsmonitor; the exit is None when git did not run
  child_env(keep=())    the base environment of a child: PATH (clean_path), LANG and LC_ALL C.UTF-8, TERM dumb, GIT_TERMINAL_PROMPT 0, and
                        HOME, USER, LOGNAME, TMPDIR and the names in keep when the caller has them
"""
import hashlib
import json
import os
import subprocess
import sys
import time

DEFAULT_PATH = "/usr/local/bin:/usr/bin:/bin"
BASE_KEEP = ("HOME", "USER", "LOGNAME", "TMPDIR")


def clean_path():
    """The caller's PATH without empty and relative entries: a command is never looked up in the working directory."""
    parts = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p.startswith("/")]
    return os.pathsep.join(parts) or DEFAULT_PATH


def pass_env(names):
    """{name: value} for each of names that the caller's environment sets to a non-empty value."""
    return {k: os.environ[k] for k in names if os.environ.get(k)}


def child_env(keep=()):
    """The base environment of a child process: a clean PATH, a fixed locale and terminal, no git prompt, and only the names listed above
    (and in keep) from the caller's environment."""
    env = {"PATH": clean_path(), "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "TERM": "dumb", "GIT_TERMINAL_PROMPT": "0"}
    env.update(pass_env(BASE_KEEP + tuple(keep)))
    return env


def now(t=None):
    """The time stamp qargi writes in its records: UTC, to the second, `2026-01-02T03:04:05Z`; of the epoch seconds t, else of now."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def plan_token(*parts):
    """The token that names a plan: the first 12 hex digits of the sha256 of the parts (text) joined by newlines."""
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def audit(verb, detail, *, asked="", approved="", origin=None, ts=None, state=None):
    """Append one line to audit.log in the state directory (state, else the one qargi uses; mode 600; the directory is made when it is not
    there): {"ts", "verb", "detail", "asked", "approved", "nested": false} and, for a line written by the supervisor, "origin". One write, so
    lines of two processes do not mix."""
    if state is None:
        import paths
        state = paths.state()
    line = {"ts": ts or now(), "verb": verb, "detail": detail, "asked": asked, "approved": approved, "nested": False}
    if origin:
        line["origin"] = origin
    os.makedirs(state, exist_ok=True)
    f = os.path.join(state, "audit.log")
    fd = os.open(f, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(line) + "\n").encode())
    finally:
        os.close(fd)
    try:
        os.chmod(f, 0o600)
    except OSError:
        pass


def die(msg, code=1):
    """Say `qargi: MSG` on standard error and leave with the exit status code."""
    print("qargi: " + msg, file=sys.stderr)
    raise SystemExit(code)


def git(*args, repo=None, cwd=None, git_dir=None, config=(), timeout=30, env=None):
    """(exit, stdout, stderr) of `git ARGS`, the output as git wrote it: standard input closed, no prompt (child_env), no optional lock, no
    fsmonitor; repo is `-C repo`, git_dir is `--git-dir`, config a list of `key=value` for `-c`, env replaces the environment. A git that
    cannot be run or is too slow is (None, "", the reason)."""
    cmd = ["git", "-c", "core.fsmonitor=false"]
    for c in config:
        cmd += ["-c", c]
    if repo:
        cmd += ["-C", repo]
    if git_dir:
        cmd += ["--git-dir", git_dir]
    try:
        r = subprocess.run(cmd + list(args), cwd=cwd, capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=timeout,
                           env=env if env is not None else dict(child_env(), GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError) as e:
        return None, "", str(e)
    return r.returncode, r.stdout, r.stderr
