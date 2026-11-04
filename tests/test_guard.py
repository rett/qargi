#!/usr/bin/env python3
"""qargi __guard: the PreToolUse hook that keeps a local agent's Bash from publishing."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
import importlib.util, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, time, unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "qargi")
LIBDIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lib")


def guard(command):
    return subprocess.run([BIN, "__guard"], input=json.dumps({"tool_input": {"command": command}}), capture_output=True, text=True)


class Guard(unittest.TestCase):
    def test_refuses_what_publishes_or_reaches_out(self):
        for c in ("git push", "git push origin main", "/tmp/x/git -C /r push -f", "cd a && git push", "make gate-go; git push", "timeout 5 git push",
                  "echo hi | gh pr list", "gh api repos/x", "ssh host ls", "sudo scp a b:", "sftp host", "git remote add o u", "git remote set-url origin u"):
            r = guard(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("Agents never push", r.stderr)

    def test_lets_ordinary_work_through(self):
        for c in ("ls -la", "git status", "git commit -m 'a push of work'", "/tmp/x/git log --oneline", "git remote -v", "git diff c2e9439..HEAD",
                  "go test ./... && go vet ./...", "grep -n 'git push' file", "make gate-go", "gitleaks git --log-opts A..B"):
            self.assertEqual(guard(c).returncode, 0, c)

    def test_bad_input_is_not_a_block(self):
        r = subprocess.run([BIN, "__guard"], input="not json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(guard("").returncode, 0)

    def test_the_member_definition_guards_bash_edits_and_key_reads(self):
        d = os.path.join(os.path.dirname(BIN), "..", "agents")
        self.assertEqual(sorted(os.listdir(d)), ["member.body.md", "member.json", "member.md"],
                         "qargi ships one member definition: the neutral one (member.json, member.body.md) and the template of the claude-code adapter's dispatch-local")
        with open(os.path.join(d, "member.md")) as f:
            text = f.read()
        self.assertIn('command: "qargi __guard{{GUARD_ARGS}}"', text)
        self.assertIn('matcher: "Bash|Edit|Write|NotebookEdit|Read|Grep"', text)
        tools = [l for l in text.splitlines() if l.startswith("tools:")][0]
        for t in ("Edit", "Write", "Monitor", "ToolSearch", "Skill"):
            self.assertIn(t, tools)


class Review(unittest.TestCase):
    """Review is read-only as a rule: the run directory says the ability, the guard holds the clone to it."""
    def setUp(self):
        self.t = tempfile.mkdtemp()
        self.run = os.path.join(self.t, "qargi.x")
        for d in ("clone/src", "out"):
            os.makedirs(os.path.join(self.run, d))
        open(os.path.join(self.run, "refs.before"), "w").close()
        self.clone, self.out = os.path.join(self.run, "clone"), os.path.join(self.run, "out")

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def ability(self, a):
        with open(os.path.join(self.run, "ability"), "w") as f:
            f.write(a + "\n")

    def call(self, tool, inp, cwd=None, *args):
        return subprocess.run([BIN, "__guard", *args], input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": cwd or self.clone}),
                              capture_output=True, text=True)

    def writes(self):
        c, o = self.clone, self.out
        return [("Edit", {"file_path": os.path.join(c, "src/a.go")}), ("Write", {"file_path": "src/new.go"}),
                ("NotebookEdit", {"notebook_path": os.path.join(c, "n.ipynb")}),
                ("Bash", {"command": "echo x > src/a.go"}), ("Bash", {"command": "printf y >> %s/README" % c}),
                ("Bash", {"command": "sed -i s/a/b/ src/a.go"}), ("Bash", {"command": "rm -f src/a.go"}),
                ("Bash", {"command": "cp /etc/hostname src/"}), ("Bash", {"command": "touch src/x"}),
                ("Bash", {"command": "git commit -am fix"}), ("Bash", {"command": "%s/git -C %s checkout -- ." % (self.run, c)}),
                ("Bash", {"command": "cd %s && tee src/b < /dev/null" % c}), ("Bash", {"command": "git apply %s/fix.patch" % o}),
                ("Bash", {"command": "git tag v1"}), ("Bash", {"command": "git tag -d v1"}), ("Bash", {"command": "git tag -a v1 -m x"}),
                ("Bash", {"command": "git tag -l -f v1 HEAD~1"}), ("Bash", {"command": "git -C %s tag -s v2" % c}),
                ("Write", {"file_path": os.path.join(self.t, "elsewhere.txt")})]

    def reads(self):
        c, o = self.clone, self.out
        return [("Write", {"file_path": os.path.join(o, "report.md")}), ("Edit", {"file_path": os.path.join(o, "manifest.json")}),
                ("Bash", {"command": "git log --oneline && git diff HEAD~1"}), ("Bash", {"command": "make test > %s/test.log 2>&1" % o}),
                ("Bash", {"command": "grep -rn x src 2>/dev/null"}), ("Bash", {"command": "go test ./... | tee %s/log.txt" % o}),
                ("Bash", {"command": "cat src/a.go"}), ("Bash", {"command": "echo done && git log --format=%s -3"}),
                ("Bash", {"command": "cat > %s/notes.txt < /dev/null" % o}),
                ("Bash", {"command": "git tag"}), ("Bash", {"command": "git tag -l 'v*'"}), ("Bash", {"command": "git tag --list"}), ("Bash", {"command": "git tag -n --list"}),
                ("Bash", {"command": "git -C %s tag -l" % c}), ("Bash", {"command": "git for-each-ref --format='%(refname)' refs/tags"})]

    def test_review_refuses_every_change_to_the_clone(self):
        self.ability("review")
        for tool, inp in self.writes():
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 2, (tool, inp, r.stderr))
            self.assertIn("review", r.stderr)

    def test_a_review_refusal_names_out_as_the_place_to_write_not_run_dir(self):
        self.ability("review")
        for tool, inp in self.writes():
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 2, (tool, inp))
            self.assertNotIn("RUN_DIR", r.stderr, (tool, inp, r.stderr))
        r = self.call("Write", {"file_path": os.path.join(self.t, "elsewhere.txt")})
        self.assertIn("report and the manifest in OUT", r.stderr)
        r = self.call("Bash", {"command": "echo x > src/a.go"})
        self.assertIn("writes its report to OUT", r.stderr)

    def test_review_may_read_and_write_its_report(self):
        self.ability("review")
        for tool, inp in self.reads():
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 0, (tool, inp, r.stderr))

    def test_build_may_change_the_clone(self):
        self.ability("build")
        for tool, inp in self.writes() + self.reads():
            self.assertEqual(self.call(tool, inp).returncode, 0, (tool, inp))

    def test_the_class_in_the_hook_holds_whatever_the_run_file_says(self):
        self.ability("build")                                   # the file says build; the class in the hook says read-only
        for tool, inp in self.writes():
            r = self.call(tool, inp, None, "--class", "read-only")
            self.assertEqual(r.returncode, 2, (tool, inp, r.stderr))
        for tool, inp in self.reads():
            self.assertEqual(self.call(tool, inp, None, "--class", "read-only").returncode, 0, (tool, inp))

    def test_a_member_cannot_change_the_run_record(self):
        self.ability("review")
        a, b = os.path.join(self.run, "ability"), os.path.join(self.run, "refs.before")
        with open(os.path.join(self.run, "profile"), "w") as f:
            f.write("advisor\n")
        pr = os.path.join(self.run, "profile")
        for cls in ((), ("--class", "read-only")):
            for tool, inp in (("Write", {"file_path": a}), ("Edit", {"file_path": b}),
                              ("Bash", {"command": "printf build > %s" % a}), ("Bash", {"command": "echo x >> %s" % b}),
                              ("Write", {"file_path": pr}), ("Bash", {"command": "printf auditor > %s" % pr}),
                              ("Bash", {"command": "cd %s && printf build > ability" % self.run})):
                r = self.call(tool, inp, self.out, *cls)
                self.assertEqual(r.returncode, 2, (tool, inp, cls, r.stderr))
        with open(a) as f:
            self.assertEqual(f.read().strip(), "review")
        with open(pr) as f:
            self.assertEqual(f.read().strip(), "advisor")

    def test_a_member_cannot_change_what_clean_and_list_trust(self):
        """`local clean` removes the directory tmpdir names and asks the repository repo.path names whether the applied tip is merged; `local list`, verify and
        review apply read the others. A member must not be able to write any of them (a link, a rewritten path, a forged tip)."""
        self.ability("review")
        names = ("tmpdir", "applied", "repo.path", "repo.url", "cred.path", "started", "verified", "refs.after", "refs.diff", "git", "class", "ability", "profile", "refs.before")
        wrong = []
        for name in names:
            p = os.path.join(self.run, name)
            for cls in ((), ("--class", "read-only")):
                for tool, inp in (("Write", {"file_path": p}), ("Edit", {"file_path": p}), ("Bash", {"command": "printf x > %s" % p}), ("Bash", {"command": "echo x >> %s" % p}),
                                  ("Bash", {"command": "cd %s && printf x > %s" % (self.run, name)}), ("Bash", {"command": "ln -sf /etc/hostname %s" % p}),
                                  ("Bash", {"command": "cp /etc/hostname %s" % p}), ("Bash", {"command": "rm -f %s" % p}), ("Bash", {"command": "echo /tmp | tee %s" % p}),
                                  ("Bash", {"command": "mv %s/out/x %s" % (self.run, p)})):
                    if self.call(tool, inp, self.out, *cls).returncode != 2:
                        wrong.append((name, tool, inp, cls))
        self.assertEqual(wrong, [])
        self.ability("build")                                   # what is not a control file of the run stays writable
        for p in (os.path.join(self.run, "out", "report.md"), os.path.join(self.run, "out", "tmpdir"), os.path.join(self.run, "clone", "applied"), os.path.join(self.run, "notes")):
            self.assertEqual(self.call("Write", {"file_path": p}, self.out).returncode, 0, p)

    TAG_LISTS = ("git tag", "git tag -l", "git tag --list 'v*'", "git tag -l --sort=-creatordate", "git tag --contains HEAD", "git tag -n", "git tag -n5 -l", "git tag --points-at HEAD",
                 "git tag -l -i V1", "git tag -l --column", "git tag --merged main", "git tag --no-merged main -l", "git tag --format '%(refname)'",
                 "git tag --sort -creatordate", "git tag v1 -l", "git tag -l v1 HEAD", "git tag --list --points-at HEAD v1", "git -C . tag -l", "git tag --lis", "git tag --sort=x --contains HEAD",
                 "git tag -l --color=always", "git tag --no-column -l", "git tag -l -- v1 -d")
    TAG_CHANGES = ("git tag v1", "git tag --format -l NAME", "git tag --form -l NAME", "git tag --trailer -l NAME", "git tag --trailer=-l -l v3", "git tag -l --del NAME",
                   "git tag -l --anno NAME", "git tag -l --create-reflog v4", "git tag -lf v5", "git tag -l -d v1", "git tag -lm x v1", "git tag -s -l v1", "git tag --list --delete v1",
                   "git tag --no-create-reflog v16", "git tag -- -l", "git tag --list=v1", "git tag --contains HEAD v1", "git tag --sort -l v1", "git tag -l --foo v1", "git tag -l --no-c v1",
                   "git tag -ln -f v1", "git tag -l -u key v1", "git tag --local-user key -l v1", "git tag -F f -l", "git tag --file f -l", "git tag --message m -l", "git tag --cleanup=strip -l v1",
                   "git tag -m x", "git tag -a v1", "git tag --edit -l", "git tag -l -e", "git tag --sign -l", "git tag --force -l v1", "git tag -v v1", "git tag --verify v1",
                   "git tag -n 5", "git tag --points-at HEAD v1", "git tag --merged main v1")

    def test_tag_listing_is_allowed_and_every_option_that_makes_changes_or_deletes_a_tag_is_not(self):
        for setup in (lambda: (self.ability("review"), ()), lambda: (self.ability("build"), ("--class", "read-only"))):
            _, cls = setup()
            wrong = [c for c in self.TAG_LISTS if self.call("Bash", {"command": c}, None, *cls).returncode != 0]
            self.assertEqual(wrong, [], "a listing was refused")
            wrong = [c for c in self.TAG_CHANGES if self.call("Bash", {"command": c}, None, *cls).returncode != 2]
            self.assertEqual(wrong, [], "a tag was made, changed or deleted")

    def test_review_sees_a_change_that_a_careless_reading_of_the_text_would_miss(self):
        self.ability("review")
        for c in ("echo a\\ #; touch newfile", "echo a\\\n#; git commit -qam x", 'trap "true; git commit -qam x; true" EXIT', "echo $[1<<2]\ntouch newfile\n2]",
                  'X="true; touch newfile; true"; eval $X', "cat > ../a <<'E'\ntouch newfile\nE\nbash <../a", 'sh -c "true; touch newfile; true"',
                  'env sh -c "true; git commit -qam x; true"', "echo ${x:-1}\ntouch newfile", "echo '#'; touch newfile"):
            r = self.call("Bash", {"command": c})
            self.assertEqual(r.returncode, 2, (c, r.stderr))
        for c in ("echo 'x; touch newfile'", "git log --format='%s; touch newfile' -3"):         # text, but read as the plain split reads it
            self.assertEqual(self.call("Bash", {"command": c}).returncode, 2, c)
        self.assertEqual(self.call("Bash", {"command": "echo hi # touch newfile"}).returncode, 0)      # a word that is no command at the start of a segment

    def test_an_unknown_class_refuses_every_call(self):
        self.assertEqual(self.call("Bash", {"command": "ls"}, None, "--class", "root").returncode, 2)
        self.assertEqual(self.call("Bash", {"command": "ls"}, None, "--class").returncode, 2)

    def test_outside_a_run_nothing_changes(self):
        self.ability("review")
        self.assertEqual(self.call("Edit", {"file_path": os.path.join(self.t, "f")}, cwd=self.t).returncode, 0)
        self.assertEqual(self.call("Bash", {"command": "echo x > f"}, cwd=self.t).returncode, 0)
        self.assertEqual(self.call("Bash", {"command": "git push"}, cwd=self.t).returncode, 2)


class Skills(unittest.TestCase):
    """Only a person, through qargi's own skills, changes a skill: the guard refuses a member the verbs that do, and writes
    under the pack library and the skill directories. The repository's own skills/ directory (in the clone) stays open."""
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home, self.conf, self.clone = (os.path.join(self.t, d) for d in ("home", "conf", "run/clone"))
        for d in ("home/.claude/skills/x", "conf/packs/skills/s", "conf/packs/tools", "run/clone/skills/sample", "run/clone/.claude/skills/p", "run/out", "proj/.claude/skills/p", "proj/src"):
            os.makedirs(os.path.join(self.t, d))
        self.lib, self.lskill = os.path.join(self.conf, "packs"), os.path.join(self.home, ".claude/skills")
        os.symlink(self.lib, os.path.join(self.clone, "link-to-library"))
        self.run_dir = os.path.join(self.t, "run")                       # what `qargi local prepare` leaves: ability and refs.before
        for name, text in (("ability", "build\n"), ("refs.before", "")):
            with open(os.path.join(self.run_dir, name), "w") as f:
                f.write(text)
        self.proj = os.path.join(self.t, "proj")                          # a project outside any clone, with an installed .claude/skills

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def call(self, tool, inp, cwd=None, **env):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf}, **env)
        e = {k: v for k, v in e.items() if v is not None}
        return subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": cwd or self.clone}),
                              capture_output=True, text=True, env=e)

    def bash(self, command, **kw):
        return self.call("Bash", {"command": command}, **kw)

    def test_refuses_the_verbs_that_change_a_skill(self):
        verbs = ["%s %s x" % (a, v) for a in ("skill", "tool") for v in ("new", "import", "seal", "remove", "unlink", "link", "enable", "disable")]
        verbs += ["skill accept p x", "skill unaccept p x", "skill accept p x --user", "skill unaccept p x --user --plan 0123456789ab --approved go",
                  "skill accept p x --plan 0123456789ab --approved go"]
        verbs += ["discover install skill-pdf --project p", "packs apply p-build --asked x", "packs link p", "packs unlink p --plan 0123456789ab --approved go",
                  "packs link p --plan 0123456789ab --approved go", "import backup.tar.gz"]
        for v in verbs:
            for form in ("qargi %s", "/opt/q/bin/qargi %s", "sudo qargi %s", "cd src && qargi %s", "echo ok; qargi %s --approved go",
                         "bash -c 'qargi %s'", "sh -c \"cd /x && qargi %s\"", "eval 'qargi %s'", "echo $(qargi %s)", "echo `qargi %s`",
                         "timeout 5 qargi %s", "env FOO=1 qargi %s", "(qargi %s)", "bash -lc 'qargi %s'"):
                r = self.bash(form % v)
                self.assertEqual(r.returncode, 2, form % v)
                self.assertIn("changes a skill and is not available to an agent", r.stderr)
                self.assertIn("qargi guard:", r.stderr)
        for c in ("lib/packs.sh skill new x", "bash lib/packs.sh tool import f.json", "./lib/packs.sh packs apply i", "./lib/packs.sh packs link p", "bash lib/packs.sh skill accept p x", "./lib/packs.sh skill unaccept p x --user", "bash lib/packs.sh packs unlink p", "python3 -I lib/discover.py install foo"):
            self.assertEqual(self.bash(c).returncode, 2, c)

    def test_refuses_the_helper_scripts_of_the_link_and_accept_verbs_run_directly(self):
        """packs_link.py (packs link|unlink), packs_audit.py store (skill accept|unaccept) and marshal_handoff.py --write are what the shell
        verbs call; run directly with a hand-made inputs file they would skip the plan token and the audit line."""
        direct = ("python3 -I lib/packs_link.py apply link in.json 0123456789ab", "python3 -I lib/packs_link.py plan unlink in.json t",
                  "python3 lib/packs_link.py apply link in.json \"$(cat t)\"", "./lib/packs_link.py apply link in.json x", "bash -c 'python3 -I lib/packs_link.py apply unlink in.json x'",
                  "cd lib && python3 -I packs_link.py apply link ../in.json x", "/opt/q/lib/packs_link.py plan link in.json t",
                  "python3 -I lib/packs_audit.py store accept acc.json project p x 0123456789ab /r/x why 2026-01-01T00:00:00Z",
                  "python3 -I lib/packs_audit.py store unaccept acc.json user p x", "python3 -I lib/packs_audit.py store $v acc.json user p x",
                  "python3 -I lib/packs_audit.py $(echo store) accept acc.json user p x", "env X=1 python3 /opt/q/lib/packs_audit.py store accept a.json user p x h")
        for c in direct:
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("changes a skill and is not available to an agent", r.stderr)
        self.assertIn("qargi packs link", self.bash("python3 -I lib/packs_link.py apply link in.json t").stderr)
        self.assertIn("qargi packs unlink", self.bash("python3 -I lib/packs_link.py apply unlink in.json t").stderr)
        self.assertIn("qargi skill accept", self.bash("python3 -I lib/packs_audit.py store accept a.json user p x h").stderr)
        self.assertIn("qargi skill unaccept", self.bash("python3 -I lib/packs_audit.py store unaccept a.json user p x").stderr)
        for c in ("python3 -I lib/packs_audit.py report in.json", "python3 -I lib/packs_audit.py acceptance acc.json project p x",
                  "python3 -I lib/packs_audit.py scan in.json out.json", "python3 -I lib/packs_audit.py target in.json x project out.json",
                  "cat lib/packs_link.py", "grep -n store lib/packs_audit.py", "python3 -I lib/marshal_handoff.py --state s --conf c --project p f"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))
        for c in ("python3 -I lib/marshal_handoff.py --state s --conf c --project p --write note.md", "python3 lib/marshal_handoff.py --write=note.md --state s",
                  "python3 lib/marshal_handoff.py --wr note.md --state s", "python3 lib/marshal_handoff.py --w note.md", "./lib/marshal_handoff.py --project p $OPT note.md",
                  "python3 lib/marshal_handoff.py --project p $(echo --write) note.md", "python3 lib/marshal_handoff.py --project p `echo --write` n"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("the lead changes the marshal; report it in your task output", r.stderr)

    def test_refuses_project_link_and_unlink_to_a_member(self):
        """qargi project link|unlink makes the checkout and the runtime's memory directory load skills, agents and memory: a person's call, with a plan
        token. Refused as the verb, through the shell script and through the helper script it calls (any use of project_link.py is the verb)."""
        for v in ("link", "unlink"):
            for tail in ("p", "p --resource memory", "p --resource skills,agents --plan 0123456789ab --approved go"):
                for form in ("qargi project %s %s", "/opt/q/bin/qargi project %s %s", "sudo qargi project %s %s", "cd src && qargi project %s %s",
                             "bash -c 'qargi project %s %s'", "eval 'qargi project %s %s'", "echo $(qargi project %s %s)", "timeout 5 qargi project %s %s",
                             "env FOO=1 qargi project %s %s", "./lib/project.sh %s %s", "bash lib/project.sh %s %s"):
                    c = form % (v, tail)
                    r = self.bash(c)
                    self.assertEqual(r.returncode, 2, c)
                    self.assertIn("qargi project %s changes what the checkout and the runtime's memory directory load" % v, r.stderr, c)
                    self.assertIn("qargi guard:", r.stderr)
            for c in ("python3 -I lib/project_link.py apply %s p memory 0123456789ab" % v, "python3 -I lib/project_link.py plan %s p '' t" % v,
                      "./lib/project_link.py apply %s p skills,agents x" % v, "bash -c 'python3 lib/project_link.py apply %s p \"\" x'" % v,
                      "cd lib && python3 -I project_link.py apply %s p memory x" % v, "/opt/q/lib/project_link.py plan %s p memory t" % v):
                r = self.bash(c)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn("qargi project %s changes what the checkout" % v, r.stderr, c)
        for c in ("qargi project show p", "qargi project list", "qargi project validate p", "bash lib/project.sh show p", "cat lib/project_link.py",
                  "grep -n members lib/project_link.py", "qargi project set p budget_cents 500"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_project_set_of_models_to_a_member(self):
        """qargi project set stores any dotted answer. The models answers choose the runtime and what counts as a barrier (models.extensions,
        models.accept_no_barrier.*, models.provider.*), so a member may not set them; they have gated verbs (provider enable, provider accept)
        and the owner's own project set. The other answers stay open."""
        for path in ("models.extensions", "models.accept_no_barrier.local", "models.provider.local", "models.provider", "models", "models.extensions.0"):
            for form in ("qargi project set p %s v", "/opt/q/bin/qargi project set p %s v", "sudo qargi project set p %s v", "cd src && qargi project set p %s v",
                         "bash -c 'qargi project set p %s v'", "env FOO=1 qargi project set p %s v", "QARGI_X=1 qargi project set p %s v",
                         "echo $(qargi project set p %s v)", "./lib/project.sh set p %s v", "bash lib/project.sh set p %s v", "qargi project --x set p %s v"):
                c = form % path
                r = self.bash(c)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn("qargi project set of %s changes which runtime the project uses or what counts as its barrier and is not available to an agent" % path, r.stderr, c)
        for c in ("qargi project set p $K v", "qargi project set p \"$K\" v", "qargi project set p `echo models.extensions` v",
                  "qargi project set p $(echo models.extensions) v", "bash lib/project.sh set p $(echo models.extensions) v"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("a path the guard cannot read", r.stderr, c)
        for c in ("qargi project set p budget_cents 500", "qargi project set p roles.build.effort high", "qargi project set p test_command 'echo models.extensions'",
                  "qargi project show p", "qargi project validate p", "echo qargi project set p models.extensions x"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_project_init_to_a_member(self):
        """qargi project init --answers FILE --force stores a whole answers file, models.extensions and models.accept_no_barrier included, with no
        plan token: a member may not run it (nor the script, nor with a verb it cannot read)."""
        for form in ("qargi project init p --answers /tmp/a.json --force", "/opt/q/bin/qargi project init p --answers /tmp/a.json", "sudo qargi project init p --answers a.json",
                     "cd src && qargi project init p --answers a.json --force", "bash -c 'qargi project init p --answers a.json --force'", "env FOO=1 qargi project init p --answers a.json",
                     "echo $(qargi project init p --answers a.json)", "./lib/project.sh init p --answers a.json", "bash lib/project.sh init p --answers a.json --force",
                     "qargi project --x init p --answers a.json", "qargi pro''ject in\\it p --answers a.json", "qargi project $(echo init) p --answers a.json"):
            r = guard(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("qargi guard:", r.stderr, form)
        for c in ("qargi project show p", "qargi project template p", "qargi project validate /tmp/a.json", "echo qargi project init p"):
            self.assertEqual(guard(c).returncode, 0, c)

    def test_refuses_the_forms_of_project_set_the_guard_cannot_read(self):
        """The path of a project set is read from the words of the command. A form that hides it (a quote inside the verb, a substitution that
        splits the command, xargs, a brace or a glob, a missing path) is refused, whatever the path would turn out to be; one that states it
        stays as it was (the path decides)."""
        for c in ("QARGI_GATED_STORE=1 qargi pro''ject set demo $(echo models.extensions) '[\"x\"]'", "qargi project s\\et demo $(echo models.provider.local) evil",
                  "echo demo models.extensions '[\"x\"]' | QARGI_GATED_STORE=1 xargs qargi project set", "echo models.extensions | xargs qargi project set demo",
                  "xargs -n3 qargi project set < args", "QARGI_GATED_STORE=1 qargi project set demo {models.extensions,'[\"x\"]'}",
                  "qargi project set demo model?.extensions x", "qargi project set demo models.ext* x", "qargi project set demo models.extension[s] x",
                  "qargi project set demo {models.extensions,x}", "qargi project set", "qargi project set demo", "qargi project set demo $K v", "qargi project set demo budget_cents \"$N\"",
                  "qargi $(echo project) set demo models.extensions x", "qargi project $(echo set) demo models.extensions x", "qargi project $V demo models.extensions x",
                  "bash -c 'qargi project set demo $(echo models.extensions) x'", "sh -c \"qargi pro''ject set demo \\$(echo models.extensions) x\"",
                  "xargs sh -c 'qargi project set \"$@\"' _ < args", "eval qargi project set demo '$(echo models.extensions)' x", "qargi project link $(echo p)",
                  "qargi project $(echo link) p", "QARGI_GATED_STORE=1 qargi project set demo models.extensions '[\"x\"]'"):
            r = guard(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("qargi guard:", r.stderr, c)
        for c in ("qargi project set p budget_cents 500", "qargi project set p roles.build.effort high", "qargi project set p test_command 'ls *.py'",
                  "qargi project set p test_command 'echo $HOME'", "qargi project show $P", "qargi project list | xargs echo", "echo qargi project set p models.extensions x",
                  "grep -n 'project set' README.md", "bash -c 'qargi project show p'"):
            r = guard(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_the_script_that_stores_the_gated_answers(self):
        """lib/gated_answers.py stores models.extensions and models.accept_no_barrier for the verbs that passed a plan token; it has no gate of its
        own, so a member may not run it, however it is named."""
        for c in ("python3 -I lib/gated_answers.py store p models.extensions '[\"x\"]'", "./lib/gated_answers.py store p models.extensions '[]'",
                  "cd lib && python3 gated_answers.py store p models.extensions '[]'", "/opt/q/lib/gated_answers.py store p models.extensions x", "bash -c 'python3 lib/gated_answers.py store p models.extensions x'",
                  "sudo python3 lib/gated_answers.py"):
            r = guard(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("gated_answers.py", r.stderr, c)
        self.assertEqual(guard("cat lib/gated_answers.py").returncode, 0)

    def test_refuses_local_run_to_a_member(self):
        """qargi local run starts a process (a vendor CLI) with an environment the definition names: the lead's call. Refused as the verb and as
        any use of its helper script; the other local verbs are not touched."""
        for form in ("qargi local run %s", "/opt/q/bin/qargi local run %s", "sudo qargi local run %s", "bash -c 'qargi local run %s'", "env FOO=1 qargi local run %s",
                     "cd src && qargi local run %s", "echo $(qargi local run %s)", "./lib/local.sh run %s"):
            for tail in ("/tmp/r", "/tmp/r --dry-run", "/tmp/r --task t.md --again"):
                c = form % tail
                r = self.bash(c)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn("qargi local run starts the runtime's command", r.stderr, c)
        for c in ("python3 -I lib/local_run.py run /tmp/r x", "./lib/local_run.py dry /tmp/r", "cd lib && python3 local_run.py x", "/opt/q/lib/local_run.py x"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("qargi local run starts the runtime's command", r.stderr, c)
        for c in ("qargi local list /tmp/r", "cat lib/local_run.py", "grep -n argv lib/local_run.py"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_provider_accept_to_a_member(self):
        for form in ("qargi provider accept claude --surface cloud --no-barrier --asked x", "/opt/q/bin/qargi provider accept claude --surface local --no-barrier",
                     "sudo qargi provider accept nobarrier", "bash -c 'qargi provider accept claude --surface cloud'", "env FOO=1 qargi provider accept x",
                     "cd src && qargi provider accept claude --plan 0123456789ab --approved go", "echo $(qargi provider accept claude)",
                     "bash lib/provider.sh accept claude --surface cloud", "python3 -I lib/provider.py accept claude --surface cloud", "./lib/provider.sh accept claude"):
            r = self.bash(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("qargi provider accept records that you accept a provider with no read-only barrier and is not available to an agent", r.stderr)

    def test_lets_the_read_only_provider_verbs_through(self):
        for c in ("qargi provider list", "qargi provider show claude", "python3 -I lib/provider.py require-barrier claude cloud",
                  "python3 -I lib/provider.py effective claude local read_only_barrier", "echo qargi provider accept", "grep -n 'provider accept' lib/commands.py"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_provider_check_to_a_member(self):
        # it records its result in verified.json, so it is not a read
        r = self.bash("qargi provider check claude")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("qargi provider check records what it verified of a library pack", r.stderr)

    def test_refuses_release_publish_to_a_member(self):
        """release publish creates the GitHub release of a tag with the lead's gh; the verb, a verb held in a variable and the script run
        directly are refused. The other release verbs (and a word in a quoted string) stay as they were."""
        for form in ("qargi release publish 0.2.0", "qargi release publish 0.2.0 --plan 0123456789ab --approved go", "/opt/q/bin/qargi release publish 0.2.0",
                     "sudo qargi release publish 0.2.0", "bash -c 'qargi release publish 0.2.0'", "env FOO=1 qargi release publish 0.2.0", "cd src && qargi release publish 0.2.0",
                     "echo $(qargi release publish 0.2.0)", "qargi release publish 0.2.0 --project p", "qargi 'release' 'publish' 0.2.0", "eval 'qargi release publish 0.2.0'",
                     "bash lib/release.sh publish 0.2.0", "./lib/release.sh publish 0.2.0 --plan 0123456789ab --approved go", "v=publish; qargi release $v 0.2.0",
                     "qargi release ${V:-publish} 0.2.0", "qargi release --project p publish 0.2.0"):
            r = self.bash(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("qargi guard:", r.stderr)
            self.assertIn("qargi release publish creates a GitHub release and is not available to an agent", r.stderr)
        for c in ("qargi release status 0.2.0", "qargi release verify 0.2.0 --project p", "qargi release push 0.2.0", "bash lib/release.sh status 0.2.0",
                  "echo qargi release publish", "grep -n 'release publish' lib/commands.py", "qargi help release publish"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_env_plan_and_apply_to_a_member(self):
        """env plan runs the project's dry-run command and env apply its bootstrap: project code. Both verbs, a verb held in a variable, and the
        scripts run directly are refused; env show (it only reads) and words in a quoted string stay allowed."""
        for form in ("qargi env plan --approve-exec make", "qargi env apply --plan 0123456789ab --approved go --approve-exec make", "/opt/q/bin/qargi env plan",
                     "sudo qargi env apply --plan x", "bash -c 'qargi env plan --approve-exec make'", "env FOO=1 qargi env plan", "cd src && qargi env apply",
                     "echo $(qargi env plan --approve-exec make)", "qargi 'env' 'plan'", "eval 'qargi env apply --plan x'", "v=plan; qargi env $v",
                     "qargi env ${V:-plan} --approve-exec make", "qargi env pl$()an", "qargi env plan --repo . --project p", "timeout 5 qargi env apply --plan x",
                     "python3 -I %s/env.py plan --approve-exec make" % LibraryScripts.LIB, "python3 %s/env_apply.py" % LibraryScripts.LIB,
                     "bash lib/env_apply.py apply", "cd %s && python3 env.py apply --plan x" % LibraryScripts.LIB):
            r = self.bash(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("qargi guard:", r.stderr)
            self.assertIn("runs the project's dry-run or bootstrap command, which is project code", r.stderr, form)
        for c in ("qargi env show", "qargi env show --json --repo $PWD", "qargi env show --project p", "python3 -I %s/env.py show" % LibraryScripts.LIB,
                  "echo qargi env plan", "grep -n 'env apply' lib/commands.py", "qargi help env plan", "qargi env", "cat lib/env_apply.py",
                  "python3 env.py plan", "FOO=1 python3 -I lib/other/env.py plan"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_packs_seed_to_a_member(self):
        for form in ("qargi packs seed", "qargi packs seed --install", "/opt/q/bin/qargi packs seed --plan 0123456789ab --approved go", "bash -c 'qargi packs seed'"):
            r = self.bash(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("changes a skill and is not available to an agent", r.stderr)
        self.assertEqual(self.bash("./lib/packs.sh packs seed").returncode, 2)

    def test_lets_the_read_only_verbs_through(self):
        for c in ("qargi skill list", "qargi skill show x", "qargi tool check p build", "qargi skill effective p build", "qargi discover search pdf",
                  "qargi packs render p build /tmp/o", "qargi packs load style --role build", "qargi packs check --target claude-code p",
                  "echo qargi skill accept p x", "git commit -m 'qargi skill unaccept p x'", "qargi export a.tgz", "qargi help skill",
                  "git commit -m 'qargi skill new is refused for members'", "grep -rn 'qargi skill link' docs", "echo qargi skill remove x",
                  "ls skills", "qargi local list"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_refuses_setting_the_nested_marker(self):
        for c in ("QARGI_NESTED=1 qargi memory split a b", "env QARGI_NESTED=1 qargi skill list", "export QARGI_NESTED=1", "bash -c 'QARGI_NESTED=1 qargi x'",
                  "declare -x QARGI_NESTED=1"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("QARGI_NESTED", r.stderr)
        self.assertEqual(self.bash("grep -rn QARGI_NESTED lib").returncode, 0)
        self.assertEqual(self.bash("echo $QARGI_NESTED").returncode, 0)

    def test_edit_tools_are_decided_by_the_resolved_path(self):
        c, lib, ls = self.clone, self.lib, self.lskill
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p in (os.path.join(lib, "skills/s/SKILL.md"), os.path.join(lib, "links.json"), os.path.join(lib, "accepted.json"), os.path.join(ls, "x/SKILL.md"), "../home/.claude/skills/x/SKILL.md",
                      "link-to-library/skills/s/SKILL.md", os.path.join(self.proj, ".claude/skills/p/SKILL.md"), "../../proj/.claude/skills/new/SKILL.md",
                      "~/.claude/skills/x/SKILL.md", "~/.claude/agents/m.md", "~/.claude/plugins/p/plugin.json"):
                r = self.call(tool, {key: p})
                self.assertEqual(r.returncode, 2, (tool, p, r.stderr))
                self.assertIn("protected location", r.stderr)
            for p in ("skills/sample/SKILL.md", os.path.join(c, "skills/new/SKILL.md"), "src/a.go", os.path.join(self.t, "run/out/report.md"),
                      ".claude/skills/p/SKILL.md", os.path.join(c, ".claude/skills/new/SKILL.md"), "sub/.claude/skills/q/SKILL.md",
                      os.path.join(self.t, "conf/projects/p.json"), os.path.join(ls, "../history.jsonl")):
                r = self.call(tool, {key: p})
                self.assertEqual(r.returncode, 0, (tool, p, r.stderr))

    def test_the_repositorys_own_skills_directory_stays_editable(self):
        for c in ("echo x > skills/sample/SKILL.md", "sed -i s/a/b/ skills/sample/SKILL.md", "cp -r skills/sample skills/sample-new",
                  "mv skills/a skills/b", "rm -rf skills/old", "git add skills && git commit -m s", "tee skills/sample/notes.md < /dev/null",
                  "cd skills/sample && touch extra.md", "rsync -a skills/ %s/run/out/skills/" % self.t, "install -m 644 a.md skills/sample/"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_bash_writes_to_a_protected_location_are_refused(self):
        lib, ls = self.lib, self.lskill
        for c in ("echo x > %s/skills/s/SKILL.md" % lib, "echo x >> %s/links.json" % lib, "echo x>%s/links.json" % lib, "echo '{}' > %s/accepted.json" % lib, "cp a.json %s/accepted.json" % lib, "mv a.json %s/accepted.json" % lib,
                  "sed -i s/a/b/ %s/accepted.json" % lib, "rm %s/accepted.json" % lib, "cat a 2> %s/e" % ls,
                  "echo x | tee %s/x/SKILL.md" % ls, "cp a.md %s/x/" % ls, "cp -t %s/x a.md" % ls, "cp --target-directory=%s/x a.md" % ls,
                  "mv %s/x /tmp/gone" % ls, "mv a.md %s/x/SKILL.md" % ls, "rm -rf %s/skills/s" % lib, "rm -rf ~/.claude", "rm -rf %s" % self.home,
                  "ln -s /etc/passwd %s/x/SKILL.md" % ls, "install -m 644 a %s/x/SKILL.md" % ls, "sed -i s/a/b/ %s/x/SKILL.md" % ls,
                  "perl -pi -e s/a/b/ %s/x/SKILL.md" % ls, "rsync -a src/ %s/x/" % ls, "dd if=/dev/zero of=%s/x/SKILL.md" % ls,
                  "truncate -s 0 %s/x/SKILL.md" % ls, "chmod 777 %s/x/SKILL.md" % ls, "touch %s/x/new" % ls, "mkdir %s/skills/new" % lib,
                  "cd %s/x && echo y > SKILL.md" % ls, "cd %s && rm -r skills" % lib, "echo y > ~/.claude/skills/x/SKILL.md",
                  "echo y > $HOME/.claude/skills/x/SKILL.md", "echo y > $QARGI_CONF/packs/links.json", "echo y > %s/.claude/skills/p/SKILL.md" % self.proj,
                  "echo y > ~/.claude/agents/m.md", "echo y > ~/.claude/plugins/p.json", "cd %s && echo y > .claude/skills/p/SKILL.md" % self.proj,
                  "rm -rf %s/.claude" % self.proj, "echo y > link-to-library/links.json", "cp a.md link-to-library/", "rm -rf link-to-library/skills", "tar xf a.tgz -C %s/x" % ls, "tar czf %s/x/b.tgz ." % ls, "tar --extract --file=a.tgz --directory=%s/x" % ls, "unzip -o a.zip -d %s/x" % ls, "curl -o %s/x/SKILL.md http://h/f" % ls,
                  "find %s -name '*.md' -delete" % ls, "find %s -exec rm {} +" % lib, "git -C %s checkout ." % lib, "patch %s/x/SKILL.md fix.diff" % ls,
                  "bash -c 'echo y > %s/links.json'" % lib, "sh -c \"cd %s/x; touch y\"" % ls, "eval 'rm %s/x/SKILL.md'" % ls,
                  "echo $(echo y > %s/links.json)" % lib):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, (c, r.stderr))
            self.assertIn("protected location", r.stderr)

    def test_bash_reads_and_other_writes_are_not_refused(self):
        lib, ls = self.lib, self.lskill
        for c in ("cat %s/x/SKILL.md" % ls, "cat %s/x/SKILL.md > %s/run/out/copy.md" % (ls, self.t), "cp %s/x/SKILL.md %s/run/out/" % (ls, self.t),
                  "grep -rn foo %s" % lib, "cat %s/accepted.json" % lib, "jq . %s/accepted.json" % lib, "ls -la %s" % ls, "diff -r %s/x skills/sample" % ls, "rsync -a %s/ %s/run/out/lib/" % (lib, self.t),
                  "jq . %s/links.json > %s/run/out/l.json" % (lib, self.t), "find %s -name '*.md'" % ls, "find %s -name SKILL.md -exec cat {} +" % self.clone + " > /dev/null",
                  "tar czf %s/run/out/lib.tgz -C %s ." % (self.t, lib), "echo x > %s/home/.claude/history.jsonl" % self.t, "rm -rf %s/run/out/old" % self.t,
                  "curl -s http://h/f -o %s/run/out/f" % self.t, "touch %s/.claude" % self.proj, "ls ~/.claude/skills", "echo ~/.claude/skills > list.txt", "cd %s && ls" % lib):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_the_protected_roots_follow_the_environment(self):
        other = os.path.join(self.t, "xdg")
        os.makedirs(os.path.join(other, "qargi/packs"))
        target = os.path.join(other, "qargi/packs/links.json")
        r = self.bash("echo x > %s" % target, QARGI_CONF=None, XDG_CONFIG_HOME=other)         # XDG_CONFIG_HOME does not move the library
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.bash("echo x > %s" % target).returncode, 0)                    # QARGI_CONF names another root
        r = self.bash("echo x > %s/.config/qargi/packs/links.json" % self.home, QARGI_CONF=None)   # nor is the XDG default one
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.bash("echo x > %s/.qargi/config/packs/links.json" % self.home, QARGI_CONF=None)   # the plain default, under HOME
        self.assertEqual(r.returncode, 2, r.stderr)
        r = self.call("Write", {"file_path": os.path.join(self.t, "alt/packs/links.json")}, QARGI_CONF=os.path.join(self.t, "alt"))
        self.assertEqual(r.returncode, 2, r.stderr)
        r = self.bash("echo x > %s/.qargi/config/packs/links.json" % self.home)         # the default stays protected beside QARGI_CONF
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_the_pack_library_is_protected_where_the_data_lives(self):
        for d in (".qargi/config/packs", "qh/config/packs", "qh2/config/packs", "xdgc/qargi/packs"):
            os.makedirs(os.path.join(self.t, d if d.startswith(("qh", "xdgc")) else "home/" + d), exist_ok=True)
        new_default = "%s/.qargi/config/packs/links.json" % self.home
        for target, env in ((new_default, dict(QARGI_CONF=None)),                                    # ~/.qargi/config
                            (os.path.join(self.t, "qh/config/packs/links.json"), dict(QARGI_CONF=None, QARGI_HOME=os.path.join(self.t, "qh")))):
            r = self.bash("echo x > %s" % target, **env)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
            r = self.call("Write", {"file_path": target}, **env)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
        # protection stops at the library: the rest of the new root is not a skill
        r = self.bash("echo x > %s/.qargi/config/instances.json" % self.home, QARGI_CONF=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        # QARGI_HOME is the root; XDG_CONFIG_HOME does not move it, and an XDG library is not one
        self.assertEqual(self.bash("echo x > %s/xdgc/qargi/packs/links.json" % self.t, QARGI_CONF=None, XDG_CONFIG_HOME=os.path.join(self.t, "xdgc")).returncode, 0)
        self.assertEqual(self.bash("echo x > %s/.config/qargi/packs/links.json" % self.home, QARGI_CONF=None).returncode, 0)
        other = os.path.join(self.t, "qh2/config/packs/links.json")
        self.assertEqual(self.bash("echo x > %s" % other, QARGI_CONF=None).returncode, 0)
        self.assertEqual(self.bash("echo x > %s" % other, QARGI_CONF=None, QARGI_HOME=os.path.join(self.t, "qh2")).returncode, 2)

    def test_credentials_and_the_install_record_are_protected_the_rest_of_conf_is_not(self):
        qh, qh3 = (os.path.join(self.t, d) for d in ("qh", "qh3"))
        bases = {"QARGI_CONF": (self.conf, dict()),
                 "QARGI_HOME": (qh + "/config", dict(QARGI_CONF=None, QARGI_HOME=qh)),
                 "QARGI_HOME beside QARGI_CONF": (qh3 + "/config", dict(QARGI_HOME=qh3)),
                 "live": (os.path.join(self.home, ".qargi/config"), dict(QARGI_CONF=None)),
                 "live beside QARGI_HOME": (os.path.join(self.home, ".qargi/config"), dict(QARGI_CONF=None, QARGI_HOME=qh))}
        for name, (base, env) in bases.items():
            os.makedirs(os.path.join(base, "credentials"), exist_ok=True)
            os.makedirs(os.path.join(base, "projects"), exist_ok=True)
            for f in ("credentials/tok", "install.json", "instances.json", "projects/x.json"):
                with open(os.path.join(base, f), "w") as fh:
                    fh.write("{}")
            cred, inst = os.path.join(base, "credentials/tok"), os.path.join(base, "install.json")
            for target in (cred, inst, os.path.join(base, "credentials/new-token")):
                for c in ("echo x > %s" % target, "echo x >> %s" % target, "echo x | tee %s" % target, "cp /dev/null %s" % target, "mv %s/f %s" % (self.clone, target),
                          "rm %s" % target, "rm -f %s" % target, "touch %s" % target, "chmod 644 %s" % target, "sed -i s/a/b/ %s" % target, "ln -sf /x %s" % target):
                    r = self.bash(c, **env)
                    self.assertEqual(r.returncode, 2, (name, c, r.stderr))
                    self.assertIn("protected location", r.stderr)
                for tool in ("Write", "Edit"):
                    r = self.call(tool, {"file_path": target}, **env)
                    self.assertEqual(r.returncode, 2, (name, tool, target, r.stderr))
            for c in ("rm -rf %s/credentials" % base, "mv %s/credentials /tmp/x" % base, "mv %s/install.json %s/run/out/" % (base, self.t)):
                self.assertEqual(self.bash(c, **env).returncode, 2, (name, c))
            # a link in the clone that leads to a protected path is followed and refused
            link = os.path.join(self.clone, "to-%d" % len(os.listdir(self.clone)))
            os.symlink(os.path.join(base, "credentials"), link)
            self.assertEqual(self.call("Write", {"file_path": link + "/tok"}, **env).returncode, 2, name)
            self.assertEqual(self.bash("echo x > %s/tok" % link, **env).returncode, 2, name)
            os.symlink(inst, link + "-i")
            self.assertEqual(self.call("Write", {"file_path": link + "-i"}, **env).returncode, 2, name)
            # the rest of the configuration directory is not protected, and reading never is
            for f in ("instances.json", "projects/x.json", "projects/new.json", "agents.json", "profiles/p.md"):
                os.makedirs(os.path.join(base, "profiles"), exist_ok=True)
                t = os.path.join(base, f)
                for r in (self.bash("echo x > %s" % t, **env), self.call("Write", {"file_path": t}, **env), self.bash("cp /dev/null %s && rm %s" % (t, t), **env)):
                    self.assertEqual(r.returncode, 0, (name, f, r.stderr))
            for c in ("cat %s" % cred, "cat %s" % inst, "ls -la %s/credentials" % base, "cp %s %s/run/out/tok" % (cred, self.t), "grep -r x %s" % base,
                      "cp -r %s/credentials %s/run/out/" % (base, self.t), "jq . %s" % inst):
                r = self.bash(c, **env)
                self.assertEqual(r.returncode, 0, (name, c, r.stderr))
            self.assertEqual(self.call("Read", {"file_path": cred}, **env).returncode, 0)
        # the guard knows nothing of the qargi verb: one that writes other conf files through the tool itself is not in its way
        # (project init is not one of them any more: it stores a whole answers file, models.extensions among them, and is refused to a member)
        for c in ("qargi agent add worker", "qargi project set x budget_cents 500", "qargi instances list"):
            self.assertEqual(self.bash(c).returncode, 0, c)

    def test_the_installed_tool_and_a_projects_member_definitions_are_protected(self):
        tool = os.path.join(self.t, "opt/qargi")
        os.makedirs(os.path.join(tool, "skills/sample"))
        os.makedirs(os.path.join(self.proj, ".claude/agents"))
        with open(os.path.join(self.conf, "install.json"), "w") as f:
            json.dump({"tool_root": tool}, f)
        os.symlink(os.path.join(tool, "skills/sample"), os.path.join(self.lskill, "sample"))   # what install.sh makes
        for target in (os.path.join(tool, "skills/sample/SKILL.md"), os.path.join(self.lskill, "sample/SKILL.md"),
                       os.path.join(tool, "agents/member.md"), os.path.join(self.proj, ".claude/agents/m.md")):
            self.assertEqual(self.call("Write", {"file_path": target}).returncode, 2, target)
            r = self.bash("echo x > %s" % target)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
        self.assertEqual(self.bash("rm -rf %s" % os.path.join(self.proj, ".claude")).returncode, 2)
        self.assertEqual(self.bash("cat %s" % os.path.join(tool, "skills/sample/SKILL.md")).returncode, 0)   # reading stays allowed
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.clone, ".claude/agents/m.md")}).returncode, 0)   # the clone's is work product

    def test_the_clone_exemption_still_holds_beside_the_new_roots(self):
        os.makedirs(os.path.join(self.clone, "credentials"))
        for c in ("echo y > credentials/tok", "echo y > install.json", "echo y > .claude/skills/p/SKILL.md", "mkdir -p config/credentials && echo y > config/credentials/t"):
            self.assertEqual(self.bash(c).returncode, 0, c)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.clone, "credentials/tok")}).returncode, 0)

    def test_a_home_whose_dot_claude_is_a_link_is_still_protected(self):
        home2, real = os.path.join(self.t, "home2"), os.path.join(self.t, "elsewhere")
        os.makedirs(os.path.join(real, "skills/x"))
        os.makedirs(home2)
        os.symlink(real, os.path.join(home2, ".claude"))                            # ~/.claude/skills resolves to .../elsewhere/skills
        for call in (("Write", {"file_path": "~/.claude/skills/x/SKILL.md"}), ("Bash", {"command": "echo y > ~/.claude/skills/x/SKILL.md"})):
            self.assertEqual(self.call(*call, HOME=home2).returncode, 2, call)
        self.assertEqual(self.call("Write", {"file_path": "~/.claude/settings.json"}, HOME=home2).returncode, 2)      # the lead's own settings: refused whatever the link
        self.assertEqual(self.call("Write", {"file_path": "~/.claude/history.jsonl"}, HOME=home2).returncode, 0)

    def test_inside_the_clone_the_dot_claude_skills_directory_is_the_work_product(self):
        for c in ("echo y > .claude/skills/p/SKILL.md", "echo y>%s/.claude/skills/p/SKILL.md" % self.clone, "mkdir -p .claude/skills/new && touch .claude/skills/new/SKILL.md",
                  "cp -r skills/sample .claude/skills/qb", "mv .claude/skills/p .claude/skills/q", "rm -rf .claude/skills/p", "rm -rf .claude",
                  "sed -i s/a/b/ .claude/skills/p/SKILL.md", "cd .claude/skills/p && touch more.md", "tee .claude/skills/p/n.md < /dev/null",
                  "install -m 644 a.md %s/.claude/skills/p/" % self.clone, "cp -t .claude/skills/p a.md", "git add .claude/skills && git commit -m s"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))
        r = self.call("Edit", {"file_path": os.path.join(self.clone, ".claude/skills/p/SKILL.md")}, cwd=self.t)       # run from outside the clone
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_exemption_is_for_the_resolved_path_in_the_clone(self):
        # (a) a link inside the clone that leads to a protected root, or to a project's installed directory, is still denied
        os.symlink(self.lskill, os.path.join(self.clone, ".claude/skills/to-user"))
        os.symlink(os.path.join(self.proj, ".claude/skills"), os.path.join(self.clone, "to-proj"))
        for call in (("Write", {"file_path": ".claude/skills/to-user/x/SKILL.md"}), ("Write", {"file_path": "to-proj/p/SKILL.md"}),
                     ("Bash", {"command": "echo y > .claude/skills/to-user/x/SKILL.md"}), ("Bash", {"command": "cp a.md to-proj/p/"}),
                     ("Bash", {"command": "rm -rf .claude/skills/to-user/x"}), ("Write", {"file_path": "link-to-library/links.json"})):
            r = self.call(*call)
            self.assertEqual(r.returncode, 2, (call, r.stderr))
            self.assertIn("protected location", r.stderr)
        # (b) .claude/skills outside any clone stays protected, also when reached from inside the clone with ..
        for call in (("Write", {"file_path": os.path.join(self.proj, ".claude/skills/p/SKILL.md")}), ("Write", {"file_path": "../../proj/.claude/skills/p/SKILL.md"}),
                     ("Bash", {"command": "echo y > ../../proj/.claude/skills/p/SKILL.md"}), ("Bash", {"command": "echo y > %s/.claude/skills/p/SKILL.md" % self.proj})):
            self.assertEqual(self.call(*call).returncode, 2, call)
        # a directory that merely looks like a clone, in a directory that is not a run, is not exempt
        fake = os.path.join(self.t, "proj/clone/.claude/skills/p")
        os.makedirs(fake)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(fake, "SKILL.md")}).returncode, 2)
        # the run directory itself, outside its clone, is not exempt either
        os.makedirs(os.path.join(self.run_dir, ".claude/skills/p"))
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.run_dir, ".claude/skills/p/SKILL.md")}).returncode, 2)
        # (c) a Bash write whose resolved destination is in the clone is allowed from any directory
        r = self.bash("echo y > %s/.claude/skills/p/SKILL.md" % self.clone, cwd=self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_a_symbolic_link_does_not_hide_the_target(self):
        os.symlink(self.lskill, os.path.join(self.clone, "sk"))
        for call in (("Write", {"file_path": "sk/x/SKILL.md"}), ("Bash", {"command": "echo y > sk/x/SKILL.md"}), ("Bash", {"command": "rm -rf sk/x"})):
            self.assertEqual(self.call(*call).returncode, 2, call)


class RenderTree(unittest.TestCase):
    """$DA_STATE/render/<project>/<runtime> is the render a runtime loads (Claude Code with --add-dir): instructions a session follows. No member
    class may write there; reading stays open. The claude/ directory an earlier version used is not special any more."""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call      # the same fixture, not its tests

    def setUp(self):
        self.setUp_skills()
        self.state = os.path.join(self.t, "state")
        self.render = os.path.join(self.state, "render", "proj", "claude-code")
        os.makedirs(os.path.join(self.render, "skills/s"))
        os.makedirs(os.path.join(self.state, "runs"))
        os.makedirs(os.path.join(self.t, "elsewhere/render/proj"))
        os.symlink(self.render, os.path.join(self.clone, "to-render"))
        os.symlink(os.path.join(self.state, "render"), os.path.join(self.clone, "to-renders"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_STATE", self.state)
        return self.call_skills(tool, inp, cwd, **env)

    def test_edit_tools_refuse_every_path_under_the_render_directory(self):
        r = self.render
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p in (os.path.join(r, "skills/s/SKILL.md"), os.path.join(r, "new.md"), os.path.join(self.state, "render/other/x"),
                      os.path.join(self.state, "render"), "to-render/skills/s/SKILL.md", "to-renders/proj/new.md", "../../state/render/proj/claude-code/CLAUDE.md"):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn("managed by qargi and changed only by the lead", res.stderr)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
        return e

    def test_bash_writes_into_the_render_are_refused(self):
        r = self.render
        for c in ("echo x > %s/CLAUDE.md" % r, "echo x >> %s/skills/s/SKILL.md" % r, "echo x>%s/CLAUDE.md" % r, "echo x | tee %s/CLAUDE.md" % r,
                  "cp a.md %s/skills/s/" % r, "cp -t %s a.md" % r, "mv a.md %s/x.md" % r, "mv %s/skills /tmp/gone" % r, "rm -rf %s/skills" % r,
                  "rm -rf %s" % r, "rm -rf %s/render" % self.state, "sed -i s/a/b/ %s/skills/s/SKILL.md" % r, "perl -pi -e s/a/b/ %s/CLAUDE.md" % r,
                  "ln -s /etc/passwd %s/x" % r, "touch %s/x" % r, "mkdir %s/new" % r, "chmod 777 %s/CLAUDE.md" % r, "truncate -s 0 %s/CLAUDE.md" % r,
                  "dd if=/dev/zero of=%s/CLAUDE.md" % r, "rsync -a src/ %s/" % r, "install -m 644 a %s/x" % r, "patch %s/CLAUDE.md fix.diff" % r,
                  "git -C %s checkout ." % r, "git -C %s/render add -A" % self.state, "cd %s && echo y > CLAUDE.md" % r, "cd %s && rm -r skills" % r,
                  "tar xf a.tgz -C %s" % r, "unzip -o a.zip -d %s" % r, "curl -o %s/x http://h/f" % r, "find %s -name '*.md' -delete" % r,
                  "echo y > to-render/CLAUDE.md", "rm -rf to-renders/proj", "bash -c 'echo y > %s/CLAUDE.md'" % r, "eval 'rm %s/CLAUDE.md'" % r,
                  "echo $(echo y > %s/CLAUDE.md)" % r, "echo y > $QARGI_STATE/render/proj/claude-code/CLAUDE.md", "qargi packs render p build %s" % r,
                  "qargi packs render p build --out %s" % r):
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("managed by qargi and changed only by the lead", res.stderr)

    def test_the_render_is_found_like_the_other_qargi_paths(self):
        home_state = os.path.join(self.home, ".qargi/state/render/proj")
        qh_state = os.path.join(self.t, "qh/state/render/proj")
        for d in (home_state, qh_state):
            os.makedirs(d)
        for target, env in ((home_state, dict(QARGI_STATE=None)), (qh_state, dict(QARGI_STATE=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                            (os.path.join(self.t, "alt/render/proj"), dict(QARGI_STATE=os.path.join(self.t, "alt")))):
            os.makedirs(target, exist_ok=True)
            self.assertEqual(self.call("Write", {"file_path": target + "/CLAUDE.md"}, **env).returncode, 2, (target, env))
            self.assertEqual(self.bash("echo x > %s/CLAUDE.md" % target, **env).returncode, 2, (target, env))
        # the default stays protected beside an override, as the pack library does
        self.assertEqual(self.call("Write", {"file_path": home_state + "/CLAUDE.md"}).returncode, 2)

    def test_reads_of_the_render_stay_allowed(self):
        r = self.render
        for c in ("cat %s/CLAUDE.md" % r, "ls -la %s" % r, "grep -rn foo %s" % r, "cp %s/CLAUDE.md %s/run/out/" % (r, self.t),
                  "cat %s/CLAUDE.md > %s/run/out/c.md" % (r, self.t), "tar czf %s/run/out/r.tgz -C %s ." % (self.t, r),
                  "find %s -name '*.md'" % r, "cd %s && ls" % r, "git -C %s log" % r, "diff -r %s/skills skills" % r, "qargi packs render p build %s/run/out/r" % self.t):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_a_path_that_merely_says_render_is_allowed(self):
        e = os.path.join(self.t, "elsewhere/render/proj")
        for p in (e + "/CLAUDE.md", os.path.join(self.state, "runs/render/x"), os.path.join(self.state, "render-notes.md"),
                  os.path.join(self.state, "runs/x.log"), os.path.join(self.t, "state2/render/proj/x")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self.assertEqual(self.call("Write", {"file_path": p}).returncode, 0, p)
            self.assertEqual(self.bash("echo x > %s" % p).returncode, 0, p)
        for c in ("echo x > %s/runs/audit.log" % self.state, "rm -rf %s/runs/old" % self.state, "touch render/x", "echo render > notes.txt"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_packs_apply_is_refused_with_whatever_options(self):
        for c in ("qargi packs apply --target claude-code", "qargi packs apply proj --target claude-code", "qargi packs apply --target=claude-code proj",
                  "qargi packs apply proj --target claude-code --asked x", "/opt/q/bin/qargi packs apply --target claude-code",
                  "bash -c 'qargi packs apply --target claude-code'", "sudo qargi packs apply proj --target claude-code", "echo $(qargi packs apply --target claude-code)",
                  "lib/packs.sh packs apply proj --target claude-code", "qargi skill new x", "qargi tool link x"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, c)
            self.assertIn("is not available to an agent", res.stderr)
        self.assertEqual(self.bash("qargi packs render p build /tmp/o").returncode, 0)

    def test_the_directory_of_the_earlier_layout_is_not_special_any_more(self):
        old = os.path.join(self.state, "claude", "proj")
        os.makedirs(old)
        self.assertEqual(self.call("Write", {"file_path": old + "/CLAUDE.md"}).returncode, 0)
        for cmd in ("echo x > %s/CLAUDE.md" % old, "rm -rf %s" % old, "echo x > $QARGI_STATE/claude/proj/CLAUDE.md"):
            res = self.bash(cmd)
            self.assertEqual(res.returncode, 0, (cmd, res.stderr))

    def test_the_verb_that_moved_the_earlier_renders_is_no_verb_the_guard_names(self):
        res = self.bash("qargi packs migrate-render --plan 000000000000 --approved x")
        self.assertEqual(res.returncode, 0, res.stderr)


class Marshal(unittest.TestCase):
    """The feature marshal is changed only by the lead: its records under $DA_STATE/features are protected, the verbs that
    change it and the lead identity (QARGI_LEAD) are not available to a member. Reading and status/check stay allowed."""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call

    def setUp(self):
        self.setUp_skills()
        self.state = os.path.join(self.t, "state")
        self.feat = os.path.join(self.state, "features")
        os.makedirs(self.feat)
        open(os.path.join(self.feat, "proj-f.json"), "w").close()
        os.symlink(self.feat, os.path.join(self.clone, "to-features"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_STATE", self.state)
        return self.call_skills(tool, inp, cwd, **env)

    def test_edit_tools_refuse_every_path_under_features(self):
        f = self.feat
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p in (f + "/proj-f.json", f + "/proj-new.json", f, "to-features/proj-f.json", "../../state/features/x.json"):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
        return e

    def refused(self, cmds):
        for c in cmds:
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)

    def test_bash_writes_into_features_are_refused(self):
        f = self.feat
        self.refused(["echo x > %s/proj-f.json" % f, "echo x>>%s/proj-f.json" % f, "echo x | tee %s/proj-f.json" % f, "cp a.json %s/" % f,
                      "cp -t %s a.json" % f, "mv a.json %s/proj-f.json" % f, "mv %s /tmp/gone" % f, "rm %s/proj-f.json" % f, "rm -rf %s" % f,
                      "sed -i s/a/b/ %s/proj-f.json" % f, "perl -pi -e s/a/b/ %s/proj-f.json" % f, "ln -sf /x %s/proj-f.json" % f,
                      "truncate -s 0 %s/proj-f.json" % f, "dd if=/dev/zero of=%s/proj-f.json" % f, "cd %s && echo y > proj-f.json" % f,
                      "cd %s && rm proj-f.json" % f, "echo y > to-features/proj-f.json", "bash -c 'echo y > %s/proj-f.json'" % f,
                      "eval 'rm %s/proj-f.json'" % f, "echo $(echo y > %s/proj-f.json)" % f, "echo y > $QARGI_STATE/features/proj-f.json",
                      "echo y \\\n> %s/proj-f.json" % f, "env FOO=1 tee %s/proj-f.json" % f, "sudo rm %s/proj-f.json" % f,
                      "find %s -name '*.json' -delete" % f, "install -m 644 a %s/x.json" % f, "touch %s/new.json" % f])

    def test_features_is_found_like_the_other_qargi_paths(self):
        home_state = os.path.join(self.home, ".qargi/state/features")
        qh = os.path.join(self.t, "qh/state/features")
        alt = os.path.join(self.t, "alt/features")
        for target, env in ((home_state, dict(QARGI_STATE=None)), (qh, dict(QARGI_STATE=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                            (alt, dict(QARGI_STATE=os.path.join(self.t, "alt")))):
            os.makedirs(target, exist_ok=True)
            self.assertEqual(self.call("Write", {"file_path": target + "/p-f.json"}, **env).returncode, 2, (target, env))
            self.assertEqual(self.bash("echo x > %s/p-f.json" % target, **env).returncode, 2, (target, env))
        self.assertEqual(self.call("Write", {"file_path": home_state + "/p-f.json"}).returncode, 2)

    def test_reads_and_look_alikes_stay_allowed(self):
        f = self.feat
        for c in ("cat %s/proj-f.json" % f, "ls %s" % f, "grep -rn owner %s" % f, "cp %s/proj-f.json %s/run/out/" % (f, self.t),
                  "cat %s/proj-f.json > %s/run/out/c.json" % (f, self.t), "find %s -name '*.json'" % f, "cd %s && ls" % f,
                  "qargi marshal status", "qargi marshal check proj f", "qargi marshal status --json", "/opt/q/bin/qargi marshal status",
                  "bash -c 'qargi marshal check'", "echo $QARGI_LEAD", "env | grep QARGI_LEAD", "echo x > %s/features-notes.md" % self.state):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))
        os.makedirs(os.path.join(self.t, "elsewhere/features"))
        p = os.path.join(self.t, "elsewhere/features/x.json")
        self.assertEqual(self.call("Write", {"file_path": p}).returncode, 0)
        self.assertEqual(self.bash("echo x > %s" % p).returncode, 0)

    def test_mutating_marshal_verbs_are_refused_however_they_are_run(self):
        cmds = []
        for v in ("claim", "set", "renew", "release", "take", "takeover", "finish", "enable", "disable"):
            cmds += ["qargi marshal %s proj f" % v, "qargi marshal %s --owner x" % v, "/opt/q/bin/qargi marshal %s" % v, "bin/qargi marshal %s" % v,
                     "env FOO=1 qargi marshal %s" % v, "FOO=1 qargi marshal %s" % v, "command qargi marshal %s" % v, "sudo qargi marshal %s" % v,
                     "bash -c 'qargi marshal %s p f'" % v, "sh -c \"qargi marshal %s\"" % v, "eval 'qargi marshal %s'" % v,
                     "echo $(qargi marshal %s)" % v, "echo `qargi marshal %s`" % v, "true && qargi marshal %s" % v, "ls; qargi marshal %s" % v,
                     "qargi 'marshal' '%s'" % v, "qargi mar\"\"shal %s" % v, "qargi marshal \\\n%s" % v, "python3 bin/qargi marshal %s" % v,
                     "bash lib/marshal.sh %s" % v, "lib/marshal.sh marshal %s" % v, "nohup qargi marshal %s" % v, "timeout 5 qargi marshal %s" % v,
                     "bash -c 'x=1; qargi marshal %s'" % v, "v=%s; qargi marshal $v" % v, "qargi marshal ${V:-%s}" % v]
        cmds += ["qargi marshal", "qargi marshal frobnicate", "qargi marshal $v", "qargi marshal \"$v\"", "v=claim; qargi marshal $v proj f",
                 "qargi marshal Claim", "qargi marshal CLAIM", "qargi marshal STATUS", "qargi marshal Status", "qargi marshal statuss", "qargi marshal check2"]
        self.refused(cmds)

    def test_handoff_is_a_read_for_a_member_until_it_is_given_a_file_to_write(self):
        """marshal handoff reads like status and check do; only --write (a file is made) is refused, however it is run, and so is an
        argument the guard cannot read because a variable holds it."""
        for c in ("qargi marshal handoff", "qargi marshal handoff f", "qargi marshal handoff f --project proj", "qargi marshal handoff f --json",
                  "qargi marshal handoff --as me", "/opt/q/bin/qargi marshal handoff f", "bin/qargi marshal handoff f --json", "env FOO=1 qargi marshal handoff f",
                  "bash -c 'qargi marshal handoff f'", "bash lib/marshal.sh handoff f", "echo $(qargi marshal handoff f)", "ls; qargi marshal handoff f",
                  "qargi marshal handoff f | head -5", "timeout 5 qargi marshal handoff f --json"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))
        cmds = []
        for w in ("--write note.md", "--write /tmp/x/note.md", "--write=note.md", "--json --write note.md", "f --write note.md", "f --project proj --write note.md"):
            cmds += ["qargi marshal handoff %s" % w, "/opt/q/bin/qargi marshal handoff %s" % w, "bin/qargi marshal handoff %s" % w,
                     "env FOO=1 qargi marshal handoff %s" % w, "sudo qargi marshal handoff %s" % w, "bash -c 'qargi marshal handoff %s'" % w,
                     "sh -c \"qargi marshal handoff %s\"" % w, "eval 'qargi marshal handoff %s'" % w, "echo $(qargi marshal handoff %s)" % w,
                     "true && qargi marshal handoff %s" % w, "ls; qargi marshal handoff %s" % w, "qargi 'marshal' 'handoff' %s" % w,
                     "bash lib/marshal.sh handoff %s" % w, "lib/marshal.sh marshal handoff %s" % w, "nohup qargi marshal handoff %s" % w]
        cmds += ["qargi marshal handoff f '--write' note.md", "qargi marshal handoff f \"--write\" note.md", "qargi marshal handoff f $OPT note.md",
                 "qargi marshal handoff f ${OPT:---json}", "qargi marshal handoff f `echo --json`", "v=handoff; qargi marshal $v f",
                 "qargi marshal handoff f $(echo --write) note.md", "qargi marshal handoff f `echo --write` note.md", "bash -c 'qargi marshal handoff f $(echo --write) x'",
                 "qargi marshal handoff $(echo f --write note.md)", "bash lib/marshal.sh handoff f $(echo --write) note.md",
                 "echo --write note.md | xargs qargi marshal handoff f", "printf x | xargs -n2 qargi marshal handoff", "xargs qargi marshal handoff f < args.txt",
                 "cat args | xargs bash lib/marshal.sh handoff f", "echo x | xargs -I{} qargi marshal handoff f"]
        for c in cmds:
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)
        res = self.bash("qargi marshal handoff f --write note.md")
        self.assertIn("handoff --write writes a file", res.stderr)

    def test_the_other_marshal_verbs_are_still_refused_with_handoff_named_as_a_read(self):
        res = self.bash("qargi marshal claim f")
        self.assertEqual(res.returncode, 2)
        self.assertIn("only status, check and handoff without --write are", res.stderr)
        self.assertEqual(self.bash("qargi marshal handoffs f").returncode, 2)
        self.assertEqual(self.bash("qargi marshal Handoff f").returncode, 2)

    def test_feature_verbs_that_write_the_marshal_are_refused_however_they_are_run(self):
        """feature start, finish and verify create, finish and renew the lead's record (marshal_start, marshal_finish and the
        renewer): a member whose working directory lies outside its run would push them with the lead's credentials."""
        cmds = []
        for v in ("start", "finish", "verify"):
            cmds += ["qargi feature %s f" % v, "qargi feature %s f --project proj" % v, "/opt/q/bin/qargi feature %s f" % v, "bin/qargi feature %s f" % v,
                     "env FOO=1 qargi feature %s f" % v, "sudo qargi feature %s f" % v, "bash -c 'qargi feature %s f'" % v,
                     "eval 'qargi feature %s f'" % v, "echo $(qargi feature %s f)" % v, "true && qargi feature %s f" % v, "ls; qargi feature %s f" % v,
                     "qargi 'feature' '%s' f" % v, "bash lib/feature.sh %s f" % v, "lib/feature.sh %s f" % v, "nohup qargi feature %s f" % v,
                     "v=%s; qargi feature $v f" % v]
        cmds += ["qargi feature $v f", "qargi feature \"$v\" f", "qargi feature ${V:-start} f", "qargi feature frobnicate f", "qargi feature START f"]
        self.refused(cmds)

    def test_the_other_feature_verbs_stay_allowed(self):
        for c in ("qargi feature list", "qargi feature status f", "qargi feature status f --project proj", "qargi feature merge f agent/x",
                  "qargi feature sync f", "/opt/q/bin/qargi feature status f", "echo qargi feature start f", "git log --grep 'feature finish'",
                  "grep -n 'feature start' lib/commands.py", "ls lib/feature.sh", "cat lib/feature.sh"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_the_switch_directory_is_protected_like_features(self):
        """$STATE/marshal/<project>.enabled turns the shared-refs backend on; a member must not write it by any construct."""
        m = os.path.join(self.state, "marshal")
        os.makedirs(m)
        open(os.path.join(m, "proj.enabled"), "w").close()
        os.symlink(m, os.path.join(self.clone, "to-marshal"))
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p in (m + "/proj.enabled", m + "/new.enabled", m, "to-marshal/proj.enabled", "../../state/marshal/x.enabled"):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)
        self.refused(["echo '{}' > %s/proj.enabled" % m, "echo x>>%s/proj.enabled" % m, "echo x | tee %s/proj.enabled" % m, "cp a.json %s/proj.enabled" % m,
                      "mv a.json %s/proj.enabled" % m, "mv %s /tmp/gone" % m, "rm %s/proj.enabled" % m, "rm -rf %s" % m, "touch %s/other.enabled" % m,
                      "sed -i s/a/b/ %s/proj.enabled" % m, "ln -sf /x %s/proj.enabled" % m, "cd %s && echo y > proj.enabled" % m,
                      "echo y > to-marshal/proj.enabled", "bash -c 'echo y > %s/proj.enabled'" % m, "echo y > $QARGI_STATE/marshal/proj.enabled"])
        for c in ("cat %s/proj.enabled" % m, "ls %s" % m, "grep -rn backend %s" % m, "cp %s/proj.enabled %s/run/out/" % (m, self.t),
                  "echo x > %s/marshal-notes.md" % self.state, "echo x > %s/marshalled.enabled" % self.state):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))
        os.makedirs(os.path.join(self.t, "elsewhere/marshal"))
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.t, "elsewhere/marshal/x.enabled")}).returncode, 0)

    def test_the_switch_directory_is_found_like_the_other_qargi_paths(self):
        for st, env in ((os.path.join(self.home, ".qargi/state"), dict(QARGI_STATE=None)),
                        (os.path.join(self.t, "qh/state"), dict(QARGI_STATE=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                        (os.path.join(self.t, "alt"), dict(QARGI_STATE=os.path.join(self.t, "alt")))):
            target = os.path.join(st, "marshal")
            os.makedirs(target, exist_ok=True)
            self.assertEqual(self.call("Write", {"file_path": target + "/p.enabled"}, **env).returncode, 2, (target, env))
            self.assertEqual(self.bash("echo x > %s/p.enabled" % target, **env).returncode, 2, (target, env))

    def test_the_observation_cache_of_the_refs_backend_is_protected(self):
        """$STATE/features/.observed-<project>.json is the taker's own clock record; it lies under features/, so a member may not write it."""
        o = os.path.join(self.feat, ".observed-proj.json")
        for tool, key in (("Edit", "file_path"), ("Write", "file_path")):
            res = self.call(tool, {key: o})
            self.assertEqual(res.returncode, 2, (tool, res.stderr))
            self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)
        self.refused(["echo '{}' > %s" % o, "rm -f %s" % o, "cp a.json %s" % o, "mv a.json %s" % o, "echo '{}' | tee %s" % o,
                      "cd %s && echo '{}' > .observed-proj.json" % self.feat])
        self.assertEqual(self.bash("cat %s" % o).returncode, 0)

    def test_a_marshal_word_is_not_a_verb_of_another_command(self):
        for c in ("echo marshal claim", "git log --grep 'marshal claim'", "grep -n 'marshal claim' lib/commands.py", "cat marshal.sh", "ls lib/marshal.sh"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_setting_the_lead_identity_is_refused(self):
        self.refused(["export QARGI_LEAD=me", "export QARGI_LEAD", "QARGI_LEAD=me qargi marshal status", "QARGI_LEAD=me", "env QARGI_LEAD=me qargi marshal status",
                      "env -u QARGI_LEAD qargi marshal status", "env --unset=QARGI_LEAD ls", "unset QARGI_LEAD", "unset -v QARGI_LEAD",
                      "declare -x QARGI_LEAD=me", "readonly QARGI_LEAD=me", "FOO=1 QARGI_LEAD=me ls", "ls; export QARGI_LEAD=me", "true && QARGI_LEAD=me ls",
                      "bash -c 'export QARGI_LEAD=me'", "sh -c 'QARGI_LEAD=me qargi marshal status'", "eval 'QARGI_LEAD=me ls'", "echo $(QARGI_LEAD=me ls)",
                      "export 'QARGI_LEAD'=me", "export QARGI_LEAD\\\n=me", "sudo env QARGI_LEAD=me ls", "export A=1 QARGI_LEAD=me", "QARGI_LEAD+=x ls",
                      "command export QARGI_LEAD=me", "unset A QARGI_LEAD"])

    def test_other_variables_are_not_the_lead(self):
        for c in ("export QARGI_LEADER=me", "QARGI_LEAD_X=1 ls", "export MY_QARGI_LEAD=1", "unset QARGI_STATE_X", "echo QARGI_LEAD=1"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    # --- signed marshal records: the lead's signing key, the allowed signers and the acceptance marks

    KEY_NOTE = "the signing key is the lead's alone; report it in your task output"

    def make_key(self, base=None):
        """A credentials directory with the lead's signing key (private and public), another credential and a look-alike."""
        cred = os.path.join(base or self.conf, "credentials")
        os.makedirs(cred, exist_ok=True)
        for n in ("marshal_ed25519", "marshal_ed25519.pub", "tok", "marshalled", "marshal-notes"):
            with open(os.path.join(cred, n), "w") as f:
                f.write("x\n")
        return cred

    def key_refused(self, cmds, env=None):
        for c in cmds:
            res = self.bash(c, **(env or {}))
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("the marshal's signing key", res.stderr, c)
            self.assertIn(self.KEY_NOTE, res.stderr, c)

    def test_the_signing_key_cannot_be_read_by_any_construct(self):
        """New behaviour: a read of a credential stays allowed in general, but not of credentials/marshal_*."""
        cred = self.make_key()
        k, out = os.path.join(cred, "marshal_ed25519"), os.path.join(self.t, "run/out")
        os.symlink(k, os.path.join(self.clone, "to-key"))
        os.symlink(cred, os.path.join(self.clone, "to-creds"))
        cmds = ["cat %s" % k, "cat %s.pub" % k, "head -c 40 %s" % k, "tail %s" % k, "less %s" % k, "more %s" % k, "base64 %s" % k, "strings %s" % k,
                "grep -n . %s" % k, "grep BEGIN %s" % k, "xxd %s" % k, "od -c %s" % k, "sed -n 1p %s" % k, "awk 1 %s" % k, "ssh-keygen -y -f %s" % k,
                "cp %s %s/k" % (k, out), "dd if=%s of=%s/k" % (k, out), "tar cf %s/k.tar %s" % (out, k), "rsync %s %s/" % (k, out),
                "cat < %s" % k, "cat <%s" % k, "xargs cat < %s" % k, "cat %s > %s/k" % (k, out), "cat %s | base64" % k, "wc -c %s" % k,
                "cat $QARGI_CONF/credentials/marshal_ed25519", "cat ${QARGI_CONF}/credentials/marshal_ed25519", "cat to-key", "cat to-creds/marshal_ed25519",
                "cat ../../conf/credentials/marshal_ed25519", "cat %s/../credentials/marshal_ed25519" % cred, "cat --file=%s" % k,
                "cd %s && cat marshal_ed25519" % cred, "cd %s; head marshal_ed25519" % cred, "cd %s && cat *" % cred, "cd %s && cat marshal_*" % cred,
                "cat %s/marshal_*" % cred, "cat %s/m*" % cred, "cat %s/marshal_ed2551?" % cred, "cat %s/marshal_ed2551[0-9]" % cred, "cat %s/cred*/marshal_ed25519" % self.conf,
                "cat %s/marshal_{ed25519,x}" % cred, "cat %s/*" % cred,
                "bash -c 'cat %s'" % k, "sh -c \"cat %s\"" % k, "bash -lc 'cd %s && cat marshal_ed25519'" % cred, "eval 'cat %s'" % k, "echo $(cat %s)" % k,
                "echo `cat %s`" % k, "true && cat %s" % k, "ls; cat %s" % k, "sudo cat %s" % k, "env FOO=1 cat %s" % k, "nohup cat %s" % k, "timeout 5 cat %s" % k,
                "FOO=1 cat %s" % k, "(cat %s)" % k, "python3 -c 'print(open(\"%s\").read())'" % k, "python3 -I -c \"import sys; sys.stdout.write(open('%s').read())\"" % k]
        self.key_refused(cmds)
        self.assertEqual(self.bash("cp -t %s/run/out %s" % (self.t, k)).returncode, 2)     # the destination rule of cp reads the key as one (its text differs)

    def test_the_signing_key_cannot_be_read_by_the_read_tools(self):
        cred = self.make_key()
        os.symlink(cred, os.path.join(self.clone, "to-creds"))
        for tool, inp in (("Read", {"file_path": os.path.join(cred, "marshal_ed25519")}), ("Read", {"file_path": os.path.join(cred, "marshal_ed25519.pub")}),
                          ("Read", {"file_path": "to-creds/marshal_ed25519"}), ("Grep", {"pattern": "BEGIN", "path": os.path.join(cred, "marshal_ed25519")}), ("Grep", {"pattern": "BEGIN", "path": cred}),
                          ("Grep", {"pattern": "BEGIN", "path": "to-creds"})):
            res = self.call(tool, inp)
            self.assertEqual(res.returncode, 2, (tool, inp, res.stderr))
            self.assertIn("the marshal's signing key", res.stderr)
            self.assertIn(self.KEY_NOTE, res.stderr)
        for tool, inp in (("Read", {"file_path": os.path.join(cred, "tok")}), ("Read", {"file_path": os.path.join(cred, "marshalled")}),
                          ("Read", {"file_path": os.path.join(self.conf, "marshal_ed25519")}), ("Grep", {"pattern": "x", "path": os.path.join(cred, "tok")}),
                          ("Grep", {"pattern": "x", "path": "src"}), ("Glob", {"pattern": "*", "path": cred}), ("Read", {"file_path": "skills/sample"})):
            res = self.call(tool, inp)
            self.assertEqual(res.returncode, 0, (tool, inp, res.stderr))

    def test_a_directory_that_holds_the_signing_key_cannot_be_read_whole(self):
        """New behaviour: a recursive reader named on the credentials directory (or above it) would carry the key along."""
        cred = self.make_key()
        out = os.path.join(self.t, "run/out")
        self.key_refused(["cp -r %s %s/" % (cred, out), "cp -r %s %s/" % (self.conf, out), "cp -a %s %s/c" % (cred, out), "tar cf %s/c.tar %s" % (out, cred),
                          "tar czf %s/c.tgz %s" % (out, self.conf), "rsync -a %s/ %s/c/" % (cred, out), "grep -r BEGIN %s" % cred,
                          "rg BEGIN %s" % cred,
                          "zip -r %s/z.zip %s" % (out, self.conf), "cd %s && tar cf %s/c.tar ." % (cred, out), "cd %s && cp -r . %s/c" % (cred, out),
                          "cd %s && grep -r BEGIN ." % cred, "bash -c 'cp -r %s %s/c'" % (cred, out)])
        for c in ("find %s -type f -exec cat {} +" % cred, "find %s -type f -execdir cat {} ;" % cred):     # find's actions already count as writes
            self.assertEqual(self.bash(c).returncode, 2, c)
        for c in ("ls %s" % cred, "ls -la %s" % self.conf, "cat %s/tok" % cred, "cp %s/tok %s/t" % (cred, out), "grep -n x %s/tok" % cred,
                  "find %s -type f" % cred, "grep -r x %s/instances.json" % self.conf, "cp -r %s %s/c" % (self.clone, out), "cp -r src %s/c" % out):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_the_signing_key_is_found_like_the_other_qargi_paths(self):
        qh = os.path.join(self.t, "qh")
        for base, env in ((qh + "/config", dict(QARGI_CONF=None, QARGI_HOME=qh)), (os.path.join(self.home, ".qargi/config"), dict(QARGI_CONF=None))):
            k = os.path.join(self.make_key(base), "marshal_ed25519")
            self.key_refused(["cat %s" % k, "base64 %s" % k, "bash -c 'cat %s'" % k], env)
            res = self.call("Read", {"file_path": k}, **env)
            self.assertEqual(res.returncode, 2, (base, res.stderr))

    def test_metadata_and_look_alikes_of_the_signing_key_stay_allowed(self):
        """Pin (passes before and after): the other credentials, names that only look like the key's and its metadata stay open."""
        cred = self.make_key()
        k = os.path.join(cred, "marshal_ed25519")
        for c in ("ls %s" % k, "ls -la %s" % cred, "stat %s" % k, "test -f %s" % k, "[ -f %s ]" % k, "[[ -s %s ]]" % k,
                  "cat %s/tok" % cred, "cat %s/marshalled" % cred, "cat %s/marshal-notes" % cred, "cat %s/marshal_ed25519" % self.conf,
                  "cat lib/marshal_store.py", "cat marshal_ed25519", "echo marshal_ed25519", "grep -rn marshal_ lib/marshal.sh", "cp lib/marshal_refs.py %s/run/out/" % self.t,
                  "qargi marshal status", "qargi marshal check proj f", "echo credentials/marshal_ed25519 is the key", "git log --grep marshal_ed25519"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))
        for tool in ("Write", "Edit"):                                    # writing it stays refused by the credentials root, as before
            res = self.call(tool, {"file_path": k})
            self.assertEqual(res.returncode, 2, (tool, res.stderr))
            self.assertIn("protected location", res.stderr)
        self.assertEqual(self.bash("echo x > %s" % k).returncode, 2)
        self.assertEqual(self.bash("rm -f %s" % k).returncode, 2)
        self.assertEqual(self.bash("cp /dev/null %s.pub" % k).returncode, 2)
        os.makedirs(os.path.join(self.clone, "credentials"))               # a credentials directory inside the clone is work product
        self.assertEqual(self.bash("cat credentials/marshal_ed25519").returncode, 0)

    def test_pushd_and_popd_are_followed_like_cd_when_the_signing_key_is_looked_for(self):
        """Review fix: `pushd DIR; cat marshal_ed25519` reads the key like `cd DIR; cat ...` does; popd goes back where the command was."""
        cred = self.make_key()
        self.key_refused(["pushd %s && cat marshal_ed25519" % cred, "pushd %s; head marshal_ed25519" % cred, "pushd %s >/dev/null && cat marshal_*" % cred,
                          "pushd -n %s; cat %s/marshal_ed25519" % (cred, cred), "cd /tmp && pushd %s && base64 marshal_ed25519" % cred,
                          "bash -c 'pushd %s && cat marshal_ed25519'" % cred, "pushd %s && pushd /tmp && popd && cat marshal_ed25519" % cred,
                          "pushd %s && cp -r . /tmp/c" % cred])
        for c in ("pushd %s >/dev/null && popd >/dev/null && cat marshal_ed25519" % cred, "pushd /tmp && cat marshal_ed25519", "popd && cat marshal_ed25519",
                  "pushd %s && cat tok" % cred, "pushd src && popd && cat lib/marshal_store.py"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_a_link_a_symbolic_copy_or_a_move_aimed_at_the_credentials_or_the_key_is_refused(self):
        """Review fix: a symbolic link to the credentials directory (or to the key) made in the same command as the read that goes through it
        is invisible to the guard, so making one is refused like a read; a move of the key is a write to a protected location."""
        cred = self.make_key()
        k, out = os.path.join(cred, "marshal_ed25519"), os.path.join(self.t, "run/out")
        self.key_refused(["ln -s %s %s/l" % (cred, out), "ln -sf %s/ %s/l" % (cred, out), "ln -s %s %s/l" % (self.conf, out), "ln -s %s %s/l" % (k, out),
                          "ln %s %s/l" % (k, out), "ln -s %s %s/l && cat %s/l/marshal_ed25519" % (cred, out, out), "bash -c 'ln -s %s %s/l'" % (cred, out),
                          "cp -s %s %s/l" % (k, out), "cp -rs %s %s/l" % (cred, out), "cp -sr %s %s/l" % (self.conf, out), "cp --symbolic-link -r %s %s/l" % (cred, out),
                          "cp -l %s %s/l" % (k, out), "cd %s && ln -s . %s/l" % (cred, out)])
        for c in ("mv %s %s/l" % (k, out), "mv %s %s/l" % (cred, out), "mv %s %s/l" % (self.conf, out), "cd %s && mv marshal_ed25519 %s/l" % (cred, out)):
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
        for c in ("ln -s %s/tok %s/l" % (cred, out), "ln -s lib/marshal_store.py %s/l" % out, "cp -s lib/marshal.sh %s/l" % out, "mv a b",
                  "cp %s/tok %s/t" % (cred, out), "ln -s %s %s/l" % (self.clone, out)):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_the_text_of_a_program_names_the_signing_key_through_slash_dot_and_double_slash(self):
        """Review fix: the scan of a -c string for the key's path reads `dir//marshal_ed25519` and `dir/./marshal_ed25519` as the path."""
        cred = self.make_key()
        self.key_refused(["python3 -c 'print(open(\"%s//marshal_ed25519\").read())'" % cred, "python3 -c 'print(open(\"%s/./marshal_ed25519\").read())'" % cred,
                          "python3 -c 'print(open(\"%s/.//marshal_ed25519\").read())'" % cred, "python3 -c 'print(open(\"%s///marshal_ed25519.pub\").read())'" % cred,
                          "perl -e 'open F, \"%s/././marshal_ed25519\"; print <F>'" % cred, "node -e 'require(\"fs\").readFileSync(\"%s//./marshal_ed25519\")'" % cred])

    def test_the_allowed_signers_and_the_acceptance_marks_are_protected(self):
        """Pin: $STATE/marshal/<project>.signers lies under marshal/ and $STATE/features/.accepted-<project>.json under
        features/, both protected roots. New: the refusal says what the file is."""
        m, f = os.path.join(self.state, "marshal"), self.feat
        os.makedirs(m)
        for p in (m + "/proj.signers", f + "/.accepted-proj.json"):
            open(p, "a").close()
        os.symlink(m, os.path.join(self.clone, "to-marshal"))
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p, text in ((m + "/proj.signers", "allowed signers"), (m + "/new.signers", "allowed signers"), ("to-marshal/proj.signers", "allowed signers"),
                            ("../../state/marshal/x.signers", "allowed signers"), (f + "/.accepted-proj.json", "acceptance marks"),
                            (f + "/.accepted-new.json", "acceptance marks"), ("to-features/.accepted-proj.json", "acceptance marks")):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)
                    self.assertIn(text, res.stderr, (tool, p))
        s, a = m + "/proj.signers", f + "/.accepted-proj.json"
        for target, text in ((s, "allowed signers"), (a, "acceptance marks")):
            for c in ("echo x > %s" % target, "echo x >> %s" % target, "echo x | tee %s" % target, "cp a %s" % target, "mv a %s" % target, "rm -f %s" % target,
                      "sed -i s/a/b/ %s" % target, "truncate -s 0 %s" % target, "ln -sf /x %s" % target, "cd %s && echo x > %s" % (os.path.dirname(target), os.path.basename(target)),
                      "bash -c 'echo x > %s'" % target, "dd if=/dev/null of=%s" % target):
                res = self.bash(c)
                self.assertEqual(res.returncode, 2, (c, res.stderr))
                self.assertIn(text, res.stderr, c)
        self.refused(["echo x > $QARGI_STATE/marshal/other.signers", "echo '{}' > to-features/.accepted-p.json", "rm -rf %s" % m])
        for c in ("cat %s" % s, "cat %s" % a, "ls -a %s" % f, "cp %s %s/run/out/" % (s, self.t), "grep -n ssh-ed25519 %s" % s,
                  "echo x > %s/proj.signers.txt" % self.state):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_the_signing_verbs_are_refused_with_their_own_reason(self):
        """Pin the refusal (the verbs are not in MARSHAL_READ); new: the message says what the verb does."""
        text = {"key": "manages the marshal's signing key", "signers": "manages the marshal's allowed signers", "resign": "signs a marshal record"}
        for v, why in text.items():
            for form in ("qargi marshal %s init", "qargi marshal %s add --line x", "qargi marshal %s list", "qargi marshal %s proj f --approved go",
                         "/opt/q/bin/qargi marshal %s x", "env FOO=1 qargi marshal %s", "sudo qargi marshal %s x", "bash -c 'qargi marshal %s x'",
                         "eval 'qargi marshal %s x'", "echo $(qargi marshal %s x)", "true && qargi marshal %s x", "bash lib/marshal.sh %s x",
                         "python3 bin/qargi marshal %s x", "nohup qargi marshal %s x", "qargi 'marshal' '%s'", "v=%s; qargi marshal $v"):
                res = self.bash(form % v)
                self.assertEqual(res.returncode, 2, (form % v, res.stderr))
                self.assertIn("qargi guard:", res.stderr)
                self.assertIn("the lead changes the marshal; report it in your task output", res.stderr)
                if "$v" not in form:
                    self.assertIn(why, res.stderr, form % v)
        for c in ("qargi marshal enable --integrity strict", "qargi marshal enable proj --integrity advisory"):
            self.assertEqual(self.bash(c).returncode, 2, c)
        for c in ("qargi marshal status", "qargi marshal check proj f", "echo qargi marshal key init", "grep -n 'marshal resign' lib/commands.py"):
            self.assertEqual(self.bash(c).returncode, 0, c)


class RefJournal(unittest.TestCase):
    """The lead's ref journal ($QARGI_STATE/ref-journal.jsonl) is changed only by the lead's own verbs: a write, move, delete
    or redirect of it, its lock or a rotated file beside it is refused to a member; reading stays allowed. (The journal is
    trusted only as far as the state directory is: an executor running as the same OS user could still edit it by code the guard
    cannot see; HMAC-signed records are a later feature.)"""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call
    NOTE = "the lead changes the marshal; report it in your task output"

    def setUp(self):
        self.setUp_skills()
        self.state = os.path.join(self.t, "state")
        self.jn = os.path.join(self.state, "ref-journal.jsonl")
        os.makedirs(self.state)
        with open(self.jn, "w") as f:
            f.write("{}\n")
        os.symlink(self.jn, os.path.join(self.clone, "to-journal"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_STATE", self.state)
        return self.call_skills(tool, inp, cwd, **env)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
        return e

    def refused(self, cmds):
        for c in cmds:
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("ref journal", res.stderr)
            self.assertIn(self.NOTE, res.stderr)

    def test_edit_tools_refuse_the_journal_its_lock_and_rotated_files(self):
        j = self.jn
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
            for p in (j, j + ".lock", j + ".1", j + ".tmp", j + ".2024.gz", "to-journal", "../../state/ref-journal.jsonl"):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn(self.NOTE, res.stderr)

    def test_bash_writes_to_the_journal_are_refused(self):
        j = self.jn
        self.refused(["echo x >> %s" % j, "echo x > %s" % j, "echo x>>%s" % j, "echo x | tee -a %s" % j, "cp a.jsonl %s" % j,
                      "mv a.jsonl %s" % j, "mv %s /tmp/gone" % j, "rm %s" % j, "rm -f %s.lock" % j,
                      "sed -i s/a/b/ %s" % j, "truncate -s 0 %s" % j, "ln -sf /x %s" % j, "echo x > %s.1" % j, "mv %s %s.1" % (j, j),
                      "cd %s && echo y >> ref-journal.jsonl" % self.state, "echo y >> to-journal", "bash -c 'echo y >> %s'" % j,
                      "echo y >> $QARGI_STATE/ref-journal.jsonl", "sudo rm %s" % j, "touch %s.lock" % j, "dd if=/dev/zero of=%s" % j])

    def test_reads_and_look_alikes_stay_allowed(self):
        j = self.jn
        for c in ("cat %s" % j, "grep -n agent %s" % j, "jq -c . %s" % j, "tail -n 5 %s" % j, "cp %s %s/run/out/j.jsonl" % (j, self.t),
                  "cat %s > %s/run/out/c.jsonl" % (j, self.t), "echo x > %s/ref-journals.md" % self.state, "echo x > %s/other.jsonl" % self.state):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))
        os.makedirs(os.path.join(self.t, "elsewhere"))
        p = os.path.join(self.t, "elsewhere/ref-journal.jsonl")
        self.assertEqual(self.call("Write", {"file_path": p}).returncode, 0)

    def test_the_journal_is_found_like_the_other_qargi_paths(self):
        home_state = os.path.join(self.home, ".qargi/state")
        qh = os.path.join(self.t, "qh/state")
        alt = os.path.join(self.t, "alt")
        for st, env in ((home_state, dict(QARGI_STATE=None)), (qh, dict(QARGI_STATE=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                        (alt, dict(QARGI_STATE=os.path.join(self.t, "alt")))):
            os.makedirs(st, exist_ok=True)
            p = st + "/ref-journal.jsonl"
            self.assertEqual(self.call("Write", {"file_path": p}, **env).returncode, 2, (p, env))
            self.assertEqual(self.bash("echo x >> %s" % p, **env).returncode, 2, (p, env))


class FailsClosed(unittest.TestCase):
    """An exception inside the guard is a refusal (exit 2 with the reason), never a silent pass or a bare crash (exit 1)."""
    def run_main(self, payload, patch=None):
        import importlib.util, io, contextlib
        spec = importlib.util.spec_from_file_location("qargi_guard_under_test", os.path.join(os.path.dirname(BIN), "..", "lib", "guard.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if patch:
            setattr(mod, patch[0], patch[1])
        err, old = io.StringIO(), sys.stdin
        sys.stdin = io.StringIO(payload)
        try:
            with contextlib.redirect_stderr(err):
                rc = mod.main()
        finally:
            sys.stdin = old
        return rc, err.getvalue()

    def test_a_forced_exception_is_exit_2(self):
        def boom(*a, **k):
            raise RuntimeError("forced")
        call = json.dumps({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        for name in ("blocked", "skill_refusal", "review_refusal"):
            rc, err = self.run_main(call, (name, boom))
            self.assertEqual(rc, 2, name)
            self.assertIn("qargi guard: internal error (RuntimeError: forced)", err)
            self.assertIn("refusing the call", err)
        rc, err = self.run_main(call)
        self.assertEqual((rc, err), (0, ""))

    def test_input_the_guard_cannot_read_is_exit_2_end_to_end(self):
        for inp in ({"tool_name": "Bash", "tool_input": {"command": 7}}, {"tool_name": "Bash", "tool_input": "ls"},
                    {"tool_name": "Edit", "tool_input": {"file_path": ["a"]}}, ["not", "an", "object"]):
            r = subprocess.run([BIN, "__guard"], input=json.dumps(inp), capture_output=True, text=True)
            self.assertEqual(r.returncode, 2, inp)
            self.assertIn("qargi guard: internal error", r.stderr)

    def test_the_member_definition_bounds_a_failing_hook(self):
        with open(os.path.join(os.path.dirname(BIN), "..", "agents", "member.md")) as f:
            text = f.read()
        self.assertIn('onFailure: "block"', text)
        self.assertRegex(text, r"(?m)^\s+timeout: \d+$")
        self.assertLess(text.index("onFailure"), text.index("\n---\n", 4))            # in the front matter
        self.assertIn("never change a skill", text.replace("\n", " "))


class MemoryTiers(unittest.TestCase):
    """The memory tiers are changed only by the lead: a member is refused `qargi memory init|move|split|merge|copy` however it is run,
    and writes under $QARGI_HOME/memory and ~/.qargi/memory. Reading and tiers|check|get|lint stay allowed."""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call
    REASON = "changes a memory tier and is not available to an agent; propose it in your report"

    def setUp(self):
        self.setUp_skills()
        self.qh = os.path.join(self.t, "qh")                              # QARGI_HOME
        self.mem = os.path.join(self.qh, "memory")
        self.home_mem = os.path.join(self.home, ".qargi", "memory")        # the default root
        for d in (self.mem + "/shared", self.mem + "/projects/demo", self.home_mem + "/shared", os.path.join(self.t, "elsewhere/memory")):
            os.makedirs(d)
        os.symlink(self.mem, os.path.join(self.clone, "to-memory"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_HOME", self.qh)
        return self.call_skills(tool, inp, cwd, **env)

    def refused(self, cmds, reason=None, **env):
        for c in cmds:
            res = self.bash(c, **env)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn(reason or self.REASON, res.stderr)

    def test_the_five_verbs_are_refused_however_they_are_run(self):
        forms = ("qargi %s", "/opt/q/bin/qargi %s", "bin/qargi %s", "sudo qargi %s", "cd src && qargi %s", "echo ok; qargi %s --approved go",
                 "bash -c 'qargi %s'", "sh -c \"cd /x && qargi %s\"", "eval 'qargi %s'", "echo $(qargi %s)", "echo `qargi %s`", "timeout 5 qargi %s",
                 "env FOO=1 qargi %s", "FOO=1 qargi %s", "(qargi %s)", "bash -lc 'qargi %s'", "nohup qargi %s", "command qargi %s", "true && qargi %s")
        cmds = []
        for v in ("init shared", "init repo --project demo", "move /roles/build/r.md --from project --to shared", "split A B --prefix /x", "merge A B", "copy A B --prefix /x",
                  "init shared --plan 0123456789ab --approved go"):
            cmds += [f % ("memory " + v) for f in forms]
        cmds += ["qargi 'memory' 'init' shared", "qargi mem\"\"ory move x", "qargi memory \\\ninit shared", "python3 bin/qargi memory init shared"]
        self.refused(cmds)

    def test_the_scripts_behind_the_verbs_are_refused_too(self):
        self.refused(["bash lib/memory.sh init shared", "lib/memory.sh split A B --prefix /x", "bash lib/memory.sh move /shared/a.md --from project --to shared",
                      "bash lib/tierwrite.sh init shared", "lib/tierwrite.sh move /shared/a.md --from project --to shared",
                      "python3 -I lib/tierplan.py plan-init shared --out /tmp/x", "python3 lib/tierplan.py apply /tmp/p.json",
                      "python3 -I lib/memplan.py apply /tmp/p.json", "python3 lib/memplan.py plan split --source a --target b --prefix /x --out f",
                      "bash -c 'python3 lib/tierplan.py apply p'", "sudo bash lib/tierwrite.sh init system"])

    def test_the_reading_verbs_and_look_alikes_stay_allowed(self):
        for c in ("qargi memory tiers", "qargi memory tiers --json --project demo", "qargi memory check", "qargi memory check --project demo", "qargi memory get memstore_X /a.md",
                  "qargi memory lint memstore_X", "/opt/q/bin/qargi memory check", "bash -c 'qargi memory tiers'", "env FOO=1 qargi memory check", "timeout 5 qargi memory check",
                  "python3 -I lib/tiers.py check --project demo", "bash lib/memory.sh get memstore_X /a.md", "bash lib/memory.sh lint memstore_X", "lib/memory.sh tiers",
                  "echo qargi memory init shared", "git log --grep 'memory init'", "grep -n 'memory move' README.md", "cat lib/tierwrite.sh", "ls lib/tierplan.py",
                  "qargi memories init", "qargi canon check memory init"):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_edit_tools_refuse_every_path_under_the_memory_root(self):
        for root in (self.mem, "to-memory"):
            for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path")):
                for p in (root + "/shared/README.md", root + "/projects/demo/CANON.md", root + "/new.md", root, "../../qh/memory/shared/x.md"):
                    for cls in ((), ("--class", "read-only")):
                        res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                             capture_output=True, text=True, env=dict(self.env_for(), QARGI_HOME=self.qh))
                        self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                        self.assertIn("qargi guard:", res.stderr)
                        self.assertIn("memory", res.stderr)

    def env_for(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf})
        return e

    def test_bash_writes_under_the_memory_root_are_refused(self):
        m = self.mem
        cmds = ["echo x > %s/shared/a.md" % m, "echo x>>%s/shared/a.md" % m, "echo x | tee %s/shared/a.md" % m, "cp a.md %s/shared/" % m, "cp -t %s/shared a.md" % m,
                "mv a.md %s/projects/demo/a.md" % m, "mv %s /tmp/gone" % m, "rm %s/shared/a.md" % m, "rm -rf %s" % m, "sed -i s/a/b/ %s/shared/a.md" % m,
                "touch %s/shared/new.md" % m, "mkdir %s/system" % m, "cd %s/shared && echo y > a.md" % m, "echo y > to-memory/shared/a.md",
                "bash -c 'echo y > %s/shared/a.md'" % m, "echo y > $QARGI_HOME/memory/shared/a.md", "install -m 644 a %s/shared/a.md" % m, "ln -sf /x %s/shared/a.md" % m,
                "find %s -name '*.md' -delete" % m]
        for c in cmds:
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)

    def test_the_default_root_is_protected_too(self):
        d = self.home_mem
        for c in ("echo x > %s/shared/a.md" % d, "rm -rf %s" % d, "cp a %s/shared/" % d, "echo x > ~/.qargi/memory/shared/a.md", "echo x > $HOME/.qargi/memory/shared/a.md"):
            res = self.bash(c, QARGI_HOME=None)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
        self.assertEqual(self.call("Write", {"file_path": d + "/shared/a.md"}, QARGI_HOME=None).returncode, 2)
        self.assertEqual(self.call("Write", {"file_path": d + "/shared/a.md"}).returncode, 2)        # protected whatever QARGI_HOME says

    def test_reads_stay_allowed(self):
        m = self.mem
        for c in ("cat %s/shared/a.md" % m, "ls %s" % m, "grep -rn x %s" % m, "cp %s/shared/a.md %s/run/out/" % (m, self.t), "cat %s/shared/a.md > %s/run/out/c.md" % (m, self.t),
                  "find %s -name '*.md'" % m, "cd %s && ls" % m, "cat to-memory/shared/a.md", "echo x > %s/memory-notes.md" % self.qh, "cat %s/shared/a.md" % self.home_mem):
            res = self.bash(c)
            self.assertEqual(res.returncode, 0, (c, res.stderr))

    def test_a_memory_folder_elsewhere_is_not_protected(self):
        p = os.path.join(self.t, "elsewhere/memory/x.md")
        self.assertEqual(self.call("Write", {"file_path": p}).returncode, 0)
        self.assertEqual(self.bash("echo x > %s" % p).returncode, 0)
        self.assertEqual(self.bash("echo x > %s/run/out/memory-r.md" % self.t).returncode, 0)


class HookProtocol(unittest.TestCase):
    """The hook protocol is data (CLAUDE_HOOK, or the barrier.hook of a definition): it turns the hook's JSON into a neutral Call, and the
    decisions see only that."""
    @staticmethod
    def load():
        import importlib.util
        spec = importlib.util.spec_from_file_location("qargi_guard_protocol", os.path.join(os.path.dirname(BIN), "..", "lib", "guard.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_the_claude_hook_data_makes_these_calls(self):
        g = self.load()
        for data, want in (({"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": "/w"}, ("shell", "Bash", "ls", "", "/w")),
                           ({"tool_input": {"command": "ls"}, "cwd": "/w"}, ("shell", None, "ls", "", "/w")),
                           ({"tool_name": "Edit", "tool_input": {"file_path": "a", "path": "b"}, "cwd": "/w"}, ("write", "Edit", "", "a", "/w")),
                           ({"tool_name": "NotebookEdit", "tool_input": {"notebook_path": "n"}, "cwd": "/w"}, ("write", "NotebookEdit", "", "n", "/w")),
                           ({"tool_name": "Read", "tool_input": {"file_path": "r"}, "cwd": "/w"}, ("read", "Read", "", "r", "/w")),
                           ({"tool_name": "Grep", "tool_input": {"path": "d", "pattern": "x"}, "cwd": "/w"}, ("search", "Grep", "", "d", "/w")),
                           ({"tool_name": "Glob", "tool_input": {"pattern": "*"}, "cwd": "/w"}, (None, "Glob", "", "", "/w")),
                           ({"tool_name": "Bash", "tool_input": None, "cwd": None}, ("shell", "Bash", "", "", os.getcwd()))):
            self.assertEqual(tuple(g.parse_call(g.CLAUDE_HOOK, data)), want, data)

    def test_the_shipped_claude_code_definition_carries_the_data_the_guard_has_built_in(self):
        path = os.path.join(os.path.dirname(BIN), "..", "lib", "providers", "claude-code.json")
        if not os.path.exists(path):
            self.skipTest("lib/providers/claude-code.json is not shipped yet")
        with open(path) as f:
            hook = json.load(f)["barrier"]["hook"]
        self.assertEqual(hook, self.load().CLAUDE_HOOK)

    def test_hook_data_that_can_never_refuse_is_not_used(self):
        """A refusal that exits like an allow and prints nothing a runtime reads as a denial would let every push and skill write through: the
        data that says so is a problem, whichever way it is written."""
        g = self.load()
        self.assertIsNone(g.hook_problem(g.CLAUDE_HOOK))
        for name in ("FAKEMD_HOOK", "FAKECLI_HOOK"):
            self.assertIsNone(g.hook_problem(globals()[name]), name)
        def with_deny(deny, allow=None):
            h = json.loads(json.dumps(g.CLAUDE_HOOK))
            h["deny"] = deny
            if allow is not None:
                h["allow"] = allow
            return h
        for deny, allow in (({"exit": 0, "stream": "stderr"}, None), ({"exit": 0, "stream": "stdout"}, None),
                            ({"exit": 2, "stream": "stderr"}, {"exit": 2}), ({"exit": 0, "stdout": {}}, None),
                            ({"exit": 0, "stdout": {"decision": "deny"}}, None), ({"exit": 3, "stdout": {"decision": 1, "reason": ["x", {"a": 2}]}}, None)):
            why = g.hook_problem(with_deny(deny, allow))
            self.assertIsNotNone(why, (deny, allow))
            self.assertIn("barrier.hook.", why)
        for deny, allow in (({"exit": 2, "stream": "stderr"}, None), ({"exit": 0, "stdout": {"decision": "deny", "reason": "{reason}"}}, None),
                            ({"exit": 3, "stdout": {"a": [{"b": "no: {reason}"}]}}, {"exit": 0})):
            self.assertIsNone(g.hook_problem(with_deny(deny, allow)), (deny, allow))

    def test_a_hook_input_that_cannot_be_read_is_an_error_not_a_pass(self):
        g = self.load()
        for data in ([], "ls", None, {"tool_name": "Bash", "tool_input": "ls"}, {"tool_name": "Bash", "tool_input": [1]}):
            with self.assertRaises(TypeError, msg=data):
                g.parse_call(g.CLAUDE_HOOK, data)


def runtime(name, **parts):
    """A schema 2 definition of a local runtime (what a library holds); parts are its sections: resources, barrier, ..."""
    d = {"schema": 2, "kind": "provider", "provider": name, "family": None, "surface": "local", "description": "a test runtime",
         "models": {"pattern": "^m-[a-z]+$", "tiers": {"*": {"model": "m-one", "alias": None, "verified_on": None, "source": "test"}}, "effort": None},
         "capabilities": {}, "resources": {}, "agents": None, "barrier": {"kind": "none"}}
    d.update(parts)
    return d


FAKEMD_HOOK = {"input": "json-stdin", "tool_pointer": "/event/tool", "command_pointer": "/event/args/cmd", "cwd_pointer": "/workdir",
               "path_pointers": ["/event/args/target"],
               "tool_names": {"shell": ["run_shell"], "write": ["patch_file", "create_file"], "read": ["open_file"], "search": ["grep_tree"]},
               "deny": {"exit": 0, "stdout": {"decision": "deny", "reason": "{reason}", "detail": ["{reason}", {"again": "x{reason}y"}]}}, "allow": {"exit": 0}}
FAKECLI_HOOK = {"input": "json-stdin", "tool_pointer": "/call/name", "command_pointer": "/call/input/command", "cwd_pointer": "/call/cwd",
                "path_pointers": {"write": ["/call/input/dest"], "read": ["/call/input/src", "/call/input/dir"]},
                "tool_names": {"shell": ["sh"], "write": ["put"], "read": ["get"], "search": ["find_in"]},
                "deny": {"exit": 3, "stream": "stdout"}, "allow": {"exit": 0}}


class ProviderHook(unittest.TestCase):
    """`qargi __guard --provider NAME` reads how that provider's hook hands over a call and how it denies from the provider's definition,
    and asks the same decisions. The runtimes here are definitions in a library; none of them is Claude Code."""
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home, self.conf = os.path.join(self.t, "home"), os.path.join(self.t, "conf")
        self.run = os.path.join(self.t, "run")
        self.clone, self.out = os.path.join(self.run, "clone"), os.path.join(self.run, "out")
        for d in ("home", "conf/packs/skills/s", "run/clone/src", "run/out"):
            os.makedirs(os.path.join(self.t, d))
        for name, text in (("ability", "build\n"), ("refs.before", "")):
            with open(os.path.join(self.run, name), "w") as f:
                f.write(text)
        self.define("fakemd", barrier={"kind": "hook", "hook": FAKEMD_HOOK})
        self.define("fakecli", barrier={"kind": "hook", "hook": FAKECLI_HOOK})

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def define(self, name, **parts):
        d = os.path.join(self.conf, "packs", "providers", name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "definition.json"), "w") as f:
            json.dump(runtime(name, **parts), f)
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "lib"))
        import provider as P
        with open(os.path.join(d, ".pack.json"), "w") as f:                         # sealed: a library pack counts only once it is
            json.dump({"kind": "provider", "sealed": True, "sha256": P.tree_hash(d)}, f)

    def run_guard(self, args, payload):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf})
        return subprocess.run([BIN, "__guard", *args], input=payload if isinstance(payload, str) else json.dumps(payload), capture_output=True, text=True, env=e)

    def md(self, tool, args, *more):
        return self.run_guard(["--provider", "fakemd", *more], {"event": {"tool": tool, "args": args}, "workdir": self.clone})

    def cli(self, name, inp, *more):
        return self.run_guard(["--provider", "fakecli", *more], {"call": {"name": name, "input": inp, "cwd": self.clone}})

    def denied_md(self, r):
        self.assertEqual((r.returncode, r.stderr), (0, ""), r)
        doc = json.loads(r.stdout)
        self.assertEqual(doc["decision"], "deny")
        self.assertEqual(doc["detail"], [doc["reason"], {"again": "x%sy" % doc["reason"]}])
        self.assertTrue(doc["reason"].startswith("qargi guard: "), doc)
        return doc["reason"]

    def test_a_json_deny_on_standard_output_with_exit_0(self):
        self.assertIn("Agents never push", self.denied_md(self.md("run_shell", {"cmd": "git push origin main"})))
        self.assertIn("gh is not available", self.denied_md(self.md("run_shell", {"cmd": "gh pr list"})))
        lib = os.path.join(self.conf, "packs/skills/s/SKILL.md")
        self.assertIn("a protected location", self.denied_md(self.md("run_shell", {"cmd": "echo x > %s" % lib})))
        self.assertIn("a protected location", self.denied_md(self.md("patch_file", {"target": lib})))
        self.assertIn("a protected location", self.denied_md(self.md("create_file", {"target": "~/.claude/skills/x/SKILL.md"})))
        self.assertIn("changes a skill and is not available to an agent", self.denied_md(self.md("run_shell", {"cmd": "qargi skill new x"})))

    def test_a_call_that_passes_is_exit_0_with_nothing_printed(self):
        for tool, args in (("run_shell", {"cmd": "ls -la && git status"}), ("patch_file", {"target": "src/a.go"}), ("open_file", {"target": "src/a.go"}),
                           ("grep_tree", {"target": "src"}), ("unknown_tool", {"cmd": "git push"}), ("run_shell", {})):
            r = self.md(tool, args)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), (tool, args))
        self.assertEqual(self.run_guard(["--provider", "fakemd"], "not json").returncode, 0)

    def test_the_names_and_pointers_are_the_providers_not_claudes(self):
        # Claude's tool names mean nothing to a provider that does not list them, and the provider's own are judged
        r = self.run_guard(["--provider", "fakemd"], {"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": self.clone})
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        r = self.run_guard([], {"event": {"tool": "run_shell", "args": {"cmd": "git push"}}})
        self.assertEqual((r.returncode, r.stdout), (0, ""))                  # and the default (Claude's) protocol cannot read fakemd's calls

    def test_a_call_that_names_no_tool_is_a_shell_command(self):
        r = self.run_guard(["--provider", "fakemd"], {"event": {"args": {"cmd": "git push"}}, "workdir": self.clone})
        self.assertIn("Agents never push", self.denied_md(r))

    def test_the_read_only_class_and_the_signing_key_are_held_through_the_provider_too(self):
        for tool, args in (("patch_file", {"target": "src/a.go"}), ("run_shell", {"cmd": "echo x > src/a.go"}), ("create_file", {"target": os.path.join(self.t, "e")})):
            r = self.md(tool, args)
            self.assertEqual((r.returncode, r.stdout), (0, ""), tool)
            self.assertIn("under the read-only class", self.denied_md(self.md(tool, args, "--class", "read-only")))
        self.assertEqual(self.md("create_file", {"target": os.path.join(self.out, "report.md")}, "--class", "read-only").stdout, "")
        os.makedirs(os.path.join(self.conf, "credentials"))
        key = os.path.join(self.conf, "credentials", "marshal_ed25519")
        open(key, "w").close()
        for tool, args in (("open_file", {"target": key}), ("grep_tree", {"target": os.path.dirname(key)}), ("run_shell", {"cmd": "cat " + key})):
            self.assertIn("signing key", self.denied_md(self.md(tool, args)))

    def test_a_stream_and_an_exit_status_of_the_definition(self):
        lib = os.path.join(self.conf, "packs/skills/s/SKILL.md")
        r = self.cli("put", {"dest": lib})
        self.assertEqual((r.returncode, r.stderr), (3, ""))
        self.assertIn("a protected location", r.stdout)
        self.assertTrue(r.stdout.startswith("qargi guard: ") and r.stdout.endswith("\n"), r.stdout)
        r = self.cli("sh", {"command": "git push"})
        self.assertEqual((r.returncode, r.stderr), (3, ""))
        self.assertIn("Agents never push", r.stdout)
        # a map of path pointers by kind: put reads dest only, get reads src then dir, find_in (a search) reads like get
        self.assertEqual(self.cli("put", {"src": lib}).stdout, "")
        self.assertEqual(self.cli("get", {"src": "src/a.go", "dir": lib}).stdout, "")
        os.makedirs(os.path.join(self.conf, "credentials"))
        open(os.path.join(self.conf, "credentials", "marshal_ed25519"), "w").close()
        self.assertIn("signing key", self.cli("find_in", {"dir": os.path.join(self.conf, "credentials")}).stdout)
        self.assertEqual(self.cli("get", {"dir": os.path.join(self.conf, "credentials")}).stdout, "")      # get is not a search: a directory is not the key

    def test_failures_are_refusals_in_the_providers_way(self):
        r = self.md("run_shell", {"cmd": 7})
        self.assertIn("internal error", self.denied_md(r))
        r = self.run_guard(["--provider", "fakemd"], {"event": "ls"})
        self.assertIn("internal error", self.denied_md(r))
        self.assertIn("unknown class", self.denied_md(self.md("run_shell", {"cmd": "ls"}, "--class", "root")))
        self.assertIn("unknown class", self.denied_md(self.md("run_shell", {"cmd": "ls"}, "--class")))
        r = self.cli("sh", {"command": 7})
        self.assertEqual((r.returncode, r.stderr), (3, ""))
        self.assertIn("internal error", r.stdout)

    def refused_before_judging(self, args, *words):
        r = self.run_guard(args, {"event": {"tool": "run_shell", "args": {"cmd": "ls"}}})
        self.assertEqual((r.returncode, r.stdout), (2, ""), r)
        self.assertTrue(r.stderr.startswith("qargi guard: "), r.stderr)
        for w in words:
            self.assertIn(w, r.stderr)

    def test_the_shipped_claude_code_definition_is_a_usable_hook(self):
        # --provider claude-code reads the data the file ships; it must judge as the built-in default does, not refuse every call
        def call(name, tool_input, *more):
            return self.run_guard(["--provider", "claude-code", *more], {"tool_name": name, "tool_input": tool_input, "cwd": self.clone})
        r = call("Bash", {"command": "git push origin main"})
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("Agents never push", r.stderr)
        for name, tool_input in (("Bash", {"command": "ls -la"}), ("Edit", {"file_path": "src/a.go"}), ("Read", {"file_path": "src/a.go"}), ("Grep", {"path": "src"})):
            r = call(name, tool_input)
            self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""), name)
        r = call("Write", {"file_path": os.path.join(self.t, "e")}, "--class", "read-only")
        self.assertEqual(r.returncode, 2)
        self.assertIn("under the read-only class", r.stderr)

    def test_a_provider_whose_hook_cannot_be_read_refuses_every_call(self):
        self.refused_before_judging(["--provider"], "--provider")
        self.refused_before_judging(["--provider", "nosuch"], "nosuch")
        self.refused_before_judging(["--provider", "../x"], "unknown provider")
        self.define("nobarrier")
        self.refused_before_judging(["--provider", "nobarrier"], "nobarrier", "hook")
        self.define("sandboxed", barrier={"kind": "sandbox-args"})
        self.refused_before_judging(["--provider", "sandboxed"], "sandboxed", "sandbox-args")
        self.refused_before_judging(["--provider", "claude-platform"], "claude-platform", "hook")    # shipped, a barrier of kind none: no hook data
        bad_hooks = (({k: v for k, v in FAKEMD_HOOK.items() if k != "tool_pointer"}, "tool_pointer"),
                     ({**FAKEMD_HOOK, "input": "argv"}, "input"),
                     ({**FAKEMD_HOOK, "command_pointer": "cmd"}, "command_pointer"),
                     ({**FAKEMD_HOOK, "path_pointers": "target"}, "path_pointers"),
                     ({**FAKEMD_HOOK, "path_pointers": {"edit": ["/a"]}}, "path_pointers"),
                     ({**FAKEMD_HOOK, "tool_names": {"shell": "run_shell"}}, "tool_names"),
                     ({**FAKEMD_HOOK, "tool_names": {"shell": ["x"], "write": ["x"]}}, "x"),
                     ({**FAKEMD_HOOK, "tool_names": {"ls": ["x"]}}, "tool_names"),
                     ({k: v for k, v in FAKEMD_HOOK.items() if k != "deny"}, "deny"),
                     ({**FAKEMD_HOOK, "deny": {"exit": 2}}, "deny"),
                     ({**FAKEMD_HOOK, "deny": {"exit": "2", "stream": "stderr"}}, "deny"),
                     ({**FAKEMD_HOOK, "deny": {"exit": 2, "stream": "file"}}, "deny"),
                     ({**FAKEMD_HOOK, "deny": {"exit": 0, "stdout": "no"}}, "deny"),
                     ({**FAKEMD_HOOK, "allow": {"exit": "0"}}, "allow"),
                     ({**FAKEMD_HOOK, "extra": 1}, "extra"))
        for n, (bad, word) in enumerate(bad_hooks):
            name = "bad%d" % n
            self.define(name, barrier={"kind": "hook", "hook": bad})
            self.refused_before_judging(["--provider", name], name, word)


    def test_hook_data_that_would_let_a_call_through_unjudged_is_refused(self):
        # incomplete data must not become "nothing to judge": a write tool with no path pointers reads no path (so the write is allowed),
        # and a hook with no shell tool judges no command. Each of these is refused before any call is judged, whatever the call is.
        no_pp = {k: v for k, v in FAKEMD_HOOK.items() if k != "path_pointers"}
        lib = os.path.join(self.conf, "packs/skills/s/SKILL.md")
        bad_hooks = (("nopp", no_pp, "path_pointers"),
                     ("emptypp", {**FAKEMD_HOOK, "path_pointers": []}, "path_pointers"),
                     ("emptymap", {**FAKEMD_HOOK, "path_pointers": {}}, "path_pointers"),
                     ("nowrite", {**FAKEMD_HOOK, "path_pointers": {"read": ["/event/args/target"]}}, "path_pointers"),
                     ("emptywrite", {**FAKEMD_HOOK, "path_pointers": {"write": [], "read": ["/event/args/target"]}}, "path_pointers"),
                     ("noread", {**FAKEMD_HOOK, "path_pointers": {"write": ["/event/args/target"]}}, "path_pointers"),
                     ("noshell", {**FAKEMD_HOOK, "tool_names": {k: v for k, v in FAKEMD_HOOK["tool_names"].items() if k != "shell"}}, "shell"),
                     ("emptyshell", {**FAKEMD_HOOK, "tool_names": {**FAKEMD_HOOK["tool_names"], "shell": []}}, "shell"),
                     ("notools", {**FAKEMD_HOOK, "tool_names": {}}, "shell"))
        for name, bad, word in bad_hooks:
            self.define(name, barrier={"kind": "hook", "hook": bad})
            self.refused_before_judging(["--provider", name], name, word)
            r = self.run_guard(["--provider", name], {"event": {"tool": "patch_file", "args": {"target": lib}}, "workdir": self.clone})
            self.assertEqual(r.returncode, 2, (name, r))
            self.assertIn("hook protocol", r.stderr)

    def test_hook_data_that_names_no_tool_of_a_kind_needs_no_pointers_for_it(self):
        # the shell tool is required; a kind with no tools (here: no write and no search tool) needs no path pointers of its own
        hook = {**FAKEMD_HOOK, "tool_names": {"shell": ["run_shell"], "read": ["open_file"]}, "path_pointers": {"read": ["/event/args/target"]}}
        self.define("readonly-ish", barrier={"kind": "hook", "hook": hook})
        r = self.run_guard(["--provider", "readonly-ish"], {"event": {"tool": "run_shell", "args": {"cmd": "git push"}}, "workdir": self.clone})
        self.assertEqual(r.returncode, 0, r)
        self.assertIn("Agents never push", self.denied_md(r))
        self.define("search-via-read", barrier={"kind": "hook", "hook": {**hook, "tool_names": {**hook["tool_names"], "search": ["grep_tree"]}}})
        self.assertEqual(self.run_guard(["--provider", "search-via-read"], {"event": {"tool": "grep_tree", "args": {"target": "src"}}, "workdir": self.clone}).returncode, 0)


class ProviderRoots(unittest.TestCase):
    """The skills and agents directories the guard protects are the ones the provider definitions name (resources.skills and
    resources.agents: project_dir and user_dir), whatever runtime they belong to."""
    setUp_skills, tearDown, bash, call = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call      # the same fixture, not its tests
    FAKECLI = {"skills": {"project_dir": ".agents/skills", "user_dir": "~/.fakecli/skills", "items": "dir-per-item", "entry": "SKILL.md",
                          "link": {"project": "dir-symlink", "user": "none"}},
               "agents": {"project_dir": ".fake/agents", "user_dir": "~/.fake/agents", "items": "file-per-item", "ext": ".toml",
                          "link": {"project": "none", "user": "none"}},
               "settings": {"files": [{"scope": "user", "path": "~/.fake/config.toml", "format": "toml"}], "allow_pointer": None},
               "memory": {"user_dir": "~/.fake/memory", "link": {"user": "dir-symlink"}}}

    def setUp(self):
        self.setUp_skills()
        for d in ("home/.fakecli/skills/x", "home/.fake/agents", "home/.claude/plugins", "proj/.agents/skills/p", "proj/.fake/agents", "proj/.fake/other",
                  "run/clone/.agents/skills/p"):
            os.makedirs(os.path.join(self.t, d), exist_ok=True)

    def define(self, name, resources, raw=None):
        d = os.path.join(self.conf, "packs", "providers", name)
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "definition.json"), "w") as f:
            if raw is not None:
                f.write(raw)
            else:
                json.dump(runtime(name, resources=resources), f)

    def refused(self, c):
        r = self.bash(c)
        self.assertEqual(r.returncode, 2, (c, r.stderr))
        self.assertIn("a protected location (skills, the pack library, credentials)", r.stderr, c)

    def test_without_a_definition_that_names_them_those_directories_are_not_protected(self):
        for c in ("echo y > ~/.fakecli/skills/x/SKILL.md", "echo y > ~/.fake/agents/m.toml", "echo y > %s/.agents/skills/p/SKILL.md" % self.proj,
                  "echo y > %s/.fake/agents/m.toml" % self.proj, "rm -rf %s/.fake" % self.proj):
            self.assertEqual(self.bash(c).returncode, 0, c)

    def test_the_directories_of_a_definition_in_the_library_are_protected(self):
        self.define("fakecli", self.FAKECLI)
        p = self.proj
        for c in ("echo y > ~/.fakecli/skills/x/SKILL.md", "echo y > $HOME/.fake/agents/m.toml", "rm -rf ~/.fakecli/skills/x", "cp a ~/.fake/agents/",
                  "echo y > %s/.agents/skills/p/SKILL.md" % p, "echo y > %s/.fake/agents/m.toml" % p, "cd %s && echo y > .fake/agents/m.toml" % p,
                  "touch %s/sub/.agents/skills/q" % p, "rm -rf %s/.fake" % p, "rm -rf %s/.agents" % p, "mv %s/.fake /tmp/gone" % p,
                  "rm -rf ../../proj/.agents/skills/p", "tee %s/.fake/agents/n.toml < /dev/null" % p):
            self.refused(c)
        for tool, path in (("Write", "~/.fakecli/skills/x/SKILL.md"), ("Edit", "~/.fake/agents/m.toml"), ("NotebookEdit", p + "/.agents/skills/p/n.ipynb"),
                           ("Write", p + "/.fake/agents/m.toml"), ("Write", "../../proj/.agents/skills/p/SKILL.md")):
            r = self.call(tool, {"notebook_path" if tool == "NotebookEdit" else "file_path": path})
            self.assertEqual(r.returncode, 2, (tool, path, r.stderr))
            self.assertIn("a protected location", r.stderr)
            self.assertIn("%s on %s would change" % (tool, path), r.stderr)

    def test_only_those_directories_are_protected(self):
        self.define("fakecli", self.FAKECLI)
        for c in ("echo y > ~/.fakecli/other.txt", "echo y > ~/.fake/config.toml", "echo y > ~/.fake/memory/m.md", "echo y > %s/.agents/other" % self.proj,
                  "echo y > %s/.fake/other/x" % self.proj, "echo y > %s/agents/m.toml" % self.proj, "rm -rf %s/.fake/other" % self.proj,
                  "ls ~/.fakecli/skills; cat %s/.fake/agents/m.toml" % self.proj):
            self.assertEqual(self.bash(c).returncode, 0, c)

    def test_inside_the_clone_they_are_the_work_product_as_the_claude_ones_are(self):
        self.define("fakecli", self.FAKECLI)
        for c in ("echo y > .agents/skills/p/SKILL.md", "mkdir -p .fake/agents && touch .fake/agents/m.toml", "rm -rf .agents", "rm -rf .claude"):
            self.assertEqual(self.bash(c).returncode, 0, c)
        os.symlink(os.path.join(self.home, ".fakecli/skills"), os.path.join(self.clone, "to-user"))
        self.refused("echo y > to-user/x/SKILL.md")                       # a link that leads out of the clone to a protected one is followed

    def test_the_claude_directories_stay_protected_beside_them(self):
        self.define("fakecli", self.FAKECLI)
        for c in ("echo y > ~/.claude/skills/x/SKILL.md", "echo y > ~/.claude/agents/m.md", "echo y > ~/.claude/plugins/p.json",
                  "echo y > %s/.claude/skills/p/SKILL.md" % self.proj, "rm -rf %s/.claude" % self.proj):
            self.refused(c)
        self.assertEqual(self.bash("echo x > %s/home/.claude/settings.json" % self.t).returncode, 2)      # the lead's own settings are no member-owned directory
        self.assertEqual(self.bash("echo x > %s/home/.claude/history.jsonl" % self.t).returncode, 0)

    def test_a_definition_with_an_unusable_path_protects_nothing_by_it(self):
        res = {"skills": {"project_dir": "../up/skills", "user_dir": "/etc/skills", "items": "dir-per-item"},
               "agents": {"project_dir": "/abs/agents", "user_dir": "relative/agents", "items": "file-per-item"}, "mcp": None}
        self.define("odd", res)
        self.define("empty", {})
        self.define("onlyuser", {"skills": {"user_dir": "~/.only/skills", "items": "dir-per-item"}})
        self.assertEqual(self.bash("echo y > /etc/skills/x; echo y > relative/agents/m; echo y > %s/up/skills/x" % self.t).returncode, 0)
        self.refused("echo y > ~/.only/skills/x")

    def test_a_definition_that_cannot_be_read_is_skipped_with_a_note_and_the_others_still_protect(self):
        # one broken definition in the library must not make the guard refuse every write: its directories are unknown, the rest are not
        self.define("fakecli", self.FAKECLI)
        self.define("garbled", None, raw="{not json")
        self.define("wrongname", None, raw=json.dumps(runtime("someone-else", resources={"skills": {"project_dir": ".elsewhere/skills"}})))
        r = self.bash("echo y > %s/notes.txt" % self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr.count("qargi guard: "), 1, r.stderr)                 # one note, not one per definition or per path
        self.assertIn("skipped", r.stderr)
        self.assertIn("garbled", r.stderr)
        self.assertIn("wrongname", r.stderr)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.proj, "notes.txt")}).returncode, 0)
        for c in ("ls -la", "cat %s/notes.txt" % self.proj, "git status", "echo hi"):              # a call that writes nowhere needs no roots
            r = self.bash(c)
            self.assertEqual((r.returncode, r.stderr), (0, ""), c)
        self.assertEqual(self.bash("git push").returncode, 2)
        # the definitions that load keep their roots, and so does Claude Code
        for c in ("echo y > ~/.fakecli/skills/x/SKILL.md", "echo y > %s/.fake/agents/m.toml" % self.proj, "echo y > ~/.claude/skills/x/SKILL.md",
                  "echo y > %s/.claude/skills/p/SKILL.md" % self.proj, "rm -rf %s/.claude" % self.proj):
            self.refused(c)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.proj, ".fake", "agents", "m.toml")}).returncode, 2)

    def test_the_claude_directories_stay_protected_when_their_definition_clashes_or_is_broken(self):
        # a library definition with the name of a shipped one makes both unusable (a clash); the Claude Code directories are still held
        self.define("claude-code", {"skills": {"project_dir": ".other/skills", "items": "dir-per-item"}})
        r = self.bash("echo y > %s/notes.txt" % self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("claude-code", r.stderr)
        for c in ("echo y > ~/.claude/skills/x/SKILL.md", "echo y > ~/.claude/agents/m.md", "echo y > %s/.claude/skills/p/SKILL.md" % self.proj,
                  "echo y > %s/.claude/agents/m.md" % self.proj, "rm -rf %s/.claude" % self.proj):
            self.refused(c)

    def test_a_name_defined_twice_is_skipped_with_a_note_too(self):
        self.define("claude", {})                                         # the shipped provider's name
        r = self.bash("echo y > %s/notes.txt" % self.proj)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("defined twice", r.stderr)
        self.refused("echo y > %s/.claude/skills/p/SKILL.md" % self.proj)


class RuntimeRender(unittest.TestCase):
    """$DA_STATE/render/<project>/<runtime> is where the renders of every runtime go (skills, tools, members): instructions a session follows,
    changed only by the lead."""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call

    def setUp(self):
        self.setUp_skills()
        self.state = os.path.join(self.t, "state")
        self.render = os.path.join(self.state, "render", "proj", "fakecli")
        os.makedirs(os.path.join(self.render, "agents"))
        os.symlink(self.render, os.path.join(self.clone, "to-render"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_STATE", self.state)
        return self.call_skills(tool, inp, cwd, **env)

    def test_writes_under_the_render_directory_are_refused(self):
        r = self.render
        for tool, key, p in (("Write", "file_path", r + "/agents/m.toml"), ("Edit", "file_path", "to-render/agents/m.toml"), ("NotebookEdit", "notebook_path", r + "/n.ipynb"),
                             ("Write", "file_path", os.path.join(self.state, "render")), ("Write", "file_path", "../../state/render/proj/x")):
            for cls in ((), ("--class", "read-only")):
                res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}), capture_output=True, text=True,
                                     env={**os.environ, "HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
                self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                self.assertIn("the render of a project's skills, tools and members that a runtime loads", res.stderr)
                self.assertIn("changed only by the lead", res.stderr)
        for c in ("echo x > %s/agents/m.toml" % r, "cp a.md %s/agents/" % r, "rm -rf %s/agents" % r, "rm -rf %s/render" % self.state, "echo x > to-render/agents/m.toml",
                  "mv a.md %s/x.md" % r, "cd %s && touch n" % r, "sed -i s/a/b/ %s/agents/m.toml" % r):
            res = self.bash(c, QARGI_STATE=self.state)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("the render of a project's skills, tools and members that a runtime loads", res.stderr)

    def test_reading_it_and_writing_beside_it_stay_allowed(self):
        r = self.render
        for c in ("cat %s/agents/m.toml" % r, "ls %s" % r, "grep -rn x %s" % r, "echo x > %s/renders.txt" % self.state, "echo x > %s/run/out/render-r.md" % self.t,
                  "cp %s/agents/m.toml %s/run/out/" % (r, self.t)):
            res = self.bash(c, QARGI_STATE=self.state)
            self.assertEqual(res.returncode, 0, (c, res.stderr))


class ProviderVerbs(unittest.TestCase):
    """The provider definitions are the user's: a member is refused every verb that changes them (new, import, seal, remove, rename,
    enable, disable, attest and accept, and any verb that is added) and keeps the ones that only read."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call
    LIFECYCLE = ("new fakecli", "import ./fakecli", "seal fakecli", "remove fakecli", "rename fakecli other", "enable fakecli --project p", "disable fakecli",
                 "attest fakecli read_only_barrier --asked x", "unseal fakecli", "invented x",
                 "new mine --kind extension --from claude-code", "import ./fakecli --name x --ref main --path sub", "import ./fakecli --plan 0123456789ab --approved go --approve-exec adapter,renderers/agent",
                 "seal fakecli --plan 0123456789ab --approved go --approve-exec adapter", "remove fakecli --plan 0123456789ab --approved go",
                 "enable p addon --plan 0123456789ab --approved go --approve-exec verbs/resume", "disable p addon --plan 0123456789ab --approved go",
                 "attest fakecli mcp --asked x --did y --result pass --cost-cents 0 --cleanup z --plan 0123456789ab --approved go")
    FORMS = ("qargi provider %s", "/opt/q/bin/qargi provider %s", "sudo qargi provider %s", "cd src && qargi provider %s", "echo ok; qargi provider %s --approved go",
             "bash -c 'qargi provider %s'", "eval 'qargi provider %s'", "echo $(qargi provider %s)", "env FOO=1 qargi provider %s", "timeout 5 qargi provider %s",
             "bash lib/provider.sh %s", "python3 -I lib/provider.py %s", "./lib/provider.py %s", "/opt/q/lib/provider.py %s")

    def test_refuses_the_lifecycle_verbs_in_every_form(self):
        for v in self.LIFECYCLE:
            for form in self.FORMS:
                c = form % v
                r = self.bash(c)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn("qargi provider %s changes the provider definitions and is not available to an agent" % v.split()[0], r.stderr, c)
                self.assertIn("qargi guard:", r.stderr)

    def test_accept_keeps_its_own_sentence(self):
        r = self.bash("qargi provider accept claude --surface cloud --no-barrier --asked x")
        self.assertEqual(r.returncode, 2)
        self.assertIn("qargi provider accept records that you accept a provider with no read-only barrier and is not available to an agent", r.stderr)
        self.assertNotIn("changes the provider definitions", r.stderr)

    def test_check_and_adapter_run_are_refused_with_their_own_reasons(self):
        """check records what it verified (and runs a sealed pack's code); adapter-run runs the adapter, and its --check copies a library adapter."""
        for tail, text in (("check fakecli", "qargi provider check records what it verified"), ("check ./fakecli --project p", "qargi provider check records what it verified"),
                           ("adapter-run fakecli local spawn", "qargi provider adapter-run runs the adapter"),
                           ("adapter-run fakecli local spawn --check", "qargi provider adapter-run runs the adapter"),
                           ("adapter-run --check fakecli cloud resume", "qargi provider adapter-run runs the adapter")):
            for form in self.FORMS:
                c = form % tail
                r = self.bash(c)
                self.assertEqual(r.returncode, 2, c)
                self.assertIn(text, r.stderr, c)

    def test_every_provider_verb_of_the_help_is_judged_as_the_list_of_reading_verbs_says(self):
        """A verb that commands.py lists is allowed exactly when PROVIDER_READ has it: a new verb cannot be allowed by being forgotten."""
        sys.path.insert(0, os.path.join(os.path.dirname(BIN), "..", "lib"))
        import commands as C
        import guard as G
        verbs = sorted(C.COMMANDS["provider"]["verbs"])
        self.assertIn("model", verbs)
        self.assertIn("check", verbs)
        for v in verbs:
            r = self.bash("qargi provider %s x" % v)
            self.assertEqual(r.returncode, 0 if v in G.PROVIDER_READ else 2, (v, r.stderr))

    def test_lets_the_verbs_that_only_read_through(self):
        for c in ("qargi provider model claude-code local balanced", "bash -c 'qargi provider model claude-platform cloud fast'", "python3 -I lib/provider.py model claude-code local deep",
                  "qargi provider", "qargi provider list", "qargi provider show claude --json", "qargi provider effective claude local skills",
                  "qargi provider require-barrier claude cloud --project p", "qargi provider skills-dirs", "qargi provider of p --surface local", "qargi provider layout claude",
                  "qargi provider layout claude user_skills_dir", "qargi provider require-skills claude", "qargi provider launch claude /r", "python3 -I lib/provider.py list",
                  "qargi provider notes", "qargi provider notes spawn", "qargi provider notes spawn --project p", "qargi provider notes --project p",
                  "python3 -I lib/provider.py notes spawn", "bash -c 'qargi provider notes spawn'", "qargi provider addenda claude-platform cloud", "python3 -I lib/provider.py addenda claude-code local",
                  "echo qargi provider seal x", "grep -n 'provider attest' lib/provider.py", "cat provider.sh"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))


class BashText(unittest.TestCase):
    """The guard reads a Bash command as the plain split reads it: the line is cut at every ; && || | & and newline, inside quotes, comments and heredocs
    too, and a $( ), <( ), >( ) or backtick substitution is a command of its own. A refused verb written anywhere a command could start is refused, text or
    not; a member writes a message to a file and commits it with `git commit -F FILE`. The table is read as one: the failures are listed together."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call
    maxDiff = None

    REFUSED = (
        "qargi packs seed",
        "x; qargi upgrade",
        "echo hi && qargi provider enable x",
        "echo hi || qargi upgrade",
        "echo hi | qargi upgrade",
        'bash -c "qargi upgrade"',
        'eval "qargi upgrade"',
        "bash -c \"echo hi; qargi upgrade\" ; ls",
        "cat <<E | bash\nqargi upgrade\nE",
        "cat <<'E' | bash\nqargi upgrade\nE",
        "cat <<'E' | python3\nqargi upgrade\nE",
        "bash <<'E'\nqargi upgrade\nE",
        "sh <<E\nqargi upgrade\nE",
        "sudo bash <<'E'\nqargi upgrade\nE",
        "python3 <<'E'\nqargi upgrade\nE",
        "eval \"$(cat <<'E'\nqargi upgrade\nE\n)\"",
        "while read l; do eval \"$l\"; done <<'E'\nqargi upgrade\nE",
        "cat > s.sh <<'E'\nqargi upgrade\nE\nbash s.sh",
        "cat > s.sh <<'E'\nqargi upgrade\nE\nsource ./s.sh",
        "cat <<E\n$(qargi upgrade)\nE",
        "cat <<E\n`qargi upgrade`\nE",
        "cat <<'E' ; qargi upgrade\nhello\nE",
        'echo "$(qargi upgrade)"',
        'echo "`qargi upgrade`"',
        'echo "a; $(qargi upgrade)"',
        'git commit -m "$(qargi upgrade)"',
        'git commit -m "x $(cat <<\'E\'\nhi\nE\n; qargi upgrade)"',
        "echo $(qargi upgrade)",
        "echo `qargi upgrade`",
        "x=$(qargi upgrade)",
        "diff <(qargi upgrade) x",
        "if true; then qargi upgrade; fi",
        "if qargi upgrade; then echo; fi",
        "for i in 1; do qargi upgrade; done",
        "while true; do qargi upgrade; done",
        "{ qargi upgrade; }",
        "(qargi upgrade)",
        "( cd x; qargi upgrade )",
        "! qargi upgrade",
        "case x in x) qargi upgrade;; esac",
        "echo \"$(case x in x) qargi upgrade;; esac)\"",
        "if true; then\n  qargi upgrade\nfi",
        "sleep 1 & qargi upgrade",
        "> /dev/null qargi upgrade",
        "FOO=1 qargi upgrade",
        "command qargi upgrade",
        '"qarg"i upgrade',
        "q\\argi upgrade",
        "'qargi' upgrade",
        "\\qargi upgrade",
        "exec qargi upgrade",
        "time qargi upgrade",
        "sudo qargi upgrade",
        "nohup qargi upgrade",
        "env -i qargi upgrade",
        "timeout 5 qargi upgrade",
        "xargs qargi upgrade",
        "echo hi # it's late\nqargi upgrade",
        "echo hi # it's\nqargi packs seed # don't",
        "echo \\\\\nqargi upgrade",
        "echo hi \\\n; qargi upgrade",
        "echo 'unclosed; qargi upgrade",
        "echo \"unclosed; qargi upgrade",
        "echo $'a\\'b'; qargi upgrade",
        "echo '1' \"2\"; qargi upgrade",
        'echo "a\nb"\nqargi upgrade',
        'echo "$(echo "x; y")"; qargi upgrade',
        "cat <<E; qargi upgrade\nx\nE",
        "echo `echo \\`qargi upgrade\\``",
        "cat <<'E' | while read l; do eval \"$l\"; done\nqargi upgrade\nE",
        "f() { sh; }; f <<'E'\nqargi upgrade\nE",
        "cat <<'E' > \"$f\"\nqargi upgrade\nE\nbash \"$f\"",
        "cat <<'E' > s.py\nqargi upgrade\nE\npython3 s.py",
        "cat <<'E' > s.sh\nqargi upgrade\nE\nchmod +x s.sh && ./s.sh",
        "f() { qargi upgrade; }; f",
        "until false; do qargi upgrade; done",
    )


    # the same text, now refused: the quotes and the heredocs do not hide a verb
    AS_TEXT = (
        'git commit -m "Fix docs\n\nqargi packs seed now refuses X"',
        'git commit -m "Docs; qargi packs seed is lead-only"',
        "git commit -m 'Docs; qargi packs seed is lead-only'",
        "echo 'run it; qargi upgrade later'",
        "cat > notes.txt <<'E2'\nqargi provider enable x\nE2",
        "cat <<'E' | tee notes.txt\nqargi upgrade\nE",
        "echo '$(qargi upgrade)'",
    )

    def verdicts(self, cmds):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            return list(zip(cmds, ex.map(self.bash, cmds)))

    def test_a_refused_verb_in_the_place_of_a_command_is_refused_however_it_is_dressed(self):
        wrong = [c for c, r in self.verdicts(self.REFUSED) if r.returncode != 2]
        self.assertEqual(wrong, [], "allowed, but a command")

    def test_a_refused_verb_in_quoted_text_is_refused_too_and_the_sentence_says_what_to_do(self):
        results = self.verdicts(self.AS_TEXT)
        self.assertEqual([c for c, r in results if r.returncode != 2], [], "allowed")
        for c, r in results:
            self.assertIn("git commit -F FILE", r.stderr, c)
            self.assertIn("inside quotes and heredocs too", r.stderr, c)

    def test_a_message_in_a_file_is_the_way_to_commit_text_about_a_verb(self):
        for c in ("git commit -F msg.txt", "git commit -F msg.txt && git log --oneline -1", "git log --grep=upgrade --oneline", "git commit -m 'Docs: the upgrade verb'",
                  "grep -rn 'qargi packs seed' .", "echo hi # then qargi upgrade"):                 # a verb not at the start of a command is only an argument
            self.assertEqual(self.bash(c).returncode, 0, c)

    def test_a_refusal_that_is_not_about_a_verb_in_text_adds_no_such_advice(self):
        r = self.bash("echo hi")
        self.assertEqual(r.returncode, 0)
        r = self.bash("qargi upgrade")                                  # no quote, no heredoc: nothing to say about text
        self.assertEqual(r.returncode, 2)
        self.assertNotIn("git commit -F FILE", r.stderr)

    def test_the_publishing_barrier_reads_commands_too(self):
        for c in ('echo "$(gh api x)"', "if true; then git push; fi", "(git push)", "{ git push; }", "echo x | sh -c 'git push'", "cat <<E | sh\ngit push\nE",
                  "echo a & gh pr list", 'git commit -m "Fix: a; gh api x"', "echo 'then git push; gh pr list'", "cat <<'E' > n.txt\ngit push\nE", "sh -c 'git push'",
                  "bash -c \"git push\"", "eval git push", "cat <<<\"$(git push)\"", "diff <(git push) x"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, (c, r.stderr))
            self.assertIn("Agents never push", r.stderr)
        self.assertEqual(self.bash("grep -n 'ssh host' f").returncode, 0)               # one command whose program is grep


class _Judge:
    """guard.py of any revision, loaded by itself with the modules of its own lib, so that two revisions can judge one command in one process.
    judge(command, cls) is the refusal, or a sentence for an exception (the hook refuses on one), or None."""
    managed = []

    def __init__(self, lib, name, cwd):
        self.lib, self.cwd, self.mods = lib, cwd, {}
        _Judge.managed.append(lib)
        self.m = self.run(lambda: self.load(name))

    def load(self, name):
        spec = importlib.util.spec_from_file_location(name, os.path.join(self.lib, "guard.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m

    @staticmethod
    def owned(lib):
        return {k: v for k, v in list(sys.modules.items()) if getattr(v, "__file__", None) and os.path.dirname(os.path.abspath(v.__file__)) == lib}

    def run(self, fn):
        stashed = {}
        for lib in _Judge.managed:
            stashed.update(self.owned(lib))
        for k in stashed:
            sys.modules.pop(k, None)
        sys.modules.update(self.mods)
        sys.path.insert(0, self.lib)
        try:
            return fn()
        finally:
            self.mods = self.owned(self.lib)
            for k in self.mods:
                sys.modules.pop(k, None)
            sys.modules.update(stashed)
            while self.lib in sys.path:
                sys.path.remove(self.lib)

    def judge(self, command, cls=""):
        def go():
            self.m.CLASS = cls
            try:
                return self.m.judge(self.m.Call("shell", "Bash", command, "", self.cwd))
            except Exception as e:                               # the hook ends in a refusal on an exception
                return "exception %s: %s" % (type(e).__name__, e)
        return self.run(go)


def old_lib(test, rev="2b41028"):
    """The lib directory of the repository at rev (the guard whose plain split on every separator is the conservative reading), or skip the test."""
    root = os.path.dirname(os.path.dirname(BIN))
    r = subprocess.run(["git", "-C", root, "archive", rev, "lib"], capture_output=True)
    if r.returncode:
        test.skipTest("the history before %s is not available here (%s)" % (rev, r.stderr.decode(errors="replace").strip()[:100]))
    d = tempfile.mkdtemp()
    test.addCleanup(shutil.rmtree, d, True)
    tar = tarfile.open(fileobj=io.BytesIO(r.stdout))
    try:
        tar.extractall(d, filter="data")
    except TypeError:
        tar.extractall(d)
    return os.path.join(d, "lib")


class ReviewedReading(unittest.TestCase):
    """The adversarial review of the Bash reader: commands that run a refused verb or git push in a form a lighter reading of the text would miss (a comment
    that starts after an escaped blank, a heredoc inside ${ }, a trap, an alias, an eval ...). The plain split on every separator refuses them all."""
    setUp, tearDown, bash, call = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call
    maxDiff = None

    REFUSED = (
        'echo a\\ #; qargi upgrade',
        'echo a\\\n#b; qargi upgrade',
        'echo a\\\t#b; git push',
        'echo ${x/<<E/y}\nqargi upgrade\nE/y}',
        ': ${x:-<<E}\ngit push\nE}',
        'trap "true; qargi upgrade; true" EXIT',
        'trap "true; git push; true" EXIT',
        'X="true; qargi upgrade; true"; eval $X',
        'X="true; git push origin x; true"\neval $X',
        'sudo -u root sh -c "true; qargi upgrade; true"',
        'env -C /tmp sh -c "true; qargi upgrade; true"',
        'timeout -s KILL 5 sh -c "true; git push; true"',
        'find . -maxdepth 0 -exec sh -c "true; qargi upgrade; true" \\;',
        'perl -e \'system "true; qargi upgrade; true"\'',
        'python3 -c "import os; os.system(\'true; qargi upgrade; true\')"',
        'awk \'BEGIN{system("true; qargi upgrade; true")}\'',
        'busybox sh -c "true; qargi upgrade; true"',
        'fish -c "true; qargi upgrade; true"',
        'script -qc "true; qargi upgrade; true" /dev/null',
        'flock /tmp/l -c "true; qargi upgrade; true"',
        'su -c "true; qargi upgrade; true"',
        'git rebase --exec "true; qargi upgrade; true" HEAD~1',
        'git -c alias.z="!true; qargi upgrade; true" z',
        'watch -n1 "true; qargi upgrade; true"',
        'echo "true; qargi upgrade; true" > a.sh; sh a.sh',
        "cat > a <<'E'\nqargi upgrade\nE\ncp a b; sh b",
        "cat > a <<'E'\nqargi upgrade\nE\nbash <a",
        "cat > a <<'E'\nqargi upgrade\nE\nbash 0<a",
        "cat > a <<'E'\nqargi upgrade\nE\n. <(cat a)",
        "cat > a <<'E'\ngit push\nE\nbash <(cat a)",
        "cat <<'E' | tee a >/dev/null\nqargi upgrade\nE\nsh a",
        "cat > a <<'E'\nqargi upgrade\nE\nsh a*",
        "cat > a <<'E'\nqargi upgrade\nE\nfind . -name a -exec sh {} \\;",
        "cat > Makefile <<'E'\nall:\n\tqargi upgrade\nE\nmake",
        "cat > .git/hooks/pre-commit <<'E'\nqargi upgrade\nE\nchmod +x .git/hooks/pre-commit; git commit -m x",
        'cat > a <<E\nqargi upgrade\nE\nsh ./"a"',
        'cat > a <<E\ngit push\nE\nchmod +x a; PATH=.:$PATH; a',
        'cat > a <<E\ngit push\nE\nmv a b && sh b',
        "alias z='true; qargi upgrade; true'\nz",
        'f() { eval "$1"; }; f "true; qargi upgrade; true"',
        'while read l; do eval "$l"; done <<\'E\'\nqargi upgrade\nE',
        'cat <<E\n`qargi upgrade`\nE',
        '"qargi" "upgrade"',
        "q'a'rgi upgrade",
        'command -p qargi upgrade',
        'exec qargi upgrade',
        'nohup qargi upgrade &',
        '{ qargi upgrade; }',
        'time qargi upgrade',
        'x=1 y=2 qargi upgrade',
        "echo x # '\nqargi upgrade",
        'echo \'x\' #"\ngit push',
        'echo hi\nqargi upgrade',
        'echo hi\ngit push',
        "shopt -s expand_aliases\nalias z='true; qargi upgrade; true'\nz",
        'for ((i=1<<2;i<0;i++)); do :; done\nqargi upgrade\n2',
        'echo $[1<<2]\nqargi upgrade\n2]',
        'env -S "sh -s" <<\'E\'\nqargi upgrade\nE',
        "stdbuf -oL sh <<'E'\ngit push\nE",
        'builtin eval "$(cat)" <<\'E\'\nqargi upgrade\nE',
        'echo "true; qargi upgrade; true" | stdbuf -oL sh',
        "ionice -c3 bash <<'E'\nqargi upgrade\nE",
        "cat > a <<'E'\nqargi upgrade\nE\nBASH_ENV=a bash -c true",
        "cat > a <<'E'\nqargi upgrade\nE\nbash --rcfile a -i </dev/null",
        'cat > a <<\'E\'\nqargi upgrade\nE\nPROMPT_COMMAND=". ./a" bash -i </dev/null',
        'mapfile -t a <<\'E\'\nqargi upgrade\nE\n"${a[@]}"',
        "read -r a b <<'E'\nqargi upgrade\nE\n$a $b",
        "cat > .git/hooks/pre-commit <<'E'\nqargi upgrade\nE\ngit commit -m x",
        "x='a[$(qargi upgrade)]'\necho $[x]\nqargi upgrade",
        "a[0]='x; qargi upgrade; y'; echo hi",
        "rg --pre 'x; qargi upgrade; y' f",
        "sort --compress-program 'x; qargi upgrade; y' f",
        "sort --comp='x; qargi upgrade; y' f",
        "PAGER='x; qargi upgrade; y' git log",
        "BASH_ENV='x; qargi upgrade; y' git log",
        "GIT_EXTERNAL_DIFF='x; qargi upgrade; y' git diff",
        "git -c core.pager='x; qargi upgrade; y' log",
        "git --exec-path='x; qargi upgrade; y' log",
        "git grep -O'x; qargi upgrade; y' foo",
        "echo hi # a\\\nqargi upgrade",
        "echo ${x:-a}\nqargi upgrade",
        "echo $((1<<2))\nqargi upgrade\n2))",
        "echo ((a))\ngit push",
        "[[ a<<b ]]\nqargi upgrade\nb",
        "echo hi\r\nqargi upgrade",
        "echo hi\r\ngit push",
        "cat <<'E'\r\nqargi upgrade\r\nE\r\nqargi upgrade",
        "git commit -m x\ngit push",
        "cat <<'E' > n.txt\nhi\nE\ngit push",
        "git log --oneline | tee n.txt; qargi upgrade",
        "echo 'a' ; echo 'b' ; qargi upgrade ; echo 'c'",
        "echo '#'; qargi upgrade",
        "echo \"#\"; qargi upgrade",
        "echo $#; qargi upgrade",
        "echo a#b; qargi upgrade",
        "echo a\\\n#b; git push",
        "echo a\\ \\#b; git push",
        "echo \\#; git push",
        "echo hi &\n# c\nqargi upgrade",
        "echo hi\n  # c\n\tqargi upgrade",
    )
    # a refused verb in quoted text or a heredoc that a file receives: refused, the cost of not guessing which text is run
    CONSERVATIVE = (
        "cat <<'E' > msg.txt\nqargi upgrade\nE\ngit commit -F msg.txt && python3 tests/x.py",
        "cat <<'E' > msg.txt\nqargi upgrade\nE\nmkdir -p out",
        "make gate; git commit -m 'a; qargi upgrade; b'",
        "echo 'a; qargi upgrade; b' | tr a b",
        "x=1; sh -c 'echo hi'; git commit -m 'a; qargi upgrade; b'",
    )

    def verdicts(self, cmds):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            return list(zip(cmds, ex.map(self.bash, cmds)))

    def test_every_command_the_review_found_is_refused(self):
        wrong = [c for c, r in self.verdicts(self.REFUSED) if r.returncode != 2]
        self.assertEqual(wrong, [], "allowed, but they run a refused verb or git push")

    def test_text_and_heredocs_are_read_as_commands(self):
        wrong = [c for c, r in self.verdicts(self.CONSERVATIVE) if r.returncode != 2]
        self.assertEqual(wrong, [], "the plain split refuses these")

    def test_the_review_found_the_variants_a_member_could_try(self):
        """Not only the single commands: each refused verb is wrapped in the shapes a member could use to hide it."""
        shapes = ('sh -c "@@"', "bash -c '@@'", 'eval "@@"', 'env sh -c "@@"', 'timeout 5 sh -c "@@"', 'trap "@@" EXIT', 'X="@@"; eval $X',
                  "f() { eval \"$1\"; }; f \"@@\"", "python3 -c 'import os; os.system(\"@@\")'", "echo '@@' | sh", "cat <<'E' | sh\n@@\nE",
                  "cat > a.sh <<'E'\n@@\nE\nsh a.sh", "echo a\\ #; @@", "echo ${x:-1}\n@@", "echo $[1<<2]\n@@\n2]")
        wrong = [c for c, r in self.verdicts([s.replace("@@", p) for s in shapes for p in ("true; qargi upgrade; true", "true; git push; true")]) if r.returncode != 2]
        self.assertEqual(wrong, [])


class Segments(unittest.TestCase):
    """segments() in the process: the plain split, what it adds for a substitution, and how fast the whole guard judges a hostile command."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.J = _Judge(LIBDIR, "guard_units", cls.tmp)
        cls.G = cls.J.m

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_line_is_cut_at_every_separator_whatever_the_quotes(self):
        G = self.G
        texts = [t.strip() for t in G.segments('git commit -m "a; qargi upgrade" && ls | wc & sleep 1\nls')]
        self.assertEqual(texts, ['git commit -m "a', 'qargi upgrade"', "ls", "wc", "sleep 1", "ls"])
        self.assertEqual([t.strip() for t in G.segments("cat <<'E'\nqargi upgrade\nE")], ["cat <<'E'", "qargi upgrade", "E"])
        self.assertEqual([t.strip() for t in G.segments("echo a >&2 &> f 2>&1 &&ls")], ["echo a >&2 &> f 2>&1", "ls"])      # & is a separator only alone

    def test_a_substitution_is_a_command_of_its_own_also_inside_quotes(self):
        G = self.G
        for c, want in (('echo "$(qargi upgrade) x"', "qargi upgrade"), ('cat <<<"$(qargi upgrade)"', "qargi upgrade"), ("echo `qargi upgrade` y", "qargi upgrade"),
                        ("diff <(qargi upgrade) x", "qargi upgrade"), ("tee >(qargi upgrade)", "qargi upgrade"), ('echo "$(echo $(git push))"', "git push"),
                        ("echo `echo \\`git push\\``", "git push"), ('echo "$(a; b)"', "b"), ('echo "$(qargi upgrade"', "qargi upgrade\"")):
            self.assertIn(want, [t.strip() for t in G.segments(c)], c)

    def test_a_pipe_after_a_greater_than_is_not_a_cut(self):
        G = self.G
        self.assertEqual([t.strip() for t in G.segments("echo x >| out; ls")], ["echo x >| out", "ls"])
        self.assertEqual([t.strip() for t in G.segments("echo x | cat > f")], ["echo x", "cat > f"])

    def test_a_line_continuation_is_read_both_ways(self):
        G = self.G
        texts = [t.strip() for t in G.segments("echo hi \\\n; qargi upgrade")]
        self.assertIn("qargi upgrade", texts)
        self.assertIn("echo hi \\", texts)

    def test_segments_is_read_once_per_command(self):
        G = self.G
        c = 'git status; echo "a; b"\n# once %s' % time.time()
        self.assertIs(G.segments(c), G.segments(c))

    def test_the_words_of_a_segment_are_found_after_assignments_keywords_and_redirects(self):
        G = self.G
        for c in ("FOO=1 qargi upgrade", "if qargi upgrade; then echo; fi", "{ qargi upgrade; }", "(qargi upgrade)", "! qargi upgrade", ">/dev/null qargi upgrade",
                  "2>&1 qargi upgrade", "while qargi upgrade; do sleep 1; done", "case x in x) qargi upgrade;; esac", "f() { qargi upgrade; }", "function f { qargi upgrade; }",
                  "time -p qargi upgrade", "echo \"$(qargi upgrade)\"", "coproc qargi upgrade"):
            why = self.J.judge(c)
            self.assertTrue(why and "qargi upgrade" in why, (c, why))

    def test_a_nul_byte_refuses_and_a_huge_command_is_refused_before_it_is_read(self):
        why = self.J.judge("echo hi\x00; git status")
        self.assertTrue(why and "NUL" in why, why)
        why = self.J.judge("git status; " * 25000)
        self.assertIn("cannot be checked", why or "")

    def test_hostile_commands_are_judged_in_seconds(self):
        """The hook has 20 seconds and a hook that times out does not block: a command of the size the guard accepts costs a verdict, never a timeout. The
        time budget (BUDGET) refuses what takes longer; this is the whole of judge()."""
        shapes = {"2000 heredocs": "".join("cat > f%d <<'E'\nbody %d\nE\n" % (i, i) for i in range(2000)),
                  "12000 commands": "".join("git status %d; " % i for i in range(12000)),
                  "12000 shell strings": "".join("sh -c 'echo %d'; " % i for i in range(12000)),
                  "12000 substitutions": "".join("echo $(echo %d) " % i for i in range(12000)),
                  "12000 backticks": "".join("echo `echo %d` " % i for i in range(12000)),
                  "nested substitutions": "echo " + "$(" * 20000 + "x" + ")" * 20000,
                  "unclosed substitutions": "echo " + "$(" * 80000,
                  "a lot of parentheses": "echo " + "(" * 80000,
                  "a lot of backticks": "echo " + "`" * 80000,
                  "200 KB of words": "echo " + "word " * 40000,
                  "many redirections": "echo " + "> /tmp/f%d " * 100 % tuple(range(100)),
                  "wide glob": "cat /*/*/*/*/*/*",
                  "a glob in every word": "cat " + "/*/*/x%d " * 2000 % tuple(range(2000))}
        for name, c in shapes.items():
            t0 = time.perf_counter()
            why = self.J.judge(c)
            took = time.perf_counter() - t0
            self.assertLess(took, 20.0, "%s: %.1f s" % (name, took))
            if name.endswith("substitutions") and name.startswith(("nested", "unclosed")):
                self.assertIn("nested more than", why or "", name)
        for name, c in {"wide glob": "cat /*/*/*/*/*/*", "a glob that finds nothing": "cat /*/*/*/*/*/*/*/*/zzz_not_here"}.items():
            t0 = time.perf_counter()
            why = self.J.judge(c)
            took = time.perf_counter() - t0
            self.assertLess(took, 10.0, "%s: %.1f s" % (name, took))
            self.assertIn("too many directories", why or "", name)

    def test_a_command_that_takes_too_long_to_check_is_refused_not_let_through(self):
        G = self.G
        real = G.BUDGET
        G.BUDGET = 0.0
        try:
            why = self.J.judge("git status; echo hi; git log %s" % time.time())
        finally:
            G.BUDGET = real
        self.assertIn("took longer", why or "")


class OldReading(unittest.TestCase):
    """The anti-regression property of the Bash reader: every command that the guard of 2b41028 refused (it cut a command at every separator, whatever the
    quotes) is refused now. The new guard only adds: substitutions read inside quotes, the keywords and groupings a command follows, `&` as a separator, the
    scripts in a shell string, the options of git tag and the write channels (see WriteChannels)."""
    PAYLOADS = ("qargi upgrade", "true; qargi upgrade; true", "git push", "true; git push origin x; true", "qargi packs seed")
    TEXTS = ('echo "@@"', "echo '@@'", 'git commit -m "@@"', "git commit -m '@@'", "printf '%s\\n' '@@'", "grep -n '@@' f", "cat <<'E'\n@@\nE",
             "git log --format='@@' -3", "git commit -F - <<'E'\n@@\nE", "cat <<'E' > n.txt\n@@\nE", "echo hi # @@")
    RUNNING = ('sh -c "@@"', "bash -c '@@'", 'eval "@@"', "eval @@", 'env sh -c "@@"', 'sudo -u root sh -c "@@"', 'timeout 5 sh -c "@@"', 'nice -n 5 sh -c "@@"',
               'nohup sh -c "@@" &', 'xargs -I% sh -c "@@"', 'find . -maxdepth 0 -exec sh -c "@@" \\;', "python3 -c '@@'", "perl -e 'system \"@@\"'",
               "ruby -e 'system(\"@@\")'", "awk 'BEGIN{system(\"@@\")}'", "node -e 'require(\"child_process\").execSync(\"@@\")'", 'trap "@@" EXIT',
               'X="@@"; eval $X', 'X="@@"\neval $X', "alias z='@@'\nz", 'f() { eval "$1"; }; f "@@"', 'su -c "@@"', 'watch "@@"', 'flock l -c "@@"',
               "script -qc '@@' /dev/null", "busybox sh -c '@@'", "fish -c '@@'", 'git -c alias.z="!@@" z', "git rebase --exec '@@' HEAD",
               "echo '@@' | sh", "echo '@@' | bash -s", "printf '%s' '@@' | xargs sh -c", "sh <<'E'\n@@\nE", "bash <<E\n@@\nE", "python3 <<'E'\n@@\nE",
               "cat <<'E' | sh\n@@\nE", "cat > a.sh <<'E'\n@@\nE\nsh a.sh", "cat > a <<'E'\n@@\nE\nbash <a", "cat > a <<'E'\n@@\nE\ncp a b; sh b",
               "echo '@@' > a.sh; sh a.sh", "cat > Makefile <<'E'\nall:\n\t@@\nE\nmake", "for x in 1; do @@; done", "{ @@; }", "(@@)", "if true; then @@; fi",
               "x=$(@@)", "echo $(@@)", "echo `@@`", 'echo "$(@@)"', "diff <(@@) x", "cat <<E\n$(@@)\nE", "echo a\\ #; @@", "echo ${x:-1}\n@@",
               "echo $[1<<2]\n@@\n2]", "echo hi\n@@", "echo 'x' #\"\n@@", "echo '@@' ; @@")

    def corpus(self):
        out = list(BashText.REFUSED) + list(BashText.AS_TEXT) + list(ReviewedReading.REFUSED) + list(ReviewedReading.CONSERVATIVE)
        out += [t.replace("@@", p) for t in self.RUNNING + self.TEXTS for p in self.PAYLOADS]
        return list(dict.fromkeys(out))

    def test_the_new_refusals_contain_the_old_ones(self):
        lib = old_lib(self)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new = _Judge(lib, "guard_old", tmp), _Judge(LIBDIR, "guard_new", tmp)
        corpus = self.corpus()
        self.assertGreaterEqual(len(corpus), 300)
        refused_by_old = [c for c in corpus if old.judge(c)]
        self.assertGreaterEqual(len(refused_by_old), 300, "the corpus must be mostly commands the old guard refused")
        lost = [c for c in refused_by_old if not new.judge(c)]
        self.assertEqual(lost, [], "the old guard refused these, the new one allows them")

    def test_the_hardening_commands_the_old_guard_missed_are_refused_now(self):
        lib = old_lib(self)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new = _Judge(lib, "guard_old", tmp), _Judge(LIBDIR, "guard_new", tmp)
        for c in ('echo "$(qargi upgrade)"', "sleep 1 & qargi upgrade", "if true; then git push; fi", "sh -c 'git push'", "cat <<<\"$(qargi upgrade)\""):
            self.assertTrue(new.judge(c), c)
        self.assertFalse(old.judge("sleep 1 & qargi upgrade"))


class Substitutions(unittest.TestCase):
    """A command substitution is a command of its own wherever it sits: after a here-string, inside double quotes, inside a backtick pair, in a process
    substitution. Each of these was let through by a reading that cut the line but kept the substitution's closing quote on its last word."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call
    MUST_REFUSE = (
        'cat <<<"$(qargi upgrade)"',
        "grep -q x <<<\"$(sh -c 'qargi upgrade')\"",
        'cat 0<<<"$(qargi upgrade)"',
        'cat <<<"x" <<<"$(qargi upgrade)"',
        'echo hi; cat <<<"`qargi upgrade`"',
        'cat <<<$(qargi upgrade)',
        'cat <<< "$(qargi upgrade) more words"',
        'cat <<<"$(qargi packs seed)" | wc',
        'cat <<<"$(cd /tmp && qargi upgrade)"',
        'cat <<<"a $(echo $(qargi upgrade)) b"',
        'cat <<<"$(git push)"',
        'git $(true) push',
        'cat <<<"$(sh -c "git push")"',
        'echo "$(qargi upgrade) x" y',
        'echo "<$(qargi upgrade)>"',
        'echo "(`qargi upgrade`)"',
        'echo "$(qargi upgrade -h)"',
        'x="$(qargi upgrade)"',
        'x="`qargi upgrade`" y',
        'echo "$(echo "$(qargi upgrade)")"',
        'tee >(qargi upgrade) < /dev/null',
        'diff <(qargi upgrade) <(ls)',
        'echo "$(qargi marshal claim x)"',
        'echo "$(qargi skill remove x)"',
        'echo "$(qargi provider enable x)"',
    )
    MAY_RUN = ('cat <<<"$(git status)"', 'echo "$(ls) done"', 'x="$(pwd)"; echo $x', 'diff <(ls) <(ls -a)', 'cat <<<"plain text"', 'echo "`date`"')

    def test_every_substitution_that_runs_a_refused_verb_is_refused(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            res = list(zip(self.MUST_REFUSE, ex.map(self.bash, self.MUST_REFUSE)))
        self.assertEqual([c for c, r in res if r.returncode != 2], [])

    def test_a_substitution_of_an_ordinary_command_is_allowed(self):
        for c in self.MAY_RUN:
            self.assertEqual(self.bash(c).returncode, 0, c)


class RunRecord(unittest.TestCase):
    """What a member cannot do to the run directory, and that the read-only class of the hook holds without asking the run. Write channels that name a file
    by a glob, a variable or a substitution are refused when they could be the run's record, the others as before."""
    def setUp(self):
        Skills.setUp(self)
        self.out = os.path.join(self.run_dir, "out")
        for name, text in (("class", "write\n"), ("repo.path", self.t + "\n"), ("tmpdir", self.t + "\n"), ("started", "1\n")):
            with open(os.path.join(self.run_dir, name), "w") as f:
                f.write(text)
        os.makedirs(os.path.join(self.clone, "src"), exist_ok=True)
        with open(os.path.join(self.clone, "src", "a.go"), "w") as f:
            f.write("package a\n")

    tearDown = Skills.tearDown

    def call(self, tool, inp, cwd=None, cls="read-only"):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf})
        return subprocess.run([BIN, "__guard"] + (["--class", cls] if cls else []), input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": cwd or self.clone}),
                              capture_output=True, text=True, env=e)

    def table(self, cmds, cwd=None, cls="read-only"):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            return list(zip(cmds, ex.map(lambda c: self.call("Bash", {"command": c}, cwd, cls), cmds)))

    # --- write channels into the clone
    CHANNELS = (
        "echo pwn >| src/a.go", "echo pwn>|src/a.go", "echo pwn 1<> src/a.go", "echo pwn 1<>src/a.go", "echo pwn <> src/a.go", "echo pwn >&src/a.go", "echo pwn >& src/a.go",
        "echo pwn &> src/a.go", "echo pwn &>> src/a.go", "echo pwn 2>| src/a.go", "echo pwn >src/a.go", "echo pwn>src/a.go",
        "git log --output=src/a.go", "git log --output src/a.go", "git diff --output=src/x", "git show --output=src/x HEAD", "git -C . log --output=src/x",
        "git format-patch -o src HEAD~1", "git format-patch --output-directory=src HEAD~1", "git archive -o src/x.tar HEAD", "git archive --output=src/x.tar HEAD",
        "git bundle create src/b HEAD", "sort -o src/a.go f", "sort --output=src/a.go f", "sort --output src/a.go f", "sort -osrc/a.go f", "sort -u -o src/a.go src/a.go",
        "uniq in.txt src/a.go", "uniq -c in.txt src/a.go", "mv src/a.go /tmp/gone", "mv -t /tmp src/a.go", "cp -t src /etc/hostname", "cp --target-directory=src /etc/hostname",
        "install -t src /etc/hostname", "ln -t src /etc/hostname", "dd if=/dev/zero of=src/a.go", "sed -ni s/a/b/ src/a.go", "sed -i.bak s/a/b/ src/a.go",
        "sed --in-place -e s/a/b/ src/a.go", "sed -i -f script.sed src/a.go", "perl -pi -e 's/a/b/' src/a.go", "rsync --remove-source-files src/a.go /tmp/", "tee src/a.go < /dev/null",
        "git update-index --add src/a.go", "git gc", "git write-tree", "git hash-object -w src/a.go | git update-index --cacheinfo x", "git mktree < /dev/null",
        "echo pwn > src/*.go", "echo pwn > src/a.g?", "echo pwn > src/[a].go", "echo pwn > $PWD/src/a.go", "rm src/*", "touch src/{a,b}.go", "chmod +x src/a.go",
        "truncate -s0 src/a.go", "echo hi > src/$(echo a).go",
    )
    # the same channels aimed at OUT, or reading only
    ALLOWED = (
        "echo pwn >| @@/r.md", "echo pwn 1<> @@/r.md", "echo pwn &> @@/r.md", "echo pwn >& @@/r.md", "git log --output=@@/log.txt", "git log --output @@/log.txt",
        "sort -o @@/s.txt f", "sort --output=@@/s.txt f", "uniq in.txt @@/u.txt", "uniq in.txt", "git archive -o @@/x.tar HEAD", "git format-patch -o @@ HEAD~1",
        "cp /etc/hostname @@/", "cp -t @@ /etc/hostname", "mv @@/a @@/b", "echo x > @@/*.md", "printf 'a > b' > @@/r.md",
        "cat src/a.go > /dev/null", "git log --oneline > /dev/null 2>&1", "make test > @@/test.log 2>&1", "sort src/a.go | uniq -c | tee @@/counts", "git diff HEAD~1 | wc -l",
        "echo '->' | tee @@/x", "git log --format='%s -> %h' -3", "echo 'a -> $b'", "ls src/*.go", "cat src/*", "grep -n x src/*.go", "uniq src/a.go",
    )

    def test_a_channel_into_the_clone_is_refused_under_the_read_only_class(self):
        for cls in ("read-only", None):
            if cls is None:
                with open(os.path.join(self.run_dir, "ability"), "w") as f:
                    f.write("review\n")
            wrong = [c for c, r in self.table(self.CHANNELS, cls=cls) if r.returncode != 2]
            self.assertEqual(wrong, [], "allowed, but they write into the clone (class %s)" % cls)

    def test_the_same_channels_aimed_at_out_and_reading_commands_are_allowed(self):
        cmds = [c.replace("@@", self.out) for c in self.ALLOWED]
        wrong = [(c, r.stderr.strip()) for c, r in self.table(cmds) if r.returncode != 0]
        self.assertEqual(wrong, [], "refused, but they write to OUT or only read")

    def test_a_build_member_may_write_all_of_it(self):
        with open(os.path.join(self.run_dir, "ability"), "w") as f:
            f.write("build\n")
        skip = ("git gc", "git write-tree", "git update-index", "git mktree", "git hash-object")         # the git subcommands that are no write to a build member either
        wrong = [(c, r.stderr.strip()) for c, r in self.table([c for c in self.CHANNELS if not c.startswith(skip)], cls=None)
                 if r.returncode != 0 and "record of the run" not in r.stderr and "cannot read" not in r.stderr]
        self.assertEqual(wrong, [])

    # --- the record of the run
    RECORD = (
        "echo pwn > abilit?", "echo pwn > ab*", "echo pwn > [a]bility", "echo pwn > ./abilit?", "echo pwn >| abilit?", "printf pwn 1<> ability", "echo pwn > $F", "echo pwn > \"$F\"",
        "echo pwn > ${F}", "echo pwn >> $F", "echo pwn > $(echo ability)", "echo pwn > `echo ability`", "echo pwn >$(echo ability)", "echo pwn > ability$X", "echo x > $D/ability",
        "echo x > ${D}/refs.before", "tee abil* < /dev/null", "tee $F < /dev/null", "cp /etc/hostname abilit?", "cp /etc/hostname $F", "cp /etc/hostname $D/ability",
        "mv ability /tmp/x", "mv refs.before /tmp/x", "mv /tmp/x ability", "mv -t /tmp ability", "rm refs.before", "rm -f ability", "rm -f ./refs.befor?", "rm $D/ability", "rm -rf .",
        "rm -rf ../run", "rm -rf ..", "rm -rf /", "mv ../run ../run2", "mv . ../run2", "truncate -s0 ability", "unlink ability", "shred -u ability", "ln -s ability x", "ln -sf /etc/hostname ability",
        "ln ability x", "cp ability /tmp/x", "cp -t /tmp ability", "cp refs.before /tmp/x", "install ability /tmp/x", "rsync ability /tmp/x", "dd if=/dev/zero of=ability", "dd if=ability of=/tmp/x",
        "sed -i s/review/build/ ability", "sed -i 's/a/b/' abil*", "find . -name ability -delete", "find . -maxdepth 1 -name 'ab*' -exec rm {} +", "find .. -delete",
        "sort -o ability f", "git log --output=ability", "uniq f ability", "echo x > class", "echo x > profile", "echo x > repo.path", "echo x > tmpdir", "echo x > started",
        "echo x > verified", "echo x > applied", "echo x > cred.path", "echo x > repo.url", "echo x > refs.after", "echo x > refs.diff", "echo x > git",
    )

    def test_the_runs_record_cannot_be_reached_by_a_name_the_guard_cannot_read_or_by_taking_it_away(self):
        for cls in ("read-only", None):
            wrong = [c for c, r in self.table(self.RECORD, cwd=self.run_dir, cls=cls) if r.returncode != 2]
            self.assertEqual(wrong, [], "allowed, but they change the run's record (class %s)" % cls)
        with open(os.path.join(self.run_dir, "ability")) as f:
            self.assertEqual(f.read(), "build\n")

    def test_what_is_not_the_runs_record_stays_writable_from_the_run_directory(self):
        cmds = ["echo x > out/report.md", "echo x > $UNSET/report.md", "echo x > $UNSET/notes", "cat ability", "ls ab*", "ls -d ref*", "rm -rf out/tmp*", "cp ability out/copy 2>/dev/null; true",
                "echo x > out/ability.md", "echo x > out/*.md", "grep -n x ab*", "cat refs.before | wc -l", "echo x >| out/report.md", "wc -c ability refs.before"]
        wrong = [(c, r.stderr.strip()) for c, r in self.table(cmds, cwd=self.run_dir, cls=None)
                 if r.returncode != 0 and not c.startswith("cp ability")]
        self.assertEqual(wrong, [])

    def test_a_glob_that_names_no_record_file_here_is_not_the_record(self):
        for c in ("rm -rf clone/build/*", "rm -f clone/*.o", "echo x > clone/n*.txt", "rm -f out/ab*"):
            self.assertEqual(self.call("Bash", {"command": c}, self.run_dir, None).returncode, 0, c)
        for c in ("rm -rf build/*", "rm -f *.o", "rm -f a*"):              # in the clone, where no record file is
            self.assertEqual(self.call("Bash", {"command": c}, self.clone, None).returncode, 0, c)
        self.assertEqual(self.call("Bash", {"command": "rm -f ab*"}, self.run_dir, None).returncode, 2)

    # --- the class of the hook does not ask the run
    def test_the_read_only_class_holds_when_the_files_the_run_is_found_by_are_gone(self):
        for name in ("ability", "refs.before", "class", "repo.path", "tmpdir", "started"):
            os.unlink(os.path.join(self.run_dir, name))
        for tool, inp in (("Write", {"file_path": os.path.join(self.clone, "src/a.go")}), ("Edit", {"file_path": "src/a.go"}), ("Write", {"file_path": os.path.join(self.out, "report.md")}),
                          ("Bash", {"command": "echo x > src/a.go"}), ("Bash", {"command": "rm src/a.go"}), ("Bash", {"command": "touch src/new"}),
                          ("Bash", {"command": "echo x > %s/report.md" % self.out}), ("Bash", {"command": "git commit -am x"})):
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 2, (tool, inp, r.stderr))
        for c in ("git log --oneline", "cat src/a.go", "ls", "grep -rn package src", "git diff", "echo x > /dev/null"):
            self.assertEqual(self.call("Bash", {"command": c}).returncode, 0, c)

    def test_a_run_whose_two_files_were_moved_is_still_a_run(self):
        """Any file of the run's record, or the clone and out directories beside one, makes a directory a run: moving ability and refs.before away does not
        switch the class off for a member that has none passed by its hook."""
        with open(os.path.join(self.run_dir, "ability"), "w") as f:
            f.write("review\n")
        for gone in (("refs.before",), ("refs.before", "repo.path", "tmpdir", "cred.path", "refs.after", "refs.diff", "repo.url")):
            for name in gone:
                try:
                    os.unlink(os.path.join(self.run_dir, name))
                except FileNotFoundError:
                    pass
            r = self.call("Bash", {"command": "echo x > src/a.go"}, cls=None)
            self.assertEqual(r.returncode, 2, (gone, r.stderr))
            self.assertIn("read-only", r.stderr)
        os.unlink(os.path.join(self.run_dir, "ability"))                        # class and started are left: the clone and out directories beside them
        r = self.call("Bash", {"command": "echo x > src/a.go"}, cls=None)
        self.assertEqual(self.call("Write", {"file_path": os.path.join(self.run_dir, "class")}, cls=None).returncode, 2)

    def test_a_run_directory_is_not_a_source_tree(self):
        d = os.path.join(self.t, "plain")
        os.makedirs(os.path.join(d, "clone"))
        for name in ("class", "profile", "git"):
            with open(os.path.join(d, name), "w") as f:
                f.write("x\n")
        self.assertEqual(self.call("Write", {"file_path": os.path.join(d, "class")}, d, None).returncode, 0)        # no out directory, no marker: not a run
        self.assertEqual(self.call("Bash", {"command": "echo x > clone/f"}, d, "read-only").returncode, 2)          # but the class of the hook still finds no OUT to write to

    # --- the variables a read-only tool reads its programs and options from
    ENV = ("printf -v PATH x", "printf -vPATH x", "PATH=. ls", "export GIT_PAGER=x", "RIPGREP_CONFIG_PATH=x rg y", "declare -x BASH_ENV=x", "env PAGER=x git log", "read PATH",
           "GIT_EXTERNAL_DIFF=x git diff", "LD_PRELOAD=x ls", "PYTHONSTARTUP=x python3 -c pass", "NODE_OPTIONS=--require=x node -e 1", "RUBYOPT=-rx ruby -e 1", "PERL5OPT=-Mx perl -e 1",
           "EDITOR=x git log", "XDG_CONFIG_HOME=/tmp/x git log", "HOME=/tmp/x git log", "GIT_SSH_COMMAND=x ls", "export PROMPT_COMMAND=x", "printf -v a[0] x; printf -v PAGER x")

    def test_a_read_only_member_sets_none_of_them(self):
        wrong = [c for c, r in self.table(self.ENV) if r.returncode != 2]
        self.assertEqual(wrong, [])
        for c in ("printf -v msg x", "NODE_ENV=test ls", "FOO=1 ls", "export FOO=1", "LANG=C sort f", "read line", "printf -v a[0] x", "echo $PATH"):
            self.assertEqual(self.call("Bash", {"command": c}).returncode, 0, c)
        self.assertEqual(self.call("Bash", {"command": "PATH=. ls"}, None, None).returncode, 0)               # a member that writes is not held to it

    # --- configuration and hooks of git, written by a command that also runs git
    GIT_PLACES = ("echo '[core]' > ~/.gitconfig; git log", "echo x >> ~/.config/git/config && git status", "echo x > ~/.config/git/attributes; git log", "echo x > .git/hooks/post-checkout; git status",
                  "echo x > .git/config; git log", "printf x | tee ~/.gitconfig; git log", "cp /etc/hostname ~/.gitconfig && git status", "git status; echo x >| ~/.gitconfig",
                  "echo x > .git/info/attributes; git log", "echo '[alias]' >> .git/config\ngit log")

    def test_a_command_that_writes_the_configuration_of_git_and_runs_git_is_refused(self):
        for cls in ("read-only", None):
            wrong = [c for c, r in self.table(self.GIT_PLACES, cls=cls) if r.returncode != 2]
            self.assertEqual(wrong, [], "class %s" % cls)
        for c in ("cat ~/.gitconfig; git log", "git config --list", "echo x > .gitattributes.txt; git status"):
            self.assertEqual(self.call("Bash", {"command": c}, self.run_dir, None).returncode, 0, c)


