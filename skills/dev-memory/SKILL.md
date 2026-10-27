---
name: dev-memory
description: Check, reconcile and curate the two dev-agent memory stores of a project: the agent-written recipes store (<project>-memory) and the curated, read-only reference store (<project>-reference), both laid out by the versioned canon (shared/ plus roles/<role>/). Lint, plan/apply a migration, import a foreign store, seed a role, promote a file to shared, audit cross-role writes.
argument-hint: check|plan|apply|import|seed-role|promote|audit PROJECT ... | lint STORE_ID
---

# /dev-memory

**Memory store** (`<project>-memory`, agents read-write): verified how-to facts and role
history. **Reference store** (`<project>-reference`, agents read-only): curated rules,
workflow, conventions and architecture in folders named for their scope (no numbered
prefixes). Agents propose reference changes in their report; the coordinator applies them
(write with `ant beta:memory-stores:memories`).

Both stores use one note format (canon 2): `# Title`, then `Kind`, `Applies to`, `Sources`,
and for the runnable kinds (`setup gate pitfall sandbox`) also `Check` and `Verified`; an
index row (`| Path | Purpose | Load |`) in the same change. No secrets, private names,
per-run data, backlog or plans. `_template.md` in each store is the shape to copy.

Stores are created and seeded by `/dev-provision`, which uses the canon. `dev-agent canon
check` (also run by `dev-agent memory lint STORE_ID`) verifies the whole of it and exits 1
on any FAIL.

## The canon and the reconciler

Both stores follow the versioned canon in `canon/CANON.md` (version 2):
`/CANON.md` marker, `/README.md`, `shared/` for every role and `roles/<role>/`
(with its `INDEX.md`) per role. An agent loads the README, `shared/INDEX.md` and
only its own role's index, never another role's folder.

| Verb | Command | Notes |
|---|---|---|
| check | `dev-agent canon check PROJECT [--kind K]` | Conformance and version report; exit 1 on any FAIL. |
| seed-role | `dev-agent canon seed-role PROJECT --role R --approved "..."` | Writes the role's skeleton (`provision/role-seeds/R/`) into the stores without overwriting. |
| plan | `dev-agent canon plan PROJECT [--kind K] [--default-role R]` | Every step needed to reach the current canon, from whichever version the store is at. Changes nothing. |
| apply | `dev-agent canon apply PROJECT [--kind K] --approved "..."` | Runs the plan: renames keep identity and history, conflicts go to `/_conflicts/<date>/`, the marker is written last, a re-run resumes. Show the plan first. |
| import | `dev-agent canon import PROJECT --from STORE --role R --map docs-v0 [--approved "..."]` | Merges a foreign store (the old documentation store layout) into `roles/<R>/` with relevant folder names (numbered prefixes removed, references rewritten); curated parts into the reference store, history into the memory store. The source is only read. |
| promote | `dev-agent canon promote PROJECT --kind K --path /roles/R/... --approved "..."` | Moves a role's file to `shared/` when every role needs it. |
| audit | `dev-agent canon audit PROJECT` | Read-only: reports a session of one role writing under another role's folder. |

`dev-agent memory lint` runs `canon check` (structure, note format, indexes and hygiene).
A store at an older version gets a plan that only adds what a note lacks (`Kind`, `Applies to`,
`Sources` from its folder and `Verified:` line) and never edits a body.
A new canon version means a new migration; see `canon/CANON.md` § Changing the canon.
