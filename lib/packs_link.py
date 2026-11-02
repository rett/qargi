#!/usr/bin/env python3
"""Link a project's repository to the render of its packs for the project's provider.

`qargi packs apply --target T PROJECT` renders the project's skills under <state>/PROVIDER/PROJECT/<skills dir>, where T is the
render target and <skills dir> the project skills directory of the provider's layout (lib/providers/NAME.json, read through
lib/provider.py; nothing here names a provider). Loading them needed the provider's launch command. `packs link` instead makes
CHECKOUT/<skills dir> a symbolic link to that directory, so a session opened in the checkout loads the packs by itself;
`packs unlink` undoes it.

Called by packs.sh, which holds the project's lock and gathers the facts only the shell knows into an inputs file:
  {project, provider, state, checkout, kids:[{name, in_library}]}
where kids are the skill directories of a real CHECKOUT/<skills dir> and in_library says whether the library has a pack of that
name. The content of a kid and of its library pack is compared here with packs_audit.strict_hash (symbolic links, the executable
bit, empty directories and nested .pack.json files count; the library pack's own top-level record does not). A provider without a project skills directory, or without verified skills support,
is refused with exit status 3.

  packs_link.py plan  link|unlink INPUTS TOKENFILE   print the plan and write the plan token (none when there is nothing to do)
  packs_link.py apply link|unlink INPUTS TOKEN       re-plan, refuse if the plan changed, then change the file system

A member's run (a directory `qargi local prepare` made, at or above the working directory) never applies: only the lead's session
changes what a checkout loads. The state directory comes from the environment (paths.state(), as the shell's DA_STATE) and the
checkout and provider must be the ones in the project's stored answers (paths.conf()); the inputs file cannot name others.

The only paths written are the directories above the link inside the checkout (when missing), the link itself, the backup
of a real directory, beside it (<skills dir>.qargi-backup), and a temporary symbolic link beside the link (.qargi-link.PID or
.qargi-unlink.PID) that is renamed into place or removed. Nothing is ever deleted except a symbolic link this tool made.

Apply works through a file descriptor of the link's parent directory (opened from the checkout one component at a time, never through
a symbolic link) and renames and links relative to it, so a directory swapped for a symbolic link after the plan cannot redirect it.
It never overwrites: a rename that must not replace anything uses renameat2(RENAME_NOREPLACE) where the kernel has it, and otherwise a
check just before the rename (a window remains there only on a file system without the flag). It re-reads the link right before it
moves or removes it and refuses what is not a symbolic link to the render.

Crash safety. link: (1) make the link under a temporary name beside the path, (2) rename the real directory to the backup name, (3)
rename the temporary link onto the path. Only between (2) and (3) is there no skills directory, and the backup holds every skill; unlink
(4) renames the link to a temporary name, (5) renames the backup onto the path, (6) removes the temporary link. A failure anywhere puts
things back where it can and says exactly what state the checkout is in and what to do (never "nothing was changed" unless that is true).
If the backup exists and the link does not (a stop between (2) and (3)), `packs unlink` plans the move of the backup back.

Tests inject faults with QARGI_TEST_FAULT=NAME[,NAME] (after-tmp-link, after-backup, after-aside, rollback: a failing rollback) and
stop between the plan and the act with QARGI_TEST_HOLD=PATH (the script creates PATH.reached and waits for PATH.go); nothing else reads them.
"""
import ctypes
import errno
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import marshal_refs  # noqa: E402  (in_member_run)
import packs_audit  # noqa: E402  (strict_hash)
import paths  # noqa: E402
import provider  # noqa: E402

NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]*$')
BACKUP_SUFFIX = ".qargi-backup"
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")


def clean(s):
    """s without control characters: names and paths come from the repository and must not move the cursor, recolour or break a line."""
    return CTRL_RE.sub("", s) if isinstance(s, str) else str(s)


