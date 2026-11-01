# Contributing

## Branching (git-flow)

- `master` holds released versions only; every release is a tag.
- `develop` is the integration branch.
- Work happens on `feature/<name>` branches started with
  `git flow feature start <name>` and finished with
  `git flow feature finish <name>` (merge into `develop`).
- A release is `git flow release start <version>`, final checks and the
  `VERSION` and `CHANGELOG.md` update on the release branch, then
  `git flow release finish <version>`. Fixes to a released version use
  `git flow hotfix`.
- Tags are the bare version number, for example `0.1.0`.

## Layout

`bin/qargi` is the single command; `lib/` holds the scripts behind it;
`skills/qargi-*` are the skills (each a short guide that calls the command; four of
them, `qargi-build`, `qargi-write`, `qargi-review` and `qargi-test`, define the
abilities); `agents/member.md` is the one member definition `qargi agent add`
renders under the names users choose; `provision/` the resource and memory
templates; `examples/` sample repository profiles; `packs/` the baseline packs shipped
with qargi (`baseline.json` and `skills/<name>/SKILL.md`).

To add a baseline pack, write `packs/skills/<name>/SKILL.md` with front matter of
two keys, `name` (the directory name) and `description`, and portable text that names
no qargi verb, then list it in `packs/baseline.json`. The packs test checks both: every
directory is listed and the reverse, and each pack passes the library's review.

## Tests

`tests/run.sh` runs everything (reconciler, project validator, local never-push barrier,
guard, members, the memory backends and their split/merge invariants, the role migration, role seeds, shellcheck). It needs no API access and no private data.

Test a branch from its own worktree with `bin/qargi`: once `install.sh --user` has recorded the installed copy it is a dev run with its own data under `.qargi/` (README, Running a branch checkout). To test the guard or the hooks, put `<worktree>/bin` first on `PATH`: members call `qargi __guard` from `PATH`, which is otherwise the installed copy.

## Changing the canon

The layout of memory stores is versioned (`canon/CANON.md`, `canon/layout.json`).
A change to it needs a new version, a migration in `lib/canon.py`, a simulation
run (`python3 tests/canon_sim.py KIND FIXTURE.jsonl`: plan, apply in memory,
plan again must be empty, check must pass) and a CHANGELOG entry.

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
`CHANGELOG.md` in the same commit. Shell scripts must pass
`shellcheck -S warning`. Commit messages state what changed and why; no
private hostnames, addresses, usernames, home paths or credentials appear in
the repository or its history.

## Adding a provider

1. Write `lib/providers/NAME.json` to the schema (`qargi provider show claude` is the example). Give every model id the `verified_on` date and `source` from the vendor's own current model list; never write an id from memory. Set each capability per surface and leave `verified_on` null where you have not tested it.
2. Write the adapter, `lib/providers/NAME/adapter` (or set `"adapter": null` for a descriptor that is data only). Implement only the verbs the descriptor supports; the others exit 3.
3. Add a stub transport and fixtures under `tests/providers/NAME/` and run `bash tests/conformance.sh NAME` until it is clean.
4. Run `qargi provider check NAME` until it is clean, and read what it says degrades.
5. If the read-only barrier is not supported on a surface, say so in the descriptor. A person accepts it per project with `qargi provider accept`; do not default it on.
6. Add a CHANGELOG entry, and run one scratch session on the real provider with the owner's approval before relying on any unverified capability.
