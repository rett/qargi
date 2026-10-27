# Review checklist

Kind: review
Applies to: any
Sources: qargi seed

## Contents

- **Design:** does the approach fit the code around it; is there a simpler one; is anything speculative or unused; is it readable by the next maintainer.
- **Correctness:** off-by-one and boundary values; empty and nil input; every error path; partial failure and the state it leaves; idempotency and re-runs; ordering and concurrency; resource leaks; time and locale assumptions.
- **Tests:** does a test fail without the change; does it assert behaviour rather than that code ran; are error paths covered; was a test weakened, skipped or deleted; are fixtures changed only where behaviour changed.
- **Scope:** every touched file is inside SCOPE and needed; no drive-by refactor, rename, formatting or dependency.
- **Security and privacy:** injection through built commands, paths or queries; path traversal; secrets in arguments, logs, fixtures or messages; private names, real addresses or device output; modes of files created.
- **Compatibility:** changed output formats, flags, file formats or stored data; migration for existing installations.
- **Docs and changelog:** every user-visible change has both, in the same commit.
- **Commits:** one change per commit, a body that says why, no trailer the project forbids, each commit builds alone where feasible.

### Project specifics

<Fill in from: past reviews on this project. Findings that recur, one per bullet, each with its source.>
