#!/usr/bin/env python3
"""Static lint over the tests: what makes a test unsafe to run next to other tests, or next to another whole suite.
Run by tests/test_hermetic.sh. Usage: hermetic_lint.py [TESTS_DIR]; prints one `FILE:LINE: RULE: text` per finding, exits 1 on any.

The rules (each test file: tests/test_*.sh, tests/test_*.py, tests/conformance.sh, tests/role_seed_sim.py):
  source  the file does not source tests/hermetic.sh (shell) or import hermetic (python): a caller's variables, HOME, config and the
          real ant and claude reach the test.
  tmp     a literal /tmp, /dev/shm or /run path in code: the test works in a place that every other run shares. Make a directory with
          mktemp (it follows TMPDIR) and work under it.
  pgrep   pkill, killall, or pgrep with -f (a pattern over every process's command line): it finds, and kills, the processes of other
          runs. Keep the pid of what the test started (spawn_bg and kill_bg of tests/hermetic.sh), or kill the child's process group.
  sleep   a `sleep N` (N under 10) that is a command of its own and not inside a for/while/until loop: a fixed wait, too short on a
          slow host and too long on a fast one. Poll for the condition with a deadline. A sleep inside a quoted command (the work of a
          fake) or `exec sleep` is not a wait of the test, and a sleep of 10 seconds or more is a simulated hang that a deadline kills.
  rm      rm -r of a directory the test did not make: "$TMPDIR", "$HOME" (alone), "~", a literal absolute path.
  port    a fixed TCP port (a host:NNNN address, --port NNNN, a bind to a number): two runs at once collide. Bind port 0 and read the
          port back.
  lock    a lock or socket path outside the test's directory (/var/lock, /var/run, $XDG_RUNTIME_DIR, flock or bind on an absolute path).
  clock   a difference of two readings of the wall clock ($SECONDS, date +%s, time.time()) compared with a constant: it fails on a slow
          host. Wait for a condition with a deadline, or use the deadline hook of the code under test.
A justified case is allowed with a comment on the line or the line above: `hermetic: allow RULE[,RULE] (the reason)`; a whole file with
`hermetic: allow-file RULE[,RULE] (the reason)` in its first 40 lines (for data that only looks like a path, such as the commands a
guard test judges)."""
import os
import re
import sys

RULES = ("source", "tmp", "pgrep", "sleep", "rm", "port", "lock", "clock")
ALLOW = re.compile(r"hermetic: allow(-file)? ([a-z,]+)")


def files(d):
    return sorted(f for f in os.listdir(d)
                  if (f.startswith("test_") and f.endswith((".sh", ".py"))) or f in ("conformance.sh", "role_seed_sim.py"))


def comment(line):
    return line.lstrip().startswith("#")


def indent(line):
    return len(line) - len(line.lstrip())


def in_loop_py(lines, i):
    """True when the statement at line i sits inside a for/while block (an enclosing line with less indentation)."""
    want = indent(lines[i])
    for j in range(i - 1, -1, -1):
        s = lines[j]
        if not s.strip() or comment(s):
            continue
        if indent(s) < want:
            if re.match(r"\s*(for|while)\b", s):
                return True
            want = indent(s)
            if want == 0:
                return False
    return False


TMP = re.compile(r"(?<![\w}\]$.-])(/tmp|/dev/shm|/run)(?![\w.-])")
PORT = re.compile(r"""(?:(?:127\.0\.0\.1|localhost|0\.0\.0\.0|\[::1\]):[1-9][0-9]{1,4}\b|--port[ =][1-9][0-9]*|\bport\s*=\s*[1-9][0-9]{2,4}\b|\bbind\(\(\s*["'][^"']*["']\s*,\s*[1-9])""")
LOCK = re.compile(r"""/var/(?:lock|run)\b|XDG_RUNTIME_DIR|\bflock\s+(?:-\S+\s+)*["']?/|\.bind\(\s*["']/""")
CLOCK_SH = re.compile(r"\$\(\(\s*(?:\$\(date[^)]*\)|\$?\{?SECONDS\}?)\s*-[^)]*\)\)\s*-(?:lt|le|gt|ge|eq)\s+\$?[0-9]+")
CLOCK_PY = re.compile(r"time\.(?:time|monotonic|perf_counter)\(\)\s*-\s*\w+\s*(?:<|<=|>|>=)\s*[0-9]|assert(?:Less|Greater)(?:Equal)?\(\s*(?:time\.(?:time|monotonic|perf_counter)\(\)\s*-\s*\w+|\w*(?:elapsed|took|duration)\w*)\s*,\s*[0-9]""")
SLEEP_SH = re.compile(r"(?:^|[;&|(]|\bthen\b|\bdo\b|\belse\b)\s*sleep\s+([0-9][0-9.]*)")
SLEEP_PY = re.compile(r"^\s*time\.sleep\(([0-9][0-9.]*)\)")
PGREP = re.compile(r"\b(pkill|pgrep)\b[^|;&\n]*?\s-[A-Za-z]*f")
RM = re.compile(r"""(?:^|[;&|(]|\bthen\b|\bdo\b)\s*rm\s+((?:-[A-Za-z]+\s+)+)([^;&|<>)]*)""")
RM_BAD = re.compile(r"""^["']?(\$\{?TMPDIR\}?|\$\{?HOME\}?|~|/[^$"']*)["']?/?$""")


