#!/usr/bin/env python3
"""The per-pack work of `skill check`, `tool check`, `packs check` and `skill|tool list`, in one process.

lib/packs.sh loops over the packs a role gets. Each pack needs the same few facts: the content hash that approval stores, the
compatible_providers of its record, the approved hash, and the review. Done from the shell that is a dozen processes (find, sort, xargs,
sha256sum, jq, python3) per pack and several times over, once per step of the loop. This script does them for all the packs of a verb in
one process, and says exactly what the shell said: the same lines in the same order, the same exit status, and the same hash for the same
pack (the approval hash of the library is stored with every pack, so it may not change by a bit).

  packs_check.py check KIND PACKS NAME...     the lines of `qargi KIND check`: drift, review failures or "ok   KIND:NAME" per pack; exit 1 on a failure
  packs_check.py list KIND PACKS [--attached TEXT --label PROJECT/ROLE]
                                              the lines of `qargi KIND list`; TEXT is `effective` of that project and role
  packs_check.py filter PROJECT SURFACES PACKS CONF
                                              stdin: KIND:NAME lines (effective). stdout: "ok<TAB>KIND:NAME" for a pack the project's
                                              provider can use (or whose use is not decided here), "skip<TAB>KIND<TAB>NAME<TAB>why" for one
                                              it cannot (what packs_compat.py check says, without a process per pack)
  packs_check.py rows PACKS OUTFILE           stdin: "ROLE KIND:NAME" lines. Appends to OUTFILE one JSON line per pack with its path, hash,
                                              approved hash, whether its review passes, its compatible_providers and the role (the render inputs)
  packs_check.py audit PACKS CCINPUTS SCAN OUTFILE
                                              the render inputs plus every skill the scan found (packs_audit.py scan) with the library's
                                              hash and approval of the same name: the inputs of the audit of the skills a session would load
  packs_check.py hash PATH                    the content hash of one pack (what the shell function content_hash printed)
  packs_check.py toolmsgs PATH [TOOL_LIST]    the findings of the review about a tool pack file: its name, its URL, its tools map, the name and the
                                              policy of each tool, a write-like tool that would run unattended (a line starts with FAIL), and what the
                                              server's tool listing says of its tools (FAIL and NOTE lines). The review of lib/packs.sh prints them: the
                                              rule that says which tool names write is in this file alone. TOOL_LIST is the tool_list to judge by, as
                                              JSON (empty: none); without it the one of the pack's record
  packs_check.py toollist LISTING PATH        the tool_list for the tool pack file PATH from the server's own tool listing in the file LISTING (an MCP
                                              tools/list result), as compact sorted JSON: what the record keeps and the content hash covers. Exit 1
                                              and the reason on stderr when LISTING is no such listing. No server is contacted

The things the shell computed with the locale (sort, a glob) are computed with the same C library calls (strcoll), so the answer is the
same in every locale. Where the shell used jq on a record or a pack file in a way that has more cases than this script handles in plain
Python (a value of an unexpected type, text that is not strict JSON) the script runs the same jq program, so the answer cannot differ.
Not reproduced: the lists `URLs mentioned` and `network commands mentioned` of the review (they are text for a person; check keeps only
the lines that start with FAIL, and the render only whether the review passed). The findings about a tool pack's document (tool_msgs) are this
file's own and the shell asks for them (toolmsgs): a file that is not one JSON object, or whose tools map is not an object, fails."""
import hashlib
import json
import locale
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


class _Lazy:
    """A module imported when it is first used: the verbs that need only part of them start faster."""

    def __init__(self, name):
        self._name, self._mod = name, None

    def __getattr__(self, attr):
        if self._mod is None:
            self._mod = __import__(self._name, fromlist=["x"])
        return getattr(self._mod, attr)


packs_compat = _Lazy("packs_compat")
R = _Lazy("conformance.review")
subprocess = _Lazy("subprocess")

try:
    locale.setlocale(locale.LC_ALL, "")
except locale.Error:
    pass

SECRET_SKILL = (rb"sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY")
SECRET_TOOL = (rb"sk-ant-|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|Bearer [A-Za-z0-9._-]{20,}")
SCRIPT_SUFFIX = (b".sh", b".py", b".js", b".rb")
SIMPLE = r"[A-Za-z0-9._-]*"
POLICY_WORDS = ("always_allow", "always_ask", "auto")
UNATTENDED = ("always_allow", "auto")                             # the policies under which a tool runs with nobody asked
TOOL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}\Z")              # the name of a tool pack (the MCP server as qargi calls it)
VAULT_ID = r"vlt_[A-Za-z0-9]+$"
MISSING = object()
BAD = object()

