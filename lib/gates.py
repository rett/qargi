#!/usr/bin/env python3
"""The declared gates of a project (the answer `gates`) and the scan of its CI jobs.

  gates: an ordered list of {name, command, tier}
    name     a label, unique in the list; a CI job of the same name (or id) is the job that runs the same check
    command  one command line, or a command as a list of words (the forms of test_command and release.test_command)
    tier     feature (run by `feature verify` and by `release verify`) or release (run by `release verify` only)

  gates.py select ANSWERS TIER...     the gates of those tiers, the tiers in the order named and the gates of a tier in the order declared, as a JSON array of {name, tier, command}
                                      with the command as one line (a list of words is shell-quoted); exit 1 and the problem
                                      on standard error when the answers' gates are not valid. Nothing is printed when the
                                      answers declare no gate.
  gates.py scan ANSWERS TREE          reads TREE/.github/workflows/*.yml and *.yaml and compares the jobs with the declared
                                      gate names; one tab-separated line per finding: KIND, FILE, JOB ID, NAME. KIND is
                                      unmatched (a job that matches no gate name; NAME is its name: text, empty when it has
                                      none or it is the id) or unknown (a job whose name cannot be read; JOB ID is empty for
                                      a workflow whose jobs cannot be read). Exit 1 when a job is unmatched, 0 otherwise
                                      (also when there is no workflow). Python standard library only.

A job matches a gate when the gate's name is the job's `name:` or its id. The parser is conservative: it reads the block layout
of GitHub workflow files (the job ids under `jobs:` and the `name:` line at the top level of each job) and nothing else, and says
"unknown" where it is not sure: a name that is an expression (`${{ ... }}`), a block scalar, an alias, a flow mapping.
"""
import glob
import json
import os
import re
import shlex
import sys

TIERS = ("feature", "release")
KEYS = ("name", "command", "tier")


def _ctl(s):
    return any(ord(c) < 32 or ord(c) == 127 for c in s)


def command_ok(c):
    """A command line (one line, no control character) or a non-empty list of non-empty words."""
    if isinstance(c, str):
        return bool(c.strip()) and not _ctl(c)
    return isinstance(c, list) and bool(c) and all(isinstance(x, str) and x and "\x00" not in x for x in c)


def command_line(c):
    """The command as the one line `bash -c` runs: a string as it is, a list of words shell-quoted."""
    return c if isinstance(c, str) else " ".join(shlex.quote(x) for x in c)


def problems(gates):
    """The problems of the answer `gates` (a list of strings; none when it is valid). The answer is optional: an empty list declares none."""
    if gates is None:
        return []
    if not isinstance(gates, list):
        return ["gates: a list of {name, command, tier} objects (for example [{\"name\": \"test\", \"command\": \"make test\", \"tier\": \"feature\"}])"]
    out, seen = [], set()
    for i, g in enumerate(gates):
        where = "gates[%d]" % i
        if not isinstance(g, dict):
            out.append("%s: an object {name, command, tier}" % where)
            continue
        for k in g:
            if k not in KEYS:
                out.append("%s.%s: unknown key (%s)" % (where, k, ", ".join(KEYS)))
        n = g.get("name")
        if not (isinstance(n, str) and n.strip() and n == n.strip() and not _ctl(n)):
            out.append("%s.name: a non-empty label with no control character and no space at either end (the name of the CI job that runs the same check, for example \"test\")" % where)
        elif n in seen:
            out.append("%s.name: \"%s\" is used twice; the names of the gates are unique" % (where, n))
        else:
            seen.add(n)
        if not command_ok(g.get("command")):
            out.append("%s.command: one command line, or a command as a list of words (for example [\"make\", \"check\"]); not empty" % where)
        if g.get("tier") not in TIERS:
            out.append("%s.tier: feature (feature verify and release verify run it) or release (only release verify runs it)" % where)
    return out


