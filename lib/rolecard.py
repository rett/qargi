#!/usr/bin/env python3
"""The role cards: what a role is held to, said before the guard or a verb refuses it. Standard library only; it names no runtime.

  rolecard.py card ROLE [--project P] [--run RUN] [--json]

prints the card of ROLE, read-only (nothing is written, nothing is asked of a remote). A card is generated, not written by hand: from the role's
class (lib/role.py), the verbs that take a plan (lib/commands.py), the status of the codes of the catalogue of refusals (lib/refusals.json) and,
for a lead, the member states the last `qargi agent list` stored. Three cards exist:

  write      a role of class write (build, write, test and the roles of the owner's own of that class): 135 words at most
  read-only  a role of class read-only (review): 215 words at most, the run's real paths filled in
  lead       the lead role: 220 words and 1600 characters at most, the card the session-start hook loads

--run RUN fills in the paths of a prepared run (RUN/clone, RUN/out, the TMP that RUN/tmpdir names); without it the words CLONE, OUT and TMP stand
for them. --project P is where the lead card reads STATE/agent-states.json (written by `qargi agent list`): the line "members STALE or DRIFT as
of TIME" is there only when the project has a stored reading and it names a member in that state (no stored reading, no line). A line that
names a rule whose code is not `live` in the catalogue (the dispatch refusal of a member with no sandbox, the refusal of --approved on a seated
project) is left out until the code is live.

Every command a member card shows, and the sentence it stands under, is checked against the guard by tests/test_rolecard.py: each command
the card calls lawful is let through under the class, each one it calls refused is refused (probes()). The text is data of this module: edit the
constants, then the golden cards (UPDATE_GOLDEN=1 python3 tests/test_rolecard.py) and the ceilings below.

--json prints one object: role, class, card (the text), words, chars, project, run and, for the lead, members_stale (null, or as_of and the
members with their states). Exit status: 0; 1 for a role or a run that is not there; 2 for a usage error.
Library use: card(), probes(), words(). The hook calls this file for the lead role and leaves the block out when it fails."""
import json
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

CEILING = {"write": 135, "read-only": 215, "lead": 220}      # words, the card's own text with each path counted as one word (both member cards carry the line on text the guard reads as a command)
LEAD_CHARS = 1600                                            # the session-start hook's room for the lead card
NAME_RE = re.compile(r"[a-z][a-z0-9-]{0,40}")
STATES = ("STALE", "DRIFT")                                  # the member states the lead card tells of (MISSING is `agent list`'s own line)
READ_MAX = 64 * 1024                                         # the most of agent-states.json that is read: the hook has two seconds, and the file is data
SHOWN = 3                                                    # members named on the lead's line; the rest are +N
USAGE = "usage: rolecard.py card ROLE [--project P] [--run RUN] [--json]"
CLASSES = ("write", "read-only")


class Exit(Exception):
    def __init__(self, code, message=""):
        self.code, self.message = code, message


# ---------------------------------------------------------------------------------------------------------------------------- the member cards
# Each line is (text, allowed, refused): the commands the text calls lawful and the ones it calls refused, with {clone}, {out}, {tmp} and {run}
# filled in. A command in backticks that starts with `git` or `cp` stands in the lists, so a card says nothing the guard has not been asked.

TEXT_LINE = ("A line, even in a heredoc, a quoted string or a commit message, that starts with git push, ssh or gh is refused: write such text with your file tool.",
             (), ("cat > {out}/report.md <<'EOF'\ngit push origin x\nEOF", "cat > {out}/report.md <<'EOF'\nssh host\nEOF", "echo 'a\ngh pr list' > {out}/report.md",
                  "cat > {out}/report.md <<'EOF'\ngh pr view\nEOF"))

