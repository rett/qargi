# Code conventions

How code is written so that a change reads like the code around it.

Kind: convention
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- Match the surrounding code: naming, structure, error handling, comment density and idiom. When in doubt, copy the nearest good example.
- Keep the diff minimal: no drive-by formatting, import reordering or renames in lines the task does not need.
- Handle every error the way the neighbours do; never discard one silently.
- Put an explanation where the code is not obvious (why, not what); delete comments that restate the code.
- No dead code, commented-out code, debugging output or TODO without an owner.
- Names say what a thing is for; a function does one thing; a new dependency needs a reason in the commit message.
- Input from outside the program is validated at the boundary; paths, commands and queries are never built by concatenating untrusted text.

### Project specifics

<Fill in from: the linter configuration, the largest packages, and the contributing guide: idioms, naming, error and output handling that a linter cannot enforce.>
