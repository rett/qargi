# Test conventions

Test layout, isolation, determinism and what a test must never touch.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- A test lives next to the code it covers and follows the project's layout and helpers.
- A test names the behaviour it proves, not the function it calls.
- A test is deterministic: no real network, no wall-clock sleeps, no dependence on order, locale, time zone or the machine it runs on; inject clocks, randomness and I/O.
- A test creates its own state in a temporary location and removes it; it never reads or writes the developer's home, the real configuration, or a production path.
- Cover the error paths with the success path: bad input, missing argument, refusal, empty and boundary values.
- A fixture or golden file changes only for the behaviour under change; regenerate narrowly and review the diff.
- A flaky test is a bug in the test or the code: find the cause, never add a retry or a skip.

### Project specifics

<Fill in from: the test README and helpers: sandboxing helpers, parallelism rules, golden file tooling, anything a test must never read from the machine.>
