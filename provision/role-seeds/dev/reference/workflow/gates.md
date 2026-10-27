# Gates

How to choose and run checks, and how to read their verdicts. The profile is the single source of which gates run; this file explains them.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- Run the narrowest check while iterating and the full set before reporting.
- Trust only a verdict line the check prints (an exit status, a PASS/FAIL line, a count against an expected total). A log that ends without one is a failure.
- Run long checks detached with their output in a log and poll the log; never wait on a process by matching its command line.
- A gate the profile marks coordinator-only is reported "not run", not skipped silently.
- When a check fails on the untouched baseline, report it as an environment or baseline problem with the output; do not mask it.
- Record durable timing and setup facts in the memory store as recipes (one fact per note, with its check).

### Project specifics

| Changed path | Check | Verdict line |
|---|---|---|
| <glob> | <command> | <what a pass looks like> |

<Fill in from: the profile and the project's Makefile, CI workflows and test README.>
