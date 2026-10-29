# Workflow

Kind: workflow
Applies to: any
Sources: qargi seed

## Contents

### Lifecycle
1. **Orient.** Read TASK, DONE, SCOPE and PROFILE and the repository's own instructions; load only the notes the task needs.
2. **Baseline.** On a clean branch from BASE, run the checks for the paths you will touch. Know what is green first; a red baseline is reported, not fixed.
3. **Implement** the smallest change that satisfies the task, with its tests, docs and changelog entry.
4. **Check.** Run the gates for the touched paths while you work and the always-gates before reporting; run DONE verbatim.
5. **Commit as you go,** one logical change per commit, reasoning in the body.
6. **Report** per the contract, and propose reference updates instead of editing the store.

### Definition of done, by kind of change
- **Bug fix:** a test that failed before and passes now; the cause is fixed, not the symptom; neighbouring code with the same flaw is named in the report.
- **Feature:** behaviour, error paths and edge cases are tested; user-visible text, docs and changelog change in the same commit.
- **Refactor:** behaviour is unchanged and the existing tests pass untouched; if a test had to change, say why.
- **Docs or tests only:** no production code changed; the relevant checks pass.
- **Dependency or tool bump:** pinned the way the project pins others; the full gates pass; lock or vendor files are in the same commit.

### Project specifics

<Fill in from: the development README and the release and branching docs: branch naming, changelog format, anything a task must follow.>
