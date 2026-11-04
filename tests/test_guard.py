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
                ("Bash", {"command": "cat src/a.go"}), ("Bash", {"command": "echo 'done; rm -rf src' && git log --format='%s; touch src/x' -3"}),
                ("Bash", {"command": "cat <<'E' > %s/notes.txt\nrm -rf src\ngit commit -am x\nE" % o}),
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
        for c in ("echo 'x; touch newfile'", "git log --format='%s; touch newfile' -3", "echo hi # touch newfile"):
            self.assertEqual(self.call("Bash", {"command": c}).returncode, 0, c)

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
        for c in ("qargi local verify /tmp/r", "cat lib/local_run.py", "grep -n argv lib/local_run.py"):
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
                  "ls skills", "qargi local verify"):
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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
            for p in (os.path.join(lib, "skills/s/SKILL.md"), os.path.join(lib, "links.json"), os.path.join(lib, "accepted.json"), os.path.join(ls, "x/SKILL.md"), "../home/.claude/skills/x/SKILL.md",
                      "link-to-library/skills/s/SKILL.md", os.path.join(self.proj, ".claude/skills/p/SKILL.md"), "../../proj/.claude/skills/new/SKILL.md",
                      "~/.claude/skills/x/SKILL.md", "~/.claude/agents/m.md", "~/.claude/plugins/p/plugin.json"):
                r = self.call(tool, {key: p})
                self.assertEqual(r.returncode, 2, (tool, p, r.stderr))
                self.assertIn("protected location", r.stderr)
            for p in ("skills/sample/SKILL.md", os.path.join(c, "skills/new/SKILL.md"), "src/a.go", os.path.join(self.t, "run/out/report.md"),
                      ".claude/skills/p/SKILL.md", os.path.join(c, ".claude/skills/new/SKILL.md"), "sub/.claude/skills/q/SKILL.md",
                      os.path.join(self.t, "conf/projects/p.json"), os.path.join(ls, "../settings.json")):
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
                  "tar czf %s/run/out/lib.tgz -C %s ." % (self.t, lib), "echo x > %s/home/.claude/settings.json" % self.t, "rm -rf %s/run/out/old" % self.t,
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
        self.assertEqual(self.call("Write", {"file_path": "~/.claude/settings.json"}, HOME=home2).returncode, 0)

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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
                          ("Read", {"file_path": "to-creds/marshal_ed25519"}), ("NotebookRead", {"notebook_path": os.path.join(cred, "marshal_ed25519")}),
                          ("Grep", {"pattern": "BEGIN", "path": os.path.join(cred, "marshal_ed25519")}), ("Grep", {"pattern": "BEGIN", "path": cred}),
                          ("Grep", {"pattern": "BEGIN", "path": self.conf}), ("Grep", {"pattern": "BEGIN", "path": "to-creds"})):
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
                          "tar czf %s/c.tgz %s" % (out, self.conf), "rsync -a %s/ %s/c/" % (cred, out), "grep -r BEGIN %s" % cred, "grep -rn x %s" % self.conf,
                          "rg BEGIN %s" % cred,
                          "zip -r %s/z.zip %s" % (out, self.conf), "cd %s && tar cf %s/c.tar ." % (cred, out), "cd %s && cp -r . %s/c" % (cred, out),
                          "cd %s && grep -r BEGIN ." % cred, "bash -c 'cp -r %s %s/c'" % (cred, out)])
        for c in ("find %s -type f -exec cat {} +" % cred, "find %s -type f -execdir cat {} ;" % self.conf):     # find's actions already count as writes
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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
            for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
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
                           ({"tool_name": "MultiEdit", "tool_input": {"path": "b"}, "cwd": "/w"}, ("write", "MultiEdit", "", "", "/w")),
                           ({"tool_name": "Read", "tool_input": {"file_path": "r"}, "cwd": "/w"}, ("read", "Read", "", "r", "/w")),
                           ({"tool_name": "NotebookRead", "tool_input": {"notebook_path": "n"}, "cwd": "/w"}, ("read", "NotebookRead", "", "n", "/w")),
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
        self.assertEqual(self.bash("echo x > %s/home/.claude/settings.json" % self.t).returncode, 0)

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
    """What the guard reads of a Bash command is its commands, not the text it carries. A refused verb in a quoted string, a comment or a
    heredoc that only a file or a message receives is not a command (ALLOWED); in the place of a command, however it is dressed up, it is
    (REFUSED). Each table is read as one: the failures are listed together."""
    setUp, tearDown, bash = Skills.setUp, Skills.tearDown, Skills.bash
    call = Skills.call
    maxDiff = None

    ALLOWED = (
        'git commit -m "Fix docs\n\nqargi packs seed now refuses X"',
        'git commit -m "Docs; qargi packs seed is lead-only"',
        "git commit -m 'Docs; qargi packs seed is lead-only'",
        "echo 'run it; qargi upgrade later'",
        'printf "a\\nqargi upgrade\\n"',
        "cat > notes.txt <<'E2'\nqargi provider enable x\nE2",
        'cat > notes.txt <<"E2"\nqargi provider enable x\nE2',
        "cat > notes.txt <<\\E2\nqargi provider enable x\nE2",
        "cat > notes.txt <<-'E2'\n\tqargi provider enable x\n\tE2",
        "cat <<'E' | tee notes.txt\nqargi upgrade\nE",
        "cat <<E\nqargi upgrade\nE",
        "cat <<E > notes.txt\nuse qargi packs seed\n\\$(qargi upgrade)\nE",
        'git commit -m "$(cat <<\'EOF\'\nFix\n\nqargi packs seed now refuses X; qargi upgrade too\nEOF\n)"',
        "grep -rn 'qargi packs seed' .",
        "git commit -m 'a push of work'",
        'git commit -m "Fix: a; gh api x"',
        "echo hi # then qargi upgrade",
        "echo hi # it's late\nls",
        "echo 'a' && echo \"b; qargi upgrade\"",
        "echo \"it's; qargi upgrade\"",
        "echo \\; qargi upgrade",
        "echo $((1 + 2)) && ls",
        'echo "${HOME:-x}; qargi upgrade"',
        "cat <<'E' > msg.txt\nqargi upgrade\nE\ngit commit -F msg.txt",
        "qargi provider list; echo 'qargi upgrade'",
        "qargi packs list | grep 'packs seed'",
        "echo '$(qargi upgrade)'",
        'echo "\\$(qargi upgrade)"',
        'python3 tests/test_guard.py && git commit -m "$(cat <<\'EOF\'\nDocs\n\nqargi upgrade is lead-only\nEOF\n)"',
        "for f in a b; do echo \"$f; qargi upgrade\"; done",
        "if [ -f x ]; then echo 'then qargi upgrade'; fi",
    )
    REFUSED = (
        "qargi packs seed",
        "x; qargi upgrade",
        "echo hi && qargi provider enable x",
        "echo hi || qargi upgrade",
        "echo hi | qargi upgrade",
        "printf 'qargi upgrade' | sh",
        'printf "a\\nqargi upgrade\\n" | sh',
        "echo qargi upgrade | bash",
        "echo qargi upgrade | sudo bash -s",
        "echo qargi upgrade | source /dev/stdin",
        "echo qargi upgrade | . /dev/stdin",
        "echo upgrade | xargs qargi",
        "echo packs seed | xargs -n 2 qargi",
        "bash <<< 'qargi upgrade'",
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
        "bash -c \"$(echo qargi upgrade)\"",
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
        "printf '%s\\n' qargi upgrade | bash",
        "echo $'qargi upgrade' | sh",
        "echo packs seed | xargs -I{} qargi {}",
        "f() { qargi upgrade; }; f",
        "until false; do qargi upgrade; done",
        "bash <(echo qargi upgrade)",
        "eval `echo qargi upgrade`",
    )

    def verdicts(self, cmds):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(8) as ex:
            return list(zip(cmds, ex.map(self.bash, cmds)))

    def test_text_that_only_carries_a_refused_verb_is_not_a_command(self):
        wrong = [(c, r.stderr.strip()) for c, r in self.verdicts(self.ALLOWED) if r.returncode != 0]
        self.assertEqual(wrong, [], "refused, but only text")

    def test_a_refused_verb_in_the_place_of_a_command_is_refused_however_it_is_dressed(self):
        wrong = [c for c, r in self.verdicts(self.REFUSED) if r.returncode != 2]
        self.assertEqual(wrong, [], "allowed, but a command")

    def test_the_publishing_barrier_reads_commands_too(self):
        for c in ('git commit -m "Fix: a; gh api x"', "echo 'then git push; gh pr list'", "cat <<'E' > n.txt\ngit push\nE", "grep -n 'ssh host' f"):
            self.assertEqual(self.bash(c).returncode, 0, c)
        for c in ('echo "$(gh api x)"', "if true; then git push; fi", "(git push)", "{ git push; }", "echo x | sh -c 'git push'", "cat <<E | sh\ngit push\nE",
                  "echo a & gh pr list"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 2, (c, r.stderr))
            self.assertIn("Agents never push", r.stderr)


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
    """The adversarial review of the Bash reader: commands that the guard before it (the plain split on every separator, now the fallback) refused and the
    quote-aware reading let through while they still run a refused verb or git push. The quote-aware reading applies only to a command whose every
    segment runs nothing from its arguments (INERT in lib/guard.py); any other command is read as the plain split reads it."""
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
    # still allowed: the text of a command that runs nothing from its arguments, however much it looks like a command
    ALLOWED = (
        'git commit -m "x; qargi upgrade; y"',
        'echo "a; qargi packs seed; b"',
        "cat <<'E'\n`qargi upgrade`\nE",
        "git commit -F - <<'EOF'\nDocs\n\nqargi upgrade now fails\ngit push is for the lead\nEOF",
        'git log --format="%s; qargi upgrade" -3',
        "git log --oneline | grep 'qargi upgrade' | head -3",
        "echo hi #; qargi upgrade",
        "echo hi # git push",
        "echo hi\n# qargi upgrade\nls",
        "echo $#; echo 'x; qargi upgrade'",
        "echo a#b; echo 'x; qargi upgrade'",
        "git status && git diff --stat | tail -1 && git commit -m 'a; qargi packs seed; b'",
        "if [ -f x ]; then echo 'qargi upgrade; git push'; fi",
        "for f in a b; do echo \"$f; git push\"; done",
        "cat <<'E' > n.txt\nqargi upgrade\nE\ngit add n.txt && git commit -m 'n.txt: qargi upgrade; git push'",
        "qargi provider list && echo 'qargi upgrade; git push'",
        "python3 tests/test_guard.py && git commit -m 'qargi upgrade; git push'",
        "python3 tests/test_guard.py && git commit -m \"$(cat <<'EOF'\nDocs\n\nqargi upgrade is lead-only\nEOF\n)\"",
        "git tag -l 'v*' | sort | tail -3; echo 'qargi upgrade'",
    )
    # read as the plain split reads them from now on (a refusal that a careful reading would not make): the cost of not guessing
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

    def test_text_that_only_a_command_which_runs_nothing_carries_is_still_not_a_command(self):
        wrong = [(c, r.stderr.strip()) for c, r in self.verdicts(self.ALLOWED) if r.returncode != 0]
        self.assertEqual(wrong, [], "refused, but only text")

    def test_a_command_with_anything_else_in_it_is_read_conservatively(self):
        wrong = [c for c, r in self.verdicts(self.CONSERVATIVE) if r.returncode != 2]
        self.assertEqual(wrong, [], "the plain split refuses these; the reader no longer guesses which file a heredoc is run through")

    def test_the_review_found_the_variants_a_member_could_try(self):
        """Not only the single commands: each refused verb is wrapped in the shapes a member could use to hide it."""
        shapes = ('sh -c "@@"', "bash -c '@@'", 'eval "@@"', 'env sh -c "@@"', 'timeout 5 sh -c "@@"', 'trap "@@" EXIT', 'X="@@"; eval $X',
                  "f() { eval \"$1\"; }; f \"@@\"", "python3 -c 'import os; os.system(\"@@\")'", "echo '@@' | sh", "cat <<'E' | sh\n@@\nE",
                  "cat > a.sh <<'E'\n@@\nE\nsh a.sh", "echo a\\ #; @@", "echo ${x:-1}\n@@", "echo $[1<<2]\n@@\n2]")
        wrong = [c for c, r in self.verdicts([s.replace("@@", p) for s in shapes for p in ("true; qargi upgrade; true", "true; git push; true")]) if r.returncode != 2]
        self.assertEqual(wrong, [])