class MoveBeside(unittest.TestCase):
    """A file moved INTO a directory that only lies above a protected location (/tmp, the temporary directory, $HOME, a conf directory) or above the run does
    not change that location. The directory is refused when what is moved is, holds or has the name of the place, and always as the target of mv -T."""
    base = None                                          # where the fixture lives: the default temporary directory, or /tmp, or /dev/shm

    def setUp(self):
        if self.base and not (os.path.isdir(self.base) and os.access(self.base, os.W_OK)):
            self.skipTest("%s is not a writable directory on this machine" % self.base)
        before, tempfile.tempdir = tempfile.tempdir, self.base
        try:
            RunRecord.setUp(self)
        finally:
            tempfile.tempdir = before
        with open(os.path.join(self.run_dir, "ability"), "w") as f:
            f.write("build\n")
        self.above = os.path.dirname(self.t)

    tearDown = Skills.tearDown
    call = RunRecord.call
    table = RunRecord.table

    ALLOWED = ("mv -t {above} src/a.go", "mv src/a.go {above}", "mv --target-directory={above} src/a.go", "mv -vt {above} src/a.go", "mv -f -t {above} src/a.go",
        "mv -t {t} src/a.go", "mv src/a.go {t}", "mv src/a.go {conf}", "mv -t {conf} src/a.go", "mv src/a.go {home}/.claude", "mv src/a.go {home}",
        "mv -t $HOME src/a.go", "mv src/a.go ~", "mv -t ~/.claude src/a.go", "mv src/a.go {proj}/.claude", "mv src/a.go src/b.go {t}", "mv {proj}/src {conf}",
        "mv src/a.go {above}/{me}/proj")
    REFUSED = (
        "mv -t {conf}/credentials src/a.go", "mv src/a.go {conf}/credentials", "cp -t {conf}/credentials src/a.go", "cp src/a.go {conf}/credentials",       # into it
        "mv -t {lib} src/a.go", "cp -t {lib} src/a.go", "mv src/a.go {lskill}/x", "mv -t {lskill} src/a.go", "mv src/a.go {home}/.claude/skills",
        "mv {conf}/credentials {t}/gone", "mv -t {t} {conf}/credentials", "mv {conf} {above}/gone", "mv -t {above} {conf}", "mv {home}/.claude {t}/gone",        # a protected directory
        "mv {t} {above}/gone", "mv -t {above} {t}", "mv {t} {above}", "mv {run} {above}", "mv -t {above} {run}", "mv {run} {above}/gone", "mv -t {conf} {conf}",   # one that holds it
        "mv {proj}/credentials {conf}", "mv -t {conf} {proj}/credentials", "mv {proj}/packs {conf}", "mv -t {conf}/ {proj}/credentials/", "mv /x/{me} {above}",    # a name that meets it
        "mv {proj}/cred* {conf}", "mv {proj}/$N {conf}", "mv -t {conf} {proj}/{{a,credentials}}", "mv {proj}/src/.. {conf}", "mv src/a.go ..",
        "mv -T {proj}/src {conf}", "mv -T {proj}/src {above}", "mv --no-target-directory {proj}/src {t}", "mv -vT {proj}/src {conf}",                           # replaces the directory
        "cp -r {proj}/src {conf}/credentials", "cp -rt {conf}/credentials {proj}/src", "mv src/a.go {run}", "mv -t {run} src/a.go", "mv src/a.go {run}/ability")

    def fill(self, cmds):
        names = dict(above=self.above, t=self.t, conf=self.conf, lib=self.lib, home=self.home, lskill=self.lskill, run=self.run_dir, proj=self.proj,
                     me=os.path.basename(self.t))
        return [c.format(**names) for c in cmds]

    def test_a_file_moved_into_a_directory_above_a_protected_location_is_allowed(self):
        cmds = self.fill(self.ALLOWED)
        wrong = [(c, r.stderr.strip()) for c, r in self.table(cmds, cls=None) if r.returncode != 0]
        self.assertEqual(wrong, [])

    def test_what_changes_a_protected_location_or_the_run_stays_refused(self):
        cmds = self.fill(self.REFUSED)
        wrong = [c for c, r in self.table(cmds, cls=None) if r.returncode != 2]
        self.assertEqual(wrong, [])

    def test_the_read_only_class_still_may_not_move_the_clone_away_into_such_a_directory(self):
        self.assertEqual(self.call("Bash", {"command": "mv -t %s src/a.go" % self.above}, cls="read-only").returncode, 2)


