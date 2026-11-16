#!/usr/bin/env python3
"""Public campaign CLI, direct script and reviewed store in hermetic state.

The store suite owns deep transaction fault injection. Here representative real
faults verify native report transport and one-call CLI delegation.
"""
import hermetic  # noqa: F401
import contextlib
import copy
import errno
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
import campaign as CLI  # noqa: E402
import campaign_doc as D  # noqa: E402
import campaign_store as S  # noqa: E402
from test_campaign_doc import CAMPAIGN, DIGEST, document, json_bytes, link  # noqa: E402
from test_campaign_store import snapshot  # noqa: E402


class Campaign(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.state = self.root / "state"
        self.conf = self.root / "conf"
        self.spec = self.root / "spec.json"
        self.value = document()
        self.spec.write_bytes(json_bytes(self.value))
        # Do not let hermetic.py's Python wrapper hide a missing public -B.
        runtime = self.root / "bin"
        runtime.mkdir()
        (runtime / "python3").symlink_to(sys.executable)
        self.env = dict(os.environ, HOME=str(self.home), QARGI_CONF=str(self.conf),
                        QARGI_STATE=str(self.state), PATH=str(runtime) + os.pathsep + os.environ["PATH"],
                        QARGI_PROJECT="unregistered", ANTHROPIC_PROFILE="unavailable")
        self.env.pop("QARGI_MEMBER_RUN", None)
        self.prefix = [str(ROOT / "bin" / "qargi"), "campaign"]

    def run_cli(self, *args, code=0, direct=False, cwd=None, env=None, native=True):
        prefix = [sys.executable, "-I", str(ROOT / "lib" / "campaign.py")] if direct else self.prefix
        result = subprocess.run(prefix + list(args), cwd=cwd or self.root, env=env or self.env,
                                capture_output=True, text=True, timeout=20, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        if native:
            report = json.loads(result.stdout)
            self.assertEqual((report["format"], report["version"], report["valid"]),
                             ("campaign-report", 1, code == 0))
            self.assertEqual(report["constants"]["authority"], "declarations-only")
            self.assertEqual(report["constants"]["invalidation_policy"], "undecided")
            return report
        return result

    def create(self):
        return self.run_cli("commit", CAMPAIGN, "--spec", str(self.spec), "--create", "--json")

    def test_documented_external_example(self):
        text = (ROOT / "docs/reference/campaign-records.md").read_text()
        blocks = re.findall(r"^```(json|sh)\n(.*?)^```$", text, re.M | re.S)
        self.assertEqual([kind for kind, _ in blocks], ["json", "sh"])
        for _, body in blocks:
            self.assertTrue(all(len(line) <= 80 for line in body.splitlines()))
        raw = blocks[0][1].encode("utf-8")
        value = D.decode(raw)
        normalized = D.transition(None, value, rev=1)
        self.assertTrue(all(p["qargi_project"] is None for p in normalized["participants"]))
        (self.root / "campaign.json").write_bytes(raw)
        # Execute the literal documented shell, through the public dispatcher.
        (self.root / "bin/qargi").symlink_to(ROOT / "bin/qargi")
        result = subprocess.run(["bash", "-eu", "-c", blocks[1][1]], cwd=self.root,
                                env=self.env, capture_output=True, text=True,
                                timeout=20, stdin=subprocess.DEVNULL)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        def report(name):
            return json.loads((self.root / name).read_text())
        created, shown = report("created.json"), report("shown.json")
        updated, retried = report("updated.json"), report("update-retry.json")
        self.assertEqual(shown["document"], normalized)
        self.assertEqual(created["revision"], shown["revision"])
        self.assertEqual(report("create-retry.json")["result"], "already-current")
        self.assertEqual((updated["result"], updated["revision"]["rev"]), ("committed", 2))
        self.assertEqual(updated["revision"]["previous"], created["revision"]["digest"])
        self.assertEqual(retried["revision"], updated["revision"])
        self.assertEqual(retried["result"], "already-current")
        current = self.run_cli("show", value["campaign"], "--json")
        self.assertEqual(current["document"]["work"][0]["design"]["rev"], 2)
        self.assertFalse(self.conf.exists())

    def update(self, previous, label="changed"):
        self.value["label"] = label
        self.spec.write_bytes(json_bytes(self.value))
        return self.run_cli("commit", CAMPAIGN, "--spec", str(self.spec),
                            "--expected-head", previous, "--json")

    def direct_main(self, args):
        output = io.StringIO()
        old_cwd = os.getcwd()
        try:
            os.chdir(self.root)
            with patch.dict(os.environ, self.env, clear=True), contextlib.redirect_stdout(output):
                code = CLI.main(args + ["--json"])
        finally:
            os.chdir(old_cwd)
        report = json.loads(output.getvalue())
        self.assertEqual(report["valid"], code == 0)
        return code, report

    def test_create_update_retry_and_conflict(self):
        created = self.create()
        self.assertEqual((created["result"], created["publication"], created["durability"]),
                         ("committed", "visible", "fsync-acknowledged"))
        self.assertEqual(self.create()["result"], "already-current")
        first = created["revision"]["digest"]
        updated = self.update(first)
        retry = self.run_cli("commit", CAMPAIGN, "--spec", str(self.spec),
                             "--expected-head=" + first, "--json", direct=True)
        self.assertEqual((retry["result"], retry["revision"]), ("already-current", updated["revision"]))
        self.value["label"] = "another candidate"
        self.spec.write_bytes(json_bytes(self.value))
        before = snapshot(self.root)
        conflict = self.run_cli("commit", CAMPAIGN, "--spec", str(self.spec),
                                "--expected-head", first, "--json", code=1)
        self.assertEqual(conflict["findings"][0]["code"], "conflict")
        self.assertEqual(conflict["current_head"], updated["revision"]["digest"])
        self.assertEqual(conflict["candidate_in_history"], "not-checked")
        self.assertEqual(conflict["publication"], "none")
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse(self.conf.exists())

    def test_current_reads_are_immutable_and_native(self):
        created = self.create()
        before = snapshot(self.root)
        caches = snapshot(ROOT / "lib" / "__pycache__")
        for direct in (False, True):
            shown = self.run_cli("show", CAMPAIGN, "--json", direct=direct)
            self.assertEqual(shown["document"], D.validate(self.value))
            self.assertEqual(shown["durability"], "not-assessed")
            checked = self.run_cli("check", CAMPAIGN, "--json", direct=direct)
            self.assertEqual(checked["transition"], "checked-create")
            page = self.run_cli("log", CAMPAIGN, "--limit=1", "--json", direct=direct)
            self.assertEqual(page["entries"], [created["revision"]])
            self.assertTrue(page["complete"])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(snapshot(ROOT / "lib" / "__pycache__"), caches)

    def test_malformed_oversized_and_schema_inputs_create_no_state(self):
        cases = [(b'{"version":1,"version":1}', "duplicate-json-key", "$"),
                 (b"{", "invalid-json", "$"), (b"x" * (D.MAX_SPEC_BYTES + 1), "bounds", "$"),
                 (json_bytes(dict(self.value, objective=0)), "schema", "$.objective")]
        for raw, expected, path in cases:
            self.spec.write_bytes(raw)
            before = snapshot(self.root)
            for args in (("check", "--spec", str(self.spec)),
                         ("commit", CAMPAIGN, "--spec", str(self.spec), "--create")):
                result = self.run_cli(*args, "--json", code=1)
                self.assertEqual(result["findings"][0]["code"], expected)
                self.assertEqual(result["findings"][0]["path"], path)
            self.assertEqual(snapshot(self.root), before)

    def test_input_symlink_modes_and_special_files(self):
        self.spec.chmod(0o644)
        (self.root / "selected").symlink_to(self.spec)
        self.run_cli("check", "--spec=selected", "--json")
        for filename in ("--json", "-h", "file with spaces.json"):
            (self.root / filename).write_bytes(json_bytes(self.value))
            self.run_cli("check", "--spec=" + filename, "--json")
        fifo = self.root / "fifo"
        os.mkfifo(fifo)
        for filename in (fifo, self.root, Path(os.devnull), self.root / "missing"):
            result = self.run_cli("check", "--spec", str(filename), "--json", code=1)
            self.assertEqual(result["findings"][0]["code"], "storage-error")
        self.assertFalse(self.state.exists())

    def test_spec_reads_are_bounded_even_if_file_size_changes(self):
        opened = os.open(self.spec, os.O_RDONLY)
        self.addCleanup(os.close, opened)
        amounts = []
        def read(_fd, amount):
            amounts.append(amount)
            return b" " * amount
        with patch.object(CLI.os, "open", return_value=opened), patch.object(CLI.os, "close"), \
                patch.object(CLI.os, "read", side_effect=read):
            with self.assertRaises(D.Invalid) as raised:
                CLI.read_spec(str(self.spec))
        self.assertEqual(raised.exception.code, "bounds")
        self.assertEqual(sum(amounts), D.MAX_SPEC_BYTES + 1)

    def test_pure_member_check_does_not_probe_configuration_or_state(self):
        blocker = self.root / "unavailable"
        blocker.write_text("not a directory")
        env = dict(self.env, QARGI_MEMBER_RUN="1", QARGI_CONF=str(blocker / "config"),
                   QARGI_STATE=str(blocker / "state"), QARGI_HOME=str(blocker / "home"))
        before, caches = snapshot(self.root), snapshot(ROOT / "lib" / "__pycache__")
        for direct in (False, True):
            report = self.run_cli("check", "--spec", str(self.spec), "--json", env=env, direct=direct)
            self.assertEqual(report["transition"], "not-checked")
            self.assertEqual(report["constants"]["coordination_scope"], "supplied-document")
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(snapshot(ROOT / "lib" / "__pycache__"), caches)

    def test_pure_route_imports_no_backend_and_calls_no_path_helpers(self):
        source = r'''
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import campaign, paths
assert 'campaign_store' not in sys.modules
def refused(*a, **k):
    raise AssertionError('unexpected path probe')
with patch.multiple(paths, **{n: refused for n in ('banner', 'state', 'conf', 'root', 'installed_tool_root')}), patch('os.getcwd', refused), patch('os.stat', refused):
    code = campaign.main(['check', '--spec', sys.argv[2], '--json'])
assert 'campaign_store' not in sys.modules
raise SystemExit(code)
'''
        result = subprocess.run([sys.executable, "-B", "-I", "-c", source, str(ROOT / "lib"), str(self.spec)],
                                cwd=self.root, env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)["valid"])

    def test_members_refused_for_all_state_verbs_at_cli_script_and_store(self):
        env = dict(self.env, QARGI_MEMBER_RUN="1")
        before = snapshot(self.root)
        forms = [("commit", CAMPAIGN, "--spec", str(self.spec), "--create"),
                 ("commit", CAMPAIGN, "--spec", str(self.spec), "--expected-head", DIGEST),
                 ("show", CAMPAIGN), ("show", CAMPAIGN, "--revision", DIGEST),
                 ("check", CAMPAIGN), ("log", CAMPAIGN)]
        for args in forms:
            for direct in (False, True):
                report = self.run_cli(*args, "--json", code=1, env=env, direct=direct)
                self.assertEqual(report["findings"][0]["code"], "lead-only")
        with patch.dict(os.environ, env, clear=True):
            backend = S.Store(CAMPAIGN)
            for operation in (lambda: backend.commit(self.value, create=True), backend.show, backend.check, backend.log):
                with self.assertRaises(S.Error) as raised:
                    operation()
                self.assertEqual(raised.exception.code, "lead-only")
        self.assertEqual(snapshot(self.root), before)

    def test_usage_errors_are_stderr_only_with_and_without_json(self):
        forms = [[], ["list"], ["check"], ["check", CAMPAIGN, "--spec", str(self.spec)],
                 ["check", "--spec"], ["check", "--spec="], ["show", "bad-id"],
                 ["commit", CAMPAIGN, "--spec", str(self.spec)],
                 ["commit", CAMPAIGN, "--spec", str(self.spec), "--create", "--expected-head", DIGEST],
                 ["commit", CAMPAIGN, "--spec", str(self.spec), "--create=yes"],
                 ["show", CAMPAIGN, "--revision", "bad-digest"],
                 ["check", "--spe", str(self.spec)], ["check", "--spec", str(self.spec), "--spec", str(self.spec)],
                 ["show", CAMPAIGN, "--json", "--json"], ["show", CAMPAIGN, "--json=true"],
                 ["log", CAMPAIGN, "--limit", "1", "--limit=2"],
                 *[["log", CAMPAIGN, "--limit=" + v] for v in ("0", "201", "01", "-1", "1.0", "1e2", "9" * 1000, "١")]]
        before = snapshot(self.root)
        for args in forms:
            for suffix in ([], ["--json"] if "--json" not in args else []):
                result = self.run_cli(*args, *suffix, code=2, native=False)
                self.assertEqual(result.stdout, "")
                self.assertIn("invalid arguments", result.stderr)
        self.assertEqual(snapshot(self.root), before)

    def test_missing_state_and_bad_cursor_are_native_failures_without_writes(self):
        before = snapshot(self.root)
        for args in (("show", CAMPAIGN), ("check", CAMPAIGN), ("log", CAMPAIGN),
                     ("commit", CAMPAIGN, "--spec", str(self.spec), "--expected-head", DIGEST)):
            report = self.run_cli(*args, "--json", code=1)
            self.assertEqual(report["findings"][0]["code"], "not-found")
        report = self.run_cli("log", CAMPAIGN, "--cursor=untrusted", "--json", code=1)
        self.assertEqual(report["findings"][0]["code"], "cursor")
        self.assertEqual((report["entries"], report["complete"]), ([], False))
        self.assertEqual(snapshot(self.root), before)

    def test_log_pages_and_historical_show_prove_selected_ancestry(self):
        first = self.create()["revision"]["digest"]
        second = self.update(first)["revision"]["digest"]
        third = self.update(second, "third")["revision"]["digest"]
        page = self.run_cli("log", CAMPAIGN, "--limit", "2", "--json")
        self.assertEqual([e["digest"] for e in page["entries"]], [third, second])
        self.assertFalse(page["complete"])
        tail = self.run_cli("log", CAMPAIGN, "--cursor", page["cursor"], "--json")
        self.assertEqual([e["digest"] for e in tail["entries"]], [first])
        self.assertTrue(tail["complete"])
        self.assertEqual(tail["verified_scope"], "selected-head-ancestry")
        self.assertEqual(tail["revision"]["digest"], third)
        shown = self.run_cli("show", CAMPAIGN, "--revision=" + first, "--json")
        self.assertEqual((shown["revision"]["digest"], shown["selected_head"]), (first, third))
        # A byte-valid sibling is an orphan, never committed history.
        sibling = copy.deepcopy(self.value)
        sibling["label"] = "orphan"
        record, raw = S._candidate(None, sibling)
        target = self.state / "campaigns" / CAMPAIGN / "objects" / (record["digest"][7:] + ".json")
        target.write_bytes(raw)
        target.chmod(0o600)
        shown = self.run_cli("show", CAMPAIGN, "--revision", record["digest"], "--json", code=1)
        self.assertEqual(shown["findings"][0]["code"], "not-in-history")
        cursor = "v1:" + record["digest"][7:] + ":" + record["digest"][7:]
        failed = self.run_cli("log", CAMPAIGN, "--cursor", cursor, "--json", code=1)
        self.assertEqual((failed["entries"], failed["complete"]), ([], False))

    def test_public_history_bound_has_no_successful_partial_page(self):
        self.create()
        objdir = self.state / "campaigns" / CAMPAIGN / "objects"
        value = dict(self.value, participants=[], requirements=[], work=[], coordination=[])
        previous, first = None, None
        for rev in range(1, S.MAX_HISTORY_EDGES + 3):
            value["label"] = str(rev)
            raw = json_bytes(dict(format="campaign-revision", version=1, rev=rev,
                                  previous=previous, document=value))
            digest = "sha256:" + hashlib.sha256(raw).hexdigest()
            target = objdir / (digest[7:] + ".json")
            target.write_bytes(raw)
            target.chmod(0o600)
            previous = digest
            if first is None:
                first = digest
        head = self.state / "campaigns" / CAMPAIGN / "head.json"
        head.write_bytes(json_bytes(dict(format="campaign-head", version=1, rev=rev, revision=digest)))
        cursor = "v1:" + digest[7:] + ":" + first[7:]
        before = snapshot(self.state)
        failed = self.run_cli("log", CAMPAIGN, "--cursor", cursor, "--json", code=1)
        self.assertEqual(failed["findings"][0]["code"], "history-walk-limit")
        self.assertEqual((failed["entries"], failed["complete"]), ([], False))
        failed = self.run_cli("show", CAMPAIGN, "--revision", first, "--json", code=1)
        self.assertEqual(failed["findings"][0]["code"], "history-walk-limit")
        self.run_cli("show", CAMPAIGN, "--json")
        self.assertEqual(snapshot(self.state), before)

    def test_lock_and_private_state_failures(self):
        self.create()
        lock = self.state / "campaigns" / CAMPAIGN / ".lock"
        with lock.open("rb") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            report = self.run_cli("commit", CAMPAIGN, "--spec", str(self.spec), "--create", "--json", code=1)
        self.assertEqual(report["findings"][0]["code"], "lock-busy")
        self.assertEqual(report["publication"], "not-assessed")
        head = lock.parent / "head.json"
        head.chmod(0o644)
        before = snapshot(self.root)
        report = self.run_cli("show", CAMPAIGN, "--json", code=1)
        self.assertEqual(report["findings"][0]["code"], "private-state")
        self.assertEqual(snapshot(self.root), before)

    def test_real_store_uncertainty_is_transported_without_retry(self):
        self.create()
        calls = []
        original = S.Store.commit
        def once(backend, *args, **kwargs):
            calls.append(backend)
            return original(backend, *args, **kwargs)
        with patch.object(S.Store, "commit", once), \
                patch.object(S._Session, "settle", side_effect=OSError(errno.EIO, "injected")):
            code, report = self.direct_main(["commit", CAMPAIGN, "--spec", str(self.spec), "--create"])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual((report["findings"][0]["code"], report["publication"], report["durability"]),
                         ("durability-unknown", "visible", "unknown"))
        self.assertEqual(self.create()["result"], "already-current")

    def test_child_parent_and_postpublication_uncertainty_keep_outcomes(self):
        first = self.create()["revision"]["digest"]
        self.value["label"] = "child"
        self.spec.write_bytes(json_bytes(self.value))
        args = ["commit", CAMPAIGN, "--spec", str(self.spec), "--expected-head", first]
        with patch.object(S._Session, "settle", side_effect=OSError(errno.EIO, "injected")):
            code, report = self.direct_main(args)
        self.assertEqual(code, 1)
        self.assertEqual((report["publication"], report["durability"], report["parent_durability"]),
                         ("none", "not-assessed", "unknown"))
        settle = S._Session.settle
        calls = []
        def fail_after_publication(session, head):
            calls.append(head)
            if len(calls) == 2:
                raise OSError(errno.EIO, "injected")
            return settle(session, head)
        with patch.object(S._Session, "settle", fail_after_publication):
            code, report = self.direct_main(args)
        self.assertEqual(code, 1)
        self.assertEqual((report["publication"], report["durability"]), ("visible", "unknown"))
        self.assertEqual(report["findings"][0]["code"], "durability-unknown")
        retry = self.run_cli(*args, "--json")
        self.assertEqual(retry["result"], "already-current")

    def test_unknown_publication_and_history_details_are_preserved(self):
        # Deep ambiguous-effect injection belongs to test_campaign_store.py.
        # These API failures isolate CLI transport without inferring success.
        error = S.Error("publication-unknown", publication="unknown", durability="unknown", stage="replace")
        with patch.object(S.Store, "commit", side_effect=error) as call:
            code, report = self.direct_main(["commit", CAMPAIGN, "--spec", str(self.spec), "--create"])
        self.assertEqual(call.call_count, 1)
        self.assertEqual((code, report["publication"], report["durability"], report["stage"]),
                         (1, "unknown", "unknown", "replace"))

    def test_references_and_content_are_never_opened_or_executed(self):
        fifo = self.root / "target"
        os.mkfifo(fifo)
        self.value["participants"][0]["locator"] = str(fifo)
        self.value["work"][0]["source"]["ref"] = str(fifo)
        self.value["work"][0]["links"] = [link(target=dict(kind="ref", ref=str(fifo)))]
        self.value["provenance"]["basis"] = "$(touch should-not-exist)"
        self.spec.write_bytes(json_bytes(self.value))
        self.run_cli("check", "--spec", str(self.spec), "--json")
        self.create()
        for verb in ("show", "check", "log"):
            self.run_cli(verb, CAMPAIGN, "--json")
        self.assertFalse((self.root / "should-not-exist").exists())
        self.assertFalse(self.conf.exists())

    def test_safe_text_and_ordinary_json_escaping(self):
        self.value["label"] = "label\u202e reversing"
        self.value["objective"] = "line one\nline two"
        self.spec.write_bytes(json_bytes(self.value))
        self.create()
        result = self.run_cli("show", CAMPAIGN, native=False)
        self.assertNotIn(self.value["label"], result.stdout)
        self.assertNotIn(self.value["objective"], result.stdout)
        self.assertTrue(result.stdout.isascii())
        result = self.run_cli("show", CAMPAIGN, "--json", native=False)
        self.assertIn("\\u202e", result.stdout)
        self.assertEqual(json.loads(result.stdout)["document"]["label"], self.value["label"])
        self.spec.write_bytes(b'{"objective":"\\u001b[31m"}')
        result = self.run_cli("check", "--spec", str(self.spec), code=1, native=False)
        self.assertNotIn("\x1b", result.stdout + result.stderr)

    def test_dev_banner_is_stderr_and_json_remains_native(self):
        (self.home / ".qargi" / "config").mkdir(parents=True)
        (self.home / ".qargi" / "config" / "install.json").write_text(json.dumps(dict(tool_root="/unavailable/tool")))
        env = {k: v for k, v in self.env.items() if k not in ("QARGI_STATE", "QARGI_CONF", "QARGI_HOME")}
        pure = self.run_cli("check", "--spec", str(self.spec), "--json", env=env, native=False)
        self.assertEqual(pure.stderr, "")
        # A backend fixture prevents access to the checkout's own dev state.
        source = r'''
import sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import campaign, campaign_store
with patch.object(campaign_store.Store, 'show', side_effect=campaign_store.Error('not-found')):
    raise SystemExit(campaign.main(['show', sys.argv[2], '--json']))
'''
        result = subprocess.run([sys.executable, "-B", "-I", "-c", source, str(ROOT / "lib"), CAMPAIGN],
                                cwd=self.root, env=env, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("qargi: dev run from", result.stderr)
        self.assertFalse(json.loads(result.stdout)["valid"])

    def test_deleted_cwd_has_structured_state_refusal_and_pure_check_works(self):
        removed = self.root / "removed"
        removed.mkdir()
        source = r'''
import json, os, subprocess, sys
os.chdir(sys.argv[2]); os.rmdir(sys.argv[2])
for prefix in ([sys.argv[1] + '/bin/qargi', 'campaign'], [sys.executable, '-I', sys.argv[1] + '/lib/campaign.py']):
    for args, expected in ((['check', '--spec', sys.argv[3], '--json'], 0), (['show', sys.argv[4], '--json'], 1)):
        p = subprocess.run(prefix + args, capture_output=True, text=True, timeout=10)
        assert p.returncode == expected, (p.returncode, p.stdout, p.stderr)
        assert 'Traceback' not in p.stderr
        report = json.loads(p.stdout)
        assert report['valid'] == (expected == 0)
        if expected:
            assert report['findings'][0]['code'] == 'lead-only'
print('deleted cwd: public and direct reports qualified')
'''
        result = subprocess.run([sys.executable, "-B", "-I", "-c", source, str(ROOT),
                                 str(removed), str(self.spec), CAMPAIGN], env=self.env,
                                cwd=self.root, capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("public and direct reports qualified", result.stdout)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
