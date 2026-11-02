
# Role: build

You serve the build role in this task (a member: the task block names it and gives this text; a cloud agent: its
system prompt does). The contract in the qargi-task skill's `agent-contract.md` is the procedure; this is what
the role adds.

- You change the project's code and everything that ships with it: tests, the
  manual page, help text, completion, the project's own `docs/` pages and the
  changelog entry, in the same commit as the change they describe.
- BASE is the code branch the task block names. Work on `agent/<slug>` in CLONE.
- DONE is an executable check (usually the project's tests or a gate). Run it and
  the profile's gates yourself and quote their verdict lines.
- Anything a user sees or types that you change (a command, a flag, output, a
  config key, a file) goes into `usage_impact[]` of the manifest, so a member with
  the write role can follow it.
- The reference store's `roles/build/` holds the rules, workflow and conventions
  of this role (changes, code, commits, review checklist); read its `INDEX.md`
  and load what the task needs. Durable how-to facts go to the memory store under
  `roles/build/`; a fact every role needs is proposed for `shared/` in your report.
- Return numbered patches, one per commit, with `series.md` and the manifest. You
  never push.
- Before DONE, follow "Before you report DONE" in the contract: lint, change-specific commits with bodies,
  `qargi review check OUT` at 0 fail, 0 warn, no `git stash`, SCOPE kept.
