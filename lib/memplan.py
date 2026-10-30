#!/usr/bin/env python3
"""Memory planning: split, merge, copy and migrate, as pure functions from stores to steps.

A store is a mapping {path: {id, path, content, content_sha256}} (what a backend lists, what canon.py reads).
Every function returns a plan: {"target": {"ops", "expect"}, "source": {...}, "notes": [...]}, where ops are
the steps canon.py already uses (create, update, marker, move) plus archive, and expect maps each path the
plan consulted to the digest it had (None: it did not exist). apply_plan hands each store's steps to
membackend.apply_ops, which refuses a store whose notes no longer match. A note the target cannot hold (a
name starting with a dot, too many path segments, too large) makes the plan itself refuse, naming the path.

Nothing is ever deleted. What a split moves out of a store goes to /_archive/<date>/<path>; a collision on a
merge goes to /_conflicts/<date>/<path>, as the reconciler does. Both record the origin by appending a segment
to the first `Sources:` line of the note's header block (or adding the line after the title). A segment ends
`@<12 hex>`, the digest of the note as it was before the segment was added; only a segment whose digest matches
the text it was taken from is ours (core, full, origin), so a hand-written look-alike is just text. core()
takes one segment off again, which restores an archived note byte for byte. A note with no `Sources:` line gets
`Sources: origin not recorded (qargi memory); <segment>`; a note whose own line is exactly that placeholder text gets
the segment appended like any other. Undoing tells them apart by the digest alone (the placeholder line is dropped
when the text without it has the digest, kept when the text with it has), so the format has no flag for it and notes
written by any earlier release restore the same way.

For a later port, typed links or a link-rewriting step, the contract this module keeps:
- The origin segment encodes paths and labels by percent-encoding every byte except A-Za-z0-9 - . _ ~ and /
  (a label also encodes /); `; copied from LABEL:PATH@HEX12` or `; archived from PATH@HEX12 on YYYY-MM-DD`.
- The plan token is the first 12 hex digits of sha256 over `jq -S -c .` of the plan file (sorted keys, compact),
  so any change in an op, in what was read (expect), in a note or in the date changes it.
- A collision renames x.md to /_conflicts/<date>/x.md, then x.md.2, x.md.3 for further ones, and an archive
  rewrites a path to /_archive/<date>/<path>[.N]. These are the only two places where a note's path changes in
  a split or merge, so a step that rewrites links between notes has to hook there (and in the restore move).
- DirBackend ids are derived from path and content, so they change with every edit; the cloud's ids are stable.
  Steps therefore name notes by path and digest, never by id.

CLI (qargi memory split|merge|copy runs these; the approval gate is in memory.sh):
  memplan.py plan  VERB --source REF --target REF [--prefix P]... [--role R] [--note-kind K] [--archive] [--policy P] --out FILE
  memplan.py show  FILE
  memplan.py apply FILE
"""
import argparse, datetime, json, os, re, sys
from urllib.parse import quote, unquote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import canon as C  # noqa: E402
import membackend as B  # noqa: E402

POLICIES = ("conflicts", "keep")
NO_SOURCE = "origin not recorded (qargi memory)"      # the Sources: value of a note that had no such line
SEGMENT = re.compile(r"; (copied|archived) from ([^;\s]+)@([0-9a-f]{12})(?: on \d{4}-\d{2}-\d{2})?(\r?)$")


class PlanRefused(ValueError):
    """A note the plan would write cannot be stored where it would go."""


def today_utc():
    return datetime.datetime.now(datetime.timezone.utc).date().isoformat()


def q(s):
    return quote(s, safe="/")


def _header(L):
    """(title index or -1, first and one past the last line of the header block): the lines after the title (and the blank
    line that follows it) up to the next blank line. Only there is a Sources: line the note's own."""
    skip = C.fenced(L)
    t = next((j for j, l in enumerate(L) if l.startswith("# ") and j not in skip), -1)
    i = t + 1
    while i < len(L) and not L[i].strip():
        i += 1
    e = i
    while e < len(L) and L[e].strip():
        e += 1
    return t, i, e, skip


def _sources_line(L):
    t, i, e, skip = _header(L)
    return next((j for j in range(i, e) if L[j].startswith("Sources:") and j not in skip), None)


