#!/usr/bin/env python3
"""How a project lays out what a release updates (the part of `qargi release` that tolerates other layouts than qargi's own).

Answers, under `release` in the project's answers file (every one optional; the defaults are the Keep a Changelog layout with a VERSION file):
  release.version_file         the file that holds only the version, relative to the repository (default VERSION); `none`: the project has
                               no such file, and the version is read from the changelog heading and the tag only
  release.changelog.unreleased the heading of the section of the changes to come (default "## [Unreleased]"). It may carry the version:
                               "## {version} (unreleased)" is then renamed by the release, not kept
  release.changelog.released   the heading of a released section (default "## [{version}] - {date}"); {version} is required, {date} is optional
  release.changelog.numbered   true when the items under the unreleased heading are numbered ("12. text" or "- 12. text"; default false): feature sync and
                               feature finish then check them for duplicates (lib/changelog_numbers.py, qargi changelog renumber)
  release.version_files        other files that carry the version (a list of paths relative to the repository; default none): `release start` lists the
                               ones that do not yet contain VERSION, `release status` and `release verify` show the same check on the release branch
  release.man_pages            the manual pages whose .TH date and version the release sets (default: the man/*.1 files of the repository)
  release.test_command         the command of `release verify` (a command line, or a list of words; default: the answer test_command)
  release.preflight            a command as a list of words, {version} replaced, run by `release start` and `release push` before they change
                               anything; a non-zero exit refuses

  release_layout.py problems REL_JSON                  the problems of those answers (a JSON object on the command line); one per line
  release_layout.py changelog FILE VER DATE ALLOW AF   check and rewrite the changelog for a release; exit 1 with the reason
  release_layout.py manpage FILE NAME VER DATE OLD     set the .TH date and version of a manual page; exit 1 with the reason
  release_layout.py th-empty FILE...                   print each manual page whose .TH line has no date or no version (exit 1 if any)
  release_layout.py has-section FILE VER AF            exit 0 when the changelog has a released section for VER
  release_layout.py has-version FILE|- VER             exit 0 when FILE (or stdin) contains VER as a whole version (0.2.1 is not found in 0.2.10 or 10.2.1)
"""
import json
import os
import re
import sys

DEFAULT_UNRELEASED = "## [Unreleased]"
DEFAULT_RELEASED = "## [{version}] - {date}"
LAYOUT_KEYS = ("version_file", "version_files", "changelog", "man_pages", "test_command", "preflight")
CHANGELOG_KEYS = ("unreleased", "released", "numbered")
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")


def rel_name_ok(p):
    """A file name inside the repository: relative, normal, no control character, no #, not an option."""
    return (isinstance(p, str) and p != "" and not p.startswith(("/", "-", "~")) and not CTRL_RE.search(p) and "#" not in p
            and os.path.normpath(p) == p and not p.startswith("../") and p != "..")


def template_problem(name, t, allowed, example, required=()):
    """Why a heading template is not usable (None when it is): one line, a heading, only the placeholders allowed."""
    if not isinstance(t, str) or not t.strip() or CTRL_RE.search(t) or not re.match(r"#{1,6} \S", t):
        return "%s: one heading line such as \"%s\" (it starts with # and a space)" % (name, example)
    names = PLACEHOLDER_RE.findall(t)
    stripped = PLACEHOLDER_RE.sub("", t)
    if "{" in stripped or "}" in stripped or any(n not in allowed for n in names):
        return "%s: the only placeholders are %s, written {version} and {date} (no other braces)" % (name, " and ".join("{%s}" % a for a in allowed))
    for r in required:
        if "{%s}" % r not in t:
            return "%s: must contain {%s}" % (name, r)
    return None


