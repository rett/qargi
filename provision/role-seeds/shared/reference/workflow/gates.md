# Gates

Kind: workflow
Applies to: any
Sources: qargi seed

## Contents

- The profile is the single source of which gates run for which paths; this note explains how to run them and read their verdicts.
- Run the narrowest check while iterating and the full set before reporting.
- Trust only a verdict line the check prints (an exit status, a PASS/FAIL line, a count against an expected total). A log that ends without one is a failure; "no test files" or "0 run" is not a pass.
- Start long checks through the runtime background facility; prefer completion or bounded waits over repeated log polling, and record the exit status. Never wait by matching a process command line.
- A gate the profile marks coordinator-only is reported "not run", never skipped silently.
- A check that fails on the untouched baseline is reported as a baseline problem with its output, and is not masked.
- Run the modes CI runs for the paths you touched (parallel, race detector, build tags, randomised order).
- Record durable timing and setup facts in the memory store as recipes.

### Project specifics

| Changed path | Check | Verdict line |
|---|---|---|
| <glob> | <command> | <what a pass looks like> |

<Fill in from: the profile, the Makefile, the CI workflows and the test README.>
