# User-visible changes

Kind: convention
Applies to: any
Sources: qargi seed

## Contents

A change users can see is complete only when all of this is in the same commit:
- [ ] A changelog entry in the project's format.
- [ ] Every document that ships with the code and describes the behaviour: manual page, help text, README or docs page, completion. (Operational documentation published on a separate docs branch belongs to the docs role.)
- [ ] `usage_impact` in the manifest for every command, flag, output, config key or file a user sees or types that changed.
- [ ] Examples use only the approved example values.
- [ ] Error and refusal messages are tested and say what to do next.
- [ ] A change to stored data or configuration says how an existing installation migrates, or that nothing needs to.
- [ ] A test that would fail without the change.

### Project specifics

<Fill in from: the contributing guide: which docs are generated, which are hand-kept, the changelog numbering rule.>
