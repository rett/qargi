#!/usr/bin/env python3
"""The role cards (lib/rolecard.py): what a role is held to, said before the guard or a verb refuses it. The golden cards; the word and character
ceilings; both directions against the guard (each command a card calls lawful is let through under the class, each one it calls refused is refused,
from a shell in the clone and from one in TMP); every command a card shows is one the card has been checked on, and every `qargi X Y` it shows is
a command of lib/commands.py; the lead card's tail from the stored member states. Offline; a scratch home. Run: python3 tests/test_rolecard.py
UPDATE_GOLDEN=1 python3 tests/test_rolecard.py rewrites tests/golden/rolecard/* (read the diff before committing it)."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, shutil, subprocess, sys, tempfile, unittest
from unittest import mock

TESTS = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(TESTS)
LIB = os.path.join(ROOT, "lib")
BIN = os.path.join(ROOT, "bin", "qargi")
GOLD = os.path.join(TESTS, "golden", "rolecard")
sys.path.insert(0, LIB)
sys.path.insert(0, TESTS)
import rolecard as RC  # noqa: E402
import commands as C  # noqa: E402
import test_guard as TG  # noqa: E402  (its in-process judge: the guard of any revision in this process)

PY = [sys.executable, "-B", "-I"]
SCOPE_LINE = re.compile(r"(?m)^[ \t]*(?:[-*][ \t]+)?SCOPE:[ \t]*(.*)$")        # the line review check reads as the limit of a run (lib/review_check.py)
TB_LINE = re.compile(r"^(ROLE|ABILITY|TASK|DONE|PROFILE|BASE|BASE_SHA|SCOPE|RUN_DIR|CLONE|OUT|TMP|GIT|CONTRACT|CARD|SUBMODULES):")


def run(args, **kw):
    kw.setdefault("env", os.environ)
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True, **kw)


def golden(case, name, text):
    path = os.path.join(GOLD, name)
    if os.environ.get("UPDATE_GOLDEN"):
        os.makedirs(GOLD, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text + "\n")
    with open(path, encoding="utf-8") as f:
        case.assertEqual(f.read(), text + "\n", "the card differs from tests/golden/rolecard/%s (UPDATE_GOLDEN=1 rewrites it)" % name)


def live_root():
    """A root whose catalogue has the two seat codes the lead card waits for (the approval refusal, the dispatch refusal) live."""
    d = tempfile.mkdtemp(prefix="cardroot.")
    os.makedirs(os.path.join(d, "lib"))
    with open(os.path.join(LIB, "refusals.json"), encoding="utf-8") as f:
        cat = json.load(f)
    for code in ("approval-refused", "member-sandbox-off"):
        cat["codes"][code]["status"] = "live"
    with open(os.path.join(d, "lib", "refusals.json"), "w", encoding="utf-8") as f:
        json.dump(cat, f)
    return d


def write_states(state, project, at, members):
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "agent-states.json"), "w", encoding="utf-8") as f:
        json.dump({"schema": 1, "projects": {project: {"at": at, "members": members}}}, f)


class Cards(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="card.")
        self.addCleanup(shutil.rmtree, self.t, True)

    def test_the_golden_cards(self):
        golden(self, "write.txt", RC.card("build")["card"])
        golden(self, "read-only.txt", RC.card("review")["card"])
        golden(self, "lead.txt", RC.card("lead")["card"])
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        state = os.path.join(self.t, "state")
        write_states(state, "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"], "scribe": ["DRIFT", "STALE"], "ok": []})
        golden(self, "lead-live-stale.txt", RC.card("lead", project="acme", root=root, state=state)["card"])

    def test_a_card_is_the_same_for_every_role_of_its_class_and_names_the_run_paths_when_given_one(self):
        for role in ("build", "write", "test"):
            self.assertEqual(RC.card(role)["card"], RC.card("build")["card"], role)
            self.assertEqual(RC.card(role)["class"], "write")
        self.assertEqual(RC.card("review")["class"], "read-only")
        self.assertEqual(RC.card("lead")["class"], "lead")
        run_dir = os.path.join(self.t, "qargi.abc123")
        os.makedirs(os.path.join(run_dir, "clone"))
        with open(os.path.join(run_dir, "tmpdir"), "w") as f:
            f.write(os.path.join(self.t, "scratch") + "\n")
        got = RC.card("review", run=run_dir)["card"]
        for path in (os.path.join(run_dir, "clone"), os.path.join(run_dir, "out"), os.path.join(self.t, "scratch"), run_dir):
            self.assertIn(path, got)
        self.assertNotIn("{", got)
        self.assertNotIn("CLONE x", got)
        self.assertEqual(RC.card("review")["card"], got.replace(os.path.join(run_dir, "clone"), "CLONE").replace(os.path.join(run_dir, "out"), "OUT")
                         .replace(os.path.join(self.t, "scratch"), "TMP").replace(run_dir, "RUN"), "the words stand for the paths")

    def test_the_ceilings(self):
        for role, cls in (("build", "write"), ("review", "read-only"), ("lead", "lead")):
            c = RC.card(role)
            self.assertLessEqual(c["words"], RC.CEILING[cls], (role, c["words"]))
        state = os.path.join(self.t, "state")
        write_states(state, "acme", "2026-11-21T10:00:00Z", {"member%d" % i: ["STALE"] for i in range(40)})
        c = RC.card("lead", project="acme", state=state)
        self.assertLessEqual(c["words"], RC.CEILING["lead"], "the lead card with a tail of three members and a count")
        self.assertIn("and 37 more", c["card"])

    def test_the_lead_card_with_every_line_live_and_the_longest_tail_fits_the_hooks_room(self):
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        state = os.path.join(self.t, "state")
        long = lambda i: ("m%02d" % i).ljust(41, "x")                       # a member name at the longest the form allows
        write_states(state, "acme", "2026-11-21T10:00:00Z", {long(i): ["STALE", "DRIFT"] for i in range(40)})
        c = RC.card("lead", project="acme", root=root, state=state)
        self.assertLessEqual(c["chars"], RC.LEAD_CHARS)
        self.assertIn("Members STALE or DRIFT as of", c["card"], "fewer names, still a tail")
        base = RC.card("lead", root=root)
        self.assertLessEqual(base["chars"], RC.LEAD_CHARS - 150, "room is left for the tail")

    def test_a_tail_that_cannot_fit_is_left_out_whole(self):
        state = os.path.join(self.t, "state")
        write_states(state, "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"]})
        old = RC.LEAD_CHARS
        self.addCleanup(setattr, RC, "LEAD_CHARS", old)
        RC.LEAD_CHARS = len(RC.card("lead")["card"]) + 20
        c = RC.card("lead", project="acme", state=state)
        self.assertEqual(c["card"], RC.card("lead")["card"])
        self.assertIsNone(c["members_stale"])

    def test_a_card_names_no_runtime(self):
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        for text in (RC.card("build")["card"], RC.card("review")["card"], RC.card("lead", root=root)["card"]):
            self.assertIsNone(re.search(r"(?i)claude|codex|anthropic|openai|gemini|cursor|copilot", text), text)

    def test_a_line_waits_for_its_code_to_be_live(self):
        text = RC.card("lead")["card"]
        self.assertNotIn("member-sandbox-off", text)
        self.assertNotIn("approval-refused", text)
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        text = RC.card("lead", root=root)["card"]
        codes = RC.catalogue(root)
        self.assertIn("Dispatch refused with member-sandbox-off: " + codes["member-sandbox-off"]["next"]["lead"], text)
        self.assertIn("approval-refused", text)

    def test_the_lead_card_tells_what_the_review_of_the_design_asked(self):
        text = RC.card("lead")["card"]
        for need in ("--plan TOKEN --approved", "--dry-run", "qargi local list", "qargi release fix VER --record", "no approval", "inside the cut", "own plan",
                     "qargi ref record", "qargi ref note", "owner's own words", "cannot tell relayed words apart"):
            self.assertIn(need, text)
        for area in RC.plan_areas():
            self.assertIn(area, text.split("by area:")[1].split("(")[0])
        for verb in RC.TERMINAL:
            area, name = verb.split()
            self.assertIn(name, C.COMMANDS[area]["verbs"], verb)

    def test_the_read_only_card_says_the_things_a_reviewer_has_got_wrong(self):
        text = RC.card("review")["card"]
        for need in ("Do not run the whole suite", "OUT/report.md", "qargi local report RUN < FILE", "--from NAME", "reads OUT only", "git -C TMP clone CLONE x",
                     "a relative directory lands under -C", "git -C TMP/x am", "cp -a CLONE TMP/x", "git worktree add", "git show BASE_SHA:PATH", "git diff BASE_SHA",
                     "Assign no variable that picks a program or options", "PATH, HOME, TMPDIR, GIT_*, LD_*, BASH_*, PYTHONPATH, NODE_OPTIONS", "see `qargi help guard`",
                     "A target platform (GOOS, GOARCH)", "systemd-run", "TMPDIR is TMP, where Go tests write", "[code]", RC.TEXT_LINE[0]):
            self.assertIn(need, text)
        self.assertNotIn("Other build variables", text, "a variable that is not a target platform is not allowed because it is a build variable")
        text = RC.card("build")["card"]
        for need in ("git push", "the lead's verbs", "the lead's directories", "with its token; never apply it", "[code]", "the lead runs the suite", RC.TEXT_LINE[0]):
            self.assertIn(need, text)
        for text in (RC.card("build")["card"], RC.card("review")["card"]):
            self.assertIn("starts with git push, ssh or gh is refused: write such text with your file tool", text)


class RoleText(unittest.TestCase):
    """What the card says, the role text and the member body no longer do: one place for what the guard holds a role to."""

    def read(self, rel):
        with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
            return f.read()

    def test_the_review_role_leaves_the_guard_to_the_card(self):
        text = self.read("roles/review/ROLE.md")
        for gone in ("TMPDIR", "GIT_*", "the guard cuts", "git push", "go build", "never the clone"):
            self.assertNotIn(gone.lower(), text.lower(), gone)
        self.assertIn("PATH, HOME, TMPDIR, GIT_*", RC.card("review")["card"])

    def test_no_role_text_says_what_the_guard_refuses(self):
        for role in ("build", "write", "test", "review"):
            text = self.read("roles/%s/ROLE.md" % role).lower()
            self.assertNotIn("the guard", text, role)

    def test_the_member_body_names_the_card_and_keeps_its_opening(self):
        for rel in ("agents/member.body.md", "agents/member.md"):
            text = self.read(rel)
            self.assertIn("Your CARD lists the guard's limits.", text)
            self.assertIn("Protection depends on selected runtime contract addenda. Hookless runtimes enforce no qargi guard.", text)
            self.assertNotIn("refuses the usual ways", text)


class Commands(unittest.TestCase):
    """Every command a card shows is one it has been checked on, and every qargi command is one the tool has."""

    def spans(self, text):
        return re.findall(r"`([^`\n]+)`", text)

    def test_every_git_or_cp_command_on_a_card_is_a_probe(self):
        for role, cls in (("build", "write"), ("review", "read-only")):
            card = RC.card(role)["card"]
            p = RC.probes(cls)
            known = set(p["allowed"]) | set(p["refused"])
            for span in self.spans(card):
                if not span.startswith(("git ", "cp ")):
                    continue
                if span == "git worktree add":                        # a form, not a command: its probes are `git -C CLONE worktree add ...`
                    self.assertTrue(any("worktree add" in c for c in p["refused"]))
                    continue
                self.assertIn(span.replace("BASE_SHA", "abc123"), known, "%s: `%s` is on the card and has no probe" % (role, span))

    def test_every_qargi_command_on_a_card_is_in_the_command_table(self):
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        for text in (RC.card("build")["card"], RC.card("review")["card"], RC.card("lead", root=root)["card"]):
            for span in self.spans(text):
                m = re.match(r"qargi ([a-z][a-z-]*)(?: ([a-z][a-z-]*))?", span)
                if not m:
                    continue
                self.assertIn(m.group(1), C.COMMANDS, span)
                verbs = C.COMMANDS[m.group(1)].get("verbs")
                if m.group(2) and isinstance(verbs, dict):
                    self.assertIn(m.group(2), verbs, span)

    def test_no_line_of_a_card_reads_as_a_line_of_the_task_block(self):
        root = live_root()
        self.addCleanup(shutil.rmtree, root, True)
        for text in (RC.card("build")["card"], RC.card("review")["card"], RC.card("lead", root=root)["card"]):
            for line in text.split("\n"):
                self.assertIsNone(SCOPE_LINE.match(line), line)
                self.assertIsNone(TB_LINE.match(line), line)


class GuardBothWays(unittest.TestCase):
    """L7: what a card calls lawful the guard lets through, what it calls refused the guard refuses, from the clone and from TMP, under the class."""

    @classmethod
    def setUpClass(cls):
        cls.J = TG._Judge(TG.LIBDIR, "guard_rolecard", None)

    @classmethod
    def tearDownClass(cls):
        del cls.J

    def fixture(self, ability, cls):
        """A run as the lead prepares it when the system has a shared-memory directory: the run directory with its record, and TMP away from it, found only through the lead's
        registry (STATE/local-runs.jsonl), as a real review-only member finds it (tmp_run in lib/guard.py). The class file says what the run is held to."""
        t = tempfile.mkdtemp(prefix="guardcard.")
        self.addCleanup(shutil.rmtree, t, True)
        self.run_dir = os.path.join(t, "qargi.x")
        tmp = os.path.join(t, "shm", "qargi-run.X")
        state = os.path.join(t, "state")
        for d in ("clone/src", "out"):
            os.makedirs(os.path.join(self.run_dir, d))
        os.makedirs(tmp)
        os.makedirs(state)
        open(os.path.join(self.run_dir, "refs.before"), "w").close()
        for name, text in (("ability", ability), ("class", cls), ("tmpdir", tmp)):
            with open(os.path.join(self.run_dir, name), "w") as f:
                f.write(text + "\n")
        with open(os.path.join(state, "local-runs.jsonl"), "w") as f:
            f.write(json.dumps({"run": self.run_dir, "tmpdir": tmp}) + "\n")
        patch = mock.patch.dict(os.environ, {"QARGI_STATE": state})
        patch.start()
        self.addCleanup(patch.stop)
        self.assertFalse(os.path.exists(os.path.join(self.run_dir, "tmp")), "TMP is not the run's tmp directory")
        return {"clone": os.path.join(self.run_dir, "clone"), "out": os.path.join(self.run_dir, "out"), "tmp": tmp, "run": self.run_dir}

    def judge(self, cmd, cwd, under=""):
        self.J.cwd = cwd
        return self.J.judge(cmd, under)

    def both_ways(self, ability, cls, judged):
        """judged: (where the shell is, what the guard is started with): "clone" or "tmp", and its --class. Started with no class, the guard finds the run from the
        directory the shell is in, so TMP (away from the run) is judged under the class alone, as the hook starts a read-only member."""
        p = self.fixture(ability, cls)
        probes = RC.probes(cls, p)
        self.assertGreater(len(probes["allowed"]), 3)
        self.assertGreater(len(probes["refused"]), 3)
        for where, under in judged:
            cwd = p[where]
            for cmd in probes["allowed"]:
                self.assertIsNone(self.judge(cmd, cwd, under), "the card says `%s` is lawful for class %s (shell in %s, --class %r)" % (cmd, cls, cwd, under))
            for cmd in probes["refused"]:
                got = self.judge(cmd, cwd, under)
                self.assertTrue(got and "qargi guard:" in got,
                                "the card says `%s` is refused for class %s (shell in %s, --class %r), the guard says %r" % (cmd, cls, cwd, under, got))

    def test_the_read_only_card(self):
        self.both_ways("review", "read-only", (("clone", ""), ("clone", "read-only"), ("tmp", "read-only")))

    def test_the_write_card(self):
        self.both_ways("build", "write", (("clone", ""), ("tmp", "")))

    def test_every_variable_the_read_only_card_names_is_one_the_guard_refuses_to_assign(self):
        """The card names PATH, HOME, TMPDIR, GIT_*, LD_*, BASH_*, PYTHONPATH and NODE_OPTIONS: the guard's own table (RESTRICTED_ENV and its prefixes) holds each, so the
        card says nothing the guard does not hold to; a target platform, which it allows, is in neither."""
        G = self.J.m
        card = RC.card("review")["card"]
        names = re.search(r"\(([^()]*), \.\.\.;", card).group(1).split(", ")
        self.assertIn("PYTHONPATH", names)
        self.assertIn("NODE_OPTIONS", names)
        for name in names:
            self.assertTrue(G.restricted_name(name.replace("*", "x")), name)
        for name in ("GOOS", "GOARCH"):
            self.assertFalse(G.restricted_name(name), name)

    def test_the_skills_directory_of_the_runtime_is_one_of_the_lead_directories_the_write_card_names(self):
        """The card says `skills`; the directory is the runtime's (its definition names it), so the module cannot probe it by name: this does, under both classes."""
        dirs = run(PY + [os.path.join(LIB, "provider.py"), "skills-dirs"]).stdout.split()
        self.assertTrue(dirs)
        for ability in ("build", "review"):
            p = self.fixture(ability, "read-only" if ability == "review" else "write")
            for d in dirs:
                for cwd in (p["clone"], p["tmp"]):
                    got = self.judge("printf x > ~/%s/x" % d, cwd)
                    self.assertTrue(got and "qargi guard:" in got, (ability, d, cwd, got))

    def test_the_card_commands_with_the_words_for_the_paths_are_judged_alike(self):
        """The probes of a card made with no run are the words CLONE, OUT, TMP and RUN: still commands, and the lists are as long as with real paths."""
        for cls in ("read-only", "write"):
            self.assertEqual(len(RC.probes(cls)["allowed"]), len(RC.probes(cls, self.fixture("review" if cls == "read-only" else "build", cls))["allowed"]))


