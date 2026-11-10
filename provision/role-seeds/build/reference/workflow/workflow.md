# Workflow

Kind: workflow
Applies to: any
Sources: qargi seed

## Contents

The order of work (orient, baseline, implement, check, commit as you go, report) is in the contract. Load only the notes the task needs, and propose reference updates in the report instead of editing the store.

### Definition of done, by kind of change
- **Bug fix:** a test that failed before and passes now; the cause is fixed, not the symptom; neighbouring code with the same flaw is named in the report.
- **Feature:** behaviour, error paths and edge cases are tested; user-visible text, docs and changelog change in the same commit.
- **Refactor:** behaviour is unchanged and the existing tests pass untouched; if a test had to change, say why.
- **Docs or tests only:** no production code changed; the relevant checks pass.
- **Dependency or tool bump:** pinned the way the project pins others; the full gates pass; lock or vendor files are in the same commit.

### Project specifics

<Fill in from: the development README and the release and branching docs: branch naming, changelog format, anything a task must follow.>
