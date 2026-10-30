#!/usr/bin/env python3
"""qargi report: what the session tracker says about cost, review and stuck sessions. Read-only; it reads
sessions.json and nothing else (no cloud call, no registry). The free-text note and asked fields are never
printed. summarize() is a pure function over the tracker's dict, so the tests feed it fixtures.

Local runs are read from the run directories `qargi local prepare` makes (RUN/out holds the agent's manifest.json
and log.txt), found through the one-line-per-run registry prepare appends to ($QARGI_STATE/local-runs.jsonl) and,
with --runs-root DIR (or QARGI_RUNS_ROOT), by scanning DIR/qargi.* as well.

Usage: report.py [--since DATE] [--instance NAME] [--stale-after DURATION] [--local-stale-after DURATION]
                 [--runs-root DIR] [--json]"""
import json, os, statistics, sys
from datetime import datetime, timezone

STATE = os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")
REVIEW = ("pending", "applied", "rejected", "not-applicable")
# status_idle stop reasons (Managed Agents): end_turn is a turn that ended on its own; the others need a person.
FINISHED = ("end_turn",)
NEEDS_INPUT = ("requires_action", "budget_reached", "retries_exhausted")
# a session in these states is working or not yet read, so it is not "waiting for review"
NOT_SETTLED = ("running", "rescheduling", "unknown")

LOCAL_LIMITS = [
    "local runs are known from the directories qargi local prepare made; a run made before the registry existed is found only through --runs-root",
    "'still changing' means a file in the run (output or clone) changed within the stale window: the agent, or a background command it left running, is probably still working",
    "a run can end its turn while its own background command still runs and report again later; a quiet run is only possibly stalled",
    "a local run has no cost record and no review state; this section cannot say whether its work was applied",
]
LIMITS = [
    "spend is list_cost as qargi last read it from the session (the units of the budget flags: cents, per the docs), not an invoice",
    "an age counts from last_seen, the last time qargi read the session; a session nobody refreshed looks older than it is",
    "review_state records what you did with the work (mark), not whether the work was good",
    "an interrupted turn also ends with end_turn; only an interrupt sent through qargi stop is recorded, so a session stopped from the console counts as finished",
]


