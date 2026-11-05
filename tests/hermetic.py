"""Imported first by every Python test (the tests directory is on sys.path when a test runs as a script).
It makes the test independent of the caller: no ANTHROPIC_* or QARGI_* variable gets through, HOME and qargi's
config and state are fresh temporary directories, and the first `ant` and `claude` on PATH are stubs that
fail, so a test that did not bring its own fake cannot reach the real tools. A test can still build its own
environment from os.environ and override any of it."""
import atexit
import os
import re
import shutil
import tempfile

for _k in [k for k in os.environ if k.startswith(("ANTHROPIC_", "QARGI_"))]:
    del os.environ[_k]
# A TMPDIR that is gone (removed under the test) is not replaced by another directory: tempfile would quietly fall back to /tmp,
# outside the temporary root the caller gave the test. The test does not run (the same rule as tests/hermetic.sh).
if os.environ.get("TMPDIR") and not (os.path.isdir(os.environ["TMPDIR"]) and os.access(os.environ["TMPDIR"], os.W_OK)):
    raise SystemExit("hermetic test: TMPDIR=%s is not a writable directory: the test does not run" % os.environ["TMPDIR"])
ROOT =tempfile.mkdtemp(prefix="hermetic.")
atexit.register(shutil.rmtree, ROOT, True)
for _d in ("home", "bin"):
    os.makedirs(os.path.join(ROOT, _d))
for _t in ("ant", "claude"):
    _p = os.path.join(ROOT, "bin", _t)
    with open(_p, "w") as _f:
        _f.write('#!/bin/sh\necho "hermetic test: the real %s is not available; put a fake first on PATH" >&2\nexit 127\n' % _t)
    os.chmod(_p, 0o755)
os.environ.update(HOME=os.path.join(ROOT, "home"), QARGI_CONF=os.path.join(ROOT, "conf"), QARGI_STATE=os.path.join(ROOT, "state"),
                  XDG_CONFIG_HOME=os.path.join(ROOT, "home", ".config"), XDG_STATE_HOME=os.path.join(ROOT, "home", ".local", "state"),
                  PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ.get("PATH", ""))

# The directories and files a test copies to run a modified copy of the tool: the one list of tests/hermetic.sh (TOOL_DIRS).
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "hermetic.sh")) as _f:
    TOOL_DIRS = tuple(re.search(r'^TOOL_DIRS="([^"]*)"', _f.read(), re.M).group(1).split())
