---
name: dev-memory
description: Seed and lint the two dev-agent memory stores: the agent-written recipes store (layered how-to facts with Check and Verified lines) and the curated, read-only development reference store (numbered folders of rules, workflow, conventions, architecture). Also covers migrating a flat store.
argument-hint: seed|seed-reference|lint STORE_ID [--kind recipes|reference] [--repo NAME]
---

# /dev-memory

**Recipes store** (`<NAME>-memory`, agent read-write): `README.md` index
(under 3 KB), `sandbox/<topic>.md`, `repos/<repo>/{INDEX.md,setup,gates,pitfalls}/`
and `_template.md`. One verified fact per file with `Kind`, `Applies to`,
`Check`, `Verified`. No secrets, per-run data, backlog or plans. Agents load
the README at session start and the rest on demand.

**Reference store** (`<NAME>-reference`, agent read-only): numbered folders
`01-rules` … `07-review` plus a README with a "load by task" table. Every
statement carries a source tag. Agents propose changes in their report; the
coordinator applies them (write with `ant beta:memory-stores:memories`).

| Verb | Command | Notes |
|---|---|---|
| seed | `dev-agent memory seed STORE_ID [--repo NAME]` | README, `_template.md` and `repos/NAME/INDEX.md`; never overwrites. |
| seed-reference | `dev-agent memory seed-reference STORE_ID` | The reference skeleton; never overwrites. |
| lint | `dev-agent memory lint STORE_ID [--kind recipes\|reference]` | Read-only: layout, index coverage, required fields, size, secrets, staleness. Exit 1 on any FAIL. |

Migrating a flat store: seed, replace the old README, have the cloud agent
move each file to its new place re-running each `Check` (cheap ones; expensive
ones keep their date marked "not re-run"), then lint and close the session with
`dev-agent close SID --no-outputs`.
