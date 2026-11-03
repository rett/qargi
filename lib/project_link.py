#!/usr/bin/env python3
"""Link a project's resources (skills, agents, memory) from where qargi keeps them into the checkout and the home directory, for the
project's local runtime, on the generic link engine (lib/linker.py).

Everything a project uses lives under ~/.qargi (the packs' render, the members' render, the project's memory) and is linked from the
places the runtime reads: skills and agents into the checkout, memory into the runtime's memory directory of that checkout. What is
linked, where and how comes from the runtime's definition (resources.skills, .agents and .memory, each with link.project or link.user:
dir-symlink, entry-symlinks, copy or none); nothing here names a runtime.

  project_link.py plan  link|unlink PROJECT RESOURCES TOKENFILE   print the plan, write one token for all of it (none when nothing is to be done)
  project_link.py apply link|unlink PROJECT RESOURCES TOKEN       re-plan, refuse if the plan changed, then change the file system
  project_link.py members-dir PROJECT RUNTIME                     print where the members of PROJECT are rendered for RUNTIME

RESOURCES is a comma separated list of skills, agents, memory; empty means every resource the runtime can link and that has something to link
(a resource the runtime does not link, or whose source does not exist yet, is skipped with a line saying why; one you name is refused with exit
status 3 or 1). `unlink` with none named undoes the resources that are linked.

The checkout is the top of the work tree the current directory is in when that work tree belongs to the project's repository (a worktree of it,
or the repository itself), else the project's repo.path: a worktree gets its links by running the verb inside it. The links are the record:
nothing lists the worktrees of a project, and the status of a link is the status of the current work tree's.

Skills: the render of the project's packs (qargi packs apply). Agents: the render of the project's members, state/render/PROJECT/RUNTIME.agents
(qargi agent add NAME --project PROJECT; beside the runtime's render, not in it, because a packs render replaces its directory whole). Memory: the
project's memory tier (qargi memory init project), linked at the runtime's memory directory for the checkout (resources.memory.user_dir).

All the resources of one call are planned first and one token covers them; an apply that fails on one resource says which were done and which not.
A member's run never applies (the engine refuses). The mechanics, the only paths written and the crash safety are the engine's.
"""
import contextlib
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linker  # noqa: E402
import packs_link  # noqa: E402  (the skills link)
import packs_render  # noqa: E402  (render_dir)
import paths  # noqa: E402
import provider  # noqa: E402
import tiers  # noqa: E402  (the project's memory tier)

RESOURCES = ("skills", "agents", "memory")
die = linker.die


class Missing(Exception):
    """The source of a link does not exist yet (nothing was rendered, nothing was initialised): the message says what to run."""


class Skip(Exception):
    """The runtime does not link this resource."""


def members_dir(state, project, runtime):
    """Where the members of a project are rendered for a runtime: state/render/PROJECT/RUNTIME.agents. Beside the runtime's render
    (a runtime name has no dot), not in it: a packs render replaces its directory whole. The one place that says so (lib/agent.sh asks)."""
    return packs_render.render_dir(state, project, runtime) + ".agents"


def words(project, resource):
    base = {"cli": "project", "unlink": "qargi project unlink %s --resource %s" % (project, resource)}
    if resource == "agents":
        base.update(plural="members", singular="member", dir="agents directory", source="this project's member render", source_word="member render",
                    loads="the project's members from the render")
    if resource == "memory":
        base.update(plural="notes", singular="note", dir="memory directory", source="this project's memory", source_word="project memory",
                    loads="the project's memory from qargi's memory directory", place="the home directory")
    return base


class Memory(linker.Link):
    def source_missing(self):
        raise Missing("the memory of %s does not exist yet: %s is missing (qargi memory init project)" % (self.project, self.source))


class Members(linker.Link):
    def source_missing(self):
        raise Missing("no member of %s is rendered for this runtime yet: %s does not exist (qargi agent add NAME --project %s)"
                      % (self.project, self.source, self.project))


class Skills(packs_link.SkillsLink):
    def source_missing(self):
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            try:
                super().source_missing()
            except SystemExit:
                pass
        raise Missing(buf.getvalue().strip().removeprefix("qargi: "))


