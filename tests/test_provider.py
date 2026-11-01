#!/usr/bin/env python3
"""Provider descriptors: lib/provider.py (load, validate, cap, effective) against lib/providers/schema.json.
Hermetic: every changed descriptor is a copy in a temporary directory, never the user's data.
Run: python3 tests/test_provider.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import copy, json, os, shutil, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
sys.path.insert(0, LIB)
import provider as P  # noqa: E402

with open(os.path.join(LIB, "providers", "claude.json")) as _f:
    CLAUDE = json.load(_f)


def descriptor():
    return copy.deepcopy(CLAUDE)


def fails(d, name="claude"):
    return [m for lvl, m in P.validate(d, name) if lvl == "fail"]


def warns(d, name="claude"):
    return [m for lvl, m in P.validate(d, name) if lvl == "warn"]


class Tree(unittest.TestCase):
    """A temporary providers directory beside a copy of provider.py's descriptors."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prov.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "providers")
        os.makedirs(self.root)
        shutil.copy(os.path.join(LIB, "providers", "schema.json"), self.root)

    def put(self, name, d):
        with open(os.path.join(self.root, name + ".json"), "w") as f:
            json.dump(d, f)


class Valid(unittest.TestCase):
    def test_the_shipped_claude_descriptor_has_no_failure(self):
        self.assertEqual(fails(descriptor()), [])

    def test_the_shipped_claude_descriptor_warns_for_every_unverified_date(self):
        d = descriptor()
        nulls = [t for t, v in d["tier_detail"].items() if v["verified_on"] is None]
        for cap in d["capabilities"].values():
            nulls += [s for s, c in cap.items() if c["verified_on"] is None]
        self.assertEqual(len(warns(d)), len(nulls))
        self.assertGreaterEqual(len(nulls), 4)

    def test_a_fully_verified_descriptor_is_clean(self):
        d = descriptor()
        for t in d["tier_detail"].values():
            t["verified_on"] = "2026-10-31"
        for cap in d["capabilities"].values():
            for c in cap.values():
                c["verified_on"] = "2026-10-31"
        self.assertEqual(P.validate(d, "claude"), [])

    def test_tiers_and_aliases_stay_plain_maps_that_older_code_reads(self):
        self.assertEqual(CLAUDE["tiers"], {"fast": "claude-haiku-5-5", "balanced": "claude-sonnet-5-5", "deep": "claude-opus-5-5", "frontier": "claude-fable-5-1"})
        self.assertEqual(CLAUDE["aliases"], {"fast": "haiku", "balanced": "sonnet", "deep": "opus", "frontier": "fable"})
        self.assertEqual({t: v["model"] for t, v in CLAUDE["tier_detail"].items()}, CLAUDE["tiers"])

    def test_reserved_names_are_the_ones_lib_agent_sh_has(self):
        with open(os.path.join(LIB, "agent.sh")) as f:
            src = f.read()
        line = [ln for ln in src.splitlines() if ln.startswith("BUILTIN=")][0]
        self.assertEqual(sorted(CLAUDE["local"]["reserved_names"]), sorted(line.split('"')[1].split()))


