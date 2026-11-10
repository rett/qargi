# Development

Changing qargi itself.

- [Architecture](architecture.md): where qargi keeps each kind of record, how the code is layered, the life of a run, what is checked and what is advice, and which parts are data. Read it first to find where a change belongs.
- [CONTRIBUTING.md](../../CONTRIBUTING.md): branching (git-flow), layout, tests and the suite, changing the canon, versioning, changes and the changelog, adding a runtime with no code, adding a runtime to qargi itself. It is the workflow a change follows from branch to release.
- [AGENTS.md](../../AGENTS.md): the development environment for coding agents and contributors. It lists the tools to install, the targets that set a checkout up and check it, and how to run the tests.
- The command line is described once, in `lib/commands.py`; see [Help, manual page and completion](../reference/README.md#help-manual-page-and-completion) for what is generated from it. That page tells you what to regenerate after you add a command, a verb or a flag.
- Running a branch checkout: [Running a branch checkout](../install-and-upgrade/README.md#running-a-branch-checkout). It explains why a checkout other than the installed copy keeps its data in its own `.qargi/` directory, and how to test the guard or the hooks from it.

To set up a checkout of this repository for development, preview with `make -n bootstrap`, install with `make bootstrap` and verify with `make doctor`; see `AGENTS.md`, Development environment.