class LeadTail(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="tail.")
        self.addCleanup(shutil.rmtree, self.t, True)

    def tail(self, project="acme"):
        c = RC.card("lead", project=project, state=self.t)
        return c, [l for l in c["card"].split("\n") if l.startswith("- Members STALE or DRIFT")]

    def test_no_stored_reading_no_line(self):
        c, lines = self.tail()
        self.assertEqual(lines, [])
        self.assertIsNone(c["members_stale"])

    def test_the_line_names_the_members_and_the_time(self):
        write_states(self.t, "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"], "scribe": ["DRIFT", "STALE"], "fine": []})
        c, lines = self.tail()
        self.assertEqual(lines, ["- Members STALE or DRIFT as of 2026-11-21T10:00:00Z: forge (STALE), scribe (STALE, DRIFT); `qargi agent list` names the fix."])
        self.assertEqual(c["members_stale"], {"as_of": "2026-11-21T10:00:00Z", "members": {"forge": ["STALE"], "scribe": ["STALE", "DRIFT"]}})

    def test_three_members_and_the_rest_as_a_count(self):
        write_states(self.t, "acme", "2026-11-21T10:00:00Z", {"m%d" % i: ["DRIFT"] for i in range(5)})
        self.assertIn("m0 (DRIFT), m1 (DRIFT), m2 (DRIFT) and 2 more;", self.tail()[1][0])

    def test_nothing_in_a_listed_state_no_line(self):
        write_states(self.t, "acme", "2026-11-21T10:00:00Z", {"forge": [], "scribe": ["MISSING"]})
        self.assertEqual(self.tail()[1], [])

    def test_another_project_or_none_no_line(self):
        write_states(self.t, "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"]})
        self.assertEqual(self.tail("other")[1], [])
        self.assertEqual(RC.card("lead", state=self.t)["card"], RC.card("lead")["card"])

    def test_a_file_that_is_not_what_qargi_writes_is_left_out(self):
        path = os.path.join(self.t, "agent-states.json")
        for doc in ("not json", "[]", '{"projects": 1}', '{"projects": {"acme": {"at": "yesterday", "members": {"a": ["STALE"]}}}}',
                    '{"projects": {"acme": {"at": "2026-11-21T10:00:00Z", "members": []}}}',
                    '{"projects": {"acme": {"at": "2026-11-21T10:00:00Z", "members": {"Bad Name; x": ["STALE"], "ok": "STALE", "x": ["WORSE"]}}}}'):
            with open(path, "w") as f:
                f.write(doc)
            self.assertEqual(self.tail()[1], [], doc)
        os.remove(path)
        os.mkdir(path)                                           # a directory where the file is: unreadable, not an error
        self.assertEqual(self.tail()[1], [])


