#!/usr/bin/env python3
"""Read-only backlog graph v1. See docs/reference/backlog-graph.md.

No source observation beyond the configured open backlog, and no authority to
approve or execute anything. Traversals use explicit queues/stacks, never Python
recursion. Reports are deterministic for a fixed pair of input byte streams.
"""
import argparse
from collections import defaultdict, deque
from datetime import date, datetime
import hashlib
import heapq
import json
import os
from pathlib import Path
import re
import sys

# -I does not put the script's directory on sys.path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backlog as B  # noqa: E402
import paths as P  # noqa: E402

SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
DAY = r"[0-9]{4}-[0-9]{2}-[0-9]{2}"
STAMP = re.compile(DAY + r"[Tt](?:[01][0-9]|2[0-3]):[0-9]{2}(?::[0-9]{2}(?:[.,][0-9]+)?)?(?:[Zz]|[+-](?:[01][0-9]|2[0-3]):[0-5][0-9])?")


class Invalid(Exception):
    def __init__(self, code, message, **details):
        self.code = code
        self.details = details
        super().__init__(message)


def require(ok, code, message):
    if not ok:
        raise Invalid(code, message)


def fields(value, keys):
    require(type(value) is dict and set(value) == set(keys.split()),
            "schema", "expected exactly these object fields: " + keys)


def words(value):
    return type(value) is str and bool(value.strip())


def scalar_words(value):
    require(words(value), "provenance", "by/basis/ref must have words")
    require(all(not 0xD800 <= ord(c) <= 0xDFFF for c in value),
            "provenance", "by/basis/ref must contain only Unicode scalar values")


def at(value):
    require(type(value) is str, "provenance", "at must be an ISO8601 date or timestamp")
    try:
        if re.fullmatch(DAY, value):
            date.fromisoformat(value)
        else:
            require(STAMP.fullmatch(value), "provenance", "at must be an ISO8601 date or timestamp")
            datetime.fromisoformat(value.upper())
    except ValueError:
        raise Invalid("provenance", "at must be a valid ISO8601 date or timestamp") from None


def typed_ref(value):
    require(type(value) is str, "typed-ref", "node reference must be a string")
    kind, sep, name = value.partition(":")
    if kind == "backlog" and sep:
        # Use the actual parser grammar, including its two-character minimum.
        match = B.ID_FORM.fullmatch("[" + name + "] item")
        ok = match is not None and match.group(1) == name
    elif kind == "feature" and sep:
        # feature.sh: single hyphens, at most 40, no long-lived branch names.
        ok = 0 < len(name) <= 40 and SLUG.fullmatch(name) and name not in {"master", "develop"}
    else:
        ok = False
    require(ok, "typed-ref", "invalid typed node reference: " + value)


def pairs(items):
    obj = {}
    for key, value in items:
        require(key not in obj, "duplicate-json-key", "duplicate JSON key: " + key)
        obj[key] = value
    return obj


def load_json(raw):
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                          parse_constant=lambda _: reject_constant())
    except (ValueError, UnicodeError, RecursionError) as e:
        raise Invalid("invalid-json", "cannot decode JSON: " + str(e)) from None


def reject_constant():
    raise Invalid("invalid-json", "non-JSON numeric constant")


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_input(report, kind, path):
    report["inputs"][kind]["path"] = str(path) if path is not None else None
    require(path is not None, "configuration", "backlog.file is not configured")
    try:
        with open(path, "rb") as stream:
            raw = stream.read()
    except (OSError, ValueError) as e:
        # NUL paths and unencodable names (UnicodeEncodeError) raise ValueError.
        reason = e.strerror if isinstance(e, OSError) else str(e)
        raise Invalid("input-unreadable", "cannot read %s: %s" % (path, reason)) from None
    report["inputs"][kind]["digest"] = digest(raw)
    return raw


