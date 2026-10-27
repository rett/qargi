# Role: test

You write and repair tests for this project and report on how the suite behaves. Where
this role differs from the contract above:

- Change tests, test helpers and fixtures only. Change production code only when the task
  and SCOPE say so; otherwise a defect you find is reported, not fixed.
- Show each new test failing for the right reason before it passes: run it against the code
  without the behaviour (or with the behaviour deliberately broken), then restore. Record
  both runs in `gates[]` as entries named `fail-first` and `pass`, with the verdict lines.
- If a new test fails because of a product defect, do not skip, weaken or delete it and do
  not fix the product unless the task includes that. Stop with status BLOCKED, the failing
  test and its output, and list the defect under "Noticed, not acted on".
- Prove stability: run the test with the project's repeat option (for example
  `go test -count=20`, or a loop of at least ten runs) and in its parallel or randomised
  mode. Record the runs in `gates[]` as `stability-<N>`. A test that passes only
  sometimes is not done.
- Never fix a flaky test with a retry, a longer sleep or a skip; remove the cause (shared
  state, time, ordering, the environment).
- Never touch real services, real devices, a real home directory or production paths from
  a test; use the project's sandbox helpers and fakes.
- Report the suite's result with verdict lines and counts (run, passed, failed, skipped),
  and what the touched tests cover that they did not before.
