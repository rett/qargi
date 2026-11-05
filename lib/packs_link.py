#!/usr/bin/env python3
"""Link a project's repository to the render of its packs for the project's provider.

`qargi packs apply --target T PROJECT` renders the project's skills under <state>/render/PROJECT/PROVIDER/<skills dir>, where T is the
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

This file is the skills wrapper of the link engine, lib/linker.py: it turns the project's answers and the provider's layout into one
link (resource kind `skills`, mode dir-symlink), says what is specific to skills (a real skills directory's skills are compared with
the library's packs, and offered for import) and keeps the command's words. The mechanics are the engine's.

The only paths written, how apply stays inside the checkout, the crash safety and the fault hooks of the tests are the engine's
(lib/linker.py). Nothing is ever deleted except a symbolic link this tool made.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import linker  # noqa: E402
import packs_audit  # noqa: E402  (strict_hash)
import packs_render  # noqa: E402  (render_dir)
import paths  # noqa: E402
import provider  # noqa: E402

NAME_RE = linker.NAME_RE
BACKUP_SUFFIX = linker.BACKUP_SUFFIX
clean, say, q, die, linked = linker.clean, linker.say, linker.q, linker.die, linker.linked
WORDS = {"plural": "skills", "singular": "skill", "dir": "skills directory", "source": "this project's render", "source_word": "render",
         "loads": "the project's packs from the render", "cli": "packs"}


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
    if inp.get("provider") != provider.provider_of(answers, "local", project):
        die("the inputs name the provider %r, not the project's; refusing" % (inp.get("provider"),))
    inp["state"] = paths.state()
    return inp


def skills_dir(inp):
    """The project skills directory of the project's provider (relative to a checkout or a render), or exit 3."""
    provider.require_skills(inp["provider"], "link the checkout's skills directory to the render", project=inp["project"])
    return provider.require(inp["provider"], "project_skills_dir", "link the checkout's skills directory to the render", project=inp["project"])


def render_path(inp):
    project = inp["project"]
    if not NAME_RE.fullmatch(project) or ".." in project:
        die("not a project name: " + project)
    return os.path.join(packs_render.render_dir(inp["state"], project, inp["provider"]), skills_dir(inp))


class SkillsLink(linker.Link):
    """The link of the skills directory: what is specific to skills is the comparison of a real directory's skills with the library."""

    def __init__(self, inp):
        self.inp = inp
        rel = skills_dir(inp)
        super().__init__("skills", inp["project"], inp.get("checkout") or "", rel, render_path(inp), "dir-symlink", inp["state"],
                         dict(WORDS, unlink="qargi packs unlink %s" % inp["project"]))

    def source_missing(self):
        target = provider.layout(self.inp["provider"], project=self.project)["render_target"]
        how = "run qargi packs apply --target %s %s first" % (target, self.project) if target else "qargi does not make one for this provider"
        die("there is no render of %s yet: %s" % (self.project, how))

    def inspect_real(self, path):
        kids = []
        known = {k["name"] for k in self.inp.get("kids", [])}
        for k in sorted(self.inp.get("kids", []), key=lambda k: k["name"]):
            lib = packs_audit.library_hash(k["name"]) if k.get("in_library") and NAME_RE.fullmatch(k["name"]) else None
            if lib is None:
                st = "new"
            else:
                mine = packs_audit.strict_hash(os.path.join(path, k["name"]))
                st = "same" if mine and mine == lib else "differs"
            kids.append([k["name"], st])
        return {"others": sorted(n for n in os.listdir(path) if n not in known), "kids": kids}

    def show_real(self, facts):
        link = clean(facts["link"])
        p = clean(facts["project"])
        say("  %s is a real directory with %d skill%s; nothing in it is tracked by git" % (facts["rel"], len(facts["kids"]), "" if len(facts["kids"]) == 1 else "s"))
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

    def real_note(self):
        return "  Skills that are not imported and linked stop loading in the checkout until they are; they stay in the backup."


def main():
    if len(sys.argv) < 5 or sys.argv[1] not in ("plan", "apply") or sys.argv[2] not in ("link", "unlink"):
        die("usage: packs_link.py plan|apply link|unlink INPUTS TOKENFILE|TOKEN")
    try:
        with open(sys.argv[3]) as fh:
            inp = bind(json.load(fh))
        (linker.cmd_plan if sys.argv[1] == "plan" else linker.cmd_apply)(sys.argv[2], SkillsLink(inp), sys.argv[4])
    except provider.Unsupported as e:
        print("qargi: %s" % e, file=sys.stderr)
        sys.exit(3)
    except provider.ProviderError as e:
        die(str(e))
    except OSError as e:
        die("%s: %s" % (e.filename or "file system error", e.strerror or e))


if __name__ == "__main__":
    main()
