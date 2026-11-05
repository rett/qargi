"""qargi project profile check: read a repository's profile (~/.qargi/config/profiles/<repository>.md, or the file given) and say what is
wrong with it. Read only; nothing is written.

  project_profile.py check CONF ANSWERS PROFILE   print the findings; exit 1 when the profile still carries the shipped template header,
                                                  0 otherwise (a gate command the repository does not know is a warning only)
  project_profile.py warn CONF ANSWERS            print one WARN line when the project's profile carries the template header (project validate)

CONF is the config directory, ANSWERS the project's answers file ("" for none: the repository is then the one the current directory is in),
PROFILE a profile file ("" for CONF/profiles/<repository name>.md). The repository's name is the name of its directory (repo.path), else the
last part of repo.url, else the project's name.

The shipped example (examples/myproject/profile.md) opens with an "Example profile" title and a "Copy to ~/.qargi/config/profiles/<repository-name>.md"
line: a profile that still has either was copied and not adapted. The gate commands are the backticked commands of the profile's "Gates"
section; each must be found in the repository's instruction files (DOC_FILES: the files `qargi attach` reads) or its Makefile: a make target of
the Makefile, the text of the command in one of those files, or a script that exists in the repository.
"""
import json
import os
import re
import sys

HEAD_LINES = 12     # the template header is at the top; look no further
TITLE = re.compile(r"^#+\s*Example profile\b", re.I)
COPY = re.compile(r"profiles/<[^>]*>\.md")
DOC_FILES = ("CLAUDE.md", "AGENTS.md", "Makefile")


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def repo_name(ans):
    repo = ans.get("repo") if isinstance(ans.get("repo"), dict) else {}
    path = repo.get("path") or ""
    if isinstance(path, str) and path.strip():
        return os.path.basename(os.path.expanduser(path).rstrip("/"))
    url = repo.get("url") or ""
    if isinstance(url, str) and url.strip() and "OWNER/REPO" not in url:
        return re.sub(r"\.git$", "", url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1])
    return ans.get("project") or ""


def repo_dir(ans):
    """The repository's directory: repo.path of the answers, else the repository the current directory is in, else None."""
    repo = ans.get("repo") if isinstance(ans.get("repo"), dict) else {}
    path = repo.get("path") or ""
    if isinstance(path, str) and path.strip():
        return os.path.expanduser(path)
    here = os.path.realpath(os.getcwd())
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return here
        up = os.path.dirname(here)
        if up == here:
            return None
        here = up


def header_findings(lines):
    """[(line number, text)] of the lines at the top of the profile that are the shipped example's."""
    out = []
    for n, ln in enumerate(lines[:HEAD_LINES], 1):
        if TITLE.match(ln) or COPY.search(ln):
            out.append((n, ln.strip()))
    return out


def gates_section(lines):
    """[(line number, text)] of the lines under the profile's Gates heading, up to the next heading."""
    out, inside = [], False
    for n, ln in enumerate(lines, 1):
        if re.match(r"^#+\s", ln):
            inside = bool(re.match(r"^#+\s*Gates\b", ln, re.I))
            continue
        if inside:
            out.append((n, ln))
    return out


def is_path(span):
    """A backticked span that names files (internal/**, docs/, README.md) and not a command. A span that starts with a capital (an output
    line such as GATE-GO PASS, a variable assignment) is not a command either; gate_commands skips those."""
    if re.search(r"\s", span):
        return False
    return "*" in span or span.endswith("/") or bool(re.fullmatch(r"[\w./-]+\.(md|txt|json|ya?ml|toml|rst)", span))


def make_targets(text):
    """The targets a Makefile defines: the names before a colon (not :=) and the .PHONY lists."""
    out = set()
    for ln in text.splitlines():
        m = re.match(r"^([^\s#:=\t][^:=#]*?)\s*:(?![=:])", ln)
        if m:
            out.update(w for w in m.group(1).split() if not w.startswith("."))
        m = re.match(r"^\.PHONY\s*:(.*)", ln)
        if m:
            out.update(m.group(1).split())
    return out


