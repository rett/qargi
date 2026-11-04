# Contributing

## Branching (git-flow)

- `master` holds released versions only; every release is a tag.
- `develop` is the integration branch.
- Work happens on `feature/<name>` branches, with every merge `--no-ff`. Use
  the `qargi feature` commands, which follow the git-flow model: `qargi feature
  start <name>`, `qargi feature merge <name> <branch>` for each verified task,
  and `qargi feature finish <name>` (merge into `develop`, after
  `qargi feature verify <name>` passed the whole suite).
- A release is `qargi release start <version>`; the `VERSION` and
  `CHANGELOG.md` update is its first commit, then `qargi release verify
  <version>`, `qargi release push <version>` (the branch and a pull request, so CI
  runs on what will be released) and `qargi release finish <version>`. Fixes to a released version
  use `qargi release start <version> --hotfix`.
- Pushing the tag publishes the GitHub release: `.github/workflows/release.yml` takes the version's section of `CHANGELOG.md` as the notes and attaches the
  source archive of the tag and its checksum. Only a tag on `master`'s history counts, and an existing release is left alone. A tag pushed before the
  workflow existed is published by running the workflow by hand with that tag.
- Tags are the bare version number, for example `0.1.0`.

## Layout

`bin/qargi` is the single command; `lib/` holds the scripts behind it;
`skills/qargi-*` are the skills (each a short guide that calls the command; the
roles are not skills: each role's text is `roles/<role>/ROLE.md`, which a member
gets with its task block); `agents/member.json` and `agents/member.body.md` are the one neutral
member definition `qargi agent add` renders, through the project's runtime, under the names users
choose; `lib/providers/` holds the shipped runtime definitions and model catalogs; `provision/` the resource and memory
templates; `examples/` sample repository profiles; `packs/` the baseline packs shipped
with qargi (`baseline.json` and `skills/<name>/SKILL.md`).

To add a baseline pack, write `packs/skills/<name>/SKILL.md` with front matter of
two keys, `name` (the directory name) and `description`, and portable text that names
no qargi verb, then list it in `packs/baseline.json`. The packs test checks both: every
directory is listed and the reverse, and each pack passes the library's review.

## Tests

`tests/run.sh` runs everything, and its list of tests and the linter is the inventory. It needs no API access and no private data.

Test a branch from its own worktree with `bin/qargi`: once `install.sh --user` has recorded the installed copy it is a dev run with its own data under `.qargi/` (README, Running a branch checkout). To test the guard or the hooks, put `<worktree>/bin` first on `PATH`: members call `qargi __guard` from `PATH`, which is otherwise the installed copy.

## Changing the canon

The layout of memory stores is versioned (`canon/CANON.md`, `canon/layout.json`).
A change to it needs a new version, a migration in `lib/canon.py` from the
version before it (only the current version is a target, so none is kept for
older ones), a case in `tests/test_canon.py` (plan, apply in memory, plan again
must be empty, check must pass) and a CHANGELOG entry.

## Versioning

[Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html), with the
version in the `VERSION` file:

- MAJOR: a change to the verb set, option names, registry or tracker file
  formats, or the agent contract that breaks existing use.
- MINOR: new verbs, options or profile keys that keep existing use working.
- PATCH: fixes and documentation.

Before 1.0.0 the minor number may carry breaking changes; the changelog says
so. The registry and tracker files carry a `schema` number once a release
depends on it.

## Changes

Every user-visible change adds a line under `## [Unreleased]` in
`CHANGELOG.md`, in the same commit as the change: one logical change per
commit, with its tests and docs. A change that spans three or more top-level
directories is split into commits that each build: code and tests, then docs
and changelog. Shell scripts must pass
`shellcheck -S warning`. Commit messages state what changed and why; no
private hostnames, addresses, usernames, home paths or credentials appear in
the repository or its history.

## Add a runtime with no code

A runtime (an agent CLI, a local model runner) is a data file; you do not change qargi to add one.
This walks through a fictional command-line runtime, `fakecli`. The lead follows the same steps
from the `/qargi-providers` skill.

1. Scaffold it: `qargi provider new fakecli --from command` (a plan and a token; apply it with
   `--plan TOKEN --approved "<your words>"`). The pack is `~/.qargi/config/packs/providers/fakecli/`
   and is unusable until you seal it. `--from minimal`, `hook-cli` or the name of another runtime
   start from other templates.
