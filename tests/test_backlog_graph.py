#!/usr/bin/env python3
"""Native graph v1 validation, conservative projections and public read-only CLI."""
import hermetic  # noqa: F401
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import backlog_graph as G  # noqa: E402


def graph(*nodes):
    return dict(format="backlog-graph", version=1, nodes=list(nodes), relations=[], evidence=[])


def relation(ident, source, target, kind="requires", status="confirmed"):
    return dict(id=ident, kind=kind, **{"from": source, "to": target}, status=status,
                provenance=dict(by="reviewer", at="2026-11-14", basis="manual declaration"))


def evidence(ident, node, full):
    return dict(id=ident, node=node, level="reported", for_digest=G.digest(full.encode()),
                ref="test-log.txt", by="worker", at="2026-11-14T12:34:56Z")


class Graph(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.backlog = self.root / "backlog.md"
        self.file = self.root / "graph.json"
        self.backlog.write_text("## Now\n- [aa] A\n  detail\n## Later\n- [bb] B\n- [cc] C\n", encoding="utf-8")

    def report(self, value, command="show", node=None, section=None):
        self.file.write_text(json.dumps(value), encoding="utf-8")
        return G.report_for(command, str(self.file), str(self.backlog), section, node)

    def invalid(self, value, code):
        report = self.report(value)
        self.assertFalse(report["valid"], report)
        self.assertIn(code, [f["code"] for f in report["findings"]], report)

    def test_empty_and_byte_digests(self):
        r = self.report(graph())
        self.assertTrue(r["valid"])
        self.assertEqual(r["inputs"]["graph"]["digest"], "sha256:" + hashlib.sha256(self.file.read_bytes()).hexdigest())
        self.assertEqual(r["inputs"]["backlog"]["digest"], G.digest(self.backlog.read_bytes()))
        self.assertEqual(r["format"], "backlog-graph-report")
        self.assertEqual(r["version"], 1)

    def test_closed_schema_and_strict_types(self):
        base = graph("backlog:aa")
        for key in base:
            value = copy.deepcopy(base)
            del value[key]
            self.invalid(value, "schema")
        for key, bad in (("extra", None), ("nodes", {}), ("relations", None), ("evidence", {}),
                         ("format", "other"), ("version", True), ("version", 1.0), ("version", 2), ("version", "1")):
            with self.subTest(key=key, bad=bad):
                value = copy.deepcopy(base)
                value[key] = bad
                self.invalid(value, "version" if key == "version" else "schema")
        for value in ([], None, True):
            self.invalid(value, "schema")

    def test_typed_refs_match_source_grammars(self):
        for ref in ("backlog:aa", "backlog:0-0", "backlog:a--b", "feature:a", "feature:0", "feature:" + "a" * 40):
            self.assertTrue(self.report(graph(ref))["valid"], ref)
        for ref in (None, True, "aa", "other:aa", "backlog:a", "backlog:UP", "backlog:a-", "backlog:aa] item",
                    "feature:master", "feature:develop", "feature:aa--bb", "feature:-aa", "feature:aa_1",
                    "feature:AA", "feature:" + "a" * 41, "feature:a/b", "backlog:a:b"):
            with self.subTest(ref=ref):
                self.invalid(graph(ref), "typed-ref")

    def test_duplicate_json_keys_at_every_level_and_malformed_json(self):
        valid = graph("backlog:aa", "backlog:bb")
        valid["relations"] = [relation("need", "backlog:aa", "backlog:bb")]
        raw = json.dumps(valid)
        for old, new in (('"version": 1', '"version": 1, "version": 1'),
                         ('"id": "need"', '"id": "need", "id": "other"'),
                         ('"by": "reviewer"', '"by": "reviewer", "by": "other"')):
            self.file.write_text(raw.replace(old, new))
            report = G.report_for("check", str(self.file), str(self.backlog))
            self.assertEqual(report["findings"][0]["code"], "duplicate-json-key")
        for raw in ('{', '{"nodes": NaN}', 'Infinity'):
            self.file.write_text(raw)
            self.assertEqual(G.report_for("check", str(self.file), str(self.backlog))["findings"][0]["code"], "invalid-json")
        self.file.write_bytes(b'\xff')
        self.assertFalse(G.report_for("check", str(self.file), str(self.backlog))["valid"])

    def test_duplicate_nodes_ids_semantics_and_endpoints(self):
        self.invalid(graph("backlog:aa", "backlog:aa"), "duplicate-node")
        value = graph("backlog:aa", "backlog:bb")
        value["relations"] = [relation("need", "backlog:aa", "backlog:bb")]
        for key, bad, code in (("to", "backlog:cc", "endpoint"), ("to", "backlog:aa", "self-edge"),
                               ("kind", "related", "schema"), ("status", "accepted", "schema"), ("id", "Bad", "schema")):
            variant = copy.deepcopy(value)
            variant["relations"][0][key] = bad
            self.invalid(variant, code)
        other = copy.deepcopy(value)
        other["relations"].append(relation("need", "backlog:bb", "backlog:aa"))
        self.invalid(other, "duplicate-id")
        other = copy.deepcopy(value)
        other["relations"].append(relation("same", "backlog:aa", "backlog:bb", status="proposed"))
        self.invalid(other, "duplicate-relation")
        value["evidence"] = [evidence("need", "backlog:aa", "- [aa] A\n  detail")]
        self.invalid(value, "duplicate-id")
        value["relations"] = []
        value["evidence"] *= 2
        self.invalid(value, "duplicate-id")

    def test_all_relation_evidence_and_provenance_fields_required(self):
        value = graph("backlog:aa", "backlog:bb")
        value["relations"] = [relation("need", "backlog:aa", "backlog:bb")]
        value["evidence"] = [evidence("report", "backlog:aa", "- [aa] A\n  detail")]
        for collection in ("relations", "evidence"):
            for key in value[collection][0]:
                variant = copy.deepcopy(value)
                del variant[collection][0][key]
                self.assertFalse(self.report(variant)["valid"], (collection, key))
            variant = copy.deepcopy(value)
            variant[collection][0]["extra"] = True
            self.invalid(variant, "schema")
        for key in ("by", "at", "basis"):
            for bad in (None, 1, True, "", "  "):
                variant = copy.deepcopy(value)
                variant["relations"][0]["provenance"][key] = bad
                self.invalid(variant, "provenance")
            variant = copy.deepcopy(value)
            del variant["relations"][0]["provenance"][key]
            self.invalid(variant, "schema")
        variant = copy.deepcopy(value)
        variant["relations"][0]["provenance"]["extra"] = "x"
        self.invalid(variant, "schema")
        for bad in ("2026-02-30", "yesterday", "2026-11-14T25:00:00Z", "2026-11-14T12:30:00+01:99", "2026-11-14 extra", "20261114"):
            variant = copy.deepcopy(value)
            variant["evidence"][0]["at"] = bad
            self.invalid(variant, "provenance")
        for good in ("2026-11-14", "2026-11-14T12:34:56", "2026-11-14T12:34:56.123+01:30", "2026-11-14T12:30Z"):
            variant = copy.deepcopy(value)
            variant["evidence"][0]["at"] = good
            self.assertTrue(self.report(variant)["valid"])

    def test_evidence_is_report_only_and_feature_evidence_unsupported(self):
        value = graph("backlog:aa")
        value["evidence"] = [evidence("report", "backlog:aa", "- [aa] A\n  detail")]
        for key, bad, code in (("level", "accepted", "schema"), ("level", "runnable", "schema"),
                               ("for_digest", "a" * 64, "schema"), ("for_digest", "sha256:" + "A" * 64, "schema"),
                               ("for_digest", True, "schema"), ("node", "backlog:bb", "endpoint"),
                               ("ref", "", "provenance"), ("by", None, "provenance")):
            variant = copy.deepcopy(value)
            variant["evidence"][0][key] = bad
            self.invalid(variant, code)
        r = self.report(value)
        self.assertEqual(r["nodes"][0]["effective"], "reported")
        self.assertNotIn("accepted", json.dumps(r))
        self.assertNotIn("runnable", json.dumps(r))
        value["nodes"].append("feature:one")
        value["evidence"][0]["node"] = "feature:one"
        self.invalid(value, "feature-evidence")

    def test_cycles_and_multiple_structural_parents(self):
        for kind in ("requires", "contains"):
            value = graph("backlog:aa", "backlog:bb", "backlog:cc")
            value["relations"] = [relation("ab", "backlog:aa", "backlog:bb", kind),
                                  relation("ba", "backlog:bb", "backlog:aa", kind)]
            self.invalid(value, kind + "-cycle")
            value["relations"][1] = relation("cb", "backlog:cc", "backlog:bb", kind)
            if kind == "contains":
                self.invalid(value, "contains-multiple-parents")
            else:
                self.assertTrue(self.report(value)["valid"])

    def test_proposed_cycles_warn_and_why_terminates(self):
        for kind in ("requires", "contains"):
            value = graph("backlog:aa", "backlog:bb", "feature:unseen")
            value["relations"] = [relation("ab", "backlog:aa", "backlog:bb", kind),
                                  relation("ba", "backlog:bb", "backlog:aa", kind, "proposed"),
                                  relation("bf", "backlog:bb", "feature:unseen", "requires", "proposed")]
            r = self.report(value, "why", "backlog:aa")
            self.assertTrue(r["valid"])
            warnings = [f for f in r["findings"] if f["code"] == "proposed-cycle"]
            self.assertEqual(warnings[0]["relations"], ["ba"])
            if kind == "requires":
                self.assertEqual(len(r["why"]), 3)
                self.assertIn("bf", json.dumps(r["why"]))
                self.assertIn("feature-not-observed", json.dumps(r["why"]))
                self.assertEqual(r["why"][-1]["path"], ["backlog:aa", "backlog:bb", "feature:unseen"])
            for edge in value["relations"]:
                edge["status"] = "proposed"
            self.assertTrue(self.report(value)["valid"])

    def test_structural_contains_never_changes_planning_or_effective(self):
        value = graph("backlog:aa", "backlog:bb")
        value["evidence"] = [evidence("aa-report", "backlog:aa", "- [aa] A\n  detail")]
        value["relations"] = [relation("parent", "backlog:aa", "backlog:bb", "contains")]
        aa, bb = self.report(value)["nodes"]
        self.assertEqual((aa["effective"], aa["prerequisites"]), ("reported", "unconstrained"))
        self.assertEqual((bb["effective"], bb["prerequisites"]), ("unknown", "unconstrained"))
        value["evidence"] = [evidence("bb-report", "backlog:bb", "- [bb] B")]
        aa, bb = self.report(value)["nodes"]
        self.assertEqual(aa["effective"], "unknown")
        self.assertEqual(bb["effective"], "reported")

    def test_projections_supersession_and_every_reason(self):
        value = graph("backlog:aa", "backlog:bb", "backlog:cc", "feature:unseen")
        value["evidence"] = [evidence("aa-report", "backlog:aa", "- [aa] A\n  detail"),
                             evidence("bb-report", "backlog:bb", "- [bb] B")]
        value["relations"] = [relation("need", "backlog:aa", "backlog:bb")]
        r = self.report(value)
        self.assertEqual((r["nodes"][0]["effective"], r["nodes"][0]["prerequisites"]), ("reported", "reported"))
        value["relations"].append(relation("proposal", "backlog:aa", "feature:unseen", status="proposed"))
        r = self.report(value)
        self.assertEqual((r["nodes"][0]["effective"], r["nodes"][0]["prerequisites"]), ("reported", "proposed"))
        self.backlog.write_text(self.backlog.read_text().replace("[bb] B", "[bb] Revised"))
        r = self.report(value, "why", "backlog:aa")
        self.assertEqual((r["nodes"][0]["own"], r["nodes"][0]["effective"], r["nodes"][0]["prerequisites"]),
                         ("reported", "unknown", "proposed"))
        self.assertEqual(r["evidence"][1]["state"], "superseded")
        self.assertIn("evidence-superseded", json.dumps(r["why"]))
        self.assertIn("prerequisite-unknown", json.dumps(r["why"]))
        self.assertIn("proposal", json.dumps(r["why"]))
        value["relations"].pop()
        self.assertEqual(self.report(value)["nodes"][0]["prerequisites"], "unknown")
        value["evidence"].append(evidence("new-bb", "backlog:bb", "- [bb] Revised"))
        r = self.report(value)
        self.assertEqual(r["nodes"][0]["effective"], "reported")
        self.assertEqual([e["state"] for e in r["evidence"]], ["current", "superseded", "current"])

    def test_missing_archived_same_id_and_reflow(self):
        value = graph("backlog:bb")
        value["evidence"] = [evidence("old", "backlog:bb", "- [bb] B")]
        (self.root / "backlog-archive-2026-11.md").write_text("- [bb] B\n")
        self.backlog.write_text("- [aa] A\n")
        r = self.report(value)
        self.assertTrue(r["valid"])
        self.assertEqual(r["nodes"][0]["effective"], "unknown")
        self.assertIn("source-not-open", json.dumps(r))
        for text in ("- [bb] different work\n", "- [bb] B\n  reflow\n"):
            self.backlog.write_text(text)
            r = self.report(value)
            self.assertEqual(r["evidence"][0]["state"], "superseded")
        self.backlog.write_text("- [bb] B\n")
        self.assertEqual(self.report(value)["nodes"][0]["effective"], "reported")

    def test_section_is_only_display_and_duplicates_anywhere_invalid(self):
        value = graph("backlog:aa", "backlog:bb")
        r = self.report(value, section="Now")
        self.assertTrue(r["valid"])
        aa, bb = r["nodes"]
        self.assertTrue(aa["source"]["in_section"])
        self.assertFalse(bb["source"]["in_section"])
        self.assertEqual(bb["source"]["digest"], G.digest(b"- [bb] B"))
        self.invalid_section = self.report(value, section="Absent")
        self.assertFalse(self.invalid_section["valid"])
        self.backlog.write_text(self.backlog.read_text() + "- [aa] duplicate outside Now\n")
        r = self.report(value, section="Now")
        self.assertEqual(r["findings"][0]["code"], "duplicate-backlog-id")

    def test_parser_full_lines_and_newline_normalization(self):
        self.backlog.write_bytes(b"- [aa] A\r\n  detail\r\n\r\n  more\r\n\r\nparagraph\r\n")
        value = graph("backlog:aa")
        full = "- [aa] A\n  detail\n\n  more"
        value["evidence"] = [evidence("report", "backlog:aa", full)]
        r = self.report(value)
        self.assertTrue(r["valid"])
        self.assertEqual(r["nodes"][0]["source"]["digest"], G.digest(full.encode()))
        self.assertEqual(r["nodes"][0]["effective"], "reported")

    def test_input_order_deterministic_except_graph_byte_digest(self):
        value = graph("backlog:aa", "backlog:bb", "backlog:cc", "feature:unseen")
        value["relations"] = [relation("ab", "backlog:aa", "backlog:bb"),
                              relation("ac", "backlog:aa", "backlog:cc", status="proposed"),
                              relation("cf", "backlog:cc", "feature:unseen"),
                              relation("ca", "backlog:cc", "backlog:aa", status="proposed")]
        value["evidence"] = [evidence("aa", "backlog:aa", "- [aa] A\n  detail"), evidence("bb", "backlog:bb", "old")]
        expected = self.report(value, "why", "backlog:aa")
        expected["inputs"]["graph"]["digest"] = None
        rng = random.Random(42)
        for _ in range(10):
            for key in ("nodes", "relations", "evidence"):
                rng.shuffle(value[key])
            actual = self.report(value, "why", "backlog:aa")
            actual["inputs"]["graph"]["digest"] = None
            self.assertEqual(actual, expected)

    def test_long_chains_iterative_and_stale_propagation(self):
        size = 1800
        nodes = ["backlog:n%d" % i for i in range(size)]
        lines = ["- [n%d] Item %d" % (i, i) for i in range(size)]
        self.backlog.write_text("\n".join(lines) + "\n")
        value = graph(*nodes)
        value["relations"] = [relation("r%d" % i, nodes[i], nodes[i+1]) for i in range(size-1)]
        value["evidence"] = [evidence("e%d" % i, nodes[i], lines[i]) for i in range(size)]
        r = self.report(value)
        self.assertTrue(r["valid"])
        self.assertTrue(all(n["effective"] == "reported" for n in r["nodes"]))
        self.backlog.write_text("\n".join(lines[:-1] + [lines[-1] + " revised"]))
        r = self.report(value, "why", nodes[0])
        self.assertTrue(r["valid"])
        self.assertTrue(all(n["effective"] == "unknown" for n in r["nodes"]))
        self.assertEqual(len(r["why"][-1]["path"]), size)

    def test_unreadable_inputs_and_unknown_node(self):
        self.invalid_report = self.report(graph("backlog:aa"), "why", "backlog:unknown")
        self.assertEqual(self.invalid_report["findings"][0]["code"], "unknown-node")
        self.file.unlink()
        self.assertFalse(G.report_for("check", str(self.file), str(self.backlog))["valid"])
        self.file.write_text(json.dumps(graph()))
        self.backlog.unlink()
        r = G.report_for("check", str(self.file), str(self.backlog))
        self.assertEqual(r["findings"][0]["code"], "input-unreadable")
        self.backlog.write_bytes(b'\xff')
        self.assertEqual(G.report_for("check", str(self.file), str(self.backlog))["findings"][0]["code"], "source-unreadable")

    def test_malformed_graph_paths(self):
        for name in ("nul\0.json", "surrogate\ud800.json"):
            with self.subTest(name=name):
                path = str(self.root / name)
                r = G.report_for("check", path, str(self.backlog))
                self.assertFalse(r["valid"])
                self.assertEqual(r["findings"][0]["code"], "input-unreadable")
                self.assertEqual(r["inputs"]["graph"], dict(path=path, digest=None))
                self.assertEqual(r["inputs"]["backlog"], dict(path=str(self.backlog), digest=None))
                self.assertEqual(json.loads(json.dumps(r)), r)

    def test_oserror_diagnostics_preserved(self):
        for path in (self.root / "missing.json", self.root):
            with self.subTest(path=path):
                with self.assertRaises(OSError) as caught:
                    path.read_bytes()
                r = G.report_for("check", str(path), str(self.backlog))
                self.assertEqual(r["findings"], [dict(
                    code="input-unreadable", severity="error",
                    message="cannot read %s: %s" % (path, caught.exception.strerror))])


class Public(unittest.TestCase):
    def setUp(self):
        Graph.setUp(self)
        self.conf = self.root / "config"
        (self.conf / "projects").mkdir(parents=True)
        self.state = self.root / "state"
        self.repo = self.root / "repo"
        (self.repo / ".git").mkdir(parents=True)
        self.config = self.conf / "projects" / "acme.json"
        self.config.write_text(json.dumps(dict(project="acme", repo=dict(path=str(self.repo)),
                                             backlog=dict(file=str(self.backlog), section="Now"))))
        self.file.write_text(json.dumps(graph("backlog:aa", "backlog:bb")))
        self.env = dict(os.environ, QARGI_CONF=str(self.conf), QARGI_STATE=str(self.state))

    def run_cli(self, *args):
        return subprocess.run([str(ROOT / "bin" / "qargi"), "backlog", "graph", *args],
                              env=self.env, cwd=self.repo, text=True, capture_output=True)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.stat().st_mode, p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
                for p in self.root.rglob("*")}

    def test_public_json_text_inference_and_no_mutation(self):
        before = self.snapshot()
        for cmd in ("check", "show", "why"):
            tail = ["--node", "backlog:aa"] if cmd == "why" else []
            for output in ([], ["--json"]):
                r = self.run_cli(cmd, "--graph", str(self.file), *tail, *output)
                self.assertEqual(r.returncode, 0, r.stderr)
                if output:
                    obj = json.loads(r.stdout)
                    self.assertEqual(obj["format"], "backlog-graph-report")
                    self.assertNotIn("output", obj)
                    self.assertTrue(obj["valid"])
                else:
                    self.assertIn("backlog graph " + cmd + ": valid", r.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(self.state.exists())

    def test_public_usage_and_data_errors_without_setup(self):
        for args in (("check",), ("nope", "--graph", str(self.file)),
                     ("why", "--graph", str(self.file)), ("show", "--graph", str(self.file), "--node", "backlog:aa"),
                     ("check", "--graph", str(self.file), "--unknown")):
            r = self.run_cli(*args)
            self.assertEqual(r.returncode, 2, r)
            self.assertIn("usage:", r.stderr)
        for args in (("check", "--graph", str(self.root / "missing")),
                     ("why", "--graph", str(self.file), "--node", "backlog:unknown"),
                     ("check", "--graph", str(self.file), "--project", "missing")):
            r = self.run_cli(*args, "--json")
            self.assertEqual(r.returncode, 1, r)
            self.assertFalse(json.loads(r.stdout)["valid"])
        self.file.write_text('{"version":1,"version":1}')
        r = self.run_cli("check", "--graph", str(self.file), "--project", "acme", "--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["findings"][0]["code"], "duplicate-json-key")
        self.assertFalse(self.state.exists())
        self.assertFalse((self.conf / "instances.json").exists())
        self.assertFalse((self.conf / "agents.json").exists())

    def test_existing_state_and_configuration_are_unchanged_on_errors(self):
        self.state.mkdir()
        (self.state / "audit.log").write_text("sentinel\n")
        (self.conf / "instances.json").write_text('{"sentinel":{"location":"local"}}')
        self.conf.chmod(0o755)
        self.state.chmod(0o755)
        self.file.write_text("invalid JSON")
        before = self.snapshot()
        r = self.run_cli("check", "--graph", str(self.file), "--project", "acme", "--json")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertFalse(json.loads(r.stdout)["valid"])
        self.assertEqual(self.snapshot(), before)

    def test_malformed_configured_backlog_paths(self):
        value = json.loads(self.config.read_text())
        for name in ("nul\0.md", "surrogate\ud800.md"):
            with self.subTest(name=name):
                # JSON escapes carry paths that cannot be passed in process argv.
                value["backlog"]["file"] = name
                self.config.write_text(json.dumps(value), encoding="utf-8")
                before = self.snapshot()
                for command in ("check", "show", "why"):
                    with self.subTest(command=command):
                        tail = ["--node", "backlog:aa"] if command == "why" else []
                        r = self.run_cli(command, "--graph", str(self.file),
                                         "--project", "acme", *tail, "--json")
                        self.assertEqual(r.returncode, 1, r.stderr)
                        self.assertEqual(r.stderr, "")
                        obj = json.loads(r.stdout)
                        self.assertEqual(obj["format"], "backlog-graph-report")
                        self.assertEqual(obj["version"], 1)
                        self.assertNotIn("output", obj)
                        self.assertFalse(obj["valid"])
                        self.assertEqual(obj["findings"][0]["code"], "input-unreadable")
                        self.assertEqual(obj["inputs"]["graph"], dict(
                            path=str(self.file), digest=G.digest(self.file.read_bytes())))
                        self.assertEqual(obj["inputs"]["backlog"], dict(
                            path=str(self.repo / name), digest=None))
                        for key in ("nodes", "relations", "evidence"):
                            self.assertEqual(obj[key], [])
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.state.exists())

    def test_text_diagnostics_escape_unencodable_values(self):
        config = json.loads(self.config.read_text())
        for bad_source in (True, False):
            with self.subTest(bad_source=bad_source):
                config["backlog"]["file"] = (
                    "surrogate\ud800.md" if bad_source else str(self.backlog))
                self.config.write_text(json.dumps(config), encoding="utf-8")
                value = graph("backlog:aa", "backlog:bb")
                if not bad_source:
                    value["nodes"].append("backlog:surrogate\ud800")
                self.file.write_text(json.dumps(value), encoding="utf-8")
                before = self.snapshot()
                for command in ("check", "show", "why"):
                    with self.subTest(command=command):
                        tail = ["--node", "backlog:aa"] if command == "why" else []
                        result = self.run_cli(command, "--graph", str(self.file),
                                              "--project", "acme", *tail)
                        self.assertEqual(result.returncode, 1, result.stderr)
                        self.assertEqual(result.stderr, "")
                        expected = "input-unreadable" if bad_source else "typed-ref"
                        self.assertIn(expected, result.stdout)
                        self.assertIn(r"\ud800", result.stdout)
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.state.exists())

    def test_leading_tilde_matches_existing_backlog_prefix_rules(self):
        value = json.loads(self.config.read_text())
        home = self.root / "operator-home"
        home.mkdir()
        self.env["HOME"] = str(home)
        for spelling in ("~notes.md", "~/notes.md", "~other/notes.md"):
            with self.subTest(spelling=spelling):
                # gitflow.sh backlog_path substitutes any leading tilde prefix.
                expected = Path(str(home) + spelling[1:])
                expected.parent.mkdir(parents=True, exist_ok=True)
                expected.write_text(self.backlog.read_text(), encoding="utf-8")
                value["backlog"]["file"] = spelling
                self.config.write_text(json.dumps(value), encoding="utf-8")
                before = self.snapshot()
                result = self.run_cli("check", "--graph", str(self.file),
                                      "--project", "acme", "--json")
                report = json.loads(result.stdout)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(report["valid"], report["findings"])
                self.assertEqual(report["inputs"]["backlog"]["path"], str(expected))
                self.assertTrue(all(n["source"] for n in report["nodes"]))
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(self.state.exists())
        value["backlog"]["file"] = "~"
        self.config.write_text(json.dumps(value), encoding="utf-8")
        result = self.run_cli("check", "--graph", str(self.file),
                              "--project", "acme", "--json")
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertEqual(report["inputs"]["backlog"], dict(path=str(home), digest=None))
        self.assertEqual(report["findings"][0]["code"], "input-unreadable")

    def test_relative_and_home_paths_and_missing_backlog_configuration(self):
        value = json.loads(self.config.read_text())
        value["backlog"]["file"] = "../backlog.md"
        self.config.write_text(json.dumps(value))
        self.assertEqual(self.run_cli("check", "--graph", str(self.file), "--project", "acme").returncode, 0)
        self.env["HOME"] = str(self.root)
        value["backlog"]["file"] = "~/backlog.md"
        self.config.write_text(json.dumps(value))
        self.assertEqual(self.run_cli("check", "--graph", str(self.file), "--project", "acme").returncode, 0)
        value.pop("backlog")
        self.config.write_text(json.dumps(value))
        r = self.run_cli("check", "--graph", str(self.file), "--project", "acme", "--json")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(json.loads(r.stdout)["findings"][0]["code"], "configuration")


if __name__ == "__main__":
    unittest.main()
