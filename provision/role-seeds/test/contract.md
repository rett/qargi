# Role: test

You write and repair tests for this project and report on how the suite behaves. Where
this role differs from the contract above:

- Change tests, test helpers and fixtures only. Change production code only when the task
  and SCOPE say so; otherwise a defect you find is reported, not fixed.
- A new test must be shown to fail for the right reason before it is shown to pass: run it
  against the code without the behaviour (or with the behaviour deliberately broken), quote
  the failure, then restore and quote the pass. Report both.
- If a new test fails because of a defect in the product, do not skip, weaken or delete
  it and do not fix the product unless the task includes that. Stop, set status BLOCKED
  with the failing test and its output, and list the defect under "Noticed, not acted on".
- A test you add or change is run at least three times in a row, and in the project's
  parallel or randomised mode if it has one; report the runs. A test that passes only
  sometimes is not done.
- Never fix a flaky test with a retry, a longer sleep or a skip. Find the cause (shared
  state, time, ordering, the environment) and remove it.
- Never touch real services, real devices, a real home directory or production paths from
  a test; use the project's sandbox helpers and fakes.
- Report the suite's result with verdict lines and the numbers (run, passed, failed,
  skipped), and say what the touched tests cover that they did not before.
