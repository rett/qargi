#!/usr/bin/env python3
"""The documentation site of a release (the part of `qargi release site`, `release status` and `release finish` that is not shell).

Answers, under `site` in the project's answers file (all optional; nothing happens while site.enabled is not true):
  site.enabled   true: the project regenerates its site when a release ships (release finish ends with the next step, release status
                 has a site line, release site builds it)
  site.branch    the detached branch that holds the hand pages and the built site (it must be in repo.detached); default gh-pages
                 when repo.detached lists it
  site.config    the site.json on that branch, relative to the branch's root (default site/site.json); the hand pages are the
                 folder pages/ beside it

  release_site.py problems AF                print the problems of the `site` answers; exit 1 if there are any
  release_site.py config AF                  print "enabled<TAB>branch<TAB>config<TAB>pages"; exit 1 with the problems
  release_site.py lead-only                  exit 2 in a member run or when QARGI_NESTED is set
  release_site.py set-release FILE VERSION   set "release" in the site.json FILE to VERSION (rewritten only when it differs)
  release_site.py next AF METHODOLOGY VER    print "next: ..." for each after_release step of the methodology whose answer is true
"""
import json, os, re, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

SITE_KEYS = ("enabled", "branch", "config")
DEFAULT_BRANCH = "gh-pages"
DEFAULT_CONFIG = "site/site.json"
OUT_DIR = "_site"      # where the built site is written on the site branch
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def rel_ok(p):
    """A file name inside the branch: relative, normal, no control character, not an option, not a hidden or _site folder."""
    return (isinstance(p, str) and p != "" and not p.startswith(("/", "-", "~")) and not CTRL_RE.search(p)
            and os.path.normpath(p) == p and ".." not in p.split("/") and not any(x.startswith(".") for x in p.split("/"))
            and p.split("/")[0] != OUT_DIR)


def resolved(c):
    """(enabled, branch or None, config, pages) of the answers, the defaults filled in."""
    site = c.get("site") if isinstance(c, dict) else None
    site = site if isinstance(site, dict) else {}
    det = ((c.get("repo") or {}).get("detached") or []) if isinstance(c, dict) else []
    branch = site.get("branch")
    if branch is None and isinstance(det, list) and DEFAULT_BRANCH in det:
        branch = DEFAULT_BRANCH
    config = site.get("config", DEFAULT_CONFIG)
    pages = "/".join([x for x in [os.path.dirname(config) if isinstance(config, str) else ""] if x] + ["pages"])
    return site.get("enabled") is True, branch, config, pages


def problems(c):
    """The problems of the `site` answers of a whole answers object (a list; empty when there are none)."""
    if not isinstance(c, dict) or "site" not in c:
        return []
    site = c["site"]
    if not isinstance(site, dict):
        return ["site: an object like {enabled: true, branch: \"gh-pages\", config: \"site/site.json\"}"]
    out = []
    for k in site:
        if k not in SITE_KEYS:
            out.append("site.%s: unknown key (%s)" % (k, ", ".join(SITE_KEYS)))
    if "enabled" in site and not isinstance(site["enabled"], bool):
        out.append("site.enabled: true or false (true: the site is regenerated when a release ships, with qargi release site VERSION)")
    det = (c.get("repo") or {}).get("detached") or []
    det = det if isinstance(det, list) else []
    enabled, branch, config, _ = resolved(c)
    if "branch" in site and not (isinstance(branch, str) and branch in det):
        out.append("site.branch: one of the detached branches of repo.detached (%s): the branch of the hand pages and the built site"
                   % (", ".join(x for x in det if isinstance(x, str)) or "none yet"))
    elif enabled and branch is None:
        out.append("site.branch: name the site's branch (it must be in repo.detached); the default %s applies only when repo.detached lists it" % DEFAULT_BRANCH)
    if "config" in site and not (rel_ok(config) and config.endswith(".json")):
        out.append("site.config: the path of the site.json on the site branch, relative to its root (default %s; not hidden, not under %s/)" % (DEFAULT_CONFIG, OUT_DIR))
    return out


def load(af):
    with open(af) as f:
        return json.load(f)


def set_release(path, version):
    """Set "release" in the site.json at path; the file is rewritten only when the value differs. Returns True when it changed."""
    if not VERSION_RE.match(version):
        raise ValueError("%r is not a version like 0.1.1" % version)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("%s: not a JSON object" % path)
    if data.get("release") == version:
        return False
    data["release"] = version
    with open(path, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    return True


def answer(c, dotted):
    """The value at a dotted path of the answers, None when absent."""
    v = c
    for k in dotted.split("."):
        if not isinstance(v, dict) or k not in v:
            return None
        v = v[k]
    return v


def next_steps(c, steps, version):
    """The lines of the after_release steps whose `when` answer is true, {version} replaced."""
    out = []
    for s in steps or []:
        if isinstance(s, dict) and isinstance(s.get("when"), str) and answer(c, s["when"]) is True and isinstance(s.get("next"), str):
            out.append("next: " + s["next"].replace("{version}", version))
    return out


def main(argv):
    cmd, rest = (argv[0] if argv else ""), argv[1:]
    if cmd == "problems" and len(rest) == 1:
        bad = problems(load(rest[0]))
        for b in bad:
            print(b)
        return 1 if bad else 0
    if cmd == "config" and len(rest) == 1:
        c = load(rest[0])
        bad = problems(c)
        if bad:
            print("qargi: the site answers are not valid: " + "; ".join(bad), file=sys.stderr)
            return 1
        enabled, branch, config, pages = resolved(c)
        print("\t".join([("true" if enabled else "false"), branch or "", config, pages]))
        return 0
    if cmd == "lead-only" and not rest:
        import marshal_refs
        if os.environ.get("QARGI_NESTED") or marshal_refs.in_member_run():
            print("qargi: release site is not available in a member run or a nested call: it writes a commit on the lead's site branch", file=sys.stderr)
            return 2
        return 0
    if cmd == "set-release" and len(rest) == 2:
        try:
            set_release(rest[0], rest[1])
        except (OSError, ValueError) as e:
            print("qargi: the site configuration %s cannot take the release: %s" % (rest[0], e), file=sys.stderr)
            return 1
        return 0
    if cmd == "next" and len(rest) == 3:
        import methodology as M
        try:
            steps = M.load(rest[1])[2].get("after_release") or []
        except SystemExit:
            return 0
        for line in next_steps(load(rest[0]), steps, rest[2]):
            print(line)
        return 0
    print("qargi: usage: release_site.py problems AF | config AF | lead-only | set-release FILE VERSION | next AF METHODOLOGY VERSION", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
