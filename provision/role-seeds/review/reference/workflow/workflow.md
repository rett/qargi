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
6. **Verify each finding** before it goes in the report: reproduce it or build the failing input; drop what you cannot tie to the diff; mark what you only reasoned to as PLAUSIBLE.
7. **Report** in the format of `conventions/findings.md`, most severe first, with the categories that came up empty.

Done: the report exists, every finding is verified or marked PLAUSIBLE, the gates you ran are quoted verbatim, and the categories checked are listed.

### Project specifics

<Fill in from: the repository's review and merge practice: who reviews what, second-model review, required approvals.>