class MoveBesideUnderTmp(MoveBeside):
    base = "/tmp"


class MoveBesideUnderShm(MoveBeside):
    base = "/dev/shm"


class GlobBound(unittest.TestCase):
    """The key checks used to expand a glob to the end: `cat /*/*/*/*/*/*` took 106 seconds, five times the time the hook has. A glob is expanded by reading
    at most GLOB_ENTRIES directory entries; a pattern that needs more is refused."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call

    def test_a_wide_glob_is_refused_in_seconds_not_minutes(self):
        for c in ("cat /*/*/*/*/*/*", "grep -r x /*/*/*/*/*/*/*/*", "cat /*/*/*/*/*/*/*/*/zzz_not_here", "cp -r /*/*/*/*/*/* /tmp/x"):
            t0 = time.perf_counter()
            r = self.bash(c)
            took = time.perf_counter() - t0
            self.assertLess(took, 10.0, (c, took))                    # it took minutes; a slow or busy machine takes seconds
            self.assertEqual(r.returncode, 2, c)
            self.assertIn("too many directories", r.stderr, c)

    def test_a_glob_that_reaches_the_key_is_still_found_and_an_ordinary_glob_is_not_refused(self):
        cred = os.path.join(self.conf, "credentials")
        os.makedirs(cred)
        with open(os.path.join(cred, "marshal_ed25519"), "w") as f:
            f.write("k\n")
        for c in ("cat %s/marshal_*" % cred, "cat %s/cred*/../credentials/marshal_*" % self.conf, "cat %s/cred*/marshal_ed*" % self.conf, "cat %s/c[r]edentials/marshal_ed25519" % self.conf):
            self.assertEqual(self.bash(c).returncode, 2, c)
        for c in ("cat %s/cred*/other_*" % self.conf, "ls %s/*" % self.clone, "grep -n x %s/skills/*/*" % self.clone):
            self.assertEqual(self.bash(c).returncode, 0, c)


class GlobsAndProtectedRoots(unittest.TestCase):
    """A write whose glob can name a protected location is refused; one that cannot is not."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call

    def test_a_glob_that_can_reach_a_protected_root_is_refused_for_a_write(self):
        h = self.home
        for c in ("echo x > %s/.claude/skil*/x/SKILL.md" % h, "rm -rf %s/.claude/s*" % h, "rm -rf %s/*" % h, "rm -rf %s/.cl*" % h, "mv %s/.claude/sk*/x /tmp/gone" % h,
                  "cp /etc/hostname %s/.claude/skills/*/SKILL.md" % h, "tee %s/.claude/*/x/SKILL.md < /dev/null" % h, "rm -rf %s/.c*/skills" % h):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, (c, r.stderr))

    def test_a_glob_that_cannot_is_not(self):
        for c in ("rm -rf %s/build/*" % self.clone, "echo x > %s/skills/*/note" % self.clone, "rm -f %s/.claude/skills/p/*" % self.clone, "ls %s/.claude/*" % self.home,
                  "cat %s/.claude/skills/*/SKILL.md" % self.home, "rm -f %s/proj/src/*.o" % self.t):
            self.assertEqual(self.bash(c).returncode, 0, c)


