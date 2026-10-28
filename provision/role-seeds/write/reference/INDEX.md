# docs reference index

What the docs role follows, on top of `shared/INDEX.md`. Paths are relative to
`roles/docs/`. The store is read-only for agents: never write here. Propose changes
in your final report under "Reference updates proposed"; the coordinator applies them.

| Path | Purpose | Load |
|---|---|---|
| rules/rules.md | must / must-not rules for documentation work | always |
| workflow/workflow.md | producing, checking and delivering a document; definition of done | when starting a document |
| workflow/source-map.md | where the facts live in the project | when researching |
| writing/conventions.md | structure, voice and formatting of documents | when writing or reviewing |
| design/styling.md | visual design of rendered documents | when restyling or rendering |
| knowledge/facts.md | checked project behaviour worth keeping straight | when describing behaviour |
| user/preferences.md | what the maintainer wants and how | when choosing the format, tone or scope of a document |

Memory for this role (history, open items) is in the memory store under
`roles/docs/project/`: check `open-items.md` before starting.
