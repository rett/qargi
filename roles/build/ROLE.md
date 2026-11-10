
# Role: build

- You change the project's code and everything that ships with it: tests, the
  manual page, help text, completion, the project's own `docs/` pages and the
  changelog entry, in the same commit as the change they describe.
- BASE is the code branch the task block names. Work on `agent/<slug>` in CLONE.
- DONE is an executable check (usually the project's tests or a gate). Run it and
  the profile's gates yourself and quote their verdict lines.
- Anything a user sees or types that you change (a command, a flag, output, a
  config key, a file) goes into `usage_impact[]` of the manifest, so a member with
  the write role can follow it.
- If the task block has a MEMORY section or a store is mounted, read the store's `roles/build/INDEX.md` first and
  load what the task needs.
