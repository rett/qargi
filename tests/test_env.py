#!/usr/bin/env python3
"""qargi env show and check, lib/env.py and lib/env_check.py: what a repository declares about its development environment, read from its
own files, and whether a checkout is set up that way. Fixture repositories are invented (acme and others); show executes nothing, check
runs only fixture scripts. Offline. Run: python3 tests/test_env.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, shutil, stat, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
sys.path.insert(0, os.path.join(ROOT, "lib"))
import env as E  # noqa: E402


def put(base, rel, text=""):
    p = os.path.join(base, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        f.write(text)
    return p


AGENTS = """# acme

Some words.

```
## Setup
this heading is inside a code block
```

## Development environment

Run `make bootstrap` to install and `make doctor` to check.

### Notes

A sub-heading stays inside the section.

## Testing
"""

MAKEFILE = """# acme
VERSION := 1.2
CC ?= gcc
include extra.mk
.PHONY: bootstrap doctor test

%.o: %.c
\t$(CC) -c $<

test:
\tgo test ./...

bootstrap:
\ttouch ran-bootstrap
\tgit submodule update --init --recursive

doctor: bootstrap-check
\t@touch ran-doctor
"""


class Fixtures(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.conf = os.path.join(self.t, "conf")
        os.makedirs(os.path.join(self.conf, "projects"))
        self.env = dict(os.environ, HOME=self.t, QARGI_CONF=self.conf, QARGI_STATE=os.path.join(self.t, "state"))
        self.env.pop("QARGI_PROJECT", None)

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def repo(self, name, files):
        d = os.path.join(self.t, name)
        os.makedirs(d)
        for rel, text in files.items():
            put(d, rel, text)
        return d

    def q(self, *a, cwd=None, env=None):
        return subprocess.run([BIN, *a], capture_output=True, text=True, cwd=cwd, env=env or self.env, stdin=subprocess.DEVNULL)

    def show(self, d, *extra):
        r = self.q("env", "show", "--repo", d, "--json", *extra)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def answers(self, name, repo_path, env=None):
        a = {"schema": 1, "project": name, "repo": {"url": "https://github.com/acme/%s" % name, "path": repo_path, "long_lived": ["master", "develop"]}}
        if env is not None:
            a["env"] = env
        put(self.conf, "projects/%s.json" % name, json.dumps(a))


class Detect(Fixtures):
    def test_makefile_project(self):
        d = self.repo("acme", {
            "AGENTS.md": AGENTS, "Makefile": MAKEFILE,
            "go.mod": "module example.test/acme\n\ngo 1.22.3\n\ntoolchain go1.22.5\n",
            ".tool-versions": "shellcheck 0.10.0  # lint\nbats 1.11.0 1.10.0\n",
            ".gitmodules": '[submodule "vendor/lib"]\n\tpath = vendor/lib\n\turl = https://user:secret@example.test/lib.git\n',
            ".devcontainer/devcontainer.json": "{}", ".github/workflows/copilot-setup-steps.yml": "steps: []\n", ".cursor/environment.json": "{}"})
        j = self.show(d)
        self.assertEqual((j["section"]["file"], j["section"]["heading"], j["section"]["line"]), ("AGENTS.md", "Development environment", 10))
        self.assertEqual(j["section"]["mentions"], ["bootstrap", "doctor"])      # the heading inside the code fence was skipped
        pins = {(p["file"], p["tool"]): p["version"] for p in j["pins"]}
        self.assertEqual(pins[("go.mod", "go")], "1.22.3")
        self.assertEqual(pins[("go.mod", "toolchain")], "go1.22.5")
        self.assertEqual(pins[(".tool-versions", "shellcheck")], "0.10.0")
        self.assertEqual(pins[(".tool-versions", "bats")], "1.11.0 1.10.0")
        self.assertEqual(j["submodules"], [{"name": "vendor/lib", "path": "vendor/lib", "url": "https://example.test/lib.git"}])   # credentials are not shown
        self.assertEqual(j["runner"], "make")
        mk = j["runners"][0]
        self.assertEqual((mk["runner"], mk["file"]), ("make", "Makefile"))
        self.assertEqual(mk["targets"], ["test", "bootstrap", "doctor"])         # variables, .PHONY and pattern rules are not targets
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "make bootstrap")
        self.assertEqual(j["commands"]["doctor_command"]["command"], "make doctor")
        self.assertEqual(j["commands"]["dry_run_command"]["command"], "make -n bootstrap")
        self.assertEqual(j["commands"]["doctor_command"]["source"], "detected: Makefile target doctor")
        self.assertEqual(j["vendor_files"], [".devcontainer/devcontainer.json", ".github/workflows/copilot-setup-steps.yml", ".cursor/environment.json"])
        self.assertEqual(j["gaps"], [])
        self.assertTrue(any("includes other files" in n for n in j["notes"]))
        self.assertEqual(j["known_failures"], [])

    def test_nothing_is_executed(self):
        d = self.repo("acme", {"Makefile": MAKEFILE, "go.mod": "go 1.22\n"})
        bindir = os.path.join(self.t, "fakebin")
        for tool in ("make", "just", "task", "mise", "git"):
            p = put(bindir, tool, '#!/bin/sh\necho "$0 $*" >> "%s"\n' % os.path.join(self.t, "ran"))
            os.chmod(p, 0o755)
        env = dict(self.env, PATH=bindir + os.pathsep + self.env["PATH"])
        for args in (("--repo", d), ("--repo", d, "--json")):
            self.assertEqual(self.q("env", "show", *args, env=env).returncode, 0)
        self.assertFalse(os.path.exists(os.path.join(self.t, "ran")), "a tool was run")
        self.assertFalse(os.path.exists(os.path.join(d, "ran-bootstrap")))

    def test_mise_project(self):
        d = self.repo("acme", {
            "README.md": "# acme\n\n## Setup\n\nRun `mise run bootstrap`, then `mise run doctor`.\n",
            "mise.toml": '[tools]\ngo = "1.23"\nnode = ["20", "22"]\npython = { version = "3.12", virtualenv = ".venv" }\n\n'
                         '[tasks.bootstrap]\nrun = "mise install"\n\n[tasks."lint:go"]\nrun = "golangci-lint run"\n\n[tasks]\ndoctor = "mise doctor"\n',
            ".python-version": "# pinned\n3.12.4\n", ".nvmrc": "v22.1.0\n", "package.json": '{"name": "acme", "engines": {"node": ">=20", "npm": ">=10"}}'})
        j = self.show(d)
        self.assertEqual(j["section"]["file"], "README.md")
        self.assertEqual(j["section"]["heading"], "Setup")
        pins = {(p["file"], p["tool"]): p["version"] for p in j["pins"]}
        self.assertEqual(pins[("mise.toml", "go")], "1.23")
        self.assertEqual(pins[("mise.toml", "node")], "20, 22")
        self.assertEqual(pins[("mise.toml", "python")], "3.12")
        self.assertEqual(pins[(".python-version", "python")], "3.12.4")
        self.assertEqual(pins[(".nvmrc", "node")], "v22.1.0")
        self.assertEqual(pins[("package.json", "node")], ">=20")
        self.assertEqual(pins[("package.json", "npm")], ">=10")
        self.assertEqual(j["runner"], "mise")
        self.assertEqual(set(j["runners"][0]["targets"]), {"bootstrap", "lint:go", "doctor"})
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "mise run bootstrap")
        self.assertEqual(j["commands"]["dry_run_command"]["command"], "mise run --dry-run bootstrap")
        self.assertEqual(j["commands"]["doctor_command"]["command"], "mise run doctor")

    def test_mise_file_without_tasks_is_only_pins(self):
        j = self.show(self.repo("acme", {"mise.toml": '[tools]\ngo = "1.23"\n'}))
        self.assertEqual(j["runners"], [])
        self.assertEqual([p["tool"] for p in j["pins"]], ["go"])

    def test_justfile_project_and_fallback_names(self):
        d = self.repo("acme", {"justfile": 'set shell := ["bash", "-c"]\nalias b := setup\nname := "acme"\n\n[private]\n_helper:\n  true\n\n'
                                           'setup target="all" *flags:\n  ./install.sh {{target}}\n\ncheck:\n  ./verify.sh\n\ntest:\n  go test ./...\n'})
        j = self.show(d)
        self.assertEqual(j["runner"], "just")
        self.assertEqual(j["runners"][0]["targets"], ["_helper", "setup", "check", "test"])
        self.assertEqual(j["targets"]["bootstrap"], {"name": "setup", "runner": "just", "file": "justfile", "fallback": True})
        self.assertEqual(j["targets"]["doctor"]["name"], "check")
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "just setup")
        self.assertEqual(j["commands"]["dry_run_command"]["command"], "just --dry-run setup")
        self.assertEqual(j["commands"]["doctor_command"]["command"], "just check")
        self.assertIn("recipe setup", j["commands"]["bootstrap_command"]["source"])

    def test_the_primary_name_beats_the_fallback_across_runners(self):
        d = self.repo("acme", {"Makefile": "setup:\n\ttrue\n", "justfile": "bootstrap:\n  true\n"})
        j = self.show(d)
        self.assertEqual(j["targets"]["bootstrap"]["runner"], "just")
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "just bootstrap")

    def test_taskfile_project(self):
        d = self.repo("acme", {"Taskfile.yml": 'version: "3"\n\nvars:\n  X: 1\n\ntasks:\n  # the install\n  bootstrap:\n    cmds:\n      - ./install.sh\n'
                                               '  "doctor":\n    desc: check\n    cmds:\n      - ./verify.sh\n  other:\n    cmds: []\n\nincludes:\n  sub:\n    taskfile: ./sub\n'})
        j = self.show(d)
        self.assertEqual(j["runners"][0]["targets"], ["bootstrap", "doctor", "other"])
        self.assertEqual(j["commands"]["dry_run_command"]["command"], "task --dry bootstrap")
        self.assertEqual(j["commands"]["doctor_command"]["command"], "task doctor")

    def test_empty_repository(self):
        j = self.show(self.repo("empty", {}))
        self.assertIsNone(j["section"])
        self.assertEqual((j["pins"], j["submodules"], j["runners"], j["vendor_files"]), ([], [], [], []))
        self.assertIsNone(j["runner"])
        self.assertEqual(j["targets"], {"bootstrap": None, "doctor": None})
        for k in ("bootstrap_command", "doctor_command", "dry_run_command"):
            self.assertEqual(j["commands"][k], {"command": None, "source": None})
        self.assertEqual(len(j["gaps"]), 3)
        r = self.q("env", "show", "--repo", j["repo"])
        self.assertEqual(r.returncode, 0)
        self.assertIn("gap:", r.stdout)
        self.assertIn("none", r.stdout)

    def test_section_headings(self):
        for n, (line, found) in enumerate((("## Development environment", True), ("# Environment", True), ("### setup", True), ("## Dev Setup ##", True),
                                          ("## `Environment`", True), ("## Environment variables", False), ("## Setup guide", False), ("## Install", False))):
            d = self.repo("h%d" % n, {"AGENTS.md": "# acme\n\n%s\n\ntext\n" % line})
            self.assertEqual(self.show(d)["section"] is not None, found, line)
        d = self.repo("both", {"AGENTS.md": "# acme\n", "README.md": "# acme\n\n# Environment\n"})
        self.assertEqual(self.show(d)["section"]["file"], "README.md")

    def test_a_bad_file_is_a_note_not_a_failure(self):
        d = self.repo("odd", {"mise.toml": "[tools\n", "package.json": "{not json"})
        j = self.show(d)
        self.assertEqual(j["pins"], [])
        self.assertTrue(any("mise.toml is not valid TOML" in n for n in j["notes"]))
        self.assertTrue(any("package.json is not valid JSON" in n for n in j["notes"]))

    def test_control_characters_are_not_printed(self):
        d = self.repo("ctl", {".nvmrc": "v22\x1b[31mred\n"})
        out = self.q("env", "show", "--repo", d).stdout
        self.assertNotIn("\x1b", out)


class Safety(Fixtures):
    def test_a_symlink_leaving_the_repository_is_refused(self):
        outside = self.repo("outside", {"secret.md": "## Setup\n\nmake bootstrap\n", "Makefile": "bootstrap:\n\ttrue\n", "dc": "{}", "cursor/environment.json": "{}"})
        d = self.repo("acme", {"go.mod": "go 1.22\n"})
        os.symlink(os.path.join(outside, "secret.md"), os.path.join(d, "AGENTS.md"))
        os.symlink(os.path.join(outside, "Makefile"), os.path.join(d, "Makefile"))
        os.symlink(os.path.join(outside, "cursor"), os.path.join(d, ".cursor"))                      # a directory link
        os.makedirs(os.path.join(d, ".devcontainer"))
        os.symlink(os.path.join(outside, "dc"), os.path.join(d, ".devcontainer", "devcontainer.json"))
        os.symlink("../outside/secret.md", os.path.join(d, "README.md"))                         # relative
        j = self.show(d)
        self.assertIsNone(j["section"])
        self.assertEqual(j["runners"], [])
        self.assertEqual(j["vendor_files"], [])
        self.assertEqual(sorted(r["file"] for r in j["refused"]), sorted(["AGENTS.md", "Makefile", ".cursor/environment.json", ".devcontainer/devcontainer.json", "README.md"]))
        self.assertTrue(all("leaves the repository" in r["why"] for r in j["refused"]))
        self.assertEqual([p["tool"] for p in j["pins"]], ["go"])
        text = self.q("env", "show", "--repo", d).stdout
        self.assertIn("refused:", text)

    def test_a_symlink_inside_the_repository_is_read(self):
        d = self.repo("acme", {"docs/ENV.md": "## Environment\n\nmake bootstrap\n"})
        os.symlink("docs/ENV.md", os.path.join(d, "AGENTS.md"))
        j = self.show(d)
        self.assertEqual(j["section"]["file"], "AGENTS.md")
        self.assertEqual(j["refused"], [])

    def test_a_large_file_and_a_fifo_are_not_read(self):
        d = self.repo("acme", {"Makefile": "bootstrap:\n\ttrue\n" + "# pad\n" * (E.CAP // 6 + 10)})
        os.mkfifo(os.path.join(d, "justfile"))
        j = self.show(d)
        self.assertEqual(j["runners"], [])
        self.assertTrue(any("Makefile is larger than 1024 KB" in n for n in j["notes"]))

    def test_the_reading_never_follows_a_link_out_through_a_directory(self):
        outside = self.repo("outside", {"mise.toml": '[tools]\nsecret = "1"\n'})
        d = self.repo("acme", {})
        os.symlink(outside, os.path.join(d, "sub"))
        r = E.Repo(d)
        self.assertIsNone(r.read("sub/mise.toml"))
        self.assertEqual(r.refused[0]["file"], "sub/mise.toml")


class Overrides(Fixtures):
    def test_answers_win_over_detection(self):
        d = self.repo("acme", {"Makefile": MAKEFILE})
        self.answers("acme", d, {"doctor_command": "./scripts/doctor", "bootstrap_command": "make bootstrap PROFILE=ci",
                                 "dry_run_command": "make -n bootstrap PROFILE=ci", "known_failures": ["expected: lint 1.2 is newer"]})
        j = json.loads(self.q("env", "show", "--project", "acme", "--json").stdout)
        self.assertEqual(j["project"], "acme")
        self.assertEqual(j["commands"]["doctor_command"], {"command": "./scripts/doctor", "source": "answers: env.doctor_command"})
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "make bootstrap PROFILE=ci")
        self.assertEqual(j["commands"]["dry_run_command"]["command"], "make -n bootstrap PROFILE=ci")
        self.assertEqual(j["known_failures"], ["expected: lint 1.2 is newer"])
        self.assertEqual(j["targets"]["doctor"]["name"], "doctor")                     # the detection is still reported
        out = self.q("env", "show", "--project", "acme").stdout
        self.assertIn("[answers: env.doctor_command]", out)
        self.assertIn("expected: lint 1.2 is newer", out)

    def test_a_partial_override_leaves_the_rest_detected(self):
        d = self.repo("acme", {"Makefile": MAKEFILE})
        self.answers("acme", d, {"doctor_command": "./doctor.sh"})
        j = json.loads(self.q("env", "show", "--project", "acme", "--json").stdout)
        self.assertEqual(j["commands"]["doctor_command"]["command"], "./doctor.sh")
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "make bootstrap")
        self.assertTrue(j["commands"]["bootstrap_command"]["source"].startswith("detected"))

    def test_an_override_applies_with_nothing_detected(self):
        d = self.repo("bare", {})
        self.answers("bare", d, {"bootstrap_command": "./install.sh"})
        j = json.loads(self.q("env", "show", "--project", "bare", "--json").stdout)
        self.assertEqual(j["commands"]["bootstrap_command"]["command"], "./install.sh")
        self.assertIsNone(j["commands"]["doctor_command"]["command"])

    def test_invalid_overrides_are_ignored_with_a_note(self):
        d = self.repo("acme", {"Makefile": MAKEFILE})
        self.answers("acme", d, {"doctor_command": ["x"], "colour": "red"})
        j = json.loads(self.q("env", "show", "--project", "acme", "--json").stdout)
        self.assertEqual(j["commands"]["doctor_command"]["command"], "make doctor")
        self.assertTrue(any(n.startswith("env in the project's answers is not valid") for n in j["notes"]))

    def test_problems(self):
        self.assertEqual(E.problems({}), [])
        self.assertEqual(E.problems({"doctor_command": "make doctor", "known_failures": []}), [])
        for bad in ("x", [], {"nope": 1}, {"doctor_command": ""}, {"doctor_command": "a\nb"}, {"bootstrap_command": 3}, {"dry_run_command": "x" * 501},
                    {"known_failures": "x"}, {"known_failures": [1]}, {"known_failures": [""]}, {"known_failures": ["a\nb"]}):
            self.assertTrue(E.problems(bad), bad)

    def test_the_project_is_found_from_the_repository(self):
        d = self.repo("acme", {"Makefile": MAKEFILE})
        os.makedirs(os.path.join(d, "src", "deep"))
        self.answers("acme", d, {"doctor_command": "./doctor.sh"})
        r = self.q("env", "show", "--json", cwd=os.path.join(d, "src", "deep"))
        self.assertEqual(r.returncode, 0, r.stderr)
        j = json.loads(r.stdout)
        self.assertEqual((j["project"], j["repo"]), ("acme", os.path.realpath(d)))
        self.assertEqual(j["commands"]["doctor_command"]["command"], "./doctor.sh")
        j = json.loads(self.q("env", "show", "--repo", d, "--json", cwd=self.t).stdout)                # --repo: the project that contains it
        self.assertEqual(j["project"], "acme")
        j = json.loads(self.q("env", "show", "--json", env=dict(self.env, QARGI_PROJECT="acme"), cwd=self.t).stdout)
        self.assertEqual(j["repo"], os.path.realpath(d))

    def test_outside_any_project_the_repository_around_here_is_read(self):
        d = self.repo("lone", {"Makefile": MAKEFILE, ".git/HEAD": "ref: refs/heads/main\n"})
        os.makedirs(os.path.join(d, "pkg"))
        j = json.loads(self.q("env", "show", "--json", cwd=os.path.join(d, "pkg")).stdout)
        self.assertEqual((j["project"], j["repo"]), (None, os.path.realpath(d)))


class Cli(Fixtures):
    def test_refusals_and_usage(self):
        self.assertEqual(self.q("env", "show", "--project", "nosuch").returncode, 2)
        self.assertIn("no such project", self.q("env", "show", "--project", "nosuch").stderr)
        self.assertEqual(self.q("env", "show", "--repo", os.path.join(self.t, "absent")).returncode, 2)
        self.assertEqual(self.q("env", "show", "--bogus").returncode, 2)
        self.assertEqual(self.q("env").returncode, 2)
        self.answers("nopath", "")
        self.assertEqual(self.q("env", "show", "--project", "nopath").returncode, 2)
        for verb in ("plan", "apply"):                # lead-only verbs: no arguments is a usage error (tests/test_env_apply.py has the rest)
            r = self.q("env", verb, "--repo", self.repo("bare", {}) if verb == "plan" else self.t)
            self.assertEqual(r.returncode, 2, verb)

    def test_help_completion_and_the_member_guard(self):
        self.assertIn("show", self.q("help", "env").stdout)
        self.assertIn("bootstrap", self.q("help", "environment").stdout)
        self.assertIn("--repo", self.q("__complete", "env", "show", "--").stdout)
        self.assertIn("env.doctor_command", self.q("__complete", "project", "set", "acme", "").stdout.split())
        g = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_input": {"command": "qargi env show --json"}}), capture_output=True, text=True, env=self.env)
        self.assertEqual(g.returncode, 0, g.stderr)

    def test_set_validates_the_environment_answers(self):
        d = self.repo("acme", {})
        template = json.loads(self.q("project", "template", "acme").stdout)
        template["repo"].update(url="https://github.com/acme/acme", path=d)
        f = os.path.join(self.t, "acme.json")
        with open(f, "w") as fh:
            json.dump(template, fh)
        self.assertEqual(self.q("project", "init", "acme", "--answers", f).returncode, 0)
        ok = self.q("project", "set", "acme", "env.doctor_command", "make doctor")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(self.q("project", "set", "acme", "env.known_failures", '["expected: x"]').returncode, 0)
        bad = self.q("project", "set", "acme", "env.doctor_command", "[1]")
        self.assertNotEqual(bad.returncode, 0)
        self.assertIn("env.doctor_command", bad.stderr)
        self.assertNotEqual(self.q("project", "set", "acme", "env.colour", "red").returncode, 0)
        j = json.loads(self.q("env", "show", "--project", "acme", "--json").stdout)
        self.assertEqual(j["commands"]["doctor_command"]["command"], "make doctor")
        self.assertEqual(j["known_failures"], ["expected: x"])


GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.net", "-c", "protocol.file.allow=always"]


class Check(Fixtures):
    """qargi env check: the doctor command, the built-in minimum, the verdict, the exit status and the state file."""

    def git(self, d, *a):
        r = subprocess.run(GIT + ["-C", d] + list(a), capture_output=True, text=True, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def gitrepo(self, name, files):
        d = self.repo(name, files)
        subprocess.run(["git", "init", "-q", d], check=True)
        self.git(d, "add", "-A")
        self.git(d, "commit", "-q", "-m", "first")
        return d

    def doctor_repo(self, script, known=None, name="acme"):
        d = self.gitrepo(name, {"doctor.sh": script})
        self.answers(name, d, {"doctor_command": "sh ./doctor.sh", **({"known_failures": known} if known else {})})
        return d

    def check(self, d, *extra, env=None):
        r = self.q("env", "check", "--repo", d, *extra, env=env)
        return r.returncode, r.stdout, r.stderr

    def test_a_doctor_with_nothing_missing_is_ok(self):
        d = self.doctor_repo("echo 'ok: git 2.40'\necho 'ok: make'\n")
        rc, out, err = self.check(d)
        self.assertEqual((rc, out.splitlines()[-1]), (0, "ENV OK"), out + err)
        self.assertIn("2 other line(s)", out)

    def test_a_missing_item_is_named_in_the_verdict(self):
        d = self.doctor_repo("echo 'ok: git'\necho 'missing: shellcheck 0.9'\necho 'bats    not installed'\nexit 1\n")
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        last = out.splitlines()[-1]
        self.assertTrue(last.startswith("ENV INCOMPLETE: 2 missing ("), last)
        self.assertIn("missing: shellcheck 0.9", last)
        self.assertIn("bats    not installed", last)

    def test_a_known_failure_is_expected_and_not_red(self):
        d = self.doctor_repo("echo 'ok: git'\necho 'FAIL: linter 1.2 is older than the pin'\necho 'expected: bats is not packaged here'\nexit 1\n",
                             known=["linter 1.2"])
        rc, out, _ = self.check(d)
        self.assertEqual((rc, out.splitlines()[-1]), (0, "ENV OK"), out)
        self.assertIn("expected: FAIL: linter 1.2", out)
        self.assertIn("expected: expected: bats", out)
        j = json.loads(self.check(d, "--json")[1])
        self.assertEqual((j["exit"], j["missing"], len(j["expected"])), (0, [], 2))
        # the same line without the accepted failure is red
        self.answers("acme", d, {"doctor_command": "sh ./doctor.sh"})
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertIn("ENV INCOMPLETE: 1 missing (FAIL: linter 1.2", out.splitlines()[-1])

    def test_a_failing_doctor_that_names_nothing_is_one_missing_item(self):
        d = self.doctor_repo("echo 'all good'\nexit 3\n")
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertIn("ENV INCOMPLETE: 1 missing (doctor exited 3 and named no missing item)", out)

    def test_lines_that_only_look_like_failures_are_not(self):
        d = self.doctor_repo("echo 'ok: 0 failed'\necho 'errors: 0'\necho 'no problems found'\necho 'warning: old'\n")
        self.assertEqual(self.check(d)[0], 0)

    def test_the_doctor_runs_without_a_shell_stdin_or_the_callers_environment(self):
        d = self.doctor_repo("[ -z \"$SECRET_TOKEN\" ] || echo 'missing: the environment leaked'\n"
                             "if read -r line; then echo 'missing: stdin was open'; fi\n"
                             "[ \"$PWD\" = \"$(pwd -P)\" ] || true\n[ -f doctor.sh ] || echo 'missing: not run in the repository'\n")
        rc, out, _ = self.check(d, env=dict(self.env, SECRET_TOKEN="hunter2"))
        self.assertEqual((rc, out.splitlines()[-1]), (0, "ENV OK"), out)
        self.answers("acme", d, {"doctor_command": "sh ./doctor.sh && echo hi"})
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertIn("without a shell", out)
        self.answers("acme", d, {"doctor_command": "no-such-doctor-tool --x"})
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertIn("is not on PATH", out)

    def test_a_doctor_that_does_not_finish_is_killed(self):
        d = self.doctor_repo("echo 'ok: started'\nsleep 30\n")
        t0 = time.monotonic()
        rc, out, _ = self.check(d, "--timeout", "1")
        self.assertLess(time.monotonic() - t0, 15)
        self.assertEqual(rc, 1)
        self.assertIn("did not finish within 1 s", out)

    def test_the_detected_make_target_is_run_when_the_answers_name_none(self):
        if shutil.which("make") is None:
            self.skipTest("make is not installed")
        d = self.gitrepo("acme", {"Makefile": "doctor:\n\t@echo 'ok: make'\n\t@echo 'missing: tool x'\n\t@false\n"})
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertIn("make doctor   [detected: Makefile target doctor]", out)
        self.assertIn("ENV INCOMPLETE: 1 missing (missing: tool x)", out)

    def test_exit_two_for_usage_and_for_no_project_or_repository(self):
        d = self.doctor_repo("echo ok\n")
        for args in (["--bogus"], ["--timeout", "0"], ["--timeout", "soon"], ["--timeout", "99999"], ["--project", "nosuch"], ["--repo", os.path.join(self.t, "absent")], ["--repo"]):
            r = self.q("env", "check", *args)
            self.assertEqual(r.returncode, 2, (args, r.stdout, r.stderr))
        self.answers("nopath", "")
        self.assertEqual(self.q("env", "check", "--project", "nopath").returncode, 2)
        self.assertEqual(self.check(d)[0], 0)

    def test_the_state_file_holds_the_verdict_and_no_output(self):
        d = self.doctor_repo("echo 'missing: sekrit-line-7f3a'\nexit 1\n")
        self.assertEqual(self.check(d)[0], 1)
        f = os.path.join(self.t, "state", "env", "acme.json")
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)
        with open(f) as fh:
            raw = fh.read()
        self.assertNotIn("sekrit-line-7f3a", raw)
        j = json.loads(raw)["check"]
        self.assertEqual((j["verdict"], j["exit"], j["missing"], j["doctor_command"], j["builtin_minimum"]), ("ENV INCOMPLETE: 1 missing", 1, 1, "sh ./doctor.sh", False))
        self.assertEqual(j["head"], self.git(d, "rev-parse", "HEAD").strip())
        self.assertRegex(j["time"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
        self.assertIn("dry_run_command", j)
        with open(os.path.join(d, "doctor.sh"), "w") as fh:
            fh.write("echo ok\n")
        self.assertEqual(self.check(d)[0], 0)
        with open(f) as fh:
            self.assertEqual(json.load(fh)["check"]["verdict"], "ENV OK")

    def test_no_state_file_without_a_stored_project(self):
        d = self.gitrepo("lone", {"doctor.sh": "echo ok\n"})
        self.assertEqual(self.check(d)[0], 0)
        self.assertFalse(os.path.exists(os.path.join(self.t, "state", "env")))

    def test_the_builtin_minimum_finds_an_uninitialised_submodule(self):
        lib = self.gitrepo("lib", {"README": "lib\n"})
        up = self.gitrepo("upstream", {"README": "up\n"})
        self.git(up, "-c", "protocol.file.allow=always", "submodule", "add", "-q", lib, "vendor/lib")
        self.git(up, "commit", "-q", "-m", "add the submodule")
        clone = os.path.join(self.t, "acme")
        subprocess.run(GIT + ["clone", "-q", up, clone], check=True, capture_output=True)
        self.answers("acme", clone)
        rc, out, _ = self.check(clone)
        self.assertEqual(rc, 1, out)
        self.assertIn("none; built-in minimum (1 submodule(s)", out)
        self.assertIn("ENV INCOMPLETE: 1 missing (submodule vendor/lib is not initialised", out.splitlines()[-1])
        self.git(clone, "-c", "protocol.file.allow=always", "submodule", "update", "--init", "-q")
        rc, out, _ = self.check(clone)
        self.assertEqual((rc, out.splitlines()[-1]), (0, "ENV OK"), out)
        with open(os.path.join(self.t, "state", "env", "acme.json")) as fh:
            self.assertTrue(json.load(fh)["check"]["builtin_minimum"])

    def test_the_builtin_minimum_checks_tags_and_pinned_tools(self):
        major = str(sys.version_info.major)
        d = self.gitrepo("acme", {"VERSION": "1.0.0\n", ".python-version": major + "\n", ".tool-versions": "nosuchtool-xyz 1.0\n"})
        self.git(d, "remote", "add", "origin", "https://example.net/acme.git")
        rc, out, _ = self.check(d)
        last = out.splitlines()[-1]
        self.assertEqual(rc, 1, out)
        self.assertIn("2 missing", last)
        self.assertIn("no tags are fetched", last)
        self.assertIn("nosuchtool-xyz is not installed (pinned in .tool-versions)", last)
        self.assertNotIn("python", last)                       # python answers --version and matches the major pin
        self.git(d, "tag", "1.0.0")
        os.remove(os.path.join(d, ".tool-versions"))
        with open(os.path.join(d, ".python-version"), "w") as fh:
            fh.write("1.0\n")
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 1)
        self.assertRegex(out.splitlines()[-1], r"ENV INCOMPLETE: 1 missing \(python 3\.\d+ does not match \.python-version 1\.0\)")
        self.git(d, "tag", "-d", "1.0.0")
        os.remove(os.path.join(d, ".python-version"))
        self.assertEqual(self.check(d)[0], 1)                  # still no tags, still a versioned project with a remote
        os.remove(os.path.join(d, "VERSION"))
        rc, out, _ = self.check(d)
        self.assertEqual((rc, out.splitlines()[-1]), (0, "ENV OK"), out)
        self.assertIn("git fetch --tags", out)                 # a note, not a missing item

    def test_the_version_rules(self):
        import env_check as C
        self.assertEqual(C.wanted("1.22"), [("=", 1, 22)])
        self.assertEqual(C.wanted(">=18"), [(">=", 18, None)])
        self.assertEqual(C.wanted("3.12 3.11"), [("=", 3, 12), ("=", 3, 11)])
        self.assertEqual(C.wanted("go1.22.3"), [("=", 1, 22)])
        for v in ("latest", "system", "lts/*", "20.x", "*"):
            self.assertIsNone(C.wanted(v), v)
        self.assertTrue(C.matches((20, 11), "=", 20, None))
        self.assertFalse(C.matches((21, 0), "=", 20, None))
        self.assertTrue(C.matches((1, 23), ">=", 1, 22))
        self.assertFalse(C.matches((1, 21), ">=", 1, 22))
        self.assertEqual(C.version_of("go version go1.22.3 linux/amd64"), (1, 22))
        self.assertEqual(C.version_of("Python 3.12.1"), (3, 12))

    def test_a_pin_with_a_backend_prefix_or_toolchain_is_not_asked(self):
        import env_check as C
        tools = C.pinned_tools([{"file": "go.mod", "tool": "go", "version": "1.22"}, {"file": "go.mod", "tool": "toolchain", "version": "go1.22.3"},
                                {"file": "mise.toml", "tool": "npm:left-pad", "version": "1"}, {"file": ".tool-versions", "tool": "golang", "version": "1.22.3"},
                                {"file": "mise.toml", "tool": "../evil", "version": "1"}])
        self.assertEqual(sorted(tools), ["go"])
        self.assertEqual(tools["go"], [("go.mod", ">=1.22"), (".tool-versions", "1.22.3")])

    def test_the_qargi_layer_for_a_stored_project(self):
        d = self.doctor_repo("echo 'ok: git'\n")
        rc, out, _ = self.check(d)
        self.assertEqual(rc, 0, out)                           # no provider set: each part is a note, none is missing
        self.assertIn("project:  acme (answers found)", out)
        self.assertIn("not checked", out)
        with open(os.path.join(self.conf, "projects", "acme.json")) as fh:
            a = json.load(fh)
        a["models"] = {"provider": {"local": "claude-code", "cloud": "claude-platform"}}
        a["roles"] = {"build": {"base": "master", "push": {"mode": "none"}, "model": "claude-sonnet-5-5", "effort": "high"}}
        a["budget_cents"] = 500
        put(self.conf, "projects/acme.json", json.dumps(a))
        env = dict(self.env, QARGI_PROJECT="acme")
        self.assertEqual(self.q("agent", "add", "forge", "--roles", "build", "--project", "acme", env=env).returncode, 0)
        j = json.loads(self.check(d, "--json")[1])
        parts = {x["part"] + ":" + x["text"].split(" ")[0]: x["text"] for x in j["qargi"]}
        self.assertIn("members", {x["part"] for x in j["qargi"]})
        self.assertTrue(any(x["part"] == "members" and x["text"].startswith("1 current") for x in j["qargi"]), j)
        self.assertFalse(any(m.startswith("skills") for m in j["missing"]), j["missing"])      # nothing is rendered yet: nothing to link
        packs = [x["text"] for x in j["qargi"] if x["part"] == "packs"]
        self.assertEqual(packs, ["not applied (qargi packs apply --target claude-code acme)"], j)   # never applied: not "no drift", and not a missing item
        self.assertFalse(any(m.startswith("packs") for m in j["missing"]), j["missing"])
        os.makedirs(os.path.join(self.t, "state", "render", "acme", "claude-code", ".claude", "skills"))
        j = json.loads(self.check(d, "--json")[1])
        self.assertIn("skills are not linked in this checkout", j["missing"])
        self.assertTrue(any(m.startswith("packs drift") for m in j["missing"]), j["missing"])
        self.assertEqual(j["exit"], 1)
        # a member whose file was edited by hand is DRIFT, a missing item
        listing = self.q("agent", "list", "--project", "acme", env=env).stdout.split()
        mf = next(w for w in listing if w.endswith(".md"))
        with open(mf, "a") as fh:
            fh.write("\nedited by hand\n")
        j = json.loads(self.check(d, "--json")[1])
        self.assertTrue(any(m.startswith("members not current: forge DRIFT") for m in j["missing"]), j["missing"])
        self.assertTrue(any(x["part"] == "members" and "DRIFT" in x["text"] for x in j["qargi"]), j)

    def test_the_member_guard_allows_check(self):
        g = subprocess.run([BIN, "__guard"], input=json.dumps({"tool_input": {"command": "qargi env check --json"}}), capture_output=True, text=True, env=self.env)
        self.assertEqual(g.returncode, 0, g.stderr)

    def test_help_and_completion(self):
        h = self.q("help", "env", "check").stdout
        self.assertIn("RUNS THE PROJECT'S CODE", h)
        self.assertIn("ENV INCOMPLETE", h)
        self.assertIn("--timeout", self.q("__complete", "env", "check", "--").stdout)
        self.assertIn("ENV INCOMPLETE", self.q("help", "environment").stdout)


if __name__ == "__main__":
    unittest.main()
