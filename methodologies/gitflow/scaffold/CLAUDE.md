# {{project}}

## Commands

- Whole test suite: `{{test_command}}`. Run it once after a set of related changes is merged, not after every edit.
- While working on a task, run only the check that covers what you changed.

## Rules

- Branches follow git-flow: `master` (releases, tagged), `develop` (integration), feature branches merged into `develop` with `--no-ff`, `release/<version>` from `develop`, `hotfix/<version>` from `master`. Never commit to `master` or `develop` directly except by merging a branch.
- Every user-visible change gets a changelog entry under `[Unreleased]`, in the same commit.
- No private names (hosts, users, home paths, secrets) in files or commit messages.
