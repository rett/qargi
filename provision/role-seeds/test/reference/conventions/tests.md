# Test conventions

How tests are written and organised.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- Name a test for the behaviour it proves; one behaviour per test, or a table of cases with named rows.
- Arrange, act, assert, in that order; assert on observable behaviour, not on internal calls.
- Cover the error paths with the success path: bad input, missing argument, refusal, empty input, boundary values, a closed or empty input stream, a "no" to a prompt.
- Use the project's helpers for sandboxes, time, I/O and fake commands; do not build your own beside them.
- Golden and fixture files change only for the behaviour under test; regenerate narrowly and review the diff.
- Keep a test fast; mark one that needs privileges, the network or a long time the way the project marks them.
- A test that needs the process environment or a global registry declares that it cannot run in parallel.

### Project specifics

<Fill in from: the test README and helpers.>