def say(text=""):
    """print text with the control characters removed from every line (the newlines between lines stay)."""
    print("\n".join(clean(line) for line in text.split("\n")))


def q(s):
    """A word safe to paste into a shell: control characters out, then quoted."""
    return shlex.quote(clean(s))


def die(msg):
    print("qargi: " + clean(msg), file=sys.stderr)
    sys.exit(1)


def bind(inp):
    """Make the inputs say what the environment and the stored answers say: the state directory is paths.state(), and the
    checkout and provider must be the project's own (an inputs file written by hand cannot point the link at another repository
    or render). Dies when they differ."""
    project = inp.get("project")
    if not isinstance(project, str) or not NAME_RE.fullmatch(project) or ".." in project:
        die("not a project name: %s" % (project,))
    answers = provider.project_answers(project, paths.conf())
    if answers is None:
        die("no stored answers for project '%s'" % project)
    co = (answers.get("repo") or {}).get("path") or ""
    if (inp.get("checkout") or "") != co:
        die("the inputs name the checkout %r, not the project's repo.path %r; refusing" % (inp.get("checkout"), co))
    if inp.get("provider") != provider.project_provider(answers, project):
        die("the inputs name the provider %r, not the project's; refusing" % (inp.get("provider"),))
    inp["state"] = paths.state()
    return inp


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
            die("%s already exists; %s (qargi never overwrites or deletes a backup)"
                % (backup, "qargi packs unlink %s moves it back to %s" % (inp["project"], link) if not present else "move it away first"))
        if not present:
            facts["kind"] = "absent"
        elif os.path.isdir(link):
            facts["kind"] = "dir"
            facts["others"] = sorted(n for n in os.listdir(link) if n not in {k["name"] for k in inp.get("kids", [])})
            for k in sorted(inp.get("kids", []), key=lambda k: k["name"]):
                lib = packs_audit.library_hash(k["name"]) if k.get("in_library") and NAME_RE.fullmatch(k["name"]) else None
                if lib is None:
                    st = "new"
                else:
                    mine = packs_audit.strict_hash(os.path.join(link, k["name"]))
                    st = "same" if mine and mine == lib else "differs"
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
        if os.path.isdir(backup) and not os.path.islink(backup):
            facts["kind"] = "backup"     # a link that stopped half way: the link is gone, the skills are in the backup
            facts["restore"] = True
            return facts
        die("%s exists and is not a directory; refusing to move it to %s" % (backup, link))
    die("%s is not linked to the render of %s; nothing to unlink" % (link, inp["project"]))


def token_of(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:12]


def show_plan(facts):
    p, link, render, backup, rel = (clean(facts[k]) for k in ("project", "link", "render", "backup", "rel"))
    if facts["verb"] == "link":
        say("link plan for %s: the checkout %s loads the project's packs from the render" % (p, clean(facts["checkout"])))
        say("  link:   %s" % link)
        say("  target: %s" % render)
        if facts["kind"] == "absent":
            say("  %s does not exist: create %s (if missing) and the symbolic link" % (rel, os.path.dirname(link)))
        else:
            say("  %s is a real directory with %d skill%s; nothing in it is tracked by git" % (rel, len(facts["kids"]), "" if len(facts["kids"]) == 1 else "s"))
            how = {"same": "the library has a pack of this name with identical content",
                   "differs": "a library pack of this name has other content; the render will shadow it",
                   "new": "not in the library"}
            for name, st in facts["kids"]:
                say("    %-8s %s  (%s)" % (st, clean(name), how[st]))
                if st == "new" and not NAME_RE.fullmatch(name):
                    say("             skipped: unusual name (no offer is printed for it)")
                elif st == "new":
                    say("             to keep it: qargi skill import %s" % q(os.path.join(link, name)))
                    say("                         qargi skill link %s --scope project --project %s" % (q(name), q(p)))
            if facts.get("others"):
                say("    other entries moved with it: %s" % ", ".join(clean(o) for o in facts["others"]))
            say("  apply moves the directory to %s (nothing is deleted) and creates the link." % backup)
            say("  Skills that are not imported and linked stop loading in the checkout until they are; they stay in the backup.")
        say("  undo: qargi packs unlink %s" % q(p))
    elif facts["kind"] == "backup":
        say("unlink plan for %s: %s is not linked, but the backup %s exists (a link stopped half way, or the link was removed by hand)" % (p, link, backup))
        say("  move %s back to %s; there is no link to remove" % (backup, link))
    else:
        say("unlink plan for %s: remove the symbolic link %s (it points to %s)" % (p, link, render))
        if facts["restore"]:
            say("  and move %s back to %s" % (backup, link))
        else:
            say("  there is no backup, so %s will not exist afterwards" % rel)
    hint = exclude_hint(facts["checkout"], rel) if facts["verb"] == "link" else None
    if hint:
        say(hint)


