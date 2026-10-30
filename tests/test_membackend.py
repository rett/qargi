#!/usr/bin/env python3
"""Memory backends, the ops executor and split/merge/copy/migrate on random stores. Offline: directories, JSONL
dumps and a fake `ant`. The invariants are checked over many seeded random stores, on both reference backends.
Run: python3 tests/test_membackend.py"""
import hashlib, json, os, random, re, subprocess, sys, tempfile, unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
SEED = os.path.join(ROOT, "provision", "canon-seed")
sys.path.insert(0, LIB)
import canon as C  # noqa: E402
import membackend as B  # noqa: E402
import memplan as P  # noqa: E402

TODAY = "2026-10-29"
SEEDS = range(30)
DIRS = ["/shared/", "/shared/sandbox/", "/roles/build/", "/roles/write/", "/roles/build/tools/", "/_conflicts/2026-01-01/", "/"]
KINDS = ["setup", "gate", "rule", "history"]


def rand_content(r):
    head = ["# Title %d" % r.randrange(50)] if r.random() < .9 else []
    fields = []
    if r.random() < .8:
        fields.append("Kind: %s" % r.choice(KINDS))
    if r.random() < .7:
        fields.append("Applies to: any")
    if r.random() < .6:
        fields.append("Sources: %s" % r.choice(["maintainer, 2026-01-02", "docs/x.md@abc1234", "run 7", "", P.NO_SOURCE]))
    r.shuffle(fields)
    body = ["word%d" % r.randrange(9) for _ in range(r.randrange(0, 4))]
    if r.random() < .15:
        body += ["```", "Sources: inside a fence", "```"]
    text = "\n".join(head + ([""] if head and fields else []) + fields + [""] + body)
    if r.random() < .1:
        text = text.replace("\n", "\r\n")
    if r.random() < .1:
        text = text.rstrip("\n")
    return "" if r.random() < .03 else text


NAMES = ["a", "b", "B", "\u00e9", "a b"]      # upper case, non-ASCII (NFC) and a space are legal names


def rand_store(r, n=None, canon=False):
    s = {}
    for _ in range(r.randrange(0, 14) if n is None else n):
        s[r.choice(DIRS) + r.choice(NAMES) + r.choice(["", "-x"]) + r.choice([".md", ".md", ".sh"])] = rand_content(r)
    if s and r.random() < .25:                # two identical notes at two paths
        s["/twin/" + r.choice(NAMES) + ".md"] = s[r.choice(sorted(s))]
    if s and r.random() < .25:                # an archive entry already where a split would put one, so the .2 suffix runs
        s["/_archive/%s%s" % (TODAY, r.choice(sorted(s)))] = rand_content(r)
    if canon:
        s["/CANON.md"] = "# Canon\n\ncanon: 2\n"
    return s


def rand_pair(r, canon=False):
    """Two stores that share some paths: with the same note, or with different ones."""
    a, b = rand_store(r, canon=canon), rand_store(r, canon=canon)
    for p in sorted(a):
        if r.random() < .3:
            b[p] = a[p] if r.random() < .4 else rand_content(r)
    return a, b


def rand_selector(r):
    k = r.choice(["prefix", "role", "kind", "two"])
    if k == "prefix":
        return {"prefix": [r.choice(DIRS[:5]), r.choice(DIRS[:5])][:r.randrange(1, 3)]}
    if k == "role":
        return {"role": r.choice(["build", "write"])}
    if k == "kind":
        return {"kind": r.choice(KINDS)}
    return {"prefix": ["/roles/"], "kind": r.choice(KINDS)}


def own_placeholder(content):
    """Whether the note's own header Sources: line is exactly the placeholder text (one an earlier copy wrote, or one written by hand)."""
    L = content.split("\n")
    i = P._sources_line(L)
    return i is not None and L[i].rstrip("\r") == "Sources: " + P.NO_SOURCE


class Stores(unittest.TestCase):
    """Each test runs against both reference backends: a directory and a fixture dump."""
    kinds = ("dir", "fixture")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def store(self, kind, files=None):
        self.n += 1
        base = os.path.join(self.tmp.name, "s%d" % self.n)
        if kind == "dir":
            b = B.DirBackend(base)
            for p, c in sorted((files or {}).items()):
                b.create(p, c)
            return b
        return B.FixtureBackend(base + ".jsonl", files)

    def snap(self, b):
        return {p: m["content"] for p, m in b.list().items()}

    def run_plan(self, plan, src, dst):
        return P.apply_plan(plan, {"source": src, "target": dst}, dry_run=False)

    def places(self, p):
        """Where the note that was at p may be afterwards: there, in the archive or the conflicts folder (with a
        suffix after a second collision), or, for an archive entry, back at the path it came from."""
        out = [p] + ["/%s/%s%s%s" % (d, TODAY, p, sfx) for d in ("_archive", "_conflicts") for sfx in ("", ".2", ".3")]
        m = re.match(r"/_archive/[^/]+(/.*?)(?:\.\d)?$", p)
        return out + ([m.group(1)] if m else [])

    def missing(self, before, *after):
        """The paths of `before` whose note is nowhere it may be in any of the stores in `after`. Checked per path:
        two identical notes at two paths are two notes, and losing one of them is a loss."""
        return [p for p, c in sorted(before.items())
                if not any(h in s and P.full(s[h]) == P.full(c) for s in after for h in self.places(p))]

    def each(self, fn):
        for kind in self.kinds:
            for seed in SEEDS:
                with self.subTest(kind=kind, seed=seed):
                    fn(kind, random.Random(seed))


