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
- Review commit cohesion from the concrete changes and their dependencies. A logical change includes its supporting tests, documentation and changelog; keep meaningful buildable commit boundaries and one patch per actual commit. Reject semantically mixed work with evidence naming the independent changes or broken dependencies.
- Treat directory counts and patch size as review prompts requiring substantive cohesion review. Directory counts cannot establish semantic unrelatedness, and a warning is never source acceptance. Inspect the changes independently; do not manufacture a second commit merely to satisfy counts.
- Report only: write no patch and change no file; show a suggested fix as a fenced diff in the report.
- No findings: say so, and list what you checked under `# Checked`. The last line is `verdict: accept` or `verdict: revise`.
