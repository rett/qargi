#!/usr/bin/env python3
"""Simulation test: plan a migration, apply the steps to an in-memory store, plan
again (must be a no-op) and check (must pass). Usage: canon_sim.py KIND FIXTURE.jsonl"""
import json, subprocess, sys, tempfile, os
kind, fixture = sys.argv[1], sys.argv[2]
here = os.path.dirname(os.path.abspath(__file__))
canon = os.path.join(here, "..", "lib", "canon.py")
seed = os.path.join(here, "..", "provision", "canon-seed")
roles = "dev,docs,review,test"

def run(*args):
    r = subprocess.run([sys.executable, canon, *args], capture_output=True, text=True)
    return r.returncode, r.stdout

def write(mems, path):
    with open(path, "w") as f:
        for i, (p, c) in enumerate(sorted(mems.items())):
            f.write(json.dumps({"type": "memory", "id": mems_ids.setdefault(p, "mem_%d" % len(mems_ids)), "path": p, "content": c}) + "\n")

mems_ids = {}
mems = {}
for l in open(fixture):
    m = json.loads(l)
    if m.get("type", "memory") == "memory":
        mems[m["path"]] = m["content"]; mems_ids[m["path"]] = m["id"]
tmp = tempfile.mkdtemp()
st = os.path.join(tmp, "s.jsonl")
write(mems, st)
rc, out = run("plan", "--kind", kind, "--project", "tacctl", "--roles", roles, "--default-role", "dev", "--store", st, "--seed", seed, "--today", "2026-10-27")
plan = json.loads(out)
print("from %s to %s: %d steps, %d notes" % (plan["from_version"], plan["to_version"], len(plan["ops"]), len(plan["notes"])))
byid = {v: k for k, v in mems_ids.items()}
for op in plan["ops"]:
    if op["op"] == "move":
        c = mems.pop(op["from"]); mems[op["to"]] = c; mems_ids[op["to"]] = mems_ids.pop(op["from"])
    elif op["op"] in ("create", "marker") and not op.get("id"):
        mems[op["path"]] = op["content"]; mems_ids[op["path"]] = "new_%d" % len(mems_ids)
    elif op["op"] in ("update", "marker"):
        mems[op["path"]] = op["content"]
write(mems, st)
rc, out = run("plan", "--kind", kind, "--project", "tacctl", "--roles", roles, "--default-role", "dev", "--store", st, "--seed", seed, "--today", "2026-10-27")
again = json.loads(out)
assert again["from_version"] == 1 and not again["ops"], "second plan is not a no-op: %s" % json.dumps(again)[:300]
rc, out = run("check", "--kind", kind, "--project", "tacctl", "--roles", roles, "--store", st)
print(out.strip().splitlines()[-1])
assert rc == 0, out
print("OK: idempotent and conformant")
