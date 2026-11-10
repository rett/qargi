# Review workflow

Kind: workflow
Applies to: any
Sources: qargi seed

## Contents

1. **Orient.** Read the task, BASE, SCOPE and the profile; load only the notes the review needs.
2. **Read the series in order:** each commit's diff, then its message, noting where they disagree.
3. **Apply** the patches to a scratch checkout of BASE (`git am --3way`); a patch that does not apply is itself a finding.
4. **Run** the build, the profile's gates for the touched paths and DONE yourself; only your own runs count.
5. **Review by dimension** (`review/checklist.md`).
6. **Verify each finding** before it goes in the report: reproduce it or build the failing input; drop what you cannot tie to the diff; say in the finding's evidence what you only reasoned to.
7. **Report** in the format of `conventions/findings.md`: `# Findings` most severe first, then `# Checked` with the categories that came up empty, and the last line `verdict: accept` or `verdict: revise`.

Done: the report exists, every finding is verified or says it is reasoned only, the gates you ran are quoted verbatim, the categories checked are listed, and the last line is the verdict.

### Project specifics

<Fill in from: the repository's review and merge practice: who reviews what, second-model review, required approvals.>
