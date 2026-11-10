# Findings format

Kind: convention
Applies to: any
Sources: qargi seed

## Contents

### Report
`report.md`, in this order:
1. **`# Findings`,** most severe first. No findings: say so.
2. **`# Checked`:** the gates and checks you ran with their exit status and verdict lines verbatim, the categories you checked with nothing found (one line each), and what you only read.
3. **Noticed, not acted on,** at the end of `# Checked`: observations outside the change.
4. **The last line:** `verdict: accept` or `verdict: revise`. Revise if a finding of severity high blocks, or a medium one does.

### One finding
**Title**, **severity** (`high`, `medium` or `low`), **where** (`path:line`), **what is wrong** in a sentence, **the evidence** (the input or state and the wrong result; the failing command or test if you built one; say so when you only reasoned), **suggested fix** as a fenced diff, only when it is not obvious.

### Severity
- **high:** wrong results, data loss, a security or privacy problem, a broken build or gate, a committed secret or private name.
- **medium:** a defect in a less common path, a missing error check, a test that cannot fail, a regression risk in neighbouring code.
- **low:** an inconsistency, a confusing message, a missing doc or changelog line.
Style preferences are not findings unless the project has a rule.

### Project specifics

<Fill in from: the maintainer's review preferences, if stated.>
