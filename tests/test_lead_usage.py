#!/usr/bin/env python3
"""qargi lead usage | compact-check and the advice line (lib/lead_usage.py), from fixture transcripts, run registries and git repositories.
Nothing reads the real session files: HOME is a fresh directory and the transcripts are written under it, where the runtime's definition
(resources.transcripts of lib/providers/claude-code.json) says they live. Offline. Run: python3 tests/test_lead_usage.py"""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import json, os, re, subprocess, sys, tempfile, time, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(ROOT, "bin", "qargi")
LEADPY = os.path.join(ROOT, "lib", "lead_usage.py")
GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.net", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.net"}


NOTE = " (window assumed 200,000; set lead.context_window)"      # what every percentage of the runtime's guessed window carries


def turn(inp=3, read=0, create=0, model="model-a", side=False, kind="assistant"):
    return json.dumps({"type": kind, "isSidechain": side, "message": {"role": kind, "model": model,
                       "usage": {"input_tokens": inp, "cache_read_input_tokens": read, "cache_creation_input_tokens": create, "output_tokens": 77}}})


class Base(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.mkdtemp(prefix="lead.")
        self.home, self.conf, self.state = (os.path.join(self.t, d) for d in ("home", "conf", "state"))
        self.repo = os.path.realpath(os.path.join(self.t, "app"))
        for d in (self.home, os.path.join(self.conf, "projects"), self.state, self.repo):
            os.makedirs(d)
        self.git("init", "-q", "-b", "master")
        self.git("commit", "-q", "--allow-empty", "-m", "one")
        self.git("branch", "develop")
        self.answers = {"schema": 1, "project": "app", "methodology": "gitflow", "repo": {"url": "https://example.net/acme/app", "path": self.repo},
                        "models": {"provider": {"local": "claude-code", "cloud": "claude-platform"}}, "test_command": "true"}
        self.write_answers()
        key = re.sub(r"[^A-Za-z0-9]", "-", self.repo)
        self.tdir = os.path.join(self.home, ".claude", "projects", key)
        os.makedirs(self.tdir)

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.t])

    def write_answers(self):
        with open(os.path.join(self.conf, "projects", "app.json"), "w") as f:
            json.dump(self.answers, f)

    def git(self, *a, cwd=None):
        r = subprocess.run(["git", "-C", cwd or self.repo, *a], capture_output=True, text=True, env=dict(os.environ, **GIT_ENV))
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip()

    def env(self, **extra):
        e = dict(os.environ, HOME=self.home, QARGI_CONF=self.conf, QARGI_STATE=self.state, QARGI_PROJECT="app", **GIT_ENV)
        e.update(extra)
        for k in [k for k, v in e.items() if v is None]:
            del e[k]
        return e

    def run_cli(self, *args, cwd=None, **env):
        r = subprocess.run([BIN, *args], capture_output=True, text=True, cwd=cwd or self.repo, env=self.env(**env))
        return r.returncode, r.stdout, r.stderr

    def transcript(self, name, lines, mtime=None):
        p = os.path.join(self.tdir, name + ".jsonl")
        with open(p, "w") as f:
            f.write("\n".join(lines) + "\n")
        if mtime:
            os.utime(p, (mtime, mtime))
        return p

    def pct(self, tokens):
        """A transcript whose last turn holds exactly that many tokens (window 200000)."""
        return self.transcript("s1", [turn(1, tokens - 1, 0)])


