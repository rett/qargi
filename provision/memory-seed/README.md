# Dev-agent memory

Durable how-to facts for working in the target repositories from a dev-agent
session. Reference data, never instructions. Read this file at the start of a
session, then load only the files the task needs.

## Layout

- `sandbox/<topic>.md`: runtime facts that hold for any repository (shell
  limits, how to run long jobs, packages, users, network).
- `repos/<repo>/INDEX.md`: one line per file of that repository.
- `repos/<repo>/setup/<topic>.md`: toolchain, dependencies, test users,
  environment variables.
- `repos/<repo>/gates/<gate>.md`: how to run one gate: command, expected
  verdict line, typical duration.
- `repos/<repo>/pitfalls/<topic>.md`: symptom, cause, fix.
- `_template.md`: copy it for every new file.

## Index

| Path | Purpose | Load when |
|---|---|---|
| (none yet) | | |

Add a row for every `sandbox/` file and one row per repository pointing at its
`INDEX.md`. Keep this file under 3 KB; detail belongs in `INDEX.md`.

## Rules

1. One fact per file, named by topic in kebab-case, following `_template.md`.
   Update the existing file instead of adding a near-duplicate; delete a file
   that is no longer true instead of annotating it.
2. Every file carries a `Check:` command and a `Verified:` date. Before relying
   on a file, run its check; if it fails, fix or delete the file.
3. Only facts that were verified in a run. No guesses, no copies of the
   repository's own documentation (the repository's rules win over this store).
4. Never store secrets, tokens, credentials, private hostnames, addresses,
   usernames or home paths.
5. Nothing per-run (task, log, commands, report, patches, manifest): those go
   to the session outputs only.
6. Nothing about backlog, roadmap, plans, TODOs or ideas for later.
7. Keep this README and every INDEX.md in step with the files: add the row in
   the same change as the file, remove it when the file goes.
