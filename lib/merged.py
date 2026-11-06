#!/usr/bin/env python3
"""Is the work of a run merged? The one test local list, local clean and lead compact-check / feature finish share.

  merged.py REPO TIP --state DIR       exit 0 merged, 1 not merged, 2 TIP is not a full hex object name

TIP is the commit a run's applied file records (qargi review apply: the second word), which a member can write. It counts as merged when it
(or the commit the lead rewrote it to) is on a local branch other than agent/*. A rewrite is the lead's own, journaled by
`qargi ref record --rewrite` (verb ref:rewrite, the same tree) in $STATE/ref-journal.jsonl: the journal is followed from TIP, line by line, to
the last rewrite of each commit, and the run is merged when any commit on that path is. A word that is not a full hex name never reaches git,
so an option-like text cannot become an option of for-each-ref; the value is given in the --contains=VALUE form and the ref patterns after --.
Read-only; python3 -I, standard library only. lib/local.sh (merged_tip) runs it, and lib/lead_usage.py imports it."""
import json, os, re, subprocess, sys

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


def on_branch(repo, tip):
    """True when the commit is on a local branch other than agent/*."""
    try:
        r = subprocess.run(["git", "-C", repo, "for-each-ref", "--contains=" + tip, "--format=%(refname)", "--", "refs/heads"],
                           capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=60,
                           env=dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0"))
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0 and any(x and not x.startswith("refs/heads/agent/") for x in r.stdout.split())


def merged_tip(repo, tip, state):
    """0 merged, 1 not merged, 2 the tip is not a full hex object name."""
    if not valid_tip(tip):
        return 2
    rw, n = rewrites(state, repo) if state else {}, 0
    while True:
        if on_branch(repo, tip):
            return 0
        if tip not in rw or n >= MAX_STEPS:
            return 1
        tip, n = rw[tip], n + 1


def merged(repo, tip, state):
    """True when merged_tip says so."""
    return bool(repo) and merged_tip(repo, tip, state) == 0


def main(argv):
    if len(argv) != 4 or argv[2] != "--state":
        print("usage: merged.py REPO TIP --state DIR", file=sys.stderr)
        return 64
    return merged_tip(argv[0], argv[1], argv[3])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
