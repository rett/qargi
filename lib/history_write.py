#!/usr/bin/env python3
"""The writers of the history (lib/history.py): what feature verify, release verify (lib/gitflow.sh) and review check (lib/review.sh) call to append an entry.

  history_write.py suite  --project P --verb V --name N --branch B --head H --tree T --command=C [--env-id=E] --result R --started S --seconds N
                          [--load-start X] [--log FILE] [--gates FILE] [--names FILE|-]
  history_write.py review --project P --run ID --slug S --facts FILE [--base B] [--base-sha H] [--role R] [--class C] [--runtime=R] [--model=M]

An option whose value may start with a hyphen is written with `=`. The entry is built here (lib/history.py), checked against its registry file and
appended; the log of a suite run is kept and the logs over the cap are removed. Exit status: 0, or 1 with a line on standard error when nothing could be
written: the caller goes on, the history is evidence and no gate. Standard library and lib/history.py only."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I does not put the script's directory on sys.path
import history as H  # noqa: E402


def write_main(argv):
    p = argparse.ArgumentParser(prog="history_write.py", allow_abbrev=False)
    sub = p.add_subparsers(dest="what", required=True)
    s = sub.add_parser("suite")
    s.add_argument("--project", required=True)
    s.add_argument("--verb", required=True, choices=H.VERBS)
    s.add_argument("--name", required=True)
    s.add_argument("--branch", required=True)
    s.add_argument("--head", required=True)
    s.add_argument("--tree", required=True)
    s.add_argument("--command", required=True)
    s.add_argument("--env-id", default="")
    s.add_argument("--result", required=True, choices=H.RESULTS)
    s.add_argument("--started", required=True)
    s.add_argument("--seconds", required=True, type=int)
    s.add_argument("--load-start", default="")
    s.add_argument("--log", default="")
    s.add_argument("--gates", default="")
    s.add_argument("--names", default="")
    r = sub.add_parser("review")
    r.add_argument("--project", required=True)
    r.add_argument("--run", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--facts", required=True)
    r.add_argument("--base", default="")
    r.add_argument("--base-sha", default="")
    r.add_argument("--role", default="")
    r.add_argument("--class", dest="cls", default="")
    r.add_argument("--runtime", default="")
    r.add_argument("--model", default="")
    a = p.parse_args(argv)
    try:
        project = H.check_project(a.project)
        if a.what == "suite":
            entry, number = H.suite_entry(project, a)
            H.append(project, entry, prepare=number)
            H.keep_logs(project)
        else:
            H.append(project, H.review_entry(project, a))
    except H.HistoryError as e:
        print("qargi: warning: history: %s; no entry was written" % e, file=sys.stderr)
        return 1
    return 0


def main(argv):
    return write_main(argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
