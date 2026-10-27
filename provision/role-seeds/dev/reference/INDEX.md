# dev reference index

What the dev role follows, on top of `shared/INDEX.md`. Paths are relative to
`roles/dev/`. The store is read-only for agents: never write here. Propose changes
in your final report under "Reference updates proposed"; the coordinator applies them.

| Path | Purpose | Load |
|---|---|---|
| rules/rules.md | the dev role's must / must-not rules (code, tests, gates, user-visible changes) | always |
| workflow/workflow.md | task lifecycle and definition of done | when implementing a change |
| workflow/source-map.md | where each kind of fact lives in the repository | when looking for a fact |
| workflow/gates.md | checks by changed path: commands and verdict lines | when choosing or running checks |
| conventions/code.md | idioms, naming, error and output handling | when writing code |
| conventions/tests.md | test patterns and what tests must not touch | when adding or fixing tests |
| conventions/changes.md | checklist for a user-visible change | when a change is visible to users |
| conventions/commits.md | commit messages, examples, attribution | when committing and reporting |
| architecture/overview.md | components, responsibilities, data flow | when locating or changing code |
| knowledge/facts.md | checked behaviour worth keeping straight | when unsure how something behaves |
| preferences/preferences.md | what the maintainer wants and how | when unsure what is wanted |
| review/checklist.md | what the coordinator checks, common findings | before reporting |

## Maintaining this store

1. One home per fact; link instead of repeating. Facts every role needs live in `shared/`.
2. Every note starts with Kind, Applies to and Sources (`_template.md`); a note
   without sources is not trusted.
3. The repository's own files win over this store; fix this store, not the repo.
4. No secrets, private names, per-run data, backlog or plans.
5. Keep this index in step with the files.