def add_origin(content, segment):
    """Record where a note came from: append `; segment` to its Sources: line, or add a Sources: line after the title."""
    L = content.split("\n")
    i = _sources_line(L)
    if i is None:
        t = _header(L)[0]
        cr = "\r" if L[t if t >= 0 else 0].endswith("\r") else ""     # the line the new one sits beside decides
        L.insert(t + 1, "Sources: %s; %s" % (NO_SOURCE, segment) + cr)
    else:
        cr = "\r" if L[i].endswith("\r") else ""
        L[i] = L[i][:len(L[i]) - len(cr)] + "; " + segment + cr
    return "\n".join(L)


def _strip(content):
    """(text without the last origin segment, how, reference) when that segment is ours: its digest is that of the
    text it was taken from. None otherwise (no segment, or one somebody wrote). When what is left of the Sources: line
    is only the placeholder, the line may be one add_origin inserted (the note had none) or the note's own (it says
    the same words): the digest tells which, because it is that of the note as it was, so the text with the line
    dropped and the text with it kept are tried and only the one that matches is returned."""
    L = content.split("\n")
    i = _sources_line(L)
    m = SEGMENT.search(L[i]) if i is not None else None
    if not m:
        return None
    L[i] = L[i][:m.start()] + m.group(4)
    kept = "\n".join(L)
    texts = [kept]
    if L[i].rstrip("\r") == "Sources: " + NO_SOURCE:
        del L[i]
        texts.append("\n".join(L))
    text = next((t for t in texts if B.digest(t)[:12] == m.group(3)), None)
    return (text, m.group(1), m.group(2)) if text is not None else None


def core(content):
    """The note without the last origin segment add_origin put on it (unchanged when there is none)."""
    r = _strip(content)
    return r[0] if r else content


def full(content):
    """The note without any origin segment of ours."""
    while True:
        r = _strip(content)
        if not r:
            return content
        content = r[0]


def origin(content):
    """(how, path) of the last origin segment of ours: how is copied or archived, path where the note was."""
    r = _strip(content)
    if not r:
        return None, None
    return r[1], unquote(r[2].split(":", 1)[1] if r[1] == "copied" else r[2])


def same(a, b):
    """The same note, whatever origin each carries."""
    return a == b or full(a) == full(b)


def d(m):
    return B.digest(m["content"])


def copied(label, p, content):
    """content with the segment saying it was copied from label:p. A note that already carries our segment for
    this very label and path gets it replaced, not a second one, so copying the same note again does not grow the line."""
    ref = "%s:%s" % (quote(label, safe=""), q(p))
    r = _strip(content)
    if r and r[1] == "copied" and r[2] == ref:
        content = r[0]
    return add_origin(content, "copied from %s@%s" % (ref, B.digest(content)[:12]))


def select(store, sel, require=False):
    """Paths picked by a selector {prefix: [..], role: R, kind: K}: all given criteria must hold (a path
    matches any prefix). /CANON.md (a store's own marker) is never picked, and /_archive/ only by a prefix that
    names it."""
    sel = {k: v for k, v in (sel or {}).items() if v}
    if require and not sel:
        raise ValueError("a selector is needed: a path prefix, a role or a Kind:")
    named = any(x.rstrip("/") == B.ARCHIVE.rstrip("/") or x.startswith(B.ARCHIVE) for x in sel.get("prefix", []))
    out = []
    for p, m in sorted(store.items()):
        if p == "/CANON.md" or (p.startswith(B.ARCHIVE) and not named):
            continue
        if "prefix" in sel and not any(p == x or p.startswith(x.rstrip("/") + "/") for x in sel["prefix"]):
            continue
        if "role" in sel and not p.startswith("/roles/%s/" % sel["role"]):
            continue
        if "kind" in sel and C.note_fields(m["content"]).get("Kind") != sel["kind"]:
            continue
        out.append(p)
    return out


def _refuse(refused, fits, path, content):
    why = fits(path, content) if fits else B.path_problem(path)
    if why:
        refused.append("%s (%s)" % (path, why))


