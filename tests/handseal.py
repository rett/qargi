#!/usr/bin/env python3
"""A test helper: write the record `qargi provider seal` leaves for each library pack directory given, so that a fixture a test builds by hand
(a definition.json put in the library with jq) is a sealed pack. Without a record a library pack is "unrecorded" and qargi does not use it.
usage: handseal.py DIR...   (each DIR holds a definition.json; its executables, the files with an executable mode, are recorded as approved)"""
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
import provider as P  # noqa: E402

for d in sys.argv[1:]:
    with open(os.path.join(d, "definition.json")) as f:
        kind = json.load(f).get("kind", "provider")
    ex = {}
    for dp, _, fns in os.walk(d):
        for fn in fns:
            p = os.path.join(dp, fn)
            if os.stat(p).st_mode & 0o111 and fn != ".pack.json":
                with open(p, "rb") as f:
                    ex[os.path.relpath(p, d)] = hashlib.sha256(f.read()).hexdigest()
    with open(os.path.join(d, ".pack.json"), "w") as f:
        json.dump({"kind": kind, "name": os.path.basename(d), "source": "test", "sealed": True, "sha256": P.tree_hash(d), "executables": ex}, f)
