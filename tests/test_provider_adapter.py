#!/usr/bin/env python3
"""The local adapter of the claude provider (lib/providers/claude/adapter) and the code that reaches it.
Hermetic: every changed descriptor lives in a copy of the tool tree in a temporary directory, never in the checkout.
Run: python3 tests/test_provider_adapter.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.realpath(os.path.join(HERE, ".."))
ADAPTER = os.path.join(ROOT, "lib", "providers", "claude", "adapter")
TEMPLATE = os.path.join(ROOT, "agents", "member.md")
TOOL = ("bin", "lib", "agents", "roles", "provision", "methodologies", "packs", "catalog", "canon", "skills", "VERSION")

with open(os.path.join(ROOT, "lib", "providers", "claude.json")) as _f:
    CLAUDE = json.load(_f)


def run(adapter, verb, req, env=None, raw=None):
    """(exit code, parsed stdout) of one adapter call; raw replaces the JSON request."""
    r = subprocess.run([adapter, verb] if verb is not None else [adapter], input=raw if raw is not None else json.dumps(req),
                       capture_output=True, text=True, env=env)
    lines = r.stdout.strip().splitlines()
    assert len(lines) == 1, "the adapter prints ONE JSON object, got %r (stderr %r)" % (r.stdout, r.stderr)
    return r.returncode, json.loads(lines[0])


def sed_render(name, abilities, model, effort, cls):
    """What lib/agent.sh rendered with sed before the adapter did: the golden text."""
    ga = " --class read-only" if cls == "read-only" else ""
    el = "/^{{EFFORT_LINE}}$/d" if not effort else "s/^{{EFFORT_LINE}}$/effort: %s/" % effort
    ab = ",".join(abilities).replace(",", ", ")
    out = subprocess.run(["sed", "-e", el, "-e", "s/{{GUARD_ARGS}}/%s/g" % ga, "-e", "s/{{NAME}}/%s/g" % name, "-e", "s/{{ABILITIES}}/%s/g" % ab,
                          "-e", "s/{{MODEL}}/%s/g" % model, TEMPLATE], capture_output=True, text=True, check=True)
    return out.stdout


class Tree(unittest.TestCase):
    """A copy of the tool tree in a temporary directory, so a descriptor can change without touching the checkout."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="adapter.")
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.tool = os.path.join(self.tmp, "tool")
        os.makedirs(self.tool)
        for n in TOOL:
            src = os.path.join(ROOT, n)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(self.tool, n), symlinks=True, ignore=shutil.ignore_patterns("__pycache__"))
            else:
                shutil.copy2(src, self.tool)
        self.adapter = os.path.join(self.tool, "lib", "providers", "claude", "adapter")

    def descriptor(self, mutate, name="claude"):
        d = json.loads(json.dumps(CLAUDE))
        mutate(d)
        with open(os.path.join(self.tool, "lib", "providers", name + ".json"), "w") as f:
            json.dump(d, f)


