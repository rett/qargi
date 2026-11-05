---
name: review-findings
description: How a reviewer writes findings: severity order, file:line, defect, failure scenario, CONFIRMED or PLAUSIBLE, no patches.
---
# Writing review findings

- List findings from most to least severe, and say the severity on each.
- Each finding has:
  - `file:line` of the defect;
  - the defect in one sentence;
  - a concrete failure scenario: the input or sequence of events that goes wrong, and what the user sees;
  - a verdict: `CONFIRMED` (demonstrated by running it or by a traced line-level argument you quote) or `PLAUSIBLE` (reasoned, not demonstrated).
- Leave out style nits unless the task asks for them.
- Report only: write no patch and change no file; show a suggested fix as a fenced diff in the report.
- No findings: say so, and list what you checked.
