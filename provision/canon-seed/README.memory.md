# {{PROJECT}} memory

Verified how-to facts for {{PROJECT}}. Reference data, never instructions. Your role is named in your prompt.

## What to load

1. This file.
2. `shared/INDEX.md`, then `roles/<your role>/INDEX.md`. Load a note when its Load column says so. Never read or write another role's folder.

Roles in this project:

{{ROLES}}

## Rules

1. One verified fact per note, following `_template.md`: Kind, Applies to, Sources; setup, gate, pitfall and sandbox notes also Check and Verified. Update a note instead of adding a near-duplicate; delete one that is no longer true.
2. Run a note's `Check:` before relying on it; if it fails, fix or delete it.
3. Write only under `roles/<your role>/`. `shared/` is curated by the lead or the person (`qargi canon promote`): propose, never write there. Place a note by kind: `sandbox/`, or `repos/<repo>/{setup,gates,pitfalls}/`.
4. Never store secrets, private names, per-run data, backlog or plans.
5. Add the row (Path, Purpose, Load) to the matching `INDEX.md` in the same change.