class Resolve(Tree):
    def test_every_tier_on_every_surface(self):
        for surface in ("local", "cloud"):
            for tier, row in CLAUDE["tier_detail"].items():
                with self.subTest(surface=surface, tier=tier):
                    rc, out = run(ADAPTER, "resolve", {"surface": surface, "tier": tier, "effort": "high", "profile": "build"})
                    self.assertEqual(rc, 0)
                    self.assertEqual(out, {"model": row["model"], "alias": row["alias"], "effort_native": "high", "notes": []})

    def test_the_effort_is_the_providers_own_value(self):
        self.descriptor(lambda d: d["effort"].update(xhigh="extra"))
        rc, out = run(self.adapter, "resolve", {"surface": "local", "tier": "deep", "effort": "xhigh"})
        self.assertEqual((rc, out["effort_native"], out["notes"]), (0, "extra", []))

    def test_an_effort_the_provider_has_no_control_for_is_null_with_a_note(self):
        self.descriptor(lambda d: d["effort"].update(max=None))
        rc, out = run(self.adapter, "resolve", {"surface": "local", "tier": "deep", "effort": "max", "profile": "p"})
        self.assertEqual(rc, 0)
        self.assertIsNone(out["effort_native"])
        self.assertEqual(len(out["notes"]), 1)
        self.assertIn("no effort control", out["notes"][0])
        self.assertIn("max", out["notes"][0])
        self.assertEqual(out["model"], "claude-opus-5-5")

    def test_no_effort_asked_is_null_without_a_note(self):
        for req in ({"surface": "local", "tier": "fast"}, {"surface": "local", "tier": "fast", "effort": None}, {"surface": "local", "tier": "fast", "effort": ""}):
            rc, out = run(ADAPTER, "resolve", req)
            self.assertEqual((rc, out["effort_native"], out["notes"]), (0, None, []))

    def test_a_tier_with_no_alias_says_so(self):
        def mutate(d):
            d["tier_detail"]["fast"]["alias"] = None
            d["aliases"]["fast"] = None
        self.descriptor(mutate)
        rc, out = run(self.adapter, "resolve", {"surface": "local", "tier": "fast"})
        self.assertEqual(rc, 0)
        self.assertIsNone(out["alias"])
        self.assertTrue(any("no alias" in n for n in out["notes"]))

    def test_an_unknown_tier_is_a_bad_request(self):
        rc, out = run(ADAPTER, "resolve", {"surface": "local", "tier": "ultra", "effort": "high"})
        self.assertEqual(rc, 1)
        self.assertIn("tier", out["error"])

    def test_a_missing_tier_surface_or_a_bad_effort_is_a_bad_request(self):
        for req in ({"surface": "local"}, {"tier": "fast"}, {"surface": "moon", "tier": "fast"}, {"surface": "local", "tier": "fast", "effort": "turbo"},
                    {"surface": "local", "tier": 3}, {"surface": 1, "tier": "fast"}, {"surface": "local", "tier": "fast", "profile": 7}):
            with self.subTest(req=req):
                self.assertEqual(run(ADAPTER, "resolve", req)[0], 1)

    def test_a_surface_the_provider_does_not_list_is_unsupported(self):
        def mutate(d):
            d["surfaces"] = ["local"]
            for cap in d["capabilities"].values():
                cap.pop("cloud", None)
        self.descriptor(mutate)
        rc, out = run(self.adapter, "resolve", {"surface": "cloud", "tier": "fast"})
        self.assertEqual(rc, 3)
        self.assertIn("cloud", out["error"])
        self.assertEqual(run(self.adapter, "resolve", {"surface": "local", "tier": "fast"})[0], 0)

    def test_a_descriptor_that_breaks_its_schema_is_a_bad_request(self):
        self.descriptor(lambda d: d.update(extra=1))
        self.assertEqual(run(self.adapter, "resolve", {"surface": "local", "tier": "fast"})[0], 1)


class Protocol(Tree):
    def test_not_built_verbs_are_unsupported_for_local(self):
        for verb in ("provision", "start-session", "status", "collect", "stop", "cost"):
            with self.subTest(verb=verb):
                rc, out = run(ADAPTER, verb, {})
                self.assertEqual((rc, out), (3, {"error": "not implemented for local"}))

    def test_an_unknown_verb_or_none_is_a_bad_request(self):
        self.assertEqual(run(ADAPTER, "frobnicate", {})[0], 1)
        self.assertEqual(run(ADAPTER, None, {})[0], 1)

    def test_a_request_that_is_not_a_json_object_is_a_bad_request(self):
        for verb in ("resolve", "dispatch-local", "barrier-check"):
            for raw in ("not json", "[]", "3", "", '"x"'):
                with self.subTest(verb=verb, raw=raw):
                    self.assertEqual(run(ADAPTER, verb, None, raw=raw)[0], 1)

    def test_the_adapter_is_executable_and_runs_isolated_from_any_directory(self):
        self.assertTrue(os.access(ADAPTER, os.X_OK))
        env = dict(os.environ, PYTHONPATH=self.tmp)                      # a planted module is not imported
        with open(os.path.join(self.tmp, "json.py"), "w") as f:
            f.write("raise SystemExit(99)\n")
        r = subprocess.run([self.adapter, "resolve"], input='{"surface":"local","tier":"fast"}', capture_output=True, text=True, env=env, cwd=self.tmp)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["model"], "claude-haiku-5-5")


