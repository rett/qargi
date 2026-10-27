#!/usr/bin/env python3
"""Simulation: a new project's empty stores reach the canon, a role's seed files are added
(as `canon seed-role` does), and `canon check` must report no problems.
Usage: role_seed_sim.py ROLE"""
import json, os, subprocess, sys, tempfile
role = sys.argv[1]
here = os.path.dirname(os.path.abspath(__file__))
canon = os.path.join(here, "..", "lib", "canon.py")
seed = os.path.join(here, "..", "provision", "canon-seed")
rs = os.path.join(here, "..", "provision", "role-seeds", role)
roles = "dev,docs,review,test"
roles = "dev,docs,review,test"
sys.path.insert(0, os.path.join(here, "..", "lib"))
import canon as C
for kind, part in (("reference", "reference"), ("memory", "memory")):
    tmp = tempfile.mkdtemp(); st = os.path.join(tmp, "s.jsonl"); open(st, "w").close()
    r = subprocess.run([sys.executable, canon, "plan", "--kind", kind, "--project", "demo", "--roles", roles,
                        "--default-role", "dev", "--store", st, "--seed", seed], capture_output=True, text=True)
    plan = json.loads(r.stdout)
    mems = C.simulate({}, plan["ops"])
    base = os.path.join(rs, part)
    if os.path.isdir(base):
        for d, _, fs in os.walk(base):
            for f in fs:
                rel = os.path.relpath(os.path.join(d, f), base)
                p = ("/shared/%s" if role == "shared" else "/roles/" + role + "/%s") % rel
                c = open(os.path.join(d, f)).read()
                mems[p] = {"type": "memory", "id": "seed_%s" % rel, "path": p, "content": c, "content_sha256": ""}
    with open(st, "w") as f:
        for m in mems.values():
            f.write(json.dumps(m) + "\n")
    r = subprocess.run([sys.executable, canon, "check", "--kind", kind, "--project", "demo", "--roles", roles, "--store", st], capture_output=True, text=True)
    print("%s: %s" % (kind, r.stdout.strip().splitlines()[-1]))
    if r.returncode != 0 or "WARN" in r.stdout:
        print(r.stdout); sys.exit(1)
print("OK: %s seed conforms to the canon" % role)