def problems(rel):
    """The problems of the layout answers of the `release` object (a list; empty when there are none). Unknown keys are the caller's concern."""
    out = []
    if not isinstance(rel, dict):
        return out
    if "version_file" in rel:
        v = rel["version_file"]
        if not (v == "none" or rel_name_ok(v)):
            out.append("release.version_file: a file name relative to the repository (default VERSION), or none when the project has no such file")
    if "version_files" in rel:
        v = rel["version_files"]
        if not (isinstance(v, list) and all(rel_name_ok(x) for x in v) and len(set(v)) == len(v)):
            out.append("release.version_files: a list of distinct files relative to the repository that carry the version (no .., no #, not starting with - or /)")
    if "changelog" in rel:
        c = rel["changelog"]
        if not isinstance(c, dict):
            out.append("release.changelog: an object like {unreleased, released}")
        else:
            for k in c:
                if k not in CHANGELOG_KEYS:
                    out.append("release.changelog.%s: unknown key (%s)" % (k, ", ".join(CHANGELOG_KEYS)))
            if "unreleased" in c:
                p = template_problem("release.changelog.unreleased", c["unreleased"], ("version",), DEFAULT_UNRELEASED)
                if p:
                    out.append(p)
            if "numbered" in c and not isinstance(c["numbered"], bool):
                out.append("release.changelog.numbered: true or false (true: the items under the unreleased heading are numbered; see qargi changelog)")
            if "released" in c:
                p = template_problem("release.changelog.released", c["released"], ("version", "date"), DEFAULT_RELEASED, ("version",))
                if p:
                    out.append(p)
    if "man_pages" in rel:
        m = rel["man_pages"]
        if not (isinstance(m, list) and all(rel_name_ok(x) for x in m) and len(set(m)) == len(m)):
            out.append("release.man_pages: a list of distinct manual page files relative to the repository (no .., no #, not starting with - or /)")
    if "test_command" in rel:
        t = rel["test_command"]
        if not ((isinstance(t, str) and t.strip() and "\n" not in t and "\r" not in t and "\x00" not in t)
                or (isinstance(t, list) and t and all(isinstance(x, str) and x and "\x00" not in x for x in t))):
            out.append("release.test_command: one command line, or a command as a list of words (for example [\"make\", \"check\"])")
    if "preflight" in rel:
        p = rel["preflight"]
        if not (isinstance(p, list) and p and all(isinstance(x, str) and x and "\x00" not in x for x in p)):
            out.append("release.preflight: a command as a list of words, run without a shell, {version} replaced (for example [\"make\", \"check-release\", \"{version}\"])")
    return out


def load_release(af):
    try:
        with open(af, encoding="utf-8") as f:
            r = (json.load(f) or {}).get("release")
    except (OSError, ValueError):
        return {}
    return r if isinstance(r, dict) else {}


def templates(rel):
    """(unreleased, released) heading templates of the `release` object, the defaults where the answers name none."""
    c = (rel or {}).get("changelog")
    c = c if isinstance(c, dict) else {}
    return c.get("unreleased") or DEFAULT_UNRELEASED, c.get("released") or DEFAULT_RELEASED


def heading_re(template, version=None, date=None):
    """A regular expression for a heading line that follows the template: the literal text as written, {version} the given version (any
    version when None), {date} the given date (a date-like word when None). It matches from the start of a line; what follows is free."""
    parts = []
    for i, piece in enumerate(PLACEHOLDER_RE.split(template)):
        if i % 2 == 0:
            parts.append(re.escape(piece))
        elif piece == "version":
            parts.append(re.escape(version) + r"(?![0-9A-Za-z]|\.[0-9])" if version else r"\S+?")
        else:
            parts.append(re.escape(date) if date else r"[0-9][^\s\]\)]*")
    return "".join(parts)


def level(template):
    return len(re.match(r"#+", template).group(0))


def find_unreleased(text, template):
    """The match of the unreleased heading line, or None. The default heading is found as it was written; a custom one case-insensitively."""
    flags = re.M if template == DEFAULT_UNRELEASED else re.M | re.I
    return re.search(r"^" + heading_re(template) + r"[^\n]*(?:\n|\Z)", text, flags)


def section_end(rest, lvl):
    """The index in rest of the next heading of the level of the unreleased heading or above, or the end."""
    n = re.search(r"^#{1,%d} " % lvl, rest, re.M)
    return n.start() if n else len(rest)