class Dispatch(Tree):
    def test_the_definition_is_what_sed_rendered_for_a_worker(self):
        req = {"member": "forge", "abilities": ["build", "write", "test"], "class": "write", "model": "claude-sonnet-5-5", "effort": "high"}
        rc, out = run(ADAPTER, "dispatch-local", req)
        self.assertEqual(rc, 0)
        self.assertEqual(out["definition"]["text"], sed_render("forge", ["build", "write", "test"], "claude-sonnet-5-5", "high", "write"))
        self.assertNotIn("--class", out["definition"]["text"])
        self.assertNotIn("{{", out["definition"]["text"])

    def test_the_definition_is_what_sed_rendered_for_a_reviewer(self):
        req = {"member": "judge", "abilities": ["review"], "class": "read-only", "model": "haiku", "effort": "low"}
        rc, out = run(ADAPTER, "dispatch-local", req)
        self.assertEqual(rc, 0)
        self.assertEqual(out["definition"]["text"], sed_render("judge", ["review"], "haiku", "low", "read-only"))
        self.assertIn('command: "qargi __guard --class read-only"', out["definition"]["text"])

    def test_no_effort_drops_the_effort_line_as_sed_did(self):
        for effort in (None, ""):
            req = {"member": "judge", "abilities": ["review", "audit"], "class": "read-only", "model": "opus", "effort": effort}
            rc, out = run(ADAPTER, "dispatch-local", req)
            self.assertEqual(rc, 0)
            self.assertEqual(out["definition"]["text"], sed_render("judge", ["review", "audit"], "opus", "", "read-only"))
            self.assertNotIn("effort:", out["definition"]["text"])

    def test_the_path_is_in_the_agents_directory(self):
        env = dict(os.environ, HOME="/h/user")
        req = {"member": "forge", "abilities": ["build"], "class": "write", "model": "sonnet", "effort": "high"}
        self.assertEqual(run(ADAPTER, "dispatch-local", req, env=env)[1]["definition"]["path"], "/h/user/.claude/agents/forge.md")
        req["project_dir"] = "/work/repo"
        self.assertEqual(run(ADAPTER, "dispatch-local", req, env=env)[1]["definition"]["path"], "/work/repo/.claude/agents/forge.md")

    def test_spawn_names_the_agent_type_the_model_alias_and_the_native_effort(self):
        base = {"member": "forge", "abilities": ["build"], "class": "write", "effort": "xhigh"}
        for model, alias in (("sonnet", "sonnet"), ("claude-opus-5-5", "opus"), ("claude-odd-9", None)):
            rc, out = run(ADAPTER, "dispatch-local", dict(base, model=model))
            self.assertEqual((rc, out["spawn"]), (0, {"agent_type": "forge", "model_alias": alias, "effort": "xhigh"}), model)
        self.assertIsNone(run(ADAPTER, "dispatch-local", dict(base, model="sonnet", effort=None))[1]["spawn"]["effort"])

    def test_a_bad_request_is_exit_1(self):
        ok = {"member": "forge", "abilities": ["build"], "class": "write", "model": "sonnet", "effort": "high"}
        for label, patch in (("name", {"member": "Forge"}), ("no name", {"member": None}), ("abilities", {"abilities": []}), ("ability", {"abilities": ["a b"]}),
                             ("class", {"class": "root"}), ("model", {"model": "a/b"}), ("effort", {"effort": "turbo"}), ("project_dir", {"project_dir": 3})):
            with self.subTest(label):
                self.assertEqual(run(ADAPTER, "dispatch-local", dict(ok, **patch))[0], 1)