class Contract(Stores):
    def test_create_read_update_move_archive(self):
        for kind in self.kinds:
            with self.subTest(kind=kind):
                b = self.store(kind)
                b.create("/a/x.md", "one")
                self.assertEqual(b.read("/a/x.md")["content"], "one")
                with self.assertRaises(B.StaleError):
                    b.create("/a/x.md", "two")                                  # a create never overwrites
                b.update("/a/x.md", "two", B.digest("one"))
                with self.assertRaises(B.StaleError):
                    b.update("/a/x.md", "three", B.digest("one"))               # stale digest
                b.move("/a/x.md", "/b/y.md", B.digest("two"))
                self.assertEqual(self.snap(b), {"/b/y.md": "two"})
                b.archive("/b/y.md", "/_archive/d/b/y.md", "two!", B.digest("two"))
                self.assertEqual(self.snap(b), {"/_archive/d/b/y.md": "two!"})
                with self.assertRaises(B.StoreError):
                    b.archive("/_archive/d/b/y.md", "/elsewhere.md", "x")      # an archive path is under /_archive/
                self.assertEqual(b.versions("/b/y.md"), [])

    def test_there_is_no_way_to_delete(self):
        for cls in (B.Backend, B.DirBackend, B.FixtureBackend, B.CloudBackend):
            names = [n for n in dir(cls) if not n.startswith("__")]
            self.assertFalse([n for n in names if any(w in n.lower() for w in ("delete", "remove", "purge", "unlink", "rmtree"))], cls)
        with open(os.path.join(LIB, "membackend.py")) as f:
            self.assertNotIn("os.remove", f.read())

    def test_paths_are_checked(self):
        for bad in ("a.md", "/", "/a/", "/a//b", "/a/../b", "/a/./b", "/a\\b", "/a\nb",
                    "/shared/.qargi-xyz", "/.git/config", "/shared/.draft.md", "/a/.hidden/b.md", "/a/b.md ", "/a /b.md", "/a/b.md\t"):
            with self.assertRaises(B.StoreError, msg=bad):
                B.check_path(bad)
        for good in ("/a.md", "/Shared/\u00e9t\u00e9.md", "/a b/c d.md", "/x/y.tar.gz", "/_archive/2026-10-29/a.md"):
            self.assertEqual(B.check_path(good), good)

    def test_what_is_listed_is_what_can_be_stored(self):
        root = os.path.join(self.tmp.name, "d")
        os.makedirs(os.path.join(root, "shared"))
        for name in ("ok.md", ".qargi-tmp", "trailing.md "):
            with open(os.path.join(root, "shared", name), "w") as f:
                f.write("x")
        b = B.DirBackend(root)
        self.assertEqual(sorted(b.list()), ["/shared/ok.md"])
        for p in b.list():
            self.assertIsNone(b.refusal(p))
        self.assertIn("dot", b.refusal("/shared/.draft.md"))
        self.assertIn("255", b.refusal("/" + "x" * 300 + ".md"))

    def test_cloud_limits_are_checked_before_anything_is_written(self):
        c = B.CloudBackend("memstore_T", "/nonexistent/ant")
        self.assertIsNone(c.refusal("/" + "/".join("d%d" % i for i in range(19)) + "/n.md", "x"))
        self.assertIn("segments", c.refusal("/" + "/".join("d%d" % i for i in range(20)) + "/n.md"))
        self.assertIn("1024", c.refusal("/" + "x" * 1030))
        self.assertIn("NFC", c.refusal("/e\u0301.md"))
        self.assertIn("format", c.refusal("/a\u200bb.md"))
        self.assertIn("line-separator", c.refusal("/a\u2028b.md"))
        self.assertIn("102400", c.refusal("/a.md", "x" * 102401))
        self.assertIsNone(c.refusal("/a.md", "x" * 102400))
        self.assertIn("dot", c.refusal("/.hidden.md"))
        with self.assertRaises(B.StoreError):                     # and the backend itself refuses, without calling ant
            c.create("/a.md", "x" * 102401)

    def test_dir_backend_details(self):
        root = os.path.join(self.tmp.name, "d")
        b = B.DirBackend(root)
        self.assertEqual(b.list(), {})                                           # a missing root is an empty store
        self.assertFalse(os.path.exists(root))
        b.create("/shared/a.md", "x")
        with open(os.path.join(root, ".hidden"), "w") as f:
            f.write("not a note")
        os.makedirs(os.path.join(root, ".git"))
        with open(os.path.join(root, ".git", "HEAD"), "w") as f:
            f.write("ref")
        os.symlink("/etc/hostname", os.path.join(root, "link.md"))
        self.assertEqual(sorted(b.list()), ["/shared/a.md"])
        m = b.read("/shared/a.md")
        self.assertEqual(m["content_sha256"], hashlib.sha256(b"x").hexdigest())
        b.update("/shared/a.md", "y")
        m2 = b.read("/shared/a.md")
        self.assertNotEqual(m["id"], m2["id"])                                   # the id names a path and a content
        self.assertEqual(m2["id"], B.DirBackend._id("/shared/a.md", B.digest("y")))
        os.symlink(self.tmp.name, os.path.join(root, "out"))
        with self.assertRaises(B.StoreError):
            b.create("/out/escape.md", "no")                                     # a link out of the store is not followed
        b.move("/shared/a.md", "/other/a.md")
        self.assertFalse(os.path.exists(os.path.join(root, "shared")))           # the emptied folder goes, the note does not
        with open(os.path.join(root, "bin.dat"), "wb") as f:
            f.write(b"\xff\xfe")
        with self.assertRaises(B.StoreError):
            b.list()

    def test_fixture_file_round_trip(self):
        f = os.path.join(self.tmp.name, "x.jsonl")
        with open(f, "w") as h:
            h.write(json.dumps({"type": "memory", "id": "m1", "path": "/a.md", "content": "A"}) + "\n")
            h.write(json.dumps({"type": "memory_store", "id": "s"}) + "\n")
        with open(f + ".tmp", "w") as h:
            h.write("somebody else's temporary file")            # a fixed temporary name would be shared and overwritten
        b = B.FixtureBackend(f)
        self.assertEqual(b.read("/a.md")["id"], "m1")
        b.create("/b.md", "B")
        again = B.FixtureBackend(f)
        self.assertEqual(self.snap(again), {"/a.md": "A", "/b.md": "B"})
        self.assertEqual(B.open_store(f).label, "x")
        with open(f + ".tmp") as h:
            self.assertEqual(h.read(), "somebody else's temporary file")
        with open(f) as h:
            rows = [json.loads(l) for l in h]
        self.assertEqual([r.get("id") for r in rows if r.get("type") != "memory"], ["s"])   # rows that are not memories survive a write
        self.assertEqual(sorted(os.listdir(self.tmp.name)), ["x.jsonl", "x.jsonl.tmp"])

    def test_a_jsonl_dump_is_never_opened_for_writing(self):
        f = os.path.join(self.tmp.name, "x.jsonl")
        B.FixtureBackend(f, {"/a.md": "A"})
        self.assertEqual(B.open_store(f).label, "x")
        with self.assertRaises(B.StoreError) as cm:
            B.open_store(f, write=True)
        self.assertIn("read-only", str(cm.exception))

    def test_dir_backend_survives_what_a_filesystem_can_do(self):
        b = self.store("dir", {"/a/x.md": "A"})
        real_link, real_rmdir = os.link, os.rmdir
        def no_link(*a, **k):
            raise OSError(1, "links not supported here")
        def no_rmdir(*a, **k):
            raise PermissionError(13, "cannot tidy")
        os.link = no_link
        try:
            b.create("/c.md", "C")                                   # a create does not need hard links
        finally:
            os.link = real_link
        self.assertEqual(b.read("/c.md")["content"], "C")
        os.rmdir = no_rmdir
        try:
            b.move("/a/x.md", "/b/x.md", B.digest("A"))              # the move succeeded; failing to tidy the folder is not its failure
        finally:
            os.rmdir = real_rmdir
        self.assertEqual(sorted(self.snap(b)), ["/b/x.md", "/c.md"])
        with self.assertRaises(B.StoreError) as cm:                 # ENAMETOOLONG is a StoreError saying how far the plan got
            B.apply_ops(b, [{"op": "create", "path": "/ok.md", "content": "o"}, {"op": "create", "path": "/" + "x" * 300, "content": "c"}], {}, dry_run=False)
        self.assertIn("1 of 2 steps applied", str(cm.exception))

    def test_the_directory_lock_excludes_other_threads(self):
        import threading, time
        b = self.store("dir", {"/a.md": "A"})
        inside, bad = [], []
        def run():
            for _ in range(5):
                with b.lock():
                    inside.append(1)
                    if len(inside) > 1:
                        bad.append(1)
                    time.sleep(0.01)
                    inside.pop()
        ts = [threading.Thread(target=run) for _ in range(4)]
        [t.start() for t in ts]
        [t.join(30) for t in ts]
        self.assertEqual(bad, [])


class Executor(Stores):
    def test_dry_run_is_the_default(self):
        for kind in self.kinds:
            b = self.store(kind, {"/a.md": "A"})
            ops = [{"op": "create", "path": "/b.md", "content": "B"}, {"op": "archive", "from": "/a.md", "to": "/_archive/d/a.md", "content": "A!"}]
            self.assertEqual(B.apply_ops(b, ops, {"/a.md": B.digest("A")}), ["create /b.md", "archive /a.md -> /_archive/d/a.md"])
            self.assertEqual(self.snap(b), {"/a.md": "A"})
            B.apply_ops(b, ops, {"/a.md": B.digest("A")}, dry_run=False)
            self.assertEqual(self.snap(b), {"/b.md": "B", "/_archive/d/a.md": "A!"})
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "never")))
        B.apply_ops(B.DirBackend(os.path.join(self.tmp.name, "never")), [{"op": "create", "path": "/x.md", "content": "x"}])
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "never")), "a dry run must not even make the folder")

    def test_a_changed_note_fails_closed_and_nothing_changes(self):
        for kind in self.kinds:
            b = self.store(kind, {"/a.md": "A", "/b.md": "B"})
            ops = [{"op": "create", "path": "/c.md", "content": "C"}, {"op": "update", "path": "/a.md", "content": "A2"}]
            exp = {"/a.md": B.digest("A"), "/c.md": None}
            b.update("/a.md", "changed by an agent")
            before = self.snap(b)
            with self.assertRaises(B.StaleError):
                B.apply_ops(b, ops, exp, dry_run=False)
            self.assertEqual(self.snap(b), before)
            b2 = self.store(kind, {"/a.md": "A"})
            b2.create("/c.md", "appeared")
            with self.assertRaises(B.StaleError):                                # a path the plan creates must still be free
                B.apply_ops(b2, ops, {"/a.md": B.digest("A"), "/c.md": None}, dry_run=False)
            self.assertEqual(self.snap(b2), {"/a.md": "A", "/c.md": "appeared"})
            with self.assertRaises(B.StaleError):                                # a step's own sha
                B.apply_ops(b2, [{"op": "update", "path": "/a.md", "content": "z", "sha": "0" * 64}], {}, dry_run=False)

    def test_a_write_between_the_check_and_the_write_is_caught(self):
        class Racy(B.FixtureBackend):
            def create(self, path, content):
                self.notes["/a.md"] = B.note("/a.md", "an agent wrote this", "x")   # lands after the preflight
                super().create(path, content)
        b = Racy(notes={"/a.md": "A"})
        ops = [{"op": "create", "path": "/c.md", "content": "C"}, {"op": "update", "path": "/a.md", "content": "A2"}]
        with self.assertRaises(B.StaleError) as cm:
            B.apply_ops(b, ops, {"/a.md": B.digest("A")}, dry_run=False)
        self.assertIn("1 of 2 steps applied", str(cm.exception))
        self.assertEqual(b.read("/a.md")["content"], "an agent wrote this")     # the agent's note is intact

    def test_the_directory_lock_is_reentrant(self):
        b = self.store("dir", {"/a.md": "A"})
        import threading
        out = []
        def run():
            with b.lock():                       # apply_ops holds it; each write takes it again
                b.update("/a.md", "A2", B.digest("A"))
                b.create("/c.md", "C")
            out.append(True)
        t = threading.Thread(target=run, daemon=True)
        t.start(); t.join(10)
        self.assertEqual(out, [True], "a nested lock blocked on itself")
        self.assertEqual(self.snap(b), {"/a.md": "A2", "/c.md": "C"})

    def test_the_lock_keeps_a_second_process_out(self):
        b = self.store("dir", {"/a.md": "A"})
        import time
        child = subprocess.Popen([sys.executable, "-I", "-c", (
            "import sys, time; sys.path.insert(0, %r); import membackend as B\n"
            "b = B.DirBackend(%r)\n"
            "with b.lock():\n    print('held', flush=True); time.sleep(1.0)\n") % (LIB, b.root)],
            stdout=subprocess.PIPE, text=True)
        self.assertEqual(child.stdout.readline().strip(), "held")
        t0 = time.time()
        with b.lock():
            waited = time.time() - t0
        child.wait()
        child.stdout.close()
        self.assertGreater(waited, 0.5, "the second process was not made to wait")

    def test_two_processes_updating_one_note_from_one_base_exactly_one_wins(self):
        b = self.store("dir", {"/a.md": "A"})
        code = ("import sys; sys.path.insert(0, %r); import membackend as B\n"
                "b = B.DirBackend(%r)\n"
                "try:\n    b.update('/a.md', sys.argv[1], B.digest('A')); print('won')\n"
                "except B.StaleError:\n    print('stale')\n") % (LIB, b.root)
        procs = [subprocess.Popen([sys.executable, "-I", "-c", code, w], stdout=subprocess.PIPE, text=True) for w in ("one", "two")]
        results = sorted(p.communicate()[0].strip() for p in procs)
        self.assertEqual(results, ["stale", "won"])
        self.assertIn(b.read("/a.md")["content"], ("one", "two"))

    def test_an_outside_edit_after_the_check_is_not_overwritten_or_lost(self):
        outside = "someone edited this in an editor"

        class Update(B.DirBackend):
            def _check(self, path, cur, expect):
                super()._check(path, cur, expect)
                with open(self._file(path), "w", encoding="utf-8") as h:     # an editor, after the check
                    h.write(outside)
        b = Update(os.path.join(self.tmp.name, "u"))
        b.create("/a.md", "A")
        with self.assertRaises(B.StaleError):
            b.update("/a.md", "A2", B.digest("A"))
        self.assertEqual(b.read("/a.md")["content"], outside)

        class Move(B.DirBackend):
            armed = False

            def _write(self, f, content, replace, was=None):
                super()._write(f, content, replace, was)
                if self.armed and not replace:
                    with open(self._file("/m.md"), "w", encoding="utf-8") as h:   # an editor, after the copy was made
                        h.write(outside)
        m = Move(os.path.join(self.tmp.name, "m"))
        m.create("/m.md", "M")
        m.armed = True
        with self.assertRaises(B.StaleError):
            m.move("/m.md", "/n.md", B.digest("M"))
        self.assertEqual(m.read("/m.md")["content"], outside)       # the edit survives; the copy at /n.md is harmless

    def test_archive_only_under_the_archive(self):
        b = self.store("fixture", {"/a.md": "A"})
        with self.assertRaises(B.StaleError):
            B.apply_ops(b, [{"op": "archive", "from": "/a.md", "to": "/elsewhere/a.md", "content": "A"}], {}, dry_run=False)
        with self.assertRaises(B.StaleError):
            B.apply_ops(b, [{"op": "bogus", "path": "/a.md"}], {}, dry_run=False)
        self.assertEqual(self.snap(b), {"/a.md": "A"})

    def test_steps_in_a_plan_see_the_earlier_ones(self):
        b = self.store("dir", {"/old.md": "O"})
        ops = [{"op": "move", "from": "/old.md", "to": "/new.md"}, {"op": "update", "path": "/new.md", "content": "N", "sha": B.digest("O")},
               {"op": "marker", "path": "/CANON.md", "content": "m"}]
        B.apply_ops(b, ops, {"/old.md": B.digest("O"), "/new.md": None, "/CANON.md": None}, dry_run=False)
        self.assertEqual(self.snap(b), {"/new.md": "N", "/CANON.md": "m"})


