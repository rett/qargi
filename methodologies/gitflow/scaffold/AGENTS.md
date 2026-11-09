# {{project}}

Instructions for coding agents and contributors. `README.md` describes the project and `CONTRIBUTING.md` its workflow.

## Development environment

This project has no tool-specific setup file. The targets below are the specification; any agent or person sets a checkout up with them.

- Prerequisites: git, {{runner}}, and the toolchain versions this project pins in its own files (a language's version file, `.tool-versions` or `mise.toml`). Do not copy those versions anywhere else.
- Install or update everything: `{{bootstrap_command}}`. It is idempotent. A line that needs root starts with `sudo` and says what it changes. Preview without changes: `{{dry_run_command}}`.
- Verify a checkout: `{{doctor_command}}`. It prints one line per item and exits non-zero when something is missing: a line starting `missing`, `fail` or `error` is a problem, a line starting `expected` is a known failure that is accepted. Run it before the tests and after pulling.
{{^gates}}
- Tests: `{{test_command}}`.
{{/gates}}
{{#gates}}
- Tests: the declared gates, run in order, stopping at the first failure:
{{#gate}}
  - `{{gate_name}}` ({{gate_tier}}): `{{gate_command}}`
{{/gate}}
{{/gates}}
- Never run the bootstrap on a checkout you have not reviewed; read the preview first.
- When the project needs a new tool, add it to the bootstrap, to the doctor and to this list in the same change.
