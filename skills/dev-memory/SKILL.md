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

## The canon and the reconciler

Both stores follow the versioned canon in `canon/CANON.md` (current version 2):
`/CANON.md` marker, `/README.md`, `shared/` for every role and `roles/<role>/`
(with its `INDEX.md`) per role. An agent loads the README, `shared/INDEX.md` and
only its own role's index, never another role's folder.

| Verb | Command | Notes |
|---|---|---|
| check | `dev-agent canon check PROJECT [--kind K]` | Conformance and version report; exit 1 on any FAIL. |
| plan | `dev-agent canon plan PROJECT [--kind K] [--default-role R]` | Every step needed to reach the current canon, from whichever version the store is at. Changes nothing. |
| apply | `dev-agent canon apply PROJECT [--kind K] --approved "..."` | Runs the plan: renames keep identity and history, conflicts go to `/_conflicts/<date>/`, the marker is written last, a re-run resumes. Show the plan first. |
| import | `dev-agent canon import PROJECT --from STORE --role R --map docs-v0 [--approved "..."]` | Merges a foreign store (the old documentation store layout) into `roles/<R>/`; curated parts into the reference store, history into the memory store. The source is only read. |
| promote | `dev-agent canon promote PROJECT --kind K --path /roles/R/... --approved "..."` | Moves a role's file to `shared/` when every role needs it. |
| audit | `dev-agent canon audit PROJECT` | Read-only: reports a session of one role writing under another role's folder. |

`dev-agent memory lint` hands canon-2 stores to `canon check`. A new canon
version means a new migration; see `canon/CANON.md` § Changing the canon.

Migrating a flat store (pre-canon): seed, replace the old README, have the cloud agent
move each file to its new place re-running each `Check` (cheap ones; expensive
ones keep their date marked "not re-run"), then lint and close the session with
`dev-agent close SID --no-outputs`.
