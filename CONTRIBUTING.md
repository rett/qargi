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

`bin/dev-agent` is the single command; `lib/` holds the scripts behind it;
`skills/dev-*` are the skills (each a short guide that calls the command);
`agents/` the local subagent; `provision/` the resource and memory templates;
`examples/` sample repository profiles.

## Tests

`tests/run.sh` runs everything (reconciler, project validator, local never-push barrier,
role seeds, shellcheck). It needs no API access and no private data.

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
