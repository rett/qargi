# Test conventions

Kind: convention
Applies to: any
Sources: dev-agent seed

## Contents

- Put the test at the lowest layer that observes the behaviour: a unit test for logic, an integration test for a boundary, an end-to-end test only for what nothing lower can show.
- Name a test for the behaviour it proves; one behaviour per test, or a table of cases with named rows. Arrange, act, assert; assert on observable behaviour, not on internal calls.
- A failure message names the expected and the actual value and the input that produced them.
- Determinism: no real network, wall-clock sleeps, dependence on order, locale or time zone, or on the machine; inject time, randomness and I/O.
- Isolation: a test makes its own state in a temporary location, cleans it up, and never reads or writes a real home, configuration or production path.
- Cover the error paths with the success path: bad input, missing argument, refusal, empty input, boundary values, a closed input stream, a "no" to a prompt.
- A golden or fixture file changes only for the behaviour under change; regenerate narrowly and review the diff.
- A flaky test is a bug in the test or the code: find the cause (shared state, time, ordering, environment); never add a retry or a skip.
- Use the project's helpers for sandboxes, time, I/O and fake commands; do not build your own beside them. Mark a test that needs privileges, the network, a long time, the process environment or a global registry the way the project does.

### Project specifics

<Fill in from: the test README and helpers.>