class Provenance(unittest.TestCase):
    def test_origin_round_trip(self):
        for seed in range(300):
            r = random.Random(seed)
            c = rand_content(r)
            seg = "copied from %s:%s@%s" % (P.quote("my store", safe=""), P.q("/a b;c.md"), B.digest(c)[:12])
            once = P.add_origin(c, seg)
            self.assertIn("; copied from", once)
            self.assertEqual(P.core(once), c, repr(c))
            twice = P.add_origin(once, "archived from %s@%s on %s" % (P.q("/a b;c.md"), B.digest(once)[:12], TODAY))
            self.assertEqual(P.core(P.core(twice)), c)
            self.assertEqual(P.origin(twice), ("archived", "/a b;c.md"))
            self.assertEqual(P.origin(once), ("copied", "/a b;c.md"))

    def test_a_note_without_sources_gets_one_and_a_fence_is_not_a_header(self):
        out = P.add_origin("# T\n\nKind: rule\n\n```\nSources: not a header\n```\n", "copied from s:/a.md@0123456789ab")
        self.assertEqual(out.splitlines()[1], "Sources: %s; copied from s:/a.md@0123456789ab" % P.NO_SOURCE)
        self.assertEqual(C.note_fields(out)["Sources"], "%s; copied from s:/a.md@0123456789ab" % P.NO_SOURCE)
        self.assertIn("origin not recorded", C.note_fields(out)["Sources"])      # canon check still asks for a real source


    def test_a_hand_written_look_alike_is_just_text(self):
        n = "# N\n\nKind: rule\nSources: me\n"
        fake = n.replace("Sources: me", "Sources: me; copied from x:/n.md@000000000000")
        self.assertEqual((P.core(fake), P.full(fake), P.origin(fake)), (fake, fake, (None, None)))
        right_shape_wrong_text = n.replace("Sources: me", "Sources: me; archived from /n.md@%s on %s" % (B.digest("something else")[:12], TODAY))
        self.assertEqual(P.origin(right_shape_wrong_text), (None, None))
        self.assertFalse(P.same(n, fake))
        # merging a note that differs from the stored one only by a look-alike must not drop it silently
        a = {"/n.md": B.note("/n.md", n, "1")}
        plan = P.merge(a, {"/n.md": B.note("/n.md", fake, "2")}, "conflicts", TODAY, "x")
        self.assertEqual([o["path"] for o in plan["target"]["ops"]], ["/_conflicts/%s/n.md" % TODAY])
        # one we made is ours, and the same note
        ours = P.copied("x", "/n.md", n)
        self.assertEqual((P.core(ours), P.origin(ours)), (n, ("copied", "/n.md")))
        self.assertEqual(P.merge(a, {"/n.md": B.note("/n.md", ours, "2")}, "conflicts", TODAY, "x")["target"]["ops"], [])
        # a segment cannot be moved onto other text: edit the note and it stops being ours
        self.assertEqual(P.core(ours.replace("Kind: rule", "Kind: gate")), ours.replace("Kind: rule", "Kind: gate"))

    def test_hops_do_not_make_notes_differ_or_grow(self):
        n = "# N\n\nKind: rule\nSources: me\n"
        hop = P.copied("A", "/n.md", P.copied("B", "/n.md", n))
        self.assertEqual(P.full(hop), n)
        self.assertTrue(P.same(hop, n))
        self.assertEqual(P.merge({"/n.md": B.note("/n.md", n, "1")}, {"/n.md": B.note("/n.md", hop, "2")}, "conflicts", TODAY, "x")["target"]["ops"], [])
        once = P.copied("A", "/n.md", n)
        again = P.copied("A", "/n.md", once)                       # the same note to the same place: replaced, not stacked
        self.assertEqual(again.count("; copied from"), 1)
        self.assertEqual(P.copied("B", "/n.md", once).count("; copied from"), 2)   # another label is another hop
        self.assertEqual(P.full(again), n)

    def test_only_the_header_block_is_the_notes_own_sources(self):
        body = "# T\n\nKind: rule\n\nSources: lives in the body\n"
        out = P.add_origin(body, "copied from s:/a.md@0123456789ab")
        self.assertIn("Sources: lives in the body\n", out)         # untouched
        self.assertEqual(out.splitlines()[1].split(";")[0], "Sources: " + P.NO_SOURCE)
        self.assertEqual(P.core(P.add_origin(body, "copied from s:/a.md@%s" % B.digest(body)[:12])), body)

    def test_the_line_ending_comes_from_the_line_that_is_edited(self):
        lf = "# T\n\nbody\r\nmore\r\n"                             # CRLF only in the body
        out = P.add_origin(lf, "copied from s:/a@0123456789ab")
        self.assertNotIn("\r\n", out.split("\n\n")[0])
        self.assertEqual(out.split("\n")[1][-1], "b")
        late = "preface\r\n# T\n\nbody\n"                          # the first line is not the one the new line sits beside
        self.assertNotIn("\r", P.add_origin(late, "copied from s:/a@0123456789ab").split("\n")[2])
        crlf = "# T\r\n\r\nbody\r\n"
        self.assertTrue(P.add_origin(crlf, "copied from s:/a@0123456789ab").split("\n")[1].endswith("\r"))
        mixed = "# T\n\nSources: me\r\nKind: x\n"
        seg = "copied from s:/a@%s" % B.digest(mixed)[:12]
        self.assertIn("; " + seg + "\r\n", P.add_origin(mixed, seg))
        self.assertEqual(P.core(P.add_origin(mixed, seg)), mixed)

    def test_a_sources_line_that_is_the_placeholder_text_is_the_authors_and_comes_back(self):
        base = "# N\n\nKind: rule\nSources: %s\nApplies to: any\n\nbody\n" % P.NO_SOURCE
        none = "# N\n\nKind: rule\nApplies to: any\n\nbody\n"
        for name, n in (("lf", base), ("crlf", base.replace("\n", "\r\n")), ("no final newline", base.rstrip("\n")),
                        ("crlf, no final newline", base.replace("\n", "\r\n").rstrip("\r\n")), ("alone", "# N\nSources: %s\n" % P.NO_SOURCE),
                        ("untitled", "Sources: %s\n" % P.NO_SOURCE)):
            with self.subTest(name):
                self.assertTrue(own_placeholder(n))
                cp = P.copied("A", "/n.md", n)
                self.assertEqual(cp.count("Sources:"), 1)                                         # still one line
                self.assertEqual((P.core(cp), P.full(cp), P.origin(cp)), (n, n, ("copied", "/n.md")))
                ar = P.add_origin(n, "archived from %s@%s on %s" % (P.q("/n.md"), B.digest(n)[:12], TODAY))
                self.assertEqual((P.core(ar), P.full(ar), P.origin(ar)), (n, n, ("archived", "/n.md")))
                hop = P.add_origin(cp, "archived from %s@%s on %s" % (P.q("/n.md"), B.digest(cp)[:12], TODAY))
                self.assertEqual((P.core(P.core(hop)), P.full(hop)), (n, n))
                self.assertTrue(P.same(n, cp))
        # the other half: a note with no Sources: line gets one, and loses exactly that line again
        for n in (none, none.replace("\n", "\r\n"), none.rstrip("\n"), "# N\n", "# N", "no title\n"):
            cp = P.copied("A", "/n.md", n)
            self.assertIn(P.NO_SOURCE, cp)
            self.assertEqual((P.core(cp), P.full(cp)), (n, n), repr(n))
            hop = P.add_origin(cp, "archived from %s@%s on %s" % (P.q("/n.md"), B.digest(cp)[:12], TODAY))
            self.assertEqual((P.core(P.core(hop)), P.full(hop)), (n, n), repr(n))
        # a note that has the placeholder and one without it are different notes, and neither turns into the other
        self.assertFalse(P.same(base, none))
        self.assertNotEqual(P.copied("A", "/n.md", base), P.copied("A", "/n.md", none))

    def test_trailers_written_by_the_released_code_restore_as_they_did(self):
        # literal text as 0.1.x-era qargi wrote it: no flag, the digest of the note as it was
        orig = "# N\n\nKind: rule\n"
        old = "# N\nSources: origin not recorded (qargi memory); copied from src:/n.md@%s\n\nKind: rule\n" % B.digest(orig)[:12]
        self.assertEqual((P.core(old), P.origin(old)), (orig, ("copied", "/n.md")))
        arch = "# N\r\nSources: origin not recorded (qargi memory); archived from /n.md@%s on 2026-10-29\r\n\r\nKind: rule\r\n" % B.digest(orig.replace("\n", "\r\n"))[:12]
        self.assertEqual((P.core(arch), P.origin(arch)), (orig.replace("\n", "\r\n"), ("archived", "/n.md")))
        own = "# N\n\nSources: maintainer\n"
        oldown = "# N\n\nSources: maintainer; copied from src:/n.md@%s\n" % B.digest(own)[:12]
        self.assertEqual(P.core(oldown), own)

    def test_a_placeholder_with_a_look_alike_segment_stays_text(self):
        n = "# N\n\nSources: %s\n" % P.NO_SOURCE
        for digest in ("000000000000", B.digest("something else")[:12]):
            fake = "# N\n\nSources: %s; copied from A:/n.md@%s\n" % (P.NO_SOURCE, digest)
            self.assertEqual((P.core(fake), P.full(fake), P.origin(fake)), (fake, fake, (None, None)), digest)
            self.assertFalse(P.same(n, fake))
        ours = P.copied("A", "/n.md", "# N\n\n")
        self.assertEqual(ours, "# N\nSources: %s; copied from A:/n.md@%s\n\n" % (P.NO_SOURCE, B.digest("# N\n\n")[:12]))
        self.assertEqual(P.core(ours), "# N\n\n")
        edited = ours.replace("# N", "# M")                                                      # edited afterwards: not ours any more
        self.assertEqual(P.core(edited), edited)