READ_ONLY = (
    ("Class read-only (a barrier, not a sandbox):", (), ()),
    ("Read anything but the lead's keys; write only OUT and TMP (tool caches are not judged).",
     ("cat {clone}/README.md", "echo x > {tmp}/note", "echo x > {out}/report.md"), ("cat ~/.qargi/config/credentials/marshal_signing", "echo x > {clone}/note")),
    ("Do not run the whole suite, only the checks that cover what you review.", (), ()),
    ("The report is OUT/report.md; if the file tool is refused, `qargi local report {run} < FILE` or `--from NAME` (it reads OUT only).",
     ("qargi local report {run} < {tmp}/report.md", "qargi local report {run} --from report.md"), ()),
    ("To test patches, copy in TMP: `git -C {tmp} clone {clone} x` (a relative directory lands under -C: {tmp}/x), then `git -C {tmp}/x am {out}/NAME.patch`; "
     "or `cp -a {clone} {tmp}/x`. In the copy only push and remote changes are refused.",
     ("git -C {tmp} clone {clone} x", "git -C {tmp}/x am {out}/NAME.patch", "cp -a {clone} {tmp}/x", "git clone {clone} {tmp}/x", "git -C {tmp}/x commit -am x",
      "git -C {tmp}/x checkout -b y", "git -C {tmp}/x stash"),
     ("git -C {tmp}/x push", "git -C {tmp}/x remote add o u")),
    ("Refused in CLONE: checkout, stash, apply, `git worktree add`, a clone or an init inside it.",
     (),
     ("git -C {clone} checkout main", "git -C {clone} stash", "git -C {clone} apply {out}/p.patch", "git -C {clone} worktree add {tmp}/w", "git clone {tmp} {clone}/x",
      "git init {clone}/y", "git -C {clone} init sub")),
    ("Read BASE with `git show BASE_SHA:PATH` and `git diff BASE_SHA`.", ("git show abc123:PATH", "git diff abc123"), ()),
    ("Assign no variable that picks a program or options (PATH, HOME, TMPDIR, GIT_*, LD_*, BASH_*, PYTHONPATH, NODE_OPTIONS, ...; see `qargi help guard`). "
     "TMPDIR is TMP, where Go tests write. A target platform (GOOS, GOARCH) and `systemd-run` in TMP are allowed.",
     ("GOOS=linux go build ./...", "GOARCH=arm64 go test ./...", "cd {tmp}/x && systemd-run --user --scope make test"),
     ("PATH=/x ls", "export HOME=/x", "TMPDIR={tmp} go test ./...", "GIT_DIR=x git log", "LD_PRELOAD=x ls", "BASH_ENV=x ls", "PYTHONPATH=src python3 -m pytest",
      "env PYTHONPATH=src pytest", "NODE_OPTIONS=--x npm test", "NODE_PATH=x npm test")),
    TEXT_LINE,
    ("Report a refusal's [code]; do not work round it.", (), ("git push",)),
)

# the lead's verbs and directories by area: the guard refuses each, whatever the class
LEAD_REFUSED = ("qargi local verify {run}", "qargi local clean {run}", "qargi local prepare --repo x", "qargi local run {run}", "qargi review apply {run}",
                "qargi release fix 1.0", "qargi release publish 1.0", "qargi release sign 1.0", "qargi feature finish x", "qargi marshal claim x",
                "qargi branch prune", "qargi ref record --rewrite x", "qargi project set p gates x", "qargi skill new x", "qargi packs apply", "qargi upgrade")
LEAD_DIRS = ("printf x > ~/.qargi/memory/x", "printf x > ~/.qargi/state/ref-journal.jsonl", "printf x > ~/.qargi/config/packs/x", "printf x > {run}/ability")

WRITE = (
    ("Class write (a barrier, not a sandbox):", (), ()),
    ("Work in CLONE; patches, report and manifest go in OUT, scratch files in TMP.",
     ("git commit -am x", "echo x > {clone}/f"), ()),
    ("Refused: git push, gh, ssh, git remote changes; the lead's verbs (local verify, clean, prepare, run; review apply; release fix, publish, sign; "
     "feature, marshal, branch, ref, project, skill, packs, upgrade); the lead's directories (state, memory, packs, skills) and the run's record files.",
     (), ("git push", "gh pr list", "git remote add o u") + LEAD_REFUSED + LEAD_DIRS),
    ("A plan you compute goes in your report with its token; never apply it.",
     ("qargi release push 1.0", "qargi release plan 1.0"), ()),
    ("Report a refusal's [code]; do not work round it.", (), ()),
    ("Run only the checks that cover your change; the lead runs the suite.", (), ()),
    (TEXT_LINE[0], (), TEXT_LINE[2] + ("git commit -m 'x\nssh host' --allow-empty",)),
)


