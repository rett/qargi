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

Crash safety, entry-symlinks and copy. Every change made by an apply is recorded with the step that undoes it; a failing step runs
them backwards, and the message says whether everything was put back or which changes were not and that running the same command
again finishes the job. entry-symlinks only ever removes or replaces a symbolic link that points into the source. copy checks every
entry against the plan before changing any, copies into a temporary name and renames it into place, moves a copy it replaces or
removes aside (and deletes the aside only after the manifest is written), and writes the manifest first with the entries to come, so
a stop leaves the manifest naming at least what it made.

Tests inject faults with QARGI_TEST_FAULT=NAME[,NAME] (dir-symlink: after-tmp-link, after-backup, after-aside, after-restore;
entry-symlinks and copy: after-entry-N, the stop after the Nth change; copy: after-copy, after a copy was made under its temporary
name; all: rollback, which makes the undo fail) and stop between the plan and the act with QARGI_TEST_HOLD=PATH (the engine creates
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
COPY_SUFFIX = ".qargi-copy.json"      # the manifest of copy mode, beside the destination
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


# ---- copy --------------------------------------------------------------------------------------------------------------------

DIRFLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def hash_at(dfd, name):
    """The content hash (32 hex digits) of the entry name of the directory dfd, or "" when it, or anything in it, is not a regular
    file or a directory (a symbolic link, a socket) or cannot be read. Nothing is followed. One line per entry, sorted by path and
    encoded as JSON: a regular file as its sha256 and whether any executable bit is set, an empty directory as itself, and the type of
    the entry itself first. Owners, times and the other mode bits are not part of it."""
    h = hashlib.sha256()

    def add(*rec):
        h.update((json.dumps(rec, ensure_ascii=True) + "\n").encode())

    def file_hash(fd_dir, n):
        f = hashlib.sha256()
        fd = os.open(n, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd_dir)
        try:
            with os.fdopen(fd, "rb", closefd=False) as fh:
                for chunk in iter(lambda: fh.read(65536), b""):
                    f.update(chunk)
        finally:
            os.close(fd)
        return f.hexdigest()

    def walk(fd, rel):
        names = sorted(os.listdir(fd))
        if not names and rel:
            add("D", rel)
        for n in names:
            r = rel + "/" + n if rel else n
            st = os.lstat(n, dir_fd=fd)
            if stat.S_ISDIR(st.st_mode):
                sub = os.open(n, DIRFLAGS, dir_fd=fd)
                try:
                    walk(sub, r)
                finally:
                    os.close(sub)
            elif stat.S_ISREG(st.st_mode):
                add("F", r, bool(st.st_mode & 0o111), file_hash(fd, n))
            else:
                raise ValueError(r)

    try:
        st = os.lstat(name, dir_fd=dfd)
        if stat.S_ISDIR(st.st_mode):
            add("T", "dir")
            sub = os.open(name, DIRFLAGS, dir_fd=dfd)
            try:
                walk(sub, "")
            finally:
                os.close(sub)
        elif stat.S_ISREG(st.st_mode):
            add("T", "file")
            add("F", "", bool(st.st_mode & 0o111), file_hash(dfd, name))
        else:
            return ""
    except (OSError, ValueError):
        return ""
    return h.hexdigest()[:32]


def copy_entry(sfd, sname, dfd, dname):
    """Copy the file or directory sname of the directory sfd to dname of the directory dfd (which must not have it); the executable
    bit is kept. Nothing is followed; anything but regular files and directories is an error."""
    st = os.lstat(sname, dir_fd=sfd)
    if stat.S_ISDIR(st.st_mode):
        os.mkdir(dname, 0o777, dir_fd=dfd)
        s2 = os.open(sname, DIRFLAGS, dir_fd=sfd)
        try:
            d2 = os.open(dname, DIRFLAGS, dir_fd=dfd)
            try:
                for n in sorted(os.listdir(s2)):
                    copy_entry(s2, n, d2, n)
            finally:
                os.close(d2)
        finally:
            os.close(s2)
    elif stat.S_ISREG(st.st_mode):
        fin = os.open(sname, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=sfd)
        try:
            fout = os.open(dname, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o777 if st.st_mode & 0o111 else 0o666, dir_fd=dfd)
            try:
                while True:
                    chunk = os.read(fin, 65536)
                    if not chunk:
                        break
                    os.write(fout, chunk)
            finally:
                os.close(fout)
        finally:
            os.close(fin)
    else:
        raise OSError(errno.EINVAL, "neither a regular file nor a directory", sname)


def remove_entry(dfd, name):
    """Remove the file or directory name of the directory dfd, and what is in it. Only ever called on a copy qargi made and checked."""
    st = os.lstat(name, dir_fd=dfd)
    if stat.S_ISDIR(st.st_mode):
        sub = os.open(name, DIRFLAGS, dir_fd=dfd)
        try:
            for n in os.listdir(sub):
                remove_entry(sub, n)
        finally:
            os.close(sub)
        os.rmdir(name, dir_fd=dfd)
    else:
        os.unlink(name, dir_fd=dfd)


def read_manifest(lk, path):
    """The manifest at path ({name: {type, hash}} of the copies qargi made), or {} when there is none. Dies on one that is not ours."""
    if not os.path.lexists(path):
        return {}
    if os.path.islink(path) or not os.path.isfile(path):
        die("%s is not a regular file; refusing" % path)
    try:
        with open(path) as fh:
            m = json.load(fh)
        ents = m["entries"]
        good = (m["schema"] == 1 and isinstance(ents, dict) and all(isinstance(v, dict) and isinstance(v.get("hash"), str) for v in ents.values())
                and all(isinstance(n, str) and n and "/" not in n and n not in (".", "..") for n in ents))
    except (OSError, ValueError, KeyError, TypeError):
        good = False
    if not good:
        die("%s is not a manifest qargi wrote; refusing to use it" % path)
    if m.get("kind") != lk.kind or m.get("source") != lk.source:
        die("%s belongs to another link (%s from %s); refusing to use it" % (path, m.get("kind"), m.get("source")))
    return ents


def manifest_bytes(lk, ents):
    return (json.dumps({"schema": 1, "kind": lk.kind, "source": lk.source, "entries": ents}, indent=1, sort_keys=True) + "\n").encode()


def write_manifest(pfd, name, data):
    """Replace (or, with data None, remove) the manifest file name of the directory pfd; the new one is written under another name and
    renamed onto the old, which is a regular file of ours."""
    if data is None:
        os.unlink(name, dir_fd=pfd)
        return
    tmp = ".qargi-manifest.%d" % os.getpid()
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o666, dir_fd=pfd)
    try:
        os.write(fd, data)
        os.fsync(fd)
    finally:
        os.close(fd)
    try:
        os.rename(tmp, name, src_dir_fd=pfd, dst_dir_fd=pfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=pfd)
        except OSError:
            pass
        raise