class Planning(Stores):
    def test_selector(self):
        s = {p: {"content": c} for p, c in {"/CANON.md": "x", "/_archive/d/a.md": "Kind: rule", "/roles/build/a.md": "# A\nKind: setup\n",
                                            "/roles/write/b.md": "# B\nKind: rule\n", "/shared/c.md": "# C\nKind: setup\n", "/sharedx/d.md": "Kind: setup"}.items()}
        self.assertEqual(P.select(s, {"role": "build"}), ["/roles/build/a.md"])
        self.assertEqual(P.select(s, {"kind": "setup"}), ["/roles/build/a.md", "/shared/c.md", "/sharedx/d.md"])
        self.assertEqual(P.select(s, {"prefix": ["/shared"]}), ["/shared/c.md"])  # a prefix ends at a folder boundary
        self.assertEqual(P.select(s, {"prefix": ["/roles/"], "kind": "rule"}), ["/roles/write/b.md"])
        self.assertEqual(P.select(s, {"prefix": ["/"]}), ["/roles/build/a.md", "/roles/write/b.md", "/shared/c.md", "/sharedx/d.md"])
        self.assertEqual(P.select(s, {"prefix": ["/_archive"]}), ["/_archive/d/a.md"])    # the archive only when a prefix names it
        with self.assertRaises(ValueError):
            P.split(s, {}, {})

    def test_split_copies_records_origin_and_archives(self):
        src = self.store("dir", {"/roles/build/a.md": "# A\n\nKind: setup\nSources: me\n", "/shared/b.md": "# B\n", "/CANON.md": "m"})
        dst = self.store("dir")
        plan = P.split(src.list(), {"role": "build"}, dst.list(), True, TODAY, "memory")
        self.run_plan(plan, src, dst)
        self.assertEqual(sorted(self.snap(src)), ["/CANON.md", "/_archive/%s/roles/build/a.md" % TODAY, "/shared/b.md"])
        self.assertEqual(self.snap(dst), {"/roles/build/a.md": "# A\n\nKind: setup\nSources: me; copied from memory:/roles/build/a.md@%s\n" % B.digest("# A\n\nKind: setup\nSources: me\n")[:12]})
        arch = self.snap(src)["/_archive/%s/roles/build/a.md" % TODAY]
        self.assertIn("; archived from /roles/build/a.md@", arch)
        self.assertEqual(P.core(arch), "# A\n\nKind: setup\nSources: me\n")        # and the archive can be taken back byte for byte

    def test_a_collision_goes_to_conflicts_like_the_reconciler(self):
        a = self.store("fixture", {"/shared/x.md": "# mine\n"})
        b = self.store("fixture", {"/shared/x.md": "# theirs\n", "/shared/y.md": "# y\n"})
        plan = P.merge(a.list(), b.list(), "conflicts", TODAY, "other")
        paths = sorted(o["path"] for o in plan["target"]["ops"])
        self.assertEqual(paths, ["/_conflicts/%s/shared/x.md" % TODAY, "/shared/y.md"])
        self.assertIn("conflict:", plan["notes"][0])
        keep = P.merge(a.list(), b.list(), "keep", TODAY, "other")
        self.assertEqual([o["path"] for o in keep["target"]["ops"]], ["/shared/y.md"])
        P.apply_plan(plan, {"target": a}, dry_run=False)
        again = P.merge(a.list(), b.list(), "conflicts", TODAY, "other")
        self.assertEqual(again["target"]["ops"], [])
        b.update("/shared/x.md", "# theirs, edited\n")                           # a second, different loser does not overwrite the first
        third = P.merge(a.list(), b.list(), "conflicts", TODAY, "other")
        self.assertEqual([o["path"] for o in third["target"]["ops"]], ["/_conflicts/%s/shared/x.md.2" % TODAY])
        with self.assertRaises(ValueError):
            P.merge({}, {}, "overwrite")

    def test_canon_marker_is_never_copied_and_the_source_is_read_only(self):
        a, b = self.store("fixture", {"/CANON.md": "A"}), self.store("fixture", {"/CANON.md": "B", "/shared/z.md": "z"})
        plan = P.merge(a.list(), b.list(), "conflicts", TODAY)
        self.assertEqual([o["path"] for o in plan["target"]["ops"]], ["/shared/z.md"])
        self.assertTrue(any("CANON.md" in n for n in plan["notes"]))

    def test_a_decision_to_leave_a_note_alone_is_checked_too(self):
        a = self.store("fixture", {"/shared/x.md": "# same\n", "/shared/z.md": "# z\n"})
        b = self.store("fixture", {"/shared/x.md": "# same\n", "/shared/y.md": "# y\n"})
        plan = P.merge(a.list(), b.list(), "conflicts", TODAY, "b")
        self.assertEqual(plan["target"]["expect"], {"/shared/x.md": B.digest("# same\n"), "/shared/y.md": None})
        a.update("/shared/x.md", "# someone changed the note the plan found identical\n")
        with self.assertRaises(B.StaleError):
            P.apply_plan(plan, {"target": a}, dry_run=False)
        self.assertNotIn("/shared/y.md", a.list())

    def test_merge_and_copy_do_not_carry_the_archive_along(self):
        for kind in self.kinds:
            a, c = self.store(kind, {"/roles/build/a.md": "# A\n", "/shared/b.md": "# B\n"}), self.store(kind)
            bb = self.store(kind)
            self.run_plan(P.split(a.list(), {"role": "build"}, bb.list(), True, TODAY, "a"), a, bb)
            self.assertTrue([p for p in a.list() if p.startswith("/_archive/")])
            plan = P.merge(c.list(), a.list(), "conflicts", TODAY, "a")
            self.assertEqual([o["path"] for o in plan["target"]["ops"]], ["/shared/b.md"])
            self.assertTrue(any("/_archive/" in n for n in plan["notes"]))
            P.apply_plan(plan, {"target": c}, dry_run=False)
            self.assertEqual([p for p in c.list() if p.startswith("/_archive/")], [])
            plan = P.copy(a.list(), c.list(), None, "conflicts", TODAY, "a")
            self.assertEqual(plan["target"]["ops"], [])
            named = P.copy(a.list(), c.list(), {"prefix": ["/_archive"]}, "conflicts", TODAY, "a")    # unless it is picked on purpose
            self.assertEqual([o["path"] for o in named["target"]["ops"]], ["/_archive/%s/roles/build/a.md" % TODAY])

    def test_an_archive_name_that_is_taken_gets_a_suffix_and_still_restores(self):
        for kind in self.kinds:
            files = {"/shared/a.md": "# A\n", "/_archive/%s/shared/a.md" % TODAY: "# an older archived note\n"}
            src, dst = self.store(kind, files), self.store(kind)
            plan = P.split(src.list(), {"prefix": ["/shared"]}, dst.list(), True, TODAY, "s")
            self.assertEqual([o["to"] for o in plan["source"]["ops"]], ["/_archive/%s/shared/a.md.2" % TODAY])
            self.run_plan(plan, src, dst)
            P.apply_plan(P.merge(src.list(), dst.list(), "conflicts", TODAY, "d"), {"target": src}, dry_run=False)
            self.assertEqual(self.snap(src), files)

    def test_upper_case_and_unicode_names_round_trip(self):
        files = {"/Shared/\u00c9t\u00e9 notes.md": "# \u00e9\n", "/shared/B.md": "# B\n", "/shared/b.md": "# b\n"}
        for kind in self.kinds:
            src, dst = self.store(kind, files), self.store(kind)
            self.run_plan(P.split(src.list(), {"prefix": ["/Shared", "/shared"]}, dst.list(), True, TODAY, "s s"), src, dst)
            self.assertEqual(sorted(self.snap(dst)), sorted(files))
            self.assertEqual(P.origin(self.snap(dst)["/Shared/\u00c9t\u00e9 notes.md"]), ("copied", "/Shared/\u00c9t\u00e9 notes.md"))
            P.apply_plan(P.merge(src.list(), dst.list(), "conflicts", TODAY, "d"), {"target": src}, dry_run=False)
            self.assertEqual(self.snap(src), files)

    def test_a_note_the_target_cannot_hold_is_refused_at_plan_time_naming_it(self):
        deep = "/" + "/".join("d%d" % i for i in range(20)) + "/n.md"
        cloudish = {p: B.note(p, "# x\n", str(i)) for i, p in enumerate(["/shared/.draft.md", "/shared/ok.md", deep, "/shared/trailing.md "])}
        dst = self.store("dir")
        with self.assertRaises(P.PlanRefused) as cm:
            P.copy(cloudish, dst.list(), None, "conflicts", TODAY, "cloud", dst.refusal)
        for named in ("/shared/.draft.md", "/shared/trailing.md "):
            self.assertIn(named, str(cm.exception))
        self.assertEqual(self.snap(dst), {})
        ok = P.copy(cloudish, dst.list(), {"prefix": ["/shared/ok.md"]}, "conflicts", TODAY, "cloud", dst.refusal)     # a narrower selector leaves them out
        self.assertEqual([o["path"] for o in ok["target"]["ops"]], ["/shared/ok.md"])
        # the cloud's own limits, applied to a directory source
        only_deep = {deep: B.note(deep, "# x\n", "1"), "/big.md": B.note("/big.md", "x" * 102401, "2")}
        with self.assertRaises(P.PlanRefused) as cm:
            P.merge({}, only_deep, "conflicts", TODAY, "s", None, B.cloud_problem)
        self.assertIn(deep, str(cm.exception))
        self.assertIn("/big.md", str(cm.exception))
        # an archive path is longer than the note: the source must be able to hold it
        nineteen = "/" + "/".join("d%d" % i for i in range(19)) + "/n.md"
        with self.assertRaises(P.PlanRefused) as cm:
            P.split({nineteen: B.note(nineteen, "# x\n", "1")}, {"prefix": ["/d0"]}, {}, True, TODAY, "c", None, B.cloud_problem)
        self.assertIn("/_archive/", str(cm.exception))
        self.assertTrue(P.split({nineteen: B.note(nineteen, "# x\n", "1")}, {"prefix": ["/d0"]}, {}, False, TODAY, "c", None, B.cloud_problem))

    def test_canon_check_accepts_the_archive(self):
        files = {"/README.md": "# r\n", "/_template.md": "t"}
        plan = C.make_plan("reference", {p: B.note(p, c, "i%d" % n) for n, (p, c) in enumerate(files.items())}, "demo", ["build"], "build", SEED, TODAY)
        mems = {p: v["content"] for p, v in C.simulate({p: B.note(p, c, p) for p, c in files.items()}, plan["ops"]).items()}
        guide = "# G\n\nKind: guide\nApplies to: any\nSources: me\n"
        mems["/_archive/%s/roles/build/guide.md" % TODAY] = P.add_origin(guide, "archived from /roles/build/guide.md@%s on %s" % (B.digest(guide)[:12], TODAY))
        mems["/_archive/%s/roles/build/other.md" % TODAY] = guide              # no segment of ours: where did it come from?
        f = os.path.join(self.tmp.name, "c.jsonl")
        B.FixtureBackend(f, mems)
        r = subprocess.run([sys.executable, os.path.join(LIB, "canon.py"), "check", "--kind", "reference", "--project", "demo", "--roles", "build", "--store", f],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout)                            # tolerated: a warning, never a failure
        self.assertIn("WARN /_archive/%s/roles/build/other.md" % TODAY, r.stdout)
        self.assertNotIn("WARN /_archive/%s/roles/build/guide.md" % TODAY, r.stdout)
        self.assertNotIn("FAIL", r.stdout)

    def test_migrate_reuses_the_canon_plan(self):
        files = {"/README.md": "# old\n\n| Path | Purpose | Load when |\n|---|---|---|\n| sandbox/a.md | a | always |\n",
                 "/_template.md": "t", "/sandbox/a.md": "# a\nKind: sandbox\nApplies to: any\nSources: t\nCheck: true\nVerified: 2026-10-01 by t\n"}
        for kind in self.kinds:
            b = self.store(kind, files)
            mems = b.list()
            plan = P.migrate(mems, C.LATEST, "memory", "demo", ["build", "write"], "build", SEED, TODAY)
            direct = C.make_plan("memory", mems, "demo", ["build", "write"], "build", SEED, TODAY)
            self.assertEqual([o["op"] for o in plan["target"]["ops"]], [o["op"] for o in direct["ops"]])
            B.apply_ops(b, plan["target"]["ops"], plan["target"]["expect"], dry_run=False)
            want = {p: v["content"] for p, v in C.simulate(mems, direct["ops"]).items()}
            self.assertEqual(self.snap(b), want)
            self.assertIn("/shared/sandbox/a.md", want)
            again = P.migrate(b.list(), C.LATEST, "memory", "demo", ["build", "write"], "build", SEED, TODAY)
            self.assertEqual(again["target"]["ops"], [])                         # idempotent
            self.assertTrue(set(files) - {"/README.md", "/sandbox/a.md"} <= set(want))
            with self.assertRaises(ValueError):
                P.migrate(mems, 1, "memory", "demo", ["build"], "build", SEED, TODAY)
            drift = b.list()
            b.update("/README.md", "edited meanwhile")
            with self.assertRaises(B.StaleError):                                # a migration planned on older notes is refused
                B.apply_ops(b, plan["target"]["ops"], plan["target"]["expect"], dry_run=False)
            del drift


