# Rules

Binding rules for review work. The agent contract holds the universal ones.

Kind: rule
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- A review is read-only: do not edit, commit to or push the project; work in a scratch checkout.
- Evidence over opinion: every finding has a location, a scenario and, where possible, a reproduction.
- Re-run, do not recall: build, tests and gates are run by you on the series as submitted.
- Separate what you know from what you suspect: CONFIRMED and PLAUSIBLE are different claims.
- Do not report the same defect twice under different names; do not pad with nits.
- Do not verify the author's work by reading the author's summary first; read the diff, then the summary, and note where they differ.
- A finding about scope creep, a weakened test, a secret or a private name is always reported.
- Do not propose or record planned work; findings concern the change under review.

### Project specifics

<Fill in from: the repository's review rules and what the maintainer refuses to merge.>
