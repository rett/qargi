# Test checklist

Kind: review
Applies to: any
Sources: qargi seed

## Contents

- [ ] Each new test failed for the right reason before it passed (evidence in `gates[]`).
- [ ] The stability runs and the project's parallel or randomised mode agree.
- [ ] No sleep, retry, skip, widened tolerance or deleted assertion was used to get green.
- [ ] The test cleans up and touches nothing outside its sandbox.
- [ ] A correct refactor of the code would not break the test (no coupling to internals).
- [ ] Error paths and boundaries are covered; failure messages name expected and actual.
- [ ] Production code is unchanged unless the task said otherwise.
- [ ] The report says what is covered now that was not before, with counts.

### Project specifics

<Fill in from: past test reviews on this project.>