# --- the names of the tools in a pack's `tools` map
# A key of the map is the name the MCP server gives the tool, so it is taken as servers write them: letters, digits and _ . - / (platform.list_items,
# repo/push, issue-close, deleteItem), 1 to 128 characters, the first a letter, a digit or _. No blank, control character, quote, wildcard or any other
# character: the name goes into a permission rule and into the lines a person approves.
TOOL_KEY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{0,127}\Z")
# The one definition of "this tool writes, by its name" (the shell review asks it through the `toolmsgs` verb).
# A name is cut into words at every character that is not a letter (_ . - / and digits) and at a camelCase boundary (deleteItem: delete, Item;
# HTTPPost: HTTP, Post), and the case is dropped. A word that STARTS with a write word makes the tool write-like, wherever the word stands in the
# name: delete_item, platform.delete_knowledge, repo/push, issue-close, deleteItem, and also deleteall and sendmail, which have no separator.
# A write word in the middle or at the end of a word does not count (offset, dataset, preset, asset). The words of READ_ALIKE start with a write
# word and are ordinary names of things that are read (settings_view, address_list, postal_code_lookup), so they do not count either; any other
# word that starts with one counts (created, comments, setup, sender), since a tool taken for a write is asked about and one taken for a read is not.
WRITE_WORDS = ("create", "update", "delete", "remove", "post", "push", "write", "merge", "send", "set", "add", "edit", "close", "comment")
READ_ALIKE = frozenset(("settings", "setting", "address", "addresses", "postal", "postcode", "postcodes", "additional", "closest"))
NAME_WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")           # a run of capitals that no lower-case letter follows, or a word with at most its first letter a capital
CAPITALS = re.compile(r"[A-Z]{2,}(?=[a-z])")                      # a run of capitals with lower-case letters after it: HTTPPost is HTTP and Post, DELETEitem is DELETE and item


def name_words(name):
    """The words of a tool name, lower-cased: cut at every character that is not an ASCII letter and at a camelCase boundary. A run of capitals that
    lower-case letters follow is read both ways (its last capital starts the next word, or the run is a word of its own), so both readings are words."""
    if not isinstance(name, str):
        return []
    return [w.lower() for w in NAME_WORD.findall(name) + CAPITALS.findall(name)]


def write_like(name):
    """True when the name of a tool says it writes: one of its words starts with a write word and is not a READ_ALIKE word."""
    return any(w.startswith(WRITE_WORDS) and w not in READ_ALIKE for w in name_words(name))


def shown_key(k):
    """A key of the tools map as a message prints it: as it is when it is a tool name, else as a JSON string (a newline or a quote in it stays on its line)."""
    return k if isinstance(k, str) and TOOL_KEY.match(k) else json.dumps(k, ensure_ascii=True)


# --- the server's own tool listing (an MCP tools/list result in a file), given to `tool import` and `tool seal` with --tool-list FILE
# The record of a tool pack keeps what the listing says of the pack's tools: tool_list = {"sha256": the sha256 of the listing file, "tools": {name:
# hint}}. The hint is read-only (annotations.readOnlyHint is true), destructive (annotations.destructiveHint is true, whatever else is said) or write
# (the listing names the tool and does not mark it read-only). A tool of the pack that the listing does not name has no entry. tool_list is part of
# the content hash, as compatible_providers is, so it is approved with the pack and a change of it is drift.
HINTS = ("read-only", "write", "destructive")
MAX_LISTING = 4 * 1024 * 1024
SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class ListingError(Exception):
    """The file given as the server's tool listing is not one."""


def listing_problem(tl):
    """What is wrong with a tool_list (it is not what this file writes), or None."""
    if not isinstance(tl, dict) or set(tl) != {"sha256", "tools"}:
        return "it is not an object with sha256 and tools"
    if not isinstance(tl["sha256"], str) or not SHA256.match(tl["sha256"]):
        return "its sha256 is not the sha256 of a file"
    if not isinstance(tl["tools"], dict) or not all(TOOL_KEY.match(k) and isinstance(v, str) and v in HINTS for k, v in tl["tools"].items()):
        return "its tools is not a map of tool names to read-only, write or destructive"
    return None


def parse_tool_list(text):
    """The tool_list a JSON text stands for: None for no text, the object when it is what this file writes, else BAD."""
    if not text.strip():
        return None
    try:
        v = json.loads(text)
    except (ValueError, RecursionError):
        return BAD
    return v if listing_problem(v) is None else BAD


