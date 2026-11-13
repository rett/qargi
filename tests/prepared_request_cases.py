#!/usr/bin/env python3
"""Prepare-to-run cases invoked by test_local_run.sh; all providers are fake."""
import hermetic  # noqa: F401
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import attempts as A
import local_run as R


class PreparedRequests(unittest.TestCase):
    """Actual prepare -> run argv, with independent offline command providers."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.repo, self.conf, self.state = (self.root / n for n in ("repo", "conf", "state"))
        self.bin = self.root / "bin"
        self.lib = self.conf / "packs/providers"
        for path in (self.repo, self.conf / "projects", self.bin):
            path.mkdir(parents=True)
        self.env = dict(os.environ, QARGI_CONF=str(self.conf), QARGI_STATE=str(self.state),
                        QARGI_RUN_TMP=str(self.root), PATH=str(self.bin) + os.pathsep + os.environ["PATH"])
        for key in list(self.env):
            if key.startswith(("GIT_AUTHOR_", "GIT_COMMITTER_")):
                del self.env[key]
        patch = mock.patch.dict(os.environ, self.env, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.git("init", "-q", "-b", "main")
        self.git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "initial", "--allow-empty")
        self.answers = {"schema": 1, "project": "demo", "repo": {"path": str(self.repo), "long_lived": ["main"]},
                        "models": {"provider": {"local": "cmdone"}}, "roles": {}, "memory": {}}
        self.save_answers()
        self.models = {"pattern": "^fake-.+$", "tiers": {
            "*": {"model": "fake-balanced", "alias": "middle", "verified_on": None, "source": "fixture"},
            "fast": {"model": "fake-fast", "alias": None, "verified_on": None, "source": "fixture"},
            "deep": {"model": "fake-deep", "alias": "depth", "verified_on": None, "source": "fixture"}},
            "effort": {"low": "little", "medium": "normal", "high": "much", "xhigh": None, "max": None}}
        cell = {"value": "yes", "verified_on": None, "source": "fixture", "note": "offline fake"}
        self.definitions = {}
        for provider, exe in (("cmdone", "qfakeone"), ("cmdtwo", "qfaketwo")):
            (self.bin / exe).write_text('#!/usr/bin/env python3\nimport json,sys\nfrom pathlib import Path\n'
                                       'Path.cwd().parent.joinpath("out/report.md").write_text("DONE\\n")\n'
                                       'print(json.dumps(sys.argv[1:]))\n')
            (self.bin / exe).chmod(0o755)
            doc = {"schema": 2, "kind": "provider", "provider": provider, "family": None, "surface": "local",
                   "models": copy.deepcopy(self.models), "agents": None, "resources": {},
                   "capabilities": {k: copy.deepcopy(cell) for k in ("per_dispatch_model_override", "per_dispatch_effort_override", "read_only_barrier")},
                   "barrier": {"kind": "sandbox-args"}, "dispatch": {"mode": "command", "argv": [exe,
                       "--base", "{member}", "--model", "{model}", {"if": "effort", "then": ["--effort", "{effort}"]}],
                       "class_argv": {"read-only": ["--ro"]}, "prompt": {"via": "stdin"}, "output": {"format": "text"}}}
            self.definitions[provider] = doc
            self.install(provider, doc)
        self.sequence = 0

    def git(self, *args):
        p = subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        return p.stdout

    def save_answers(self):
        (self.conf / "projects/demo.json").write_text(json.dumps(self.answers))

    def install(self, name, doc, verify=True):
        path = self.lib / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "definition.json").write_text(json.dumps(doc))
        p = subprocess.run([sys.executable, "-I", str(ROOT / "tests/handseal.py"), str(path)], env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(p.returncode, 0, p.stderr)
        if verify and doc["kind"] == "provider":
            P = R.P
            P.record_verification(name, {k: {"hash": P.definition_hash(name), "by": "attest", "at": "2026-11-02", "note": "fixture"}
                                         for k in doc["capabilities"]})

    def cmd(self, *args, code=0):
        p = subprocess.run([str(ROOT / "bin/qargi"), *map(str, args)], env=self.env, cwd=self.repo,
                           capture_output=True, text=True, timeout=30)
        self.assertEqual(p.returncode, code, p.stdout + p.stderr)
        return p.stdout + p.stderr

    def prepare(self, *args):
        self.sequence += 1
        out = self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "fixture-" + str(self.sequence),
                       "--scratch", self.root, *args)
        self.run = Path(next(l[4:] for l in out.splitlines() if l.startswith("RUN=")))
        (self.run / "task.md").write_text("TASK: offline argv\nDONE: true\n")
        self.store = A.Store(self.run)
        self.record = Path(self.store.path) / "state.json"
        return out

    def request(self):
        return self.store.show()["prepared"]["request"]

    def argv(self, *args):
        self.cmd("local", "run", self.run, *args)
        return json.loads((self.run / "out/transcript").read_text())

    def test_ordinary_default_and_explicit_profile_run_two_providers(self):
        out = self.prepare()
        self.assertIn("MODEL=fake-balanced", out)
        self.assertEqual(self.argv(), ["--base", "worker", "--model", "fake-balanced", "--effort", "much"])
        self.answers["models"]["provider"]["local"] = "cmdtwo"
        self.answers["profiles"] = {"quick": {"base": "worker", "tier": "fast", "effort": "low"}}
        self.save_answers()
        out = self.prepare("--profile", "quick")
        self.assertIn("MODEL=fake-fast", out)
        self.assertEqual(self.argv(), ["--base", "worker", "--model", "fake-fast", "--effort", "little"])
        self.assertEqual(self.request()["runtime"], "cmdtwo")

    def test_alias_and_id_catalog_policy_and_unaliased_tier(self):
        catalog = dict(self.models, schema=2, kind="catalog", family="fakecat")
        self.install("fakecat", catalog)
        for use, model in (("alias", "depth"), ("id", "fake-deep")):
            doc = copy.deepcopy(self.definitions["cmdtwo"])
            doc["models"] = {"catalog": "fakecat", "use": use}
            self.install("cmdtwo", doc)
            self.answers["models"]["provider"]["local"] = "cmdtwo"
            self.save_answers()
            self.prepare("--role", "review")
            self.assertEqual(self.argv(), ["--base", "reviewer", "--model", model, "--effort", "much", "--ro"])
            self.prepare("--role", "review", "--profile", "auditor")
            self.assertEqual(self.argv(), ["--base", "reviewer", "--model", "fake-fast", "--effort", "little", "--ro"])

    def test_implicit_role_profile_and_class_fallback(self):
        role = self.conf / "roles/checker"
        role.mkdir(parents=True)
        (role / "role.json").write_text('{"class":"write","description":"fixture"}')
        (role / "ROLE.md").write_text("Fixture checker.\n")
        self.prepare("--role", "checker")
        self.assertEqual(self.request()["profile"], "build")
        self.assertEqual(self.argv()[2:], ["--model", "fake-balanced", "--effort", "much"])
        self.answers["profiles"] = {"checker": {"base": "worker", "tier": "deep", "effort": "low"}}
        self.save_answers()
        self.prepare("--role", "checker")
        self.assertEqual(self.request()["profile"], "checker")
        self.assertEqual(self.argv()[2:], ["--model", "fake-deep", "--effort", "little"])

    def test_explicit_overrides_null_controls_and_empty_values(self):
        self.prepare()
        original = self.request()
        self.assertEqual(self.argv("--model", "deep", "--effort", "low")[2:], ["--model", "fake-deep", "--effort", "little"])
        self.assertEqual(self.argv("--again", "--effort", "max")[2:], ["--model", "fake-balanced"])
        for flag in ("--model", "--effort"):
            self.assertIn("--" + flag[2:], self.cmd("local", "run", self.run, "--dry-run", flag, "", code=2))
        self.assertIn("current catalog", self.cmd("local", "run", self.run, "--dry-run", "--model", "other", code=2))
        self.assertEqual(self.request(), original)
        self.assertEqual(self.argv("--again")[2:], ["--model", "fake-balanced", "--effort", "much"])

    def test_prepared_null_effort_control_keeps_requested_level(self):
        doc = copy.deepcopy(self.definitions["cmdone"])
        doc["models"]["effort"] = None
        self.install("cmdone", doc)
        self.prepare()
        self.assertEqual(self.request()["effort"], "high")
        self.assertEqual(self.argv(), ["--base", "worker", "--model", "fake-balanced"])
        self.assertEqual(self.argv("--again", "--effort", "low"), ["--base", "worker", "--model", "fake-balanced"])
        self.assertEqual(self.request()["effort"], "high")

    def test_unverified_overrides_refuse_but_prepared_requests_are_not_claims(self):
        self.install("cmdone", self.definitions["cmdone"], verify=False)
        (self.state / "providers/cmdone/verified.json").unlink()
        self.prepare()
        self.assertEqual(self.argv()[2:], ["--model", "fake-balanced", "--effort", "much"])
        for args in (("--model", "deep"), ("--effort", "low")):
            self.assertIn("not supported", self.cmd("local", "run", self.run, "--dry-run", *args, code=2))
        self.assertEqual(self.argv("--again", "--model", "fake-balanced", "--effort", "high")[2:],
                         ["--model", "fake-balanced", "--effort", "much"])

    def test_mutated_run_mirrors_never_select_request_or_accept_drift(self):
        self.prepare("--role", "review", "--profile", "auditor")
        for name, text in (("profile", "researcher"), ("ability", "build"), ("class", "write"),
                           ("request.json", '{"runtime":"cmdtwo","model":"fake-deep"}')):
            (self.run / name).write_text(text)
        self.assertEqual(self.argv(), ["--base", "reviewer", "--model", "fake-fast", "--effort", "little", "--ro"])

    def test_saved_evidence_and_retry_retain_private_request_despite_forged_mirrors(self):
        self.prepare()
        request = self.request()
        self.argv()
        (self.run / "request.json").write_text('{"model":"forged"}')
        self.cmd("local", "verify", self.run)
        saved = self.state / "runs" / self.run.name
        self.assertEqual(json.loads((saved / "request.json").read_text()), request)
        (saved / "request.json").write_text('{"model":"also-forged"}')
        self.argv("--again", "--model", "fast", "--effort", "low")
        self.assertEqual(self.request(), request)
        self.assertEqual(json.loads((Path(self.store.path) / "a1.saved.1/request.json").read_text()), {"model": "also-forged"})
        # The saved mirror is evidence, not a source for a retry's selection.
        self.assertEqual(self.argv("--again")[2:], ["--model", "fake-balanced", "--effort", "much"])

    def tree(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob("*") if p.is_file() and not p.is_symlink()}

    def test_dry_success_and_drift_leave_all_bytes_unchanged(self):
        self.prepare()
        before = self.tree()
        self.cmd("local", "run", self.run, "--dry-run")
        self.assertEqual(self.tree(), before)
        self.answers["profiles"] = {"build": {"tier": "fast"}}
        self.save_answers()
        before = self.tree()
        self.assertIn("re-prepare", self.cmd("local", "run", self.run, "--dry-run", code=2))
        self.assertEqual(self.tree(), before)

    def test_runtime_mode_catalog_profile_and_policy_drift_refuse_before_launch(self):
        for change in ("runtime", "mode", "catalog", "profile", "policy", "dispatch"):
            with self.subTest(change=change):
                self.answers.pop("profiles", None)
                self.answers["models"] = {"provider": {"local": "cmdone"}}
                self.save_answers()
                self.install("cmdone", self.definitions["cmdone"])
                self.prepare()
                request = self.request()
                if change == "runtime":
                    self.answers["models"]["provider"]["local"] = "cmdtwo"
                elif change == "profile":
                    self.answers["profiles"] = {"build": {"effort": "low"}}
                elif change == "policy":
                    (self.state / "providers/cmdone/verified.json").unlink()
                else:
                    doc = copy.deepcopy(self.definitions["cmdone"])
                    if change == "mode":
                        doc["dispatch"] = {"mode": "in-session"}
                    elif change == "catalog":
                        doc["models"]["tiers"]["*"]["model"] = "fake-changed"
                    else:
                        doc["dispatch"]["argv"].append("changed")
                    self.install("cmdone", doc)
                self.save_answers()
                (self.run / "request.json").write_text(json.dumps(request))
                self.assertIn("re-prepare", self.cmd("local", "run", self.run, code=2))
                self.assertFalse((self.run / "out/transcript").exists())
                self.assertEqual(self.request(), request)

    def test_referenced_catalog_only_drift_preserves_previous_output(self):
        catalog = dict(self.models, schema=2, kind="catalog", family="fakecat")
        self.install("fakecat", catalog)
        doc = copy.deepcopy(self.definitions["cmdone"])
        doc["models"] = {"catalog": "fakecat", "use": "alias"}
        self.install("cmdone", doc)
        self.prepare()
        self.assertEqual(self.argv()[2:], ["--model", "middle", "--effort", "much"])
        transcript = (self.run / "out/transcript").read_bytes()
        catalog["tiers"]["deep"]["model"] = "fake-updated"
        self.install("fakecat", catalog)
        self.assertIn("re-prepare", self.cmd("local", "run", self.run, "--again", "--model", "fast", code=2))
        self.assertEqual((self.run / "out/transcript").read_bytes(), transcript)

    def test_missing_executable_and_unsupported_barrier(self):
        self.prepare()
        (self.bin / "qfakeone").unlink()
        self.assertIn("not on PATH", self.cmd("local", "run", self.run, code=3))
        self.assertFalse((self.run / "dispatch.json").exists())
        doc = copy.deepcopy(self.definitions["cmdone"])
        doc["barrier"] = {"kind": "none"}
        doc["capabilities"].pop("read_only_barrier")
        self.install("cmdone", doc)
        before = set(self.root.glob("qargi.*"))
        self.assertIn("no read-only barrier", self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "refused",
                                                      "--scratch", self.root, "--role", "review", code=2))
        self.assertEqual(set(self.root.glob("qargi.*")), before)

    def test_malformed_profiles_and_private_requests_refuse_without_adoption(self):
        for entry in (None, [], {"effort": None}, {"tier": "unknown"}, {"base": "reviewer"}):
            self.answers["profiles"] = {"build": entry}
            self.save_answers()
            before = set(self.root.glob("qargi.*"))
            self.cmd("local", "prepare", "--repo", self.repo, "--base", "main", "--slug", "invalid", "--scratch", self.root, code=2)
            self.assertEqual(set(self.root.glob("qargi.*")), before)
        self.answers.pop("profiles")
        self.save_answers()
        self.prepare()
        original = self.record.read_bytes()
        for key, value in (("model", []), ("effort", None), ("mode", "in-session"), ("binding", {}), ("extra", True)):
            bad = json.loads(original)
            bad["prepared"]["request"][key] = value
            self.record.write_bytes(A.encode(bad))
            self.assertIn("prepared", self.cmd("local", "run", self.run, "--dry-run", code=2))
            self.assertEqual(self.record.read_bytes(), A.encode(bad))
        bad = json.loads(original)
        bad["prepared"].pop("request")
        self.record.write_bytes(A.encode(bad))
        self.assertIn("re-prepare", self.cmd("local", "run", self.run, "--dry-run", code=2))



if __name__ == "__main__":
    unittest.main(verbosity=2)