def read_file_at(pfd, name):
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=pfd)
    except FileNotFoundError:
        return None
    try:
        return os.read(fd, 1 << 24)
    finally:
        os.close(fd)


def classify_copy(verb, lk):
    """The facts of the plan for verb link|unlink in mode copy: for every entry of the source, and every copy qargi recorded, what apply
    will do, with the content hashes the decision was made on; refuses a copy that was modified and an entry that is not qargi's."""
    base, link, _ = lk.locate()
    rel = lk.dest
    w = lk.words
    mpath = link + COPY_SUFFIX
    facts = {"verb": verb, "resource": lk.kind, "mode": lk.mode, "project": lk.project, "checkout": base, "link": link, "source": lk.source,
             "rel": rel, "manifest": mpath, "entries": [], "skipped": []}
    real_dest(lk, link)
    present = os.path.lexists(link)
    recorded = read_manifest(lk, mpath)
    dfd = os.open(link, DIRFLAGS) if present else None
    try:
        def current(n):
            return hash_at(dfd, n) if dfd is not None and os.path.lexists(os.path.join(link, n)) else None

        def modified(n, cur):
            die("%s was changed since qargi copied it (it is not what %s recorded); refusing to touch it: move it away, or copy your change into the source"
                % (os.path.join(link, n), mpath))

        if verb == "unlink":
            if not recorded:
                die("%s has no copy recorded in %s; nothing to unlink" % (link, mpath))
            for n in sorted(recorded):
                cur = current(n)
                if cur is None:
                    facts["entries"].append([n, "forget", "", recorded[n]["hash"]])
                elif cur != recorded[n]["hash"]:
                    modified(n, cur)
                else:
                    facts["entries"].append([n, "remove", "", cur])
            facts["state"] = "ours"
            return facts
        lk.source_ready()
        entries, facts["skipped"] = source_entries(lk)
        names = {n for n, _ in entries}
        sfd = os.open(lk.source, DIRFLAGS)
        try:
            for n, t in entries:
                hs = hash_at(sfd, n)
                if not hs:
                    die("%s holds a symbolic link or another file that is neither a regular file nor a directory; mode copy does not copy those" % os.path.join(lk.source, n))
                cur = current(n)
                if cur is None:
                    facts["entries"].append([n, "new", hs, ""])
                elif n in recorded:
                    if cur != recorded[n]["hash"]:
                        modified(n, cur)
                    facts["entries"].append([n, "same" if cur == hs else "update", hs, cur])
                else:
                    die("%s exists and qargi did not make it; refusing to replace it (move it away first)" % os.path.join(link, n))
        finally:
            os.close(sfd)
        for n in sorted(recorded):
            if n in names:
                continue
            cur = current(n)
            if cur is None:
                facts["entries"].append([n, "forget", "", recorded[n]["hash"]])
            elif cur != recorded[n]["hash"]:
                modified(n, cur)
            else:
                facts["entries"].append([n, "stale", "", cur])
    finally:
        if dfd is not None:
            os.close(dfd)
    facts["entries"].sort(key=lambda e: e[0])
    t = tracked_any(base, [rel + "/" + n for n, a, _, _ in facts["entries"] if a not in ("same", "forget")] + [rel + COPY_SUFFIX])
    if t:
        die("files under %s are tracked by git in %s (%s): the repository's owner decides how its %s are loaded; "
            "qargi does not touch tracked files" % (rel, base, t, w["plural"]))
    facts["state"] = "absent" if not present else "dir"
    if all(a == "same" for _, a, _, _ in facts["entries"]) and (present or not facts["entries"]):
        facts["state"] = "linked"
    return facts