def read_listing(path, pack):
    """(tool_list, notes) for the tool pack file PACK from the server's tool listing in the file PATH: an MCP tools/list result (an object with a tools
    list) or the JSON-RPC response that holds it as result. ListingError says why PATH is no listing."""
    try:
        with open(path, "rb") as f:
            raw = f.read(MAX_LISTING + 1)
    except OSError as e:
        raise ListingError("the tool listing %s cannot be read (%s)" % (path, e.strerror or type(e).__name__))
    if len(raw) > MAX_LISTING:
        raise ListingError("the tool listing %s is larger than %d bytes" % (path, MAX_LISTING))
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        raise ListingError("the tool listing %s is not JSON" % path)
    if isinstance(doc, dict) and "tools" not in doc and isinstance(doc.get("result"), dict):
        doc = doc["result"]
    tools = doc.get("tools") if isinstance(doc, dict) else None
    if not isinstance(tools, list):
        raise ListingError("the tool listing %s is not an MCP tools/list result: an object with a tools list, or the response that holds one as result" % path)
    hints = {}
    for i, t in enumerate(tools):
        name = t.get("name") if isinstance(t, dict) else None
        if not isinstance(name, str) or not name:
            raise ListingError("the tool listing %s: tools[%d] has no name" % (path, i))
        if name in hints:
            raise ListingError("the tool listing %s names the tool %s twice" % (path, shown_key(name)))
        ann = t["annotations"] if isinstance(t.get("annotations"), dict) else {}
        hints[name] = "destructive" if ann.get("destructiveHint") is True else "read-only" if ann.get("readOnlyHint") is True else "write"
    d = read_tool(pack)
    keys = [k for k in d["tools"] if TOOL_KEY.match(k)] if isinstance(d, dict) and isinstance(d.get("tools"), dict) else []
    notes = []
    if isinstance(doc.get("nextCursor"), str) and doc["nextCursor"]:
        notes.append("the tool listing has a nextCursor: it is one page of the server's tools, and a tool on another page counts as not listed")
    return {"sha256": hashlib.sha256(raw).hexdigest(), "tools": {k: hints[k] for k in keys if k in hints}}, notes


# the jq programs the review used, kept word for word for the values this file does not read itself
JQ_TOOLS_LINE = r'"tools: " + ((.tools // {}) | to_entries | map(.key + "=" + (.value|tostring)) | join(", "))'
JQ_VAULT = r'(.vault_ids // []) | all(test("^vlt_[A-Za-z0-9]+$"))'


# --- output: stdout is flushed before anything goes to stderr, so the two come out in the order the shell wrote them
def out(text):
    sys.stdout.write(text)


def warn(text):
    sys.stdout.flush()
    sys.stderr.write(text)
    sys.stderr.flush()


# --- locale order: what `sort` and a glob do (strcoll, then the bytes)
def coll(b):
    try:
        return (locale.strxfrm(b.decode("utf-8")), b)
    except (UnicodeDecodeError, ValueError, OSError):
        return (locale.strxfrm(b.decode("utf-8", "replace")), b)


def to_b(p):
    return os.fsencode(p)


def to_s(b):
    return b.decode("utf-8", "surrogateescape")


# --- jq, for the values the plain code does not read
def jq(args, path=None, text=None):
    """(status, stdout as text with the trailing newlines of a command substitution removed)."""
    cmd = ["jq"] + list(args) + ([path] if path is not None else [])
    try:
        p = subprocess.run(cmd, input=None if text is None else text.encode("utf-8", "surrogateescape"), stdout=subprocess.PIPE,
                           stderr=subprocess.DEVNULL, check=False)
    except OSError:
        return 127, ""
    return p.returncode, to_s(p.stdout).rstrip("\n")


# --- the pack and its record
def item_path(packs, kind, name):
    return os.path.join(packs, "skills", name) if kind == "skill" else os.path.join(packs, "tools", name + ".json")


def record_of(p):
    if os.path.isdir(p):
        return os.path.join(p, ".pack.json")
    return (p[:-5] if p.endswith(".json") else p) + ".pack.json"


def _record(p):
    """The record's parsed JSON, MISSING when it cannot be read, BAD when it is not one clean JSON document."""
    try:
        with open(record_of(p), "rb") as f:
            raw = f.read()
    except OSError:
        return MISSING
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, RecursionError):
        return BAD


def compat_of(p):
    """compat_of of the shell: the record's compatible_providers as compact, sorted JSON; empty when there is none."""
    d = _record(p)
    if d is MISSING:
        return ""
    if isinstance(d, dict):
        v = d.get("compatible_providers")
        if v is None:
            return ""
        if isinstance(v, list) and all(isinstance(x, str) and re.fullmatch(SIMPLE, x) for x in v):
            return json.dumps(sorted(set(v)), separators=(",", ":"))
    return jq(["-cS", '.compatible_providers | select(. != null) | if type == "array" then unique else . end'], record_of(p))[1]


def approved_of(p):
    """The sha256 the record holds (empty when none)."""
    d = _record(p)
    if d is MISSING:
        return ""
    if isinstance(d, dict):
        v = d.get("sha256")
        if v is None or v is False:
            return ""
        if isinstance(v, str):
            return v.rstrip("\n")
    return jq(["-r", '.sha256 // ""'], record_of(p))[1]


def tool_list_text(p):
    """tl_of of the shell: the tool_list of a tool pack's record as compact, sorted JSON (the text the content hash covers); empty when the record has
    none, and for a directory (a skill has none)."""
    if os.path.isdir(p):
        return ""
    d = _record(p)
    if d is MISSING:
        return ""
    if isinstance(d, dict):
        v = d.get("tool_list")
        if v is None:
            return ""
        if listing_problem(v) is None:               # names and words in ASCII: this is the text `jq -cS` prints
            return json.dumps(v, sort_keys=True, separators=(",", ":"))
    return jq(["-cS", ".tool_list | select(. != null)"], record_of(p))[1]


