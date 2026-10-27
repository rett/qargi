# Commit conventions

Kind: convention
Applies to: any
Sources: dev-agent seed

## Contents

- Subject: imperative, specific, about 72 characters or fewer, no trailing period. Body: what changed, why, the limits of the change, wrapped near 72-80 columns.
- Each commit builds and passes its own checks where feasible, so the series applies one commit at a time.
- No attribution trailer or generated-by line unless the profile requires one; check with `git interpret-trailers --parse`.
- No private names, secrets or real device output in a message; examples come from the approved table.

### Project specifics

<Fill in from: `git log` and the contributing guide: subject prefixes in use, merge message shapes, rules about trailers. Count, do not guess.>