def show_copy(facts, lk):
    p, link, source, rel = (clean(facts[k]) for k in ("project", "link", "source", "rel"))
    w = lk.words
    acts = facts["entries"]
    if facts["verb"] == "link":
        say("link plan for %s: the checkout %s loads %s, as copies (this runtime does not follow links)" % (p, clean(facts["checkout"]), w["loads"]))
        say("  directory: %s" % link)
        say("  source:    %s" % source)
        say("  manifest:  %s (what qargi copied, with its content hash)" % clean(facts["manifest"]))
        if facts["state"] == "absent":
            say("  %s does not exist: create it (with %s if missing) and the copies" % (rel, os.path.dirname(link)))
        else:
            say("  %s is a real directory and stays one; only copies qargi made and that are unmodified are ever replaced or removed" % rel)
        how = {"new": "create", "same": "keep", "update": "update", "stale": "remove", "forget": "forget"}
        why = {"new": "", "same": "  (already copied)", "update": "  (the source changed; the copy is unmodified)",
               "stale": "  (a copy of ours, unmodified; the source has no entry of that name)", "forget": "  (recorded, but gone from the directory)"}
        for n, a, _, _ in acts:
            say("    %-8s %s%s" % (how[a], q(n), why[a]))
        for n in facts["skipped"]:
            say("    skipped  %s  (unusual name or not a file or directory)" % q(n))
        say("  entries that are not qargi's are left alone. A copy is replaced or removed only while it is what the manifest recorded.")
        say("  undo: %s" % clean(w["unlink"]))
    else:
        say("unlink plan for %s: remove the %d cop%s qargi made in %s (all unmodified), and the manifest" % (p, len([a for a in acts if a[1] == "remove"]),
                                                                                                           "y" if len([a for a in acts if a[1] == "remove"]) == 1 else "ies", link))
        for n, a, _, _ in acts:
            say("    %-8s %s%s" % ("remove" if a == "remove" else "forget", q(n), "" if a == "remove" else "  (recorded, but gone from the directory)"))
        say("  entries that are not qargi's are left alone; the directory stays.")


def hint_copy(facts):
    if facts["verb"] != "link":
        return None
    return exclude_hint_many(facts["checkout"], [facts["rel"] + "/" + n for n, a, _, _ in facts["entries"] if a == "new"] + [facts["rel"] + COPY_SUFFIX])