def cmd_changelog(argv):
    path, ver, date, allow, af = argv[:5]
    unrel, rel = templates(load_release(af))
    t = open(path, encoding="utf-8").read()
    m = find_unreleased(t, unrel)
    if not m:
        sys.exit("qargi: %s has no '%s' section to release. Fix: add one with the changes of this release, then start again."
                 % (os.path.basename(path), unrel))
    body = t[m.end():][:section_end(t[m.end():], level(unrel))]
    if not allow and not [l for l in body.split("\n") if l.strip() and not l.startswith("#")]:
        sys.exit("qargi: %s has nothing under '%s'. Fix: record the changes of this release there (or pass --allow-empty-notes to release without notes), then start again."
                 % (os.path.basename(path), unrel))
    released = rel.replace("{version}", ver).replace("{date}", date)
    head = m.group(0).rstrip("\n")
    if "{version}" in unrel:        # the unreleased heading carries the version: it is renamed, nothing is kept
        new = t[:m.start()] + released + ("\n" if m.group(0).endswith("\n") else "") + t[m.end():]
    else:
        new = t[:m.start()] + head + "\n\n" + released + ("\n" if m.group(0).endswith("\n") else "") + t[m.end():]
    open(path, "w", encoding="utf-8").write(new)
    return 0


def cmd_has_section(argv):
    path, ver, af = argv[:3]
    _, rel = templates(load_release(af))
    t = open(path, encoding="utf-8").read()
    return 0 if re.search(r"^" + heading_re(rel, ver), t, re.M) else 1


def has_version(text, ver):
    """True when text holds ver as a whole version: not inside a longer number (0.2.1 is not in 0.2.10, 10.2.1 or 0.2.1.4)."""
    return re.search(r"(?<![0-9])(?<![0-9]\.)" + re.escape(ver) + r"(?![0-9]|\.[0-9])", text) is not None


def cmd_has_version(argv):
    path, ver = argv[:2]
    try:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return 1
    return 0 if has_version(text, ver) else 1


def refuse(name, why):
    sys.exit("qargi: %s: %s. Fix: make its .TH line read .TH NAME SECTION \"DATE\" \"NAME VERSION\", then start the release again." % (name, why))


def cmd_manpage(argv):
    path, name, ver, date, old = argv[:5]
    lines = open(path, encoding="utf-8").read().split("\n")
    for i, l in enumerate(lines):
        if l.startswith(".TH ") or l == ".TH":
            break
    else:
        refuse(name, "it has no .TH line, so the release cannot set its date and version")
    tok = re.findall(r'"[^"]*"|\S+', lines[i])
    if len(tok) < 5:
        refuse(name, "its .TH line has no date and source (version) fields, so the bump cannot update them")
    src = tok[4].strip('"')
    if old and old in src:
        src = src.replace(old, ver)
    else:
        m = list(re.finditer(r"\d+\.\d+\.\d+[\w.+-]*", src))
        if not m:
            refuse(name, "the source field of its .TH line (%s) carries no version, so the bump cannot update it" % tok[4])
        src = src[:m[-1].start()] + ver + src[m[-1].end():]
    tok[3] = '"%s"' % date
    tok[4] = '"%s"' % src
    lines[i] = " ".join(tok)
    open(path, "w", encoding="utf-8").write("\n".join(lines))
    if date_of(lines[i]) != date or ver not in src:     # whatever the line looked like, a page that leaves here carries both
        refuse(name, "its date or version could not be set")
    return 0


def date_of(th_line):
    tok = re.findall(r'"[^"]*"|\S+', th_line)
    return tok[3].strip('"') if len(tok) > 3 else ""


def cmd_th_empty(argv):
    bad = 0
    for p in argv:
        try:
            txt = open(p, encoding="utf-8").read()
        except OSError:
            continue
        th = next((l for l in txt.split("\n") if l.startswith(".TH ")), None)
        if th is None:
            continue
        tok = re.findall(r'"[^"]*"|\S+', th)
        if len(tok) < 5 or not tok[3].strip('"').strip() or not tok[4].strip('"').strip():
            print(p)
            bad = 1
    return bad


def main(argv):
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    cmd, rest = argv[0], argv[1:]
    if cmd == "problems" and len(rest) == 1:
        try:
            rel = json.loads(rest[0])
        except ValueError:
            return 2
        found = problems(rel)
        print("\n".join(found))
        return 1 if found else 0
    if cmd == "changelog" and len(rest) == 5:
        return cmd_changelog(rest)
    if cmd == "manpage" and len(rest) == 5:
        return cmd_manpage(rest)
    if cmd == "th-empty":
        return cmd_th_empty(rest)
    if cmd == "has-section" and len(rest) == 3:
        return cmd_has_section(rest)
    if cmd == "has-version" and len(rest) == 2:
        return cmd_has_version(rest)
    print("qargi: release_layout.py: unknown command or wrong arguments: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