class LeadTailFile(unittest.TestCase):
    """The stored reading is data: a thing that is not a regular file of a size qargi writes is no reading, and is not waited for."""

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="tailfile.")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.path = os.path.join(self.t, "agent-states.json")

    def card_fast(self):
        """The card is made in a process of its own, as the hook makes it, under a timeout: a read that waits on the file (a pipe) or fills memory (a link to a device)
        does not come back, and the card is the one without the tail."""
        r = run(PY + [os.path.join(LIB, "rolecard.py"), "card", "lead", "--project", "acme"], env=dict(os.environ, QARGI_STATE=self.t), timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("Members STALE or DRIFT", r.stdout)
        self.assertEqual(r.stdout, RC.card("lead")["card"] + "\n", "the card without the tail")
        self.assertIsNone(RC.stale_members("acme", self.t))

    def test_a_link_to_a_device_is_no_reading(self):
        os.symlink("/dev/zero", self.path)
        self.card_fast()

    def test_a_link_to_a_real_reading_is_no_reading_either(self):
        write_states(os.path.join(self.t, "elsewhere"), "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"]})
        os.symlink(os.path.join(self.t, "elsewhere", "agent-states.json"), self.path)
        self.card_fast()

    def test_a_pipe_is_no_reading_and_is_not_waited_for(self):
        os.mkfifo(self.path)
        self.card_fast()

    def test_a_file_longer_than_the_room_is_no_reading(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"schema": 1, "projects": {"acme": {"at": "2026-11-21T10:00:00Z", "members": {"forge": ["STALE"], "pad": ["x" * RC.READ_MAX]}}}}, f)
        self.assertGreater(os.path.getsize(self.path), RC.READ_MAX)
        self.card_fast()

    def test_a_large_sparse_file_is_no_reading_and_is_not_read(self):
        with open(self.path, "wb") as f:
            f.truncate(62 * 1024 * 1024)
        self.card_fast()

    def test_a_reading_that_fits_is_read(self):
        write_states(self.t, "acme", "2026-11-21T10:00:00Z", {"forge": ["STALE"]})
        self.assertLess(os.path.getsize(self.path), RC.READ_MAX)
        self.assertEqual(RC.stale_members("acme", self.t), ("2026-11-21T10:00:00Z", {"forge": ["STALE"]}))

    def test_a_file_that_is_not_utf_8_is_no_reading(self):
        with open(self.path, "wb") as f:
            f.write(b"\xff\xfe{")
        self.assertIsNone(RC.stale_members("acme", self.t))


