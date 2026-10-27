# User-visible changes

The checklist for a change that users can see. A change is complete only when all of it is in the same commit.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- [ ] A changelog entry in the project's format.
- [ ] Every document that describes the behaviour is updated: manual page, help text, README or docs page, completion.
- [ ] Examples use only the approved example values.
- [ ] The error and refusal messages are tested and name what to do next.
- [ ] Anything that changes stored data or configuration states how an existing installation migrates, or that nothing needs to.
- [ ] The new behaviour is covered by a test that would fail without the change.

### Project specifics

<Fill in from: the contributing guide: which docs are generated, which are hand-kept, the changelog numbering rule.>