class Barrier(unittest.TestCase):
    """A run directory as `qargi local prepare` leaves it, the calls of tests/test_guard.py's Review, through the adapter."""

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="barrier.")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.run = os.path.join(self.t, "qargi.x")
        for d in ("clone/src", "out"):
            os.makedirs(os.path.join(self.run, d))
        open(os.path.join(self.run, "refs.before"), "w").close()
        with open(os.path.join(self.run, "ability"), "w") as f:
            f.write("review\n")
        self.clone, self.out = os.path.join(self.run, "clone"), os.path.join(self.run, "out")

    def check(self, cls, tool, cwd=None, surface="local", **call):
        return run(ADAPTER, "barrier-check", {"surface": surface, "class": cls, "tool_call": dict({"tool": tool, "cwd": cwd or self.clone}, **call)})

    def test_a_read_only_member_may_not_edit_outside_the_out_directory(self):
        rc, out = self.check("read-only", "Edit", path=os.path.join(self.clone, "src", "a.go"))
        self.assertEqual((rc, out["decision"]), (0, "deny"))
        self.assertIn("review", out["reason"])
        self.assertEqual(self.check("read-only", "Write", path=os.path.join(self.t, "elsewhere.txt"))[1]["decision"], "deny")

    def test_a_read_only_member_may_not_redirect_into_the_clone_or_change_the_history(self):
        for command in ("echo x > src/a.go", "printf y >> %s/README" % self.clone, "sed -i s/a/b/ src/a.go", "git commit -am fix", "git checkout -- ."):
            with self.subTest(command):
                rc, out = self.check("read-only", "Bash", command=command)
                self.assertEqual((rc, out["decision"]), (0, "deny"))
                self.assertTrue(out["reason"])

    def test_nobody_may_push(self):
        for cls in ("read-only", "write"):
            for command in ("git push", "git push origin main", "gh pr list", "ssh host ls"):
                with self.subTest(cls=cls, command=command):
                    out = self.check(cls, "Bash", command=command)[1]
                    self.assertEqual(out["decision"], "deny")
                    self.assertIn("never push", out["reason"])

    def test_a_read_only_member_may_read_and_write_its_report(self):
        for tool, call in (("Write", {"path": os.path.join(self.out, "report.md")}), ("Edit", {"path": os.path.join(self.out, "manifest.json")}),
                           ("Bash", {"command": "cat src/a.go"}), ("Bash", {"command": "git status"}), ("Bash", {"command": "git log --oneline && git diff HEAD~1"}),
                           ("Bash", {"command": "make test > %s/test.log 2>&1" % self.out}), ("Bash", {"command": "grep -rn x src 2>/dev/null"})):
            with self.subTest(tool=tool, call=call):
                rc, out = self.check("read-only", tool, **call)
                self.assertEqual((rc, out), (0, {"decision": "allow", "reason": ""}))

    def test_a_write_member_in_a_build_run_may_change_the_clone(self):
        with open(os.path.join(self.run, "ability"), "w") as f:
            f.write("build\n")
        for tool, call in (("Edit", {"path": os.path.join(self.clone, "src", "a.go")}), ("Bash", {"command": "echo x > src/a.go"}), ("Bash", {"command": "git commit -am fix"})):
            self.assertEqual(self.check("write", tool, **call)[1]["decision"], "allow", call)
        self.assertEqual(self.check("read-only", "Edit", path=os.path.join(self.clone, "src", "a.go"))[1]["decision"], "deny")

    def test_the_cloud_surface_has_no_barrier(self):
        rc, out = self.check("read-only", "Bash", surface="cloud", command="ls")
        self.assertEqual(rc, 3)
        self.assertIn("error", out)

    def test_a_bad_request_is_exit_1(self):
        good = {"surface": "local", "class": "write", "tool_call": {"tool": "Bash", "command": "ls", "cwd": self.t}}
        for label, patch in (("class", {"class": "root"}), ("surface", {"surface": "moon"}), ("no call", {"tool_call": "ls"}),
                             ("no tool", {"tool_call": {"command": "ls"}}), ("neither command nor path", {"tool_call": {"tool": "Bash", "cwd": self.t}}),
                             ("command type", {"tool_call": {"tool": "Bash", "command": 3}})):
            with self.subTest(label):
                self.assertEqual(run(ADAPTER, "barrier-check", dict(good, **patch))[0], 1)
        self.assertEqual(run(ADAPTER, "barrier-check", good)[0], 0)