def merge(a, b, policy="conflicts", today=None, label="source", only=None, fits=None):
    """The union of two stores as steps on a (b is only read). A path in both with the same note is left;
    with different content the incoming note goes to /_conflicts/<date>/<path> (policy conflicts) or is
    reported and left out (keep). A note whose original sits in a's archive is moved back from it, so
    merging a split's target undoes the split. Everything copied in records its origin in Sources:.
    only: the paths of b to consider (default all but /CANON.md and b's /_archive/, which are reported).
    fits(path, content) -> why the target cannot hold it, or None; a plan that would write such a note raises
    PlanRefused naming every path. -> plan with a "target" and the digests read of b"""
    if policy not in POLICIES:
        raise ValueError("policy is one of %s" % ", ".join(POLICIES))
    today = today or today_utc()
    ops, expect, notes, read, refused = [], {}, [], {}, []
    taken = set(a)
    arch = {}
    for p, m in a.items():
        how, op = origin(m["content"])
        if p.startswith(B.ARCHIVE) and how == "archived":
            arch.setdefault(op, []).append(p)
    paths = sorted(b if only is None else only)
    if only is None:
        skipped = [p for p in paths if p.startswith(B.ARCHIVE)]
        paths = [p for p in paths if p not in skipped]
        if skipped:
            notes.append("not copied: %d note(s) under /_archive/ (history of the other store; copy --prefix /_archive/ picks them)" % len(skipped))
    for p in paths:
        if p == "/CANON.md":
            notes.append("not copied: /CANON.md (a store keeps its own marker)")
            continue
        c = b[p]["content"]
        read[p] = d(b[p])
        if p in a:
            expect[p] = d(a[p])
            if same(a[p]["content"], c):
                continue
            if policy == "keep":
                notes.append("kept %s: the other store's version differs" % p)
                continue
            base, dest, n = "/_conflicts/%s%s" % (today, p), None, 1
            while dest is None:
                cand = base if n == 1 else "%s.%d" % (base, n)
                if cand in a:
                    expect[cand] = d(a[cand])
                    if same(a[cand]["content"], c):
                        break                              # an earlier run put it there
                elif cand not in taken:
                    expect[cand] = None
                    dest = cand
                n += 1
            if dest is None:
                continue
            taken.add(dest)
            out = copied(label, p, c)
            _refuse(refused, fits, dest, out)
            ops.append({"op": "create", "path": dest, "content": out})
            notes.append("conflict: %s exists with different content; the incoming note goes to %s" % (p, dest))
            continue
        expect[p] = None
        back = next((x for x in sorted(arch.get(p, []), reverse=True) if full(a[x]["content"]) == full(c)), None)
        if back:
            expect[back] = d(a[back])
            _refuse(refused, fits, p, core(a[back]["content"]))
            ops.append({"op": "move", "from": back, "to": p, "sha": d(a[back]), "content": core(a[back]["content"])})
            notes.append("restored %s from %s" % (p, back))
            arch[p].remove(back)
        else:
            out = copied(label, p, c)
            _refuse(refused, fits, p, out)
            ops.append({"op": "create", "path": p, "content": out})
        taken.add(p)
    if refused:
        raise PlanRefused("refused, the target cannot hold: " + "; ".join(refused) + " (pick other notes with --prefix, --role or --note-kind)")
    return {"target": {"ops": ops, "expect": expect}, "read": read, "notes": notes}


def copy(store, target, selector=None, policy="conflicts", today=None, label="source", fits=None):
    """Copy the notes a selector picks (all by default) into target; the source is only read."""
    sel = select(store, selector)
    plan = merge(target, store, policy, today, label, sel, fits)
    plan["source"] = {"ops": [], "expect": plan.pop("read")}
    return plan


def split(store, selector, target, move=False, today=None, label="source", fits=None, src_fits=None):
    """Copy what a selector picks into target and, with move, archive the originals in store
    (/_archive/<date>/<path>, origin recorded in Sources:). A split is copy with a required selector.
    src_fits is the source's own limits for the archive paths, which are longer than the originals."""
    today = today or today_utc()
    sel = select(store, selector, require=True)
    plan = copy(store, target, selector, "conflicts", today, label, fits)
    if move:
        ops, taken, refused = [], set(store), []
        for p in sel:
            base, dest, n = "/_archive/%s%s" % (today, p), None, 1
            while dest is None:
                cand = base if n == 1 else "%s.%d" % (base, n)
                if cand not in taken:
                    dest = cand
                n += 1
            taken.add(dest)
            plan["source"]["expect"][dest] = None
            out = add_origin(store[p]["content"], "archived from %s@%s on %s" % (q(p), d(store[p])[:12], today))
            _refuse(refused, src_fits, dest, out)
            ops.append({"op": "archive", "from": p, "to": dest, "sha": d(store[p]), "content": out})
        if refused:
            raise PlanRefused("refused, the source cannot hold the archive paths: " + "; ".join(refused))
        plan["source"]["ops"] = ops
    return plan


