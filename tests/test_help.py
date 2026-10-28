#!/usr/bin/env python3
"""The command description (lib/commands.py) against the scripts, and the help, man page, completion and
project inference built from it. Offline. Run: python3 tests/test_help.py"""
import glob, json, os, re, shutil, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, LIB)
import commands as C  # noqa: E402
import help as H  # noqa: E402


def slurp(p):
    with open(p) as f:
        return f.read()


def verbs(cmd):
    v = C.COMMANDS[cmd].get("verbs")
    return v if isinstance(v, dict) else {}


def doc_flags(cmd):
    spec = C.COMMANDS[cmd]
    out = {o["flag"] for o in spec.get("opts", [])}
    for v in verbs(cmd).values():
        out |= {o["flag"] for o in v["opts"]}
    return out


# every kind of value the command data may name, and what completes it
TYPES = {"none": None, "project": 1, "instance": 1, "session": 1, "target": 1, "pack": 1, "team": 1, "role": 1, "store": 1, "deployment": 1,
         "model": 1, "branch": 1, "key": 1, "value": 1, "seconds": 1, "cents": 1, "file": 1, "dir": 1, "help": 1}


class Sync(unittest.TestCase):
    def test_every_dispatched_command_is_described_and_back(self):
        src = slurp(BIN)
        body = src[src.index("area=${1:-}"):]
        labels = set()
        for m in re.finditer(r"(?m)^  ([a-z_|-]+)\) ", body):
            labels |= set(m.group(1).split("|"))
        labels -= {"-h", "--help", "__complete"}
        self.assertEqual(labels, set(C.COMMANDS), "bin/qargi and lib/commands.py disagree")

    def test_groups_cover_every_command_once(self):
        listed = [c for _, cs in C.GROUPS for c in cs]
        self.assertEqual(sorted(listed), sorted(C.COMMANDS))

    def test_documented_verbs_and_flags_exist_in_the_scripts(self):
        for cmd, spec in C.COMMANDS.items():
            src = "".join(slurp(os.path.join(LIB, s)) for s in spec.get("scripts", []))
            if not src:
                continue
            for v in verbs(cmd):
                self.assertRegex(src, r"\b%s\b" % re.escape(v), "%s %s is documented but not in %s" % (cmd, v, spec["scripts"]))
            for f in doc_flags(cmd):
                self.assertIn(f, src, "%s %s is documented but not in %s" % (cmd, f, spec["scripts"]))

    def test_every_flag_a_script_parses_is_documented(self):
        label = re.compile(r"(?m)^\s*(--[a-z][a-z-]*(?:\|--?[a-z][a-z-]*)*)\)")
        quoted = re.compile(r"\"(--[a-z][a-z-]+)\"")
        by_script = {}
        for cmd, spec in C.COMMANDS.items():
            for s in spec.get("scripts", []):
                by_script.setdefault(s, set()).update(doc_flags(cmd))
        ignore = {"--help"}
        for s, documented in by_script.items():
            src = slurp(os.path.join(LIB, s))
            found = set()
            for m in label.finditer(src):
                found |= set(m.group(1).split("|"))
            if s.endswith(".py"):
                found |= set(quoted.findall(src))
            missing = {f for f in found if f.startswith("--")} - documented - ignore
            self.assertFalse(missing, "%s parses %s, which lib/commands.py does not describe" % (s, sorted(missing)))

    def test_argument_types_are_known(self):
        known = set(TYPES)
        for cmd, spec in C.COMMANDS.items():
            arglists = [spec.get("usage", [])] + [v["args"] for v in verbs(cmd).values()]
            for al in arglists:
                for a in al:
                    self.assertTrue(isinstance(a[1], tuple) or H.kind(a[1]) in known, "%s: unknown argument type %r" % (cmd, a[1]))
            opts = list(spec.get("opts", [])) + [o for v in verbs(cmd).values() for o in v["opts"]]
            for o in opts:
                self.assertTrue(isinstance(o["type"], tuple) or H.kind(o["type"]) in known, "%s %s: unknown type" % (cmd, o["flag"]))