def validate(graph):
    fields(graph, "format version nodes relations evidence")
    require(type(graph["format"]) is str and graph["format"] == "backlog-graph",
            "schema", "format must be backlog-graph")
    require(type(graph["version"]) is int and graph["version"] == 1, "version", "version must be integer 1")
    for key in ("nodes", "relations", "evidence"):
        require(type(graph[key]) is list, "schema", key + " must be an array")
    nodes = set()
    for node in graph["nodes"]:
        typed_ref(node)
        require(node not in nodes, "duplicate-node", "duplicate node: " + node)
        nodes.add(node)
    ids, semantics = set(), set()
    for entry in graph["relations"] + graph["evidence"]:
        require(type(entry) is dict, "schema", "relation/evidence must be an object")
        ident = entry.get("id")
        require(type(ident) is str and SLUG.fullmatch(ident), "schema", "id must be a lowercase slug")
        require(ident not in ids, "duplicate-id", "duplicate relation/evidence id: " + ident)
        ids.add(ident)
    for rel in graph["relations"]:
        fields(rel, "id kind from to status provenance")
        require(type(rel["kind"]) is str and rel["kind"] in ("requires", "contains"), "schema", "unknown relation kind")
        require(type(rel["status"]) is str and rel["status"] in ("confirmed", "proposed"), "schema", "unknown relation status")
        for key in ("from", "to"):
            typed_ref(rel[key])
            require(rel[key] in nodes, "endpoint", "undeclared endpoint: " + rel[key])
        require(rel["from"] != rel["to"], "self-edge", "self relation: " + rel["id"])
        semantic = (rel["kind"], rel["from"], rel["to"])
        require(semantic not in semantics, "duplicate-relation", "duplicate relation semantics: " + rel["id"])
        semantics.add(semantic)
        fields(rel["provenance"], "by at basis")
        for key in ("by", "basis"):
            scalar_words(rel["provenance"][key])
        at(rel["provenance"]["at"])
    for ev in graph["evidence"]:
        fields(ev, "id node level for_digest ref by at")
        typed_ref(ev["node"])
        require(ev["node"] in nodes, "endpoint", "undeclared evidence node: " + ev["node"])
        require(ev["node"].startswith("backlog:"), "feature-evidence", "feature evidence is unsupported")
        require(type(ev["level"]) is str and ev["level"] == "reported", "schema", "only reported evidence is supported")
        require(type(ev["for_digest"]) is str and DIGEST.fullmatch(ev["for_digest"]), "schema", "for_digest must be sha256: and 64 lowercase hex digits")
        for key in ("ref", "by"):
            scalar_words(ev[key])
        at(ev["at"])
    return sorted(nodes), sorted(graph["relations"], key=lambda r: r["id"]), sorted(graph["evidence"], key=lambda e: e["id"])


def order(nodes, edges):
    """Prerequisites first, or a short result if cyclic (Kahn, O(V+E log V))."""
    pending = dict.fromkeys(nodes, 0)
    users = defaultdict(list)
    for rel in edges:
        pending[rel["from"]] += 1
        users[rel["to"]].append(rel["from"])
    ready = [n for n in nodes if not pending[n]]
    heapq.heapify(ready)
    result = []
    while ready:
        node = heapq.heappop(ready)
        result.append(node)
        for user in users[node]:
            pending[user] -= 1
            if not pending[user]:
                heapq.heappush(ready, user)
    return result


def components(nodes, edges):
    """Iterative Kosaraju; proposed cycles get bounded, precise diagnostics."""
    forward, reverse = defaultdict(list), defaultdict(list)
    for r in edges:
        forward[r["from"]].append(r["to"])
        reverse[r["to"]].append(r["from"])
    seen, finish = set(), []
    for root in nodes:
        if root in seen:
            continue
        seen.add(root)
        stack = [(root, iter(forward[root]))]
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                finish.append(node)
                stack.pop()
            elif child not in seen:
                seen.add(child)
                stack.append((child, iter(forward[child])))
    groups, assigned = [], set()
    for root in reversed(finish):
        if root in assigned:
            continue
        group, todo = [], [root]
        assigned.add(root)
        while todo:
            node = todo.pop()
            group.append(node)
            for child in reverse[node]:
                if child not in assigned:
                    assigned.add(child)
                    todo.append(child)
        groups.append(sorted(group))
    return groups


def finding(report, code, message, **details):
    report["findings"].append(dict(code=code, severity="warning", message=message, **details))


def structure(report, nodes, relations):
    for kind in ("requires", "contains"):
        edges = [r for r in relations if r["kind"] == kind]
        confirmed = [r for r in edges if r["status"] == "confirmed"]
        if len(order(nodes, confirmed)) != len(nodes):
            groups = components(nodes, confirmed)
            membership = {n: i for i, group in enumerate(groups) for n in group if len(group) > 1}
            cycle_edges = [r["id"] for r in confirmed if r["from"] in membership
                           and membership[r["from"]] == membership.get(r["to"])]
            raise Invalid(kind + "-cycle", "confirmed " + kind + " cycle",
                          kind=kind, nodes=sorted(membership), relations=sorted(cycle_edges))
        if kind == "contains":
            parents = defaultdict(list)
            for r in confirmed:
                parents[r["to"]].append(r)
            for child in sorted(parents):
                incoming = parents[child]
                if len(incoming) > 1:
                    raise Invalid("contains-multiple-parents", "multiple confirmed parents: " + child,
                                  kind=kind, node=child,
                                  nodes=sorted({child} | {r["from"] for r in incoming}),
                                  relations=sorted(r["id"] for r in incoming))
        # A cycle warning names only the proposals participating in that cycle.
        groups = components(nodes, edges)
        membership = {n: i for i, group in enumerate(groups) for n in group}
        cycle_ids = defaultdict(list)
        for r in edges:
            i = membership[r["from"]]
            if r["status"] == "proposed" and i == membership[r["to"]] and len(groups[i]) > 1:
                cycle_ids[i].append(r["id"])
        for i, ids in cycle_ids.items():
            finding(report, "proposed-cycle", "proposed edges participate in a " + kind + " cycle",
                    kind=kind, nodes=groups[i], relations=sorted(ids))


