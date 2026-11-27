#!/usr/bin/env python3
"""Run plan check v1, the static checker behind `qargi flow plan check FILE [--json]`. See docs/reference/run-plan.md.

A run plan is one JSON file (kind qargi-run-plan, lib/kinds/qargi-run-plan.json): one feature and the task nodes that merge into it, each with its
role, the paths it may change (scope), its DONE command and the nodes it comes after. The checker says whether the file is valid and in which order
the nodes can run, in waves. It reads the file, the list of roles qargi knows and the files of the current directory a DONE command names, and
nothing else: no state, no token, no network, nothing written. It plans nothing and starts nothing.

The validation and the ordering are those of lib/backlog_graph.py (its Invalid and require, the JSON reader that refuses constants and duplicate
keys, the deterministic order of nodes, the strongly connected components); the DONE rule is the one `qargi local prepare` applies (the scanner of
lib/done_words.py). Traversals use explicit queues and stacks, never Python recursion. A report is deterministic for a fixed byte stream, the
roles and the files a DONE names.

Exit status: 0 the plan is valid (notes are allowed), 1 it is not (a finding of severity error; with --json the document is printed all the same,
its `valid` says which), 2 a wrong call or a file that cannot be read, 70 the document of --json failed the check of its own registry file (a defect
of qargi, no document is printed). Run as python3 -I lib/run_plan.py plan check FILE [--json]. Standard library only."""
import argparse
from collections import defaultdict, deque
import fnmatch
import functools
import json
import os
import re
import shutil
import subprocess
import sys

# -I does not put the script's directory on sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backlog_graph as G  # noqa: E402
import done_words as D  # noqa: E402
import jsonkind as K  # noqa: E402
import role as R  # noqa: E402

PLAN_KIND = "qargi-run-plan"
CHECK_KIND = "qargi-run-plan-check"
SCHEMA = 1

TOP_KEYS = ("kind", "schema", "project", "target_feature", "nodes")
NODE_REQUIRED = ("id", "task", "role", "scope", "done", "review_kind")
NODE_OPTIONAL = ("after", "profile", "runtime")
REVIEW_KINDS = ("none", "review", "advisor")
PROJECT_NAME = re.compile(r"[a-z][a-z0-9]{0,23}")        # lib/refusal.py PROJECT_RE: the name of a stored project
WORD = re.compile(r"[a-z][a-z0-9-]{0,39}")               # a profile or a runtime: lower case words with hyphens
MAX_BYTES = 1 << 20
MAX_NODES = 500
MAX_SCOPE = 100                                          # entries in the scope of one node
MAX_ID = 40                                              # as a feature name (lib/backlog_graph.py typed_ref)
# Files that almost every task changes. A node that lists one in its scope overlaps every other unordered node that lists it; a node that does not
# list it is not assumed to write it: declare these in the scope of a task that changes them.
SHARED = ("CHANGELOG.md", "man/qargi.1", "docs/reference/refusals.md", "tests/suite.txt", "tests/durations.txt")
GLOB_CHARS = "*?[]{}\\"


def slug(value, limit=MAX_ID):
    return type(value) is str and len(value) <= limit and G.SLUG.fullmatch(value) is not None


def feature_name(value):
    """A feature slug as feature.sh takes it: single hyphens, at most 40, never a long-lived branch."""
    return slug(value) and value not in ("master", "develop")


# ---- findings ------------------------------------------------------------------------------------------------------------------------

class Findings:
    """The findings of one check. A check is a function that calls G.require; guard() turns what it raises into a finding, so that one bad field
    does not hide the others."""
    def __init__(self):
        self.items = []

    def add(self, code, message, nodes=(), path="$", severity="error", **extra):
        self.items.append(dict(code=code, severity=severity, message=message, nodes=list(nodes), path=path, **extra))

    def guard(self, path="$", nodes=()):
        return _Guard(self, path, nodes)

    def errors(self):
        return any(f["severity"] == "error" for f in self.items)

    def sorted(self):
        return sorted(self.items, key=lambda f: (f["severity"] != "error", f["code"], f["nodes"], f["path"], f["message"]))