class Usage(Base):
    def test_the_last_assistant_turn_is_the_context_in_use(self):
        self.transcript("s1", [turn(5, 1000, 100), '{"type":"user"}', turn(3, 90000, 2000), '{"type":"user","message":{"role":"user"}}'])
        rc, out, _ = self.run_cli("lead", "usage")
        self.assertEqual(rc, 0)
        self.assertIn("context: 92,003 of 200,000 tokens in use (46%)", out)
        self.assertIn("model: model-a", out)
        self.assertIn("s1.jsonl", out)

    def test_json_has_the_figures(self):
        self.transcript("s1", [turn(3, 49997, 0)])
        rc, out, _ = self.run_cli("lead", "usage", "--json")
        d = json.loads(out)
        self.assertEqual((rc, d["known"], d["tokens"], d["window"], d["percent"], d["session"]), (0, True, 50000, 200000, 25.0, "s1"))
        self.assertEqual(d["window_source"], "assumed")
        self.assertGreater(d["bytes"], 0)

    def test_sidechain_and_empty_turns_do_not_count(self):
        self.transcript("s1", [turn(2, 40000, 0), turn(2, 150000, 0, side=True), turn(0, 0, 0, model="<synthetic>"), '{"type":"user"}'])
        self.assertIn("40,002 of 200,000", self.run_cli("lead", "usage")[1])

    def test_a_malformed_line_is_skipped(self):
        self.transcript("s1", [turn(2, 40000, 0), "{not json", "[1,2]", "null", ""])
        self.assertIn("40,002 of 200,000", self.run_cli("lead", "usage")[1])

    def test_a_long_transcript_is_read_from_its_end(self):
        filler = '{"type":"user","message":{"content":"%s"}}' % ("x" * 4000)
        lines = [turn(1, 1000, 0)] + [filler] * 600 + [turn(1, 120000, 0)] + [filler] * 400       # about 4 MB: the turn is several blocks from the end
        self.transcript("s1", lines)
        rc, out, _ = self.run_cli("lead", "usage")
        self.assertIn("120,001 of 200,000", out)

    def test_the_session_id_names_the_transcript(self):
        self.transcript("old", [turn(1, 1000, 0)], mtime=1000)
        self.transcript("mine", [turn(1, 20000, 0)], mtime=2000)
        self.transcript("newest", [turn(1, 90000, 0)], mtime=3000)
        self.assertIn("90,001", self.run_cli("lead", "usage")[1])                                    # no session: the newest of the directory
        self.assertIn("20,001", self.run_cli("lead", "usage", QARGI_LEAD="mine")[1])                 # QARGI_LEAD is the session id
        self.assertIn("1,001", self.run_cli("lead", "usage", "--session", "old", QARGI_LEAD="mine")[1])
        rc, out, _ = self.run_cli("lead", "usage", "--session", "nosuch")
        self.assertEqual(rc, 0)
        self.assertIn("context: unknown (no transcript of session nosuch", out)
        rc, out, _ = self.run_cli("lead", "usage", "--session", "../x")
        self.assertEqual(rc, 0)
        self.assertIn("unknown (../x is not a session id)", out)

    def test_a_transcript_file_can_be_named(self):
        p = self.transcript("elsewhere", [turn(1, 30000, 0)])
        os.rename(p, os.path.join(self.t, "t.jsonl"))
        rc, out, _ = self.run_cli("lead", "usage", "--transcript", os.path.join(self.t, "t.jsonl"))
        self.assertIn("30,001 of 200,000", out)
        rc, out, _ = self.run_cli("lead", "usage", "--transcript", os.path.join(self.t, "none.jsonl"))
        self.assertEqual(rc, 0)
        self.assertIn("unknown (no such file", out)

    def test_it_finds_the_transcript_from_a_subdirectory_of_the_checkout(self):
        self.transcript("s1", [turn(1, 70000, 0)])
        os.makedirs(os.path.join(self.repo, "sub", "dir"))
        self.assertIn("70,001", self.run_cli("lead", "usage", cwd=os.path.join(self.repo, "sub", "dir"))[1])

    def test_the_window_is_the_answer_lead_context_window(self):
        self.transcript("s1", [turn(1, 99999, 0)])
        self.answers["lead"] = {"context_window": 1000000}
        self.write_answers()
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["percent"], d["window_source"]), (1000000, 10.0, "answer"))
        self.answers["lead"] = {"context_window": "big"}                                              # not a number: the runtime's window
        self.write_answers()
        self.assertEqual(json.loads(self.run_cli("lead", "usage", "--json")[1])["window"], 200000)

    def test_the_window_follows_the_model_of_the_last_turn(self):
        self.transcript("s1", [turn(1, 99999, 0, model="model-a"), turn(1, 192117, 0, model="model-b[1m]")])
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["window_source"], d["percent"], d["model"]), (1000000, "model", 19.2, "model-b[1m]"))
        self.transcript("s1", [turn(1, 192117, 0, model="model-b-1m")])
        self.assertEqual(json.loads(self.run_cli("lead", "usage", "--json")[1])["window"], 1000000)
        self.transcript("s1", [turn(1, 192117, 0, model="model-b[1m]"), turn(1, 99999, 0, model="model-a")])      # the last turn's model, not an earlier one
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["window_source"]), (200000, "assumed"))

    def test_an_unknown_model_gets_the_runtimes_window_marked_assumed(self):
        self.transcript("s1", [turn(1, 99999, 0, model="model-a")])
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["window_source"], d["percent"]), (200000, "assumed", 50.0))
        for k in ("known", "tokens", "window", "percent", "model", "session", "transcript", "bytes", "why"):      # the keys that were there stay
            self.assertIn(k, d)

    def test_a_guessed_window_says_so_and_a_known_one_does_not(self):
        self.transcript("s1", [turn(1, 192117, 0, model="model-a")])
        out = self.run_cli("lead", "usage")[1]
        self.assertIn("context: 192,118 of 200,000 tokens in use (96.1%)" + NOTE + "\n", out)
        self.transcript("s1", [turn(1, 192117, 0, model="model-b[1m]")])
        out = self.run_cli("lead", "usage")[1]
        self.assertIn("context: 192,118 of 1,000,000 tokens in use (19.2%)\n", out)
        self.assertNotIn("assumed", out)
        self.transcript("s1", [turn(1, 192117, 0, model="model-a")])
        self.answers["lead"] = {"context_window": 200000}                                                # the answer, even when it equals the guess
        self.write_answers()
        self.assertNotIn("assumed", self.run_cli("lead", "usage")[1])

    def test_tokens_beyond_an_assumed_window_say_the_window_is_larger_and_show_no_percentage(self):
        self.transcript("s1", [turn(1, 249999, 0, model="model-a")])
        rc, out, _ = self.run_cli("lead", "usage")
        self.assertEqual(rc, 0)
        self.assertIn("context: 250,000 tokens in use; tokens exceed the assumed window 200,000; set lead.context_window\n", out)
        self.assertNotIn("%", out)
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["window_source"], d["percent"], d["window_exceeded"]), (200000, "assumed", 125.0, True))
        self.transcript("s1", [turn(1, 199999, 0, model="model-a")])                                   # exactly the window: not beyond it
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertIs(d["window_exceeded"], False)
        self.assertIn("(100%)" + NOTE, self.run_cli("lead", "usage")[1])
        self.transcript("s1", [turn(1, 249999, 0, model="model-b[1m]")])                               # a window from the model: never flagged
        self.assertIs(json.loads(self.run_cli("lead", "usage", "--json")[1])["window_exceeded"], False)
        self.transcript("s1", [turn(1, 249999, 0, model="model-a")])
        self.answers["lead"] = {"context_window": 200000}                                              # the answer: the owner's number, not flagged
        self.write_answers()
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertIs(d["window_exceeded"], False)
        self.assertIn("(125%)", self.run_cli("lead", "usage")[1])

    def test_the_answer_wins_over_the_model(self):
        self.transcript("s1", [turn(1, 99999, 0, model="model-b[1m]")])
        self.answers["lead"] = {"context_window": 400000}
        self.write_answers()
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["window"], d["window_source"], d["percent"]), (400000, "answer", 25.0))

    def test_everything_that_cannot_be_read_is_unknown_with_exit_0(self):
        rc, out, _ = self.run_cli("lead", "usage")                                                    # an empty transcripts directory
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"^context: unknown \(no transcript under ")
        self.transcript("s1", ['{"type":"user"}'])
        self.assertIn("unknown (no turn with a token count", self.run_cli("lead", "usage")[1])
        os.chmod(os.path.join(self.tdir, "s1.jsonl"), 0)
        if os.geteuid() != 0:
            rc, out, _ = self.run_cli("lead", "usage")
            self.assertEqual(rc, 0)
            self.assertIn("unknown (cannot read the transcript", out)
        rc, out, _ = self.run_cli("lead", "usage", "--project", "nosuch")
        self.assertEqual(rc, 0)
        self.assertIn("unknown (no stored answers for project nosuch)", out)
        self.answers["models"] = {}
        self.write_answers()
        rc, out, _ = self.run_cli("lead", "usage")
        self.assertEqual(rc, 0)
        self.assertIn("context: unknown (", out)
        d = json.loads(self.run_cli("lead", "usage", "--json")[1])
        self.assertEqual((d["known"], d["tokens"], d["percent"]), (False, None, None))

    def test_a_runtime_with_no_transcripts_is_unknown(self):
        self.answers["models"] = {"provider": {"local": "claude-platform", "cloud": "claude-platform"}}
        self.write_answers()
        rc, out, _ = self.run_cli("lead", "usage")
        self.assertEqual(rc, 0)
        self.assertIn("context: unknown (", out)

    def test_usage_refuses_unknown_options(self):
        self.assertEqual(self.run_cli("lead", "usage", "--advise")[0], 2)
        self.assertEqual(self.run_cli("lead", "compact-check", "--session", "x")[0], 2)
        self.assertEqual(self.run_cli("lead", "usage", "--bogus")[0], 2)

    def test_it_writes_nothing(self):
        self.transcript("s1", [turn(1, 1000, 0)])
        self.run_cli("lead", "usage")                                                                     # the first call makes the state files every verb makes
        before = sorted(os.listdir(self.state))
        self.run_cli("lead", "usage")
        self.run_cli("lead", "compact-check", "--advise")
        self.assertEqual(sorted(os.listdir(self.state)), before)


