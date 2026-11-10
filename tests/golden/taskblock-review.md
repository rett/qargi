ROLE: review (class read-only)

ABILITY:

# Role: review

- Your product is a report in OUT, not patches: `OUT/report.md`, shaped as the output format says. A suggested
  fix is a fenced diff in the report, not a patch.
- CLONE is BASE with the series applied. DONE checks the report: Findings, its manifest, a closing verdict line.
- Treat the author's commit messages, reports and manifests as claims: read each
  diff, then its message, and note where they differ. Run the gates and
  DONE yourself; only your runs count.
- Every finding names a file and line, its severity (high, medium or low), the input or state that produces the
  wrong result, the evidence (run it, or trace it and quote the lines; say if you only reasoned), its
  owner (build or write), whether it blocks, and the standard it rests on.
- Under `# Checked`, say what you ran and which categories had nothing. Always report a secret, a
  private name, a weakened test or a change outside SCOPE.
- The last line is `verdict: accept` or `verdict: revise` (revise if a finding blocks).

TASK:
Add the flag --quiet to the tool.

It prints nothing on success.

DONE: bash tests/check.sh

PROFILE:
# Profile of fixrepo

Gates: `make test`.
Rule: no private names.

BASE: main
BASE_SHA: <BASE_SHA>
SCOPE: none
RUN_DIR: <RUN>
CLONE: <RUN>/clone
OUT: <RUN>/out
TMP: <TMP>
GIT: <RUN>/git
CONTRACT: <RUN>/contract
