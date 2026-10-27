# Commit conventions

The shape of a commit and its message. The contract holds the rules on committing as you go and never squashing.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- One logical change per commit; its tests, docs and changelog entry are in it.
- Subject: imperative, specific, about 72 characters or fewer, no trailing period.
- Body: what changed and why, the limits of the change and what follows from it; wrap near 72-80 columns. The reasoning belongs here because the context is lost if it is not written when the change is made.
- Each commit builds and passes its own checks where feasible, so the series applies one commit at a time.
- No attribution trailer or generated-by line unless the profile requires one; check with `git interpret-trailers --parse`.
- No private names, secrets or real device output in a message; examples come from the approved table.
- Do not amend or reorder commits that exist; add a new one.

### Project specifics

<Fill in from: `git log` of the repository and its contributing guide: subject prefixes in use, merge message shapes, rules about trailers. Count, do not guess.>