class Invariants(Stores):
    def pair(self, kind, r, canon=False):
        a, b = rand_pair(r, canon)
        return self.store(kind, a), self.store(kind, b)

    def test_a_lossless(self):
        def check(kind, r):
            src, dst = self.pair(kind, r, canon=True)
            before = [self.snap(src), self.snap(dst)]
            plan = P.split(src.list(), rand_selector(r), dst.list(), r.random() < .7, TODAY, "src")
            self.run_plan(plan, src, dst)
            after = (self.snap(src), self.snap(dst))
            for s in before:
                self.assertEqual(self.missing(s, *after), [])
            ma, mb = rand_pair(r)
            a, b = self.store(kind, ma), self.store(kind, mb)
            P.apply_plan(P.merge(a.list(), b.list(), "conflicts", TODAY, "b"), {"target": a}, dry_run=False)
            theirs = {p: c for p, c in mb.items() if p != "/CANON.md" and not p.startswith("/_archive/")}   # reported, not copied
            self.assertEqual(self.missing(theirs, self.snap(a)), [])
            self.assertEqual(self.missing(ma, self.snap(a)), [])
            self.assertEqual(self.snap(b), mb)                                   # the other store is only read
        self.each(check)

    def test_a_losing_one_of_two_identical_notes_is_a_loss(self):
        before = {"/x/a.md": "# same\n", "/y/a.md": "# same\n"}
        self.assertEqual(self.missing(before, {"/x/a.md": "# same\n"}), ["/y/a.md"])
        self.assertEqual(self.missing(before, {"/x/a.md": "# same\n"}, {"/_archive/%s/y/a.md" % TODAY: "# same\n"}), [])

    def test_b_idempotent(self):
        def check(kind, r):
            src, dst = self.pair(kind, r, canon=True)
            sel, move = rand_selector(r), r.random() < .7
            self.run_plan(P.split(src.list(), sel, dst.list(), move, TODAY, "src"), src, dst)
            again = P.split(src.list(), sel, dst.list(), move, TODAY, "src")
            self.assertEqual((again["target"]["ops"], again["source"]["ops"]), ([], []))
            a, b = self.pair(kind, r, canon=True)
            P.apply_plan(P.merge(a.list(), b.list(), "conflicts", TODAY, "b"), {"target": a}, dry_run=False)
            self.assertEqual(P.merge(a.list(), b.list(), "conflicts", TODAY, "b")["target"]["ops"], [])
            c, d = self.pair(kind, r)
            self.run_plan(P.copy(c.list(), d.list(), sel, "conflicts", TODAY, "c"), c, d)
            self.assertEqual(P.copy(c.list(), d.list(), sel, "conflicts", TODAY, "c")["target"]["ops"], [])
        self.each(check)

    def test_c_split_then_merge_returns_the_original(self):
        restored = []

        def check(kind, r):
            files = rand_store(r, canon=r.random() < .5)
            src, dst = self.store(kind, files), self.store(kind)
            self.run_plan(P.split(src.list(), rand_selector(r), dst.list(), True, TODAY, "src"), src, dst)
            plan = P.merge(src.list(), dst.list(), "conflicts", TODAY, "dst")
            restored.append(sum(n.startswith("restored ") for n in plan["notes"]))
            P.apply_plan(plan, {"target": src}, dry_run=False)
            self.assertEqual(self.snap(src), files)
            # and with other notes already in the target: they come back with the rest, marked as copies
            other = {"/other/%s.md" % i: "# o%d\n" % i for i in range(r.randrange(0, 3))}
            src2, dst2 = self.store(kind, files), self.store(kind, other)
            self.run_plan(P.split(src2.list(), rand_selector(r), dst2.list(), True, TODAY, "src"), src2, dst2)
            P.apply_plan(P.merge(src2.list(), dst2.list(), "conflicts", TODAY, "dst"), {"target": src2}, dry_run=False)
            got = self.snap(src2)
            self.assertEqual({p: c for p, c in got.items() if p not in other}, files)
            self.assertEqual({p: P.core(c) for p, c in got.items() if p in other}, other)
        self.each(check)
        self.assertGreater(sum(restored), 20)

    def test_c2_a_sources_line_equal_to_the_placeholder_survives_split_and_merge(self):
        base = "# N\n\nKind: rule\nSources: %s\n\nbody\n" % P.NO_SOURCE
        bare = "# B\n\nKind: rule\n\nbody\n"
        variants = [base, base.replace("\n", "\r\n"), base.rstrip("\n"), bare, bare.replace("\n", "\r\n"), bare.rstrip("\n")]

        def check(kind, r):
            files = {"/shared/%s.md" % i: c for i, c in enumerate(variants)}
            files["/shared/plain.md"] = "# P\n\nSources: maintainer\n"
            src, dst = self.store(kind, files), self.store(kind)
            self.run_plan(P.split(src.list(), {"prefix": ["/shared/"]}, dst.list(), True, TODAY, "src"), src, dst)
            self.assertEqual(self.snap(src).keys() & files.keys(), set())                       # all archived
            plan = P.merge(src.list(), dst.list(), "conflicts", TODAY, "dst")
            self.assertEqual(sum(n.startswith("restored ") for n in plan["notes"]), len(files))
            P.apply_plan(plan, {"target": src}, dry_run=False)
            self.assertEqual(self.snap(src), files)                                              # byte for byte
            copy_to = self.store(kind)                                                           # a copy, and the segment taken off it again
            self.run_plan(P.copy(src.list(), copy_to.list(), {"prefix": ["/shared/"]}, "conflicts", TODAY, "src"), src, copy_to)
            self.assertEqual({p: P.core(c) for p, c in self.snap(copy_to).items()}, files)
        self.each(check)

    def test_c3_random_stores_with_the_placeholder_round_trip_and_are_covered(self):
        seen = {"own": 0, "own crlf": 0, "own no final newline": 0, "none": 0}

        def check(kind, r):
            files = rand_store(r, n=r.randrange(4, 14))
            for p, c in files.items():
                if own_placeholder(c):
                    seen["own"] += 1
                    seen["own crlf"] += "\r\n" in c
                    seen["own no final newline"] += not c.endswith("\n")
                else:
                    seen["none"] += P._sources_line(c.split("\n")) is None
            src, dst = self.store(kind, files), self.store(kind)
            self.run_plan(P.split(src.list(), {"prefix": ["/"]}, dst.list(), True, TODAY, "src"), src, dst)
            P.apply_plan(P.merge(src.list(), dst.list(), "conflicts", TODAY, "dst"), {"target": src}, dry_run=False)
            live = lambda m: {p: c for p, c in m.items() if not p.startswith("/_archive/")}
            self.assertEqual(live(self.snap(src)), live(files))
            for p, c in self.snap(dst).items():                                                  # and every copy lets go of its segment
                self.assertIn(P.full(c), files.values(), p)
        self.each(check)
        for k, v in seen.items():
            self.assertGreater(v, 2 if k == "own crlf" else 8, seen)         # the explicit variants are in the test above

    def test_d_a_concurrent_write_is_detected_and_nothing_changes(self):
        def check(kind, r):
            src, dst = self.pair(kind, r, canon=True)
            plan = P.split(src.list(), rand_selector(r), dst.list(), True, TODAY, "src")
            touched = [(k, p) for k in ("target", "source") for p in plan[k]["expect"]]
            if not touched:
                return
            k, p = r.choice(touched)
            victim = {"target": dst, "source": src}[k]
            if p in victim.list():
                victim.update(p, victim.read(p)["content"] + "\nan agent added this\n")
            else:
                victim.create(p, "an agent created this")
            before = (self.snap(src), self.snap(dst))
            with self.assertRaises(B.StaleError):
                self.run_plan(plan, src, dst)
            self.assertEqual((self.snap(src), self.snap(dst)), before)
        self.each(check)

    def test_e_dry_run_is_the_default(self):
        def check(kind, r):
            src, dst = self.pair(kind, r)
            plan = P.split(src.list(), rand_selector(r), dst.list(), True, TODAY, "src")
            before = (self.snap(src), self.snap(dst))
            done = P.apply_plan(plan, {"source": src, "target": dst})
            self.assertEqual((self.snap(src), self.snap(dst)), before)
            self.assertEqual(len(done), len(plan["target"]["ops"]) + len(plan["source"]["ops"]))
        self.each(check)

    def test_f_the_plan_token_changes_when_the_plan_changes(self):
        def token(plan):
            return hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()[:12]

        def check(kind, r):
            files = rand_store(r, n=r.randrange(3, 14))
            src, dst = self.store(kind, files), self.store(kind)
            sel = rand_selector(r)
            picked = P.select(src.list(), sel)
            if not picked:
                return
            base = P.split(src.list(), sel, dst.list(), True, TODAY, "src")
            self.assertEqual(token(base), token(P.split(src.list(), sel, dst.list(), True, TODAY, "src")))   # same plan, same token
            self.assertNotEqual(token(base), token(P.split(src.list(), sel, dst.list(), False, TODAY, "src")))   # archiving or not
            self.assertNotEqual(token(base), token(P.split(src.list(), sel, dst.list(), True, "2026-10-30", "src")))   # another day
            src.update(picked[0], src.read(picked[0])["content"] + "\nedited\n")
            self.assertNotEqual(token(base), token(P.split(src.list(), sel, dst.list(), True, TODAY, "src")))   # a note changed
        self.each(check)

    def test_h_the_random_stores_exercise_the_planner(self):
        seen = {"copy": 0, "archive": 0, "conflict": 0, "inserted": 0}
        for seed in SEEDS:
            r = random.Random(seed)
            a, b = rand_pair(r, canon=True)
            plan = P.split({p: B.note(p, c) for p, c in a.items()}, rand_selector(r), {p: B.note(p, c) for p, c in b.items()}, True, TODAY, "x")
            seen["copy"] += sum(o["op"] == "create" for o in plan["target"]["ops"])
            seen["archive"] += len(plan["source"]["ops"])
            seen["conflict"] += sum("/_conflicts/%s" % TODAY in o["path"] for o in plan["target"]["ops"])
            seen["inserted"] += sum(P.NO_SOURCE in o.get("content", "") for o in plan["target"]["ops"])
        for k in ("copy", "archive", "conflict", "inserted"):
            self.assertGreater(seen[k], 5, seen)

    def test_g_imported_notes_carry_their_origin(self):
        def check(kind, r):
            a, b = self.pair(kind, r)
            b_before = self.snap(b)
            P.apply_plan(P.merge(a.list(), b.list(), "conflicts", TODAY, "other"), {"target": a}, dry_run=False)
            for p, c in self.snap(a).items():
                if p in b_before and c != b_before[p] and P.core(c) == b_before[p]:
                    self.assertEqual(P.origin(c), ("copied", p))
        self.each(check)


