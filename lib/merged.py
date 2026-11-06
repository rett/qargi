#!/usr/bin/env python3
"""Is the work of a run merged? The one test local list, local clean and lead compact-check / feature finish share.

  merged.py REPO TIP --state DIR [--branch NAME] [--answers JSON]     exit 0 merged, 1 not merged, 2 no tip that is a full hex object name

TIP is the commit a run's applied file records (qargi review apply: the second word), which a member can write; NAME is the first word of that file, the
branch review apply made. When the lead's ref journal ($STATE/ref-journal.jsonl) has a review:apply line for that branch in this repository, its tip is
the one tested and the file's is ignored (the journal is the lead's, the file the member's). The tip counts as merged when it (or the commit the lead
rewrote it to) is on a local branch other than agent/*, other than a worktree-bridge-* branch and other than a ref the run's answers declare the runtime's
own (JSON, the copy of the answers in the lead's registry: runs.owned_refs, matched as lib/owned_refs.py matches): a member can create such a branch at
the tip, and a branch the lead did not make settles nothing. A rewrite is the lead's own, journaled by
`qargi ref record --rewrite` (verb ref:rewrite, the same tree) in $STATE/ref-journal.jsonl: the journal is followed from TIP, line by line, to
the last rewrite of each commit, and the run is merged when any commit on that path is. A word that is not a full hex name never reaches git,
so an option-like text cannot become an option of for-each-ref; the value is given in the --contains=VALUE form and the ref patterns after --.
Read-only; python3 -I, standard library only. lib/local.sh (merged_tip) runs it, and lib/lead_usage.py imports it."""
import importlib.util, json, os, re, subprocess, sys

HEX = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?")
MAX_STEPS = 50


def valid_tip(tip):
    return isinstance(tip, str) and HEX.fullmatch(tip) is not None


def rewrites(state, repo):
    """{old: new} of the rewrites the lead recorded for this repository (the last line wins)."""
    out = {}
    try:
        rp = os.path.realpath(repo)
        with open(os.path.join(state, "ref-journal.jsonl"), errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if (isinstance(r, dict) and r.get("verb") == "ref:rewrite" and r.get("repo") == rp
                        and valid_tip(r.get("old")) and valid_tip(r.get("new"))):
                    out[r["old"]] = r["new"]
    except OSError:
        pass
    return out


def owned_module():
    spec = importlib.util.spec_from_file_location("owned_refs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "owned_refs.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def excluder(answers):
    """A function ref name -> True for the refs that settle nothing: agent/*, bridge branches, and the refs the answers declare owned."""
    pats, ll = [], []
    if isinstance(answers, dict):
        try:
            pats, ll = owned_module().from_answers(answers)
        except Exception:                                  # noqa: BLE001  (an unreadable pattern list excludes nothing more)
            pats, ll = [], []
    om = owned_module() if pats else None

    def skip(ref):
        if ref.startswith(("refs/heads/agent/", "refs/heads/worktree-bridge-")):
            return True
        return bool(om) and om.match(pats, ref, ll) is not None
    return skip


def journal_tip(state, repo, branch):
    """The tip the lead's ref journal records for the last review:apply of BRANCH in this repository, or ''."""
    best = ""
    if not branch:
        return best
    try:
        rp = os.path.realpath(repo)
        with open(os.path.join(state, "ref-journal.jsonl"), errors="replace") as f:
            for ln in f:
                try:
                    r = json.loads(ln)
                except ValueError:
                    continue
                if (isinstance(r, dict) and r.get("verb") == "review:apply" and r.get("repo") == rp and r.get("ref") == "refs/heads/" + branch
                        and "remote" not in r and valid_tip(r.get("new"))):
                    best = r["new"]
    except OSError:
        pass
    return best


def on_branch(repo, tip, skip=None):
    """True when the commit is on a local branch that settles it: not agent/*, not a worktree-bridge-* branch, not an owned ref (skip decides)."""
    skip = skip or excluder(None)
    try:
        r = subprocess.run(["git", "-C", repo, "for-each-ref", "--contains=" + tip, "--format=%(refname)", "--", "refs/heads"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and any(x and not skip(x) for x in r.stdout.split())


def merged_tip(repo, tip, state, branch=None, answers=None):
    """0 merged, 1 not merged, 2 there is no tip that is a full hex object name. The journaled tip of BRANCH's review:apply, when there is one, replaces TIP."""
    jt = journal_tip(state, repo, branch) if state else ""
    tip = jt or tip
    if not valid_tip(tip):
        return 2
    rw, n = rewrites(state, repo) if state else {}, 0
    skip = excluder(answers)
    while True:
        if on_branch(repo, tip, skip):
            return 0
        if tip not in rw or n >= MAX_STEPS:
            return 1
        tip, n = rw[tip], n + 1


def merged(repo, tip, state, branch=None, answers=None):
    """True when merged_tip says so."""
    return bool(repo) and merged_tip(repo, tip, state, branch, answers) == 0


def main(argv):
    usage = "usage: merged.py REPO TIP --state DIR [--branch NAME] [--answers JSON]"
    if len(argv) < 4 or argv[2] != "--state":
        print(usage, file=sys.stderr)
        return 64
    branch, answers, rest = None, None, argv[4:]
    while rest:
        if len(rest) < 2 or rest[0] not in ("--branch", "--answers"):
            print(usage, file=sys.stderr)
            return 64
        if rest[0] == "--branch":
            branch = rest[1]
        else:
            try:
                answers = json.loads(rest[1])
            except ValueError:
                answers = None
        rest = rest[2:]
    return merged_tip(argv[0], argv[1], argv[3], branch, answers)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
