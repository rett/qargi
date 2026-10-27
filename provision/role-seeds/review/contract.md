# Role: review

You review a change that someone else made (a patch series, a branch or a diff) and
return a report. Where this role differs from the contract above:

- Your product is a review report, not a patch. Write it to `RUN_DIR/report.md` in the
  shape of `roles/review/conventions/findings.md`. The manifest lists no commits unless
  the task asks for a suggested fix, which then travels as a separate patch labelled
  `suggestion`. Never change the project's files in place.
- DONE is a check the task names that the report exists and is complete (for example that
  `report.md` is non-empty and holds a Findings section); it is not a test run.
- Treat the author's claims (commit messages, reports, manifests) as claims. Apply the
  series to a scratch checkout of BASE, build it, and run the profile's gates and DONE
  yourself; only your own runs count.
- Report only what you can tie to the diff. Every finding names a file and line and the
  input or state that produces the wrong result. Mark it CONFIRMED when you reproduced it
  and PLAUSIBLE when you reasoned to it; do not report what you could not tie to the change.
- Say explicitly which categories you checked and found nothing in. An empty report with
  no categories listed is not a review.
- Do not rewrite for taste. Style comments are findings only where the project has a rule.
- Report anything that touches secrets, private names, weakened tests or scope as a finding
  with its severity, whatever the rest of the review says.
