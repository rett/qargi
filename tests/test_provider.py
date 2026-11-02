#!/usr/bin/env python3
"""Provider descriptors: lib/provider.py (load, validate, cap, effective) against lib/providers/schema.json.
Hermetic: every changed descriptor is a copy in a temporary directory, never the user's data.
Run: python3 tests/test_provider.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import copy, json, os, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
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
        for sch in ("schema.json", "schema-2.json"):
            shutil.copy(os.path.join(LIB, "providers", sch), self.root)

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

    def test_reserved_names_are_the_agent_types_the_claude_runtime_brings_itself(self):
        self.assertEqual(sorted(CLAUDE["local"]["reserved_names"]),
                         sorted("general-purpose explore plan statusline-setup claude-code-guide claude output-style-setup".split()))


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

    def test_an_adapter_outside_the_providers_directory(self):
        for ad in ("/usr/bin/adapter", "lib/providers/../guard.py", "bin/qargi", "adapter"):
            d = descriptor()
            d["adapter"] = ad
            self.one(d, "adapter: '%s' is not a path under lib/providers/" % ad)

    def test_the_adapter_may_be_null_or_a_path_under_lib_providers(self):
        d = descriptor()
        self.assertEqual(d["adapter"], "lib/providers/claude/adapter")
        self.assertEqual(fails(d), [])
        d["adapter"] = None
        self.assertEqual(fails(d), [])

    def test_a_missing_required_key(self):
        d = descriptor()
        del d["effort"]
        self.one(d, "missing required property 'effort'")

    def test_a_schema_version_other_than_1_or_2(self):
        d = descriptor()
        d["schema"] = 3
        self.one(d, "schema: 3 is not the supported version 1")

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
        self.assertEqual(P.cap("claude", "local", "per_dispatch_effort_override", self.root), "unverified")
        self.assertEqual(P.effective("claude", "local", "per_dispatch_effort_override", self.root), "no")

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


class Barrier(Tree):
    """require_barrier: a read-only role on a surface, from the descriptor and the project's recorded acceptance."""

    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp, "conf")
        os.makedirs(os.path.join(self.conf, "projects"))
        self.put("claude", CLAUDE)
        d = descriptor()
        d["provider"] = "bare"
        for s in ("local", "cloud"):
            d["capabilities"]["read_only_barrier"][s] = {"value": "no", "verified_on": "2026-10-31", "note": "nothing stops a write"}
        self.put("bare", d)

    def answers(self, project, models):
        with open(os.path.join(self.conf, "projects", project + ".json"), "w") as f:
            json.dump({"project": project, "models": models}, f)

    def rb(self, provider, surface, project=None):
        return P.require_barrier(provider, surface, project, root=self.root, conf=self.conf)

    ACC = {"by": "me", "at": "2026-10-31T12:00:00Z", "reason": "because I said so"}

    def test_a_partial_barrier_passes_with_its_note(self):
        state, text = self.rb("claude", "local")
        self.assertEqual(state, "partial")
        self.assertIn("PreToolUse hook", text)

    def test_no_barrier_is_refused_with_the_command(self):
        state, text = self.rb("claude", "cloud", "alpha")
        self.assertEqual(state, "refused")
        self.assertIn("qargi provider accept claude --surface cloud --no-barrier --project alpha --asked", text)

    def test_the_command_names_a_placeholder_without_a_project(self):
        self.assertIn("--project PROJECT", self.rb("bare", "local")[1])

    def test_an_unverified_partial_counts_as_no(self):
        d = descriptor()
        d["provider"] = "unver"
        d["capabilities"]["read_only_barrier"]["local"] = {"value": "partial", "verified_on": None, "note": "maybe"}
        self.put("unver", d)
        state, text = self.rb("unver", "local")
        self.assertEqual(state, "refused")
        self.assertIn("not verified", text)

    def test_a_recorded_acceptance_allows_it_for_that_surface_only(self):
        self.answers("alpha", {"accept_no_barrier": {"cloud": self.ACC}})
        self.assertEqual(self.rb("claude", "cloud", "alpha")[0], "accepted")
        self.assertEqual(self.rb("bare", "cloud", "alpha")[0], "accepted")
        self.assertEqual(self.rb("bare", "local", "alpha")[0], "refused")
        self.assertEqual(self.rb("claude", "cloud", "beta")[0], "refused")

    def test_a_malformed_acceptance_is_none(self):
        for rec in ({"by": "me"}, "yes", {**self.ACC, "extra": 1}, {**self.ACC, "reason": ""}):
            self.answers("alpha", {"accept_no_barrier": {"cloud": rec}})
            self.assertIsNone(P.accepted("alpha", "cloud", self.conf), rec)
        self.answers("alpha", {"accept_no_barrier": "all"})
        self.assertIsNone(P.accepted("alpha", "cloud", self.conf))

    def test_a_verified_yes_passes_silently(self):
        d = descriptor()
        d["provider"] = "solid"
        d["capabilities"]["read_only_barrier"]["cloud"] = {"value": "yes", "verified_on": "2026-10-31", "note": "enforced"}
        self.put("solid", d)
        self.assertEqual(self.rb("solid", "cloud"), ("yes", ""))

    def test_an_unknown_provider_raises(self):
        with self.assertRaises(P.ProviderError):
            self.rb("nope", "cloud")

    def test_the_cli_exits_2_when_refused_and_0_when_accepted_or_partial(self):
        env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.tmp, "state"), HOME=os.path.join(self.tmp, "home"))
        os.makedirs(env["HOME"])

        def rb(*a):
            r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py"), "require-barrier"] + list(a), capture_output=True, text=True, env=env)
            return r.returncode, r.stderr
        rc, err = rb("claude", "cloud", "--project", "alpha")
        self.assertEqual(rc, 2)
        self.assertIn("qargi provider accept claude --surface cloud --no-barrier --project alpha", err)
        rc, err = rb("claude", "local")
        self.assertEqual((rc, "partial read-only barrier" in err), (0, True))
        self.answers("alpha", {"accept_no_barrier": {"cloud": self.ACC}})
        self.assertEqual(rb("claude", "cloud", "--project", "alpha"), (0, ""))
        self.assertEqual(rb("nope", "cloud")[0], 1)
        self.assertEqual(rb("claude", "moon")[0], 1)


class CliBase(Tree):
    """The verbs, run from a copy of provider.py with its own providers/ (so a changed descriptor never touches lib/)."""

    def setUp(self):
        super().setUp()
        self.copy = os.path.join(self.tmp, "lib")
        os.makedirs(self.copy)
        shutil.copy(os.path.join(LIB, "provider.py"), self.copy)
        os.rename(self.root, os.path.join(self.copy, "providers"))
        self.root = os.path.join(self.copy, "providers")
        shutil.copytree(os.path.join(LIB, "providers", "claude"), os.path.join(self.root, "claude"), ignore=shutil.ignore_patterns("__pycache__"))
        self.put("claude", CLAUDE)

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, "-I", os.path.join(self.copy, "provider.py")] + list(args), capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def other(self, mutate, name="other"):
        d = descriptor()
        d["provider"] = name
        mutate(d)
        self.put(name, d)


