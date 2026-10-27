# Workflow

The lifecycle of one task and the definition of done for each kind of change.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

### Lifecycle
1. **Orient.** Read TASK, DONE, SCOPE and PROFILE; load `shared/INDEX.md` and this role's index, then only the files the task needs. Read the repository's own instructions.
2. **Baseline.** On a clean branch from BASE, build and run the checks for the paths you will touch. Know what is green before you change anything; a red baseline is reported, not fixed.
3. **Implement** the smallest change that satisfies the task, with its tests, docs and changelog entry.
4. **Check.** Run the gates for the touched paths while you work, and the always-gates before reporting. Run DONE verbatim.
5. **Commit as you go,** one logical change per commit, with the reasoning in the message body.
6. **Report.** DONE or BLOCKED, verdict lines verbatim, files with reasons, commit advice, deviations, noticed-not-acted-on, reference updates proposed.

### Definition of done, by kind of change
- **Bug fix:** a test that failed before and passes now; the cause is fixed, not the symptom; neighbouring code with the same flaw is named in the report.
- **Feature:** behaviour, error paths and edge cases are tested; user-visible text, docs and changelog are updated in the same commit.
- **Refactor:** behaviour is unchanged and the existing tests pass untouched; if a test had to change, say why.
- **Docs or tests only:** no production code changed; the relevant checks pass.
- **Dependency or tool bump:** the version is pinned the way the project pins others; the full gates pass; the lock or vendor files are committed with it.

### Project specifics

<Fill in from: the development README and the release and branching docs: branch naming, changelog format, release steps that touch a task.>
