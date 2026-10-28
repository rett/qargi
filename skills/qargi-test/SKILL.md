---
name: qargi-test
description: The test ability of a qargi member - write and repair a project's tests, prove them failing first and stable, and report how the suite behaves. Load it when a qargi task block says ABILITY test.
---

# Ability: test

You serve the test ability in this task (a member: the task block names it; a cloud agent: its role). The contract in
the qargi-task skill's `agent-contract.md` is the procedure; this is what the
ability adds.

- Change tests, test helpers and fixtures only; production code only when the task
  and SCOPE say so. A defect you find is reported, not fixed.
- Show each new test failing for the right reason before it passes, and record both
  runs in `gates[]` as `fail-first` and `pass` with their verdict lines.
- A test that fails because of a product defect is not skipped, weakened or deleted:
  stop with BLOCKED, the failing test and its output, and list the defect under
  "Noticed, not acted on".
- Prove stability with the project's repeat option (for example `go test -count=20`,
  or at least ten runs) and in its parallel or randomised mode; record them as
  `stability-<N>`. Never fix a flaky test with a retry, a longer sleep or a skip.
- Never touch real services, devices, a real home directory or production paths
  from a test; use the project's sandbox helpers and fakes.
- Report the suite's result with verdict lines and counts (run, passed, failed,
  skipped) and what the touched tests cover that they did not before. Known flaky
  tests are kept in the memory store under `roles/test/status/`.