def tool_list_of(p):
    """The tool_list of the record of the tool pack P: None when it has none, BAD when it is not what this file writes (the review fails then)."""
    return parse_tool_list(tool_list_text(p))


# --- the content hash: the files, the entries that are not plain files, and the declaration
def walk(root):
    """Every entry under ROOT in the order `find` lists them (the directory's own order, a directory before its content, nothing followed):
    [relative path (bytes), lstat result, number of entries when it is a directory that could be read]."""
    res = []

    def opened(path):
        try:
            with os.scandir(path) as it:
                return list(it)
        except OSError:
            return None
    top = opened(root)
    if top is None:
        return res
    stack = [(iter(top), b"")]
    while stack:
        it, prefix = stack[-1]
        e = next(it, None)
        if e is None:
            stack.pop()
            continue
        rel = prefix + e.name
        try:
            st = e.stat(follow_symlinks=False)
        except OSError:
            continue
        rec = [rel, st, None]
        res.append(rec)
        if stat.S_ISDIR(st.st_mode):
            kids = opened(e.path)
            if kids is not None:
                rec[2] = len(kids)
                stack.append((iter(kids), rel + b"/"))
    return res


def kind_char(mode):
    for test, c in ((stat.S_ISREG, b"f"), (stat.S_ISDIR, b"d"), (stat.S_ISLNK, b"l"), (stat.S_ISFIFO, b"p"), (stat.S_ISSOCK, b"s"),
                    (stat.S_ISBLK, b"b"), (stat.S_ISCHR, b"c")):
        if test(mode):
            return c
    return b"U"


def sha256sum_name(name):
    """The name as sha256sum prints it: a backslash, a newline or a carriage return in it is escaped and the line starts with a backslash."""
    if b"\\" in name or b"\n" in name or b"\r" in name:
        return True, name.replace(b"\\", b"\\\\").replace(b"\n", b"\\n").replace(b"\r", b"\\r")
    return False, name


def content_hash(p, quiet=True):
    """content_hash of the shell for the pack at P with its record's declaration."""
    pb = to_b(p)
    if os.path.isdir(p):
        recs = walk(pb)
        names = sorted((b"./" + r for r, st, _ in recs if stat.S_ISREG(st.st_mode) and r != b".pack.json"), key=coll)
        lines = []
        for name in names:
            try:
                with open(os.path.join(pb, name[2:]), "rb") as f:
                    digest = hashlib.sha256(f.read()).hexdigest()
            except OSError as e:
                if not quiet:
                    warn("sha256sum: %s: %s\n" % (to_s(name), os.strerror(e.errno or 0)))
                continue
            esc, shown = sha256sum_name(name)
            lines.append((b"\\" if esc else b"") + digest.encode() + b"  " + shown + b"\n")
        if not names:                      # xargs ran sha256sum once with no file: it read its standard input, which is empty
            lines.append(hashlib.sha256(b"").hexdigest().encode() + b"  -\n")
        h = hashlib.sha256(b"".join(lines)).hexdigest()[:16]
        odd = []
        for r, st, kids in recs:
            if r == b".pack.json":
                continue
            c = kind_char(st.st_mode)
            if (c not in (b"f", b"d")) or (c == b"d" and kids == 0) or (c == b"f" and st.st_nlink > 1):
                target = os.readlink(os.path.join(pb, r)) if c == b"l" else b""
                odd.append(c + b" " + str(st.st_nlink).encode() + b" " + r + b" -> " + target)
        x = b"".join(o + b"\n" for o in sorted(odd)).rstrip(b"\n")
        if x:
            h = hashlib.sha256(h.encode() + b"\nnon-regular entries\n" + x + b"\n").hexdigest()[:16]
    else:
        try:
            with open(pb, "rb") as f:
                h = hashlib.sha256(f.read()).hexdigest()[:16]
        except OSError:
            h = ""
    c = compat_of(p)
    if c:
        h = hashlib.sha256(("%s\ncompatible_providers=%s\n" % (h, c)).encode("utf-8", "surrogateescape")).hexdigest()[:16]
    t = tool_list_text(p)                            # a pack with no tool_list hashes as it always did
    if t:
        h = hashlib.sha256(("%s\ntool_list=%s\n" % (h, t)).encode("utf-8", "surrogateescape")).hexdigest()[:16]
    return h


# --- the review
def cmdsub(text):
    return text.rstrip("\n")


def sed_dot(line):
    return "  " + line[2:] if line.startswith("./") else line


def find_lines(rels):
    """The lines `find` prints for these relative paths, then `sed 's#^\\./#  #'`: a name with a newline is several lines."""
    res = []
    for r in rels:
        for ln in ("./" + to_s(r)).split("\n"):
            res.append(sed_dot(ln))
    return res


