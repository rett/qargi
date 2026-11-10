#!/usr/bin/env python3
"""Checks that an agent's output is a series of change-specific patches with their context,
not one monolithic patch. Usage: review_check.py OUT [--allow-empty]   (exit 1 on any FAIL, 2 on a usage error)
OUT is the member's output directory (RUN/out; given RUN, whose out directory exists, it checks RUN/out): it holds manifest.json and the patches in OUT/patches/*.patch, the one place `review apply` reads them from.
SCOPE is a hard limit: the SCOPE line of RUN/task.md (beside OUT) when it records one, else the manifest's scope[]; a patch outside it fails.
A review run has no patches: report.md (or PREFIXreport.md) with a Findings heading and a last line `verdict: accept` or `verdict: revise`, with manifest.json beside it, is its deliverable."""
import fnmatch, glob, json, os, re, sys
from email.utils import parsedate_to_datetime

args = [a for a in sys.argv[1:] if not a.startswith("--")]
unknown = [a for a in sys.argv[1:] if a.startswith("--") and a != "--allow-empty"]
if unknown or len(args) > 1:
    print("qargi: %s\nusage: review_check.py OUT [--allow-empty]" % ("unknown option " + unknown[0] if unknown else "one OUT directory, not %d" % len(args)), file=sys.stderr)
    sys.exit(2)
allow_empty = "--allow-empty" in sys.argv   # a team member may return no commits (blocked, or nothing to change)
run = args[0] if args else "."
fails, warns, notes = [], [], []
F = lambda m: fails.append("FAIL " + m)
W = lambda m: warns.append("WARN " + m)
N = lambda m: notes.append("NOTE " + m)
# a run directory (RUN_DIR) was given where OUT (RUN_DIR/out) is meant: use its out directory, unless the directory is an OUT itself
if os.path.isdir(os.path.join(run, "out")) and not os.path.isdir(os.path.join(run, "patches")) and not os.path.exists(os.path.join(run, "manifest.json")):
    run = os.path.join(run, "out")
    N("checked %s (a run directory was given; the output directory is RUN_DIR/out)" % run)

patches = sorted(glob.glob(os.path.join(run, "patches", "*.patch")))
if not patches:
    # a review run returns a report, not patches
    # the report is report.md, or PREFIXreport.md when the task block gave an OUT_PREFIX (a team run: review--report.md)
    for rep in sorted(glob.glob(os.path.join(run, "*report.md"))):
        text = open(rep, errors="replace").read()
        if text.strip() and re.search(r"(?mi)^#+\s*findings\b", text):
            # the report is `# Findings`, `# Checked`, and a last line `verdict: accept` or `verdict: revise`; manifest.json travels with it
            base = os.path.basename(rep)
            last = [l.strip() for l in text.splitlines() if l.strip()][-1]
            try:
                json.load(open(os.path.join(run, base[:-len("report.md")] + "manifest.json")))
            except Exception as e:
                F("%s: %smanifest.json missing or unreadable (%s); a report-only run returns report.md and manifest.json" % (base, base[:-len("report.md")], e))
            if not re.fullmatch(r"verdict: (accept|revise)", last):
                F("%s: the last line must be `verdict: accept` or `verdict: revise` (it is: %s)" % (base, last[:60]))
            if not re.search(r"(?mi)^#+\s*checked\b", text):
                W("%s: no `# Checked` section (what you ran with its exit status; what you only read)" % base)
            if fails:
                print("\n".join(fails + warns)); print("%d fail, %d warn" % (len(fails), len(warns))); sys.exit(1)
            print("OK report-only run: %s holds a Findings section and ends with its verdict (%d chars)" % (base, len(text)))
            if warns: print("\n".join(warns))
            sys.exit(0)
    try:
        m0 = json.load(open(os.path.join(run, "manifest.json")))
    except Exception:
        m0 = None
    if m0 is not None and m0.get("commits") == [] and (allow_empty or m0.get("status") == "BLOCKED"):
        print("OK no commits (status %s)%s" % (m0.get("status"), ": " + m0["blocked_reason"] if m0.get("blocked_reason") else "")); sys.exit(0)
    print("FAIL no patches found in %s, and no report.md (or PREFIXreport.md) with a Findings section" % run); sys.exit(1)
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
    renamed = re.findall(r"(?m)^diff --git a/\S+ b/(\S+)$", t)   # the new name of a rename or copy is a touched path too
    changed = len(re.findall(r"(?m)^[+-](?![+-]{2} )", t))
    areas = {f.split("/")[0] for f in files}
    ts = None
    if date:
        try: ts = parsedate_to_datetime(date.group(1)).timestamp()
        except Exception: pass
    info.append({"name": os.path.basename(p), "subject": subj.group(1).strip() if subj else "", "body": body,
                 "files": files, "paths": set(files) | set(renamed), "changed": changed, "areas": areas, "ts": ts})

n = len(info)
nums = [re.match(r"(\d{4})-", i["name"]) for i in info]
if not all(nums) or [int(m.group(1)) for m in nums] != list(range(1, n + 1)):
    F("patches are not numbered 0001..%04d in order (git format-patch output)" % n)
for i in info:
    if not i["subject"]: F("%s: no subject" % i["name"])
    if not i["body"]:
        F("%s: the commit message has no body; each commit must say what changed and why, so its context travels with it" % i["name"])

def task_scope(out):
    """The paths of the `SCOPE:` line of the run's task block (RUN/task.md, beside OUT; the guard keeps a member from writing it), or None."""
    try:
        text = open(os.path.join(os.path.dirname(os.path.abspath(out)), "task.md"), errors="replace").read()
    except OSError:
        return None
    m = re.search(r"(?m)^[ \t]*(?:[-*][ \t]+)?SCOPE:[ \t]*(.*)$", text)
    paths = [p for p in re.split(r"[,\s]+", m.group(1)) if p] if m else []
    return None if paths in ([], ["none"]) else paths

def in_scope(path, scope):
    for s in scope:
        s = s[2:] if s.startswith("./") else s
        if any(c in s for c in "*?["):
            if fnmatch.fnmatchcase(path, s): return True
        elif path == s.rstrip("/") or path.startswith(s.rstrip("/") + "/"): return True
    return False

# SCOPE is a hard limit: the scope of the task block when it records one, else the manifest's scope[]; no patch may touch a path outside it
scope = task_scope(run) or [str(s) for s in (man.get("scope") if isinstance(man.get("scope"), list) else [])]
if scope:
    listed = man.get("touched_paths") if isinstance(man.get("touched_paths"), list) else []
    touched = {f for i in info for f in i["paths"]} | {str(t.get("path", "") if isinstance(t, dict) else t) for t in listed}
    outside = sorted(p for p in touched if p and not in_scope(p, scope))
    if outside:
        F("%d path(s) outside SCOPE (%s): %s; stop with BLOCKED naming the path, or list the change under noticed_not_acted_on" % (len(outside), ", ".join(scope), ", ".join(outside[:8]) + (" ..." if len(outside) > 8 else "")))

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
    W("all %d commits are dated within %d seconds: they look made in one batch at the end, and the contract says to commit as you go; make sure each one really stands alone and its message records the reasoning at that step" % (n, int(max(ts) - min(ts))))

for i in info:
    print("%s  %s  (%d file(s), %d changed line(s))" % (i["name"], i["subject"][:70], len(i["files"]), i["changed"]))
out = fails + warns + notes
print("\n".join(out) if out else "series ok: %d change-specific patch(es), each with its own message" % n)
print("%d fail, %d warn" % (len(fails), len(warns)))
sys.exit(1 if fails else 0)