class Cli(CliBase):

    def test_list_has_one_line_per_provider_with_surfaces_and_state(self):
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 1)
        n = len(warns(CLAUDE))
        self.assertEqual(lines[0].split(), ["claude", "local,cloud", "%d" % n, "warnings"])

    def test_list_says_clean_for_a_clean_descriptor_and_counts_failures(self):
        def verify(d):
            for t in d["tier_detail"].values():
                t["verified_on"] = "2026-10-31"
            for cap in d["capabilities"].values():
                for c in cap.values():
                    c["verified_on"] = "2026-10-31"
        self.other(verify, "tidy")
        self.other(lambda d: d.update(extra=1, surfaces=["local"]), "broken")
        rc, out, _ = self.run_cli("list")
        rows = {ln.split()[0]: ln.split()[1:] for ln in out.strip().splitlines()}
        self.assertEqual(rc, 0)
        self.assertEqual(list(rows), ["broken", "claude", "tidy"])
        self.assertEqual(rows["tidy"], ["local,cloud", "clean"])
        self.assertEqual(rows["broken"][0], "local")
        self.assertEqual(rows["broken"][-1], "failures")

    def test_list_does_not_show_schema_json(self):
        self.assertNotIn("schema", self.run_cli("list")[1])

    def test_list_with_an_argument_is_a_usage_error(self):
        self.assertEqual(self.run_cli("list", "x")[0], 2)

    def test_show_prints_tiers_effort_and_the_matrix(self):
        rc, out, _ = self.run_cli("show", "claude")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"fast\s+claude-haiku-5-5\s+alias haiku\s+verified: no")
        self.assertRegex(out, r"frontier\s+claude-fable-5-1\s+alias fable")
        self.assertRegex(out, r"xhigh\s+xhigh")
        self.assertIn("per_dispatch_model_override", out)
        self.assertRegex(out, r"local\s+yes\s+verified 2026-10-31\s+Agent tool model parameter overrides the definition")
        self.assertRegex(out, r"cloud\s+yes\s+verified 2026-11-01\s+a session created with a model override")
        self.assertRegex(out, r"read_only_barrier\s*\n\s+local\s+partial")
        self.assertRegex(out, r"cloud\s+no\s+verified 2026-10-31")

    def test_show_json_is_the_descriptor(self):
        rc, out, _ = self.run_cli("show", "claude", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out), CLAUDE)

    def test_show_an_unknown_name_exits_1(self):
        for a in (["show", "nope"], ["check", "nope"], ["show", "../claude"], ["check", "schema"]):
            rc, out, err = self.run_cli(*a)
            self.assertEqual(rc, 1, a)
            self.assertIn("unknown provider", err)
            self.assertEqual(out, "")

    def test_show_and_check_without_a_name_is_a_usage_error(self):
        self.assertEqual(self.run_cli("show")[0], 2)
        self.assertEqual(self.run_cli("check")[0], 2)
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(self.run_cli("nonsense")[0], 2)

    def test_check_of_a_valid_descriptor_exits_0_and_warns(self):
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("warn: "), len(warns(CLAUDE)))
        self.assertIn("0 failures", out)
        self.assertIn("warn: tier_detail.fast.verified_on: not verified", out)

    def test_check_says_what_degrades_on_each_surface(self):
        out = self.run_cli("check", "claude")[1]
        self.assertRegex(out, r"local: per_dispatch_effort_override\s+unverified \(counts as no\)")
        self.assertNotRegex(out, r"cloud: per_dispatch_model_override")
        self.assertRegex(out, r"local: session_budget_ceiling\s+no")
        self.assertRegex(out, r"cloud: read_only_barrier\s+no")
        self.assertNotRegex(out, r"local: per_dispatch_model_override")
        self.assertNotRegex(out, r"local: read_only_barrier")

    def test_a_cloud_read_only_barrier_of_no_means_review_cannot_be_served_there(self):
        out = self.run_cli("check", "claude")[1]
        self.assertIn("the review role cannot be served on cloud", out)
        self.assertNotIn("cannot be served on local", out)

    def test_an_unverified_read_only_barrier_cannot_serve_review_either(self):
        def mutate(d):
            d["capabilities"]["read_only_barrier"]["cloud"].update(value="yes", verified_on=None)
        self.other(mutate)
        out = self.run_cli("check", "other")[1]
        self.assertRegex(out, r"cloud: read_only_barrier\s+unverified \(counts as no\)")
        self.assertIn("the review role cannot be served on cloud", out)

    def test_a_verified_read_only_barrier_on_both_surfaces_serves_review(self):
        def mutate(d):
            d["capabilities"]["read_only_barrier"]["cloud"].update(value="yes")
        self.other(mutate)
        out = self.run_cli("check", "other")[1]
        self.assertNotIn("cannot be served", out)

    def test_both_surfaces_without_a_barrier_print_both_lines(self):
        def mutate(d):
            d["capabilities"]["read_only_barrier"]["local"].update(value="no")
        self.other(mutate)
        out = self.run_cli("check", "other")[1]
        self.assertIn("the review role cannot be served on local", out)
        self.assertIn("the review role cannot be served on cloud", out)

    def test_a_provider_that_lists_only_local_is_not_judged_on_cloud(self):
        def mutate(d):
            d["surfaces"] = ["local"]
            for cap in d["capabilities"].values():
                cap.pop("cloud", None)
        self.other(mutate)
        rc, out, _ = self.run_cli("check", "other")
        self.assertEqual(rc, 0)
        self.assertNotIn("cloud", out)

    def test_check_reports_that_the_adapter_exists_and_is_executable(self):
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 0)
        self.assertIn("adapter: lib/providers/claude/adapter (exists, executable)", out)

    def test_check_fails_for_an_adapter_that_is_missing_or_not_executable(self):
        adapter = os.path.join(self.root, "claude", "adapter")
        os.chmod(adapter, 0o644)
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 1)
        self.assertIn("fail: adapter: lib/providers/claude/adapter is not executable", out)
        os.remove(adapter)
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 1)
        self.assertIn("fail: adapter: lib/providers/claude/adapter does not exist", out)

    def test_check_says_so_for_a_provider_with_no_adapter(self):
        self.other(lambda d: d.update(adapter=None))
        rc, out, _ = self.run_cli("check", "other")
        self.assertEqual(rc, 0)
        self.assertIn("adapter: none", out)

    def test_check_fails_with_exit_1_on_each_kind_of_violation(self):
        cases = {
            "additional": lambda d: d.update(extra=1),
            "name": lambda d: d.update(provider="elsewhere"),
            "tier": lambda d: d["tier_detail"].pop("deep"),
            "capability": lambda d: d["capabilities"].update(teleport={}),
            "pattern": lambda d: d.update(model_pattern="^zzz"),
            "tiers": lambda d: d["tiers"].update(fast="claude-other"),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.other(mutate, "other")
                rc, out, _ = self.run_cli("check", "other")
                self.assertEqual(rc, 1)
                self.assertRegex(out, r"fail: ")
                self.assertNotRegex(out, r"\b0 failures")

    def test_check_of_broken_json_exits_1(self):
        with open(os.path.join(self.root, "bad.json"), "w") as f:
            f.write("{")
        rc, _, err = self.run_cli("check", "bad")
        self.assertEqual(rc, 1)
        self.assertIn("not readable JSON", err)

    def test_through_qargi_itself(self):
        env = dict(os.environ, QARGI_CONF=os.path.join(self.tmp, "conf"), QARGI_STATE=os.path.join(self.tmp, "state"), HOME=os.path.join(self.tmp, "home"))
        os.makedirs(env["HOME"])

        def q(*a):
            r = subprocess.run([BIN, "provider"] + list(a), capture_output=True, text=True, env=env)
            return r.returncode, r.stdout, r.stderr
        rc, out, _ = q("list")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"^claude\s+local,cloud\s+\d+ warnings")
        rc, out, _ = q("show", "claude")
        self.assertEqual(rc, 0)
        self.assertIn("claude-haiku-5-5", out)
        rc, out, _ = q("check", "claude")
        self.assertEqual(rc, 0)
        self.assertIn("the review role cannot be served on cloud", out)
        self.assertEqual(q("check", "nope")[0], 1)
        self.assertEqual(json.loads(q("show", "claude", "--json")[1]), CLAUDE)


class Layout(Tree):
    """The optional layout object: where a provider keeps skills, agents, settings and memory, and how a session is launched."""

    def with_layout(self, **over):
        d = descriptor()
        d.setdefault("layout", {}).update(over)
        return d

    def test_the_shipped_claude_layout_is_valid_and_complete(self):
        lay = descriptor()["layout"]
        self.assertEqual(fails(descriptor()), [])
        self.assertEqual(lay["project_skills_dir"], ".claude/skills")
        self.assertEqual(lay["user_skills_dir"], "~/.claude/skills")
        self.assertEqual([s["scope"] for s in lay["settings_files"]], ["user", "project", "project-local"])
        self.assertEqual(lay["exclusion"], {"file_key": "skillOverrides", "off_value": "off"})
        self.assertEqual(lay["checkout_key"], "nonalnum-dash")
        self.assertEqual(lay["render_target"], "claude-code")
        self.assertIn("{render}", lay["session_launch"])

    def test_a_descriptor_without_a_layout_is_valid(self):
        d = descriptor()
        del d["layout"]
        self.assertEqual(fails(d), [])

    def test_unknown_layout_keys_are_rejected(self):
        self.assertTrue(any("layout.hooks_dir" in m for m in fails(self.with_layout(hooks_dir=".x"))))
        d = self.with_layout()
        d["layout"]["settings_files"].append({"scope": "user", "path": "~/x", "extra": 1})
        self.assertTrue(any("layout.settings_files[3].extra" in m for m in fails(d)))
        self.assertTrue(any("layout.exclusion.mode" in m for m in fails(self.with_layout(exclusion={"file_key": "k", "off_value": "off", "mode": 1}))))

    def test_layout_field_types_and_rules_are_checked(self):
        self.assertTrue(fails(self.with_layout(project_skills_dir=3)))
        self.assertTrue(fails(self.with_layout(settings_files=[{"scope": "world", "path": "x"}])))
        self.assertTrue(fails(self.with_layout(checkout_key="rot13")))
        self.assertTrue(any("project_skills_dir" in m for m in fails(self.with_layout(project_skills_dir="/abs/skills"))))
        self.assertTrue(any("project_skills_dir" in m for m in fails(self.with_layout(project_skills_dir="../up"))))
        self.assertTrue(any("user_skills_dir" in m for m in fails(self.with_layout(user_skills_dir="relative/skills"))))
        self.assertTrue(any("session_launch" in m for m in fails(self.with_layout(session_launch="agent run"))))
        self.assertTrue(any("memory_dir" in m for m in fails(self.with_layout(memory_dir="~/m/{checkout_key}", checkout_key=None))))
        self.assertTrue(any("exclusion" in m for m in fails(self.with_layout(settings_files=None))))

    def test_null_fields_are_valid(self):
        nulls = {k: None for k in P.LAYOUT_FIELDS}
        self.assertEqual(fails(self.with_layout(**nulls)), [])

    def test_the_accessor_expands_the_home_and_leaves_project_paths_relative(self):
        self.put("claude", CLAUDE)
        lay = P.layout("claude", root=self.root, home="/h/me")
        self.assertEqual(lay["user_skills_dir"], "/h/me/.claude/skills")
        self.assertEqual(lay["user_agents_dir"], "/h/me/.claude/agents")
        self.assertEqual(lay["project_skills_dir"], ".claude/skills")
        self.assertEqual([s["path"] for s in lay["settings_files"]], ["/h/me/.claude/settings.json", ".claude/settings.json", ".claude/settings.local.json"])
        self.assertEqual(lay["memory_dir"], "/h/me/.claude/projects/{checkout_key}/memory")
        self.assertEqual(CLAUDE["layout"]["user_skills_dir"], "~/.claude/skills")        # the descriptor itself is not changed

    def test_the_accessor_defaults_the_home_to_the_environment(self):
        self.put("claude", CLAUDE)
        old = os.environ.get("HOME")
        os.environ["HOME"] = "/env/home"
        try:
            self.assertEqual(P.layout("claude", root=self.root)["user_skills_dir"], "/env/home/.claude/skills")
        finally:
            os.environ["HOME"] = old

    def test_a_provider_without_a_layout_has_every_field_null(self):
        d = descriptor()
        del d["layout"]
        self.put("bare", dict(d, provider="bare"))
        lay = P.layout("bare", root=self.root)
        self.assertEqual(set(lay), set(P.LAYOUT_FIELDS))
        self.assertTrue(all(v is None for v in lay.values()))

    def test_require_returns_a_value_and_refuses_a_null_field_with_the_degrade_text(self):
        d = self.with_layout(project_skills_dir=None)
        self.put("claude", d)
        self.assertEqual(P.require("claude", "user_skills_dir", "x", root=self.root, home="/h"), "/h/.claude/skills")
        with self.assertRaises(P.Unsupported) as cm:
            P.require("claude", "project_skills_dir", "link the checkout's skills directory to the render", root=self.root)
        self.assertEqual(str(cm.exception), "provider claude has no project skills directory: link the checkout's skills directory to the render")
        self.assertIsInstance(cm.exception, P.ProviderError)

    def test_require_skills_wants_a_verified_skills_capability(self):
        d = descriptor()
        self.put("claude", d)
        P.require_skills("claude", "audit", root=self.root)
        d["capabilities"]["skills"]["local"]["verified_on"] = None
        self.put("claude", d)
        with self.assertRaises(P.Unsupported) as cm:
            P.require_skills("claude", "audit the skills a session loads", root=self.root)
        self.assertEqual(str(cm.exception), "provider claude has no skills support on the local surface: audit the skills a session loads")
        d["capabilities"]["skills"]["local"].update(value="no", verified_on="2026-10-31")
        self.put("claude", d)
        with self.assertRaises(P.Unsupported):
            P.require_skills("claude", "x", root=self.root)

    def test_checkout_key_replaces_every_non_alphanumeric(self):
        self.assertEqual(P.checkout_key("nonalnum-dash", "/home/me/My Proj.x/a_b"), "-home-me-My-Proj-x-a-b")
        with self.assertRaises(P.ProviderError):
            P.checkout_key("rot13", "/x")

    def test_memory_dir_is_the_template_with_the_key_filled_in(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.memory_dir("claude", "/home/me/p.q", root=self.root, home="/h"), "/h/.claude/projects/-home-me-p-q/memory")
        self.put("claude", self.with_layout(memory_dir=None))
        with self.assertRaises(P.Unsupported):
            P.memory_dir("claude", "/x", root=self.root)

    def test_the_launch_line_keeps_an_optional_group_only_when_its_file_exists(self):
        render = os.path.join(self.tmp, "render")
        os.makedirs(render)
        self.put("claude", CLAUDE)
        self.assertEqual(P.launch_line("claude", render, root=self.root), "claude --add-dir %s" % render)
        for f in ("mcp.json", "settings.json"):
            with open(os.path.join(render, f), "w") as fh:
                fh.write("{}")
        self.assertEqual(P.launch_line("claude", render, root=self.root),
                         "claude --add-dir %s --mcp-config %s/mcp.json --settings %s/settings.json" % (render, render, render))
        self.put("claude", self.with_layout(session_launch=None))
        with self.assertRaises(P.Unsupported):
            P.launch_line("claude", render, root=self.root)

    def test_project_provider_is_models_provider_and_has_no_default(self):
        self.assertEqual(P.project_provider({"models": {"provider": "other"}}, "p"), "other")
        msg = "project p has no provider: set one with qargi project set p models.provider NAME"
        for answers in ({}, None, {"models": {}}, {"models": {"provider": ""}}, {"models": {"provider": "  "}}, {"models": {"provider": 3}}):
            with self.assertRaises(P.NoProvider) as cm:
                P.project_provider(answers, "p")
            self.assertEqual(str(cm.exception), msg)
            self.assertIsInstance(cm.exception, P.ProviderError)