def policy_text(p):
    """pol=$(python3 review.py policy P 2>&1): (status, text)."""
    try:
        found = R.policy(p) if os.path.isdir(p) else R._policy_file(p, "the tool file")
    except Exception as e:           # the script printed a traceback and failed
        return 1, "Traceback: %s: %s" % (type(e).__name__, e)
    text = "".join("FAIL: %s\n" % R.vis(m) for m in found)
    return (1 if found else 0), text


def declared_of(c):
    try:
        return json.loads(c) if c.strip() else None
    except (ValueError, RecursionError):
        return "not JSON"


def readable(path):
    try:
        with open(path, "rb"):
            return True
    except OSError:
        return False


def regular_files(root, root_link=False):
    """(count, bytes) of `find ROOT -type f ! -path ROOT/.pack.json`, and what `cat` of them printed. Without -H find does not enter a
    symbolic link given as ROOT."""
    if root_link:
        return 0, 0
    n = size = 0
    for r, st, _ in walk(to_b(root)):
        if stat.S_ISREG(st.st_mode) and r != b".pack.json":
            n += r.count(b"\n") + 1                       # wc -l counts lines: a name with a newline is more than one
            try:
                with open(os.path.join(to_b(root), r), "rb") as f:
                    size += len(f.read())
            except OSError:
                pass
    return n, size


def secret_in(root, pattern):
    """grep -rqE: a regular file under ROOT (the record included) has a line that matches."""
    pb = to_b(root)
    if os.path.isfile(pb):
        files = [pb]
    else:
        files = [os.path.join(pb, r) for r, st, _ in walk(pb) if stat.S_ISREG(st.st_mode)]
    for f in files:
        try:
            with open(f, "rb") as fh:
                if re.search(pattern, fh.read()):
                    return True
        except OSError:
            pass
    return False


def skill_review(p, c):
    """The lines review() of the shell printed for a skill, and its status."""
    o = []
    rc = 0
    pb = to_b(p)
    skill_md = os.path.join(pb, b"SKILL.md")
    if not os.path.isfile(skill_md):
        return "FAIL: no SKILL.md\n", 1
    try:
        with open(skill_md, "rb") as f:
            data = f.read()
    except OSError:
        data = None
    first = data.split(b"\n", 1)[0] if data is not None else None
    if first != b"---":
        o.append("FAIL: SKILL.md has no front matter\n")
        rc = 1
    text = data.decode("utf-8", "surrogateescape") if data is not None else ""
    if not re.search(r"^name: *[a-z0-9]", text, re.M):
        o.append("FAIL: SKILL.md front matter has no name\n")
        rc = 1
    if not re.search(r"^description: *[^< \n\ud800-\udfff]", text, re.M):
        o.append("FAIL: SKILL.md front matter has no real description\n")
        rc = 1
    prc, pol = policy_text(p)
    if prc:
        o.append(cmdsub(pol) + "\n")
        rc = 1
    n, size = regular_files(p, os.path.islink(p))
    nested = sorted(find_lines(r for r, st, _ in walk(pb) if r.count(b"/") >= 1 and os.path.basename(r) == b".pack.json"), key=lambda s: coll(s.encode("utf-8", "surrogateescape")))
    nested = cmdsub("\n".join(nested))
    if nested:
        o.append("FAIL: .pack.json is qargi's own record and only the top level of a library pack holds it; remove or rename these:\n")
        o.append(R.vis(nested + "\n"))
        rc = 1
    o.append("files: %d, %d bytes\n" % (n, size))
    if not (n <= 100 and size <= 2000000):
        o.append("FAIL: more than 100 files or 2 MB\n")
        rc = 1
    recs = walk(pb)
    listed = sorted(find_lines(r for r, st, _ in recs if stat.S_ISREG(st.st_mode) and r != b".pack.json"), key=lambda s: coll(s.encode("utf-8", "surrogateescape")))[:40]
    if listed:
        o.append(R.vis("\n".join(listed) + "\n"))
    scripts = find_lines(r for r, st, _ in recs if stat.S_ISREG(st.st_mode) and r != b".pack.json"
                         and (st.st_mode & 0o111 or os.path.basename(r).endswith(SCRIPT_SUFFIX)))
    scripts = cmdsub("\n".join(scripts))
    if scripts:
        o.append("executable or script files (the agent may run these):\n")
        o.append(R.vis(scripts + "\n"))
    if secret_in(p, SECRET_SKILL):
        o.append("FAIL: looks like a secret\n")
        rc = 1
    return "".join(o), rc