def literal_home(path):
    """Use a raw HOME prefix; Bash patsub_replacement can differ for '&'."""
    if path.startswith("~"):
        return os.environ.get("HOME", "") + path[1:]
    return path


def absolute_path(path):
    """Prefix cwd without changing the kernel's symlink/.. traversal."""
    if os.path.isabs(path):
        return path
    try:
        return os.getcwd() + "/" + path
    except OSError as e:
        raise Invalid("input-unreadable", "cannot resolve path %s: %s" % (path, e.strerror)) from None


def project_source(project):
    if not project:
        from help import infer_project
        project = infer_project()
    require(words(project) and re.fullmatch(r"[a-z][a-z0-9]{0,23}", project), "configuration", "name a project with --project P")
    try:
        config = json.loads((Path(P.conf()) / "projects" / (project + ".json")).read_text(encoding="utf-8"))
        repo = config.get("repo", {}).get("path")
        backlog = config.get("backlog") or {}
        path, section = backlog.get("file"), backlog.get("section")
    except (OSError, ValueError, AttributeError, TypeError, RecursionError) as e:
        raise Invalid("configuration", "cannot read project backlog configuration: " + str(e)) from None
    require(words(repo), "configuration", "repo.path is not configured")
    require(path is None or words(path), "configuration", "backlog.file must be a path")
    if section is None or section is False or section == "":
        section = None
    require(section is None or words(section), "configuration", "backlog.section must name a heading")
    if path is not None:
        path = literal_home(path)
        if not os.path.isabs(path):
            path = literal_home(repo) + "/" + path
        path = absolute_path(path)
    return path, section


def observe(report, raw, section):
    try:
        # Match read_lines' universal newline handling before splitting.
        lines = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    except UnicodeError:
        raise Invalid("source-unreadable", "backlog is not UTF-8") from None
    items = B.parse(lines)
    duplicate, _ = B.duplicates(items)
    require(not duplicate, "duplicate-backlog-id", "duplicate backlog IDs: " + ", ".join(sorted(duplicate)))
    try:
        selected = {it["start"] for it in B.parse(lines, section)} if section else {it["start"] for it in items}
    except B.BacklogError as e:
        raise Invalid("source-section", str(e)) from None
    return {"backlog:" + it["id"]: dict(digest=digest("\n".join(it["full"]).encode("utf-8")),
            line=it["line"], in_section=it["start"] in selected) for it in items if it["id"]}


def project(report, nodes, relations, evidence, sources):
    ev_by_node = defaultdict(list)
    for ev in evidence:
        current = sources.get(ev["node"], {}).get("digest") == ev["for_digest"]
        record = dict(ev, state="current" if current else "superseded")
        report["evidence"].append(record)
        ev_by_node[ev["node"]].append(record)
        if not current:
            finding(report, "evidence-superseded", "reported evidence does not match an open source revision",
                    node=ev["node"], evidence=ev["id"])
    needs = defaultdict(list)
    for r in relations:
        if r["kind"] == "requires":
            needs[r["from"]].append(r)
    records = {}
    confirmed = [r for r in relations if r["kind"] == "requires" and r["status"] == "confirmed"]
    for node in order(nodes, confirmed):
        source = sources.get(node)
        reasons = []
        if source is None:
            code = "feature-not-observed" if node.startswith("feature:") else "source-not-open"
            reasons.append(dict(code=code))
            finding(report, code, "source is not observed in the configured open backlog", node=node)
        evs = ev_by_node[node]
        own = any(e["state"] == "current" for e in evs)
        if not own:
            reasons.append(dict(code="no-current-reported"))
        stale = [e["id"] for e in evs if e["state"] == "superseded"]
        if stale:
            reasons.append(dict(code="evidence-superseded", evidence=stale))
        unknown, proposed = [], []
        for r in needs[node]:
            if r["status"] == "proposed":
                proposed.append(r["id"])
                reasons.append(dict(code="proposed-need", relation=r["id"], node=r["to"]))
            elif records[r["to"]]["effective"] != "reported":
                unknown.append(r["id"])
                reasons.append(dict(code="prerequisite-unknown", relation=r["id"], node=r["to"]))
        planning = "proposed" if proposed else "unknown" if unknown else "reported" if needs[node] else "unconstrained"
        records[node] = dict(ref=node, source=source, own="reported" if own else "unknown",
                             effective="reported" if own and not unknown else "unknown",
                             prerequisites=planning, reasons=reasons)
    report["nodes"] = [records[n] for n in nodes]
    return records, needs


