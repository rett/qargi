#!/usr/bin/env python3
"""lib/tools.py: the tools a role declares (roles.<role>.tools). What an entry needs, the one list across roles, where a tool is and
whether it is the declared one (a fake go, a file and its sha256), and the offline submodule checkout qargi local prepare runs.
Offline. Run: python3 tests/test_tools.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import tools as T  # noqa: E402

FAKE_GO = os.path.join(ROOT, "tests", "fixtures", "fake-go.sh")
SYSTEM_PATH = "/usr/bin:/bin"                    # where the system tools the fake go runs are looked up; never a place to look for a go
GO = {"kind": "go", "name": "github.com/acme/lint/cmd/acme-lint", "version": "v1.2.0"}
BIN = {"kind": "binary", "name": "acme-fmt", "version": "2.0.1", "url": "https://downloads.example.test/acme-fmt-2.0.1", "sha256": "0" * 64}
SUB = {"kind": "submodule", "name": "acme-test", "path": "vendor/acme-test"}
GIT_ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.test", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.test",
               GIT_CONFIG_GLOBAL="/dev/null", GIT_CONFIG_NOSYSTEM="1")


def git(*a, cwd=None):
    r = subprocess.run(["git", "-c", "protocol.file.allow=always", *a], cwd=cwd, env=GIT_ENV, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise AssertionError("git %s: %s" % (" ".join(a), r.stderr))
    return r.stdout.strip()


class Answers(unittest.TestCase):
    def test_what_each_kind_needs(self):
        self.assertEqual(T.problems("roles.build", None), [])
        self.assertEqual(T.problems("roles.build", [GO, BIN, SUB]), [])
        bad = T.problems("roles.build", "go")
        self.assertEqual(len(bad), 1)
        self.assertIn("roles.build.tools: a list", bad[0])
        for entry, word in (({"kind": "apt", "name": "jq"}, "kind go, binary or submodule"), ("jq", "an object"),
                            (dict(GO, version="latest"), "tagged version"), (dict(GO, name="github.com/acme/lint@v1"), "no @version"),
                            (dict(GO, extra=1), "unknown key extra"), ({"kind": "go", "name": "x"}, "needs version"),
                            (dict(BIN, sha256="abc"), "64 hex digits"), (dict(BIN, url="ftp://x/y"), "http(s) URL"), (dict(BIN, name="a/b"), "file name"),
                            (dict(SUB, path="/vendor/x"), "relative"), (dict(SUB, path="vendor/../x"), "no .. segment"), ({"kind": "submodule", "name": "x"}, "needs path")):
            bad = T.problems("roles.test", [entry])
            self.assertTrue(bad and word in bad[0], (entry, bad))
            self.assertTrue(bad[0].startswith("roles.test.tools[0]"), bad)
        bad = T.problems("roles.build", [GO, dict(GO, version="v1.3.0")])
        self.assertIn("listed twice", bad[0])

    def test_the_same_tool_in_two_roles_must_agree(self):
        roles = {"build": {"tools": [GO, SUB]}, "test": {"tools": [dict(GO, version="v1.3.0"), SUB]}}
        bad = T.conflicts(roles)
        self.assertEqual(len(bad), 1, bad)
        self.assertIn("roles.build.tools and roles.test.tools declare go github.com/acme/lint/cmd/acme-lint differently", bad[0])
        self.assertEqual(T.conflicts({"build": {"tools": [GO]}, "test": {"tools": [GO, BIN]}}), [])
        self.assertEqual(T.conflicts({"build": {"tools": "broken"}, "test": {"tools": [GO]}}), [])   # a list that is not valid is reported by problems, not here

    def test_declared_is_one_list_with_the_roles_of_each(self):
        a = {"roles": {"test": {"tools": [SUB, GO]}, "build": {"tools": [GO, BIN]}, "write": {"apt": ["groff"]}}}
        d = T.declared(a)
        self.assertEqual([(t["kind"], t["roles"]) for t in d], [("go", ["build", "test"]), ("binary", ["build"]), ("submodule", ["test"])])
        self.assertEqual([t["path"] for t in T.declared(a, "test") if t["kind"] == "submodule"], ["vendor/acme-test"])
        self.assertEqual(T.declared({}), [])
        self.assertEqual(T.declared({"roles": {"build": {"tools": [{"kind": "go"}]}}}), [])

    def test_binary_name_of_a_go_tool(self):
        self.assertEqual(T.binary_name(GO), "acme-lint")
        self.assertEqual(T.binary_name({"kind": "go", "name": "github.com/acme/tool/v2", "version": "v2.0.0"}), "tool")
        self.assertEqual(T.binary_name(BIN), "acme-fmt")


class Status(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.bin = os.path.join(self.t, "fakebin")
        os.makedirs(self.bin)
        shutil.copy(FAKE_GO, os.path.join(self.bin, "go"))
        os.chmod(os.path.join(self.bin, "go"), 0o755)
        self.gobin = os.path.join(self.t, "gobin")
        self.saved = dict(os.environ)
        os.environ.update(HOME=self.t, PATH=self.bin + os.pathsep + SYSTEM_PATH, GOBIN=self.gobin)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.t, ignore_errors=True)

    def go_install(self, pkg_at_version):
        subprocess.run([os.path.join(self.bin, "go"), "install", pkg_at_version], check=True, env=dict(os.environ))

    def test_a_go_tool_missing_wrong_off_path_and_ok(self):
        t = dict(GO, roles=["build"])
        state, text = T.status(t)
        self.assertEqual(state, "missing")
        self.assertIn("acme-lint is not installed (roles build: go github.com/acme/lint/cmd/acme-lint@v1.2.0", text)
        self.go_install("github.com/acme/lint/cmd/acme-lint@v1.1.0")
        state, text = T.status(t)
        self.assertEqual(state, "wrong")
        self.assertIn("is v1.1.0; roles build pins v1.2.0", text)
        self.go_install("github.com/acme/lint/cmd/acme-lint@v1.2.0")
        state, text = T.status(t)                                           # GOBIN is not on PATH
        self.assertEqual(state, "path")
        self.assertIn("acme-lint v1.2.0 is installed in %s, which is not on PATH" % self.gobin, text)
        os.environ["PATH"] = self.gobin + os.pathsep + os.environ["PATH"]
        self.assertEqual(T.status(t)[0], "ok")
        with open(os.path.join(self.gobin, "acme-lint"), "w") as f:         # a file of that name that go did not build
            f.write("#!/bin/sh\n")
        os.unlink(os.path.join(self.gobin, ".acme-lint.mod"))
        state, text = T.status(t)
        self.assertEqual(state, "wrong")
        self.assertIn("is not a go build of github.com/acme/lint/cmd/acme-lint", text)

    def reduced_path(self, with_go):
        """A PATH of the tool's own directory and one fresh directory that holds only what the fake go runs (links to the system's tools)
        and, with_go, the fake go. Nothing of the host is on it, so whether the host has a go (a CI runner does) cannot change a result."""
        d = os.path.join(self.t, "reduced-go" if with_go else "reduced-nogo")
        os.makedirs(d)
        for name in ("sh", "dirname", "basename", "mkdir", "chmod"):
            os.symlink(shutil.which(name, path=SYSTEM_PATH), os.path.join(d, name))
        if with_go:
            shutil.copy(FAKE_GO, os.path.join(d, "go"))
            os.chmod(os.path.join(d, "go"), 0o755)
        return self.gobin + os.pathsep + d

    def test_the_version_of_an_installed_tool_is_read_with_go_and_only_noted_without(self):
        t = dict(GO, roles=["build"])
        self.go_install("github.com/acme/lint/cmd/acme-lint@v1.2.0")
        os.environ["PATH"] = self.reduced_path(True)                        # go is there: the version is read
        state, text = T.status(t)
        self.assertEqual(state, "ok", text)
        self.assertEqual(T.status(dict(t, version="v1.3.0"))[0], "wrong")
        os.environ["PATH"] = self.reduced_path(False)                       # go is not: the tool is found, its version cannot be read
        state, text = T.status(t)
        self.assertEqual(state, "note", text)
        self.assertIn("go is not on PATH", text)
        self.assertEqual(T.status(dict(t, version="v1.3.0"))[0], "note")

    def test_a_binary_is_the_file_its_sha256_names(self):
        d = os.path.join(self.t, ".local", "bin")
        os.makedirs(d)
        p = os.path.join(d, "acme-fmt")
        with open(p, "wb") as f:
            f.write(b"#!/bin/sh\necho 2.0.1\n")
        os.chmod(p, 0o755)
        good = dict(BIN, sha256=T.sha256_of(p), roles=["build"])
        self.assertEqual(T.sha256_of(p), hashlib.sha256(b"#!/bin/sh\necho 2.0.1\n").hexdigest())
        state, text = T.status(good)
        self.assertEqual(state, "path", text)                                # ~/.local/bin is not on PATH here
        os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
        self.assertEqual(T.status(good)[0], "ok")
        state, text = T.status(dict(BIN, roles=["build"]))
        self.assertEqual(state, "wrong")
        self.assertIn("acme-fmt at %s is not the file roles build pins (sha256 differs; version 2.0.1)" % p, text)
        os.unlink(p)
        state, text = T.status(good)
        self.assertEqual(state, "missing")
        self.assertIn("acme-fmt is not installed", text)

    def test_a_submodule_in_a_work_tree(self):
        sub = os.path.join(self.t, "sub")
        git("init", "-q", "-b", "main", sub)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=sub)
        repo = os.path.join(self.t, "repo")
        git("init", "-q", "-b", "main", repo)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=repo)
        state, text = T.status(dict(SUB, roles=["test"]), repo)
        self.assertEqual(state, "missing")
        self.assertIn("no submodule at vendor/acme-test", text)
        git("submodule", "add", "-q", sub, "vendor/acme-test", cwd=repo)
        git("commit", "-q", "-m", "sub", cwd=repo)
        self.assertEqual(T.status(SUB, repo)[0], "ok")
        git("commit", "-q", "--allow-empty", "-m", "two", cwd=os.path.join(repo, "vendor/acme-test"))
        state, text = T.status(SUB, repo)
        self.assertEqual(state, "wrong")
        self.assertIn("at another commit than HEAD records", text)
        clone = os.path.join(self.t, "clone")
        git("clone", "-q", repo, clone)
        state, text = T.status(SUB, clone)
        self.assertEqual(state, "missing")
        self.assertIn("submodule vendor/acme-test is not initialised", text)
        self.assertEqual(T.status(SUB, self.t)[0], "note")
        self.assertEqual(T.status(SUB, None)[0], "note")


class Checkout(unittest.TestCase):
    """What qargi local prepare runs: the declared submodules checked out in the member's clone from the lead's copy, nothing fetched."""

    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.saved = dict(os.environ)
        os.environ.update(HOME=self.t, PATH="/usr/bin:/bin")
        self.sub = os.path.join(self.t, "sub")
        git("init", "-q", "-b", "main", self.sub)
        with open(os.path.join(self.sub, "f"), "w") as f:
            f.write("a\n")
        git("add", "f", cwd=self.sub)
        git("commit", "-q", "-m", "a", cwd=self.sub)
        self.lead = os.path.join(self.t, "lead")
        git("init", "-q", "-b", "main", self.lead)
        git("commit", "-q", "--allow-empty", "-m", "one", cwd=self.lead)
        git("submodule", "add", "-q", self.sub, "vendor/acme-test", cwd=self.lead)
        git("commit", "-q", "-m", "sub", cwd=self.lead)

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self.saved)
        shutil.rmtree(self.t, ignore_errors=True)

    def bump(self):
        """A new commit of the submodule that only the lead's checkout has fetched, recorded by the lead as the gitlink (detached, no branch)."""
        git("commit", "-q", "--allow-empty", "-m", "b", cwd=self.sub)
        sha = git("rev-parse", "HEAD", cwd=self.sub)
        wt = os.path.join(self.lead, "vendor/acme-test")
        git("fetch", "-q", "origin", cwd=wt)
        git("checkout", "-q", sha, cwd=wt)
        git("add", "vendor/acme-test", cwd=self.lead)
        git("commit", "-q", "-m", "bump", cwd=self.lead)
        return sha

    def member_clone(self):
        bare = os.path.join(self.t, "bare.git")
        git("clone", "-q", "--bare", "--no-hardlinks", self.lead, bare)
        git("remote", "remove", "origin", cwd=bare)
        clone = os.path.join(self.t, "clone")
        git("clone", "-q", "--no-hardlinks", bare, clone)
        return clone

    def test_checked_out_offline_from_the_leads_copy_with_the_push_url_disabled(self):
        sha = self.bump()
        clone = self.member_clone()
        copies = os.path.join(self.t, "run-sub")
        done, notes = T.checkout([dict(SUB, roles=["test"])], clone, copies, self.lead)
        self.assertEqual((done, notes), (["vendor/acme-test"], []))
        wt = os.path.join(clone, "vendor/acme-test")
        self.assertEqual(git("rev-parse", "HEAD", cwd=wt), sha)                     # the commit HEAD records, which no branch of the submodule holds
        self.assertEqual(git("remote", "get-url", "--push", "origin", cwd=wt), "DISABLED")
        self.assertEqual(git("remote", "get-url", "origin", cwd=wt), os.path.join(copies, "vendor/acme-test.git"))
        self.assertEqual(git("remote", cwd=os.path.join(copies, "vendor/acme-test.git")), "")   # the copy knows no remote
        self.assertEqual(T.status(SUB, clone)[0], "ok")
        self.assertTrue(os.path.isfile(os.path.join(wt, "f")))

    def test_a_commit_the_lead_lacks_is_a_note_and_nothing_is_fetched(self):
        git("commit", "-q", "--allow-empty", "-m", "b", cwd=self.sub)             # the lead's submodule checkout never fetched it
        sha = git("rev-parse", "HEAD", cwd=self.sub)
        git("update-index", "--cacheinfo", "160000,%s,vendor/acme-test" % sha, cwd=self.lead)
        git("commit", "-q", "-m", "bump without fetch", cwd=self.lead)
        clone = self.member_clone()
        done, notes = T.checkout([SUB], clone, os.path.join(self.t, "run-sub"), self.lead)
        self.assertEqual(done, [])
        self.assertEqual(len(notes), 1, notes)
        self.assertIn("the commit HEAD records (%s) is not in" % sha[:12], notes[0])
        self.assertIn("nothing is fetched", notes[0])
        self.assertFalse(os.path.exists(os.path.join(clone, "vendor/acme-test", ".git")))

    def test_not_initialised_in_the_lead_no_source_and_not_declared_in_gitmodules(self):
        lead2 = os.path.join(self.t, "lead2")
        git("clone", "-q", self.lead, lead2)                                        # a checkout whose submodule was never initialised
        clone = self.member_clone()
        done, notes = T.checkout([SUB], clone, os.path.join(self.t, "run-sub"), lead2)
        self.assertEqual(done, [])
        self.assertIn("is not initialised in %s" % lead2, notes[0])
        self.assertIn("git -C %s submodule update --init -- vendor/acme-test" % lead2, notes[0])
        done, notes = T.checkout([SUB], clone, os.path.join(self.t, "run-sub"), None)
        self.assertEqual(done, [])
        self.assertIn("cloned from a URL", notes[0])
        done, notes = T.checkout([dict(SUB, path="vendor/other", name="other")], clone, os.path.join(self.t, "run-sub"), self.lead)
        self.assertEqual(done, [])
        self.assertIn("vendor/other (other) is not in the .gitmodules", notes[0])
        self.assertEqual(T.status(SUB, clone)[0], "missing")

    def test_the_verb_prints_the_paths_and_notes(self):
        clone = self.member_clone()
        answers = os.path.join(self.t, "acme.json")
        with open(answers, "w") as f:
            json.dump({"roles": {"test": {"tools": [SUB]}, "build": {"tools": []}}}, f)
        for role, want in (("test", "SUBMODULES=vendor/acme-test\n"), ("build", "")):
            shutil.rmtree(os.path.join(self.t, "run-sub"), ignore_errors=True)
            r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "tools.py"), "checkout", "--answers", answers, "--role", role, "--clone", clone,
                                "--copies", os.path.join(self.t, "run-sub"), "--source", self.lead], capture_output=True, text=True)
            self.assertEqual((r.returncode, r.stdout), (0, want), r.stderr)
        r = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "tools.py"), "checkout", "--answers", answers, "--role", "test", "--clone", clone,
                            "--copies", os.path.join(self.t, "run-sub")], capture_output=True, text=True)
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertIn("qargi: note: submodule vendor/acme-test: the run was cloned from a URL", r.stderr)
        self.assertEqual(subprocess.run([sys.executable, "-I", os.path.join(ROOT, "lib", "tools.py"), "checkout"], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
