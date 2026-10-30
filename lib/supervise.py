#!/usr/bin/env python3
"""qargi supervise: find stalled agent runs and say so. Hooks only record; one idempotent tick is the only actor.

  supervise.py hook-event VERB        a Claude Code hook (stdin: its JSON): append one small line to
                                      $QARGI_STATE/run-events/<agent_id>.jsonl. No content is read or stored (ids,
                                      timestamps, the tool NAME and a hash of its input; never a command, a message
                                      or an error text). Always exits 0, quickly, even on malformed input.
  supervise.py tick [--now ISO] [--json]
  supervise.py status [--now ISO] [--json]
  supervise.py delivered KEY [--now ISO]            the coordinating session delivered the prepared nudge of a local run
  supervise.py nudge-check SID [--now ISO]          caps for a cloud nudge (prints JSON; sends nothing)
  supervise.py nudge-record SID [--now ISO]         count a cloud nudge that supervise.sh sent
  supervise.py hooks [--qargi COMMAND]              print the settings.json hook snippet (never writes a file)

The tick folds the per-run event files and the tracker (sessions.json) and the local-run registry (local-runs.jsonl)
into runs.json (the only writer, under a lock), classifies every unfinished run, and acts ONLY by printing
`QARGI SUPERVISE <class> <run> <next-action>` lines, appending to supervisor.log and audit.log (origin supervisor), and
PREPARING a nudge in nudges.jsonl (the exact fixed template and the target). It never sends anything. A nudge counts
once it is delivered: the coordinating session delivers a local one (`delivered`), the owner sends a cloud one with
`qargi supervise nudge SID --asked ...`. The numbers are data in supervise-defaults.json; the safety caps are also
enforced here (at most 2 nudges, cooldown of at least 10 minutes), so the data cannot loosen them.

Standing permission (extension point, default off): `standing_permission` in the defaults file is read by
standing_permission() below and is False for every key today. A future owner decision can let the tick send a cloud
nudge itself by checking it in tick_nudge(); nothing sends automatically now."""
import fcntl, hashlib, json, os, re, signal, sys, time
from datetime import datetime, timezone, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("QARGI_STATE") or os.path.join(os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state"), "qargi")
DEFAULTS = os.environ.get("QARGI_SUPERVISE_DEFAULTS") or os.path.join(HERE, "supervise-defaults.json")

EVENTS = {"subagent-start": "start", "subagent-stop": "stop", "tool-use": "tool", "tool-failure": "fail",
          "notification": "notify", "stop-failure": "stopfail", "pre-compact": "compact"}
HARD_MAX_NUDGES = 2          # the design's cap; the data may lower it, never raise it
HARD_COOLDOWN = 600          # seconds; at least 10 minutes between two nudges
ALERT = {"waiting", "stop_failure", "ended_no_manifest", "interim_overdue", "looping", "suspected_dead",
         "requires_action", "budget_reached", "stale_running", "idle_awaiting_review", "terminated"}
NUDGEABLE = {"interim_overdue", "looping", "suspected_dead", "stale_running"}
FILE_FIELDS = ("run_id", "agent_id", "agent_type", "ability", "started_at", "last_tool_at", "tool_calls", "last_tool_digest",
               "repeat_count", "failures", "compactions", "waiting_on", "waiting_since", "stop_failure", "ended_at", "end_kind",
               "report_count", "manifest_present", "last_activity_at", "nudges", "last_nudge_at", "interrupt_sent_at")


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    if not isinstance(s, str):
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return None


def secs(now, then):
    t = parse(then)
    return None if t is None else int((now - t).total_seconds())


def clean(v, n=60, keep=r"[^A-Za-z0-9_.:-]"):
    return re.sub(keep, "", str(v))[:n] if isinstance(v, (str, int)) else ""


def load_defaults():
    with open(DEFAULTS) as f:
        return json.load(f)


def cfg(d, ability, section, key):
    """A threshold: the defaults, then per_ability overrides, then the floors the code insists on."""
    v = ((d.get("per_ability") or {}).get(ability or "", {}).get(section) or {}).get(key)
    if v is None:
        v = d[section][key]
    if section == "nudge":
        if key == "max_per_run":
            v = min(int(v), HARD_MAX_NUDGES)
        elif key == "cooldown_seconds":
            v = max(int(v), HARD_COOLDOWN)
    return v


def standing_permission(d, key):
    """Extension point: may the tick itself send a nudge to this run? Always False now (default off)."""
    return False


# ---------------------------------------------------------------- hooks

def run_dir(path):
    p = os.path.realpath(path) if isinstance(path, str) and path else ""
    while p and p != os.path.dirname(p):
        if os.path.isfile(os.path.join(p, "ability")) and os.path.isfile(os.path.join(p, "refs.before")):
            return p
        p = os.path.dirname(p)
    return None


def hook_event(verb):
    """Never raises, never blocks, always returns normally (the caller exits 0)."""
    try:
        signal.signal(signal.SIGALRM, lambda *a: os._exit(0))
        signal.alarm(4)
        if verb not in EVENTS or sys.stdin.isatty():
            return
        p = json.loads(sys.stdin.buffer.read(4000000).decode("utf-8", "replace"))
        if not isinstance(p, dict):
            return
        ev = {"ev": EVENTS[verb], "t": iso(parse(os.environ.get("QARGI_NOW")) or datetime.now(timezone.utc))}   # QARGI_NOW: tests
        aid = clean(p.get("agent_id"), 80)
        run = run_dir(p.get("cwd"))
        if aid:
            ev["agent_id"] = aid
            name = aid
        elif run and verb in ("notification", "stop-failure", "pre-compact"):
            name = "run-" + os.path.basename(run)
        else:
            return          # an event of the coordinating session itself is not a run's
        if clean(p.get("agent_type"), 60):
            ev["agent_type"] = clean(p["agent_type"], 60)
        if clean(p.get("session_id"), 80):
            ev["session_id"] = clean(p["session_id"], 80)
        if run:
            ev["run"] = run
        if verb in ("tool-use", "tool-failure"):
            ev["tool"] = clean(p.get("tool_name"), 80)
            raw = json.dumps(p.get("tool_input"), sort_keys=True, separators=(",", ":"), default=str)
            ev["dg"] = hashlib.sha256((str(p.get("tool_name")) + "\0" + raw).encode("utf-8", "replace")).hexdigest()[:12]
            if verb == "tool-failure":
                ev["intr"] = p.get("is_interrupt") is True
        elif verb == "subagent-stop":
            bg = p.get("background_tasks")
            ev["bg"] = len(bg) if isinstance(bg, list) else None
            tp = p.get("agent_transcript_path")
            if isinstance(tp, str):
                ev["transcript"] = tp[:400]
        elif verb == "notification":
            ev["ntype"] = clean(p.get("notification_type"), 40)
        elif verb == "stop-failure":
            ev["err"] = clean(p.get("error"), 40, r"[^a-z_]")
        elif verb == "pre-compact":
            ev["trigger"] = clean(p.get("trigger"), 20, r"[^a-z]")
        d = os.path.join(STATE, "run-events")
        os.makedirs(d, mode=0o700, exist_ok=True)
        fd = os.open(os.path.join(d, name + ".jsonl"), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (json.dumps(ev, sort_keys=True) + "\n").encode())   # one write: an append of one line
        finally:
            os.close(fd)
    except BaseException:
        pass


# ---------------------------------------------------------------- files

def read_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def read_lines(path):
    out = []
    try:
        with open(path) as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if isinstance(e, dict):
                    out.append(e)
    except OSError:
        pass
    return out


def append_line(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (text + "\n").encode())
    finally:
        os.close(fd)


def audit(verb, detail, now_iso, asked=""):
    append_line(os.path.join(STATE, "audit.log"), json.dumps(
        {"ts": now_iso, "verb": verb, "detail": detail, "asked": asked, "approved": "", "nested": False, "origin": "supervisor"}))


def blank_row(key, kind):
    return {"kind": kind, "run_id": key, "agent_id": None, "agent_type": None, "ability": None, "slug": None, "run": None,
            "started_at": None, "last_tool_at": None, "tool_calls": 0, "last_tool_digest": None, "repeat_count": 0,
            "failures": 0, "compactions": 0, "waiting_on": None, "waiting_since": None, "stop_failure": None,
            "stop_failure_at": None, "ended_at": None, "end_kind": None, "bg": None, "transcript": None, "report_count": 0,
            "manifest_present": False, "last_activity_at": None, "nudges": 0, "last_nudge_at": None,
            "interrupt_sent_at": None, "class": None, "class_since": None, "announced": None, "salvage_announced": False}


def fold_event(r, e, wait_types):
    t, k = e.get("t"), e.get("ev")
    if e.get("agent_type") and not r["agent_type"]:
        r["agent_type"] = e["agent_type"]
    if e.get("run") and not r["run"]:
        r["run"] = e["run"]
    if r["started_at"] is None or (t and t < r["started_at"]):
        r["started_at"] = t
    if k == "start":
        r["ended_at"] = r["end_kind"] = None
    elif k in ("tool", "fail"):
        r["tool_calls"] += 1
        r["last_tool_at"] = t
        if e.get("dg") == r["last_tool_digest"]:
            r["repeat_count"] += 1
        else:
            r["last_tool_digest"], r["repeat_count"] = e.get("dg"), 1
        if k == "fail":
            r["failures"] += 1
        # a tool call after a wait, a stop failure or a stop: the ask was answered, the run went on
        if r["waiting_on"] and t > (r["waiting_since"] or ""):
            r["waiting_on"] = r["waiting_since"] = None
        if r["stop_failure"] and t > (r["stop_failure_at"] or ""):
            r["stop_failure"] = r["stop_failure_at"] = None
        if r["ended_at"] and t > r["ended_at"]:
            r["ended_at"] = r["end_kind"] = None
    elif k == "stop":
        r["ended_at"], r["bg"], r["report_count"] = t, e.get("bg"), r["report_count"] + 1
        if e.get("transcript"):
            r["transcript"] = e["transcript"]
        r["waiting_on"] = r["waiting_since"] = None
    elif k == "notify":
        if e.get("ntype") in wait_types:
            r["waiting_on"], r["waiting_since"] = e["ntype"], t
    elif k == "stopfail":
        r["stop_failure"], r["stop_failure_at"] = e.get("err") or "unknown", t
    elif k == "compact":
        r["compactions"] += 1


def fold_files(st, rows, wait_types):
    """Fold the new complete lines of every per-run file; st['offsets'] remembers how far each file was read."""
    d = os.path.join(STATE, "run-events")
    try:
        names = sorted(os.listdir(d), key=lambda n: (n.startswith("run-"), n))   # agent files first
    except OSError:
        return
    for name in names:
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(d, name)
        off = st["offsets"].get(name, 0)
        try:
            size = os.path.getsize(path)
            if size < off:
                off = 0
            with open(path, "rb") as f:
                f.seek(off)
                data = f.read()
        except OSError:
            continue
        end = data.rfind(b"\n") + 1
        if not end:
            continue
        st["offsets"][name] = off + end
        for line in data[:end].decode("utf-8", "replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not isinstance(e, dict) or not isinstance(e.get("t"), str):
                continue
            if e.get("agent_id"):
                key = e["agent_id"]
                if key not in rows:
                    rows[key] = blank_row(key, "local")
                    rows[key]["agent_id"] = key
                    rows[key]["run_id"] = os.path.basename(e["run"]) if e.get("run") else key
                fold_event(rows[key], e, wait_types)
            else:   # an event of the run's own session: apply it to the newest unfinished agent of that run
                cand = [k for k, r in rows.items() if r["kind"] == "local" and r["run"] == e.get("run") and r["agent_id"]]
                if cand:
                    key = max(cand, key=lambda k: rows[k]["started_at"] or "")
                else:
                    key = "local-" + os.path.basename(e.get("run") or name)
                    if key not in rows:
                        rows[key] = blank_row(key, "local")
                        rows[key]["run"], rows[key]["run_id"] = e.get("run"), key[len("local-"):]
                fold_event(rows[key], e, wait_types)


def join_local(rows, now, d):
    """Join local-runs.jsonl (from local prepare) by run directory; a registered run no agent reported on gets a row of
    its own (key local-<dir>), dropped once a real agent row appears for the same directory."""
    window = timedelta(days=int(d["registry_window_days"]))
    reg = {}
    for e in read_json_lines(os.path.join(STATE, "local-runs.jsonl")):
        if e.get("run"):
            reg[e["run"]] = e
    by_run = {}
    for k, r in rows.items():
        if r["kind"] == "local" and r["run"]:
            by_run.setdefault(r["run"], []).append(k)
    for run, e in reg.items():
        real = [k for k in by_run.get(run, []) if rows[k]["agent_id"]]
        for k in by_run.get(run, []):
            if real and not rows[k]["agent_id"]:
                del rows[k]
        keys = real or by_run.get(run, [])
        if not keys:
            s = parse(e.get("started"))
            if not os.path.isdir(run) or s is None or now - s > window:
                continue
            k = "local-" + os.path.basename(run)
            rows[k] = blank_row(k, "local")
            rows[k]["run"], rows[k]["run_id"], rows[k]["started_at"] = run, os.path.basename(run), e.get("started")
            keys = [k]
        for k in keys:
            rows[k]["ability"] = e.get("ability") or rows[k]["ability"]
            rows[k]["slug"] = e.get("slug") or rows[k]["slug"]
            if not rows[k]["started_at"]:
                rows[k]["started_at"] = e.get("started")
    for r in rows.values():
        if r["kind"] == "local" and r["run"] and not r["ability"]:
            try:
                with open(os.path.join(r["run"], "ability")) as f:
                    r["ability"] = f.read().strip() or None
            except OSError:
                pass


def read_json_lines(path):
    return read_lines(path)


def newest_mtime(r):
    run = r["run"]
    best = None
    def see(p):
        nonlocal best
        try:
            m = os.stat(p).st_mtime
        except OSError:
            return
        if best is None or m > best:
            best = m
    if run and os.path.isdir(run):
        sys.path.insert(0, HERE)
        import report
        m = report.newest_change(run)
        if m is not None:
            best = m
    if r.get("transcript"):
        see(r["transcript"])
    return best


def refresh_local(r):
    run = r["run"]
    r["manifest_present"] = bool(run) and os.path.isfile(os.path.join(run, "out", "manifest.json"))
    cands = []
    if r["last_tool_at"]:
        cands.append(parse(r["last_tool_at"]).timestamp())
    m = newest_mtime(r)
    if m is not None:
        cands.append(m)
    r["last_activity_at"] = iso(datetime.fromtimestamp(max(cands), timezone.utc)) if cands else None
    if r["ended_at"]:
        bg = r["bg"]
        r["end_kind"] = "interim" if (isinstance(bg, int) and bg > 0) else "final" if isinstance(bg, int) else ("final" if r["manifest_present"] else "interim")
    else:
        r["end_kind"] = None


# ---------------------------------------------------------------- classification

def classify_local(r, now, d):
    ab = r["ability"]
    if r["manifest_present"]:
        return "finished", ""
    if r["waiting_on"]:
        return "waiting", r["waiting_on"]
    if r["stop_failure"]:
        return "stop_failure", r["stop_failure"]
    if r["ended_at"] and r["end_kind"] == "final":
        return "ended_no_manifest", ""
    if r["ended_at"]:
        if secs(now, r["ended_at"]) > cfg(d, ab, "local", "interim_cap_seconds"):
            return "interim_overdue", ""
        return "interim", ""
    if r["repeat_count"] >= cfg(d, ab, "local", "loop_repeats"):
        return "looping", ""
    ref = r["last_activity_at"] or r["started_at"]
    quiet = secs(now, ref)
    if quiet is not None and quiet > cfg(d, ab, "local", "stale_seconds"):
        return "suspected_dead", ""
    return "working", ""


def num(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def budget_tight(t, d):
    cost, bud = num(t.get("list_cost")), num(t.get("budget"))
    return bool(cost is not None and bud and cost * 100 >= bud * cfg(d, None, "cloud", "budget_tight_percent"))


def classify_cloud(t, now, d):
    if t.get("closed_at"):
        return "closed", ""
    st, why = t.get("status"), t.get("stop_reason") or ""
    if st == "terminated":
        return "terminated", ""
    if st == "idle" and t.get("interrupt_sent_at") and why == "end_turn":
        return "stopped_by_qargi", ""
    if why == "requires_action" and st == "idle":
        return "requires_action", ""
    if why == "budget_reached":
        return "budget_reached", ""
    if st == "idle" and why == "retries_exhausted":
        return "stop_failure", why
    age = secs(now, t.get("last_processed_at") or t.get("last_seen"))
    if st == "running" and age is not None and age > cfg(d, None, "cloud", "stale_running_seconds"):
        return "stale_running", ""
    if st == "idle" and why == "end_turn" and t.get("review_state") == "pending" and age is not None and age > cfg(d, None, "cloud", "idle_review_seconds"):
        return "idle_awaiting_review", ""
    return ("working" if st == "running" else "ok"), ""


def next_action(cls, detail, kind):
    if cls == "stop_failure":
        return {"rate_limit": "wait-then-resume", "overloaded": "wait-then-resume", "authentication_failed": "log-in-again",
                "billing_error": "owner-must-fix-billing"}.get(detail, "check-the-error-then-resume" if kind == "local" else "check-the-session")
    return {"waiting": "answer-the-pending-approval", "ended_no_manifest": "collect-or-rerun",
            "interim_overdue": "notify-then-nudge", "looping": "notify-then-nudge", "suspected_dead": "notify-then-nudge",
            "requires_action": "answer-the-pending-approval", "budget_reached": "raise-the-budget-or-collect",
            "stale_running": "refresh-then-nudge", "idle_awaiting_review": "collect-and-review", "terminated": "collect-what-exists"}.get(cls, "none")


# ---------------------------------------------------------------- nudges

def nudge_state(key, lines=None):
    """From nudges.jsonl (the source of truth): delivered count, last delivery, the outstanding prepared nudge."""
    lines = read_lines(os.path.join(STATE, "nudges.jsonl")) if lines is None else lines
    prepared, closed, delivered = {}, set(), []
    for e in lines:
        if e.get("key") != key:
            continue
        if e.get("type") == "prepared":
            prepared[e["id"]] = e
        elif e.get("type") in ("delivered", "cancelled"):
            closed.add(e.get("id"))
            if e["type"] == "delivered":
                delivered.append(e)
    outstanding = [p for i, p in prepared.items() if i not in closed]
    return {"delivered": len(delivered), "last": max((e["delivered_at"] for e in delivered), default=None),
            "outstanding": outstanding[-1] if outstanding else None, "prepared": len(prepared)}


def gate(ns, now, d, ability, waiting, budget_block=None):
    """Why a nudge is not allowed now (a string), or None."""
    if waiting:
        return "the run waits on an approval or an answer; a nudge is never an approval and never interrupts one"
    if budget_block:
        return budget_block
    mx = cfg(d, ability, "nudge", "max_per_run")
    if ns["delivered"] >= mx:
        return "the cap of %d nudges per run is reached" % mx
    cd = cfg(d, ability, "nudge", "cooldown_seconds")
    if ns["last"] and secs(now, ns["last"]) < cd:
        return "cooldown: the last nudge was %d s ago, the minimum is %d s" % (secs(now, ns["last"]), cd)
    return None


def template(d):
    return d["nudge"]["template"]


def local_instruction(key, r, ns, d, text):
    mx = cfg(d, r["ability"], "nudge", "max_per_run")
    n = ns["delivered"] + 1
    return ["  nudge %d of %d prepared for agent %s (%d left after it). The coordinating session sends this fixed message to that agent:" % (n, mx, key, mx - n),
            "    " + text,
            "  then records it: qargi supervise delivered %s" % key,
            "  (a script cannot message a Claude Code subagent; the nudge counts only once it is delivered, and it approves nothing)"]


def cloud_instruction(sid, ns, d, text):
    mx = cfg(d, None, "nudge", "max_per_run")
    n = ns["delivered"] + 1
    return ["  nudge %d of %d prepared for session %s (%d left after it); not sent. To send this fixed message, say so and run:" % (n, mx, sid, mx - n),
            "    qargi supervise nudge %s --asked \"<your words>\"" % sid,
            "    " + text]


# ---------------------------------------------------------------- tick

class Lock:
    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.f = open(self.path, "a")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *a):
        self.f.close()


def runs_path():
    return os.path.join(STATE, "runs.json")


def load_runs():
    st = read_json(runs_path(), {})
    if not isinstance(st, dict):
        st = {}
    st.setdefault("runs", {})
    st.setdefault("offsets", {})
    return st


def tick(now, d):
    os.makedirs(STATE, mode=0o700, exist_ok=True)
    out, prepared = [], []
    nowi = iso(now)
    with Lock(runs_path() + ".lock"):
        st = load_runs()
        rows = st["runs"]
        fold_files(st, rows, set(d["waiting_notification_types"]))
        join_local(rows, now, d)
        nl = read_lines(os.path.join(STATE, "nudges.jsonl"))
        trk = read_json(os.path.join(STATE, "sessions.json"), {})
        for sid in [k for k, r in rows.items() if r["kind"] == "cloud" and k not in trk]:
            del rows[sid]
        for sid, t in sorted(trk.items()):
            if isinstance(t, dict) and sid not in rows:
                rows[sid] = blank_row(sid, "cloud")
        for key in sorted(rows):
            r = rows[key]
            if r["kind"] == "local":
                refresh_local(r)
                cls, detail = classify_local(r, now, d)
            else:
                t = trk[key]
                r["ability"] = (t.get("instance") or "").rsplit("-", 1)[-1] or None
                r["started_at"] = t.get("created")
                r["interrupt_sent_at"] = t.get("interrupt_sent_at")
                r["last_activity_at"] = t.get("last_processed_at") or t.get("last_seen")
                cls, detail = classify_cloud(t, now, d)
            ns = nudge_state(key, nl)
            r["nudges"], r["last_nudge_at"] = ns["delivered"], ns["last"]
            if cls != r["class"]:
                r["class"], r["class_since"] = cls, nowi
                r["salvage_announced"] = False
            run = r["run_id"]
            action = next_action(cls, detail, r["kind"])
            if cls in ALERT and r["announced"] != cls:
                line = "QARGI SUPERVISE %s %s %s" % (cls, run, action)
                out.append(line)
                append_line(os.path.join(STATE, "supervisor.log"), "%s %s" % (nowi, line))
                audit("supervise:" + cls, "%s %s %s" % (key, run, action), nowi)
                r["announced"] = cls
            elif cls not in ALERT:
                r["announced"] = None
            tick_nudge(key, r, cls, ns, now, nowi, d, trk.get(key) or {}, out, prepared)
        st["last_tick_at"] = nowi
        st["interval_seconds"] = int(d["tick_interval_seconds"])
        tmp = runs_path() + ".tmp"
        with open(tmp, "w") as f:
            json.dump(st, f, indent=1, sort_keys=True)
        os.chmod(tmp, 0o600)
        os.replace(tmp, runs_path())
    return out, prepared, st


def tick_nudge(key, r, cls, ns, now, nowi, d, t, out, prepared):
    """Prepare (never send) the next nudge of a stalled run, or cancel one that is no longer needed; after the nudges
    are used up and the run is still stalled, say once that it is time to salvage."""
    path = os.path.join(STATE, "nudges.jsonl")
    ab = r["ability"]
    if cls not in NUDGEABLE:
        if ns["outstanding"]:
            append_line(path, json.dumps({"type": "cancelled", "id": ns["outstanding"]["id"], "key": key, "ts": nowi}))
        return
    if ns["outstanding"]:
        return
    waiting = bool(r["waiting_on"]) if r["kind"] == "local" else False
    block = None
    if r["kind"] == "cloud" and budget_tight(t, d):
        block = "the session's budget is nearly used"
    why = gate(ns, now, d, ab, waiting, block)
    cls_age = secs(now, r["class_since"]) or 0
    if why is None and cls_age < cfg(d, ab, "nudge", "after_notify_seconds"):
        return          # notify first; the nudge waits until the stall has lasted a while after the notice
    if why is not None:
        used_up = ns["delivered"] >= cfg(d, ab, "nudge", "max_per_run") and secs(now, ns["last"]) >= cfg(d, ab, "nudge", "cooldown_seconds")
        if used_up and not r["salvage_announced"]:     # still stalled a cooldown after the last nudge
            line = "QARGI SUPERVISE %s %s salvage" % (cls, r["run_id"])
            out.append(line)
            append_line(os.path.join(STATE, "supervisor.log"), "%s %s" % (nowi, line))
            audit("supervise:salvage", "%s %s" % (key, r["run_id"]), nowi)
            r["salvage_announced"] = True
        return
    if standing_permission(d, key):
        pass            # extension point: a future standing permission may send a cloud nudge here; off today
    text = template(d)
    n = ns["delivered"] + 1
    entry = {"type": "prepared", "id": "%s#%d" % (key, n), "key": key, "kind": r["kind"], "class": cls, "target": key,
             "number": n, "ts": nowi, "template": "fixed-v1", "text": text}
    append_line(path, json.dumps(entry))
    audit("supervise:nudge-prepared", "%s nudge %d" % (key, n), nowi)
    line = "QARGI SUPERVISE %s %s nudge-prepared" % (cls, r["run_id"])
    out.append(line)
    out.extend(local_instruction(key, r, ns, d, text) if r["kind"] == "local" else cloud_instruction(key, ns, d, text))
    append_line(os.path.join(STATE, "supervisor.log"), "%s %s (%s nudge %d)" % (nowi, line, r["kind"], n))
    prepared.append(entry)


# ---------------------------------------------------------------- verbs

def parse_args(argv, flags):
    """flags: {name: takes_value}. Returns (positional, {name: value})."""
    pos, opt, i = [], {}, 0
    while i < len(argv):
        a = argv[i]
        if a in flags:
            if flags[a]:
                if i + 1 >= len(argv):
                    raise ValueError("%s needs a value" % a)
                opt[a] = argv[i + 1]
                i += 1
            else:
                opt[a] = True
        elif a.startswith("-"):
            raise ValueError("unknown option %s" % a)
        else:
            pos.append(a)
        i += 1
    return pos, opt


def get_now(opt):
    if "--now" in opt:
        n = parse(opt["--now"])
        if n is None:
            raise ValueError("--now takes an ISO time, 2026-10-30T12:00:00Z")
        return n
    return datetime.now(timezone.utc)


def cmd_tick(argv):
    pos, opt = parse_args(argv, {"--now": 1, "--json": 0})
    now, d = get_now(opt), load_defaults()
    out, prepared, st = tick(now, d)
    if "--json" in opt:
        print(json.dumps({"now": iso(now), "lines": out, "prepared": [p["id"] for p in prepared], "last_tick_at": st["last_tick_at"]}, indent=1))
    else:
        for line in out:
            print(line)
    return 0


def cmd_status(argv):
    pos, opt = parse_args(argv, {"--now": 1, "--json": 0})
    now, d = get_now(opt), load_defaults()
    st = load_runs()
    last = st.get("last_tick_at")
    interval = int(d["tick_interval_seconds"])
    warn = None
    if not last:
        warn = "no tick has run yet: nothing is supervising; run qargi supervise tick (on a timer or a loop)"
    elif secs(now, last) > 2 * interval:
        warn = "the last tick was %d minutes ago (more than twice the %d-minute interval): the supervisor may not be running" % (secs(now, last) // 60, interval // 60)
    rows = st["runs"]
    nl = read_lines(os.path.join(STATE, "nudges.jsonl"))
    counts, open_rows, waiting = {}, [], []
    for key, r in sorted(rows.items()):
        counts[r["class"]] = counts.get(r["class"], 0) + 1
        if r["class"] in ALERT or r["class"] in ("interim", "working"):
            open_rows.append((key, r))
        ns = nudge_state(key, nl)
        if ns["outstanding"]:
            waiting.append((key, r, ns))
    if "--json" in opt:
        print(json.dumps({"last_tick_at": last, "warning": warn, "classes": counts,
                          "awaiting_nudge": [k for k, _, _ in waiting], "runs": {k: r for k, r in rows.items()}}, indent=1, sort_keys=True))
        return 0
    if warn:
        print("WARNING: " + warn)
    print("qargi supervise status: last tick %s" % (last or "never"))
    print("  runs by class: " + (", ".join("%s %d" % (k or "-", v) for k, v in sorted(counts.items(), key=lambda x: str(x[0]))) or "none"))
    for key, r in open_rows:
        print("  %-22s %-20s %s" % (r["run_id"][:22], r["class"], "nudges %d" % r["nudges"] if r["nudges"] else ""))
    for key, r, ns in waiting:
        print("  nudge %d prepared for %s (%s), not yet %s" % (ns["outstanding"]["number"], key, r["class"], "delivered" if r["kind"] == "local" else "sent"))
    return 0


def cmd_delivered(argv):
    pos, opt = parse_args(argv, {"--now": 1})
    if len(pos) != 1:
        raise ValueError("usage: supervise delivered KEY (the agent id the nudge was prepared for)")
    now, d, key = get_now(opt), load_defaults(), pos[0]
    with Lock(runs_path() + ".lock"):     # serialise with the tick's reads of nudges.jsonl
        ns = nudge_state(key)
        row = load_runs()["runs"].get(key) or {}
        if not ns["outstanding"]:
            print("qargi: no prepared nudge for %s (the tick prepares one only when the caps allow)" % key, file=sys.stderr)
            return 1
        why = gate(ns, now, d, row.get("ability"), bool(row.get("waiting_on")))
        if why:
            print("qargi: refused: %s" % why, file=sys.stderr)
            return 1
        e = {"type": "delivered", "id": ns["outstanding"]["id"], "key": key, "delivered_at": iso(now), "how": "coordinator"}
        append_line(os.path.join(STATE, "nudges.jsonl"), json.dumps(e))
        audit("supervise:nudge-delivered", "%s nudge %d" % (key, ns["delivered"] + 1), iso(now))
    print("recorded nudge %d of %d for %s; the next tick counts it" % (ns["delivered"] + 1, cfg(d, row.get("ability"), "nudge", "max_per_run"), key))
    return 0


def cloud_gate(sid, now, d):
    t = read_json(os.path.join(STATE, "sessions.json"), {}).get(sid)
    if not isinstance(t, dict):
        return None, "session %s is not tracked" % sid
    if t.get("closed_at") or t.get("status") not in ("running", "idle"):
        return t, "session %s is not active (status %s)" % (sid, t.get("status"))
    block = None
    if t.get("stop_reason") == "requires_action" and t.get("status") == "idle":
        block = "the session waits on an approval (requires_action); a nudge is never an approval"
    elif t.get("stop_reason") == "budget_reached":
        block = "the session reached its budget"
    elif budget_tight(t, d):
        block = "the session's budget is nearly used"
    ns = nudge_state(sid)
    return t, gate(ns, now, d, None, False, block)


def cmd_nudge_check(argv):
    pos, opt = parse_args(argv, {"--now": 1})
    now, d = get_now(opt), load_defaults()
    if len(pos) != 1:
        raise ValueError("usage: supervise nudge SID --asked \"...\"")
    t, why = cloud_gate(pos[0], now, d)
    ns = nudge_state(pos[0])
    print(json.dumps({"ok": why is None, "reason": why, "text": template(d), "number": ns["delivered"] + 1,
                      "max": cfg(d, None, "nudge", "max_per_run")}))
    return 0


def cmd_nudge_record(argv):
    pos, opt = parse_args(argv, {"--now": 1})
    now = get_now(opt)
    with Lock(runs_path() + ".lock"):
        ns = nudge_state(pos[0])
        n = ns["delivered"] + 1
        nid = ns["outstanding"]["id"] if ns["outstanding"] else "%s#%d" % (pos[0], n)
        append_line(os.path.join(STATE, "nudges.jsonl"), json.dumps({"type": "delivered", "id": nid, "key": pos[0], "delivered_at": iso(now), "how": "supervise nudge"}))
    print(n)
    return 0


def hooks_snippet(qargi="qargi"):
    spec = [("SubagentStart", "subagent-start"), ("SubagentStop", "subagent-stop"), ("PostToolUse", "tool-use"),
            ("PostToolUseFailure", "tool-failure"), ("Notification", "notification"), ("StopFailure", "stop-failure"),
            ("PreCompact", "pre-compact")]
    return {"hooks": {ev: [{"hooks": [{"type": "command", "command": "%s hook %s" % (qargi, verb), "timeout": 5}]}] for ev, verb in spec}}


def cmd_hooks(argv):
    pos, opt = parse_args(argv, {"--qargi": 1})
    print(json.dumps(hooks_snippet(opt.get("--qargi", "qargi")), indent=2))
    print("\nMerge the \"hooks\" entries above into your Claude Code settings.json yourself (qargi never writes that file).\n"
          "Each handler records ids, times, the tool name and a hash of its input, and exits 0 at once; it reads no message or command text.", file=sys.stderr)
    return 0


def main(argv):
    if argv and argv[0] == "hook-event":
        hook_event(argv[1] if len(argv) > 1 else "")
        return 0
    verbs = {"tick": cmd_tick, "status": cmd_status, "delivered": cmd_delivered, "nudge-check": cmd_nudge_check,
             "nudge-record": cmd_nudge_record, "hooks": cmd_hooks}
    if not argv or argv[0] not in verbs:
        print("usage: qargi supervise tick|status|nudge|delivered|hooks ...", file=sys.stderr)
        return 2
    try:
        return verbs[argv[0]](argv[1:])
    except ValueError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