def tool_msgs(d, tl=None):
    """The findings about the document D of a tool pack (what json.loads made of the file, or BAD), one line each: its name, its URL, the tools map, the name
    and the policy of every tool, a write-like tool that would run unattended and, with a tool_list TL (what the server's own listing says of the pack's
    tools; BAD: one that is not what this file writes), a tool the listing does not mark read-only that would run unattended. A finding starts with
    FAIL; the lines that start with NOTE are for the person who approves (a tool the listing marks destructive or does not name, the listing's hash)."""
    if not isinstance(d, dict):
        return ["FAIL: not a JSON object: a tool pack is one object with name, url and tools"]
    msgs = []
    name = d.get("name")
    if not isinstance(name, str) or not TOOL_NAME.match(name):
        msgs.append("FAIL: name: lower-case letters, digits, -")
    url = d.get("url")
    if not isinstance(url, str) or not url.startswith("https://") or re.search(r"example\.invalid|OWNER|<", url):
        msgs.append("FAIL: url: a real https URL")
    tools = d.get("tools")
    if not isinstance(tools, dict) or len(tools) == 0:
        msgs.append("FAIL: tools: an explicit allowlist of tool names with a policy each")
        return msgs
    named = [k for k in tools if TOOL_KEY.match(k)]
    for k in tools:
        if not TOOL_KEY.match(k):
            msgs.append("FAIL: tools.%s: not a tool name (letters, digits, _ . - /, at most 128 characters, no blank)" % shown_key(k))
    for k in named:
        if not (isinstance(tools[k], str) and tools[k] in POLICY_WORDS):
            msgs.append("FAIL: tools." + k + ": policy must be always_allow, always_ask or auto")
    for k in named:
        if write_like(k) and tools[k] in UNATTENDED and d.get("write_ok") is not True:
            msgs.append("FAIL: tools." + k + ": a write-like tool may not run unattended (use always_ask) unless write_ok is true on the pack, on purpose")
    if tl is BAD:
        msgs.append("FAIL: tool_list: what the pack's record keeps of the server's tool listing is not what qargi wrote; seal the pack again with --tool-list FILE")
    elif tl is not None:
        hints = tl["tools"]
        for k in named:                              # the name check above stands: a tool it failed is not failed twice
            if tools[k] in UNATTENDED and hints.get(k) != "read-only" and d.get("write_ok") is not True and not write_like(k):
                msgs.append("FAIL: tools." + k + ": the server's tool listing does not mark it read-only (readOnlyHint), so it may not run unattended "
                            "(use always_ask) unless write_ok is true on the pack, on purpose")
        for k in named:
            if hints.get(k) == "destructive":
                msgs.append("NOTE: tools." + k + ": the server's tool listing marks it destructive (destructiveHint)")
        for k in named:
            if k not in hints:
                msgs.append("NOTE: tools." + k + ": not in the server's tool listing")
        msgs.append("NOTE: tool listing %s: it marks %d of the pack's %d tools read-only" % (tl["sha256"][:16], sum(1 for k in named if hints.get(k) == "read-only"), len(named)))
    return msgs


def read_tool(p):
    """The document of the tool pack file P, or BAD when it cannot be read as one JSON value."""
    try:
        with open(p, "rb") as f:
            return json.loads(f.read().decode("utf-8"))
    except (OSError, ValueError, RecursionError):
        return BAD


def tool_review(p, c, tl=MISSING):
    """The review of a tool pack. TL is the tool_list to judge by (None: none; BAD: not a tool_list); left out, it is the one of the pack's record."""
    o = []
    rc = 0
    if tl is MISSING:
        tl = tool_list_of(p)
    prc, pol = policy_text(p)
    if prc:
        o.append(cmdsub(pol) + "\n")
        rc = 1
    d = read_tool(p)
    if not isinstance(d, dict):                      # jq -e decides the cases that are not an object
        if jq(["-e", "."], p)[0] != 0:
            o.append("FAIL: not valid JSON\n")
            return "".join(o), 1
    msgs = tool_msgs(d, tl)
    if msgs:
        o.append(R.vis("\n".join(msgs) + "\n"))
        if any(m.startswith("FAIL") for m in msgs):
            rc = 1
    wo = d.get("write_ok") if isinstance(d, dict) else MISSING
    if wo is True or wo == "true":
        o.append("NOTE: write_ok is set: write-like tools may run unattended\n")
    if isinstance(d, dict) and isinstance(d.get("tools"), dict) and all(isinstance(v, str) and isinstance(k, str) for k, v in d["tools"].items()):
        line = "tools: " + ", ".join("%s=%s" % (k, v) for k, v in d["tools"].items())
    else:
        line = jq(["-r", JQ_TOOLS_LINE], p)[1]
    if line:
        o.append(R.vis(line + "\n"))
    vault_ok = None
    if isinstance(d, dict):
        v = d.get("vault_ids")
        if v is None or v is False:
            vault_ok = True
        elif isinstance(v, list) and all(isinstance(x, str) and "\n" not in x for x in v):
            vault_ok = all(re.match(VAULT_ID, x) for x in v)
    if vault_ok is None:
        vault_ok = jq(["-e", JQ_VAULT], p)[0] == 0
    if not vault_ok:
        o.append("FAIL: vault_ids must be vault ids (vlt_...), never secrets\n")
        rc = 1
    if secret_in(p, SECRET_TOOL):
        o.append("FAIL: looks like a secret (credentials belong in a vault)\n")
        rc = 1
    return "".join(o), rc


