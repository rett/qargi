# Test workflow

Kind: workflow
Applies to: any
Sources: qargi seed

## Contents

1. **Orient.** Read the task, DONE, SCOPE and profile; read the test README and an existing test of the same kind.
2. **Baseline.** Run the suite (or the part you will touch) on BASE and note what is green, red or skipped.
3. **Find the gap.** List the behaviours and error paths the code has and the tests do not; take the ones the task names.
4. **Write the test** in the project's style, beside the code it covers (`shared/conventions/tests.md`).
5. **Watch it fail** against the missing or deliberately broken behaviour, then pass against the real code.
6. **Prove it is stable:** repeat it (ten runs as the floor, or the project's repeat option) and in its parallel or randomised mode.
7. **Run the suite** for the touched packages and DONE; quote verdict lines and counts.
8. **Commit** each test with its helper or fixture change, reasoning in the body.

### Triaging a failing or flaky test
1. Reproduce: the same command, then in isolation, then with order or parallelism changed.
2. Classify: leaked state, ordering, time or time zone, resource limits, environment (user, locale, tools), or a real defect.
3. Fix the cause in the test or helper; if it is a product defect, report it and stop.
4. Confirm with repeated runs, not one.

Done: DONE passes, each new test failed for the right reason before it passed, the stability runs agree, and nothing was skipped or weakened.

### Project specifics

<Fill in from: the test README and CI configuration: how the suite runs, its modes and its duration.>