class AgentAdd(Tree):
    """qargi agent add reaches the definition through the adapter the active provider's descriptor names."""

    def setUp(self):
        super().setUp()
        self.env = dict(os.environ, HOME=os.path.join(self.tmp, "home"), QARGI_CONF=os.path.join(self.tmp, "c"), QARGI_STATE=os.path.join(self.tmp, "s"))
        os.makedirs(os.path.join(self.env["HOME"]))
        os.makedirs(os.path.join(self.env["QARGI_CONF"], "projects"))
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)

    def project(self, provider=None):
        p = {"schema": 1, "project": "alpha", "repo": {"url": "https://github.com/example/alpha", "path": self.repo, "long_lived": ["main"]},
             "roles": {"build": {"base": "main", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high"}}, "memory": {}, "budget_cents": 500}
        if provider:
            p["models"] = {"provider": provider}
        with open(os.path.join(self.env["QARGI_CONF"], "projects", "alpha.json"), "w") as f:
            json.dump(p, f)

    def qargi(self, *args):
        r = subprocess.run([os.path.join(self.tool, "bin", "qargi")] + list(args), capture_output=True, text=True, env=self.env)
        return r.returncode, r.stdout + r.stderr

    def test_a_provider_without_a_local_adapter_cannot_add_a_member(self):
        self.descriptor(lambda d: d.update(provider="plain", adapter=None), name="plain")
        self.project("plain")
        rc, out = self.qargi("agent", "add", "forge", "--abilities", "build", "--project", "alpha")
        self.assertNotEqual(rc, 0)
        self.assertIn("provider 'plain' has no local adapter", out)
        self.assertFalse(os.path.exists(os.path.join(self.repo, ".claude", "agents", "forge.md")))
        conf = os.path.join(self.env["QARGI_CONF"], "agents.json")
        if os.path.exists(conf):
            with open(conf) as f:
                self.assertNotIn("forge", json.load(f))

    def test_the_definition_the_adapter_returns_is_the_file_written(self):
        self.project()
        rc, out = self.qargi("agent", "add", "forge", "--abilities", "build,test", "--project", "alpha")
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.repo, ".claude", "agents", "forge.md")) as f:
            self.assertEqual(f.read(), sed_render("forge", ["build", "test"], "claude-sonnet-5-5", "high", "write"))
        rc, out = self.qargi("agent", "add", "judge", "--abilities", "review")
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.env["HOME"], ".claude", "agents", "judge.md")) as f:
            self.assertEqual(f.read(), sed_render("judge", ["review"], "claude-opus-5-5", "high", "read-only"))

    def test_refresh_without_a_recorded_model_uses_the_balanced_alias_of_the_provider(self):
        self.assertEqual(self.qargi("agent", "add", "forge", "--abilities", "build")[0], 0)
        conf = os.path.join(self.env["QARGI_CONF"], "agents.json")
        with open(conf) as f:
            m = json.load(f)
        m["forge"]["model"] = None
        with open(conf, "w") as f:
            json.dump(m, f)
        rc, out = self.qargi("agent", "refresh", "forge")
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.env["HOME"], ".claude", "agents", "forge.md")) as f:
            self.assertIn("\nmodel: sonnet\n", f.read())

    def test_the_reserved_names_come_from_the_descriptor(self):
        self.assertEqual(self.qargi("agent", "add", "plan")[0], 1)
        self.descriptor(lambda d: d["local"].update(reserved_names=["plan", "mine"]))
        rc, out = self.qargi("agent", "add", "mine")
        self.assertNotEqual(rc, 0)
        self.assertIn("built-in", out)
        rc, out = self.qargi("agent", "add", "explore", "--abilities", "build")
        self.assertEqual(rc, 0, out)

    def test_a_pinned_model_is_one_that_matches_the_model_pattern(self):
        self.assertEqual(self.qargi("agent", "add", "forge", "--abilities", "build", "--model", "claude-opus-5-5")[0], 0)
        self.assertEqual(self.qargi("agent", "add", "judge", "--abilities", "review", "--model", "opus")[0], 0)
        rc, out = self.qargi("agent", "models", "--json")
        self.assertEqual(rc, 0, out)
        pinned = {m["name"]: m["pinned"] for m in json.loads(out)["members"]}
        self.assertEqual(pinned, {"forge": True, "judge": False})
        self.descriptor(lambda d: d.update(model_pattern="^zzz"))
        pinned = {m["name"]: m["pinned"] for m in json.loads(self.qargi("agent", "models", "--json")[1])["members"]}
        self.assertEqual(pinned, {"forge": False, "judge": False})


