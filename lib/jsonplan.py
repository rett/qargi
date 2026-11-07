#!/usr/bin/env python3
"""qargi ... --json: the plan of a gated verb as one JSON object, so the lead does not read a token out of text.

bin/qargi hands every call that carries --json here (the one place; no verb knows about it). The call runs as it would without the flag,
with the same standard input and error, and its standard output is captured and wrapped:

  a plan token in the output   {"verb": "packs seed", "plan": TEXT, "token": HEX, "apply": COMMAND LINE, "exit": N}
  none                         {"verb": "packs seed", "plan": null, "token": null, "output": TEXT, "exit": N}

TEXT is the output without the token line(s). COMMAND LINE is the call as given, without --json, plus --plan HEX and --approved "<the user's
go-ahead>": the flag never supplies the approval, only the person's words do. A call that already carries --plan or --approved was
not asking for a plan: it runs and its output is wrapped with a null token. A verb that has an option --json of its own
(lib/commands.py) is left alone and sees the flag. The exit status is the verb's.

Usage (from bin/qargi): jsonplan.py AREA ARGUMENT...   (the arguments with --json in them). The program it runs is the bin/qargi beside this lib, never a
name it is given: the guard judges the call by its words.
"""
import json, os, re, shlex, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = re.compile(r"plan token: ([0-9a-f]+)")
# the hint after the token, to the end of its line: "   (apply with: ...)"
HINT = re.compile(r"plan token: [0-9a-f]+(?:[ \t]*\([^\n]*\))?")
GO_AHEAD = "<the user's go-ahead>"
GATE_FLAGS = ("--plan", "--approved")


def verb_name(args):
    """'AREA VERB' for a call that names a verb the command description knows, else 'AREA'."""
    sys.path.insert(0, HERE)
    import commands as C
    area = args[0] if args else ""
    spec = C.COMMANDS.get(area, {})
    verbs = spec.get("verbs")
    verb = args[1] if len(args) > 1 and isinstance(verbs, dict) and args[1] in verbs else ""
    return (area + " " + verb).strip(), spec, verbs.get(verb) if verb else None


def has_own_json(spec, verb_spec):
    """True when the verb (or, for a command without verbs, the command) documents --json for itself."""
    opts = (verb_spec["opts"] if verb_spec else spec.get("opts", []))
    return any(o["flag"] == "--json" for o in opts)


def carries_gate(args):
    return any(a in GATE_FLAGS or a.startswith(tuple(f + "=" for f in GATE_FLAGS)) for a in args)


def plan_text(out):
    """The output without the token line(s): a line that is only the token and its hint goes, a line that says more (plan only, ...; plan token: ...) keeps the rest."""
    lines = []
    for line in out.split("\n"):
        if not TOKEN.search(line):
            lines.append(line)
            continue
        rest = HINT.sub("", line).strip(" \t;,:")
        if rest:
            lines.append(rest)
    return "\n".join(lines).strip("\n")


def main(argv):
    qargi, given = os.path.join(os.path.dirname(HERE), "bin", "qargi"), argv
    args = [a for a in given if a != "--json"]
    name, spec, vspec = verb_name(args)
    env = dict(os.environ, QARGI_NO_JSON_WRAP="1")          # bin/qargi takes it out again: nothing below this call sees it
    if has_own_json(spec, vspec):
        os.execve(qargi, [qargi] + given, env)
    r = subprocess.run([qargi] + args, stdout=subprocess.PIPE, env=env)
    out = r.stdout.decode("utf-8", "replace")
    code = r.returncode if r.returncode >= 0 else 128 - r.returncode
    m = None if carries_gate(args) else TOKEN.search(out)
    if m:
        apply = " ".join(["qargi"] + [shlex.quote(a) for a in args] + ["--plan", m.group(1), "--approved", '"%s"' % GO_AHEAD])
        doc = {"verb": name, "plan": plan_text(out), "token": m.group(1), "apply": apply, "exit": code}
    else:
        doc = {"verb": name, "plan": None, "token": None, "output": out, "exit": code}
    sys.stdout.write(json.dumps(doc) + "\n")
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
