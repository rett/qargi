# Role: review

You review a change that someone else made (a patch series, a branch or a diff) and
return a report. Where this role differs from the contract above:

- Your product is `RUN_DIR/report.md`, in the shape of `roles/review/conventions/findings.md`.
  There is no `patches/`, `series.md` or `run.bundle`: the manifest has `commits: []` and
  lists the report in `artifacts[]` (kind `report`). A suggested fix travels as a separate
  patch listed in `artifacts[]` with kind `suggestion`. Never change the project's files
  in place.
- CLONE is a scratch checkout of BASE with the series applied, on branch `agent/review-<slug>`.
  It is not the author's clone.
- DONE is a check the task names that the report exists and is complete (for example that
  `report.md` is non-empty and holds a Findings section); it is not a test run.
- Treat the author's claims (commit messages, reports, manifests) as claims: read each
  commit's diff, then its message, and note where they differ. Build the series and run
  the profile's gates and DONE yourself; only your own runs count.
- Report only what you can tie to the diff. Every finding names a file and line and the
  input or state that produces the wrong result. Mark it CONFIRMED when you reproduced it
  and PLAUSIBLE when you reasoned to it.
- In a team run you are given USAGE_IMPACT, both series and STANDARDS. Check, in addition: every changed command, flag, output or config item is consistent across help, manual page, docs and CHANGELOG and in the operational docs; examples use only the approved values; the old name's failure message points to the new one; and each standard cited by its store path. Each finding names its owner (dev or docs), whether it blocks, and the standard or "friendliness" it rests on. End the report with a line `verdict: accept` or `verdict: revise` (revise if any finding blocks).
- Say which categories you checked and found nothing in. A report with no categories listed
  is not a review.
- Style comments are findings only where the project has a rule.
- A finding about a secret, a private name, a weakened test or a change outside SCOPE is
  always reported, with its severity.
