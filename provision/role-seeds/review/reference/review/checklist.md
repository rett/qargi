# Review checklist

The dimensions to cover in every review and the bug classes to look for in each.

Kind: review
Applies to: any
Sources: the dev-agent baseline for this role (agent contract and common engineering practice); the project's own files override it

## Contents

- **Correctness:** off-by-one and boundary values; empty and nil input; every error path; partial failure and what state it leaves; idempotency and re-runs; ordering and concurrency; resource leaks; time and locale assumptions.
- **Tests:** does a test fail without the change; does it assert behaviour rather than that code ran; are error paths covered; was any test weakened, skipped or deleted; are fixtures and goldens changed only where behaviour changed.
- **Scope:** every touched file is inside SCOPE and needed; no drive-by refactor, rename or formatting; no unrelated dependency.
- **Security and privacy:** injection through built commands, paths or queries; path traversal; secrets in arguments, logs, fixtures or messages; private names, real addresses or device output; permissions and modes of files created.
- **Compatibility:** changed output formats, flags, file formats or stored data; migration for existing installations; behaviour on the oldest supported version.
- **Docs and changelog:** every user-visible change has its changelog entry and its documentation, in the same commit.
- **Commits:** one change per commit, a message body that says why, no trailer the project forbids, each commit builds alone where feasible, nothing squashed that should be separate.

### Project specifics

<Fill in from: past reviews on this project. Findings that recur, one per bullet, each with its source.>
