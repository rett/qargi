#!/usr/bin/env python3
"""qargi plan show TOKEN [--json]: the stored record of a plan (STATE/plans/TOKEN.json, written by `plan_token --basis`), read only.

It changes nothing: no file is made or removed (an expired record stays, the store prunes), no audit line, no lock; it works under QARGI_DRY=1. The directory and the
file are opened without following a link, and the file must be a regular file of one link and mode 600. Before anything is printed the record is checked: its schema, its
form, the hash of its lines against input_sha256, the token against that hash and against the name of the file. A record that fails is not shown:

  plan-unknown          not 12 hex digits, no such file, or a file of before the schema (no `schema` key)
  plan-record-invalid   a link, a file of the wrong kind or mode, one that cannot be read, damaged JSON, an unknown schema, a malformed record, or lines that do not hash to the token
  plan-expired          `expires` is past (QARGI_PLAN_NOW, a time like 2026-11-22T10:00:00Z, stands for the clock in tests)

Text: the verb, the target, the labelled lines, created and expires; a control character in a value is printed as \\xNN. --json: the record as it was stored, and "state": "valid". Exit 0, 1 for a refusal, 2 for a
usage error. Standard library only; the checks are lib/refusal.py's (plan_read)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import refusal  # noqa: E402

USAGE = "usage: qargi plan show TOKEN [--json]"


def esc(value):
    """The value with each control character (C0, DEL, C1) written as \\xNN: a value is text the lead chose, and a terminal must not act on it."""
    return "".join("\\x%02x" % ord(c) if ord(c) < 0x20 or 0x7f <= ord(c) <= 0x9f else c for c in value)


def text_of(rec):
    out = ["plan %s: %s (%s)" % (rec["token"], rec["verb"], rec["context"]),
           "target: %s %s" % (rec["target"]["project"], esc(rec["target"]["object"]))]
    width = max([len(x["label"]) for x in rec["lines"]] or [0])
    out += ["  %s  %s" % (x["label"].ljust(width), esc(x["value"])) for x in rec["lines"]]
    out += ["created: " + rec["created"], "expires: " + rec["expires"]]
    return "\n".join(out) + "\n"


def show(argv):
    as_json = "--json" in argv
    rest = [a for a in argv if a != "--json"]
    if len(rest) != 1 or rest[0].startswith("-"):
        sys.stderr.write(USAGE + "\n")
        return 2
    try:
        rec = refusal.plan_read(rest[0])
    except refusal.PlanRefusal as e:        # one call for each code, so that the lint of the catalogue finds the raise
        if e.code == "plan-unknown":
            return refusal.refuse("plan-unknown", e.pairs, verb="plan show")
        if e.code == "plan-expired":
            return refusal.refuse("plan-expired", e.pairs, verb="plan show")
        return refusal.refuse("plan-record-invalid", e.pairs, verb="plan show")
    except refusal.Defect as e:
        sys.stderr.write("qargi: defect: %s\n" % e)
        return 70
    if as_json:
        sys.stdout.write(json.dumps(dict(rec, state="valid"), separators=(",", ":")) + "\n")
    else:
        sys.stdout.write(text_of(rec))
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "show":
        return show(argv[1:])
    sys.stderr.write(USAGE + "\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
