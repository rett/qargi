#!/usr/bin/env python3
"""The stub transport of the conformance suite: stands in for the vendor, so an adapter is exercised with no network.

Called by an adapter as $QARGI_TRANSPORT METHOD TARGET [ARG...] (the request body, when there is one, on stdin).
Each provider's tests/providers/NAME/stub starts this file with its own directory as the argument.
  - Every call is appended to $QARGI_STUB_LOG as one JSON line {"argv": [...], "stdin": "..."}.
  - The reply is a fixture of NAME/fixtures/: METHOD_TARGET.json, where the target has every run of characters outside
    [A-Za-z0-9] replaced by one underscore and the ends trimmed (GET /sessions/s1 -> GET_sessions_s1.json), else
    default.json. A fixture is printed as it is, exit 0. With none the stub says so on stderr and exits 4 (a transport
    error).
  - $QARGI_STUB_DELAY (seconds) keeps the stub alive that long, so a `ps`-style capture of the process list sees it.
A call is read-class when its method is one of READ below (compared without regard to case), otherwise it changes
something; the conformance suite holds a provision in plan mode to read-class calls.
Stdlib only; run isolated (python3 -I)."""
import json
import os
import re
import sys
import time

READ = ("GET", "HEAD", "OPTIONS", "LIST", "SHOW", "RETRIEVE", "DESCRIBE", "READ")


def main(argv):
    if not argv:
        print("usage: stub.py PROVIDER_TEST_DIR METHOD TARGET [ARG...]", file=sys.stderr)
        return 2
    base, call = argv[0], argv[1:]
    body = "" if sys.stdin.isatty() else sys.stdin.read()
    log = os.environ.get("QARGI_STUB_LOG")
    if log:
        with open(log, "a") as f:
            f.write(json.dumps({"argv": call, "stdin": body}) + "\n")
    delay = os.environ.get("QARGI_STUB_DELAY")
    if delay:
        time.sleep(float(delay))
    method = call[0] if call else ""
    slug = re.sub(r"[^A-Za-z0-9]+", "_", call[1] if len(call) > 1 else "").strip("_")
    for name in ("%s_%s.json" % (method, slug), "default.json"):
        path = os.path.join(base, "fixtures", name)
        if os.path.isfile(path):
            with open(path) as f:
                sys.stdout.write(f.read())
            return 0
    print("stub: no fixture for %s" % " ".join(call), file=sys.stderr)
    return 4


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
