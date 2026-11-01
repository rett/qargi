#!/usr/bin/env python3
"""qargi __guard: the PreToolUse hook that keeps a local agent's Bash from publishing."""
import hermetic  # noqa: F401  (first: scrubs the caller's environment)
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
        self.assertIn('command: "qargi __guard{{GUARD_ARGS}}"', text)
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

    def test_refuses_provider_accept_to_a_member(self):
        for form in ("qargi provider accept claude --surface cloud --no-barrier --asked x", "/opt/q/bin/qargi provider accept claude --surface local --no-barrier",
                     "sudo qargi provider accept nobarrier", "bash -c 'qargi provider accept claude --surface cloud'", "env FOO=1 qargi provider accept x",
                     "cd src && qargi provider accept claude --plan 0123456789ab --approved go", "echo $(qargi provider accept claude)",
                     "bash lib/provider.sh accept claude --surface cloud", "python3 -I lib/provider.py accept claude --surface cloud", "./lib/provider.sh accept claude"):
            r = self.bash(form)
            self.assertEqual(r.returncode, 2, form)
            self.assertIn("qargi provider accept records that you accept a provider with no read-only barrier and is not available to an agent", r.stderr)

    def test_lets_the_read_only_provider_verbs_through(self):
        for c in ("qargi provider list", "qargi provider show claude", "qargi provider check claude", "python3 -I lib/provider.py require-barrier claude cloud",
                  "python3 -I lib/provider.py effective claude local read_only_barrier", "echo qargi provider accept", "grep -n 'provider accept' lib/commands.py"):
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
                  "qargi packs render p build /tmp/o", "qargi packs load style --role build", "qargi export a.tgz", "qargi help skill",
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
                self.assertIn("protected location", r.stderr)
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
            self.assertIn("protected location", r.stderr)

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

    def test_credentials_and_the_install_record_are_protected_the_rest_of_conf_is_not(self):
        qh, qh3, xdgc = (os.path.join(self.t, d) for d in ("qh", "qh3", "xdgc"))
        bases = {"QARGI_CONF": (self.conf, dict()),
                 "QARGI_HOME": (qh + "/config", dict(QARGI_CONF=None, QARGI_HOME=qh)),
                 "QARGI_HOME beside QARGI_CONF": (qh3 + "/config", dict(QARGI_HOME=qh3)),
                 "live": (os.path.join(self.home, ".qargi/config"), dict(QARGI_CONF=None)),
                 "live beside QARGI_HOME": (os.path.join(self.home, ".qargi/config"), dict(QARGI_CONF=None, QARGI_HOME=qh)),
                 "earlier": (os.path.join(self.home, ".config/qargi"), dict(QARGI_CONF=None)),
                 "earlier through XDG_CONFIG_HOME": (xdgc + "/qargi", dict(QARGI_CONF=None, XDG_CONFIG_HOME=xdgc)),
                 "earlier default beside XDG_CONFIG_HOME": (os.path.join(self.home, ".config/qargi"), dict(QARGI_CONF=None, XDG_CONFIG_HOME=xdgc))}
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
        for c in ("qargi agent add worker", "qargi project init x --answers a.json", "qargi instances list"):
            self.assertEqual(self.bash(c).returncode, 0, c)

    def test_the_installed_tool_and_a_projects_member_definitions_are_protected(self):
        tool = os.path.join(self.t, "opt/qargi")
        os.makedirs(os.path.join(tool, "skills/qargi-build"))
        os.makedirs(os.path.join(self.proj, ".claude/agents"))
        with open(os.path.join(self.conf, "install.json"), "w") as f:
            json.dump({"tool_root": tool}, f)
        os.symlink(os.path.join(tool, "skills/qargi-build"), os.path.join(self.lskill, "qargi-build"))   # what install.sh makes
        for target in (os.path.join(tool, "skills/qargi-build/SKILL.md"), os.path.join(self.lskill, "qargi-build/SKILL.md"),
                       os.path.join(tool, "agents/member.md"), os.path.join(self.proj, ".claude/agents/m.md")):
            self.assertEqual(self.call("Write", {"file_path": target}).returncode, 2, target)
            r = self.bash("echo x > %s" % target)
            self.assertEqual(r.returncode, 2, (target, r.stderr))
        self.assertEqual(self.bash("rm -rf %s" % os.path.join(self.proj, ".claude")).returncode, 2)
        self.assertEqual(self.bash("cat %s" % os.path.join(tool, "skills/qargi-build/SKILL.md")).returncode, 0)   # reading stays allowed
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


