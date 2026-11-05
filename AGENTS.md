# Agent instructions

Instructions for coding agents and contributors. `README.md` describes the project and `CONTRIBUTING.md` its workflow.

## Development environment

This project has no tool-specific setup file. The targets below are the specification; any agent or person sets a checkout up with them.

- Prerequisites: git, make, and the tools the bootstrap installs: bash, git, jq, shellcheck and python3 (3.11 or newer; the standard library is all the code uses).
- Install or update everything: `make bootstrap`. It is idempotent and installs those tools with the system package manager of Arch, Debian or Ubuntu, and Fedora; on another distribution it says what to install by hand. The one line that needs root starts with `sudo` and installs system packages, nothing else. Preview without changes: `make -n bootstrap`.
- Verify a checkout: `make doctor`. It prints one line per tool with its version and exits non-zero when one is missing or too old: a line starting `missing`, `fail` or `error` is a problem, a line starting `expected` is a known failure that is accepted. Run it before the tests and after pulling.
- Tests: run the suite against a scratch home, never against live data: `T=$(mktemp -d -p /dev/shm); mkdir $T/h; HOME=$T/h bash tests/run.sh` (all CPUs; `--tier fast` is the quick run of about a minute, `-j 1` the serial one; `tests/suite.txt` lists the steps). While working on a task run only the check that covers the change (for example `python3 tests/test_env.py` or `bash tests/test_project.sh`). Shell files must pass `shellcheck -x -S warning`.
- Never run the bootstrap on a checkout you have not reviewed; read the preview first.
- When the project needs a new tool, add it to the bootstrap, to the doctor and to this list in the same change.