def cmd_plan(verb, inp, tokenfile):
    facts = classify(verb, inp)
    if facts["kind"] == "linked":
        say("already linked: %s -> %s" % (clean(facts["link"]), clean(facts["render"])))
        return
    show_plan(facts)
    with open(tokenfile, "w") as fh:
        fh.write(token_of(facts))


class Refused(Exception):
    """The checkout is no longer what the plan saw: nothing is changed (or what was is put back first)."""


def fault(name):
    """Tests only: QARGI_TEST_FAULT=NAME[,NAME] makes the step called NAME fail."""
    if name in os.environ.get("QARGI_TEST_FAULT", "").split(","):
        raise OSError(errno.EIO, "injected fault " + name)


def hold():
    """Tests only: with QARGI_TEST_HOLD=PATH, say PATH.reached and wait (30 s at most) for PATH.go, so a test can change the checkout
    between the plan and the act."""
    path = os.environ.get("QARGI_TEST_HOLD")
    if not path:
        return
    open(path + ".reached", "w").close()
    end = time.time() + 30
    while not os.path.exists(path + ".go") and time.time() < end:
        time.sleep(0.05)


def renameat2(pfd, old, new, flags):
    """True when libc's renameat2 did it, None when it is not available here (no libc function, no kernel or file system support)."""
    try:
        fn = ctypes.CDLL(None, use_errno=True).renameat2
    except (OSError, AttributeError):
        return None
    if fn(pfd, os.fsencode(old), pfd, os.fsencode(new), flags) == 0:
        return True
    e = ctypes.get_errno()
    if e in (errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP):
        return None
    raise OSError(e, os.strerror(e), new)


def rename_new(pfd, old, new):
    """Rename old to new in the directory pfd; FileExistsError if new exists. RENAME_NOREPLACE (1) where there is one, else a check
    right before the rename."""
    if renameat2(pfd, old, new, 1):
        return
    try:
        os.lstat(new, dir_fd=pfd)
    except FileNotFoundError:
        os.rename(old, new, src_dir_fd=pfd, dst_dir_fd=pfd)
        return
    raise FileExistsError(errno.EEXIST, "File exists", new)


