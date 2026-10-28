#!/usr/bin/env python3
"""qargi __guard: a PreToolUse hook for the local agents' Bash tool. Reads the hook's JSON on stdin and refuses
(exit 2, reason on stderr) a command that would publish or reach out: git push, gh, ssh, scp, sftp, and changing
a remote. A second barrier beside the git wrapper (which has no credentials) and `qargi local verify`; an agent
that goes out of its way can still get around it, which is why verify exists. Anything else exits 0."""
import json, os, re, shlex, sys

SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
WRAP = {"sudo", "env", "command", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice"}


def blocked(command):
    for seg in SEGMENT.split(command):
        try:
            toks = shlex.split(seg)
        except ValueError:
            toks = seg.split()
        toks = [t for t in toks if "=" not in t.split("/")[0] or t.startswith("-")]
        i = 0
        while i < len(toks) and (os.path.basename(toks[i]) in WRAP or toks[i].isdigit() or (toks[i].startswith("-") and i)):
            i += 1
        if i >= len(toks):
            continue
        prog = os.path.basename(toks[i])
        rest = toks[i + 1:]
        if prog in ("gh", "ssh", "scp", "sftp"):
            return "%s is not available to an agent" % prog
        if prog == "git":
            words = [t for t in rest if not t.startswith("-")]
            if "push" in words:
                return "git push is not available to an agent"
            if words[:1] == ["remote"] and len(words) > 1 and words[1] in ("add", "set-url", "remove", "rm"):
                return "changing a git remote is not available to an agent"
    return None


def main():
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
    except ValueError:
        return 0
    why = blocked(command)
    if why:
        print("qargi guard: %s. Agents never push; return patches instead." % why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