def parse_time(s):
    if not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def parse_duration(s):
    """90, 90s, 45m, 2h or 1d, in seconds."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    s = str(s).strip()
    try:
        if s and s[-1] in units:
            return int(s[:-1]) * units[s[-1]]
        return int(s)
    except ValueError:
        raise ValueError("a duration is a whole number with s, m, h or d (2h, 90m, 1d), got %r" % s)


def cost(v):
    try:
        return float(v) if v is not None and v != "" else None
    except (TypeError, ValueError):
        return None


def age(now, then):
    t = parse_time(then)
    return None if t is None else max(0, int((now - t).total_seconds()))


def newest_change(run, cap=20000):
    """The mtime of the newest file the run has touched: everything under out/ and the clone's working tree, plus
    the few git files a commit or checkout rewrites (the object store is not walked)."""
    newest, n = None, 0
    def see(p):
        nonlocal newest
        try:
            m = os.stat(p).st_mtime
        except OSError:
            return
        if newest is None or m > newest:
            newest = m
    for top in (os.path.join(run, "out"), os.path.join(run, "clone")):
        for d, dirs, files in os.walk(top):
            if top.endswith("clone") and ".git" in dirs:
                dirs.remove(".git")
            for f in files:
                see(os.path.join(d, f))
                n += 1
            if n > cap:
                break
    for g in ("index", "HEAD", os.path.join("logs", "HEAD")):
        see(os.path.join(run, "clone", ".git", g))
    return newest


def inspect_run(entry):
    """The facts about one local run directory; entry: {run, label, ability, started} (any may be None)."""
    run = entry["run"]
    f = {"run": run, "label": entry.get("label") or "-", "ability": entry.get("ability"), "started": entry.get("started"),
         "exists": os.path.isdir(run), "manifest": None, "last_change": None, "log_bytes": None}
    if not f["exists"]:
        return f
    mf = os.path.join(run, "out", "manifest.json")
    if os.path.isfile(mf):
        try:
            with open(mf) as h:
                st = json.load(h).get("status")
            f["manifest"] = st if st in ("DONE", "BLOCKED") else "unreadable"
        except (OSError, ValueError, AttributeError):
            f["manifest"] = "unreadable"
    try:
        f["log_bytes"] = os.path.getsize(os.path.join(run, "out", "log.txt"))
    except OSError:
        pass
    f["last_change"] = newest_change(run)
    return f


def find_local_runs(state, root=None):
    """The runs to look at: every line of the registry, then the directories under root not already listed."""
    seen, out = set(), []
    try:
        with open(os.path.join(state, "local-runs.jsonl")) as h:
            for line in h:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict) and e.get("run") and e["run"] not in seen:
                    seen.add(e["run"])
                    out.append({"run": e["run"], "label": e.get("slug"), "ability": e.get("ability"), "started": e.get("started")})
    except OSError:
        pass
    if root and os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            run = os.path.join(root, name)
            if not name.startswith("qargi.") or run in seen or not os.path.isdir(run):
                continue
            label = started = None
            try:
                with open(os.path.join(run, "clone", ".git", "HEAD")) as h:
                    ref = h.read().strip()
                label = ref.rsplit("agent/", 1)[1] if "agent/" in ref else None
                started = datetime.fromtimestamp(os.stat(os.path.join(run, "ability")).st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (OSError, IndexError):
                pass
            out.append({"run": run, "label": label, "ability": None, "started": started})
    return out


def local_section(facts, now, stale_after=1800, since=None):
    """Pure: classify the facts of local runs. A run with a manifest is finished; one without is either still
    changing (a background command may be running after the agent ended its turn) or quiet for stale_after."""
    runs, counts = [], {"finished_DONE": 0, "finished_BLOCKED": 0, "finished_other": 0, "no_manifest_changing": 0, "possibly_stalled": 0, "directory_gone": 0}
    for f in facts:
        t = parse_time(f.get("started"))
        if since is not None and (t is None or t < since):
            continue
        quiet = None if f["last_change"] is None else max(0, int(now.timestamp() - f["last_change"]))
        if not f["exists"]:
            state, key = "directory gone", "directory_gone"
        elif f["manifest"] in ("DONE", "BLOCKED"):
            state, key = "finished " + f["manifest"], "finished_" + f["manifest"]
        elif f["manifest"]:
            state, key = "manifest unreadable", "finished_other"
        else:
            if quiet is None and t is not None:
                quiet = max(0, int((now - t).total_seconds()))
            if quiet is not None and quiet > stale_after:
                state, key = "no manifest, quiet for %d minutes: possibly stalled" % (quiet // 60), "possibly_stalled"
            else:
                state, key = "no manifest, still changing", "no_manifest_changing"
        counts[key] += 1
        runs.append({"run": f["run"], "label": f["label"], "ability": f["ability"], "started": f["started"], "state": state, "unfinished": key in ("possibly_stalled", "no_manifest_changing"),
                     "since_last_change_seconds": quiet, "log_bytes": f["log_bytes"], "age_seconds": age(now, f["started"])})
    runs.sort(key=lambda r: r["started"] or "")
    return {"stale_after_seconds": stale_after, "runs": runs, "counts": counts}


def scope(rows, now, stale_after):
    """The figures for one set of sessions: [(sid, row)]."""
    out = {"sessions": len(rows), "review": {k: 0 for k in REVIEW}, "status": {}}
    spend, unknown_cost, applied = 0.0, 0, 0
    pending, stale, spans = [], [], []
    idle = {"finished": 0, "stopped_by_qargi": 0, "needs_input": {}, "not_recorded": 0, "other": {}}
    for sid, r in rows:
        rv, st = r.get("review_state"), r.get("status") or "unknown"
        out["review"][rv] = out["review"].get(rv, 0) + 1
        out["status"][st] = out["status"].get(st, 0) + 1
        c = cost(r.get("list_cost"))
        if c is None:
            unknown_cost += 1
        else:
            spend += c
        if rv == "applied":
            applied += 1
        a = age(now, r.get("last_seen"))
        item = {"session": sid, "instance": r.get("instance"), "label": r.get("label") or "-", "status": st, "age_seconds": a}
        waiting = rv == "pending" and r.get("closed_at") is None and st not in NOT_SETTLED
        if waiting:
            pending.append(item)
        if a is not None and a > stale_after and r.get("closed_at") is None and (st == "running" or (st == "idle" and rv == "pending")):
            stale.append(item)
        if r.get("closed_at") is not None:
            c0, c1 = parse_time(r.get("created")), parse_time(r.get("closed_at"))
            if c0 and c1 and c1 >= c0:
                spans.append(int((c1 - c0).total_seconds()))
        if st == "idle":
            why = r.get("stop_reason") or ""
            if not why:
                idle["not_recorded"] += 1
            elif why in FINISHED and r.get("interrupt_sent_at"):
                idle["stopped_by_qargi"] += 1   # an interrupted turn also ends with end_turn
            elif why in FINISHED:
                idle["finished"] += 1
            elif why in NEEDS_INPUT:
                idle["needs_input"][why] = idle["needs_input"].get(why, 0) + 1
            else:
                idle["other"][why] = idle["other"].get(why, 0) + 1
    out["spend"] = {"total": spend, "sessions_without_cost": unknown_cost, "applied_sessions": applied,
                    "per_applied": (spend / applied) if applied else None}
    key = lambda i: -(i["age_seconds"] if i["age_seconds"] is not None else -1)
    out["pending_review"] = sorted(pending, key=key)
    out["stale"] = sorted(stale, key=key)
    out["time_to_close_seconds"] = {"count": len(spans), "median": statistics.median(spans) if spans else None, "max": max(spans) if spans else None}
    out["idle"] = idle
    return out


def summarize(sessions, now, since=None, instance=None, stale_after=7200):
    """sessions: the tracker's dict {sid: row}. since: a datetime (sessions created on or after it).
    Returns the figures per instance and in total; nothing in it is free text from the tracker."""
    rows = []
    for sid, r in sorted(sessions.items()):
        if not isinstance(r, dict):
            continue
        if instance and r.get("instance") != instance:
            continue
        if since is not None:
            c = parse_time(r.get("created"))
            if c is None or c < since:
                continue
        rows.append((sid, r))
    names = sorted({r.get("instance") or "-" for _, r in rows})
    return {
        "generated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "since": since.strftime("%Y-%m-%d") if since else None,
        "stale_after_seconds": stale_after,
        "total": scope(rows, now, stale_after),
        "instances": {n: scope([(s, r) for s, r in rows if (r.get("instance") or "-") == n], now, stale_after) for n in names},
        "limits": list(LIMITS),
    }


def hms(sec):
    if sec is None:
        return "unknown age"
    sec = int(sec)
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return ("%dd %dh" % (d, h)) if d else ("%dh %02dm" % (h, m)) if h else "%dm" % m


def num(x):
    return ("%d" % x) if abs(x - round(x)) < 1e-9 else ("%.1f" % x)


def counts(d, order=()):
    keys = [k for k in order if d.get(k)] + sorted(k for k in d if k not in order and d[k])
    return ", ".join("%s %d" % (k, d[k]) for k in keys) or "none"


def render_scope(s, title, stale_after, out):
    out.append(title)
    out.append("  sessions: %d" % s["sessions"])
    out.append("  review: %s" % counts(s["review"], REVIEW))
    out.append("  status: %s" % counts(s["status"], ("running", "idle", "archived")))
    sp = s["spend"]
    line = "  spend: %s" % num(sp["total"])
    if sp["sessions_without_cost"]:
        line += " (no cost recorded for %d session(s))" % sp["sessions_without_cost"]
    out.append(line)
    out.append("  spend per applied session (all spend over the applied ones): %s" % (num(sp["per_applied"]) + " (%d applied)" % sp["applied_sessions"] if sp["per_applied"] is not None else "n/a (none applied)"))
    i = s["idle"]
    if s["status"].get("idle"):
        out.append("  idle sessions:")
        out.append("    awaiting review (finished, end_turn): %d" % i["finished"])
        out.append("    stopped by qargi (interrupt sent, end_turn): %d" % i["stopped_by_qargi"])
        out.append("    stopped needing input: %s" % counts(i["needs_input"]))
        if i["other"]:
            out.append("    other stop reason: %s" % counts(i["other"]))
        out.append("    reason a session went idle: not recorded for %d" % i["not_recorded"])
    t = s["time_to_close_seconds"]
    out.append("  created to closed: %s" % (("%d closed, median %s, max %s" % (t["count"], hms(t["median"]), hms(t["max"]))) if t["count"] else "no closed session"))
    out.append("  pending review, oldest first:" + (" none" if not s["pending_review"] else ""))
    for p in s["pending_review"]:
        out.append("    %-24s %-12s %s" % (p["label"], p["status"], hms(p["age_seconds"])))
    out.append("  looks stale (running or idle-pending for over %s):%s" % (hms(stale_after), " none" if not s["stale"] else ""))
    for p in s["stale"]:
        out.append("    %-24s %-12s %s" % (p["label"], p["status"], hms(p["age_seconds"])))


def render_local(loc, out):
    out.append("")
    out.append("Local runs")
    c = loc["counts"]
    out.append("  runs: %d (finished DONE %d, BLOCKED %d, no manifest and still changing %d, possibly stalled %d%s)" % (
        len(loc["runs"]), c["finished_DONE"], c["finished_BLOCKED"], c["no_manifest_changing"], c["possibly_stalled"],
        (", directory gone %d" % c["directory_gone"]) if c["directory_gone"] else ""))
    open_runs = [r for r in loc["runs"] if r["unfinished"]]
    out.append("  without a manifest, oldest first:" + (" none" if not open_runs else ""))
    for r in open_runs:
        log = "no log" if r["log_bytes"] is None else "log %d bytes" % r["log_bytes"]
        out.append("    %-24s started %s ago, last change %s ago, %s" % (r["label"], hms(r["age_seconds"]), hms(r["since_last_change_seconds"]), log))
        out.append("      %s" % r["state"])
        out.append("      %s" % r["run"])


def render(rep):
    out = ["qargi report, %s%s" % (rep["generated"], (", sessions created since " + rep["since"]) if rep["since"] else "")]
    if not rep["total"]["sessions"]:
        out.append("no tracked sessions match")
    else:
        render_scope(rep["total"], "Total", rep["stale_after_seconds"], out)
        for n, s in rep["instances"].items():
            out.append("")
            render_scope(s, "Instance " + n, rep["stale_after_seconds"], out)
    if rep.get("local") is not None:
        render_local(rep["local"], out)
    elif rep.get("local_skipped"):
        out.append("")
        out.append("Local runs: not shown (%s)" % rep["local_skipped"])
    out.append("")
    out.append("What this cannot tell you:")
    out += ["  - " + x for x in rep["limits"] + (LOCAL_LIMITS if rep.get("local") is not None else [])]
    out.append("  - the note and the request (asked) of a session are never printed")
    return "\n".join(out)


def main(argv):
    since = inst = None
    root = os.environ.get("QARGI_RUNS_ROOT") or None
    stale, lstale = 7200, 1800
    as_json = False
    i = 0
    try:
        while i < len(argv):
            a = argv[i]
            if a == "--json":
                as_json = True
            elif a in ("--since", "--instance", "--stale-after", "--local-stale-after", "--runs-root") and i + 1 < len(argv):
                v = argv[i + 1]
                i += 1
                if a == "--since":
                    since = parse_time(v)
                    if since is None:
                        raise ValueError("--since takes a date, 2026-10-01 or 2026-10-01T08:00:00Z, got %r" % v)
                elif a == "--instance":
                    inst = v
                elif a == "--runs-root":
                    root = v
                elif a == "--stale-after":
                    stale = parse_duration(v)
                else:
                    lstale = parse_duration(v)
            else:
                raise ValueError("usage: qargi report [--since DATE] [--instance NAME] [--stale-after DURATION] [--local-stale-after DURATION] [--runs-root DIR] [--json]")
            i += 1
    except ValueError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2
    path = os.path.join(STATE, "sessions.json")
    try:
        with open(path) as f:
            sessions = json.load(f)
    except FileNotFoundError:
        sessions = {}
    except (OSError, ValueError) as e:
        print("qargi: cannot read the tracker: %s" % e, file=sys.stderr)
        return 1
    now = datetime.now(timezone.utc)
    rep = summarize(sessions, now, since, inst, stale)
    if inst:
        rep["local_skipped"] = "local runs belong to no instance, so --instance leaves them out"
    else:
        rep["local"] = local_section([inspect_run(e) for e in find_local_runs(STATE, root)], now, lstale, since)
    print(json.dumps(rep, indent=2, sort_keys=True) if as_json else render(rep))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