class _Guard:
    def __init__(self, col, path, nodes):
        self.col, self.path, self.nodes = col, path, nodes

    def __enter__(self):
        return self

    def __exit__(self, kind, error, trace):
        if isinstance(error, G.Invalid):
            details = dict(error.details)
            self.col.add(error.code, str(error), details.pop("nodes", self.nodes), details.pop("path", self.path), **details)
            return True
        return False


# ---- the scope of a node -------------------------------------------------------------------------------------------------------------

def scope_entry(text):
    """The segments of a scope entry (a path or a glob below the repository root), or Invalid. A directory names itself and everything beneath it."""
    G.require(type(text) is str and text != "", "bad-scope", "a scope entry must be non-empty text")
    G.require(text.isprintable(), "bad-scope", "scope entry %s holds a control character" % ascii(text))
    G.require(not text.startswith("/"), "bad-scope", "scope entry %s is absolute: use a path below the repository root" % text)
    G.require(not re.search(r"[\s,]", text), "bad-scope", "scope entry %s holds a space or a comma" % text)
    body = text
    while body.startswith("./"):
        body = body[2:]
    body = body.rstrip("/")
    if body in ("", "."):
        return []
    parts = body.split("/")
    G.require(".." not in parts, "bad-scope", "scope entry %s holds `..`" % text)
    G.require("" not in parts and "." not in parts, "bad-scope", "scope entry %s holds an empty or a `.` segment" % text)
    return parts


def has_glob(segment):
    return any(c in segment for c in GLOB_CHARS)


def segment_overlap(a, b):
    """Whether two path segments (a literal or a glob each) can name the same file name. Conservative: True unless they provably cannot."""
    if a == b:
        return True
    ga, gb = has_glob(a), has_glob(b)
    if not ga and not gb:
        return False
    if ga != gb:
        glob, literal = (a, b) if ga else (b, a)
        if "{" in glob or "\\" in glob:       # not fnmatch's dialect: say overlap
            return True
        return fnmatch.fnmatchcase(literal, glob)
    # two globs: they cannot overlap when their fixed beginnings or their fixed ends disagree; otherwise they may
    first = [min((s.index(c) for c in GLOB_CHARS if c in s)) for s in (a, b)]
    last = [max((s.rindex(c) for c in GLOB_CHARS if c in s)) for s in (a, b)]
    heads, tails = (a[:first[0]], b[:first[1]]), (a[last[0] + 1:], b[last[1] + 1:])
    return (heads[0].startswith(heads[1]) or heads[1].startswith(heads[0])) and (tails[0].endswith(tails[1]) or tails[1].endswith(tails[0]))


def scopes_overlap(parts_a, parts_b):
    """Whether some path can match both entries. `**` as a whole segment matches any number of segments, and every entry also matches what lies
    beneath it (a trailing `**`). A search over (position in a, position in b) with a stack and a visited set."""
    a, b = parts_a + ["**"], parts_b + ["**"]
    seen, todo = set(), [(0, 0)]
    while todo:
        i, j = todo.pop()
        if (i, j) in seen:
            continue
        seen.add((i, j))
        if i == len(a) and j == len(b):
            return True
        x = a[i] if i < len(a) else None
        y = b[j] if j < len(b) else None
        if x == "**":
            todo.append((i + 1, j))
            if j < len(b):
                todo.append((i, j + 1))
        if y == "**":
            todo.append((i, j + 1))
            if i < len(a):
                todo.append((i + 1, j))
        if x not in (None, "**") and y not in (None, "**") and segment_overlap(x, y):
            todo.append((i + 1, j + 1))
    return False


def normal(text):
    """A valid scope entry as one path: without a leading ./ or a trailing /."""
    return "/".join(scope_entry(text))


