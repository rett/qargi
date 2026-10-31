# Contributing to {{project}}

## Branches

- `master` holds released code and is tagged for each release. `develop` holds the next release's work.
- A release branch, `feature/<version>` (for example `feature/{{version}}`), is cut from `develop`. Work is done on short-lived task branches and merged into the release branch, one task at a time.
- When the release is ready, the release branch gets the dated changelog and the version, then a pull request into `develop`. When CI passes it is merged into `develop`, then `master`, and tagged.

## Tests

- While working on a task, run the targeted check that covers your change.
- After a set of related changes is merged into the release branch, run the whole suite once: `{{test_command}}`.

## Changes

- Every user-visible change gets a changelog entry under `[Unreleased]`, in the same commit as the change.
- One logical change per commit; no private names (hosts, users, home paths) in files or commit messages.