def paths_of(run=None):
    """The paths of a prepared run, or the words that stand for them."""
    if not run:
        return {"clone": "CLONE", "out": "OUT", "tmp": "TMP", "run": "RUN"}
    run = os.path.abspath(run)
    if not os.path.isdir(run):
        raise Exit(1, "qargi: %s is not a run directory\n" % run)
    tmp = ""
    try:
        with open(os.path.join(run, "tmpdir"), encoding="utf-8") as f:
            tmp = f.readline().strip()
    except OSError:
        pass
    return {"clone": os.path.join(run, "clone"), "out": os.path.join(run, "out"), "tmp": tmp or os.path.join(run, "tmp"), "run": run}


def fill(text, p):
    for k, v in p.items():
        text = text.replace("{%s}" % k, v)
    return text


def member_table(cls):
    return READ_ONLY if cls == "read-only" else WRITE


def member_text(cls, p):
    t = member_table(cls)
    return "\n".join(fill(t[0][0], p) if i == 0 else "- " + fill(row[0], p) for i, row in enumerate(t))


def probes(cls, p=None):
    """{"allowed": [...], "refused": [...]}: the commands the card of class cls stands on, paths filled in (the words CLONE, OUT, TMP, RUN without p)."""
    p = p or paths_of()
    rows = member_table(cls)
    return {"allowed": [fill(c, p) for r in rows for c in r[1]], "refused": [fill(c, p) for r in rows for c in r[2]]}


# ---------------------------------------------------------------------------------------------------------------------------- the lead card

def catalogue(root=None):
    import refusal
    return refusal.load(root or ROOT)["codes"]


def plan_areas():
    """The areas of lib/commands.py that have a verb with a --plan option, in the table's order: what the lead sees a plan and a token from."""
    import commands as C
    out = []
    for area, spec in C.COMMANDS.items():
        verbs = spec.get("verbs")
        if isinstance(verbs, dict):
            if any(o["flag"] == "--plan" for v in verbs.values() for o in v["opts"]):
                out.append(area)
        elif any(o["flag"] == "--plan" for o in spec.get("opts", ())):
            out.append(area)
    return out


TERMINAL = ("lead grant", "lead revoke", "release sign", "cloud login", "discover install")   # asked at a terminal: no session can answer for the person


def state_dir():
    import paths
    return paths.state()


