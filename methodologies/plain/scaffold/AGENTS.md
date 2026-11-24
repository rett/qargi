# {{project}}

Instructions for coding agents and contributors. `README.md` describes the project and `CONTRIBUTING.md` its workflow.

## Development environment

This project holds documents and builds nothing, so there is nothing to install and no test suite. The list below is the specification; any agent or person sets a checkout up with it.

- Prerequisites: git, and whatever the check of a task needs (a Markdown linter, a link checker): the task names it, and when the project adopts one for good it is added to this list.
- Install or update everything: nothing is installed yet. Add the command here when a tool is adopted, and make it idempotent.
- Verify a checkout: `git status` shows a clean work tree on a branch cut from `main`.
- Checks: the check of a task is given with the task and run on the document it changes; there is no whole-project suite.
- When the project needs a new tool, add it to this list in the same change.

## Rules

- `main` holds the documents; work goes on a branch `agent/<slug>` and is merged into `main` with `--no-ff`. Never commit to `main` directly except by merging a branch.
- Change only the paths the task names.
- No private names (hosts, users, home paths, secrets) in files or commit messages.