class Check(Base):
    def registry(self, *runs):
        with open(os.path.join(self.state, "local-runs.jsonl"), "a") as f:
            for r in runs:
                f.write(json.dumps(r) + "\n")

    def run_dir(self, name, *files, base="feature/lc", repo=None, slug=None, cls=None):
        d = os.path.join(self.t, name)
        os.makedirs(d)
        for fn, text in files:
            with open(os.path.join(d, fn), "w") as f:
                f.write(text)
        rec = {"run": d, "slug": slug or name, "ability": "build", "base": base, "started": "1", "repo": repo or self.repo}
        if cls:
            rec["class"] = cls                                                                            # the class prepare records in the lead's registry
        self.registry(rec)
        return d

    def check(self, *args, **env):
        return self.run_cli("lead", "compact-check", *args, **env)

    def test_nothing_open_is_safe_and_prints_the_restart_block(self):
        rc, out, _ = self.check()
        self.assertEqual(rc, 0)
        self.assertIn("compact is safe now", out)
        self.assertIn("After the compact, resume from stored state, not from memory:", out)
        self.assertIn("no handoff note is recorded", out)
        self.assertIn("qargi marshal status --all --brief", out)
        self.assertIn("no feature branch is open", out)
        self.assertIn("open runs: none", out)

    def test_the_restart_block_names_the_features_the_runs_and_the_note(self):
        self.git("branch", "feature/lc", "develop")
        d = self.run_dir("r1", ("verified", "x"))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("qargi feature status lc", out)
        self.assertIn("build r1 [verified, not applied]", out)
        self.assertIn(d, out)

    def test_a_run_prepared_and_not_verified_is_not_safe(self):
        d = self.run_dir("r1")
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("do not compact now:", out)
        self.assertIn("a local run is prepared and not verified: " + d, out)

    def test_a_run_verified_and_not_applied_is_not_safe(self):
        d = self.run_dir("r1", ("verified", "refs"))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("a local run is verified and not applied: " + d, out)

    def test_an_applied_run_matters_until_its_work_is_merged(self):
        self.git("checkout", "-q", "-b", "agent/x")
        self.git("commit", "-q", "--allow-empty", "-m", "work")
        tip = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "master")
        d = self.run_dir("r1", ("verified", "refs"), ("applied", "agent/x %s\n" % tip))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("a local run is applied and not merged: " + d, out)
        self.git("branch", "feature/lc", tip)                                                          # the work is on a feature branch now
        rc, out, _ = self.check()
        self.assertEqual(rc, 0, out)
        with open(os.path.join(d, "applied"), "w") as f:                                                 # a word that is not a commit is not merged
            f.write("agent/x not-a-sha\n")
        self.assertEqual(self.check()[0], 1)

    def journal_rewrite(self, old, new, repo=None, verb="ref:rewrite"):
        with open(os.path.join(self.state, "ref-journal.jsonl"), "a") as f:
            f.write(json.dumps({"at": "x", "epoch": 1, "verb": verb, "project": "app", "repo": repo or self.repo, "ref": "refs/heads/agent/x", "old": old, "new": new, "by": "t"}) + "\n")

    def test_a_rewritten_and_merged_run_is_settled_here_as_in_local_list_and_clean(self):
        """merged is one test (lib/merged.py) for local list, local clean and compact-check: a tip the lead rewrote (qargi ref record --rewrite,
        journaled as ref:rewrite) counts by the commit it was rewritten to, and the run directory may sit in any (old) scratch directory."""
        self.git("checkout", "-q", "-b", "agent/x")
        self.git("commit", "-q", "--allow-empty", "-m", "work")
        old = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "--amend", "-m", "work, reworded")
        new = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "master")
        self.git("branch", "-D", "agent/x")                                                              # only the rewritten commit is left, on the feature branch
        self.git("branch", "feature/lc", new)
        old_scratch = os.path.join(self.t, "scratch-from-last-month")
        os.makedirs(old_scratch)
        d = os.path.join(old_scratch, "qargi.old001")
        os.makedirs(d)
        for fn, text in (("applied", "agent/x %s\n" % old), ("refs.before", ""), ("ability", "build\n")):                # what local list needs of a run directory
            with open(os.path.join(d, fn), "w") as f:
                f.write(text)
        self.registry({"run": d, "slug": "old", "ability": "build", "base": "feature/lc", "started": "1", "repo": self.repo})
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)                                                                          # not journaled: the old commit is nowhere, so the run is not merged
        self.assertIn("a local run is applied and not merged: " + d, out)
        self.journal_rewrite(old, new)
        rc, out, _ = self.check()
        self.assertEqual(rc, 0, out)                                                                     # journaled: merged, wherever its directory is
        self.assertIn("open runs: none", out)
        rc, out, _ = self.run_cli("feature", "finish", "lc")
        self.assertNotIn("open run", out)
        rc, out, _ = self.run_cli("local", "list")
        self.assertRegex(out, r"build +old +\S+ +yes +yes +" + re.escape(d))                                    # the same verdict in local list
        os.remove(os.path.join(self.state, "ref-journal.jsonl"))
        self.journal_rewrite(old, new, repo=os.path.join(self.t, "elsewhere"))                           # a rewrite of another repository is not this run's
        self.assertEqual(self.check()[0], 1)

    def test_a_rewrite_chain_is_followed_and_only_a_rewrite_counts(self):
        self.git("checkout", "-q", "-b", "agent/x")
        self.git("commit", "-q", "--allow-empty", "-m", "work")
        a = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "--amend", "-m", "two")
        b = self.git("rev-parse", "HEAD")
        self.git("commit", "-q", "--allow-empty", "--amend", "-m", "three")
        c = self.git("rev-parse", "HEAD")
        self.git("checkout", "-q", "master")
        self.git("branch", "-D", "agent/x")
        self.git("branch", "feature/lc", c)
        d = self.run_dir("r1", ("applied", "agent/x %s\n" % a))
        self.journal_rewrite(a, b)
        self.assertEqual(self.check()[0], 1)                                                             # a -> b: b is on no branch yet
        self.journal_rewrite(b, c)
        self.assertEqual(self.check()[0], 0)                                                             # a -> b -> c: c is on feature/lc
        os.remove(os.path.join(self.state, "ref-journal.jsonl"))
        self.journal_rewrite(a, c, verb="ref:note")                                                      # another verb is no rewrite
        self.assertEqual(self.check()[0], 1)
        self.assertTrue(os.path.isdir(d))

    def test_every_open_run_names_the_command_that_closes_it(self):
        """open-runs (what feature finish lists) carries the exact closing command: a read-only run with its report closes with a plain clean, a run of
        work by the next step it waits for."""
        ro = self.run_dir("ro", ("class", "read-only\n"), slug="advice")
        os.makedirs(os.path.join(ro, "out"))
        with open(os.path.join(ro, "out", "report.md"), "w") as f:
            f.write("# report\n")
        ro2 = self.run_dir("ro2", ("class", "read-only\n"), slug="waiting")
        wr = self.run_dir("wr", ("class", "write\n"), ("verified", "refs"), slug="work")
        pr = self.run_dir("pr", slug="fresh")
        rc, out, _ = self.run_cli("lead", "compact-check")
        self.assertEqual(rc, 1)
        self.assertIn("a read-only local run is open: %s (build advice on feature/lc, prepared, not verified); read its report, then close it: qargi local clean %s\n" % (ro, ro), out)
        self.assertIn("close it: qargi local clean %s (once the member has written OUT/report.md" % ro2, out)
        self.assertIn("a local run is verified and not applied: " + wr, out)
        rows = {}
        for ln in subprocess.run([sys.executable, "-I", LEADPY, "open-runs", "--state", self.state, "--conf", self.conf, "--project", "app", "--feature", "lc"],
                                 capture_output=True, text=True).stdout.splitlines():
            f = ln.split("\t")
            self.assertEqual(len(f), 5, ln)
            rows[f[1]] = f
        self.assertEqual(rows["advice"][4], "qargi local clean " + ro)
        self.assertTrue(rows["waiting"][4].startswith("qargi local clean %s (once the member" % ro2))
        self.assertTrue(rows["work"][4].startswith("qargi local close %s --applied-by-am" % wr))
        self.assertIn("qargi review apply %s, qargi feature merge lc agent/work, qargi local clean %s" % (wr, wr), rows["work"][4])
        self.assertTrue(rows["fresh"][4].startswith("qargi local verify %s" % pr))

    def test_the_class_is_the_registrys_and_a_report_is_a_regular_file_named_report_md(self):
        """The class file of a run directory is a member's: the registry's class wins; a record with none falls back to the file, and a run with neither is a
        run of work. A report is a regular file named report.md or NAME-report.md directly in OUT, as lib.sh out_has_report says."""
        fg = self.run_dir("fg", ("class", "read-only\n"), cls="write", slug="forged")
        old = self.run_dir("old", ("class", "read-only\n"), slug="oldrec")
        none = self.run_dir("none", slug="nothing")
        sym = self.run_dir("sym", cls="read-only", slug="symrep")
        pre = self.run_dir("pre", cls="read-only", slug="prerep")
        for d, make in ((sym, lambda o: os.symlink("/etc/hostname", os.path.join(o, "report.md"))),
                        (pre, lambda o: open(os.path.join(o, "review-report.md"), "w").close())):
            os.makedirs(os.path.join(d, "out"))
            make(os.path.join(d, "out"))
        rc, out, _ = self.run_cli("lead", "compact-check")
        self.assertEqual(rc, 1)
        self.assertNotIn("a read-only local run is open: " + fg, out)          # the registry says write; the member's file does not matter
        self.assertNotIn("a read-only local run is open: " + none, out)        # neither: a run of work
        self.assertIn("a read-only local run is open: " + old, out)            # an older record: the file
        self.assertIn("close it: qargi local clean %s (once the member has written OUT/report.md" % sym, out)   # a link is no report
        self.assertIn("close it: qargi local clean %s\n" % pre, out)           # NAME-report.md is

    def test_runs_of_another_repository_and_cleaned_runs_are_not_counted(self):
        self.run_dir("other", repo=os.path.join(self.t, "elsewhere"))
        gone = self.run_dir("gone")
        subprocess.run(["rm", "-rf", gone])
        self.assertEqual(self.check()[0], 0)
        self.registry({"run": os.path.join(self.t, "nourl"), "url": "https://example.net/acme/app"})
        os.makedirs(os.path.join(self.t, "nourl"))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("nourl", out)

    def test_a_merge_waiting_for_its_resolution_is_not_safe(self):
        os.makedirs(os.path.join(self.state, "conflicts", "app-feature-lc-merge-agent_x"))
        os.makedirs(os.path.join(self.state, "conflicts", "other-feature-z"))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("a merge waits to be resolved or applied (app-feature-lc-merge-agent_x", out)
        self.assertNotIn("other-feature-z", out)
        subprocess.run(["rm", "-rf", os.path.join(self.state, "conflicts", "app-feature-lc-merge-agent_x")])
        with open(os.path.join(self.state, "conflicts", "app-feature-lc-merge-agent_x.done"), "w") as f:      # resolved, not yet applied
            f.write("a b c\n")
        self.assertEqual(self.check()[0], 1)

    def test_bookkeeping_is_not_a_merge_that_waits(self):
        """The .master file of a release finish (kept beside a parked worktree, and left by a finish that stopped after writing it) and the records of finish-intent/ are
        bookkeeping, not a merge to resolve: they do not make a compact unsafe. A parked worktree (a directory) and the .done mark of a resolved merge still do."""
        os.makedirs(os.path.join(self.state, "conflicts"))
        os.makedirs(os.path.join(self.state, "finish-intent"))
        with open(os.path.join(self.state, "conflicts", "app-release-0.2.0-into-develop.master"), "w") as f:
            f.write("a b c\n")
        with open(os.path.join(self.state, "finish-intent", "app-release-0.2.0.json"), "w") as f:
            f.write("{}\n")
        os.makedirs(os.path.join(self.state, "finish-intent", "app-release-0.2.0.json.run"))
        rc, out, _ = self.check()
        self.assertEqual((rc, "a merge waits" in out), (0, False), out)
        os.makedirs(os.path.join(self.state, "conflicts", "app-release-0.2.0-into-develop"))                  # the parked worktree of the same merge
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("a merge waits to be resolved or applied (app-release-0.2.0-into-develop under", out)
        self.assertNotIn(".master", out)

    def test_a_whole_suite_run_in_progress_is_not_safe_and_a_dead_pid_is_ignored(self):
        os.makedirs(os.path.join(self.state, "busy"))
        pidf = os.path.join(self.state, "busy", "app.verify.lc.pid")
        proc = subprocess.Popen(["sleep", "30"])
        try:
            with open(pidf, "w") as f:
                f.write("%d\n" % proc.pid)
            rc, out, _ = self.check()
            self.assertEqual(rc, 1)
            self.assertIn("the whole suite is running (verify.lc, pid %d)" % proc.pid, out)
        finally:
            proc.kill()
            proc.wait()
        self.assertEqual(self.check()[0], 0)                                                           # the process is gone: the file is stale
        with open(pidf, "w") as f:
            f.write("not a pid\n")
        self.assertEqual(self.check()[0], 0)

    def test_a_handoff_note_older_than_the_last_merge_is_not_safe(self):
        os.makedirs(os.path.join(self.state, "handoff"))
        note = os.path.join(self.t, "note.md")
        with open(os.path.join(self.state, "handoff", "app.json"), "w") as f:
            json.dump({"epoch": 1000, "at": "x", "file": note, "by": "me", "features": []}, f)
        self.assertEqual(self.check()[0], 0)                                                           # no merge yet
        with open(os.path.join(self.state, "ref-journal.jsonl"), "w") as f:
            for e, verb, proj in ((900, "feature:merge", "app"), (2000, "feature:merge", "other"), (3000, "review:apply", "app"), (4000, "feature:start", "app")):
                f.write(json.dumps({"epoch": e, "verb": verb, "project": proj}) + "\n")
        self.assertEqual(self.check()[0], 0)                                                           # merges before the note, other projects, other verbs
        with open(os.path.join(self.state, "ref-journal.jsonl"), "a") as f:
            f.write(json.dumps({"epoch": 2500, "verb": "feature:merge", "project": "app"}) + "\n")
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("the handoff note (written 1970-01-01 00:16:40Z) is older than the last merge (1970-01-01 00:41:40Z)", out)
        self.assertIn("read the handoff note: " + note, out)                                          # the restart block names the note
        with open(os.path.join(self.state, "handoff", "app.json"), "w") as f:                          # written again after the merge
            json.dump({"epoch": 2600, "file": note}, f)
        self.assertEqual(self.check()[0], 0)

    def test_a_release_in_progress_is_not_safe(self):
        self.git("branch", "release/0.2.0", "develop")
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertIn("a release is in progress (release/0.2.0)", out)
        self.git("branch", "-D", "release/0.2.0")
        self.git("branch", "hotfix/0.1.1", "master")
        self.assertIn("hotfix/0.1.1", self.check()[1])

    def test_every_reason_is_listed(self):
        self.run_dir("r1")
        self.git("branch", "release/0.2.0", "develop")
        os.makedirs(os.path.join(self.state, "conflicts", "app-x"))
        rc, out, _ = self.check()
        self.assertEqual(rc, 1)
        self.assertEqual(out.count("\n  - "), 3, out)

    def test_advise_combines_the_context_with_the_verdict(self):
        for tokens, word in ((50000, "no compact needed (25%, 50k tokens of the context)"), (100000, "compact advised (50%, 100k tokens of the context)"),
                             (140000, "compact strongly advised (70%, 140k tokens of the context)")):
            self.pct(tokens)
            rc, out, _ = self.check("--advise")
            self.assertEqual(rc, 0)
            self.assertIn(word, out)
            self.assertIn("tokens in use", out)
        self.run_dir("r1")                                                                                 # not safe: the advice says so, the exit status is the check's
        rc, out, _ = self.check("--advise")
        self.assertEqual(rc, 1)
        self.assertIn("compact strongly advised (70%, 140k tokens of the context), but not safe yet", out)
        os.remove(os.path.join(self.tdir, "s1.jsonl"))
        rc, out, _ = self.check("--advise")
        self.assertIn("context unknown", out)
        self.assertNotIn("compact advised", out)

    def test_advise_names_an_assumed_window_once_in_text_and_in_the_json_advice(self):
        self.pct(140000)
        rc, out, _ = self.check("--advise")
        self.assertEqual(out.count("window assumed"), 1)
        d = json.loads(self.check("--advise", "--json")[1])
        self.assertEqual(d["usage"]["window_source"], "assumed")
        self.assertIn("compact strongly advised (70%, 140k tokens of the context)" + NOTE, d["advice"])
        self.transcript("s1", [turn(1, 139999, 0, model="model-b[1m]")])                                   # a recognised model: no label, 14% of 1,000,000
        rc, out, _ = self.check("--advise")
        self.assertNotIn("assumed", out)
        self.assertIn("no compact needed (14%, 140k tokens of the context)", out)
        self.assertNotIn("assumed", json.loads(self.check("--advise", "--json")[1])["advice"])

    def test_advice_beyond_an_assumed_window_says_so_without_a_percentage(self):
        self.pct(250000)
        rc, out, _ = self.check("--advise")
        self.assertIn("context window larger than assumed (250k tokens: tokens exceed the assumed window 200,000; set lead.context_window)", out)
        self.assertNotIn("%", out.split("context window larger")[1].split("\n")[0])
        self.assertNotIn("window assumed", out)
        d = json.loads(self.check("--advise", "--json")[1])
        self.assertIs(d["usage"]["window_exceeded"], True)
        self.assertIn("exceed the assumed window 200,000", d["advice"])
        self.assertNotIn("%", d["advice"])

    def test_json_carries_the_reasons_and_the_restart_block(self):
        self.pct(100000)
        self.run_dir("r1")
        rc, out, _ = self.check("--advise", "--json")
        d = json.loads(out)
        self.assertEqual((rc, d["safe"]), (1, False))
        self.assertEqual(len(d["reasons"]), 1)
        self.assertEqual(d["open_runs"][0]["state"], "prepared, not verified")
        self.assertEqual(d["usage"]["tokens"], 100000)
        self.assertIn("compact advised", d["advice"])
        self.assertTrue(d["restart"][0].startswith("After the compact"))

    def test_it_needs_a_project(self):
        rc, _, err = self.run_cli("lead", "compact-check", "--project", "nosuch")
        self.assertEqual(rc, 2)
        self.assertIn("no stored answers for project nosuch", err)


