---
name: qargi-build
description: The build ability of a qargi member - change the code of a project (with its tests, manual page, help, completion and changelog) for one task in your own clone and return the series as patches. Load it when a qargi task block says ABILITY build.
---

# Ability: build

You serve the build ability in this task (a member: the task block names it; a cloud agent: its role). The contract in
the qargi-task skill's `agent-contract.md` is the procedure; this is what the
ability adds.

- You change the project's code and everything that ships with it: tests, the
  manual page, help text, completion, the project's own `docs/` pages and the
  changelog entry, in the same commit as the change they describe.
- BASE is the code branch the task block names. Work on `agent/<slug>` in CLONE.
- DONE is an executable check (usually the project's tests or a gate). Run it and
  the profile's gates yourself and quote their verdict lines.
- Anything a user sees or types that you change (a command, a flag, output, a
  config key, a file) goes into `usage_impact[]` of the manifest, so a member with
  the write ability can follow it.
- The reference store's `roles/build/` holds the rules, workflow and conventions
  of this ability (changes, code, commits, review checklist); read its `INDEX.md`
  and load what the task needs. Durable how-to facts go to the memory store under
  `roles/build/`; a fact every role needs is proposed for `shared/` in your report.
- Return numbered patches, one per commit, with `series.md` and the manifest. You
  never push.