class Cli(unittest.TestCase):
    def test_the_card_and_its_json(self):
        r = run(PY + [os.path.join(LIB, "rolecard.py"), "card", "review", "--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = json.loads(r.stdout)
        self.assertEqual(sorted(doc), ["card", "chars", "class", "members_stale", "project", "role", "run", "words"])
        self.assertEqual(doc["card"], RC.card("review")["card"])
        plain = run(PY + [os.path.join(LIB, "rolecard.py"), "card", "review"])
        self.assertEqual(plain.stdout, doc["card"] + "\n")

    def test_a_role_of_the_owner_gets_the_card_of_its_class(self):
        d = os.path.join(os.environ["QARGI_CONF"], "roles", "auditor")
        os.makedirs(d)
        with open(os.path.join(d, "role.json"), "w") as f:
            json.dump({"class": "read-only", "description": "x"}, f)
        with open(os.path.join(d, "ROLE.md"), "w") as f:
            f.write("# Role: auditor\n")
        self.addCleanup(shutil.rmtree, d, True)
        self.assertEqual(RC.card("auditor")["card"], RC.card("review")["card"])
        self.assertEqual(json.loads(run(PY + [os.path.join(LIB, "rolecard.py"), "card", "auditor", "--json"]).stdout)["class"], "read-only")

    def test_refusals_and_usage(self):
        for args, code, words in ((["card", "nobody"], 1, "no role named nobody"), (["card"], 2, "usage:"), ([], 2, "usage:"), (["card", "build", "--nope"], 2, "unknown option"),
                                  (["card", "build", "--project"], 2, "needs a value"), (["card", "build", "extra"], 2, "unexpected argument"),
                                  (["card", "build", "--run", "/nonexistent-run-dir"], 1, "is not a run directory"), (["list"], 2, "usage:")):
            r = run(PY + [os.path.join(LIB, "rolecard.py")] + args)
            self.assertEqual((r.returncode, r.stdout), (code, ""), args)
            self.assertIn(words, r.stderr, args)



class Fixture(unittest.TestCase):
    """A repository and a project that `qargi local prepare` and `qargi agent` work on, in the scratch home."""

    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="cardfix.")
        self.addCleanup(shutil.rmtree, self.t, True)
        self.conf, self.state = os.path.join(self.t, "conf"), os.path.join(self.t, "state")
        self.env = dict(os.environ, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_RUN_TMP=self.t)
        self.repo = os.path.join(self.t, "fixrepo")
        git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.net"]
        os.makedirs(os.path.join(self.repo, "tests"))
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        with open(os.path.join(self.repo, "tests", "check.sh"), "w") as f:
            f.write("#!/bin/sh\nexit 0\n")
        os.chmod(os.path.join(self.repo, "tests", "check.sh"), 0o755)
        subprocess.run(git + ["-C", self.repo, "add", "-A"], check=True)
        subprocess.run(git + ["-C", self.repo, "commit", "-q", "-m", "one"], check=True)
        os.makedirs(os.path.join(self.conf, "projects"))
        with open(os.path.join(self.conf, "projects", "fixproj.json"), "w") as f:
            json.dump({"schema": 1, "project": "fixproj", "repo": {"url": "https://github.com/example/fixproj", "path": self.repo, "long_lived": ["main"]},
                       "roles": {"build": {"base": "main", "push": {"mode": "none"}}}, "models": {"provider": {"local": "claude-code", "cloud": "claude-platform"}},
                       "memory": {}, "budget_cents": 500}, f)
        with open(os.path.join(self.t, "task.txt"), "w") as f:
            f.write("Add the flag --quiet to the tool.\n")

    def qargi(self, *args, **kw):
        return run([BIN] + list(args), env=kw.pop("env", self.env), **kw)


class Prepare(Fixture):
    def prepare(self, role, slug, *scope):
        args = ["local", "prepare", "--repo", self.repo, "--base", "main", "--scratch", self.t, "--slug", slug, "--role", role, "--task-file", os.path.join(self.t, "task.txt"),
                "--done", "bash tests/check.sh"]
        for s in scope:
            args += ["--scope", s]
        r = self.qargi(*args)
        self.assertEqual(r.returncode, 0, r.stderr)
        run_dir = re.search(r"(?m)^RUN=(.*)$", r.stdout).group(1)
        with open(os.path.join(run_dir, "task.md"), encoding="utf-8") as f:
            return run_dir, f.read()

    def test_the_task_block_carries_the_card_of_the_role_made_with_the_runs_paths_after_the_path_lines(self):
        for role in ("build", "review", "test", "write"):
            run_dir, text = self.prepare(role, "s" + role, "lib/", "docs/guide.md")
            card = run(PY + [os.path.join(LIB, "rolecard.py"), "card", role, "--run", run_dir], env=self.env)
            self.assertEqual(card.returncode, 0, card.stderr)
            head, _, tail = text.partition("\nCARD:\n")
            self.assertEqual(tail, card.stdout, "%s: the card is the last block, and the whole of it" % role)
            self.assertRegex(head, r"CONTRACT: [^\n]+/contract\n$", "the card follows the path lines")
            self.assertEqual(len(re.findall(r"(?m)^CARD:$", text)), 1)
            self.assertNotIn("\n\n", tail.rstrip("\n"), "no blank line in the card: a block that follows it is a block of its own")
            self.assertEqual(SCOPE_LINE.search(text).group(1), "lib/, docs/guide.md", "the card adds no SCOPE line: review check reads the first one")
            self.assertEqual(len([l for l in text.split("\n") if l.startswith("DONE: ")]), 1)

    def test_a_read_only_card_names_the_real_paths_and_the_run(self):
        run_dir, text = self.prepare("review", "sread")
        with open(os.path.join(run_dir, "tmpdir")) as f:
            tmp = f.read().strip()
        card = text.partition("\nCARD:\n")[2]
        for need in ("qargi local report %s < FILE" % run_dir, "git -C %s clone %s x" % (tmp, os.path.join(run_dir, "clone")), "cp -a %s %s/x" % (os.path.join(run_dir, "clone"), tmp),
                     "git -C %s/x am %s/NAME.patch" % (tmp, os.path.join(run_dir, "out"))):
            self.assertIn(need, card)

    def test_the_submodule_line_is_written_with_the_block_not_appended_after_the_card(self):
        with open(os.path.join(LIB, "local.sh"), encoding="utf-8") as f:
            src = f.read()
        self.assertNotRegex(src, r"SUBMODULES: %s[^\n]*>> ")
        self.assertRegex(src, r"(?s)taskblock_write\(\) \{.*SUBMODULES: .*CARD:")



class AgentStates(Fixture):
    def setUp(self):
        super().setUp()
        self.agents = os.path.join(self.repo, ".claude", "agents")
        self.states = os.path.join(self.state, "agent-states.json")

    def stored(self):
        with open(self.states, encoding="utf-8") as f:
            return json.load(f)

    def test_agent_list_stores_the_states_the_lead_card_reads(self):
        r = self.qargi("agent", "add", "forge", "--project", "fixproj", "--roles", "build,test")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(os.path.exists(self.states), "nothing is stored before a list")
        self.assertEqual(self.qargi("agent", "list", "--project", "fixproj").returncode, 0)
        doc = self.stored()
        self.assertEqual(doc["schema"], 1)
        self.assertRegex(doc["projects"]["fixproj"]["at"], r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z$")
        self.assertEqual(doc["projects"]["fixproj"]["members"], {"forge": []})
        self.assertEqual(oct(os.stat(self.states).st_mode & 0o777), "0o600")
        self.assertIsNone(RC.stale_members("fixproj", self.state), "a current member is no line")
        with open(os.path.join(self.agents, "forge.md"), "a") as f:                 # edited by hand: DRIFT
            f.write("a hand edit\n")
        listing = self.qargi("agent", "list", "--project", "fixproj")
        self.assertIn("DRIFT", listing.stdout)
        self.assertEqual(self.stored()["projects"]["fixproj"]["members"], {"forge": ["DRIFT"]})
        at, members = RC.stale_members("fixproj", self.state)
        self.assertEqual(members, {"forge": ["DRIFT"]})
        text = RC.card("lead", project="fixproj", state=self.state)["card"]
        self.assertIn("Members STALE or DRIFT as of %s: forge (DRIFT)" % at, text)
        self.assertEqual(self.qargi("agent", "refresh", "forge", "--project", "fixproj").returncode, 0)
        self.qargi("agent", "list", "--project", "fixproj")
        self.assertEqual(self.stored()["projects"]["fixproj"]["members"], {"forge": []})
        self.assertIsNone(RC.stale_members("fixproj", self.state))

    def test_a_list_of_one_project_keeps_the_reading_of_the_others(self):
        self.qargi("agent", "add", "forge", "--project", "fixproj")
        write_states(self.state, "elsewhere", "2026-01-01T00:00:00Z", {"old": ["STALE"]})
        with open(self.states, encoding="utf-8") as f:
            doc = json.load(f)
        doc["projects"]["fixproj"] = {"at": "2026-01-01T00:00:00Z", "members": {"gone": ["STALE"]}}
        with open(self.states, "w", encoding="utf-8") as f:
            json.dump(doc, f)
        self.qargi("agent", "list", "--project", "fixproj")
        doc = self.stored()
        self.assertEqual(doc["projects"]["elsewhere"]["members"], {"old": ["STALE"]})
        self.assertEqual(doc["projects"]["fixproj"]["members"], {"forge": []})
        self.qargi("agent", "list")                                                  # every project: the reading is replaced, no project of the file survives that has no member
        self.assertEqual(sorted(self.stored()["projects"]), ["fixproj"])

    def test_a_list_that_cannot_store_still_lists(self):
        self.qargi("agent", "add", "forge", "--project", "fixproj")
        os.mkdir(self.states)                                                        # a directory where the file goes
        r = self.qargi("agent", "list", "--project", "fixproj")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("forge", r.stdout)


class Hook(Fixture):
    """lib/hook.sh session-start puts the lead card into the context: 1600 characters at most, two seconds, left out when it fails."""

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.conf, "projects", "fixproj.json"), "w") as f:
            json.dump({"project": "fixproj", "repo": {"path": self.repo}, "memory": {}}, f)
        self.bin = os.path.join(self.t, "shim")
        os.makedirs(self.bin)
        self.real = shutil.which("python3")

    def hook(self, shim=None):
        env = dict(self.env, QARGI_HOOK_MARSHAL_SECS="1")
        if shim:
            with open(os.path.join(self.bin, "python3"), "w") as f:
                f.write("#!/bin/sh\ncase \"$*\" in *rolecard.py*) %s;; esac\nexec '%s' -B \"$@\"\n" % (shim, self.real))
            os.chmod(os.path.join(self.bin, "python3"), 0o755)
            env["PATH"] = self.bin + os.pathsep + env["PATH"]
        r = subprocess.run(["bash", os.path.join(LIB, "hook.sh"), "session-start", "--project", "fixproj"], input='{"session_id":"abc"}', stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def context(self, doc):
        return (doc.get("hookSpecificOutput") or {}).get("additionalContext", "")

    def test_the_context_holds_the_lead_card(self):
        doc = self.hook()
        ctx = self.context(doc)
        self.assertIn(RC.card("lead")["card"], ctx)
        self.assertLessEqual(len(RC.card("lead")["card"]), RC.LEAD_CHARS)
        self.assertEqual(doc["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertNotIn("Members STALE or DRIFT", ctx, "no stored reading, no line")

    def test_the_tail_comes_from_the_stored_states(self):
        write_states(self.state, "fixproj", "2026-11-21T10:00:00Z", {"forge": ["STALE"]})
        self.assertIn("- Members STALE or DRIFT as of 2026-11-21T10:00:00Z: forge (STALE);", self.context(self.hook()))
        os.remove(os.path.join(self.state, "agent-states.json"))
        self.assertNotIn("Members STALE or DRIFT", self.context(self.hook()))

    def test_it_is_left_out_when_it_fails(self):
        doc = self.hook("exit 1")
        self.assertNotIn("Lead card", self.context(doc))
        self.assertIn("systemMessage", doc)

    def test_it_is_left_out_when_it_takes_over_two_seconds(self):
        doc = self.hook("exec sleep 30")
        self.assertNotIn("Lead card", self.context(doc))
        self.assertIn("systemMessage", doc)

    def test_a_card_longer_than_the_room_is_not_loaded(self):
        doc = self.hook("printf 'x%.0s' $(seq 1 1700); exit 0")
        self.assertNotIn("xxxxxxxx", self.context(doc))

    def test_a_card_with_control_characters_is_not_loaded_as_it_is(self):
        doc = self.hook("printf 'Lead card\\001\\033[31m red\\n'; exit 0")
        ctx = self.context(doc)
        self.assertNotIn("\x01", ctx)
        self.assertNotIn("\x1b", ctx)

if __name__ == "__main__":
    unittest.main()