FAKE_ANT = r'''#!/usr/bin/env python3
# A fake ant with state. It logs every call, and can be told (environment) to refuse a precondition, to create a
# second memory at one path, or to fail a call with a message: FAKE_REFUSE_PRECONDITION, FAKE_DUP_CREATE, FAKE_FAIL=<substring of the call>.
import hashlib, json, os, re, sys
fake = os.environ["FAKE"]
a = sys.argv[1:]
with open(os.path.join(fake, "ant.log"), "a") as f:
    f.write(" ".join(a) + "\n")
def opt(k):
    return a[a.index(k) + 1] if k in a else None
cmd, verb = (a + ["", ""])[:2]
if cmd == "auth":
    sys.exit(0)
if os.environ.get("FAKE_FAIL") and os.environ["FAKE_FAIL"] in " ".join(a):
    sys.stderr.write("boom: the store said no to " + verb + "\n"); sys.exit(1)
d = os.path.join(fake, "memories", opt("--memory-store-id") or "none")
os.makedirs(d, exist_ok=True)
vlog = os.path.join(fake, "versions.jsonl")
sha = lambda s: hashlib.sha256(s.encode()).hexdigest()
def version(m, op):
    with open(vlog, "a") as f:
        f.write(json.dumps({"memory_id": m["id"], "path": m["path"], "operation": op}) + "\n")
def put(m):
    json.dump(m, open(os.path.join(d, m["id"] + ".json"), "w"))
def fail(kind, msg, status, **fields):      # what ant prints: the request line with the status, then the JSON body
    sys.stderr.write('POST "https://api.example.invalid/v1/memory_stores/x/memories": %s\n' % status)
    sys.stderr.write(json.dumps({"type": "error", "error": dict({"type": kind, "message": msg}, **fields)}) + "\n")
    sys.exit(1)
def holder(path):
    for fn in sorted(os.listdir(d)):
        m = json.load(open(os.path.join(d, fn)))
        if m["path"] == path:
            return m
if cmd == "beta:memory-stores:memories":
    if verb == "list":
        pre, depth, view = opt("--path-prefix") or "/", opt("--depth"), opt("--view") or "full"
        for fn in sorted(os.listdir(d)):
            m = json.load(open(os.path.join(d, fn)))
            rest = m["path"][len(pre):]
            if not m["path"].startswith(pre) or (depth == "1" and "/" in rest):
                continue
            m.update(type="memory", content_sha256=sha(m["content"]))
            if view == "basic":
                del m["content"]
            print(json.dumps(m, indent=2))
    elif verb == "create":
        body = sys.stdin.read()
        text = open(body.split('"@', 1)[1].split('"', 1)[0]).read()
        if holder(opt("--path")) and not os.environ.get("FAKE_DUP_CREATE"):
            h = holder(opt("--path"))
            fail("memory_path_conflict_error", "path `%s` is already used by `%s`; use update to modify it" % (h["path"], h["id"]), "409 Conflict",
                 conflicting_path=h["path"], conflicting_memory_id=h["id"])
        for _ in range(2 if os.environ.get("FAKE_DUP_CREATE") else 1):   # belt and braces: a store that did let two memories share a path
            m = {"id": "mem_%d" % (len(os.listdir(d)) + 1), "path": opt("--path"), "content": text}
            put(m); version(m, "created")
        print("{}")
    elif verb == "update":
        f = os.path.join(d, opt("--memory-id") + ".json"); m = json.load(open(f))
        want = opt("--precondition.content-sha256")
        if os.environ.get("FAKE_REFUSE_PRECONDITION") or (want and want != sha(m["content"])):
            fail("memory_precondition_failed_error", "precondition content_sha256 failed: content has changed", "409 Conflict")
        if opt("--path") and opt("--path") != m["path"]:
            h = holder(opt("--path"))
            if h:
                fail("memory_path_conflict_error", "path `%s` is already used by `%s`; delete it first to rename-and-replace" % (h["path"], h["id"]),
                     "409 Conflict", conflicting_path=h["path"], conflicting_memory_id=h["id"])
            m["path"] = opt("--path")
        body = sys.stdin.read()
        if '"@' in body:
            m["content"] = open(body.split('"@', 1)[1].split('"', 1)[0]).read()
        put(m); version(m, "modified"); print("{}")
elif cmd == "beta:memory-stores:memory-versions":
    if os.path.exists(vlog):
        for l in open(vlog):
            v = json.loads(l)
            if opt("--memory-id") in (None, v["memory_id"]):
                print(json.dumps(v))
'''


