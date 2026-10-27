# Code conventions

Kind: convention
Applies to: any
Sources: dev-agent seed

## Contents

- Match the surrounding code: naming, structure, error handling, comment density and idiom. When in doubt, copy the nearest good example.
- Keep the diff minimal: no drive-by formatting, import reordering or renames.
- Handle every error the way the neighbours do; never discard one silently.
- Comment the why, not the what; delete comments that restate the code. No dead or commented-out code, debug output, or TODO without an owner.
- Names say what a thing is for; a function does one thing; a new dependency needs a reason in the commit message.
- Prefer the simplest design that meets the task; no speculative generality or options nobody asked for.
- Validate input at the boundary; never build commands, paths or queries by concatenating untrusted text; create files with the least permission they need; never log a secret.

### Project specifics

<Fill in from: the linter configuration and the contributing guide: idioms and naming a linter cannot enforce.>