def declared(af):
    """The valid gates of the answers file (a list; [] when the answer is absent or empty). Raises ValueError with the problems when it is not valid."""
    try:
        with open(af, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        raise ValueError("the answers %s cannot be read: %s" % (af, e))
    gates = data.get("gates") if isinstance(data, dict) else None
    p = problems(gates)
    if p:
        raise ValueError("the answer gates is not valid:\n  " + "\n  ".join(p))
    return gates or []


def select(gates, tiers):
    """The gates of the tiers, the tiers in the order named (feature gates, then release gates), each in the order declared."""
    return [{"name": g["name"], "tier": g["tier"], "command": command_line(g["command"])} for t in tiers for g in gates if g["tier"] == t]


# ---- the CI scan

def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _scalar(v):
    """The value of a plain or quoted one-line scalar after its comment; None when it is anything else (empty, block scalar, alias,
    anchor, tag, flow collection, an expression)."""
    v = v.strip()
    if not v:
        return None
    if v[0] in "\"'":
        q = v[0]
        i, buf = 1, []
        while i < len(v):
            c = v[i]
            if q == "'" and c == "'" and v[i + 1:i + 2] == "'":
                buf.append("'")
                i += 2
                continue
            if c == q:
                rest = v[i + 1:].strip()
                if rest and not rest.startswith("#"):
                    return None
                s = "".join(buf)
                return None if "${{" in s else s
            if q == '"' and c == "\\":
                return None     # an escape: not read
            buf.append(c)
            i += 1
        return None             # no closing quote on the line
    if v[0] in "|>&*!{[%@`,?-" and not (v[0] == "-" and len(v) > 1 and v[1] not in " "):
        return None
    m = re.search(r"\s#", v)
    if m:
        v = v[:m.start()].rstrip()
    if not v or "${{" in v or ": " in v or v.endswith(":"):
        return None
    return v


def parse_jobs(text):
    """[(job id, name)] of a workflow file, name being the `name:` text, "" when the job has none (GitHub then shows the id), None when it has
    one that cannot be read. None for the whole result when the jobs cannot be read at all."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    i, n = 0, len(lines)
    while i < n and not re.match(r"jobs:\s*(#.*)?$", lines[i]):
        i += 1
    if i == n:
        return None
    i += 1
    jobs, jind, kind = [], None, None
    cur = None   # the index of the job being read in jobs
    while i < n:
        raw = lines[i]
        i += 1
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        if "\t" in raw[:len(raw) - len(raw.lstrip())]:
            return None
        ind = _indent(raw)
        if ind == 0:
            break                       # the next top-level key ends `jobs:`
        if jind is None:
            jind = ind
        if ind == jind:
            m = re.match(r"(\"[^\"]+\"|'[^']+'|[^\s#:'\"][^:#]*?)\s*:(?:\s+(.*))?$", s)
            if not m:
                return None
            jid = m.group(1).strip("\"'")
            rest = (m.group(2) or "").strip()
            inline = bool(rest) and not rest.startswith("#")
            jobs.append([jid, None if inline else "", inline])
            cur, kind = len(jobs) - 1, None
            continue
        if ind < jind:
            return None
        if cur is None or jobs[cur][2]:
            continue                    # inside a flow mapping of a job: not read
        if kind is None:
            kind = ind                  # the indent of the keys of this job
        if ind == kind:
            m = re.match(r"name\s*:(?:\s+(.*))?$", s)
            if m:
                jobs[cur][1] = _scalar(m.group(1) or "")
    return [(j[0], j[1]) for j in jobs] or None


def scan(gates, tree):
    """([(kind, file, job id, name)], unmatched count): kind is "unmatched" (a job no gate name matches; name is its `name:` text, "" when it has
    none) or "unknown" (job id "" for a workflow whose jobs cannot be read; name "" for a job whose name cannot be read)."""
    names = {g["name"] for g in gates}
    found, bad = [], 0
    files = sorted(glob.glob(os.path.join(tree, ".github", "workflows", "*.yml")) + glob.glob(os.path.join(tree, ".github", "workflows", "*.yaml")))
    for f in files:
        rel = os.path.relpath(f, tree)
        try:
            with open(f, encoding="utf-8", errors="replace") as fh:
                jobs = parse_jobs(fh.read())
        except OSError:
            jobs = None
        if jobs is None:
            found.append(("unknown", rel, "", ""))
            continue
        for jid, name in jobs:
            if jid in names or (name and name in names):
                continue
            if name is None:
                found.append(("unknown", rel, jid, ""))
            else:
                bad += 1
                found.append(("unmatched", rel, jid, name if name != jid else ""))
    return found, bad


def main(argv):
    if len(argv) < 3 or argv[1] not in ("select", "scan"):
        print(__doc__.strip().split("\n\n")[0], file=sys.stderr)
        return 2
    try:
        gates = declared(argv[2])
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    if argv[1] == "select":
        if gates:
            bad = [t for t in argv[3:] if t not in TIERS]
            if bad:
                print("not a tier: %s" % ", ".join(bad), file=sys.stderr)
                return 2
            print(json.dumps(select(gates, argv[3:])))
        return 0
    if len(argv) != 4:
        return 2
    found, bad = scan(gates, argv[3])
    for row in found:
        print("\t".join(row))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