class ReaderUnits(unittest.TestCase):
    """segments() in the process: what it returns, once per command, and how fast."""
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.J = _Judge(LIBDIR, "guard_units", cls.tmp)
        cls.G = cls.J.m

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_the_quote_aware_reading_is_only_for_commands_that_run_nothing_from_their_words(self):
        G = self.G
        texts, exact = G.segments('git commit -m "a; qargi upgrade"')
        self.assertTrue(exact)
        self.assertEqual(list(texts), ['git commit -m "a; qargi upgrade"'])
        for c in ('sh -c "a; b"', 'eval "a; b"', 'trap "a; b" EXIT', 'X="a; b"; eval $X', 'find . -exec sh -c "a; b" \\;', 'git -c alias.z="!a; b" z',
                  'git rebase --exec "a; b" HEAD', 'env sh -c "a; b"', 'python3 -c "a; b"', 'awk \'BEGIN{system("a; b")}\'', 'f() { git log; }; echo "a; b"',
                  'alias z="a; b"', 'echo "a; b"; unknown-program', 'echo "$x" | bash', '$x "a; b"', 'echo ${x:-"a; b"}', 'echo $((1 + 2)); echo "a; b"',
                  'echo $[1 + 2]; echo "a; b"', 'echo "a; b"\r\nls', 'cat <<E\n$(ls)\nE\nsh'):
            texts, exact = G.segments(c)
            self.assertFalse(exact, c)
        texts, exact = G.segments('echo "a; b"; sh -c x')
        self.assertFalse(exact)
        self.assertIn('b"', [t.strip() for t in texts])                          # the plain split cuts at every separator, quotes or not

    def test_a_program_found_after_assignments_keywords_and_redirects_decides(self):
        G = self.G
        for c in ("FOO=1 git status", "if git status; then echo ok; fi", "{ git log; }", "(git log)", "! git diff", ">/dev/null git status", "2>&1 echo hi",
                  "while git diff --quiet; do sleep 1; done", "git -C /x status", "git --no-pager log -3", "x=1", "cd /x && git status"):
            self.assertTrue(G.segments(c + " # 'x'")[1] or c.startswith("while"), c)
        for c in ("FOO=1 sh x", "BASH_ENV=a git log", "GIT_PAGER=less git log", "PATH=. git log", "git -c core.pager=x log", "git --exec-path=x log", "git rebase -i",
                  "git config alias.z '!x'", "git diff --ext-diff-x; python3 -c x", "rg --pre x y", "sort --compress-program x", "printf -v 'a[1]' x",
                  "test -v a[1]", "[[ x ]]", "((x))", "let x=1", "a[1]=2", "function f { git log; }", "f() { git log; }", "case x in x) git log;; esac", "x=1 y=2 make", "git log; make",
                  "cat > .git/hooks/post-commit <<'E'\nhi\nE", "git commit -m x > .git/config"):
            self.assertFalse(G.segments(c + " # 'x'")[1], c)

    def test_segments_is_read_once_per_command(self):
        G, calls = self.G, []
        real = G.read_segments
        G.read_segments = lambda c: calls.append(c) or real(c)
        try:
            c = 'git status; echo "a; b"\n# once %s' % time.time()
            self.assertIs(G.segments(c), G.segments(c))
            self.assertEqual(len(calls), 1)
            calls.clear()
            c2 = 'echo "a; b"; git status # twice %s' % time.time()
            why = self.J.judge(c2)
            self.assertIsNone(why, why)
            self.assertEqual(len(calls), 1, calls)
        finally:
            G.read_segments = real

    def test_a_huge_command_is_read_by_the_plain_split(self):
        G = self.G
        text = "echo 'a; b'\n" * 20000
        self.assertGreater(len(text), 200000)
        self.assertFalse(G.segments(text)[1])
        self.assertTrue(G.segments("echo 'a; b'\n" * 100)[1])

    def test_a_nul_byte_refuses_and_so_does_a_carriage_return_in_the_reading(self):
        why = self.J.judge("echo hi\x00; git status")
        self.assertTrue(why and "NUL" in why, why)
        self.assertFalse(self.G.segments("echo hi\r\nls")[1])

    def test_comments_start_at_the_beginning_of_a_word_only(self):
        G = self.G
        for c, has in (("echo a #; ls", False), ("echo a\\ #; ls", True), ("echo a\\\n#; ls", True), ("echo a\\\t#; ls", True), ("echo a#; ls", True),
                       ("echo $#; ls", True), ("echo 'a'#; ls", True), ("echo \"a\"#; ls", True), ("echo a;#; ls", False), ("echo a&#; ls", False), ("echo a\n#; ls", False),
                       ("echo a>#; ls", True), ("echo a<#; ls", True)):
            self.assertEqual(any(t.strip() == "ls" for t in G.segments(c)[0]), has, c)

    def test_two_thousand_heredocs_and_a_megabyte_are_read_in_seconds(self):
        """The hook has 20 seconds and a hook that times out does not block. The quote-aware reading and the plain split, a command of 2000 small heredocs
        and commands of a size near the limit, in the process (the callers of segments() included); a megabyte is refused at once."""
        inert = "".join("cat > f%d <<'E'\nbody %d\nE\n" % (i, i) for i in range(2000))
        shapes = {"2000 heredocs, quote-aware": (inert, None), "2000 heredocs, plain split": (inert + "make\n", None),
                  "150 KB heredoc body, quote-aware": ("cat <<'E'\n" + "a line of text; and more text %d\n" * 5000 % tuple(range(5000)) + "E\n", None),
                  "200 KB of words": ("echo " + "word " * 40000, None),
                  "100 KB heredoc body, plain split": ("cat <<'E'\n" + "a line of text; and more text %d\n" * 3500 % tuple(range(3500)) + "E\nmake\n", None),
                  "120 KB of commands, plain split": ("".join("git status %d; " % i for i in range(7000)) + "make", None),
                  "1 MB heredoc body": ("cat <<'E'\n" + "a line of text; and more text\n" * 35000 + "E\n", "cannot be checked"),
                  "1 MB of commands": ("git status; " * 80000, "cannot be checked"),
                  "1 MB of pipes": ("echo x | " * 120000 + "sh", "cannot be checked"),
                  "1 MB of words": ("echo " + "word " * 200000, "cannot be checked")}
        for name, (c, refused) in shapes.items():
            t0 = time.perf_counter()
            why = self.J.judge(c)
            took = time.perf_counter() - t0
            self.assertLess(took, 2.0, "%s: %.1f s" % (name, took))
            if refused:
                self.assertIn(refused, why or "", name)
            else:
                self.assertIsNone(why, (name, why))
        t0 = time.perf_counter()
        self.G.read_segments(inert)
        self.assertLess(time.perf_counter() - t0, 2.0)
        self.assertEqual(self.G.read_segments(inert)[1], True)

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
    quotes) is refused now, except the commands that only carry text for a program that runs nothing from its words (NARROWED)."""
    PAYLOADS = ("qargi upgrade", "true; qargi upgrade; true", "git push", "true; git push origin x; true", "qargi packs seed")
    NARROWED = ('echo "@@"', "echo '@@'", 'git commit -m "@@"', "git commit -m '@@'", "printf '%s\\n' '@@'", "grep -n '@@' f", "cat <<'E'\n@@\nE",
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
        out = list(BashText.REFUSED) + list(ReviewedReading.REFUSED) + list(ReviewedReading.CONSERVATIVE)
        out += [t.replace("@@", p) for t in self.RUNNING for p in self.PAYLOADS]
        return list(dict.fromkeys(out))

    def test_the_new_refusals_contain_the_old_ones_but_the_narrowed(self):
        lib = old_lib(self)
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        old, new = _Judge(lib, "guard_old", tmp), _Judge(LIBDIR, "guard_new", tmp)
        narrowed = {t.replace("@@", p) for t in self.NARROWED for p in self.PAYLOADS}
        corpus = self.corpus() + sorted(narrowed)
        self.assertGreaterEqual(len(corpus), 150)
        refused_by_old = [c for c in corpus if old.judge(c)]
        self.assertGreaterEqual(len(refused_by_old), 150, "the corpus must be mostly commands the old guard refused")
        lost = [c for c in refused_by_old if c not in narrowed and not new.judge(c)]
        self.assertEqual(lost, [], "the old guard refused these, the new one allows them")
        lost_narrowed = [c for c in narrowed if not old.judge(c) and new.judge(c)]
        self.assertEqual(lost_narrowed, [], "the new guard refuses text the old one allowed")

    def test_the_fallback_cuts_where_the_old_split_cut(self):
        """Without the history: the plain split of 2b41028 (its SEGMENT, vendored) cut a command into pieces; every piece is a piece (or a part of one) of the
        fallback, and every command of the review is read by the fallback."""
        old_split = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        G = _Judge(LIBDIR, "guard_fallback", tmp).m
        subst = re.compile(r"\$\(|`")
        for c in self.corpus():
            texts, exact = G.segments(c)
            if exact:
                continue
            have = {t.strip() for t in texts}
            for piece in old_split.split(subst.sub(";", c.replace("\\\n", ""))):
                for part in (g.text for g in G.plain_segments(piece)):
                    self.assertIn(part.strip(), have | {""}, c)
        self.assertEqual([c for c in ReviewedReading.REFUSED if G.segments(c)[1]], [])


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


if __name__ == "__main__":
    unittest.main()