class Render(unittest.TestCase):
    def test_overview_names_everything(self):
        out = H.show_overview()
        self.assertIn(C.TAGLINE, out)
        for title, cmds in C.GROUPS:
            self.assertIn(title, out)
            for c in cmds:
                self.assertIn(c, out)
        for t in C.TOPICS:
            self.assertIn(t, out)
        self.assertNotIn("\033", out)

    def test_every_command_and_verb_renders_within_the_width(self):
        for cmd in C.COMMANDS:
            txt = H.show_command(cmd)
            self.assertTrue(txt and cmd in txt)
            for v in verbs(cmd):
                vt = H.show_command(cmd, v)
                self.assertTrue(vt and v in vt, "%s %s" % (cmd, v))
                for line in vt.splitlines():
                    self.assertLessEqual(len(line), 100, "%s %s: %r" % (cmd, v, line))
        for t in C.TOPICS:
            self.assertTrue(H.show_topic(t))

    def test_cli_help_forms(self):
        def run(*a, env=None):
            return subprocess.run([BIN, *a], capture_output=True, text=True, env=dict(os.environ, **(env or {})), stdin=subprocess.DEVNULL)
        self.assertEqual(run("help").returncode, 0)
        r = run("lead", "--help")
        self.assertEqual(r.returncode, 0)
        self.assertIn("grant", r.stdout)
        r = run("canon", "apply", "-h")
        self.assertIn("--plan", r.stdout)
        r = run("help", "approvals")
        self.assertIn("plan token", r.stdout)
        r = run("help", "nosuch")
        self.assertEqual(r.returncode, 2)
        r = run("nosuch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("unknown command", r.stderr)
        self.assertEqual(run("version").returncode, 0)

    def test_man_page_is_current_and_lints(self):
        page = H.man()
        self.assertEqual(slurp(os.path.join(ROOT, "man", "qargi.1")), page, "regenerate: python3 lib/help.py man > man/qargi.1")
        self.assertIn(".SH COMMANDS", page)
        for c in C.COMMANDS:
            self.assertIn("qargi %s" % c.replace("-", "\\-"), page)
        if shutil.which("groff"):
            r = subprocess.run(["groff", "-k", "-ww", "-man", "-Tutf8"], input=page, capture_output=True, text=True)
            self.assertEqual(r.stderr, "", "groff warnings")


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.t, "c", "projects"))
        os.makedirs(os.path.join(self.t, "s"))
        self.repo = os.path.join(self.t, "repo")
        os.makedirs(os.path.join(self.repo, "sub"))
        def put(path, obj):
            with open(path, "w") as f:
                json.dump(obj, f)
        for n, path in (("alpha", self.repo), ("beta", os.path.join(self.t, "elsewhere"))):
            put(os.path.join(self.t, "c", "projects", n + ".json"), {"project": n, "repo": {"path": path}, "teams": {"code-docs": {}} if n == "alpha" else {}})
        put(os.path.join(self.t, "c", "instances.json"), {"alpha-dev": {}, "alpha-docs": {}})
        put(os.path.join(self.t, "s", "sessions.json"), {"sesn_1": {}})
        self.put = put
        self.old = {k: os.environ.get(k) for k in ("QARGI_CONF", "QARGI_STATE", "QARGI_PROJECT")}
        os.environ["QARGI_CONF"], os.environ["QARGI_STATE"] = os.path.join(self.t, "c"), os.path.join(self.t, "s")
        os.environ.pop("QARGI_PROJECT", None)
        self.cwd = os.getcwd()

    def tearDown(self):
        os.chdir(self.cwd)
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.t, ignore_errors=True)


