# Example profile: myproject, a Go CLI project

Copy to `~/.qargi/config/profiles/<repository-name>.md` (outside
the repository) and adapt. The coordinator inlines it in each task.

## Rules
- Skip the repository's "start with the backlog and release plan" line; read
  `docs/plans/` only if TASK names it.
- No private names (hosts, addresses, users, home paths, domains) in files or
  commit messages. Examples use the documented example table.
- A user-visible change needs a numbered CHANGELOG item (next free number on
  BASE; the coordinator renumbers) and updates to the man page and the
  matching docs page in the same change.
- Never act against a production host; no device credentials.

## Gates by path
- `internal/**`: gofmt, go vet, `make gate-go` (final `GATE-GO PASS` line
  only; detached run).
- `docs/`, `man/`, `README.md`: `make lint`.
- shell, config: `make lint-sh` plus the matching bats file after `make build`.
- Always: `make lint`.
- Coordinator-only (report "not run"): diff corpus, container matrix.

## Review (coordinator)
- Run the private-name scrub (`tests/tools/no-private.sh`) on the patches.
- Rebuild generated man blocks with `make man`.
- Code under `internal/**` also gets a second-model review before applying.
- Renumber the CHANGELOG item; ask before any push.
- Apply the agent's commits as separate, change-specific commits; never squash.
