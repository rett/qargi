# Development reference: index

Curated reference for developing this project: rules, workflow, conventions,
architecture, checked facts, maintainer preferences and review criteria.
Read this index at the start of every session, then load only the files the
task needs. The store is read-only for agents: never write here. Propose
changes in your final report under "Reference updates proposed"; the
coordinator applies them.

## Folder map

```
README.md                        this index (always read first)
01-rules/rules.md                must / must-not rules              [ALWAYS LOAD]
02-workflow/workflow.md          task lifecycle and definition of done
02-workflow/source-map.md        where each kind of fact lives in the repository
02-workflow/gates.md             checks by path: commands, verdict lines
03-conventions/code.md           idioms, naming, error and output handling
03-conventions/tests.md          test patterns and what tests must not touch
03-conventions/changes.md        checklist for a user-visible change
03-conventions/commits.md        commit messages, examples, attribution
04-architecture/overview.md      components, responsibilities, data flow
05-knowledge/facts.md            checked behaviour worth keeping straight
06-preferences/preferences.md    what the maintainer wants and how
07-review/checklist.md           what the coordinator checks, common findings
```

Numbered prefixes give the load order, most binding first.

## What to load, by task

| Task | Load |
|---|---|
| Any task | `01-rules/rules.md` |
| Implement a change | `02-workflow/workflow.md`, `03-conventions/code.md`, `03-conventions/changes.md`, `04-architecture/overview.md` |
| Add or fix tests | `03-conventions/tests.md`, `02-workflow/gates.md` |
| Find where something lives | `02-workflow/source-map.md`, `04-architecture/overview.md` |
| Prepare commits and the report | `03-conventions/commits.md`, `07-review/checklist.md` |
| Unsure what the maintainer wants | `06-preferences/preferences.md`, `05-knowledge/facts.md` |

## Maintaining this store

1. One home per fact; link instead of repeating.
2. Every entry carries its source, for example `(source: docs/x.md@abc1234)`
   or `(maintainer, 2026-10-27)`. A file without sources is not trusted.
3. The repository's own files win over this store; fix this store, not the repo.
4. No secrets, private names, per-run data, backlog or plans.
5. Keep this index in step with the files.