class Complete(Env):
    def test_commands_verbs_and_values(self):
        self.assertIn("lead", H.complete([""]))
        self.assertEqual(H.complete(["lead", ""]), ["grant", "status", "revoke"])
        self.assertEqual(H.complete(["lead", "grant", ""]), ["alpha"])   # only projects that define teams
        self.assertEqual(H.complete(["team", "brief", "alpha", ""]), ["code-docs"])
        self.assertEqual(H.complete(["instances", "show", ""]), ["alpha-dev", "alpha-docs"])
        self.assertEqual(H.complete(["close", ""]), ["sesn_1"])
        self.assertEqual(H.complete(["canon", "apply", "--kind", ""]), ["memory", "reference"])
        self.assertEqual(H.complete(["skill", "link", "x", "--scope", ""]), ["user", "user-role", "project", "project-role"])
        self.assertIn("--plan", H.complete(["canon", "apply", "alpha", "-"]))
        self.assertEqual(H.complete(["review", "check", ""]), ["@dir"])
        self.assertEqual(H.complete(["project", "init", "x", "--answers", ""]), ["@file"])
        self.assertIn("lead", H.complete(["help", ""]))
        self.assertEqual(H.complete(["nosuch", ""]), [])

    def test_bash_function(self):
        script = os.path.join(ROOT, "completions", "qargi.bash")
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi lead gr); COMP_CWORD=2; _qargi; echo "${COMPREPLY[*]}"' % script],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.strip(), "grant", r.stderr)
        r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi instances show ""); COMP_CWORD=3; _qargi; echo "${COMPREPLY[*]}"' % script],
                           capture_output=True, text=True, env=env)
        self.assertEqual(r.stdout.split(), ["alpha-dev", "alpha-docs"], r.stderr)


class Shells(Env):
    def run_shell(self, argv, script):
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        return subprocess.run(argv + [script], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)

    def test_described_output(self):
        out = H.complete_described(["lead", ""])
        self.assertEqual([c for c, _ in out], ["grant", "status", "revoke"])
        self.assertTrue(all(d for _, d in out))
        r = subprocess.run([BIN, "__complete", "--described", "lead", ""], capture_output=True, text=True)
        self.assertIn("grant\tGuided", r.stdout)

    @unittest.skipUnless(shutil.which("zsh"), "zsh is not installed")
    def test_zsh(self):
        script = os.path.join(ROOT, "completions", "_qargi")
        stub = ('_describe() { shift 3; print -l -- "${(@P)1}"; }; _files() { print "FILES $*"; }; f() { source %s }; ' % script)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi lead ""); CURRENT=3; f')
        self.assertEqual([l.split(":")[0] for l in r.stdout.split("\n") if l], ["grant", "status", "revoke"], r.stderr)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi instances show ""); CURRENT=4; f')
        self.assertEqual([l.split(":")[0] for l in r.stdout.split("\n") if l], ["alpha-dev", "alpha-docs"], r.stderr)
        r = self.run_shell(["zsh", "-f", "-c"], stub + 'words=(qargi review check ""); CURRENT=4; f')
        self.assertEqual(r.stdout.strip(), "FILES -/")
        r = self.run_shell(["zsh", "-n"], script)
        self.assertEqual(r.returncode, 0, r.stderr)

    @unittest.skipUnless(shutil.which("fish"), "fish is not installed")
    def test_fish(self):
        script = os.path.join(ROOT, "completions", "qargi.fish")
        r = self.run_shell(["fish", "-c"], 'source %s; complete -C "qargi lead "' % script)
        self.assertEqual(sorted(l.split("\t")[0] for l in r.stdout.split("\n") if l), ["grant", "revoke", "status"], r.stderr)
        r = self.run_shell(["fish", "-c"], 'source %s; complete -C "qargi team brief alpha "' % script)
        self.assertEqual(r.stdout.strip(), "code-docs", r.stderr)
        r = self.run_shell(["fish", "-n"], script)
        self.assertEqual(r.returncode, 0, r.stderr)


