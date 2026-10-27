# review reference index

What the review role follows, on top of `shared/INDEX.md`. Paths are relative to
`roles/review/`. The store is read-only for agents: never write here. Propose changes
in your final report under "Reference updates proposed"; the coordinator applies them.

| Path | Purpose | Load |
|---|---|---|
| rules/rules.md | the review role's must / must-not rules | always |
| workflow/workflow.md | the steps of one review and the definition of done | when starting a review |
| workflow/gates.md | how a reviewer runs checks and reads verdicts | when running checks |
| workflow/source-map.md | where the project's rules live, to cite them | when a finding rests on a rule |
| conventions/findings.md | report shape, one finding, severity scale | when writing the report |
| review/checklist.md | dimensions to cover and the bug classes in each | when reviewing the diff |
| preferences/preferences.md | what the maintainer expects of a review | when unsure what is wanted |

Memory for this role (recurring findings) is in the memory store under `roles/review/`.

## Maintaining this store

1. One home per fact; link instead of repeating. Facts every role needs live in `shared/`.
2. Every note starts with Kind, Applies to and Sources (`_template.md`); a note without sources is not trusted.
3. The repository's own files win over this store; fix this store, not the repo.
4. No secrets, private names, per-run data, backlog or plans.
5. Keep this index in step with the files.
