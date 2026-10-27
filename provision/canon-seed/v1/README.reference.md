# {{PROJECT}} reference

Curated rules, workflow, conventions and architecture for {{PROJECT}}. Read-only:
never write here; propose changes in your report. Your role is named in your
prompt.

## What to load

1. This file.
2. `shared/INDEX.md`: what every role follows.
3. `roles/<your role>/INDEX.md`: what your role follows.
Then only what the task needs. Never read another role's folder. Roles in this
project:

{{ROLES}}

## Layout

```
CANON.md                 canon version marker
shared/                  folders named for their scope (rules/, workflow/, ...) for every role
roles/<role>/            the same for that role, its INDEX.md, tools/
```

## Rules

1. One home per fact; every entry carries its source, for example
   `(source: docs/x.md@abc1234)`. A file without sources is not trusted.
2. The repository's own files win over this store.
3. No secrets, private names, per-run data, backlog or plans.
4. The coordinator curates; `qargi canon promote` moves a role's file to
   `shared/` when every role needs it.