class LayoutCli(Cli):
    def test_layout_prints_json_or_one_field(self):
        rc, out, _ = self.run_cli("layout", "claude", "--home", "/h")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["user_skills_dir"], "/h/.claude/skills")
        rc, out, _ = self.run_cli("layout", "claude", "project_skills_dir")
        self.assertEqual((rc, out), (0, ".claude/skills\n"))
        rc, out, _ = self.run_cli("layout", "claude", "exclusion")
        self.assertEqual(json.loads(out), {"file_key": "skillOverrides", "off_value": "off"})

    def test_a_null_field_exits_3_with_the_degrade_text(self):
        d = descriptor()
        d["layout"]["project_skills_dir"] = None
        self.put("claude", d)
        rc, out, err = self.run_cli("layout", "claude", "project_skills_dir", "--would", "link the skills")
        self.assertEqual((rc, out), (3, ""))
        self.assertEqual(err, "qargi: provider claude has no project skills directory: link the skills\n")

    def test_check_lists_a_missing_layout_facility_among_the_degrades(self):
        rc, out, _ = self.run_cli("check", "claude")
        self.assertNotIn("layout:", out)
        d = descriptor()
        d["layout"]["session_launch"] = None
        self.put("claude", d)
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"layout: session_launch\s+no \(")

    def test_of_prints_the_provider_of_a_project_and_refuses_one_with_none_with_exit_2(self):
        conf = os.path.join(self.tmp, "conf")
        os.makedirs(os.path.join(conf, "projects"))
        for name, answers in (("withp", {"models": {"provider": "claude"}}), ("nop", {"models": {}}), ("badp", {"models": {"provider": "nope"}})):
            with open(os.path.join(conf, "projects", name + ".json"), "w") as f:
                json.dump(answers, f)
        self.assertEqual(self.run_cli("of", "withp", "--conf", conf)[:2], (0, "claude\n"))
        rc, out, err = self.run_cli("of", "nop", "--conf", conf)
        self.assertEqual((rc, out, err), (2, "", "qargi: project nop has no provider: set one with qargi project set nop models.provider NAME\n"))
        self.assertEqual(self.run_cli("of", "absent", "--conf", conf)[0], 2)
        self.assertEqual(self.run_cli("of", "badp", "--conf", conf)[:2], (0, "nope\n"))
        self.assertEqual(self.run_cli("layout", "nope")[0], 1)

    def test_an_unknown_field_or_provider_is_not_exit_3(self):
        self.assertEqual(self.run_cli("layout", "claude", "nope")[0], 2)
        self.assertEqual(self.run_cli("layout", "nope")[0], 1)

    def test_require_skills_and_launch(self):
        self.assertEqual(self.run_cli("require-skills", "claude")[0], 0)
        rc, out, _ = self.run_cli("launch", "claude", self.tmp)
        self.assertEqual((rc, out), (0, "claude --add-dir %s\n" % self.tmp))
        d = descriptor()
        d["capabilities"]["skills"]["local"]["value"] = "no"
        self.put("claude", d)
        rc, _, err = self.run_cli("require-skills", "claude", "--would", "audit")
        self.assertEqual(rc, 3)
        self.assertIn("provider claude has no skills support on the local surface: audit", err)


# ---- schema 2 ---------------------------------------------------------------------------------------------------------

def tier(model, alias=None, verified_on=None):
    return {"model": model, "alias": alias, "verified_on": verified_on, "source": "test"}


def runtime(name="mylocal", **over):
    """The smallest schema 2 runtime: one model for every tier, no effort control, run as a command."""
    d = {"schema": 2, "kind": "provider", "provider": name, "family": None, "surface": "local",
         "models": {"pattern": "^.+$", "tiers": {"*": tier("my-model")}, "effort": None},
         "dispatch": {"mode": "command", "argv": [name, "run", "--model", "{model}"], "prompt": {"via": "stdin"}, "cwd": "{clone}",
                      "output": {"format": "text"}},
         "agents": None, "resources": {}, "barrier": {"kind": "none"}}
    d.update(over)
    return d


def catalog(family="fam", **over):
    d = {"schema": 2, "kind": "catalog", "family": family, "version": "2026-11-02", "pattern": "^fam-[a-z0-9.-]+$",
         "tiers": {"fast": tier("fam-small", "small"), "balanced": tier("fam-mid", "mid"), "deep": tier("fam-big", "big"),
                   "frontier": tier("fam-top", None)},
         "effort": {"low": "low", "medium": "medium", "high": "high", "xhigh": None, "max": None}}
    d.update(over)
    return d


def cell(value="yes", verified_on="2026-11-02", note="n"):
    return {"value": value, "verified_on": verified_on, "source": "test", "note": note}


