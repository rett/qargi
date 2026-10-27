# Source map

Where test facts live in the repository.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

Read the test README and an existing test of the same kind before writing one; the CI workflow shows which modes actually run.

### Project specifics

| Question | Where |
|---|---|
| How are tests run and in which modes? | <test README, Makefile, CI workflow> |
| Which helpers sandbox paths, time and commands? | <helper package> |
| Where are fixtures and goldens, and how are they regenerated? | <directory, generator> |
| Which tests are slow or need privileges? | <notes> |