def open_parent(base, parts, create):
    """A directory descriptor of base/parts[0]/.../parts[-2], each component opened relative to the one before without following a
    symbolic link; missing ones are made when create. Refused (Refused) when a component is a link or not a directory."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(base, flags)
    try:
        walked = base
        for part in parts:
            walked = os.path.join(walked, part)
            try:
                nfd = os.open(part, flags, dir_fd=fd)
            except FileNotFoundError:
                if not create:
                    raise Refused("%s does not exist any more" % walked)
                os.mkdir(part, 0o777, dir_fd=fd)
                nfd = os.open(part, flags, dir_fd=fd)
            except OSError as e:
                if e.errno in (errno.ELOOP, errno.ENOTDIR):
                    raise Refused("%s is a symbolic link or not a directory now (it was neither when the plan was made)" % walked)
                raise
            os.close(fd)
            fd = nfd
    except BaseException:
        os.close(fd)
        raise
    return fd


def kind_of(pfd, name):
    """"absent", "link", "dir" or "other" for the entry name of the directory pfd (nothing followed)."""
    try:
        m = os.lstat(name, dir_fd=pfd).st_mode
    except FileNotFoundError:
        return "absent"
    return "link" if stat.S_ISLNK(m) else "dir" if stat.S_ISDIR(m) else "other"


def points_to(pfd, name, render):
    """True when the entry name of pfd is a symbolic link that resolves to the render."""
    try:
        target = os.readlink(name, dir_fd=pfd)
    except OSError:
        return False
    return os.path.realpath(target) == os.path.realpath(render)


def apply_link(facts, parts, pfd, render):
    """Steps (1) to (3) of the docstring. On a failure: undo what can be undone, say the state, exit 1."""
    leaf = parts[-1]
    bname = leaf + BACKUP_SUFFIX
    tmp = ".qargi-link.%d" % os.getpid()
    link, backup = facts["link"], facts["backup"]
    made, moved, rolled = False, False, False
    try:
        now = kind_of(pfd, leaf)
        if facts["kind"] == "dir":
            if now != "dir":
                raise Refused("%s is no longer a real directory (it is %s)" % (link, "absent" if now == "absent" else "a " + now))
            if kind_of(pfd, bname) != "absent":
                raise Refused("%s exists now; qargi never overwrites or deletes a backup" % backup)
            os.symlink(render, tmp, dir_fd=pfd)
            made = True
            fault("after-tmp-link")
            rename_new(pfd, leaf, bname)
            moved = True
            fault("after-backup")
            rename_new(pfd, tmp, leaf)
            made = False
        else:
            if now != "absent":
                raise Refused("%s exists now (it did not when the plan was made)" % link)
            os.symlink(render, leaf, dir_fd=pfd)
    except BaseException as e:
        why = str(e) if isinstance(e, Refused) else "%s%s" % (e.strerror or type(e).__name__, " (%s)" % e.filename if getattr(e, "filename", None) else "") if isinstance(e, OSError) else repr(e)
        stray = ""
        if made:
            try:
                os.unlink(tmp, dir_fd=pfd)
            except OSError:
                stray = " A temporary symbolic link %s remains beside it; it is ours and can be removed." % os.path.join(os.path.dirname(link), tmp)
        if moved:
            try:
                fault("rollback")
                rename_new(pfd, bname, leaf)
                moved, rolled = False, True
            except OSError:
                pass
        if moved:
            die("cannot link %s: %s. The skills directory was moved and could not be put back: your skills are in %s and %s does not exist. "
                "Recovery: qargi packs unlink %s (it plans moving the backup back), or mv %s %s.%s Nothing was deleted."
                % (link, why, backup, link, facts["project"], backup, link, stray))
        if facts["kind"] == "dir":
            die("cannot link %s: %s. The skills directory was %s; %s" % (link, why, "moved and put back" if rolled else "not moved",
                                                                          "nothing was changed." if not stray else stray.strip()))
        die("cannot link %s: %s. No link was made; nothing else was changed (a missing directory above it may have been created, empty).%s" % (link, why, stray))
    say("linked: %s -> %s" % (link, render))
    if facts["kind"] == "dir":
        say("backup: %s (the former %s; qargi packs unlink %s moves it back)" % (backup, facts["rel"], facts["project"]))
    hint = exclude_hint(facts["checkout"], facts["rel"])
    if hint:
        say(hint)


def apply_unlink(facts, parts, pfd, render):
    """Steps (4) to (6) of the docstring, or the move of a backup whose link is already gone."""
    leaf = parts[-1]
    bname = leaf + BACKUP_SUFFIX
    aside = ".qargi-unlink.%d" % os.getpid()
    link, backup = facts["link"], facts["backup"]
    where = os.path.join(os.path.dirname(link), aside)
    phase = "start"          # start: nothing moved; aside: the link is at `aside`; restored: the backup is at the path, `aside` remains
    try:
        now = kind_of(pfd, leaf)
        if facts["kind"] == "backup":
            if now != "absent" or kind_of(pfd, bname) != "dir":
                raise Refused("%s or %s is not as the plan saw it" % (link, backup))
            rename_new(pfd, bname, leaf)
            say("unlinked: %s restored from %s (there was no link)" % (link, backup))
            return
        if now != "link" or not points_to(pfd, leaf, render):
            raise Refused("%s is not a symbolic link to this project's render any more; it is left alone" % link)
        has_backup = kind_of(pfd, bname) != "absent"
        if has_backup != facts["restore"] or (has_backup and kind_of(pfd, bname) != "dir"):
            raise Refused("%s changed since the plan; nothing is moved" % backup)
        if not has_backup:
            os.unlink(leaf, dir_fd=pfd)
            say("unlinked: %s removed" % link)
            return
        rename_new(pfd, leaf, aside)
        phase = "aside"
        if kind_of(pfd, aside) != "link" or not points_to(pfd, aside, render):   # what was moved is not what was checked: put it back
            raise Refused("%s was replaced while it was being moved; it is put back" % link)
        fault("after-aside")
        rename_new(pfd, bname, leaf)
        phase = "restored"
        fault("after-restore")
        os.unlink(aside, dir_fd=pfd)
        say("unlinked: %s restored from %s" % (link, backup))
    except BaseException as e:
        why = str(e) if isinstance(e, Refused) else "%s%s" % (e.strerror or type(e).__name__, " (%s)" % e.filename if getattr(e, "filename", None) else "") if isinstance(e, OSError) else repr(e)
        if phase == "aside":
            try:
                fault("rollback")
                rename_new(pfd, aside, leaf)
                phase = "start"
            except OSError:
                pass
        if phase == "aside":
            die("cannot unlink %s: %s. The link could not be put back: it is at %s and %s does not exist; your skills are in %s. "
                "Recovery: qargi packs unlink %s (it plans moving the backup back), or mv %s %s, then remove the link %s if you do not want it. "
                "Nothing was deleted." % (link, why, where, link, backup, facts["project"], backup, link, where))
        if phase == "restored":
            die("cannot unlink %s: %s. The skills are back at %s (from %s); a temporary symbolic link %s remains beside it; it is ours and can be removed."
                % (link, why, link, backup, where))
        die("cannot unlink %s: %s. %s" % (link, why, "The link is in place and nothing was changed." if facts["kind"] != "backup"
                                           else "The backup is where it was and nothing was changed."))


def cmd_apply(verb, inp, token):
    if marshal_refs.in_member_run():
        die("packs %s is not available in a member run: only the lead's session changes what a checkout loads; nothing was changed" % verb)
    facts = classify(verb, inp)
    if facts["kind"] == "linked" or token_of(facts) != token:
        die("the plan changed since it was approved; nothing was changed")
    hold()
    parts = skills_dir(inp).split("/")
    try:
        pfd = open_parent(facts["checkout"], parts[:-1], create=verb == "link" and facts["kind"] == "absent")
    except Refused as e:
        die("%s; nothing was changed" % e)
    try:
        (apply_link if verb == "link" else apply_unlink)(facts, parts, pfd, facts["render"])
    finally:
        os.close(pfd)


def main():
    if len(sys.argv) < 5 or sys.argv[1] not in ("plan", "apply") or sys.argv[2] not in ("link", "unlink"):
        die("usage: packs_link.py plan|apply link|unlink INPUTS TOKENFILE|TOKEN")
    try:
        with open(sys.argv[3]) as fh:
            inp = bind(json.load(fh))
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