class Schema2(unittest.TestCase):
    """validate() of a schema 2 document: the node of schema-2.json for its kind, and the rules a schema cannot say."""

    def one(self, d, needle, name=None):
        f = fails(d, name or d.get("provider") or d.get("family"))
        self.assertTrue(any(needle in m for m in f), "%r not in %r" % (needle, f))
        return f

    def test_the_smallest_runtime_is_valid_and_clean(self):
        self.assertEqual(P.validate(runtime(), "mylocal"), [])

    def test_a_catalog_is_valid_and_a_runtime_may_reference_it(self):
        self.assertEqual(P.validate(catalog(), "fam"), [])
        d = runtime("fam-cli", family="fam", models={"catalog": "fam", "use": "alias"})
        self.assertEqual(fails(d, "fam-cli"), [])

    def test_a_full_cloud_or_local_runtime_with_resources_is_valid(self):
        res = {"skills": {"project_dir": ".fake/skills", "user_dir": "~/.fake/skills", "items": "dir-per-item", "entry": "SKILL.md",
                          "format": "skill-md", "link": {"project": "dir-symlink", "user": "entry-symlinks"},
                          "exclusion": {"form": "config-list", "file": "~/.fake/config.toml", "format": "toml", "pointer": "/skills/config",
                                        "match": {"name": "{name}"}, "off": {"enabled": False}}},
               "agents": {"project_dir": ".fake/agents", "user_dir": "~/.fake/agents", "items": "file-per-item", "ext": ".toml"},
               "instructions": {"project_file": ["AGENTS.md"], "items": "single-file"},
               "mcp": {"file": ".fake/mcp.json", "format": "json", "root_pointer": "/servers", "entry": {"command": "{command}"}, "permission_rule": None},
               "settings": {"files": [{"scope": "user", "path": "~/.fake/settings.json", "format": "json"}, {"scope": "project", "path": ".fake/settings.json"}],
                            "allow_pointer": "/allow"},
               "memory": {"user_dir": "~/.fake/mem/{checkout_key}", "checkout_key": "sha256-16", "link": {"user": "dir-symlink"}}}
        d = runtime("fakecli", resources=res, agents={"reserved_names": ["plan"], "tools": {"shell": "sh"}},
                    capabilities={"skills": cell(), "headless_dispatch": cell("partial")}, session={"launch": "fake --dir {render}", "render_target": "fakecli"},
                    adapter="adapter", adapter_verbs=["self-test"], barrier={"kind": "hook", "hook": {"input": "json-stdin"}})
        self.assertEqual(fails(d, "fakecli"), [])

    def test_an_unknown_or_unbuilt_kind_is_refused(self):
        self.one(runtime(kind="extension"), "kind: 'extension' is not one of provider, catalog")
        self.one(runtime(kind="widget"), "kind: 'widget' is not one of provider, catalog")
        d = runtime()
        del d["kind"]
        self.one(d, "missing required property 'kind'")

    def test_the_basic_violations(self):
        self.one(runtime(extra=1), "extra: additional property is not allowed")
        self.one(runtime(provider="Bad_Name"), "provider: 'Bad_Name' does not match")
        self.one(runtime("other"), "provider 'other' differs from the file name 'mylocal'", "mylocal")
        self.one(runtime(surface="both"), "surface: 'both' is not one of local, cloud")
        self.one(runtime(family="Bad"), "family: 'Bad' does not match")
        d = runtime()
        del d["models"]
        self.one(d, "missing required property 'models'")

    def test_models_take_the_catalog_form_or_the_inline_form_not_both(self):
        self.one(runtime(models={"catalog": "fam"}), "models: a catalog reference needs use (alias or id)")
        both = {"catalog": "fam", "use": "id", "pattern": "^.+$", "tiers": {"*": tier("m")}, "effort": None}
        self.one(runtime(models=both), "models: a catalog reference and inline models are two forms; give one")
        self.one(runtime(models={}), "models: needs a catalog reference or inline models (pattern and tiers)")
        self.one(runtime(models={"pattern": "^.+$"}), "models: inline models need tiers")
        self.one(runtime(models={"tiers": {"*": tier("m")}}), "models: inline models need pattern")

    def test_every_tier_must_resolve_and_match_the_pattern(self):
        m = {"pattern": "^m-.*$", "tiers": {"fast": tier("m-a"), "deep": tier("m-b")}, "effort": None}
        self.one(runtime(models=m), "models.tiers: tier 'balanced' resolves to no model (give it or '*')")
        m["tiers"]["*"] = tier("m-c")
        self.assertEqual(fails(runtime(models=m), "mylocal"), [])
        m["tiers"]["*"] = tier("zzz")
        self.one(runtime(models=m), "models.tiers.*.model: 'zzz' does not match pattern ^m-.*$")
        self.one(runtime(models={"pattern": "([", "tiers": {"*": tier("m")}, "effort": None}), "models.pattern: not a regular expression")

    def test_a_catalog_is_checked_like_inline_models(self):
        c = catalog()
        c["tiers"]["fast"]["model"] = "other-small"
        self.one(c, "tiers.fast.model: 'other-small' does not match pattern", "fam")
        del c["tiers"]["balanced"]
        self.one(c, "tiers: tier 'balanced' resolves to no model", "fam")
        self.one(catalog("other"), "family 'other' differs from the file name 'fam'", "fam")
        self.one(catalog(version="02/11/2026"), "version: '02/11/2026' is not a date", "fam")

    def test_capability_cells_are_flat_and_unverified_ones_warn(self):
        d = runtime(capabilities={"skills": cell(), "mcp": cell("yes", None), "resume": {"value": "yes"}})
        self.assertEqual(fails(d, "mylocal"), [])
        w = warns(d, "mylocal")
        self.assertEqual(sorted(m.split(":")[0] for m in w), ["capabilities.mcp.verified_on", "capabilities.resume.verified_on"])
        self.assertTrue(all("counts as not supported" in m for m in w))
        self.one(runtime(capabilities={"teleport": cell()}), "capabilities.teleport: unknown capability")
        self.one(runtime(capabilities={"skills": {"value": "maybe"}}), "capabilities.skills.value: 'maybe' is not one of yes, partial, no")
        self.one(runtime(capabilities={"skills": {"local": cell()}}), "capabilities.skills.local: additional property is not allowed")
        self.assertEqual(warns(runtime(capabilities={"skills": {"value": "no"}}), "mylocal"), [])

    def test_resource_paths_stay_inside_the_checkout_or_the_home(self):
        def bad(res, needle):
            self.one(runtime(resources=res), needle)
        bad({"skills": {"project_dir": "../out"}}, "resources.skills.project_dir: '../out' is not a path inside the checkout")
        bad({"skills": {"project_dir": "/abs"}}, "resources.skills.project_dir: '/abs' is not a path inside the checkout")
        bad({"agents": {"user_dir": "rel/dir"}}, "resources.agents.user_dir: 'rel/dir' does not start with ~/")
        bad({"settings": {"files": [{"scope": "user", "path": "rel"}]}}, "resources.settings.files[0].path: the user file 'rel' does not start with ~/")
        bad({"settings": {"files": [{"scope": "project", "path": "~/x"}]}}, "resources.settings.files[0].path: '~/x' is not a path inside the checkout")
        bad({"memory": {"user_dir": "/m"}}, "resources.memory.user_dir: '/m' does not start with ~/")
        bad({"memory": {"user_dir": "~/m/{checkout_key}", "checkout_key": None}}, "resources.memory.user_dir: uses {checkout_key} but checkout_key is null")
        bad({"mcp": {"file": "../x.json"}}, "resources.mcp.file: '../x.json' is not a path inside the checkout")

    def test_an_exclusion_form_needs_the_keys_that_form_reads(self):
        def excl(e):
            return {"skills": {"project_dir": ".s", "exclusion": e}}
        self.one(runtime(resources=excl({"form": "settings-key", "pointer": "/o"})), "resources.skills.exclusion: form settings-key needs files, pointer, shape and off")
        self.one(runtime(resources=excl({"form": "config-list", "file": "~/c.toml"})), "resources.skills.exclusion: form config-list needs file, format, pointer, match and off")
        self.one(runtime(resources=excl({"form": "deny-list", "file": "~/c.json", "format": "json"})), "resources.skills.exclusion: form deny-list needs file, format and pointer")
        key = {"form": "settings-key", "files": ["user", "project"], "pointer": "/o", "shape": "map", "off": "off"}
        self.one(runtime(resources=excl(key)), "resources.skills.exclusion.files: scope 'user' is not among resources.settings.files")
        res = excl(key)
        res["settings"] = {"files": [{"scope": "user", "path": "~/s.json"}]}
        self.one(runtime(resources=res), "resources.skills.exclusion.files: scope 'project' is not among resources.settings.files")
        res["settings"]["files"].append({"scope": "project", "path": "s.json"})
        self.assertEqual(fails(runtime(resources=res), "mylocal"), [])
        for e in ({"form": "none"}, {"form": "adapter"}, None):
            self.assertEqual(fails(runtime(resources=excl(e)), "mylocal"), [])

    def test_the_adapter_is_a_path_inside_the_definitions_directory(self):
        for ad in ("/usr/bin/x", "../x", "a/../../x"):
            self.one(runtime(adapter=ad), "adapter: '%s' is not a path inside the definition's directory" % ad)
        for ad in ("adapter", "bin/adapter", None):
            self.assertEqual(fails(runtime(adapter=ad), "mylocal"), [])

    def test_every_violation_is_reported_not_only_the_first(self):
        self.assertGreaterEqual(len(fails(runtime(extra=1, surface="x", family="Bad"), "mylocal")), 3)

    def test_a_schema_1_document_is_still_validated_as_schema_1(self):
        self.assertEqual(fails(descriptor()), [])
        d = descriptor()
        d["models"] = {}
        self.assertTrue(any("models: additional property is not allowed" in m for m in fails(d)))


class V2Tree(Tree):
    """A temporary shipped directory (root, with catalogs/) and a temporary pack library, both fixtures."""

    def setUp(self):
        super().setUp()
        self.library = os.path.join(self.tmp, "library")
        self.state = os.path.join(self.tmp, "state")
        os.makedirs(self.library)
        os.makedirs(os.path.join(self.root, "catalogs"))

    def put_catalog(self, family, d=None):
        with open(os.path.join(self.root, "catalogs", family + ".json"), "w") as f:
            json.dump(d or catalog(family), f)

    def put_lib(self, name, d):
        os.makedirs(os.path.join(self.library, name), exist_ok=True)
        with open(os.path.join(self.library, name, "definition.json"), "w") as f:
            json.dump(d, f)

    def kw(self, **extra):
        return dict(root=self.root, library=self.library, **extra)