def review(kind, p, c=None):
    """(text, status): what review() of the shell printed (the lists of URLs and network commands left out) and returned."""
    if c is None:
        c = compat_of(p)
    declared = declared_of(c)
    bad = packs_compat.problem(declared)
    if bad:
        head, rc = "FAIL: compatible_providers: %s\n" % bad, 1
    else:
        head, rc = "compatible_providers: %s\n" % ", ".join(declared), 0
    body, brc = skill_review(p, c) if kind == "skill" else tool_review(p, c)
    return head + body, 1 if (rc or brc) else 0


# --- check
def check(kind, packs, names):
    rc = 0
    for n in names:
        e = "%s:%s" % (kind, n)
        p = item_path(packs, kind, n)
        if not os.path.exists(p):
            out("FAIL %s: linked but not in the library\n" % e)
            rc = 1
            continue
        want = approved_of(p)
        have = content_hash(p, quiet=False)
        if want and want != have:
            out("FAIL %s: content changed since it was approved (drift: %s -> %s); review it and re-import\n" % (e, want, have))
            rc = 1
        text, brc = review(kind, p)
        if brc == 0:
            out("ok   %s\n" % e)
        else:
            for ln in cmdsub(text).split("\n"):
                if ln.startswith("FAIL"):
                    out("%s: %s\n" % (e, ln))
            rc = 1
    return rc


# --- list
def cl_of(c):
    """The compatible: column for the compat_of text C."""
    text = c if c else "null"
    try:
        v = json.loads(text)
    except (ValueError, RecursionError):
        v = BAD
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return ", ".join(v)
    if v is None:
        return "NOT DECLARED"
    if v is not BAD and not isinstance(v, list):
        return "invalid"
    st, res = jq(["-r", 'if type == "array" then join(", ") elif . == null then "NOT DECLARED" else "invalid" end'], text=text)
    return res if st == 0 else "invalid"


def links_of(links_file, key):
    """The `links:` text of one pack: each link that names it, as scope[:project][/role], joined with a comma."""
    def unset(v):
        return v is None or v is False
    try:
        with open(links_file, "rb") as f:
            items = json.loads(f.read().decode("utf-8"))["links"]
        plain = isinstance(items, list) and all(isinstance(x, dict) for x in items) and all(
            isinstance(x.get("scope"), str) and all(unset(x.get(f)) or isinstance(x.get(f), str) for f in ("project", "role"))
            for x in items if x.get("pack") == key)
    except (OSError, ValueError, RecursionError, KeyError, TypeError):
        plain = False
    if not plain:
        return jq(["-r", "--arg", "k", key, '[.links[] | select(.pack==$k) | .scope + (if .project then ":"+.project else "" end) + (if .role then "/"+.role else "" end)] | join(", ")'],
                  links_file)[1]
    return ", ".join(x["scope"] + ("" if unset(x.get("project")) else ":" + x["project"]) + ("" if unset(x.get("role")) else "/" + x["role"])
                     for x in items if x.get("pack") == key)


def listing(kind, packs, attached, label):
    d = os.path.join(packs, kind + "s")
    try:
        names = [n for n in os.listdir(to_b(d)) if not n.startswith(b".")]
    except OSError:
        return 0
    names.sort(key=lambda n: coll(os.path.join(to_b(d), n)))
    links_file = os.path.join(packs, "links.json")
    on = set(attached.split("\n")) if attached else set()
    for nb in names:
        f = os.path.join(d, to_s(nb))
        if not os.path.exists(f) or nb.endswith(b".pack.json"):
            continue
        n = to_s(nb)
        if n.endswith(".json") and n != ".json":
            n = n[:-5]
        mark = ""
        if label is not None and "%s:%s" % (kind, n) in on:
            mark = "  [attached to %s]" % label
        lk = links_of(links_file, "%s:%s" % (kind, n))
        out("%s   links: %s   compatible: %s%s\n" % (n, lk or "none", cl_of(compat_of(f)), mark))
    return 0


# --- filter
def usable(entries, project, surfaces, packs, conf):
    """(entry, kind, name, why) for each KIND:NAME entry: why is None for a pack the project's provider can use on one of SURFACES (or whose use is
    not decided here: a pack that is missing, declares nothing or "any", or changed since it was approved fails loudly where it is used), else the
    reason the pack is skipped. The rule of `filter`, for the callers in this process too (lib/packs_mcp.py)."""
    answers = MISSING
    surf = [s for s in surfaces.split(",") if s]
    valid_surfaces = bool(surf) and all(s in packs_compat.SURFACES for s in surf)
    for e in entries:
        k, n = e.split(":", 1) if ":" in e else (e, e)
        p = item_path(packs, k, n)
        c = compat_of(p) if os.path.exists(p) else ""
        why = None
        if c and c != '["any"]' and valid_surfaces:
            want = approved_of(p)
            if not (want and want != content_hash(p)):
                declared = declared_of(c)
                if packs_compat.problem(declared) is None:
                    if answers is MISSING:
                        answers = packs_compat._provider().project_answers(project, conf)
                    try:
                        ok, said = packs_compat.evaluate(declared, answers, project, surf)
                    except Exception as ex:             # the script would have failed with a traceback and status 1
                        ok, said = False, "%s: %s" % (type(ex).__name__, ex)
                    if not ok:
                        why = said.rstrip("\n")
        yield e, k, n, why


