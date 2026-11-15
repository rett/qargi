#!/usr/bin/env python3
"""Local campaign store fixtures with injected I/O and actual child processes.

These tests qualify syscall outcomes and process interruption on the test
filesystem. They make no power-loss claim. Fixtures isolate caller classification
in their own processes with explicit mocks. Real member refusal cases use the
unmodified helper. Every configured state path belongs to a scratch directory.
"""
import hermetic  # noqa: F401
import errno
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import campaign_doc as C  # noqa: E402
import campaign_store as S  # noqa: E402
from test_campaign_doc import CAMPAIGN, Q, document, json_bytes, link, participant  # noqa: E402


def digest(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def snapshot(root):
    """Capture names, inode identities, metadata and bytes without following links."""
    result = {}
    for path in [root, *sorted(root.rglob("*"))] if root.exists() else []:
        st = path.lstat()
        result[str(path.relative_to(root))] = (
            st.st_ino, st.st_mode, st.st_nlink, st.st_uid, st.st_size, st.st_mtime_ns,
            path.read_bytes() if stat.S_ISREG(st.st_mode) else
            os.readlink(path) if path.is_symlink() else None)
    return result


def write_private(path, raw):
    path.write_bytes(raw)
    path.chmod(0o600)


WORKER = r'''
import json, os, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import campaign_store as S
campaign, mode = sys.argv[2:4]
request = json.loads(sys.argv[4])
original = S._Session.publish_object
temporary = S._Session.temporary
settle = S._Session.settle
def held(self, *args):
    print("locked", flush=True)
    sys.stdin.buffer.read(1)
    return original(self, *args)
def held_head(self, *args):
    result = temporary(self, *args)
    if args[2] == ".head-":
        print("prepared", flush=True)
        sys.stdin.buffer.read(1)
    return result
def held_visible(self, head):
    if head["revision"] != request.get("expected_head"):
        print("visible", flush=True)
        sys.stdin.buffer.read(1)
    return settle(self, head)
print("ready", flush=True)
sys.stdin.buffer.read(1)
# Test-process caller isolation is authorized by the component task. The state
# root remains the scratch path inherited from the parent fixture.
with patch.object(S.marshal_refs, "in_member_run", return_value=False):
    try:
        if mode == "hold":
            with patch.object(S._Session, "publish_object", held):
                result = S.Store(campaign).commit(**request)
        elif mode == "hold-head":
            with patch.object(S._Session, "temporary", held_head):
                result = S.Store(campaign).commit(**request)
        elif mode == "hold-visible":
            with patch.object(S._Session, "settle", held_visible):
                result = S.Store(campaign).commit(**request)
        else:
            result = S.Store(campaign).commit(**request)
        print(json.dumps(result), flush=True)
    except S.Error as error:
        print(json.dumps(dict(code=error.code, **error.details)), flush=True)
'''


class CampaignStore(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.env = patch.dict(os.environ, QARGI_STATE=str(self.state))
        self.env.start()
        self.addCleanup(self.env.stop)
        # Only this unit fixture's caller classification is isolated. No live
        # paths or production bypass switches are used. Refusal tests undo it.
        self.caller = patch.object(S.marshal_refs, "in_member_run", return_value=False)
        self.caller.start()
        self.addCleanup(self.caller.stop)
        self.store = S.Store(CAMPAIGN)
        self.campaign = self.state / "campaigns" / CAMPAIGN
        self.objects = self.campaign / "objects"

    def error(self, code, function, *args, **kwargs):
        with self.assertRaises(S.Error) as caught:
            function(*args, **kwargs)
        error = caught.exception
        self.assertEqual(error.code, code, repr(error.details))
        self.assertTrue(str(error).isascii())
        self.assertTrue(all(c.isprintable() for c in str(error)))
        return error

    def create(self):
        return self.store.commit(document(), create=True)["revision"]["digest"]

    def child(self, previous, label="Changed declaration"):
        doc = self.store.show()["document"]
        doc["label"] = label
        result = self.store.commit(doc, expected_head=previous)
        return result["revision"]["digest"]

    def object_path(self, value):
        return self.objects / (value[7:] + ".json")

    def chain(self, length, *, maximum=False):
        """Direct immutable fixtures avoid thousands of fsync-heavy commits.

        Each envelope remains a genuine hash of canonical schema-valid bytes.
        A label change makes every successive declaration a valid transition.
        """
        self.create()
        doc = C.validate(document())
        for group in C.LIMITS:
            doc[group] = []
        if maximum:
            doc["requirements"] = [dict(id="r1:req%d" % i, text="x" * 2048,
                                        state="active") for i in range(128)]
            doc["work"] = []
            doc["coordination"] = []
            while len(json_bytes(doc)) > C.MAX_DOCUMENT_BYTES:
                delta = len(json_bytes(doc)) - C.MAX_DOCUMENT_BYTES
                entry = next(r for r in reversed(doc["requirements"]) if len(r["text"]) > 1)
                entry["text"] = entry["text"][:max(1, len(entry["text"]) - delta)]
            doc = C.validate(doc)
        previous, ids = None, []
        for rev in range(1, length + 1):
            # Fixed label width preserves the maximum-document byte boundary.
            doc["label"] = "%09d" % rev if not maximum else ("%09d" % rev).ljust(len(doc["label"]), "x")
            envelope = dict(format="campaign-revision", version=1, rev=rev,
                            previous=previous, document=doc)
            raw = json_bytes(envelope)
            self.assertLessEqual(len(raw), C.MAX_REVISION_BYTES)
            previous = digest(raw)
            write_private(self.object_path(previous), raw)
            ids.append(previous)
        write_private(self.campaign / "head.json", json_bytes(dict(
            format="campaign-head", version=1, rev=length, revision=previous)))
        return ids

    def test_create_update_reorder_retry_conflicts(self):
        first = self.create()
        before = snapshot(self.root)
        doc = document()
        for key in C.LIMITS:
            doc[key].reverse()
        result = self.store.commit(doc, create=True)
        self.assertEqual(result["result"], "already-current")
        self.assertEqual(result["revision"]["digest"], first)
        self.assertEqual(snapshot(self.root), before)
        second = self.child(first)
        child = document()
        child["label"] = "Changed declaration"
        before = snapshot(self.root)
        retry = self.store.commit(child, expected_head=first)
        self.assertEqual(retry["result"], "already-current")
        self.assertEqual(retry["durability"], "fsync-acknowledged")
        self.assertEqual(snapshot(self.root), before)
        self.error("no-change", self.store.commit, child, expected_head=second)
        self.error("conflict", self.store.commit, document(), create=True)
        third = self.child(second, "Later declaration")
        before = snapshot(self.root)
        conflict = self.error("conflict", self.store.commit, child, expected_head=first)
        self.assertEqual(conflict.details["current_head"], third)
        self.assertEqual(conflict.details["candidate"], second)
        self.assertEqual(conflict.details["candidate_in_history"], "not-checked")
        self.error("conflict", self.store.commit, child, expected_head="sha256:" + "0" * 64)
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(self.store.check()["transition"], "checked-current-parent")

    def test_invalid_input_and_absent_operations_create_nothing(self):
        before = snapshot(self.root)
        for method in (self.store.show, self.store.check, self.store.log):
            self.error("not-found", method)
        self.error("not-found", self.store.commit, document(), expected_head="sha256:" + "0" * 64)
        for doc in ({}, dict(document(), campaign="00000000-0000-0000-0000-000000000001")):
            self.error("schema" if not doc else "identity-mismatch", self.store.commit, doc, create=True)
        doc = document()
        doc["work"][1]["design"]["rev"] = 2
        self.error("transition", self.store.commit, doc, create=True)
        for kwargs in ({}, dict(create=True, expected_head="bad"), dict(create=1)):
            self.error("schema", self.store.commit, document(), **kwargs)
        for cursor in ("bad", "v1:" + "A" * 64 + ":" + "0" * 64, 1):
            self.error("cursor", self.store.log, cursor=cursor)
        for limit in (0, 201, True, 1.5):
            self.error("bounds", self.store.log, limit=limit)
        self.assertEqual(snapshot(self.root), before)
        self.create()
        before = snapshot(self.root)
        doc = document()
        doc["work"][0]["participant"] = "00000000-0000-0000-0000-000000000001"
        self.error("reference", self.store.commit, doc, expected_head=self.store.show()["revision"]["digest"])
        self.assertEqual(snapshot(self.root), before)

    def test_update_normalization_and_invalid_transition_are_read_only(self):
        first = self.create()
        doc = document()
        doc["participants"].append(participant(Q))
        doc["requirements"].append(dict(id="r2:another", text="Another requirement", state="active"))
        doc["work"][0]["requirements"].append("r2:another")
        doc["work"][0]["links"] = [link("evaluation"), link("outcome")]
        second = self.store.commit(doc, expected_head=first)["revision"]["digest"]
        for key in C.LIMITS:
            doc[key].reverse()
        for work in doc["work"]:
            work["requirements"].reverse()
            work["links"].reverse()
        before = snapshot(self.root)
        retry = self.store.commit(doc, expected_head=first)
        self.assertEqual(retry["result"], "already-current")
        self.assertEqual(retry["revision"]["digest"], second)
        self.assertEqual(snapshot(self.root), before)
        doc["requirements"].append(dict(id="r1:retired", text="Invalid old birth", state="active"))
        with patch.object(S.os, "fsync", side_effect=AssertionError("invalid transition synced")):
            self.error("identity", self.store.commit, doc, expected_head=second)
        self.assertEqual(snapshot(self.root), before)

    def test_real_member_helper_refuses_every_state_entry(self):
        self.caller.stop()
        before = snapshot(self.root)
        # The real task-run marker is preserved. An explicit marker also tests
        # a member that has changed its working directory.
        with patch.dict(os.environ, QARGI_MEMBER_RUN="fixture-member"), \
                patch.object(S.paths, "state", side_effect=AssertionError("state resolved")):
            for method, args, kwargs in ((self.store.show, (), {}), (self.store.check, (), {}),
                                         (self.store.log, (), {}),
                                         (self.store.commit, (document(),), dict(create=True))):
                self.error("lead-only", method, *args, **kwargs)
            C.validate(document())
            C.transition(None, document(), rev=1)
        member = self.root / "member"
        member.mkdir()
        (member / "ability").write_text("build")
        (member / "refs.before").write_text("")
        self.assertTrue(S.marshal_refs.in_member_run(str(member)))
        # The real helper also refuses from the prepared-run directory when
        # the environment marker is absent. No classification mock is loaded.
        code = r'''
import json, sys
sys.path.insert(0, sys.argv[1])
import campaign_store as S
store = S.Store(sys.argv[2])
document = json.loads(sys.argv[3])
codes = []
for operation in (store.show, store.check, store.log,
                  lambda: store.commit(document, create=True)):
    try:
        operation()
    except S.Error as error:
        codes.append(error.code)
print(json.dumps(codes))
'''
        env = dict(os.environ)
        env.pop("QARGI_MEMBER_RUN", None)
        result = subprocess.run([sys.executable, "-B", "-I", "-c", code,
                                 str(Path(S.__file__).parent), CAMPAIGN, json.dumps(document())],
                                cwd=member, env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["lead-only"] * 4)
        # All store state remains absent. Marker fixture files are separate.
        self.assertEqual(snapshot(self.state), {})
        self.assertEqual(list(before), ["."])

    def test_root_alias_resolution_once_and_permissions(self):
        target = self.root / "trusted" / "missing" / "state"
        (self.root / "trusted").mkdir()
        alias = self.root / "alias"
        alias.symlink_to(self.root / "trusted", target_is_directory=True)
        with patch.object(S.paths, "state", return_value=str(alias / "missing" / "state")) as choose:
            self.create()
            self.store.show()
            self.store.check()
            self.assertEqual(choose.call_count, 1)
        self.assertTrue((target / "campaigns" / CAMPAIGN / "head.json").exists())
        for path in (target, target / "campaigns", target / "campaigns" / CAMPAIGN):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o700)
        for mode in (0o755, 0o750, 0o711):
            target.chmod(mode)
            self.store.show()
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), mode)
        target.chmod(0o770)
        before = snapshot(self.root)
        self.error("private-state", self.store.show)
        self.assertEqual(snapshot(self.root), before)

    def test_reads_never_mutate_lock_create_fsync_or_repair(self):
        ids = self.chain(4)
        before = snapshot(self.root)
        source = Path(S.__file__).parent
        bytecode = sorted(source.rglob("*.pyc"))
        with patch.object(S.fcntl, "flock", side_effect=AssertionError("read locked")), \
                patch.object(S.os, "fsync", side_effect=AssertionError("read synced")), \
                patch.object(S.os, "mkdir", side_effect=AssertionError("read created")):
            self.store.show()
            self.store.show(ids[0])
            self.store.check()
            first = self.store.log(limit=2)
            last = self.store.log(cursor=first["cursor"], limit=2)
            self.assertTrue(last["complete"])
            self.assertEqual(last["selected_start"], ids[-1])
        self.assertEqual(snapshot(self.root), before)
        self.assertEqual(sorted(source.rglob("*.pyc")), bytecode)
        (self.campaign / ".lock").unlink()
        self.assertEqual(self.store.show()["revision"]["digest"], ids[-1])
        self.assertFalse((self.campaign / ".lock").exists())

    def test_private_descendants_and_files(self):
        first = self.create()
        files = [self.campaign / "head.json", self.object_path(first), self.campaign / ".lock"]
        for path in files:
            original = path.read_bytes()
            for mode in (0o644, 0o400, 0o660):
                path.chmod(mode)
                before = snapshot(self.root)
                method = (lambda: self.store.commit(document(), create=True)) if path.name == ".lock" else self.store.show
                self.error("private-state", method)
                self.assertEqual(snapshot(self.root), before)
            path.chmod(0o600)
            other = path.with_name("saved-file")
            path.rename(other)
            for kind in ("symlink", "hardlink", "fifo", "directory"):
                if kind == "symlink":
                    path.symlink_to(other)
                elif kind == "hardlink":
                    os.link(other, path)
                elif kind == "fifo":
                    os.mkfifo(path, 0o600)
                else:
                    path.mkdir(mode=0o700)
                before = snapshot(self.root)
                self.error("private-state", method)
                self.assertEqual(snapshot(self.root), before)
                path.rmdir() if kind == "directory" else path.unlink()
            other.rename(path)
            self.assertEqual(path.read_bytes(), original)
        for path in (self.state / "campaigns", self.campaign, self.objects):
            path.chmod(0o750)
            before = snapshot(self.root)
            self.error("private-state", self.store.show)
            self.assertEqual(snapshot(self.root), before)
            path.chmod(0o700)
            other = path.with_name(path.name + "-saved")
            path.rename(other)
            path.symlink_to(other, target_is_directory=True)
            before = snapshot(self.root)
            self.error("private-state", self.store.show)
            self.assertEqual(snapshot(self.root), before)
            path.unlink()
            other.rename(path)
        with patch.object(S.os, "geteuid", return_value=os.geteuid() + 1):
            self.error("private-state", self.store.show)

    def test_corrupt_heads_and_objects(self):
        first = self.create()
        headpath = self.campaign / "head.json"
        original = headpath.read_bytes()
        head = json.loads(original)
        bad_heads = [original + b" ", b'{"format":1,"format":2}', b"\xff", b"[",
                     b" " * 513, json_bytes(dict(head, rev=True)),
                     json_bytes(dict(head, version=True)), json_bytes(dict(head, extra=1)),
                     json_bytes(dict(head, revision="sha256:" + "A" * 64)),
                     json_bytes(dict(head, rev=2)), original.replace(b'"rev":1', b'"rev":1.0')]
        for raw in bad_heads:
            write_private(headpath, raw)
            before = snapshot(self.root)
            self.error("corrupt-store", self.store.show)
            self.assertEqual(snapshot(self.root), before)
        write_private(headpath, original)
        objpath = self.object_path(first)
        raw = objpath.read_bytes()
        for invalid in (raw + b" ", b"[]", b"x" * (C.MAX_REVISION_BYTES + 1)):
            write_private(objpath, invalid)
            self.error("corrupt-store", self.store.show)
        write_private(objpath, raw)
        record = json.loads(raw)
        invalid_records = [dict(record, rev=0), dict(record, rev=True), dict(record, previous=first),
                           dict(record, rev=2, previous=None), dict(record, extra=1),
                           dict(record, document=dict(record["document"], campaign="00000000-0000-0000-0000-000000000001"))]
        for value in invalid_records:
            invalid = json_bytes(value)
            ident = digest(invalid)
            write_private(self.object_path(ident), invalid)
            write_private(headpath, json_bytes(dict(head, revision=ident, rev=value["rev"])))
            self.error("corrupt-store", self.store.show)
        # A correctly hashed but noncanonical document order is still refused.
        record["document"]["work"].reverse()
        invalid = json_bytes(record)
        ident = digest(invalid)
        write_private(self.object_path(ident), invalid)
        write_private(headpath, json_bytes(dict(head, revision=ident)))
        self.error("corrupt-store", self.store.show)

    def test_hash_valid_noncanonical_envelopes_are_refused(self):
        first = self.create()
        original = self.object_path(first).read_bytes()
        value = json.loads(original)
        noncanonical = [original + b" ",
                        original.replace(b'campaign-revision', b'c\\u0061mpaign-revision'),
                        (json.dumps(dict(reversed(list(value.items())))) + "\n").encode(),
                        original.replace(b'"rev":1', b'"rev":1,"rev":1'),
                        original.replace(b'"version":1', b'"version":1.0')]
        for raw in noncanonical:
            ident = digest(raw)
            write_private(self.object_path(ident), raw)
            write_private(self.campaign / "head.json", json_bytes(dict(
                format="campaign-head", version=1, rev=1, revision=ident)))
            before = snapshot(self.root)
            self.error("corrupt-store", self.store.show)
            self.assertEqual(snapshot(self.root), before)

    def test_missing_references_sequence_and_resource_errors(self):
        ids = self.chain(3)
        self.object_path(ids[1]).unlink()
        self.error("corrupt-store", self.store.check)
        self.error("corrupt-store", self.store.log)
        self.error("not-found", self.store.show, ids[1])
        with patch.object(S, "_read", side_effect=OSError(errno.EIO, "secret free text")):
            self.error("storage-error", self.store.show)
        with patch.object(S, "_read", side_effect=MemoryError):
            self.error("bounds", self.store.log)
        head = dict(format="campaign-revision", version=1, rev=4, previous=ids[0], document=C.validate(document()))
        raw = json_bytes(head)
        ident = digest(raw)
        write_private(self.object_path(ident), raw)
        write_private(self.campaign / "head.json", json_bytes(dict(format="campaign-head", version=1,
                                                                 rev=4, revision=ident)))
        self.error("corrupt-store", self.store.log)
        self.error("corrupt-store", self.store.check)
        self.objects.rename(self.campaign / "missing-objects")
        self.error("corrupt-store", self.store.show)

    def test_lock_identity_before_publication(self):
        first = self.create()
        original = S._Session.temporary

        def replace_lock(session, *args):
            result = original(session, *args)
            if args[2] == ".head-":
                old = self.campaign / ".lock"
                old.rename(self.campaign / ".old-lock")
                write_private(old, b"")
            return result

        with patch.object(S._Session, "temporary", replace_lock):
            error = self.error("lock-replaced", self.child, first)
        self.assertEqual(error.details["publication"], "none")
        self.assertEqual(self.store.show()["revision"]["digest"], first)

    def test_lock_identity_immediately_after_flock(self):
        self.create()
        original = S.fcntl.flock

        def replace_lock(fd, flags):
            original(fd, flags)
            (self.campaign / ".lock").rename(self.campaign / ".old-lock")
            write_private(self.campaign / ".lock", b"")

        with patch.object(S.fcntl, "flock", replace_lock):
            error = self.error("lock-replaced", self.store.commit, document(), create=True)
        self.assertEqual(error.details["publication"], "none")

    def test_object_reuse_is_exact_bytes_and_not_membership(self):
        first = self.create()
        doc = dict(document(), label="orphan")
        candidate, raw = S._candidate(dict(json.loads(self.object_path(first).read_bytes()), digest=first), doc)
        second = candidate["digest"]
        write_private(self.object_path(second), raw)
        self.error("not-in-history", self.store.show, second)
        before_ino = self.object_path(second).stat().st_ino
        result = self.store.commit(doc, expected_head=first)
        self.assertEqual(result["revision"]["digest"], second)
        self.assertEqual(self.object_path(second).stat().st_ino, before_ino)
        third_doc = dict(doc, label="next orphan")
        candidate, raw = S._candidate(candidate, third_doc)
        write_private(self.object_path(candidate["digest"]), raw + b" ")
        before = snapshot(self.root)
        self.error("corrupt-store", self.store.commit, third_doc, expected_head=second)
        self.assertEqual(snapshot(self.root), before)

    def test_read_selects_one_head_during_replacement(self):
        first = self.create()
        original = S._Session.head
        calls = []

        def swap(session):
            result = original(session)
            calls.append(result)
            if len(calls) == 1:
                # A separate Store performs a normal commit after the snapshot.
                with patch.object(S._Session, "head", original):
                    self.child(first)
            return result

        with patch.object(S._Session, "head", swap):
            result = self.store.log(limit=1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["selected_head"], first)
        self.assertEqual(result["entries"][0]["digest"], first)
        self.assertTrue(result["complete"])
        self.assertNotEqual(self.store.show()["revision"]["digest"], first)

    def test_forged_cursor_orphans_and_page_scope(self):
        ids = self.chain(6)
        first = self.store.log(limit=2)
        self.assertEqual([e["digest"] for e in first["entries"]], ids[-1:-3:-1])
        self.assertFalse(first["complete"])
        final_cursor = "v1:" + ids[-1][7:] + ":" + ids[0][7:]
        final = self.store.log(cursor=final_cursor)
        self.assertTrue(final["complete"])
        self.assertEqual(len(final["entries"]), 1)
        self.assertIsNone(final["cursor"])
        self.assertEqual(final["verified_scope"], "selected-head-ancestry")
        self.error("cursor", self.store.log, cursor="v1:" + ids[1][7:] + ":" + ids[2][7:])
        orphan, raw = S._candidate(None, dict(document(), label="uncommitted orphan"))
        write_private(self.object_path(orphan["digest"]), raw)
        orphan_cursor = "v1:" + orphan["digest"][7:] + ":" + orphan["digest"][7:]
        before = snapshot(self.root)
        error = self.error("not-in-history", self.store.log, cursor=orphan_cursor)
        self.assertEqual(error.details["entries"], [])
        self.error("not-in-history", self.store.log,
                   cursor="v1:" + ids[-1][7:] + ":" + orphan["digest"][7:])
        self.assertEqual(snapshot(self.root), before)

    def test_history_4095_4096_4097_edges_and_advancing_head(self):
        ids = self.chain(4098)
        started = time.monotonic()
        for edges in (4095, 4096):
            result = self.store.show(ids[-1 - edges])
            self.assertEqual(result["revision"]["digest"], ids[-1 - edges])
        self.error("history-walk-limit", self.store.show, ids[0])
        cursor = "v1:" + ids[-1][7:] + ":" + ids[1][7:]
        result = self.store.log(cursor=cursor, limit=1)
        self.assertEqual(result["entries"][0]["rev"], 2)
        error = self.error("history-walk-limit", self.store.log, cursor=cursor, limit=2)
        self.assertEqual(error.details["entries"], [])
        self.assertFalse(error.details["complete"])
        self.error("history-walk-limit", self.store.log, cursor=result["cursor"], limit=1)
        # A pinned start one revision behind the head shares the traversal
        # budget with the path to next and the page. It is not charged twice.
        shared = "v1:" + ids[-2][7:] + ":" + ids[2][7:]
        result = self.store.log(cursor=shared, limit=2)
        self.assertEqual([e["rev"] for e in result["entries"]], [3, 2])
        old_cursor = "v1:" + ids[-2][7:] + ":" + ids[1][7:]
        self.store.log(cursor=old_cursor, limit=1)
        self.child(ids[-1], "advanced")
        self.error("history-walk-limit", self.store.log, cursor=old_cursor, limit=1)
        self.assertEqual(self.store.show()["revision"]["rev"], 4099)
        self.store.check()
        print("representative small-object 4096-edge queries %.3fs" % (time.monotonic() - started))

    def test_conservative_aggregate_history_read_bound(self):
        # Inject only the chain I/O. The ordinary Store entry point still
        # performs real root/head validation and all schema/hash/edge checks.
        # Small documents exercise the worst object count without reading 1 GiB.
        self.create()
        doc = C.validate(document())
        for key in C.LIMITS:
            doc[key] = []
        chain, previous = {}, None
        for rev in range(1, 4099):
            raw = json_bytes(dict(format="campaign-revision", version=1, rev=rev,
                                  previous=previous, document=doc))
            previous = digest(raw)
            chain[previous[7:] + ".json"] = raw
        write_private(self.campaign / "head.json", json_bytes(dict(
            format="campaign-head", version=1, rev=4098, revision=previous)))
        orphan, raw1 = S._candidate(None, dict(doc, label="orphan root"))
        other, raw2 = S._candidate(orphan, dict(doc, label="orphan child"))
        chain[orphan["digest"][7:] + ".json"] = raw1
        chain[other["digest"][7:] + ".json"] = raw2
        original = S._read
        counts = []

        def injected(parent, name, limit):
            if name == "head.json":
                return original(parent, name, limit)
            raw = chain[name]
            counts.append(len(raw))
            return raw

        cursor = "v1:" + other["digest"][7:] + ":" + orphan["digest"][7:]
        with patch.object(S, "_read", injected):
            self.error("not-in-history", self.store.log, cursor=cursor)
        self.assertEqual(len(counts), 4099)
        self.assertLessEqual(sum(counts) + S.MAX_HEAD_BYTES,
                             4099 * C.MAX_REVISION_BYTES + S.MAX_HEAD_BYTES)
        self.assertEqual(4099 * C.MAX_REVISION_BYTES + S.MAX_HEAD_BYTES, 1074528768)

    def test_page_default_maximum_and_bounded_ordinary_reads(self):
        ids = self.chain(220)
        self.assertEqual(len(self.store.log()["entries"]), 50)
        self.assertEqual(len(self.store.log(limit=200)["entries"]), 200)
        original = S._read
        for method in (self.store.show, self.store.check,
                       lambda: self.store.commit(dict(document(), label="retry-conflict"), expected_head=ids[0])):
            reads = []

            def tracked(parent, name, limit):
                reads.append(name)
                return original(parent, name, limit)

            with patch.object(S, "_read", tracked), \
                    patch.object(S.os, "listdir", side_effect=AssertionError("directory scan")):
                try:
                    method()
                except S.Error as error:
                    self.assertEqual(error.code, "conflict")
            objects = [n for n in reads if n != "head.json"]
            self.assertLessEqual(len(objects), 2, reads)
        reads = []
        with patch.object(S, "_read", tracked):
            self.child(ids[-1])
        self.assertLessEqual(len(set(n for n in reads if n != "head.json")), 2)

    def test_maximum_objects_aggregate_bytes_and_memory(self):
        ids = self.chain(16, maximum=True)
        original = S._read
        sizes = []

        def tracked(*args):
            raw = original(*args)
            sizes.append(len(raw))
            return raw

        started = time.monotonic()
        tracemalloc.start()
        try:
            with patch.object(S, "_read", tracked):
                result = self.store.log(limit=16)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["entries"]), 16)
        self.assertGreater(max(sizes), C.MAX_REVISION_BYTES - 20)
        self.assertLessEqual(sum(sizes), 16 * C.MAX_REVISION_BYTES + S.MAX_HEAD_BYTES)
        self.assertLess(peak, 12 * 1024 * 1024)
        print("maximum-document 16-object page bytes=%d peak=%d elapsed=%.3fs" %
              (sum(sizes), peak, time.monotonic() - started))
        self.assertEqual(self.store.show(ids[0])["revision"]["rev"], 1)
        # Two nine-digit revisions exercise actual 256 KiB envelopes without
        # constructing a billion-revision fixture. check visits only this pair.
        envelope = json.loads(self.object_path(ids[-1]).read_bytes())
        envelope.update(rev=C.MAX_REV - 1, previous="sha256:" + "0" * 64)
        raw = json_bytes(envelope)
        self.assertEqual(len(raw), C.MAX_REVISION_BYTES)
        parent = digest(raw)
        write_private(self.object_path(parent), raw)
        envelope.update(rev=C.MAX_REV, previous=parent)
        envelope["document"]["label"] = "x" * len(envelope["document"]["label"])
        raw = json_bytes(envelope)
        self.assertEqual(len(raw), C.MAX_REVISION_BYTES)
        ident = digest(raw)
        write_private(self.object_path(ident), raw)
        write_private(self.campaign / "head.json", json_bytes(dict(
            format="campaign-head", version=1, rev=C.MAX_REV, revision=ident)))
        self.assertEqual(self.store.check()["revision"]["digest"], ident)
        self.assertEqual(self.store.show()["revision"]["rev"], C.MAX_REV)
        self.error("bounds", self.store.commit, dict(envelope["document"], label="last edit"),
                   expected_head=ident)

    def worker(self, request, mode="normal"):
        process = subprocess.Popen([sys.executable, "-B", "-I", "-c", WORKER,
                                    str(Path(S.__file__).parent), CAMPAIGN, mode, json.dumps(request)],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   env=dict(os.environ), text=True)
        self.addCleanup(self.stop_worker, process)
        self.assertEqual(self.line(process), "ready")
        return process

    @staticmethod
    def stop_worker(process):
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)

    def line(self, process):
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            self.assertTrue(selector.select(15), "worker output deadline")
        return process.stdout.readline().strip()

    @staticmethod
    def release(process):
        process.stdin.write("x")
        process.stdin.flush()

    def finish(self, process):
        output, errors = process.communicate(timeout=20)
        self.assertEqual(process.returncode, 0, errors)
        return json.loads(output)

    def test_actual_subprocess_competing_and_identical_writers(self):
        first = self.create()
        doc = dict(document(), label="subprocess child")
        request = dict(document=doc, expected_head=first)
        holder = self.worker(request, "hold")
        self.release(holder)
        self.assertEqual(self.line(holder), "locked")
        other = self.worker(request)
        self.release(other)
        self.assertEqual(self.finish(other)["code"], "lock-busy")
        self.release(holder)
        result = self.finish(holder)
        self.assertEqual(result["result"], "committed")
        identical = self.worker(request)
        self.release(identical)
        self.assertEqual(self.finish(identical)["result"], "already-current")
        competing = self.worker(dict(document=dict(doc, label="different child"), expected_head=first))
        self.release(competing)
        self.assertEqual(self.finish(competing)["code"], "conflict")

    def test_process_kill_before_publication_leaves_parent(self):
        first = self.create()
        request = dict(document=dict(document(), label="interrupted child"), expected_head=first)
        process = self.worker(request, "hold")
        self.release(process)
        self.assertEqual(self.line(process), "locked")
        process.send_signal(signal.SIGKILL)
        process.communicate(timeout=10)
        self.assertEqual(self.store.show()["revision"]["digest"], first)
        self.assertEqual(self.store.commit(**request)["result"], "committed")

    def test_process_kill_at_prepared_and_visible_boundaries(self):
        first = self.create()
        lock_inode = (self.campaign / ".lock").stat().st_ino
        for mode, marker in (("hold-head", "prepared"), ("hold-visible", "visible")):
            with self.subTest(mode=mode):
                request = dict(document=dict(document(), label=mode), expected_head=first)
                process = self.worker(request, mode)
                self.release(process)
                self.assertEqual(self.line(process), marker)
                selected = self.store.show()["revision"]["digest"]
                self.assertEqual(selected == first, mode == "hold-head")
                process.send_signal(signal.SIGKILL)
                process.communicate(timeout=10)
                retry = self.store.commit(**request)
                self.assertEqual(retry["result"], "committed" if mode == "hold-head" else "already-current")
                first = retry["revision"]["digest"]
                self.assertEqual((self.campaign / ".lock").stat().st_ino, lock_inode)

    def test_all_fsync_boundaries_and_retry_settlement(self):
        first = self.create()
        doc = dict(document(), label="fault boundary child")
        # Record the real successful syscall order, then inject one failure at
        # every position in a fresh copy of the same private state tree.
        import shutil
        template = self.root / "template"
        shutil.copytree(self.state, template)
        real_fsync = S.os.fsync
        trace = []
        real_replace = S.os.replace
        visible = [False]

        def replaced(src, dst, **kwargs):
            result = real_replace(src, dst, **kwargs)
            if dst == "head.json":
                visible[0] = True
            return result

        def record(fd):
            trace.append((visible[0], os.readlink("/proc/self/fd/%d" % fd)))
            return real_fsync(fd)

        with patch.object(S.os, "fsync", record), patch.object(S.os, "replace", replaced):
            second = self.store.commit(doc, expected_head=first)["revision"]["digest"]
        self.assertTrue(any(v for v, _ in trace))
        self.assertTrue(any(not v for v, _ in trace))
        for index, (was_visible, _) in enumerate(trace):
            with self.subTest(fsync=index, visible=was_visible):
                shutil.rmtree(self.state)
                shutil.copytree(template, self.state)
                count = [0]

                def fail(fd):
                    position = count[0]
                    count[0] += 1
                    if position == index:
                        raise OSError(errno.EIO, "injected I/O failure")
                    return real_fsync(fd)

                with patch.object(S.os, "fsync", fail):
                    error = self.error("durability-unknown" if was_visible else "storage-error",
                                       self.store.commit, doc, expected_head=first)
                self.assertEqual(error.details["publication"], "visible" if was_visible else "none")
                self.assertEqual(self.store.show()["revision"]["digest"], second if was_visible else first)
                settled = self.store.commit(doc, expected_head=first)
                self.assertEqual(settled["result"], "already-current" if was_visible else "committed")
        # Exact-current and different-child parent settlement have distinct
        # publication fields even when the same first fsync fails.
        with patch.object(S.os, "fsync", side_effect=OSError(errno.EIO, "injected")):
            retry = self.error("durability-unknown", self.store.commit, doc, expected_head=first)
            self.assertEqual(retry.details["publication"], "visible")
            self.assertEqual(retry.details["durability"], "unknown")
            error = self.error("storage-error", self.store.commit, dict(doc, label="different"), expected_head=second)
            self.assertEqual(error.details["publication"], "none")
            self.assertEqual(error.details["parent_durability"], "unknown")

    def test_creation_fsync_links_and_publication_write_failures(self):
        import shutil
        trace = []
        real_fsync = S.os.fsync

        def record(fd):
            trace.append(os.readlink("/proc/self/fd/%d" % fd))
            return real_fsync(fd)

        with patch.object(S.os, "fsync", record):
            self.create()
        # Directory creation syncs the new directory before its parent link.
        self.assertEqual(trace[:2], [str(self.state), str(self.root)])
        for index in range(len(trace)):
            shutil.rmtree(self.state)
            calls = [0]

            def fail(fd):
                position = calls[0]
                calls[0] += 1
                if position == index:
                    raise OSError(errno.EIO, "injected creation fsync")
                return real_fsync(fd)

            with patch.object(S.os, "fsync", fail):
                with self.assertRaises(S.Error) as caught:
                    self.create()
            error = caught.exception
            published = (self.campaign / "head.json").exists()
            self.assertEqual(error.details["publication"], "visible" if published else "none")
            self.assertEqual(error.code, "durability-unknown" if published else "storage-error")
            self.store.commit(document(), create=True)
        first = self.store.show()["revision"]["digest"]
        for target in ("object", "head"):
            real_replace = S.os.replace

            def fail_replace(src, dst, **kwargs):
                if (dst == "head.json") == (target == "head"):
                    raise OSError(errno.EIO, "injected replace")
                return real_replace(src, dst, **kwargs)

            doc = dict(document(), label="replace-" + target)
            with patch.object(S.os, "replace", fail_replace):
                error = self.error("storage-error", self.store.commit, doc, expected_head=first)
            self.assertEqual(error.details["publication"], "none")
            self.assertEqual(self.store.show()["revision"]["digest"], first)
        with patch.object(S.os, "write", side_effect=OSError(errno.ENOSPC, "injected full disk")):
            error = self.error("storage-error", self.store.commit,
                               dict(document(), label="write failure"), expected_head=first)
        self.assertEqual(error.details["publication"], "none")

    def test_object_and_head_temporary_open_and_write_failures(self):
        first = self.create()
        original_open, original_write = S._open, S.os.write
        for stage in (".tmp-", ".head-"):
            for operation in ("open", "write"):
                with self.subTest(stage=stage, operation=operation):
                    active = [False]

                    def open_file(name, flags, **kwargs):
                        active[0] = name.startswith(stage)
                        if active[0] and operation == "open":
                            raise OSError(errno.ENOSPC, "injected temporary open")
                        return original_open(name, flags, **kwargs)

                    def write_file(fd, data):
                        if active[0] and operation == "write":
                            raise OSError(errno.ENOSPC, "injected temporary write")
                        return original_write(fd, data)

                    doc = dict(document(), label=stage + operation)
                    with patch.object(S, "_open", open_file), patch.object(S.os, "write", write_file):
                        error = self.error("storage-error", self.store.commit, doc, expected_head=first)
                    self.assertEqual(error.details["publication"], "none")
                    self.assertEqual(self.store.show()["revision"]["digest"], first)
        with patch.object(S.os, "write", return_value=0):
            self.error("storage-error", self.store.commit,
                       dict(document(), label="zero write"), expected_head=first)
        # A real partial write is retried until all bytes are on the descriptor.
        def short_write(fd, data):
            return original_write(fd, data[:17])
        with patch.object(S.os, "write", short_write):
            self.child(first, "short write")

    def test_documented_reader_launch_does_not_write_bytecode(self):
        # The real interpreter uses the documented -B launch contract even
        # under -I, which ignores the environment's bytecode hint.
        first = self.create()
        code = r'''
import json, sys
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
import campaign_store as S
with patch.object(S.marshal_refs, "in_member_run", return_value=False):
    print(json.dumps(S.Store(sys.argv[2]).show()))
'''
        source = Path(S.__file__).parent
        before = sorted(source.rglob("*.pyc"))
        env = dict(os.environ)
        env.pop("PYTHONDONTWRITEBYTECODE", None)
        process = subprocess.run([sys.executable, "-B", "-I", "-c", code, str(source), CAMPAIGN],
                                 env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(json.loads(process.stdout)["revision"]["digest"], first)
        self.assertEqual(sorted(source.rglob("*.pyc")), before)


if __name__ == "__main__":
    unittest.main()
