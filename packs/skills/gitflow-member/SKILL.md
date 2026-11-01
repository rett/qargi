---
name: gitflow-member
description: Your part of a git-flow project as a member: work on agent/<slug> from the BASE you were given, leave the long-lived branches and merges to the lead, and run only the checks that cover your change.
---
# Git-flow, the member's part

## The model in two lines
- `master` holds tagged releases; `develop` is the integration branch.
- The lead merges `feature/*`, `release/*` and `hotfix/*` branches with `--no-ff`. You do not.

## Your branch
- Work on `agent/<slug>`, created from the BASE named in your task (usually `feature/<name>`).
- Record BASE's sha at the start (`git rev-parse BASE`); the report and patches are measured from it.

## Never
- Commit to, merge into, rebase or reset `develop`, `master`, `release/*`, `hotfix/*` or BASE.
- Run merge, pull, push or tag. Do not use `git stash` either: set work aside in a WIP commit.

## BASE moved, or conflicts
- Do not rebase or merge to catch up. Report that BASE moved (old and new sha) or which files conflict. The lead syncs.

## Checks
- Run the DONE check and the gates for the paths you touched, nothing wider.
- The one whole-suite run per feature is the lead's. If DONE itself is the suite, run it and say so.

## Commits
- One logical change per commit. The message says what changed and why; add a body.
- Stay inside SCOPE. A change you need outside it goes in the report, not in your commit.

## Releases and hotfixes
- `VERSION`, changelog dates and tags belong to the lead. Leave them alone.
