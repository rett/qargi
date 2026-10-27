# Findings format

Kind: convention
Applies to: any
Sources: dev-agent seed

## Contents

### Report
1. **Verdict** in one line and the count by severity: *not ready* if any High, *ready with changes* if any Medium, otherwise *ready*.
2. **Gates run,** verdict lines verbatim.
3. **Findings,** most severe first.
4. **Categories checked with nothing found,** one line each.
5. **Noticed, not acted on:** observations outside the change.

### One finding
**Title**, **severity**, **confidence** (CONFIRMED or PLAUSIBLE), **where** (`path:line`), **what is wrong** in a sentence, **scenario** (the input or state and the wrong result; a failing command or test if you built one), **suggested fix** only when it is not obvious.

### Severity
- **High:** wrong results, data loss, a security or privacy problem, a broken build or gate, a committed secret or private name.
- **Medium:** a defect in a less common path, a missing error check, a test that cannot fail, a regression risk in neighbouring code.
- **Low:** an inconsistency, a confusing message, a missing doc or changelog line.
Style preferences are not findings unless the project has a rule.

### Project specifics

<Fill in from: the maintainer's review preferences, if stated.>
