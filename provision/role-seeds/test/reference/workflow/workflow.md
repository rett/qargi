# Test workflow

The steps of one test task and the definition of done.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

1. **Orient.** Read the task, DONE, SCOPE and profile; load the indexes and the files the task needs; read the test README and an existing test of the same kind.
2. **Baseline.** Run the suite (or the part you will touch) on BASE and note what is green, red or skipped before you change anything.
3. **Find the gap.** For new coverage, list the behaviours and error paths the code has and the tests do not; pick the ones the task names.
4. **Write the test** in the project's style, beside the code it covers.
5. **Watch it fail** against the missing or deliberately broken behaviour, then pass against the real code.
6. **Prove it is stable:** run it three times in a row and in the project's parallel or randomised mode.
7. **Run the suite** for the touched packages and DONE; quote verdict lines and counts.
8. **Commit** each test with its helper or fixture change, reasoning in the body.
9. **Report** per the contract, with the fail-then-pass evidence and the flakiness runs.

### Triaging a failing or flaky test
1. Reproduce it: same command, then in isolation, then with the order or parallelism changed.
2. Classify: shared state or leaked fixture, ordering, time or timezone, resource limits, environment (user, locale, tools), or a real defect.
3. Fix the cause in the test or helper; if the cause is a product defect, report it and stop.
4. Confirm with repeated runs, not one.

Done means: DONE passes, the new tests failed for the right reason before they passed, three consecutive runs agree, and nothing was skipped or weakened.

### Project specifics

<Fill in from: the test README and CI configuration: how the suite is run, its modes (parallel, race, tags) and its duration.>