class FakeAnt(Stores):
    def setUp(self):
        super().setUp()
        self.fake = os.path.join(self.tmp.name, "fake")
        os.makedirs(self.fake)
        self.ant = os.path.join(self.tmp.name, "ant")
        with open(self.ant, "w") as f:
            f.write(FAKE_ANT)
        os.chmod(self.ant, 0o755)
        self.env = dict(os.environ, FAKE=self.fake, PATH=self.tmp.name + os.pathsep + os.environ["PATH"])
        os.environ["FAKE"] = self.fake

    def tearDown(self):
        os.environ.pop("FAKE", None)
        super().tearDown()

    def log(self):
        try:
            with open(os.path.join(self.fake, "ant.log")) as f:
                return f.read()
        except FileNotFoundError:
            return ""


class Cloud(FakeAnt):
    def test_cloud_backend_through_a_fake_ant(self):
        c = B.CloudBackend("memstore_T", self.ant)
        c.create("/a.md", "A")
        c.create("/b.md", "B")
        with self.assertRaises(B.StaleError):
            c.create("/a.md", "again")
        self.assertEqual(self.snap(c), {"/a.md": "A", "/b.md": "B"})
        c.update("/a.md", "A2", B.digest("A"))
        with self.assertRaises(B.StaleError):
            c.update("/a.md", "A3", B.digest("A"))
        c.move("/b.md", "/c.md", B.digest("B"))
        c.archive("/c.md", "/_archive/d/c.md", "B!", B.digest("B"))
        self.assertEqual(self.snap(c), {"/a.md": "A2", "/_archive/d/c.md": "B!"})
        self.assertEqual([v["operation"] for v in c.versions("/a.md")], ["created", "modified"])
        self.assertIn("memory-versions list --memory-store-id memstore_T --memory-id mem_1", self.log())   # by id, not the whole store's history
        self.assertNotRegex(self.log(), r"\b(delete|remove|archive-delete)\b")
        # a plan between a store in the cloud and a directory, and the sha check against the cloud's own digest
        dst = self.store("dir")
        plan = P.split(c.list(), {"prefix": ["/a.md"]}, dst.list(), True, TODAY, "memstore_T")
        c.update("/a.md", "edited meanwhile")
        with self.assertRaises(B.StaleError):
            self.run_plan(plan, c, dst)
        self.assertEqual(self.snap(dst), {})
        self.run_plan(P.split(c.list(), {"prefix": ["/a.md"]}, dst.list(), True, TODAY, "memstore_T"), c, dst)
        self.assertEqual(sorted(self.snap(c)), ["/_archive/%s/a.md" % TODAY, "/_archive/d/c.md"])
        self.assertEqual(sorted(self.snap(dst)), ["/a.md"])


    def calls(self):
        return len(self.log().splitlines())

    def test_a_plan_costs_a_number_of_calls_linear_in_its_steps(self):
        counts = {}
        for n in (10, 20):
            c = B.CloudBackend("memstore_N%d" % n, self.ant)
            before = self.calls()
            ops = [{"op": "create", "path": "/n/%d.md" % i, "content": "# %d\n" % i} for i in range(n)]
            B.apply_ops(c, ops, {}, dry_run=False)
            counts[n] = self.calls() - before
            self.assertEqual(len(c.list()), n)
        self.assertLessEqual(counts[10], 2 * 10 + 3, counts)       # a listing, then a write and a check of one folder per step
        self.assertLessEqual(counts[20], 2 * 20 + 3, counts)
        c = B.CloudBackend("memstore_N10", self.ant)
        before = self.calls()
        with c.lock():
            c.list(); c.list(); c.list()
        self.assertEqual(self.calls() - before, 1, "one listing per lock")

    def test_a_refused_precondition_is_stale_and_says_what_the_store_said(self):
        c = B.CloudBackend("memstore_P", self.ant)
        c.create("/a.md", "A")
        os.environ["FAKE_REFUSE_PRECONDITION"] = "1"
        try:
            with self.assertRaises(B.StaleError) as cm:
                c.update("/a.md", "A2", B.digest("A"))
        finally:
            del os.environ["FAKE_REFUSE_PRECONDITION"]
        self.assertEqual(str(cm.exception), "/a.md changed since the plan was made")
        self.assertEqual(c.read("/a.md")["content"], "A")
        os.environ["FAKE_FAIL"] = "list"
        try:
            with self.assertRaises(B.StoreError) as cm:
                c.list()
        finally:
            del os.environ["FAKE_FAIL"]
        self.assertIn("boom: the store said no", str(cm.exception))
        self.assertNotIsInstance(cm.exception, B.StaleError)

    def test_the_servers_409s_are_mapped_and_nothing_is_deleted_to_make_room(self):
        c = B.CloudBackend("memstore_M", self.ant)
        c.create("/a.md", "A")
        c.create("/b.md", "B")
        other = B.CloudBackend("memstore_M", self.ant)
        # the path was taken after our listing: the server says 409 path conflict, which is a stale plan, not a failure
        with self.assertRaises(B.StaleError) as cm:
            c._send("create", "/a.md", "again")
        self.assertEqual(str(cm.exception), "/a.md already exists")
        cur = other.list()["/a.md"]
        with self.assertRaises(B.StaleError) as cm:
            c._send("update", "/a.md", None, cur, "/b.md")                  # a rename onto an occupied path
        self.assertEqual(str(cm.exception), "/b.md already exists")
        with self.assertRaises(B.StaleError) as cm:                       # a precondition built from an old digest
            c._send("update", "/a.md", "A2", dict(cur, content_sha256="0" * 64))
        self.assertEqual(str(cm.exception), "/a.md changed since the plan was made")
        self.assertEqual(self.snap(other), {"/a.md": "A", "/b.md": "B"})
        self.assertIn("--precondition.type content_sha256 --precondition.content-sha256", self.log())
        self.assertNotRegex(self.log(), r"\b(delete|remove)\b")
        # a rename without content: the id stays, the content is not touched
        c.move("/a.md", "/z.md", B.digest("A"))
        self.assertEqual(self.snap(other), {"/z.md": "A", "/b.md": "B"})
        self.assertEqual(other.list()["/z.md"]["id"], cur["id"])
        # any other failure keeps the tail of what ant said
        os.environ["FAKE_FAIL"] = "create"
        try:
            with self.assertRaises(B.StoreError) as cm:
                c.create("/new.md", "N")
        finally:
            del os.environ["FAKE_FAIL"]
        self.assertNotIsInstance(cm.exception, B.StaleError)
        self.assertIn("boom", str(cm.exception))

    def test_two_memories_at_one_path_after_a_create_are_reported_and_nothing_is_deleted(self):
        c = B.CloudBackend("memstore_D", self.ant)
        os.environ["FAKE_DUP_CREATE"] = "1"
        try:
            with self.assertRaises(B.StoreError) as cm:
                c.create("/dup.md", "D")
        finally:
            del os.environ["FAKE_DUP_CREATE"]
        self.assertRegex(str(cm.exception), r"mem_1.*mem_2")
        self.assertIn("nothing was deleted", str(cm.exception))
        self.assertNotRegex(self.log(), r"\b(delete|remove)\b")
        self.assertEqual(len([m for m in c.list().values() if m["path"] == "/dup.md"]), 1)    # list() keys by path; the duplicate is in the store