2. Edit `definition.json`. Four parts decide how qargi uses the runtime:
   - **models**: the pattern a model id must match, the model for each tier (`"*"` for all of
     them) and the effort levels (`null` for none). Write down where each id came from.
   - **render**: how a member becomes the runtime's own file (`agents` and `renderers.agent`),
     or `"agents": null` for a runtime with no agent files.
   - **link**: where its skills, agents, MCP file, settings and memory live (`resources`) and
     whether each is linked as a directory, one link per entry, or copied.
   - **contract addenda** (`resources.contract_addenda`): a runtime's rules about its own
     surface, as plain text files in the definition's directory (at most 16 KB each). A cloud
     agent's prompt carries them after the member contract, and `local prepare` copies those
     of the local runtime into the run's contract directory, so the contract never names a
     runtime. The provider check fails on a file that is missing, is not text or leaves the
     directory; an extension cannot add them.
   - **notes** (`notes`): how the runtime does what a skill asks of it, as topics (a lower case
     name of at most 32 characters, up to 16) with one line of plain text each (at most 2000
     characters), for example `spawn` (how a lead starts a member), `session-model`,
     `exploration`, `skills-dir`, `identity` and `commands`. `qargi provider notes TOPIC` prints
     one for the project's local runtime, so the skills point at a topic and never name a
     runtime's tools. Say in a note what is verified and what is assumed. An extension cannot add
     notes.
   - **dispatch** and **barrier**: the command to run (an argv array, never a shell string), how
     the prompt reaches it, which environment variables it may see, and how a read-only member
     is held (`hook`, `sandbox-args`, `adapter` or `none`).

   ```json
   {"schema": 2, "kind": "provider", "provider": "fakecli", "family": null, "surface": "local",
    "description": "fakecli, a command-line model runner",
    "models": {"pattern": "^fake-.+$", "effort": null,
               "tiers": {"*": {"model": "fake-1", "alias": null, "verified_on": null, "source": "fakecli --list-models"}}},
    "capabilities": {"skills": {"value": "yes"}},
    "resources": {"skills": {"project_dir": ".fake/skills", "items": "dir-per-item", "entry": "SKILL.md",
                             "format": "skill-md", "link": {"project": "dir-symlink", "user": "none"}}},
    "agents": null,
    "dispatch": {"mode": "command", "argv": ["fakecli", "run", "--model", "{model}"],
                 "class_argv": {"read-only": ["--sandbox", "read-only"]}, "prompt": {"via": "stdin"},
                 "cwd": "{clone}", "env_pass": ["FAKECLI_API_KEY"], "timeout_s": 1800, "output": {"format": "text"}},
    "barrier": {"kind": "sandbox-args"},
    "session": {"render_target": "fakecli"}}
   ```

   `session.render_target` is the name `qargi packs apply --target` takes for the runtime; without
   it qargi makes no render of the project's skills for it, so there is nothing to link.
   `qargi provider show claude-code` is a runtime with agent files, a hook barrier and
   in-session dispatch; `lib/providers/schema-2.json` is the format.
3. `qargi provider check fakecli` validates it and runs the hermetic cases; `qargi provider seal
   fakecli` approves it as it is; run `check` again to record what is verified. A capability
   counts only when it is claimed and verified. For what no hermetic case can show, such as an
   operating-system sandbox that really holds, `qargi provider attest` records a check you ran,
   asked each time.
4. Point a project at it: `qargi project set P models.provider.local fakecli` (a role's stored
   `model` that does not match the runtime's `pattern` makes it refuse, naming each role; start
   the project with `project attach --provider-local fakecli`, or edit the answers file and
   `project init P --answers FILE --force`). Render its skills
   with `qargi packs apply --target fakecli P` and link them with `qargi project link P`. For a task,
   `qargi local prepare ...` followed by `qargi local run RUN --dry-run` shows the exact command, and
   `qargi local run RUN` runs it.

A pack holds text only: scripts you can read, never a compiled program, an archive or a symlink. A
pack with a script (a renderer, an adapter) needs `--approve-exec` naming it when you seal or import
it, and that script runs with your rights, so read it first. The vendor CLI itself is installed by you
and only named in the definition. To share a runtime, hand over the directory: `qargi provider
import DIR` shows whoever imports it the same review.

## Adding a runtime to qargi itself

A shipped runtime is reviewed data and code in this repository.

1. Write `lib/providers/NAME.json` to schema 2 (`qargi provider show claude-code` is the example),
   and the model catalog it shares in `lib/providers/catalogs/FAMILY.json`. Give every model id the
   `verified_on` date and `source` from the vendor's own current model list; never write an id from
   memory. Set each capability and leave `verified_on` null where you have not tested it.
2. If it needs code, write the adapter, `lib/providers/NAME/adapter`, and list its verbs in
   `adapter_verbs` (`"adapter": null` for a definition that is data only). Implement only those
   verbs; the others exit 3.
3. Add a stub transport and fixtures under `tests/providers/NAME/` and run
   `bash tests/conformance.sh NAME` until it is clean.
4. Run `qargi provider check NAME` until it is clean, and read what it says degrades.
5. If the read-only barrier is not supported on a surface, say so in the definition. A person accepts
   it per project with `qargi provider accept`; do not default it on.
6. Add a CHANGELOG entry, and run one scratch session on the real runtime with the owner's approval
   before relying on any unverified capability.
