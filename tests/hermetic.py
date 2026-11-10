"""Imported first by every Python test (the tests directory is on sys.path when a test runs as a script).
It makes the test independent of the caller, with the environment of tests/hermetic.sh (read its header for the reasons): no ANTHROPIC_*
or QARGI_* variable gets through, HOME, TMPDIR and qargi's config and state are fresh directories under one temporary directory (ROOT,
removed at exit; what tempfile makes goes into ROOT/tmp), and the first `ant` and `claude` on PATH are stubs that fail, so a test that
did not bring its own fake cannot reach the real tools. The locale, time zone and umask are fixed, git reads no configuration of the
host or the user and has a default branch name (no identity: a test that commits sets its own), and python writes no bytecode (the first
`python3` on PATH is a wrapper that adds -B, because PYTHONDONTWRITEBYTECODE is ignored under `python3 -I`, which qargi's scripts use). A test can still build its own
environment from os.environ and override any of it."""
import atexit
import os
import re
import shutil
import subprocess
import sys
import tempfile

for _k in [k for k in os.environ if k.startswith(("ANTHROPIC_", "QARGI_"))]:
    del os.environ[_k]
# A TMPDIR that is gone (removed under the test) is not replaced by another directory: tempfile would quietly fall back to /tmp,
# outside the temporary root the caller gave the test. The test does not run (the same rule as tests/hermetic.sh).
if os.environ.get("TMPDIR") and not (os.path.isdir(os.environ["TMPDIR"]) and os.access(os.environ["TMPDIR"], os.W_OK)):
    raise SystemExit("hermetic test: TMPDIR=%s is not a writable directory: the test does not run" % os.environ["TMPDIR"])
ROOT =tempfile.mkdtemp(prefix="hermetic.")
atexit.register(shutil.rmtree, ROOT, True)
for _d in ("home", "bin", "tmp"):
    os.makedirs(os.path.join(ROOT, _d))
for _t in ("ant", "claude"):
    _p = os.path.join(ROOT, "bin", _t)
    with open(_p, "w") as _f:
        _f.write('#!/bin/sh\necho "hermetic test: the real %s is not available; put a fake first on PATH" >&2\nexit 127\n' % _t)
    os.chmod(_p, 0o755)
# the wrapper: the real python3 with -B (`python3 -I` ignores PYTHONDONTWRITEBYTECODE, and every qargi script starts that way)
_py = shutil.which("python3")
if _py:
    with open(os.path.join(ROOT, "bin", "python3"), "w") as _f:
        _f.write("#!/bin/sh\nexec '%s' -B \"$@\"\n" % _py)
    os.chmod(os.path.join(ROOT, "bin", "python3"), 0o755)
os.environ.update(HOME=os.path.join(ROOT, "home"), QARGI_CONF=os.path.join(ROOT, "conf"), QARGI_STATE=os.path.join(ROOT, "state"),
                  XDG_CONFIG_HOME=os.path.join(ROOT, "home", ".config"), XDG_STATE_HOME=os.path.join(ROOT, "home", ".local", "state"),
                  PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ.get("PATH", ""))
# the temporary files of the test and of what it runs go into ROOT: tempfile has cached the caller's directory by now
os.environ["TMPDIR"] = tempfile.tempdir = os.path.join(ROOT, "tmp")
for _k in ("LC_ALL", "LANGUAGE", "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "SSH_AUTH_SOCK", "SSH_ASKPASS", "PYTHONPATH", "PYTHONSTARTUP"):
    os.environ.pop(_k, None)
os.environ.update(LANG="C.UTF-8" if any(l.lower().replace("-", "") == "c.utf8" for l in subprocess.run(
                      ["locale", "-a"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True).stdout.split()) else "C",
                  TZ="UTC", NO_COLOR="1", COLUMNS="80", TERM="dumb", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1",
                  GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1", GIT_TERMINAL_PROMPT="0",
                  GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="init.defaultBranch", GIT_CONFIG_VALUE_0="master")
os.umask(0o022)
sys.dont_write_bytecode = True

# The directories and files a test copies to run a modified copy of the tool: the one list of tests/hermetic.sh (TOOL_DIRS).
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermetic.sh")) as _f:
    TOOL_DIRS = tuple(re.search(r'^TOOL_DIRS="([^"]*)"', _f.read(), re.M).group(1).split())
