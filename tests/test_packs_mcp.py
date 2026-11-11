#!/usr/bin/env python3
"""lib/packs_mcp.py: what a runtime calls an MCP tool, which tools of its tool packs a role gets, and whether a member may call one.

The render writes its permission rules with these names, the tool list of a member holds them and the guard judges a call by them, so the three agree by
construction; this file holds the answers themselves. The packs of a role are checked against `qargi tool effective` and `qargi skill effective`, the
shell's own list. The guard's side (the run, the hook command) is in tests/test_guard.py (McpTools), the member's in tests/test_agent.sh, the render's
in tests/test_packs_render.sh.
Run: python3 tests/test_packs_mcp.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import packs_check as C  # noqa: E402
import packs_mcp as M  # noqa: E402

CLAUDE = {"permission_rule": "mcp__{server}__{tool}", "name_key": "nonword-underscore"}


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


class Names(unittest.TestCase):
    def test_the_form_is_the_definitions(self):
        with open(os.path.join(ROOT, "lib", "providers", "claude-code.json")) as f:
            mcp = json.load(f)["resources"]["mcp"]
        self.assertEqual(M.form_of(mcp), {"rule": "mcp__{server}__{tool}", "name_key": "nonword-underscore"})
        self.assertEqual(M.form_of({"permission_rule": "{server}.{tool}"}), {"rule": "{server}.{tool}", "name_key": None})
        for none in (None, {}, [], {"permission_rule": None}, {"permission_rule": "mcp__{server}"}, {"permission_rule": "{tool}"}, {"permission_rule": 7},
                     {"permission_rule": "plain"}):
            self.assertIsNone(M.form_of(none), none)

    def test_a_name_as_the_runtime_writes_it(self):
        form = M.form_of(CLAUDE)
        for server, tool, want in (("kb", "list_items", "mcp__kb__list_items"), ("kb", "platform.list_items", "mcp__kb__platform_list_items"),
                                   ("kb", "repo/push", "mcp__kb__repo_push"), ("kb", "issue-close", "mcp__kb__issue-close"), ("kb", "deleteItem", "mcp__kb__deleteItem"),
                                   ("my-server", "a.b/c-d_e", "mcp__my-server__a_b_c-d_e"), ("kb", "{server}", "mcp__kb___server_")):
            self.assertEqual(M.native(form, server, tool), want)
        plain = M.form_of({"permission_rule": "{server}.{tool}"})
        self.assertEqual(M.native(plain, "kb", "repo/push"), "kb.repo/push")
        self.assertEqual(M.native(M.form_of({"permission_rule": "t:{tool}@{server}"}), "{tool}", "{server}"), "t:{server}@{tool}", "one pass: a name is never read for placeholders")
        self.assertEqual(M.part("nonword-underscore", "a b\n*(c)é"), "a_b___c__")
        self.assertEqual(M.part(None, "a.b/c"), "a.b/c")
        for key in ("rot13", 7, ["nonword-underscore"]):
            with self.assertRaises(M.McpError):
                M.part(key, "x")

    def test_the_shape_of_a_name(self):
        form = M.form_of(CLAUDE)
        for name in ("mcp__kb__search", "mcp__kb__a__b", "mcp__a-b__c_d", "mcp__kb__x\ny"):
            self.assertTrue(M.is_name(form, name), name)
        for name in ("Bash", "mcp__kb", "mcp____", "mcp__kb__", "mcp____x", "xmcp__kb__search", "mcp_kb_search", "", None, 7):
            self.assertFalse(M.is_name(form, name), name)
        self.assertFalse(M.is_name(None, "mcp__kb__search"))
        dotted = M.form_of({"permission_rule": "{server}.{tool}"})
        self.assertTrue(M.is_name(dotted, "kb.search"))
        self.assertFalse(M.is_name(dotted, "mcp__kb__search"))

    def test_the_names_a_tools_map_may_hold_are_the_reviews(self):
        for k in ("platform.list_items", "repo/push", "x" * 128):
            self.assertTrue(M.tool_key_ok(k))
        for k in ("a b", "x" * 129, "*", "", None, 3):
            self.assertFalse(M.tool_key_ok(k))


class Roles(unittest.TestCase):
    """The packs of a role and the tools they give it. The library: kb for every role of alpha, ops for build of alpha, look for review of every project, all
    for every role of every project, a skill beside them, a pack of another project, a pack the project's runtime cannot use, and the role write opted out of kb."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mcp.")
        self.conf = os.path.join(self.dir, "conf")
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.dir, "state"), HOME=os.path.join(self.dir, "home"))
        os.makedirs(self.env["HOME"])
        role = {"base": "@dispatcher", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high", "apt": [], "skills": []}
        put(os.path.join(self.conf, "projects", "alpha.json"), json.dumps(
            {"schema": 1, "project": "alpha", "repo": {"url": "https://github.com/example/x", "path": os.path.join(self.dir, "repo"), "long_lived": ["main"]},
             "roles": {"build": role, "review": role, "write": dict(role, packs_off=["tool:kb", "skill:notes"])},
             "models": {"provider": {"local": "claude-code", "cloud": "claude-platform"}}, "memory": {"memory_store": "", "reference_store": ""}, "budget_cents": 500}))
        self.links = []
        self.tool("kb", {"platform.list_items": "always_allow", "getStatus": "always_allow", "platform.delete_knowledge": "always_allow", "repo/push": "auto", "issue-close": "always_ask"},
                  {"scope": "project", "project": "alpha"}, write_ok=True)
        self.tool("ops", {"list_jobs": "always_allow"}, {"scope": "project-role", "project": "alpha", "role": "build"})
        self.tool("look", {"lookup": "always_allow", "fetch_all": "always_allow"}, {"scope": "user-role", "role": "review"}, write_ok=True,
                  listing={"lookup": "read-only", "fetch_all": "write"})
        self.tool("all", {"ping": "always_allow"}, {"scope": "user"})
        self.tool("beta-only", {"list_b": "always_allow"}, {"scope": "project", "project": "beta"})
        self.tool("other-rt", {"list_o": "always_allow"}, {"scope": "project", "project": "alpha"}, compat=["other-provider"])
        d = os.path.join(self.conf, "packs", "skills", "notes")
        put(os.path.join(d, "SKILL.md"), "---\nname: notes\ndescription: Use for notes.\n---\nbody\n")
        put(os.path.join(d, ".pack.json"), json.dumps({"kind": "skill", "source": "created", "compatible_providers": ["any"]}))
        self.links.append({"pack": "skill:notes", "scope": "project", "project": "alpha"})
        put(os.path.join(self.conf, "packs", "links.json"), json.dumps({"links": self.links}))
        self.form = M.form_of(CLAUDE)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def tool(self, name, tools, link, write_ok=False, listing=None, compat=("any",)):
        p = os.path.join(self.conf, "packs", "tools", name + ".json")
        put(p, json.dumps(dict({"name": name, "url": "https://mcp.example.net/" + name, "tools": tools}, **({"write_ok": True} if write_ok else {}))))
        rec = {"kind": "tool", "source": "created", "stored": "2026-01-01T00:00:00Z", "compatible_providers": list(compat)}
        if listing is not None:
            rec["tool_list"] = {"sha256": "ab" * 32, "tools": listing}
        put(p[:-5] + ".pack.json", json.dumps(rec))
        put(p[:-5] + ".pack.json", json.dumps(dict(rec, sha256=C.content_hash(p))))
        self.links.append(dict(link, pack="tool:" + name))

    def qargi(self, *args):
        r = subprocess.run([os.path.join(ROOT, "bin", "qargi")] + list(args), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        return r.stdout

    def test_the_packs_of_a_role_are_the_ones_the_shell_lists(self):
        for role in ("build", "review", "write", "test"):
            mine = M.effective(self.conf, "alpha", role)
            shell = sorted(["tool:" + ln for ln in self.qargi("tool", "effective", "alpha", role).split("\n") if ln and not ln.startswith("skipped ")] +
                           ["skill:" + ln for ln in self.qargi("skill", "effective", "alpha", role).split("\n") if ln and not ln.startswith("skipped ")])
            self.assertEqual([e for e in mine if e != "tool:other-rt"], shell, role)          # effective lists what the links say; the shell has taken the skipped pack out
            self.assertIn("tool:other-rt", mine)
            self.assertIn("skipped tool other-rt", self.qargi("tool", "effective", "alpha", role))
        self.assertEqual(M.effective(self.conf, "alpha", "build"), ["skill:notes", "tool:all", "tool:kb", "tool:ops", "tool:other-rt"])
        self.assertEqual(M.effective(self.conf, "alpha", "write"), ["tool:all", "tool:other-rt"])
        self.assertEqual(M.effective(self.conf, "beta", "review"), ["tool:all", "tool:beta-only", "tool:look"])
        self.assertEqual(M.effective(self.conf, "nosuch", "build"), ["tool:all"])

    def test_the_tools_of_a_role_under_the_runtimes_names(self):
        table = M.tools_of(self.conf, "alpha", "build", self.form)
        self.assertEqual(sorted(table), ["mcp__all__ping", "mcp__kb__getStatus", "mcp__kb__issue-close", "mcp__kb__platform_delete_knowledge", "mcp__kb__platform_list_items",
                                         "mcp__kb__repo_push", "mcp__ops__list_jobs"])
        self.assertTrue(all(len(v) == 1 and v[0].unusable is None for v in table.values()))
        self.assertEqual({n: t[0].read for n, t in table.items()},
                         {"mcp__all__ping": True, "mcp__kb__getStatus": True, "mcp__kb__platform_list_items": True, "mcp__ops__list_jobs": True,
                          "mcp__kb__issue-close": False, "mcp__kb__platform_delete_knowledge": False, "mcp__kb__repo_push": False})
        review = M.tools_of(self.conf, "alpha", "review", self.form)
        self.assertEqual({n: t[0].read for n, t in review.items() if "look" in n}, {"mcp__look__lookup": True, "mcp__look__fetch_all": False})
        self.assertNotIn("mcp__ops__list_jobs", review)
        self.assertEqual(sorted(M.tools_of(self.conf, "alpha", "write", self.form)), ["mcp__all__ping"])
        self.assertEqual(sorted(M.tools_of(self.conf, "alpha", "build", M.form_of({"permission_rule": "{server}.{tool}"})))[:3], ["all.ping", "kb.getStatus", "kb.issue-close"])

    def test_the_tool_list_of_a_member(self):
        def member(*roles):
            return M.member_tools(self.conf, "alpha", roles, {"build": False, "write": False, "review": True, "test": False}, self.form)
        self.assertEqual(member("build"), ["mcp__all__ping", "mcp__kb__getStatus", "mcp__kb__platform_delete_knowledge", "mcp__kb__platform_list_items",
                                           "mcp__kb__repo_push", "mcp__ops__list_jobs"], "every tool of the role's packs but the always_ask one")
        self.assertEqual(member("review"), ["mcp__all__ping", "mcp__kb__getStatus", "mcp__kb__platform_list_items", "mcp__look__lookup"], "a read-only role: the declared reads")
        self.assertEqual(member("build", "review"), sorted(set(member("build")) | set(member("review"))), "what at least one of its roles may call")
        self.assertEqual(member("write"), ["mcp__all__ping"])
        self.assertEqual(member(), [])
        self.assertEqual(M.member_tools(self.conf, "alpha", ["build"], {}, None), [], "a runtime with no MCP tool names")
        put(os.path.join(self.conf, "packs", "links.json"), json.dumps({"links": []}))
        self.assertEqual(member("build", "review", "write", "test"), [], "no tool pack reaches the roles: no MCP tool")
        put(os.path.join(self.conf, "packs", "links.json"), "{nope")
        with self.assertRaises(M.McpError):
            member("build")

    def test_a_pack_counts_only_as_it_was_approved(self):
        p = os.path.join(self.conf, "packs", "tools", "ops.json")
        self.assertIsNone(M.refusal(self.conf, "alpha", "build", False, "mcp__ops__list_jobs", self.form))
        with open(p) as f:
            doc = json.load(f)
        put(p, json.dumps(dict(doc, tools={"list_jobs": "always_allow", "run_job": "always_allow"})))
        for name in ("mcp__ops__list_jobs", "mcp__ops__run_job"):
            self.assertIn("the tool pack ops changed since it was approved", M.refusal(self.conf, "alpha", "build", False, name, self.form))
        self.assertNotIn("mcp__ops__list_jobs", M.member_tools(self.conf, "alpha", ["build"], {}, self.form))
        os.remove(p)
        self.assertIn("is not a tool of a tool pack linked to the role build of alpha", M.refusal(self.conf, "alpha", "build", False, "mcp__ops__list_jobs", self.form))


if __name__ == "__main__":
    unittest.main()
