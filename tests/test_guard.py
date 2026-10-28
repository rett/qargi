#!/usr/bin/env python3
"""qargi __guard: the PreToolUse hook that keeps a local agent's Bash from publishing."""
import json, os, subprocess, unittest

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

    def test_every_agent_definition_has_the_hook_and_review_cannot_edit(self):
        d = os.path.join(os.path.dirname(BIN), "..", "agents")
        for n in ("qargi-agent", "qargi-dev", "qargi-docs", "qargi-review", "qargi-test"):
            with open(os.path.join(d, n + ".md")) as f:
                text = f.read()
            self.assertIn('command: "qargi __guard"', text, n)
            tools = [l for l in text.splitlines() if l.startswith("tools:")][0]
            self.assertIn("Monitor", tools, n)
            self.assertIn("ToolSearch", tools, n)
            self.assertEqual("Edit" in tools, n != "qargi-review", n)


if __name__ == "__main__":
    unittest.main()