class Violations(unittest.TestCase):
    def one(self, d, needle, name="claude"):
        f = fails(d, name)
        self.assertTrue(any(needle in m for m in f), "%r not in %r" % (needle, f))
        return f

    def test_an_additional_property_at_the_top(self):
        d = descriptor()
        d["extra"] = 1
        self.one(d, "extra: additional property is not allowed")

    def test_an_additional_property_deep_inside(self):
        d = descriptor()
        d["capabilities"]["mcp"]["local"]["colour"] = "red"
        self.one(d, "capabilities.mcp.local.colour: additional property is not allowed")

    def test_a_bad_provider_name(self):
        d = descriptor()
        d["provider"] = "Claude_X"
        self.one(d, "provider: 'Claude_X' does not match")

    def test_a_name_that_differs_from_the_file(self):
        d = descriptor()
        d["provider"] = "other"
        self.one(d, "provider 'other' differs from the file name 'claude'")

    def test_a_missing_tier(self):
        d = descriptor()
        del d["tier_detail"]["deep"]
        self.one(d, "tier_detail: missing tier 'deep'")

    def test_a_bad_date(self):
        d = descriptor()
        d["tier_detail"]["fast"]["verified_on"] = "31/10/2026"
        self.one(d, "tier_detail.fast.verified_on: '31/10/2026' is not a date")
        d["tier_detail"]["fast"]["verified_on"] = "2026-02-30"
        self.one(d, "tier_detail.fast.verified_on: '2026-02-30' is not a date")

    def test_a_bad_capability_value(self):
        d = descriptor()
        d["capabilities"]["skills"]["local"]["value"] = "maybe"
        self.one(d, "capabilities.skills.local.value: 'maybe' is not one of yes, partial, no")

    def test_a_capability_for_a_surface_the_provider_does_not_list(self):
        d = descriptor()
        d["surfaces"] = ["local"]
        self.one(d, "capabilities.skills.cloud: the provider does not list the surface 'cloud'")

    def test_an_unknown_capability(self):
        d = descriptor()
        d["capabilities"]["teleport"] = d["capabilities"]["mcp"]
        self.one(d, "capabilities.teleport: unknown capability")

    def test_a_model_that_does_not_match_the_pattern(self):
        d = descriptor()
        d["tier_detail"]["fast"]["model"] = "gpt-9"
        d["tiers"]["fast"] = "gpt-9"
        f = self.one(d, "tier_detail.fast.model: 'gpt-9' does not match model_pattern")
        self.assertEqual(len(f), 1)

    def test_a_model_pattern_that_is_not_a_regular_expression(self):
        d = descriptor()
        d["model_pattern"] = "(["
        self.one(d, "model_pattern: not a regular expression")

    def test_tiers_that_disagree_with_tier_detail(self):
        d = descriptor()
        d["tiers"]["balanced"] = "claude-sonnet-4-4"
        self.one(d, "tiers.balanced: 'claude-sonnet-4-4' differs from tier_detail.balanced.model 'claude-sonnet-5-5'")

    def test_aliases_that_disagree_with_tier_detail(self):
        d = descriptor()
        d["aliases"]["deep"] = "big"
        self.one(d, "aliases.deep: 'big' differs from tier_detail.deep.alias 'opus'")

    def test_no_surface_at_all(self):
        d = descriptor()
        d["surfaces"] = []
        self.one(d, "surfaces: needs at least 1 item")

    def test_an_unknown_surface(self):
        d = descriptor()
        d["surfaces"] = ["local", "moon"]
        self.one(d, "surfaces[1]: 'moon' is not one of local, cloud")

    def test_wrong_type(self):
        d = descriptor()
        d["adapter"] = 3
        self.one(d, "adapter: 3 is not of type string, null")

    def test_a_missing_required_key(self):
        d = descriptor()
        del d["effort"]
        self.one(d, "missing required property 'effort'")

    def test_a_schema_version_other_than_1(self):
        d = descriptor()
        d["schema"] = 2
        self.one(d, "schema: 2 is not the supported version 1")

    def test_a_missing_capability_cell_for_a_listed_surface_warns(self):
        d = descriptor()
        del d["capabilities"]["mcp"]["cloud"]
        self.assertEqual(fails(d), [])
        self.assertTrue(any("capabilities.mcp.cloud: no entry for the listed surface; it counts as not supported" in m for m in warns(d)))

    def test_every_violation_is_reported_not_only_the_first(self):
        d = descriptor()
        d["extra"] = 1
        d["tiers"]["fast"] = "x"
        self.assertGreaterEqual(len(fails(d)), 2)


class Cap(Tree):
    def test_load_reads_a_descriptor_by_name(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.load("claude", self.root)["provider"], "claude")

    def test_load_of_an_unknown_name_raises(self):
        for n in ("nope", "../claude", "schema", "Claude", ""):
            with self.assertRaises(P.ProviderError, msg=n):
                P.load(n, self.root)

    def test_load_of_broken_json_raises(self):
        with open(os.path.join(self.root, "bad.json"), "w") as f:
            f.write("{")
        with self.assertRaises(P.ProviderError):
            P.load("bad", self.root)

    def test_a_verified_yes_is_yes(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.cap("claude", "local", "per_dispatch_model_override", self.root), "yes")
        self.assertEqual(P.effective("claude", "local", "per_dispatch_model_override", self.root), "yes")

    def test_a_verified_partial_is_partial(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.cap("claude", "local", "read_only_barrier", self.root), "partial")
        self.assertEqual(P.effective("claude", "local", "read_only_barrier", self.root), "partial")

    def test_an_unverified_yes_counts_as_no(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.cap("claude", "cloud", "per_dispatch_model_override", self.root), "unverified")
        self.assertEqual(P.effective("claude", "cloud", "per_dispatch_model_override", self.root), "no")

    def test_an_unverified_partial_counts_as_no(self):
        d = descriptor()
        d["capabilities"]["read_only_barrier"]["local"]["verified_on"] = None
        self.put("claude", d)
        self.assertEqual(P.cap("claude", "local", "read_only_barrier", self.root), "unverified")
        self.assertEqual(P.effective("claude", "local", "read_only_barrier", self.root), "no")

    def test_a_no_is_no_even_without_a_date(self):
        d = descriptor()
        d["capabilities"]["read_only_barrier"]["cloud"]["verified_on"] = None
        self.put("claude", d)
        self.assertEqual(P.cap("claude", "cloud", "read_only_barrier", self.root), "no")
        self.assertEqual(P.effective("claude", "cloud", "read_only_barrier", self.root), "no")

    def test_a_surface_the_provider_does_not_list_is_no(self):
        d = descriptor()
        d["surfaces"] = ["local"]
        del d["capabilities"]["skills"]["cloud"]
        self.put("claude", d)
        self.assertEqual(P.effective("claude", "cloud", "skills", self.root), "no")

    def test_an_unknown_capability_or_surface_is_an_error(self):
        self.put("claude", CLAUDE)
        with self.assertRaises(P.ProviderError):
            P.cap("claude", "local", "teleport", self.root)
        with self.assertRaises(P.ProviderError):
            P.cap("claude", "moon", "skills", self.root)

    def test_the_default_root_is_beside_provider_py(self):
        self.assertEqual(P.cap("claude", "local", "skills"), "yes")


if __name__ == "__main__":
    unittest.main()
