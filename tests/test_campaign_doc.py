#!/usr/bin/env python3
"""Pure campaign v1 snapshots and transitions; no store or CLI fixtures."""
import hermetic  # noqa: F401
import copy
import importlib
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import backlog_graph as G  # noqa: E402
import campaign_doc as C  # noqa: E402

CAMPAIGN = "6f1c2a9e-3b7d-4c1e-9a55-0d2f8e4b7a10"
P = "0b9d4c7e-51aa-4e0f-8c2b-7d1e9f3a6b20"
Q = "c41e88d2-0f6b-4a39-b1d7-2e5c9a7f4d31"
DIGEST = "sha256:" + "a" * 64


def attribution():
    return dict(by="lead", at="2026-11-14")


def json_bytes(value):
    """Fixture byte accounting, independently of the module's private helpers."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()


def design(rev=1):
    return dict(rev=rev, state="provisional", ref="design note", **attribution())


def participant(ident=P):
    return dict(id=ident, label="external project", locator="https://example.org/project", qargi_project=None)


def work(ident="r1:client", person=P):
    return dict(id=ident, participant=person, state="active", requirements=["r1:api"],
                source=dict(kind="external", ref="issue 412", pin=None), design=None, links=[])


def link(purpose="evaluation", target=None):
    return dict(purpose=purpose, target=target or dict(kind="ref", ref="evaluation/result.json"),
                digest=None, status="unresolved", **attribution())


def document():
    upstream = work("r1:api-design")
    upstream["design"] = design()
    return dict(format="campaign", version=1, campaign=CAMPAIGN, label="API split",
                objective="Split the client from the API.\nAllow provisional work.", continues=None,
                participants=[participant()],
                requirements=[dict(id="r1:api", text="Stable API.\nDocument it.", state="active")],
                work=[work(), upstream],
                coordination=[dict(id="r1:follows", dependent="r1:client", upstream="r1:api-design",
                                   briefed=None, graph_pin=None)],
                provenance=dict(basis="owner direction", **attribution()))


def brief(rev=1):
    return dict(design_rev=rev, ref="task text", **attribution())


def graph_document():
    doc = document()
    doc["participants"][0]["qargi_project"] = "long-project-name"
    for w in doc["work"]:
        w["source"] = dict(kind="backlog", ref="backlog:" + w["id"].split(":")[1],
                           pin=dict(type="item-digest", value=DIGEST))
    doc["coordination"][0]["graph_pin"] = dict(graph=dict(locator="plans/graph.json", digest=DIGEST),
        relation="needs-api", kind="requires", **{"from": "backlog:client", "to": "backlog:api-design"},
        status="proposed", verification="unverified")
    return doc


class Campaign(unittest.TestCase):
    def invalid(self, function, value, code, **kwargs):
        with self.assertRaises(C.Invalid) as caught:
            function(value, **kwargs)
        self.assertEqual(caught.exception.code, code, str(caught.exception))
        self.assertTrue(str(caught.exception).isascii())
        self.assertTrue(all(c.isprintable() for c in str(caught.exception)))
        self.assertEqual(caught.exception.path, caught.exception.details["path"])
        return caught.exception

    def bad_transition(self, parent, child, code="transition", rev=2):
        self.invalid(lambda value: C.transition(parent, value, rev=rev), child, code)

    def test_external_create_revise_and_authority(self):
        doc = document()
        self.assertEqual(C.transition(None, doc, rev=1), C.validate(doc))
        child = copy.deepcopy(doc)
        child["objective"] = "Corrected objective"
        child["requirements"][0]["text"] = "Corrected requirement"
        child["work"][0]["source"]["pin"] = dict(type="opaque", value="release candidate")
        C.transition(doc, child, rev=2)
        self.assertEqual(C.constants()["acceptance"], "not-recorded")
        empty = document()
        for group in C.LIMITS:
            empty[group] = []
        C.transition(None, empty, rev=1)
        self.assertEqual(C.constants()["invalidation_policy"], "undecided")
        self.assertEqual(C.constants()["source_observation"], "not-performed")
        self.assertEqual(C.constants()["authority"], "declarations-only")
        self.assertEqual(C.constants()["coordination_scope"], "supplied-document")
        changed = C.constants()
        changed["acceptance"] = "accepted"
        self.assertEqual(C.constants()["acceptance"], "not-recorded")

    def test_closed_schema_every_object(self):
        base = graph_document()
        base["continues"] = dict(campaign=Q, revision=DIGEST)
        base["coordination"][0]["briefed"] = brief()
        base["work"][0]["links"] = [link(target=dict(kind="qargi-attempt", run="qargi.Ab12Cd",
            prepared_identity=None, prepared_epoch=None, attempt=None))]
        C.validate(base)
        paths = [(), ("continues",), ("participants", 0), ("requirements", 0), ("work", 0),
                 ("work", 0, "source"), ("work", 0, "source", "pin"), ("work", 1, "design"),
                 ("work", 0, "links", 0), ("work", 0, "links", 0, "target"), ("coordination", 0),
                 ("coordination", 0, "briefed"), ("coordination", 0, "graph_pin"),
                 ("coordination", 0, "graph_pin", "graph"), ("provenance",)]
        for path in paths:
            for extra in (False, True):
                with self.subTest(path=path, extra=extra):
                    doc = copy.deepcopy(base)
                    obj = doc
                    for key in path:
                        obj = obj[key]
                    if extra:
                        obj["extra"] = "unexpected"
                    else:
                        del obj[next(iter(obj))]
                    self.invalid(C.validate, doc, "identity" if path in (("work", 0), ("requirements", 0),
                        ("coordination", 0)) and not extra else "schema")

    def test_decode_strict_json(self):
        for raw in (b'{', b'null trailing', b'\xff', '{}'.encode("utf-16"), b'\xef\xbb\xbf{}',
                    b'NaN', b'Infinity', b'-Infinity', b'"\x1b"'):
            with self.subTest(raw=raw):
                self.invalid(C.decode, raw, "invalid-json")
        for raw in (b'{"x":1,"x":2}', b'{"x":[{"y":0,"y":1}]}',
                    b'{"\\u001b":1,"\\u001b":2}', b'{"\\ud800":1,"\\ud800":2}'):
            self.invalid(C.decode, raw, "duplicate-json-key")
        for raw in (b'1.0', b'1e0', b'1e999', b'-0.0'):
            self.invalid(C.decode, raw, "schema")
        self.invalid(C.decode, b'9' * 10000, "bounds")
        self.invalid(C.decode, "{}", "invalid-json")
        self.assertEqual(C.decode(b'-0'), 0)
        self.assertEqual(C.decode(b'"\\ud83d\\ude00"'), "😀")
        C.validate(C.decode(json.dumps(document(), ensure_ascii=False).encode()))

    def test_unicode_controls_and_safe_diagnostics(self):
        for bad in ("\ud800", "text\udfff", "text\x1b[31m", "a\x00b", "a\x7fb", "a\x85b"):
            for api in (C.validate, lambda d: C.decode(json.dumps(d).encode())):
                doc = document()
                doc["label"] = bad
                self.invalid(api, doc, "schema")
        doc = document()
        doc["label"] = "café 雪 😀\u202e"
        # Printable formatting scalars are data, never echoed in diagnostics.
        C.validate(doc)
        for field in ("label", "campaign"):
            doc = document()
            doc[field] = "bad\ntext"
            self.invalid(C.validate, doc, "schema" if field == "label" else "identity")
        doc = document()
        doc["work"][0]["links"] = [link(target=dict(kind="ref", ref="bad\nref"))]
        self.invalid(C.validate, doc, "schema")
        doc = document()
        doc["\x1b"] = "bad"
        self.invalid(C.validate, doc, "schema")

    def test_strict_integer_fields(self):
        base = document()
        base["coordination"][0]["briefed"] = brief()
        base["work"][0]["links"] = [link(target=dict(kind="qargi-attempt", run="qargi.Ab12Cd",
            prepared_identity="a" * 32, prepared_epoch=0, attempt=1))]
        for path in (("version",), ("work", 1, "design", "rev"),
                     ("coordination", 0, "briefed", "design_rev"),
                     ("work", 0, "links", 0, "target", "attempt"),
                     ("work", 0, "links", 0, "target", "prepared_epoch")):
            for value in (True, 1.0, "1"):
                doc = copy.deepcopy(base)
                obj = doc
                for key in path[:-1]:
                    obj = obj[key]
                obj[path[-1]] = value
                self.invalid(C.validate, doc, "schema" if type(value) is float or path != ("version",) else "version")
        self.invalid(lambda d: C.transition(None, d, rev=True), document(), "schema")
        self.invalid(lambda d: C.transition(None, d, rev=0), document(), "bounds")
        self.invalid(lambda d: C.transition(None, d, rev=C.MAX_REV + 1), document(), "bounds")

    def test_neutral_uuid_identity_and_namespace(self):
        for key in ("campaign", "participant"):
            for value in ("00000000-0000-0000-0000-000000000000", P.upper(), "r1:project", 1):
                doc = document()
                if key == "campaign":
                    doc[key] = value
                else:
                    doc["participants"][0]["id"] = value
                self.invalid(C.validate, doc, "identity")
        doc = document()
        doc["participants"].append(participant())
        self.invalid(C.validate, doc, "identity")
        doc = document()
        doc["requirements"][0]["id"] = "r1:client"
        self.invalid(C.validate, doc, "identity")
        for ident in ("r0:aa", "r01:aa", "r1000000000:aa", "r1:A", "r1:a--b", "r1:" + "a" * 49):
            doc = document()
            doc["work"][0]["id"] = ident
            self.invalid(C.validate, doc, "identity")

    def test_participant_mappings_mutable_and_work_stable(self):
        parent = document()
        child = copy.deepcopy(parent)
        child["participants"][0].update(label="new label", locator=None, qargi_project="a" + "-b" * 31)
        C.transition(parent, child, rev=2)
        child["participants"][0]["qargi_project"] = "new-binding"
        C.transition(parent, child, rev=2)
        child["participants"].append(participant(Q))
        child["work"][0]["participant"] = Q
        self.bad_transition(parent, child)
        child = document()
        child["participants"] = []
        self.invalid(C.validate, child, "reference")
        parent["participants"].append(participant(Q))
        child = copy.deepcopy(parent)
        child["participants"].pop()
        C.transition(parent, child, rev=2)
        C.transition(child, parent, rev=3)  # Neutral UUID may return.
        for binding in ("A", "a_", "a" * 65):
            doc = document()
            doc["participants"][0]["qargi_project"] = binding
            self.invalid(C.validate, doc, "schema")

    def test_birth_omission_reintroduction_and_type_movement(self):
        parent = document()
        child = copy.deepcopy(parent)
        child["work"].append(work("r2:new"))
        C.transition(parent, child, rev=2)
        omitted = copy.deepcopy(child)
        omitted["work"].pop()
        C.transition(child, omitted, rev=3)
        self.bad_transition(omitted, child, "identity", rev=4)
        for ident in ("r1:new", "r3:new"):
            child = document()
            child["work"].append(work(ident))
            self.bad_transition(parent, child, "identity")
        child = document()
        child["requirements"].append(dict(id="r1:client", text="moved", state="active"))
        child["work"].pop(0)
        child["coordination"] = []
        self.bad_transition(parent, child, "identity")
        for group in ("requirements", "coordination"):
            child = document()
            child[group].append(dict(id="r2:new", text="new", state="active") if group == "requirements" else
                dict(id="r2:new", dependent="r1:api-design", upstream="r1:client", briefed=None, graph_pin=None))
            if group == "coordination":
                child["work"][0]["design"] = design()
            C.transition(parent, child, rev=2)
            omitted = copy.deepcopy(child)
            omitted[group].pop()
            self.bad_transition(omitted, child, "identity", rev=3)

    def test_current_window_can_outlive_array_budgets(self):
        parent = document()
        for rev in range(2, 306):
            child = copy.deepcopy(parent)
            child["work"] = [work("r%d:window" % rev)]
            child["coordination"] = []
            C.transition(parent, child, rev=rev)
            parent = child
        self.assertEqual(len(parent["work"]), 1)

    def test_lineage_and_no_change(self):
        parent = document()
        self.bad_transition(parent, copy.deepcopy(parent), "no-change")
        child = copy.deepcopy(parent)
        child["work"].reverse()
        self.bad_transition(parent, child, "no-change")
        child["campaign"] = Q
        self.bad_transition(parent, child)
        child = document()
        child["continues"] = dict(campaign=Q, revision=DIGEST)
        self.bad_transition(parent, child)
        C.transition(None, child, rev=1)
        self.bad_transition(None, parent, rev=2)
        self.bad_transition(parent, child, rev=1)

    def test_design_progression(self):
        parent = document()
        for change in (dict(ref="corrected"), dict(rev=3), dict(state="settled")):
            child = document()
            child["work"][1]["design"].update(change)
            self.bad_transition(parent, child)
        child = document()
        child["coordination"] = []
        child["work"][1]["design"] = None
        self.bad_transition(parent, child)
        child = document()
        child["work"][1]["design"].update(rev=2, state="settled", ref="corrected")
        C.transition(parent, child, rev=2)
        child = document()
        child["work"][0]["design"] = design()
        C.transition(parent, child, rev=2)
        child["work"][0]["design"]["rev"] = 2
        self.bad_transition(parent, child)
        child = document()
        child["work"][1]["design"]["rev"] = 2
        C.validate(child)  # Valid historical snapshot, invalid create.
        self.bad_transition(None, child, rev=1)
        child = document()
        child["work"].append(work("r2:new"))
        child["work"][-1]["design"] = design(2)
        self.bad_transition(parent, child)

    def test_briefing_corrections_and_warning_wording(self):
        parent = document()
        parent["work"][1]["design"] = design(3)
        parent["coordination"][0]["briefed"] = brief(3)
        for claim, code in ((brief(1), "brief-claim-behind"), (None, "brief-claim-missing")):
            child = copy.deepcopy(parent)
            child["coordination"][0]["briefed"] = claim
            C.transition(parent, child, rev=4)
            warning = C.findings(child)[0]
            self.assertEqual(warning["code"], code)
            self.assertEqual(warning["severity"], "warning")
        child["coordination"][0]["briefed"] = brief(4)
        self.invalid(C.validate, child, "reference")
        child["coordination"][0]["briefed"] = brief(1)
        self.assertEqual(C.findings(child)[0]["message"],
                         "recorded briefing claim is behind declared design revision")

    def test_coordination_cycles_and_retained_endpoints(self):
        parent = document()
        parent["work"][0]["design"] = design()
        child = copy.deepcopy(parent)
        child["coordination"].append(dict(id="r2:reverse", dependent="r1:api-design", upstream="r1:client",
                                          briefed=None, graph_pin=None))
        C.transition(parent, child, rev=2)  # Notification cycles are valid.
        child = copy.deepcopy(parent)
        c = child["coordination"][0]
        c["dependent"], c["upstream"] = c["upstream"], c["dependent"]
        self.bad_transition(parent, child)
        child = copy.deepcopy(parent)
        child["coordination"][0]["upstream"] = "r1:client"
        self.invalid(C.validate, child, "reference")
        child = copy.deepcopy(parent)
        child["coordination"].append(dict(child["coordination"][0], id="r2:duplicate"))
        self.invalid(C.validate, child, "reference")
        child = copy.deepcopy(parent)
        child["work"].pop()
        self.invalid(C.validate, child, "reference")

    def test_planning_states_and_warning_coverage(self):
        doc = document()
        for w in doc["work"]:
            w["state"] = "withdrawn"
        codes = [f["code"] for f in C.findings(doc)]
        self.assertEqual(codes, ["requirement-uncovered", "brief-claim-missing", "coordination-target-withdrawn"])
        doc["requirements"][0]["state"] = "withdrawn"
        self.assertNotIn("requirement-uncovered", [f["code"] for f in C.findings(doc)])
        for group in ("requirements", "work"):
            for state in ("done", "merged", "accepted"):
                doc = document()
                doc[group][0]["state"] = state
                self.invalid(C.validate, doc, "schema")

    def test_source_pin_matrix(self):
        for kind in ("backlog", "feature", "external"):
            for typ in (None, "item-digest", "file-digest", "commit", "opaque"):
                with self.subTest(kind=kind, typ=typ):
                    doc = document()
                    doc["participants"][0]["qargi_project"] = "mapped-project"
                    doc["work"][0]["source"] = dict(kind=kind, ref="issue" if kind == "external" else kind + ":client",
                        pin=None if typ is None else dict(type=typ, value="a" * 40 if typ == "commit" else
                                                         "revision opaque" if typ == "opaque" else DIGEST))
                    permitted = typ is None or typ == "commit" or typ == "item-digest" and kind == "backlog" or \
                        typ == "file-digest" and kind in ("backlog", "external") or typ == "opaque" and kind == "external"
                    if permitted:
                        C.validate(doc)
                    else:
                        self.invalid(C.validate, doc, "schema")
        doc = graph_document()
        doc["participants"][0]["qargi_project"] = None
        self.invalid(C.validate, doc, "reference")
        doc = document()
        doc["work"][0]["source"] = None
        C.validate(doc)

    def test_graph_pins_declare_unverified_bytes_status_and_endpoints(self):
        parent = graph_document()
        C.transition(None, parent, rev=1)
        for key, value, code in (("from", "backlog:other", "graph-pin"),
                                  ("to", "feature:other", "graph-pin"),
                                  ("verification", "verified", "schema"),
                                  ("status", "accepted", "schema"), ("kind", "depends", "schema")):
            child = copy.deepcopy(parent)
            child["coordination"][0]["graph_pin"][key] = value
            self.invalid(C.validate, child, code)
        child = copy.deepcopy(parent)
        child["participants"].append(dict(participant(Q), qargi_project="other"))
        child["work"][1]["participant"] = Q
        self.invalid(C.validate, child, "graph-pin")
        child = copy.deepcopy(parent)
        child["work"][0]["source"]["ref"] = "feature:new-source"
        child["work"][0]["source"].update(kind="feature", pin=dict(type="commit", value="b" * 64))
        pin = child["coordination"][0]["graph_pin"]
        pin.update(status="confirmed", **{"from": "feature:new-source"})
        pin["graph"]["digest"] = "sha256:" + "b" * 64
        C.transition(parent, child, rev=2)  # Same relation ID grants no authority.

    def test_graph_rule_parity(self):
        self.assertIs(C.typed_ref, G.typed_ref)
        self.assertIs(C.at, G.at)
        self.assertIs(C.scalar_words, G.scalar_words)
        self.assertIs(C.SLUG, G.SLUG)
        self.assertIs(C.DIGEST, G.DIGEST)
        for text in ("", "  ", "lead", "café 雪 😀", "bad\ud800"):
            doc = document()
            doc["provenance"]["by"] = text
            try:
                G.scalar_words(text)
            except G.Invalid:
                self.invalid(C.validate, doc, "schema")
            else:
                C.validate(doc)
        for ref in ("backlog:aa", "backlog:a", "backlog:a--b", "feature:a", "feature:develop",
                    "feature:" + "a" * 41, "feature:a--b", "backlog:雪"):
            valid = True
            try:
                G.typed_ref(ref)
            except G.Invalid:
                valid = False
            doc = document()
            doc["participants"][0]["qargi_project"] = "declared"
            doc["work"][0]["source"] = dict(kind=ref.split(":")[0], ref=ref, pin=None)
            if valid:
                C.validate(doc)
            else:
                self.invalid(C.validate, doc, "schema")
        for stamp in ("2024-02-29", "2026-11-14t12:34z", "2026-11-14T12:34:56.123456789Z",
                      "2026-11-14T12:34:56,125+02:30", "2026-11-14T24:00", "2026-02-29"):
            doc = document()
            doc["provenance"]["at"] = stamp
            try:
                G.at(stamp)
            except G.Invalid:
                self.invalid(C.validate, doc, "schema")
            else:
                C.validate(doc)

    def test_unresolved_attempts_and_opaque_pointers(self):
        for target in (dict(kind="ref", ref="$(never execute); file:///not-opened"),
                       dict(kind="qargi-attempt", run="qargi.Ab12Cd", prepared_identity=None,
                            prepared_epoch=None, attempt=None),
                       dict(kind="qargi-attempt", run="qargi.Ab12Cd", prepared_identity="a" * 32,
                            prepared_epoch=C.MAX_EPOCH, attempt=256)):
            doc = document()
            doc["work"][0]["links"] = [link(purpose, target) for purpose in C.PURPOSES]
            C.validate(doc)
        for field, value, code in (("run", "qargi.bad", "schema"), ("prepared_identity", "A" * 32, "schema"),
                                   ("prepared_epoch", -1, "bounds"), ("attempt", 257, "bounds")):
            doc = document()
            bad = dict(target, **{field: value})
            doc["work"][0]["links"] = [link(target=bad)]
            self.invalid(C.validate, doc, code)
        doc = document()
        doc["work"][0]["links"] = [dict(link(), status="resolved")]
        self.invalid(C.validate, doc, "schema")

    def test_deterministic_semantic_order_and_duplicates(self):
        doc = document()
        doc["participants"].append(participant(Q))
        doc["requirements"].extend(dict(id=ident, text=ident, state="active") for ident in ("r10:aa", "r2:zz"))
        doc["work"][0]["requirements"] += ["r10:aa", "r2:zz"]
        doc["work"][0]["links"] = [link("outcome"), link("evaluation")]
        expected = C.canonicalize(doc)
        rng = random.Random(23)
        for _ in range(20):
            shuffled = copy.deepcopy(doc)
            for group in ("participants", "requirements", "work", "coordination"):
                rng.shuffle(shuffled[group])
            for w in shuffled["work"]:
                rng.shuffle(w["requirements"])
                rng.shuffle(w["links"])
            self.assertEqual(C.canonicalize(shuffled), expected)
        self.assertEqual([r["id"] for r in C.validate(doc)["requirements"]], ["r1:api", "r2:zz", "r10:aa"])
        self.assertTrue(expected.endswith(b"\n"))
        self.assertEqual(expected, (json.dumps(C.validate(doc), sort_keys=True, separators=(",", ":"),
                                             ensure_ascii=True) + "\n").encode())
        doc["work"][0]["links"].append(dict(link("outcome"), by="different", digest=DIGEST))
        self.invalid(C.validate, doc, "reference")
        doc = document()
        doc["work"][0]["requirements"].append("r1:api")
        self.invalid(C.validate, doc, "reference")

    def test_text_byte_boundaries(self):
        setters = [(128, lambda d, v: d.update(label=v)),
                   (4096, lambda d, v: d.update(objective=v)),
                   (2048, lambda d, v: d["requirements"][0].update(text=v)),
                   (1024, lambda d, v: d["participants"][0].update(locator=v)),
                   (1024, lambda d, v: d["provenance"].update(basis=v)),
                   (128, lambda d, v: d["provenance"].update(by=v)),
                   (1024, lambda d, v: d["work"][0]["source"].update(ref=v)),
                   (1024, lambda d, v: d["work"][1]["design"].update(ref=v)),
                   (128, lambda d, v: d["work"][0]["source"].update(pin=dict(type="opaque", value=v)))]
        for limit, setter in setters:
            for unit in ("a", "é"):
                doc = document()
                value = unit * (limit // len(unit.encode()))
                setter(doc, value)
                C.validate(doc)
                setter(doc, value + "a")
                self.invalid(C.validate, doc, "bounds")
        for text in ("", " ", "\n"):
            doc = document()
            doc["objective"] = text
            self.invalid(C.validate, doc, "schema")

    def test_collection_boundaries(self):
        for group, limit in C.LIMITS.items():
            doc = document()
            if group == "participants":
                entries = [participant("%08x-1111-2222-3333-444444444444" % i) for i in range(1, limit + 1)]
                entries[0]["id"] = P
            elif group == "requirements":
                entries = [dict(id="r1:req%d" % i, text="req", state="active") for i in range(limit)]
                entries[0]["id"] = "r1:api"
            elif group == "work":
                entries = [work("r1:work%d" % i) for i in range(limit)]
                doc["coordination"] = []
            else:
                doc["work"] = [dict(work("r1:work%d" % i), design=design()) for i in range(17)]
                pairs = [(a, b) for a in doc["work"] for b in doc["work"] if a is not b]
                entries = [dict(id="r1:coord%d" % i, dependent=a["id"], upstream=b["id"],
                                briefed=None, graph_pin=None) for i, (a, b) in enumerate(pairs[:limit])]
            doc[group] = entries
            C.validate(doc)
            doc[group].append(copy.deepcopy(entries[0]))
            self.invalid(C.validate, doc, "bounds")
        doc = document()
        doc["work"][0]["links"] = [link(target=dict(kind="ref", ref="ref%d" % i)) for i in range(32)]
        C.validate(doc)
        doc["work"][0]["links"].append(link())
        self.invalid(C.validate, doc, "bounds")

    def test_decode_resource_boundaries(self):
        self.assertEqual(C.decode(b'0' + b' ' * (C.MAX_SPEC_BYTES - 1)), 0)
        self.invalid(C.decode, b'0' + b' ' * C.MAX_SPEC_BYTES, "bounds")
        # Root and every scalar/container/key count toward depth and values.
        C.decode(b'[' * 15 + b'0' + b']' * 15)
        self.invalid(C.decode, b'[' * 16 + b'0' + b']' * 16, "bounds")
        self.invalid(C.decode, b'[' * 10000 + b'0' + b']' * 10000, "bounds")
        C.decode(b'[' + b','.join([b'0'] * (C.MAX_VALUES - 1)) + b']')
        self.invalid(C.decode, b'[' + b','.join([b'0'] * C.MAX_VALUES) + b']', "bounds")
        cycle = []
        cycle.append(cycle)
        self.invalid(C.validate, cycle, "bounds")

    def test_joint_canonical_envelope_bound(self):
        doc = document()
        doc["requirements"] = [dict(id="r1:req%d" % i, text="x" * 2048, state="active") for i in range(128)]
        for w in doc["work"]:
            w["requirements"] = []
        self.invalid(C.validate, doc, "bounds")
        # Tune a valid schema to the exact document+maximum-envelope boundary.
        doc["requirements"][-1]["text"] = "x"
        while True:
            size = len(json_bytes(doc))
            delta = size - C.MAX_DOCUMENT_BYTES
            if delta <= 0:
                break
            r = next(r for r in reversed(doc["requirements"]) if len(r["text"]) > 1)
            r["text"] = r["text"][:max(1, len(r["text"]) - delta)]
        self.assertEqual(len(C.canonicalize(doc)), C.MAX_DOCUMENT_BYTES)
        envelope = dict(format="campaign-revision", version=1, rev=C.MAX_REV,
                        previous="sha256:" + "f" * 64, document=C.validate(doc))
        self.assertEqual(len(json_bytes(envelope)), C.MAX_REVISION_BYTES)
        doc["requirements"][-1]["text"] += "x"
        self.invalid(C.validate, doc, "bounds")
        doc = document()
        doc["requirements"] = [dict(id="r1:req%d" % i, text="😀" * 512, state="active") for i in range(50)]
        for w in doc["work"]:
            w["requirements"] = []
        # Input UTF-8 is below 512 KiB; ensure_ascii expansion still exceeds envelope budget.
        raw = json.dumps(doc, ensure_ascii=False).encode()
        self.assertLess(len(raw), C.MAX_SPEC_BYTES)
        self.invalid(C.validate, C.decode(raw), "bounds")

    def test_remaining_reference_and_grammar_boundaries(self):
        doc = document()
        doc["work"][0]["requirements"] = ["r1:missing"]
        self.invalid(C.validate, doc, "reference")
        doc = document()
        doc["requirements"] = [dict(id="r1:req%d" % i, text="requirement", state="active") for i in range(128)]
        for w in doc["work"]:
            w["requirements"] = [r["id"] for r in doc["requirements"]]
        C.validate(doc)
        doc["work"][0]["requirements"].append("r1:missing")
        self.invalid(C.validate, doc, "bounds")
        doc = document()
        doc["work"].append(work("r999999999:" + "a" * 48))
        doc["work"][-1]["design"] = design(1)
        C.transition(document(), doc, rev=999999999)
        doc["work"][-1]["design"]["rev"] = C.MAX_REV + 1
        self.invalid(C.validate, doc, "bounds")
        doc = document()
        stamp = "2026-11-14T12:34:56." + "1" * 107 + "Z"
        self.assertEqual(len(stamp), 128)
        doc["provenance"]["at"] = stamp
        C.validate(doc)
        doc["provenance"]["at"] = stamp[:-1] + "1Z"
        self.invalid(C.validate, doc, "bounds")
        doc = graph_document()
        doc["coordination"][0]["graph_pin"]["relation"] = "a" * 1024
        C.validate(doc)
        doc["coordination"][0]["graph_pin"]["relation"] += "a"
        self.invalid(C.validate, doc, "bounds")
        for value in ("sha256:" + "A" * 64, "sha256:" + "a" * 63, "a" * 64):
            doc = graph_document()
            doc["coordination"][0]["graph_pin"]["graph"]["digest"] = value
            self.invalid(C.validate, doc, "schema")
        doc = document()
        doc["participants"][0]["qargi_project"] = "a" * 64
        C.validate(doc)
        doc["work"][0]["source"] = dict(kind="backlog", ref="feature:client", pin=None)
        self.invalid(C.validate, doc, "schema")

    def test_pure_apis_no_mutation_files_config_or_lifecycle(self):
        doc = graph_document()
        original = copy.deepcopy(doc)
        raw = json.dumps(doc).encode()
        with patch("builtins.open", side_effect=AssertionError("file access")), \
             patch("os.open", side_effect=AssertionError("file access")), \
             patch("os.getenv", side_effect=AssertionError("config access")), \
             patch("os.environ", {}), \
             patch.object(G.P, "state", side_effect=AssertionError("state access")), \
             patch.object(G.P, "conf", side_effect=AssertionError("config access")):
            importlib.reload(C)
            parsed = C.decode(raw)
            normalized = C.validate(parsed)
            C.canonicalize(parsed)
            C.transition(None, parsed, rev=1)
            C.findings(parsed)
            C.constants()
        self.assertEqual(doc, original)
        self.assertEqual(parsed, original)
        normalized["work"][0]["source"]["pin"]["value"] = "changed"
        self.assertEqual(doc, original)
        self.assertNotIn("attempts", C.__dict__)


if __name__ == "__main__":
    unittest.main()
