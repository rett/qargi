#!/usr/bin/env python3
"""qargi __guard: the PreToolUse hook that keeps a local agent's Bash from publishing."""
import json, os, shutil, subprocess, tempfile, unittest

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


if __name__ == "__main__":
    unittest.main()
