#!/usr/bin/env python3
"""qargi __guard: the PreToolUse hook that keeps a local agent's Bash from publishing."""
import json, os, shutil, subprocess, sys, tempfile, unittest

BIN = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin", "qargi")


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

    def test_the_member_definition_guards_bash_and_edits(self):
        d = os.path.join(os.path.dirname(BIN), "..", "agents")
        self.assertEqual(sorted(os.listdir(d)), ["member.md"], "qargi ships one member definition")
        with open(os.path.join(d, "member.md")) as f:
            text = f.read()
        self.assertIn('command: "qargi __guard"', text)
        self.assertIn('matcher: "Bash|Edit|Write|NotebookEdit"', text)
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

    def call(self, tool, inp, cwd=None):
        return subprocess.run([BIN, "__guard"], input=json.dumps({"tool_name": tool, "tool_input": inp, "cwd": cwd or self.clone}),
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
                ("Write", {"file_path": os.path.join(self.t, "elsewhere.txt")})]

    def reads(self):
        c, o = self.clone, self.out
        return [("Write", {"file_path": os.path.join(o, "report.md")}), ("Edit", {"file_path": os.path.join(o, "manifest.json")}),
                ("Bash", {"command": "git log --oneline && git diff HEAD~1"}), ("Bash", {"command": "make test > %s/test.log 2>&1" % o}),
                ("Bash", {"command": "grep -rn x src 2>/dev/null"}), ("Bash", {"command": "go test ./... | tee %s/log.txt" % o}),
                ("Bash", {"command": "cat src/a.go"})]

    def test_review_refuses_every_change_to_the_clone(self):
        self.ability("review")
        for tool, inp in self.writes():
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 2, (tool, inp, r.stderr))
            self.assertIn("review", r.stderr)

    def test_review_may_read_and_write_its_report(self):
        self.ability("review")
        for tool, inp in self.reads():
            r = self.call(tool, inp)
            self.assertEqual(r.returncode, 0, (tool, inp, r.stderr))

    def test_build_may_change_the_clone(self):
        self.ability("build")
        for tool, inp in self.writes() + self.reads():
            self.assertEqual(self.call(tool, inp).returncode, 0, (tool, inp))

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
        for d in ("home/.claude/skills/x", "conf/packs/skills/s", "conf/packs/tools", "run/clone/skills/qargi-build", "run/clone/.claude/skills/p", "run/out", "proj/.claude/skills/p", "proj/src"):
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
        verbs += ["discover install skill-pdf --project p", "packs apply p-build --asked x", "import backup.tar.gz"]
        for v in verbs:
            for form in ("qargi %s", "/opt/q/bin/qargi %s", "sudo qargi %s", "cd src && qargi %s", "echo ok; qargi %s --approved go",
                         "bash -c 'qargi %s'", "sh -c \"cd /x && qargi %s\"", "eval 'qargi %s'", "echo $(qargi %s)", "echo `qargi %s`",
                         "timeout 5 qargi %s", "env FOO=1 qargi %s", "(qargi %s)", "bash -lc 'qargi %s'"):
                r = self.bash(form % v)
                self.assertEqual(r.returncode, 2, form % v)
                self.assertIn("changes a skill and is not available to an agent", r.stderr)
                self.assertIn("qargi guard:", r.stderr)
        for c in ("lib/packs.sh skill new x", "bash lib/packs.sh tool import f.json", "./lib/packs.sh packs apply i", "python3 -I lib/discover.py install foo"):
            self.assertEqual(self.bash(c).returncode, 2, c)

    def test_lets_the_read_only_verbs_through(self):
        for c in ("qargi skill list", "qargi skill show x", "qargi tool check p build", "qargi skill effective p build", "qargi discover search pdf",
                  "qargi packs render p build /tmp/o", "qargi export a.tgz", "qargi help skill",
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
            for p in (os.path.join(lib, "skills/s/SKILL.md"), os.path.join(lib, "links.json"), os.path.join(ls, "x/SKILL.md"), "../home/.claude/skills/x/SKILL.md",
                      "link-to-library/skills/s/SKILL.md", os.path.join(self.proj, ".claude/skills/p/SKILL.md"), "../../proj/.claude/skills/new/SKILL.md",
                      "~/.claude/skills/x/SKILL.md", "~/.claude/agents/m.md", "~/.claude/plugins/p/plugin.json"):
                r = self.call(tool, {key: p})
                self.assertEqual(r.returncode, 2, (tool, p, r.stderr))
                self.assertIn("protected skill location", r.stderr)
            for p in ("skills/qargi-build/SKILL.md", os.path.join(c, "skills/new/SKILL.md"), "src/a.go", os.path.join(self.t, "run/out/report.md"),
                      ".claude/skills/p/SKILL.md", os.path.join(c, ".claude/skills/new/SKILL.md"), "sub/.claude/skills/q/SKILL.md",
                      os.path.join(self.t, "conf/projects/p.json"), os.path.join(ls, "../settings.json")):
                r = self.call(tool, {key: p})
                self.assertEqual(r.returncode, 0, (tool, p, r.stderr))

    def test_the_repositorys_own_skills_directory_stays_editable(self):
        for c in ("echo x > skills/qargi-build/SKILL.md", "sed -i s/a/b/ skills/qargi-build/SKILL.md", "cp -r skills/qargi-build skills/qargi-new",
                  "mv skills/a skills/b", "rm -rf skills/old", "git add skills && git commit -m s", "tee skills/qargi-build/notes.md < /dev/null",
                  "cd skills/qargi-build && touch extra.md", "rsync -a skills/ %s/run/out/skills/" % self.t, "install -m 644 a.md skills/qargi-build/"):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_bash_writes_to_a_protected_location_are_refused(self):
        lib, ls = self.lib, self.lskill
        for c in ("echo x > %s/skills/s/SKILL.md" % lib, "echo x >> %s/links.json" % lib, "echo x>%s/links.json" % lib, "cat a 2> %s/e" % ls,
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
            self.assertIn("protected skill location", r.stderr)

    def test_bash_reads_and_other_writes_are_not_refused(self):
        lib, ls = self.lib, self.lskill
        for c in ("cat %s/x/SKILL.md" % ls, "cat %s/x/SKILL.md > %s/run/out/copy.md" % (ls, self.t), "cp %s/x/SKILL.md %s/run/out/" % (ls, self.t),
                  "grep -rn foo %s" % lib, "ls -la %s" % ls, "diff -r %s/x skills/qargi-build" % ls, "rsync -a %s/ %s/run/out/lib/" % (lib, self.t),
                  "jq . %s/links.json > %s/run/out/l.json" % (lib, self.t), "find %s -name '*.md'" % ls, "find %s -name SKILL.md -exec cat {} +" % self.clone + " > /dev/null",
                  "tar czf %s/run/out/lib.tgz -C %s ." % (self.t, lib), "echo x > %s/home/.claude/settings.json" % self.t, "rm -rf %s/run/out/old" % self.t,
                  "curl -s http://h/f -o %s/run/out/f" % self.t, "touch %s/.claude" % self.proj, "ls ~/.claude/skills", "echo ~/.claude/skills > list.txt", "cd %s && ls" % lib):
            r = self.bash(c)
            self.assertEqual(r.returncode, 0, (c, r.stderr))

    def test_the_protected_roots_follow_the_environment(self):
        other = os.path.join(self.t, "xdg")
        os.makedirs(os.path.join(other, "qargi/packs"))
        target = os.path.join(other, "qargi/packs/links.json")
        r = self.bash("echo x > %s" % target, QARGI_CONF=None, XDG_CONFIG_HOME=other)         # the XDG default
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.bash("echo x > %s" % target).returncode, 0)                    # QARGI_CONF names another root
        r = self.bash("echo x > %s/.config/qargi/packs/links.json" % self.home, QARGI_CONF=None)   # the plain default, under HOME
        self.assertEqual(r.returncode, 2, r.stderr)
        r = self.call("Write", {"file_path": os.path.join(self.t, "alt/packs/links.json")}, QARGI_CONF=os.path.join(self.t, "alt"))
        self.assertEqual(r.returncode, 2, r.stderr)
        r = self.bash("echo x > %s/.config/qargi/packs/links.json" % self.home)         # the default stays protected beside QARGI_CONF
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_the_pack_library_is_protected_where_the_data_lives_now_and_where_it_was(self):
        for d in (".qargi/config/packs", ".config/qargi/packs", "qh/config/packs", "qh2/config/packs", "xdgc/qargi/packs"):
            os.makedirs(os.path.join(self.t, d if d.startswith(("qh", "xdgc")) else "home/" + d), exist_ok=True)
        new_default = "%s/.qargi/config/packs/links.json" % self.home
        old_default = "%s/.config/qargi/packs/links.json" % self.home
        for target, env in ((new_default, dict(QARGI_CONF=None)),                                    # ~/.qargi/config
                            (old_default, dict(QARGI_CONF=None)),                                    # the earlier library stays protected
                            (os.path.join(self.t, "qh/config/packs/links.json"), dict(QARGI_CONF=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                            (os.path.join(self.t, "xdgc/qargi/packs/links.json"), dict(QARGI_CONF=None, XDG_CONFIG_HOME=os.path.join(self.t, "xdgc")))):
            r = self.bash("echo x > %s" % target, **env)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
            r = self.call("Write", {"file_path": target}, **env)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
        # protection stops at the library: the rest of the new root is not a skill
        r = self.bash("echo x > %s/.qargi/config/instances.json" % self.home, QARGI_CONF=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        # QARGI_HOME is the root; XDG_CONFIG_HOME no longer moves it
        other = os.path.join(self.t, "qh2/config/packs/links.json")
        self.assertEqual(self.bash("echo x > %s" % other, QARGI_CONF=None).returncode, 0)
        self.assertEqual(self.bash("echo x > %s" % other, QARGI_CONF=None, QARGI_HOME=os.path.join(self.t, "qh2")).returncode, 2)

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
                  "cp -r skills/qargi-build .claude/skills/qb", "mv .claude/skills/p .claude/skills/q", "rm -rf .claude/skills/p", "rm -rf .claude",
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
            self.assertIn("protected skill location", r.stderr)
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


if __name__ == "__main__":
    unittest.main()
