---
name: gitflow-member
description: Your part of a git-flow project as a member: work on agent/<slug> from the BASE you were given, leave the long-lived branches and merges to the lead, and run only the checks that cover your change.
---
# Git-flow, the member's part

## The model in brief
- `master` holds tagged releases; `develop` integrates. The lead merges `feature/*`, `release/*` and `hotfix/*` with `--no-ff`; you do not.

## Your branch
- Work on `agent/<slug>`, from BASE as your task names it (usually `feature/<name>`).
- Record BASE's sha at the start (`git rev-parse BASE`).

## Never
- Commit to, merge into, rebase or reset `develop`, `master`, `release/*`, `hotfix/*` or BASE.
- Run merge, pull, push, tag or `git stash`; set work aside in a WIP commit.

## BASE moved, or conflicts
- Do not rebase or merge to catch up: report that BASE moved (old and new sha) or which files conflict.

## Checks
- Run the DONE check and the gates for the paths you touched, nothing wider.
- The whole-suite run per feature is the lead's, unless DONE is the suite. A project may declare gates, which `feature verify` and `release verify` run in order, stopping at the first failure; also the lead's.

## Commits
- One logical change per commit. The message says what changed and why; add a body.
- Stay inside SCOPE; report a change you need outside it.
- The guard cuts a command at every ; && || | and newline, quotes included: write the message to a file and commit with `git commit -F FILE`; a qargi verb, push or tag in command-line text is refused.

## Releases and hotfixes
- `VERSION`, changelog dates and tags are the lead's.
