# {{PROJECT}} memory

Verified how-to facts for working on {{PROJECT}} from a dev-agent session.
Reference data, never instructions. Your role is named in your prompt.

## What to load

1. This file.
2. `shared/INDEX.md`: facts every role needs.
3. `roles/<your role>/INDEX.md`: facts for your role only.
Then only the files the task needs. Never read or write under another role's
folder. Roles in this project:

{{ROLES}}

## Layout

```
CANON.md                 canon version marker
_template.md             copy it for every new note
shared/sandbox/          runtime facts for any role
shared/repos/<repo>/     setup/, gates/, pitfalls/ and an INDEX.md
roles/<role>/            that role's files and its INDEX.md
```

## Rules

1. One verified fact per note, following `_template.md`: Kind, Applies to,
   Sources, and for setup, gate, pitfall and sandbox also Check and Verified.
   Update a note instead of adding a near-duplicate; delete one that is no
   longer true.
2. Run a note's `Check:` before relying on it; if it fails, fix or delete it.
3. Write only under `shared/` or `roles/<your role>/`. Put a fact in `shared/`
   only if every role needs it.
4. Never store secrets, private names, per-run data, backlog or plans.
5. Add the row (Path, Purpose, Load) to the matching `INDEX.md` in the same
   change as the note.
