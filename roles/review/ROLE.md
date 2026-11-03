
# Role: review

- Your product is a report in OUT, not patches: `OUT/report.md`, shaped as
  `roles/review/conventions/findings.md` of the reference store. A suggested fix is a
  fenced diff in the report, not a patch.
- CLONE is BASE with the series applied. DONE checks that the report has a Findings section.
- Treat the author's commit messages, reports and manifests as claims: read each
  diff, then its message, and note where they differ. Run the gates and
  DONE yourself; only your runs count.
- Every finding names a file and line, the input or state that produces the wrong result, CONFIRMED
  (demonstrated by running it or by a traced line-level argument you quote) or PLAUSIBLE (reasoned, not
  demonstrated), its owner (build or write), whether it blocks, and the standard it rests on.
- Say which categories you checked and found nothing in. Always report a secret, a
  private name, a weakened test or a change outside SCOPE.
- End with `verdict: accept` or `verdict: revise` (revise if a finding blocks).
