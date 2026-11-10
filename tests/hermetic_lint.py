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
  absent  a grep used as an absence assertion (`! grep`, `grep ... && no`, `[ "$(grep -c ...)" = 0 ]`, `[ -z "$(... | grep ...)" ]`) whose
          literal pattern is shorter than six characters and has nothing that makes it distinctive. The output searched usually
          holds a random temporary path (mktemp makes letters and digits), and any short token can occur in it: the test then fails
          now and then, and only when it should pass. Distinctive: six or more characters, -w or -x, an anchor (^ or $), a character
          that a path does not hold (a space, a colon, a quote, a bracket, an equals sign), or a hyphen or underscore in four or more
          characters. Otherwise assert on a longer value, with -w, or on the structure (jq, a field).
A justified case is allowed with a comment on the line or the line above: `hermetic: allow RULE[,RULE] (the reason)`; a whole file with
`hermetic: allow-file RULE[,RULE] (the reason)` in its first 40 lines (for data that only looks like a path, such as the commands a
guard test judges)."""
import os
import re
import sys

RULES = ("source", "tmp", "pgrep", "sleep", "rm", "port", "lock", "clock", "absent")
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


GREP = re.compile(r"""\bgrep\b(?P<opts>(?:\s+-[A-Za-z0-9]+|\s+--[a-z-]+(?:=\S+)?)*)\s+(?:-e\s+)?(?:(?P<q>["'])(?P<pat>(?:\\.|(?!(?P=q)).)*)(?P=q)|(?P<bare>[^\s"'|;&<>()$-][^\s|;&<>()]*))""")
SEGMENT = re.compile(r"&&|\|\||;|\{|\(|\bthen\b|\bdo\b")
NEGATED = re.compile(r"^\s*(?:(?:if|elif|while|until)\s+)?!")
AND_NO = re.compile(r"^[^;|]*?&&\s*(?:no|fail)\b")
COUNT_ZERO = re.compile(r"""^[^)]*\)"?\s*(?:=|==|-eq)\s*"?0\b""")
EMPTY_CAPTURE = re.compile(r"""-z\s+"?\$\([^)]*$""")


def alternatives(pat):
    """The alternatives of a grep pattern, split at the top level of its groups (`a|b`, `a\\|b`, `(a|b)`): each one is a token that must not occur."""
    parts, cur, depth, i = [], "", 0, 0
    while i < len(pat):
        c = pat[i]
        two = pat[i:i + 2]
        if two in ("\\|", "\\(", "\\)"):
            if two == "\\|" and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += two
                depth += (two == "\\(") - (two == "\\)")
            i += 2
            continue
        if c == "[":    # a bracket expression is one item
            j = pat.find("]", i + 2)
            j = len(pat) - 1 if j < 0 else j
            cur += pat[i:j + 1]
            i = j + 1
            continue
        if c == "|" and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += c
            depth += (c == "(") - (c == ")")
        i += 1
    parts.append(cur)
    out = []
    for a in parts:
        g = re.fullmatch(r"\\?\((.*)\\?\)", a)
        if g and g.group(1).count("(") == g.group(1).count(")"):
            out += alternatives(g.group(1))    # a whole alternative that is one group: its own alternatives
        else:
            out.append(a)
    return out


def short_absent(line):
    """The short, indistinctive literal patterns of the greps in line that assert something is absent."""
    found = []
    for m in GREP.finditer(line):
        pre = line[:m.start()]
        post = line[m.end():]
        opts = m.group("opts")
        absent = (NEGATED.match(SEGMENT.split(pre)[-1]) or AND_NO.match(post) or EMPTY_CAPTURE.search(pre)
                  or ("c" in opts.replace("--", "") and COUNT_ZERO.match(post)))
        if not absent:
            continue
        pat = m.group("pat") if m.group("q") else m.group("bare")
        if m.group("q") == '"':
            pat = pat.replace("\\$", "$")    # inside double quotes \$ is a plain $ for grep: an end anchor
        if re.search(r"(?<!\\)\$[\w{(]", pat):
            continue    # a variable: its length is not known here
        if re.search(r"\s-[A-Za-z]*[wx]", opts) or re.search(r"(?<!\\)[\^$]", pat):
            continue    # a whole word or line, or an anchor: nothing in a path's random part matches
        for alt in alternatives(pat):
            lit = alt.replace("\\", "")
            if len(lit) >= 6 or re.search(r"[ ,:=!@#%&~<>'\"]", lit) or not re.search(r"[A-Za-z0-9]", lit) or (len(lit) >= 4 and re.search(r"[_-]", lit)):
                continue
            found.append(alt)
    return found


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
        if not py and "grep" in line:
            for pat in short_absent(line):
                add(i, "absent", "a short pattern (%s) asserted absent: a random temporary path in the output can hold it: %s" % (pat, line.strip()[:100]))
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