def tmp_hit(line):
    for m in TMP.finditer(line):
        i = m.start()
        # "$VAR"/tmp: a quoted variable followed by a path is not a literal /tmp
        if i >= 2 and line[i - 1] in "\"'" and (line[i - 2].isalnum() or line[i - 2] in "}_"):
            continue
        return True
    return False


def lint(path):
    name = os.path.basename(path)
    py = name.endswith(".py")
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.read().split("\n")
    file_allow = set()
    for ln in lines[:40]:
        m = ALLOW.search(ln)
        if m and m.group(1):
            file_allow.update(m.group(2).split(","))
    out = []

    def add(i, rule, why):
        if rule in file_allow:
            return
        for j in (i, i - 1):
            if j >= 0:
                m = ALLOW.search(lines[j])
                if m and not m.group(1) and rule in m.group(2).split(","):
                    return
        out.append("%s:%d: %s: %s" % (name, i + 1, rule, why))

    text = "\n".join(lines)
    if py:
        has = re.search(r"^\s*(import hermetic|from hermetic import)", text, re.M)
    else:
        has = re.search(r"^\s*(\.|source)\s+\S*hermetic\.sh", text, re.M)
    if not has and "source" not in file_allow:
        out.append("%s:1: source: does not %s" % (name, "import hermetic" if py else "source tests/hermetic.sh"))
    for i, line in enumerate(lines):
        if comment(line):
            continue
        if tmp_hit(line):
            add(i, "tmp", "a literal /tmp, /dev/shm or /run path: " + line.strip()[:100])
        if PORT.search(line):
            add(i, "port", "a fixed TCP port: " + line.strip()[:100])
        if LOCK.search(line):
            add(i, "lock", "a lock or socket path outside the test's directory: " + line.strip()[:100])
        if (CLOCK_PY if py else CLOCK_SH).search(line):
            add(i, "clock", "a wall-clock difference against a constant: " + line.strip()[:100])
        if PGREP.search(line) or re.search(r"\b(pkill|killall)\b", line):
            add(i, "pgrep", "pkill/pgrep with -f matches other runs' processes: " + line.strip()[:100])
        m = RM.search(line)
        if m and re.search(r"[rR]", m.group(1)) and any(RM_BAD.match(a) for a in m.group(2).split()):
            add(i, "rm", "removes a directory the test did not make: " + line.strip()[:100])
        if py:
            m = SLEEP_PY.match(line)
            if m and float(m.group(1)) < 10 and not in_loop_py(lines, i):
                add(i, "sleep", "a fixed wait outside a poll loop: " + line.strip()[:100])
        else:
            m = SLEEP_SH.search(line)
            if m and float(m.group(1).rstrip(".") or 0) < 10:
                before = line[:m.start()]
                loop = re.search(r"\b(for|while|until)\b", before) or any(
                    re.search(r"\b(for|while|until)\b.*\bdo\s*$|^\s*(for|while|until)\b", lines[j]) for j in range(max(0, i - 3), i))
                if not loop:
                    add(i, "sleep", "a fixed wait outside a poll loop: " + line.strip()[:100])
    return out


def main(argv):
    d = argv[0] if argv else os.path.dirname(os.path.abspath(__file__))
    found = []
    for f in files(d):
        found += lint(os.path.join(d, f))
    for line in found:
        print(line)
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
