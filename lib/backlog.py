#!/usr/bin/env python3
"""The backlog of a project: a markdown file the answer backlog.file names (lib/backlog.sh is the verb, lib/gitflow.sh the finish plans).

The file is read as a list of items. An item is a top-level list line (`- ` or `* ` in the first column) and the indented lines after it
(a blank line between them is part of the item when an indented line follows). An item with an id is written

    - [fix-names] Rename the two helpers that share a name
      continuation lines are indented

where the id is a lowercase slug: letters, digits and hyphens, two characters or more, beginning and ending with a letter or a digit (so
a task-list box such as `- [x] text` is no id). Any other top-level list line is an item without an id and is listed as unnumbered.
Headings, paragraphs and anything inside a fenced code block are not items.

  backlog.py list FILE [--json]        the items, a duplicated id flagged
  backlog.py plan FILE ID EVIDENCE     what `done` would do, as text (the item and the archive file it goes to)
  backlog.py token FILE ID EVIDENCE    the plan token: a hash of what the plan shows
  backlog.py apply FILE ID EVIDENCE    append the item, the date and the evidence to the archive file beside FILE
                                       (NAME-archive-YYYY-MM.md, created when absent), then remove the item from FILE
  backlog.py named FILE                read commit messages on standard input; print the ids of the open items they name, comma separated

The date is today's (local), or the day of QARGI_NOW when that is set (tests). Exit 1 with a message on standard error for anything it
cannot do; nothing is written then.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import date

ID_FORM = re.compile(r"^\[([a-z0-9][a-z0-9-]*[a-z0-9])\] +(\S.*)$")
FENCE = re.compile(r"^\s*(```|~~~)")
MARKER = re.compile(r"^[-*] +(\S.*)$")


class BacklogError(Exception):
    pass


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().split("\n")
    except OSError as e:
        raise BacklogError("cannot read %s: %s" % (path, e.strerror or e))
    except UnicodeDecodeError:
        raise BacklogError("%s is not UTF-8 text" % path)


def parse(lines):
    """The items of a file's lines: dicts with id (or None), line (1-based), start and end (slice of lines), text (the first line, without
    the id form) and full (all the item's lines, as written)."""
    items, fenced, i, n = [], False, 0, len(lines)
    while i < n:
        ln = lines[i]
        if FENCE.match(ln):
            fenced = not fenced
            i += 1
            continue
        m = None if fenced else MARKER.match(ln)
        if not m:
            i += 1
            continue
        start, end, j = i, i + 1, i + 1
        while j < n:
            nxt = lines[j]
            if FENCE.match(nxt) and nxt[:1] in " \t":
                fenced = not fenced
                end = j + 1
            elif nxt.strip() == "":
                pass
            elif nxt[:1] in " \t":
                end = j + 1
            else:
                break
            j += 1
        body = m.group(1).rstrip()
        idm = ID_FORM.match(body)
        items.append({"id": idm.group(1) if idm else None, "line": start + 1, "start": start, "end": end,
                      "text": (idm.group(2) if idm else body).rstrip(), "full": lines[start:end]})
        i = end
    return items


def duplicates(items):
    seen, dup = {}, []
    for it in items:
        if it["id"] is None:
            continue
        seen.setdefault(it["id"], []).append(it["line"])
    for k, v in seen.items():
        if len(v) > 1:
            dup.append(k)
    return dup, seen


def archive_path(path):
    real = os.path.realpath(path)
    d, name = os.path.split(real)
    stem = name[:-3] if name.endswith(".md") and len(name) > 3 else name
    return os.path.join(d, "%s-archive-%s.md" % (stem, today().strftime("%Y-%m")))


def today():
    now = os.environ.get("QARGI_NOW", "")
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", now)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    return date.today()


def pick(path, ident):
    """The one item with this id; BacklogError for an id that is no slug, is not there, or is used twice."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", ident):
        raise BacklogError("ID: a lowercase slug of letters, digits and hyphens, two characters or more (got %r)" % ident)
    lines = read_lines(path)
    items = parse(lines)
    hits = [it for it in items if it["id"] == ident]
    if not hits:
        raise BacklogError("no open item [%s] in %s (qargi backlog list shows them)" % (ident, path))
    if len(hits) > 1:
        raise BacklogError("the id [%s] is used by %d items (lines %s) in %s: make the ids unique first" % (ident, len(hits), ", ".join(str(h["line"]) for h in hits), path))
    return lines, hits[0]


def clean_evidence(evidence):
    ev = evidence.strip()
    if not ev:
        raise BacklogError("--evidence needs the words that show the item is done")
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in ev):
        raise BacklogError("--evidence: no control characters")
    return ev


def entry_text(item, evidence, day):
    ev = evidence.replace("\n", "\n  ")
    return "### %s: %s\n\n%s\n\nEvidence: %s\n" % (day.isoformat(), item["id"], "\n".join(item["full"]), ev)


def cmd_list(path, as_json):
    items = parse(read_lines(path))
    dup, seen = duplicates(items)
    if as_json:
        print(json.dumps({"file": path, "items": [{"id": it["id"], "line": it["line"], "text": it["text"], "full": "\n".join(it["full"]),
                                                   "duplicate": it["id"] in dup} for it in items], "duplicates": dup}, indent=2))
        return 0
    if not items:
        print("%s: no open items" % path)
        return 0
    print("%s: %d open item%s" % (path, len(items), "" if len(items) == 1 else "s"))
    width = max([len(it["id"]) for it in items if it["id"]] + [1])
    for it in items:
        flag = "   (duplicate id: lines %s)" % ", ".join(str(x) for x in seen[it["id"]]) if it["id"] in dup else ""
        print("  %-*s  %s%s" % (width, it["id"] or "-", it["text"], flag))
    if any(it["id"] is None for it in items):
        print("(%d without an id, shown as -: write them as '- [some-id] text' to name them)" % sum(1 for it in items if it["id"] is None))
    if dup:
        print("duplicate ids: %s (done refuses an id used twice)" % ", ".join(dup))
    return 0


def cmd_plan(path, ident, evidence):
    ev = clean_evidence(evidence)
    _, item = pick(path, ident)
    arch = archive_path(path)
    out = ["done [%s]: move this item out of %s into %s (appended; the file is created when absent), then remove it from the backlog" % (ident, path, arch)]
    out += ["  | " + ln for ln in item["full"]]
    out.append("  evidence: %s" % ev.replace("\n", "\n            "))
    out.append("  dated %s" % today().isoformat())
    print("\n".join(out))
    return 0


def plan_token(path, ident, evidence):
    ev = clean_evidence(evidence)
    _, item = pick(path, ident)
    material = "\n".join([os.path.realpath(path), archive_path(path), ident, "\n".join(item["full"]), ev]) + "\n"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:12]


def write_atomic(path, text):
    real = os.path.realpath(path)
    fd, tmp = tempfile.mkstemp(prefix=".backlog.", dir=os.path.dirname(real))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, os.stat(real).st_mode & 0o7777)
        os.replace(tmp, real)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def cmd_apply(path, ident, evidence):
    ev = clean_evidence(evidence)
    lines, item = pick(path, ident)
    arch = archive_path(path)
    day = today()
    entry = entry_text(item, ev, day)
    existing = ""
    if os.path.exists(arch):
        with open(arch, encoding="utf-8") as f:
            existing = f.read()
    head = "" if existing else "# %s archive %s\n\n" % (os.path.basename(arch)[:-len("-archive-YYYY-MM.md")], day.strftime("%Y-%m"))
    sep = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    with open(arch, "a", encoding="utf-8") as f:   # the archive first: an interruption then leaves the item in both files, never in neither
        f.write(head + sep + entry)
        f.flush()
        os.fsync(f.fileno())
    rest = lines[:item["start"]] + lines[item["end"]:]
    k = item["start"]
    if 0 < k < len(rest) and rest[k - 1].strip() == "" and rest[k].strip() == "":   # the item stood between two blank lines: keep one
        del rest[k]
    write_atomic(path, "\n".join(rest))
    print("done [%s]: moved to %s and removed from %s" % (ident, arch, path))
    return 0


def cmd_named(path):
    msgs = sys.stdin.read()
    names = []
    for it in parse(read_lines(path)):
        ident = it["id"]
        if ident and ident not in names and re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(ident), msgs):
            names.append(ident)
    if names:
        print(", ".join(names))
    return 0


def main(argv):
    try:
        cmd, rest = (argv[0] if argv else ""), argv[1:]
        if cmd == "list" and len(rest) in (1, 2) and (len(rest) == 1 or rest[1] == "--json"):
            return cmd_list(rest[0], len(rest) == 2)
        if cmd in ("plan", "apply", "token") and len(rest) == 3:
            if cmd == "token":
                print(plan_token(*rest))
                return 0
            return (cmd_plan if cmd == "plan" else cmd_apply)(*rest)
        if cmd == "named" and len(rest) == 1:
            return cmd_named(rest[0])
        print(__doc__, file=sys.stderr)
        return 2
    except BacklogError as e:
        print("qargi: %s" % e, file=sys.stderr)
        return 1
    except OSError as e:
        print("qargi: backlog: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
