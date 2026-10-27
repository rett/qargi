# Self-review checklist

Kind: review
Applies to: any
Sources: qargi seed

## Contents

- [ ] The diff holds only what the task needs: no stray files, formatting churn, debug output or unrelated edits; every touched path is inside SCOPE.
- [ ] A test covers the behaviour and one fails without the change; none was weakened, skipped or deleted.
- [ ] DONE and every required gate ran on the final commit; verdict lines are quoted verbatim.
- [ ] No secret, private name or real device output anywhere; examples are the approved ones.
- [ ] Generated files are regenerated; docs and changelog changed with the code that needs them.
- [ ] Each commit has a body that says why; the series applies cleanly on BASE (`git am --3way`).

### Project specifics

<Fill in from: past reviews. Findings that recur on this project, one per bullet, each with its source.>
