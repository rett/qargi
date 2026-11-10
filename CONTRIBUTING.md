# Contributing

## Branching (git-flow)

- `master` holds released versions only; every release is a tag.
- `develop` is the integration branch.
- Work happens on `feature/<name>` branches, with every merge `--no-ff`. Use
  the `qargi feature` commands, which follow the git-flow model: `qargi feature
  start <name>`, `qargi feature merge <name> <branch>` for each verified task,
  and `qargi feature finish <name>` (merge into `develop`, after
  `qargi feature verify <name>` passed the whole suite).
- A release is `qargi release start <version>` (it prints a plan and a token; apply it with `--plan TOKEN --approved "..."`); the `VERSION` and
  `CHANGELOG.md` update is its first commit, then
  `qargi release verify <version>`, `qargi release push <version>` (the branch and a pull request, so CI
  runs on what will be released) and `qargi release finish <version>`. Fixes to a released version
  use `qargi release start <version> --hotfix` (planned and approved the same way).
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
templates; `examples/` sample repository profiles; `docs/` the documentation by topic (`README.md` links to each topic's `README.md`, and
`tests/test_docs_links.py` checks every relative link); `packs/` the baseline packs shipped
with qargi (`baseline.json` and `skills/<name>/SKILL.md`).

To add a baseline pack, write `packs/skills/<name>/SKILL.md` with front matter of
two keys, `name` (the directory name) and `description`, and portable text that names
no qargi verb, then list it in `packs/baseline.json`. The packs test checks both: every
directory is listed and the reverse, and each pack passes the library's review.

## Tests

`tests/run.sh` runs everything and needs no API access and no private data. `tests/suite.txt` is the inventory: one step per
line with its tier (`fast` or `full`), whether it may run beside others, its timeout, its time budget in seconds and,
optionally, the globs of the files it covers. A new `tests/test_*` file gets a line there, and the runner fails when a test
file is not listed or a listed file does not exist. The budget is the time the step takes on the reference machine; a step
that takes more than 1.5 times its budget is reported, and a budget only shrinks (a step that grew is split).

    bash tests/run.sh                  every step, as many at a time as there are CPUs (-j N; -j 1 is the serial run)
    bash tests/run.sh --tier fast      the fast tier: every area, about a minute
    bash tests/run.sh --only PATTERN   the steps whose command matches PATTERN (extended regular expression)
    bash tests/run.sh --shard 2/4 --durations tests/durations.txt   the second of four parts, balanced by the recorded durations (CI)
    bash tests/run.sh --tier fast --changed-from origin/develop     the fast tier plus the steps that cover the files changed since develop
    bash tests/run.sh --shard 2/4 --plan   print the plan of the four parts and the steps of the second, run nothing
    bash tests/run.sh --shuffle SEED --repeat 3   random order and repeats, to find a test that fails now and then

Tiers: `fast` is a quick run that has every area in it (about a minute); `full` steps run only in the whole run. `-j N` sets how many
steps run at once (default: the CPUs); the verdict is the same at every `-j`, and `-j 1` is the serial run. A step marked `serial` runs
alone after the others. A shard is one of K parts of the selected steps, dealt longest first to the least loaded part by the recorded
duration of a step (`--durations FILE`) or else its budget.

Adding a step: put the test in `tests/`, add a line to `tests/suite.txt` with its tier (`fast` only for a step of a few seconds
that covers an area the other fast steps do not), `par` unless it cannot run beside others, a timeout (several times the budget),
its budget (the seconds it takes on a loaded eight-CPU machine, measured with `bash tests/run.sh --only 'tests/test_x.sh'`; a budget
only shrinks, so a step that grew is split) and the `covers` globs of the files it tests. A pull request runs the fast tier and the
steps whose `covers` match the files it changed (or whose command names a changed file), so a `full` step without `covers` is
checked only in the whole run.

CI (`.github/workflows/test.yml`) runs the fast tier and the covered steps on a pull request into a branch other than master (the
label `full-suite` on the pull request runs the whole suite), and the whole suite in four shards on a push to develop, on a pull
request into master and on a manual run; there is no scheduled run. The time limit of a job is computed from the budgets, as the
comment in the workflow shows, and `tests/test_ci.py` fails when the limit falls below that, so budgets that grow past it show in
the same pull request.

`tests/durations.txt` has one line per step, `seconds command`, from a whole run; the CI shards are balanced by it, and
`tests/test_ci.py` fails when the four parts plan more than 1.3 times apart. Regenerate it when steps were added or their time
changed much, from a whole run on a machine with eight CPUs, and commit it:

    T=$(mktemp -d); mkdir $T/h; HOME=$T/h TMPDIR=$T bash tests/run.sh -j 8 --save-durations tests/durations.txt

A sharded run ends with `shard i/K: planned Ns, the steps took Ns together`, which shows how far the file is from the runs.

Each step runs in a session of its own with a fresh `HOME`, no standard input and only its output open, and fails when it
exceeds its timeout or leaves a process running. A step prints one block when it ends, so the output is in completion order and
never interleaved; the end of the output has the failed steps, the slowest ten and `total: Ns (passed|FAILED)`, and
`--enforce-budgets` makes a step over budget fail. The linter step runs shellcheck through `xargs`, all CPUs at once.

A test is safe to run next to other tests and next to another whole suite: it sources `tests/hermetic.sh` (a python test imports `hermetic`), which gives it a fresh HOME, TMPDIR, config and state, a fixed locale, time zone and umask, and git without the host's configuration, and it works only under `mktemp` directories, starts nothing it does not stop by pid (`spawn_bg`, `kill_bg`), waits for a condition with a deadline and not with a bare `sleep`, and binds port 0. `tests/test_hermetic.sh` runs `tests/hermetic_lint.py` over the tests and fails on a file that breaks one of its rules; a justified case carries `hermetic: allow RULE (reason)` on its line. The rules are `source` (the file sources `hermetic.sh` or imports `hermetic`), `tmp` (no literal `/tmp`, `/dev/shm` or `/run` path), `pgrep` (no `pkill`, `killall` or `pgrep -f`), `sleep` (no fixed wait outside a loop), `rm` (no `rm -r` of a directory the test did not make), `port` (no fixed TCP port), `lock` (no lock or socket outside the test's directory), `clock` (no difference of two clock readings compared with a constant) and `absent` (a grep that asserts something is absent needs a distinctive pattern: six or more characters, `-w` or `-x`, an anchor, or a character a temporary path does not hold, because a random temporary path in the output can contain a short token). `python3 tests/hermetic_lint.py` prints the findings.

`tests/test_legacy_lint.py` keeps code for earlier versions out of `lib/` (qargi keeps no backwards compatibility): it fails when a file there holds the phrase `older record`, `migrat` or `earlier version`, unless `tests/legacy-allowlist.txt` names the file and the phrase with a reason. That list only shrinks.

Prompt text is one paragraph per line: in `contract/`, `roles/`, `agents/` and `packs/skills/` a paragraph and a list item are each one physical line (a viewer narrower than a line wraps it whole), and `tests/test_prose_lint.py` fails on a line that continues the one before it or has trailing spaces.

Test a branch from its own worktree with `bin/qargi`: once `install.sh --user` has recorded the installed copy it is a dev run with its own data under `.qargi/` ([Running a branch checkout](docs/install-and-upgrade/README.md#running-a-branch-checkout)). To test the guard or the hooks, put `<worktree>/bin` first on `PATH`: members call `qargi __guard` from `PATH`, which is otherwise the installed copy.

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