def apply_copy(verb, facts, lk, pfd):
    link, leaf = facts["link"], lk.parts[-1]
    mname = leaf + COPY_SUFFIX
    journal, asides, dfd, sfd, done = Journal(), [], None, None, []
    recorded = read_manifest(lk, link + COPY_SUFFIX)
    old_bytes = read_file_at(pfd, mname)
    try:
        dfd = open_dest(pfd, leaf, link, create=verb == "link" and facts["state"] == "absent")
        if verb == "link" and facts["state"] == "absent":
            journal.add("created the directory %s" % q(link), lambda: os.rmdir(leaf, dir_fd=pfd))
        if verb == "link":
            sfd = os.open(lk.source, DIRFLAGS)
        # nothing is changed before every entry is as the plan saw it
        for n, a, hs, old in facts["entries"]:
            cur = hash_at(dfd, n) if kind_of(dfd, n) != "absent" else None
            if a == "new":
                if cur is not None:
                    raise Refused("%s exists now (it did not when the plan was made)" % os.path.join(link, n))
            elif a == "forget":
                if cur is not None:
                    raise Refused("%s exists now (it did not when the plan was made)" % os.path.join(link, n))
            elif cur != old:
                raise Refused("%s is not the copy the plan saw" % os.path.join(link, n))
            if a in ("new", "update", "same") and verb == "link" and hash_at(sfd, n) != hs:
                raise Refused("%s changed in the source since the plan was made" % os.path.join(lk.source, n))
        final = {n: v for n, v in recorded.items() if n not in {e[0] for e in facts["entries"] if e[1] in ("stale", "remove", "forget")}}
        for n, a, hs, _ in facts["entries"]:
            if a in ("new", "update", "same"):
                final[n] = {"hash": hs}
        union = dict(recorded)
        union.update({n: {"hash": hs} for n, a, hs, _ in facts["entries"] if a in ("new", "update")})
        if verb == "link" and union != recorded:
            write_manifest(pfd, mname, manifest_bytes(lk, union))
            journal.add("changed the manifest %s" % q(link + COPY_SUFFIX),
                        lambda: write_manifest(pfd, mname, old_bytes) if old_bytes is not None else write_manifest(pfd, mname, None))
        order = {"stale": 0, "remove": 0, "update": 1, "new": 2}
        todo = sorted((e for e in facts["entries"] if e[1] in order), key=lambda e: (order[e[1]], e[0]))
        for i, (n, a, hs, old) in enumerate(todo, 1):
            if a in ("stale", "remove", "update"):
                aside = ".qargi-old.%d.%d" % (os.getpid(), i)
                rename_new(dfd, n, aside)
                asides.append(aside)
                journal.add("moved the copy %s to %s" % (q(n), q(os.path.join(link, aside))),
                            lambda n=n, aside=aside: rename_new(dfd, aside, n))
            if a in ("update", "new"):
                tmp = ".qargi-copy.%d.%d" % (os.getpid(), i)
                try:
                    copy_entry(sfd, n, dfd, tmp)
                    fault("after-copy")
                    if hash_at(dfd, tmp) != hs:
                        raise OSError(errno.EIO, "the copy of %s is not what was read" % n)
                    rename_new(dfd, tmp, n)
                except BaseException:
                    if kind_of(dfd, tmp) != "absent":
                        try:
                            remove_entry(dfd, tmp)
                        except OSError:
                            pass
                    raise
                journal.add("copied %s" % q(n), lambda n=n, hs=hs: remove_entry(dfd, n) if hash_at(dfd, n) == hs else None)
            done.append((n, a))
            fault("after-entry-%d" % i)
        if final:
            write_manifest(pfd, mname, manifest_bytes(lk, final))
        elif kind_of(pfd, mname) != "absent":
            write_manifest(pfd, mname, None)
    except BaseException as e:
        try:
            failed(verb, lk, facts, e, journal)
        finally:
            for fd in (dfd, sfd):
                if fd is not None:
                    os.close(fd)
    leftovers = []
    for aside in asides:
        try:
            remove_entry(dfd, aside)
        except OSError:
            leftovers.append(aside)
    os.close(dfd)
    if sfd is not None:
        os.close(sfd)
    if verb == "link":
        say("linked: %s: %d cop%s from %s" % (link, len(done), "y" if len(done) == 1 else "ies", facts["source"]))
        for n, a in done:
            say("  %s %s" % ({"new": "created", "update": "updated", "stale": "removed"}[a], q(n)))
        hint = hint_copy(facts)
        if hint:
            say(hint)
    else:
        say("unlinked: %d cop%s removed from %s" % (len(done), "y" if len(done) == 1 else "ies", link))
    if leftovers:
        say("note: %s could not be removed; they are qargi's old copies and can be deleted" % ", ".join(q(os.path.join(link, a)) for a in leftovers))


# ---- the verbs ---------------------------------------------------------------------------------------------------------------

def apply_dir(verb, facts, lk, pfd):
    (apply_link if verb == "link" else apply_unlink)(facts, lk, pfd)


def hint_dir(facts):
    return exclude_hint(facts["checkout"], facts["rel"]) if facts["verb"] == "link" else None


# mode -> (classify, show, apply, hint): the plan's facts, their text, the act and the line about git's exclude file
MODE_FUNCS = {"dir-symlink": (classify_dir, show_dir, apply_dir, hint_dir),
              "entry-symlinks": (classify_entries, show_entries, apply_entries, hint_entries),
              "copy": (classify_copy, show_copy, apply_copy, hint_copy)}


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