def migrate(store, to_version, kind, project, roles, default_role, seed, today=None):
    """The canon's own plan for a store (canon.make_plan), with the digests it was computed from.
    Only the current canon version is a target. -> plan with a "target" (the store itself) and notes"""
    if to_version != C.LATEST:
        raise ValueError("this qargi migrates to canon %d only" % C.LATEST)
    today = today or today_utc()
    p = C.make_plan(kind, store, project, roles, default_role, seed, today)
    byid = {m["id"]: path for path, m in store.items() if m.get("id")}
    expect, ops = {}, []
    for op in p["ops"]:
        op = dict(op)
        for path in (op.get("from"), op.get("path"), op.get("to")):
            if path:
                expect.setdefault(path, d(store[path]) if path in store else None)
        if op.get("sha") is not None:
            if op.get("id") in byid:
                op["sha"] = d(store[byid[op["id"]]])
            else:
                del op["sha"]
        ops.append(op)
    return {"target": {"ops": ops, "expect": expect}, "notes": p["notes"], "from_version": p["from_version"], "to_version": p["to_version"]}


def apply_plan(plan, backends, dry_run=True):
    """Run a plan against {"source": backend, "target": backend}. Every store is checked before any is changed
    (a store whose notes differ from what the plan read raises StaleError); the target is written first, so an
    interrupted split leaves copies and a plan made again finishes it. -> descriptions of the steps"""
    steps = [(k, plan[k]) for k in ("target", "source") if plan.get(k) and k in backends]
    for k, s in steps:
        B.apply_ops(backends[k], s["ops"], s["expect"], True)
    done = []
    for k, s in steps:
        done += ["%s: %s" % (k, x) for x in B.apply_ops(backends[k], s["ops"], s["expect"], dry_run)]
    return done


def load(backend):
    return backend.list()


def show(plan):
    out = []
    for k in ("target", "source"):
        s = plan.get(k)
        if not s or not s["ops"]:
            continue
        out.append("%s store:" % k)
        for op in s["ops"]:
            if op["op"] in ("move", "archive"):
                out.append("  %-7s %s -> %s" % (op["op"], op["from"], op["to"]))
            else:
                out.append("  %-7s %s  (%d chars)" % (op["op"], op["path"], len(op["content"])))
    out += ["  note: " + n for n in plan["notes"]]
    if not any(plan.get(k) and plan[k]["ops"] for k in ("target", "source")):
        out.append("nothing to do")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("plan")
    s.add_argument("verb", choices=["split", "merge", "copy"])
    s.add_argument("--source", required=True)
    s.add_argument("--target", required=True)
    s.add_argument("--prefix", action="append", default=[])
    s.add_argument("--role")
    s.add_argument("--note-kind")
    s.add_argument("--archive", action="store_true")
    s.add_argument("--policy", default="conflicts")
    s.add_argument("--today")
    s.add_argument("--out", required=True)
    for n in ("show", "apply"):
        sub.add_parser(n).add_argument("file")
    a = ap.parse_args()
    try:
        if a.cmd == "plan":
            src, dst = B.open_store(a.source, write=a.archive), B.open_store(a.target, write=True)
            if os.path.realpath(a.source) == os.path.realpath(a.target):
                raise ValueError("the source and the target are the same store")
            sel = {"prefix": a.prefix, "role": a.role, "kind": a.note_kind}
            if a.verb == "merge":
                if any(sel.values()) or a.archive:
                    raise ValueError("merge takes the whole store; use copy or split to pick notes")
                plan = merge(dst.list(), src.list(), a.policy, a.today, src.label, None, dst.refusal)
                plan["source"] = {"ops": [], "expect": plan.pop("read")}
            elif a.verb == "copy":
                if a.archive:
                    raise ValueError("copy never changes the source; use split --archive")
                plan = copy(src.list(), dst.list(), sel, a.policy, a.today, src.label, dst.refusal)
            else:
                plan = split(src.list(), sel, dst.list(), a.archive, a.today, src.label, dst.refusal, src.refusal)
            plan.update(verb=a.verb, stores={"source": a.source, "target": a.target})
            with open(a.out, "w") as f:
                json.dump(plan, f, sort_keys=True)
        else:
            with open(a.file) as f:
                plan = json.load(f)
            if a.cmd == "show":
                print("%s %s -> %s" % (plan["verb"], plan["stores"]["source"], plan["stores"]["target"]))
                print(show(plan))
            else:
                backends = {k: B.open_store(v, write=bool(plan.get(k) and plan[k]["ops"])) for k, v in plan["stores"].items()}
                done = apply_plan(plan, backends, dry_run=False)
                print("applied %d step(s)" % len(done))
    except (B.StoreError, ValueError, OSError) as x:
        print("qargi: %s" % x, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