class Rich(Env):
    """Values from the user's own state, narrowed by what the verb can act on, with a description each."""
    def setUp(self):
        super().setUp()
        res = [{"memory_store_id": "memstore_A", "access": "read_write"}, {"memory_store_id": "memstore_B", "access": "read_only"}]
        agent = {"version_pinned": 3, "model": "claude-sonnet-5-5", "effort": "high"}
        self.put(os.path.join(self.t, "c", "instances.json"), {
            "alpha-dev": {"location": "cloud", "agent": agent, "deployment_id": "depl_1", "resources": res},
            "alpha-docs": {"location": "cloud", "agent": dict(agent, model="claude-opus-5-5"), "deployment_id": "depl_2", "resources": res},
            "alpha-local": {"location": "local"}})
        self.put(os.path.join(self.t, "s", "sessions.json"), {
            "sesn_run": {"instance": "alpha-dev", "status": "running", "label": "job", "list_cost": "9", "outputs_collected": False},
            "sesn_idle": {"instance": "alpha-dev", "status": "idle", "outputs_collected": True},
            "sesn_old": {"instance": "alpha-dev", "status": "archived", "closed_at": "2026-01-01T00:00:00Z", "outputs_collected": True}})
        self.put(os.path.join(self.t, "c", "projects", "alpha.json"), {
            "project": "alpha", "repo": {"path": self.repo, "url": "https://example.net/alpha"}, "budget_cents": 1500,
            "teams": {"code-docs": {"members": ["dev", "docs"]}}, "lead": {"push": {"local": True, "cloud": "none"}},
            "roles": {"dev": {"model": "claude-sonnet-5-5", "effort": "high"}, "docs": {"model": "claude-opus-5-5", "effort": "medium"}}})
        os.makedirs(os.path.join(self.t, "c", "packs", "skills", "pdf"))
        os.makedirs(os.path.join(self.t, "c", "packs", "tools"))
        self.put(os.path.join(self.t, "c", "packs", "tools", "github.json"), {})

    def test_sessions_are_narrowed_by_what_the_verb_does(self):
        self.assertEqual(H.complete(["stop", ""]), ["sesn_run"])
        self.assertEqual(H.complete(["collect", ""]), ["sesn_run"])
        self.assertEqual(H.complete(["close", ""]), ["sesn_idle", "sesn_run"])
        self.assertEqual(H.complete(["watch", ""]), ["sesn_idle", "sesn_run"])
        self.assertEqual(H.complete(["send", "alpha-dev", "x", "--session", ""]), ["sesn_idle"])
        self.assertEqual(H.complete(["status", ""]), ["sesn_idle", "sesn_old", "sesn_run", "alpha-dev", "alpha-docs"])   # sessions and cloud instances
        self.assertEqual(dict(H.complete_described(["stop", ""]))["sesn_run"], "alpha-dev running job $0.09")

    def test_cloud_verbs_do_not_offer_a_local_instance(self):
        self.assertEqual(H.complete(["start", ""]), ["alpha-dev", "alpha-docs"])
        self.assertEqual(H.complete(["instances", "show", ""]), ["alpha-dev", "alpha-docs", "alpha-local"])
        self.assertEqual(dict(H.complete_described(["start", ""]))["alpha-dev"], "cloud agent v3 claude-sonnet-5-5/high")

    def test_stores_deployments_models_and_numbers(self):
        self.assertEqual(dict(H.complete_described(["memory", "lint", ""])), {"memstore_A": "alpha, memory", "memstore_B": "alpha, reference"})
        self.assertEqual(H.complete(["memory", "get", "memstore_A", ""]), [])   # a note path needs the store itself
        self.assertEqual(H.complete(["instances", "init", "--deployment", ""]), ["depl_1", "depl_2"])
        self.assertEqual(H.complete(["provision", "plan", "--memory-store", ""]), ["memstore_A", "memstore_B"])
        self.assertIn("claude-opus-5-5", H.complete(["instances", "init", "--model", ""]))
        self.assertEqual(H.complete(["instances", "budget", "alpha-dev", ""])[:2], ["500", "1000"])
        self.assertIn("3600", H.complete(["watch", "sesn_run", ""]))

    def test_branches_come_from_the_projects_repository(self):
        def git(*a):
            subprocess.run(["git", "-C", self.repo] + list(a), check=True, capture_output=True,
                           env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.net", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.net"))
        git("init", "-q", "-b", "develop"); git("commit", "-q", "--allow-empty", "-m", "x"); git("branch", "feature/one")
        self.assertEqual(sorted(H.complete(["team", "brief", "alpha", "code-docs", "--base", ""])), ["develop", "feature/one"])
        os.chdir(self.repo)
        self.assertEqual(sorted(H.complete(["local", "prepare", "--base", ""])), ["develop", "feature/one"])

    def test_project_answers_and_their_values(self):
        keys = H.complete(["project", "set", "alpha", ""])
        for k in ("budget_cents", "lead.push.local", "roles.dev.effort", "roles.docs.model", "teams.code-docs.members", "lead.push.merge"):
            self.assertIn(k, keys)
        self.assertEqual(dict(H.complete_described(["project", "set", "alpha", ""]))["budget_cents"], "now 1500")
        self.assertEqual(H.complete(["project", "set", "alpha", "roles.dev.effort", ""]), list(C.EFFORTS))
        self.assertEqual(H.complete(["project", "set", "alpha", "lead.push.cloud", ""]), ["none", "branches"])
        self.assertEqual(H.complete(["project", "set", "alpha", "lead.push.local", ""]), ["true", "false"])
        self.assertEqual(H.complete(["project", "set", "alpha", "budget_cents", ""]), [])
        os.chdir(os.path.join(self.repo, "sub"))   # the project implied by the directory also gives the keys
        self.assertIn("budget_cents", H.complete(["project", "set", "alpha", ""]))

    def test_packs_follow_the_command(self):
        self.assertEqual(H.complete(["skill", "show", ""]), ["pdf"])
        self.assertEqual(H.complete(["tool", "show", ""]), ["github"])

    def test_roles_follow_the_project_and_teams_get_their_members(self):
        self.assertEqual(H.complete(["packs", "render", "alpha", ""]), ["dev", "docs", "lead"])
        self.assertEqual(dict(H.complete_described(["packs", "render", "alpha", ""]))["docs"], "claude-opus-5-5/medium")
        self.assertEqual(dict(H.complete_described(["team", "brief", "alpha", ""]))["code-docs"], "dev, docs")

    def test_option_equals_value_and_options_are_offered_once(self):
        self.assertEqual(H.complete(["instances", "init", "--effort="]), ["--effort=" + e for e in C.EFFORTS])
        self.assertEqual(H.complete(["canon", "apply", "alpha", "--kind=", ]), ["--kind=memory", "--kind=reference"])
        # an inline value counts as given: no option twice, the positional is still the next one
        out = H.complete(["canon", "apply", "--kind=memory", "alpha", "-"])
        self.assertNotIn("--kind", out)
        self.assertIn("--plan", out)
        self.assertIn("--help", out)
        self.assertEqual(H.complete(["start", "--label=x", ""]), ["alpha-dev", "alpha-docs"])

    def test_help_completes_the_verbs_of_a_command(self):
        self.assertIn("refresh-prompt", H.complete(["help", "instances", ""]))
        self.assertEqual(H.complete(["help", "start", ""]), [])
        self.assertEqual(H.complete(["help", "instances", "show", ""]), [])

    def test_bash_puts_option_equals_value_back_together(self):
        script = os.path.join(ROOT, "completions", "qargi.bash")
        env = dict(os.environ, PATH=os.path.join(ROOT, "bin") + os.pathsep + os.environ["PATH"])
        for words, cword, want in (("instances init --effort = hi", 5, "high"), ("instances init --effort =", 4, "low medium high xhigh max")):
            r = subprocess.run(["bash", "-c", 'source "%s"; COMP_WORDS=(qargi %s); COMP_CWORD=%d; _qargi; echo "${COMPREPLY[*]}"' % (script, words, cword)],
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.stdout.strip(), want, r.stderr)

    def test_every_kind_of_value_has_a_completer(self):
        """A new type in the command data must come with candidates, as tacctl's completion is held to its schema."""
        seen = set()
        for cmd, spec in C.COMMANDS.items():
            vs = spec.get("verbs") or {}
            lists = [(spec.get("usage", []), spec.get("opts", []))] + [(v["args"], v["opts"]) for v in vs.values()]
            for args, opts in lists:
                seen |= {H.kind(a[1]) for a in args if isinstance(a[1], str)} | {H.kind(o["type"]) for o in opts if isinstance(o["type"], str)}
        self.assertEqual(seen, set(TYPES), "the types in the command data and the list in this test")
        ctx = ["alpha", "dev", "project"]
        for t in sorted(seen - {"none", "value", "branch"}):   # a branch needs a repository (its own test); a value needs a key
            self.assertTrue(H.by_type(t, ctx), "no candidates for the type %r" % t)
        self.assertTrue(H.by_type("value", ["alpha", "lead.push.cloud"]))


