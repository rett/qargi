#!/usr/bin/env python3
"""qargi noticed: the things members saw and did not act on (noticed_not_acted_on in a manifest), each with a
disposition. Raw events go to the append-only $QARGI_STATE/events.jsonl; a disposition is a later event that names the
note, so nothing is rewritten. Notes are agent-written text: they are stored short, with secret-looking strings
redacted, and are shown only by `list`; `qargi report` shows counts and ages.

Usage: noticed.py ingest SID DIR            (collect.sh calls it; reads DIR/manifest.json and DIR/*/manifest.json)
       noticed.py list [--all]              open notes, oldest first (--all: every note with its disposition)
       noticed.py resolve ID DISPOSITION [--why CODE]
DISPOSITION is followup, dismissed (needs --why CODE), accepted or superseded."""
import hashlib, json, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths as P  # noqa: E402

DISPOSITIONS = ("followup", "dismissed", "accepted", "superseded")
MAXLEN = 300
SECRET = re.compile(r"(sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{12,}|[A-Za-z0-9+/_-]{40,}={0,2})")


def events_path():
    return os.path.join(P.state(), "events.jsonl")


def reasons():
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "reasons.json")) as f:
        return json.load(f)["codes"]


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def clean(text):
    t = " ".join(str(text).split())
    t = SECRET.sub("[redacted]", t)
    return t if len(t) <= MAXLEN else t[:MAXLEN - 1] + "…"


def read_events(path=None):
    out = []
    try:
        with open(path or events_path()) as f:
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


def append(event):
    path = events_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(event, sort_keys=True) + "\n").encode())   # one write: appends do not interleave
    finally:
        os.close(fd)


def fold(events):
    """{id: note} where note has ts, session, member, text, disposition (open until resolved), why, resolved_at."""
    notes = {}
    for e in events:
        if e.get("kind") == "noticed" and e.get("id"):
            notes.setdefault(e["id"], {"id": e["id"], "ts": e.get("ts"), "session": e.get("session"), "member": e.get("member") or "",
                                       "text": e.get("text") or "", "disposition": "open", "why": None, "resolved_at": None})
        elif e.get("kind") == "noticed_disposition" and e.get("id") in notes:
            n = notes[e["id"]]
            n.update(disposition=e.get("disposition") or "open", why=e.get("why"), resolved_at=e.get("ts"))
    return notes


def summary(events, now_dt):
    """Counts for the report: open notes with the age of the oldest, and the dispositions given. No text."""
    notes = fold(events).values()
    ages = []
    for n in notes:
        if n["disposition"] == "open":
            try:
                t = datetime.strptime(n["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
                ages.append(max(0, int((now_dt - t).total_seconds())))
            except (TypeError, ValueError):
                pass
    done = {}
    for n in notes:
        if n["disposition"] != "open":
            done[n["disposition"]] = done.get(n["disposition"], 0) + 1
    return {"open": sum(1 for n in notes if n["disposition"] == "open"), "oldest_open_seconds": max(ages) if ages else None, "resolved": done}


def manifests(d):
    out = []
    if os.path.isfile(os.path.join(d, "manifest.json")):
        out.append(("", os.path.join(d, "manifest.json")))
    try:
        for sub in sorted(os.listdir(d)):
            m = os.path.join(d, sub, "manifest.json")
            if os.path.isfile(m):
                out.append((sub, m))
    except OSError:
        pass
    return out


def ingest(sid, d):
    seen = set(fold(read_events()))
    added = 0
    for member, m in manifests(d):
        try:
            with open(m) as f:
                items = (json.load(f) or {}).get("noticed_not_acted_on") or []
        except (OSError, ValueError, AttributeError):
            continue
        if not isinstance(items, list):
            continue
        for it in items:
            text = clean(it if isinstance(it, str) else json.dumps(it, sort_keys=True))
            if not text:
                continue
            nid = hashlib.sha256(("%s\0%s\0%s" % (sid, member, text)).encode()).hexdigest()[:10]
            if nid in seen:
                continue
            seen.add(nid)
            append({"kind": "noticed", "id": nid, "ts": now(), "session": sid, "member": member, "text": text})
            added += 1
    print("noticed: %d new note(s) recorded" % added if added else "noticed: nothing new")
    return 0


def main(argv):
    if not argv:
        print("usage: qargi noticed list [--all] | resolve ID followup|dismissed|accepted|superseded [--why CODE]", file=sys.stderr)
        return 2
    verb, rest = argv[0], argv[1:]
    if verb == "ingest" and len(rest) == 2:
        return ingest(rest[0], rest[1])
    if verb == "list":
        if rest not in ([], ["--all"]):
            print("qargi: usage: qargi noticed list [--all]", file=sys.stderr)
            return 2
        notes = sorted(fold(read_events()).values(), key=lambda n: n["ts"] or "")
        shown = [n for n in notes if rest or n["disposition"] == "open"]
        for n in shown:
            print("%s  %s  %-10s %s%s  %s" % (n["id"], n["ts"], n["disposition"], n["session"] or "-", ("/" + n["member"]) if n["member"] else "", n["text"]))
        if not shown:
            print("no open notes" if not rest else "no notes")
        return 0
    if verb == "resolve":
        why = None
        args = []
        i = 0
        while i < len(rest):
            if rest[i] == "--why" and i + 1 < len(rest):
                why = rest[i + 1]
                i += 2
            else:
                args.append(rest[i])
                i += 1
        if len(args) != 2:
            print("qargi: usage: qargi noticed resolve ID followup|dismissed|accepted|superseded [--why CODE]", file=sys.stderr)
            return 2
        nid, disp = args
        if disp not in DISPOSITIONS:
            print("qargi: a disposition is one of %s" % ", ".join(DISPOSITIONS), file=sys.stderr)
            return 2
        if disp == "dismissed" and why is None:
            print("qargi: dismissing a note needs --why CODE (%s)" % ", ".join(reasons()), file=sys.stderr)
            return 2
        if why is not None and why not in reasons():
            print("qargi: --why is one of %s" % ", ".join(reasons()), file=sys.stderr)
            return 2
        if nid not in fold(read_events()):
            print("qargi: no note %s (qargi noticed list --all)" % nid, file=sys.stderr)
            return 1
        append({"kind": "noticed_disposition", "id": nid, "ts": now(), "disposition": disp, "why": why})
        print("note %s: %s%s" % (nid, disp, " (%s)" % why if why else ""))
        return 0
    print("qargi: usage: qargi noticed list [--all] | resolve ID DISPOSITION [--why CODE]", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
