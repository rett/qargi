# Gates for tests

How to run the suite and read its verdicts.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- Run the narrow package or test while writing; run the whole relevant suite before reporting.
- A pass is a verdict the runner prints (exit status, a PASS line, counts against an expected total). "No test files" or "0 run" is not a pass.
- Run long suites detached with a log and poll it; never wait on a process by matching its command line.
- Know the project's modes (verbose, parallel, race detector, build tags, randomised order) and run the ones CI runs for the packages you touched.
- Record timings and setup needs in the memory store as recipes.

### Project specifics

| Scope | Command | Verdict line |
|---|---|---|
| <package or suite> | <command> | <what a pass looks like> |

<Fill in from: the profile, the Makefile and the CI workflows.>