class Loader(V2Tree):
    """The loader: shipped files and the pack library, schema 1 upgraded in memory, catalogs, the legacy view."""

    def test_the_shipped_claude_descriptor_loads_exactly_as_before(self):
        self.assertEqual(P.load("claude"), CLAUDE)
        self.assertIn("claude", P.names())
        self.assertEqual(P.cap("claude", "local", "skills"), "yes")
        self.assertEqual(P.origin("claude"), "shipped")

    def test_schema_1_is_upgraded_in_memory_one_definition_per_surface(self):
        self.put("claude", CLAUDE)
        self.assertEqual(P.surfaces_of("claude", **self.kw()), ["local", "cloud"])
        loc = P.definition("claude", "local", **self.kw())
        cld = P.definition("claude", "cloud", **self.kw())
        self.assertEqual((loc["schema"], loc["kind"], loc["provider"], loc["surface"], loc["family"]), (2, "provider", "claude", "local", None))
        self.assertEqual(cld["surface"], "cloud")
        self.assertEqual(loc["models"]["pattern"], CLAUDE["model_pattern"])
        self.assertEqual(loc["models"]["tiers"], CLAUDE["tier_detail"])
        self.assertEqual(loc["capabilities"]["skills"], CLAUDE["capabilities"]["skills"]["local"])
        self.assertEqual(cld["capabilities"]["skills"], CLAUDE["capabilities"]["skills"]["cloud"])
        self.assertEqual(loc["agents"]["reserved_names"], CLAUDE["local"]["reserved_names"])
        self.assertIsNone(cld["agents"])
        self.assertEqual(loc["adapter"], "adapter")
        with self.assertRaises(P.ProviderError) as cm:
            P.definition("claude", **self.kw())
        self.assertIn("serves local, cloud; name the surface", str(cm.exception))
        with open(os.path.join(self.root, "claude.json")) as f:      # the file itself is untouched
            self.assertEqual(json.load(f), CLAUDE)

    def test_the_layout_of_schema_1_is_mapped_to_resources(self):
        self.put("claude", CLAUDE)
        res = P.definition("claude", "local", **self.kw())["resources"]
        self.assertEqual(res["skills"]["project_dir"], ".claude/skills")
        self.assertEqual(res["skills"]["user_dir"], "~/.claude/skills")
        self.assertEqual(res["skills"]["exclusion"], {"form": "settings-key", "files": ["user", "project", "project-local"], "pointer": "/skillOverrides",
                                                      "shape": "map", "off": "off"})
        self.assertEqual(res["agents"]["project_dir"], ".claude/agents")
        self.assertEqual([f["scope"] for f in res["settings"]["files"]], ["user", "project", "project-local"])
        self.assertEqual(res["memory"], {"user_dir": "~/.claude/projects/{checkout_key}/memory", "checkout_key": "nonalnum-dash", "link": {"user": "dir-symlink"}})
        self.assertEqual(P.definition("claude", "cloud", **self.kw())["resources"], {})
        self.assertEqual(fails(P.definition("claude", "local", **self.kw()), "claude"), [])      # and the result is a valid schema 2 document

    def test_the_layout_accessor_answers_from_the_resources_for_both_schemas(self):
        self.put("claude", CLAUDE)
        want = dict(CLAUDE["layout"])
        lay = P.layout("claude", home="/h", **self.kw())
        self.assertEqual(lay["project_skills_dir"], want["project_skills_dir"])
        self.assertEqual(lay["exclusion"], want["exclusion"])
        self.assertEqual(lay["render_target"], "claude-code")
        self.assertEqual(lay["session_launch"], want["session_launch"])
        self.assertEqual(lay["settings_files"][0], {"scope": "user", "path": "/h/.claude/settings.json"})
        res = {"skills": {"project_dir": ".fake/skills", "user_dir": "~/.fake/skills", "items": "dir-per-item", "entry": "SKILL.md"},
               "settings": {"files": [{"scope": "user", "path": "~/.fake/s.json", "format": "json"}]},
               "memory": {"user_dir": "~/.fake/m/{checkout_key}", "checkout_key": "nonalnum-dash"}}
        self.put("fakecli", runtime("fakecli", resources=res, session={"launch": "fake --add {render}", "render_target": "fakecli"}))
        lay = P.layout("fakecli", home="/h", **self.kw())
        self.assertEqual((lay["project_skills_dir"], lay["user_skills_dir"], lay["project_agents_dir"]), (".fake/skills", "/h/.fake/skills", None))
        self.assertEqual((lay["memory_dir"], lay["checkout_key"], lay["exclusion"], lay["render_target"]), ("/h/.fake/m/{checkout_key}", "nonalnum-dash", None, "fakecli"))
        self.assertEqual(P.launch_line("fakecli", "/r", **self.kw()), "fake --add /r")
        self.put("plain", runtime("plain", resources=res))
        self.assertIsNone(P.layout("plain", **self.kw())["render_target"])                  # no session, no packs renderer of its own
        with self.assertRaises(P.Unsupported) as cm:
            P.require("plain", "render_target", "render the packs", **self.kw())
        self.assertEqual(str(cm.exception), "provider plain has no packs render target: render the packs")
        self.assertEqual(P.memory_dir("fakecli", "/x/y", home="/h", **self.kw()), "/h/.fake/m/-x-y")
        with self.assertRaises(P.Unsupported) as cm:
            P.require("fakecli", "project_agents_dir", "write the agent", **self.kw())
        self.assertEqual(str(cm.exception), "provider fakecli has no project agents directory: write the agent")

    def test_a_v2_fixture_loads_and_reads_like_a_v1_one_through_load(self):
        self.put("fakecli", runtime("fakecli", capabilities={"skills": cell()}))
        self.assertEqual(P.names(**self.kw()), ["fakecli"])
        d = P.load("fakecli", **self.kw())
        self.assertEqual((d["provider"], d["surfaces"], d["model_pattern"]), ("fakecli", ["local"], "^.+$"))
        self.assertEqual(d["tiers"], {t: "my-model" for t in P.TIERS})
        self.assertEqual(d["aliases"], {t: None for t in P.TIERS})
        self.assertEqual(d["effort"], {e: None for e in ("low", "medium", "high", "xhigh", "max")})
        self.assertEqual(d["capabilities"]["skills"], {"local": cell()})
        self.assertEqual(d["local"], {"reserved_names": []})
        self.assertEqual(P.cap("fakecli", "local", "skills", **self.kw()), "yes")
        self.assertEqual(P.cap("fakecli", "cloud", "skills", **self.kw()), "no")
        self.assertEqual(P.definition("fakecli", **self.kw())["provider"], "fakecli")
        self.assertEqual(P.models_of("fakecli", **self.kw())["tiers"]["deep"]["model"], "my-model")

    def test_a_catalog_reference_takes_the_models_of_the_catalog(self):
        self.put_catalog("fam")
        self.put("fam-cli", runtime("fam-cli", family="fam", models={"catalog": "fam", "use": "alias"}))
        self.put("fam-hosted", runtime("fam-hosted", family="fam", surface="cloud", models={"catalog": "fam", "use": "id"}))
        m = P.models_of("fam-cli", **self.kw())
        self.assertEqual((m["catalog"], m["use"], m["pattern"]), ("fam", "alias", "^fam-[a-z0-9.-]+$"))
        self.assertEqual(m["tiers"]["balanced"], tier("fam-mid", "mid"))
        self.assertEqual(m["effort"], {"low": "low", "medium": "medium", "high": "high", "xhigh": None, "max": None})
        self.assertEqual([P.model_for(m, t) for t in P.TIERS], ["small", "mid", "big", "fam-top"])       # alias when the tier has one, else the id
        mh = P.models_of("fam-hosted", **self.kw())
        self.assertEqual([P.model_for(mh, t) for t in P.TIERS], ["fam-small", "fam-mid", "fam-big", "fam-top"])
        d = P.load("fam-cli", **self.kw())
        self.assertEqual((d["tiers"]["fast"], d["aliases"]["fast"], d["model_pattern"]), ("fam-small", "small", "^fam-[a-z0-9.-]+$"))

    def test_a_catalog_reference_to_nothing_or_to_a_runtime_is_refused(self):
        self.put("lost", runtime("lost", models={"catalog": "nope", "use": "id"}))
        with self.assertRaises(P.ProviderError) as cm:
            P.models_of("lost", **self.kw())
        self.assertIn("no catalog 'nope'", str(cm.exception))
        with open(os.path.join(self.root, "catalogs", "wrong.json"), "w") as f:
            json.dump(runtime("wrong"), f)
        self.put("lost", runtime("lost", models={"catalog": "wrong", "use": "id"}))
        with self.assertRaises(P.ProviderError) as cm:
            P.models_of("lost", **self.kw())
        self.assertIn("catalog 'wrong' is not a catalog", str(cm.exception))

    def test_the_pack_library_adds_definitions_and_catalogs(self):
        self.put_lib("libcat", catalog("libcat"))
        self.put_lib("libcli", runtime("libcli", family="libcat", models={"catalog": "libcat", "use": "id"}))
        self.put("fakecli", runtime("fakecli"))
        self.assertEqual(P.names(**self.kw()), ["fakecli", "libcli"])            # a catalog is not a runtime
        self.assertEqual((P.origin("libcli", **self.kw()), P.origin("fakecli", **self.kw())), ("library", "shipped"))
        self.assertEqual(P.models_of("libcli", **self.kw())["tiers"]["fast"]["model"], "fam-small")
        self.assertEqual(P.load("libcli", **self.kw())["provider"], "libcli")
        with self.assertRaises(P.ProviderError) as cm:
            P.load("nope", **self.kw())
        self.assertIn("available: fakecli, libcli", str(cm.exception))

    def test_a_broken_library_definition_breaks_only_itself(self):
        self.put("fakecli", runtime("fakecli"))
        os.makedirs(os.path.join(self.library, "broken"))
        with open(os.path.join(self.library, "broken", "definition.json"), "w") as f:
            f.write("{")
        self.put_lib("named", runtime("other-name"))
        self.put_lib("old", descriptor())
        self.assertEqual(P.names(**self.kw()), ["broken", "fakecli", "named", "old"])
        self.assertEqual(P.load("fakecli", **self.kw())["provider"], "fakecli")
        for n, needle in (("broken", "not readable JSON"), ("named", "declares provider 'other-name'"), ("old", "library definitions are schema 2")):
            with self.assertRaises(P.ProviderError, msg=n) as cm:
                P.load(n, **self.kw())
            self.assertIn(needle, str(cm.exception))

    def test_the_same_name_in_the_shipped_directory_and_the_library_is_refused(self):
        self.put("dupe", runtime("dupe"))
        self.put_lib("dupe", runtime("dupe"))
        self.put("fine", runtime("fine"))
        with self.assertRaises(P.Clash) as cm:
            P.load("dupe", **self.kw())
        self.assertEqual(str(cm.exception), "'dupe' is defined twice (shipped and library); qargi provider remove dupe, or rename it")
        self.assertIsInstance(cm.exception, P.ProviderError)
        for f in (P.definition, P.surfaces_of, P.models_of):
            with self.assertRaises(P.Clash):
                f("dupe", **self.kw())
        with self.assertRaises(P.Clash):
            P.effective("dupe", "local", "skills", **self.kw())
        self.assertEqual(P.load("fine", **self.kw())["provider"], "fine")        # a clash refuses what needs the name, nothing else
        self.assertEqual(P.names(**self.kw()), ["dupe", "fine"])

    def test_a_catalog_in_both_places_or_a_library_name_taken_by_a_shipped_catalog_is_refused(self):
        self.put_catalog("fam")
        self.put_lib("fam", catalog("fam"))
        self.put("user", runtime("user", models={"catalog": "fam", "use": "id"}))
        with self.assertRaises(P.Clash):
            P.models_of("user", **self.kw())
        self.put_catalog("taken")
        self.put_lib("taken", runtime("taken"))
        with self.assertRaises(P.Clash):
            P.load("taken", **self.kw())

    def test_an_explicit_root_without_a_library_sees_no_library(self):
        self.put_lib("libcli", runtime("libcli"))
        self.put("fakecli", runtime("fakecli"))
        self.assertEqual(P.names(root=self.root), ["fakecli"])

    def test_the_default_library_is_below_the_configuration_directory(self):
        conf = os.environ["QARGI_CONF"]
        self.assertEqual(P.library_dir(), os.path.join(conf, "packs", "providers"))
        os.makedirs(os.path.join(conf, "packs", "providers", "homecli"))
        self.addCleanup(shutil.rmtree, os.path.join(conf, "packs", "providers", "homecli"), True)
        with open(os.path.join(conf, "packs", "providers", "homecli", "definition.json"), "w") as f:
            json.dump(runtime("homecli"), f)
        self.assertIn("homecli", P.names())
        self.assertEqual(P.origin("homecli"), "library")


