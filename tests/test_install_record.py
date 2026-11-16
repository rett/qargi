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
