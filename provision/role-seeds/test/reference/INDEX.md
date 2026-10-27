# test reference index

What the test role follows, on top of `shared/INDEX.md`. Paths are relative to
`roles/test/`. The store is read-only for agents: never write here. Propose changes
in your final report under "Reference updates proposed"; the coordinator applies them.

| Path | Purpose | Load |
|---|---|---|
| rules/rules.md | the test role's must / must-not rules | always |
| workflow/workflow.md | the steps of one test task, triaging a flaky test, definition of done | when starting a task |
| workflow/gates.md | how to run the suite and read its verdicts | when running tests |
| workflow/source-map.md | where test facts live in the repository | when looking for helpers or fixtures |
| conventions/tests.md | how tests are named, structured and isolated | when writing a test |
| review/checklist.md | what to check on your own tests before reporting | before reporting |
| preferences/preferences.md | what the maintainer expects of tests | when unsure what is wanted |

Memory for this role (known flaky tests) is in the memory store under `roles/test/`.

## Maintaining this store

1. One home per fact; link instead of repeating. Facts every role needs live in `shared/`.
2. Every note starts with Kind, Applies to and Sources (`_template.md`); a note without sources is not trusted.
3. The repository's own files win over this store; fix this store, not the repo.
4. No secrets, private names, per-run data, backlog or plans.
5. Keep this index in step with the files.
