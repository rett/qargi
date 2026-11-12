# Development

Changing qargi itself.

- [Architecture](architecture.md): where qargi keeps each kind of record, how the code is layered, the life of a run, what is checked and what is advice, and which parts are data. Read it first to find where a change belongs.
- [CONTRIBUTING.md](../../CONTRIBUTING.md): branching (git-flow), layout, tests and the suite, changing the canon, versioning, changes and the changelog, adding a runtime with no code, adding a runtime to qargi itself. It is the workflow a change follows from branch to release.
- [AGENTS.md](../../AGENTS.md): the development environment for coding agents and contributors. It lists the tools to install, the targets that set a checkout up and check it, and how to run the tests.
- The command line is described once, in `lib/commands.py`; see [Help, manual page and completion](../reference/README.md#help-manual-page-and-completion) for what is generated from it. That page tells you what to regenerate after you add a command, a verb or a flag.
- Running a branch checkout: [Running a branch checkout](../install-and-upgrade/README.md#running-a-branch-checkout). It explains why a checkout other than the installed copy keeps its data in its own `.qargi/` directory, and how to test the guard or the hooks from it.

To set up a checkout of this repository for development, preview with `make -n bootstrap`, install with `make bootstrap` and verify with `make doctor`; see `AGENTS.md`, Development environment.

## Member checks

A lead can supply passing baseline evidence for the exact BASE of a member task. Reuse it only when the relevant inputs and check definitions match; cite its reference and provenance as context, not as a check the member ran. Otherwise run the smallest relevant check on the clean base. A suspected bug that needs a failing baseline also calls for a fresh check.

For each logical commit, run focused checks covering the change and the applicable gates before committing. After completing all required outcomes, run the task's DONE command; repeat checks after relevant changes or failures. Path and always gates still apply, coordinator-only gates remain the lead's responsibility, and the lead's whole-suite feature checkpoint is still required.

## Parking the main checkout

`qargi feature park` puts the main checkout on the parking branch at develop. Nonconflicting untracked runtime files can stay in the checkout. Parking refuses tracked changes, commits on the parking branch that develop lacks, and untracked or ignored files that would collide with the checkout.

After feature, release or hotfix finish moves develop, qargi tries to fast-forward the parking branch. If it cannot, the status line explains why and the parking branch may remain behind; a successful integration is still complete. Resolve the obstruction and park again when ready.
