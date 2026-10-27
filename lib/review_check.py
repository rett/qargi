#!/usr/bin/env python3
"""Checks that an agent's output is a series of change-specific patches with their context,
not one monolithic patch. Usage: review_check.py RUN_DIR   (exit 1 on any FAIL)
RUN_DIR holds manifest.json and the patches (RUN_DIR/patches/*.patch or RUN_DIR/*.patch)."""
import glob, json, os, re, sys
from email.utils import parsedate_to_datetime

run = sys.argv[1] if len(sys.argv) > 1 else "."
fails, warns, notes = [], [], []
F = lambda m: fails.append("FAIL " + m)
W = lambda m: warns.append("WARN " + m)
N = lambda m: notes.append("NOTE " + m)

patches = sorted(glob.glob(os.path.join(run, "patches", "*.patch")) or glob.glob(os.path.join(run, "*.patch")))
if not patches:
    print("FAIL no patches found in %s" % run); sys.exit(1)
try:
    man = json.load(open(os.path.join(run, "manifest.json")))
except Exception as e:
    man = {}; F("manifest.json missing or unreadable (%s)" % e)

info = []
for p in patches:
    t = open(p, errors="replace").read()
    unfolded = re.sub(r"\n[ \t]+", " ", t.split("\n\n", 1)[0])   # git folds long header lines
    subj = re.search(r"(?m)^Subject: (?:\[PATCH[^\]]*\] )?(.*)$", unfolded)
    date = re.search(r"(?m)^Date: (.*)$", t)
    head, _, rest = t.partition("\n---\n")
    body = head.split("\n\n", 1)[1].strip() if "\n\n" in head else ""
    files = re.findall(r"(?m)^diff --git a/(\S+) b/", t)
    changed = len(re.findall(r"(?m)^[+-](?![+-]{2} )", t))
    areas = {f.split("/")[0] for f in files}
    ts = None
    if date:
        try: ts = parsedate_to_datetime(date.group(1)).timestamp()
        except Exception: pass
    info.append({"name": os.path.basename(p), "subject": subj.group(1).strip() if subj else "", "body": body,
                 "files": files, "changed": changed, "areas": areas, "ts": ts})

n = len(info)
nums = [re.match(r"(\d{4})-", i["name"]) for i in info]
if not all(nums) or [int(m.group(1)) for m in nums] != list(range(1, n + 1)):
    F("patches are not numbered 0001..%04d in order (git format-patch output)" % n)
for i in info:
    if not i["subject"]: F("%s: no subject" % i["name"])
    if not i["body"]:
        F("%s: the commit message has no body; each commit must say what changed and why, so its context travels with it" % i["name"])
if man:
    commits = man.get("commits", [])
    if len(commits) != n: F("manifest lists %d commit(s) but there are %d patch(es): one patch per commit" % (len(commits), n))
    subjects = {c.get("subject", "").strip() for c in commits}
    for i in info:
        if subjects and i["subject"] not in subjects: W("%s: its subject is not among the manifest's commits" % i["name"])
    adv = man.get("commit_advice")
    if not adv: W("manifest has no commit_advice")
    elif len(adv) != n: W("commit_advice has %d entries for %d patches" % (len(adv), n))
    groups = man.get("patch_groups")
    if not groups: W("manifest has no patch_groups (which commits belong to which change)")
    else:
        listed = [s for g in groups for s in g.get("commits", [])]
        if sorted(listed) != sorted(c.get("sha", "")[:7] for c in commits) and sorted(listed) != sorted(c.get("sha", "") for c in commits) \
           and sorted(listed) != sorted(c.get("subject", "") for c in commits):
            W("patch_groups do not cover every commit exactly once (list commits by sha or subject)")
        for g in groups:
            if not g.get("why"): W("patch group %r has no why" % g.get("name"))
if not os.path.exists(os.path.join(run, "series.md")) and not os.path.exists(os.path.join(run, "patches", "series.md")):
    W("no series.md (a short account of each patch in order)")

# monolith heuristics
total = sum(i["changed"] for i in info) or 1
allareas = set().union(*[i["areas"] for i in info])
if n == 1 and len(allareas) >= 3:
    F("one patch touches %d areas (%s): this looks monolithic; split it into change-specific commits" % (len(allareas), ", ".join(sorted(allareas))))
if n > 1:
    big = max(info, key=lambda i: i["changed"])
    if big["changed"] / total > 0.7 and len(big["areas"]) >= 3:
        W("%s holds %d%% of the changed lines across %d areas: check it is one change, not several combined" % (big["name"], 100 * big["changed"] // total, len(big["areas"])))
ts = [i["ts"] for i in info if i["ts"]]
if n >= 3 and len(ts) == n and max(ts) - min(ts) < 120:
    N("all %d commits are dated within %d seconds: they may have been made in one batch at the end; make sure each one really stands alone and its message records the reasoning at that step" % (n, int(max(ts) - min(ts))))

for i in info:
    print("%s  %s  (%d file(s), %d changed line(s))" % (i["name"], i["subject"][:70], len(i["files"]), i["changed"]))
out = fails + warns + notes
print("\n".join(out) if out else "series ok: %d change-specific patch(es), each with its own message" % n)
print("%d fail, %d warn" % (len(fails), len(warns)))
sys.exit(1 if fails else 0)
