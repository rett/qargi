#!/usr/bin/env python3
"""Link a project's repository to the render of its packs for the project's provider.

`qargi packs apply --target T PROJECT` renders the project's skills under <state>/PROVIDER/PROJECT/<skills dir>, where T is the
render target and <skills dir> the project skills directory of the provider's layout (lib/providers/NAME.json, read through
lib/provider.py; nothing here names a provider). Loading them needed the provider's launch command. `packs link` instead makes
CHECKOUT/<skills dir> a symbolic link to that directory, so a session opened in the checkout loads the packs by itself;
`packs unlink` undoes it.

Called by packs.sh, which holds the project's lock and gathers the facts only the shell knows into an inputs file:
  {project, provider, state, checkout, kids:[{name, hash, lib}]}
where kids are the skill directories of a real CHECKOUT/<skills dir> (hash: their content hash; lib: the content hash of
the library pack of that name, or null). A provider without a project skills directory, or without verified skills support,
is refused with exit status 3.

  packs_link.py plan  link|unlink INPUTS TOKENFILE   print the plan and write the plan token (none when there is nothing to do)
  packs_link.py apply link|unlink INPUTS TOKEN       re-plan, refuse if the plan changed, then change the file system

The only paths written are the directories above the link inside the checkout (when missing), the link itself and the backup
of a real directory, beside it (<skills dir>.qargi-backup).
Nothing is ever deleted except the symbolic link this tool made.
"""
import hashlib
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import provider  # noqa: E402

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
BACKUP_SUFFIX = ".qargi-backup"


def die(msg):
    print("qargi: " + msg, file=sys.stderr)
    sys.exit(1)


def git(base, *args):
    """(exit status, stdout) of a git command in base, with no repository override from the environment."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", base] + list(args), capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, env=env)
    return r.returncode, r.stdout


def linked(path, render):
    """True when path is a symbolic link that resolves to the render directory."""
    return os.path.islink(path) and os.path.realpath(path) == os.path.realpath(render)


def skills_dir(inp):
    """The project skills directory of the project's provider (relative to a checkout or a render), or exit 3."""
    provider.require_skills(inp["provider"], "link the checkout's skills directory to the render")
    return provider.require(inp["provider"], "project_skills_dir", "link the checkout's skills directory to the render")


def render_path(inp):
    project = inp["project"]
    if not NAME_RE.match(project) or ".." in project:
        die("not a project name: " + project)
    return os.path.join(os.path.abspath(inp["state"]), inp["provider"], project, skills_dir(inp))


def render_ready(inp, render):
    """Refuse a render that is missing or reached through a symbolic link inside the state directory."""
    p = os.path.abspath(inp["state"])
    for part in [inp["provider"], inp["project"]] + skills_dir(inp).split("/"):
        p = os.path.join(p, part)
        if os.path.islink(p):
            die("%s is a symbolic link; refusing" % p)
    if not os.path.isdir(render):
        target = provider.layout(inp["provider"])["render_target"]
        how = "run qargi packs apply --target %s %s first" % (target, inp["project"]) if target else "qargi does not make one for this provider"
        die("there is no render of %s yet: %s" % (inp["project"], how))


def locate(inp):
    """(checkout realpath, skills path, backup path) of a checkout that is the top of a git work tree."""
    co = inp.get("checkout") or ""
    if not co:
        die("project %s has no checkout (repo.path is empty): qargi project set %s repo.path DIR" % (inp["project"], inp["project"]))
    if not os.path.isabs(co) or not os.path.isdir(co):
        die("the checkout %s of project %s is not a directory" % (co, inp["project"]))
    base = os.path.realpath(co)
    rc, top = git(base, "rev-parse", "--show-toplevel")
    if rc != 0 or os.path.realpath(top.strip()) != base:
        die("%s is not the top of a git work tree; refusing" % co)
    parts = skills_dir(inp).split("/")
    cdir = base
    for part in parts[:-1]:
        cdir = os.path.join(cdir, part)
        if os.path.islink(cdir):
            die("%s is a symbolic link; refusing (the link would be created outside the checkout's own files)" % cdir)
        if os.path.lexists(cdir) and not os.path.isdir(cdir):
            die("%s exists and is not a directory; refusing" % cdir)
    link = os.path.join(cdir, parts[-1])
    return base, link, link + BACKUP_SUFFIX


def tracked(base, rel):
    rc, out = git(base, "ls-files", "--", rel)
    return rc == 0 and out.strip() != ""


def exclude_hint(base, rel):
    """A line telling the owner to ignore the skills directory, or None when git already ignores it. Nothing is edited."""
    rc, _ = git(base, "check-ignore", "-q", "--", rel)
    if rc == 0:
        return None
    rc, path = git(base, "rev-parse", "--git-path", "info/exclude")
    path = path.strip() if rc == 0 and path.strip() else ".git/info/exclude"
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return "warning: git does not ignore %s, so the link shows up as untracked; to keep it out of git status add this line to %s:\n    %s" % (rel, path, rel)