class Cli(FakeAnt):
    def qargi(self, *args, env=None):
        e = dict(self.env, QARGI_CONF=os.path.join(self.tmp.name, "conf"), QARGI_STATE=os.path.join(self.tmp.name, "state"), **(env or {}))
        return subprocess.run([BIN, "memory"] + list(args), capture_output=True, text=True, env=e, cwd=self.tmp.name, stdin=subprocess.DEVNULL)

    def tree(self, root):
        out = {}
        for d, _, fs in os.walk(root):
            for fn in fs:
                with open(os.path.join(d, fn)) as f:
                    out[os.path.relpath(os.path.join(d, fn), root)] = f.read()
        return out

    def token(self, r):
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.split("plan token: ")[1].split()[0]

    def test_split_plan_approve_and_audit(self):
        src, dst = os.path.join(self.tmp.name, "src"), os.path.join(self.tmp.name, "dst")
        b = B.DirBackend(src)
        b.create("/roles/build/a.md", "# A\n\nKind: setup\n")
        b.create("/shared/b.md", "# B\n")
        before = self.tree(src)
        r = self.qargi("split", src, dst, "--role", "build", "--archive")
        tok = self.token(r)
        self.assertIn("nothing was changed", r.stdout)
        self.assertEqual((self.tree(src), os.path.exists(dst)), (before, False))   # a dry run is the default
        r = self.qargi("split", src, dst, "--role", "build", "--archive", "--approved", "go on")
        self.assertNotEqual(r.returncode, 0)                                      # no token, no change
        r = self.qargi("split", src, dst, "--role", "build", "--archive", "--plan", "0" * 12, "--approved", "go on")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.tree(src), os.path.exists(dst)), (before, False))
        self.assertNotEqual(self.token(self.qargi("split", src, dst, "--role", "write", "--prefix", "/shared")), tok)   # another plan, another token
        self.assertNotEqual(self.token(self.qargi("split", src, dst, "--role", "build")), tok)   # not archiving is another plan
        b.update("/shared/b.md", "# B edited\n")                                  # an unrelated note changes: the plan holds
        self.assertEqual(self.token(self.qargi("split", src, dst, "--role", "build", "--archive")), tok)
        b.update("/roles/build/a.md", "# A edited\n")                             # a note the plan read changes: the token moves
        self.assertNotEqual(self.token(self.qargi("split", src, dst, "--role", "build", "--archive")), tok)
        tok = self.token(self.qargi("split", src, dst, "--role", "build", "--archive"))
        r = self.qargi("split", src, dst, "--role", "build", "--archive", "--plan", tok, "--approved", "split the build notes out")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(sorted(self.tree(dst)), ["roles/build/a.md"])
        self.assertTrue(any(k.startswith("_archive") for k in self.tree(src)))
        self.assertNotIn("roles/build/a.md", self.tree(src))
        with open(os.path.join(self.tmp.name, "state", "audit.log")) as f:
            audit = [json.loads(l) for l in f]
        self.assertEqual([(a["verb"], a["approved"]) for a in audit], [("memory-split", "split the build notes out"), ("memory-split-applied", "split the build notes out")])
        detail = json.loads(audit[0]["detail"])                                   # what was approved, not just where
        self.assertEqual((detail["token"], detail["role"], detail["archive"], detail["policy"], detail["prefix"]), (tok, "build", True, "conflicts", []))
        self.assertEqual([(x["store"], x["op"], x["path"]) for x in detail["steps"]],
                         [("target", "create", "/roles/build/a.md"), ("source", "archive", "/roles/build/a.md")])
        self.assertEqual(audit[1]["detail"], tok)
        r = self.qargi("split", src, dst, "--role", "build", "--archive")           # planning again after the apply: nothing left
        self.assertIn("nothing to do", r.stdout)

    def test_copy_merge_and_refusals(self):
        a, b = os.path.join(self.tmp.name, "a"), os.path.join(self.tmp.name, "b")
        B.DirBackend(a).create("/shared/x.md", "# mine\n")
        B.DirBackend(b).create("/shared/x.md", "# theirs\n")
        B.DirBackend(b).create("/shared/y.md", "# y\n")
        tok = self.token(self.qargi("merge", b, a))
        r = self.qargi("merge", b, a, "--plan", tok, "--approved", "merge them")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = self.tree(a)
        self.assertEqual(got["shared/x.md"], "# mine\n")
        self.assertEqual(len([k for k in got if k.startswith("_conflicts")]), 1)
        self.assertEqual(self.tree(b), {"shared/x.md": "# theirs\n", "shared/y.md": "# y\n"})
        self.assertNotEqual(self.qargi("split", a, b).returncode, 0)               # a selector is required
        self.assertNotEqual(self.qargi("copy", a, a).returncode, 0)                # not onto itself
        self.assertNotEqual(self.qargi("merge", b, a, "--role", "build").returncode, 0)
        self.assertNotEqual(self.qargi("split", a, b, "--role", "build", "--policy", "keep").returncode, 0)
        c = os.path.join(self.tmp.name, "c")
        r = self.qargi("copy", b, c, "--prefix", "/shared/y.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(c))
        self.qargi("copy", b, c, "--prefix", "/shared/y.md", "--plan", self.token(r), "--approved", "copy y")
        self.assertEqual(sorted(self.tree(c)), ["shared/y.md"])

    def test_a_dump_and_a_cloud_store_are_sources_a_dump_is_never_a_target(self):
        dump = os.path.join(self.tmp.name, "dump.jsonl")
        B.FixtureBackend(dump, {"/shared/a.md": "# A\n"})
        c = B.CloudBackend("memstore_X", self.ant)
        c.create("/shared/c.md", "# C\n")
        into = os.path.join(self.tmp.name, "into")
        for src in (dump, "memstore_X"):
            r = self.qargi("merge", src, into)
            self.qargi("merge", src, into, "--plan", self.token(r), "--approved", "pull it in")
        self.assertEqual(sorted(self.tree(into)), ["shared/a.md", "shared/c.md"])
        self.assertNotRegex(self.log(), r"\b(delete|remove)\b")
        self.assertEqual(self.snap(c), {"/shared/c.md": "# C\n"})                   # the cloud store was only read
        before = (self.tree(into), self.tree(os.path.dirname(dump))["dump.jsonl"])
        for verb, extra in (("merge", []), ("copy", ["--prefix", "/shared"]), ("split", ["--prefix", "/shared"])):
            for args in ((into, dump), ("memstore_X", dump)):
                r = self.qargi(verb, *args, *extra)
                self.assertNotEqual(r.returncode, 0, verb)
                self.assertIn("read-only", r.stderr)
                self.assertNotIn("plan token", r.stdout)
        r = self.qargi("split", dump, into, "--prefix", "/shared", "--archive")      # archiving writes to the source: also refused
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.tree(into), self.tree(os.path.dirname(dump))["dump.jsonl"]), before)

    def test_a_note_that_cannot_be_stored_is_refused_before_anything_is_applied(self):
        dump = os.path.join(self.tmp.name, "cloud.jsonl")
        with open(dump, "w") as f:
            for i, p in enumerate(["/shared/.draft.md", "/shared/ok.md"]):
                f.write(json.dumps({"type": "memory", "id": "m%d" % i, "path": p, "content": "# x\n"}) + "\n")
        into = os.path.join(self.tmp.name, "into")
        r = self.qargi("copy", dump, into)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("/shared/.draft.md", r.stderr)
        self.assertFalse(os.path.exists(into))
        r = self.qargi("copy", dump, into, "--prefix", "/shared/ok.md")
        self.assertEqual(r.returncode, 0, r.stderr)

    def gate_case(self, verb, extra):
        a, b = os.path.join(self.tmp.name, "ga"), os.path.join(self.tmp.name, "gb")
        B.DirBackend(a).create("/shared/x.md", "# mine\n\nKind: rule\n")
        B.DirBackend(a).create("/shared/y.md", "# y\n\nKind: rule\n")
        B.DirBackend(b).create("/shared/z.md", "# z\n")
        args = [verb, a, b] + extra
        before = (self.tree(a), self.tree(b))
        tok = self.token(self.qargi(*args))
        for bad in (["--approved", "go"], ["--plan", "", "--approved", "go"], ["--plan", "0" * 12, "--approved", "go"], ["--plan", tok[:-1] + ("0" if tok[-1] != "0" else "1"), "--approved", "go"]):
            self.assertNotEqual(self.qargi(*args, *bad).returncode, 0, bad)
            self.assertEqual((self.tree(a), self.tree(b)), before, bad)
        r = self.qargi(*args, "--approved", "go", env={"QARGI_NESTED": "1"})       # a nested call is not an approval of this plan
        self.assertNotEqual(r.returncode, 0)
        r = self.qargi(*args, "--plan", "0" * 12, "--approved", "go", env={"QARGI_NESTED": "1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.tree(a), self.tree(b)), before)
        r = self.qargi(*args, "--plan", tok, "--approved", "go", env={"QARGI_NESTED": "1"})
        self.assertEqual(r.returncode, 0, r.stderr)                                  # with the right token it applies, and it is not logged as nested
        self.assertNotEqual((self.tree(a), self.tree(b)), before)
        with open(os.path.join(self.tmp.name, "state", "audit.log")) as f:
            audit = [json.loads(l) for l in f]
        self.assertEqual([x["verb"] for x in audit], ["memory-%s" % verb, "memory-%s-applied" % verb])
        self.assertFalse(any(x["nested"] for x in audit))
        d = json.loads(audit[0]["detail"])
        self.assertEqual((d["token"], d["from"], d["to"]), (tok, a, b))
        return d

    def test_the_gate_holds_for_merge(self):
        d = self.gate_case("merge", [])
        self.assertEqual([(x["store"], x["op"]) for x in d["steps"]], [("target", "create"), ("target", "create")])

    def test_the_gate_holds_for_copy_and_records_the_selector(self):
        d = self.gate_case("copy", ["--prefix", "/shared/x.md", "--prefix", "/shared/y.md", "--note-kind", "rule", "--policy", "keep"])
        self.assertEqual((d["prefix"], d["note_kind"], d["policy"], d["archive"]), (["/shared/x.md", "/shared/y.md"], "rule", "keep", False))


if __name__ == "__main__":
    unittest.main()
