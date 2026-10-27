# Review workflow

The steps of one review and the definition of done.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

1. **Orient.** Read the task, BASE, SCOPE and the profile; load the indexes and the files the review needs.
2. **Read the series in order,** commit message first and then its diff, so each change is judged with its stated intent. Note every place the message and the diff disagree.
3. **Apply** the patches to a scratch checkout of BASE (`git am --3way`); a patch that does not apply is itself a finding.
4. **Run** the build, the profile's gates for the touched paths and DONE; run long checks detached and trust only verdict lines.
5. **Review by dimension** (`review/checklist.md`): correctness, tests, scope, security and privacy, compatibility and migration, docs and changelog, commit hygiene.
6. **Verify each finding** before it goes in the report: reproduce it, or build the failing input; drop what you cannot tie to the diff; downgrade what you only reasoned to.
7. **Report** in the format of `conventions/findings.md`, most severe first, with the categories that came up empty.

Done means: the report exists, every finding is verified or marked PLAUSIBLE, the gates you ran are quoted verbatim, and the categories checked are listed.

### Project specifics

<Fill in from: the repository's review and merge practice: who reviews what, second-model review rules, required approvals.>
