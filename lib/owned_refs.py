#!/usr/bin/env python3
"""Refs a runtime or harness creates in the repository, declared by the lead: the project answer runs.owned_refs.

  owned_refs.py match ANSWERS_FILE REFNAME [--base BRANCH]...     exit 0 and print the pattern when REFNAME is a declared owned ref, 1 when not

runs.owned_refs is a list of glob patterns for full ref names (["refs/heads/foo-*"]). `qargi local verify` and `local clean` accept a change of a
ref that matches one, in either phase, and name the pattern ("accepted: refs/heads/foo-* (owned by the runtime, per runs.owned_refs)"). It is the
lead's answer: the guard refuses `qargi project set` of it to a member. The harness's own bridge branches (worktree-bridge-NAME) stay built in.

A pattern is hardened so that it cannot become a way round the ref check:
  - it is a full ref name: refs/NAMESPACE/REST, NAMESPACE with no glob character, and only letters, digits, . _ - / and the globs * and ?
    (* matches any characters, a slash too, as in a shell `case`);
  - REST starts with a literal prefix of at least 3 characters (so refs/heads/* and refs/heads/ab* are refused);
  - it may not match refs/heads/develop, refs/heads/master or a branch in repo.long_lived, and may not reach into the git-flow namespaces
    (agent/, feature/, release/, hotfix/): a member's rewrite of those is what the ref check is for;
  - at the time of the check a ref is also never accepted when it is the base of a run that is not cleaned or closed (--base), whatever the
    pattern says; a pattern that fails any of these is ignored there (project validate names it).
A ref that matches no valid pattern is checked as before, in the strict phase too. Read-only; python3 -I, standard library only."""
import fnmatch, json, re, sys

CHARS = re.compile(r"[A-Za-z0-9._/*?-]+")
GLOBS = "*?"
MIN_LITERAL = 3
MAX_PATTERNS = 32
ALWAYS = ("develop", "master")
FLOW_PREFIXES = ("agent/", "feature/", "release/", "hotfix/")


def protected_refs(protected=()):
    """The branches no pattern may match: develop, master, the project's long-lived branches."""
    names = list(ALWAYS) + [b for b in protected if isinstance(b, str) and b]
    return ["refs/heads/" + b for b in dict.fromkeys(names)]


def pattern_problem(pat, protected=()):
    """The reason a pattern is refused, or '' when it is fine."""
    if not isinstance(pat, str) or not pat:
        return "must be a non-empty string"
    if not CHARS.fullmatch(pat):
        return "may hold only letters, digits, . _ - / and the globs * and ?"
    if not pat.startswith("refs/") or ".." in pat or "//" in pat or pat.endswith(("/", ".", ".lock")):
        return "must be a full ref name such as refs/heads/foo-* (no .., //, or trailing / . .lock)"
    parts = pat.split("/")
    if len(parts) < 3 or any(c in parts[1] for c in GLOBS):
        return "must be refs/NAMESPACE/NAME... with a literal NAMESPACE (refs/heads/foo-*)"
    rest = "/".join(parts[2:])
    literal = re.split(r"[*?]", rest, maxsplit=1)[0]
    if len(literal) < MIN_LITERAL:
        return "must start (after refs/%s/) with a literal prefix of at least %d characters, not %r" % (parts[1], MIN_LITERAL, literal)
    if parts[1] == "heads":
        if literal.startswith(FLOW_PREFIXES):
            return "reaches into the git-flow branches (agent/, feature/, release/, hotfix/), which a run's ref check is for"
        for pre in FLOW_PREFIXES:
            if fnmatch.fnmatchcase("refs/heads/" + pre + "x", pat):
                return "would match git-flow branches (%s*), which a run's ref check is for" % pre
    for ref in protected_refs(protected):
        if fnmatch.fnmatchcase(ref, pat):
            return "would match %s, which no run may touch" % ref
    return ""


def problems(value, protected=()):
    """The findings about a runs.owned_refs value (project validate), one line each; [] when it is fine."""
    if not isinstance(value, list):
        return ["runs.owned_refs: a list of ref patterns such as [\"refs/heads/foo-*\"]"]
    out = []
    if len(value) > MAX_PATTERNS:
        out.append("runs.owned_refs: at most %d patterns" % MAX_PATTERNS)
    if len(set(x for x in value if isinstance(x, str))) != len([x for x in value if isinstance(x, str)]):
        out.append("runs.owned_refs: a pattern is listed twice")
    for i, pat in enumerate(value):
        why = pattern_problem(pat, protected)
        if why:
            out.append("runs.owned_refs[%d]: %s" % (i, why))
    return out


def match(patterns, name, protected=(), bases=()):
    """The first valid pattern that matches the ref name, or None. Never a protected ref or the base of an open run."""
    if not isinstance(patterns, list) or not isinstance(name, str) or not name.startswith("refs/"):
        return None
    forbidden = set(protected_refs(protected))
    for b in bases:
        if isinstance(b, str) and b:
            forbidden.add(b if b.startswith("refs/") else "refs/heads/" + b)
    if name in forbidden:
        return None
    for pat in patterns[:MAX_PATTERNS]:
        if not pattern_problem(pat, protected) and fnmatch.fnmatchcase(name, pat):
            return pat
    return None


def answers(path):
    try:
        with open(path) as f:
            d = json.load(f)
    except (OSError, ValueError):
        return [], []
    d = d if isinstance(d, dict) else {}
    runs = d.get("runs") if isinstance(d.get("runs"), dict) else {}
    repo = d.get("repo") if isinstance(d.get("repo"), dict) else {}
    ll = repo.get("long_lived")
    return runs.get("owned_refs"), (ll if isinstance(ll, list) else [])


def main(argv):
    if len(argv) < 3 or argv[0] != "match":
        print("usage: owned_refs.py match ANSWERS_FILE REFNAME [--base BRANCH]...", file=sys.stderr)
        return 64
    bases, rest = [], argv[1:]
    while "--base" in rest:
        i = rest.index("--base")
        if i + 1 >= len(rest):
            return 64
        bases.append(rest[i + 1])
        rest = rest[:i] + rest[i + 2:]
    if len(rest) != 2:
        return 64
    pats, ll = answers(rest[0])
    hit = match(pats, rest[1], ll, bases)
    if hit is None:
        return 1
    print(hit)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