def explain(node, records, needs):
    """One shortest path per reachable need, tied by sorted relation ID.

    Include proposals for explanation, without treating them as confirmed needs.
    A visited set bounds traversal even when proposals form cycles.
    """
    parents = {node: None}
    todo, result = deque([node]), []
    while todo:
        current = todo.popleft()
        reasons = records[current]["reasons"]
        if reasons:
            path, edge_ids, cursor = [], [], current
            while cursor is not None:
                path.append(cursor)
                parent = parents[cursor]
                if parent is None:
                    break
                cursor, edge = parent
                edge_ids.append(edge)
            result.append(dict(node=current, path=list(reversed(path)), relations=list(reversed(edge_ids)), reasons=reasons))
        for r in needs[current]:
            if r["to"] not in parents:
                parents[r["to"]] = (current, r["id"])
                todo.append(r["to"])
    return sorted(result, key=lambda item: (len(item["path"]), item["path"], item["relations"]))


def report_for(command, graph_path, backlog_path, section=None, node=None):
    report = dict(format="backlog-graph-report", version=1, command=command, valid=False,
                  inputs={"graph": dict(path=str(graph_path), digest=None),
                          "backlog": dict(path=backlog_path, digest=None)},
                  findings=[], nodes=[], relations=[], evidence=[])
    try:
        raw_graph = read_input(report, "graph", graph_path)
        raw_backlog = read_input(report, "backlog", backlog_path)
        nodes, relations, evidence = validate(load_json(raw_graph))
        structure(report, nodes, relations)
        sources = observe(report, raw_backlog, section)
        if command == "why":
            require(node in nodes, "unknown-node", "why needs a declared node: " + str(node))
        report["relations"] = relations
        records, needs = project(report, nodes, relations, evidence, sources)
        if command == "why":
            report["node"] = node
            report["why"] = explain(node, records, needs)
        report["valid"] = True
    except Invalid as e:
        report["findings"].append(dict(code=e.code, severity="error", message=str(e), **e.details))
    report["findings"].sort(key=lambda f: json.dumps(f, sort_keys=True))
    return report


def text_value(value):
    """Keep printable Unicode, escaping controls and output encoding failures."""
    escaped = "".join(c if c.isprintable() else ascii(c)[1:-1] for c in value)
    encoding = sys.stdout.encoding or "utf-8"
    return escaped.encode(encoding, "backslashreplace").decode(encoding)


def text_report(report):
    print("backlog graph %s: %s" % (report["command"], "valid" if report["valid"] else "invalid"))
    if report["command"] in ("show", "why"):
        for n in report["nodes"]:
            if report["command"] == "why" and n["ref"] != report.get("node"):
                continue
            print("  %s: own %s; effective %s; prerequisites %s" % (n["ref"], n["own"], n["effective"], n["prerequisites"]))
    # Other slots contain constants, validated ASCII typed refs, or slug IDs.
    # Finding messages can contain arbitrary input paths, keys and references.
    for f in report["findings"]:
        message = text_value(f["message"])
        if "nodes" in f:
            message += " (nodes " + ", ".join(f["nodes"]) + ")"
        if "relations" in f:
            message += " (relations " + ", ".join(f["relations"]) + ")"
        print("  %s: %s%s" % (f["code"], f["node"] + " " if "node" in f else "", message))
    for why in report.get("why", []):
        print("  %s: %s%s" % (" -> ".join(why["path"]),
              ", ".join(r["code"] + (" (" + r["relation"] + ")" if "relation" in r else "") for r in why["reasons"]),
              " via " + ", ".join(why["relations"]) if why["relations"] else ""))


def main(argv):
    parser = argparse.ArgumentParser(prog="qargi backlog graph", allow_abbrev=False)
    parser.add_argument("command", choices=("check", "show", "why"))
    parser.add_argument("--graph", required=True)
    parser.add_argument("--node")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (args.command == "why") != (args.node is not None):
        parser.error("--node REF is required for why and belongs only to why")
    graph_path = args.graph
    try:
        graph_path = absolute_path(graph_path)
        backlog_path, section = project_source(args.project)
    except Invalid as e:
        report = dict(format="backlog-graph-report", version=1, command=args.command, valid=False,
                      inputs={"graph": dict(path=graph_path, digest=None), "backlog": dict(path=None, digest=None)},
                      findings=[dict(code=e.code, severity="error", message=str(e))], nodes=[], relations=[], evidence=[])
    else:
        report = report_for(args.command, graph_path, backlog_path, section, args.node)
    if args.json:
        print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    else:
        text_report(report)
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
