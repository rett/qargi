# dev reference index

Curated reference for developing this project: rules, workflow, conventions,
architecture, checked facts, maintainer preferences and review criteria.
Read this index at the start of every session, then load only the files the
task needs. The store is read-only for agents: never write here. Propose
changes in your final report under "Reference updates proposed"; the
coordinator applies them.

## Folder map

```
README.md                        this index (always read first)
rules/rules.md                must / must-not rules              [ALWAYS LOAD]
workflow/workflow.md          task lifecycle and definition of done
workflow/source-map.md        where each kind of fact lives in the repository
workflow/gates.md             checks by path: commands, verdict lines
conventions/code.md           idioms, naming, error and output handling
conventions/tests.md          test patterns and what tests must not touch
conventions/changes.md        checklist for a user-visible change
conventions/commits.md        commit messages, examples, attribution
architecture/overview.md      components, responsibilities, data flow
knowledge/facts.md            checked behaviour worth keeping straight
preferences/preferences.md    what the maintainer wants and how
review/checklist.md           what the coordinator checks, common findings
```

Load order and what is binding are stated in the Load column and the table below, not in folder names.

## What to load, by task

| Task | Load |
|---|---|
| Any task | `rules/rules.md` |
| Implement a change | `workflow/workflow.md`, `conventions/code.md`, `conventions/changes.md`, `architecture/overview.md` |
| Add or fix tests | `conventions/tests.md`, `workflow/gates.md` |
| Find where something lives | `workflow/source-map.md`, `architecture/overview.md` |
| Prepare commits and the report | `conventions/commits.md`, `review/checklist.md` |
| Unsure what the maintainer wants | `preferences/preferences.md`, `knowledge/facts.md` |

## Maintaining this store

1. One home per fact; link instead of repeating.
2. Every entry carries its source, for example `(source: docs/x.md@abc1234)`
   or `(maintainer, 2026-10-27)`. A file without sources is not trusted.
3. The repository's own files win over this store; fix this store, not the repo.
4. No secrets, private names, per-run data, backlog or plans.
5. Keep this index in step with the files.
