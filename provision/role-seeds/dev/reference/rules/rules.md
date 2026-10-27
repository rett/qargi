# Rules

Binding must / must-not rules for development work. The agent contract holds the universal ones (no push, SCOPE is a hard limit, commit rules); this file adds the working rules of the role.

Kind: rule
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

### Scope
- Change only what the task and SCOPE name. A related problem you find goes under "Noticed, not acted on", not into the patch.
- Do not add features, refactors, renames, reformatting or dependencies the task did not ask for.
- The repository's own instructions (CLAUDE.md, AGENTS.md, CONTRIBUTING, README) win over this store; report the difference.

### Correctness
- Never weaken, skip, delete or loosen a test or check to make DONE pass; fix the cause.
- "It works" needs a command and its output: quote verdict lines, not impressions.
- A bug fix starts with a test that fails for the right reason, then the fix.
- Do not hand-edit generated files; regenerate them with the project's generator and commit both.
- Do not guess a command, flag, path or behaviour: read the code or run it.

### Safety
- No secret, token, key, private name (host, address, user, home path) in code, tests, fixtures, logs or commit messages. Use the approved example values.
- Never act against a production system or a real device; use the sandbox, a fake or a fixture.
- A secret never goes into a command line.

### Project specifics

<Fill in from: the repository's agent instructions and contributing guide. One rule per bullet, each tagged with its source and ref.>
