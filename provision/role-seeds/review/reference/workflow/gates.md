# Gates for review

How a reviewer runs checks.

Kind: workflow
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- Use a scratch checkout of BASE with the series applied; never the author's clone.
- Run the same gates the profile names for the touched paths, and DONE, exactly as written.
- Quote each verdict line verbatim; a check with no verdict line is a failure.
- If a gate fails on BASE alone, say so, and distinguish it from a failure the series causes.
- Record how long the long gates took and any setup they needed in the memory store as a recipe.

### Project specifics

<Fill in from: the profile and the project's CI configuration.>