class LibraryScripts(unittest.TestCase):
    """lib/linker.py (the link engine: what a checkout loads its skills and agents from) and lib/render.py (the renderer of member
    definitions, which can run the command a definition names) are qargi's own and are not available to a member when run directly. Their
    names are common, so only the files of the tool are refused: a render.py or linker.py of a project, or of the clone a member works in, is
    its work product."""
    setUp, tearDown, bash, call = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call
    LIB = os.path.realpath(os.path.join(os.path.dirname(BIN), "..", "lib"))

    def refused(self, c, text, **kw):
        r = self.bash(c, **kw)
        self.assertEqual(r.returncode, 2, (c, r.stderr))
        self.assertIn(text, r.stderr, c)
        self.assertIn("qargi guard:", r.stderr)

    def test_refuses_the_tools_own_scripts_run_directly(self):
        lib = self.LIB
        render = "lib/render.py is the renderer of member definitions and can run the command a definition names; it is not available to an agent"
        link = "qargi packs link changes a skill and is not available to an agent"
        for c in ("python3 -I %s/render.py render spec.json def.json", "python3 %s/render.py render spec.json def.json", "%s/render.py render s d",
                  "bash -c 'python3 -I %s/render.py render s d'", "env X=1 python3 %s/render.py render s d", "sudo python3 %s/render.py render s d",
                  "echo $(python3 %s/render.py render s d)", "cd src && python3 %s/render.py render s d", "python3 %s/../lib/render.py render s d",
                  "python3 %s/render.py"):
            self.refused(c % lib, render)
        for c in ("python3 -I %s/linker.py", "python3 %s/linker.py plan link in.json t", "%s/linker.py", "bash -c 'python3 %s/linker.py'", "sudo python3 -I %s/linker.py"):
            self.refused(c % lib, link)
        self.refused("python3 -I render.py render s d", render, cwd=lib)
        self.refused("python3 -I linker.py", link, cwd=lib)
        self.refused("cd %s && python3 render.py render s d" % lib, render)
        self.refused("./render.py render s d", render, cwd=lib)
        self.refused("python3 lib/render.py render s d", render, cwd=os.path.dirname(lib))
        os.symlink(lib, os.path.join(self.clone, "tool-lib"))                     # a link in the clone to the tool's lib is followed
        self.refused("python3 tool-lib/render.py render s d", render)

    def test_refuses_the_installed_copy_too(self):
        opt = os.path.join(self.t, "opt")
        os.makedirs(os.path.join(opt, "lib"))
        with open(os.path.join(self.conf, "install.json"), "w") as f:
            json.dump({"tool_root": opt}, f)
        self.refused("python3 -I %s/lib/render.py render s d" % opt, "lib/render.py is the renderer of member definitions")
        self.refused("python3 %s/lib/linker.py" % opt, "qargi packs link changes a skill")
        self.assertEqual(self.bash("python3 -I %s/other/render.py render s d" % opt).returncode, 0)

    def test_a_script_of_the_same_name_that_is_not_the_tools_is_not_refused(self):
        for c in ("python3 render.py render s d", "python3 -I lib/render.py render s d", "python3 scripts/linker.py", "./render.py", "python3 %s/proj/render.py" % self.t,
                  "cd src && python3 ../tools/linker.py", "cat %s/render.py" % self.LIB, "grep -n def %s/linker.py" % self.LIB, "python3 -m unittest tests/test_render.py",
                  "python3 -I %s/render_helpers.py" % self.LIB, "echo python3 %s/render.py" % self.LIB, "ls %s/linker.py" % self.LIB):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))
        r = self.bash("python3 -I lib/render.py render s d", cwd=self.proj)           # a project's own, with no lib of the tool
        self.assertEqual(r.returncode, 0, r.stderr)


