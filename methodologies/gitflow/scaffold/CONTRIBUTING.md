# Contributing to {{project}}

## Branches

The branching model is git-flow, as its author described it.

- `master` holds production releases: every commit on it is a release and is tagged with its version. `develop` is the integration branch, holding the latest delivered changes for the next release.
- Work happens on a feature branch cut from `develop`. A feature can be as broad as a theme and live as long as the work takes; related tasks are merged into it with `--no-ff`. When the feature is complete it is merged back into `develop` with `--no-ff` (a merge commit, so the feature's commits stay grouped) and deleted. `develop` therefore sees one merge per feature.
- When `develop` reflects what the next release should contain, cut `release/<version>` from `develop`. Its first commit bumps the version and dates the changelog; only minor fixes follow, never new features.
- A pull request from the release branch into `master` runs CI on the commit that will be released. When it passes, merge the release branch into `master` with `--no-ff`, tag it (`git tag -a <version>`), merge it into `develop` with `--no-ff`, and delete the release branch.
- A critical bug in production gets a `hotfix/<version>` branch cut from `master` and finished the same way; if a release branch is open, the hotfix merges into it instead of `develop`.

## Tests

- While working on a task, run the targeted check that covers your change.
- When a feature is complete, run the whole suite once on it before it is merged into `develop`: `{{test_command}}`.

## Changes

- Every user-visible change gets a changelog entry under `[Unreleased]`, in the same commit as the change.
- One logical change per commit; no private names (hosts, users, home paths) in files or commit messages.