class Verified(V2Tree):
    """A capability counts when it is claimed and verified: shipped, verified_on; library, a record in state/providers/NAME/verified.json
    whose hash is the hash of the definition as it is now."""

    def setUp(self):
        super().setUp()
        self.lib = runtime("libcli", capabilities={"skills": cell("yes", "2026-11-02"), "mcp": cell("partial", None), "resume": cell("no", None)})
        self.put_lib("libcli", self.lib)

    def record(self, **cells):
        os.makedirs(os.path.join(self.state, "providers", "libcli"), exist_ok=True)
        with open(os.path.join(self.state, "providers", "libcli", "verified.json"), "w") as f:
            json.dump(cells, f)

    def good(self, by="conformance"):
        return {"hash": P.definition_hash("libcli", **self.kw()), "by": by, "at": "2026-11-02T10:00:00Z", "note": "n"}

    def eff(self, capability="skills"):
        return P.effective("libcli", "local", capability, **self.kw(state=self.state))

    def test_an_unverified_library_capability_is_demoted_even_with_a_date(self):
        self.assertEqual(P.cap("libcli", "local", "skills", **self.kw(state=self.state)), "unverified")
        self.assertEqual(self.eff("skills"), "no")
        self.assertEqual(self.eff("mcp"), "no")

    def test_a_record_with_the_hash_of_the_definition_verifies_it(self):
        self.record(skills=self.good(), mcp=self.good("attest"))
        self.assertEqual(P.cap("libcli", "local", "skills", **self.kw(state=self.state)), "yes")
        self.assertEqual(self.eff("skills"), "yes")
        self.assertEqual(self.eff("mcp"), "partial")                  # the record verifies; the claim stays partial, a date is not needed
        self.assertEqual(self.eff("resume"), "no")

    def test_a_record_binds_one_capability_only(self):
        self.record(skills=self.good())
        self.assertEqual(self.eff("skills"), "yes")
        self.assertEqual(self.eff("mcp"), "no")

    def test_a_record_with_a_stale_hash_is_demoted(self):
        stale = dict(self.good(), hash="0" * 64)
        self.record(skills=stale)
        self.assertEqual(self.eff("skills"), "no")
        self.assertEqual(P.cap("libcli", "local", "skills", **self.kw(state=self.state)), "unverified")

    def test_a_record_goes_stale_when_the_definition_or_its_catalog_changes(self):
        self.record(skills=self.good())
        self.assertEqual(self.eff("skills"), "yes")
        self.put_lib("libcli", dict(self.lib, description="changed"))
        self.assertEqual(self.eff("skills"), "no")
        self.put_catalog("fam")
        self.put_lib("libcli", dict(self.lib, models={"catalog": "fam", "use": "id"}))
        self.record(skills=self.good())
        self.assertEqual(self.eff("skills"), "yes")
        c = catalog("fam")
        c["version"] = "2026-11-03"
        self.put_catalog("fam", c)
        self.assertEqual(self.eff("skills"), "no")

    def test_a_malformed_record_verifies_nothing(self):
        for rec in ({"skills": "yes"}, {"skills": dict(self.good(), by="me")}, {"skills": {"by": "conformance"}}, {"skills": dict(self.good(), hash=7)}, ["skills"]):
            self.record(**rec) if isinstance(rec, dict) else self.record_raw(rec)
            self.assertEqual(self.eff("skills"), "no", rec)
        with open(os.path.join(self.state, "providers", "libcli", "verified.json"), "w") as f:
            f.write("{")
        self.assertEqual(self.eff("skills"), "no")

    def record_raw(self, data):
        with open(os.path.join(self.state, "providers", "libcli", "verified.json"), "w") as f:
            json.dump(data, f)

    def test_a_missing_catalog_leaves_the_definition_unverified_not_broken(self):
        self.put_lib("libcli", dict(self.lib, models={"catalog": "gone", "use": "id"}))
        self.record(skills={"hash": "0" * 64, "by": "conformance"})
        self.assertEqual(self.eff("skills"), "no")

    def test_a_shipped_definition_is_verified_by_its_date_and_needs_no_record(self):
        self.put("fakecli", runtime("fakecli", capabilities={"skills": cell("yes", "2026-11-02"), "mcp": cell("yes", None)}))
        kw = self.kw(state=self.state)
        self.assertEqual(P.effective("fakecli", "local", "skills", **kw), "yes")
        self.assertEqual(P.cap("fakecli", "local", "mcp", **kw), "unverified")
        os.makedirs(os.path.join(self.state, "providers", "fakecli"))
        with open(os.path.join(self.state, "providers", "fakecli", "verified.json"), "w") as f:
            json.dump({"mcp": {"hash": P.definition_hash("fakecli", **self.kw()), "by": "attest"}}, f)
        self.assertEqual(P.cap("fakecli", "local", "mcp", **kw), "unverified")          # a record is for the library; a shipped file is verified by its date

    def test_require_skills_and_the_barrier_follow_the_record(self):
        self.put_lib("libcli", dict(self.lib, capabilities={"skills": cell("yes", None), "read_only_barrier": cell("yes", None)}))
        with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):             # the default state directory is QARGI_STATE
            with self.assertRaises(P.Unsupported):
                P.require_skills("libcli", "x", **self.kw())
            self.record(skills=self.good(), read_only_barrier=self.good())
            P.require_skills("libcli", "x", **self.kw())
            self.assertEqual(P.require_barrier("libcli", "local", None, **self.kw())[0], "yes")


class Family(V2Tree):
    """A name in models.provider is a runtime or a family; a family names exactly one runtime on a surface."""

    def setUp(self):
        super().setUp()
        self.put("fam-cli", runtime("fam-cli", family="fam"))
        self.put("fam-hosted", runtime("fam-hosted", family="fam", surface="cloud"))
        self.put("solo", runtime("solo"))

    def res(self, name, surface):
        return P.resolve_runtime(name, surface, **self.kw())

    def test_a_runtime_name_resolves_to_itself_on_the_surface_it_serves(self):
        self.assertEqual(self.res("fam-cli", "local"), "fam-cli")
        self.assertEqual(self.res("solo", "local"), "solo")

    def test_a_family_name_matches_the_one_runtime_of_each_surface(self):
        self.assertEqual(self.res("fam", "local"), "fam-cli")
        self.assertEqual(self.res("fam", "cloud"), "fam-hosted")

    def test_a_family_with_two_runtimes_on_a_surface_is_ambiguous_there_only(self):
        self.put("fam-other", runtime("fam-other", family="fam"))
        with self.assertRaises(P.Ambiguous) as cm:
            self.res("fam", "local")
        self.assertEqual(str(cm.exception), "the family 'fam' has more than one runtime on the local surface (fam-cli, fam-other); name one of them")
        self.assertIsInstance(cm.exception, P.Refused)
        self.assertEqual(self.res("fam", "cloud"), "fam-hosted")
        self.assertEqual(self.res("fam-cli", "local"), "fam-cli")        # naming the runtime is never ambiguous

    def test_a_library_runtime_joins_its_family(self):
        self.put_lib("libcli", runtime("libcli", family="fam"))
        with self.assertRaises(P.Ambiguous) as cm:
            self.res("fam", "local")
        self.assertIn("(fam-cli, libcli)", str(cm.exception))

    def test_a_runtime_of_the_other_surface_and_an_unknown_name_are_refused(self):
        with self.assertRaises(P.Refused) as cm:
            self.res("fam-cli", "cloud")
        self.assertEqual(str(cm.exception), "the provider fam-cli does not serve the cloud surface (it serves local)")
        with self.assertRaises(P.Refused) as cm:
            self.res("nope", "local")
        self.assertEqual(str(cm.exception), "no runtime or family 'nope' for the local surface; available: fam, fam-cli, solo")
        with self.assertRaises(P.Refused) as cm:
            self.res("solo", "cloud")
        self.assertIn("does not serve the cloud surface", str(cm.exception))

    def test_a_clash_refuses_a_family_that_a_clashing_name_belongs_to_and_nothing_else(self):
        self.put("dupe", runtime("dupe", family="other"))
        self.put_lib("dupe", runtime("dupe", family="other"))
        self.assertEqual(self.res("fam", "local"), "fam-cli")
        with self.assertRaises(P.Clash):
            self.res("other", "local")
        with self.assertRaises(P.Clash):
            self.res("dupe", "local")

    def test_a_schema_1_provider_is_a_runtime_of_its_own_name_on_each_surface_it_lists(self):
        self.put("claude", CLAUDE)
        self.assertEqual((self.res("claude", "local"), self.res("claude", "cloud")), ("claude", "claude"))


class PerSurface(V2Tree):
    """provider_of(answers, surface): models.provider is one name or an object {local, cloud}; no default."""

    def setUp(self):
        super().setUp()
        self.put("fam-cli", runtime("fam-cli", family="fam"))
        self.put("fam-hosted", runtime("fam-hosted", family="fam", surface="cloud"))
        self.put("solo", runtime("solo"))
        self.put("claude", CLAUDE)

    def of(self, provider, surface, project="p"):
        return P.provider_of({"models": {"provider": provider}}, surface, project, **self.kw())

    def test_the_object_form_names_a_runtime_or_a_family_per_surface(self):
        self.assertEqual(self.of({"local": "solo", "cloud": "fam-hosted"}, "local"), "solo")
        self.assertEqual(self.of({"local": "solo", "cloud": "fam-hosted"}, "cloud"), "fam-hosted")
        self.assertEqual(self.of({"local": "fam", "cloud": "fam"}, "cloud"), "fam-hosted")

    def test_the_string_form_is_a_runtime_or_a_family_resolved_for_the_surface(self):
        self.assertEqual(self.of("solo", "local"), "solo")
        self.assertEqual(self.of(" fam ", "local"), "fam-cli")
        self.assertEqual(self.of("fam", "cloud"), "fam-hosted")
        self.assertEqual(self.of("claude", "local"), "claude")
        self.assertEqual(self.of("claude", "cloud"), "claude")

    def test_a_string_that_resolves_through_its_family_comes_with_a_notice(self):
        models = {"models": {"provider": "fam"}}
        self.assertEqual(P.resolve_project(models, "local", "p", **self.kw()),
                         ("fam-cli", "models.provider is the single name 'fam'; on the local surface it resolves to fam-cli through the family. "
                                     "Name a runtime for each surface: qargi project set p models.provider.local fam-cli"))
        for provider in ("solo", "claude"):
            self.assertIsNone(P.resolve_project({"models": {"provider": provider}}, "local", "p", **self.kw())[1])
        self.assertIsNone(P.resolve_project({"models": {"provider": {"local": "fam"}}}, "local", "p", **self.kw())[1])

    def test_a_string_naming_a_runtime_of_the_other_surface_leaves_that_surface_unset(self):
        with self.assertRaises(P.NoProvider) as cm:
            self.of("solo", "cloud")
        self.assertEqual(str(cm.exception), "project p has no cloud provider: its provider 'solo' does not serve that surface; "
                                            "set one with qargi project set p models.provider.cloud NAME")
        self.assertEqual(P.NoProvider.__mro__[1], P.ProviderError)

    def test_an_unset_surface_is_no_provider_with_the_standard_message(self):
        standard = "project p has no provider: set one with qargi project set p models.provider NAME"
        for answers in ({}, None, {"models": {}}, {"models": {"provider": ""}}, {"models": {"provider": "  "}}, {"models": {"provider": 3}}, {"models": {"provider": None}}):
            for surface in P.SURFACES:
                with self.assertRaises(P.NoProvider, msg=repr(answers)) as cm:
                    P.provider_of(answers, surface, "p", **self.kw())
                self.assertEqual(str(cm.exception), standard)
        for provider, surface in (({"local": "solo"}, "cloud"), ({}, "local"), ({"local": "solo", "cloud": " "}, "cloud"), ({"cloud": None}, "cloud")):
            with self.assertRaises(P.NoProvider) as cm:
                self.of(provider, surface)
            self.assertEqual(str(cm.exception), "project p has no %s provider: set one with qargi project set p models.provider.%s NAME" % (surface, surface))

    def test_an_unknown_surface_key_or_name_is_refused(self):
        with self.assertRaises(P.Refused) as cm:
            self.of({"local": "solo", "moon": "solo"}, "local")
        self.assertEqual(str(cm.exception), "models.provider: unknown surface 'moon'; one of local, cloud")
        with self.assertRaises(P.Refused):
            self.of({"local": "nope"}, "local")
        with self.assertRaises(P.ProviderError):
            P.provider_of({"models": {"provider": "solo"}}, "moon", "p", **self.kw())

    def test_the_earlier_calls_keep_working(self):
        self.assertEqual(P.project_provider({"models": {"provider": "claude"}}, "p"), "claude")
        self.assertEqual(P.project_provider({"models": {"provider": "fam"}}, "p"), "fam")            # a string is not resolved without a surface
        self.assertEqual(P.project_provider({"models": {"provider": {"local": "solo", "cloud": "solo"}}}, "p", **self.kw()), "solo")
        with self.assertRaises(P.Refused) as cm:
            P.project_provider({"models": {"provider": {"local": "solo", "cloud": "fam-hosted"}}}, "p", **self.kw())
        self.assertIn("names a runtime per surface", str(cm.exception))
        self.assertEqual(P.project_provider({"models": {"provider": {"local": "fam"}}}, "p", "local", **self.kw()), "fam-cli")