def mode_of(res, key, scope):
    """The link mode the definition gives resource key at scope project|user, or Skip."""
    r = res.get(key)
    if not isinstance(r, dict):
        raise Skip("the runtime has no %s resource" % key)
    m = (r.get("link") or {}).get(scope) if isinstance(r.get("link"), dict) else None
    if m not in linker.MODES:
        raise Skip("the runtime links no %s at %s level (link mode %s)" % (key, scope, m or "none"))
    return r, m


def kids_of(checkout, rel, conf):
    """The skills of a real project skills directory in the checkout, with whether the library has a pack of the same name (packs link's inputs)."""
    sk = os.path.join(checkout, rel)
    kids = []
    if os.path.isdir(os.path.dirname(sk)) and not os.path.islink(os.path.dirname(sk)) and os.path.isdir(sk) and not os.path.islink(sk):
        for n in sorted(os.listdir(sk)):
            d = os.path.join(sk, n)
            if os.path.isdir(d) and not os.path.islink(d) and os.path.isfile(os.path.join(d, "SKILL.md")):
                kids.append({"name": n, "in_library": os.path.isdir(os.path.join(conf, "packs", "skills", n))})
    return kids


class Context:
    """What the verb knows: the project's answers, its local runtime, its definition's resources and the checkout of the current directory."""

    def __init__(self, project):
        if not isinstance(project, str) or not linker.NAME_RE.fullmatch(project) or ".." in project:
            die("not a project name: %s" % (project,))
        self.project = project
        self.conf, self.state = paths.conf(), paths.state()
        self.answers = provider.project_answers(project, self.conf)
        if self.answers is None:
            die("no stored answers for project '%s'" % project)
        self.runtime = provider.provider_of(self.answers, "local", project)
        self.res = (provider.definition(self.runtime, "local").get("resources") or {})
        repo = (self.answers.get("repo") or {}).get("path") or ""
        if not repo:
            die("project %s has no checkout (repo.path is empty): qargi project set %s repo.path DIR" % (project, project))
        self.repo = repo
        self.checkout = linker.resolve_checkout(repo)

    def link_of(self, resource):
        """The Link of one resource, or Skip (the runtime does not link it)."""
        p, st, rt, co = self.project, self.state, self.runtime, self.checkout
        if resource == "skills":
            r, mode = mode_of(self.res, "skills", "project")
            provider.require_skills(rt, "link the checkout's skills directory to the render")
            rel = r.get("project_dir")
            if not rel:
                raise Skip("the runtime has no project skills directory")
            lk = Skills({"project": p, "provider": rt, "state": st, "checkout": co, "kids": kids_of(co, rel, self.conf)})
            lk.mode = mode
            lk.words.update(words(p, "skills"))
            return lk
        if resource == "agents":
            r, mode = mode_of(self.res, "agents", "project")
            if not r.get("project_dir"):
                raise Skip("the runtime has no project agents directory")
            return Members("agents", p, co, r["project_dir"], members_dir(st, p, rt), mode, st, words(p, "agents"))
        r, mode = mode_of(self.res, "memory", "user")
        tpl = r.get("user_dir") or ""
        if not tpl.startswith("~/"):
            raise Skip("the runtime keeps its memory directory outside the home directory (%s)" % (tpl or "none"))
        if "{checkout_key}" in tpl:
            tpl = tpl.replace("{checkout_key}", provider.checkout_key(r.get("checkout_key") or "nonalnum-dash", co))
        tier = next(t for t in tiers.resolve(self.answers, p) if t["tier"] == "project")
        src = tier["location"]
        mroot = os.path.join(paths.root(), "memory")
        if not src or not os.path.abspath(src).startswith(os.path.abspath(mroot) + os.sep):
            die("the memory of project %s is placed at %r, outside %s (memory.tiers.project.path); qargi links only what is kept there"
                % (p, src, mroot))
        return Memory("memory", p, co, tpl[2:], src, mode, st, words(p, "memory"), root=os.path.expanduser("~"), source_root=mroot)


def quiet(fn, *a):
    """(result, None) or (None, the refusal) of a call that dies: the engine's die() prints and exits."""
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            return fn(*a), None
    except SystemExit:
        return None, buf.getvalue().strip().removeprefix("qargi: ")


