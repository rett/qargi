---
name: review-findings
description: How a reviewer writes findings: severity high, medium or low, file:line, defect, failure scenario, evidence, a closing verdict line, no patches.
---
# Writing review findings

- List findings from most to least severe: `high`, `medium` or `low`, said on each.
- Each finding has:
  - `file:line` of the defect;
  - the defect in one sentence;
  - a concrete failure scenario: the input or sequence of events that goes wrong, and what the user sees;
  - the evidence: run it, or trace it and quote the lines; say if you only reasoned.
- Leave out style nits unless the task asks for them.
- Report only: write no patch and change no file; show a suggested fix as a fenced diff in the report.
- No findings: say so, and list what you checked under `# Checked`. The last line is `verdict: accept` or `verdict: revise`.
