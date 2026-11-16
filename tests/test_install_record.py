#!/usr/bin/env python3
"""lib/install_record.py, the install records of install.sh: every manifest line is checked on read (a known kind, an absolute normalized
path, a place its kind of manifest allows) and a manifest with one bad line is refused whole; a manifest is written whole and private; the
complete manifest is on disk before an install changes anything, so an interrupted install leaves a record that lists more than is there and
the next run converges; a link is removed only while it points at its recorded target and one already pointing at its target is left as it
is; nothing is replaced that no record lists, without --force; one skills directory holds one runtime; an uninstall leaves no record, lock
or empty configuration directory it made. Offline, temporary directories only. Run: python3 tests/test_install_record.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import io, json, os, stat, subprocess, sys, tempfile, unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lib"))
import install_record as R  # noqa: E402

SKILLS = ("qargi-task", "qargi-flow")


def spit(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def slurp(path):
    with open(path) as f:
        return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home = os.path.join(self.t, "home")
        self.conf = os.path.join(self.t, "conf")
        self.rdir = os.path.join(self.conf, "install.d")
        self.tool = os.path.join(self.t, "tool")
        for s in SKILLS:
            spit(os.path.join(self.tool, "skills", s, "SKILL.md"), "---\nname: %s\n---\n" % s)
        spit(os.path.join(self.tool, "skills", "qargi-task", "ref.md"), "ref\n")
        spit(os.path.join(self.tool, "bin", "qargi"), "#!/bin/sh\n")
        os.makedirs(self.home)
        os.makedirs(self.conf)

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.t])

    def sk(self, runtime="claude-code"):
        return os.path.join(self.home, "." + runtime.split("-")[0], "skills")

    def mf(self, runtime="claude-code"):
        return os.path.join(self.rdir, "runtime-%s.manifest" % runtime)

    def plan(self, runtime="claude-code", copy=False, root=None):
        root = root or self.sk(runtime)
        lines = ["M\t%s\tkind=runtime\tname=%s\troot=%s" % (self.mf(runtime), runtime, root), "D\t" + root]
        for s in SKILLS:
            src = os.path.join(self.tool, "skills", s)
            lines.append(("C\t%s\t%s" if copy else "L\t%s\t%s") % (os.path.join(root, s), src))
        return "\n".join(lines) + "\n"

    def apply(self, text, force=False):
        R.apply(self.conf, text, force)

    def refused(self, fn, *a, **k):
        with self.assertRaises(R.Refused) as cm:
            fn(*a, **k)
        return str(cm.exception)

    def snapshot(self, *tops):
        """path -> (type, inode, link target) of everything under tops, without following a link."""
        out = {}
        for top in tops:
            for p in R.tree(top) if os.path.lexists(top) else []:
                st = os.lstat(p)
                out[p] = (stat.S_IFMT(st.st_mode), st.st_ino, os.readlink(p) if os.path.islink(p) else None)
        return out


class Lines(Base):
    """What a manifest may hold, by its kind: every line is checked when it is read."""

    def write_raw(self, name, header, *lines):
        path = os.path.join(self.rdir, name)
        spit(path, "\t".join(["#qargi-manifest", "2"] + list(header)) + "\n" + "".join(l + "\n" for l in lines))
        return path

    def runtime(self, *lines):
        return self.write_raw("runtime-codex.manifest", ["kind=runtime", "name=codex", "root=" + self.sk("codex")], *lines)

    def test_a_good_runtime_manifest_reads(self):
        sk = self.sk("codex")
        m = R.read(self.runtime("P\t" + os.path.dirname(sk), "P\t" + sk, "L\t%s/qargi-task\t/x/skills/qargi-task" % sk,
                                "C\t%s/qargi-flow" % sk, "d\t%s/qargi-flow/refs" % sk, "f\t%s/qargi-flow/SKILL.md" % sk))
        self.assertEqual(m.header["name"], "codex")
        self.assertEqual(len(m.lines), 6)

    def test_every_bad_line_is_refused_with_its_line_number(self):
        sk = self.sk("codex")
        bad = {"X\t%s/qargi-task" % sk: "unknown kind",
               "L\tskills/qargi-task\t/x": "absolute normalized",
               "C\t%s/../qargi-task" % sk: "absolute normalized",
               "C\t%s//qargi-task" % sk: "absolute normalized",
               "L\t%s/qargi-task" % sk: "no absolute normalized target",
               "C\t%s/qargi-task\t/x\t/y" % sk: "not KIND",
               "L\t%s/qargi-task\trelative" % sk: "target",
               "C\t%s/qargi-task\t/x" % sk: "third field",
               "C\t%s/mine" % sk: "not a place",                        # not a qargi-* entry
               "C\t%s/qargi-task" % self.home: "not a place",           # not in the root
               "f\t%s/qargi-task" % sk: "not a place",                  # a file directly in the root
               "f\t/etc/passwd": "not a place",
               "P\t%s/qargi-task" % sk: "not a place",                  # below the root
               "c\t" + self.conf: "configuration directory in a runtime"}
        for line, why in bad.items():
            with self.subTest(line=line):
                msg = self.refused(R.read, self.runtime("P\t" + sk, line))
                self.assertIn("line 3", msg)
                self.assertIn(why, msg)
                self.assertIn("nothing was changed", msg)

    def test_a_shared_manifest_holds_its_slots_its_data_and_their_parents(self):
        data, cmd = os.path.join(self.home, ".local/share/qargi"), os.path.join(self.home, ".local/bin/qargi")
        man = os.path.join(self.home, ".local/share/man/man1/qargi.1")
        hdr = ["kind=shared", "data=" + data, "slot=" + cmd, "slot=" + man]
        good = ["L\t%s\t/x/bin/qargi" % cmd, "C\t" + man, "C\t" + data, "d\t%s/lib" % data, "f\t%s/lib/a.py" % data,
                "P\t" + os.path.join(self.home, ".local"), "c\t" + self.conf, "c\t" + os.path.dirname(self.conf)]
        self.assertEqual(len(R.read(self.write_raw("shared.manifest", hdr, *good)).lines), len(good))
        for line in ("L\t%s/.bashrc\t/x" % self.home, "C\t" + self.home + "/.local/bin/other", "f\t%s/.local/share/x" % self.home,
                     "P\t%s/.cache" % self.home, "c\t%s/other" % self.t, "c\t%s/sub" % self.conf):
            with self.subTest(line=line):
                self.refused(R.read, self.write_raw("shared.manifest", hdr, line))

    def test_the_header_must_fit_the_file_and_its_kind(self):
        sk = self.sk("codex")
        cases = [("runtime-codex.manifest", ["kind=runtime", "name=claude-code", "root=" + sk]),     # names another runtime
                 ("runtime-codex.manifest", ["kind=runtime", "name=codex"]),                       # no root
                 ("runtime-codex.manifest", ["kind=runtime", "name=codex", "root=/"]),
                 ("runtime-codex.manifest", ["kind=shared", "data=/a/qargi", "slot=/a/qargi"]),
                 ("shared.manifest", ["kind=shared", "data=/a/other", "slot=/a/bin/qargi"]),      # data is not named qargi
                 ("shared.manifest", ["kind=shared", "data=/a/qargi", "slot=/a/bin/rm"]),         # a slot of another name
                 ("project-1-codex.manifest", ["kind=project", "name=codex", "project=/p", "root=/q/.agents/skills"]),
                 ("runtime-codex.manifest", ["kind=runtime", "name=codex", "root=" + sk, "colour=red"])]
        for name, hdr in cases:
            with self.subTest(name=name, hdr=hdr):
                self.refused(R.read, self.write_raw(name, hdr))
        spit(os.path.join(self.rdir, "runtime-x.manifest"), "L\t/a/qargi-x\t/b\n")
        self.assertIn("not an install manifest", self.refused(R.read, os.path.join(self.rdir, "runtime-x.manifest")))
        spit(os.path.join(self.rdir, "runtime-y.manifest"), "#qargi-manifest\t2\tkind=runtime\tname=y\troot=/a/skills")
        self.assertIn("not complete", self.refused(R.read, os.path.join(self.rdir, "runtime-y.manifest")))

    def test_a_project_manifest_stays_inside_its_project(self):
        p = os.path.join(self.t, "proj")
        root = p + "/.agents/skills"
        hdr = ["kind=project", "name=codex", "project=" + p, "root=" + root]
        ok = self.write_raw("project-7-codex.manifest", hdr, "P\t%s/.agents" % p, "L\t%s/qargi-task\t/x" % root, "c\t" + self.conf)
        self.assertEqual(R.excludes(ok), ["/.agents/skills/qargi-task"])
        self.refused(R.read, self.write_raw("project-7-codex.manifest", hdr, "P\t" + p))      # the project directory itself is not made by it

    def test_a_manifest_that_is_a_link_is_not_read(self):
        real = self.runtime()
        os.rename(real, real + ".real")
        os.symlink(real + ".real", real)
        self.assertIn("not a regular file", self.refused(R.read, real))

    def test_write_is_whole_private_and_refuses_what_could_not_be_read_back(self):
        os.makedirs(self.rdir)
        h = {"kind": "runtime", "name": "codex", "root": [self.sk("codex")], "data": [], "slot": []}
        R.write(self.mf("codex"), h, [("P", self.sk("codex"), None), ("P", self.sk("codex"), None)])
        self.assertEqual(stat.S_IMODE(os.stat(self.mf("codex")).st_mode), 0o600)
        self.assertEqual(slurp(self.mf("codex")).count("\n"), 2, "a line is written once")
        before = slurp(self.mf("codex"))
        self.refused(R.write, self.mf("codex"), h, [("f", "/etc/passwd", None)])
        self.assertEqual(slurp(self.mf("codex")), before, "a refused write leaves the record as it was")
        self.assertEqual([n for n in os.listdir(self.rdir) if n.endswith(".tmp")], [], "and no temporary file")


class Apply(Base):
    def test_install_records_then_links_and_a_second_run_changes_nothing(self):
        self.apply(self.plan())
        sk = self.sk()
        for s in SKILLS:
            self.assertEqual(os.readlink(os.path.join(sk, s)), os.path.join(self.tool, "skills", s))
        m = R.read(self.mf())
        self.assertIn(("P", sk, None), m.lines)
        self.assertIn(("P", os.path.dirname(sk), None), m.lines)
        self.assertEqual(stat.S_IMODE(os.stat(self.rdir).st_mode), 0o700)
        snap, text = self.snapshot(sk), slurp(self.mf())
        self.apply(self.plan())
        self.assertEqual(self.snapshot(sk), snap, "a link already pointing at its target is left as it is (same inode)")
        self.assertEqual(slurp(self.mf()), text, "and the record is the same, the directories the first run made included")

    def test_the_complete_manifest_is_written_before_anything_changes(self):
        seen = []
        real = R.os.symlink

        def spy(t, p):
            seen.append(R.read(self.mf()).paths())
            real(t, p)
        with mock.patch.object(R.os, "symlink", spy):
            self.apply(self.plan())
        want = {os.path.join(self.sk(), s) for s in SKILLS}
        self.assertTrue(seen and all(want <= s for s in seen), "every link is recorded before the first is made")

    def test_an_interrupted_install_leaves_a_record_the_next_run_converges_from(self):
        calls = []
        real = R.os.symlink

        def crash(t, p):
            if calls:
                raise KeyboardInterrupt
            calls.append(p)
            real(t, p)
        with mock.patch.object(R.os, "symlink", crash), self.assertRaises(KeyboardInterrupt):
            self.apply(self.plan())
        self.assertTrue(os.path.islink(calls[0]))
        self.assertIn(calls[0], R.read(self.mf()).paths(), "what was made is recorded")
        # an interrupted copy install over the links: the record lists the links and the copies
        self.apply(self.plan())
        before = self.snapshot(self.sk())
        with mock.patch.object(R, "run", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.apply(self.plan(copy=True))
        kinds = {(k, os.path.basename(p)) for k, p, _ in R.read(self.mf()).lines}
        self.assertTrue({("L", "qargi-task"), ("C", "qargi-task"), ("f", "ref.md")} <= kinds, kinds)
        self.assertNotEqual(self.snapshot(self.sk()), before)
        self.apply(self.plan(copy=True))
        m = R.read(self.mf())
        self.assertNotIn("L", {k for k, _, _ in m.lines}, "the converged record lists what is there, no more")
        self.assertTrue(os.path.isfile(os.path.join(self.sk(), "qargi-task", "ref.md")))
        R.uninstall(self.conf, [self.mf()], True, lambda _: None)
        self.assertFalse(os.path.lexists(os.path.dirname(self.sk())), "and an uninstall then leaves nothing")

    def test_nothing_unrecorded_is_replaced_without_force(self):
        sk = self.sk()
        os.makedirs(os.path.join(sk, "qargi-task"))
        spit(os.path.join(sk, "qargi-task", "mine.md"), "mine\n")
        os.symlink("/elsewhere", os.path.join(sk, "qargi-flow"))
        snap = self.snapshot(sk)
        msg = self.refused(self.apply, self.plan())
        self.assertIn("refusing to replace", msg)
        self.assertEqual(self.snapshot(sk), snap)
        self.assertFalse(os.path.exists(self.rdir), "a refused install records nothing")
        os.rename(os.path.join(sk, "qargi-task"), os.path.join(self.t, "mine"))
        self.assertIn("a link to /elsewhere that no install recorded (use --force)", self.refused(self.apply, self.plan()))
        self.apply(self.plan(), force=True)
        self.assertEqual(os.readlink(os.path.join(sk, "qargi-flow")), os.path.join(self.tool, "skills", "qargi-flow"))

    def test_a_recorded_link_replaced_by_a_file_or_a_directory_is_yours_and_nothing_changes(self):
        self.apply(self.plan("codex"))
        self.apply(self.plan())
        moved = os.path.join(self.t, "moved")
        subprocess.run(["cp", "-r", self.tool, moved], check=True)
        again = (self.plan("codex") + self.plan()).replace(self.tool, moved)     # one run: codex first, then claude-code, from a moved tool
        task, flow = os.path.join(self.sk(), "qargi-task"), os.path.join(self.sk(), "qargi-flow")
        os.unlink(task)
        spit(task, "#!/bin/sh\nexec mine\n")                         # a wrapper of yours where the install recorded a link
        os.unlink(flow)
        os.mkdir(flow)                                               # and an empty directory of yours
        snap, recs = self.snapshot(self.home), {n: slurp(os.path.join(self.rdir, n)) for n in os.listdir(self.rdir)}
        for _ in range(2):                                           # a second run refuses the same way: no change, no loop
            msg = self.refused(self.apply, again)
            self.assertIn("refusing to replace %s: the install recorded a link there and it is now a file, which is yours" % task, msg)
            self.assertIn("nothing was changed: move it aside and install again, or install with --force", msg)
            self.assertNotIn("run the install again", msg)
            self.assertEqual(self.snapshot(self.home), snap, "the codex part before it is not touched either")
            self.assertEqual({n: slurp(os.path.join(self.rdir, n)) for n in os.listdir(self.rdir)}, recs)
        os.rename(task, os.path.join(self.t, "wrapper"))
        self.assertIn("%s: the install recorded a link there and it is now a directory" % flow, self.refused(self.apply, again))
        os.rmdir(flow)
        self.apply(again)
        self.assertEqual(os.readlink(task), os.path.join(moved, "skills", "qargi-task"))
        self.assertEqual(os.readlink(os.path.join(self.sk("codex"), "qargi-task")), os.path.join(moved, "skills", "qargi-task"))

    def test_a_link_to_the_target_is_adopted_as_it_is(self):
        sk = self.sk()
        os.makedirs(sk)
        p = os.path.join(sk, "qargi-task")
        os.symlink(os.path.join(self.tool, "skills", "qargi-task"), p)
        ino = os.lstat(p).st_ino
        self.apply(self.plan())
        self.assertEqual(os.lstat(p).st_ino, ino)
        self.assertIn(("L", p, os.path.join(self.tool, "skills", "qargi-task")), R.read(self.mf()).lines)

    def test_a_copied_skill_with_a_file_of_yours_is_not_ours(self):
        self.apply(self.plan(copy=True))
        sk = self.sk()
        self.apply(self.plan(copy=True))                            # its own copy: no --force needed
        os.makedirs(os.path.join(sk, "qargi-task", "__pycache__"))  # bytecode inside a copied directory is the copy's
        self.apply(self.plan(copy=True))
        spit(os.path.join(sk, "qargi-task", "notes.md"), "mine\n")
        self.assertIn("refusing to replace existing %s/qargi-task" % sk, self.refused(self.apply, self.plan(copy=True)))

    def test_one_skills_directory_holds_one_runtime(self):
        self.apply(self.plan())
        os.makedirs(os.path.join(self.home, ".codex"))
        os.symlink(self.sk(), self.sk("codex"))
        msg = self.refused(self.apply, self.plan("codex"))
        self.assertIn("one skills directory holds the skills of one runtime", msg)
        self.assertFalse(os.path.exists(self.mf("codex")))

    def test_a_refresh_that_moves_the_skills_directory_cleans_the_old_one(self):
        self.apply(self.plan())
        new = os.path.join(self.home, ".alt", "skills")
        self.apply(self.plan(root=new))
        self.assertFalse(os.path.lexists(os.path.join(self.home, ".claude")), "the old directory the install made is gone")
        self.assertEqual(R.read(self.mf()).header["root"], [new])

    def test_a_plan_is_checked(self):
        for text in ("L\t/a/qargi-x\t/b\n", "M\t/elsewhere/runtime-x.manifest\tkind=runtime\tname=x\troot=/a/skills\n",
                     "M\t%s\tkind=runtime\tname=claude-code\troot=%s\nX\t/a\n" % (self.mf(), self.sk()),
                     "M\t%s\tkind=runtime\tname=claude-code\troot=%s\nC\t%s/qargi-x\t/src\t../x\n" % (self.mf(), self.sk(), self.sk())):
            with self.subTest(text=text):
                self.refused(self.apply, text)
        self.assertFalse(os.path.exists(self.rdir))


class Remove(Base):
    def test_uninstall_removes_what_is_listed_keeps_the_rest_and_leaves_no_record(self):
        made = os.path.join(self.t, "made")
        conf = os.path.join(made, "config")
        os.makedirs(conf)
        self.conf, self.rdir = conf, os.path.join(conf, "install.d")
        proj = os.path.join(self.t, "proj")
        sk, pm = os.path.join(proj, ".claude", "skills"), os.path.join(self.rdir, "project-9-claude-code.manifest")
        os.makedirs(proj)
        self.apply(self.plan(root=sk).replace("M\t%s\tkind=runtime\tname=claude-code\t" % self.mf(),
                                              "M\t%s\tkind=project\tname=claude-code\tproject=%s\t" % (pm, proj))
                   + "c\t%s\nc\t%s\n" % (conf, made))
        spit(os.path.join(conf, "install.lock"), "")
        os.unlink(os.path.join(sk, "qargi-flow"))
        os.symlink("/mine", os.path.join(sk, "qargi-flow"))         # retargeted by you
        said = []
        self.assertEqual(R.excludes(pm), ["/.claude/skills/" + s for s in SKILLS])
        R.uninstall(conf, [pm], False, said.append)
        self.assertEqual(os.readlink(os.path.join(sk, "qargi-flow")), "/mine")
        self.assertFalse(os.path.lexists(os.path.join(sk, "qargi-task")))
        self.assertIn("kept %s/qargi-flow (a link to /mine, not the one the install made)" % sk, said)
        self.assertFalse(os.path.exists(made), "the record, its directory, the lock and the empty configuration directories it made go")

    def test_uninstall_checks_every_record_before_it_removes_anything(self):
        self.apply(self.plan())
        self.apply(self.plan("codex"))
        with open(self.mf("codex"), "a") as f:
            f.write("f\t/etc/passwd\n")
        snap = self.snapshot(self.home)
        self.refused(R.uninstall, self.conf, [self.mf(), self.mf("codex")], False, print)
        self.assertEqual(self.snapshot(self.home), snap)
        self.assertTrue(os.path.isfile(self.mf()))

    def test_the_bytecode_inside_a_copied_directory_goes_with_it(self):
        self.apply(self.plan(copy=True))
        pyc = os.path.join(self.sk(), "qargi-task", "__pycache__")
        spit(os.path.join(pyc, "x.pyc"), "")
        R.uninstall(self.conf, [self.mf()], False, lambda _: None)
        self.assertFalse(os.path.lexists(self.sk()))


class Migrate(Base):
    """The one-time move of the single install.manifest of 0.3.1 into install.d (removed in 0.3.3). The legacy file is a literal fixture
    in the two-field format 0.3.1 wrote, beside the links it lists."""

    def setUp(self):
        super().setUp()
        self.env = mock.patch.dict(os.environ, {"HOME": self.home})
        self.env.start()
        self.addCleanup(self.env.stop)
        h = self.home
        self.data = os.path.join(h, ".local/share/qargi")
        self.slots = [os.path.join(h, ".local/bin/qargi"), os.path.join(h, ".local/share/man/man1/qargi.1"),
                      os.path.join(h, ".local/share/bash-completion/completions/qargi"), os.path.join(h, ".local/share/zsh/site-functions/_qargi"),
                      os.path.join(h, ".config/fish/completions/qargi.fish")]
        rel = ["bin/qargi", "man/qargi.1", "completions/qargi.bash", "completions/_qargi", "completions/qargi.fish"]
        sk = self.sk()
        os.makedirs(sk)
        for s in SKILLS:
            os.symlink(os.path.join(self.tool, "skills", s), os.path.join(sk, s))
        for p, r in zip(self.slots, rel):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            os.symlink(os.path.join(self.tool, r), p)
        spit(os.path.join(self.conf, "install.json"), json.dumps({"tool_root": self.tool, "installed_at": "2026-11-16T00:00:00Z", "version": "0.3.1"}))
        self.legacy = os.path.join(self.conf, "install.manifest")
        spit(self.legacy, "".join("L\t%s\n" % p for p in [os.path.join(sk, s) for s in SKILLS] + self.slots)
             + "P\t%s\nP\t%s\nP\t%s\n" % (os.path.join(h, ".claude"), sk, os.path.join(h, ".local/bin")))
        self.said = []

    def migrate(self, tool=None):
        R.migrate(self.conf, self.data, self.slots, tool or self.tool, self.said.append)

    def test_the_legacy_manifest_splits_into_the_runtime_and_the_shared_record(self):
        snap = self.snapshot(self.home)
        self.migrate()
        self.assertEqual(sorted(os.listdir(self.rdir)), ["runtime-claude-code.manifest", "shared.manifest"])
        self.assertFalse(os.path.exists(self.legacy), "the legacy file goes once install.d is committed")
        self.assertEqual(stat.S_IMODE(os.stat(self.rdir).st_mode), 0o700)
        rt, sh = R.read(self.mf()), R.read(os.path.join(self.rdir, "shared.manifest"))
        self.assertEqual({(k, p, t) for k, p, t in rt.lines if k == "L"},
                         {("L", os.path.join(self.sk(), s), os.path.join(self.tool, "skills", s)) for s in SKILLS})
        self.assertIn(("P", os.path.join(self.home, ".claude"), None), rt.lines)
        self.assertEqual(len([x for x in sh.lines if x[0] == "L"]), 5)
        self.assertIn(("P", os.path.join(self.home, ".local/bin"), None), sh.lines)
        self.assertEqual(self.snapshot(self.home), snap, "the migration changes no link")
        self.assertFalse(os.path.exists(os.path.join(self.conf, "install.d.new")))

    def test_a_link_that_no_longer_points_into_the_tool_is_not_carried(self):
        p = os.path.join(self.sk(), "qargi-flow")
        os.unlink(p)
        os.symlink("/mine", p)
        os.unlink(self.slots[1])
        self.migrate()
        paths = R.read(self.mf()).paths() | R.read(os.path.join(self.rdir, "shared.manifest")).paths()
        self.assertNotIn(p, paths)
        self.assertNotIn(self.slots[1], paths)
        self.assertIn("not carried over: %s (no longer the link the install made)" % p, self.said)

    def test_a_line_outside_the_install_is_refused_and_nothing_changes(self):
        for line in ("f\t%s/.bashrc\n" % self.home, "C\t/etc\n", "d\trelative/dir\n", "P\t%s/.cache\n" % self.home, "x\t%s\n" % self.sk()):
            with self.subTest(line=line):
                text = slurp(self.legacy)
                spit(self.legacy, text + line)
                msg = self.refused(self.migrate)
                self.assertIn("nothing was changed", msg)
                self.assertEqual(slurp(self.legacy), text + line)
                self.assertFalse(os.path.lexists(self.rdir))
                self.assertFalse(os.path.lexists(os.path.join(self.conf, "install.d.new")))
                spit(self.legacy, text)

    def test_skills_of_no_known_runtime_are_refused(self):
        spit(self.legacy, "L\t%s/.other/skills/qargi-task\n" % self.home)
        self.assertIn("cannot tell which runtime", self.refused(self.migrate))
        self.assertTrue(os.path.isfile(self.legacy))
        self.assertFalse(os.path.lexists(self.rdir))

    def test_a_project_manifest_moves_to_its_runtime(self):
        proj = os.path.join(self.t, "proj")
        root = os.path.join(proj, ".agents", "skills")
        os.makedirs(root)
        os.symlink(os.path.join(self.tool, "skills", "qargi-task"), os.path.join(root, "qargi-task"))
        spit(os.path.join(self.conf, "project-123.manifest"), "c\t%s\nP\t%s/.agents\nP\t%s\nL\t%s/qargi-task\n" % (self.conf, proj, root, root))
        self.migrate()
        m = R.read(os.path.join(self.rdir, "project-123-codex.manifest"))
        self.assertEqual(m.header["project"], proj)
        self.assertIn(("L", root + "/qargi-task", os.path.join(self.tool, "skills", "qargi-task")), m.lines)
        self.assertFalse(os.path.exists(os.path.join(self.conf, "project-123.manifest")))

    def test_it_runs_once_and_an_interrupted_one_starts_again_from_the_legacy_files(self):
        with mock.patch.object(R.os, "rename", side_effect=KeyboardInterrupt), self.assertRaises(KeyboardInterrupt):
            self.migrate()
        self.assertTrue(os.path.isfile(self.legacy))
        self.assertFalse(os.path.lexists(self.rdir))
        # a crash between the commit and the removal of the legacy file: install.d is there, so the file is removed unread
        real = R.os.unlink
        with mock.patch.object(R.os, "unlink", side_effect=lambda p: (_ for _ in ()).throw(KeyboardInterrupt) if p == self.legacy else real(p)), \
                self.assertRaises(KeyboardInterrupt):
            self.migrate()
        self.assertTrue(os.path.isfile(self.legacy) and os.path.isdir(self.rdir))
        before = slurp(self.mf())
        spit(self.legacy, "f\t/etc/passwd\n")             # planted after the commit: never read
        self.migrate()
        self.assertFalse(os.path.exists(self.legacy))
        self.assertEqual(slurp(self.mf()), before)
        self.assertTrue(any("was not read" in s for s in self.said), self.said)

    def test_a_leftover_install_d_new_is_removed_and_never_read(self):
        new = os.path.join(self.conf, "install.d.new")
        precious = os.path.join(self.home, "precious")
        spit(precious, "keep\n")
        spit(os.path.join(new, "runtime-codex.manifest"),
             "#qargi-manifest\t2\tkind=runtime\tname=codex\troot=%s\nf\t%s/qargi-x/y\n" % (self.home, self.home))
        spit(os.path.join(new, "shared.manifest"), "planted\n")
        self.migrate()
        self.assertEqual(sorted(os.listdir(self.rdir)), ["runtime-claude-code.manifest", "shared.manifest"], "built from the legacy file alone")
        self.assertFalse(os.path.lexists(new))
        self.assertTrue(os.path.isfile(precious))
        # with no legacy file left, a planted install.d.new and a temporary manifest in install.d are removed all the same
        spit(os.path.join(new, "runtime-codex.manifest"), "planted\n")
        spit(os.path.join(self.rdir, ".runtime-codex.manifest.x1.tmp"), "planted\n")
        self.migrate()
        self.assertFalse(os.path.lexists(new))
        self.assertEqual(sorted(os.listdir(self.rdir)), ["runtime-claude-code.manifest", "shared.manifest"])
        self.assertIn("removed %s, left by an interrupted migration (not read)" % new, self.said)


class Verbs(Base):
    def cli(self, *argv, stdin=""):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err), mock.patch.object(R.sys, "stdin", io.StringIO(stdin)):
            rc = R.main(list(argv))
        return rc, out.getvalue(), err.getvalue()

    def test_state_lists_the_records_and_the_install_json(self):
        self.apply(self.plan())
        self.apply(self.plan("codex"))
        p = os.path.join(self.t, "proj")
        root = p + "/.agents/skills"
        os.makedirs(p)
        pm = os.path.join(self.rdir, "project-42-codex.manifest")
        self.apply("M\t%s\tkind=project\tname=codex\tproject=%s\troot=%s\nD\t%s\n" % (pm, p, root, root))
        rc, out, _ = self.cli("record", "--conf", self.conf, "--tool-root", self.tool, "--version", "0.3.2", "--source", "link")
        self.assertEqual(rc, 0)
        j = json.loads(slurp(os.path.join(self.conf, "install.json")))
        self.assertEqual(sorted(j), ["installed_at", "source", "tool_root", "version"])
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.conf, "install.json")).st_mode), 0o600)
        rc, out, _ = self.cli("state", "--conf", self.conf)
        self.assertEqual(out.splitlines(), ["runtime\tclaude-code\t" + self.mf(), "runtime\tcodex\t" + self.mf("codex"),
                                            "record\t%s\tlink" % self.tool])
        rc, out, _ = self.cli("state", "--conf", self.conf, "--project-key", "42")
        self.assertIn("project\tcodex\t" + pm, out.splitlines())

    def test_a_record_without_source_reads_as_link_or_copy_by_its_tool_root(self):
        data = os.path.join(self.t, "data", "qargi")
        spit(os.path.join(self.conf, "install.json"), json.dumps({"tool_root": data}))
        self.assertEqual(R.state(self.conf, data, None), ["record\t%s\tcopy" % data])
        self.assertEqual(R.state(self.conf, "/other/qargi", None), ["record\t%s\tlink" % data])

    def test_a_refusal_is_status_1_with_the_reason(self):
        os.makedirs(self.rdir)
        spit(self.mf(), "junk\n")
        rc, _, err = self.cli("state", "--conf", self.conf)
        self.assertEqual(rc, 1)
        self.assertIn("not an install manifest", err)
        os.unlink(self.mf())
        os.rmdir(self.rdir)
        os.symlink(self.t, self.rdir)
        rc, _, err = self.cli("apply", "--conf", self.conf, stdin=self.plan())
        self.assertEqual(rc, 1)
        self.assertIn("is not a directory", err)


if __name__ == "__main__":
    unittest.main()