class PerSurfaceCli(CliBase):
    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp, "conf")
        os.makedirs(os.path.join(self.conf, "projects"))
        self.put("fam-cli", runtime("fam-cli", family="fam"))
        self.put("fam-hosted", runtime("fam-hosted", family="fam", surface="cloud"))
        self.put("fam-other", runtime("fam-other", family="fam", surface="cloud"))
        for name, provider in (("str", "claude"), ("fam", "fam"), ("obj", {"local": "fam-cli"}), ("none", None), ("amb", {"cloud": "fam"})):
            models = {} if provider is None else {"provider": provider}
            with open(os.path.join(self.conf, "projects", name + ".json"), "w") as f:
                json.dump({"project": name, "models": models}, f)

    def of(self, project, *extra):
        return self.run_cli("of", project, "--conf", self.conf, *extra)

    def test_of_with_a_surface_resolves_and_prints_the_runtime(self):
        self.assertEqual(self.of("str", "--surface", "cloud")[:2], (0, "claude\n"))
        self.assertEqual(self.of("obj", "--surface", "local")[:2], (0, "fam-cli\n"))
        rc, out, err = self.run_cli("of", "--surface", "local", "fam", "--conf", self.conf)
        self.assertEqual((rc, out), (0, "fam-cli\n"))
        self.assertEqual(err, "qargi: note: models.provider is the single name 'fam'; on the local surface it resolves to fam-cli through the family. "
                              "Name a runtime for each surface: qargi project set fam models.provider.local fam-cli\n")

    def test_of_exits_2_for_an_unset_surface_an_ambiguous_family_and_a_project_with_none(self):
        rc, out, err = self.of("obj", "--surface", "cloud")
        self.assertEqual((rc, out, err), (2, "", "qargi: project obj has no cloud provider: set one with qargi project set obj models.provider.cloud NAME\n"))
        rc, out, err = self.of("none", "--surface", "local")
        self.assertEqual((rc, out, err), (2, "", "qargi: project none has no provider: set one with qargi project set none models.provider NAME\n"))
        rc, out, err = self.of("amb", "--surface", "cloud")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("more than one runtime on the cloud surface (fam-hosted, fam-other)", err)
        self.assertEqual(self.of("absent", "--surface", "local")[0], 2)

    def test_of_without_a_surface_is_what_it_was_and_refuses_the_object_form(self):
        self.assertEqual(self.of("str")[:2], (0, "claude\n"))
        rc, out, err = self.of("obj")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("names a runtime per surface", err)

    def test_of_with_a_bad_surface_or_option_is_a_usage_error(self):
        self.assertEqual(self.of("str", "--surface", "moon")[0], 2)
        self.assertEqual(self.of("str", "--surface")[0], 2)
        self.assertEqual(self.run_cli("of")[0], 2)


class V2Cli(CliBase):
    """list, show, check and effective on schema 2 definitions, shipped (the copy's providers/) and in the pack library."""

    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp, "conf")
        self.state = os.path.join(self.tmp, "state")
        self.library = os.path.join(self.conf, "packs", "providers")
        os.makedirs(os.path.join(self.root, "catalogs"))
        os.makedirs(self.library)

    def run_cli(self, *args):
        env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=self.state)
        r = subprocess.run([sys.executable, "-I", os.path.join(self.copy, "provider.py")] + list(args), capture_output=True, text=True, env=env)
        return r.returncode, r.stdout, r.stderr

    def put_lib(self, name, d, files=None):
        os.makedirs(os.path.join(self.library, name), exist_ok=True)
        with open(os.path.join(self.library, name, "definition.json"), "w") as f:
            json.dump(d, f)
        for rel, mode in (files or {}).items():
            with open(os.path.join(self.library, name, rel), "w") as f:
                f.write("#!/bin/sh\n")
            os.chmod(os.path.join(self.library, name, rel), mode)

    def put_catalog(self, family):
        with open(os.path.join(self.root, "catalogs", family + ".json"), "w") as f:
            json.dump(catalog(family), f)

    def test_list_shows_every_definition_with_its_surfaces_and_marks_the_library(self):
        self.put("fakecli", runtime("fakecli"))
        self.put_lib("libcli", runtime("libcli", surface="cloud"))
        self.put("broken2", runtime("broken2", extra=1))
        self.put("lost", runtime("lost", models={"catalog": "gone", "use": "id"}))
        rc, out, _ = self.run_cli("list")
        rows = {ln.split()[0]: ln.split()[1:] for ln in out.strip().splitlines()}
        self.assertEqual((rc, list(rows)), (0, ["broken2", "claude", "fakecli", "libcli", "lost"]))
        self.assertEqual(rows["fakecli"], ["local", "clean"])
        self.assertEqual(rows["libcli"], ["cloud", "clean", "(library)"])
        self.assertEqual(rows["broken2"][-1], "failure")
        self.assertEqual(rows["lost"][:2], ["local", "1"])

    def test_list_says_when_a_name_is_defined_twice(self):
        self.put("dupe", runtime("dupe"))
        self.put_lib("dupe", runtime("dupe"))
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"dupe\s+-\s+1 failure \('dupe' is defined twice")

    def test_show_a_definition_prints_models_effort_and_capabilities(self):
        self.put_catalog("fam")
        self.put("fam-cli", runtime("fam-cli", family="fam", models={"catalog": "fam", "use": "alias"},
                                    capabilities={"skills": cell("yes", "2026-11-02", "loads from .fake")}))
        rc, out, _ = self.run_cli("show", "fam-cli")
        self.assertEqual(rc, 0)
        self.assertIn("fam-cli  (local, shipped; family fam)", out)
        self.assertIn("models: catalog fam (2026-11-02), passes the alias", out)
        self.assertRegex(out, r"fast\s+fam-small\s+alias small")
        self.assertRegex(out, r"xhigh\s+- \(no control\)")
        self.assertRegex(out, r"skills\s+yes\s+verified 2026-11-02\s+loads from \.fake")
        rc, out, _ = self.run_cli("show", "fam-cli", "--json")
        self.assertEqual(json.loads(out)["models"], {"catalog": "fam", "use": "alias"})

    def test_show_a_library_definition_says_whether_the_record_backs_a_claim(self):
        self.put_lib("libcli", runtime("libcli", capabilities={"skills": cell("yes", "2026-11-02"), "mcp": cell("no", None)}))
        out = self.run_cli("show", "libcli")[1]
        self.assertIn("libcli  (local, library)", out)
        self.assertIn("single model my-model for every tier", out)
        self.assertRegex(out, r"effort\s*\n\s+no control")
        self.assertRegex(out, r"skills\s+yes\s+no record, counts as no")
        os.makedirs(os.path.join(self.state, "providers", "libcli"))
        with open(os.path.join(self.state, "providers", "libcli", "verified.json"), "w") as f:
            json.dump({"skills": {"hash": P.definition_hash("libcli", root=self.root, library=self.library), "by": "attest"}}, f)
        self.assertRegex(self.run_cli("show", "libcli")[1], r"skills\s+yes\s+verified by attest")

    def test_check_of_a_clean_definition(self):
        self.put("fakecli", runtime("fakecli"))
        rc, out, _ = self.run_cli("check", "fakecli")
        self.assertEqual(rc, 0)
        self.assertIn("fakecli: 0 failures, 0 warnings", out)
        self.assertIn("adapter: none (what needs one is refused)", out)
        self.assertNotIn("note: schema 1", out)
        self.assertIn("the review role cannot be served on local", out)
        self.assertRegex(out, r"local: skills\s+no")
        self.assertRegex(out, r"layout: project_skills_dir\s+no \(the verb that needs it is refused with exit 3\)")
        self.assertNotIn("cloud", out)

    def test_check_fails_for_a_violation_a_missing_catalog_and_a_clash(self):
        self.put("bad", runtime("bad", extra=1))
        self.put("lost", runtime("lost", models={"catalog": "gone", "use": "id"}))
        self.put("dupe", runtime("dupe"))
        self.put_lib("dupe", runtime("dupe"))
        rc, out, _ = self.run_cli("check", "bad")
        self.assertEqual(rc, 1)
        self.assertIn("fail: extra: additional property is not allowed", out)
        rc, out, _ = self.run_cli("check", "lost")
        self.assertEqual(rc, 1)
        self.assertIn("fail: models.catalog: no catalog 'gone'", out)
        rc, _, err = self.run_cli("check", "dupe")
        self.assertEqual(rc, 2)
        self.assertIn("'dupe' is defined twice", err)

    def test_check_looks_for_the_adapter_in_the_definitions_own_directory(self):
        self.put("withad", runtime("withad", adapter="adapter"))
        rc, out, _ = self.run_cli("check", "withad")
        self.assertEqual(rc, 1)
        self.assertIn("fail: adapter: adapter does not exist", out)
        os.makedirs(os.path.join(self.root, "withad"))
        ad = os.path.join(self.root, "withad", "adapter")
        with open(ad, "w") as f:
            f.write("#!/bin/sh\n")
        self.assertIn("fail: adapter: adapter is not executable", self.run_cli("check", "withad")[1])
        os.chmod(ad, 0o755)
        rc, out, _ = self.run_cli("check", "withad")
        self.assertEqual(rc, 0)
        self.assertIn("adapter: adapter (exists, executable)", out)
        self.put_lib("libad", runtime("libad", adapter="adapter"), {"adapter": 0o755})
        self.assertIn("adapter: adapter (exists, executable)", self.run_cli("check", "libad")[1])

    def test_check_degrades_follow_the_record_for_a_library_definition(self):
        self.put_lib("libcli", runtime("libcli", capabilities={"skills": cell("yes", "2026-11-02"), "read_only_barrier": cell("yes", "2026-11-02")}))
        out = self.run_cli("check", "libcli")[1]
        self.assertRegex(out, r"local: skills\s+unverified \(counts as no\)")
        self.assertIn("the review role cannot be served on local", out)
        os.makedirs(os.path.join(self.state, "providers", "libcli"))
        h = P.definition_hash("libcli", root=self.root, library=self.library)
        with open(os.path.join(self.state, "providers", "libcli", "verified.json"), "w") as f:
            json.dump({c: {"hash": h, "by": "conformance"} for c in ("skills", "read_only_barrier")}, f)
        out = self.run_cli("check", "libcli")[1]
        self.assertNotRegex(out, r"local: skills")
        self.assertNotIn("cannot be served", out)

    def test_check_of_a_schema_1_descriptor_notes_that_schema_2_exists(self):
        rc, out, _ = self.run_cli("check", "claude")
        self.assertEqual(rc, 0)
        self.assertIn("note: schema 1 is the earlier format; qargi provider migrate claude --dry-run shows the schema 2 form", out)

    def test_effective_of_a_definition_and_of_the_other_surface(self):
        self.put("fakecli", runtime("fakecli", capabilities={"skills": cell()}))
        self.assertEqual(self.run_cli("effective", "fakecli", "local", "skills")[:2], (0, "yes\n"))
        self.assertEqual(self.run_cli("effective", "fakecli", "local", "mcp")[:2], (0, "no\n"))
        rc, _, err = self.run_cli("effective", "fakecli", "cloud", "skills")
        self.assertEqual(rc, 1)
        self.assertIn("the provider fakecli does not list the surface cloud", err)

    def test_the_other_verbs_work_on_a_definition_with_resources(self):
        res = {"skills": {"project_dir": ".fake/skills", "user_dir": "~/.fake/skills"}}
        self.put("fakecli", runtime("fakecli", resources=res, capabilities={"skills": cell()}, session={"launch": "fake {render}"}))
        self.assertEqual(self.run_cli("layout", "fakecli", "project_skills_dir")[:2], (0, ".fake/skills\n"))
        self.assertEqual(self.run_cli("require-skills", "fakecli")[0], 0)
        self.assertEqual(self.run_cli("launch", "fakecli", "/r")[:2], (0, "fake /r\n"))
        self.assertEqual(self.run_cli("skills-dirs")[1], ".claude/skills\n.fake/skills\n")
        rc, _, err = self.run_cli("layout", "fakecli", "project_agents_dir", "--would", "write")
        self.assertEqual((rc, err), (3, "qargi: provider fakecli has no project agents directory: write\n"))
        self.assertEqual(self.run_cli("require-barrier", "fakecli", "local")[0], 2)


