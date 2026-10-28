#!/usr/bin/env python3
"""qargi __guard: a PreToolUse hook for the local members' Bash, Edit, Write and NotebookEdit tools. Reads the hook's
JSON on stdin and refuses (exit 2, reason on stderr) what would publish or reach out: git push, gh, ssh, scp, sftp, and
changing a remote. A second barrier beside the git wrapper (which has no credentials) and `qargi local verify`; an
agent that goes out of its way can still get around it, which is why verify exists.

Review is read-only as a rule: `qargi local prepare` writes the task's ability to RUN/ability. When the nearest run
directory above the call's cwd or file path says review, the guard also refuses an edit outside RUN/out (the report
and the manifest) and a Bash command that writes into the clone: a redirection into it, a command that creates,
changes or removes files there, or a git command that changes the work tree or the history. Anything else exits 0."""
import json, os, re, shlex, sys

SEGMENT = re.compile(r"\s*(?:&&|\|\||;|\||\n)\s*")
WRAP = {"sudo", "env", "command", "exec", "nohup", "time", "timeout", "setsid", "xargs", "nice"}
WRITERS = {"rm", "rmdir", "touch", "mkdir", "chmod", "chown", "truncate", "tee", "patch", "unlink", "shred"}
COPIERS = {"cp", "mv", "ln", "install", "rsync"}            # the last argument is the destination
INPLACE = {"sed", "perl"}                                   # with -i
GIT_WRITES = {"add", "commit", "apply", "am", "checkout", "switch", "reset", "rm", "mv", "stash", "merge", "rebase",
              "cherry-pick", "revert", "restore", "clean", "tag", "branch", "pull", "fetch", "init", "clone", "worktree",
              "notes", "update-ref", "config", "submodule"}
REDIR = re.compile(r"^(?:\d*|&)>>?(.*)$")


def blocked(command):
    for seg in SEGMENT.split(command):
        toks = tokens(seg)
        i = skip_wrappers(toks)
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


def tokens(seg):
    try:
        toks = shlex.split(seg)
    except ValueError:
        toks = seg.split()
    return toks


def skip_wrappers(toks):
    i = 0
    while i < len(toks) and ("=" in toks[i].split("/")[0] and not toks[i].startswith("-")
                             or os.path.basename(toks[i]) in WRAP or toks[i].isdigit() or (toks[i].startswith("-") and i)):
        i += 1
    return i


def run_dir(path):
    """The nearest directory at or above path that `qargi local prepare` made (it holds ability and refs.before)."""
    p = os.path.realpath(path) if path else ""
    while p and p != os.path.dirname(p):
        if os.path.isfile(os.path.join(p, "ability")) and os.path.isfile(os.path.join(p, "refs.before")):
            return p
        p = os.path.dirname(p)
    return None


def ability_of(run):
    try:
        with open(os.path.join(run, "ability")) as f:
            return f.read().strip()
    except OSError:
        return ""


def inside(path, base):
    return path == base or path.startswith(base + os.sep)


def review_refusal(tool, inp, cwd):
    """The reason a call under the review ability is refused, or None."""
    if tool in ("Edit", "Write", "NotebookEdit", "MultiEdit"):
        fp = inp.get("file_path") or inp.get("notebook_path") or ""
        if not fp:
            return None
        full = os.path.realpath(os.path.join(cwd, fp))
        run = run_dir(os.path.dirname(full)) or run_dir(cwd)
        if run and ability_of(run) == "review" and not inside(full, os.path.join(run, "out")):
            return "under the review ability only the report and the manifest in RUN_DIR may be written (%s is not)" % fp
        return None
    if tool != "Bash":
        return None
    command = inp.get("command") or ""
    here = cwd
    for seg in SEGMENT.split(command):
        toks = tokens(seg)
        i = skip_wrappers(toks)
        if i < len(toks) and toks[i] == "cd" and i + 1 < len(toks):
            here = os.path.realpath(os.path.join(here, os.path.expanduser(toks[i + 1])))
            continue
        why = review_segment(toks, i, here)
        if why:
            return why
    return None


def review_segment(toks, i, here):
    def resolve(p):
        return os.path.realpath(os.path.join(here, os.path.expanduser(p)))
    targets, gitdir = [], None
    for k, t in enumerate(toks):                       # redirections anywhere in the segment
        m = REDIR.match(t)
        if m and not t.startswith(">&") and not re.match(r"^\d*>&\d+$", t):
            dest = m.group(1) or (toks[k + 1] if k + 1 < len(toks) else "")
            if dest and dest != "/dev/null":
                targets.append(("a redirection", dest))
    if i < len(toks):
        prog, rest = os.path.basename(toks[i]), toks[i + 1:]
        args = [t for t in rest if not t.startswith("-") and not REDIR.match(t)]
        if prog in WRITERS:
            targets += [(prog, a) for a in args]
        elif prog in COPIERS and args:
            targets.append((prog, args[-1]))
        elif prog in INPLACE and any(t.startswith("-i") or t == "--in-place" for t in rest):
            targets += [(prog + " -i", a) for a in args[1:]]
        elif prog == "git":
            k = 0
            while k < len(rest) and rest[k].startswith("-"):
                if rest[k] == "-C" and k + 1 < len(rest):
                    gitdir = rest[k + 1]; k += 2
                elif rest[k] in ("-c", "--git-dir", "--work-tree"):
                    k += 2
                else:
                    k += 1
            sub = rest[k] if k < len(rest) else ""
            if sub in GIT_WRITES:
                targets.append(("git " + sub, gitdir or "."))
    for what, dest in targets:
        full = resolve(dest)
        run = run_dir(full if os.path.isdir(full) else os.path.dirname(full)) or run_dir(here)
        if run and ability_of(run) == "review" and inside(full, os.path.join(run, "clone")):
            return "under the review ability nothing in the clone may be changed (%s into %s)" % (what, dest)
    return None


def main():
    try:
        data = json.load(sys.stdin)
        tool = data.get("tool_name") or "Bash"
        inp = data.get("tool_input") or {}
        cwd = data.get("cwd") or os.getcwd()
    except ValueError:
        return 0
    why = blocked(inp.get("command") or "") if tool == "Bash" else None
    if why:
        print("qargi guard: %s. Agents never push; return patches instead." % why, file=sys.stderr)
        return 2
    why = review_refusal(tool, inp, cwd)
    if why:
        print("qargi guard: %s. A review reads the work and writes its report to RUN_DIR." % why, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
