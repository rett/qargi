#!/usr/bin/env python3
"""qargi migrate roles: an installation with the old role names, a fake ant with state, a throwaway home.
The plan changes nothing, the apply needs its token and --asked, a second run finds nothing, and a failure in
the middle stops with what is done and is finished by running it again.
`python3 tests/test_migrate.py fixture DIR [PROJECT]` only builds the fixture in DIR (to look at the plan by hand)."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")

FAKE_ANT = r'''#!/usr/bin/env python3
import hashlib, json, os, re, sys
fake = os.environ["FAKE"]
a = sys.argv[1:]
with open(os.path.join(fake, "ant.log"), "a") as f:
    f.write(" ".join(a) + "\n")
if os.environ.get("FAKE_FAIL") and re.search(os.environ["FAKE_FAIL"], " ".join(a)):
    sys.exit(1)
def opt(k):
    return a[a.index(k) + 1] if k in a else None
def path(kind, i):
    return os.path.join(fake, kind, i + ".json")
def load(kind, i):
    try:
        return json.load(open(path(kind, i)))
    except OSError:
        sys.exit(1)
def save(kind, i, o):
    json.dump(o, open(path(kind, i), "w"))
cmd, verb = (a + ["", ""])[:2]
if cmd == "auth":
    sys.exit(0)
if cmd == "beta:agents":
    i = opt("--agent-id"); o = load("agents", i)
    if verb == "update":
        if str(o["version"]) != opt("--version"):
            sys.exit(1)
        o["version"] += 1
        for k in ("name", "system"):
            if opt("--" + k) is not None: o[k] = opt("--" + k)
        if opt("--multiagent"): o["multiagent"] = json.loads(opt("--multiagent"))
        save("agents", i, o)
    print(json.dumps(o))
elif cmd == "beta:deployments":
    i = opt("--deployment-id"); o = load("deployments", i)
    if verb == "update":
        if opt("--agent"): o["agent"] = {"id": opt("--agent"), "version": load("agents", opt("--agent"))["version"]}
        if opt("--name"): o["name"] = opt("--name")
        save("deployments", i, o)
    print(json.dumps(o))
elif cmd in ("beta:environments", "beta:memory-stores"):
    kind = "environments" if cmd == "beta:environments" else "stores"
    i = opt("--environment-id") if kind == "environments" else opt("--memory-store-id"); o = load(kind, i)
    if verb == "update":
        o["name"] = opt("--name"); save(kind, i, o)
    print(json.dumps(o))
elif cmd == "beta:memory-stores:memories":
    s = opt("--memory-store-id"); d = os.path.join(fake, "memories", s)
    if verb == "list":
        for fn in sorted(os.listdir(d)):
            m = json.load(open(os.path.join(d, fn)))
            m["type"] = "memory"; m["content_sha256"] = hashlib.sha256(m["content"].encode()).hexdigest()
            print(json.dumps(m, indent=2))
    elif verb == "update":
        f = os.path.join(d, opt("--memory-id") + ".json"); m = json.load(open(f))
        if opt("--path"): m["path"] = opt("--path")
        body = sys.stdin.read()
        if '"@' in body:
            want = re.search(r'content_sha256: "([0-9a-f]+)"', opt("--precondition") or "")
            if want and want.group(1) != hashlib.sha256(m["content"].encode()).hexdigest():
                sys.exit(1)
            m["content"] = open(body.split('"@', 1)[1].split('"', 1)[0]).read()
        json.dump(m, open(f, "w")); print("{}")
    else:
        print("{}")
else:
    print("{}")
'''

OLD_AGENT = "---\nname: %s\ntools: Bash, Read\n---\nold definition\n"


def rd(path):
    with open(path) as f:
        return f.read()


def w(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def fixture(t, project="alpha"):
    """An installation of the old names under t: home, config, state, a fake cloud. Returns the environment."""
    P = project
    home, conf, state, fake = [os.path.join(t, d) for d in ("home", "conf", "state", "fake")]
    for d in ("agents", "deployments", "environments", "stores", "memories"):
        os.makedirs(os.path.join(fake, d), exist_ok=True)
    os.makedirs(os.path.join(t, "bin"), exist_ok=True)
    w(os.path.join(t, "bin", "ant"), FAKE_ANT)
    os.chmod(os.path.join(t, "bin", "ant"), 0o755)
    # the old checkout's per-role agents, linked into the home as install.sh did
    for old in ("qargi-dev", "qargi-docs", "qargi-review", "qargi-test"):
        w(os.path.join(t, "oldqargi", "agents", old + ".md"), OLD_AGENT % old)
        os.makedirs(os.path.join(home, ".claude", "agents"), exist_ok=True)
        os.symlink(os.path.join(t, "oldqargi", "agents", old + ".md"), os.path.join(home, ".claude", "agents", old + ".md"))
    w(os.path.join(conf, "projects", P + ".json"), json.dumps({
        "schema": 1, "project": P, "repo": {"url": "https://github.com/example/%s" % P, "path": "", "long_lived": ["master", "develop"]},
        "roles": {r: {"base": "gh-pages" if r == "docs" else "@dispatcher", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high",
                      "apt": [], "skills": []} for r in ("dev", "docs", "review")},
        "lead": {"model": "claude-opus-5-5", "effort": "high"},
        "teams": {"code-docs": {"members": ["dev", "docs", "review"], "scopes": {"docs": ["site/"]}, "done": {"docs": "make lint"}}},
        "memory": {"memory_store": "memstore_M", "reference_store": "memstore_R"}, "budget_cents": 500}))
    w(os.path.join(conf, "profiles", P + ".md"), "profile\n")
    w(os.path.join(conf, "packs", "links.json"), json.dumps({"links": [{"pack": "skill:pdf", "scope": "project-role", "project": P, "role": "docs"}]}))
    res = [{"type": "memory_store", "memory_store_id": "memstore_M", "access": "read_write"},
           {"type": "memory_store", "memory_store_id": "memstore_R", "access": "read_only"}]
    reg = {}
    agents = {}
    for r in ("dev", "docs", "review", "lead"):
        aid, did = "agent_%s" % r, "depl_%s" % r
        agents[r] = aid
        reg["%s-%s" % (P, r)] = {"location": "cloud", "deployment_id": did, "environment_id": "env_1", "resources": res,
                                 "agent": {"id": aid, "version_pinned": 1}}
        ag = {"id": aid, "name": "%s-agent-%s" % (P, r), "version": 1, "system": "the prompt of the %s role" % r}
        if r == "lead":
            ag["multiagent"] = {"type": "coordinator", "agents": [{"type": "agent", "id": agents[m], "version": 1} for m in ("dev", "docs", "review")]}
        w(os.path.join(fake, "agents", aid + ".json"), json.dumps(ag))
        w(os.path.join(fake, "deployments", did + ".json"), json.dumps({"id": did, "name": "%s-deployment-%s" % (P, r), "agent": {"id": aid, "version": 1}, "resources": res}))
    w(os.path.join(conf, "instances.json"), json.dumps(reg))
    w(os.path.join(fake, "environments", "env_1.json"), json.dumps({"id": "env_1", "name": "%s-environment" % P}))
    for sid, name in (("memstore_M", P + "-memory"), ("memstore_R", P + "-reference")):
        w(os.path.join(fake, "stores", sid + ".json"), json.dumps({"id": sid, "name": name}))
    notes = {"memstore_M": {
        "/CANON.md": "# Canon\n\ncanon: 2\nkind: memory\nproject: %s\nroles: dev docs review lead\n" % P,
        "/README.md": "# %s memory\n\nRoles in this project:\n\n- `roles/dev/INDEX.md`: the dev role\n- `roles/docs/INDEX.md`: the docs role\n" % P,
        "/roles/dev/INDEX.md": "# dev memory index\n\nFacts for the dev role only. Paths are relative to `roles/dev/`.\n\n| Path | Purpose | Load |\n|---|---|---|\n| sandbox/go.md | Go toolchain | always |\n",
        "/roles/dev/sandbox/go.md": "# Go\n\nKind: sandbox\n",
        "/roles/docs/project/history.md": "# History\n\nsee roles/dev/sandbox/go.md\n",
        "/roles/review/INDEX.md": "# review memory index\n"},
        "memstore_R": {"/CANON.md": "# Canon\n\ncanon: 2\nkind: reference\nproject: %s\nroles: dev docs review lead\n" % P,
                       "/roles/docs/writing/conventions.md": "# Writing\n"}}
    for s, ns in notes.items():
        for n, (p, c) in enumerate(sorted(ns.items())):
            w(os.path.join(fake, "memories", s, "mem_%s_%d.json" % (s[-1], n)), json.dumps({"id": "mem_%s_%d" % (s[-1], n), "path": p, "content": c}))
    w(os.path.join(state, "sessions.json"), json.dumps({"sesn_1": {"instance": P + "-dev", "status": "archived"}}))
    os.makedirs(os.path.join(state, "definitions", P + "-dev"), exist_ok=True)
    env = dict(os.environ, HOME=home, QARGI_CONF=conf, QARGI_STATE=state, FAKE=fake, XDG_CONFIG_HOME=os.path.join(t, "xdgc"),
               XDG_STATE_HOME=os.path.join(t, "xdgs"), PATH=os.path.join(t, "bin") + os.pathsep + os.environ["PATH"])
    env.pop("QARGI_PROJECT", None)
    env.pop("FAKE_FAIL", None)
    return env


class Migrate(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.env = fixture(self.t)
        self.conf, self.state, self.fake = self.env["QARGI_CONF"], self.env["QARGI_STATE"], self.env["FAKE"]

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def q(self, *args, **extra):
        return subprocess.run([BIN, "migrate", "roles"] + list(args), capture_output=True, text=True, env=dict(self.env, **extra),
                              cwd=self.t, stdin=subprocess.DEVNULL)

    def token(self, out):
        line = [l for l in out.splitlines() if l.startswith("plan token: ")]
        self.assertTrue(line, out)
        return line[0].split()[2]

    def snapshot(self):
        out = {}
        for base in (self.conf, self.state, self.fake, self.env["HOME"]):
            for d, _, fs in os.walk(base):
                for f in fs:
                    p = os.path.join(d, f)
                    if f != "ant.log":
                        out[p] = os.readlink(p) if os.path.islink(p) else rd(p)
        return out

    def log(self):
        return rd(os.path.join(self.fake, "ant.log")).splitlines()

    def jd(self, *p):
        with open(os.path.join(*p)) as f:
            return json.load(f)

    def notes(self, store):
        d = os.path.join(self.fake, "memories", store)
        return {m["path"]: m["content"] for m in (self.jd(d, f) for f in os.listdir(d))}

    def apply(self):
        out = self.q().stdout
        return self.q("--apply", "--plan", self.token(out), "--asked", "migrate the roles")

    def test_the_plan_lists_every_step_and_changes_nothing(self):
        before = self.snapshot()
        r = self.q()
        self.assertEqual(r.returncode, 0, r.stderr)
        out = r.stdout
        for want in ("Roles: dev -> build, docs -> write", "qargi-dev -> builder (build)", "qargi-review -> reviewer (review)",
                     "registry:", "alpha-dev -> alpha-build", "alpha-docs -> alpha-write", "tracker:", "answers:", "pack links:",
                     "saved definitions:", "move   /roles/dev/sandbox/go.md -> /roles/build/sandbox/go.md",
                     "update /CANON.md", "ant beta:agents update --agent-id agent_dev --version 1 --name alpha-build",
                     "ant beta:deployments update --deployment-id depl_dev --name alpha-deployment-build",
                     "ant beta:agents update --agent-id agent_review --version 1 --name alpha-review",
                     "--name alpha-lead", "--multiagent <members agent_dev, agent_docs, agent_review",
                     "qargi agent add builder --abilities build", "qargi agent add tester --abilities test",
                     "remove %s" % os.path.join(self.env["HOME"], ".claude", "agents", "qargi-dev.md"), "--asked"):
            self.assertIn(want, out)
        self.assertEqual(self.snapshot(), before, "the plan changed something")
        self.assertFalse([l for l in self.log() if " update " in l], "the plan updated something in the cloud")

    def test_apply_needs_the_token_and_the_request(self):
        tok = self.token(self.q().stdout)
        r = self.q("--apply", "--plan", "000000000000", "--asked", "x")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("plan changed", r.stderr)
        r = self.q("--apply", "--plan", tok)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--asked", r.stderr)
        self.assertTrue(os.path.islink(os.path.join(self.env["HOME"], ".claude", "agents", "qargi-dev.md")))

    def test_apply_renames_everything_and_a_second_run_finds_nothing(self):
        r = self.apply()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        reg = self.jd(self.conf, "instances.json")
        self.assertEqual(sorted(reg), ["alpha-build", "alpha-lead", "alpha-review", "alpha-write"])
        ans = self.jd(self.conf, "projects", "alpha.json")
        self.assertEqual(sorted(ans["roles"]), ["build", "review", "write"])
        self.assertEqual(ans["teams"]["code-docs"], {"members": ["build", "write", "review"], "scopes": {"write": ["site/"]}, "done": {"write": "make lint"}})
        self.assertEqual(self.jd(self.conf, "packs", "links.json")["links"][0]["role"], "write")
        self.assertEqual(self.jd(self.state, "sessions.json")["sesn_1"]["instance"], "alpha-build")
        self.assertTrue(os.path.isdir(os.path.join(self.state, "definitions", "alpha-build")))
        m = self.notes("memstore_M")
        self.assertIn("/roles/build/sandbox/go.md", m)
        self.assertFalse([p for p in m if p.startswith(("/roles/dev/", "/roles/docs/"))])
        self.assertIn("roles: build write review lead", m["/CANON.md"])
        self.assertIn("- `roles/write/INDEX.md`: the write role", m["/README.md"])
        self.assertTrue(m["/roles/build/INDEX.md"].startswith("# build memory index\n\nFacts for the build role only. Paths are relative to `roles/build/`."))
        self.assertIn("see roles/build/sandbox/go.md", m["/roles/write/project/history.md"])
        self.assertIn("/roles/write/writing/conventions.md", self.notes("memstore_R"))
        names = {f[:-5]: self.jd(self.fake, "agents", f) for f in os.listdir(os.path.join(self.fake, "agents"))}
        self.assertEqual({k: v["name"] for k, v in names.items()},
                         {"agent_dev": "alpha-build", "agent_docs": "alpha-write", "agent_review": "alpha-review", "agent_lead": "alpha-lead"})
        self.assertIn("Your role is build", names["agent_dev"]["system"])
        self.assertIn("Role: build", names["agent_dev"]["system"])
        self.assertEqual(sorted((x["id"], x["version"]) for x in names["agent_lead"]["multiagent"]["agents"]),
                         sorted((k, names[k]["version"]) for k in ("agent_dev", "agent_docs", "agent_review")))
        deps = {f[:-5]: self.jd(self.fake, "deployments", f) for f in os.listdir(os.path.join(self.fake, "deployments"))}
        self.assertEqual(deps["depl_docs"]["name"], "alpha-deployment-write")
        self.assertEqual(deps["depl_dev"]["agent"]["version"], names["agent_dev"]["version"])
        self.assertEqual(reg["alpha-build"]["agent"]["version_pinned"], names["agent_dev"]["version"])
        verbs = {tuple(l.split()[:2]) for l in self.log() if l.startswith("beta:")}
        self.assertFalse([v for v in verbs if v[1:] and v[1] in ("archive", "delete", "create")], "renaming is an update: %s" % sorted(verbs))
        adir = os.path.join(self.env["HOME"], ".claude", "agents")
        self.assertEqual(sorted(os.listdir(adir)), ["builder.md", "reviewer.md", "tester.md", "writer.md"])
        members = self.jd(self.conf, "agents.json")
        self.assertEqual({k: v["abilities"] for k, v in members.items()}, {"builder": ["build"], "writer": ["write"], "reviewer": ["review"], "tester": ["test"]})
        again = self.q()
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertIn("nothing to migrate", again.stdout)
        self.assertNotIn("plan token", again.stdout)
        self.assertEqual(subprocess.run([BIN, "agent", "for", "review"], capture_output=True, text=True, env=self.env).stdout.split()[0], "reviewer")

    def test_member_names_are_the_users(self):
        out = self.q("--member-names", "build=forge,write=scribe").stdout
        self.assertIn("qargi-dev -> forge (build)", out)
        self.assertIn("qargi agent add scribe --abilities write", out)
        self.assertIn("--member-names build=forge,write=scribe", out)
        self.assertNotEqual(self.q("--member-names", "build=Forge").returncode, 0)
        self.assertNotEqual(self.q("--member-names", "build=x,write=x").returncode, 0)

    def test_a_failure_in_the_middle_stops_and_a_rerun_finishes(self):
        out = self.q().stdout
        r = self.q("--apply", "--plan", self.token(out), "--asked", "migrate the roles", FAKE_FAIL="--deployment-id depl_docs --name")
        self.assertEqual(r.returncode, 1)
        self.assertIn("stopped at step", r.stderr)
        self.assertIn("alpha-write", r.stderr)
        self.assertEqual(sorted(self.jd(self.conf, "instances.json")), ["alpha-build", "alpha-lead", "alpha-review", "alpha-write"])
        self.assertTrue(os.path.islink(os.path.join(self.env["HOME"], ".claude", "agents", "qargi-dev.md")), "a later step ran after the failure")
        rest = self.q()
        self.assertNotIn("registry:", rest.stdout)
        self.assertNotIn("move   /roles/dev/", rest.stdout)
        self.assertNotIn("--agent-id agent_dev --version 1 --name", rest.stdout)
        self.assertIn("--name alpha-deployment-write", rest.stdout)
        r = self.q("--apply", "--plan", self.token(rest.stdout), "--asked", "migrate the roles")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("nothing to migrate", self.q().stdout)
        self.assertEqual(self.jd(self.fake, "deployments", "depl_docs.json")["name"], "alpha-deployment-write")

    def test_a_local_only_installation_needs_no_request(self):
        shutil.rmtree(self.fake)
        os.makedirs(os.path.join(self.fake, "memories"))
        self.jd(self.conf, "projects", "alpha.json")
        p = os.path.join(self.conf, "projects", "alpha.json")
        a = self.jd(p); a["memory"] = {"memory_store": "", "reference_store": ""}
        w(p, json.dumps(a)); w(os.path.join(self.conf, "instances.json"), "{}")
        out = self.q().stdout
        self.assertNotIn("--asked", out.splitlines()[-1])
        r = self.q("--apply", "--plan", self.token(out))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.jd(p)["roles"]), ["build", "review", "write"])


if __name__ == "__main__":
    if sys.argv[1:2] == ["fixture"]:
        os.makedirs(sys.argv[2], exist_ok=True)
        e = fixture(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "alpha")
        for k in ("HOME", "QARGI_CONF", "QARGI_STATE", "FAKE", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "PATH"):
            print("export %s=%s" % (k, e[k]))
        sys.exit(0)
    unittest.main()
