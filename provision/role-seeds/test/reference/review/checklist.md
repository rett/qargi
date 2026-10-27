# Test checklist

What to check on your own tests before reporting.

Kind: review
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- [ ] Each new test failed for the right reason before it passed (evidence quoted).
- [ ] Three consecutive runs and the project's parallel or randomised mode all agree.
- [ ] No sleep, retry, skip, tolerance widening or deleted assertion was used to get green.
- [ ] The test cleans up and touches nothing outside its sandbox.
- [ ] The test would still pass after a correct refactor of the code (no coupling to internals).
- [ ] Error paths and boundaries are covered, not only the success path.
- [ ] No secret, private name or real output in the test or its fixtures.
- [ ] Production code is unchanged unless the task said otherwise.
- [ ] The report states what is covered now that was not before, with counts.

### Project specifics

<Fill in from: past test reviews on this project.>