def read_regular(path, limit=READ_MAX):
    """The text of the regular file at path, at most limit bytes of it; an OSError for anything else: a link (a link to /dev/zero would fill memory), a pipe or a
    device (a read would wait, the hook has two seconds), a directory, a file longer than limit. The file is opened without following a link and without
    waiting for a writer, and what it is is asked of the descriptor opened, not of the name."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0))
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > limit:
            raise OSError("not a regular file of at most %d bytes: %s" % (limit, path))
        data = b""
        while len(data) <= limit:
            chunk = os.read(fd, limit + 1 - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) > limit:
            raise OSError("longer than %d bytes: %s" % (limit, path))
        return data.decode("utf-8")
    finally:
        os.close(fd)


def stale_members(project, state=None):
    """(as_of, {member: [STALE | DRIFT]}) from the last `qargi agent list` of the project, or None: no stored reading, an unreadable one, or no member in a
    listed state. The file is data: a name or a state that is not of the form qargi writes is left out."""
    if not project:
        return None
    try:
        doc = json.loads(read_regular(os.path.join(state or state_dir(), "agent-states.json")))
        entry = doc["projects"][project]
        at, members = entry["at"], entry["members"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(at, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z", at) or not isinstance(members, dict):
        return None
    out = {}
    for name in sorted(members):
        st = members[name]
        if NAME_RE.fullmatch(name) and isinstance(st, list):
            hit = [s for s in STATES if s in st]
            if hit:
                out[name] = hit
    return (at, out) if out else None


def lead_lines(root=None, project=None, state=None):
    codes = catalogue(root)
    live = lambda c: codes.get(c, {}).get("status") == "live"
    lines = ["Lead card, the rules that refuse late (qargi role card lead):"]
    lines.append("Verbs that take --plan, by area: %s (`qargi AREA` lists them). They print a plan and a token; apply with --plan TOKEN --approved \"the owner's words\". "
                 "A token dies when what it hashed changes, so run --dry-run, where the verb has one, just before asking." % ", ".join(plan_areas()))
    lines.append("Only at a terminal, the person's own: %s." % ", ".join("`qargi %s`" % t for t in TERMINAL))
    lines.append("Wait for a run with `qargi local list`, not a loop on process names.")
    lines.append("Commits made by hand on a release or hotfix branch: `qargi release fix VER --record` journals them, needs no approval and says whether they are inside "
                 "the cut; if not, push takes its own plan. A branch you deleted or rewrote by hand: `qargi ref record`. A branch you made: `qargi ref note`.")
    words = "--approved is the owner's own words, in this session, for this plan. qargi cannot tell relayed words apart: the rule is yours to keep."
    if live("approval-refused"):
        words += " On a seated project it is refused outside qargi host (approval-refused): %s." % codes["approval-refused"]["next"]["lead"]
    lines.append(words)
    if live("member-sandbox-off"):
        lines.append("Dispatch refused with member-sandbox-off: %s." % codes["member-sandbox-off"]["next"]["lead"])
    return lines


def tail_line(stale, shown):
    at, members = stale
    names = ["%s (%s)" % (n, ", ".join(s)) for n, s in members.items()]
    more = len(names) - shown
    return "Members STALE or DRIFT as of %s: %s%s; `qargi agent list` names the fix." % (at, ", ".join(names[:shown]), (" and %d more" if shown else "%d members") % more if more > 0 else "")


def lead_text(root=None, project=None, state=None):
    """(the lead card, the stored reading it tells of or None). The tail names up to SHOWN members and counts the rest; when the card would pass
    LEAD_CHARS it names fewer, and at last none: the card is never cut in the middle of a line."""
    lines = lead_lines(root, project, state)
    stale = stale_members(project, state)
    head = "\n".join(lines[:1] + ["- " + x for x in lines[1:]])
    if not stale:
        return head, None
    for shown in range(min(SHOWN, len(stale[1])), -1, -1):
        text = head + "\n- " + tail_line(stale, shown)
        if len(text) <= LEAD_CHARS:
            return text, stale
    return head, None


# ---------------------------------------------------------------------------------------------------------------------------- the card

def words(text):
    return len(text.split())


def role_class(role):
    if role == "lead":
        return "lead"
    import role as R
    if R.role_dir(role) is None:
        raise Exit(1, "qargi: no role named %s (qargi role list)\n" % role)
    return "read-only" if R.role_class(role) == "read-only" else "write"


def card(role, project=None, run=None, root=None, state=None):
    """{role, class, card, words, chars, project, run, members_stale}: the card of a role."""
    cls = role_class(role)
    stale = None
    if cls == "lead":
        text, stale = lead_text(root, project, state)
    else:
        text = member_text(cls, paths_of(run))
    return {"role": role, "class": cls, "card": text, "words": words(text), "chars": len(text), "project": project, "run": os.path.abspath(run) if run else None,
            "members_stale": {"as_of": stale[0], "members": stale[1]} if stale else None}


def main(argv):
    args = list(argv)
    if not args or args[0] != "card":
        raise Exit(2, "qargi: %s\n" % USAGE)
    args.pop(0)
    role = project = run = None
    as_json = False
    while args:
        a = args.pop(0)
        if a in ("--project", "--run"):
            if not args:
                raise Exit(2, "qargi: %s needs a value\n" % a)
            if a == "--project":
                project = args.pop(0)
            else:
                run = args.pop(0)
        elif a == "--json":
            as_json = True
        elif a.startswith("-"):
            raise Exit(2, "qargi: unknown option %s\n%s\n" % (a, USAGE))
        elif role is None:
            role = a
        else:
            raise Exit(2, "qargi: unexpected argument %s\n%s\n" % (a, USAGE))
    if role is None:
        raise Exit(2, "qargi: %s\n" % USAGE)
    out = card(role, project, run)
    sys.stdout.write(json.dumps(out) + "\n" if as_json else out["card"] + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except Exit as e:
        sys.stderr.write(e.message)
        sys.exit(e.code)