def in_scope(path, scope):
    """Whether the path of a script is covered by a scope entry of the node (a path, a directory or a glob), as `local prepare` reads --scope."""
    for entry in scope:
        entry = (entry[2:] if entry.startswith("./") else entry).rstrip("/")
        if path == entry or path.startswith(entry + "/") or fnmatch.fnmatchcase(path, entry):
            return True
    return False


# ---- the DONE command ----------------------------------------------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def shell_words():
    """The builtins and the keywords of bash: a command word that is one of them needs no file."""
    try:
        out = subprocess.run(["bash", "-c", "compgen -b; compgen -k"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             stdin=subprocess.DEVNULL, universal_newlines=True, timeout=20).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return frozenset(out.split())


@functools.lru_cache(maxsize=256)
def parses(line):
    try:
        return subprocess.run(["bash", "-n", "-c", line], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                              timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def check_done(line, scope):
    """The rule of `qargi local prepare --done`: one line that bash parses, whose command words are real. A word with a slash is looked up for the first
    command only: a file below the current directory, a file under a scope path of the node (the task may create it) or an absolute file. A word
    with $ or a backquote has nothing to look up. Any other word is an executable on PATH, a shell builtin or a keyword; the arguments are never read."""
    G.require(type(line) is str and line.strip() != "", "bad-done", "done must be a command line: the check that says the task is done")
    G.require(not re.search(r"[\n\r\0]", line), "bad-done", "done must be one command line, not several: put the lines in a script and give its path")
    ok = parses(line)
    G.require(ok is not None, "bad-done", "done cannot be read: bash is not available")
    G.require(ok, "bad-done", "done %s is not a command line: bash cannot parse it (it reads as prose)" % ascii(line))
    words = D.command_words(line)
    G.require(words, "bad-done", "done %s is not a command: it has no command word" % ascii(line))
    builtins = shell_words()
    G.require(builtins is not None, "bad-done", "done cannot be read: bash is not available")
    for position, word in enumerate(words):
        if "$" in word or "`" in word:
            continue
        if "/" in word:
            if position:                 # a later command may follow a cd
                continue
            path = word[2:] if word.startswith("./") else word
            found = os.path.isfile(word) if word.startswith("/") else os.path.isfile(path) or in_scope(path, scope)
            G.require(found, "bad-done", "done %s is not a command: %s is not an existing script (it is not a file here, nor under a scope path)" % (ascii(line), ascii(word)))
        else:
            G.require(shutil.which(word) is not None or word in builtins, "bad-done",
                      "done %s is not a command: %s is not an executable, a shell builtin or an existing script (it reads as prose)" % (ascii(line), ascii(word)))


# ---- the plan ------------------------------------------------------------------------------------------------------------------------

def known_roles():
    """The roles `qargi role list` prints."""
    return [r for r in R.role_names() if R.role_dir(r) is not None]


def examine_node(i, node, col, roles):
    """The checks of one node. -> {id, after, scope, review} with None for what is not usable."""
    path = "$.nodes[%d]" % i
    info = dict(index=i, id=None, after=None, scope=None, review=None)
    if type(node) is not dict:
        col.add("not-an-object", "nodes[%d] is not an object" % i, path=path)
        return info
    for key in sorted(node):
        if key not in NODE_REQUIRED + NODE_OPTIONAL:
            col.add("unknown-key", "nodes[%d] has the key %s, which a node does not have" % (i, ascii(key)), path=path)
    ident = node.get("id")
    if "id" in node and slug(ident):
        info["id"] = ident
    named = [info["id"]] if info["id"] else []
    label = named[0] if named else "nodes[%d]" % i
    for key in NODE_REQUIRED:
        if key not in node:
            col.add("missing-key", "nodes[%d] has no %s" % (i, key), named, path)
    if "id" in node and not info["id"]:
        with col.guard(path + ".id"):
            G.require(False, "bad-id", "nodes[%d].id must be a lower case slug of letters, digits and single hyphens, at most %d characters" % (i, MAX_ID))
    with col.guard(path + ".task", named):
        if "task" in node:
            G.require(type(node["task"]) is str and node["task"].strip() != "", "bad-value", "the task of %s must be non-empty text" % label)
    with col.guard(path + ".role", named):
        if "role" in node:
            role = node["role"]
            G.require(type(role) is str and role != "", "bad-value", "the role of %s must be a role name" % label)
            G.require(role in roles, "unknown-role", "the role %s is not one qargi knows (qargi role list): %s" % (ascii(role), ", ".join(roles)))
    scope = node.get("scope")
    if "scope" in node:
        entries, clean = {}, False
        with col.guard(path + ".scope", named):
            G.require(type(scope) is list and 0 < len(scope) <= MAX_SCOPE, "bad-scope",
                      "the scope of %s must be a non-empty list of at most %d paths or globs" % (label, MAX_SCOPE))
            clean = True
            for k, entry in enumerate(scope):
                try:
                    entries[entry] = scope_entry(entry)
                except G.Invalid as e:
                    clean = False
                    col.add(e.code, str(e), named, "%s.scope[%d]" % (path, k))
        if clean:
            info["scope"] = sorted(entries.items())
    with col.guard(path + ".done", named):
        if "done" in node:
            check_done(node["done"], [e for e in scope if type(e) is str] if type(scope) is list else [])
    with col.guard(path + ".review_kind", named):
        if "review_kind" in node:
            G.require(type(node["review_kind"]) is str and node["review_kind"] in REVIEW_KINDS, "bad-review-kind",
                      "review_kind of %s must be one of %s" % (label, ", ".join(REVIEW_KINDS)))
            info["review"] = node["review_kind"]
    for key in ("profile", "runtime"):
        with col.guard("%s.%s" % (path, key), named):
            if key in node:
                G.require(type(node[key]) is str and WORD.fullmatch(node[key]) is not None, "bad-value",
                          "%s of %s must be a lower case word (letters, digits, hyphens)" % (key, label))
    if "after" in node:
        with col.guard(path + ".after", named):
            after = node["after"]
            G.require(type(after) is list and all(slug(x) for x in after), "bad-after", "after of %s must be a list of node ids" % label)
            G.require(len(set(after)) == len(after), "bad-after", "after of %s names a node twice" % label)
            info["after"] = list(after)
    else:
        info["after"] = []
    return info


def find_cycle(nodes, after):
    """One cycle among nodes (ids) given each node's `after`: the shortest one through the smallest node that lies on a cycle, as [a, b, ...] where
    every node comes after the next and the last comes after the first. Explicit queue."""
    groups = [g for g in G.components(nodes, [{"from": n, "to": d} for n in nodes for d in after[n]]) if len(g) > 1]
    group = min(groups)
    inside = set(group)
    start = group[0]
    parents = {}
    queue = deque([start])
    while queue:
        node = queue.popleft()
        for dep in sorted(after[node]):
            if dep not in inside:
                continue
            if dep == start:
                path = [node]
                while path[-1] != start:
                    path.append(parents[path[-1]])
                return list(reversed(path))
            if dep not in parents:
                parents[dep] = node
                queue.append(dep)
    return group


def waves_of(order, after):
    level = {}
    for node in order:
        level[node] = 1 + max((level[d] for d in after[node]), default=0)
    waves = defaultdict(list)
    for node in order:
        waves[level[node]].append(node)
    return [sorted(waves[k]) for k in sorted(waves)]


def ancestors(order, after):
    """Every node a node comes after, directly or through others (the order lists prerequisites first)."""
    anc = {}
    for node in order:
        mine = set()
        for dep in after[node]:
            mine.add(dep)
            mine |= anc[dep]
        anc[node] = mine
    return anc


def examine(doc, col, report, roles):
    G.require(type(doc) is dict, "not-an-object", "a run plan is one JSON object")
    for key in sorted(doc):
        if key not in TOP_KEYS:
            col.add("unknown-key", "the plan has the key %s, which a plan does not have" % ascii(key))
    G.require(doc.get("kind") == PLAN_KIND, "wrong-kind", "kind must be %s" % PLAN_KIND)
    G.require(type(doc.get("schema")) is int and doc["schema"] == SCHEMA, "wrong-schema", "schema must be the integer %d" % SCHEMA)
    for key in TOP_KEYS:
        if key not in doc:
            col.add("missing-key", "the plan has no %s" % key)
    with col.guard("$.project"):
        if "project" in doc:
            G.require(type(doc["project"]) is str and PROJECT_NAME.fullmatch(doc["project"]) is not None, "bad-value",
                      "project must be a project name: lower case letters and digits, starting with a letter, at most 24")
            report["project"] = doc["project"]
    with col.guard("$.target_feature"):
        if "target_feature" in doc:
            G.require(feature_name(doc["target_feature"]), "bad-value",
                      "target_feature must be a feature name: a lower case slug of at most %d characters, not master or develop" % MAX_ID)
            report["target_feature"] = doc["target_feature"]
    if "nodes" not in doc:
        return
    nodes = doc["nodes"]
    with col.guard("$.nodes"):
        G.require(type(nodes) is list, "bad-value", "nodes must be a list of task nodes")
        report["nodes"] = len(nodes)
        G.require(nodes, "empty-nodes", "nodes is empty: a plan has at least one task node")
        G.require(len(nodes) <= MAX_NODES, "too-many-nodes", "a plan has at most %d nodes" % MAX_NODES)
    if type(nodes) is not list or not nodes or len(nodes) > MAX_NODES:
        return
    infos = [examine_node(i, node, col, roles) for i, node in enumerate(nodes)]
    sound = all(info["id"] and info["after"] is not None for info in infos)
    where = defaultdict(list)
    for info in infos:
        if info["id"]:
            where[info["id"]].append(info["index"])
    for ident in sorted(where):
        if len(where[ident]) > 1:
            sound = False
            col.add("duplicate-id", "the node id %s is used by %s" % (ident, ", ".join("nodes[%d]" % k for k in where[ident])), [ident], "$.nodes[%d].id" % where[ident][1])
    ids = set(where)
    for info in infos:
        if info["id"] is None or info["after"] is None:
            continue
        for dep in info["after"]:
            path = "$.nodes[%d].after" % info["index"]
            if dep == info["id"]:
                sound = False
                col.add("self-after", "the node %s comes after itself" % dep, [dep], path)
            elif dep not in ids:
                sound = False
                col.add("unknown-after", "the node %s comes after %s, which is no node of the plan" % (info["id"], dep), [info["id"]], path)
    for info in infos:
        if info["review"] in REVIEW_KINDS[1:] and info["id"]:
            col.add("review-requested", "the node %s has review_kind %s: the checker only notes it, a review is a task of its own" % (info["id"], info["review"]),
                    [info["id"]], "$.nodes[%d].review_kind" % info["index"], "note")
    if not sound:
        return
    after = {info["id"]: info["after"] for info in infos}
    names = sorted(after)
    order = G.order(names, [{"from": n, "to": d} for n in names for d in after[n]])
    if len(order) != len(names):
        cycle = find_cycle(names, after)
        col.add("cycle", "the nodes come after each other in a circle: %s" % " after ".join(cycle + [cycle[0]]), sorted(cycle), "$.nodes", cycle=cycle)
        return
    report["waves"] = waves_of(order, after)
    anc = ancestors(order, after)
    scopes = {info["id"]: info["scope"] for info in infos if info["scope"]}
    for x in range(len(names)):
        for y in range(x + 1, len(names)):
            a, b = names[x], names[y]
            if a not in scopes or b not in scopes or a in anc[b] or b in anc[a]:
                continue
            hit = next(((ta, tb) for ta, pa in scopes[a] for tb, pb in scopes[b] if scopes_overlap(pa, pb)), None)
            if hit:
                both = normal(hit[0]) == normal(hit[1]) and normal(hit[0]) in SHARED
                col.add("scope-overlap-unordered",
                        "the nodes %s and %s are not ordered by after and their scopes can touch the same path: %s and %s%s" % (
                            a, b, hit[0], hit[1], " (a file most tasks change: declare it in the scope of the task that changes it, and order those tasks)" if both else
                            " (order them with after, or narrow the scopes)"),
                        [a, b], "$.nodes", patterns=[hit[0], hit[1]])


def check_bytes(raw, roles=None):
    """The report of the bytes of a plan: a dict of the kind qargi-run-plan-check."""
    report = dict(schema=SCHEMA, kind=CHECK_KIND, valid=False, digest=G.digest(raw), project=None, target_feature=None, nodes=0, waves=[], findings=[])
    col = Findings()
    try:
        if len(raw) > MAX_BYTES:
            raise G.Invalid("too-large", "the plan is over %d bytes" % MAX_BYTES)
        examine(G.load_json(raw), col, report, known_roles() if roles is None else roles)
    except G.Invalid as e:
        details = dict(e.details)
        col.add(e.code, str(e), details.pop("nodes", ()), details.pop("path", "$"), **details)
    report["findings"] = col.sorted()
    report["valid"] = not col.errors()
    return report


# ---- output --------------------------------------------------------------------------------------------------------------------------

def text_report(report):
    lines = ["run plan check: %s" % ("valid" if report["valid"] else "invalid")]
    if report["project"] is not None or report["target_feature"] is not None or report["nodes"]:
        lines.append("  project %s, target feature %s, %d node%s" % (report["project"] or "-", report["target_feature"] or "-", report["nodes"], "" if report["nodes"] == 1 else "s"))
    if report["waves"]:
        lines.append("  waves (a wave starts when the ones before it are done):")
        for k, wave in enumerate(report["waves"], 1):
            lines.append("    wave %d: %s" % (k, ", ".join(wave)))
    for f in report["findings"]:
        lines.append("  %s %s%s: %s" % (f["severity"], f["code"], " [%s]" % ", ".join(f["nodes"]) if f["nodes"] else "", G.text_value(f["message"])))
    return "\n".join(lines) + "\n"


def json_document(report):
    """The text of the document, checked against the registry file of its kind before anything is printed. -> (text, None) or (None, why)."""
    try:
        text = json.dumps(report, sort_keys=True, ensure_ascii=True, indent=1, allow_nan=False) + "\n"
    except (ValueError, TypeError) as e:
        return None, "the document of %s cannot be written as JSON (%s)" % (CHECK_KIND, e)
    try:
        found = K.validate(K.registry_path(CHECK_KIND), text)
    except K.RegistryError as e:
        return None, "the document of %s cannot be checked: %s" % (CHECK_KIND, e)
    if found:
        return None, "the document of %s breaks its registry file at %s %s: %s" % (CHECK_KIND, found[0].rule, found[0].path, found[0].message)
    return text, None


def main(argv):
    parser = argparse.ArgumentParser(prog="qargi flow", allow_abbrev=False)
    parser.add_argument("group", choices=("plan",))
    parser.add_argument("action", choices=("check",))
    parser.add_argument("file")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        with open(args.file, "rb") as stream:
            raw = stream.read(MAX_BYTES + 1)
    except (OSError, ValueError) as e:
        print("qargi: cannot read %s: %s" % (args.file, e.strerror if isinstance(e, OSError) and e.strerror else e), file=sys.stderr)
        return 2
    report = check_bytes(raw)
    if args.json:
        text, why = json_document(report)
        if text is None:
            print("qargi: %s; this is a defect of qargi, not of the plan" % why, file=sys.stderr)
            return 70
    else:
        text = text_report(report)
    try:
        sys.stdout.write(text)
        sys.stdout.flush()
    except (OSError, ValueError) as e:
        print("qargi: cannot write the report: %s" % (getattr(e, "strerror", None) or e), file=sys.stderr)
        return 1
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
