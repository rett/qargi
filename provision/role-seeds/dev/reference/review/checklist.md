# Self-review checklist

What to check on your own work before reporting. The coordinator checks the same things again.

Kind: review
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- [ ] The diff contains only what the task needs: no stray files, formatting churn, debug output or unrelated edits.
- [ ] Every touched path is inside SCOPE; every file is accounted for in the report.
- [ ] Tests were added or changed for the behaviour, and one of them fails without the change.
- [ ] DONE and every required gate were run on the final commit and their verdict lines are quoted verbatim.
- [ ] No test or check was weakened, skipped or deleted.
- [ ] No secret, token, private name or real device output in any file or message; examples are approved ones.
- [ ] Generated files are regenerated, not hand-edited.
- [ ] Docs and the changelog changed with the code that needs them, in the same commit.
- [ ] Each commit has a body that says why; the series applies cleanly on BASE (`git am --3way`) and each patch builds alone where feasible.
- [ ] The report separates deviations from "noticed, not acted on", and proposes reference updates instead of editing the store.

### Project specifics

<Fill in from: past reviews. The findings that recur on this project, one per bullet, each with its source.>