class ThirdReview(unittest.TestCase):
    """The third security review of the Bash reader. Every case here was allowed by the guard it reviewed and is refused now. The base is a run directory
    (what `qargi local prepare` makes: clone, out, the record) with every protected location a member could aim at."""
    def setUp(self):
        self.t = os.path.realpath(tempfile.mkdtemp())
        self.home, self.conf, self.state = (os.path.join(self.t, d) for d in ("home", "conf", "state"))
        self.run_dir = os.path.join(self.t, "run")
        self.clone, self.out = os.path.join(self.run_dir, "clone"), os.path.join(self.run_dir, "out")
        for d in ("home/.claude/skills/x", "home/.claude/agents", "home/.claude/plugins/p", "conf/packs/skills/s", "conf/credentials", "state/features", "run/clone/sub", "run/clone/docs",
                  "run/out", "run/contract", "run/home"):
            os.makedirs(os.path.join(self.t, d))
        for name, text in (("run/ability", "build\n"), ("run/refs.before", ""), ("run/class", "write\n"), ("run/repo.path", self.t + "\n"), ("run/tmpdir", self.t + "/tmp\n"),
                           ("run/started", "1\n"), ("conf/credentials/marshal_ed25519", "key\n"), ("conf/credentials/other", "x\n"), ("state/ref-journal.jsonl", "{}\n"),
                           ("state/features/proj-f.json", "{}\n")):
            with open(os.path.join(self.t, name), "w") as f:
                f.write(text)
        self.key = os.path.join(self.conf, "credentials", "marshal_ed25519")
        self.targets = {"skills": os.path.join(self.home, ".claude/skills/x/SKILL.md"), "agents": os.path.join(self.home, ".claude/agents/m.md"),
                        "plugins": os.path.join(self.home, ".claude/plugins/p/f"), "packs": os.path.join(self.conf, "packs/x/SKILL.md"),
                        "credentials": os.path.join(self.conf, "credentials/c"), "features": os.path.join(self.state, "features/f.json"),
                        "ref-journal": os.path.join(self.state, "ref-journal.jsonl")}

    def tearDown(self):
        shutil.rmtree(self.t, ignore_errors=True)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME", "OUT")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
        return e

    def call(self, tool, inp, cwd=None, cls=None):
        return subprocess.run([BIN, "__guard"] + (["--class", cls] if cls else []), input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": cwd or os.path.join(self.clone, "sub")}),
                              capture_output=True, text=True, env=self.env())

    def table(self, cmds, cwd=None, cls=None):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            return list(zip(cmds, ex.map(lambda c: self.call("Bash", {"command": c}, cwd, cls), cmds)))

    def not_refused(self, cmds, cwd=None, cls=None):
        return [(c, r.stderr.strip()[:80]) for c, r in self.table(cmds, cwd, cls) if r.returncode != 2]

    def not_allowed(self, cmds, cwd=None, cls=None):
        return [(c, r.stderr.strip()[:120]) for c, r in self.table(cmds, cwd, cls) if r.returncode != 0]

    # --- finding 1: a redirection before the program, or with no program, is judged like any other write and read
    BARE = (">T", "> T", "2>T", "2> T", "<>T", ">>T", "&>T", ">|T", "exec 3>T; echo payload >&3", "exec 3> T; echo payload >&3", "exec >T", "exec 1>>T", "exec 3<>T; echo hi >&3",
            "exec {fd}>T; echo hi >&$fd", "{ >T; }", "( >T )", "true && >T", "if true; then >T; fi", "false || >T", "echo a | >T", "X_=1 >T", "> T echo payload", "2>T true")

    def test_a_redirection_with_no_program_or_before_it_is_judged_like_a_write(self):
        cmds = [form.replace("T", path) for path in self.targets.values() for form in self.BARE]
        cmds += [">~/.claude/skills/x/SKILL.md", ">$HOME/.claude/skills/x", "exec 3>~/.claude/skills/x/SKILL.md; echo payload >&3"]
        self.assertEqual(self.not_refused(cmds), [])
        for c in (": > %s/note", "> %s/note", "exec 3>%s/note; echo hi >&3", "2>%s/note true"):
            self.assertEqual(self.not_allowed([c % self.clone]), [], c)

    KEYS = ("exec 3<K; cat <&3", "exec 3< K; cat <&3", "<K cat", "< K cat", "exec <K; cat", "exec < K", "{ <K cat; }", "( <K cat )", "true && <K cat", "0<K cat", "3<K cat <&3", "<K",
            "< K", "if true; then <K cat; fi", "<K head -c 5", "exec 4<K", "A=1 <K cat")

    def test_a_redirection_before_the_program_or_with_none_reads_the_key(self):
        cmds = [form.replace("K", self.key) for form in self.KEYS] + [form.replace("K", "$QARGI_CONF/credentials/marshal_ed25519") for form in self.KEYS[:6]]
        self.assertEqual(self.not_refused(cmds), [])
        for c in ("exec 3<%s/credentials/other; cat <&3", "<%s/credentials/other cat", "ls %s/credentials/marshal_ed25519", "< %s/credentials/other cat"):
            self.assertEqual(self.not_allowed([c % self.conf]), [], c)

    # --- finding 2: a cd is followed only when it is a plain command of the top level
    MAYBE_CD = ("(cd D); %s", "if false; then cd D; fi; %s", ": $(cd D); %s", "echo `cd D`; %s", "false && cd D; %s", "true || cd D; %s", "cd D & %s", "cd D | cat; %s",
                "for i in 1; do cd D; done; %s", "while false; do cd D; done; %s", "case x in y) cd D;; esac; %s", "f() { cd D; }; %s", "cd /nonexistent-zz; %s", "(cd /tmp; cd D) ; %s",
                "echo 'x\ncd D\ny'; %s", "# cd D\n%s", "true # ; cd D\n%s", "cat <<E\ncd D\nE\n%s")

    def test_a_cd_that_may_not_happen_does_not_move_the_judgment_of_the_next_write(self):
        """From the clone, under the read-only class, `(cd ../../out); echo x > a` writes into the clone; so does every form where the cd may not have changed
        the directory the next command runs in (a subshell, a substitution, a condition, a loop, a pipe, a background job, a directory that does not exist)."""
        want = ("echo x > a", "git commit -am x", "sed -i s/a/b/ x.sh", "cp /etc/hostname f", "touch n")
        cmds = [form.replace("D", "../../out") % w for form in self.MAYBE_CD for w in want[:2]]
        self.assertEqual(self.not_refused(cmds, cls="read-only"), [])

    def test_a_cd_into_a_protected_directory_followed_by_a_cd_that_may_not_happen_is_still_a_write_there(self):
        spots = [os.path.join(self.conf, "packs"), os.path.join(self.home, ".claude/skills"), os.path.join(self.home, ".claude/agents"), os.path.join(self.home, ".claude/plugins"),
                 os.path.join(self.conf, "credentials"), os.path.join(self.state, "features")]
        forms = ("cd %s && if false; then cd /tmp; fi; echo payload > evil.md", "cd %s; (cd /tmp); echo payload > evil.md", "cd %s; : $(cd /tmp); echo payload > evil.md",
                 "cd %s; false && cd /tmp; echo payload > evil.md", "cd %s; cd /tmp & echo payload > evil.md", "cd %s; cd /tmp | cat; echo payload > evil.md",
                 "cd %s; for i in 1; do cd /tmp; done; echo payload > evil.md", "cd %s; echo `cd /tmp`; cp /etc/hostname evil.md", "cd %s\n(cd /tmp)\ntee evil.md < /dev/null",
                 "cd %s; cd /nonexistent-zz; echo payload > evil.md", "cd %s; (cd /tmp; true); rm -rf evil.md", "pushd %s; (pushd /tmp); echo payload > evil.md")
        cmds = [f % d for d in spots for f in forms]
        for cls in (None, "read-only"):
            self.assertEqual(self.not_refused(cmds, cls=cls), [], cls)
        cmds = ["cd %s; echo payload > evil.md" % os.path.join(self.state, "x")]
        os.makedirs(os.path.join(self.state, "x"))
        self.assertEqual(self.not_allowed(cmds), [])

    def test_a_plain_cd_is_followed_and_a_line_is_not_read_twice_from_the_directory_it_left(self):
        """The line is cut more than once (with its substitutions left whole, and each substitution on its own): a relative cd applied once per cut would
        judge the next write from a directory that is not the one the shell is in."""
        ok = ("cd ../../out; echo x > report.md", "cd ../../out && echo x > report.md", "cd ../../out\necho x > report.md", "cd ../../out; echo \"$(date)\" > report.md",
              "cd ../../out && echo \"$(date)\" > report.md", "cd ../../out; echo `date` > report.md", "cd ../../out; echo $(true) x > report.md", "cd ../../out; cd .; echo x > report.md",
              "cd ../../out; cat <(echo a) > report.md", "cd -P ../../out; echo x > report.md", "cd -- ../../out; echo x > report.md", "cd ../../out || true; echo x > report.md",
              "cd ../../out; cd ../clone; cd ../out; echo x > report.md",
              "pushd ../../out; echo x > report.md; popd", "cd ../../out; mkdir -p d; cd d; echo x > report.md")
        self.assertEqual(self.not_allowed(ok, cls="read-only"), [])
        for c in ("cd ../../out; cd ..; cd clone; echo x > a", "cd ../../out; echo \"$(date)\" > ../clone/a", "cd ../../out; cd - ; echo x > a", "pushd ../../out; popd; echo x > a",
                  "cd ../../out; cd ../clone/sub; echo \"$(date)\" > a"):
            self.assertEqual(self.not_refused([c], cls="read-only"), [], c)

    # --- finding 3: the repository's own files named like the record do not make a run of a directory of the clone
    LOOK_ALIKES = ("tmpdir", "ability", "repo.path", "repo.url", "cred.path", "refs.before", "refs.after", "refs.diff")

    def make_look_alikes(self):
        for name in self.LOOK_ALIKES:
            with open(os.path.join(self.clone, "docs", name), "w") as f:
                f.write("repository content\n")
        for d in ("fake/clone", "fake/out", "pair"):
            os.makedirs(os.path.join(self.clone, d))
        for path in ("fake/ability", "fake/refs.before", "fake/class", "pair/ability", "pair/refs.before"):
            with open(os.path.join(self.clone, path), "w") as f:
                f.write("review\n" if path.endswith("ability") else "")

    def test_a_directory_of_the_clone_with_files_named_like_the_record_is_not_a_run(self):
        """A repository may hold docs/tmpdir, docs/ability and the like: is_run() took the directory for the run, so under the read-only class a write into
        docs/ was judged by a run whose clone it is not inside, and a build member could not edit the repository's own file."""
        self.make_look_alikes()
        for d in ("docs", "fake", "pair"):
            self.assertEqual(self.not_refused(["echo x > %s/f" % d, "touch %s/g" % d, "rm -f %s/h" % d, "sed -i s/a/b/ %s/f" % d, "cp /etc/hostname %s/" % d], self.clone, "read-only"), [], d)
            for tool, key in (("Write", "file_path"), ("Edit", "file_path")):
                r = self.call(tool, {key: os.path.join(self.clone, d, "f")}, self.clone, "read-only")
                self.assertEqual(r.returncode, 2, (d, tool, r.stderr))
            self.assertEqual(self.not_refused(["cd %s; echo x > f" % d, "cd %s && git commit -am x" % d], self.clone, "read-only"), [], d)
            r = self.call("Bash", {"command": "echo x > f"}, os.path.join(self.clone, d), "read-only")
            self.assertEqual(r.returncode, 2, (d, r.stderr))

    def test_a_build_member_edits_the_repositorys_own_files_named_like_the_record(self):
        self.make_look_alikes()
        cmds = []
        for d in ("docs", "fake", "pair"):
            cmds += ["echo x > %s/%s" % (d, n) for n in ("tmpdir", "ability", "refs.before", "class", "repo.path")]
            cmds += ["rm -f %s/ability" % d, "sed -i s/a/b/ %s/tmpdir" % d, "cp /etc/hostname %s/refs.before" % d, "mv %s/ability %s/ability.old" % (d, d), "touch %s/tmpdir" % d]
        self.assertEqual(self.not_allowed(cmds, self.clone), [])
        for tool, key in (("Write", "file_path"), ("Edit", "file_path")):
            for d in ("docs", "fake", "pair"):
                for n in ("tmpdir", "ability", "refs.before"):
                    r = self.call(tool, {key: os.path.join(self.clone, d, n)}, self.clone)
                    self.assertEqual(r.returncode, 0, (tool, d, n, r.stderr))
        r = self.call("Bash", {"command": "echo x > ability"}, os.path.join(self.clone, "docs"))
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_the_true_run_is_still_found_and_its_record_still_held(self):
        self.make_look_alikes()
        for c in ("echo x > ../../ability", "echo x > ../../tmpdir", "rm ../../refs.before", "cp /etc/hostname ../../class"):
            self.assertEqual(self.not_refused([c], os.path.join(self.clone, "docs")), [], c)
        for f in ("ability", "refs.before"):                                    # the two files moved away: the markers beside clone/ and out/ still say it is a run
            os.unlink(os.path.join(self.run_dir, f))
        self.assertEqual(self.not_refused(["echo x > ../../tmpdir"], os.path.join(self.clone, "sub")), [])
        self.assertEqual(self.not_refused(["echo x > docs/f"], self.clone, "read-only"), [])

    # --- finding 4: the run directory is not a destination for a copy, an extraction, a link, a move or a redirection (out/, clone/ and tmp/ are)
    INTO_RUN = ("cp -r /tmp/y/. R", "cp -r /tmp/y/. R/", "cp -a /tmp/y/. R/.", "cp -rT /tmp/y R", "cp -rt R /tmp/y", "cp -at R/ /tmp/y", "cp /tmp/ability R", "cp /tmp/ability R/.",
                "rsync -a /tmp/y/ R", "rsync -a /tmp/y/ R/", "rsync -a /tmp/y/ R/.", "rsync -aq --delete /tmp/y/ R/", "mv /tmp/ability R", "mv /tmp/ability R/", "mv -t R /tmp/ability",
                "ln -s /tmp/x R", "ln -t R /tmp/x", "install -Dt R /etc/hostname", "install -t R /etc/hostname", "install -D /etc/hostname R/", "ditto /tmp/y R", "ditto /tmp/y R/",
                "tar -C R -xf /tmp/rec.tar", "tar xf /tmp/rec.tar -C R", "tar -xf /tmp/rec.tar --directory=R", "tar -xf /tmp/rec.tar --directory R/.", "tar xzf /tmp/rec.tgz -C R/",
                "tar --extract -f /tmp/rec.tar -C R", "unzip /tmp/rec.zip -d R", "unzip -o /tmp/rec.zip -d R/", "unzip -d R /tmp/rec.zip", "unzip -dR /tmp/rec.zip", "unzip -od R /tmp/rec.zip",
                "touch R", "chmod -R 777 R", "mkdir -p R", "git -C R init", "git -C R checkout-index -a", "patch -d R -p0 < /tmp/rec.patch", "git apply --unsafe-paths --directory=R /tmp/rec.patch")

    def test_the_run_directory_itself_is_not_a_destination(self):
        """Copying a directory over the run directory (`cp -r Y/. ../..`) or extracting an archive there replaces the record the run is judged by (the files
        are made under the names they have in the source): the run directory as a destination, whatever way the path to it is written (`.`, `..`, a trailing
        `/.`, a relative path from where the shell is), is refused for every member."""
        from_sub = [c.replace("R", "../..") for c in self.INTO_RUN]
        from_run = [c.replace("R", ".") for c in self.INTO_RUN]
        from_clone = [c.replace("R/", "../").replace("R", "..") for c in self.INTO_RUN]
        absolute = [c.replace("R", self.run_dir) for c in self.INTO_RUN]
        for cls in (None, "read-only"):
            self.assertEqual(self.not_refused(from_sub, None, cls), [], ("clone/sub", cls))
            self.assertEqual(self.not_refused(from_run, self.run_dir, cls), [], ("run directory", cls))
            self.assertEqual(self.not_refused(from_clone, self.clone, cls), [], ("clone", cls))
            self.assertEqual(self.not_refused(absolute, None, cls), [], ("absolute", cls))

    def test_the_run_directory_is_still_a_destination_from_a_directory_the_guard_cannot_be_sure_of(self):
        cmds = ["cd ../..; tar xf /tmp/rec.tar", "cd ../.. && tar xf /tmp/rec.tar", "cd ../.. && cp -r /tmp/y/. .", "cd ../.. && cp -r /tmp/y/. ./", "cd ../..; unzip /tmp/rec.zip",
                "(cd ..); cp -r /tmp/y/. ../..", "cd ../..; ditto /tmp/y .", "pushd ../..; tar xf /tmp/rec.tar; popd", "cd ../../out; cd ..; rsync -a /tmp/y/ .", "cd ../../clone/..; tar xf /tmp/rec.tar",
                "if true; then cd ../..; fi; tar xf /tmp/rec.tar", "cd ../.. | cat; tar xf /tmp/rec.tar"]
        self.assertEqual(self.not_refused(cmds), [])
        self.assertEqual(self.not_refused(["cd ../..; tar xf /tmp/rec.tar", "cd ../.. && cp -r /tmp/y/. ."], os.path.join(self.clone, "docs"), "read-only"), [])

    def test_out_clone_and_tmp_of_the_run_and_a_file_of_its_own_name_are_still_destinations(self):
        os.makedirs(os.path.join(self.run_dir, "tmp"))
        ok = ["cp -r /tmp/y/. ../../out/", "rsync -a /tmp/y/ ../../out", "tar -C ../../out -xf /tmp/rec.tar", "cd ../../out && tar xf /tmp/rec.tar", "unzip /tmp/rec.zip -d ../../out", "install -D /etc/hostname ../../out/a/b",
              "ditto /tmp/y ../../out/", "echo x > ../../out/report.md", "mkdir -p ../../out/patches", "ln -s /tmp/x ../../out/l", "cp -r /tmp/y/. ../../tmp/", "tar -C ../../tmp -xf /tmp/rec.tar",
              "echo x > ../../tmp/f", "mkdir ../../tmp/work", "cp -r /tmp/y/. ../../clone/docs/", "tar -C ../../clone -xf /tmp/rec.tar", "unzip /tmp/rec.zip -d ../../clone/docs", "cp -r /tmp/y/. .",
              "tar xf /tmp/rec.tar", "unzip /tmp/rec.zip", "install -D /etc/hostname a/b", "echo x > ../../out/../out/r.md",
              "echo x > ../../notes", "touch ../../zz", "mkdir ../../zz", "cp /etc/hostname ../../newfile", "ln -s /tmp/x ../../link", "install -D /etc/hostname ../../sub/zz"]
        self.assertEqual(self.not_allowed(ok, None, None), [])
        self.assertEqual(self.not_allowed([c for c in ok if "clone" not in c and "docs" not in c and " ." not in c and "tar xf" not in c and "unzip /tmp" not in c and "install -D /etc/hostname a" not in c], None, "read-only"), [])
        for c in ("cp ../../contract/contract.md /tmp/x", "tar -C ../.. -cf /tmp/x.tar contract", "tar -cf /tmp/x.tar ../../contract", "unzip -l /tmp/rec.zip", "unzip -p /tmp/rec.zip | wc -c",
                  "tar -tf /tmp/rec.tar", "rsync -a ../../contract/ /tmp/y/", "ls ../.. > /dev/null", "cat ../../contract/contract.md", "git -C ../../clone log --oneline"):
            self.assertEqual(self.not_allowed([c], None, None), [], c)
        for tool, key in (("Write", "file_path"), ("Edit", "file_path")):
            for name, want in ((".", 2), ("", 2), ("notes", 0), ("contract/contract.md", 0), ("out/report.md", 0), ("clone/docs/f", 0), ("tmp/f", 0)):
                r = self.call(tool, {key: os.path.join(self.run_dir, name)}, None, None)
                self.assertEqual(r.returncode, want, (tool, name, r.stderr))

    # --- finding 7: the time the hook has (it is killed at 20 seconds and a hook that is killed does not block)
    def hostile(self):
        K = 200_000
        return {
            "qargi project x12000 then a write": "qargi project " * 12000 + "; echo x > ../../ability",
            "qargi project x3000": "qargi project " * 3000,
            "brace words 5000": " ".join("cp a{b,c}{d,e}{f,g}{h,i}{j,k}{l,m}%d" % k for k in range(5000)),
            "empty braces x13000": "cat " + " ".join("{,}{,}{,}{,}{,}{,}" for k in range(13000)),
            "empty braces, each different, x12000": "cat " + " ".join("{,}{,}{,}{,}{,}%d" % k for k in range(12000)),
            "unique touch 20k": ";".join("touch f%d" % k for k in range(K // 10)),
            "unique redirection 20k": ";".join("echo>g%d" % k for k in range(K // 10)),
            "a; x 100k": "a;" * (K // 2),
            "$(a) x 20k": "echo " + "$(a)" * (K // 4),
            "unclosed $( x 40 and text": "$(" * 40 + "a " * (K // 2 - 50),
            "redirection >a x 20k": "echo " + " >a" * (K // 4),
            "sh -c chain 5000": ";".join("sh -c x%d" % k for k in range(5000)),
            "cd chain 10000": ";".join("cd d%d" % k for k in range(10000)) + "; echo x > a",
            "one word 200 KB": "echo " + "a" * K,
            "key words 20000": "cat " + " ".join("/usr/lib/x%d" % k for k in range(20000)),
            "globs in every word": "cat " + " ".join("~/.qargi/config/*/*%d" % k for k in range(2000)),
            "2000 heredocs": "\n".join("cat <<E%d\nqq\nE%d" % (k, k) for k in range(2000)),
            "260 KB of blanks between two words": "echo a" + " " * 260000 + "b",
            "tabs and blanks": "echo a" + " \t" * 100000 + "b",
            "marshal handoff x12000": "marshal handoff " * 12000,
            "project set x20000": "project set " * 20000,
            "packs_audit.py x15000": "packs_audit.py " * 15000,
        }

    def test_the_hostile_commands_of_the_review_are_judged_well_inside_the_hooks_timeout(self):
        """Whole hook processes, as Claude Code runs them: a verdict, allowed or refused, well inside the hook's timeout of 20 seconds (BUDGET, checked in every
        loop, is 5; the bound here is 15 for a busy machine), so the hook never reaches it. The loops were checked once per segment, and a word, a brace or a project word could cost 25 seconds."""
        from concurrent.futures import ThreadPoolExecutor
        inputs = self.hostile()

        def run(c):
            t0 = time.monotonic()
            r = self.call("Bash", {"command": c})
            return r, time.monotonic() - t0
        with ThreadPoolExecutor(4) as ex:
            got = dict(zip(inputs, ex.map(run, inputs.values())))
        slow = {n: round(t, 1) for n, (r, t) in got.items() if t >= 15.0}
        self.assertEqual(slow, {})
        for name in ("qargi project x12000 then a write", "brace words 5000", "empty braces, each different, x12000", "cd chain 10000"):
            self.assertEqual(got[name][0].returncode, 2, (name, got[name][0].stderr[:200]))
        self.assertIn("ability", got["qargi project x12000 then a write"][0].stderr)

    def test_a_brace_list_is_checked_whole_or_refused_never_cut(self):
        """Only the first 64 words of a brace expression were looked at: the signing key placed before the 64th was not."""
        names = ",".join("a%d" % k for k in range(100))
        key = os.path.join(self.conf, "credentials")
        cmds = ["cat %s/{marshal_ed25519,%s}" % (key, names), "cat %s/{%s,marshal_ed25519}" % (key, names), "cat %s/{%s,marshal_ed25519,%s}" % (key, names, names),
                "cat %s/{%s}" % (key, ",".join("x%d" % k for k in range(300))), "cat {%s}{%s}" % (names, names)]
        self.assertEqual(self.not_refused(cmds), [])
        self.assertEqual(self.not_allowed(["echo x > %s/{a,b,c}/x" % self.clone, "touch %s/{a,b}{1,2,3}" % self.clone, "cat %s/{credentials/other,packs}" % self.conf,
                                           "cat %s/{other,a1,a2}" % key]), [])

    def test_a_loop_inside_one_command_is_cut_short_by_the_time_budget(self):
        """The budget is read inside the loops (the words of a segment, its write targets, the project words, the brace words), not once per segment: with
        0.2 seconds left, each of these single segments is cut short by its own loop and not by the next check made after it."""
        J = _Judge(LIBDIR, "guard_budget", self.clone)
        G = J.m
        words = ["/usr/lib/x%d" % k for k in range(15000)]
        loops = {"key words": lambda: G.key_read(["cat"] + words, 0, self.clone), "write targets": lambda: G.protected_write(["touch"] + words, 0, self.clone),
                 "review of the targets": lambda: G.review_segment(["touch"] + words, 0, self.clone, "touch"),
                 "project words": lambda: G.unreadable_project_verb("qargi project " * 12000),
                 "brace words": lambda: [G.brace_expand("a{b,c}{d,e}%d" % k) for k in range(100000)]}
        for name, run in loops.items():
            getattr(G, "clear_caches", lambda: None)()
            G._DEADLINE[0] = time.monotonic() + 0.2
            t0 = time.perf_counter()
            try:
                with self.assertRaises(G.TooSlow, msg=name):
                    run()
            finally:
                G._DEADLINE[0] = None
            self.assertLess(time.perf_counter() - t0, 5.0, name)

    def test_what_is_read_from_the_files_is_read_again_for_each_call(self):
        """The reading of the run's files is kept for the call that made it, not for the next: a judge that outlives one call sees the file as it is then."""
        J = _Judge(LIBDIR, "guard_calls", os.path.join(self.clone, "sub"))
        ability = os.path.join(self.run_dir, "ability")
        for text, refused in (("review\n", True), ("build\n", False), ("review\n", True)):
            with open(ability, "w") as f:
                f.write(text)
            self.assertEqual(bool(J.judge("echo x > f")), refused, text)

    # --- finding 9: `qargi local clean` removes the temporary directory the lead's registry names for the run, so the registry is the lead's alone
    def test_the_registry_of_local_runs_is_the_leads_alone(self):
        reg = os.path.join(self.state, "local-runs.jsonl")
        with open(reg, "w") as f:
            f.write("{}\n")
        os.symlink(reg, os.path.join(self.clone, "to-registry"))
        cmds = ["echo '{}' >> %s" % reg, "echo x > %s" % reg, "cp /etc/hostname %s" % reg, "sed -i s/a/b/ %s" % reg, "tee -a %s < /dev/null" % reg, "rm %s" % reg, "mv %s /tmp/x" % reg,
                "echo x > %s.1" % reg, "echo x > %s.lock" % reg, "truncate -s0 %s" % reg, ">%s" % reg, "exec 3>>%s" % reg, "echo x >> %s/to-registry" % self.clone, "jq -c . %s > %s.new" % (reg, reg),
                "cd %s && echo x >> local-runs.jsonl" % self.state, "mv /tmp/x %s" % reg, "ln -sf /tmp/x %s" % reg]
        for cls in (None, "read-only"):
            wrong = [(c, r.stderr.strip()[:100]) for c, r in self.table(cmds, cls=cls) if r.returncode != 2 or "registry of local runs" not in r.stderr]
            self.assertEqual(wrong, [], cls)
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")):
            for path in (reg, reg + ".tmp", os.path.join(self.clone, "to-registry")):
                r = self.call(tool, {key: path})
                self.assertEqual(r.returncode, 2, (tool, path, r.stderr))
                self.assertIn("registry of local runs", r.stderr)
        self.assertEqual(self.not_allowed(["cat %s" % reg, "jq -c . %s" % reg, "wc -l %s" % reg, "grep -c run %s" % reg, "jq -r .run %s | sort > %s/out/runs.txt" % (reg, self.run_dir)]), [])

    # --- two refusals of work that is allowed (read-only class)
    def test_tee_with_an_input_redirection_writes_only_what_it_names(self):
        """`tee OUT/report.md < r.md`: the `<` and the file after it are no operand of tee, so no file named r.md is written (it is a file of the clone)."""
        o = self.out
        ok = ["tee %s/report.md < r.md" % o, "tee -a %s/report.md <r.md" % o, "tee %s/x 0< r.md" % o, "tee %s/x <<< hello" % o, "tee %s/x << EOF\nhi\nEOF" % o, "cat r.md | tee %s/x" % o,
              "tee %s/a %s/b < r.md" % (o, o), "sort r.md | tee %s/s.txt < /dev/null" % o, "cp %s/a %s/b < /dev/null" % (o, o), "tee %s/x 2> /dev/null < r.md" % o]
        self.assertEqual(self.not_allowed(ok, None, "read-only"), [])
        bad = ["tee r.md < /dev/null", "tee %s/x r.md < r.md" % o, "tee %s/x < r.md > f" % o, "tee %s/x <r.md; tee f < /dev/null" % o, "tee 0< r.md f"]
        self.assertEqual(self.not_refused(bad, None, "read-only"), [])

    def test_a_command_whose_names_come_from_its_input_is_still_a_write_under_the_read_only_class(self):
        """Leaving `< FILE` out of the operands of tee must not let through the commands whose input says what they write: patch writes the files the patch
        names, and xargs hands the names of its command from its standard input. The old guard refused them only because it took `<` and FILE for operands."""
        bad = ["patch -p1 < p", "patch < p", "patch -p1 <p", "xargs touch < l", "xargs rm < l", "xargs cp -t . < l", "xargs sed -i s/a/b/ < l", "patch -p0 -i p"]
        self.assertEqual(self.not_refused(bad, None, "read-only"), [])
        self.assertEqual(self.not_allowed(["patch -p1 -d %s < p" % self.out, "xargs touch < l", "patch -p1 < p"], None, None), [])

    def test_a_brace_word_is_judged_as_the_words_it_stands_for(self):
        """cp a ~/.claude/{x,skills}/ writes the skills directory, and echo x > OUT/{a,../clone/b} the clone: the word was judged as it is written."""
        h, c, o = os.path.join(self.home, ".claude"), self.clone, self.out
        bad = ["cp a %s/{x,skills}/" % h, "echo x > %s/{x,skills}/f" % h, "touch %s/{skills,x}/q" % h, "tee %s/{x,agents}/f < /dev/null" % h, "rm -rf %s/{x,plugins}" % h,
               "cp a %s/{x,packs}/f" % self.conf, "tee %s/{x,packs}/f < /dev/null" % self.conf, "echo x > %s/{x,features}/f" % self.state, "mv a %s/{ref-journal.jsonl,y}" % self.state]
        self.assertEqual(self.not_refused(bad), [])
        ro = ["echo x > %s/{a,../clone/b}" % o, "touch %s/{a,../clone/b}" % o, "cp a %s/{,../clone/}a" % o, "echo x > %s/{a,b}" % c]
        self.assertEqual(self.not_refused(ro, None, "read-only"), [])
        self.assertEqual(self.not_allowed(["echo x > %s/{a,b}" % o, "touch %s/{a,b}{1,2}" % o, "cp a %s/{x,y}/f" % self.clone, "touch %s/{x,y}" % self.t], None, None), [])
        self.assertEqual(self.not_allowed(["echo x > %s/{a,b}" % o, "touch %s/{a,b}{1,2}" % o], None, "read-only"), [])

    OUT_WORDS = ('sort -o "$OUT/s.txt" r.md', 'git format-patch --binary BASE..HEAD -o "$OUT/patches"', 'git bundle create "$OUT/run.bundle" BASE..HEAD', "echo x > $OUT/report.md",
                 "echo x > ${OUT}/report.md", 'git diff --output="$OUT/d.patch"', 'cp r.md "$OUT/"', 'git log > "${OUT}/log.txt"', "mkdir -p $OUT/patches && cp r.md $OUT/patches/", "cd $OUT; echo x > f", "cd $OUT && git log > report.md")

    def test_out_is_the_runs_out_when_nothing_in_the_command_sets_it(self):
        """$OUT is not in the hook's environment, so the guard cannot expand it and refused every write through it under the read-only class. It reads it
        from the run record (RUN/out) when nothing in the command could set it."""
        self.assertEqual(self.not_allowed(list(self.OUT_WORDS), None, "read-only"), [])
        c = self.clone
        bad = ["OUT=%s; echo x > $OUT/f" % c, "OUT=%s echo x > $OUT/f" % c, "export OUT=%s; echo x > $OUT/f" % c, 'eval "OUT=%s"; echo x > $OUT/f' % c, "declare OUT=%s; echo x > $OUT/f" % c,
               "read OUT <<< %s; echo x > $OUT/f" % c, "printf -v OUT %%s %s; echo x > \"$OUT/f\"" % c, "echo x > ${OUT:-%s}/f" % c, "bash -c 'OUT=%s; echo x > $OUT/f'" % c,
               "for OUT in %s; do echo x > $OUT/f; done" % c, "echo x > $OUT/../clone/f", "echo x > $OUT/../ability", "echo x > ${OUT}/../clone/f", "v=OUT; eval $v=%s; echo x > $OUT/f" % c,
               "source ./set-out.sh; echo x > $OUT/f", ". ./set-out.sh; echo x > $OUT/f", "local OUT=%s; echo x > $OUT/f" % c,
               "echo x > $OUT2/f", "echo x > $OUTPUT/f", "set -a; OUT=%s; echo x > $OUT/f" % c, "echo x > ${!v}/f"]
        self.assertEqual(self.not_refused(bad, None, "read-only"), [])
        self.assertEqual(self.not_refused(["echo x > $OUT/../clone/f"], self.out, "read-only"), [])
        r = self.call("Bash", {"command": "echo x > $OUT/report.md"}, "/tmp", "read-only")                  # no run is found from here: nothing is guessed
        self.assertEqual(r.returncode, 2, r.stderr)


class FifthReview(unittest.TestCase):
    """The fifth audit of the Bash reader (guard-r5): every command here was run against the hook and allowed, and is refused now (the first two tests), or was
    refused for the wrong reason and is allowed now (the *_stay_allowed tests). The base is ThirdReview's: a run directory with every protected location."""
    tearDown, env, call, table, not_refused, not_allowed = (ThirdReview.tearDown, ThirdReview.env, ThirdReview.call, ThirdReview.table, ThirdReview.not_refused,
                                                            ThirdReview.not_allowed)

    def setUp(self):
        ThirdReview.setUp(self)
        for d in ("home/.config/git", "home/.ssh", "home/.claude/commands", "home/.claude/hooks"):
            os.makedirs(os.path.join(self.t, d), exist_ok=True)
        for name in ("home/.gitconfig", "home/.config/git/config", "home/.claude/settings.json", "home/.claude.json", "home/.claude/CLAUDE.md", "home/.bashrc", "home/.ssh/config"):
            with open(os.path.join(self.t, name), "w") as f:
                f.write("\n")
        self.skill = self.targets["skills"]

    # --- G1: $'...' and $"..." quoting hides no word
    def test_ansi_c_and_translated_quotes_do_not_hide_a_word(self):
        k, s = self.key, self.skill
        bad = ["git $'push'", "git $'pu\\x73h'", "git $'\\160ush'", "git p$'ush'", "git $'pu'sh", "qargi $'packs' link p", 'qargi $"packs" link p', "qargi packs $'link' p",
               "eval $'git push'", "bash -c $'git push'", "sh -c $'qargi skill new x'", "echo x | xargs $'git' push", "gh $'api' x", "$'ssh' host",
               "echo x > $'%s'" % s, 'echo x > $"%s"' % s, "cp a $'%s'" % s, "tee $'%s' < /dev/null" % s, "cat $'%s'" % k, "cat %s/$'marshal_ed25519'" % os.path.dirname(k),
               'cat %s/$"marshal_ed25519"' % os.path.dirname(k), "cat %s/marshal_$'ed25519'" % os.path.dirname(k), "echo x > $'%s'" % self.targets["packs"],
               "qargi marshal $'claim' p", "cat $'\\x2f'%s" % k[1:]]
        self.assertEqual(self.not_refused(bad), [])
        ok = ["git status", "git log -S push", "echo $'a\\nb'", "git commit -m $'two\\nlines'", "qargi skill list", "echo $'x' > %s/f" % self.out, "echo '$'x", "echo \"cost $'5'\"",
              "grep -n $'\\t' f", "printf $'%s\\n' hi"]
        self.assertEqual(self.not_allowed(ok), [])

    def test_a_verb_the_shell_builds_is_refused(self):
        bad = ["git pu$()sh", "git pu${x}sh", 'git pu"$x"sh', "git pu`true`sh", "git $x", 'git "$@"', "git -C . $sub origin", "qargi pa$()cks link p", "qargi packs li${x}nk p", "qargi skill $v new x",
               'qargi "$v" link p', "qargi $a $b", "qargi lo$()cal run", "qargi local $v"]
        self.assertEqual(self.not_refused(bad), [])
        ok = ["git status $x", 'git commit -m "$m"', 'git -C "$d" status', "qargi review check $OUT", "qargi local run", 'qargi memory get "$k"', "qargi skill list $x"]
        self.assertEqual(self.not_allowed([c for c in ok if c != "qargi local run"]), [])

    # --- G2: git -c, --exec-path and the environment of git that give a command another name or run a program
    def test_git_options_and_variables_that_give_git_another_command_are_refused(self):
        bad = ["git -c alias.p=push p", 'git -c alias.p="!git push" p', "git -c alias.co=checkout co -- .", "git -c ALIAS.P=push p", "git -c core.pager=x log", "git -c core.editor=x commit",
               "git -c core.fsmonitor=x status", "git -c core.hooksPath=/x commit", "git -c core.sshCommand=x fetch", "git -c diff.external=x diff", "git -c credential.helper=x fetch",
               "git -c include.path=/x status", "git -c includeIf.gitdir:/.path=/x status", "git --exec-path=/x status", "git --config-env=alias.p=V p",
               "git -c user.name=t -c alias.p=push p", "git -C . -c alias.p=push p", "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.p GIT_CONFIG_VALUE_0=push git p",
               "GIT_CONFIG_PARAMETERS=\"'alias.p=push'\" git p", "GIT_EXEC_PATH=/x git status", "GIT_SSH_COMMAND=x git fetch", "env GIT_CONFIG_GLOBAL=/x git p", "GIT_EXTERNAL_DIFF=x git diff"]
        self.assertEqual(self.not_refused(bad), [])
        self.assertEqual(self.not_refused(["git -c alias.co=checkout co -- ."], None, "read-only"), [])
        ok = ["git -c user.name=t -c user.email=t@x commit -m x", "git -c color.ui=never diff", "git -c safe.directory=/x status", "git --no-pager log", "git --exec-path", "git -c core.autocrlf=false add f"]
        self.assertEqual(self.not_allowed(ok), [])

    # --- G3: the other ways to publish
    def test_the_other_push_paths_are_refused(self):
        bad = ["git send-pack origin x", "git http-push http://h/r x", "git-push origin", "git-send-pack o", "/usr/lib/git-core/git-receive-pack r", "git -C . send-pack o",
               "git svn dcommit", "git svn dcommit --rmdir", "git-svn dcommit", "svn dcommit", "rsync -a build/ host:dst/", "rsync -a build/ user@host:dst", "rsync -a build/ rsync://h/m/",
               "rsync -avz -e ssh host:src dst", "rsync --delete . [::1]:dst", "sudo rsync -a x h:y", "timeout 9 rsync -a x h:y"]
        self.assertEqual(self.not_refused(bad), [])
        ok = ["rsync -a build/ dst/", "rsync -a ./a:b dst/", "rsync -a --exclude=a:b src/ dst/", "git svn log", "git svn info", "git remote -v", "git fetch origin", "svn log"]
        self.assertEqual(self.not_allowed(ok), [])

    # --- G14: only the subcommand names the verb
    def test_a_word_push_that_is_no_subcommand_stays_allowed(self):
        ok = ["git commit -m push", "git commit -m 'make push work'", "git log -S push", "git log --grep push", "git grep push", "git help push", "git config user.name push",
              "git -C push status", "git checkout -b push", "git branch push", "git tag push", "git show push", "git log push", "git diff push..HEAD"]
        self.assertEqual(self.not_allowed(ok), [])
        self.assertEqual(self.not_refused(["git push", "git -C sub push", "git --no-pager -c user.name=t push", "git -C push push"]), [])

    # --- G4: --work-tree and GIT_WORK_TREE name where the tree is changed, as -C does
    def test_a_work_tree_option_is_the_target_of_a_git_command_that_changes_the_tree(self):
        s = os.path.dirname(self.skill)
        bad = ["git --work-tree=%s checkout -- ." % s, "git --work-tree %s checkout -- ." % s, "GIT_WORK_TREE=%s git checkout -- ." % s, "env GIT_WORK_TREE=%s git reset --hard" % s,
               "git -C . --work-tree=%s restore ." % s, "git --git-dir=.git --work-tree=%s clean -fdx" % s, "git --work-tree=%s/.. checkout -- ." % s]
        self.assertEqual(self.not_refused(bad), [])
        self.assertEqual(self.not_allowed(["git --work-tree=. checkout -- .", "git --work-tree=%s status" % s, "git -C %s status" % self.clone]), [])

    # --- G5: the lead's own git configuration
    def test_the_leads_own_git_configuration_is_not_written_by_any_member(self):
        h = os.path.join(self.t, "home")
        bad = ["echo x > ~/.gitconfig", "echo x >> %s/.gitconfig" % h, "echo x > ~/.config/git/config", "cp a ~/.config/git/ignore", "tee ~/.gitconfig < /dev/null", "rm ~/.gitconfig",
               "git config --global user.name x", "git config --global alias.p x", "git config --system core.editor x", "git config --global --unset alias.p",
               "git config --global --add include.path /x", "git config --global --edit", "git config --file /tmp/x alias.p x", "git config -f %s/x alias.p x" % self.t,
               "git config --file=%s/x alias.p x" % self.out, "git -C ~ init", "git init ~", "git init %s" % h, "mkdir ~/.git", "echo x > ~/.git/config"]
        for cls in (None, "read-only"):
            self.assertEqual(self.not_refused(bad, None, cls), [], cls)
        self.assertEqual(self.not_allowed(["cat ~/.gitconfig", "git config --global user.name", "git config --global --get user.name", "git config --global --list", "git config --list",
                                           "git config --file .gitmodules submodule.a.url u", "git init sub2", "git config user.name x", "grep -n alias ~/.config/git/config"]), [])
        self.assertEqual(self.call("Write", {"file_path": "~/.gitconfig"}).returncode, 2)
        self.assertEqual(self.call("Edit", {"file_path": h + "/.config/git/config"}).returncode, 2)

    # --- G6: the lead's own session settings and shell startup files
    def test_the_leads_session_settings_and_startup_files_are_not_written_by_any_member(self):
        h = os.path.join(self.t, "home")
        files = ("~/.claude/settings.json", "~/.claude/settings.local.json", "~/.claude/CLAUDE.md", "~/.claude.json", "~/.claude/commands/c.md", "~/.claude/hooks/h.sh", "~/.bashrc",
                 "~/.bash_profile", "~/.profile", "~/.zshrc", "~/.ssh/config", "~/.ssh/authorized_keys", h + "/.claude/settings.json", "$HOME/.bashrc")
        bad = [form % f for f in files for form in ("echo x > %s", "echo x >> %s", "tee %s < /dev/null", "cp a %s", "touch %s", "rm %s", "sed -i s/a/b/ %s")]
        bad += ["mkdir ~/.claude/hooks/new", "rm -rf ~/.claude/commands", "mv a ~/.claude/commands/", "cd ~ && echo x >> .bashrc", "ln -sf /x ~/.bashrc"]
        for cls in (None, "read-only"):
            self.assertEqual(self.not_refused(bad, None, cls), [], cls)
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("NotebookEdit", "notebook_path")):
            for f in ("~/.claude/settings.json", "~/.claude/CLAUDE.md", "~/.claude.json", "~/.claude/hooks/h.sh", "~/.bashrc", "~/.ssh/config"):
                self.assertEqual(self.call(tool, {key: f}).returncode, 2, (tool, f))
        ok = ["cat ~/.bashrc", "grep -n hooks ~/.claude/settings.json", "ls ~/.claude/commands", "echo x > ~/.claude/history.jsonl", "echo x > ~/.claude/todos/t.json", "echo x > ~/.ssh/known_hosts", "echo x > ~/.cache/x"]
        self.assertEqual(self.not_allowed(ok), [])
        self.assertEqual(self.call("Write", {"file_path": "~/.claude/history.jsonl"}).returncode, 0)

    # --- G17: the read-only class writes OUT and TMP, in Bash as with the file tools, and nothing else
    def test_the_read_only_class_writes_out_and_tmp_and_nothing_else_in_bash_and_with_the_file_tools(self):
        tmp = os.path.join(self.t, "shm-tmp")
        os.makedirs(tmp)
        with open(os.path.join(self.state, "local-runs.jsonl"), "w") as f:
            f.write(json.dumps({"run": self.run_dir, "tmpdir": tmp}) + "\n")
        runtmp = os.path.join(self.run_dir, "tmp")
        os.makedirs(runtmp)
        allowed = ["echo x > %s/report.md" % self.out, "echo x > %s/n" % tmp, "echo x > %s/n" % runtmp, "cp r %s/" % tmp, "git log > %s/l" % tmp, "echo x > /dev/null", "echo x > /dev/stderr",
                   "sort -o %s/s f" % tmp, "tee %s/t < /dev/null" % self.out]
        self.assertEqual(self.not_allowed(allowed, None, "read-only"), [])
        elsewhere = os.path.join(self.t, "elsewhere")
        refused = ["echo x > %s" % elsewhere, "echo x > %s/notes" % self.run_dir, "echo x > /tmp/qargi-zzz", "touch %s" % elsewhere, "cp r %s" % elsewhere, "echo x > ~/.claude/history.jsonl",
                   "echo x > %s/n" % self.t, "mkdir %s/d" % self.t, "tee %s < /dev/null" % elsewhere, "sed -i s/a/b/ %s" % elsewhere, "echo x > %s/../n" % tmp]
        self.assertEqual(self.not_refused(refused, None, "read-only"), [])
        self.assertEqual(self.not_allowed(refused[:3], None, None), [])
        for tool in ("Write", "Edit"):
            for f in (os.path.join(self.out, "report.md"), os.path.join(tmp, "n"), os.path.join(runtmp, "n")):
                self.assertEqual(self.call(tool, {"file_path": f}, None, "read-only").returncode, 0, (tool, f))
            for f in (os.path.join(self.run_dir, "notes"), elsewhere, os.path.join(self.clone, "a.go")):
                r = self.call(tool, {"file_path": f}, None, "read-only")
                self.assertEqual(r.returncode, 2, (tool, f))
                self.assertIn("report and the manifest in OUT", r.stderr)
        for f in ("ability", "class", "tmpdir"):
            self.assertEqual(self.call("Write", {"file_path": os.path.join(self.run_dir, f)}, None, "read-only").returncode, 2, f)

    # --- G7: a cd the guard cannot read leaves the directory unknown, and a relative write after it is refused
    def test_a_cd_to_a_directory_the_guard_cannot_name_makes_a_relative_write_unreadable(self):
        s = os.path.dirname(self.skill)
        bad = ["cd $(dirname $PWD); echo x > ability", 'cd "$(echo %s)" && echo x > x/SKILL.md' % s, "cd `dirname $PWD` && echo x > class", "builtin cd .. && echo x > ability", "command cd .. && touch ability", "CDPATH=.. cd clone && echo x > ability", "export CDPATH=..; cd clone; echo x > ability",
               "env -C .. touch ability", "env -C .. tee ability < /dev/null", "env --chdir=.. touch ability", "env -i -C .. touch ability", "env -C '$d' touch x",
               "for d in $(ls ..); do cd $d; echo x > ability; done", "for d in a b; do cd $d; touch ability; done", 'cd "$d" && cp a b', "cd $UNSET_VAR && tar xf x.tar",
               "cd $d && sed -i s/a/b/ ability", "cd ../* && echo x > ability"]
        for cls in (None, "read-only"):
            self.assertEqual(self.not_refused(bad, self.clone, cls), [], cls)
        ok = ["cd $(git rev-parse --show-toplevel) && git commit -m x", "cd $d && echo x > /tmp/ok", "cd $d && cat ability", "cd sub && echo x > f", "cd $d; cd %s; echo x > a.txt" % self.clone,
              'cd "$HOME" && echo x > f', "cd $d && echo x > $HOME/f", "env -C sub touch f", "builtin cd sub && touch f"]
        self.assertEqual(self.not_allowed(ok, self.clone, None), [])

    # --- G8: ${NAME:-x}, ${NAME%/} and the like are read by the value of NAME, or refused
    def test_a_braced_expansion_with_an_operator_is_read_by_its_variable_or_refused(self):
        h, cred = os.path.join(self.t, "home"), os.path.join(self.conf, "credentials")
        bad = ["echo x > ${HOME%/}/.claude/skills/x/SKILL.md", "echo x > ${HOME:-/nonexistent}/.claude/skills/x/SKILL.md", "echo x > ${HOME:+%s}/.claude/skills/x/SKILL.md" % h,
               "echo x > ${UNSET_NAME:-%s}/.claude/skills/x/SKILL.md" % h, "echo x > ${UNSET_NAME}/f", "tee ${UNSET_NAME%/}/f < /dev/null", "touch ${UNSET_NAME:-.}/f",
               "cp a ${UNSET_NAME:-%s}/packs/x" % self.conf, "rm -rf ${UNSET_NAME:-%s}/.claude/skills" % h,
               "cat ${QARGI_CONF%/}/credentials/marshal_ed25519", "cat ${UNSET_NAME:-%s}/marshal_ed25519" % cred, "cat ${UNSET_NAME:-%s}/marshal_*" % cred,
               "grep -r x ${UNSET_NAME:-%s}" % cred, "cp -r ${UNSET_NAME:-.} %s/y" % self.out]
        self.assertEqual(self.not_refused(bad), [])
        ok = ["echo x > ${HOME}/note.txt", "echo x > ${HOME:-/x}/note.txt", "echo x > ${HOME%/}/note.txt", "cat ${UNSET_NAME:-f}", "cat ${UNSET_NAME:-%s}/other" % cred,
              "echo ${UNSET_NAME:-x} > f", "git commit -m ${UNSET_NAME:-x}", "cat ${QARGI_CONF%/}/credentials/other"]
        self.assertEqual(self.not_allowed(ok), [])

    # --- G12: the lead's runs and agents
    def test_a_member_may_not_prepare_verify_clean_or_dispatch(self):
        verbs = ["local clean RUN", "local clean RUN --discard", "local prepare P build", "local verify RUN", "agent remove m", "project new p", "team run t", "task x", "local run RUN"]
        bad = [form % v for v in verbs for form in ("qargi %s", "/opt/q/bin/qargi %s", "sudo qargi %s", "cd src && qargi %s", "bash -c 'qargi %s'", "eval 'qargi %s'", "echo $(qargi %s)",
                                                    "timeout 5 qargi %s")]
        bad += ["./lib/local.sh clean RUN", "bash lib/agent.sh remove m", "bash lib/team.sh run t", "qargi local $v RUN"]
        self.assertEqual(self.not_refused(bad), [])
        r = self.call("Bash", {"command": "qargi local clean RUN --discard"})
        self.assertIn("is the lead's", r.stderr)
        ok = ["qargi local list", "qargi local status RUN", "qargi agent list", "qargi project show p", "qargi team brief t", "qargi review check out", "qargi agent for build", "qargi project validate p"]
        self.assertEqual(self.not_allowed(ok), [])

    # --- G13: the destination of a copy and a search above the credentials directory are no read of the key
    def test_a_directory_above_the_credentials_is_a_place_to_write_and_to_search(self):
        h, cred = os.path.join(self.t, "home"), os.path.join(self.conf, "credentials")
        ok = ["cp src/a.go ~/", "mv x ~/", "rsync -a build/ ~/", "tar -C ~ -xf x.tar", "tar -xf x.tar -C ~", "tar -xf x.tar --directory=~", "cp -t ~ src/a.go", "cp -rt ~ src/a.go",
              "cp -t %s a.go" % self.t, "mv x %s/" % self.conf, "cp -r src %s/" % self.conf, "grep -r TODO ~", "grep -rn TODO %s" % self.conf, "grep -r TODO %s" % self.t, "rg TODO %s" % self.conf,
              "find ~ -name x", "find %s -name x -type f" % self.t, "rsync -a build/ %s/" % self.conf, "install -m 644 a %s/" % self.conf]
        self.assertEqual(self.not_allowed(ok), [])
        self.assertEqual(self.call("Grep", {"pattern": "x", "path": "~"}).returncode, 0)
        self.assertEqual(self.call("Grep", {"pattern": "x", "path": self.conf}).returncode, 0)
        k = os.path.join(cred, "marshal_ed25519")
        bad = ["cp -r %s /tmp/y" % self.conf, "cp -rt /tmp/y %s" % self.conf, "cp -r %s /tmp/y" % cred, "cp %s /tmp/y" % k, "cp -t /tmp/y %s" % k, "mv %s /tmp/y" % self.conf,
               "rsync -a %s/ /tmp/y/" % self.conf, "rsync -a %s /tmp/y/" % k, "tar czf /tmp/o.tgz %s" % self.conf, "tar czf /tmp/o.tgz -C %s ." % self.conf, 
               "tar -xf %s -C /tmp" % k, "zip -r /tmp/o.zip %s" % self.conf, "ln -s %s /tmp/lnk" % self.conf, "ln -s %s /tmp/lnk" % cred,
               "grep -r BEGIN %s" % cred, "grep BEGIN %s" % k, "rg BEGIN %s" % cred, "find %s -type f -exec cat {} +" % cred, "cd %s && grep -r BEGIN ." % cred,
               "cat %s" % k, "cat < %s" % k, "< %s" % k, "cp %s ~/" % k, "cp -r %s ~/" % cred]
        self.assertEqual(self.not_refused(bad), [])
        self.assertEqual(self.call("Grep", {"pattern": "x", "path": cred}).returncode, 2)
        self.assertIn("a redirection on", self.call("Bash", {"command": "< %s" % k}).stderr)

    # --- G9: a link to a protected location
    def test_a_link_to_a_protected_location_is_refused_where_it_is_made(self):
        h, s = os.path.join(self.t, "home"), os.path.dirname(self.skill)
        bad = ["ln -s %s dst" % s, "ln -s %s dst" % h, "ln -s ~/.claude/skills/x dst", "ln -s %s/x dst; echo x > dst/SKILL.md" % s, "ln -sf %s dst" % self.conf, "ln -s %s/packs dst" % self.conf,
               "ln -s %s/features dst" % self.state, "ln -s %s dst/" % self.t, "ln %s dst" % self.skill, "ln -s -t dst %s" % self.skill, "ln -s ../../../home/.claude/skills dst"]
        self.assertEqual(self.not_refused(bad, self.clone), [])
        ok = ["ln -s /etc/hostname dst", "ln -s ../a b", "ln -s %s/sub x" % self.clone, "ln -s %s/f %s/l" % (self.out, self.out), "ln -s sub x"]
        self.assertEqual(self.not_allowed(ok, self.clone), [])

    # --- G10: more writers, and the commands find and parallel run
    def test_more_writers_and_the_commands_find_exec_and_parallel_run(self):
        s = self.skill
        bad = ["awk -i inplace '{print}' %s" % s, "gawk -i inplace '1' %s" % s, "awk -iinplace 1 %s" % s, "vim -es %s" % s, "vi %s" % s, "ex %s" % s, "ed %s" % s, "rename s/a/b/ %s" % s,
               "sqlite3 %s 'create table t(a)'" % s, "setfacl -m u:x:rwx %s" % s, "mkfifo %s" % s, "find . -exec git push {} \\;", "find . -name x -execdir gh api x \\;",
               "find . -ok qargi packs link p \\;", "find . -exec qargi skill new x {} +", "find . -exec ls {} \\; -exec git push {} \\;", "parallel git push ::: a b", "parallel -j 4 gh api ::: a",
               "echo a | parallel qargi packs link", "find ~ -delete", "find %s -name x -delete" % os.path.join(self.t, "home/.claude"), "find ~ -exec rm {} +",
               "find %s -type f -exec rm {} \\;" % os.path.dirname(s), "find %s -delete" % self.t]
        self.assertEqual(self.not_refused(bad), [])
        ok = ["awk '{print}' f", "gawk -i inplace 1 f", "find . -type f -exec echo {} \\;", "find . -name '*.o' -delete", "find . -exec rm {} \\;", "find ~ -name x", "sqlite3 db.sqlite .tables",
              "find . -exec grep -l push {} +", "parallel echo ::: a b", "find %s -name '*.o' -delete" % self.out]
        self.assertEqual(self.not_allowed(ok), [])

    # --- G11: git commands that change the repository, under the read-only class
    def test_git_commands_that_change_the_repository_are_refused_under_the_read_only_class(self):
        bad = ["git bisect start", "git bisect good", "git bisect reset", "git symbolic-ref HEAD refs/heads/x", "git symbolic-ref -d HEAD", "git reflog expire --all", "git reflog delete HEAD@{1}",
               "git hash-object -w f", "git hash-object --write f", "git hash-object -tw f", "git unpack-objects", "git lfs pull", "git lfs checkout", "git lfs fetch", "git -C . bisect run true"]
        self.assertEqual(self.not_refused(bad, self.clone, "read-only"), [])
        ok = ["git bisect log", "git symbolic-ref HEAD", "git symbolic-ref --short HEAD", "git reflog", "git reflog show HEAD", "git hash-object f", "git lfs ls-files", "git lfs status",
              "git log --oneline", "git show HEAD", "git rev-parse HEAD"]
        self.assertEqual(self.not_allowed(ok, self.clone, "read-only"), [])
        self.assertEqual(self.not_allowed(["git bisect start", "git symbolic-ref HEAD refs/heads/x", "git hash-object -w f"], self.clone, None), [])

    # --- the caches are read again for each call
    def test_clear_caches_forgets_everything_read_from_the_library_the_environment_and_the_state(self):
        G = _Judge(LIBDIR, "guard_caches", self.clone).m
        G.resource_dirs(), G.protected_roots(), G.key_dirs(), G.state_dirs()
        self.assertTrue(G._RESOURCE_DIRS and G._ROOTS and G._KEY_DIRS and G._STATE)
        G.clear_caches()
        self.assertEqual((G._RESOURCE_DIRS, G._ROOTS, G._KEY_DIRS, G._STATE), ([], {}, [], {}))

    # --- the patterns the fifth audit added stay linear: no run of blanks, quotes, at signs or repeated words costs the hook its time
    def test_the_new_patterns_do_not_cost_quadratic_time(self):
        J = _Judge(LIBDIR, "guard_linear", self.clone)
        cases = {"blanks": "git" + " " * 150000 + "status", "push words": "git " + "push " * 30000, "dollar quotes": "$'" * 60000, "dollar quote escapes": "$'\\x" * 40000,
                 "at signs": "rsync " + "@" * 100000 + ":", "user at host": "rsync " + "a@" * 80000, "alias dots": "git -c alias." + "." * 100000 + "x s", "diff dots": "git -c diff." + "." * 100000 + " s",
                 "find -exec": "find . " + "-exec echo {} + " * 20000, "find -exec blanks": "find ." + " " * 100000 + "-exec " + " " * 100000 + "echo", "cd words": "cd " + "$d " * 20000,
                 "env -C": "env " + "-C x " * 20000 + "ls", "braces": "echo ${x:-" + "a" * 100000 + "}", "ln": "ln -s " + "a " * 30000 + "b"}
        for name, command in cases.items():
            t0 = time.perf_counter()
            J.judge(command)
            took = time.perf_counter() - t0
            self.assertLess(took, 15.0, "%s: %.1f s" % (name, took))


if __name__ == "__main__":
    unittest.main()
