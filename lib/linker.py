#!/usr/bin/env python3
"""The link engine: make a path inside a checkout load a resource that qargi keeps (rendered or stored) under its state directory.

One engine serves every resource of a provider definition (skills, agents, ...). A caller describes ONE link with a Link object:

  Link(kind, project, checkout, dest, source, mode, state)

  kind      the resource kind's name (`skills`, `agents`, ...); it is part of the plan, so a plan for one kind is not one for another
  project   the project's name (for messages and recovery commands)
  checkout  the top of a git work tree: the project's repository or one of its worktrees; nothing outside it is ever written
  dest      the path of the link, relative to the checkout, parts separated by /
  source    the directory (or, for dir-symlink, a file) under the state directory that the link makes visible
  mode      dir-symlink    dest is a symbolic link to source
            entry-symlinks dest stays a real directory and holds one symbolic link per entry of source; only links qargi made (they point
                           into source) are ever touched, the user's own entries are left alone
            copy           dest stays a real directory and holds a copy of each entry of source, recorded in a manifest beside it, for
                           runtimes that do not follow symbolic links; unlink removes only a copy that is still what qargi made
  state     the state directory; source must lie below it and be reached through no symbolic link

Nothing in a Link names a provider or a runtime. The words a message needs (the plural of the resource, the command that undoes the
link, ...) are the Link's `words`; a caller whose messages must stay as they are overrides the hooks below (inspect_real, show_real,
real_note, source_missing).

The verbs, each with a plan and an apply (the caller holds the project's lock and gathers what only it knows into the Link):

  plan(verb, link)            the facts of the plan (a JSON-able dict) for verb link|unlink; refuses what must not be touched
  show_plan(facts, link)      print them
  token_of(facts)             the plan token: a hash of the facts, which name the kind, the mode, the source (its listing and the
                              classification of every entry, where the mode links or copies entries) and the state of the destination
  cmd_plan(verb, link, tokenfile)   print the plan and write the token (none when there is nothing to do)
  cmd_apply(verb, link, token)      re-plan, refuse if the plan changed, then change the file system

A member's run (a directory `qargi local prepare` made, at or above the working directory) never applies: only the lead's session
changes what a checkout loads.

The only paths written are the directories above the destination inside the checkout (when missing), the destination (the link, or
the entries in it), the backup of a real directory or file, beside the destination (<dest>.qargi-backup), and a temporary symbolic
link beside what it replaces (.qargi-link.PID or .qargi-unlink.PID) that is renamed into place or removed. Nothing is ever deleted
except a symbolic link this tool made.

Apply works through a file descriptor of the destination's parent directory (opened from the checkout one component at a time, never
through a symbolic link) and renames and links relative to it, so a directory swapped for a symbolic link after the plan cannot
redirect it. It never overwrites: a rename that must not replace anything uses renameat2(RENAME_NOREPLACE) where the kernel has it, and
otherwise a check just before the rename (a window remains there only on a file system without the flag). It re-reads what it is about
to move or remove and refuses what is not as the plan saw it.

Crash safety, dir-symlink. link: (1) make the link under a temporary name beside the path, (2) rename the real directory to the backup
name, (3) rename the temporary link onto the path. Only between (2) and (3) is there no directory at the path, and the backup holds
everything; unlink (4) renames the link to a temporary name, (5) renames the backup onto the path, (6) removes the temporary link. A
failure anywhere puts things back where it can and says exactly what state the checkout is in and what to do (never "nothing was
changed" unless that is true). If the backup exists and the link does not (a stop between (2) and (3)), unlink plans the move of the
backup back.

Tests inject faults with QARGI_TEST_FAULT=NAME[,NAME] (after-tmp-link, after-backup, after-aside, after-restore, rollback: a failing
rollback, and the names of the other modes) and stop between the plan and the act with QARGI_TEST_HOLD=PATH (the engine creates
PATH.reached and waits for PATH.go); nothing else reads them.
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

NAME_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]*')   # used with fullmatch: a `$` would let a trailing newline through
KIND_RE = re.compile(r'[a-z][a-z0-9-]{0,39}')
BACKUP_SUFFIX = ".qargi-backup"
CTRL_RE = re.compile(r"[\x00-\x1f\x7f]")
MODES = ("dir-symlink", "entry-symlinks", "copy")


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


def git(base, *args):
    """(exit status, stdout) of a git command in base, with no repository override from the environment."""
    env = {k: v for k, v in os.environ.items() if k not in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR")}
    r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-C", base] + list(args), capture_output=True, text=True,
                       stdin=subprocess.DEVNULL, env=env)
    return r.returncode, r.stdout


def linked(path, source):
    """True when path is a symbolic link that resolves to source."""
    return os.path.islink(path) and os.path.realpath(path) == os.path.realpath(source)


def tracked(base, rel):
    rc, out = git(base, "ls-files", "--", rel)
    return rc == 0 and out.strip() != ""


def exclude_hint(base, rel):
    """A line telling the owner to ignore the destination, or None when git already ignores it. Nothing is edited."""
    rc, _ = git(base, "check-ignore", "-q", "--", rel)
    if rc == 0:
        return None
    rc, path = git(base, "rev-parse", "--git-path", "info/exclude")
    path = path.strip() if rc == 0 and path.strip() else ".git/info/exclude"
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return "warning: git does not ignore %s, so the link shows up as untracked; to keep it out of git status add this line to %s:\n    %s" % (rel, path, rel)


def resolve_checkout(repo, cwd=None):
    """The checkout a link is made in for a project whose repository is repo: the top of the work tree of cwd when that work tree
    belongs to the same repository (it is a worktree of it, or the repository's own), else repo. The links are the record: no list of
    worktrees is kept anywhere."""
    cwd = os.path.realpath(cwd or os.getcwd())
    rc, top = git(cwd, "rev-parse", "--show-toplevel")
    if rc != 0 or not top.strip():
        return repo
    rc1, mine = git(cwd, "rev-parse", "--path-format=absolute", "--git-common-dir")
    rc2, theirs = git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if rc1 == 0 and rc2 == 0 and mine.strip() and os.path.realpath(mine.strip()) == os.path.realpath(theirs.strip()):
        return os.path.realpath(top.strip())
    return repo


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
    """A directory descriptor of base/parts[0]/.../parts[-1], each component opened relative to the one before without following a
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
    """"absent", "link", "dir", "file" or "other" for the entry name of the directory pfd (nothing followed)."""
    try:
        m = os.lstat(name, dir_fd=pfd).st_mode
    except FileNotFoundError:
        return "absent"
    return "link" if stat.S_ISLNK(m) else "dir" if stat.S_ISDIR(m) else "file" if stat.S_ISREG(m) else "other"


def points_to(pfd, name, source):
    """True when the entry name of pfd is a symbolic link that resolves to source."""
    try:
        target = os.readlink(name, dir_fd=pfd)
    except OSError:
        return False
    return os.path.realpath(target) == os.path.realpath(source)


def why_of(e):
    """The reason an exception gives, for a message."""
    if isinstance(e, Refused):
        return str(e)
    if isinstance(e, OSError):
        return "%s%s" % (e.strerror or type(e).__name__, " (%s)" % e.filename if getattr(e, "filename", None) else "")
    return repr(e)


def token_of(facts):
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()[:12]


class Link:
    """One link to make or undo: the data above, the words of its messages and the hooks of a caller that has more to say."""

    def __init__(self, kind, project, checkout, dest, source, mode, state, words=None):
        if not isinstance(kind, str) or not KIND_RE.fullmatch(kind):
            die("not a resource kind: %s" % (kind,))
        if not isinstance(project, str) or not NAME_RE.fullmatch(project) or ".." in project:
            die("not a project name: %s" % (project,))
        if mode not in MODES:
            die("not a link mode: %s (one of %s)" % (mode, ", ".join(MODES)))
        parts = dest.split("/") if isinstance(dest, str) else []
        if not parts or any(p in ("", ".", "..") or CTRL_RE.search(p) for p in parts):
            die("not a path inside a checkout: %s" % (dest,))
        self.kind, self.project, self.checkout, self.dest, self.mode = kind, project, checkout, dest, mode
        self.parts = parts
        self.source = os.path.abspath(source)
        self.state = os.path.abspath(state)
        singular = kind[:-1] if kind.endswith("s") else kind
        self.words = {"plural": kind, "singular": singular, "dir": "%s directory" % kind, "source": "this project's %s source" % kind,
                      "source_word": "%s source" % kind, "loads": "the project's %s from the source" % kind, "cli": "packs",
                      "unlink": "qargi packs unlink %s" % project}
        self.words.update(words or {})

    # ---- hooks -----------------------------------------------------------------------------------------------------------------

    def source_missing(self):
        """Called when the source does not exist (link only). Must not return."""
        die("there is no %s source for %s yet: %s does not exist" % (self.kind, self.project, self.source))

    def inspect_real(self, path):
        """The facts about the real directory at path that dir-symlink is about to move to a backup (added to the plan, so the token
        covers them). Default: the names in it."""
        return {"others": sorted(os.listdir(path))}

    def show_real(self, facts):
        """Print what the plan knows about the real directory (the line after `link:` and `target:`)."""
        w = self.words
        n = len(facts.get("kids", []))
        say("  %s is a real %s%s; nothing in it is tracked by git" % (facts["rel"], "file" if facts["state"] == "file" else "directory",
                                                                   "" if not n else " with %d %s" % (n, w["singular"] if n == 1 else w["plural"])))
        if facts.get("others"):
            say("    entries moved with it: %s" % ", ".join(clean(o) for o in facts["others"]))

    def real_note(self):
        """A line printed after `apply moves the directory ...`, or None."""
        return None

    # ---- the checkout ----------------------------------------------------------------------------------------------------------

    def locate(self):
        """(checkout realpath, destination path, backup path) of a checkout that is the top of a git work tree."""
        co = self.checkout or ""
        if not co:
            die("project %s has no checkout (repo.path is empty): qargi project set %s repo.path DIR" % (self.project, self.project))
        if not os.path.isabs(co) or not os.path.isdir(co):
            die("the checkout %s of project %s is not a directory" % (co, self.project))
        base = os.path.realpath(co)
        rc, top = git(base, "rev-parse", "--show-toplevel")
        if rc != 0 or os.path.realpath(top.strip()) != base:
            die("%s is not the top of a git work tree; refusing" % co)
        cdir = base
        for part in self.parts[:-1]:
            cdir = os.path.join(cdir, part)
            if os.path.islink(cdir):
                die("%s is a symbolic link; refusing (the link would be created outside the checkout's own files)" % cdir)
            if os.path.lexists(cdir) and not os.path.isdir(cdir):
                die("%s exists and is not a directory; refusing" % cdir)
        link = os.path.join(cdir, self.parts[-1])
        return base, link, link + BACKUP_SUFFIX

    def source_ready(self):
        """Refuse a source that is missing or reached through a symbolic link inside the state directory."""
        rel = os.path.relpath(self.source, self.state)
        if rel == "." or rel.startswith(".."):
            die("%s is not below the state directory %s; refusing" % (self.source, self.state))
        p = self.state
        for part in rel.split(os.sep):
            p = os.path.join(p, part)
            if os.path.islink(p):
                die("%s is a symbolic link; refusing" % p)
        if self.mode == "dir-symlink":
            if not os.path.isdir(self.source) and not os.path.isfile(self.source):
                self.source_missing()
        elif not os.path.isdir(self.source):
            self.source_missing()


# ---- dir-symlink -------------------------------------------------------------------------------------------------------------

def classify_dir(verb, lk):
    """The facts of the plan for verb link|unlink in mode dir-symlink; refuses what must not be touched."""
    base, link, backup = lk.locate()
    rel = lk.dest
    w = lk.words
    facts = {"verb": verb, "resource": lk.kind, "mode": lk.mode, "project": lk.project, "checkout": base, "link": link, "source": lk.source,
             "backup": backup, "rel": rel, "kids": []}
    present = os.path.lexists(link)
    if verb == "link":
        lk.source_ready()
        want = "dir" if os.path.isdir(lk.source) else "file"
        facts["source_kind"] = want
        if present and os.path.islink(link):
            if linked(link, lk.source):
                facts["state"] = "linked"
                return facts
            die("%s is a symbolic link to %s, not to %s; refusing to replace it" % (link, os.readlink(link), w["source"]))
        if tracked(base, rel):
            die("files under %s are tracked by git in %s: the repository's owner decides how its %s are loaded; "
                "qargi does not touch tracked files" % (rel, base, w["plural"]))
        if os.path.lexists(backup):
            die("%s already exists; %s (qargi never overwrites or deletes a backup)"
                % (backup, "%s moves it back to %s" % (w["unlink"], link) if not present else "move it away first"))
        if not present:
            facts["state"] = "absent"
        elif want == "dir" and os.path.isdir(link):
            facts["state"] = "dir"
            facts.update(lk.inspect_real(link))
        elif want == "file" and os.path.isfile(link):
            facts["state"] = "file"
        else:
            die("%s exists and is not a %s or a symbolic link; refusing" % (link, "directory" if want == "dir" else "file"))
        return facts
    # unlink
    if present and os.path.islink(link):
        if not linked(link, lk.source):
            die("%s is a symbolic link to %s, not to %s; refusing to remove it" % (link, os.readlink(link), w["source"]))
        facts["state"] = "ours"
        facts["restore"] = os.path.lexists(backup)
        return facts
    if present:
        die("%s is not a symbolic link (a real %s has taken its place); refusing to touch it" % (link, rel))
    if os.path.lexists(backup):
        if not os.path.islink(backup) and (os.path.isdir(backup) or os.path.isfile(backup)):
            facts["state"] = "backup"     # a link that stopped half way: the link is gone, what it replaced is in the backup
            facts["restore"] = True
            return facts
        die("%s exists and is not a directory; refusing to move it to %s" % (backup, link))
    die("%s is not linked to the %s of %s; nothing to unlink" % (link, w["source_word"], lk.project))


def show_dir(facts, lk):
    p, link, source, backup, rel = (clean(facts[k]) for k in ("project", "link", "source", "backup", "rel"))
    w = lk.words
    if facts["verb"] == "link":
        say("link plan for %s: the checkout %s loads %s" % (p, clean(facts["checkout"]), w["loads"]))
        say("  link:   %s" % link)
        say("  target: %s" % source)
        if facts["state"] == "absent":
            say("  %s does not exist: create %s (if missing) and the symbolic link" % (rel, os.path.dirname(link)))
        else:
            lk.show_real(facts)
            say("  apply moves the %s to %s (nothing is deleted) and creates the link." % ("directory" if facts["state"] == "dir" else "file", backup))
            note = lk.real_note()
            if note:
                say(note)
        say("  undo: %s" % clean(w["unlink"]))
    elif facts["state"] == "backup":
        say("unlink plan for %s: %s is not linked, but the backup %s exists (a link stopped half way, or the link was removed by hand)" % (p, link, backup))
        say("  move %s back to %s; there is no link to remove" % (backup, link))
    else:
        say("unlink plan for %s: remove the symbolic link %s (it points to %s)" % (p, link, source))
        if facts["restore"]:
            say("  and move %s back to %s" % (backup, link))
        else:
            say("  there is no backup, so %s will not exist afterwards" % rel)


def apply_link(facts, lk, pfd):
    """Steps (1) to (3) of the docstring. On a failure: undo what can be undone, say the state, exit 1."""
    leaf = lk.parts[-1]
    bname = leaf + BACKUP_SUFFIX
    tmp = ".qargi-link.%d" % os.getpid()
    link, backup, source = facts["link"], facts["backup"], facts["source"]
    w = lk.words
    real = facts["state"] in ("dir", "file")
    made, moved, rolled = False, False, False
    try:
        now = kind_of(pfd, leaf)
        if real:
            if now != facts["state"]:
                raise Refused("%s is no longer a real %s (it is %s)" % (link, "directory" if facts["state"] == "dir" else "file",
                                                                         "absent" if now == "absent" else "a " + now))
            if kind_of(pfd, bname) != "absent":
                raise Refused("%s exists now; qargi never overwrites or deletes a backup" % backup)
            os.symlink(source, tmp, dir_fd=pfd)
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
            os.symlink(source, leaf, dir_fd=pfd)
    except BaseException as e:
        why = why_of(e)
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
            die("cannot link %s: %s. The %s was moved and could not be put back: your %s are in %s and %s does not exist. "
                "Recovery: %s (it plans moving the backup back), or mv %s %s.%s Nothing was deleted."
                % (link, why, w["dir"], w["plural"], backup, link, w["unlink"], q(backup), q(link), stray))
        if real:
            die("cannot link %s: %s. The %s was %s; %s" % (link, why, w["dir"], "moved and put back" if rolled else "not moved",
                                                          "nothing was changed." if not stray else stray.strip()))
        die("cannot link %s: %s. No link was made; nothing else was changed (a missing directory above it may have been created, empty).%s" % (link, why, stray))
    say("linked: %s -> %s" % (link, source))
    if real:
        say("backup: %s (the former %s; %s moves it back)" % (backup, facts["rel"], w["unlink"]))
    hint = exclude_hint(facts["checkout"], facts["rel"])
    if hint:
        say(hint)


def apply_unlink(facts, lk, pfd):
    """Steps (4) to (6) of the docstring, or the move of a backup whose link is already gone."""
    leaf = lk.parts[-1]
    bname = leaf + BACKUP_SUFFIX
    aside = ".qargi-unlink.%d" % os.getpid()
    link, backup, source = facts["link"], facts["backup"], facts["source"]
    w = lk.words
    where = os.path.join(os.path.dirname(link), aside)
    phase = "start"          # start: nothing moved; aside: the link is at `aside`; restored: the backup is at the path, `aside` remains
    try:
        now = kind_of(pfd, leaf)
        if facts["state"] == "backup":
            if now != "absent" or kind_of(pfd, bname) not in ("dir", "file"):
                raise Refused("%s or %s is not as the plan saw it" % (link, backup))
            rename_new(pfd, bname, leaf)
            say("unlinked: %s restored from %s (there was no link)" % (link, backup))
            return
        if now != "link" or not points_to(pfd, leaf, source):
            raise Refused("%s is not a symbolic link to %s any more; it is left alone" % (link, w["source"]))
        has_backup = kind_of(pfd, bname) != "absent"
        if has_backup != facts["restore"] or (has_backup and kind_of(pfd, bname) not in ("dir", "file")):
            raise Refused("%s changed since the plan; nothing is moved" % backup)
        if not has_backup:
            os.unlink(leaf, dir_fd=pfd)
            say("unlinked: %s removed" % link)
            return
        rename_new(pfd, leaf, aside)
        phase = "aside"
        if kind_of(pfd, aside) != "link" or not points_to(pfd, aside, source):   # what was moved is not what was checked: put it back
            raise Refused("%s was replaced while it was being moved; it is put back" % link)
        fault("after-aside")
        rename_new(pfd, bname, leaf)
        phase = "restored"
        fault("after-restore")
        os.unlink(aside, dir_fd=pfd)
        say("unlinked: %s restored from %s" % (link, backup))
    except BaseException as e:
        why = why_of(e)
        if phase == "aside":
            try:
                fault("rollback")
                rename_new(pfd, aside, leaf)
                phase = "start"
            except OSError:
                pass
        if phase == "aside":
            die("cannot unlink %s: %s. The link could not be put back: it is at %s and %s does not exist; your %s are in %s. "
                "Recovery: %s (it plans moving the backup back), or mv %s %s, then remove the link %s if you do not want it. "
                "Nothing was deleted." % (link, why, where, link, w["plural"], backup, w["unlink"], q(backup), q(link), q(where)))
        if phase == "restored":
            die("cannot unlink %s: %s. The %s are back at %s (from %s); a temporary symbolic link %s remains beside it; it is ours and can be removed."
                % (link, why, w["plural"], link, backup, where))
        die("cannot unlink %s: %s. %s" % (link, why, "The link is in place and nothing was changed." if facts["state"] != "backup"
                                           else "The backup is where it was and nothing was changed."))


# ---- what entry-symlinks and copy share --------------------------------------------------------------------------------------

def source_entries(lk):
    """([[name, "dir"|"file"]], [skipped names]): the entries of the source directory that are linked or copied, sorted. A name that
    starts with a dot, holds a control character, or is neither a directory nor a regular file is skipped (and said so in the plan)."""
    out, skipped = [], []
    for n in sorted(os.listdir(lk.source)):
        m = os.lstat(os.path.join(lk.source, n)).st_mode
        if n.startswith(".") or CTRL_RE.search(n) or not (stat.S_ISDIR(m) or stat.S_ISREG(m)):
            skipped.append(n)
        else:
            out.append([n, "dir" if stat.S_ISDIR(m) else "file"])
    return out, skipped


def tracked_any(base, rels):
    """The first of the relative paths rels that git tracks in base, or None."""
    if not rels:
        return None
    rc, out = git(base, "ls-files", "-z", "--", *rels)
    names = [n for n in out.split("\0") if n] if rc == 0 else []
    return names[0] if names else None


def real_dest(lk, link):
    """Refuse a destination of entry-symlinks or copy that is not a real directory (or missing)."""
    if os.path.islink(link):
        die("%s is a symbolic link; refusing (mode %s keeps a real directory and puts the entries inside it)" % (link, lk.mode))
    if os.path.lexists(link) and not os.path.isdir(link):
        die("%s exists and is not a directory; refusing" % link)


def open_dest(pfd, leaf, link, create):
    """A descriptor of the destination directory in the directory pfd, made first when create (Refused if it exists by now)."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        try:
            os.mkdir(leaf, 0o777, dir_fd=pfd)
        except FileExistsError:
            raise Refused("%s exists now (it did not when the plan was made)" % link)
    try:
        return os.open(leaf, flags, dir_fd=pfd)
    except FileNotFoundError:
        raise Refused("%s does not exist any more" % link)
    except OSError as e:
        if e.errno in (errno.ELOOP, errno.ENOTDIR):
            raise Refused("%s is a symbolic link or not a directory now (it was neither when the plan was made)" % link)
        raise


class Journal:
    """What an apply has changed, each with the step that undoes it, so that a failure puts the files back where it can."""

    def __init__(self):
        self.ops = []

    def add(self, desc, undo):
        self.ops.append((desc, undo))

    def rollback(self):
        """Undo in reverse order. The descriptions of what could not be undone (all of it when the rollback itself fails)."""
        try:
            fault("rollback")
        except OSError:
            return [d for d, _ in reversed(self.ops)]
        left = []
        for desc, undo in reversed(self.ops):
            try:
                undo()
            except OSError:
                left.append(desc)
        return left


def failed(verb, lk, facts, e, journal):
    """Say what a failed apply left, after putting back what can be put back, and exit 1."""
    why = why_of(e)
    link = facts["link"]
    n = len(journal.ops)
    left = journal.rollback() if n else []
    above = " (a missing directory above it may have been created, empty)" if verb == "link" and facts["state"] == "absent" else ""
    if not n:
        die("cannot %s %s: %s. Nothing was changed%s." % (verb, link, why, above))
    if not left:
        die("cannot %s %s: %s. %d change%s made and put back; nothing was changed%s." % (verb, link, why, n, " was" if n == 1 else "s were", above))
    die("cannot %s %s: %s. %d of %d changes could not be put back: %s. Run the same command again to finish it, or %s undoes what is linked. "
        "Only links qargi made were removed or replaced; nothing else was deleted."
        % (verb, link, why, len(left), n, "; ".join(left), lk.words["unlink"]))


def own_links(lk, link):
    """{name: target} of the symbolic links in the directory link that point into the source: qargi's own entries."""
    out = {}
    src, real = os.path.normpath(lk.source), os.path.realpath(lk.source)
    for n in sorted(os.listdir(link)):
        p = os.path.join(link, n)
        if not os.path.islink(p):
            continue
        t = os.readlink(p)
        d = os.path.dirname(os.path.normpath(t if os.path.isabs(t) else os.path.join(link, t)))
        if d == src or os.path.realpath(d) == real:
            out[n] = t
    return out


def is_own(lk, link, target):
    src, real = os.path.normpath(lk.source), os.path.realpath(lk.source)
    d = os.path.dirname(os.path.normpath(target if os.path.isabs(target) else os.path.join(link, target)))
    return d == src or os.path.realpath(d) == real


def exclude_hint_many(base, rels):
    """One warning naming the paths of rels that git does not ignore, with the line to add for each, or None."""
    loose = [r for r in rels if git(base, "check-ignore", "-q", "--", r)[0] != 0]
    if not loose:
        return None
    rc, path = git(base, "rev-parse", "--git-path", "info/exclude")
    path = path.strip() if rc == 0 and path.strip() else ".git/info/exclude"
    if not os.path.isabs(path):
        path = os.path.join(base, path)
    return "warning: git does not ignore %s, so the links show up as untracked; to keep them out of git status add these lines to %s:\n%s" % (
        "them" if len(loose) > 1 else loose[0], path, "\n".join("    " + r for r in loose))


# ---- entry-symlinks ----------------------------------------------------------------------------------------------------------

def classify_entries(verb, lk):
    """The facts of the plan for verb link|unlink in mode entry-symlinks: for every entry of the source (and every link of ours the
    source has no entry for) what apply will do; refuses what is not qargi's to touch."""
    base, link, _ = lk.locate()
    rel = lk.dest
    w = lk.words
    facts = {"verb": verb, "resource": lk.kind, "mode": lk.mode, "project": lk.project, "checkout": base, "link": link, "source": lk.source,
             "rel": rel, "entries": [], "skipped": []}
    real_dest(lk, link)
    present = os.path.lexists(link)
    own = own_links(lk, link) if present else {}
    if verb == "unlink":
        if not own:
            die("%s has no entry linked to the %s of %s; nothing to unlink" % (link, w["source_word"], lk.project))
        facts["state"] = "ours"
        facts["entries"] = [[n, "remove", own[n]] for n in sorted(own)]
        return facts
    lk.source_ready()
    entries, facts["skipped"] = source_entries(lk)
    names = {n for n, _ in entries}
    for n, t in entries:
        p = os.path.join(link, n)
        want = os.path.join(lk.source, n)
        if not os.path.lexists(p):
            facts["entries"].append([n, "new", want])
        elif os.path.islink(p) and n in own:
            facts["entries"].append([n, "same" if os.path.basename(os.path.normpath(own[n])) == n else "relink", own[n]])
        elif os.path.islink(p):
            die("%s is a symbolic link to %s, not into %s; refusing to replace it" % (p, os.readlink(p), w["source"]))
        else:
            die("%s exists and is a real %s that qargi did not make; refusing to replace it (move it away first)" % (p, "directory" if os.path.isdir(p) else "file"))
    for n in sorted(own):
        if n not in names:
            facts["entries"].append([n, "stale", own[n]])
    facts["entries"].sort(key=lambda e: e[0])
    t = tracked_any(base, [rel + "/" + n for n, a, _ in facts["entries"] if a != "same"])
    if t:
        die("files under %s are tracked by git in %s (%s): the repository's owner decides how its %s are loaded; "
            "qargi does not touch tracked files" % (rel, base, t, w["plural"]))
    facts["state"] = "absent" if not present else "dir"
    if all(a == "same" for _, a, _ in facts["entries"]) and (present or not facts["entries"]):
        facts["state"] = "linked"
    return facts


def show_entries(facts, lk):
    p, link, source, rel = (clean(facts[k]) for k in ("project", "link", "source", "rel"))
    w = lk.words
    acts = facts["entries"]
    if facts["verb"] == "link":
        say("link plan for %s: the checkout %s loads %s, one link per entry" % (p, clean(facts["checkout"]), w["loads"]))
        say("  directory: %s" % link)
        say("  source:    %s" % source)
        if facts["state"] == "absent":
            say("  %s does not exist: create it (with %s if missing) and the links" % (rel, os.path.dirname(link)))
        else:
            say("  %s is a real directory and stays one; only links that point into the source are ever touched" % rel)
        how = {"new": "create", "same": "keep", "relink": "relink", "stale": "remove"}
        why = {"new": "", "same": "  (already linked)", "relink": "  (points elsewhere in the source; now to its own entry)",
               "stale": "  (a link of ours; the source has no entry of that name)"}
        for n, a, t in acts:
            say("    %-8s %s%s" % (how[a], q(n), why[a]))
        for n in facts["skipped"]:
            say("    skipped  %s  (unusual name or not a file or directory)" % q(n))
        say("  entries that are not qargi's are left alone; nothing is moved or deleted except links qargi made.")
        say("  undo: %s" % clean(w["unlink"]))
    else:
        say("unlink plan for %s: remove the %d link%s in %s that point into %s" % (p, len(acts), "" if len(acts) == 1 else "s", link, source))
        for n, a, t in acts:
            say("    remove   %s" % q(n))
        say("  entries that are not qargi's are left alone; the directory stays.")


def hint_entries(facts):
    if facts["verb"] != "link":
        return None
    return exclude_hint_many(facts["checkout"], [facts["rel"] + "/" + n for n, a, _ in facts["entries"] if a == "new"])


def _verify_entries(dfd, facts, lk):
    link = facts["link"]
    for n, a, target in facts["entries"]:
        cur = kind_of(dfd, n)
        p = os.path.join(link, n)
        if a == "new":
            if cur != "absent":
                raise Refused("%s exists now (it did not when the plan was made)" % p)
        else:
            try:
                now = os.readlink(n, dir_fd=dfd) if cur == "link" else None
            except OSError:
                now = None
            if now is None or not is_own(lk, link, now) or (a != "same" and now != target):
                raise Refused("%s is not the link of qargi's that the plan saw" % p)


def _swap_link(dfd, name, target):
    """Make name a symbolic link to target, replacing the symbolic link that is there (a link of ours), atomically."""
    tmp = ".qargi-link.%d" % os.getpid()
    os.symlink(target, tmp, dir_fd=dfd)
    try:
        os.rename(tmp, name, src_dir_fd=dfd, dst_dir_fd=dfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=dfd)
        except OSError:
            pass
        raise


def apply_entries(verb, facts, lk, pfd):
    link = facts["link"]
    journal = Journal()
    dfd = None
    try:
        dfd = open_dest(pfd, lk.parts[-1], link, create=verb == "link" and facts["state"] == "absent")
        if verb == "link" and facts["state"] == "absent":
            journal.add("created the directory %s" % q(link), lambda: os.rmdir(lk.parts[-1], dir_fd=pfd))
        _verify_entries(dfd, facts, lk)
        order = {"stale": 0, "remove": 0, "relink": 1, "new": 2}
        todo = sorted((e for e in facts["entries"] if e[1] != "same"), key=lambda e: (order[e[1]], e[0]))
        done = []
        for i, (n, a, target) in enumerate(todo, 1):
            if a in ("stale", "remove"):
                old = os.readlink(n, dir_fd=dfd)
                os.unlink(n, dir_fd=dfd)
                journal.add("removed the link %s (it pointed to %s)" % (q(n), q(old)), lambda n=n, old=old: os.symlink(old, n, dir_fd=dfd))
            elif a == "relink":
                old = os.readlink(n, dir_fd=dfd)
                _swap_link(dfd, n, os.path.join(lk.source, n))
                journal.add("changed the link %s (it pointed to %s)" % (q(n), q(old)), lambda n=n, old=old: _swap_link(dfd, n, old))
            else:
                os.symlink(target, n, dir_fd=dfd)
                journal.add("created the link %s" % q(n), lambda n=n: os.unlink(n, dir_fd=dfd))
            done.append((n, a))
            fault("after-entry-%d" % i)
    except BaseException as e:
        try:
            failed(verb, lk, facts, e, journal)
        finally:
            if dfd is not None:
                os.close(dfd)
    os.close(dfd)
    if verb == "link":
        say("linked: %s: %d entr%s from %s" % (link, len(done), "y" if len(done) == 1 else "ies", facts["source"]))
        for n, a in done:
            say("  %s %s" % ({"new": "created", "relink": "relinked", "stale": "removed"}[a], q(n)))
        hint = hint_entries(facts)
        if hint:
            say(hint)
    else:
        say("unlinked: %d link%s removed from %s" % (len(done), "" if len(done) == 1 else "s", link))


# ---- the verbs ---------------------------------------------------------------------------------------------------------------

def apply_dir(verb, facts, lk, pfd):
    (apply_link if verb == "link" else apply_unlink)(facts, lk, pfd)


def hint_dir(facts):
    return exclude_hint(facts["checkout"], facts["rel"]) if facts["verb"] == "link" else None


# mode -> (classify, show, apply, hint): the plan's facts, their text, the act and the line about git's exclude file
MODE_FUNCS = {"dir-symlink": (classify_dir, show_dir, apply_dir, hint_dir),
              "entry-symlinks": (classify_entries, show_entries, apply_entries, hint_entries)}


def _mode(lk):
    if lk.mode not in MODE_FUNCS:
        die("the link mode %s is not supported by this engine yet" % lk.mode)
    return MODE_FUNCS[lk.mode]


def plan(verb, lk):
    """The facts of the plan (a JSON-able dict) for verb link|unlink; refuses what must not be touched."""
    return _mode(lk)[0](verb, lk)


def show_plan(facts, lk):
    _mode(lk)[1](facts, lk)
    hint = _mode(lk)[3](facts)
    if hint:
        say(hint)


def cmd_plan(verb, lk, tokenfile):
    facts = plan(verb, lk)
    if facts["state"] == "linked":
        say("already linked: %s -> %s" % (clean(facts["link"]), clean(facts["source"])))
        return
    show_plan(facts, lk)
    with open(tokenfile, "w") as fh:
        fh.write(token_of(facts))


def cmd_apply(verb, lk, token):
    if marshal_refs.in_member_run():
        die("%s %s is not available in a member run: only the lead's session changes what a checkout loads; nothing was changed" % (lk.words["cli"], verb))
    facts = plan(verb, lk)
    if facts["state"] == "linked" or token_of(facts) != token:
        die("the plan changed since it was approved; nothing was changed")
    hold()
    try:
        pfd = open_parent(facts["checkout"], lk.parts[:-1], create=verb == "link" and facts["state"] == "absent")
    except Refused as e:
        die("%s; nothing was changed" % e)
    try:
        _mode(lk)[2](verb, facts, lk, pfd)
    finally:
        os.close(pfd)