def filt(project, surfaces, packs, conf):
    entries = [e for e in (line.strip(" \t") for line in sys.stdin.read().split("\n")) if e]
    for e, k, n, why in usable(entries, project, surfaces, packs, conf):
        out("ok\t%s\n" % e if why is None else "skip\t%s\t%s\t%s\n" % (k, n, why))
    return 0


# --- rows, audit
def unreadable(p):
    if not os.access(p, os.R_OK):
        return True
    return any(not os.access(os.path.join(to_b(p), r), os.R_OK) for r, _, _ in walk(to_b(p)))


def rows(packs, outfile):
    res = []
    for line in sys.stdin.read().split("\n"):
        parts = line.strip().split(None, 1)
        if len(parts) < 2:
            continue
        r, e = parts
        k, n = e.split(":", 1) if ":" in e else (e, e)
        p = item_path(packs, k, n)
        if os.path.exists(p):
            cpj = compat_of(p)
            try:
                cv = json.loads(cpj) if cpj else None
            except (ValueError, RecursionError):
                continue
            rv = (not unreadable(p)) and review(k, p, cpj)[1] == 0
            row = {"kind": k, "name": n, "path": p, "sha256": content_hash(p), "approved": approved_of(p), "review_ok": rv, "exists": True,
                   "role": r, "compatible_providers": cv}
        else:
            row = {"kind": k, "name": n, "path": "", "sha256": "", "approved": "", "review_ok": False, "exists": False, "role": r,
                   "compatible_providers": None}
        res.append(json.dumps(row, separators=(",", ":"), ensure_ascii=False))
    with open(outfile, "a", encoding="utf-8", errors="surrogateescape") as f:
        for r in res:
            f.write(r + "\n")
    return 0


def audit(packs, cc, scan, outfile):
    with open(scan, encoding="utf-8", errors="surrogateescape") as f:
        found = json.load(f)
    skills = []
    for e in found:
        n = e["name"].rstrip("\n") if isinstance(e.get("name"), str) else ""
        lib = None
        d = packs + "/skills/" + n
        if os.path.isdir(d) and not os.path.islink(d):
            lib = {"hash": content_hash(d), "approved": approved_of(d)}
        skills.append(dict(e, lib=lib))
    with open(cc, encoding="utf-8", errors="surrogateescape") as f:
        doc = json.load(f)
    doc.update({"skills": skills, "accepted": os.path.join(packs, "accepted.json")})
    with open(outfile, "w", encoding="utf-8", errors="surrogateescape") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return 0


def main(argv):
    try:
        verb = argv[0]
        if verb == "check" and len(argv) >= 3:
            return check(argv[1], argv[2], argv[3:])
        if verb == "list" and len(argv) >= 3:
            attached, label, i = "", None, 3
            while i < len(argv):
                if argv[i] == "--attached" and i + 1 < len(argv):
                    attached, i = argv[i + 1], i + 2
                elif argv[i] == "--label" and i + 1 < len(argv):
                    label, i = argv[i + 1], i + 2
                else:
                    raise IndexError
            return listing(argv[1], argv[2], attached, label)
        if verb == "filter" and len(argv) == 5:
            return filt(*argv[1:])
        if verb == "rows" and len(argv) == 3:
            return rows(*argv[1:])
        if verb == "audit" and len(argv) == 5:
            return audit(*argv[1:])
        if verb == "hash" and len(argv) == 2:
            out(content_hash(argv[1], quiet=False) + "\n")
            return 0
        if verb == "toolmsgs" and len(argv) in (2, 3):
            tl = tool_list_of(argv[1]) if len(argv) == 2 else parse_tool_list(argv[2])
            out("".join(m + "\n" for m in tool_msgs(read_tool(argv[1]), tl)))
            return 0
        if verb == "toollist" and len(argv) == 3:
            try:
                tl, notes = read_listing(argv[1], argv[2])
            except ListingError as e:
                warn("qargi: %s\n" % R.vis(str(e)))
                return 1
            for n in notes:
                warn("note: %s\n" % n)
            out(json.dumps(tl, sort_keys=True, separators=(",", ":")) + "\n")
            return 0
    except IndexError:
        pass
    print("usage: packs_check.py check KIND PACKS NAME... | list KIND PACKS [--attached TEXT --label P/R] | filter PROJECT SURFACES PACKS CONF | "
          "rows PACKS OUTFILE | audit PACKS CCINPUTS SCAN OUTFILE | hash PATH | toolmsgs PATH [TOOL_LIST] | toollist LISTING PATH", file=sys.stderr)
    return 2


if __name__ == "__main__":
    code = main(sys.argv[1:])
    sys.stdout.flush()
    sys.exit(code)