class Migrate(V2Tree):
    """migrate(): a schema 1 descriptor as schema 2 documents (a pure function); `provider migrate NAME --dry-run` prints them."""

    def one_surface(self, surface="local"):
        d = descriptor()
        d["surfaces"] = [surface]
        for row in d["capabilities"].values():
            for other in [x for x in P.SURFACES if x != surface]:
                row.pop(other, None)
        d["adapter"] = None
        if surface != "local":
            d.pop("layout")
        return d

    def test_a_single_surface_descriptor_becomes_one_runtime_with_inline_models(self):
        docs, notes = P.migrate(self.one_surface(), today="2026-11-02")
        self.assertEqual(len(docs), 1)
        d = docs[0]
        self.assertEqual((d["schema"], d["kind"], d["provider"], d["family"], d["surface"]), (2, "provider", "claude", None, "local"))
        self.assertEqual(d["models"], {"pattern": CLAUDE["model_pattern"], "tiers": CLAUDE["tier_detail"], "effort": CLAUDE["effort"]})
        self.assertEqual(d["capabilities"]["skills"], CLAUDE["capabilities"]["skills"]["local"])
        self.assertEqual(d["resources"]["skills"]["project_dir"], ".claude/skills")
        self.assertEqual(d["agents"], {"reserved_names": CLAUDE["local"]["reserved_names"]})
        self.assertEqual(d["session"], {"launch": CLAUDE["layout"]["session_launch"], "render_target": "claude-code"})
        self.assertIn("migrated from schema 1", d["description"])
        self.assertEqual(fails(d, "claude"), [])
        self.assertEqual(notes, [])

    def test_a_cloud_only_descriptor_has_no_local_resources(self):
        docs, _ = P.migrate(self.one_surface("cloud"))
        self.assertEqual((docs[0]["surface"], docs[0]["resources"], docs[0]["agents"]), ("cloud", {}, None))
        self.assertEqual(fails(docs[0], "claude"), [])

    def test_a_descriptor_for_two_surfaces_is_split_into_a_catalog_and_two_runtimes(self):
        docs, notes = P.migrate(CLAUDE, today="2026-11-02")
        cat, loc, cld = docs
        self.assertEqual((cat["kind"], cat["family"], cat["version"]), ("catalog", "claude", "2026-11-02"))
        self.assertEqual((cat["pattern"], cat["tiers"], cat["effort"]), (CLAUDE["model_pattern"], CLAUDE["tier_detail"], CLAUDE["effort"]))
        self.assertEqual((loc["provider"], loc["surface"], loc["family"], loc["models"]), ("claude-local", "local", "claude", {"catalog": "claude", "use": "alias"}))
        self.assertEqual((cld["provider"], cld["surface"], cld["family"], cld["models"]), ("claude-cloud", "cloud", "claude", {"catalog": "claude", "use": "id"}))
        self.assertEqual(cld["capabilities"]["skills"], CLAUDE["capabilities"]["skills"]["cloud"])
        self.assertEqual((cld["resources"], cld["agents"]), ({}, None))
        self.assertEqual((loc["adapter"], cld["adapter"]), ("adapter", "adapter"))
        self.assertTrue(any("adapter serves both surfaces" in n for n in notes))
        for doc, name in zip(docs, ("claude", "claude-local", "claude-cloud")):
            self.assertEqual(fails(doc, name), [], name)

    def test_names_and_the_catalog_version(self):
        d = descriptor()
        d["tier_detail"]["deep"]["verified_on"] = "2026-10-30"
        d["tier_detail"]["fast"]["verified_on"] = "2026-10-12"
        docs, _ = P.migrate(d, names={"local": "claude-code", "cloud": "claude-platform"}, today="2026-11-02")
        self.assertEqual([x.get("provider") or x["family"] for x in docs], ["claude", "claude-code", "claude-platform"])
        self.assertEqual(docs[0]["version"], "2026-10-30")                    # the latest date a tier was verified, else the day of the conversion
        with self.assertRaises(P.ProviderError):
            P.migrate(d, names={"local": "Bad_Name"})

    def test_the_migrated_definitions_mean_what_the_descriptor_meant(self):
        docs, _ = P.migrate(CLAUDE, today="2026-11-02")
        cat, loc, cld = docs
        self.put_catalog(cat["family"], cat)
        self.put("claude-local", loc)
        self.put("claude-cloud", cld)
        self.put("claude", dict(CLAUDE, provider="claude"))
        kw = self.kw(state=self.state)
        for surface, new in (("local", "claude-local"), ("cloud", "claude-cloud")):
            for c in P.capabilities():
                self.assertEqual(P.effective(new, surface, c, **kw), P.effective("claude", surface, c, **kw), (surface, c))
            m = P.models_of(new, **self.kw())
            self.assertEqual({t: m["tiers"][t]["model"] for t in P.TIERS}, CLAUDE["tiers"])
            self.assertEqual(m["effort"], CLAUDE["effort"])
        lay = P.layout("claude-local", home="/h", **self.kw())
        self.assertEqual(lay, P.layout("claude", home="/h", **self.kw()))
        self.assertEqual(P.resolve_runtime("claude", "local", **self.kw()), "claude")

    def test_an_adapter_outside_the_descriptors_directory_is_dropped_with_a_note(self):
        d = self.one_surface()
        d["adapter"] = "lib/providers/other/adapter"
        docs, notes = P.migrate(d)
        self.assertIsNone(docs[0]["adapter"])
        self.assertTrue(any("lib/providers/other/adapter" in n and "outside" in n for n in notes))

    def test_a_descriptor_that_breaks_schema_1_or_is_schema_2_is_refused(self):
        d = descriptor()
        d["extra"] = 1
        with self.assertRaises(P.ProviderError) as cm:
            P.migrate(d)
        self.assertIn("breaks schema 1", str(cm.exception))
        with self.assertRaises(P.ProviderError) as cm:
            P.migrate(runtime())
        self.assertIn("is already schema 2", str(cm.exception))

    def test_migrate_does_not_change_its_input(self):
        d = descriptor()
        P.migrate(d)
        self.assertEqual(d, CLAUDE)


class MigrateCli(CliBase):
    def listing(self):
        return sorted(os.path.join(dp, f) for dp, _, fs in os.walk(self.copy) for f in fs if "__pycache__" not in dp)

    def test_dry_run_prints_the_documents_and_writes_nothing(self):
        before = self.listing()
        rc, out, err = self.run_cli("migrate", "claude", "--dry-run")
        self.assertEqual(rc, 0)
        docs = json.loads(out)
        self.assertEqual([(d["kind"], d.get("provider") or d["family"]) for d in docs], [("catalog", "claude"), ("provider", "claude-local"), ("provider", "claude-cloud")])
        self.assertIn("qargi: note: the adapter serves both surfaces", err)
        self.assertEqual(self.listing(), before)

    def test_as_names_the_two_runtimes(self):
        rc, out, _ = self.run_cli("migrate", "claude", "--dry-run", "--as", "local=claude-code,cloud=claude-platform")
        self.assertEqual(rc, 0)
        self.assertEqual([d.get("provider") for d in json.loads(out)], [None, "claude-code", "claude-platform"])
        self.assertEqual(self.run_cli("migrate", "claude", "--dry-run", "--as", "local=x")[0], 2)

    def test_one_document_is_printed_as_an_object(self):
        d = descriptor()
        d["provider"] = "solo"
        d["surfaces"] = ["cloud"]
        for row in d["capabilities"].values():
            row.pop("local", None)
        d.pop("layout")
        d["adapter"] = None
        self.put("solo", d)
        rc, out, _ = self.run_cli("migrate", "solo", "--dry-run")
        self.assertEqual(rc, 0)
        self.assertEqual((json.loads(out)["provider"], json.loads(out)["surface"]), ("solo", "cloud"))

    def test_without_dry_run_the_write_is_not_built_and_changes_nothing(self):
        before = self.listing()
        rc, out, err = self.run_cli("migrate", "claude")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("migrate writes through a plan and your approval, which is not built yet; use --dry-run", err)
        self.assertEqual(self.listing(), before)

    def test_unknown_and_schema_2_and_usage(self):
        self.assertEqual(self.run_cli("migrate", "nope", "--dry-run")[0], 1)
        self.put("two", runtime("two"))
        rc, _, err = self.run_cli("migrate", "two", "--dry-run")
        self.assertEqual(rc, 1)
        self.assertIn("provider 'two' is already schema 2", err)
        self.assertEqual(self.run_cli("migrate")[0], 2)
        self.assertEqual(self.run_cli("migrate", "claude", "extra", "--dry-run")[0], 2)


if __name__ == "__main__":
    unittest.main()
