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
  backlog.py plan FILE IDS EVIDENCE    what `done` would do, as text (the item and the archive file it goes to)
  backlog.py token FILE IDS EVIDENCE   the plan token: a hash of what the plan shows
  backlog.py apply FILE IDS EVIDENCE   append the item, the date and the evidence to the archive file beside FILE
                                       (NAME-archive-YYYY-MM.md, created when absent), then remove the item from FILE
  backlog.py add FILE ID TEXT [DETAIL] append the item `- [ID] TEXT` (DETAIL as indented lines) at the end of the list (of the section, with --section);
                                       an id that is no slug, or is taken anywhere in the file, is refused
  backlog.py named FILE                read commit messages on standard input; print the ids of the open items they name, comma separated

IDS is one id, or several joined by commas (a batch: one plan, one token, the same evidence archived with each item, all in one write of each file).

Two options, given anywhere after the verb (the verb's script reads them from the project's answers backlog.archive and backlog.section):
  --section HEADING    only the list under the heading HEADING holds items: from that heading to the next heading of the same or a higher
                       level (a deeper heading and what follows it belong to the section). HEADING is the heading's text, with or without
                       the leading #s (a heading is a line of 1 to 6 #s, a space and the text, outside a code fence). A file with no such
                       heading is an error for every verb but named, which prints nothing
  --archive PATH       an absolute path: a name ending in .md is the one archive file (all months, appended); anything else is a directory
                       (created when absent) that receives NAME-archive-YYYY-MM.md. Without it the archive is beside FILE

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
HEADING = re.compile(r"^(#{1,6})[ \t]+(.*?)(?:[ \t]+#+)?[ \t]*$")
OPTS = {"section": None, "archive": None}   # --section and --archive of the call (main sets them; the functions below read them)
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


def heading_text(section):
    """The text of a section name given with or without its leading #s."""
    return re.sub(r"^#{1,6}(?:[ \t]+|$)", "", section.strip()).strip()


def section_range(lines, section):
    """The slice (lo, hi) of line indexes under the first heading whose text is SECTION, up to the next heading of the same or a higher
    level; BacklogError when there is none. Headings inside a code fence are none."""
    want, fenced, found = heading_text(section), False, None
    for i, ln in enumerate(lines):
        if FENCE.match(ln):
            fenced = not fenced
            continue
        m = None if fenced else HEADING.match(ln)
        if not m:
            continue
        if found is not None and len(m.group(1)) <= found[1]:
            return found[0], i
        if found is None and m.group(2) == want:
            found = (i + 1, len(m.group(1)))
    if found is None:
        raise BacklogError("no heading '%s' in the backlog file (backlog.section)" % want)
    return found[0], len(lines)


def parse(lines, section=None):
    """The items of a file's lines: dicts with id (or None), line (1-based), start and end (slice of lines), text (the first line, without
    the id form) and full (all the item's lines, as written). With a section only the list under that heading holds items."""
    lo, hi = section_range(lines, section) if section else (0, len(lines))
    items, fenced, i, n = [], False, 0, len(lines)
    while i < n:
        ln = lines[i]
        if FENCE.match(ln):
            fenced = not fenced
            i += 1
            continue
        m = None if fenced or not lo <= i < hi else MARKER.match(ln)
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
    if OPTS["archive"]:
        a = os.path.abspath(OPTS["archive"])
        if a.endswith(".md"):
            return a
        d = a
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
    items = parse(lines, OPTS["section"])
    hits = [it for it in items if it["id"] == ident]
    if not hits:
        raise BacklogError("no open item [%s] in %s (qargi backlog list shows them)" % (ident, path))
    if len(hits) > 1:
        raise BacklogError("the id [%s] is used by %d items (lines %s) in %s: make the ids unique first" % (ident, len(hits), ", ".join(str(h["line"]) for h in hits), path))
    return lines, hits[0]