class ClaudeRender(unittest.TestCase):
    """$DA_STATE/claude/<project>/ is the render Claude Code loads with --add-dir: instructions a session follows. No member
    class may write there; reading stays open."""
    setUp_skills, tearDown, bash, call_skills = Skills.setUp, Skills.tearDown, Skills.bash, Skills.call      # the same fixture, not its tests

    def setUp(self):
        self.setUp_skills()
        self.state = os.path.join(self.t, "state")
        self.render = os.path.join(self.state, "claude", "proj")
        os.makedirs(os.path.join(self.render, "skills/s"))
        os.makedirs(os.path.join(self.state, "runs"))
        os.makedirs(os.path.join(self.t, "elsewhere/claude/proj"))
        os.symlink(self.render, os.path.join(self.clone, "to-render"))
        os.symlink(os.path.join(self.state, "claude"), os.path.join(self.clone, "to-claude"))

    def call(self, tool, inp, cwd=None, **env):
        env.setdefault("QARGI_STATE", self.state)
        return self.call_skills(tool, inp, cwd, **env)

    def test_edit_tools_refuse_every_path_under_the_claude_state_directory(self):
        r = self.render
        for tool, key in (("Edit", "file_path"), ("Write", "file_path"), ("NotebookEdit", "notebook_path"), ("MultiEdit", "file_path")):
            for p in (os.path.join(r, "skills/s/SKILL.md"), os.path.join(r, "new.md"), os.path.join(self.state, "claude/other/x"),
                      os.path.join(self.state, "claude"), "to-render/skills/s/SKILL.md", "to-claude/proj/new.md", "../../state/claude/proj/CLAUDE.md"):
                for cls in ((), ("--class", "read-only")):
                    res = subprocess.run([BIN, "__guard", *cls], input=json.dumps({"tool_name": tool, "tool_input": {key: p}, "cwd": self.clone}),
                                         capture_output=True, text=True, env=self.env())
                    self.assertEqual(res.returncode, 2, (tool, p, cls, res.stderr))
                    self.assertIn("managed by `qargi packs apply`", res.stderr)
                    self.assertIn("changed only by the lead", res.stderr)

    def env(self):
        e = {k: v for k, v in os.environ.items() if k not in ("QARGI_CONF", "QARGI_STATE", "QARGI_HOME", "XDG_CONFIG_HOME", "XDG_STATE_HOME", "HOME")}
        e.update({"HOME": self.home, "QARGI_CONF": self.conf, "QARGI_STATE": self.state})
        return e

    def test_bash_writes_into_the_render_are_refused(self):
        r = self.render
        for c in ("echo x > %s/CLAUDE.md" % r, "echo x >> %s/skills/s/SKILL.md" % r, "echo x>%s/CLAUDE.md" % r, "echo x | tee %s/CLAUDE.md" % r,
                  "cp a.md %s/skills/s/" % r, "cp -t %s a.md" % r, "mv a.md %s/x.md" % r, "mv %s/skills /tmp/gone" % r, "rm -rf %s/skills" % r,
                  "rm -rf %s" % r, "rm -rf %s/claude" % self.state, "sed -i s/a/b/ %s/skills/s/SKILL.md" % r, "perl -pi -e s/a/b/ %s/CLAUDE.md" % r,
                  "ln -s /etc/passwd %s/x" % r, "touch %s/x" % r, "mkdir %s/new" % r, "chmod 777 %s/CLAUDE.md" % r, "truncate -s 0 %s/CLAUDE.md" % r,
                  "dd if=/dev/zero of=%s/CLAUDE.md" % r, "rsync -a src/ %s/" % r, "install -m 644 a %s/x" % r, "patch %s/CLAUDE.md fix.diff" % r,
                  "git -C %s checkout ." % r, "git -C %s/claude add -A" % self.state, "cd %s && echo y > CLAUDE.md" % r, "cd %s && rm -r skills" % r,
                  "tar xf a.tgz -C %s" % r, "unzip -o a.zip -d %s" % r, "curl -o %s/x http://h/f" % r, "find %s -name '*.md' -delete" % r,
                  "echo y > to-render/CLAUDE.md", "rm -rf to-claude/proj", "bash -c 'echo y > %s/CLAUDE.md'" % r, "eval 'rm %s/CLAUDE.md'" % r,
                  "echo $(echo y > %s/CLAUDE.md)" % r, "echo y > $QARGI_STATE/claude/proj/CLAUDE.md", "qargi packs render p build %s" % r,
                  "qargi packs render p build --out %s" % r):
            res = self.bash(c)
            self.assertEqual(res.returncode, 2, (c, res.stderr))
            self.assertIn("qargi guard:", res.stderr)
            self.assertIn("managed by `qargi packs apply`", res.stderr)

    def test_the_render_is_found_like_the_other_qargi_paths(self):
        home_state = os.path.join(self.home, ".qargi/state/claude/proj")
        qh_state = os.path.join(self.t, "qh/state/claude/proj")
        for d in (home_state, qh_state):
            os.makedirs(d)
        for target, env in ((home_state, dict(QARGI_STATE=None)), (qh_state, dict(QARGI_STATE=None, QARGI_HOME=os.path.join(self.t, "qh"))),
                            (os.path.join(self.t, "alt/claude/proj"), dict(QARGI_STATE=os.path.join(self.t, "alt")))):
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

    def test_a_path_that_merely_says_claude_is_allowed(self):
        e = os.path.join(self.t, "elsewhere/claude/proj")
        for p in (e + "/CLAUDE.md", os.path.join(self.state, "runs/claude/x"), os.path.join(self.state, "claude-notes.md"),
                  os.path.join(self.state, "runs/x.log"), os.path.join(self.t, "state2/claude/proj/x")):
            os.makedirs(os.path.dirname(p), exist_ok=True)
            self.assertEqual(self.call("Write", {"file_path": p}).returncode, 0, p)
            self.assertEqual(self.bash("echo x > %s" % p).returncode, 0, p)
        for c in ("echo x > %s/runs/audit.log" % self.state, "rm -rf %s/runs/old" % self.state, "touch claude/x", "echo claude > notes.txt"):
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


if __name__ == "__main__":
    unittest.main()