def select(ctx, verb, named):
    """([(resource, Link, facts)] to act on, [notes]). named: the resources asked for ([] = every one that applies). A named resource that
    cannot be done is a refusal (exit 3 when the runtime does not link it); an unnamed one is a note."""
    out, notes = [], []
    for resource in (named or RESOURCES):
        try:
            lk = ctx.link_of(resource)
        except Skip as e:
            if named:
                raise provider.Unsupported("provider %s has no %s link: %s" % (ctx.runtime, resource, e))
            notes.append("%s: not linked, %s" % (resource, e))
            continue
        if verb == "link":
            try:
                facts = linker.plan("link", lk)
            except Missing as e:
                if named:
                    die(str(e))
                notes.append("%s: not linked, %s" % (resource, e))
                continue
            out.append((resource, lk, facts))
            continue
        facts, why = quiet(linker.plan, "unlink", lk)
        if facts is None:
            if named:
                die(why)
            continue
        out.append((resource, lk, facts))
    return out, notes


def token_of(verb, items):
    return hashlib.sha256(json.dumps([verb, [(r, linker.token_of(f)) for r, _, f in items if f["state"] != "linked"]], sort_keys=True).encode()).hexdigest()[:12]


def cmd_plan(verb, ctx, named, tokenfile):
    items, notes = select(ctx, verb, named)
    for n in notes:
        linker.say(n)
    if not items:
        die("nothing to %s for %s%s" % (verb, ctx.project, "" if verb == "link" else " in this work tree (nothing is linked)"))
    todo = [i for i in items if i[2]["state"] != "linked"]
    for resource, lk, facts in items:
        if facts["state"] == "linked":
            linker.say("already linked: %s -> %s" % (linker.clean(facts["link"]), linker.clean(facts["source"])))
            continue
        linker.say("== %s (%s)" % (resource, lk.mode))
        linker.show_plan(facts, lk)
    if todo:
        with open(tokenfile, "w") as fh:
            fh.write(token_of(verb, items))


def cmd_apply(verb, ctx, named, token):
    items, _ = select(ctx, verb, named)
    if items:
        linker.refuse_member_run(verb, items[0][1])
    todo = [i for i in items if i[2]["state"] != "linked"]
    if not todo or token_of(verb, items) != token:
        die("the plan changed since it was approved; nothing was changed")
    done = []
    for resource, lk, facts in todo:
        try:
            linker.apply_planned(verb, lk, facts)
        except SystemExit:
            if done or len(todo) > len(done) + 1:
                rest = [r for r, _, _ in todo[len(done):]]
                print("qargi: %s of %s stopped at %s: %s done, %s not done; running the same command again plans what is left" % (
                    verb, ctx.project, rest[0], ", ".join(done) or "nothing", ", ".join(rest)), file=sys.stderr)
            raise
        done.append(resource)


def main():
    if len(sys.argv) == 4 and sys.argv[1] == "members-dir":      # for lib/agent.sh: where the members of PROJECT for RUNTIME are rendered
        print(members_dir(paths.state(), sys.argv[2], sys.argv[3]))
        return
    if len(sys.argv) != 6 or sys.argv[1] not in ("plan", "apply") or sys.argv[2] not in ("link", "unlink"):
        die("usage: project_link.py plan|apply link|unlink PROJECT RESOURCES TOKENFILE|TOKEN")
    phase, verb, project, res = sys.argv[1:5]
    named = [r for r in res.split(",") if r]
    bad = [r for r in named if r not in RESOURCES]
    if bad or len(set(named)) != len(named):
        die("--resource: %s (one or more of %s, each once)" % ("not a resource: " + ", ".join(bad) if bad else "a resource given twice", ", ".join(RESOURCES)))
    try:
        ctx = Context(project)
        (cmd_plan if phase == "plan" else cmd_apply)(verb, ctx, named, sys.argv[5])
    except provider.Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        sys.exit(3)
    except provider.NoProvider as e:
        print("qargi: %s" % e, file=sys.stderr)
        sys.exit(2)
    except provider.ProviderError as e:
        die(str(e))
    except OSError as e:
        die("%s: %s" % (e.filename or "file system error", e.strerror or e))


if __name__ == "__main__":
    main()
