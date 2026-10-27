# Rules

Binding rules for test work. The agent contract holds the universal ones.

Kind: rule
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- A test must be able to fail: prove it by watching it fail for the right reason first.
- Never skip, disable, weaken or delete a test to get a green run; never widen a tolerance or an expected value to match wrong output without saying why.
- Determinism: no real network, wall-clock sleeps, dependence on order, locale or time zone, or on the machine; inject time, randomness and I/O.
- Isolation: a test makes its own state in a temporary location, cleans it up, and never reads or writes a real home, configuration or production path.
- A defect found by a test is reported with the failing test and output; it is not hidden by changing the test.
- No secret, token, private name or real device output in a test, fixture or golden file; use the approved example values.
- Do not couple a test to implementation details that a correct refactor would change.

### Project specifics

<Fill in from: the repository's test README and agent instructions.>