def classify(verb, inp):
    """The facts of the plan (a JSON-able dict) for verb link|unlink; refuses what must not be touched."""
    render = render_path(inp)
    base, link, backup = locate(inp)
    rel = skills_dir(inp)
    facts = {"verb": verb, "project": inp["project"], "checkout": base, "link": link, "render": render, "backup": backup, "rel": rel, "kids": []}
    present = os.path.lexists(link)
    if verb == "link":
        render_ready(inp, render)
        if present and os.path.islink(link):
            if linked(link, render):
                facts["kind"] = "linked"
                return facts
            die("%s is a symbolic link to %s, not to this project's render; refusing to replace it" % (link, os.readlink(link)))
        if tracked(base, rel):
            die("files under %s are tracked by git in %s: the repository's owner decides how its skills are loaded; "
                "qargi does not touch tracked files" % (rel, base))
        if os.path.lexists(backup):
            die("%s already exists; move it away first (qargi never overwrites or deletes a backup)" % backup)
        if not present:
            facts["kind"] = "absent"
        elif os.path.isdir(link):
            facts["kind"] = "dir"
            facts["others"] = sorted(n for n in os.listdir(link) if n not in {k["name"] for k in inp.get("kids", [])})
            for k in sorted(inp.get("kids", []), key=lambda k: k["name"]):
                if k.get("lib") is None:
                    st = "new"
                elif k.get("hash") == k["lib"]:
                    st = "same"
                else:
                    st = "differs"
                facts["kids"].append([k["name"], st])
        else:
            die("%s exists and is not a directory or a symbolic link; refusing" % link)
        return facts
    # unlink
    if present and os.path.islink(link):
        if not linked(link, render):
            die("%s is a symbolic link to %s, not to this project's render; refusing to remove it" % (link, os.readlink(link)))
        facts["kind"] = "ours"
        facts["restore"] = os.path.lexists(backup)
        return facts
    if present:
        die("%s is not a symbolic link (a real %s has taken its place); refusing to touch it" % (link, rel))
    if os.path.lexists(backup):
        die("%s exists but %s is not a symbolic link of this project's render; refusing to move it" % (backup, link))
    die("%s is not linked to the render of %s; nothing to unlink" % (link, inp["project"]))


def token_of(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:12]


def show_plan(facts):
    p, link, render, backup, rel = facts["project"], facts["link"], facts["render"], facts["backup"], facts["rel"]
    if facts["verb"] == "link":
        print("link plan for %s: the checkout %s loads the project's packs from the render" % (p, facts["checkout"]))
        print("  link:   %s" % link)
        print("  target: %s" % render)
        if facts["kind"] == "absent":
            print("  %s does not exist: create %s (if missing) and the symbolic link" % (rel, os.path.dirname(link)))
        else:
            print("  %s is a real directory with %d skill%s; nothing in it is tracked by git" % (rel, len(facts["kids"]), "" if len(facts["kids"]) == 1 else "s"))
            how = {"same": "the library has a pack of this name with identical content",
                   "differs": "a library pack of this name has other content; the render will shadow it",
                   "new": "not in the library"}
            for name, st in facts["kids"]:
                print("    %-8s %s  (%s)" % (st, name, how[st]))
                if st == "new":
                    print("             to keep it: qargi skill import %s" % os.path.join(link, name))
                    print("                         qargi skill link %s --scope project --project %s" % (name, p))
            if facts.get("others"):
                print("    other entries moved with it: %s" % ", ".join(facts["others"]))
            print("  apply moves the directory to %s (nothing is deleted) and creates the link." % backup)
            print("  Skills that are not imported and linked stop loading in the checkout until they are; they stay in the backup.")
        print("  undo: qargi packs unlink %s" % p)
    else:
        print("unlink plan for %s: remove the symbolic link %s (it points to %s)" % (p, link, render))
        if facts["restore"]:
            print("  and move %s back to %s" % (backup, link))
        else:
            print("  there is no backup, so %s will not exist afterwards" % rel)
    hint = exclude_hint(facts["checkout"], rel) if facts["verb"] == "link" else None
    if hint:
        print(hint)


def cmd_plan(verb, inp, tokenfile):
    facts = classify(verb, inp)
    if facts["kind"] == "linked":
        print("already linked: %s -> %s" % (facts["link"], facts["render"]))
        return
    show_plan(facts)
    with open(tokenfile, "w") as fh:
        fh.write(token_of(facts))


def cmd_apply(verb, inp, token):
    facts = classify(verb, inp)
    if facts["kind"] == "linked" or token_of(facts) != token:
        die("the plan changed since it was approved; nothing was changed")
    link, render, backup = facts["link"], facts["render"], facts["backup"]
    if verb == "link":
        moved = False
        if facts["kind"] == "dir":
            os.rename(link, backup)
            moved = True
        else:
            os.makedirs(os.path.dirname(link), exist_ok=True)
        try:
            os.symlink(render, link)
        except OSError as e:
            if moved:
                os.rename(backup, link)
            die("cannot create the link %s: %s; nothing was changed" % (link, e.strerror or e))
        print("linked: %s -> %s" % (link, render))
        if moved:
            print("backup: %s (the former %s; qargi packs unlink %s moves it back)" % (backup, facts["rel"], facts["project"]))
        hint = exclude_hint(facts["checkout"], facts["rel"])
        if hint:
            print(hint)
        return
    os.unlink(link)
    if facts["restore"]:
        os.rename(backup, link)
        print("unlinked: %s restored from %s" % (link, backup))
    else:
        print("unlinked: %s removed" % link)


def main():
    if len(sys.argv) < 5 or sys.argv[1] not in ("plan", "apply") or sys.argv[2] not in ("link", "unlink"):
        die("usage: packs_link.py plan|apply link|unlink INPUTS TOKENFILE|TOKEN")
    try:
        with open(sys.argv[3]) as fh:
            inp = json.load(fh)
        (cmd_plan if sys.argv[1] == "plan" else cmd_apply)(sys.argv[2], inp, sys.argv[4])
    except provider.Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        sys.exit(3)
    except provider.ProviderError as e:
        die(str(e))
    except OSError as e:
        die("%s: %s" % (e.filename or "file system error", e.strerror or e))


if __name__ == "__main__":
    main()