class Advice(Base):
    def advice(self, *args):
        r = subprocess.run([sys.executable, "-I", LEADPY, "advice", "--state", self.state, "--conf", self.conf, "--project", "app", "--cwd", self.repo, *args],
                           capture_output=True, text=True, env=self.env())
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_it_speaks_from_the_threshold_up(self):
        self.pct(78000)                                                                                   # 39%
        self.assertEqual(self.advice(), "")
        self.pct(80000)                                                                                   # 40%
        self.assertEqual(self.advice(), "lead: 40%%, 80k tokens of context%s; compact is safe now: run /compact\n" % NOTE)

    def test_the_token_count_is_beside_the_percentage(self):
        self.transcript("s1", [turn(1, 179999, 0, model="model-b[1m]")])
        self.answers["lead"] = {"compact_advice_pct": 10}
        self.write_answers()
        self.assertEqual(self.advice(), "lead: 18%, 180k tokens of context; compact is safe now: run /compact\n")
        self.answers["lead"] = {"compact_advice_pct": 10, "context_window": 4000000}
        self.write_answers()
        self.transcript("s1", [turn(1, 1199999, 0)])
        self.assertEqual(self.advice(), "lead: 30%, 1.2M tokens of context; compact is safe now: run /compact\n")

    def test_a_known_window_has_no_label_in_the_line(self):
        self.transcript("s1", [turn(1, 499999, 0, model="model-b[1m]")])                                    # 50% of 1,000,000
        self.assertEqual(self.advice(), "lead: 50%, 500k tokens of context; compact is safe now: run /compact\n")

    def test_the_stage_line_beyond_an_assumed_window_names_no_percentage(self):
        self.pct(250000)
        out = self.advice()
        self.assertEqual(out, "lead: 250k tokens of context, tokens exceed the assumed window 200,000; set lead.context_window; compact is safe now: run /compact\n")

    def test_the_threshold_is_an_answer_and_zero_turns_it_off(self):
        self.pct(100000)
        self.answers["lead"] = {"compact_advice_pct": 60}
        self.write_answers()
        self.assertEqual(self.advice(), "")
        self.answers["lead"] = {"compact_advice_pct": 50}
        self.write_answers()
        self.assertIn("lead: 50%, 100k tokens of context" + NOTE + ";", self.advice())
        self.answers["lead"] = {"compact_advice_pct": 0}
        self.write_answers()
        self.assertEqual(self.advice(), "")

    def test_it_says_why_not_when_a_compact_is_not_safe(self):
        self.pct(100000)
        d = os.path.join(self.t, "r1")
        os.makedirs(d)
        with open(os.path.join(self.state, "local-runs.jsonl"), "w") as f:
            f.write(json.dumps({"run": d, "slug": "r1", "ability": "build", "base": "feature/lc", "repo": self.repo}) + "\n")
        out = self.advice()
        self.assertEqual(out, "lead: 50%%, 100k tokens of context%s; compact is not safe yet: a local run is prepared and not verified (qargi lead compact-check)\n" % NOTE)

    def test_for_a_merge_it_waits_for_the_last_open_run_of_the_feature(self):
        self.pct(100000)
        d = os.path.join(self.t, "r1")
        os.makedirs(d)
        with open(os.path.join(self.state, "local-runs.jsonl"), "w") as f:
            f.write(json.dumps({"run": d, "slug": "r1", "ability": "build", "base": "feature/lc", "repo": self.repo}) + "\n")
        self.assertEqual(self.advice("--feature", "lc"), "")                                              # a run of feature/lc is still open
        self.assertIn("compact is not safe yet", self.advice("--feature", "other"))                       # not a run of that feature
        subprocess.run(["rm", "-rf", d])
        self.assertIn("compact is safe now", self.advice("--feature", "lc"))

    def test_it_never_fails_and_prints_nothing_when_it_cannot_tell(self):
        self.assertEqual(self.advice(), "")                                                               # no transcript
        r = subprocess.run([sys.executable, "-I", LEADPY, "advice", "--state", self.state, "--conf", self.conf, "--project", "nosuch"], capture_output=True, text=True, env=self.env())
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        os.makedirs(os.path.join(self.state, "ref-journal.jsonl"))                                          # a journal that is a directory
        self.pct(100000)
        self.assertIn("lead: 50%, 100k tokens of context" + NOTE + ";", self.advice())


if __name__ == "__main__":
    unittest.main()