def pick_all(path, idents):
    """The items named by IDENTS (ids joined by commas, in that order) and the file's lines; BacklogError for an id that pick refuses, and for an id named twice."""
    names = idents.split(",")
    if len(set(names)) != len(names):
        raise BacklogError("the id [%s] is named more than once" % next(n for n in names if names.count(n) > 1))
    lines, found = None, []
    for n in names:
        lines, it = pick(path, n)
        found.append(it)
    return lines, found


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
    items = parse(read_lines(path), OPTS["section"])
    dup, seen = duplicates(items)
    if as_json:
        print(json.dumps({"file": path, "section": OPTS["section"], "items": [{"id": it["id"], "line": it["line"], "text": it["text"], "full": "\n".join(it["full"]),
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
    _, found = pick_all(path, ident)
    arch = archive_path(path)
    if len(found) == 1:
        out = ["done [%s]: move this item out of %s into %s (appended; the file is created when absent), then remove it from the backlog" % (ident, path, arch)]
        out += ["  | " + ln for ln in found[0]["full"]]
    else:
        out = ["done %d items (%s): move them out of %s into %s (appended; the file is created when absent), then remove them from the backlog" % (
            len(found), ", ".join("[%s]" % it["id"] for it in found), path, arch)]
        for it in found:
            out.append("  [%s]" % it["id"])
            out += ["  | " + ln for ln in it["full"]]
    out.append("  evidence: %s" % ev.replace("\n", "\n            "))
    out.append("  dated %s%s" % (today().isoformat(), "" if len(found) == 1 else " (the same evidence is archived with each item)"))
    print("\n".join(out))
    return 0


def plan_token(path, ident, evidence):
    ev = clean_evidence(evidence)
    _, found = pick_all(path, ident)
    parts = [os.path.realpath(path), archive_path(path)]
    for it in found:
        parts += [it["id"], "\n".join(it["full"])]
    material = "\n".join(parts + [ev]) + "\n"
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
    lines, found = pick_all(path, ident)
    arch = archive_path(path)
    day = today()
    entry = "\n".join(entry_text(it, ev, day) for it in found)
    existing = ""
    if os.path.exists(arch):
        with open(arch, encoding="utf-8") as f:
            existing = f.read()
    base = os.path.basename(arch)
    named = re.match(r"(.*)-archive-\d{4}-\d{2}\.md$", base)   # the monthly file; an archive file of its own name is titled by that name
    title = "%s archive %s" % (named.group(1), day.strftime("%Y-%m")) if named else re.sub(r"\.md$", "", base)
    head = "" if existing else "# %s\n\n" % title
    os.makedirs(os.path.dirname(arch), exist_ok=True)
    sep = "" if not existing or existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
    with open(arch, "a", encoding="utf-8") as f:   # the archive first, every item in one write: an interruption then leaves the items in both files, never in neither
        f.write(head + sep + entry)
        f.flush()
        os.fsync(f.fileno())
    rest = list(lines)
    for item in sorted(found, key=lambda it: -it["start"]):   # from the end, so the line numbers of the items still to remove stay right
        rest = rest[:item["start"]] + rest[item["end"]:]
        k = item["start"]
        if 0 < k < len(rest) and rest[k - 1].strip() == "" and rest[k].strip() == "":   # the item stood between two blank lines: keep one
            del rest[k]
    write_atomic(path, "\n".join(rest))
    for it in found:
        print("done [%s]: moved to %s and removed from %s" % (it["id"], arch, path))
    return 0


def clean_line(text, what):
    t = text.strip()
    if not t:
        raise BacklogError("%s needs words" % what)
    if any(ord(c) < 32 and c not in "\n\t" or ord(c) == 127 for c in t):
        raise BacklogError("%s: no control characters" % what)
    return t


def cmd_add(path, ident, text, detail=None):
    """Append the item `- [IDENT] TEXT` (and DETAIL as indented lines) at the end of the list: of the section when backlog.section is set, else of the file."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*[a-z0-9]", ident):
        raise BacklogError("ID: a lowercase slug of letters, digits and hyphens, two characters or more (got %r)" % ident)
    text = clean_line(text, "the text")
    if "\n" in text:
        raise BacklogError("the text is one line; put the rest in --detail")
    lines = read_lines(path)
    for it in parse(lines):   # the whole file: an id is taken wherever it stands
        if it["id"] == ident:
            raise BacklogError("the id [%s] is already an item (line %d) in %s" % (ident, it["line"], path))
    entry = ["- [%s] %s" % (ident, text)]
    if detail is not None:
        entry += [("  " + ln.rstrip()) if ln.strip() else "" for ln in clean_line(detail, "--detail").split("\n")]
    lo, hi = section_range(lines, OPTS["section"]) if OPTS["section"] else (0, len(lines))
    at = hi
    while at > lo and lines[at - 1].strip() == "":
        at -= 1
    before = lines[at - 1] if at > 0 else ""
    if before.strip() and not (MARKER.match(before) or before[:1] in " \t"):   # a heading or a paragraph: a blank line, then the list
        entry.insert(0, "")
    if at < len(lines) and lines[at].strip() and not lines[at][:1] in " \t":   # the next line abuts the list (a heading): keep a blank line between
        entry.append("")
    write_atomic(path, "\n".join(lines[:at] + entry + lines[at:]))
    print("added [%s] to %s%s" % (ident, path, " under '%s'" % heading_text(OPTS["section"]) if OPTS["section"] else ""))
    return 0


def cmd_named(path):
    msgs = sys.stdin.read()
    names = []
    try:
        found = parse(read_lines(path), OPTS["section"])
    except BacklogError:
        if OPTS["section"]:   # informational: a heading that is not there names nothing, it is no failure
            return 0
        raise
    for it in found:
        ident = it["id"]
        if ident and ident not in names and re.search(r"(?<![a-z0-9-])%s(?![a-z0-9-])" % re.escape(ident), msgs):
            names.append(ident)
    if names:
        print(", ".join(names))
    return 0


def options(argv):
    """argv without --section and --archive (set in OPTS); a missing value or an empty one is a BacklogError."""
    out, i = [], 0
    while i < len(argv):
        if argv[i] in ("--section", "--archive"):
            if i + 1 >= len(argv) or not argv[i + 1].strip():
                raise BacklogError("%s needs a value" % argv[i])
            OPTS[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            out.append(argv[i])
            i += 1
    return out


def main(argv):
    try:
        argv = options(argv)
        cmd, rest = (argv[0] if argv else ""), argv[1:]
        if cmd == "list" and len(rest) in (1, 2) and (len(rest) == 1 or rest[1] == "--json"):
            return cmd_list(rest[0], len(rest) == 2)
        if cmd in ("plan", "apply", "token") and len(rest) == 3:
            if cmd == "token":
                print(plan_token(*rest))
                return 0
            return (cmd_plan if cmd == "plan" else cmd_apply)(*rest)
        if cmd == "add" and len(rest) in (3, 4):
            return cmd_add(*rest)
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
