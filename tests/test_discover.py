#!/usr/bin/env python3
"""qargi discover: search, recommend, show and install; offline (fake curl, a test catalog, scripted terminal answers)."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, subprocess, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")

FAKE_CURL = r'''#!/usr/bin/env python3
import os, sys
url = sys.argv[-1]
if os.path.exists(os.path.join(os.environ["FAKE"], "offline")):
    sys.exit(7)
if "registry.modelcontextprotocol.io" in url:
    print('{"servers":[{"server":{"name":"io.example/weather","description":"Weather forecasts","repository":{"url":"https://github.com/example/weather"},"remotes":[{"type":"streamable-http","url":"https://mcp.example.net/weather","headers":[{"name":"Authorization","isSecret":true}]}]}}]}')
elif "api.github.com" in url:
    print('[{"name":"pdf","type":"dir"},{"name":"webapp-testing","type":"dir"},{"name":"README.md","type":"file"}]')
else:
    sys.exit(22)
'''

CATALOG = {"format": 1, "tools": [
    {"id": "skill-demo", "kind": "skill", "name": "demo", "summary": "A demo skill for documents", "tags": ["documents", "pdf"], "roles": {"write": "recommended"},
     "stack": [], "risk": "low", "install": {"dir": "@SKILLDIR@", "name": "demo"}, "scope_hint": "project-role"},
    {"id": "mcp-demo", "kind": "mcp", "name": "demo-mcp", "summary": "Read a demo service", "tags": ["service"], "roles": {"review": "optional"}, "stack": [], "risk": "medium",
     "install": {"name": "demo-mcp", "url": "https://mcp.example.net/demo", "tools": {"read_item": "always_allow"}, "vault_ids": []}, "scope_hint": "user-role"},
    {"id": "pkg-lint", "kind": "package", "name": "shellcheck", "summary": "Lint shell scripts", "tags": ["lint", "shell"], "roles": {"build": "recommended", "test": "optional"},
     "stack": ["go"], "risk": "low", "install": {"manager": "apt", "packages": ["shellcheck", "jq"]}, "scope_hint": "project-role"},
    {"id": "pkg-have", "kind": "package", "name": "groff", "summary": "Man pages", "tags": ["man"], "roles": {"build": "recommended"}, "stack": [], "risk": "low",
     "install": {"manager": "apt", "packages": ["groff"]}},
    {"id": "pkg-rust", "kind": "package", "name": "cargo-audit", "summary": "Audit Rust deps", "tags": ["rust"], "roles": {"build": "recommended"}, "stack": ["rust"], "risk": "low",
     "install": {"manager": "apt", "packages": ["cargo"]}},
    {"id": "agent-wait", "kind": "agent-tool", "name": "Monitor", "summary": "Wait for a detached command", "tags": ["wait"], "roles": {"build": "necessary"}, "stack": [],
     "risk": "low", "install": {"target": "local", "tool": "Monitor"}, "scope_hint": "user"},
]}


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.conf, self.state, self.fake, self.repo = [os.path.join(self.t, d) for d in ("c", "s", "fake", "repo")]
        for d in (self.conf, self.state, self.fake, self.repo, os.path.join(self.t, "bin"), os.path.join(self.t, "skill")):
            os.makedirs(d, exist_ok=True)
        self.w(os.path.join(self.t, "skill", "SKILL.md"), "---\nname: demo\ndescription: Use for demo documents when the user asks.\n---\n\n# demo\n\nSteps.\n")
        self.w(os.path.join(self.repo, "go.mod"), "module example\n")
        tpl = subprocess.run([BIN, "project", "template", "alpha"], capture_output=True, text=True, env=dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=self.state)).stdout
        ans = json.loads(tpl)
        ans["repo"]["path"] = self.repo
        ans["repo"]["url"] = "https://github.com/example/alpha"
        ans["roles"]["build"]["apt"] = ["groff"]
        ans["roles"]["review"] = dict(ans["roles"]["build"], apt=[], model="claude-opus-5-5")
        self.w(os.path.join(self.conf, "projects", "alpha.json"), json.dumps(ans))
        self.w(os.path.join(self.conf, "instances.json"), "{}")
        self.catalog = os.path.join(self.t, "catalog.json")
        self.w(self.catalog, json.dumps(CATALOG).replace("@SKILLDIR@", os.path.join(self.t, "skill")))
        self.agent = os.path.join(self.t, "agent.md")
        self.w(self.agent, "---\nname: x\ntools: Bash, Read, Edit\n---\nbody\n")
        self.w(os.path.join(self.t, "bin", "curl"), FAKE_CURL)
        os.chmod(os.path.join(self.t, "bin", "curl"), 0o755)
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_CATALOG=self.catalog, QARGI_AGENT_FILE=self.agent, FAKE=self.fake,
                        PATH=os.path.join(self.t, "bin") + os.pathsep + os.environ["PATH"])
        self.env.pop("QARGI_PROJECT", None)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def w(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def rd(self, path):
        with open(path) as f:
            return f.read()

    def q(self, args, answers=None, cwd=None):
        e = dict(self.env)
        if answers is not None:
            self.w(os.path.join(self.t, "in"), "".join(a + "\n" for a in answers))
            open(os.path.join(self.t, "out"), "w").close()
            e["QARGI_TTY_IN"], e["QARGI_TTY_OUT"] = os.path.join(self.t, "in"), os.path.join(self.t, "out")
        else:
            e["QARGI_TTY_IN"] = e["QARGI_TTY_OUT"] = "/nonexistent"
        return subprocess.run([BIN, "discover"] + args, capture_output=True, text=True, env=e, cwd=cwd or self.t, stdin=subprocess.DEVNULL)


class Search(Env):
    def test_finds_by_name_tag_and_summary_and_filters(self):
        r = self.q(["search", "pdf"])
        self.assertIn("skill-demo", r.stdout)
        self.assertNotIn("pkg-lint", r.stdout)
        self.assertIn("pkg-lint", self.q(["search", "lint", "--kind", "package"]).stdout)
        self.assertNotIn("skill-demo", self.q(["search", "documents", "--kind", "package"]).stdout)
        self.assertIn("agent-wait", self.q(["search", "wait", "--role", "build"]).stdout)
        self.assertNotIn("agent-wait", self.q(["search", "wait", "--role", "write"]).stdout)
        self.assertIn("Nothing found", self.q(["search", "zzzz"]).stdout)

    def test_online_adds_the_registries_and_marks_them_unreviewed(self):
        r = self.q(["search", "weather", "--online"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("mcp-registry:io.example/weather", r.stdout)
        self.assertIn("not reviewed", self.q(["show", "anthropic-skills:pdf"]).stdout)
        r = self.q(["search", "testing", "--online", "--kind", "skill"])
        self.assertIn("anthropic-skills:webapp-testing", r.stdout)
        self.assertNotIn("README.md", r.stdout)

    def test_an_unreachable_source_is_a_note_not_a_failure(self):
        self.w(os.path.join(self.fake, "offline"), "")
        r = self.q(["search", "demo", "--online"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("skill-demo", r.stdout)
        self.assertIn("could not be reached", r.stderr)

    def test_a_library_pack_is_listed_as_installed(self):
        self.w(os.path.join(self.conf, "packs", "skills", "mine", "SKILL.md"), "x")
        self.assertIn("[installed]", self.q(["search", "mine"]).stdout)


class Recommend(Env):
    def test_ranks_by_role_and_stack_and_leaves_out_what_the_role_has(self):
        r = self.q(["recommend", "alpha", "--role", "build"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("go", r.stdout.splitlines()[0])
        out = r.stdout
        self.assertLess(out.index("agent-wait"), out.index("pkg-lint"))          # necessary first
        self.assertIn("(have)", [l for l in out.splitlines() if "pkg-have" in l][0])
        self.assertNotIn("pkg-rust", out)                                          # needs a stack the repository lacks
        self.assertNotIn("skill-demo", out)                                        # a write tool

    def test_the_project_is_implied_inside_its_repository(self):
        r = self.q(["recommend", "--role", "write"], cwd=self.repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("skill-demo", r.stdout)

    def test_an_unknown_project_names_the_choices(self):
        r = self.q(["recommend", "nope"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("alpha", r.stderr)


class Show(Env):
    def test_show_prints_risk_and_install_data(self):
        r = self.q(["show", "mcp-demo"])
        self.assertIn("risk: medium", r.stdout)
        self.assertIn("install.url: https://mcp.example.net/demo", r.stdout)
        self.assertNotEqual(self.q(["show", "nope"]).returncode, 0)


class Install(Env):
    def test_dry_run_and_the_terminal_requirement(self):
        r = self.q(["install", "skill-demo", "--dry-run"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        r = self.q(["install", "skill-demo"])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("interactive", r.stderr)

    def test_a_skill_goes_through_the_review_the_approval_and_the_scope(self):
        # continue, approve the review, scope by name, then project and role come from the options
        r = self.q(["install", "skill-demo", "--project", "alpha", "--role", "write"], answers=["y", "y", "project-role"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("== review of skill demo", r.stdout)
        self.assertTrue(os.path.exists(os.path.join(self.conf, "packs", "skills", "demo", "SKILL.md")))
        links = json.loads(self.rd(os.path.join(self.conf, "packs", "links.json")))["links"]
        self.assertEqual(links, [{"pack": "skill:demo", "scope": "project-role", "project": "alpha", "role": "write"}])
        audit = self.rd(os.path.join(self.state, "audit.log"))
        self.assertIn("interactive: confirmed at the terminal", audit)
        self.assertIn("skill-import", audit)

    def test_declining_the_review_stores_nothing(self):
        r = self.q(["install", "skill-demo", "--project", "alpha", "--role", "write"], answers=["y", "n"])
        self.assertIn("Not stored", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(self.conf, "packs", "skills", "demo")))

    def test_an_mcp_server_with_an_allowlist_becomes_a_tool_pack(self):
        r = self.q(["install", "mcp-demo", "--scope", "user-role", "--role", "review"], answers=["y", "y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        pack = json.loads(self.rd(os.path.join(self.conf, "packs", "tools", "demo-mcp.json")))
        self.assertEqual(pack["tools"], {"read_item": "always_allow"})
        links = json.loads(self.rd(os.path.join(self.conf, "packs", "links.json")))["links"]
        self.assertEqual(links[0]["scope"], "user-role")

    def test_a_registry_server_without_a_known_allowlist_only_gets_a_draft(self):
        r = self.q(["install", "mcp-registry:io.example/weather"], answers=["y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("does not know which tools", r.stdout)
        draft = os.path.join(self.t, "io-example-weather.tool.json")
        self.assertTrue(os.path.exists(draft))
        self.assertFalse(os.path.exists(os.path.join(self.conf, "packs", "tools")))
        self.assertIn("credential", r.stdout)

    def test_a_package_is_added_to_the_roles_apt_list(self):
        r = self.q(["install", "pkg-lint", "--project", "alpha", "--role", "build"], answers=["y", "y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        apt = json.loads(self.rd(os.path.join(self.conf, "projects", "alpha.json")))["roles"]["build"]["apt"]
        self.assertEqual(apt, ["groff", "shellcheck", "jq"])
        r = self.q(["install", "pkg-have", "--project", "alpha", "--role", "build"], answers=["y"])
        self.assertIn("Already there", r.stdout)

    def test_an_agent_tool_edits_the_local_definition_once(self):
        r = self.q(["install", "agent-wait"], answers=["y", "y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("tools: Bash, Read, Edit, Monitor", self.rd(self.agent))
        r = self.q(["install", "agent-wait"], answers=["y"])
        self.assertIn("already", r.stdout)
        self.assertEqual(self.rd(self.agent).count("Monitor"), 1)

    def test_member_files_are_edited_by_ability(self):
        d = os.path.join(self.t, "agents")
        members = {"forge": ["build", "test"], "scribe": ["write"], "judge": ["review"]}
        for n in members:
            self.w(os.path.join(d, n + ".md"), "---\nname: %s\ntools: Bash, Read\n---\nbody\n" % n)
        self.w(os.path.join(self.conf, "agents.json"), json.dumps({n: {"abilities": a, "file": os.path.join(d, n + ".md"), "seq": k}
                                                                   for k, (n, a) in enumerate(members.items())}))
        env = dict(self.env)
        env.pop("QARGI_AGENT_FILE")
        self.env = env
        r = self.q(["install", "agent-wait", "--role", "review"], answers=["y", "y"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("Monitor", self.rd(os.path.join(d, "judge.md")))
        self.assertNotIn("Monitor", self.rd(os.path.join(d, "forge.md")))
        r = self.q(["install", "agent-wait"], answers=["y", "y"])
        for n in members:
            self.assertEqual(self.rd(os.path.join(d, n + ".md")).count("Monitor"), 1, n)

    def test_answering_no_changes_nothing(self):
        before = self.rd(self.agent)
        r = self.q(["install", "agent-wait"], answers=["y", "n"])
        self.assertEqual(self.rd(self.agent), before)


if __name__ == "__main__":
    unittest.main()