class Infer(Env):
    def test_project_is_implied_inside_its_repository(self):
        os.chdir(os.path.join(self.repo, "sub"))
        self.assertEqual(H.infer_project(), "alpha")
        self.assertEqual(H.resolve(["lead", "status"]), ["lead", "status", "alpha"])
        self.assertEqual(H.resolve(["lead", "status", "beta"]), ["lead", "status", "beta"])     # an explicit project wins
        self.assertEqual(H.resolve(["team", "brief", "code-docs", "--task", "x"]), ["team", "brief", "alpha", "code-docs", "--task", "x"])
        self.assertEqual(H.resolve(["team", "brief", "alpha", "code-docs"]), ["team", "brief", "alpha", "code-docs"])
        self.assertEqual(H.resolve(["credential", "setup", "lead-push", "--from-file", "f"]), ["credential", "setup", "lead-push", "alpha", "--from-file", "f"])
        self.assertEqual(H.resolve(["canon", "apply", "--kind", "memory"]), ["canon", "apply", "alpha", "--kind", "memory"])
        self.assertEqual(H.resolve(["project", "set", "budget_cents", "600"]), ["project", "set", "alpha", "budget_cents", "600"])
        self.assertEqual(H.resolve(["skill", "check", "docs"]), ["skill", "check", "alpha", "docs"])

    def test_a_role_stands_for_the_instance(self):
        os.chdir(self.repo)
        self.assertEqual(H.resolve(["instances", "show", "dev"]), ["instances", "show", "alpha-dev"])
        self.assertEqual(H.resolve(["instances", "show", "alpha-docs"]), ["instances", "show", "alpha-docs"])
        self.assertEqual(H.resolve(["provision", "plan", "docs"]), ["provision", "plan", "alpha-docs"])
        self.assertEqual(H.resolve(["provision", "plan"]), ["provision", "plan", "--project", "alpha"])
        self.assertEqual(H.resolve(["send", "dev", "the task text", "--label", "x"]), ["send", "alpha-dev", "the task text", "--label", "x"])

    def test_free_text_and_unrelated_commands_are_left_alone(self):
        os.chdir(self.repo)
        for argv in (["send", "alpha-dev", "dev lead status", "--label", "x"], ["collect", "sesn_1", "dir"], ["review", "check", "dir"],
                     ["help", "lead"], ["version"], ["skill", "list"], ["memory", "get", "memstore_1", "/a.md"]):
            self.assertEqual(H.resolve(argv), argv, argv)

    def test_outside_a_repository_nothing_is_guessed(self):
        os.chdir(self.t)
        self.assertIsNone(H.infer_project())
        self.assertEqual(H.resolve(["instances", "show", "dev"]), ["instances", "show", "dev"])
        self.assertIsNone(H.resolve(["lead", "status"]))
        self.assertEqual(H.resolve(["lead", "status", "alpha"]), ["lead", "status", "alpha"])

    def test_environment_names_the_project(self):
        os.chdir(self.t)
        os.environ["QARGI_PROJECT"] = "beta"
        self.assertEqual(H.resolve(["lead", "status"]), ["lead", "status", "beta"])

    def test_the_command_line_uses_it(self):
        os.chdir(self.repo)
        r = subprocess.run([BIN, "project", "show"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("alpha", r.stdout)
        os.chdir(self.t)
        r = subprocess.run([BIN, "project", "show"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 2)
        self.assertIn("which project?", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