def gate_commands(lines):
    """[(line number, command)] of the backticked commands of the Gates section, each once."""
    seen, out = set(), []
    for n, ln in gates_section(lines):
        for span in re.findall(r"`([^`\n]+)`", ln):
            span = span.strip()
            if span and re.match(r"[a-z./_]", span) and not is_path(span) and span not in seen:
                seen.add(span)
                out.append((n, span))
    return out


def known(cmd, repo, text, targets):
    if cmd in text:
        return True
    words = cmd.split()
    if words and words[0] == "make":
        asked = [w for w in words[1:] if not w.startswith("-") and "=" not in w]
        if targets is not None and all(w in targets for w in asked):
            return True
    return bool(words) and "/" in words[0] and os.path.exists(os.path.join(repo, words[0]))


def read_lines(path):
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return None


def check(conf, answers, given):
    ans = load(answers) if answers else {}
    name = repo_name(ans)
    repo = repo_dir(ans)
    if not name and repo:
        name = os.path.basename(repo.rstrip("/"))
    path = given or os.path.join(conf, "profiles", name + ".md")
    lines = read_lines(path)
    if lines is None:
        if given:
            print("qargi: no such profile file: " + given, file=sys.stderr)
            return 2
        print("no profile at %s (a profile is optional; the example to copy is examples/myproject/profile.md of the qargi install)" % path)
        return 0
    print("profile: %s%s" % (path, " (repository %s)" % name if name else ""))
    rc = 0
    heads = header_findings(lines)
    for n, text in heads:
        print('FAIL line %d still carries the shipped template header: "%s"' % (n, text[:100]))
    if heads:
        print("FAIL replace the title and drop the \"Copy to\" line: this profile is the shipped example, not one for %s" % (name or "this repository"))
        rc = 1
    warned = 0
    cmds = gate_commands(lines)
    if repo is None or not os.path.isdir(repo):
        print("WARN the repository directory is not known or not found, so the gate commands were not checked (answers repo.path)")
        warned += 1
    else:
        docs = {}
        for f in DOC_FILES:
            try:
                with open(os.path.join(repo, f), errors="replace") as fh:
                    docs[f] = fh.read()
            except OSError:
                pass
        if not docs:
            print("WARN none of the instruction files or the Makefile is in %s, so the gate commands were not checked" % repo)
            warned += 1
        else:
            text = "\n".join(docs.values())
            targets = make_targets(docs["Makefile"]) if "Makefile" in docs else None
            for n, cmd in cmds:
                if not known(cmd, repo, text, targets):
                    print("WARN line %d: gate `%s` is not in the instruction files or the Makefile targets of %s" % (n, cmd, repo))
                    warned += 1
            if not warned:
                print("ok   %d gate commands, each found in the repository's instruction files or Makefile" % len(cmds) if cmds else "ok   the profile lists no gate command")
    if warned:
        print("%d warning%s (gates are only looked for in those files; a gate the repository runs some other way is fine)" % (warned, "" if warned == 1 else "s"))
    return rc


def warn(conf, answers):
    ans = load(answers)
    if not ans:
        return 0
    path = os.path.join(conf, "profiles", repo_name(ans) + ".md")
    lines = read_lines(path)
    if lines and header_findings(lines):
        print("WARN: the profile %s still carries the shipped template header; adapt it to the repository (qargi project profile check %s)" % (path, ans.get("project") or "NAME"))
    return 0


def main(argv):
    if len(argv) == 5 and argv[1] == "check":
        return check(argv[2], argv[3], argv[4])
    if len(argv) == 4 and argv[1] == "warn":
        return warn(argv[2], argv[3])
    print("usage: project_profile.py check CONF ANSWERS PROFILE | warn CONF ANSWERS", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