class Derived(Tree):
    """What was hardcoded for claude now follows the descriptor of the project's provider (models.provider, default claude)."""

    def setUp(self):
        super().setUp()
        self.env = dict(os.environ, HOME=os.path.join(self.tmp, "home"), QARGI_CONF=os.path.join(self.tmp, "c"), QARGI_STATE=os.path.join(self.tmp, "s"))
        os.makedirs(os.path.join(self.env["HOME"]))
        os.makedirs(os.path.join(self.env["QARGI_CONF"], "projects"))
        os.makedirs(os.path.join(self.tmp, "bin"))
        with open(os.path.join(self.tmp, "bin", "ant"), "w") as f:         # a fake ant: logged in, empty lists
            f.write('#!/usr/bin/env bash\ncase "$1" in auth) exit 0;; *) echo "{}";; esac\n')
        os.chmod(os.path.join(self.tmp, "bin", "ant"), 0o755)
        self.env["PATH"] = os.path.join(self.tmp, "bin") + os.pathsep + self.env["PATH"]

    def other(self):
        """A provider whose ids look nothing like the claude ones."""
        def mutate(d):
            d["provider"] = "zeta"
            d["adapter"] = None
            d["model_pattern"] = "^zeta-[0-9]+$"
            d["aliases"] = {"fast": "z1", "balanced": "z2", "deep": "z3", "frontier": "z4"}
            for i, t in enumerate(("fast", "balanced", "deep", "frontier"), 1):
                d["tier_detail"][t].update(model="zeta-%d" % i, alias="z%d" % i)
                d["tiers"][t] = "zeta-%d" % i
        self.descriptor(mutate, name="zeta")

    def qargi(self, *args):
        r = subprocess.run([os.path.join(self.tool, "bin", "qargi")] + list(args), capture_output=True, text=True, env=self.env)
        return r.returncode, r.stdout + r.stderr

    def answers(self, provider=None):
        rc, out = self.qargi("project", "template", "demo")
        self.assertEqual(rc, 0, out)
        a = json.loads(out)
        a["repo"]["url"] = "https://github.com/example/demo"
        if provider:
            a["models"] = {"provider": provider}
        path = os.path.join(self.tmp, "answers.json")
        with open(path, "w") as f:
            json.dump(a, f)
        return a, path

    def validate(self, a):
        path = os.path.join(self.tmp, "check.json")
        with open(path, "w") as f:
            json.dump(a, f)
        return self.qargi("project", "validate", path)

    def test_validate_names_the_balanced_model_of_the_default_provider_in_its_messages(self):
        a, _ = self.answers()
        self.assertEqual(self.validate(a)[0], 0)
        a["roles"]["build"]["model"] = "gpt"
        rc, out = self.validate(a)
        self.assertEqual(rc, 1)
        self.assertIn("roles.build.model: a model id like claude-sonnet-5-5", out)
        a["roles"]["build"]["model"] = "claude-sonnet-5-5"
        a["profiles"] = {"tiny": {"base": "worker", "model": "gpt"}}
        self.assertIn("profiles.tiny.model: haiku, sonnet, opus, fable or a model id like claude-sonnet-5-5", self.validate(a)[1])
        a["profiles"] = {"tiny": {"base": "worker", "model": "fable"}}
        self.assertEqual(self.validate(a)[0], 0)
        a["profiles"] = {"tiny": {"base": "worker", "tier": "ultra"}}
        self.assertIn("profiles.tiny.tier: one of fast, balanced, deep, frontier", self.validate(a)[1])
        a.pop("profiles")
        a["teams"] = {"duo": {"members": ["build", "write"]}}
        self.assertIn("lead.model: a model id like claude-opus-5-5", self.validate(a)[1])

    def test_validate_follows_the_model_pattern_and_aliases_of_the_projects_provider(self):
        self.other()
        a, _ = self.answers("zeta")
        rc, out = self.validate(a)
        self.assertEqual(rc, 1)
        self.assertIn("roles.build.model: a model id like zeta-2", out)
        for r in a["roles"].values():
            r["model"] = "zeta-7"
        self.assertEqual(self.validate(a)[0], 0, self.validate(a)[1])
        a["profiles"] = {"tiny": {"base": "worker", "model": "z3"}, "big": {"base": "worker", "model": "zeta-1"}}
        self.assertEqual(self.validate(a)[0], 0, self.validate(a)[1])
        a["profiles"] = {"tiny": {"base": "worker", "model": "sonnet"}}
        self.assertIn("profiles.tiny.model: z1, z2, z3, z4 or a model id like zeta-2", self.validate(a)[1])

    def test_an_unknown_provider_in_the_answers_validates_as_the_default_one(self):
        a, _ = self.answers("nope")
        self.assertEqual(self.validate(a)[0], 0)

    def test_attach_proposes_the_balanced_model_of_the_descriptor(self):
        repo = os.path.join(self.tmp, "widget")
        subprocess.run(["git", "init", "-q", repo], check=True)
        def detect():
            r = subprocess.run([sys.executable, "-I", os.path.join(self.tool, "lib", "attach.py"), "detect", repo, "--name", "widget", "--methodology", "gitflow"],
                               capture_output=True, text=True, env=self.env)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        models = {r["model"] for r in detect()["answers"]["roles"].values()}
        self.assertEqual(models, {"claude-sonnet-5-5"})
        def mutate(d):
            d["tier_detail"]["balanced"]["model"] = "claude-sonnet-9-9"
            d["tiers"]["balanced"] = "claude-sonnet-9-9"
        self.descriptor(mutate)
        self.assertEqual({r["model"] for r in detect()["answers"]["roles"].values()}, {"claude-sonnet-9-9"})

    def test_provision_defaults_to_the_balanced_model_of_the_projects_provider(self):
        def agent_model(name):
            rc, out = self.qargi("provision", "plan", name)
            self.assertEqual(rc, 0, out)
            with open(os.path.join(self.env["QARGI_STATE"], "provision", name, "agents", name, "agent.md")) as f:
                return re.search(r"^  id: .*$", f.read(), re.M).group(0)
        self.assertIn("claude-sonnet-5-5", agent_model("zed-build"))
        def mutate(d):
            d["tier_detail"]["balanced"]["model"] = "claude-sonnet-9-9"
            d["tiers"]["balanced"] = "claude-sonnet-9-9"
        self.descriptor(mutate)
        self.assertIn("claude-sonnet-9-9", agent_model("zed-build"))

    def test_provision_names_a_project_provider_that_has_no_descriptor(self):
        a, _ = self.answers("nope")
        a["project"] = "zed"
        for r in a["roles"].values():
            r["model"] = ""
        with open(os.path.join(self.env["QARGI_CONF"], "projects", "zed.json"), "w") as f:
            json.dump(a, f)
        rc, out = self.qargi("provision", "plan", "--project", "zed", "--role", "build")
        self.assertEqual(rc, 1)
        self.assertIn("models.provider 'nope' has no descriptor", out)


class Hardcodes(unittest.TestCase):
    def test_no_model_id_outside_the_descriptors_and_the_command_table(self):
        pat = re.compile(r"claude-(haiku|sonnet|opus|fable)")
        found = []
        for top in ("lib", "bin"):
            for dp, dn, fn in os.walk(os.path.join(ROOT, top)):
                dn[:] = [d for d in dn if d != "__pycache__"]
                for f in fn:
                    p = os.path.join(dp, f)
                    rel = os.path.relpath(p, ROOT)
                    if rel.startswith("lib/providers/") or rel == "lib/commands.py":
                        continue
                    with open(p, errors="replace") as fh:
                        found += ["%s:%d" % (rel, i) for i, ln in enumerate(fh, 1) if pat.search(ln)]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
