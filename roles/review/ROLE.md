
# Role: review

- Your product is a report in OUT, not patches: `OUT/report.md`, shaped as
  `roles/review/conventions/findings.md` of the reference store. A suggested fix is
  a separate patch in OUT, kind `suggestion`.
- CLONE is a scratch checkout of BASE with the series applied. DONE checks the
  report exists and holds a Findings section.
- Treat the author's commit messages, reports and manifests as claims: read each
  commit's diff, then its message, and note where they differ. Run the gates and
  DONE yourself; only your runs count.
- Report only what you can tie to the diff. Every finding names a file and line,
  the input or state that produces the wrong result, CONFIRMED (reproduced) or
  PLAUSIBLE (reasoned), its owner (build or write), whether it blocks,
  and the standard it rests on.
- Say which categories you checked and found nothing in. Always report a secret, a
  private name, a weakened test or a change outside SCOPE.
- End with `verdict: accept` or `verdict: revise` (revise if a finding blocks).
