# Findings format

How a review report is written, so it can be acted on without a conversation.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

### Report shape
1. **Verdict** in one line: ready, ready with changes, or not ready, and the count of findings by severity.
2. **Gates run** with verdict lines verbatim.
3. **Findings**, most severe first.
4. **Categories checked with nothing found**, one line each.
5. **Noticed, not acted on:** observations outside the change.

### One finding
- **Title** in one line, **severity**, **confidence** (CONFIRMED or PLAUSIBLE).
- **Where:** `path:line`.
- **What is wrong,** in a sentence.
- **Scenario:** the input or state, and the wrong result. A failing command or test, if you built one.
- **Suggested fix,** in a sentence, only when it is not obvious.

### Severity
- **High:** wrong results, data loss, a security or privacy problem, a broken build or gate, a secret or private name committed.
- **Medium:** a defect in a less common path, a missing error check, a test that cannot fail, a regression risk in neighbouring code.
- **Low:** an inconsistency, a confusing message, a missing doc or changelog line.
Style preferences are not findings unless the project has a rule.

### Project specifics

<Fill in from: the maintainer's review preferences, if stated.>
