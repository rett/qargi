#!/usr/bin/env python3
"""qargi export / import: offline, with a fake ant, real gpg in a throwaway home and scripted terminal answers."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, io, json, os, shutil, stat, subprocess, sys, tarfile, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")

FAKE_ANT = r'''#!/usr/bin/env python3
import hashlib, json, os, sys
fake = os.environ["FAKE"]
a = sys.argv[1:]
def opt(k):
    return a[a.index(k) + 1] if k in a else ""
with open(os.path.join(fake, "ant.log"), "a") as f:
    f.write(" ".join(a) + "\n")
def store(s):
    d = os.path.join(fake, "stores", s); os.makedirs(d, exist_ok=True); return d
cmd = a[0] if a else ""
if cmd == "beta:memory-stores:memories":
    verb, s = a[1], opt("--memory-store-id")
    d = store(s)
    if verb == "list":
        for fn in sorted(os.listdir(d)):
            print(json.dumps(json.load(open(os.path.join(d, fn))), indent=2))
    elif verb in ("create", "update"):
        body = sys.stdin.read()
        src = body.split('"@', 1)[1].split('"', 1)[0]
        path = opt("--path")
        mid = opt("--memory-id")
        if verb == "update":
            for fn in os.listdir(d):
                m = json.load(open(os.path.join(d, fn)))
                if m["id"] == mid: path = m["path"]
        mid = mid or "mem_" + hashlib.sha1(path.encode()).hexdigest()[:10]
        json.dump({"id": mid, "path": path, "content": open(src).read()}, open(os.path.join(d, mid + ".json"), "w"))
    elif verb == "delete":
        os.remove(os.path.join(d, opt("--memory-id") + ".json"))
elif cmd == "beta:agents":
    print(json.dumps({"id": opt("--agent-id"), "version": 3, "system": "prompt text", "authorization_token": "SECRETAGENT", "mcp_servers": [{"name": "github", "url": "u"}]}))
elif cmd == "beta:deployments":
    print(json.dumps({"id": opt("--deployment-id"), "resources": [{"type": "github_repository", "authorization_token": "SECRETDEPLOY", "url": "https://example.net/r"}]}))
elif cmd == "beta:environments":
    print(json.dumps({"id": opt("--environment-id"), "name": "alpha-environment"}))
'''


def rd(path):
    with open(path) as f:
        return f.read()


def jd(path):
    with open(path) as f:
        return json.load(f)


class Env(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.conf, self.state, self.fake = [os.path.join(self.t, d) for d in ("c", "s", "fake")]
        for d in (self.conf, self.state, self.fake, os.path.join(self.t, "bin"), os.path.join(self.t, "gnupg")):
            os.makedirs(d)
        os.chmod(os.path.join(self.t, "gnupg"), 0o700)
        with open(os.path.join(self.t, "bin", "ant"), "w") as f:
            f.write(FAKE_ANT)
        os.chmod(os.path.join(self.t, "bin", "ant"), 0o755)
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=self.state, FAKE=self.fake, GNUPGHOME=os.path.join(self.t, "gnupg"),
                        PATH=os.path.join(self.t, "bin") + os.pathsep + os.environ["PATH"])
        self.env.pop("QARGI_PROJECT", None)
        self.seed(self.conf, self.state)
        self.put_store(self.fake, "memstore_A", {"/README.md": "memory readme", "/roles/build/x.md": "build note"})
        self.put_store(self.fake, "memstore_B", {"/README.md": "reference readme"})

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def seed(self, conf, state):
        w = self.write
        w(os.path.join(conf, "projects", "alpha.json"), json.dumps({"project": "alpha", "repo": {"path": "/x/alpha"}, "memory": {"memory_store": "memstore_A", "reference_store": "memstore_B"}}))
        w(os.path.join(conf, "projects", "beta.json"), json.dumps({"project": "beta", "memory": {}}))
        w(os.path.join(conf, "instances.json"), json.dumps({
            "alpha-build": {"location": "cloud", "agent": {"id": "agent_1", "version_pinned": 3}, "deployment_id": "depl_1", "environment_id": "env_1"},
            "alpha-write": {"location": "cloud", "agent": {"id": "agent_2"}, "deployment_id": "depl_2", "environment_id": "env_1"},
            "beta-build": {"location": "local"}}))
        w(os.path.join(conf, "profiles", "alpha.md"), "profile text")
        w(os.path.join(conf, "packs", "links.json"), '{"links":[]}')
        w(os.path.join(conf, "credentials", "alpha-lead-push"), "TOKEN-VALUE-1234")
        w(os.path.join(state, "sessions.json"), json.dumps({"sesn_1": {"instance": "alpha-build", "status": "idle"}}))
        w(os.path.join(state, "audit.log"), '{"verb":"one"}\n{"verb":"two"}\n')

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def put_store(self, fake, store, notes):
        d = os.path.join(fake, "stores", store)
        os.makedirs(d, exist_ok=True)
        for path, content in notes.items():
            mid = "mem_" + hashlib.sha1(path.encode()).hexdigest()[:10]
            with open(os.path.join(d, mid + ".json"), "w") as f:
                json.dump({"id": mid, "path": path, "content": content}, f)

    def store_notes(self, store):
        d = os.path.join(self.fake, "stores", store)
        out = {}
        for fn in os.listdir(d) if os.path.isdir(d) else []:
            m = jd(os.path.join(d, fn))
            out[m["path"]] = m["content"]
        return out

    def qargi(self, args, answers=None, env=None):
        e = dict(self.env, **(env or {}))
        if answers is not None:
            self.write(os.path.join(self.t, "in"), "".join(a + "\n" for a in answers))
            open(os.path.join(self.t, "out"), "w").close()
            e["QARGI_TTY_IN"], e["QARGI_TTY_OUT"] = os.path.join(self.t, "in"), os.path.join(self.t, "out")
        else:
            e["QARGI_TTY_IN"] = e["QARGI_TTY_OUT"] = "/nonexistent"
        return subprocess.run([BIN] + args, capture_output=True, text=True, env=e, cwd=self.t, stdin=subprocess.DEVNULL)

    def export(self, name="a.tar.gz", extra=()):
        r = self.qargi(["export", "--only", "config,definitions,memories,state", "--no-encrypt", "--out", os.path.join(self.t, name)] + list(extra))
        self.assertEqual(r.returncode, 0, r.stderr)
        return os.path.join(self.t, name)

    def members(self, path):
        with tarfile.open(path) as tf:
            return {m.name: tf.extractfile(m).read() for m in tf if m.isreg()}

    def fresh_target(self):
        """A second machine: empty config and state, the same fake cloud (separate stores)."""
        conf, state, fake = [os.path.join(self.t, d) for d in ("c2", "s2", "fake2")]
        for d in (conf, state, fake):
            os.makedirs(d)
        self.write(os.path.join(conf, "projects", "alpha.json"), json.dumps({"project": "alpha", "memory": {"memory_store": "memstore_A", "reference_store": "memstore_B"}}))
        return dict(QARGI_CONF=conf, QARGI_STATE=state, FAKE=fake), conf, state, fake


class Export(Env):
    def test_archive_holds_the_selected_parts_with_a_manifest(self):
        path = self.export()
        m = self.members(path)
        manifest = json.loads(m.pop("manifest.json"))
        self.assertEqual(manifest["format"], 1)
        self.assertEqual(sorted(manifest["projects"]), ["alpha", "beta"])
        self.assertEqual(set(m), set(manifest["files"]))
        for p, data in m.items():
            self.assertEqual(hashlib.sha256(data).hexdigest(), manifest["files"][p]["sha256"])
        for want in ("config/projects/alpha.json", "config/instances/alpha-build.json", "config/profiles/alpha.md", "config/packs/links.json",
                     "definitions/alpha-build/agent.json", "definitions/alpha-write/deployment.json", "definitions/alpha-build/environment.json",
                     "memories/alpha/memory/roles/build/x.md", "memories/alpha/reference/README.md", "state/sessions/sesn_1.json", "state/audit.log"):
            self.assertIn(want, m)
        self.assertFalse(any(k.startswith("credentials/") for k in m), "credentials are not in the default selection")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o600)

    def test_secrets_are_removed_from_the_definitions(self):
        m = self.members(self.export())
        blob = b"".join(v for k, v in m.items() if k.startswith("definitions/"))
        self.assertNotIn(b"SECRETAGENT", blob)
        self.assertNotIn(b"SECRETDEPLOY", blob)
        self.assertIn(b"<removed>", blob)
        self.assertIn(b"https://example.net/r", blob)   # the rest stays

    def test_one_project_only(self):
        m = self.members(self.export(extra=["--project", "beta"]))
        self.assertTrue(any(k == "config/projects/beta.json" for k in m))
        self.assertFalse(any("alpha" in k for k in m))

    def test_credentials_need_a_password(self):
        r = self.qargi(["export", "--only", "credentials", "--no-encrypt", "--out", os.path.join(self.t, "c.tgz")])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("give a password", r.stderr)
        self.assertFalse(os.path.exists(os.path.join(self.t, "c.tgz")))

    def test_encrypted_archive_is_not_readable_without_the_password(self):
        self.write(os.path.join(self.t, "pw"), "correct horse\n")
        out = os.path.join(self.t, "e.tar.gz.gpg")
        r = self.qargi(["export", "--only", "config,credentials", "--password-file", os.path.join(self.t, "pw"), "--out", out])
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(out, "rb") as fh:
            raw = fh.read()
        self.assertFalse(raw.startswith(b"\x1f\x8b"))
        self.assertNotIn(b"TOKEN-VALUE-1234", raw)
        self.assertNotIn(b"alpha", raw)
        d = subprocess.run(["gpg", "--batch", "--quiet", "--pinentry-mode", "loopback", "--passphrase", "correct horse", "-d", out], capture_output=True, env=self.env)
        self.assertEqual(d.returncode, 0, d.stderr)
        with tarfile.open(fileobj=io.BytesIO(d.stdout)) as tf:
            self.assertIn("credentials/alpha-lead-push", tf.getnames())

    def test_interactive_export_asks_what_and_for_a_password_twice(self):
        out = os.path.join(self.t, "i.tar.gz.gpg")
        r = self.qargi(["export", "--out", out], answers=["alpha", "config, 3", "one", "two", "right", "right"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("encrypted", r.stdout)
        said = rd(os.path.join(self.t, "out"))
        self.assertIn("credentials", said)           # the list of parts was shown
        self.assertNotIn("right", said)              # the password is never echoed
        self.assertIn("did not match", r.stderr)
        r = self.qargi(["import", out, "--dry-run", "--password-file", self._pw("right")])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("config", r.stdout)
        self.assertIn("memories", r.stdout)
        self.assertNotIn("definitions   ", r.stdout)

    def test_needs_an_explicit_choice_without_a_terminal(self):
        r = self.qargi(["export", "--only", "config", "--out", os.path.join(self.t, "n.tgz")])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--no-encrypt", r.stderr)
        r = self.qargi(["export", "--no-encrypt"])
        self.assertIn("say what to export", r.stderr)

    def test_a_relative_file_name_and_the_default_name_work(self):
        r = self.qargi(["export", "--only", "config", "--no-encrypt", "--out", "rel.tar.gz"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.exists(os.path.join(self.t, "rel.tar.gz")))
        r = self.qargi(["export", "--only", "config", "--no-encrypt"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(any(f.startswith("qargi-export-") and f.endswith(".tar.gz") for f in os.listdir(self.t)))

    def test_never_overwrites_a_file(self):
        p = self.export()
        r = self.qargi(["export", "--only", "config", "--no-encrypt", "--out", p])
        self.assertNotEqual(r.returncode, 0)

    def _pw(self, text):
        p = os.path.join(self.t, "pwf")
        self.write(p, text + "\n")
        return p


class Import(Env):
    def target(self):
        t, conf, state, fake = self.fresh_target()
        self.put_store(fake, "memstore_A", {})
        self.put_store(fake, "memstore_B", {})
        return t, conf, state, fake

    def run_import(self, archive, answers, extra=(), env=None):
        return self.qargi(["import", archive] + list(extra), answers=answers, env=env)

    def test_dry_run_changes_nothing_and_needs_no_terminal(self):
        a = self.export()
        t, conf, state, fake = self.target()
        r = self.qargi(["import", a, "--dry-run"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dry run", r.stdout)
        self.assertRegex(r.stdout, r"memories +mode merge +add 3,")
        self.assertFalse(os.path.exists(os.path.join(conf, "instances.json")))
        self.assertEqual(self.store_notes_at(fake, "memstore_A"), {})

    def store_notes_at(self, fake, store):
        d = os.path.join(fake, "stores", store)
        return {jd(os.path.join(d, f))["path"]: jd(os.path.join(d, f))["content"] for f in os.listdir(d)}

    def test_refuses_to_change_anything_without_a_terminal(self):
        a = self.export()
        r = self.qargi(["import", a])
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--dry-run", r.stderr)

    def test_merge_into_an_empty_machine_with_a_confirmation(self):
        a = self.export()
        t, conf, state, fake = self.target()
        # parts: config, definitions, memories (by name); projects: alpha; modes: Enter (merge) for each; confirm
        r = self.run_import(a, ["config,memories", "alpha", "", "", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        inst = jd(os.path.join(conf, "instances.json"))
        self.assertEqual(sorted(inst), ["alpha-build", "alpha-write"])
        self.assertTrue(os.path.exists(os.path.join(conf, "profiles", "alpha.md")))
        self.assertEqual(self.store_notes_at(fake, "memstore_A")["/roles/build/x.md"], "build note")
        self.assertIn('"verb": "import"', rd(os.path.join(state, "audit.log")))
        self.assertIn("interactive: confirmed at the terminal", rd(os.path.join(state, "audit.log")))

    def test_an_archive_made_with_the_old_role_names_is_imported_under_the_new_ones(self):
        self.write(os.path.join(self.conf, "instances.json"), json.dumps({"alpha-dev": {"location": "cloud", "agent": {"id": "agent_1"}, "deployment_id": "depl_1", "environment_id": "env_1"},
                                                                          "alpha-review": {"location": "local"}}))
        self.write(os.path.join(self.conf, "projects", "alpha.json"), json.dumps({"project": "alpha", "repo": {"path": "/x/alpha"}, "roles": {"dev": {}, "docs": {}},
            "teams": {"t": {"members": ["dev", "docs"], "done": {"docs": "make lint"}}}, "memory": {"memory_store": "memstore_A", "reference_store": "memstore_B"}}))
        self.write(os.path.join(self.conf, "packs", "links.json"), json.dumps({"links": [{"pack": "skill:pdf", "scope": "user-role", "role": "docs"}]}))
        self.write(os.path.join(self.state, "sessions.json"), json.dumps({"sesn_1": {"instance": "alpha-dev", "status": "idle"}}))
        shutil.rmtree(os.path.join(self.fake, "stores", "memstore_A"))
        self.put_store(self.fake, "memstore_A", {"/CANON.md": "canon: 2\nroles: dev docs\n", "/roles/dev/INDEX.md": "# dev memory index\n\nFacts for the dev role only.\n"})
        a = self.export()
        t, conf, state, fake = self.target()
        r = self.run_import(a, ["config,memories,state", "alpha", "2", "", "", "y"], env=t)   # config: overwrite (the target has answers)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("role names before dev became build", r.stdout)
        self.assertEqual(sorted(jd(os.path.join(conf, "instances.json"))), ["alpha-build", "alpha-review"])
        ans = jd(os.path.join(conf, "projects", "alpha.json"))
        self.assertEqual((sorted(ans["roles"]), ans["teams"]["t"]), (["build", "write"], {"members": ["build", "write"], "done": {"write": "make lint"}}))
        self.assertEqual(jd(os.path.join(conf, "packs", "links.json"))["links"][0]["role"], "write")
        self.assertEqual(jd(os.path.join(state, "sessions.json"))["sesn_1"]["instance"], "alpha-build")
        notes = self.store_notes_at(fake, "memstore_A")
        self.assertEqual(notes["/roles/build/INDEX.md"], "# build memory index\n\nFacts for the build role only.\n")
        self.assertIn("roles: build write", notes["/CANON.md"])
        self.assertNotIn("/roles/dev/INDEX.md", notes)

    def test_merge_keeps_what_differs_overwrite_replaces_it_with_a_backup(self):
        a = self.export()
        t, conf, state, fake = self.target()
        self.write(os.path.join(conf, "profiles", "alpha.md"), "my own profile")
        r = self.run_import(a, ["config", "alpha", "1", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(rd(os.path.join(conf, "profiles", "alpha.md")), "my own profile")
        r = self.run_import(a, ["config", "alpha", "2", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertEqual(rd(os.path.join(conf, "profiles", "alpha.md")), "profile text")
        backups = [os.path.join(dp, f) for dp, _, fs in os.walk(os.path.join(state, "backups")) for f in fs]
        self.assertTrue(any(rd(b) == "my own profile" for b in backups), backups)

    def test_replace_removes_what_the_archive_lacks_only_after_typing_replace(self):
        a = self.export()
        t, conf, state, fake = self.target()
        self.write(os.path.join(conf, "instances.json"), json.dumps({"alpha-old": {"location": "local"}, "alpha-build": {"location": "local"}}))
        self.put_store(fake, "memstore_A", {"/stale.md": "stale", "/README.md": "other"})
        r = self.run_import(a, ["config,memories", "alpha", "3", "3", "no", "y"], env=t)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("alpha-old", jd(os.path.join(conf, "instances.json")))   # nothing removed
        self.assertIn("/stale.md", self.store_notes_at(fake, "memstore_A"))
        r = self.run_import(a, ["config,memories", "alpha", "3", "3", "replace", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        inst = jd(os.path.join(conf, "instances.json"))
        self.assertEqual(sorted(inst), ["alpha-build", "alpha-write"])
        notes = self.store_notes_at(fake, "memstore_A")
        self.assertNotIn("/stale.md", notes)
        self.assertEqual(notes["/README.md"], "memory readme")
        backups = "".join(rd(os.path.join(dp, f)) for dp, _, fs in os.walk(os.path.join(state, "backups")) for f in fs)
        self.assertIn("stale", backups)

    def test_password_is_asked_for_and_retried(self):
        self.write(os.path.join(self.t, "pw"), "s3cret\n")
        enc = os.path.join(self.t, "e.gpg")
        self.assertEqual(self.qargi(["export", "--only", "config", "--password-file", os.path.join(self.t, "pw"), "--out", enc]).returncode, 0)
        t, conf, state, fake = self.target()
        r = self.run_import(enc, ["wrong", "s3cret", "config", "alpha", "", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        self.assertIn("does not open it", r.stderr)
        self.assertTrue(os.path.exists(os.path.join(conf, "instances.json")))
        r = self.run_import(enc, ["a", "b", "c"], env=t)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("three tries", r.stderr)

    def test_credentials_come_back_mode_600_and_their_value_is_never_printed(self):
        self.write(os.path.join(self.t, "pw"), "pw1\n")
        enc = os.path.join(self.t, "c.gpg")
        self.assertEqual(self.qargi(["export", "--only", "credentials", "--password-file", os.path.join(self.t, "pw"), "--out", enc]).returncode, 0)
        t, conf, state, fake = self.target()
        r = self.run_import(enc, ["credentials", "alpha", "", "y"], extra=["--password-file", os.path.join(self.t, "pw")], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        f = os.path.join(conf, "credentials", "alpha-lead-push")
        self.assertEqual(rd(f), "TOKEN-VALUE-1234")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(os.path.dirname(f)).st_mode), 0o700)
        self.assertNotIn("TOKEN-VALUE-1234", r.stdout + r.stderr + rd(os.path.join(self.t, "out")))

    def test_audit_log_is_only_ever_appended_to(self):
        a = self.export()
        t, conf, state, fake = self.target()
        self.write(os.path.join(state, "audit.log"), '{"verb":"mine"}\n{"verb":"one"}\n')
        r = self.run_import(a, ["state", "alpha", "3", "y"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
        lines = rd(os.path.join(state, "audit.log")).splitlines()
        self.assertEqual(lines[0], '{"verb":"mine"}')
        self.assertEqual(lines.count('{"verb":"one"}'), 1)
        self.assertIn('{"verb":"two"}', lines)

    def test_a_project_subset_and_a_part_subset(self):
        a = self.export()
        t, conf, state, fake = self.target()
        r = self.qargi(["import", a, "--only", "config", "--project", "beta", "--mode", "overwrite", "--dry-run"], env=t)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("beta", r.stdout)
        self.assertNotIn("alpha-build", r.stdout)


class Hostile(Env):
    def archive(self, entries, manifest_files=None, fmt=1):
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            files = {}
            for name, data in entries:
                if isinstance(data, tarfile.TarInfo):
                    tf.addfile(data); continue
                ti = tarfile.TarInfo(name); ti.size = len(data); tf.addfile(ti, io.BytesIO(data))
                files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size": len(data), "project": "alpha"}
            m = json.dumps({"format": fmt, "projects": ["alpha"], "components": {"config": 1}, "files": manifest_files if manifest_files is not None else files}).encode()
            ti = tarfile.TarInfo("manifest.json"); ti.size = len(m); tf.addfile(ti, io.BytesIO(m))
        p = os.path.join(self.t, "h.tar.gz")
        with open(p, "wb") as f:
            f.write(buf.getvalue())
        return p

    def dry(self, p):
        return self.qargi(["import", p, "--dry-run"])

    def test_path_traversal_and_absolute_names_are_refused(self):
        for name in ("../evil", "config/../../evil", "/etc/x"):
            r = self.dry(self.archive([(name, b"x")]))
            self.assertNotEqual(r.returncode, 0, name)
            self.assertIn("refusing", r.stderr)

    def test_links_and_unknown_folders_are_refused(self):
        ti = tarfile.TarInfo("config/projects/alpha.json"); ti.type = tarfile.SYMTYPE; ti.linkname = "/etc/passwd"
        r = self.dry(self.archive([("config/projects/alpha.json", ti)]))
        self.assertIn("refusing", r.stderr)
        r = self.dry(self.archive([("elsewhere/x", b"x")]))
        self.assertIn("outside the known folders", r.stderr)

    def test_a_changed_file_fails_its_checksum(self):
        p = self.archive([("config/profiles/a.md", b"one")], manifest_files={"config/profiles/a.md": {"sha256": "0" * 64, "size": 3, "project": "alpha"}})
        self.assertIn("checksum", self.dry(p).stderr)

    def test_files_missing_from_or_extra_to_the_manifest_are_refused(self):
        p = self.archive([("config/profiles/a.md", b"one")], manifest_files={})
        self.assertIn("disagree", self.dry(p).stderr)

    def test_invalid_names_for_their_folder_are_refused(self):
        r = self.dry(self.archive([("config/projects/Bad Name.json", b"{}")]))
        self.assertIn("not valid for its folder", r.stderr)
        r = self.dry(self.archive([("credentials/a/b", b"x")]))
        self.assertIn("not valid for its folder", r.stderr)

    def test_a_newer_format_and_a_non_archive_are_refused(self):
        self.assertIn("format 2", self.dry(self.archive([("config/profiles/a.md", b"x")], fmt=2)).stderr)
        p = os.path.join(self.t, "junk")
        self.write(p, "not an archive")
        self.assertNotEqual(self.dry(p).returncode, 0)


if __name__ == "__main__":
    unittest.main()
